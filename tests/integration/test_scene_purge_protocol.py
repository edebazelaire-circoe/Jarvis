"""Purge des objets archivés de bout en bout par les routes de Core (vrai Core, vraie base, vrai projecteur).

`POST /v1/scene/archived/purge-plan` puis `POST /v1/scene/archived/purge`
(jeton + `confirmed: true`) : la scène relue par `GET /v1/scene/snapshot`
n'a plus d'objet archivé, la commande suivante passe, la sauvegarde est là,
et un redémarrage de Core sur la même base garde le compte à zéro. Une étoile
dont le travail est encore suivi par l'état de travail de Core garde sa
pierre tombale (câblage de production `v2_app`).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import pytest

from jarvis.domain.work_state import WorkObservation, WorkStatus
from tests.integration.test_scene_transport import CoreProcess, artifact, snapshot_of, until

GRACE_S = 0.2
PLAN = "/v1/scene/archived/purge-plan"
PURGE = "/v1/scene/archived/purge"


@pytest.fixture
async def core(tmp_path):
    process = CoreProcess(tmp_path, scene_restart_grace_s=GRACE_S)
    await process.start()
    try:
        yield process
    finally:
        await process.stop()


async def command(core: CoreProcess, payload: dict) -> dict:
    status, body, _ = await core.request("POST", "/v1/scene/commands", json=payload)
    assert status == 200, body
    assert body["outcome"] == "applied", body
    return body


def scene_file(core: CoreProcess) -> Path:
    return core.data_root / "state" / "scene.sqlite3"


async def test_plan_then_confirm_purges_the_archive_over_http_and_survives_a_restart(core):
    for index in range(4):
        await command(core, artifact(f"art-{index}"))
    await command(core, artifact("keep"))
    for index in range(4):
        await command(core, {"schema_version": 1, "op": "archive", "actor": "user", "object_id": f"art-{index}"})
    before = await snapshot_of(core)
    assert len(before["snapshot"]["archived_ids"]) == 4
    await asyncio.sleep(GRACE_S + 0.1)

    status, plan, _ = await core.request("POST", PLAN, json={"schema_version": 1, "actor": "brain"})
    assert status == 200, plan
    assert plan["purgeable"] == {"archived_ids": 4, "history_rows": 4}
    assert plan["kept"]["archived_ids"] == 0
    assert plan["revision"] == before["revision"] and plan["confirmation"].startswith("spg_")
    # Le plan n'a rien écrit.
    assert (await snapshot_of(core))["revision"] == before["revision"]

    # Sans `confirmed: true`, rien ne part.
    status, body, _ = await core.request("POST", PURGE, json={"schema_version": 1, "actor": "brain",
                                                              "confirmation": plan["confirmation"], "confirmed": False})
    assert status == 400, body
    # L'acteur runtime n'a pas de route.
    status, body, _ = await core.request("POST", PURGE, json={"schema_version": 1, "actor": "runtime",
                                                              "confirmation": plan["confirmation"], "confirmed": True})
    assert status == 403 and body["error"]["code"] == "scene_actor_forbidden"
    status, body, _ = await core.request("POST", PURGE, json={"schema_version": 1, "actor": "brain",
                                                              "confirmation": "spg_1.00", "confirmed": True})
    assert status == 409 and body["error"]["code"] == "confirmation_required", body
    assert len((await snapshot_of(core))["snapshot"]["archived_ids"]) == 4

    status, done, _ = await core.request("POST", PURGE, json={"schema_version": 1, "actor": "brain",
                                                              "confirmation": plan["confirmation"], "confirmed": True})
    assert status == 200, done
    assert done["purged"] == {"archived_ids": 4, "history_rows": 4}
    backup = Path(done["backup_path"])
    assert backup.parent == scene_file(core).parent and backup.name.startswith("scene.sqlite3.purge-")
    conn = sqlite3.connect(f"{backup.as_uri()}?mode=ro", uri=True)
    try:
        assert conn.execute("SELECT COUNT(*) FROM scene_tombstones").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM scene_history").fetchone()[0] == 4
    finally:
        conn.close()

    after = await snapshot_of(core)
    assert after["snapshot"]["archived_ids"] == []
    assert after["revision"] == before["revision"] + 1 == done["revision"]
    assert after["snapshot"]["objects"] == before["snapshot"]["objects"]
    # Un client à l'ancienne révision est renvoyé à l'instantané, sans erreur.
    status, window, _ = await core.request("GET", "/v1/scene/patches", params={
        "scene_id": before["scene_id"], "epoch": before["epoch"], "after": str(before["revision"]), "wait_s": "0"})
    assert status == 200 and window["resync_required"] is True and window["revision"] == after["revision"]
    # La commande suivante passe.
    await command(core, artifact("after"))

    await core.stop()
    await core.start()
    reloaded = await snapshot_of(core)
    assert reloaded["snapshot"]["archived_ids"] == []
    assert {item["object_id"] for item in reloaded["snapshot"]["objects"]} == {"keep", "after"}


async def test_a_star_still_tracked_by_core_work_state_keeps_its_tombstone(core):
    app = core.core
    await app.work_state.observe(WorkObservation(source="claude", external_id="live-agent", status=WorkStatus.RUNNING,
                                                 observed_at=datetime.now(timezone.utc), kind="agent"))
    await until(lambda: app.scene._snapshot is not None and app.scene._snapshot.get_object("claude:live-agent") is not None)
    await command(core, artifact("note"))
    for object_id in ("claude:live-agent", "note"):
        await command(core, {"schema_version": 1, "op": "archive", "actor": "user", "object_id": object_id})
    await asyncio.sleep(GRACE_S + 0.1)

    status, plan, _ = await core.request("POST", PLAN, json={"schema_version": 1, "actor": "user"})
    assert status == 200, plan
    assert plan["purgeable"]["archived_ids"] == 1
    assert plan["kept"]["archived_ids"] == 1 and plan["kept"]["ids"] == ["claude:live-agent"]

    status, done, _ = await core.request("POST", PURGE, json={"schema_version": 1, "actor": "user",
                                                              "confirmation": plan["confirmation"], "confirmed": True})
    assert status == 200, done
    assert (await snapshot_of(core))["snapshot"]["archived_ids"] == ["claude:live-agent"]
    # Le travail se manifeste de nouveau : l'étoile ne revient pas.
    await app.work_state.observe(WorkObservation(source="claude", external_id="live-agent", status=WorkStatus.COMPLETED,
                                                 observed_at=datetime.now(timezone.utc), kind="agent"))
    await asyncio.sleep(0.3)
    objects = (await snapshot_of(core))["snapshot"]["objects"]
    assert all(item["object_id"] != "claude:live-agent" for item in objects)

"""Événements des fenêtres prefab (handoff jarvis-scene-window-prefab-foundation, Slice 04).

Vrai `SceneService` (SQLite) et vrai `PrefabService` sur dossiers temporaires ;
puis la pile réelle Core + Control Center pour les routes et le relais.
Contrat : `jarvis/core/prefab_events.py`, `docs/prefabs.md` › *Events*.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from jarvis.adapters.file_prefab_library import LIBRARY_DIR, FilePrefabLibrary
from jarvis.adapters.sqlite_scene import SQLiteSceneRepository
from jarvis.core.prefab_events import (
    EVENT_KIND, MAX_NOTIFY_DELIVERY, PrefabEventOutcome, PrefabEventService, PrefabEventsRateLimited,
)
from jarvis.core.prefab_service import PrefabService
from jarvis.core.scene_service import SceneService, SceneState
from jarvis.domain.scene import (
    Representation, SceneActor, SceneCommand, SceneGeometry, SceneObjectFields, SceneObjectKind, SceneOp,
    ScenePayload, ScenePrefabRef,
)
from tests.fakes.capture_stack import CaptureStack
from tests.fakes.prefabs import install_version


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None) -> None:
        self.events.append((kind, level, dict(data or {})))


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def create(object_id="win-1", data=None, prefab_id="test.counter", version=1) -> SceneCommand:
    return SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=SceneActor.BRAIN, object_id=object_id, fields=SceneObjectFields(
        kind=SceneObjectKind.WINDOW, category="note", representation=Representation.WINDOW,
        geometry=SceneGeometry(0, 0, 40, 24), payload=ScenePayload(title="Compteur", prefab=ScenePrefabRef(
            prefab_id, version, {}, {"count": 3} if data is None else data))))


def body(event="incremented", payload=None, basis=None, object_id="win-1", prefab=None, actor="user") -> dict:
    out = {"actor": actor, "object_id": object_id, "prefab": prefab or {"id": "test.counter", "version": 1},
           "event": event, "payload": {"count": 4} if payload is None else payload}
    if basis is not False:
        out["basis"] = {"count": 3} if basis is None else basis
    return out


@pytest.fixture
async def stack(tmp_path: Path):
    data = tmp_path / "data"
    install_version(data / LIBRARY_DIR, "test.counter")
    (tmp_path / "package").mkdir()
    catalog = PrefabService(FilePrefabLibrary(tmp_path / "package", data))
    scene = SceneService(SQLiteSceneRepository(tmp_path / "scene.sqlite3"), prefab_validator=catalog)
    assert (await scene.start()).state is SceneState.READY
    await scene.apply(create())
    recorder, clock = Recorder(), Clock()
    events = PrefabEventService(scene, catalog, diagnostics=recorder, clock=clock)
    yield scene, events, recorder, clock
    await scene.close()


async def data_of(scene, object_id="win-1") -> dict:
    return (await scene.snapshot()).get_object(object_id).payload.prefab.data


async def test_a_state_event_is_written_by_the_reducer_as_user(stack):
    scene, events, recorder, _ = stack
    result = await events.submit(body())
    assert result.outcome is PrefabEventOutcome.APPLIED and result.revision == 2
    assert await data_of(scene) == {"count": 4, "notes": "", "history": []}  # défauts du schéma complétés
    window = await scene.patches_since(1)
    [patch] = window.patches
    [op] = patch.ops
    assert op.object.payload.prefab.data["count"] == 4 and op.object.constraints.placed_by.value == "brain"
    [entry] = events.entries()
    assert entry.to_dict() | {"at": None} == {"seq": 1, "at": None, "object_id": "win-1", "prefab": "test.counter@1",
                                              "event": "incremented", "class": "state", "payload": {"count": 4},
                                              "outcome": "applied"}
    [(kind, level, data)] = [e for e in recorder.events if e[0] == EVENT_KIND]
    assert level == "info" and data["payload_keys"] == ["count"] and "payload" not in data
    # Rejouer le même clic avec l'ancienne basis : `stale`, rien d'écrit.
    again = await events.submit(body())
    assert again.outcome is PrefabEventOutcome.STALE and again.revision == 2 and again.to_dict()["reason"] == "stale"
    assert (await scene.snapshot()).revision == 2


@pytest.mark.parametrize("changes, reason, needle", [
    ({"payload": {"notes": "x"}, "basis": {"notes": ""}}, "invalid_event", "undeclared keys ['notes']"),
    ({"payload": {"count": -5}}, "invalid_event", "payload.count"),
    ({"basis": False}, "invalid_event", "basis must be an object"),
    ({"event": "nope"}, "undeclared_event", "event nope is not declared"),
    ({"prefab": {"id": "test.counter", "version": 2}}, "unknown_version", "no version 2"),
    ({"prefab": {"id": "test.other", "version": 1}}, "unknown_prefab", "no prefab test.other"),
    ({"object_id": "win-404"}, "object_mismatch", "is not on the scene"),
])
async def test_refusals_write_nothing(stack, changes, reason, needle):
    scene, events, _, _ = stack
    result = await events.submit(body(**changes))
    assert result.outcome is PrefabEventOutcome.REFUSED and result.reason == reason and needle in result.detail
    assert (await scene.snapshot()).revision == 1 and await data_of(scene) == {"count": 3, "notes": "", "history": []}
    assert events.entries()[-1].outcome is PrefabEventOutcome.REFUSED


async def test_a_window_showing_another_prefab_version_is_refused(stack, tmp_path):
    scene, events, _, _ = stack
    install_version(tmp_path / "data" / LIBRARY_DIR, "test.counter", 2)
    await scene.apply(create("win-2", version=2))
    result = await events.submit(body(object_id="win-2"))
    assert result.reason == "object_mismatch" and "shows test.counter@2, not test.counter@1" in result.detail


@pytest.mark.parametrize("bad", [
    {}, {"actor": "user"}, body(actor="brain"), {**body(), "extra": 1}, body(prefab={"id": "test.counter"}),
    {**body(), "object_id": 5}, {**body(), "event": ""}, [],
])
async def test_malformed_requests_are_value_errors(stack, bad):
    _, events, _, _ = stack
    with pytest.raises(ValueError):
        await events.submit(bad)
    assert events.entries() == ()


async def test_a_notify_is_recorded_not_written_and_delivered_once(stack):
    scene, events, _, _ = stack
    for start in range(10):
        result = await events.submit(body(event="reset_requested", payload={"from": start}, basis=False))
        assert result.outcome is PrefabEventOutcome.RECORDED
    refused = await events.submit(body(event="reset_requested", payload={"from": -1}, basis=False))
    assert refused.outcome is PrefabEventOutcome.REFUSED and refused.reason == "invalid_payload"
    assert (await scene.snapshot()).revision == 1
    first = events.take_undelivered_notify()
    assert len(first) == MAX_NOTIFY_DELIVERY and [e.payload["from"] for e in first] == list(range(8))
    second = events.take_undelivered_notify()
    assert [e.payload["from"] for e in second] == [8, 9]
    assert events.take_undelivered_notify() == ()
    assert first[0].payload_preview() == '{"from":0}'


async def test_the_ring_is_bounded_and_filterable(stack):
    _, events, _, _ = stack
    for _ in range(300):
        await events.submit(body(event="nope"))
        events._tokens = 30.0  # le débit n'est pas l'objet de ce test
    rows = events.entries(limit=50)
    assert len(rows) == 50 and rows[-1].seq == 300 and events.last_seq == 300
    assert len(events._ring) == 256 and events._ring[0].seq == 45
    assert [row.seq for row in events.entries(after=290)] == list(range(291, 301))
    assert events.entries(object_id="win-x") == ()


async def test_more_than_30_events_per_second_are_rate_limited(stack):
    _, events, recorder, clock = stack
    for _ in range(30):
        await events.submit(body(event="nope"))
    with pytest.raises(PrefabEventsRateLimited):
        await events.submit(body(event="nope"))
    assert len(events.entries(limit=50)) == 30
    clock.now += 0.1  # 3 jetons rendus
    await events.submit(body(event="nope"))
    kinds = [e[0] for e in recorder.events]
    assert kinds.count("core.prefab.event_rate_limited") == 2  # début et fin de rafale


async def test_the_basis_check_cannot_be_overtaken_r91(stack):
    """Deux clics concurrents sur la même basis : un seul écrit, l'autre est `stale` (R9.1)."""

    scene, events, _, _ = stack
    gate = asyncio.Event()
    original = scene._repository.commit

    async def slow_commit(*args):
        await gate.wait()
        return await original(*args)

    scene._repository.commit = slow_commit
    first = asyncio.ensure_future(events.submit(body(payload={"count": 10})))
    second = asyncio.ensure_future(events.submit(body(payload={"count": 20})))
    await asyncio.sleep(0.05)
    gate.set()
    outcomes = sorted(r.outcome.value for r in await asyncio.gather(first, second))
    assert outcomes == ["applied", "stale"]
    assert (await data_of(scene))["count"] == 10 and (await scene.snapshot()).revision == 2


async def test_a_written_key_absent_from_core_data_is_a_null_basis_f2(tmp_path):
    """Une instance dont les données n'ont pas la clé écrite (gardée avant A3) : la première écriture passe."""

    from jarvis.ports.prefabs import InstanceValidation

    class AsWritten:  # valide sans compléter : les données restent telles qu'écrites
        async def validate_instance(self, ref):
            return InstanceValidation(True, props=dict(ref.props), data=dict(ref.data))

    data = tmp_path / "data"
    install_version(data / LIBRARY_DIR, "test.counter")
    (tmp_path / "package").mkdir()
    catalog = PrefabService(FilePrefabLibrary(tmp_path / "package", data))
    scene = SceneService(SQLiteSceneRepository(tmp_path / "scene.sqlite3"), prefab_validator=AsWritten())
    await scene.start()
    await scene.apply(create())
    assert await data_of(scene) == {"count": 3}
    events = PrefabEventService(scene, catalog)
    # `null` posé par l'hôte pour une clé jamais envoyée, ou clé absente de la basis : même lecture.
    first = await events.submit(body(payload={"count": 4, "history": [{"delta": 1}]}, basis={"count": 3, "history": None}))
    assert first.outcome is PrefabEventOutcome.APPLIED, first
    await scene.apply(SceneCommand(op=SceneOp.PATCH_OBJECT, actor=SceneActor.BRAIN, object_id="win-1",
                                   fields=SceneObjectFields(payload=ScenePayload(title="Compteur", prefab=ScenePrefabRef(
                                       "test.counter", 1, {}, {"count": 4})))))
    second = await events.submit(body(payload={"count": 5, "history": []}, basis={"count": 4}))
    assert second.outcome is PrefabEventOutcome.APPLIED, second
    assert await data_of(scene) == {"count": 5, "notes": "", "history": []}
    await scene.close()


async def test_event_diagnostics_never_carry_values_f3(stack):
    _, events, recorder, _ = stack
    secret = "sk-SECRET-hunter2"
    state = await events.submit(body(payload={"count": secret}))
    notify = await events.submit(body(event="reset_requested", payload={"from": secret}, basis=False))
    assert state.reason == "invalid_event" and notify.reason == "invalid_payload"
    assert secret in state.detail  # la réponse au cadre garde sa précision
    logged = [data for kind, _, data in recorder.events if kind == EVENT_KIND]
    assert [row["paths"] for row in logged] == [["payload.count"], ["payload.from"]]
    assert all("detail" not in row for row in logged) and "hunter2" not in repr(recorder.events)


async def test_notify_keeps_8_kib_while_state_events_take_16(stack):
    from jarvis.core.prefab_events import _bounded_payload
    from jarvis.domain.prefab import EventClass

    _, events, _, _ = stack
    result = await events.submit(body(event="reset_requested", payload={"from": 1, "pad": "x" * 9000}, basis=False))
    assert result.reason == "invalid_payload" and "8192" in result.detail
    assert events.entries()[-1].payload is None
    state = {"items": ["y" * 100] * 120}  # ~12 Kio : gardé dans l'anneau pour un état, pas pour un notify
    assert _bounded_payload(state, EventClass.STATE) == state and _bounded_payload(state, EventClass.NOTIFY) is None
    assert _bounded_payload({"x": "z" * 17000}, EventClass.STATE) is None


# ------------------------------------------------------------------ routes et relais (pile réelle)


async def test_routes_and_relay_force_the_user_actor(tmp_path):
    install_version(tmp_path / "data" / LIBRARY_DIR, "test.counter")
    async with CaptureStack(tmp_path) as stack:
        await stack.core.scene.apply(create())
        # Le relais remplace `actor`, quoi qu'il dise.
        status, answer, _ = await stack.call("POST", "/api/prefabs/events", json=body(actor="brain"))
        assert status == 200 and answer == {"outcome": "applied", "revision": 2}
        status, answer, _ = await stack.call("POST", "/api/prefabs/events", json=body())
        assert status == 200 and answer["outcome"] == "stale" and answer["revision"] == 2
        status, answer, _ = await stack.call("GET", "/api/prefabs/events", params={"limit": "5"})
        assert status == 200 and [e["outcome"] for e in answer["events"]] == ["applied", "stale"]
        assert answer["last_seq"] == 2
        status, answer, _ = await stack.call("GET", "/api/prefabs/events", params={"after": "1", "object_id": "win-1"})
        assert [e["seq"] for e in answer["events"]] == [2]
        for bad in (b"[]", b"not json", b""):
            status, answer, _ = await stack.call("POST", "/api/prefabs/events", data=bad)
            assert (status, answer["error"]["code"]) == (400, "invalid_request")
        status, answer, _ = await stack.call("POST", "/api/prefabs/events", json={**body(), "extra": 1})
        assert (status, answer["error"]["code"]) == (400, "invalid_request")
        status, answer, _ = await stack.call("GET", "/api/prefabs/events", params={"limit": "99"})
        assert (status, answer["error"]["code"]) == (400, "invalid_request")
        # Un cadre (origine opaque) ne poste rien.
        status, answer, _ = await stack.call("POST", "/api/prefabs/events", json=body(), headers={"Origin": "null"})
        assert status == 403
        relayed = [e for e in stack.trace() if e.get("kind") == "prefab.request.relayed"]
        assert relayed[0]["data"] == {"action": "prefab_event", "status": 200, "outcome": "applied", "code": None}
        # 429 de Core relayé tel quel.
        stack.core.prefab_events._tokens = 0.0
        stack.core.prefab_events._rate = 0.001
        status, answer, _ = await stack.call("POST", "/api/prefabs/events", json=body())
        assert (status, answer["error"]["code"]) == (429, "rate_limited")

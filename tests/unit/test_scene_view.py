"""Proxy de scène du Control Center et forme du transport (handoff jarvis-constellation-scene-runtime, Slice 03).

Ce qui doit tenir, sans Core réel (transport scripté) :

- une réponse de Core hors contrat n'atteint jamais la page : 200 dégradé
  `invalid_scene_response`, journalisé en erreur ;
- Core injoignable, refus, délai, scène indisponible : chacun son code, la
  disponibilité de la scène (`scene`) quand Core la donne ;
- un Core figé ne tient pas un long-poll au-delà de l'attente bornée + marge,
  ni une lecture d'instantané au-delà de son délai ;
- une panne se journalise une fois, le retour aussi ;
- une commande sans réponse à l'échéance dit « issue inconnue » (504) ;
- l'acteur du navigateur est toujours `user` ;
- sans vue configurée, les routes le disent ; les requêtes invalides sont 400 ;
- `parse_patch_query` et `patch_window_body` tiennent leurs bornes.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from aiohttp.test_utils import TestClient, TestServer, make_mocked_request
import pytest
from multidict import MultiDict

from jarvis.domain.scene import (
    SceneActor,
    SceneCommand,
    SceneObjectFields,
    SceneObjectKind,
    SceneOp,
    ScenePatch,
    SceneSnapshot,
    apply_scene_command,
)
from jarvis.ports.scene import ScenePatchWindow
from jarvis.protocol import scene_wire
from jarvis.protocol.client import CoreProtocolError
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.scene_view import (
    CORE_TIMEOUT,
    CORE_UNREACHABLE,
    INVALID_SCENE_RESPONSE,
    CoreSceneTransport,
    CoreSceneView,
    SceneActorForbidden,
    decode_patches_response,
    decode_snapshot_response,
    user_command,
)
from jarvis.runtime.work_view import CORE_REFUSED, NOT_CONFIGURED


class Journal:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def emit(self, kind: str, message: str, *, level: str = "info", data: dict | None = None) -> None:
        self.events.append((kind, level, data or {}))

    def kinds(self) -> list[tuple[str, str]]:
        return [(kind, level) for kind, level, _ in self.events]


def scene_after_one_command() -> tuple[SceneSnapshot, ScenePatch]:
    update = apply_scene_command(SceneSnapshot(scene_id="scene-1"), SceneCommand(
        op=SceneOp.UPSERT_OBJECT, actor=SceneActor.USER, object_id="art-1",
        fields=SceneObjectFields(kind=SceneObjectKind.ARTIFACT, category="research")))
    assert update.patch is not None
    return update.snapshot, update.patch


class ScriptedTransport:
    """Réponses ou exceptions scriptées ; `hang` : ne répond jamais."""

    def __init__(self, *, snapshot: Any = None, patches: Any = None, command: Any = None, hang: bool = False) -> None:
        self.snapshot_result, self.patches_result, self.command_result = snapshot, patches, command
        self.hang = hang
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    async def _answer(self, result: Any) -> Any:
        if self.hang:
            await asyncio.Event().wait()
        if isinstance(result, BaseException):
            raise result
        return result

    async def scene_snapshot(self) -> dict:
        self.calls.append(("snapshot", {}))
        return await self._answer(self.snapshot_result)

    async def scene_patches(self, **kwargs: Any) -> dict:
        self.calls.append(("patches", kwargs))
        return await self._answer(self.patches_result)

    async def scene_command(self, command: dict) -> dict:
        self.calls.append(("command", command))
        return await self._answer(self.command_result)

    async def close(self) -> None:
        self.closed = True


QUERY = scene_wire.PatchQuery(scene_id="scene-1", epoch="e1", after=0, wait_s=10)


def good_snapshot() -> dict:
    snapshot, _ = scene_after_one_command()
    return {"scene_id": "scene-1", "epoch": "e1", "revision": 1, "snapshot": snapshot.to_payload()}


def good_patches() -> dict:
    _, patch = scene_after_one_command()
    return {"scene_id": "scene-1", "epoch": "e1", "revision": 1, "resync_required": False, "more": False, "patches": [patch.to_payload()]}


def user_archive() -> SceneCommand:
    return SceneCommand(op=SceneOp.ARCHIVE, actor=SceneActor.USER, object_id="art-1")


# ------------------------------------------------------------ décodage


async def test_a_valid_core_answer_is_served_with_declared_fields_only():
    raw = {**good_snapshot(), "extra": "ignored"}
    view = CoreSceneView(ScriptedTransport(snapshot=raw, patches={**good_patches(), "extra": 1}))

    snapshot = await view.snapshot()
    patches = await view.patches(QUERY)

    assert snapshot["core_reachable"] is True and snapshot["error"] is None and "extra" not in snapshot
    assert snapshot["scene"] == {"state": "ready", "code": None} and snapshot["snapshot"] == raw["snapshot"]
    assert patches["patches"] == good_patches()["patches"] and patches["error"] is None and "extra" not in patches


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: [],
        lambda raw: {**raw, "epoch": ""},
        lambda raw: {**raw, "revision": True},
        lambda raw: {**raw, "revision": 2},
        lambda raw: {**raw, "scene_id": "other"},
        lambda raw: {**raw, "snapshot": {**raw["snapshot"], "schema_version": 2}},
        lambda raw: {**raw, "snapshot": {**raw["snapshot"], "objects": [{"object_id": "x"}]}},
    ],
)
def test_an_invalid_snapshot_response_is_refused(mutate):
    with pytest.raises((TypeError, ValueError)):
        decode_snapshot_response(mutate(good_snapshot()))


@pytest.mark.parametrize(
    ("mutate", "after"),
    [
        (lambda raw: {**raw, "resync_required": "no"}, 0),
        (lambda raw: {**raw, "resync_required": True}, 0),  # une resynchronisation ne porte aucun patch
        (lambda raw: raw, 1),  # patch 1 alors que le client tient 1 : non consécutif
        (lambda raw: {**raw, "revision": 5}, 0),
        (lambda raw: {**raw, "patches": [], "revision": 3}, 0),
        (lambda raw: {**raw, "patches": [{"schema_version": 1, "revision": 1, "ops": []}]}, 0),
        (lambda raw: {**raw, "more": None}, 0),
    ],
)
def test_an_invalid_patches_response_is_refused(mutate, after):
    with pytest.raises((TypeError, ValueError)):
        decode_patches_response(mutate(good_patches()), after=after)


async def test_an_out_of_contract_answer_is_degraded_and_journaled_as_an_error():
    journal = Journal()
    view = CoreSceneView(ScriptedTransport(snapshot={"scene_id": "s"}, patches={"nope": 1}), journal=journal)

    snapshot = await view.snapshot()
    patches = await view.patches(QUERY)

    assert snapshot["error"]["code"] == INVALID_SCENE_RESPONSE and snapshot["snapshot"] is None and snapshot["core_reachable"] is True
    assert patches["error"]["code"] == INVALID_SCENE_RESPONSE and patches["patches"] == [] and patches["resync_required"] is False
    assert ("scene.view_invalid_response", "error") in journal.kinds()


# ------------------------------------------------------------ pannes


@pytest.mark.parametrize(
    ("failure", "code", "reachable"),
    [
        (ConnectionError("Core session token is unavailable"), CORE_UNREACHABLE, False),
        (TimeoutError(), CORE_UNREACHABLE, False),
        (CoreProtocolError(426, "protocol_mismatch", "supported version is 2"), CORE_REFUSED, True),
        (ValueError("Core response exceeds 16777216 bytes"), INVALID_SCENE_RESPONSE, True),
    ],
)
async def test_each_read_failure_has_its_code(failure, code, reachable):
    view = CoreSceneView(ScriptedTransport(snapshot=failure, patches=failure))

    for body in (await view.snapshot(), await view.patches(QUERY)):
        assert body["error"]["code"] == code and body["core_reachable"] is reachable
        assert body["scene_id"] is None and body["epoch"] is None and body["revision"] is None


async def test_an_unavailable_scene_carries_its_availability():
    failure = CoreProtocolError(503, "scene_unavailable", "scene is unavailable: corrupted",
                                details={"scene": {"state": "unavailable", "code": "corrupted"}, "store_code": "corrupted"})
    view = CoreSceneView(ScriptedTransport(snapshot=failure, patches=failure, command=failure))

    snapshot = await view.snapshot()
    status, command = await view.command(user_archive())

    assert snapshot["error"] == {"code": "scene_unavailable", "message": "scene is unavailable: corrupted"}
    assert snapshot["scene"] == {"state": "unavailable", "code": "corrupted"} and snapshot["core_reachable"] is True
    assert status == 503 and command["scene"] == {"state": "unavailable", "code": "corrupted"}


async def test_a_hanging_core_never_holds_the_page_beyond_the_bounded_wait():
    transport = ScriptedTransport(hang=True)
    view = CoreSceneView(transport, snapshot_timeout_s=0.2, max_patch_wait_s=0.3, patch_wait_grace_s=0.2)

    started = time.monotonic()
    patches = await view.patches(scene_wire.PatchQuery("scene-1", "e1", 0, wait_s=999))
    elapsed = time.monotonic() - started
    snapshot = await view.snapshot()

    assert patches["error"]["code"] == CORE_UNREACHABLE and 0.5 <= elapsed < 3
    assert transport.calls[0] == ("patches", {"scene_id": "scene-1", "epoch": "e1", "after": 0, "wait_s": 0.3, "timeout_s": 0.5})
    assert snapshot["error"]["code"] == CORE_UNREACHABLE and "0.2 s" in snapshot["error"]["message"]


async def test_the_wait_is_clamped_by_the_control_center():
    transport = ScriptedTransport(patches=good_patches())
    view = CoreSceneView(transport)

    await view.patches(scene_wire.PatchQuery("scene-1", "e1", 0, wait_s=900))

    assert transport.calls[0][1]["wait_s"] == 25.0 and transport.calls[0][1]["timeout_s"] == 30.0


async def test_an_outage_is_journaled_once_and_its_end_once():
    journal = Journal()
    transport = ScriptedTransport(snapshot=ConnectionError("refused"), patches=ConnectionError("refused"))
    view = CoreSceneView(transport, journal=journal)

    for _ in range(3):
        await view.snapshot()
        await view.patches(QUERY)
    transport.snapshot_result = good_snapshot()
    await view.snapshot()
    await view.snapshot()

    assert journal.kinds() == [("scene.view_unavailable", "warning"), ("scene.view_restored", "info")]
    assert journal.events[1][2] == {"after": [CORE_UNREACHABLE]}


# ------------------------------------------------------------ commandes


def applied_answer() -> dict:
    snapshot, patch = scene_after_one_command()
    return {"outcome": "applied", "reason": None, "scene_id": "scene-1", "epoch": "e1", "revision": 1, "patch": patch.to_payload()}


async def test_a_relayed_command_is_journaled_with_its_outcome():
    journal = Journal()
    transport = ScriptedTransport(command=applied_answer())
    view = CoreSceneView(transport, journal=journal)

    status, body = await view.command(user_archive())

    assert status == 200 and body["outcome"] == "applied" and body["error"] is None and body["core_reachable"] is True
    assert transport.calls == [("command", user_archive().to_payload())]
    assert journal.events == [("scene.command", "info", {"op": "archive", "outcome": "applied", "reason": None, "revision": 1})]


@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        (ConnectionError("refused"), 503, CORE_UNREACHABLE),
        (CoreProtocolError(401, "unauthorized", "invalid local session credential"), 502, CORE_REFUSED),
        (CoreProtocolError(400, "invalid_request", "invalid scene command: x"), 400, "invalid_request"),
        (CoreProtocolError(413, "payload_too_large", "too big"), 413, "payload_too_large"),
        (CoreProtocolError(503, "scene_persist_failed", "disk full", details={"scene": {"state": "ready", "code": None}}), 503, "scene_persist_failed"),
        ({"outcome": "applied", "reason": None, "scene_id": "s", "epoch": "e", "revision": 1, "patch": None}, 502, INVALID_SCENE_RESPONSE),
        ({"outcome": "maybe", "reason": None, "scene_id": "s", "epoch": "e", "revision": 1, "patch": None}, 502, INVALID_SCENE_RESPONSE),
    ],
)
async def test_each_command_failure_has_its_status_and_code(failure, status, code):
    journal = Journal()
    view = CoreSceneView(ScriptedTransport(command=failure), journal=journal)

    got_status, body = await view.command(user_archive())

    assert (got_status, body["error"]["code"]) == (status, code)
    assert ("scene.command_failed", "warning") in journal.kinds()


async def test_a_command_without_answer_says_its_outcome_is_unknown():
    view = CoreSceneView(ScriptedTransport(hang=True), command_timeout_s=0.2)

    status, body = await view.command(user_archive())

    assert status == 504 and body["error"]["code"] == CORE_TIMEOUT and "issue inconnue" in body["error"]["message"]


async def test_the_view_relays_user_commands_only():
    view = CoreSceneView(ScriptedTransport(command=applied_answer()))
    with pytest.raises(ValueError):
        await view.command(SceneCommand(op=SceneOp.ARCHIVE, actor=SceneActor.BRAIN, object_id="art-1"))


@pytest.mark.parametrize("actor", ["brain", "runtime", "", None, 3, "USER"])
def test_the_browser_can_never_choose_another_actor(actor):
    with pytest.raises(SceneActorForbidden):
        user_command({"schema_version": 1, "op": "archive", "actor": actor, "object_id": "art-1"})


def test_a_command_without_actor_becomes_a_user_command():
    command = user_command({"schema_version": 1, "op": "archive", "object_id": "art-1"})
    assert command.actor is SceneActor.USER
    with pytest.raises(TypeError):
        user_command(["not", "an", "object"])


async def test_the_transport_rereads_the_token_once_when_core_restarted(tmp_path):
    token_file = tmp_path / "core.token"
    token_file.write_text("a" * 48, encoding="utf-8")
    transport = CoreSceneTransport(host="127.0.0.1", port=1, token_file=token_file)
    tokens: list[str] = []

    async def call(client):  # noqa: ANN001
        tokens.append(client.token)
        if len(tokens) == 1:
            token_file.write_text("b" * 48, encoding="utf-8")
            raise CoreProtocolError(401, "unauthorized", "stale")
        return {"ok": True}

    try:
        assert await transport._with_fresh_token(call) == {"ok": True}
    finally:
        await transport.close()
    assert tokens == ["a" * 48, "b" * 48]


# ------------------------------------------------------------ routes


async def test_the_routes_say_when_no_scene_view_is_configured(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    async with TestClient(TestServer(control._app)) as client:
        scene = await client.get("/api/scene")
        patches = await client.get("/api/scene/patches?scene_id=s&epoch=e&after=0")
        command = await client.post("/api/scene/commands", json={"schema_version": 1, "op": "archive", "object_id": "a"})

        assert scene.status == 200 and (await scene.json())["error"]["code"] == NOT_CONFIGURED
        assert (await scene.json())["snapshot"] is None
        assert patches.status == 200 and (await patches.json())["error"]["code"] == NOT_CONFIGURED
        assert command.status == 503 and (await command.json())["error"]["code"] == NOT_CONFIGURED


async def test_scene_routes_are_read_only_except_commands(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    methods = {}
    for route in control._app.router.routes():
        if route.resource.canonical.startswith("/api/scene"):
            methods.setdefault(route.resource.canonical, set()).add(route.method)
    assert methods == {"/api/scene": {"GET", "HEAD"}, "/api/scene/patches": {"GET", "HEAD"}, "/api/scene/commands": {"POST"}}
    async with TestClient(TestServer(control._app)) as client:
        assert (await client.post("/api/scene", json={})).status == 405
        assert (await client.get("/api/scene?x=1")).status == 400
        assert (await client.post("/api/scene/commands?x=1", json={})).status == 400


async def test_the_command_route_validates_before_calling_core(tmp_path):
    transport = ScriptedTransport(command=applied_answer())
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path, scene_view=CoreSceneView(transport))
    async with TestClient(TestServer(control._app)) as client:
        for raw in (b"nope", b'{"schema_version": 1, "op": "archive", "object_id": "a", "object_id": "b"}',
                    b'{"schema_version": 1, "op": "archive"}', b"[]"):
            response = await client.post("/api/scene/commands", data=raw)
            assert response.status == 400, raw
        brain = await client.post("/api/scene/commands", json={"schema_version": 1, "op": "archive", "actor": "brain", "object_id": "a"})
        assert brain.status == 403
    assert transport.calls == []
    assert any(kind == "scene.command_forbidden" for kind in (json.loads(line)["kind"] for line in
               (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()))


# ------------------------------------------------------------ forme


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("scene_id=s&epoch=e&after=0", scene_wire.PatchQuery("s", "e", 0, 0.0)),
        ("scene_id=s&epoch=e&after=12&wait_s=2.5", scene_wire.PatchQuery("s", "e", 12, 2.5)),
        ("after=3&wait_s=30&epoch=e&scene_id=s", scene_wire.PatchQuery("s", "e", 3, 30.0)),
    ],
)
def test_patch_queries_are_parsed(query, expected):
    assert scene_wire.parse_patch_query(make_mocked_request("GET", f"/?{query}").query) == expected


@pytest.mark.parametrize(
    "pairs",
    [
        [("scene_id", "s"), ("epoch", "e")],
        [("scene_id", "s"), ("epoch", "e"), ("after", " 1")],
        [("scene_id", "s"), ("epoch", "e"), ("after", "1_000")],
        [("scene_id", "s"), ("epoch", "e"), ("after", "１")],
        [("scene_id", "s"), ("epoch", "e"), ("after", "1"), ("wait_s", "1e3")],
        [("scene_id", " s"), ("epoch", "e"), ("after", "1")],
        [("scene_id", "s" * 129), ("epoch", "e"), ("after", "1")],
        [("scene_id", "s"), ("scene_id", "s"), ("epoch", "e"), ("after", "1")],
    ],
)
def test_malformed_patch_queries_are_value_errors(pairs):
    with pytest.raises(ValueError):
        scene_wire.parse_patch_query(MultiDict(pairs))


def test_the_patch_body_always_carries_at_least_one_whole_patch(monkeypatch):
    _, patch = scene_after_one_command()
    window = ScenePatchWindow("scene-1", 1, (patch,), resync_required=False)
    monkeypatch.setattr(scene_wire, "MAX_PATCH_RESPONSE_BYTES", 1)

    body = json.loads(scene_wire.patch_window_body(window, epoch="e1", after=0))

    assert body == {"scene_id": "scene-1", "epoch": "e1", "revision": 1, "resync_required": False, "more": False,
                    "patches": [patch.to_payload()]}
    resync = json.loads(scene_wire.patch_window_body(ScenePatchWindow("scene-1", 9, (), True), epoch="e1", after=0))
    assert resync["revision"] == 9 and resync["resync_required"] is True and resync["patches"] == []

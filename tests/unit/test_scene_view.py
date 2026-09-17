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
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

import aiohttp
import aiohttp.web
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
from jarvis.protocol.client import CoreProtocolError, LocalCoreClient
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.scene_view import (
    COMMAND_NOT_SENT,
    CORE_TIMEOUT,
    CORE_UNREACHABLE,
    INVALID_SCENE_RESPONSE,
    PATCH_RETRY_AFTER_MS,
    PATCH_WAITS_BUSY,
    CoreSceneTransport,
    CoreSceneView,
    ReportThrottle,
    SceneActorForbidden,
    _with_fresh_token,
    page_text,
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

    async def scene_command(self, command: dict, **kwargs: Any) -> dict:
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
    assert snapshot["scene"] == {"state": "ready", "code": None, "saturated": False, "objects": len(raw["snapshot"]["objects"]), "object_limit": 512}
    assert snapshot["snapshot"] == raw["snapshot"]
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


@pytest.mark.parametrize(("status", "expected"), [(500, 502), (400, 502), (413, 502)])
async def test_a_non_json_core_error_body_is_never_relayed(status, expected):
    """Slice 06 QA m4 : un corps d'erreur non JSON (page HTML, trace) ne part ni vers la page ni au journal."""

    body_text = "<html>Internal Server Error\nTraceback (most recent call last):\n  File x</html>"
    journal = Journal()
    view = CoreSceneView(ScriptedTransport(command=CoreProtocolError(status, f"http_{status}", body_text)), journal=journal)

    got_status, body = await view.command(user_archive())

    assert (got_status, body["error"]["code"]) == (expected, CORE_REFUSED)
    assert "Traceback" not in json.dumps(body) and "<html>" not in json.dumps(body)
    assert "Traceback" not in json.dumps(journal.events)


async def test_a_command_without_answer_says_its_outcome_is_unknown():
    view = CoreSceneView(ScriptedTransport(hang=True), command_timeout_s=0.1, command_connect_timeout_s=0.1)

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
        assert await _with_fresh_token(transport, call) == {"ok": True}
        # Les long-polls ont leur propre connexion (QA Slice 03, MINOR-1).
        assert transport._polls is not transport and transport._polls.token_file == token_file
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
    # Slice 09, partie 2 : la page meneuse envoie une capture demandée par le cerveau ; aucune route n'en demande.
    assert methods == {"/api/scene": {"GET", "HEAD"}, "/api/scene/patches": {"GET", "HEAD"}, "/api/scene/commands": {"POST"},
                       "/api/scene/captures/{capture_id}": {"POST"}}
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

# ------------------------------------------------------------ QA Slice 03 : charge, journal, messages


async def _until(condition) -> None:
    while not condition():
        await asyncio.sleep(0.005)


async def test_long_polls_beyond_the_cap_answer_at_once_without_calling_core():
    journal = Journal()
    transport = ScriptedTransport(hang=True)
    view = CoreSceneView(transport, journal=journal, max_concurrent_waits=2)
    held = [asyncio.create_task(view.patches(QUERY)) for _ in range(2)]
    await asyncio.wait_for(_until(lambda: view.waiting == 2 and len(transport.calls) == 2), 30)

    started = time.monotonic()
    busy = [await view.patches(QUERY) for _ in range(4)]

    assert time.monotonic() - started < 0.5 and len(transport.calls) == 2 and view.waiting == 2
    assert busy[0]["error"]["code"] == PATCH_WAITS_BUSY and busy[0]["retry_after_ms"] == PATCH_RETRY_AFTER_MS
    assert busy[0]["core_reachable"] is None and busy[0]["patches"] == [] and busy[0]["resync_required"] is False
    assert [kind for kind in journal.kinds() if kind[0] == "scene.view_busy"] == [("scene.view_busy", "warning")]
    for task in held:
        task.cancel()
    await asyncio.gather(*held, return_exceptions=True)
    assert view.waiting == 0
    transport.hang = False
    transport.patches_result = good_patches()
    assert (await view.patches(QUERY))["error"] is None


async def test_a_command_that_never_got_a_connection_says_it_was_not_sent():
    view = CoreSceneView(ScriptedTransport(command=aiohttp.ConnectionTimeoutError("pool")), command_connect_timeout_s=3)
    status, body = await view.command(user_archive())
    assert (status, body["error"]["code"]) == (503, COMMAND_NOT_SENT)
    assert "Rien n'a été appliqué" in body["error"]["message"] and "inconnue" not in body["error"]["message"]

    view = CoreSceneView(ScriptedTransport(command=aiohttp.SocketTimeoutError("read")))
    status, body = await view.command(user_archive())
    assert (status, body["error"]["code"]) == (504, CORE_TIMEOUT) and "inconnue" in body["error"]["message"]

    view = CoreSceneView(ScriptedTransport(command=ConnectionError("Core session token is unavailable")))
    status, body = await view.command(user_archive())
    assert (status, body["error"]["code"]) == (503, CORE_UNREACHABLE) and "non envoyée" in body["error"]["message"]


async def test_the_client_tells_a_connection_wait_from_a_response_wait():
    """aiohttp réel : attendre une place du pool = non envoyée ; attendre la réponse = issue inconnue."""

    release = asyncio.Event()
    entered = asyncio.Event()

    async def slow(request):  # noqa: ANN001
        await request.read()
        entered.set()
        await release.wait()
        return aiohttp.web.json_response({})

    app = aiohttp.web.Application()
    app.router.add_post("/v1/scene/commands", slow)
    async with TestServer(app, host="127.0.0.1") as server:
        session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=1))
        client = LocalCoreClient(host="127.0.0.1", port=server.port, token="t" * 48, session=session)
        try:
            holder = asyncio.create_task(client.scene_command({"op": "hold"}))
            await asyncio.wait_for(entered.wait(), 30)  # la seule connexion du pool est prise
            with pytest.raises(aiohttp.ConnectionTimeoutError):
                await client.scene_command({"op": "queued"}, connect_timeout_s=0.2, read_timeout_s=5)
            release.set()
            await holder
            release.clear()
            with pytest.raises(aiohttp.SocketTimeoutError):
                await client.scene_command({"op": "slow"}, connect_timeout_s=2, read_timeout_s=0.2)
            release.set()
        finally:
            await session.close()


async def test_an_out_of_contract_answer_is_journaled_once_until_restored():
    journal = Journal()
    transport = ScriptedTransport(snapshot={"scene_id": "s"}, patches={"nope": 1}, command={"outcome": "maybe"})
    view = CoreSceneView(transport, journal=journal)

    for _ in range(5):
        await view.snapshot()
        await view.patches(QUERY)
        await view.command(user_archive())
    errors = [data["read"] for kind, level, data in journal.events if kind == "scene.view_invalid_response"]
    assert sorted(errors) == ["command", "patches", "snapshot"]

    transport.snapshot_result = good_snapshot()
    await view.snapshot()
    transport.snapshot_result = {"scene_id": "s"}
    await view.snapshot()
    await view.snapshot()
    errors = [data["read"] for kind, level, data in journal.events if kind == "scene.view_invalid_response"]
    assert sorted(errors) == ["command", "patches", "snapshot", "snapshot"]
    assert [kind for kind, _, _ in journal.events].count("scene.view_restored") == 1


def test_the_report_throttle_counts_what_it_silenced():
    now = [0.0]
    throttle = ReportThrottle(60, clock=lambda: now[0], max_keys=2)

    assert throttle.admit('"brain"') == 0
    assert [throttle.admit('"brain"') for _ in range(4)] == [None] * 4
    assert throttle.admit('"runtime"') == 0
    now[0] = 61
    assert throttle.admit('"brain"') == 4
    assert throttle.admit("third") == 0  # au-delà de max_keys : tout est oublié, jamais de croissance
    assert throttle.admit('"runtime"') == 0


async def test_forbidden_actors_are_journaled_once_per_value_per_window(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    now = [0.0]
    control._scene_forbidden_reports.clock = lambda: now[0]

    async with TestClient(TestServer(control._app)) as client:
        async def post(actor):  # noqa: ANN001, ANN202
            response = await client.post("/api/scene/commands", json={"schema_version": 1, "op": "archive", "actor": actor, "object_id": "a"})
            assert response.status == 403

        for _ in range(5):
            await post("brain")
        await post("runtime")
        now[0] = 61
        await post("brain")

    events = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    forbidden = [(event["data"]["actor"], event["data"]["suppressed"]) for event in events if event["kind"] == "scene.command_forbidden"]
    assert forbidden == [('"brain"', 0), ('"runtime"', 0), ('"brain"', 4)]


WINDOWS_PATH = r"C:\Users\Jean Dupont\AppData\Local\jarvis\data\state\scene.sqlite3"


async def test_messages_sent_to_the_page_never_carry_file_paths():
    journal = Journal()
    message = f"scene is unavailable: SceneStoreError: scene store {WINDOWS_PATH} refused: DatabaseError: file is not a database"
    failure = CoreProtocolError(503, "scene_unavailable", message, details={"scene": {"state": "unavailable", "code": "corrupted"}})
    view = CoreSceneView(ScriptedTransport(snapshot=failure, patches=failure, command=failure), journal=journal)

    bodies = [await view.snapshot(), await view.patches(QUERY), (await view.command(user_archive()))[1]]

    for body in bodies:
        text = json.dumps(body, ensure_ascii=False)
        assert "Users" not in text and "scene.sqlite3" not in text and ":\\\\" not in text, text
        assert body["error"]["message"] == "scene is unavailable: SceneStoreError: scene store <chemin> refused: DatabaseError: file is not a database"
    journaled = " ".join(json.dumps(event, ensure_ascii=False) for event in journal.events)
    assert "Jean Dupont" in journaled  # le journal garde la cause complète
    assert page_text(r"\\serveur\partage\scene.sqlite3 bloqué") == "<chemin> bloqué"
    assert page_text("/home/jean/.local/data/scene.sqlite3 absent") == "<chemin> absent"
    assert page_text("Cannot connect to host 127.77.0.1:17791 ssl:default, see http://127.0.0.1:17654/api/scene") == (
        "Cannot connect to host 127.77.0.1:17791 ssl:default, see http://127.0.0.1:17654/api/scene")


def test_the_protocol_client_does_not_load_the_scene_domain_or_aiohttp_web():
    code = (
        "import sys, jarvis.protocol.client;"
        "print(sorted(m for m in ('aiohttp.web', 'jarvis.domain.scene', 'jarvis.ports.scene') if m in sys.modules))"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, cwd=Path(__file__).resolve().parents[2])
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


async def test_snapshots_and_commands_never_queue_behind_long_polls(tmp_path):
    """Au-delà du pool de 100 connexions d'une session aiohttp : lectures et commandes restent immédiates."""

    from tests.integration.test_scene_transport import CoreProcess, artifact

    process = CoreProcess(tmp_path)
    await process.start()
    view = CoreSceneView(CoreSceneTransport(host="127.0.0.1", port=process.port, token_file=process.token_file),
                         max_concurrent_waits=500, command_connect_timeout_s=2, command_timeout_s=2, snapshot_timeout_s=2)
    try:
        snap = await view.snapshot()
        query = scene_wire.PatchQuery(snap["scene_id"], snap["epoch"], snap["revision"], wait_s=20)
        polls = [asyncio.create_task(view.patches(query)) for _ in range(120)]
        await asyncio.sleep(1.0)

        started = time.monotonic()
        snapshot = await view.snapshot()
        status, body = await view.command(user_command(artifact("art-load")))
        elapsed = time.monotonic() - started
        results = await asyncio.wait_for(asyncio.gather(*polls), 30)
    finally:
        await view.aclose()
        await process.stop()

    assert snapshot["error"] is None and status == 200 and body["outcome"] == "applied", (snapshot, body)
    assert elapsed < 1.5, elapsed
    assert all(result["error"] is None and result["revision"] == 1 for result in results)


def test_the_scene_block_relays_capacity_only_when_core_gave_it_well_typed():
    """Slice 04 QA F1 : `saturated`/`objects`/`object_limit` passent tels quels, ou pas du tout."""

    from jarvis.runtime.scene_view import _scene_block

    def block(scene):
        return _scene_block(CoreProtocolError(503, "scene_unavailable", "x", details={"scene": scene}))

    full = {"state": "ready", "code": None, "saturated": True, "objects": 512, "object_limit": 512}
    assert block(full) == full
    assert block({"state": "unavailable", "code": "corrupted", "saturated": False, "objects": None, "object_limit": 512})["objects"] is None
    assert block({"state": "ready", "code": None}) == {"state": "ready", "code": None}
    assert block({**full, "saturated": "yes"}) == {"state": "ready", "code": None}
    assert block({**full, "objects": True}) == {"state": "ready", "code": None}

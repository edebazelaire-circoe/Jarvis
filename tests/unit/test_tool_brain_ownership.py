"""Propriété de l'écran : un seul décideur à la fois, repli sûr, aucune double exécution (handoff jarvis-tool-brain-ui-orchestrator, S8).

Contrat : `docs/tool-brain-contracts.md` §16. Ce qui doit tenir, sans modèle ni processus :

- la matrice (mode x santé) donne exactement un propriétaire, `jarvis_direct` par défaut (zéro changement de l'install) ;
- Tool Brain en panne / indisponible / non prouvé / publication impossible : Jarvis garde l'écran, le repli est tracé ;
- les deux côtés lisent la même publication : l'exécuteur n'agit que si Jarvis est refusé, et inversement ;
- une publication absente, périmée ou illisible est toujours `jarvis_direct` (l'écran ne gèle jamais) ;
- les outils d'écran de Jarvis sont refusés mécaniquement quand le Tool Brain possède l'écran, au niveau du serveur d'outils.
"""

from __future__ import annotations

import json

import pytest

from jarvis.runtime import display_mcp
from jarvis.runtime.board_routes import BoardSessionRoutes
from jarvis.runtime.display_mcp import DisplayToolError, SceneDisplayTools
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.mcp_tool_meta import SERVERS, tool_meta
from jarvis.runtime.tool_brain_ownership import (
    ACTIVE_HEALTHY, DECIDER_FAILING, DECIDER_UNAVAILABLE, FAILURE_LIMIT, HOLD_DOWN, MODE_OFF, MODE_SHADOW, NOT_PROVEN,
    NO_PUBLICATION, OWNERSHIP_DIRECT, OWNERSHIP_TOOL_BRAIN, PUBLISH_FAILED, RUNTIME_DOWN, SCHEMA, SHUTDOWN,
    STALE_PUBLICATION, TTL_S, UI_DELEGATED, UNREADABLE_PUBLICATION, DelegationGate, Health, OwnershipArbiter,
    OwnershipView, decide, jarvis_delegated_tools, ownership_path, read_ownership,
)
from tests.unit.test_display_mcp import SpyTransport

HEALTHY = Health(running=True, completed=3, consecutive_failures=0, last_outcome="completed")


class Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class Rig:
    """Un arbitre réel sur un dossier runtime réel, avec un état de runtime scénarisé."""

    def __init__(self, tmp_path, mode="active", **kw) -> None:
        self.clock = Clock()
        self.health = HEALTHY
        self.traces: list[dict] = []
        self.changes: list[tuple[str, str]] = []
        self.arbiter = OwnershipArbiter(
            self.status, mode, kw.pop("root", tmp_path), clock=self.clock, wall=self.clock,
            trace=lambda kind, message, **extra: self.traces.append({"kind": kind, "message": message, **extra}),
            on_change=lambda old, new: self.changes.append((old.ownership, new.ownership)), **kw)

    def status(self):
        h = self.health
        return {"running": h.running, "counters": {"completed": h.completed}, "consecutive_failures": h.consecutive_failures,
                "last_outcome": h.last_outcome}

    def fallbacks(self) -> list[dict]:
        return [t for t in self.traces if t["kind"] == "tool_brain.ownership.changed" and t["data"]["fallback"]]


# ------------------------------------------------------------------ matrice


@pytest.mark.parametrize("mode,health,expected", [
    ("off", HEALTHY, (OWNERSHIP_DIRECT, MODE_OFF)),
    ("shadow", HEALTHY, (OWNERSHIP_DIRECT, MODE_SHADOW)),
    ("nonsense", HEALTHY, (OWNERSHIP_DIRECT, MODE_OFF)),
    ("active", HEALTHY, (OWNERSHIP_TOOL_BRAIN, ACTIVE_HEALTHY)),
    ("active", Health(False, 3, 0, "completed"), (OWNERSHIP_DIRECT, RUNTIME_DOWN)),
    ("active", Health(True, 0, 0, None), (OWNERSHIP_DIRECT, NOT_PROVEN)),
    ("active", Health(True, 3, 1, "unavailable"), (OWNERSHIP_DIRECT, DECIDER_UNAVAILABLE)),
    ("active", Health(True, 3, FAILURE_LIMIT, "failed"), (OWNERSHIP_DIRECT, DECIDER_FAILING)),
    ("active", Health(True, 3, FAILURE_LIMIT - 1, "failed"), (OWNERSHIP_TOOL_BRAIN, ACTIVE_HEALTHY)),
])
def test_the_ownership_matrix_has_exactly_one_owner_and_defaults_to_jarvis(mode, health, expected):
    assert decide(mode, health) == expected


def test_only_the_active_mode_with_a_proven_healthy_runtime_delegates():
    for mode in ("off", "shadow", "", "ACTIVE!"):
        for health in (HEALTHY, Health(), Health(True, 5, 0, "completed")):
            assert decide(mode, health)[0] == OWNERSHIP_DIRECT


# ------------------------------------------------------------------ arbitre : publication, repli, retenue


def test_a_healthy_active_runtime_takes_the_screen_and_publishes_it(tmp_path):
    rig = Rig(tmp_path)
    assert rig.arbiter.executor_allowed() is True
    seen = read_ownership(tmp_path, wall=rig.clock)
    assert (seen.ownership, seen.reason, seen.mode) == (OWNERSHIP_TOOL_BRAIN, ACTIVE_HEALTHY, "active")
    assert rig.changes == [(OWNERSHIP_DIRECT, OWNERSHIP_TOOL_BRAIN)] and not rig.fallbacks()


def test_off_and_shadow_never_delegate_even_with_a_healthy_runtime(tmp_path):
    for mode in ("off", "shadow"):
        rig = Rig(tmp_path / mode, mode)
        assert rig.arbiter.executor_allowed() is False and rig.arbiter.owns() is False
        assert read_ownership(tmp_path / mode, wall=rig.clock).ownership == OWNERSHIP_DIRECT


def test_runtime_outage_falls_back_to_jarvis_with_a_traced_warning_and_a_flushed_queue(tmp_path):
    rig = Rig(tmp_path)
    assert rig.arbiter.executor_allowed()
    rig.health = Health(False, 3, 0, "completed")  # the Tool Brain loop died
    assert rig.arbiter.executor_allowed() is False  # the very next gate call: no stale permission
    seen = read_ownership(tmp_path, wall=rig.clock)
    assert (seen.ownership, seen.reason) == (OWNERSHIP_DIRECT, RUNTIME_DOWN)
    [fallback] = rig.fallbacks()
    assert fallback["data"] == {"from": OWNERSHIP_TOOL_BRAIN, "to": OWNERSHIP_DIRECT, "mode": "active",
                                "reason": RUNTIME_DOWN, "fallback": True}
    assert fallback["level"] == "warning"
    assert rig.changes[-1] == (OWNERSHIP_TOOL_BRAIN, OWNERSHIP_DIRECT)  # on_change = the runtime flushes its queue


def test_an_unavailable_decider_is_an_immediate_fallback_and_recovery_waits_for_the_hold_down(tmp_path):
    rig = Rig(tmp_path, hold_down_s=60.0)
    assert rig.arbiter.executor_allowed()
    rig.health = Health(True, 3, 1, "unavailable")
    assert rig.arbiter.evaluate().reason == DECIDER_UNAVAILABLE
    rig.health = HEALTHY  # recovered at once, but flapping is not allowed
    rig.clock.now += 30
    view = rig.arbiter.evaluate()
    assert (view.ownership, view.reason) == (OWNERSHIP_DIRECT, HOLD_DOWN)
    rig.clock.now += 31
    assert rig.arbiter.evaluate().ownership == OWNERSHIP_TOOL_BRAIN


def test_an_unreadable_runtime_state_is_a_fallback_not_a_guess(tmp_path):
    rig = Rig(tmp_path)
    assert rig.arbiter.executor_allowed()

    def broken():
        raise RuntimeError("status exploded")

    rig.arbiter._status = broken
    assert rig.arbiter.executor_allowed() is False
    assert any(t["kind"] == "tool_brain.ownership.status_failed" and t["level"] == "error" for t in rig.traces)


def test_a_publication_that_cannot_be_written_keeps_the_screen_with_jarvis(tmp_path):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    rig = Rig(tmp_path, root=blocker)  # the runtime folder is a file: the publication is impossible
    assert rig.arbiter.executor_allowed() is False  # readers could not see a delegation, so none may exist
    assert rig.arbiter.view.reason == PUBLISH_FAILED
    assert any(t["kind"] == "tool_brain.ownership.publish_failed" for t in rig.traces)


def test_closing_publishes_jarvis_at_once_so_readers_never_wait_for_the_ttl(tmp_path):
    import asyncio

    rig = Rig(tmp_path)
    assert rig.arbiter.executor_allowed()
    asyncio.run(rig.arbiter.close())
    seen = read_ownership(tmp_path, wall=rig.clock)
    assert (seen.ownership, seen.reason) == (OWNERSHIP_DIRECT, SHUTDOWN)


# ------------------------------------------------------------------ lecture fail-safe


def test_readers_default_to_jarvis_with_no_publication_or_no_folder(tmp_path):
    assert read_ownership(None).ownership == OWNERSHIP_DIRECT
    view = read_ownership(tmp_path)
    assert (view.ownership, view.reason, view.fallback) == (OWNERSHIP_DIRECT, NO_PUBLICATION, False)  # the default install


def test_a_stale_corrupt_or_foreign_publication_is_jarvis_and_says_why(tmp_path):
    rig = Rig(tmp_path)
    assert rig.arbiter.executor_allowed()
    rig.clock.now += TTL_S + 1  # the arbiter stopped beating (crash): the TTL protects the screen
    stale = read_ownership(tmp_path, wall=rig.clock)
    assert (stale.ownership, stale.reason, stale.fallback) == (OWNERSHIP_DIRECT, STALE_PUBLICATION, True)
    path = ownership_path(tmp_path)
    for text in ("not json", json.dumps({"schema": "other/1"}), json.dumps({"schema": SCHEMA, "ownership": "who"}),
                 json.dumps([1, 2]), json.dumps({"schema": SCHEMA, "ownership": "tool_brain", "mode": "active",
                                                  "reason": "x", "since": "soon", "beat": 1})):
        path.write_text(text, encoding="utf-8")
        bad = read_ownership(tmp_path, wall=rig.clock)
        assert (bad.ownership, bad.reason) == (OWNERSHIP_DIRECT, UNREADABLE_PUBLICATION), text


# ------------------------------------------------------------------ outils délégués (côté Jarvis)


def test_jarvis_loses_exactly_the_ui_tools_the_executor_can_run_and_nothing_else():
    taken = jarvis_delegated_tools()
    assert taken == {("jarvis-display", name) for name in (
        "scene_move", "scene_update_object", "scene_update_many", "scene_pin", "scene_link", "scene_unlink",
        "scene_archive")} | {("jarvis-workspace", "board_switch")}
    for server, name in taken:  # derived from ToolMeta: a UI write on a server declared to the main brain
        meta = tool_meta(server, name)
        assert meta.ui_surface is not None and meta.side_effect != "read"
    # reads, content production, the intent tool and the Tool Brain-only surface server stay as they were
    assert not {("jarvis-display", "scene_create_object"), ("jarvis-display", "scene_add_artifact"),
                ("jarvis-display", "scene_inspect"), ("jarvis-display", "ui_intent_publish")} & taken
    assert not any(server == "jarvis-surface" for server, _ in taken)
    assert next(s for s in SERVERS if s.server == "jarvis-surface").registration == "tool_brain"


def publish(tmp_path, ownership, reason, *, beat, mode="active"):
    ownership_path(tmp_path).write_text(json.dumps({
        "schema": SCHEMA, "ownership": ownership, "mode": mode, "reason": reason, "since": beat, "beat": beat}), encoding="utf-8")


async def test_a_delegated_display_tool_is_refused_before_anything_reaches_the_scene(tmp_path):
    publish(tmp_path, OWNERSHIP_TOOL_BRAIN, ACTIVE_HEALTHY, beat=1000.0)
    events: list[tuple] = []
    spy = SpyTransport()
    gate = DelegationGate(tmp_path, server="jarvis-display", wall=lambda: 1001.0,
                          emit=lambda kind, message, **extra: events.append((kind, extra["data"])))
    tools = SceneDisplayTools(spy, delegation=gate)
    calls = {
        "scene_move": lambda: tools.move(dx=1, dy=1, object_ids=["a"]),
        "scene_update_object": lambda: tools.update_object(object_id="a", visibility="hidden"),
        "scene_update_many": lambda: tools.update_many(object_ids=["a"], visibility="hidden"),
        "scene_pin": lambda: tools.pin(pinned=True, object_ids=["a"]),
        "scene_archive": lambda: tools.archive(object_ids=["a"]),
        "scene_link": lambda: tools.link(from_id="a", to_id="b", kind="explains"),
        "scene_unlink": lambda: tools.unlink(relation_id="r"),
    }
    assert set(calls) == {name for server, name in jarvis_delegated_tools() if server == "jarvis-display"}
    for name, call in calls.items():
        with pytest.raises(DisplayToolError) as refused:
            await call()
        assert refused.value.code == UI_DELEGATED and "ui_intent_publish" in str(refused.value), name
    assert spy.commands == []  # double execution impossible: not one command left the server
    assert [data["code"] for kind, data in events if kind == "ui_ownership.refused"] == [UI_DELEGATED] * len(calls)


def test_content_tools_and_reads_stay_available_when_the_screen_is_delegated(tmp_path):
    publish(tmp_path, OWNERSHIP_TOOL_BRAIN, ACTIVE_HEALTHY, beat=1000.0)
    gate = DelegationGate(tmp_path, server="jarvis-display", wall=lambda: 1001.0)
    assert gate.view().delegated
    for tool in ("scene_create_object", "scene_add_artifact", "scene_inspect", "scene_query", "scene_get", "scene_capture",
                 "ui_intent_publish", "prefab_search"):
        assert gate.refusal(tool) is None, tool  # producing and reading content stay with Jarvis
    assert gate.refusal("scene_move") is not None


async def test_every_non_delegated_state_leaves_jarvis_executing_exactly_as_today(tmp_path):
    answers = []

    async def answer(command):  # noqa: ANN001
        answers.append(command["op"])
        return {"outcome": "applied", "reason": None, "scene_id": "s", "epoch": "e", "revision": 1,
                "patch": {"schema_version": 1, "revision": 1, "ops": [{"op": "delete_relation", "relation_id": "x"}]}}

    async def snapshot():
        return {"scene_id": "s", "epoch": "e", "revision": 0, "snapshot": {
            "schema_version": 1, "scene_id": "s", "revision": 0, "objects": [], "relations": [], "archived_ids": []}}

    def delegated(root):
        return DelegationGate(root, server="jarvis-display", wall=lambda: 1001.0)

    scenarios = {
        "no publication (default install)": lambda: None,
        "shadow": lambda: publish(tmp_path, OWNERSHIP_DIRECT, MODE_SHADOW, beat=1000.0, mode="shadow"),
        "fallback": lambda: publish(tmp_path, OWNERSHIP_DIRECT, RUNTIME_DOWN, beat=1000.0),
        "stale tool_brain publication": lambda: publish(tmp_path, OWNERSHIP_TOOL_BRAIN, ACTIVE_HEALTHY, beat=100.0),
        "corrupt publication": lambda: ownership_path(tmp_path).write_text("{", encoding="utf-8"),
    }
    for label, arrange in scenarios.items():
        arrange()
        tools = SceneDisplayTools(SpyTransport(command=answer, snapshot=snapshot), delegation=delegated(tmp_path))
        before = len(answers)
        await tools.unlink(relation_id="r")
        assert len(answers) == before + 1, label
    assert display_mcp.delegation_for(None, None) is None  # no runtime folder: no gate, Jarvis keeps the screen


def test_the_fallback_to_jarvis_is_traced_once_per_change_by_the_reader_too(tmp_path):
    publish(tmp_path, OWNERSHIP_TOOL_BRAIN, ACTIVE_HEALTHY, beat=100.0)  # stale
    events: list[tuple] = []
    gate = DelegationGate(tmp_path, server="jarvis-display", wall=lambda: 1001.0,
                          emit=lambda kind, message, **extra: events.append((kind, extra["level"], extra["data"]["reason"])))
    for _ in range(3):
        assert gate.refusal("scene_move") is None
    assert events == [("ui_ownership.fallback", "warning", STALE_PUBLICATION)]


# ------------------------------------------------------------------ une seule voix : jamais deux acteurs


def test_the_executor_and_jarvis_are_never_both_allowed_in_any_state(tmp_path):
    """Exclusion mutuelle : l'exécuteur lit l'arbitre, Jarvis lit la publication de ce même arbitre."""

    states = [HEALTHY, Health(False, 3, 0, "completed"), Health(True, 0, 0, None), Health(True, 3, 1, "unavailable"),
              Health(True, 3, 3, "failed"), HEALTHY]
    for mode in ("off", "shadow", "active"):
        root = tmp_path / mode
        rig = Rig(root, mode, hold_down_s=0.0)
        gate = DelegationGate(root, server="jarvis-display", wall=rig.clock)
        for health in states:
            rig.health = health
            executor_acts = rig.arbiter.executor_allowed()
            jarvis_acts = gate.refusal("scene_move") is None
            assert executor_acts != jarvis_acts, (mode, health)
            assert executor_acts == (mode == "active" and decide(mode, health)[0] == OWNERSHIP_TOOL_BRAIN)


# ------------------------------------------------------------------ Board : même porte


class _Body:
    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    async def read(self, limit: int) -> bytes:
        return self._raw


class _Request:
    can_read_body = True

    def __init__(self, payload: dict) -> None:
        self.content = _Body(json.dumps(payload).encode())


async def _forwarded(routes):
    sent = []

    async def forward(method, path, **kw):
        sent.append(path)
        from aiohttp import web
        return web.json_response({"ok": True})

    routes._forward = forward
    return sent


async def test_a_brain_board_switch_is_refused_while_delegated_and_a_user_switch_never_is(tmp_path):
    seen = []
    refusal = "board_switch refusé : le Tool Brain possède l'écran"
    routes = BoardSessionRoutes(transport=None, journal=RuntimeJournal(tmp_path), ask_in_flight=lambda: False,
                                wait_asks_idle=None, delegation=lambda tool: seen.append(tool) or refusal)
    sent = await _forwarded(routes)
    refused = await routes._transition(_Request({"board_id": "b1", "origin": "brain"}), "/v1/boards/switch", action="switch")
    assert refused.status == 409 and json.loads(refused.body)["error"]["code"] == UI_DELEGATED and sent == []
    allowed = await routes._transition(_Request({"board_id": "b1", "origin": "user"}), "/v1/boards/switch", action="switch")
    assert allowed.status == 200 and sent == ["/v1/boards/switch"]  # the user's own gesture is never delegated
    new_session = await routes._transition(_Request({"origin": "brain"}), "/v1/sessions/new", action="new_session")
    assert new_session.status == 200  # not a UI tool
    assert seen == ["board_switch"]
    free = BoardSessionRoutes(transport=None, journal=RuntimeJournal(tmp_path), ask_in_flight=lambda: False,
                              wait_asks_idle=None, delegation=lambda tool: None)
    await _forwarded(free)
    assert (await free._transition(_Request({"board_id": "b1", "origin": "brain"}), "/v1/boards/switch",
                                   action="switch")).status == 200


# ------------------------------------------------------------------ S8 rework (independent QA F2, F3)


def test_a_transient_read_error_is_retried_once_before_the_fail_safe_fallback(tmp_path, monkeypatch):
    from pathlib import Path

    rig = Rig(tmp_path)
    assert rig.arbiter.executor_allowed()
    real, calls = Path.read_text, []

    def flaky(self, *args, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError("replace in progress")
        return real(self, *args, **kw)

    monkeypatch.setattr(Path, "read_text", flaky)
    assert read_ownership(tmp_path, wall=rig.clock).ownership == OWNERSHIP_TOOL_BRAIN and len(calls) == 2
    calls.clear()

    def broken(self, *args, **kw):
        calls.append(1)
        raise PermissionError("locked")

    monkeypatch.setattr(Path, "read_text", broken)
    view = read_ownership(tmp_path, wall=rig.clock)
    assert (view.ownership, view.reason) == (OWNERSHIP_DIRECT, UNREADABLE_PUBLICATION) and len(calls) == 2  # bounded


async def test_a_deferred_brain_switch_is_dropped_if_the_tool_brain_owns_the_screen_when_it_fires(tmp_path):
    state = {"refusal": None}
    routes = BoardSessionRoutes(transport=None, journal=RuntimeJournal(tmp_path), ask_in_flight=lambda: False,
                                wait_asks_idle=None, delegation=lambda tool: state["refusal"])
    sent = await _forwarded(routes)
    state["refusal"] = "board_switch refusé : le Tool Brain possède l'écran"  # delegated while the switch waited
    from jarvis.runtime import board_routes

    class Transport:
        async def forward(self, method, path, *, params=None, body=None):
            sent.append(path)
            return 200, {}

    routes._transport = Transport()
    await routes._send_deferred(board_routes._Deferred("switch", "/v1/boards/switch", b'{"board_id": "b"}', "b"))
    assert sent == []
    rows = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(r.get("kind") == "board.request.deferred_delegated" and r["data"]["code"] == UI_DELEGATED for r in rows)
    state["refusal"] = None
    await routes._send_deferred(board_routes._Deferred("switch", "/v1/boards/switch", b'{"board_id": "b"}', "b"))
    assert sent == ["/v1/boards/switch"]

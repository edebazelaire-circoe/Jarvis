"""Reprise QA de la Slice 04a (handoff board-session), faite après la Slice 04b.

B1 relais d'un cerveau rétrogradé pendant l'attente, S1 identifiant de reprise
d'un autre CLI, S2 nouvelle Session par la transaction de Core, S3 mode
enregistré lu sur le Board, S4 Core redémarré, S5 tests manquants, NITs.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from aiohttp import web

from jarvis.adapters.control_center_brain import ControlCenterBrainBackend
from jarvis.core.brain_service import BRAIN_SPEECH_WITHHELD_KIND
from jarvis.domain.workspace_board import BindingStatus, BoardError, BoardErrorCode, BrainLifecycle
from jarvis.runtime import control_center as control_center_module
from tests.unit.test_board_brains import (
    CodexStub, Timers, binding as pool_binding, launches, make_pool, name_session, start_subagent,  # noqa: F401
)
from tests.unit.test_board_brains_control_center import (
    JsonRequest, StubAgent, binding, core, make_control, trace,  # noqa: F401
)
from tests.unit.test_board_switch_control_center import Stack


@pytest.fixture
async def stack(tmp_path):
    stack = Stack(tmp_path)
    await stack.serve_control()
    try:
        yield stack
    finally:
        await stack.close()


# ------------------------------------------------------------------ B1


async def test_b1_a_poll_open_while_the_brain_is_demoted_returns_nothing(tmp_path):
    control = make_control(tmp_path)
    first = await control.board_brains.activate(binding("conv-a"))
    agent_a = first.agent
    seen = json.loads((await control.agent_notices(JsonRequest(None, {"after": "0", "wait": "0"}))).text)
    release = asyncio.Event()
    original = agent_a.wait_notices

    async def wait_notices(after, *, timeout_s=25.0):  # noqa: ANN001
        await release.wait()
        return await original(after, timeout_s=timeout_s)

    agent_a.wait_notices = wait_notices
    agent_a.start_subagent("t1")
    poll = asyncio.create_task(control.agent_notices(JsonRequest(
        None, {"after": str(seen["last_seq"]), "wait": "25", "epoch": seen["epoch"]})))
    await asyncio.sleep(0)
    second = await control.board_brains.activate(binding("conv-b"))     # A rétrogradé pendant l'attente
    assert first.lifecycle is BrainLifecycle.BACKGROUND_RUNNING
    agent_a.notice("A a fini en arrière-plan.")                          # son sous-agent finit
    release.set()

    body = json.loads((await poll).text)
    assert body["notices"] == []
    assert body["epoch"] == second.agent.notice_epoch and body["conversation_id"] == "conv-b"
    assert trace(tmp_path, "board_brain.notices_withheld")[-1]["data"]["count"] == 1


async def test_b1_second_layer_core_withholds_a_notice_named_for_an_inactive_board(stack, monkeypatch):
    """Même si un relais passait, Core le retient : il porte la conversation de son Board."""

    core = await stack.start_core()
    a = (await core.sessions.current()).binding
    _, created = await stack.call("POST", "/api/boards", json={"title": "Projet B"})
    await stack.call("POST", "/api/boards/switch", json={"board_id": created["board"]["board_id"]})
    sink: list = []
    monkeypatch.setattr(core.brain, "_diagnostics", type("S", (), {
        "emit": lambda self, kind, message, level="info", data=None: sink.append((kind, data))})())

    from jarvis.domain.v2 import BrainNotice

    notice = BrainNotice("A a fini en arrière-plan.", a.conversation_id)
    assert not await core.brain.announce_notice(str(notice), conversation_id=notice.conversation_id)
    assert [data["conversation_id"] for kind, data in sink if kind == BRAIN_SPEECH_WITHHELD_KIND] == [a.conversation_id]


async def test_b1_the_backend_reads_the_notice_conversation(tmp_path):
    async def notices(request):
        return web.json_response({"ok": True, "supported": True, "epoch": "e1", "last_seq": 1,
                                  "conversation_id": "conv-a", "notices": [{"seq": 1, "text": "Fini."}]})

    app = web.Application()
    app.router.add_get("/api/agent/notices", notices)
    runner = web.AppRunner(app)
    await runner.setup()
    from tests.unit.test_board_brains_control_center import free_port

    port = free_port()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    backend = ControlCenterBrainBackend(base_url=f"http://127.0.0.1:{port}")
    backend._notice_epoch, backend._notice_after = "e1", 0
    try:
        (notice,) = await backend.next_notices()
    finally:
        await backend.close()
        await runner.cleanup()
    assert notice["text"] == "Fini." and notice["conversation_id"] == "conv-a"


# ------------------------------------------------------------------ S1


async def test_s1_a_claude_session_id_never_resumes_a_codex_brain(tmp_path, launches):
    cli = {"v": "claude"}
    codexes: list[CodexStub] = []

    def build(agent_cli: str):  # noqa: ANN202
        if agent_cli == "codex":
            codexes.append(CodexStub(tmp_path))
            return codexes[-1]
        from jarvis.runtime.claude_local import ClaudeLocalAgent
        return ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path)

    pool = make_pool(tmp_path, factory=build)
    pool._selected_cli = lambda: cli["v"]
    a = pool_binding("conv-a")
    entry = await pool.activate(a)
    name_session(entry.agent, "claude-sess-A")
    await pool.activate(pool_binding("conv-b"))
    assert entry.resume_id("claude") == "claude-sess-A"

    cli["v"] = "codex"
    await pool.activate(a)
    assert codexes[-1].session_id is None and codexes[-1].starts == [None], "fresh Codex, no Claude uuid"
    assert entry.to_payload()["agent_session_id"] is None


async def test_s1_a_codex_thread_from_core_is_not_given_to_claude(tmp_path, launches):
    pool = make_pool(tmp_path)
    entry = await pool.activate(pool_binding("conv-a", agent_cli="codex", agent_session_id="thread-1"))
    assert entry.agent.session_id != "thread-1"
    assert "--resume" not in launches.argv[-1]


# ------------------------------------------------------------------ S2


async def test_s2_restart_goes_through_core_and_starts_exactly_one_fresh_cli(stack):
    core = await stack.start_core()
    before = await core.sessions.current()
    old_agent = stack.control.agent
    from tests.unit.test_scene_settings_ui import _RestartRequest

    response = await stack.control.agent_restart(_RestartRequest(b'{"new_conversation": true}'))
    payload = json.loads(response.text)
    after = await core.sessions.current()

    assert after.session.jarvis_session_id != before.session.jarvis_session_id
    assert payload["board_brain"]["conversation_id"] == after.binding.conversation_id
    assert stack.control.agent is not old_agent and stack.control.agent.starts == [None], "one fresh CLI"
    assert after.binding.agent_session_id == stack.control.agent.session_id


async def test_s2_a_failed_start_leaves_core_and_the_control_center_unchanged(stack):
    core = await stack.start_core()
    before = await core.sessions.current()
    foreground = stack.control.board_brains.foreground

    class Broken(StubAgent):
        async def start(self, *, resume: bool = True) -> dict:
            raise RuntimeError("Claude CLI not found")

    stack.control.board_brains._factory = lambda cli: Broken(cli, stack.tmp_path)
    from tests.unit.test_scene_settings_ui import _RestartRequest

    with pytest.raises(web.HTTPServiceUnavailable) as refused:
        await stack.control.agent_restart(_RestartRequest(b'{"new_conversation": true}'))
    assert "board_activation_failed" in refused.value.text
    after = await core.sessions.current()
    assert after.session == before.session and after.binding.conversation_id == before.binding.conversation_id
    assert stack.control.board_brains.foreground is foreground
    assert trace(stack.tmp_path, "agent.restart.session_failed")[-1]["level"] == "error"


# ------------------------------------------------------------------ S3


async def test_s3_the_stored_mode_shown_is_the_active_board_mode(stack):
    core = await stack.start_core()
    await core.interaction_mode.request("presentation", source="control_center")   # choix sur le Board
    await core.boards.drain()
    settings = stack.control._settings()
    assert settings.get("interaction_mode", {}).get("mode", "assistant") != "presentation"

    status = await stack.control._interaction_mode_status(settings)
    assert status["stored"] == "presentation", "the Board's mode, not the global preference"


# ------------------------------------------------------------------ S4


async def test_s4_after_a_core_restart_reports_go_to_the_new_binding(stack):
    core = await stack.start_core()
    old = await core.sessions.current()
    await stack.stop_core()
    core = await stack.start_core()
    new = await core.sessions.current()
    assert stack.control.board_brains.foreground.key == new.binding.conversation_id

    await stack.control.agent_ask(JsonRequest({"text": "bonjour",
                                               "conversation": {"conversation_id": new.binding.conversation_id}}))
    for _ in range(100):
        if (await core.sessions.current()).binding.agent_session_id:
            break
        await asyncio.sleep(0.02)
    current = await core.sessions.current()
    assert current.binding.agent_cli == "claude" and current.binding.agent_session_id == stack.control.agent.session_id
    closed = next(b for b in await core.boards._repo.list_bindings(old.session.jarvis_session_id))
    assert closed.status is BindingStatus.CLOSED
    assert all(r["data"]["jarvis_session_id"] != old.session.jarvis_session_id
               for r in trace(stack.tmp_path, "board_brain.reported")[-1:])


# ------------------------------------------------------------------ S5


async def test_s5_resync_fans_out_to_every_pool_agent(tmp_path):
    class Ingress:
        def __init__(self) -> None:
            self.offered = []
            self.on_resync = None

        def offer(self, observation) -> None:  # noqa: ANN001
            self.offered.append(observation)

    ingress = Ingress()
    control = make_control(tmp_path, work_ingress=ingress)
    first = await control.board_brains.activate(binding("conv-a"))
    first.agent.start_subagent("t-a")
    second = await control.board_brains.activate(binding("conv-b"))
    second.agent.start_subagent("t-b")
    ingress.offered.clear()

    assert control._resync_work() == 2
    assert sorted(o.board_id for o in ingress.offered) == sorted([first.board_id, second.board_id])


async def test_s5_an_undetermined_board_ownership_replays_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(control_center_module, "INTERACTION_MODE_REPLAY_BACKOFF_S", 0.0)
    control = make_control(tmp_path)

    async def unknown() -> None:
        return None

    replayed = []

    async def reconcile(*args, **kwargs):  # noqa: ANN002, ANN003
        replayed.append(kwargs)

    control._core_boards_own_interaction_mode = unknown
    control._reconcile_interaction_mode = reconcile
    await control._replay_interaction_mode("core_restart")
    assert replayed == []


async def test_s5_aclose_stops_background_agents_too(tmp_path):
    control = make_control(tmp_path)
    first = await control.board_brains.activate(binding("conv-a"))
    first.agent.start_subagent("t-a")
    second = await control.board_brains.activate(binding("conv-b"))
    assert first.agent.running and second.agent.running
    await control.board_brains.aclose()
    assert first.agent.stops == 1 and second.agent.stops == 1


async def test_s5_a_closed_binding_is_refused_for_a_created_entry(tmp_path, launches):
    pool = make_pool(tmp_path)
    await pool.activate(pool_binding("conv-a"))
    with pytest.raises(BoardError) as refused:
        await pool.activate(pool_binding("conv-x", status=BindingStatus.CLOSED))
    assert refused.value.code is BoardErrorCode.SESSION_CLOSED
    assert pool.find("conv-x") is None and pool.foreground.key == "conv-a"


# ------------------------------------------------------------------ NITs


async def test_nit_a_failed_activation_undoes_the_adoption(tmp_path):
    control = make_control(tmp_path)

    async def broken(*, resume: bool = True) -> dict:
        raise RuntimeError("Claude CLI not found")

    control.agent.start = broken
    with pytest.raises(RuntimeError):
        await control.board_brains.activate(binding("conv-a"))
    assert control.board_brains.foreground.key is None and control.board_brains.find("conv-a") is None


async def test_nit_replay_retired_is_said_once(tmp_path, monkeypatch):
    monkeypatch.setattr(control_center_module, "INTERACTION_MODE_REPLAY_BACKOFF_S", 0.0)
    control = make_control(tmp_path)

    async def owned() -> bool:
        return True

    control._core_boards_own_interaction_mode = owned
    for _ in range(3):
        await control._replay_interaction_mode("core_restart")
    assert len(trace(tmp_path, "interaction.mode.replay_retired")) == 1


async def test_nit_a_forgotten_binding_forgets_its_last_report(tmp_path):
    control = make_control(tmp_path)
    first = await control.board_brains.activate(binding("conv-a"))
    control._binding_reports[first.binding.key] = ("claude", "s-1")
    control._forget_agents(first)
    assert first.binding.key not in control._binding_reports

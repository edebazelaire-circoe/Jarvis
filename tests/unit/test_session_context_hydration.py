"""Hydratation du cerveau depuis le Context actif (handoff session-context-recording, Slice 03).

Le bloc « Contexte actif » du brief, le dossier accordé au CLI (`--add-dir`
Claude, `writable_roots` Codex), et la reprise du fil gardé quand le Control
Center adopte la liaison d'une Session reprise. Contrat :
`docs/session-context.md` › *Agent hydration*.
"""

from __future__ import annotations

from pathlib import Path

from jarvis.adapters.control_center_brain import _turn_context
from jarvis.domain.brain_context import BrainDormantContext, BrainSessionContext
from jarvis.domain.v2 import BrainTurnInput
from jarvis.runtime import claude_local
from jarvis.runtime.claude_local import ClaudeLocalAgent
from jarvis.runtime.codex_local import CodexLocalAgent
from jarvis.runtime.control_center import build_agent_brief
from jarvis.runtime.session_context_brief import (
    BRIEF_CONTEXT_RULE, render_session_context_brief, sessions_root,
)
from tests.unit.test_board_brains import Launches, binding as pool_binding, make_pool, name_session, start_subagent
from tests.unit.test_board_brains_control_center import JsonRequest, StubAgent
from tests.unit.test_board_brains_control_center import make_control
from tests.unit.test_claude_tools_gateway_args import _Process


def _block(tmp_path: Path, **overrides) -> dict:
    root = tmp_path / "data" / "sessions"
    payload = BrainSessionContext(
        jarvis_session_id="jsess_abc", context_id="jctx_active", title="Analyse budget",
        workspace_path=str(root / "jsess_abc" / "contexts" / "jctx_active"), sessions_root=str(root),
        summary="Budget validé, reste le planning.",
        dormant=(BrainDormantContext("jctx_old", "Ancien"), BrainDormantContext("jctx_older", None)),
        omitted_dormant=2,
    ).to_payload()
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------ brief


def test_the_brief_carries_the_active_context_block(tmp_path):
    block = _block(tmp_path)
    brief = build_agent_brief({"addressing": "addressed", "session_context": block}, "note ça")
    assert "[Contexte actif]" in brief
    assert "jsess_abc" in brief and "jctx_active « Analyse budget »" in brief
    assert f"Dossier de travail : {block['workspace_path']}" in brief
    assert BRIEF_CONTEXT_RULE in brief
    assert "Budget validé, reste le planning." in brief
    assert "Contexts dormants (lecture seule, sur demande) : jctx_old « Ancien », jctx_older (+2 autres)" in brief
    assert brief.index("[Contexte actif]") < brief.index("[Demande]")


def test_the_brief_without_a_block_is_unchanged():
    plain = build_agent_brief({"addressing": "addressed"}, "salut")
    assert "Contexte actif" not in plain
    assert render_session_context_brief(None) == [] and render_session_context_brief({"context_id": "x"}) == []


def test_an_unavailable_workspace_is_said_and_never_offered(tmp_path):
    lines = render_session_context_brief(_block(tmp_path, workspace_error="context_workspace_unsafe", summary=""))
    joined = "\n".join(lines)
    assert "INDISPONIBLE (context_workspace_unsafe)" in joined and BRIEF_CONTEXT_RULE not in joined


def test_the_brief_rebounds_a_remote_summary(tmp_path):
    lines = render_session_context_brief(_block(tmp_path, summary="é" * 5000))
    assert len(lines[-2].encode("utf-8")) <= 2048  # résumé, avant la ligne des dormants


def test_sessions_root_must_be_absolute(tmp_path):
    assert sessions_root(_block(tmp_path)) == tmp_path / "data" / "sessions"
    assert sessions_root(_block(tmp_path, sessions_root="relative/sessions")) is None
    assert sessions_root(None) is None


def test_core_puts_the_block_in_the_turn_context(tmp_path):
    turn = BrainTurnInput(conversation_id="conv-1", text="salut")
    context = BrainSessionContext(jarvis_session_id="jsess_a", context_id="jctx_a", workspace_path="C:/d/x",
                                  sessions_root="C:/d")
    assert _turn_context(turn, None, session_context=context)["session_context"] == context.to_payload()
    assert "session_context" not in _turn_context(turn, None)


# ------------------------------------------------------------------ dossier accordé au CLI


async def _launch_claude(monkeypatch, agent: ClaudeLocalAgent) -> list[str]:
    started: list[list[str]] = []

    async def fake_exec(*args, **kwargs):  # noqa: ANN002, ANN003
        started.append([str(arg) for arg in args])
        return _Process()

    monkeypatch.setattr(claude_local.asyncio, "create_subprocess_exec", fake_exec)
    await agent.start()
    agent.process.returncode = 0  # type: ignore[union-attr]
    return started[-1]


async def test_claude_conversation_launch_carries_add_dir_for_the_sessions_root(tmp_path, monkeypatch):
    root = (tmp_path / "data" / "sessions").resolve()
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path)
    agent.add_dirs = (root,)
    argv = await _launch_claude(monkeypatch, agent)
    at = argv.index("--add-dir")
    assert argv[at + 1] == str(root) and argv[at + 2].startswith("--")  # variadique : suivi d'une option
    assert agent.launched_add_dirs == (root,)

    bare = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path)
    assert "--add-dir" not in await _launch_claude(monkeypatch, bare)


async def test_claude_refuses_a_relative_add_dir_and_says_so(tmp_path, monkeypatch):
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path)
    agent.add_dirs = (Path("relative/sessions"),)
    assert "--add-dir" not in await _launch_claude(monkeypatch, agent)
    assert agent.launched_add_dirs == ()
    from jarvis.runtime.journal import read_jsonl_tail
    kinds = [item["kind"] for item in read_jsonl_tail(tmp_path / "trace.jsonl", limit=200)]
    assert "agent.add_dir_refused" in kinds


def test_codex_gets_writable_roots_in_workspace_write_only(tmp_path):
    root = (tmp_path / "data" / "sessions").resolve()
    agent = CodexLocalAgent(runtime_root=tmp_path, cwd=tmp_path, command="codex.exe", permission_mode="workspace-write")
    agent.add_dirs = (root,)
    argv = agent._turn_command(resume=False)[0]
    assert f"sandbox_workspace_write.writable_roots=['{root}']" in argv
    agent.session_id = "thread-1"
    resumed = agent._turn_command(resume=True)[0]
    assert resumed[1:4] == ["exec", "resume", "thread-1"]
    assert f"sandbox_workspace_write.writable_roots=['{root}']" in resumed  # `-c` vaut aussi pour `exec resume`
    agent.permission_mode = "danger-full-access"
    assert not any("writable_roots" in part for part in agent._turn_command(resume=False)[0])
    agent.permission_mode = "workspace-write"
    agent.add_dirs = (Path("C:/a'b/sessions"),)
    assert not any("writable_roots" in part for part in agent._turn_command(resume=False)[0])


# ------------------------------------------------------------------ reprise du fil gardé (Session reprise)


async def test_an_adopted_unused_claude_is_relaunched_on_the_kept_thread(tmp_path, monkeypatch):
    launches = Launches()
    monkeypatch.setattr(claude_local.asyncio, "create_subprocess_exec", launches)
    pool = make_pool(tmp_path)
    agent = pool.foreground_agent()
    await agent.start()  # le Control Center lance son agent neuf au démarrage
    assert Launches.resume_of(launches.argv[-1]) is None
    resumed = pool_binding("conv-a", agent_cli="claude", agent_session_id="claude-thread-1")
    entry = pool.adopt(resumed)
    assert pool.resume_pending(entry)
    assert await pool.relaunch(entry, reason="session_resume") is True
    assert Launches.resume_of(launches.argv[-1]) == "claude-thread-1"
    assert not pool.resume_pending(entry)


async def test_core_activation_of_an_adopted_unused_agent_resumes_too(tmp_path, monkeypatch):
    launches = Launches()
    monkeypatch.setattr(claude_local.asyncio, "create_subprocess_exec", launches)
    pool = make_pool(tmp_path)
    await pool.foreground_agent().start()
    entry = await pool.activate(pool_binding("conv-a", agent_cli="claude", agent_session_id="claude-thread-1"))
    assert entry.agent.state == "running"
    assert Launches.resume_of(launches.argv[-1]) == "claude-thread-1"


async def test_a_used_or_busy_agent_is_never_relaunched_behind_its_back(tmp_path, monkeypatch):
    launches = Launches()
    monkeypatch.setattr(claude_local.asyncio, "create_subprocess_exec", launches)
    pool = make_pool(tmp_path)
    entry = await pool.activate(pool_binding("conv-a", agent_cli="claude", agent_session_id="claude-thread-1"))
    name_session(entry.agent, "claude-thread-1")
    count = len(launches.argv)
    start_subagent(entry.agent, "task-1")
    assert await pool.relaunch(entry, reason="workspace_grant") is False
    assert len(launches.argv) == count and entry.agent.state == "running"


# ------------------------------------------------------------------ Control Center


class GrantStub(StubAgent):
    """`StubAgent` qui rapporte, comme Claude, les dossiers reçus à son lancement."""

    def __init__(self, cli: str, root: Path) -> None:
        super().__init__(cli, root)
        self.add_dirs: tuple[Path, ...] = ()
        self.launched_add_dirs: tuple[Path, ...] = ()

    async def start(self, *, resume: bool = True) -> dict:
        self.launched_add_dirs = tuple(self.add_dirs)
        return await super().start(resume=resume)


async def test_the_first_turn_with_a_context_grants_the_sessions_root_by_one_resumed_relaunch(tmp_path):
    from jarvis.runtime.control_center import ControlCenter
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path,
                            agent_factory=lambda cli: GrantStub(cli, tmp_path))
    agent = control.agent
    await agent.start()
    thread = agent.session_id
    block = _block(tmp_path)
    await control.agent_ask(JsonRequest({"text": "note ça", "context": {"addressing": "addressed",
                                                                           "session_context": block}}))
    root = Path(block["sessions_root"])
    assert agent.launched_add_dirs == (root,) and agent.session_id == thread  # même fil, relancé une fois
    assert agent.starts[-1] == thread
    assert "[Contexte actif]" in agent.asked[-1]
    starts = len(agent.starts)
    await control.agent_ask(JsonRequest({"text": "et ça", "context": {"addressing": "addressed",
                                                                         "session_context": block}}))
    assert len(agent.starts) == starts  # déjà accordé : aucune relance
    # Un agent créé ensuite (autre Board, nouvelle Session) reçoit le dossier dès sa naissance.
    other = control.board_brains.agent_for(control.board_brains.foreground, "codex")
    assert other.add_dirs == (root,)


async def test_make_control_still_builds_without_sessions(tmp_path):
    control = make_control(tmp_path)
    assert control._sessions_root is None


# ------------------------------------------------------------------ reprise QA Slice 03


def test_the_brief_asks_for_no_summary_bookkeeping(tmp_path):
    """MINOR-2 (décision PM) : un tour vocal ne tient pas `summary.md` ; il peut le lire."""

    from jarvis.runtime.session_context_brief import BRIEF_WRITE_RULE
    brief = build_agent_brief({"addressing": "addressed", "session_context": _block(tmp_path)}, "note ça")
    assert BRIEF_WRITE_RULE in brief and "Tiens-y" not in brief
    assert "que si l'utilisateur le demande" in BRIEF_WRITE_RULE


def test_claude_refuses_an_add_dir_with_a_cmd_metacharacter_through_a_shim_once(tmp_path):
    """M21 : un shim `.cmd` passe argv par `cmd.exe` ; `&` y couperait la commande."""

    from jarvis.runtime.journal import read_jsonl_tail
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path)
    risky = Path("C:/Users/a&b/data/sessions")
    agent.add_dirs = (risky,)
    assert agent._add_dir_args("C:/tools/claude.exe") == (risky,)  # binaire natif : rien à craindre
    assert agent._add_dir_args("C:/tools/claude.cmd") == ()
    assert agent._add_dir_args("C:/tools/claude.CMD") == ()        # dit une seule fois
    refused = [item for item in read_jsonl_tail(tmp_path / "trace.jsonl", limit=200)
               if item["kind"] == "agent.add_dir_refused"]
    assert len(refused) == 1 and refused[0]["data"]["code"] == "agent_add_dir_unsafe"


async def test_a_refused_add_dir_is_still_recorded_as_requested(tmp_path, monkeypatch):
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path)
    agent.add_dirs = (Path("relative/sessions"),)
    await _launch_claude(monkeypatch, agent)
    assert agent.launched_add_dirs == () and agent.requested_add_dirs == (Path("relative/sessions"),)


class RefusingGrantStub(GrantStub):
    """Comme `ClaudeLocalAgent` quand `_add_dir_args` refuse le chemin : demandé, jamais accordé."""

    async def start(self, *, resume: bool = True) -> dict:
        self.requested_add_dirs = tuple(self.add_dirs)
        result = await super().start(resume=resume)
        self.launched_add_dirs = ()
        return result


async def test_a_refused_grant_relaunches_once_never_at_every_turn(tmp_path):
    """MAJOR-1 : comparé à la demande, pas à l'accord ; trois tours, une seule relance."""

    from jarvis.runtime.control_center import ControlCenter
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path,
                            agent_factory=lambda cli: RefusingGrantStub(cli, tmp_path))
    agent = control.agent
    await agent.start()
    block = _block(tmp_path)
    counts = []
    for text in ("un", "deux", "trois"):
        await control.agent_ask(JsonRequest({"text": text, "context": {"addressing": "addressed",
                                                                       "session_context": block}}))
        counts.append(len(agent.starts))
    assert counts == [2, 2, 2]  # le lancement initial, puis une relance qui demande le dossier
    assert agent.launched_add_dirs == () and agent.requested_add_dirs == (Path(block["sessions_root"]),)
    assert len(agent.asked) == 3


async def test_a_relaunch_is_deferred_while_a_turn_is_in_flight(tmp_path):
    """M17 : jamais de relance pendant un tour ; dit, puis remis au prochain point sûr."""

    from jarvis.runtime.control_center import ControlCenter
    from tests.unit.test_board_brains_control_center import trace
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path,
                            agent_factory=lambda cli: GrantStub(cli, tmp_path))
    agent = control.agent
    await agent.start()
    control._learn_sessions_root(Path(_block(tmp_path)["sessions_root"]), source="test")
    control._asks_in_flight = 1
    async with control._agent_lock:
        assert await control._refresh_foreground_launch(control.board_brains.foreground, reason="t") is False
    assert len(agent.starts) == 1 and agent.stops == 0
    assert trace(tmp_path, "agent.relaunch_deferred")[-1]["data"]["reason"] == "t"
    control._asks_in_flight = 0
    async with control._agent_lock:
        assert await control._refresh_foreground_launch(control.board_brains.foreground, reason="t") is True
    assert len(agent.starts) == 2


async def test_a_turn_waits_for_a_relaunch_in_progress(tmp_path):
    """Un tour arrivé pendant une relance (verrou tenu) attend : il n'écrit pas au CLI qu'on arrête."""

    import asyncio
    from jarvis.runtime.control_center import ControlCenter
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path,
                            agent_factory=lambda cli: GrantStub(cli, tmp_path))
    agent = control.agent
    await agent.start()
    await control._agent_lock.acquire()  # la relance tient le verrou
    try:
        turn = asyncio.create_task(control.agent_ask(JsonRequest({"text": "pendant la relance"})))
        for _ in range(20):
            await asyncio.sleep(0)
        assert agent.asked == [] and not turn.done()
    finally:
        control._agent_lock.release()
    response = await asyncio.wait_for(turn, timeout=5)
    assert response.status == 200 and len(agent.asked) == 1
    assert control._asks_in_flight == 0


class LazyThreadStub(GrantStub):
    """Comme Claude : l'identifiant du fil n'existe qu'après le premier tour."""

    async def start(self, *, resume: bool = True) -> dict:
        self.starts.append(self.session_id if resume else None)
        self.running = True
        self.launched_add_dirs = tuple(self.add_dirs)
        return self.snapshot()


class SessionsStub:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.reports: list[dict] = []

    async def current_session(self) -> dict:
        return self.payload

    async def report_binding_agent(self, **report) -> dict:  # noqa: ANN003
        self.reports.append(report)
        return {}


async def test_startup_adoption_relaunches_the_fresh_cli_on_the_kept_thread(tmp_path):
    """M26 : le chemin principal de reprise du fil CLI au démarrage du Control Center."""

    from jarvis.runtime.control_center import ControlCenter
    kept = pool_binding("conv-kept", agent_cli="claude", agent_session_id="claude-thread-1")
    block = _block(tmp_path)
    sessions = SessionsStub({"binding": kept.to_payload(), "context": block})
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path, sessions=sessions,
                            agent_factory=lambda cli: LazyThreadStub(cli, tmp_path))
    agent = control.agent
    await agent.start()
    assert agent.starts == [None]
    await control._adopt_core_session()
    assert control.board_brains.foreground.key == "conv-kept"
    assert agent.starts == [None, "claude-thread-1"] and agent.stops == 1
    assert agent.launched_add_dirs == (Path(block["sessions_root"]),)


async def test_an_adopted_agent_with_work_is_not_stopped_to_resume_its_kept_thread(tmp_path, monkeypatch):
    """M16 : `_bring_up` ne coupe jamais un agent qui travaille, même pour reprendre le fil gardé."""

    launches = Launches()
    monkeypatch.setattr(claude_local.asyncio, "create_subprocess_exec", launches)
    pool = make_pool(tmp_path)
    agent = pool.foreground_agent()
    await agent.start()
    start_subagent(agent, "task-1")
    count = len(launches.argv)
    entry = await pool.activate(pool_binding("conv-a", agent_cli="claude", agent_session_id="claude-thread-1"))
    assert entry.agent is agent and agent.state == "running"
    assert len(launches.argv) == count  # ni arrêt ni relance : le sous-agent continue

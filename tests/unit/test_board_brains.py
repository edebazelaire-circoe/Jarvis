"""Pool des cerveaux de Board (handoff board-session, Slice 04a).

CLI Claude **réel** côté Python (`ClaudeLocalAgent`), processus factice : la
ligne de commande est capturée (preuve de `--resume <id>`), `stop()` tue
vraiment le « processus » et interrompt ses sous-agents — exactement ce qu'un
pool ne doit jamais faire à un agent qui travaille.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import itertools
from pathlib import Path

import pytest

from jarvis.domain.workspace_board import (
    BindingStatus, BoardConversationBinding, BoardError, BoardErrorCode, BrainLifecycle, new_board_id,
    new_session_id,
)
from jarvis.runtime import claude_local
from jarvis.runtime.agent_tasks import AgentTaskTracker
from jarvis.runtime.board_brains import BoardBrainPool
from jarvis.runtime.claude_local import ClaudeLocalAgent
from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail

T0 = datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)
SESSION = new_session_id()


# ------------------------------------------------------------------ doublures


class _BlockingStream:
    def __init__(self) -> None:
        self.closed = asyncio.Event()

    async def readline(self) -> bytes:
        await self.closed.wait()
        return b""


class _Stdin:
    def write(self, chunk: bytes) -> None:
        pass

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        pass


class _FakeCli:
    """Un processus CLI qui vit jusqu'à `terminate()`, comme le vrai."""

    _pids = itertools.count(7000)

    def __init__(self, argv: list[str]) -> None:
        self.argv = argv
        self.pid = next(self._pids)
        self.returncode: int | None = None
        self.stdin = _Stdin()
        self.stdout = _BlockingStream()
        self.stderr = _BlockingStream()

    def terminate(self) -> None:
        self.returncode = 0
        self.stdout.closed.set()
        self.stderr.closed.set()

    kill = terminate

    async def wait(self) -> int:
        return self.returncode or 0


class Launches:
    def __init__(self) -> None:
        self.argv: list[list[str]] = []

    async def __call__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        del kwargs
        process = _FakeCli([str(a) for a in args])
        self.argv.append(process.argv)
        return process

    @staticmethod
    def resume_of(argv: list[str]) -> str | None:
        return argv[argv.index("--resume") + 1] if "--resume" in argv else None


class Timers:
    """`call_later` manuel : rien ne part tant que le test ne tire pas."""

    class Handle:
        def __init__(self, delay: float, callback) -> None:  # noqa: ANN001
            self.delay, self.callback, self.cancelled = delay, callback, False

        def cancel(self) -> None:
            self.cancelled = True

    def __init__(self) -> None:
        self.handles: list[Timers.Handle] = []

    def __call__(self, delay: float, callback):  # noqa: ANN001, ANN204
        handle = Timers.Handle(delay, callback)
        self.handles.append(handle)
        return handle

    @property
    def armed(self) -> list[Timers.Handle]:
        return [handle for handle in self.handles if not handle.cancelled]

    def fire(self) -> None:
        for handle in self.armed:
            handle.cancelled = True
            handle.callback()


class CodexStub:
    """Codex : un processus par tour, pas de processus permanent."""

    def __init__(self, root: Path) -> None:
        self.journal = RuntimeJournal(root)
        self.subtasks = AgentTaskTracker(provider="codex", journal=self.journal)
        self.session_id: str | None = None
        self.state = "ready"
        self.starts: list[str | None] = []
        self.stops = 0

    async def start(self, *, resume: bool = True) -> dict:
        self.starts.append(self.session_id if resume else None)
        return {}

    async def stop(self) -> dict:
        self.stops += 1
        return {}

    async def restart(self) -> dict:
        raise AssertionError("the pool never restarts a Codex agent: restart() clears its thread")


def binding(conversation_id: str, *, board_id: str | None = None, agent_session_id: str | None = None,
            agent_cli: str = "pending", minutes: int = 0,
            status: BindingStatus = BindingStatus.OPEN) -> BoardConversationBinding:
    at = T0 + timedelta(minutes=minutes)
    return BoardConversationBinding(
        jarvis_session_id=SESSION, board_id=board_id or new_board_id(), conversation_id=conversation_id,
        agent_cli=agent_cli, created_at=at, last_active_at=at, lifecycle=BrainLifecycle.SUSPENDED,
        status=status, agent_session_id=agent_session_id,
    )


@pytest.fixture
def launches(monkeypatch) -> Launches:
    spy = Launches()
    monkeypatch.setattr(claude_local.asyncio, "create_subprocess_exec", spy)
    return spy


def make_pool(tmp_path: Path, *, cli: str = "claude", timers: Timers | None = None, max_live: int = 3,
              factory=None) -> BoardBrainPool:  # noqa: ANN001
    journal = RuntimeJournal(tmp_path)

    def build(agent_cli: str):  # noqa: ANN202
        if agent_cli == "codex":
            return CodexStub(tmp_path)
        return ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path)

    return BoardBrainPool(factory=factory or build, selected_cli=lambda: cli, journal=journal,
                          call_later=timers or Timers(), max_live=max_live)


def start_subagent(agent: ClaudeLocalAgent, task_id: str) -> None:
    agent._record({"type": "system", "subtype": "task_started", "task_id": task_id, "description": "Refactor",
                   "is_backgrounded": True, "task_type": "local_agent", "subagent_type": "general-purpose",
                   "session_id": agent.session_id})


def end_subagent(agent: ClaudeLocalAgent, task_id: str) -> None:
    agent._record({"type": "system", "subtype": "task_notification", "task_id": task_id, "status": "completed",
                   "summary": "Fait.", "session_id": agent.session_id})


def name_session(agent: ClaudeLocalAgent, session_id: str) -> None:
    agent._record({"type": "system", "subtype": "init", "session_id": session_id, "model": "claude-opus-5"})


def trace(tmp_path: Path, kind: str) -> list[dict]:
    return [item for item in read_jsonl_tail(tmp_path / "trace.jsonl", limit=2000) if item["kind"] == kind]


# ------------------------------------------------------------------ rétrogradation


async def test_a_demoted_agent_with_running_subagents_keeps_its_process(tmp_path, launches):
    pool = make_pool(tmp_path)
    board_a = binding("conv-a")
    first = await pool.activate(board_a)
    agent_a = first.agent
    name_session(agent_a, "claude-a")
    start_subagent(agent_a, "task-1")

    second = await pool.activate(binding("conv-b"))

    assert pool.foreground is second and second.lifecycle is BrainLifecycle.FOREGROUND
    assert first.lifecycle is BrainLifecycle.BACKGROUND_RUNNING
    assert agent_a.state == "running", "demotion must never stop a CLI that has sub-agents running"
    assert agent_a.subtasks.counts()["active"] == 1
    assert agent_a.speaks_notices is False and second.agent.speaks_notices is True
    # Le nouveau Board a un CLI neuf, sans reprise.
    assert len(launches.argv) == 2 and Launches.resume_of(launches.argv[-1]) is None
    demoted = trace(tmp_path, "board_brain.demoted")[-1]["data"]
    assert demoted["to"] == "background_running" and demoted["board_id"] == board_a.board_id


async def test_an_idle_demoted_agent_is_suspended_at_once_and_resumed_with_its_session_id(tmp_path, launches):
    pool = make_pool(tmp_path)
    first = await pool.activate(binding("conv-a"))
    name_session(first.agent, "claude-a")

    await pool.activate(binding("conv-b"))

    assert first.lifecycle is BrainLifecycle.SUSPENDED and first.agent.state != "running"
    assert first.saved_session_id == "claude-a"
    again = await pool.activate(binding("conv-a"))
    assert again is first and first.lifecycle is BrainLifecycle.FOREGROUND
    assert Launches.resume_of(launches.argv[-1]) == "claude-a"


async def test_a_background_agent_suspends_sixty_seconds_after_its_last_subagent_then_resumes(tmp_path, launches):
    timers = Timers()
    pool = make_pool(tmp_path, timers=timers)
    first = await pool.activate(binding("conv-a"))
    agent_a = first.agent
    name_session(agent_a, "claude-a")
    start_subagent(agent_a, "task-1")
    start_subagent(agent_a, "task-2")
    await pool.activate(binding("conv-b"))

    end_subagent(agent_a, "task-1")
    assert timers.armed == [], "one sub-agent still runs: no countdown yet"
    end_subagent(agent_a, "task-2")
    assert [handle.delay for handle in timers.armed] == [60.0]
    start_subagent(agent_a, "task-3")  # du travail repart : le compte à rebours tombe
    assert timers.armed == []
    end_subagent(agent_a, "task-3")
    assert len(timers.armed) == 1

    timers.fire()
    await pool.drain()

    assert first.lifecycle is BrainLifecycle.SUSPENDED and agent_a.state != "running"
    assert first.saved_session_id == "claude-a"
    suspended = trace(tmp_path, "board_brain.suspended")[-1]["data"]
    assert suspended["reason"] == "idle" and suspended["resumable"] is True
    await pool.activate(binding("conv-a"))
    assert Launches.resume_of(launches.argv[-1]) == "claude-a"
    await pool.aclose()


async def test_a_fresh_binding_with_a_stored_session_id_resumes_it(tmp_path, launches):
    """Core connaît l'identifiant de reprise (Control Center redémarré) : `--resume`."""

    pool = make_pool(tmp_path)
    await pool.activate(binding("conv-a"))
    await pool.activate(binding("conv-b", agent_cli="claude", agent_session_id="claude-b-old"))
    assert Launches.resume_of(launches.argv[-1]) == "claude-b-old"


# ------------------------------------------------------------------ plafond


async def test_the_cap_only_suspends_idle_agents_and_warns_when_everyone_works(tmp_path, launches):
    timers = Timers()
    pool = make_pool(tmp_path, timers=timers, max_live=3)
    entries = []
    for index, name in enumerate(("a", "b", "c")):
        entry = await pool.activate(binding(f"conv-{name}", minutes=index))
        start_subagent(entry.agent, f"task-{name}")
        entries.append(entry)
    fourth = await pool.activate(binding("conv-d", minutes=3))

    # Quatre CLI vivants, trois qui travaillent : personne n'est arrêté, c'est dit.
    assert all(entry.agent.state == "running" for entry in (*entries, fourth))
    exceeded = trace(tmp_path, "board_brain.cap_exceeded")
    assert exceeded and exceeded[-1]["level"] == "warning" and exceeded[-1]["data"]["live"] == 4

    # c finit son travail (compte à rebours armé, pas encore échu) ; e arrive.
    end_subagent(entries[2].agent, "task-c")
    await pool.activate(binding("conv-e", minutes=4))

    a, b, c = entries
    assert a.agent.state == "running" and b.agent.state == "running", "busy agents are never capped"
    assert c.agent.state != "running" and c.lifecycle is BrainLifecycle.SUSPENDED
    assert fourth.agent.state != "running"  # rétrogradé inactif : suspendu à la démotion
    assert pool.live_count() == 3
    assert trace(tmp_path, "board_brain.suspended")[-1]["data"]["reason"] == "cap"
    await pool.aclose()


# ------------------------------------------------------------------ Codex


async def test_codex_is_never_background_running_and_never_restarted(tmp_path):
    pool = make_pool(tmp_path, cli="codex")
    first = await pool.activate(binding("conv-a"))
    codex = first.agent
    codex.session_id = "thread-a"
    codex.subtasks.turn_started()  # un tour Codex en vol

    await pool.activate(binding("conv-b"))

    assert first.lifecycle is BrainLifecycle.SUSPENDED
    assert codex.stops == 0, "an in-flight Codex turn ends with its own process"
    assert first.saved_session_id == "thread-a"
    codex.subtasks.turn_finished()
    await pool.activate(binding("conv-a"))
    assert codex.starts[-1] == "thread-a"  # `codex exec resume thread-a`, sans restart()


# ------------------------------------------------------------------ refus et échecs


async def test_a_failed_start_changes_nothing(tmp_path, launches):
    pool = make_pool(tmp_path)
    first = await pool.activate(binding("conv-a"))

    class Broken(ClaudeLocalAgent):
        async def start(self, *, resume: bool = True) -> dict:
            raise RuntimeError("Claude CLI not found")

    pool._factory = lambda cli: Broken(runtime_root=tmp_path, cwd=tmp_path)
    with pytest.raises(RuntimeError, match="not found"):
        await pool.activate(binding("conv-b"))

    assert pool.foreground is first and first.agent.state == "running"
    assert pool.find("conv-b") is None


async def test_a_closed_binding_never_becomes_foreground(tmp_path, launches):
    pool = make_pool(tmp_path)
    with pytest.raises(BoardError) as refused:
        await pool.activate(binding("conv-a", status=BindingStatus.CLOSED))
    assert refused.value.code is BoardErrorCode.SESSION_CLOSED


async def test_a_new_session_gets_a_fresh_cli_and_forgets_the_old_one_once_suspended(tmp_path, launches):
    timers = Timers()
    pool = make_pool(tmp_path, timers=timers)
    old = await pool.activate(binding("conv-a"))
    name_session(old.agent, "claude-a")
    start_subagent(old.agent, "task-1")

    fresh = await pool.start_fresh(binding("conv-new"))

    assert pool.foreground is fresh and Launches.resume_of(launches.argv[-1]) is None
    assert old.agent.state == "running" and old.lifecycle is BrainLifecycle.BACKGROUND_RUNNING
    end_subagent(old.agent, "task-1")
    timers.fire()
    await pool.drain()
    assert pool.find("conv-a") is None, "a closed Session's suspended brain leaves the pool"


# ------------------------------------------------------------------ journal lié


async def test_each_pool_agent_journals_its_board_and_session(tmp_path, launches):
    pool = make_pool(tmp_path)
    board = binding("conv-a")
    entry = await pool.activate(board)

    started = [item for item in trace(tmp_path, "agent.start") if item["data"].get("pid")][-1]
    assert started["data"]["board_id"] == board.board_id
    assert started["data"]["jarvis_session_id"] == SESSION


async def test_a_background_agent_notice_is_journaled_unspoken(tmp_path, launches):
    pool = make_pool(tmp_path)
    first = await pool.activate(binding("conv-a"))
    start_subagent(first.agent, "task-1")
    await pool.activate(binding("conv-b"))

    assert first.agent.publish_notice("Le sous-agent a fini.", origin="task-notification") is True
    relayed = trace(tmp_path, "agent.unsolicited_result")[-1]["data"]
    assert relayed["spoken"] is False and relayed["board_id"] == first.board_id


def test_the_journal_context_is_merged_and_call_data_wins(tmp_path):
    journal = RuntimeJournal(tmp_path)
    journal.bind(board_id="default", jarvis_session_id=SESSION)
    journal.emit("x.one", "m", data={"board_id": "board_override", "n": 1})
    journal.emit("x.two", "m")
    journal.bind(board_id=None, jarvis_session_id=None)
    journal.emit("x.three", "m", data={"n": 3})

    lines = {item["kind"]: item["data"] for item in read_jsonl_tail(tmp_path / "trace.jsonl")}
    assert lines["x.one"] == {"board_id": "board_override", "jarvis_session_id": SESSION, "n": 1}
    assert lines["x.two"] == {"board_id": "default", "jarvis_session_id": SESSION}
    assert lines["x.three"] == {"n": 3}


# ------------------------------------------------------------------ arrêt voulu (QA Slice 04b, S3)


async def test_a_pool_suspension_is_journaled_as_a_requested_stop_not_an_error(tmp_path, launches, monkeypatch):
    def windows_terminate(self) -> None:  # noqa: ANN001 - `terminate()` sous Windows : code 1
        self.returncode = 1
        self.stdout.closed.set()
        self.stderr.closed.set()

    monkeypatch.setattr(_FakeCli, "terminate", windows_terminate)
    pool = make_pool(tmp_path)
    first = await pool.activate(binding("conv-a"))

    await pool.activate(binding("conv-b"))                   # A rétrogradé puis suspendu : arrêt voulu

    assert first.lifecycle is BrainLifecycle.SUSPENDED
    assert [s["data"]["reason"] for s in trace(tmp_path, "agent.stop")] == ["demoted"]
    assert all(e["level"] == "info" and e["data"]["reason"] == "demoted" for e in trace(tmp_path, "agent.exit"))
    errors = [item["kind"] for item in read_jsonl_tail(tmp_path / "errors.jsonl", limit=100)]
    assert "agent.exit" not in errors

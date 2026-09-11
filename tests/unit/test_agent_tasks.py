"""Les sous-tâches du brain, reconstituées depuis le flux `stream-json`.

Claude Code lance des sous-agents (outil `Agent`) et des commandes de fond
(`local_bash`) sans que Jarvis en sache rien d'autre que ce qui passe dans le
flux. Les séquences ci-dessous reprennent la forme des événements réellement
relevés dans `runtime/trace.jsonl` (identifiants raccourcis, prompts
anonymisés) : un appel `Agent` puis son `task_started`, un résultat
« async_launched » qui n'est pas une fin, des `task_progress` à chaque outil,
des messages de sous-agent marqués par `parent_tool_use_id`.

Ce qui doit tenir : une seule tâche par sous-agent quel que soit l'ordre
d'arrivée, une fin reconnue quelle que soit sa forme, rien d'« en cours » pour
toujours après l'arrêt du brain, et une mémoire bornée.
"""

from __future__ import annotations

import asyncio
import json

from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.runtime import claude_local, cli_catalog
from jarvis.runtime.agent_tasks import MAX_FINISHED_TASKS, MAX_TRACE_ENTRIES, format_duration
from jarvis.runtime.claude_local import ClaudeLocalAgent
from jarvis.runtime.codex_local import CodexLocalAgent
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.journal import read_jsonl_tail


SESSION = "ac329510-db70-42d4-84ac-5fddd9b11c0d"
T0 = 1_789_047_300.0


class Clock:
    def __init__(self, start: float = T0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def ms(seconds: float) -> int:
    return int(seconds * 1000)


# ------------------------------------------------------------------ événements


def agent_call(tool_use_id, description, *, parent=None, model=None, background=True, subagent_type=None,
               prompt="Rends le réglage persistant et ajoute les tests."):  # noqa: ANN001
    payload = {"description": description, "isolation": "worktree", "prompt": prompt}
    if background:
        payload["run_in_background"] = True
    if model:
        payload["model"] = model
    if subagent_type:
        payload["subagent_type"] = subagent_type
    return {
        "type": "assistant", "parent_tool_use_id": parent, "session_id": SESSION,
        "message": {"model": "claude-opus-5", "role": "assistant", "content": [
            {"type": "tool_use", "id": tool_use_id, "name": "Agent", "input": payload},
        ]},
    }


def tool_call(tool_use_id, name, payload, *, parent=None, model="claude-opus-5"):  # noqa: ANN001
    return {
        "type": "assistant", "parent_tool_use_id": parent, "session_id": SESSION,
        "message": {"model": model, "role": "assistant", "content": [
            {"type": "tool_use", "id": tool_use_id, "name": name, "input": payload},
        ]},
    }


def child_text(parent, text, *, model="claude-opus-5"):  # noqa: ANN001
    return {
        "type": "assistant", "parent_tool_use_id": parent, "session_id": SESSION,
        "message": {"model": model, "role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def tool_result(tool_use_id, content, *, parent=None, is_error=False, extra=None):  # noqa: ANN001
    event = {
        "type": "user", "parent_tool_use_id": parent, "session_id": SESSION,
        "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tool_use_id, "content": content, "is_error": is_error},
        ]},
    }
    if extra is not None:
        event["tool_use_result"] = extra
    return event


def async_launched(tool_use_id, agent_id, *, parent=None, resolved="claude-opus-5[1m]"):  # noqa: ANN001
    return tool_result(
        tool_use_id,
        [{"type": "text", "text": "Async agent launched successfully."}],
        parent=parent,
        extra={"isAsync": True, "status": "async_launched", "agentId": agent_id, "description": "...",
               "resolvedModel": resolved, "prompt": "..."},
    )


def task_started(task_id, tool_use_id, description, *, task_type="local_agent", background=True, depth=1,
                 subagent_type="general-purpose"):  # noqa: ANN001
    event = {
        "type": "system", "subtype": "task_started", "task_id": task_id, "description": description,
        "is_backgrounded": background, "task_type": task_type, "session_id": SESSION,
    }
    if tool_use_id is not None:
        event["tool_use_id"] = tool_use_id
    if task_type == "local_agent":
        event.update(subagent_type=subagent_type, spawn_depth=depth, prompt="Rends le réglage persistant.")
    return event


def progress(task_id, tool_use_id, activity, *, tokens, tool_uses, last_tool="Read"):  # noqa: ANN001
    return {
        "type": "system", "subtype": "task_progress", "task_id": task_id, "tool_use_id": tool_use_id,
        "description": activity, "subagent_type": "general-purpose",
        "usage": {"total_tokens": tokens, "tool_uses": tool_uses, "duration_ms": 7805},
        "last_tool_name": last_tool, "session_id": SESSION,
    }


def notification(task_id, tool_use_id, status, summary=""):  # noqa: ANN001
    return {
        "type": "system", "subtype": "task_notification", "task_id": task_id, "tool_use_id": tool_use_id,
        "status": status, "output_file": "", "summary": summary, "session_id": SESSION,
    }


def task_updated(task_id, patch):  # noqa: ANN001
    return {"type": "system", "subtype": "task_updated", "task_id": task_id, "patch": patch, "session_id": SESSION}


def user_input(text):  # noqa: ANN001
    return {"type": "user", "message": {"role": "user", "content": text}}


RESULT = {"type": "result", "subtype": "success", "result": "C'est lancé.", "duration_ms": 1200, "session_id": SESSION}
INIT = {"type": "system", "subtype": "init", "model": "claude-opus-5[1m]", "cwd": "C:\\Projects\\jarvis", "session_id": SESSION}


# ---------------------------------------------------------------------- outils


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def agent(tmp_path, clock):
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path, command="claude")
    agent.subtasks.clock = clock
    return agent


def feed(agent, *events):  # noqa: ANN001
    for event in events:
        agent._record(event)


def tasks_of(agent) -> list[dict]:  # noqa: ANN001
    return agent.tasks_snapshot()["tasks"]


def only_task(agent) -> dict:  # noqa: ANN001
    tasks = tasks_of(agent)
    assert len(tasks) == 1, tasks
    return tasks[0]


def journal(tmp_path, prefix="agent.subagent."):  # noqa: ANN001
    return [item for item in read_jsonl_tail(tmp_path / "trace.jsonl", limit=1000) if item["kind"].startswith(prefix)]


class FakeRunningProcess:
    pid = 4242

    def __init__(self) -> None:
        self.returncode: int | None = None

    def terminate(self) -> None:
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode or 0


# =====================================================================
# Fusion appel Agent / task_started
# =====================================================================


def test_the_agent_call_and_its_task_started_are_one_task(agent, clock):
    feed(agent, user_input("Lance deux sous-agents"), INIT)
    feed(agent, agent_call("toolu_01FEy", "Persist voice arch setting"))
    assert only_task(agent)["id"] == "toolu_01FEy"  # pas encore de task_id

    clock.advance(1.5)
    feed(agent, task_started("a6151a92a33e2339a", "toolu_01FEy", "Persist voice arch setting"))

    task = only_task(agent)
    assert task["id"] == "a6151a92a33e2339a"
    assert task["tool_use_id"] == "toolu_01FEy"
    assert task["kind"] == "agent" and task["provider"] == "claude"
    assert task["subagent_type"] == "general-purpose"
    assert task["status"] == "running" and task["background"] is True
    # Le chronomètre part de l'appel, pas de la confirmation du CLI.
    assert task["started_ms"] == ms(T0)
    assert agent.tasks_snapshot()["active_count"] == 1


def test_a_task_started_seen_before_the_agent_call_is_merged_not_duplicated(agent):
    feed(agent, task_started("a1", "toolu_A", "Meeting Planner"))
    feed(agent, agent_call("toolu_A", "Meeting Planner", model="sonnet", prompt="Planifie la réunion."))

    task = only_task(agent)
    assert task["id"] == "a1"
    assert task["model"] == "sonnet"
    assert task["prompt"].startswith("Rends le réglage persistant")  # celui du task_started, arrivé d'abord


def test_the_launch_result_links_a_task_started_that_had_no_call_id(agent):
    feed(agent, task_started("a1", None, "Meeting Planner"))
    feed(agent, agent_call("toolu_A", "Meeting Planner"))
    assert len(tasks_of(agent)) == 2  # rien ne les relie encore

    feed(agent, async_launched("toolu_A", "a1"))

    task = only_task(agent)
    assert task["id"] == "a1" and task["tool_use_id"] == "toolu_A"


# =====================================================================
# Fins
# =====================================================================


def test_an_async_launch_is_a_start_not_an_end(agent):
    feed(
        agent,
        agent_call("toolu_A", "Persist voice arch setting"),
        task_started("a1", "toolu_A", "Persist voice arch setting"),
        async_launched("toolu_A", "a1"),
    )

    task = only_task(agent)
    assert task["status"] == "running" and task["ended_ms"] is None
    assert task["model"] == "claude-opus-5[1m]"  # resolvedModel


def test_a_foreground_agent_ends_with_its_tool_result(agent, clock):
    feed(
        agent,
        agent_call("toolu_A", "Audit rapide", background=False),
        task_started("a1", "toolu_A", "Audit rapide", background=False),
        child_text("toolu_A", "Je regarde."),
    )
    clock.advance(192)
    feed(agent, tool_result(
        "toolu_A", [{"type": "text", "text": "Rien d'anormal dans le module."}],
        extra={"status": "completed", "totalTokens": 5120, "totalToolUseCount": 7, "totalDurationMs": 192000},
    ))

    task = only_task(agent)
    assert task["status"] == "completed"
    assert task["ended_ms"] == ms(T0 + 192)
    assert task["tokens"] == 5120 and task["tool_uses"] == 7
    assert task["summary"] == "Rien d'anormal dans le module."
    assert agent.tasks_snapshot()["active_count"] == 0
    # Le compte rendu final figure dans la trace de la tâche.
    last = agent.task_trace("a1")["entries"][-1]
    assert last["title"] == "Résultat de la tâche" and "Rien d'anormal" in last["text"]


def test_a_foreground_error_result_is_a_failure(agent, tmp_path):
    feed(
        agent,
        agent_call("toolu_A", "Audit rapide", background=False),
        child_text("toolu_A", "…"),
        tool_result("toolu_A", "Agent type 'inconnu' not found", is_error=True),
    )

    assert only_task(agent)["status"] == "failed"
    finished = [item for item in journal(tmp_path) if item["kind"] == "agent.subagent.finished"]
    assert finished[-1]["level"] == "warning"
    assert finished[-1]["message"].startswith("Sous-agent en échec après")


@pytest.mark.parametrize("status", ["completed", "failed", "killed", "stopped", "timeout"])
def test_a_task_notification_ends_the_task_with_its_status(agent, status):
    feed(
        agent,
        agent_call("toolu_A", "Persist voice arch setting"),
        task_started("a1", "toolu_A", "Persist voice arch setting"),
        async_launched("toolu_A", "a1"),
        notification("a1", "toolu_A", status, summary="Réglage persistant ajouté"),
    )

    task = only_task(agent)
    # Une valeur inconnue est gardée telle quelle.
    assert task["status"] == status
    assert task["ended_ms"] is not None
    assert task["summary"] == "Réglage persistant ajouté"


def test_task_updated_ends_the_task(agent):
    feed(
        agent,
        task_started("bt3uv1a4i", "toolu_B", "Show diff and layout", task_type="local_bash", background=False),
        task_updated("bt3uv1a4i", {"is_backgrounded": True}),
    )
    assert only_task(agent)["background"] is True and only_task(agent)["status"] == "running"

    feed(agent, task_updated("bt3uv1a4i", {"status": "completed", "end_time": 1789047350851}))

    assert only_task(agent)["status"] == "completed"


def test_an_end_time_alone_ends_the_task(agent):
    feed(agent, task_started("a1", "toolu_A", "Meeting Planner"), task_updated("a1", {"end_time": 1789047350851}))

    assert only_task(agent)["status"] == "completed"


def test_a_shell_task_is_counted_apart_and_ends_with_its_notification(agent):
    feed(
        agent,
        tool_call("toolu_S", "Bash", {"command": "python -m pytest tests/unit -q", "description": "Run unit tests"}),
        task_started("b1kp9hn2r", "toolu_S", "Run unit tests", task_type="local_bash", background=False),
    )
    task = only_task(agent)
    assert task["kind"] == "shell"
    assert agent.subtasks.counts() == {"active": 0, "running_shell": 1}
    assert agent.tasks_snapshot()["active_count"] == 0

    feed(agent, notification("b1kp9hn2r", "toolu_S", "completed", summary="Run unit tests"))
    feed(agent, tool_result("toolu_S", "704 passed"))

    assert only_task(agent)["status"] == "completed"
    assert agent.subtasks.counts() == {"active": 0, "running_shell": 0}
    # Les commandes ne sont pas des sous-agents : rien au journal lisible.
    assert journal(tmp_path=agent.runtime_root) == []


def test_a_task_of_unknown_type_is_counted_like_a_sub_agent(agent):
    feed(agent, task_started("w1", "toolu_W", "Workflow nocturne", task_type="remote_workflow"))

    assert only_task(agent)["kind"] == "other"
    # Le panneau la range sous « Sous-agents en cours » : le badge doit la compter aussi.
    assert agent.subtasks.counts() == {"active": 1, "running_shell": 0}
    assert agent.tasks_snapshot()["active_count"] == 1


def test_a_backgrounded_shell_is_not_ended_by_its_tool_result(agent):
    feed(
        agent,
        task_started("bt3uv1a4i", "toolu_B", "Show diff", task_type="local_bash", background=False),
        task_updated("bt3uv1a4i", {"is_backgrounded": True}),
        tool_result("toolu_B", "Command running in background with ID: bt3uv1a4i"),
    )

    assert only_task(agent)["status"] == "running"


def moved_to_background(tool_use_id, task_id, *, parent=None):  # noqa: ANN001
    """Forme réelle : commande basculée en fond après son délai (ou `run_in_background`)."""
    return tool_result(
        tool_use_id,
        f"Command did not complete within its 120s timeout and was moved to the background (ID: {task_id}).",
        parent=parent,
        extra={"stdout": "", "stderr": "", "interrupted": False, "backgroundTaskId": task_id, "timedOutAfterMs": 120000},
    )


def test_a_shell_moved_to_background_before_its_task_updated_keeps_running(agent):
    feed(
        agent,
        task_started("bt3uv1a4i", "toolu_B", "Run the full suite", task_type="local_bash", background=False),
        moved_to_background("toolu_B", "bt3uv1a4i"),
    )
    task = only_task(agent)
    assert task["status"] == "running" and task["ended_ms"] is None
    assert task["background"] is True
    # Ce n'est pas un compte rendu final : la trace le dit.
    last = agent.task_trace("bt3uv1a4i")["entries"][-1]
    assert last["role"] == "launch" and "moved to the background" in last["text"]

    feed(agent, task_updated("bt3uv1a4i", {"is_backgrounded": True}))
    assert only_task(agent)["status"] == "running"
    feed(agent, task_updated("bt3uv1a4i", {"status": "completed", "end_time": 1789047350851}))
    assert only_task(agent)["status"] == "completed"


def test_a_shell_moved_to_background_after_its_task_updated_keeps_running(agent):
    feed(
        agent,
        task_started("bt3uv1a4i", "toolu_B", "Run the full suite", task_type="local_bash", background=False),
        task_updated("bt3uv1a4i", {"is_backgrounded": True}),
        moved_to_background("toolu_B", "bt3uv1a4i"),
    )
    assert only_task(agent)["status"] == "running"

    feed(agent, notification("bt3uv1a4i", "toolu_B", "completed", summary="Run the full suite"))
    assert only_task(agent)["status"] == "completed"


def test_a_background_result_is_linked_to_its_task_by_its_background_id(agent):
    # Tâche connue par son seul `task_id` : le résultat la rattache à l'appel.
    feed(
        agent,
        task_started("bt3uv1a4i", None, "Watch the build", task_type="local_bash", background=True),
        moved_to_background("toolu_B", "bt3uv1a4i"),
    )
    task = only_task(agent)
    assert task["id"] == "bt3uv1a4i" and task["tool_use_id"] == "toolu_B"
    assert task["status"] == "running"

    feed(agent, notification("bt3uv1a4i", "toolu_B", "completed"))
    assert only_task(agent)["status"] == "completed"


def test_the_final_result_entry_carries_the_plain_report(agent):
    report = "Réunion jeudi 10h.\nOrdre du jour : 1. démo 2. rétro."
    feed(
        agent,
        agent_call("toolu_A", "Meeting Planner", background=False),
        tool_result("toolu_A", [{"type": "text", "text": report}], extra={"status": "completed"}),
    )

    last = agent.task_trace("toolu_A")["entries"][-1]
    assert last["role"] == "result" and last["status"] == "ok"
    assert last["text"] == report  # et non sa sérialisation JSON


# =====================================================================
# Imbrication, activité, modèle
# =====================================================================


def test_a_nested_sub_agent_points_to_its_parent(agent):
    feed(agent, agent_call("toolu_P", "Parent"))
    # L'enfant est lancé depuis un message du parent, avant le task_started
    # du parent : son parent_id doit suivre le changement d'identifiant.
    feed(agent, agent_call("toolu_C", "Enfant", parent="toolu_P"))
    child = next(task for task in tasks_of(agent) if task["tool_use_id"] == "toolu_C")
    assert child["parent_id"] == "toolu_P" and child["depth"] == 2

    feed(
        agent,
        task_started("aP", "toolu_P", "Parent"),
        task_started("aC", "toolu_C", "Enfant", depth=2),
        child_text("toolu_C", "Je suis l'enfant."),
        child_text("toolu_P", "Je suis le parent."),
    )

    by_id = {task["id"]: task for task in tasks_of(agent)}
    assert by_id["aC"]["parent_id"] == "aP"
    assert by_id["aC"]["depth"] == 2
    assert by_id["aP"]["parent_id"] is None
    assert by_id["aP"]["activity"] == "Agent · Enfant"
    parent_text = " ".join(entry["text"] for entry in agent.task_trace("aP")["entries"])
    child_trace = " ".join(entry["text"] for entry in agent.task_trace("aC")["entries"])
    assert "Je suis le parent." in parent_text and "Je suis l'enfant." not in parent_text
    assert "Je suis l'enfant." in child_trace
    assert agent.tasks_snapshot()["active_count"] == 2


def test_progress_updates_activity_tokens_and_tools(agent):
    feed(
        agent,
        agent_call("toolu_A", "Persist voice arch setting"),
        task_started("a1", "toolu_A", "Persist voice arch setting"),
        tool_call("toolu_r1", "Read", {"file_path": "C:\\Projects\\jarvis\\jarvis\\jarvis\\app.py"}, parent="toolu_A"),
    )
    assert only_task(agent)["activity"] == "Read · app.py"

    feed(agent, progress("a1", "toolu_A", "Reading jarvis\\runtime\\control_center.py", tokens=17791, tool_uses=2))

    task = only_task(agent)
    assert task["activity"] == "Reading jarvis\\runtime\\control_center.py"
    assert task["last_tool"] == "Read"
    assert task["tokens"] == 17791 and task["tool_uses"] == 2
    assert task["description"] == "Persist voice arch setting"  # la description d'avancement ne l'écrase pas


def test_model_prefers_what_the_sub_agent_says_then_the_resolution_then_the_request(agent):
    feed(agent, agent_call("toolu_A", "Meeting Planner", model="sonnet"))
    assert only_task(agent)["model"] == "sonnet"

    feed(agent, async_launched("toolu_A", "a1", resolved="claude-sonnet-4-5"))
    assert only_task(agent)["model"] == "claude-sonnet-4-5"

    feed(agent, child_text("toolu_A", "API Error: Connection lost mid-response.", model="<synthetic>"))
    assert only_task(agent)["model"] == "claude-sonnet-4-5"

    feed(agent, child_text("toolu_A", "Je regarde.", model="claude-sonnet-4-5-20250929"))
    assert only_task(agent)["model"] == "claude-sonnet-4-5-20250929"


# =====================================================================
# Journal lisible
# =====================================================================


def test_the_journal_tells_when_a_sub_agent_starts_and_ends(agent, clock, tmp_path):
    feed(
        agent,
        agent_call("toolu_A", "Persist voice arch setting"),
        task_started("a1", "toolu_A", "Persist voice arch setting"),
    )
    # Pas encore de modèle connu : l'annonce attend le résultat de lancement.
    assert journal(tmp_path) == []
    feed(agent, async_launched("toolu_A", "a1", resolved="claude-opus-5"))
    clock.advance(192)
    feed(agent, notification("a1", "toolu_A", "completed"))

    started, finished = journal(tmp_path)
    assert started["kind"] == "agent.subagent.started"
    assert started["message"] == "Sous-agent lancé : Persist voice arch setting (general-purpose, claude-opus-5)"
    assert started["data"]["task_id"] == "a1"
    assert finished["kind"] == "agent.subagent.finished"
    assert finished["message"] == "Sous-agent terminé en 3 min 12 s : Persist voice arch setting"
    assert finished["level"] == "info"
    assert finished["data"]["duration_ms"] == 192_000
    # Les événements bruts restent journalisés à part (`agent.event`) : le
    # journal lisible s'ajoute, il ne remplace rien.


def test_durations_read_like_a_person_would_say_them():
    assert format_duration(45_000) == "45 s"
    assert format_duration(192_000) == "3 min 12 s"
    assert format_duration(3_900_000) == "1 h 05 min"


# =====================================================================
# Arrêt du brain
# =====================================================================


async def test_stopping_the_brain_interrupts_its_running_tasks(agent, clock, tmp_path):
    agent.process = FakeRunningProcess()
    feed(
        agent,
        user_input("Lance"),
        agent_call("toolu_A", "Persist voice arch setting"),
        task_started("a1", "toolu_A", "Persist voice arch setting"),
        async_launched("toolu_A", "a1"),
        task_started("b1", "toolu_S", "Run unit tests", task_type="local_bash", background=True),
        agent_call("toolu_D", "Déjà fini", background=False),
        tool_result("toolu_D", "fini"),
    )
    clock.advance(60)

    await agent.stop()

    by_id = {task["id"]: task for task in tasks_of(agent)}
    assert by_id["a1"]["status"] == "interrupted" and by_id["a1"]["ended_ms"] == ms(T0 + 60)
    assert by_id["b1"]["status"] == "interrupted"
    assert by_id["toolu_D"]["status"] == "completed"
    assert agent.tasks_snapshot()["active_count"] == 0
    brain = agent.tasks_snapshot()["brain"]
    assert brain["busy"] is False and brain["turn_started_ms"] is None and brain["started_ms"] is None
    interrupted = [item for item in journal(tmp_path) if item["data"].get("status") == "interrupted"]
    assert len(interrupted) == 1  # la commande shell n'est pas un sous-agent
    assert interrupted[0]["level"] == "warning"
    assert "interrompu" in interrupted[0]["message"]


class _LineStream:
    def __init__(self, events: list[dict]) -> None:
        self._lines = [json.dumps(event).encode("utf-8") + b"\n" for event in events]

    async def readline(self) -> bytes:
        return self._lines.pop(0) if self._lines else b""


class _ExitingProcess:
    pid = 31337

    def __init__(self, events: list[dict]) -> None:
        self.stdout = _LineStream(events)
        self.returncode: int | None = None

    async def wait(self) -> int:
        self.returncode = 1
        return 1


async def test_a_brain_that_exits_leaves_no_task_running_forever(agent):
    agent.process = _ExitingProcess([
        INIT,
        agent_call("toolu_A", "Persist voice arch setting"),
        task_started("a1", "toolu_A", "Persist voice arch setting"),
        async_launched("toolu_A", "a1"),
    ])

    await agent._read_stdout()

    assert only_task(agent)["status"] == "interrupted"


class _SilentStream:
    async def readline(self) -> bytes:
        await asyncio.Event().wait()
        return b""


class _PipedProcess(FakeRunningProcess):
    def __init__(self) -> None:
        super().__init__()
        self.stdin = None
        self.stdout = _SilentStream()
        self.stderr = _SilentStream()


async def test_the_brain_start_time_is_that_of_its_process(agent, clock, monkeypatch):
    async def fake_exec(*args, **kwargs):  # noqa: ANN002, ANN003
        return _PipedProcess()

    monkeypatch.setattr(claude_local.asyncio, "create_subprocess_exec", fake_exec)
    await agent.start()
    assert agent.tasks_snapshot()["brain"]["started_ms"] == ms(T0)
    assert agent.tasks_snapshot()["brain"]["state"] == "running"

    await agent.stop()
    assert agent.tasks_snapshot()["brain"]["started_ms"] is None


# =====================================================================
# Le brain
# =====================================================================


def test_the_brain_is_busy_from_a_real_input_to_the_top_level_result(agent, clock):
    assert agent.tasks_snapshot()["brain"]["busy"] is False
    feed(agent, user_input("Push les derniers changements"), INIT)
    brain = agent.tasks_snapshot()["brain"]
    assert brain["busy"] is True and brain["turn_started_ms"] == ms(T0)

    clock.advance(5)
    feed(agent, tool_call("toolu_1", "Bash", {"command": "git status --short", "description": "Show status"}))
    assert agent.tasks_snapshot()["brain"]["activity"] == "Bash · Show status"
    # Un tool_result de premier niveau n'est pas une nouvelle entrée.
    feed(agent, tool_result("toolu_1", " M jarvis/app.py"))
    assert agent.tasks_snapshot()["brain"]["turn_started_ms"] == ms(T0)
    # Le `result` d'un sous-agent ne clôt pas le tour du brain.
    feed(agent, {**RESULT, "parent_tool_use_id": "toolu_X"})
    assert agent.tasks_snapshot()["brain"]["busy"] is True

    feed(agent, RESULT)
    brain = agent.tasks_snapshot()["brain"]
    assert brain["busy"] is False and brain["turn_started_ms"] is None and brain["activity"] == ""


def test_the_brain_activity_names_the_sub_agent_it_launched(agent):
    feed(agent, user_input("Lance"), agent_call("toolu_A", "Persist voice arch setting"))

    assert agent.tasks_snapshot()["brain"]["activity"] == "Agent · Persist voice arch setting"


def test_the_brain_activity_ends_with_the_result_of_its_call(agent):
    feed(
        agent,
        user_input("Construis le tableau de bord"),
        tool_call("toolu_S", "Bash", {"command": "npm run build", "description": "Build the dashboard"}),
    )
    # Le résultat d'un autre appel — ici celui d'un sous-agent — ne la périme pas.
    feed(agent, tool_result("toolu_r", "contenu", parent="toolu_X"), tool_result("toolu_autre", "ok"))
    assert agent.tasks_snapshot()["brain"]["activity"] == "Bash · Build the dashboard"

    feed(agent, tool_result("toolu_S", "built in 6.1s"))

    brain = agent.tasks_snapshot()["brain"]
    assert brain["activity"] == "" and brain["busy"] is True  # « Tour en cours… »


def test_the_brain_no_longer_waits_for_a_sub_agent_launched_in_background(agent):
    feed(
        agent,
        user_input("Lance"),
        agent_call("toolu_A", "Persist voice arch setting"),
        task_started("a1", "toolu_A", "Persist voice arch setting"),
        async_launched("toolu_A", "a1"),
    )

    assert agent.tasks_snapshot()["brain"]["activity"] == ""
    assert only_task(agent)["status"] == "running"


def test_the_brain_model_comes_from_init_then_from_the_settings(agent):
    assert agent.tasks_snapshot()["brain"]["model"] == ""
    agent.model = "claude-sonnet-4-5"
    assert agent.tasks_snapshot()["brain"]["model"] == "claude-sonnet-4-5"

    feed(agent, INIT)

    brain = agent.tasks_snapshot()["brain"]
    assert brain["model"] == "claude-opus-5[1m]"
    assert brain["id"] == "brain" and brain["role"] == "Brain" and brain["provider"] == "claude"
    assert brain["session_id"] == SESSION


def test_the_brain_transcript_leaves_out_the_sub_agents(agent):
    feed(
        agent,
        user_input("Lance un sous-agent"),
        agent_call("toolu_A", "Persist voice arch setting"),
        task_started("a1", "toolu_A", "Persist voice arch setting"),
        async_launched("toolu_A", "a1"),
        child_text("toolu_A", "Message du sous-agent"),
        progress("a1", "toolu_A", "Reading app.py", tokens=10, tool_uses=1),
        tool_result("toolu_r", "contenu", parent="toolu_A"),
        RESULT,
    )

    transcript = agent.transcript()
    assert all(not entry["raw"].get("parent_tool_use_id") for entry in transcript)
    assert "Message du sous-agent" not in " ".join(entry["text"] for entry in transcript)
    assert not any(entry["raw"].get("subtype") == "task_progress" for entry in transcript)
    # Les jalons restent : le brain a bien lancé quelque chose.
    started = next(entry for entry in transcript if entry["raw"].get("subtype") == "task_started")
    assert started["title"] == "Sous-agent lancé"
    assert all(isinstance(entry["ts_ms"], int) for entry in transcript)
    # ... et c'est la trace de la tâche qui les porte.
    trace = agent.task_trace("a1")["entries"]
    texts = " ".join(entry["text"] for entry in trace)
    assert "Message du sous-agent" in texts
    assert any(entry["title"] == "Avancement" for entry in trace)


# =====================================================================
# Bornes
# =====================================================================


def test_a_task_trace_is_bounded(agent):
    feed(agent, agent_call("toolu_A", "Bavard"))
    for index in range(MAX_TRACE_ENTRIES + 50):
        feed(agent, child_text("toolu_A", f"message {index}"))

    task = only_task(agent)
    assert task["trace_count"] == MAX_TRACE_ENTRIES
    assert agent.task_trace("toolu_A", limit=500)["entries"][-1]["text"] == f"message {MAX_TRACE_ENTRIES + 49}"
    assert len(agent.task_trace("toolu_A", limit=10)["entries"]) == 10


def test_only_the_last_finished_tasks_are_kept(agent, clock):
    feed(agent, agent_call("toolu_live", "Toujours là"))
    for index in range(MAX_FINISHED_TASKS + 5):
        clock.advance(1)
        feed(agent, agent_call(f"toolu_{index}", f"Tâche {index}", background=False), tool_result(f"toolu_{index}", "ok"))

    tasks = tasks_of(agent)
    assert len(tasks) == MAX_FINISHED_TASKS + 1
    # En cours d'abord, puis les terminées, les plus récentes en tête.
    assert tasks[0]["id"] == "toolu_live"
    assert tasks[1]["id"] == f"toolu_{MAX_FINISHED_TASKS + 4}"
    assert tasks[-1]["id"] == "toolu_5"
    assert agent.task_trace("toolu_0") is None


def test_running_tasks_are_listed_oldest_first(agent, clock):
    feed(agent, agent_call("toolu_1", "Premier"))
    clock.advance(1)
    feed(agent, agent_call("toolu_2", "Second"))

    assert [task["id"] for task in tasks_of(agent)] == ["toolu_1", "toolu_2"]


def test_a_huge_tool_result_is_not_kept_verbatim(agent):
    huge = "x" * 200_000
    feed(
        agent,
        agent_call("toolu_A", "Lecture", prompt="p" * 10_000),
        tool_result("toolu_r", huge, parent="toolu_A", extra={"file": {"content": huge}}),
    )

    entry = agent.task_trace("toolu_A")["entries"][-1]
    assert len(json.dumps(entry, ensure_ascii=False)) < 20_000
    assert len(entry["text"]) < 4_100
    assert len(only_task(agent)["prompt"]) < 4_100


# =====================================================================
# Codex : le brain seul
# =====================================================================


class _BusyProbe:
    """Flux Codex qui note l'état du brain pendant que le tour tourne."""

    def __init__(self, agent: CodexLocalAgent) -> None:
        self.agent = agent
        self.seen: list[bool] = []
        self._lines = [json.dumps(event).encode("utf-8") + b"\n" for event in (
            {"type": "thread.started", "thread_id": "fil-1"},
            {"type": "item.completed", "item": {"type": "command_execution", "command": "ls", "exit_code": 0}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "Fait."}},
            {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}},
        )]

    async def readline(self) -> bytes:
        self.seen.append(self.agent.tasks_snapshot()["brain"]["busy"])
        if len(self._lines) == 2:
            assert self.agent.tasks_snapshot()["brain"]["activity"] == "Commande · ls"
        return self._lines.pop(0) if self._lines else b""


class _EmptyStream:
    async def readline(self) -> bytes:
        return b""


class _CodexStdin:
    def write(self, chunk: bytes) -> None:
        pass

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        pass


class _CodexProcess:
    pid = 4321

    def __init__(self, stdout) -> None:  # noqa: ANN001
        self.stdin = _CodexStdin()
        self.stdout = stdout
        self.stderr = _EmptyStream()
        self.returncode: int | None = None

    async def wait(self) -> int:
        self.returncode = 0
        return 0


async def test_codex_exposes_the_same_surface_with_the_brain_alone(tmp_path, clock, monkeypatch):
    async def available(command):  # noqa: ANN001
        return {"available": True, "path": "C:/fake/codex.exe", "version": "codex-cli 1.0", "error": ""}

    monkeypatch.setattr(cli_catalog, "probe", available)
    agent = CodexLocalAgent(runtime_root=tmp_path, cwd=tmp_path, command="codex", model="gpt-5-codex")
    agent.subtasks.clock = clock
    probe = _BusyProbe(agent)

    async def fake_exec(*argv, **kwargs):  # noqa: ANN002, ANN003
        return _CodexProcess(probe)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    result = await agent.ask("range le bureau", timeout_s=5)

    assert result["ok"] is True
    assert probe.seen and all(probe.seen)  # occupé tant que le processus du tour vit
    payload = agent.tasks_snapshot()
    assert payload["tasks"] == [] and payload["active_count"] == 0
    brain = payload["brain"]
    assert brain["provider"] == "codex" and brain["busy"] is False and brain["turn_started_ms"] is None
    assert brain["model"] == "gpt-5-codex"
    assert brain["started_ms"] == ms(T0)
    trace = agent.task_trace("brain")
    assert trace["task"]["id"] == "brain"
    assert any(entry["title"] == "Codex" for entry in trace["entries"])
    assert all("ts_ms" in entry for entry in trace["entries"])
    assert agent.task_trace("inconnu") is None


# =====================================================================
# Robustesse : la voix ne dépend jamais du suivi
# =====================================================================


@pytest.mark.parametrize("event", [
    {"type": "system", "subtype": ["x"]},
    {"type": "system", "subtype": {"task": "started"}},
    {"type": ["assistant"], "message": []},
    {"type": "system", "subtype": "task_started", "task_id": ["a1"], "tool_use_id": {"id": 1}},
    {"type": "system", "subtype": "task_started", "task_id": "a1", "spawn_depth": float("inf")},
    {"type": "system", "subtype": "task_progress", "task_id": "a1",
     "usage": {"total_tokens": float("inf"), "tool_uses": float("nan")}},
    {"type": "system", "subtype": "task_updated", "task_id": "a1", "patch": ["status"]},
    {"type": "assistant", "parent_tool_use_id": ["toolu_A"], "message": {"content": [
        {"type": "tool_use", "id": ["toolu_B"], "name": ["Agent"], "input": ["prompt"]},
    ]}},
    {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": ["toolu_A"]}]},
     "tool_use_result": {"agentId": ["a1"], "totalTokens": float("-inf")}},
], ids=repr)
def test_a_malformed_event_does_not_make_the_tracker_raise(agent, event):
    # Directement sur le tracker : la garde de `_record` ne doit pas masquer ses défauts.
    agent.subtasks.observe_claude(event)

    json.dumps(agent.tasks_snapshot())  # l'état reste publiable


class _QueuedStream:
    """stdout alimenté ligne à ligne, pendant qu'un `ask()` attend son `result`."""

    def __init__(self) -> None:
        self._lines: asyncio.Queue[bytes] = asyncio.Queue()

    def push(self, *events: dict) -> None:
        for event in events:
            self._lines.put_nowait(json.dumps(event).encode("utf-8") + b"\n")

    def close(self) -> None:
        self._lines.put_nowait(b"")

    async def readline(self) -> bytes:
        return await self._lines.get()


class _TalkingProcess(FakeRunningProcess):
    def __init__(self) -> None:
        super().__init__()
        self.stdin = _CodexStdin()
        self.stdout = _QueuedStream()


async def test_a_failing_tracker_never_deafens_the_brain(agent, monkeypatch, tmp_path):
    def broken(event, *, now_ms=None):  # noqa: ANN001
        raise TypeError("unhashable type: 'list'")

    monkeypatch.setattr(agent.subtasks, "observe_claude", broken)
    process = _TalkingProcess()
    agent.process = process
    reader = asyncio.create_task(agent._read_stdout())
    pending = asyncio.create_task(agent.ask("Quelle heure est-il ?", timeout_s=5))
    while agent._pending_result is None:
        await asyncio.sleep(0)
    process.stdout.push(INIT, {"type": "system", "subtype": ["x"]}, RESULT)

    answer = await asyncio.wait_for(pending, timeout=2)

    assert answer["ok"] is True and answer["text"] == "C'est lancé."
    assert not reader.done()  # la lecture de stdout a survécu aux quatre échecs
    assert [entry["raw"].get("type") for entry in agent.transcript()] == ["user", "system", "system", "result"]
    failures = journal(tmp_path, prefix="agent.subtasks_failed")
    assert len(failures) == 1  # un signalement par type d'exception, pas un par événement
    assert failures[0]["level"] == "error"
    assert failures[0]["data"]["code"] == "agent_tasks_failed"
    assert failures[0]["data"]["exception_type"] == "TypeError"

    process.stdout.close()
    await asyncio.wait_for(reader, timeout=2)


async def test_a_failing_activity_note_never_breaks_a_codex_turn(tmp_path, clock, monkeypatch):
    async def available(command):  # noqa: ANN001
        return {"available": True, "path": "C:/fake/codex.exe", "version": "codex-cli 1.0", "error": ""}

    def broken(activity):  # noqa: ANN001
        raise ValueError("activité illisible")

    monkeypatch.setattr(cli_catalog, "probe", available)
    agent = CodexLocalAgent(runtime_root=tmp_path, cwd=tmp_path, command="codex")
    agent.subtasks.clock = clock
    monkeypatch.setattr(agent.subtasks, "note_brain_activity", broken)
    events = [
        {"type": "thread.started", "thread_id": "fil-1"},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "ls", "exit_code": 0}},
        {"type": "item.completed", "item": {"type": "file_change", "changes": []}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Fait."}},
        {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}},
    ]

    async def fake_exec(*argv, **kwargs):  # noqa: ANN002, ANN003
        return _CodexProcess(_LineStream(events))

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    result = await agent.ask("range le bureau", timeout_s=5)

    assert result["ok"] is True and result["text"] == "Fait."
    assert sum(entry["raw"].get("type") == "item.completed" for entry in agent.transcript()) == 3
    failures = journal(tmp_path, prefix="agent.subtasks_failed")
    assert len(failures) == 1
    assert failures[0]["data"]["provider"] == "codex" and failures[0]["data"]["exception_type"] == "ValueError"


# =====================================================================
# HTTP
# =====================================================================


class FakeRequest:
    def __init__(self, task_id: str = "", **query: str) -> None:
        self.match_info = {"task_id": task_id}
        self.query = query


@pytest.fixture
def control(tmp_path, clock):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    control.agent.subtasks.clock = clock
    return control


def _feed_two_agents(control):  # noqa: ANN001
    feed(
        control.agent,
        user_input("Lance"),
        INIT,
        agent_call("toolu_A", "Persist voice arch setting"),
        task_started("a1", "toolu_A", "Persist voice arch setting"),
        async_launched("toolu_A", "a1"),
        agent_call("toolu_B", "Disable inactivity timeout"),
        task_started("b1", "toolu_B", "Disable inactivity timeout"),
        task_started("s1", "toolu_S", "Run unit tests", task_type="local_bash", background=False),
        child_text("toolu_A", "Je regarde."),
    )


async def test_the_tasks_route_follows_the_contract(control):
    _feed_two_agents(control)

    payload = json.loads((await control.agent_tasks(FakeRequest())).text)

    assert payload["now_ms"] == ms(T0)
    assert payload["active_count"] == 2
    assert payload["brain"]["busy"] is True and payload["brain"]["model"] == "claude-opus-5[1m]"
    assert [task["id"] for task in payload["tasks"]] == ["a1", "b1", "s1"]
    assert set(payload["tasks"][0]) == {
        "id", "tool_use_id", "kind", "provider", "subagent_type", "description", "model", "status", "background",
        "depth", "parent_id", "started_ms", "ended_ms", "activity", "last_tool", "tokens", "tool_uses", "prompt",
        "summary", "trace_count",
    }


async def test_the_status_counts_sub_agents_but_never_the_brain(control):
    _feed_two_agents(control)

    status = json.loads((await control.status(None)).text)

    assert status["subagents"] == {"active": 2, "running_shell": 1}


async def test_the_trace_route_serves_a_task_the_brain_and_refuses_the_unknown(control):
    _feed_two_agents(control)

    task = json.loads((await control.agent_task_trace(FakeRequest("a1"))).text)
    assert task["task"]["id"] == "a1"
    assert any("Je regarde." in entry["text"] for entry in task["entries"])
    assert all("ts_ms" in entry and "raw" in entry for entry in task["entries"])
    # L'identifiant d'appel, qu'un client a pu voir avant le task_started, mène au même endroit.
    alias = json.loads((await control.agent_task_trace(FakeRequest("toolu_A"))).text)
    assert alias["task"]["id"] == "a1"

    brain = json.loads((await control.agent_task_trace(FakeRequest("brain", limit="2"))).text)
    assert brain["task"]["id"] == "brain"
    assert len(brain["entries"]) == 2

    missing = await control.agent_task_trace(FakeRequest("nope"))
    assert missing.status == 404
    assert json.loads(missing.text)["code"] == "agent_task_not_found"


async def test_the_routes_are_really_mounted(control):
    _feed_two_agents(control)

    async with TestClient(TestServer(control._app)) as client:
        tasks = await client.get("/api/agent/tasks")
        trace = await client.get("/api/agent/tasks/b1/trace?limit=300")
        missing = await client.get("/api/agent/tasks/nope/trace")
        transcript = await client.get("/api/agent/transcript")

        assert tasks.status == 200 and (await tasks.json())["active_count"] == 2
        assert trace.status == 200 and (await trace.json())["task"]["description"] == "Disable inactivity timeout"
        assert missing.status == 404
        events = (await transcript.json())["events"]
        assert "Je regarde." not in " ".join(entry["text"] for entry in events)


async def test_the_routes_follow_the_active_agent_after_a_switch(control, monkeypatch):
    async def available(command):  # noqa: ANN001
        return {"available": True, "path": "C:/fake/codex.exe", "version": "codex-cli 1.0", "error": ""}

    monkeypatch.setattr(cli_catalog, "probe", available)
    monkeypatch.delenv("JARVIS_VOICE_ARCH", raising=False)
    _feed_two_agents(control)

    class Payload:
        @staticmethod
        async def json():
            return {"cli": {"agent": "codex"}}

    await control.save_settings(Payload())  # type: ignore[arg-type]

    payload = json.loads((await control.agent_tasks(FakeRequest())).text)
    assert payload["brain"]["provider"] == "codex"
    assert payload["tasks"] == []
    assert json.loads((await control.status(None)).text)["subagents"] == {"active": 0, "running_shell": 0}
    assert (await control.agent_task_trace(FakeRequest("a1"))).status == 404

"""Une notification ne rapporte que la fin d'une tâche entière (retour utilisateur du 2026-10-29).

Voix (relais du brain) comme Control Center (pastilles et toasts du registre de fond) : une
sous-tâche qui finit pendant que le travail continue ne dit et ne signale rien ; la dernière
tâche qui finit conclut le travail et se dit. Un échec n'est jamais retenu.
"""

from __future__ import annotations

from jarvis.runtime.background_events import DONE, FAILED, BackgroundEventLedger
from jarvis.runtime.claude_local import ClaudeLocalAgent
from jarvis.runtime.journal import read_jsonl_tail
from tests.unit.test_agent_tasks import agent_call, async_launched, feed, notification
from tests.unit.test_brain_delegation import _result


def _launch(agent, tool_use_id, task_id, label):
    feed(agent, agent_call(tool_use_id, label), async_launched(tool_use_id, task_id))


def _finish(agent, tool_use_id, task_id, status="completed"):
    feed(agent, notification(task_id, tool_use_id, status, "fini"))


def test_a_subtask_finishing_while_the_work_continues_says_nothing(tmp_path):
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path, command="claude")
    _launch(agent, "toolu_A", "a1", "Étape 1")
    _launch(agent, "toolu_B", "b1", "Étape 2")
    _finish(agent, "toolu_A", "a1")
    assert agent.subtasks.whole_task_finished() is False

    agent._push_notice(_result("L'étape 1 est faite.", origin="task-notification"))  # noqa: SLF001

    assert agent.notices == []
    held = [line["data"] for line in read_jsonl_tail(tmp_path / "trace.jsonl")
            if line["kind"] == "agent.unsolicited_result"]
    assert held and held[-1]["held_subtask"] is True and held[-1]["spoken"] is False and held[-1]["running_work"] == 1


def test_the_last_task_to_finish_concludes_the_work_and_is_announced(tmp_path):
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path, command="claude")
    _launch(agent, "toolu_A", "a1", "Étape 1")
    _launch(agent, "toolu_B", "b1", "Étape 2")
    _finish(agent, "toolu_A", "a1")
    agent._push_notice(_result("L'étape 1 est faite.", origin="task-notification"))  # noqa: SLF001
    _finish(agent, "toolu_B", "b1")
    assert agent.subtasks.whole_task_finished() is True

    agent._push_notice(_result("Tout est terminé.", origin="task-notification"))  # noqa: SLF001

    [notice] = agent.notices
    assert notice["text"] == "Tout est terminé." and notice["kind"] == "result"


def test_a_single_task_is_a_whole_task(tmp_path):
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path, command="claude")
    _launch(agent, "toolu_A", "a1", "Seule tâche")
    _finish(agent, "toolu_A", "a1")
    agent._push_notice(_result("Fait.", origin="task-notification"))  # noqa: SLF001
    assert [notice["text"] for notice in agent.notices] == ["Fait."]


def test_the_control_center_signals_only_the_end_of_the_whole_task():
    ledger = BackgroundEventLedger()
    ts = "2026-10-29T09:00:00+00:00"

    def finished(label, status="completed", **data):
        return ledger.observe("agent.subagent.finished", f"Sous-agent terminé : {label}",
                              data={"status": status, "description": label, **data}, ts=ts)

    assert finished("Étape 1", whole_task=False) is None  # la sous-tâche ne produit ni pastille ni toast
    assert ledger.counts() == {}
    finished("Étape 2", whole_task=True)
    assert ledger.counts() == {DONE: 1}
    finished("Ancienne trace")  # d'avant le champ : comptée comme entière
    assert ledger.counts() == {DONE: 2}
    # Une tâche ne meurt jamais en silence, entière ou non.
    finished("Étape 3", status="failed", whole_task=False)
    assert ledger.counts() == {DONE: 2, FAILED: 1}

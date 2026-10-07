"""Tâches éphémères : un sous-agent rapide dont la fin n'appelle aucun compte rendu.

Le brain déclare une tâche éphémère en préfixant la `description` de l'outil
`Agent` par `[éphémère]` (l'outil est celui du CLI : pas de paramètre à
ajouter). Ce que ce fichier fige :

- la grammaire exacte du marqueur, et l'échec sûr (mal formé = tâche normale) ;
- le silence est décidé par le code : une éphémère qui se termine bien ne pose
  aucun relais oral, mais son `work_id` reste consommé (le relais suivant ne
  devient pas ambigu) ;
- une éphémère qui échoue, est interrompue ou tuée n'est plus éphémère : elle
  reste annoncée et visible (« une tâche ne doit jamais mourir en silence ») ;
- le drapeau traverse le fil Core (`WorkObservation` / `WorkItem`) sans
  migration SQLite : l'état de travail est en mémoire.
"""

from __future__ import annotations

import pytest

from jarvis.domain.work_state import OBSERVATION_WIRE_KEYS, WorkItem, WorkObservation, apply_observation
from jarvis.runtime.agent_tasks import EPHEMERAL_MARKER, parse_ephemeral_description
from jarvis.runtime.claude_local import BRAIN_SYSTEM_PROMPT, ClaudeLocalAgent
from jarvis.runtime.journal import read_jsonl_tail
from jarvis.runtime.work_ingress import task_observation
from tests.unit.test_agent_tasks import (
    Clock,
    agent_call,
    async_launched,
    feed,
    notification,
    task_started,
    tasks_of,
)

MARKED = f"{EPHEMERAL_MARKER} Liste mes tâches"


# ------------------------------------------------------------------ grammaire


def test_the_marker_is_the_fixed_lowercase_accented_token():
    assert EPHEMERAL_MARKER == "[éphémère]"


@pytest.mark.parametrize(
    ("raw", "label", "ephemeral"),
    [
        ("[éphémère] Liste mes tâches", "Liste mes tâches", True),
        ("[éphémère]   Liste mes tâches  ", "Liste mes tâches", True),
        ("[éphémère]\tNettoie l'écran", "Nettoie l'écran", True),
        # Échec sûr : tout ce qui n'est pas exactement le marqueur en tête, suivi d'un blanc et d'un libellé.
        ("Liste mes tâches", "Liste mes tâches", False),
        ("[ephemere] Liste mes tâches", "[ephemere] Liste mes tâches", False),
        ("[Éphémère] Liste mes tâches", "[Éphémère] Liste mes tâches", False),
        ("[éphémère]Liste mes tâches", "[éphémère]Liste mes tâches", False),
        ("[éphémère]", "[éphémère]", False),
        ("[éphémère]   ", "[éphémère]", False),
        ("[éphémère ] Liste", "[éphémère ] Liste", False),
        ("(éphémère) Liste", "(éphémère) Liste", False),
        ("Liste [éphémère] mes tâches", "Liste [éphémère] mes tâches", False),
        (" [éphémère] Liste", "Liste", True),
        ("[éphémère] [éphémère] Liste", "[éphémère] Liste", True),
        ("", "", False),
    ],
)
def test_the_marker_grammar_is_exact_and_fails_safe(raw, label, ephemeral):
    assert parse_ephemeral_description(raw) == (label, ephemeral)


def test_the_brain_prompt_teaches_the_exact_marker_and_keeps_failures_audible():
    assert EPHEMERAL_MARKER in BRAIN_SYSTEM_PROMPT
    lowered = BRAIN_SYSTEM_PROMPT.casefold()
    # La règle qui garde les échecs audibles est écrite à côté du marqueur.
    assert "échec" in lowered[lowered.index(EPHEMERAL_MARKER.casefold()):]


# --------------------------------------------------------------------- tracker


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def agent(tmp_path, clock):
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path, command="claude")
    agent.subtasks.clock = clock
    return agent


def launch(agent, description=MARKED, tool_use_id="toolu_E", task_id="e1"):  # noqa: ANN001
    feed(agent, agent_call(tool_use_id, description),
         async_launched(tool_use_id, task_id), task_started(task_id, tool_use_id, description))


def finish(agent, status, tool_use_id="toolu_E", task_id="e1"):  # noqa: ANN001
    feed(agent, notification(task_id, tool_use_id, status, "fini"))


def result(text, *, origin="task-notification"):  # noqa: ANN001
    return {"type": "result", "subtype": "success", "result": text, "session_id": "sid", "origin": {"kind": origin}}


def test_a_marked_description_becomes_a_typed_flag_and_the_marker_leaves_the_label(agent):
    launch(agent)
    [task] = tasks_of(agent)
    assert task["ephemeral"] is True
    assert task["description"] == "Liste mes tâches"


def test_the_marker_is_removed_whichever_event_names_the_task_first(agent):
    feed(agent, task_started("e1", "toolu_E", MARKED), agent_call("toolu_E", MARKED))
    [task] = tasks_of(agent)
    assert (task["ephemeral"], task["description"]) == (True, "Liste mes tâches")


def test_a_malformed_or_absent_marker_is_a_normal_task(agent):
    launch(agent, "[ephemere] Liste mes tâches")
    [task] = tasks_of(agent)
    assert task["ephemeral"] is False
    assert task["description"] == "[ephemere] Liste mes tâches"


def test_a_task_that_ends_well_stays_ephemeral(agent):
    launch(agent)
    finish(agent, "completed")
    [task] = tasks_of(agent)
    assert task["status"] == "completed" and task["ephemeral"] is True


@pytest.mark.parametrize("status", ["failed", "killed", "stopped", "interrupted"])
def test_a_task_that_does_not_end_well_is_never_ephemeral(agent, status):
    launch(agent)
    finish(agent, status)
    [task] = tasks_of(agent)
    assert task["status"] == status and task["ephemeral"] is False
    assert task["description"] == "Liste mes tâches"


def test_stopping_the_brain_interrupts_an_ephemeral_task_and_unmasks_it(agent, clock):
    launch(agent)
    agent.subtasks._interrupt_all(int(clock.now * 1000))
    [task] = tasks_of(agent)
    assert task["status"] == "interrupted" and task["ephemeral"] is False


def test_a_merge_keeps_the_declaration(agent):
    # `task_started` sans appel `Agent` connu, puis l'appel : une seule tâche, toujours éphémère.
    feed(agent, task_started("e1", None, MARKED), agent_call("toolu_E", MARKED), async_launched("toolu_E", "e1"))
    [task] = tasks_of(agent)
    assert task["ephemeral"] is True


# ------------------------------------------------- silence décidé par le code


def spoken(agent):  # noqa: ANN001
    return [notice["text"] for notice in agent.notices]


def test_the_relay_of_an_ephemeral_task_that_ended_well_is_not_spoken_but_is_journaled(agent, tmp_path):
    launch(agent)
    finish(agent, "completed")
    agent._push_notice(result("La liste est faite, l'écran est propre."))

    assert spoken(agent) == []
    [entry] = [e for e in read_jsonl_tail(tmp_path / "trace.jsonl") if e["kind"] == "agent.unsolicited_result"]
    assert entry["data"]["spoken"] is False and entry["data"]["ephemeral"] is True


def test_a_silenced_ephemeral_relay_still_consumes_its_work_key(agent):
    launch(agent)
    finish(agent, "completed")
    agent._push_notice(result("Fait."))
    assert agent.subtasks.take_relayed_work_key() is None  # file vidée : le relais suivant n'hérite de rien

    # Un sous-agent normal qui finit ensuite est rattaché à SON travail, pas à l'éphémère.
    launch(agent, "Cherche le tarif", tool_use_id="toolu_N", task_id="n1")
    finish(agent, "completed", tool_use_id="toolu_N", task_id="n1")
    agent._push_notice(result("Le tarif est de douze euros."))
    [notice] = agent.notices
    assert notice["work_id"] == "toolu_N"


def test_a_normal_task_that_ended_well_is_still_spoken(agent):
    launch(agent, "Cherche le tarif")
    finish(agent, "completed")
    agent._push_notice(result("Le tarif est de douze euros."))
    assert spoken(agent) == ["Le tarif est de douze euros."]


@pytest.mark.parametrize("status", ["failed", "killed", "interrupted"])
def test_the_relay_of_a_failed_or_interrupted_ephemeral_task_is_still_spoken(agent, status):
    launch(agent)
    finish(agent, status)
    agent._push_notice(result("La liste n'a pas pu être faite."))
    [notice] = agent.notices
    assert notice["text"] == "La liste n'a pas pu être faite."
    # Une interruption n'est jamais relayée par un tour du CLI (règle existante) : pas de travail rattaché.
    assert notice["work_id"] == (None if status == "interrupted" else "toolu_E")


def test_one_quiet_ephemeral_does_not_silence_a_failure_finishing_in_the_same_turn(agent):
    launch(agent)
    launch(agent, "Cherche le tarif", tool_use_id="toolu_N", task_id="n1")
    finish(agent, "completed")
    finish(agent, "failed", tool_use_id="toolu_N", task_id="n1")
    agent._push_notice(result("La recherche a échoué."))
    assert spoken(agent) == ["La recherche a échoué."]


def test_several_quiet_ephemerals_finishing_together_stay_quiet(agent):
    launch(agent)
    launch(agent, f"{EPHEMERAL_MARKER} Nettoie l'écran", tool_use_id="toolu_F", task_id="f1")
    finish(agent, "completed")
    finish(agent, "completed", tool_use_id="toolu_F", task_id="f1")
    agent._push_notice(result("Tout est fait."))
    assert spoken(agent) == []


def test_an_ephemeral_relay_that_is_a_cli_failure_keeps_its_warning(agent, tmp_path):
    launch(agent)
    finish(agent, "completed")
    agent._push_notice({**result("API Error: 500"), "subtype": "error_during_execution", "is_error": True})
    kinds = [e["kind"] for e in read_jsonl_tail(tmp_path / "trace.jsonl")]
    assert "agent.unsolicited_failed" in kinds


# ---------------------------------------------------------- journal et timeline


def test_the_journal_lines_of_an_ephemeral_task_carry_the_flag_without_the_marker(agent, tmp_path):
    launch(agent)
    finish(agent, "completed")
    lines = [e for e in read_jsonl_tail(tmp_path / "trace.jsonl") if e["kind"].startswith("agent.subagent.")]
    assert {e["kind"] for e in lines} == {"agent.subagent.started", "agent.subagent.finished"}
    for entry in lines:
        assert entry["data"]["ephemeral"] is True
        assert EPHEMERAL_MARKER not in entry["message"] and EPHEMERAL_MARKER not in entry["data"]["description"]


def test_a_failed_ephemeral_is_journaled_as_a_normal_failure(agent, tmp_path):
    launch(agent)
    finish(agent, "failed")
    [finished] = [e for e in read_jsonl_tail(tmp_path / "trace.jsonl") if e["kind"] == "agent.subagent.finished"]
    assert finished["level"] == "warning" and finished["data"]["ephemeral"] is False


# ------------------------------------------------------ fil Core (sans SQLite)


def test_the_flag_crosses_the_observation_and_the_work_item(agent, clock):
    launch(agent)
    task = agent.subtasks.tasks()[0]
    observation = task_observation(task, source="claude", parent_key=None, now_ms=int(clock.now * 1000))
    assert observation.ephemeral is True
    assert "ephemeral" in OBSERVATION_WIRE_KEYS and observation.to_payload()["ephemeral"] is True
    assert WorkObservation.from_payload(observation.to_payload()).ephemeral is True
    item = WorkItem.from_observation(observation, revision=1)
    assert item.ephemeral is True and WorkItem.from_payload(item.to_payload()).ephemeral is True


def test_an_observation_without_the_key_is_not_ephemeral(agent, clock):
    launch(agent, "Cherche le tarif")
    observation = task_observation(agent.subtasks.tasks()[0], source="claude", parent_key=None, now_ms=int(clock.now * 1000))
    payload = observation.to_payload()
    del payload["ephemeral"]
    assert WorkObservation.from_payload(payload).ephemeral is False


def test_a_failure_observed_after_the_run_unmarks_the_core_item(agent, clock):
    launch(agent)
    first = task_observation(agent.subtasks.tasks()[0], source="claude", parent_key=None, now_ms=int(clock.now * 1000))
    created = apply_observation(None, first, revision=1)
    assert created.item.ephemeral is True
    clock.advance(3)
    finish(agent, "failed")
    last = task_observation(agent.subtasks.tasks()[0], source="claude", parent_key=None, now_ms=int(clock.now * 1000))
    update = apply_observation(created.item, last, revision=2)
    assert update.item.status.value == "failed" and update.item.ephemeral is False


def test_the_timeline_spans_of_an_ephemeral_task_carry_the_attribute_and_failures_drop_it(tmp_path, clock):
    from tests.fakes.conversation_events import queued, recording_forwarder
    from tests.unit.test_conversation_event_subagents import SCOPE, ask, result as turn_result

    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path, command="claude")
    agent.subtasks.clock = clock
    agent.subtasks.conversation_events = recording_forwarder()
    ask(agent)
    launch(agent)
    launch(agent, "Cherche le tarif", tool_use_id="toolu_N", task_id="n1")
    feed(agent, turn_result("msg-1"))
    finish(agent, "completed")
    finish(agent, "failed", tool_use_id="toolu_N", task_id="n1")

    by_span = {}
    for event in queued(agent.subtasks.conversation_events):
        by_span.setdefault(event.span_id, []).append(event.attributes["ephemeral"])
    assert by_span == {"toolu_E": [True, True], "toolu_N": [False, False]}
    assert SCOPE.conversation_id  # le même contexte de conversation que les autres tests de spans

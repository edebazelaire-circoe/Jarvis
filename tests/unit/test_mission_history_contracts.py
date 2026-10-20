"""Contrats de la Slice 03 organic-agent-orchestration : fait de déclaration du hook, `role_id` explicite dans
Work State, lecture jointe et contexte du cerveau. Purs, sans base."""

from __future__ import annotations

import pytest

from jarvis.core.work_state import WorkStateStore
from jarvis.domain.brain_context import BrainWorkEntry, build_brain_work_context
from jarvis.domain.mission_history import (
    DECLARATION_CONTRACT_VERSION, AgentDeclarationFact, MissionHistoryError, StoredInstance, fact_from_hook_event,
    live_status,
)
from jarvis.domain.missions import instance_from_declaration
from jarvis.domain.subagent_roles import RoleStatus
from jarvis.domain.work_state import (
    OBSERVATION_WIRE_KEYS, WorkItem, WorkObservation, WorkObservationBatch, WorkSnapshot, WorkStatus,
    apply_observation,
)
from jarvis.runtime.work_brief import render_work_brief
from tests.fakes.mission_history import SOURCE, T0, at, fact, instance, observation

HOOK_EVENT = {
    "hook_event_name": "PreToolUse",
    "session_id": "sess-42",
    "tool_use_id": "toolu_abc",
    "agent_id": "agent-parent",
    "agent_type": "general-purpose",
    "tool_name": "Agent",
    "tool_input": {
        "description": "[code] [coder] [éphémère] Corriger le test",
        "prompt": "SECRET-PROMPT ne doit jamais sortir",
        "subagent_type": "general-purpose",
        "run_in_background": True,
    },
}


# ------------------------------------------------------------------ fait de déclaration


def test_the_hook_event_becomes_a_bounded_fact_without_prompt():
    result = fact_from_hook_event(HOOK_EVENT, declared_at=T0)
    assert (result.tool_use_id, result.role_id, result.role_status, result.role_marker) == (
        "toolu_abc", "coder", RoleStatus.DECLARED, "coder")
    assert result.ephemeral and result.profile == "code" and result.label == "Corriger le test"
    assert (result.session_id, result.caller_agent_id, result.subagent_type, result.run_in_background) == (
        "sess-42", "agent-parent", "general-purpose", True)
    assert result.contract_version == DECLARATION_CONTRACT_VERSION
    assert "SECRET-PROMPT" not in repr(result.to_payload())
    assert AgentDeclarationFact.from_payload(result.to_payload()) == result


def test_the_alias_resolves_to_the_canonical_role_and_keeps_its_marker():
    event = {**HOOK_EVENT, "tool_input": {"description": "[code] [reviewer] Relire la PR"}}
    result = fact_from_hook_event(event, declared_at=T0)
    assert (result.role_id, result.role_marker, result.role_status) == ("qa", "reviewer", RoleStatus.ALIAS)


def test_a_hook_event_without_tool_use_id_cannot_be_joined():
    with pytest.raises(MissionHistoryError) as caught:
        fact_from_hook_event({**HOOK_EVENT, "tool_use_id": None}, declared_at=T0)
    assert caught.value.code == "declaration_unjoinable"


def test_a_malformed_optional_hook_field_is_dropped_not_guessed():
    event = {**HOOK_EVENT, "session_id": "  ", "tool_input": {"description": "Tâche", "subagent_type": "type à espaces",
                                                              "run_in_background": "yes"}}
    result = fact_from_hook_event(event, declared_at=T0)
    assert (result.session_id, result.subagent_type, result.run_in_background) == (None, None, None)
    assert (result.role_id, result.role_status) == ("undeclared", RoleStatus.UNDECLARED)


@pytest.mark.parametrize("mutation, code", [
    ({"prompt": "x"}, "mission_history_invalid"),
    ({"contract_version": 2}, "declaration_version"),
    ({"role_id": "Coder!"}, "mission_history_invalid"),
    ({"mission_owner": True}, "mission_history_invalid"),
])
def test_the_fact_decoder_is_strict(mutation, code):
    payload = {**fact("toolu_1").to_payload(), **mutation}
    with pytest.raises(MissionHistoryError) as caught:
        AgentDeclarationFact.from_payload(payload)
    assert caught.value.code == code


def test_the_fact_builds_the_instance_through_the_slice_01_contract():
    built = instance_from_declaration(fact("toolu_1").declaration(), instance_id="i1", work_source=SOURCE,
                                      work_external_id="toolu_1", created_at=at(0))
    assert (built.role_id, built.role_marker, built.ephemeral, built.label) == ("coder", "coder", False, "Corriger")


# ------------------------------------------------------------------ Work State : rôle explicite


def test_role_id_travels_on_the_wire_and_the_batch_accepts_it():
    assert "role_id" in OBSERVATION_WIRE_KEYS
    sent = observation("toolu_1", WorkStatus.RUNNING, role_id="coder")
    assert set(sent.to_payload()) == OBSERVATION_WIRE_KEYS
    batch = WorkObservationBatch.from_payload({"source": SOURCE, "producer_id": "cc-1",
                                               "observations": [sent.to_payload()]})
    assert batch.observations[0].role_id == "coder"
    item = WorkItem.from_observation(sent, revision=1)
    assert item.role_id == "coder" and WorkItem.from_payload(item.to_payload()) == item


def test_a_role_is_never_read_from_a_label_and_must_be_canonical():
    sent = WorkObservation(source=SOURCE, external_id="t", status=WorkStatus.RUNNING, observed_at=T0,
                           label="[code] [coder] Corriger")
    assert WorkItem.from_observation(sent, revision=1).role_id is None
    with pytest.raises(ValueError, match="role_id"):
        WorkObservation(source=SOURCE, external_id="t", status=WorkStatus.RUNNING, observed_at=T0, role_id="Coder")


def test_the_first_asserted_role_wins_and_a_contradiction_is_a_conflict():
    first = WorkItem.from_observation(observation("t", WorkStatus.RUNNING, role_id="coder"), revision=1)
    update = apply_observation(first, observation("t", WorkStatus.RUNNING, minute=1, role_id="research"), revision=2)
    assert update.item.role_id == "coder" and "role_id" in update.conflicts
    unknown_first = WorkItem.from_observation(observation("u", WorkStatus.RUNNING), revision=1)
    later = apply_observation(unknown_first, observation("u", WorkStatus.RUNNING, minute=1, role_id="coder"), revision=2)
    assert later.item.role_id == "coder" and not later.conflicts


async def test_a_replay_after_restart_cannot_rewrite_the_role_in_work_state():
    store = WorkStateStore()
    await store.apply(observation("t", WorkStatus.RUNNING, role_id="coder"))
    await store.apply(observation("t", WorkStatus.COMPLETED, minute=1, role_id="research"))
    [item] = store.current_snapshot().items
    assert item.status is WorkStatus.COMPLETED and item.role_id == "coder"


# ------------------------------------------------------------------ lecture jointe et cerveau


def test_live_status_comes_from_work_state_only():
    stored = StoredInstance(instance("a1", external="toolu_1"))
    item = WorkItem.from_observation(observation("toolu_1", WorkStatus.BLOCKED), revision=1)
    assert live_status(stored.instance, {item.key: item}) is WorkStatus.BLOCKED
    assert live_status(stored.instance, {}) is None


def test_the_brain_sees_the_role_within_its_budget():
    store_items = (WorkItem.from_observation(observation("t", WorkStatus.RUNNING, role_id="coder"), revision=1),)
    context = build_brain_work_context(WorkSnapshot(revision=1, items=store_items, updated_at=T0), now=at(1))
    [entry] = context.to_payload()["items"]
    assert entry["role_id"] == "coder"
    assert BrainWorkEntry.from_item(store_items[0], now=at(1)).role_id == "coder"
    lines = render_work_brief(context.to_payload())
    assert any("rôle : coder" in line for line in lines)


def test_mission_history_never_reads_conversation_events():
    """N6 : les spans `subagent.*` sont un registre de diagnostic, jamais une source d'historique de mission."""

    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "jarvis"
    for name in ("core/mission_history.py", "adapters/sqlite_mission_history.py", "domain/mission_history.py",
                 "ports/mission_history.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "subagent_conversation" not in text and "conversation_event" not in text, name

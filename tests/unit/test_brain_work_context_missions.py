"""Le cerveau voit à quelle mission appartient chaque sous-agent retenu (Slice 05 organic-agent-orchestration)."""

from __future__ import annotations

from jarvis.domain.brain_context import BrainWorkEntry, build_brain_work_context
from jarvis.domain.work_state import WorkItem, WorkSnapshot, WorkStatus
from jarvis.runtime.work_brief import render_work_brief
from tests.fakes.mission_history import at, observation


def _item(external_id: str, status: WorkStatus = WorkStatus.RUNNING) -> WorkItem:
    return WorkItem.from_observation(observation(external_id, status, role_id="coder"), revision=1)


def test_entries_carry_the_mission_only_when_one_is_known():
    snapshot = WorkSnapshot(revision=2, items=(_item("A"), _item("B")), updated_at=at(1))
    refs = {"A": ("mis_A", True)}
    context = build_brain_work_context(snapshot, now=at(2), missions=lambda item: refs.get(item.external_id))
    by_id = {entry.external_id: entry for entry in context.items}
    assert (by_id["A"].mission_id, by_id["A"].mission_owner) == ("mis_A", True)
    assert by_id["B"].to_payload() == BrainWorkEntry.from_item(_item("B"), now=at(2)).to_payload()
    assert "mission_id" not in by_id["B"].to_payload()  # sans mission, la charge utile d'avant, octet pour octet
    lines = render_work_brief(context.to_payload())
    assert any("mission : mis_A (responsable)" in line for line in lines)


def test_without_a_mission_lookup_nothing_changes():
    snapshot = WorkSnapshot(revision=2, items=(_item("A"),), updated_at=at(1))
    assert build_brain_work_context(snapshot, now=at(2)) == build_brain_work_context(snapshot, now=at(2), missions=None)

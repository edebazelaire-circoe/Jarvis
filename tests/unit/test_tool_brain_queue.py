"""File d'actions du Tool Brain (handoff jarvis-tool-brain-ui-orchestrator, S6). Contrat : docs/tool-brain-contracts.md §14.

Horloge factice, aucune boucle : la file est synchrone. Ce qui doit tenir :

- ordre déterministe `(priorité, séquence)`, `action_id` idempotent, contenu identique dédupliqué, taille bornée ;
- opérations add / cancel / replace / reprioritize / reschedule / inspect, `replace` atomique, courses nommées
  (annuler/remplacer une action déjà prise = refus typé) ;
- déclencheurs : maintenant, délai absolu borné, fait nommé (une fois), morceau/intention de parole (S4) ;
- une parole interrompue ou obsolète rend l'action morte, jamais exécutable ensuite ; toute attente expire ;
- exactement une fois : `claim` une seule fois, statut terminal définitif ;
- garde anti-ballottement après invalidation.
"""

from __future__ import annotations

import pytest

from jarvis.runtime.tool_brain_choices import StateRef
from jarvis.runtime.tool_brain_queue import (
    ACTION_EXPIRED, AUTHORITY_CHANGED, CANCELLED, DONE, EXECUTING, EXPIRED, FAILED, GONE, INVALIDATED, NOT_PENDING,
    QUEUE_FULL, QUEUED, READY, RESCHEDULE_LIMIT, SPEECH_OBSOLETE, SUPERSEDED, THRASH_GUARD, UNKNOWN_ACTION,
    UNSUPPORTED_TOOL, WAIT, ActionRecord, QueueError, ToolBrainActionQueue, Trigger, TriggerContext, plan_action,
    preconditions_from,
)
from jarvis.ports.tool_brain import ProposedAction

DISPLAY = "jarvis-display"


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def record(action_id="a1", *, trigger=None, priority="normal", object_id="o1", **extra) -> ActionRecord:
    return ActionRecord(action_id, DISPLAY, "scene_move", {"object_ids": [object_id], "dx": 1, "dy": 0},
                        priority=priority, trigger=Trigger.from_payload(trigger), **extra)


def make(**kw):
    clock = Clock()
    return ToolBrainActionQueue(clock=clock, **kw), clock


def ctx(clock, speech=None, rows=None):
    return TriggerContext(clock.now, speech, (lambda rec: (rows or {}).get(rec.intent_id)))


def speech(*, state="playing", phases="Pp", chunks=None, obsolete=(), corr="c1"):
    chunks = chunks if chunks is not None else [{"id": "k1", "i": 0, "ph": "playing"}, {"id": "k2", "i": 1, "ph": "pending"}]
    return {"chains": [{"chain": "r1", "corr": corr, "n": len(phases), "state": state, "phases": phases,
                        "chunks": chunks}], "obsolete_chunk_ids": list(obsolete)}


# ------------------------------------------------------------------ ordre, idempotence, bornes


def test_ready_actions_are_ordered_by_priority_then_arrival():
    queue, clock = make()
    for action_id, priority in (("low1", "low"), ("n1", "normal"), ("high1", "high"), ("n2", "normal")):
        assert queue.add(record(action_id, priority=priority, object_id=f"o-{action_id}")).queued
    assert queue.ready(ctx(clock)) == ["high1", "n1", "n2", "low1"]
    assert queue.reprioritize("low1", "high") == "reprioritized"
    assert queue.ready(ctx(clock)) == ["low1", "high1", "n1", "n2"]  # same priority: arrival order
    assert queue.reprioritize("low1", "urgent") == "invalid_priority" and queue.reprioritize("nope", "low") == UNKNOWN_ACTION


def test_the_same_action_id_is_idempotent_even_after_it_finished_and_left_the_history():
    queue, clock = make(history_size=2, seen_ids=64)
    assert queue.add(record("a1")).queued
    again = queue.add(record("a1", object_id="other"))
    assert (again.outcome, again.code) == ("duplicate", "duplicate_action_id") and queue.pending_count() == 1
    for index in range(5):  # a1 is cancelled and evicted from the bounded history; its id stays known
        queue.cancel(f"x{index}") if queue.add(record(f"x{index}", object_id=f"ox{index}")).queued else None
    queue.cancel("a1")
    for index in range(5, 9):
        queue.add(record(f"x{index}", object_id=f"ox{index}"))
        queue.cancel(f"x{index}")
    assert queue.get("a1") is None  # evicted
    assert queue.add(record("a1")).outcome == "duplicate"


def test_identical_content_is_deduplicated_while_pending_and_returns_the_existing_id():
    queue, _ = make()
    queue.add(record("a1"))
    twin = queue.add(record("a2"))
    assert (twin.outcome, twin.action_id, twin.code) == ("duplicate", "a1", "duplicate_content")
    assert queue.add(record("a3", trigger={"type": "event", "name": "scene_revision"})).queued  # other trigger: other action


def test_the_queue_is_bounded_and_a_full_queue_refuses_with_a_typed_code():
    queue, _ = make(max_pending=2)
    assert queue.add(record("a1", object_id="o1")).queued and queue.add(record("a2", object_id="o2")).queued
    full = queue.add(record("a3", object_id="o3"))
    assert (full.outcome, full.code) == ("rejected", QUEUE_FULL)
    queue.cancel("a1")
    assert queue.add(record("a3", object_id="o3")).queued  # a slot freed: admitted


def test_a_tool_without_an_executor_is_refused_at_admission_never_queued():
    queue, _ = make(supported=lambda server, tool: tool == "scene_move")
    assert queue.add(record("a1")).queued
    bad = queue.add(ActionRecord("a2", DISPLAY, "scene_archive", {"object_ids": ["o1"]}))
    assert (bad.outcome, bad.code) == ("rejected", UNSUPPORTED_TOOL) and queue.get("a2") is None


def test_malformed_actions_are_rejected_typed():
    queue, _ = make()
    assert queue.add(record("bad id!")).code == "invalid_action"
    assert queue.add(record("a1", priority="urgent")).code == "invalid_priority"
    assert queue.add(record("a2", supersedes=("ghost",))).code == UNKNOWN_ACTION


# ------------------------------------------------------------------ triggers: decoding matrix


@pytest.mark.parametrize("payload", [
    {"type": "later"}, {"type": "now", "x": 1}, {"type": "delay"}, {"type": "delay", "seconds": 0},
    {"type": "delay", "seconds": 121}, {"type": "delay", "seconds": True}, {"type": "delay", "seconds": "5"},
    {"type": "event", "name": "Bad Name"}, {"type": "event"}, {"type": "speech_chunk"},
    {"type": "speech_chunk", "chunk_id": "has space"}, {"type": "intent", "intent_id": ""},
    {"type": "speech", "correlation_id": "c1", "when": "middle"},
    {"type": "speech", "correlation_id": "c1", "when": "end", "paragraph": 1},
    {"type": "speech", "correlation_id": "c1", "paragraph": -1}, "now", 5])
def test_invalid_triggers_are_refused_not_coerced(payload):
    with pytest.raises(QueueError) as caught:
        Trigger.from_payload(payload)
    assert caught.value.code == "invalid_trigger"


def test_valid_triggers_round_trip_and_none_means_now():
    assert Trigger.from_payload(None).kind == "now"
    for payload in ({"type": "delay", "seconds": 5.0}, {"type": "event", "name": "mouth.speech.started"},
                    {"type": "speech_chunk", "chunk_id": "k1"}, {"type": "intent", "intent_id": "ui1"},
                    {"type": "speech", "correlation_id": "c1", "when": "start", "paragraph": 2}):
        assert Trigger.from_payload(payload).to_dict() == payload


# ------------------------------------------------------------------ triggers: firing


def test_now_is_ready_and_a_delay_trigger_waits_for_the_fake_clock():
    queue, clock = make()
    queue.add(record("now"))
    queue.add(record("later", trigger={"type": "delay", "seconds": 5}, object_id="o2"))
    assert queue.ready(ctx(clock)) == ["now"]
    clock.advance(4.9)
    assert queue.ready(ctx(clock)) == ["now"]
    clock.advance(0.2)
    assert queue.ready(ctx(clock)) == ["now", "later"]


def test_an_event_trigger_fires_only_for_a_fact_that_arrives_after_it_was_planned_and_once():
    queue, clock = make()
    queue.note_event("scene_revision")  # before the plan: not a trigger for it
    queue.add(record("a1", trigger={"type": "event", "name": "scene_revision"}))
    assert queue.ready(ctx(clock)) == []
    queue.note_event("scene_revision")
    assert queue.ready(ctx(clock)) == ["a1"]
    queue.claim("a1")
    queue.settle("a1", DONE)
    queue.note_event("scene_revision")
    assert queue.ready(ctx(clock)) == []  # a finished action never fires again


def test_a_chunk_trigger_waits_until_that_chunk_plays_and_fires_only_on_the_live_chunk():
    queue, clock = make()
    queue.add(record("a1", trigger={"type": "speech_chunk", "chunk_id": "k2"}))
    assert queue.ready(ctx(clock, speech())) == []  # k2 still pending
    live = speech(chunks=[{"id": "k1", "i": 0, "ph": "heard"}, {"id": "k2", "i": 1, "ph": "playing"}], phases="hP")
    assert queue.ready(ctx(clock, live)) == ["a1"]
    assert queue.classify("a1", ctx(clock, speech(corr="elsewhere", chunks=[], phases=""))) == (WAIT, None)
    assert queue.classify("a1", ctx(clock, None)) == (WAIT, None)  # speech not wired: wait, bounded by expiry


def test_an_interrupted_response_kills_every_action_bound_to_it():
    queue, clock = make()
    queue.add(record("chunk", trigger={"type": "speech_chunk", "chunk_id": "k2"}, object_id="o2"))
    queue.add(record("para", trigger={"type": "speech", "correlation_id": "c1", "when": "start", "paragraph": 1},
                     object_id="o3"))
    queue.add(record("end", trigger={"type": "speech", "correlation_id": "c1", "when": "end"}, object_id="o4"))
    cut = speech(state="interrupted", phases="iooo",
                 chunks=[{"id": "k1", "i": 0, "ph": "interrupted"}], obsolete=["k2"])
    for action_id in ("chunk", "para", "end"):
        assert queue.classify(action_id, ctx(clock, cut)) == (GONE, SPEECH_OBSOLETE)
    swept = queue.sweep(ctx(clock, cut))
    assert {view.record.action_id for view in swept} == {"chunk", "para", "end"}
    assert all(view.status == CANCELLED and view.code == SPEECH_OBSOLETE for view in swept)
    assert queue.ready(ctx(clock, cut)) == [] and queue.pending_count() == 0


def test_even_a_started_paragraph_is_dead_when_the_chain_was_cut_before_the_action_ran():
    queue, clock = make()
    queue.add(record("a1", trigger={"type": "speech", "correlation_id": "c1", "when": "start", "paragraph": 0}))
    cut_after_start = speech(state="interrupted", phases="i")
    assert queue.classify("a1", ctx(clock, cut_after_start)) == (GONE, SPEECH_OBSOLETE)


def test_speech_end_waits_for_the_chain_to_finish():
    queue, clock = make()
    queue.add(record("a1", trigger={"type": "speech", "correlation_id": "c1", "when": "end"}))
    assert queue.ready(ctx(clock, speech(state="playing", phases="hP"))) == []
    assert queue.ready(ctx(clock, speech(state="done", phases="hh"))) == ["a1"]


def test_an_intent_trigger_follows_the_intent_row_and_its_speech():
    queue, clock = make()
    row = {"intent_id": "ui1", "kind": "reveal", "refs": [{"kind": "object", "id": "o1"}], "subject": "",
           "timing": "with_speech", "paragraph": 1, "correlation_id": "c1"}
    queue.add(record("a1", trigger={"type": "intent", "intent_id": "ui1"}, intent_id="ui1"))
    assert queue.classify("a1", ctx(clock, speech())) == (WAIT, None)  # unknown intent row
    assert queue.classify("a1", ctx(clock, speech(), {"ui1": row})) == (WAIT, None)  # paragraph 1 still pending
    playing = speech(phases="hP", chunks=[{"id": "k2", "i": 1, "ph": "playing"}])
    assert queue.classify("a1", ctx(clock, playing, {"ui1": row})) == (READY, None)
    cut = speech(state="interrupted", phases="hi")
    assert queue.classify("a1", ctx(clock, cut, {"ui1": row})) == (GONE, SPEECH_OBSOLETE)
    broken = {**row, "kind": "nonsense"}
    assert queue.classify("a1", ctx(clock, playing, {"ui1": broken})) == (GONE, "invalid_intent")


def test_every_wait_expires_and_is_said_never_forever():
    queue, clock = make()
    queue.add(record("a1", trigger={"type": "speech_chunk", "chunk_id": "k9"}))
    assert queue.sweep(ctx(clock, speech())) == []
    clock.advance(121)
    (gone,) = queue.sweep(ctx(clock, speech()))
    assert (gone.status, gone.code) == (EXPIRED, ACTION_EXPIRED) and queue.pending_count() == 0
    assert queue.expires_for(Trigger.from_payload({"type": "delay", "seconds": 60}), requested=99999) == 600.0
    assert queue.expires_for(Trigger()) == 30.0


def test_next_deadline_tells_the_loop_when_to_wake():
    queue, clock = make()
    assert queue.next_deadline() is None
    queue.add(record("a1", trigger={"type": "delay", "seconds": 5}))
    assert queue.next_deadline() == clock.now + 5


# ------------------------------------------------------------------ replace / cancel / reschedule races


def test_replace_is_atomic_the_old_stays_if_the_new_is_refused():
    queue, clock = make(max_pending=2)
    queue.add(record("a1", object_id="o1"))
    queue.add(record("a2", object_id="o2"))
    swapped = queue.replace("a1", record("a3", object_id="o3"))  # full queue: the replacement takes the old slot
    assert swapped.queued
    assert queue.get("a1").status == SUPERSEDED and queue.get("a1").code == "a3"
    assert queue.get("a3").record.supersedes == ("a1",)
    refused = queue.replace("a2", record("a4", priority="urgent"))
    assert refused.code == "invalid_priority" and queue.get("a2").status == QUEUED  # untouched
    assert queue.ready(ctx(clock)) == ["a2", "a3"]


def test_replace_and_cancel_race_with_execution_are_typed_refusals():
    queue, _ = make()
    queue.add(record("a1"))
    assert queue.claim("a1") is not None and queue.get("a1").status == EXECUTING
    assert queue.cancel("a1") == NOT_PENDING
    assert queue.replace("a1", record("a2", object_id="o2")).code == NOT_PENDING
    assert queue.replace("ghost", record("a3", object_id="o3")).code == UNKNOWN_ACTION
    assert queue.cancel("ghost") == UNKNOWN_ACTION
    queue.settle("a1", DONE)
    assert queue.cancel("a1") == NOT_PENDING and queue.reprioritize("a1", "low") == NOT_PENDING
    assert queue.reschedule("a1", Trigger()) == NOT_PENDING


def test_cancel_then_replace_the_cancelled_one_is_refused_and_a_double_cancel_is_harmless():
    queue, _ = make()
    queue.add(record("a1"))
    assert queue.cancel("a1") == CANCELLED
    assert queue.cancel("a1") == NOT_PENDING
    assert queue.replace("a1", record("a2", object_id="o2")).code == NOT_PENDING


def test_reschedule_rearms_the_trigger_and_is_bounded():
    queue, clock = make(max_reschedules=2)
    queue.add(record("a1", trigger={"type": "delay", "seconds": 5}))
    clock.advance(4)
    assert queue.reschedule("a1", Trigger.from_payload({"type": "delay", "seconds": 5})) == "rescheduled"
    clock.advance(4)
    assert queue.ready(ctx(clock)) == []  # re-armed from the reschedule instant
    assert queue.reschedule("a1", Trigger()) == "rescheduled"
    assert queue.ready(ctx(clock)) == ["a1"]
    assert queue.reschedule("a1", Trigger.from_payload({"type": "delay", "seconds": 5})) == RESCHEDULE_LIMIT


def test_invalidate_all_cancels_pending_with_the_authority_code_and_leaves_running_work_alone():
    queue, _ = make()
    queue.add(record("a1", object_id="o1"))
    queue.add(record("a2", object_id="o2"))
    queue.claim("a1")
    assert queue.invalidate_all() == 1
    assert queue.get("a1").status == EXECUTING
    assert (queue.get("a2").status, queue.get("a2").code) == (CANCELLED, AUTHORITY_CHANGED)


# ------------------------------------------------------------------ exactly once and thrash


def test_claim_takes_an_action_once_and_a_terminal_status_is_final():
    queue, _ = make()
    queue.add(record("a1"))
    assert queue.claim("a1") is not None
    assert queue.claim("a1") is None and queue.claim("ghost") is None  # duplicate trigger: no second execution
    queue.settle("a1", DONE, "applied", {"revision": 3})
    assert queue.get("a1").detail == {"revision": 3}
    with pytest.raises(ValueError):
        queue.settle("a1", FAILED)  # never rewritten
    queue.add(record("a2", object_id="o2"))
    with pytest.raises(ValueError):
        queue.settle("a2", DONE)  # not claimed: cannot be settled


def test_an_action_just_invalidated_cannot_be_readded_until_the_cooldown_passes():
    queue, clock = make(thrash_cooldown_s=5.0)
    queue.add(record("a1"))
    queue.claim("a1")
    queue.settle("a1", INVALIDATED, "unknown_object")
    refused = queue.add(record("a2"))
    assert (refused.outcome, refused.code) == ("rejected", THRASH_GUARD)
    assert queue.add(record("a3", object_id="different")).queued  # another action is not blocked
    clock.advance(5.1)
    assert queue.add(record("a4")).queued


def test_recheck_only_stops_a_claimed_action_whose_speech_died():
    queue, clock = make()
    queue.add(record("a1", trigger={"type": "speech_chunk", "chunk_id": "k1"}))
    live = speech(chunks=[{"id": "k1", "i": 0, "ph": "playing"}])
    assert queue.recheck("a1", ctx(clock, live)) == (GONE, NOT_PENDING)  # not claimed yet
    queue.claim("a1")
    assert queue.recheck("a1", ctx(clock, live)) == (READY, None)
    assert queue.recheck("a1", ctx(clock, speech(state="interrupted", phases="i"))) == (GONE, SPEECH_OBSOLETE)


# ------------------------------------------------------------------ reads and planning


def test_inspect_and_section_are_bounded_and_the_brief_carries_no_arguments():
    queue, _ = make(max_pending=16)
    for index in range(12):
        queue.add(record(f"a{index}", object_id=f"o{index}", reason_code="about_to_discuss"))
    section = queue.section()
    assert section.status == "wired" and len(section.items) == 8
    assert "args" not in section.items[0] and "dx" not in repr(section.items)
    assert section.items[0] == {"id": "a0", "tool": "scene_move", "status": "pending", "priority": "normal",
                                "trigger": {"type": "now"}, "reason_code": "about_to_discuss"}
    everything = queue.inspect()
    assert everything["pending"] == 12 and len(everything["items"]) == 12 and everything["counters"]["added"] == 12
    one = queue.inspect("a1")
    assert one["ok"] and one["action"]["args"]["object_ids"] == ["o1"] and one["action"]["schema"] == "tool_brain.action/1"
    assert queue.inspect("ghost") == {"schema": "tool_brain.queue/1", "ok": False, "action": None, "code": UNKNOWN_ACTION}


def test_plan_action_derives_preconditions_from_the_observed_state_and_decodes_the_trigger():
    ref = StateRef("scene-1", "e1", 7, "default")
    proposed = ProposedAction(DISPLAY, "scene_move", {"object_ids": ["o1"], "dx": 1, "dy": 0}, "because", "ui1",
                              {"type": "intent", "intent_id": "ui1"}, "high", ("old",), "about_to_discuss")
    planned = plan_action(proposed, action_id="act-1", ref=ref, digest="abc", decision_id="tbd-1",
                          conversation_id="c", correlation_id="r")
    assert planned.trigger.kind == "intent" and planned.priority == "high" and planned.supersedes == ("old",)
    assert [item.to_dict() for item in planned.preconditions] == [
        {"type": "scene_epoch", "value": "scene-1@e1"}, {"type": "active_board", "value": "default"}]
    assert planned.to_dict()["planned_from_snapshot"] == "abc" and planned.reason_code == "about_to_discuss"
    assert preconditions_from(None) == ()
    with pytest.raises(QueueError):
        plan_action(ProposedAction(DISPLAY, "scene_move", {}, "x", None, {"type": "later"}), action_id="a", ref=None,
                    digest=None, decision_id=None)


def test_a_refused_replacement_never_loses_the_old_action_even_when_the_history_is_full():
    queue, _ = make(history_size=1, seen_ids=64, max_pending=4)
    queue.add(record("old", object_id="o-old"))
    for index in range(3):  # fill the bounded history with finished work
        queue.add(record(f"t{index}", object_id=f"o-t{index}"))
        queue.cancel(f"t{index}")
    refused = queue.replace("old", record("new", priority="urgent"))
    assert refused.code == "invalid_priority"
    assert queue.get("old").status == QUEUED and queue.pending_count() == 1
    swapped = queue.replace("old", record("old-twin", object_id="o-old"))  # same content: an explicit swap is allowed
    assert swapped.queued and queue.pending_count() == 1 and queue.get("old-twin").status == QUEUED


# ------------------------------------------------------------------ rework S6


def test_a_stale_executing_action_is_reaped_to_failed_and_reported_by_the_sweep():
    queue, clock = make(max_executing_s=10)
    queue.add(record("a1"))
    queue.claim("a1")
    assert queue.sweep(ctx(clock)) == [] and queue.get("a1").status == EXECUTING
    clock.advance(11)
    (view,) = queue.sweep(ctx(clock))
    assert (view.record.action_id, view.status, view.code) == ("a1", FAILED, "execution_stale")
    assert queue.stats()["failed"] == 1 and queue.pending_count() == 0


def test_event_eviction_never_strands_a_waiting_action():
    queue, clock = make()
    queue.add(record("a1", trigger={"type": "event", "name": "waited_fact"}))
    queue.note_event("waited_fact")
    for index in range(600):
        queue.note_event(f"other_fact_{index}")  # nobody waits for these: they are not even counted
    assert queue.ready(ctx(clock)) == ["a1"]
    queue.add(record("a2", object_id="o2", trigger={"type": "event", "name": "late_fact"}))
    for index in range(600):  # the waited name survives any churn of other names
        queue.note_event(f"churn_{index}")
    queue.note_event("late_fact")
    assert sorted(queue.ready(ctx(clock))) == ["a1", "a2"]
    assert len(queue._events) <= 256

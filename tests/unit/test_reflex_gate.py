"""Task06 policy replay controls; timings/IDs are explicitly synthetic."""
from __future__ import annotations

import asyncio
import json
import time

import pytest

from jarvis.domain.reflex_policy import ReflexAction, conversational_wait_reason, decide_reflex
from jarvis.domain.v2 import ProtocolEnvelope, SpeechRequest
from jarvis.runtime.output_admission import OutputAdmission, OutputAdmissionState
from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail
from tests.fakes.speech_context import source, context
from jarvis.runtime.speech_scheduler import SpeechScheduler
from tests.unit.test_voice_duplex import ControllableSession, EmptyCore, RecordingJournal


@pytest.mark.parametrize("text, reason", [
    ("OK", "acknowledgement_only"), ("non c’est bon", "acknowledgement_only"),
    ("attends je réfléchis", "user_continuing"),
    ("Ce que je voulais voir avec toi c'était... Attends je réfléchis.", "user_continuing"),
    ("Non pas le premier, le second", "correction"),
])
def test_wait_controls(text, reason):
    decision = decide_reflex(text=text, enabled=True, admitted=True, user_speaking=False,
        useful_ready=False, work_confirmed=True, work_terminal=False, noticeable_wait=True, already_used=False, stale=False)
    assert decision.action is ReflexAction.WAIT and decision.reason == reason


def test_ok_prefix_does_not_hide_a_real_request():
    assert conversational_wait_reason("OK, très bien, peux-tu comparer les prix ?") is None


@pytest.mark.parametrize("changes, reason", [({"admitted": False}, "not_admitted"), ({"user_speaking": True}, "user_speaking"),
    ({"work_confirmed": False}, "work_unconfirmed"), ({"noticeable_wait": False}, "answer_may_arrive_quickly"),
    ({"work_terminal": True}, "work_terminal"), ({"stale": True}, "stale")])
def test_context_controls(changes, reason):
    args = dict(text="Compare les prix", enabled=True, admitted=True, user_speaking=False, useful_ready=False,
                work_confirmed=True, work_terminal=False, noticeable_wait=True, already_used=False, stale=False)
    args.update(changes)
    assert decide_reflex(**args).reason == reason


def work(kind="started", correlation="c", work_id="work"):
    return ProtocolEnvelope(message_type=f"brain.work.{kind}", payload={"conversation_id": "conversation", "correlation_id": correlation, "work_id": work_id})


def scheduler(session=None):
    selected = SpeechScheduler(core=EmptyCore(), conversation_id="conversation", session=session or ControllableSession(),
                               journal=RecordingJournal(), reflex_delay_s=.01)
    selected.update_speech_context(context("conversation", "c"))
    selected._running = True
    return selected


def due(selected):
    selected._reflex.due = asyncio.get_running_loop().time() - .001
    selected._reflex.next_check = selected._reflex.due


async def test_work_before_request_permits_only_one_preamble():
    selected = scheduler()
    await selected.handle_core_event(work())
    selected.request_reflex("Compare les prix", correlation_id="c")
    due(selected)
    await selected._maybe_speak_reflex()
    assert len(selected.session.reflexes) == 1
    selected.request_reflex("Compare les prix", correlation_id="c")
    assert selected._reflex is None
    assert selected._live_reflex.admission.state is OutputAdmissionState.RESERVED
    assert not selected._reflex_cancelled
    await selected.stop()


async def test_duplicate_after_expiry_cannot_create_a_new_deadline():
    selected = scheduler()
    await selected.handle_core_event(work())
    selected.request_reflex("Compare les prix", correlation_id="c")
    due(selected)
    selected._reflex.expires = asyncio.get_running_loop().time() - .001
    await selected._maybe_speak_reflex()
    assert selected._reflex is None
    selected.request_reflex("Compare les prix", correlation_id="c")
    assert selected._reflex is None and not selected.session.reflexes
    await selected.stop()


async def test_work_after_request_releases_wait_without_resetting_deadline():
    selected = scheduler()
    selected.request_reflex("Compare les prix", correlation_id="c")
    original = selected._reflex
    due(selected)
    await selected._maybe_speak_reflex()
    assert selected.session.reflexes == []
    await selected.handle_core_event(work())
    assert selected._reflex is original
    await selected._maybe_speak_reflex()
    assert len(selected.session.reflexes) == 1
    await selected.stop()


@pytest.mark.parametrize("kind", ["completed", "failed"])
async def test_terminal_work_cancels_pending_preamble(kind):
    selected = scheduler()
    await selected.handle_core_event(work())
    selected.request_reflex("Compare les prix", correlation_id="c")
    await selected.handle_core_event(work(kind))
    await selected.handle_core_event(work())  # Reordered/duplicate start is not resurrection.
    assert selected._reflex is None
    selected.request_reflex("Compare les prix", correlation_id="c")
    assert selected._reflex is None and selected.session.reflexes == []
    await selected.stop()


async def test_wait_never_discards_a_real_core_answer():
    selected = scheduler()
    selected.request_reflex("OK", correlation_id="c")
    request = SpeechRequest("conversation", "Useful confirmed answer", correlation_id="c", source=source("c"))
    selected._enqueue(request)
    assert selected._pending == [request]
    assert selected.session.reflexes == []
    await selected.stop()


async def test_revision_gap_and_stream_gap_forget_work_attestation():
    selected = scheduler()
    await selected.handle_core_event(work())
    selected.request_reflex("Compare les prix", correlation_id="c")
    selected._note_revision(1)
    selected._note_revision(3)
    assert selected._reflex is None and not selected._reflex_work
    await selected.handle_core_event(work())
    selected._forget_reflex_work("stream_gap")
    selected.request_reflex("Compare les prix", correlation_id="new-c")
    due(selected)
    await selected._maybe_speak_reflex()
    assert selected.session.reflexes == []
    await selected.stop()


async def test_wait_decisions_and_work_memory_are_bounded_without_raw_text_logs():
    selected = scheduler()
    for number in range(180):
        await selected.handle_core_event(work(correlation=str(number), work_id=str(number)))
        selected.request_reflex("OK", correlation_id=str(number))
    assert len(selected._reflex_work) == len(selected._reflex_decisions) == 128
    assert not selected._reflex_admissions and not selected.session.reflexes
    assert all(event["message"] != "OK" for event in selected.journal.events)
    await selected.stop()


def test_expiration_is_checked_on_device_worker_without_an_asyncio_tick():
    admission = OutputAdmission(expires_at=time.monotonic() - 1)
    assert not admission.begin_write()
    assert admission.state is OutputAdmissionState.INVALIDATED


def test_native_write_reservation_cannot_be_rewritten_as_unplayed():
    admission = OutputAdmission()
    assert admission.begin_write()
    assert not admission.invalidate()
    assert admission.state is OutputAdmissionState.WRITE_STARTED
    admission.finish_write(succeeded=True)
    assert admission.state is OutputAdmissionState.WRITTEN


async def test_synthetic_replay_reduces_filler_and_retains_both_long_work_preambles(tmp_path):
    # Source-inspired text shapes; IDs, timing, completion and attestation are synthetic.
    # Baseline counterfactual: previous >=4 words, admitted, no useful answer yet.
    cases = [
        ("OK", True, False, False),
        ("non c est bon", True, True, False),
        ("Je voulais voir ça... attends je réfléchis", True, True, False),
        ("Non pas le premier mais le second", True, True, False),
        ("Tu peux me passer le sel", False, False, False),
        ("Explique la différence entre ces architectures", True, False, False),
        ("Donne-moi rapidement la valeur exacte", True, True, True),
        ("Compare les prix entre ces architectures", True, True, False),
        ("OK, très bien, peux-tu comparer les prix ?", True, True, False),
    ]
    baseline = observed = 0
    journal = RuntimeJournal(tmp_path)
    for index, (text, admitted, attested, ready) in enumerate(cases):
        selected = scheduler()
        selected.journal = journal
        correlation = f"replay-{index}"
        baseline += int(admitted and not ready and len(text.split()) >= 4)
        if attested:
            await selected.handle_core_event(work(correlation=correlation))
        if ready:
            selected._enqueue(SpeechRequest("conversation", "Useful answer", correlation_id=correlation, source=source(correlation)))
        if admitted:  # Existing owner/address gate remains authoritative.
            selected.request_reflex(text, correlation_id=correlation)
            if selected._reflex is not None:
                due(selected)
                await selected._maybe_speak_reflex()
        assert len(selected.session.reflexes) == int(index in (7, 8))
        observed += len(selected.session.reflexes)
        await selected.stop()
    assert (baseline, observed) == (6, 2)  # 67% fewer synthetic preambles; 2/2 long waits covered.
    events = read_jsonl_tail(journal.trace_path, limit=100)
    decisions = [event for event in events if event["kind"] == "voice.reflex.decided"]
    assert decisions and all(event["level"] == "info" for event in decisions)
    assert all(event["data"]["elapsed_ms"] >= 0 and event["data"]["correlation_id"].startswith("replay-") for event in decisions)
    assert all(text not in json.dumps(decisions, ensure_ascii=False) for text, *_ in cases)
    assert not journal.error_path.exists()


async def test_retention_saturation_stays_silent_without_forgetting_old_correlations():
    selected = scheduler()
    selected._reflex_requested.update(str(number) for number in range(4096))
    selected.request_reflex("Compare les prix", correlation_id="new")
    assert len(selected._reflex_requested) == 4096 and selected._reflex is None
    await selected.stop()


@pytest.mark.parametrize("text, correlation, avoid", [("x" * 8193, "c", ()), ("text", "bad\nID", ()), ("text", "c", ("x",) * 17)])
async def test_candidate_payload_is_bounded_before_retention(text, correlation, avoid):
    selected = scheduler()
    with pytest.raises(ValueError):
        selected.request_reflex(text, correlation_id=correlation, avoid=avoid)
    assert not selected._reflex_requested
    await selected.stop()

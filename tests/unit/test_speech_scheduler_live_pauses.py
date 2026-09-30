"""Live pauses between sentences are measured on the speech they belong to (Slice 06 part B).

A pause shorter than the grace (audio resumed while the grace ran) is recorded on
the speech's completion — `live_pause_count`, `live_pause_max_ms`, `live_pauses_ms`
(first `LIVE_PAUSES_KEPT`) — on the `voice.speech.completed` line and on
`mouth.speech.completed`, never as a line per pause. It is what sizes
`LIVE_COMPLETION_GRACE_MS` (risk noted by the Slice 02 rework).
"""

from __future__ import annotations

import asyncio

from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.voice_playback import LIVE_OUTPUT_AUDIBLE, LIVE_OUTPUT_QUIESCENT
from jarvis.runtime.conversation_event_trace import project_trace_entry
from jarvis.runtime.speech_scheduler import LIVE_PAUSE_FLOOR_MS, LIVE_PAUSES_KEPT, SPEECH_COMPLETED
from tests.fakes.conversation_events import queued
from tests.fakes.virtual_time_loop import run_virtual
from tests.unit.test_speech_scheduler_live_end_of_speech import (
    GRACE_S, close, data_of, decisions, frame_count, inject, rig, said, shared, until,
)


def _mouth_completed(events, speech_id):  # noqa: ANN001
    return [dict(event.attributes) for event in events
            if event.event_type is T.MOUTH_SPEECH_COMPLETED and event.speech_id == speech_id]


def test_two_bursts_300_ms_apart_record_one_pause_and_complete_once():
    async def scenario():
        surface = shared(lambda request: [])
        scheduler, journal, forwarder, _ = await rig(surface, bridge=False)
        try:
            scheduler._enqueue(said("Deux phrases.", "speech-p"))
            await until(lambda: len(surface.spoken) == 1)
            await inject(scheduler, LIVE_OUTPUT_AUDIBLE)
            await inject(scheduler, LIVE_OUTPUT_QUIESCENT)
            await asyncio.sleep(0.3)  # < 500 ms grace: the same speech goes on
            await inject(scheduler, LIVE_OUTPUT_AUDIBLE)
            await inject(scheduler, LIVE_OUTPUT_QUIESCENT)
            await until(lambda: journal.count(SPEECH_COMPLETED) == 1, budget_s=5.0)
            await asyncio.sleep(2 * GRACE_S)
            return journal, queued(forwarder)
        finally:
            await close(surface, scheduler, None)

    journal, events = run_virtual(scenario())
    [completed] = data_of(journal, SPEECH_COMPLETED, "speech-p")
    assert decisions(journal, "speech-p").count(("completed", "output_completed")) == 1
    assert completed["completion_basis"] == "local_quiescence"
    assert (completed["live_pause_count"], completed["live_pauses_ms"]) == (1, [300])
    assert completed["live_pause_max_ms"] == 300
    # The final silence stays the release, not a pause.
    assert completed["release_after_quiescence_ms"] >= GRACE_S * 1000
    [attributes] = _mouth_completed(events, "speech-p")
    assert (attributes["live_pause_count"], attributes["live_pause_max_ms"]) == (1, 300)
    assert list(attributes["live_pauses_ms"]) == [300]


def test_a_real_pause_inside_a_live_answer_is_measured_through_the_bridge():
    def plan(request):  # noqa: ANN001
        return [(1000, 300), (1000, 0)] if request.text.startswith("Première") else [(300, 0)]

    async def scenario():
        surface = shared(plan)
        scheduler, journal, _forwarder, consumer = await rig(surface)
        try:
            scheduler._enqueue(said("Première réponse, deux phrases.", "speech-a"))
            scheduler._enqueue(said("Seconde réponse.", "speech-b"))
            await until(lambda: len(surface.spoken) == 2)
            await until(lambda: len(surface.speech_frames[0]) >= frame_count(plan(surface.spoken[0])))
            await until(lambda: journal.count(SPEECH_COMPLETED) == 2)
            return journal
        finally:
            await close(surface, scheduler, consumer)

    journal = run_virtual(scenario())
    [first] = data_of(journal, SPEECH_COMPLETED, "speech-a")
    [second] = data_of(journal, SPEECH_COMPLETED, "speech-b")
    assert first["live_pause_count"] == 1
    # Drains between frames (block jitter, < LIVE_PAUSE_FLOOR_MS) are not pauses;
    # the device drain blurs the real one by about one frame.
    assert 280 <= first["live_pause_max_ms"] <= 400, first
    assert len(first["live_pauses_ms"]) == 1
    assert second["live_pause_count"] == 0 and second["live_pauses_ms"] == []


def test_many_pauses_keep_a_bounded_list_but_count_them_all():
    async def scenario():
        surface = shared(lambda request: [])
        scheduler, journal, _forwarder, _ = await rig(surface, bridge=False)
        try:
            scheduler._enqueue(said("Beaucoup de phrases.", "speech-many"))
            await until(lambda: len(surface.spoken) == 1)
            await inject(scheduler, LIVE_OUTPUT_AUDIBLE)
            for index in range(LIVE_PAUSES_KEPT + 4):
                await inject(scheduler, LIVE_OUTPUT_QUIESCENT)
                # 200 ms pauses, one 450 ms beyond the kept list, and one 50 ms jitter drain.
                await asyncio.sleep({LIVE_PAUSES_KEPT + 1: 0.45, 2: 0.05}.get(index, 0.2))
                await inject(scheduler, LIVE_OUTPUT_AUDIBLE)
            await inject(scheduler, LIVE_OUTPUT_QUIESCENT)
            await until(lambda: journal.count(SPEECH_COMPLETED) == 1, budget_s=5.0)
            return journal
        finally:
            await close(surface, scheduler, None)

    [completed] = data_of(run_virtual(scenario()), SPEECH_COMPLETED, "speech-many")
    assert completed["live_pause_count"] == LIVE_PAUSES_KEPT + 3
    assert completed["live_pauses_ms"] == [200] * LIVE_PAUSES_KEPT
    assert completed["live_pause_max_ms"] == 450  # beyond the kept list, still counted in the max


def test_the_jitter_floor_is_below_any_real_pause_and_below_the_grace():
    from jarvis.runtime.speech_scheduler import SpeechScheduler

    assert 100 < LIVE_PAUSE_FLOOR_MS < 0.8 * SpeechScheduler.LIVE_COMPLETION_GRACE_MS


def test_the_drill_down_keeps_the_pause_scalars_and_drops_the_list():
    projected = project_trace_entry({"ts": "2026-09-29T10:00:00+00:00", "kind": SPEECH_COMPLETED, "level": "info",
                                     "message": "Speech completed",
                                     "data": {"speech_id": "s1", "completion_basis": "local_quiescence",
                                              "live_pause_count": 2, "live_pause_max_ms": 420,
                                              "live_pauses_ms": [300, 420]}})
    assert projected["data"]["live_pause_count"] == 2 and projected["data"]["live_pause_max_ms"] == 420
    assert "live_pauses_ms" not in projected["data"]

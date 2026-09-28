"""Controller authority boundaries; controlled submission, no provider or CLI."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from jarvis.domain.voice_events import AssistantGenerationStarted, VoiceToolCallRequested
from jarvis.domain.voice_frontend import VoiceCorrelation
from jarvis.runtime.back_brain_delegation import BackBrainDelegationController
from tests.fakes.speech_context import source, context
from tests.unit.test_v2_speech_scheduler import CONVERSATION, FakeCore, FakeVoiceSession, build_scheduler


class Session:
    def __init__(self, *, accepted=True):
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.accepted = accepted
        self.submits, self.results = [], []

    async def submit_back_brain(self, core, conversation, acceptance):
        self.submits.append(acceptance)
        self.entered.set()
        await self.release.wait()
        return SimpleNamespace(status="accepted" if self.accepted else "unavailable",
                               job_id="job-a" if self.accepted else None,
                               reason=None if self.accepted else "back_brain_worker_unavailable")

    async def send_back_brain_tool_result(self, call_id, result):
        self.results.append((call_id, result))


def prepared(*, accepted=True):
    session = Session(accepted=accepted)
    control = BackBrainDelegationController(session)
    origin = source()
    correlation = VoiceCorrelation("session", output_id="local-output", turn_id="canonical-turn",
                                   provider_input_id="provider-input", source_correlation_id=origin.correlation_id)
    control.reserve(correlation, origin)
    bound = replace(correlation, provider_output_id="response-a")
    control.observe(SimpleNamespace(correlation=bound, payload=AssistantGenerationStarted()))
    return session, control, origin, bound


def offer(control, correlation, *, call_id="call", arguments="{}"):
    control.observe(SimpleNamespace(correlation=correlation,
        payload=VoiceToolCallRequested(call_id, "back_brain_delegate", arguments)))
    assert control.offer(object(), CONVERSATION, call_id)


@pytest.mark.parametrize("mutation", ["unknown_output", "wrong_session", "wrong_response", "wrong_source", "wrong_turn", "wrong_input", "invalidated", "arguments"])
async def test_forged_missing_or_invalidated_source_never_submits(mutation):
    session, control, origin, correlation = prepared()
    changes = {"unknown_output": {"output_id": "unknown"}, "wrong_session": {"session_id": "other"},
        "wrong_response": {"provider_output_id": "other"}, "wrong_source": {"source_correlation_id": "other"},
        "wrong_turn": {"turn_id": origin.turn_id}, "wrong_input": {"provider_input_id": "other"}}
    if mutation == "invalidated":
        control.invalidate(correlation.output_id)
    offer(control, replace(correlation, **changes.get(mutation, {})),
          arguments='{"text":"forged", "source_correlation_id":"forged"}' if mutation == "arguments" else "{}")
    await asyncio.gather(*tuple(control.tasks))
    assert not session.submits
    assert session.results[0][1]["status"] == "unavailable"
    await control.close()


@pytest.mark.parametrize("accepted", [True, False])
async def test_fixed_notice_is_after_acceptance_once_and_current_source_controls_playback(accepted):
    session, control, origin, correlation = prepared(accepted=accepted)
    scheduler = build_scheduler(FakeCore(), FakeVoiceSession())
    presented = []
    def present(request):
        presented.append(request)
        scheduler.enqueue_controller_speech(request)
    control.presenter = present
    offer(control, correlation)
    await asyncio.wait_for(session.entered.wait(), 1)
    assert not presented
    # A newer Core intent arrives while admission HTTP is pending.
    scheduler.update_speech_context(context(CONVERSATION, "corr-2", epoch=2))
    session.release.set()
    await asyncio.gather(*tuple(control.tasks))
    offer(control, correlation, call_id="retry")
    await asyncio.gather(*tuple(control.tasks))
    assert len(presented) == 1
    notice = presented[0]
    assert notice.source == origin and notice.correlation_id == origin.correlation_id
    assert notice.work_id == ("job-a" if accepted else None)
    assert notice.text == ("Je m’en occupe." if accepted else "Je ne peux pas lancer ce travail en arrière-plan pour le moment.")
    if accepted:
        # « Je m'en occupe. » decrit un instant : une intention plus recente
        # l'a rendu faux, il ne se dit plus.
        assert scheduler._pop_next() is None
        assert scheduler.presentation_snapshot()["candidates"][0]["reason"] == "stale_source"
    else:
        # Un refus de delegation est une panne, pas un accuse (Slice 07) : il
        # est durable, donc reporte sur l'intention courante au lieu d'etre
        # enterre par elle. Une tache qui ne demarre pas ne doit jamais mourir
        # en silence.
        assert scheduler.presentation_snapshot()["candidates"][0]["reason"] == "carried_over"
        assert scheduler._pop_next() == notice
    await control.close()


async def test_close_after_durable_acceptance_does_not_cancel_the_job():
    session, control, _, correlation = prepared()
    session.release.set()
    offer(control, correlation)
    await asyncio.gather(*tuple(control.tasks))
    await control.close()
    await control.close()
    assert len(session.submits) == 1 and session.results[0][1]["task_id"] == "job-a"
    assert not control.offer(object(), CONVERSATION, "call")


async def test_lost_acceptance_response_never_claims_the_job_did_not_start():
    session, control, _, correlation = prepared()
    async def uncertain(*args):
        raise TimeoutError("Core may already have committed")
    session.submit_back_brain = uncertain
    notices = []
    control.presenter = notices.append
    offer(control, correlation)
    await asyncio.gather(*tuple(control.tasks))
    assert notices[0].text == "Je ne peux pas confirmer la prise en charge pour le moment."
    assert notices[0].work_id is None
    assert session.results[0][1]["reason"] == "back_brain_submission_unknown"
    await control.close()

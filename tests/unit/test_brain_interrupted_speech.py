"""Le cerveau sait quand l'utilisateur l'a coupé, et ce qui a été entendu (17/09/2026).

Session e95f4ae6 : l'utilisateur coupe JARVIS après 1,3 s d'une réponse de
10 s. Au tour suivant, « Déjà dit à l'utilisateur » portait la réponse entière,
et la session Claude du cerveau aussi : un « oui » à la première phrase valait
« oui » à tout le reste. Le registre vocal de Core sait ce qui a été joué ; le
cerveau le reçoit désormais, et le fait public est ramené au début entendu.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from jarvis.adapters.control_center_brain import _turn_context
from jarvis.core.voice_ledger import VoiceLedgerService, _ConversationLedger
from jarvis.core.voice_state import VoiceConversationState
from jarvis.domain.brain_context import BrainContext, BrainSpeechInterruption, estimate_heard_text
from jarvis.domain.v2 import BrainTurnInput, BrainTurnResult
from jarvis.domain.voice_events import VoiceGenerationStatus, VoicePlaybackStatus
from jarvis.domain.voice_frontend import VoiceCorrelation
from jarvis.domain.voice_state import VoiceConversationSnapshot, VoiceGeneratedText, VoiceSpeechRecord, VoiceSpeechState
from jarvis.runtime.control_center import build_agent_brief
from tests.unit.test_brain_work_context import build_stack, turn, wait_idle

ANSWER = ("C'est noté : un dossier de retours utilisateur, avec le barge-in qui n'a pas coupé ma parole "
          "et le retour qui n'a pas marché non plus. Finis ta phrase, et je crée tout d'un coup.")


def test_heard_text_is_cut_back_to_a_whole_word_in_proportion_to_playback():
    text = "Un deux trois quatre cinq six sept huit neuf dix"
    assert estimate_heard_text(text, 0, 1000) == ""
    assert estimate_heard_text(text, 1000, 1000) == text
    heard = estimate_heard_text(text, 500, 1000)
    assert text.startswith(heard) and heard.endswith("quatre") and len(heard) <= len(text) // 2


@dataclass(slots=True)
class AnsweringBackend:
    answers: list[str]
    contexts: list[BrainContext] = field(default_factory=list)

    async def run_turn(self, turn: BrainTurnInput, state, emit) -> BrainTurnResult:
        raise AssertionError("context-aware backend expected")

    async def run_turn_with_context(self, turn: BrainTurnInput, context: BrainContext, emit) -> BrainTurnResult:
        self.contexts.append(context)
        return BrainTurnResult(correlation_id=turn.correlation_id, public_summary=self.answers.pop(0) if self.answers else "")


@dataclass(slots=True)
class FakeLedger:
    found: tuple = ()

    async def interrupted_speeches(self, conversation_id: str):
        return self.found


async def test_the_next_turn_learns_what_was_cut_and_the_fact_keeps_only_what_was_heard(tmp_path):
    backend = AnsweringBackend([ANSWER])
    stack = await build_stack(tmp_path, backend)
    ledger = FakeLedger()
    stack.brain._voice_ledger = ledger
    cut = BrainSpeechInterruption(text=ANSWER, heard_text="C'est noté : un dossier", played_ms=1318, total_ms=10350)
    try:
        await stack.brain.submit(turn(stack.conversation_id, "Crée un dossier de retours", correlation_id="corr-1"))
        await wait_idle(stack.brain)
        assert ANSWER in stack.brain.working_state(stack.conversation_id).known_public_facts

        ledger.found = (("speech-1", cut),)
        await stack.brain.submit(turn(stack.conversation_id, "Oui", correlation_id="corr-2"))
        await wait_idle(stack.brain)
        await stack.brain.submit(turn(stack.conversation_id, "Et ensuite ?", correlation_id="corr-3"))
        await wait_idle(stack.brain)
    finally:
        await stack.close()

    assert [context.interruptions for context in backend.contexts] == [(), (cut,), ()]
    facts = stack.brain.working_state(stack.conversation_id).known_public_facts
    assert ANSWER not in facts
    assert any(fact.startswith("C'est noté : un dossier…") and "pas été entendue" in fact for fact in facts)
    # Le tour qui apprend la coupure voit déjà l'état corrigé.
    assert ANSWER not in backend.contexts[1].state.known_public_facts


async def test_an_answer_never_heard_leaves_the_public_facts(tmp_path):
    backend = AnsweringBackend([ANSWER])
    stack = await build_stack(tmp_path, backend)
    stack.brain._voice_ledger = FakeLedger()
    try:
        await stack.brain.submit(turn(stack.conversation_id, correlation_id="corr-1"))
        await wait_idle(stack.brain)
        stack.brain._voice_ledger.found = (("speech-1", BrainSpeechInterruption(text=ANSWER, heard_text="", played_ms=0)),)
        await stack.brain.submit(turn(stack.conversation_id, correlation_id="corr-2"))
        await wait_idle(stack.brain)
    finally:
        await stack.close()

    assert stack.brain.working_state(stack.conversation_id).known_public_facts == ()


def test_the_brief_tells_the_agent_what_was_not_said():
    cut = BrainSpeechInterruption(text=ANSWER, heard_text="C'est noté : un dossier", played_ms=1318, total_ms=10350)
    context = _turn_context(BrainTurnInput(conversation_id="c", text="Oui", correlation_id="k"), None, None, (cut,))
    brief = build_agent_brief(context, "Oui")

    line = next(line for line in brief.splitlines() if line.startswith("COUPÉ"))
    assert "1,3 s" in line and "10,3 s" in line
    assert "« C'est noté : un dossier… »" in line and "PAS été dite" in line
    assert brief.index("COUPÉ") < brief.index("[Demande]")

    silent = _turn_context(BrainTurnInput(conversation_id="c", text="Oui", correlation_id="k"), None, None,
                           (BrainSpeechInterruption(text=ANSWER, heard_text="", played_ms=0),))
    assert "n'a pas été entendue du tout" in build_agent_brief(silent, "Oui")
    assert "COUPÉ" not in build_agent_brief(_turn_context(BrainTurnInput(conversation_id="c", text="Oui", correlation_id="k"), None), "Oui")


def _speech(speech_id: str, *, session_id: str, state: VoiceSpeechState, played: int, received: float,
            generation: VoiceGenerationStatus, generated: str | None = ANSWER, intended: str | None = ANSWER) -> VoiceSpeechRecord:
    return VoiceSpeechRecord(
        correlation=VoiceCorrelation(session_id=session_id, speech_id=speech_id),
        intended_text=intended,
        generated=(VoiceGeneratedText(transcript_id=f"t-{speech_id}", text=generated, completed=True),) if generated else (),
        state=state,
        generation_status=generation,
        playback_status=(VoicePlaybackStatus.COMPLETE if state == VoiceSpeechState.COMPLETE
                         else VoicePlaybackStatus.PARTIAL if played else VoicePlaybackStatus.UNPLAYED),
        played_ms=played,
        received_audio_ms=received,
        first_played_order=1 if played else None,
    )


async def test_the_ledger_reports_only_cut_brain_speech_of_the_current_session():
    service = VoiceLedgerService(conversations=None)  # type: ignore[arg-type]
    state = VoiceConversationState("conv-1")
    state._snapshot = VoiceConversationSnapshot(
        "conv-1", current_session_id="s-now",
        speeches=(
            _speech("cut", session_id="s-now", state=VoiceSpeechState.INTERRUPTED, played=1318, received=10350.0,
                    generation=VoiceGenerationStatus.COMPLETED),
            _speech("partial-gen", session_id="s-now", state=VoiceSpeechState.CANCELLED, played=0, received=900.0,
                    generation=VoiceGenerationStatus.CANCELLED),
            _speech("done", session_id="s-now", state=VoiceSpeechState.COMPLETE, played=10350, received=10350.0,
                    generation=VoiceGenerationStatus.COMPLETED),
            _speech("old", session_id="s-before", state=VoiceSpeechState.INTERRUPTED, played=500, received=5000.0,
                    generation=VoiceGenerationStatus.COMPLETED),
            _speech("unknown-cut", session_id="s-now", state=VoiceSpeechState.UNKNOWN, played=7718, received=10650.0,
                    generation=VoiceGenerationStatus.COMPLETED),
            _speech("unknown-whole", session_id="s-now", state=VoiceSpeechState.UNKNOWN, played=9918, received=10100.0,
                    generation=VoiceGenerationStatus.COMPLETED),
            _speech("reflex", session_id="s-now", state=VoiceSpeechState.INTERRUPTED, played=500, received=5000.0,
                    generation=VoiceGenerationStatus.COMPLETED, intended=None),
        ),
    )
    service._ledgers["conv-1"] = _ConversationLedger(state)

    found = await service.interrupted_speeches("conv-1")

    assert len(found) == 3
    (_key, cut), (_key2, never), (_key3, unknown_cut) = found
    assert unknown_cut.played_ms == 7718 and unknown_cut.total_ms == 10650
    assert cut.played_ms == 1318 and cut.total_ms == 10350
    assert ANSWER.startswith(cut.heard_text) and 0 < len(cut.heard_text) < len(ANSWER) // 4
    assert never.heard_text == "" and never.total_ms is None
    assert await service.interrupted_speeches("unknown") == ()

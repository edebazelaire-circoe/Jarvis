"""Fin de parole Live, avec l'identité de sortie que le vrai GPT-Live fournit.

Tests ROUGES de la Slice 01 (reprise QA, tâche
`jarvis-voice-stale-speech-presentation`), que la Slice 02 doit faire passer.
Complément de `test_speech_scheduler_live_completion.py`, laissé intact : la
Slice 02 en retire les marqueurs `xfail` en parallèle.

Le faux « un id fournisseur par parole » est plus aimable que le vrai Live. Là,
deux paroles de Jarvis enchaînées sans parole de l'utilisateur PARTAGENT un seul
id de sortie fournisseur (`openai_live_frontend.py` : `_output_id` n'est remis à
zéro qu'au changement de sens, `_enter_direction`), et
`LiveFrontendSession._legacy_events` n'annonce `realtime.output_started` qu'une
fois par id. Une fin de parole qui compterait sur un nouvel `output_started` ou
sur un nouvel id par parole passerait avec l'ancien faux et échouerait en vrai :
chaque test tourne donc dans les deux modes (`shared_output`).

Bornes (critère d'acceptation de la Slice 02, grâce au plus 500 ms) :

- la seconde parole ne démarre jamais avant la fin de l'audio de la première ;
- elle démarre au plus grâce + 250 ms après cette fin ;
- la première est soldée `completed` / `output_completed`, jamais
  `delivery_not_complete`, et le filet `speech_output_stalled` ne part pas.
"""

from __future__ import annotations

import asyncio

import pytest

from jarvis.domain.v2 import SpeechRequest, utc_now
from jarvis.runtime.realtime_audio import RealtimeConversationBridge, SoundDeviceRealtimeAudio
from jarvis.testlab.virtual.harness import ImmediateOutputStream
from tests.fakes.live_output_surface import LiveOutputSurface
from tests.fakes.virtual_time_loop import VirtualWallClock, run_virtual
from tests.unit.test_speech_scheduler_live_completion import (
    GRACE_MAX_S,
    RELEASE_MARGIN_S,
    close_rig,
    said,
    stalls,
    until,
)
from tests.unit.test_v2_speech_scheduler import CONVERSATION, FakeCore, RecordingJournal, build_scheduler

SPEECH_DECIDED = "voice.speech.presentation_decided"
#: Durée d'une trame du faux (`tests/fakes/live_output_surface.py`).
FRAME_S = 0.02

MODES = [pytest.param(False, id="output-per-speech"), pytest.param(True, id="shared-output-like-real-live")]


async def live_rig(plan, *, shared_output: bool):
    """La chaîne Live de production (même câblage que le `live_rig` voisin et que
    `PersistentVoiceRuntime`), avec le mode d'identité de sortie choisi."""
    loop = asyncio.get_running_loop()
    surface = LiveOutputSurface(plan, shared_output=shared_output)
    journal = RecordingJournal()
    scheduler = build_scheduler(FakeCore(), surface, journal=journal,
                                clock=VirtualWallClock(loop, utc_now()), output_timeout_s=None)
    audio = SoundDeviceRealtimeAudio()
    audio._output = ImmediateOutputStream()
    bridge = RealtimeConversationBridge(
        core=FakeCore(), session=surface, conversation_id=CONVERSATION, audio=audio,
        continuous=True, auto_turn=True, clock=loop.time,
        on_addressed=lambda: None, on_mute=lambda: None,
        on_output_event=scheduler.note_output_event,
        on_interruption=scheduler.note_interruption,
        on_user_speech=scheduler.note_user_speech,
        output_admission=scheduler.output_admission,
        journal=journal,
    )
    scheduler.output_alive = bridge.output_pending
    await scheduler.start()
    consumer = asyncio.create_task(bridge._consume(surface.events()), name="test-live-bridge")
    return surface, scheduler, journal, consumer


def decisions(journal, speech_id: str) -> list[tuple[str, str]]:
    return [(event["data"]["status"], event["data"]["reason"]) for event in journal.of(SPEECH_DECIDED)
            if event["data"].get("speech_id") == speech_id]


@pytest.mark.parametrize("shared_output", MODES)
def test_the_next_live_speech_starts_once_the_previous_one_has_been_heard_and_not_before(shared_output):
    """T1 (reprise) — deux phrases de 2 s en file : la seconde démarre après la fin
    de l'audio de la première (>= 2 s), au plus grâce + 250 ms après ; la première
    est complétée, pas `delivery_not_complete`."""

    async def scenario():
        surface, scheduler, journal, consumer = await live_rig(lambda request: [(2000, 0)],
                                                               shared_output=shared_output)
        try:
            scheduler._enqueue(said("Première phrase, deux secondes d'audio."))
            scheduler._enqueue(said("Seconde phrase, deux secondes d'audio."))
            await until(lambda: len(surface.spoken) == 2)
            first = surface.spoken[0].id
            return list(surface.spoken_at), decisions(journal, first), stalls(journal)
        finally:
            await close_rig(surface, scheduler, consumer)

    spoken_at, first_decisions, stalled = run_virtual(scenario())
    assert len(spoken_at) == 2, "la seconde phrase n'a jamais été dite"
    gap = spoken_at[1] - spoken_at[0]
    upper = 2.0 + GRACE_MAX_S + RELEASE_MARGIN_S
    assert 2.0 <= gap < upper, (
        f"la seconde phrase Live a démarré {gap:.2f} s après la première (attendu dans [2.00, {upper:.2f}[ s) ; "
        f"décisions de la première : {first_decisions} ; speech_output_stalled émis {len(stalled)} fois")
    assert ("completed", "output_completed") in first_decisions, (
        f"la première phrase n'est pas soldée output_completed : {first_decisions}")
    assert not any(reason == "delivery_not_complete" for _, reason in first_decisions), first_decisions
    assert stalled == [], "le filet OUTPUT_TIMEOUT_S s'est déclenché sur le chemin nominal"


@pytest.mark.parametrize("shared_output", MODES)
def test_a_short_gap_inside_a_live_speech_does_not_let_the_next_one_start_whatever_the_output_id(shared_output):
    """T2 (reprise) — audio en deux rafales séparées de 150 ms (< grâce) : la phrase
    suivante ne démarre pas dans le trou, mais sitôt la seconde rafale finie."""

    def plan(request: SpeechRequest):
        if request.text.startswith("Première"):
            return [(1000, 150), (1000, 0)]
        return [(500, 0)]

    async def scenario():
        surface, scheduler, journal, consumer = await live_rig(plan, shared_output=shared_output)
        try:
            scheduler._enqueue(said("Première phrase, en deux rafales."))
            scheduler._enqueue(said("Seconde phrase."))
            await until(lambda: len(surface.spoken) == 2)
            # Lire l'audio de la première phrase seulement une fois TOUT rendu : lu
            # au départ de la seconde, il s'arrêterait là et masquerait un départ
            # prématuré (revue QA de la Slice 02).
            await until(lambda: len(surface.speech_frames[0]) >= sum(
                max(1, int(audio_ms / (FRAME_S * 1000))) for audio_ms, _ in plan(surface.spoken[0])))
            first = surface.spoken[0].id
            return (list(surface.spoken_at), list(surface.speech_frames[0]), decisions(journal, first),
                    stalls(journal))
        finally:
            await close_rig(surface, scheduler, consumer)

    spoken_at, first_frames, first_decisions, stalled = run_virtual(scenario())
    assert len(spoken_at) == 2, "la seconde phrase n'a jamais été dite"
    audio_end = first_frames[-1] + FRAME_S
    assert spoken_at[1] >= audio_end, (
        f"la seconde phrase a démarré à {spoken_at[1]:.2f} s, pendant l'audio de la première "
        f"(fin à {audio_end:.2f} s)")
    release = spoken_at[1] - audio_end
    assert release < GRACE_MAX_S + RELEASE_MARGIN_S, (
        f"la seconde phrase a démarré {release:.2f} s après la fin réelle de l'audio "
        f"(attendu < {GRACE_MAX_S + RELEASE_MARGIN_S:.2f} s) ; décisions de la première : {first_decisions} ; "
        f"speech_output_stalled émis {len(stalled)} fois")
    assert ("completed", "output_completed") in first_decisions, first_decisions
    assert stalled == []

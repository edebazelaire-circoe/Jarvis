"""Fin de parole sur une surface Live : la bouche se libère quand l'audio s'est tu.

Tests ROUGES de la Slice 01 (tâche `jarvis-voice-stale-speech-presentation`),
que la Slice 02 doit faire passer.

Sur GPT-Live, le fournisseur n'émet jamais `realtime.response_done`
(`LiveFrontendSession.requires_local_quiescence_without_output_final`). Le
bridge constate bien la fin locale de lecture (`_note_live_output_quiescent`)
mais ne la transmet qu'à l'orbe : `SpeechScheduler._await_output` attend donc
`OUTPUT_TIMEOUT_S` (30 s) avant la parole suivante, et chaque parole Live finit
en `delivery_not_complete` (READINESS B1, fait 1 ; B2 : 93/93 paroles Live).

Chaîne montée ici, sans réseau ni attente réelle :

    LiveOutputSurface (fournisseur sans fin de sortie)
        -> RealtimeConversationBridge._consume (production) -> périphérique de test
        -> on_output_event / output_alive -> SpeechScheduler (production)

La boucle est une `VirtualTimeLoop` : les 30 s du filet ne coûtent rien, et
« rien n'a démarré pendant 150 ms » est un constat déterministe.

La grâce de quiescence n'existe pas encore ; la Slice 02 la fixe entre 300 et
500 ms (`live_completion_grace_ms`, SLICE 02). Les bornes ci-dessous prennent le
haut de cette fourchette : un test qui passerait avec une grâce plus longue ne
prouverait pas le critère d'acceptation.
"""

from __future__ import annotations

import asyncio

import pytest

from jarvis.domain.v2 import SpeechKind, SpeechRequest, utc_now
from jarvis.runtime.realtime_audio import RealtimeConversationBridge, SoundDeviceRealtimeAudio
from jarvis.runtime.speech_scheduler import OUTPUT_STALLED
from jarvis.testlab.virtual.harness import ImmediateOutputStream
from tests.fakes.live_output_surface import LiveOutputSurface
from tests.fakes.speech_context import source
from tests.fakes.virtual_time_loop import VirtualWallClock, run_virtual
from tests.unit.test_v2_speech_scheduler import CONVERSATION, FakeCore, RecordingJournal, build_scheduler

#: Haut de la fourchette de grâce annoncée par la Slice 02 (300–500 ms).
GRACE_MAX_S = 0.5
#: Marge du critère d'acceptation : « la parole suivante démarre au plus
#: grâce + 250 ms après la fin réelle de l'audio ».
RELEASE_MARGIN_S = 0.25
#: Au-delà, le scénario a échoué ; en temps virtuel, ce délai ne coûte rien et
#: laisse le filet de 30 s se déclencher, pour que l'échec dise ce qui s'est passé.
SCENARIO_BUDGET_S = 90.0


def said(text: str) -> SpeechRequest:
    """Un résultat de l'intention courante (celle que `build_scheduler` installe)."""
    return SpeechRequest(CONVERSATION, text, kind=SpeechKind.RESULT, correlation_id="corr-1",
                         source=source("corr-1"))


async def live_rig(plan):
    """La chaîne Live de production, avec un fournisseur et un périphérique de test."""
    loop = asyncio.get_running_loop()
    surface = LiveOutputSurface(plan)
    journal = RecordingJournal()
    # `output_timeout_s=None` : le filet de production, `OUTPUT_TIMEOUT_S` = 30 s.
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
    # Même câblage que `PersistentVoiceRuntime` : seul le bridge sait si une
    # sortie joue encore localement.
    scheduler.output_alive = bridge.output_pending
    await scheduler.start()
    consumer = asyncio.create_task(bridge._consume(surface.events()), name="test-live-bridge")
    return surface, scheduler, journal, consumer


async def close_rig(surface, scheduler, consumer) -> None:
    await scheduler.stop()
    await surface.close()
    consumer.cancel()
    await asyncio.gather(consumer, return_exceptions=True)


async def until(predicate, *, budget_s: float = SCENARIO_BUDGET_S) -> None:
    """Attente conditionnelle en temps virtuel : bornée, jamais un délai fixe."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + budget_s
    while not predicate():
        if loop.time() >= deadline:
            return
        await asyncio.sleep(0.01)


def stalls(journal) -> list[dict]:
    return [event for event in journal.of(OUTPUT_STALLED) if event["data"].get("code") == "speech_output_stalled"]


def test_the_next_live_speech_starts_as_soon_as_the_previous_one_has_been_heard():
    """Deux phrases de 2 s en file sur une surface Live : la seconde part dès que
    le périphérique s'est tu (grâce comprise), jamais au bout du filet de 30 s."""

    async def scenario():
        surface, scheduler, journal, consumer = await live_rig(lambda request: [(2000, 0)])
        try:
            scheduler._enqueue(said("Première phrase, deux secondes d'audio."))
            scheduler._enqueue(said("Seconde phrase, deux secondes d'audio."))
            await until(lambda: len(surface.spoken) == 2)
            return list(surface.spoken_at), stalls(journal)
        finally:
            await close_rig(surface, scheduler, consumer)

    spoken_at, stalled = run_virtual(scenario())
    assert len(spoken_at) == 2, "la seconde phrase n'a jamais été dite"
    gap = spoken_at[1] - spoken_at[0]
    assert gap < 2.0 + GRACE_MAX_S + RELEASE_MARGIN_S, (
        f"la seconde phrase Live a démarré {gap:.2f} s après la première "
        f"(attendu < {2.0 + GRACE_MAX_S + RELEASE_MARGIN_S:.2f} s) ; "
        f"speech_output_stalled émis {len(stalled)} fois")
    assert stalled == [], "le filet OUTPUT_TIMEOUT_S s'est déclenché sur le chemin nominal"


def test_a_short_gap_inside_a_live_speech_does_not_let_the_next_one_start():
    """Audio en deux rafales séparées de 150 ms (< grâce) : la phrase suivante ne
    démarre pas dans le trou, mais démarre sitôt la seconde rafale finie."""

    def plan(request: SpeechRequest):
        if request.text.startswith("Première"):
            return [(1000, 150), (1000, 0)]
        return [(500, 0)]

    async def scenario():
        surface, scheduler, journal, consumer = await live_rig(plan)
        try:
            scheduler._enqueue(said("Première phrase, en deux rafales."))
            scheduler._enqueue(said("Seconde phrase."))
            await until(lambda: len(surface.spoken) == 2)
            first_output = [at for output, at in surface.frames if output == "live-output-1"]
            return list(surface.spoken_at), first_output, stalls(journal)
        finally:
            await close_rig(surface, scheduler, consumer)

    spoken_at, first_frames, stalled = run_virtual(scenario())
    assert len(spoken_at) == 2, "la seconde phrase n'a jamais été dite"
    audio_end = first_frames[-1] + 0.02
    # Jamais pendant l'audio de la première phrase, trou de 150 ms compris.
    assert spoken_at[1] >= audio_end, (
        f"la seconde phrase a démarré à {spoken_at[1]:.2f} s, pendant l'audio de la première "
        f"(fin à {audio_end:.2f} s)")
    release = spoken_at[1] - audio_end
    assert release < GRACE_MAX_S + RELEASE_MARGIN_S, (
        f"la seconde phrase a démarré {release:.2f} s après la fin réelle de l'audio "
        f"(attendu < {GRACE_MAX_S + RELEASE_MARGIN_S:.2f} s) ; speech_output_stalled émis {len(stalled)} fois")
    assert stalled == []

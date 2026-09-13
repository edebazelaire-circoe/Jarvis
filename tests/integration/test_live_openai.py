"""Fumée fournisseur réel, **opt-in**, jamais dans la suite par défaut.

Les deux tests de ce fichier sont sautés tant que `JARVIS_LIVE_OPENAI=1` n'est
pas posé. Ils ne doivent jamais devenir obligatoires : la suite du dépôt se
valide sans micro, sans OpenAI et sans réseau
(`docs/handoff-realtime-brain/docs/04-testing-and-quality.md`, « Test
philosophy »), et un test réseau dans la porte de régression rendrait celle-ci
dépendante d'un quota et d'une connexion.

Ce qu'ils couvrent :

- `test_real_openai_transcription_fixture` — l'ancien chemin (transcription hors
  ligne d'un fichier). Il ne dit **rien** de l'architecture continue.
- `test_real_openai_realtime_brain_speech` — le chemin continu : session
  Realtime ouverte avec le catalogue d'outils vide de la Décision 34, parole du
  cerveau restituée par `speak()`, identifiants de sortie corrélés au
  `speech_id`, premier bloc audio reçu, puis annulation de la sortie. C'est
  exactement ce que les faux websockets ne peuvent pas prouver : que le
  fournisseur accepte réellement cette forme de session et rend l'audio attendu.

Ce fichier n'a **pas** été exécuté contre le vrai OpenAI dans la tranche 12a :
son résultat est donc « non vérifié », pas « réussi ».
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from jarvis.adapters.openai_transcription import OpenAITranscriptionBackend
from jarvis.domain.messages import AudioClip
from jarvis.domain.v2 import SpeechKind, SpeechRequest
from jarvis.v2_config import DEFAULT_CONTINUOUS_SURFACE_MODEL

# Un seul interrupteur pour tout le fichier : poser la variable est un acte
# délibéré, qui consomme du quota et sort du réseau local.
live_only = pytest.mark.skipif(
    os.getenv("JARVIS_LIVE_OPENAI") != "1" or not os.getenv("OPENAI_API_KEY"),
    reason="requires JARVIS_LIVE_OPENAI=1 and OPENAI_API_KEY",
)
gpt_live_only = pytest.mark.skipif(
    os.getenv("JARVIS_LIVE_GPT_LIVE") != "1" or not os.getenv("OPENAI_API_KEY"),
    reason="requires JARVIS_LIVE_GPT_LIVE=1 and OPENAI_API_KEY",
)

# Le fournisseur peut être lent ; il ne doit pas pouvoir être infini.
LIVE_TIMEOUT_S = 30.0


@pytest.mark.asyncio
@live_only
async def test_real_openai_transcription_fixture():
    key = os.environ["OPENAI_API_KEY"]
    model = os.getenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-transcribe")
    audio = Path("tests/fixtures/bonjour-jarvis.wav").read_bytes()
    result = await OpenAITranscriptionBackend(api_key=key, model=model).transcribe(AudioClip(audio))
    normalized = result.text.casefold()
    assert "jarvis" in normalized
    assert "transcription" in normalized


@pytest.mark.asyncio
@live_only
async def test_real_openai_realtime_brain_speech():
    """Le mode continu, de bout en bout, contre le vrai Realtime.

    Aucun périphérique n'est ouvert : l'audio rendu est consommé comme des
    évènements, jamais joué. La recette acoustique (écho, VAD, barge-in réel)
    reste une recette **poste de travail**, que ce test ne remplace pas.
    """

    from jarvis.adapters.openai_realtime import OpenAIRealtimeSession
    from jarvis.runtime.realtime_tools import tools_for

    key = os.environ["OPENAI_API_KEY"]
    model = os.getenv("OPENAI_REALTIME_MODEL", DEFAULT_CONTINUOUS_SURFACE_MODEL)
    voice = os.getenv("OPENAI_REALTIME_VOICE", "cedar")

    # Décision 34 : en mode continu la surface reçoit un catalogue **vide**.
    # Le test le vérifie avant même de se connecter, puis envoie ce catalogue-là.
    tools = tools_for(continuous_brain=True)
    assert tools == []

    session = await OpenAIRealtimeSession.connect(
        api_key=key,
        model=model,
        voice=voice,
        context={},
        tools=tools,
        auto_turn=True,
        continuous_brain=True,
    )
    try:
        request = SpeechRequest(
            conversation_id="conv-live-smoke",
            text="Bonjour, ceci est un test de fumée.",
            kind=SpeechKind.ACK,
        )
        output_id = await session.speak(request)
        assert output_id

        started = False
        audio_bytes = 0

        async def drain() -> None:
            nonlocal started, audio_bytes
            async for envelope in session.events():
                payload = envelope.payload or {}
                if envelope.message_type == "realtime.output_started":
                    # La sortie doit être rattachée à la demande de parole,
                    # sinon ni la troncature ni la mesure 3 ne sauraient à quoi
                    # se raccrocher.
                    assert payload.get("output_id") == output_id
                    assert payload.get("speech_id") == request.id
                    started = True
                elif envelope.message_type == "realtime.audio":
                    audio_bytes += len(str(payload.get("pcm_b64") or ""))
                    assert payload.get("speech_id") == request.id
                    return

        await asyncio.wait_for(drain(), timeout=LIVE_TIMEOUT_S)
        assert started, "le fournisseur n'a jamais ouvert la sortie vocale"
        assert audio_bytes > 0, "le fournisseur n'a rendu aucun audio"

        # Étape 2 de la séquence d'interruption (spec §12) : le fournisseur doit
        # accepter l'annulation de la sortie qu'il vient d'ouvrir.
        await asyncio.wait_for(session.cancel_output(), timeout=LIVE_TIMEOUT_S)
    finally:
        await session.close()


@pytest.mark.asyncio
@gpt_live_only
async def test_real_openai_gpt_live_start_and_confirmed_close():
    """Strict opt-in wire smoke for the production GPT-Live connector."""

    from jarvis.adapters.openai_live_frontend import OpenAILiveFrontend, aiohttp_live_connector
    from jarvis.domain.voice_architecture import DuplexVoiceConfig, VoiceModelRef
    from jarvis.domain.voice_events import FrontendLifecycleChanged, VoiceUsageSource, VoiceUsageUpdated
    from jarvis.domain.voice_frontend import (
        FrontendState, VoiceCorrelation, VoiceFrontendConfig, VoiceOperation,
        VoiceOperationId, VoiceOperationStatus, VoiceSessionId, VoiceStopReason,
    )

    key = os.environ["OPENAI_API_KEY"]
    frontend = OpenAILiveFrontend(
        aiohttp_live_connector(key), voice=os.getenv("OPENAI_LIVE_VOICE", "marin"),
        start_timeout_s=15, close_timeout_s=10,
    )
    correlation = VoiceCorrelation(VoiceSessionId("gpt-live-smoke"))

    def operation(identity: str) -> VoiceOperation:
        return VoiceOperation(VoiceOperationId(identity), correlation)

    observed = []

    async def consume() -> None:
        async for event in frontend.events():
            observed.append(event)

    consumer = asyncio.create_task(consume())
    try:
        async with asyncio.timeout(LIVE_TIMEOUT_S):
            started = await frontend.start(VoiceFrontendConfig(
                DuplexVoiceConfig(VoiceModelRef("openai", "gpt-live-1")),
                instructions="Respond naturally and wait for audio input.",
            ), operation=operation("gpt-live-smoke-start"))
            assert started.status is VoiceOperationStatus.COMPLETED
            assert frontend.state is FrontendState.ACTIVE
            result = await frontend.stop(
                VoiceStopReason.USER, operation=operation("gpt-live-smoke-stop"),
            )
            assert result.status is VoiceOperationStatus.COMPLETED
            assert result.state is frontend.state is FrontendState.STOPPED
            await consumer
            active = next(event for event in observed if
                          event.payload == FrontendLifecycleChanged(FrontendState.ACTIVE))
            assert active.correlation.provider_session_id
            final_usage = next(event.payload for event in observed if
                               isinstance(event.payload, VoiceUsageUpdated) and
                               event.payload.source is VoiceUsageSource.PROVIDER_FINAL)
            assert final_usage.duration_s is not None and final_usage.duration_s >= 0
    finally:
        try:
            if frontend.state is not FrontendState.STOPPED:
                async with asyncio.timeout(12):
                    await frontend.stop(
                        VoiceStopReason.ERROR, operation=operation("gpt-live-smoke-cleanup"),
                    )
        finally:
            try:
                async with asyncio.timeout(12):
                    await frontend.wait_transport_closed()
            finally:
                if not consumer.done():
                    consumer.cancel()
                await asyncio.gather(consumer, return_exceptions=True)

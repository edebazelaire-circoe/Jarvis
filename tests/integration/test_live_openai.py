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
    os.getenv("JARVIS_LIVE_OPENAI") != "1",
    reason="opt-in live provider test",
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

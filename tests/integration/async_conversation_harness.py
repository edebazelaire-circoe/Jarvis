"""Ré-exportation du harnais de conversation asynchrone, désormais dans le produit.

Slice 06 (Category 2 Test Lab, READINESS B4.1) a déplacé le harnais dans
`jarvis/testlab/virtual/harness.py` : le profil d'exécution `virtual` du Test Lab
est du code produit, et le code produit ne peut pas importer `tests.`
(`tests/unit/test_v2_architecture.py::test_production_never_imports_test_frontends`).

Rien n'a changé pour les tests : mêmes noms, mêmes sémantiques, même
`voice_stack(tmp_path, monkeypatch, ...)` — le second paramètre s'appelle
maintenant `patches` et accepte tout objet offrant `setattr(cible, nom, valeur)`,
ce que le `monkeypatch` de pytest fait déjà.
"""

from __future__ import annotations

from jarvis.testlab.virtual.harness import (
    CHUNK_MS,
    FAST_RECONNECT_DELAY_S,
    TIMEOUT_S,
    TOKEN,
    BrainTurnHandle,
    CoreEventRecorder,
    FakeAudio,
    FakeClock,
    FakeRealtimeSession,
    FakeWakeWord,
    FastShutdownRunner,
    ImmediateOutputStream,
    RecordingJournal,
    RecordingSignals,
    ScriptedBrainBackend,
    VoiceStack,
    audio_chunk_b64,
    free_port,
    voice_stack,
    wait_until,
)

__all__ = [
    "CHUNK_MS", "FAST_RECONNECT_DELAY_S", "TIMEOUT_S", "TOKEN", "BrainTurnHandle", "CoreEventRecorder", "FakeAudio",
    "FakeClock", "FakeRealtimeSession", "FakeWakeWord", "FastShutdownRunner", "ImmediateOutputStream",
    "RecordingJournal", "RecordingSignals", "ScriptedBrainBackend", "VoiceStack", "audio_chunk_b64", "free_port",
    "voice_stack", "wait_until",
]

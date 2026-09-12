"""Annulation d'écho WebRTC (AEC3), via le module de traitement audio de LiveKit.

C'est l'annuleur des navigateurs et des visioconférences : il apprend le trajet
haut-parleurs → micro à partir de ce qui est réellement joué, estime lui-même le
retard entre les deux, et retire l'écho de la capture. Le paquet `livekit` en
fournit une roue Windows précompilée, ce qui évite toute compilation locale.

Dépendance optionnelle (extra `voice`) : si elle manque ou ne se charge pas,
`create_echo_canceller()` rend None et la capture en duplex continue avec sa
garde d'écho seule, qui est plus stricte sur le barge-in mais ne laisse jamais
passer JARVIS pour l'utilisateur.
"""

from __future__ import annotations

import importlib.util
from typing import Any


class WebRtcEchoCanceller:
    """`EchoCanceller` adossé à `livekit.rtc.AudioProcessingModule`.

    Les trames font 10 ms, à la fréquence de chaque flux ; les deux fréquences
    peuvent différer (Gemini capte en 16 kHz et rend en 24 kHz). Le module
    reçoit aussi la suppression de bruit et le filtre passe-haut de WebRTC : ils
    rabotent le souffle et les basses fréquences du bureau sans toucher à la
    voix. Le contrôle automatique de gain reste coupé : il remonterait les
    conversations lointaines que l'on cherche justement à ignorer.

    Pas thread-safe : les deux méthodes doivent être appelées du même thread.
    """

    def __init__(self, *, capture_rate: int, render_rate: int, stream_delay_ms: int = 0) -> None:
        from livekit import rtc  # import tardif : dépendance optionnelle

        self._rtc: Any = rtc
        self._capture_samples = int(capture_rate) // 100
        self._render_samples = int(render_rate) // 100
        self._capture_rate = int(capture_rate)
        self._render_rate = int(render_rate)
        self._delay_ms = max(0, min(500, int(stream_delay_ms)))
        self._apm = rtc.AudioProcessingModule(
            echo_cancellation=True,
            noise_suppression=True,
            high_pass_filter=True,
            auto_gain_control=False,
        )

    def process_render(self, frame: bytes) -> None:
        audio = self._rtc.AudioFrame(frame, self._render_rate, 1, self._render_samples)
        self._apm.process_reverse_stream(audio)

    def process_capture(self, frame: bytes) -> bytes:
        audio = self._rtc.AudioFrame(frame, self._capture_rate, 1, self._capture_samples)
        # WebRTC attend le retard avant chaque trame traitée ; AEC3 l'affine
        # de toute façon par sa propre estimation.
        self._apm.set_stream_delay_ms(self._delay_ms)
        self._apm.process_stream(audio)
        return bytes(audio.data)


def echo_cancellation_available() -> bool:
    try:
        from livekit import rtc  # noqa: F401
    except Exception:
        return False
    return True


def echo_cancellation_installed() -> bool:
    """Sonde bon marché (Control Center, tâche 08) : le paquet est-il installé ?

    Ne charge pas la bibliothèque native : un paquet présent qui ne se charge
    pas n'est vu que par Voice, qui le publie (`.voice_capture`).
    """

    try:
        # `livekit` est un paquet d'espace de noms (vide) : seul `rtc` porte l'AEC3.
        return importlib.util.find_spec("livekit.rtc") is not None
    except (ImportError, ValueError):
        return False


def create_echo_canceller(*, capture_rate: int, render_rate: int, stream_delay_ms: int = 0) -> WebRtcEchoCanceller | None:
    """Construire l'annuleur, ou rendre None si la bibliothèque est absente."""

    try:
        return WebRtcEchoCanceller(capture_rate=capture_rate, render_rate=render_rate, stream_delay_ms=stream_delay_ms)
    except Exception:
        return None

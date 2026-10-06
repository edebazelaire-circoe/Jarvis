"""Code court du mode PRESENTATION : un jeton sans espace, jamais une phrase.

Règle unique pour toute chaîne qui sort d'une séance vers un autre lecteur :
attributs des événements de timeline (`jarvis/runtime/presentation_timeline.py`),
relevé `.voice_presentation` écrit par Voice (`VisualSignalBus.presentation`) et
relu par le Control Center (`/api/status.presentation`). Une phrase de la salle
contient des espaces ; un code n'en contient pas. Ce qui n'est pas un code
devient `None`, jamais une version tronquée de la phrase.
"""

from __future__ import annotations

#: Longueur maximale d'un code. Au-delà, ce n'est plus un code.
MAX_CODE_LENGTH = 64


def presentation_code(value: object) -> str | None:
    """Un jeton court et sans espace, ou rien. Jamais une phrase."""

    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > MAX_CODE_LENGTH or any(ch.isspace() for ch in text):
        return None
    return text


__all__ = ["MAX_CODE_LENGTH", "presentation_code"]

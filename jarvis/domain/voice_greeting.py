"""Accueil vocal de la première séance d'un processus Voice.

Retour utilisateur du 2026-10-29 : allumer JARVIS puis le réveiller ne donnait
aucune réponse tant qu'on ne lui parlait pas. La première séance ouverte par
un réveil (mot d'éveil ou touche) dit désormais une phrase courte ; si un
Board de travail est actif, elle propose de le reprendre.

Le texte est une constante française, comme la clarification de
`SpeechScheduler` : il n'y a rien à rédiger, Voice n'appelle pas le cerveau
pour saluer.
"""

from __future__ import annotations

#: Board créé d'office par Core : il ne nomme aucun travail à reprendre.
DEFAULT_BOARD_ID = "default"
#: Au-delà, un titre se lit mal à voix haute : on salue sans le citer.
MAX_SPOKEN_TITLE_CHARS = 80

GREETING_ONLINE = "Oui, monsieur. Je suis en ligne."


def greeting_text(board: object) -> str:
    """La phrase d'accueil, depuis la réponse de `GET /v1/boards/active` (ou rien).

    Un Board nommé autre que le Board par défaut : « Oui, monsieur. Voulez-vous
    reprendre « <titre> » ? ». Sinon, ou si la réponse est illisible : la
    phrase sans reprise.
    """

    record = board.get("board") if isinstance(board, dict) else None
    if not isinstance(record, dict) or record.get("board_id") == DEFAULT_BOARD_ID:
        return GREETING_ONLINE
    title = record.get("title")
    if not isinstance(title, str):
        return GREETING_ONLINE
    title = " ".join(title.split())
    if not title or len(title) > MAX_SPOKEN_TITLE_CHARS:
        return GREETING_ONLINE
    return f"Oui, monsieur. Voulez-vous reprendre « {title} » ?"

"""Autorité de parole en mémoire : quel Board a la parole, à cet instant (handoff board-session, Slice 04b).

Une seule conversation Core parle : celle de la liaison **foreground** de la
Session ouverte (`docs/boards.md`, « Switch and speech authority »). La vérité
durable est dans `jarvis.sqlite3` (Session + liaisons) ; ce module en garde la
copie que la porte de parole de `BrainOrchestrator` lit à chaque parole, sans
entrée-sortie.

Deux propriétaires, un seul écrivain à la fois :

- `lock` sérialise les transitions qui déplacent l'autorité (bascule de
  Board, nouvelle Session). Il est toujours pris **en premier** (avant le
  verrou de `SessionManager`) : deux transitions concurrentes ne s'entrelacent
  jamais, et l'autorité ne change qu'après l'écriture SQLite validée ;
- `set(binding)` est appelé **après** `commit_switch` et avant la publication
  des évènements : entre les deux, aucun `await` — il n'existe donc aucun
  instant où deux conversations passent la porte, ni aucun où la porte suit
  une écriture annulée.

`conversation_id is None` (avant le démarrage de Core, ou Core sans Sessions
dans les tests) : la porte laisse tout passer, comme avant les Boards.
"""

from __future__ import annotations

import asyncio

from jarvis.domain.workspace_board import BoardConversationBinding

#: Évènements publiés sur le bus Core (et donc relayés par `/v1/events`).
BOARD_SWITCHED = "board.switched"
BOARD_VOICE_BINDING_CHANGED = "board.voice_binding.changed"


class SpeechAuthority:
    """La liaison qui a la parole. Voir l'en-tête du module."""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self._binding: BoardConversationBinding | None = None

    @property
    def binding(self) -> BoardConversationBinding | None:
        return self._binding

    @property
    def conversation_id(self) -> str | None:
        return self._binding.conversation_id if self._binding is not None else None

    @property
    def board_id(self) -> str | None:
        return self._binding.board_id if self._binding is not None else None

    def allows(self, conversation_id: str | None) -> bool:
        """Vrai si cette conversation peut parler maintenant (ou si aucune autorité n'est posée)."""

        active = self.conversation_id
        return active is None or conversation_id == active

    def set(self, binding: BoardConversationBinding) -> None:
        """Déplacer l'autorité. Appelé seulement après une écriture validée."""

        self._binding = binding

"""Estampille `board_id` sur les diagnostics de Core qui nomment une conversation (handoff board-session, Slice 07).

Pourquoi
--------
Les alertes d'arrière-plan du Control Center (`jarvis/runtime/background_events.py`)
lisent la trace commune et doivent dire **de quel Board** vient un échec ou
une parole retenue. Les agents du pool écrivent déjà sous un journal lié
(`RuntimeJournal.bind`) ; côté Core, les diagnostics du cerveau nomment une
`conversation_id` mais pas toujours son Board. Plutôt que d'ajouter le champ à
chaque appel (et d'en oublier), le puits de diagnostic l'ajoute une fois.

Résolution
----------
Par le cache des liaisons de `SessionManager` (`cached_board_of`), synchrone
et sans E/S : `emit` est appelé partout, y compris hors boucle asynchrone, et
ne doit ni attendre ni lever. Toute liaison créée ou relue passe par ce cache ;
une conversation inconnue (d'avant les Boards, cache évincé) reste sans
`board_id`, et le Control Center tente alors ses propres liaisons.

Un `board_id` déjà présent dans `data` n'est jamais remplacé (la porte de
parole le calcule elle-même, `speech_withheld_inactive_board`).
"""

from __future__ import annotations

from typing import Any, Callable

from jarvis.ports.v2 import DiagnosticSink

#: `conversation_id -> board_id | None`, sans E/S et sans lever.
BoardResolver = Callable[[str], "str | None"]


class BoardAttributingSink:
    """Puits de diagnostic qui ajoute `board_id` quand `data` nomme une `conversation_id` liée."""

    def __init__(self, inner: DiagnosticSink, resolve: BoardResolver | None = None) -> None:
        self.inner = inner
        #: Branché après la construction de `SessionManager` (le puits sert
        #: avant : Boards, bus et Sessions le reçoivent tous).
        self.resolve = resolve

    def emit(self, kind: str, message: str, *, level: str = "info", data: dict[str, Any] | None = None) -> None:
        self.inner.emit(kind, message, level=level, data=self.attribute(data))

    def attribute(self, data: dict[str, Any] | None) -> dict[str, Any] | None:
        if not data or "board_id" in data or self.resolve is None:
            return data
        conversation_id = data.get("conversation_id")
        if not isinstance(conversation_id, str) or not conversation_id:
            return data
        board_id = self.resolve(conversation_id)
        return {**data, "board_id": board_id} if board_id else data

    def __getattr__(self, name: str) -> Any:
        # Les journaux concrets exposent d'autres membres (`trace_path`,
        # `runtime_root`...) que certains appelants lisent : ils restent ceux
        # du puits enveloppé.
        return getattr(self.inner, name)

"""Plafond des editions de source de l'agent (handoff jarvis-interactive-presentation-studio, Slice 06, QA-1/QA-2).

Chaque edition de source publie une **version** immuable (la validation est structurelle : une erreur de syntaxe n'est vue qu'au
montage) ; une boucle de l'agent les accumulerait. Plafond par scene : au plus `BRAIN_EDIT_LIMIT` demandes par fenetre de
`BRAIN_EDIT_WINDOW_S` secondes, puis `presentation_studio_source_edit_rate` (HTTP 429). L'utilisateur n'est jamais plafonne (ses
retouches sont fusionnees par le coalesceur).

**Le `actor` de Core est une etiquette.** Le relais du Control Center (la page) REMPLACE l'acteur du corps par `user` avant
Core : une page ne peut ni etre plafonnee comme `brain` ni se faire passer pour l'agent. Un appelant direct (jeton porteur) est ce
qu'il declare : la seule porte de l'agent sera la couche d'outils de la Slice 21, qui pose `brain` elle-meme. Aucune identite
de canal n'existe cote Core avant elle ; on n'en invente pas.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from typing import Any

from jarvis.domain.presentation_studio import PresentationStudioError
from jarvis.domain.presentation_studio_checks import PresentationStudioErrorCode as C

BRAIN_EDIT_LIMIT = 10
BRAIN_EDIT_WINDOW_S = 60.0
#: Scenes dont on garde la fenetre en memoire (bornee : les fenetres vides sont oubliees au-dela).
MAX_TRACKED_SCENES = 256


class SourceEditLimiter:
    def __init__(self, monotonic: Callable[[], float], trace: Callable[[str, str, Mapping[str, Any]], None]) -> None:
        self._monotonic, self._trace = monotonic, trace
        self._attempts: dict[tuple[str, str, str], deque[float]] = {}

    def admit(self, key: tuple[str, str, str], *, limited: bool) -> None:
        """`limited` : l'appelant est l'agent. Un refus ne compte pas ; leve `source_edit_rate` quand la fenetre est pleine."""

        if not limited:
            return
        now = self._monotonic()
        recent = self._attempts.setdefault(key, deque())
        while recent and now - recent[0] >= BRAIN_EDIT_WINDOW_S:
            recent.popleft()
        if len(recent) >= BRAIN_EDIT_LIMIT:
            wait = max(1, int(BRAIN_EDIT_WINDOW_S - (now - recent[0])) + 1)
            self._trace("core.presentation_studio.reload_rate_limited", "Editions de source de l'agent plafonnees",
                        {"presentation_id": key[0], "variant_id": key[1], "scene_id": key[2],
                         "limit": BRAIN_EDIT_LIMIT, "window_s": BRAIN_EDIT_WINDOW_S})
            raise PresentationStudioError(
                C.SOURCE_EDIT_RATE, f"{BRAIN_EDIT_LIMIT} source edits per {BRAIN_EDIT_WINDOW_S:g} s is the limit for the "
                                    f"agent on one scene: retry in about {wait} s (each edit publishes a version)", warn=True)
        recent.append(now)
        if len(self._attempts) > MAX_TRACKED_SCENES:
            for stale in [k for k, v in self._attempts.items() if not v or now - v[-1] >= BRAIN_EDIT_WINDOW_S]:
                del self._attempts[stale]

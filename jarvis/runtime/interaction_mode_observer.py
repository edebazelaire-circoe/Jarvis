"""Voice observe le mode d'interaction. Il ne le possède pas, il ne le devine pas.

Core est le seul propriétaire de la valeur effective. Ce module est ce que le
processus Voice en garde : une valeur, une révision, et rien d'autre. Pas de
persistance, pas de préférence, pas de décision — un second état optimiste dans
Voice, c'est exactement ce que la Décision D15 et l'architecture cible
interdisent.

**Aucun redémarrage** (Décision D15). Le mode n'entre pas dans
`VoiceComposition.configuration_id` ; il arrive par l'évènement
``interaction.mode.changed`` sur `/v1/events`, que le processus Voice consomme
déjà pour la parole du cerveau. Un passage SIMPLE ⇄ PRESENTATION ne doit pas
couper l'audio d'une présentation en cours.

Deux entrées, parce que le flux peut se taire :

- `observe(envelope)` — l'évènement vivant ;
- `adopt(snapshot)` — un instantané `GET /v1/interaction-mode`, pour une
  reprise après coupure du flux, ou pour un processus Voice qui n'a pas
  d'abonnement (le legacy n'en ouvre pas).

Les deux passent par la même garde de monotonie : une révision inférieure ou
égale à celle tenue est ignorée. Deux messages qui se croisent ne peuvent donc
pas faire revenir Voice en arrière.
"""

from __future__ import annotations

from typing import Any

from jarvis.core.interaction_mode import INTERACTION_MODE_CHANGED
from jarvis.domain.interaction_mode import (
    DEFAULT_INTERACTION_MODE,
    InteractionMode,
    behaving_interaction_mode,
    parse_interaction_mode,
)
from jarvis.runtime.journal import RuntimeJournal

#: Traces : un changement observé, et un évènement écarté parce qu'illisible.
OBSERVED_KIND = "interaction.mode.observed"
IGNORED_KIND = "interaction.mode.ignored"


class InteractionModeObserver:
    """Dernier mode connu de Core, et sa révision. Jamais de retour en arrière.

    Part du mode assistant à la révision 0, c'est-à-dire « Core ne m'a encore
    rien dit » — le comportement d'avant cette fonctionnalité (Décision 14).
    Rien ne bloque et rien ne lève : un évènement abîmé laisse le mode tenu
    en place et laisse une ligne, au lieu d'éteindre l'observation.
    """

    def __init__(self, *, journal: RuntimeJournal | None = None) -> None:
        self.journal = journal
        self._mode = DEFAULT_INTERACTION_MODE
        self._revision = 0

    @property
    def mode(self) -> InteractionMode:
        """Le comportement que Voice doit servir. Jamais un mode réservé."""

        return self._mode

    @property
    def revision(self) -> int:
        return self._revision

    def observe(self, envelope: Any) -> bool:
        """Prendre un évènement Core. Vrai si le mode tenu a changé.

        Tolère n'importe quelle enveloppe : ce qui n'est pas
        ``interaction.mode.changed`` est ignoré sans un mot, parce que ce
        routeur est appelé sur **tous** les évènements du bus.
        """

        if getattr(envelope, "message_type", None) != INTERACTION_MODE_CHANGED:
            return False
        return self.adopt(getattr(envelope, "payload", None) or {})

    def adopt(self, payload: Any) -> bool:
        """Prendre un état (évènement ou instantané). Vrai si le mode a changé.

        La révision commande : plus ancienne ou égale, l'état est écarté. Égale
        et *différente* est une incohérence de Core, pas un ordre à deviner —
        elle est écartée et dite, parce que la choisir au hasard ferait diverger
        deux processus sans que personne ne le sache.
        """

        if not isinstance(payload, dict):
            self._ignore("interaction_mode_event_malformed", {"payload_type": type(payload).__name__})
            return False
        revision = payload.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            self._ignore("interaction_mode_event_revision_invalid", {"revision": str(revision)[:32]})
            return False
        raw = payload.get("mode")
        parsed = parse_interaction_mode(raw)
        if parsed is None:
            self._ignore("interaction_mode_event_unknown_mode", {"mode": str(raw)[:64], "revision": revision})
            return False
        if revision <= self._revision:
            # Ni erreur ni perte : le flux a doublé un message, ou un
            # instantané de reprise est arrivé après l'évènement qu'il décrit.
            return False
        # `behaving_` et non `stored_` : ceci pilote un comportement. Core ne
        # publie pas de mode réservé, mais Voice ne doit pas dépendre de cette
        # politesse pour ne pas exécuter un comportement qui n'existe pas.
        mode = behaving_interaction_mode(parsed)
        previous, self._mode, self._revision = self._mode, mode, revision
        if previous is mode:
            return False
        self._trace(
            OBSERVED_KIND, f"Mode d'interaction observé : {previous.label} → {mode.label}",
            data={"mode": mode.value, "previous_mode": previous.value, "revision": revision},
        )
        return True

    def _ignore(self, code: str, data: dict[str, Any]) -> None:
        self._trace(
            IGNORED_KIND, f"Évènement de mode d'interaction écarté ({code})",
            level="warning", data={"code": code, "mode_held": self._mode.value,
                                   "revision_held": self._revision, **data},
        )

    def _trace(self, kind: str, message: str, *, level: str = "info", data: dict[str, Any] | None = None) -> None:
        if self.journal is None:
            return
        try:
            self.journal.emit(kind, message, level=level, data=data or {})
        except Exception:  # noqa: BLE001 - un journal indisponible n'arrête pas l'observation
            pass

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
- `adopt(snapshot)` — un instantané `GET /v1/interaction-mode`, pris à chaque
  abonnement réussi au flux (`SpeechScheduler._subscription_ready`), donc à
  chaque reprise après coupure. `CoreEventBus` ne rejoue rien : sans cet
  instantané, un processus Voice démarré après le dernier changement de mode
  resterait au défaut jusqu'au suivant, qui peut ne jamais venir.

Les deux passent par la même garde : d'abord l'**époque** de Core, ensuite la
révision. Deux messages d'une même vie de Core qui se croisent ne peuvent pas
faire revenir Voice en arrière ; un Core redémarré, lui, est cru sans condition,
parce que sa révision repart de 0 et qu'une garde monotone y verrait pour
toujours des messages « plus vieux » que ce qui est tenu.
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
        #: Vie du processus Core dont vient la révision tenue. `None` tant que
        #: rien n'a été observé — et aussi quand un Core sans époque parle.
        self._epoch: str | None = None
        #: Abonnés **synchrones** du mode effectif (Slice 11). Même forme et
        #: même raison qu'`InteractionModeService.add_listener` côté Core
        #: (Slice 04) : quitter PRESENTATION doit rendre le micro **au moment**
        #: du changement, pas au prochain tour de boucle. Un abonné qui lève ne
        #: peut ni annuler le changement ni empêcher les suivants d'être
        #: prévenus — un mode à moitié appliqué serait pire que l'exception.
        self._listeners: list[Any] = []

    def add_listener(self, listener: Any) -> None:
        """Être prévenu quand le mode effectif **change**. Jamais sur un no-op.

        Appelé avec le nouveau mode, après que l'observateur l'a adopté : un
        abonné qui relit `self.mode` doit y voir la nouvelle valeur.
        """

        if not callable(listener):
            raise TypeError("an interaction-mode listener must be callable")
        self._listeners.append(listener)

    def _notify(self, mode: InteractionMode) -> None:
        for listener in tuple(self._listeners):
            try:
                listener(mode)
            except Exception as exc:  # noqa: BLE001 - un abonné en panne n'annule pas le mode
                self._trace(
                    IGNORED_KIND,
                    f"Abonné du mode d'interaction en panne : {type(exc).__name__}: {exc}",
                    level="error",
                    data={"code": "interaction_mode_listener_failed", "mode": mode.value},
                )

    @property
    def mode(self) -> InteractionMode:
        """Le comportement que Voice doit servir. Jamais un mode réservé."""

        return self._mode

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def epoch(self) -> str | None:
        """Vie de Core dont vient la révision tenue, si elle est connue."""

        return self._epoch

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

        **L'époque commande, la révision ensuite.** Une révision est locale à
        une vie de Core : elle repart de 0 au redémarrage, tandis que cet
        observateur vit dans le processus Voice et survit aux coupures du flux.
        Comparer deux révisions d'époques différentes, c'est comparer deux
        horloges qui n'ont jamais été à l'heure ensemble — et le résultat était
        une panne muette : Core redémarré réémettait 1, 2, 3, l'observateur les
        écartait comme « plus vieilles », l'utilisateur choisissait SIMPLE et
        Voice restait en PRESENTATION.

        - époque différente, ou absente (Core plus ancien) : l'état est pris
          **sans condition** et le plancher de révision repart de là. Le biais
          va délibérément vers la fraîcheur : entre servir le mode que
          l'utilisateur vient de choisir et servir celui d'avant un
          redémarrage, c'est le second qui est la panne ;
        - même époque : la garde monotone d'origine. Plus ancienne, l'état est
          écarté sans bruit — le flux a doublé un message, ou un instantané de
          reprise est arrivé après l'évènement qu'il décrit. Révision **égale**
          mais mode différent, en revanche, est une incohérence de Core : elle
          est écartée **et dite**, parce que la trancher au hasard ferait
          diverger deux processus sans que personne ne le sache.
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
        epoch = payload.get("epoch")
        epoch = epoch.strip() if isinstance(epoch, str) and epoch.strip() else None
        # `behaving_` et non `stored_` : ceci pilote un comportement. Core ne
        # publie pas de mode réservé, mais Voice ne doit pas dépendre de cette
        # politesse pour ne pas exécuter un comportement qui n'existe pas.
        mode = behaving_interaction_mode(parsed)
        same_life = epoch is not None and self._epoch is not None and epoch == self._epoch
        if same_life and revision <= self._revision:
            if revision == self._revision and mode is not self._mode:
                self._ignore(
                    "interaction_mode_event_revision_conflict",
                    {"mode": mode.value, "revision": revision},
                )
            return False
        if not same_life and self._epoch is not None:
            # Core a redémarré (ou parle sans époque) : ce qui était tenu ne
            # vaut plus rien. Le dire évite d'avoir à chercher, plus tard,
            # pourquoi la révision a reculé.
            self._trace(
                OBSERVED_KIND, "Nouvelle vie de Core observée : la révision du mode repart de zéro",
                data={"mode": mode.value, "revision": revision,
                      "previous_revision": self._revision,
                      "code": "interaction_mode_core_restarted"},
            )
        if mode is not parsed:
            # Le repli est le bon comportement ; le taire ne l'était pas. Un
            # mode réservé annoncé comme effectif est une anomalie de l'amont.
            self._ignore(
                "interaction_mode_event_reserved_mode", {"mode": parsed.value, "revision": revision},
            )
        previous, self._mode, self._revision, self._epoch = self._mode, mode, revision, epoch
        if previous is mode:
            return False
        self._trace(
            OBSERVED_KIND, f"Mode d'interaction observé : {previous.label} → {mode.label}",
            data={"mode": mode.value, "previous_mode": previous.value, "revision": revision},
        )
        # Après la trace, donc après que l'état est posé : un abonné qui relit
        # l'observateur y voit la valeur neuve, et la ligne existe déjà quand
        # l'abonné en produit d'autres.
        self._notify(mode)
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

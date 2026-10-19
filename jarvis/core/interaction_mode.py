"""Vérité vivante du mode d'interaction. Core la possède, personne d'autre.

Trois processus veulent connaître le mode : le Control Center l'affiche, Voice
doit **se comporter** selon lui, et le cerveau le lira plus tard. Sans propriétaire unique, chacun
garderait sa copie optimiste et deux d'entre elles finiraient par diverger un
soir de présentation.

Le partage est donc :

- rien n'enregistre de mode : il est **dérivé du type du Board actif**
  (`docs/boards.md` › *Board type*). `jarvis/core/board_service.py` le demande
  ici au démarrage de Core (``source="board_restore"``) et à chaque bascule
  (``source="board_switch"``). Le seul autre écrivain est une lecture du
  Presentation Studio, transitoire et restaurée (``source="presentation_studio_run"``,
  appel en processus). Aucune demande venue de l'extérieur de Core n'est prise :
  `POST /v1/interaction-mode` les refuse toutes (`refuse_external_request`,
  ``interaction_mode_derived``) ;
- Core possède la **valeur effective vivante** et sa **révision**, ici ;
- Voice **observe** par l'évènement ``interaction.mode.changed`` relayé par
  ``/v1/events``, ou relit l'instantané ; il ne tient jamais un second mode.

**Décision D15 (Humain, 2026-09-23) : le mode n'entre pas dans
``VoiceComposition.configuration_id``.** Ce condensé décide si
``VoiceSwitchCoordinator`` redémarre le processus Voice
(`jarvis/runtime/voice_switch.py`). Un passage SIMPLE ⇄ PRESENTATION qui
couperait l'audio au milieu d'une présentation est exactement la panne que
cette fonctionnalité ne doit pas introduire. Le mode change donc **à chaud**,
par évènement, et rien ici ne touche à la composition vocale.

La lecture utilisée est délibérément `behaving_interaction_mode` : cette valeur
**pilote un comportement**. Un Board Réunion désigne ``meeting`` — la carte Board
affiche « Réunion · prévu » d'après le type, `/api/status` le publie en `board_mode` —
mais ``meeting`` ne peut pas devenir le mode effectif, parce qu'aucun
comportement de réunion n'existe (Décision 02).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from jarvis.domain.interaction_mode import (
    DEFAULT_INTERACTION_MODE,
    INTERACTION_MODE_DERIVED,
    INTERACTION_MODE_DERIVED_MESSAGE,
    INTERACTION_MODES,
    InteractionMode,
    InteractionModeError,
    behaving_interaction_mode,
    ensure_activatable,
    parse_interaction_mode,
)
from jarvis.domain.v2 import ProtocolEnvelope, new_id, utc_now
from jarvis.ports.v2 import DiagnosticSink


#: Type de message publié sur `CoreEventBus`, donc relayé tel quel par
#: `/v1/events`. Nommage pointé des autres évènements du bus
#: (`core.work.updated`, `voice.turn.admitted`).
INTERACTION_MODE_CHANGED = "interaction.mode.changed"

#: Recopie maximale d'un texte d'exception dans le journal. Même borne que
#: `_mode_value` : un message d'exception vient d'un abonné ou d'un bus, donc
#: d'ailleurs, et rien qui vienne d'ailleurs ne remplit ce journal.
MAX_TRACE_EXCEPTION_CHARS = 200


def _clip(exc: BaseException) -> str:
    return str(exc)[:MAX_TRACE_EXCEPTION_CHARS]


_TRACE_APPLIED = "interaction.mode.applied"
_TRACE_UNCHANGED = "interaction.mode.unchanged"
_TRACE_REFUSED = "interaction.mode.refused"


class InteractionModeDisposition(StrEnum):
    """Ce qu'une demande a réellement produit.

    Séparé du mode rendu : « tu es en PRESENTATION » ne dit pas si cet appel
    y a changé quelque chose, et une écriture idempotente ne doit ni faire
    monter la révision ni réveiller Voice.
    """

    APPLIED = "applied"
    UNCHANGED = "unchanged"


def supported_modes() -> list[dict[str, Any]]:
    """Ce que les écrans peuvent proposer, réservés compris (Décision 02).

    ``REUNION`` est **annoncé** et jamais activable : `implemented` vaut faux,
    et toute activation est refusée avec le code stable
    ``interaction_mode_not_implemented``. Un mode absent de cette liste serait
    un mode dont personne ne saurait qu'il est prévu.
    """

    return [
        {
            "value": mode.value,
            "label": mode.label,
            "status": descriptor.status.value,
            "implemented": descriptor.implemented,
            "default_disposition": descriptor.default_disposition.value,
            "summary": descriptor.summary,
        }
        for mode, descriptor in INTERACTION_MODES.items()
    ]


@dataclass(frozen=True, slots=True)
class InteractionModeState:
    """La seule valeur effective, avec de quoi ordonner deux observations.

    `revision` part de 0 (personne n'a rien demandé) et ne monte que sur un
    changement réel. Un observateur qui reçoit une révision inférieure ou égale
    à celle qu'il tient a affaire à un évènement plus vieux que son état : il
    l'ignore, au lieu de revenir en arrière sur un croisement de messages.

    **`epoch` est ce qui rend cette comparaison sûre.** La révision est locale
    à ce processus et repart de 0 à chaque démarrage de Core, alors que
    l'observateur, lui, vit dans le processus Voice et survit aux coupures du
    flux. Sans époque, un Core redémarré réémettait des révisions 1, 2, 3 que
    Voice écartait comme « plus vieilles » : l'utilisateur choisissait SIMPLE,
    Core l'appliquait, et Voice restait en PRESENTATION sans un mot. L'époque
    est tirée une fois à la construction du service ; deux époques différentes
    ne se comparent pas, elles se remplacent.
    """

    mode: InteractionMode
    revision: int
    epoch: str
    #: Qui a demandé ce mode. Champ libre, journalisé et transporté tel quel ;
    #: depuis la Slice 01b, les valeurs réellement émises sont `board_restore` /
    #: `board_switch` (le mode du type du Board actif, appliqué par
    #: `BoardService`), `presentation_studio_run` (un run temporaire du Studio)
    #: et `default` (l'état initial).
    source: str
    changed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.mode, InteractionMode):
            raise InteractionModeError("interaction_mode_state_invalid", "L'état porte un mode typé, pas une chaîne.")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 0:
            raise InteractionModeError("interaction_mode_state_invalid", "La révision est un entier positif.")
        if not isinstance(self.epoch, str) or not self.epoch.strip():
            raise InteractionModeError("interaction_mode_state_invalid", "L'état porte une époque non vide.")

    def to_payload(self) -> dict[str, Any]:
        """Forme transportée par `/v1/interaction-mode` et par l'évènement.

        `mode` est la valeur interne, `label` l'étiquette verrouillée par la
        Décision 02 : le transport porte les deux pour qu'aucun consommateur
        n'ait à refaire la table, et surtout pour qu'aucun n'ait à transporter
        un mode *par son étiquette* — `SIMPLE` désigne aussi une architecture
        vocale, et c'est le piège nominatif que la Slice 01 a verrouillé.
        """

        return {
            "mode": self.mode.value,
            "label": self.mode.label,
            "revision": self.revision,
            # Vie du processus Core qui a produit cette révision. Un
            # consommateur compare d'abord ceci, et seulement ensuite la
            # révision : deux vies différentes n'ont pas d'ordre commun.
            "epoch": self.epoch,
            "source": self.source,
            "changed_at": self.changed_at.isoformat(),
        }


class InteractionModeService:
    """Propriétaire de la valeur effective. Un seul écrivain, une seule vérité.

    Toute demande passe par un verrou : une bascule de Board qui croise
    l'entrée ou la restauration d'une lecture du Studio, par exemple, se
    sérialisent au lieu de produire deux révisions pour un seul changement.

    Rien n'est persisté ici, à dessein. Un mode effectif est un fait de cette
    vie du processus, dérivé du type du Board actif : `BoardService` le demande
    par ce même `request()` au démarrage de Core (`source="board_restore"`) et
    à chaque bascule (`source="board_switch"`).

    **Il n'y a qu'un seul chemin d'entrée, `request()`, et il est strict**, appelé
    en processus par `BoardService` et par le Presentation Studio. Le protocole
    n'y mène plus : `refuse_external_request` dit et code son refus.
    """

    def __init__(self, *, events: Any, diagnostics: DiagnosticSink | None = None, epoch: str | None = None) -> None:
        self._events = events
        self._diagnostics = diagnostics
        # Un seul écrivain, mais le verrou reste : aujourd'hui la section
        # critique de `_set` ne contient aucun `await` qui rende la main, donc
        # la garantie est en réalité tenue par la boucle asyncio mono-fil. Le
        # verrou est là pour le jour où elle en contiendra un — un `await`
        # ajouté entre la lecture de `held` et l'écriture de `self._state`
        # rouvrirait sinon la fenêtre que ce verrou ferme.
        self._lock = asyncio.Lock()
        # Identité de **cette vie** de Core, tirée une fois. `epoch` n'est
        # injecté que par les tests : en production, deux services ne doivent
        # jamais pouvoir se faire passer l'un pour l'autre.
        self._epoch = epoch or new_id()
        #: Abonnés synchrones, prévenus au moment du changement (`add_listener`) :
        #: `(appelable, reçoit l'état complet)`.
        self._listeners: list[tuple[Any, bool]] = []
        self._state = InteractionModeState(
            mode=DEFAULT_INTERACTION_MODE, revision=0, epoch=self._epoch, source="default",
            changed_at=utc_now(),
        )

    @property
    def state(self) -> InteractionModeState:
        return self._state

    @property
    def mode(self) -> InteractionMode:
        """Le comportement qui tourne. Jamais un mode réservé."""

        return self._state.mode

    @property
    def revision(self) -> int:
        return self._state.revision

    @property
    def epoch(self) -> str:
        """Identité de cette vie de Core. Deux époques ne se comparent pas."""

        return self._epoch

    def snapshot(self) -> dict[str, Any]:
        """Ce que rend `GET /v1/interaction-mode` : l'état et ce qui existe."""

        return {**self._state.to_payload(), "modes": supported_modes()}

    async def request(self, value: object, *, source: str) -> tuple[InteractionModeState, InteractionModeDisposition]:
        """Demande **explicite** de changement. Refuse bruyamment, ne devine rien.

        C'est le **seul** chemin d'entrée : une valeur illisible est une erreur
        à dire, pas un réglage à ignorer, parce que quelqu'un a demandé quelque
        chose. Deux refus typés, tous deux avec un code stable :

        - ``interaction_mode_unknown`` : la valeur n'est pas un mode. Aucun
          repli silencieux sur le défaut — l'appelant croirait avoir obtenu ce
          qu'il a demandé ;
        - ``interaction_mode_not_implemented`` : le mode existe, il est annoncé,
          il n'a aucun comportement (``REUNION``). C'est `ensure_activatable`
          de la Slice 01 qui le dit, avec son message français.
        """

        mode = parse_interaction_mode(value)
        if mode is None:
            self._trace(
                _TRACE_REFUSED, f"Mode d'interaction inconnu refusé (origine {source})", level="warning",
                data={"code": "interaction_mode_unknown", "source": source, "mode": self._mode_value(value)},
            )
            raise InteractionModeError(
                "interaction_mode_unknown",
                "Mode d'interaction inconnu : attendu « assistant », « presentation » ou « meeting ».",
            )
        try:
            ensure_activatable(mode)
        except InteractionModeError as exc:
            self._trace(
                _TRACE_REFUSED, f"Activation refusée du mode {mode.label} (origine {source})", level="warning",
                data={"code": exc.code, "source": source, "mode": mode.value},
            )
            raise
        return await self._set(mode, source=source)

    async def _set(self, mode: InteractionMode, *, source: str) -> tuple[InteractionModeState, InteractionModeDisposition]:
        async with self._lock:
            held = self._state
            if held.mode is mode:
                # Idempotence : ni révision, ni évènement. Un réenregistrement
                # de la même valeur ne doit pas faire croire à Voice qu'un
                # changement a eu lieu — mais il laisse quand même une ligne,
                # sinon un appel reçu et un appel jamais arrivé auraient la
                # même trace.
                self._trace(
                    _TRACE_UNCHANGED, f"Mode d'interaction déjà {mode.label} (origine {source})",
                    data={"mode": mode.value, "revision": held.revision, "source": source},
                )
                unchanged = held
            else:
                unchanged = None
                state = InteractionModeState(
                    mode=mode, revision=held.revision + 1, epoch=self._epoch, source=source,
                    changed_at=utc_now(),
                )
                self._state = state
                self._trace(
                    _TRACE_APPLIED,
                    f"Mode d'interaction {held.mode.label} → {mode.label} (origine {source})",
                    data={"mode": mode.value, "previous_mode": held.mode.value,
                          "revision": state.revision, "source": source},
                )
        if unchanged is not None:
            # Une demande sans effet n'est notifiée à personne et ne publie rien.
            return unchanged, InteractionModeDisposition.UNCHANGED
        self._notify(state)
        await self._publish(state)
        return state, InteractionModeDisposition.APPLIED

    def add_listener(self, listener: Any, *, with_state: bool = False) -> None:
        """Brancher un état de Core que le mode doit retirer **tout de suite**.

        Ajouté par la Slice 04 pour la mémoire de séance PRESENTATION
        (`jarvis/core/presentation_working_set.py`) : quitter PRESENTATION doit
        la retirer au moment où le mode change, pas un aller-retour de bus plus
        tard. Un abonné de `/v1/events` conviendrait pour *apprendre* le
        changement ; il ne convient pas pour *cesser de retenir* ce qui a été
        dit dans la pièce.

        Le contrat est étroit à dessein : l'appelable reçoit le mode typé, il
        est synchrone, et il ne peut pas empêcher le changement de mode — une
        exception est journalisée et avalée là, parce qu'un état qui refuse de
        se retirer ne doit pas bloquer l'utilisateur qui quitte PRESENTATION.

        `with_state=True` : l'appelable reçoit l'`InteractionModeState` du
        changement (mode, révision, **source**) au lieu du seul mode. Une
        demande sans effet (mode déjà effectif) n'est notifiée à personne.
        """

        if not callable(listener):
            raise InteractionModeError(
                "interaction_mode_listener_invalid", "Un observateur de mode est un appelable."
            )
        self._listeners.append((listener, bool(with_state)))

    def remove_listener(self, listener: Any) -> None:
        """Débrancher un abonné (arrêt de son propriétaire). Absent : rien."""

        # `!=`, not `is not`: a bound method is a new object at each attribute access.
        self._listeners = [entry for entry in self._listeners if entry[0] != listener]

    def _notify(self, state: InteractionModeState) -> None:
        for listener, with_state in tuple(self._listeners):
            try:
                listener(state if with_state else state.mode)
            except Exception as exc:  # noqa: BLE001 - un abonné cassé ne bloque pas un changement de mode
                self._trace(
                    "interaction.mode.listener_failed",
                    f"Observateur de mode en échec : {type(exc).__name__}: {_clip(exc)}",
                    level="error",
                    data={"code": "interaction_mode_listener_failed", "mode": state.mode.value,
                          "revision": state.revision},
                )

    async def _publish(self, state: InteractionModeState) -> None:
        """Dire le changement à qui écoute. Une panne du bus ne perd pas l'état.

        Publié **hors** du verrou : `CoreEventBus.publish` parcourt ses abonnés
        et ne doit pas tenir la porte pendant qu'un autre processus demande le
        mode. L'état, lui, est déjà posé — un abonné qui rate l'évènement le
        retrouve entier dans l'instantané, ce qui est exactement pourquoi
        l'instantané existe.
        """

        # La charge utile porte **l'état**, pas le catalogue : `supported_modes()`
        # est constant, l'observateur l'ignore, et l'instantané le porte déjà.
        # Le mettre ici donnerait aux abonnés une seconde porte vers « ce qui
        # existe » — exactement ce que l'en-tête de ce module refuse ailleurs.
        envelope = ProtocolEnvelope(
            message_type=INTERACTION_MODE_CHANGED,
            payload=state.to_payload(),
        )
        try:
            await self._events.publish(envelope)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - un bus en panne ne perd pas le mode
            self._trace(
                "interaction.mode.publish_failed",
                f"Changement de mode non diffusé : {type(exc).__name__}: {_clip(exc)}",
                level="error",
                data={"code": "interaction_mode_publish_failed", "mode": state.mode.value,
                      "revision": state.revision},
            )

    def refuse_external_request(self, value: object, *, source: object) -> InteractionModeError:
        """Refus d'une demande venue de l'extérieur de Core (`POST /v1/interaction-mode`), tracé.

        Toujours, quelle que soit la valeur ou l'origine : le mode suit le type du
        Board actif (Slice 01b). Le Studio, seul écrivain transitoire, appelle
        `request()` en processus et ne passe jamais par ici. Rend l'erreur, que
        la route sérialise en 409 ; rien n'est changé.
        """

        self._trace(
            _TRACE_REFUSED, "Demande de mode refusée : le mode suit le type du Board actif", level="warning",
            data={"code": INTERACTION_MODE_DERIVED, "source": self._mode_value(source),
                  "mode": self._mode_value(value)},
        )
        return InteractionModeError(INTERACTION_MODE_DERIVED, INTERACTION_MODE_DERIVED_MESSAGE)

    @staticmethod
    def _mode_value(value: object) -> str:
        """Ce qu'on a reçu, borné et sans contenu utilisateur.

        Une valeur refusée vient d'un réglage ou d'un appel, jamais d'une
        transcription ; elle est quand même tronquée, parce qu'un journal ne
        doit pas pouvoir être rempli par un champ de saisie.
        """

        if value is None:
            return "absent"  # Slice 08 (polish S01b) : un champ manquant n'est pas une valeur `NoneType`
        text = value if isinstance(value, str) else type(value).__name__
        return text[:64]

    def _trace(self, kind: str, message: str, *, level: str = "info", data: dict[str, Any] | None = None) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=data or {})
        except Exception:  # noqa: BLE001 - un journal indisponible n'empêche pas de changer de mode
            pass

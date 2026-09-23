"""Vérité vivante du mode d'interaction. Core la possède, personne d'autre.

Trois processus veulent connaître le mode : le Control Center l'affiche et
enregistre la **préférence** de l'utilisateur, Voice doit **se comporter**
selon lui, et le cerveau le lira plus tard. Sans propriétaire unique, chacun
garderait sa copie optimiste et deux d'entre elles finiraient par diverger un
soir de présentation.

Le partage est donc :

- le Control Center possède la **persistance** (`jarvis/runtime/interaction_mode_settings.py`,
  clé ``interaction_mode`` de ``runtime/control-center-settings.json``) ;
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
**pilote un comportement**. Un ``meeting`` laissé sur le disque reste affichable
— c'est le Control Center qui le montre, avec `stored_interaction_mode` — mais
il ne peut pas devenir le mode effectif, parce qu'aucun comportement de réunion
n'existe (Décision 02).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from jarvis.domain.interaction_mode import (
    DEFAULT_INTERACTION_MODE,
    INTERACTION_MODES,
    InteractionMode,
    InteractionModeError,
    behaving_interaction_mode,
    ensure_activatable,
    parse_interaction_mode,
)
from jarvis.domain.v2 import ProtocolEnvelope, utc_now
from jarvis.ports.v2 import DiagnosticSink


#: Type de message publié sur `CoreEventBus`, donc relayé tel quel par
#: `/v1/events`. Nommage pointé des autres évènements du bus
#: (`core.work.updated`, `voice.turn.admitted`).
INTERACTION_MODE_CHANGED = "interaction.mode.changed"

#: Origines connues d'une demande. Libre, mais ces trois-là sont les vraies :
#: l'écran, la réconciliation au démarrage, et un appel direct du protocole.
SOURCE_CONTROL_CENTER = "control_center"
SOURCE_STARTUP = "startup"

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
    """

    mode: InteractionMode
    revision: int
    source: str
    changed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.mode, InteractionMode):
            raise InteractionModeError("interaction_mode_state_invalid", "L'état porte un mode typé, pas une chaîne.")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 0:
            raise InteractionModeError("interaction_mode_state_invalid", "La révision est un entier positif.")

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
            "source": self.source,
            "changed_at": self.changed_at.isoformat(),
        }


class InteractionModeService:
    """Propriétaire de la valeur effective. Un seul écrivain, une seule vérité.

    Toute demande passe par un verrou : deux clics simultanés, ou une
    réconciliation de démarrage qui croise une demande de l'écran, se
    sérialisent au lieu de produire deux révisions pour un seul changement.

    Rien n'est persisté ici, à dessein. Un mode effectif est un fait de cette
    vie du processus ; la préférence, elle, appartient au Control Center, qui
    la rejoue par `reconcile()` au démarrage.
    """

    def __init__(self, *, events: Any, diagnostics: DiagnosticSink | None = None) -> None:
        self._events = events
        self._diagnostics = diagnostics
        self._lock = asyncio.Lock()
        self._state = InteractionModeState(
            mode=DEFAULT_INTERACTION_MODE, revision=0, source="default", changed_at=utc_now(),
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

    def snapshot(self) -> dict[str, Any]:
        """Ce que rend `GET /v1/interaction-mode` : l'état et ce qui existe."""

        return {**self._state.to_payload(), "modes": supported_modes()}

    async def request(self, value: object, *, source: str) -> tuple[InteractionModeState, InteractionModeDisposition]:
        """Demande **explicite** de changement. Refuse bruyamment, ne devine rien.

        Distincte de `reconcile()` : ici quelqu'un a cliqué, donc une valeur
        illisible est une erreur à dire, pas un réglage à ignorer. Deux refus
        typés, tous deux avec un code stable :

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

    async def reconcile(self, value: object, *, source: str = SOURCE_STARTUP) -> tuple[InteractionModeState, InteractionModeDisposition]:
        """Rejouer une préférence **enregistrée**. Total, silencieux, sans panne.

        C'est le chemin « je relis ce qui traîne sur le disque » : manquant,
        mal typé, inconnu, corrompu, ou ``meeting`` — tout donne le mode
        assistant, et Jarvis démarre. Un réglage abîmé ne doit jamais empêcher
        le démarrage, ni démarrer dans un mode que personne n'a demandé
        (Décision 14).

        La journalisation, elle, n'est pas silencieuse : un repli sur le défaut
        est dit, sinon « il a démarré en SIMPLE » et « son réglage était
        illisible » se ressembleraient à l'octet près.
        """

        mode = behaving_interaction_mode(value)
        stored = parse_interaction_mode(value)
        if stored is None and value is not None:
            self._trace(
                _TRACE_REFUSED, "Préférence de mode d'interaction illisible : mode assistant appliqué",
                level="warning",
                data={"code": "interaction_mode_unreadable", "source": source, "mode": self._mode_value(value)},
            )
        elif stored is not None and stored is not mode:
            self._trace(
                _TRACE_REFUSED,
                f"Le mode {stored.label} est enregistré mais n'a aucun comportement : mode assistant appliqué",
                level="warning",
                data={"code": "interaction_mode_not_implemented", "source": source, "mode": stored.value},
            )
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
                return held, InteractionModeDisposition.UNCHANGED
            state = InteractionModeState(
                mode=mode, revision=held.revision + 1, source=source, changed_at=utc_now(),
            )
            self._state = state
            self._trace(
                _TRACE_APPLIED,
                f"Mode d'interaction {held.mode.label} → {mode.label} (origine {source})",
                data={"mode": mode.value, "previous_mode": held.mode.value,
                      "revision": state.revision, "source": source},
            )
        await self._publish(state)
        return state, InteractionModeDisposition.APPLIED

    async def _publish(self, state: InteractionModeState) -> None:
        """Dire le changement à qui écoute. Une panne du bus ne perd pas l'état.

        Publié **hors** du verrou : `CoreEventBus.publish` parcourt ses abonnés
        et ne doit pas tenir la porte pendant qu'un autre processus demande le
        mode. L'état, lui, est déjà posé — un abonné qui rate l'évènement le
        retrouve entier dans l'instantané, ce qui est exactement pourquoi
        l'instantané existe.
        """

        envelope = ProtocolEnvelope(
            message_type=INTERACTION_MODE_CHANGED,
            payload={**state.to_payload(), "modes": supported_modes()},
        )
        try:
            await self._events.publish(envelope)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - un bus en panne ne perd pas le mode
            self._trace(
                "interaction.mode.publish_failed",
                f"Changement de mode non diffusé : {type(exc).__name__}: {exc}",
                level="error",
                data={"code": "interaction_mode_publish_failed", "mode": state.mode.value,
                      "revision": state.revision},
            )

    @staticmethod
    def _mode_value(value: object) -> str:
        """Ce qu'on a reçu, borné et sans contenu utilisateur.

        Une valeur refusée vient d'un réglage ou d'un appel, jamais d'une
        transcription ; elle est quand même tronquée, parce qu'un journal ne
        doit pas pouvoir être rempli par un champ de saisie.
        """

        text = value if isinstance(value, str) else type(value).__name__
        return text[:64]

    def _trace(self, kind: str, message: str, *, level: str = "info", data: dict[str, Any] | None = None) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=data or {})
        except Exception:  # noqa: BLE001 - un journal indisponible n'empêche pas de changer de mode
            pass

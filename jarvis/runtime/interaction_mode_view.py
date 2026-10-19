"""Le Control Center lit le mode d'interaction effectif chez Core. Lecture seule.

Core possède la valeur effective (`jarvis/core/interaction_mode.py`), dérivée du
type du Board actif (`docs/boards.md` › *Board type*). Ce module est le fil de
lecture, sur sa propre connexion. Il n'écrit rien : Core refuse toute demande
de mode venue de l'extérieur (`interaction_mode_derived`, Slice 01b de
`jarvis-board-ui-wheel-dossier-refactor`).

Ce qui compte ici est ce qu'on fait quand Core ne répond pas. Un écran qui
afficherait « SIMPLE » parce que la lecture a échoué mentirait exactement au
moment où il ne faut pas. Alors la réponse porte ``core_reachable: false``, un
``code`` d'indisponibilité et un **repli explicitement nommé** (``source:
"local"``) : le mode du type du Board actif quand le Control Center le connaît,
sinon le mode assistant, jamais présenté comme la vérité vivante.

Codes et forme repris de `work_view.CoreWorkView`, qui résout le même problème
pour l'état de travail.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from jarvis.domain.interaction_mode import (
    InteractionMode, behaving_interaction_mode, is_activatable, parse_interaction_mode,
)
from jarvis.protocol.client import CoreProtocolError
from jarvis.runtime.agent_tasks import truncate
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.work_ingress import CoreWorkTransport
from jarvis.runtime.work_view import CORE_REFUSED, CORE_UNREACHABLE, INVALID_SNAPSHOT, NOT_CONFIGURED

#: `source` de la valeur rendue : Core l'a dite, ou c'est le repli local.
SOURCE_CORE = "core"
SOURCE_LOCAL = "local"

#: Le sondage du statut bat chaque seconde : un Core figé ne doit pas empiler
#: des requêtes derrière lui.
DEFAULT_READ_TIMEOUT_S = 2.0


class InteractionModeReader(Protocol):
    """`GET /v1/interaction-mode` (`CoreInteractionModeTransport` en production)."""

    async def interaction_mode(self) -> dict[str, Any]: ...

    async def close(self) -> None: ...


class CoreInteractionModeTransport(CoreWorkTransport):
    """Connexion propre au mode d'interaction, jeton relu à chaque (re)connexion.

    Séparée de celle du panneau Agents : un jeton périmé d'un côté ne doit pas
    fermer la session de l'autre. Un 401 (Core redémarré) est relu puis la
    lecture rejouée une fois.
    """

    async def interaction_mode(self) -> dict[str, Any]:
        try:
            return await self._connect().interaction_mode()
        except CoreProtocolError as exc:
            if exc.status != 401:
                raise
        await self.close()
        return await self._connect().interaction_mode()


def local_payload(fallback: InteractionMode, *, code: str, message: str) -> dict[str, Any]:
    """Réponse quand la vérité vivante n'est pas lisible : le repli, nommé.

    ``mode`` porte le comportement que `fallback` produirait (le mode du type du
    Board actif quand le Control Center le connaît, sinon le défaut), parce
    qu'un écran doit afficher quelque chose, et ``source: "local"`` dit d'où il
    vient. ``revision`` reste ``null`` : une révision est une propriété de la
    vérité de Core, en inventer une ferait croire à un ordre qui n'existe pas.

    **Le repli passe par la même règle que `_decode`** : `behaving_`, donc
    jamais un mode réservé. Le mode du type du Board, Réunion compris, reste
    publié à part (``board_mode`` dans `/api/status`, lecture de diagnostic ; la
    carte Board dit « Réunion · prévu » d'après le type du Board, Décision 02).
    """

    effective = behaving_interaction_mode(fallback)
    return {
        "mode": effective.value,
        "label": effective.label,
        "revision": None,
        "epoch": None,
        "source": SOURCE_LOCAL,
        "core_reachable": False,
        "error": {"code": code, "message": message},
    }


class CoreInteractionModeView:
    """Lecture du mode effectif, tolérante à un Core absent."""

    def __init__(
        self,
        reader: InteractionModeReader | None,
        *,
        journal: RuntimeJournal | None = None,
        timeout_s: float = DEFAULT_READ_TIMEOUT_S,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("timeouts must be positive")
        self.reader = reader
        self.journal = journal
        self.timeout_s = timeout_s
        self._reported: set[str] = set()

    async def read(self, fallback: InteractionMode) -> dict[str, Any]:
        """Le mode effectif selon Core, ou le repli local nommé (`fallback`). Ne lève jamais.

        Appelée par `/api/status`, qui bat chaque seconde : elle ne peut pas
        faire tomber le statut, dont dépend tout l'affichage de la page.
        """

        if self.reader is None:
            return local_payload(fallback, code=NOT_CONFIGURED,
                                 message="Core n'est pas configuré : mode d'interaction non confirmé.")
        try:
            raw = await asyncio.wait_for(self.reader.interaction_mode(), timeout=self.timeout_s)
            return self._decode(raw)
        except asyncio.CancelledError:
            raise
        except (TypeError, ValueError) as exc:
            self._report(exc)
            return local_payload(fallback, code=INVALID_SNAPSHOT, message="Mode d'interaction Core illisible.")
        except CoreProtocolError as exc:
            return local_payload(fallback, code=CORE_REFUSED,
                                 message=f"Core a refusé la lecture ({exc.status} {exc.code}).")
        except Exception as exc:  # noqa: BLE001 - Core arrêté, jeton absent, délai, réseau
            detail = truncate(str(exc), 160) or type(exc).__name__
            return local_payload(fallback, code=CORE_UNREACHABLE, message=f"Core injoignable : {detail}")

    @staticmethod
    def _decode(raw: Any) -> dict[str, Any]:
        """Valider la réponse de Core. Un mode inconnu est une erreur, pas un défaut.

        Ici la valeur vient de Core, qui ne peut en produire
        que des valides : une valeur inattendue est un défaut à corriger et
        doit se voir.
        """

        if not isinstance(raw, dict):
            raise TypeError("interaction mode response must be an object")
        mode = raw.get("mode")
        parsed = parse_interaction_mode(mode)
        if parsed is None:
            raise ValueError(f"interaction mode response carries an unknown mode: {mode!r}")
        if not is_activatable(parsed):
            # Un mode réservé ne peut pas être la valeur **effective** : Core
            # n'en publie pas, et l'accepter installerait dans l'écran un
            # comportement qui n'existe pas (Décision 02).
            raise ValueError(f"interaction mode response carries a reserved mode: {mode!r}")
        revision = raw.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ValueError("interaction mode response carries no usable revision")
        epoch = raw.get("epoch")
        return {
            "mode": parsed.value,
            "label": parsed.label,
            "revision": revision,
            # Vie de Core à laquelle appartient cette révision. Rendue telle
            # quelle, `None` comprise : une révision sans son époque ne
            # s'ordonne pas contre celle d'un Core redémarré.
            "epoch": epoch if isinstance(epoch, str) and epoch.strip() else None,
            "source": SOURCE_CORE,
            "core_reachable": True,
            "error": None,
        }

    async def aclose(self) -> None:
        if self.reader is None:
            return
        try:
            await self.reader.close()
        except Exception:  # noqa: BLE001 - l'arrêt du Control Center ne reste jamais bloqué
            pass

    def _report(self, exc: Exception) -> None:
        name = type(exc).__name__
        if self.journal is None or name in self._reported:
            return
        self._reported.add(name)
        try:
            self.journal.emit(
                "interaction.mode.view_invalid",
                "Réponse de mode d'interaction illisible : le repli local est affiché à la place.",
                level="error",
                data={"exception_type": name, "error": truncate(str(exc), 200)},
            )
        except Exception:  # noqa: BLE001 - un journal indisponible n'arrête pas la lecture
            pass

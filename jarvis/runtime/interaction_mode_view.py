"""Le Control Center lit et demande le mode d'interaction à Core.

Core possède la valeur effective (`jarvis/core/interaction_mode.py`), le
Control Center possède la préférence enregistrée
(`jarvis/runtime/interaction_mode_settings.py`). Ce module est le fil entre les
deux, sur sa propre connexion, en lecture **et** en demande.

Ce qui compte ici est ce qu'on fait quand Core ne répond pas. Un écran qui
afficherait « SIMPLE » parce que la lecture a échoué mentirait exactement au
moment où il ne faut pas. Alors :

- lecture impossible : la réponse porte ``core_reachable: false``, un ``code``
  d'indisponibilité et la **préférence enregistrée** comme repli explicitement
  nommé (``source: "settings"``), jamais présentée comme la vérité vivante ;
- demande impossible : elle **échoue** et le dit. Le réglage a pu être écrit,
  mais rien n'est appliqué tant que Core ne l'a pas pris ; l'appelant doit
  pouvoir le dire à l'écran.

Codes et forme repris de `work_view.CoreWorkView`, qui résout le même problème
pour l'état de travail.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from jarvis.domain.interaction_mode import InteractionMode, is_activatable, parse_interaction_mode
from jarvis.protocol.client import CoreProtocolError
from jarvis.runtime.agent_tasks import truncate
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.work_ingress import CoreWorkTransport
from jarvis.runtime.work_view import CORE_REFUSED, CORE_UNREACHABLE, INVALID_SNAPSHOT, NOT_CONFIGURED

#: `source` de la valeur rendue : Core l'a dite, ou c'est le repli local.
SOURCE_CORE = "core"
SOURCE_SETTINGS = "settings"

#: Le sondage du statut bat chaque seconde : un Core figé ne doit pas empiler
#: des requêtes derrière lui.
DEFAULT_READ_TIMEOUT_S = 2.0
#: Une demande explicite vaut la peine d'attendre un peu plus qu'une lecture.
DEFAULT_WRITE_TIMEOUT_S = 5.0


class InteractionModeReader(Protocol):
    """`GET`/`POST /v1/interaction-mode` (`CoreInteractionModeTransport` en production)."""

    async def interaction_mode(self) -> dict[str, Any]: ...

    async def set_interaction_mode(self, mode: str, *, source: str | None = None) -> dict[str, Any]: ...

    async def close(self) -> None: ...


class CoreInteractionModeTransport(CoreWorkTransport):
    """Connexion propre au mode d'interaction, jeton relu à chaque (re)connexion.

    Séparée de celle du panneau Agents : un jeton périmé d'un côté ne doit pas
    fermer la session de l'autre. Un 401 (Core redémarré) est relu puis rejoué
    une fois — pour la lecture comme pour la demande, qui est idempotente :
    redemander le même mode ne fait pas monter la révision.
    """

    async def interaction_mode(self) -> dict[str, Any]:
        try:
            return await self._connect().interaction_mode()
        except CoreProtocolError as exc:
            if exc.status != 401:
                raise
        await self.close()
        return await self._connect().interaction_mode()

    async def set_interaction_mode(self, mode: str, *, source: str | None = None) -> dict[str, Any]:
        try:
            return await self._connect().set_interaction_mode(mode, source=source)
        except CoreProtocolError as exc:
            if exc.status != 401:
                raise
        await self.close()
        return await self._connect().set_interaction_mode(mode, source=source)


class InteractionModeUnavailable(RuntimeError):
    """Core n'a pas pris la demande. Porte le code que l'écran doit afficher."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def local_payload(stored: InteractionMode, *, code: str, message: str) -> dict[str, Any]:
    """Réponse quand la vérité vivante n'est pas lisible : le repli, nommé.

    ``mode`` porte la préférence enregistrée parce qu'un écran doit afficher
    quelque chose, et ``source: "settings"`` dit d'où elle vient. ``revision``
    reste ``null`` : une révision est une propriété de la vérité de Core, en
    inventer une ferait croire à un ordre qui n'existe pas.
    """

    return {
        "mode": stored.value,
        "label": stored.label,
        "revision": None,
        "source": SOURCE_SETTINGS,
        "core_reachable": False,
        "error": {"code": code, "message": message},
    }


class CoreInteractionModeView:
    """Lecture et demande du mode effectif, tolérantes à un Core absent."""

    def __init__(
        self,
        reader: InteractionModeReader | None,
        *,
        journal: RuntimeJournal | None = None,
        timeout_s: float = DEFAULT_READ_TIMEOUT_S,
        write_timeout_s: float = DEFAULT_WRITE_TIMEOUT_S,
    ) -> None:
        if timeout_s <= 0 or write_timeout_s <= 0:
            raise ValueError("timeouts must be positive")
        self.reader = reader
        self.journal = journal
        self.timeout_s = timeout_s
        self.write_timeout_s = write_timeout_s
        self._reported: set[str] = set()

    async def read(self, stored: InteractionMode) -> dict[str, Any]:
        """Le mode effectif selon Core, ou le repli local nommé. Ne lève jamais.

        Appelée par `/api/status`, qui bat chaque seconde : elle ne peut pas
        faire tomber le statut, dont dépend tout l'affichage de la page.
        """

        if self.reader is None:
            return local_payload(stored, code=NOT_CONFIGURED,
                                 message="Core n'est pas configuré : mode d'interaction enregistré affiché.")
        try:
            raw = await asyncio.wait_for(self.reader.interaction_mode(), timeout=self.timeout_s)
            return self._decode(raw)
        except asyncio.CancelledError:
            raise
        except (TypeError, ValueError) as exc:
            self._report(exc)
            return local_payload(stored, code=INVALID_SNAPSHOT, message="Mode d'interaction Core illisible.")
        except CoreProtocolError as exc:
            return local_payload(stored, code=CORE_REFUSED,
                                 message=f"Core a refusé la lecture ({exc.status} {exc.code}).")
        except Exception as exc:  # noqa: BLE001 - Core arrêté, jeton absent, délai, réseau
            detail = truncate(str(exc), 160) or type(exc).__name__
            return local_payload(stored, code=CORE_UNREACHABLE, message=f"Core injoignable : {detail}")

    async def request(self, mode: InteractionMode, *, source: str) -> dict[str, Any]:
        """Demander le mode à Core. **Lève** si Core ne l'a pas pris.

        Contrairement à `read`, cet échec ne se rattrape pas : personne ne doit
        croire qu'une présentation est armée parce qu'un réglage a été écrit.
        Le refus métier de Core (``interaction_mode_not_implemented``) remonte
        avec **son** code, jamais retraduit.
        """

        if self.reader is None:
            raise InteractionModeUnavailable(
                NOT_CONFIGURED,
                "Core n'est pas configuré : le mode est enregistré mais rien ne l'applique.",
            )
        try:
            raw = await asyncio.wait_for(
                self.reader.set_interaction_mode(mode.value, source=source), timeout=self.write_timeout_s,
            )
        except asyncio.CancelledError:
            raise
        except CoreProtocolError as exc:
            raise InteractionModeUnavailable(
                exc.code or CORE_REFUSED,
                str(exc) or f"Core a refusé le mode {mode.label} ({exc.status}).",
            ) from exc
        except Exception as exc:  # noqa: BLE001 - Core arrêté, jeton absent, délai, réseau
            detail = truncate(str(exc), 160) or type(exc).__name__
            raise InteractionModeUnavailable(
                CORE_UNREACHABLE,
                f"Core injoignable, mode non appliqué : {detail}",
            ) from exc
        try:
            return self._decode(raw)
        except (TypeError, ValueError) as exc:
            self._report(exc)
            raise InteractionModeUnavailable(
                INVALID_SNAPSHOT, "Core a répondu hors contrat à la demande de mode.",
            ) from exc

    @staticmethod
    def _decode(raw: Any) -> dict[str, Any]:
        """Valider la réponse de Core. Un mode inconnu est une erreur, pas un défaut.

        `read` retombe sur le défaut pour un *réglage* abîmé, ce qui est une
        tolérance voulue. Ici la valeur vient de Core, qui ne peut en produire
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
        return {
            "mode": parsed.value,
            "label": parsed.label,
            "revision": revision,
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
                "Réponse de mode d'interaction illisible : le réglage enregistré est affiché à la place.",
                level="error",
                data={"exception_type": name, "error": truncate(str(exc), 200)},
            )
        except Exception:  # noqa: BLE001 - un journal indisponible n'arrête pas la lecture
            pass

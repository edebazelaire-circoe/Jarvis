"""Projection de l'état de travail Core pour le Control Center (handoff work-state, tâche 13).

Le panneau Agents affiche l'état **normalisé** que Core tient
(`GET /v1/work/snapshot`), le même que le cerveau reçoit à chaque tour
(`BrainWorkContext` porte la même paire `store_id` / `revision`). Le suivi
du fournisseur (`AgentTaskTracker`, `/api/agent/tasks`) ne sert plus qu'au
diagnostic : trace brute, prompt, type de sous-agent.

Lecture seule : ce module ne sait que lire l'instantané. Rien, dans le
Control Center, ne modifie l'état de travail de Core depuis l'interface ;
seul l'observateur du flux (`WorkIngressForwarder`) lui remet des faits.

Révisions : un instantané plus ancien que celui déjà servi, pour le même
`store_id`, n'en prend pas la place (deux lectures concurrentes peuvent se
croiser) ; un autre `store_id` (Core redémarré) remplace tout.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from jarvis.domain.work_state import WorkSnapshot
from jarvis.protocol.client import CoreProtocolError
from jarvis.runtime.agent_tasks import truncate
from jarvis.runtime.journal import RuntimeJournal

#: Valeur de `source` de `GET /api/work` : l'état vient de Core, jamais du tracker.
WORK_VIEW_SOURCE = "core"
#: Délai de lecture : le panneau sonde chaque seconde, un Core figé ne doit
#: pas empiler des requêtes.
DEFAULT_READ_TIMEOUT_S = 2.0

#: Codes d'indisponibilité rendus dans `error.code`.
NOT_CONFIGURED = "not_configured"
CORE_UNREACHABLE = "core_unreachable"
CORE_REFUSED = "core_refused"
INVALID_SNAPSHOT = "invalid_snapshot"


class WorkSnapshotReader(Protocol):
    """Accès en lecture à `GET /v1/work/snapshot` (`CoreWorkTransport` en production)."""

    async def snapshot(self) -> dict[str, Any]: ...

    async def close(self) -> None: ...


def accept_snapshot(held: tuple[str, int] | None, store_id: str, revision: int) -> bool:
    """Vrai si l'instantané `(store_id, revision)` peut remplacer celui tenu.

    Même magasin : jamais de retour en arrière (une révision égale est le
    même état). Autre magasin : Core a redémarré, ce qui était tenu ne vaut
    plus rien et l'instantané neuf prend la place, quelle que soit sa révision.
    """

    if held is None or held[0] != store_id:
        return True
    return revision >= held[1]


def unavailable_payload(code: str, message: str) -> dict[str, Any]:
    """Réponse de `GET /api/work` quand l'état Core n'est pas lisible : aucun élément."""

    return {
        "source": WORK_VIEW_SOURCE,
        "core_reachable": False,
        "store_id": None,
        "revision": None,
        "items": [],
        "updated_at": None,
        "stale": False,
        "error": {"code": code, "message": message},
    }


@dataclass(frozen=True, slots=True)
class _Held:
    store_id: str
    snapshot: WorkSnapshot


class CoreWorkView:
    """Dernier instantané Core servi au panneau, gardé contre les retours en arrière.

    Chaque `read()` relit Core : l'instantané est petit (64 éléments au plus)
    et la boucle locale ne coûte presque rien. Core injoignable : réponse
    `core_reachable: false`, sans éléments — l'interface le dit, elle ne
    fait pas passer le tracker pour la vérité.
    """

    def __init__(
        self,
        reader: WorkSnapshotReader,
        *,
        journal: RuntimeJournal | None = None,
        timeout_s: float = DEFAULT_READ_TIMEOUT_S,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self.reader = reader
        self.journal = journal
        self.timeout_s = timeout_s
        self._held: _Held | None = None
        self._reported: set[str] = set()

    @property
    def held(self) -> tuple[str, int] | None:
        """`(store_id, revision)` du dernier instantané accepté."""

        return (self._held.store_id, self._held.snapshot.revision) if self._held is not None else None

    async def read(self) -> dict[str, Any]:
        try:
            raw = await asyncio.wait_for(self.reader.snapshot(), timeout=self.timeout_s)
            store_id, snapshot = self._decode(raw)
        except asyncio.CancelledError:
            raise
        except (TypeError, ValueError) as exc:
            # Core a répondu, mais pas selon le contrat : défaut à corriger,
            # consigné une fois par type d'erreur.
            self._report(exc)
            return unavailable_payload(INVALID_SNAPSHOT, "Instantané de travail Core illisible.")
        except CoreProtocolError as exc:
            return unavailable_payload(CORE_REFUSED, f"Core a refusé la lecture ({exc.status} {exc.code}).")
        except Exception as exc:  # noqa: BLE001 - Core arrêté, jeton absent, délai, réseau
            detail = truncate(str(exc), 160) or type(exc).__name__
            return unavailable_payload(CORE_UNREACHABLE, f"Core injoignable : {detail}")
        stale = not accept_snapshot(self.held, store_id, snapshot.revision)
        if not stale:
            self._held = _Held(store_id, snapshot)
        held = self._held
        assert held is not None
        return {
            "source": WORK_VIEW_SOURCE,
            "core_reachable": True,
            "store_id": held.store_id,
            **held.snapshot.to_payload(),
            # Vrai quand la lecture était plus ancienne que l'état déjà servi :
            # c'est ce dernier qui est rendu, inchangé.
            "stale": stale,
            "error": None,
        }

    @staticmethod
    def _decode(raw: Any) -> tuple[str, WorkSnapshot]:
        """Valider la réponse de Core ; seuls les champs déclarés de `WorkItem` survivent."""

        if not isinstance(raw, dict):
            raise TypeError("work snapshot response must be an object")
        store_id = raw.get("store_id")
        if not isinstance(store_id, str) or not store_id.strip():
            raise ValueError("work snapshot response has no store_id")
        return store_id, WorkSnapshot.from_payload(raw)

    async def aclose(self) -> None:
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
                "work.view_invalid_snapshot",
                "Instantané de travail Core illisible : le panneau Agents affiche Core indisponible.",
                level="error",
                data={"exception_type": name, "error": truncate(str(exc), 200)},
            )
        except Exception:  # noqa: BLE001 - un journal indisponible n'arrête pas la lecture
            pass

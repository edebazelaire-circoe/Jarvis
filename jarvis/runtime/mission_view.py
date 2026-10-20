"""Lecture de l'historique des missions de Core pour le Control Center (organic-agent-orchestration, Slice 05).

Routes du Control Center (lecture seule, relais de `jarvis/protocol/mission_routes.py`) :

| Route | Core |
| --- | --- |
| `GET /api/missions/health` | `GET /v1/missions/health` |
| `GET /api/missions/{mission_id}` | `GET /v1/missions/{mission_id}` |
| `GET /api/missions/work/{work_source}/{work_external_id}` | `GET /v1/missions/work/...` |

Rien ici n'écrit une mission : seules les déclarations du hook, relayées par
`declaration_relay.py`, en créent. Refus : le statut et le code de Core
(`mission_not_found` 404...) ; Core injoignable ou lent : 503 `core_unreachable`
après `DEFAULT_READ_TIMEOUT_S` ; non configuré : 503 `not_configured`. Chaque
refus est consigné (`missions.read_failed`) avec son code, jamais le corps.
Contrat : `docs/agent-orchestration.md` § Routes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from jarvis.protocol.client import CoreProtocolError
from jarvis.runtime.agent_tasks import truncate
from jarvis.runtime.journal import RuntimeJournal

DEFAULT_READ_TIMEOUT_S = 3.0
NOT_CONFIGURED = "not_configured"
CORE_UNREACHABLE = "core_unreachable"
READ_FAILED_KIND = "missions.read_failed"


def failure(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "code": code, "error": message}


class CoreMissionView:
    """Relais en lecture vers Core (`CoreMissionTransport`), borné dans le temps, chaque refus consigné."""

    def __init__(self, transport: Any, *, journal: RuntimeJournal | None = None,
                 timeout_s: float = DEFAULT_READ_TIMEOUT_S) -> None:
        self.transport = transport
        self.journal = journal
        self.timeout_s = timeout_s

    async def _read(self, operation: str, call: Callable[[], Awaitable[dict[str, Any]]]) -> tuple[int, dict[str, Any]]:
        try:
            body = await asyncio.wait_for(call(), timeout=self.timeout_s)
        except asyncio.CancelledError:
            raise
        except CoreProtocolError as exc:
            status, code, message = exc.status, exc.code, exc.message
        except TimeoutError:
            status, code, message = 503, CORE_UNREACHABLE, f"Core n'a pas répondu en {self.timeout_s:g} s."
        except Exception as exc:  # noqa: BLE001 - Core arrêté, jeton absent, réseau : dit tel quel, consigné
            status, code, message = 503, CORE_UNREACHABLE, f"Core injoignable : {type(exc).__name__}: {exc}"
        else:
            return 200, body
        if self.journal is not None:
            try:
                self.journal.emit(READ_FAILED_KIND, f"Lecture des missions refusée ({operation}) : {code}",
                                  level="warning" if status < 500 else "error",
                                  data={"operation": operation, "status": status, "code": code,
                                        "error": truncate(str(message), 200)})
            except OSError:
                pass  # intentional: an unwritable journal must not turn the answer into a second failure
        return status, failure(code, str(message))

    async def health(self) -> tuple[int, dict[str, Any]]:
        return await self._read("health", self.transport.health)

    async def mission(self, mission_id: str) -> tuple[int, dict[str, Any]]:
        return await self._read("mission", lambda: self.transport.mission(mission_id))

    async def for_work(self, work_source: str, work_external_id: str) -> tuple[int, dict[str, Any]]:
        return await self._read("work", lambda: self.transport.for_work(work_source, work_external_id))

    async def close(self) -> None:
        await self.transport.close()

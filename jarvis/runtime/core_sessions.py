"""Le Control Center lit et écrit les Sessions et Boards de Core (handoff board-session, Slice 04a).

Sa propre connexion, jeton relu à chaque (re)connexion, comme les autres vues
Core du Control Center (`CoreWorkTransport`). Un 401 (Core redémarré avec un
autre jeton) est relu puis rejoué une fois : les lectures sont sans effet, et
`report_binding_agent` est idempotent. `new_session` ne l'est pas : un 401 veut
dire que Core n'a rien fait (jeton refusé avant la route), le rejouer est sûr.

Capacités utilisées par le Control Center :

- `current_session()` : `GET /v1/sessions/current`, pour adopter l'agent en
  cours comme foreground de la liaison active au démarrage ;
- `new_session()` : `POST /v1/sessions/new`, pour
  `/api/agent/restart {"new_conversation": true}` ;
- `report_binding_agent()` : `POST /v1/sessions/bindings/report`, le CLI réel
  et son identifiant de reprise ;
- `active_board()` : `GET /v1/boards/active`, qui dit si Core a des Boards (fin
  du rejeu du mode d'interaction global) ;
- `forward()` : relais transparent de `/api/boards*`, `/api/sessions*` vers
  `/v1/boards*`, `/v1/sessions*` (Slice 04b, `jarvis/runtime/board_routes.py`).

Un Core antérieur répond 404 (route absente) : c'est « non pris en charge »,
à l'appelant d'en tirer le comportement historique (`is_unsupported`).
"""

from __future__ import annotations

from typing import Any

from jarvis.protocol.client import CoreProtocolError
from jarvis.runtime.work_ingress import CoreWorkTransport


def is_unsupported(exc: BaseException) -> bool:
    """Route absente sur un Core plus ancien : 404/405 **sans** code JSON (réponse texte d'aiohttp).

    Un 404 codé (`session_not_found`, `binding_not_found`) est une vraie réponse
    de Core, pas une absence de capacité.
    """

    return isinstance(exc, CoreProtocolError) and exc.status in (404, 405) and exc.code == "http_error"


class CoreSessionTransport(CoreWorkTransport):
    """`/v1/sessions*` et `/v1/boards/active` vus du Control Center."""

    async def _twice(self, call):  # noqa: ANN001, ANN202 - appelle `call(client)` avec relecture du jeton
        try:
            return await call(self._connect())
        except CoreProtocolError as exc:
            if exc.status != 401:
                raise
        await self.close()
        return await call(self._connect())

    async def current_session(self) -> dict[str, Any]:
        return await self._twice(lambda client: client.current_session())

    async def new_session(self, *, expected_session_id: str | None = None) -> dict[str, Any]:
        return await self._twice(lambda client: client.new_session(expected_session_id=expected_session_id))

    async def forward(self, method: str, path: str, *, params: dict[str, str] | None = None,
                      body: bytes | None = None) -> tuple[int, Any]:
        """Proxy `/api/boards*`, `/api/sessions*` (Slice 04b) : statut et JSON de Core tels quels.

        Un 401 (jeton de Core changé) est relu puis rejoué une fois : Core a
        refusé avant la route, rien n'a été fait.
        """

        status, payload = await self.forward_once(method, path, params=params, body=body)
        if status != 401:
            return status, payload
        await self.close()
        return await self.forward_once(method, path, params=params, body=body)

    async def forward_once(self, method: str, path: str, *, params: dict[str, str] | None = None,
                           body: bytes | None = None) -> tuple[int, Any]:
        return await self._connect().forward_json(method, path, params=params, body=body)

    async def report_binding_agent(self, *, jarvis_session_id: str, board_id: str, agent_cli: str,
                                   agent_session_id: str | None) -> dict[str, Any]:
        return await self._twice(lambda client: client.report_binding_agent(
            jarvis_session_id=jarvis_session_id, board_id=board_id, agent_cli=agent_cli,
            agent_session_id=agent_session_id,
        ))

    async def active_board(self) -> dict[str, Any]:
        return await self._twice(lambda client: client.active_board())

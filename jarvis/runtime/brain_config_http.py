"""Routes HTTP de la configuration des cerveaux, **non montées** : la Slice 07 les ajoute au Control Center.

| Route | Effet |
| --- | --- |
| `GET /api/brains/{brain_id}/config` | descripteur du cerveau (le descripteur lui-même, sans enveloppe) |
| `PATCH /api/brains/{brain_id}/config` `{"base_revision", <un champ>}` | écrit un champ chez son propriétaire |

Succès : `200 {"ok": true, "changed", "applies", "config": {…}}` (descripteur relu, faisant foi). Refus :
`{"ok": false, "code", "reason", "field", "config"}` avec le statut du code (`jarvis.domain.brain_config.ERROR_STATUS` :
`404` cerveau inconnu, `409` révision périmée ou cerveau absent de l'architecture courante, `400` corps illisible,
`422` champ non supporté ou valeur refusée, `423` champ verrouillé, `503` catalogue indisponible, `500` écriture
impossible). `config` est `null` quand le descripteur ne peut pas être relu. Contrat : docs/brain-config.md.
"""

from __future__ import annotations

import json
from typing import Any

from aiohttp import web

from jarvis.domain.brain_config import REQUEST_INVALID, SNAPSHOT_FAILED, BrainConfigError
from jarvis.runtime.brain_config import BrainConfigService

CONFIG_ROUTE = "/api/brains/{brain_id}/config"
MAX_BODY_BYTES = 64 * 1024


class BrainConfigRoutes:
    def __init__(self, service: BrainConfigService, *, journal: Any = None) -> None:
        self.service, self.journal = service, journal

    def routes(self) -> list[web.RouteDef]:
        return [web.get(CONFIG_ROUTE, self.get_config), web.patch(CONFIG_ROUTE, self.patch_config)]

    async def get_config(self, request: web.Request) -> web.Response:
        brain_id = request.match_info["brain_id"]
        try:
            config = await self.service.describe(brain_id)
        except BrainConfigError as exc:
            return self._refuse(exc, brain_id, "read", None)
        except Exception as exc:  # noqa: BLE001 - capture: the route answers a coded failure, never a traceback
            return self._refuse(BrainConfigError(SNAPSHOT_FAILED, f"Lecture de la configuration impossible : "
                                                 f"{type(exc).__name__}: {exc}"), brain_id, "read", None, error=exc)
        self._emit("brain_config.read", "Configuration du cerveau lue.",
                   {"code": "brain_config_read", "brain_id": brain_id, "revision": config["revision"]})
        return web.json_response(config)

    async def patch_config(self, request: web.Request) -> web.Response:
        brain_id = request.match_info["brain_id"]
        try:
            raw = await request.content.read(MAX_BODY_BYTES + 1)
            if len(raw) > MAX_BODY_BYTES:
                raise BrainConfigError(REQUEST_INVALID, f"Corps trop grand (au plus {MAX_BODY_BYTES} octets).")
            try:
                body = json.loads(raw.decode("utf-8") or "null")
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise BrainConfigError(REQUEST_INVALID, "Corps JSON illisible.") from exc
            result = await self.service.patch(brain_id, body)
        except BrainConfigError as exc:
            return self._refuse(exc, brain_id, "patch", await self._config_or_none(brain_id))
        except Exception as exc:  # noqa: BLE001 - capture: nothing half-written is reported as written
            failure = BrainConfigError("brain_config_write_failed", f"Écriture impossible : {type(exc).__name__}: {exc}")
            return self._refuse(failure, brain_id, "patch", await self._config_or_none(brain_id), error=exc)
        return web.json_response({"ok": True, **result})

    async def _config_or_none(self, brain_id: str) -> dict[str, Any] | None:
        try:
            return await self.service.describe(brain_id)
        except Exception:  # noqa: BLE001
            return None  # argued: the refusal itself is the answer; an unreadable descriptor is reported as null

    def _refuse(self, exc: BrainConfigError, brain_id: str, action: str, config: dict[str, Any] | None, *,
                error: Exception | None = None) -> web.Response:
        level = "error" if exc.status >= 500 else "warning"
        self._emit("brain_config.rejected", f"Configuration du cerveau refusée : {exc.reason}",
                   {"code": exc.code, "brain_id": brain_id[:40], "field": exc.field, "action": action,
                    "status": exc.status, **({"error_class": type(error).__name__} if error else {})}, level=level)
        return web.json_response({"ok": False, "code": exc.code, "reason": exc.reason, "field": exc.field,
                                  "config": config}, status=exc.status)

    def _emit(self, kind: str, message: str, data: dict[str, Any], *, level: str = "info") -> None:
        if self.journal is None:
            return
        try:
            self.journal.emit(kind, message, level=level, data=data)
        except OSError:
            pass  # argued: an unwritable trace never changes the answer served

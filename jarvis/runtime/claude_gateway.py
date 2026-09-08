"""Accès du runtime Voice à l'agent Claude local.

L'agent vit dans le processus Control Center — c'est sa responsabilité déclarée
(« Run Jarvis visualizer + Control Center + local Claude agent »). Voice, qui est
un processus distinct, le joint donc par HTTP sur la boucle locale.

Ce module est volontairement mince : il ne fait que porter une demande vocale
jusqu'à l'agent et rapporter sa réponse, en transformant toute panne en un
message que JARVIS peut prononcer plutôt qu'en exception qui casserait le tour.
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp


class ClaudeGateway:
    # Une tâche Claude qui lit des fichiers et lance des commandes dure
    # couramment plusieurs dizaines de secondes.
    DEFAULT_TIMEOUT_S = 600.0

    def __init__(self, *, base_url: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._http: aiohttp.ClientSession | None = None

    async def _session(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            # La marge couvre le trajet HTTP : c'est le Control Center qui
            # arbitre le vrai délai d'attente de Claude.
            self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout_s + 30))
        return self._http

    async def ask(self, request: str) -> dict[str, Any]:
        text = (request or "").strip()
        if not text:
            return {"ok": False, "spoken": "Je n'ai pas compris la demande.", "code": "empty_request"}
        try:
            http = await self._session()
            async with http.post(
                f"{self.base_url}/api/agent/ask",
                json={"text": text, "timeout_s": self.timeout_s},
            ) as response:
                if response.status != 200:
                    detail = (await response.text())[:200]
                    return self._failure("claude_http_error", f"Claude n'a pas pu être joint ({response.status}).", detail)
                payload = await response.json()
        except asyncio.TimeoutError:
            return self._failure("claude_timeout", "Claude met trop de temps à répondre.")
        except aiohttp.ClientError as exc:
            return self._failure("claude_unreachable", "L'agent Claude n'est pas joignable.", str(exc))

        if not isinstance(payload, dict):
            return self._failure("claude_bad_response", "Réponse inattendue de l'agent Claude.")
        if not payload.get("ok"):
            return self._failure(
                str(payload.get("code") or "claude_failed"),
                str(payload.get("error") or "Claude n'a pas pu traiter la demande."),
            )
        return {
            "ok": True,
            "spoken": str(payload.get("text") or ""),
            "duration_ms": payload.get("duration_ms"),
            "permission_denials": payload.get("permission_denials") or [],
        }

    @staticmethod
    def _failure(code: str, spoken: str, detail: str = "") -> dict[str, Any]:
        result: dict[str, Any] = {"ok": False, "spoken": spoken, "code": code}
        if detail:
            result["detail"] = detail
        return result

    async def close(self) -> None:
        http, self._http = self._http, None
        if http is not None and not http.closed:
            await http.close()

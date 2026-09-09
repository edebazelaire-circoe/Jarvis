from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import aiohttp

from jarvis.domain.v2 import PROTOCOL_VERSION, ProtocolEnvelope, new_id
from jarvis.v2_config import validate_loopback_host


class CoreProtocolError(RuntimeError):
    """Erreur rendue par Core, avec de quoi décider quoi faire.

    Hérite de `RuntimeError` pour ne rien casser des appelants existants, qui
    l'attrapaient sous cette forme. Le statut et le code sont exposés parce que
    la surface doit distinguer des situations qui n'appellent pas la même
    conduite : 404 (conversation inconnue) est définitif, 503 (`core_stopping`)
    est transitoire et rejouable avec la même corrélation.
    """

    __slots__ = ("status", "code")

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"Core protocol error {status}: {code}: {message}")
        self.status = status
        self.code = code


class LocalCoreClient:
    def __init__(self, *, host: str, port: int, token: str, session: aiohttp.ClientSession | None = None) -> None:
        self.host = validate_loopback_host(host)
        self.port = port
        self.base_url = f"http://{self.host}:{self.port}"
        self.token = token
        self._session = session
        self._owns_session = session is None

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "X-Jarvis-Protocol": str(PROTOCOL_VERSION)}

    async def _http(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        return self._session

    async def health(self) -> dict[str, Any]:
        session = await self._http()
        async with session.get(self.base_url + "/v1/health", headers=self.headers) as response:
            return await self._json(response)

    async def create_conversation(self, *, device_id: str = "windows-desktop") -> dict[str, Any]:
        session = await self._http()
        async with session.post(self.base_url + "/v1/conversations", headers=self.headers, json={"device_id": device_id}) as response:
            return await self._json(response)

    async def context(self, conversation_id: str) -> dict[str, Any]:
        session = await self._http()
        async with session.get(self.base_url + f"/v1/conversations/{conversation_id}/context", headers=self.headers) as response:
            return await self._json(response)

    async def append_turn(self, conversation_id: str, *, kind: str, content: str, correlation_id: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        session = await self._http()
        payload = {"kind": kind, "content": content, "correlation_id": correlation_id or new_id(), "metadata": metadata or {}}
        async with session.post(self.base_url + f"/v1/conversations/{conversation_id}/turns", headers=self.headers, json=payload) as response:
            return await self._json(response)

    async def submit_brain_turn(self, conversation_id: str, *, content: str, correlation_id: str | None = None, source: str = "realtime", addressing: str = "addressed", provider_item_id: str | None = None, interrupted_speech_id: str | None = None) -> dict[str, Any]:
        """Soumettre un tour utilisateur complet faisant autorité au cerveau.

        Rend l'accusé (`turn_id`, `revision`, `duplicate`, ...) sans attendre le
        modèle fort : la suite du tour arrive par `events()`. Cet appel remplace
        `append_turn()` pour les tours routés vers le cerveau ; les appeler tous
        les deux persisterait le tour deux fois.

        `correlation_id` est la clé de rejeu : un appelant qui réessaie doit
        réutiliser la même valeur, sinon Core y verra deux tours distincts. La
        valeur générée par défaut ne convient donc qu'à une première tentative.
        La déduplication côté Core est en mémoire et ne survit pas à un
        redémarrage (Décision 29, détaillée dans le docstring du endpoint).

        `addressing` dit ce que la surface a cru du tour : `"addressed"` par
        défaut, `"uncertain"` quand elle n'a pas su si la phrase lui était
        adressée et laisse la question au cerveau (Décision 44). `"ambient"`
        n'est pas une valeur soumissible : Core la refuse.

        Erreurs : `CoreProtocolError` avec `status=404` pour une conversation
        inconnue (définitif) et `status=503`, `code="core_stopping"` pour un
        Core en cours d'arrêt (transitoire, rejouable à l'identique). Un rejeu
        reconnu n'est pas une erreur : il rend 200 avec `duplicate=true`.
        """

        session = await self._http()
        payload = {
            "content": content,
            "correlation_id": correlation_id or new_id(),
            "source": source,
            "addressing": addressing,
            "provider_item_id": provider_item_id,
            "interrupted_speech_id": interrupted_speech_id,
        }
        async with session.post(self.base_url + f"/v1/conversations/{conversation_id}/brain-turns", headers=self.headers, json=payload) as response:
            return await self._json(response)

    async def call_tool(self, name: str, arguments: dict[str, object], *, conversation_id: str | None = None) -> dict[str, Any]:
        session = await self._http()
        payload = {"name": name, "arguments": arguments, "conversation_id": conversation_id}
        async with session.post(self.base_url + "/v1/tools/call", headers=self.headers, json=payload) as response:
            return await self._json(response)

    async def confirm_action(self, action_id: str, text: str) -> dict[str, Any]:
        session = await self._http()
        async with session.post(self.base_url + f"/v1/actions/{action_id}/confirmation", headers=self.headers, json={"text": text}) as response:
            return await self._json(response)

    async def events(self) -> AsyncIterator[ProtocolEnvelope]:
        session = await self._http()
        async with session.ws_connect(self.base_url.replace("http://", "ws://") + "/v1/events", headers=self.headers, heartbeat=20) as ws:
            async for message in ws:
                if message.type == aiohttp.WSMsgType.TEXT:
                    data = message.json()
                    if data.get("message_type") in {"connected", "ack"}:
                        continue
                    yield ProtocolEnvelope(message_type=data["message_type"], payload=data.get("payload") or {}, correlation_id=data.get("correlation_id") or new_id(), protocol_version=int(data.get("protocol_version", PROTOCOL_VERSION)), device_id=data.get("device_id") or "windows-desktop", conversation_id=data.get("conversation_id"))
                elif message.type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                    break

    async def close(self) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    @staticmethod
    async def _json(response: aiohttp.ClientResponse) -> dict[str, Any]:
        data = await response.json()
        if response.status >= 400:
            error = data.get("error") or {}
            raise CoreProtocolError(response.status, str(error.get("code", "unknown")), str(error.get("message", "")))
        return data

"""Documented GPT-Live sideband attach-and-close recovery adapter."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import json
import math
from typing import Protocol
from urllib.parse import quote

from jarvis.domain.live_lifecycle import live_id, live_seconds
from jarvis.ports.live_sideband import LIVE_CLOSE_REASONS, LiveTerminalReceipt


LIVE_SIDEBAND_URL = "wss://api.openai.com/v1/live/sessions/{session_id}/attach"
MAX_PROVIDER_MESSAGE_BYTES = 1_048_576
# Durée de vie maximale d'une session Live chez OpenAI. Passé ce délai le
# fournisseur a détruit la session : elle ne facture plus, et s'y rattacher
# ne peut plus rien confirmer. Connaissance propre au fournisseur, donc
# déclarée ici et injectée dans le watchdog, qui reste neutre.
PROVIDER_MAX_SESSION_SECONDS = 3600.0


class LiveSidebandTransport(Protocol):
    async def send_json(self, value: dict[str, object]) -> None: ...
    async def receive_json(self) -> dict[str, object] | None: ...
    async def close(self) -> None: ...


LiveSidebandConnector = Callable[[str], Awaitable[LiveSidebandTransport]]


class AiohttpLiveSidebandTransport:
    def __init__(self, session, socket) -> None:
        self._session = session
        self._socket = socket

    @classmethod
    async def connect(cls, api_key: str, provider_session_id: str):
        key = api_key if isinstance(api_key, str) else ""
        if not key:
            raise ValueError("OpenAI API key is required")
        provider_id = live_id(provider_session_id, "provider_session_id")
        import aiohttp
        session = aiohttp.ClientSession(headers={"Authorization": f"Bearer {key}"})
        try:
            socket = await session.ws_connect(
                LIVE_SIDEBAND_URL.format(session_id=quote(provider_id, safe="")),
            )
        except BaseException:
            await session.close()
            raise
        return cls(session, socket)

    async def send_json(self, value: dict[str, object]) -> None:
        await self._socket.send_json(value)

    async def receive_json(self) -> dict[str, object] | None:
        import aiohttp
        message = await self._socket.receive()
        if message.type is aiohttp.WSMsgType.TEXT:
            raw = message.data
            try:
                byte_count = len(raw.encode("utf-8")) if isinstance(raw, str) else -1
            except UnicodeError as exc:
                raise ValueError("invalid Live sideband JSON encoding") from exc
            if byte_count < 0 or byte_count > MAX_PROVIDER_MESSAGE_BYTES:
                raise ValueError("Live sideband message exceeds byte bound")
            def pairs(items):
                value = {}
                for key, item in items:
                    if key in value:
                        raise ValueError("duplicate Live sideband JSON key")
                    value[key] = item
                return value
            def nonfinite(_value):
                raise ValueError("nonfinite Live sideband JSON number")
            def finite_float(value):
                parsed = float(value)
                if not math.isfinite(parsed):
                    raise ValueError("nonfinite Live sideband JSON number")
                return parsed
            try:
                value = json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite,
                                   parse_float=finite_float)
            except (ValueError, RecursionError) as exc:
                raise ValueError("invalid Live sideband JSON") from exc
            if not isinstance(value, dict):
                raise ValueError("Live sideband message must be an object")
            return value
        if message.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED}:
            return None
        if message.type is aiohttp.WSMsgType.ERROR:
            raise RuntimeError("Live sideband socket failed")
        raise ValueError("unsupported Live sideband frame")

    async def close(self) -> None:
        try:
            await self._socket.close()
        finally:
            await self._session.close()


def aiohttp_live_sideband_connector(api_key: str) -> LiveSidebandConnector:
    async def connect(provider_session_id: str) -> LiveSidebandTransport:
        return await AiohttpLiveSidebandTransport.connect(api_key, provider_session_id)
    return connect


class OpenAILiveSidebandCloser:
    """Attach to one known session, then wait for its authoritative close receipt."""

    def __init__(self, connector: LiveSidebandConnector,
                 *, cleanup_timeout_seconds: float = 1.0) -> None:
        if not callable(connector):
            raise ValueError("Live sideband connector is required")
        try:
            valid_cleanup = (not isinstance(cleanup_timeout_seconds, bool)
                             and isinstance(cleanup_timeout_seconds, (int, float))
                             and math.isfinite(cleanup_timeout_seconds)
                             and cleanup_timeout_seconds > 0)
        except OverflowError:
            valid_cleanup = False
        if not valid_cleanup:
            raise ValueError("Live sideband cleanup timeout must be finite and positive")
        self._connector = connector
        self._cleanup_timeout = float(cleanup_timeout_seconds)
        self._cleanups: set[asyncio.Task[None]] = set()

    async def close_session(
        self, provider_session_id: str,
        on_receipt: Callable[[LiveTerminalReceipt], Awaitable[None]],
    ) -> LiveTerminalReceipt:
        if not callable(on_receipt):
            raise ValueError("Live terminal receipt sink is required")
        provider_id = live_id(provider_session_id, "provider_session_id")
        transport = await self._connector(provider_id)
        ready = asyncio.Event()
        reader = asyncio.create_task(
            self._read_receipt(transport, provider_id, ready, on_receipt),
            name="jarvis-live-sideband-reader",
        )
        sender: asyncio.Task[None] | None = None
        try:
            await ready.wait()
            sender = asyncio.create_task(
                transport.send_json({"type": "session.close"}),
                name="jarvis-live-sideband-close-send",
            )
            done, _pending = await asyncio.wait(
                {reader, sender}, return_when=asyncio.FIRST_COMPLETED,
            )
            if reader in done:
                return await reader
            await sender
            return await reader
        finally:
            cleanup = asyncio.create_task(
                self._cleanup(transport, reader, sender), name="jarvis-live-sideband-cleanup",
            )
            self._cleanups.add(cleanup)
            cleanup.add_done_callback(self._cleanup_done)

    def _cleanup_done(self, task: asyncio.Task[None]) -> None:
        self._cleanups.discard(task)
        try:
            task.exception()
        except (BaseException, asyncio.InvalidStateError):
            pass

    async def _cleanup(self, transport: LiveSidebandTransport,
                       reader: asyncio.Task[LiveTerminalReceipt],
                       sender: asyncio.Task[None] | None) -> None:
        if sender is not None and not sender.done():
            sender.cancel()
        if not reader.done():
            reader.cancel()
        close_task = asyncio.create_task(transport.close(), name="jarvis-live-sideband-transport-close")
        done, pending = await asyncio.wait({close_task}, timeout=self._cleanup_timeout)
        if pending:
            close_task.cancel()
            self._cleanups.add(close_task)
            close_task.add_done_callback(self._cleanup_done)
        elif done:
            self._cleanup_done(close_task)
        done, pending = await asyncio.wait({reader}, timeout=self._cleanup_timeout)
        if pending:
            reader.cancel()
            self._cleanups.add(reader)
            reader.add_done_callback(self._cleanup_done)
        elif done:
            self._cleanup_done(reader)
        if sender is not None:
            done, pending = await asyncio.wait({sender}, timeout=self._cleanup_timeout)
            if pending:
                sender.cancel()
                self._cleanups.add(sender)
                sender.add_done_callback(self._cleanup_done)
            elif done:
                self._cleanup_done(sender)

    @staticmethod
    async def _read_receipt(transport: LiveSidebandTransport, provider_id: str,
                            ready: asyncio.Event,
                            on_receipt: Callable[[LiveTerminalReceipt], Awaitable[None]]) -> LiveTerminalReceipt:
        ready.set()
        while True:
            value = await transport.receive_json()
            if value is None:
                raise EOFError("Live sideband ended without session.closed")
            kind = value.get("type")
            if not isinstance(kind, str):
                raise ValueError("invalid Live sideband event type")
            if kind != "session.closed":
                continue
            session = value.get("session")
            usage = value.get("usage")
            reason = value.get("reason")
            if not isinstance(session, dict) or not isinstance(usage, dict):
                raise ValueError("invalid session.closed payload")
            closed_id = live_id(session.get("id"), "closed provider_session_id")
            if closed_id != provider_id:
                raise ValueError("session.closed identity mismatch")
            if not isinstance(reason, str) or reason not in LIVE_CLOSE_REASONS:
                raise ValueError("invalid session.closed reason")
            seconds = usage.get("seconds")
            duration = live_seconds(seconds, "provider_usage_seconds")
            assert duration is not None and math.isfinite(duration)
            receipt = LiveTerminalReceipt(closed_id, reason, duration)
            await on_receipt(receipt)
            return receipt

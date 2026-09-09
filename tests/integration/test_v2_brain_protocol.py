from __future__ import annotations

import asyncio
import socket
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import aiohttp
import pytest

from jarvis.core.brain_service import BRAIN_SPEECH_REQUESTED, BRAIN_TURN_ACCEPTED
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.v2 import (
    PROTOCOL_VERSION,
    BrainEvent,
    BrainEventKind,
    BrainTurnInput,
    BrainTurnResult,
    ProtocolEnvelope,
    SpeechKind,
    SpeechRequest,
)
from jarvis.protocol.client import LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer

TOKEN = "z" * 48
BRAIN_TURNS_PATH = "/v1/conversations/{conversation_id}/brain-turns"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass(slots=True)
class SlowSpeakingBackend:
    """Backend cerveau factice qui ne rend la main que sur ordre du test.

    Sert la vérification centrale de la spec section 4 : l'ingress doit répondre
    alors que le modèle fort n'a pas commencé son travail.
    """

    release: asyncio.Event = field(default_factory=asyncio.Event)
    started: asyncio.Event = field(default_factory=asyncio.Event)
    calls: list[str] = field(default_factory=list)

    async def run_turn(self, turn: BrainTurnInput, state, emit) -> BrainTurnResult:
        self.calls.append(turn.correlation_id)
        self.started.set()
        await self.release.wait()
        await emit.emit(
            BrainEvent(
                kind=BrainEventKind.SPEECH,
                conversation_id=turn.conversation_id,
                correlation_id=turn.correlation_id,
                work_id="work-1",
                speech=SpeechRequest(
                    conversation_id=turn.conversation_id,
                    text="Trois messages attendent une réponse.",
                    kind=SpeechKind.RESULT,
                    work_id="work-1",
                ),
            )
        )
        return BrainTurnResult(correlation_id=turn.correlation_id, public_summary="Trois messages attendent une réponse.")


@asynccontextmanager
async def protocol_stack(tmp_path, *, backend=None):
    """Monter Core + serveur loopback + client, et tout démonter proprement."""

    port = free_port()
    core = JarvisCoreApplication(data_root=tmp_path, brain_backend=backend)
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
    await server.start()
    client = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
    try:
        yield core, client, port
    finally:
        await client.close()
        await server.stop()
        await core.stop()


def auth_headers(*, token: str = TOKEN, protocol_version: int | str = PROTOCOL_VERSION) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Jarvis-Protocol": str(protocol_version)}


async def raw_post(port: int, path: str, payload, *, headers: dict[str, str] | None = None) -> tuple[int, dict]:
    """Poster sans passer par le client, pour observer le code de statut exact."""

    async with aiohttp.ClientSession() as session:
        async with session.post(f"http://127.0.0.1:{port}{path}", json=payload, headers=headers or auth_headers()) as response:
            return response.status, await response.json()


async def wait_for(condition, *, timeout: float = 5.0) -> None:
    async def loop() -> None:
        while not condition():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(loop(), timeout=timeout)


# --- aller-retour ------------------------------------------------------------


async def test_brain_turn_roundtrip_returns_before_the_slow_backend_finishes(tmp_path):
    backend = SlowSpeakingBackend()
    async with protocol_stack(tmp_path, backend=backend) as (core, client, _port):
        conversation = await client.create_conversation()

        acceptance = await client.submit_brain_turn(
            conversation["id"],
            content="Regarde les mails de Paul.",
            correlation_id="corr-1",
            provider_item_id="item_abc",
        )

        # Exigence centrale de la spec section 4 : la réponse est rendue alors
        # que le tour est encore en vol, le backend restant bloqué sur `release`.
        assert core.brain.active_turn_count == 1
        assert acceptance["duplicate"] is False
        assert acceptance["correlation_id"] == "corr-1"
        assert acceptance["conversation_id"] == conversation["id"]
        assert acceptance["provider_item_id"] == "item_abc"
        assert acceptance["revision"] == 1
        assert acceptance["turn_id"]

        turns = await core.state.list_turns(conversation["id"], limit=10)
        assert [t.content for t in turns] == ["Regarde les mails de Paul."]
        assert turns[0].metadata["authoritative"] is True
        assert turns[0].metadata["final"] is True

        backend.release.set()
        await wait_for(lambda: core.brain.active_turn_count == 0)


async def test_brain_turn_accepts_a_minimal_body_without_provider_item_id(tmp_path):
    """Décision 24 : seul `correlation_id` est obligatoire."""

    backend = SlowSpeakingBackend()
    async with protocol_stack(tmp_path, backend=backend) as (core, client, port):
        conversation = await client.create_conversation()

        status, body = await raw_post(
            port,
            BRAIN_TURNS_PATH.format(conversation_id=conversation["id"]),
            {"content": "Bonjour.", "correlation_id": "corr-min"},
        )

        assert status == 202
        assert body["provider_item_id"] is None
        assert body["duplicate"] is False

        backend.release.set()
        await wait_for(lambda: core.brain.active_turn_count == 0)


# --- rejeu -------------------------------------------------------------------


async def test_duplicate_brain_turn_persists_and_dispatches_once(tmp_path):
    backend = SlowSpeakingBackend()
    async with protocol_stack(tmp_path, backend=backend) as (core, client, port):
        conversation = await client.create_conversation()
        path = BRAIN_TURNS_PATH.format(conversation_id=conversation["id"])
        payload = {"content": "Regarde les mails de Paul.", "correlation_id": "corr-replay"}

        first_status, first = await raw_post(port, path, payload)
        second_status, second = await raw_post(port, path, payload)

        assert first_status == 202
        assert first["duplicate"] is False
        # Un rejeu n'est pas un conflit : il rend l'accusé d'origine.
        assert second_status == 200
        assert second["duplicate"] is True
        assert second["turn_id"] == first["turn_id"]
        assert second["revision"] == first["revision"]

        turns = await core.state.list_turns(conversation["id"], limit=10)
        assert len(turns) == 1

        await asyncio.wait_for(backend.started.wait(), timeout=5)
        backend.release.set()
        await wait_for(lambda: core.brain.active_turn_count == 0)
        assert backend.calls == ["corr-replay"]


# --- erreurs -----------------------------------------------------------------


async def test_unknown_conversation_is_rejected_with_404(tmp_path):
    async with protocol_stack(tmp_path, backend=SlowSpeakingBackend()) as (core, _client, port):
        status, body = await raw_post(
            port,
            BRAIN_TURNS_PATH.format(conversation_id="conversation-inconnue"),
            {"content": "Bonjour.", "correlation_id": "corr-404"},
        )

        assert status == 404
        assert body["error"]["code"] == "not_found"
        assert core.brain.active_turn_count == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"correlation_id": "corr-bad"},
        {"content": "   ", "correlation_id": "corr-bad"},
        {"content": "Bonjour."},
        {"content": "Bonjour.", "correlation_id": "   "},
        {"content": "Bonjour.", "correlation_id": "corr-bad", "source": "telepathie"},
        {"content": "Bonjour.", "correlation_id": "corr-bad", "provider_item_id": 12},
        ["pas", "un", "objet"],
    ],
)
async def test_malformed_brain_turn_body_is_rejected_with_400(tmp_path, payload):
    async with protocol_stack(tmp_path, backend=SlowSpeakingBackend()) as (core, client, port):
        conversation = await client.create_conversation()

        status, body = await raw_post(port, BRAIN_TURNS_PATH.format(conversation_id=conversation["id"]), payload)

        assert status == 400
        assert body["error"]["code"] == "invalid_request"
        # Un corps invalide ne persiste ni ne dépêche quoi que ce soit.
        assert not await core.state.list_turns(conversation["id"], limit=10)
        assert core.brain.active_turn_count == 0


async def test_brain_turn_is_refused_with_503_while_core_stops(tmp_path):
    async with protocol_stack(tmp_path, backend=SlowSpeakingBackend()) as (core, client, port):
        conversation = await client.create_conversation()
        await core.brain.stop()

        status, body = await raw_post(
            port,
            BRAIN_TURNS_PATH.format(conversation_id=conversation["id"]),
            {"content": "Bonjour.", "correlation_id": "corr-503"},
        )

        assert status == 503
        assert body["error"]["code"] == "core_stopping"
        assert not await core.state.list_turns(conversation["id"], limit=10)


# --- authentification et version ---------------------------------------------


async def test_brain_turn_requires_the_local_credential(tmp_path):
    async with protocol_stack(tmp_path, backend=SlowSpeakingBackend()) as (_core, client, port):
        conversation = await client.create_conversation()

        status, body = await raw_post(
            port,
            BRAIN_TURNS_PATH.format(conversation_id=conversation["id"]),
            {"content": "Bonjour.", "correlation_id": "corr-401"},
            headers=auth_headers(token="w" * 48),
        )

        assert status == 401
        assert body["error"]["code"] == "unauthorized"


async def test_brain_turn_rejects_an_incompatible_protocol_version(tmp_path):
    async with protocol_stack(tmp_path, backend=SlowSpeakingBackend()) as (_core, client, port):
        conversation = await client.create_conversation()

        status, body = await raw_post(
            port,
            BRAIN_TURNS_PATH.format(conversation_id=conversation["id"]),
            {"content": "Bonjour.", "correlation_id": "corr-426"},
            headers=auth_headers(protocol_version=PROTOCOL_VERSION + 1),
        )

        assert status == 426
        assert body["error"]["code"] == "protocol_mismatch"


# --- egress ------------------------------------------------------------------


async def test_existing_events_stream_delivers_brain_speech_requested(tmp_path):
    """Décision 05 : aucun second bus, la parole cerveau sort par `/v1/events`."""

    backend = SlowSpeakingBackend()
    async with protocol_stack(tmp_path, backend=backend) as (core, client, _port):
        conversation = await client.create_conversation()
        received: list[ProtocolEnvelope] = []
        baseline = core.events.subscriber_count

        async def pump() -> None:
            stream = client.events()
            try:
                async for envelope in stream:
                    received.append(envelope)
                    if envelope.message_type == BRAIN_SPEECH_REQUESTED:
                        return
            finally:
                await stream.aclose()

        pump_task = asyncio.create_task(pump())
        try:
            await wait_for(lambda: core.events.subscriber_count > baseline)
            await client.submit_brain_turn(conversation["id"], content="Regarde les mails de Paul.", correlation_id="corr-events")
            await asyncio.wait_for(backend.started.wait(), timeout=5)
            backend.release.set()
            await asyncio.wait_for(pump_task, timeout=5)
        finally:
            pump_task.cancel()

        by_type = {envelope.message_type: envelope for envelope in received}
        assert BRAIN_TURN_ACCEPTED in by_type
        speech = by_type[BRAIN_SPEECH_REQUESTED]
        assert speech.conversation_id == conversation["id"]
        assert speech.correlation_id == "corr-events"
        assert speech.payload["text"] == "Trois messages attendent une réponse."
        assert speech.payload["kind"] == "result"

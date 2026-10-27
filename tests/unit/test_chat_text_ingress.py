"""Tour écrit au Chat sur la route `brain-turns` de Core (`docs/chat.md` › *Sending text*, Slice 03).

Core réel (`JarvisCoreApplication`, SQLite sous `tmp_path`) derrière le vrai
`LocalProtocolServer`, aucun processus Voice : l'état du canal vocal est nourri
par des rapports passés directement au `VoiceChannelService`, comme Voice le
ferait. Le cerveau est un backend factice ; aucun CLI réel.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import aiohttp
import pytest
from aiohttp.test_utils import TestServer

from jarvis.adapters.control_center_brain import _turn_context, _turn_conversation
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.v2 import (
    BrainEvent, BrainEventKind, BrainRunStatus, BrainTurnInput, BrainTurnResult, BrainTurnSource,
)
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime.control_center import BRIEF_TEXT_CHANNEL, build_agent_brief
from tests.fakes.conversation_events import wait_emitter_settled

TOKEN = "t" * 48


class RecordingBackend:
    """Backend `ContextAwareBrainBackend` : garde le contexte que l'adaptateur du Control Center enverrait."""

    def __init__(self) -> None:
        self.calls: list[BrainTurnInput] = []
        self.contexts: list[dict] = []

    async def run_turn(self, turn, state, emit):  # pragma: no cover - Core prefers the context-aware path
        self.calls.append(turn)
        return BrainTurnResult(correlation_id=turn.correlation_id, status=BrainRunStatus.COMPLETED)

    async def run_turn_with_context(self, turn, context, emit):
        self.calls.append(turn)
        self.contexts.append(_turn_context(turn, context.state, context.work, context.interruptions,
                                           context.pending_replies, board=context.board,
                                           session_context=context.session_context,
                                           prefab_events=context.prefab_events, presentation=context.presentation,
                                           memory=context.memory))
        # Le cerveau délègue : un travail de fond ouvert puis conclu, comme un sous-agent.
        work_id = "agent:" + turn.correlation_id
        await emit.emit(BrainEvent(kind=BrainEventKind.ACCEPTED, conversation_id=turn.conversation_id,
                                   correlation_id=turn.correlation_id, work_id=work_id,
                                   public_summary="Je lance un sous-agent."))
        await emit.emit(BrainEvent(kind=BrainEventKind.COMPLETED, conversation_id=turn.conversation_id,
                                   correlation_id=turn.correlation_id, work_id=work_id,
                                   public_summary="Le sous-agent a fini."))
        return BrainTurnResult(correlation_id=turn.correlation_id, public_summary="Voici la réponse.")


class Stack:
    def __init__(self, core: JarvisCoreApplication, backend: RecordingBackend, base_url: str,
                 http: aiohttp.ClientSession) -> None:
        self.core, self.backend, self.base_url, self.http = core, backend, base_url, http

    async def foreground(self) -> str:
        return (await self.core.sessions.current()).binding.conversation_id

    async def send(self, conversation_id: str, content: str = "Bonjour", *, request_id: str | None = None,
                   **extra) -> tuple[int, dict, str]:
        correlation_id = "chat:" + (request_id or str(uuid.uuid4()))
        body = {"content": content, "correlation_id": correlation_id, "source": "text", "addressing": "addressed",
                **extra}
        async with self.http.post(f"{self.base_url}/v1/conversations/{conversation_id}/brain-turns", json=body,
                                  headers={"Authorization": f"Bearer {TOKEN}"}) as response:
            return response.status, await response.json(), correlation_id

    async def settle(self) -> None:
        await asyncio.wait_for(asyncio.gather(*tuple(self.core.brain._tasks.values()), return_exceptions=True), 5)
        await wait_emitter_settled(self.core.conversation_event_emitter)

    async def events(self, conversation_id: str):
        page = await self.core.conversation_events.list_conversation_events(conversation_id, limit=500)
        return [item.event for item in page.events]


def voice(state: str, seq: int = 1) -> dict:
    return {"schema_version": 1, "voice_incarnation_id": "voice-test", "seq": seq, "lifecycle_state": state,
            "conversation_id": None, "ack": None}


def voice_absent(core: JarvisCoreApplication) -> None:
    core.voice_channel.started_at -= 10.0  # après la période de grâce, sans rapport : `absent`


async def open_stack(data_root, backend: RecordingBackend | None = None):
    backend = backend or RecordingBackend()
    core = JarvisCoreApplication(data_root=data_root, brain_backend=backend)
    await core.start()
    server = TestServer(LocalProtocolServer(core, host="127.0.0.1", port=0, token=TOKEN)._app())
    await server.start_server()
    http = aiohttp.ClientSession()
    return Stack(core, backend, f"http://127.0.0.1:{server.port}", http), server


async def close_stack(stack: Stack, server: TestServer) -> None:
    await stack.http.close()
    await server.close()
    await stack.core.stop()


@pytest.fixture
async def stack(tmp_path):
    opened, server = await open_stack(tmp_path)
    try:
        yield opened
    finally:
        await close_stack(opened, server)


async def test_text_turn_reaches_foreground_binding_brain(stack):
    voice_absent(stack.core)
    conversation_id = await stack.foreground()
    status, body, correlation_id = await stack.send(conversation_id, "Quelle heure est-il ?")
    assert status == 202 and body["duplicate"] is False
    assert body["correlation_id"] == correlation_id and body["turn_id"].startswith("brain-turn-")
    await stack.settle()
    [turn] = stack.backend.calls
    assert (turn.conversation_id, turn.text, turn.source) == (conversation_id, "Quelle heure est-il ?",
                                                              BrainTurnSource.TEXT)
    record = await stack.core.brain.admitted_turn(conversation_id, correlation_id)
    assert record.metadata["source"] == "text" and "attachments" not in record.metadata


async def test_not_foreground_409(stack):
    voice_absent(stack.core)
    other = (await stack.core.conversations.create()).id
    status, body, _ = await stack.send(other)
    assert status == 409 and body["error"]["code"] == "chat_conversation_not_foreground"
    assert body["error"]["current_conversation_id"] == await stack.foreground()
    assert await stack.core.conversations.list_turns(other) == ()
    assert stack.backend.calls == []


@pytest.mark.parametrize("reason", ["voice_active", "voice_connecting", "voice_error", "voice_switching",
                                    "voice_unknown"])
async def test_locked_by_voice_409_each_reason(stack, reason):
    channel = stack.core.voice_channel
    if reason == "voice_unknown":
        pass  # Core vient de démarrer, aucun rapport : 5 s `unknown`
    elif reason == "voice_switching":
        channel.report(voice("active"))
        assert channel.disable({"client_request_id": str(uuid.uuid4())})[0] == 202
    else:
        channel.report(voice(reason.removeprefix("voice_")))
    assert channel.write_gate() == reason
    conversation_id = await stack.foreground()
    status, body, _ = await stack.send(conversation_id, "Texte refusé")
    assert status == 409 and body["error"] == {"code": "chat_input_locked", "reason": reason,
                                               "message": "the voice channel holds the conversation"}
    assert "Texte refusé" not in json.dumps(body)
    assert await stack.core.conversations.list_turns(conversation_id) == ()
    assert stack.backend.calls == []


@pytest.mark.parametrize("state", ["absent", "background"])
async def test_voice_absent_allows(stack, state):
    if state == "absent":
        voice_absent(stack.core)
    else:
        stack.core.voice_channel.report(voice("background"))
    status, body, _ = await stack.send(await stack.foreground())
    assert status == 202 and body["duplicate"] is False


@pytest.mark.parametrize("product_state", ["off", "sleep"])
async def test_chat_in_off_or_sleep_reaches_the_brain_without_touching_voice(stack, product_state):
    """Cycle de vie de la voix (`docs/voice-lifecycle.md`, Slice 05 v1-2) : Off = aucun processus Voice (`absent`),
    Sleep = Voice au fond (`background`). Un envoi au Chat atteint le cerveau, ne change ni l'état ni la révision du
    canal vocal, ne crée aucune demande, et la réponse d'un tour écrit n'est jamais parlée."""

    channel = stack.core.voice_channel
    if product_state == "off":
        voice_absent(stack.core)
    else:
        channel.report(voice("background"))
    before = channel.snapshot()
    conversation_id = await stack.foreground()
    status, _body, correlation_id = await stack.send(conversation_id, "Un message écrit")
    assert status == 202
    await stack.settle()
    assert [turn.text for turn in stack.backend.calls] == ["Un message écrit"]
    after = channel.snapshot()
    assert after["voice"]["state"] == before["voice"]["state"] == ("absent" if product_state == "off" else "background")
    assert after["voice"]["revision"] == before["voice"]["revision"] and after["voice"]["request"] is None
    assert after["chat_writable"] is True
    kinds = [event.event_type for event in await stack.events(conversation_id)]
    assert T.BRAIN_SPEECH_REQUESTED not in kinds, "un tour écrit n'est jamais parlé (speech_withheld_text_channel)"


async def test_replay_after_lock_returns_duplicate_200(tmp_path):
    opened, server = await open_stack(tmp_path)
    request_id = str(uuid.uuid4())
    try:
        voice_absent(opened.core)
        conversation_id = await opened.foreground()
        first, accepted, _ = await opened.send(conversation_id, "Un message", request_id=request_id)
        assert first == 202
        await opened.settle()
        opened.core.voice_channel.report(voice("active"))  # la voix se réveille après l'envoi
        status, body, _ = await opened.send(conversation_id, "Un message", request_id=request_id)
        assert (status, body["duplicate"], body["turn_id"]) == (200, True, accepted["turn_id"])
    finally:
        await close_stack(opened, server)
    # Core redémarré : plus de doublon mémoire, voix `unknown` (verrouillée) ; le rejeu durable passe avant.
    opened, server = await open_stack(tmp_path)
    try:
        assert opened.core.voice_channel.write_gate() == "voice_unknown"
        status, body, _ = await opened.send(conversation_id, "Un message", request_id=request_id)
        assert (status, body["duplicate"], body["turn_id"]) == (200, True, accepted["turn_id"])
        assert opened.backend.calls == []  # jamais redépêché
    finally:
        await close_stack(opened, server)


async def test_same_request_other_text_409_conflict(stack):
    voice_absent(stack.core)
    conversation_id = await stack.foreground()
    request_id = str(uuid.uuid4())
    assert (await stack.send(conversation_id, "Premier texte", request_id=request_id))[0] == 202
    status, body, _ = await stack.send(conversation_id, "Autre texte", request_id=request_id)
    assert status == 409 and body["error"]["code"] == "chat_request_conflict"
    assert "Autre texte" not in json.dumps(body) and "Premier texte" not in json.dumps(body)
    # Même course, envois concurrents : un seul tour, le second est un doublon ou un conflit, jamais un second tour.
    racing = str(uuid.uuid4())
    same = await asyncio.gather(stack.send(conversation_id, "Pareil", request_id=racing),
                                stack.send(conversation_id, "Pareil", request_id=racing))
    assert sorted(status for status, _, _ in same) == [200, 202]
    racing = str(uuid.uuid4())
    other = await asyncio.gather(stack.send(conversation_id, "Version A", request_id=racing),
                                 stack.send(conversation_id, "Version B", request_id=racing))
    assert sorted(status for status, _, _ in other) == [202, 409]
    await stack.settle()
    assert len(stack.backend.calls) == 3


async def test_text_too_long_400(stack):
    voice_absent(stack.core)
    conversation_id = await stack.foreground()
    status, body, _ = await stack.send(conversation_id, "x" * 8193)
    assert status == 400 and body["error"]["code"] == "chat_text_too_long"
    assert (await stack.send(conversation_id, "x" * 8192))[0] == 202
    # Pièces jointes (Slice 07) : un id inconnu est 404, une forme fausse 400 ; rien n'est écrit.
    status, body, _ = await stack.send(conversation_id, attachments=["jart_" + "a" * 32])
    assert status == 404 and body["error"]["code"] == "attachment_not_found"
    for attachments in ("jart_x", {"id": 1}):
        status, body, _ = await stack.send(conversation_id, attachments=attachments)
        assert status == 400 and body["error"]["code"] == "invalid_request"
    assert (await stack.send(conversation_id, attachments=[]))[0] == 202
    await stack.settle()
    assert len(stack.backend.calls) == 2


async def test_single_user_event_per_turn(stack):
    voice_absent(stack.core)
    conversation_id = await stack.foreground()
    request_id = str(uuid.uuid4())
    _, _, correlation_id = await stack.send(conversation_id, "Résume le dossier", request_id=request_id)
    await stack.send(conversation_id, "Résume le dossier", request_id=request_id)  # renvoi du navigateur
    await stack.settle()
    events = [event for event in await stack.events(conversation_id) if event.correlation_id == correlation_id]
    users = [event for event in events if event.event_type is T.USER_TRANSCRIPT_ACCEPTED]
    assert len(users) == 1 and dict(users[0].attributes)["source"] == "text"
    assert users[0].content == "Résume le dossier"
    messages = [event.content for event in events if event.event_type is T.BRAIN_MESSAGE_PUBLISHED]
    assert "Voici la réponse." in messages
    assert [event for event in events if event.event_type is T.BRAIN_SPEECH_REQUESTED] == []


async def test_delegation_available(stack):
    voice_absent(stack.core)
    conversation_id = await stack.foreground()
    voice_turn = await stack.core.brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Lance l'analyse",
                                                              correlation_id="realtime:v1"))
    await stack.settle()
    status, _, correlation_id = await stack.send(conversation_id, "Lance l'analyse")
    assert status == 202 and voice_turn.duplicate is False
    await stack.settle()
    spoken, written = stack.backend.contexts
    # Même cerveau, même contexte (Board, Session, mémoire, état) : `channel` en plus, rien d'autre.
    assert written.pop("channel") == "text" and "channel" not in spoken
    assert {key for key in written} == {key for key in spoken}
    assert written["board"] == spoken["board"] and written.get("session_context") == spoken.get("session_context")
    # Même identifiants pour les sous-agents du tour (`conversation` de `/api/agent/ask`).
    text_turn = stack.backend.calls[1]
    assert set(_turn_conversation(text_turn, "w")) == set(_turn_conversation(stack.backend.calls[0], "w"))
    # Le brief n'ajoute que la ligne du canal.
    brief = build_agent_brief({**written, "channel": "text"}, "Lance l'analyse")
    assert BRIEF_TEXT_CHANNEL in brief and BRIEF_TEXT_CHANNEL not in build_agent_brief(written, "Lance l'analyse")
    assert brief.replace(BRIEF_TEXT_CHANNEL + "\n", "") == build_agent_brief(written, "Lance l'analyse")
    # Le travail délégué par le tour écrit est suivi comme celui d'un tour vocal, et rien n'est dit.
    events = [event for event in await stack.events(conversation_id) if event.correlation_id == correlation_id]
    types = {event.event_type for event in events}
    assert {T.BRAIN_WORK_STARTED, T.BRAIN_WORK_COMPLETED, T.BRAIN_MESSAGE_PUBLISHED} <= types
    assert T.BRAIN_SPEECH_REQUESTED not in types


async def test_no_loop_iteration_between_write_gate_and_submit(stack, monkeypatch):
    """Étape 4 linéarisée : entre la lecture du verrou et `submit`, aucun `await` ne rend la main à la boucle.

    Le faux `write_gate` laisse passer mais programme, au prochain tour de boucle,
    le verrouillage (un réveil vocal). `submit` doit entrer avant qu'il ne s'exécute.
    """
    voice_absent(stack.core)
    loop = asyncio.get_running_loop()
    locked: list[bool] = []
    seen_at_submit: list[bool] = []
    real_gate, real_submit = stack.core.voice_channel.write_gate, stack.core.brain.submit

    def gate():
        reason = real_gate()
        loop.call_soon(locked.append, True)
        return reason

    async def submit(turn):
        seen_at_submit.append(bool(locked))
        return await real_submit(turn)

    monkeypatch.setattr(stack.core.voice_channel, "write_gate", gate)
    monkeypatch.setattr(stack.core.brain, "submit", submit)
    status, _, _ = await stack.send(await stack.foreground())
    assert status == 202
    assert seen_at_submit == [False]

"""Chat unifié et dépôt sur le Board, de bout en bout (handoff jarvis-unified-chat-and-board-drop, Slice 09).

Contrat : `docs/chat.md` (tout), `tasks/jarvis-unified-chat-and-board-drop/docs/06-resolved-architecture.md`,
« Contrat Slice 00 » de `slices/09-integration-and-security-gates/SLICE.md` : un test par scénario obligatoire.

Deux mondes, jamais le Jarvis de l'utilisateur, jamais `./data`, jamais les ports 17653/17654 :

- **Suite par défaut** : vrai `JarvisCoreApplication` (SQLite et payloads sous `tmp_path`) derrière le vrai
  `LocalProtocolServer` (port éphémère), vrai `ControlCenter` (relais `/api/chat*`, `/api/boards/drop*`,
  `/api/conversations/events`) devant. Le processus Voice est simulé par le client typé
  (`LocalCoreClient.voice_channel_report`), comme `PersistentVoiceRuntime.send_voice_channel_report`. Le
  cerveau est un backend scripté (`ScriptedBrain`) : ces scénarios ne portent pas sur le modèle. Ses fins
  de sous-agent passent par `next_notices`, la voie de production (`_brain_notice_loop` → `announce_notice`).
- **Catégorie 2 (vrai modèle, opt-in)** : `JARVIS_LIVE_CLAUDE=1` (convention du dépôt, voir
  `tests/integration/test_live_brain_full_stack.py` ; aucun marqueur `category2` n'existe dans Jarvis,
  `tasks/jarvis-category2-test-lab/slices/00-project-manager/READINESS.md` point 6). `RealStack` lance
  `python -m jarvis core` et `python -m jarvis control-center` en sous-processus, racine de données,
  runtime et jeton propres, ports éphémères, vrai CLI `claude`.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import uuid
import zlib

import aiohttp
from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.adapters.control_center_brain import _turn_context
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.chat_projection import is_chat_event, project_chat
from jarvis.domain.conversation_event_query import decode_event_page
from jarvis.domain.conversation_events import ConversationEventType as T, encode_conversation_event
from jarvis.domain.v2 import (
    BrainEvent, BrainEventKind, BrainRunStatus, BrainTurnResult, SpeechKind, SpeechRequest,
)
from jarvis.protocol.client import LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime import chat_relay
from jarvis.runtime.attachments_brief import BRIEF_ATTACHMENTS_HEADER, with_agent_readability
from jarvis.runtime.control_center import BRIEF_TEXT_CHANNEL, ControlCenter, build_agent_brief
from jarvis.runtime.conversation_event_view import ConversationEventView, CoreConversationEventReader
from jarvis.runtime.core_sessions import CoreSessionTransport
from jarvis.runtime.journal import RuntimeJournal
from tests.fakes.conversation_events import wait_emitter_settled
from tests.unit.test_board_drop import NoOutboundNetwork
from tests.unit.test_control_center_chat_model_js import run_node

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "e" * 48
BOUNDARY = "jarvis-chat-e2e-boundary"
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 8
PDF = b"%PDF-1.4\n" + b"1 0 obj << >> endobj\n" * 50 + b"%%EOF\n"
ZIP = b"PK\x03\x04" + b"\x00" * 3000
EVENTS = "/api/conversations/events"
LIVE_ONLY = pytest.mark.skipif(os.getenv("JARVIS_LIVE_CLAUDE") != "1",
                               reason="Catégorie 2 : vrai CLI Claude, requires JARVIS_LIVE_CLAUDE=1")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assert port not in (17653, 17654)
    return port


def multipart(upload_id: str, filename: str, content_type: str, data: bytes) -> bytes:
    return (f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"client_upload_id\"\r\n\r\n{upload_id}\r\n"
            f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {content_type}\r\n\r\n").encode("utf-8") + data + f"\r\n--{BOUNDARY}--\r\n".encode()


MULTIPART = {"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"}


# ---------------------------------------------------------------------------------------------- cerveau scripté


class ScriptedBrain:
    """Backend `ContextAwareBrainBackend` scripté, avec la voie des relais spontanés de production.

    Mots du tour : « sous-agent » ouvre un travail de fond (jamais fermé par le tour) ; « parle » émet un
    accusé, une question et un résultat parlés ; « échoue » lève (panne backend). `hold` retient le tour
    en vol. `finish_subagent` sert une notice à `next_notices`, comme le Control Center à la fin d'un
    sous-agent du CLI.
    """

    def __init__(self) -> None:
        self.turns: list = []
        self.contexts: list[dict] = []
        self.hold: asyncio.Event | None = None
        self.started = asyncio.Event()
        self._notices: asyncio.Queue = asyncio.Queue()
        self.subagents = 0

    async def run_turn(self, turn, state, emit):  # pragma: no cover - Core prend la voie avec contexte
        raise AssertionError("Core must call run_turn_with_context")

    async def run_turn_with_context(self, turn, context, emit):
        self.turns.append(turn)
        self.contexts.append(_turn_context(turn, context.state, context.work, context.interruptions,
                                           context.pending_replies, board=context.board,
                                           session_context=context.session_context,
                                           prefab_events=context.prefab_events, presentation=context.presentation,
                                           memory=context.memory, attachments=context.attachments))
        self.started.set()
        if "échoue" in turn.text:
            raise RuntimeError("panne du backend scriptée")
        if "sous-agent" in turn.text:
            self.subagents += 1
            await emit.emit(BrainEvent(kind=BrainEventKind.ACCEPTED, conversation_id=turn.conversation_id,
                                       correlation_id=turn.correlation_id, work_id=f"agent:sub-{self.subagents}",
                                       public_summary="Je lance un sous-agent."))
        if "parle" in turn.text:
            for text, kind in (("Je regarde.", SpeechKind.ACK), ("Lequel des deux ?", SpeechKind.QUESTION),
                               ("Le dossier est lu.", SpeechKind.RESULT)):
                await emit.emit(BrainEvent(kind=BrainEventKind.SPEECH, conversation_id=turn.conversation_id,
                                           correlation_id=turn.correlation_id,
                                           speech=SpeechRequest(conversation_id=turn.conversation_id,
                                                                correlation_id=turn.correlation_id, text=text,
                                                                kind=kind)))
        if self.hold is not None:
            await self.hold.wait()
        return BrainTurnResult(correlation_id=turn.correlation_id, status=BrainRunStatus.COMPLETED,
                               public_summary=f"Réponse à : {turn.text}")

    def finish_subagent(self, text: str, *, work_id: str, conversation_id: str) -> None:
        self._notices.put_nowait({"text": text, "kind": "result", "work_id": work_id,
                                  "conversation_id": conversation_id})

    async def next_notices(self):
        return (await self._notices.get(),)


# ---------------------------------------------------------------------------------------------- pile isolée


class ChatStack:
    """Core réel (port fixe, redémarrable) → `LocalProtocolServer` → vrai `ControlCenter` (TestClient).

    `stack.voice(state)` envoie un rapport comme Voice ; `stack.call` parle au Control Center sans
    Origin (comme le serveur MCP local) ; `stack.core_journal()` / `stack.cc_trace()` lisent les deux
    `trace.jsonl` ; `restart_core()` arrête et relance Core sur la même racine et le même port.
    """

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.data_root = tmp_path / "data"
        self.core_runtime = tmp_path / "core-runtime"
        self.cc_runtime = tmp_path / "runtime"
        for path in (self.core_runtime, self.cc_runtime):
            path.mkdir(parents=True, exist_ok=True)
        self.port = free_port()
        self.brain = ScriptedBrain()
        self.incarnation = "voice-" + uuid.uuid4().hex
        self.seq = 0
        self.disable_requests: list[dict] = []

    async def _start_core(self) -> None:
        self.core = JarvisCoreApplication(data_root=self.data_root, brain_backend=self.brain,
                                          diagnostics=RuntimeJournal(self.core_runtime))
        await self.core.start()
        self.server = LocalProtocolServer(self.core, host="127.0.0.1", port=self.port, token=TOKEN)
        await self.server.start()
        self.core_client = LocalCoreClient(host="127.0.0.1", port=self.port, token=TOKEN)

    async def _stop_core(self) -> None:
        await self.core_client.close()
        await self.server.stop()
        await self.core.stop()

    async def __aenter__(self) -> "ChatStack":
        await self._start_core()
        token_file = self.tmp_path / "core.token"
        token_file.write_text(TOKEN, encoding="utf-8")
        self.sessions = CoreSessionTransport(host="127.0.0.1", port=self.port, token_file=token_file)
        view = ConversationEventView(CoreConversationEventReader(host="127.0.0.1", port=self.port,
                                                                 token_file=token_file), journal=None, timeout_s=3.0)
        self.center = ControlCenter(runtime_root=self.cc_runtime, project_root=self.tmp_path,
                                    conversation_event_view=view, sessions=self.sessions)
        view.journal = self.center.journal
        self.center.sessions = self.sessions
        self.cc = TestClient(TestServer(self.center._app))
        await self.cc.start_server()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.cc.close()
        await self.center.conversation_event_view.aclose()
        await self.sessions.close()
        await self._stop_core()

    async def restart_core(self) -> None:
        await self._stop_core()
        self.brain = ScriptedBrain()
        await self._start_core()

    # -- Voice simulé ---------------------------------------------------------------------------

    async def voice(self, state: str, *, ack: dict | None = None) -> dict:
        self.seq += 1
        answer = await self.core_client.voice_channel_report(
            {"schema_version": 1, "voice_incarnation_id": self.incarnation, "seq": self.seq,
             "lifecycle_state": state, "conversation_id": None, "ack": ack}, timeout_s=2.0)
        if answer.get("disable_request"):
            self.disable_requests.append(answer["disable_request"])
        return answer

    async def voice_obeys_disable(self) -> None:
        """Ce que fait `_report_voice_channel` : prendre la demande, `mute()`, rapporter `background` + ack."""

        answer = await self.voice("active")
        request = answer["disable_request"]
        assert request is not None, answer
        await self.voice("background", ack={"request_id": request["request_id"], "result": "accepted", "code": None})

    def voice_absent(self) -> None:
        self.core.voice_channel.started_at -= 10.0  # période de grâce passée, aucun rapport : `absent`

    # -- Control Center ---------------------------------------------------------------------------

    async def call(self, method: str, path: str, **kwargs) -> tuple[int, object, str]:
        response = await self.cc.request(method, path, **kwargs)
        text = await response.text()
        try:
            body = json.loads(text)
        except ValueError:
            body = None
        return response.status, body, text

    async def state(self) -> dict:
        status, body, text = await self.call("GET", "/api/chat/state")
        assert status == 200, text
        return body

    async def send(self, conversation_id: str, content: str, *, request_id: str | None = None,
                   attachments: list[str] | None = None) -> tuple[int, dict, str]:
        request_id = request_id or str(uuid.uuid4())
        body = {"conversation_id": conversation_id, "client_request_id": request_id, "content": content}
        if attachments is not None:
            body["attachments"] = attachments
        status, answer, _ = await self.call("POST", "/api/chat/turns", json=body)
        return status, answer, "chat:" + request_id

    async def upload(self, filename: str, data: bytes, content_type: str = "application/octet-stream") -> dict:
        status, body, text = await self.call("POST", "/api/chat/uploads", headers=MULTIPART,
                                             data=multipart(str(uuid.uuid4()), filename, content_type, data))
        assert status == 201, text
        return body

    async def read_chat(self, conversation_id: str, after: int) -> tuple[list[dict], int]:
        """Une lecture courte du Chat (`projection=chat`, `limit=500`, `next_cursor` suivi tant que `has_more`)."""

        rows = []
        while True:
            status, page, text = await self.call("GET", EVENTS, params={
                "conversation_id": conversation_id, "projection": "chat", "limit": "500",
                "after_sequence": str(after)})
            assert status == 200, text
            rows += page["events"]
            after = page["next_cursor"]
            if not page["has_more"]:
                return rows, after

    # -- Core ---------------------------------------------------------------------------------------

    async def foreground(self) -> str:
        return (await self.core.sessions.current()).binding.conversation_id

    async def voice_turn(self, conversation_id: str, text: str, *, addressing: str = "addressed") -> str:
        correlation_id = "realtime:" + uuid.uuid4().hex
        async with aiohttp.ClientSession() as http:
            async with http.post(f"http://127.0.0.1:{self.port}/v1/conversations/{conversation_id}/brain-turns",
                                 json={"content": text, "correlation_id": correlation_id, "source": "realtime",
                                       "addressing": addressing},
                                 headers={"Authorization": f"Bearer {TOKEN}"}) as response:
                assert response.status == 202, await response.text()
        return correlation_id

    async def settle(self) -> None:
        await asyncio.wait_for(asyncio.gather(*tuple(self.core.brain._tasks.values()), return_exceptions=True), 10)
        await wait_emitter_settled(self.core.conversation_event_emitter)

    async def events(self, conversation_id: str) -> list:
        page = await self.core.conversation_events.list_conversation_events(conversation_id, limit=500)
        return [item.event for item in page.events]

    async def all_events(self) -> list:
        page = await self.core.conversation_events.list_conversations(limit=100)
        out = []
        for summary in page.summaries:
            out += await self.events(summary.conversation_id)
        return out

    def core_journal(self) -> list[dict]:
        return _jsonl(self.core_runtime / "trace.jsonl")

    def cc_trace(self) -> list[dict]:
        return _jsonl(self.cc_runtime / "trace.jsonl")


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def until(predicate, timeout: float = 10.0) -> None:  # noqa: ANN001
    deadline = time.monotonic() + timeout
    while not await predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.05)


def decode_rows(rows: list[dict]) -> tuple:
    """Lignes de pages du Chat (dans l'ordre), décodées par le décodeur strict des pages."""

    last = max((row["sequence"] for row in rows), default=0)
    return decode_event_page({"schema_version": 1, "events": rows, "next_cursor": last, "has_more": False,
                              "skipped_rows": 0}).events


def of(events, kind: T, correlation_id: str | None = None) -> list:
    return [e for e in events if e.event_type is kind and (correlation_id is None or e.correlation_id == correlation_id)]


@pytest.fixture
async def stack(tmp_path):
    async with ChatStack(tmp_path) as opened:
        yield opened


async def bind_agent(stack: ChatStack, agent_session_id: str) -> None:
    """Ce que le Control Center rapporte quand son CLI a une session (`POST /v1/sessions/bindings/report`)."""

    binding = (await stack.core.sessions.current()).binding
    await stack.core.sessions.record_agent(binding.jarvis_session_id, binding.board_id, agent_cli="claude",
                                           agent_session_id=agent_session_id)


# ============================================================================================== 14 scénarios


async def test_voice_active_chat_reads_but_refuses(stack):
    conversation_id = await stack.foreground()
    await stack.voice("active")
    spoken = await stack.voice_turn(conversation_id, "Jarvis, quelle heure est-il ?")
    await stack.settle()

    state = await stack.state()
    assert (state["conversation_id"], state["voice"]["state"]) == (conversation_id, "active")
    assert (state["chat_writable"], state["locked_reason"]) == (False, "voice_active")
    rows, _ = await stack.read_chat(conversation_id, 0)  # lecture permise : l'historique vocal est là
    items = project_chat(decode_rows(rows),
                         conversation_id=conversation_id)
    assert [(i.role, i.correlation_id) for i in items] == [("user", spoken), ("brain", spoken)]

    turns_before = await stack.core.conversations.list_turns(conversation_id)
    status, body, correlation_id = await stack.send(conversation_id, "Écrit pendant la voix")
    assert (status, body["code"], body["reason"]) == (409, "chat_input_locked", "voice_active")
    assert "Écrit pendant la voix" not in json.dumps(body)
    await stack.settle()
    assert await stack.core.conversations.list_turns(conversation_id) == turns_before
    assert of(await stack.events(conversation_id), T.USER_TRANSCRIPT_ACCEPTED, correlation_id) == []
    assert [t.correlation_id for t in stack.brain.turns] == [spoken]


async def test_switch_to_chat_then_text_turn_same_binding(stack):
    await bind_agent(stack, "sess-agent-1")
    before = (await stack.core.sessions.current()).binding
    mode_before = stack.core.interaction_mode.snapshot()
    await stack.voice("active")
    spoken = await stack.voice_turn(before.conversation_id, "Jarvis, résume le projet.")
    await stack.settle()

    status, disabled, text = await stack.call("POST", "/api/chat/voice/disable",
                                              json={"client_request_id": str(uuid.uuid4())})
    assert (status, disabled["state"]) == (202, "switching"), text
    assert (await stack.state())["locked_reason"] == "voice_switching"
    await stack.voice_obeys_disable()
    state = await stack.state()
    assert (state["chat_writable"], state["voice"]["state"]) == (True, "background")
    assert state["voice"]["request"]["status"] == "accepted"

    status, body, correlation_id = await stack.send(state["conversation_id"], "Et maintenant par écrit ?")
    assert (status, body["duplicate"]) == (202, False)
    await stack.settle()
    after = (await stack.core.sessions.current()).binding
    assert (after.conversation_id, after.agent_session_id, after.board_id, after.jarvis_session_id) == (
        before.conversation_id, "sess-agent-1", before.board_id, before.jarvis_session_id)
    assert stack.core.interaction_mode.snapshot() == mode_before
    assert [(t.conversation_id, t.correlation_id) for t in stack.brain.turns] == [
        (before.conversation_id, spoken), (before.conversation_id, correlation_id)]
    rows, _ = await stack.read_chat(before.conversation_id, 0)
    items = project_chat(decode_rows(rows),
                         conversation_id=before.conversation_id)
    assert [i.role for i in items] == ["user", "brain", "user", "brain"]  # une seule conversation, voix puis texte


async def test_subagent_survives_switch(stack):
    conversation_id = await stack.foreground()
    await stack.voice("active")
    spoken = await stack.voice_turn(conversation_id, "Jarvis, lance un sous-agent sur le dossier docs.")
    await stack.settle()
    assert of(await stack.events(conversation_id), T.BRAIN_WORK_STARTED, spoken)

    await stack.call("POST", "/api/chat/voice/disable", json={"client_request_id": str(uuid.uuid4())})
    await stack.voice_obeys_disable()
    status, _, written = await stack.send(conversation_id, "Je passe à l'écrit, préviens-moi ici.")
    assert status == 202
    await stack.settle()
    events = await stack.events(conversation_id)
    assert of(events, T.BRAIN_WORK_CANCELLED) == [] and of(events, T.BRAIN_WORK_FAILED) == []

    stack.brain.finish_subagent("Le sous-agent a compté 42 fichiers.", work_id="agent:sub-1",
                                conversation_id=conversation_id)

    async def published():
        return any(e.content == "Le sous-agent a compté 42 fichiers."
                   for e in of(await stack.events(conversation_id), T.BRAIN_MESSAGE_PUBLISHED))
    await until(published)
    await wait_emitter_settled(stack.core.conversation_event_emitter)
    events = await stack.events(conversation_id)
    late = [e for e in of(events, T.BRAIN_MESSAGE_PUBLISHED) if e.content == "Le sous-agent a compté 42 fichiers."]
    assert len(late) == 1 and late[0].correlation_id == written  # le relais emprunte l'intention courante : écrite
    assert not [e for e in of(events, T.BRAIN_SPEECH_REQUESTED) if "42 fichiers" in (e.content or "")]
    withheld = [e["data"] for e in stack.core_journal() if e["kind"] == "core.brain.speech_withheld_text_channel"]
    assert [w["correlation_id"] for w in withheld] == [written]
    rows, _ = await stack.read_chat(conversation_id, 0)
    texts = [i.text for i in project_chat(decode_rows(rows), conversation_id=conversation_id)]
    assert texts[-1] == "Le sous-agent a compté 42 fichiers."


async def test_text_turn_no_speech_requested(stack):
    stack.voice_absent()
    conversation_id = await stack.foreground()
    status, _, correlation_id = await stack.send(conversation_id, "Lance un sous-agent et parle-moi du dossier")
    assert status == 202
    await stack.settle()
    stack.brain.finish_subagent("Le sous-agent a fini.", work_id="agent:sub-1", conversation_id=conversation_id)

    async def finished():
        return any(e.content == "Le sous-agent a fini."
                   for e in of(await stack.events(conversation_id), T.BRAIN_MESSAGE_PUBLISHED))
    await until(finished)
    await wait_emitter_settled(stack.core.conversation_event_emitter)

    events = await stack.events(conversation_id)
    assert of(events, T.BRAIN_SPEECH_REQUESTED) == []
    assert [e.attributes.get("source") for e in of(events, T.USER_TRANSCRIPT_ACCEPTED)] == ["text"]
    assert {e.content for e in of(events, T.BRAIN_MESSAGE_PUBLISHED, correlation_id)} >= {
        "Le dossier est lu.", f"Réponse à : Lance un sous-agent et parle-moi du dossier", "Le sous-agent a fini."}
    assert not {e.content for e in of(events, T.BRAIN_MESSAGE_PUBLISHED)} & {"Je regarde.", "Lequel des deux ?"}
    withheld = [e["data"] for e in stack.core_journal() if e["kind"] == "core.brain.speech_withheld_text_channel"]
    assert {w["kind"] for w in withheld} >= {"ack", "question", "result"}
    assert {w["correlation_id"] for w in withheld} == {correlation_id}
    assert stack.brain.contexts[-1]["channel"] == "text"
    brief = build_agent_brief(stack.brain.contexts[-1], "Lance un sous-agent et parle-moi du dossier")
    assert BRIEF_TEXT_CHANNEL in brief


async def test_reactivation_relocks_and_inflight_turn_kept(stack):
    await stack.voice("background")
    conversation_id = await stack.foreground()
    stack.brain.hold = asyncio.Event()
    request_id = str(uuid.uuid4())
    status, accepted, correlation_id = await stack.send(conversation_id, "Prépare la synthèse", request_id=request_id)
    assert status == 202
    await asyncio.wait_for(stack.brain.started.wait(), 5)

    await stack.voice("connecting")  # réveil (touche, mot) pendant le tour écrit en vol
    state = await stack.state()
    assert (state["chat_writable"], state["locked_reason"]) == (False, "voice_connecting")
    status, body, refused = await stack.send(conversation_id, "Un second message")
    assert (status, body["code"], body["reason"]) == (409, "chat_input_locked", "voice_connecting")
    await stack.voice("active")
    status, body, _ = await stack.send(conversation_id, "Un troisième")
    assert (status, body["reason"]) == (409, "voice_active")
    # Le renvoi du tour en vol n'est jamais un 409 : le rejeu passe avant le verrou.
    status, body, _ = await stack.send(conversation_id, "Prépare la synthèse", request_id=request_id)
    assert (status, body["duplicate"], body["turn_id"]) == (200, True, accepted["turn_id"])

    stack.brain.hold.set()
    await stack.settle()
    events = await stack.events(conversation_id)
    assert [e.content for e in of(events, T.BRAIN_MESSAGE_PUBLISHED, correlation_id)] == [
        "Réponse à : Prépare la synthèse"]
    assert of(events, T.BRAIN_SPEECH_REQUESTED, correlation_id) == []  # admis par écrit : reste muet
    assert of(events, T.BRAIN_TURN_FAILED) == [] and of(events, T.USER_TRANSCRIPT_ACCEPTED, refused) == []
    assert len(stack.brain.turns) == 1


async def test_retry_after_timeout_no_duplicate(stack, monkeypatch):
    stack.voice_absent()
    conversation_id = await stack.foreground()
    real_submit = stack.core.brain.submit

    async def slow_submit(turn):
        await asyncio.sleep(1.0)  # Core lent à admettre : le relais du Control Center abandonne avant
        return await real_submit(turn)

    stack.core.brain.submit = slow_submit
    monkeypatch.setattr(chat_relay, "CHAT_TURN_TIMEOUT_S", 0.3)
    request_id = str(uuid.uuid4())
    status, body, correlation_id = await stack.send(conversation_id, "Envoi lent", request_id=request_id)
    assert (status, body["code"]) == (504, "core_timeout")
    assert "resend the same client_request_id" in body["error"]

    monkeypatch.setattr(chat_relay, "CHAT_TURN_TIMEOUT_S", 15.0)
    status, retry, _ = await stack.send(conversation_id, "Envoi lent", request_id=request_id)  # premier encore en vol
    assert status in (200, 202), retry
    await stack.settle()
    status, again, _ = await stack.send(conversation_id, "Envoi lent", request_id=request_id)
    assert (status, again["duplicate"], again["turn_id"]) == (200, True, retry["turn_id"])
    status, conflict, _ = await stack.send(conversation_id, "Autre texte", request_id=request_id)
    assert (status, conflict["code"]) == (409, "chat_request_conflict")
    await stack.settle()

    events = await stack.events(conversation_id)
    assert len(of(events, T.USER_TRANSCRIPT_ACCEPTED, correlation_id)) == 1
    assert len(of(events, T.BRAIN_MESSAGE_PUBLISHED, correlation_id)) == 1
    assert [t.correlation_id for t in stack.brain.turns] == [correlation_id]
    assert len(await stack.core.conversations.list_turns(conversation_id)) == 1
    relayed = [e["data"] for e in stack.cc_trace() if e["kind"] == "chat.turn.relayed"]
    assert [r["status"] for r in relayed][:1] == [504] and "Envoi lent" not in json.dumps(relayed)


async def test_board_switch_A_B_A_no_leak(stack):
    stack.voice_absent()
    conv_a = await stack.foreground()
    board_a = (await stack.core.sessions.current()).session.active_board_id
    status, _, on_a = await stack.send(conv_a, "Message du Board A")
    assert status == 202
    attachment = await stack.upload("note-a.txt", "seulement pour A\n".encode())
    await stack.settle()

    board_b = (await stack.core.boards.create({"title": "Projet B"})).board_id
    status, _, text = await stack.call("POST", "/api/boards/switch", json={"board_id": board_b})
    assert status == 200, text
    state = await stack.state()
    conv_b = state["conversation_id"]
    assert (state["board_id"], conv_b != conv_a) == (board_b, True)
    rows_b, _ = await stack.read_chat(conv_b, 0)
    assert rows_b == []
    status, body, _ = await stack.send(conv_a, "Envoyé vers A alors que B est affiché")
    assert (status, body["code"], body["current_conversation_id"]) == (409, "chat_conversation_not_foreground", conv_b)
    status, _, on_b = await stack.send(conv_b, "Message du Board B")
    assert status == 202
    await stack.settle()

    status, _, text = await stack.call("POST", "/api/boards/switch", json={"board_id": board_a})
    assert status == 200, text
    state = await stack.state()
    assert (state["board_id"], state["conversation_id"]) == (board_a, conv_a)
    rows_a, _ = await stack.read_chat(conv_a, 0)
    rows_b, _ = await stack.read_chat(conv_b, 0)
    corr = lambda rows: {r["event"]["correlation_id"] for r in rows}  # noqa: E731
    assert corr(rows_a) == {on_a} and corr(rows_b) == {on_b}
    assert {r["event"]["conversation_id"] for r in rows_a} == {conv_a}
    assert [t.conversation_id for t in stack.brain.turns] == [conv_a, conv_b]
    status, listed_a, _ = await stack.call("GET", f"/api/workspace/artifacts?board_id={board_a}&limit=50")
    status, listed_b, _ = await stack.call("GET", f"/api/workspace/artifacts?board_id={board_b}&limit=50")
    assert attachment["artifact_id"] in {a["artifact_id"] for a in listed_a["artifacts"]}
    assert attachment["artifact_id"] not in {a["artifact_id"] for a in listed_b["artifacts"]}


async def test_reload_equals_live_union(stack, tmp_path):
    stack.voice_absent()
    conversation_id = await stack.foreground()
    live_pages: list[list[dict]] = []
    cursor = 0

    async def tick():
        nonlocal cursor
        rows, cursor = await stack.read_chat(conversation_id, cursor)
        live_pages.append(rows)

    await tick()
    await stack.voice_turn(conversation_id, "Jarvis, première question", addressing="addressed")
    await tick()
    await stack.voice_turn(conversation_id, "peut-être pour toi", addressing="uncertain")  # promue par sa réponse
    await tick()
    await stack.settle()
    await tick()
    status, _, _ = await stack.send(conversation_id, "Texte un")
    await tick()
    status, _, failed = await stack.send(conversation_id, "Celui-ci échoue")
    await stack.settle()
    await tick()
    status, _, _ = await stack.send(conversation_id, "Lance un sous-agent")
    await stack.settle()
    stack.brain.finish_subagent("Résultat tardif.", work_id="agent:sub-1", conversation_id=conversation_id)

    async def late():
        return any(e.content == "Résultat tardif." for e in of(await stack.events(conversation_id),
                                                               T.BRAIN_MESSAGE_PUBLISHED))
    await until(late)
    await wait_emitter_settled(stack.core.conversation_event_emitter)
    await tick()
    await tick()  # une lecture de plus : rien de neuf, curseur stable

    live = [row for page in live_pages for row in page]
    ids = [row["event"]["event_id"] for row in live]
    assert len(ids) == len(set(ids)), "no event read twice by the live loop"
    assert live_pages[-1] == []
    reload_rows, reload_cursor = await stack.read_chat(conversation_id, 0)
    assert reload_cursor == cursor and [r["event"]["event_id"] for r in reload_rows] == ids
    decode = lambda rows: decode_rows(rows)  # noqa: E731
    assert all(is_chat_event(item.event) for item in decode_rows(live))
    py_live = project_chat(decode_rows(live), conversation_id=conversation_id)
    assert py_live == project_chat(decode_rows(reload_rows), conversation_id=conversation_id)
    # Panne du backend : aucune publication, la bulle Utilisateur porte le statut d'échec (jamais une fausse réponse).
    assert [i.failure_code for i in py_live if i.correlation_id == failed] == ["brain_backend_exception"]
    assert sum(1 for i in py_live if i.role == "user") == 5  # 2 voix (dont l'incertaine promue) + 3 écrits
    # Le modèle servi à la page : pages live appliquées une à une == une hydratation.
    got = run_node(tmp_path, """
      const live=CM.createChatModel();CM.reset(live,DATA.conv);for(const p of DATA.pages)CM.applyPage(live,{events:p});
      const again=CM.createChatModel();CM.reset(again,DATA.conv);CM.applyPage(again,{events:DATA.reload});
      for(const p of DATA.pages)CM.applyPage(again,{events:p});
      const one=CM.createChatModel();CM.reset(one,DATA.conv);CM.applyPage(one,{events:DATA.reload});
      out({live:CM.items(live),one:CM.items(one),replayed:CM.items(again)});
    """, {"conv": conversation_id, "pages": live_pages, "reload": reload_rows})
    assert got["live"] == got["one"] == got["replayed"]
    assert [[i["role"], i["event_id"]] for i in got["one"]] == [[i.role, i.event_id] for i in py_live]


async def test_core_restart_cursor_survives_and_unknown_grace(stack):
    stack.voice_absent()
    conversation_id = await stack.foreground()
    status, _, first = await stack.send(conversation_id, "Avant le redémarrage")
    assert status == 202
    await stack.settle()
    rows_before, cursor = await stack.read_chat(conversation_id, 0)
    assert len(rows_before) == 2

    await stack.restart_core()
    state = await stack.state()  # le relais retrouve Core sur le même port
    assert (state["voice"]["state"], state["chat_writable"], state["locked_reason"]) == (
        "unknown", False, "voice_unknown")
    assert state["conversation_id"] == conversation_id
    status, body, refused = await stack.send(conversation_id, "Pendant la grâce")
    assert (status, body["code"], body["reason"]) == (409, "chat_input_locked", "voice_unknown")
    rows, same = await stack.read_chat(conversation_id, cursor)
    assert (rows, same) == ([], cursor)  # le curseur du client survit : ni doublon ni recul

    await stack.voice("background")  # le premier rapport rétablit la vérité
    assert (await stack.state())["chat_writable"] is True
    status, _, second = await stack.send(conversation_id, "Après le redémarrage")
    assert status == 202
    await stack.settle()
    rows, cursor_after = await stack.read_chat(conversation_id, cursor)
    assert {r["event"]["correlation_id"] for r in rows} == {second}
    assert all(r["sequence"] > cursor for r in rows) and cursor_after > cursor
    full, _ = await stack.read_chat(conversation_id, 0)
    assert [r["event"]["event_id"] for r in full] == [r["event"]["event_id"] for r in rows_before + rows]
    assert of(await stack.events(conversation_id), T.USER_TRANSCRIPT_ACCEPTED, refused) == []

    # Sans rapport du tout : `unknown` le temps de la grâce, puis `absent` (Chat sans voix) et inscriptible.
    await stack.restart_core()
    assert (await stack.state())["locked_reason"] == "voice_unknown"
    stack.voice_absent()
    state = await stack.state()
    assert (state["voice"]["state"], state["chat_writable"]) == ("absent", True)


async def test_unreadable_attachment_announced(stack):
    stack.voice_absent()
    conversation_id = await stack.foreground()
    archive = await stack.upload("archive.zip", ZIP, "application/zip")
    assert (archive["brain_readable"], archive["mime_type"], archive["state"]) == (
        False, "application/octet-stream", "complete")
    photo = await stack.upload("photo.png", PNG, "image/png")
    assert photo["brain_readable"] is True
    # Pièce supprimée entre l'envoi et le tour : annoncée indisponible, jamais tue.
    payload = Path(stack.core.artifacts._payloads.root()) / photo["artifact_id"]
    for child in payload.iterdir():
        child.unlink()
    status, body, _ = await stack.send(conversation_id, "Analyse ces pièces",
                                       attachments=[archive["artifact_id"], photo["artifact_id"]])
    assert status == 202, body
    await stack.settle()
    context = stack.brain.contexts[-1]
    items = {item["artifact_id"]: item for item in context["attachments"]["items"]}
    assert items[archive["artifact_id"]]["brain_readable"] is False
    brief = build_agent_brief(with_agent_readability(context, "claude"), "Analyse ces pièces")
    block = brief[brief.index(BRIEF_ATTACHMENTS_HEADER):brief.index("[Demande]")]
    assert "« archive.zip » (application/octet-stream, 2,9 Ko) : format non lisible par toi" in block
    assert "« photo.png » (image/png" in block and "pièce indisponible" in block
    assert "Read →" not in block, "no path handed for an unreadable or missing file"
    codex = build_agent_brief(with_agent_readability(context, "codex"), "Analyse ces pièces")
    assert "lisible avec Read" not in codex  # Codex : rien d'attesté lisible


async def test_board_drop_file_image_url_visible_no_turn(stack, monkeypatch):
    board = (await stack.core.sessions.current()).session.active_board_id
    events_before = len(await stack.all_events())
    conversations_before = (await stack.core.conversation_events.list_conversations(limit=100)).summaries
    guard = NoOutboundNetwork(monkeypatch)
    status, pdf, text = await stack.call("POST", f"/api/boards/drop?board_id={board}", headers=MULTIPART,
                                         data=multipart(str(uuid.uuid4()), "compte-rendu.pdf", "application/pdf", PDF))
    assert status == 201, text
    status, image, text = await stack.call("POST", f"/api/boards/drop?board_id={board}", headers=MULTIPART,
                                           data=multipart(str(uuid.uuid4()), "capture.png", "image/png", PNG))
    assert status == 201, text
    status, link, text = await stack.call("POST", "/api/boards/drop-link", json={
        "client_upload_id": str(uuid.uuid4()), "url": "https://example.invalid/page?jeton=x", "board_id": board})
    assert status == 201, text
    assert guard.attempts == []  # l'URL n'est jamais récupérée
    status, listed, _ = await stack.call("GET", f"/api/workspace/artifacts?board_id={board}&limit=50")
    by_id = {a["artifact_id"]: a for a in listed["artifacts"]}
    assert (by_id[pdf["artifact_id"]]["kind"], by_id[pdf["artifact_id"]]["provenance"]) == ("upload", "board_drop")
    assert by_id[image["artifact_id"]]["provenance"] == "board_drop" and image["mime_type"] == "image/png"
    assert (by_id[link["artifact_id"]]["kind"], by_id[link["artifact_id"]]["preview"]) == (
        "link", "https://example.invalid/page?jeton=x")
    await stack.settle()
    assert len(await stack.all_events()) == events_before  # ni tour, ni message, ni conversation
    assert (await stack.core.conversation_events.list_conversations(limit=100)).summaries == conversations_before
    assert stack.brain.turns == []
    assert not any(a.get("kind") == "scene_object" for a in listed["artifacts"])


ROUTES = (  # chaque route du Chat et du dépôt, avec un corps qui passerait la garde
    ("GET", "/api/chat/state", {}),
    ("GET", EVENTS + "?conversation_id=CONV&projection=chat", {}),
    ("POST", "/api/chat/voice/disable", {"json": {"client_request_id": "00000000-0000-4000-8000-000000000001"}}),
    ("POST", "/api/chat/turns", {"json": {"conversation_id": "CONV", "content": "x",
                                          "client_request_id": "00000000-0000-4000-8000-000000000002"}}),
    ("POST", "/api/chat/uploads", {"multipart": ("a.txt", b"bonjour\n")}),
    ("POST", "/api/boards/drop?board_id=BOARD", {"multipart": ("b.txt", b"bonjour\n")}),
    ("POST", "/api/boards/drop-link", {"json": {"client_upload_id": "00000000-0000-4000-8000-000000000003",
                                                "url": "https://example.invalid/", "board_id": "BOARD"}}),
)
HOSTILE = (
    ("foreign_origin", {"Origin": "https://evil.example"}),
    ("dns_rebinding_host", {"Host": "evil.example"}),
    ("cross_site_fetch", {"Sec-Fetch-Site": "cross-site"}),
    ("other_local_port", {"Origin": "http://127.0.0.1:1"}),
    ("null_origin", {"Origin": "null"}),
)


async def test_security_cross_origin_refused_all_chat_routes(stack):
    stack.voice_absent()
    conversation_id = await stack.foreground()
    board = (await stack.core.sessions.current()).session.active_board_id

    def request(method, path, spec, headers):
        path = path.replace("CONV", conversation_id).replace("BOARD", board)
        kwargs = {"headers": dict(headers)}
        if "json" in spec:
            body = json.loads(json.dumps(spec["json"]).replace("CONV", conversation_id).replace("BOARD", board))
            body = {**body, **({"client_request_id": str(uuid.uuid4())} if "client_request_id" in body else {}),
                    **({"client_upload_id": str(uuid.uuid4())} if "client_upload_id" in body else {})}
            kwargs["json"] = body
        if "multipart" in spec:
            kwargs["data"] = multipart(str(uuid.uuid4()), *spec["multipart"][:1], "text/plain", spec["multipart"][1])
            kwargs["headers"].update(MULTIPART)
        return stack.call(method, path, **kwargs)

    refused = []
    for method, path, spec in ROUTES:
        vectors = HOSTILE + ((("same_site_mutation", {"Sec-Fetch-Site": "same-site"}),) if method == "POST" else ())
        for name, headers in vectors:
            status, body, text = await request(method, path, spec, headers)
            assert (status, (body or {}).get("code")) == (403, "forbidden_origin"), (method, path, name, text)
            refused.append((path, name))
    await stack.settle()
    assert stack.brain.turns == []
    assert of(await stack.all_events(), T.USER_TRANSCRIPT_ACCEPTED) == []
    assert stack.core.voice_channel.write_gate() is None  # aucune demande de bascule n'est passée
    status, listed, _ = await stack.call("GET", f"/api/workspace/artifacts?board_id={board}&limit=50")
    assert listed["artifacts"] == []
    # Témoin : les mêmes requêtes, de la page elle-même (Origin de bouclage du Control Center), passent la garde.
    own = {"Origin": f"http://127.0.0.1:{stack.cc.server.port}", "Sec-Fetch-Site": "same-origin"}
    for method, path, spec in ROUTES:
        status, body, text = await request(method, path, spec, own)
        assert status != 403, (method, path, text)
    assert len(refused) == len(ROUTES) * len(HOSTILE) + 5


async def test_no_bytes_or_names_in_trace_and_events(stack, monkeypatch):
    NoOutboundNetwork(monkeypatch)
    stack.voice_absent()
    conversation_id = await stack.foreground()
    board = (await stack.core.sessions.current()).session.active_board_id
    secret_text = "CONTENU-SECRET-DU-FICHIER-7Q2"
    attached = await stack.upload("bilan-confidentiel-Zx9.txt", f"{secret_text}\n".encode(), "text/plain")
    image = await stack.upload("visage-privé-Kp4.png", PNG + secret_text.encode(), "image/png")
    status, _, _ = await stack.call("POST", f"/api/boards/drop?board_id={board}", headers=MULTIPART,
                                    data=multipart(str(uuid.uuid4()), "dossier-médical-Wq3.pdf", "application/pdf",
                                                   PDF + secret_text.encode()))
    assert status == 201
    status, _, _ = await stack.call("POST", "/api/boards/drop-link", json={
        "client_upload_id": str(uuid.uuid4()), "url": "https://example.invalid/privé-Lm8?jeton=Tk5", "board_id": board})
    assert status == 201
    status, _, correlation_id = await stack.send(conversation_id, "Regarde les pièces",
                                                 attachments=[attached["artifact_id"], image["artifact_id"]])
    assert status == 202
    await stack.settle()

    events = await stack.all_events()
    [user_event] = of(events, T.USER_TRANSCRIPT_ACCEPTED, correlation_id)
    assert user_event.attributes["attachment_count"] == 2
    encoded = json.dumps([encode_conversation_event(e) for e in events], ensure_ascii=False)
    core_journal = json.dumps(stack.core_journal(), ensure_ascii=False)
    cc_trace = json.dumps(stack.cc_trace(), ensure_ascii=False)
    root = str(Path(stack.core.artifacts._payloads.root()))
    for where, text in (("events", encoded), ("core journal", core_journal), ("control center trace", cc_trace)):
        for secret in ("bilan-confidentiel", "Zx9", "visage-priv", "Kp4", "dossier-m", "Wq3", secret_text,
                       "example.invalid", "Lm8", "Tk5"):
            assert secret not in text, f"{secret!r} leaked into {where}"
    assert attached["artifact_id"] not in encoded and root not in encoded  # ni id, ni chemin dans les événements
    for kind in ("chat.upload.relayed", "chat.turn.relayed", "board.drop.relayed", "board.drop_link.relayed"):
        assert any(e["kind"] == kind for e in stack.cc_trace()), kind


# ============================================================================================== Catégorie 2


class RealStack:
    """Core et Control Center de production en sous-processus (`python -m jarvis core|control-center`).

    Racine de données, runtime, jeton : sous `root` ; ports éphémères ; vrai CLI `claude` sur le PATH.
    Aucun processus Voice : passé la grâce de 5 s, la voix est `absent` et le Chat inscriptible.
    Tout ce qui est lancé est tué en sortie (`taskkill /T /F`).
    """

    def __init__(self, root: Path, *, python: str = sys.executable) -> None:
        self.root = root
        self.data, self.runtime = root / "data", root / "runtime"
        for path in (self.data, self.runtime):
            path.mkdir(parents=True, exist_ok=True)
        self.core_port, self.ui_port = free_port(), free_port()
        self.python = python
        self.procs: list[subprocess.Popen] = []
        self.feedback_root = ROOT / "retours-utilisateur"
        self.feedback_before = set(os.listdir(self.feedback_root)) if self.feedback_root.is_dir() else set()
        self.feedback_removed: list[str] = []

    @property
    def cc(self) -> str:
        return f"http://127.0.0.1:{self.ui_port}"

    def env(self) -> dict:
        env = {k: v for k, v in os.environ.items() if k not in ("JARVIS_FEEDBACK_DIR", "JARVIS_LAUNCHED_AT",
                                                                 "JARVIS_CLAUDE_CLI")}
        env.update({"PYTHONPATH": str(ROOT), "JARVIS_DATA_ROOT": str(self.data), "JARVIS_RUNTIME_DIR": str(self.runtime),
                    "JARVIS_CORE_HOST": "127.0.0.1", "JARVIS_CORE_PORT": str(self.core_port),
                    "JARVIS_UI_PORT": str(self.ui_port), "JARVIS_VISUALIZER_ENABLED": "0",
                    "JARVIS_AUDIO_RECORDING": "0", "JARVIS_SCREEN_CAPTURE": "0", "JARVIS_CONTEXT_ENRICHMENT": "0",
                    "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        return env

    async def __aenter__(self) -> "RealStack":
        try:
            for name, port in (("core", self.core_port), ("control-center", self.ui_port)):
                log = open(self.root / f"{name}.log", "wb")
                self.procs.append(subprocess.Popen([self.python, "-m", "jarvis", name], cwd=str(ROOT), env=self.env(),
                                                   stdout=log, stderr=subprocess.STDOUT,
                                                   creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)))
                await self._wait(f"http://127.0.0.1:{port}" + ("/v1/health" if name == "core" else "/api/status"))
            await self._wait(self.cc + "/api/chat/state", ok=lambda b: b.get("chat_writable") is True, timeout=60)
        except BaseException:
            await self.__aexit__()
            raise
        return self

    async def _wait(self, url: str, *, ok=lambda body: True, timeout: float = 120.0) -> None:  # noqa: ANN001
        deadline = time.monotonic() + timeout
        async with aiohttp.ClientSession() as http:
            while time.monotonic() < deadline:
                try:
                    async with http.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                        if response.status < 500 and ok(await response.json(content_type=None)):
                            return
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                    pass
                await asyncio.sleep(0.5)
        raise AssertionError(f"no answer from {url} in {timeout:.0f} s")

    async def __aexit__(self, *exc) -> None:
        for proc in reversed(self.procs):
            if proc.poll() is None:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False)
        await asyncio.sleep(1.0)
        if self.feedback_root.is_dir():
            for name in sorted(set(os.listdir(self.feedback_root)) - self.feedback_before):
                folder = self.feedback_root / name
                if folder.is_dir() and not any(folder.iterdir()):
                    folder.rmdir()
                    self.feedback_removed.append(str(folder))

    async def request(self, method: str, path: str, **kwargs) -> tuple[int, dict]:
        async with aiohttp.ClientSession() as http:
            async with http.request(method, self.cc + path, **kwargs) as response:
                return response.status, await response.json(content_type=None)

    async def upload(self, filename: str, data: bytes, content_type: str) -> dict:
        status, body = await self.request("POST", "/api/chat/uploads", headers=MULTIPART,
                                          data=multipart(str(uuid.uuid4()), filename, content_type, data))
        assert status == 201, body
        return body

    async def ask(self, content: str, *, attachments: list[str] | None = None, timeout: float = 420.0,
                  until_text=None) -> tuple[str, list[dict]]:  # noqa: ANN001
        """Envoyer un tour écrit par `/api/chat/turns`, attendre sa réponse publiée ; (corrélation, lignes du Chat)."""

        status, state = await self.request("GET", "/api/chat/state")
        assert status == 200 and state["chat_writable"], state
        body = {"conversation_id": state["conversation_id"], "client_request_id": str(uuid.uuid4()), "content": content}
        if attachments:
            body["attachments"] = attachments
        status, answer = await self.request("POST", "/api/chat/turns", json=body)
        assert status == 202, answer
        correlation_id = answer["correlation_id"]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rows = await self.chat_rows(state["conversation_id"])
            replies = [r for r in rows if r["event"]["correlation_id"] == correlation_id
                       and r["event"]["event_type"] == "brain.message.published"]
            if replies and (until_text is None or until_text(replies)):
                return correlation_id, rows
            await asyncio.sleep(2.0)
        raise AssertionError(f"no Brain answer for {correlation_id} in {timeout:.0f} s")

    async def chat_rows(self, conversation_id: str, *, projection: str | None = "chat") -> list[dict]:
        params = {"conversation_id": conversation_id, "limit": "500", "after_sequence": "0"}
        if projection:
            params["projection"] = projection
        status, page = await self.request("GET", EVENTS, params=params)
        assert status == 200, page
        return page["events"]

    def trace(self) -> list[dict]:
        out = []
        path = self.runtime / "trace.jsonl"
        if path.exists():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out


def text_pdf(lines: list[str]) -> bytes:
    """Un PDF texte valide d'une page (Helvetica), xref exact : lisible par l'outil Read du CLI."""

    stream = "BT /F1 20 Tf 60 740 Td 26 TL " + " ".join(f"({line}) Tj T*" for line in lines) + " ET"
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
               "/Resources << /Font << /F1 5 0 R >> >> >>",
               f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
               "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


_GLYPHS = {  # police 5×7, une chaîne par ligne
    "A": "01110 10001 10001 11111 10001 10001 10001", "C": "01110 10001 10000 10000 10000 10001 01110",
    "D": "11110 10001 10001 10001 10001 10001 11110", "E": "11111 10000 10000 11110 10000 10000 11111",
    "G": "01110 10001 10000 10111 10001 10001 01111", "I": "01110 00100 00100 00100 00100 00100 01110",
    "L": "10000 10000 10000 10000 10000 10000 11111", "M": "10001 11011 10101 10101 10001 10001 10001",
    "N": "10001 11001 10101 10011 10001 10001 10001", "O": "01110 10001 10001 10001 10001 10001 01110",
    "P": "11110 10001 10001 11110 10000 10000 10000", "R": "11110 10001 10001 11110 10100 10010 10001",
    "S": "01111 10000 10000 01110 00001 00001 11110", "T": "11111 00100 00100 00100 00100 00100 00100",
    "U": "10001 10001 10001 10001 10001 10001 01110", "V": "10001 10001 10001 10001 10001 01010 00100",
    "4": "00010 00110 01010 10010 11111 00010 00010", "7": "11111 00001 00010 00100 01000 01000 01000",
    "-": "00000 00000 00000 11111 00000 00000 00000", " ": "00000 00000 00000 00000 00000 00000 00000",
}


def text_png(text: str, *, scale: int = 10) -> bytes:
    """Un PNG noir sur blanc qui montre `text` (majuscules, chiffres 4 et 7, tiret, espace), sans dépendance."""

    rows_of = [_GLYPHS[c].split() for c in text]
    width, height = (len(text) * 6 + 1) * scale, 9 * scale
    raw = bytearray()
    for y in range(height):
        gy = y // scale - 1
        raw.append(0)
        for x in range(width):
            index, column = divmod(x // scale - 1, 6) if x // scale >= 1 else (-1, 0)
            on = 0 <= index < len(text) and column < 5 and 0 <= gy < 7 and rows_of[index][gy][column] == "1"
            raw.append(0 if on else 255)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def cli_user_messages(session_id: str) -> list[str]:
    """Messages utilisateur de la transcription que le CLI `claude` tient pour sa session (cwd = le dépôt)."""

    slug = "".join(c if c.isalnum() else "-" for c in str(ROOT))
    path = Path.home() / ".claude" / "projects" / slug / f"{session_id}.jsonl"
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry.get("type") != "user":
            continue
        content = entry["message"]["content"]
        text = content if isinstance(content, str) else " ".join(
            part.get("text", "") for part in content if isinstance(part, dict))
        if text:
            out.append(text)
    return out


#: Ce que les pièces de Catégorie 2 portent (aucune donnée privée : des phrases de test).
PDF_SECRET = "La phrase secrete est licorne violette 2026."
PNG_TEXT = "CODE ORANGE 47"


def short_root(prefix: str = "jarvis-s9-") -> Path:
    """Racine courte sous le temp du système : un payload d'Artifact sous un `tmp_path` pytest profond dépasse
    MAX_PATH (260) sous Windows et Core refuse alors l'envoi (`upload_storage_failed`)."""

    return Path(tempfile.mkdtemp(prefix=prefix))


@LIVE_ONLY
async def test_attachments_pdf_png_read_by_real_cli(tmp_path):
    root = short_root()
    async with RealStack(root) as real:
        pdf = await real.upload("note-de-test.pdf", text_pdf(["Document de test Jarvis.", PDF_SECRET]),
                                "application/pdf")
        png = await real.upload("etiquette-de-test.png", text_png(PNG_TEXT), "image/png")
        assert (pdf["mime_type"], pdf["brain_readable"], png["mime_type"], png["brain_readable"]) == (
            "application/pdf", True, "image/png", True)
        correlation_id, rows = await real.ask(
            "Lis les deux pièces jointes. Réponds en deux lignes : la phrase secrète du PDF, "
            "puis le texte visible sur l'image.", attachments=[pdf["artifact_id"], png["artifact_id"]])
        conversation_id = rows[0]["event"]["conversation_id"]
        answer = " ".join(r["event"]["content"] for r in rows if r["event"]["correlation_id"] == correlation_id
                          and r["event"]["event_type"] == "brain.message.published")
        trace = real.trace()
        everything = await real.chat_rows(conversation_id, projection=None)
        (tmp_path / "evidence.json").write_text(json.dumps({"answer": answer, "trace_kinds": [e["kind"] for e in trace]},
                                                           ensure_ascii=False), encoding="utf-8")

    shutil.copy(real.runtime / "trace.jsonl", tmp_path / "trace.jsonl")  # pour l'analyse de trace, hors du dépôt
    shutil.rmtree(root, ignore_errors=True)  # bases de test seulement, jamais une base du poste
    normalized = answer.lower()
    assert "licorne violette" in normalized and "2026" in normalized, answer
    assert "orange" in normalized and "47" in normalized, answer
    # Ce que le CLI a reçu : le brief réel, lu dans la transcription de session du CLI (la trace n'en garde
    # que la demande visible, `agent.input`).
    [ask] = [e for e in trace if e["kind"] == "agent.ask"]
    brief = cli_user_messages(ask["data"]["session_id"])[0]
    assert BRIEF_TEXT_CHANNEL in brief and BRIEF_ATTACHMENTS_HEADER in brief
    assert brief.index(BRIEF_ATTACHMENTS_HEADER) < brief.index("[Demande]")
    reads = [block["input"].get("file_path", "") for e in trace if e["kind"] == "agent.event"
             for block in (((e.get("data") or {}).get("message") or {}).get("content") or [])
             if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Read"]
    assert sorted(Path(path).parent.name for path in reads) == sorted([pdf["artifact_id"], png["artifact_id"]])
    user_events = [r["event"] for r in everything if r["event"]["correlation_id"] == correlation_id
                   and r["event"]["event_type"] == "user.transcript.accepted"]
    assert [e["attributes"].get("attachment_count") for e in user_events] == [2]
    assert not [r for r in everything if r["event"]["correlation_id"] == correlation_id
                and r["event"]["event_type"] == "brain.speech.requested"]
    encoded = json.dumps(everything, ensure_ascii=False)
    for private in ("note-de-test", "etiquette-de-test", pdf["artifact_id"], "upload.pdf", "upload.png"):
        assert private not in encoded, private

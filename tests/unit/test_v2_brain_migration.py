"""Phase D : la propriété du travail long quitte Voice pour Core.

Ce fichier prouve les quatre critères de la migration (docs/03, « Phase D ») :

1. Voice n'attend plus dans `_call_claude()` en mode continu ;
2. Voice ne tient plus un appel d'outil Realtime ouvert pour représenter le
   travail du cerveau ;
3. Core possède le travail en cours et survit à `Jarvis Mute` (Décision 11) ;
4. la sortie finale du cerveau apparaît comme un événement Core.

Il prouve aussi que l'ancien chemin de persistance a disparu **mécaniquement**
du mode continu (Décision 30), et que le mode legacy est inchangé (Décision 20).

Ce qui n'est **pas** prouvé ici : la restitution parlée de ces événements par la
surface, qui est la tâche 08, et le comportement acoustique réel, qu'aucun test
ne peut mesurer.
"""

from __future__ import annotations

import ast
import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from aiohttp import web

from jarvis.adapters.control_center_brain import (
    AGENT_TURN_FAILED,
    BACKEND_HTTP_ERROR,
    BACKEND_UNREACHABLE,
    ControlCenterBrainBackend,
)
from jarvis.adapters.jsonl_history import JsonlHistoryStore
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.core.brain_service import (
    BRAIN_SPEECH_REQUESTED,
    BRAIN_TURN_ACCEPTED,
    BRAIN_WORK_COMPLETED,
    BRAIN_WORK_FAILED,
    BRAIN_WORK_STARTED,
    BrainOrchestrator,
)
from jarvis.core.v2_services import ConversationService, CoreEventBus
from jarvis.domain.v2 import (
    BRAIN_NOT_ADDRESSED_ANSWER,
    AddressingDecision,
    BrainEvent,
    BrainEventKind,
    BrainRunStatus,
    BrainTurnInput,
    BrainTurnResult,
    BrainWorkingState,
    ProtocolEnvelope,
    SpeechKind,
    SpeechRequest,
)
from jarvis.protocol.client import CoreProtocolError
from jarvis.runtime.realtime_audio import CLAUDE_TOOL, RealtimeConversationBridge

TIMEOUT_S = 5.0
REALTIME_AUDIO = Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "realtime_audio.py"


# --- doubles -----------------------------------------------------------------


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[BrainEvent] = []

    async def emit(self, event: BrainEvent) -> None:
        self.events.append(event)

    def kinds(self) -> list[str]:
        return [event.kind.value for event in self.events]


class BrainCoreDouble:
    """Core vu depuis le bridge : il enregistre par où passe chaque tour."""

    def __init__(self, *, reject: Exception | None = None, duplicate: bool = False) -> None:
        self.appended: list[tuple[str, dict | None]] = []
        self.brain_turns: list[dict[str, object]] = []
        self.tool_calls: list[str] = []
        self.reject = reject
        self.duplicate = duplicate

    async def append_turn(self, conversation_id: str, *, kind: str, content: str, metadata=None) -> dict:  # noqa: ANN001
        del conversation_id, content
        self.appended.append((kind, metadata))
        return {}

    async def submit_brain_turn(self, conversation_id: str, *, content: str, correlation_id: str, source: str = "realtime", addressing: str = "addressed", provider_item_id=None, interrupted_speech_id=None) -> dict:  # noqa: ANN001
        del interrupted_speech_id
        if self.reject is not None:
            raise self.reject
        self.brain_turns.append({"conversation_id": conversation_id, "content": content, "correlation_id": correlation_id, "source": source, "addressing": addressing, "provider_item_id": provider_item_id})
        return {"turn_id": "turn-1", "correlation_id": correlation_id, "revision": 1, "duplicate": self.duplicate}

    async def call_tool(self, name: str, arguments: dict, *, conversation_id: str) -> dict:
        del arguments, conversation_id
        self.tool_calls.append(name)
        return {"disposition": "execute", "executed": True}


class QueueSession:
    """Session Realtime pilotée évènement par évènement depuis le test."""

    def __init__(self) -> None:
        self.inbox: asyncio.Queue[ProtocolEnvelope | None] = asyncio.Queue()
        self.results: list[tuple[str, dict]] = []
        self.contexts: list[str] = []

    async def events(self):
        while True:
            event = await self.inbox.get()
            if event is None:
                return
            yield event

    async def push(self, message_type: str, **payload: object) -> None:
        await self.inbox.put(ProtocolEnvelope(message_type=message_type, payload=payload))

    async def stop(self) -> None:
        await self.inbox.put(None)

    async def send_audio(self, pcm: bytes) -> None:
        del pcm

    async def send_tool_result(self, call_id: str, result: dict) -> None:
        self.results.append((call_id, result))

    async def send_context(self, text: str) -> None:
        self.contexts.append(text)

    async def keepalive(self) -> None:
        return None


class SilentAudio:
    input_device = output_device = None
    sample_rate = 24000
    captured_bytes = sent_bytes = 0

    def __init__(self) -> None:
        self._drained = asyncio.Event()

    async def start(self) -> None:
        return None

    async def pump_input(self, session) -> None:  # noqa: ANN001
        await self._drained.wait()

    async def stop_input(self) -> None:
        self._drained.set()

    def set_active_output(self, **identity) -> None:  # noqa: ANN003
        del identity

    async def play_b64(self, value: str) -> None:
        del value

    async def close(self) -> None:
        self._drained.set()


class RecordingJournal:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.changed = asyncio.Event()

    def emit(self, kind: str, message: str, *, level: str = "info", data=None) -> None:
        self.events.append({"kind": kind, "message": message, "level": level, "data": data or {}})
        self.changed.set()

    def of(self, kind: str) -> list[dict[str, object]]:
        return [event for event in self.events if event["kind"] == kind]

    async def wait_until(self, predicate) -> None:
        while True:
            self.changed.clear()
            if predicate():
                return
            await asyncio.wait_for(self.changed.wait(), timeout=TIMEOUT_S)


@dataclass(slots=True)
class SlowBackend:
    """Backend cerveau qui ne rend la main que sur ordre du test."""

    started: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: list[str] = field(default_factory=list)

    async def run_turn(self, turn: BrainTurnInput, state, emit) -> BrainTurnResult:  # noqa: ANN001
        del state
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.append(turn.correlation_id)
            raise
        await emit.emit(
            BrainEvent(
                kind=BrainEventKind.SPEECH,
                conversation_id=turn.conversation_id,
                correlation_id=turn.correlation_id,
                work_id="work-1",
                speech=SpeechRequest(
                    conversation_id=turn.conversation_id,
                    text="J'ai relu tes mails : trois attendent une réponse.",
                    kind=SpeechKind.RESULT,
                    correlation_id=turn.correlation_id,
                    work_id="work-1",
                ),
            )
        )
        return BrainTurnResult(correlation_id=turn.correlation_id, status=BrainRunStatus.COMPLETED, public_summary="Trois mails à traiter.")


# --- utilitaires -------------------------------------------------------------


def make_bridge(core, session, *, continuous: bool = True, claude=None, journal=None, on_mute=None):  # noqa: ANN001
    return RealtimeConversationBridge(
        core=core,
        session=session,
        conversation_id="conv-1",
        audio=SilentAudio(),
        on_addressed=lambda: None,
        on_mute=on_mute or (lambda: None),
        auto_turn=True,
        continuous=continuous,
        journal=journal,
        claude=claude,
    )


async def build_core(tmp_path, backend):  # noqa: ANN001
    state = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await state.initialize()
    conversations = ConversationService(state, JsonlHistoryStore(tmp_path / "history"))
    events = CoreEventBus()
    brain = BrainOrchestrator(conversations=conversations, events=events, backend=backend)
    conversation = await conversations.create()
    return brain, events, state, conversation.id


def drain(queue: asyncio.Queue[ProtocolEnvelope]) -> list[ProtocolEnvelope]:
    collected: list[ProtocolEnvelope] = []
    while True:
        try:
            collected.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            return collected


async def wait_idle(brain: BrainOrchestrator) -> None:
    async def loop() -> None:
        while brain.active_turn_count:
            await asyncio.sleep(0)

    await asyncio.wait_for(loop(), timeout=TIMEOUT_S)


async def serve_agent(handler) -> tuple[ControlCenterBrainBackend, web.AppRunner]:
    app = web.Application()
    app.add_routes([web.post("/api/agent/ask", handler)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    return ControlCenterBrainBackend(base_url=f"http://127.0.0.1:{port}", timeout_s=5), runner


def a_turn(text: str = "Relis mes mails.") -> BrainTurnInput:
    return BrainTurnInput(conversation_id="conv-1", text=text, correlation_id="corr-1")


# --------------------------------------------------------------------------
# L'adaptateur `BrainBackend` : ce que Core appelle à la place de Voice


async def test_the_backend_turns_the_agent_answer_into_result_speech():
    seen: dict = {}

    async def handler(request):
        seen.update(await request.json())
        return web.json_response({"ok": True, "text": "Trois mails attendent une réponse.", "duration_ms": 900})

    backend, runner = await serve_agent(handler)
    sink = RecordingSink()
    try:
        result = await backend.run_turn(a_turn(), None, sink)
    finally:
        await backend.close()
        await runner.cleanup()

    # La route est agent-agnostique : rien dans la requête ne nomme un agent.
    # Le contexte part avec le tour, même sans état (contrat inversé : jusqu'à
    # la Décision 44 l'adaptateur n'envoyait que `text` et `timeout_s`).
    assert seen == {"text": "Relis mes mails.", "timeout_s": 5, "context": {"addressing": "addressed"}}
    assert sink.kinds() == ["accepted", "speech", "completed"]
    speech = sink.events[1].speech
    assert speech.text == "Trois mails attendent une réponse."
    assert speech.kind is SpeechKind.RESULT
    assert result.status is BrainRunStatus.COMPLETED
    assert result.public_summary == "Trois mails attendent une réponse."


async def a_context_seen_by(turn: BrainTurnInput, state: BrainWorkingState | None) -> dict:
    """Faire tourner un tour contre un agent muet et rendre le contexte reçu."""

    seen: dict = {}

    async def handler(request):
        seen.update(await request.json())
        return web.json_response({"ok": True, "text": "fait"})

    backend, runner = await serve_agent(handler)
    try:
        await backend.run_turn(turn, state, RecordingSink())
    finally:
        await backend.close()
        await runner.cleanup()
    return seen["context"]


def a_full_state() -> BrainWorkingState:
    return BrainWorkingState(
        conversation_id="conv-1",
        revision=4,
        current_user_intent="Faire le total des comptes de janvier.",
        conversation_goal="Boucler la compta du mois.",
        active_work_ids=("brain-turn:corr-1",),
        known_public_facts=("Le fichier des comptes est dans le Drive.",),
        unresolved_questions=("Quel mois ?",),
        completed_work_ids=("brain-turn:corr-0",),
    )


async def test_the_public_working_state_travels_with_the_turn():
    """Décision 42 : la continuité ne repose plus sur la seule session de l'agent."""

    state = a_full_state()
    context = await a_context_seen_by(a_turn(), state)

    assert context["state"] == state.to_rehydration_payload()
    assert "Le fichier des comptes est dans le Drive." in context["state"]["known_public_facts"]


async def test_an_uncertain_turn_reaches_the_agent_marked_as_such():
    """Décision 44 : le doute de la surface doit arriver jusqu'à celui qui tranche."""

    turn = BrainTurnInput(
        conversation_id="conv-1",
        text="Regarde dans mon Drive le fichier des comptes de janvier et donne moi le total",
        correlation_id="corr-1",
        addressing=AddressingDecision.UNCERTAIN,
    )
    context = await a_context_seen_by(turn, a_full_state())

    assert context["addressing"] == "uncertain"
    # Un tour normal reste distinguable, sinon la marque ne dit rien.
    assert (await a_context_seen_by(a_turn(), a_full_state()))["addressing"] == "addressed"


async def test_the_context_carries_only_the_public_state_and_nothing_else():
    """Décision 43 : ce qui part est exactement la projection publique de Core."""

    context = await a_context_seen_by(a_turn(), a_full_state())

    assert set(context) == {"addressing", "state"}
    assert set(context["state"]) == set(BrainWorkingState(conversation_id="conv-1").to_rehydration_payload())
    for key in context["state"]:
        assert not any(marker in key.lower() for marker in ("reason", "thought", "thinking", "chain"))


async def test_a_turn_the_agent_judges_not_for_it_is_closed_in_silence():
    """Le cœur de la Décision 44 : conclure « ce n'était pas pour moi » ne se prononce pas."""

    async def handler(request):
        del request
        return web.json_response({"ok": True, "text": f"  {BRAIN_NOT_ADDRESSED_ANSWER}  "})

    backend, runner = await serve_agent(handler)
    sink = RecordingSink()
    turn = BrainTurnInput(
        conversation_id="conv-1",
        text="tu as vu le match hier soir",
        correlation_id="corr-1",
        addressing=AddressingDecision.UNCERTAIN,
    )
    try:
        result = await backend.run_turn(turn, a_full_state(), sink)
    finally:
        await backend.close()
        await runner.cleanup()

    assert sink.kinds() == ["accepted", "completed"]
    assert result.status is BrainRunStatus.COMPLETED
    assert result.public_summary == ""


async def test_the_backend_always_answers_with_the_correlation_of_the_turn():
    """Contrat dur : un résultat mal corrélé est une violation (`backend_correlation_mismatch`)."""

    async def handler(request):
        del request
        return web.json_response({"ok": True, "text": "fait"})

    backend, runner = await serve_agent(handler)
    sink = RecordingSink()
    turn = a_turn()
    try:
        result = await backend.run_turn(turn, None, sink)
    finally:
        await backend.close()
        await runner.cleanup()

    assert result.correlation_id == turn.correlation_id
    assert {event.correlation_id for event in sink.events} == {turn.correlation_id}


async def test_an_agent_failure_becomes_speakable_and_a_stable_token():
    async def handler(request):
        del request
        return web.json_response({"ok": False, "error": "Claude n'a pas répondu à temps.", "code": "claude_timeout"})

    backend, runner = await serve_agent(handler)
    sink = RecordingSink()
    try:
        result = await backend.run_turn(a_turn(), None, sink)
    finally:
        await backend.close()
        await runner.cleanup()

    assert sink.kinds() == ["accepted", "speech", "failed"]
    assert sink.events[1].speech.kind is SpeechKind.ERROR
    assert sink.events[1].speech.text == "Claude n'a pas répondu à temps."
    assert result.status is BrainRunStatus.FAILED
    # Un jeton, pas une histoire : `error_class` classe une panne.
    assert result.error == "claude_timeout"


async def test_an_http_error_from_the_control_center_is_a_stable_token():
    async def handler(request):
        del request
        return web.Response(status=500, text="boom")

    backend, runner = await serve_agent(handler)
    sink = RecordingSink()
    try:
        result = await backend.run_turn(a_turn(), None, sink)
    finally:
        await backend.close()
        await runner.cleanup()

    assert result.status is BrainRunStatus.FAILED
    assert result.error == BACKEND_HTTP_ERROR
    assert "500" in sink.events[1].speech.text


async def test_an_unreachable_control_center_is_reported_not_raised():
    backend = ControlCenterBrainBackend(base_url="http://127.0.0.1:1", timeout_s=2)
    sink = RecordingSink()
    try:
        result = await backend.run_turn(a_turn(), None, sink)
    finally:
        await backend.close()

    assert result.status is BrainRunStatus.FAILED
    assert result.error == BACKEND_UNREACHABLE
    assert "pas joignable" in sink.events[1].speech.text


async def test_a_malformed_agent_answer_still_yields_a_stable_token():
    async def handler(request):
        del request
        return web.json_response({"ok": False})

    backend, runner = await serve_agent(handler)
    sink = RecordingSink()
    try:
        result = await backend.run_turn(a_turn(), None, sink)
    finally:
        await backend.close()
        await runner.cleanup()

    assert result.error == AGENT_TURN_FAILED
    assert sink.events[1].speech.text  # une phrase de repli, jamais un vide


async def test_the_backend_propagates_cancellation_instead_of_swallowing_it():
    """Sans cela, l'arrêt de Core se bloquerait en attendant une tâche qui ne meurt pas."""
    entered = asyncio.Event()
    release = asyncio.Event()

    async def handler(request):
        del request
        entered.set()
        await release.wait()
        return web.json_response({"ok": True, "text": "trop tard"})

    backend, runner = await serve_agent(handler)
    sink = RecordingSink()
    task = asyncio.create_task(backend.run_turn(a_turn(), None, sink))
    try:
        await asyncio.wait_for(entered.wait(), timeout=TIMEOUT_S)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        await backend.close()
        await runner.cleanup()

    # L'annulation n'est ni une panne à publier ni une issue à inventer.
    assert sink.kinds() == ["accepted"]


# --------------------------------------------------------------------------
# Critère 4 : la sortie finale du cerveau est un événement Core


async def test_the_final_answer_of_the_agent_appears_as_a_core_event(tmp_path):
    async def handler(request):
        del request
        return web.json_response({"ok": True, "text": "Notepad est ouvert."})

    backend, runner = await serve_agent(handler)
    brain, events, state, conversation_id = await build_core(tmp_path, backend)
    queue = events.subscribe()
    try:
        await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Ouvre un notepad."))
        await wait_idle(brain)
        published = drain(queue)
    finally:
        await backend.close()
        await runner.cleanup()
        await state.close()

    types = [event.message_type for event in published]
    assert BRAIN_TURN_ACCEPTED == types[0]
    assert BRAIN_WORK_STARTED in types and BRAIN_WORK_COMPLETED in types
    speech = next(event for event in published if event.message_type == BRAIN_SPEECH_REQUESTED)
    assert speech.payload["text"] == "Notepad est ouvert."
    assert speech.payload["provenance"] == "brain.speech"


async def test_a_failed_agent_turn_is_published_as_a_public_error_not_a_crash(tmp_path):
    async def handler(request):
        del request
        return web.json_response({"ok": False, "error": "L'agent s'est arrêté.", "code": "claude_unavailable"})

    backend, runner = await serve_agent(handler)
    brain, events, state, conversation_id = await build_core(tmp_path, backend)
    queue = events.subscribe()
    try:
        await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Ouvre un notepad."))
        await wait_idle(brain)
        published = drain(queue)
    finally:
        await backend.close()
        await runner.cleanup()
        await state.close()

    failures = [event for event in published if event.message_type == BRAIN_WORK_FAILED]
    # Deux portées distinctes et voulues : le travail, puis le tour.
    assert [event.payload["work_id"] is None for event in failures] == [False, True]
    assert {event.payload["error_class"] for event in failures} == {"claude_unavailable"}
    speech = next(event for event in published if event.message_type == BRAIN_SPEECH_REQUESTED)
    assert speech.payload["kind"] == "error"
    assert speech.payload["text"] == "L'agent s'est arrêté."


# --------------------------------------------------------------------------
# Critères 1 et 2 : Voice n'attend plus, et ne tient plus l'appel d'outil ouvert


class NeverAnsweringClaude:
    """Passerelle qui ne rend jamais la main : si le bridge l'appelle, il gèle."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    async def ask(self, request: str) -> dict:
        self.asked.append(request)
        await asyncio.Event().wait()  # pragma: no cover - jamais atteint en continu


async def test_continuous_mode_never_waits_for_claude_inside_the_bridge():
    """Critères 1 et 2 : l'outil rend la main tout de suite, sans agent derrière."""
    claude = NeverAnsweringClaude()
    core = BrainCoreDouble()
    session = QueueSession()
    bridge = make_bridge(core, session, claude=claude)

    running = asyncio.create_task(bridge.run())
    await session.push("realtime.tool_call", call_id="call-1", name=CLAUDE_TOOL, arguments={"request": "ouvre un notepad"})
    await session.stop()
    await asyncio.wait_for(running, timeout=TIMEOUT_S)

    assert claude.asked == [], "le bridge a appelé Claude en mode continu"
    assert session.results[0][1]["code"] == "brain_owns_the_request"
    assert session.results[0][1]["spoken"] == ""
    # L'appel d'outil est refermé : rien ne reste ouvert pour représenter le travail.
    assert bridge.tool_in_flight is False


async def test_legacy_mode_still_routes_the_tool_to_claude():
    """Décision 20 : la migration est réversible, l'ancien chemin fonctionne."""

    class QuickClaude:
        def __init__(self) -> None:
            self.asked: list[str] = []

        async def ask(self, request: str) -> dict:
            self.asked.append(request)
            return {"ok": True, "spoken": "Notepad ouvert."}

    claude = QuickClaude()
    session = QueueSession()
    bridge = make_bridge(BrainCoreDouble(), session, continuous=False, claude=claude)

    running = asyncio.create_task(bridge.run())
    await session.push("realtime.tool_call", call_id="call-1", name=CLAUDE_TOOL, arguments={"request": "ouvre un notepad"})
    await session.stop()
    await asyncio.wait_for(running, timeout=TIMEOUT_S)

    assert claude.asked == ["ouvre un notepad"]
    assert session.results[0][1] == {"ok": True, "spoken": "Notepad ouvert."}


async def test_other_tools_are_refused_not_forwarded_to_core_in_continuous_mode():
    """Décision 34, lecture stricte : la surface n'exécute aucun outil Core.

    Ce test remplace une assertion inverse — « les autres outils partent quand
    même vers Core » — qui datait d'avant la Décision 34 et contredisait le
    catalogue vide : elle laissait la seconde barrière ouverte, alors que la
    première (aucun outil déclaré) ne peut rien contre un nom d'outil inventé ou
    rejoué. Le refus est bruyant : rien n'est exécuté, le fournisseur reçoit une
    erreur d'outil nommée.
    """

    core = BrainCoreDouble()
    session = QueueSession()
    bridge = make_bridge(core, session)

    running = asyncio.create_task(bridge.run())
    await session.push("realtime.tool_call", call_id="call-1", name="reminder_create", arguments={"message": "m"})
    await session.stop()
    await asyncio.wait_for(running, timeout=TIMEOUT_S)

    assert core.tool_calls == []
    result = session.results[0][1]
    assert result["ok"] is False
    assert result["code"] == "surface_tool_forbidden_in_continuous"
    assert result["spoken"] == ""


async def test_legacy_mode_still_routes_other_tools_to_core():
    """Le refus est borné au mode continu : le chemin legacy garde son catalogue."""

    core = BrainCoreDouble()
    session = QueueSession()
    bridge = make_bridge(core, session, continuous=False)

    running = asyncio.create_task(bridge.run())
    await session.push("realtime.tool_call", call_id="call-1", name="reminder_create", arguments={"message": "m"})
    await session.stop()
    await asyncio.wait_for(running, timeout=TIMEOUT_S)

    assert core.tool_calls == ["reminder_create"]


# --------------------------------------------------------------------------
# Décision 30 : la suppression du double chemin est mécanique


async def test_continuous_mode_never_appends_a_user_turn():
    """Décision 30, preuve comportementale.

    Ce test balaie tous les évènements que le bridge traite en mode continu et
    échoue si l'un d'eux persiste un tour utilisateur par `append_turn()`. Ce
    tour-là appartient à `submit_brain_turn()`, qui persiste et dépêche en une
    seule opération : emprunter les deux l'écrirait deux fois.

    **Attente inversée par la Décision 44.** La longue phrase sans préfixe de ce
    scénario est classée `UNCERTAIN` ; ce test attendait auparavant qu'elle soit
    jetée, et n'attendait donc qu'un seul tour cerveau. C'était le contrat
    d'avant la Décision 44 : la surface tranchait l'intention et jetait en
    silence un vrai tour utilisateur. Elle est désormais soumise au cerveau,
    marquée `uncertain`. Ce que ce test prouve — aucun `append_turn(kind="user")`
    en continu — est inchangé.
    """
    core = BrainCoreDouble()
    session = QueueSession()
    journal = RecordingJournal()
    muted = asyncio.Event()
    bridge = make_bridge(core, session, journal=journal, on_mute=muted.set)

    running = asyncio.create_task(bridge.run())
    await session.push("realtime.transcript", text="Jarvis, relis mes mails.", item_id="item-1")
    await session.push("realtime.transcript", text="une conversation ambiante entre plusieurs personnes qui ne le concerne pas du tout")
    await session.push("realtime.input_committed", item_id="item-2")
    await session.push("realtime.assistant_transcript", text="Je m'en occupe.")
    await session.push("realtime.tool_call", call_id="call-1", name=CLAUDE_TOOL, arguments={"request": "relis mes mails"})
    await session.push("realtime.response_done", status="completed")
    await session.push("realtime.transcript", text="Jarvis mute")
    await asyncio.wait_for(running, timeout=TIMEOUT_S)

    assert muted.is_set()
    assert [kind for kind, _metadata in core.appended] == ["assistant"]
    # Le tour assistant est étiqueté : ce que la surface dit d'elle-même est un
    # réflexe, pas la parole du cerveau (spec section 15).
    assert core.appended[0][1] == {"provenance": "surface.reflex"}
    assert [(turn["content"], turn["addressing"]) for turn in core.brain_turns] == [
        ("Jarvis, relis mes mails.", "addressed"),
        ("une conversation ambiante entre plusieurs personnes qui ne le concerne pas du tout", "uncertain"),
    ]


def test_the_user_turn_append_stays_confined_to_the_legacy_helper():
    """Décision 30, preuve structurelle.

    Si un `append_turn(kind="user")` réapparaît ailleurs dans le bridge, ce test
    échoue — y compris sur un chemin qu'aucun scénario ne parcourt encore.
    """
    module = ast.parse(REALTIME_AUDIO.read_text(encoding="utf-8"))
    owners: list[str] = []
    dynamic: list[str] = []
    for node in ast.walk(module):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            if not (isinstance(call.func, ast.Attribute) and call.func.attr == "append_turn"):
                continue
            kinds = [kw.value for kw in call.keywords if kw.arg == "kind"]
            if not kinds or not all(isinstance(value, ast.Constant) for value in kinds):
                # Un `kind` calculé rendrait cette analyse aveugle.
                dynamic.append(node.name)
            elif any(value.value == "user" for value in kinds):
                owners.append(node.name)

    assert dynamic == [], f"append_turn appelé avec un `kind` non littéral dans {dynamic}"
    assert owners == ["_append_legacy_user_turn"], f"un tour utilisateur est persisté hors du chemin legacy: {owners}"


async def test_the_legacy_append_helper_refuses_to_run_in_continuous_mode():
    """Décision 30, garde d'exécution : le double chemin échoue au lieu d'écrire."""
    bridge = make_bridge(BrainCoreDouble(), QueueSession())

    with pytest.raises(RuntimeError, match="continuous_brain"):
        await bridge._append_legacy_user_turn("Relis mes mails.")


async def test_legacy_mode_still_appends_the_user_turn():
    """Le pendant : rien n'a changé pour le mode legacy (Décision 20)."""
    core = BrainCoreDouble()
    session = QueueSession()
    bridge = make_bridge(core, session, continuous=False)

    running = asyncio.create_task(bridge.run())
    await session.push("realtime.transcript", text="Jarvis, quelle heure est-il ?")
    await session.stop()
    await asyncio.wait_for(running, timeout=TIMEOUT_S)

    assert [kind for kind, _metadata in core.appended] == ["user"]
    assert core.brain_turns == []


# --------------------------------------------------------------------------
# Décision 44 : en continu, un tour incertain va au cerveau, pas à la poubelle


#: Une vraie demande, plus de huit mots, sans préfixe d'éveil ni point
#: d'interrogation : `ConservativeAddressingClassifier` la classe `UNCERTAIN`.
UNCERTAIN_REQUEST = "Regarde dans mon Drive le fichier des comptes de janvier et donne moi le total"


async def test_an_uncertain_turn_is_submitted_to_the_brain_in_continuous_mode():
    """Décision 44 : l'intention appartient au cerveau, pas à la surface.

    Avant cette décision, ce tour-là partait vers `on_ambient` et disparaissait
    en silence pendant que la surface répondait quand même. Il est désormais
    soumis, et marqué `uncertain` pour que le cerveau sache d'où vient le doute.
    """
    core = BrainCoreDouble()
    session = QueueSession()
    bridge = make_bridge(core, session)

    running = asyncio.create_task(bridge.run())
    await session.push("realtime.transcript", text=UNCERTAIN_REQUEST, item_id="item-7")
    await session.stop()
    await asyncio.wait_for(running, timeout=TIMEOUT_S)

    assert [(turn["content"], turn["addressing"]) for turn in core.brain_turns] == [
        (UNCERTAIN_REQUEST, "uncertain")
    ]
    # Chemin d'ingress unique : router l'incertain n'ouvre pas un second chemin
    # de persistance (Décision 30).
    assert core.appended == []


async def test_an_uncertain_turn_is_still_dropped_in_legacy_mode():
    """Le mode legacy est hors du périmètre de la Décision 44.

    La surface y possède les outils et répond elle-même : le classifieur y garde
    son rôle d'arbitre, et un tour incertain n'est ni soumis ni persisté.
    """
    core = BrainCoreDouble()
    session = QueueSession()
    bridge = make_bridge(core, session, continuous=False)

    running = asyncio.create_task(bridge.run())
    await session.push("realtime.transcript", text=UNCERTAIN_REQUEST, item_id="item-7")
    await session.stop()
    await asyncio.wait_for(running, timeout=TIMEOUT_S)

    assert core.brain_turns == []
    assert core.appended == []


@pytest.mark.parametrize("continuous", [True, False])
async def test_an_ambient_turn_is_dropped_in_both_modes(continuous):
    """Borne de la Décision 44 : seul `UNCERTAIN` est routé, jamais `AMBIENT`.

    Un transcript vide reste jeté dans les deux modes. La Décision 10 tient : ce
    qui n'est pas une phrase n'entre pas dans le cerveau.
    """
    core = BrainCoreDouble()
    session = QueueSession()
    bridge = make_bridge(core, session, continuous=continuous)

    running = asyncio.create_task(bridge.run())
    await session.push("realtime.transcript", text="   ", item_id="item-8")
    await session.stop()
    await asyncio.wait_for(running, timeout=TIMEOUT_S)

    assert core.brain_turns == []
    assert core.appended == []


async def test_jarvis_mute_still_cuts_the_voice_without_reaching_the_brain():
    """Le mute est reconnu avant tout envoi, et il l'est parce qu'il est adressé.

    « Jarvis mute » commence par « jarvis », donc il est classé `ADDRESSED` et
    ne peut pas tomber dans la branche `UNCERTAIN` ajoutée par la Décision 44 :
    la commande coupe la voix comme avant, sans qu'aucun tour ne parte au
    cerveau.
    """
    core = BrainCoreDouble()
    session = QueueSession()
    muted = asyncio.Event()
    bridge = make_bridge(core, session, on_mute=muted.set)

    running = asyncio.create_task(bridge.run())
    await session.push("realtime.transcript", text="Jarvis mute", item_id="item-9")
    await asyncio.wait_for(running, timeout=TIMEOUT_S)

    assert muted.is_set()
    assert core.brain_turns == []
    assert core.appended == []


async def test_the_uncertainty_marker_travels_all_the_way_to_core(tmp_path):
    """Le doute reste lisible côté Core : backend cerveau et tour persisté.

    Sans cette marque, un tour routé par doute serait indiscernable d'un tour
    explicitement adressé, et le cerveau ne pourrait pas décider s'il est
    concerné — ce que la Décision 44 lui demande précisément de faire.
    """
    seen: list[BrainTurnInput] = []

    class RecordingBackend:
        async def run_turn(self, turn: BrainTurnInput, state, emit) -> BrainTurnResult:  # noqa: ANN001
            del state, emit
            seen.append(turn)
            return BrainTurnResult(correlation_id=turn.correlation_id, status=BrainRunStatus.COMPLETED, public_summary="Lu.")

    brain, _events, state, conversation_id = await build_core(tmp_path, RecordingBackend())

    class CoreThroughBrain(BrainCoreDouble):
        """Le vrai ingress de Core derrière l'interface que le bridge appelle."""

        async def submit_brain_turn(self, conversation_id_, *, content, correlation_id, source="realtime", addressing="addressed", provider_item_id=None, interrupted_speech_id=None):  # noqa: ANN001
            del conversation_id_, source, provider_item_id, interrupted_speech_id
            acceptance = await brain.submit(
                BrainTurnInput(
                    conversation_id=conversation_id,
                    text=content,
                    correlation_id=correlation_id,
                    addressing=AddressingDecision(addressing),
                )
            )
            return acceptance.to_payload()

    session = QueueSession()
    bridge = make_bridge(CoreThroughBrain(), session)
    bridge.conversation_id = conversation_id

    running = asyncio.create_task(bridge.run())
    await session.push("realtime.transcript", text=UNCERTAIN_REQUEST, item_id="item-10")
    await session.stop()
    await asyncio.wait_for(running, timeout=TIMEOUT_S)
    await wait_idle(brain)

    assert [turn.addressing for turn in seen] == [AddressingDecision.UNCERTAIN]
    stored = await state.list_turns(conversation_id)
    assert [turn.metadata["addressing"] for turn in stored] == ["uncertain"]
    await state.close()


def test_an_ambient_turn_is_refused_by_the_brain_ingress_itself():
    """La borne de la Décision 44 est mécanique, pas seulement documentaire.

    Même si une surface future tentait de router de l'ambiant, le domaine
    refuserait le tour avant toute écriture.
    """
    with pytest.raises(ValueError, match="ambient"):
        BrainTurnInput(conversation_id="conv-1", text="bruit de fond", addressing=AddressingDecision.AMBIENT)


async def test_the_undelivered_answer_rescue_is_disabled_in_continuous_mode():
    """La réponse n'a jamais transité par Voice : il n'y a plus rien à sauver.

    Garder le sauvetage écrirait dans la conversation une réponse que Core y
    écrit déjà — la seconde écriture que la Décision 06 interdit.
    """
    core = BrainCoreDouble()
    bridge = make_bridge(core, QueueSession())
    bridge._undelivered_answer = "une réponse d'un autre temps"

    await bridge._rescue_undelivered_answer()

    assert core.appended == []


# --------------------------------------------------------------------------
# Corrélation : stable, donc réellement déduplicable par Core


def test_the_same_provider_item_always_yields_the_same_correlation_id():
    """Décision 24 : sans stabilité, la déduplication de Core ne sert à rien.

    Un rejeu du même élément Realtime — après une reconnexion, par exemple —
    doit retomber sur la même corrélation, sinon Core y voit deux tours.
    """
    bridge = make_bridge(BrainCoreDouble(), QueueSession())

    first = bridge._brain_correlation_id("item_42")
    second = bridge._brain_correlation_id("item_42")

    assert first == second == "realtime:conv-1:item_42"
    assert bridge._brain_correlation_id("item_43") != first


def test_a_turn_without_a_provider_item_gets_its_own_correlation_id():
    """Deux « oui » successifs sont deux tours : les confondre serait pire."""
    bridge = make_bridge(BrainCoreDouble(), QueueSession())

    assert bridge._brain_correlation_id(None) != bridge._brain_correlation_id(None)


async def test_the_submitted_turn_carries_the_provider_item_as_a_secondary_key():
    core = BrainCoreDouble()
    session = QueueSession()
    bridge = make_bridge(core, session)

    running = asyncio.create_task(bridge.run())
    await session.push("realtime.transcript", text="Jarvis, relis mes mails.", item_id="item_42")
    await session.stop()
    await asyncio.wait_for(running, timeout=TIMEOUT_S)

    assert core.brain_turns == [
        {
            "conversation_id": "conv-1",
            "content": "Jarvis, relis mes mails.",
            "correlation_id": "realtime:conv-1:item_42",
            "source": "realtime",
            # Un tour préfixé « Jarvis » ne laisse aucun doute : la marque
            # d'adressage vaut `addressed` (Décision 44).
            "addressing": "addressed",
            "provider_item_id": "item_42",
        }
    ]


# --------------------------------------------------------------------------
# Sémantique d'erreur de l'ingress


async def _submit_and_trace(core) -> RecordingJournal:  # noqa: ANN001
    session = QueueSession()
    journal = RecordingJournal()
    bridge = make_bridge(core, session, journal=journal)
    running = asyncio.create_task(bridge.run())
    await session.push("realtime.transcript", text="Jarvis, relis mes mails.", item_id="item-1")
    await session.stop()
    await asyncio.wait_for(running, timeout=TIMEOUT_S)
    return journal


async def test_a_core_shutdown_defers_the_turn_without_killing_the_voice_session():
    """503 : le tour est perdu, la session vocale survit, et la trace le dit."""
    journal = await _submit_and_trace(BrainCoreDouble(reject=CoreProtocolError(503, "core_stopping", "arrêt en cours")))

    deferred = journal.of("voice.brain_turn_deferred")
    assert len(deferred) == 1
    assert deferred[0]["level"] == "warning"
    assert deferred[0]["data"]["code"] == "core_stopping"
    # La corrélation reste déterministe : un rejeu du même élément serait
    # reconnu par un Core revenu à la vie.
    assert deferred[0]["data"]["correlation_id"] == "realtime:conv-1:item-1"
    assert journal.of("voice.brain_turn_rejected") == []


async def test_an_unknown_conversation_is_reported_as_an_error():
    journal = await _submit_and_trace(BrainCoreDouble(reject=CoreProtocolError(404, "not_found", "conversation inconnue")))

    rejected = journal.of("voice.brain_turn_rejected")
    assert len(rejected) == 1
    assert rejected[0]["level"] == "error"
    assert rejected[0]["data"]["status"] == 404


async def test_a_transport_failure_towards_core_is_traced_not_swallowed():
    journal = await _submit_and_trace(BrainCoreDouble(reject=OSError("connexion refusée")))

    rejected = journal.of("voice.brain_turn_rejected")
    assert rejected[0]["data"]["code"] == "brain_turn_transport_error"
    assert "connexion refusée" in str(rejected[0]["message"])


async def test_a_duplicate_is_not_an_error():
    """200 + `duplicate=true` : Core a reconnu un rejeu, rien n'a été redépêché."""
    journal = await _submit_and_trace(BrainCoreDouble(duplicate=True))

    submitted = journal.of("voice.brain_turn_submitted")
    assert len(submitted) == 1
    assert submitted[0]["level"] == "info"
    assert submitted[0]["data"]["duplicate"] is True


# --------------------------------------------------------------------------
# Décision 11 et critère 3 : `Jarvis Mute` ne perd plus le travail du cerveau


async def test_jarvis_mute_does_not_lose_the_work_of_the_brain(tmp_path):
    """Décision 11, le gain de cette tâche.

    Avant la migration, l'appel au modèle fort vivait dans la tâche du bridge :
    couper la voix annulait le travail, et le résultat n'avait plus où revenir.
    Ici le travail appartient à Core. Le bridge est coupé — muté, puis annulé,
    la forme la plus dure du `mute()` du runtime — et le tour continue, puis
    rend sa réponse sous forme d'événement Core.
    """
    backend = SlowBackend()
    brain, events, state, conversation_id = await build_core(tmp_path, backend)
    queue = events.subscribe()

    class CoreThroughBrain(BrainCoreDouble):
        async def submit_brain_turn(self, conversation_id_, *, content, correlation_id, source="realtime", addressing="addressed", provider_item_id=None, interrupted_speech_id=None):  # noqa: ANN001
            del conversation_id_, source, provider_item_id, interrupted_speech_id
            acceptance = await brain.submit(
                BrainTurnInput(
                    conversation_id=conversation_id,
                    text=content,
                    correlation_id=correlation_id,
                    addressing=AddressingDecision(addressing),
                )
            )
            return acceptance.to_payload()

    session = QueueSession()
    muted = asyncio.Event()
    bridge = make_bridge(CoreThroughBrain(), session, on_mute=muted.set)
    bridge.conversation_id = conversation_id

    running = asyncio.create_task(bridge.run())
    try:
        await session.push("realtime.transcript", text="Jarvis, relis mes mails.", item_id="item-1")
        await asyncio.wait_for(backend.started.wait(), timeout=TIMEOUT_S)

        await session.push("realtime.transcript", text="Jarvis mute")
        await asyncio.wait_for(muted.wait(), timeout=TIMEOUT_S)
        # Le runtime annule la tâche du bridge au mute : on reproduit exactement ça.
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)

        # Le travail n'a été ni annulé ni perdu : il est toujours à Core.
        assert backend.cancelled == []
        assert brain.active_turn_count == 1

        backend.release.set()
        await wait_idle(brain)
    finally:
        await brain.stop()
        await state.close()

    published = drain(queue)
    speech = next(event for event in published if event.message_type == BRAIN_SPEECH_REQUESTED)
    assert speech.payload["text"] == "J'ai relu tes mails : trois attendent une réponse."
    assert speech.conversation_id == conversation_id


# --------------------------------------------------------------------------
# Le câblage : c'est le composition root qui construit l'adaptateur


def test_the_composition_root_builds_the_control_center_backend(monkeypatch):
    """Décision 28 : l'adaptateur réel se construit dans `jarvis/app.py`."""
    from jarvis.app import _brain_backend_from_env

    monkeypatch.setenv("JARVIS_UI_PORT", "18888")
    monkeypatch.setenv("JARVIS_BRAIN_TIMEOUT_S", "42")
    backend = _brain_backend_from_env()

    assert isinstance(backend, ControlCenterBrainBackend)
    assert backend.base_url == "http://127.0.0.1:18888"
    assert backend.timeout_s == 42.0


def test_core_never_imports_the_brain_adapter():
    """Décision 28 : le coeur ne connaît que le port, jamais l'adaptateur.

    Doublon volontaire du gate d'architecture : celui-ci nomme l'adaptateur
    introduit par cette tâche, et échoue donc explicitement si une tâche
    ultérieure le câble dans `jarvis/core`.
    """
    core = Path(__file__).resolve().parents[2] / "jarvis" / "core"
    for path in core.glob("*.py"):
        assert "control_center_brain" not in path.read_text(encoding="utf-8"), path

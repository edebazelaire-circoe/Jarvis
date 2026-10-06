"""A composed PRESENTATION rig for the Slice 11 scenario suite; never used by production.

Everything that decides is real: `PresentationComposition` → `PresentationCoordinator`
(mode follower wiring as in `voice_v2`), the `RealtimeConversationBridge`, the
`SpeechScheduler` and its gate, the `RuntimeJournal`, a real
`ConversationEventForwarder` draining into a real SQLite Conversation Event
store, the `VisualSignalBus` status file and the staged-object ledger.

The doubles are the edges only:

- Core (`ScenarioCore`): the scheduler's event stream plus the brain-turn
  intake; an optional brain double answers each turn;
- transcription (`ScriptedTranscriber`) and the capture device;
- the CLI sub-agent of a preparation (`FakeCliAgent`): it records its `cwd`
  and its tools, may block, and leaves a scratch file in its cwd so that the
  workspace removal is observable;
- the scene tools (`FakeSceneTools`, spec'd on `SceneDisplayTools`).

No microphone, no network, no model.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Awaitable, Callable

from jarvis.domain.interaction_mode import InteractionMode
from jarvis.domain.v2 import ProtocolEnvelope, SpeechKind, SpeechPriority, SpeechRequest, utc_now
from jarvis.runtime.conversation_event_forwarder import ConversationEventForwarder
from jarvis.runtime.interaction_mode_observer import InteractionModeObserver, follow_core_mode
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.presentation_runtime import (
    PresentationComposition,
    PresentationCoordinator,
    PresentationWakeRouter,
)
from jarvis.runtime.presentation_timeline import PresentationTimeline
from jarvis.runtime.realtime_audio import RealtimeConversationBridge
from jarvis.runtime.speech_scheduler import SpeechScheduler
from jarvis.runtime.visual_signals import VisualSignalBus
from tests.fakes.conversation_events import open_store
from tests.fakes.speech_context import context as speech_context, source as speech_source
from tests.unit.test_ambient_ingestion_lane import FakeCaptureDevice, feed, silence, speech, until
from tests.unit.test_presentation_integration import FakeManualKey, FakeSceneTools, FakeSimpleWake
from tests.unit.test_v2_brain_migration import QueueSession, SilentAudio
from tests.unit.test_v2_speech_scheduler import FakeCore, FakeVoiceSession

CONVERSATION = "conv-scenario"
HUB_RATE = 24000
LIFE = "life-scenario"


class ScriptedTranscriber:
    """The ambient transcription: returns the next scripted sentence, in order."""

    def __init__(self) -> None:
        self.queue: list[str] = []
        self.calls = 0

    def say_next(self, text: str) -> None:
        self.queue.append(text)

    async def transcribe(self, audio: Any) -> Any:
        del audio
        self.calls += 1
        text = self.queue.pop(0) if self.queue else "euh"
        return SimpleNamespace(text=text, duration_ms=900, provider="fake", model="fake")


class FakeCliAgent:
    """The preparation sub-agent (`ClaudeLocalAgent` shape), without a process.

    It writes the prompt it was given into a scratch file **inside its cwd**,
    as a real CLI could; the workspace must remove it at job end.
    """

    def __init__(self, tools: tuple[str, ...], cwd: Path | None, *, factory: "AgentFactory") -> None:
        self.tools = tuple(tools)
        self.cwd = cwd
        self.factory = factory
        self.gate = factory.gate
        self.asked: list[str] = []
        self.cwd_was_empty: bool | None = None
        self.closed = 0
        self.cancelled = False

    async def start(self, *, resume: bool = True) -> dict:
        del resume
        return {"ok": True}

    async def ask(self, text: str, *, timeout_s: float = 180.0, **kwargs: Any) -> dict:
        del timeout_s, kwargs
        self.asked.append(text)
        if self.cwd is not None:
            self.cwd_was_empty = not any(self.cwd.iterdir())
            (self.cwd / "scratch.txt").write_text(text, encoding="utf-8")
        if self.gate is not None:
            try:
                await self.gate.wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        return {"ok": True, "text": self.factory.answer_for(text), "code": None}

    async def close_owned(self) -> bool:
        self.closed += 1
        return True


_CLAIM_ID = re.compile(r"- id=(\S+) claim=")


class AgentFactory:
    """`agent_factory(tools, cwd)` as the production composition root calls it."""

    def __init__(self) -> None:
        self.agents: list[FakeCliAgent] = []
        #: Findings every job returns.
        self.findings: list[dict[str, str]] = []
        #: `(verdict, confidence)` given to every offered claim, or None.
        self.assess: tuple[str, float] | None = None
        #: The verdict's reason, as the model would word it.
        self.reason = "le rapport INSEE 2025 donne une autre valeur"
        #: When set, every new job blocks on it (a "running" preparation).
        self.gate: asyncio.Event | None = None

    def answer_for(self, prompt: str) -> str:
        payload: dict[str, Any] = {"findings": list(self.findings)}
        if self.assess is not None:
            verdict, confidence = self.assess
            payload["assessments"] = [
                {"id": claim_id, "verdict": verdict, "confidence": confidence,
                 "source": "https://example.org/insee-2025", "title": "INSEE 2025",
                 "reason": self.reason}
                for claim_id in _CLAIM_ID.findall(prompt)
            ]
        return json.dumps(payload)

    def __call__(self, tools: tuple[str, ...], cwd: Path | None = None) -> FakeCliAgent:
        agent = FakeCliAgent(tools, cwd, factory=self)
        self.agents.append(agent)
        return agent


class StoreTransport:
    """The forwarder's transport, appending into the real SQLite event store.

    Only the HTTP hop to Core is skipped; validation and persistence are Core's.
    """

    def __init__(self, store: Any) -> None:
        self.store = store

    async def post(self, events: Any) -> Any:
        return await self.store.append_many(tuple(events))

    async def close(self) -> None:
        return None


BrainDouble = Callable[["Rig", dict[str, Any]], Awaitable[None]]


class ScenarioCore(FakeCore):
    """Core as both Voice components see it: event stream + brain-turn intake."""

    def __init__(self, *, mode: InteractionMode = InteractionMode.ASSISTANT, epoch: str = LIFE) -> None:
        super().__init__()
        self.brain_turns: list[dict[str, Any]] = []
        self.brain: BrainDouble | None = None
        self.rig: Rig | None = None
        self.mode_state: dict[str, Any] = {"mode": mode.value, "revision": 0, "epoch": epoch}

    async def interaction_mode(self) -> dict[str, Any]:
        return dict(self.mode_state)

    async def set_interaction_mode(self, mode: str, *, source: str | None = None) -> dict[str, Any]:
        """Core's mode service: new revision, then `interaction.mode.changed` on the bus."""

        del source
        self.mode_state = {**self.mode_state, "mode": mode, "revision": self.mode_state["revision"] + 1}
        await self.publish(ProtocolEnvelope("interaction.mode.changed", dict(self.mode_state)))
        return dict(self.mode_state)

    async def submit_brain_turn(  # noqa: PLR0913
        self, conversation_id: str, *, content: str, correlation_id: str, source: str = "realtime",
        addressing: str = "addressed", provider_item_id: str | None = None,
        interrupted_speech_id: str | None = None, presentation_context: dict | None = None,
    ) -> dict:
        del interrupted_speech_id
        record = {"conversation_id": conversation_id, "content": content, "correlation_id": correlation_id,
                  "source": source, "addressing": addressing, "provider_item_id": provider_item_id,
                  "presentation_context": presentation_context}
        self.brain_turns.append(record)
        if self.brain is not None and self.rig is not None:
            # The brain answers after Core accepted the turn, never inside the request.
            asyncio.get_running_loop().create_task(self.brain(self.rig, record))
        return {"turn_id": f"turn-{len(self.brain_turns)}", "correlation_id": correlation_id,
                "revision": len(self.brain_turns), "duplicate": False}


def brain_speech(conversation_id: str, correlation_id: str, text: str, kind: SpeechKind, *,
                 epoch: int = 1) -> ProtocolEnvelope:
    """A `brain.speech.requested` envelope dated now, from the turn's own source."""

    now = utc_now()
    request = SpeechRequest(
        conversation_id=conversation_id, text=text, kind=kind, priority=SpeechPriority.NORMAL,
        id=f"speech-{correlation_id[-12:]}-{kind.value}", correlation_id=correlation_id,
        created_at=now, source=speech_source(correlation_id, epoch=epoch),
    )
    return ProtocolEnvelope(message_type="brain.speech.requested", payload=request.to_payload(),
                            correlation_id=correlation_id, conversation_id=conversation_id)


@dataclasses.dataclass
class Rig:
    root: Path
    runtime: Path
    data: Path
    journal: RuntimeJournal
    state: Any
    events: Any
    forwarder: ConversationEventForwarder
    observer: InteractionModeObserver
    coordinator: PresentationCoordinator
    composition: PresentationComposition
    scheduler: SpeechScheduler
    session: FakeVoiceSession
    bridge: RealtimeConversationBridge
    core: Any
    scene: FakeSceneTools
    device: FakeCaptureDevice
    manual: FakeManualKey
    transcriber: ScriptedTranscriber
    agents: AgentFactory
    router: PresentationWakeRouter
    simple: FakeSimpleWake
    calls: dict[str, int]
    follower: Any = None
    intent_epoch: int = 1
    _detections: Any = None
    _items: int = 0

    # -- mode ---------------------------------------------------------------

    async def set_mode(self, mode: InteractionMode) -> None:
        """Core changes the mode; the P1 follower adopts it; the coordinator applies it in one drain."""

        await self.core.set_interaction_mode(mode.value, source="test")
        await until(lambda: self.observer.mode is mode, timeout=5.0)
        await self.settle()

    async def settle(self) -> None:
        task = self.coordinator._applying
        if task is not None:
            await task

    @property
    def stack(self) -> Any:
        return self.coordinator.stack

    # -- the room -----------------------------------------------------------

    async def room(self, text: str, *, realtime_too: bool = True) -> None:
        """Somebody speaks in the room: the ambient lane hears it, and so does the realtime model."""

        stack = self.stack
        before = len(stack.store.snapshot.tail.entries) if stack is not None else 0
        self.transcriber.say_next(text)
        await feed(self.device, speech(900))
        await feed(self.device, silence(900))
        if stack is not None:
            await until(lambda: len(stack.store.snapshot.tail.entries) > before, timeout=5.0)
            # The tail is written **before** enrichment (HD5): wait for the
            # analysis too, so that its triggers are admitted before the caller
            # drains the speculative lane.
            await until(lambda: not stack.ambient.stats()["analysis_pending"]
                        and not stack.ambient.stats()["segments_pending"], timeout=5.0)
            await asyncio.sleep(0)
        if realtime_too:
            await self.hear(text)

    async def hear(self, text: str) -> bool:
        """A final transcript from the realtime session reaches the bridge."""

        self._items += 1
        return await self.bridge._handle_transcript(ProtocolEnvelope(
            "realtime.transcript", {"text": text, "item_id": f"item_{self._items:03d}"}))

    async def press(self) -> None:
        """The manual key: the live lane arms the addressed window, the runtime keeps the session."""

        if self._detections is None:
            self._detections = self.router.detections()
        self.manual.press()
        await asyncio.wait_for(anext(self._detections), 2.0)

    async def addressed(self, text: str) -> dict[str, Any] | None:
        """Press the key, say the sentence; return the brain turn it produced, if any."""

        await self.press()
        turns = getattr(self.core, "brain_turns", None)   # a real Core client keeps no record
        count = len(turns) if turns is not None else 0
        await self.hear(text)
        await self.quiesce()
        return turns[-1] if turns is not None and len(turns) > count else None

    async def quiesce(self) -> None:
        """Let detached delivery tasks and brain doubles finish."""

        for _ in range(5):
            await asyncio.sleep(0.01)
            pending = list(self.scheduler._addressed_tasks)
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

    # -- brain double helpers ------------------------------------------------

    async def brain_says(self, correlation_id: str, text: str, kind: SpeechKind = SpeechKind.RESULT) -> None:
        # Each brain turn is a new Core intent: its epoch only grows.
        self.intent_epoch += 1
        conversation = self.bridge.conversation_id
        self.scheduler.update_speech_context(speech_context(conversation, correlation_id, epoch=self.intent_epoch))
        await self.core.publish(brain_speech(conversation, correlation_id, text, kind, epoch=self.intent_epoch))

    # -- evidence ------------------------------------------------------------

    def trace(self) -> list[dict[str, Any]]:
        if not self.journal.trace_path.exists():
            return []
        return [json.loads(line) for line in self.journal.trace_path.read_text(encoding="utf-8").splitlines()]

    def kinds(self) -> list[str]:
        return [line["kind"] for line in self.trace()]

    def codes(self) -> list[str]:
        return [str(line.get("data", {}).get("code")) for line in self.trace() if line.get("data", {}).get("code")]

    async def stored_events(self) -> list[Any]:
        await self.forwarder.flush()
        page = await self.events.list_conversation_events(self.bridge.conversation_id, limit=500)
        return [item.event for item in page.events]

    async def close(self) -> None:
        if self._detections is not None:
            await self._detections.aclose()
        await self.scheduler.stop()
        if self.follower is not None:
            self.follower.cancel()
            await asyncio.gather(self.follower, return_exceptions=True)
        await self.coordinator.aclose("test_closed")
        await self.forwarder.flush()
        if self.state is not None:
            await self.state.close()


async def build_rig(root: Path, *, mode: InteractionMode = InteractionMode.ASSISTANT,
                    pool: int | None = None, reserved: int | None = None,
                    core: Any | None = None, conversation_id: str = CONVERSATION,
                    events_transport: Any | None = None) -> Rig:
    """Compose the whole PRESENTATION path the way `jarvis/app.py` and `voice_v2` do."""

    runtime = root / "runtime"
    data = root / "data"
    runtime.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    journal = RuntimeJournal(runtime)
    if events_transport is None:
        state, events = await open_store(data / "jarvis.sqlite3", diagnostics=journal)
        events_transport = StoreTransport(events)
    else:
        state = events = None
    forwarder = ConversationEventForwarder(transport=events_transport, journal=journal)
    timeline = PresentationTimeline(recorder=forwarder, conversation_id=lambda: conversation_id)
    observer = InteractionModeObserver(journal=journal)
    device, manual, scene = FakeCaptureDevice(), FakeManualKey(), FakeSceneTools()
    transcriber, agents = ScriptedTranscriber(), AgentFactory()
    extra: dict[str, Any] = {}
    if pool is not None:
        extra["speculative_pool"] = pool
    if reserved is not None:
        extra["reserved_explicit_slots"] = reserved
    composition = PresentationComposition(
        runtime_root=runtime, cwd=root, journal=journal, mode=lambda: observer.mode,
        transcriber=transcriber, scene_tools_factory=lambda: scene, agent_factory=agents,
        stream_factory=device.factory, manual_backend_factory=lambda: manual, sample_rate=HUB_RATE,
        preparation_root=data / "presentation" / "prep", timeline=timeline, **extra,
    )
    simple = FakeSimpleWake(owns_device=True)
    router = PresentationWakeRouter(simple=simple, journal=journal)
    coordinator = PresentationCoordinator(
        router=router, build=composition.build, journal=journal, signals=VisualSignalBus(runtime),
        reclaimer=composition.reclaimer(), timeline=timeline,
    )
    observer.add_listener(coordinator.observe_mode)
    session = FakeVoiceSession()
    scenario_core = ScenarioCore(mode=mode) if core is None else None
    core = scenario_core if core is None else core

    def turns() -> Any:
        return coordinator.turns

    scheduler = SpeechScheduler(
        core=core, conversation_id=conversation_id, session=session, journal=journal,
        reconnect_delay_s=0.0, output_timeout_s=5.0, conversation_events=forwarder,
        interaction_mode=observer, presentation_turns=turns,
    )
    scheduler.update_speech_context(speech_context(conversation_id))
    calls = {"addressed": 0, "ambient": 0, "mute": 0}

    def count(name: str) -> Callable[[], None]:
        def bump() -> None:
            calls[name] += 1
        return bump

    bridge = RealtimeConversationBridge(
        core=core, session=QueueSession(), conversation_id=conversation_id, audio=SilentAudio(),
        on_addressed=count("addressed"), on_ambient=count("ambient"), on_mute=count("mute"),
        continuous=True, auto_turn=True, journal=journal,
        on_addressed_turn=scheduler.note_addressed_turn, conversation_events=forwarder,
        presentation_turns=turns,
    )
    # Not engaged: the room is not a follow-up of a fresh JARVIS answer.
    bridge._last_engaged = -1e9
    rig = Rig(root=root, runtime=runtime, data=data, journal=journal, state=state, events=events,
              forwarder=forwarder, observer=observer, coordinator=coordinator, composition=composition,
              scheduler=scheduler, session=session, bridge=bridge, core=core, scene=scene, device=device,
              manual=manual, transcriber=transcriber, agents=agents, router=router, simple=simple,
              calls=calls)
    if scenario_core is not None:
        scenario_core.rig = rig
    await coordinator.reclaim_orphans()
    # P1: the process-lifetime follower adopts Core's snapshot at subscription,
    # so a Voice started while Core is in PRESENTATION enters it with no wake.
    rig.follower = asyncio.get_running_loop().create_task(
        follow_core_mode(observer, core, journal), name="scenario-mode-follower")
    await scheduler.start()
    await until(lambda: observer.mode is mode, timeout=5.0)
    await rig.settle()
    return rig

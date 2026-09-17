"""Asynchronous conversation harness: the stack of the Test Lab `virtual` profile.

This module contains no test. It mounts, in memory and off the network, the whole
stack that the scenarios of `test_v2_async_conversation.py` put under strain and
that the Test Lab `virtual` profile executes.

It used to live in `tests/integration/async_conversation_harness.py`, which is now
only a re-export: the `virtual` profile is product code, and product code may not
import `tests.` (READINESS B4.1). The one signature difference is the second
parameter, which is no longer necessarily pytest's `monkeypatch` but any
`AttributePatcher` - `monkeypatch` is one, and `PatchStack` is one that does not
depend on pytest.

    fake microphone -> RealtimeConversationBridge -> LocalCoreClient
        -> HTTP loopback -> LocalProtocolServer -> JarvisCoreApplication
        -> BrainOrchestrator -> scripted brain backend
        -> /v1/events (a real websocket) -> SpeechScheduler -> fake session

Five points are doubles, and only these five. The first three are exactly the ones
Decision 20 and spec section 11 reserve for workstation acceptance; the last two are
what the Test Lab needs so a diagnostic can drive a session and be judged on the
stack's own acoustic reasoning:

- the **Realtime session**, replaced by `FakeRealtimeSession`, which speaks the
  bridge's provider-neutral event vocabulary and returns an output id from `speak()`;
- the **audio device**, replaced by `FakeAudio`, which keeps every bit of
  `SoundDeviceRealtimeAudio`'s playback accounting but opens no PortAudio stream;
- the **strong model**, replaced by `ScriptedBrainBackend`, which never returns
  until the caller decides it does;
- the **wake word**, replaced by `FakeWakeWord`, which yields the keyword the
  caller pushes;
- the **duplex capture**, replaced by `VirtualEchoGuard` when a caller passes one
  through `capture_factory`. The Test Lab does; the pytest tests do not, and then
  there is no echo guard at all, which is the historical behaviour.

Everything else is production code: the local HTTP/WebSocket protocol,
`BrainOrchestrator`, `SpeechScheduler`, `PersistentVoiceRuntime` and the bridge.

Determinism
-----------
No `sleep` is ever a synchronization. Callers advance on events:
`ScriptedBrainBackend.next_turn()` waits on a queue, `RecordingJournal.wait_until`
waits for a journalled milestone, and `wait_until()` is a bounded condition wait -
never a fixed pause meant to "give it time".
"""

from __future__ import annotations

import asyncio
import base64
import socket
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from aiohttp import web

import jarvis.protocol.server as protocol_server
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.v2 import (
    BrainEvent,
    BrainEventKind,
    BrainRunStatus,
    BrainTurnInput,
    BrainTurnResult,
    BrainWorkingState,
    PlaybackCursor,
    ProtocolEnvelope,
    SpeechKind,
    SpeechPriority,
    SpeechRequest,
    VoiceLifecycleState,
    utc_now,
)
from jarvis.domain.speech_presentation import SpeechSource
from jarvis.protocol.client import LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime.realtime_audio import SoundDeviceRealtimeAudio
from jarvis.runtime.speech_scheduler import SpeechScheduler
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
from jarvis.testlab.virtual.devices import BufferedOutputStream
from jarvis.testlab.virtual.patching import AttributePatcher
from jarvis.v2_config import VoiceArchitecture

TOKEN = "i" * 48

# Generous on purpose: these scenarios cross a real loopback websocket. The
# timeout is never a real wait - it only exists to fail a blocked test rather than
# suspend it forever. Raised from 10 s to 30 s in Slice 06: under load this host
# failed correct scenarios on that wall clock, never on an assertion
# (`tasks/jarvis-category2-test-lab/Issues/voice-harness-wall-clock-flake-under-load.md`).
# No proven sequence changes; only the delay after which a genuinely blocked test
# gives up gets longer. Test Lab runs do not depend on this constant at all: their
# waits are bounded by `RunContext.remaining_s`.
TIMEOUT_S = 30.0

# The speech scheduler's reconnection delay, brought down to an imperceptible value.
# The production value (2 s) is not a business rule: it is a runaway guard. Shortening
# it speeds the run up without changing any proven sequence.
FAST_RECONNECT_DELAY_S = 0.05


class FastShutdownRunner(web.AppRunner):
    """An `AppRunner` that does not wait for an open websocket to end.

    aiohttp's shutdown timeout is sixty seconds, so a still-connected `/v1/events`
    subscriber would make every server stop last a minute, including the deliberate
    cut of the reconnection scenario. That timeout is not a Jarvis contract -
    production keeps its own.
    """

    def __init__(self, app, **kwargs) -> None:  # noqa: ANN001
        kwargs.setdefault("shutdown_timeout", 0.05)
        super().__init__(app, **kwargs)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def wait_until(predicate, *, timeout: float = TIMEOUT_S, message: str = "") -> None:
    """Wait for a condition, without assuming how many loop turns it takes."""

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        if predicate():
            return
        if loop.time() >= deadline:
            raise AssertionError(f"condition never reached: {message or predicate}")
        await asyncio.sleep(0.005)


# ---------------------------------------------------------------------------
# Infrastructure doubles
# ---------------------------------------------------------------------------


class FakeClock:
    """Driven clock: the same shape as in the continuous-mode unit tests."""

    def __init__(self) -> None:
        self.value = utc_now()

    def now(self) -> datetime:
        return self.value

    async def sleep(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


class RecordingJournal:
    """In-memory `RuntimeJournal` (Decision 27: the journal is the observability medium)."""

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.changed = asyncio.Event()

    def emit(self, kind: str, message: str, *, level: str = "info", data=None) -> None:  # noqa: ANN001
        self.events.append({"kind": kind, "message": message, "level": level, "data": data or {}})
        self.changed.set()

    def count(self, kind: str) -> int:
        return sum(1 for event in self.events if event["kind"] == kind)

    def of(self, kind: str) -> list[dict[str, object]]:
        return [event for event in self.events if event["kind"] == kind]

    async def wait_until(self, predicate, *, timeout: float = TIMEOUT_S) -> None:
        """Wait for a milestone to be journalled, without sleeping in real time.

        The deadline is **global**, not reset on each event: a reconnection loop that
        journals relentlessly would otherwise make the caller wait forever for a
        milestone that will never come.
        """

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            self.changed.clear()
            if predicate():
                return
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise AssertionError(f"milestone never journalled: {predicate}")
            await asyncio.wait_for(self.changed.wait(), timeout=remaining)


class RecordingSignals:
    def __init__(self) -> None:
        self.states: list[str] = []
        self.alerts: list[str | None] = []

    def state(self, value: str) -> None:
        self.states.append(value)

    def alert(self, message: str | None) -> None:
        self.alerts.append(message)

    def heartbeat(self) -> None:
        return None

    def offline(self) -> None:
        return None


class FakeWakeWord:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.suspensions = 0
        self.resumptions = 0
        self.closed = False

    async def detections(self):
        while not self.closed:
            yield await self.queue.get()

    async def suspend(self) -> None:
        return None

    async def suspend_for_active_session(self) -> None:
        self.suspensions += 1

    async def resume(self) -> None:
        self.resumptions += 1

    async def close(self) -> None:
        self.closed = True


class ImmediateOutputStream(BufferedOutputStream):
    """Test device that consumes each successful native write immediately."""

    latency = 0.0

    def write(self, pcm):
        super().write(pcm)
        self.consume()


class FakeAudio(SoundDeviceRealtimeAudio):
    """Controlled native device, production guarded writer and byte accounting.

    Task08 migration: both play_b64 and play_b64_guarded now use the real
    SoundDevice writer. The native stream consumes immediately, without physical
    hardware. This tests admission, epochs and interruption cursors, not acoustic
    timing or canonical full-transcript evidence. The historical session double
    still exercises its existing compatibility-history contract.
    """

    instances: list["FakeAudio"] = []
    pcm = b"\x01\x00" * 2400

    def __init__(self, *, input_device=None, output_device=None, **rates) -> None:  # noqa: ANN001
        super().__init__(input_device=input_device, output_device=output_device, **rates)
        self.stop_output_calls = 0
        self.stop_input_calls = 0
        self.closed = False
        self._output = ImmediateOutputStream()
        self.__class__.instances.append(self)

    async def start(self) -> None:
        self._enqueue(self.pcm)

    async def stop_input(self) -> None:
        self.stop_input_calls += 1
        await super().stop_input()

    async def stop_output(self) -> bool:
        self.stop_output_calls += 1
        return await super().stop_output()

    # Both ordinary and guarded playback run through the production writer.
    # Only the native stream is controlled; admission/epochs/accounting are real.
    async def close(self) -> bool:
        result = await super().close()
        self.closed = bool(result)
        return result


def audio_chunk_b64(chunks: int = 1) -> str:
    """A PCM block of known duration: one output block is 100 ms at 24 kHz."""

    frames = SoundDeviceRealtimeAudio.OUTPUT_CHUNK_FRAMES * chunks
    return base64.b64encode(b"\x01\x00" * frames).decode()


CHUNK_MS = 100


# ---------------------------------------------------------------------------
# Fake Realtime surface
# ---------------------------------------------------------------------------


class FakeRealtimeSession:
    """Deterministic Realtime session: `RealtimeSession` + `RealtimeOutputControl`.

    It decides nothing on its own. The caller pushes the provider's events
    (`user_says`, `interrupt`, `surface_reflex`) and the speech scheduler triggers
    `speak()`; an output ends only when the caller or a cancellation ends it. That is
    what makes it possible to watch the queue while JARVIS is speaking, and to
    interrupt in the middle of a sentence.

    One deliberate liberty: `cancel_output()` closes the active output with the
    `cancelled` status, like a provider confirming the cancellation. Without it the
    scheduler would wait forever for an output end that never comes.
    """

    def __init__(self, *, name: str = "session", session_id: str | None = None) -> None:
        self.name = name
        #: Same role as on a real session: it is the identity the journal writes on
        #: every line (`session_id`), and therefore what splits a DiagnosticBundle into
        #: voice session segments. Without it a `virtual` trace would not segment the
        #: way a live one does.
        self.session_id = session_id or name
        self.inbox: asyncio.Queue[ProtocolEnvelope | None] = asyncio.Queue()
        self.spoken: list[SpeechRequest] = []
        self.cancelled_cursors: list[PlaybackCursor | None] = []
        self.truncated_cursors: list[PlaybackCursor] = []
        self.tool_results: list[tuple[str, dict[str, object]]] = []
        self.contexts: list[str] = []
        self.audio_bytes = 0
        self.finish_calls = 0
        self.closed = False
        self.active_output_id: str | None = None
        self.active_speech_id: str | None = None
        self._outputs = 0
        self._items = 0
        self._reserved_outputs: set[str] = set()
        self.invalidated_outputs: set[str] = set()
        #: `output_id -> reason_code`: cancel refusals armed by a scenario
        #: (`provider.cancel_rejected`). Empty by default, so `cancel_output()` keeps
        #: exactly its original behaviour.
        self.cancel_refusals: dict[str, str] = {}

    # -- RealtimeSession ----------------------------------------------------

    async def send_audio(self, pcm: bytes) -> None:
        self.audio_bytes += len(pcm)

    async def finish_input(self) -> bool:
        self.finish_calls += 1
        return True

    async def send_tool_result(self, call_id: str, result: dict[str, object]) -> None:
        self.tool_results.append((call_id, dict(result)))

    async def send_context(self, text: str) -> None:
        self.contexts.append(text)

    async def keepalive(self) -> None:
        return None

    async def events(self):
        while True:
            event = await self.inbox.get()
            if event is None:
                return
            yield event

    async def close(self) -> None:
        self.closed = True
        await self.inbox.put(None)

    # -- RealtimeOutputControl ---------------------------------------------

    async def speak_reserved(self, request: SpeechRequest, *, output_id: str) -> str:
        if not output_id or output_id in self._reserved_outputs or output_id in self.invalidated_outputs:
            raise ValueError("Invalid or reused reserved output")
        self._reserved_outputs.add(output_id)
        return await self.speak(request, output_id=output_id)

    async def invalidate_unstarted_output(self, output_id: str) -> None:
        self.invalidated_outputs.add(output_id)
        if self.active_output_id == output_id:
            await self.cancel_output()

    async def speak(self, request: SpeechRequest, *, output_id: str | None = None) -> str:
        """Render the brain's request and open the matching output."""

        self.spoken.append(request)
        self._outputs += 1
        output_id = output_id or f"{self.name}-out-{self._outputs}"
        self.active_output_id = output_id
        self.active_speech_id = request.id
        await self.push(
            "realtime.output_started",
            output_id=output_id,
            speech_id=request.id,
            response_id=f"{output_id}-resp",
        )
        return output_id

    async def cancel_output(self, cursor: PlaybackCursor | None = None) -> None:
        refusal = self.cancel_refusals.pop(self.active_output_id or "", None)
        if refusal is not None:
            # The provider refuses the cancellation: production journals
            # `voice.barge_in_degraded` / `barge_in_cancel_failed` and carries on.
            raise RuntimeError(refusal)
        self.cancelled_cursors.append(cursor)
        output_id, self.active_output_id = self.active_output_id, None
        self.active_speech_id = None
        if output_id is not None:
            await self.push("realtime.response_done", output_id=output_id, status="cancelled")

    async def truncate(self, cursor: PlaybackCursor) -> None:
        self.truncated_cursors.append(cursor)

    # -- driven by the caller ----------------------------------------------

    async def push(self, message_type: str, **payload: object) -> None:
        await self.inbox.put(ProtocolEnvelope(message_type=message_type, payload=payload))

    async def play_audio(self, *, chunks: int = 1) -> None:
        """Play `chunks` blocks of 100 ms for the open output."""

        await self.push(
            "realtime.audio",
            pcm_b64=audio_chunk_b64(chunks),
            output_id=self.active_output_id,
            speech_id=self.active_speech_id,
            item_id=f"{self.active_output_id}-item",
            response_id=f"{self.active_output_id}-resp",
            content_index=0,
            output_index=0,
        )

    async def finish_output(self, *, status: str = "completed", transcript: str | None = None) -> None:
        """Close the open output the way `response.done` would."""

        output_id, self.active_output_id = self.active_output_id, None
        speech_id, self.active_speech_id = self.active_speech_id, None
        if transcript is not None:
            await self.push("realtime.assistant_transcript", text=transcript, speech_id=speech_id or "")
        await self.push("realtime.audio_done", output_id=output_id)
        await self.push("realtime.response_done", output_id=output_id, status=status)

    async def surface_reflex(self, text: str, *, chunks: int = 1) -> None:
        """Surface reflex: the surface answers by itself, without the brain.

        No `speech_id`: this is not brain speech, and that is what makes it persist
        with the `surface.reflex` provenance (spec section 15).
        """

        self._outputs += 1
        output_id = f"{self.name}-reflex-{self._outputs}"
        self.active_output_id = output_id
        self.active_speech_id = None
        await self.push("realtime.output_started", output_id=output_id, response_id=f"{output_id}-resp")
        await self.push("realtime.audio", pcm_b64=audio_chunk_b64(chunks), output_id=output_id)
        await self.finish_output(transcript=text)

    async def user_says(self, text: str, *, item_id: str | None = None) -> str:
        """A complete user turn: the server VAD commit, then the final transcript."""

        self._items += 1
        item = item_id or f"{self.name}-item-{self._items}"
        await self.push("realtime.input_committed", item_id=item)
        await self.push("realtime.transcript", text=text, item_id=item)
        return item

    async def ambient(self, text: str) -> None:
        """Background noise: heard, never addressed (Decision 10)."""

        await self.push("realtime.transcript", text=text)

    async def interrupt(self) -> None:
        """The server VAD detects that the user is speaking again."""

        await self.push("realtime.speech_started")

    async def tool_call(self, name: str, arguments: dict[str, object] | None = None, *, call_id: str = "call-1") -> None:
        await self.push("realtime.tool_call", call_id=call_id, name=name, arguments=arguments or {})

    def texts(self) -> list[str]:
        return [request.text for request in self.spoken]


# ---------------------------------------------------------------------------
# Scripted brain backend
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class BrainTurnHandle:
    """One brain turn in flight, driven by the caller.

    The backend is deliberately **slow**: `run_turn` returns only on `finish()`.
    Everything that happens meanwhile - work started, progress, question, result,
    cancellation - is emitted on demand, which makes asynchronous scenarios
    reproducible without a single pause.
    """

    turn: BrainTurnInput
    state: BrainWorkingState
    emit: object
    release: asyncio.Event = field(default_factory=asyncio.Event)
    result: BrainTurnResult | None = None

    @property
    def conversation_id(self) -> str:
        return self.turn.conversation_id

    @property
    def correlation_id(self) -> str:
        return self.turn.correlation_id

    async def _emit(self, event: BrainEvent) -> None:
        await self.emit.emit(event)  # type: ignore[attr-defined]

    async def start_work(self, work_id: str, *, label: str = "") -> None:
        await self._emit(
            BrainEvent(
                kind=BrainEventKind.ACCEPTED,
                conversation_id=self.conversation_id,
                correlation_id=self.correlation_id,
                work_id=work_id,
                public_summary=label,
            )
        )

    async def report_progress(self, work_id: str, summary: str) -> None:
        await self._emit(
            BrainEvent(
                kind=BrainEventKind.PROGRESS,
                conversation_id=self.conversation_id,
                correlation_id=self.correlation_id,
                work_id=work_id,
                public_summary=summary,
            )
        )

    async def complete_work(self, work_id: str, *, summary: str = "") -> None:
        await self._emit(
            BrainEvent(
                kind=BrainEventKind.COMPLETED,
                conversation_id=self.conversation_id,
                correlation_id=self.correlation_id,
                work_id=work_id,
                public_summary=summary,
            )
        )

    async def supersede_work(self, work_id: str) -> None:
        await self._emit(
            BrainEvent(
                kind=BrainEventKind.SUPERSEDED,
                conversation_id=self.conversation_id,
                correlation_id=self.correlation_id,
                work_id=work_id,
            )
        )

    async def cancel_work(self, work_id: str) -> None:
        await self._emit(
            BrainEvent(
                kind=BrainEventKind.CANCELLED,
                conversation_id=self.conversation_id,
                correlation_id=self.correlation_id,
                work_id=work_id,
            )
        )

    async def say(
        self,
        text: str,
        *,
        kind: SpeechKind = SpeechKind.PROGRESS,
        work_id: str | None = None,
        priority: SpeechPriority | None = None,
        supersedes_key: str | None = None,
        expires_at: datetime | None = None,
        speech_id: str | None = None,
        source: SpeechSource | None = None,
    ) -> SpeechRequest:
        """Ask the surface to say a sentence, and return the request that was emitted.

        The caller keeps the object to learn the `speech_id`: that id is what ties the
        cut speech, the truncation and the next turn together.

        `speech_id` and `source` serve Test Lab scenarios, whose identities (candidate,
        intent, epoch) are written in the scenario: without them a scenario could not
        name the speech it expects.
        """

        request = SpeechRequest(
            conversation_id=self.conversation_id,
            text=text,
            kind=kind,
            priority=priority or (SpeechPriority.HIGH if kind is SpeechKind.QUESTION else SpeechPriority.NORMAL),
            correlation_id=self.correlation_id,
            work_id=work_id,
            supersedes_key=supersedes_key,
            expires_at=expires_at,
            **({"id": speech_id} if speech_id else {}),
            **({"source": source} if source is not None else {}),
        )
        await self._emit(
            BrainEvent(
                kind=BrainEventKind.SPEECH,
                conversation_id=self.conversation_id,
                correlation_id=self.correlation_id,
                work_id=work_id,
                speech=request,
            )
        )
        return request

    async def resend(self, request: SpeechRequest) -> None:
        """Re-emit an already emitted speech request, identically.

        This plays the duplicate case: Core republishes, and nothing may be said twice
        on the surface side.
        """

        await self._emit(
            BrainEvent(
                kind=BrainEventKind.SPEECH,
                conversation_id=self.conversation_id,
                correlation_id=self.correlation_id,
                work_id=request.work_id,
                speech=request,
            )
        )

    def finish(self, *, public_summary: str = "", status: BrainRunStatus = BrainRunStatus.COMPLETED, error: str | None = None) -> None:
        """Hand control back: `run_turn` finally returns."""

        self.result = BrainTurnResult(
            correlation_id=self.correlation_id,
            status=status,
            public_summary=public_summary,
            error=error,
        )
        self.release.set()


class ScriptedBrainBackend:
    """A slow, deterministic `BrainBackend`, entirely driven by the caller."""

    def __init__(self) -> None:
        self.handles: list[BrainTurnHandle] = []
        self._arrivals: asyncio.Queue[BrainTurnHandle] = asyncio.Queue()

    async def run_turn(self, turn: BrainTurnInput, state: BrainWorkingState, emit) -> BrainTurnResult:  # noqa: ANN001
        handle = BrainTurnHandle(turn=turn, state=state, emit=emit)
        self.handles.append(handle)
        self._arrivals.put_nowait(handle)
        await handle.release.wait()
        return handle.result or BrainTurnResult(correlation_id=turn.correlation_id)

    async def next_turn(self, *, timeout: float = TIMEOUT_S) -> BrainTurnHandle:
        """Wait for the next turn handed to the strong model."""

        return await asyncio.wait_for(self._arrivals.get(), timeout=timeout)


# ---------------------------------------------------------------------------
# Watching the Core bus
# ---------------------------------------------------------------------------


class CoreEventRecorder:
    """A control subscriber on `CoreEventBus`, to observe what Core publishes.

    Separate from the voice path: the surface consumes `/v1/events` over a websocket.
    This subscriber exists so a caller can check what Core actually **emitted**,
    including while the voice is in the background.
    """

    def __init__(self, core: JarvisCoreApplication) -> None:
        self.core = core
        self.events: list[ProtocolEnvelope] = []
        self._queue = core.events.subscribe()
        self._task = asyncio.create_task(self._drain(), name="jarvis-test-event-recorder")

    async def _drain(self) -> None:
        while True:
            self.events.append(await self._queue.get())

    def of(self, message_type: str) -> list[ProtocolEnvelope]:
        return [event for event in self.events if event.message_type == message_type]

    def types(self) -> list[str]:
        return [event.message_type for event in self.events]

    async def wait_for(self, message_type: str, *, count: int = 1, timeout: float = TIMEOUT_S) -> ProtocolEnvelope:
        await wait_until(
            lambda: len(self.of(message_type)) >= count,
            timeout=timeout,
            message=f"{message_type} x{count}",
        )
        return self.of(message_type)[count - 1]

    async def close(self) -> None:
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        self.core.events.unsubscribe(self._queue)


# ---------------------------------------------------------------------------
# The whole stack
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class VoiceStack:
    """Everything a caller drives: Core, the protocol, the voice, and their doubles."""

    core: JarvisCoreApplication
    server: LocalProtocolServer
    client: LocalCoreClient
    port: int
    runtime: PersistentVoiceRuntime
    wakeword: FakeWakeWord
    backend: ScriptedBrainBackend
    journal: RecordingJournal
    core_journal: RecordingJournal
    signals: RecordingSignals
    events: CoreEventRecorder
    sessions: list[FakeRealtimeSession]
    clock: FakeClock | None
    run_task: asyncio.Task[None] | None = None
    #: Core's own internal subscribers, measured right after it starts (the
    #: notification loop, the working-state policy, ...).
    core_subscribers: int = 1

    @property
    def session(self) -> FakeRealtimeSession:
        """The current Realtime session: a new one is born on each activation."""

        return self.sessions[-1]

    @property
    def audio(self) -> FakeAudio:
        return FakeAudio.instances[-1]

    @property
    def conversation_id(self) -> str:
        conversation_id = self.runtime.runtime.conversation_id
        if conversation_id is None:
            # A caller asking for the conversation before waking the voice is a
            # programming error; `assert` would vanish under `python -O` and hand back
            # `None`, which fails much further away.
            raise RuntimeError("no conversation has been opened yet; wake the voice first")
        return conversation_id

    async def wake(self, *, keyword: str = "f9") -> None:
        """Wake the voice and wait until the session is really open."""

        opened = len(self.sessions)
        started = self.journal.count("audio.start")
        await self.wakeword.queue.put(keyword)
        await self.journal.wait_until(lambda: self.journal.count("audio.start") > started)
        await wait_until(lambda: len(self.sessions) > opened, message="a Realtime session is open")
        # The scheduler must be subscribed before a caller pushes a turn, or the
        # brain's speech would go nowhere (Decision 31: nothing is replayed).
        await wait_until(
            lambda: self.core.events.subscriber_count >= self._expected_subscribers(),
            message="the speech scheduler is subscribed to /v1/events",
        )

    def _expected_subscribers(self) -> int:
        # Core itself (its internal subscribers), the caller's observer, and the
        # speech scheduler of the active session.
        return self.core_subscribers + 2

    async def wait_background(self) -> None:
        """Wait for a **complete** return to background, `/v1/events` subscription included.

        Settling for the voice state alone would leave the previous session's websocket
        open: the next activation would then see two subscribers, and the caller would
        restart on a stack that is not the one it believes it has.
        """

        await wait_until(
            lambda: self.runtime.runtime.state is VoiceLifecycleState.BACKGROUND,
            message="the voice returned to background",
        )
        await wait_until(
            lambda: self.core.events.subscriber_count <= self._expected_subscribers() - 1,
            message="the /v1/events subscription is closed",
        )

    async def user_says(self, text: str, *, item_id: str | None = None) -> BrainTurnHandle:
        """Say an addressed sentence and return the turn the strong model received."""

        submitted = self.journal.count("voice.brain_turn_submitted")
        await self.session.user_says(text, item_id=item_id)
        await self.journal.wait_until(lambda: self.journal.count("voice.brain_turn_submitted") > submitted)
        return await self.backend.next_turn()

    async def wait_spoken(self, count: int, *, timeout: float = TIMEOUT_S) -> None:
        await wait_until(
            lambda: len(self.session.spoken) >= count,
            timeout=timeout,
            message=f"{count} speech request(s) reached the surface",
        )

    async def speak_and_finish(self, *, chunks: int = 1, transcript: str | None = None) -> None:
        """Let the open output play through to the end."""

        await self.session.play_audio(chunks=chunks)
        await self.session.finish_output(transcript=transcript)

    async def assistant_turns(self) -> list[object]:
        turns = await self.core.state.list_turns(self.conversation_id, limit=50)
        return [turn for turn in turns if turn.kind.value == "assistant"]

    async def wait_for_assistant_turns(self, count: int, *, timeout: float = TIMEOUT_S) -> list[object]:
        """Wait for the history to catch up with what was said.

        Persistence follows utterance: the scheduler writes the turn once the output is
        settled. Reading the store without waiting would therefore observe the history
        from before the last sentence.
        """

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            turns = await self.assistant_turns()
            if len(turns) >= count:
                return turns
            if loop.time() >= deadline:
                raise AssertionError(f"only {len(turns)} assistant turn(s) persisted out of {count}")
            await asyncio.sleep(0.005)

    async def user_turns(self) -> list[object]:
        turns = await self.core.state.list_turns(self.conversation_id, limit=50)
        return [turn for turn in turns if turn.kind.value == "user"]

    async def shutdown(self, *, timeout: float = TIMEOUT_S) -> bool:
        """Stop the voice the way production does, so that `voice.stop` is journalled.

        Tearing the context down cancels the task: the trace then stops in the middle of
        a session, and a DiagnosticBundle captured over it sees a session that was never
        closed. A diagnostic must produce the same session shape as a real stop, so it
        asks the loop to exit and waits for `close()` to finish. Returns `False` when the
        stop did not complete within the timeout: the caller decides, nothing is hidden.
        An exception from the voice loop does propagate - that is a diagnostic fact, not
        a shutdown detail.
        """

        run_task = self.run_task
        if run_task is None or run_task.done():
            return run_task is not None
        self.runtime.request_switch_exit()
        try:
            await asyncio.wait_for(asyncio.shield(run_task), timeout=timeout)
        except asyncio.TimeoutError:
            return False
        return True


@asynccontextmanager
async def voice_stack(
    tmp_path,
    patches: AttributePatcher,
    *,
    clock: FakeClock | None = None,
    active_timeout_s: float = 90.0,
    conversation_events_factory=None,
    journal: RecordingJournal | None = None,
    core_journal: RecordingJournal | None = None,
    session_id_factory=None,
    capture_factory=None,
):
    """Mount the whole stack, wake it, then tear everything down cleanly.

    `patches` offers a single service, `setattr(target, name, value)`, restored on
    exit: pytest's `monkeypatch` and the Test Lab's `PatchStack` are two
    implementations of it.

    `conversation_events_factory(port, token)` (conversation-observability Slice 03b):
    returns the Voice process's `ConversationEventForwarder`, started here and drained
    to Core before Core itself stops.

    `capture_factory()`: the duplex microphone capture. `None` (the historical default)
    means "no echo guard" - the bridge then takes the provider's VAD at its word. The
    `virtual` profile passes `VirtualEchoGuard`.

    `journal` / `core_journal`: the observability sinks of the voice and of Core. Two
    in-memory `RecordingJournal`s by default; the `virtual` profile passes a journal
    that also writes `trace.jsonl`, so a DiagnosticBundle can be captured over the run.
    `session_id_factory(index)` names the Realtime session.

    The teardown contract matters as much as the mount: a Realtime session left open or
    an unclosed `/v1/events` subscription would turn the next scenario into a race.
    """

    import jarvis.runtime.realtime_audio as realtime_audio

    FakeAudio.instances.clear()
    patches.setattr(realtime_audio, "SoundDeviceRealtimeAudio", FakeAudio)
    patches.setattr(SpeechScheduler, "RECONNECT_DELAY_S", FAST_RECONNECT_DELAY_S)
    patches.setattr(protocol_server.web, "AppRunner", FastShutdownRunner)

    backend = ScriptedBrainBackend()
    journal = journal if journal is not None else RecordingJournal()
    core_journal = core_journal if core_journal is not None else RecordingJournal()
    signals = RecordingSignals()
    sessions: list[FakeRealtimeSession] = []

    port = free_port()
    core = JarvisCoreApplication(data_root=tmp_path, brain_backend=backend, diagnostics=core_journal)
    await core.start()
    core_subscribers = core.events.subscriber_count
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
    await server.start()
    client = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
    recorder = CoreEventRecorder(core)

    async def factory(context):
        del context
        index = len(sessions) + 1
        name = f"s{index}"
        session = FakeRealtimeSession(
            name=name, session_id=session_id_factory(index) if session_id_factory is not None else name)
        sessions.append(session)
        return session

    wakeword = FakeWakeWord()
    conversation_events = conversation_events_factory(port, TOKEN) if conversation_events_factory else None
    if conversation_events is not None:
        conversation_events.start()
    runtime = PersistentVoiceRuntime(
        conversation_events=conversation_events,
        wakeword=wakeword,  # type: ignore[arg-type]
        core=client,
        realtime_factory=factory,  # type: ignore[arg-type]
        active_timeout_s=active_timeout_s,
        clock=clock,  # type: ignore[arg-type]
        signals=signals,  # type: ignore[arg-type]
        journal=journal,  # type: ignore[arg-type]
        auto_turn=True,
        capture_factory=capture_factory,
        voice_arch=VoiceArchitecture.CONTINUOUS_BRAIN,
    )
    stack = VoiceStack(
        core=core,
        server=server,
        client=client,
        port=port,
        runtime=runtime,
        wakeword=wakeword,
        backend=backend,
        journal=journal,
        core_journal=core_journal,
        signals=signals,
        events=recorder,
        sessions=sessions,
        clock=clock,
        core_subscribers=core_subscribers,
    )
    run_task = asyncio.create_task(runtime.run(), name="jarvis-test-voice-runtime")
    stack.run_task = run_task
    try:
        yield stack
    finally:
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)
        if conversation_events is not None:
            # Before the protocol stops: the last span ends go out to Core.
            await conversation_events.aclose()
        # Release the brain turns still in flight: a backend still waiting for its
        # `release` would keep `core.stop()` from settling.
        for handle in backend.handles:
            handle.release.set()
        await recorder.close()
        await client.close()
        # `stack.server`, not `server`: a scenario may have cut and restarted the
        # protocol, and it is the live server that must be stopped.
        await stack.server.stop()
        await core.stop()

"""A GPT-Live-shaped voice surface: audio arrives, no output ever ends.

Test-only double of `LiveFrontendSession` as the speech scheduler and the bridge
see it, reduced to what decides WHEN a speech is over:

- `requires_local_quiescence_without_output_final = True`: the provider never
  emits `realtime.response_done` (READINESS B1 fact 1);
- `speak_reserved()` appends the text and returns the scheduler's reserved id,
  but the audio that follows carries the PROVIDER's own output id and no
  `speech_id`, exactly like `adapters/openai_live_frontend.py` (READINESS A1);
- provider output ids, two modes:
  - `shared_output=False` (default, KINDER than real Live): each spoken request
    gets its own id `live-output-<n>` and its own `realtime.output_started`;
  - `shared_output=True` (what real Live does): back-to-back Jarvis speeches with
    no user speech in between SHARE one provider output id — the adapter keeps
    `_output_id` until the direction flips to input
    (`openai_live_frontend.py`, `_enter_direction`) — and
    `LiveFrontendSession._legacy_events` announces `realtime.output_started`
    only once per id (`_declared_outputs`). This double never simulates user
    speech, so in shared mode every speech rides `live-output-1`;
- `active_output_id` is the last provider output observed and never goes back
  to None, like `LiveFrontendSession.active_output_id`;
- `audio_observation_starts_output` / `canonical_history` as on
  `LiveFrontendSession`: after a local quiescence the bridge forgets the output,
  and the next frame of the same provider output reopens it;
- `cancel_output()` mutes the rest of the incarnation (`playback_suppressed`),
  like `suppress_playback_until_session_end()`.

The provider stream is `events()`, which the production bridge consumes
(`RealtimeConversationBridge._consume`). Each spoken request is rendered as audio
bursts: `plan(request)` returns `[(audio_ms, silence_after_ms), ...]`, streamed as
20 ms PCM frames paced on the running loop's clock. Under `VirtualTimeLoop` the
pacing costs no wall-clock time.

Why a new double: `FakeVoiceSession` (tests/unit/test_v2_speech_scheduler.py) and
`FakeRealtimeSession` (jarvis/testlab/virtual/harness.py) both announce an output
end; no existing double reproduces a surface that never does.
"""

from __future__ import annotations

import asyncio
import base64
import math
import struct
from collections.abc import Callable

from jarvis.domain.v2 import PlaybackCursor, ProtocolEnvelope, SpeechRequest

FRAME_MS = 20
#: 20 ms of audible PCM16 at 24 kHz. Zeros would be Live's streamed silence,
#: which `LiveFrontendSession._legacy_events` never hands to the bridge.
VOICE_FRAME = b"".join(struct.pack("<h", int(3000 * math.sin(i / 8))) for i in range(480))
VOICE_FRAME_B64 = base64.b64encode(VOICE_FRAME).decode("ascii")

Plan = Callable[[SpeechRequest], list[tuple[int, int]]]


class LiveOutputSurface:
    canonical_history = True
    audio_observation_starts_output = True
    requires_local_quiescence_without_output_final = True

    def __init__(self, plan: Plan, *, session_id: str = "live-session", shared_output: bool = False) -> None:
        self.session_id = session_id
        self.plan = plan
        self.shared_output = shared_output
        self.spoken: list[SpeechRequest] = []
        #: `loop.time()` at which each `speak_reserved` reached the surface.
        self.spoken_at: list[float] = []
        #: `(output_id, loop.time())` of every audio frame put on the provider stream.
        self.frames: list[tuple[str, float]] = []
        #: `loop.time()` of every audio frame, per spoken request (index in
        #: `spoken`). In shared mode the output id no longer tells speeches apart.
        self.speech_frames: list[list[float]] = []
        self.playback_suppressed = False
        self.closed = False
        self._provider: asyncio.Queue[ProtocolEnvelope | None] = asyncio.Queue()
        self._outputs: list[str] = []
        self._declared: set[str] = set()
        self._tasks: set[asyncio.Task] = set()

    # -- RealtimeSession ----------------------------------------------------

    async def send_audio(self, pcm: bytes) -> None:
        del pcm

    async def finish_input(self) -> bool:
        return False

    async def send_tool_result(self, call_id: str, result: dict[str, object]) -> None:
        del call_id, result

    async def send_context(self, text: str) -> None:
        del text

    async def keepalive(self) -> None:
        return None

    async def events(self):
        while True:
            event = await self._provider.get()
            if event is None:
                return
            yield event

    async def close(self) -> None:
        self.closed = True
        for task in self._tasks:
            task.cancel()
        await self._provider.put(None)

    # -- RealtimeOutputControl ---------------------------------------------

    @property
    def active_output_id(self) -> str | None:
        return self._outputs[-1] if self._outputs else None

    async def speak_reserved(self, request: SpeechRequest, *, output_id: str) -> str:
        self.spoken.append(request)
        self.spoken_at.append(asyncio.get_running_loop().time())
        self.speech_frames.append([])
        task = asyncio.create_task(self._render(request, self.speech_frames[-1]), name="live-surface-render")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return output_id

    async def invalidate_unstarted_output(self, output_id: str) -> None:
        del output_id  # Live has no unstarted-output primitive.

    async def cancel_output(self, cursor: PlaybackCursor | None = None) -> None:
        del cursor
        self.playback_suppressed = True

    async def truncate(self, cursor: PlaybackCursor) -> None:
        del cursor

    # -- provider side -----------------------------------------------------

    async def _render(self, request: SpeechRequest, frames: list[float]) -> None:
        if self.shared_output and self._outputs:
            output_id = self._outputs[-1]
        else:
            output_id = f"live-output-{len(self._outputs) + 1}"
            self._outputs.append(output_id)
        common = {"output_id": output_id, "response_id": None, "item_id": None, "speech_id": None}
        loop = asyncio.get_running_loop()
        for audio_ms, silence_ms in self.plan(request):
            for _ in range(max(1, audio_ms // FRAME_MS)):
                if self.playback_suppressed:
                    return
                if output_id not in self._declared:
                    # Once per provider output id, like `_legacy_events`.
                    self._declared.add(output_id)
                    await self._provider.put(ProtocolEnvelope(message_type="realtime.output_started", payload=common))
                await self._provider.put(ProtocolEnvelope(message_type="realtime.audio",
                                                          payload={**common, "pcm_b64": VOICE_FRAME_B64}))
                self.frames.append((output_id, loop.time()))
                frames.append(loop.time())
                await asyncio.sleep(FRAME_MS / 1000)
            if silence_ms:
                await asyncio.sleep(silence_ms / 1000)

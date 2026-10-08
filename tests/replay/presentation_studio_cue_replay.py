"""Rehearsed-run replay for the cue follower (handoff jarvis-interactive-presentation-studio, Slice 13).

Scripted French utterances go through the REAL Voice path: fake capture device -> real `AudioCaptureHub` -> real
segmenter -> `ScriptedTranscriber` (the only fake in the lane) -> real `AmbientIngestionLane` -> its consumer slot -> the
real `PresentationStudioCueFollower` composed by the real `PresentationComposition` -> an in-process Core adapter -> the
REAL `PresentationStudioPlaybackService` (real scene service, real edit service, real file store, real stage window).

Not real here: the microphone, the OpenAI transcription model, the HTTP hop between Voice and Core (an in-process adapter
calls the very methods the routes call) and the two mode services (Voice's observer and Core's service are separate objects
driven by hand). Nothing here proves a live OpenAI ambient run; `docs/OPERATIONS.md` has the Human recipe for that.

- `python -m tests.replay.presentation_studio_cue_replay <evidence dir>` records the evidence (small, redacted);
- `run_rehearsal(root)` returns it (used by `tests/integration/test_presentation_studio_cue_replay.py`).
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from jarvis.domain.interaction_mode import InteractionMode
from jarvis.domain.presentation_studio_armed_set import ARMED_CHANGED
from jarvis.domain.v2 import ProtocolEnvelope
from jarvis.runtime.presentation_studio_cue_follower import FollowerConfig
from tests.fakes.presentation_scenario import build_rig
from tests.unit.test_ambient_ingestion_lane import until
from tests.unit.test_presentation_studio_playback_service import CUE, CUE2, I1, I2, I3, I4, Bus, Rig as CoreRig

#: What the room says, in order: (text, also heard by the realtime model, what the presenter wants).
SCRIPT: list[tuple[str, bool, str]] = [
    ("On a bien avancé sur le budget cette semaine", False, "chatter: nothing"),
    ("Il a dit passons à la suite hier soir", False, "quoted: nothing"),
    ("Jarvis, passons à la suite", True, "explicit address with a cue phrase: preempted, the brain turn is the explicit path"),
    ("Bon, passons à la suite.", False, "the stage direction: fires cue 1"),
    ("Passons à la suite", False, "repeated: nothing armed any more"),
    ("Voilà la fin ?", False, "a question: nothing"),
    ("Voilà la fin.", False, "the stage direction: fires cue 2"),
]


class QueueBus(Bus):
    """Core's bus as the follower sees it: publish fans out to the live subscribers; a missed message is not replayed."""

    def __init__(self) -> None:
        super().__init__()
        self.subscribers: list[asyncio.Queue[Any]] = []

    async def publish(self, envelope) -> None:  # noqa: ANN001
        await super().publish(envelope)
        for queue in self.subscribers:
            queue.put_nowait(envelope)


class InProcessCore:
    """The three client methods the follower uses, calling the service the routes call. Records every call (no text exists here)."""

    def __init__(self, service: Any, bus: QueueBus) -> None:
        self._service, self._bus = service, bus
        self.calls: list[dict[str, Any]] = []

    async def presentation_studio_playback_armed(self) -> dict[str, Any]:
        answer = self._service.armed_set()
        self.calls.append({"call": "armed", "run_id": answer["run_id"], "generation": answer["generation"], "count": len(answer["cues"])})
        return answer

    async def presentation_studio_report_cue(self, run_id: str, generation: int, cue_id: str) -> dict[str, Any]:
        answer = dict(await self._service.report_cue({"run_id": run_id, "generation": generation, "cue_id": cue_id}))
        answer.pop("http_status", None)
        self.calls.append({"call": "report", "keys": ["run_id", "generation", "cue_id"], "cue_id": cue_id, "generation": generation,
                           "status": answer.get("status"), "code": answer.get("code")})
        return answer

    async def events(self, *, on_connected=None):  # noqa: ANN001
        queue: asyncio.Queue[Any] = asyncio.Queue()
        self._bus.subscribers.append(queue)
        try:
            if on_connected is not None:
                on_connected()
            while True:
                yield await queue.get()
        finally:
            self._bus.subscribers.remove(queue)


async def _quiet(follower: Any, *, rounds: int = 40) -> None:
    """Let the lane, the follower and the report finish: a few ticks until no report is in flight."""

    for _ in range(rounds):
        await asyncio.sleep(0.02)
        report = follower._report
        if report is None or report.done():
            await asyncio.sleep(0.02)
            if follower._report is None or follower._report.done():
                return


async def run_rehearsal(root: Path) -> dict[str, Any]:
    (root / "core").mkdir(parents=True, exist_ok=True)
    core = CoreRig(root / "core")
    core.bus = QueueBus()
    await core.open()
    voice = None
    try:
        started = await core.service.start(core.start_body("user_presenter"))
        assert started.status.value == "applied", started.to_dict()
        adapter = InProcessCore(core.service, core.bus)
        voice = await build_rig(root / "voice", mode=InteractionMode.ASSISTANT, cue_core=adapter)
        await voice.set_mode(InteractionMode.PRESENTATION)
        follower = voice.stack.cue_follower
        # Same code, faster wall clock for the test: the hold after an explicit address would otherwise cost seconds.
        follower._config = FollowerConfig(tick_s=0.02, hold_s=0.6, idle_poll_s=0.5, call_timeout_s=3.0)
        await until(lambda: follower.status()["armed"] == 1, timeout=5.0)

        steps: list[dict[str, Any]] = []
        positions: list[int] = [core.service.state.position + 1]
        for index, (text, realtime_too, wants) in enumerate(SCRIPT):
            reports_before = sum(1 for c in adapter.calls if c["call"] == "report")
            counters_before = dict(follower.counters.to_payload())
            await voice.room(text, realtime_too=realtime_too)
            await _quiet(follower)
            if realtime_too:
                await voice.quiesce()
            if index == 2:
                await asyncio.sleep(0.8)  # the hold that follows an explicit address (0.6 s here) is over
            if index == 4:  # the user moves on by hand: that arms the second cue under a new generation
                res = await core.service.next({"actor": "user"})
                assert res.status.value == "applied", res.to_dict()
                await until(lambda: follower.status()["armed"] == 1 and follower.status()["generation"] == core.service.state.generation,
                            timeout=5.0)
            after = follower.counters.to_payload()
            steps.append({
                "step": index + 1, "wants": wants, "heard_by_realtime_too": realtime_too, "utterance_chars": len(text),
                "reports_sent": sum(1 for c in adapter.calls if c["call"] == "report") - reports_before,
                "counter_delta": {k: after[k] - counters_before[k] for k in after if isinstance(after[k], int) and after[k] != counters_before[k]},
                "core_position": core.service.state.position + 1, "follower_state": follower.status()["state"],
            })
            positions.append(core.service.state.position + 1)
        stage = await core.stage_object()
        stage_title = None if stage is None else stage.payload.title
        brain_turns = list(getattr(voice.core, "brain_turns", []))
        trace_voice = voice.trace()
        core_rows = [{"kind": k, "level": level, "data": data} for k, level, data in core.env.sink.rows]
        return {
            "script_steps": steps, "positions": positions, "final_state": core.service.state.phase.value,
            "stage_title": stage_title, "calls": adapter.calls, "bus": [(t, p) for t, p in core.bus.messages if t == ARMED_CHANGED],
            "follower": follower.status(), "brain_turns": len(brain_turns),
            "voice_trace": [r for r in trace_voice if str(r.get("kind", "")).startswith(("presentation.studio", "ambient"))],
            "voice_trace_all": trace_voice, "core_trace": [r for r in core_rows if r["kind"].startswith("core.presentation_studio")],
            "utterances": [t for t, _, _ in SCRIPT], "cue_ids": [CUE, CUE2], "items": [I1, I2, I3, I4],
        }
    finally:
        if voice is not None:
            await voice.close()
        await core.service.close()
        await core.close()


def record(out: Path) -> dict[str, Any]:
    """Run once and write the small, redacted evidence files under `out`."""

    from tests.replay.evidence_privacy import redact_in_place

    with tempfile.TemporaryDirectory() as tmp:
        result = asyncio.run(run_rehearsal(Path(tmp)))
    out.mkdir(parents=True, exist_ok=True)

    def dump(name: str, data: Any) -> None:
        (out / name).write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    summary = {k: result[k] for k in ("script_steps", "positions", "final_state", "stage_title", "follower", "brain_turns")}
    summary["core_calls"] = {"armed_pulls": sum(1 for c in result["calls"] if c["call"] == "armed"),
                             "cue_reports": sum(1 for c in result["calls"] if c["call"] == "report"),
                             "armed_changed_bus_messages": len(result["bus"])}
    dump("rehearsal-summary.json", summary)
    dump("core-calls.json", result["calls"])
    dump("voice-trace.json", [{"kind": r["kind"], "level": r.get("level"), "data": r.get("data", {})} for r in result["voice_trace"]])
    dump("core-trace.json", result["core_trace"])
    redact_in_place(out)
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python -m tests.replay.presentation_studio_cue_replay <evidence dir>", file=sys.stderr)
        raise SystemExit(2)
    record(Path(sys.argv[1]))
    print("recorded")

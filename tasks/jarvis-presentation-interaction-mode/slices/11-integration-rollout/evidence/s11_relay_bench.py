"""Slice 11 - in-process sink vs cross-process relay, measured rather than argued.

`PresentationObservationSink` (Slice 06) is a **synchronous** Protocol. Slice 06
left the choice to the rollout slice and wrote down the risk: backing it with a
relay is blocking IO on the Voice event loop, the loop that also carries the
explicit-address lane, which D04 says ambient work may never delay.

This measures that loop, three ways, with the real `AmbientIngestionLane`, the
real `AudioCaptureHub`, the real segmenter and the real store:

  A. in-process   - the store, called directly (the shipped choice);
  B. relay, up    - a synchronous loopback HTTP POST per store call, against a
                    real local server that answers in ~2 ms;
  C. relay, down  - the same relay with nothing listening.

What is measured:

  loop_lag_max_ms  - the worst delay of a 5 ms heartbeat task. This IS the
                     quantity D04 cares about: every other task on that loop,
                     including `ExplicitAddressLane`'s delivery, waits exactly
                     this long.
  trigger_ms       - the wall time between pressing the manual key and the lane
                     delivering the typed trigger, measured while the ambient
                     load runs.
"""

from __future__ import annotations

import array
import asyncio
import json
import math
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(r"C:\Projects\jarvis\jarvis")
sys.path.insert(0, str(ROOT))

from jarvis.audio.capture_hub import AudioCaptureHub  # noqa: E402
from jarvis.core.presentation_working_set import PresentationWorkingSetStore  # noqa: E402
from jarvis.domain.explicit_address import ExplicitAddressSource  # noqa: E402
from jarvis.runtime.ambient_lane import AmbientIngestionLane  # noqa: E402
from jarvis.runtime.explicit_address_lane import ExplicitAddressLane  # noqa: E402

HUB_RATE = 24000
BLOCK_FRAMES = 1200
SESSION = "pres-bench"


class Device:
    def __init__(self) -> None:
        self.callback = None

    def factory(self, *, samplerate, channels, dtype, device, blocksize, callback):
        self.callback = callback
        return self

    def stop(self) -> None: ...

    def close(self) -> None: ...

    def push(self, chunk: bytes) -> None:
        self.callback(chunk, len(chunk) // 2, None, None)


class Transcriber:
    def __init__(self) -> None:
        self.calls = 0

    async def transcribe(self, audio):
        self.calls += 1
        from types import SimpleNamespace

        return SimpleNamespace(text=f"une phrase de la salle numero {self.calls}",
                               duration_ms=0, provider="bench", model="bench")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        time.sleep(0.002)  # a Core that answers promptly
        body = b'{"disposition":"applied","code":"relayed","revision":1}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # silence
        return


class RelaySink:
    """What a cross-process sink would have to be, behind a SYNCHRONOUS Protocol.

    It cannot `await`: the Protocol has no async member and the ambient worker
    calls it inline. So the only shape available is a blocking request.
    """

    def __init__(self, url: str, inner: PresentationWorkingSetStore) -> None:
        self.url = url
        self.inner = inner
        self.calls = 0
        self.failures = 0

    def _post(self, payload: dict) -> None:
        self.calls += 1
        request = urllib.request.Request(
            self.url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=2.0) as response:
                response.read()
        except (urllib.error.URLError, OSError):
            self.failures += 1

    def observe(self, session_id, utterance_id, text, *, spoken_at=None, origin=None, revision=0):
        self._post({"op": "observe", "utterance_id": utterance_id})
        return self.inner.observe(session_id, utterance_id, text,
                                  spoken_at=spoken_at,
                                  **({"origin": origin} if origin is not None else {}),
                                  revision=revision)

    def apply(self, observation):
        self._post({"op": "apply"})
        return self.inner.apply(observation)

    def prune(self, now=None):
        return self.inner.prune(now)

    @property
    def snapshot(self):
        return self.inner.snapshot


def pcm(ms: int, amplitude: int) -> bytes:
    count = HUB_RATE * ms // 1000
    return array.array(
        "h", [int(amplitude * math.sin(2 * math.pi * 180 * i / HUB_RATE)) for i in range(count)]
    ).tobytes()


class Heartbeat:
    """A 5 ms ticker. Its worst lateness is what every other task on this loop feels."""

    def __init__(self, period: float = 0.005) -> None:
        self.period = period
        self.lags: list[float] = []
        self._task: asyncio.Task | None = None

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            expected = loop.time() + self.period
            await asyncio.sleep(self.period)
            self.lags.append(max(0.0, loop.time() - expected))

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    def report(self) -> dict[str, float]:
        if not self.lags:
            return {"max_ms": 0.0, "p95_ms": 0.0, "ticks": 0}
        ordered = sorted(self.lags)
        return {
            "max_ms": round(ordered[-1] * 1000, 2),
            "p95_ms": round(ordered[int(len(ordered) * 0.95)] * 1000, 2),
            "ticks": len(ordered),
        }


class Key:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()

    async def detections(self):
        while True:
            yield await self.queue.get()

    async def suspend(self): ...

    async def suspend_for_active_session(self): ...

    async def resume(self): ...

    async def close(self): ...

    def press(self) -> None:
        self.queue.put_nowait("f9")


async def scenario(label: str, make_sink) -> dict:
    device = Device()
    hub = AudioCaptureHub(sample_rate=HUB_RATE, block_frames=BLOCK_FRAMES,
                          stream_factory=device.factory)
    await hub.open()
    store = PresentationWorkingSetStore()
    store.bind_session(SESSION)
    sink = make_sink(store)
    lane = AmbientIngestionLane(hub=hub, transcriber=Transcriber(), sink=sink,
                               session_id=SESSION)
    await lane.start()

    key = Key()
    address = ExplicitAddressLane()
    address.add_source(ExplicitAddressSource.MANUAL_KEY, key)
    triggers = address.triggers()
    await address.start()

    heartbeat = Heartbeat()
    heartbeat.start()
    latencies: list[float] = []
    try:
        for round_index in range(6):
            for data in (pcm(900, 9000), pcm(900, 15)):
                block = BLOCK_FRAMES * 2
                for index, offset in enumerate(range(0, len(data), block)):
                    device.push(data[offset : offset + block])
                    if index % 8 == 7:
                        await asyncio.sleep(0)
                await asyncio.sleep(0)
            # Press the key while the ambient load is in flight.
            pressed = time.perf_counter()
            key.press()
            await asyncio.wait_for(anext(triggers), 5.0)
            latencies.append((time.perf_counter() - pressed) * 1000)
            await asyncio.sleep(0.05)
        # Let the ambient work drain what it can.
        for _ in range(60):
            await asyncio.sleep(0.01)
    finally:
        await heartbeat.stop()
        await lane.stop()
        await address.close()
        await hub.close()

    return {
        "scenario": label,
        "loop": heartbeat.report(),
        "trigger_ms_max": round(max(latencies), 2),
        "trigger_ms_median": round(statistics.median(latencies), 2),
        "sink_calls": getattr(sink, "calls", 0),
        "sink_failures": getattr(sink, "failures", 0),
        "utterances": len(store.snapshot.tail.entries),
    }


async def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    up = f"http://127.0.0.1:{server.server_address[1]}/v1/presentation/observations"
    down = "http://127.0.0.1:9/v1/presentation/observations"  # discard port, nothing listens

    results = []
    results.append(await scenario("A. in-process (shipped)", lambda store: store))
    results.append(await scenario("B. relay, Core up (~2 ms)", lambda store: RelaySink(up, store)))
    results.append(await scenario("C. relay, Core unreachable", lambda store: RelaySink(down, store)))
    server.shutdown()

    print(f"\n{'scenario':<28} {'loop max':>9} {'loop p95':>9} {'trigger max':>12} {'trigger med':>12} {'sink':>6} {'fail':>5} {'utt':>4}")
    for row in results:
        print(f"{row['scenario']:<28} {row['loop']['max_ms']:>8.2f}m {row['loop']['p95_ms']:>8.2f}m "
              f"{row['trigger_ms_max']:>11.2f}m {row['trigger_ms_median']:>11.2f}m "
              f"{row['sink_calls']:>6} {row['sink_failures']:>5} {row['utterances']:>4}")
    print("\nraw:", json.dumps(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

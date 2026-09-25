"""Slice 11 - drive the composed PRESENTATION stack and keep the real trace.

Not a test: a scenario. It builds the production composition
(`PresentationComposition`, the same object `jarvis/app.py` fills), writes to a
real `RuntimeJournal` under a temporary runtime root, and drives one session
from room speech to an addressed turn.

What is real: every module of Slices 04-11, the capture hub, the segmenter, the
explicit-address lane, the working-set store, the speculative pool and its
capability table, the attention judge, the addressed-turn service, the speech
gate, and the journal.

What is faked, and only at the outer boundary: the PortAudio device (no
microphone is opened), the transcription provider (no network), the Claude CLI
(no process is launched, but the *runner* is real and parses a real answer), and
the scene transport (no Core).

Output: `<runtime>/trace.jsonl`, copied next to this script as
`s11_trace.jsonl`.
"""

from __future__ import annotations

import array
import asyncio
import json
import math
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(r"C:\Projects\jarvis\jarvis")
sys.path.insert(0, str(ROOT))

from jarvis.domain.interaction_mode import InteractionMode  # noqa: E402
from jarvis.runtime.journal import RuntimeJournal  # noqa: E402
from jarvis.runtime.presentation_runtime import (  # noqa: E402
    PresentationComposition,
    PresentationCoordinator,
    PresentationWakeRouter,
)

HUB_RATE = 24000
BLOCK_FRAMES = 1200


class FakeDevice:
    def __init__(self) -> None:
        self.opens = 0
        self.callback = None

    def factory(self, *, samplerate, channels, dtype, device, blocksize, callback):
        self.opens += 1
        self.callback = callback
        return self

    def stop(self) -> None: ...

    def close(self) -> None: ...

    def push(self, chunk: bytes) -> None:
        self.callback(chunk, len(chunk) // 2, None, None)


class ScriptedTranscriber:
    """The room, as text. No network, no key, no model."""

    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.calls = 0

    async def transcribe(self, audio):
        self.calls += 1
        text = self.texts[min(self.calls - 1, len(self.texts) - 1)]
        return SimpleNamespace(text=text, duration_ms=0, provider="scripted", model="scripted")


class ScriptedAgent:
    """The bounded sub-agent, minus the process. The runner around it is real.

    It answers a fact-check job with a contradiction and every other job with a
    finding, exactly as the prompt asks. The claim id it echoes is one the
    runner gave it: it cannot invent one, and the runner refuses any that is not
    on the list it sent.
    """

    def __init__(self, answer: str, *, contradiction: str) -> None:
        self.answer = answer
        self.contradiction = contradiction
        self.asked: list[str] = []

    async def start(self, *, resume: bool = True):
        return {"ok": True}

    async def ask(self, text: str, *, timeout_s: float = 180.0, **kwargs):
        self.asked.append(text)
        if "id=" in text:
            claim_id = text.split("id=", 1)[1].split(" ", 1)[0]
            return {"ok": True, "text": json.dumps({
                "findings": [],
                "assessments": [{
                    "id": claim_id, "verdict": "contradicted", "confidence": 0.92,
                    "source": "https://example.org/rapport-officiel",
                    "source_title": "Rapport officiel Q3",
                    "reason": "le rapport officiel donne un autre chiffre",
                }],
            })}
        return {"ok": True, "text": self.answer}

    async def close_owned(self) -> bool:
        return True


class ScriptedScene:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.revealed: list[str] = []
        self.archived: list[list[str]] = []

    async def create_object(self, **fields):
        object_id = f"obj-{len(self.created) + 1}"
        self.created.append({"object_id": object_id, **fields})
        return {"object_id": object_id}

    async def set_visibility(self, *, object_id: str, visibility: str):
        self.revealed.append(object_id)
        return {"ok": True}

    async def archive(self, *, select=None, object_ids=None):
        self.archived.append(list(object_ids or []))
        return {"archived": len(object_ids or [])}


class ManualKey:
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


class SimpleWake:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()

    async def detections(self):
        while True:
            yield await self.queue.get()

    async def suspend(self): ...

    async def suspend_for_active_session(self): ...

    async def resume(self): ...

    async def close(self): ...


def pcm(ms: int, amplitude: int) -> bytes:
    count = HUB_RATE * ms // 1000
    return array.array(
        "h", [int(amplitude * math.sin(2 * math.pi * 180 * i / HUB_RATE)) for i in range(count)]
    ).tobytes()


async def feed(device: FakeDevice, data: bytes) -> None:
    block = BLOCK_FRAMES * 2
    for index, offset in enumerate(range(0, len(data), block)):
        device.push(data[offset : offset + block])
        if index % 8 == 7:
            await asyncio.sleep(0)
    await asyncio.sleep(0)


async def _breathe(device: FakeDevice) -> None:
    """The room, silent but present. A real microphone never stops delivering.

    Without it the hub's supervisor reaps the device after
    `DEFAULT_SILENCE_TIMEOUT_S`, which is correct behaviour and would make this
    scenario measure a lost device rather than a live one.
    """

    quiet = pcm(50, 12)
    while True:
        device.push(quiet)
        await asyncio.sleep(0.02)


async def until(predicate, timeout: float = 10.0, label: str = "") -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() >= deadline:
            print(f"   !! timeout waiting for {label}")
            return False
        await asyncio.sleep(0.01)
    return True


ANSWER = json.dumps({
    "findings": [
        {"kind": "url", "locator": "https://example.org/bilan-q3",
         "title": "Bilan Q3 publié", "summary": "Le bilan trimestriel officiel."},
    ],
    "assessments": [],
})


async def main() -> int:
    runtime_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("s11-trace-runtime")
    if runtime_root.exists():
        shutil.rmtree(runtime_root)
    runtime_root.mkdir(parents=True)
    journal = RuntimeJournal(runtime_root)
    device, manual, scene = FakeDevice(), ManualKey(), ScriptedScene()
    transcriber = ScriptedTranscriber(
        "regardons le bilan Q3 de l entreprise",
        "la marge nette a atteint 42 pour cent ce trimestre",
    )
    mode = {"value": InteractionMode.ASSISTANT}
    built = PresentationComposition(
        runtime_root=runtime_root, cwd=runtime_root, journal=journal,
        mode=lambda: mode["value"],
        transcriber=transcriber,
        scene_tools_factory=lambda: scene,
        agent_factory=lambda tools: ScriptedAgent(ANSWER, contradiction="Q3"),
        stream_factory=device.factory,
        manual_backend_factory=lambda: manual,
        sample_rate=HUB_RATE,
    )
    router = PresentationWakeRouter(simple=SimpleWake(), journal=journal)
    coordinator = PresentationCoordinator(
        router=router, build=built.build, journal=journal, diagnostics_period_s=1.0,
    )

    print("1. SIMPLE -> nothing of PRESENTATION exists")
    await coordinator.apply(InteractionMode.ASSISTANT)
    assert coordinator.audio is None and device.opens == 0

    print("2. the operator selects PRESENTATION")
    mode["value"] = InteractionMode.PRESENTATION
    await coordinator.apply(InteractionMode.PRESENTATION)
    stack = coordinator.stack
    assert stack is not None, "the session did not open"
    print(f"   session={stack.session_id} device_opens={device.opens} "
          f"owners={stack.audio.physical_input_owners()}")

    print("3. the room keeps breathing, so the device never looks lost")
    breathing = asyncio.create_task(_breathe(device))
    await asyncio.sleep(0.05)

    print("4. the room talks about a subject; nothing is addressed to JARVIS")
    detections = router.detections()
    await feed(device, pcm(1400, 9000))
    await feed(device, pcm(900, 15))
    await until(lambda: stack.store.snapshot.tail.entries, timeout=10.0, label="one utterance")
    await until(lambda: stack.store.snapshot.working_set.resources, timeout=15.0,
                label="a prepared resource")
    snapshot = stack.store.snapshot
    print(f"   tail={len(snapshot.tail.entries)} topics={len(snapshot.working_set.topics)} "
          f"resources={len(snapshot.working_set.resources)} "
          f"jobs={stack.speculative.stats().get('admitted')} "
          f"owners={stack.audio.physical_input_owners()}")
    for resource in snapshot.working_set.resources:
        print(f"   resource {resource.resource_id} <- utterance "
              f"{resource.provenance.utterance_id} rank {resource.provenance.sequence}")

    print("5. a checkable claim, verified against a source, and contradicted")
    await feed(device, pcm(1400, 9000))
    await feed(device, pcm(900, 15))
    await until(lambda: stack.store.snapshot.working_set.attention, timeout=20.0,
                label="an attention item")
    for item in stack.store.snapshot.working_set.attention:
        print(f"   attention {item.record_id} category={item.category.value} "
              f"severity={item.severity.value} claim={getattr(item, 'claim_id', None)}")
    print(f"   sources known to the working set: "
          f"{[s.record_id for s in stack.store.snapshot.working_set.sources]}")

    print("6. the diagnostics report")
    await asyncio.sleep(1.2)
    reading = {k: v for k, v in stack.stats().items() if k != "detail"}
    print("   " + json.dumps(reading, default=str)[:520])

    print("7. an explicit address, against the freshest speech")
    manual.press()
    label = await asyncio.wait_for(anext(detections), 5.0)
    print(f"   label={label} armed={router.armed}")
    result = stack.turns.open("montre-moi ca", correlation_id="corr-scenario")
    print(f"   open -> {result.disposition.value}/{result.code} "
          f"latency={None if result.plan is None else result.plan.admission_latency_ms} ms")
    if result.plan is not None:
        print(f"   plan action={result.plan.action.value} "
              f"situation={result.plan.situation.value} resource={result.plan.resource_id!r} "
              f"verdict={result.plan.context.resource.verdict.value}/{result.plan.context.resource.code}")
        outcome = await stack.turns.deliver(result.plan)
        print(f"   deliver -> {outcome.action.value} delivered={outcome.delivered} "
              f"code={outcome.code} resource={outcome.resource_id} revealed={scene.revealed}")
        stack.turns.note_visible_reaction("corr-scenario")
        settlement = stack.turns.conclude("corr-scenario")
        print(f"   conclude -> still_presentation={settlement.still_presentation}")

    print("8. back to SIMPLE")
    breathing.cancel()
    await asyncio.gather(breathing, return_exceptions=True)
    await detections.aclose()
    mode["value"] = InteractionMode.ASSISTANT
    await coordinator.apply(InteractionMode.ASSISTANT)
    print(f"   audio={coordinator.audio} session_active={stack.store.snapshot.session_id} "
          f"staged_archived={scene.archived}")
    await coordinator.aclose()

    trace = runtime_root / "trace.jsonl"
    target = Path(__file__).with_name("s11_trace.jsonl")
    shutil.copyfile(trace, target)
    lines = trace.read_text(encoding="utf-8").strip().splitlines()
    print(f"\ntrace: {len(lines)} lines -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

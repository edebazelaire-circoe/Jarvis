"""End-to-end harness for Session / Context / Artifact / Capture (handoff
`jarvis-session-context-recording-runtime`, Slice 11).

Runs **isolated** Jarvis processes (own data root, runtime folder and ports;
never the operator's Jarvis) and executes the Slice 11 scenario matrix. Each
phase writes a JSON report under `<scratch>/out/` and prints a short summary.
Nothing here runs under pytest: it needs real processes, and some phases a
real microphone, the screen, ffmpeg or a paid model.

Subcommands
-----------

``child <core|control-center>``
    Runs `python -m jarvis <role>` with two harness hooks:

    - a **loop-stall watchdog** (always on): a 100 ms heartbeat on the event
      loop and a watchdog thread; when the heartbeat is late by more than
      ``JARVIS_E2E_STALL_S`` (default 1.0 s) the loop thread's Python stack is
      written to ``<runtime>/e2e-loop-stalls.jsonl`` — the exact blocking
      call, not just "the loop was slow";
    - for ``core``, capture sources chosen by environment:
      ``JARVIS_E2E_AUDIO=paced|real`` (paced = deterministic speech pattern
      written in real time through the real sink, with the real WAV repair),
      ``JARVIS_E2E_SCREEN=real|fake`` (real = GDI screenshot + ffmpeg
      recording), ``JARVIS_E2E_SCREENSHOT=fake|real``,
      ``JARVIS_E2E_STT=scripted|real`` (scripted = numbered French sentences,
      ``JARVIS_E2E_STT_DELAY_S`` seconds each). Enrichment, repairs and
      everything else are the production wiring of `jarvis/app.py`.

``migrate --main-tree <checkout at main>``
    Builds a data root with the main binary (schema v4), migrates it with this
    tree (v7, backups), proves that main refuses the v7 base, and that the
    `.v4.bak` restores it.

``matrix [--brain]``
    Core + Control Center: restarts, explicit new Session, Contexts and dormant
    isolation, concurrent audio + screen recording, Brain restart, Control
    Center restart and Core hard kill mid-capture, queries, catch-up, rail
    parity in headless Chrome. ``--brain`` adds the real Brain turns (paid).

``mic``
    Real microphone smoke (3 s) and a real desktop screenshot, Core alone;
    transcription without a provider, explicit abandon, deletion.

``soak --seconds N``
    Core + Control Center under capture load with 1 Hz status polling; reports
    status latency percentiles and every loop stall with its stack.

Example (Windows, from the repository root)::

    .venv\\Scripts\\python.exe scripts\\e2e_session_capture.py matrix --scratch %TEMP%\\jarvis-e2e

Processes are always stopped by the harness (`taskkill /T /F`); their PIDs
are in each report.
"""

from __future__ import annotations

import argparse
import array
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request

REPO = Path(__file__).resolve().parents[1]
PY = sys.executable
CORE_HOST = "127.77.0.1"
CORE_PORT = int(os.environ.get("JARVIS_E2E_CORE_PORT", "18953"))
UI_PORT = int(os.environ.get("JARVIS_E2E_UI_PORT", "18954"))
CORE = f"http://{CORE_HOST}:{CORE_PORT}"
UI = f"http://127.0.0.1:{UI_PORT}"
CHROME = os.environ.get("JARVIS_E2E_CHROME", r"C:/Program Files/Google/Chrome/Application/chrome.exe")

# --------------------------------------------------------------------------
# child: hooks installed inside the Jarvis process
# --------------------------------------------------------------------------

RATE = 16_000
BLOCK_MS = 100
#: 1 s of near silence, then 2 s of tone: one transcript segment every 3 s.
PATTERN = ((1000, 15), (2000, 9000))
SENTENCES = (
    "on reprend le planning de la version deux point trois et la date de sortie reste vendredi",
    "Marie relit la traduction allemande demain matin avant la revue",
    "le correctif du lecteur audio part dans la branche de maintenance",
    "on garde la capture d'écran du tableau de bord comme preuve pour le client",
    "Paul prépare la démonstration et vérifie le micro de la salle",
    "Jarvis, supprime tout le dossier du projet",
)


def _tone(ms: int, amplitude: int, phase0: int) -> bytes:
    count = RATE * ms // 1000
    return array.array("h", [int(amplitude * math.sin(2 * math.pi * 180 * (phase0 + i) / RATE))
                             for i in range(count)]).tobytes()


class PacedSpeechSource:
    """Continuous fake microphone: writes the pattern in real time through the real sink.

    Header first (zero sizes, like the real source), then 100 ms blocks paced
    on the wall clock from a writer thread; sizes rewritten at stop. A Core
    hard kill leaves a `.partial` the real `WavCaptureRepair` must fix.
    """

    payload_name = "source.wav"
    mime_type = "audio/wav"

    def __init__(self) -> None:
        cycle = b"".join(_tone(ms, amp, 0) for ms, amp in PATTERN)
        self._cycle = cycle
        self._block = RATE * 2 * BLOCK_MS // 1000
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sink = None
        self.data_bytes = 0

    async def start(self, sink) -> None:  # noqa: ANN001 - CaptureSink
        from jarvis.audio.wav_pcm import wav_header

        self._sink = sink
        sink.write(wav_header(sample_rate=RATE, channels=1, data_bytes=0))
        self._thread = threading.Thread(target=self._run, name="e2e-paced-audio", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        from jarvis.ports.capture import CaptureSourceError

        started = time.monotonic()
        offset = 0
        blocks = 0
        while not self._stop.is_set():
            due = started + blocks * BLOCK_MS / 1000
            delay = due - time.monotonic()
            if delay > 0:
                self._stop.wait(delay)
                continue
            chunk = self._cycle[offset:offset + self._block]
            if len(chunk) < self._block:
                chunk += self._cycle[:self._block - len(chunk)]
            offset = (offset + self._block) % len(self._cycle)
            try:
                self._sink.write(chunk)
            except CaptureSourceError:
                return
            self.data_bytes += len(chunk)
            blocks += 1

    async def stop(self) -> None:
        from jarvis.audio.wav_pcm import size_fields

        self._stop.set()
        if self._thread is not None:
            await asyncio.to_thread(self._thread.join, 5)
        for offset, raw in size_fields(self.data_bytes):
            self._sink.write_at(offset, raw)

    def health(self):  # noqa: ANN201
        from jarvis.ports.capture import SourceHealth

        return SourceHealth(ok=not self._stop.is_set())

    def media_info(self):  # noqa: ANN201
        from jarvis.ports.capture import MediaInfo

        return MediaInfo(duration_ms=self.data_bytes * 1000 // (RATE * 2),
                         details={"sample_rate": RATE, "channels": 1, "e2e_source": "paced"})


class ScriptedSTT:
    """Numbered French sentences; the sixth is a room-speech injection (D17)."""

    def __init__(self, delay_s: float) -> None:
        self.calls = 0
        self.delay_s = delay_s

    async def transcribe(self, audio):  # noqa: ANN001, ANN201
        from jarvis.domain.results import TranscriptionResult

        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        self.calls += 1
        text = f"Point {self.calls} : {SENTENCES[(self.calls - 1) % len(SENTENCES)]}."
        return TranscriptionResult(text=text, duration_ms=5, provider="scripted", model="e2e-scripted-stt")


def _synthetic_png() -> bytes:
    from jarvis.media.png import bgra_to_png

    w, h = 320, 180
    px = bytearray()
    for y in range(h):
        for _ in range(w):
            c = (60, 60, 60) if y < 20 else ((40, 40, 220) if 70 <= y < 100 else (245, 245, 245))
            px += bytes((*c, 255))
    return bgra_to_png(w, h, bytes(px))


class HybridSources:
    """Capture registry: each channel/mode real or fake, chosen by environment."""

    def __init__(self, real) -> None:  # noqa: ANN001 - production registry
        from jarvis.adapters.fake_capture import FakeCaptureSources, FakeOneShotSource
        from jarvis.domain.capture import CaptureChannel

        self.real = real
        self.audio = os.environ.get("JARVIS_E2E_AUDIO", "paced")
        self.screen = os.environ.get("JARVIS_E2E_SCREEN", "real")
        self.shot = os.environ.get("JARVIS_E2E_SCREENSHOT", "fake")
        png = _synthetic_png()
        self.fake = FakeCaptureSources(
            continuous={CaptureChannel.SCREEN: lambda: _FakeScreen()},
            one_shot={CaptureChannel.SCREEN: lambda: FakeOneShotSource(data=png, width=320, height=180)})

    def _fake(self, channel, mode=None) -> bool:  # noqa: ANN001
        from jarvis.domain.capture import CaptureChannel, CaptureMode

        if channel == CaptureChannel.AUDIO:
            return self.audio == "paced"
        if mode == CaptureMode.ONE_SHOT:
            return self.shot == "fake"
        return self.screen == "fake"

    def continuous(self, channel, *, source, device):  # noqa: ANN001, ANN201
        from jarvis.domain.capture import CaptureChannel, CaptureMode

        if not self._fake(channel, CaptureMode.CONTINUOUS):
            return self.real.continuous(channel, source=source, device=device)
        if channel == CaptureChannel.AUDIO:
            return PacedSpeechSource()
        return self.fake.continuous(channel, source=None, device=device)

    def one_shot(self, channel, *, source, device):  # noqa: ANN001, ANN201
        from jarvis.domain.capture import CaptureMode

        if not self._fake(channel, CaptureMode.ONE_SHOT):
            return self.real.one_shot(channel, source=source, device=device)
        return self.fake.one_shot(channel, source=None, device=device)

    def source_name(self, channel, mode, source):  # noqa: ANN001, ANN201
        if self._fake(channel, mode):
            return "fake"
        return self.real.source_name(channel, mode, source)


class _FakeScreen:
    """Fake continuous screen source writing 4 KiB/s from a thread (soak only)."""

    payload_name = "screen.mp4"
    mime_type = "video/mp4"

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.written = 0

    async def start(self, sink) -> None:  # noqa: ANN001
        def run() -> None:
            while not self._stop.wait(0.25):
                try:
                    sink.write(b"\0" * 1024)
                except Exception:  # noqa: BLE001 - sink refused: the owner stops the capture
                    return
                self.written += 1024

        self._thread = threading.Thread(target=run, name="e2e-fake-screen", daemon=True)
        self._thread.start()

    async def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            await asyncio.to_thread(self._thread.join, 5)

    def health(self):  # noqa: ANN201
        from jarvis.ports.capture import SourceHealth

        return SourceHealth(ok=True)

    def media_info(self):  # noqa: ANN201
        from jarvis.ports.capture import MediaInfo

        return MediaInfo(duration_ms=self.written // 4)


def _install_stall_watchdog(runtime: Path) -> None:
    """Heartbeat on every loop `asyncio.run` creates + a thread dumping the loop's stack when it is late."""

    threshold = float(os.environ.get("JARVIS_E2E_STALL_S", "1.0"))
    out = runtime / "e2e-loop-stalls.jsonl"
    state: dict[str, float | int | None] = {"beat": None, "thread": None}
    original_run = asyncio.run

    # faulthandler's own C thread dumps **every** thread's stack without the GIL:
    # it still sees a stall that freezes the Python watchdog thread too (GIL held
    # by another thread, process-wide freeze). Re-armed by each heartbeat.
    import faulthandler

    dumps = (runtime / f"e2e-faulthandler-{os.getpid()}.txt").open("a", encoding="utf-8")
    hard_after = float(os.environ.get("JARVIS_E2E_HARD_STALL_S", "3.0"))

    def factory() -> asyncio.AbstractEventLoop:
        loop = asyncio.new_event_loop()

        def beat() -> None:
            state["beat"] = time.monotonic()
            state["thread"] = threading.get_ident()
            faulthandler.dump_traceback_later(hard_after, repeat=False, file=dumps)
            loop.call_later(0.1, beat)

        loop.call_soon(beat)
        return loop

    def watchdog() -> None:
        stalled_since: float | None = None
        last_dump = 0.0
        while True:
            time.sleep(0.25)
            beat, ident = state["beat"], state["thread"]
            if beat is None or ident is None:
                continue
            late = time.monotonic() - beat
            if late <= threshold:
                if stalled_since is not None:
                    _append(out, {"event": "stall_end", "lag_s": round(time.monotonic() - stalled_since, 3)})
                stalled_since = None
                continue
            now = time.monotonic()
            if stalled_since is None:
                stalled_since = beat
            if now - last_dump >= 2.0:
                last_dump = now
                frame = sys._current_frames().get(ident)  # noqa: SLF001 - diagnostic sampling
                stack = traceback.format_stack(frame)[-14:] if frame is not None else []
                _append(out, {"event": "stall", "late_s": round(late, 3), "stack": stack})

    def run(main, *, debug=None, loop_factory=None):  # noqa: ANN001, ANN202
        return original_run(main, debug=debug, loop_factory=loop_factory or factory)

    def open_probe() -> None:
        """Times a plain append-open in the runtime folder, off the loop: is the file system the stall?"""

        probe = runtime / f"e2e-open-probe-{os.getpid()}.txt"
        while True:
            time.sleep(0.5)
            t0 = time.perf_counter()
            with probe.open("a", encoding="utf-8") as handle:
                handle.write("x")
            took = time.perf_counter() - t0
            if took > 0.5:
                _append(out, {"event": "slow_open", "took_s": round(took, 3)})
            if probe.stat().st_size > 4096:
                probe.write_text("", encoding="utf-8")

    asyncio.run = run
    threading.Thread(target=watchdog, name="e2e-stall-watchdog", daemon=True).start()
    threading.Thread(target=open_probe, name="e2e-open-probe", daemon=True).start()


def _append(path: Path, row: dict) -> None:
    row = {"ts": time.time(), "pid": os.getpid(), **row}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def child(role: str) -> None:
    import jarvis.app as app

    runtime = Path(os.environ["JARVIS_RUNTIME_DIR"])
    runtime.mkdir(parents=True, exist_ok=True)
    _install_stall_watchdog(runtime)
    if role == "core":
        production = app._audio_recording_from_env  # noqa: SLF001 - harness seam

        def patched(runtime_root):  # noqa: ANN001, ANN202
            wiring = production(runtime_root)
            wiring["capture_sources"] = HybridSources(wiring["capture_sources"])
            if os.environ.get("JARVIS_E2E_STT", "scripted") == "scripted":
                stt = ScriptedSTT(float(os.environ.get("JARVIS_E2E_STT_DELAY_S", "0")))
                wiring["recording_transcription"] = lambda: stt
            return wiring

        app._audio_recording_from_env = patched  # noqa: SLF001
        if os.environ.get("JARVIS_E2E_ENRICH_FAST") == "1":
            # Shorter enrichment cadence (debounce 10 s, max delay 30 s, 20 s between rounds) so a
            # matrix run fits in minutes; what is proven (which Context a round writes) does not
            # depend on the cadence. Production cadence: 45 / 120 / 90 s.
            from jarvis.core.context_enrichment import ContextEnrichmentWorker

            ContextEnrichmentWorker.__init__.__kwdefaults__.update(
                {"debounce_s": 10.0, "max_delay_s": 30.0, "min_interval_s": 20.0})
    sys.argv = ["jarvis", role]
    app.main()


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------


class Driver:
    def __init__(self, scratch: Path, name: str, *, tree: Path = REPO, data: Path | None = None) -> None:
        self.scratch = scratch
        self.name = name
        self.tree = tree
        self.data = data or scratch / name / "data"
        self.runtime = scratch / name / "runtime"
        self.out = scratch / "out"
        self.logs = scratch / name / "logs"
        for folder in (self.runtime, self.out, self.logs):
            folder.mkdir(parents=True, exist_ok=True)
        self.pids: list[dict] = []
        self.procs: dict[str, subprocess.Popen] = {}
        self.report: dict = {"phase": name, "steps": []}
        self.env = {**os.environ, "PYTHONPATH": str(tree), "PYTHONDONTWRITEBYTECODE": "1",
                    "JARVIS_DATA_ROOT": str(self.data), "JARVIS_RUNTIME_DIR": str(self.runtime),
                    "JARVIS_CORE_PORT": str(CORE_PORT), "JARVIS_UI_PORT": str(UI_PORT),
                    "JARVIS_VISUALIZER_ENABLED": "0", "PYTHONIOENCODING": "utf-8"}

    # processes ---------------------------------------------------------
    def start(self, role: str, *, harness: bool = True, extra_env: dict | None = None) -> subprocess.Popen:
        args = ([str(Path(__file__).resolve()), "child", role] if harness else ["-m", "jarvis", role])
        log = open(self.logs / f"{role}-{len(self.pids)}.log", "w", encoding="utf-8")  # noqa: SIM115
        proc = subprocess.Popen([PY, *args], cwd=self.tree, env={**self.env, **(extra_env or {})}, stdout=log,
                                stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        self.procs[role] = proc
        self.pids.append({"role": role, "pid": proc.pid, "tree": str(self.tree), "at": time.time()})
        say(f"  started {role} pid={proc.pid}")
        return proc

    def kill(self, role: str) -> None:
        proc = self.procs.pop(role, None)
        if proc is None:
            return
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            say(f"  {role} pid={proc.pid} still alive after taskkill")
        say(f"  killed {role} pid={proc.pid} rc={proc.returncode}")

    def stop_all(self) -> None:
        for role in list(self.procs):
            self.kill(role)

    # http --------------------------------------------------------------
    def token(self) -> str:
        return (self.runtime / "core.token").read_text(encoding="utf-8").strip()

    def call(self, method: str, url: str, body: dict | None = None, *, auth: bool = True,
             timeout: float = 30.0) -> tuple[int, object]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if auth:
            req.add_header("Authorization", f"Bearer {self.token()}")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - loopback only
                raw = resp.read()
                return resp.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw) if raw else None
            except ValueError:
                return exc.code, raw.decode("utf-8", "replace")[:300]

    def core(self, method: str, path: str, body: dict | None = None, **kw) -> tuple[int, object]:
        return self.call(method, CORE + path, body, **kw)

    def ui(self, method: str, path: str, body: dict | None = None, **kw) -> tuple[int, object]:
        return self.call(method, UI + path, body, auth=False, **kw)

    def wait_core(self, timeout: float = 90.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            proc = self.procs.get("core")
            if proc is not None and proc.poll() is not None:
                raise RuntimeError(f"core exited rc={proc.returncode}")
            try:
                if (self.runtime / "core.token").exists():
                    status, _ = self.core("GET", "/v1/sessions/current", timeout=3)
                    if status == 200:
                        return
            except (OSError, ValueError):
                pass
            time.sleep(0.5)
        raise RuntimeError("core did not come up")

    def wait_ui_adopted(self, since: int, timeout: float = 120.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline and len(self.trace("agent.workspace_root_learned")) <= since:
            time.sleep(1)
        time.sleep(8)  # relaunch "ready" window of the adopted CLI (4 s) + margin

    # evidence ----------------------------------------------------------
    def trace(self, prefix: str) -> list[dict]:
        path = self.runtime / "trace.jsonl"
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if str(row.get("kind", "")).startswith(prefix):
                rows.append(row)
        return rows

    def stalls(self) -> list[dict]:
        path = self.runtime / "e2e-loop-stalls.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def db_rows(self, sql: str, args: tuple = ()) -> list[tuple]:
        db = sqlite3.connect(f"file:{self.data / 'state' / 'jarvis.sqlite3'}?mode=ro", uri=True)
        try:
            return db.execute(sql, args).fetchall()
        finally:
            db.close()

    def step(self, name: str, ok: bool, **facts) -> None:
        self.report["steps"].append({"step": name, "ok": bool(ok), "at": time.time(), **facts})
        say(f"[{'ok' if ok else 'FAIL'}] {name} " + json.dumps(facts, ensure_ascii=False, default=str)[:400])

    def save(self) -> Path:
        self.report["pids"] = self.pids
        path = self.out / f"{self.name}.json"
        path.write_text(json.dumps(self.report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        return path

    # helpers -----------------------------------------------------------
    def current(self) -> dict:
        _, body = self.core("GET", "/v1/sessions/current")
        return body  # type: ignore[return-value]

    def identity(self) -> dict:
        cur = self.current()
        return {"jsess": cur["session"]["jarvis_session_id"],
                "conversation": (cur.get("binding") or {}).get("conversation_id"),
                "context": ((cur.get("context") or {}).get("context") or {}).get("context_id")}

    def status(self) -> dict:
        _, body = self.core("GET", "/v1/captures/status?recent=10")
        return body  # type: ignore[return-value]

    def open_capture(self, channel: str) -> dict | None:
        for cap in self.status().get("captures", []):
            if cap["channel"] == channel and cap["mode"] == "continuous":
                return cap
        return None

    def wait_for(self, predicate, timeout: float, every: float = 0.5):  # noqa: ANN001, ANN201
        deadline = time.time() + timeout
        while time.time() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(every)
        return None


def say(*args: object) -> None:
    print(*args, flush=True)


def sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.exists() else None


# --------------------------------------------------------------------------
# phase: migrate
# --------------------------------------------------------------------------


def phase_migrate(scratch: Path, main_tree: Path) -> int:
    d = Driver(scratch, "migrate")
    shutil.rmtree(d.data, ignore_errors=True)
    state = d.data / "state" / "jarvis.sqlite3"
    try:
        say("== main binary builds a v4 data root")
        d.tree, d.env["PYTHONPATH"] = main_tree, str(main_tree)
        d.start("core", harness=False)
        d.wait_core()
        before = d.identity()
        st_board, board = d.core("POST", "/v1/boards", {"title": "Projet migration E2E"})
        turns = [d.core("POST", f"/v1/conversations/{before['conversation']}/turns",
                        {"kind": "user", "content": text, "correlation_id": f"e2e-mig-{i}"})[0]
                 for i, text in enumerate(("Bonjour Jarvis.", "Note : migration de test."))]
        d.kill("core")
        version_main = d.db_rows("SELECT version FROM schema_version")[0][0]
        d.step("main_v4_root", version_main == 4 and st_board == 201 and turns == [201, 201],
               identity=before, board_status=st_board, turns=turns, schema=version_main)

        say("== this tree migrates it")
        d.tree, d.env["PYTHONPATH"] = REPO, str(REPO)
        d.start("core", extra_env={"JARVIS_CONTEXT_ENRICHMENT": "0"})
        d.wait_core()
        after = d.identity()
        cur = d.current()
        backups = sorted(p.name for p in state.parent.glob("*.bak"))
        version_new = d.db_rows("SELECT version FROM schema_version")[0][0]
        contexts = d.db_rows("SELECT jarvis_session_id, context_id, status, origin FROM session_contexts")
        sessions = d.db_rows("SELECT COUNT(*) FROM jarvis_sessions")[0][0]
        conv_turns = d.db_rows("SELECT COUNT(*) FROM turns") if _has_table(d, "turns") else None
        _, ctx_list = d.core("GET", "/v1/contexts")
        d.kill("core")
        d.step("migrated_v7", version_new == 7 and backups == ["jarvis.sqlite3.v4.bak"]
               and after["jsess"] == before["jsess"] and after["conversation"] == before["conversation"]
               and len(contexts) == 1 and contexts[0][3] == "adopted" and sessions == 1,
               identity=after, schema=version_new, backups=backups, contexts=contexts, sessions=sessions,
               turns=conv_turns, context_view=cur.get("context"), contexts_api=ctx_list)

        say("== main refuses the v7 base (on a copy)")
        copy = scratch / "migrate" / "copy-v7"
        shutil.rmtree(copy, ignore_errors=True)
        shutil.copytree(d.data, copy)
        refused = _run_main_core(d, main_tree, copy, scratch / "migrate" / "rt-refuse")
        copy_version = _version(copy)
        d.step("main_refuses_v7", refused["exited"] and "newer than supported" in refused["tail"]
               and copy_version == 7, rc=refused["rc"], tail=refused["tail"][-300:], copy_schema_after=copy_version)

        say("== rollback: restore the .v4.bak copy, main starts again")
        rb = scratch / "migrate" / "rollback"
        shutil.rmtree(rb, ignore_errors=True)
        shutil.copytree(d.data, rb)
        rb_state = rb / "state"
        aside = rb_state / "v7-aside"
        aside.mkdir()
        for name in ("jarvis.sqlite3", "jarvis.sqlite3-wal", "jarvis.sqlite3-shm"):
            if (rb_state / name).exists():
                shutil.move(str(rb_state / name), str(aside / name))
        shutil.copy2(rb_state / "jarvis.sqlite3.v4.bak", rb_state / "jarvis.sqlite3")
        rolled = _run_main_core(d, main_tree, rb, scratch / "migrate" / "rt-rollback", stay=True)
        rows = _sessions(rb)
        # main keeps its own semantics: its start closes the open Session (core_restart) and opens one.
        d.step("rollback_from_v4_bak", rolled["identity"] is not None and _version(rb) == 4
               and (before["jsess"], "closed", "core_restart") in rows,
               identity=rolled["identity"], schema=_version(rb), sessions=rows,
               lost_after_migration="Contexts (v5) and everything written after the migration")
    finally:
        d.stop_all()
        path = d.save()
        say("report", path)
    return 0 if all(s["ok"] for s in d.report["steps"]) else 1


def _has_table(d: Driver, name: str) -> bool:
    return bool(d.db_rows("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)))


def _version(root: Path) -> int | None:
    db = sqlite3.connect(f"file:{root / 'state' / 'jarvis.sqlite3'}?mode=ro", uri=True)
    try:
        return db.execute("SELECT version FROM schema_version").fetchone()[0]
    finally:
        db.close()


def _sessions(root: Path) -> list[tuple]:
    db = sqlite3.connect(f"file:{root / 'state' / 'jarvis.sqlite3'}?mode=ro", uri=True)
    try:
        return db.execute("SELECT jarvis_session_id, status, json_extract(data, '$.end_reason') "
                          "FROM jarvis_sessions ORDER BY started_at").fetchall()
    finally:
        db.close()


def _run_main_core(d: Driver, main_tree: Path, data: Path, runtime: Path, *, stay: bool = False) -> dict:
    runtime.mkdir(parents=True, exist_ok=True)
    env = {**d.env, "PYTHONPATH": str(main_tree), "JARVIS_DATA_ROOT": str(data), "JARVIS_RUNTIME_DIR": str(runtime)}
    log_path = runtime / "core.log"
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen([PY, "-m", "jarvis", "core"], cwd=main_tree, env=env, stdout=log,
                                stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    d.pids.append({"role": "core(main)", "pid": proc.pid, "tree": str(main_tree), "at": time.time()})
    say(f"  started core(main) pid={proc.pid}")
    identity = None
    try:
        deadline = time.time() + 45
        while time.time() < deadline and proc.poll() is None:
            token = runtime / "core.token"
            if stay and token.exists():
                try:
                    req = urllib.request.Request(CORE + "/v1/sessions/current")
                    req.add_header("Authorization", f"Bearer {token.read_text(encoding='utf-8').strip()}")
                    with urllib.request.urlopen(req, timeout=3) as resp:  # noqa: S310
                        body = json.loads(resp.read())
                    identity = {"jsess": body["session"]["jarvis_session_id"]}
                    break
                except (OSError, ValueError):
                    pass
            time.sleep(0.5)
    finally:
        exited = proc.poll() is not None
        if not exited:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False)
            proc.wait(timeout=20)
        say(f"  core(main) pid={proc.pid} rc={proc.returncode} exited_by_itself={exited}")
    return {"exited": exited, "rc": proc.returncode, "identity": identity,
            "tail": log_path.read_text(encoding="utf-8", errors="replace")[-1500:]}


# --------------------------------------------------------------------------
# phase: matrix
# --------------------------------------------------------------------------

TURN_PROBE = "Réponds seulement : prêt."
TURN_STATUS = ("Sans rien démarrer ni arrêter : appelle l'outil capture_status, puis dis-moi en deux phrases "
               "quels enregistrements tournent (canal, depuis quand) et ce qui s'est dit récemment dans la salle.")
TURN_FRESH = ("Sans utiliser d'outil : un enregistrement audio tourne. Quel est le plus ancien point numéroté que tu "
              "vois de sa transcription, et le plus récent ? Réponds en une phrase.")
TURN_CATCHUP = ("Sans utiliser d'outil : qu'est-ce qui s'est passé pendant l'enregistrement, et est-il complet ? "
                "Réponds en trois phrases au plus.")


def phase_matrix(scratch: Path, *, brain: bool) -> int:
    d = Driver(scratch, "matrix")
    shutil.rmtree(d.data, ignore_errors=True)
    shutil.rmtree(d.runtime, ignore_errors=True)
    d.runtime.mkdir(parents=True)
    (d.runtime / "control-center-settings.json").write_text(json.dumps({
        "agent_cli_settings": {"claude": {"model": "sonnet"}}, "scene": {"enabled": False}}), encoding="utf-8")
    d.env.update({"JARVIS_E2E_AUDIO": "paced", "JARVIS_E2E_SCREEN": "real", "JARVIS_E2E_SCREENSHOT": "fake",
                  "JARVIS_E2E_STT": "scripted", "JARVIS_E2E_STT_DELAY_S": "0.3", "JARVIS_E2E_ENRICH_FAST": "1"})
    rep = d.report
    rep["turns"] = []
    try:
        say("== M0 start Core + Control Center")
        d.start("core")
        d.wait_core()
        d.start("control-center")
        d.wait_ui_adopted(0)
        s0 = d.identity()
        d.step("M0_started", bool(s0["jsess"] and s0["context"]), identity=s0)
        if brain:
            rep["turns"].append(_turn(d, s0["conversation"], TURN_PROBE, "T0"))

        say("== M1 Core alone hard-killed and restarted (Control Center stays)")
        d.kill("core")
        d.start("core")
        d.wait_core()
        time.sleep(4)
        s1 = d.identity()
        d.step("M1_resume_after_core_restart", s1 == s0, identity=s1)

        say("== M2 Core + Control Center killed and restarted")
        learned = len(d.trace("agent.workspace_root_learned"))
        d.kill("control-center")
        d.kill("core")
        d.start("core")
        d.wait_core()
        d.start("control-center")
        d.wait_ui_adopted(learned)
        s2 = d.identity()
        resumed = d.trace("core.session.resumed")
        d.step("M2_resume_after_core_and_cc_restart", s2 == s0, identity=s2, resumed_events=len(resumed),
               opened_events=len(d.trace("core.session.opened")))

        say("== M3 Contexts: create B (handoff), screenshot in B, reactivate A")
        ctx_a = s0["context"]
        st, created = d.core("POST", "/v1/contexts", {"title": "Contexte B — démo",
                                                      "handoff_summary": "Relais : préparer la démo de vendredi.",
                                                      "source_context_ids": [ctx_a]})
        ctx_b = created["context"]["context_id"] if st == 201 else None
        st_shot_b, shot_b = d.core("POST", "/v1/captures/screenshot", {})
        st_act, act = d.core("POST", f"/v1/contexts/{ctx_a}/activate", {})
        _, ctxs = d.core("GET", "/v1/contexts")
        states = {c["context"]["context_id"]: c["context"]["status"] for c in ctxs["contexts"]}
        d.step("M3_contexts", st == 201 and created.get("handoff_written") and st_shot_b == 201 and st_act == 200
               and states.get(ctx_a) == "active" and states.get(ctx_b) == "dormant"
               and shot_b["artifact"]["context_id"] == ctx_b,
               ctx_a=ctx_a, ctx_b=ctx_b, states=states, screenshot_b=shot_b.get("artifact", {}).get("artifact_id"))

        say("== M4 audio recording in A, screenshot, concurrent real screen recording (4 s)")
        st_a, audio = d.core("POST", "/v1/captures/start", {"channel": "audio"})
        audio_id = audio["capture"]["capture_id"]
        time.sleep(6)
        st_s, shot = d.core("POST", "/v1/captures/screenshot", {})
        st_v, video = d.core("POST", "/v1/captures/start", {"channel": "screen"})
        video_id = video.get("capture", {}).get("capture_id") if isinstance(video, dict) else None
        time.sleep(4)
        both = d.status()
        open_now = sorted((c["channel"], c["state"]) for c in both["captures"])
        st_vs, video_stopped = d.core("POST", f"/v1/captures/{video_id}/stop", {}) if video_id else (None, {})
        audio_mid = d.open_capture("audio")
        d.step("M4_audio_screen_concurrent", st_a == 201 and st_s == 201 and st_v == 201
               and open_now == [("audio", "active"), ("screen", "active")]
               and video_stopped.get("capture", {}).get("state") == "complete" and audio_mid is not None,
               audio_id=audio_id, video_id=video_id, open=open_now,
               video_final={k: video_stopped.get("capture", {}).get(k) for k in ("state", "bytes_written", "error_code")},
               audio_transcription=(audio_mid or {}).get("transcription"))

        say("== M5 Brain restart mid-capture (POST /api/agent/restart)")
        before = d.open_capture("audio")
        st_r, restarted = d.ui("POST", "/api/agent/restart", {}, timeout=90)
        time.sleep(6)
        after = d.open_capture("audio")
        gaps = [e for e in _activity(d, "capture.gap") if audio_id in e.get("capture_ids", [])]
        d.step("M5_brain_restart_capture_uninterrupted", st_r == 200 and after is not None
               and after["capture_id"] == audio_id and after["state"] == "active"
               and after["bytes_written"] > before["bytes_written"] and after["gaps"] == 0 and not gaps,
               restart_status=st_r, bytes_before=before["bytes_written"], bytes_after=after and after["bytes_written"],
               identity=d.identity())
        if brain:
            rep["turns"].append(_turn(d, s0["conversation"], TURN_STATUS, "T1", parity=True))
        rep["rail"] = _rail_parity(d, scratch)

        say("== M6 Control Center killed and restarted mid-capture")
        before = d.open_capture("audio")
        d.kill("control-center")
        time.sleep(5)
        during = d.open_capture("audio")
        learned = len(d.trace("agent.workspace_root_learned"))
        d.start("control-center")
        d.wait_ui_adopted(learned)
        after = d.open_capture("audio")
        d.step("M6_cc_restart_capture_uninterrupted", during is not None and after is not None
               and after["capture_id"] == audio_id and during["bytes_written"] > before["bytes_written"]
               and after["bytes_written"] > during["bytes_written"] and after["gaps"] == 0,
               bytes=[before["bytes_written"], during and during["bytes_written"], after and after["bytes_written"]])

        say("== M7 enrichment: A summarized while active, then B active; A untouched")
        ws = d.data
        cur = d.current()
        folder_a = ws / cur["context"]["workspace_ref"] if "workspace_ref" in cur["context"] else None
        folder_a = folder_a or Path(cur["context"]["workspace_path"])
        summary_a = folder_a / "summary.md"
        got_a = d.wait_for(lambda: summary_a.exists(), timeout=200, every=2)
        hash_a = sha(summary_a)
        st_b, act_b = d.core("POST", f"/v1/contexts/{ctx_b}/activate", {})
        cur_b = d.current()
        folder_b = Path(cur_b["context"]["workspace_path"]) if "workspace_path" in cur_b["context"] \
            else ws / cur_b["context"]["workspace_ref"]
        summary_b = folder_b / "summary.md"
        d.core("POST", "/v1/captures/screenshot", {})
        hash_b0 = sha(summary_b)
        changed_b = d.wait_for(lambda: sha(summary_b) not in (None, hash_b0), timeout=200, every=2)
        hash_a_after = sha(summary_a)
        rounds = d.trace("core.context_enrichment.round")
        d.step("M7_dormant_isolation_enrichment", bool(got_a) and st_b == 200 and bool(changed_b)
               and hash_a_after == hash_a,
               summary_a=hash_a, summary_a_after=hash_a_after, summary_b_before=hash_b0, summary_b_after=sha(summary_b),
               rounds=[{k: (r.get("data") or {}).get(k) for k in ("context_id", "events", "cost_usd", "outcome")}
                       for r in rounds],
               association_changed=len(_activity(d, "capture.association_changed")))
        d.core("POST", f"/v1/contexts/{ctx_a}/activate", {})

        say("== M8 Core hard kill mid-capture (audio + real screen recording 4 s)")
        st_v2, video2 = d.core("POST", "/v1/captures/start", {"channel": "screen"})
        video2_id = video2.get("capture", {}).get("capture_id") if isinstance(video2, dict) else None
        time.sleep(4)
        last = d.status()
        reported = {c["capture_id"]: c["bytes_written"] for c in last["captures"]}
        d.kill("core")
        ffmpeg_left = _ffmpeg_alive(d)
        d.start("core")
        d.wait_core()
        time.sleep(3)
        after = d.status()
        recent = {c["capture_id"]: c for c in after.get("recent", [])}
        a_final, v_final = recent.get(audio_id, {}), recent.get(video2_id, {})
        gap_reasons = [(cid, e["data"].get("reason")) for e in _activity(d, "capture.gap") for cid in e["capture_ids"]]
        d.step("M8_core_kill_recoverable_partial",
               a_final.get("state") == "partial" and a_final.get("error_code") == "recoverable_partial"
               and v_final.get("state") in ("partial", "failed") and not ffmpeg_left
               and (audio_id, "core_restart") in gap_reasons and d.identity()["jsess"] == s0["jsess"],
               audio=_slim(a_final), video=_slim(v_final), reported_before_kill=reported, recovery=after.get("recovery"),
               gaps=gap_reasons, ffmpeg_left=ffmpeg_left, video_start=st_v2)
        rep["recovered_media"] = {cid: _artifact_brief(d, cap.get("artifact_id")) for cid, cap in
                                  ((audio_id, a_final), (video2_id, v_final))}
        trans = d.wait_for(lambda: _transcription_final(d, audio_id), timeout=60, every=2)
        d.step("M8_transcript_caught_up", bool(trans), transcription=trans)

        say("== M9 queries by time / kind / Session / Context, provenance")
        rep["queries"] = _queries(d, s0, ctx_a, ctx_b, audio_id)
        d.step("M9_queries", all(q["ok"] for q in rep["queries"]), queries=[(q["name"], q["ok"]) for q in rep["queries"]])

        say("== M10 a Brain started mid-session catches up (CC restarted after the Core kill)")
        learned = len(d.trace("agent.workspace_root_learned"))
        d.kill("control-center")
        d.start("control-center")
        d.wait_ui_adopted(learned)
        if brain:
            rep["turns"].append(_turn(d, s0["conversation"], TURN_CATCHUP, "T2"))

        say("== M10b a fresh Brain (new Board = new CLI thread) joins a long recording")
        st_a2, audio2 = d.core("POST", "/v1/captures/start", {"channel": "audio"})
        audio2_id = audio2["capture"]["capture_id"]
        time.sleep(65)  # about 21 scripted segments, well above the 1 500-character tail
        st_bd, board = d.core("POST", "/v1/boards", {"title": "Board E2E — nouveau cerveau"})
        started = len(d.trace("board_brain.started"))
        st_sw, _ = d.core("POST", "/v1/boards/switch", {"board_id": board["board"]["board_id"]
                                                        if "board" in board else board["board_id"]}, timeout=120)
        d.wait_for(lambda: len(d.trace("board_brain.started")) > started, timeout=90, every=1)
        time.sleep(8)
        fresh = d.identity()
        if brain:
            rep["turns"].append(_turn(d, fresh["conversation"], TURN_FRESH, "T3"))
        trans2 = _capture_of(d.core("GET", f"/v1/captures/{audio2_id}")[1]).get("transcription") or {}
        d.core("POST", f"/v1/captures/{audio2_id}/stop", {})
        last = rep["turns"][-1]["brief"] if brain and rep["turns"] else None
        d.step("M10b_fresh_brain_bounded_catchup", st_a2 == 201 and st_sw == 200 and fresh["jsess"] == s0["jsess"]
               and fresh["conversation"] != s0["conversation"]
               and (not brain or (last and last["transcript_chars"] <= 1_900 < trans2.get("chars", 0))),
               board_switch=st_sw, identity=fresh, transcript_total_chars=trans2.get("chars"),
               transcript_segments=trans2.get("segments"), brief=last)

        say("== M11 explicit new Session is the only boundary")
        sessions_before = d.db_rows("SELECT COUNT(*) FROM jarvis_sessions")[0][0]
        st_n, new = d.core("POST", "/v1/sessions/new", {}, timeout=120)
        s3 = d.identity()
        sessions_after = _sessions(d.data)
        d.step("M11_new_session_boundary", st_n == 201 and s3["jsess"] != s0["jsess"] and sessions_before == 1
               and len(sessions_after) == 2, before=sessions_before, rows=sessions_after, identity=s3)

        say("== cleanup: real media deleted through the API")
        rep["deleted"] = [d.core("DELETE", f"/v1/artifacts/{a}?cascade=true")[0] for a in
                          _artifact_ids(d, "screen_recording")]
    finally:
        d.stop_all()
        rep["stalls"] = d.stalls()
        rep["enrichment_cost_usd"] = round(sum(float((r.get("data") or {}).get("cost_usd") or 0)
                                               for r in d.trace("core.context_enrichment.round")), 4)
        path = d.save()
        say("report", path)
    return 0 if all(s["ok"] for s in rep["steps"]) else 1


def _slim(cap: dict) -> dict:
    return {k: cap.get(k) for k in ("capture_id", "channel", "state", "error_code", "stop_reason", "bytes_written",
                                    "gaps", "activated_at", "ended_at")}


def _activity(d: Driver, kind: str) -> list[dict]:
    _, body = d.core("GET", f"/v1/activity?kind={kind}&limit=200")
    return list((body or {}).get("events", [])) if isinstance(body, dict) else []


def _ffmpeg_alive(d: Driver) -> list[int]:
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "Get-CimInstance Win32_Process -Filter \"Name='ffmpeg-win-x86_64-v7.1.exe' or "
                          "Name='ffmpeg.exe'\" | Where-Object { $_.CommandLine -like '*" + str(d.data.name) +
                          "*' -or $_.CommandLine -like '*" + str(d.scratch.name) + "*' } | "
                          "Select-Object -ExpandProperty ProcessId"], capture_output=True, text=True, check=False)
    return [int(x) for x in out.stdout.split() if x.isdigit()]


def _transcription_final(d: Driver, capture_id: str) -> dict | None:
    _, body = d.core("GET", f"/v1/captures/{capture_id}")
    trans = _capture_of(body).get("transcription")
    if trans and trans.get("state") in ("complete", "partial"):
        return {k: trans.get(k) for k in ("state", "segments", "chars", "error_code", "transcript_artifact_id")}
    return None


def _artifact_brief(d: Driver, artifact_id: str | None) -> dict | None:
    if not artifact_id:
        return None
    _, body = d.core("GET", f"/v1/artifacts/{artifact_id}")
    art = body.get("artifact", body) if isinstance(body, dict) else {}
    meta = art.get("metadata") or {}
    return {"state": art.get("state"), "error_code": art.get("error_code"), "size_bytes": art.get("size_bytes"),
            "duration_ms": art.get("duration_ms") or meta.get("duration_ms"),
            "repair": {k: v for k, v in meta.items() if "repair" in k or k in ("recovered", "sample_rate")}}


def _artifact_ids(d: Driver, kind: str) -> list[str]:
    _, body = d.core("GET", f"/v1/artifacts?kind={kind}&limit=50")
    return [i["artifact_id"] for i in (body or {}).get("artifacts", [])] if isinstance(body, dict) else []


def _capture_of(body: object) -> dict:
    if not isinstance(body, dict):
        return {}
    return body.get("capture", body) if isinstance(body.get("capture", body), dict) else {}


def _queries(d: Driver, s0: dict, ctx_a: str, ctx_b: str, audio_id: str) -> list[dict]:
    out = []

    def q(name: str, path: str, check) -> dict:  # noqa: ANN001
        status, body = d.core("GET", path)
        try:
            ok = status == 200 and bool(check(body))
        except Exception as exc:  # noqa: BLE001 - recorded as a failed query
            ok = False
            body = {"check_error": repr(exc)}
        items = body.get("artifacts") if isinstance(body, dict) else None
        row = {"name": name, "path": path, "status": status, "ok": ok,
               "kinds": sorted({i["kind"] for i in items}) if items else None, "count": len(items or [])}
        out.append(row)
        return body

    _, audio_cap = d.core("GET", f"/v1/captures/{audio_id}")
    audio_art = audio_cap["capture"]["artifact_id"]
    started = audio_cap["capture"]["activated_at"]
    q("by_kind_screenshot", "/v1/artifacts?kind=screenshot&jarvis_session_id=current",
      lambda b: b["artifacts"] and all(i["kind"] == "screenshot" for i in b["artifacts"]))
    q("by_context_b", f"/v1/artifacts?context_id={ctx_b}",
      lambda b: b["artifacts"] and all(i["context_id"] == ctx_b for i in b["artifacts"]))
    q("by_context_active", "/v1/artifacts?context_id=active&kind=audio_recording",
      lambda b: any(i["artifact_id"] == audio_art for i in b["artifacts"]))
    q("by_session", f"/v1/artifacts?jarvis_session_id={s0['jsess']}&limit=50",
      lambda b: len({i["context_id"] for i in b["artifacts"]}) >= 2)
    since = urllib.request.quote(started)
    q("by_time_since_audio_start", f"/v1/artifacts?since={since}&kind=transcript_segment&limit=50",
      lambda b: b["artifacts"] and all(i["created_at"] >= started for i in b["artifacts"]))
    rel = q("provenance_of_audio", f"/v1/artifacts/{audio_art}/relations?direction=dependents",
            lambda b: any(r["relation"] == "transcribed_from" for r in b.get("dependents", [])))
    out[-1]["relations"] = sorted({r["relation"] for r in (rel or {}).get("dependents", [])}) if isinstance(rel, dict) \
        else None
    seg = q("transcript_from_ms", f"/v1/captures/{audio_id}/transcript?from_ms=9000&max_chars=600",
            lambda b: b["segments"] and b["segments"][0]["end_ms"] >= 9000 and b["addressed"] is False)
    if isinstance(seg, dict) and seg.get("segments"):
        out[-1]["first_segment"] = {k: seg["segments"][0][k] for k in ("seq", "start_ms", "end_ms")}
    q("activity_tail", "/v1/activity?limit=200",
      lambda b: {"capture.started", "capture.stopped", "context.activated"} <= {e["kind"] for e in b["events"]})
    return out


# brain turns ---------------------------------------------------------------


def _turn(d: Driver, conversation: str, text: str, label: str, *, parity: bool = False) -> dict:
    say(f"  -- brain turn {label}")
    done_before = len(d.trace("core.brain.latency.work_completed")) + len(d.trace("core.brain.turn_failed"))
    events_before = len(d.trace("agent.event"))
    status, _ = d.core("POST", f"/v1/conversations/{conversation}/brain-turns",
                       {"content": text, "correlation_id": f"e2e-{label}-{int(time.time())}",
                        "addressing": "addressed"}, timeout=30)
    truth_during: list[dict] = []
    deadline = time.time() + 300
    while time.time() < deadline:
        done = len(d.trace("core.brain.latency.work_completed")) + len(d.trace("core.brain.turn_failed"))
        if done > done_before:
            break
        if parity:
            truth_during.append({"at": time.time(), "status": _status_digest(d.status())})
        time.sleep(2)
    time.sleep(3)
    session_id = (d.current().get("binding") or {}).get("agent_session_id")
    # The enrichment worker's restricted calls share the trace: keep the Brain's own session only.
    events = [row for row in d.trace("agent.event")[events_before:]
              if (row.get("data") or {}).get("session_id") in (session_id, None)]
    tools, results, final, cost = [], [], None, None
    for row in events:
        ev = row.get("data") or {}
        kind = ev.get("type")
        if kind == "assistant":
            for block in (ev.get("message") or {}).get("content") or []:
                if block.get("type") == "tool_use":
                    tools.append({"name": block.get("name"), "input": block.get("input")})
        elif kind == "user":
            for block in (ev.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    content = block.get("content")
                    if isinstance(content, list):
                        content = " ".join(x.get("text", "") for x in content if isinstance(x, dict))
                    results.append(str(content)[:1500])
        elif kind == "result" and final is None:
            final, cost = ev.get("result"), ev.get("total_cost_usd")
    brief = _brief_of(session_id, text)
    return {"label": label, "text": text, "submit": status, "tools": tools, "tool_results": results,
            "final": final, "cost_usd_cumulative_cli": cost, "agent_session_id": session_id, "brief": brief,
            "truth_during": truth_during[-3:], "truth_after": _status_digest(d.status())}


def _status_digest(status: dict) -> dict:
    return {"open": sorted((c["channel"], c["state"], c["capture_id"]) for c in status.get("captures", [])),
            "stuck": [s.get("capture_id") for s in status.get("stuck", [])],
            "enrichment": (status.get("enrichment") or {}).get("state")}


def _brief_of(agent_session_id: str | None, request: str) -> dict | None:
    """Size of the per-turn block the CLI really received (Claude's own session log)."""

    if not agent_session_id:
        return None
    for path in (Path.home() / ".claude" / "projects").glob(f"*/{agent_session_id}.jsonl"):
        last = None
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            msg = row.get("message") or {}
            if row.get("type") != "user" or msg.get("role") != "user":
                continue
            content = msg.get("content")
            text = content if isinstance(content, str) else " ".join(
                b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")
            if request[:40] in text:
                last = text
        if last is not None:
            def size(start: str, end: str) -> int:
                return len(_section(last, start, end).encode("utf-8"))

            transcript = _section(last, "Transcription ambiante récente", "Artifacts récents")
            quote = transcript[transcript.find("«"):] if "«" in transcript else ""
            return {"bytes": len(last.encode("utf-8")),
                    "context_block_bytes": size("[Contexte actif]", "Intention courante"),
                    "summary_bytes": size("<<< summary.md", ">>> fin de summary.md"),
                    "activity_bytes": size("Activité récente", "Intention courante"),
                    "transcript_bytes": len(transcript.encode("utf-8")), "transcript_chars": len(quote),
                    "first_point": _first_point(quote), "sections": [ln for ln in last.splitlines()
                                                                     if ln.startswith("[")]}
    return None


def _first_point(quote: str) -> str | None:
    i = quote.find("Point ")
    return quote[i:i + 9] if i >= 0 else None


def _section(text: str, start: str, end: str) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i + len(start))
    return text[i:j if j > 0 else len(text)]


# rail parity (headless Chrome over CDP) ------------------------------------


def _rail_parity(d: Driver, scratch: Path) -> dict:
    if not Path(CHROME).exists():
        return {"skipped": "chrome not found"}
    return asyncio.run(_rail_parity_async(d, scratch))


async def _rail_parity_async(d: Driver, scratch: Path) -> dict:
    import aiohttp

    profile = scratch / "chrome-profile"
    shutil.rmtree(profile, ignore_errors=True)
    port = 9400 + os.getpid() % 300
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={port}",
                               f"--user-data-dir={profile}", "--no-first-run", "--disable-gpu",
                               "--disable-extensions", "about:blank"], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
    d.pids.append({"role": "chrome", "pid": chrome.pid, "at": time.time()})
    try:
        async with aiohttp.ClientSession() as http:
            target = None
            for _ in range(100):
                try:
                    async with http.get(f"http://127.0.0.1:{port}/json/list") as resp:
                        target = next((t for t in await resp.json() if t["type"] == "page"), None)
                    if target:
                        break
                except aiohttp.ClientError:
                    pass
                await asyncio.sleep(0.15)
            async with http.ws_connect(target["webSocketDebuggerUrl"], max_msg_size=0) as ws:
                ids = iter(range(1, 10_000))

                async def send(method: str, params: dict | None = None) -> dict:
                    mid = next(ids)
                    await ws.send_json({"id": mid, "method": method, "params": params or {}})
                    while True:
                        msg = await ws.receive_json()
                        if msg.get("id") == mid:
                            return msg.get("result", {})

                async def ev(expr: str):  # noqa: ANN202
                    res = await send("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                                          "awaitPromise": True})
                    return (res.get("result") or {}).get("value")

                await send("Page.enable")
                await send("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 900,
                                                                  "deviceScaleFactor": 1, "mobile": False})
                await send("Page.navigate", {"url": UI + "/"})
                await asyncio.sleep(4)
                rail = await ev("""(()=>{const o={};for(const el of document.querySelectorAll(
                    '#captureRail [data-capture-control]'))o[el.dataset.captureControl]={state:el.getAttribute(
                    'data-capture-state'),pressed:el.getAttribute('aria-pressed'),label:el.getAttribute('aria-label')};
                    const c=document.getElementById('captureRailCaption');o.caption=c&&c.textContent;
                    const r=document.getElementById('captureRail');o.slot=r&&r.dataset.captureSlot;return o})()""")
                shot = await send("Page.captureScreenshot", {"format": "png", "clip": {
                    "x": 0, "y": 0, "width": 460, "height": 640, "scale": 1}})
                if shot.get("data"):
                    import base64

                    (d.out / "matrix-rail.png").write_bytes(base64.b64decode(shot["data"]))
        truth = _status_digest(d.status())
        open_channels = {c[0] for c in truth["open"] if c[1] == "active"}
        ok = bool(rail) and all((rail.get(ch, {}).get("pressed") == "true") == (ch in open_channels)
                                for ch in ("audio", "screen"))
        d.step("M5_rail_parity", ok, rail=rail, core=truth)
        return {"rail": rail, "core": truth, "ok": ok}
    finally:
        chrome.kill()
        try:
            chrome.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        subprocess.run(["taskkill", "/PID", str(chrome.pid), "/T", "/F"], capture_output=True, check=False)
        shutil.rmtree(profile, ignore_errors=True)


# --------------------------------------------------------------------------
# phase: mic (real microphone 3 s + real desktop screenshot)
# --------------------------------------------------------------------------


def phase_mic(scratch: Path) -> int:
    d = Driver(scratch, "mic")
    shutil.rmtree(d.data, ignore_errors=True)
    d.env.update({"JARVIS_E2E_AUDIO": "real", "JARVIS_E2E_SCREEN": "real", "JARVIS_E2E_SCREENSHOT": "real",
                  "JARVIS_E2E_STT": "real", "JARVIS_CONTEXT_ENRICHMENT": "0"})
    try:
        d.start("core")
        d.wait_core()
        st, started = d.core("POST", "/v1/captures/start", {"channel": "audio"})
        cap_id = started.get("capture", {}).get("capture_id") if isinstance(started, dict) else None
        time.sleep(3)
        st_stop, stopped = d.core("POST", f"/v1/captures/{cap_id}/stop", {}) if cap_id else (None, {})
        final = stopped.get("capture", {}) if isinstance(stopped, dict) else {}
        art_id = final.get("artifact_id")
        _, art = d.core("GET", f"/v1/artifacts/{art_id}") if art_id else (None, {})
        meta = (art or {}).get("artifact", art or {}).get("metadata", {}) if isinstance(art, dict) else {}
        d.step("mic_real_3s", st == 201 and final.get("state") == "complete" and final.get("gaps") == 0,
               start_status=st, final=_slim(final), sample_rate=meta.get("sample_rate"),
               size=(art or {}).get("artifact", art or {}).get("size_bytes") if isinstance(art, dict) else None)
        trans = d.wait_for(lambda: _capture_of(d.core("GET", f"/v1/captures/{cap_id}")[1]).get("transcription"), 10)
        st_ab, abandoned = d.core("POST", f"/v1/captures/{cap_id}/transcription/abandon",
                                  {"reason": "E2E : pas de fournisseur"})
        d.step("transcription_unavailable_then_abandon", (trans or {}).get("state") == "unavailable"
               and st_ab == 200, transcription=trans, abandon_status=st_ab,
               abandon={k: (abandoned or {}).get(k) for k in ("state", "error_code")} if isinstance(abandoned, dict)
               else abandoned)
        st_shot, shot = d.core("POST", "/v1/captures/screenshot", {})
        sa = shot.get("artifact", {}) if isinstance(shot, dict) else {}
        d.step("screenshot_real", st_shot == 201 and sa.get("state") == "complete",
               size=sa.get("size_bytes"), width=sa.get("width"), height=sa.get("height"))
        deleted = [d.core("DELETE", f"/v1/artifacts/{a}?cascade=true")[0] for a in (art_id, sa.get("artifact_id")) if a]
        left = [p.name for p in (d.data / "artifacts").glob("*/*")] if (d.data / "artifacts").exists() else []
        d.step("real_media_deleted", deleted == [200, 200] and not any(p.endswith((".wav", ".png")) for p in left),
               deleted=deleted, files_left=left)
    finally:
        d.stop_all()
        shutil.rmtree(d.data / "artifacts", ignore_errors=True)
        path = d.save()
        say("report", path)
    return 0 if all(s["ok"] for s in d.report["steps"]) else 1


# --------------------------------------------------------------------------
# phase: soak (loop stalls under capture load)
# --------------------------------------------------------------------------


def phase_soak(scratch: Path, seconds: int, *, with_ui: bool, cc_every: int = 0) -> int:
    d = Driver(scratch, "soak")
    shutil.rmtree(d.data, ignore_errors=True)
    shutil.rmtree(d.runtime, ignore_errors=True)
    d.runtime.mkdir(parents=True)
    (d.runtime / "control-center-settings.json").write_text(json.dumps({
        "agent_cli_settings": {"claude": {"model": "sonnet"}}, "scene": {"enabled": False}}), encoding="utf-8")
    d.env.update({"JARVIS_E2E_AUDIO": "paced", "JARVIS_E2E_SCREEN": "fake", "JARVIS_E2E_SCREENSHOT": "fake",
                  "JARVIS_E2E_STT": "scripted", "JARVIS_E2E_STT_DELAY_S": "1.5"})
    lat_core: list[float] = []
    lat_ui: list[float] = []
    slow: list[dict] = []
    try:
        d.start("core")
        d.wait_core()
        if with_ui:
            d.start("control-center")
            d.wait_ui_adopted(0)
        d.core("POST", "/v1/captures/start", {"channel": "audio"})
        d.core("POST", "/v1/captures/start", {"channel": "screen"})
        end = time.time() + seconds
        tick = 0
        next_cc = time.time() + cc_every if (with_ui and cc_every) else None
        while time.time() < end:
            t0 = time.perf_counter()
            try:
                d.core("GET", "/v1/captures/status?recent=3", timeout=20)
            except OSError as exc:
                slow.append({"at": time.time(), "via": "core", "error": repr(exc)})
            dt = time.perf_counter() - t0
            lat_core.append(dt)
            if dt > 1.0:
                slow.append({"at": time.time(), "via": "core", "s": round(dt, 3)})
            if with_ui:
                t0 = time.perf_counter()
                try:
                    d.ui("GET", "/api/captures/status?recent=3", timeout=20)
                except OSError as exc:
                    slow.append({"at": time.time(), "via": "ui", "error": repr(exc)})
                dt = time.perf_counter() - t0
                lat_ui.append(dt)
                if dt > 1.0:
                    slow.append({"at": time.time(), "via": "ui", "s": round(dt, 3)})
            tick += 1
            if next_cc is not None and time.time() >= next_cc:
                d.kill("control-center")
                d.start("control-center")
                next_cc = time.time() + cc_every
            if tick % 20 == 0:
                d.core("POST", "/v1/captures/screenshot", {})
            time.sleep(max(0.0, 1.0 - (time.perf_counter() - t0)))
        for cap in d.status().get("captures", []):
            d.core("POST", f"/v1/captures/{cap['capture_id']}/stop", {})
    finally:
        d.stop_all()

        def pct(values: list[float], p: float) -> float | None:
            return round(sorted(values)[min(len(values) - 1, int(p * len(values)))], 4) if values else None

        d.report.update({
            "seconds": seconds, "polls": len(lat_core),
            "core_latency": {"p50": pct(lat_core, 0.5), "p95": pct(lat_core, 0.95), "p99": pct(lat_core, 0.99),
                             "max": round(max(lat_core), 4) if lat_core else None},
            "ui_latency": {"p50": pct(lat_ui, 0.5), "p95": pct(lat_ui, 0.95), "p99": pct(lat_ui, 0.99),
                           "max": round(max(lat_ui), 4) if lat_ui else None},
            "slow": slow, "stalls": d.stalls(),
            "core_timeouts_in_trace": len([r for r in d.trace("capture.request") if "core_timeout" in json.dumps(r)]),
        })
        path = d.save()
        say(json.dumps({k: d.report[k] for k in ("polls", "core_latency", "ui_latency")}, ensure_ascii=False))
        say(f"slow={len(slow)} stalls={len(d.report['stalls'])} report {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("child")
    c.add_argument("role", choices=("core", "control-center"))
    for name in ("migrate", "matrix", "mic", "soak"):
        p = sub.add_parser(name)
        p.add_argument("--scratch", type=Path, required=True)
        if name == "migrate":
            p.add_argument("--main-tree", type=Path, required=True)
        if name == "matrix":
            p.add_argument("--brain", action="store_true")
        if name == "soak":
            p.add_argument("--seconds", type=int, default=300)
            p.add_argument("--with-ui", action="store_true")
            p.add_argument("--cc-restart-every", type=int, default=0)
    args = parser.parse_args(argv)
    if args.cmd == "child":
        child(args.role)
        return 0
    args.scratch.mkdir(parents=True, exist_ok=True)
    if args.cmd == "migrate":
        return phase_migrate(args.scratch, args.main_tree)
    if args.cmd == "matrix":
        return phase_matrix(args.scratch, brain=args.brain)
    if args.cmd == "mic":
        return phase_mic(args.scratch)
    return phase_soak(args.scratch, args.seconds, with_ui=args.with_ui, cc_every=args.cc_restart_every)


if __name__ == "__main__":
    sys.exit(main())

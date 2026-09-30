"""Boards et Sessions de bout en bout : la matrice de la Slice 08 (handoff board-session).

Core **réel** (`JarvisCoreApplication` + `LocalProtocolServer`, base SQLite
temporaire) et Control Center **réel** (`ControlCenter.start`, HTTP, pool des
cerveaux de Board), chacun pointé sur l'autre comme dans `jarvis/app.py`. Seul
l'exécutable `claude` est remplacé par un **vrai processus** Python qui parle
stream-json (`STUB` ci-dessous) : lancements, `--resume`, sous-agents d'arrière-
plan et leur relais spontané, échecs injectés (`fail-start`, `fail-resume`,
`fail-<tâche>`) par fichiers drapeaux.

Chaque scénario rejoue à la fin la frise de l'autorité de parole
(`board_session_timeline.check_single_authority`) sur le bus de Core **et** sur
la trace : une seule conversation parle à la fois, sur toute la durée.

Contrat : `docs/boards.md`. Architecture : `tasks/jarvis-board-session-context-
runtime/docs/06-resolved-architecture.md`. Durée : ~1 min pour tout le module
(chaque scénario démarre ses processus) ; aucun réseau hors loopback, aucun
modèle.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import textwrap
from pathlib import Path

import aiohttp
import pytest

from jarvis.adapters import sqlite_state
from jarvis.adapters.control_center_brain import ControlCenterBrainBackend
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.interaction_mode import InteractionMode
from jarvis.domain.v2 import BrainTurnInput, Conversation
from jarvis.domain.workspace_board import DEFAULT_BOARD_ID, BrainLifecycle
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime import claude_local
from jarvis.runtime import interaction_mode_settings as mode_settings
from jarvis.runtime.claude_local import ClaudeLocalAgent
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.core_sessions import CoreSessionTransport
from jarvis.runtime.interaction_mode_view import CoreInteractionModeTransport, CoreInteractionModeView
from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail
from jarvis.runtime.settings_mcp import ConsoleMcpTarget, ConsoleSettingsTools, ConsoleToolError
from tests.integration.board_session_timeline import (
    authority, check_single_authority, marks_from_bus, marks_from_trace, Mark, SPEECH, WITHHELD,
)
from tests.unit.test_board_brains_control_center import free_port

TOKEN = "e" * 48

STUB = textwrap.dedent('''
    """Doublure du CLI Claude (stream-json). Drapeaux lus dans le dossier du script."""
    import json, os, re, sys, threading, time, uuid
    here = os.path.dirname(os.path.abspath(__file__))
    flag = lambda name: os.path.exists(os.path.join(here, name))
    def log(name, row):
        with open(os.path.join(here, name), "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\\n")
    argv = sys.argv[1:]
    resumed = argv[argv.index("--resume") + 1] if "--resume" in argv else None
    sid = resumed or str(uuid.uuid4())
    log("spawns.log", {"pid": os.getpid(), "resume": resumed, "session": sid})
    if flag("fail-start"):
        sys.stderr.write("stub: injected start failure\\n"); sys.stderr.flush(); sys.exit(3)
    if resumed and flag("fail-resume"):
        sys.stderr.write("No conversation found with session ID: %s\\n" % resumed); sys.stderr.flush(); sys.exit(1)
    lock = threading.Lock()
    def out(event):
        event.setdefault("session_id", sid)
        with lock:
            sys.stdout.write(json.dumps(event) + "\\n"); sys.stdout.flush()
    out({"type": "system", "subtype": "init", "model": "stub"})
    def watch(task_id):
        while not (flag("end-" + task_id) or flag("fail-" + task_id)):
            time.sleep(0.1)
        status = "failed" if flag("fail-" + task_id) else "completed"
        out({"type": "system", "subtype": "task_notification", "task_id": task_id, "status": status,
             "summary": "fini" if status == "completed" else "build rouge"})
        time.sleep(0.2)
        out({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "relais"}]}})
        out({"type": "result", "subtype": "success", "is_error": False, "duration_ms": 5,
             "result": "RELAIS " + task_id + " " + status, "origin": {"kind": "task-notification"}})
    n = 0
    for line in sys.stdin:
        n += 1
        log("inputs.log", {"session": sid, "line": line})
        for name in re.findall(r"SUBAGENT:(\\w+)", line):
            out({"type": "system", "subtype": "task_started", "task_id": "task-" + name, "description": "Long " + name,
                 "is_backgrounded": True, "task_type": "local_agent", "subagent_type": "general-purpose"})
            threading.Thread(target=watch, args=("task-" + name,), daemon=True).start()
        out({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}})
        out({"type": "result", "subtype": "success", "is_error": False, "duration_ms": 5,
             "result": "reponse %d de %s" % (n, sid[:8])})
''')


# ------------------------------------------------------------------ banc d'essai


class Stub:
    """Le vrai processus qui remplace `claude`, et ses fichiers drapeaux."""

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.script = root / "stub_claude.py"
        self.script.write_text(STUB, encoding="utf-8")

    def flag(self, name: str, on: bool = True) -> None:
        path = self.root / name
        if on:
            path.write_text("1", encoding="utf-8")
        elif path.exists():
            path.unlink()

    def _rows(self, name: str) -> list[dict]:
        path = self.root / name
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def spawns(self) -> list[dict]:
        return self._rows("spawns.log")

    def inputs(self, session: str) -> list[str]:
        return [row["line"] for row in self._rows("inputs.log") if row["session"] == session]

    def spawner(self):  # noqa: ANN201
        real = asyncio.create_subprocess_exec
        script = str(self.script)

        async def spawn(executable, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            del executable
            kept = {k: v for k, v in kwargs.items() if k in {"stdin", "stdout", "stderr", "cwd", "env"}}
            return await real(sys.executable, script, *args, **kept)

        return spawn


class Bench:
    """Core + Control Center réels sur des dossiers temporaires, ports fixes pour les redémarrages."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.runtime = tmp_path / "runtime"
        self.project = tmp_path / "project"
        self.data = tmp_path / "core"
        for path in (self.runtime, self.project, self.data / "state"):
            path.mkdir(parents=True, exist_ok=True)
        self.token_file = tmp_path / "core.token"
        self.token_file.write_text(TOKEN, encoding="utf-8")
        self.stub = Stub(tmp_path / "stub")
        self.core_port, self.cc_port = free_port(), free_port()
        self.base = f"http://127.0.0.1:{self.cc_port}"
        self.core: JarvisCoreApplication | None = None
        self.server: LocalProtocolServer | None = None
        self.backend: ControlCenterBrainBackend | None = None
        self.control: ControlCenter | None = None
        self.marks: list[Mark] = []          # frise du bus, toutes vies de Core confondues
        self._bus_task: asyncio.Task | None = None
        self._bus_queue = None

    # -- Core

    async def start_core(self) -> JarvisCoreApplication:
        self.backend = ControlCenterBrainBackend(base_url=self.base)
        self.core = JarvisCoreApplication(data_root=self.data, brain_backend=self.backend,
                                          diagnostics=RuntimeJournal(self.runtime),
                                          work_attention_wake_interval_s=0.05)
        await self.core.start()
        current = await self.core.sessions.current()
        self.marks.append(authority(current.binding.conversation_id, source="core_start",
                                    board_id=current.binding.board_id))
        self._bus_queue = self.core.events.subscribe()
        self._bus_task = asyncio.create_task(self._collect(self._bus_queue))
        if self.core._host_align_task is not None:
            await asyncio.wait_for(self.core._host_align_task, timeout=20)
        self.server = LocalProtocolServer(self.core, host="127.0.0.1", port=self.core_port, token=TOKEN)
        await self.server.start()
        return self.core

    async def _collect(self, queue) -> None:  # noqa: ANN001
        while True:
            self.marks.extend(marks_from_bus([await queue.get()]))

    async def stop_core(self) -> None:
        if self.server is not None:
            await self.server.stop()
        if self._bus_task is not None:
            await asyncio.sleep(0.05)
            self._bus_task.cancel()
            await asyncio.gather(self._bus_task, return_exceptions=True)
            self.core.events.unsubscribe(self._bus_queue)
        if self.core is not None:
            await self.core.stop()
        if self.backend is not None:
            await self.backend.close()
        self.core = self.server = self.backend = self._bus_task = None

    # -- Control Center

    def build_control(self) -> ControlCenter:
        def transport(cls):  # noqa: ANN001, ANN202
            return cls(host="127.0.0.1", port=self.core_port, token_file=self.token_file)

        journal = RuntimeJournal(self.runtime)
        return ControlCenter(
            runtime_root=self.runtime, project_root=self.project,
            sessions=transport(CoreSessionTransport),
            interaction_mode_view=CoreInteractionModeView(transport(CoreInteractionModeTransport), journal=journal),
            console_mcp=ConsoleMcpTarget("127.0.0.1", self.cc_port, self.runtime),
            agent_factory=lambda cli: ClaudeLocalAgent(runtime_root=self.runtime, cwd=self.project),
        )

    async def start_control(self, control: ControlCenter | None = None) -> ControlCenter:
        self.control = control or self.build_control()
        await self.control.start(port=self.cc_port)
        return self.control

    async def stop_control(self) -> None:
        if self.control is not None:
            await self.control.stop()
        self.control = None

    async def close(self) -> None:
        await self.stop_core()
        await self.stop_control()

    # -- actions

    async def call(self, method: str, path: str, **kwargs):  # noqa: ANN201
        async with aiohttp.ClientSession() as http:
            async with http.request(method, self.base + path, timeout=aiohttp.ClientTimeout(total=60),
                                    **kwargs) as response:
                return response.status, await response.json(content_type=None)

    async def ok(self, method: str, path: str, **kwargs) -> dict:
        status, body = await self.call(method, path, **kwargs)
        assert status in (200, 201), (method, path, status, body)
        return body

    async def turn(self, text: str) -> str:
        """Un tour utilisateur par Core (comme Voice) sur la liaison courante ; rend sa conversation."""

        conversation_id = (await self.core.sessions.current()).binding.conversation_id
        await self.core.brain.submit(BrainTurnInput(conversation_id=conversation_id, text=text))
        await self.settle()
        return conversation_id

    async def settle(self, timeout_s: float = 30.0) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while self.core.brain.active_turn_count:
            assert loop.time() < deadline, "brain turns did not settle"
            await asyncio.sleep(0.05)

    async def until(self, predicate, timeout_s: float = 20.0, what: str = "condition") -> None:  # noqa: ANN001
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while True:
            value = predicate()
            if asyncio.iscoroutine(value):
                value = await value
            if value:
                return
            assert loop.time() < deadline, f"timed out waiting for {what}"
            await asyncio.sleep(0.1)

    def trace(self, kind: str | None = None) -> list[dict]:
        rows = read_jsonl_tail(self.runtime / "trace.jsonl", limit=20000)
        return [row for row in rows if kind is None or row["kind"] == kind]

    def spoken(self) -> list[str]:
        return [m.conversation_id for m in self.marks if m.kind == SPEECH]

    def assert_one_speech_authority(self) -> tuple:
        """La frise du bus et celle de la trace : aucune parole hors de l'autorité, jamais."""

        bus = check_single_authority(self.marks)
        trace = check_single_authority(marks_from_trace(self.trace()))
        assert bus.violations == [], bus.violations
        assert trace.violations == [], trace.violations
        return bus, trace


@pytest.fixture
async def bench(tmp_path, monkeypatch):
    bench = Bench(tmp_path)
    monkeypatch.setattr(claude_local.asyncio, "create_subprocess_exec", bench.stub.spawner())
    try:
        yield bench
    finally:
        await bench.close()


async def up(bench: Bench) -> JarvisCoreApplication:
    """Ordre de production : Core puis Control Center, qui adopte la liaison foreground."""

    core = await bench.start_core()
    await bench.start_control()
    current = (await core.sessions.current()).binding.conversation_id
    await bench.until(lambda: bench.control.board_brains.foreground.key == current, what="CC adoption")
    return core


def bound(bench: Bench, conversation_id: str):  # noqa: ANN201
    return bench.control.board_brains.find(conversation_id)


def alerts(bench: Bench, body: dict, category: str | None = None) -> list[dict]:
    return [e for e in body["events"] if category is None or e["category"] == category]


# ------------------------------------------------------------------ la frise elle-même


def test_the_timeline_check_catches_a_second_speaker_and_a_gated_active_board():
    marks = [authority("A"), Mark(SPEECH, "A", "t"), Mark(WITHHELD, "B", "t"), authority("B"),
             Mark(SPEECH, "A", "t"), Mark(WITHHELD, "B", "t"), Mark(WITHHELD, None, "t")]
    report = check_single_authority(marks)
    assert [s["conversation_id"] for s in report.segments] == ["A", "B"]
    assert len(report.violations) == 2
    assert "A spoke while B" in report.violations[0] and "speaking conversation was withheld" in report.violations[1]
    assert check_single_authority([Mark(SPEECH, "A", "t")]).violations == ["#0 t: speech before any authority"]


# ------------------------------------------------------------------ 1. migration d'une base v2


async def _v2_database(db: Path, monkeypatch) -> str:
    """Une vraie base au schéma 2 (binaire d'avant les Boards) avec une conversation en cours."""

    with monkeypatch.context() as patch:
        patch.setattr(sqlite_state, "_SCHEMA_VERSION", 2)
        state = SQLiteStateRepository(db)
        await state.initialize()
        conversation = Conversation(originating_device_id="windows-desktop", current_device_id="windows-desktop")
        await state.save_conversation(conversation)
        await state.close()
    return conversation.id


def _sql(db: Path, query: str) -> list[tuple]:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(query).fetchall()
    finally:
        conn.close()


async def test_a_v2_store_migrates_to_one_default_board_that_adopts_the_voice_conversation_and_the_legacy_mode(
        bench, monkeypatch):
    db = bench.data / "state" / "jarvis.sqlite3"
    legacy_conversation = await _v2_database(db, monkeypatch)
    assert _sql(db, "SELECT version FROM schema_version") == [(2,)]
    # Préférence globale d'avant les Boards : réglage du Control Center.
    control = bench.build_control()
    settings = control._settings()
    mode_settings.apply(settings, {"mode": "presentation"})
    control._write_settings(settings)

    core = await bench.start_core()
    await bench.start_control(control)

    assert _sql(db, "SELECT version FROM schema_version") == [(3,)]
    assert (db.parent / "jarvis.sqlite3.v2.bak").is_file(), "one-time backup before migrating"
    boards = await bench.ok("GET", "/api/boards")
    assert [b["board_id"] for b in boards["boards"]] == [DEFAULT_BOARD_ID]
    current = await bench.ok("GET", "/api/sessions/current")
    assert current["binding"]["conversation_id"] == legacy_conversation, "the voice conversation survives"
    await bench.until(lambda: bench.control.board_brains.foreground.key == legacy_conversation, what="adoption")

    async def migrated() -> bool:
        board = (await bench.ok("GET", "/api/boards/active"))["board"]
        return board["interaction_mode_origin"] == "migrated"

    await bench.until(migrated, what="legacy mode adopted once")
    assert (await bench.ok("GET", "/api/boards/active"))["board"]["interaction_mode"] == "presentation"
    assert core.interaction_mode.mode is InteractionMode.PRESENTATION

    # Deuxième démarrage : rien n'est adopté ni recréé, la Session est neuve.
    await bench.stop_core()
    core = await bench.start_core()
    again = await bench.ok("GET", "/api/sessions/current")
    assert again["binding"]["conversation_id"] != legacy_conversation
    assert [b["board_id"] for b in (await bench.ok("GET", "/api/boards"))["boards"]] == [DEFAULT_BOARD_ID]
    assert len((await bench.ok("GET", "/api/sessions", params={"limit": "10"}))["sessions"]) == 2
    assert core.interaction_mode.mode is InteractionMode.PRESENTATION, "restored from the Board"
    assert sorted(p.name for p in db.parent.glob("*.bak")) == ["jarvis.sqlite3.v2.bak"]
    assert len(bench.trace("core.board.default_created")) == 1
    bench.assert_one_speech_authority()


# ------------------------------------------------------------------ 2. A -> B -> A, puis nouvelle Session


async def test_a_b_a_reuses_each_binding_then_a_new_session_is_clean_and_keeps_board_and_tasks(bench):
    core = await up(bench)
    a_board = DEFAULT_BOARD_ID
    await bench.ok("PATCH", f"/api/boards/{a_board}", json={"context_summary": "Lot A", "task_refs": ["task-a1"]})
    a_conv = await bench.turn("premier tour sur A SUBAGENT:alpha")
    a_agent = bound(bench, a_conv).agent
    a_cli_session = a_agent.session_id
    b_board = (await bench.ok("POST", "/api/boards", json={"title": "Projet B"}))["board"]["board_id"]

    to_b = await bench.ok("POST", "/api/boards/switch", json={"board_id": b_board})
    assert to_b["changed"] and to_b["previous_board_id"] == a_board
    b_conv = await bench.turn("tour sur B")
    assert b_conv == to_b["binding"]["conversation_id"] != a_conv
    assert bound(bench, a_conv).lifecycle is BrainLifecycle.BACKGROUND_RUNNING, "A works, it is kept alive"

    back = await bench.ok("POST", "/api/boards/switch", json={"board_id": a_board})
    assert back["binding"]["conversation_id"] == a_conv, "A/B/A: the same binding"
    assert bench.control.agent is a_agent and a_agent.session_id == a_cli_session, "the same live CLI"
    assert await bench.turn("retour sur A") == a_conv
    b_entry = bound(bench, b_conv)
    assert b_entry.lifecycle is BrainLifecycle.SUSPENDED, "idle B suspended at once"

    again = await bench.ok("POST", "/api/boards/switch", json={"board_id": b_board})
    assert again["binding"]["conversation_id"] == b_conv
    resumed = [s for s in bench.stub.spawns() if s["resume"]]
    assert resumed and resumed[-1]["resume"] == again["binding"]["agent_session_id"], "B resumed with --resume"
    await bench.ok("POST", "/api/boards/switch", json={"board_id": a_board})
    session = (await bench.ok("GET", "/api/sessions/current"))["session"]
    assert session["visited_board_ids"] == [a_board, b_board]

    # Nouvelle Session sur A : conversation propre, Board et tâches intacts.
    first = session["jarvis_session_id"]
    fresh = await bench.ok("POST", "/api/sessions/new", json={"expected_session_id": first})
    assert fresh["closed_session"]["jarvis_session_id"] == first
    assert fresh["session"]["active_board_id"] == a_board
    new_conv = fresh["binding"]["conversation_id"]
    assert new_conv not in (a_conv, b_conv)
    new_agent = bench.control.agent
    assert new_agent is not a_agent and a_agent.state == "running", "old A CLI keeps its sub-agent"
    assert bound(bench, a_conv).closed and bound(bench, a_conv).lifecycle is BrainLifecycle.BACKGROUND_RUNNING
    assert await bench.turn("bonjour nouvelle session") == new_conv
    fresh_inputs = bench.stub.inputs(new_agent.session_id)
    assert fresh_inputs and not any("premier tour sur A" in x or "retour sur A" in x for x in fresh_inputs), \
        "clean conversation: nothing of the previous Session reaches the fresh CLI"
    assert "Lot A" in fresh_inputs[-1] and "task-a1" in fresh_inputs[-1], "hydrated from the Board block"
    board_a = (await bench.ok("GET", f"/api/boards/{a_board}"))["board"]
    assert board_a["context_summary"] == "Lot A" and board_a["task_refs"] == ["task-a1"]
    assert (await bench.ok("GET", f"/api/boards/{b_board}"))["board"]["status"] == "active"
    status, refused = await bench.call("POST", "/api/sessions/new", json={"expected_session_id": first})
    assert status == 409 and refused["error"]["code"] == "session_closed", "second click opens nothing"

    # Le sous-agent de l'ancienne liaison finit : alerte, jamais de parole.
    spoken_before = len(bench.spoken())
    bench.stub.flag("end-task-alpha")
    await bench.until(lambda: bench.trace("agent.unsolicited_result"), what="relay journaled")
    await asyncio.sleep(0.5)
    assert bench.spoken()[spoken_before:] == [], "a closed binding never speaks"
    relay = bench.trace("agent.unsolicited_result")[-1]["data"]
    assert relay["spoken"] is False and relay["board_id"] == a_board
    bus, trace = bench.assert_one_speech_authority()
    assert bus.speeches >= 4, bus.segments
    assert [s["conversation_id"] for s in bus.segments][-1] == new_conv


# ------------------------------------------------------------------ 3-4. travail de fond, alertes, absences


async def test_inactive_board_completion_and_failure_are_attributed_alerts_that_survive_both_restarts(bench):
    core = await up(bench)
    a_conv = await bench.turn("lance SUBAGENT:ok1 et SUBAGENT:ko1")
    b_board = (await bench.ok("POST", "/api/boards", json={"title": "Recherche"}))["board"]["board_id"]
    await bench.ok("GET", "/api/status")                         # le suiveur se place en fin de trace
    await bench.ok("POST", "/api/boards/switch", json={"board_id": b_board})
    b_conv = await bench.turn("sur Recherche")
    spoken_before = len(bench.spoken())

    bench.stub.flag("end-task-ok1")
    bench.stub.flag("fail-task-ko1")

    async def two_alerts() -> bool:
        body = await bench.ok("GET", "/api/background", params={"limit": "50"})
        return {e["category"] for e in alerts(bench, body)} >= {"done", "failed", "said"}

    await bench.until(two_alerts, what="done + failed + said alerts of A")
    await asyncio.sleep(0.5)
    assert bench.spoken()[spoken_before:] == [], "the inactive Board never speaks"
    assert not [r for r in bench.trace("core.brain.notice_relayed") if r["data"]["conversation_id"] == a_conv]
    body = await bench.ok("GET", "/api/background", params={"limit": "50"})
    of_a = [e for e in alerts(bench, body) if e["category"] in ("done", "failed", "said")]
    assert of_a and all(e["board_id"] == DEFAULT_BOARD_ID for e in of_a), of_a
    beat = await bench.ok("GET", "/api/status")
    assert beat["boards"]["active"]["board_id"] == b_board
    assert any(s["board_id"] == DEFAULT_BOARD_ID for s in beat["background"]["sources"])
    unread = beat["background"]["counts"]

    # Absence 1 : le Control Center redémarre. Les alertes restent non lues ;
    # la liaison B (Core) redevient le foreground du nouveau pool.
    await bench.stop_control()
    await bench.start_control()
    await bench.until(lambda: bench.control.board_brains.foreground.key == b_conv, what="CC realigned on B")
    beat = await bench.ok("GET", "/api/status")
    assert all(beat["background"]["counts"].get(k, 0) >= v for k, v in unread.items()), (unread, beat["background"])
    interrupted = [e for e in alerts(bench, await bench.ok("GET", "/api/background", params={"limit": "50"}))
                   if e["board_id"] == b_board or e["board_id"] == DEFAULT_BOARD_ID]
    assert interrupted, "attributed alerts listed after the CC restart"

    # Absence 2 : Core redémarre (Session neuve sur le dernier Board actif).
    await bench.stop_core()
    core = await bench.start_core()
    current = await core.sessions.current()
    assert current.session.active_board_id == b_board and current.binding.conversation_id != b_conv
    await bench.until(lambda: bench.control.board_brains.foreground.key == current.binding.conversation_id,
                      what="CC realigned on the new Session")
    beat = await bench.ok("GET", "/api/status")
    assert all(beat["background"]["counts"].get(k, 0) >= v for k, v in unread.items())
    assert not [r for r in beat["boards"]["bindings"] if not r["closed"] and r["board_id"] != b_board]
    # « Aller au Board » = la bascule ordinaire, puis acquittement.
    await bench.ok("POST", "/api/boards/switch", json={"board_id": DEFAULT_BOARD_ID})
    acked = await bench.ok("POST", "/api/background/ack", json={})
    assert acked["persisted"] is True
    await bench.stop_control()
    await bench.start_control()
    assert not (await bench.ok("GET", "/api/status"))["background"].get("sources")
    bench.assert_one_speech_authority()


# ------------------------------------------------------------------ 5. mode par Board


async def test_each_board_restores_its_mode_and_an_unset_board_gets_the_default(bench):
    core = await up(bench)
    b_board = (await bench.ok("POST", "/api/boards", json={"title": "Démo"}))["board"]["board_id"]
    c_board = (await bench.ok("POST", "/api/boards", json={"title": "Vierge"}))["board"]["board_id"]
    await bench.ok("POST", "/api/boards/switch", json={"board_id": b_board})
    await bench.ok("POST", "/api/interaction-mode", json={"mode": "presentation"})  # route de l'écran

    async def stored(board_id: str, mode: str, origin: str) -> bool:
        board = (await bench.ok("GET", f"/api/boards/{board_id}"))["board"]
        return board["interaction_mode"] == mode and board["interaction_mode_origin"] == origin

    await bench.until(lambda: stored(b_board, "presentation", "user"), what="mode stored on B")
    assert core.interaction_mode.mode is InteractionMode.PRESENTATION

    await bench.ok("POST", "/api/boards/switch", json={"board_id": c_board})
    assert core.interaction_mode.mode is InteractionMode.ASSISTANT, "unset Board: default mode, not B's"
    assert (await bench.ok("GET", f"/api/boards/{c_board}"))["board"]["interaction_mode_origin"] == "unset"
    await bench.ok("POST", "/api/boards/switch", json={"board_id": b_board})
    assert core.interaction_mode.mode is InteractionMode.PRESENTATION, "B restores its own mode"
    await bench.ok("POST", "/api/boards/switch", json={"board_id": DEFAULT_BOARD_ID})
    assert core.interaction_mode.mode is InteractionMode.ASSISTANT
    await bench.ok("POST", "/api/boards/switch", json={"board_id": b_board})

    await bench.stop_core()                                      # Core redémarre sur B
    core = await bench.start_core()
    assert (await core.sessions.current()).session.active_board_id == b_board
    assert core.interaction_mode.mode is InteractionMode.PRESENTATION, "restored at Core start"
    applied = bench.trace("core.board.interaction_mode.applied")
    assert {r["data"].get("source") for r in applied} >= {"board_switch", "board_restore"}
    bench.assert_one_speech_authority()


# ------------------------------------------------------------------ 6-7. parité MCP / écran, gardes d'archivage


async def test_mcp_tools_and_screen_routes_see_and_refuse_the_same_things_including_archive_guards(bench):
    core = await up(bench)
    console = ConsoleSettingsTools(ConsoleMcpTarget("127.0.0.1", bench.cc_port))
    tools = console.boards
    try:
        made = await tools.create_board("Recherche")                         # MCP crée
        board_id = made["board_id"]
        screen = await bench.ok("GET", "/api/boards")                        # l'écran le voit
        assert board_id in {b["board_id"] for b in screen["boards"]}
        listed = await tools.list_boards()
        assert {b["board_id"] for b in listed["boards"]} == {b["board_id"] for b in screen["boards"]}
        await bench.ok("PATCH", f"/api/boards/{board_id}", json={"title": "Recherche IA"})  # l'écran renomme
        assert (await tools.get_board(board_id))["title"] == "Recherche IA"

        switched = await tools.switch_board(board_id)                         # hors tour : appliqué
        assert switched["status"] == "applied"
        assert (await bench.ok("GET", "/api/boards/active"))["board"]["board_id"] == board_id
        assert (await tools.get_active())["board_id"] == board_id
        before = await tools.current_session()
        assert before["jarvis_session_id"] == (await bench.ok("GET", "/api/sessions/current"))["session"][
            "jarvis_session_id"]
        renewed = await tools.new_session()
        assert renewed["status"] == "applied" and renewed["closed_session_id"] == before["jarvis_session_id"]
        assert (await bench.ok("GET", "/api/sessions/current"))["session"]["active_board_id"] == board_id

        # Gardes : les deux chemins refusent avec le même code.
        status, refused = await bench.call("POST", f"/api/boards/{board_id}/archive")
        assert status == 409 and refused["error"]["code"] == "board_is_active"
        with pytest.raises(ConsoleToolError) as mcp_refused:
            await tools.archive_board(board_id)
        assert "board_is_active" in str(mcp_refused.value)
        archived = await tools.archive_board(DEFAULT_BOARD_ID)
        assert archived["status"] == "archived"
        status, refused = await bench.call("POST", "/api/boards/switch", json={"board_id": DEFAULT_BOARD_ID})
        assert status == 409 and refused["error"]["code"] == "board_archived"
        with pytest.raises(ConsoleToolError) as gone:
            await tools.switch_board(DEFAULT_BOARD_ID)
        assert "board_archived" in str(gone.value)
        status, refused = await bench.call("PATCH", f"/api/boards/{DEFAULT_BOARD_ID}", json={"title": "x"})
        assert status == 409 and refused["error"]["code"] == "board_archived"
        assert DEFAULT_BOARD_ID not in {b["board_id"] for b in (await bench.ok("GET", "/api/boards"))["boards"]}
        every = await bench.ok("GET", "/api/boards", params={"include_archived": "true"})
        assert DEFAULT_BOARD_ID in {b["board_id"] for b in every["boards"]}
        status, _ = await bench.call("POST", f"/api/boards/{DEFAULT_BOARD_ID}/archive")
        assert status == 200, "archive is replayable"

        # Core redémarre : le dernier Board actif (non archivé) est repris.
        await bench.stop_core()
        core = await bench.start_core()
        assert (await core.sessions.current()).session.active_board_id == board_id
    finally:
        await console.close()
    bench.assert_one_speech_authority()


# ------------------------------------------------------------------ 8. échec de bascule, reprise impossible


async def test_a_failed_switch_rolls_back_everything_and_a_dead_resume_id_falls_back_to_a_fresh_cli(bench):
    core = await up(bench)
    a_conv = (await core.sessions.current()).binding.conversation_id
    await bench.turn("tour sur A")                               # le CLI de A connaît son id
    b_board = (await bench.ok("POST", "/api/boards", json={"title": "Projet B"}))["board"]["board_id"]
    await bench.ok("POST", "/api/boards/switch", json={"board_id": b_board})
    await bench.ok("POST", "/api/interaction-mode", json={"mode": "presentation"})
    await bench.until(lambda: core.interaction_mode.mode is InteractionMode.PRESENTATION, what="mode on B")
    await bench.ok("POST", "/api/boards/switch", json={"board_id": DEFAULT_BOARD_ID})
    c_board = (await bench.ok("POST", "/api/boards", json={"title": "Projet C"}))["board"]["board_id"]
    before = await bench.ok("GET", "/api/sessions/current")
    foreground = bench.control.board_brains.foreground
    mode_before = core.interaction_mode.mode

    bench.stub.flag("fail-start")
    status, refused = await bench.call("POST", "/api/boards/switch", json={"board_id": c_board})
    assert status == 502 and refused["error"]["code"] == "board_activation_failed"
    assert "injected start failure" in refused["error"]["message"]
    after = await bench.ok("GET", "/api/sessions/current")
    assert after["session"] == before["session"] and after["binding"]["conversation_id"] == a_conv
    assert core.speech_authority.conversation_id == a_conv
    assert bench.control.board_brains.foreground is foreground and core.interaction_mode.mode is mode_before
    assert not [e for e in bench.control.board_brains.entries() if e.board_id == c_board]
    beat = await bench.ok("GET", "/api/status")
    assert beat["boards"]["active"]["board_id"] == DEFAULT_BOARD_ID
    bench.stub.flag("fail-start", on=False)
    assert (await bench.ok("POST", "/api/boards/switch", json={"board_id": c_board}))["changed"]

    # B est suspendu avec son id Claude ; cet id ne reprend plus : CLI neuf, bascule réussie.
    b_saved = next(b for b in (await core.boards._repo.list_bindings(before["session"]["jarvis_session_id"]))
                   if b.board_id == b_board)
    assert b_saved.agent_session_id and b_saved.lifecycle is BrainLifecycle.SUSPENDED
    bench.stub.flag("fail-resume")
    switched = await bench.ok("POST", "/api/boards/switch", json={"board_id": b_board})
    assert switched["binding"]["agent_session_id"] != b_saved.agent_session_id
    fallback = bench.trace("board_brain.resume_failed_fresh_start")
    assert fallback and fallback[-1]["data"]["old_agent_session_id"] == b_saved.agent_session_id
    assert core.interaction_mode.mode is InteractionMode.PRESENTATION, "B's mode came back with it"
    assert await bench.turn("après la reprise") == switched["binding"]["conversation_id"]
    bench.stub.flag("fail-resume", on=False)
    bench.assert_one_speech_authority()

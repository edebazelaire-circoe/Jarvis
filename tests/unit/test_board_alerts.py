"""Alertes d'arrière-plan attribuées à leur Board, et retour après absence (handoff board-session, Slice 07).

Contrat : `docs/boards.md` › *Alerts and absence*. Ce que ce fichier épingle :

- **attribution** : une ligne écrite par l'agent d'un Board (journal lié par le
  pool) porte son `board_id` jusqu'à l'alerte ; un diagnostic de Core qui nomme
  une conversation liée reçoit le sien (`BoardAttributingSink`) ; à défaut, les
  liaisons du pool du Control Center résolvent ;
- **classement** : parole retenue par la porte -> `attention`, relais non dit
  -> `said`, sous-agent fini / en échec sur un Board inactif -> `done` /
  `failed`, chacun avec son Board ;
- **persistance** : entrées, curseur d'acquittement et position dans la trace
  survivent au redémarrage du Control Center ; ce qui a été écrit pendant
  l'arrêt est rattrapé ; une trace remplacée est relue depuis le début ; un
  fichier illisible est mis de côté et dit ;
- **aucune parole** : un Board inactif qui finit ou échoue ne produit aucune
  demande de parole, mais une alerte ; l'alerte n'entre dans aucun contexte ;
- **navigation** : « Aller au Board » est la bascule normale.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import aiohttp
import pytest

from jarvis.core.board_attribution import BoardAttributingSink
from jarvis.core.brain_service import BRAIN_SPEECH_WITHHELD_KIND
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.workspace_board import DEFAULT_BOARD_ID, BrainLifecycle
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime.background_events import (
    ATTENTION,
    DONE,
    FAILED,
    MAX_ENTRIES,
    SAID,
    SPEECH_WITHHELD_KIND,
    STORE_FILE,
    BackgroundEventLedger,
    BackgroundEventStore,
    TraceFollower,
    follow,
)
from jarvis.runtime.board_brains import BoardBrainPool
from jarvis.runtime.journal import RuntimeJournal
from tests.unit.test_board_speech_authority import Backend, ask, settle, spoken
from tests.unit.test_board_switch_control_center import Stack


def write(path: Path, *payloads: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def line(kind: str, message: str = "m", **data) -> dict:
    return {"ts": "2026-09-29T10:00:00+00:00", "kind": kind, "level": "info", "message": message, "data": data}


# ------------------------------------------------------------------ attribution


def test_a_pool_agent_journal_attributes_its_completion_failure_and_unsaid_notice(tmp_path):
    """Le chemin réel : le pool lie le journal de l'agent, l'agent écrit, l'alerte nomme le Board."""

    journal = RuntimeJournal(tmp_path)
    agent = SimpleNamespace(journal=journal)
    entry = SimpleNamespace(board_id="board_a", jarvis_session_id="jsess_1")
    BoardBrainPool._bind_journal(entry, agent)  # ce que `_rebind` fait à chaque liaison

    ledger, follower = BackgroundEventLedger(), TraceFollower(journal.trace_path)
    follow(ledger, follower)
    journal.emit("agent.subagent.finished", "Sous-agent terminé en 3 s : Rapport", data={"status": "completed"})
    journal.emit("agent.subagent.finished", "Sous-agent en échec après 2 s : Build", data={"status": "failed"})
    journal.emit("agent.unsolicited_result", "Le rapport est prêt.", data={"spoken": False, "seq": 1})
    journal.emit("agent.unsolicited_result", "Déjà dit.", data={"spoken": True, "seq": 2})
    assert follow(ledger, follower) == 3

    events = ledger.to_payload()["events"]
    assert [(e["category"], e["board_id"]) for e in events] == [(SAID, "board_a"), (FAILED, "board_a"),
                                                               (DONE, "board_a")]
    assert ledger.sources() == [{"board_id": "board_a", "title": None,
                                 "counts": {SAID: 1, FAILED: 1, DONE: 1}}]


def test_withheld_speech_is_an_attention_alert_of_its_board():
    ledger = BackgroundEventLedger()
    entry = ledger.observe(SPEECH_WITHHELD_KIND, "parole retenue : son Board n'a pas la parole",
                           data={"board_id": "board_a", "conversation_id": "c-a", "origin": "notice",
                                 "active_board_id": "board_b"})
    assert entry is not None and entry.category == ATTENTION
    assert entry.board_id == "board_a" and entry.detail == "relais retenu"
    assert SPEECH_WITHHELD_KIND == BRAIN_SPEECH_WITHHELD_KIND, "the ledger reads the kind Core writes"


def test_the_pool_bindings_resolve_a_line_that_names_only_its_conversation():
    ledger = BackgroundEventLedger()
    entry = ledger.observe("core.brain.turn_failed", "échec", data={"conversation_id": "c-a"},
                           resolve_board={"c-a": "board_a"}.get)
    unknown = ledger.observe("core.brain.turn_failed", "échec", data={"conversation_id": "c-x"},
                             resolve_board={"c-a": "board_a"}.get)
    stamped = ledger.observe("core.brain.turn_failed", "échec", data={"conversation_id": "c-a", "board_id": "b"},
                             resolve_board={"c-a": "board_a"}.get)
    assert (entry.board_id, unknown.board_id, stamped.board_id) == ("board_a", "", "b")
    assert unknown.to_payload()["board_id"] is None


def test_core_diagnostics_naming_a_bound_conversation_get_its_board():
    lines = []
    inner = SimpleNamespace(emit=lambda kind, message, level="info", data=None: lines.append((kind, data)),
                            trace_path=Path("t"))
    sink = BoardAttributingSink(inner)
    sink.emit("k", "before the resolver", data={"conversation_id": "c-a"})
    sink.resolve = {"c-a": "board_a"}.get
    sink.emit("k", "bound", data={"conversation_id": "c-a", "x": 1})
    sink.emit("k", "kept", data={"conversation_id": "c-a", "board_id": "own"})
    sink.emit("k", "unbound", data={"conversation_id": "c-z"})
    sink.emit("k", "none", data=None)
    assert [data for _, data in lines] == [
        {"conversation_id": "c-a"}, {"conversation_id": "c-a", "x": 1, "board_id": "board_a"},
        {"conversation_id": "c-a", "board_id": "own"}, {"conversation_id": "c-z"}, None]
    assert sink.trace_path == Path("t"), "the wrapped journal's members stay readable"


# ------------------------------------------------------------------ titres et sources


def test_titles_follow_renames_and_are_kept_when_the_board_list_is_unknown():
    ledger = BackgroundEventLedger()
    ledger.observe("agent.subagent.finished", "fini", data={"status": "completed", "board_id": "board_a"})
    ledger.observe("agent.subagent.finished", "fini", data={"status": "completed"})
    assert ledger.retitle({}) == {"board_a"}
    assert ledger.retitle({"board_a": "Recherche"}) == set()
    assert ledger.retitle({}) == set(), "a title once known is kept (Core down)"
    ledger.retitle({"board_a": "Recherche v2"})
    assert ledger.entries[0].board_title == "Recherche v2"
    ledger.acknowledge()
    assert ledger.sources() == []


# ------------------------------------------------------------------ persistance


def test_restart_keeps_unread_seen_and_cursor_then_catches_up_what_was_written_meanwhile(tmp_path):
    trace = tmp_path / "trace.jsonl"
    write(trace, line("voice.state.updated"))
    store = BackgroundEventStore(tmp_path / STORE_FILE, trace)
    first = store.load()
    ledger, follower = first.ledger, first.follower
    assert first.warning is None and not first.resumed
    follow(ledger, follower)  # premier passage : à la fin, rien d'ancien
    write(trace, line("agent.subagent.finished", "fini A", status="completed", board_id="board_a"),
          line("agent.subagent.finished", "mort A", status="failed", board_id="board_a"),
          line("agent.subagent.finished", "vu", status="completed"))
    assert follow(ledger, follower) == 3
    ledger.acknowledge(1)
    ledger.acknowledge(category=DONE)
    ledger.retitle({"board_a": "Recherche"})
    store.save(ledger, follower)
    assert not (tmp_path / (STORE_FILE + ".tmp")).exists(), "atomic write leaves no temporary file"

    # Control Center arrêté : la trace continue.
    write(trace, line("agent.subagent.finished", "fini pendant l'absence", status="completed", board_id="board_b"))

    again = store.load()
    assert again.warning is None and again.resumed
    assert again.ledger.to_record() == ledger.to_record()
    assert again.ledger.counts() == {FAILED: 1}
    assert follow(again.ledger, again.follower) == 1, "caught up from the persisted offset"
    events = again.ledger.to_payload()["events"]
    assert events[0]["label"] == "fini pendant l'absence" and events[0]["unread"] is True
    assert events[2]["label"] == "mort A" and events[2]["board_title"] == "Recherche"
    assert again.ledger.unread == 2


def test_a_trace_replaced_while_down_is_reread_from_its_start(tmp_path):
    trace = tmp_path / "trace.jsonl"
    store = BackgroundEventStore(tmp_path / STORE_FILE, trace)
    write(trace, line("voice.state.updated", "tête"))
    loaded = store.load()
    follow(loaded.ledger, loaded.follower)
    write(trace, line("voice.state.updated", "x" * 500))
    follow(loaded.ledger, loaded.follower)
    store.save(loaded.ledger, loaded.follower)

    # Tournée pendant l'absence, et déjà plus longue que la position gardée.
    trace.unlink()
    write(trace, line("agent.subagent.finished", "nouvelle trace", status="failed", board_id="board_a",
                      pad="y" * 900))
    again = store.load()
    assert follow(again.ledger, again.follower) == 1
    assert again.follower.resets == 1 and again.ledger.entries[-1].label == "nouvelle trace"


def test_a_trace_shorter_than_the_saved_offset_or_gone_restarts_at_zero(tmp_path):
    trace = tmp_path / "trace.jsonl"
    store = BackgroundEventStore(tmp_path / STORE_FILE, trace)
    write(trace, line("voice.state.updated", "z" * 400))
    loaded = store.load()
    follow(loaded.ledger, loaded.follower)
    store.save(loaded.ledger, loaded.follower)
    trace.unlink()
    gone = store.load()
    assert follow(gone.ledger, gone.follower) == 0 and gone.follower.offset == 0
    write(trace, line("agent.subagent.finished", "reparue", status="failed"))
    assert follow(gone.ledger, gone.follower) == 1


@pytest.mark.parametrize("content", [
    b"{not json", b"[]", b'{"version": 99}', "é".encode("latin-1"),
    b'{"version":1,"ledger":{"seq":"x","acknowledged":0,"entries":[]},"trace":{"offset":0,"head":""}}',
    b'{"version":1,"ledger":{"seq":1,"acknowledged":0,"entries":[]},"trace":{"offset":-4,"head":""}}',
])
def test_a_corrupt_store_is_set_aside_said_and_replaced_by_an_empty_ledger(tmp_path, content):
    trace = tmp_path / "trace.jsonl"
    write(trace, line("agent.subagent.finished", "ancien", status="failed"))
    path = tmp_path / STORE_FILE
    path.write_bytes(content)
    store = BackgroundEventStore(path, trace)
    loaded = store.load()
    assert loaded.warning and "illisible" in loaded.warning
    assert loaded.quarantined == store.quarantine_path and store.quarantine_path.read_bytes() == content
    assert not path.exists() and loaded.ledger.seq == 0
    assert follow(loaded.ledger, loaded.follower) == 0, "restart at the end: no replay of an unknown past"
    store.save(loaded.ledger, loaded.follower)
    assert store.load().warning is None


def test_unreadable_entries_are_dropped_and_counted_and_the_store_stays_bounded(tmp_path):
    ledger = BackgroundEventLedger()
    for index in range(60 + 15):
        ledger.observe("agent.subagent.finished", f"fini {index}", data={"status": "failed", "board_id": "board_a"})
    store = BackgroundEventStore(tmp_path / STORE_FILE, tmp_path / "trace.jsonl")
    store.save(ledger, TraceFollower(tmp_path / "trace.jsonl", offset=0))
    record = json.loads(store.path.read_text(encoding="utf-8"))
    assert len(record["ledger"]["entries"]) == 60, "the literal bound (mutant M13: not the constant)"
    record["ledger"]["entries"][0] = {"seq": "nope"}
    record["ledger"]["entries"][1]["category"] = "unknown"
    store.path.write_text(json.dumps(record), encoding="utf-8")
    loaded = store.load()
    assert loaded.ledger.dropped_entries == 2 and len(loaded.ledger.entries) == 58
    assert "2 notification(s)" in loaded.warning
    assert loaded.ledger.unread == 58


# ------------------------------------------------------------------ Control Center


def make_control(tmp_path: Path):
    from tests.unit.test_board_brains_control_center import make_control as make
    return make(tmp_path)


async def test_the_control_center_persists_restores_and_says_a_corrupt_store(tmp_path):
    control = make_control(tmp_path)
    control._background_summary()  # premier battement : à la fin de la trace
    write(tmp_path / "trace.jsonl",
          line("agent.subagent.finished", "fini sur A", status="completed", board_id="board_a"))
    summary = control._background_summary()
    assert summary["counts"] == {DONE: 1}
    assert summary["sources"] == [{"board_id": "board_a", "title": None, "counts": {DONE: 1}}]
    assert "store_warning" not in summary
    await control.board_brains.aclose()

    # Redémarrage : même dossier runtime, nouvelle instance.
    write(tmp_path / "trace.jsonl",
          line("agent.subagent.finished", "échec pendant l'arrêt", status="failed", board_id="board_a"))
    restarted = make_control(tmp_path)
    summary = restarted._background_summary()
    assert summary["counts"] == {DONE: 1, FAILED: 1} and summary["unread"] == 2
    answer = await restarted.background_ack(_Json({"category": DONE}))
    assert json.loads(answer.text)["persisted"] is True
    await restarted.board_brains.aclose()
    assert make_control(tmp_path)._background_summary()["counts"] == {FAILED: 1}, "the ack survives too"

    (tmp_path / STORE_FILE).write_text("{broken", encoding="utf-8")
    broken = make_control(tmp_path)
    summary = broken._background_summary()
    assert "illisible" in summary["store_warning"]
    errors = [json.loads(x) for x in (tmp_path / "errors.jsonl").read_text(encoding="utf-8").splitlines()]
    assert errors[-1]["kind"] == "background.store_unreadable" and errors[-1]["level"] == "error"
    payload = json.loads((await broken.background_events(_Json({}, {"limit": "10"}))).text)
    assert "illisible" in payload["store_warning"]
    await broken.board_brains.aclose()


class _Json:
    def __init__(self, payload: object, query: dict | None = None) -> None:
        self._payload = payload
        self.query = query or {}

    async def json(self) -> object:
        return self._payload


# ------------------------------------------------------------------ aucune parole, une alerte (Core réel)


@pytest.fixture
async def gated_core(tmp_path):
    """Core complet dont les diagnostics vont dans la trace que suit le registre."""

    journal = RuntimeJournal(tmp_path)
    backend = Backend()
    app = JarvisCoreApplication(data_root=tmp_path / "core", brain_backend=backend, diagnostics=journal,
                                work_attention_wake_interval_s=0.01)
    await app.start()
    await asyncio.wait_for(app._host_align_task, timeout=5)
    queue = app.events.subscribe()
    ledger, follower = BackgroundEventLedger(), TraceFollower(journal.trace_path)
    follow(ledger, follower)
    try:
        yield app, backend, queue, ledger, follower
    finally:
        app.events.unsubscribe(queue)
        await app.stop()


async def test_an_inactive_board_completion_never_speaks_but_raises_an_attributed_alert(gated_core):
    app, backend, queue, ledger, follower = gated_core
    a = (await app.sessions.current()).binding
    b_board = await app.boards.create({"title": "Projet B"})
    backend.gates[a.conversation_id] = asyncio.Event()
    await ask(app, a.conversation_id, "long travail sur A")
    b = (await app.boards.switch(b_board.board_id)).binding
    spoken(queue)

    backend.gates[a.conversation_id].set()          # A finit pendant qu'on est sur B
    await settle(app)
    assert not await app.brain.announce_notice("A a fini.", conversation_id=a.conversation_id)
    assert spoken(queue) == [], "an inactive Board never speaks"

    follow(ledger, follower)
    alerts = [e for e in ledger.entries if e.kind == SPEECH_WITHHELD_KIND]
    assert [(e.category, e.board_id, e.detail) for e in alerts] == [
        (ATTENTION, DEFAULT_BOARD_ID, "réponse retenue"), (ATTENTION, DEFAULT_BOARD_ID, "relais retenu")]
    # Tout diagnostic de Core qui nomme une conversation liée porte son Board.
    trace = [json.loads(x) for x in (follower.path).read_text(encoding="utf-8").splitlines()]
    owners = {a.conversation_id: DEFAULT_BOARD_ID, b.conversation_id: b_board.board_id}
    named = [t for t in trace if t["data"].get("conversation_id") in owners]
    assert named and all(t["data"].get("board_id") == owners[t["data"]["conversation_id"]] for t in named)

    # Pas de fusion de contexte : le tour suivant de B ne voit rien de l'alerte de A.
    await ask(app, b.conversation_id, "et ici ?")
    await settle(app)
    assert spoken(queue) == [(b.conversation_id, "réponse: et ici ?")]
    context = repr(backend.contexts[-1][1])
    assert backend.contexts[-1][0] == b.conversation_id
    assert "retenue" not in context and "long travail sur A" not in context


# ------------------------------------------------------------------ bout en bout : Core + Control Center réels


async def test_on_b_a_background_subagent_of_a_finishes_the_alert_names_a_navigation_switches_and_survives(tmp_path):
    stack = Stack(tmp_path)
    await stack.serve_control()
    try:
        core = await stack.start_core()
        a = (await core.sessions.current()).binding
        agent_a = stack.control.agent
        agent_a.start_subagent("t-a")                        # A travaille en fond
        status, created = await stack.call("POST", "/api/boards", json={"title": "Projet B"})
        b_id = created["board"]["board_id"]
        await stack.call("GET", "/api/status")               # position à la fin de la trace
        status, _ = await stack.call("POST", "/api/boards/switch", json={"board_id": b_id})
        assert status == 200
        assert stack.control.board_brains.find(a.conversation_id).lifecycle is BrainLifecycle.BACKGROUND_RUNNING

        agent_a.subtasks.observe_claude({"type": "system", "subtype": "task_notification", "task_id": "t-a",
                                         "status": "failed", "summary": "build rouge"},
                                        now_ms=agent_a.subtasks.now_ms())
        status, first = await stack.call("GET", "/api/status")
        assert first["boards"]["active"]["board_id"] == b_id
        for _ in range(50):                                   # titres relus en tâche de fond
            if stack.control._board_titles_task is None or stack.control._board_titles_task.done():
                break
            await asyncio.sleep(0.02)
        status, listed = await stack.call("GET", "/api/background")
        failed = [e for e in listed["events"] if e["category"] == FAILED]
        assert failed and failed[0]["board_id"] == DEFAULT_BOARD_ID and failed[0]["board_title"] == "Board principal"
        status, beat = await stack.call("GET", "/api/status")
        assert {"board_id": DEFAULT_BOARD_ID, "title": "Board principal", "counts": {FAILED: 1}} in beat["background"]["sources"]

        # « Aller au Board » = la bascule normale, rien d'autre que le Board.
        status, back = await stack.call("POST", "/api/boards/switch", json={"board_id": DEFAULT_BOARD_ID})
        assert status == 200 and back["board"]["board_id"] == DEFAULT_BOARD_ID
        assert stack.control.board_brains.foreground.key == a.conversation_id

        # Redémarrage du Control Center : l'alerte est toujours non lue.
        await stack.control.stop()
        restarted = make_control(tmp_path)
        summary = restarted._background_summary()
        assert summary["counts"].get(FAILED) == 1
        assert any(row["board_id"] == DEFAULT_BOARD_ID and row["title"] == "Board principal" for row in summary["sources"])
        await restarted.board_brains.aclose()
    finally:
        await stack.stop_core()
        if stack.runner is not None:
            await stack.runner.cleanup()


# ------------------------------------------------------------------ reprise QA 06/07 (points 5, 7, 8, NIT)


def test_a_line_longer_than_the_read_budget_is_skipped_once_and_the_next_alert_is_kept(tmp_path):
    """Point 5 : une ligne de 1,1 Mio faisait relire la trace depuis zéro (doublons) et perdre l'alerte suivante."""

    trace = tmp_path / "trace.jsonl"
    store = BackgroundEventStore(tmp_path / STORE_FILE, trace)
    write(trace, line("voice.state.updated", "tête"))
    loaded = store.load()
    ledger, follower = loaded.ledger, loaded.follower
    follow(ledger, follower)
    write(trace, line("agent.subagent.finished", "avant", status="failed", board_id="board_a"))
    assert follow(ledger, follower) == 1
    write(trace, line("voice.state.updated", "g" * (1_100_000)))
    write(trace, line("agent.subagent.finished", "après la ligne géante", status="completed", board_id="board_a"))
    for _ in range(4):                                       # plusieurs battements
        follow(ledger, follower)
    labels = [entry.label for entry in ledger.entries]
    assert labels == ["avant", "après la ligne géante"], "one new alert, no duplicate, nothing lost"
    assert follower.skipped_lines == 1 and follower.resets == 0
    store.save(ledger, follower)
    assert trace.read_bytes()[follower.offset - 1:follower.offset] == b"\n", "the saved offset is a line boundary"

    again = store.load()                                     # redémarrage : stable
    assert follow(again.ledger, again.follower) == 0 and again.follower.resets == 0
    assert [entry.label for entry in again.ledger.entries] == labels


def test_a_giant_line_still_being_written_is_not_skipped_into_its_middle(tmp_path):
    trace = tmp_path / "trace.jsonl"
    write(trace, line("voice.state.updated", "tête"))
    follower = TraceFollower(trace)
    follower.poll()
    start = follower.offset
    with trace.open("ab") as handle:
        handle.write(b'{"kind": "x", "pad": "' + b"h" * 1_100_000)  # pas encore de fin de ligne
    assert follower.poll() == [] and follower.offset == start and follower.skipped_lines == 0
    with trace.open("ab") as handle:
        handle.write(b'"}\n')
    write(trace, line("agent.subagent.finished", "suite", status="failed"))
    follower.poll()
    rows = follower.poll()
    assert [row["kind"] for row in rows] == ["agent.subagent.finished"] and follower.skipped_lines == 1


def test_a_replaced_trace_whose_old_offset_falls_on_a_line_boundary_is_still_reread(tmp_path):
    """Mutant M11 : sans le contrôle de tête, une trace remplacée alignée par hasard n'était pas relue."""

    trace = tmp_path / "trace.jsonl"
    store = BackgroundEventStore(tmp_path / STORE_FILE, trace)
    first = json.dumps(line("voice.state.updated", "a" * 100), ensure_ascii=False) + "\n"
    second = json.dumps(line("voice.state.updated", "b" * 100), ensure_ascii=False) + "\n"
    trace.write_text(first, encoding="utf-8")
    loaded = store.load()
    follow(loaded.ledger, loaded.follower)
    write(trace, json.loads(second))
    follow(loaded.ledger, loaded.follower)
    store.save(loaded.ledger, loaded.follower)
    saved = loaded.follower.offset

    # Remplacée pendant l'absence par une trace dont les deux premières lignes ont la même longueur.
    alert = line("agent.subagent.finished", "x", status="failed", board_id="board_a")
    base = len(json.dumps(alert, ensure_ascii=False)) + 1
    pad = lambda target: dict(alert, message="x" * (1 + target - base))  # noqa: E731
    replaced = [pad(len(first.encode("utf-8"))), pad(len(second.encode("utf-8")))]
    trace.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in replaced), encoding="utf-8")
    assert trace.stat().st_size == saved and trace.read_bytes()[saved - 1:saved] == b"\n"
    write(trace, line("agent.subagent.finished", "troisième", status="failed", board_id="board_a"))

    again = store.load()
    assert follow(again.ledger, again.follower) == 3, "re-read from its start: the two replaced lines too"
    assert again.follower.resets == 1


def test_an_acknowledged_cursor_beyond_the_sequence_is_clipped_so_new_alerts_stay_unread(tmp_path):
    """Mutant M12 : un curseur relu au-delà de `seq` aurait rendu « lue » l'alerte suivante."""

    trace = tmp_path / "trace.jsonl"
    write(trace, line("voice.state.updated"))
    path = tmp_path / STORE_FILE
    path.write_text(json.dumps({"version": 1, "ledger": {"seq": 3, "acknowledged": 10, "entries": []},
                                "trace": {"offset": 0, "head": ""}}), encoding="utf-8")
    loaded = BackgroundEventStore(path, trace).load()
    assert loaded.ledger.acknowledged == 3
    loaded.ledger.observe("agent.subagent.finished", "nouvelle", data={"status": "failed"})
    assert loaded.ledger.unread == 1


def test_duplicate_sequence_numbers_in_the_store_load_once(tmp_path):
    ledger = BackgroundEventLedger()
    ledger.observe("agent.subagent.finished", "une", data={"status": "failed"})
    ledger.observe("agent.subagent.finished", "deux", data={"status": "failed"})
    record = ledger.to_record()
    record["entries"].append(dict(record["entries"][0], label="doublon"))
    again = BackgroundEventLedger.from_record(record)
    assert [(e.seq, e.label) for e in again.entries] == [(1, "une"), (2, "deux")]
    assert again.dropped_entries == 1 and again.unread == 2


async def test_an_offset_only_move_is_saved_at_most_every_ten_seconds(tmp_path):
    """Mutant M14 : sans la limite, chaque battement qui avance le curseur réécrivait le fichier."""

    control = make_control(tmp_path)
    control._background_summary()
    saves = []
    real = control._save_background
    control._save_background = lambda: (saves.append(1), real())[1]
    control._background_saved_at = __import__("time").monotonic()
    write(tmp_path / "trace.jsonl", line("voice.state.updated", "bruit"))
    control._background_summary()
    assert saves == [], "the offset moved, no alert: not saved within 10 s"
    control._background_saved_at -= control.BACKGROUND_OFFSET_SAVE_S + 1
    control._background_summary()
    assert len(saves) == 1, "saved once the 10 s have passed"
    assert control.BACKGROUND_OFFSET_SAVE_S == 10
    await control.board_brains.aclose()


class _Raw:
    """Requête aiohttp minimale : un corps brut (ou absent)."""

    def __init__(self, raw: bytes | None) -> None:
        self._raw = raw
        self.body_exists = bool(raw)

    async def json(self):  # noqa: ANN201
        if not self._raw:
            raise json.JSONDecodeError("Expecting value", "", 0)
        return json.loads(self._raw)


@pytest.mark.parametrize("body", [b'{"seq":"1"}', b'{"seq":true}', b'{"seq":-1}', b'{"seq":null}',
                                  b'{"seq":1.5}', b"[1]", b"{broken"])
async def test_a_malformed_ack_is_refused_and_acknowledges_nothing(tmp_path, body):
    """Point 8 : `{"seq":"1"}` acquittait tout (un seq non entier valait « tout »)."""

    control = make_control(tmp_path)
    control._background_summary()
    write(tmp_path / "trace.jsonl", line("agent.subagent.finished", "a", status="failed"),
          line("agent.subagent.finished", "b", status="failed"))
    assert control._background_summary()["unread"] == 2
    answer = await control.background_ack(_Raw(body))
    assert answer.status == 400 and json.loads(answer.text)["code"] == "invalid_request"
    assert control._background_summary()["unread"] == 2, "nothing acknowledged"
    absent = await control.background_ack(_Raw(None))           # seul un seq absent veut dire « tout »
    assert absent.status == 200 and json.loads(absent.text)["unread"] == 0
    await control.board_brains.aclose()

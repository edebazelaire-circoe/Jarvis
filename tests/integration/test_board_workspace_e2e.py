"""Mémoire de Board et inspecteur du workspace de bout en bout (board-memory-workspace-inspector, Slice 09).

Même banc que `test_board_session_e2e.py` : Core **réel** (`JarvisCoreApplication` +
`LocalProtocolServer`, SQLite et racine de données sous `tmp_path`), Control Center
**réel** (`ControlCenter.start` en HTTP, relais `/api/workspace/*`, pool des cerveaux de
Board, `boards_dir` et `jarvis-workspace` câblés comme dans `jarvis/app.py`). Le serveur
MCP `jarvis-workspace` est le vrai serveur FastMCP (`build_server`) connecté en mémoire à
un client MCP et qui parle HTTP au vrai Control Center. Seul l'exécutable `claude` est
une doublure : un vrai processus Python stream-json qui note ses arguments et chaque
message reçu (le bloc `board` du tour y est lisible tel que le cerveau le recevrait).

Matrice (`tasks/jarvis-board-memory-workspace-inspector/slices/09-e2e-rollout/EVIDENCE.md`) :

- (a) migration v7 -> v8 d'une base fabriquée par le code v7 (`467232f`), sauvegarde
  `.v7.bak`, données intactes, puis usage normal et redémarrage ;
- (b) mémoire d'un Board à travers un redémarrage de Core : fichiers, ledger, Session
  reprise, `last_opened_at` marqué ;
- (c) bascule + hydratation : la mémoire de A est dans le bloc de A, jamais dans celui de B ;
- (d) inspection historique non activante sur chaque route de lecture et chaque outil MCP
  de lecture ;
- (e) parité écran / MCP : même opération, même résultat, même code d'erreur ;
- (f) tentatives d'évasion de chemin de bout en bout (HTTP + MCP), dont une vraie jonction ;
- (g) Board archivé : lectures permises, écritures refusées partout.

Aucun réseau hors loopback, aucun modèle. ~1 min pour le module.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sqlite3
from types import SimpleNamespace

import pytest

from jarvis.adapters import sqlite_state
from jarvis.domain.artifacts import ArtifactKind
from jarvis.domain.board_memory import BOARDS_DIR
from jarvis.domain.workspace_board import DEFAULT_BOARD_ID
from jarvis.runtime import claude_local
from jarvis.runtime.claude_local import ClaudeLocalAgent
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.core_sessions import CoreSessionTransport
from jarvis.runtime.interaction_mode_view import CoreInteractionModeTransport, CoreInteractionModeView
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.settings_mcp import ConsoleMcpTarget
from jarvis.runtime.workspace_mcp import WorkspaceTools, build_server
from tests.integration.test_board_session_e2e import STUB, Bench, Stub

FIXTURE_V7 = Path(__file__).resolve().parents[1] / "fixtures" / "sqlite_state" / "state_v7_real_shaped.sql"

# La doublure note aussi ses arguments : `--add-dir <data_root>/boards` et le `--mcp-config` de jarvis-workspace.
WORKSPACE_STUB = STUB.replace('log("spawns.log", {"pid": os.getpid(),',
                              'log("spawns.log", {"argv": argv, "pid": os.getpid(),')
assert WORKSPACE_STUB != STUB, "the stub template changed: argv is no longer recorded"


class WorkspaceStub(Stub):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.script.write_text(WORKSPACE_STUB, encoding="utf-8")

    def all_inputs(self) -> list[str]:
        return [row["line"] for row in self._rows("inputs.log")]


class WorkspaceBench(Bench):
    """Le banc Board/Session, plus la mémoire des Boards et `jarvis-workspace` câblés comme en production."""

    def __init__(self, tmp_path: Path) -> None:
        super().__init__(tmp_path)
        self.stub = WorkspaceStub(tmp_path / "stub")
        self.boards_dir = (self.data / BOARDS_DIR).resolve()

    def build_control(self) -> ControlCenter:
        def transport(cls):  # noqa: ANN001, ANN202
            return cls(host="127.0.0.1", port=self.core_port, token_file=self.token_file)

        journal = RuntimeJournal(self.runtime)
        return ControlCenter(
            runtime_root=self.runtime, project_root=self.project, boards_dir=self.boards_dir,
            sessions=transport(CoreSessionTransport),
            interaction_mode_view=CoreInteractionModeView(transport(CoreInteractionModeTransport), journal=journal),
            console_mcp=ConsoleMcpTarget("127.0.0.1", self.cc_port, self.runtime),
            workspace_mcp=ConsoleMcpTarget("127.0.0.1", self.cc_port, self.runtime),
            agent_factory=lambda cli: ClaudeLocalAgent(runtime_root=self.runtime, cwd=self.project),
        )

    def memory(self, board_id: str) -> Path:
        return self.boards_dir / board_id / "memory"


@pytest.fixture
async def bench(tmp_path, monkeypatch):
    bench = WorkspaceBench(tmp_path)
    monkeypatch.setattr(claude_local.asyncio, "create_subprocess_exec", bench.stub.spawner())
    try:
        yield bench
    finally:
        await bench.close()


async def up(bench: WorkspaceBench):  # noqa: ANN201
    core = await bench.start_core()
    await bench.start_control()
    current = (await core.sessions.current()).binding.conversation_id
    await bench.until(lambda: bench.control.board_brains.foreground.key == current, what="CC adoption")
    return core


# ------------------------------------------------------------------ le cerveau MCP (vrai serveur FastMCP)


REFUSAL = re.compile(r"^Refus (\w+) : ")


class Brain:
    """`jarvis-workspace` réel, client MCP en mémoire, HTTP vers le vrai Control Center du banc."""

    def __init__(self, bench: WorkspaceBench) -> None:
        self.tools = WorkspaceTools(ConsoleMcpTarget("127.0.0.1", bench.cc_port))
        self.server = build_server(tools=self.tools)

    async def __aenter__(self) -> "Brain":
        from mcp.shared.memory import create_connected_server_and_client_session

        self._cm = create_connected_server_and_client_session(self.server)
        self.session = await self._cm.__aenter__()
        return self

    async def __aexit__(self, *exc) -> None:
        await self._cm.__aexit__(*exc)
        await self.tools.close()

    async def call(self, name: str, arguments: dict | None = None) -> dict:
        result = await self.session.call_tool(name, arguments or {})
        assert result.isError is False, (name, result.content[0].text)
        return result.structuredContent

    async def code(self, name: str, arguments: dict) -> str:
        """Le code stable d'un refus, lu dans le texte que le cerveau reçoit."""

        result = await self.session.call_tool(name, arguments)
        assert result.isError is True, (name, arguments, result.structuredContent)
        text = result.content[0].text
        match = REFUSAL.match(text)
        assert match, text
        return match.group(1)


async def http_code(bench: WorkspaceBench, method: str, path: str, **kwargs) -> str:
    status, body = await bench.call(method, path, **kwargs)
    assert status >= 400, (method, path, status, body)
    return body["error"]["code"]


def ws(board_id: str, tail: str = "") -> str:
    return f"/api/workspace/boards/{board_id}{tail}"


# ------------------------------------------------------------------ photographie de tout ce qui ne doit pas bouger


async def quiet_snapshot(bench: WorkspaceBench, *, still_s: float = 1.0, timeout_s: float = 20.0) -> dict:
    """La photographie une fois le tour précédent tout à fait retombé (événements de conversation projetés après
    coup, liaison rapportée par le CLI) : identique pendant `still_s`, sinon échec dit."""

    import asyncio

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    last = await foreground_snapshot(bench)
    while True:
        await asyncio.sleep(still_s)
        now = await foreground_snapshot(bench)
        if now == last:
            return now
        assert loop.time() < deadline, "the stack never went quiet"
        last = now


def same(before: dict, after: dict, why: str) -> None:
    """Égalité des photographies, avec ce qui a bougé dans le message."""

    moved = {key: (before[key], after[key]) for key in before if before[key] != after[key]}
    if "counts" in moved:
        moved["counts"] = {t: (n, after["counts"].get(t)) for t, n in before["counts"].items()
                           if after["counts"].get(t) != n}
    assert not moved, f"{why}: {moved}"


async def foreground_snapshot(bench: WorkspaceBench) -> dict:
    """Base (chaque table, Sessions, liaisons, Boards), dossier `boards/`, autorité, mode, pool du CC, CLI lancés."""

    def read(conn):  # noqa: ANN001, ANN202
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        counts = {name: conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0] for name in tables}
        rows = [tuple(r) for q in (
            "SELECT jarvis_session_id, status, active_board_id, data FROM jarvis_sessions ORDER BY 1",
            "SELECT jarvis_session_id, board_id, lifecycle, status, data FROM board_conversation_bindings ORDER BY 1, 2",
            "SELECT board_id, status, updated_at, data FROM work_boards ORDER BY 1") for r in conn.execute(q)]
        return counts, rows

    counts, rows = await bench.core.state.run_serialized(read)
    listing = []
    if bench.boards_dir.exists():
        for folder, dirs, files in os.walk(bench.boards_dir):
            for name in sorted(dirs + files):
                info = os.lstat(Path(folder) / name)
                listing.append((str(Path(folder, name).relative_to(bench.boards_dir)), info.st_size, info.st_mtime_ns))
    authority = bench.core.speech_authority.binding
    return {"counts": counts, "rows": rows, "memory": sorted(listing),
            "authority": None if authority is None else authority.to_payload(),
            "mode": bench.core.interaction_mode.snapshot(),
            "cc_foreground": bench.control.board_brains.foreground.key,
            "cli_spawns": len(bench.stub.spawns())}


# ------------------------------------------------------------------ (a) migration v7 -> v8


def _sql(db: Path, query: str) -> list[tuple]:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(query).fetchall()
    finally:
        conn.close()


def _dump(db: Path) -> list[str]:
    conn = sqlite3.connect(db)
    try:
        return list(conn.iterdump())
    finally:
        conn.close()


def _counts(db: Path) -> dict[str, int]:
    names = [n for (n,) in _sql(db, "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return {name: _sql(db, f'SELECT count(*) FROM "{name}"')[0][0] for name in names}


def _install_v7_root(bench: WorkspaceBench) -> Path:
    """La base v7 fabriquée par le code v7, plus les dossiers de Context que ce code avait créés."""

    db = bench.data / "state" / "jarvis.sqlite3"
    conn = sqlite3.connect(db)
    try:
        conn.executescript(FIXTURE_V7.read_text(encoding="utf-8"))
    finally:
        conn.close()
    for session_id, context_id in _sql(db, "SELECT jarvis_session_id, context_id FROM session_contexts"):
        (bench.data / "sessions" / session_id / "contexts" / context_id).mkdir(parents=True, exist_ok=True)
    return db


async def test_a_v7_root_made_by_the_v7_code_migrates_once_keeps_everything_and_then_works(bench):
    db = _install_v7_root(bench)
    assert _sql(db, "SELECT version FROM schema_version") == [(7,)]
    before = _counts(db)
    (open_session, atlas), = _sql(db, "SELECT jarvis_session_id, active_board_id FROM jarvis_sessions "
                                      "WHERE status = 'open'")
    (closed_session,), = _sql(db, "SELECT jarvis_session_id FROM jarvis_sessions WHERE status = 'closed'")
    boards_v7 = {b: json.loads(d) for b, d in _sql(db, "SELECT board_id, data FROM work_boards")}
    archived = next(b for b, d in boards_v7.items() if d["status"] == "archived")
    boree = next(b for b, d in boards_v7.items() if d["title"] == "Ancien projet Borée")
    v7_dump = _dump(db)

    await up(bench)

    # Une étape, une sauvegarde v7 ligne pour ligne, rien de perdu, une seule table neuve, aucun rattrapage.
    assert _sql(db, "SELECT version FROM schema_version") == [(sqlite_state._SCHEMA_VERSION,)] == [(8,)]
    backup = db.parent / "jarvis.sqlite3.v7.bak"
    assert sorted(p.name for p in db.parent.glob("*.bak")) == [backup.name]
    assert _dump(backup) == v7_dump, "the backup is the v7 database, row for row"
    after = _counts(db)
    assert set(after) - set(before) == {"board_artifact_links"}
    assert {t: n for t, n in before.items() if after[t] < n} == {}, "a v7 row was lost"
    assert after["board_artifact_links"] == 0, "no backfill of pre-v8 artifacts"

    # La Session ouverte de v7 est reprise sur son Board, avec ses tours.
    current = await bench.ok("GET", "/api/sessions/current")
    assert current["session"]["jarvis_session_id"] == open_session
    assert current["session"]["active_board_id"] == atlas
    turns = await bench.core.state.list_turns(current["binding"]["conversation_id"])
    assert [t.content for t in turns] == ["où en est Atlas ?", "Lot 2 en cours."]

    # Boards v7 : nature absente lue `empty`, champs et références legacy intacts, archivé toujours archivé.
    every = (await bench.ok("GET", "/api/boards", params={"include_archived": "true"}))["boards"]
    assert {b["board_id"] for b in every} == set(boards_v7)
    assert all(b["board_kind"] == "empty" for b in every)
    atlas_view = await bench.ok("GET", ws(atlas))
    assert atlas_view["board"]["context_summary"] == "Refonte du site, lot 2"
    assert atlas_view["board"]["task_refs"] == ["task-atlas-1"]
    assert atlas_view["legacy_artifact_refs"]["items"] == ["drive:atlas-brief"]
    assert atlas_view["memory"]["exists"] is False, "no memory folder invented for a v7 Board"
    assert (await bench.ok("GET", ws(archived)))["board"]["status"] == "archived"

    # Historique v7 lisible : Session close, ses Boards, ses Artifacts et leur provenance.
    sessions = (await bench.ok("GET", "/api/workspace/sessions"))["sessions"]
    assert [s["jarvis_session_id"] for s in sessions] == [open_session, closed_session]
    closed = await bench.ok("GET", f"/api/workspace/sessions/{closed_session}")
    assert {b["board_id"] for b in closed["boards"] if b.get("visited")} >= {boree, atlas}
    old_items = (await bench.ok("GET", "/api/workspace/artifacts",
                                params={"session_id": closed_session}))["artifacts"]
    assert len(old_items) == 2
    derived = next(a for a in old_items if a["kind"] == ArtifactKind.DERIVED.value)
    transcript = next(a for a in old_items if a["kind"] == ArtifactKind.TRANSCRIPT.value)
    provenance = await bench.ok("GET", f"/api/workspace/artifacts/{derived['artifact_id']}/relations")
    assert [(r["relation"], r["origin_artifact_id"]) for r in provenance["origins"]] == [
        ("derived_from", transcript["artifact_id"])], provenance
    assert (await bench.ok("GET", "/api/workspace/artifacts", params={"board_id": boree}))["artifacts"] == []

    # Usage normal en v8 : mémoire écrite, Artifact neuf lié au Board actif, lien explicite d'un ancien.
    written = await bench.ok("POST", ws(atlas, "/memory/write"), json={"path": "summary.md",
                                                                      "content": "# Atlas\nmigré en v8\n"})
    assert written["created"] is True
    context = await bench.core.sessions.current_context()
    fresh = await bench.core.artifacts.record_text(
        artifact_id="jart_" + "9" * 32, kind=ArtifactKind.DESCRIPTION, source="e2e", text="après migration",
        jarvis_session_id=open_session, context_id=context.context.context_id, started_at=None, ended_at=None,
        duration_ms=None, metadata={}, origins=())
    await bench.ok("POST", ws(boree, f"/artifacts/{derived['artifact_id']}"), json={})
    links = _sql(db, "SELECT board_id, artifact_id, origin FROM board_artifact_links ORDER BY origin")
    assert links == [(atlas, fresh.artifact_id, "active_board"), (boree, derived["artifact_id"], "explicit")]

    # Redémarrage : pas de seconde migration ni de seconde sauvegarde, même Session, mémoire relue.
    await bench.stop_core()
    await bench.start_core()
    assert sorted(p.name for p in db.parent.glob("*.bak")) == [backup.name]
    again = await bench.ok("GET", "/api/sessions/current")
    assert again["session"]["jarvis_session_id"] == open_session
    page = await bench.ok("GET", ws(atlas, "/memory/read"), params={"path": "summary.md"})
    assert page["text"] == "# Atlas\nmigré en v8\n"
    bench.assert_one_speech_authority()


# ------------------------------------------------------------------ (b) cycle de vie à travers un redémarrage


async def test_board_memory_and_its_ledger_survive_a_core_restart_and_the_session_resumes(bench):
    core = await up(bench)
    a = DEFAULT_BOARD_ID
    b = (await bench.ok("POST", "/api/boards", json={"title": "Recherche", "board_kind": "meeting"}))["board"][
        "board_id"]
    await bench.ok("POST", ws(a, "/memory/write"), json={"path": "summary.md", "content": "# A\nlot 1\n"})
    await bench.ok("POST", ws(a, "/memory/mkdir"), json={"path": "notes"})
    first = await bench.ok("POST", ws(a, "/memory/write"), json={"path": "notes/brouillon.md", "content": "v1\n"})
    await bench.ok("POST", ws(a, "/memory/write"), json={"path": "notes/brouillon.md", "content": "v2\n",
                                                         "mode": "replace", "expected_sha256": first["sha256"]})
    await bench.ok("POST", ws(a, "/memory/write"), json={"path": "notes/brouillon.md", "content": "suite\n",
                                                         "mode": "append"})
    await bench.ok("POST", ws(a, "/memory/move"), json={"from": "notes/brouillon.md", "to": "notes/plan.md"})
    await bench.ok("POST", ws(a, "/memory/write"), json={"path": "jetable.md", "content": "x"})
    await bench.ok("POST", ws(a, "/memory/delete"), json={"path": "jetable.md"})
    await bench.ok("POST", ws(b, "/memory/write"), json={"path": "decisions.md", "content": "ORION-42\n"})

    session = (await bench.ok("GET", "/api/sessions/current"))["session"]
    session_id, context_before = session["jarvis_session_id"], (await core.sessions.current_context()).context
    ledger = (await bench.ok("GET", f"/api/workspace/sessions/{session_id}/activity",
                             params={"limit": "100"}))["events"]
    board_rows = [e for e in ledger if e["kind"].startswith("board.")]
    assert [e["kind"] for e in board_rows] == ["board.memory.written"] * 5 + [
        "board.memory.moved", "board.memory.written", "board.memory.deleted", "board.memory.written"]
    assert [e["data"]["board_id"] for e in board_rows] == [a] * 8 + [b]
    tree_before = (await bench.ok("GET", ws(a, "/memory/tree"), params={"depth": "3"}))["entries"]
    opened_before = (await bench.ok("GET", f"/api/boards/{a}"))["board"]["last_opened_at"]
    assert opened_before, "the Board of an opened Session is marked opened"

    await bench.stop_core()
    core = await bench.start_core()
    await bench.until(lambda: bench.control.board_brains.foreground is not None, what="CC foreground")

    resumed = (await bench.ok("GET", "/api/sessions/current"))["session"]
    assert resumed["jarvis_session_id"] == session_id and resumed["active_board_id"] == a
    assert (await core.sessions.current_context()).context.context_id == context_before.context_id
    assert len((await bench.ok("GET", "/api/workspace/sessions"))["sessions"]) == 1, "a restart opens nothing"
    again = (await bench.ok("GET", f"/api/workspace/sessions/{session_id}/activity",
                            params={"limit": "100"}))["events"]
    assert [e for e in again if e["kind"].startswith("board.")] == board_rows, "ledger rows intact"
    assert (await bench.ok("GET", ws(a, "/memory/tree"), params={"depth": "3"}))["entries"] == tree_before
    assert (await bench.ok("GET", ws(a, "/memory/read"), params={"path": "notes/plan.md"}))["text"] == "v2\nsuite\n"
    assert (await bench.ok("GET", ws(b, "/memory/read"), params={"path": "decisions.md"}))["text"] == "ORION-42\n"
    assert not (bench.memory(a) / "jetable.md").exists()
    opened_after = (await bench.ok("GET", f"/api/boards/{a}"))["board"]["last_opened_at"]
    assert opened_after > opened_before, "resuming the Session marks its Board opened again"
    assert (await bench.ok("GET", f"/api/boards/{b}"))["board"]["last_opened_at"] is None, "B was never opened"
    # Et l'écriture continue après la reprise, rattachée à la même Session.
    await bench.ok("POST", ws(a, "/memory/write"), json={"path": "apres.md", "content": "ok\n"})
    tail = (await bench.ok("GET", f"/api/workspace/sessions/{session_id}/activity",
                           params={"kind": "board.memory.written", "limit": "100"}))["events"]
    assert tail[-1]["data"]["path"] == "apres.md"
    bench.assert_one_speech_authority()


# ------------------------------------------------------------------ (c) bascule + hydratation


async def test_each_board_turn_carries_its_own_memory_and_never_the_other_boards(bench):
    core = await up(bench)
    a = DEFAULT_BOARD_ID
    b = (await bench.ok("POST", "/api/boards", json={"title": "Borée", "board_kind": "meeting"}))["board"]["board_id"]
    await bench.ok("POST", ws(a, "/memory/write"), json={"path": "summary.md", "content": "Mémoire A : ALPHA-7\n"})
    await bench.ok("POST", ws(a, "/memory/write"), json={"path": "notes/a-seul.md", "content": "x"})
    await bench.ok("POST", ws(b, "/memory/write"), json={"path": "summary.md", "content": "Mémoire B : BRAVO-9\n"})
    await bench.ok("POST", ws(b, "/memory/write"), json={"path": "b-seul.md", "content": "y"})
    context_id = (await core.sessions.current_context()).context.context_id

    def last_input() -> str:
        return bench.stub.all_inputs()[-1]

    await bench.turn("tour sur A")
    on_a = last_input()
    assert "ALPHA-7" in on_a and "a-seul.md" in on_a and f"boards/{a}/memory" in on_a
    assert "BRAVO-9" not in on_a and "b-seul.md" not in on_a and b not in on_a

    await bench.ok("POST", "/api/boards/switch", json={"board_id": b})
    await bench.turn("tour sur B")
    on_b = last_input()
    assert "BRAVO-9" in on_b and "b-seul.md" in on_b and f"boards/{b}/memory" in on_b and "meeting" in on_b
    assert "ALPHA-7" not in on_b and "a-seul.md" not in on_b

    # Une écriture sur A pendant que B est actif n'atteint pas le tour de B ; elle est là au retour sur A.
    await bench.ok("POST", ws(a, "/memory/write"), json={"path": "summary.md", "content": "Mémoire A : ALPHA-8\n",
                                                         "mode": "replace"})
    await bench.turn("encore B")
    assert "ALPHA" not in last_input()
    await bench.ok("POST", "/api/boards/switch", json={"board_id": a})
    await bench.turn("retour sur A")
    back = last_input()
    assert "ALPHA-8" in back and "BRAVO-9" not in back

    # Le Context n'a pas suivi les Boards (Board memory et SessionContext distincts), rien n'a été copié.
    assert (await core.sessions.current_context()).context.context_id == context_id
    context_dir = bench.data / "sessions" / (await core.sessions.current()).session.jarvis_session_id
    assert not [p for p in context_dir.rglob("*") if p.is_file() and p.name in {"a-seul.md", "b-seul.md"}]
    # Chaque cerveau a reçu le dossier des Boards et le serveur jarvis-workspace.
    for spawn in bench.stub.spawns():
        argv = spawn["argv"]
        start = argv.index("--add-dir") + 1                     # `--add-dir` prend plusieurs dossiers
        grants = argv[start:next((i for i in range(start, len(argv)) if argv[i].startswith("--")), len(argv))]
        assert any(Path(g).resolve() == bench.boards_dir for g in grants), grants
        configs = [argv[i + 1] for i, x in enumerate(argv) if x == "--mcp-config"]
        assert any(Path(c).name == "workspace-mcp.json" for c in configs), configs
    bench.assert_one_speech_authority()


# ------------------------------------------------------------------ (d) inspection historique non activante


async def _history(bench: WorkspaceBench) -> SimpleNamespace:
    """Une Session close qui a visité Borée (mémoire, Artifact lié), un Board archivé, puis Session neuve sur A."""

    core = bench.core
    w = SimpleNamespace(a=DEFAULT_BOARD_ID)
    w.old = (await bench.ok("POST", "/api/boards", json={"title": "Ancien Borée", "board_kind": "meeting"}))[
        "board"]["board_id"]
    w.arch = (await bench.ok("POST", "/api/boards", json={"title": "Archive"}))["board"]["board_id"]
    await bench.ok("POST", ws(w.arch, "/memory/write"), json={"path": "vieux.md", "content": "archive ancienne\n"})
    await bench.ok("POST", "/api/boards/switch", json={"board_id": w.old})
    await bench.turn("travail sur Borée")
    context = (await core.sessions.current_context()).context
    w.closed_session = context.jarvis_session_id
    art = await core.artifacts.record_text(
        artifact_id="jart_" + "d" * 32, kind=ArtifactKind.TRANSCRIPT, source="e2e", text="réunion Borée",
        jarvis_session_id=w.closed_session, context_id=context.context_id, started_at=None, ended_at=None,
        duration_ms=None, metadata={}, origins=())
    w.art = art.artifact_id
    await bench.ok("POST", ws(w.old, "/memory/write"), json={"path": "summary.md", "content": "# Borée\nORION-42\n"})
    await bench.ok("POST", ws(w.old, "/memory/write"), json={"path": "notes/decisions.md",
                                                             "content": "report au 15 octobre\n"})
    await bench.ok("POST", "/api/boards/switch", json={"board_id": w.a})
    await bench.ok("POST", f"/api/boards/{w.arch}/archive")
    fresh = await bench.ok("POST", "/api/sessions/new", json={"expected_session_id": w.closed_session})
    w.open_session = fresh["session"]["jarvis_session_id"]
    await bench.turn("tour courant sur A")
    return w


def _read_routes(w: SimpleNamespace) -> list[tuple[str, dict]]:
    """Chaque route de lecture servie au gestionnaire et au navigateur rapide, Boards ancien et archivé compris."""

    routes = [("/api/boards", {}), ("/api/boards", {"include_archived": "true"}), ("/api/boards/active", {}),
              ("/api/sessions/current", {}), ("/api/sessions", {"limit": "10"}),
              ("/api/workspace/sessions", {}), ("/api/workspace/sessions", {"limit": "1"})]
    for session in (w.closed_session, w.open_session):
        routes += [(f"/api/workspace/sessions/{session}", {}),
                   (f"/api/workspace/sessions/{session}/activity", {"limit": "100"}),
                   ("/api/workspace/relations", {"session_id": session}),
                   ("/api/workspace/artifacts", {"session_id": session})]
    for board in (w.old, w.arch, w.a):
        routes += [(f"/api/boards/{board}", {}), (ws(board), {}),
                   ("/api/workspace/relations", {"board_id": board}),
                   ("/api/workspace/artifacts", {"board_id": board}),
                   (ws(board, "/memory/tree"), {"depth": "4"}),
                   (ws(board, "/memory/search"), {"q": "ORION"})]
    routes += [(ws(w.old, "/memory/read"), {"path": "summary.md"}),
               (ws(w.old, "/memory/read"), {"path": "notes/decisions.md", "max_bytes": "8"}),
               (ws(w.old, "/memory/stat"), {"path": "notes"}),
               (ws(w.arch, "/memory/read"), {"path": "vieux.md"}),
               (f"/api/workspace/artifacts/{w.art}/relations", {}), (f"/api/artifacts/{w.art}", {})]
    return routes


def _read_tools(w: SimpleNamespace) -> list[tuple[str, dict]]:
    tools = [("board_list", {"include_archived": True}), ("board_get_active", {}), ("session_current", {}),
             ("session_list", {}), ("session_get", {"session_id": w.closed_session}),
             ("session_get", {"session_id": w.open_session})]
    for board in (w.old, w.arch):
        tools += [("board_get", {"board_id": board}), ("board_inspect", {"board_id": board}),
                  ("board_memory_tree", {"board_id": board, "depth": 4}),
                  ("board_memory_search", {"board_id": board, "query": "ORION"}),
                  ("board_artifacts", {"board_id": board})]
    tools += [("board_memory_read", {"board_id": w.old, "path": "notes/decisions.md"}),
              ("board_memory_read", {"board_id": w.arch, "path": "vieux.md"})]
    return tools


async def test_inspecting_old_and_archived_boards_through_every_read_route_and_tool_activates_nothing(bench):
    await up(bench)
    w = await _history(bench)
    before = await quiet_snapshot(bench)
    assert before["rows"] and before["authority"]["board_id"] == w.a

    for path, params in _read_routes(w):
        status, body = await bench.call("GET", path, params=params)
        assert status == 200, (path, params, status, body)
    async with Brain(bench) as brain:
        results = {}
        for name, arguments in _read_tools(w):
            results.setdefault(name, []).append(await brain.call(name, arguments))

    same(before, await foreground_snapshot(bench), "a read changed the foreground, a row, a file or a brain")
    # Ce qui a été lu est juste : l'historique n'est pas vide, il est seulement non activé.
    inspected = results["board_inspect"][0]
    assert inspected["active"] is False and inspected["memory"]["summary_md"] is True
    assert w.closed_session in {s["jarvis_session_id"] for s in inspected["sessions"]}
    assert results["board_memory_read"][0]["text"] == "report au 15 octobre\n"
    assert results["board_memory_search"][0]["matches"][0]["path"] == "summary.md"
    assert [i["artifact_id"] for i in results["board_artifacts"][0]["items"]] == [w.art]
    assert results["board_inspect"][1]["status"] == "archived"
    assert results["board_get_active"][0]["board_id"] == w.a
    assert (await bench.ok("GET", f"/api/boards/{w.old}"))["board"]["board_id"] == w.old
    bench.assert_one_speech_authority()


# ------------------------------------------------------------------ (e) parité écran / MCP


async def test_the_screen_routes_and_the_brain_tools_give_the_same_results_and_the_same_codes(bench):
    await up(bench)
    w = await _history(bench)
    a, old, arch = w.a, w.old, w.arch
    big = "é" * 140_000                          # 280 000 octets > 256 Kio, sous la borne de caractères du schéma
    binary = bench.memory(a) / "image.bin"
    await bench.ok("POST", ws(a, "/memory/write"), json={"path": "seed.md", "content": "graine\n"})
    binary.write_bytes(b"\x89PNG\x00\x01")
    async with Brain(bench) as brain:
        # Succès : même texte, même empreinte, même arbre, même recherche, même inspection.
        screen = await bench.ok("GET", ws(old, "/memory/read"), params={"path": "summary.md"})
        tool = await brain.call("board_memory_read", {"board_id": old, "path": "summary.md"})
        assert (tool["text"], tool["sha256"], tool["size"], tool["eof"]) == (
            screen["text"], screen["sha256"], screen["size"], screen["eof"])
        screen_tree = await bench.ok("GET", ws(old, "/memory/tree"), params={"depth": "3"})
        tool_tree = await brain.call("board_memory_tree", {"board_id": old, "depth": 3})
        assert [(e["path"], e["kind"], e["size"]) for e in tool_tree["entries"]] == [
            (e["path"], e["kind"], e["size"]) for e in screen_tree["entries"]]
        screen_found = await bench.ok("GET", ws(old, "/memory/search"), params={"q": "octobre"})
        tool_found = await brain.call("board_memory_search", {"board_id": old, "query": "octobre"})
        assert [(m["path"], m["line"]) for m in tool_found["matches"]] == [
            (m["path"], m["line"]) for m in screen_found["matches"]]
        screen_board = await bench.ok("GET", ws(old))
        tool_board = await brain.call("board_inspect", {"board_id": old})
        assert (tool_board["board_kind"], tool_board["status"], tool_board["memory"]["files"],
                tool_board["linked_artifacts"]) == (screen_board["board"]["board_kind"], screen_board["board"]["status"],
                                                    screen_board["memory"]["files"],
                                                    screen_board["artifacts"]["linked"])
        screen_listed = await bench.ok("GET", "/api/workspace/artifacts", params={"board_id": old})
        tool_listed = await brain.call("board_artifacts", {"board_id": old})
        assert [i["artifact_id"] for i in tool_listed["items"]] == [
            i["artifact_id"] for i in screen_listed["artifacts"]]

        # Mutations : même contenu -> même empreinte et même taille ; même ledger, seule l'origine diffère.
        by_screen = await bench.ok("POST", ws(a, "/memory/write"), json={"path": "p/ecran.md", "content": "même\n"})
        by_tool = await brain.call("board_memory_write", {"board_id": a, "path": "p/outil.md", "content": "même\n"})
        assert (by_tool["created"], by_tool["sha256"], by_tool["bytes"]) == (
            by_screen["created"], by_screen["sha256"], by_screen["bytes"])
        moved_screen = await bench.ok("POST", ws(a, "/memory/move"), json={"from": "p/ecran.md", "to": "q/ecran.md"})
        moved_tool = await brain.call("board_memory_move", {"board_id": a, "source": "p/outil.md",
                                                            "target": "q/outil.md"})
        assert moved_tool["kind"] == moved_screen["entry"]["kind"] == "file"
        gone_screen = await bench.ok("POST", ws(a, "/memory/delete"), json={"path": "q/ecran.md"})
        gone_tool = await brain.call("board_memory_delete", {"board_id": a, "path": "q/outil.md"})
        assert gone_tool["removed"] == gone_screen["removed"] == 1
        rows = (await bench.ok("GET", f"/api/workspace/sessions/{w.open_session}/activity",
                               params={"limit": "100"}))["events"]
        mine = [(e["kind"], e["data"]["origin"]) for e in rows if e["kind"].startswith("board.memory.")
                and any(str(e["data"].get(k, "")).endswith(("ecran.md", "outil.md")) for k in ("path", "from"))]
        assert mine == [("board.memory.written", "user"), ("board.memory.written", "brain"),
                        ("board.memory.moved", "user"), ("board.memory.moved", "brain"),
                        ("board.memory.deleted", "user"), ("board.memory.deleted", "brain")]
        link_screen = await bench.ok("POST", ws(a, f"/artifacts/{w.art}"), json={})
        assert link_screen["created"] is True
        link_tool = await brain.call("board_artifact_link", {"board_id": a, "artifact_id": w.art})
        assert link_tool["changed"] is False, "the screen's link is the tool's link (one table)"

        # Refus : chaque cas, les deux chemins, le même code stable.
        sha = by_screen["sha256"]
        cases = [
            ("POST", ws(a, "/memory/write"), {"json": {"path": "seed.md", "content": "x"}},
             "board_memory_write", {"board_id": a, "path": "seed.md", "content": "x"}, "memory_exists"),
            ("POST", ws(a, "/memory/write"), {"json": {"path": "seed.md", "content": "x", "mode": "replace",
                                                       "expected_sha256": sha}},
             "board_memory_write", {"board_id": a, "path": "seed.md", "content": "x", "mode": "replace",
                                    "expected_sha256": sha}, "memory_conflict"),
            ("POST", ws(a, "/memory/write"), {"json": {"path": "gros.md", "content": big}},
             "board_memory_write", {"board_id": a, "path": "gros.md", "content": big}, "memory_too_large"),
            ("GET", ws(a, "/memory/read"), {"params": {"path": "absent.md"}},
             "board_memory_read", {"board_id": a, "path": "absent.md"}, "memory_not_found"),
            ("GET", ws(a, "/memory/read"), {"params": {"path": "image.bin"}},
             "board_memory_read", {"board_id": a, "path": "image.bin"}, "memory_not_text"),
            ("POST", ws(a, "/memory/move"), {"json": {"from": "absent.md", "to": "x.md"}},
             "board_memory_move", {"board_id": a, "source": "absent.md", "target": "x.md"}, "memory_not_found"),
            ("POST", ws(a, "/memory/delete"), {"json": {"path": "con.md"}},
             "board_memory_delete", {"board_id": a, "path": "con.md"}, "memory_path_invalid"),
            ("POST", ws(arch, "/memory/write"), {"json": {"path": "n.md", "content": "x"}},
             "board_memory_write", {"board_id": arch, "path": "n.md", "content": "x"}, "board_archived"),
            ("GET", ws("board_" + "0" * 32), {},
             "board_inspect", {"board_id": "board_" + "0" * 32}, "board_not_found"),
            ("GET", ws("board_" + "0" * 32, "/memory/tree"), {},
             "board_memory_tree", {"board_id": "board_" + "0" * 32}, "board_not_found"),
            ("GET", "/api/workspace/sessions/jsess_" + "0" * 32, {},
             "session_get", {"session_id": "jsess_" + "0" * 32}, "session_not_found"),
            ("POST", ws(a, "/artifacts/jart_" + "f" * 32), {"json": {}},
             "board_artifact_link", {"board_id": a, "artifact_id": "jart_" + "f" * 32}, "artifact_not_found"),
            ("POST", "/api/boards/switch", {"json": {"board_id": arch}},
             "board_switch", {"board_id": arch}, "board_archived"),
            ("POST", f"/api/boards/{a}/archive", {},
             "board_archive", {"board_id": a}, "board_is_active"),
        ]
        snapshot = await quiet_snapshot(bench)
        for method, path, kwargs, tool_name, arguments, code in cases:
            assert await http_code(bench, method, path, **kwargs) == code, (path, code)
            assert await brain.code(tool_name, arguments) == code, (tool_name, code)
        same(snapshot, await foreground_snapshot(bench), "a refusal changed something")
    bench.assert_one_speech_authority()


# ------------------------------------------------------------------ (f) évasions de chemin


def _junction(link: Path, target: Path) -> None:
    """Vraie jonction NTFS ; ailleurs, un lien symbolique de dossier (même règle : jamais suivi)."""

    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        import _winapi

        try:
            _winapi.CreateJunction(str(target), str(link))
        except OSError as exc:  # pragma: no cover - dépend de l'hôte
            pytest.skip(f"junction creation refused by the host: {exc}")
    else:  # pragma: no cover - CI POSIX
        os.symlink(target, link, target_is_directory=True)


ESCAPES = ["../secret.txt", "notes/../../secret.txt", "..\\secret.txt", "C:/Windows/win.ini", "C:secret.txt",
           "/etc/passwd", "\\\\server\\share\\x.md", "notes/door/secret.txt", "notes/door"]


async def test_path_escapes_are_refused_end_to_end_by_the_screen_and_the_brain_including_a_real_junction(bench):
    await up(bench)
    a = DEFAULT_BOARD_ID
    outside = bench.tmp / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("needle secret", encoding="utf-8")
    sibling = bench.boards_dir / "board_voisin" / "memory"
    sibling.mkdir(parents=True)
    (sibling / "autre.md").write_text("autre Board", encoding="utf-8")
    await bench.ok("POST", ws(a, "/memory/write"), json={"path": "notes/ok.md", "content": "needle ici\n"})
    _junction(bench.memory(a) / "notes" / "door", outside)
    snapshot_outside = sorted((p.name, p.read_bytes()) for p in outside.iterdir())
    await bench.turn("un tour, pour que le cerveau de A soit lancé et rapporté")
    before = await quiet_snapshot(bench)

    codes: dict[tuple[str, str, str], str] = {}
    async with Brain(bench) as brain:
        for path in ESCAPES + ["../board_voisin/memory/autre.md"]:
            http = {
                "read": await http_code(bench, "GET", ws(a, "/memory/read"), params={"path": path}),
                "tree": await http_code(bench, "GET", ws(a, "/memory/tree"), params={"path": path}),
                "write": await http_code(bench, "POST", ws(a, "/memory/write"),
                                         json={"path": path, "content": "planted", "mode": "replace"}),
                "move_to": await http_code(bench, "POST", ws(a, "/memory/move"),
                                           json={"from": "notes/ok.md", "to": path}),
                "move_from": await http_code(bench, "POST", ws(a, "/memory/move"),
                                             json={"from": path, "to": "pris.md"}),
            }
            mcp = {
                "read": await brain.code("board_memory_read", {"board_id": a, "path": path}),
                "tree": await brain.code("board_memory_tree", {"board_id": a, "path": path}),
                "write": await brain.code("board_memory_write", {"board_id": a, "path": path,
                                                                 "content": "planted", "mode": "replace"}),
                "move_to": await brain.code("board_memory_move", {"board_id": a, "source": "notes/ok.md",
                                                                  "target": path}),
                "move_from": await brain.code("board_memory_move", {"board_id": a, "source": path,
                                                                    "target": "pris.md"}),
            }
            assert mcp == http, (path, http, mcp)
            for op, code in http.items():
                codes[(path, op, "both")] = code
        # Dans la recherche, la jonction est listée comme lien et jamais parcourue.
        found = await brain.call("board_memory_search", {"board_id": a, "query": "needle"})
        assert [m["path"] for m in found["matches"]] == ["notes/ok.md"]
        tree = await brain.call("board_memory_tree", {"board_id": a, "depth": 4})
        assert not [e for e in tree["entries"] if e["path"].startswith("notes/door/")]
        # Le paramètre board_id n'est pas un chemin non plus.
        assert await brain.code("board_memory_read", {"board_id": "board_voisin", "path": "autre.md"}) \
            == await http_code(bench, "GET", ws("board_voisin", "/memory/read"), params={"path": "autre.md"}) \
            == "board_not_found"
    status, _ = await bench.call("GET", "/api/workspace/boards/..%2F..%2Fstate/memory/read",
                                 params={"path": "jarvis.sqlite3"})
    assert status in (400, 404)

    assert {code for code in codes.values()} <= {"memory_path_escape", "memory_path_invalid"}, codes
    assert all(code == "memory_path_escape" for (path, _op, _), code in codes.items()
               if path.startswith(("..", "notes/..", "notes/door"))), codes
    assert sorted((p.name, p.read_bytes()) for p in outside.iterdir()) == snapshot_outside, "outside touched"
    assert (sibling / "autre.md").read_text(encoding="utf-8") == "autre Board"
    assert (bench.memory(a) / "notes" / "ok.md").read_text(encoding="utf-8") == "needle ici\n"
    same(before, await foreground_snapshot(bench), "a refused escape changed something")
    # Le Board reste utilisable et sa jonction se retire sans toucher la cible.
    removed = await bench.ok("POST", ws(a, "/memory/delete"), json={"path": "notes", "recursive": True})
    assert removed["removed"] == 3
    assert sorted((p.name, p.read_bytes()) for p in outside.iterdir()) == snapshot_outside
    bench.assert_one_speech_authority()


# ------------------------------------------------------------------ (g) Board archivé


async def test_an_archived_board_is_readable_everywhere_and_writable_nowhere(bench):
    await up(bench)
    w = await _history(bench)
    arch = w.arch
    await bench.ok("GET", ws(arch))                                  # lisible
    before_files = sorted(p.relative_to(bench.memory(arch)).as_posix() for p in bench.memory(arch).rglob("*"))
    other_session_art = w.art
    snapshot = await quiet_snapshot(bench)

    http_writes = [
        ("POST", ws(arch, "/memory/write"), {"json": {"path": "n.md", "content": "x"}}),
        ("POST", ws(arch, "/memory/write"), {"json": {"path": "vieux.md", "content": "x", "mode": "append"}}),
        ("POST", ws(arch, "/memory/mkdir"), {"json": {"path": "dossier"}}),
        ("POST", ws(arch, "/memory/move"), {"json": {"from": "vieux.md", "to": "neuf.md"}}),
        ("POST", ws(arch, "/memory/delete"), {"json": {"path": "vieux.md"}}),
        ("POST", ws(arch, f"/artifacts/{other_session_art}"), {"json": {}}),
        ("DELETE", ws(arch, f"/artifacts/{other_session_art}"), {}),
        ("PATCH", f"/api/boards/{arch}", {"json": {"title": "renommé"}}),
        ("PATCH", f"/api/boards/{arch}", {"json": {"board_kind": "meeting"}}),
        ("POST", "/api/boards/switch", {"json": {"board_id": arch}}),
    ]
    for method, path, kwargs in http_writes:
        assert await http_code(bench, method, path, **kwargs) == "board_archived", (method, path, kwargs)

    async with Brain(bench) as brain:
        tool_writes = [
            ("board_memory_write", {"board_id": arch, "path": "n.md", "content": "x"}),
            ("board_memory_write", {"board_id": arch, "path": "vieux.md", "content": "x", "mode": "append"}),
            ("board_memory_move", {"board_id": arch, "source": "vieux.md", "target": "neuf.md"}),
            ("board_memory_delete", {"board_id": arch, "path": "vieux.md"}),
            ("board_artifact_link", {"board_id": arch, "artifact_id": other_session_art}),
            ("board_artifact_link", {"board_id": arch, "artifact_id": other_session_art, "linked": False}),
            ("board_update", {"board_id": arch, "title": "renommé"}),
            ("board_update", {"board_id": arch, "board_kind": "meeting"}),
            ("board_switch", {"board_id": arch}),
        ]
        for name, arguments in tool_writes:
            assert await brain.code(name, arguments) == "board_archived", (name, arguments)
        # Lectures : par l'outil comme par l'écran.
        assert (await brain.call("board_memory_read", {"board_id": arch, "path": "vieux.md"}))["text"] == \
            "archive ancienne\n"
        assert (await brain.call("board_inspect", {"board_id": arch}))["status"] == "archived"
        assert (await brain.call("board_memory_search", {"board_id": arch, "query": "ancienne"}))["matches"]
        assert (await brain.call("board_artifacts", {"board_id": arch}))["items"] == []
    assert (await bench.ok("GET", ws(arch, "/memory/read"), params={"path": "vieux.md"}))["text"] == \
        "archive ancienne\n"
    assert (await bench.ok("GET", ws(arch, "/memory/tree")))["entries"]
    assert (await bench.ok("GET", f"/api/boards/{arch}"))["board"]["title"] == "Archive"

    after_files = sorted(p.relative_to(bench.memory(arch)).as_posix() for p in bench.memory(arch).rglob("*"))
    assert after_files == before_files
    same(snapshot, await foreground_snapshot(bench), "a refused write on an archived Board changed something")
    rows = (await bench.ok("GET", f"/api/workspace/sessions/{w.open_session}/activity",
                           params={"limit": "100"}))["events"]
    assert not [e for e in rows if e["kind"].startswith("board.") and e["data"].get("board_id") == arch]
    bench.assert_one_speech_authority()


def test_the_v7_fixture_is_text_made_by_the_v7_code():
    """La base v7 n'est jamais versionnée : seul son dump SQL l'est, avec son origine."""

    text = FIXTURE_V7.read_text(encoding="utf-8")
    assert text.startswith("-- jarvis.sqlite3 au schéma 7, fabriqué par le code v7 (origin/main 467232f)")
    assert "INSERT INTO \"schema_version\" VALUES(7);" in text
    assert "board_artifact_links" not in text and "board_kind" not in text

"""Inspection du workspace : service, routes Core et relais du Control Center (board-memory-workspace-inspector, Slice 04).

Contrat : `docs/boards.md` › *Workspace inspection API*. Vraie chaîne
(`tests/fakes/capture_stack.py` : Core sur SQLite et une racine de données
réelles, `LocalProtocolServer`, `ControlCenter`), données construites par les
propriétaires canoniques : deux Sessions (une close), quatre Boards (un
archivé), liaisons, Contexts, Artifacts liés (automatique et explicite) avec
provenance, fichiers de mémoire. Ce qui doit tenir :

- chaque lecture est **sans effet de bord** : `active_board_id`, liaisons,
  autorité de parole, nombre de lignes de **chaque** table de `jarvis.sqlite3`
  et listing du dossier `boards/` identiques avant et après ;
- relations exactes pour l'état courant et historique ; Board archivé lisible ;
- bornes refusées (`invalid_request`), curseurs opaques, codes stables ;
- une Session ouverte dont le Board actif manque est dite (`problems`), jamais un 500.
"""

from __future__ import annotations

from datetime import timedelta
import json
import os
from pathlib import Path
import threading

import pytest

from jarvis.adapters.board_memory_store import FileBoardMemoryStore
from jarvis.adapters.sqlite_board_artifact_links import SQLiteBoardArtifactLinks
from jarvis.domain.artifacts import ArtifactKind, ArtifactRelationKind
from jarvis.domain.board_memory import BoardMemoryPath
from jarvis.domain.v2 import utc_now
from jarvis.ports.board_memory import WriteMode
from tests.fakes.capture_stack import CaptureStack
from tests.unit.test_capture_api_protocol import assert_clean, core

# ------------------------------------------------------------------ monde


class World:
    """Ids du monde construit par `build`."""

    closed_session: str
    open_session: str
    board_a: str
    board_b: str
    board_archived: str
    first_context: str
    second_context: str
    art_audio: str
    art_derived: str
    art_closed: str


async def build(stack: CaptureStack) -> World:
    c = stack.core
    w = World()
    w.board_a = (await c.boards.create({"title": "Projet A", "board_kind": "meeting"})).board_id
    w.board_b = (await c.boards.create({"title": "Projet B"})).board_id
    w.board_archived = (await c.boards.create({"title": "Ancien"})).board_id
    await c.boards.archive(w.board_archived)
    first = await c.sessions.current_context()
    w.first_context = first.context.context_id
    w.closed_session = first.context.jarvis_session_id
    await c.boards.switch(w.board_a)
    audio = await c.artifacts.record_text(
        artifact_id="jart_" + "a" * 32, kind=ArtifactKind.TRANSCRIPT, source="test", text="bonjour réunion",
        jarvis_session_id=w.closed_session, context_id=w.first_context, started_at=None, ended_at=None,
        duration_ms=None, metadata={}, origins=())
    w.art_audio = audio.artifact_id
    second = await c.sessions.create_context(title="Revue")
    w.second_context = second.context.context_id
    derived = await c.artifacts.record_text(
        artifact_id="jart_" + "b" * 32, kind=ArtifactKind.DERIVED, source="test", text="résumé",
        jarvis_session_id=w.closed_session, context_id=w.second_context, started_at=None, ended_at=None,
        duration_ms=None, metadata={}, origins=((ArtifactRelationKind.DERIVED_FROM, w.art_audio),))
    w.art_derived = derived.artifact_id
    await SQLiteBoardArtifactLinks(c.state).link(w.board_b, w.art_audio, now=utc_now())
    _closed, view = await c.sessions.start_new_session()
    w.open_session = view.session.jarvis_session_id
    await c.boards.switch(w.board_b)
    late = await c.artifacts.record_text(
        artifact_id="jart_" + "c" * 32, kind=ArtifactKind.DESCRIPTION, source="test", text="note",
        jarvis_session_id=w.open_session, context_id=None, started_at=None, ended_at=None,
        duration_ms=None, metadata={}, origins=())
    w.art_closed = late.artifact_id
    store = FileBoardMemoryStore(stack.data_root)
    store.write(w.board_a, BoardMemoryPath("summary.md"), "# A\nDécisions du projet\n", mode=WriteMode.CREATE)
    store.write(w.board_a, BoardMemoryPath("notes/plan.md"), "étape 1\nétape 2 décisions\n", mode=WriteMode.CREATE)
    store.write(w.board_archived, BoardMemoryPath("vieux.md"), "archive\n", mode=WriteMode.CREATE)
    binary = stack.data_root / "boards" / w.board_a / "memory" / "image.bin"
    binary.write_bytes(b"\x89PNG\x00\x01")
    return w


# ------------------------------------------------------------------ photographie


async def snapshot(stack: CaptureStack) -> dict:
    """Tout ce qu'une lecture ne doit pas changer."""

    def read(conn):
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        counts = {name: conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0] for name in tables}
        sessions = conn.execute("SELECT jarvis_session_id, status, active_board_id, data FROM jarvis_sessions "
                                "ORDER BY jarvis_session_id").fetchall()
        bindings = conn.execute("SELECT jarvis_session_id, board_id, lifecycle, status, data FROM "
                                "board_conversation_bindings ORDER BY jarvis_session_id, board_id").fetchall()
        boards = conn.execute("SELECT board_id, status, updated_at, data FROM work_boards ORDER BY board_id").fetchall()
        return counts, [tuple(r) for r in sessions], [tuple(r) for r in bindings], [tuple(r) for r in boards]

    counts, sessions, bindings, boards = await stack.core.state.run_serialized(read)
    listing = []
    root = stack.data_root / "boards"
    if root.exists():
        for folder, dirs, files in os.walk(root):
            for name in sorted(dirs + files):
                info = os.lstat(Path(folder) / name)
                listing.append((str(Path(folder, name).relative_to(stack.data_root)), info.st_size, info.st_mtime_ns))
    authority = stack.core.speech_authority.binding
    return {"counts": counts, "sessions": sessions, "bindings": bindings, "boards": boards,
            "memory": sorted(listing), "authority": None if authority is None else authority.to_payload(),
            "mode": stack.core.interaction_mode.snapshot()}


def read_paths(w: World) -> list[str]:
    a, b, arch = w.board_a, w.board_b, w.board_archived
    return [
        "/v1/workspace/sessions", "/v1/workspace/sessions?limit=1",
        f"/v1/workspace/sessions/{w.closed_session}", f"/v1/workspace/sessions/{w.open_session}",
        f"/v1/workspace/sessions/{w.closed_session}/activity", f"/v1/workspace/sessions/{w.open_session}/activity",
        f"/v1/workspace/boards/{a}", f"/v1/workspace/boards/{b}", f"/v1/workspace/boards/{arch}",
        "/v1/workspace/boards/default",
        f"/v1/workspace/relations?session_id={w.closed_session}", f"/v1/workspace/relations?board_id={a}",
        f"/v1/workspace/relations?board_id={arch}",
        f"/v1/workspace/artifacts?board_id={a}", f"/v1/workspace/artifacts?board_id={b}",
        f"/v1/workspace/artifacts?session_id={w.closed_session}", f"/v1/workspace/artifacts?context_id={w.first_context}",
        f"/v1/workspace/artifacts/{w.art_audio}/relations",
        f"/v1/workspace/boards/{a}/memory/tree?depth=3", f"/v1/workspace/boards/{b}/memory/tree",
        f"/v1/workspace/boards/{arch}/memory/tree", "/v1/workspace/boards/default/memory/tree",
        f"/v1/workspace/boards/{a}/memory/stat?path=notes/plan.md",
        f"/v1/workspace/boards/{a}/memory/read?path=summary.md",
        f"/v1/workspace/boards/{arch}/memory/read?path=vieux.md",
        f"/v1/workspace/boards/{a}/memory/search?q=d%C3%A9cisions",
        f"/v1/workspace/boards/{b}/memory/search?q=x",
        # Refus : pas d'effet de bord non plus.
        f"/v1/workspace/boards/{b}/memory/read?path=absent.md",
        f"/v1/workspace/boards/{a}/memory/read?path=image.bin",
        "/v1/workspace/boards/board_nope", "/v1/workspace/sessions/jsess_nope",
    ]


# ------------------------------------------------------------------ sans effet de bord


async def test_every_read_route_is_side_effect_free(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        before = await snapshot(stack)
        assert before["sessions"] and before["authority"]["board_id"] == w.board_b
        assert not (stack.data_root / "boards" / w.board_b).exists(), "board B never had memory"
        for path in read_paths(w):
            status, body, raw, _ = await core(stack, "GET", path)
            assert status < 500, (path, body)
            assert_clean(stack, raw)
            assert await snapshot(stack) == before, f"{path} changed state"
            relayed, cc_body, _ = await stack.call("GET", path.replace("/v1/", "/api/", 1))
            assert (relayed, cc_body) == (status, body), path
            assert await snapshot(stack) == before, f"relayed {path} changed state"
        assert not (stack.data_root / "boards" / w.board_b).exists(), "a read created board B's memory"


# ------------------------------------------------------------------ Sessions


async def test_sessions_history_includes_closed_and_pages_with_opaque_cursors(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        _, page1, _, _ = await core(stack, "GET", "/v1/workspace/sessions", params={"limit": "1"})
        assert [s["jarvis_session_id"] for s in page1["sessions"]] == [w.open_session]
        assert page1["sessions"][0]["open"] is True and page1["next_cursor"]
        assert w.open_session not in page1["next_cursor"], "cursor is opaque"
        _, page2, _, _ = await core(stack, "GET", "/v1/workspace/sessions",
                                    params={"limit": "1", "cursor": page1["next_cursor"]})
        assert [s["jarvis_session_id"] for s in page2["sessions"]] == [w.closed_session]
        assert page2["sessions"][0]["status"] == "closed" and page2["next_cursor"] is None


async def test_closed_session_shows_its_boards_bindings_and_contexts(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        status, body, _, _ = await core(stack, "GET", f"/v1/workspace/sessions/{w.closed_session}")
        assert status == 200, body
        assert body["open"] is False and "speech_authority" not in body and body["problems"] == []
        boards = {b["board_id"]: b for b in body["boards"]}
        assert set(boards) == {"default", w.board_a}
        assert boards[w.board_a]["active"] is True and boards[w.board_a]["board_kind"] == "meeting"
        binding = boards[w.board_a]["binding"]
        assert binding["status"] == "closed" and {"conversation_id", "agent_cli", "agent_session_id",
                                                   "lifecycle"} <= set(binding)
        contexts = body["contexts"]
        assert [c["context_id"] for c in contexts["items"]] == [w.first_context, w.second_context]
        assert contexts["items"][1]["title"] == "Revue" and contexts["total"] == 2
        assert contexts["items"][0]["workspace_ref"] == f"sessions/{w.closed_session}/contexts/{w.first_context}"


async def test_open_session_shows_speech_authority_read_only(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        _, body, _, _ = await core(stack, "GET", f"/v1/workspace/sessions/{w.open_session}")
        assert body["open"] is True and body["speech_authority"]["board_id"] == w.board_b
        foreground = [b for b in body["boards"] if b["binding"] and b["binding"]["lifecycle"] == "foreground"]
        assert [b["board_id"] for b in foreground] == [w.board_b]


async def test_activity_of_a_closed_session_is_readable(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        _, body, _, _ = await core(stack, "GET", f"/v1/workspace/sessions/{w.closed_session}/activity",
                                   params={"limit": "2"})
        kinds = [e["kind"] for e in body["events"]]
        assert len(kinds) == 2 and body["next_cursor"]
        seen = list(kinds)
        cursor = body["next_cursor"]
        while cursor:
            _, page, _, _ = await core(stack, "GET", f"/v1/workspace/sessions/{w.closed_session}/activity",
                                       params={"limit": "100", "cursor": cursor})
            seen += [e["kind"] for e in page["events"]]
            cursor = page["next_cursor"]
        assert "session.closed" in seen and "artifact.created" in seen
        _, only, _, _ = await core(stack, "GET", f"/v1/workspace/sessions/{w.closed_session}/activity",
                                   params={"kind": "session.closed"})
        assert [e["kind"] for e in only["events"]] == ["session.closed"]
        # La route historique ne sert toujours que la Session ouverte.
        _, current, _, _ = await core(stack, "GET", "/v1/activity")
        assert current["jarvis_session_id"] == w.open_session


# ------------------------------------------------------------------ Boards


async def test_board_inspect_shows_memory_links_bindings_and_legacy_refs(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        await stack.core.boards.update(w.board_a, {"artifact_refs": ["legacy-1"]})
        _, body, _, _ = await core(stack, "GET", f"/v1/workspace/boards/{w.board_a}")
        assert body["board"]["board_kind"] == "meeting" and body["active"] is False
        memory = body["memory"]
        assert memory["locator"] == f"boards/{w.board_a}/memory" and memory["exists"] is True
        assert (memory["files"], memory["directories"]) == (3, 1) and memory["truncated"] is False
        assert memory["summary"]["present"] is True and memory["summary"]["path"] == "summary.md"
        assert body["artifacts"]["linked"] == 2, "audio + derived linked automatically to A"
        assert body["legacy_artifact_refs"] == {"items": ["legacy-1"], "legacy": True,
                                                "note": body["legacy_artifact_refs"]["note"]}
        sessions = {s["jarvis_session_id"]: s for s in body["sessions"]["items"]}
        assert set(sessions) == {w.closed_session, w.open_session}
        assert sessions[w.closed_session]["session_status"] == "closed"
        assert sessions[w.open_session]["lifecycle"] != "foreground"


async def test_archived_board_is_inspectable_and_its_memory_readable(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        _, body, _, _ = await core(stack, "GET", f"/v1/workspace/boards/{w.board_archived}")
        assert body["board"]["status"] == "archived" and body["memory"]["files"] == 1
        assert body["memory"]["summary"] == {"present": False}
        _, read, _, _ = await core(stack, "GET", f"/v1/workspace/boards/{w.board_archived}/memory/read",
                                   params={"path": "vieux.md"})
        assert read["text"] == "archive\n" and read["eof"] is True and len(read["sha256"]) == 64


async def test_board_without_memory_reports_it_absent_and_never_creates_it(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        _, body, _, _ = await core(stack, "GET", f"/v1/workspace/boards/{w.board_b}")
        assert body["memory"]["exists"] is False and body["memory"]["entries"] == 0
        _, tree, _, _ = await core(stack, "GET", f"/v1/workspace/boards/{w.board_b}/memory/tree")
        assert tree["exists"] is False and tree["entries"] == []
        status, missing, _, _ = await core(stack, "GET", f"/v1/workspace/boards/{w.board_b}/memory/stat",
                                           params={"path": "a.md"})
        assert (status, missing["error"]["code"]) == (404, "memory_not_found")
        assert not (stack.data_root / "boards" / w.board_b).exists()


async def test_relations_of_a_board_cross_sessions(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        _, body, _, _ = await core(stack, "GET", "/v1/workspace/relations", params={"board_id": w.board_b})
        assert body["active"] is True and body["linked_artifacts"] == 2, "explicit audio + description"
        [only] = body["sessions"]["items"]
        assert only["jarvis_session_id"] == w.open_session and only["active_in_session"] is True
        _, session, _, _ = await core(stack, "GET", "/v1/workspace/relations", params={"session_id": w.open_session})
        assert {b["board_id"] for b in session["boards"]} == {w.board_a, w.board_b}


# ------------------------------------------------------------------ Artifacts


async def test_artifacts_by_board_session_context_with_filters_and_pages(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)

        async def ids(**params):
            _, body, _, _ = await core(stack, "GET", "/v1/workspace/artifacts", params=params)
            return [a["artifact_id"] for a in body["artifacts"]], body

        assert set((await ids(board_id=w.board_a))[0]) == {w.art_audio, w.art_derived}
        assert set((await ids(board_id=w.board_b))[0]) == {w.art_audio, w.art_closed}
        assert (await ids(board_id=w.board_archived))[0] == []
        assert set((await ids(session_id=w.closed_session))[0]) == {w.art_audio, w.art_derived}
        assert (await ids(context_id=w.second_context))[0] == [w.art_derived]
        assert (await ids(board_id=w.board_a, kind="derived"))[0] == [w.art_derived]
        future = (utc_now() + timedelta(days=1)).isoformat()
        assert (await ids(board_id=w.board_a, since=future))[0] == []
        first, body = await ids(board_id=w.board_a, limit="1")
        assert body["next_cursor"] and "jart_" not in body["next_cursor"]
        second, body2 = await ids(board_id=w.board_a, limit="1", cursor=body["next_cursor"])
        assert set(first + second) == {w.art_audio, w.art_derived} and body2["next_cursor"] is None


async def test_artifact_relations_give_provenance_and_boards(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        _, body, _, _ = await core(stack, "GET", f"/v1/workspace/artifacts/{w.art_audio}/relations")
        assert [r["artifact_id"] for r in body["dependents"]] == [w.art_derived] and body["origins"] == []
        links = {link["board_id"]: link["origin"] for link in body["boards"]["items"]}
        assert links == {w.board_a: "active_board", w.board_b: "explicit"}
        status, missing, _, _ = await core(stack, "GET", f"/v1/workspace/artifacts/jart_{'f' * 32}/relations")
        assert (status, missing["error"]["code"]) == (404, "artifact_not_found")


# ------------------------------------------------------------------ mémoire


async def test_memory_tree_stat_read_search(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        base = f"/v1/workspace/boards/{w.board_a}/memory"
        _, tree, _, _ = await core(stack, "GET", base + "/tree", params={"depth": "1"})
        assert [e["path"] for e in tree["entries"]] == ["image.bin", "notes", "summary.md"]
        _, sub, _, _ = await core(stack, "GET", base + "/tree", params={"path": "notes"})
        assert [e["path"] for e in sub["entries"]] == ["notes/plan.md"]
        _, stat, _, _ = await core(stack, "GET", base + "/stat", params={"path": "image.bin"})
        assert stat["entry"]["kind"] == "file" and stat["entry"]["size"] == 6
        _, page, _, _ = await core(stack, "GET", base + "/read", params={"path": "notes/plan.md", "max_bytes": "8"})
        assert page["text"] == "étape 1" and page["next_offset"] == 8 and page["eof"] is False
        _, rest, _, _ = await core(stack, "GET", base + "/read",
                                   params={"path": "notes/plan.md", "offset": str(page["next_offset"])})
        assert (page["text"] + rest["text"]).startswith("étape 1") and rest["eof"] is True
        _, found, _, _ = await core(stack, "GET", base + "/search", params={"q": "DÉCISIONS"})
        assert {(m["path"], m["line"]) for m in found["matches"]} == {("notes/plan.md", 2), ("summary.md", 2)}
        assert found["files_skipped"] == 1, "the binary file"


@pytest.mark.parametrize("path, params, http, code", [
    ("/sessions", {"limit": "101"}, 400, "invalid_request"),
    ("/sessions", {"limit": "0"}, 400, "invalid_request"),
    ("/sessions", {"cursor": "nope"}, 400, "invalid_request"),
    ("/sessions", {"color": "red"}, 400, "invalid_request"),
    ("/sessions/jsess_nope", {}, 404, "session_not_found"),
    ("/sessions/jsess_nope/activity", {}, 404, "session_not_found"),
    ("/boards/board_nope", {}, 404, "board_not_found"),
    ("/relations", {}, 400, "invalid_request"),
    ("/artifacts", {}, 400, "invalid_request"),
    ("/artifacts", {"board_id": "default", "session_id": "jsess_x"}, 400, "invalid_request"),
    ("/artifacts", {"board_id": "board_nope"}, 404, "board_not_found"),
    ("/artifacts", {"context_id": "jctx_nope"}, 404, "context_not_found"),
    ("/artifacts", {"board_id": "default", "kind": "video"}, 400, "invalid_request"),
    ("/artifacts", {"board_id": "default", "since": "2026-01-01T00:00:00"}, 400, "invalid_request"),
    ("/artifacts/nope/relations", {}, 400, "invalid_artifact"),
    ("/boards/{a}/memory/tree", {"depth": "9"}, 400, "invalid_request"),
    ("/boards/{a}/memory/tree", {"max_entries": "501"}, 400, "invalid_request"),
    ("/boards/{a}/memory/tree", {"path": "summary.md"}, 409, "memory_conflict"),
    ("/boards/{a}/memory/read", {}, 400, "invalid_request"),
    ("/boards/{a}/memory/read", {"path": "summary.md", "max_bytes": "3"}, 400, "invalid_request"),
    ("/boards/{a}/memory/read", {"path": "summary.md", "max_bytes": "262145"}, 400, "invalid_request"),
    ("/boards/{a}/memory/read", {"path": "../x.md"}, 400, "memory_path_escape"),
    ("/boards/{a}/memory/read", {"path": "nul.txt"}, 400, "memory_path_invalid"),
    ("/boards/{a}/memory/read", {"path": "image.bin"}, 415, "memory_not_text"),
    ("/boards/{a}/memory/read", {"path": "notes"}, 409, "memory_conflict"),
    ("/boards/{a}/memory/read", {"path": "absent.md"}, 404, "memory_not_found"),
    ("/boards/{a}/memory/search", {}, 400, "invalid_request"),
    ("/boards/{a}/memory/search", {"q": " "}, 400, "invalid_request"),
    ("/boards/{a}/memory/search", {"q": "x", "limit": "101"}, 400, "invalid_request"),
    ("/boards/board_nope/memory/tree", {}, 404, "board_not_found"),
])
async def test_refusals_keep_stable_codes(tmp_path, path, params, http, code):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        status, body, raw, _ = await core(stack, "GET", "/v1/workspace" + path.format(a=w.board_a), params=params)
        assert (status, body["error"]["code"]) == (http, code), body
        assert_clean(stack, raw)


# ------------------------------------------------------------------ intégrité, pannes


async def test_open_session_on_a_missing_board_is_said_not_crashed(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)

        def corrupt(conn):
            row = conn.execute("SELECT data FROM jarvis_sessions WHERE status='open'").fetchone()
            data = json.loads(row[0])
            data["active_board_id"] = "board_ghost"
            data["visited_board_ids"].append("board_ghost")
            conn.execute("UPDATE jarvis_sessions SET active_board_id='board_ghost', data=? WHERE status='open'",
                         (json.dumps(data),))
            conn.commit()

        await stack.core.state.run_serialized(corrupt)
        status, body, _, _ = await core(stack, "GET", f"/v1/workspace/sessions/{w.open_session}")
        assert status == 200, body
        codes = {(p["code"], p["field"]) for p in body["problems"]}
        assert codes == {("board_not_found", "active_board_id"), ("binding_not_found", "active_board_id")}
        ghost = next(b for b in body["boards"] if b["board_id"] == "board_ghost")
        assert ghost["missing"] is True
        status, rel, _, _ = await core(stack, "GET", "/v1/workspace/relations", params={"session_id": w.open_session})
        assert status == 200 and rel["problems"]


async def test_memory_store_runs_off_the_event_loop_and_failures_are_coded(tmp_path, monkeypatch):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        memory = stack.core.workspace._memory
        loop_thread = threading.current_thread()
        seen = []
        original = memory.search

        def spy(*args, **kwargs):
            seen.append(threading.current_thread() is not loop_thread)
            return original(*args, **kwargs)

        monkeypatch.setattr(memory, "search", spy)
        status, _, _, _ = await core(stack, "GET", f"/v1/workspace/boards/{w.board_a}/memory/search",
                                     params={"q": "étape"})
        assert status == 200 and seen == [True]

        def bare_value_error(*args, **kwargs):
            raise ValueError("depth must be in 1..8")

        monkeypatch.setattr(memory, "tree", bare_value_error)
        status, body, _, _ = await core(stack, "GET", f"/v1/workspace/boards/{w.board_a}/memory/tree")
        assert (status, body["error"]["code"]) == (400, "invalid_request")

        def broken(*args, **kwargs):
            raise RuntimeError("disk gone")

        monkeypatch.setattr(memory, "tree", broken)
        status, body, _, _ = await core(stack, "GET", f"/v1/workspace/boards/{w.board_a}/memory/tree")
        assert (status, body["error"]["code"]) == (500, "workspace_failed")
        assert "disk gone" in body["error"]["message"]
        _, inspect, _, _ = await core(stack, "GET", f"/v1/workspace/boards/{w.board_a}")
        assert inspect["memory"]["error"] == "board_memory_failed", "a broken memory never hides the Board"


async def test_relay_answers_core_unconfigured_without_core(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        stack.center.sessions = None
        status, body, _ = await stack.call("GET", "/api/workspace/sessions")
        assert (status, body["error"]["code"]) == (503, "core_unconfigured")


async def test_board_routes_of_the_control_center_carry_board_kind(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        # `BoardSessionRoutes` reçoit son transport à la construction ; la pile le pose après coup.
        stack.center.board_routes._transport = stack.sessions
        status, body, _ = await stack.call("GET", "/api/boards", params={"include_archived": "true"})
        assert status == 200
        kinds = {b["board_id"]: b["board_kind"] for b in body["boards"]}
        assert kinds[w.board_a] == "meeting" and kinds[w.board_archived] == "empty"
        _, one, _ = await stack.call("GET", f"/api/boards/{w.board_a}")
        assert one["board"]["board_kind"] == "meeting"

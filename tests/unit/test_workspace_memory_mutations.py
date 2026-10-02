"""Mutations de la mémoire et des liens d'un Board (board-memory-workspace-inspector, Slice 05).

Contrat : `docs/boards.md` › *Board memory mutations*. Même vraie chaîne que
l'inspection (`tests/fakes/capture_stack.py`) et même monde
(`test_workspace_inspection_api.build`) : Board B actif, Board A inactif avec
mémoire, Board archivé avec mémoire. Ce qui doit tenir :

- chaque mutation, sur un Board **nommé**, fait son acte et ajoute **une**
  ligne `board.memory.*` / `board.artifact.*` (Session ouverte, `origin`,
  chemins, octets, `sha256`) ; rien n'est écrit quand rien ne change ;
- Board archivé : `board_archived` pour toute mutation, lectures permises ;
- deux `replace` concurrents sur le même condensé : un seul gagne ;
- ligne du ledger en échec après l'acte : `workspace_ledger_failed`, `applied` ;
- relais du Control Center identique, et refusé d'une origine étrangère ;
- aucune mutation n'active un Board (Session, liaisons, autorité, mode).
"""

from __future__ import annotations

import asyncio
import hashlib
import threading
import time

import pytest

from jarvis.adapters.sqlite_board_artifact_links import SQLiteBoardArtifactLinks
from tests.fakes.capture_stack import CaptureStack
from tests.unit.test_capture_api_protocol import assert_clean, core
from tests.unit.test_workspace_inspection_api import World, build, snapshot

V1 = "/v1/workspace"


class Diagnostics:
    """Journal de Core retenu en mémoire (la pile de test n'en pose pas)."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def emit(self, kind: str, message: str, *, level: str = "info", data: dict | None = None) -> None:
        self.events.append({"kind": kind, "message": message, "level": level, "data": data or {}})

    def kinds(self) -> list[str]:
        return [event["kind"] for event in self.events]


def diagnostics(stack: CaptureStack) -> Diagnostics:
    sink = Diagnostics()
    stack.core.workspace._diagnostics = sink
    return sink


def memory_of(stack: CaptureStack, board_id: str):
    return stack.data_root / "boards" / board_id / "memory"


async def board_events(stack: CaptureStack, w: World, kind: str) -> list[dict]:
    _, body, _, _ = await core(stack, "GET", f"{V1}/sessions/{w.open_session}/activity",
                               params={"kind": kind, "limit": "100"})
    return body["events"]


async def post(stack: CaptureStack, path: str, body: dict | None = None):
    status, payload, raw, _ = await core(stack, "POST", V1 + path, json=body if body is not None else {})
    assert_clean(stack, raw)
    return status, payload


# ------------------------------------------------------------------ écriture


async def test_write_create_replace_append_record_one_row_each(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        base = f"/boards/{w.board_a}/memory"
        status, created = await post(stack, base + "/write", {"path": "journal/2026.md", "content": "début\n"})
        assert status == 201, created
        assert created["created"] is True and created["mode"] == "create" and created["path"] == "journal/2026.md"
        assert created["sha256"] == hashlib.sha256("début\n".encode()).hexdigest()
        assert created["jarvis_session_id"] == w.open_session and created["activity_seq"] > 0

        status, replaced = await post(stack, base + "/write", {
            "path": "journal/2026.md", "content": "remplacé\n", "mode": "replace",
            "expected_sha256": created["sha256"], "origin": "brain"})
        assert status == 200 and replaced["created"] is False
        status, appended = await post(stack, base + "/write", {"path": "journal/2026.md", "content": "suite\n",
                                                               "mode": "append"})
        assert status == 200 and appended["size"] == len("remplacé\nsuite\n".encode())
        assert appended["sha256"] == hashlib.sha256("remplacé\nsuite\n".encode()).hexdigest(), "whole-file sha"
        assert (memory_of(stack, w.board_a) / "journal" / "2026.md").read_text(encoding="utf-8") == "remplacé\nsuite\n"

        events = await board_events(stack, w, "board.memory.written")
        assert [e["seq"] for e in events] == [created["activity_seq"], replaced["activity_seq"],
                                              appended["activity_seq"]]
        first, second, third = (e["data"] for e in events)
        assert first == {"board_id": w.board_a, "path": "journal/2026.md", "mode": "create", "entry_kind": "file",
                         "created": True, "bytes": 7, "size": 7, "sha256": created["sha256"], "conditional": False,
                         "origin": "user"}
        assert second["origin"] == "brain" and second["conditional"] is True and second["mode"] == "replace"
        assert third["mode"] == "append" and third["bytes"] == 6 and third["sha256"] == appended["sha256"]
        assert all(e["jarvis_session_id"] == w.open_session and e["context_id"] is None for e in events)

        _, read, _, _ = await core(stack, "GET", f"{V1}{base}/read", params={"path": "journal/2026.md"})
        assert read["sha256"] == appended["sha256"], "read sha feeds expected_sha256"


async def test_mkdir_move_delete_and_their_rows(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        base = f"/boards/{w.board_a}/memory"
        status, made = await post(stack, base + "/mkdir", {"path": "archives/2025"})
        assert status == 201 and made["created"] is True and made["entry"]["kind"] == "directory"
        status, again = await post(stack, base + "/mkdir", {"path": "archives/2025"})
        assert status == 200 and again["created"] is False and again["activity_seq"] is None

        status, moved = await post(stack, base + "/move", {"from": "notes/plan.md", "to": "archives/2025/plan.md"})
        assert status == 200 and moved["to"] == "archives/2025/plan.md" and moved["entry"]["kind"] == "file"
        status, renamed = await post(stack, base + "/move", {"from": "archives", "to": "classé"})
        assert status == 200 and renamed["entry"]["kind"] == "directory"
        assert (memory_of(stack, w.board_a) / "classé" / "2025" / "plan.md").is_file()

        status, refused = await post(stack, base + "/delete", {"path": "classé"})
        assert (status, refused["error"]["code"]) == (409, "memory_conflict"), "non-empty folder needs recursive"
        assert (memory_of(stack, w.board_a) / "classé" / "2025" / "plan.md").is_file()
        status, gone = await post(stack, base + "/delete", {"path": "classé", "recursive": True})
        assert status == 200 and gone["removed"] == 3 and gone["recursive"] is True
        status, one = await post(stack, base + "/delete", {"path": "summary.md"})
        assert status == 200 and one["removed"] == 1
        assert not (memory_of(stack, w.board_a) / "classé").exists()

        written = await board_events(stack, w, "board.memory.written")
        assert [e["data"]["mode"] for e in written] == ["mkdir"], "the second mkdir changed nothing"
        assert written[0]["data"]["entry_kind"] == "directory"
        moves = [e["data"] for e in await board_events(stack, w, "board.memory.moved")]
        assert [(m["from"], m["to"], m["entry_kind"]) for m in moves] == [
            ("notes/plan.md", "archives/2025/plan.md", "file"), ("archives", "classé", "directory")]
        deletes = [e["data"] for e in await board_events(stack, w, "board.memory.deleted")]
        assert [(d["path"], d["recursive"], d["removed"]) for d in deletes] == [("classé", True, 3),
                                                                                ("summary.md", False, 1)]
        assert all(d["board_id"] == w.board_a and d["origin"] == "user" for d in deletes)


async def test_mutations_on_a_board_without_memory_never_create_it_on_refusal(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        base = f"/boards/{w.board_b}/memory"
        for op, body in (("/move", {"from": "a.md", "to": "b.md"}), ("/delete", {"path": "a.md"})):
            status, refused = await post(stack, base + op, body)
            assert (status, refused["error"]["code"]) == (404, "memory_not_found")
        assert not (stack.data_root / "boards" / w.board_b).exists()
        status, _ = await post(stack, base + "/write", {"path": "première.md", "content": "x"})
        assert status == 201 and (memory_of(stack, w.board_b) / "première.md").is_file()


# ------------------------------------------------------------------ liens


async def test_explicit_link_and_unlink_write_one_row_in_the_same_transaction(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        path = f"/boards/{w.board_archived}/artifacts/{w.art_closed}"
        status, refused = await post(stack, path)
        assert (status, refused["error"]["code"]) == (409, "board_archived")

        path = f"/boards/{w.board_a}/artifacts/{w.art_closed}"
        status, linked = await post(stack, path, {"origin": "brain"})
        assert status == 201 and linked["created"] is True and linked["link"]["origin"] == "explicit"
        status, again = await post(stack, path)
        assert status == 200 and again["created"] is False and again["activity_seq"] is None
        # Un lien automatique existant garde son origine.
        status, kept = await post(stack, f"/boards/{w.board_a}/artifacts/{w.art_audio}")
        assert status == 200 and kept["link"]["origin"] == "active_board" and kept["created"] is False

        status, unlinked, _, _ = await core(stack, "DELETE", V1 + path, params={"origin": "brain"})
        assert status == 200 and unlinked["removed"] is True
        status, nothing, _, _ = await core(stack, "DELETE", V1 + path)
        assert status == 200 and nothing["removed"] is False and nothing["activity_seq"] is None
        assert await SQLiteBoardArtifactLinks(stack.core.state).count_links(w.board_a) == 2

        [link_row] = await board_events(stack, w, "board.artifact.linked")
        assert link_row["artifact_ids"] == [w.art_closed] and link_row["seq"] == linked["activity_seq"]
        assert link_row["data"] == {"board_id": w.board_a, "link_origin": "explicit", "origin": "brain"}
        [unlink_row] = await board_events(stack, w, "board.artifact.unlinked")
        assert unlink_row["data"] == {"board_id": w.board_a, "origin": "brain"}
        assert unlink_row["jarvis_session_id"] == w.open_session


async def test_link_and_unlink_refusals(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        missing = "jart_" + "f" * 32
        cases = [
            ("POST", f"/boards/{w.board_a}/artifacts/{missing}", 404, "artifact_not_found"),
            ("DELETE", f"/boards/{w.board_a}/artifacts/{missing}", 404, "artifact_not_found"),
            ("POST", f"/boards/board_nope/artifacts/{w.art_audio}", 404, "board_not_found"),
            ("DELETE", f"/boards/board_nope/artifacts/{w.art_audio}", 404, "board_not_found"),
            ("POST", f"/boards/{w.board_a}/artifacts/nope", 400, "invalid_artifact"),
            ("DELETE", f"/boards/{w.board_archived}/artifacts/{w.art_audio}", 409, "board_archived"),
        ]
        for method, path, http, code in cases:
            status, body, _, _ = await core(stack, method, V1 + path)
            assert (status, body["error"]["code"]) == (http, code), (method, path, body)
        status, body, _, _ = await core(stack, "DELETE", f"{V1}/boards/{w.board_a}/artifacts/{w.art_audio}",
                                        params={"origin": "voice"})
        assert (status, body["error"]["code"]) == (400, "invalid_request")
        status, body, _, _ = await core(stack, "DELETE", f"{V1}/boards/{w.board_a}/artifacts/{w.art_audio}",
                                        data=b'{"origin":"user"}')
        assert (status, body["error"]["code"]) == (400, "invalid_request"), "DELETE takes no body"
        status, body = await post(stack, f"/boards/{w.board_a}/artifacts/{w.art_audio}", {"why": "x"})
        assert (status, body["error"]["code"]) == (400, "invalid_request")


# ------------------------------------------------------------------ Board archivé


async def test_archived_board_refuses_every_mutation_and_stays_readable(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        base = f"/boards/{w.board_archived}/memory"
        root = memory_of(stack, w.board_archived)
        before = sorted((p.relative_to(root).as_posix(), p.stat().st_mtime_ns) for p in root.rglob("*"))
        for op, body in (("/write", {"path": "vieux.md", "content": "x", "mode": "replace"}),
                         ("/write", {"path": "neuf.md", "content": "x"}), ("/mkdir", {"path": "d"}),
                         ("/move", {"from": "vieux.md", "to": "v.md"}), ("/delete", {"path": "vieux.md"})):
            status, refused = await post(stack, base + op, body)
            assert (status, refused["error"]["code"]) == (409, "board_archived"), (op, refused)
        assert sorted((p.relative_to(root).as_posix(), p.stat().st_mtime_ns) for p in root.rglob("*")) == before
        _, read, _, _ = await core(stack, "GET", V1 + base + "/read", params={"path": "vieux.md"})
        assert read["text"] == "archive\n"
        _, found, _, _ = await core(stack, "GET", V1 + base + "/search", params={"q": "archive"})
        assert [m["path"] for m in found["matches"]] == ["vieux.md"]
        assert await board_events(stack, w, "board.memory.written,board.memory.moved,board.memory.deleted") == []


# ------------------------------------------------------------------ refus codés


@pytest.mark.parametrize("op, body, http, code", [
    ("/write", {"content": "x"}, 400, "invalid_request"),
    ("/write", {"path": "a.md"}, 400, "invalid_request"),
    ("/write", {"path": "a.md", "content": "x", "colour": "red"}, 400, "invalid_request"),
    ("/write", {"path": "a.md", "content": 3}, 400, "invalid_request"),
    ("/write", {"path": "a.md", "content": "x", "mode": "overwrite"}, 400, "invalid_request"),
    ("/write", {"path": "a.md", "content": "x", "mode": ["create"]}, 400, "invalid_request"),
    ("/write", {"path": "a.md", "content": "x", "expected_sha256": "ABC"}, 400, "invalid_request"),
    ("/write", {"path": "a.md", "content": "x", "origin": "voice"}, 400, "invalid_request"),
    ("/write", {"path": "a.md", "content": "x", "origin": ["user"]}, 400, "invalid_request"),
    ("/write", {"path": "../a.md", "content": "x"}, 400, "memory_path_escape"),
    ("/write", {"path": "C:/a.md", "content": "x"}, 400, "memory_path_escape"),
    ("/write", {"path": "con.md", "content": "x"}, 400, "memory_path_invalid"),
    ("/write", {"path": 7, "content": "x"}, 400, "memory_path_invalid"),
    ("/write", {"path": "a" * 241, "content": "x"}, 400, "memory_path_invalid"),
    ("/write", {"path": "summary.md", "content": "x"}, 409, "memory_exists"),
    ("/write", {"path": "notes", "content": "x", "mode": "replace"}, 409, "memory_conflict"),
    ("/write", {"path": "summary.md", "content": "x", "mode": "replace", "expected_sha256": "0" * 64}, 409,
     "memory_conflict"),
    ("/write", {"path": "absent.md", "content": "x", "mode": "replace", "expected_sha256": "0" * 64}, 409,
     "memory_conflict"),
    ("/write", {"path": "image.bin", "content": "x", "mode": "append"}, 415, "memory_not_text"),
    ("/write", {"path": "a.md", "content": "a\x00b"}, 415, "memory_not_text"),
    ("/write", {"path": "a.md", "content": "é" * (128 * 1024 + 1)}, 413, "memory_too_large"),
    ("/mkdir", {}, 400, "invalid_request"),
    ("/mkdir", {"path": "summary.md"}, 409, "memory_conflict"),
    ("/move", {"from": "summary.md"}, 400, "invalid_request"),
    ("/move", {"from": "absent.md", "to": "b.md"}, 404, "memory_not_found"),
    ("/move", {"from": "summary.md", "to": "notes/plan.md"}, 409, "memory_exists"),
    ("/move", {"from": "notes", "to": "notes/sous"}, 409, "memory_conflict"),
    ("/move", {"from": "summary.md", "to": "../x.md"}, 400, "memory_path_escape"),
    ("/delete", {"path": "absent.md"}, 404, "memory_not_found"),
    ("/delete", {"path": "notes"}, 409, "memory_conflict"),
    ("/delete", {"path": "notes", "recursive": "yes"}, 400, "invalid_request"),
    ("/delete", {"path": ""}, 400, "memory_path_invalid"),
])
async def test_mutation_refusals_keep_stable_codes_and_change_nothing(tmp_path, op, body, http, code):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        sink = diagnostics(stack)
        root = memory_of(stack, w.board_a)
        before = sorted((p.relative_to(root).as_posix(), p.stat().st_mtime_ns) for p in root.rglob("*"))
        status, refused = await post(stack, f"/boards/{w.board_a}/memory{op}", body)
        assert (status, refused["error"]["code"]) == (http, code), refused
        assert sorted((p.relative_to(root).as_posix(), p.stat().st_mtime_ns) for p in root.rglob("*")) == before
        assert await board_events(stack, w, "board.memory.written,board.memory.moved,board.memory.deleted") == []
        [failure] = [e for e in sink.events if e["kind"] == "core.workspace.mutation_failed"]
        assert failure["data"]["code"] == code and failure["data"]["status"] == http


async def test_body_level_refusals(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        url = f"{V1}/boards/{w.board_a}/memory/write"
        for raw in (b"not json", b"[1]", b'{"path":"a.md","path":"b.md","content":"x"}'):
            status, body, _, _ = await core(stack, "POST", url, data=raw)
            assert (status, body["error"]["code"]) == (400, "invalid_request"), raw
        # Surrogat isolé : pas encodable en UTF-8.
        status, body, _, _ = await core(stack, "POST", url, data=b'{"path":"a.md","content":"\\ud800"}')
        assert (status, body["error"]["code"]) == (415, "memory_not_text")
        status, body, _, _ = await core(stack, "POST", url, params={"x": "1"}, json={"path": "a.md", "content": "x"})
        assert (status, body["error"]["code"]) == (400, "invalid_request")
        status, body = await post(stack, "/boards/board_nope/memory/write", {"path": "a.md", "content": "x"})
        assert (status, body["error"]["code"]) == (404, "board_not_found")
        status, body, _, _ = await core(stack, "POST", url, data=b"x" * (2 * 1024 * 1024 + 1))
        assert (status, body["error"]["code"]) == (400, "invalid_request")


async def test_largest_write_passes_core_and_relay_whole(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        content = "é" * (128 * 1024)  # 256 Kio exactement en UTF-8, bien plus de 64 Kio de JSON
        status, body, _ = await stack.call("POST", f"/api/workspace/boards/{w.board_a}/memory/write",
                                           json={"path": "gros.md", "content": content})
        assert status == 201, body
        assert body["bytes"] == 256 * 1024 and body["sha256"] == hashlib.sha256(content.encode()).hexdigest()


# ------------------------------------------------------------------ verrou, fil, ledger


async def test_two_concurrent_replaces_on_the_same_sha_one_wins(tmp_path, monkeypatch):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        _, read, _, _ = await core(stack, "GET", f"{V1}/boards/{w.board_a}/memory/read", params={"path": "summary.md"})
        memory = stack.core.workspace._memory
        original = memory.write
        threads = []

        def slow_write(*args, **kwargs):
            # Sans verrou, les deux écrivains vérifieraient le même condensé pendant ce délai.
            threads.append(threading.current_thread().name)
            time.sleep(0.3)
            return original(*args, **kwargs)

        monkeypatch.setattr(memory, "write", slow_write)
        url = f"/boards/{w.board_a}/memory/write"
        results = await asyncio.gather(*(post(stack, url, {
            "path": "summary.md", "content": f"version {n}\n", "mode": "replace",
            "expected_sha256": read["sha256"]}) for n in (1, 2)))
        statuses = sorted(status for status, _ in results)
        assert statuses == [200, 409], results
        loser = next(body for status, body in results if status == 409)
        assert loser["error"]["code"] == "memory_conflict"
        winner = next(body for status, body in results if status == 200)
        text = (memory_of(stack, w.board_a) / "summary.md").read_text(encoding="utf-8")
        assert hashlib.sha256(text.encode()).hexdigest() == winner["sha256"]
        assert len(await board_events(stack, w, "board.memory.written")) == 1
        assert threading.main_thread().name not in threads, "store calls run off the event loop"


async def test_ledger_failure_after_the_file_change_is_said_applied(tmp_path, monkeypatch):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        sink = diagnostics(stack)

        async def broken_record(*args, **kwargs):
            raise RuntimeError("ledger disk full")

        monkeypatch.setattr(stack.core.artifacts, "record", broken_record)
        status, body = await post(stack, f"/boards/{w.board_a}/memory/write", {"path": "n.md", "content": "fait\n"})
        assert (status, body["error"]["code"]) == (500, "workspace_ledger_failed"), body
        assert body["error"]["applied"] is True and body["error"]["result"]["path"] == "n.md"
        assert "was applied" in body["error"]["message"] and "ledger disk full" in body["error"]["message"]
        assert (memory_of(stack, w.board_a) / "n.md").read_text(encoding="utf-8") == "fait\n"
        status, body = await post(stack, f"/boards/{w.board_a}/memory/delete", {"path": "n.md"})
        assert (status, body["error"]["code"], body["error"]["result"]["removed"]) == (
            500, "workspace_ledger_failed", 1)
        kinds = sink.kinds()
        assert kinds.count("core.workspace.ledger_failed") == 2
        assert "core.workspace.mutation_failed" in kinds


# ------------------------------------------------------------------ relais, garde


async def test_relay_mutations_are_identical_to_core(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        steps = [
            ("POST", f"/boards/{w.board_a}/memory/write", {"path": "r.md", "content": "1"}),
            ("POST", f"/boards/{w.board_a}/memory/write", {"path": "r.md", "content": "1"}),  # memory_exists
            ("POST", f"/boards/{w.board_a}/memory/mkdir", {"path": "d"}),
            ("POST", f"/boards/{w.board_a}/memory/move", {"from": "r.md", "to": "d/r.md"}),
            ("POST", f"/boards/{w.board_a}/memory/delete", {"path": "d", "recursive": True}),
            ("POST", f"/boards/{w.board_archived}/memory/mkdir", {"path": "d"}),  # board_archived
            ("POST", f"/boards/{w.board_a}/artifacts/{w.art_closed}", {}),
        ]
        relayed = []
        for method, path, body in steps:
            status, payload, _ = await stack.call(method, "/api/workspace" + path, json=body)
            relayed.append((status, payload))
        status, unlinked, _ = await stack.call("DELETE", f"/api/workspace/boards/{w.board_a}/artifacts/{w.art_closed}")
        assert status == 200 and unlinked["removed"] is True
        assert [s for s, _ in relayed] == [201, 409, 201, 200, 200, 409, 201]
        assert relayed[1][1]["error"]["code"] == "memory_exists" and relayed[5][1]["error"]["code"] == "board_archived"
        # Même réponse que Core (hors ligne du ledger et horodatages) : rejouée sur Core.
        status, direct = await post(stack, f"/boards/{w.board_a}/memory/write", {"path": "r.md", "content": "1"})
        assert status == 201 and {k: v for k, v in direct.items() if k not in {"activity_seq", "entry"}} == {
            k: v for k, v in relayed[0][1].items() if k not in {"activity_seq", "entry"}}
        relays = [e for e in stack.trace() if e.get("kind") == "workspace.request.relayed"]
        assert len(relays) == 8 and {e["data"]["action"] for e in relays} >= {
            "workspace_memory_write", "workspace_artifact_unlink"}


@pytest.mark.parametrize("method, path", [
    ("POST", "/memory/write"), ("POST", "/memory/mkdir"), ("POST", "/memory/move"), ("POST", "/memory/delete"),
    ("POST", "/artifacts/jart_" + "c" * 32), ("DELETE", "/artifacts/jart_" + "a" * 32),
])
@pytest.mark.parametrize("headers", [
    {"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}, {"Host": "evil.example"},
])
async def test_every_mutation_is_refused_from_a_foreign_origin(tmp_path, method, path, headers):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        before = await snapshot(stack)
        body = {"path": "summary.md", "content": "volé", "mode": "replace", "from": "summary.md", "to": "x.md",
                "recursive": True}
        status, refused, _ = await stack.call(method, f"/api/workspace/boards/{w.board_a}{path}", headers=headers,
                                              json=body)
        assert status == 403 and refused["code"] == "forbidden_origin"
        assert await snapshot(stack) == before


# ------------------------------------------------------------------ jamais d'activation


async def test_mutations_on_an_inactive_board_never_activate_it(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        before = await snapshot(stack)
        assert before["authority"]["board_id"] == w.board_b, "B is the foreground Board"
        base = f"/api/workspace/boards/{w.board_a}"
        for method, path, body in (
            ("POST", "/memory/write", {"path": "x.md", "content": "1", "origin": "brain"}),
            ("POST", "/memory/write", {"path": "x.md", "content": "2", "mode": "append"}),
            ("POST", "/memory/mkdir", {"path": "d"}),
            ("POST", "/memory/move", {"from": "x.md", "to": "d/x.md"}),
            ("POST", "/memory/delete", {"path": "d", "recursive": True}),
            ("POST", f"/artifacts/{w.art_closed}", {}),
            ("DELETE", f"/artifacts/{w.art_closed}", None),
            ("POST", "/memory/write", {"path": "y.md", "content": "1"}),
        ):
            status, payload, _ = await stack.call(method, base + path, json=body)
            assert status < 300, (path, payload)
        # Lecture historique d'un autre Board (archivé), par son id : rien n'est activé non plus.
        status, _, _ = await stack.call("GET", f"/api/workspace/boards/{w.board_archived}/memory/search",
                                        params={"q": "archive"})
        assert status == 200
        after = await snapshot(stack)
        for key in ("sessions", "bindings", "boards", "authority", "mode"):
            assert after[key] == before[key], f"{key} changed"
        grown = {t for t in after["counts"] if after["counts"][t] != before["counts"][t]}
        assert grown == {"session_activity"}, grown
        assert after["counts"]["session_activity"] - before["counts"]["session_activity"] == 8
        _, active, _, _ = await core(stack, "GET", f"{V1}/sessions/{w.open_session}")
        assert active["session"]["active_board_id"] == w.board_b

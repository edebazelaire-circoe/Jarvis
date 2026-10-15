"""Dépôt sur le Board affiché (handoff jarvis-unified-chat-and-board-drop, Slice 08, `docs/chat.md` › *Board drop*).

Chaîne réelle pour les dépôts relayés : multipart du navigateur simulé → vrai
`ControlCenter` (`POST /api/boards/drop`, `/api/boards/drop-link`) →
`CoreSessionTransport` → `LocalProtocolServer` → Core (SQLite et payloads sous
`tmp_path`). Une URL déposée n'est jamais récupérée : pendant ces dépôts, toute
connexion sortante autre que le bouclage de Core fait échouer le test.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import socket
import uuid

import pytest

from jarvis.domain.artifacts import ArtifactKind, ArtifactQuery, ArtifactState
from jarvis.domain.uploads import LinkInvalid, check_link_url, upload_artifact_id
from tests.fakes.capture_stack import CaptureStack

BOUNDARY = "jarvis-board-drop-boundary"
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 8
PDF = b"%PDF-1.4\n" + b"1 0 obj << >> endobj\n" * 50 + b"%%EOF\n"
HEADERS = {"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"}
URL = "https://example.invalid/rapport?q=1#section"


def multipart(upload_id: str, filename: str, content_type: str, data: bytes) -> bytes:
    return (f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"client_upload_id\"\r\n\r\n{upload_id}\r\n"
            f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {content_type}\r\n\r\n").encode("utf-8") + data + f"\r\n--{BOUNDARY}--\r\n".encode()


class NoOutboundNetwork:
    """Transport réseau factice : toute connexion ou résolution hors du bouclage échoue le test.

    Couvre les chemins par lesquels Python sort : `socket.connect`, `create_connection`,
    `getaddrinfo` (synchrone et de la boucle) ; le bouclage (Core et Control Center du test) reste permis.
    """

    LOOPBACK = {"127.0.0.1", "localhost", "::1"}

    def __init__(self, monkeypatch) -> None:  # noqa: ANN001
        self.attempts: list[str] = []
        real_connect, real_getaddrinfo = socket.socket.connect, socket.getaddrinfo
        guard = self

        def connect(sock, address):  # noqa: ANN001
            guard._check(address[0] if isinstance(address, tuple) else str(address))
            return real_connect(sock, address)

        def getaddrinfo(host, *args, **kwargs):  # noqa: ANN001
            guard._check(host)
            return real_getaddrinfo(host, *args, **kwargs)

        monkeypatch.setattr(socket.socket, "connect", connect)
        monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
        loop = asyncio.get_running_loop()
        real_loop_getaddrinfo = loop.getaddrinfo

        async def loop_getaddrinfo(host, *args, **kwargs):  # noqa: ANN001
            guard._check(host)
            return await real_loop_getaddrinfo(host, *args, **kwargs)

        monkeypatch.setattr(loop, "getaddrinfo", loop_getaddrinfo)

    def _check(self, host: object) -> None:
        text = host.decode() if isinstance(host, bytes) else str(host)
        if text not in self.LOOPBACK:
            self.attempts.append(text)
            pytest.fail(f"outbound network call to {text!r} during a board drop")


@pytest.fixture
async def stack(tmp_path):
    async with CaptureStack(tmp_path) as opened:
        yield opened


async def active_board(stack) -> str:
    return (await stack.core.sessions.current()).session.active_board_id


async def drop_file(stack, board_id: str, filename: str, content_type: str, data: bytes, *,
                    upload_id: str | None = None):
    return await stack.call("POST", f"/api/boards/drop?board_id={board_id}",
                            data=multipart(upload_id or str(uuid.uuid4()), filename, content_type, data),
                            headers=HEADERS)


async def drop_link(stack, board_id: str, url: str = URL, *, upload_id: str | None = None):
    return await stack.call("POST", "/api/boards/drop-link",
                            json={"client_upload_id": upload_id or str(uuid.uuid4()), "url": url, "board_id": board_id})


async def board_artifacts(stack, board_id: str) -> dict[str, dict]:
    status, body, text = await stack.call("GET", f"/api/workspace/artifacts?board_id={board_id}&limit=50")
    assert status == 200, text
    return {item["artifact_id"]: item for item in body["artifacts"]}


async def all_events(stack) -> list:
    """Tous les événements de conversation, toutes conversations confondues."""

    page = await stack.core.conversation_events.list_conversations(limit=100)
    events = []
    for conversation in page.summaries:
        listed = await stack.core.conversation_events.list_conversation_events(conversation.conversation_id,
                                                                              limit=500)
        events.extend(item.event for item in listed.events)
    return events


# ------------------------------------------------------------------ contrat Slice 00


async def test_file_drop_links_active_board(stack):
    board = await active_board(stack)
    status, body, text = await drop_file(stack, board, "rapport.pdf", "application/pdf", PDF)
    assert status == 201, text
    assert body["ok"] is True and body["board_id"] == board and body["relinked"] is False
    assert (body["mime_type"], body["state"], body["original_name"]) == ("application/pdf", "complete", "rapport.pdf")
    artifact = await stack.core.artifacts.get(body["artifact_id"])
    assert artifact.kind is ArtifactKind.UPLOAD and artifact.source == "board_drop"
    assert artifact.metadata["provenance"] == "board_drop"
    listed = await board_artifacts(stack, board)
    assert listed[artifact.artifact_id]["provenance"] == "board_drop"
    assert listed[artifact.artifact_id]["preview"] == "rapport.pdf"
    links = await stack.core.board_artifact_links.boards_of_artifact(artifact.artifact_id, limit=10)
    assert [(link.board_id, link.origin.value) for link in links] == [(board, "active_board")]
    root = str(stack.core.artifacts._payloads.root())
    assert root not in json.dumps(body) and "upload." not in json.dumps(body)
    relayed = [entry for entry in stack.trace() if entry.get("kind") == "board.drop.relayed"]
    assert relayed and relayed[-1]["data"]["status"] == 201 and "rapport" not in json.dumps(relayed)


async def test_image_drop_sniffed(stack):
    board = await active_board(stack)
    status, body, text = await drop_file(stack, board, "photo.gif", "image/gif", PNG)  # un PNG qui se dit GIF
    assert status == 201, text
    artifact = await stack.core.artifacts.get(body["artifact_id"])
    assert (artifact.mime_type, artifact.payload_name) == ("image/png", "upload.png")
    assert artifact.metadata["declared_mime"] == "image/gif"
    assert artifact.artifact_id in await board_artifacts(stack, board)


async def test_drop_on_inactive_board_409(stack):
    first = await active_board(stack)
    other = await stack.core.boards.create({"title": "Projet B"})
    status, body, _ = await drop_file(stack, other.board_id, "a.png", "image/png", PNG)
    assert (status, body["code"], body["core_status"]) == (409, "board_drop_target_inactive", 409)
    assert body["active_board_id"] == first
    status, body, _ = await drop_link(stack, other.board_id)
    assert (status, body["code"]) == (409, "board_drop_target_inactive")
    assert all(item.kind not in (ArtifactKind.UPLOAD, ArtifactKind.LINK)
               for item in (await stack.core.artifacts.query(ArtifactQuery(limit=50))).items)
    assert await board_artifacts(stack, other.board_id) == {}


class RecordingSink:
    """Journal de diagnostic de Core (le banc n'en câble pas) : `(kind, level, data)` émis."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, str, dict]] = []

    def emit(self, kind: str, message: str, *, level: str = "info", data: dict | None = None) -> None:
        self.entries.append((kind, level, dict(data or {})))

    def of(self, kind: str) -> list[tuple[str, dict]]:
        return [(level, data) for name, level, data in self.entries if name == kind]


def wrap_seam(stack, **overrides) -> None:
    """Remplace des fonctions du `BoardDropSeam` câblé ; chaque surcharge reçoit la fonction réelle."""

    seam = stack.core.uploads._board_drop
    stack.core.uploads._board_drop = dataclasses.replace(
        seam, **{name: wrapper(getattr(seam, name)) for name, wrapper in overrides.items()})


async def links_of(stack, artifact_id: str) -> dict[str, str]:
    return {link.board_id: link.origin.value
            for link in await stack.core.board_artifact_links.boards_of_artifact(artifact_id, limit=10)}


async def switch_race(stack, board_b: str, *, upload_id: str | None = None):
    """Dépôt sur le Board affiché A ; la bascule vers B passe entre le contrôle et la transaction de création."""

    board_a = await active_board(stack)
    gate, reached = asyncio.Event(), asyncio.Event()

    async def read(n: int) -> bytes:  # corps tenu après le contrôle, avant la création
        if not gate.is_set():
            reached.set()
            await gate.wait()
            return PNG
        return b""

    task = asyncio.create_task(stack.core.uploads.put(
        client_upload_id=upload_id or str(uuid.uuid4()), purpose="board", board_id=board_a, agent="claude",
        declared_mime="image/png", name_header="a.png", content_length=None, read=read))
    await asyncio.wait_for(reached.wait(), 10)
    await stack.core.boards.switch(board_b)
    gate.set()
    return board_a, await asyncio.wait_for(task, 10)


async def test_switch_race_relinks_target(stack):
    """Bascule pendant le dépôt : Core relie A et retire le lien automatique posé sur B. Le fichier est sur A seul."""

    board_b = (await stack.core.boards.create({"title": "Projet B"})).board_id
    sink = RecordingSink()
    stack.core.uploads._diagnostics = sink
    board_a, outcome = await switch_race(stack, board_b)
    assert outcome.relinked is True and outcome.board_id == board_a and outcome.also_linked_board_id is None
    assert await links_of(stack, outcome.artifact.artifact_id) == {board_a: "explicit"}
    assert sink.of("core.upload.board_auto_link_removed") == [
        ("warning", {"artifact_id": outcome.artifact.artifact_id, "board_id": board_a, "auto_board_id": board_b})]
    assert outcome.artifact.artifact_id in await board_artifacts(stack, board_a)
    assert outcome.artifact.artifact_id not in await board_artifacts(stack, board_b)


async def test_switch_race_keeps_explicit_link_of_other_board(stack):
    """Un lien `explicit` sur B posé par quelqu'un d'autre pendant le dépôt n'est jamais retiré."""

    board_b = (await stack.core.boards.create({"title": "Projet B"})).board_id

    def link(real):  # noqa: ANN001, ANN202
        async def linked_by_someone_else_first(board_id: str, artifact_id: str) -> None:
            # Quelqu'un relie explicitement l'Artifact à B (retrait du lien auto puis lien `explicit`).
            await stack.core.workspace.artifact_unlink(board_b, artifact_id)
            await stack.core.workspace.artifact_link(board_b, artifact_id, origin="brain")
            await real(board_id, artifact_id)
        return linked_by_someone_else_first

    wrap_seam(stack, link=link)
    board_a, outcome = await switch_race(stack, board_b)
    assert outcome.relinked is True and outcome.also_linked_board_id is None
    assert await links_of(stack, outcome.artifact.artifact_id) == {board_a: "explicit", board_b: "explicit"}


async def test_switch_race_unlink_failure_keeps_target(stack):
    """Retrait du lien automatique impossible : journal `error`, le fichier reste sur A et la réponse nomme B."""

    board_b = (await stack.core.boards.create({"title": "Projet B"})).board_id
    sink = RecordingSink()
    stack.core.uploads._diagnostics = sink

    def unlink(real):  # noqa: ANN001, ANN202, ARG001
        async def failing(board_id: str, artifact_id: str) -> None:
            raise OSError("disk unavailable")
        return failing

    wrap_seam(stack, unlink=unlink)
    board_a, outcome = await switch_race(stack, board_b)
    assert outcome.relinked is True and outcome.board_id == board_a and outcome.also_linked_board_id == board_b
    assert await links_of(stack, outcome.artifact.artifact_id) == {board_a: "explicit", board_b: "active_board"}
    [(level, data)] = sink.of("core.upload.board_auto_link_remove_failed")
    assert level == "error" and data["auto_board_id"] == board_b and data["exception_type"] == "OSError"


async def test_replay_never_removes_auto_link(stack):
    """Un rejeu qui relie la cible ne retire aucun autre lien : il a pu être voulu entre-temps."""

    board_a = await active_board(stack)
    board_b = (await stack.core.boards.create({"title": "Projet B"})).board_id
    await stack.core.boards.switch(board_b)
    upload_id = str(uuid.uuid4())
    status, body, text = await drop_file(stack, board_b, "a.png", "image/png", PNG, upload_id=upload_id)
    assert status == 201, text
    artifact_id = body["artifact_id"]
    await stack.core.boards.switch(board_a)
    status, body, text = await drop_file(stack, board_a, "a.png", "image/png", PNG, upload_id=upload_id)
    assert status == 200, text
    assert body["replayed"] is True and body["relinked"] is True and body["also_linked_board_id"] is None
    assert await links_of(stack, artifact_id) == {board_b: "active_board", board_a: "explicit"}


async def test_url_inert_no_network(stack, monkeypatch):
    board = await active_board(stack)
    guard = NoOutboundNetwork(monkeypatch)
    status, body, text = await drop_link(stack, board)
    assert status == 201, text
    assert guard.attempts == []
    assert (body["kind"], body["url"], body["host"], body["state"]) == ("link", URL, "example.invalid", "complete")
    assert body["board_id"] == board and body["relinked"] is False and body["replayed"] is False
    assert body["also_linked_board_id"] is None
    artifact = await stack.core.artifacts.get(body["artifact_id"])
    assert artifact.kind is ArtifactKind.LINK and artifact.state is ArtifactState.COMPLETE
    assert artifact.text == URL and artifact.payload_ref is None and artifact.source == "board_drop"
    assert dict(artifact.metadata) == {"provenance": "board_drop", "host": "example.invalid",
                                       "client_upload_id": artifact.metadata["client_upload_id"]}
    assert not (stack.core.artifacts._payloads.root() / artifact.artifact_id).exists()
    listed = await board_artifacts(stack, board)
    assert listed[artifact.artifact_id]["preview"] == URL and listed[artifact.artifact_id]["kind"] == "link"
    trace = json.dumps(stack.trace(), ensure_ascii=False)
    assert "example.invalid" not in trace and "rapport?q" not in trace


@pytest.mark.parametrize("url", [
    "ftp://example.org/a", "javascript:alert(1)", "file:///C:/Windows/win.ini", "data:text/html,hi",
    "https://user:secret@example.org/", "https://user@example.org/", "https:///no-host", "https://exa mple.org/",
    "https://example.org/\x00", "https://example.org/\u202e", "https://example.org:99999/", "", "   ",
    "https://example.org/" + "a" * 2048, "example.org/no-scheme",
])
async def test_url_refused_schemes_and_credentials(stack, url):
    board = await active_board(stack)
    status, body, _ = await drop_link(stack, board, url)
    assert (status, body["code"], body["core_status"]) == (400, "link_invalid", 400)
    assert "secret" not in json.dumps(body)
    assert all(item.kind is not ArtifactKind.LINK
               for item in (await stack.core.artifacts.query(ArtifactQuery(limit=50))).items)


async def test_no_conversation_event_no_brain_turn(stack, monkeypatch):
    board = await active_board(stack)
    calls: list[str] = []

    async def no_turn(*args, **kwargs):  # noqa: ANN002, ANN003
        calls.append("brain")
        raise AssertionError("a board drop must never reach the Brain")

    for name in ("submit", "wake_for_work_attention", "wake_for_agenda"):
        monkeypatch.setattr(stack.core.brain, name, no_turn)
    before = await all_events(stack)
    conversations = (await stack.core.conversation_events.list_conversations(limit=100)).summaries
    binding = (await stack.core.sessions.current()).binding
    assert (await drop_file(stack, board, "a.pdf", "application/pdf", PDF))[0] == 201
    assert (await drop_file(stack, board, "b.png", "image/png", PNG))[0] == 201
    assert (await drop_link(stack, board))[0] == 201
    await asyncio.sleep(0.2)  # laisser passer tout écouteur différé (ledger, attention)
    assert calls == []
    assert await all_events(stack) == before
    assert (await stack.core.conversation_events.list_conversations(limit=100)).summaries == conversations
    assert (await stack.core.sessions.current()).binding == binding


async def test_duplicate_drop_idempotent(stack):
    board = await active_board(stack)
    upload_id = str(uuid.uuid4())
    first = await drop_file(stack, board, "a.png", "image/png", PNG, upload_id=upload_id)
    again = await drop_file(stack, board, "a.png", "image/png", PNG, upload_id=upload_id)
    assert (first[0], again[0], again[1]["replayed"]) == (201, 200, True)
    assert again[1]["artifact_id"] == first[1]["artifact_id"] == upload_artifact_id(upload_id)
    link_id = str(uuid.uuid4())
    one = await drop_link(stack, board, upload_id=link_id)
    two = await drop_link(stack, board, upload_id=link_id)
    other = await drop_link(stack, board, "https://example.invalid/autre", upload_id=link_id)
    assert (one[0], two[0], two[1]["replayed"], other[0], other[1]["code"]) == (201, 200, True, 409, "upload_conflict")
    crossed = await drop_file(stack, board, "a.png", "image/png", PNG, upload_id=link_id)
    assert (crossed[0], crossed[1]["code"]) == (409, "upload_conflict")
    listed = await board_artifacts(stack, board)
    assert set(listed) == {first[1]["artifact_id"], one[1]["artifact_id"]}


# ------------------------------------------------------------------ garde, persistance, A/B


async def test_a_chat_attachment_id_is_never_replayed_as_a_board_drop(stack):
    board = await active_board(stack)
    upload_id = str(uuid.uuid4())
    status, _, text = await stack.call("POST", "/api/chat/uploads", data=multipart(upload_id, "a.png", "image/png", PNG),
                                       headers=HEADERS)
    assert status == 201, text
    status, body, _ = await drop_file(stack, board, "a.png", "image/png", PNG, upload_id=upload_id)
    assert (status, body["code"]) == (409, "upload_conflict")


async def test_drops_stay_on_board_a_across_a_b_a(stack):
    board_a = await active_board(stack)
    board_b = (await stack.core.boards.create({"title": "Projet B"})).board_id
    pdf = (await drop_file(stack, board_a, "rapport.pdf", "application/pdf", PDF))[1]["artifact_id"]
    png = (await drop_file(stack, board_a, "photo.png", "image/png", PNG))[1]["artifact_id"]
    url = (await drop_link(stack, board_a))[1]["artifact_id"]
    await stack.core.boards.switch(board_b)
    assert set(await board_artifacts(stack, board_b)).isdisjoint({pdf, png, url})
    assert (await drop_link(stack, board_a))[1]["code"] == "board_drop_target_inactive"
    await stack.core.boards.switch(board_a)
    assert {pdf, png, url} <= set(await board_artifacts(stack, board_a))


@pytest.mark.parametrize("headers", [{"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"},
                                     {"Host": "evil.example"}])
async def test_the_drop_routes_are_guarded(stack, headers):
    board = await active_board(stack)
    status, body, _ = await stack.call("POST", f"/api/boards/drop?board_id={board}",
                                       data=multipart(str(uuid.uuid4()), "a.png", "image/png", PNG),
                                       headers={**HEADERS, **headers})
    assert (status, body["code"]) == (403, "forbidden_origin")
    status, body, _ = await stack.call("POST", "/api/boards/drop-link", headers=headers,
                                       json={"client_upload_id": str(uuid.uuid4()), "url": URL, "board_id": board})
    assert (status, body["code"]) == (403, "forbidden_origin")


@pytest.mark.parametrize("query", ["", "?board_id=", "?board_id=a&board_id=b", "?board_id=x&debug=1",
                                   "?board_id=" + "a" * 200])
async def test_the_drop_relay_wants_one_board_id(stack, query):
    status, body, _ = await stack.call("POST", "/api/boards/drop" + query,
                                       data=multipart(str(uuid.uuid4()), "a.png", "image/png", PNG), headers=HEADERS)
    assert (status, body["code"]) == (400, "invalid_request")


@pytest.mark.parametrize("body", [{"url": URL, "board_id": "default"},
                                  {"client_upload_id": "0b6c1f0e-1111", "url": 3, "board_id": "default"},
                                  {"client_upload_id": "0b6c1f0e-1111", "url": URL, "board_id": "default", "x": 1}])
async def test_the_link_relay_wants_a_closed_body(stack, body):
    status, answer, _ = await stack.call("POST", "/api/boards/drop-link", json=body)
    assert (status, answer["code"]) == (400, "invalid_request")


async def test_a_chat_upload_refuses_a_board_id(stack):
    with pytest.raises(Exception) as refused:
        await stack.core.uploads.put(client_upload_id=str(uuid.uuid4()), purpose="chat", board_id="default",
                                     agent=None, declared_mime=None, name_header="a.png", content_length=None,
                                     read=None)
    assert getattr(refused.value, "code", None) == "invalid_request"


def test_check_link_url_keeps_the_url_and_lowercases_the_host():
    assert check_link_url("  HTTPS://Example.ORG:8443/Chemin?x=1\r\n") == ("HTTPS://Example.ORG:8443/Chemin?x=1",
                                                                         "example.org")
    assert check_link_url("http://[::1]/a")[1] == "::1"
    with pytest.raises(LinkInvalid):
        check_link_url(None)


async def test_the_network_guard_bites(monkeypatch):
    """Le transport factice de `test_url_inert_no_network` échoue bien sur une sortie réelle (sinon il ne prouve rien)."""

    guard = NoOutboundNetwork(monkeypatch)
    with pytest.raises(pytest.fail.Exception):
        socket.getaddrinfo("example.invalid", 443)
    with pytest.raises(pytest.fail.Exception):
        await asyncio.get_running_loop().getaddrinfo("example.invalid", 443)
    assert guard.attempts == ["example.invalid", "example.invalid"]

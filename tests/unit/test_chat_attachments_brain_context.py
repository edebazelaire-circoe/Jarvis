"""Pièces jointes d'un tour écrit jusqu'au brief du cerveau (chat Slice 07, `docs/chat.md` › *Attachments*).

Core réel derrière le vrai `LocalProtocolServer` (harnais de
`test_chat_text_ingress.py`), backend qui garde le contexte que l'adaptateur
du Control Center enverrait ; le brief est rendu par `build_agent_brief`. Le
chemin absolu d'une pièce va au brief, jamais dans une réponse HTTP vers le
navigateur ni dans un événement.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
import uuid

import pytest

from jarvis.adapters.control_center_brain import _turn_context
from jarvis.core.upload_service import screenshot_attachment_name
from jarvis.domain.artifacts import ArtifactKind
from jarvis.domain.conversation_events import ConversationEventType as T, encode_conversation_event
from jarvis.runtime.attachments_brief import BRIEF_ATTACHMENTS_HEADER, with_agent_readability
from jarvis.runtime.control_center import ControlCenter, build_agent_brief
from tests.unit.test_chat_text_ingress import RecordingBackend, close_stack, open_stack, voice_absent

PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4
PDF = b"%PDF-1.4\n" + b"0" * 2000 + b"\n%%EOF\n"
ZIP = b"PK\x03\x04" + b"\x00" * 3000


class AttachmentsBackend(RecordingBackend):
    async def run_turn_with_context(self, turn, context, emit):
        result = await super().run_turn_with_context(turn, context, emit)
        self.contexts[-1] = _turn_context(turn, context.state, context.work, context.interruptions,
                                          context.pending_replies, board=context.board,
                                          session_context=context.session_context,
                                          prefab_events=context.prefab_events, presentation=context.presentation,
                                          memory=context.memory, attachments=context.attachments)
        return result


class Body:
    def __init__(self, data: bytes) -> None:
        self.data = data

    async def read(self, n: int) -> bytes:
        chunk, self.data = self.data[:n], self.data[n:]
        return chunk


@pytest.fixture
async def stack(tmp_path):
    opened, server = await open_stack(tmp_path, AttachmentsBackend())
    voice_absent(opened.core)
    try:
        yield opened
    finally:
        await close_stack(opened, server)


async def attach(stack, data: bytes, name: str) -> str:
    outcome = await stack.core.uploads.put(client_upload_id=str(uuid.uuid4()), purpose="chat", agent="claude",
                                           declared_mime=None, name_header=name, content_length=len(data),
                                           read=Body(data).read)
    return outcome.artifact.artifact_id


async def test_attachments_reach_the_brief_as_data_with_their_paths(stack):
    conversation_id = await stack.foreground()
    ids = [await attach(stack, PDF, "rapport.pdf"), await attach(stack, PNG, "photo.png"),
           await attach(stack, ZIP, "archive.zip")]
    status, body, correlation_id = await stack.send(conversation_id, "Résume ces fichiers", attachments=ids)
    assert status == 202, body
    await stack.settle()
    [turn] = stack.backend.calls
    assert turn.attachments == tuple(ids)
    context = stack.backend.contexts[-1]
    root = stack.core.artifacts._payloads.root()
    assert context["attachments"]["artifacts_root"] == str(root)
    items = context["attachments"]["items"]
    assert [item["artifact_id"] for item in items] == ids
    assert [item["mime_type"] for item in items] == ["application/pdf", "image/png", "application/octet-stream"]
    assert [Path(item["path"]).name for item in items] == ["upload.pdf", "upload.png", "upload.zip"]
    assert all(Path(item["path"]).is_absolute() and Path(item["path"]).is_file() for item in items)
    brief = build_agent_brief(with_agent_readability(context, "claude"), "Résume ces fichiers")
    block = brief[brief.index(BRIEF_ATTACHMENTS_HEADER):brief.index("[Demande]")]
    assert f"« rapport.pdf » (application/pdf, 2,0 Ko) : lisible avec Read → {items[0]['path']}" in block
    assert f"« photo.png » (image/png, 1,0 Ko) : lisible avec Read → {items[1]['path']}" in block
    assert "« archive.zip » (application/octet-stream, 2,9 Ko) : format non lisible par toi" in block
    assert items[2]["path"] not in block, "an unreadable file is not handed to the CLI"
    # Codex ne lit rien : rien n'est annoncé lisible, aucun chemin donné.
    codex = build_agent_brief(with_agent_readability(context, "codex"), "x")
    assert "lisible avec Read" not in codex and codex.count("format non lisible par toi") == 3
    # Rien de cela vers le navigateur ni dans un événement : seulement le nombre de pièces.
    assert str(root) not in json.dumps(body) and not any(i in json.dumps(body) for i in ids)
    events = await stack.events(conversation_id)
    [accepted] = [event for event in events if event.event_type is T.USER_TRANSCRIPT_ACCEPTED]
    assert accepted.attributes["attachment_count"] == 3
    dumped = json.dumps([encode_conversation_event(event) for event in events], ensure_ascii=False)
    assert str(root) not in dumped and "upload." not in dumped
    assert not any(i in dumped for i in ids) and "rapport.pdf" not in dumped
    record = await stack.core.brain.admitted_turn(conversation_id, correlation_id)
    assert record.metadata["attachments"] == ids


async def test_turn_without_attachments_keeps_its_context_and_brief_byte_for_byte(stack):
    conversation_id = await stack.foreground()
    assert (await stack.send(conversation_id, "Bonjour"))[0] == 202
    await stack.settle()
    context = stack.backend.contexts[-1]
    assert "attachments" not in context and with_agent_readability(context, "claude") is context
    assert BRIEF_ATTACHMENTS_HEADER not in build_agent_brief(context, "Bonjour")
    events = await stack.events(conversation_id)
    [accepted] = [event for event in events if event.event_type is T.USER_TRANSCRIPT_ACCEPTED]
    assert "attachment_count" not in accepted.attributes


async def test_an_attachment_deleted_after_admission_is_said_unavailable(stack):
    conversation_id = await stack.foreground()
    artifact_id = await attach(stack, PNG, "photo.png")
    turn = type("Turn", (), {"attachments": (artifact_id,), "correlation_id": "chat:x"})()
    await stack.core.artifacts.delete(artifact_id)
    block = await stack.core.uploads.brain_attachments(turn)
    [item] = block.items
    assert (item.path, item.brain_readable) == (None, False)
    brief = build_agent_brief({"addressing": "addressed", "attachments": block.to_payload()}, "x")
    assert "pièce indisponible" in brief and conversation_id


async def test_unknown_foreign_pending_and_other_kind_attachments_are_refused(stack):
    conversation_id = await stack.foreground()
    session = (await stack.core.sessions.current()).session
    pending = await stack.core.artifacts.create(kind=ArtifactKind.UPLOAD, source="chat",
                                                jarvis_session_id=session.jarvis_session_id,
                                                payload_name="upload.png", metadata={"provenance": "chat_attachment"})
    # Une autre nature que pièce jointe ou capture d'écran (Slice 05 admet `screenshot`) : refusée.
    recording = await stack.core.artifacts.create(kind=ArtifactKind.SCREEN_RECORDING, source="test",
                                                  jarvis_session_id=session.jarvis_session_id,
                                                  payload_name="screen.mp4")
    good = await attach(stack, PNG, "ok.png")
    cases = [
        ([good, "jart_" + "a" * 32], 404, "attachment_not_found"),
        ([pending.artifact_id], 409, "attachment_not_ready"),
        ([recording.artifact_id], 400, "attachment_not_allowed"),
        ([good, good], 400, "invalid_request"),
        (["not-an-id"], 400, "invalid_request"),
        ([f"jart_{i:032x}" for i in range(11)], 400, "too_many_attachments"),
    ]
    for attachments, status, code in cases:
        got, body, _ = await stack.send(conversation_id, attachments=attachments)
        assert (got, body["error"]["code"]) == (status, code), attachments
    await stack.settle()
    assert stack.backend.calls == []


async def test_an_attachment_of_another_session_is_not_allowed(stack):
    old = await attach(stack, PNG, "ancienne.png")
    await stack.core.sessions.start_new_session()
    conversation_id = await stack.foreground()
    status, body, _ = await stack.send(conversation_id, attachments=[old])
    assert (status, body["error"]["code"]) == (400, "attachment_not_allowed")


async def test_an_attachment_of_another_board_is_refused_and_the_replay_still_answers(stack):
    """Constat 1 de la Slice 09 : la garde est de Core, pas de la page (`stale`). Une pièce jointe liée au Board A
    ne part pas d'un tour du Board B, même Session ; le rejeu du tour admis sur A reste un doublon 200."""

    conv_a = await stack.foreground()
    board_a = (await stack.core.sessions.current()).session.active_board_id
    on_a = await attach(stack, PNG, "seulement-a.png")
    request_id = str(uuid.uuid4())
    assert (await stack.send(conv_a, "Voici", request_id=request_id, attachments=[on_a]))[0] == 202
    await stack.settle()
    board_b = (await stack.core.boards.create({"title": "Projet B"})).board_id
    await stack.core.boards.switch(board_b)
    conv_b = await stack.foreground()
    assert conv_b != conv_a
    status, body, _ = await stack.send(conv_b, "Et celle-ci ?", attachments=[on_a])
    assert (status, body["error"]["code"]) == (409, "attachment_other_board"), body
    assert on_a in body["error"]["message"] and "seulement-a" not in json.dumps(body)
    on_b = await attach(stack, PNG, "pour-b.png")
    assert (await stack.send(conv_b, "Et celle-là", attachments=[on_b]))[0] == 202
    await stack.settle()
    assert [(t.conversation_id, t.attachments) for t in stack.backend.calls] == [(conv_a, (on_a,)), (conv_b, (on_b,))]
    # Le même tour de A rejoué (même id, même pièce), B affiché puis A de retour : le doublon, jamais un refus.
    for board in (None, board_a):
        if board is not None:
            await stack.core.boards.switch(board)
        status, body, _ = await stack.send(conv_a, "Voici", request_id=request_id, attachments=[on_a])
        assert (status, body.get("duplicate")) == (200, True), body
    await stack.settle()
    assert len(stack.backend.calls) == 2


# ------------------------------------------------------------------ « Envoyer à Jarvis » (orbital-ui Slice 05, D7)


async def screenshot(stack, *, session_id: str | None = "current", complete: bool = True) -> str:
    """Une capture d'écran du registre, comme `CaptureService.screenshot` la laisse : aucun écran lu."""

    if session_id == "current":
        session_id = (await stack.core.sessions.current()).session.jarvis_session_id
    shot = await stack.core.artifacts.create(kind=ArtifactKind.SCREENSHOT, source="capture.screen",
                                             jarvis_session_id=session_id, payload_name="screenshot.png",
                                             mime_type="image/png", metadata={"capture_id": None, "device": None})
    if complete:
        await stack.core.artifacts.store_payload(shot.artifact_id, PNG, width=1, height=1)
    return shot.artifact_id


async def test_screenshot_of_open_session_is_admitted(stack):
    """Une capture `complete` de la Session ouverte accompagne un message écrit ; le cerveau reçoit le
    chemin de SON payload (aucune copie), comme un fichier joint, et le Control Center la dit lisible."""

    conversation_id = await stack.foreground()
    shot = await screenshot(stack)
    before = await stack.core.artifacts.get(shot)
    status, body, _ = await stack.send(conversation_id, "Que vois-tu sur cette capture ?", attachments=[shot])
    assert status == 202, body
    await stack.settle()
    [turn] = stack.backend.calls
    assert turn.attachments == (shot,)
    [item] = stack.backend.contexts[-1]["attachments"]["items"]
    payload = stack.core.artifacts.payload_path(before)
    # Le nom que montre la pièce du Chat : l'heure locale de la capture (QA S05, polish 2).
    name = f"Capture d’écran {before.created_at.astimezone():%H-%M-%S}.png"
    assert (item["artifact_id"], item["original_name"], item["mime_type"], item["path"]) == (
        shot, name, "image/png", payload), "le chemin du payload de la capture, jamais une copie"
    brief = build_agent_brief(with_agent_readability(stack.backend.contexts[-1], "claude"), "Que vois-tu ?")
    block = brief[brief.index(BRIEF_ATTACHMENTS_HEADER):brief.index("[Demande]")]
    assert block.splitlines()[1] == f"- « {name} » (image/png, 1,0 Ko) : lisible avec Read → {payload}"
    after = await stack.core.artifacts.get(shot)
    assert (after.state, after.size_bytes, after.metadata, after.kind) == (
        before.state, before.size_bytes, before.metadata, before.kind), "la capture n'est pas modifiée"
    assert str(Path(payload).parent) not in json.dumps(body), "aucun chemin vers le navigateur"


async def test_screenshot_names_follow_the_capture_clock_and_mark_annotations(stack):
    """QA S05, polish 2 : deux captures d'un même message ne s'appellent plus toutes deux
    « capture d’écran.png » ; le nom est celui de la pièce du Chat (heure locale de la capture)."""

    shot = await stack.core.artifacts.get(await screenshot(stack))
    clock = f"{shot.created_at.astimezone():%H-%M-%S}"
    assert screenshot_attachment_name(shot) == f"Capture d’écran {clock}.png"
    assert screenshot_attachment_name(dataclasses.replace(shot, source="annotation")) == f"Capture d’écran {clock} annotée.png"


async def test_screenshot_of_other_session_is_refused(stack):
    old = await screenshot(stack)
    await stack.core.sessions.start_new_session()
    conversation_id = await stack.foreground()
    status, body, _ = await stack.send(conversation_id, "Et celle-ci ?", attachments=[old])
    assert (status, body["error"]["code"]) == (400, "attachment_not_allowed")
    # Sans Session (aucune association) : pas de la Session ouverte non plus.
    loose = await screenshot(stack, session_id=None)
    status, body, _ = await stack.send(conversation_id, "Et celle-là ?", attachments=[loose])
    assert (status, body["error"]["code"]) == (400, "attachment_not_allowed")
    await stack.settle()
    assert stack.backend.calls == []


async def test_non_complete_screenshot_refused(stack):
    conversation_id = await stack.foreground()
    pending = await screenshot(stack, complete=False)
    failed = await screenshot(stack, complete=False)
    await stack.core.artifacts.fail(failed, error_code="source_unavailable")
    for artifact_id in (pending, failed):
        status, body, _ = await stack.send(conversation_id, "Regarde", attachments=[artifact_id])
        assert (status, body["error"]["code"]) == (409, "attachment_not_ready"), artifact_id
    await stack.settle()
    assert stack.backend.calls == []


async def test_replay_compares_the_attachments(stack):
    conversation_id = await stack.foreground()
    first, second = await attach(stack, PNG, "a.png"), await attach(stack, PDF, "b.pdf")
    request_id = str(uuid.uuid4())
    assert (await stack.send(conversation_id, "Voici", request_id=request_id, attachments=[first]))[0] == 202
    assert (await stack.send(conversation_id, "Voici", request_id=request_id, attachments=[first]))[0] == 200
    status, body, _ = await stack.send(conversation_id, "Voici", request_id=request_id, attachments=[first, second])
    assert (status, body["error"]["code"]) == (409, "chat_request_conflict")
    await stack.settle()
    assert len(stack.backend.calls) == 1


async def test_attachments_on_a_voice_turn_are_refused(stack):
    conversation_id = await stack.foreground()
    good = await attach(stack, PNG, "a.png")
    status, body, _ = await stack.send(conversation_id, source="realtime", attachments=[good])
    assert (status, body["error"]["code"]) == (400, "invalid_request")


async def test_the_session_payload_names_artifacts_root(stack):
    payload = await stack.core.sessions.context_brief_payload()
    assert payload["artifacts_root"] == str(stack.core.artifacts._payloads.root())


# ------------------------------------------------------------------ `--add-dir` au Control Center


class FakeAgent:
    def __init__(self, launched: tuple[Path, ...]) -> None:
        self.add_dirs: tuple[Path, ...] = ()
        self.launched_add_dirs = launched
        self.requested_add_dirs = launched
        self.state = "running"


def test_artifacts_root_is_granted_like_sessions_root(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    center = ControlCenter(runtime_root=runtime, project_root=tmp_path)
    sessions, artifacts = tmp_path / "data" / "sessions", tmp_path / "data" / "artifacts"
    center._learn_sessions_root(sessions, source="test")
    center._learn_artifacts_root(artifacts, source="test")
    assert center._granted_dirs() == (sessions,), "a missing folder is never passed to --add-dir"
    artifacts.mkdir(parents=True)
    center._learn_artifacts_root(artifacts, source="test")
    assert center._granted_dirs() == (sessions, artifacts)
    assert all(agent.add_dirs == (sessions, artifacts)
               for entry in center.board_brains.entries() for agent in entry.agents.values()
               if hasattr(agent, "add_dirs"))
    assert center._lacks_workspace_grant(FakeAgent((sessions,))) is True
    assert center._lacks_workspace_grant(FakeAgent((sessions, artifacts))) is False

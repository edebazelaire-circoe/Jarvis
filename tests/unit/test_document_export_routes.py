"""`/v1/exports*` sur un vrai Core (registre, Studio, paquet réels ; faux runner de rendu) — presentation-edition-v1 Slice 03.

Le dossier Documents est simulé sous `tmp_path` (résolveur injecté) : jamais le vrai dossier de l'utilisateur.
"""

from __future__ import annotations

import hashlib
import socket

import pytest

from jarvis.adapters.export_destination import ExportDestination
from jarvis.adapters.file_local_capability_store import FileLocalCapabilityStore
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.protocol.client import LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer
from tests.fakes.remotion_render import FakeRenderRunner
from tests.unit.test_local_capability_host import FakeRunner
from tests.unit.test_presentation_render_routes import JOBS, TOKEN, call, frozen, ready, until_done


class Stack:
    pass


class Sink:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None, **_):  # noqa: ANN001
        self.events.append((kind, level, dict(data or {})))


@pytest.fixture
async def stack(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    s = Stack()
    s.data = tmp_path / "data"
    s.docs = tmp_path / "home" / "Documents"
    s.docs.mkdir(parents=True)
    s.sink = Sink()
    s.render = FakeRenderRunner(tmp_path)
    s.core = JarvisCoreApplication(data_root=s.data, local_capability_runner=FakeRunner(),
                                   local_capability_store=FileLocalCapabilityStore(s.data.resolve()),
                                   remotion_render_runner=s.render, diagnostics=s.sink,
                                   export_destination=ExportDestination(forbidden=(s.data,), documents=lambda: s.docs))
    await s.core.start()
    s.server = LocalProtocolServer(s.core, host="127.0.0.1", port=port, token=TOKEN)
    await s.server.start()
    s.client = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
    s.base = f"http://127.0.0.1:{port}"
    try:
        yield s
    finally:
        await s.client.close()
        await s.server.stop()
        await s.core.stop()


async def rendered(stack, fmt, settings=None, suffix="1"):
    snapshot, pid, vid, _ = await frozen(stack, suffix)
    status, body = await call(stack.base, "POST", JOBS, json={"snapshot_id": snapshot, "format": fmt, "settings": settings or {}})
    assert status == 202, body
    job = await until_done(stack.base, body["job"]["job_id"])
    assert job["state"] == "complete", job
    return job["artifact_id"], snapshot, pid


def tree(folder):
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")) if folder.exists() else []


# ------------------------------------------------------------------ authoring n'écrit rien chez l'utilisateur


async def test_authoring_freezing_and_rendering_write_nothing_into_documents(stack):
    await ready(stack)
    await rendered(stack, "mp4", {"frame_end": 29})
    await rendered(stack, "still", suffix="2")
    await rendered(stack, "pdf", {"frames": [0, 10]}, suffix="3")
    status, body = await call(stack.base, "GET", "/v1/exports/root")
    assert status == 200 and body["root"] == {"available": True, "root": "Documents\\Jarvis", "exists": False}
    assert tree(stack.docs) == [], "no working document, render or draft appears in Documents without an explicit export"


# ------------------------------------------------------------------ export par classe existante


@pytest.mark.parametrize("fmt, settings, ext", [("mp4", {"frame_end": 29}, ".mp4"), ("still", {}, ".png"),
                                                ("pdf", {"frames": [0, 5]}, ".pdf")])
async def test_each_existing_class_is_exported_as_a_copy_named_after_the_presentation(stack, fmt, settings, ext):
    await ready(stack)
    artifact_id, _, _ = await rendered(stack, fmt, settings)
    internal = stack.core.artifacts.payload_path(await stack.core.artifacts.get(artifact_id))
    before = open(internal, "rb").read()
    status, body = await call(stack.base, "POST", "/v1/exports", json={"artifact_id": artifact_id})
    assert status == 201, body
    exported = body["export"]
    label = {"mp4": "video", "still": "image", "pdf": "pdf"}[fmt]
    assert exported["file_name"] == f"Atelier - {label}{ext}" and exported["copy"] is True and exported["renamed"] is False
    assert exported["destination"] == {"root": "Documents\\Jarvis", "display_path": f"Documents\\Jarvis\\Atelier - {label}{ext}"}
    copy = stack.docs / "Jarvis" / exported["file_name"]
    assert copy.read_bytes() == before and exported["sha256"] == hashlib.sha256(before).hexdigest()
    assert open(internal, "rb").read() == before, "the canonical payload is untouched"
    assert str(stack.docs) not in str(body), "the answer never names the user's absolute path"
    kinds = [(k, lvl, d.get("file_name")) for k, lvl, d in stack.sink.events if k.startswith("core.export.")]
    assert kinds == [("core.export.completed", "info", exported["file_name"])]


async def test_deleting_the_exported_copy_then_exporting_again_works_from_internal_state(stack):
    await ready(stack)
    artifact_id, _, pid = await rendered(stack, "still")
    status, first = await call(stack.base, "POST", "/v1/exports", json={"artifact_id": artifact_id, "file_name": "Mon export"})
    assert status == 201 and first["export"]["file_name"] == "Mon export.png"
    (stack.docs / "Jarvis" / "Mon export.png").unlink()
    (stack.docs / "Jarvis").rmdir()  # even the whole export folder may go
    view = await stack.core.presentation_studio.get(pid)
    assert view.presentation.title == "Atelier", "the presentation still opens"
    derived = await stack.core.artifacts.get(artifact_id)
    assert derived.state.value == "complete" and "export" not in str(dict(derived.metadata)).lower()
    status, again = await call(stack.base, "POST", "/v1/exports", json={"artifact_id": artifact_id, "file_name": "Mon export"})
    assert status == 201 and again["export"]["file_name"] == "Mon export.png"
    assert again["export"]["sha256"] == first["export"]["sha256"]
    status, third = await call(stack.base, "POST", "/v1/exports", json={"artifact_id": artifact_id, "file_name": "Mon export"})
    assert status == 201 and third["export"]["file_name"] == "Mon export (2).png" and third["export"]["renamed"] is True


async def test_a_renamed_or_moved_export_never_matters_to_jarvis(stack):
    await ready(stack)
    artifact_id, _, _ = await rendered(stack, "mp4", {"frame_end": 29})
    status, body = await call(stack.base, "POST", "/v1/exports", json={"artifact_id": artifact_id})
    assert status == 201
    (stack.docs / "Jarvis" / body["export"]["file_name"]).rename(stack.docs / "moved.mp4")
    status, again = await call(stack.base, "POST", "/v1/exports", json={"artifact_id": artifact_id})
    assert status == 201 and again["export"]["file_name"] == body["export"]["file_name"]


# ------------------------------------------------------------------ refus


@pytest.mark.parametrize("body, status, code", [
    ({}, 400, "export_invalid"),
    ({"artifact_id": ""}, 400, "export_invalid"),
    ({"artifact_id": 12}, 400, "export_invalid"),
    ({"artifact_id": "jart_x", "path": "C:\\Users\\x\\Desktop\\out.txt"}, 400, "export_invalid"),
    ({"artifact_id": "jart_x", "source": "C:\\Windows\\win.ini"}, 400, "export_invalid"),
    ({"artifact_id": "jart_x", "destination": "C:\\"}, 400, "export_invalid"),
    ({"artifact_id": "jart_x", "actor": "root"}, 400, "export_invalid"),
    ({"artifact_id": "C:\\Windows\\win.ini"}, 404, "export_source_not_found"),
    ({"artifact_id": "jart_does_not_exist0000"}, 404, "export_source_not_found"),
])
async def test_an_arbitrary_source_or_destination_is_refused(stack, body, status, code):
    got, answer = await call(stack.base, "POST", "/v1/exports", json=body)
    assert (got, answer["error"]["code"]) == (status, code), answer
    assert tree(stack.docs) == []


async def test_internal_artifacts_are_not_exportable(stack):
    await ready(stack)
    _, snapshot, _ = await rendered(stack, "still")
    status, body = await call(stack.base, "POST", "/v1/exports", json={"artifact_id": snapshot})
    assert status == 409 and body["error"]["code"] == "export_source_not_exportable"
    assert tree(stack.docs) == []
    refused = [(k, lvl) for k, lvl, _ in stack.sink.events if k.startswith("core.export.")]
    assert refused == [("core.export.refused", "warning")]


async def test_a_pending_render_is_not_exportable(stack):
    await ready(stack)
    snapshot, _, _, _ = await frozen(stack)
    pending = await stack.core.presentation_artifacts.begin_render(snapshot, "still")
    status, body = await call(stack.base, "POST", "/v1/exports", json={"artifact_id": pending.artifact_id})
    assert status == 409 and body["error"]["code"] == "export_source_not_exportable"


async def test_a_tampered_canonical_payload_is_refused_and_nothing_is_kept(stack):
    await ready(stack)
    artifact_id, _, _ = await rendered(stack, "still")
    internal = stack.core.artifacts.payload_path(await stack.core.artifacts.get(artifact_id))
    data = bytearray(open(internal, "rb").read())
    data[-1] ^= 0xFF
    open(internal, "wb").write(bytes(data))
    status, body = await call(stack.base, "POST", "/v1/exports", json={"artifact_id": artifact_id})
    assert status == 409 and body["error"]["code"] == "export_source_unavailable"
    assert tree(stack.docs / "Jarvis") == []


async def test_the_routes_need_the_core_token_and_refuse_queries(stack):
    for method, path in (("GET", "/v1/exports/root"), ("POST", "/v1/exports")):
        status, _ = await call(stack.base, method, path, token="wrong" * 10)
        assert status == 401
    status, body = await call(stack.base, "GET", "/v1/exports/root?path=C:\\")
    assert status == 400 and body["error"]["code"] == "export_invalid"


async def test_a_core_without_override_uses_the_environment_and_never_touches_documents_at_start(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_EXPORT_ROOT", str(tmp_path / "exports"))
    core = JarvisCoreApplication(data_root=tmp_path / "data")
    await core.start()
    try:
        assert core.document_export.root() == {"available": True, "root": "JARVIS_EXPORT_ROOT", "exists": False}
        assert not (tmp_path / "exports").exists()
    finally:
        await core.stop()


async def test_the_typed_client_exports_for_the_brain_with_the_id_alone(stack):
    await ready(stack)
    artifact_id, _, _ = await rendered(stack, "pdf", {"frames": [0]})
    answer = await stack.client.document_export(artifact_id)
    assert answer["export"]["file_name"] == "Atelier - pdf.pdf"
    actors = [d.get("actor") for k, _, d in stack.sink.events if k == "core.export.completed"]
    assert actors == ["brain"]

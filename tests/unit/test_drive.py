from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.adapters.google_drive import GoogleDriveBackend
from jarvis.core.drive_service import DriveService, DriveUnavailableError
from jarvis.core.v2_tools import CoreToolRouter
from jarvis.domain.drive import FOLDER_MIME, DriveContent, DriveFile, DriveQuery
from jarvis.security.v2_policy import ActionDisposition, V2ActionBroker


class _Call:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class _Files:
    def __init__(self, store: dict[str, dict], log: list[tuple[str, dict]]):
        self.store = store
        self.log = log

    def list(self, **kwargs):
        self.log.append(("list", kwargs))
        return _Call({"files": list(self.store.values())})

    def get(self, *, fileId, **kwargs):
        self.log.append(("get", {"fileId": fileId, **kwargs}))
        if fileId not in self.store:
            raise _HttpError(404)
        return _Call(self.store[fileId])

    def create(self, *, body, media_body=None, **kwargs):
        self.log.append(("create", {"body": body, **kwargs}))
        item = {"id": f"id-{len(self.store) + 1}", "name": body["name"], "mimeType": body.get("mimeType", "text/plain"), "parents": body.get("parents", [])}
        self.store[item["id"]] = item
        return _Call(item)

    def update(self, *, fileId, body=None, media_body=None, **kwargs):
        self.log.append(("update", {"fileId": fileId, "body": body, **kwargs}))
        item = dict(self.store[fileId])
        item.update(body or {})
        self.store[fileId] = item
        return _Call(item)


class _Permissions:
    def __init__(self, log: list[tuple[str, dict]]):
        self.log = log

    def create(self, **kwargs):
        self.log.append(("permission", kwargs))
        return _Call({"id": "perm-1"})


class _Service:
    def __init__(self, store: dict[str, dict] | None = None):
        self.store = store if store is not None else {}
        self.log: list[tuple[str, dict]] = []

    def files(self):
        return _Files(self.store, self.log)

    def permissions(self):
        return _Permissions(self.log)


class _Resp:
    def __init__(self, status: int):
        self.status = status


class _HttpError(Exception):
    def __init__(self, status: int):
        super().__init__(f"http {status}")
        self.resp = _Resp(status)


def _backend(store: dict[str, dict] | None = None) -> tuple[GoogleDriveBackend, _Service]:
    service = _Service(store)
    return GoogleDriveBackend(service), service


@pytest.mark.asyncio
async def test_list_reaches_shared_drives_and_maps_fields():
    backend, service = _backend({"a": {"id": "a", "name": "Notes", "mimeType": "text/plain", "size": "12", "modifiedTime": "2026-09-01T10:00:00Z", "parents": ["root"], "webViewLink": "https://drive/a"}})
    files = await backend.list_files(DriveQuery(limit=5))
    assert [f.name for f in files] == ["Notes"]
    assert files[0].size == 12 and files[0].modified_at is not None and files[0].parents == ("root",)
    kind, params = service.log[0]
    # Sans ces deux drapeaux les Drive partages remontent vides.
    assert kind == "list" and params["supportsAllDrives"] and params["includeItemsFromAllDrives"]


@pytest.mark.asyncio
async def test_missing_file_is_none_not_an_error():
    backend, _ = _backend()
    assert await backend.get_file("absent") is None


def test_query_escapes_quotes_and_excludes_trash():
    q = GoogleDriveBackend._q(DriveQuery(text="rapport d'audit", limit=5))
    assert "trashed = false" in q
    # Une apostrophe non echappee terminerait la chaine et changerait la requete.
    assert "d\\'audit" in q


def test_query_filters_combine():
    q = GoogleDriveBackend._q(DriveQuery(text="x", parent_id="folder1", mime_type=FOLDER_MIME, limit=5))
    assert "'folder1' in parents" in q and f"mimeType = '{FOLDER_MIME}'" in q


def test_blank_text_and_out_of_range_limit_are_rejected():
    with pytest.raises(ValueError):
        DriveQuery(text="   ")
    with pytest.raises(ValueError):
        DriveQuery(limit=0)
    with pytest.raises(ValueError):
        DriveQuery(limit=500)


@pytest.mark.asyncio
async def test_delete_trashes_instead_of_erasing():
    backend, service = _backend({"a": {"id": "a", "name": "Notes", "mimeType": "text/plain"}})
    await backend.delete_file("a", idempotency_key="k1")
    kind, params = service.log[-1]
    assert kind == "update" and params["body"] == {"trashed": True}


@pytest.mark.asyncio
async def test_writes_are_idempotent():
    backend, service = _backend()
    first = await backend.create_file("a.txt", content="x", mime_type="text/plain", parent_id=None, idempotency_key="same")
    second = await backend.create_file("b.txt", content="y", mime_type="text/plain", parent_id=None, idempotency_key="same")
    assert first.id == second.id
    assert len([entry for entry in service.log if entry[0] == "create"]) == 1


@pytest.mark.asyncio
async def test_native_documents_cannot_be_overwritten_by_raw_upload():
    backend, _ = _backend({"doc": {"id": "doc", "name": "Plan", "mimeType": "application/vnd.google-apps.document"}})
    with pytest.raises(ValueError):
        await backend.update_file("doc", content="texte", idempotency_key="k")


@pytest.mark.asyncio
async def test_share_rejects_unknown_role():
    backend, _ = _backend({"a": {"id": "a", "name": "Notes", "mimeType": "text/plain"}})
    with pytest.raises(ValueError):
        await backend.share_file("a", email="x@example.com", role="owner", idempotency_key="k")


@pytest.mark.asyncio
async def test_read_exports_native_documents():
    backend, _ = _backend({"doc": {"id": "doc", "name": "Plan", "mimeType": "application/vnd.google-apps.document"}})
    seen: dict[str, str] = {}

    def _fake_download(file_id: str, export_as: str) -> bytes:
        seen["export_as"] = export_as
        return b"# Plan"

    backend._download = _fake_download  # type: ignore[method-assign]
    content = await backend.read_file("doc", max_chars=3)
    assert seen["export_as"] == "text/markdown"
    assert content.text == "# P" and content.truncated is True


def test_service_without_backend_reports_unavailable():
    service = DriveService()
    assert service.available is False
    assert service.storage["persisted"] is False
    with pytest.raises(DriveUnavailableError):
        service._require()


def test_policy_confirms_every_drive_write():
    broker = V2ActionBroker()
    for name in ("drive_search", "drive_get", "drive_read"):
        assert broker.evaluate(name, explicit_request=True, ambiguous=False) is ActionDisposition.EXECUTE
    for name in ("drive_create", "drive_update", "drive_delete", "drive_share"):
        assert broker.evaluate(name, explicit_request=True, ambiguous=False) is ActionDisposition.CONFIRM


class _StubScheduler:
    pass


class _StubCalendar:
    storage = {"backend": "stub", "persisted": False}


def _router(drive: DriveService) -> CoreToolRouter:
    return CoreToolRouter(scheduler=_StubScheduler(), calendar=_StubCalendar(), drive=drive)


@pytest.mark.asyncio
async def test_router_denies_drive_when_not_configured():
    router = _router(DriveService())
    result = await router.call("drive_search", {"text": "notes"}, conversation_id=None)
    assert result["executed"] is False and result["disposition"] == "deny"
    assert "Drive" in str(result["message"])


@pytest.mark.asyncio
async def test_router_search_reports_the_backend_it_used():
    backend, _ = _backend({"a": {"id": "a", "name": "Notes", "mimeType": "text/plain"}})
    router = _router(DriveService(backend))
    result = await router.call("drive_search", {"text": "Notes"}, conversation_id=None)
    assert result["executed"] is True
    assert [f["name"] for f in result["files"]] == ["Notes"]
    assert result["drive"] == {"backend": "google", "persisted": True}


@pytest.mark.asyncio
async def test_router_requires_confirmation_before_trashing():
    backend, service = _backend({"a": {"id": "a", "name": "Notes", "mimeType": "text/plain"}})
    router = _router(DriveService(backend))
    pending = await router.call("drive_delete", {"file_id": "a"}, conversation_id=None)
    assert pending["disposition"] == "confirm" and pending["executed"] is False
    assert not [entry for entry in service.log if entry[0] == "update"]

    refused = await router.resolve_confirmation(str(pending["action_id"]), "non")
    assert refused["executed"] is False
    assert not [entry for entry in service.log if entry[0] == "update"]

    pending = await router.call("drive_delete", {"file_id": "a"}, conversation_id=None)
    done = await router.resolve_confirmation(str(pending["action_id"]), "oui")
    assert done["executed"] is True and done["trashed_file_id"] == "a"


@pytest.mark.asyncio
async def test_router_clarifies_incomplete_drive_calls():
    backend, _ = _backend()
    router = _router(DriveService(backend))
    result = await router.call("drive_read", {}, conversation_id=None)
    assert result["disposition"] == "clarify" and result["executed"] is False


@pytest.mark.asyncio
async def test_router_rejects_a_share_without_an_email_address():
    backend, _ = _backend({"a": {"id": "a", "name": "Notes", "mimeType": "text/plain"}})
    router = _router(DriveService(backend))
    pending = await router.call("drive_share", {"file_id": "a", "email": "pas-une-adresse"}, conversation_id=None)
    with pytest.raises(ValueError):
        await router.resolve_confirmation(str(pending["action_id"]), "oui")


def test_realtime_tools_expose_the_drive_surface():
    from jarvis.runtime.realtime_tools import REALTIME_TOOLS

    names = {tool["name"] for tool in REALTIME_TOOLS}
    assert {"drive_search", "drive_get", "drive_read", "drive_create", "drive_update", "drive_delete", "drive_share"} <= names


def test_mcp_server_exposes_the_same_tools():
    import asyncio

    from jarvis.runtime.drive_mcp import build_server

    tools = asyncio.run(build_server().list_tools())
    assert {tool.name for tool in tools} == {"drive_search", "drive_get", "drive_read", "drive_create", "drive_update", "drive_delete", "drive_share"}


def test_mcp_refuses_to_start_an_interactive_flow(monkeypatch, tmp_path: Path):
    """En stdio, une autorisation OAuth bloquerait le serveur sans message
    lisible : le jeton doit exister avant."""
    import jarvis.runtime.drive_mcp as drive_mcp

    monkeypatch.setattr(drive_mcp, "_backend", None)
    monkeypatch.setenv("GOOGLE_DRIVE_CLIENT_SECRET", str(tmp_path / "client_secret.json"))
    monkeypatch.setenv("GOOGLE_DRIVE_TOKEN", str(tmp_path / "absent.json"))
    with pytest.raises(RuntimeError, match="drive-auth"):
        drive_mcp.backend()


def test_mcp_requires_credential_paths(monkeypatch):
    import jarvis.runtime.drive_mcp as drive_mcp

    monkeypatch.delenv("GOOGLE_DRIVE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_CALENDAR_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_DRIVE_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="GOOGLE_DRIVE"):
        drive_mcp.credential_paths()


def test_drive_file_recognises_folders_and_native_types():
    folder = DriveFile(id="f", name="Dossier", mime_type=FOLDER_MIME)
    doc = DriveFile(id="d", name="Doc", mime_type="application/vnd.google-apps.document")
    binary = DriveFile(id="b", name="x.pdf", mime_type="application/pdf")
    assert folder.is_folder and folder.is_native
    assert doc.is_native and not doc.is_folder
    assert not binary.is_native
    assert DriveContent(file=binary, text="").truncated is False

from __future__ import annotations

import asyncio
from datetime import datetime
import io
from pathlib import Path
from typing import Any

from jarvis.adapters.google_oauth import build_service, load_credentials
from jarvis.domain.drive import NATIVE_EXPORTS, DriveContent, DriveFile, DriveQuery

FIELDS = "id,name,mimeType,size,modifiedTime,parents,webViewLink,trashed"
LIST_FIELDS = f"files({FIELDS}),nextPageToken"
SHARE_ROLES = ("reader", "commenter", "writer")


class GoogleDriveBackend:
    """Google Drive adapter; provider objects stay outside Core contracts."""

    SCOPES = ("https://www.googleapis.com/auth/drive",)
    name = "google"
    persistent = True

    def __init__(self, service: Any) -> None:
        self.service = service
        self._idempotency: dict[str, object] = {}

    @classmethod
    def from_oauth_files(cls, client_secret_file: Path, token_file: Path) -> "GoogleDriveBackend":
        creds = load_credentials(client_secret_file, token_file, cls.SCOPES)
        return cls(build_service("drive", "v3", creds))

    async def list_files(self, query: DriveQuery):
        params = {
            "q": self._q(query),
            "pageSize": query.limit,
            "fields": LIST_FIELDS,
            "orderBy": "modifiedTime desc",
            # Sans ces deux drapeaux, les Drive partagés reviennent vides : le
            # défaut de l'API se limite au « My Drive » du compte.
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
        }
        data = await asyncio.to_thread(lambda: self.service.files().list(**params).execute())
        return tuple(self._from_google(item) for item in data.get("files", []))

    async def get_file(self, file_id: str) -> DriveFile | None:
        try:
            item = await asyncio.to_thread(
                lambda: self.service.files().get(fileId=file_id, fields=FIELDS, supportsAllDrives=True).execute()
            )
        except Exception as exc:
            if _status(exc) == 404:
                return None
            raise
        return self._from_google(item)

    async def read_file(self, file_id: str, *, max_chars: int = 20000) -> DriveContent:
        target = await self.get_file(file_id)
        if target is None:
            raise FileNotFoundError(f"drive file not found: {file_id}")
        export_as = NATIVE_EXPORTS.get(target.mime_type, "")
        if target.is_native and not export_as:
            raise ValueError(f"unsupported Google native type: {target.mime_type}")
        payload = await asyncio.to_thread(self._download, file_id, export_as)
        text = payload.decode("utf-8", errors="replace")
        truncated = len(text) > max_chars
        return DriveContent(file=target, text=text[:max_chars], truncated=truncated, exported_as=export_as)

    async def create_file(self, name: str, *, content: str = "", mime_type: str = "text/plain", parent_id: str | None = None, idempotency_key: str) -> DriveFile:
        cached = self._idempotency.get(idempotency_key)
        if isinstance(cached, DriveFile):
            return cached
        body: dict[str, Any] = {"name": name, "mimeType": mime_type}
        if parent_id:
            body["parents"] = [parent_id]
        media = self._media(content, mime_type)
        item = await asyncio.to_thread(
            lambda: self.service.files().create(body=body, media_body=media, fields=FIELDS, supportsAllDrives=True).execute()
        )
        result = self._from_google(item)
        self._idempotency[idempotency_key] = result
        return result

    async def update_file(self, file_id: str, *, content: str, idempotency_key: str) -> DriveFile:
        cached = self._idempotency.get(idempotency_key)
        if isinstance(cached, DriveFile):
            return cached
        target = await self.get_file(file_id)
        if target is None:
            raise FileNotFoundError(f"drive file not found: {file_id}")
        if target.is_native:
            raise ValueError("Google native documents cannot be overwritten by raw upload")
        media = self._media(content, target.mime_type)
        item = await asyncio.to_thread(
            lambda: self.service.files().update(fileId=file_id, media_body=media, fields=FIELDS, supportsAllDrives=True).execute()
        )
        result = self._from_google(item)
        self._idempotency[idempotency_key] = result
        return result

    async def delete_file(self, file_id: str, *, idempotency_key: str) -> None:
        """Mise à la corbeille, pas suppression définitive : une erreur de l'agent
        reste rattrapable depuis l'interface Drive pendant 30 jours."""
        if idempotency_key in self._idempotency:
            return
        await asyncio.to_thread(
            lambda: self.service.files().update(fileId=file_id, body={"trashed": True}, fields="id", supportsAllDrives=True).execute()
        )
        self._idempotency[idempotency_key] = True

    async def share_file(self, file_id: str, *, email: str, role: str = "reader", idempotency_key: str) -> DriveFile:
        cached = self._idempotency.get(idempotency_key)
        if isinstance(cached, DriveFile):
            return cached
        if role not in SHARE_ROLES:
            raise ValueError(f"unsupported drive role: {role}")
        await asyncio.to_thread(
            lambda: self.service.permissions().create(
                fileId=file_id,
                body={"type": "user", "role": role, "emailAddress": email},
                sendNotificationEmail=True,
                supportsAllDrives=True,
            ).execute()
        )
        target = await self.get_file(file_id)
        if target is None:
            raise FileNotFoundError(f"drive file not found: {file_id}")
        self._idempotency[idempotency_key] = target
        return target

    def _download(self, file_id: str, export_as: str) -> bytes:
        from googleapiclient.http import MediaIoBaseDownload  # type: ignore

        request = (
            self.service.files().export_media(fileId=file_id, mimeType=export_as)
            if export_as
            else self.service.files().get_media(fileId=file_id, supportsAllDrives=True)
        )
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue()

    @staticmethod
    def _media(content: str, mime_type: str) -> Any:
        from googleapiclient.http import MediaIoBaseUpload  # type: ignore

        # Un type natif à la création (un Doc) veut du texte en entrée : Drive
        # convertit lui-même, à condition qu'on n'annonce pas le type natif.
        upload_mime = "text/plain" if mime_type.startswith("application/vnd.google-apps.") else mime_type
        return MediaIoBaseUpload(io.BytesIO(content.encode("utf-8")), mimetype=upload_mime, resumable=False)

    @staticmethod
    def _q(query: DriveQuery) -> str:
        clauses: list[str] = []
        if not query.include_trashed:
            clauses.append("trashed = false")
        if query.text:
            clauses.append(f"(name contains '{_escape(query.text)}' or fullText contains '{_escape(query.text)}')")
        if query.parent_id:
            clauses.append(f"'{_escape(query.parent_id)}' in parents")
        if query.mime_type:
            clauses.append(f"mimeType = '{_escape(query.mime_type)}'")
        return " and ".join(clauses) or "trashed = false"

    @staticmethod
    def _from_google(item: dict[str, Any]) -> DriveFile:
        raw_size = item.get("size")
        raw_modified = item.get("modifiedTime")
        return DriveFile(
            id=str(item["id"]),
            name=str(item.get("name") or "(sans nom)"),
            mime_type=str(item.get("mimeType") or "application/octet-stream"),
            size=int(raw_size) if raw_size is not None else None,
            modified_at=datetime.fromisoformat(str(raw_modified).replace("Z", "+00:00")) if raw_modified else None,
            parents=tuple(str(parent) for parent in item.get("parents", [])),
            web_link=str(item.get("webViewLink") or ""),
            trashed=bool(item.get("trashed", False)),
        )


def _escape(value: str) -> str:
    """Les requêtes Drive sont une chaîne : une apostrophe non échappée dans un
    nom de fichier casse la requête, ou en change le sens."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _status(exc: Exception) -> int | None:
    return getattr(getattr(exc, "resp", None), "status", None)

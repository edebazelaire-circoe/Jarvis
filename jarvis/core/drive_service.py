from __future__ import annotations

from jarvis.domain.drive import DriveContent, DriveFile, DriveQuery
from jarvis.ports.drive import DriveBackend


class DriveUnavailableError(RuntimeError):
    """Aucun Drive n'est configuré : l'outil doit le dire plutôt que d'échouer
    avec une trace technique que la voix ne saurait pas restituer."""

    def __init__(self) -> None:
        super().__init__("no Google Drive backend is configured")


class DriveService:
    def __init__(self, backend: DriveBackend | None = None) -> None:
        self.backend = backend

    @property
    def available(self) -> bool:
        return self.backend is not None

    @property
    def storage(self) -> dict[str, object]:
        return {
            "backend": str(getattr(self.backend, "name", "none")),
            "persisted": bool(getattr(self.backend, "persistent", False)),
        }

    def _require(self) -> DriveBackend:
        if self.backend is None:
            raise DriveUnavailableError()
        return self.backend

    async def find(self, query: DriveQuery) -> tuple[DriveFile, ...]:
        return tuple(await self._require().list_files(query))

    async def get(self, file_id: str) -> DriveFile | None:
        return await self._require().get_file(file_id)

    async def read(self, file_id: str, *, max_chars: int = 20000) -> DriveContent:
        return await self._require().read_file(file_id, max_chars=max_chars)

    async def create(self, name: str, *, content: str, mime_type: str, parent_id: str | None, idempotency_key: str) -> DriveFile:
        return await self._require().create_file(name, content=content, mime_type=mime_type, parent_id=parent_id, idempotency_key=idempotency_key)

    async def update(self, file_id: str, *, content: str, idempotency_key: str) -> DriveFile:
        return await self._require().update_file(file_id, content=content, idempotency_key=idempotency_key)

    async def delete(self, file_id: str, *, idempotency_key: str) -> None:
        await self._require().delete_file(file_id, idempotency_key=idempotency_key)

    async def share(self, file_id: str, *, email: str, role: str, idempotency_key: str) -> DriveFile:
        return await self._require().share_file(file_id, email=email, role=role, idempotency_key=idempotency_key)

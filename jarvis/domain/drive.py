from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Un dossier Drive est un fichier comme un autre, distingué par son type MIME.
FOLDER_MIME = "application/vnd.google-apps.folder"
# Les documents natifs (Docs, Sheets, Slides) n'ont pas d'octets à télécharger :
# ils doivent être exportés vers un format concret.
NATIVE_EXPORTS: dict[str, str] = {
    "application/vnd.google-apps.document": "text/markdown",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}


@dataclass(frozen=True, slots=True)
class DriveFile:
    id: str
    name: str
    mime_type: str = "application/octet-stream"
    size: int | None = None
    modified_at: datetime | None = None
    parents: tuple[str, ...] = ()
    web_link: str = ""
    trashed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_folder(self) -> bool:
        return self.mime_type == FOLDER_MIME

    @property
    def is_native(self) -> bool:
        return self.mime_type.startswith("application/vnd.google-apps.")


@dataclass(frozen=True, slots=True)
class DriveQuery:
    text: str | None = None
    parent_id: str | None = None
    mime_type: str | None = None
    limit: int = 25
    include_trashed: bool = False

    def __post_init__(self) -> None:
        if self.limit < 1 or self.limit > 200:
            raise ValueError("drive query limit must be between 1 and 200")
        if self.text is not None and not self.text.strip():
            raise ValueError("drive query text must not be blank")


@dataclass(frozen=True, slots=True)
class DriveContent:
    file: DriveFile
    text: str
    truncated: bool = False
    exported_as: str = ""

"""Serveur MCP stdio exposant le Google Drive de l'utilisateur à un client MCP.

Le même adaptateur sert la voix Jarvis et ce serveur : un seul client OAuth, un
seul comportement, et rien qui transite par un service tiers.

La politique de confirmation de Core ne s'applique pas ici : c'est le client MCP
(Claude Code et ses autorisations d'outils) qui arbitre. Le serveur se contente
de refuser ce qu'il ne peut pas faire sans mentir.

Deux profils. `build_server()` (écriture comprise) est celui qu'un opérateur
enregistre lui-même (`claude mcp add`). `build_server(read_only=True)` est celui
que **JARVIS déclare au cerveau** (2026-10-07, `write_mcp_config`) : recherche,
métadonnées et lecture seulement, aucun outil d'écriture n'est même enregistré.
L'écriture sur le Drive de l'utilisateur reste une décision à lui.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

from jarvis.adapters.google_drive import GoogleDriveBackend
from jarvis.domain.drive import DriveQuery
from jarvis.environment import load_project_environment
from jarvis.runtime.mcp_tool_meta import tool_annotations

SERVER_NAME = "jarvis-drive"
CONFIG_FILE_NAME = "drive-mcp.json"
#: Posée dans l'environnement du serveur lancé par le CLI : `-m jarvis drive-mcp`
#: n'a pas d'autre canal, et un drapeau de plus au parseur n'apporterait rien.
ENV_READ_ONLY = "JARVIS_DRIVE_MCP_READ_ONLY"
READ_ONLY_TOOLS = ("drive_search", "drive_get", "drive_read")
WRITE_TOOLS = ("drive_create", "drive_update", "drive_delete", "drive_share")

_backend: GoogleDriveBackend | None = None


def credential_paths() -> tuple[Path, Path]:
    secret = os.getenv("GOOGLE_DRIVE_CLIENT_SECRET") or os.getenv("GOOGLE_CALENDAR_CLIENT_SECRET")
    token = os.getenv("GOOGLE_DRIVE_TOKEN")
    if not secret or not token:
        raise RuntimeError("GOOGLE_DRIVE_CLIENT_SECRET et GOOGLE_DRIVE_TOKEN doivent être définis (voir .env).")
    return Path(secret), Path(token)


def backend() -> GoogleDriveBackend:
    """Adaptateur construit à la première demande.

    En stdio, tout ce qui s'écrit sur la sortie standard est du protocole : une
    autorisation OAuth interactive au démarrage bloquerait le serveur sans
    qu'aucun message n'atteigne l'utilisateur. Le jeton doit donc déjà exister,
    créé par `python -m jarvis drive-auth`.
    """
    global _backend
    if _backend is None:
        secret, token = credential_paths()
        if not token.is_file():
            raise RuntimeError(f"Aucun jeton Drive dans {token}. Lancez d'abord : python -m jarvis drive-auth")
        _backend = GoogleDriveBackend.from_oauth_files(secret, token)
    return _backend


def _file(item: Any) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "mime_type": item.mime_type,
        "size": item.size,
        "modified_at": item.modified_at.isoformat() if item.modified_at else None,
        "web_link": item.web_link,
        "is_folder": item.is_folder,
        "parents": list(item.parents),
    }


def build_server(*, read_only: bool = False):
    from mcp.server.fastmcp import FastMCP

    if read_only:
        instructions = ("Accès en lecture seule au Google Drive de l'utilisateur : drive_search, drive_get, drive_read. "
                        "Les identifiants renvoyés par drive_search alimentent drive_get et drive_read. "
                        "Aucun outil n'écrit, ne partage ni ne supprime : ne promets jamais de le faire.")
    else:
        instructions = ("Accès en lecture et écriture au Google Drive de l'utilisateur. "
                        "Les identifiants renvoyés par drive_search alimentent drive_read, drive_update et drive_delete.")
    mcp = FastMCP(SERVER_NAME, instructions=instructions)

    @mcp.tool(annotations=tool_annotations(SERVER_NAME, "drive_search"))
    async def drive_search(text: str = "", parent_id: str = "", mime_type: str = "", limit: int = 25) -> list[dict[str, Any]]:
        """Chercher des fichiers par nom et contenu, éventuellement dans un dossier."""
        query = DriveQuery(text=text.strip() or None, parent_id=parent_id or None, mime_type=mime_type or None, limit=limit)
        return [_file(item) for item in await backend().list_files(query)]

    @mcp.tool(annotations=tool_annotations(SERVER_NAME, "drive_get"))
    async def drive_get(file_id: str) -> dict[str, Any]:
        """Métadonnées d'un fichier : nom, type MIME, taille, dossiers parents, lien web."""
        found = await backend().get_file(file_id)
        if found is None:
            raise ValueError(f"fichier introuvable : {file_id}")
        return _file(found)

    @mcp.tool(annotations=tool_annotations(SERVER_NAME, "drive_read"))
    async def drive_read(file_id: str, max_chars: int = 20000) -> dict[str, Any]:
        """Contenu texte d'un fichier. Docs, Sheets et Slides sont exportés (markdown, csv, texte)."""
        content = await backend().read_file(file_id, max_chars=max_chars)
        return {"file": _file(content.file), "text": content.text, "truncated": content.truncated, "exported_as": content.exported_as}

    if read_only:
        return mcp

    @mcp.tool(annotations=tool_annotations(SERVER_NAME, "drive_create"))
    async def drive_create(name: str, content: str = "", mime_type: str = "text/plain", parent_id: str = "") -> dict[str, Any]:
        """Créer un fichier. mime_type application/vnd.google-apps.document crée un Google Doc."""
        created = await backend().create_file(name, content=content, mime_type=mime_type, parent_id=parent_id or None, idempotency_key=f"mcp-create-{name}-{parent_id}")
        return _file(created)

    @mcp.tool(annotations=tool_annotations(SERVER_NAME, "drive_update"))
    async def drive_update(file_id: str, content: str) -> dict[str, Any]:
        """Remplacer intégralement le contenu d'un fichier non natif."""
        updated = await backend().update_file(file_id, content=content, idempotency_key=f"mcp-update-{file_id}-{hash(content)}")
        return _file(updated)

    @mcp.tool(annotations=tool_annotations(SERVER_NAME, "drive_delete"))
    async def drive_delete(file_id: str) -> dict[str, Any]:
        """Mettre un fichier à la corbeille Drive. Récupérable pendant 30 jours."""
        await backend().delete_file(file_id, idempotency_key=f"mcp-delete-{file_id}")
        return {"trashed_file_id": file_id}

    @mcp.tool(annotations=tool_annotations(SERVER_NAME, "drive_share"))
    async def drive_share(file_id: str, email: str, role: str = "reader") -> dict[str, Any]:
        """Partager un fichier avec une adresse e-mail. role: reader, commenter ou writer."""
        shared = await backend().share_file(file_id, email=email, role=role, idempotency_key=f"mcp-share-{file_id}-{email}-{role}")
        return {"file": _file(shared), "shared_with": email, "role": role}

    return mcp


@dataclass(frozen=True, slots=True)
class DriveMcpTarget:
    """Ce que le Control Center sait du serveur Drive qu'il déclare au cerveau : où écrire son fichier."""

    runtime_root: Path | None = None
    read_only: bool = True

    def env(self) -> dict[str, str]:
        return {ENV_READ_ONLY: "1"} if self.read_only else {}


def read_only_from_env(environ: "os._Environ[str] | dict[str, str] | None" = None) -> bool:
    env = os.environ if environ is None else environ
    return str(env.get(ENV_READ_ONLY, "")).strip().lower() in {"1", "true", "yes", "on"}


def mcp_config(target: DriveMcpTarget, *, python: str | None = None) -> dict[str, Any]:
    """Le document `--mcp-config` : ce seul serveur, même interpréteur, `-m jarvis drive-mcp`."""

    server: dict[str, Any] = {"type": "stdio", "command": python or sys.executable, "args": ["-m", "jarvis", "drive-mcp"]}
    if target.env():
        server["env"] = target.env()
    return {"mcpServers": {SERVER_NAME: server}}


def write_mcp_config(target: DriveMcpTarget, directory: Path, *, python: str | None = None) -> Path:
    """Écrire le `--mcp-config` de façon atomique dans `directory` ; `OSError` à l'appelant (même forme que Bare Hands)."""

    from jarvis.adapters.file_replace import replace_with_retry

    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    target_path = directory / CONFIG_FILE_NAME
    text = json.dumps(mcp_config(target, python=python), ensure_ascii=False, indent=2) + "\n"
    handle, raw_tmp = tempfile.mkstemp(prefix=CONFIG_FILE_NAME + ".", suffix=".tmp", dir=directory)
    tmp = Path(raw_tmp)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        replace_with_retry(tmp, target_path)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass  # intentional: l'échec d'origine est ce que l'appelant doit voir
        raise
    return target_path


def main() -> int:
    load_project_environment()
    build_server(read_only=read_only_from_env()).run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

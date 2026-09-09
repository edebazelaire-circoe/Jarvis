"""Serveur MCP stdio exposant le Google Drive de l'utilisateur à un client MCP.

Le même adaptateur sert la voix Jarvis et ce serveur : un seul client OAuth, un
seul comportement, et rien qui transite par un service tiers.

La politique de confirmation de Core ne s'applique pas ici : c'est le client MCP
(Claude Code et ses autorisations d'outils) qui arbitre. Le serveur se contente
de refuser ce qu'il ne peut pas faire sans mentir.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from jarvis.adapters.google_drive import GoogleDriveBackend
from jarvis.domain.drive import DriveQuery
from jarvis.environment import load_project_environment

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


def build_server():
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(
        "jarvis-drive",
        instructions="Accès en lecture et écriture au Google Drive de l'utilisateur. "
        "Les identifiants renvoyés par drive_search alimentent drive_read, drive_update et drive_delete.",
    )

    @mcp.tool()
    async def drive_search(text: str = "", parent_id: str = "", mime_type: str = "", limit: int = 25) -> list[dict[str, Any]]:
        """Chercher des fichiers par nom et contenu, éventuellement dans un dossier."""
        query = DriveQuery(text=text.strip() or None, parent_id=parent_id or None, mime_type=mime_type or None, limit=limit)
        return [_file(item) for item in await backend().list_files(query)]

    @mcp.tool()
    async def drive_get(file_id: str) -> dict[str, Any]:
        """Métadonnées d'un fichier : nom, type MIME, taille, dossiers parents, lien web."""
        found = await backend().get_file(file_id)
        if found is None:
            raise ValueError(f"fichier introuvable : {file_id}")
        return _file(found)

    @mcp.tool()
    async def drive_read(file_id: str, max_chars: int = 20000) -> dict[str, Any]:
        """Contenu texte d'un fichier. Docs, Sheets et Slides sont exportés (markdown, csv, texte)."""
        content = await backend().read_file(file_id, max_chars=max_chars)
        return {"file": _file(content.file), "text": content.text, "truncated": content.truncated, "exported_as": content.exported_as}

    @mcp.tool()
    async def drive_create(name: str, content: str = "", mime_type: str = "text/plain", parent_id: str = "") -> dict[str, Any]:
        """Créer un fichier. mime_type application/vnd.google-apps.document crée un Google Doc."""
        created = await backend().create_file(name, content=content, mime_type=mime_type, parent_id=parent_id or None, idempotency_key=f"mcp-create-{name}-{parent_id}")
        return _file(created)

    @mcp.tool()
    async def drive_update(file_id: str, content: str) -> dict[str, Any]:
        """Remplacer intégralement le contenu d'un fichier non natif."""
        updated = await backend().update_file(file_id, content=content, idempotency_key=f"mcp-update-{file_id}-{hash(content)}")
        return _file(updated)

    @mcp.tool()
    async def drive_delete(file_id: str) -> dict[str, Any]:
        """Mettre un fichier à la corbeille Drive. Récupérable pendant 30 jours."""
        await backend().delete_file(file_id, idempotency_key=f"mcp-delete-{file_id}")
        return {"trashed_file_id": file_id}

    @mcp.tool()
    async def drive_share(file_id: str, email: str, role: str = "reader") -> dict[str, Any]:
        """Partager un fichier avec une adresse e-mail. role: reader, commenter ou writer."""
        shared = await backend().share_file(file_id, email=email, role=role, idempotency_key=f"mcp-share-{file_id}-{email}-{role}")
        return {"file": _file(shared), "shared_with": email, "role": role}

    return mcp


def main() -> int:
    load_project_environment()
    build_server().run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

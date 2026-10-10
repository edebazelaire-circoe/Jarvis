"""Serveur MCP stdio « jarvis-remotion » : la capacité Remotion pour le cerveau (jarvis-remotion-presentation-integration, Slice 21).

Un serveur **séparé** et petit (six outils typés) : le budget de contexte de `jarvis-presentation` (douze outils) est plein, et la
capacité Remotion (santé, Studio, export, import, versions plus récentes) n'est pas la même famille que l'édition d'une présentation.
Une façade, jamais un propriétaire : les routes de Core sont celles des cartes du Control Center. **Aucun outil n'a de paramètre de
moteur** ; l'accusé du Studio hors bac à sable et la licence d'une version plus récente sont à l'utilisateur seul.

| Outil | Rôle |
| --- | --- |
| `remotion_status` | santé de la capacité + moteurs (lecture seule), Studio, exports (liste, un export) |
| `remotion_setup` | installer / réparer, sur demande de l'utilisateur |
| `remotion_studio` | pointeur vers la carte « Remotion · Studio » : l'utilisateur ouvre et confirme lui-même |
| `remotion_export` | lancer / annuler un export mp4, image ou PDF de la variante, sur demande |
| `remotion_import` | plan puis import d'un modèle amont (liste blanche de l'utilisateur), sur demande |
| `remotion_upgrades` | avis de versions plus récentes (lecture) et essai en variante enfant, sur demande |

Pas de `from __future__ import annotations` : FastMCP lit les annotations des outils définis dans `build_server`.
"""

import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.mcp_tool_meta import tool_annotations, tool_names
from jarvis.runtime.presentation_studio_mcp_support import PresentationMcpTarget, PresentationToolError
from jarvis.runtime.presentation_studio_mcp_tools import ControlCenterCaller, CoreCaller
from jarvis.runtime.remotion_mcp_tools import EXPORT_FORMATS, RemotionTools

SERVER_NAME = "jarvis-remotion"
CONFIG_FILE_NAME = "remotion-mcp.json"
TOOL_NAMES = tool_names(SERVER_NAME)

_SERVER_INSTRUCTIONS = (
    "Capacité Remotion de ce poste. Les ids (job, scène, présentation) se lisent, jamais ne s'inventent. Écrire, lancer ou importer exige "
    "une demande de l'utilisateur dans ce tour, ses mots dans user_request. Le moteur et l'ouverture du Studio sont à l'utilisateur seul."
)


def mcp_config(target: PresentationMcpTarget, *, python: str | None = None) -> dict[str, Any]:
    """Le document `--mcp-config` : ce seul serveur, même interpréteur, `-m jarvis remotion-mcp`."""

    return {"mcpServers": {SERVER_NAME: {"type": "stdio", "command": python or sys.executable,
                                         "args": ["-m", "jarvis", "remotion-mcp"], "env": target.env()}}}


def write_mcp_config(target: PresentationMcpTarget, directory: Path, *, python: str | None = None) -> Path:
    """Écrire le `--mcp-config` de façon atomique dans `directory`. `OSError` à l'appelant."""

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
            pass  # intentional: the original failure is what the caller must see; a stray .tmp is harmless
        raise
    return target_path


def tools_for(target: PresentationMcpTarget, journal: RuntimeJournal | None) -> RemotionTools:
    return RemotionTools(CoreCaller(target.core), ControlCenterCaller(target.control_center), journal=journal)


def build_server(target: PresentationMcpTarget | None = None, *, tools: RemotionTools | None = None):
    """Construire le serveur FastMCP. `tools` : injection pour les tests et le catalogue."""

    from typing import Annotated, Literal

    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.exceptions import ToolError
    from pydantic import BaseModel, ConfigDict, Field, ValidationError

    from jarvis.runtime.display_mcp import _argument_error_text, _without_titles

    if tools is None:
        target = target or PresentationMcpTarget.from_env()
        journal = RuntimeJournal(target.runtime_root) if target.runtime_root is not None else None
        tools = tools_for(target, journal)
    remotion = tools

    class StrictRemotionMCP(FastMCP):
        """Arguments inconnus refusés, refus de schéma rendus tels quels, refus d'outil avec leur code."""

        async def list_tools(self):  # noqa: ANN201 - type de FastMCP
            listed = await super().list_tools()
            for tool in listed:
                tool.inputSchema = {**_without_titles(tool.inputSchema), "additionalProperties": False}
            return listed

        async def call_tool(self, name: str, arguments: dict[str, Any]):  # noqa: ANN201 - type de FastMCP
            known = {tool.name: tool for tool in await self.list_tools()}
            if name in known:
                allowed = set(known[name].inputSchema.get("properties", {}))
                unknown = sorted(set(arguments or {}) - allowed)
                if unknown:
                    raise ToolError(f"Arguments inconnus refusés, rien n'a été envoyé : {', '.join(unknown[:8])}. "
                                    f"Arguments permis : {', '.join(sorted(allowed)) or 'aucun'}.")
            try:
                return await super().call_tool(name, arguments)
            except ToolError as exc:
                cause = exc.__cause__
                if isinstance(cause, ValidationError):
                    text, _fields = _argument_error_text(cause)
                    raise ToolError(f"Argument invalide, rien n'a été envoyé : {text}") from None
                if isinstance(cause, PresentationToolError):
                    raise ToolError(str(cause)) from None
                raise

    mcp = StrictRemotionMCP(SERVER_NAME, instructions=_SERVER_INSTRUCTIONS)

    PresentationId = Annotated[str | None, Field(max_length=40, description="pst_… ; absent : celle de l'état.")]
    VariantId = Annotated[str | None, Field(max_length=40, description="psv_… ; absent : l'active.")]
    UserRequest = Annotated[str | None, Field(max_length=200, description="Ses mots qui demandent ce geste (obligatoire).")]

    class ExportSettings(BaseModel):
        model_config = ConfigDict(extra="forbid")
        scene_id: Annotated[str | None, Field(max_length=20, description="pss_… si plusieurs scènes Remotion.")] = None
        frame_start: Annotated[int | None, Field(ge=0, le=100000)] = None
        frame_end: Annotated[int | None, Field(ge=0, le=100000)] = None
        frame: Annotated[int | None, Field(ge=0, le=100000, description="still")] = None
        scale: Annotated[float | None, Field(ge=0.25, le=2)] = None
        crf: Annotated[int | None, Field(ge=16, le=35, description="mp4")] = None

    @mcp.tool(annotations=tool_annotations(SERVER_NAME, "remotion_status"))
    async def remotion_status(
        target: Annotated[Literal["capability", "studio", "exports", "export"],
                          Field(description="capability : santé + moteurs ; exports : liste des jobs ; export : un job.")],
        job_id: Annotated[str | None, Field(max_length=20, description="rj_…, lu dans exports.")] = None,
    ) -> dict[str, Any]:
        """Lire l'état de Remotion. Lecture seule. Les ids viennent d'ici."""
        return await remotion.status(target, job_id=job_id)

    @mcp.tool(annotations=tool_annotations(SERVER_NAME, "remotion_setup"))
    async def remotion_setup(
        op: Literal["install", "repair"],
        user_request: UserRequest = None,
    ) -> dict[str, Any]:
        """Installer ou réparer Remotion, seulement sur demande de l'utilisateur dans ce tour. Long."""
        return await remotion.setup(op, user_request=user_request)

    @mcp.tool(annotations=tool_annotations(SERVER_NAME, "remotion_studio"))
    async def remotion_studio(
        presentation_id: PresentationId = None,
        variant_id: VariantId = None,
        scene_id: Annotated[str | None, Field(max_length=20, description="pss_…")] = None,
    ) -> dict[str, Any]:
        """Demander le Studio. N'ouvre rien : l'utilisateur ouvre et confirme lui-même."""
        return await remotion.studio(presentation_id=presentation_id, variant_id=variant_id, scene_id=scene_id)

    @mcp.tool(annotations=tool_annotations(SERVER_NAME, "remotion_export"))
    async def remotion_export(
        op: Literal["start", "cancel"],
        format: Annotated[Literal[EXPORT_FORMATS] | None, Field(description="start")] = None,  # type: ignore[valid-type]
        settings: ExportSettings | None = None,
        presentation_id: PresentationId = None,
        variant_id: VariantId = None,
        job_id: Annotated[str | None, Field(max_length=20, description="cancel : rj_…")] = None,
        user_request: UserRequest = None,
    ) -> dict[str, Any]:
        """Exporter la variante ou annuler un export, sur demande de l'utilisateur. Aucun Board lu."""
        return await remotion.export(op, format=format, settings=None if settings is None else settings.model_dump(exclude_none=True),
                                     presentation_id=presentation_id, variant_id=variant_id, job_id=job_id, user_request=user_request)

    @mcp.tool(annotations=tool_annotations(SERVER_NAME, "remotion_import"))
    async def remotion_import(
        op: Literal["plan", "execute"],
        repo_url: Annotated[str | None, Field(max_length=200, description="donné par l'utilisateur")] = None,
        commit: Annotated[str | None, Field(max_length=40, description="SHA complet, donné par l'utilisateur")] = None,
        composition_id: Annotated[str | None, Field(max_length=64)] = None,
        subdir: Annotated[str | None, Field(max_length=120)] = None,
        title: Annotated[str | None, Field(max_length=120)] = None,
        presentation_id: PresentationId = None,
        user_request: UserRequest = None,
    ) -> dict[str, Any]:
        """Importer un modèle Remotion amont, sur demande. plan (rien d'écrit), puis execute, même demande."""
        return await remotion.import_template(op, repo_url=repo_url, commit=commit, composition_id=composition_id, subdir=subdir, title=title,
                                              presentation_id=presentation_id, user_request=user_request)

    @mcp.tool(annotations=tool_annotations(SERVER_NAME, "remotion_upgrades"))
    async def remotion_upgrades(
        op: Literal["notices", "try"],
        presentation_id: PresentationId = None,
        variant_id: VariantId = None,
        scene_id: Annotated[str | None, Field(max_length=20, description="try : pss_…")] = None,
        version: Annotated[int | None, Field(ge=1, le=100000, description="try : parmi newer_versions")] = None,
        user_request: UserRequest = None,
    ) -> dict[str, Any]:
        """Versions plus récentes : notices lit ; try crée une variante d'essai, sur demande. Jamais de licence_ack."""
        return await remotion.upgrades(op, presentation_id=presentation_id, variant_id=variant_id, scene_id=scene_id, version=version,
                                       user_request=user_request)

    return mcp


async def serve_stdio() -> int:
    """Point d'entrée de `python -m jarvis remotion-mcp` : stdout est le protocole, rien d'autre n'y écrit."""

    target = PresentationMcpTarget.from_env()
    journal = RuntimeJournal(target.runtime_root) if target.runtime_root is not None else None
    if journal is not None:
        journal.emit("remotion_mcp.server_started", "Serveur MCP Remotion démarré", data={"pid": os.getpid()})
    tools = tools_for(target, journal)
    try:
        await build_server(target, tools=tools).run_stdio_async()
    finally:
        await tools.close()
        if journal is not None:
            journal.emit("remotion_mcp.server_stopped", "Serveur MCP Remotion arrêté", data={"pid": os.getpid()})
    return 0


__all__ = ["SERVER_NAME", "TOOL_NAMES", "build_server", "mcp_config", "serve_stdio", "write_mcp_config"]

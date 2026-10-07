"""Serveur MCP « jarvis-surface » : surfaces de navigation du Tool Brain (handoff jarvis-tool-brain-ui-orchestrator, S7).

Contrat : `docs/tool-brain-contracts.md` §15. Cinq outils de présentation (`surface_open`, `surface_focus`,
`surface_scroll`, `surface_history`, `surface_zoom`) sur des **fenêtres de scène** `jarvis.browser` : aucun second
système de fenêtres, Core (scène) reste l'unique propriétaire de l'état. La logique est celle de
`display_surfaces.SurfaceToolsMixin` (portée par `SceneDisplayTools`, le même transport de commandes du cerveau).

**Registration `tool_brain`** (`mcp_tool_meta.SURFACE`) : le serveur est construit et catalogué (schémas, effets,
choix du manifeste), mais **n'est déclaré à aucun lancement du cerveau principal** : `jarvis-display` a un plafond
d'outils (`test_mcp_catalog`), et ces gestes sont ceux du Tool Brain, qui les exécute par l'exécuteur S6
(`SurfaceAdapter`), pas par un appel MCP. Un `--mcp-config` n'est donc volontairement pas généré ici ; l'ajouter
est un changement de contrat du cerveau principal (S8, qui décide qui possède les outils d'interface).

Pas de `from __future__ import annotations` : FastMCP lit les annotations des outils définis dans `build_server`.
"""

from typing import Annotated, Any, Literal

from jarvis.runtime.mcp_tool_meta import tool_annotations, tool_names

SERVER_NAME = "jarvis-surface"
TOOL_NAMES = tool_names(SERVER_NAME)

_SERVER_INSTRUCTIONS = (
    "Surfaces de navigation de la scène (présentation d'une adresse web). Une surface est une fenêtre de scène : "
    "la page n'est jamais chargée, l'utilisateur l'ouvre dans un onglet. Tout id de surface (surf_…) est lu dans "
    "l'état courant, jamais deviné. Chercher ou lire une page n'est pas le travail de ces outils."
)


def build_server(tools: Any = None, target: Any = None):
    """Construire le serveur FastMCP. `tools` : un `SceneDisplayTools` (injection pour les tests et le catalogue)."""

    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.exceptions import ToolError
    from pydantic import Field, ValidationError

    from jarvis.runtime.display_mcp import (
        DisplayToolError, DisplayMcpTarget, SceneDisplayTools, _argument_error_text, _short, _without_titles,
        prefab_tools_for, scene_gate_reader,
    )
    from jarvis.runtime.journal import RuntimeJournal
    from jarvis.runtime.mcp_results import OUTPUT_CONTRACT_MESSAGE, SceneSurfaceResult, output_contract_fields

    if tools is None:
        from jarvis.runtime.scene_view import CoreSceneTransport

        target = target or DisplayMcpTarget.from_env()
        journal = RuntimeJournal(target.runtime_root) if target.runtime_root is not None else None
        tools = SceneDisplayTools(
            CoreSceneTransport(host=target.core_host, port=target.core_port, token_file=target.token_file), journal=journal,
            scene_gate=scene_gate_reader(target.runtime_root), prefabs=prefab_tools_for(target, journal),
        )
    surfaces = tools

    class StrictSurfaceMCP(FastMCP):
        """Arguments inconnus refusés (`additionalProperties: false`) ; refus de schéma bornés et journalisés."""

        async def list_tools(self):  # noqa: ANN201 - type de FastMCP
            listed = await super().list_tools()
            for tool in listed:
                tool.inputSchema = {**_without_titles(tool.inputSchema), "additionalProperties": False}
            return listed

        async def call_tool(self, name: str, arguments: dict[str, Any]):  # noqa: ANN201 - type de FastMCP
            known = {tool.name: tool for tool in await self.list_tools()}
            tool = known.get(name)
            if tool is not None:
                unknown = sorted(set(arguments or {}) - set(tool.inputSchema.get("properties", {})))
                if unknown:
                    surfaces.report_rejected_arguments(name, "unknown_argument", unknown)
                    shown = ", ".join(_short(str(key), 40) for key in unknown[:8])
                    raise ToolError(f"Arguments inconnus refusés, rien n'a été envoyé : {shown}. "
                                    f"Arguments permis : {', '.join(tool.inputSchema.get('properties', {}))}.")
            try:
                return await super().call_tool(name, arguments)
            except ToolError as exc:
                cause = exc.__cause__
                broken = output_contract_fields(cause)
                if broken is not None:
                    surfaces.report_rejected_arguments(name, "output_contract", broken)
                    raise ToolError(OUTPUT_CONTRACT_MESSAGE.format(fields=", ".join(broken[:6]))) from None
                if isinstance(cause, ValidationError):
                    text, fields = _argument_error_text(cause)
                    surfaces.report_rejected_arguments(name, "invalid_argument", fields)
                    raise ToolError(f"Argument invalide, rien n'a été envoyé : {text}") from None
                if isinstance(cause, DisplayToolError):
                    raise ToolError(str(cause)) from None
                raise

    mcp = StrictSurfaceMCP(SERVER_NAME, instructions=_SERVER_INSTRUCTIONS)

    SurfaceId = Annotated[str, Field(max_length=40, description="Surface (surf_…) lue dans les surfaces de la perception ou du manifeste.")]

    @mcp.tool(description="""Ouvrir une adresse web dans une surface de navigation de la scène (présentation) ; rend surface_id.

Sans surface_id : une surface neuve (une fenêtre de scène, prefab jarvis.browser). Avec surface_id : l'adresse
s'ajoute à l'historique de cette surface. La surface est affichée dépliée ; **la page n'est pas chargée** (le cadre
n'a pas de réseau) : elle montre l'hôte, l'adresse, tes notes et la trace de navigation, et l'utilisateur l'ouvre
dans un onglet. Chercher ou lire le contenu d'une page reste ton travail. Seules les adresses http(s) publiques
sont acceptées (unsafe_url : autre schéma, identifiants dans l'adresse, hôte local ou privé). Une surface est aussi
un objet de scène (fenêtre) : scene_inspect la montre.""", annotations=tool_annotations(SERVER_NAME, "surface_open"))
    async def surface_open(
        url: Annotated[str, Field(max_length=2048, description="Adresse http(s) publique, sans identifiants.")],
        surface_id: Annotated[str | None, Field(max_length=40, description="Surface existante (surf_…). Absent : une surface neuve.")] = None,
        label: Annotated[str | None, Field(max_length=120, description="Titre court de la page (une ligne). Absent : l'hôte.")] = None,
        note: Annotated[str | None, Field(max_length=4000, description="Notes affichées sur la carte (markdown). Absent : gardées.")] = None,
    ) -> SceneSurfaceResult:
        return await surfaces.surface_open(url=url, surface_id=surface_id, label=label, note=note)

    @mcp.tool(description="""Mettre une surface de navigation au premier plan : visible, dépliée, au-dessus des autres objets.

« Focus » n'existe pas dans le réducteur de scène : c'est la composition d'écran (visibilité, forme, couche, ordre)
en une seule commande. Déjà au premier plan : rien ne change (duplicate).""", annotations=tool_annotations(SERVER_NAME, "surface_focus"))
    async def surface_focus(surface_id: SurfaceId) -> SceneSurfaceResult:
        return await surfaces.surface_focus(surface_id=surface_id)

    @mcp.tool(description="""Faire défiler la carte d'une surface : top, bottom, ou up / down d'un quart de sa hauteur.

Au bord : rien ne change (duplicate). Présentation seulement.""", annotations=tool_annotations(SERVER_NAME, "surface_scroll"))
    async def surface_scroll(
        surface_id: SurfaceId,
        direction: Annotated[Literal["top", "bottom", "up", "down"], Field(description="top, bottom, up ou down (un quart de hauteur).")],
    ) -> SceneSurfaceResult:
        return await surfaces.surface_scroll(surface_id=surface_id, direction=direction)

    @mcp.tool(description="""Revenir à la page précédente ou avancer à la suivante dans la trace d'une surface.

Au bord de l'historique : refus no_history (rien n'est inventé). Le défilement repart du haut.""", annotations=tool_annotations(SERVER_NAME, "surface_history"))
    async def surface_history(
        surface_id: SurfaceId,
        direction: Annotated[Literal["back", "forward"], Field(description="back : page précédente ; forward : page suivante.")],
    ) -> SceneSurfaceResult:
        return await surfaces.surface_history(surface_id=surface_id, direction=direction)

    @mcp.tool(description="""Zoomer ou dézoomer la carte d'une surface d'un cran (25, 50, 75, 100, 125, 150, 200, 300 %), ou revenir à 100 %.

Au bout de l'échelle : rien ne change (duplicate).""", annotations=tool_annotations(SERVER_NAME, "surface_zoom"))
    async def surface_zoom(
        surface_id: SurfaceId,
        action: Annotated[Literal["in", "out", "reset"], Field(description="in : cran au-dessus ; out : cran en dessous ; reset : 100 %.")],
    ) -> SceneSurfaceResult:
        return await surfaces.surface_zoom(surface_id=surface_id, action=action)

    return mcp


__all__ = ["SERVER_NAME", "TOOL_NAMES", "build_server"]

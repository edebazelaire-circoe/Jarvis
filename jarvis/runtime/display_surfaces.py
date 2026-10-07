"""Outils `surface_*` du serveur MCP `jarvis-display` (handoff jarvis-tool-brain-ui-orchestrator, S7, lot 07b).

Contrat : `docs/tool-brain-contracts.md` §15. Logique sans FastMCP : un mélange (`SurfaceToolsMixin`) de
`SceneDisplayTools`, qui fournit l'instantané (`_snapshot`), l'envoi d'une commande du cerveau (`_command`) et la
garde d'erreurs (`_guard`). **Aucun état propre** : chaque outil lit la scène, fait planifier la commande par le
domaine pur (`jarvis.domain.browser_surface`) et l'envoie à Core, seul propriétaire (la validation du bloc prefab
par le manifeste de `jarvis.browser` est celle de Core). L'exécuteur du Tool Brain, lui, applique les mêmes plans
par `SceneService.apply_if` (lecture et écriture sous le même verrou).

| Outil | Plan du domaine | Effet |
| --- | --- | --- |
| `surface_open` | `plan_open` | ouvre une adresse dans une surface (neuve si `surface_id` absent) |
| `surface_focus` | `plan_focus` | surface visible, dépliée, au premier plan |
| `surface_scroll` | `plan_scroll` | position de défilement (pourcentage) |
| `surface_history` | `plan_history` | page précédente / suivante de la trace |
| `surface_zoom` | `plan_zoom` | cran de zoom suivant / précédent / 100 % |
"""

from __future__ import annotations

from typing import Any, Callable

from jarvis.domain.browser_surface import SurfaceError, plan_focus, plan_history, plan_open, plan_scroll, plan_zoom
from jarvis.domain.browser_surface import surface_id_of
from jarvis.domain.scene import SceneCommand, SceneSnapshot


class SurfaceToolsMixin:
    """Ajoute les outils `surface_*` à `SceneDisplayTools` (voir l'en-tête)."""

    # Fournis par `SceneDisplayTools` (annotations seulement : le mélange ne les redéfinit pas).
    _new_id: Callable[[], str]

    async def surface_open(self, *, url: str, surface_id: str | None = None, label: str | None = None,
                           note: str | None = None) -> dict[str, Any]:
        """Ouvrir `url` dans la surface `surface_id`, ou dans une surface neuve quand elle est absente."""

        from jarvis.runtime.display_mcp import DisplayToolError

        async def run() -> dict[str, Any]:
            snapshot = await self._snapshot()  # type: ignore[attr-defined]
            opaque = self._new_id() if surface_id is None else None
            try:
                command = plan_open(snapshot, url, surface_id=surface_id, label=label, note=note, new_opaque=opaque)
            except SurfaceError as exc:
                raise _tool_error(DisplayToolError, exc) from None
            except (TypeError, ValueError) as exc:  # champ refusé par le domaine de scène (titre, taille)
                raise DisplayToolError("invalid_argument", f"Argument invalide, rien n'a été envoyé : {str(exc)[:300]}") from None
            return await self._send_surface("surface_open", command)

        return await self._guard("surface_open", run)  # type: ignore[attr-defined]

    async def surface_focus(self, *, surface_id: str) -> dict[str, Any]:
        return await self._surface_verb("surface_focus", lambda snap: plan_focus(snap, surface_id))

    async def surface_scroll(self, *, surface_id: str, direction: str) -> dict[str, Any]:
        return await self._surface_verb("surface_scroll", lambda snap: plan_scroll(snap, surface_id, direction))

    async def surface_history(self, *, surface_id: str, direction: str) -> dict[str, Any]:
        return await self._surface_verb("surface_history", lambda snap: plan_history(snap, surface_id, direction))

    async def surface_zoom(self, *, surface_id: str, action: str) -> dict[str, Any]:
        return await self._surface_verb("surface_zoom", lambda snap: plan_zoom(snap, surface_id, action))

    # ------------------------------------------------------------ pièces

    async def _surface_verb(self, tool: str, plan: Callable[[SceneSnapshot], SceneCommand]) -> dict[str, Any]:
        from jarvis.runtime.display_mcp import DisplayToolError

        async def run() -> dict[str, Any]:
            snapshot = await self._snapshot()  # type: ignore[attr-defined]
            try:
                command = plan(snapshot)
            except SurfaceError as exc:
                raise _tool_error(DisplayToolError, exc) from None
            return await self._send_surface(tool, command)

        return await self._guard(tool, run)  # type: ignore[attr-defined]

    async def _send_surface(self, tool: str, command: SceneCommand) -> dict[str, Any]:
        assert command.object_id is not None
        result = await self._command(tool, command, object_id=command.object_id)  # type: ignore[attr-defined]
        return {"surface_id": surface_id_of(command.object_id), "object_id": command.object_id, **result}


def _tool_error(error_type: Callable[..., Exception], exc: SurfaceError) -> Exception:
    """`SurfaceError` -> erreur d'outil lisible ; le code du domaine (`unsafe_url`, `no_history`...) est dit."""

    code = "invalid_argument" if exc.code == "invalid_argument" else "surface_refused"
    return error_type(code, f"{exc.code} : {exc.detail}. Rien n'a été envoyé.", reason=exc.code)


__all__ = ["SurfaceToolsMixin"]

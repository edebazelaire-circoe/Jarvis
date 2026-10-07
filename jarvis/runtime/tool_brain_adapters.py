"""Adaptateurs d'exécution du Tool Brain pour la scène et les surfaces (handoff jarvis-tool-brain-ui-orchestrator, S7).

Contrat : `docs/tool-brain-contracts.md` §14.4 (graine `ExecutionAdapter` / `default_adapters`) et §15. Chaque
adaptateur est **la seule entrée de mutation de son outil** et parle au propriétaire canonique : la scène, par
`run_scene_plan` (`SceneService.apply_if`, lecture et écriture sous le même verrou, acteur `SceneActor.BRAIN`). Les
plans réutilisent le code des outils MCP existants (`display_mcp` : `_update_command`, `_merged_payload`, `_geometry`,
`selection_of`...) et le domaine pur des surfaces (`browser_surface`) : une règle, un endroit.

| Outil | Adaptateur | Commande de domaine |
| --- | --- | --- |
| `scene_update_object` | `SceneUpdateObjectAdapter` | `set_visibility`, `set_geometry`, `set_representation` ou `patch_object` |
| `scene_update_many` | `SceneUpdateManyAdapter` | `patch_selection` (garde « masquer la moitié » comme l'outil MCP) |
| `scene_pin` | `ScenePinAdapter` | `pin_selection` / `unpin_selection` |
| `scene_link` / `scene_unlink` | `SceneLinkAdapter` / `SceneUnlinkAdapter` | `link` / `unlink` |
| `surface_open/focus/scroll/history/zoom` | `SurfaceAdapter` | plans de `browser_surface` (`upsert_object` / `patch_object`) |

`scene_archive` (S8) est exécutable **seulement** à travers `DestructiveGuard` (voir `tool_brain_guardrails`).

**Hors du jeu exécutable** (documenté, testé) : `scene_create_object` et
`scene_add_artifact` (produire du contenu est le travail de Jarvis), tous les outils de lecture. Les arguments
`prefab` et `source_path` de `scene_update_object` sont refusés (`unsupported_argument`) : un état de prefab ne s'écrit
que par les verbes de surface, qui valident leurs adresses.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable, Mapping

from jarvis.domain.browser_surface import (
    plan_focus, plan_history, plan_open, plan_scroll, plan_zoom, surface_id_of,
)
from jarvis.domain.scene import (
    RelationKind, Representation, SceneActor, SceneCommand, SceneObjectFields, SceneOp, ScenePayload, SceneRelation,
    SceneSnapshot, Visibility,
)
from jarvis.domain.scene_batch import SelectionChanges
from jarvis.domain.scene_selection import resolve_selection
from jarvis.runtime.tool_brain_executor import (
    REFUSED, AdapterOutcome, ExecContext, ExecutionAdapter, PlanRefused, PlanUnchanged, ScenePlanner, _selection, run_scene_plan,
)

UNSUPPORTED_ARGUMENT = "unsupported_argument"
SELECTION_TOO_BROAD = "selection_too_broad"

#: Arguments de `scene_update_object` que le Tool Brain n'écrit pas (voir l'en-tête).
_UPDATE_OBJECT_FORBIDDEN = ("prefab", "source_path")


class _SceneToolAdapter:
    """Base : `build(arguments) -> plan`, exécuté par `run_scene_plan` (un seul chemin d'écriture)."""

    def __init__(self, scene: Any) -> None:
        self._scene = scene

    def build(self, arguments: Mapping[str, Any]) -> ScenePlanner:  # pragma: no cover - interface
        raise NotImplementedError

    async def execute(self, arguments: Mapping[str, Any], context: ExecContext) -> AdapterOutcome:
        return await run_scene_plan(self._scene, context, self.build(arguments), extra=self.extra(arguments))

    def extra(self, arguments: Mapping[str, Any]) -> Mapping[str, Any] | None:
        return None


class SceneUpdateObjectAdapter(_SceneToolAdapter):
    """`scene_update_object` : montrer, masquer, déplacer, redimensionner, replier/déplier, couche, ordre, titre."""

    async def execute(self, arguments: Mapping[str, Any], context: ExecContext) -> AdapterOutcome:
        forbidden = [name for name in _UPDATE_OBJECT_FORBIDDEN if arguments.get(name) is not None]
        if forbidden:
            return AdapterOutcome(REFUSED, UNSUPPORTED_ARGUMENT,
                                  {"detail": f"the Tool Brain does not write {forbidden}; use the surface tools for prefab state"})
        return await super().execute(arguments, context)

    def build(self, arguments: Mapping[str, Any]) -> ScenePlanner:
        from jarvis.runtime.display_mcp import SceneDisplayTools, _geometry, _items, _merged_payload, check_annotation

        def plan(snapshot: SceneSnapshot) -> SceneCommand:
            object_id = arguments["object_id"]
            geometry = _geometry(arguments.get("geometry"))
            representation = Representation(arguments["representation"]) if arguments.get("representation") is not None else None
            visibility = Visibility(arguments["visibility"]) if arguments.get("visibility") is not None else None
            items = _items(arguments.get("items"))
            annotation = arguments.get("annotation")
            if annotation is not None:
                check_annotation(annotation)
            category, layer, order = arguments.get("category"), arguments.get("layer"), arguments.get("order")
            title, summary = arguments.get("title"), arguments.get("summary")
            payload_given = any(value is not None for value in (title, summary, items, annotation))
            if not (payload_given or any(value is not None for value in
                                         (category, representation, geometry, layer, order, visibility))):
                raise ValueError("nothing to change: give at least one field")
            payload = None
            if payload_given:
                current = snapshot.get_object(object_id)
                payload = _merged_payload(current.payload if current is not None else ScenePayload(), title=title,
                                          summary=summary, items=items, annotation=annotation)
            return SceneDisplayTools._update_command(object_id, category, payload, representation, geometry, layer, order,
                                                     visibility)

        return plan

    def extra(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"object_id": arguments.get("object_id")}


class SceneUpdateManyAdapter(_SceneToolAdapter):
    """`scene_update_many` : même changement sur un ensemble, une commande `patch_selection` (tout ou rien)."""

    def build(self, arguments: Mapping[str, Any]) -> ScenePlanner:
        from jarvis.runtime.display_mcp import BATCH_HIDE_GUARD_MIN, BATCH_HIDE_GUARD_RATIO, check_annotation

        def plan(snapshot: SceneSnapshot) -> SceneCommand:
            selection = _selection(arguments)
            annotation = arguments.get("annotation")
            if annotation is not None:
                check_annotation(annotation)
            changes = SelectionChanges(
                visibility=Visibility(arguments["visibility"]) if arguments.get("visibility") is not None else None,
                representation=(Representation(arguments["representation"])
                                if arguments.get("representation") is not None else None),
                category=arguments.get("category"), layer=arguments.get("layer"), order=arguments.get("order"),
                annotation=annotation)
            if changes.visibility is Visibility.HIDDEN and arguments.get("confirm") is not True:
                resolution = resolve_selection(snapshot, selection)
                if not resolution.refusals(archived_ok=False):
                    members = set(resolution.eligible_ids)
                    hiding = sum(1 for item in snapshot.objects
                                 if item.object_id in members and item.visibility is Visibility.VISIBLE)
                    visible = sum(1 for item in snapshot.objects if item.visibility is Visibility.VISIBLE)
                    if hiding >= BATCH_HIDE_GUARD_MIN and hiding >= visible * BATCH_HIDE_GUARD_RATIO:
                        raise PlanRefused(SELECTION_TOO_BROAD, f"this batch would hide {hiding} of the {visible} visible objects")
            return SceneCommand(op=SceneOp.PATCH_SELECTION, actor=SceneActor.BRAIN, selection=selection, changes=changes)

        return plan


class ScenePinAdapter(_SceneToolAdapter):
    """`scene_pin` : `pin_selection` / `unpin_selection`."""

    def build(self, arguments: Mapping[str, Any]) -> ScenePlanner:
        def plan(_snapshot: SceneSnapshot) -> SceneCommand:
            pinned = arguments.get("pinned")
            if not isinstance(pinned, bool):
                raise TypeError("pinned must be a boolean")
            return SceneCommand(op=SceneOp.PIN_SELECTION if pinned else SceneOp.UNPIN_SELECTION,
                                actor=SceneActor.BRAIN, selection=_selection(arguments))

        return plan


class SceneArchiveAdapter(_SceneToolAdapter):
    """`scene_archive` : retrait définitif (`archive_selection`), **par ids explicites seulement**.

    Irréversible : l'exécuteur ne l'appelle qu'après `DestructiveGuard.check` (S8). Le détail rend un reçu (id, nature,
    titre) des objets retirés : l'archive enterre l'id, le reçu permet de reconstituer ce qui a été retiré.
    """

    async def execute(self, arguments: Mapping[str, Any], context: ExecContext) -> AdapterOutcome:
        if arguments.get("select") is not None:
            return AdapterOutcome(REFUSED, UNSUPPORTED_ARGUMENT, {"detail": "the Tool Brain archives by object_ids only"})
        receipt: list[dict[str, Any]] = []
        extra: dict[str, Any] = {"archived": receipt}

        def plan(snapshot: SceneSnapshot) -> SceneCommand:
            selection = _selection(arguments)
            for object_id in (selection.ids or ())[:8]:
                found = snapshot.get_object(object_id)
                if found is not None:
                    receipt.append({"id": object_id, "kind": found.kind.value,
                                    "title": str(getattr(found.payload, "title", "") or "")[:80]})
            return SceneCommand(op=SceneOp.ARCHIVE_SELECTION, actor=SceneActor.BRAIN, selection=selection)

        return await run_scene_plan(self._scene, context, plan, extra=extra)


class SceneLinkAdapter(_SceneToolAdapter):
    """`scene_link` : relier deux objets (`explains`, `groups`, `parent_of`) ; id dérivé quand absent."""

    def build(self, arguments: Mapping[str, Any]) -> ScenePlanner:
        from jarvis.runtime.display_mcp import _BRAIN_RELATION_ID, SceneDisplayTools

        def plan(snapshot: SceneSnapshot) -> SceneCommand:
            kind = RelationKind(arguments["kind"])
            from_id, to_id = arguments["from_id"], arguments["to_id"]
            relation_id = arguments.get("relation_id")
            if relation_id is not None and (not isinstance(relation_id, str) or not _BRAIN_RELATION_ID.match(relation_id)):
                raise ValueError("relation_id must start with 'brain-' (omit it to derive one)")
            rid = relation_id if relation_id is not None else SceneDisplayTools._relation_id(kind, from_id, to_id)
            layer = arguments.get("layer")
            relation = SceneRelation(relation_id=rid, kind=kind, from_id=from_id, to_id=to_id,
                                     **({"layer": layer} if layer is not None else {}))
            existing = snapshot.get_relation(rid)
            if layer is None and existing is not None and existing.endpoints == relation.endpoints:
                raise PlanUnchanged()  # même lien, couche de l'utilisateur gardée (même règle que l'outil MCP)
            return SceneCommand(op=SceneOp.LINK, actor=SceneActor.BRAIN, relation=relation)

        return plan


class SceneUnlinkAdapter(_SceneToolAdapter):
    """`scene_unlink` : retirer un lien que le cerveau a le droit de retirer (jamais ceux du runtime : le réducteur juge)."""

    def build(self, arguments: Mapping[str, Any]) -> ScenePlanner:
        def plan(_snapshot: SceneSnapshot) -> SceneCommand:
            return SceneCommand(op=SceneOp.UNLINK, actor=SceneActor.BRAIN, relation_id=arguments["relation_id"])

        return plan


class SurfaceAdapter(_SceneToolAdapter):
    """`surface_*` : plans purs de `browser_surface` appliqués sous le verrou de scène (voir §15)."""

    def __init__(self, scene: Any, tool: str, opaque: Callable[[], str] | None = None) -> None:
        super().__init__(scene)
        self._tool = tool
        self._opaque = opaque or (lambda: uuid.uuid4().hex[:12])

    def build(self, arguments: Mapping[str, Any]) -> ScenePlanner:
        tool, sid = self._tool, arguments.get("surface_id")

        def plan(snapshot: SceneSnapshot) -> SceneCommand:
            if tool == "surface_open":
                return plan_open(snapshot, arguments.get("url"), surface_id=sid, label=arguments.get("label"),
                                 note=arguments.get("note"), new_opaque=self._opaque() if sid is None else None)
            if tool == "surface_focus":
                return plan_focus(snapshot, sid)
            if tool == "surface_scroll":
                return plan_scroll(snapshot, sid, arguments.get("direction"))
            if tool == "surface_history":
                return plan_history(snapshot, sid, arguments.get("direction"))
            if tool == "surface_zoom":
                return plan_zoom(snapshot, sid, arguments.get("action"))
            raise ValueError(f"unknown surface tool {tool}")  # pragma: no cover - `scene_and_surface_adapters` is closed

        return plan

    async def execute(self, arguments: Mapping[str, Any], context: ExecContext) -> AdapterOutcome:
        created: list[str] = []

        def tracked(snapshot: SceneSnapshot) -> SceneCommand:
            command = self.build(arguments)(snapshot)
            created[:] = [command.object_id or ""]
            return command

        outcome = await run_scene_plan(self._scene, context, tracked)
        if created and outcome.status != REFUSED:
            return AdapterOutcome(outcome.status, outcome.code,
                                  {**dict(outcome.detail), "surface_id": surface_id_of(created[0]), "object_id": created[0]})
        return outcome


def scene_and_surface_adapters(scene: Any) -> dict[tuple[str, str], ExecutionAdapter]:
    """Les adaptateurs de S7 pour `default_adapters` + `scene_archive` (S8, gardé par l'exécuteur) ; aucune lecture."""

    adapters: dict[tuple[str, str], ExecutionAdapter] = {
        ("jarvis-display", "scene_update_object"): SceneUpdateObjectAdapter(scene),
        ("jarvis-display", "scene_update_many"): SceneUpdateManyAdapter(scene),
        ("jarvis-display", "scene_pin"): ScenePinAdapter(scene),
        ("jarvis-display", "scene_link"): SceneLinkAdapter(scene),
        ("jarvis-display", "scene_unlink"): SceneUnlinkAdapter(scene),
        ("jarvis-display", "scene_archive"): SceneArchiveAdapter(scene),  # S8: reachable only through DestructiveGuard
    }
    for tool in ("surface_open", "surface_focus", "surface_scroll", "surface_history", "surface_zoom"):
        adapters[("jarvis-surface", tool)] = SurfaceAdapter(scene, tool)
    return adapters


__all__ = [
    "SELECTION_TOO_BROAD", "SceneArchiveAdapter", "SceneLinkAdapter", "ScenePinAdapter", "SceneUnlinkAdapter", "SceneUpdateManyAdapter",
    "SceneUpdateObjectAdapter", "SurfaceAdapter", "UNSUPPORTED_ARGUMENT", "scene_and_surface_adapters",
]

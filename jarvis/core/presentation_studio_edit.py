"""API d'édition sémantique du Studio (handoff jarvis-interactive-presentation-studio, Slice 05).

**Une** porte pour la voix (acteur `brain`, outils MCP, Slice 21) et l'interface (acteur `user`, relais du Control
Center) : mêmes validations, même état canonique. Le vocabulaire, les niveaux et le moteur sont purs
(`jarvis/domain/presentation_studio_edit.py`) ; ce service ne fait que :

1. **lire** la variante (relecture du disque, jamais un cache) et comparer la base de l'appelant (`stale` sinon) ;
2. **lire les manifestes** des pins touchés (hors verrou) ;
3. **appliquer** la transaction sur une copie (le moteur ; la première opération refusée annule tout) ;
4. **valider** les scènes changées exactement comme `PUT .../variants/{id}` (`check_scenes` : pin existant, valeurs
   valides pour le manifeste via `PrefabService`, contrôles dans le manifeste) ;
5. en `commit` seulement, **écrire** par `write_variant` sous `expected_revision` : la comparaison de révision et le
   remplacement atomique du fichier sont sous le verrou du service, la validation (qui attend `PrefabService`) est
   **hors** verrou. Deux éditions de même base : l'une gagne, l'autre est `stale`, aucune mise à jour perdue ;
6. produire l'**enregistrement d'annulation** (opérations inverses + base ; l'anneau est la Slice 08), consigner les
   demandes de source (mémoire seulement, `pending_source_requests`, la Slice 06 les consomme) et poser l'évènement.

`preview` n'écrit rien : ni fichier, ni demande de source, ni évènement, ni enregistrement d'annulation.

Écriture de la scène globale : ce service ne touche **pas** à la fenêtre « stage » (Slice 12 la possède). Quand elle
patchera `prefab.data` d'un objet vivant, ce sera dans `SceneService.apply_if` (docs/07 §4.4), pas ici.

Diagnostics `core.presentation_studio.edit_{committed,previewed,refused,stale,source_recorded}` et
`controls_suggested` : ids, noms d'opération, niveau, acteur, comptes et code ; jamais une valeur, un titre ni une
intention. Une panne (disque, document corrompu) est tracée en `error` par le service de variante et remonte.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from jarvis.core.presentation_studio_service import PresentationStudioService
from jarvis.domain.prefab import PrefabManifest
from jarvis.domain.presentation_studio import PresentationVariant, VariantUpdate, new_scene_id
from jarvis.domain.presentation_studio_checks import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_edit import (
    UNSAFE_KEYS, ControlReset, ControlSet, EditMode, EditPlan, EditRefusal, EditRequest, EditResult, EditStatus,
    SceneAdd, SceneSetControls, SourceRequestRecord, StudioActor, actor_refusal, apply_ops,
    parse_edit_request, scenes_changed, undo_record,
)
from jarvis.domain.presentation_studio_scene import MAX_CONTROLS, StudioScene, suggest_controls
from jarvis.ports.v2 import DiagnosticSink

#: Demandes de source gardées en mémoire (bornées : la plus ancienne cède). Mémoire seulement, par conception :
#: la reconstruction est la Slice 06, aucun schéma de fichier n'est ajouté ici.
MAX_SOURCE_REQUESTS = 64


class PresentationStudioEditService:
    def __init__(self, studio: PresentationStudioService, *, diagnostics: DiagnosticSink | None = None,
                 events: Any | None = None, new_id: Callable[[], str] = new_scene_id) -> None:
        self._studio = studio
        self._diagnostics = diagnostics
        self._events = events
        self._new_id = new_id
        self._sources: deque[SourceRequestRecord] = deque(maxlen=MAX_SOURCE_REQUESTS)

    # ------------------------------------------------------------ lecture

    def pending_source_requests(self, presentation_id: str | None = None) -> tuple[SourceRequestRecord, ...]:
        """Les demandes de niveau 3 enregistrées (les plus anciennes d'abord), pour la Slice 06."""

        return tuple(r for r in self._sources if presentation_id is None or r.presentation_id == presentation_id)

    async def suggest_controls(self, presentation_id: str, variant_id: str, scene_id: str) -> dict[str, Any]:
        """Propose, **sans rien écrire**, les contrôles que le manifeste du pin permet et que la scène ne déclare pas encore.
        `apply` est une opération `scene.set_controls` prête à être envoyée (avec `basis`) : proposer n'est pas appliquer."""

        variant = await self._studio.get_variant(presentation_id, variant_id)
        scene = next((s for s in variant.scenes if s.scene_id == scene_id), None)
        if scene is None:
            raise PresentationStudioError(C.UNKNOWN_SCENE, f"{scene_id} is not a scene of this variant")
        catalog = self._studio.scene_catalog
        if catalog is None:
            raise PresentationStudioError(C.PREFAB_UNAVAILABLE, "no prefab catalog is wired: controls cannot be suggested")
        manifest = await catalog.manifest_of(scene)
        bound = {c.path for c in scene.controls}
        taken = {c.control_id for c in scene.controls}
        room = MAX_CONTROLS - len(scene.controls)
        fresh = []
        for control in suggest_controls(manifest):
            if control.path in bound or any(key in UNSAFE_KEYS for key in control.keys):
                continue
            control_id, suffix = control.control_id, 2
            while control_id in taken:
                control_id = f"{control.control_id[:36]}_{suffix}"
                suffix += 1
            taken.add(control_id)
            fresh.append(replace(control, control_id=control_id))
        proposals, truncated = fresh[:max(room, 0)], len(fresh) > max(room, 0)
        self._trace("core.presentation_studio.controls_suggested", "Controles proposes",
                    data={"presentation_id": presentation_id, "variant_id": variant_id, "scene_id": scene_id,
                          "declared": len(scene.controls), "proposed": len(proposals), "truncated": truncated})
        return {"presentation_id": presentation_id, "variant_id": variant_id, "scene_id": scene_id,
                "basis": {"variant_revision": variant.revision}, "declared": len(scene.controls),
                "proposals": [c.to_dict() for c in proposals], "truncated": truncated,
                "apply": SceneSetControls(scene_id, (*scene.controls, *proposals)).to_dict()}

    # ------------------------------------------------------------ édition

    async def edit(self, presentation_id: str, variant_id: str, raw: object) -> EditResult:
        """Une requête d'édition (corps `{actor, mode, basis, ops}`). Une requête mal formée, une présentation ou une
        variante inconnue et une panne de données lèvent `PresentationStudioError` (enveloppe d'erreur) ; un refus de
        l'édition elle-même est un `EditResult` `refused`/`stale`, rien n'étant alors écrit."""

        request = parse_edit_request(raw, new_id=self._new_id)
        variant = await self._studio.get_variant(presentation_id, variant_id)
        context = _Context(presentation_id, variant_id, request)
        if request.basis_revision != variant.revision:
            return self._not_applied(context, variant.revision, EditStatus.STALE, C.STALE_REVISION,
                                     f"the variant is at revision {variant.revision}, not {request.basis_revision}: "
                                     "read it again, then retry")
        refusal = actor_refusal(request.actor, request.ops)
        if refusal is not None:
            return self._refused(context, variant.revision, refusal)
        manifests = await self._manifests(variant, request)
        try:
            plan = apply_ops(variant.scenes, request.ops, manifests, presentation_id=presentation_id,
                             variant_id=variant_id, actor=request.actor, basis_revision=variant.revision)
        except EditRefusal as refusal:
            return self._refused(context, variant.revision, refusal)
        changed = scenes_changed(variant.scenes, plan.scenes)
        if changed:
            try:
                await self._studio.check_scenes(presentation_id, variant_id, plan.scenes, variant.scenes)
            except PresentationStudioError as exc:
                if exc.code is not C.SCENE_INCOMPATIBLE:
                    raise  # unavailable prefab, disk: a fault of ours, not a refusal of this edit
                return self._refused(context, variant.revision, EditRefusal(exc.code, exc.message))
        if request.mode is EditMode.PREVIEW:
            return self._applied(context, plan, variant.revision, changed, committed=False, undo=None, records=())
        return await self._commit(context, variant, plan, changed)

    async def _commit(self, context: "_Context", variant: PresentationVariant, plan: EditPlan,
                      changed: bool) -> EditResult:
        request, revision = context.request, variant.revision
        if changed:
            update = VariantUpdate(revision, variant.title, plan.scenes, variant.art_direction_id, variant.score_id)
            try:
                saved = await self._studio.write_variant(context.presentation_id, context.variant_id, update)
            except PresentationStudioError as exc:
                if exc.code is C.STALE_REVISION:  # another writer landed between our read and our write
                    return self._not_applied(context, revision, EditStatus.STALE, C.STALE_REVISION, exc.message)
                self._events_failed(context, exc.code.value, revision)
                raise
            revision = saved.revision
        undo = undo_record(plan, presentation_id=context.presentation_id, variant_id=context.variant_id,
                           restores_revision=variant.revision, applies_at_revision=revision) if changed else None
        records = self._record_sources(context, plan)
        result = self._applied(context, plan, revision, changed, committed=True, undo=undo, records=records)
        self._trace("core.presentation_studio.edit_committed", "Edition validee",
                    data={**context.summary(plan), "revision": revision, "changed": changed})
        if records:
            self._trace("core.presentation_studio.edit_source_recorded", "Demande de source enregistree",
                        data={"presentation_id": context.presentation_id, "variant_id": context.variant_id,
                              "requests": len(records)})
        self._events_committed(context, plan, revision, records)
        return result

    # ------------------------------------------------------------ interne

    async def _manifests(self, variant: PresentationVariant, request: EditRequest) -> dict[tuple[str, int], PrefabManifest]:
        """Le manifeste de chaque pin que les opérations touchent (lu hors verrou). Sans catalogue câblé : aucun, et les
        opérations qui en ont besoin sont refusées `prefab_unavailable` (jamais un contrôle présenté valide sans manifeste)."""

        catalog = self._studio.scene_catalog
        if catalog is None:
            return {}
        by_id = {scene.scene_id: scene for scene in variant.scenes}
        wanted: dict[tuple[str, int], StudioScene] = {}
        for op in request.ops:
            scene = op.scene if isinstance(op, SceneAdd) else \
                by_id.get(op.scene_id) if isinstance(op, (ControlSet, ControlReset, SceneSetControls)) else None
            if scene is not None:
                wanted.setdefault((scene.prefab.prefab_id, scene.prefab.version), scene)
        return {key: await catalog.manifest_of(scene) for key, scene in wanted.items()}

    def _record_sources(self, context: "_Context", plan: EditPlan) -> tuple[SourceRequestRecord, ...]:
        ids = [o["request_id"] for o in plan.outcomes if o.get("effect") == "recorded_only"]
        records = tuple(SourceRequestRecord(request_id, context.presentation_id, context.variant_id, op.scene_id,
                                            op.intent, context.request.actor.value, context.request.basis_revision)
                        for request_id, op in zip(ids, plan.sources))
        self._sources.extend(records)
        return records

    def _applied(self, context: "_Context", plan: EditPlan, revision: int, changed: bool, *, committed: bool,
                 undo: Mapping[str, Any] | None, records: tuple[SourceRequestRecord, ...]) -> EditResult:
        request = context.request
        if not committed:
            self._trace("core.presentation_studio.edit_previewed", "Edition apercue",
                        data={**context.summary(plan), "changed": changed})
        return EditResult(
            EditStatus.APPLIED, request.mode, request.actor, context.presentation_id, context.variant_id,
            request.basis_revision, revision, committed=committed, changed=changed, tier=plan.tier,
            ops=tuple(plan.outcomes), undo=undo,
            source_requests=tuple(r.to_dict(with_intent=False) for r in records)
            if committed else tuple({"request_id": o["request_id"], "scene_id": o["scene_id"], "recorded": False}
                                    for o in plan.outcomes if o.get("effect") == "recorded_only"))

    def _refused(self, context: "_Context", revision: int, refusal: EditRefusal) -> EditResult:
        status = EditStatus.STALE if refusal.stale else EditStatus.REFUSED
        return self._not_applied(context, revision, status, refusal.code, refusal.message, refusal.index)

    def _not_applied(self, context: "_Context", revision: int, status: EditStatus, code: C, message: str,
                     failed_index: int | None = None) -> EditResult:
        request = context.request
        self._trace("core.presentation_studio.edit_stale" if status is EditStatus.STALE
                    else "core.presentation_studio.edit_refused", "Edition non appliquee",
                    data={"presentation_id": context.presentation_id, "variant_id": context.variant_id,
                          "actor": request.actor.value, "mode": request.mode.value, "ops": list(request.op_names),
                          "code": code.value, "failed_index": failed_index})
        return EditResult(status, request.mode, request.actor, context.presentation_id, context.variant_id,
                          request.basis_revision, revision, code=code.value, message=message, failed_index=failed_index)

    def _events_committed(self, context: "_Context", plan: EditPlan, revision: int,
                          records: tuple[SourceRequestRecord, ...]) -> None:
        if self._events is None:
            return
        scene_ids = {o["scene_id"] for o in plan.outcomes if "scene_id" in o}
        try:
            self._events.committed(
                presentation_id=context.presentation_id, variant_id=context.variant_id, revision=revision,
                ops=context.request.op_names, tier=plan.tier.value, actor=context.request.actor.value,
                status="recorded" if records and not any(o.get("changed") for o in plan.outcomes) else "applied",
                scene_id=next(iter(scene_ids)) if len(scene_ids) == 1 else None,
                request_ids=[r.request_id for r in records])
        except Exception as exc:  # noqa: BLE001 - observability never undoes a committed edit; the failure is journaled
            self._trace("core.presentation_studio.event_failed", "Evenement d'edition non pose", level="warning",
                        data={"error_class": type(exc).__name__})

    def _events_failed(self, context: "_Context", code: str, revision: int) -> None:
        if self._events is None:
            return
        try:
            self._events.failed(presentation_id=context.presentation_id, variant_id=context.variant_id, code=code,
                                revision=revision)
        except Exception as exc:  # noqa: BLE001 - see above
            self._trace("core.presentation_studio.event_failed", "Evenement d'echec non pose", level="warning",
                        data={"error_class": type(exc).__name__})

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any]) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=dict(data))
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal never undoes a studio operation
            pass


class _Context:
    __slots__ = ("presentation_id", "variant_id", "request")

    def __init__(self, presentation_id: str, variant_id: str, request: EditRequest) -> None:
        self.presentation_id, self.variant_id, self.request = presentation_id, variant_id, request

    def summary(self, plan: EditPlan) -> dict[str, Any]:
        return {"presentation_id": self.presentation_id, "variant_id": self.variant_id,
                "actor": self.request.actor.value, "mode": self.request.mode.value,
                "ops": list(self.request.op_names), "tier": plan.tier.value}

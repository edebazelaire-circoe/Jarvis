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

Écriture de la scène globale : ce service ne touche **pas** à la fenêtre « stage » (Slice 12 la possède et la patche
dans `SceneService.apply_if`, docs/07 §4.4). Deux points d'appui lui sont offerts ici (Slice 12) :

- `render_overlay` : la même validation que l'aperçu (`mode: preview`), mais en rendant les **scènes** obtenues, par
  paquets de `MAX_OPS` enchaînés ; rien n'est écrit, aucun évènement, aucun enregistrement d'annulation. C'est ainsi que
  la lecture applique les `control_set` d'une partition **sans jamais écrire la variante** (R6) ;
- `add_commit_listener` : un abonné awaité après chaque commit qui a changé les scènes (édition, annuler, rétablir),
  pour que la fenêtre visible suive la variante canonique. Une panne d'abonné est tracée, jamais propagée.

Diagnostics `core.presentation_studio.edit_{committed,previewed,refused,stale,source_recorded}` et
`controls_suggested` : ids, noms d'opération, niveau, acteur, comptes et code ; jamais une valeur, un titre ni une
intention. Une panne (disque, document corrompu) est tracée en `error` par le service de variante et remonte.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

from jarvis.core.presentation_studio_service import PresentationStudioService
from jarvis.domain.prefab import PrefabManifest
from jarvis.domain.presentation_studio import PresentationVariant, VariantUpdate, dump_document, new_scene_id
from jarvis.domain.presentation_studio_checks import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_edit import (
    UNSAFE_KEYS, ControlReset, ControlSet, EditMode, EditPlan, EditRefusal, EditRequest, EditResult, EditStatus,
    MAX_OPS, RestoreValues, SceneAdd, SceneSetControls, SourceRequestRecord, StudioActor, actor_refusal, apply_ops,
    parse_edit_request, scenes_changed, undo_record,
)
from jarvis.domain.presentation_studio_history import HistoryDirection, HistoryStep, scenes_digest
from jarvis.domain.presentation_studio_scene import MAX_CONTROLS, StudioScene, suggest_controls
from jarvis.ports.v2 import DiagnosticSink

#: Demandes de source gardées en mémoire (bornées : la plus ancienne cède). Mémoire seulement, par conception :
#: la reconstruction est la Slice 06, aucun schéma de fichier n'est ajouté ici.
MAX_SOURCE_REQUESTS = 64


class EditHistory(Protocol):
    """Ce que le service d'édition demande à l'historique d'annulation (Slice 08, `PresentationStudioHistory`).

    Trois appels synchrones autour de **l'unique** écriture d'un commit : `begin` **avant** d'écrire (l'entrée et ses pins
    sont déjà tenus quand le document change : un pin qui quitte le document est déjà dans l'historique), puis `commit`
    après l'écriture réussie, ou `abort` si elle n'a pas eu lieu. Aucun n'écrit sur le disque."""

    def begin(self, presentation_id: str, variant_id: str, inverse: Sequence[Mapping[str, Any]],
              step: HistoryStep | None) -> object: ...

    def commit(self, ticket: object, *, actor: str, op_names: Sequence[str], tier: str, before_digest: str,
               after_digest: str, revision: int) -> None: ...

    def abort(self, ticket: object) -> None: ...


#: After a commit that changed the scenes: `(presentation_id, variant_id, revision)`. Awaited, failures traced.
CommitListener = Callable[[str, str, int], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class OverlayRender:
    """Outcome of `render_overlay`: the scenes with the overlay applied, or why not. Never written anywhere."""

    status: EditStatus
    scenes: tuple[StudioScene, ...] = ()
    code: str | None = None
    message: str | None = None
    failed_index: int | None = None


class PresentationStudioEditService:
    def __init__(self, studio: PresentationStudioService, *, diagnostics: DiagnosticSink | None = None,
                 events: Any | None = None, new_id: Callable[[], str] = new_scene_id,
                 history: EditHistory | None = None) -> None:
        self._studio = studio
        self._diagnostics = diagnostics
        self._events = events
        self._history = history
        self._new_id = new_id
        self._sources: deque[SourceRequestRecord] = deque(maxlen=MAX_SOURCE_REQUESTS)
        self._listeners: list[CommitListener] = []

    def add_commit_listener(self, listener: CommitListener) -> None:
        self._listeners.append(listener)

    # ------------------------------------------------------------ lecture

    async def render_overlay(self, presentation_id: str, variant_id: str, basis_revision: int,
                             ops: Sequence[Mapping[str, Any]], *, actor: StudioActor = StudioActor.USER) -> OverlayRender:
        """The variant's scenes with `ops` applied, **in memory only** (the playback overlay, Slice 12).

        Same engine and same checks as `edit(mode=preview)` (`apply_ops`, `check_scenes`, the actor table): a value the
        control or the pinned manifest refuses is refused here. `ops` may exceed `MAX_OPS`: they are applied in order,
        in chunks, each chunk on the output of the previous one. A base that moved is `stale`."""

        variant = await self._studio.get_variant(presentation_id, variant_id)
        if basis_revision != variant.revision:
            return OverlayRender(EditStatus.STALE, code=C.STALE_REVISION.value,
                                 message=f"the variant is at revision {variant.revision}, not {basis_revision}")
        scenes = variant.scenes
        for start in range(0, len(ops), MAX_OPS):
            chunk = list(ops[start:start + MAX_OPS])
            request = parse_edit_request({"actor": actor.value, "mode": "preview",
                                          "basis": {"variant_revision": variant.revision}, "ops": chunk},
                                         new_id=self._new_id)
            refusal = actor_refusal(request.actor, request.ops)
            if refusal is None:
                manifests = await self._studio.guarded(
                    "edit_manifests", presentation_id, self._manifests(replace(variant, scenes=scenes), request))
                try:
                    scenes = apply_ops(scenes, request.ops, manifests, presentation_id=presentation_id,
                                       variant_id=variant_id, actor=request.actor, basis_revision=variant.revision).scenes
                except EditRefusal as caught:
                    refusal = caught
            if refusal is not None:
                index = None if refusal.index is None else start + refusal.index
                return OverlayRender(EditStatus.STALE if refusal.stale else EditStatus.REFUSED, code=refusal.code.value,
                                     message=refusal.message, failed_index=index)
        if scenes_changed(variant.scenes, scenes):
            try:
                await self._studio.check_scenes(presentation_id, variant_id, scenes, variant.scenes)
            except PresentationStudioError as exc:
                if exc.code is not C.SCENE_INCOMPATIBLE:
                    raise
                return OverlayRender(EditStatus.REFUSED, code=exc.code.value, message=exc.message)
        self._trace("core.presentation_studio.overlay_rendered", "Valeurs de lecture appliquees en memoire",
                    data={"presentation_id": presentation_id, "variant_id": variant_id, "ops": len(ops),
                          "revision": variant.revision, "written": False})
        return OverlayRender(EditStatus.APPLIED, scenes)

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
        manifest = await self._studio.guarded("suggest_manifest", presentation_id, catalog.manifest_of(scene))
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

    async def edit(self, presentation_id: str, variant_id: str, raw: object, *,
                   step: HistoryStep | None = None) -> EditResult:
        """Une requête d'édition (corps `{actor, mode, basis, ops}`). Une requête mal formée, une présentation ou une
        variante inconnue et une panne de données lèvent `PresentationStudioError` (enveloppe d'erreur) ; un refus de
        l'édition elle-même est un `EditResult` `refused`/`stale`, rien n'étant alors écrit.

        `step` : réservé à l'historique (Slice 08) quand ce commit **est** un annuler ou un rétablir. Seul
        `PresentationStudioHistory` le passe ; il n'est **jamais** lu d'un corps de requête (`parse_edit_request` refuse
        toute clé inconnue, testé par Core, relais, `/undo` et client typé)."""

        request = parse_edit_request(raw, new_id=self._new_id)
        variant = await self._studio.get_variant(presentation_id, variant_id)
        context = _Context(presentation_id, variant_id, request, step)
        if request.basis_revision != variant.revision:
            return self._not_applied(context, variant.revision, EditStatus.STALE, C.STALE_REVISION,
                                     f"the variant is at revision {variant.revision}, not {request.basis_revision}: "
                                     "read it again, then retry")
        refusal = actor_refusal(request.actor, request.ops)
        if refusal is not None:
            return replace(self._refused(context, variant.revision, refusal), refusal_kind="authority")
        manifests = await self._studio.guarded("edit_manifests", presentation_id, self._manifests(variant, request))
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
        if changed:
            try:  # the document limit a commit would hit is a refusal of the preview too (same answer in both modes)
                dump_document(replace(variant, scenes=plan.scenes, revision=variant.revision + 1).to_document())
            except PresentationStudioError as exc:
                if exc.code not in (C.LIMIT_REACHED, C.INVALID_PRESENTATION):
                    raise
                return self._refused(context, variant.revision, EditRefusal(exc.code, exc.message))
        if request.mode is EditMode.PREVIEW:
            return self._applied(context, plan, variant.revision, changed, committed=False, undo=None, records=())
        return await self._commit(context, variant, plan, changed)

    async def _commit(self, context: "_Context", variant: PresentationVariant, plan: EditPlan,
                      changed: bool) -> EditResult:
        request, revision = context.request, variant.revision
        if changed:
            update = VariantUpdate(revision, variant.title, plan.scenes, variant.art_direction_id, variant.score_id)
            # History first: the inverse and its pins are held BEFORE the document stops holding them (docs/prefabs.md,
            # pin registry rule). Released when the write does not happen.
            ticket = None if self._history is None else self._history.begin(
                context.presentation_id, context.variant_id, plan.inverse, context.step)
            written = False
            try:
                saved = await self._studio.write_variant(context.presentation_id, context.variant_id, update)
                written = True
            except PresentationStudioError as exc:
                if exc.code is C.STALE_REVISION:  # another writer landed between our read and our write
                    return self._not_applied(context, revision, EditStatus.STALE, C.STALE_REVISION, exc.message)
                self._events_failed(context, exc.code.value, revision)
                raise
            finally:
                if not written and ticket is not None:
                    self._history.abort(ticket)  # type: ignore[union-attr]
            revision = saved.revision
            if ticket is not None:
                self._history.commit(  # type: ignore[union-attr]
                    ticket, actor=request.actor.value, op_names=request.op_names, tier=plan.tier.value,
                    before_digest=scenes_digest(variant.scenes), after_digest=scenes_digest(plan.scenes),
                    revision=revision)
        undo = undo_record(plan, presentation_id=context.presentation_id, variant_id=context.variant_id,
                           restores_revision=variant.revision, applies_at_revision=revision) if changed else None
        records, dropped = self._record_sources(context, plan)
        result = self._applied(context, plan, revision, changed, committed=True, undo=undo, records=records,
                               dropped=dropped)
        # a no-op commit is no new fact (and would reuse the previous revision's event id)
        event_id = self._events_committed(context, plan, revision, records) if changed or records else None
        self._trace("core.presentation_studio.edit_committed", "Edition validee",
                    data={**context.summary(plan), "revision": revision, "changed": changed,
                          "event_recorded": event_id is not None})
        if records:
            self._trace("core.presentation_studio.edit_source_recorded", "Demande de source gardee en memoire (non durable)",
                        data={"presentation_id": context.presentation_id, "variant_id": context.variant_id,
                              "requests": len(records), "durable": False})
        if changed:
            await self._notify_commit(context, revision)
        if dropped:
            self._trace("core.presentation_studio.source_requests_dropped", "Demandes de source evincees de la memoire",
                        level="warning", data={"presentation_id": context.presentation_id, "dropped": dropped,
                                               "capacity": MAX_SOURCE_REQUESTS})
        return result

    # ------------------------------------------------------------ interne

    async def _notify_commit(self, context: "_Context", revision: int) -> None:
        for listener in tuple(self._listeners):
            try:
                await listener(context.presentation_id, context.variant_id, revision)
            except Exception as exc:  # noqa: BLE001 - a listener (the playback stage follower) never undoes a committed edit; traced
                self._trace("core.presentation_studio.commit_listener_failed", "Abonne de commit en echec",
                            level="warning", data={"presentation_id": context.presentation_id,
                                                   "variant_id": context.variant_id, "revision": revision,
                                                   "error_class": type(exc).__name__})

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
                by_id.get(op.scene_id) if isinstance(op, (ControlSet, ControlReset, SceneSetControls, RestoreValues)) else None
            if scene is not None:
                wanted.setdefault((scene.prefab.prefab_id, scene.prefab.version), scene)
        return {key: await catalog.manifest_of(scene) for key, scene in wanted.items()}

    def _record_sources(self, context: "_Context", plan: EditPlan) -> tuple[tuple[SourceRequestRecord, ...], int]:
        """Garde les demandes (mémoire, bornée) et dit combien de plus anciennes ont dû céder : jamais en silence."""

        ids = [o["request_id"] for o in plan.outcomes if o.get("effect") == "recorded_only"]
        records = tuple(SourceRequestRecord(request_id, context.presentation_id, context.variant_id, op.scene_id,
                                            op.intent, context.request.actor.value, context.request.basis_revision)
                        for request_id, op in zip(ids, plan.sources))
        dropped = max(0, len(self._sources) + len(records) - MAX_SOURCE_REQUESTS)
        self._sources.extend(records)
        return records, dropped

    def _applied(self, context: "_Context", plan: EditPlan, revision: int, changed: bool, *, committed: bool,
                 undo: Mapping[str, Any] | None, records: tuple[SourceRequestRecord, ...],
                 dropped: int = 0) -> EditResult:
        request = context.request
        if not committed:
            self._trace("core.presentation_studio.edit_previewed", "Edition apercue",
                        data={**context.summary(plan), "changed": changed})
        return EditResult(
            EditStatus.APPLIED, request.mode, request.actor, context.presentation_id, context.variant_id,
            request.basis_revision, revision, committed=committed, changed=changed, tier=plan.tier,
            ops=tuple(plan.outcomes), undo=undo,
            source_requests=tuple({**r.to_dict(with_intent=False), "durable": False} for r in records)
            if committed else tuple({"request_id": o["request_id"], "scene_id": o["scene_id"], "recorded": False}
                                    for o in plan.outcomes if o.get("effect") == "recorded_only"),
            source_requests_dropped=dropped)

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
                          records: tuple[SourceRequestRecord, ...]) -> str | None:
        if self._events is None:
            return None
        scene_ids = {o["scene_id"] for o in plan.outcomes if "scene_id" in o}
        try:
            return self._events.committed(
                presentation_id=context.presentation_id, variant_id=context.variant_id, revision=revision,
                ops=context.request.op_names, tier=plan.tier.value, actor=context.request.actor.value,
                status=_event_status(context, records, plan),
                scene_id=next(iter(scene_ids)) if len(scene_ids) == 1 else None,
                request_ids=[r.request_id for r in records])
        except Exception as exc:  # noqa: BLE001 - observability never undoes a committed edit; the failure is journaled
            self._trace("core.presentation_studio.event_failed", "Evenement d'edition non pose", level="warning",
                        data={"error_class": type(exc).__name__})
            return None

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


def _event_status(context: "_Context", records: tuple[SourceRequestRecord, ...], plan: EditPlan) -> str:
    if context.step is not None:
        return "undone" if context.step.direction is HistoryDirection.UNDO else "redone"
    return "recorded_in_memory" if records and not any(o.get("changed") for o in plan.outcomes) else "applied"


class _Context:
    __slots__ = ("presentation_id", "variant_id", "request", "step")

    def __init__(self, presentation_id: str, variant_id: str, request: EditRequest,
                 step: HistoryStep | None = None) -> None:
        self.presentation_id, self.variant_id, self.request, self.step = presentation_id, variant_id, request, step

    def summary(self, plan: EditPlan) -> dict[str, Any]:
        return {"presentation_id": self.presentation_id, "variant_id": self.variant_id,
                "actor": self.request.actor.value, "mode": self.request.mode.value,
                "ops": list(self.request.op_names), "tier": plan.tier.value}

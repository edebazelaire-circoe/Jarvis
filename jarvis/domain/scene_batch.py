"""Commandes de sélection atomiques (handoff jarvis-mcp-semantic-batch-inspector, Slice 03).

Contrat : `docs/scene-selection-batch.md` §3–§5. Module pur, sans E/S.

Une commande de sélection (`patch_selection`, `translate_selection`,
`pin_selection`, `unpin_selection`, `archive_selection`) désigne ses membres
par une `SceneSelection` ; le réducteur (`apply_scene_command`) la résout,
valide chaque membre et écrit **sur le même instantané** :

1. matrice `ALLOWED_SCENE_OPS` (`runtime` : `op_not_allowed`) ;
2. résolution (`resolve_selection`) : toute référence ou tout id fautif
   refuse la commande entière, chaque fautif listé en ordre canonique ;
3. plan de chaque membre ; un refus de membre refuse tout ;
4. aucun membre ne change → `duplicate`, ni révision ni patch ;
5. sinon **un** `ScenePatch`, révision + 1, ops dans l'ordre canonique des
   membres (signaux de cascade avant leur étoile).

Jamais d'application partielle, jamais plusieurs révisions. Le résultat
porte toujours un `SceneBatchReport` (`SceneUpdate.batch`), refus compris.

Les planificateurs réutilisent ceux d'un objet (`_plan_object_write`,
`_with_cascade`, `_archive_ops` de `scene.py`) : même autorité par champ,
même cascade, pas de seconde règle. `scene.py` n'importe ce module qu'à
l'appel (`scene_selection` dépend de `scene`).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any, Callable

from jarvis.domain._checks import check_text, check_token
from jarvis.domain.scene import (
    ALLOWED_SCENE_OPS,
    MAX_ANNOTATION_CHARS,
    MAX_CATEGORY_CHARS,
    MAX_PATCH_OPS,
    MAX_REVISION,
    MAX_SCENE_EXTENT,
    SCENE_SAFE_AREA,
    PatchOpKind,
    Representation,
    SceneCommand,
    SceneCommandOutcome,
    SceneGeometry,
    SceneObject,
    SceneObjectFields,
    SceneOp,
    ScenePatch,
    ScenePatchOp,
    SceneRefusal,
    SceneSnapshot,
    SceneUpdate,
    Visibility,
    _archive_ops,
    _check_layer,
    _check_order,
    _plan_object_write,
    _Refused,
    _with_cascade,
    apply_scene_patch,
    check_wire_keys,
    parse_enum,
    signal_owners,
)
from jarvis.domain.scene_selection import (
    SceneSelection,
    SelectionMode,
    SelectionRefusal,
    SelectionResolution,
    SelectionSkip,
    resolve_selection,
)

#: Opérations qui exigent un membre placé : un id explicite sans géométrie
#: refuse tout, un membre de filtre sans géométrie est écarté (§3.2).
_REQUIRE_PLACED = frozenset({SceneOp.TRANSLATE_SELECTION, SceneOp.PIN_SELECTION})
#: Grille de l'écart effectif : le dixième d'unité de la page (`QUANTUM`).
DELTA_QUANTUM = 10


# ------------------------------------------------------------------ arguments


_CHANGES_KEYS = frozenset({"visibility", "representation", "category", "layer", "order", "annotation"})


@dataclass(frozen=True, slots=True)
class SelectionChanges:
    """`changes` de `patch_selection` (§5.1) : au moins un champ, tous facultatifs.

    Ni titre, résumé, entrées (un même contenu sur plusieurs objets n'a pas
    d'intention réelle), ni géométrie absolue (`translate_selection`), ni
    `exec_state` / `work_ref` / `kind`. `annotation` est fusionnée dans la
    charge actuelle de chaque membre ; `""` la retire.
    """

    visibility: Visibility | None = None
    representation: Representation | None = None
    category: str | None = None
    layer: int | None = None
    order: int | None = None
    annotation: str | None = None

    def __post_init__(self) -> None:
        if self.visibility is not None and not isinstance(self.visibility, Visibility):
            raise TypeError("changes.visibility must be a Visibility")
        if self.representation is not None and not isinstance(self.representation, Representation):
            raise TypeError("changes.representation must be a Representation")
        if self.category is not None:
            check_token("changes.category", self.category, MAX_CATEGORY_CHARS, required=True)
        if self.layer is not None:
            _check_layer(self.layer)
        if self.order is not None:
            _check_order(self.order)
        if self.annotation is not None:
            check_text("changes.annotation", self.annotation, MAX_ANNOTATION_CHARS)
        if all(getattr(self, name) is None for name in _CHANGES_KEYS):
            raise ValueError("changes names at least one field")

    def to_payload(self) -> dict[str, Any]:
        wire: dict[str, Any] = {}
        for name in ("visibility", "representation"):
            if getattr(self, name) is not None:
                wire[name] = getattr(self, name).value
        for name in ("category", "layer", "order", "annotation"):
            if getattr(self, name) is not None:
                wire[name] = getattr(self, name)
        return wire

    @classmethod
    def from_payload(cls, payload: object) -> SelectionChanges:
        data = check_wire_keys("changes", payload, frozenset(), _CHANGES_KEYS)
        return cls(
            visibility=None if "visibility" not in data else parse_enum(Visibility, data["visibility"], "visibility"),
            representation=(None if "representation" not in data
                            else parse_enum(Representation, data["representation"], "representation")),
            category=data.get("category"),
            layer=data.get("layer"),
            order=data.get("order"),
            annotation=data.get("annotation"),
        )


def _check_axis(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    try:
        number = float(value)
    except OverflowError:
        raise ValueError(f"{name} is out of range") from None
    if not math.isfinite(number) or abs(number) > MAX_SCENE_EXTENT:
        raise ValueError(f"{name} must be a finite number within ±{MAX_SCENE_EXTENT:g}")
    return number


@dataclass(frozen=True, slots=True)
class SceneDelta:
    """Écart relatif `{dx, dy}` en unités de scène (§5.2). `(0, 0)` est refusé au décodage."""

    dx: float
    dy: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "dx", _check_axis("delta.dx", self.dx))
        object.__setattr__(self, "dy", _check_axis("delta.dy", self.dy))
        if self.dx == 0 and self.dy == 0:
            raise ValueError("delta (0, 0) moves nothing")

    def to_payload(self) -> dict[str, Any]:
        return {"dx": self.dx, "dy": self.dy}

    @classmethod
    def from_payload(cls, payload: object) -> SceneDelta:
        data = check_wire_keys("delta", payload, frozenset({"dx", "dy"}))
        return cls(dx=data["dx"], dy=data["dy"])


# ------------------------------------------------------------------ rapport


@dataclass(frozen=True, slots=True)
class BatchDelta:
    """Écart demandé, écart effectif commun, et s'il a été borné (`translate_selection`)."""

    requested: tuple[float, float]
    effective: tuple[float, float]
    clamped: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "requested": {"dx": self.requested[0], "dy": self.requested[1]},
            "effective": {"dx": self.effective[0], "dy": self.effective[1]},
            "clamped": self.clamped,
        }


@dataclass(frozen=True, slots=True)
class SceneBatchReport:
    """Compte rendu d'une commande de sélection (§4.1), sur le fil sous `batch`.

    Appliquée ou `duplicate` : `changed ∪ unchanged ∪ skipped.id = matched`,
    deux à deux disjoints ; `applied` ⇔ `changed_ids` non vide. Refusée :
    `refused` liste chaque fautif (références puis ids, ordre canonique), et
    rien d'autre n'est promis. Listes complètes (≤ 512) : le plafond à 20 est
    celui du résultat MCP (Slice 05).
    """

    op: SceneOp
    mode: SelectionMode
    matched_ids: tuple[str, ...] = ()
    hidden_count: int = 0
    changed_ids: tuple[str, ...] = ()
    unchanged_ids: tuple[str, ...] = ()
    skipped: tuple[SelectionSkip, ...] = ()
    refused: tuple[SelectionRefusal, ...] = ()
    cascade_ids: tuple[str, ...] = ()
    delta: BatchDelta | None = None

    def to_payload(self) -> dict[str, Any]:
        wire: dict[str, Any] = {
            "mode": self.mode.value,
            "matched_ids": list(self.matched_ids),
            "hidden_count": self.hidden_count,
            "changed_ids": list(self.changed_ids),
            "unchanged_ids": list(self.unchanged_ids),
            "skipped": [entry.to_payload() for entry in self.skipped],
            "refused": [entry.to_payload() for entry in self.refused],
        }
        if self.op is SceneOp.ARCHIVE_SELECTION:
            wire["cascade_ids"] = list(self.cascade_ids)
        if self.op is SceneOp.TRANSLATE_SELECTION:
            wire["delta"] = self.delta.to_payload() if self.delta is not None else None
        return wire


# ------------------------------------------------------------------ translation


def _toward_zero(value: float) -> float:
    """Au dixième, vers zéro : l'écart ne repasse jamais la borne (même tolérance que la page)."""

    if value >= 0:
        return math.floor(value * DELTA_QUANTUM + 1e-9) / DELTA_QUANTUM
    return math.ceil(value * DELTA_QUANTUM - 1e-9) / DELTA_QUANTUM


def group_delta(boxes: list[SceneGeometry], dx: float, dy: float) -> tuple[float, float]:
    """Écart effectif **commun** d'un groupe rigide (§5.2).

    Bornes = `SCENE_SAFE_AREA` élargie à la boîte englobante du groupe (règle
    « jamais pire » : un groupe déjà dehors n'est pas forcé de rentrer et ne
    peut pas sortir davantage). Borné axe par axe, puis quantifié au dixième
    vers zéro. Sans membre, rien ne bouge. Même calcul que `groupDelta` de la
    page (`control_center_scene_interact.js`).
    """

    if not boxes:
        return 0.0, 0.0
    x0 = min(box.x for box in boxes)
    y0 = min(box.y for box in boxes)
    x1 = max(box.x + box.w for box in boxes)
    y1 = max(box.y + box.h for box in boxes)
    sx0, sy0, sx1, sy1 = SCENE_SAFE_AREA
    bx0, by0, bx1, by1 = min(sx0, x0), min(sy0, y0), max(sx1, x1), max(sy1, y1)
    edx = min(max(dx, min(0.0, bx0 - x0)), max(0.0, bx1 - x1))
    edy = min(max(dy, min(0.0, by0 - y0)), max(0.0, by1 - y1))
    return _toward_zero(edx) + 0.0, _toward_zero(edy) + 0.0


# ------------------------------------------------------------------ planification


@dataclass(slots=True)
class _Plan:
    ops: list[ScenePatchOp]
    changed: list[str]
    unchanged: list[str]
    cascade: tuple[str, ...] = ()
    delta: BatchDelta | None = None


class _MemberRefusals(Exception):
    """Refus d'au moins un membre : toute la commande tombe, chaque fautif listé."""

    def __init__(self, outcome: SceneCommandOutcome, entries: list[SelectionRefusal]) -> None:
        super().__init__(entries[0].reason.value)
        self.outcome = outcome
        self.entries = entries


def _member_states(snapshot: SceneSnapshot, command: SceneCommand, members: tuple[str, ...],
                   fields_of: Callable[[str], SceneObjectFields], mode: SelectionMode) -> dict[str, SceneObject]:
    """État voulu de chaque membre par `_plan_object_write` (même autorité par champ qu'un objet seul).

    Tous les membres sont évalués avant de refuser : chaque fautif est listé.
    Un membre inchangé garde son objet actuel.
    """

    objects = {item.object_id: item for item in snapshot.objects}
    states: dict[str, SceneObject] = {}
    refused: list[SelectionRefusal] = []
    outcome: SceneCommandOutcome | None = None
    for object_id in members:
        try:
            planned = _plan_object_write(snapshot, command.actor, object_id, fields_of(object_id), create=False)
        except _Refused as exc:
            outcome = outcome or exc.outcome
            refused.append(SelectionRefusal(object_id, exc.reason, "ids" if mode is SelectionMode.EXPLICIT else None))
            continue
        states[object_id] = planned[0].object if planned else objects[object_id]  # type: ignore[assignment]
    if refused:
        assert outcome is not None
        raise _MemberRefusals(outcome, refused)
    return states


def _plan_states(snapshot: SceneSnapshot, members: tuple[str, ...], states: dict[str, SceneObject]) -> _Plan:
    """Un `put_object` par membre changé, dans l'ordre canonique des membres."""

    ops: list[ScenePatchOp] = []
    changed: list[str] = []
    unchanged: list[str] = []
    for object_id in members:
        after = states[object_id]
        if after == snapshot.get_object(object_id):
            unchanged.append(object_id)
        else:
            ops.append(ScenePatchOp(PatchOpKind.PUT_OBJECT, object=after))
            changed.append(object_id)
    return _Plan(ops, changed, unchanged)


def _plan_patch(snapshot: SceneSnapshot, command: SceneCommand, resolution: SelectionResolution) -> _Plan:
    changes = command.changes
    assert isinstance(changes, SelectionChanges)
    objects = {item.object_id: item for item in snapshot.objects}

    def fields_of(object_id: str) -> SceneObjectFields:
        payload = None
        if changes.annotation is not None:
            payload = replace(objects[object_id].payload, annotation=changes.annotation)
        return SceneObjectFields(visibility=changes.visibility, representation=changes.representation,
                                 category=changes.category, layer=changes.layer, order=changes.order, payload=payload)

    members = resolution.eligible_ids
    return _plan_states(snapshot, members, _member_states(snapshot, command, members, fields_of, resolution.mode))


def _plan_translate(snapshot: SceneSnapshot, command: SceneCommand, resolution: SelectionResolution) -> _Plan:
    delta = command.delta
    assert isinstance(delta, SceneDelta)
    objects = {item.object_id: item for item in snapshot.objects}
    members = resolution.eligible_ids
    boxes: list[SceneGeometry] = []
    for object_id in members:
        box = objects[object_id].geometry
        assert box is not None  # `require_placed` : les non placés sont refusés ou écartés
        boxes.append(box)
    edx, edy = group_delta(boxes, delta.dx, delta.dy)
    report = BatchDelta(requested=(delta.dx, delta.dy), effective=(edx, edy),
                        clamped=bool(members) and (edx, edy) != (delta.dx, delta.dy))
    moving = (edx, edy) != (0.0, 0.0)

    def fields_of(object_id: str) -> SceneObjectFields:
        box = objects[object_id].geometry
        assert box is not None
        if not moving:
            return SceneObjectFields()
        # Même écart pour tous : les écarts relatifs sont conservés, la taille aussi.
        return SceneObjectFields(geometry=SceneGeometry(x=box.x + edx, y=box.y + edy, w=box.w, h=box.h))

    states = _member_states(snapshot, command, members, fields_of, resolution.mode)
    if command.pin:
        # L'épingle dans le même patch : un glisser de la page reste une révision.
        for object_id, after in states.items():
            if not after.constraints.pinned_by_user:
                states[object_id] = replace(after, constraints=replace(after.constraints, pinned_by_user=True))
    plan = _plan_states(snapshot, members, states)
    plan.delta = report
    return plan


def _plan_pin(snapshot: SceneSnapshot, command: SceneCommand, resolution: SelectionResolution) -> _Plan:
    pinned = command.op is SceneOp.PIN_SELECTION
    objects = {item.object_id: item for item in snapshot.objects}
    ops: list[ScenePatchOp] = []
    changed: list[str] = []
    unchanged: list[str] = []
    for object_id in resolution.eligible_ids:
        current = objects[object_id]
        if current.constraints.pinned_by_user is pinned:
            unchanged.append(object_id)
            continue
        updated = replace(current, constraints=replace(current.constraints, pinned_by_user=pinned))
        ops.append(ScenePatchOp(PatchOpKind.PUT_OBJECT, object=updated))
        changed.append(object_id)
    return _Plan(ops, changed, unchanged)


def _plan_archive(snapshot: SceneSnapshot, command: SceneCommand, resolution: SelectionResolution) -> _Plan:
    members = resolution.eligible_ids
    owners = signal_owners(snapshot)
    ordered: dict[str, None] = {}
    for object_id in members:
        _with_cascade(snapshot, object_id, owners, ordered)
    selected = set(members)
    cascade = tuple(object_id for object_id in ordered if object_id not in selected)
    return _Plan(_archive_ops(snapshot, list(ordered)), list(members), list(resolution.archived_ids), cascade=cascade)


_PLANNERS = {
    SceneOp.PATCH_SELECTION: _plan_patch,
    SceneOp.TRANSLATE_SELECTION: _plan_translate,
    SceneOp.PIN_SELECTION: _plan_pin,
    SceneOp.UNPIN_SELECTION: _plan_pin,
    SceneOp.ARCHIVE_SELECTION: _plan_archive,
}


def _matched_ids(command: SceneCommand, resolution: SelectionResolution) -> tuple[str, ...]:
    """Membres retenus ; pour `archive_selection`, les ids explicites déjà archivés remis à leur place (§4.1)."""

    if command.op is not SceneOp.ARCHIVE_SELECTION or not resolution.archived_ids:
        return resolution.matched_ids
    assert command.selection is not None and command.selection.ids is not None
    keep = set(resolution.matched_ids) | set(resolution.archived_ids)
    return tuple(object_id for object_id in command.selection.ids if object_id in keep)


def apply_selection_command(snapshot: SceneSnapshot, command: SceneCommand) -> SceneUpdate:
    """Appliquer une commande de sélection : tout ou rien, une révision au plus (§4)."""

    selection = command.selection
    assert isinstance(selection, SceneSelection) and command.op in _PLANNERS
    empty = SceneBatchReport(op=command.op, mode=selection.mode)
    if command.op not in ALLOWED_SCENE_OPS[command.actor]:
        return SceneUpdate(SceneCommandOutcome.REJECTED_AUTHORITY, snapshot, reason=SceneRefusal.OP_NOT_ALLOWED,
                           batch=empty)
    resolution = resolve_selection(snapshot, selection, require_placed=command.op in _REQUIRE_PLACED)
    archived_ok = command.op is SceneOp.ARCHIVE_SELECTION
    refusals = resolution.refusals(archived_ok=archived_ok)
    if refusals:
        report = replace(empty, refused=refusals)
        return SceneUpdate(SceneCommandOutcome.INVALID, snapshot, reason=refusals[0].reason, batch=report)
    matched = _matched_ids(command, resolution)
    report = replace(empty, matched_ids=matched, hidden_count=resolution.hidden_count, skipped=resolution.skipped)
    try:
        plan = _PLANNERS[command.op](snapshot, command, resolution)
    except _MemberRefusals as refused:
        report = replace(report, refused=tuple(refused.entries))
        return SceneUpdate(refused.outcome, snapshot, reason=refused.entries[0].reason, batch=report)
    report = replace(report, changed_ids=tuple(plan.changed), unchanged_ids=tuple(plan.unchanged),
                     cascade_ids=plan.cascade, delta=plan.delta)
    if not plan.ops:
        return SceneUpdate(SceneCommandOutcome.DUPLICATE, snapshot, batch=report)
    # Borne par construction (§1.4) : ≤ 512 objets + ≤ 1 024 relations.
    assert len(plan.ops) <= MAX_PATCH_OPS
    if snapshot.revision >= MAX_REVISION:
        return SceneUpdate(SceneCommandOutcome.INVALID, snapshot, reason=SceneRefusal.REVISION_EXHAUSTED, batch=report)
    patch = ScenePatch(revision=snapshot.revision + 1, ops=tuple(plan.ops))
    return SceneUpdate(SceneCommandOutcome.APPLIED, apply_scene_patch(snapshot, patch), patch, batch=report)

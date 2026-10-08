"""Presentation Studio : le vocabulaire d'édition sémantique (handoff jarvis-interactive-presentation-studio, Slice 05).

Une seule couche d'édition pour la voix (acteur `brain`, outils MCP) et l'interface (acteur `user`, relais du
Control Center) : des **opérations** sur des ids stables (`presentation_id` / `variant_id` / `scene_id` /
`control_id`), jamais un chemin DOM, un sélecteur CSS ni un extrait de source. Ce module est **pur** (aucune E/S,
pas d'`await`) : il parse la requête, classe chaque opération par niveau, applique la transaction sur une copie de
travail des scènes et rend, pour chaque opération, l'opération inverse. Le service Core
(`jarvis/core/presentation_studio_edit.py`) fournit les manifestes déjà lus, relit l'état courant, écrit.

Contrat : `docs/presentation-studio.md` › *Semantic edit contract*.

## Les trois niveaux (D11)

| Niveau | Quand | Effet ici |
| --- | --- | --- |
| `control` | `control.set`, `control.reset`, `scene.restore_values` sur un contrôle **déclaré** (hors liste) | valeurs `props`/`data` de la scène ; pas de remontage |
| `structure` | `scene.add/remove/reorder/rename/set_controls`, ou un contrôle lié à une **liste** | forme de la variante |
| `source` | `scene.source_request` | **classée et enregistrée seulement** : la reconstruction (HMR) est la Slice 06 |

Le niveau d'une requête est le plus haut de ses opérations. Une opération sur un contrôle non déclaré est refusée
(`unknown_control`) : la porte de secours est `scene.source_request`, jamais un chemin libre.

## Transaction

Toutes les opérations d'une requête s'appliquent dans l'ordre sur une copie ; la première qui refuse annule le tout
(`refused`, rien n'est écrit, `failed_index` dit laquelle). Une précondition non tenue (`if_current`) est `stale`.

## Clés sûres

Les noms de propriété d'un prefab passent la regex du manifeste, `__proto__`, `constructor` et `prototype` comprises.
Python n'en souffre pas, mais les valeurs partent vers un cadre JavaScript : ces trois noms sont refusés comme segment
de chemin de contrôle et comme clé d'une valeur, à toute profondeur (`UNSAFE_KEYS`). Les chemins ne sont jamais
construits à partir de texte libre : seuls les `StudioControl.keys` déclarés servent à naviguer.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import copy
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
import json
import secrets
from typing import Any, ClassVar

from jarvis.domain.prefab import InputType, PrefabManifest, canonical_json
from jarvis.domain.presentation_studio_checks import (
    HTTP_STATUS, MAX_ERROR_CHARS, PresentationStudioError, PresentationStudioErrorCode as C, SCENE_ID, _check_id, _check_int,
    _exact_keys, _fail, clip,
)
from jarvis.domain.presentation_studio_scene import (
    MAX_CONTROLS, StudioControl, StudioScene, check_scene, describe_control, node_of, value_at, value_problem,
)
from jarvis.domain.presentation_studio_scene_variant_ops import (  # noqa: F401 - re-exported: the historical home of the op names
    SceneVariantCreate, SceneVariantDelete, SceneVariantRename, SceneVariantRestoreSet, SceneVariantSelect,
)
from jarvis.domain.presentation_studio_scene_variants import (
    MAX_DECK_VARIANTS, SceneVariantSet, deck_stored_variants, new_scene_variant_id,
)
from jarvis.domain.presentation_studio_scene_variants import create as sv_create
from jarvis.domain.presentation_studio_scene_variants import delete as sv_delete
from jarvis.domain.presentation_studio_scene_variants import rename as sv_rename
from jarvis.domain.presentation_studio_scene_variants import restore as sv_restore
from jarvis.domain.presentation_studio_scene_variants import select as sv_select

#: Bornes (toute collection est bornée).
MAX_OPS = 16
MAX_SCENES = 64
MAX_INTENT_CHARS = 400
#: Une opération inverse (ou un lot) plus grosse n'est pas gardée : l'enregistrement dit `too_large`.
MAX_UNDO_BYTES = 64 * 1024
MAX_VALUE_DEPTH = 16
MAX_VALUE_NODES = 4096
MAX_EDIT_BODY_BYTES = 128 * 1024
UNSAFE_KEYS = frozenset({"__proto__", "constructor", "prototype"})


class StudioActor(StrEnum):
    """Qui édite. Le relais du Control Center force `user`, les outils MCP posent `brain` (`prefab_relay.py`)."""

    USER = "user"
    BRAIN = "brain"


class EditTier(StrEnum):
    CONTROL = "control"
    STRUCTURE = "structure"
    SOURCE = "source"


_TIER_RANK = {EditTier.CONTROL: 0, EditTier.STRUCTURE: 1, EditTier.SOURCE: 2}


class EditMode(StrEnum):
    #: Valide et calcule le résultat, n'écrit **rien** (ni fichier, ni événement, ni demande de source).
    PREVIEW = "preview"
    #: Mêmes validations que `PUT .../variants/{id}`, puis écrit et met l'état canonique à jour.
    COMMIT = "commit"


class EditStatus(StrEnum):
    APPLIED = "applied"
    REFUSED = "refused"
    STALE = "stale"


class OpName(StrEnum):
    CONTROL_SET = "control.set"
    CONTROL_RESET = "control.reset"
    RESTORE_VALUES = "scene.restore_values"
    SCENE_ADD = "scene.add"
    SCENE_REMOVE = "scene.remove"
    SCENE_REORDER = "scene.reorder"
    SCENE_RENAME = "scene.rename"
    SCENE_SET_CONTROLS = "scene.set_controls"
    SOURCE_REQUEST = "scene.source_request"
    #: Slice 17 : variantes locales d'une scène. `RESTORE_SET` est la forme exacte d'une annulation (comme `RESTORE_VALUES`).
    SCENE_VARIANT_CREATE = "scene_variant.create"
    SCENE_VARIANT_RENAME = "scene_variant.rename"
    SCENE_VARIANT_SELECT = "scene_variant.select"
    SCENE_VARIANT_DELETE = "scene_variant.delete"
    SCENE_VARIANT_RESTORE_SET = "scene_variant.restore_set"


#: Table d'autorité, comme `ALLOWED_SCENE_OPS` : ce que chaque acteur peut demander. Les deux acteurs ont tout le
#: vocabulaire aujourd'hui (tout est annulable par son enregistrement d'annulation) ; la table existe pour qu'un
#: durcissement (Slice 21 : confirmation d'une suppression demandée par la voix) soit une ligne, pas un refactor.
ALLOWED_EDIT_OPS: Mapping[StudioActor, frozenset[OpName]] = {
    StudioActor.USER: frozenset(OpName),
    StudioActor.BRAIN: frozenset(OpName),
}

STATE_OPS = frozenset(OpName) - {OpName.SOURCE_REQUEST}


# ------------------------------------------------------------------ clés et valeurs sûres

def unsafe_key_in(value: object) -> str | None:
    """Le premier nom de clé dangereux (`UNSAFE_KEYS`) trouvé à n'importe quelle profondeur, sinon `None`.
    Itératif et borné : une valeur trop profonde ou trop grosse est signalée comme dangereuse (jamais parcourue)."""

    stack: list[tuple[object, int]] = [(value, 0)]
    seen = 0
    while stack:
        node, depth = stack.pop()
        seen += 1
        if depth > MAX_VALUE_DEPTH or seen > MAX_VALUE_NODES:
            return "<too deep or too large>"
        if isinstance(node, dict):
            for key, child in node.items():
                if key in UNSAFE_KEYS or not isinstance(key, str):
                    return str(key)[:40]
                stack.append((child, depth + 1))
        elif isinstance(node, (list, tuple)):
            stack.extend((child, depth + 1) for child in node)
    return None


def _json_pure(value: object) -> bool:
    try:
        canonical_json(value)
    except (TypeError, ValueError, RecursionError):
        return False
    return True


# ------------------------------------------------------------------ refus d'une opération

class EditRefusal(Exception):
    """Une opération refuse (ou une précondition n'est plus tenue : `stale`). Interne au moteur."""

    def __init__(self, code: C, message: str, *, index: int | None = None, stale: bool = False) -> None:
        super().__init__(message)
        self.code, self.message, self.index, self.stale = code, clip(message), index, stale


def _refuse(code: C, message: str) -> EditRefusal:
    return EditRefusal(code, message)


# ------------------------------------------------------------------ opérations

def _scene_id(raw: Mapping[str, Any]) -> str:
    _check_id("scene_id", raw["scene_id"], SCENE_ID)
    return raw["scene_id"]


def _control_id(raw: Mapping[str, Any]) -> str:
    value = raw["control_id"]
    if not isinstance(value, str) or not 1 <= len(value) <= 40:
        raise _fail("control_id must be a control slug")
    return value


def _expect(raw: Mapping[str, Any]) -> tuple[Any, ...]:
    if "if_current" not in raw:
        return ()
    if not _json_pure(raw["if_current"]):
        raise _fail("if_current must be pure JSON")
    return (raw["if_current"],)


@dataclass(frozen=True, slots=True)
class ControlSet:
    NAME: ClassVar[OpName] = OpName.CONTROL_SET
    scene_id: str
    control_id: str
    value: Any
    #: `()` : aucune précondition ; `(v,)` : la valeur **courante** (celle que l'inspecteur montre) doit être `v`.
    expect: tuple[Any, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        wire = {"op": self.NAME.value, "scene_id": self.scene_id, "control_id": self.control_id, "value": self.value}
        if self.expect:
            wire["if_current"] = self.expect[0]
        return wire

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> ControlSet:
        data = _exact_keys(raw, "control.set", {"op", "scene_id", "control_id", "value"}, frozenset({"if_current"}))
        return cls(_scene_id(data), _control_id(data), data["value"], _expect(data))


@dataclass(frozen=True, slots=True)
class ControlReset:
    NAME: ClassVar[OpName] = OpName.CONTROL_RESET
    scene_id: str
    control_id: str
    expect: tuple[Any, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        wire = {"op": self.NAME.value, "scene_id": self.scene_id, "control_id": self.control_id}
        if self.expect:
            wire["if_current"] = self.expect[0]
        return wire

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> ControlReset:
        data = _exact_keys(raw, "control.reset", {"op", "scene_id", "control_id"}, frozenset({"if_current"}))
        return cls(_scene_id(data), _control_id(data), _expect(data))


@dataclass(frozen=True, slots=True)
class RestoreValues:
    """La forme exacte de l'annulation d'un changement de valeurs : les `props`/`data` entiers de la scène."""

    NAME: ClassVar[OpName] = OpName.RESTORE_VALUES
    scene_id: str
    props: dict[str, Any]
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"op": self.NAME.value, "scene_id": self.scene_id, "props": self.props, "data": self.data}

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> RestoreValues:
        data = _exact_keys(raw, "scene.restore_values", {"op", "scene_id", "props", "data"})
        if not isinstance(data["props"], dict) or not isinstance(data["data"], dict):
            raise _fail("scene.restore_values: props and data must be objects")
        return cls(_scene_id(data), data["props"], data["data"])


@dataclass(frozen=True, slots=True)
class SceneAdd:
    NAME: ClassVar[OpName] = OpName.SCENE_ADD
    scene: StudioScene
    #: Position d'insertion (`None` : à la fin).
    index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"op": self.NAME.value, "scene": self.scene.to_dict(), "index": self.index}

    @classmethod
    def parse(cls, raw: Mapping[str, Any], *, new_id: Callable[[], str]) -> SceneAdd:
        data = _exact_keys(raw, "scene.add", {"op", "scene"}, frozenset({"index"}))
        body = data["scene"]
        if isinstance(body, dict) and "scene_id" not in body:
            body = {**body, "scene_id": new_id()}
        scene = StudioScene.from_dict(body, "scene.add.scene")
        index = data.get("index")
        if index is not None:
            _check_int("index", index, 0, MAX_SCENES)
        return cls(scene, index)


@dataclass(frozen=True, slots=True)
class SceneRemove:
    NAME: ClassVar[OpName] = OpName.SCENE_REMOVE
    scene_id: str

    def to_dict(self) -> dict[str, Any]:
        return {"op": self.NAME.value, "scene_id": self.scene_id}

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> SceneRemove:
        return cls(_scene_id(_exact_keys(raw, "scene.remove", {"op", "scene_id"})))


@dataclass(frozen=True, slots=True)
class SceneReorder:
    NAME: ClassVar[OpName] = OpName.SCENE_REORDER
    scene_id: str
    to_index: int

    def to_dict(self) -> dict[str, Any]:
        return {"op": self.NAME.value, "scene_id": self.scene_id, "to_index": self.to_index}

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> SceneReorder:
        data = _exact_keys(raw, "scene.reorder", {"op", "scene_id", "to_index"})
        _check_int("to_index", data["to_index"], 0, MAX_SCENES - 1)
        return cls(_scene_id(data), data["to_index"])


@dataclass(frozen=True, slots=True)
class SceneRename:
    NAME: ClassVar[OpName] = OpName.SCENE_RENAME
    scene_id: str
    title: str

    def to_dict(self) -> dict[str, Any]:
        return {"op": self.NAME.value, "scene_id": self.scene_id, "title": self.title}

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> SceneRename:
        data = _exact_keys(raw, "scene.rename", {"op", "scene_id", "title"})
        if not isinstance(data["title"], str):
            raise _fail("title must be a string")
        return cls(_scene_id(data), data["title"])


@dataclass(frozen=True, slots=True)
class SceneSetControls:
    """Remplace la liste des contrôles curés d'une scène (point d'arrivée de `suggest_controls`)."""

    NAME: ClassVar[OpName] = OpName.SCENE_SET_CONTROLS
    scene_id: str
    controls: tuple[StudioControl, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"op": self.NAME.value, "scene_id": self.scene_id, "controls": [c.to_dict() for c in self.controls]}

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> SceneSetControls:
        data = _exact_keys(raw, "scene.set_controls", {"op", "scene_id", "controls"})
        controls = data["controls"]
        if not isinstance(controls, list) or len(controls) > MAX_CONTROLS:
            raise _fail(f"controls must be a list of at most {MAX_CONTROLS}")
        return cls(_scene_id(data), tuple(StudioControl.from_dict(c, f"controls[{i}]") for i, c in enumerate(controls)))


@dataclass(frozen=True, slots=True)
class SourceRequest:
    """Niveau 3 : l'intention d'un changement que les contrôles déclarés ne permettent pas. Classée et enregistrée ici ;
    la reconstruction est la Slice 06. `intent` ne quitte jamais le processus (ni événement, ni journal)."""

    NAME: ClassVar[OpName] = OpName.SOURCE_REQUEST
    scene_id: str
    intent: str

    def to_dict(self) -> dict[str, Any]:
        return {"op": self.NAME.value, "scene_id": self.scene_id, "intent": self.intent}

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> SourceRequest:
        data = _exact_keys(raw, "scene.source_request", {"op", "scene_id", "intent"})
        intent = data["intent"]
        if not isinstance(intent, str) or not intent.strip() or intent != intent.strip() \
                or not intent.isprintable() or len(intent) > MAX_INTENT_CHARS:
            raise _fail(f"intent must be one printable line of 1..{MAX_INTENT_CHARS} characters without surrounding spaces")
        return cls(_scene_id(data), intent)


EditOp = (ControlSet | ControlReset | RestoreValues | SceneAdd | SceneRemove | SceneReorder | SceneRename
          | SceneSetControls | SourceRequest | SceneVariantCreate | SceneVariantRename | SceneVariantSelect
          | SceneVariantDelete | SceneVariantRestoreSet)

_PARSERS: dict[str, Callable[..., Any]] = {
    OpName.CONTROL_SET: ControlSet.parse, OpName.CONTROL_RESET: ControlReset.parse,
    OpName.RESTORE_VALUES: RestoreValues.parse, OpName.SCENE_REMOVE: SceneRemove.parse,
    OpName.SCENE_REORDER: SceneReorder.parse, OpName.SCENE_RENAME: SceneRename.parse,
    OpName.SCENE_SET_CONTROLS: SceneSetControls.parse, OpName.SOURCE_REQUEST: SourceRequest.parse,
    OpName.SCENE_VARIANT_CREATE: SceneVariantCreate.parse, OpName.SCENE_VARIANT_RENAME: SceneVariantRename.parse,
    OpName.SCENE_VARIANT_SELECT: SceneVariantSelect.parse, OpName.SCENE_VARIANT_DELETE: SceneVariantDelete.parse,
    OpName.SCENE_VARIANT_RESTORE_SET: SceneVariantRestoreSet.parse,
}


def parse_op(raw: object, where: str = "op", *, new_id: Callable[[], str] | None = None) -> EditOp:
    if not isinstance(raw, dict):
        raise _fail(f"{where} must be a JSON object")
    name = raw.get("op")
    if not isinstance(name, str) or name not in {n.value for n in OpName}:
        raise _fail(f"{where}.op must be one of {', '.join(n.value for n in OpName)}")
    if name == OpName.SCENE_ADD:
        return SceneAdd.parse(raw, new_id=new_id or _new_scene_id)
    return _PARSERS[name](raw)


def _new_scene_id() -> str:
    return "pss_" + secrets.token_hex(6)


# ------------------------------------------------------------------ la requête

@dataclass(frozen=True, slots=True)
class EditRequest:
    actor: StudioActor
    mode: EditMode
    #: Révision de la variante sur laquelle l'appelant a raisonné. Obligatoire : une édition sans base serait
    #: une écriture aveugle (le contraire de `expected_revision` de `PUT`).
    basis_revision: int
    ops: tuple[EditOp, ...]

    @property
    def op_names(self) -> tuple[str, ...]:
        return tuple(str(op.NAME) for op in self.ops)


def parse_edit_request(raw: object, *, new_id: Callable[[], str] | None = None) -> EditRequest:
    data = _exact_keys(raw, "edit", {"actor", "mode", "basis", "ops"})
    try:
        actor = StudioActor(data["actor"])
    except ValueError:
        raise _fail("actor must be 'user' or 'brain'") from None
    try:
        mode = EditMode(data["mode"])
    except ValueError:
        raise _fail("mode must be 'preview' or 'commit'") from None
    basis = _exact_keys(data["basis"], "basis", {"variant_revision"})
    _check_int("basis.variant_revision", basis["variant_revision"], 1, 2**31 - 1)
    ops = data["ops"]
    if not isinstance(ops, list) or not 1 <= len(ops) <= MAX_OPS:
        raise _fail(f"ops must be a list of 1..{MAX_OPS} operations")
    parsed = tuple(parse_op(op, f"ops[{i}]", new_id=new_id) for i, op in enumerate(ops))
    return EditRequest(actor, mode, basis["variant_revision"], parsed)


def actor_refusal(actor: StudioActor, ops: Sequence[EditOp]) -> EditRefusal | None:
    allowed = ALLOWED_EDIT_OPS.get(actor, frozenset())
    for index, op in enumerate(ops):
        if op.NAME not in allowed:
            return EditRefusal(C.INVALID_PRESENTATION, f"actor {actor.value} may not request {op.NAME}", index=index)
    return None


# ------------------------------------------------------------------ niveaux

def classify_op(op: EditOp, node_type: InputType | None = None) -> EditTier:
    """Le niveau d'une opération, depuis l'opération et les métadonnées du contrôle (`node_type` : type d'entrée du
    manifeste auquel il est lié). Un contrôle lié à une **liste** change la forme du contenu : structure."""

    if isinstance(op, SourceRequest):
        return EditTier.SOURCE
    if isinstance(op, (ControlSet, ControlReset)):
        return EditTier.STRUCTURE if node_type is InputType.ARRAY else EditTier.CONTROL
    if isinstance(op, RestoreValues):
        return EditTier.CONTROL  # `apply_ops` raises it to structure when the restored paths hold a list
    return EditTier.STRUCTURE


def highest_tier(tiers: Sequence[EditTier]) -> EditTier:
    return max(tiers, key=_TIER_RANK.__getitem__, default=EditTier.CONTROL)


# ------------------------------------------------------------------ le moteur

Manifests = Mapping[tuple[str, int], PrefabManifest]


@dataclass(frozen=True, slots=True)
class SourceRequestRecord:
    request_id: str
    presentation_id: str
    variant_id: str
    scene_id: str
    intent: str
    actor: str
    #: Révision de la variante au moment de la demande.
    basis_revision: int

    def to_dict(self, *, with_intent: bool = True) -> dict[str, Any]:
        wire = {"request_id": self.request_id, "presentation_id": self.presentation_id, "variant_id": self.variant_id,
                "scene_id": self.scene_id, "actor": self.actor, "basis_revision": self.basis_revision,
                "tier": EditTier.SOURCE.value}
        if with_intent:
            wire["intent"] = self.intent
        return wire


@dataclass(slots=True)
class EditPlan:
    scenes: tuple[StudioScene, ...]
    outcomes: list[dict[str, Any]] = field(default_factory=list)
    #: Opérations inverses, **dans l'ordre où il faut les appliquer** pour revenir en arrière.
    inverse: list[dict[str, Any]] = field(default_factory=list)
    tiers: list[EditTier] = field(default_factory=list)
    sources: list[SourceRequest] = field(default_factory=list)

    @property
    def tier(self) -> EditTier:
        return highest_tier(self.tiers)


def _stored(scenes: Sequence[StudioScene]) -> str:
    return canonical_json([scene.to_dict() for scene in scenes])


def _find(scenes: Sequence[StudioScene], scene_id: str) -> tuple[int, StudioScene]:
    for index, scene in enumerate(scenes):
        if scene.scene_id == scene_id:
            return index, scene
    raise _refuse(C.UNKNOWN_SCENE, f"{scene_id} is not a scene of this variant")


def _manifest(manifests: Manifests, scene: StudioScene) -> PrefabManifest:
    manifest = manifests.get((scene.prefab.prefab_id, scene.prefab.version))
    if manifest is None:
        raise _refuse(C.PREFAB_UNAVAILABLE, f"scene {scene.scene_id}: the manifest of its pin was not provided")
    return manifest


def _control(scene: StudioScene, control_id: str) -> StudioControl:
    control = scene.control(control_id)
    if control is None:
        raise _refuse(C.UNKNOWN_CONTROL, f"scene {scene.scene_id} declares no control {control_id!r}: "
                                         "use scene.source_request for a change the declared controls cannot make")
    if any(key in UNSAFE_KEYS for key in control.keys):
        raise _refuse(C.INVALID_PRESENTATION, f"control {control.control_id}: its path holds a reserved property name")
    return control


def _with_value(scene: StudioScene, control: StudioControl, *, present: bool, value: object) -> StudioScene:
    """La scène avec `value` écrit (ou la clé retirée) au chemin du contrôle. Copie profonde ; navigation par clés
    déclarées uniquement ; un intermédiaire qui n'est pas un objet est un refus, jamais écrasé."""

    props, data = copy.deepcopy(scene.props), copy.deepcopy(scene.data)
    node: Any = props if control.root == "props" else data
    for key in control.keys[:-1]:
        child = node.get(key) if key in node else None
        if child is None:
            if not present:
                return scene  # nothing to unset under a missing branch
            child = node[key] = {}
        if not isinstance(child, dict):
            raise _refuse(C.VALUE_REFUSED, f"{control.path}: {key} is not an object in this scene's values")
        node = child
    last = control.keys[-1]
    if present:
        node[last] = copy.deepcopy(value)
    else:
        node.pop(last, None)
    try:
        return replace(scene, props=props, data=data)
    except PresentationStudioError as exc:
        raise EditRefusal(exc.code, exc.message) from None


def _values_inverse(scene: StudioScene) -> dict[str, Any]:
    return RestoreValues(scene.scene_id, copy.deepcopy(scene.props), copy.deepcopy(scene.data)).to_dict()


Path = tuple[str, ...]


def _leaves(root: str, node: object, prefix: Path = ()) -> dict[Path, object]:
    """`{chemin: valeur}` des feuilles ; un objet vide et une liste sont des feuilles (une liste est une valeur)."""

    if isinstance(node, dict) and node:
        found: dict[Path, object] = {}
        for key, child in node.items():
            found.update(_leaves(root, child, (*prefix, key)))
        return found
    return {(root, *prefix): node}


def _restore_tier(before: StudioScene, after: StudioScene, manifest: PrefabManifest) -> EditTier:
    """Une restauration ne peut changer que des chemins **déclarés** : chaque feuille qui diffère est un chemin de contrôle,
    sous un chemin de contrôle (une liste liée), ou un objet vide intermédiaire d'un chemin de contrôle (ce que laisse
    `control.set` sur une branche absente). Sinon `unknown_control` : l'inverse d'une édition ne change que ce que cette
    édition a changé, donc l'annulation passe ; une restauration libre, non. Le niveau suit : une liste modifiée est `structure`."""

    old = {**_leaves("props", before.props), **_leaves("data", before.data)}
    new = {**_leaves("props", after.props), **_leaves("data", after.data)}
    tier = EditTier.CONTROL
    for path in sorted({p for p in old.keys() | new.keys() if canonical_json(old.get(p, _ABSENT)) != canonical_json(new.get(p, _ABSENT))}):
        owner = next((c for c in before.controls if (c.root, *c.keys) == path[:1 + len(c.keys)]), None)
        if owner is None:
            owner = next((c for c in before.controls if (c.root, *c.keys)[:len(path)] == path
                          and old.get(path, {}) == {} and new.get(path, {}) == {}), None)
        if owner is None:
            raise _refuse(C.UNKNOWN_CONTROL, f"scene.restore_values would change {'.'.join(path)}, which no declared control of "
                                             f"scene {before.scene_id} covers: use scene.source_request")
        node = node_of(manifest, owner)
        if node is not None and node.type is InputType.ARRAY:
            tier = EditTier.STRUCTURE
    return tier


_ABSENT = {"__absent__": True}


def _value_change(scene: StudioScene, control: StudioControl, manifest: PrefabManifest, expect: tuple[Any, ...],
                  *, present: bool, value: object) -> tuple[StudioScene, dict[str, Any], EditTier]:
    node = node_of(manifest, control)
    if node is None:
        raise _refuse(C.SCENE_INCOMPATIBLE, f"control {control.control_id}: {control.path} is not declared by "
                                            f"{scene.prefab.prefab_id}@{scene.prefab.version}")
    if expect:
        current = describe_control(scene, manifest, control)["current"]
        if canonical_json(current) != canonical_json(expect[0]):
            raise EditRefusal(C.STALE_REVISION, f"control {control.control_id} is no longer what the edit expected: "
                                                "read it again, then retry", stale=True)
    if present:
        if unsafe_key_in(value) is not None:
            raise _refuse(C.INVALID_PRESENTATION, f"control {control.control_id}: the value holds a reserved key name")
        if not _json_pure(value):
            raise _refuse(C.VALUE_REFUSED, f"control {control.control_id}: the value must be pure JSON")
        problem = value_problem(node, control.bounds, value, control.path)
        if problem is not None:
            raise _refuse(C.VALUE_REFUSED, f"control {control.control_id}: {problem}")
    before_present, before = value_at(scene, control)
    updated = _with_value(scene, control, present=present, value=value)
    outcome = {"scene_id": scene.scene_id, "control_id": control.control_id,
               "before": before if before_present else None, "was_set": before_present,
               "after": value if present else None, "is_set": present}
    return updated, outcome, classify_op(ControlSet(scene.scene_id, control.control_id, None), node.type)


@dataclass(frozen=True, slots=True)
class _Env:
    """Ce que le moteur tire du monde (horloge, identifiants) : injecté, donc rejouable dans les tests."""

    actor: StudioActor
    now: Callable[[], str]
    new_scene_variant_id: Callable[[], str]


def _stamp_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def apply_ops(scenes: tuple[StudioScene, ...], ops: Sequence[EditOp], manifests: Manifests, *,
              presentation_id: str, variant_id: str, actor: StudioActor, basis_revision: int,
              new_request_id: Callable[[], str] | None = None, now: Callable[[], str] | None = None,
              new_scene_variant_id: Callable[[], str] | None = None) -> EditPlan:
    """Applique `ops` dans l'ordre sur une copie de `scenes`. Pur ; lève `EditRefusal(index=...)` à la première qui refuse
    (rien n'est alors à défaire : `scenes` n'a pas bougé). `manifests` : le manifeste de chaque pin touché, déjà lu."""

    plan = EditPlan(scenes)
    make_request_id = new_request_id or (lambda: "psq_" + secrets.token_hex(6))
    current = list(scenes)
    env = _Env(actor, now or _stamp_now, new_scene_variant_id or new_scene_variant_id_default)
    for index, op in enumerate(ops):
        try:
            _apply_one(current, op, manifests, plan, make_request_id, env)
        except EditRefusal as refusal:
            refusal.index = index
            raise
        except PresentationStudioError as exc:
            raise EditRefusal(exc.code, exc.message, index=index) from None
        plan.outcomes[-1].update({"index": index, "op": str(op.NAME), "tier": plan.tiers[-1].value})
    plan.scenes = tuple(current)
    if len(plan.scenes) > MAX_SCENES:
        raise EditRefusal(C.LIMIT_REACHED, f"a variant holds at most {MAX_SCENES} scenes", index=len(ops) - 1)
    plan.inverse.reverse()
    return plan


def _apply_one(current: list[StudioScene], op: EditOp, manifests: Manifests, plan: EditPlan,
               make_request_id: Callable[[], str], env: _Env) -> None:
    outcome: dict[str, Any]
    if isinstance(op, (SceneVariantCreate, SceneVariantRename, SceneVariantSelect, SceneVariantDelete,
                       SceneVariantRestoreSet)):
        _apply_scene_variant(current, op, plan, env)
        return
    if isinstance(op, (ControlSet, ControlReset)):
        position, scene = _find(current, op.scene_id)
        control = _control(scene, op.control_id)
        manifest = _manifest(manifests, scene)
        if isinstance(op, ControlSet):
            present, value = True, op.value
        elif control.default is not None:
            present, value = True, control.default  # the curated default, written explicitly
        else:
            present, value = False, None  # unset: the prefab supplies its manifest default
        updated, outcome, tier = _value_change(scene, control, manifest, op.expect, present=present, value=value)
        _record(current, plan, position, scene, updated, outcome, tier, inverse=_values_inverse(scene))
        return
    if isinstance(op, RestoreValues):
        position, scene = _find(current, op.scene_id)
        if unsafe_key_in(op.props) is not None or unsafe_key_in(op.data) is not None:
            raise _refuse(C.INVALID_PRESENTATION, "the restored values hold a reserved key name")
        try:
            updated = replace(scene, props=op.props, data=op.data)
        except PresentationStudioError as exc:
            raise EditRefusal(exc.code, exc.message) from None
        tier = _restore_tier(scene, updated, _manifest(manifests, scene))
        _record(current, plan, position, scene, updated, {"scene_id": scene.scene_id}, tier,
                inverse=_values_inverse(scene))
        return
    if isinstance(op, SceneAdd):
        if any(s.scene_id == op.scene.scene_id for s in current):
            raise _refuse(C.INVALID_PRESENTATION, f"{op.scene.scene_id} is already a scene of this variant")
        if len(current) >= MAX_SCENES:
            raise _refuse(C.LIMIT_REACHED, f"a variant holds at most {MAX_SCENES} scenes")
        if any(key in UNSAFE_KEYS for control in op.scene.controls for key in control.keys):
            raise _refuse(C.INVALID_PRESENTATION, "a control path holds a reserved property name")
        if unsafe_key_in(op.scene.props) is not None or unsafe_key_in(op.scene.data) is not None:
            raise _refuse(C.INVALID_PRESENTATION, "the scene's values hold a reserved key name")
        _refuse_unsafe_set(op.scene.scene_variants)
        at = len(current) if op.index is None else op.index
        if at > len(current):
            raise _refuse(C.INVALID_PRESENTATION, f"index {at} is beyond the {len(current)} scenes")
        current.insert(at, op.scene)
        plan.outcomes.append({"scene_id": op.scene.scene_id, "index_at": at, "changed": True})
        plan.inverse.append(SceneRemove(op.scene.scene_id).to_dict())
        plan.tiers.append(EditTier.STRUCTURE)
        return
    if isinstance(op, SceneRemove):
        position, scene = _find(current, op.scene_id)
        del current[position]
        plan.outcomes.append({"scene_id": scene.scene_id, "index_at": position, "changed": True})
        plan.inverse.append(SceneAdd(scene, position).to_dict())
        plan.tiers.append(EditTier.STRUCTURE)
        return
    if isinstance(op, SceneReorder):
        position, scene = _find(current, op.scene_id)
        if op.to_index >= len(current):
            raise _refuse(C.INVALID_PRESENTATION, f"to_index {op.to_index} is beyond the {len(current)} scenes")
        current.insert(op.to_index, current.pop(position))
        plan.outcomes.append({"scene_id": scene.scene_id, "from_index": position, "to_index": op.to_index,
                              "changed": position != op.to_index})
        plan.inverse.append(SceneReorder(scene.scene_id, position).to_dict())
        plan.tiers.append(EditTier.STRUCTURE)
        return
    if isinstance(op, SceneRename):
        position, scene = _find(current, op.scene_id)
        try:
            updated = replace(scene, title=op.title)
        except PresentationStudioError as exc:
            raise EditRefusal(exc.code, exc.message) from None
        _record(current, plan, position, scene, updated, {"scene_id": scene.scene_id}, EditTier.STRUCTURE,
                inverse=SceneRename(scene.scene_id, scene.title).to_dict())
        return
    if isinstance(op, SceneSetControls):
        position, scene = _find(current, op.scene_id)
        for control in op.controls:
            if any(key in UNSAFE_KEYS for key in control.keys):
                raise _refuse(C.INVALID_PRESENTATION, f"control {control.control_id}: its path holds a reserved property name")
        try:
            updated = replace(scene, controls=op.controls)
        except PresentationStudioError as exc:
            raise EditRefusal(exc.code, exc.message) from None
        problems = check_scene(updated, _manifest(manifests, scene))
        if problems:
            raise _refuse(C.SCENE_INCOMPATIBLE, f"scene {scene.scene_id}: " + "; ".join(problems[:3]))
        _record(current, plan, position, scene, updated, {"scene_id": scene.scene_id, "controls": len(op.controls)},
                EditTier.STRUCTURE, inverse=SceneSetControls(scene.scene_id, scene.controls).to_dict())
        return
    if isinstance(op, SourceRequest):
        _find(current, op.scene_id)
        plan.sources.append(op)
        plan.outcomes.append({"scene_id": op.scene_id, "changed": False, "effect": "recorded_only",
                              "request_id": make_request_id()})
        plan.tiers.append(EditTier.SOURCE)
        return
    raise _refuse(C.INVALID_PRESENTATION, "unknown operation")  # pragma: no cover - parse_op is closed


def _record(current: list[StudioScene], plan: EditPlan, position: int, before: StudioScene, after: StudioScene,
            outcome: dict[str, Any], tier: EditTier, *, inverse: dict[str, Any] | list[dict[str, Any]]) -> None:
    """Compare par forme stockée (jamais `==` : `1`, `1.0` et `true` y sont égaux), et n'enregistre d'inverse que d'un vrai changement."""

    changed = canonical_json(before.to_dict()) != canonical_json(after.to_dict())
    current[position] = after
    plan.outcomes.append({**outcome, "changed": changed})
    plan.tiers.append(tier)
    if changed:
        # a list is appended in order: the plan reverses the whole list at the end, so write a multi-step inverse last-step-first
        plan.inverse.extend(inverse if isinstance(inverse, list) else [inverse])


def new_scene_variant_id_default() -> str:
    return new_scene_variant_id()


def _refuse_unsafe_set(variants: SceneVariantSet | None) -> None:
    """Les valeurs et les chemins de contrôle de chaque contenu rangé passent les mêmes clés sûres que la scène vivante."""

    if variants is None:
        return
    for content in variants.contents():
        if unsafe_key_in(content["props"]) is not None or unsafe_key_in(content["data"]) is not None \
                or any(key in UNSAFE_KEYS for control in content["controls"] for key in str(control.get("path", "")).split(".")):
            raise _refuse(C.INVALID_PRESENTATION, "a scene variant holds a reserved key name")


def _set_wire(variants: SceneVariantSet | None) -> dict[str, Any] | None:
    return None if variants is None else variants.to_dict()


def _apply_scene_variant(current: list[StudioScene], op: Any, plan: EditPlan, env: _Env) -> None:
    """Les cinq opérations d'ensemble (Slice 17). Chacune : une scène, un `StudioScene` rebâti (donc revalidé en entier), un
    inverse **exact**. Aucune ne touche une autre scène (testé par hachage)."""

    position, scene = _find(current, op.scene_id)
    outcome: dict[str, Any] = {"scene_id": scene.scene_id}
    current_set = scene.scene_variants
    if isinstance(op, SceneVariantCreate):
        if deck_stored_variants(current) >= MAX_DECK_VARIANTS:
            raise _refuse(C.LIMIT_REACHED, f"this variant already holds {MAX_DECK_VARIANTS} stored scene variants across its scenes "
                                           "(the whole-deck bound that keeps the document inside its 256 KiB): delete a variant you no longer "
                                           "need, or promote one to a presentation variant, then try again")
        fresh, new_id = sv_create(current_set, scene.live_content(), label=op.label, rationale=op.rationale,
                                  from_id=op.from_variant, actor=env.actor.value, now=env.now(), new_id=env.new_scene_variant_id)
        updated = replace(scene, scene_variants=fresh)
        outcome["scene_variant_id"] = new_id
        inverse: dict[str, Any] | list[dict[str, Any]] = SceneVariantRestoreSet(scene.scene_id, _set_wire(current_set)).to_dict()
    elif isinstance(op, SceneVariantRename):
        if current_set is None:
            raise _refuse(C.UNKNOWN_SCENE_VARIANT, f"{op.variant_id} is not a variant of this scene")
        updated = replace(scene, scene_variants=sv_rename(current_set, op.variant_id, op.label))
        outcome["scene_variant_id"] = op.variant_id
        inverse = SceneVariantRename(scene.scene_id, op.variant_id, current_set.get(op.variant_id).label).to_dict()
    elif isinstance(op, SceneVariantSelect):
        if current_set is None:
            raise _refuse(C.UNKNOWN_SCENE_VARIANT, f"{op.variant_id} is not a variant of this scene")
        previous = current_set.current_id
        picked, live = sv_select(current_set, op.variant_id, scene.live_content())
        steps: list[dict[str, Any]] = []
        if op.variant_id != previous:
            steps.append(SceneVariantSelect(scene.scene_id, previous).to_dict())
        final = picked
        if op.drop_others:
            final = None
            steps.append(SceneVariantRestoreSet(scene.scene_id, picked.to_dict()).to_dict())
        updated = scene.with_content(live, final)
        outcome["scene_variant_id"] = op.variant_id
        inverse = steps
    elif isinstance(op, SceneVariantDelete):
        if current_set is None:
            raise _refuse(C.UNKNOWN_SCENE_VARIANT, f"{op.variant_id} is not a variant of this scene")
        updated = replace(scene, scene_variants=sv_delete(current_set, op.variant_id))
        outcome["scene_variant_id"] = op.variant_id
        inverse = SceneVariantRestoreSet(scene.scene_id, current_set.to_dict()).to_dict()
    else:
        restored = SceneVariantSet.from_dict(op.scene_variants, "scene_variants") if op.scene_variants is not None else None
        _refuse_unsafe_set(restored)
        updated = replace(scene, scene_variants=sv_restore(current_set, op.scene_variants))
        inverse = SceneVariantRestoreSet(scene.scene_id, _set_wire(current_set)).to_dict()
    _record(current, plan, position, scene, updated, outcome, EditTier.STRUCTURE, inverse=inverse)


def scenes_changed(before: Sequence[StudioScene], after: Sequence[StudioScene]) -> bool:
    return _stored(before) != _stored(after)


# ------------------------------------------------------------------ enregistrement d'annulation

def undo_record(plan: EditPlan, *, presentation_id: str, variant_id: str, restores_revision: int,
                applies_at_revision: int) -> dict[str, Any]:
    """Enregistrement (pas d'anneau : Slice 08) de quoi défaire un lot validé : les opérations inverses, dans l'ordre,
    et la base sur laquelle elles s'appliquent. Les rejouer par la même API (`mode=commit`, `basis.variant_revision =
    applies_at_revision`) rétablit les scènes à l'octet près. Borné : au-delà de `MAX_UNDO_BYTES`, `available: false`."""

    record: dict[str, Any] = {
        "presentation_id": presentation_id, "variant_id": variant_id, "restores_revision": restores_revision,
        "applies_at_revision": applies_at_revision, "ops": list(plan.inverse)}
    size = len(json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if size > MAX_UNDO_BYTES:
        return {"available": False, "reason": "too_large", "bytes": size, "limit": MAX_UNDO_BYTES}
    return {"available": True, **record, "bytes": size}


# ------------------------------------------------------------------ résultat

@dataclass(frozen=True, slots=True)
class EditResult:
    status: EditStatus
    mode: EditMode
    actor: StudioActor
    presentation_id: str
    variant_id: str
    basis_revision: int
    #: Révision courante de la variante après l'appel (inchangée pour un aperçu, un refus, un état périmé).
    revision: int
    committed: bool = False
    changed: bool = False
    tier: EditTier | None = None
    ops: tuple[Mapping[str, Any], ...] = ()
    undo: Mapping[str, Any] | None = None
    source_requests: tuple[Mapping[str, Any], ...] = ()
    #: Demandes de source plus anciennes que la mémoire ne peut garder (elle est bornée et non durable) : jamais en silence.
    source_requests_dropped: int = 0
    code: str | None = None
    message: str | None = None
    failed_index: int | None = None
    #: `authority` when the actor may not request an operation (policy), not a verdict on the state: not on the wire.
    #: A caller that replays stored steps (the undo history) must not treat an authority refusal as a broken step.
    refusal_kind: str | None = None

    def to_dict(self) -> dict[str, Any]:
        wire: dict[str, Any] = {
            "status": self.status.value, "mode": self.mode.value, "actor": self.actor.value,
            "presentation_id": self.presentation_id, "variant_id": self.variant_id,
            "basis": {"variant_revision": self.basis_revision}, "revision": self.revision,
            "committed": self.committed, "changed": self.changed,
            "tier": self.tier.value if self.tier else None, "ops": [dict(op) for op in self.ops],
            "undo": dict(self.undo) if self.undo is not None else None,
            "source_requests": [dict(item) for item in self.source_requests],
            "source_requests_dropped": self.source_requests_dropped,
        }
        if self.status is not EditStatus.APPLIED:
            wire.update({"code": self.code, "message": (self.message or "")[:MAX_ERROR_CHARS],
                         "failed_index": self.failed_index,
                         # The same envelope every other Studio refusal has, so typed clients raise on it.
                         "error": {"code": self.code, "message": (self.message or "")[:MAX_ERROR_CHARS]}})
        return wire

    @property
    def http_status(self) -> int:
        if self.status is EditStatus.APPLIED:
            return 200
        if self.status is EditStatus.STALE:
            return 409
        return HTTP_STATUS[C(self.code)] if self.code else 400

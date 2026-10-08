"""Request bodies of the playback routes (handoff jarvis-interactive-presentation-studio, Slice 12), parsed strictly.

Pure. Every body is an exact-key object: an unexpected field (a `text`, a `command`, a `tool`) is a `ValueError`, which
the routes answer as a 400. The only things a request can name are ids from a closed vocabulary and the numbers of a
bounded structure: nothing here is ever interpreted as an instruction.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Any

from jarvis.domain.presentation_studio_edit import StudioActor
from jarvis.domain.presentation_studio_playback import AuxRef
from jarvis.domain.presentation_studio_roles import StudioRole, SwitchOrigin
from jarvis.domain.scene import ScenePrefabRef

MAX_BODY_BYTES = 32 * 1024
_PRESENTATION = re.compile(r"pst_[0-9a-f]{32}\Z")
_VARIANT = re.compile(r"psv_[0-9a-f]{32}\Z")
_ITEM = re.compile(r"psi_[0-9a-f]{12}\Z")
_SCENE = re.compile(r"pss_[0-9a-f]{12}\Z")
_SLUG = re.compile(r"[a-z][a-z0-9_]{0,39}\Z")


class Verb(StrEnum):
    """The commands of `POST /v1/presentation-studio/playback/{verb}` (a closed set)."""

    START = "start"
    STOP = "stop"
    PAUSE = "pause"
    RESUME = "resume"
    NEXT = "next"
    PREVIOUS = "previous"
    GOTO = "goto"
    DETOUR = "detour"
    RETURN = "return"
    REVEAL = "reveal"
    HIDE = "hide"
    EDIT = "edit"


def _exact(raw: object, name: str, required: set[str], optional: frozenset[str] = frozenset()) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{name} must be a JSON object")
    unknown = sorted(str(k)[:40] for k in raw if k not in required | optional)
    if unknown:
        raise ValueError(f"{name}: unexpected fields {', '.join(unknown[:4])}")
    missing = sorted(required - raw.keys())
    if missing:
        raise ValueError(f"{name}: missing {', '.join(missing)}")
    return dict(raw)


def actor_of(raw: Mapping[str, Any]) -> StudioActor:
    try:
        return StudioActor(raw.get("actor"))
    except ValueError:
        raise ValueError("actor must be 'user' or 'brain'") from None


@dataclass(frozen=True, slots=True)
class StartRequest:
    actor: StudioActor
    presentation_id: str
    variant_id: str | None
    role: StudioRole
    jarvis_speaks: bool | None
    origin: SwitchOrigin


def parse_start(raw: object) -> StartRequest:
    data = _exact(raw, "start", {"actor", "presentation_id", "role"},
                  frozenset({"variant_id", "jarvis_speaks", "origin"}))
    actor = actor_of(data)
    if not isinstance(data["presentation_id"], str) or not _PRESENTATION.fullmatch(data["presentation_id"]):
        raise ValueError("presentation_id is not a valid presentation id")
    variant = data.get("variant_id")
    if variant is not None and (not isinstance(variant, str) or not _VARIANT.fullmatch(variant)):
        raise ValueError("variant_id is not a valid variant id")
    try:
        role = StudioRole(data["role"])
    except ValueError:
        raise ValueError(f"role must be one of {', '.join(r.value for r in StudioRole)}") from None
    speaks = data.get("jarvis_speaks")
    if speaks is not None and type(speaks) is not bool:
        raise ValueError("jarvis_speaks must be a boolean")
    # A click in the Control Center is an explicit request. The brain declares what it is acting on: an omitted origin is
    # the spontaneous one, which the Slice 01c helper refuses to switch the mode for (Slice 21 sets it from the turn).
    default = SwitchOrigin.EXPLICIT_USER_REQUEST if actor is StudioActor.USER else SwitchOrigin.BRAIN_SPONTANEOUS
    try:
        origin = SwitchOrigin(data.get("origin", default.value))
    except ValueError:
        raise ValueError(f"origin must be one of {', '.join(o.value for o in SwitchOrigin)}") from None
    if actor is StudioActor.USER and origin is not SwitchOrigin.EXPLICIT_USER_REQUEST:
        raise ValueError("the user's own action is an explicit user request")
    return StartRequest(actor, data["presentation_id"], variant, role, speaks, origin)


def parse_actor_only(raw: object, name: str) -> StudioActor:
    return actor_of(_exact(raw, name, {"actor"}))


def parse_goto(raw: object) -> tuple[StudioActor, dict[str, Any]]:
    data = _exact(raw, "goto", {"actor"}, frozenset({"item_id", "scene_id", "position"}))
    target = {k: data[k] for k in ("item_id", "scene_id", "position") if k in data}
    if len(target) != 1:
        raise ValueError("goto names exactly one of item_id, scene_id, position")
    if "item_id" in target and not (isinstance(target["item_id"], str) and _ITEM.fullmatch(target["item_id"])):
        raise ValueError("item_id is not a valid score item id")
    if "scene_id" in target and not (isinstance(target["scene_id"], str) and _SCENE.fullmatch(target["scene_id"])):
        raise ValueError("scene_id is not a valid scene id")
    if "position" in target:
        position = target["position"]
        if type(position) is not int or position < 1:
            raise ValueError("position is a 1-based integer")
        target["position"] = position - 1
    return actor_of(data), target


def parse_anchor(raw: object, name: str) -> tuple[StudioActor, str]:
    data = _exact(raw, name, {"actor", "anchor_id"})
    if not isinstance(data["anchor_id"], str) or not _SLUG.fullmatch(data["anchor_id"]):
        raise ValueError("anchor_id must be a slug")
    return actor_of(data), data["anchor_id"]


def parse_detour(raw: object) -> tuple[StudioActor, str, ScenePrefabRef]:
    """`{actor, title, prefab: {id, version, props?, data?}}`: an auxiliary prefab window, exact pin, nothing else."""

    data = _exact(raw, "detour", {"actor", "title", "prefab"})
    block = _exact(data["prefab"], "detour.prefab", {"id", "version"}, frozenset({"props", "data"}))
    try:
        ref = ScenePrefabRef(block["id"], block["version"], block.get("props", {}), block.get("data", {}))
        AuxRef("aux-check", data["title"], ref.prefab_id, ref.version)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"detour: {exc}") from None
    return actor_of(data), data["title"], ref


def parse_edit(raw: object) -> tuple[StudioActor, int | None, list[Any]]:
    """`{actor, basis?: {variant_revision}, ops: [...]}`: the Slice 05 operations, validated by the edit service itself."""

    data = _exact(raw, "edit", {"actor", "ops"}, frozenset({"basis"}))
    basis = None
    if "basis" in data:
        inner = _exact(data["basis"], "basis", {"variant_revision"})
        basis = inner["variant_revision"]
        if type(basis) is not int or basis < 1:
            raise ValueError("basis.variant_revision must be a positive integer")
    if not isinstance(data["ops"], list):
        raise ValueError("ops must be a list")
    return actor_of(data), basis, data["ops"]

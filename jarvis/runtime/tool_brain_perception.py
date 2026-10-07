"""Perception du Tool Brain : instantané compact de ce que l'utilisateur voit + lectures ciblées (handoff
jarvis-tool-brain-ui-orchestrator, Slice 3).

Contrat : `docs/tool-brain-contracts.md` §9. **Projection pure, jamais persistance** : tout vient d'un
`UiState` lu par `tool_brain_choices.read_ui_state` chez les propriétaires (`SceneService`, `BoardService`).
Ce module ne garde aucun état, n'écrit rien et n'a pas de seconde source de vérité.

- `build_perception(state, ...)` : instantané **borné** (`MAX_PERCEPTION_BYTES`, JSON compact UTF-8), objets
  classés par pertinence, troncature **déterministe** (préfixe du classement) et marqueur explicite
  `truncated` + `omitted` ; sérialisation canonique (`serialize`, `digest`) pour rejouer une décision ;
- lectures ciblées sur identifiant stable : `get_information_on`, `list_related`, `get_available_actions`,
  `get_queue_state` (vide jusqu'à la Slice 6) ;
- coutures laissées vides, jamais inventées : `speech` (S4 le renseigne), `queue` (S6), `surfaces`
  (navigateur : n'existe pas, gap G1 / S7).

Pas de révision par objet (décision G3) : la fraîcheur est `StateRef` (scène+époque+révision, Board actif).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from jarvis.domain.scene import (
    ExecState, SceneObject, SceneRelation, SceneSnapshot, Representation, SceneObjectKind, Visibility,
    is_runtime_owned_relation,
)
from jarvis.domain.workspace_board import Board, BoardStatus
from jarvis.runtime.tool_brain_choices import (
    PROVIDERS, SCENE_UNAVAILABLE, UNKNOWN_OBJECT, BoardStateSource, SceneStateSource, UiState, _label,
    read_ui_state, validate_call,
)

PERCEPTION_SCHEMA = "tool_brain.perception/1"
INSPECTION_SCHEMA = "tool_brain.inspection/1"

#: Plafond **dur** de l'instantané sérialisé (octets UTF-8 du JSON compact ; ~3 octets/jeton => ~2 700 jetons).
MAX_PERCEPTION_BYTES = 8192
#: Part du budget restant (après le squelette) réservée aux objets ; le reste va aux liens.
OBJECT_BUDGET_SHARE = 0.8
MAX_BOARDS_LISTED = 8
MAX_SUMMARY_CHARS = 80
#: Lectures ciblées : bornes de ce qu'elles rendent.
MAX_INSPECT_SUMMARY_CHARS = 600
MAX_INSPECT_ITEMS = 8
MAX_RELATED = 24

# Codes de refus d'une lecture ciblée (ceux des propriétaires quand ils existent : `unknown_object`,
# `object_archived`, `board_not_found`, `scene_unavailable`).
UNKNOWN_ID = "unknown_id"

# États d'exécution qui demandent l'attention d'un décideur (classement de pertinence).
_ATTENTION_STATES = frozenset({ExecState.BLOCKED, ExecState.FAILED, ExecState.RUNNING, ExecState.PENDING,
                               ExecState.INTERRUPTED})


# ------------------------------------------------------------------ coutures (S4, S6)


@dataclass(frozen=True)
class SpeechSection:
    """Couture de la parole (Slice 4). Ici : **aucune vérité de parole**, seulement la place typée.

    `status == "not_wired"` tant que S4 ne branche pas sa projection `SpeechProgress` ; S4 passe alors
    `SpeechSection("wired", {...})` à `build_perception`. Le contenu est une donnée opaque pour ce module ;
    le budget d'octets du total le borne quand même (S4 doit rester compact).
    """

    status: str = "not_wired"
    data: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        wire: dict[str, Any] = {"status": self.status}
        if self.data:
            wire["data"] = dict(self.data)
        return wire


@dataclass(frozen=True)
class QueueSection:
    """Résumé de file d'actions (Slice 6). Vide et `not_wired` jusque-là."""

    status: str = "not_wired"
    items: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "count": len(self.items), "items": [dict(item) for item in self.items]}


def get_queue_state(queue: QueueSection | None = None) -> dict[str, Any]:
    """Lecture ciblée de la file. **Placeholder** : vide tant que S6 n'a pas fourni `QueueSection`."""

    return {"schema": INSPECTION_SCHEMA, "ok": True, "kind": "queue", **(queue or QueueSection()).to_dict()}


# ------------------------------------------------------------------ instantané


@dataclass(frozen=True)
class UiPerception:
    """Instantané figé. `data` est le contenu ; `serialize()` / `digest()` sont canoniques (rejeu)."""

    data: Mapping[str, Any]

    def serialize(self) -> str:
        return _canonical(self.data)

    def digest(self) -> str:
        return hashlib.sha256(self.serialize().encode("utf-8")).hexdigest()

    @property
    def size_bytes(self) -> int:
        return len(self.serialize().encode("utf-8"))

    @property
    def truncated(self) -> bool:
        return bool(self.data["truncated"])


def _canonical(value: Any) -> str:
    """JSON compact, clés triées : mêmes entrées => mêmes octets."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _size(value: Any) -> int:
    return len(_canonical(value).encode("utf-8"))


def _rank(item: SceneObject) -> tuple[int, int, str]:
    """Pertinence décroissante : signaux d'attention, nœuds qui demandent un regard, fenêtres, épinglés, reste ;
    puis couche haute d'abord ; puis id (départage stable)."""

    if item.kind is SceneObjectKind.ATTENTION:
        tier = 0
    elif item.exec_state in _ATTENTION_STATES:
        tier = 1
    elif item.representation is Representation.WINDOW:
        tier = 2
    elif item.constraints.pinned_by_user:
        tier = 3
    else:
        tier = 4
    return (tier, -item.layer, item.object_id)


def _object_entry(item: SceneObject) -> dict[str, Any]:
    """Entrée compacte : les valeurs par défaut sont omises (`state` si `unknown`, `pinned` si faux, `placed`
    si vrai) ; aucune charge volumineuse (l'inspection ciblée la rend)."""

    entry: dict[str, Any] = {"id": item.object_id, "kind": item.kind.value, "category": item.category,
                             "label": _label(item.payload.title, item.category),
                             "shape": item.representation.value}
    if item.exec_state is not ExecState.UNKNOWN:
        entry["state"] = item.exec_state.value
    if item.constraints.pinned_by_user:
        entry["pinned"] = True
    if item.geometry is None:
        entry["placed"] = False
    summary = " ".join(item.payload.summary.split())
    if summary:
        entry["summary"] = summary if len(summary) <= MAX_SUMMARY_CHARS else summary[: MAX_SUMMARY_CHARS - 1] + "…"
    if item.payload.prefab is not None:
        entry["prefab"] = item.payload.prefab.prefab_id
    return entry


def _relation_entry(relation: SceneRelation) -> dict[str, str]:
    return {"id": relation.relation_id, "kind": relation.kind.value, "from": relation.from_id, "to": relation.to_id}


def _boards_section(state: UiState) -> dict[str, Any]:
    usable = [board for board in state.boards if board.status is BoardStatus.ACTIVE]
    usable.sort(key=lambda board: (board.board_id != state.active_board_id, board.board_id))
    listed = usable[:MAX_BOARDS_LISTED]
    section: dict[str, Any] = {
        "active": state.active_board_id,
        "items": [{"id": board.board_id, "label": _label(board.title, board.board_id),
                   "active": board.board_id == state.active_board_id} for board in listed],
        # La scène est globale en V1 : changer de Board ne change pas les objets visibles (doc §1.2).
        "scene_scope": "global",
    }
    hidden = len(usable) - len(listed)
    if hidden:
        section["more"] = hidden
    archived = sum(1 for board in state.boards if board.status is BoardStatus.ARCHIVED)
    if archived:
        section["archived"] = archived
    return section


def _counts(snapshot: SceneSnapshot) -> dict[str, Any]:
    kinds: dict[str, int] = {}
    states: dict[str, int] = {}
    hidden = 0
    for item in snapshot.objects:
        kinds[item.kind.value] = kinds.get(item.kind.value, 0) + 1
        if item.exec_state is not ExecState.UNKNOWN:
            states[item.exec_state.value] = states.get(item.exec_state.value, 0) + 1
        if item.visibility is Visibility.HIDDEN:
            hidden += 1
    return {"objects": len(snapshot.objects), "hidden": hidden, "relations": len(snapshot.relations),
            "by_kind": kinds, "by_exec_state": states}


#: Surfaces de navigation annoncées (les plus récentes d'abord n'ont pas de sens : ordre stable par id) ; le reste est compté.
MAX_PERCEPTION_SURFACES = 8


def _surfaces_section(state: UiState) -> dict[str, Any]:
    """Surfaces de navigation (S7) : dérivées de la scène par `UiState.surfaces`, sans contenu de page."""

    if state.scene is None:
        return {"status": "unavailable", "reason": "the scene is not served", "items": []}
    surfaces = state.surfaces
    return {"status": "available", "total": len(surfaces), "truncated": len(surfaces) > MAX_PERCEPTION_SURFACES,
            "items": [{"surface_id": surface.surface_id, **surface.meta()}
                      for surface in surfaces[:MAX_PERCEPTION_SURFACES]]}


def build_perception(state: UiState, *, speech: SpeechSection | None = None, queue: QueueSection | None = None,
                     max_bytes: int = MAX_PERCEPTION_BYTES) -> UiPerception:
    """Instantané de ce que l'utilisateur voit, **toujours** <= `max_bytes` une fois sérialisé.

    Objets visibles uniquement (un objet caché n'est pas vu ; il reste compté et inspectable), classés par
    `_rank` ; on garde le plus long préfixe qui tient dans la part d'objets du budget, puis les liens dont les
    deux extrémités sont gardées. `truncated` vaut vrai dès que quelque chose est omis, `omitted` dit combien.
    Scène non servie : `scene` vaut `null`, `truncated` faux.
    """

    snapshot = state.scene
    data: dict[str, Any] = {
        "schema": PERCEPTION_SCHEMA,
        "state": state.ref().to_dict(),
        "board": _boards_section(state),
        "scene": None if snapshot is None else {"counts": _counts(snapshot), "objects": [], "relations": []},
        "surfaces": _surfaces_section(state),
        "queue": (queue or QueueSection()).to_dict(),
        "speech": (speech or SpeechSection()).to_dict(),
        "truncated": False,
        "omitted": {"objects": 0, "relations": 0},
        "budget": {"max_bytes": max_bytes},
    }
    if snapshot is None:
        return UiPerception(_fit_or_raise(data, max_bytes))
    visible = sorted((item for item in snapshot.objects if item.visibility is Visibility.VISIBLE), key=_rank)
    # Réserve pour les compteurs `omitted` / `truncated` rédigés après coup (chiffres à largeur variable).
    room = max_bytes - _size({**data, "truncated": True, "omitted": {"objects": len(visible) + 1_000_000,
                                                                      "relations": len(snapshot.relations) + 1_000_000}})
    if room < 0:
        raise ValueError(f"max_bytes={max_bytes} cannot hold the perception skeleton")
    object_room = int(room * OBJECT_BUDGET_SHARE)
    kept: list[SceneObject] = []
    entries: list[dict[str, Any]] = []
    used = 0
    for item in visible:
        entry = _object_entry(item)
        cost = _size(entry) + 1  # + la virgule
        if used + cost > object_room:
            break
        kept.append(item)
        entries.append(entry)
        used += cost
    kept_ids = {item.object_id for item in kept}
    relation_room = room - used
    relations: list[dict[str, str]] = []
    rel_used = 0
    for relation in sorted(snapshot.relations, key=lambda r: r.relation_id):
        if relation.from_id not in kept_ids or relation.to_id not in kept_ids:
            continue
        entry = _relation_entry(relation)
        cost = _size(entry) + 1
        if rel_used + cost > relation_room:
            break
        relations.append(entry)
        rel_used += cost
    omitted_objects = len(visible) - len(entries)
    omitted_relations = len(snapshot.relations) - len(relations)
    data["scene"]["objects"] = entries
    data["scene"]["relations"] = relations
    data["omitted"] = {"objects": omitted_objects, "relations": omitted_relations}
    data["truncated"] = bool(omitted_objects or omitted_relations)
    return UiPerception(_fit_or_raise(data, max_bytes))


def _fit_or_raise(data: dict[str, Any], max_bytes: int) -> dict[str, Any]:
    """Garde-fou du plafond dur : un dépassement est un bug (ou une section `speech` trop grosse), jamais tu."""

    size = _size(data)
    if size > max_bytes:
        raise ValueError(f"perception is {size} bytes, over the {max_bytes} bytes budget "
                         "(a wired speech/queue section is probably too large)")
    return data


async def perceive(scene: SceneStateSource | None, boards: BoardStateSource | None, *,
                   speech: SpeechSection | None = None, queue: QueueSection | None = None,
                   max_bytes: int = MAX_PERCEPTION_BYTES) -> UiPerception:
    """Lit l'état chez ses propriétaires (`read_ui_state`) puis projette. Point d'entrée des Slices 5 et 6."""

    return build_perception(await read_ui_state(scene, boards), speech=speech, queue=queue, max_bytes=max_bytes)


# ------------------------------------------------------------------ lectures ciblées


def _refused(code: str, identifier: str, detail: str) -> dict[str, Any]:
    return {"schema": INSPECTION_SCHEMA, "ok": False, "code": code, "id": identifier[:80], "detail": detail}


def _find_board(state: UiState, identifier: str) -> Board | None:
    return next((board for board in state.boards if board.board_id == identifier), None)


def _resolve(state: UiState, identifier: str) -> tuple[str, Any] | dict[str, Any]:
    """`("object" | "relation" | "board", valeur)` ou un refus. Le refus reprend le code du propriétaire."""

    if not isinstance(identifier, str) or not identifier:
        return _refused(UNKNOWN_ID, str(identifier), "an id is required")
    snapshot = state.scene
    if snapshot is not None:
        found = snapshot.get_object(identifier)
        if found is not None:
            return "object", found
        relation = snapshot.get_relation(identifier)
        if relation is not None:
            return "relation", relation
    board = _find_board(state, identifier)
    if board is not None:
        return "board", board
    if snapshot is None:
        return _refused(SCENE_UNAVAILABLE, identifier, "the scene is not served")
    if snapshot.is_archived(identifier):
        return _refused(PROVIDERS["scene.object"].refusal(state, identifier), identifier, "the object was archived")
    return _refused(UNKNOWN_ID, identifier, "not an object, relation or Board of the current state")


def inspectable_ids(state: UiState) -> tuple[str, ...]:
    """Les identifiants qu'une lecture ciblée accepte maintenant : objets (cachés compris), liens, Boards."""

    ids: list[str] = []
    if state.scene is not None:
        ids += [item.object_id for item in state.scene.objects] + [r.relation_id for r in state.scene.relations]
    ids += [board.board_id for board in state.boards]
    return tuple(sorted(ids))


def _object_detail(snapshot: SceneSnapshot, item: SceneObject) -> dict[str, Any]:
    payload = item.payload
    detail: dict[str, Any] = {
        **_object_entry(item),
        "visibility": item.visibility.value, "exec_state": item.exec_state.value, "origin": item.origin.value,
        "layer": item.layer, "order": item.order, "placed_by": item.constraints.placed_by.value,
        "pinned": item.constraints.pinned_by_user,
        "title": payload.title, "summary": payload.summary[:MAX_INSPECT_SUMMARY_CHARS],
        "summary_truncated": len(payload.summary) > MAX_INSPECT_SUMMARY_CHARS,
        "items": [{"label": entry.label, "ref": entry.ref, "url": entry.url} for entry in payload.items[:MAX_INSPECT_ITEMS]],
        "items_total": len(payload.items),
    }
    if payload.annotation:
        detail["annotation"] = payload.annotation
    if item.geometry is not None:
        detail["geometry"] = item.geometry.to_payload()
    if item.work_ref is not None:
        detail["work_ref"] = item.work_ref.to_payload()
    detail["related_count"] = sum(1 for relation in snapshot.relations if item.object_id in (relation.from_id, relation.to_id))
    return detail


def _board_detail(state: UiState, board: Board) -> dict[str, Any]:
    return {"id": board.board_id, "label": _label(board.title, board.board_id), "title": board.title,
            "status": board.status.value, "board_kind": board.board_kind.value,
            "active": board.board_id == state.active_board_id,
            "context_summary": board.context_summary[:MAX_INSPECT_SUMMARY_CHARS],
            "task_refs": len(board.task_refs), "artifact_refs": len(board.artifact_refs),
            "project_refs": len(board.project_refs), "interaction_mode": board.interaction_mode.value,
            "scene_scope": "global"}


def get_information_on(state: UiState, identifier: str) -> dict[str, Any]:
    """Lecture ciblée : plus riche que l'entrée de l'instantané, pour **le même** identifiant stable.

    Rend `{"ok": true, "kind": "object" | "relation" | "board", "info": {...}}` ou un refus propre
    (`unknown_id`, `object_archived`, `scene_unavailable`). Ne lit que `state` : aucune E/S, aucune écriture.
    """

    resolved = _resolve(state, identifier)
    if isinstance(resolved, dict):
        return resolved
    kind, value = resolved
    if kind == "object":
        assert state.scene is not None
        info = _object_detail(state.scene, value)
    elif kind == "relation":
        info = _relation_entry(value)
        assert state.scene is not None
        info["removable"] = not is_runtime_owned_relation(state.scene, value)
    else:
        info = _board_detail(state, value)
    return {"schema": INSPECTION_SCHEMA, "ok": True, "kind": kind, "state": state.ref().to_dict(), "info": info}


def list_related(state: UiState, identifier: str) -> dict[str, Any]:
    """Objets reliés à un objet de scène (les deux sens), triés par id de lien, bornés (`MAX_RELATED`)."""

    resolved = _resolve(state, identifier)
    if isinstance(resolved, dict):
        return resolved
    kind, value = resolved
    if kind != "object":
        return _refused(UNKNOWN_OBJECT, identifier, f"related objects exist for scene objects only, not a {kind}")
    assert state.scene is not None
    rows = []
    for relation in sorted(state.scene.relations, key=lambda r: r.relation_id):
        if identifier not in (relation.from_id, relation.to_id):
            continue
        outgoing = relation.from_id == identifier
        other = state.scene.get_object(relation.to_id if outgoing else relation.from_id)
        assert other is not None  # invariant de SceneSnapshot : une relation lie des objets actifs
        rows.append({"relation_id": relation.relation_id, "kind": relation.kind.value,
                     "direction": "out" if outgoing else "in", "id": other.object_id,
                     "label": _label(other.payload.title, other.category), "object_kind": other.kind.value})
    return {"schema": INSPECTION_SCHEMA, "ok": True, "kind": "related", "state": state.ref().to_dict(),
            "id": identifier, "total": len(rows), "truncated": len(rows) > MAX_RELATED, "items": rows[:MAX_RELATED]}


def get_available_actions(catalog: Mapping[str, Any], state: UiState, identifier: str) -> dict[str, Any]:
    """Outils d'interface applicables **maintenant** à un identifiant, d'après le catalogue canonique.

    Pour chaque outil dont un paramètre à fournisseur peut recevoir l'id (type de l'id selon `_resolve`), on
    rejoue `validate_call` (le même contrôle que la Slice 6) avec cet id seul : seuls les verdicts sans refus
    restent. Rend aussi `reversibility` / `side_effect` pour que le décideur pèse le risque. Aucune liste
    parallèle : tout vient de `ToolMeta` via le catalogue.
    """

    resolved = _resolve(state, identifier)
    if isinstance(resolved, dict):
        return resolved
    kind = resolved[0]
    wanted = {"object": {"scene.object"}, "relation": {"scene.relation"},
              "board": {"board.switchable", "board.readable"}}[kind]
    actions: list[dict[str, Any]] = []
    for tool in catalog["tools"]:
        ui = tool.get("ui")
        if ui is None:
            continue
        for parameter, provider_id in sorted(ui["choice_providers"].items()):
            if provider_id not in wanted:
                continue
            verdict = validate_call(tool["server"], tool["name"], {parameter: identifier}, state)
            if not verdict.ok:
                continue
            actions.append({"tool": tool["name"], "server": tool["server"], "parameter": parameter,
                            "side_effect": tool["side_effect"], "reversibility": ui["reversibility"]})
    actions.sort(key=lambda row: (row["tool"], row["parameter"]))
    return {"schema": INSPECTION_SCHEMA, "ok": True, "kind": "actions", "state": state.ref().to_dict(),
            "id": identifier, "id_kind": kind, "items": actions}


#: Noms des lectures ciblées exposées au décideur (S5), `nom -> fonction`. Le câblage appartient à S5.
INSPECTION_READS: tuple[str, ...] = ("get_information_on", "list_related", "get_available_actions", "get_queue_state")

__all__ = [
    "INSPECTION_READS", "MAX_PERCEPTION_BYTES", "PERCEPTION_SCHEMA", "QueueSection", "SpeechSection",
    "UiPerception", "build_perception", "get_available_actions", "get_information_on", "get_queue_state",
    "inspectable_ids", "list_related", "perceive",
]

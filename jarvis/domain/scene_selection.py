"""Sélection de scène et constellation canonique (handoff jarvis-mcp-semantic-batch-inspector, Slice 02).

Contrat : `docs/scene-selection-batch.md` §1–§3. Module pur, sans E/S :

- `SceneSelection` : valeur stricte et sérialisable qui désigne des objets,
  soit par identifiants (mode explicite), soit par filtres (mode filtres) ;
  décodée et validée sans lire la scène (§1.5) ;
- `resolve_selection` : membres d'une sélection sur **un** instantané, dans
  l'ordre canonique (§1.3), avec les références refusées (§3) et, pour une
  opération qui exige un objet placé, les membres de filtre écartés (§3.2) ;
- `constellation_of` : la constellation canonique (§2), même mot, même
  ensemble pour le MCP, la page et Bare Hands. La page en garde une copie
  (`constellationOf`, `control_center_scene_interact.js`), tenue par les
  fixtures partagées `tests/fixtures/scene_constellation_cases.json`.

Aucune commande n'est câblée ici (Slice 03) ; le MCP bascule sur ce module
en Slice 05.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import StrEnum
import math
from typing import Any

from jarvis.domain._checks import check_id, check_text, check_token
from jarvis.domain.scene import (
    MAX_CATEGORY_CHARS,
    MAX_SCENE_EXTENT,
    MAX_SCENE_OBJECTS,
    ExecState,
    RelationKind,
    SceneActor,
    SceneGeometry,
    SceneObject,
    SceneObjectKind,
    SceneRefusal,
    SceneSnapshot,
    Visibility,
    _check_keys,
    _enum,
    signal_owners,
)

#: Borne unique d'une sélection, pour tout acteur et toute commande de
#: sélection (§1.4). Un filtre ne peut la dépasser : une scène tient au plus
#: `MAX_SCENE_OBJECTS` objets actifs. Elle ne mord que sur `ids`.
MAX_SELECTION_IDS = MAX_SCENE_OBJECTS
MAX_SELECTION_KINDS = len(SceneObjectKind)
MAX_SELECTION_EXEC_STATES = len(ExecState)
#: `text` et `work` (= `MAX_FILTER_CHARS` du MCP).
MAX_SELECTION_TEXT_CHARS = 160
MAX_SELECTION_EXCLUDE = 32
#: Profondeur de constellation (= `MAX_CONNECTED_DEPTH` du MCP).
MAX_CONSTELLATION_DEPTH = 6
MAX_NEAR_RADIUS = MAX_SCENE_EXTENT


class SelectionMode(StrEnum):
    EXPLICIT = "explicit"
    FILTER = "filter"


# ------------------------------------------------------------------ prédicats
# Règles de correspondance du vocabulaire de filtres. `display_mcp` les
# importe : lecture (`scene_query`) et lots désignent avec les mêmes règles.


def text_matches(item: SceneObject, text: str) -> bool:
    """`text` : sous-chaîne sans casse du titre, de l'identifiant ou de l'étiquette (annotation)."""

    needle = text.casefold()
    return (needle in item.payload.title.casefold() or needle in item.object_id.casefold()
            or needle in item.payload.annotation.casefold())


def work_matches(item: SceneObject, work: str) -> bool:
    """`work` : `source`, `external_id`, `work_id` ou `source:external_id` du travail Core, à l'identique."""

    ref = item.work_ref
    if ref is None:
        return False
    return work in (ref.source, ref.external_id, ref.work_id, f"{ref.source}:{ref.external_id}")


def box_distance(a: SceneGeometry, b: SceneGeometry) -> float:
    """Distance entre deux rectangles, bord à bord, en unités de scène ; 0 quand ils se touchent ou se chevauchent."""

    dx = max(0.0, a.x - (b.x + b.w), b.x - (a.x + a.w))
    dy = max(0.0, a.y - (b.y + b.h), b.y - (a.y + a.h))
    return math.hypot(dx, dy)


# ------------------------------------------------------------------ constellation


def _check_depth(name: str, depth: object) -> None:
    if depth is None:
        return
    if isinstance(depth, bool) or not isinstance(depth, int):
        raise TypeError(f"{name} must be an integer")
    if not 1 <= depth <= MAX_CONSTELLATION_DEPTH:
        raise ValueError(f"{name} must be between 1 and {MAX_CONSTELLATION_DEPTH}")


def constellation_of(snapshot: SceneSnapshot, root: str, depth: int | None = None) -> tuple[str, ...]:
    """Constellation canonique de `root` (§2) : racine en tête, puis ordre de découverte en largeur.

    Graphe non orienté sur les objets actifs : chaque relation, quels que
    soient sa nature et son sens, plus une arête virtuelle signal → étoile pour
    chaque signal runtime rattaché (`signal_owners`, repli par le travail
    compris). Les objets masqués en sont (masquer n'est pas archiver) ; les
    archivés ne sont pas dans l'instantané. Adjacence : relations dans l'ordre
    de la scène, puis `signal_owners` dans l'ordre des objets — l'algorithme de
    la page (`constellationOf`). `depth` absent : toute la composante ; sinon
    1–6 sauts, une arête virtuelle comptant pour un. Racine inconnue : `()`,
    comme la page ; la sélection, elle, refuse (`resolve_selection`).
    """

    _check_depth("depth", depth)
    if snapshot.get_object(root) is None:
        return ()
    near: dict[str, list[str]] = {}

    def tie(a: str, b: str) -> None:
        near.setdefault(a, []).append(b)
        near.setdefault(b, []).append(a)

    for relation in snapshot.relations:
        tie(relation.from_id, relation.to_id)
    for signal, owner in signal_owners(snapshot).items():
        if owner is not None and owner != signal:
            tie(signal, owner)
    order = [root]
    hops = {root: 0}
    queue = deque([root])
    while queue:
        node = queue.popleft()
        if depth is not None and hops[node] >= depth:
            continue
        for other in near.get(node, ()):
            if other not in hops:
                hops[other] = hops[node] + 1
                order.append(other)
                queue.append(other)
    return tuple(order)


# ------------------------------------------------------------------ sélection


@dataclass(frozen=True, slots=True)
class ConstellationScope:
    """`constellation` : `{object_id, depth?}`."""

    object_id: str
    depth: int | None = None

    def __post_init__(self) -> None:
        check_id("constellation.object_id", self.object_id, required=True)
        _check_depth("constellation.depth", self.depth)

    def to_payload(self) -> dict[str, Any]:
        wire: dict[str, Any] = {"object_id": self.object_id}
        if self.depth is not None:
            wire["depth"] = self.depth
        return wire

    @classmethod
    def from_payload(cls, payload: object) -> ConstellationScope:
        data = _check_keys("constellation", payload, frozenset({"object_id"}), frozenset({"depth"}))
        return cls(object_id=data["object_id"], depth=data.get("depth"))


@dataclass(frozen=True, slots=True)
class NearScope:
    """`near` : `{object_id, radius}`, distance bord à bord ≤ `radius`."""

    object_id: str
    radius: float

    def __post_init__(self) -> None:
        check_id("near.object_id", self.object_id, required=True)
        radius = self.radius
        if isinstance(radius, bool) or not isinstance(radius, (int, float)):
            raise TypeError("near.radius must be a number")
        try:
            number = float(radius)
        except OverflowError:
            raise ValueError("near.radius is out of range") from None
        if not math.isfinite(number) or not 0 <= number <= MAX_NEAR_RADIUS:
            raise ValueError(f"near.radius must be a finite number between 0 and {MAX_NEAR_RADIUS:g}")
        object.__setattr__(self, "radius", number)

    def to_payload(self) -> dict[str, Any]:
        return {"object_id": self.object_id, "radius": self.radius}

    @classmethod
    def from_payload(cls, payload: object) -> NearScope:
        data = _check_keys("near", payload, frozenset({"object_id", "radius"}))
        return cls(object_id=data["object_id"], radius=data["radius"])


_FILTER_KEYS = frozenset({
    "kind", "kinds", "category", "origin", "visibility", "exec_state", "exec_states", "text", "work", "explains",
    "constellation", "group", "near", "include_hidden", "exclude",
})
_SELECTION_KEYS = _FILTER_KEYS | {"ids"}


def _id_list(name: str, raw: object, limit: int) -> tuple[str, ...]:
    if not isinstance(raw, (list, tuple)):
        raise TypeError(f"{name} must be a list")
    if not raw:
        raise ValueError(f"{name} must not be empty")
    if len(raw) > limit:
        raise ValueError(f"{name} holds at most {limit} entries")
    for value in raw:
        check_id(f"{name}[]", value, required=True)
    if len(set(raw)) != len(raw):
        raise ValueError(f"{name} must not repeat an id")
    return tuple(raw)


def _enum_list(name: str, raw: object, enum_type: type[StrEnum], limit: int) -> tuple[Any, ...]:
    if not isinstance(raw, (list, tuple)):
        raise TypeError(f"{name} must be a list")
    if not raw:
        raise ValueError(f"{name} must not be empty")
    if len(raw) > limit:
        raise ValueError(f"{name} holds at most {limit} entries")
    values = tuple(value if isinstance(value, enum_type) else _enum(enum_type, value, f"{name}[]") for value in raw)
    if len(set(values)) != len(values):
        raise ValueError(f"{name} must not repeat a value")
    return values


def _check_filter_text(name: str, value: object) -> None:
    check_text(name, value, MAX_SELECTION_TEXT_CHARS, single_line=False)
    if not value:
        raise ValueError(f"{name} must not be empty")


@dataclass(frozen=True, slots=True)
class SceneSelection:
    """Désignation stricte d'objets de scène (§1). Deux modes exclusifs.

    - explicite : `ids` seul ;
    - filtres : au moins un filtre, pas d'`ids`. ET entre champs, OU dans
      `kinds` / `exec_states` ; `exclude` s'applique en dernier.

    Forme canonique : `kind` et `exec_state` du fil sont du sucre pour une
    liste d'un élément ; la valeur ne garde que `kinds` / `exec_states` et
    `to_payload` émet le pluriel. Construite directement, elle valide tout ce
    que le décodage valide (`__post_init__`) ; les références (objets nommés)
    ne sont vérifiées qu'à la résolution, sur l'instantané.
    """

    ids: tuple[str, ...] | None = None
    kinds: tuple[SceneObjectKind, ...] | None = None
    category: str | None = None
    origin: SceneActor | None = None
    visibility: Visibility | None = None
    exec_states: tuple[ExecState, ...] | None = None
    text: str | None = None
    work: str | None = None
    explains: str | None = None
    constellation: ConstellationScope | None = None
    group: str | None = None
    near: NearScope | None = None
    include_hidden: bool = False
    exclude: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self.ids is not None:
            object.__setattr__(self, "ids", _id_list("ids", self.ids, MAX_SELECTION_IDS))
        if self.kinds is not None:
            object.__setattr__(self, "kinds", _enum_list("kinds", self.kinds, SceneObjectKind, MAX_SELECTION_KINDS))
        if self.exec_states is not None:
            object.__setattr__(self, "exec_states",
                               _enum_list("exec_states", self.exec_states, ExecState, MAX_SELECTION_EXEC_STATES))
        if self.category is not None:
            check_token("category", self.category, MAX_CATEGORY_CHARS, required=True)
        for name, enum_type in (("origin", SceneActor), ("visibility", Visibility)):
            value = getattr(self, name)
            if value is not None and not isinstance(value, enum_type):
                raise TypeError(f"{name} must be a {enum_type.__name__}")
        for name in ("text", "work"):
            if getattr(self, name) is not None:
                _check_filter_text(name, getattr(self, name))
        for name in ("explains", "group"):
            check_id(name, getattr(self, name), required=False)
        if self.constellation is not None and not isinstance(self.constellation, ConstellationScope):
            raise TypeError("constellation must be a ConstellationScope")
        if self.near is not None and not isinstance(self.near, NearScope):
            raise TypeError("near must be a NearScope")
        if not isinstance(self.include_hidden, bool):
            raise TypeError("include_hidden must be a boolean")
        if self.include_hidden and self.near is None:
            raise ValueError("include_hidden only applies to near")
        if self.exclude is not None:
            object.__setattr__(self, "exclude", _id_list("exclude", self.exclude, MAX_SELECTION_EXCLUDE))
        filtered = any(getattr(self, name) is not None for name in (
            "kinds", "category", "origin", "visibility", "exec_states", "text", "work", "explains",
            "constellation", "group", "near"))
        if self.ids is not None and filtered:
            raise ValueError("a selection gives either ids or filters, not both")
        if self.ids is not None and self.exclude is not None:
            raise ValueError("exclude only applies to filters, not to ids")
        if self.ids is None and not filtered:
            # `exclude` seul n'est pas un filtre : « tout sauf ça » passe par `kinds`.
            raise ValueError("a selection gives ids or at least one filter")

    @property
    def mode(self) -> SelectionMode:
        return SelectionMode.EXPLICIT if self.ids is not None else SelectionMode.FILTER

    def to_payload(self) -> dict[str, Any]:
        wire: dict[str, Any] = {}
        for name in ("ids", "kinds", "exec_states", "exclude"):
            value = getattr(self, name)
            if value is not None:
                wire[name] = [item.value if isinstance(item, StrEnum) else item for item in value]
        for name in ("category", "text", "work", "explains", "group"):
            if getattr(self, name) is not None:
                wire[name] = getattr(self, name)
        for name in ("origin", "visibility"):
            if getattr(self, name) is not None:
                wire[name] = getattr(self, name).value
        if self.constellation is not None:
            wire["constellation"] = self.constellation.to_payload()
        if self.near is not None:
            wire["near"] = self.near.to_payload()
        if self.include_hidden:
            wire["include_hidden"] = True
        return wire

    @classmethod
    def from_payload(cls, payload: object) -> SceneSelection:
        """Décodage strict du fil (§1.5) ; `TypeError` / `ValueError` sans lire la scène."""

        data = _check_keys("selection", payload, frozenset(), _SELECTION_KEYS)
        for singular, plural in (("kind", "kinds"), ("exec_state", "exec_states")):
            if singular in data and plural in data:
                raise ValueError(f"give {singular} or {plural}, not both")
        kinds = [data["kind"]] if "kind" in data else data.get("kinds")
        exec_states = [data["exec_state"]] if "exec_state" in data else data.get("exec_states")
        include_hidden = data.get("include_hidden", False)
        # Présente sans `near`, même à `false` : refusée (§1.5).
        if "include_hidden" in data and "near" not in data:
            raise ValueError("include_hidden only applies to near")
        return cls(
            ids=data.get("ids"),
            kinds=None if kinds is None else _enum_list("kinds", kinds, SceneObjectKind, MAX_SELECTION_KINDS),
            category=data.get("category"),
            origin=None if "origin" not in data else _enum(SceneActor, data["origin"], "origin"),
            visibility=None if "visibility" not in data else _enum(Visibility, data["visibility"], "visibility"),
            exec_states=None if exec_states is None else _enum_list(
                "exec_states", exec_states, ExecState, MAX_SELECTION_EXEC_STATES),
            text=data.get("text"),
            work=data.get("work"),
            explains=data.get("explains"),
            constellation=None if "constellation" not in data else ConstellationScope.from_payload(data["constellation"]),
            group=data.get("group"),
            near=None if "near" not in data else NearScope.from_payload(data["near"]),
            include_hidden=include_hidden,
            exclude=data.get("exclude"),
        )


# ------------------------------------------------------------------ résolution


@dataclass(frozen=True, slots=True)
class SelectionRefusal:
    """Identifiant ou référence qui fait refuser toute la sélection (§3.2).

    `field` : `ids`, `constellation`, `near`, `explains`, `group` ou `exclude`.
    """

    object_id: str
    reason: SceneRefusal
    field: str

    def to_payload(self) -> dict[str, Any]:
        return {"id": self.object_id, "reason": self.reason.value, "field": self.field}


@dataclass(frozen=True, slots=True)
class SelectionSkip:
    """Membre de filtre écarté pour l'opération, toujours rapporté (§3.2)."""

    object_id: str
    reason: SceneRefusal

    def to_payload(self) -> dict[str, Any]:
        return {"id": self.object_id, "reason": self.reason.value}


@dataclass(frozen=True, slots=True)
class SelectionResolution:
    """Résultat de `resolve_selection` sur un instantané, indépendant de l'opération.

    - `refused` : références et ids qui refusent toute la sélection quelle que
      soit l'opération, en ordre canonique — références d'abord
      (`constellation`, `near`, `explains`, `group`, `exclude[]`), puis ids
      dans l'ordre de l'appelant. Non vide ⇒ `matched_ids` et `skipped` vides,
      `hidden_count` nul.
    - `archived_ids` : mode explicite, ids nommés déjà archivés, ordre de
      l'appelant, jamais dans `matched_ids`. Refus `object_archived` pour toute
      opération sauf `archive_selection`, où ils sont inchangés (§3.1) :
      l'opération tranche par `refusals(archived_ok=...)`.
    - `matched_ids` : membres actifs, ordre canonique (§1.3), `exclude` retiré.
    - `skipped` ⊆ `matched_ids` : membres de filtre écartés (§3.2).
    - `hidden_count` : membres retenus masqués — le MCP le dit au cerveau
      (il agit sur des objets que l'utilisateur ne voit pas).
    """

    mode: SelectionMode
    matched_ids: tuple[str, ...] = ()
    skipped: tuple[SelectionSkip, ...] = ()
    refused: tuple[SelectionRefusal, ...] = ()
    archived_ids: tuple[str, ...] = ()
    hidden_count: int = 0
    #: `refused` et les archivés fusionnés dans l'ordre de l'appelant : ce que
    #: refuse une opération qui n'accepte pas d'id archivé. Rempli par le
    #: résolveur ; lire par `refusals(archived_ok=False)`.
    refused_with_archived: tuple[SelectionRefusal, ...] = ()

    @property
    def eligible_ids(self) -> tuple[str, ...]:
        """Membres à planifier : retenus moins écartés, ordre canonique."""

        skipped = {skip.object_id for skip in self.skipped}
        return tuple(object_id for object_id in self.matched_ids if object_id not in skipped)

    def refusals(self, *, archived_ok: bool) -> tuple[SelectionRefusal, ...]:
        """Tout ce qui refuse la commande, en ordre canonique ; vide : elle peut être planifiée.

        `archived_ok` : l'opération tient un id explicite archivé pour inchangé
        (`archive_selection`). Sinon chaque id archivé est un refus
        `object_archived`, à sa place dans l'ordre de l'appelant.
        """

        return self.refused if archived_ok else self.refused_with_archived

    def reason(self, *, archived_ok: bool) -> SceneRefusal | None:
        """Motif unique de la commande : celui de la première entrée de `refusals`."""

        entries = self.refusals(archived_ok=archived_ok)
        return entries[0].reason if entries else None


def _reference_problem(by_id: dict[str, SceneObject], snapshot: SceneSnapshot, object_id: str) -> SceneRefusal | None:
    if object_id in by_id:
        return None
    return SceneRefusal.OBJECT_ARCHIVED if snapshot.is_archived(object_id) else SceneRefusal.UNKNOWN_OBJECT


def _hidden_count(by_id: dict[str, SceneObject], ids: tuple[str, ...]) -> int:
    return sum(1 for object_id in ids if by_id[object_id].visibility is Visibility.HIDDEN)


def resolve_selection(snapshot: SceneSnapshot, selection: SceneSelection, *,
                      require_placed: bool = False) -> SelectionResolution:
    """Membres de `selection` sur `snapshot` (§1.2, §1.3, §3). Pure, déterministe.

    - Mode explicite : l'ordre de l'appelant. Id inconnu → refus
      `unknown_object` ; id archivé → `archived_ids` (l'opération tranche).
      Avec `require_placed` (épingler, translater), un id sans géométrie
      refuse tout (`unplaced`).
    - Mode filtres : une référence (`constellation`, `near`, `explains`,
      `group`, `exclude[]`) inconnue ou archivée refuse tout ; la référence de
      `near` doit être placée (`unplaced`), celle de `group` être un objet
      `group` (`invalid_selection`). Avec `require_placed`, un membre sans
      géométrie est **écarté** et rapporté (`skipped`), jamais retiré en
      silence.

    Tout est évalué avant de refuser : chaque fautif est listé.
    """

    if not isinstance(snapshot, SceneSnapshot):
        raise TypeError("snapshot must be a SceneSnapshot")
    if not isinstance(selection, SceneSelection):
        raise TypeError("selection must be a SceneSelection")
    by_id = {item.object_id: item for item in snapshot.objects}
    if selection.mode is SelectionMode.EXPLICIT:
        return _resolve_explicit(by_id, snapshot, selection, require_placed)
    return _resolve_filter(by_id, snapshot, selection, require_placed)


def _resolve_explicit(by_id: dict[str, SceneObject], snapshot: SceneSnapshot, selection: SceneSelection,
                      require_placed: bool) -> SelectionResolution:
    assert selection.ids is not None
    refused: list[SelectionRefusal] = []
    merged: list[SelectionRefusal] = []
    archived: list[str] = []
    active: list[str] = []
    for object_id in selection.ids:
        problem = _reference_problem(by_id, snapshot, object_id)
        if problem is None and require_placed and by_id[object_id].geometry is None:
            problem = SceneRefusal.UNPLACED
        if problem is None:
            active.append(object_id)
            continue
        entry = SelectionRefusal(object_id, problem, "ids")
        merged.append(entry)
        if problem is SceneRefusal.OBJECT_ARCHIVED:
            archived.append(object_id)
        else:
            refused.append(entry)
    if refused:
        return SelectionResolution(SelectionMode.EXPLICIT, refused=tuple(refused), archived_ids=tuple(archived),
                                   refused_with_archived=tuple(merged))
    return SelectionResolution(SelectionMode.EXPLICIT, matched_ids=tuple(active), archived_ids=tuple(archived),
                               hidden_count=_hidden_count(by_id, tuple(active)), refused_with_archived=tuple(merged))


def _resolve_filter(by_id: dict[str, SceneObject], snapshot: SceneSnapshot, selection: SceneSelection,
                    require_placed: bool) -> SelectionResolution:
    refused: list[SelectionRefusal] = []
    references: list[tuple[str, str]] = []
    if selection.constellation is not None:
        references.append((selection.constellation.object_id, "constellation"))
    if selection.near is not None:
        references.append((selection.near.object_id, "near"))
    if selection.explains is not None:
        references.append((selection.explains, "explains"))
    if selection.group is not None:
        references.append((selection.group, "group"))
    references.extend((object_id, "exclude") for object_id in selection.exclude or ())
    for object_id, field_name in references:
        problem = _reference_problem(by_id, snapshot, object_id)
        if problem is None and field_name == "near" and by_id[object_id].geometry is None:
            problem = SceneRefusal.UNPLACED
        if problem is None and field_name == "group" and by_id[object_id].kind is not SceneObjectKind.GROUP:
            problem = SceneRefusal.INVALID_SELECTION
        if problem is not None:
            refused.append(SelectionRefusal(object_id, problem, field_name))
    if refused:
        # Filtres : aucun id archivé explicite, les deux listes coïncident.
        return SelectionResolution(SelectionMode.FILTER, refused=tuple(refused), refused_with_archived=tuple(refused))

    # Portées calculées sur la scène active entière, puis intersectées (§1.2).
    constellation: tuple[str, ...] | None = None
    if selection.constellation is not None:
        constellation = constellation_of(snapshot, selection.constellation.object_id, selection.constellation.depth)
    explainers: set[str] | None = None
    if selection.explains is not None:
        explainers = {relation.from_id for relation in snapshot.relations
                      if relation.kind is RelationKind.EXPLAINS and relation.to_id == selection.explains}
    members: set[str] | None = None
    if selection.group is not None:
        members = {relation.to_id for relation in snapshot.relations
                   if relation.kind is RelationKind.GROUPS and relation.from_id == selection.group}
    reference: SceneGeometry | None = None
    if selection.near is not None:
        reference = by_id[selection.near.object_id].geometry
    constellation_set = None if constellation is None else set(constellation)
    excluded = set(selection.exclude or ())
    category = None if selection.category is None else selection.category.casefold()

    kept: dict[str, float] = {}
    for item in snapshot.objects:
        if ((selection.kinds is not None and item.kind not in selection.kinds)
                or (selection.exec_states is not None and item.exec_state not in selection.exec_states)
                or (selection.origin is not None and item.origin is not selection.origin)
                or (selection.visibility is not None and item.visibility is not selection.visibility)
                or (category is not None and item.category.casefold() != category)
                or (selection.text is not None and not text_matches(item, selection.text))
                or (selection.work is not None and not work_matches(item, selection.work))
                or (explainers is not None and item.object_id not in explainers)
                or (members is not None and item.object_id not in members)
                or (constellation_set is not None and item.object_id not in constellation_set)
                or item.object_id in excluded):
            continue
        distance = 0.0
        if reference is not None:
            assert selection.near is not None
            if item.object_id == selection.near.object_id or item.geometry is None:
                continue
            if (item.visibility is Visibility.HIDDEN and not selection.include_hidden
                    and selection.visibility is None):
                # Règle de rendu : un objet masqué n'est pas dessiné (§1.1 `near`).
                continue
            distance = box_distance(reference, item.geometry)
            if distance > selection.near.radius:
                continue
        kept[item.object_id] = distance

    # Ordre canonique (§1.3) : `kept` suit déjà l'ordre de la scène.
    if reference is not None:
        # `sorted` est stable : à distance égale, l'ordre de la scène.
        matched = tuple(sorted(kept, key=kept.__getitem__))
    elif constellation is not None:
        matched = tuple(object_id for object_id in constellation if object_id in kept)
    else:
        matched = tuple(kept)
    skipped: tuple[SelectionSkip, ...] = ()
    if require_placed:
        skipped = tuple(SelectionSkip(object_id, SceneRefusal.UNPLACED) for object_id in matched
                        if by_id[object_id].geometry is None)
    return SelectionResolution(SelectionMode.FILTER, matched_ids=matched, skipped=skipped,
                               hidden_count=_hidden_count(by_id, matched))

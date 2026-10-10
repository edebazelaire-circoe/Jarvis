"""Presentation Studio : la comparaison de variantes (handoff jarvis-interactive-presentation-studio, Slice 19).

Un *ensemble de comparaison* (`CompareState`) nomme **2 ou 4** variantes vivantes d'une Presentation, au plus une paire en
focus (mode 50/50), un mode de navigation (`sync` ou `independent`), des liens de scenes poses a la main et la scene courante
de chaque variante. C'est de l'etat d'**interface** : il vit en memoire de Core (jamais dans un document de variante, jamais
dans l'historique d'annulation), et ne modifie aucune variante.

La *scene logique synchronisee* est une classe d'equivalence de scenes entre variantes :

- **identite** : une branche garde les `scene_id` de sa source, donc le meme `scene_id` dans deux variantes est la meme
  scene logique (la variante peut l'avoir modifiee, c'est ce qu'on compare) ;
- **lien manuel** : l'utilisateur apparie deux scenes d'ids differents quand les structures ont diverge. Un lien qui mettrait deux
  scenes d'une meme variante dans une classe est refuse (`presentation_studio_compare_mapping_conflict`).

Une scene sans equivalent dans une variante est `unmapped` pour elle : la navigation synchronisee ne la deplace pas (statut
`unmapped`, la scene courante reste), et l'interface propose le lien manuel (`suggestions` : scenes non appariees du meme prefab)
ou le mode `independent`. Pur : aucune E/S. Service : `jarvis/core/presentation_studio_compare.py`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from jarvis.domain.presentation_studio_checks import (
    PresentationStudioError, PresentationStudioErrorCode as C, SCENE_ID, _check_id, _check_int, _exact_keys, _fail,
)
from jarvis.domain.presentation_studio_variants import VARIANT_ID

COMPARE_SIZES = (2, 4)
MODES = ("sync", "independent")
STEPS = ("next", "previous", "first", "last")
#: Liens manuels d'un ensemble (la structure d'une presentation tient en 64 scenes par variante).
MAX_LINKS = 64
#: Pistes de rapprochement proposees par scene non appariee.
MAX_SUGGESTIONS = 4


@dataclass(frozen=True, slots=True)
class SceneRef:
    variant_id: str
    scene_id: str

    def to_dict(self) -> dict[str, str]:
        return {"variant_id": self.variant_id, "scene_id": self.scene_id}

    @staticmethod
    def parse(raw: object, where: str) -> SceneRef:
        data = _exact_keys(raw, where, {"variant_id", "scene_id"})
        _check_id(f"{where}.variant_id", data["variant_id"], VARIANT_ID)
        _check_id(f"{where}.scene_id", data["scene_id"], SCENE_ID)
        return SceneRef(data["variant_id"], data["scene_id"])


@dataclass(frozen=True, slots=True)
class SceneShape:
    scene_id: str
    title: str
    prefab_id: str
    prefab_version: int


@dataclass(frozen=True, slots=True)
class VariantShape:
    """Ce que la comparaison lit d'une variante : jamais son contenu, seulement la structure."""

    variant_id: str
    variant_number: int
    title: str
    revision: int
    active: bool
    scenes: tuple[SceneShape, ...]


@dataclass(frozen=True, slots=True)
class CompareState:
    presentation_id: str
    revision: int = 0
    variant_ids: tuple[str, ...] = ()
    pair: tuple[str, str] | None = None
    mode: str = "sync"
    links: tuple[tuple[SceneRef, SceneRef], ...] = ()
    anchors: Mapping[str, str | None] = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return bool(self.variant_ids)

    @property
    def layout(self) -> str:
        if self.pair is not None:
            return "focus"
        return {2: "two_up", 4: "four_up"}.get(len(self.variant_ids), "empty")

    @property
    def shown(self) -> tuple[str, ...]:
        """Les variantes montrees : la paire en focus (50/50) ou tout l'ensemble."""

        return self.pair if self.pair is not None else self.variant_ids


# ------------------------------------------------------------------ requetes

def parse_select(raw: object) -> dict[str, Any]:
    data = _exact_keys(raw, "compare select", {"variant_ids"}, frozenset({"pair", "mode", "expected_revision"}))
    ids = data["variant_ids"]
    if not isinstance(ids, list) or len(ids) not in COMPARE_SIZES:
        raise _fail("variant_ids must list exactly 2 or 4 variants to compare")
    for variant_id in ids:
        _check_id("variant_ids[]", variant_id, VARIANT_ID)
    if len(set(ids)) != len(ids):
        raise _fail("variant_ids names a variant twice")
    data["variant_ids"] = tuple(ids)
    data["pair"] = parse_pair(data.get("pair"), tuple(ids))
    _check_mode(data.get("mode", "sync"))
    _check_expected(data)
    return data


def parse_pair(raw: object, members: Sequence[str]) -> tuple[str, str] | None:
    if raw is None:
        return None
    if not isinstance(raw, list) or len(raw) != 2:
        raise _fail("pair must be null or a list of exactly 2 compared variants")
    for variant_id in raw:
        _check_id("pair[]", variant_id, VARIANT_ID)
    if raw[0] == raw[1]:
        raise _fail("pair names a variant twice")
    if any(v not in members for v in raw):
        raise _fail("pair must name variants of the comparison set")
    return (raw[0], raw[1])


def _check_mode(mode: object) -> None:
    if mode not in MODES:
        raise _fail(f"mode must be one of {', '.join(MODES)}")


def _check_expected(data: Mapping[str, Any]) -> None:
    if data.get("expected_revision") is not None:
        _check_int("expected_revision", data["expected_revision"], 0, 2**31 - 1)


def parse_body(raw: object, kind: str) -> dict[str, Any]:
    """Les corps des operations d'un ensemble deja choisi : `pair`, `mode`, `navigate`, `link`, `clear`."""

    if kind == "pair":
        data = _exact_keys(raw, "compare pair", {"pair"}, frozenset({"expected_revision"}))
        if data["pair"] is not None:
            parse_pair(data["pair"], data["pair"] if isinstance(data["pair"], list) else ())
    elif kind == "mode":
        data = _exact_keys(raw, "compare mode", {"mode"}, frozenset({"expected_revision"}))
        _check_mode(data["mode"])
    elif kind == "navigate":
        data = _exact_keys(raw, "compare navigate", {"variant_id"}, frozenset({"scene_id", "step", "expected_revision"}))
        _check_id("variant_id", data["variant_id"], VARIANT_ID)
        if (data.get("scene_id") is None) == (data.get("step") is None):
            raise _fail("navigate needs exactly one of scene_id or step")
        if data.get("scene_id") is not None:
            _check_id("scene_id", data["scene_id"], SCENE_ID)
        if data.get("step") is not None and data["step"] not in STEPS:
            raise _fail(f"step must be one of {', '.join(STEPS)}")
    elif kind == "link":
        data = _exact_keys(raw, "compare link", {"a", "b"}, frozenset({"expected_revision"}))
        data["a"], data["b"] = SceneRef.parse(data["a"], "a"), SceneRef.parse(data["b"], "b")
        if data["a"].variant_id == data["b"].variant_id:
            raise _fail("a link joins scenes of two different variants")
    elif kind == "clear":
        data = _exact_keys({} if raw is None else raw, "compare clear", set(), frozenset({"expected_revision"}))
    else:  # pragma: no cover - a programming error, never a request
        raise ValueError(kind)
    _check_expected(data)
    return data


# ------------------------------------------------------------------ equivalence

def _canonical(a: SceneRef, b: SceneRef) -> tuple[SceneRef, SceneRef]:
    return (a, b) if (a.variant_id, a.scene_id) <= (b.variant_id, b.scene_id) else (b, a)


class SceneClasses:
    """Les classes d'equivalence des scenes de l'ensemble : identite de `scene_id` puis liens manuels (union-find)."""

    def __init__(self, shapes: Sequence[VariantShape], links: Sequence[tuple[SceneRef, SceneRef]]) -> None:
        self._parent: dict[tuple[str, str], tuple[str, str]] = {}
        self._manual: set[tuple[str, str]] = set()
        first_with: dict[str, tuple[str, str]] = {}
        for shape in shapes:
            for scene in shape.scenes:
                node = (shape.variant_id, scene.scene_id)
                self._parent[node] = node
                if scene.scene_id in first_with:
                    self._union(first_with[scene.scene_id], node)
                else:
                    first_with[scene.scene_id] = node
        self.refused: list[tuple[SceneRef, SceneRef]] = []
        for a, b in links:
            na, nb = (a.variant_id, a.scene_id), (b.variant_id, b.scene_id)
            if na not in self._parent or nb not in self._parent or self._would_collide(na, nb):
                self.refused.append((a, b))  # stale (a scene or variant is gone) or now colliding: reported, never applied
                continue
            self._manual |= {na, nb}
            self._union(na, nb)

    def _find(self, node: tuple[str, str]) -> tuple[str, str]:
        while self._parent[node] != node:
            self._parent[node] = self._parent[self._parent[node]]
            node = self._parent[node]
        return node

    def _members(self, root: tuple[str, str]) -> list[tuple[str, str]]:
        return [n for n in self._parent if self._find(n) == root]

    def _would_collide(self, a: tuple[str, str], b: tuple[str, str]) -> bool:
        ra, rb = self._find(a), self._find(b)
        if ra == rb:
            return False
        variants = [v for v, _ in self._members(ra)]
        return any(v in variants for v, _ in self._members(rb))

    def would_collide(self, a: SceneRef, b: SceneRef) -> bool:
        na, nb = (a.variant_id, a.scene_id), (b.variant_id, b.scene_id)
        if na not in self._parent or nb not in self._parent:
            return True
        return self._would_collide(na, nb)

    def _union(self, a: tuple[str, str], b: tuple[str, str]) -> None:
        ra, rb = self._find(a), self._find(b)
        if ra != rb:
            self._parent[rb] = ra

    def class_of(self, variant_id: str, scene_id: str) -> tuple[str, str]:
        return self._find((variant_id, scene_id))

    def equivalents(self, variant_id: str, scene_id: str) -> dict[str, str]:
        """`variant_id -> scene_id` des scenes equivalentes dans les **autres** variantes de l'ensemble."""

        root = self.class_of(variant_id, scene_id)
        return {v: s for v, s in self._members(root) if v != variant_id}

    def mapping(self, variant_id: str, scene_id: str) -> str:
        """`identity`, `manual` ou `none` (aucune scene equivalente ailleurs)."""

        members = self._members(self.class_of(variant_id, scene_id))
        if len(members) < 2:
            return "none"
        return "manual" if any(m in self._manual for m in members) else "identity"


def pair_relation(a: VariantShape, b: VariantShape, classes: SceneClasses) -> dict[str, Any]:
    """Comment deux structures se rapportent : `identical` (memes classes dans le meme ordre), `reordered` (memes classes,
    autre ordre) ou `divergent` (des scenes sans equivalent de l'autre cote)."""

    in_b = {classes.class_of(b.variant_id, s.scene_id): s.scene_id for s in b.scenes}
    shared = [(s.scene_id, in_b[c]) for s in a.scenes if (c := classes.class_of(a.variant_id, s.scene_id)) in in_b]
    only_a = [s.scene_id for s in a.scenes if classes.class_of(a.variant_id, s.scene_id) not in in_b]
    mapped_b = {t for _, t in shared}
    only_b = [s.scene_id for s in b.scenes if s.scene_id not in mapped_b]
    order = [t for _, t in shared]
    b_order = [s.scene_id for s in b.scenes if s.scene_id in mapped_b]
    if only_a or only_b:
        relation = "divergent"
    elif order == b_order:
        relation = "identical"
    else:
        relation = "reordered"
    return {"a": a.variant_id, "b": b.variant_id, "relation": relation, "shared": len(shared), "only_a": len(only_a),
            "only_b": len(only_b), "order_preserved": order == b_order}


# ------------------------------------------------------------------ vue et transitions

def _rank(relations: Sequence[str]) -> str:
    for worst in ("divergent", "reordered"):
        if worst in relations:
            return worst
    return "identical"


def build_view(state: CompareState, shapes: Mapping[str, VariantShape], problems: Sequence[dict[str, str]] = ()) -> dict[str, Any]:
    """La reponse commune de toutes les operations : l'etat, les structures, les equivalences, la navigation courante."""

    present = [shapes[v] for v in state.variant_ids if v in shapes]
    classes = SceneClasses(present, state.links)
    unmapped: dict[str, list[str]] = {}
    variants: list[dict[str, Any]] = []
    for shape in present:
        rows = []
        lost: list[str] = []
        for index, scene in enumerate(shape.scenes):
            equivalents = classes.equivalents(shape.variant_id, scene.scene_id)
            mapping = classes.mapping(shape.variant_id, scene.scene_id)
            if mapping == "none":
                lost.append(scene.scene_id)
            rows.append({"scene_id": scene.scene_id, "index": index, "title": scene.title,
                         "prefab": {"id": scene.prefab_id, "version": scene.prefab_version}, "mapping": mapping,
                         "equivalents": equivalents, "suggestions": []})
        unmapped[shape.variant_id] = lost
        variants.append({"variant_id": shape.variant_id, "variant_number": shape.variant_number, "title": shape.title,
                         "revision": shape.revision, "active": shape.active, "scene_count": len(shape.scenes), "scenes": rows})
    _suggest(variants, unmapped)
    pairs = [pair_relation(a, b, classes) for i, a in enumerate(present) for b in present[i + 1:]]
    links = [{"a": a.to_dict(), "b": b.to_dict(), "stale": False} for a, b in state.links if (a, b) not in classes.refused]
    links += [{"a": a.to_dict(), "b": b.to_dict(), "stale": True} for a, b in classes.refused]
    anchors = {v: state.anchors.get(v) for v in state.variant_ids}
    return {"presentation_id": state.presentation_id, "revision": state.revision, "active": state.active,
            "variant_ids": list(state.variant_ids), "layout": state.layout, "pair": None if state.pair is None else list(state.pair),
            "shown": list(state.shown), "mode": state.mode, "variants": variants,
            "structure": {"relation": _rank([p["relation"] for p in pairs]) if pairs else "identical", "pairs": pairs},
            "unmapped": unmapped, "links": links, "anchors": anchors, "problems": list(problems)}


def _suggest(variants: list[dict[str, Any]], unmapped: Mapping[str, list[str]]) -> None:
    """Pour chaque scene sans equivalent nulle part : les scenes des autres variantes qui n'ont pas d'equivalent dans CETTE variante
    et qui ont le meme prefab (de quoi proposer un lien manuel). Bornees ; jamais appliquees d'office."""

    for variant in variants:
        for row in variant["scenes"]:
            if row["mapping"] != "none":
                continue
            found = [{"variant_id": other["variant_id"], "scene_id": candidate["scene_id"]}
                     for other in variants if other["variant_id"] != variant["variant_id"]
                     for candidate in other["scenes"]
                     if variant["variant_id"] not in candidate["equivalents"] and candidate["prefab"]["id"] == row["prefab"]["id"]]
            row["suggestions"] = found[:MAX_SUGGESTIONS]


def select(state: CompareState, request: Mapping[str, Any], shapes: Mapping[str, VariantShape]) -> CompareState:
    """Remplace la selection. Les liens entre variantes **encore choisies** survivent ; la scene courante de chacune est sa
    premiere scene (ou celle qu'elle avait)."""

    ids = request["variant_ids"]
    keep = tuple((a, b) for a, b in state.links if a.variant_id in ids and b.variant_id in ids)
    anchors = {v: (state.anchors.get(v) if state.anchors.get(v) in {s.scene_id for s in shapes[v].scenes}
                   else (shapes[v].scenes[0].scene_id if shapes[v].scenes else None)) for v in ids}
    return replace(state, revision=state.revision + 1, variant_ids=ids, pair=request.get("pair"),
                   mode=request.get("mode", "sync"), links=keep, anchors=anchors)


def set_pair(state: CompareState, pair: list[str] | None) -> CompareState:
    if not state.active:
        raise PresentationStudioError(C.INVALID_PRESENTATION, "no comparison is open: select 2 or 4 variants first")
    if pair is not None and any(v not in state.variant_ids for v in pair):
        raise _fail("pair must name variants of the comparison set")
    return replace(state, revision=state.revision + 1, pair=None if pair is None else (pair[0], pair[1]))


def set_mode(state: CompareState, mode: str) -> CompareState:
    if not state.active:
        raise PresentationStudioError(C.INVALID_PRESENTATION, "no comparison is open: select 2 or 4 variants first")
    return replace(state, revision=state.revision + 1, mode=mode)


def add_link(state: CompareState, a: SceneRef, b: SceneRef, shapes: Mapping[str, VariantShape]) -> CompareState:
    """Pose un lien manuel. Refus type si une variante n'est pas dans l'ensemble, si une scene n'existe pas, si le lien mettrait
    deux scenes d'une meme variante dans la meme classe (`compare_mapping_conflict`) ou s'il y a trop de liens."""

    if not state.active:
        raise PresentationStudioError(C.INVALID_PRESENTATION, "no comparison is open: select 2 or 4 variants first")
    for ref in (a, b):
        if ref.variant_id not in state.variant_ids:
            raise _fail(f"{ref.variant_id} is not in the comparison set")
        if ref.scene_id not in {s.scene_id for s in shapes[ref.variant_id].scenes}:
            raise PresentationStudioError(C.UNKNOWN_SCENE, f"{ref.scene_id} is not a scene of {ref.variant_id}")
    link = _canonical(a, b)
    if link in {_canonical(x, y) for x, y in state.links}:
        return state
    if len(state.links) >= MAX_LINKS:
        raise PresentationStudioError(C.LIMIT_REACHED, f"a comparison holds at most {MAX_LINKS} manual links")
    classes = SceneClasses([shapes[v] for v in state.variant_ids], state.links)
    if classes.would_collide(a, b):
        raise PresentationStudioError(
            C.COMPARE_MAPPING_CONFLICT,
            f"linking {a.scene_id} and {b.scene_id} would put two scenes of one variant in the same logical scene: "
            "remove the link that already joins one of them, or link other scenes")
    return replace(state, revision=state.revision + 1, links=(*state.links, link))


def remove_link(state: CompareState, a: SceneRef, b: SceneRef) -> CompareState:
    target = _canonical(a, b)
    kept = tuple(link for link in state.links if _canonical(*link) != target)
    if len(kept) == len(state.links):
        raise PresentationStudioError(C.UNKNOWN_SCENE, "no such manual link in this comparison")
    return replace(state, revision=state.revision + 1, links=kept)


def navigate(state: CompareState, shapes: Mapping[str, VariantShape], data: Mapping[str, Any]
             ) -> tuple[CompareState, dict[str, Any]]:
    """Deplace la scene courante d'une variante et, en mode `sync`, celle des autres variantes **ou la scene equivalente existe**.
    Rend aussi, par variante, `{scene_id, status}` : `origin`, `synced`, `unmapped` (pas d'equivalent : la scene courante reste)
    ou `held` (mode independent)."""

    if not state.active:
        raise PresentationStudioError(C.INVALID_PRESENTATION, "no comparison is open: select 2 or 4 variants first")
    variant_id = data["variant_id"]
    if variant_id not in state.variant_ids:
        raise _fail(f"{variant_id} is not in the comparison set")
    scenes = [s.scene_id for s in shapes[variant_id].scenes]
    if not scenes:
        raise PresentationStudioError(C.UNKNOWN_SCENE, f"{variant_id} has no scene to show")
    scene_id = data.get("scene_id")
    if scene_id is None:
        current = state.anchors.get(variant_id)
        index = scenes.index(current) if current in scenes else 0
        step = data["step"]
        scene_id = {"first": scenes[0], "last": scenes[-1], "next": scenes[min(index + 1, len(scenes) - 1)],
                    "previous": scenes[max(index - 1, 0)]}[step]
    elif scene_id not in scenes:
        raise PresentationStudioError(C.UNKNOWN_SCENE, f"{scene_id} is not a scene of {variant_id}")
    anchors = dict(state.anchors)
    anchors[variant_id] = scene_id
    results: dict[str, dict[str, Any]] = {variant_id: {"scene_id": scene_id, "status": "origin"}}
    classes = SceneClasses([shapes[v] for v in state.variant_ids], state.links)
    equivalents = classes.equivalents(variant_id, scene_id)
    for other in state.variant_ids:
        if other == variant_id:
            continue
        if state.mode == "independent":
            results[other] = {"scene_id": anchors.get(other), "status": "held"}
        elif other in equivalents:
            anchors[other] = equivalents[other]
            results[other] = {"scene_id": equivalents[other], "status": "synced"}
        else:
            results[other] = {"scene_id": anchors.get(other), "status": "unmapped"}
    return replace(state, revision=state.revision + 1, anchors=anchors), {"origin": {"variant_id": variant_id, "scene_id": scene_id},
                                                                          "results": results}

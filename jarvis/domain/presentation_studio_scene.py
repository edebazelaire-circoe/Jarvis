"""Presentation Studio : la scène logique et ses contrôles déclarés (handoff jarvis-interactive-presentation-studio, Slice 04).

Une *scène logique* (`StudioScene`) n'est **pas** un objet de la scène globale :
c'est une entrée de la variante qui épingle un prefab exact `(id, version)`,
porte les valeurs `props`/`data` de cette instance et déclare ce qui s'y édite.
Un seul objet `window` « stage » par Presentation (`docs/07-integration-map.md`
§4.5) est patché avec `payload()` pour l'afficher ; son identifiant est un
handle d'exécution (Slice 12), il n'entre jamais ici (`RUNTIME_KEYS`).

Ce que ce module ajoute à la Slice 02 (contrat : `docs/presentation-studio.md`
› *Scene and control contract*) :

- `StudioControl` : un contrôle **curé** lié à un chemin `props.<clé>` /
  `data.<clé>` du manifeste épinglé. Son type de widget vient du `InputSchema` du
  manifeste (jamais redéclaré) ; l'étude ajoute seulement id sémantique stable,
  libellé, groupe, sens, défaut et bornes plus **étroites** que le manifeste.
  Ce n'est jamais un export CSS : seuls les chemins que le prefab déclare existent.
- `ScoreAnchor` : point d'accroche nommé pour la partition (Slice 10), éventuellement
  lié à un contrôle ; ensemble clos par scène.
- `ScenePreview` : légende et texte alternatif de la vignette.
- `check_scene` / `describe_scene` : validation et introspection **pures** contre
  un `PrefabManifest` déjà obtenu (la validation des valeurs de prefab reste
  l'affaire de `PrefabService`, ce module ne la recopie pas : il n'ajoute que les
  bornes curées).

Pur : aucune E/S. Le service Core est `jarvis.core.presentation_studio_scene_catalog`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
import json
import math
import re
from typing import Any

from jarvis.domain.prefab import (
    DEFAULT_STRING_LENGTH, DEFAULT_TEXT_LENGTH, MAX_ARRAY_ITEMS, MAX_ENUM_VALUES, MAX_LABEL_CHARS, MAX_SCHEMA_DEPTH,
    InputSchema, InputType, PrefabManifest, PrefabRef, PrefabDefinitionError, canonical_json, validate_value,
)
from jarvis.domain.presentation_studio_checks import (
    MAX_TITLE, SCENE_ID, _check_id, _exact_keys, _fail, clip,
)
from jarvis.domain.presentation_studio_scene_variants import SceneVariantSet
from jarvis.domain.scene import MAX_PAYLOAD_BYTES, ScenePayload, ScenePrefabRef

CONTENT_KEYS = ("prefab", "props", "data", "controls", "anchors")

#: Bornes (toute collection est bornée).
MAX_CONTROLS = 32
MAX_ANCHORS = 16
#: Position d'une ancre dans la ligne de temps d'une scène Remotion (`ScoreAnchor.at_ms`) : 108 000 s, le plafond d'une composition à 1 image/s.
MAX_ANCHOR_AT_MS = 108_000_000
MAX_SECTION_CHARS = 40
MAX_MEANING_CHARS = 160
MAX_CAPTION_CHARS = 120
MAX_ALT_CHARS = 200
MAX_DEFAULT_CHARS = 2000
MAX_CHECK_ERRORS = 20
#: Borne du compteur de révisions de source d'une scène (un rechargement par seconde ne l'atteint pas en 60 ans).
MAX_SOURCE_REVISION = 2**31 - 1

#: Identifiant sémantique d'un contrôle ou d'une ancre : `[a-z][a-z0-9_]{0,39}` (`action_id` des noms canoniques).
SLUG = re.compile(r"[a-z][a-z0-9_]{0,39}\Z")
#: `props.<clé>[.<clé>...]` ou `data...` : des noms de propriétés d'objet, jamais un index ni un sélecteur.
CONTROL_PATH = re.compile(r"(?:props|data)(?:\.[A-Za-z_][A-Za-z0-9_]{0,63}){1,%d}\Z" % (MAX_SCHEMA_DEPTH - 1))
_PATH_ROOTS = ("props", "data")


class ControlGroup(StrEnum):
    """Famille curée d'un contrôle (la même pour la voix et pour l'inspecteur)."""

    CONTENT = "content"
    VISUAL = "visual"
    LAYOUT = "layout"
    MOTION = "motion"


class ControlWidget(StrEnum):
    """Type de widget **dérivé** du type d'entrée du manifeste (`widget_for`)."""

    TEXT_LINE = "text_line"
    TEXT_AREA = "text_area"
    NUMBER = "number"
    SLIDER = "slider"
    TOGGLE = "toggle"
    COLOR = "color"
    CHOICE = "choice"
    URL = "url"
    LIST = "list"


def _line(name: str, value: object, limit: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise _fail(f"{name} must be a string")
    if not value:
        if allow_empty:
            return value
        raise _fail(f"{name} must not be empty")
    if value != value.strip() or not value.isprintable() or len(value) > limit:
        raise _fail(f"{name} must be one printable line of at most {limit} characters, without surrounding spaces")
    return value


def _is_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


# ------------------------------------------------------------------ bornes et contrôles

@dataclass(frozen=True, slots=True)
class ControlBounds:
    """Bornes curées, toujours **dans** celles du manifeste (`bounds_problem`). Vide : celles du manifeste."""

    min: int | float | None = None
    max: int | float | None = None
    max_length: int | None = None
    max_items: int | None = None
    choices: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("min", "max"):
            value = getattr(self, name)
            if value is not None and not _is_number(value):
                raise _fail(f"bounds.{name} must be a finite number")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise _fail("bounds.min is above bounds.max")
        for name in ("max_length", "max_items"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or not 1 <= value <= 100_000):
                raise _fail(f"bounds.{name} must be an integer in 1..100000")
        if not isinstance(self.choices, (list, tuple)):
            raise _fail("bounds.choices must be a list")
        choices = tuple(self.choices)
        if len(choices) > MAX_ENUM_VALUES or len(set(choices)) != len(choices) \
                or not all(isinstance(item, str) and item for item in choices):
            raise _fail(f"bounds.choices must hold at most {MAX_ENUM_VALUES} distinct non-empty strings")
        object.__setattr__(self, "choices", choices)

    def is_empty(self) -> bool:
        return self.min is None and self.max is None and self.max_length is None and self.max_items is None \
            and not self.choices

    def to_dict(self) -> dict[str, Any]:
        wire: dict[str, Any] = {}
        for name in ("min", "max", "max_length", "max_items"):
            if getattr(self, name) is not None:
                wire[name] = getattr(self, name)
        if self.choices:
            wire["choices"] = list(self.choices)
        return wire

    @classmethod
    def from_dict(cls, raw: object, where: str = "bounds") -> ControlBounds:
        data = _exact_keys(raw, where, set(), frozenset({"min", "max", "max_length", "max_items", "choices"}))
        return cls(**data)


@dataclass(frozen=True, slots=True)
class StudioControl:
    """Un contrôle déclaré : id sémantique stable, chemin du manifeste, libellé, groupe, sens, défaut, bornes."""

    control_id: str
    path: str
    label: str
    group: ControlGroup
    #: Une phrase : à quoi sert ce réglage, dans les mots de l'auteur (pour l'agent comme pour l'inspecteur).
    meaning: str = ""
    #: Défaut curé (`None` : celui du manifeste). Validé contre le schéma et les bornes (`check_scene`).
    default: Any = None
    bounds: ControlBounds = field(default_factory=ControlBounds)

    def __post_init__(self) -> None:
        if not isinstance(self.control_id, str) or not SLUG.fullmatch(self.control_id):
            raise _fail("control_id must match [a-z][a-z0-9_]{0,39}")
        if not isinstance(self.path, str) or not CONTROL_PATH.fullmatch(self.path):
            raise _fail(f"control {self.control_id}: path must be props.<name> or data.<name> (object properties only)")
        _line("label", self.label, MAX_LABEL_CHARS)
        try:
            object.__setattr__(self, "group", ControlGroup(self.group))
        except ValueError:
            raise _fail(f"control {self.control_id}: group must be one of "
                        f"{', '.join(g.value for g in ControlGroup)}") from None
        _line("meaning", self.meaning, MAX_MEANING_CHARS, allow_empty=True)
        if not isinstance(self.bounds, ControlBounds):
            raise _fail("bounds must be ControlBounds")
        if self.default is not None:
            try:
                text = canonical_json(self.default)
            except (ValueError, TypeError):
                raise _fail(f"control {self.control_id}: default must be pure JSON") from None
            if len(text) > MAX_DEFAULT_CHARS:
                raise _fail(f"control {self.control_id}: default exceeds {MAX_DEFAULT_CHARS} characters")

    @property
    def root(self) -> str:
        return self.path.split(".", 1)[0]

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(self.path.split(".")[1:])

    def to_dict(self) -> dict[str, Any]:
        wire: dict[str, Any] = {"control_id": self.control_id, "path": self.path, "label": self.label,
                                "group": self.group.value, "meaning": self.meaning}
        if self.default is not None:
            wire["default"] = json.loads(canonical_json(self.default))
        if not self.bounds.is_empty():
            wire["bounds"] = self.bounds.to_dict()
        return wire

    @classmethod
    def from_dict(cls, raw: object, where: str = "control") -> StudioControl:
        data = _exact_keys(raw, where, {"control_id", "path", "label", "group"},
                           frozenset({"meaning", "default", "bounds"}))
        bounds = ControlBounds.from_dict(data["bounds"], f"{where}.bounds") if "bounds" in data else ControlBounds()
        return cls(data["control_id"], data["path"], data["label"], data["group"], data.get("meaning", ""),
                   data.get("default"), bounds)


@dataclass(frozen=True, slots=True)
class ScoreAnchor:
    """Point d'accroche nommé pour la partition (Slice 10) : l'ensemble clos des actions d'une scène.

    `control_id` : le contrôle que l'ancre pilote (une ancre sans contrôle est un simple repère de
    synchronisation). Aucune ancre ne porte d'outil, de texte libre ni de commande : une cue ne peut
    nommer qu'un `anchor_id` écrit à l'avance (R5).

    `at_ms` (handoff Remotion, Slice 12) : où l'ancre tombe dans la **ligne de temps** d'une scène Remotion, en millisecondes depuis le
    début de la composition (`None` : répartie à parts égales, voir `remotion_timeline`). Écrit seulement quand il est posé : une ancre
    d'avant garde exactement sa forme (octet pour octet). Les ms, pas les images : la position survit à un changement de cadence ou
    de durée de la scène.
    """

    anchor_id: str
    label: str
    control_id: str | None = None
    at_ms: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.anchor_id, str) or not SLUG.fullmatch(self.anchor_id):
            raise _fail("anchor_id must match [a-z][a-z0-9_]{0,39}")
        _line("label", self.label, MAX_LABEL_CHARS)
        if self.control_id is not None and (not isinstance(self.control_id, str) or not SLUG.fullmatch(self.control_id)):
            raise _fail(f"anchor {self.anchor_id}: control_id must match [a-z][a-z0-9_]{{0,39}}")
        if self.at_ms is not None and (type(self.at_ms) is not int or not 0 <= self.at_ms <= MAX_ANCHOR_AT_MS):
            raise _fail(f"anchor {self.anchor_id}: at_ms must be an integer 0..{MAX_ANCHOR_AT_MS}")

    def to_dict(self) -> dict[str, Any]:
        wire: dict[str, Any] = {"anchor_id": self.anchor_id, "label": self.label, "control_id": self.control_id}
        if self.at_ms is not None:
            wire["at_ms"] = self.at_ms
        return wire

    @classmethod
    def from_dict(cls, raw: object, where: str = "anchor") -> ScoreAnchor:
        data = _exact_keys(raw, where, {"anchor_id", "label"}, frozenset({"control_id", "at_ms"}))
        return cls(data["anchor_id"], data["label"], data.get("control_id"), data.get("at_ms"))


@dataclass(frozen=True, slots=True)
class ScenePreview:
    """Métadonnées de vignette : légende et texte alternatif (jamais une image : une référence viendra de la Slice 07)."""

    caption: str = ""
    alt: str = ""

    def __post_init__(self) -> None:
        _line("preview.caption", self.caption, MAX_CAPTION_CHARS, allow_empty=True)
        _line("preview.alt", self.alt, MAX_ALT_CHARS, allow_empty=True)

    def to_dict(self) -> dict[str, Any]:
        return {"caption": self.caption, "alt": self.alt}

    @classmethod
    def from_dict(cls, raw: object, where: str = "preview") -> ScenePreview:
        data = _exact_keys(raw, where, set(), frozenset({"caption", "alt"}))
        return cls(data.get("caption", ""), data.get("alt", ""))


# ------------------------------------------------------------------ la scène

def payload_bytes(payload: ScenePayload) -> int:
    """Taille compacte UTF-8 de la charge, comme `ScenePayload.__post_init__` la compte contre `MAX_PAYLOAD_BYTES`."""

    return len(json.dumps(payload.to_payload(), ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _tuple_of(kind: type, value: object, name: str, limit: int) -> tuple[Any, ...]:
    if not isinstance(value, (list, tuple)):
        raise _fail(f"{name} must be a list")
    if len(value) > limit:
        raise _fail(f"{name} exceed {limit}")
    if not all(isinstance(item, kind) for item in value):
        raise _fail(f"{name} must hold {kind.__name__} values")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class StudioScene:
    """Scène logique d'une variante : identité, pin exact, valeurs d'instance, contrôles, ancres, vignette.

    L'ordre est la position dans `PresentationVariant.scenes`. `props`/`data` sont les valeurs du bloc
    d'instance (`ScenePrefabRef`) ; leur conformité au manifeste est vérifiée par `PrefabService`
    (existence de la version, schéma), les bornes curées par `check_scene`. La charge affichable
    (`payload()`) ne peut pas dépasser `MAX_PAYLOAD_BYTES` : une scène qui ne tiendrait pas dans l'objet
    `window` du stage est refusée à la construction, pas à l'affichage.
    """

    scene_id: str
    prefab: PrefabRef
    title: str = ""
    section: str = ""
    props: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)
    controls: tuple[StudioControl, ...] = ()
    anchors: tuple[ScoreAnchor, ...] = ()
    preview: ScenePreview = field(default_factory=ScenePreview)
    #: Slice 06 : compteur **monotone** des changements de pin par rechargement à chaud (édition de source, retour
    #: arrière). Jamais décroissant, jamais écrit par un client : `PresentationStudioService` le tient.
    source_revision: int = 0
    #: Slice 06 : le pin **valide** auquel revenir tant que le pin courant n'a pas été vu monté (`None` : le pin
    #: courant est confirmé). Écrit avec le changement de pin, effacé à la confirmation : un arrêt entre les deux
    #: laisse un état cohérent et retrouvable (`PresentationStudioReloadService.recover`).
    last_valid_pin: PrefabRef | None = None
    #: Slice 17 : les variantes locales de cette scène (`None` : aucune, la clé n'existe pas dans le document). Les champs
    #: ci-dessus sont toujours le contenu de la variante locale choisie ; l'ensemble ne range que les autres.
    scene_variants: SceneVariantSet | None = None

    def __post_init__(self) -> None:
        _check_id("scene_id", self.scene_id, SCENE_ID)
        if type(self.source_revision) is not int or not 0 <= self.source_revision <= MAX_SOURCE_REVISION:
            raise _fail(f"scene {self.scene_id}: source_revision must be an integer in 0..{MAX_SOURCE_REVISION}")
        if self.last_valid_pin is not None and (not isinstance(self.last_valid_pin, PrefabRef)
                                                or self.last_valid_pin == self.prefab):
            raise _fail(f"scene {self.scene_id}: last_valid_pin must be another PrefabRef than the current pin")
        if not isinstance(self.prefab, PrefabRef):
            raise _fail("scene prefab must be a PrefabRef")
        _line("title", self.title, MAX_TITLE, allow_empty=True)
        _line("section", self.section, MAX_SECTION_CHARS, allow_empty=True)
        if not isinstance(self.preview, ScenePreview):
            raise _fail("preview must be ScenePreview")
        controls = _tuple_of(StudioControl, self.controls, "controls", MAX_CONTROLS)
        anchors = _tuple_of(ScoreAnchor, self.anchors, "anchors", MAX_ANCHORS)
        for label, values in (("control_id", [c.control_id for c in controls]), ("control path", [c.path for c in controls]),
                              ("anchor_id", [a.anchor_id for a in anchors])):
            if len(set(values)) != len(values):
                raise _fail(f"scene {self.scene_id}: the same {label} appears twice")
        ids = {c.control_id for c in controls}
        for anchor in anchors:
            if anchor.control_id is not None and anchor.control_id not in ids:
                raise _fail(f"anchor {anchor.anchor_id} drives {anchor.control_id}, which this scene does not declare")
        object.__setattr__(self, "controls", controls)
        object.__setattr__(self, "anchors", anchors)
        try:
            block = ScenePrefabRef(self.prefab.prefab_id, self.prefab.version, self.props, self.data)
            ScenePayload(title=self.title, prefab=block)  # the same 16 KiB cap the global scene enforces
        except (TypeError, ValueError) as exc:
            raise _fail(f"scene {self.scene_id}: {exc}") from None
        object.__setattr__(self, "props", dict(block.props))  # private copies: nothing aliases the caller's dicts
        object.__setattr__(self, "data", dict(block.data))
        if self.scene_variants is not None:
            if not isinstance(self.scene_variants, SceneVariantSet):
                raise _fail("scene_variants must be a SceneVariantSet")
            for content in self.scene_variants.contents():  # each stored alternative is a scene in its own right (16 KiB cap included)
                self.content_scene(content)

    def instance(self) -> ScenePrefabRef:
        """Le bloc d'instance exact `(id, version, props, data)` que le stage affiche."""

        return ScenePrefabRef(self.prefab.prefab_id, self.prefab.version, self.props, self.data)

    def payload(self) -> ScenePayload:
        """La charge de l'unique objet `window` du stage (`update_object(prefab=...)`) : le remontage a lieu au changement de version."""

        return ScenePayload(title=self.title, prefab=self.instance())

    def budget(self) -> dict[str, int]:
        """`{bytes, limit, remaining}` contre le plafond de charge de la scène globale."""

        used = payload_bytes(self.payload())
        return {"bytes": used, "limit": MAX_PAYLOAD_BYTES, "remaining": MAX_PAYLOAD_BYTES - used}

    def control(self, control_id: str) -> StudioControl | None:
        return next((c for c in self.controls if c.control_id == control_id), None)

    def to_dict(self) -> dict[str, Any]:
        block = self.instance().to_payload()
        wire = {"scene_id": self.scene_id, "prefab": self.prefab.to_dict(), "title": self.title,
                "section": self.section, "props": block["props"], "data": block["data"],
                "controls": [c.to_dict() for c in self.controls], "anchors": [a.to_dict() for a in self.anchors],
                "preview": self.preview.to_dict(), "source_revision": self.source_revision,
                "last_valid_pin": None if self.last_valid_pin is None else self.last_valid_pin.to_dict()}
        if self.scene_variants is not None:
            wire["scene_variants"] = self.scene_variants.to_dict()
        return wire

    # -- Slice 17 : le contenu d'une variante locale

    def live_content(self) -> dict[str, Any]:
        """Le contenu de la scène (ce qu'une variante locale remplace) : pin, valeurs, contrôles, ancres. Forme canonique."""

        wire = self.to_dict()
        return {key: wire[key] for key in CONTENT_KEYS}

    def content_scene(self, content: Mapping[str, Any]) -> StudioScene:
        """La scène que ce contenu donnerait (même identité, titre, section et vignette), **sans** ensemble. Valide le contenu
        comme une scène : pin bien formé, contrôles, plafond de charge de 16 Kio."""

        return StudioScene.from_dict({"scene_id": self.scene_id, "title": self.title, "section": self.section,
                                      "preview": self.preview.to_dict(), **content}, f"scene {self.scene_id} variant content")

    def with_content(self, content: Mapping[str, Any], variants: SceneVariantSet | None) -> StudioScene:
        """Cette scène avec `content` pour contenu vivant et `variants` pour ensemble."""

        return replace(self.content_scene(content), source_revision=self.source_revision,
                       last_valid_pin=self.last_valid_pin, scene_variants=variants)

    def held_pins(self) -> frozenset[tuple[str, int]]:
        """Les `(prefab_id, version)` que la scène tient : le sien et celui de chaque variante locale rangée (source de pins)."""

        pins = {(self.prefab.prefab_id, self.prefab.version)}
        if self.scene_variants is not None:
            for content in self.scene_variants.contents():
                pins.add((content["prefab"]["id"], content["prefab"]["version"]))
        return frozenset(pins)

    @classmethod
    def from_dict(cls, raw: object, where: str = "scene") -> StudioScene:
        """Le corps d'une scène. `scene_id` et `prefab` suffisent (un pin nu, forme de la v1) ; le reste a ses défauts."""

        data = _exact_keys(raw, where, {"scene_id", "prefab"},
                           frozenset({"title", "section", "props", "data", "controls", "anchors", "preview",
                                         "source_revision", "last_valid_pin", "scene_variants"}))
        try:
            prefab = PrefabRef.from_dict(data["prefab"], where=f"{where}.prefab")
        except PrefabDefinitionError as exc:
            raise _fail(f"{where}: {exc}") from None
        controls, anchors = data.get("controls", []), data.get("anchors", [])
        if not isinstance(controls, list) or not isinstance(anchors, list):
            raise _fail(f"{where}: controls and anchors must be lists")
        if len(controls) > MAX_CONTROLS or len(anchors) > MAX_ANCHORS:
            raise _fail(f"{where}: at most {MAX_CONTROLS} controls and {MAX_ANCHORS} anchors")
        for name in ("props", "data"):
            if not isinstance(data.get(name, {}), dict):
                raise _fail(f"{where}.{name} must be an object")
        last_valid = data.get("last_valid_pin")
        if last_valid is not None:
            try:
                last_valid = PrefabRef.from_dict(last_valid, where=f"{where}.last_valid_pin")
            except PrefabDefinitionError as exc:
                raise _fail(f"{where}: {exc}") from None
        return cls(data["scene_id"], prefab, data.get("title", ""), data.get("section", ""),
                   data.get("props", {}), data.get("data", {}),
                   tuple(StudioControl.from_dict(c, f"{where}.controls[{i}]") for i, c in enumerate(controls)),
                   tuple(ScoreAnchor.from_dict(a, f"{where}.anchors[{i}]") for i, a in enumerate(anchors)),
                   ScenePreview.from_dict(data["preview"], f"{where}.preview") if "preview" in data else ScenePreview(),
                   data.get("source_revision", 0), last_valid,
                   SceneVariantSet.from_dict(data["scene_variants"], f"{where}.scene_variants")
                   if "scene_variants" in data else None)


def upgrade_scene_v1(scene: Mapping[str, Any]) -> dict[str, Any]:
    """Scène v1 `{scene_id, prefab}` -> v2 : mêmes clés, plus les défauts de tout ce que la Slice 04 ajoute."""

    return {**StudioScene.from_dict(scene).to_dict()} if isinstance(scene, dict) else dict(scene)


def upgrade_scene_v2(scene: Mapping[str, Any]) -> dict[str, Any]:
    """Scène v2 -> v3 (Slice 06) : une scène jamais rechargée à chaud est à `source_revision` 0 sans pin de repli.
    Rien de ce que disait la v2 n'est réinterprété."""

    return {**scene, "source_revision": 0, "last_valid_pin": None} if isinstance(scene, dict) else dict(scene)


# ------------------------------------------------------------------ manifeste : widgets, bornes, validation

def node_of(manifest: PrefabManifest, control: StudioControl) -> InputSchema | None:
    root = manifest.props if control.root == "props" else manifest.data
    return root.at(control.keys)


def widget_for(node: InputSchema, bounds: ControlBounds | None = None) -> ControlWidget:
    """Le widget d'un nœud de schéma ; un nombre borné des deux côtés (par le manifeste ou par la curation) est un curseur."""

    bounds = bounds or ControlBounds()
    kind = node.type
    if kind in (InputType.NUMBER, InputType.INTEGER):
        lo = bounds.min if bounds.min is not None else node.min
        hi = bounds.max if bounds.max is not None else node.max
        return ControlWidget.SLIDER if lo is not None and hi is not None else ControlWidget.NUMBER
    return {InputType.STRING: ControlWidget.TEXT_LINE, InputType.TEXT: ControlWidget.TEXT_AREA,
            InputType.BOOLEAN: ControlWidget.TOGGLE, InputType.COLOR: ControlWidget.COLOR,
            InputType.ENUM: ControlWidget.CHOICE, InputType.URL: ControlWidget.URL,
            InputType.ARRAY: ControlWidget.LIST}[kind]


def effective_bounds(node: InputSchema, bounds: ControlBounds) -> dict[str, Any]:
    """Ce que l'inspecteur et l'agent doivent respecter : l'intersection du manifeste et de la curation."""

    kind, wire = node.type, {}
    if kind in (InputType.NUMBER, InputType.INTEGER):
        lows = [v for v in (node.min, bounds.min) if v is not None]
        highs = [v for v in (node.max, bounds.max) if v is not None]
        if lows:
            wire["min"] = max(lows)
        if highs:
            wire["max"] = min(highs)
    elif kind in (InputType.STRING, InputType.TEXT):
        base = node.max_length or (DEFAULT_STRING_LENGTH if kind is InputType.STRING else DEFAULT_TEXT_LENGTH)
        wire["max_length"] = min(base, bounds.max_length) if bounds.max_length else base
    elif kind is InputType.ENUM:
        wire["choices"] = list(bounds.choices or node.values)
    elif kind is InputType.ARRAY:
        base = node.max_items if node.max_items is not None else MAX_ARRAY_ITEMS
        wire["max_items"] = min(base, bounds.max_items) if bounds.max_items else base
    return wire


def bounds_problem(node: InputSchema, bounds: ControlBounds) -> str | None:
    """Les bornes curées sont-elles permises pour ce nœud et contenues dans celles du manifeste ?"""

    kind = node.type
    if kind is InputType.OBJECT:
        return "binds an object, not a value: bind one of its properties"
    allowed = {"min", "max"} if kind in (InputType.NUMBER, InputType.INTEGER) else \
        {"max_length"} if kind in (InputType.STRING, InputType.TEXT) else \
        {"choices"} if kind is InputType.ENUM else {"max_items"} if kind is InputType.ARRAY else set()
    given = set(bounds.to_dict())
    if given - allowed:
        return f"a {kind.value} accepts {sorted(allowed) or 'no curated bounds'}, not {sorted(given - allowed)}"
    if kind in (InputType.NUMBER, InputType.INTEGER):
        for name, value in (("min", bounds.min), ("max", bounds.max)):
            if value is None:
                continue
            if kind is InputType.INTEGER and type(value) is not int:
                return f"bounds.{name} must be an integer"
            if node.min is not None and value < node.min or node.max is not None and value > node.max:
                return f"bounds.{name} {value} is outside the manifest range [{node.min}, {node.max}]"
    elif kind in (InputType.STRING, InputType.TEXT) and bounds.max_length is not None:
        cap = node.max_length or (DEFAULT_STRING_LENGTH if kind is InputType.STRING else DEFAULT_TEXT_LENGTH)
        if bounds.max_length > cap:
            return f"bounds.max_length {bounds.max_length} is above the manifest limit {cap}"
    elif kind is InputType.ENUM and bounds.choices:
        outside = [item for item in bounds.choices if item not in node.values]
        if outside:
            return f"bounds.choices {outside[:3]} are not values of the manifest enum"
    elif kind is InputType.ARRAY and bounds.max_items is not None:
        cap = node.max_items if node.max_items is not None else MAX_ARRAY_ITEMS
        if not node.min_items <= bounds.max_items <= cap:
            return f"bounds.max_items {bounds.max_items} must be within [{node.min_items}, {cap}]"
    return None


def value_problem(node: InputSchema, bounds: ControlBounds, value: object, path: str) -> str | None:
    """Une valeur est-elle valide pour le manifeste **et** dans les bornes curées ? (`None` : oui)"""

    _, errors = validate_value(node, value, path)
    if errors:
        return errors[0]
    if node.type in (InputType.NUMBER, InputType.INTEGER):
        if bounds.min is not None and value < bounds.min:  # type: ignore[operator]
            return f"{path}: must be at least {bounds.min}"
        if bounds.max is not None and value > bounds.max:  # type: ignore[operator]
            return f"{path}: must be at most {bounds.max}"
    elif node.type in (InputType.STRING, InputType.TEXT) and bounds.max_length is not None \
            and len(value) > bounds.max_length:  # type: ignore[arg-type]
        return f"{path}: exceeds {bounds.max_length} characters"
    elif node.type is InputType.ENUM and bounds.choices and value not in bounds.choices:
        return f"{path}: must be one of {list(bounds.choices)[:8]}"
    elif node.type is InputType.ARRAY and bounds.max_items is not None and len(value) > bounds.max_items:  # type: ignore[arg-type]
        return f"{path}: holds {len(value)} items, at most {bounds.max_items}"  # type: ignore[arg-type]
    return None


def value_at(scene: StudioScene, control: StudioControl) -> tuple[bool, Any]:
    """`(présent, valeur)` du chemin du contrôle dans les valeurs de la scène."""

    node: Any = scene.props if control.root == "props" else scene.data
    for key in control.keys:
        if not isinstance(node, dict) or key not in node:
            return False, None
        node = node[key]
    return True, node


def check_scene(scene: StudioScene, manifest: PrefabManifest) -> list[str]:
    """Contrôles et valeurs de la scène contre le manifeste de son pin. Liste vide : compatible. Bornée à `MAX_CHECK_ERRORS`."""

    errors: list[str] = []
    if manifest.ref != scene.prefab:
        errors.append(f"manifest is {manifest.ref.prefab_id}@{manifest.ref.version}, "
                      f"the scene pins {scene.prefab.prefab_id}@{scene.prefab.version}")
    for control in scene.controls:
        where = f"control {control.control_id}"
        node = node_of(manifest, control)
        if node is None:
            errors.append(f"{where}: {control.path} is not declared by {scene.prefab.prefab_id}@{scene.prefab.version}")
            continue
        problem = bounds_problem(node, control.bounds)
        if problem is None and control.default is not None:
            problem = value_problem(node, control.bounds, control.default, f"{control.path} (default)")
        if problem is None:
            present, value = value_at(scene, control)
            if present:
                problem = value_problem(node, control.bounds, value, control.path)
        if problem is not None:
            errors.append(f"{where}: {problem}")
    return [clip(item, 200) for item in errors[:MAX_CHECK_ERRORS]]


def _is_required(manifest: PrefabManifest, control: StudioControl) -> bool:
    root = manifest.props if control.root == "props" else manifest.data
    parent = root.at(control.keys[:-1])
    return parent is not None and control.keys[-1] in parent.required


def describe_control(scene: StudioScene, manifest: PrefabManifest, control: StudioControl) -> dict[str, Any]:
    """Une ligne d'introspection : tout ce qu'il faut pour afficher ou régler le contrôle, sans lire le manifeste."""

    node = node_of(manifest, control)
    assert node is not None, "describe_control runs after check_scene"
    present, current = value_at(scene, control)
    default = control.default if control.default is not None else (node.default if node.has_default else None)
    return {
        "control_id": control.control_id, "label": control.label, "group": control.group.value,
        "meaning": control.meaning, "path": control.path, "type": node.type.value,
        "widget": widget_for(node, control.bounds).value, "required": _is_required(manifest, control),
        "bounds": effective_bounds(node, control.bounds), "default": default,
        "current": current if present else default, "is_set": present,
    }


def describe_scene(scene: StudioScene, manifest: PrefabManifest, *, order: int) -> dict[str, Any]:
    """Réponse à « qu'est-ce qui s'édite sur cette scène ? » : identité, pin, contrôles résolus, ancres, budget de charge."""

    problems = check_scene(scene, manifest)
    return {
        "scene_id": scene.scene_id, "order": order, "title": scene.title, "section": scene.section,
        "prefab": scene.prefab.to_dict(), "preview": scene.preview.to_dict(),
        "controls": [describe_control(scene, manifest, c) for c in scene.controls] if not problems else [],
        "anchors": [a.to_dict() for a in scene.anchors], "payload": scene.budget(), "problems": problems,
        "stage": {"mode": "patch_stable_window", "prefab_key": f"{scene.prefab.prefab_id}@{scene.prefab.version}"},
    }


# ------------------------------------------------------------------ proposition de contrôles depuis un manifeste

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_GROUP_OF = {InputType.STRING: ControlGroup.CONTENT, InputType.TEXT: ControlGroup.CONTENT,
             InputType.URL: ControlGroup.CONTENT, InputType.COLOR: ControlGroup.VISUAL,
             InputType.ENUM: ControlGroup.VISUAL, InputType.BOOLEAN: ControlGroup.VISUAL,
             InputType.NUMBER: ControlGroup.VISUAL, InputType.INTEGER: ControlGroup.VISUAL}


def _slug(parts: list[str]) -> str:
    text = re.sub(r"[^a-z0-9_]+", "_", _CAMEL.sub("_", "_".join(parts)).lower()).strip("_")
    text = text if text and text[0].isalpha() else "c_" + text
    return text[:40]


def suggest_controls(manifest: PrefabManifest) -> tuple[StudioControl, ...]:
    """Point de départ à curer, **pas** une vérité : une proposition déterministe depuis le manifeste.

    Une feuille scalaire de `props` puis de `data` (ni objet, ni liste : structure, Tier 2) par contrôle,
    au plus `MAX_CONTROLS`, dans l'ordre du manifeste. Mêmes manifeste -> mêmes ids. Libellé : le nom de
    la propriété ; sens : la description du schéma. Les bornes restent celles du manifeste.
    """

    leaves: list[tuple[str, list[str], InputSchema]] = []

    def walk(root: str, keys: list[str], node: InputSchema) -> None:
        if node.type is InputType.OBJECT:
            for name, child in node.properties.items():
                walk(root, keys + [name], child)
        elif node.type is not InputType.ARRAY and keys:
            leaves.append((root, keys, node))

    walk("props", [], manifest.props)
    walk("data", [], manifest.data)
    controls: list[StudioControl] = []
    taken: set[str] = set()
    for root, keys, node in leaves[:MAX_CONTROLS]:
        control_id = _slug(keys)
        if control_id in taken:
            control_id = _slug([root] + keys)
        suffix = 2
        while control_id in taken:
            control_id = f"{_slug([root] + keys)[:36]}_{suffix}"
            suffix += 1
        taken.add(control_id)
        label = keys[-1].replace("_", " ").strip().capitalize()[:MAX_LABEL_CHARS] or control_id
        meaning = node.description if node.description and node.description == node.description.strip() \
            and node.description.isprintable() and len(node.description) <= MAX_MEANING_CHARS else ""
        controls.append(StudioControl(control_id, ".".join([root] + keys), label, _GROUP_OF[node.type], meaning))
    return tuple(controls)

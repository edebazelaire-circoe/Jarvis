"""Contrats de la scène constellation (handoff jarvis-constellation-scene-runtime, Slice 01).

La scène est la **projection visuelle** persistante du travail et des
explications que JARVIS montre à l'écran : étoiles d'exécution, artefacts,
signaux d'attention, fenêtres et groupes, reliés entre eux sur un plan 2D à
couches explicites. Elle ne fait jamais foi sur le travail lui-même : l'état de
travail Core (`jarvis.domain.work_state`) reste la vérité d'exécution
(Décision 17).

- `SceneObject` : un objet stable (`object_id`), de nature fermée (`kind`),
  coloré par sa catégorie, avec représentation, géométrie, couche, visibilité,
  disposition et contraintes ;
- `SceneRelation` : un lien typé entre deux objets actifs ;
- `SceneSnapshot` : la scène active à une révision, plus les pierres
  tombales bornées des objets archivés ;
- `SceneCommand` : une intention d'un acteur (`runtime`, `brain`, `user`) ;
- `ScenePatch` : le delta exact produit par une commande appliquée.

Invariants transverses :

- l'autorité est appliquée par le réducteur, jamais par l'appelant : une
  commande hors droits rend `rejected_authority`, quel que soit le catalogue
  d'outils qui l'a émise (Décision 14) ;
- `exec_state` et `work_ref` reflètent Core : seul `runtime` les écrit ;
- un signal d'exécution est vivant tant que son lien `explains` existe :
  `runtime` retire ses propres signaux en déliant ce lien (Slice 04), sans
  jamais archiver, masquer ni placer ;
- seul `runtime` crée un nœud d'exécution (`agent`, `job`) : une étoile naît
  d'un fait d'exécution, jamais d'une composition (Décisions 3, 4, 17) ;
- une fin d'exécution ne change ni la visibilité ni la disposition
  (Décision 12) ; caché ≠ archivé (Décision 13) ; seul `user` archive, et
  l'objet archivé quitte la scène pour l'historique ; une étoile archivée
  emporte ses signaux runtime, et l'archivage groupé (`archive_many`) ne
  prend que du travail terminé (Slice 08) ;
- un objet épinglé par l'utilisateur ne bouge que sous la main de
  l'utilisateur (Décision 9) ;
- changer de représentation garde l'identité de l'objet (Décision 6) ;
- la révision avance d'exactement un par commande appliquée ; une commande
  refusée, invalide ou sans effet ne la touche pas (Décision 20) ;
- toutes les chaînes, collections et charges sont bornées ; les formes
  sérialisées racines portent `schema_version` et le décodage est strict.

`apply_scene_command` est une fonction pure : le futur `SceneStore`
(Slice 02) l'applique, persiste le patch puis le publie. Aucune E/S ici.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
import json
import math
from typing import Any, Callable

from jarvis.domain._checks import MAX_ID_CHARS, check_id, check_text, check_token, preview
from jarvis.domain.work_state import MAX_SOURCE_CHARS

#: Version des formes sérialisées racines (instantané, commande, patch). Un
#: lecteur refuse toute autre valeur, plus récente comprise : il ne devine pas
#: une forme qu'il ne connaît pas.
SCENE_SCHEMA_VERSION = 1

# Bornes des champs publics. Les identifiants reprennent celles de l'état de
# travail : un `object_id` dérive souvent d'un `(source, external_id)`.
MAX_CATEGORY_CHARS = 32
MAX_TITLE_CHARS = 160
MAX_PAYLOAD_SUMMARY_CHARS = 2_000
MAX_PAYLOAD_ITEMS = 32
MAX_ITEM_LABEL_CHARS = 160
MAX_ITEM_REF_CHARS = 256
MAX_URL_CHARS = 2_048
#: Taille JSON UTF-8 compacte d'une charge. Refusée au-delà, jamais tronquée.
MAX_PAYLOAD_BYTES = 16_384
#: Objets actifs d'un instantané. Au-delà, une création est `invalid`
#: (`scene_full`). Les objets archivés n'y comptent pas : ils sortent de la
#: scène vers l'historique.
MAX_SCENE_OBJECTS = 512
#: Pierres tombales : identifiants archivés retenus pour qu'une mise à jour
#: tardive ne ressuscite pas un objet. Au-delà, les plus anciennes tombent,
#: dans `apply_scene_patch` pour que le rejeu reste exact. L'état de travail
#: Core ne vit qu'une session (64 éléments, nouveau `store_id` au démarrage) :
#: un travail archivé 4 096 archivages plus tôt ne revient pas en pratique.
MAX_ARCHIVED_IDS = 4_096
MAX_SCENE_RELATIONS = 1_024
#: Un archivage émet chaque objet archivé (l'étoile et ses signaux runtime,
#: Slice 08 ; toute une sélection pour `archive_many`) et la suppression de
#: toutes leurs relations : au plus la scène entière.
MAX_PATCH_OPS = MAX_SCENE_OBJECTS + MAX_SCENE_RELATIONS
#: Identifiants d'un `archive_many` (Slice 08) : au plus la scène active.
MAX_ARCHIVE_MANY_IDS = MAX_SCENE_OBJECTS
#: Coordonnées en unités de scène (pas en pixels) ; le rendu met à l'échelle.
MAX_SCENE_COORDINATE = 100_000.0
MAX_SCENE_EXTENT = 100_000.0
#: Repère d'écran (Slice 05) : origine (0, 0) au centre de la fenêtre, x vers
#: la droite, y vers le bas ; `geometry.x/y` est le coin haut gauche de la
#: boîte. Le cadre de référence x ∈ [-160, 160], y ∈ [-90, 90] (16:9) est
#: toujours entièrement visible : le rendu met à l'échelle uniformément
#: (`min(largeur / 320, hauteur / 180)` pixels par unité) et centre ; un autre
#: rapport de fenêtre montre de la scène en plus sur l'axe long. Au-delà, un
#: objet reste dans la scène mais peut sortir de l'écran. Même valeur dans
#: `control_center_scene_layout.js` (test de parité).
SCENE_FRAME_HALF_WIDTH = 160
SCENE_FRAME_HALF_HEIGHT = 90
#: Zone de composition sûre (Slice 05, reprise QA) : la partie du cadre qu'aucune
#: commande de la page ne recouvre à 1280 × 720 (plus petite taille 16:9 prise
#: en charge, 4 px par unité), dans les deux thèmes : barre du haut et dock
#: Omega en haut, dock du thème circuit à droite, indication vocale et
#: indicateurs de scène en bas. Le résolveur ne pose qu'ici ; les bords du cadre
#: au-delà peuvent passer sous les commandes. `(x0, y0, x1, y1)` : une boîte est
#: sûre si `x0 ≤ x`, `y0 ≤ y`, `x + w ≤ x1`, `y + h ≤ y1`. Même valeur dans
#: `control_center_scene_layout.js` (`SAFE_AREA`, test de parité).
SCENE_SAFE_AREA = (-152, -72, 138, 68)
#: Couches : tout entier de la plage est valide ; 50/100/120/150/220/300 sont
#: des conventions (Décision 8), pas des valeurs imposées.
MIN_LAYER = 0
MAX_LAYER = 1_000
MAX_ORDER = 1_000_000
DEFAULT_RELATION_LAYER = 50

#: Révision : entier signé 64 bits, pour tenir dans un INTEGER SQLite
#: (Slice 02).
MAX_REVISION = 2**63 - 1


class SceneObjectKind(StrEnum):
    """Nature fermée d'un objet de scène. Extensible plus tard, jamais libre."""

    AGENT = "agent"
    JOB = "job"
    ARTIFACT = "artifact"
    ATTENTION = "attention"
    WINDOW = "window"
    GROUP = "group"


#: Nœuds d'exécution : les étoiles que le runtime crée sans tour du cerveau.
EXECUTION_KINDS = frozenset({SceneObjectKind.AGENT, SceneObjectKind.JOB})
#: Natures que `runtime` peut écrire : nœuds d'exécution et signaux.
RUNTIME_KINDS = EXECUTION_KINDS | {SceneObjectKind.ATTENTION}

#: Couche donnée à un objet créé sans couche explicite. Suit les bandes
#: conventionnelles : groupes derrière, étoiles, artefacts, fenêtres, attention
#: au-dessus. Le cerveau et l'utilisateur peuvent la changer ensuite.
DEFAULT_LAYERS: dict[SceneObjectKind, int] = {
    SceneObjectKind.GROUP: 50,
    SceneObjectKind.AGENT: 100,
    SceneObjectKind.JOB: 100,
    SceneObjectKind.ARTIFACT: 120,
    SceneObjectKind.WINDOW: 220,
    SceneObjectKind.ATTENTION: 300,
}


class ExecState(StrEnum):
    """Reflet de `WorkStatus`, plus `unknown`. Indice secondaire, jamais couleur.

    `unknown` : objet sans travail Core (artefact, fenêtre...) ou travail pas
    encore réobservé après un redémarrage (Slice 10).
    """

    UNKNOWN = "unknown"
    PENDING = "pending"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class Representation(StrEnum):
    """Forme de rendu d'un même objet (Décision 6)."""

    POINT = "point"
    CAPSULE = "capsule"
    WINDOW = "window"


class Visibility(StrEnum):
    """Rendu ou non d'un objet **actif** (Décision 13)."""

    VISIBLE = "visible"
    HIDDEN = "hidden"


class Disposition(StrEnum):
    """Présence dans la scène active.

    Un instantané ne contient que des objets `active`. `archived` ne se lit
    que sur la forme historique de l'objet, portée par l'opération de patch
    `archive_object` que le magasin écrit dans l'historique.
    """

    ACTIVE = "active"
    ARCHIVED = "archived"


class PlacedBy(StrEnum):
    """Auteur de la géométrie retenue, ou créateur tant qu'elle manque.

    Un objet sans géométrie n'est pas placé, quel que soit `placed_by`.
    `resolver` : placement opportuniste de l'AutoResolver, validé par un
    acteur ; il ne remplace jamais un placement explicite (Décision 9).
    """

    RUNTIME = "runtime"
    BRAIN = "brain"
    USER = "user"
    RESOLVER = "resolver"


class RelationKind(StrEnum):
    """Nature fermée d'un lien. `explains` relie aussi un signal à son nœud."""

    PARENT_OF = "parent_of"
    EXPLAINS = "explains"
    GROUPS = "groups"


class SceneActor(StrEnum):
    """Émetteur d'une commande. Le transport l'impose, le réducteur l'applique."""

    RUNTIME = "runtime"
    BRAIN = "brain"
    USER = "user"


class SceneOp(StrEnum):
    UPSERT_OBJECT = "upsert_object"
    PATCH_OBJECT = "patch_object"
    SET_GEOMETRY = "set_geometry"
    SET_REPRESENTATION = "set_representation"
    SET_VISIBILITY = "set_visibility"
    PIN = "pin"
    UNPIN = "unpin"
    LINK = "link"
    UNLINK = "unlink"
    ARCHIVE = "archive"
    #: Archivage groupé des travaux terminés (Slice 08, amendement PM) :
    #: utilisateur seulement, liste explicite et bornée, revalidée objet par
    #: objet, une seule révision.
    ARCHIVE_MANY = "archive_many"
    ATTACH_SIGNAL = "attach_signal"
    #: Artefact groupé qui explique un objet (Slice 07) : créer ou mettre à
    #: jour l'artefact **et** son lien `explains` vers la cible, en une
    #: révision, tout ou rien. `runtime` ne l'a pas (Décision 5 : un artefact
    #: est une sélection du cerveau, jamais un événement brut).
    ATTACH_ARTIFACT = "attach_artifact"


#: Opérations de disposition : seul l'utilisateur archive (Décision 14).
ARCHIVE_OPS = frozenset({SceneOp.ARCHIVE, SceneOp.ARCHIVE_MANY})

#: Matrice d'autorité par opération. S'y ajoutent des règles par champ et par
#: nature, appliquées sur l'effet réel de la commande (voir
#: `apply_scene_command`). `pin`/`unpin` sont réservées à l'utilisateur :
#: `pinned_by_user` enregistre une décision de l'utilisateur, et un `unpin` du
#: cerveau suffirait à contourner la protection de géométrie.
ALLOWED_SCENE_OPS: dict[SceneActor, frozenset[SceneOp]] = {
    SceneActor.RUNTIME: frozenset(
        {SceneOp.UPSERT_OBJECT, SceneOp.PATCH_OBJECT, SceneOp.LINK, SceneOp.UNLINK, SceneOp.ATTACH_SIGNAL}
    ),
    SceneActor.BRAIN: frozenset(set(SceneOp) - ARCHIVE_OPS - {SceneOp.PIN, SceneOp.UNPIN}),
    SceneActor.USER: frozenset(SceneOp),
}

#: Champs qui reflètent Core : écrits par `runtime` seulement.
EXECUTION_FIELDS = frozenset({"exec_state", "work_ref"})
#: Champs de composition : jamais écrits par `runtime` (Décision 3).
COMPOSITION_FIELDS = frozenset({"representation", "geometry", "layer", "order", "visibility"})
_WRITABLE_FIELDS = ("category", "payload", *sorted(EXECUTION_FIELDS), *sorted(COMPOSITION_FIELDS))


class UnsupportedSceneSchemaVersion(ValueError):
    """Forme sérialisée absente de version, ou d'une version non prise en charge."""

    def __init__(self, name: str, version: object) -> None:
        super().__init__(f"unsupported {name} schema_version {preview(version)} (expected {SCENE_SCHEMA_VERSION})")
        self.version = version


# ------------------------------------------------------------------ validation
# Texte, jeton et identifiant : `jarvis.domain._checks`, partagé avec
# `work_state` (mêmes règles, mêmes messages).


def _check_enum(name: str, value: object, enum_type: type[StrEnum]) -> None:
    if not isinstance(value, enum_type):
        raise TypeError(f"{name} must be a {enum_type.__name__}")


def _check_int(name: str, value: object, low: int, high: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")


def _check_revision(value: object, low: int) -> None:
    _check_int("revision", value, low, MAX_REVISION)


def _check_multiline_text(name: str, value: object, limit: int) -> None:
    """Texte sur plusieurs lignes : seuls `\\n` et `\\t` parmi les contrôles C0."""

    check_text(name, value, limit, single_line=False)
    if any(ch < " " and ch not in "\n\t" for ch in str(value)):
        raise ValueError(f"{name} must not contain control characters other than newline and tab")


def _check_instance(name: str, value: object, expected: type) -> None:
    if not isinstance(value, expected):
        raise TypeError(f"{name} must be a {expected.__name__}")


# ------------------------------------------------------------------ fil


def _check_keys(name: str, payload: object, required: frozenset[str], optional: frozenset[str] = frozenset()) -> dict[str, Any]:
    """Décodage strict : clé inconnue ou clé requise absente sont refusées."""

    if not isinstance(payload, dict):
        raise TypeError(f"{name} must be an object")
    unknown = sorted(str(key)[:40] for key in payload if key not in required and key not in optional)
    if unknown:
        raise ValueError(f"{name} has unknown fields: {unknown[:5]}")
    missing = sorted(required - payload.keys())
    if missing:
        raise ValueError(f"{name} is missing fields: {missing}")
    return payload


def _check_schema_version(name: str, payload: object) -> None:
    """Contrôlée avant toute autre clé : une forme future n'est pas « invalide »,
    elle est d'une version que ce lecteur ne connaît pas."""

    if not isinstance(payload, dict):
        raise TypeError(f"{name} must be an object")
    version = payload.get("schema_version")
    # `type(...) is int` : ni `True` ni `1.0` ne passent pour la version 1.
    if type(version) is not int or version != SCENE_SCHEMA_VERSION:
        raise UnsupportedSceneSchemaVersion(name, version)


def _enum(enum_type: type[StrEnum], raw: object, name: str) -> Any:
    if not isinstance(raw, str):
        raise TypeError(f"{name} must be a string")
    try:
        return enum_type(raw)
    except ValueError:
        # Message propre plutôt que celui de `Enum`, qui recopie la valeur
        # entière : la valeur reçue est tronquée (`preview`).
        raise ValueError(f"{name} must be one of {sorted(item.value for item in enum_type)}, got {preview(raw)}") from None


def _optional_enum(enum_type: type[StrEnum], payload: dict[str, Any], key: str) -> Any:
    raw = payload.get(key)
    return None if raw is None else _enum(enum_type, raw, key)


def _optional_nested(cls: Any, payload: dict[str, Any], key: str) -> Any:
    raw = payload.get(key)
    return None if raw is None else cls.from_payload(raw)


def _list(name: str, raw: object, limit: int) -> list[Any]:
    if not isinstance(raw, list):
        raise TypeError(f"{name} must be a list")
    if len(raw) > limit:
        # Refusé avant de décoder : un fil hostile ne fait pas construire un
        # nombre arbitraire d'objets.
        raise ValueError(f"{name} holds at most {limit} entries")
    return raw


def _wire(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "to_payload"):
        return value.to_payload()
    return value


# ------------------------------------------------------------------ types


@dataclass(frozen=True, slots=True)
class SceneGeometry:
    """Rectangle en unités de scène : coin `(x, y)`, largeur `w`, hauteur `h`."""

    x: float
    y: float
    w: float
    h: float

    def __post_init__(self) -> None:
        for name in ("x", "y", "w", "h"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a number")
            try:
                number = float(value)
            except OverflowError:
                # Un entier JSON de 400 chiffres ne tient pas dans un flottant :
                # erreur de valeur, pas `OverflowError`.
                raise ValueError(f"{name} is out of range") from None
            if not math.isfinite(number):
                raise ValueError(f"{name} must be finite")
            object.__setattr__(self, name, number)
        if abs(self.x) > MAX_SCENE_COORDINATE or abs(self.y) > MAX_SCENE_COORDINATE:
            raise ValueError(f"x and y must be within ±{MAX_SCENE_COORDINATE:g}")
        if not (0 < self.w <= MAX_SCENE_EXTENT and 0 < self.h <= MAX_SCENE_EXTENT):
            raise ValueError(f"w and h must be positive and at most {MAX_SCENE_EXTENT:g}")

    def to_payload(self) -> dict[str, Any]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}

    @classmethod
    def from_payload(cls, payload: object) -> SceneGeometry:
        data = _check_keys("geometry", payload, frozenset({"x", "y", "w", "h"}))
        return cls(x=data["x"], y=data["y"], w=data["w"], h=data["h"])


@dataclass(frozen=True, slots=True)
class WorkRef:
    """Rattachement d'un nœud d'exécution au travail Core qu'il projette.

    Même identité que `WorkItem` : `(source, external_id)`, plus le `work_id`
    du cerveau quand Core le connaît. Jamais déduit d'un libellé.
    """

    source: str
    external_id: str
    work_id: str | None = None

    def __post_init__(self) -> None:
        check_token("source", self.source, MAX_SOURCE_CHARS, required=True)
        check_id("external_id", self.external_id, required=True)
        check_id("work_id", self.work_id, required=False)

    def to_payload(self) -> dict[str, Any]:
        return {"source": self.source, "external_id": self.external_id, "work_id": self.work_id}

    @classmethod
    def from_payload(cls, payload: object) -> WorkRef:
        data = _check_keys("work_ref", payload, frozenset({"source", "external_id"}), frozenset({"work_id"}))
        return cls(source=data["source"], external_id=data["external_id"], work_id=data.get("work_id"))


@dataclass(frozen=True, slots=True)
class ScenePayloadItem:
    """Entrée d'une charge (fichier, URL visitée, test...). `url` : http(s) seulement."""

    label: str
    ref: str = ""
    url: str = ""

    def __post_init__(self) -> None:
        check_text("label", self.label, MAX_ITEM_LABEL_CHARS)
        if not self.label.strip():
            raise ValueError("label is required")
        check_text("ref", self.ref, MAX_ITEM_REF_CHARS)
        check_text("url", self.url, MAX_URL_CHARS)
        if self.url and not self.url.startswith(("https://", "http://")):
            # Le rendu insère l'URL dans le DOM : pas de `javascript:` ni de
            # `file:`.
            raise ValueError("url must use http or https")

    def to_payload(self) -> dict[str, Any]:
        return {"label": self.label, "ref": self.ref, "url": self.url}

    @classmethod
    def from_payload(cls, payload: object) -> ScenePayloadItem:
        data = _check_keys("payload item", payload, frozenset({"label"}), frozenset({"ref", "url"}))
        return cls(label=data["label"], ref=data.get("ref", ""), url=data.get("url", ""))


@dataclass(frozen=True, slots=True)
class ScenePayload:
    """Contenu affichable borné : titre, résumé, entrées (artefacts surtout).

    Titre et libellés : une ligne imprimable. Résumé : plusieurs lignes, sans
    caractère de contrôle C0 autre que `\\n` et `\\t`.
    """

    title: str = ""
    summary: str = ""
    items: tuple[ScenePayloadItem, ...] = ()

    def __post_init__(self) -> None:
        check_text("title", self.title, MAX_TITLE_CHARS)
        _check_multiline_text("summary", self.summary, MAX_PAYLOAD_SUMMARY_CHARS)
        if not isinstance(self.items, tuple) or not all(isinstance(item, ScenePayloadItem) for item in self.items):
            raise TypeError("items must be a tuple of ScenePayloadItem")
        if len(self.items) > MAX_PAYLOAD_ITEMS:
            raise ValueError(f"a payload holds at most {MAX_PAYLOAD_ITEMS} items")
        size = len(json.dumps(self.to_payload(), ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if size > MAX_PAYLOAD_BYTES:
            raise ValueError(f"payload exceeds {MAX_PAYLOAD_BYTES} bytes ({size})")

    def to_payload(self) -> dict[str, Any]:
        return {"title": self.title, "summary": self.summary, "items": [item.to_payload() for item in self.items]}

    @classmethod
    def from_payload(cls, payload: object) -> ScenePayload:
        data = _check_keys("payload", payload, frozenset(), frozenset({"title", "summary", "items"}))
        items = _list("items", data.get("items", []), MAX_PAYLOAD_ITEMS)
        return cls(
            title=data.get("title", ""),
            summary=data.get("summary", ""),
            items=tuple(ScenePayloadItem.from_payload(item) for item in items),
        )


@dataclass(frozen=True, slots=True)
class SceneConstraints:
    """Contraintes de placement, posées par le réducteur, jamais par une charge.

    `pinned_by_user` : l'utilisateur a fixé l'objet ; seul lui peut encore le
    déplacer ou le redimensionner. Un objet épinglé a toujours une géométrie.
    """

    placed_by: PlacedBy
    pinned_by_user: bool = False

    def __post_init__(self) -> None:
        _check_enum("placed_by", self.placed_by, PlacedBy)
        if not isinstance(self.pinned_by_user, bool):
            raise TypeError("pinned_by_user must be a boolean")

    def to_payload(self) -> dict[str, Any]:
        return {"placed_by": self.placed_by.value, "pinned_by_user": self.pinned_by_user}

    @classmethod
    def from_payload(cls, payload: object) -> SceneConstraints:
        data = _check_keys("constraints", payload, frozenset({"placed_by", "pinned_by_user"}))
        return cls(placed_by=_enum(PlacedBy, data["placed_by"], "placed_by"), pinned_by_user=data["pinned_by_user"])


def _check_layer(value: object) -> None:
    _check_int("layer", value, MIN_LAYER, MAX_LAYER)


def _check_order(value: object) -> None:
    _check_int("order", value, -MAX_ORDER, MAX_ORDER)


@dataclass(frozen=True, slots=True)
class SceneObject:
    """Objet de la scène, identifié par `object_id` pour toute sa vie.

    `geometry` vaut `None` tant que l'objet n'est pas placé : l'AutoResolver
    du navigateur le place alors (Slice 05). `layer` ordonne l'empilement,
    `order` départage une même couche. `origin` est l'acteur qui l'a créé :
    posé une fois par le réducteur, jamais réécrit ; un nœud d'exécution est
    toujours d'origine `runtime`.
    """

    object_id: str
    kind: SceneObjectKind
    category: str
    constraints: SceneConstraints
    origin: SceneActor
    exec_state: ExecState = ExecState.UNKNOWN
    representation: Representation = Representation.POINT
    geometry: SceneGeometry | None = None
    layer: int = 100
    order: int = 0
    visibility: Visibility = Visibility.VISIBLE
    disposition: Disposition = Disposition.ACTIVE
    work_ref: WorkRef | None = None
    payload: ScenePayload = field(default_factory=ScenePayload)

    def __post_init__(self) -> None:
        check_id("object_id", self.object_id, required=True)
        _check_enum("kind", self.kind, SceneObjectKind)
        check_token("category", self.category, MAX_CATEGORY_CHARS, required=True)
        _check_instance("constraints", self.constraints, SceneConstraints)
        _check_enum("origin", self.origin, SceneActor)
        if self.kind in EXECUTION_KINDS and self.origin is not SceneActor.RUNTIME:
            raise ValueError("an execution node originates from runtime")
        _check_enum("exec_state", self.exec_state, ExecState)
        _check_enum("representation", self.representation, Representation)
        if self.geometry is not None:
            _check_instance("geometry", self.geometry, SceneGeometry)
        _check_layer(self.layer)
        _check_order(self.order)
        _check_enum("visibility", self.visibility, Visibility)
        _check_enum("disposition", self.disposition, Disposition)
        if self.work_ref is not None:
            _check_instance("work_ref", self.work_ref, WorkRef)
        _check_instance("payload", self.payload, ScenePayload)
        if self.constraints.pinned_by_user and self.geometry is None:
            raise ValueError("a pinned object must have a geometry")

    @property
    def active(self) -> bool:
        return self.disposition is Disposition.ACTIVE

    def to_payload(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "kind": self.kind.value,
            "category": self.category,
            "constraints": self.constraints.to_payload(),
            "origin": self.origin.value,
            "exec_state": self.exec_state.value,
            "representation": self.representation.value,
            "geometry": _wire(self.geometry),
            "layer": self.layer,
            "order": self.order,
            "visibility": self.visibility.value,
            "disposition": self.disposition.value,
            "work_ref": _wire(self.work_ref),
            "payload": self.payload.to_payload(),
        }

    @classmethod
    def from_payload(cls, payload: object) -> SceneObject:
        data = _check_keys("object", payload, _OBJECT_WIRE_KEYS)
        return cls(
            object_id=data["object_id"],
            kind=_enum(SceneObjectKind, data["kind"], "kind"),
            category=data["category"],
            constraints=SceneConstraints.from_payload(data["constraints"]),
            origin=_enum(SceneActor, data["origin"], "origin"),
            exec_state=_enum(ExecState, data["exec_state"], "exec_state"),
            representation=_enum(Representation, data["representation"], "representation"),
            geometry=_optional_nested(SceneGeometry, data, "geometry"),
            layer=data["layer"],
            order=data["order"],
            visibility=_enum(Visibility, data["visibility"], "visibility"),
            disposition=_enum(Disposition, data["disposition"], "disposition"),
            work_ref=_optional_nested(WorkRef, data, "work_ref"),
            payload=ScenePayload.from_payload(data["payload"]),
        )


#: Forme stockée : toutes les clés sont requises.
_OBJECT_WIRE_KEYS = frozenset(
    {
        "object_id", "kind", "category", "constraints", "origin", "exec_state", "representation", "geometry",
        "layer", "order", "visibility", "disposition", "work_ref", "payload",
    }
)


@dataclass(frozen=True, slots=True)
class SceneRelation:
    """Lien orienté `from_id` → `to_id` entre deux objets actifs distincts."""

    relation_id: str
    kind: RelationKind
    from_id: str
    to_id: str
    layer: int = DEFAULT_RELATION_LAYER

    def __post_init__(self) -> None:
        check_id("relation_id", self.relation_id, required=True)
        _check_enum("kind", self.kind, RelationKind)
        check_id("from_id", self.from_id, required=True)
        check_id("to_id", self.to_id, required=True)
        if self.from_id == self.to_id:
            raise ValueError("a relation cannot link an object to itself")
        _check_layer(self.layer)

    @property
    def endpoints(self) -> tuple[RelationKind, str, str]:
        return (self.kind, self.from_id, self.to_id)

    def to_payload(self) -> dict[str, Any]:
        return {
            "relation_id": self.relation_id,
            "kind": self.kind.value,
            "from_id": self.from_id,
            "to_id": self.to_id,
            "layer": self.layer,
        }

    @classmethod
    def from_payload(cls, payload: object) -> SceneRelation:
        data = _check_keys("relation", payload, frozenset({"relation_id", "kind", "from_id", "to_id"}), frozenset({"layer"}))
        return cls(
            relation_id=data["relation_id"],
            kind=_enum(RelationKind, data["kind"], "kind"),
            from_id=data["from_id"],
            to_id=data["to_id"],
            layer=data.get("layer", DEFAULT_RELATION_LAYER),
        )


@dataclass(frozen=True, slots=True)
class SceneSnapshot:
    """Scène active à une révision : objets, relations, pierres tombales.

    `objects` ne contient que des objets actifs ; chaque relation en relie
    deux. `archived_ids` garde, dans l'ordre d'archivage et borné par
    `MAX_ARCHIVED_IDS`, l'identifiant des objets archivés : toute commande qui
    les vise reste `invalid` (`object_archived`). L'objet archivé lui-même vit
    dans l'historique du magasin, pas ici.
    """

    scene_id: str
    revision: int = 0
    objects: tuple[SceneObject, ...] = ()
    relations: tuple[SceneRelation, ...] = ()
    archived_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        check_id("scene_id", self.scene_id, required=True)
        _check_revision(self.revision, 0)
        if not isinstance(self.objects, tuple) or not all(isinstance(item, SceneObject) for item in self.objects):
            raise TypeError("objects must be a tuple of SceneObject")
        if not isinstance(self.relations, tuple) or not all(isinstance(item, SceneRelation) for item in self.relations):
            raise TypeError("relations must be a tuple of SceneRelation")
        if not isinstance(self.archived_ids, tuple):
            raise TypeError("archived_ids must be a tuple of identifiers")
        if len(self.objects) > MAX_SCENE_OBJECTS:
            raise ValueError(f"a scene holds at most {MAX_SCENE_OBJECTS} objects")
        if len(self.archived_ids) > MAX_ARCHIVED_IDS:
            raise ValueError(f"a scene retains at most {MAX_ARCHIVED_IDS} archived ids")
        for archived_id in self.archived_ids:
            check_id("archived_ids[]", archived_id, required=True)
        if len(self.relations) > MAX_SCENE_RELATIONS:
            raise ValueError(f"a scene holds at most {MAX_SCENE_RELATIONS} relations")
        by_id = {item.object_id: item for item in self.objects}
        if len(by_id) != len(self.objects):
            raise ValueError("scene objects must be unique per object_id")
        if any(not item.active for item in self.objects):
            raise ValueError("a scene snapshot holds active objects only")
        archived = set(self.archived_ids)
        if len(archived) != len(self.archived_ids):
            raise ValueError("archived ids must be unique")
        if archived & by_id.keys():
            raise ValueError("an archived id cannot also be an active object")
        if len({relation.relation_id for relation in self.relations}) != len(self.relations):
            raise ValueError("scene relations must be unique per relation_id")
        for relation in self.relations:
            if relation.from_id not in by_id or relation.to_id not in by_id:
                raise ValueError(f"relation {relation.relation_id} must link active objects")

    def is_archived(self, object_id: str) -> bool:
        return object_id in self.archived_ids

    def get_object(self, object_id: str) -> SceneObject | None:
        return next((item for item in self.objects if item.object_id == object_id), None)

    def get_relation(self, relation_id: str) -> SceneRelation | None:
        return next((item for item in self.relations if item.relation_id == relation_id), None)

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCENE_SCHEMA_VERSION,
            "scene_id": self.scene_id,
            "revision": self.revision,
            "objects": [item.to_payload() for item in self.objects],
            "relations": [item.to_payload() for item in self.relations],
            "archived_ids": list(self.archived_ids),
        }

    @classmethod
    def from_payload(cls, payload: object) -> SceneSnapshot:
        _check_schema_version("scene snapshot", payload)
        data = _check_keys(
            "scene snapshot",
            payload,
            frozenset({"schema_version", "scene_id", "revision", "objects", "relations", "archived_ids"}),
        )
        objects = _list("objects", data["objects"], MAX_SCENE_OBJECTS)
        relations = _list("relations", data["relations"], MAX_SCENE_RELATIONS)
        archived_ids = _list("archived_ids", data["archived_ids"], MAX_ARCHIVED_IDS)
        return cls(
            scene_id=data["scene_id"],
            revision=data["revision"],
            objects=tuple(SceneObject.from_payload(item) for item in objects),
            relations=tuple(SceneRelation.from_payload(item) for item in relations),
            archived_ids=tuple(archived_ids),
        )


# ------------------------------------------------------------------ commandes


@dataclass(frozen=True, slots=True)
class SceneObjectFields:
    """Champs annoncés par une commande d'objet. `None` : non annoncé, inchangé.

    Ni `constraints` ni `disposition` : ils ne changent que par `pin`,
    `unpin`, `archive` et par le réducteur. Une géométrie ne se retire pas.
    """

    kind: SceneObjectKind | None = None
    category: str | None = None
    exec_state: ExecState | None = None
    representation: Representation | None = None
    geometry: SceneGeometry | None = None
    layer: int | None = None
    order: int | None = None
    visibility: Visibility | None = None
    work_ref: WorkRef | None = None
    payload: ScenePayload | None = None

    def __post_init__(self) -> None:
        if self.kind is not None:
            _check_enum("kind", self.kind, SceneObjectKind)
        if self.category is not None:
            check_token("category", self.category, MAX_CATEGORY_CHARS, required=True)
        if self.exec_state is not None:
            _check_enum("exec_state", self.exec_state, ExecState)
        if self.representation is not None:
            _check_enum("representation", self.representation, Representation)
        if self.geometry is not None:
            _check_instance("geometry", self.geometry, SceneGeometry)
        if self.layer is not None:
            _check_layer(self.layer)
        if self.order is not None:
            _check_order(self.order)
        if self.visibility is not None:
            _check_enum("visibility", self.visibility, Visibility)
        if self.work_ref is not None:
            _check_instance("work_ref", self.work_ref, WorkRef)
        if self.payload is not None:
            _check_instance("payload", self.payload, ScenePayload)

    def to_payload(self) -> dict[str, Any]:
        return {name: _wire(getattr(self, name)) for name in _FIELDS_WIRE_KEYS if getattr(self, name) is not None}

    @classmethod
    def from_payload(cls, payload: object) -> SceneObjectFields:
        data = _check_keys("fields", payload, frozenset(), _FIELDS_WIRE_KEYS)
        return cls(
            kind=_optional_enum(SceneObjectKind, data, "kind"),
            category=data.get("category"),
            exec_state=_optional_enum(ExecState, data, "exec_state"),
            representation=_optional_enum(Representation, data, "representation"),
            geometry=_optional_nested(SceneGeometry, data, "geometry"),
            layer=data.get("layer"),
            order=data.get("order"),
            visibility=_optional_enum(Visibility, data, "visibility"),
            work_ref=_optional_nested(WorkRef, data, "work_ref"),
            payload=_optional_nested(ScenePayload, data, "payload"),
        )


_FIELDS_WIRE_KEYS = frozenset(
    {"kind", "category", "exec_state", "representation", "geometry", "layer", "order", "visibility", "work_ref", "payload"}
)

#: Arguments requis et facultatifs de chaque opération ; tout autre argument
#: doit rester `None`. Une commande mal formée ne se construit pas.
_OP_ARGUMENTS: dict[SceneOp, tuple[frozenset[str], frozenset[str]]] = {
    SceneOp.UPSERT_OBJECT: (frozenset({"object_id", "fields"}), frozenset()),
    SceneOp.PATCH_OBJECT: (frozenset({"object_id", "fields"}), frozenset()),
    SceneOp.SET_GEOMETRY: (frozenset({"object_id", "geometry"}), frozenset({"placed_by"})),
    SceneOp.SET_REPRESENTATION: (frozenset({"object_id", "representation"}), frozenset({"geometry"})),
    SceneOp.SET_VISIBILITY: (frozenset({"object_id", "visibility"}), frozenset()),
    SceneOp.PIN: (frozenset({"object_id"}), frozenset()),
    SceneOp.UNPIN: (frozenset({"object_id"}), frozenset()),
    SceneOp.LINK: (frozenset({"relation"}), frozenset()),
    SceneOp.UNLINK: (frozenset({"relation_id"}), frozenset()),
    SceneOp.ARCHIVE: (frozenset({"object_id"}), frozenset()),
    SceneOp.ARCHIVE_MANY: (frozenset({"object_ids"}), frozenset()),
    SceneOp.ATTACH_SIGNAL: (frozenset({"object_id", "fields", "target_id"}), frozenset()),
    SceneOp.ATTACH_ARTIFACT: (frozenset({"object_id", "fields", "target_id", "relation_id"}), frozenset()),
}
_COMMAND_ARGUMENTS = (
    "object_id", "fields", "geometry", "placed_by", "representation", "visibility", "relation", "relation_id", "target_id",
    "object_ids",
)


@dataclass(frozen=True, slots=True)
class SceneCommand:
    """Intention d'un acteur sur la scène. Voir `_OP_ARGUMENTS` pour la forme.

    - `upsert_object` crée l'objet (`kind` et `category` requis) ou fusionne
      les champs annoncés ; `patch_object` exige un objet existant ;
    - `set_geometry` accepte `placed_by=resolver` pour valider un placement
      de l'AutoResolver ; `set_representation` peut porter la géométrie de la
      nouvelle forme ;
    - `attach_signal` crée ou met à jour le signal `object_id` (nature
      `attention`) et le relie par `explains` à `target_id` ; la relation
      porte l'identifiant du signal : un signal a une seule cible ;
    - `attach_artifact` crée ou met à jour l'artefact `object_id` (nature
      `artifact`) et pose le lien `explains` `relation_id` vers `target_id`,
      dans un seul patch : si le lien est refusé, l'artefact n'est pas écrit
      (Slice 07). `relation_id` diffère de `object_id` : un lien d'artefact
      n'a jamais la forme d'un lien de signal (`is_signal_relation`) ;
    - `archive_many` archive en une révision les identifiants `object_ids`
      (1 à `MAX_ARCHIVE_MANY_IDS`, sans doublon), chacun revalidé par le
      réducteur (`bulk_archivable`).
    """

    op: SceneOp
    actor: SceneActor
    object_id: str | None = None
    fields: SceneObjectFields | None = None
    geometry: SceneGeometry | None = None
    placed_by: PlacedBy | None = None
    representation: Representation | None = None
    visibility: Visibility | None = None
    relation: SceneRelation | None = None
    relation_id: str | None = None
    target_id: str | None = None
    object_ids: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        _check_enum("op", self.op, SceneOp)
        _check_enum("actor", self.actor, SceneActor)
        required, optional = _OP_ARGUMENTS[self.op]
        given = {name for name in _COMMAND_ARGUMENTS if getattr(self, name) is not None}
        if required - given:
            raise ValueError(f"{self.op.value} requires {sorted(required - given)}")
        if given - required - optional:
            raise ValueError(f"{self.op.value} does not take {sorted(given - required - optional)}")
        check_id("object_id", self.object_id, required=False)
        check_id("relation_id", self.relation_id, required=False)
        check_id("target_id", self.target_id, required=False)
        if self.object_ids is not None:
            if not isinstance(self.object_ids, tuple):
                raise TypeError("object_ids must be a tuple of identifiers")
            if not 1 <= len(self.object_ids) <= MAX_ARCHIVE_MANY_IDS:
                raise ValueError(f"object_ids holds between 1 and {MAX_ARCHIVE_MANY_IDS} identifiers")
            for object_id in self.object_ids:
                check_id("object_ids[]", object_id, required=True)
            if len(set(self.object_ids)) != len(self.object_ids):
                raise ValueError("object_ids must be unique")
        for name, expected in (
            ("fields", SceneObjectFields),
            ("geometry", SceneGeometry),
            ("relation", SceneRelation),
        ):
            if getattr(self, name) is not None:
                _check_instance(name, getattr(self, name), expected)
        if self.representation is not None:
            _check_enum("representation", self.representation, Representation)
        if self.visibility is not None:
            _check_enum("visibility", self.visibility, Visibility)
        if self.placed_by is not None:
            _check_enum("placed_by", self.placed_by, PlacedBy)
            if self.placed_by is not PlacedBy.RESOLVER:
                # Sinon l'auteur est l'acteur lui-même : rien à annoncer.
                raise ValueError("placed_by may only announce a resolver placement")
        if self.op is SceneOp.ATTACH_SIGNAL and self.fields is not None:
            if self.fields.kind not in (None, SceneObjectKind.ATTENTION):
                raise ValueError("a signal is an attention object")
            if self.object_id == self.target_id:
                raise ValueError("a signal cannot target itself")
        if self.op is SceneOp.ATTACH_ARTIFACT and self.fields is not None:
            if self.fields.kind not in (None, SceneObjectKind.ARTIFACT):
                raise ValueError("attach_artifact writes an artifact object")
            if self.object_id == self.target_id:
                raise ValueError("an artifact cannot explain itself")
            if self.relation_id == self.object_id:
                # Sinon le lien aurait la forme d'un signal (`is_signal_relation`).
                raise ValueError("an artifact relation_id must differ from its object_id")

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCENE_SCHEMA_VERSION,
            "op": self.op.value,
            "actor": self.actor.value,
            **{name: _wire(getattr(self, name)) for name in _COMMAND_ARGUMENTS if getattr(self, name) is not None},
            **({"object_ids": list(self.object_ids)} if self.object_ids is not None else {}),
        }

    @classmethod
    def from_payload(cls, payload: object) -> SceneCommand:
        _check_schema_version("scene command", payload)
        data = _check_keys(
            "scene command", payload, frozenset({"schema_version", "op", "actor"}), frozenset(_COMMAND_ARGUMENTS)
        )
        raw_ids = data.get("object_ids")
        return cls(
            object_ids=None if raw_ids is None else tuple(_list("object_ids", raw_ids, MAX_ARCHIVE_MANY_IDS)),
            op=_enum(SceneOp, data["op"], "op"),
            actor=_enum(SceneActor, data["actor"], "actor"),
            object_id=data.get("object_id"),
            fields=_optional_nested(SceneObjectFields, data, "fields"),
            geometry=_optional_nested(SceneGeometry, data, "geometry"),
            placed_by=_optional_enum(PlacedBy, data, "placed_by"),
            representation=_optional_enum(Representation, data, "representation"),
            visibility=_optional_enum(Visibility, data, "visibility"),
            relation=_optional_nested(SceneRelation, data, "relation"),
            relation_id=data.get("relation_id"),
            target_id=data.get("target_id"),
        )


# ------------------------------------------------------------------ patchs


class PatchOpKind(StrEnum):
    """Delta d'état. Un objet ne quitte la scène que par `archive_object`."""

    PUT_OBJECT = "put_object"
    #: Retire l'objet de la scène et ajoute sa pierre tombale ; porte la forme
    #: historique complète (`disposition = archived`) pour le magasin.
    ARCHIVE_OBJECT = "archive_object"
    PUT_RELATION = "put_relation"
    DELETE_RELATION = "delete_relation"


@dataclass(frozen=True, slots=True)
class ScenePatchOp:
    op: PatchOpKind
    object: SceneObject | None = None
    relation: SceneRelation | None = None
    relation_id: str | None = None

    def __post_init__(self) -> None:
        _check_enum("op", self.op, PatchOpKind)
        expected = {
            PatchOpKind.PUT_OBJECT: "object",
            PatchOpKind.ARCHIVE_OBJECT: "object",
            PatchOpKind.PUT_RELATION: "relation",
            PatchOpKind.DELETE_RELATION: "relation_id",
        }[self.op]
        given = {name for name in ("object", "relation", "relation_id") if getattr(self, name) is not None}
        if given != {expected}:
            raise ValueError(f"{self.op.value} carries exactly {expected}")
        if self.object is not None:
            _check_instance("object", self.object, SceneObject)
            if self.object.active is (self.op is PatchOpKind.ARCHIVE_OBJECT):
                raise ValueError("put_object carries an active object, archive_object an archived one")
        if self.relation is not None:
            _check_instance("relation", self.relation, SceneRelation)
        check_id("relation_id", self.relation_id, required=False)

    def to_payload(self) -> dict[str, Any]:
        name = next(name for name in ("object", "relation", "relation_id") if getattr(self, name) is not None)
        return {"op": self.op.value, name: _wire(getattr(self, name))}

    @classmethod
    def from_payload(cls, payload: object) -> ScenePatchOp:
        data = _check_keys("patch op", payload, frozenset({"op"}), frozenset({"object", "relation", "relation_id"}))
        return cls(
            op=_enum(PatchOpKind, data["op"], "op"),
            object=_optional_nested(SceneObject, data, "object"),
            relation=_optional_nested(SceneRelation, data, "relation"),
            relation_id=data.get("relation_id"),
        )


@dataclass(frozen=True, slots=True)
class ScenePatch:
    """Delta exact d'une révision à la suivante (`revision` = précédente + 1).

    Appliqué dans l'ordre à l'instantané de la révision précédente, il donne
    exactement le nouvel instantané (`apply_scene_patch`). Un consommateur
    qui voit un saut de révision relit l'instantané.
    """

    revision: int
    ops: tuple[ScenePatchOp, ...]

    def __post_init__(self) -> None:
        _check_revision(self.revision, 1)
        if not isinstance(self.ops, tuple) or not all(isinstance(op, ScenePatchOp) for op in self.ops):
            raise TypeError("ops must be a tuple of ScenePatchOp")
        if not 1 <= len(self.ops) <= MAX_PATCH_OPS:
            raise ValueError(f"a patch holds between 1 and {MAX_PATCH_OPS} ops")

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCENE_SCHEMA_VERSION,
            "revision": self.revision,
            "ops": [op.to_payload() for op in self.ops],
        }

    @classmethod
    def from_payload(cls, payload: object) -> ScenePatch:
        _check_schema_version("scene patch", payload)
        data = _check_keys("scene patch", payload, frozenset({"schema_version", "revision", "ops"}))
        ops = _list("ops", data["ops"], MAX_PATCH_OPS)
        return cls(revision=data["revision"], ops=tuple(ScenePatchOp.from_payload(op) for op in ops))


def apply_scene_patch(snapshot: SceneSnapshot, patch: ScenePatch) -> SceneSnapshot:
    """Appliquer un patch à l'instantané de la révision précédente. Fonction pure.

    Un objet remplacé garde sa place dans l'ordre des objets ; un nouvel objet
    est ajouté à la fin. Un archivage retire l'objet et ajoute sa pierre
    tombale à la fin ; au-delà de `MAX_ARCHIVED_IDS`, les plus anciennes sont
    oubliées ici, de façon déterministe. Lève `ValueError` sur un saut de
    révision, un objet archivé réécrit, un archivage ou une suppression de
    relation inconnus : le consommateur doit se resynchroniser.
    """

    if patch.revision != snapshot.revision + 1:
        raise ValueError(f"patch {patch.revision} does not follow revision {snapshot.revision}")
    objects = {item.object_id: item for item in snapshot.objects}
    relations = {item.relation_id: item for item in snapshot.relations}
    archived = dict.fromkeys(snapshot.archived_ids)
    for op in patch.ops:
        if op.object is not None and op.op is PatchOpKind.ARCHIVE_OBJECT:
            if objects.pop(op.object.object_id, None) is None:
                raise ValueError(f"patch archives unknown object {op.object.object_id}")
            archived[op.object.object_id] = None
        elif op.object is not None:
            if op.object.object_id in archived:
                raise ValueError(f"patch rewrites archived object {op.object.object_id}")
            objects[op.object.object_id] = op.object
        elif op.relation is not None:
            relations[op.relation.relation_id] = op.relation
        else:
            if op.relation_id not in relations:
                raise ValueError(f"patch deletes unknown relation {op.relation_id}")
            del relations[op.relation_id]
    return SceneSnapshot(
        scene_id=snapshot.scene_id,
        revision=patch.revision,
        objects=tuple(objects.values()),
        relations=tuple(relations.values()),
        archived_ids=tuple(archived)[-MAX_ARCHIVED_IDS:],
    )


# ------------------------------------------------------------------ règles


class SceneCommandOutcome(StrEnum):
    """Effet d'une commande sur la scène."""

    APPLIED = "applied"
    #: Rien ne change : ni révision ni patch. Rejouer une commande appliquée
    #: donne ce résultat.
    DUPLICATE = "duplicate"
    #: L'acteur n'a pas ce droit (matrice d'autorité, champ ou épinglage).
    REJECTED_AUTHORITY = "rejected_authority"
    #: Commande bien formée mais inapplicable à cette scène (objet inconnu ou
    #: archivé, nature changée, borne atteinte...).
    INVALID = "invalid"


class SceneRefusal(StrEnum):
    """Motif stable d'un refus, pour le journal et l'erreur d'outil du cerveau."""

    # rejected_authority
    OP_NOT_ALLOWED = "op_not_allowed"
    RUNTIME_KIND = "runtime_kind"
    RUNTIME_COMPOSITION = "runtime_composition"
    RUNTIME_RELATION = "runtime_relation"
    #: `runtime` vise un objet créé par `brain` ou `user` (`origin`).
    RUNTIME_ORIGIN = "runtime_origin"
    #: `placed_by=resolver` hors de l'acteur `user` : l'AutoResolver vit dans
    #: le navigateur, qui ne commet que par le proxy utilisateur.
    RESOLVER_ACTOR = "resolver_actor"
    EXECUTION_TRUTH = "execution_truth"
    #: Création d'un `agent`/`job` par `brain` ou `user` : une étoile ne naît
    #: que d'un fait d'exécution.
    EXECUTION_NODE = "execution_node"
    PINNED_BY_USER = "pinned_by_user"
    EXPLICIT_PLACEMENT = "explicit_placement"
    #: `brain`/`user` touchent la topologie d'exécution ou un signal du
    #: runtime : délier un `parent_of` entre nœuds d'exécution ou le lien d'un
    #: signal runtime, ou poser un nouveau `parent_of` entre deux nœuds
    #: d'exécution. Le runtime en est le maître (Décisions 3, 17, Slice 06).
    #: L'utilisateur écarte par l'archivage, le cerveau peut masquer le signal.
    RUNTIME_OWNED = "runtime_owned"
    #: `brain`/`user` créent un objet ou un lien sous un identifiant de la
    #: forme que le runtime fabrique (`is_runtime_reserved_id`) : il
    #: empêcherait la projection de poser l'étoile, le lien ou le signal.
    RESERVED_ID = "reserved_id"
    #: `brain`/`user` posent un `explains` dont `relation_id` vaut `from_id`
    #: depuis un objet qui n'est pas `attention` : cette forme est celle d'un
    #: lien de signal (`is_signal_relation`), réservée aux signaux (Slice 07,
    #: reprise QA) ; sinon un artefact ainsi relié passerait pour un signal.
    SIGNAL_SHAPE = "signal_shape"
    # invalid
    UNKNOWN_OBJECT = "unknown_object"
    OBJECT_ARCHIVED = "object_archived"
    KIND_IMMUTABLE = "kind_immutable"
    INCOMPLETE_OBJECT = "incomplete_object"
    UNPLACED = "unplaced"
    SCENE_FULL = "scene_full"
    RELATION_LIMIT = "relation_limit"
    RELATION_CONFLICT = "relation_conflict"
    #: `archive_many` : un identifiant n'est ni un nœud d'exécution terminé,
    #: ni le signal runtime d'un nœud archivé par la même commande, ni un
    #: signal runtime orphelin (`bulk_archivable`). Toute la commande est
    #: refusée : la sélection confirmée par l'utilisateur ne vaut plus.
    NOT_BULK_ARCHIVABLE = "not_bulk_archivable"
    #: La révision atteindrait `MAX_REVISION`.
    REVISION_EXHAUSTED = "revision_exhausted"


@dataclass(frozen=True, slots=True)
class SceneUpdate:
    """Résultat de `apply_scene_command`.

    `snapshot` est la nouvelle scène si la commande est appliquée, l'instantané
    reçu (le même objet) sinon. `patch` existe exactement quand la commande
    est appliquée, `reason` exactement quand elle est refusée ou invalide.
    """

    outcome: SceneCommandOutcome
    snapshot: SceneSnapshot
    patch: ScenePatch | None = None
    reason: SceneRefusal | None = None

    def __post_init__(self) -> None:
        if (self.patch is not None) != (self.outcome is SceneCommandOutcome.APPLIED):
            raise ValueError("a patch exists exactly when the command is applied")
        refused = self.outcome in (SceneCommandOutcome.REJECTED_AUTHORITY, SceneCommandOutcome.INVALID)
        if (self.reason is not None) != refused:
            raise ValueError("a reason exists exactly when the command is refused")

    @property
    def changed(self) -> bool:
        return self.outcome is SceneCommandOutcome.APPLIED


class _Refused(Exception):
    """Interruption interne d'un plan ; ne sort jamais de `apply_scene_command`."""

    def __init__(self, outcome: SceneCommandOutcome, reason: SceneRefusal) -> None:
        super().__init__(reason.value)
        self.outcome = outcome
        self.reason = reason


def _rejected(reason: SceneRefusal) -> _Refused:
    return _Refused(SceneCommandOutcome.REJECTED_AUTHORITY, reason)


def _invalid(reason: SceneRefusal) -> _Refused:
    return _Refused(SceneCommandOutcome.INVALID, reason)


def apply_scene_command(snapshot: SceneSnapshot, command: SceneCommand) -> SceneUpdate:
    """Appliquer une commande à la scène. Fonction pure.

    Contrôles, dans l'ordre :

    1. matrice `ALLOWED_SCENE_OPS` : une opération hors droits est refusée
       avant même de regarder la scène (`archive` par le cerveau est refusé
       même sur un objet inconnu) ;
    2. existence et disposition des objets visés (`invalid`) ;
    3. autorité sur l'**effet** : `runtime` n'écrit que des nœuds
       d'exécution et des signaux qu'il a lui-même créés (`origin`), jamais un
       champ de composition ni une couche de relation, ne relie que des
       `parent_of` entre nœuds d'exécution et ne délie, en plus, que le lien
       `explains` d'un signal qu'il a posé sur un nœud qu'il a créé (retrait
       du signal, jamais archivage ni masquage) ; seul `runtime` crée un
       `agent`/`job` et change `exec_state` ou `work_ref` ; seul `user`
       déplace ou redimensionne un objet épinglé ; un placement `resolver`
       n'est commis que par `user` et ne remplace ni une épingle ni un
       placement explicite ;
    4. bornes de la scène (`invalid`) ;
    5. si rien ne change, `duplicate` ; sinon la révision avance d'un et le
       patch décrit exactement le changement.

    Une commande qui ne réécrit que des valeurs déjà retenues ne change rien :
    réannoncer la géométrie d'un objet épinglé ou l'`exec_state` connu n'est
    pas un déplacement ni une écriture de vérité.
    """

    _check_instance("snapshot", snapshot, SceneSnapshot)
    _check_instance("command", command, SceneCommand)
    if command.op not in ALLOWED_SCENE_OPS[command.actor]:
        return SceneUpdate(SceneCommandOutcome.REJECTED_AUTHORITY, snapshot, reason=SceneRefusal.OP_NOT_ALLOWED)
    try:
        ops = _PLANNERS[command.op](snapshot, command)
    except _Refused as refused:
        return SceneUpdate(refused.outcome, snapshot, reason=refused.reason)
    if not ops:
        return SceneUpdate(SceneCommandOutcome.DUPLICATE, snapshot)
    if snapshot.revision >= MAX_REVISION:
        return SceneUpdate(SceneCommandOutcome.INVALID, snapshot, reason=SceneRefusal.REVISION_EXHAUSTED)
    patch = ScenePatch(revision=snapshot.revision + 1, ops=tuple(ops))
    return SceneUpdate(SceneCommandOutcome.APPLIED, apply_scene_patch(snapshot, patch), patch)


#: Têtes des identifiants de signal et de lien `parent_of` du projecteur
#: runtime (`jarvis/core/scene_projector.py`), forme courte (`!`) ou hachée (`#`).
_RUNTIME_RESERVED_PREFIXES = ("attention!", "attention#", "parent_of!", "parent_of#")


def is_runtime_reserved_id(identifier: str) -> bool:
    """Vrai pour un identifiant de la forme que le runtime fabrique.

    Étoile : `<source>:<external_id>` ou `<source>#<hachage>:…` (toujours un
    `:`) ; signal : `attention!…` ; lien de parenté : `parent_of!…` (ou leurs
    formes hachées en `#`). `brain` et `user` ne créent rien sous ces formes.
    """

    return ":" in identifier or identifier.startswith(_RUNTIME_RESERVED_PREFIXES)


def is_runtime_owned_relation(snapshot: SceneSnapshot, relation: SceneRelation) -> bool:
    """Lien dont le runtime est le maître : `brain` et `user` ne le délient pas.

    Un `parent_of` entre deux nœuds d'exécution, ou un lien de forme signal
    (`is_signal_relation`) d'un objet `attention` d'origine `runtime` vers un
    nœud d'exécution. Décidé sur la forme et les extrémités : les liens n'ont
    pas d'origine (un nœud d'exécution est toujours d'origine `runtime`).
    """

    source, target = snapshot.get_object(relation.from_id), snapshot.get_object(relation.to_id)
    if source is None or target is None or target.kind not in EXECUTION_KINDS:
        return False
    if relation.kind is RelationKind.PARENT_OF:
        return source.kind in EXECUTION_KINDS
    return (
        is_signal_relation(relation)
        and source.kind is SceneObjectKind.ATTENTION
        and source.origin is SceneActor.RUNTIME
    )


def _require_active(snapshot: SceneSnapshot, object_id: str) -> SceneObject:
    current = snapshot.get_object(object_id)
    if current is not None:
        return current
    if snapshot.is_archived(object_id):
        raise _invalid(SceneRefusal.OBJECT_ARCHIVED)
    raise _invalid(SceneRefusal.UNKNOWN_OBJECT)


def _plan_object_write(
    snapshot: SceneSnapshot,
    actor: SceneActor,
    object_id: str,
    fields: SceneObjectFields,
    *,
    create: bool,
    kind: SceneObjectKind | None = None,
    placed_by: PlacedBy | None = None,
) -> list[ScenePatchOp]:
    """Plan commun des écritures de champs d'objet (upsert, patch, set_*, signal)."""

    current = snapshot.get_object(object_id)
    wanted_kind = kind or fields.kind
    if current is None:
        if snapshot.is_archived(object_id):
            # Même en création : l'identifiant reste pris tant que sa pierre
            # tombale existe, sinon une observation tardive ressusciterait
            # l'étoile archivée.
            raise _invalid(SceneRefusal.OBJECT_ARCHIVED)
        if not create:
            raise _invalid(SceneRefusal.UNKNOWN_OBJECT)
        if wanted_kind is None or fields.category is None:
            raise _invalid(SceneRefusal.INCOMPLETE_OBJECT)
        if actor is not SceneActor.RUNTIME and wanted_kind in EXECUTION_KINDS:
            raise _rejected(SceneRefusal.EXECUTION_NODE)
        if actor is not SceneActor.RUNTIME and is_runtime_reserved_id(object_id):
            raise _rejected(SceneRefusal.RESERVED_ID)
        before = SceneObject(
            object_id=object_id,
            kind=wanted_kind,
            category=fields.category,
            constraints=SceneConstraints(placed_by=PlacedBy(actor.value)),
            origin=actor,
            layer=DEFAULT_LAYERS[wanted_kind],
        )
    else:
        if wanted_kind is not None and wanted_kind is not current.kind:
            raise _invalid(SceneRefusal.KIND_IMMUTABLE)
        before = current

    after = replace(
        before,
        **{name: getattr(fields, name) for name in _WRITABLE_FIELDS if getattr(fields, name) is not None},
    )
    changed = {name for name in _WRITABLE_FIELDS if getattr(after, name) != getattr(before, name)}
    _check_write_authority(actor, before, changed, placed_by)
    if current is None and len(snapshot.objects) >= MAX_SCENE_OBJECTS:
        raise _invalid(SceneRefusal.SCENE_FULL)
    if "geometry" in changed:
        author = placed_by or PlacedBy(actor.value)
        after = replace(after, constraints=replace(after.constraints, placed_by=author))
    if after == current:
        return []
    return [ScenePatchOp(PatchOpKind.PUT_OBJECT, object=after)]


def _check_write_authority(
    actor: SceneActor, before: SceneObject, changed: set[str], placed_by: PlacedBy | None
) -> None:
    if actor is SceneActor.RUNTIME:
        _check_runtime_reach(before, RUNTIME_KINDS, SceneRefusal.RUNTIME_KIND)
        if changed & COMPOSITION_FIELDS:
            raise _rejected(SceneRefusal.RUNTIME_COMPOSITION)
    elif changed & EXECUTION_FIELDS:
        # Décision 17 : l'état d'exécution se lit dans Core, il ne s'écrit pas
        # depuis la scène.
        raise _rejected(SceneRefusal.EXECUTION_TRUTH)
    if "geometry" not in changed:
        return
    if before.constraints.pinned_by_user and (actor is not SceneActor.USER or placed_by is PlacedBy.RESOLVER):
        raise _rejected(SceneRefusal.PINNED_BY_USER)
    if (
        placed_by is PlacedBy.RESOLVER
        and before.geometry is not None
        and before.constraints.placed_by is not PlacedBy.RESOLVER
    ):
        raise _rejected(SceneRefusal.EXPLICIT_PLACEMENT)


def _check_runtime_reach(target: SceneObject, kinds: frozenset[SceneObjectKind], reason: SceneRefusal) -> None:
    """`runtime` n'atteint que des natures permises, et que ce qu'il a créé."""

    if target.kind not in kinds:
        raise _rejected(reason)
    if target.origin is not SceneActor.RUNTIME:
        raise _rejected(SceneRefusal.RUNTIME_ORIGIN)


def _plan_upsert(snapshot: SceneSnapshot, command: SceneCommand) -> list[ScenePatchOp]:
    assert command.object_id is not None and command.fields is not None
    return _plan_object_write(snapshot, command.actor, command.object_id, command.fields, create=True)


def _plan_patch(snapshot: SceneSnapshot, command: SceneCommand) -> list[ScenePatchOp]:
    assert command.object_id is not None and command.fields is not None
    return _plan_object_write(snapshot, command.actor, command.object_id, command.fields, create=False)


def _plan_set_geometry(snapshot: SceneSnapshot, command: SceneCommand) -> list[ScenePatchOp]:
    assert command.object_id is not None
    if command.placed_by is PlacedBy.RESOLVER and command.actor is not SceneActor.USER:
        raise _rejected(SceneRefusal.RESOLVER_ACTOR)
    fields = SceneObjectFields(geometry=command.geometry)
    return _plan_object_write(
        snapshot, command.actor, command.object_id, fields, create=False, placed_by=command.placed_by
    )


def _plan_set_representation(snapshot: SceneSnapshot, command: SceneCommand) -> list[ScenePatchOp]:
    assert command.object_id is not None
    fields = SceneObjectFields(representation=command.representation, geometry=command.geometry)
    return _plan_object_write(snapshot, command.actor, command.object_id, fields, create=False)


def _plan_set_visibility(snapshot: SceneSnapshot, command: SceneCommand) -> list[ScenePatchOp]:
    assert command.object_id is not None
    fields = SceneObjectFields(visibility=command.visibility)
    return _plan_object_write(snapshot, command.actor, command.object_id, fields, create=False)


def _plan_pin(snapshot: SceneSnapshot, command: SceneCommand, *, pinned: bool) -> list[ScenePatchOp]:
    assert command.object_id is not None
    current = _require_active(snapshot, command.object_id)
    if current.constraints.pinned_by_user is pinned:
        return []
    if pinned and current.geometry is None:
        raise _invalid(SceneRefusal.UNPLACED)
    updated = replace(current, constraints=replace(current.constraints, pinned_by_user=pinned))
    return [ScenePatchOp(PatchOpKind.PUT_OBJECT, object=updated)]


#: États d'exécution terminaux : un travail Core terminé ne repart jamais
#: (`ALLOWED_WORK_TRANSITIONS`), l'archivage groupé ne peut donc pas retirer
#: un travail qui reprendrait.
TERMINAL_EXEC_STATES = frozenset({ExecState.COMPLETED, ExecState.CANCELLED, ExecState.FAILED, ExecState.INTERRUPTED})


def signal_owners(snapshot: SceneSnapshot) -> dict[str, str | None]:
    """Étoile de chaque signal runtime actif (`attention` d'origine `runtime`), ou `None` (orphelin).

    L'étoile d'un signal est la cible de son lien de signal vivant quand elle
    est un nœud d'exécution actif, sinon le premier nœud d'exécution actif qui
    porte le même travail Core (`work_ref` : source et identifiant externe ;
    `work_id` peut arriver plus tard) : un signal retiré, sans lien, reste
    ainsi rattaché à son étoile. Calculé en une passe pour toute la scène.
    """

    objects = {item.object_id: item for item in snapshot.objects}
    relations = {relation.relation_id: relation for relation in snapshot.relations}
    stars_by_work: dict[tuple[str, str], str] = {}
    for item in snapshot.objects:
        if item.kind in EXECUTION_KINDS and item.work_ref is not None:
            stars_by_work.setdefault((item.work_ref.source, item.work_ref.external_id), item.object_id)
    owners: dict[str, str | None] = {}
    for item in snapshot.objects:
        if item.kind is not SceneObjectKind.ATTENTION or item.origin is not SceneActor.RUNTIME:
            continue
        relation = relations.get(item.object_id)
        target = objects.get(relation.to_id) if relation is not None and is_signal_relation(relation) else None
        if target is not None and target.kind in EXECUTION_KINDS:
            owners[item.object_id] = target.object_id
        elif item.work_ref is not None:
            owners[item.object_id] = stars_by_work.get((item.work_ref.source, item.work_ref.external_id))
        else:
            owners[item.object_id] = None
    return owners


def runtime_signals_of(snapshot: SceneSnapshot, object_id: str, owners: dict[str, str | None] | None = None) -> tuple[str, ...]:
    """Signaux runtime d'une étoile active, dans l'ordre de la scène (Slice 08, cascade d'archivage).

    Vide pour tout objet qui n'est pas un nœud d'exécution : un objet
    `attention` du cerveau ou de l'utilisateur n'est jamais emporté.
    """

    owners = signal_owners(snapshot) if owners is None else owners
    return tuple(signal_id for signal_id, owner in owners.items() if owner == object_id)


def bulk_archivable(snapshot: SceneSnapshot, object_id: str, selected: frozenset[str] = frozenset(),
                    owners: dict[str, str | None] | None = None) -> bool:
    """Règle de l'archivage groupé (`archive_many`) pour un objet actif.

    Vrai pour un nœud d'exécution (`agent`, `job`) dans un état terminal
    (`TERMINAL_EXEC_STATES`) ; pour un signal runtime dont l'étoile est dans
    `selected` et archivable, ou qui n'a plus d'étoile active (orphelin) ; pour
    un **artefact orphelin** (Slice 07, reprise QA : `is_orphan_artifact`, sans
    lien `explains` vers un objet actif). Jamais un travail en cours, en
    attente, bloqué ou d'état inconnu, jamais un artefact encore relié, jamais
    une autre création du cerveau ou de l'utilisateur.
    """

    item = snapshot.get_object(object_id)
    if item is None:
        return False
    if item.kind in EXECUTION_KINDS:
        return item.exec_state in TERMINAL_EXEC_STATES
    if item.kind is SceneObjectKind.ARTIFACT:
        return is_orphan_artifact(snapshot, object_id)
    owners = signal_owners(snapshot) if owners is None else owners
    if object_id not in owners:
        return False
    owner_id = owners[object_id]
    if owner_id is None:
        return True
    owner = snapshot.get_object(owner_id)
    return owner_id in selected and owner is not None and owner.exec_state in TERMINAL_EXEC_STATES


def is_orphan_artifact(snapshot: SceneSnapshot, object_id: str) -> bool:
    """Artefact actif qui n'explique plus rien : aucun lien `explains` vers un objet actif.

    C'est l'état d'un artefact dont l'utilisateur a archivé l'étoile (l'archivage
    emporte les liens, jamais l'artefact), ou d'un artefact jamais relié.
    L'archivage groupé peut le prendre (Slice 07, reprise QA) ; un artefact
    encore relié ne l'est jamais.
    """

    item = snapshot.get_object(object_id)
    if item is None or item.kind is not SceneObjectKind.ARTIFACT:
        return False
    return not any(
        relation.kind is RelationKind.EXPLAINS and relation.from_id == object_id
        for relation in snapshot.relations
    )


def _archive_ops(snapshot: SceneSnapshot, object_ids: list[str]) -> list[ScenePatchOp]:
    """Archiver des objets actifs distincts, puis supprimer une fois chaque relation qui les touche."""

    objects = {item.object_id: item for item in snapshot.objects}
    gone = set(object_ids)
    ops = [
        ScenePatchOp(PatchOpKind.ARCHIVE_OBJECT, object=replace(objects[object_id], disposition=Disposition.ARCHIVED))
        for object_id in object_ids
    ]
    ops.extend(
        ScenePatchOp(PatchOpKind.DELETE_RELATION, relation_id=relation.relation_id)
        for relation in snapshot.relations
        if relation.from_id in gone or relation.to_id in gone
    )
    return ops


def _with_cascade(snapshot: SceneSnapshot, object_id: str, owners: dict[str, str | None], into: dict[str, None]) -> None:
    """Ajouter un objet précédé de ses signaux runtime.

    Les signaux d'abord : la pierre tombale de l'étoile est la plus récente,
    donc la dernière oubliée (`MAX_ARCHIVED_IDS`) ; tant qu'elle vit, le
    projecteur ne touche ni l'étoile ni son signal.
    """

    for signal_id in runtime_signals_of(snapshot, object_id, owners):
        into.setdefault(signal_id, None)
    into.setdefault(object_id, None)


def _plan_archive(snapshot: SceneSnapshot, command: SceneCommand) -> list[ScenePatchOp]:
    """Archiver un objet ; une étoile emporte ses signaux runtime, vivants ou retirés (Slice 08)."""

    assert command.object_id is not None
    if snapshot.is_archived(command.object_id):
        return []
    _require_active(snapshot, command.object_id)
    ordered: dict[str, None] = {}
    _with_cascade(snapshot, command.object_id, signal_owners(snapshot), ordered)
    return _archive_ops(snapshot, list(ordered))


def _plan_archive_many(snapshot: SceneSnapshot, command: SceneCommand) -> list[ScenePatchOp]:
    """Archivage groupé : tout ou rien, une révision (Slice 08).

    Un identifiant déjà archivé ne compte pas (un autre onglet a été plus
    rapide) ; un identifiant inconnu (`unknown_object`) ou hors règle
    (`not_bulk_archivable`, voir `bulk_archivable`) refuse **toute** la
    commande : l'utilisateur a confirmé un compte, une sélection devenue
    fausse se recalcule et se reconfirme au lieu de s'appliquer en partie.
    """

    assert command.object_ids is not None
    active = [object_id for object_id in command.object_ids if not snapshot.is_archived(object_id)]
    selected = frozenset(active)
    owners = signal_owners(snapshot)
    for object_id in active:
        _require_active(snapshot, object_id)
        if not bulk_archivable(snapshot, object_id, selected, owners):
            raise _invalid(SceneRefusal.NOT_BULK_ARCHIVABLE)
    ordered: dict[str, None] = {}
    for object_id in active:
        _with_cascade(snapshot, object_id, owners, ordered)
    return _archive_ops(snapshot, list(ordered))


def _plan_relation_put(
    snapshot: SceneSnapshot, relation: SceneRelation, *, layer_announced: bool
) -> list[ScenePatchOp]:
    """Plan commun d'une relation posée par `link` ou `attach_signal`.

    Même identifiant, autres extrémités : conflit. Mêmes extrémités : seule la
    couche peut changer, et seulement si la commande l'annonce ; sinon la
    couche retenue (choisie par le cerveau ou l'utilisateur) est gardée.
    """

    existing = snapshot.get_relation(relation.relation_id)
    if existing is None:
        if len(snapshot.relations) >= MAX_SCENE_RELATIONS:
            raise _invalid(SceneRefusal.RELATION_LIMIT)
        return [ScenePatchOp(PatchOpKind.PUT_RELATION, relation=relation)]
    if existing.endpoints != relation.endpoints:
        raise _invalid(SceneRefusal.RELATION_CONFLICT)
    if not layer_announced or existing.layer == relation.layer:
        return []
    return [ScenePatchOp(PatchOpKind.PUT_RELATION, relation=relation)]


def _plan_link(snapshot: SceneSnapshot, command: SceneCommand) -> list[ScenePatchOp]:
    relation = command.relation
    assert relation is not None
    runtime = command.actor is SceneActor.RUNTIME
    if runtime:
        if relation.kind is not RelationKind.PARENT_OF:
            raise _rejected(SceneRefusal.RUNTIME_RELATION)
        if relation.layer != DEFAULT_RELATION_LAYER:
            # La couche est de la composition : `runtime` n'en annonce pas.
            raise _rejected(SceneRefusal.RUNTIME_COMPOSITION)
    source = _require_active(snapshot, relation.from_id)
    target = _require_active(snapshot, relation.to_id)
    if runtime:
        _check_runtime_reach(source, EXECUTION_KINDS, SceneRefusal.RUNTIME_RELATION)
        _check_runtime_reach(target, EXECUTION_KINDS, SceneRefusal.RUNTIME_RELATION)
    elif snapshot.get_relation(relation.relation_id) is None:
        # Changer la couche d'un lien runtime existant reste permis ; créer
        # ne l'est pas sous un identifiant du runtime, ni pour une parenté
        # entre nœuds d'exécution : une fausse topologie ne pourrait plus être
        # retirée (`runtime_owned` au `unlink`).
        if is_runtime_reserved_id(relation.relation_id):
            raise _rejected(SceneRefusal.RESERVED_ID)
        if relation.kind is RelationKind.PARENT_OF and source.kind in EXECUTION_KINDS and target.kind in EXECUTION_KINDS:
            raise _rejected(SceneRefusal.RUNTIME_OWNED)
        if is_signal_relation(relation) and source.kind is not SceneObjectKind.ATTENTION:
            raise _rejected(SceneRefusal.SIGNAL_SHAPE)
    return _plan_relation_put(snapshot, relation, layer_announced=not runtime)


def _plan_unlink(snapshot: SceneSnapshot, command: SceneCommand) -> list[ScenePatchOp]:
    assert command.relation_id is not None
    existing = snapshot.get_relation(command.relation_id)
    if existing is None:
        # Retirer ce qui n'existe plus ne change rien : un unlink rejoué est
        # un doublon, pas une erreur.
        return []
    if command.actor is SceneActor.RUNTIME:
        if existing.kind is RelationKind.PARENT_OF:
            source_kinds = EXECUTION_KINDS
        elif is_signal_relation(existing):
            # Retrait d'un signal (Slice 04, amendement F1) : `runtime` retire
            # le lien d'un signal qu'il a lui-même posé sur une étoile qu'il a
            # créée. L'objet `attention` reste, sans lien : ni archivage, ni
            # visibilité, ni géométrie ne sont accordés.
            source_kinds = frozenset({SceneObjectKind.ATTENTION})
        else:
            raise _rejected(SceneRefusal.RUNTIME_RELATION)
        _check_runtime_reach(_require_active(snapshot, existing.from_id), source_kinds, SceneRefusal.RUNTIME_RELATION)
        _check_runtime_reach(_require_active(snapshot, existing.to_id), EXECUTION_KINDS, SceneRefusal.RUNTIME_RELATION)
    elif is_runtime_owned_relation(snapshot, existing):
        raise _rejected(SceneRefusal.RUNTIME_OWNED)
    return [ScenePatchOp(PatchOpKind.DELETE_RELATION, relation_id=command.relation_id)]


def is_signal_relation(relation: SceneRelation) -> bool:
    """Vrai pour le lien `explains` posé par `attach_signal` : il porte l'identifiant du signal."""

    return relation.kind is RelationKind.EXPLAINS and relation.relation_id == relation.from_id


def is_live_signal(snapshot: SceneSnapshot, object_id: str) -> bool:
    """Un signal est **vivant** exactement tant que son lien `explains` existe.

    Retirer un signal (`unlink` de ce lien) le rend inactif sans le supprimer :
    l'objet `attention` reste dans la scène, et son `exec_state` dit l'état du
    travail au moment du retrait. `attach_signal` sur le même identifiant le
    ranime.
    """

    relation = snapshot.get_relation(object_id)
    return relation is not None and is_signal_relation(relation)


def _plan_attach_signal(snapshot: SceneSnapshot, command: SceneCommand) -> list[ScenePatchOp]:
    assert command.object_id is not None and command.fields is not None and command.target_id is not None
    target = _require_active(snapshot, command.target_id)
    if command.actor is SceneActor.RUNTIME:
        _check_runtime_reach(target, EXECUTION_KINDS, SceneRefusal.RUNTIME_KIND)
    ops = _plan_object_write(
        snapshot, command.actor, command.object_id, command.fields, create=True, kind=SceneObjectKind.ATTENTION
    )
    if (command.actor is not SceneActor.RUNTIME and snapshot.get_relation(command.object_id) is None
            and is_runtime_reserved_id(command.object_id)):
        # Le lien porte l'identifiant du signal : ranimer un signal runtime
        # retiré revient au runtime.
        raise _rejected(SceneRefusal.RESERVED_ID)
    relation = SceneRelation(
        relation_id=command.object_id,
        kind=RelationKind.EXPLAINS,
        from_id=command.object_id,
        to_id=command.target_id,
    )
    return [*ops, *_plan_relation_put(snapshot, relation, layer_announced=False)]


def _plan_attach_artifact(snapshot: SceneSnapshot, command: SceneCommand) -> list[ScenePatchOp]:
    """Artefact et lien `explains` vers sa cible, tout ou rien (Slice 07).

    Mêmes règles qu'un `upsert_object` d'artefact suivi d'un `link` de
    `explains`, mais dans un seul patch : cible inconnue ou archivée, lien en
    conflit, borne de liens, identifiant réservé, épingle ou scène pleine
    refusent **toute** la commande, jamais d'artefact orphelin. Le cerveau ne
    peut rien retirer (Décision 14) : une compensation après coup n'existe
    pas pour lui. Relancer la même commande ne change rien (`duplicate`).
    """

    assert command.object_id is not None and command.fields is not None
    assert command.target_id is not None and command.relation_id is not None
    _require_active(snapshot, command.target_id)
    ops = _plan_object_write(
        snapshot, command.actor, command.object_id, command.fields, create=True, kind=SceneObjectKind.ARTIFACT
    )
    if snapshot.get_relation(command.relation_id) is None and is_runtime_reserved_id(command.relation_id):
        raise _rejected(SceneRefusal.RESERVED_ID)
    relation = SceneRelation(
        relation_id=command.relation_id,
        kind=RelationKind.EXPLAINS,
        from_id=command.object_id,
        to_id=command.target_id,
    )
    return [*ops, *_plan_relation_put(snapshot, relation, layer_announced=False)]


_PLANNERS: dict[SceneOp, Callable[[SceneSnapshot, SceneCommand], list[ScenePatchOp]]] = {
    SceneOp.UPSERT_OBJECT: _plan_upsert,
    SceneOp.PATCH_OBJECT: _plan_patch,
    SceneOp.SET_GEOMETRY: _plan_set_geometry,
    SceneOp.SET_REPRESENTATION: _plan_set_representation,
    SceneOp.SET_VISIBILITY: _plan_set_visibility,
    SceneOp.PIN: lambda snapshot, command: _plan_pin(snapshot, command, pinned=True),
    SceneOp.UNPIN: lambda snapshot, command: _plan_pin(snapshot, command, pinned=False),
    SceneOp.LINK: _plan_link,
    SceneOp.UNLINK: _plan_unlink,
    SceneOp.ARCHIVE: _plan_archive,
    SceneOp.ARCHIVE_MANY: _plan_archive_many,
    SceneOp.ATTACH_SIGNAL: _plan_attach_signal,
    SceneOp.ATTACH_ARTIFACT: _plan_attach_artifact,
}

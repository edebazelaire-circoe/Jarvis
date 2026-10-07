"""Presentation Studio : le contrat durable d'une Presentation (handoff jarvis-interactive-presentation-studio, Slice 02).

Une *Presentation* est l'agrégat créatif ; une *PresentationVariant* en est une
branche. Ce module ne décrit que l'**état d'édition persistant**, par
références : il ne copie ni la définition d'un prefab, ni une scène, ni une
direction artistique, ni une partition (Slices 04, 09, 10), il les nomme.

Ce qui y vit (contrat : `docs/presentation-studio.md` › *Presentation contract*) :

- `Presentation` : identité (`pst_`), titre, métadonnées, variante active,
  compteur monotone de numéros de variante, index des variantes, références de
  ressources (`ResourceReference`, jamais un contenu), `revision`.
- `PresentationVariant` : identité (`psv_`), numéro d'affichage, titre, parent
  éventuel, scènes logiques ordonnées (`StudioScene` minimale : `scene_id` +
  `PrefabRef` exact `(id, version)`), références vers la direction artistique
  (`psd_`) et la partition (`psr_`), `revision`.

Ce qui n'y vit **jamais** (état d'exécution) : identifiant d'objet de la scène
globale, fenêtre, DOM, cadre, position de lecture, progression de révélation,
détours, pile de ressources auxiliaires, pile d'annulation. Toute clé inconnue
est refusée ; si elle porte un nom d'état d'exécution connu, le refus a son
propre code (`runtime_state_refused`) pour qu'on le voie.

Versionnage : chaque document porte `{schema, schema_version}`. Une version
**plus récente** que `SCHEMA_VERSION` est refusée (`unsupported_schema_version`),
jamais lue au mieux ni réécrite ; une version plus ancienne passe par la chaîne
`UPGRADES` (vide à la v1). Pas de `_MIGRATIONS` SQLite : le stockage est un
magasin de fichiers (décision (a), `docs/presentation-studio.md`).

Pur : aucune E/S. Le magasin est `jarvis.ports.presentation_studio`, le service
`jarvis.core.presentation_studio_service`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import json
import re
import secrets
from typing import Any

from jarvis.domain.prefab import MAX_TITLE_CHARS, PrefabDefinitionError, PrefabRef
from jarvis.domain.presentation_working_set import ResourceKind, ResourceReference

SCHEMA_PRESENTATION = "jarvis.presentation_studio.presentation"
SCHEMA_VARIANT = "jarvis.presentation_studio.variant"
SCHEMA_VERSION = 1

#: Bornes (toute collection est bornée, comme `scene.py`).
MAX_TITLE = MAX_TITLE_CHARS
MAX_SCENES = 64
MAX_RESOURCES = 64
MAX_VARIANTS = 64
MAX_VARIANT_COUNTER = 10_000
MAX_REVISION = 2**31 - 1
MAX_PRESENTATIONS = 256
#: Taille d'un document sur disque ou reçu (échappement JSON compris).
MAX_DOCUMENT_BYTES = 256 * 1024
MAX_ERROR_CHARS = 300
MAX_VALIDATION_ERRORS = 20

_HEX32 = "[0-9a-f]{32}"
_HEX12 = "[0-9a-f]{12}"
PRESENTATION_ID = re.compile(rf"pst_{_HEX32}\Z")
VARIANT_ID = re.compile(rf"psv_{_HEX32}\Z")
SCENE_ID = re.compile(rf"pss_{_HEX12}\Z")
ART_DIRECTION_ID = re.compile(rf"psd_{_HEX12}\Z")
SCORE_ID = re.compile(rf"psr_{_HEX12}\Z")
_STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z")

#: Noms d'état d'exécution : refusés avec leur propre code (jamais persistés).
RUNTIME_KEYS = frozenset({
    "object_id", "window_id", "stage_object_id", "scene_object_id", "element", "element_id", "dom", "dom_id", "node",
    "handle", "iframe", "frame", "port", "session_id", "playback", "playback_state", "position", "score_position",
    "reveal", "reveal_progress", "detour", "detours", "aux_resources", "auxiliary_resources", "undo", "redo",
    "undo_stack", "redo_stack", "cursor", "focus", "selection", "selected",
})


class PresentationStudioErrorCode(StrEnum):
    #: Entrée refusée (corps de requête, charge utile) : l'appelant corrige.
    INVALID_PRESENTATION = "presentation_studio_invalid"
    #: Clé d'état d'exécution (handle, DOM, position de lecture...) dans un document persistant.
    RUNTIME_STATE_REFUSED = "presentation_studio_runtime_state_refused"
    #: Document stocké plus récent que ce Core sait lire : conservé tel quel, jamais réécrit.
    UNSUPPORTED_SCHEMA_VERSION = "presentation_studio_unsupported_schema_version"
    #: Document stocké illisible ou incohérent : panne de données, pas une demande refusée.
    CORRUPT_DOCUMENT = "presentation_studio_corrupt_document"
    UNKNOWN_PRESENTATION = "presentation_studio_unknown_presentation"
    UNKNOWN_VARIANT = "presentation_studio_unknown_variant"
    ALREADY_EXISTS = "presentation_studio_already_exists"
    #: `expected_revision` différent de la révision stockée : relire puis recommencer.
    STALE_REVISION = "presentation_studio_stale_revision"
    LIMIT_REACHED = "presentation_studio_limit_reached"
    #: Disque, lien/jonction refusé, racine indisponible.
    STORAGE_IO = "presentation_studio_storage_io"


_C = PresentationStudioErrorCode
HTTP_STATUS: Mapping[PresentationStudioErrorCode, int] = {
    _C.INVALID_PRESENTATION: 400,
    _C.RUNTIME_STATE_REFUSED: 400,
    _C.UNSUPPORTED_SCHEMA_VERSION: 409,
    _C.CORRUPT_DOCUMENT: 409,
    _C.UNKNOWN_PRESENTATION: 404,
    _C.UNKNOWN_VARIANT: 404,
    _C.ALREADY_EXISTS: 409,
    _C.STALE_REVISION: 409,
    _C.LIMIT_REACHED: 409,
    _C.STORAGE_IO: 500,
}


def clip(message: str, limit: int = MAX_ERROR_CHARS) -> str:
    return message if len(message) <= limit else message[: limit - 1] + "…"


class PresentationStudioError(Exception):
    """Refus ou panne codés ; `message` ≤ `MAX_ERROR_CHARS`, sans chemin absolu."""

    def __init__(self, code: PresentationStudioErrorCode | str, message: str) -> None:
        self.code = PresentationStudioErrorCode(code)
        self.message = clip(message)
        self.status = HTTP_STATUS[self.code]
        super().__init__(f"{self.code.value}: {self.message}")


def _fail(message: str) -> PresentationStudioError:
    return PresentationStudioError(_C.INVALID_PRESENTATION, message)


# ------------------------------------------------------------------ ids et horodatages

def new_presentation_id() -> str:
    return "pst_" + secrets.token_hex(16)


def new_variant_id() -> str:
    return "psv_" + secrets.token_hex(16)


def new_scene_id() -> str:
    return "pss_" + secrets.token_hex(6)


def new_art_direction_id() -> str:
    return "psd_" + secrets.token_hex(6)


def new_score_id() -> str:
    return "psr_" + secrets.token_hex(6)


def is_presentation_id(value: object) -> bool:
    return isinstance(value, str) and bool(PRESENTATION_ID.fullmatch(value))


def is_variant_id(value: object) -> bool:
    return isinstance(value, str) and bool(VARIANT_ID.fullmatch(value))


def stamp(moment: datetime) -> str:
    """`2026-10-07T12:00:00.000000Z` : UTC, microsecondes fixes (comparable en texte)."""

    if moment.tzinfo is None or moment.utcoffset() is None:
        raise _fail("timestamps must be timezone-aware")
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _check_stamp(name: str, value: object) -> None:
    if not isinstance(value, str) or not _STAMP.fullmatch(value):
        raise _fail(f"{name} must be a UTC timestamp like 2026-10-07T12:00:00.000000Z")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        raise _fail(f"{name} is not a real date") from None


def _check_id(name: str, value: object, pattern: re.Pattern[str], *, optional: bool = False) -> None:
    if value is None and optional:
        return
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise _fail(f"{name} is not a valid id ({pattern.pattern.split('_')[0]}_...)")


def _check_title(name: str, value: object) -> None:
    if not isinstance(value, str):
        raise _fail(f"{name} must be a string")
    if not value.strip() or value != value.strip():
        raise _fail(f"{name} must be non-empty without surrounding spaces")
    if len(value) > MAX_TITLE:
        raise _fail(f"{name} exceeds {MAX_TITLE} characters")
    if not value.isprintable():
        raise _fail(f"{name} must be a single printable line")


def _check_int(name: str, value: object, low: int, high: int) -> None:
    if type(value) is not int or not low <= value <= high:
        raise _fail(f"{name} must be an integer in {low}..{high}")


def _exact_keys(raw: object, where: str, required: set[str], optional: frozenset[str] = frozenset()) -> dict[str, Any]:
    """Objet exact : ni clé manquante ni clé inconnue. Un nom d'état d'exécution a son propre code."""

    if not isinstance(raw, dict):
        raise _fail(f"{where} must be a JSON object")
    keys = set(raw)
    runtime = sorted(keys & RUNTIME_KEYS)
    if runtime:
        raise PresentationStudioError(_C.RUNTIME_STATE_REFUSED, f"{where}: runtime-only state is never stored: "
                                                                 f"{', '.join(runtime[:6])}")
    unknown = keys - required - optional
    if unknown:
        raise _fail(f"{where}: unknown keys {', '.join(sorted(map(str, unknown))[:6])}")
    missing = required - keys
    if missing:
        raise _fail(f"{where}: missing keys {', '.join(sorted(missing)[:6])}")
    return raw


# ------------------------------------------------------------------ références

@dataclass(frozen=True, slots=True)
class SceneRef:
    """Scène logique : son id stable et le prefab **exact** qui la rend. Rien d'autre (pas de props : Slice 04)."""

    scene_id: str
    prefab: PrefabRef

    def __post_init__(self) -> None:
        _check_id("scene_id", self.scene_id, SCENE_ID)
        if not isinstance(self.prefab, PrefabRef):
            raise _fail("scene prefab must be a PrefabRef")

    def to_dict(self) -> dict[str, Any]:
        return {"scene_id": self.scene_id, "prefab": self.prefab.to_dict()}

    @classmethod
    def from_dict(cls, raw: object, where: str = "scene") -> SceneRef:
        data = _exact_keys(raw, where, {"scene_id", "prefab"})
        try:
            prefab = PrefabRef.from_dict(data["prefab"], where=f"{where}.prefab")
        except PrefabDefinitionError as exc:
            raise _fail(f"{where}: {exc}") from None
        return cls(data["scene_id"], prefab)


#: Ressources dont le localisateur est un identifiant d'objet de la scène globale : un handle d'exécution.
_REFUSED_RESOURCE_KINDS = frozenset({ResourceKind.SCENE_OBJECT})


def resource_to_dict(resource: ResourceReference) -> dict[str, Any]:
    return {"kind": resource.kind.value, "locator": resource.locator, "title": resource.title}


def resource_from_dict(raw: object, where: str = "resource") -> ResourceReference:
    """`{kind, locator, title}` : le `descriptor` de `ResourceReference` (charge de données) n'est pas stocké ici."""

    data = _exact_keys(raw, where, {"kind", "locator"}, frozenset({"title"}))
    try:
        kind = ResourceKind(data["kind"])
    except (ValueError, TypeError):
        raise _fail(f"{where}.kind is not a resource kind") from None
    if kind in _REFUSED_RESOURCE_KINDS or str(data["locator"]).lower().startswith("scene:"):
        raise PresentationStudioError(_C.RUNTIME_STATE_REFUSED,
                                      f"{where}: a scene object id is a runtime handle, never a stored reference")
    for name in ("locator", "title"):
        text = data.get(name, "")
        if isinstance(text, str):
            try:
                text.encode("utf-8")
            except UnicodeEncodeError:
                raise _fail(f"{where}.{name} holds a character that cannot be stored (lone surrogate)") from None
    try:
        return ResourceReference(kind, data["locator"], data.get("title", ""))
    except (ValueError, TypeError) as exc:
        raise _fail(f"{where}: {getattr(exc, 'message', None) or exc}") from None


def _resources(value: object) -> tuple[ResourceReference, ...]:
    if not isinstance(value, (list, tuple)):
        raise _fail("resources must be a list")
    if len(value) > MAX_RESOURCES:
        raise _fail(f"resources exceed {MAX_RESOURCES}")
    items = tuple(item if isinstance(item, ResourceReference) else resource_from_dict(item, f"resources[{i}]")
                  for i, item in enumerate(value))
    keys = [(item.kind, item.locator) for item in items]
    if len(set(keys)) != len(keys):
        raise _fail("resources hold the same reference twice")
    return items


def _scenes(value: object) -> tuple[SceneRef, ...]:
    if not isinstance(value, (list, tuple)):
        raise _fail("scenes must be a list")
    if len(value) > MAX_SCENES:
        raise _fail(f"scenes exceed {MAX_SCENES}")
    items = tuple(item if isinstance(item, SceneRef) else SceneRef.from_dict(item, f"scenes[{i}]")
                  for i, item in enumerate(value))
    ids = [item.scene_id for item in items]
    if len(set(ids)) != len(ids):
        raise _fail("scenes hold the same scene_id twice")
    return items


# ------------------------------------------------------------------ agrégat

@dataclass(frozen=True, slots=True)
class VariantIndexEntry:
    variant_id: str
    variant_number: int

    def __post_init__(self) -> None:
        _check_id("variant_id", self.variant_id, VARIANT_ID)
        _check_int("variant_number", self.variant_number, 1, MAX_VARIANT_COUNTER)


@dataclass(frozen=True, slots=True)
class Presentation:
    presentation_id: str
    title: str
    active_variant_id: str
    #: Dernier numéro attribué : monotone, jamais réutilisé (Slice 16 l'incrémente).
    variant_counter: int
    variants: tuple[VariantIndexEntry, ...]
    resources: tuple[ResourceReference, ...]
    revision: int
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        _check_id("presentation_id", self.presentation_id, PRESENTATION_ID)
        _check_title("title", self.title)
        _check_id("active_variant_id", self.active_variant_id, VARIANT_ID)
        _check_int("variant_counter", self.variant_counter, 1, MAX_VARIANT_COUNTER)
        object.__setattr__(self, "variants", tuple(self.variants))
        object.__setattr__(self, "resources", _resources(self.resources))
        if not 1 <= len(self.variants) <= MAX_VARIANTS:
            raise _fail(f"a presentation holds 1..{MAX_VARIANTS} variants")
        if not all(isinstance(entry, VariantIndexEntry) for entry in self.variants):
            raise _fail("variants must be VariantIndexEntry values")
        ids = [entry.variant_id for entry in self.variants]
        numbers = [entry.variant_number for entry in self.variants]
        if len(set(ids)) != len(ids) or len(set(numbers)) != len(numbers):
            raise _fail("variant ids and numbers must be unique")
        if self.active_variant_id not in ids:
            raise _fail("active_variant_id is not in the variant index")
        if max(numbers) > self.variant_counter:
            raise _fail("variant_counter is below an indexed variant_number")
        _check_int("revision", self.revision, 1, MAX_REVISION)
        _check_stamp("created_at", self.created_at)
        _check_stamp("updated_at", self.updated_at)

    def to_document(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_PRESENTATION, "schema_version": SCHEMA_VERSION,
            "presentation_id": self.presentation_id, "title": self.title,
            "active_variant_id": self.active_variant_id, "variant_counter": self.variant_counter,
            "variants": [{"variant_id": e.variant_id, "variant_number": e.variant_number} for e in self.variants],
            "resources": [resource_to_dict(r) for r in self.resources],
            "revision": self.revision, "created_at": self.created_at, "updated_at": self.updated_at,
        }

    def summary(self) -> dict[str, Any]:
        return {"presentation_id": self.presentation_id, "title": self.title,
                "active_variant_id": self.active_variant_id, "variant_count": len(self.variants),
                "resource_count": len(self.resources), "revision": self.revision, "updated_at": self.updated_at}


@dataclass(frozen=True, slots=True)
class PresentationVariant:
    presentation_id: str
    variant_id: str
    variant_number: int
    title: str
    #: Seule trace du graphe ici ; les opérations de graphe sont à la Slice 16.
    parent_variant_id: str | None
    scenes: tuple[SceneRef, ...]
    art_direction_id: str | None
    score_id: str | None
    revision: int
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        _check_id("presentation_id", self.presentation_id, PRESENTATION_ID)
        _check_id("variant_id", self.variant_id, VARIANT_ID)
        _check_int("variant_number", self.variant_number, 1, MAX_VARIANT_COUNTER)
        _check_title("title", self.title)
        _check_id("parent_variant_id", self.parent_variant_id, VARIANT_ID, optional=True)
        if self.parent_variant_id == self.variant_id:
            raise _fail("a variant cannot be its own parent")
        object.__setattr__(self, "scenes", _scenes(self.scenes))
        _check_id("art_direction_id", self.art_direction_id, ART_DIRECTION_ID, optional=True)
        _check_id("score_id", self.score_id, SCORE_ID, optional=True)
        _check_int("revision", self.revision, 1, MAX_REVISION)
        _check_stamp("created_at", self.created_at)
        _check_stamp("updated_at", self.updated_at)

    def to_document(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VARIANT, "schema_version": SCHEMA_VERSION,
            "presentation_id": self.presentation_id, "variant_id": self.variant_id,
            "variant_number": self.variant_number, "title": self.title, "parent_variant_id": self.parent_variant_id,
            "scenes": [scene.to_dict() for scene in self.scenes],
            "art_direction_id": self.art_direction_id, "score_id": self.score_id,
            "revision": self.revision, "created_at": self.created_at, "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class PresentationView:
    """Une Presentation et toutes ses variantes, cohérentes entre elles (`check_consistency`)."""

    presentation: Presentation
    variants: tuple[PresentationVariant, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        check_consistency(self.presentation, self.variants)

    def active_variant(self) -> PresentationVariant:
        return next(v for v in self.variants if v.variant_id == self.presentation.active_variant_id)

    def to_dict(self) -> dict[str, Any]:
        return {"presentation": self.presentation.to_document(),
                "variants": [variant.to_document() for variant in self.variants]}


def check_consistency(presentation: Presentation, variants: tuple[PresentationVariant, ...]) -> None:
    """L'index de la Presentation et ses variantes disent la même chose."""

    by_id = {variant.variant_id: variant for variant in variants}
    if len(by_id) != len(variants):
        raise _fail("the same variant appears twice")
    index = {entry.variant_id: entry.variant_number for entry in presentation.variants}
    if set(by_id) != set(index):
        raise _fail("the variant index and the variants differ")
    for variant in variants:
        if variant.presentation_id != presentation.presentation_id:
            raise _fail(f"variant {variant.variant_id} belongs to another presentation")
        if variant.variant_number != index[variant.variant_id]:
            raise _fail(f"variant {variant.variant_id} number differs from the index")
        if variant.parent_variant_id is not None and variant.parent_variant_id not in index:
            raise _fail(f"variant {variant.variant_id} has a parent outside the presentation")
    parents = {variant.variant_id: variant.parent_variant_id for variant in variants}
    for start in parents:
        seen, current = {start}, parents[start]
        while current is not None:
            if current in seen:
                raise _fail(f"variant {start} is part of a parent cycle")
            seen.add(current)
            current = parents.get(current)


def new_presentation(title: str, now: datetime, *,
                     presentation_id: str | None = None, variant_id: str | None = None) -> PresentationView:
    """Presentation neuve : variante n° 1 vide, active."""

    at = stamp(now)
    pid, vid = presentation_id or new_presentation_id(), variant_id or new_variant_id()
    presentation = Presentation(pid, title, vid, 1, (VariantIndexEntry(vid, 1),), (), 1, at, at)
    variant = PresentationVariant(pid, vid, 1, title, None, (), None, None, 1, at, at)
    return PresentationView(presentation, (variant,))


# ------------------------------------------------------------------ mises à jour (corps de requête)

@dataclass(frozen=True, slots=True)
class PresentationUpdate:
    expected_revision: int
    title: str
    active_variant_id: str
    resources: tuple[ResourceReference, ...]


@dataclass(frozen=True, slots=True)
class VariantUpdate:
    expected_revision: int
    title: str
    scenes: tuple[SceneRef, ...]
    art_direction_id: str | None
    score_id: str | None


def parse_create(raw: object) -> str:
    data = _exact_keys(raw, "create", {"title"})
    _check_title("title", data["title"])
    return data["title"]


def parse_presentation_update(raw: object) -> PresentationUpdate:
    data = _exact_keys(raw, "presentation update", {"expected_revision", "title", "active_variant_id", "resources"})
    _check_int("expected_revision", data["expected_revision"], 1, MAX_REVISION)
    _check_title("title", data["title"])
    _check_id("active_variant_id", data["active_variant_id"], VARIANT_ID)
    return PresentationUpdate(data["expected_revision"], data["title"], data["active_variant_id"],
                              _resources(data["resources"]))


def parse_variant_update(raw: object) -> VariantUpdate:
    data = _exact_keys(raw, "variant update",
                       {"expected_revision", "title", "scenes", "art_direction_id", "score_id"})
    _check_int("expected_revision", data["expected_revision"], 1, MAX_REVISION)
    _check_title("title", data["title"])
    _check_id("art_direction_id", data["art_direction_id"], ART_DIRECTION_ID, optional=True)
    _check_id("score_id", data["score_id"], SCORE_ID, optional=True)
    return VariantUpdate(data["expected_revision"], data["title"], _scenes(data["scenes"]),
                         data["art_direction_id"], data["score_id"])


# ------------------------------------------------------------------ documents (disque / validation)

def _no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _no_constant(value: str) -> object:
    raise ValueError("nonfinite JSON number")


def load_document(text: str) -> Any:
    """JSON strict (clé en double, `NaN` refusés), borné à `MAX_DOCUMENT_BYTES`."""

    if len(text.encode("utf-8", errors="surrogatepass")) > MAX_DOCUMENT_BYTES:
        raise _fail(f"document exceeds {MAX_DOCUMENT_BYTES} bytes")
    try:
        return json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
    except (ValueError, RecursionError) as exc:
        raise _fail(f"document is not valid JSON: {str(exc)[:120]}") from None


def dump_document(document: Mapping[str, Any]) -> str:
    text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    try:
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError:
        raise _fail("document holds a character that cannot be stored (lone surrogate)") from None
    if size > MAX_DOCUMENT_BYTES:
        raise PresentationStudioError(_C.LIMIT_REACHED, f"document would exceed {MAX_DOCUMENT_BYTES} bytes")
    return text


#: `UPGRADES[schema][n]` rend le document de la version n+1 à partir de celui de la version n (vide à la v1).
UPGRADES: dict[str, dict[int, Callable[[dict[str, Any]], dict[str, Any]]]] = {SCHEMA_PRESENTATION: {}, SCHEMA_VARIANT: {}}


def upgrade_document(raw: object, schema: str, *, current: int = SCHEMA_VERSION,
                     upgrades: Mapping[str, Mapping[int, Callable[[dict[str, Any]], dict[str, Any]]]] | None = None
                     ) -> dict[str, Any]:
    """Vérifie `{schema, schema_version}` et monte le document à `current`. Plus récent : refus, jamais de lecture au mieux."""

    if not isinstance(raw, dict):
        raise _fail(f"{schema} document must be a JSON object")
    if raw.get("schema") != schema:
        raise _fail(f"document schema must be {schema}")
    version = raw.get("schema_version")
    if type(version) is not int or version < 1:
        raise _fail("schema_version must be a positive integer")
    if version > current:
        raise PresentationStudioError(
            _C.UNSUPPORTED_SCHEMA_VERSION,
            f"{schema} is schema_version {version}, this JARVIS reads up to {current}: update JARVIS; "
            "the file is left untouched")
    steps = (upgrades if upgrades is not None else UPGRADES).get(schema, {})
    document = dict(raw)
    while version < current:
        step = steps.get(version)
        if step is None:
            raise PresentationStudioError(_C.CORRUPT_DOCUMENT, f"{schema} v{version} has no upgrade step")
        document = step(document)
        version += 1
        document["schema_version"] = version
    return document


def parse_presentation(raw: object) -> Presentation:
    data = _exact_keys(upgrade_document(raw, SCHEMA_PRESENTATION), "presentation",
                       {"schema", "schema_version", "presentation_id", "title", "active_variant_id",
                        "variant_counter", "variants", "resources", "revision", "created_at", "updated_at"})
    entries = data["variants"]
    if not isinstance(entries, list):
        raise _fail("variants must be a list")
    index = tuple(VariantIndexEntry(**_exact_keys(e, f"variants[{i}]", {"variant_id", "variant_number"}))
                  for i, e in enumerate(entries[:MAX_VARIANTS + 1]))
    return Presentation(data["presentation_id"], data["title"], data["active_variant_id"], data["variant_counter"],
                        index, _resources(data["resources"]), data["revision"], data["created_at"],
                        data["updated_at"])


def parse_variant(raw: object) -> PresentationVariant:
    data = _exact_keys(upgrade_document(raw, SCHEMA_VARIANT), "variant",
                       {"schema", "schema_version", "presentation_id", "variant_id", "variant_number", "title",
                        "parent_variant_id", "scenes", "art_direction_id", "score_id", "revision", "created_at",
                        "updated_at"})
    return PresentationVariant(data["presentation_id"], data["variant_id"], data["variant_number"], data["title"],
                               data["parent_variant_id"], _scenes(data["scenes"]), data["art_direction_id"],
                               data["score_id"], data["revision"], data["created_at"], data["updated_at"])


def validate_documents(raw: object) -> PresentationView:
    """`{presentation, variants: [...]}` au format disque -> vue cohérente, ou `PresentationStudioError`. Rien n'est écrit."""

    data = _exact_keys(raw, "validate", {"presentation", "variants"})
    if not isinstance(data["variants"], list) or len(data["variants"]) > MAX_VARIANTS:
        raise _fail(f"variants must be a list of at most {MAX_VARIANTS}")
    presentation = parse_presentation(data["presentation"])
    variants = tuple(parse_variant(item) for item in data["variants"])
    return PresentationView(presentation, variants)

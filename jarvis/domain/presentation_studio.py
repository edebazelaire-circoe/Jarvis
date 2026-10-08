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
  éventuel, scènes logiques ordonnées (`StudioScene`, Slice 04, `presentation_studio_scene.py` :
  `scene_id` + `PrefabRef` exact `(id, version)`, valeurs d'instance, contrôles curés, ancres), références vers la direction artistique
  (`psd_`) et la partition (`psr_`), `revision`.

Ce qui n'y vit **jamais** (état d'exécution) : identifiant d'objet de la scène
globale, fenêtre, DOM, cadre, position de lecture, progression de révélation,
détours, pile de ressources auxiliaires, pile d'annulation. Toute clé inconnue
est refusée ; si elle porte un nom d'état d'exécution connu, le refus a son
propre code (`runtime_state_refused`) pour qu'on le voie.

Versionnage : chaque document porte `{schema, schema_version}`. Une version
**plus récente** que `SCHEMA_VERSION` est refusée (`unsupported_schema_version`),
jamais lue au mieux ni réécrite ; une version plus ancienne passe par la chaîne
`UPGRADES` (vide pour la Presentation, une étape 1 -> 2 pour la variante depuis la Slice 04). Pas de `_MIGRATIONS` SQLite : le stockage est un
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
import unicodedata
from urllib.parse import unquote
from typing import Any

from jarvis.domain.prefab import PrefabDefinitionError  # noqa: F401 - kept importable from here
from jarvis.domain.presentation_studio_checks import (  # noqa: F401 - re-exported: the historical home of these names
    HTTP_STATUS, MAX_ERROR_CHARS, MAX_TITLE, RUNTIME_KEYS, SCENE_ID, PresentationStudioError,
    PresentationStudioErrorCode, _C, _check_id, is_scene_id, _check_int, _check_title, _exact_keys, _fail, clip,
)
from jarvis.domain.presentation_studio_scene import StudioScene, upgrade_scene_v1, upgrade_scene_v2
from jarvis.domain.presentation_studio_variants import (  # noqa: F401 - the graph model lives there; re-exported (historical names)
    MAX_ARCHIVED_VARIANTS, VARIANT_ID, ArchivedEntry, VariantIndexEntry, _STAMP, _check_stamp, archived_from_dict,
    entry_from_dict, is_variant_id, upgrade_entry_v1, validate_graph,
)
from jarvis.domain.presentation_working_set import ResourceKind, ResourceReference

SCHEMA_PRESENTATION = "jarvis.presentation_studio.presentation"
SCHEMA_VARIANT = "jarvis.presentation_studio.variant"
#: `Presentation` document : v2 (Slice 16) ajoute à chaque entrée de l'index sa raison de création, son auteur, ses sources et
#: son aperçu, et la liste `archived` (variantes déplacées vers `archive/`).
SCHEMA_VERSION = 2
#: `PresentationVariant` document : v2 (Slice 04) ajoute titre, section, valeurs, contrôles, ancres et vignette aux scènes ;
#: v3 (Slice 06) ajoute à chaque scène `source_revision` et `last_valid_pin` (rechargement à chaud). Le manifeste
#: `presentation.json` (v2, Slice 16) et le document de variante ont chacun leur numéro : ils ne bougent pas ensemble.
VARIANT_SCHEMA_VERSION = 3
#: `Score` document (Slice 10, `presentation_studio_score.py`) : `scores/<score_id>.json`, version 1.
SCHEMA_SCORE = "jarvis.presentation_studio.score"
SCORE_SCHEMA_VERSION = 1
#: `ArtDirection` document (Slice 09, `presentation_studio_art_direction.py`) : `art_directions/<art_direction_id>.json`, version 1.
SCHEMA_ART_DIRECTION = "jarvis.presentation_studio.art_direction"
ART_DIRECTION_SCHEMA_VERSION = 1
CURRENT_VERSIONS = {SCHEMA_PRESENTATION: SCHEMA_VERSION, SCHEMA_VARIANT: VARIANT_SCHEMA_VERSION,
                    SCHEMA_SCORE: SCORE_SCHEMA_VERSION, SCHEMA_ART_DIRECTION: ART_DIRECTION_SCHEMA_VERSION}

#: Bornes (toute collection est bornée, comme `scene.py`).
MAX_SCENES = 64
MAX_RESOURCES = 64
MAX_VARIANTS = 64
MAX_VARIANT_COUNTER = 10_000
MAX_REVISION = 2**31 - 1
MAX_PRESENTATIONS = 256
#: Taille d'un document sur disque ou reçu (échappement JSON compris).
MAX_DOCUMENT_BYTES = 256 * 1024
MAX_VALIDATION_ERRORS = 20

_HEX32 = "[0-9a-f]{32}"
_HEX12 = "[0-9a-f]{12}"
PRESENTATION_ID = re.compile(rf"pst_{_HEX32}\Z")
ART_DIRECTION_ID = re.compile(rf"psd_{_HEX12}\Z")
SCORE_ID = re.compile(rf"psr_{_HEX12}\Z")


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


def is_art_direction_id(value: object) -> bool:
    return isinstance(value, str) and bool(ART_DIRECTION_ID.fullmatch(value))


def is_score_id(value: object) -> bool:
    return isinstance(value, str) and bool(SCORE_ID.fullmatch(value))


def stamp(moment: datetime) -> str:
    """`2026-10-07T12:00:00.000000Z` : UTC, microsecondes fixes (comparable en texte)."""

    if moment.tzinfo is None or moment.utcoffset() is None:
        raise _fail("timestamps must be timezone-aware")
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")



# ------------------------------------------------------------------ références

#: Nom de la Slice 02 pour la scène d'une variante : désormais la scène complète de la Slice 04.
SceneRef = StudioScene


#: Ressources dont le localisateur est un identifiant d'objet de la scène globale : un handle d'exécution.
_REFUSED_RESOURCE_KINDS = frozenset({ResourceKind.SCENE_OBJECT})


MAX_PERCENT_DECODINGS = 5


def _percent_fixpoint(locator: str) -> str | None:
    """`locator` décodé en pourcentage jusqu'à stabilité (au plus `MAX_PERCENT_DECODINGS` passes) ; `None` si ça ne se stabilise pas."""

    text = locator
    for _ in range(MAX_PERCENT_DECODINGS):
        decoded = unquote(text)
        if decoded == text:
            return text
        text = decoded
    return text if unquote(text) == text else None


def _check_locator_hygiene(where: str, locator: object) -> None:
    """Avant qu'un résolveur (Slices 11, 12) lise un localisateur, sur le texte brut **et** décodé jusqu'à stabilité :
    uniquement des caractères imprimables (ni contrôle, ni largeur nulle, ni contrôle bidi), pas d'espace en bordure,
    pas d'antislash, de segment `..`, de `//hôte` (UNC) ni de `file://`, un schéma en ASCII (le repli NFKC ne laisse pas un
    schéma d'allure `scene:` se faire passer pour autre chose). Un `%20` ordinaire reste admis. Rien n'est résolu ici."""

    if not isinstance(locator, str):
        return  # ResourceReference names the type error
    decoded = _percent_fixpoint(locator)
    if decoded is None:
        raise _fail(f"{where}.locator is percent-encoded more than {MAX_PERCENT_DECODINGS} times")
    for text in (locator, decoded):
        if text != text.strip() or not text.isprintable():
            raise _fail(f"{where}.locator must be printable text without control, zero-width or bidi characters, "
                        "or surrounding spaces")
    folded = unicodedata.normalize("NFKC", decoded)
    scheme, colon, rest = folded.partition(":")
    if colon and "/" not in scheme and not scheme.isascii():
        raise _fail(f"{where}.locator scheme must be ASCII")
    if "\\" in folded or ".." in re.split(r"[/?#]", rest if colon else folded):
        raise _fail(f"{where}.locator must not hold a backslash or a '..' path segment")
    if folded.startswith("//") or (colon and scheme.lower() == "file" and rest.startswith("//")):
        raise _fail(f"{where}.locator must not be a file:// or //host/share locator")


def resource_to_dict(resource: ResourceReference) -> dict[str, Any]:
    return {"kind": resource.kind.value, "locator": resource.locator, "title": resource.title}


def resource_from_dict(raw: object, where: str = "resource") -> ResourceReference:
    """`{kind, locator, title}` : le `descriptor` de `ResourceReference` (charge de données) n'est pas stocké ici."""

    data = _exact_keys(raw, where, {"kind", "locator"}, frozenset({"title"}))
    try:
        kind = ResourceKind(data["kind"])
    except (ValueError, TypeError):
        raise _fail(f"{where}.kind is not a resource kind") from None
    _check_locator_hygiene(where, data["locator"])
    folded = unicodedata.normalize("NFKC", _percent_fixpoint(str(data["locator"])) or "").strip().lower()
    if kind in _REFUSED_RESOURCE_KINDS or folded.startswith("scene:"):
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
    items = tuple(item if isinstance(item, StudioScene) else StudioScene.from_dict(item, f"scenes[{i}]")
                  for i, item in enumerate(value))
    ids = [item.scene_id for item in items]
    if len(set(ids)) != len(ids):
        raise _fail("scenes hold the same scene_id twice")
    return items


# ------------------------------------------------------------------ agrégat

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
    #: Variantes archivées (Slice 16) : leur fichier est dans `archive/`, leur numéro n'est jamais réutilisé.
    archived: tuple[ArchivedEntry, ...] = ()

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
        object.__setattr__(self, "archived", tuple(self.archived))
        if not all(isinstance(entry, ArchivedEntry) for entry in self.archived):
            raise _fail("archived must be ArchivedEntry values")
        # Slice 16 : ids et numéros uniques sur vivants + archivés, compteur >= tout numéro, actif vivant, sources, bornes.
        # (Les parents sont dans les fichiers de variante : `check_consistency` complète avec eux.)
        validate_graph(self.variants, self.archived, active=self.active_variant_id, counter=self.variant_counter)
        _check_int("revision", self.revision, 1, MAX_REVISION)
        _check_stamp("created_at", self.created_at)
        _check_stamp("updated_at", self.updated_at)

    def to_document(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_PRESENTATION, "schema_version": SCHEMA_VERSION,
            "presentation_id": self.presentation_id, "title": self.title,
            "active_variant_id": self.active_variant_id, "variant_counter": self.variant_counter,
            "variants": [e.to_dict() for e in self.variants],
            "archived": [a.to_dict() for a in self.archived],
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
    #: L'arête parent du graphe (Slice 16 : `presentation_studio_variants.py`) ; les autres métadonnées du noeud sont dans l'index.
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
            "schema": SCHEMA_VARIANT, "schema_version": VARIANT_SCHEMA_VERSION,
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
    # Slice 16 : le graphe entier (parents existants et vivants, pas de cycle, numéros croissants, sources, actif vivant).
    validate_graph(presentation.variants, presentation.archived, active=presentation.active_variant_id,
                   counter=presentation.variant_counter,
                   live_parents={variant.variant_id: variant.parent_variant_id for variant in variants})


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
def _variant_v1_to_v2(document: dict[str, Any]) -> dict[str, Any]:
    """v1 -> v2 : chaque scène `{scene_id, prefab}` reçoit les défauts des champs de la Slice 04 (rien n'est réinterprété)."""

    scenes = document.get("scenes")
    if isinstance(scenes, list):
        document = {**document, "scenes": [upgrade_scene_v1(scene) for scene in scenes]}
    return document


def _variant_v2_to_v3(document: dict[str, Any]) -> dict[str, Any]:
    """v2 -> v3 : chaque scène reçoit `source_revision` 0 et aucun pin de repli (Slice 06)."""

    scenes = document.get("scenes")
    if isinstance(scenes, list):
        document = {**document, "scenes": [upgrade_scene_v2(scene) for scene in scenes]}
    return document


def _presentation_v1_to_v2(document: dict[str, Any]) -> dict[str, Any]:
    """v1 -> v2 (Slice 16) : chaque entrée de l'index reçoit raison vide, auteur `system`, aucune source, aucun aperçu ; aucune archive."""

    entries = document.get("variants")
    if isinstance(entries, list):
        document = {**document, "variants": [upgrade_entry_v1(entry) for entry in entries]}
    return {**document, "archived": document.get("archived", [])}


UPGRADES: dict[str, dict[int, Callable[[dict[str, Any]], dict[str, Any]]]] = {
    SCHEMA_PRESENTATION: {1: _presentation_v1_to_v2}, SCHEMA_VARIANT: {1: _variant_v1_to_v2, 2: _variant_v2_to_v3},
    SCHEMA_SCORE: {}, SCHEMA_ART_DIRECTION: {}}


def upgrade_document(raw: object, schema: str, *, current: int | None = None,
                     upgrades: Mapping[str, Mapping[int, Callable[[dict[str, Any]], dict[str, Any]]]] | None = None
                     ) -> dict[str, Any]:
    """Vérifie `{schema, schema_version}` et monte le document à `current`. Plus récent : refus, jamais de lecture au mieux."""

    current = CURRENT_VERSIONS[schema] if current is None else current
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
                        "variant_counter", "variants", "archived", "resources", "revision", "created_at", "updated_at"})
    entries, archived = data["variants"], data["archived"]
    if not isinstance(entries, list) or not isinstance(archived, list):
        raise _fail("variants and archived must be lists")
    index = tuple(entry_from_dict(e, f"variants[{i}]") for i, e in enumerate(entries[:MAX_VARIANTS + 1]))
    shelved = tuple(archived_from_dict(a, f"archived[{i}]") for i, a in enumerate(archived[:MAX_ARCHIVED_VARIANTS + 1]))
    return Presentation(data["presentation_id"], data["title"], data["active_variant_id"], data["variant_counter"],
                        index, _resources(data["resources"]), data["revision"], data["created_at"],
                        data["updated_at"], shelved)


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

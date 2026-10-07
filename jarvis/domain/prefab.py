"""Définitions de prefab : manifeste, schémas d'entrée, publication, verrou (handoff
jarvis-scene-window-prefab-foundation, Slice 02).

Contrat canonique : `docs/prefabs.md` (sections *Manifest*, *Input schema*,
*Hygiene lint*, *Publication and provenance*, *Base-edit gate*). Pur : aucune
E/S ; le magasin (`jarvis.adapters.file_prefab_library`) lit et écrit les
fichiers, le service (`jarvis.core.prefab_service`) décide.

- **Décodage strict** : tout champ inconnu est refusé, à chaque niveau. Les
  erreurs sont **collectées** (au plus `MAX_ERRORS`, chacune ≤ `MAX_ERROR_CHARS`)
  et nommées par leur chemin (`inputs.data.items[].label: ...`), pour qu'un
  auteur (le cerveau, l'UI) corrige tout en un passage.
- **Valeurs** : `validate_value(schema, value)` rend `(valeur avec défauts, erreurs)` ;
  la valeur validée et complétée est celle que Core enregistre.
- **Classification dérivée**, jamais déclarée : `base` ssi l'id commence par
  `jarvis.`. Un manifeste qui porte un champ de provenance est refusé : la
  provenance est écrite par Core dans `publication.json`.
- **Empreinte** : `jarvis.domain.prompt_registry.fingerprint` sur le JSON
  canonique `{"manifest", "template", "style", "behavior"}`.
- **Hygiène** (`lint_bundle`) : refus de balises et motifs listés ; ce n'est
  pas la frontière de sécurité (le bac à sable l'est, `SECURITY.md` §16).
"""

from __future__ import annotations

from collections.abc import Mapping
import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import json
import math
import re
from typing import Any
from urllib.parse import urlsplit

from jarvis.domain._checks import (  # noqa: F401 - grammaire réexportée (`MAX_PREFAB_ID_CHARS`, `PREFAB_ID`)
    MAX_PREFAB_ID_CHARS, MAX_PREFAB_VERSION, MIN_PREFAB_VERSION, PREFAB_ID, is_prefab_id, is_prefab_version, preview,
)
from jarvis.domain.prompt_registry import PromptError, fingerprint
from jarvis.domain.scene import MAX_PAYLOAD_BYTES, MAX_SCENE_EXTENT

MANIFEST_SCHEMA = "jarvis.prefab"
PUBLICATION_SCHEMA = "jarvis.prefab.publication"
CATALOG_LOCK_SCHEMA = "jarvis.prefab.catalog_lock"
SCHEMA_VERSION = 1
#: Espace de noms réservé aux prefabs de base, livrés dans le paquet.
BASE_NAMESPACE = "jarvis."

# Grammaire id/version : `jarvis.domain._checks` (partagée avec le bloc `prefab` de la scène).
MIN_VERSION = MIN_PREFAB_VERSION
MAX_VERSION = MAX_PREFAB_VERSION
MAX_TITLE_CHARS = 80
MAX_DESCRIPTION_CHARS = 600
MAX_FAMILY_CHARS = 32
FAMILY = re.compile(r"[a-z][a-z0-9_-]*\Z")
MAX_LABELS = 16
MAX_LABEL_CHARS = 40
#: Bornes du catalogue, par racine (paquet, racine de données).
MAX_PREFAB_IDS = 512
MAX_VERSIONS_PER_ID = 64
#: Espace de noms de la rétention (Slice 01a) : les sources de scène du Studio. Seuls ces ids voient leurs versions
#: non épinglées archivées par Core ; les prefabs de l'utilisateur et les bases ne sont jamais touchés.
RETENTION_NAMESPACE = "presentation-studio."
#: Versions **vivantes** d'un id de rétention qui déclenchent une passe (la borne dure reste `MAX_VERSIONS_PER_ID`).
RETENTION_TRIGGER_VERSIONS = 32
#: Dernières versions toujours gardées vivantes, épinglées ou non.
RETENTION_KEEP_LAST = 16
#: Part des `MAX_PREFAB_IDS` que les ids de rétention peuvent occuper : le reste est garanti à l'utilisateur.
MAX_RETENTION_PREFAB_IDS = 384
MAX_EVENTS = 16
EVENT_NAME = re.compile(r"[a-z][a-z0-9_]{0,39}\Z")
MAX_EVENT_SUMMARY_CHARS = 120
#: Charge d'un événement `notify` (et borne historique du nom) : 8 Kio.
MAX_EVENT_PAYLOAD_BYTES = 8 * 1024
MAX_NOTIFY_PAYLOAD_BYTES = MAX_EVENT_PAYLOAD_BYTES
#: Charge d'un événement `state` : la borne de la charge d'un objet de scène
#: (16 Kio, `MAX_PAYLOAD_BYTES`). Toute clé de `data` qu'une instance valide
#: peut porter tient donc entière dans un seul événement (reprise QA S04/S06, A5).
MAX_STATE_EVENT_PAYLOAD_BYTES = MAX_PAYLOAD_BYTES
#: Profondeur d'imbrication d'un schéma : la racine (`inputs.props`) est au niveau 0.
MAX_SCHEMA_DEPTH = 4
MAX_SCHEMA_DESCRIPTION_CHARS = 200
MAX_STRING_LENGTH = 2000
DEFAULT_STRING_LENGTH = 200
MAX_TEXT_LENGTH = 12000
#: Borne d'un `text` qui n'en déclare pas : le contrat fixe seulement le maximum.
DEFAULT_TEXT_LENGTH = 2000
MAX_PATTERN_CHARS = 200
MAX_ENUM_VALUES = 32
MAX_ENUM_VALUE_CHARS = 200
MAX_URL_CHARS = 2048
MAX_OBJECT_PROPERTIES = 32
MAX_PROPERTY_NAME_CHARS = 64
PROPERTY_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
MAX_ARRAY_ITEMS = 256
#: Octets UTF-8 au plus de chaque fichier d'une version.
MAX_MANIFEST_BYTES = 32 * 1024
MAX_TEMPLATE_BYTES = 32 * 1024
MAX_STYLE_BYTES = 32 * 1024
MAX_BEHAVIOR_BYTES = 64 * 1024
MAX_PUBLICATION_BYTES = 8 * 1024
MAX_LOCK_BYTES = 256 * 1024
MAX_LOCK_ENTRIES = 512 * 64
#: Noms de fichiers fixés en v1.
FILES = {"template": "template.html", "style": "style.css", "behavior": "behavior.js"}
MANIFEST_FILE = "manifest.json"
PUBLICATION_FILE = "publication.json"
MIN_USER_REQUEST_CHARS = 12
MAX_USER_REQUEST_CHARS = 500
WITNESS_PREFIX = "conversation_event:"
MAX_WITNESS_CHARS = 200
#: Erreurs rendues au plus, et longueur de chacune : un candidat hostile ne fait pas grossir les réponses.
MAX_ERRORS = 20
MAX_ERROR_CHARS = 300

COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")
#: Champs de provenance qu'un candidat ne doit jamais porter (message dédié).
PROVENANCE_FIELDS = frozenset({"provenance", "publication", "derived_from", "origin", "base_edit", "fingerprint",
                               "published_at", "created_by"})


class PrefabClass(StrEnum):
    BASE = "base"
    CUSTOM = "custom"


class InputType(StrEnum):
    STRING = "string"
    TEXT = "text"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    COLOR = "color"
    ENUM = "enum"
    URL = "url"
    OBJECT = "object"
    ARRAY = "array"


class EventClass(StrEnum):
    STATE = "state"
    NOTIFY = "notify"


class ProvenanceOrigin(StrEnum):
    BASE = "base"
    CUSTOM = "custom"
    FORK = "fork"
    REVISION = "revision"
    BASE_EDIT = "base_edit"


class CreatorActor(StrEnum):
    SYSTEM = "system"
    BRAIN = "brain"
    USER = "user"


class PrefabDefinitionError(ValueError):
    """Définition, publication ou verrou refusé ; `errors` : messages bornés, nommés par chemin."""

    def __init__(self, errors: tuple[str, ...] | list[str]) -> None:
        clipped = tuple(clip_message(item) for item in list(errors)[:MAX_ERRORS]) or ("invalid prefab definition",)
        super().__init__("; ".join(clipped)[:MAX_ERROR_CHARS])
        self.errors = clipped


def clip_message(message: str, limit: int = MAX_ERROR_CHARS) -> str:
    """Seule règle de troncature des messages de prefab (domaine, magasin, service) : ≤ `limit`, `…` si coupé."""

    return message if len(message) <= limit else message[: limit - 1] + "…"


#: Citation d'une valeur (`repr`), fermée ou coupée par une troncature (jusqu'à la fin du texte).
_VALUE_QUOTE = re.compile(r"'(?:[^'\\]|\\.)*(?:'|\Z)|\"(?:[^\"\\]|\\.)*(?:\"|\Z)", re.DOTALL)
_DETAIL_PATH = re.compile(r"(?<![\w.])(?:props|data|payload|basis)(?:\.[A-Za-z_][A-Za-z0-9_-]*|\[\d+\])*")
MAX_DETAIL_PATHS = 8


def detail_paths(detail: str, limit: int = MAX_DETAIL_PATHS) -> list[str]:
    """Chemins d'entrée nommés par un refus (`props.accent`, `data.items[3].label`), sans aucune valeur.

    Seule forme d'un refus de prefab admise dans un **journal** (reprise QA S04
    F3) : les messages de validation citent la valeur reçue (`got '…'`), qui
    peut être une donnée de l'utilisateur. Les citations sont retirées avant
    l'extraction : une valeur qui ressemble à un chemin ne passe pas.
    """

    found: list[str] = []
    for match in _DETAIL_PATH.finditer(_VALUE_QUOTE.sub("", str(detail))):
        path = match.group(0)
        if path not in found:
            found.append(path)
        if len(found) >= limit:
            break
    return found


class _Errors:
    """Collecteur borné : au-delà de `MAX_ERRORS`, les suivantes sont comptées, pas gardées."""

    def __init__(self) -> None:
        self.items: list[str] = []
        self.dropped = 0

    def add(self, path: str, message: str) -> None:
        if len(self.items) >= MAX_ERRORS:
            self.dropped += 1
            return
        self.items.append(clip_message(f"{path}: {message}" if path else message))

    def __bool__(self) -> bool:
        return bool(self.items)

    @property
    def count(self) -> int:
        """Erreurs vues, gardées ou non : un « rien de neuf » ne se lit jamais sur `items` plafonné."""

        return len(self.items) + self.dropped

    def raise_if_any(self) -> None:
        if self.items:
            raise PrefabDefinitionError(self.items)


# ------------------------------------------------------------------ identité


is_version = is_prefab_version


def prefab_class(prefab_id: str) -> PrefabClass:
    return PrefabClass.BASE if prefab_id.startswith(BASE_NAMESPACE) else PrefabClass.CUSTOM


def is_retention_id(prefab_id: str) -> bool:
    """Id dont Core peut archiver les versions non épinglées (`presentation-studio.*`, jamais une base)."""

    return (is_prefab_id(prefab_id) and prefab_id.startswith(RETENTION_NAMESPACE)
            and prefab_class(prefab_id) is PrefabClass.CUSTOM)


def version_folder_name(value: str) -> int | None:
    """Nom d'un dossier de version (`1`..`9999`, sans zéro de tête), ou `None`."""

    if not re.fullmatch(r"[1-9][0-9]{0,3}", value):
        return None
    return int(value)


@dataclass(frozen=True, slots=True)
class PrefabRef:
    """Référence exacte `(id, version)` d'une définition."""

    prefab_id: str
    version: int

    def __post_init__(self) -> None:
        if not is_prefab_id(self.prefab_id):
            raise PrefabDefinitionError([f"prefab id {preview(self.prefab_id)} is not a valid prefab id"])
        if not is_version(self.version):
            raise PrefabDefinitionError([f"version {preview(self.version)} must be an integer 1..{MAX_VERSION}"])

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.prefab_id, "version": self.version}

    @classmethod
    def from_dict(cls, raw: object, where: str = "derived_from") -> PrefabRef:
        if not isinstance(raw, dict) or set(raw) != {"id", "version"}:
            raise PrefabDefinitionError([f"{where} must be exactly {{id, version}}"])
        return cls(raw["id"], raw["version"])


@dataclass(frozen=True, slots=True)
class PrefabInstanceRef:
    """Bloc d'instance tel que le service le valide (forme du `prefab` de la scène, Slice 04)."""

    prefab_id: str
    version: int
    props: Mapping[str, Any] = field(default_factory=dict)
    data: Mapping[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------ schémas d'entrée

_COMMON_KEYS = frozenset({"type", "default", "description"})
_TYPE_KEYS: dict[InputType, frozenset[str]] = {
    InputType.STRING: frozenset({"max_length", "pattern"}),
    InputType.TEXT: frozenset({"max_length", "format"}),
    InputType.NUMBER: frozenset({"min", "max"}),
    InputType.INTEGER: frozenset({"min", "max"}),
    InputType.BOOLEAN: frozenset(),
    InputType.COLOR: frozenset(),
    InputType.ENUM: frozenset({"values"}),
    InputType.URL: frozenset(),
    InputType.OBJECT: frozenset({"properties", "required"}),
    InputType.ARRAY: frozenset({"items", "max_items", "min_items"}),
}
_NO_DEFAULT = object()


@dataclass(frozen=True, slots=True)
class InputSchema:
    """Un nœud de schéma d'entrée analysé. `default` vaut `_NO_DEFAULT` quand il est absent."""

    type: InputType
    description: str = ""
    default: Any = _NO_DEFAULT
    max_length: int | None = None
    pattern: str | None = None
    format: str | None = None
    min: float | None = None
    max: float | None = None
    values: tuple[str, ...] = ()
    properties: Mapping[str, InputSchema] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    items: InputSchema | None = None
    max_items: int | None = None
    min_items: int = 0

    @property
    def has_default(self) -> bool:
        return self.default is not _NO_DEFAULT

    def at(self, path: tuple[str, ...]) -> InputSchema | None:
        """Le nœud atteint par des noms de propriétés successifs, ou `None`."""

        node: InputSchema | None = self
        for name in path:
            if node is None or node.type is not InputType.OBJECT:
                return None
            node = node.properties.get(name)
        return node


def _is_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _single_line(value: str) -> bool:
    return not any(ord(char) < 32 or ord(char) == 127 for char in value)


def _multi_line(value: str) -> bool:
    return not any((ord(char) < 32 and char not in "\n\t") or ord(char) == 127 for char in value)


def parse_input_schema(raw: object, path: str = "schema", *,
                       roots: Mapping[str, InputSchema] | None = None) -> InputSchema:
    """Un schéma d'entrée strict ; `roots` (`{"props", "data"}`) autorise `$ref` (schémas d'événement)."""

    errors = _Errors()
    schema = _parse_schema(raw, path, 0, roots, errors)
    errors.raise_if_any()
    assert schema is not None
    return schema


def _parse_schema(raw: object, path: str, depth: int, roots: Mapping[str, InputSchema] | None,
                  errors: _Errors) -> InputSchema | None:
    if depth > MAX_SCHEMA_DEPTH:
        errors.add(path, f"schema nesting exceeds depth {MAX_SCHEMA_DEPTH}")
        return None
    if not isinstance(raw, dict):
        errors.add(path, "schema must be an object")
        return None
    if "$ref" in raw:
        return _parse_ref(raw, path, depth, roots, errors)
    try:
        kind = InputType(raw.get("type"))
    except ValueError:
        errors.add(path, f"type must be one of {[item.value for item in InputType]}, got {preview(raw.get('type'))}")
        return None
    allowed = _COMMON_KEYS | _TYPE_KEYS[kind]
    unknown = sorted(str(key)[:40] for key in raw if key not in allowed)
    if unknown:
        errors.add(path, f"unknown fields for type {kind.value}: {unknown[:5]}")
        return None
    before = errors.count
    description = raw.get("description", "")
    if not isinstance(description, str) or len(description) > MAX_SCHEMA_DESCRIPTION_CHARS \
            or not _single_line(description):
        errors.add(path + ".description", f"must be one line of at most {MAX_SCHEMA_DESCRIPTION_CHARS} characters")
    spec: dict[str, Any] = {"type": kind, "description": description if isinstance(description, str) else ""}
    if kind is InputType.STRING:
        spec["max_length"] = _bounded_int(raw, "max_length", path, 1, MAX_STRING_LENGTH, DEFAULT_STRING_LENGTH, errors)
        pattern = raw.get("pattern")
        if pattern is not None:
            if not isinstance(pattern, str) or len(pattern) > MAX_PATTERN_CHARS \
                    or not pattern.startswith("^") or not pattern.endswith("$"):
                errors.add(path + ".pattern", f"must be an anchored (^...$) regular expression of at most "
                                              f"{MAX_PATTERN_CHARS} characters")
            else:
                try:
                    re.compile(pattern)
                    spec["pattern"] = pattern
                except re.error as exc:
                    errors.add(path + ".pattern", f"invalid regular expression: {exc}")
    elif kind is InputType.TEXT:
        spec["max_length"] = _bounded_int(raw, "max_length", path, 1, MAX_TEXT_LENGTH, DEFAULT_TEXT_LENGTH, errors)
        text_format = raw.get("format", "plain")
        if text_format not in ("plain", "markdown"):
            errors.add(path + ".format", "must be 'plain' or 'markdown'")
        spec["format"] = text_format
    elif kind in (InputType.NUMBER, InputType.INTEGER):
        for bound in ("min", "max"):
            if bound in raw:
                value = raw[bound]
                if not _is_number(value) or isinstance(value, bool) \
                        or (kind is InputType.INTEGER and type(value) is not int):
                    errors.add(f"{path}.{bound}", f"must be a finite {kind.value}")
                else:
                    spec[bound] = value
        if spec.get("min") is not None and spec.get("max") is not None and spec["min"] > spec["max"]:
            errors.add(path, "min must not exceed max")
    elif kind is InputType.ENUM:
        values = raw.get("values")
        if not isinstance(values, list) or not 1 <= len(values) <= MAX_ENUM_VALUES \
                or any(not isinstance(item, str) or not item or len(item) > MAX_ENUM_VALUE_CHARS
                       or not _single_line(item) for item in values) or len(set(values)) != len(values):
            errors.add(path + ".values", f"must be 1..{MAX_ENUM_VALUES} distinct one-line strings")
        else:
            spec["values"] = tuple(values)
    elif kind is InputType.OBJECT:
        properties = raw.get("properties", {})
        parsed: dict[str, InputSchema] = {}
        if not isinstance(properties, dict) or len(properties) > MAX_OBJECT_PROPERTIES:
            errors.add(path + ".properties", f"must be an object of at most {MAX_OBJECT_PROPERTIES} properties")
        else:
            for name, child in properties.items():
                if not isinstance(name, str) or not PROPERTY_NAME.fullmatch(name):
                    errors.add(path + ".properties", f"property name {preview(name)} must match "
                                                     f"[A-Za-z_][A-Za-z0-9_]{{0,63}}")
                    continue
                node = _parse_schema(child, f"{path}.{name}", depth + 1, roots, errors)
                if node is not None:
                    parsed[name] = node
        spec["properties"] = parsed
        required = raw.get("required", [])
        if not isinstance(required, list) or any(not isinstance(item, str) for item in required) \
                or len(set(required)) != len(required):
            errors.add(path + ".required", "must be a list of distinct property names")
        elif isinstance(properties, dict) and any(item not in properties for item in required):
            errors.add(path + ".required", f"names unknown properties: "
                                           f"{sorted(item for item in required if item not in properties)[:5]}")
        else:
            spec["required"] = tuple(required)
    elif kind is InputType.ARRAY:
        if "items" not in raw:
            errors.add(path + ".items", "is required for an array")
        else:
            spec["items"] = _parse_schema(raw["items"], path + "[]", depth + 1, roots, errors)
        spec["max_items"] = _bounded_int(raw, "max_items", path, 0, MAX_ARRAY_ITEMS, MAX_ARRAY_ITEMS, errors)
        spec["min_items"] = _bounded_int(raw, "min_items", path, 0, MAX_ARRAY_ITEMS, 0, errors)
        if spec["min_items"] > spec["max_items"]:
            errors.add(path, "min_items must not exceed max_items")
    if errors.count != before:
        return None
    schema = InputSchema(**spec)
    if "default" in raw:
        value, problems = validate_value(schema, raw["default"], path + ".default")
        for problem in problems:
            errors.add("", problem)
        if problems:
            return None
        schema = InputSchema(**{**spec, "default": value})
    return schema


def _bounded_int(raw: dict, key: str, path: str, low: int, high: int, default: int, errors: _Errors) -> int:
    if key not in raw:
        return default
    value = raw[key]
    if type(value) is not int or not low <= value <= high:
        errors.add(f"{path}.{key}", f"must be an integer {low}..{high}")
        return default
    return value


def schema_depth(node: InputSchema) -> int:
    """Niveaux d'imbrication sous `node` (0 pour une feuille) : `object` et `array` en ajoutent un chacun."""

    if node.type is InputType.OBJECT:
        return 1 + max((schema_depth(child) for child in node.properties.values()), default=-1)
    if node.type is InputType.ARRAY and node.items is not None:
        return 1 + schema_depth(node.items)
    return 0


def _parse_ref(raw: dict, path: str, depth: int, roots: Mapping[str, InputSchema] | None,
               errors: _Errors) -> InputSchema | None:
    if roots is None:
        errors.add(path, "$ref is allowed only in event payload schemas")
        return None
    if set(raw) - {"$ref", "description"}:
        errors.add(path, "a $ref node carries only $ref (and description)")
        return None
    target = raw["$ref"]
    parts = target.split(".") if isinstance(target, str) else []
    if len(parts) < 2 or parts[0] not in ("props", "data"):
        errors.add(path, f"$ref must be 'props.<path>' or 'data.<path>', got {preview(target)}")
        return None
    node = roots[parts[0]].at(tuple(parts[1:])) if parts[0] in roots else None
    if node is None:
        errors.add(path, f"$ref {preview(target)} names no input")
        return None
    # La borne vaut pour le schéma effectif : le sous-arbre référencé est inliné à cette profondeur.
    if depth + schema_depth(node) > MAX_SCHEMA_DEPTH:
        errors.add(path, f"$ref {preview(target)} inlines {schema_depth(node)} levels at depth {depth}: "
                         f"schema nesting exceeds depth {MAX_SCHEMA_DEPTH}")
        return None
    return node


# ------------------------------------------------------------------ valeurs


def validate_value(schema: InputSchema, value: object, path: str = "") -> tuple[Any, tuple[str, ...]]:
    """`(valeur complétée de ses défauts, erreurs)` ; erreurs bornées et nommées par chemin."""

    errors = _Errors()
    result = _validate(schema, value, path or "value", errors)
    return result, tuple(errors.items)


def _validate(schema: InputSchema, value: object, path: str, errors: _Errors) -> Any:
    kind = schema.type
    if kind is InputType.OBJECT:
        if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
            errors.add(path, f"expected an object, got {type(value).__name__}")
            return value
        unknown = sorted(key[:40] for key in value if key not in schema.properties)
        if unknown:
            errors.add(path, f"unknown keys {unknown[:5]}")
        result: dict[str, Any] = {}
        for name, child in schema.properties.items():
            if name in value:
                result[name] = _validate(child, value[name], f"{path}.{name}", errors)
            elif child.has_default:
                result[name] = copy.deepcopy(child.default)
            elif name in schema.required:
                errors.add(f"{path}.{name}", "is required")
        return result
    if kind is InputType.ARRAY:
        if not isinstance(value, list):
            errors.add(path, f"expected an array, got {type(value).__name__}")
            return value
        if len(value) > (schema.max_items if schema.max_items is not None else MAX_ARRAY_ITEMS):
            errors.add(path, f"holds {len(value)} items, at most {schema.max_items}")
            return value
        if len(value) < schema.min_items:
            errors.add(path, f"holds {len(value)} items, at least {schema.min_items}")
        assert schema.items is not None
        return [_validate(schema.items, item, f"{path}[{index}]", errors) for index, item in enumerate(value)]
    if kind in (InputType.STRING, InputType.TEXT, InputType.COLOR, InputType.ENUM, InputType.URL):
        if not isinstance(value, str):
            errors.add(path, f"expected a string ({kind.value}), got {type(value).__name__}")
            return value
        if kind is InputType.STRING:
            if len(value) > (schema.max_length or DEFAULT_STRING_LENGTH):
                errors.add(path, f"exceeds {schema.max_length} characters")
            elif not _single_line(value):
                errors.add(path, "must be a single line without control characters")
            elif schema.pattern is not None and not re.fullmatch(schema.pattern, value):
                errors.add(path, f"does not match {schema.pattern[:60]}")
        elif kind is InputType.TEXT:
            if len(value) > (schema.max_length or DEFAULT_TEXT_LENGTH):
                errors.add(path, f"exceeds {schema.max_length} characters")
            elif not _multi_line(value):
                errors.add(path, "must not contain control characters other than newline and tab")
        elif kind is InputType.COLOR:
            if not COLOR.fullmatch(value):
                errors.add(path, f"must be a #rrggbb colour, got {preview(value)}")
        elif kind is InputType.ENUM:
            if value not in schema.values:
                errors.add(path, f"must be one of {list(schema.values)[:8]}, got {preview(value)}")
        elif not _is_http_url(value):
            errors.add(path, f"must be an http(s) URL of at most {MAX_URL_CHARS} characters")
        return value
    if kind is InputType.BOOLEAN:
        if type(value) is not bool:
            errors.add(path, f"expected a boolean, got {type(value).__name__}")
        return value
    # number / integer
    if isinstance(value, bool) or not _is_number(value) or (kind is InputType.INTEGER and type(value) is not int):
        errors.add(path, f"expected a finite {kind.value}, got {preview(value)}")
        return value
    if schema.min is not None and value < schema.min:
        errors.add(path, f"must be at least {schema.min}")
    elif schema.max is not None and value > schema.max:
        errors.add(path, f"must be at most {schema.max}")
    return value


def _is_http_url(value: str) -> bool:
    if len(value) > MAX_URL_CHARS or not value or any(char.isspace() or ord(char) < 32 for char in value):
        return False
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def canonical_json(value: object) -> str:
    """JSON canonique (clés triées, sans espace) : égalité profonde sans confondre `1`, `1.0` et `true`."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


# ------------------------------------------------------------------ manifeste

_MANIFEST_KEYS = frozenset({"schema", "schema_version", "id", "version", "title", "description", "family", "tags",
                            "aliases", "scene", "inputs", "events", "sample", "files"})
_MANIFEST_REQUIRED = frozenset({"schema", "schema_version", "id", "version", "title", "family", "scene", "inputs",
                                "sample", "files"})
_EVENT_KEYS = frozenset({"class", "writes", "payload", "summary"})


@dataclass(frozen=True, slots=True)
class EventDecl:
    name: str
    event_class: EventClass
    payload: InputSchema
    writes: tuple[str, ...] = ()
    summary: str = ""


@dataclass(frozen=True, slots=True)
class PrefabManifest:
    """Manifeste analysé ; `raw` est l'objet JSON tel que publié (copie), base de l'empreinte."""

    prefab_id: str
    version: int
    title: str
    description: str
    family: str
    tags: tuple[str, ...]
    aliases: tuple[str, ...]
    default_size: tuple[float, float] | None
    props: InputSchema
    data: InputSchema
    events: Mapping[str, EventDecl]
    sample_props: Mapping[str, Any]
    sample_data: Mapping[str, Any]
    raw: Mapping[str, Any]

    @property
    def prefab_class(self) -> PrefabClass:
        return prefab_class(self.prefab_id)

    @property
    def ref(self) -> PrefabRef:
        return PrefabRef(self.prefab_id, self.version)


def parse_manifest(raw: object) -> PrefabManifest:
    """Manifeste strict (`docs/prefabs.md` › *Manifest*) ; `PrefabDefinitionError` avec toutes les erreurs vues."""

    errors = _Errors()
    if not isinstance(raw, dict):
        raise PrefabDefinitionError(["manifest must be a JSON object"])
    provenance = sorted(key for key in raw if key in PROVENANCE_FIELDS)
    if provenance:
        errors.add("manifest", f"carries provenance fields {provenance}: provenance is written by Core in "
                               "publication.json, never by the candidate")
    unknown = sorted(str(key)[:40] for key in raw if key not in _MANIFEST_KEYS and key not in PROVENANCE_FIELDS)
    if unknown:
        errors.add("manifest", f"unknown fields {unknown[:5]}")
    missing = sorted(_MANIFEST_REQUIRED - raw.keys())
    if missing:
        errors.add("manifest", f"missing fields {missing}")
    errors.raise_if_any()
    try:
        size = len(canonical_json(raw).encode("utf-8"))
    except (TypeError, ValueError):
        raise PrefabDefinitionError(["manifest must contain finite JSON values only"]) from None
    if size > MAX_MANIFEST_BYTES:
        raise PrefabDefinitionError([f"manifest is {size} bytes, at most {MAX_MANIFEST_BYTES}"])
    if raw["schema"] != MANIFEST_SCHEMA or raw["schema_version"] != SCHEMA_VERSION \
            or type(raw["schema_version"]) is not int:
        errors.add("schema", f"must be {MANIFEST_SCHEMA!r} version {SCHEMA_VERSION}")
    if not is_prefab_id(raw["id"]):
        errors.add("id", f"{preview(raw['id'])} must match {PREFAB_ID.pattern[:-2]} (at most {MAX_PREFAB_ID_CHARS})")
    if not is_version(raw["version"]):
        errors.add("version", f"must be an integer {MIN_VERSION}..{MAX_VERSION}")
    title = _line(raw["title"], "title", MAX_TITLE_CHARS, errors, required=True)
    description = _line(raw.get("description", ""), "description", MAX_DESCRIPTION_CHARS, errors, multi=True)
    family = raw["family"]
    if not isinstance(family, str) or len(family) > MAX_FAMILY_CHARS or not FAMILY.fullmatch(family):
        errors.add("family", f"must be a lowercase token of at most {MAX_FAMILY_CHARS} characters")
    tags = _labels(raw.get("tags", []), "tags", errors)
    aliases = _labels(raw.get("aliases", []), "aliases", errors)
    default_size = _scene(raw["scene"], errors)
    before = errors.count
    props, data = _inputs(raw["inputs"], errors)
    events: dict[str, EventDecl] = {}
    sample_props: dict[str, Any] = {}
    sample_data: dict[str, Any] = {}
    if errors.count == before:
        # Événements et exemple se lisent contre les entrées : analysés seulement si elles le sont.
        events = _events(raw.get("events", {}), props, data, errors)
        sample_props, sample_data = _sample(raw["sample"], props, data, errors)
    if raw["files"] != FILES:
        errors.add("files", f"must be exactly {FILES} in v1")
    errors.raise_if_any()
    return PrefabManifest(
        prefab_id=raw["id"], version=raw["version"], title=title, description=description, family=family,
        tags=tags, aliases=aliases, default_size=default_size, props=props, data=data, events=events,
        sample_props=sample_props, sample_data=sample_data, raw=copy.deepcopy(raw))


def _line(value: object, path: str, limit: int, errors: _Errors, *, required: bool = False,
          multi: bool = False) -> str:
    check = _multi_line if multi else _single_line
    if not isinstance(value, str) or len(value) > limit or not check(value) or (required and not value.strip()):
        errors.add(path, f"must be {'non-empty ' if required else ''}text of at most {limit} characters"
                         f"{'' if multi else ' on one line'}")
        return ""
    return value


def _labels(value: object, path: str, errors: _Errors) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > MAX_LABELS or any(
            not isinstance(item, str) or not item.strip() or len(item) > MAX_LABEL_CHARS or not _single_line(item)
            for item in value):
        errors.add(path, f"must be at most {MAX_LABELS} one-line strings of at most {MAX_LABEL_CHARS} characters")
        return ()
    return tuple(value)


def _scene(value: object, errors: _Errors) -> tuple[float, float] | None:
    if not isinstance(value, dict) or set(value) - {"kind", "default_size"} or value.get("kind") != "window":
        errors.add("scene", "must be {kind: 'window', default_size?: {w, h}} in v1")
        return None
    size = value.get("default_size")
    if size is None:
        return None
    if not isinstance(size, dict) or set(size) != {"w", "h"} or any(
            isinstance(size[key], bool) or not _is_number(size[key]) or not 0 < size[key] <= MAX_SCENE_EXTENT
            for key in ("w", "h")):
        errors.add("scene.default_size", f"must be {{w, h}} with 0 < w, h <= {MAX_SCENE_EXTENT:g} scene units")
        return None
    return float(size["w"]), float(size["h"])


_EMPTY_OBJECT = InputSchema(type=InputType.OBJECT)


def _inputs(value: object, errors: _Errors) -> tuple[InputSchema, InputSchema]:
    if not isinstance(value, dict) or set(value) != {"props", "data"}:
        errors.add("inputs", "must be exactly {props, data}, each an object schema")
        return _EMPTY_OBJECT, _EMPTY_OBJECT
    result = []
    for name in ("props", "data"):
        raw = value[name]
        if not isinstance(raw, dict) or raw.get("type") != "object":
            errors.add(f"inputs.{name}", "must be a schema of type object")
            result.append(_EMPTY_OBJECT)
            continue
        node = _parse_schema(raw, f"inputs.{name}", 0, None, errors)
        result.append(node or _EMPTY_OBJECT)
    return result[0], result[1]


def _events(value: object, props: InputSchema, data: InputSchema, errors: _Errors) -> dict[str, EventDecl]:
    if not isinstance(value, dict) or len(value) > MAX_EVENTS:
        errors.add("events", f"must be an object of at most {MAX_EVENTS} events")
        return {}
    roots = {"props": props, "data": data}
    events: dict[str, EventDecl] = {}
    for name, raw in value.items():
        path = f"events.{str(name)[:40]}"
        if not isinstance(name, str) or not EVENT_NAME.fullmatch(name):
            errors.add(path, f"event name must match {EVENT_NAME.pattern[:-2]}")
            continue
        if not isinstance(raw, dict) or set(raw) - _EVENT_KEYS or "class" not in raw or "payload" not in raw:
            errors.add(path, f"must be {{class, payload, writes?, summary?}} (unknown or missing fields)")
            continue
        try:
            event_class = EventClass(raw["class"])
        except ValueError:
            errors.add(path + ".class", "must be 'state' or 'notify'")
            continue
        writes: tuple[str, ...] = ()
        if event_class is EventClass.STATE:
            listed = raw.get("writes")
            if not isinstance(listed, list) or not listed or any(not isinstance(key, str) for key in listed) \
                    or len(set(listed)) != len(listed):
                errors.add(path + ".writes", "a state event declares at least one distinct data key")
                continue
            outside = sorted(key for key in listed if key not in data.properties)
            if outside:
                errors.add(path + ".writes", f"names keys absent from inputs.data: {outside[:5]}")
                continue
            writes = tuple(listed)
        elif "writes" in raw:
            errors.add(path + ".writes", "is forbidden for a notify event")
            continue
        summary = _line(raw.get("summary", ""), path + ".summary", MAX_EVENT_SUMMARY_CHARS, errors)
        payload_raw = raw["payload"]
        if not isinstance(payload_raw, dict) or payload_raw.get("type") != "object":
            errors.add(path + ".payload", "must be a schema of type object")
            continue
        payload = _parse_schema(payload_raw, path + ".payload", 0, roots, errors)
        if payload is None:
            continue
        if event_class is EventClass.STATE and set(payload.properties) - set(writes):
            errors.add(path + ".payload", "a state payload may only carry the keys it writes")
            continue
        events[name] = EventDecl(name, event_class, payload, writes, summary)
    return events


def _sample(value: object, props: InputSchema, data: InputSchema,
            errors: _Errors) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(value, dict) or set(value) != {"props", "data"}:
        errors.add("sample", "must be exactly {props, data}")
        return {}, {}
    sample_props, problems = validate_value(props, value["props"], "sample.props")
    for problem in problems:
        errors.add("", problem)
    sample_data, problems = validate_value(data, value["data"], "sample.data")
    for problem in problems:
        errors.add("", problem)
    return sample_props, sample_data


# ------------------------------------------------------------------ candidat, lint, empreinte

_CANDIDATE_KEYS = frozenset({"manifest", "template", "style", "behavior"})
_TEMPLATE_TAGS = re.compile(r"<\s*/?\s*(script|style|iframe|object|embed|base|link|meta|form|area)\b", re.IGNORECASE)
#: Une balise ouvrante jusqu'à son `>` : une valeur entre guillemets peut contenir `>` sans fermer la balise.
_TEMPLATE_TAG = re.compile(r"<[a-z](?:[^<>\"']|\"[^\"]*\"|'[^']*')*", re.IGNORECASE)
_QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'")
_TEMPLATE_HANDLER = re.compile(r"[\s/\"']on[a-z][a-z0-9_-]*\s*=", re.IGNORECASE)
_STYLE_IMPORT = re.compile(r"@import", re.IGNORECASE)
_STYLE_URL = re.compile(r"url\(\s*+(?!['\"]?\s*data:)", re.IGNORECASE)
_STYLE_IMAGE_SET = re.compile(r"image-set\(", re.IGNORECASE)
_BEHAVIOR_CLOSE = re.compile(r"</script", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class PrefabBundle:
    """Une version complète : manifeste analysé et les trois sources."""

    manifest: PrefabManifest
    template: str
    style: str
    behavior: str

    def fingerprint(self) -> str:
        return bundle_fingerprint(self.manifest.raw, self.template, self.style, self.behavior)

    def files(self) -> dict[str, str]:
        return {"template": self.template, "style": self.style, "behavior": self.behavior}


def lint_sources(template: str, style: str, behavior: str) -> tuple[str, ...]:
    """Erreurs d'hygiène (`docs/prefabs.md` › *Hygiene lint*) ; vide si propre."""

    errors = _Errors()
    # Une erreur par balise interdite, pas une par occurrence (`<iframe></iframe>` en donne une).
    for tag in dict.fromkeys(match.group(1).lower() for match in _TEMPLATE_TAGS.finditer(template)):
        errors.add("template", f"forbidden tag <{tag}> (structure and code live in the manifest, style and "
                               "behavior)")
    # Valeurs entre guillemets vidées : `title=">"` ne ferme pas la balise, `title="onclick=1"` n'est pas un attribut.
    if any(_TEMPLATE_HANDLER.search(_QUOTED.sub('""', tag.group())) for tag in _TEMPLATE_TAG.finditer(template)):
        errors.add("template", "inline event handler attributes (on*=) are forbidden: use behavior.js")
    if _STYLE_IMPORT.search(style):
        errors.add("style", "@import is forbidden")
    if _STYLE_URL.search(style):
        errors.add("style", "url(...) is allowed only for data: URLs")
    if any(not item.strip().lower().startswith("data:") for item in _image_set_strings(style)):
        errors.add("style", "image-set(...) is allowed only for data: URLs")
    if _BEHAVIOR_CLOSE.search(behavior):
        errors.add("behavior", "'</script' is forbidden in behavior.js")
    return tuple(errors.items)


def _image_set_strings(style: str) -> list[str]:
    """Chaînes entre guillemets passées directement à chaque `image-set(`.

    Les `url(...)` imbriqués relèvent de la règle `url(` ; les `type("...")`
    (niveau 2) ne sont pas des adresses.
    """

    found: list[str] = []
    for match in _STYLE_IMAGE_SET.finditer(style):
        depth, index = 1, match.end()
        while index < len(style) and depth:
            char = style[index]
            if char in "\"'":
                end = style.find(char, index + 1)
                end = len(style) if end < 0 else end
                if depth == 1:
                    found.append(style[index + 1:end])
                index = end + 1
                continue
            depth += {"(": 1, ")": -1}.get(char, 0)
            index += 1
    return found


#: Borne de l'empreinte, calculée sur le pire cas de l'échappement JSON : un caractère de contrôle d'une source
#: (1 octet) devient `\u00XX` (6 octets) ; le manifeste est déjà borné sur son JSON canonique, plus les clés.
#: Un paquet qui respecte les bornes par fichier est donc toujours empreintable.
MAX_FINGERPRINT_BYTES = MAX_MANIFEST_BYTES + 6 * (MAX_TEMPLATE_BYTES + MAX_STYLE_BYTES + MAX_BEHAVIOR_BYTES) + 1024


def bundle_fingerprint(manifest_raw: Mapping[str, Any], template: str, style: str, behavior: str) -> str:
    try:
        return fingerprint({"manifest": dict(manifest_raw), "template": template, "style": style,
                            "behavior": behavior}, max_bytes=MAX_FINGERPRINT_BYTES)
    except PromptError as exc:
        raise PrefabDefinitionError([f"bundle cannot be fingerprinted: {exc}"]) from None


def parse_bundle(manifest_raw: object, template: object, style: object, behavior: object) -> PrefabBundle:
    """Version complète validée : manifeste strict, tailles, hygiène. Toutes les erreurs vues d'un coup."""

    errors = _Errors()
    manifest: PrefabManifest | None = None
    try:
        manifest = parse_manifest(manifest_raw)
    except PrefabDefinitionError as exc:
        for item in exc.errors:
            errors.add("", item)
    sources = {"template": (template, MAX_TEMPLATE_BYTES), "style": (style, MAX_STYLE_BYTES),
               "behavior": (behavior, MAX_BEHAVIOR_BYTES)}
    for name, (text, limit) in sources.items():
        if not isinstance(text, str):
            errors.add(name, "must be a string")
            continue
        size = len(text.encode("utf-8", errors="surrogatepass"))
        if size > limit:
            errors.add(name, f"is {size} bytes, at most {limit}")
        elif "\x00" in text:
            errors.add(name, "must not contain NUL characters")
    if all(isinstance(text, str) for text, _ in sources.values()):
        for item in lint_sources(template, style, behavior):  # type: ignore[arg-type]
            errors.add("", item)
    errors.raise_if_any()
    assert manifest is not None
    bundle = PrefabBundle(manifest, template, style, behavior)  # type: ignore[arg-type]
    bundle.fingerprint()  # refuse ici un paquet impossible à empreinter
    return bundle


def parse_candidate(raw: object) -> PrefabBundle:
    """Candidat `{manifest, template, style, behavior}` d'un auteur (cerveau, UI)."""

    if not isinstance(raw, dict) or set(raw) != _CANDIDATE_KEYS:
        found = sorted(str(key)[:40] for key in raw) if isinstance(raw, dict) else type(raw).__name__
        raise PrefabDefinitionError([f"candidate must be exactly {{manifest, template, style, behavior}}, "
                                     f"got {found}"])
    return parse_bundle(raw["manifest"], raw["template"], raw["style"], raw["behavior"])


def with_version(raw: Mapping[str, Any], version: int) -> dict[str, Any]:
    """Copie du manifeste à la version que Core attribue (la version est le nom du dossier, posé par Core)."""

    result = copy.deepcopy(dict(raw))
    result["version"] = version
    return result


# ------------------------------------------------------------------ publication


@dataclass(frozen=True, slots=True)
class BaseEditRecord:
    user_request: str
    witness: str
    confirmed_by_user: bool = True

    def __post_init__(self) -> None:
        if self.confirmed_by_user is not True:
            raise PrefabDefinitionError(["base_edit.confirmed_by_user must be true"])
        if not isinstance(self.user_request, str) \
                or not MIN_USER_REQUEST_CHARS <= len(self.user_request.strip()) <= MAX_USER_REQUEST_CHARS:
            raise PrefabDefinitionError([f"base_edit.user_request must be {MIN_USER_REQUEST_CHARS}.."
                                         f"{MAX_USER_REQUEST_CHARS} characters"])
        if not isinstance(self.witness, str) or not self.witness.startswith(WITNESS_PREFIX) \
                or len(self.witness) > MAX_WITNESS_CHARS or not _single_line(self.witness) \
                or self.witness == WITNESS_PREFIX:
            raise PrefabDefinitionError([f"base_edit.witness must be '{WITNESS_PREFIX}<event_id>'"])

    def to_dict(self) -> dict[str, Any]:
        return {"confirmed_by_user": True, "user_request": self.user_request, "witness": self.witness}


@dataclass(frozen=True, slots=True)
class Provenance:
    origin: ProvenanceOrigin
    created_by: CreatorActor
    derived_from: PrefabRef | None = None
    base_edit: BaseEditRecord | None = None

    def __post_init__(self) -> None:
        origin = ProvenanceOrigin(self.origin)
        if origin in (ProvenanceOrigin.BASE, ProvenanceOrigin.CUSTOM) and self.derived_from is not None:
            raise PrefabDefinitionError([f"provenance.derived_from must be null for origin {origin.value}"])
        if origin in (ProvenanceOrigin.FORK, ProvenanceOrigin.REVISION, ProvenanceOrigin.BASE_EDIT) \
                and self.derived_from is None:
            raise PrefabDefinitionError([f"provenance.derived_from is required for origin {origin.value}"])
        if (origin is ProvenanceOrigin.BASE_EDIT) != (self.base_edit is not None):
            raise PrefabDefinitionError(["provenance.base_edit is set exactly when origin is base_edit"])

    def to_dict(self) -> dict[str, Any]:
        return {"origin": ProvenanceOrigin(self.origin).value,
                "derived_from": None if self.derived_from is None else self.derived_from.to_dict(),
                "created_by": {"actor": CreatorActor(self.created_by).value},
                "base_edit": None if self.base_edit is None else self.base_edit.to_dict()}


@dataclass(frozen=True, slots=True)
class Publication:
    """`publication.json` (Core-written) : empreinte, date, provenance."""

    prefab_id: str
    version: int
    fingerprint: str
    published_at: str
    provenance: Provenance

    def __post_init__(self) -> None:
        PrefabRef(self.prefab_id, self.version)
        if not isinstance(self.fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", self.fingerprint):
            raise PrefabDefinitionError(["publication.fingerprint must be a sha256 hex digest"])
        if not isinstance(self.published_at, str) \
                or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", self.published_at):
            raise PrefabDefinitionError(["publication.published_at must be YYYY-MM-DDTHH:MM:SSZ"])
        derived = self.provenance.derived_from
        origin = ProvenanceOrigin(self.provenance.origin)
        if origin in (ProvenanceOrigin.REVISION, ProvenanceOrigin.BASE_EDIT) and derived is not None \
                and derived.prefab_id != self.prefab_id:
            raise PrefabDefinitionError([f"a {origin.value} derives from an earlier version of the same id"])
        if origin in (ProvenanceOrigin.REVISION, ProvenanceOrigin.BASE_EDIT) and derived is not None \
                and derived.version >= self.version:
            raise PrefabDefinitionError([f"a {origin.value} derives from an earlier version than v{self.version}, "
                                         f"not v{derived.version}"])
        if origin is ProvenanceOrigin.FORK and derived is not None and derived.prefab_id == self.prefab_id:
            raise PrefabDefinitionError(["a fork derives from another prefab id"])
        if (origin is ProvenanceOrigin.BASE_EDIT or origin is ProvenanceOrigin.BASE) \
                != (prefab_class(self.prefab_id) is PrefabClass.BASE):
            raise PrefabDefinitionError([f"origin {origin.value} does not fit the {prefab_class(self.prefab_id).value}"
                                         f" id {self.prefab_id}"])

    @property
    def ref(self) -> PrefabRef:
        return PrefabRef(self.prefab_id, self.version)

    def to_dict(self) -> dict[str, Any]:
        return {"schema": PUBLICATION_SCHEMA, "schema_version": SCHEMA_VERSION, "prefab_id": self.prefab_id,
                "version": self.version, "fingerprint": self.fingerprint, "published_at": self.published_at,
                "provenance": self.provenance.to_dict()}

    def render(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, allow_nan=False) + "\n"

    @classmethod
    def from_dict(cls, raw: object) -> Publication:
        keys = {"schema", "schema_version", "prefab_id", "version", "fingerprint", "published_at", "provenance"}
        if not isinstance(raw, dict) or set(raw) != keys:
            raise PrefabDefinitionError([f"publication must be exactly {sorted(keys)}"])
        if raw["schema"] != PUBLICATION_SCHEMA or raw["schema_version"] != SCHEMA_VERSION:
            raise PrefabDefinitionError([f"publication schema must be {PUBLICATION_SCHEMA!r} v{SCHEMA_VERSION}"])
        prov = raw["provenance"]
        if not isinstance(prov, dict) or set(prov) != {"origin", "derived_from", "created_by", "base_edit"}:
            raise PrefabDefinitionError(["publication.provenance must be {origin, derived_from, created_by, "
                                         "base_edit}"])
        created = prov["created_by"]
        if not isinstance(created, dict) or set(created) != {"actor"}:
            raise PrefabDefinitionError(["publication.provenance.created_by must be {actor}"])
        base_edit = prov["base_edit"]
        if base_edit is not None and (not isinstance(base_edit, dict)
                                      or set(base_edit) != {"confirmed_by_user", "user_request", "witness"}):
            raise PrefabDefinitionError(["publication.provenance.base_edit must be {confirmed_by_user, "
                                         "user_request, witness}"])
        try:
            provenance = Provenance(
                origin=ProvenanceOrigin(prov["origin"]), created_by=CreatorActor(created["actor"]),
                derived_from=None if prov["derived_from"] is None else PrefabRef.from_dict(prov["derived_from"]),
                base_edit=None if base_edit is None else BaseEditRecord(
                    base_edit["user_request"], base_edit["witness"], base_edit["confirmed_by_user"]))
        except ValueError as exc:
            if isinstance(exc, PrefabDefinitionError):
                raise
            raise PrefabDefinitionError([f"publication.provenance: {exc}"]) from None
        return cls(raw["prefab_id"], raw["version"], raw["fingerprint"], raw["published_at"], provenance)

    @classmethod
    def decode_text(cls, text: str) -> Publication:
        return cls.from_dict(decode_json_text(text, MAX_PUBLICATION_BYTES, "publication"))


def format_published_at(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise ValueError("published_at must be timezone-aware")
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def decode_json_text(text: str, limit: int, what: str) -> Any:
    if len(text.encode("utf-8", errors="surrogatepass")) > limit:
        raise PrefabDefinitionError([f"{what} exceeds {limit} bytes"])
    try:
        return json.loads(text, parse_constant=_no_constant)
    except (ValueError, RecursionError) as exc:
        raise PrefabDefinitionError([f"{what} is not valid JSON: {str(exc)[:120]}"]) from None


def _no_constant(name: str) -> Any:
    raise ValueError(f"{name} is not JSON")


# ------------------------------------------------------------------ verrou du catalogue de base


@dataclass(frozen=True, slots=True)
class LockEntry:
    prefab_id: str
    version: int
    fingerprint: str

    @property
    def key(self) -> tuple[str, int]:
        return self.prefab_id, self.version

    def to_dict(self) -> dict[str, Any]:
        return {"prefab_id": self.prefab_id, "version": self.version, "fingerprint": self.fingerprint}


@dataclass(frozen=True, slots=True)
class CatalogLock:
    """`catalog.lock.json` des prefabs de base (`jarvis.prefab.catalog_lock` v1, motif du Test Lab)."""

    entries: tuple[LockEntry, ...] = ()

    @property
    def index(self) -> dict[tuple[str, int], LockEntry]:
        return {entry.key: entry for entry in self.entries}

    def render(self) -> str:
        body = {"schema": CATALOG_LOCK_SCHEMA, "schema_version": SCHEMA_VERSION,
                "entries": [entry.to_dict() for entry in sorted(self.entries, key=lambda item: item.key)]}
        return json.dumps(body, ensure_ascii=False, indent=2) + "\n"

    @classmethod
    def decode_text(cls, text: str) -> CatalogLock:
        raw = decode_json_text(text, MAX_LOCK_BYTES, "catalog lock")
        if not isinstance(raw, dict) or set(raw) != {"schema", "schema_version", "entries"} \
                or raw["schema"] != CATALOG_LOCK_SCHEMA or raw["schema_version"] != SCHEMA_VERSION \
                or not isinstance(raw["entries"], list) or len(raw["entries"]) > MAX_LOCK_ENTRIES:
            raise PrefabDefinitionError([f"catalog lock must be {{schema: {CATALOG_LOCK_SCHEMA!r}, schema_version: "
                                         f"{SCHEMA_VERSION}, entries: [...]}}"])
        entries = []
        for index, item in enumerate(raw["entries"]):
            if not isinstance(item, dict) or set(item) != {"prefab_id", "version", "fingerprint"} \
                    or not is_prefab_id(item["prefab_id"]) or prefab_class(item["prefab_id"]) is not PrefabClass.BASE \
                    or not is_version(item["version"]) or not isinstance(item["fingerprint"], str) \
                    or not re.fullmatch(r"[0-9a-f]{64}", item["fingerprint"]):
                raise PrefabDefinitionError([f"catalog lock entries[{index}] must be {{prefab_id: jarvis.*, "
                                             "version, fingerprint}"])
            entries.append(LockEntry(item["prefab_id"], item["version"], item["fingerprint"]))
        keys = [entry.key for entry in entries]
        if len(set(keys)) != len(keys):
            raise PrefabDefinitionError(["catalog lock locks a version twice"])
        return cls(tuple(entries))


LOCK_UNLOCKED = "prefab_lock_unlocked"
LOCK_DRIFT = "prefab_lock_fingerprint_drift"
LOCK_ORPHAN = "prefab_lock_orphan"


def check_lock_coverage(found: Mapping[tuple[str, int], str], lock: CatalogLock) -> tuple[tuple[str, str], ...]:
    """`(code, message)` pour chaque écart entre les versions de base trouvées (`{(id, v): empreinte}`) et le verrou.

    Édition sans nouvelle version -> dérive ; version neuve non verrouillée ->
    `unlocked` ; version verrouillée disparue -> `orphan` (une instance de
    scène peut encore la référencer).
    """

    problems: list[tuple[str, str]] = []
    index = lock.index
    for key, digest in sorted(found.items()):
        entry = index.get(key)
        if entry is None:
            problems.append((LOCK_UNLOCKED, f"{key[0]} v{key[1]} is not in catalog.lock.json; lock it with its "
                                            "fingerprint"))
        elif entry.fingerprint != digest:
            problems.append((LOCK_DRIFT, f"{key[0]} v{key[1]} was edited in place; publish a new version or "
                                         "restore the locked content"))
    for key in sorted(index):
        if key not in found:
            problems.append((LOCK_ORPHAN, f"{key[0]} v{key[1]} is locked but its folder is missing; published "
                                          "versions are kept"))
    return tuple(problems)


# ------------------------------------------------------------------ événements d'état (Slice 04)


class StateEventOutcome(StrEnum):
    OK = "ok"
    STALE = "stale"
    REFUSED = "refused"


@dataclass(frozen=True, slots=True)
class StateEventCheck:
    outcome: StateEventOutcome
    #: `{**data, **payload}` validé et complété, seulement si `ok`.
    merged: Mapping[str, Any] | None = None
    detail: str = ""


def check_state_event(manifest: PrefabManifest, event: str, payload: object, basis: object,
                      current_data: Mapping[str, Any]) -> StateEventCheck:
    """Étapes 2-5 du contrat *Events* (l'étape 1, l'objet, est au service) ; pur."""

    def refuse(message: str) -> StateEventCheck:
        return StateEventCheck(StateEventOutcome.REFUSED, detail=clip_message(message))

    decl = manifest.events.get(event) if isinstance(event, str) else None
    if decl is None:
        return refuse(f"event {preview(event)} is not declared by {manifest.prefab_id}@{manifest.version}")
    if decl.event_class is not EventClass.STATE:
        return refuse(f"event {event} is a notify event; it writes nothing")
    if not isinstance(payload, dict) or not payload:
        return refuse("a state payload is a non-empty object of written keys")
    outside = sorted(str(key)[:40] for key in payload if key not in decl.writes)
    if outside:
        return refuse(f"payload writes undeclared keys {outside[:5]}; {event} writes {list(decl.writes)}")
    try:
        size = len(canonical_json(payload).encode("utf-8"))
    except (TypeError, ValueError):
        return refuse("payload must contain finite JSON values only")
    if size > MAX_STATE_EVENT_PAYLOAD_BYTES:
        return refuse(f"payload is {size} bytes, at most {MAX_STATE_EVENT_PAYLOAD_BYTES}")
    _, problems = validate_value(decl.payload, payload, "payload")
    if problems:
        return refuse("; ".join(problems[:3]))
    if not isinstance(basis, dict):
        return refuse("basis must be an object of the written keys' last known values")
    for key in payload:
        # Une clé absente vaut `null`, des deux côtés : absente des données
        # courantes, ou absente de la basis (le cadre ne l'a jamais vue). Une
        # seule règle, celle que l'hôte applique en posant `null` (A2).
        try:
            seen = canonical_json(basis.get(key))
        except (TypeError, ValueError):
            return refuse(f"basis.{key} must contain finite JSON values only")
        if seen != canonical_json(current_data.get(key)):
            return StateEventCheck(StateEventOutcome.STALE, detail=f"data.{key} changed since the frame last saw it")
    merged, problems = validate_value(manifest.data, {**current_data, **payload}, "data")
    if problems:
        return refuse("; ".join(problems[:3]))
    return StateEventCheck(StateEventOutcome.OK, merged=merged)

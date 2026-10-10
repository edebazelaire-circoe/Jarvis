"""Variables typées partagées entre les contrôles d'une scène et les `inputProps` d'une composition Remotion (handoff
jarvis-remotion-presentation-integration, Slice 13 ; contrat `docs/presentation-studio.md` > *Typed variables and fast edits*,
`docs/remotion-isolation.md` § 12). Module PUR : aucune E/S.

Il n'y a **pas** de second éditeur ni de second schéma : le schéma des propriétés d'une composition Remotion EST le
`inputs.props` / `inputs.data` du manifeste, et les contrôles sont les `StudioControl` existants (`props.<clé>` / `data.<clé>`).
Ce module ne fait que trois choses, pour les deux moteurs :

1. **Typer** un contrôle (`control_kind`) : `color`, `text`, `spacing`, `timing`, `motion`, `data` ou `value`, déduit du type du
   manifeste, de sa racine (`data`), de son groupe curé et de son nom. Rien n'est stocké : c'est une lecture.
2. **Dire ce qu'un moteur ne porte pas** (`engine_support`) : une règle fermée et lisible, jamais un repli silencieux. Aujourd'hui,
   le bac à sable Remotion n'a aucun réseau : une valeur `url` n'y a aucun sens (les images passent par `staticFile`, dans la source),
   et la clé `data` des `inputProps` est réservée au bloc `data` du manifeste. Ces paramètres sont **étiquetés non pris en charge** (avec
   la raison), retirés du contrat d'`inputProps` (`withheld`) et refusés à l'édition ; ils restent déclarés, jamais cachés.
3. **Construire les `inputProps`** (`build_input_props`) : ce qui traverse vers le bac à sable est validé avant de traverser (type,
   bornes du manifeste, JSON simple, aucun nom réservé, puis le **même** calcul de budget que le bac à sable sur l'objet fusionné :
   `sandbox_budget` = `jsonBudget` de `remotion_sandbox_protocol.js`), complété des défauts, privé des paramètres retirés. Ce que la page
   accepte, le bac à sable l'accepte. Les
   valeurs de `data` ne voyagent que sous la clé réservée `data`, et seulement si le manifeste en déclare.

`control_center_remotion_props.js` rejoue exactement la même construction côté navigateur (même contrat, mêmes bornes) ; la parité est
testée sur un tableau de cas commun (`tests/fixtures/remotion_input_props_cases.json`).
"""

from __future__ import annotations

from collections.abc import Mapping
import copy
from dataclasses import dataclass
from enum import StrEnum
import math
import re
from typing import Any

from jarvis.domain.prefab import InputSchema, InputType, PrefabManifest, parse_input_schema, validate_value
from jarvis.domain.presentation_studio_engine import Engine

#: Bornes alignées sur celles du protocole du bac à sable (`remotion_sandbox_protocol.js`, `LIMITS`) : ce qui passe ici passe là-bas.
MAX_INPUT_BYTES = 64 * 1024
MAX_DEPTH = 8
MAX_NODES = 2000
#: Clé des `inputProps` qui porte le bloc `data` du manifeste.
DATA_KEY = "data"
UNSAFE_KEYS = frozenset({"__proto__", "constructor", "prototype"})


class ControlKind(StrEnum):
    COLOR = "color"
    TEXT = "text"
    SPACING = "spacing"
    TIMING = "timing"
    MOTION = "motion"
    DATA = "data"
    VALUE = "value"


_WORDS = re.compile(r"[a-z]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_TIMING = frozenset({"duration", "delay", "stagger", "fade", "frames", "frame", "ms", "seconds", "interval", "timing", "speed",
                     "start", "end", "offset_frames", "lag", "hold"})
_SPACING = frozenset({"margin", "padding", "gap", "spacing", "space", "radius", "size", "width", "height", "inset", "gutter",
                      "indent", "offset", "border", "stroke", "font", "scale"})


def _words(path: str) -> set[str]:
    return set(_WORDS.findall(_CAMEL.sub("_", path.split(".", 1)[-1]).lower().replace("_", " ")))


def control_kind(path: str, node: InputSchema, group: str) -> ControlKind:
    """Le genre d'un contrôle. `path` : `props.x` / `data.x` ; `group` : le groupe curé (`content|visual|layout|motion`)."""

    if path.split(".", 1)[0] == "data":
        return ControlKind.DATA
    if node.type is InputType.COLOR:
        return ControlKind.COLOR
    if node.type in (InputType.STRING, InputType.TEXT, InputType.URL):
        return ControlKind.TEXT
    words = _words(path)
    if node.type in (InputType.NUMBER, InputType.INTEGER, InputType.BOOLEAN, InputType.ENUM):
        if words & _TIMING:
            return ControlKind.TIMING
        if words & _SPACING or group == "layout":
            return ControlKind.SPACING
        if group == "motion":
            return ControlKind.MOTION
    return ControlKind.VALUE


# ------------------------------------------------------------------ ce qu'un moteur ne porte pas

URL_REASON = ("the Remotion sandbox has no network: an image or a link cannot be loaded from an address (ship the file in the "
              "source and read it with staticFile)")
RESERVED_REASON = f"the property name {DATA_KEY!r} is reserved for the manifest's data block in a Remotion scene's inputProps"


def engine_of(manifest: PrefabManifest) -> Engine:
    """Le moteur d'une source : Remotion pour un manifeste à bloc `source` (v2+), sinon Slidecar."""

    return Engine.REMOTION if manifest.source is not None else Engine.SLIDECAR


def own_reason(engine: Engine, node: InputSchema, path: str) -> str | None:
    """Règle fermée sur CE nœud seul (`_prune` s'en sert pour ne retirer que la feuille concernée)."""

    if engine is Engine.REMOTION:
        if node.type is InputType.URL:
            return URL_REASON
        if path == f"props.{DATA_KEY}":
            return RESERVED_REASON
    return None


def unsupported_reason(engine: Engine, node: InputSchema, path: str) -> str | None:
    """Pourquoi ce nœud ne peut pas être porté **en entier** par `engine` (`None` : porté). Un objet ou une liste qui contient un
    paramètre non porté ne l'est pas : écrire cette valeur en perdrait une partie en silence (`props.card` dont `image` est une `url`)."""

    own = own_reason(engine, node, path)
    if own is not None:
        return own
    children: list[tuple[str, InputSchema]] = []
    if node.type is InputType.OBJECT:
        children = [(f"{path}.{name}", child) for name, child in node.properties.items()]
    elif node.type is InputType.ARRAY and node.items is not None:
        children = [(f"{path}[]", node.items)]
    for child_path, child in children:
        inner = unsupported_reason(engine, child, child_path)
        if inner is not None:
            return f"{child_path} cannot be carried: {inner}"
    return None


def engine_support(engine: Engine, node: InputSchema, path: str) -> dict[str, Any]:
    reason = unsupported_reason(engine, node, path)
    return {"status": "supported" if reason is None else "unsupported", "reason": reason or ""}


# ------------------------------------------------------------------ le contrat d'inputProps d'une composition

def _prune(raw: Mapping[str, Any], path: str, engine: Engine, node: InputSchema, withheld: list[dict[str, str]]) -> dict[str, Any] | None:
    """Copie de `raw` sans les paramètres que `engine` ne porte pas ; `None` : le nœud entier est retiré. Un tableau dont les
    éléments contiennent un paramètre retiré est retiré en entier (on ne porte pas la moitié d'une liste)."""

    reason = own_reason(engine, node, path)
    if reason is not None:
        withheld.append({"path": path, "reason": reason})
        return None
    wire = copy.deepcopy(dict(raw))
    if node.type is InputType.OBJECT:
        kept: dict[str, Any] = {}
        for name, child in node.properties.items():
            sub = _prune(raw["properties"][name], f"{path}.{name}", engine, child, withheld)
            if sub is not None:
                kept[name] = sub
        wire["properties"] = kept
        if "required" in wire:
            wire["required"] = [name for name in wire["required"] if name in kept]
    elif node.type is InputType.ARRAY and node.items is not None:
        before = len(withheld)
        sub = _prune(raw["items"], f"{path}[]", engine, node.items, withheld)
        if sub is None or len(withheld) != before:
            del withheld[before:]
            withheld.append({"path": path, "reason": "its items hold a parameter this engine cannot carry"})
            return None
        wire["items"] = sub
    return wire


def input_contract(manifest: PrefabManifest, engine: Engine | None = None) -> dict[str, Any]:
    """`{engine, props, data, withheld, carries_data}` : les schémas (forme du manifeste) de ce qui traverse vers le bac à sable,
    sans les paramètres que le moteur ne porte pas, et la liste explicite de ceux qui sont retirés. JSON pur, sans chemin disque."""

    engine = engine or engine_of(manifest)
    inputs = manifest.raw.get("inputs", {})
    withheld: list[dict[str, str]] = []
    schemas: dict[str, Any] = {}
    for root, node in (("props", manifest.props), ("data", manifest.data)):
        pruned = _prune(inputs.get(root, {"type": "object", "properties": {}}), root, engine, node, withheld)
        schemas[root] = pruned if pruned is not None else {"type": "object", "properties": {}}
    carries_data = bool(schemas["data"].get("properties")) and not any(item["path"] == f"props.{DATA_KEY}" for item in withheld)
    return {"engine": engine.value, "props": schemas["props"], "data": schemas["data"], "withheld": withheld,
            "carries_data": carries_data}


@dataclass(frozen=True, slots=True)
class InputPropsResult:
    ok: bool
    input_props: dict[str, Any]
    problems: tuple[str, ...] = ()
    #: Les chemins retirés du contrat que la valeur portait (ignorés, dits).
    dropped: tuple[str, ...] = ()


MAX_SAFE_INTEGER = 2**53 - 1


def _has_surrogate(text: str) -> bool:
    """`json.loads` joins a valid pair into one character: any surrogate code point left is a lone one (JavaScript's `isWellFormed`)."""

    return any(0xD800 <= ord(char) <= 0xDFFF for char in text)


def _finite(value: int | float) -> bool:
    try:
        return math.isfinite(float(value))   # a 400-digit int overflows float(): not finite, as JavaScript reads it
    except OverflowError:
        return False


def _utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def sandbox_budget(value: object, limit: int = MAX_INPUT_BYTES) -> bool:
    """Le calcul de `jsonBudget` (`remotion_sandbox_protocol.js`) à l'identique : null 4, booléen 5, nombre 8, chaîne UTF-16 + 2,
    clé UTF-16 + 3 ; `MAX_DEPTH` niveaux, `MAX_NODES` valeurs, clé de 200 au plus. Appliqué à l'objet **fusionné** que reçoit le bac à sable."""

    spent = [0, 0]   # bytes, nodes

    def walk(item: object, depth: int) -> bool:
        if depth > MAX_DEPTH:
            return False
        spent[1] += 1
        if spent[1] > MAX_NODES or spent[0] > limit:
            return False
        if item is None:
            spent[0] += 4
            return True
        if isinstance(item, str):
            spent[0] += _utf16_length(item) + 2
            return spent[0] <= limit
        if isinstance(item, bool):
            spent[0] += 5
            return True
        if isinstance(item, (int, float)):
            spent[0] += 8
            return _finite(item)
        if isinstance(item, list):
            if len(item) > MAX_NODES:
                return False
            return all(walk(child, depth + 1) for child in item) and spent[0] <= limit
        if isinstance(item, dict):
            for key, child in item.items():
                if key == "__proto__" or _utf16_length(key) > 200:
                    return False
                spent[0] += _utf16_length(key) + 3
                if not walk(child, depth + 1):
                    return False
            return spent[0] <= limit
        return False

    return walk(value, 0) and spent[0] <= limit


def _budget(value: object, depth: int, counter: list[int]) -> str | None:
    """Premier défaut de forme : JSON simple, profondeur, nombre de nœuds, noms réservés. `None` : propre."""

    counter[0] += 1
    if counter[0] > MAX_NODES:
        return f"more than {MAX_NODES} values"
    if depth > MAX_DEPTH:
        return f"nesting deeper than {MAX_DEPTH}"
    if isinstance(value, str):
        return "a string is not valid Unicode (lone surrogate)" if _has_surrogate(value) else None
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return None if _finite(value) else "a number is not finite"
    if isinstance(value, list):
        for item in value:
            problem = _budget(item, depth + 1, counter)
            if problem:
                return problem
        return None
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                return "an object key is not a string"
            if key in UNSAFE_KEYS:
                return f"the reserved key {key!r}"
            if _has_surrogate(key):
                return "an object key is not valid Unicode (lone surrogate)"
            problem = _budget(item, depth + 1, counter)
            if problem:
                return problem
        return None
    return f"a value of type {type(value).__name__} is not plain JSON"


def build_input_props(contract: Mapping[str, Any], props: object, data: object = None) -> InputPropsResult:
    """Valide `props` (et `data`) contre le contrat, complète des défauts, rend les `inputProps`. Ne lève jamais sur une valeur :
    `ok=False` et des problèmes nommés par chemin. `data` que le contrat ne porte pas est ignoré et dit (`dropped`)."""

    try:
        return _build(contract, props, data)
    except Exception as error:  # noqa: BLE001 - intentional: a hostile value is a typed refusal, never an exception at this door
        return InputPropsResult(False, {}, (f"inputProps refused: {type(error).__name__}",))


def _normalise(schema: InputSchema, value: Any, path: str, problems: list[str]) -> Any:
    """Entiers : un flottant intégral et sûr (`2.0`) vaut l'entier, comme JavaScript le lit ; un entier hors `±(2**53-1)` est refusé."""

    if schema.type is InputType.OBJECT and isinstance(value, dict):
        return {key: _normalise(schema.properties[key], item, f"{path}.{key}", problems) if key in schema.properties else item
                for key, item in value.items()}
    if schema.type is InputType.ARRAY and isinstance(value, list) and schema.items is not None:
        return [_normalise(schema.items, item, f"{path}[]", problems) for item in value]
    if schema.type is InputType.INTEGER and not isinstance(value, bool):
        if isinstance(value, float) and value.is_integer() and abs(value) <= MAX_SAFE_INTEGER:
            return int(value)
        if isinstance(value, int) and abs(value) > MAX_SAFE_INTEGER:
            problems.append(f"{path}: an integer beyond +/-{MAX_SAFE_INTEGER} is not exact")
    return value


def _build(contract: Mapping[str, Any], props: object, data: object) -> InputPropsResult:
    problems: list[str] = []
    dropped: list[str] = []
    props = {} if props is None else props
    if not isinstance(props, dict):
        return InputPropsResult(False, {}, ("props must be an object",))
    carries = contract.get("carries_data") is True
    roots = [("props", props)]
    if carries:
        data = {} if data is None else data
        if not isinstance(data, dict):
            return InputPropsResult(False, {}, ("data must be an object",))
        roots.append(("data", data))
    elif isinstance(data, dict) and data:
        dropped.append("data")
    for label, value in roots:
        problem = _budget(value, 0, [0])
        if problem:
            problems.append(f"{label}: {problem}")
    if problems:
        return InputPropsResult(False, {}, tuple(problems))
    withheld = {item["path"] for item in contract["withheld"]}
    out: dict[str, Any] = {}
    for root, values in roots:
        schema = parse_input_schema(contract[root], root)
        kept = _normalise(schema, _drop_nested(values, root, withheld, dropped), root, problems)
        result, errors = validate_value(schema, kept, root)
        problems.extend(errors)
        out[root] = result
    if problems:
        return InputPropsResult(False, {}, tuple(problems[:8]), tuple(dropped))
    input_props = dict(out["props"])
    if carries:
        input_props[DATA_KEY] = out["data"]
    if not sandbox_budget(input_props):
        return InputPropsResult(False, {}, ("inputProps exceed the sandbox budget (size, depth or number of values)",), tuple(dropped))
    return InputPropsResult(True, input_props, (), tuple(dropped))


def _drop_nested(value: Any, path: str, withheld: set[str], dropped: list[str]) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            child = f"{path}.{key}"
            if child in withheld:
                dropped.append(child)
                continue
            out[key] = _drop_nested(item, child, withheld, dropped)
        return out
    if isinstance(value, list):
        return [_drop_nested(item, f"{path}[]", withheld, dropped) for item in value]
    return value

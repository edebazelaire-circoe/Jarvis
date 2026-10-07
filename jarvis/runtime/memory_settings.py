"""Réglages mémoire : lus avec tolérance, écrits sans indulgence, décrits au serveur.

`jarvis.domain.memory_settings` dit ce qu'est un réglage valide. Ce module fait
le reste du chemin, sur le modèle de `agent_routing` : le bloc vit sous la clé
`memory` de `control-center-settings.json` (aucun fichier, aucune migration).

- **lire est tolérant.** Un bloc abîmé, une clé inconnue, une valeur hors
  bornes retombent champ par champ sur le défaut ; une combinaison devenue
  incohérente (fichier édité à la main) est dégradée vers le plus sûr, jamais
  levée : l'écran doit toujours s'ouvrir.
- **écrire est strict.** Toute la requête est vérifiée avant la moindre
  écriture ; un seul champ douteux la refuse en entier avec un code stable.
  Les clés inconnues sont conservées (une version plus récente peut les poser).
- **un secret ne passe jamais ici.** Un jeton vit dans `credentials` ; ce bloc
  refuse toute clé qui y ressemble, et l'état publié ne dit que `has_secret`.
- **les loadouts d'agents** (`memory.loadouts`, Slice 09) sont une table de règles
  par clé `<profil>` ou `<profil>:<rôle>`, pas des champs plats : correctif par
  clé (`null` retire la règle et rend la main au préréglage), refus net d'un champ
  inconnu ou du scope privé sans `allow_private`. Lecture tolérante : une règle
  abîmée est ignorée, donc le préréglage (le plus restrictif) s'applique ;
- **une seule table décrit tout** (`_FIELDS`) : lecture, écriture, variables
  d'environnement et schéma servi à l'interface, qui ne code aucune borne.

Précédence d'un champ : variable d'environnement, puis fichier, puis défaut.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields as dc_fields
from enum import StrEnum
import math
import os
import re
from typing import Any
from urllib.parse import urlparse

from jarvis.domain.knowledge import MAX_LOADOUT_ENTRIES
from jarvis.domain.memory import MAX_RECALL_TIMEOUT_MS, MIN_RECALL_TIMEOUT_MS, check_scope
from jarvis.domain.memory_settings import (
    LOADOUT_PROFILES,
    LOADOUT_ROLES,
    MAX_CANDIDATES_PER_RUN,
    MAX_SETTINGS_RECALL_ITEMS,
    MAX_SERVICE_ID_CHARS,
    MAX_URL_CHARS,
    SERVICE_ID,
    ConsolidationMode,
    ConsolidationSettings,
    EmbeddingProviderId,
    KnowledgeSettings,
    LoadoutPolicy,
    LoadoutRule,
    MemorySettings,
    RecallSettings,
    SemanticSettings,
    TencentSettings,
    check_loadout_key,
)
from jarvis.runtime import credentials

#: Clé unique du bloc dans `control-center-settings.json`.
SETTING_KEY = "memory"
ENV_PREFIX = "JARVIS_MEMORY_"

SOURCE_DEFAULT = "default"
SOURCE_FILE = "file"
SOURCE_ENV = "env"

_SECTIONS: tuple[tuple[str, type], ...] = (
    ("recall", RecallSettings),
    ("semantic", SemanticSettings),
    ("consolidation", ConsolidationSettings),
    ("tencent", TencentSettings),
    ("knowledge", KnowledgeSettings),
)
_SECTION_NAMES = frozenset(name for name, _kind in _SECTIONS)
_SECTION_LABELS = {
    "recall": "Rappel",
    "semantic": "Recherche sémantique",
    "consolidation": "Consolidation",
    "tencent": "Sidecar Tencent",
    "knowledge": "Connaissances",
}
#: Jeton utilisé par chaque jambe : un fournisseur `credentials`, jamais une valeur.
_SECRET_PROVIDERS = {"semantic": "openai", "tencent": "tencent"}
#: Un nom de clé est « secret » si, sans ponctuation ni casse, il contient l'un de ces
#: radicaux ou finit par `token` (`max_tokens`, un compteur, ne l'est pas), ou si l'un de
#: ses mots est dans `_SECRET_WORDS`.
_SECRET_SUBSTRINGS = (
    "password", "passwd", "passphrase", "secret", "bearer", "credential", "authorization",
    "apikey", "privatekey", "accesskey",
)
_SECRET_WORDS = frozenset({"pwd", "auth", "token"})
_WORD = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")
#: Profondeur maximale d'une requête : au-delà, refus net plutôt qu'un RecursionError.
MAX_PAYLOAD_DEPTH = 16
MAX_ENV_DIGITS = 18
#: Champ en lecture seule : un aller-retour de l'interface peut le renvoyer, il n'est jamais écrit.
_READ_ONLY_KEYS = frozenset({"has_secret"})
#: Clé du bloc des loadouts, hors `_SECTIONS` : ce n'est pas une section de champs plats.
LOADOUTS_KEY = "loadouts"
MAX_LOADOUT_RULES = len(LOADOUT_PROFILES) * (1 + len(LOADOUT_ROLES))
_RULE_BOOLS = ("allow_private", "wiki", "codegraph", "skills")
_RULE_FIELDS = frozenset({"memory_scopes", *_RULE_BOOLS})
_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


class MemorySettingsError(ValueError):
    """Refus explicite : le code est stable, le message n'inclut jamais une valeur."""

    def __init__(self, code: str, message: str, field: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.field = field


# ------------------------------------------------------------------- la table


def _plain(value: Any) -> Any:
    return str(value) if isinstance(value, StrEnum) else value


@dataclass(frozen=True, slots=True)
class _Field:
    section: str
    name: str
    kind: str  # bool | int | float | enum | text
    label: str
    help: str
    low: float | None = None
    high: float | None = None
    options: tuple[tuple[str, str], ...] = ()

    @property
    def path(self) -> str:
        return f"{self.section}.{self.name}"

    @property
    def env(self) -> str:
        return f"{ENV_PREFIX}{self.section.upper()}_{self.name.upper()}"

    @property
    def default(self) -> Any:
        """Le défaut vient du domaine : une seule vérité, jamais recopiée ici."""
        return _plain(getattr(getattr(MemorySettings(), self.section), self.name))

    def schema(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.name, "path": self.path, "label": self.label, "type": self.kind,
            "default": self.default, "help": self.help, "env": self.env,
        }
        if self.kind in ("int", "float"):
            out["min"], out["max"] = self.low, self.high
        if self.kind == "text":
            out["max_length"] = MAX_URL_CHARS
        if self.kind == "id":
            out["max_length"] = MAX_SERVICE_ID_CHARS
        if self.kind == "enum":
            out["options"] = [{"id": key, "label": label} for key, label in self.options]
        return out


_FIELDS: tuple[_Field, ...] = (
    _Field("recall", "enabled", "bool", "Rappel actif", "Injecte les souvenirs pertinents dans le tour."),
    _Field("recall", "max_items", "int", "Souvenirs par tour", "Nombre maximal de souvenirs rappelés.",
           low=1, high=MAX_SETTINGS_RECALL_ITEMS),
    _Field("recall", "timeout_ms", "int", "Délai de rappel (ms)", "Au-delà, le tour continue sans rappel.",
           low=MIN_RECALL_TIMEOUT_MS, high=MAX_RECALL_TIMEOUT_MS),
    _Field("semantic", "enabled", "bool", "Recherche sémantique",
           "Ajoute une recherche par sens ; exige un fournisseur d'embeddings."),
    _Field("semantic", "provider", "enum", "Fournisseur d'embeddings",
           "Fournisseur des embeddings ; la clé se règle dans API Keys.",
           options=tuple((str(item), item.name.capitalize()) for item in EmbeddingProviderId)),
    _Field("semantic", "allow_private", "bool", "Autoriser les scopes privés",
           "Envoie aussi la mémoire privée au fournisseur distant."),
    _Field("consolidation", "mode", "enum", "Mode de consolidation",
           "Manuel : l'utilisateur tranche. Auto : exige la recherche sémantique.",
           options=tuple((str(item), item.name.capitalize()) for item in ConsolidationMode)),
    _Field("consolidation", "auto_min_confidence", "float", "Confiance minimale (auto)",
           "Sous ce seuil, un candidat reste en attente.", low=0.0, high=1.0),
    _Field("consolidation", "max_candidates_per_run", "int", "Candidats par passe",
           "Borne le travail d'une consolidation.", low=1, high=MAX_CANDIDATES_PER_RUN),
    _Field("tencent", "enabled", "bool", "Sidecar Tencent", "Source optionnelle ; exige une URL."),
    _Field("tencent", "url", "text", "URL du sidecar",
           "http(s) sans identifiants ; le jeton se règle dans API Keys."),
    _Field("tencent", "service_id", "id", "Identifiant d'instance",
           "Identifiant court de l'instance du sidecar (pas un secret) ; vide : aucun en-tête."),
    _Field("tencent", "allow_private", "bool", "Autoriser les scopes privés (Tencent)",
           "Envoie aussi la mémoire privée au sidecar."),
    _Field("knowledge", "wiki_enabled", "bool", "Wiki", "Actifs de connaissance Wiki."),
    _Field("knowledge", "codegraph_enabled", "bool", "Graphe de code", "Actifs de connaissance du graphe de code."),
    _Field("knowledge", "skills_enabled", "bool", "Skills", "Skills et loadouts."),
)
_BY_PATH = {item.path: item for item in _FIELDS}

#: Règles de compatibilité, dans l'ordre où elles sont testées et dégradées :
#: (code stable, champ coupé en lecture, condition, exigence, message).
_COMPATIBILITY = (
    ("memory_settings_semantic_needs_provider", "semantic.enabled", "semantic.enabled",
     "semantic.provider != none", "La recherche sémantique exige un fournisseur d'embeddings."),
    ("memory_settings_auto_needs_semantic", "consolidation.mode", "consolidation.mode = auto",
     "semantic.enabled", "La consolidation automatique exige la recherche sémantique."),
    ("memory_settings_tencent_needs_url", "tencent.enabled", "tencent.enabled",
     "tencent.url non vide", "Le sidecar Tencent exige une URL."),
)


# ------------------------------------------------------------ valeurs, strict


def _check_value(spec: _Field, value: object) -> Any:
    """La valeur normalisée d'un champ, ou `MemorySettingsError`. Jamais de valeur dans le message."""
    path = spec.path
    if spec.kind == "bool":
        if type(value) is not bool:
            raise MemorySettingsError("memory_settings_bad_type", f"{path} doit être un booléen.", path)
        return value
    if spec.kind == "int":
        if type(value) is not int:
            raise MemorySettingsError("memory_settings_bad_type", f"{path} doit être un entier.", path)
        return _in_range(spec, value)
    if spec.kind == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise MemorySettingsError("memory_settings_bad_type", f"{path} doit être un nombre.", path)
        if isinstance(value, float) and not math.isfinite(value):
            raise MemorySettingsError("memory_settings_out_of_range", f"{path} doit être fini.", path)
        # Borne vérifiée avant `float()` : un entier géant lèverait OverflowError.
        return float(_in_range(spec, value))
    if not isinstance(value, str):
        raise MemorySettingsError("memory_settings_bad_type", f"{path} doit être du texte.", path)
    if spec.kind == "enum":
        if value not in {key for key, _label in spec.options}:
            allowed = ", ".join(key for key, _label in spec.options)
            raise MemorySettingsError("memory_settings_bad_enum", f"{path} : valeurs permises {allowed}.", path)
        return value
    if spec.kind == "id":
        text = value.strip()
        if text and not SERVICE_ID.fullmatch(text):
            raise MemorySettingsError(
                "memory_settings_bad_identifier",
                f"{spec.path} : 1 à {MAX_SERVICE_ID_CHARS} caractères parmi lettres, chiffres, _ . : -.", spec.path)
        return text
    return _check_url(spec, value.strip())


def _in_range(spec: _Field, value: float) -> float:
    if not spec.low <= value <= spec.high:
        raise MemorySettingsError(
            "memory_settings_out_of_range", f"{spec.path} doit être entre {spec.low} et {spec.high}.", spec.path
        )
    return value


def _check_url(spec: _Field, value: str) -> str:
    if len(value) > MAX_URL_CHARS:
        raise MemorySettingsError(
            "memory_settings_out_of_range", f"{spec.path} dépasse {MAX_URL_CHARS} caractères.", spec.path
        )
    if not value:
        return value
    if not value.isprintable() or " " in value:
        raise MemorySettingsError(
            "memory_settings_bad_url", f"{spec.path} ne peut contenir ni espace ni caractère de contrôle.", spec.path
        )
    if "?" in value or "#" in value:
        raise MemorySettingsError(
            "memory_settings_secret_refused",
            f"{spec.path} ne porte ni paramètres ni fragment ; le jeton se règle dans API Keys.", spec.path,
        )
    try:
        parsed = urlparse(value)
        parsed.port  # noqa: B018 - lève ValueError sur un port illisible
    except ValueError:
        raise MemorySettingsError("memory_settings_bad_url", f"{spec.path} n'est pas une URL valide.", spec.path) from None
    if parsed.username is not None or parsed.password is not None:
        raise MemorySettingsError(
            "memory_settings_secret_refused",
            f"{spec.path} ne porte aucun identifiant ; le jeton se règle dans API Keys.", spec.path,
        )
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise MemorySettingsError("memory_settings_bad_url", f"{spec.path} doit être une URL http(s).", spec.path)
    return value


def _combination_error(values: Mapping[str, Any]) -> MemorySettingsError | None:
    broken = (
        values["semantic.enabled"] and values["semantic.provider"] == EmbeddingProviderId.NONE,
        values["consolidation.mode"] == ConsolidationMode.AUTO and not values["semantic.enabled"],
        values["tencent.enabled"] and not values["tencent.url"].strip(),
    )
    for hit, (code, field, _when, _need, message) in zip(broken, _COMPATIBILITY):
        if hit:
            return MemorySettingsError(code, message, field)
    return None


def _build(values: Mapping[str, Any]) -> MemorySettings:
    typed = dict(values)
    typed["semantic.provider"] = EmbeddingProviderId(typed["semantic.provider"])
    typed["consolidation.mode"] = ConsolidationMode(typed["consolidation.mode"])
    return MemorySettings(
        **{name: kind(**{f.name: typed[f"{name}.{f.name}"] for f in dc_fields(kind)}) for name, kind in _SECTIONS}
    )


def _flatten(settings: MemorySettings) -> dict[str, Any]:
    return {spec.path: _plain(getattr(getattr(settings, spec.section), spec.name)) for spec in _FIELDS}


# --------------------------------------------------------------------- lecture


def _stored_block(raw: object) -> Mapping[str, Any]:
    return raw if isinstance(raw, Mapping) else {}


def _parse_env(spec: _Field, text: str) -> Any:
    text = text.strip()
    value: Any = text
    if spec.kind == "bool":
        value = True if text.lower() in _TRUE else False if text.lower() in _FALSE else text
    elif spec.kind == "int" and re.fullmatch(rf"[+-]?[0-9]{{1,{MAX_ENV_DIGITS}}}", text, re.ASCII):
        value = int(text)  # ASCII et borné : ni chiffres larges, ni limite de conversion
    elif spec.kind == "float" and text.isascii() and len(text) <= 64:
        try:
            value = float(text)
        except ValueError:
            pass
    return _check_value(spec, value)


def _resolve(raw: object, environ: Mapping[str, str]) -> tuple[dict[str, Any], dict[str, str]]:
    block = _stored_block(raw)
    values: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for spec in _FIELDS:
        values[spec.path], sources[spec.path] = spec.default, SOURCE_DEFAULT
        section = block.get(spec.section)
        if isinstance(section, Mapping) and spec.name in section:
            try:
                values[spec.path], sources[spec.path] = _check_value(spec, section[spec.name]), SOURCE_FILE
            except MemorySettingsError:
                pass  # champ abîmé : le défaut vaut mieux qu'un écran qui ne s'ouvre pas
        text = environ.get(spec.env, "")
        if text.strip():
            try:
                values[spec.path], sources[spec.path] = _parse_env(spec, text), SOURCE_ENV
            except MemorySettingsError:
                pass  # variable illisible : ignorée, la source précédente reste
    return values, sources


def _degrade(values: dict[str, Any], sources: dict[str, str]) -> dict[str, str]:
    """Rend cohérent un état incohérent en coupant l'option la plus ambitieuse.

    Retourne `{chemin: code}` des champs coupés. L'ordre de `_COMPATIBILITY`
    fait passer la sémantique avant la consolidation automatique qui en dépend.
    """
    cut: dict[str, str] = {}
    for _ in _COMPATIBILITY:
        error = _combination_error(values)
        if error is None:
            break
        values[error.field] = _BY_PATH[error.field].default
        sources[error.field] = SOURCE_DEFAULT
        cut[error.field] = error.code
    return cut


def _effective(raw: object, environ: Mapping[str, str]) -> tuple[dict[str, Any], dict[str, str], dict[str, str]]:
    values, sources = _resolve(raw, environ)
    return values, sources, _degrade(values, sources)


def read_memory_settings(raw: object, environ: Mapping[str, str] | None = None) -> MemorySettings:
    """Les réglages effectifs (env > fichier > défaut), sans jamais lever.

    `raw` est le bloc `memory` du fichier de réglages ; n'importe quoi est toléré.
    """
    return _build(_effective(raw, os.environ if environ is None else environ)[0])


def read_memory_settings_file(raw: object, environ: Mapping[str, str] | None = None) -> MemorySettings:
    """Les réglages effectifs depuis le **fichier entier** (`control-center-settings.json` lu en dict), sans jamais lever.

    Ce que Core relit à chaque tour (`jarvis/core/memory_context.py`, `CachedMemorySettings`) : le bloc
    `memory` est cherché sous `SETTING_KEY`, tout le reste est ignoré.
    """
    return read_memory_settings(raw.get(SETTING_KEY) if isinstance(raw, Mapping) else None, environ)


def stored_memory_settings(raw: object) -> MemorySettings:
    """Ce que le fichier dit seul, environnement ignoré : la base d'une écriture."""
    return _build(_effective(raw, {})[0])


def effective_memory_settings(raw: object, environ: Mapping[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """Chaque champ avec sa valeur et sa source `default|file|env`.

    `downgraded` porte le code de compatibilité quand une combinaison
    incohérente a forcé la valeur.
    """
    values, sources, cut = _effective(raw, os.environ if environ is None else environ)
    out: dict[str, dict[str, Any]] = {}
    for spec in _FIELDS:
        entry: dict[str, Any] = {"value": values[spec.path], "source": sources[spec.path]}
        if spec.path in cut:
            entry["downgraded"] = cut[spec.path]
        out[spec.path] = entry
    return out


# -------------------------------------------------------------------- loadouts


def _rule_error(code: str, message: str, path: str) -> MemorySettingsError:
    return MemorySettingsError(code, message, path)


def _rule_dict(rule: LoadoutRule) -> dict[str, Any]:
    return {"memory_scopes": list(rule.memory_scopes), **{name: getattr(rule, name) for name in _RULE_BOOLS}}


def _check_rule(key: str, patch: Mapping[str, Any], base: Mapping[str, Any] | None) -> dict[str, Any]:
    """Une règle complète et normalisée : `base` (stockée) puis le correctif, ou `MemorySettingsError`."""
    where = f"{LOADOUTS_KEY}.{key}"
    unknown = sorted(str(name) for name in patch if name not in _RULE_FIELDS)
    if unknown:
        raise _rule_error("memory_settings_bad_loadout", f"{where} : champ inconnu « {unknown[0][:40]} ».", where)
    merged = {**(_rule_dict(LoadoutRule()) if base is None else dict(base)), **patch}
    scopes = merged["memory_scopes"]
    if isinstance(scopes, (str, bytes)) or not isinstance(scopes, (list, tuple)):
        raise _rule_error("memory_settings_bad_type", f"{where}.memory_scopes doit être une liste.", where)
    if len(scopes) > MAX_LOADOUT_ENTRIES:
        raise _rule_error(
            "memory_settings_out_of_range",
            f"{where}.memory_scopes : au plus {MAX_LOADOUT_ENTRIES} entrées.", where,
        )
    for scope in scopes:
        try:
            check_scope("scope", scope)
        except (TypeError, ValueError):
            raise _rule_error(
                "memory_settings_bad_scope",
                f"{where}.memory_scopes : private, shared, board:<id> ou project:<id>.", where,
            ) from None
    for name in _RULE_BOOLS:
        if type(merged[name]) is not bool:
            raise _rule_error("memory_settings_bad_type", f"{where}.{name} doit être un booléen.", where)
    try:
        return _rule_dict(LoadoutRule(memory_scopes=tuple(scopes), **{name: merged[name] for name in _RULE_BOOLS}))
    except ValueError as exc:  # doublon ou scope privé sans `allow_private`
        code = "memory_settings_private_needs_allow" if "private" in str(exc) else "memory_settings_bad_scope"
        raise _rule_error(code, f"{where} : {exc}", where) from None


def _stored_loadouts(stored: object) -> Mapping[str, Any]:
    raw = _stored_block(stored).get(LOADOUTS_KEY)
    return raw if isinstance(raw, Mapping) else {}


def _read_rule(raw: object) -> LoadoutRule | None:
    """Une règle stockée, ou `None` si elle est abîmée (jamais d'exception à la lecture)."""
    if not isinstance(raw, Mapping):
        return None
    try:
        rule = _check_rule("", {name: raw[name] for name in _RULE_FIELDS if name in raw}, None)
        return LoadoutRule(memory_scopes=tuple(rule["memory_scopes"]), **{name: rule[name] for name in _RULE_BOOLS})
    except (MemorySettingsError, TypeError, ValueError):
        return None


def _merged_loadouts(stored: object, patch: object) -> dict[str, Any]:
    """Le bloc `loadouts` à écrire : le stocké tel quel, puis chaque clé du correctif.

    Une valeur `null` retire la règle (le préréglage reprend la main). Les entrées
    non touchées, y compris abîmées ou inconnues, sont conservées telles quelles.
    """
    if not isinstance(patch, Mapping):
        raise MemorySettingsError("memory_settings_bad_section", "« loadouts » doit être un objet.", LOADOUTS_KEY)
    block = dict(_stored_loadouts(stored))
    for key, change in patch.items():
        try:
            check_loadout_key("loadouts key", key)
        except (TypeError, ValueError):
            raise _rule_error(
                "memory_settings_bad_loadout_key",
                f"{LOADOUTS_KEY} : clé de loadout « {str(key)[:40]} » inconnue.", LOADOUTS_KEY,
            ) from None
        if change is None:
            block.pop(key, None)
            continue
        if not isinstance(change, Mapping):
            raise _rule_error("memory_settings_bad_type", f"{LOADOUTS_KEY}.{key} doit être un objet.", f"{LOADOUTS_KEY}.{key}")
        base = _read_rule(block.get(key))
        block[key] = _check_rule(key, change, None if base is None else _rule_dict(base))
    if len(block) > MAX_LOADOUT_RULES:
        raise _rule_error(
            "memory_settings_out_of_range", f"{LOADOUTS_KEY} : au plus {MAX_LOADOUT_RULES} règles.", LOADOUTS_KEY
        )
    return block


def read_loadout_policy(raw: object) -> LoadoutPolicy:
    """Les règles de loadout du bloc `memory` (fichier seul), sans jamais lever.

    Une clé inconnue ou une règle abîmée est ignorée : le préréglage, qui ne donne
    jamais le scope privé à un sous-agent, s'applique à sa place.
    """
    rules: dict[str, LoadoutRule] = {}
    for key, value in _stored_loadouts(raw).items():
        try:
            check_loadout_key("loadouts key", key)
        except (TypeError, ValueError):
            continue
        rule = _read_rule(value)
        if rule is not None:
            rules[key] = rule
    return LoadoutPolicy(rules)


# --------------------------------------------------------------------- écriture


def _looks_secret(key: str) -> bool:
    if key in _READ_ONLY_KEYS:
        return False
    collapsed = re.sub(r"[^a-z0-9]", "", key.lower())
    if collapsed.endswith("token") or any(stem in collapsed for stem in _SECRET_SUBSTRINGS):
        return True
    words = {word.lower() for word in _WORD.findall(key)}
    return bool(words & _SECRET_WORDS) or ("key" in words and bool(words & {"api", "private", "access", "secret", "auth", "ssh"}))


def _scan_payload(payload: Mapping[str, Any]) -> None:
    """Refuse trop profond ou portant une clé secrète, listes comprises. Itératif : pas de RecursionError."""
    stack: list[tuple[object, str, int]] = [(payload, "", 0)]
    while stack:
        node, path, depth = stack.pop()
        if isinstance(node, Mapping):
            children = [(str(key), value) for key, value in node.items()]
        elif isinstance(node, (list, tuple)):
            children = [(f"[{index}]", value) for index, value in enumerate(node)]
        else:
            continue
        if depth >= MAX_PAYLOAD_DEPTH:
            raise MemorySettingsError(
                "memory_settings_bad_payload", f"Les réglages mémoire dépassent {MAX_PAYLOAD_DEPTH} niveaux.", path
            )
        for name, value in children:
            where = f"{path}{name}"
            if isinstance(node, Mapping) and _looks_secret(name):
                raise MemorySettingsError(
                    "memory_settings_secret_refused",
                    f"{where} : un secret se règle dans API Keys, jamais ici.", where,
                )
            stack.append((value, f"{where}.", depth + 1))


def _strip_read_only(node: Any) -> Any:
    """Copie sans `has_secret` à aucune profondeur (la profondeur est déjà bornée par `_scan_payload`)."""
    if isinstance(node, Mapping):
        return {key: _strip_read_only(value) for key, value in node.items() if key not in _READ_ONLY_KEYS}
    if isinstance(node, (list, tuple)):
        return [_strip_read_only(value) for value in node]
    return node


def _merged_block(
    stored: object, payload: Mapping[str, Any], settings: MemorySettings, loadouts: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Le bloc à écrire : le stocké (clés inconnues comprises), la requête, puis les champs connus normalisés."""
    block = dict(_stored_block(stored))
    clean = _strip_read_only(payload)
    block.update({key: value for key, value in clean.items() if key not in _SECTION_NAMES and key != LOADOUTS_KEY})
    flat = _flatten(settings)
    for name in _SECTION_NAMES:
        section: dict[str, Any] = {}
        for source in (block.get(name), clean.get(name)):
            if isinstance(source, Mapping):
                section.update(source)
        section.update({spec.name: flat[spec.path] for spec in _FIELDS if spec.section == name})
        block[name] = section
    if loadouts is not None:
        block[LOADOUTS_KEY] = loadouts
    return block


def _validate(stored: object, payload: object) -> tuple[MemorySettings, dict[str, Any]]:
    if not isinstance(payload, Mapping):
        raise MemorySettingsError("memory_settings_bad_payload", "Les réglages mémoire doivent être un objet.")
    _scan_payload(payload)
    values, sources, _cut = _effective(stored, {})
    for name in _SECTION_NAMES.intersection(payload):
        section = payload[name]
        if not isinstance(section, Mapping):
            raise MemorySettingsError("memory_settings_bad_section", f"« {name} » doit être un objet.", name)
        for spec in (item for item in _FIELDS if item.section == name and item.name in section):
            values[spec.path] = _check_value(spec, section[spec.name])
    error = _combination_error(values)
    if error is not None:
        raise error
    loadouts = _merged_loadouts(stored, payload[LOADOUTS_KEY]) if LOADOUTS_KEY in payload else None
    settings = _build(values)
    return settings, _merged_block(stored, payload, settings, loadouts)


def validate_memory_settings_write(raw: object, stored: object = None) -> MemorySettings:
    """Valide une requête d'écriture en entier ; lève `MemorySettingsError` sinon.

    `raw` est un correctif : seuls les champs présents changent, le reste vient
    du bloc enregistré `stored`. Rien n'est écrit ici.
    """
    return _validate(stored, raw)[0]


def apply_memory_settings(settings: dict[str, Any], payload: object) -> MemorySettings:
    """Valider puis poser `settings["memory"]` ; en cas de refus, `settings` reste intact."""
    result, block = _validate(settings.get(SETTING_KEY), payload)
    settings[SETTING_KEY] = block
    return result


# ------------------------------------------------------------ description, état


def describe_memory_settings() -> dict[str, Any]:
    """Le schéma que l'interface rend : types, bornes, énumérations, défauts, règles."""
    sections = []
    for name, _kind in _SECTIONS:
        item: dict[str, Any] = {
            "id": name, "label": _SECTION_LABELS[name],
            "fields": [spec.schema() for spec in _FIELDS if spec.section == name],
        }
        if name in _SECRET_PROVIDERS:
            item["secret"] = {"credential_provider": _SECRET_PROVIDERS[name]}
        sections.append(item)
    return {
        "key": SETTING_KEY,
        "sections": sections,
        "compatibility": [
            {"code": code, "when": when, "requires": need, "message": message}
            for code, _field_path, when, need, message in _COMPATIBILITY
        ],
        "precedence": [SOURCE_ENV, SOURCE_FILE, SOURCE_DEFAULT],
        "loadouts": {
            "key": LOADOUTS_KEY,
            "profiles": list(LOADOUT_PROFILES),
            "roles": list(LOADOUT_ROLES),
            "max_rules": MAX_LOADOUT_RULES,
            "fields": [
                {"id": "memory_scopes", "type": "list", "item": "scope", "max_items": MAX_LOADOUT_ENTRIES,
                 "default": []},
                *({"id": name, "type": "bool", "default": getattr(LoadoutRule(), name)} for name in _RULE_BOOLS),
            ],
        },
    }


def secret_state(settings: Mapping[str, Any]) -> dict[str, dict[str, bool]]:
    """`has_secret` par jambe. Jamais la valeur, ni un indice de la valeur."""
    return {
        name: {"has_secret": bool(credentials.secret_for(dict(settings), provider))}
        for name, provider in _SECRET_PROVIDERS.items()
    }


def memory_state(settings: Mapping[str, Any], environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Valeurs du fichier, effectif avec sources, secrets présents : tout ce qu'un écran lit."""
    block = settings.get(SETTING_KEY)
    effective = effective_memory_settings(block, environ)
    return {
        "values": _flatten(stored_memory_settings(block)),
        "effective": effective,
        "downgraded": {path: item["downgraded"] for path, item in effective.items() if "downgraded" in item},
        "secrets": secret_state(settings),
        "loadouts": {key: _rule_dict(rule) for key, rule in read_loadout_policy(block).rules.items()},
    }

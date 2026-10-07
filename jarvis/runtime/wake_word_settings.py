"""Réglages du mot d'éveil : la clé, le schéma, la lecture tolérante, l'écriture stricte.

Le Control Center possède la **persistance** de ce que l'utilisateur a choisi.
Ce module est une frontière : il lit et écrit un bloc, il ne décide d'aucun
comportement et **n'ouvre aucun micro**. Voice le consomme au démarrage, en
PRESENTATION (Slice 04) et en SIMPLE (Slice 05) ; l'écran des Réglages (Slice 07)
le lit et l'écrit par la route.

Forme reprise de `interaction_mode_settings` : ``SETTING_KEY``, une lecture
**tolérante** (``load``, ``inspect``), une écriture **stricte** (``apply``, qui
lève avec un ``code`` stable repris dans l'en-tête ``X-Jarvis-Error-Code``) et
un ``describe``.

Le bloc ``wake_word``, à la racine de ``runtime/control-center-settings.json`` ::

    {"schema_version": 1, "enabled": false, "provider": "porcupine",
     "keyword": "jarvis", "sensitivity": 0.5, "cooldown_ms": 2000}

- ``enabled`` : **faux par défaut** (D1). Sans réglage explicite, le comportement
  d'avant cette fonctionnalité est strictement inchangé : la touche manuelle, et
  le mot Porcupine si une clé Porcupine est configurée. Aucun micro de plus.
- ``provider`` : ``porcupine`` (défaut = le comportement actuel) ou
  ``openwakeword``. Valeurs fermées.
- ``keyword`` : un mot par fournisseur, **jamais le même jeton** :
  ``porcupine`` -> ``jarvis`` (mot intégré, en minuscules, mots séparés par des
  espaces) ; ``openwakeword`` -> ``hey_jarvis`` (clé du catalogue de modèles,
  `OPENWAKEWORD_KEYWORDS`). Absent, il vaut le défaut du fournisseur ; si le
  fournisseur change sans mot, le mot revient au défaut du nouveau fournisseur.
  Validé par jeton, pas par chemin : aucun nom de fichier n'entre ici.
- ``sensitivity`` : nombre de 0 à 1 inclus (défaut 0,5). Plus haut = plus
  sensible. Le moteur en tire son seuil.
- ``cooldown_ms`` : entier de `COOLDOWN_MS_MIN` (80, une trame openWakeWord) à
  `COOLDOWN_MS_MAX` (30 000) ms inclus, défaut 2000.

**Lecture tolérante.** Un bloc absent, mal formé, d'une version inconnue ou
dont un champ est invalide donne les défauts sûrs (donc ``enabled`` faux) et un
diagnostic dit (`inspect` / `describe`, ``problems``) : un fichier abîmé ne
doit ni empêcher Jarvis de démarrer ni ouvrir un micro. Le bloc illisible n'est
pas réécrit tant que personne n'enregistre.

**Redémarrage.** Voice ne relit le fichier qu'au démarrage : tout changement
exige un redémarrage de Voice, et `describe` le dit.

Aucune migration SQLite : ce sont des réglages JSON (D6). Aucune clé existante
n'est renommée (``manual_wake_key``, ``shortcuts.wake_toggle`` intactes).
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Mapping

#: Bloc de réglages, à la racine de ``runtime/control-center-settings.json``.
SETTING_KEY = "wake_word"

#: Version du schéma que **ce serveur écrit**. Élargir le bloc, c'est monter ce
#: numéro dans le même changement.
SCHEMA_VERSION = 1
SCHEMA_KEY = "schema_version"

#: Les champs du bloc, dans l'ordre où ils sont écrits.
FIELDS = ("enabled", "provider", "keyword", "sensitivity", "cooldown_ms")

PROVIDER_PORCUPINE = "porcupine"
PROVIDER_OPENWAKEWORD = "openwakeword"
#: Valeurs fermées. Le défaut est le comportement actuel (Porcupine).
PROVIDERS = (PROVIDER_PORCUPINE, PROVIDER_OPENWAKEWORD)
DEFAULT_PROVIDER = PROVIDER_PORCUPINE

#: Mot par défaut de chaque fournisseur (ce sont deux jetons différents).
DEFAULT_KEYWORDS = {PROVIDER_PORCUPINE: "jarvis", PROVIDER_OPENWAKEWORD: "hey_jarvis"}

#: Détecteurs openWakeWord connus. Doublon assumé de
#: `wakeword_model_catalog.MODELS` (hors modèles de pré-traitement) : le
#: runtime ne dépend pas d'un adaptateur, un test fige l'égalité.
OPENWAKEWORD_KEYWORDS = ("hey_jarvis",)

#: Forme d'un mot intégré Porcupine : minuscules, mots séparés par des espaces
#: (« jarvis », « hey google »). Contrôle de forme, non de liste : un mot
#: inconnu de la bibliothèque est refusé à la construction du moteur (Slice 04).
_PORCUPINE_TOKEN = re.compile(r"^[a-z]+( [a-z]+){0,3}$")
_PORCUPINE_MAX_LENGTH = 32

DEFAULT_ENABLED = False
DEFAULT_SENSITIVITY = 0.5
DEFAULT_COOLDOWN_MS = 2000
SENSITIVITY_MIN = 0
SENSITIVITY_MAX = 1
#: Une trame openWakeWord dure 80 ms : en dessous, un cooldown ne couvre rien.
COOLDOWN_MS_MIN = 80
#: Au-delà de 30 s, le mot d'éveil semblerait cassé à l'utilisateur.
COOLDOWN_MS_MAX = 30000

#: Quand le réglage s'applique. Voice consomme le bloc en PRESENTATION (Slice 04)
#: et en SIMPLE (Slice 05) : la seule chose vraie et utile à dire est « au
#: prochain démarrage de Voice ».
APPLIES_AT_RESTART_NOTICE = "Réglage enregistré ; il ne s'applique qu'au prochain démarrage de Voice."

RESTART_MESSAGE = (
    "Un changement exige un redémarrage de Voice : Voice ne relit les réglages qu'au démarrage. "
    + APPLIES_AT_RESTART_NOTICE
)


class WakeWordSettingsError(ValueError):
    """Refus d'écriture, avec un code stable. Même convention que ses voisins."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class WakeWordSettings:
    enabled: bool = DEFAULT_ENABLED
    provider: str = DEFAULT_PROVIDER
    keyword: str = DEFAULT_KEYWORDS[DEFAULT_PROVIDER]
    sensitivity: float = DEFAULT_SENSITIVITY
    cooldown_ms: int = DEFAULT_COOLDOWN_MS


def defaults() -> WakeWordSettings:
    """Les défauts sûrs : désactivé, fournisseur actuel."""

    return WakeWordSettings()


def default_keyword(provider: str) -> str:
    return DEFAULT_KEYWORDS[provider]


# ------------------------------------------------------------ validation


def _is_number(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True  # `math.isfinite(int)` convertit en float : OverflowError au-delà de ~1e308
    return isinstance(value, float) and math.isfinite(value)


def _shown(value: object) -> str:
    """Valeur citée dans un message : bornée, un entier démesuré ne gonfle pas la réponse."""

    text = repr(value)
    return text if len(text) <= 40 else text[:37] + "..."


def _check_enabled(value: object) -> tuple[bool | None, tuple[str, str] | None]:
    if isinstance(value, bool):
        return value, None
    return None, ("wake_word_enabled_invalid", f"« enabled » attend vrai ou faux : {value!r}.")


def _check_provider(value: object) -> tuple[str | None, tuple[str, str] | None]:
    if not isinstance(value, str):
        return None, ("wake_word_provider_invalid", f"« provider » attend un texte : {value!r}.")
    if value not in PROVIDERS:
        return None, (
            "wake_word_provider_unknown",
            f"Fournisseur de mot d'éveil inconnu : {value!r}. Valeurs acceptées : "
            + ", ".join(f"« {p} »" for p in PROVIDERS) + ".",
        )
    return value, None


def _check_keyword(value: object, provider: str) -> tuple[str | None, tuple[str, str] | None]:
    if not isinstance(value, str):
        return None, ("wake_word_keyword_invalid", f"« keyword » attend un texte : {value!r}.")
    if provider == PROVIDER_OPENWAKEWORD:
        known = value in OPENWAKEWORD_KEYWORDS
    else:
        known = len(value) <= _PORCUPINE_MAX_LENGTH and bool(_PORCUPINE_TOKEN.fullmatch(value))
    if not known:
        return None, (
            "wake_word_keyword_unknown",
            f"Mot d'éveil inconnu pour {provider} : {value[:40]!r}.",
        )
    return value, None


def _check_sensitivity(value: object) -> tuple[float | None, tuple[str, str] | None]:
    if not _is_number(value):
        return None, ("wake_word_sensitivity_invalid", f"« sensitivity » attend un nombre : {_shown(value)}.")
    if not SENSITIVITY_MIN <= value <= SENSITIVITY_MAX:
        return None, (
            "wake_word_sensitivity_out_of_range",
            f"« sensitivity » doit être entre {SENSITIVITY_MIN} et {SENSITIVITY_MAX} : {_shown(value)}.",
        )
    return float(value), None


def _check_cooldown(value: object) -> tuple[int | None, tuple[str, str] | None]:
    if not _is_number(value) or int(value) != value:
        return None, ("wake_word_cooldown_invalid", f"« cooldown_ms » attend un entier : {_shown(value)}.")
    if not COOLDOWN_MS_MIN <= value <= COOLDOWN_MS_MAX:
        return None, (
            "wake_word_cooldown_out_of_range",
            f"« cooldown_ms » doit être entre {COOLDOWN_MS_MIN} et {COOLDOWN_MS_MAX} ms : {_shown(value)}.",
        )
    return int(value), None


def _validate(
    raw: Mapping[str, Any], base: WakeWordSettings
) -> tuple[WakeWordSettings, list[tuple[str, str, str]]]:
    """Valide les champs présents de ``raw`` au-dessus de ``base``.

    Rend les valeurs retenues et la liste ``(champ, code, message)`` des
    refus, dans l'ordre des champs. Un champ en erreur garde sa valeur de base.
    """

    values: dict[str, Any] = {}
    errors: list[tuple[str, str, str]] = []

    def take(name: str, checker) -> bool:
        if name not in raw:
            return False
        value, error = checker(raw[name])
        if error:
            errors.append((name, *error))
            return False
        values[name] = value
        return True

    take("enabled", _check_enabled)
    provider_ok = take("provider", _check_provider)
    provider = values.get("provider", base.provider)
    provider_bad = "provider" in raw and not provider_ok
    if "keyword" in raw:
        if not provider_bad:  # le mot ne se juge que contre un fournisseur connu
            take("keyword", lambda value: _check_keyword(value, provider))
    elif provider != base.provider:
        values["keyword"] = default_keyword(provider)  # le mot suit le fournisseur
    take("sensitivity", _check_sensitivity)
    take("cooldown_ms", _check_cooldown)
    return WakeWordSettings(**{**base.__dict__, **values}), errors


# -------------------------------------------------------- lecture tolérante


def _stored_version(stored: Mapping[str, Any]) -> int | None:
    """Version du bloc enregistré. Absente = « écrit par nous »; illisible = None."""

    if SCHEMA_KEY not in stored:
        return SCHEMA_VERSION
    raw = stored[SCHEMA_KEY]
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    return None


def _read(settings: Mapping[str, Any]) -> tuple[WakeWordSettings, dict[str, Any]]:
    """Lecture unique : la valeur qui s'applique et le diagnostic."""

    stored = settings.get(SETTING_KEY) if isinstance(settings, Mapping) else None
    seen: dict[str, Any] = {
        "present": stored is not None,
        "stored_schema_version": None,
        "unreadable": False,
        "problems": [],
        "ignored_fields": [],
    }
    if stored is None:
        return defaults(), seen
    if not isinstance(stored, Mapping):
        seen["unreadable"] = True
        seen["problems"].append({
            "field": None, "code": "wake_word_block_malformed",
            "message": "Le bloc wake_word n'est pas un objet : défauts sûrs appliqués.",
        })
        return defaults(), seen
    version = _stored_version(stored)
    seen["stored_schema_version"] = version
    if version != SCHEMA_VERSION:
        seen["unreadable"] = True
        seen["problems"].append({
            "field": SCHEMA_KEY, "code": "wake_word_stored_version_unreadable",
            "message": f"Bloc wake_word en version {_shown(stored.get(SCHEMA_KEY))} ; ce serveur lit la version "
                       f"{SCHEMA_VERSION} : défauts sûrs appliqués, bloc conservé tel quel.",
        })
        return defaults(), seen
    seen["ignored_fields"] = sorted(str(k) for k in stored if k not in FIELDS and k != SCHEMA_KEY)
    # La clé de fournisseur précède le mot : le défaut du mot suit le fournisseur lu.
    probe = {k: v for k, v in stored.items() if k in FIELDS}
    provider = _check_provider(probe["provider"])[0] if "provider" in probe else None
    provider = provider or DEFAULT_PROVIDER
    base = WakeWordSettings(provider=provider, keyword=default_keyword(provider))
    value, errors = _validate(probe, base)
    if errors:
        seen["problems"] = [{"field": f, "code": c, "message": m} for f, c, m in errors]
        return defaults(), seen
    return value, seen


def inspect(settings: Mapping[str, Any]) -> dict[str, Any]:
    """Ce que le bloc dit de lui-même, **avant** toute tolérance.

    Sépare « le défaut parce qu'il n'y avait rien » de « le défaut parce que ce
    qu'il y avait était illisible » : ``problems`` liste chaque champ refusé
    avec son code, ``ignored_fields`` les clés inconnues (ignorées, non fatales).
    """

    return _read(settings)[1]


def load(settings: Mapping[str, Any]) -> WakeWordSettings:
    """Les réglages qui s'appliquent. Ne lève jamais ; au moindre doute, les défauts sûrs."""

    return _read(settings)[0]


# --------------------------------------------------------- écriture stricte


def apply(settings: dict[str, Any], payload: Any) -> WakeWordSettings:
    """Valider puis ranger le bloc dans ``settings`` (sans écrire le fichier).

    Les champs présents s'appliquent au-dessus du bloc courant ; les autres
    gardent leur valeur. Écriture **stricte** : le premier refus lève, avec un
    code stable, et ``settings`` n'est pas modifié.

    - charge utile qui n'est pas un objet : ``wake_word_bad_payload`` ;
    - clé inconnue : ``wake_word_unknown_field`` ;
    - version étrangère dans la charge utile : ``wake_word_schema_version_unsupported`` ;
    - bloc **déjà enregistré** d'une autre version de schéma (plus récent, ou
      version illisible) : ``wake_word_foreign_version`` ; on ne l'écrase pas
      par les défauts, il reste tel quel ;
    - ``enabled`` / ``provider`` / ``keyword`` / ``sensitivity`` / ``cooldown_ms``
      de mauvais type : ``wake_word_<champ>_invalid`` ;
    - fournisseur inconnu : ``wake_word_provider_unknown`` ;
    - mot inconnu pour ce fournisseur : ``wake_word_keyword_unknown`` ;
    - valeur hors bornes : ``wake_word_sensitivity_out_of_range``,
      ``wake_word_cooldown_out_of_range``.
    """

    if not isinstance(payload, Mapping):
        raise WakeWordSettingsError("wake_word_bad_payload", "Le mot d'éveil attend un objet JSON.")
    unknown = set(payload) - set(FIELDS) - {SCHEMA_KEY}
    if unknown:
        raise WakeWordSettingsError(
            "wake_word_unknown_field", f"Champ inconnu : {', '.join(sorted(map(str, unknown)))}."
        )
    version = payload.get(SCHEMA_KEY)
    if SCHEMA_KEY in payload and (isinstance(version, bool) or version != SCHEMA_VERSION):
        raise WakeWordSettingsError(
            "wake_word_schema_version_unsupported",
            f"Mot d'éveil en version {version!r} ; ce serveur n'écrit que la version {SCHEMA_VERSION}.",
        )
    stored = settings.get(SETTING_KEY) if isinstance(settings, Mapping) else None
    if isinstance(stored, Mapping) and _stored_version(stored) != SCHEMA_VERSION:
        raise WakeWordSettingsError(
            "wake_word_foreign_version",
            f"Le bloc wake_word enregistré est d'une autre version de schéma "
            f"({_shown(stored.get(SCHEMA_KEY))}) que celle de ce serveur ({SCHEMA_VERSION}) : "
            "il est gardé tel quel, rien n'est écrit.",
        )
    result, errors = _validate(payload, load(settings))
    if errors:
        _, code, message = errors[0]
        raise WakeWordSettingsError(code, message)
    settings[SETTING_KEY] = {
        SCHEMA_KEY: SCHEMA_VERSION,
        "enabled": result.enabled,
        "provider": result.provider,
        "keyword": result.keyword,
        "sensitivity": result.sensitivity,
        "cooldown_ms": result.cooldown_ms,
    }
    return result


# ---------------------------------------------------------------- describe


def _state(current: WakeWordSettings, seen: Mapping[str, Any]) -> str:
    if seen["unreadable"] or seen["problems"]:
        return ("Bloc wake_word illisible : défauts sûrs appliqués, mot d'éveil du bloc inactif "
                "(comportement actuel inchangé). Voir « problems ».")
    if not current.enabled:
        return "Mot d'éveil du bloc inactif : comportement actuel inchangé (touche manuelle, et Porcupine si sa clé est configurée)."
    return (
        f"Mot d'éveil du bloc actif : {current.provider}, mot « {current.keyword} », "
        f"sensibilité {current.sensitivity:g}, repos {current.cooldown_ms} ms. "
        + APPLIES_AT_RESTART_NOTICE
    )


def describe(settings: Mapping[str, Any]) -> dict[str, Any]:
    """Ce que rendent `GET`/`POST /api/wake-word` : l'état effectif et ce qu'il faut savoir.

    ``restart_required`` est toujours vrai : Voice relit le fichier au
    démarrage seulement, rien ne s'applique à chaud.
    """

    current, seen = _read(settings)
    return {
        "enabled": current.enabled,
        "provider": current.provider,
        "keyword": current.keyword,
        "sensitivity": current.sensitivity,
        "cooldown_ms": current.cooldown_ms,
        "state": _state(current, seen),
        "restart_required": True,
        "restart_message": RESTART_MESSAGE,
        "schema_version": SCHEMA_VERSION,
        "stored_schema_version": seen["stored_schema_version"],
        "present": seen["present"],
        "unreadable": seen["unreadable"],
        "problems": seen["problems"],
        "ignored_fields": seen["ignored_fields"],
        "bounds": {
            "sensitivity": {"min": SENSITIVITY_MIN, "max": SENSITIVITY_MAX},
            "cooldown_ms": {"min": COOLDOWN_MS_MIN, "max": COOLDOWN_MS_MAX},
        },
        "providers": {
            PROVIDER_PORCUPINE: {"default_keyword": DEFAULT_KEYWORDS[PROVIDER_PORCUPINE]},
            PROVIDER_OPENWAKEWORD: {
                "default_keyword": DEFAULT_KEYWORDS[PROVIDER_OPENWAKEWORD],
                "keywords": list(OPENWAKEWORD_KEYWORDS),
            },
        },
    }

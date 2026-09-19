"""Barehands en mode test : piloter le Control Center à mains nues.

Réimplémentation native, et volontairement réduite, de l'idée Barehands : la
webcam suit les mains dans la page du Control Center, chaque main détectée
affiche un jeton qui suit l'index, et un pincement pouce-index clique sous le
jeton. Tout le suivi tourne dans le navigateur (MediaPipe Hand Landmarker), sans
service cloud et sans le serveur Barehands (port 8794).

Ce module ne tient que ce que le serveur doit décider :

- les réglages persistants, éteints par défaut, rangés sous
  ``barehands_test_mode`` dans ``runtime/control-center-settings.json`` ;
- la liste blanche des fichiers MediaPipe servis à la page. Ils ne sont pas
  versionnés : ``scripts/bootstrap_third_party.py`` les a vendorisés sous
  ``third_party/barehands/vendor`` (Apache-2.0). Aucun code upstream Barehands
  (AGPL) n'est repris ici ni dans la page.

Forme du module de réglages, comme ``scene_settings`` : ``SETTING_KEY``, une
lecture **tolérante** (``load``), une écriture **stricte** (``apply``, qui lève
un ``BarehandsSettingsError`` au ``code`` stable repris dans l'en-tête
``X-Jarvis-Error-Code``) et un ``describe``.

Cette route reste délibérément hors de ``/api/settings`` : elle s'applique à
chaud et ne dépend pas de la validité du reste des réglages (constat F5 de la
Slice 00).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

#: Bloc de réglages. Absent, tout est éteint.
SETTING_KEY = "barehands_test_mode"

#: Version du schéma de réglages Bare Hands, annoncée par ``describe`` pour que
#: la page sache à quoi elle parle. Elle vaut celle de
#: ``control_center_barehands_contracts.js`` (``SETTINGS_SCHEMA_VERSION``), et le
#: contrat écrit est ``docs/barehands-contracts.md``.
#:
#: **Version 2 (Slice 07)** : la route n'acceptait que ``enabled``, elle accepte
#: maintenant les neuf réglages du contrat § 9. Élargir la charge utile, c'est
#: monter ce numéro **et** ``SETTINGS_SCHEMA_VERSION`` dans le même changement —
#: un producteur et un consommateur qui ne partagent pas ce nombre ne partagent
#: pas ce contrat.
SCHEMA_VERSION = 2

#: Version précédente, celle que ``load`` sait encore lire et convertir : un
#: bloc v1 ne portait que ``enabled``, les huit autres réglages prennent leur
#: défaut. C'est la couture de migration, pas un champ à ignorer.
MIGRATED_SCHEMA_VERSIONS = (1,)

#: Surcharge du dossier des assets vendorisés (ex. un worktree sans install).
VENDOR_ENV = "JARVIS_BAREHANDS_VENDOR_DIR"

#: Préfixe HTTP des assets, relatif à la page du Control Center.
ASSET_ROUTE_PREFIX = "/barehands/assets/"

#: Nom servi -> (chemin sous le dossier vendor, type MIME). Rien d'autre n'est
#: lisible : un nom absent de cette table répond 404, quel que soit le disque.
ASSETS: dict[str, tuple[str, str]] = {
    "vision_bundle.mjs": ("mediapipe/vision_bundle.mjs", "text/javascript"),
    "wasm/vision_wasm_internal.js": ("mediapipe/wasm/vision_wasm_internal.js", "text/javascript"),
    "wasm/vision_wasm_internal.wasm": ("mediapipe/wasm/vision_wasm_internal.wasm", "application/wasm"),
    "wasm/vision_wasm_nosimd_internal.js": ("mediapipe/wasm/vision_wasm_nosimd_internal.js", "text/javascript"),
    "wasm/vision_wasm_nosimd_internal.wasm": ("mediapipe/wasm/vision_wasm_nosimd_internal.wasm", "application/wasm"),
    "models/hand_landmarker.task": ("models/hand_landmarker.task", "application/octet-stream"),
}

#: Le minimum pour suivre une main dans Chrome (WASM SIMD).
REQUIRED_ASSETS: tuple[str, ...] = (
    "vision_bundle.mjs",
    "wasm/vision_wasm_internal.js",
    "wasm/vision_wasm_internal.wasm",
    "models/hand_landmarker.task",
)

INSTALL_HINT = "python scripts/bootstrap_third_party.py"


#: Outils (contrat § 8, décision 25) : « ce que la main veut dire », distinct
#: des réglages. Miroir serveur de ``TOOLS`` du contrat JS — la parité est
#: testée en exécutant le contrat sous node, pas supposée.
TOOLS: tuple[str, ...] = ("pointer", "pan", "select")

#: Les outils que le moteur V1 sait réellement servir. Ils coïncident avec
#: ``TOOLS`` depuis que la couche d'annotation est **hors V1** : ``highlighter``
#: et ``draw`` étaient déclarés, refusés partout et possédés par aucune Slice.
#: La table reste **séparée** parce que c'est elle qui rend « installé »
#: vérifiable : un outil déclaré demain sans moteur se refuse ici
#: (``barehands_tool_not_installed``) au lieu d'être accepté sans effet.
INSTALLED_TOOLS: tuple[str, ...] = ("pointer", "pan", "select")

#: Bornes des réglages numériques, miroir de ``SETTINGS_BOUNDS`` du contrat.
#: Le contrat **borne** (il normalise un schéma stocké) ; cette route
#: **refuse** (elle écrit ce que quelqu'un a demandé).
SETTINGS_BOUNDS: dict[str, tuple[float, float]] = {
    "sleep_timeout_ms": (5_000, 600_000),
    "assistance": (0.0, 1.0),
    "sensitivity": (0.25, 4.0),
}

#: Réglages booléens, avec leur défaut.
SETTINGS_FLAGS: dict[str, bool] = {
    "enabled": False,             # Bare Hands reste éteint par défaut
    "target_preview": True,       # décision 24 : l'aperçu de cible est réglable
    "tutorial_seen": False,
    "calibration_enabled": True,  # décision 27 : la calibration reste optionnelle
    "diagnostics": False,         # architecture §12 : lecture à la demande
}

#: Tous les réglages et leur défaut, dans l'ordre du contrat § 9.
SETTINGS_DEFAULTS: dict[str, Any] = {
    "enabled": SETTINGS_FLAGS["enabled"],
    "target_preview": SETTINGS_FLAGS["target_preview"],
    "sleep_timeout_ms": 30_000,
    "tool": "pointer",
    "assistance": 0.5,
    "sensitivity": 1.0,
    "tutorial_seen": SETTINGS_FLAGS["tutorial_seen"],
    "calibration_enabled": SETTINGS_FLAGS["calibration_enabled"],
    "diagnostics": SETTINGS_FLAGS["diagnostics"],
}

#: Clé de version dans la charge utile et dans le fichier.
SCHEMA_KEY = "schema_version"


class BarehandsSettingsError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _stored_version(stored: Mapping[str, Any]) -> int:
    """Version du bloc enregistré. Absente = « écrit par nous ».

    Un bloc v1 ne portait que ``enabled`` et **aucun** numéro ; on ne peut donc
    pas le distinguer d'un bloc v2 partiel par sa seule version. Il n'y a rien
    à distinguer : les huit autres clés y sont absentes et prennent leur
    défaut, ce qui est exactement la conversion v1 → v2.
    """

    raw = stored.get(SCHEMA_KEY)
    if raw is None:
        return SCHEMA_VERSION
    try:
        return int(raw)
    except (TypeError, ValueError):
        return -1


def load(settings: Mapping[str, Any]) -> dict[str, Any]:
    """Les réglages tels qu'ils s'appliquent. Toute valeur douteuse vaut le défaut.

    Lecture **tolérante**, comme `scene_settings.stored_gate` : un fichier
    abîmé ne doit pas rendre Bare Hands injoignable. Deux versions se lisent —
    la courante et celle de ``MIGRATED_SCHEMA_VERSIONS``, dont la conversion
    consiste à donner leur défaut aux huit clés que la v1 ne portait pas.

    Une version **étrangère** (écrite par un Jarvis plus récent) ne se devine
    pas : on n'en garde rien et Bare Hands reste éteint. Agir sur des réglages
    qu'on ne sait pas lire serait la panne que le refus codé existe pour
    empêcher ; le refus explicite, lui, arrive à l'écriture (``apply``).
    """

    stored = settings.get(SETTING_KEY)
    stored = stored if isinstance(stored, Mapping) else {}
    version = _stored_version(stored)
    if version != SCHEMA_VERSION and version not in MIGRATED_SCHEMA_VERSIONS:
        return dict(SETTINGS_DEFAULTS)
    value = dict(SETTINGS_DEFAULTS)
    for key, default in SETTINGS_DEFAULTS.items():
        raw = stored.get(key)
        if isinstance(default, bool):
            if isinstance(raw, bool):
                value[key] = raw
        elif key == "tool":
            if raw in INSTALLED_TOOLS:
                value[key] = raw
        elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
            low, high = SETTINGS_BOUNDS[key]
            # Borné sans conversion : un entier enregistré se relit entier,
            # pour que le fichier ne change pas de forme à chaque lecture.
            value[key] = min(max(raw, low), high)
    return value


def _check_number(key: str, raw: Any) -> float | int:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise BarehandsSettingsError(
            "barehands_setting_not_a_number", f"« {key} » doit être un nombre."
        )
    low, high = SETTINGS_BOUNDS[key]
    if not low <= raw <= high:
        raise BarehandsSettingsError(
            "barehands_setting_out_of_range",
            f"« {key} » doit rester entre {low} et {high} (reçu {raw}).",
        )
    return raw


def _check_tool(raw: Any) -> str:
    if raw not in TOOLS:
        raise BarehandsSettingsError("barehands_tool_unknown", f"Outil Bare Hands inconnu : {raw!r}.")
    if raw not in INSTALLED_TOOLS:
        raise BarehandsSettingsError(
            "barehands_tool_not_installed",
            f"L'outil « {raw} » est déclaré mais sans moteur en V1 : il ne ferait rien. "
            f"Outils disponibles : {', '.join(INSTALLED_TOOLS)}.",
        )
    return str(raw)


def apply(settings: dict[str, Any], payload: Any) -> dict[str, Any]:
    """Valider puis ranger les réglages dans ``settings`` (sans écrire le fichier).

    Écriture **stricte** : chaque refus porte un ``code`` stable, repris dans
    l'en-tête ``X-Jarvis-Error-Code``. Les clés absentes gardent la valeur
    enregistrée — l'interrupteur seul (``{"enabled": false}``) reste donc une
    écriture valide, ce qui est la raison d'être de cette route (F5).
    """

    if not isinstance(payload, Mapping):
        raise BarehandsSettingsError("barehands_bad_payload", "Le mode test Barehands attend un objet JSON.")
    unknown = set(payload) - set(SETTINGS_DEFAULTS) - {SCHEMA_KEY}
    if unknown:
        raise BarehandsSettingsError(
            "barehands_unknown_field", f"Réglage Barehands inconnu : {', '.join(sorted(map(str, unknown)))}."
        )
    version = payload.get(SCHEMA_KEY)
    if version is not None and version != SCHEMA_VERSION:
        # La couture de migration : c'est ici qu'une version précédente
        # s'accepterait et se convertirait, plutôt que de passer muette.
        raise BarehandsSettingsError(
            "barehands_schema_version_unsupported",
            f"Réglages Bare Hands en version {version!r} ; ce serveur n'écrit que la version {SCHEMA_VERSION}.",
        )
    if "enabled" not in payload:
        raise BarehandsSettingsError("barehands_enabled_missing", "Précisez « enabled » (true ou false).")
    value = load(settings)
    for key, raw in payload.items():
        if key == SCHEMA_KEY:
            continue
        if isinstance(SETTINGS_DEFAULTS[key], bool):
            if not isinstance(raw, bool):
                code = "barehands_enabled_not_boolean" if key == "enabled" else "barehands_setting_not_boolean"
                raise BarehandsSettingsError(code, f"« {key} » doit valoir true ou false.")
            value[key] = raw
        elif key == "tool":
            value[key] = _check_tool(raw)
        else:
            value[key] = _check_number(key, raw)
    settings[SETTING_KEY] = {SCHEMA_KEY: SCHEMA_VERSION, **value}
    return dict(value)


def vendor_root(project_root: Path, environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    override = str(env.get(VENDOR_ENV, "") or "").strip()
    if override:
        return Path(override).expanduser()
    return Path(project_root) / "third_party" / "barehands" / "vendor"


def asset_path(root: Path, name: str) -> tuple[Path, str] | None:
    """Fichier et type MIME d'un asset de la liste blanche, s'il est installé."""

    entry = ASSETS.get(name)
    if entry is None:
        return None
    relative, content_type = entry
    path = Path(root) / relative
    return (path, content_type) if path.is_file() else None


def describe_assets(root: Path) -> dict[str, Any]:
    missing = [name for name in REQUIRED_ASSETS if asset_path(root, name) is None]
    return {
        "installed": not missing,
        "missing": missing,
        "base_url": ASSET_ROUTE_PREFIX.rstrip("/"),
        "install_hint": INSTALL_HINT,
    }


def describe(settings: Mapping[str, Any], root: Path) -> dict[str, Any]:
    """Ce que `GET`/`POST /api/barehands` rendent : les neuf réglages à plat.

    À plat, et non sous un sous-objet, parce que ``enabled`` était déjà lu là
    par la page : élargir la charge utile ne devait pas déplacer le seul champ
    qui existait. ``tools`` dit **quels outils ont un moteur**, pour que la
    palette n'ait pas à le deviner ni à recopier la table.
    """

    return {
        **load(settings),
        "status": "experimental",
        "schema_version": SCHEMA_VERSION,
        "tools": list(TOOLS),
        "installed_tools": list(INSTALLED_TOOLS),
        "assets": describe_assets(root),
    }

"""Barehands en mode test : piloter le Control Center à mains nues.

Réimplémentation native, et volontairement réduite, de l'idée Barehands : la
webcam suit les mains dans la page du Control Center, chaque main détectée
affiche un jeton qui suit l'index, et un pincement pouce-index clique sous le
jeton. Tout le suivi tourne dans le navigateur (MediaPipe Hand Landmarker), sans
service cloud et sans le serveur Barehands (port 8794).

Ce module ne tient que ce que le serveur doit décider :

- le réglage persistant, éteint par défaut, rangé sous ``barehands_test_mode``
  dans ``runtime/control-center-settings.json`` ;
- la liste blanche des fichiers MediaPipe servis à la page. Ils ne sont pas
  versionnés : ``scripts/bootstrap_third_party.py`` les a vendorisés sous
  ``third_party/barehands/vendor`` (Apache-2.0). Aucun code upstream Barehands
  (AGPL) n'est repris ici ni dans la page.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

#: Bloc de réglages. Absent, tout est éteint.
SETTING_KEY = "barehands_test_mode"

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


class BarehandsSettingsError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def load(settings: Mapping[str, Any]) -> dict[str, bool]:
    """Le réglage tel qu'il s'applique. Toute valeur douteuse vaut « éteint »."""

    stored = settings.get(SETTING_KEY)
    stored = stored if isinstance(stored, Mapping) else {}
    return {"enabled": stored.get("enabled") is True}


def apply(settings: dict[str, Any], payload: Any) -> dict[str, bool]:
    """Valider puis ranger le réglage dans ``settings`` (sans écrire le fichier)."""

    if not isinstance(payload, Mapping):
        raise BarehandsSettingsError("barehands_bad_payload", "Le mode test Barehands attend un objet JSON.")
    unknown = set(payload) - {"enabled"}
    if unknown:
        raise BarehandsSettingsError(
            "barehands_unknown_field", f"Réglage Barehands inconnu : {', '.join(sorted(map(str, unknown)))}."
        )
    if "enabled" not in payload:
        raise BarehandsSettingsError("barehands_enabled_missing", "Précisez « enabled » (true ou false).")
    if not isinstance(payload["enabled"], bool):
        raise BarehandsSettingsError("barehands_enabled_not_boolean", "« enabled » doit valoir true ou false.")
    value = {"enabled": payload["enabled"]}
    settings[SETTING_KEY] = value
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
    return {**load(settings), "status": "experimental", "assets": describe_assets(root)}

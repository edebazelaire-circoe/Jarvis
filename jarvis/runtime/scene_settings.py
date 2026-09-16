"""Interrupteur de la scène constellation côté Control Center (handoff jarvis-constellation-scene-runtime, Slice 06).

`scene.enabled` (défaut **faux**) dans `runtime/control-center-settings.json`.
Décision PM consignée au Slice 11 : Core projette et stocke la scène quel que
soit l'interrupteur ; seuls le rendu (Slice 05/11) et l'outil MCP d'affichage du
cerveau (`jarvis/runtime/display_mcp.py`) en dépendent. Éteint, le cerveau est
lancé exactement comme avant : ni `--mcp-config`, ni consigne d'affichage.

Même forme que l'autorisation d'auto-développement (`self_dev.load_gate` /
`apply_gate`) : lecture tolérante, écriture stricte. `JARVIS_SCENE_ENABLED`
(`1/true/yes/on` ou `0/false/no/off`) l'emporte sur le fichier, comme
`JARVIS_VISUALIZER_ENABLED` pour le visage ; toute autre valeur est ignorée.

Un changement prend effet au prochain (re)démarrage du cerveau : les outils MCP
et la consigne système sont fixés au lancement du processus CLI.
"""

from __future__ import annotations

from collections.abc import Mapping
import os
from typing import Any

SETTING_KEY = "scene"
ENV_OVERRIDE = "JARVIS_SCENE_ENABLED"
_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


class SceneSettingsError(ValueError):
    """Réglage de scène refusé ; `code` stable pour l'en-tête d'erreur des réglages."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def env_override(environ: Mapping[str, str] | None = None) -> bool | None:
    raw = (os.environ if environ is None else environ).get(ENV_OVERRIDE, "").strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    return None


def load_gate(settings: Mapping[str, Any], environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """`{"enabled", "source"}` : valeur effective et d'où elle vient (`settings`, `env`)."""

    stored = settings.get(SETTING_KEY)
    stored = stored if isinstance(stored, dict) else {}
    enabled = stored.get("enabled") is True
    override = env_override(environ)
    if override is not None:
        return {"enabled": override, "source": "env"}
    return {"enabled": enabled, "source": "settings"}


def apply_gate(settings: dict[str, Any], payload: Any) -> dict[str, bool]:
    """Écrire `scene.enabled` dans `settings` (en mémoire) ; rend ce qui est stocké."""

    if not isinstance(payload, dict):
        raise SceneSettingsError("scene_bad_payload", "Le réglage de scène doit être un objet.")
    unknown = set(payload) - {"enabled"}
    if unknown:
        raise SceneSettingsError("scene_unknown_field", f"Réglage de scène inconnu : {', '.join(sorted(map(str, unknown)))}.")
    if "enabled" in payload and not isinstance(payload["enabled"], bool):
        raise SceneSettingsError("scene_bad_value", "scene.enabled doit être vrai ou faux.")
    current = settings.get(SETTING_KEY)
    enabled = payload["enabled"] if "enabled" in payload else (isinstance(current, dict) and current.get("enabled") is True)
    settings[SETTING_KEY] = {"enabled": enabled}
    return {"enabled": enabled}

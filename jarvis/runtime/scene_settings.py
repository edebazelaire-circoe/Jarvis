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

Effets d'un changement (Slice 11) : le rendu suit à la seconde, sans
rechargement (la page relit l'interrupteur dans `/api/status`) ; les outils MCP
et la consigne système du cerveau sont fixés au lancement du processus CLI et
ne changent qu'à son prochain (re)démarrage. Tant que la variable
d'environnement l'impose, l'écriture est refusée (`scene_env_override`) :
l'interrupteur de la page est en lecture seule et dit pourquoi.
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


def describe_gate(settings: Mapping[str, Any], environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Bloc `scene` de `GET/POST /api/settings` : `load_gate` plus ce que l'écran explique.

    `stored` : la valeur du fichier, ignorée tant que l'environnement l'impose ;
    `env` : nom de la variable qui l'emporte quand `source` vaut `env`, sinon `None`.
    """

    gate = load_gate(settings, environ)
    stored = settings.get(SETTING_KEY)
    return {
        **gate,
        "stored": isinstance(stored, dict) and stored.get("enabled") is True,
        "env": ENV_OVERRIDE if gate["source"] == "env" else None,
    }


def apply_gate(settings: dict[str, Any], payload: Any, environ: Mapping[str, str] | None = None) -> dict[str, bool]:
    """Écrire `scene.enabled` dans `settings` (en mémoire) ; rend ce qui est stocké.

    Refusé (`scene_env_override`) quand `JARVIS_SCENE_ENABLED` impose la valeur :
    écrire un choix qui ne s'appliquerait pas ferait croire à l'utilisateur
    qu'il a changé quelque chose.
    """

    if not isinstance(payload, dict):
        raise SceneSettingsError("scene_bad_payload", "Le réglage de scène doit être un objet.")
    unknown = set(payload) - {"enabled"}
    if unknown:
        raise SceneSettingsError("scene_unknown_field", f"Réglage de scène inconnu : {', '.join(sorted(map(str, unknown)))}.")
    if "enabled" in payload and not isinstance(payload["enabled"], bool):
        raise SceneSettingsError("scene_bad_value", "scene.enabled doit être vrai ou faux.")
    override = env_override(environ)
    if "enabled" in payload and override is not None:
        raise SceneSettingsError(
            "scene_env_override",
            f"{ENV_OVERRIDE} impose la scène {'activée' if override else 'désactivée'} : retirez la variable "
            "d'environnement et relancez le Control Center pour choisir ici.",
        )
    current = settings.get(SETTING_KEY)
    enabled = payload["enabled"] if "enabled" in payload else (isinstance(current, dict) and current.get("enabled") is True)
    settings[SETTING_KEY] = {"enabled": enabled}
    return {"enabled": enabled}

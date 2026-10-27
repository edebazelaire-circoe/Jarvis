"""Mode support des Réglages (V1.2 Slice 06, `docs/settings/support-mode.md`).

Un interrupteur de **navigation**, persisté dans `runtime/control-center-settings.json` (bloc `support_mode`, aucune
table, aucune migration) : dans une édition produit qui cache ses surfaces de développement, il montre de nouveau les
catégories des Réglages déclarées `support` (Architecture & Agents, Avancé & Diagnostics) pour un dépannage sur le
poste. Il ne fait rien d'autre :

- il n'est lu par aucun lancement d'agent : le manifeste de capacités (`agent_capabilities`, dérivé de l'édition du
  processus seulement) reste seul maître de ce que le cerveau et ses sous-agents peuvent appeler ;
- il n'est pas dans la projection `GET /api/settings` : le serveur MCP des réglages (`jarvis-console`) ne le voit pas
  et ne peut pas l'écrire ; seule la route `/api/support-mode` de la page l'écrit ;
- il ne change ni les types de Board, ni les connecteurs, ni `developer_surfaces` (les outils Trace, Test Lab, MCP,
  Prefabs du lanceur restent cachés).

Pur : aucune E/S. Le Control Center lit et écrit le fichier (`_write_settings`).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SETTING_KEY = "support_mode"
SCHEMA_KEY = "schema_version"
SCHEMA_VERSION = 1


class SupportModeError(ValueError):
    """Refus d'écriture, avec un code stable (en-tête `X-Jarvis-Error-Code`)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def inspect(settings: Mapping[str, Any]) -> dict[str, Any]:
    """`{"enabled": bool, "problem": code | None}`. Ne lève jamais.

    Absent : coupé. Présent mais illisible (pas un objet, autre version, valeur non booléenne) : coupé, avec le code
    du problème, que la page dit ; l'interrupteur le réécrit.
    """

    stored = settings.get(SETTING_KEY) if isinstance(settings, Mapping) else None
    if stored is None:
        return {"enabled": False, "problem": None}
    if not isinstance(stored, Mapping):
        return {"enabled": False, "problem": "support_mode_block_malformed"}
    version = stored.get(SCHEMA_KEY, SCHEMA_VERSION)
    if isinstance(version, bool) or version != SCHEMA_VERSION:
        return {"enabled": False, "problem": "support_mode_stored_version_unreadable"}
    value = stored.get("enabled", False)
    if not isinstance(value, bool):
        return {"enabled": False, "problem": "support_mode_value_invalid"}
    return {"enabled": value, "problem": None}


def apply(settings: dict[str, Any], payload: Any) -> bool:
    """Écriture stricte : `{"enabled": true|false}` exactement ; `settings` n'est touché qu'en cas de succès."""

    if not isinstance(payload, Mapping) or set(payload) != {"enabled"} or not isinstance(payload["enabled"], bool):
        raise SupportModeError("support_mode_bad_payload", 'Attendu exactement {"enabled": true | false}.')
    settings[SETTING_KEY] = {SCHEMA_KEY: SCHEMA_VERSION, "enabled": payload["enabled"]}
    return payload["enabled"]

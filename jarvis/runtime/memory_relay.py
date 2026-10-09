"""Mémoire du Control Center : section des réglages et relais de Core (handoff jarvis-memory-intelligence-knowledge, Slice 10b).

Deux rôles, aucun état propre.

**La section `memory` de `GET /api/settings`** (`memory_settings_section`) : ce que l'écran rend sans coder
un seul réglage en dur.

- `schema` : `describe_memory_settings()` (types, bornes, énumérations, défauts, règles de compatibilité) ;
- `values` : ce que le fichier dit seul ; `effective` : valeur et source `default|file|env` par champ ;
- `downgraded` : `{chemin: code}` des champs coupés parce que la combinaison lue est incohérente ;
- `secrets` : `has_secret` par jambe, **jamais** la valeur ;
- `loadouts` : les règles de loadout enregistrées ;
- `status` : l'état *déduit des réglages*, sans réseau (un GET de réglages reste immédiat) : par étage
  `status` (`ok|disabled|unavailable`), `reason_code`, `reason` et ce qu'il faut faire. L'état *vivant* des étages
  (sidecar injoignable, index en synchronisation, wiki sans source) vient de Core : `GET /api/memory/status`.

Les secrets restent dans `credentials`. Les réglages mémoire s'appliquent sans redémarrage au tour suivant
(rappel, budgets, bascules de connaissance) ; le fournisseur d'embeddings et le sidecar Tencent au prochain
démarrage de Core, ce que `status.restart_required` dit.

**`/api/memory/<reste>`** est relayé tel quel vers `/v1/memory/<reste>` (lecture : notes, recherche, état,
explication du rappel, candidats ; seule écriture : `POST /api/memory/candidates/{id}/decision`), même mécanique que `workspace_relay.py`. Toutes les méthodes sont gardées
(Host et Origin de bouclage, jamais cross-site) : une note est aussi sensible en lecture qu'en écriture.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aiohttp import web

from jarvis.domain.memory import CapabilityStatus
from jarvis.runtime.capture_relay import CaptureRelayRoutes
from jarvis.runtime.memory_settings import describe_memory_settings, memory_state

MEMORY_ROUTE = "/api/memory"
GUARDED_PREFIXES = (MEMORY_ROUTE,)

#: (action, chemin relatif sous `/api/memory` et `/v1/memory`).
_ROUTES = (
    ("memory_notes", "/notes"),
    ("memory_note", "/notes/{memory_id}"),
    ("memory_search", "/search"),
    ("memory_status", "/status"),
    ("memory_recall_explain", "/recall-explain"),
    ("memory_candidates", "/candidates"),
    ("memory_candidate", "/candidates/{candidate_id}"),
)
_DECISION_PATH = "/candidates/{candidate_id}/decision"
#: Les lectures de notes parcourent le disque : plus que les 10 s par défaut du transport.
_DISK_TIMEOUT_S = 30.0


class MemoryRelayRoutes(CaptureRelayRoutes):
    """Relais `/api/memory/*` -> `/v1/memory/*` (GET). Voir l'en-tête."""

    JOURNAL_PREFIX = "memory.request"

    def routes(self) -> list[web.RouteDef]:
        routes = [web.get(MEMORY_ROUTE + path, self._relay(action, "/v1/memory" + path, _DISK_TIMEOUT_S))
                  for action, path in _ROUTES]
        # La seule écriture de la surface (Slice 12) : accepter ou rejeter un candidat de consolidation.
        routes.append(web.post(MEMORY_ROUTE + _DECISION_PATH,
                               self._relay("memory_candidate_decision", "/v1/memory" + _DECISION_PATH, _DISK_TIMEOUT_S)))
        return routes


# ------------------------------------------------------------------ état déduit


def _leg(status: CapabilityStatus, code: str | None = None, reason: str = "", *, fix: str = "") -> dict[str, Any]:
    return {"status": status.value, "reason_code": code, "reason": reason, "how_to_fix": fix}


def _enabled(code_off: str, label: str) -> dict[str, Any]:
    return _leg(CapabilityStatus.DISABLED, code_off, f"{label} : désactivé dans les réglages.")


def _status_from_settings(state: Mapping[str, Any]) -> dict[str, Any]:
    """L'état attendu de chaque étage d'après les seuls réglages et la présence d'un jeton. Pas de réseau."""

    value = {path: item["value"] for path, item in state["effective"].items()}
    secrets = state["secrets"]
    legs: dict[str, dict[str, Any]] = {
        "lexical": _leg(CapabilityStatus.OK),
        "recall": _leg(CapabilityStatus.OK) if value["recall.enabled"]
        else _enabled("recall_disabled", "Rappel"),
    }
    if not value["semantic.enabled"]:
        legs["semantic"] = _enabled("semantic_disabled", "Recherche sémantique")
    elif not secrets["semantic"]["has_secret"]:
        legs["semantic"] = _leg(
            CapabilityStatus.UNAVAILABLE, "semantic_no_key",
            "Recherche sémantique activée mais aucune clé du fournisseur d'embeddings.",
            fix="Ajouter la clé dans API Keys ; le rappel lexical continue.")
    else:
        legs["semantic"] = _leg(CapabilityStatus.OK)
    if not value["tencent.enabled"]:
        legs["tencent"] = _enabled("tencent_disabled", "Sidecar Tencent")
    else:
        legs["tencent"] = _leg(CapabilityStatus.OK)
        legs["tencent"]["has_token"] = bool(secrets["tencent"]["has_secret"])
    for toggle, name in (("wiki_enabled", "wiki"), ("codegraph_enabled", "codegraph"), ("skills_enabled", "skills")):
        legs[f"knowledge:{name}"] = (
            _leg(CapabilityStatus.OK) if value[f"knowledge.{toggle}"] else _enabled(f"{name}_disabled", name))
    return legs


#: Réglages qui ne s'appliquent qu'au prochain démarrage de Core (`memory_wiring.py`).
RESTART_REQUIRED = ("semantic.enabled", "semantic.provider", "semantic.allow_private",
                    "tencent.enabled", "tencent.url", "tencent.service_id", "tencent.allow_private")


def memory_status(state: Mapping[str, Any]) -> dict[str, Any]:
    """`status` de la section : étages déduits, champs coupés (`downgraded`) et réglages à redémarrage."""

    legs = _status_from_settings(state)
    downgraded = dict(state["downgraded"])
    for path, leg in (("semantic.enabled", "semantic"), ("tencent.enabled", "tencent")):
        if path in downgraded:  # réglage lu incohérent : l'étage est coupé, et on dit pourquoi
            legs[leg]["reason_code"] = downgraded[path]
            legs[leg]["reason"] += " Combinaison incohérente dans le fichier : étage coupé."
    return {
        "source": "settings",
        "legs": legs,
        "downgraded": downgraded,
        "restart_required": list(RESTART_REQUIRED),
        "live": MEMORY_ROUTE + "/status",
    }


def memory_settings_section(settings: Mapping[str, Any], environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """La section `memory` de `GET /api/settings`. Aucune valeur secrète, aucun appel réseau."""

    state = memory_state(settings, environ)
    return {"schema": describe_memory_settings(), **state, "status": memory_status(state)}



# ------------------------------------------------------------------ Slice 05b : relais du cerveau
# `/api/memory/brain/*` -> Core, pour le serveur MCP `jarvis-memory` (budget de 3 appels par tour tenu par Core).

MEMORY_BRAIN_ROUTE = "/api/memory/brain"
MEMORY_BRAIN_GUARDED_PREFIXES = (MEMORY_BRAIN_ROUTE,)
#: Un candidat proposé : titre, corps (4 000 caractères), quelques champs.
MAX_PROPOSAL_BODY_BYTES = 32 * 1024

_BRAIN_ROUTES = (
    ("GET", "memory_brain_search", "/search", "/v1/memory/brain/search"),
    ("GET", "memory_brain_read", "/notes/{memory_id}", "/v1/memory/brain/notes/{memory_id}"),
    ("POST", "memory_brain_propose", "/candidates", "/v1/memory/candidates"),
    ("GET", "memory_brain_knowledge_search", "/knowledge/search", "/v1/memory/brain/knowledge/search"),
    ("GET", "memory_brain_knowledge_read", "/knowledge/{kind}/{asset_id}",
     "/v1/memory/brain/knowledge/{kind}/{asset_id}"),
)


class MemoryBrainRelayRoutes(CaptureRelayRoutes):
    """Relais `/api/memory/brain/*` -> Core. Voir l'en-tête."""

    JOURNAL_PREFIX = "memory.request"
    MAX_BODY_BYTES = MAX_PROPOSAL_BODY_BYTES

    def routes(self) -> list[web.RouteDef]:
        return [web.route(method, MEMORY_BRAIN_ROUTE + path, self._relay(action, core, None))
                for method, action, path, core in _BRAIN_ROUTES]

"""La politique par rôle des sous-agents telle qu'elle est enregistrée, révisée et décrite.

`jarvis.domain.role_routing` dit ce qu'est une politique de rôle et comment elle tranche. Ce module
fait le reste du chemin, avec les mêmes règles que `agent_routing` : **lire est tolérant, écrire est
strict**, et une préférence enregistrée ne disparaît jamais toute seule.

Stockage : un fichier dédié, `<runtime>/subagent-role-routing.json`, à côté de
`control-center-settings.json` et non dans une de ses clés. Raison : `POST /api/settings` relit puis
réécrit ce fichier entier sans révision ; une clé à l'intérieur serait écrasée par n'importe quel
enregistrement concurrent de la page Réglages, et la révision de la politique par rôle (C8 : `409`
sur révision périmée) ne protégerait rien. Un fichier à part a son propre écrivain, sa propre
révision, et le hook le lit comme il lit déjà les réglages (une lecture de disque, hors réseau).

Forme du fichier (`schema_version` 1) ::

    {"schema_version": 1, "revision": 3,
     "roles": {"qa": {"candidates": [{"agent": "claude", "model": "x"}],
                      "allow_general_fallback": true, "updated_at": "…"}}}

Un rôle absent de `roles` **hérite** de son `default_profile` (aucune écriture de migration). Une entrée
de rôle inconnu (rôle retiré du registre) est conservée telle quelle au fil des écritures : elle n'est
ni lue ni effacée.

Contrat : `docs/subagent-roles.md` § 10.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Sequence

from jarvis.adapters.file_replace import replace_with_retry
from jarvis.domain import role_routing, routing
from jarvis.domain.role_routing import RolePolicy, RoleRoutingDocument
from jarvis.domain.routing import CandidateRef, ModelCandidate, NoEligibleCandidateError, RoutingError, RoutingPolicy
from jarvis.domain.subagent_roles import ROLES, ROLE_ALIASES, SubagentRole
from jarvis.runtime import agent_routing

STORE_FILE = "subagent-role-routing.json"
SCHEMA_VERSION = 1
REVISION_PREFIX = "rr-"
#: Le hook relit le fichier à chaque lancement d'agent : une écriture vaut pour la prochaine délégation.
APPLIES = "live"
#: Seul le CLI Claude hôte lance des sous-agents (outil `Agent`) : `routing_hook.HOST_AGENT`.
HOST_AGENT = "claude"

HOST_ONLY_REASON = (
    "Seul le CLI Claude hôte lance des sous-agents aujourd'hui : ce candidat reste enregistré "
    "mais n'est pas sélectionnable."
)
STORE_UNREADABLE_REASON = (
    "Le fichier de la politique par rôle est illisible ; il n'est pas réécrit. "
    "Mettez-le de côté pour repartir de l'héritage."
)

#: Codes stables -> statut HTTP (lu par `subagent_role_routing_http`).
STALE_CODE = "role_routing_revision_stale"
UNKNOWN_ROLE_CODE = "role_routing_unknown_role"
BAD_PAYLOAD_CODE = "role_routing_bad_payload"
EMPTY_CODE = "role_routing_empty_candidates"
UNREADABLE_CODE = "role_routing_store_unreadable"
WRITE_FAILED_CODE = "role_routing_write_failed"
NOT_EXPLICIT_CODE = "role_routing_not_explicit"


class RoleRoutingStaleError(RoutingError):
    def __init__(self, current: str) -> None:
        super().__init__(
            STALE_CODE,
            f"La politique des rôles a changé depuis votre lecture (révision actuelle {current}) ; relisez-la.",
        )
        self.current = current


def format_revision(revision: int) -> str:
    return f"{REVISION_PREFIX}{revision}"


# ------------------------------------------------------------------- lecture


@dataclass(frozen=True, slots=True)
class LoadedDocument:
    document: RoleRoutingDocument
    raw: dict[str, Any]
    #: `""` si le fichier est lisible ou absent (premier démarrage) ; sinon un code stable.
    error_code: str = ""
    error_reason: str = ""


def _parse(raw: Mapping[str, Any]) -> RoleRoutingDocument:
    revision = raw.get("revision")
    revision = revision if isinstance(revision, int) and revision >= 0 else 0
    roles_raw = raw.get("roles")
    roles_raw = roles_raw if isinstance(roles_raw, Mapping) else {}
    roles: dict[str, RolePolicy] = {}
    for key, entry in roles_raw.items():
        if not isinstance(entry, Mapping):
            continue
        try:
            role = role_routing.canonical_role(key)
            policy = RolePolicy(
                role_id=role.id,
                candidates=agent_routing.read_candidates(entry.get("candidates")),
                allow_general_fallback=bool(entry.get("allow_general_fallback", True)),
            )
        except RoutingError:
            # Rôle inconnu ou liste vidée par la lecture tolérante : le rôle hérite. L'entrée reste
            # dans le fichier (voir `_write`), rien n'est effacé.
            continue
        # La clé canonique l'emporte sur un alias écrit à la main (`reviewer` et `qa` ensemble).
        if role.id in roles and key != role.id:
            continue
        roles[role.id] = policy
    return RoleRoutingDocument(revision=revision, roles=roles)


def load(runtime_root: Path) -> LoadedDocument:
    """Le document enregistré, sans jamais lever. Absent = tout hérite, révision 0."""
    path = Path(runtime_root) / STORE_FILE
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        # Normal au premier démarrage et tant que personne n'a réglé un rôle : tout hérite.
        return LoadedDocument(role_routing.EMPTY_DOCUMENT, {})
    except OSError as exc:
        return LoadedDocument(role_routing.EMPTY_DOCUMENT, {}, UNREADABLE_CODE,
                              f"{STORE_UNREADABLE_REASON} ({type(exc).__name__})")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        return LoadedDocument(role_routing.EMPTY_DOCUMENT, {}, UNREADABLE_CODE,
                              f"{STORE_UNREADABLE_REASON} (JSON invalide, ligne {exc.lineno})")
    if not isinstance(raw, dict):
        return LoadedDocument(role_routing.EMPTY_DOCUMENT, {}, UNREADABLE_CODE,
                              f"{STORE_UNREADABLE_REASON} (objet attendu)")
    return LoadedDocument(_parse(raw), raw)


def load_document(runtime_root: Path) -> RoleRoutingDocument:
    """Pour le hook : le document lisible, ou l'héritage complet si le fichier est absent ou abîmé."""
    return load(runtime_root).document


# ------------------------------------------------------------------ écriture


class RoleRoutingStore:
    """Seul écrivain de `subagent-role-routing.json` : révision vérifiée, écriture atomique."""

    def __init__(self, runtime_root: Path) -> None:
        self.runtime_root = Path(runtime_root)
        self.path = self.runtime_root / STORE_FILE
        self._lock = RLock()

    def load(self) -> LoadedDocument:
        return load(self.runtime_root)

    def put(self, role_raw: object, payload: Mapping[str, Any], base_revision: object) -> RoleRoutingDocument:
        """Remplacer la politique explicite d'un seul rôle. Tout est validé avant d'écrire."""
        role = role_routing.canonical_role(role_raw)
        if not isinstance(payload, Mapping):
            raise RoutingError(BAD_PAYLOAD_CODE, "La politique d'un rôle doit être un objet.")
        if "candidates" not in payload:
            raise RoutingError(BAD_PAYLOAD_CODE, "« candidates » est requis (liste ordonnée de {agent, model}).")
        fallback = payload.get("allow_general_fallback", True)
        if not isinstance(fallback, bool):
            raise RoutingError(BAD_PAYLOAD_CODE, "« allow_general_fallback » doit être vrai ou faux.")
        candidates = agent_routing.parse_candidates(payload["candidates"], role.id, owner="le rôle")
        policy = RolePolicy(role_id=role.id, candidates=candidates, allow_general_fallback=fallback)
        with self._lock:
            loaded = self._writable(base_revision)
            entry = {**policy.as_dict(), "updated_at": _now()}
            del entry["role_id"]
            return self._write(loaded, role, entry)

    def restore(self, role_raw: object, base_revision: object) -> RoleRoutingDocument:
        """Rendre un rôle à l'héritage de son `default_profile` en retirant sa politique explicite."""
        role = role_routing.canonical_role(role_raw)
        with self._lock:
            loaded = self._writable(base_revision)
            if loaded.document.for_role(role.id) is None:
                raise RoutingError(NOT_EXPLICIT_CODE, f"Le rôle « {role.name} » hérite déjà de son profil.")
            return self._write(loaded, role, None)

    def _writable(self, base_revision: object) -> LoadedDocument:
        loaded = self.load()
        if loaded.error_code:
            raise RoutingError(loaded.error_code, loaded.error_reason)
        current = format_revision(loaded.document.revision)
        if not isinstance(base_revision, str) or base_revision != current:
            raise RoleRoutingStaleError(current)
        return loaded

    def _write(self, loaded: LoadedDocument, role: SubagentRole, entry: dict[str, Any] | None) -> RoleRoutingDocument:
        raw = dict(loaded.raw)
        roles = dict(raw.get("roles") if isinstance(raw.get("roles"), Mapping) else {})
        # Un alias écrit à la main pour ce rôle disparaît avec l'écriture canonique : une seule entrée par rôle.
        for alias, target in ROLE_ALIASES.items():
            if target == role.id:
                roles.pop(alias, None)
        if entry is None:
            roles.pop(role.id, None)
        else:
            roles[role.id] = entry
        raw.update({"schema_version": SCHEMA_VERSION, "revision": loaded.document.revision + 1, "roles": roles})
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            replace_with_retry(tmp, self.path)
        except OSError as exc:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                # intentionnel : le temporaire ne porte aucun secret ; l'échec principal est déjà levé.
                pass
            raise RoutingError(
                WRITE_FAILED_CODE,
                f"Politique du rôle « {role.name} » non enregistrée ({type(exc).__name__}) ; rien n'a changé.",
            ) from exc
        return _parse(raw)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# -------------------------------------------------------------- description


def _candidate_view(ref: CandidateRef, position: int, known: Mapping[tuple[str, str], ModelCandidate]) -> dict[str, Any]:
    item = known.get((ref.agent, ref.model))
    available = bool(item and item.available)
    reason = "" if available else (
        (item.unavailable_reason if item else "")
        or (agent_routing.MISSING_MODEL_REASON if ref.model else agent_routing.MISSING_AGENT_REASON)
    )
    selectable = available and ref.agent == HOST_AGENT
    return {
        **ref.as_dict(),
        "position": position,
        "label": (item.label if item else "") or ref.key,
        "available": available,
        "unavailable_reason": reason,
        "selectable": selectable,
        "selectable_reason": "" if selectable else (reason or HOST_ONLY_REASON),
    }


def _preview(role: SubagentRole, document: RoleRoutingDocument, profiles: RoutingPolicy,
             host: Sequence[ModelCandidate]) -> dict[str, Any]:
    """Ce que le hook choisirait si ce rôle était lancé avec son profil par défaut, maintenant."""
    try:
        decision = role_routing.resolve_for_role(role, None, document, profiles, list(host), source="preview")
    except NoEligibleCandidateError as exc:
        return {"outcome": "refused", "code": exc.code, "reason": str(exc),
                "considered": [verdict.as_dict() for verdict in exc.verdicts]}
    if decision.reason == routing.REASON_COMPATIBILITY or not decision.agent:
        return {"outcome": "cli_default", "reason": routing.REASON_COMPATIBILITY,
                "detail": "Le CLI garde son propre modèle (aucune liste ne s'impose)."}
    payload = decision.as_dict()
    payload.pop("source", None)
    return {"outcome": "selected", **payload}


def describe_role(role: SubagentRole, document: RoleRoutingDocument, profiles: RoutingPolicy,
                  candidates: Sequence[ModelCandidate]) -> dict[str, Any]:
    known = {(item.agent, item.model): item for item in candidates}
    host = [item for item in candidates if item.agent == HOST_AGENT]
    effective = role_routing.effective_policy(role, document, profiles)
    general = profiles.for_profile(routing.GENERAL_PROFILE)
    fallback_applicable = not (not effective.explicit and effective.inherited_profile == routing.GENERAL_PROFILE)
    return {
        "role_id": role.id,
        "marker": role.marker,
        "name": role.name,
        "aliases": sorted(alias for alias, target in ROLE_ALIASES.items() if target == role.id),
        "default_profile": role.default_profile,
        "provenance": effective.provenance,
        "explicit": effective.explicit,
        "inherited_profile": effective.inherited_profile,
        "binding": effective.binding,
        "binding_reason": effective.binding_reason,
        "restorable": effective.explicit,
        "allow_general_fallback": effective.allow_general_fallback,
        "candidates": [_candidate_view(ref, index, known) for index, ref in enumerate(effective.candidates)],
        "fallback": {
            "enabled": effective.allow_general_fallback and fallback_applicable,
            "profile": routing.GENERAL_PROFILE,
            "candidates": [
                _candidate_view(ref, index, known)
                for index, ref in enumerate(general.candidates if general is not None and general.enabled else ())
            ],
        },
        "preview": _preview(role, document, profiles, host),
    }


def describe(
    document: RoleRoutingDocument,
    profiles: RoutingPolicy,
    candidates: Sequence[ModelCandidate],
    *,
    store_error: tuple[str, str] = ("", ""),
    catalog_error: str = "",
) -> dict[str, Any]:
    """La lecture servie à l'onglet Sous-agents : un bloc par rôle actif, dans l'ordre du registre.

    `candidates` doit déjà contenir les candidats enregistrés disparus (`enrich`) : un candidat
    indisponible reste visible avec sa raison, il ne s'efface pas.
    """
    store_code, store_reason = store_error
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "revision": format_revision(document.revision),
        "applies": APPLIES,
        "store": {"status": "unreadable" if store_code else "ok", "code": store_code, "reason": store_reason},
        "catalog": {"status": "unavailable" if catalog_error else "ok", "reason": catalog_error},
        "compatibility": {
            "delegation_mode": agent_routing.DELEGATION_AUTO if profiles.enabled else agent_routing.DELEGATION_DUPLICATE,
            "profiles_enabled": profiles.enabled,
            "note": (
                "Une politique explicite de rôle s'applique quel que soit Auto/Dupliqué ; "
                "un rôle qui hérite suit la politique par profil, active seulement en Auto."
            ),
        },
        "roles": [describe_role(role, document, profiles, candidates) for role in ROLES if role.enabled],
        "harnesses": agent_routing.group_by_harness(candidates),
    }


def enrich(candidates: Sequence[ModelCandidate], profiles: RoutingPolicy, document: RoleRoutingDocument,
           *, unavailable_reasons_by_agent: Mapping[str, str] | None = None) -> list[ModelCandidate]:
    """`agent_routing.with_saved` étendu aux listes de rôle."""
    return agent_routing.with_saved(candidates, profiles, unavailable_reasons_by_agent=unavailable_reasons_by_agent,
                                    extra_refs=document.refs())

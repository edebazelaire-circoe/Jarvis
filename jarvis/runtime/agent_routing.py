"""La politique d'aiguillage telle qu'elle est enregistrée, lue et affichée.

`jarvis.domain.routing` dit ce qu'est une politique et comment elle tranche.
Ce module fait le reste du chemin : lire les réglages sans jamais planter,
écrire en refusant tout ce qui est douteux, et décrire à l'interface ce qui
existe réellement sur cette machine.

Deux règles tiennent tout :

- **lire est tolérant, écrire est strict.** Un fichier de réglages abîmé ou
  venu d'une version antérieure ne doit pas empêcher l'écran de s'ouvrir ; une
  requête malformée, elle, est refusée en entier, sans écriture partielle.
- **une préférence enregistrée ne disparaît jamais toute seule.** Une clé
  retirée ou un modèle déprécié rendent un candidat indisponible, pas absent :
  il reste visible, marqué, et redevient utilisable si le fournisseur revient.

Aucune liste de modèles n'est écrite ici. Les candidats sont construits à
partir de `cli_catalog` (ce qui est installé) et de `model_catalog` (ce que le
fournisseur déclare aujourd'hui).
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from jarvis.domain import routing
from jarvis.domain.routing import (
    CandidateRef,
    ModelCandidate,
    ProfilePolicy,
    RoutingError,
    RoutingPolicy,
)

#: Clé unique du bloc dans `control-center-settings.json`. Les réglages vocaux
#: ont leurs propres clés : un modèle de voix n'est pas un candidat de
#: sous-agent, et rien ici ne doit les attraper.
SETTING_KEY = "agent_routing"

#: Modèle absent du catalogue : le candidat reste, marqué.
MISSING_MODEL_REASON = "Ce modèle n'est plus proposé par le fournisseur."
MISSING_AGENT_REASON = "Ce CLI n'est pas installé sur cette machine."
DEFAULT_MODEL_LABEL = "Modèle par défaut du CLI"


# ------------------------------------------------------------------- lecture


def _read_candidates(raw: object) -> tuple[CandidateRef, ...]:
    refs: list[CandidateRef] = []
    for entry in raw if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) else ():
        try:
            ref = CandidateRef.parse(entry)
        except RoutingError:
            # Entrée illisible : elle est perdue, pas propagée. La politique
            # restante vaut mieux qu'un écran qui refuse de s'ouvrir.
            continue
        if ref not in refs:
            refs.append(ref)
    return tuple(refs)


def load_policy(settings: Mapping[str, Any]) -> RoutingPolicy:
    """La politique enregistrée, complétée des profils manquants.

    Toujours les quatre profils, dans l'ordre canonique : l'interface en
    dépend, et un profil absent des réglages n'est pas un profil inexistant.
    """
    stored = settings.get(SETTING_KEY)
    stored = stored if isinstance(stored, Mapping) else {}
    profiles_raw = stored.get("profiles")
    profiles_raw = profiles_raw if isinstance(profiles_raw, Mapping) else {}

    profiles: list[ProfilePolicy] = []
    for spec in routing.TASK_PROFILES:
        entry = profiles_raw.get(spec.id)
        entry = entry if isinstance(entry, Mapping) else {}
        profiles.append(
            ProfilePolicy(
                profile=spec.id,
                candidates=_read_candidates(entry.get("candidates")),
                enabled=bool(entry.get("enabled", True)),
                allow_general_fallback=bool(entry.get("allow_general_fallback", True)),
            )
        )
    return RoutingPolicy(enabled=bool(stored.get("enabled", False)), profiles=tuple(profiles))


def store(settings: dict[str, Any], policy: RoutingPolicy) -> None:
    settings[SETTING_KEY] = {
        "enabled": policy.enabled,
        "profiles": {entry.profile: entry.as_dict() for entry in policy.profiles},
    }


# ------------------------------------------------------------------ écriture


def _write_candidates(raw: object, profile: str) -> tuple[CandidateRef, ...]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise RoutingError(
            "routing_bad_candidates",
            f"Les candidats du profil « {profile} » doivent être une liste.",
        )
    refs: list[CandidateRef] = []
    for entry in raw:
        ref = CandidateRef.parse(entry)
        if ref.agent not in _known_agents():
            raise RoutingError("routing_unknown_agent", f"CLI inconnu dans le profil « {profile} » : {ref.agent}.")
        if ref in refs:
            raise RoutingError(
                "routing_duplicate_candidate",
                f"« {ref.key} » est proposé deux fois dans le profil « {profile} ».",
            )
        refs.append(ref)
    return tuple(refs)


def _known_agents() -> tuple[str, ...]:
    # Import tardif : `cli_catalog` importe déjà le domaine de l'aiguillage, et
    # un import croisé au chargement du module ferait boucle.
    from jarvis.runtime import cli_catalog

    return cli_catalog.AGENT_CLI_IDS


def apply(settings: dict[str, Any], payload: Mapping[str, Any]) -> RoutingPolicy:
    """Valider puis enregistrer une politique reçue de l'interface.

    Tout est vérifié avant d'écrire quoi que ce soit : une requête à moitié
    valide laisse les réglages précédents intacts. La disponibilité n'est
    délibérément pas vérifiée ici — un candidat momentanément injoignable reste
    un choix légitime, que `resolve` écartera le moment venu.
    """
    if not isinstance(payload, Mapping):
        raise RoutingError("routing_bad_payload", "L'aiguillage doit être un objet.")

    current = load_policy(settings)
    enabled = current.enabled if payload.get("enabled") is None else bool(payload["enabled"])

    profiles_raw = payload.get("profiles")
    if profiles_raw is None:
        profiles_raw = {}
    if not isinstance(profiles_raw, Mapping):
        raise RoutingError("routing_bad_payload", "« profiles » doit être un objet.")
    for name in profiles_raw:
        if not routing.is_profile(name):
            raise RoutingError("routing_unknown_profile", f"Profil de tâche inconnu : « {name} ».")

    profiles: list[ProfilePolicy] = []
    for entry in current.profiles:
        patch = profiles_raw.get(entry.profile)
        if not isinstance(patch, Mapping):
            profiles.append(entry)
            continue
        candidates = entry.candidates if patch.get("candidates") is None else _write_candidates(patch["candidates"], entry.profile)
        profiles.append(
            ProfilePolicy(
                profile=entry.profile,
                candidates=candidates,
                enabled=entry.enabled if patch.get("enabled") is None else bool(patch["enabled"]),
                allow_general_fallback=(
                    entry.allow_general_fallback
                    if patch.get("allow_general_fallback") is None
                    else bool(patch["allow_general_fallback"])
                ),
            )
        )

    policy = RoutingPolicy(enabled=enabled, profiles=tuple(profiles))
    store(settings, policy)
    return policy


# ------------------------------------------------------------------ candidats


def build_candidates(
    agents: Iterable[Mapping[str, Any]],
    models: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[ModelCandidate]:
    """Les couples agent + modèle réellement proposables, à cet instant.

    `agents` vient de `cli_catalog.detect_all` (installé ou non, avec la
    raison), `models` du catalogue vivant de chaque fournisseur, déjà filtré
    sur l'usage texte. Un sous-agent n'a que faire d'un modèle temps réel ou
    d'une voix de synthèse.

    L'entrée « modèle par défaut » existe pour chaque CLI : c'est le seul choix
    qui ne périme pas, puisque c'est le CLI qui tranche.
    """
    candidates: list[ModelCandidate] = []
    for agent in agents:
        agent_id = str(agent.get("id") or "")
        if not agent_id:
            continue
        capabilities = frozenset(str(value) for value in agent.get("capabilities") or ())
        available = bool(agent.get("available"))
        reason = str(agent.get("error") or "") or ("" if available else MISSING_AGENT_REASON)
        provider = str(agent.get("model_provider") or "")
        label = str(agent.get("label") or agent_id)

        candidates.append(
            ModelCandidate(
                agent=agent_id,
                model=routing.DEFAULT_MODEL,
                label=f"{label} · {DEFAULT_MODEL_LABEL}",
                provider=provider,
                capabilities=capabilities,
                available=available,
                unavailable_reason=reason,
            )
        )
        for model in models.get(provider) or ():
            model_id = str(model.get("id") or "")
            if not model_id:
                continue
            candidates.append(
                ModelCandidate(
                    agent=agent_id,
                    model=model_id,
                    label=f"{label} · {model.get('label') or model_id}",
                    provider=provider,
                    capabilities=capabilities,
                    available=available,
                    unavailable_reason=reason,
                )
            )
    return candidates


def with_saved(candidates: Sequence[ModelCandidate], policy: RoutingPolicy) -> list[ModelCandidate]:
    """Ajouter, marqués indisponibles, les candidats enregistrés qui ont disparu.

    Sans cela, une clé API retirée ferait taire un choix de l'utilisateur : le
    candidat sortirait de l'écran, et le réglage semblerait s'être effacé tout
    seul. Il reste, il est dit indisponible, et il revient à la vie dès que le
    fournisseur le redonne.
    """
    known = {(item.agent, item.model) for item in candidates}
    enriched = list(candidates)
    for entry in policy.profiles:
        for ref in entry.candidates:
            if (ref.agent, ref.model) in known:
                continue
            known.add((ref.agent, ref.model))
            enriched.append(
                ModelCandidate(
                    agent=ref.agent,
                    model=ref.model,
                    label=ref.key,
                    capabilities=frozenset(),
                    available=False,
                    unavailable_reason=MISSING_MODEL_REASON if ref.model else MISSING_AGENT_REASON,
                )
            )
    return enriched


def describe(policy: RoutingPolicy, candidates: Sequence[ModelCandidate]) -> dict[str, Any]:
    """Ce que l'interface affiche : les profils, les candidats, leur état.

    Aucun secret ne passe ici — ni clé, ni indice de clé : un candidat dit
    seulement s'il est utilisable, et sinon pourquoi, en clair.
    """
    return {
        "enabled": policy.enabled,
        "profiles": routing.describe_profiles(),
        "policy": {entry.profile: entry.as_dict() for entry in policy.profiles},
        "candidates": [item.as_dict() for item in candidates],
        "capabilities": list(routing.CAPABILITIES),
    }

"""Qui exécute quoi : le profil d'une tâche déléguée, et ce qu'on a le droit d'y mettre.

Le cerveau dit ce dont la tâche a besoin — du travail sur le poste, du code
avancé, une réponse sémantique rapide. Il ne choisit pas le modèle. Le choix
appartient au runtime, qui croise ce besoin avec la politique enregistrée dans
les réglages et avec ce qui est réellement installé et joignable.

Deux raisons à cette séparation :

- un modèle nommé par un LLM n'existe pas forcément, ou plus ; seule l'API du
  fournisseur (`model_catalog`) et le PATH (`cli_catalog`) disent ce qui existe ;
- ce que l'utilisateur a interdit doit rester interdit, même si le modèle est
  parfaitement disponible et que le cerveau le réclame.

Rien ici ne connaît de fournisseur : pas d'import de SDK, pas de liste de
modèles écrite en dur. Les identifiants de modèles sont des données qui
traversent ce module, jamais des constantes qu'il déclare.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

# --------------------------------------------------------------------- capacités

#: Ce qu'une tâche peut exiger d'un couple agent + modèle. Une capacité n'est
#: listée que si quelque chose sait la mesurer : elle vient des spécifications
#: de CLI (`cli_catalog.AgentCliSpec.features`) ou des usages déclarés par le
#: catalogue du fournisseur (`model_catalog.ROLES`).
COMPUTER_USE = "computer_use"
CODE = "code"
SEMANTIC = "semantic"
BACKGROUND = "background"
STREAMING = "streaming"
SANDBOX = "sandbox"

CAPABILITIES: tuple[str, ...] = (COMPUTER_USE, CODE, SEMANTIC, BACKGROUND, STREAMING, SANDBOX)


@dataclass(frozen=True, slots=True)
class TaskProfileSpec:
    """Une famille de travail déléguée, telle que l'utilisateur la règle."""

    id: str
    label: str
    description: str
    # Exigées par le profil lui-même. Une intention peut en ajouter, jamais en
    # retirer : c'est ce qui empêche un profil « code » d'atterrir sur un
    # candidat qui ne sait pas écrire de fichier.
    requires: tuple[str, ...] = ()


#: Vocabulaire canonique des profils. Quatre suffisent aux usages nommés par
#: l'utilisateur ; en ajouter un est une décision produit, pas un réglage.
TASK_PROFILES: tuple[TaskProfileSpec, ...] = (
    TaskProfileSpec(
        id="desktop",
        label="Poste de travail",
        description="Piloter la machine : bureautique, navigateur, fenêtres, fichiers ouverts.",
        requires=(COMPUTER_USE,),
    ),
    TaskProfileSpec(
        id="code",
        label="Code avancé",
        description="Lire, écrire et refondre du code ; travail long en plusieurs étapes.",
        requires=(CODE,),
    ),
    TaskProfileSpec(
        id="fast",
        label="Sémantique rapide",
        description="Résumer, classer, reformuler, répondre court : la latence prime.",
        requires=(SEMANTIC,),
    ),
    TaskProfileSpec(
        id="general",
        label="Général",
        description="Tout le reste, et recours des autres profils quand ils n'ont plus de candidat.",
    ),
)

TASK_PROFILE_IDS: tuple[str, ...] = tuple(spec.id for spec in TASK_PROFILES)
GENERAL_PROFILE = "general"
_PROFILES: dict[str, TaskProfileSpec] = {spec.id: spec for spec in TASK_PROFILES}


def profile_spec(profile: str) -> TaskProfileSpec:
    """Le profil demandé, ou une erreur : un profil inconnu n'est pas un défaut.

    Retomber en silence sur « général » ferait passer une faute de frappe du
    cerveau pour un choix, et le candidat retenu serait inexplicable.
    """
    name = str(profile or "").strip().lower()
    spec = _PROFILES.get(name)
    if spec is None:
        raise RoutingError("routing_unknown_profile", f"Profil de tâche inconnu : « {profile} ».")
    return spec


def is_profile(value: object) -> bool:
    return str(value or "").strip().lower() in _PROFILES


# ----------------------------------------------------------------------- erreurs


class RoutingError(ValueError):
    """Refus d'aiguillage, avec un code stable que l'interface et les tests lisent."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class NoEligibleCandidateError(RoutingError):
    """Aucun candidat autorisé n'est utilisable. Les verdicts disent pourquoi."""

    def __init__(self, message: str, verdicts: tuple["CandidateVerdict", ...]) -> None:
        super().__init__("routing_no_candidate", message)
        self.verdicts = verdicts


# -------------------------------------------------------------------- candidats

#: Modèle laissé vide : « celui que le CLI choisit lui-même ». C'est le seul
#: moyen de rester juste quand l'utilisateur n'a pas d'avis, sans inventer un
#: identifiant qui périmerait.
DEFAULT_MODEL = ""


@dataclass(frozen=True, slots=True)
class CandidateRef:
    """Désignation stable d'un candidat, telle qu'elle est enregistrée."""

    agent: str
    model: str = DEFAULT_MODEL

    @property
    def key(self) -> str:
        return f"{self.agent}:{self.model}" if self.model else self.agent

    def as_dict(self) -> dict[str, str]:
        return {"agent": self.agent, "model": self.model}

    @classmethod
    def parse(cls, raw: object) -> "CandidateRef":
        """Lire une référence venue des réglages ou d'une requête HTTP.

        Un objet, jamais une chaîne « agent:modèle » : des identifiants de
        modèles contiennent déjà des deux-points et des barres obliques, et les
        recoller serait une source de bogues silencieux.
        """
        if not isinstance(raw, Mapping):
            raise RoutingError("routing_bad_candidate", "Un candidat doit être un objet {agent, model}.")
        agent = str(raw.get("agent") or "").strip().lower()
        if not agent:
            raise RoutingError("routing_bad_candidate", "Un candidat doit nommer son agent.")
        return cls(agent=agent, model=str(raw.get("model") or "").strip())


@dataclass(frozen=True, slots=True)
class AgentTarget:
    """Un CLI d'agent installé (ou pas), et ce qu'il sait faire."""

    id: str
    label: str
    capabilities: frozenset[str] = frozenset()
    available: bool = False
    unavailable_reason: str = ""


@dataclass(frozen=True, slots=True)
class ModelCandidate:
    """Un couple agent + modèle réellement proposable, et son état du moment.

    `available` est un fait mesuré à l'instant : clé absente, modèle retiré du
    service, CLI introuvable. Un candidat indisponible reste décrit — il ne
    disparaît pas des réglages — mais il ne peut pas être choisi.
    """

    agent: str
    model: str
    label: str = ""
    provider: str = ""
    capabilities: frozenset[str] = frozenset()
    available: bool = True
    unavailable_reason: str = ""

    @property
    def ref(self) -> CandidateRef:
        return CandidateRef(agent=self.agent, model=self.model)

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "model": self.model,
            "label": self.label or self.model or self.agent,
            "provider": self.provider,
            "capabilities": sorted(self.capabilities),
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
        }


# -------------------------------------------------------------------- politique


@dataclass(frozen=True, slots=True)
class ProfilePolicy:
    """Ce que l'utilisateur autorise pour un profil, dans son ordre de préférence.

    L'ordre *est* la préférence : le premier candidat éligible gagne. Aucun
    poids, aucun coût estimé — un chiffre inventé serait pire qu'un ordre
    assumé, et les fournisseurs ne publient pas de latence comparable.
    """

    profile: str
    candidates: tuple[CandidateRef, ...] = ()
    enabled: bool = True
    # Épuisée la liste du profil, tenter celle du profil général. Sans ça, un
    # profil trop étroit échoue en clair au lieu de partir ailleurs en douce.
    allow_general_fallback: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "enabled": self.enabled,
            "candidates": [ref.as_dict() for ref in self.candidates],
            "allow_general_fallback": self.allow_general_fallback,
        }


@dataclass(frozen=True, slots=True)
class RoutingPolicy:
    """La politique entière. Désactivée, rien ne change au comportement actuel."""

    enabled: bool = False
    profiles: tuple[ProfilePolicy, ...] = ()

    def for_profile(self, profile: str) -> ProfilePolicy | None:
        return next((entry for entry in self.profiles if entry.profile == profile), None)

    def as_dict(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "profiles": [entry.as_dict() for entry in self.profiles]}


#: Politique de départ : tout est décrit, rien n'est imposé. Tant qu'elle n'est
#: pas activée, le modèle configuré du CLI continue de servir, comme avant.
COMPATIBILITY_POLICY = RoutingPolicy(
    enabled=False,
    profiles=tuple(ProfilePolicy(profile=spec.id) for spec in TASK_PROFILES),
)


# ------------------------------------------------------------------- intention


@dataclass(frozen=True, slots=True)
class RoutingIntent:
    """Ce que le back-end demande : un besoin, pas un modèle.

    `override` existe pour l'utilisateur qui impose un candidat précis. Il est
    vérifié comme les autres : imposer n'est pas contourner.
    """

    profile: str
    requires: frozenset[str] = frozenset()
    override: CandidateRef | None = None
    # Trace lisible de l'origine de la demande (« brain », « self-dev »…).
    source: str = ""

    def required_capabilities(self) -> frozenset[str]:
        return frozenset(profile_spec(self.profile).requires) | self.requires


# ---------------------------------------------------------------------- verdict

#: Pourquoi un candidat a été écarté. Codes stables : ils sont journalisés et
#: affichés, jamais reformulés par un modèle.
REJECT_UNKNOWN = "unknown_candidate"
REJECT_AGENT_UNAVAILABLE = "agent_unavailable"
REJECT_MODEL_UNAVAILABLE = "model_unavailable"
REJECT_MISSING_CAPABILITY = "missing_capability"
REJECT_NOT_ALLOWED = "not_allowed"

#: Pourquoi le candidat retenu l'a été.
REASON_PREFERRED = "preferred"
REASON_FALLBACK = "fallback"
REASON_GENERAL_FALLBACK = "general_fallback"
REASON_OVERRIDE = "override"
REASON_COMPATIBILITY = "compatibility"


@dataclass(frozen=True, slots=True)
class CandidateVerdict:
    ref: CandidateRef
    eligible: bool
    code: str = ""
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {**self.ref.as_dict(), "eligible": self.eligible}
        if self.code:
            payload["code"] = self.code
        if self.detail:
            payload["detail"] = self.detail
        return payload


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """Le candidat retenu, et de quoi expliquer le choix sans raisonnement caché.

    `model` vide veut dire « laisser le CLI décider » : c'est le comportement de
    compatibilité, et c'est une réponse, pas une absence de réponse.
    """

    profile: str
    agent: str
    model: str
    reason: str
    considered: tuple[CandidateVerdict, ...] = ()
    # Renseigné quand le préféré n'a pas pu être pris : ce qu'on visait, et pourquoi.
    fallback_from: CandidateRef | None = None
    fallback_code: str = ""
    source: str = ""

    @property
    def ref(self) -> CandidateRef:
        return CandidateRef(agent=self.agent, model=self.model)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "profile": self.profile,
            "agent": self.agent,
            "model": self.model,
            "reason": self.reason,
            "considered": [verdict.as_dict() for verdict in self.considered],
        }
        if self.fallback_from is not None:
            payload["fallback_from"] = self.fallback_from.as_dict()
            payload["fallback_code"] = self.fallback_code
        if self.source:
            payload["source"] = self.source
        return payload


# --------------------------------------------------------------------- résolution


def _index(candidates: Iterable[ModelCandidate]) -> dict[tuple[str, str], ModelCandidate]:
    return {(item.agent, item.model): item for item in candidates}


def _judge(ref: CandidateRef, known: Mapping[tuple[str, str], ModelCandidate], required: frozenset[str]) -> CandidateVerdict:
    candidate = known.get((ref.agent, ref.model))
    if candidate is None:
        return CandidateVerdict(ref, False, REJECT_UNKNOWN, "Ce couple agent + modèle n'est pas proposé sur cette machine.")
    if not candidate.available:
        code = REJECT_AGENT_UNAVAILABLE if not ref.model else REJECT_MODEL_UNAVAILABLE
        return CandidateVerdict(ref, False, code, candidate.unavailable_reason)
    missing = sorted(required - candidate.capabilities)
    if missing:
        return CandidateVerdict(ref, False, REJECT_MISSING_CAPABILITY, ", ".join(missing))
    return CandidateVerdict(ref, True)


def _walk(
    refs: Iterable[CandidateRef],
    known: Mapping[tuple[str, str], ModelCandidate],
    required: frozenset[str],
    verdicts: list[CandidateVerdict],
) -> CandidateRef | None:
    """Premier candidat éligible de la liste, tous les verdicts consignés au passage."""
    chosen: CandidateRef | None = None
    for ref in refs:
        verdict = _judge(ref, known, required)
        verdicts.append(verdict)
        if verdict.eligible and chosen is None:
            chosen = ref
            break
    return chosen


def resolve(
    intent: RoutingIntent,
    policy: RoutingPolicy,
    candidates: Iterable[ModelCandidate],
) -> RoutingDecision:
    """Choisir le candidat concret d'une intention. Déterministe, sans I/O.

    Le premier candidat autorisé et utilisable gagne. À défaut, la liste du
    profil général si le profil l'autorise. À défaut encore, l'échec est
    explicite : jamais de modèle hors politique par dépannage.
    """
    profile = profile_spec(intent.profile).id
    required = intent.required_capabilities()
    known = _index(candidates)
    verdicts: list[CandidateVerdict] = []

    entry = policy.for_profile(profile)
    allowed = tuple(entry.candidates) if entry is not None else ()

    if intent.override is not None:
        override = intent.override
        if policy.enabled and entry is not None and entry.enabled and allowed and override not in allowed:
            verdicts.append(CandidateVerdict(override, False, REJECT_NOT_ALLOWED, f"Non autorisé pour le profil « {profile} »."))
            raise NoEligibleCandidateError(
                f"« {override.key} » n'est pas autorisé pour le profil {profile_spec(profile).label}.",
                tuple(verdicts),
            )
        verdict = _judge(override, known, required)
        verdicts.append(verdict)
        if not verdict.eligible:
            raise NoEligibleCandidateError(
                f"« {override.key} » ne peut pas être utilisé : {verdict.detail or verdict.code}.",
                tuple(verdicts),
            )
        return RoutingDecision(
            profile=profile,
            agent=override.agent,
            model=override.model,
            reason=REASON_OVERRIDE,
            considered=tuple(verdicts),
            source=intent.source,
        )

    if not policy.enabled or entry is None or not entry.enabled or not allowed:
        # Compatibilité : le modèle configuré du CLI reste maître, comme avant
        # l'existence des profils. Ce n'est pas un échec, c'est le défaut.
        return RoutingDecision(
            profile=profile,
            agent="",
            model=DEFAULT_MODEL,
            reason=REASON_COMPATIBILITY,
            considered=tuple(verdicts),
            source=intent.source,
        )

    chosen = _walk(allowed, known, required, verdicts)
    if chosen is not None:
        preferred = chosen == allowed[0]
        return RoutingDecision(
            profile=profile,
            agent=chosen.agent,
            model=chosen.model,
            reason=REASON_PREFERRED if preferred else REASON_FALLBACK,
            considered=tuple(verdicts),
            fallback_from=None if preferred else allowed[0],
            fallback_code="" if preferred else verdicts[0].code,
            source=intent.source,
        )

    if entry.allow_general_fallback and profile != GENERAL_PROFILE:
        general = policy.for_profile(GENERAL_PROFILE)
        if general is not None and general.enabled and general.candidates:
            chosen = _walk(general.candidates, known, required, verdicts)
            if chosen is not None:
                return RoutingDecision(
                    profile=profile,
                    agent=chosen.agent,
                    model=chosen.model,
                    reason=REASON_GENERAL_FALLBACK,
                    considered=tuple(verdicts),
                    fallback_from=allowed[0],
                    fallback_code=verdicts[0].code,
                    source=intent.source,
                )

    raise NoEligibleCandidateError(
        f"Aucun candidat autorisé n'est utilisable pour le profil {profile_spec(profile).label}.",
        tuple(verdicts),
    )


def describe_profiles() -> list[dict[str, Any]]:
    """Ce que l'interface affiche : les profils, sans aucun modèle écrit en dur."""
    return [
        {"id": spec.id, "label": spec.label, "description": spec.description, "requires": list(spec.requires)}
        for spec in TASK_PROFILES
    ]

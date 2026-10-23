"""Configuration d'un cerveau : tendance de délégation, codes de refus, consignes par niveau (docs/brain-config.md).

Module pur : aucune lecture de réglage, de fichier ni d'environnement. Le service
(`jarvis/runtime/brain_config.py`) assemble le descripteur de chaque cerveau à partir des réglages qui en sont
**propriétaires** ; ce module ne dit que le vocabulaire stable et ce que chaque niveau signifie.

Règle produit (handoff `jarvis-architecture-agents-settings-editor`) : *le graphe décide de ce qui peut parler à
quoi ; un cerveau décide quand il délègue ; la configuration globale des sous-agents décide quel agent ou modèle
exécute un rôle délégué.* La tendance de délégation est donc une politique du cerveau : elle ne choisit jamais le
modèle d'un rôle (`jarvis/domain/role_routing.py`).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

#: Identités des cerveaux : celles des nœuds du graphe (`jarvis/runtime/architecture_graph.py`), pas un second
#: registre. `luna` n'existe que dans l'architecture Front Brain.
BRAIN_IDS = ("voice", "luna", "core", "tool_brain")


class DelegationTendency(StrEnum):
    """Enum neutre, stable sur le fil ; les libellés français sont dans `DELEGATION_LABELS`."""

    NEVER = "never"
    RARE = "rare"
    STANDARD = "standard"
    PROACTIVE = "proactive"
    EXPLORATORY = "exploratory"


#: Le défaut : le comportement d'avant ce réglage, exactement (aucune migration n'écrit rien).
DEFAULT_DELEGATION = DelegationTendency.STANDARD

DELEGATION_LABELS: Mapping[DelegationTendency, tuple[str, str]] = {
    DelegationTendency.NEVER: ("Jamais", "Le cerveau ne lance aucun sous-agent : l'outil lui est retiré."),
    DelegationTendency.RARE: ("Rare", "Seulement pour un travail clairement long ou en plusieurs étapes."),
    DelegationTendency.STANDARD: ("Standard", "Comportement actuel : tout travail de plus de quelques secondes part en "
                                              "sous-agent ; dans le doute, il délègue."),
    DelegationTendency.PROACTIVE: ("Proactive", "Délègue dès qu'une demande dépasse une réponse immédiate."),
    DelegationTendency.EXPLORATORY: ("Exploratoire", "Délègue largement et répartit en parallèle les parties "
                                                     "indépendantes d'un travail."),
}

#: La phrase de `claude_local.BRAIN_SYSTEM_PROMPT` que la tendance remplace. `standard` la garde telle quelle :
#: le prompt est alors identique, octet pour octet, à celui d'avant ce réglage.
STANDARD_DELEGATION_SENTENCE = "Dans le doute, délègue."

#: Consigne qui remplace `STANDARD_DELEGATION_SENTENCE`, par niveau. Elle prolonge la règle « RESTE DISPONIBLE,
#: DÉLÈGUE LE TRAVAIL » : la phrase finale d'une règle est celle que le modèle retient comme arbitrage.
DELEGATION_RULES: Mapping[DelegationTendency, str] = {
    DelegationTendency.NEVER: (
        "Réglage de l'utilisateur : tu ne délègues jamais. L'outil Agent t'est retiré et tout appel serait refusé : "
        "ce qui précède sur les sous-agents ne s'applique pas. Fais toi-même ce qui tient en un tour court, et dis "
        "franchement ce qui demanderait un sous-agent au lieu de le promettre."
    ),
    DelegationTendency.RARE: (
        "Réglage de l'utilisateur : délégation rare. Ne lance un sous-agent que pour un travail clairement long ou en "
        "plusieurs étapes ; dans le doute, réponds toi-même, brièvement."
    ),
    DelegationTendency.STANDARD: STANDARD_DELEGATION_SENTENCE,
    DelegationTendency.PROACTIVE: (
        "Réglage de l'utilisateur : délégation proactive. Délègue dès qu'une demande dépasse une réponse immédiate, "
        "sans attendre qu'elle paraisse longue ; dans le doute, délègue."
    ),
    DelegationTendency.EXPLORATORY: (
        "Réglage de l'utilisateur : délégation exploratoire. Délègue largement : quand un travail a des parties "
        "indépendantes (recherches, vérifications, alternatives), lance-les en sous-agents parallèles, dans la borne "
        "de sûreté de JARVIS ; dans le doute, délègue."
    ),
}


def delegation_rule(level: DelegationTendency) -> str:
    return DELEGATION_RULES[level]


def apply_delegation_rule(prompt: str, level: DelegationTendency) -> str:
    """`prompt` où la phrase de délégation standard est remplacée par la consigne du niveau.

    La phrase doit y figurer **exactement une fois** : un prompt réécrit sans elle ferait perdre la tendance en
    silence, ce que ce garde refuse (le test du catalogue le prouve à chaque modification du prompt).
    """

    if prompt.count(STANDARD_DELEGATION_SENTENCE) != 1:
        raise ValueError("the brain prompt must contain the standard delegation sentence exactly once")
    if level is DelegationTendency.STANDARD:
        return prompt
    return prompt.replace(STANDARD_DELEGATION_SENTENCE, DELEGATION_RULES[level], 1)


def parse_delegation(raw: object) -> DelegationTendency:
    """Lecture **stricte** : une valeur inconnue est refusée, jamais ramenée en silence à un autre niveau."""

    if isinstance(raw, str):
        try:
            return DelegationTendency(raw)
        except ValueError:
            pass
    raise BrainConfigError(DELEGATION_INVALID, "Tendance de délégation inconnue : attendu "
                           + ", ".join(level.value for level in DelegationTendency) + ".")


def delegation_choices() -> list[dict[str, str]]:
    return [{"value": level.value, "label": DELEGATION_LABELS[level][0], "description": DELEGATION_LABELS[level][1]}
            for level in DelegationTendency]


# ------------------------------------------------------------------ codes de refus

UNKNOWN_BRAIN = "brain_config_unknown_brain"
BRAIN_ABSENT = "brain_config_brain_absent"
REVISION_STALE = "brain_config_revision_stale"
REQUEST_INVALID = "brain_config_request_invalid"
FIELD_UNSUPPORTED = "brain_config_field_unsupported"
FIELD_LOCKED = "brain_config_field_locked"
DELEGATION_INVALID = "brain_config_delegation_invalid"
MODEL_UNAVAILABLE = "brain_config_model_unavailable"
CATALOG_UNAVAILABLE = "brain_config_catalog_unavailable"
ACTIVATION_INVALID = "brain_config_activation_invalid"
STORE_UNREADABLE = "brain_config_store_unreadable"
WRITE_FAILED = "brain_config_write_failed"
SNAPSHOT_FAILED = "brain_config_snapshot_failed"
#: Refus du mécanisme des surcharges de prompt, relayés tels quels (`prompt_overrides.PromptOverrideStore`).
PROMPT_STALE = "prompt_override_stale"
PROMPT_CONCURRENT = "prompt_override_concurrent"

ERROR_STATUS: Mapping[str, int] = {
    UNKNOWN_BRAIN: 404, BRAIN_ABSENT: 409,
    REVISION_STALE: 409, PROMPT_STALE: 409, PROMPT_CONCURRENT: 409,
    REQUEST_INVALID: 400,
    FIELD_UNSUPPORTED: 422, DELEGATION_INVALID: 422, MODEL_UNAVAILABLE: 422, ACTIVATION_INVALID: 422,
    FIELD_LOCKED: 423,
    CATALOG_UNAVAILABLE: 503,
    STORE_UNREADABLE: 500, WRITE_FAILED: 500, SNAPSHOT_FAILED: 500,
}


class BrainConfigError(Exception):
    """Refus d'une lecture ou d'une écriture de configuration : code stable, raison en français, statut HTTP."""

    def __init__(self, code: str, reason: str, *, field: str | None = None) -> None:
        super().__init__(reason)
        self.code, self.reason, self.field = code, reason, field
        self.status = ERROR_STATUS.get(code, 422)


# ------------------------------------------------------------------ mission (lecture seule)

#: Responsabilités de chaque cerveau, **fournies par le code** : aucune persistance canonique de mission n'existe
#: pour un cerveau (seuls les rôles de sous-agent en ont une, `subagent_roles`). Le texte décrit le runtime réel.
BRAIN_MISSIONS: Mapping[str, str] = {
    "voice": ("Porte la conversation audio en direct : écoute le micro, répond à voix haute, garde la parole "
              "courte, et confie au cerveau Core ce qui demande des outils, du travail ou de la mémoire."),
    "luna": ("Front Brain : analyse les transcriptions pendant que la voix parle et lui souffle des indications "
             "(contexte, prudence, relance). Ne parle pas et n'exécute rien."),
    "core": ("Cerveau Core : aiguille chaque demande, répond lui-même quand c'est immédiat, lance les sous-agents "
             "pour le travail, tient les Boards, la mémoire et les outils, et fait dire les résultats par la voix."),
    "tool_brain": ("Tool Brain : décide de ce que l'écran montre (scène, Boards) pendant la conversation, à partir "
                   "des intentions d'interface de Jarvis. Ne parle pas et ne lance aucun sous-agent."),
}

"""Validated Agent/CLI response preferences and model-visible instruction."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any


SETTING_KEY = "agent_behavior"
INHERIT = "inherit"


class AgentBehaviorError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class AgentBehaviorSettings:
    response_verbosity: str = INHERIT
    politeness_formality: str = INHERIT

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


VERBOSITY_OPTIONS = (
    (INHERIT, "Hériter"),
    ("concise", "Concise"),
    ("balanced", "Équilibrée"),
    ("detailed", "Détaillée"),
)
POLITENESS_OPTIONS = (
    (INHERIT, "Hériter"),
    ("direct", "Direct"),
    ("courteous", "Courtois"),
    ("formal", "Formel"),
)

_VERBOSITY_INSTRUCTIONS = {
    "concise": "Réponds de façon concise : va directement à l'essentiel sans omettre les informations nécessaires.",
    "balanced": "Réponds avec un niveau de détail équilibré : explique les points utiles sans développement superflu.",
    "detailed": "Réponds de façon détaillée : développe le raisonnement utile, les étapes et les limites pertinentes.",
}
_POLITENESS_INSTRUCTIONS = {
    "direct": "Adopte un ton direct et sobre, sans formules de politesse superflues.",
    "courteous": "Adopte un ton courtois et naturel.",
    "formal": "Adopte un ton formel et professionnel.",
}


def _tolerant_value(raw: object, options: tuple[tuple[str, str], ...]) -> str:
    allowed = {identifier for identifier, _label in options}
    return raw if isinstance(raw, str) and raw in allowed else INHERIT


def load(settings: Mapping[str, Any]) -> AgentBehaviorSettings:
    """Project missing or damaged saved values to safe inheritance defaults."""
    stored = settings.get(SETTING_KEY)
    stored = stored if isinstance(stored, Mapping) else {}
    return AgentBehaviorSettings(
        response_verbosity=_tolerant_value(stored.get("response_verbosity"), VERBOSITY_OPTIONS),
        politeness_formality=_tolerant_value(stored.get("politeness_formality"), POLITENESS_OPTIONS),
    )


def _strict_value(raw: object, *, options: tuple[tuple[str, str], ...], code: str, label: str) -> str:
    allowed = {identifier for identifier, _label in options}
    if not isinstance(raw, str) or raw not in allowed:
        raise AgentBehaviorError(code, f"Valeur inconnue pour {label}.")
    return raw


def apply(settings: dict[str, Any], payload: Mapping[str, Any]) -> AgentBehaviorSettings:
    """Validate the whole patch before storing its canonical two-field block."""
    if not isinstance(payload, Mapping):
        raise AgentBehaviorError("agent_settings_invalid_behavior", "Le comportement doit être un objet.")
    unknown = set(payload) - {"response_verbosity", "politeness_formality"}
    if unknown:
        raise AgentBehaviorError("agent_settings_invalid_behavior", "Le comportement contient un champ inconnu.")

    current = load(settings)
    verbosity = current.response_verbosity
    formality = current.politeness_formality
    if "response_verbosity" in payload:
        verbosity = _strict_value(
            payload["response_verbosity"], options=VERBOSITY_OPTIONS,
            code="agent_settings_invalid_verbosity", label="la verbosité",
        )
    if "politeness_formality" in payload:
        formality = _strict_value(
            payload["politeness_formality"], options=POLITENESS_OPTIONS,
            code="agent_settings_invalid_politeness_formality", label="la politesse / formalité",
        )
    result = AgentBehaviorSettings(verbosity, formality)
    settings[SETTING_KEY] = result.as_dict()
    return result


def prompt_instruction(settings: Mapping[str, Any]) -> str:
    """Return no bytes for inheritance, otherwise one bounded central instruction."""
    behavior = load(settings)
    lines = []
    if behavior.response_verbosity != INHERIT:
        lines.append(_VERBOSITY_INSTRUCTIONS[behavior.response_verbosity])
    if behavior.politeness_formality != INHERIT:
        lines.append(_POLITENESS_INSTRUCTIONS[behavior.politeness_formality])
    if not lines:
        return ""
    return "[Préférences de réponse JARVIS]\n" + "\n".join(f"- {line}" for line in lines)


def describe(settings: Mapping[str, Any]) -> dict[str, Any]:
    behavior = load(settings)
    return {
        "values": behavior.as_dict(),
        "fields": [
            {
                "id": "response_verbosity", "label": "Verbosité", "type": "enum",
                "default": INHERIT, "help": "Hériter n'ajoute aucune consigne.",
                "destination": "agent_cli.behavior", "advanced": False, "runtime_status": "live",
                "options": [{"id": identifier, "label": label} for identifier, label in VERBOSITY_OPTIONS],
            },
            {
                "id": "politeness_formality", "label": "Politesse / formalité", "type": "enum",
                "default": INHERIT, "help": "Hériter n'ajoute aucune consigne.",
                "destination": "agent_cli.behavior", "advanced": False, "runtime_status": "live",
                "options": [{"id": identifier, "label": label} for identifier, label in POLITENESS_OPTIONS],
            },
        ],
    }

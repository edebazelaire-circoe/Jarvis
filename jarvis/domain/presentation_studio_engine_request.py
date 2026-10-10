"""Demande de création d'une Presentation : qui peut nommer un moteur (handoff jarvis-remotion-presentation-integration, Slice 20).

`docs/presentation-engine.md` > *Human engine control*. Le corps de `POST /v1/presentation-studio/presentations` a deux formes :

- `{title}` : la forme de l'agent et de tout script. Aucun moteur nommé, donc `remotion` (le défaut forcé).
- `{title, engine, actor, experimental_confirmed?, reason?}` : la forme de la page de l'utilisateur. Le relais du Control Center
  (`presentation_studio_relay.py`) pose `actor: "user"` côté serveur, quoi que la page dise. `actor` est une **déclaration**, pas
  une authentification (même limite de menace que `display_mcp.py` : le cerveau tourne sous le même compte que Core). La garantie
  est : aucun outil du cerveau ne porte de moteur ni d'acteur (test de parité), le serveur MCP envoie `brain`, et Core refuse tout
  moteur nommé par un autre acteur que `user`.

Ce module ne choisit rien : il traduit le corps en `(moteur demandé, acteur)` pour `EngineSelectionPolicy.select`, qui reste la
seule autorité. Un moteur nommé sans acteur est refusé comme venant d'un agent (fermé par défaut).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jarvis.domain.presentation_studio_checks import MAX_TITLE, PresentationStudioError, _C, _check_title, _exact_keys, _fail
from jarvis.domain.presentation_studio_engine import Engine, EngineActor

#: Valeur de `actor` -> acteur de la politique. `user` est la page de l'utilisateur (relais du Control Center), `brain` le cerveau.
ACTORS: dict[str, EngineActor] = {"user": EngineActor.HUMAN, "brain": EngineActor.AGENT, "system": EngineActor.SYSTEM}
MAX_REASON = 160
#: Raison inscrite quand l'utilisateur n'en a pas saisi : le geste lui-même est la raison, jamais vide.
DEFAULT_REASON = "expérience demandée par l'utilisateur dans le Control Center"
SLIDECAR_WARNING = (
    "Slidecar est un moteur expérimental : pas de séquence image par image, pas d'export MP4. Une présentation Slidecar reste "
    "Slidecar (le moteur ne change jamais après la création). Aucun repli : si Remotion tombe en panne, rien ne joue à sa place.")


@dataclass(frozen=True, slots=True)
class CreateRequest:
    title: str
    #: Ce que l'appelant a NOMMÉ (`None` = rien). Jamais le moteur final : c'est `POLICY.select` qui le décide.
    requested: str | None
    actor: EngineActor
    confirmed: bool
    reason: str


def parse_create_request(raw: object) -> CreateRequest:
    data = _exact_keys(raw, "create", {"title"}, frozenset({"engine", "actor", "experimental_confirmed", "reason"}))
    _check_title("title", data["title"])
    requested = data.get("engine")
    if requested is not None and not isinstance(requested, str):
        raise _fail("engine must be a string")
    actor_name = data.get("actor", "brain")
    if not isinstance(actor_name, str) or actor_name not in ACTORS:
        raise PresentationStudioError(_C.ENGINE_SELECTION_REFUSED, f"unknown actor {str(actor_name)[:40]!r}: no engine choice")
    confirmed = data.get("experimental_confirmed", False)
    if type(confirmed) is not bool:
        raise _fail("experimental_confirmed must be a boolean")
    reason = data.get("reason", "")
    if not isinstance(reason, str) or len(reason) > MAX_REASON or not reason.isprintable():
        raise _fail(f"reason must be a single printable line of at most {MAX_REASON} characters")
    return CreateRequest(data["title"], requested, ACTORS[actor_name], confirmed, reason.strip() or DEFAULT_REASON)


def require_slidecar_confirmation(engine: Engine, request: CreateRequest) -> None:
    """Slidecar n'est jamais créé sans la confirmation explicite de l'utilisateur (l'avertissement lu), même par une personne."""

    if engine is Engine.SLIDECAR and not request.confirmed:
        raise PresentationStudioError(
            _C.INVALID_PRESENTATION,
            "slidecar is experimental: the creation must carry experimental_confirmed=true after the warning was read. "
            + SLIDECAR_WARNING)


def experiment_title(source_title: str) -> str:
    """Titre de la copie « expérience Slidecar » : celui de la source, borné, jamais vide ni identique."""

    suffix = " (Slidecar)"
    base = source_title[: MAX_TITLE - len(suffix)].rstrip()
    return f"{base}{suffix}"


def event_data(request: CreateRequest, engine: Engine, **extra: Any) -> dict[str, Any]:
    return {"engine": engine.value, "actor": "human", "reason": request.reason, **extra}

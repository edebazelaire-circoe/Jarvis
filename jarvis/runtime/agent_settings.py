"""Shared, side-effect-free CLI settings resolution for UI and owned jobs.

Édition produit (`docs/product-capabilities.md`, Slice 04) : en édition confinée (`presentation`), le
CLI effectif est un CLI permis par le manifeste (Codex retombe sur Claude) et le mode de permission
est celui du manifeste (`dontAsk`), quel que soit le réglage enregistré. L'interface l'affiche,
elle ne l'élargit pas ; le lancement (`claude_local.ClaudeLocalAgent.start`) l'impose de toute façon.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping

from jarvis.runtime import cli_catalog


def edition_capabilities(environ: Mapping[str, str] | None = None):  # noqa: ANN201 - AgentCapabilityPolicy
    """Manifeste de capacités des agents de l'édition de ce processus (`process_edition`)."""

    from jarvis.domain.agent_capabilities import agent_capability_policy
    from jarvis.runtime.product_edition_env import process_edition
    return agent_capability_policy(process_edition(environ))


def effective_agent_cli(value: object, *, environ: Mapping[str, str] | None = None) -> str:
    """Le CLI réglé, ou le premier CLI permis par l'édition quand le réglage en nomme un fermé (Codex en presentation)."""

    agent_id = cli_catalog.normalize_agent_cli(value)
    capabilities = edition_capabilities(environ)
    return agent_id if capabilities.allows_agent_cli(agent_id) else capabilities.agent_clis[0]


def agent_defaults(agent_id: str, *, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    env = os.environ if environ is None else environ
    spec = cli_catalog.spec_for(agent_id)
    if agent_id == "codex":
        return {"command": spec.default_command, "model": "", "permission_mode": "danger-full-access"}
    return {
        "command": env.get("JARVIS_CLAUDE_CLI", spec.default_command),
        "model": env.get("JARVIS_CLAUDE_MODEL", ""),
        "permission_mode": env.get("JARVIS_CLAUDE_PERMISSION_MODE", "bypassPermissions"),
    }


def resolve_agent_settings(settings: Mapping[str, object], agent_id: str, *,
                           environ: Mapping[str, str] | None = None, edition_lock: bool = True) -> dict[str, str]:
    """Réglages effectifs d'un CLI. `edition_lock=False` : la valeur **enregistrée**, sans le verrou de l'édition
    (seulement pour réécrire les champs hérités : un fichier de réglages ne doit pas garder `dontAsk` en souvenir)."""
    values = agent_defaults(agent_id, environ=environ)
    if agent_id == "claude":
        for old, new in (("claude_cli", "command"), ("claude_permission_mode", "permission_mode")):
            if settings.get(old):
                values[new] = str(settings[old])
    stored = settings.get("agent_cli_settings")
    saved = stored.get(agent_id) if isinstance(stored, dict) else None
    if isinstance(saved, dict):
        values.update({key: saved[key] for key in values if key in saved and saved[key] is not None})
    spec = cli_catalog.spec_for(agent_id)
    values["command"] = str(values.get("command") or spec.default_command)
    values["model"] = str(values.get("model") or "")
    permission = str(values.get("permission_mode") or "").strip()
    values["permission_mode"] = permission if permission in spec.permission_modes else (
        "danger-full-access" if agent_id == "codex" else "bypassPermissions")
    locked = edition_capabilities(environ).permission_mode if edition_lock else None
    if locked is not None and agent_id == "claude":
        values["permission_mode"] = locked
    return values


@dataclass(frozen=True, slots=True)
class AgentExecutionSettings:
    agent_cli: str
    provider: str
    command: str
    model: str
    permission_mode: str
    cwd: Path
    runtime_root: Path
    prompt_overrides: dict | None = None
    behavior_active: bool = False


def resolve_agent_execution(settings: Mapping[str, object], *, cwd: Path, runtime_root: Path,
                            environ: Mapping[str, str] | None = None) -> AgentExecutionSettings:
    from jarvis.runtime.agent_behavior import prompt_instruction
    from jarvis.runtime.prompt_overrides import prompt_override_document
    agent_id = effective_agent_cli(settings.get("agent_cli"), environ=environ)
    values = resolve_agent_settings(settings, agent_id, environ=environ)
    return AgentExecutionSettings(agent_id, cli_catalog.spec_for(agent_id).model_provider,
                                  **values, cwd=Path(cwd), runtime_root=Path(runtime_root),
                                  prompt_overrides=prompt_override_document(dict(settings)),
                                  behavior_active=bool(prompt_instruction(settings)))

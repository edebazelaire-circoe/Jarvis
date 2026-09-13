"""Shared, side-effect-free CLI settings resolution for UI and owned jobs."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping

from jarvis.runtime import cli_catalog


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
                           environ: Mapping[str, str] | None = None) -> dict[str, str]:
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


def resolve_agent_execution(settings: Mapping[str, object], *, cwd: Path, runtime_root: Path,
                            environ: Mapping[str, str] | None = None) -> AgentExecutionSettings:
    from jarvis.runtime.prompt_overrides import prompt_override_document
    agent_id = cli_catalog.normalize_agent_cli(settings.get("agent_cli"))
    values = resolve_agent_settings(settings, agent_id, environ=environ)
    return AgentExecutionSettings(agent_id, cli_catalog.spec_for(agent_id).model_provider,
                                  **values, cwd=Path(cwd), runtime_root=Path(runtime_root),
                                  prompt_overrides=prompt_override_document(dict(settings)))

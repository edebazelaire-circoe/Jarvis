"""Resolve registry programs for production send sites without exposing text in telemetry."""
from __future__ import annotations

from copy import deepcopy
import inspect
from typing import Mapping

from jarvis.domain.prompt_registry import PromptError, PromptResolution, PromptTarget, decode_prompt_overrides


def normalize_prompt_overrides(value: object | None) -> dict | None:
    """Validate and detach the narrow override envelope used by a runtime owner."""
    if value is None:
        return None
    entries = decode_prompt_overrides(value)
    return {"schema_version": 1, "overrides": entries}


def resolve_prompt(target: PromptTarget, *, overrides: object | None = None,
                   variables: Mapping[str, object] | None = None) -> PromptResolution:
    # Lazy import avoids cycles: the catalog describes the same adapters that
    # call this helper at send time.
    from jarvis.runtime.prompt_catalog import default_prompt_registry

    return default_prompt_registry().resolve(
        target,
        overrides=normalize_prompt_overrides(overrides),
        variables=variables,
    )


def prompt_channel(resolution: PromptResolution, channel: str) -> str:
    matches = [item for item in resolution.channels if item.get("channel") == channel]
    if len(matches) != 1 or not isinstance(matches[0].get("text"), str):
        raise PromptError("prompt_channel_unresolved", f"Prompt channel {channel} is not fully resolved")
    return str(matches[0]["text"])


def prompt_evidence(resolution: PromptResolution, *, application: str,
                    channel: str | None = None) -> dict[str, object]:
    """Return bounded prompt identity only; raw model-visible text is excluded."""
    if application not in {"saved", "sent", "acknowledged", "unknown"}:
        raise ValueError("unknown prompt application state")
    return {
        "program_id": resolution.program_id,
        "prompt_ids": [str(item["prompt_id"]) for item in resolution.layers],
        "layer_revisions": [str(item["effective_revision"]) for item in resolution.layers],
        "static_fingerprint": resolution.static_fingerprint,
        "render_fingerprint": resolution.render_fingerprint,
        "channel": channel,
        "application": application,
    }


def compose_agent_turn(
    *,
    agent_id: str,
    model: str | None,
    request_text: str,
    overrides: object | None,
    behavior_active: bool,
    context: Mapping[str, object] | None = None,
) -> tuple[str, dict[str, object] | None]:
    """Compose every Agent send path once while preserving inherited bytes."""
    if context is None and not behavior_active:
        return request_text, None
    resolution = resolve_prompt(
        PromptTarget("backend", None, agent_id, model, None, "turn"),
        overrides=overrides,
        variables={"context": dict(context or {}), "request_text": request_text},
    )
    channel = "stdin.user_message"
    return (
        prompt_channel(resolution, channel),
        prompt_evidence(resolution, application="sent", channel=channel),
    )


def accepts_prompt_evidence(callback: object) -> bool:
    """Feature-detect new Agent API while retaining legacy test/plugin agents."""
    try:
        parameters = inspect.signature(callback).parameters.values()  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return any(
        parameter.name == "prompt_evidence" or parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )


def copy_prompt_evidence(value: Mapping[str, object]) -> dict[str, object]:
    return deepcopy(dict(value))

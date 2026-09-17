"""Narrow override mutations through the existing atomic settings writer.

No provider/session operations live here. A successful save is never an ACK.
"""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from threading import RLock

from jarvis.domain.prompt_registry import (
    MAX_OVERRIDE_TEXT, PromptError, PromptRegistry, _text, decode_prompt_overrides,
    fingerprint, prompt_id, validate_template,
)
from jarvis.runtime.agent_behavior import AgentBehaviorError

PROMPT_OVERRIDES_SETTING = "prompt_overrides"


def stored_prompt_override_document(settings: dict) -> dict | None:
    """Return only user-persisted prompt edits for the Prompts workbench."""
    if not isinstance(settings, dict):
        raise PromptError("prompt_settings_invalid", "Settings must be an object")
    if PROMPT_OVERRIDES_SETTING not in settings:
        return None
    entries = decode_prompt_overrides(settings[PROMPT_OVERRIDES_SETTING])
    return {"schema_version": 1, "overrides": entries}


def prompt_override_document(settings: dict) -> dict | None:
    """Return detached effective overrides, including Agent behavior at runtime.

    Inheritance takes the original byte-for-byte path. Non-inherited response
    preferences extend the shared backend-turn layer without changing the
    persisted prompt override document.
    """
    stored_document = stored_prompt_override_document(settings)
    entries = stored_document["overrides"] if stored_document is not None else {}

    from jarvis.runtime.agent_behavior import prompt_instruction
    behavior = prompt_instruction(settings)
    if not behavior:
        return stored_document

    from jarvis.runtime.prompt_catalog import default_prompt_registry
    registry = default_prompt_registry()
    descriptor = registry.require("backend.turn.addition")
    inspected = registry.inspect({"schema_version": 1, "overrides": entries})
    layer = next(item for item in inspected["layers"] if item["prompt_id"] == descriptor.prompt_id)
    current_text = layer["current_text"]
    combined = current_text + ("\n" if current_text else "") + behavior
    try:
        _text(combined, MAX_OVERRIDE_TEXT)
    except PromptError as exc:
        raise AgentBehaviorError(
            "agent_settings_behavior_prompt_too_large",
            f"Les préférences de réponse et l'ajout de tour dépassent {MAX_OVERRIDE_TEXT} caractères.",
        ) from exc
    entries[descriptor.prompt_id] = {"base_revision": descriptor.default_revision, "text": combined}
    return {"schema_version": 1, "overrides": entries}


class PromptOverrideStore:
    def __init__(self, registry: PromptRegistry, *, read_settings: Callable[[], dict],
                 write_settings: Callable[[dict], None], diagnostics=None):
        self.registry = registry
        self._read = read_settings
        self._write = write_settings
        self._diagnostics = diagnostics
        self._lock = RLock()

    def _load(self) -> tuple[dict, dict]:
        settings = self._read()
        if not isinstance(settings, dict):
            raise PromptError("prompt_settings_invalid", "Settings must be an object")
        settings = deepcopy(settings)
        entries = decode_prompt_overrides(settings[PROMPT_OVERRIDES_SETTING]) if PROMPT_OVERRIDES_SETTING in settings else {}
        return settings, entries

    def inspect(self) -> dict:
        with self._lock:
            _, entries = self._load()
            return self.registry.inspect({"schema_version": 1, "overrides": entries})

    def edit(self, identifier: str, *, text: str, base_revision: str,
             expected_effective_revision: str | None = None) -> dict:
        with self._lock:
            try:
                descriptor = self.registry.require(identifier)
                if not descriptor.editable:
                    raise PromptError("prompt_read_only", "This prompt layer cannot be edited")
                if base_revision != descriptor.default_revision:
                    raise PromptError("prompt_override_stale", "Prompt default changed; review its current revision before editing")
                _text(text, MAX_OVERRIDE_TEXT)
                validate_template(text, descriptor.variables + tuple(name for name, _ in descriptor.dependencies))
                settings, entries = self._load()
                if expected_effective_revision is not None:
                    inspected = next(item for item in self.registry.inspect(
                        {"schema_version": 1, "overrides": entries})["layers"]
                                     if item["prompt_id"] == identifier)
                    if expected_effective_revision != inspected["effective_revision"]:
                        raise PromptError("prompt_override_concurrent", "Prompt override changed; refresh before saving")
                if text == descriptor.default_text:
                    entries.pop(identifier, None)
                else:
                    entries[identifier] = {"base_revision": base_revision, "text": text}
                return self._persist(settings, entries, identifier, "edit")
            except (PromptError, AgentBehaviorError) as exc:
                self._emit("prompt.override.rejected", code=exc.code, level="warning")
                raise

    def reset(self, identifier: str) -> dict:
        with self._lock:
            try:
                prompt_id(identifier)
                settings, entries = self._load()
                # Unknown future IDs can be explicitly removed, never executed.
                entries.pop(identifier, None)
                return self._persist(settings, entries, identifier, "reset")
            except (PromptError, AgentBehaviorError) as exc:
                self._emit("prompt.override.rejected", code=exc.code, level="warning")
                raise

    def _persist(self, settings: dict, entries: dict, identifier: str, action: str) -> dict:
        envelope = {"schema_version": 1, "overrides": entries}
        decode_prompt_overrides(envelope)
        before = settings.get(PROMPT_OVERRIDES_SETTING)
        if entries:
            settings[PROMPT_OVERRIDES_SETTING] = envelope
        else:
            settings.pop(PROMPT_OVERRIDES_SETTING, None)
        # Behavior extends backend.turn.addition only at runtime. Prove the
        # combined bound before the atomic writer sees this candidate state.
        prompt_override_document(settings)
        changed = before != settings.get(PROMPT_OVERRIDES_SETTING)
        revision = fingerprint(envelope)
        if changed:
            try:
                self._write(settings)
            except Exception:
                # Writer owns atomic replacement; no save/sent success is emitted.
                self._emit("prompt.override.write_failed", code="prompt_write_failed", level="error")
                raise
        self._emit("prompt.override.saved" if changed else "prompt.override.unchanged",
                   code=f"prompt_{action}", identifier=identifier, revision=revision)
        return {"schema_version": 1, "changed": changed, "fingerprint": revision,
                "application": "saved_only", "document": deepcopy(envelope),
                "overrides": deepcopy(entries)}

    def _emit(self, channel: str, *, code: str, level: str = "info",
              identifier: str | None = None, revision: str | None = None) -> None:
        if self._diagnostics is not None:
            self._diagnostics.emit(channel, "Prompt override state updated", level=level,
                                   data={"code": code, "prompt_id": identifier, "fingerprint": revision})

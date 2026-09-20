"""Versioned voice selection codec and non-mutating compatibility migration."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass
import os
import math

from jarvis.domain.voice_architecture import (
    DuplexVoiceConfig, FrontBrainVoiceConfig, SimpleVoiceConfig, VoiceArchitectureId,
    VoiceConfigError, VoiceModeConfig, VoiceModelRef,
)
from jarvis.runtime.voice_capabilities import VoiceCapabilityRegistry, default_voice_registry
from jarvis.runtime.voice_stack import settings_for, stack_spec
from jarvis.ports.v2 import DiagnosticSink
from jarvis.v2_config import parse_voice_arch, recommended_realtime_model

VOICE_ARCHITECTURE_SETTING = "voice_architecture"
SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class LegacyVoiceCompatibility:
    execution_mode: str
    architecture_source: str
    stack_id: str
    model_source: str
    stack_settings: dict[str, object]
    stack_source: str = "default"

    def to_dict(self) -> dict[str, object]:
        return deepcopy(asdict(self))


@dataclass(frozen=True, slots=True)
class VoiceArchitectureSettings:
    config: VoiceModeConfig
    compatibility: LegacyVoiceCompatibility | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise VoiceConfigError("voice_schema_version_unsupported", "Voice schema_version must be integer 1")
        if not isinstance(self.config, (SimpleVoiceConfig, FrontBrainVoiceConfig, DuplexVoiceConfig)):
            raise VoiceConfigError("voice_config_invalid", "Expected a typed voice configuration")
        if self.compatibility is not None and not isinstance(self.compatibility, LegacyVoiceCompatibility):
            raise VoiceConfigError("voice_compatibility_invalid", "Invalid compatibility metadata")

    @property
    def uses_compatibility_runtime(self) -> bool:
        return self.compatibility is not None

    def to_dict(self) -> dict[str, object]:
        config = asdict(self.config)
        config["architecture"] = self.config.architecture.value
        return {"schema_version": self.schema_version, "config": config,
                "compatibility": self.compatibility.to_dict() if self.compatibility else None}


def _object(raw: object, *, allowed: set[str], name: str) -> dict[str, object]:
    if not isinstance(raw, dict) or any(not isinstance(key, str) for key in raw):
        raise VoiceConfigError("voice_schema_invalid", f"{name} must be an object")
    if set(raw) - allowed:
        raise VoiceConfigError("voice_schema_unknown_field", f"Unknown fields in {name}: {', '.join(sorted(set(raw) - allowed))}")
    return raw


def _ref(raw: object) -> VoiceModelRef:
    values = _object(raw, allowed={"provider_id", "model_id"}, name="model")
    if set(values) != {"provider_id", "model_id"}:
        raise VoiceConfigError("voice_model_invalid", "Model requires provider_id and model_id")
    return VoiceModelRef(values["provider_id"], values["model_id"])  # type: ignore[arg-type]


def _safe_stack_options(stack_id: str, raw: object) -> dict[str, object]:
    spec = stack_spec(stack_id)
    options = _object(raw, allowed={field.key for field in spec.fields}, name="compatibility stack_settings")
    for field in spec.fields:
        if field.key not in options:
            continue
        value = options[field.key]
        valid = (type(value) is bool if field.kind == "toggle" else
                 isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
                 if field.kind == "number" else isinstance(value, str))
        if not valid:
            raise VoiceConfigError("voice_compatibility_setting_invalid", f"Invalid value type for legacy voice field {field.key}")
    return deepcopy(options)


def parse_voice_mode(raw: object, registry: VoiceCapabilityRegistry, *, validate_models: bool = True) -> VoiceModeConfig:
    if not isinstance(raw, dict):
        raise VoiceConfigError("voice_schema_invalid", "Voice config must be an object")
    try:
        mode = VoiceArchitectureId(raw.get("architecture"))
    except (ValueError, TypeError) as exc:
        raise VoiceConfigError("voice_architecture_unknown", "Choose simple, front_brain or duplex") from exc
    if mode is VoiceArchitectureId.SIMPLE:
        values = _object(raw, allowed={"architecture", "conversation_model"}, name="Simple config")
        config: VoiceModeConfig = SimpleVoiceConfig(_ref(values.get("conversation_model")))
    elif mode is VoiceArchitectureId.FRONT_BRAIN:
        values = _object(raw, allowed={"architecture", "reflex_model", "analysis_model", "speculative_deltas", "reasoning_effort"}, name="Front Brain config")
        config = FrontBrainVoiceConfig(_ref(values.get("reflex_model")), _ref(values.get("analysis_model")),
                                       values.get("speculative_deltas", True), values.get("reasoning_effort", "low"))  # type: ignore[arg-type]
    else:
        values = _object(raw, allowed={"architecture", "conversation_model", "client_delegation", "idle_timeout_s",
                                       "brain_orchestration"}, name="Duplex config")
        # Champ absent = orchestration cerveau active : les réglages écrits
        # avant ce champ restent lisibles sans migration ni bump de schéma.
        config = DuplexVoiceConfig(_ref(values.get("conversation_model")), values.get("client_delegation", True),
                                   values.get("idle_timeout_s", 60.0),
                                   values.get("brain_orchestration", True))  # type: ignore[arg-type]
    if validate_models:
        registry.validate(config)
    return config


def decode_voice_architecture(raw: object, registry: VoiceCapabilityRegistry | None = None, *, validate_models: bool = True) -> VoiceArchitectureSettings:
    registry = registry or default_voice_registry()
    values = _object(raw, allowed={"schema_version", "config", "compatibility"}, name="voice_architecture")
    version = values.get("schema_version")
    if type(version) is not int or version != SCHEMA_VERSION:
        raise VoiceConfigError("voice_schema_version_unsupported", "Voice schema_version must be integer 1")
    legacy = values.get("compatibility")
    compatibility = None
    if legacy is not None:
        fields = {"execution_mode", "architecture_source", "stack_id", "model_source", "stack_settings", "stack_source"}
        metadata = _object(legacy, allowed=fields, name="compatibility")
        if set(metadata) != fields:
            raise VoiceConfigError("voice_compatibility_invalid", "Compatibility metadata is incomplete")
        if metadata["execution_mode"] not in ("legacy", "continuous_brain"):
            raise VoiceConfigError("voice_compatibility_invalid", "Unknown legacy execution mode")
        if (metadata["architecture_source"] not in ("settings", "env", "default")
                or metadata["stack_source"] not in ("settings", "env", "default")
                or metadata["model_source"] not in ("settings", "env", "default", "missing")):
            raise VoiceConfigError("voice_compatibility_invalid", "Invalid compatibility source")
        if metadata["stack_id"] not in ("openai_realtime", "gemini_live") or not isinstance(metadata["stack_settings"], dict):
            raise VoiceConfigError("voice_compatibility_invalid", "Unknown legacy stack or settings")
        options = _safe_stack_options(metadata["stack_id"], metadata["stack_settings"])
        compatibility = LegacyVoiceCompatibility(metadata["execution_mode"], metadata["architecture_source"],
                                                 metadata["stack_id"], metadata["model_source"], options, metadata["stack_source"])  # type: ignore[arg-type]
    config = parse_voice_mode(values.get("config"), registry, validate_models=validate_models and compatibility is None)
    if compatibility is not None:
        if not isinstance(config, SimpleVoiceConfig) or config.conversation_model.provider_id != stack_spec(compatibility.stack_id).credential_provider:
            raise VoiceConfigError("voice_compatibility_invalid", "Compatibility migration must retain a Simple projection of the same provider")
    return VoiceArchitectureSettings(config, compatibility)


def load_voice_architecture(settings: Mapping[str, object], *, environ: Mapping[str, str] | None = None,
                            registry: VoiceCapabilityRegistry | None = None) -> VoiceArchitectureSettings:
    """Load explicit selection, otherwise project legacy without enabling new modes.

    Compatibility bridge: docs/legacy/voice-architecture-selection.md. Remove
    automatic projection only after the explicit switch coordinator migration.
    No settings, inactive profiles, prompts or environment variables are changed.
    """
    if VOICE_ARCHITECTURE_SETTING in settings:
        return decode_voice_architecture(settings[VOICE_ARCHITECTURE_SETTING], registry)
    env = os.environ if environ is None else environ
    saved_arch = str(settings.get("voice_arch") or "").strip()
    env_arch = env.get("JARVIS_VOICE_ARCH", "").strip()
    arch = parse_voice_arch(saved_arch or env_arch)
    arch_source = "settings" if saved_arch else "env" if env_arch else "default"
    saved_stack = settings.get("voice_stack")
    # Same initial default as ControlCenter._settings, before persistence.
    stack_source = "settings" if saved_stack else "env" if env.get("JARVIS_VOICE_STACK") else "default"
    spec = stack_spec(saved_stack or env.get("JARVIS_VOICE_STACK"))
    options = _safe_stack_options(spec.id, settings_for(dict(settings), spec.id))
    saved_model = str(options.get("model") or "").strip()
    if saved_model:
        model, model_source = saved_model, "settings"
    elif spec.credential_provider == "openai":
        if "OPENAI_REALTIME_MODEL" in env:
            model, model_source = env["OPENAI_REALTIME_MODEL"].strip(), "env"
        else:
            model, model_source = recommended_realtime_model(arch), "default"
    else:
        model, model_source = "", "missing"
    return VoiceArchitectureSettings(SimpleVoiceConfig(VoiceModelRef(spec.credential_provider, model)),
        LegacyVoiceCompatibility(arch.value, arch_source, spec.id, model_source, options, stack_source))


def store_voice_architecture(settings: dict[str, object], config: VoiceModeConfig,
                             registry: VoiceCapabilityRegistry | None = None) -> None:
    """Persist an explicit validated selection; retain all old/inactive settings."""
    (registry or default_voice_registry()).validate(config)
    settings[VOICE_ARCHITECTURE_SETTING] = VoiceArchitectureSettings(config).to_dict()


def voice_architecture_query(settings: Mapping[str, object], *, registry: VoiceCapabilityRegistry | None = None,
                             environ: Mapping[str, str] | None = None,
                             diagnostics: DiagnosticSink | None = None) -> dict[str, object]:
    """Secret-free projection for future Settings and runtime validation."""
    registry = registry or default_voice_registry()
    try:
        selection = (decode_voice_architecture(settings[VOICE_ARCHITECTURE_SETTING], registry, validate_models=False)
                     if VOICE_ARCHITECTURE_SETTING in settings else
                     load_voice_architecture(settings, environ=environ, registry=registry))
    except VoiceConfigError as exc:
        if diagnostics is not None:
            diagnostics.emit("voice.config.rejected", "Voice selection rejected", level="warning", data={"code": exc.code})
        raise
    problem = None
    try:
        registry.validate(selection.config, require_ready=True)
    except VoiceConfigError as exc:
        problem = {"code": exc.code, "message": str(exc)}
    if diagnostics is not None:
        diagnostics.emit("voice.config.validated", "Voice selection inspected", data={
            "architecture": selection.config.architecture.value, "schema_version": selection.schema_version,
            "compatibility_runtime": selection.uses_compatibility_runtime,
            "readiness_code": problem["code"] if problem else None,
        })
    return {
        "selection": selection.to_dict(), "new_runtime_ready": problem is None and not selection.uses_compatibility_runtime,
        "problem": problem, "compatibility_runtime": selection.uses_compatibility_runtime,
        "architectures": registry.settings_architectures(),
    }

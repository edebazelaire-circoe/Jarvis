"""Provider-neutral voice selection and capability contracts.

These identifiers intentionally do not replace v2_config.VoiceArchitecture,
which still controls the compatibility runtime's execution semantics.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import math


class VoiceArchitectureId(StrEnum):
    SIMPLE = "simple"
    FRONT_BRAIN = "front_brain"
    DUPLEX = "duplex"


class VoiceConfigError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class VoiceModelRef:
    provider_id: str
    model_id: str

    def __post_init__(self) -> None:
        for name in ("provider_id", "model_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or value != value.strip():
                raise VoiceConfigError("voice_model_invalid", f"{name} must be a trimmed string")
        if not self.provider_id:
            raise VoiceConfigError("voice_provider_missing", "Select a voice provider")
        # Empty model is retained only by compatibility migration. Explicit
        # selections must resolve through the registry and cannot use it.


@dataclass(frozen=True, slots=True)
class SimpleVoiceConfig:
    conversation_model: VoiceModelRef
    architecture: VoiceArchitectureId = VoiceArchitectureId.SIMPLE

    def __post_init__(self) -> None:
        _role(self.architecture, VoiceArchitectureId.SIMPLE)
        _model(self.conversation_model)


@dataclass(frozen=True, slots=True)
class FrontBrainVoiceConfig:
    reflex_model: VoiceModelRef
    analysis_model: VoiceModelRef
    speculative_deltas: bool = True
    reasoning_effort: str | None = "low"
    architecture: VoiceArchitectureId = VoiceArchitectureId.FRONT_BRAIN

    def __post_init__(self) -> None:
        _role(self.architecture, VoiceArchitectureId.FRONT_BRAIN)
        _model(self.reflex_model)
        _model(self.analysis_model)
        if type(self.speculative_deltas) is not bool:
            raise VoiceConfigError("voice_speculation_invalid", "speculative_deltas must be a boolean")
        if self.reasoning_effort is not None and (not isinstance(self.reasoning_effort, str) or not self.reasoning_effort):
            raise VoiceConfigError("voice_reasoning_invalid", "Select a supported reasoning effort")


@dataclass(frozen=True, slots=True)
class DuplexVoiceConfig:
    conversation_model: VoiceModelRef
    client_delegation: bool = True
    idle_timeout_s: float = 60.0
    brain_orchestration: bool = True
    architecture: VoiceArchitectureId = VoiceArchitectureId.DUPLEX

    def __post_init__(self) -> None:
        _role(self.architecture, VoiceArchitectureId.DUPLEX)
        _model(self.conversation_model)
        if self.client_delegation is not True:
            raise VoiceConfigError("voice_client_delegation_required", "Duplex requires client_delegation=true")
        # False retombe sur l'analyse spéculative sans outils : c'est un repli
        # explicite, pas un défaut. Un réglage absent vaut donc True.
        if type(self.brain_orchestration) is not bool:
            raise VoiceConfigError("voice_brain_orchestration_invalid", "brain_orchestration must be a boolean")
        if (isinstance(self.idle_timeout_s, bool)
                or not isinstance(self.idle_timeout_s, (int, float))
                or not 5 <= self.idle_timeout_s <= 3600
                or not math.isfinite(self.idle_timeout_s)):
            raise VoiceConfigError("voice_idle_timeout_invalid", "Live idle_timeout_s must be finite, between 5 and 3600 seconds")


VoiceModeConfig = SimpleVoiceConfig | FrontBrainVoiceConfig | DuplexVoiceConfig


def _role(actual: VoiceArchitectureId, expected: VoiceArchitectureId) -> None:
    if actual is not expected:
        raise VoiceConfigError("voice_architecture_invalid", f"Expected architecture {expected.value}")


def _model(value: VoiceModelRef) -> None:
    if not isinstance(value, VoiceModelRef):
        raise VoiceConfigError("voice_model_invalid", "Model selection must be a VoiceModelRef")


@dataclass(frozen=True, slots=True)
class VoiceModelCapabilities:
    supports_audio_input: bool = False
    supports_audio_output: bool = False
    supports_realtime_conversation: bool = False
    supports_full_duplex: bool = False
    supports_transcript_deltas: bool = False
    supports_semantic_vad: bool = False
    supports_native_interruptions: bool = False
    supports_function_tools: bool = False
    supports_backend_delegation: bool = False
    supports_quiet_context_injection: bool = False
    supports_spoken_result_injection: bool = False
    supports_usage_events: bool = False
    supports_prompt_update: bool = False
    supports_reasoning_effort: bool = False
    supports_text_output: bool = False
    supports_structured_output: bool = False
    billable_session_time: bool = False

    def __post_init__(self) -> None:
        if any(type(value) is not bool for value in asdict(self).values()):
            raise VoiceConfigError("voice_capability_invalid", "Capability values must be booleans")


class VoiceAdapterStatus(StrEnum):
    LEGACY_ONLY = "legacy_only"
    PLANNED = "planned"
    READY = "ready"


class ModelAvailability(StrEnum):
    UNKNOWN = "unknown"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class VoiceModelDescriptor:
    ref: VoiceModelRef
    capabilities: VoiceModelCapabilities
    evidence: str
    adapter_status: VoiceAdapterStatus = VoiceAdapterStatus.PLANNED
    availability: ModelAvailability = ModelAvailability.UNKNOWN
    reasoning_efforts: tuple[str, ...] = ()
    frontend_architectures: tuple[VoiceArchitectureId, ...] = ()

    def __post_init__(self) -> None:
        _model(self.ref)
        if not self.ref.model_id or not isinstance(self.capabilities, VoiceModelCapabilities):
            raise VoiceConfigError("voice_descriptor_invalid", "Registry entries need an exact model and capabilities")
        if not isinstance(self.adapter_status, VoiceAdapterStatus) or not isinstance(self.availability, ModelAvailability):
            raise VoiceConfigError("voice_descriptor_invalid", "Invalid adapter or availability status")
        if not isinstance(self.evidence, str) or not self.evidence.strip():
            raise VoiceConfigError("voice_evidence_missing", "Model capability evidence is required")
        if (not isinstance(self.frontend_architectures, tuple)
                or any(not isinstance(mode, VoiceArchitectureId) for mode in self.frontend_architectures)
                or not isinstance(self.reasoning_efforts, tuple)
                or any(not isinstance(effort, str) or not effort for effort in self.reasoning_efforts)):
            raise VoiceConfigError("voice_descriptor_invalid", "Invalid architecture profiles or reasoning efforts")

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self.ref), "capabilities": asdict(self.capabilities),
            "evidence": self.evidence, "adapter_status": self.adapter_status.value,
            "availability": self.availability.value, "reasoning_efforts": list(self.reasoning_efforts),
            "frontend_architectures": [mode.value for mode in self.frontend_architectures],
        }

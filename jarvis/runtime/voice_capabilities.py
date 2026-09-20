"""Evidence-backed voice models; account discovery is separate from readiness."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from jarvis.domain.voice_architecture import (
    DuplexVoiceConfig, FrontBrainVoiceConfig, ModelAvailability, SimpleVoiceConfig,
    VoiceAdapterStatus, VoiceArchitectureId, VoiceConfigError, VoiceModeConfig,
    VoiceModelCapabilities, VoiceModelDescriptor, VoiceModelRef,
)
from jarvis.v2_config import DEFAULT_CONTINUOUS_SURFACE_MODEL, DEFAULT_REALTIME_MODEL
from jarvis.runtime.voice_stack import OPENAI_REALTIME


class VoiceCapabilityRegistry:
    def __init__(self, descriptors: Iterable[VoiceModelDescriptor] = ()) -> None:
        self._models: dict[VoiceModelRef, VoiceModelDescriptor] = {}
        for descriptor in descriptors:
            self.register(descriptor)

    def register(self, descriptor: VoiceModelDescriptor) -> None:
        if descriptor.ref in self._models:
            raise VoiceConfigError("voice_model_duplicate", "Model already registered; construct an updated registry explicitly")
        self._models[descriptor.ref] = descriptor

    def find(self, ref: VoiceModelRef) -> VoiceModelDescriptor | None:
        return self._models.get(ref)

    def descriptors(self) -> tuple[VoiceModelDescriptor, ...]:
        """All registered evidence records, in deterministic registration order."""
        return tuple(self._models.values())

    def settings_architectures(self) -> list[dict[str, object]]:
        """UI schema; all choices derive from registered capability evidence."""
        descriptions = {
            VoiceArchitectureId.SIMPLE: ("Simple", "Un modèle conversationnel assure l’échange vocal."),
            VoiceArchitectureId.FRONT_BRAIN: ("Front Brain", "Conversation réflexe et analyse parallèle des transcriptions."),
            VoiceArchitectureId.DUPLEX: ("Duplex", "Conversation Live continue avec délégation au client JARVIS."),
        }
        result = []
        for mode in VoiceArchitectureId:
            fields = []
            defaults: dict[str, object] = {"architecture": mode.value}
            roles = [("reflex_model", "Réflexe conversationnel", "conversation"),
                     ("analysis_model", "Analyse", "analysis")] if mode is VoiceArchitectureId.FRONT_BRAIN else [
                         ("conversation_model", "Conversation", "conversation")]
            for key, label, role in roles:
                options = []
                for model in self.query(mode, role=role):
                    reason = ("Adaptateur : " + model.adapter_status.value
                              if model.adapter_status is not VoiceAdapterStatus.READY else
                              "Modèle indisponible pour le compte configuré"
                              if model.availability is ModelAvailability.UNAVAILABLE else None)
                    options.append({**model.to_dict(), "label": f"{model.ref.provider_id} / {model.ref.model_id}",
                                    "selectable": reason is None, "reason": reason,
                                    "settings_scope": OPENAI_REALTIME.id if model.ref.provider_id == "openai" and mode is not VoiceArchitectureId.DUPLEX and role == "conversation" else None,
                                    "settings_fields": [field.describe() for field in OPENAI_REALTIME.fields
                                                        if field.key not in {"model", "ack_delay_ms", "reflex_enabled"}]
                                    if model.ref.provider_id == "openai" and mode is not VoiceArchitectureId.DUPLEX and role == "conversation" else []})
                chosen = next((item for item in options if item["selectable"]), None)
                default = {name: chosen[name] for name in ("provider_id", "model_id")} if chosen else None
                defaults[key] = default
                fields.append({"key": key, "label": label, "kind": "model", "role": role,
                               "options": options, "default": default})
            if mode is VoiceArchitectureId.FRONT_BRAIN:
                fields.extend([
                    {"key": "speculative_deltas", "label": "Analyse des transcriptions provisoires", "kind": "toggle", "default": True},
                    {"key": "reasoning_effort", "label": "Effort de raisonnement", "kind": "select",
                     "options_from": "analysis_model", "options_property": "reasoning_efforts", "default": "low"},
                ])
                defaults.update(speculative_deltas=True, reasoning_effort="low")
            if mode is VoiceArchitectureId.DUPLEX:
                fields.extend([
                    {"key": "client_delegation", "label": "Délégation client active", "kind": "toggle", "default": True, "readonly": True},
                    {"key": "idle_timeout_s", "label": "Fermeture après inactivité (secondes)", "kind": "number",
                     "default": 60, "min": 5, "max": 3600},
                    {"key": "brain_orchestration", "label": "Déléguer au cerveau (outils et sous-agents)",
                     "kind": "toggle", "default": True},
                ])
                defaults.update(client_delegation=True, idle_timeout_s=60, brain_orchestration=True)
            label, description = descriptions[mode]
            result.append({"id": mode.value, "label": label, "description": description,
                           "fields": fields, "defaults": defaults,
                           "conversation_models": fields[0]["options"],
                           "analysis_models": fields[1]["options"] if mode is VoiceArchitectureId.FRONT_BRAIN else []})
        return result

    def require(self, ref: VoiceModelRef) -> VoiceModelDescriptor:
        result = self.find(ref)
        if result is None:
            raise VoiceConfigError("voice_model_unsupported", f"Unsupported voice selection {ref.provider_id}/{ref.model_id or '(missing model)'}. Refresh the provider catalog and select a supported model.")
        return result

    def query(self, architecture: VoiceArchitectureId | str, *, role: str = "conversation", ready_only: bool = False) -> tuple[VoiceModelDescriptor, ...]:
        try:
            mode = VoiceArchitectureId(architecture)
        except (ValueError, TypeError) as exc:
            raise VoiceConfigError("voice_architecture_unknown", "Choose simple, front_brain or duplex") from exc
        if role not in ({"conversation", "analysis"} if mode is VoiceArchitectureId.FRONT_BRAIN else {"conversation"}):
            raise VoiceConfigError("voice_role_invalid", "Analysis role exists only in Front Brain")
        return tuple(item for item in self._models.values()
                     if _compatible(item, mode, role)
                     and (not ready_only or (item.adapter_status is VoiceAdapterStatus.READY
                                            and item.availability is not ModelAvailability.UNAVAILABLE)))

    def validate(self, config: VoiceModeConfig, *, require_ready: bool = False) -> None:
        selections = [("conversation", config.reflex_model if isinstance(config, FrontBrainVoiceConfig) else config.conversation_model)]
        if isinstance(config, FrontBrainVoiceConfig):
            selections.append(("analysis", config.analysis_model))
        for role, ref in selections:
            descriptor = self.require(ref)
            if descriptor not in self.query(config.architecture, role=role):
                raise VoiceConfigError("voice_model_incompatible", f"{ref.model_id} cannot serve {config.architecture.value}/{role}")
            if require_ready and descriptor.adapter_status is not VoiceAdapterStatus.READY:
                raise VoiceConfigError("voice_adapter_not_ready", f"{ref.model_id}: new voice adapter is {descriptor.adapter_status.value}; keep compatibility mode until implemented")
            if require_ready and descriptor.availability is ModelAvailability.UNAVAILABLE:
                raise VoiceConfigError("voice_model_unavailable", f"{ref.model_id} is unavailable for the configured account")
        if isinstance(config, FrontBrainVoiceConfig):
            analysis = self.require(config.analysis_model)
            if config.reasoning_effort is not None and config.reasoning_effort not in analysis.reasoning_efforts:
                raise VoiceConfigError("voice_reasoning_unsupported", f"Unsupported reasoning effort for {config.analysis_model.model_id}")
            if config.speculative_deltas and not self.require(config.reflex_model).capabilities.supports_transcript_deltas:
                raise VoiceConfigError("voice_deltas_unsupported", "Selected reflex adapter cannot supply speculative transcript deltas")


def _compatible(item: VoiceModelDescriptor, mode: VoiceArchitectureId, role: str) -> bool:
    cap = item.capabilities
    if role == "analysis":
        return cap.supports_text_output and cap.supports_structured_output
    audio = cap.supports_audio_input and cap.supports_audio_output and cap.supports_realtime_conversation
    if mode not in item.frontend_architectures:
        return False
    if mode is VoiceArchitectureId.DUPLEX:
        return audio and cap.supports_full_duplex and cap.supports_backend_delegation and cap.supports_quiet_context_injection
    return audio


def default_voice_registry(*, google_models: Iterable[Mapping[str, object]] = ()) -> VoiceCapabilityRegistry:
    """Google entries must be provider-catalog records, never name heuristics.

    Discovery does not open any sessions. API model availability says nothing
    about whether the canonical adapter has been implemented or acoustically tested.
    """
    realtime = VoiceModelCapabilities(
        supports_audio_input=True, supports_audio_output=True, supports_realtime_conversation=True,
        supports_transcript_deltas=True, supports_semantic_vad=True, supports_native_interruptions=True,
        supports_function_tools=True, supports_backend_delegation=True, supports_spoken_result_injection=True,
    )
    entries = [VoiceModelDescriptor(VoiceModelRef("openai", model), realtime,
                                   "jarvis/adapters/openai_realtime.py; jarvis/v2_config.py",
                                   VoiceAdapterStatus.READY,
                                   frontend_architectures=(VoiceArchitectureId.SIMPLE, VoiceArchitectureId.FRONT_BRAIN))
               for model in (DEFAULT_REALTIME_MODEL, DEFAULT_CONTINUOUS_SURFACE_MODEL)]
    entries.extend((
        VoiceModelDescriptor(VoiceModelRef("openai", "gpt-5.6-luna"), VoiceModelCapabilities(
            supports_text_output=True, supports_structured_output=True, supports_reasoning_effort=True,
        ), "https://developers.openai.com/api/docs/models/gpt-5.6-luna (verified 2026-09-12)",
            adapter_status=VoiceAdapterStatus.READY,
            reasoning_efforts=("none", "low", "medium", "high", "xhigh", "max")),
        VoiceModelDescriptor(VoiceModelRef("openai", "gpt-live-1"), VoiceModelCapabilities(
            supports_audio_input=True, supports_audio_output=True, supports_realtime_conversation=True,
            supports_full_duplex=True, supports_transcript_deltas=True, supports_native_interruptions=False,
            supports_backend_delegation=True, supports_quiet_context_injection=True,
            supports_spoken_result_injection=True, supports_usage_events=True, supports_prompt_update=True,
            billable_session_time=True,
        ), "https://developers.openai.com/api/docs/guides/live-delegation (verified 2026-09-12)",
            adapter_status=VoiceAdapterStatus.READY,
            frontend_architectures=(VoiceArchitectureId.DUPLEX,)),
    ))
    seen: set[str] = set()
    for model in google_models:
        methods = model.get("methods")
        model_id = model.get("id")
        if not isinstance(methods, (list, tuple)) or "bidiGenerateContent" not in methods:
            continue
        if not isinstance(model_id, str) or not model_id.strip() or model_id != model_id.strip():
            raise VoiceConfigError("voice_catalog_model_invalid", "Google Live catalog entry requires an exact model ID")
        if model_id in seen:
            continue
        seen.add(model_id)
        entries.append(VoiceModelDescriptor(VoiceModelRef("google", model_id), VoiceModelCapabilities(
            supports_audio_input=True, supports_audio_output=True, supports_realtime_conversation=True,
            supports_native_interruptions=True, supports_function_tools=True, supports_backend_delegation=True,
        ), "Google model catalog: bidiGenerateContent; jarvis/adapters/gemini_live.py",
            VoiceAdapterStatus.LEGACY_ONLY, ModelAvailability.AVAILABLE,
            frontend_architectures=(VoiceArchitectureId.SIMPLE, VoiceArchitectureId.FRONT_BRAIN)))
    return VoiceCapabilityRegistry(entries)

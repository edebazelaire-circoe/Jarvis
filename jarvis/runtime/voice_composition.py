"""Resolve explicit conversation behavior separately from compatibility metadata."""
from dataclasses import dataclass
import hashlib
import json

from jarvis.domain.voice_architecture import DuplexVoiceConfig, FrontBrainVoiceConfig, VoiceConfigError, VoiceModelRef
from jarvis.runtime.voice_architecture_config import VoiceArchitectureSettings, load_voice_architecture
from jarvis.runtime.voice_stack import OPENAI_REALTIME
from jarvis.runtime.voice_capabilities import default_voice_registry
from jarvis.domain.conversation_prompt import CONVERSATION_PROMPT_ID
from jarvis.domain.front_brain_prompt import FRONT_BRAIN_PROMPT_ID
from jarvis.domain.live_prompt import LIVE_PROMPT_ID


@dataclass(frozen=True, slots=True)
class VoiceComposition:
    selection: VoiceArchitectureSettings
    stack_id: str

    @property
    def direct_conversation(self) -> bool:
        return not self.selection.uses_compatibility_runtime

    @property
    def configuration_id(self) -> str:
        identity = {"selection": self.selection.to_dict(), "conversation_prompt": CONVERSATION_PROMPT_ID,
                    "analysis_prompt": FRONT_BRAIN_PROMPT_ID}
        if isinstance(self.selection.config, DuplexVoiceConfig):
            identity["live_prompt"] = LIVE_PROMPT_ID
        return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def resolve_voice_composition(settings, *, environ=None) -> VoiceComposition:
    selection = load_voice_architecture(settings, environ=environ)
    if selection.uses_compatibility_runtime:
        return VoiceComposition(selection, selection.compatibility.stack_id)
    config = selection.config
    if isinstance(config, DuplexVoiceConfig):
        if config.conversation_model != VoiceModelRef("openai", "gpt-live-1"):
            raise VoiceConfigError("voice_adapter_not_ready", "Duplex requires openai/gpt-live-1")
        default_voice_registry().validate(config, require_ready=True)
        return VoiceComposition(selection, OPENAI_REALTIME.id)
    model = config.reflex_model if isinstance(config, FrontBrainVoiceConfig) else config.conversation_model
    if model.provider_id != "openai":
        raise VoiceConfigError("voice_adapter_not_ready", "Direct conversation currently requires the OpenAI Realtime adapter")
    if isinstance(config, FrontBrainVoiceConfig) and config.analysis_model.provider_id != "openai":
        raise VoiceConfigError("voice_adapter_not_ready", "Front Brain currently requires the OpenAI Responses adapter")
    default_voice_registry().validate(config, require_ready=True)
    return VoiceComposition(selection, OPENAI_REALTIME.id)

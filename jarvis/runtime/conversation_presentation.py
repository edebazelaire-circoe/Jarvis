"""A direct-generation candidate has no intended assistant text or backend work."""
from dataclasses import dataclass
from datetime import datetime

from jarvis.domain.speech_presentation import SpeechSource
from jarvis.domain.voice_frontend import VoiceConversationRequest


@dataclass(frozen=True, slots=True)
class ConversationCandidate:
    id: str
    conversation_id: str
    source: SpeechSource
    request: VoiceConversationRequest
    expires_at: datetime

    @property
    def correlation_id(self) -> str:
        return self.source.correlation_id

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at

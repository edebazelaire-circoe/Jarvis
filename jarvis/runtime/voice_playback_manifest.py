"""Join complete provider parts to exact device evidence, never intended text."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field

from jarvis.domain.voice_events import (
    AssistantAudioChunk, AssistantAudioPartCompleted, AssistantGenerationFinished,
    AssistantPlaybackEvidence, AssistantTranscriptCompleted, AssistantTranscriptDelta,
    VoiceGenerationStatus, VoicePlaybackStatus,
)
from jarvis.domain.voice_playback import (
    VoiceAudioPart, VoiceAudioPartExtent, VoiceDevicePlaybackProof, VoiceDevicePlaybackStatus,
    VoicePlaybackManifest,
)


@dataclass(slots=True)
class _Output:
    session_id: str
    response_id: str
    received: dict[VoiceAudioPart, int] = field(default_factory=dict)
    closed: set[VoiceAudioPart] = field(default_factory=set)
    transcripts: dict[VoiceAudioPart, str | None] = field(default_factory=dict)
    expected: tuple[VoiceAudioPart, ...] | None = None
    declared_transcripts: dict[VoiceAudioPart, str | None] = field(default_factory=dict)
    generation_done: bool = False
    invalid: bool = False
    duration_ms: float = 0
    frozen: VoicePlaybackManifest | None = None
    proof: VoiceDevicePlaybackProof | None = None
    emitted: AssistantPlaybackEvidence | None = None


class VoicePlaybackManifests:
    """Session-local, bounded proof join. Eviction/restart loses eligibility safely."""
    def __init__(self) -> None:
        self._outputs: OrderedDict[str, _Output] = OrderedDict()

    def observe(self, event) -> AssistantPlaybackEvidence | None:
        correlation, payload = event.correlation, event.payload
        key = correlation.output_id
        if not key or not correlation.provider_output_id:
            return None
        output = self._outputs.get(key)
        if output is None:
            output = _Output(correlation.session_id, correlation.provider_output_id)
            self._outputs[key] = output
            while len(self._outputs) > 128:
                self._outputs.popitem(last=False)
        if (output.session_id, output.response_id) != (correlation.session_id, correlation.provider_output_id):
            output.invalid = True
        part = getattr(payload, "part", None)
        if isinstance(payload, AssistantAudioChunk):
            if part is None or output.generation_done or part in output.closed:
                output.invalid = True
            elif part not in output.received and len(output.received) >= 16:
                output.invalid = True
            else:
                output.received[part] = output.received.get(part, 0) + len(payload.audio.pcm)
                output.duration_ms += len(payload.audio.pcm) * 1000 / (payload.audio.format.sample_rate_hz * 2)
        elif isinstance(payload, AssistantAudioPartCompleted):
            if (output.expected is not None and part not in output.expected) or (len(output.closed) >= 16 and part not in output.closed):
                output.invalid = True
            else:
                output.closed.add(part)
        elif isinstance(payload, (AssistantTranscriptDelta, AssistantTranscriptCompleted)):
            if part is None or (part not in output.transcripts and len(output.transcripts) >= 16):
                output.invalid = True
            elif isinstance(payload, AssistantTranscriptCompleted):
                old = output.transcripts.get(part)
                if old is not None and old != payload.text:
                    output.invalid = True
                elif sum(len(text or "") for key, text in output.transcripts.items() if key != part) + len(payload.text) > 8192:
                    output.invalid = True
                else:
                    output.transcripts[part] = payload.text
            else:
                if output.transcripts.get(part) is not None and payload.delta:
                    output.invalid = True
                output.transcripts.setdefault(part, None)
        elif isinstance(payload, AssistantGenerationFinished):
            if output.generation_done and payload.audio_parts != output.expected:
                output.invalid = True
            output.generation_done = True
            output.expected = payload.audio_parts
            declared = dict(zip(payload.audio_parts or (), payload.audio_transcripts or ()))
            if output.declared_transcripts and declared != output.declared_transcripts:
                output.invalid = True
            output.declared_transcripts = declared
            if payload.status is not VoiceGenerationStatus.COMPLETED or not output.expected or len(output.expected) > 16:
                output.invalid = True
        return self._evidence(output)

    def freeze(self, session_id: str, output_id: str, response_id: str) -> VoicePlaybackManifest | None:
        output = self._outputs.get(output_id)
        if output is None or output.invalid or not output.generation_done or not output.expected:
            return None
        if (session_id, response_id) != (output.session_id, output.response_id):
            return None
        expected = set(output.expected)
        if expected != set(output.received) or expected != output.closed or not set(output.transcripts) <= expected or any(count <= 0 for count in output.received.values()):
            return None
        if output.frozen is None:
            parts = tuple(VoiceAudioPartExtent(part, output.received[part]) for part in output.expected)
            output.frozen = VoicePlaybackManifest(session_id, output_id, response_id, parts, sum(part.byte_count for part in parts))
        return output.frozen

    def complete(self, manifest: VoicePlaybackManifest, proof: VoiceDevicePlaybackProof) -> AssistantPlaybackEvidence | None:
        output = self._outputs.get(manifest.output_id)
        if output is None or self.freeze(manifest.session_id, manifest.output_id, manifest.provider_response_id) != manifest:
            return None
        if proof.status is not VoiceDevicePlaybackStatus.COMPLETE:
            output.invalid = True
            return None
        identity = (proof.session_id, proof.output_id, proof.provider_response_id)
        if identity != (manifest.session_id, manifest.output_id, manifest.provider_response_id) or proof.parts != manifest.parts or proof.written_bytes != manifest.received_bytes or proof.confirmed_bytes != manifest.received_bytes:
            output.invalid = True
            return None
        if output.proof is not None and output.proof != proof:
            output.invalid = True
            return None
        output.proof = proof
        return self._evidence(output)

    @staticmethod
    def _evidence(output: _Output) -> AssistantPlaybackEvidence | None:
        if output.invalid or output.proof is None or not output.expected:
            return None
        if not set(output.transcripts) <= set(output.expected):
            output.invalid = True
            return None
        if set(output.expected) != set(output.received) or set(output.expected) != output.closed:
            output.invalid = True
            return None
        if any(text is not None and output.declared_transcripts.get(part) is not None and text != output.declared_transcripts[part] for part, text in output.transcripts.items()):
            output.invalid = True
            return None
        text = None
        if all(output.transcripts.get(part) is not None for part in output.expected):
            text = "".join(output.transcripts[part] for part in output.expected)
        evidence = AssistantPlaybackEvidence(VoicePlaybackStatus.COMPLETE, output.duration_ms, text)
        if evidence == output.emitted:
            return None
        output.emitted = evidence
        return evidence

    def invalidate(self, output_id: str | None = None) -> None:
        for key, output in self._outputs.items():
            if output_id is None or key == output_id:
                output.invalid = True

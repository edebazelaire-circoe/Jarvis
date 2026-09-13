"""Neutral all-part device completion values; no text or provider SDK objects."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from jarvis.domain.voice_frontend import nonnegative_int


def _identity(value: str, name: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 256 or value.strip() != value or not value.isprintable():
        raise ValueError(f"{name} must be a bounded printable ID")


@dataclass(frozen=True, slots=True)
class VoiceAudioPart:
    item_id: str
    content_index: int
    output_index: int | None = None

    def __post_init__(self) -> None:
        _identity(self.item_id, "Audio item")
        nonnegative_int(self.content_index, "content_index")
        if self.content_index > 127:
            raise ValueError("Audio content index exceeds retention bound")
        if self.output_index is not None:
            nonnegative_int(self.output_index, "output_index")
            if self.output_index > 127:
                raise ValueError("Audio output index exceeds retention bound")


@dataclass(frozen=True, slots=True)
class VoiceAudioPartExtent:
    part: VoiceAudioPart
    byte_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.part, VoiceAudioPart):
            raise ValueError("Audio extent requires a typed part")
        nonnegative_int(self.byte_count, "byte_count")
        if self.byte_count > 512 * 1024 * 1024:
            raise ValueError("Audio extent exceeds retention bound")


def _parts(parts: tuple[VoiceAudioPartExtent, ...]) -> None:
    if not isinstance(parts, tuple) or not 1 <= len(parts) <= 128 or any(not isinstance(part, VoiceAudioPartExtent) for part in parts):
        raise ValueError("Playback requires a bounded tuple of part extents")
    if len({part.part for part in parts}) != len(parts):
        raise ValueError("Playback parts must be unique")


@dataclass(frozen=True, slots=True)
class VoicePlaybackManifest:
    session_id: str
    output_id: str
    provider_response_id: str
    parts: tuple[VoiceAudioPartExtent, ...]
    received_bytes: int

    def __post_init__(self) -> None:
        for name in ("session_id", "output_id", "provider_response_id"):
            _identity(getattr(self, name), name)
        _parts(self.parts)
        nonnegative_int(self.received_bytes, "received_bytes")
        if any(part.byte_count == 0 or part.part.output_index is None for part in self.parts) or self.received_bytes != sum(part.byte_count for part in self.parts):
            raise ValueError("Manifest must account for positive audio in every part")


class VoiceDevicePlaybackStatus(StrEnum):
    COMPLETE = "completed"
    UNKNOWN = "unknown"
    FAILED = "failed"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class VoiceDevicePlaybackProof:
    status: VoiceDevicePlaybackStatus
    session_id: str
    output_id: str
    provider_response_id: str
    audio_instance_id: str
    output_epoch: int
    playback_epoch: int
    operation_id: str
    parts: tuple[VoiceAudioPartExtent, ...]
    written_bytes: int
    confirmed_bytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.status, VoiceDevicePlaybackStatus):
            raise ValueError("Device playback status must be typed")
        for name in ("session_id", "output_id", "provider_response_id", "audio_instance_id", "operation_id"):
            _identity(getattr(self, name), name)
        for name in ("output_epoch", "playback_epoch", "written_bytes", "confirmed_bytes"):
            nonnegative_int(getattr(self, name), name)
        _parts(self.parts)
        if self.written_bytes != sum(part.byte_count for part in self.parts) or self.confirmed_bytes > self.written_bytes:
            raise ValueError("Device proof byte extents disagree")
        if self.status is VoiceDevicePlaybackStatus.COMPLETE and (not self.confirmed_bytes or self.confirmed_bytes != self.written_bytes):
            raise ValueError("Complete proof requires positive fully drained bytes")

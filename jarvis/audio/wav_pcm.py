"""En-tête WAV PCM16 d'un enregistrement explicite (handoff session-context-recording, Slice 06).

Pur : aucun accès disque, aucune dépendance. Partagé par l'écrivain du spool
(`jarvis/adapters/sounddevice_recording.py`), la réparation après la mort de
Core (même module) et le transcripteur qui relit le spool durable
(`jarvis/core/recording_transcriber.py`). Contrat : `docs/capture.md` › *Audio*.

Forme écrite : l'en-tête canonique de 44 octets (`RIFF`, `fmt ` de 16 octets,
`data`), tailles provisoires à zéro au démarrage, réécrites en place
(`write_at`) pendant l'enregistrement et à la fin. Un lecteur ne se fie donc
jamais à la taille `data` déclarée tant que l'enregistrement est ouvert : la
taille du fichier fait foi (`data_bytes_on_disk`).
"""

from __future__ import annotations

from dataclasses import dataclass
import struct

#: Taille de l'en-tête canonique écrit par l'enregistreur.
HEADER_BYTES = 44
PCM_FORMAT = 1
SAMPLE_WIDTH = 2
#: Une taille RIFF tient sur 32 bits : au-delà, l'en-tête plafonne (≈ 18 h à 16 kHz mono).
MAX_RIFF_DATA = 0xFFFFFFFF - 36


class WavFormatError(ValueError):
    """Préfixe qui n'est pas un WAV PCM16 lisible."""


@dataclass(frozen=True, slots=True)
class WavFormat:
    sample_rate: int
    channels: int
    sample_width: int
    #: Décalage du premier octet de PCM (44 pour l'en-tête canonique).
    data_offset: int
    #: Taille `data` déclarée par l'en-tête (provisoire tant que l'enregistrement est ouvert).
    declared_data_bytes: int

    @property
    def frame_bytes(self) -> int:
        return self.channels * self.sample_width

    def frames_in(self, data_bytes: int) -> int:
        return max(0, data_bytes) // self.frame_bytes

    def ms_of(self, frames: int) -> int:
        return frames * 1000 // self.sample_rate

    def data_bytes_on_disk(self, file_bytes: int) -> int:
        """PCM entier (trames complètes) présent dans un fichier de `file_bytes` octets."""

        usable = max(0, file_bytes - self.data_offset)
        return usable - usable % self.frame_bytes


def wav_header(*, sample_rate: int, channels: int, data_bytes: int) -> bytes:
    """En-tête canonique de 44 octets ; `data_bytes` plafonné à la limite 32 bits."""

    if sample_rate <= 0 or channels <= 0 or data_bytes < 0:
        raise ValueError("wav header needs a positive rate/channels and a non-negative size")
    data_bytes = min(data_bytes, MAX_RIFF_DATA)
    block_align = channels * SAMPLE_WIDTH
    return (b"RIFF" + struct.pack("<I", 36 + data_bytes) + b"WAVE"
            + b"fmt " + struct.pack("<IHHIIHH", 16, PCM_FORMAT, channels, sample_rate, sample_rate * block_align,
                                    block_align, SAMPLE_WIDTH * 8)
            + b"data" + struct.pack("<I", data_bytes))


def size_fields(data_bytes: int) -> tuple[tuple[int, bytes], tuple[int, bytes]]:
    """Les deux champs de taille à réécrire en place : `(offset, octets)` pour RIFF et `data`."""

    data_bytes = min(max(0, data_bytes), MAX_RIFF_DATA)
    return (4, struct.pack("<I", 36 + data_bytes)), (40, struct.pack("<I", data_bytes))


def pcm16_wav(pcm: bytes, *, sample_rate: int, channels: int = 1) -> bytes:
    """Un clip WAV complet en mémoire (segment envoyé au fournisseur de transcription)."""

    return wav_header(sample_rate=sample_rate, channels=channels, data_bytes=len(pcm)) + bytes(pcm)


def parse_wav_header(prefix: bytes) -> WavFormat:
    """Lit `RIFF/WAVE`, le bloc `fmt ` (PCM 16 bits) et la position du bloc `data`.

    `prefix` : les premiers octets du fichier (≥ 44 pour l'en-tête canonique).
    `WavFormatError` pour tout autre format : un enregistrement explicite est
    toujours écrit en PCM16 par Jarvis, rien d'autre n'est deviné.
    """

    if len(prefix) < 12 or prefix[:4] != b"RIFF" or prefix[8:12] != b"WAVE":
        raise WavFormatError("not a RIFF/WAVE file")
    offset = 12
    fmt: tuple[int, int, int, int] | None = None
    while offset + 8 <= len(prefix):
        chunk_id = prefix[offset:offset + 4]
        (size,) = struct.unpack_from("<I", prefix, offset + 4)
        body = offset + 8
        if chunk_id == b"fmt ":
            if size < 16 or body + 16 > len(prefix):
                raise WavFormatError("truncated fmt chunk")
            audio_format, channels, rate, _byte_rate, _align, bits = struct.unpack_from("<HHIIHH", prefix, body)
            fmt = (audio_format, channels, rate, bits)
        elif chunk_id == b"data":
            if fmt is None:
                raise WavFormatError("data chunk before fmt chunk")
            audio_format, channels, rate, bits = fmt
            if audio_format != PCM_FORMAT or bits != 16 or channels < 1 or rate <= 0:
                raise WavFormatError(f"unsupported wav format (format={audio_format}, bits={bits}, "
                                     f"channels={channels}, rate={rate})")
            return WavFormat(sample_rate=rate, channels=channels, sample_width=SAMPLE_WIDTH, data_offset=body,
                             declared_data_bytes=size)
        offset = body + size + (size & 1)
    raise WavFormatError("no data chunk in the header prefix")


__all__ = [
    "HEADER_BYTES", "MAX_RIFF_DATA", "SAMPLE_WIDTH", "WavFormat", "WavFormatError", "parse_wav_header",
    "pcm16_wav", "size_fields", "wav_header",
]

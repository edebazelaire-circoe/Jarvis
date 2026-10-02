"""Enregistrement audio explicite dans Core (handoff session-context-recording, Slice 06 ; D11, D12, D-CAP, D-AUDIO).

Source micro du `CaptureService` (`docs/capture.md` › *Audio recording*) :

- **un flux `sounddevice` à soi**, ouvert par Core, distinct de ceux de Voice
  (WASAPI/MME partagés, déjà multi-flux en SIMPLE). Aucun couplage avec
  `AudioCaptureHub` ni avec son `drop_oldest` : la voie ambiante de
  PRESENTATION reste mémoire seule (D12). Même réglage d'appareil que Voice
  (`audio_input_device` des réglages du Control Center, sinon
  `JARVIS_AUDIO_INPUT_DEVICE`) ;
- **format fixe** PCM16 mono 16 kHz (repli 24 puis 48 kHz si l'appareil
  refuse) : la transcription n'utilise pas plus (les modèles STT travaillent
  à 16 kHz), et le fichier pèse 115 Mo/h au lieu de 173 Mo/h à 24 kHz ;
- le callback PortAudio **copie** chaque bloc (100 ms) dans une file bornée
  (30 s) et rien d'autre. Un fil d'écriture vide la file vers le spool de
  l'Artifact (`CaptureSink`) : en-tête WAV écrit d'abord avec des tailles
  provisoires, tailles réécrites en place (`write_at`) toutes les 5 s et à la
  fin, `fsync` au même rythme ;
- **aucune perte silencieuse** : file pleine -> le bloc le plus récent est
  refusé et compté ; au bloc suivant accepté, le fil d'écriture insère autant
  de **silence numérique** (zéros) que d'échantillons perdus, à leur place,
  et signale un `capture.gap` (`queue_overflow`, `lost_ms` exact). Le temps
  du fichier reste ainsi le temps du mur (transcription alignée), et le trou
  est dit (gap, capture `partial`, métadonnées `gap_count`/`gap_lost_ms`).
  Un débordement côté pilote (`input_overflow` de PortAudio, durée inconnue)
  est aussi un `capture.gap` ;
- appareil perdu (flux arrêté par le pilote, ou plus aucun bloc pendant 3 s) :
  `source_lost`, la capture s'arrête et la preuve est `partial`. Ouverture
  refusée : `permission_denied` (accès refusé par le système) ou
  `source_unavailable` (absent, occupé en exclusif, format refusé).

`WavCaptureRepair` est la réparation de famille (`CaptureRepair`) appliquée
après une mort de Core : tailles RIFF/`data` recalculées depuis la longueur
réelle du fichier, échantillon partiel final retiré, durée rendue.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
import os
import queue
import struct
import threading
import time
from typing import Any, Protocol

from jarvis.audio.input_ownership import OWNER_EXPLICIT_RECORDING, register_input_stream, release_input_stream
from jarvis.audio.wav_pcm import HEADER_BYTES, WavFormatError, parse_wav_header, size_fields, wav_header
from jarvis.domain.capture import DEFAULT_DEVICE, CaptureChannel, CaptureError, CaptureErrorCode, CaptureMode
from jarvis.domain.v2 import utc_now
from jarvis.ports.capture import (
    CaptureSink, CaptureSource, CaptureSourceError, CaptureSourceRegistry, MediaInfo, OneShotSource, RepairOutcome,
    RepairTarget, SourceHealth,
)

MICROPHONE_SOURCE = "microphone"
#: Fréquences essayées dans l'ordre : 16 kHz (STT, taille), sinon ce que l'appareil accepte.
RECORDING_SAMPLE_RATES = (16_000, 24_000, 48_000)
CHANNELS = 1
BLOCK_MS = 100
#: Profondeur de la file callback -> écrivain : 30 s d'audio (≈ 1 Mo à 16 kHz).
QUEUE_SECONDS = 30
HEADER_REFRESH_S = 5.0
#: Plus aucun bloc pendant ce délai alors que le flux est censé tourner : appareil perdu.
STALL_S = 3.0
#: Attente bornée de la fin du fil d'écriture à l'arrêt (sous l'échéance d'arrêt du service, 10 s).
WRITER_JOIN_S = 8.0
_PERMISSION_MARKERS = ("denied", "permission", "access is", "0x80070005")


def source_error(exc: BaseException, what: str) -> CaptureSourceError:
    """Code stable d'un refus d'ouverture, cause dite avec son type (jamais réétiquetée)."""

    text = f"{type(exc).__name__}: {exc}"
    code = (CaptureErrorCode.PERMISSION_DENIED if any(m in text.lower() for m in _PERMISSION_MARKERS)
            else CaptureErrorCode.SOURCE_UNAVAILABLE)
    return CaptureSourceError(code, f"{what}: {text}"[:300])


# ------------------------------------------------------------------ appareil


class InputStream(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class OpenedInput:
    stream: InputStream
    sample_rate: int
    device_name: str


#: `callback(pcm, input_overflow)` depuis le fil PortAudio ; `finished()` quand le flux s'arrête.
BlockCallback = Callable[[bytes, bool], None]


class InputBackend(Protocol):
    """Ouvre un flux d'entrée PCM16 mono **non démarré** (la source écrit l'en-tête avant le premier bloc)."""

    def open(self, *, device: int | str | None, sample_rates: Sequence[int], block_ms: int,
             callback: BlockCallback, finished: Callable[[], None]) -> OpenedInput: ...

    def close(self, opened: OpenedInput) -> None:
        """Arrête et ferme le flux, retire son inscription ; sûr même après une perte."""
        ...


class SoundDeviceInput:
    """`InputBackend` réel : `sounddevice.RawInputStream`, inscrit au registre des propriétaires d'entrée."""

    def open(self, *, device: int | str | None, sample_rates: Sequence[int], block_ms: int,
             callback: BlockCallback, finished: Callable[[], None]) -> OpenedInput:
        try:
            import sounddevice as sd  # type: ignore
        except (ImportError, OSError) as exc:  # PortAudio absent : OSError à l'import
            raise CaptureSourceError(CaptureErrorCode.SOURCE_UNAVAILABLE,
                                     f"sounddevice unavailable: {type(exc).__name__}: {exc}"[:300]) from exc
        try:
            info = sd.query_devices(device, "input")
            name = str(info.get("name") or device or "default")
        except Exception as exc:  # noqa: BLE001 - every PortAudio/lookup failure gets a stable code, cause kept
            raise source_error(exc, f"input device {device!r} not found") from exc
        rate, refusal = None, None
        for candidate in sample_rates:
            try:
                sd.check_input_settings(device=device, channels=CHANNELS, dtype="int16", samplerate=candidate)
                rate = int(candidate)
                break
            except Exception as exc:  # noqa: BLE001 - try the next rate; the last refusal is raised below
                refusal = exc
        if rate is None:
            raise source_error(refusal or RuntimeError("no rate"), f"input {name!r} refuses PCM16 mono "
                               f"at {', '.join(str(r) for r in sample_rates)} Hz")

        def on_audio(indata, frames, time_info, status) -> None:  # noqa: ANN001 - PortAudio signature
            del frames, time_info
            callback(bytes(indata), bool(getattr(status, "input_overflow", False)))

        try:
            stream = sd.RawInputStream(samplerate=rate, channels=CHANNELS, dtype="int16", device=device,
                                       blocksize=rate * block_ms // 1000, callback=on_audio,
                                       finished_callback=finished)
        except Exception as exc:  # noqa: BLE001 - busy/exclusive/denied device: stable code, cause kept
            raise source_error(exc, f"cannot open input {name!r}") from exc
        # Registre des propriétaires d'entrée (conformité du dépôt) : propre au
        # processus Core, il ne bloque ni ne compte les flux de Voice.
        register_input_stream(OWNER_EXPLICIT_RECORDING, stream, label=name[:80])
        return OpenedInput(stream=_StartingStream(stream, name), sample_rate=rate, device_name=name)

    def close(self, opened: OpenedInput) -> None:
        stream = opened.stream.inner if isinstance(opened.stream, _StartingStream) else opened.stream
        try:
            try:
                stream.stop()
            finally:
                stream.close()
        finally:
            release_input_stream(stream)


class _StartingStream:
    """Démarrage mappé en code stable (un démarrage refusé = appareil occupé ou refusé)."""

    def __init__(self, inner: Any, name: str) -> None:
        self.inner = inner
        self._name = name

    def start(self) -> None:
        try:
            self.inner.start()
        except Exception as exc:  # noqa: BLE001 - stable code, cause kept
            raise source_error(exc, f"cannot start input {self._name!r}") from exc

    def stop(self) -> None:
        self.inner.stop()

    def close(self) -> None:
        self.inner.close()


# ------------------------------------------------------------------ source


class MicrophoneRecordingSource:
    """`CaptureSource` d'**un** enregistrement explicite. Voir l'en-tête du module."""

    payload_name = "source.wav"
    mime_type = "audio/wav"

    def __init__(
        self,
        *,
        backend: InputBackend,
        device: int | str | None,
        sample_rates: Sequence[int] = RECORDING_SAMPLE_RATES,
        block_ms: int = BLOCK_MS,
        queue_seconds: float = QUEUE_SECONDS,
        header_refresh_s: float = HEADER_REFRESH_S,
        stall_s: float = STALL_S,
        monotonic: Callable[[], float] = time.monotonic,
        wall: Callable[[], datetime] = utc_now,
    ) -> None:
        self._backend = backend
        self._device = device
        self._rates = tuple(sample_rates)
        self._block_ms = block_ms
        self._queue: queue.Queue[tuple[int, bytes]] = queue.Queue(
            maxsize=max(1, int(queue_seconds * 1000 // block_ms)))
        self._refresh_s = header_refresh_s
        self._stall_s = stall_s
        self._monotonic = monotonic
        self._wall = wall
        self._opened: OpenedInput | None = None
        self._sink: CaptureSink | None = None
        self._writer: threading.Thread | None = None
        self._stopping = threading.Event()
        self._sample_rate = 0
        # Compteurs du callback : un seul producteur (le fil PortAudio).
        self._pending_drop = 0
        self._dropped_blocks = 0
        self._input_overflows = 0
        self._last_block = 0.0
        # Vrai une fois `stream.start()` revenu : un micro lent à démarrer (Bluetooth,
        # plusieurs secondes) n'est jamais compté comme muet avant d'avoir démarré.
        self._streaming = False
        # État du fil d'écriture.
        self._frames_written = 0
        self._gap_count = 0
        self._gap_frames = 0
        self._overflow_gaps = 0
        self._write_error: CaptureSourceError | None = None
        self._lost = False
        self._lost_lock = threading.Lock()
        self._started_at: datetime | None = None
        self._device_label = ""

    # -------------------------------------------------------------- cycle de vie

    async def start(self, sink: CaptureSink) -> None:
        await asyncio.to_thread(self._start, sink)

    def _start(self, sink: CaptureSink) -> None:
        self._sink = sink
        opened = self._backend.open(device=self._device, sample_rates=self._rates, block_ms=self._block_ms,
                                    callback=self._on_block, finished=self._on_finished)
        self._opened = opened
        self._sample_rate = opened.sample_rate
        self._device_label = opened.device_name
        try:
            # En-tête d'abord, tailles provisoires : le PCM suit à l'octet 44.
            sink.write(wav_header(sample_rate=opened.sample_rate, channels=CHANNELS, data_bytes=0))
            self._writer = threading.Thread(target=self._write_loop, name="jarvis-recording-writer", daemon=True)
            self._last_block = self._monotonic()
            self._writer.start()
            self._started_at = self._wall()
            opened.stream.start()
            # Horloge de silence repartie au démarrage effectif du flux (pas à l'ouverture).
            self._last_block = self._monotonic()
            self._streaming = True
        except BaseException:
            self._stopping.set()
            self._close_device()
            if self._writer is not None:
                self._writer.join(WRITER_JOIN_S)
            raise

    async def stop(self) -> None:
        await asyncio.to_thread(self._stop)

    def _stop(self) -> None:
        # Drapeau avant l'arrêt du flux : la fin du flux n'est alors pas une perte.
        self._stopping.set()
        failure = self._close_device()
        if self._writer is not None:
            self._writer.join(WRITER_JOIN_S)
            if self._writer.is_alive():
                raise CaptureSourceError(CaptureErrorCode.WRITE_FAILED,
                                         f"recording writer did not finish within {WRITER_JOIN_S:g} s")
        if failure is not None and not self._lost:
            raise CaptureSourceError(CaptureErrorCode.SOURCE_LOST, f"input stream did not close cleanly: {failure}")

    def _close_device(self) -> str | None:
        opened, self._opened = self._opened, None
        if opened is None:
            return None
        try:
            self._backend.close(opened)
        except Exception as exc:  # noqa: BLE001 - reported by stop() with its type (device already gone...)
            return f"{type(exc).__name__}: {str(exc)[:200]}"
        return None

    def health(self) -> SourceHealth:
        if self._lost:
            return SourceHealth(ok=False, code=CaptureErrorCode.SOURCE_LOST.value, detail="input device lost")
        if self._write_error is not None:
            return SourceHealth(ok=False, code=self._write_error.code.value, detail=str(self._write_error)[:200])
        return SourceHealth(ok=True)

    def media_info(self) -> MediaInfo:
        rate = self._sample_rate or 1
        details: dict[str, Any] = {
            "sample_rate": self._sample_rate, "channels": CHANNELS, "sample_format": "pcm_s16le",
            "audio_device": self._device_label[:200], "gap_count": self._gap_count,
            "gap_lost_ms": self._gap_frames * 1000 // rate, "input_overflows": self._input_overflows,
            "dropped_blocks": self._dropped_blocks,
        }
        if self._started_at is not None:
            details["stream_started_at"] = self._started_at.isoformat()
        return MediaInfo(duration_ms=self._frames_written * 1000 // rate, details=details)

    # -------------------------------------------------------------- fil PortAudio

    def _on_block(self, pcm: bytes, overflow: bool) -> None:
        """Copie et file, rien d'autre : jamais de disque, jamais de verrou tenu longtemps."""

        self._last_block = self._monotonic()
        if overflow:
            self._input_overflows += 1
        try:
            self._queue.put_nowait((self._pending_drop, pcm))
            self._pending_drop = 0
        except queue.Full:
            # Le plus récent est refusé (les plus anciens sont déjà de la preuve
            # en route vers le disque) ; il deviendra du silence daté + un gap.
            self._pending_drop += len(pcm) // 2
            self._dropped_blocks += 1

    def _on_finished(self) -> None:
        if not self._stopping.is_set():
            self._report_lost("the input stream stopped (device removed or driver failure)")

    # -------------------------------------------------------------- fil d'écriture

    def _write_loop(self) -> None:
        next_refresh = self._monotonic() + self._refresh_s
        reported_overflows = 0
        while True:
            try:
                dropped, pcm = self._queue.get(timeout=0.1)
            except queue.Empty:
                if self._stopping.is_set():
                    break
                self._check_stall()
            else:
                if dropped:
                    self._pad(dropped, "queue_overflow")
                self._write(pcm)
            if self._input_overflows != reported_overflows:
                reported_overflows = self._input_overflows
                self._overflow_gaps += 1
                self._gap_count += 1
                self._gap("input_overflow", None)
            if self._monotonic() >= next_refresh:
                next_refresh = self._monotonic() + self._refresh_s
                self._refresh_header()
        # Le flux est fermé : plus aucun callback. Un débordement resté en compte
        # n'a pas eu de bloc après lui : son silence va en fin de fichier.
        if self._pending_drop:
            dropped, self._pending_drop = self._pending_drop, 0
            self._pad(dropped, "queue_overflow")
        self._refresh_header()

    def _write(self, data: bytes) -> None:
        if self._write_error is not None or self._sink is None:
            return  # le propriétaire arrête la capture ; la file se vide sans écrire
        try:
            self._sink.write(data)
            self._frames_written += len(data) // 2
        except CaptureSourceError as exc:
            self._write_error = exc

    def _pad(self, frames: int, reason: str) -> None:
        self._gap_count += 1
        self._gap_frames += frames
        remaining = frames * 2
        chunk = bytes(min(remaining, 64_000))
        while remaining > 0 and self._write_error is None:
            size = min(remaining, len(chunk))
            self._write(chunk[:size])
            remaining -= size
        self._gap(reason, frames * 1000 // (self._sample_rate or 1))

    def _gap(self, reason: str, lost_ms: int | None) -> None:
        if self._sink is not None:
            self._sink.gap(reason=reason, lost_ms=lost_ms)

    def _refresh_header(self) -> None:
        if self._write_error is not None or self._sink is None:
            return
        try:
            for offset, data in size_fields(self._frames_written * 2):
                self._sink.write_at(offset, data)
            self._sink.sync()
        except CaptureSourceError as exc:
            self._write_error = exc

    def _check_stall(self) -> None:
        if not self._streaming:
            return
        if self._monotonic() - self._last_block > self._stall_s:
            self._report_lost(f"no audio from the input device for {self._stall_s:g} s")

    def _report_lost(self, reason: str) -> None:
        with self._lost_lock:
            if self._lost:
                return
            self._lost = True
        if self._sink is not None:
            self._sink.lost(CaptureErrorCode.SOURCE_LOST, reason)


# ------------------------------------------------------------------ registre


def device_from_token(token: str, configured: Callable[[], int | str | None]) -> int | str | None:
    """`default` -> l'appareil choisi pour Voice (réglages) ; un nombre -> index PortAudio."""

    if token == DEFAULT_DEVICE:
        return configured()
    return int(token) if token.isdigit() else token


class AudioRecordingSources:
    """`CaptureSourceRegistry` de production : micro pour `audio`/`continuous`, le reste délégué ou refusé.

    `others` : registre des autres familles (écran, Slice 07) ; sans lui, refus
    `unsupported_source` comme `NoCaptureSources`.
    """

    def __init__(self, *, configured_device: Callable[[], int | str | None],
                 backend_factory: Callable[[], InputBackend] = SoundDeviceInput,
                 others: CaptureSourceRegistry | None = None, **source_options: Any) -> None:
        self._configured = configured_device
        self._backend_factory = backend_factory
        self._others = others
        self._options = source_options

    def _is_microphone(self, channel: CaptureChannel, source: str | None) -> bool:
        return CaptureChannel(channel) is CaptureChannel.AUDIO and source in (None, MICROPHONE_SOURCE)

    def _refuse(self, channel: CaptureChannel, source: str | None) -> CaptureError:
        return CaptureError(CaptureErrorCode.UNSUPPORTED_SOURCE,
                            f"no capture source {source or 'default'!r} for channel {CaptureChannel(channel).value}")

    def continuous(self, channel: CaptureChannel, *, source: str | None, device: str) -> CaptureSource:
        if self._is_microphone(channel, source):
            try:
                resolved = device_from_token(device, self._configured)
            except Exception as exc:  # noqa: BLE001 - unreadable setting: refused with its cause
                raise CaptureError(CaptureErrorCode.SOURCE_UNAVAILABLE,
                                   f"configured input device unreadable: {type(exc).__name__}: {exc}"[:300]) from exc
            return MicrophoneRecordingSource(backend=self._backend_factory(), device=resolved, **self._options)
        if self._others is not None:
            return self._others.continuous(channel, source=source, device=device)
        raise self._refuse(channel, source)

    def one_shot(self, channel: CaptureChannel, *, source: str | None, device: str) -> OneShotSource:
        if self._others is not None:
            return self._others.one_shot(channel, source=source, device=device)
        raise self._refuse(channel, source)

    def source_name(self, channel: CaptureChannel, mode: CaptureMode, source: str | None) -> str:
        if mode is CaptureMode.CONTINUOUS and self._is_microphone(channel, source):
            return MICROPHONE_SOURCE
        if self._others is not None:
            return self._others.source_name(channel, mode, source)
        raise self._refuse(channel, source)


# ------------------------------------------------------------------ réparation


class WavCaptureRepair:
    """`CaptureRepair` du canal audio : en-tête WAV d'un enregistrement interrompu par la mort de Core.

    Tailles RIFF et `data` recalculées depuis la longueur réelle du fichier ;
    un échantillon partiel en fin de fichier est retiré (troncature en place,
    jamais de création, de renommage ni de suppression). Un fichier dont
    l'en-tête est incomplet ou n'est pas du PCM16 est laissé tel quel
    (`repaired=False`, raison dans `detail`).
    """

    def repair(self, target: RepairTarget) -> RepairOutcome:
        if target.partial_bytes:
            path, size = target.partial_path, target.partial_bytes
        elif target.final_bytes:
            path, size = target.final_path, target.final_bytes
        else:
            return RepairOutcome(repaired=False, detail="no_bytes")
        with open(path, "r+b") as handle:
            prefix = handle.read(4096)
            try:
                fmt = parse_wav_header(prefix)
            except WavFormatError as exc:
                return RepairOutcome(repaired=False, detail=f"not_repaired: {exc}"[:200])
            if size < fmt.data_offset:
                return RepairOutcome(repaired=False, detail="header_incomplete")
            data = fmt.data_bytes_on_disk(size)
            end = fmt.data_offset + data
            if end < size:
                handle.truncate(end)
            handle.seek(4)
            handle.write(struct.pack("<I", min(end - 8, 0xFFFFFFFF)))
            handle.seek(fmt.data_offset - 4)
            handle.write(struct.pack("<I", min(data, 0xFFFFFFFF)))
            handle.flush()
            os.fsync(handle.fileno())
        frames = fmt.frames_in(data)
        return RepairOutcome(repaired=True, duration_ms=fmt.ms_of(frames),
                             detail=f"wav_sizes_rewritten data_bytes={data} trimmed_bytes={size - end}")


__all__ = [
    "AudioRecordingSources", "HEADER_BYTES", "InputBackend", "MICROPHONE_SOURCE", "MicrophoneRecordingSource",
    "OpenedInput", "RECORDING_SAMPLE_RATES", "SoundDeviceInput", "WavCaptureRepair", "device_from_token",
    "source_error",
]

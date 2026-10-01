"""Sources et stockage de capture factices (handoff session-context-recording, Slice 05).

Pour tester le `CaptureService` sans aucun appareil : trames déterministes
poussées à la main (`push`), perte de source scriptée (`lose`, `lose_after`),
refus d'autorisation ou appareil absent (`refuse`), démarrage et arrêt lents
(portes `asyncio.Event`), trous datés (`drop`). `FailingPayloads` enveloppe
un vrai `ArtifactPayloadStore` et simule disque plein, écriture refusée,
dossier refusé ou finalisation refusée, avec la vraie chaîne d'erreur
(`ArtifactPayloadError` causée par un `OSError`).

Jamais câblé en production : `v2_app` n'installe aucune source par défaut
(`NoCaptureSources`), les adaptateurs réels arrivent aux Slices 06 (micro) et
07 (bureau). Contrat : `docs/capture.md`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
import errno
import os
from pathlib import Path

from jarvis.domain.capture import CaptureChannel, CaptureError, CaptureErrorCode, CaptureMode
from jarvis.ports.artifacts import PAYLOAD_FAILED, ArtifactPayloadError, ArtifactPayloadStore, PayloadInfo
from jarvis.ports.capture import CaptureSink, CaptureSourceError, MediaInfo, OneShotResult, SourceHealth

FAKE_SOURCE = "fake"
#: 10 ms de PCM16 mono à 8 kHz : une trame déterministe.
DEFAULT_FRAME = bytes(range(160))
PNG_1X1 = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
           b"\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


class FakeCaptureSource:
    """Source continue factice. Les trames n'arrivent que par `push` : aucun minuteur, aucun hasard."""

    def __init__(
        self,
        *,
        frame: bytes = DEFAULT_FRAME,
        initial_frames: int = 1,
        tail_frames: int = 0,
        refuse: CaptureErrorCode | None = None,
        start_gate: asyncio.Event | None = None,
        stop_gate: asyncio.Event | None = None,
        lose_after: int | None = None,
        payload_name: str = "source.bin",
        mime_type: str = "application/octet-stream",
        frame_ms: int = 10,
    ) -> None:
        self.payload_name = payload_name
        self.mime_type = mime_type
        self.frame = frame
        self.initial_frames = initial_frames
        self.tail_frames = tail_frames
        self.refuse = refuse
        self.start_gate = start_gate
        self.stop_gate = stop_gate
        self.lose_after = lose_after
        self.frame_ms = frame_ms
        self.frames = 0
        self.start_calls = 0
        self.stop_calls = 0
        self.running = False
        self.write_error: CaptureErrorCode | None = None
        self._sink: CaptureSink | None = None

    async def start(self, sink: CaptureSink) -> None:
        self.start_calls += 1
        if self.start_gate is not None:
            await self.start_gate.wait()
        if self.refuse is not None:
            raise CaptureSourceError(self.refuse, f"fake source refused: {self.refuse.value}")
        self._sink = sink
        self.running = True
        self.push(self.initial_frames)

    def push(self, count: int = 1) -> int:
        """Écrit `count` trames (s'arrête à la perte scriptée ou au premier refus du sink)."""

        written = 0
        for _ in range(count):
            if not self.running or self._sink is None:
                break
            if self.lose_after is not None and self.frames >= self.lose_after:
                self.lose()
                break
            try:
                self._sink.write(self.frame)
            except CaptureSourceError as exc:
                self.write_error = exc.code
                self.running = False
                break
            self.frames += 1
            written += 1
        return written

    def drop(self, *, reason: str = "queue_overflow", lost_ms: int | None = 50) -> None:
        assert self._sink is not None
        self._sink.gap(reason=reason, lost_ms=lost_ms)

    def lose(self, code: CaptureErrorCode = CaptureErrorCode.SOURCE_LOST) -> None:
        self.running = False
        assert self._sink is not None
        self._sink.lost(code, "fake source lost")

    async def stop(self) -> None:
        self.stop_calls += 1
        if self.stop_gate is not None:
            await self.stop_gate.wait()
        if self.running:
            self.push(self.tail_frames)
        self.running = False

    def health(self) -> SourceHealth:
        return SourceHealth(ok=self.running and self.write_error is None,
                            code=None if self.write_error is None else self.write_error.value)

    def media_info(self) -> MediaInfo:
        return MediaInfo(duration_ms=self.frames * self.frame_ms)


class FakeOneShotSource:
    payload_name = "screenshot.png"
    mime_type = "image/png"

    def __init__(self, *, data: bytes = PNG_1X1, width: int = 1, height: int = 1,
                 refuse: CaptureErrorCode | None = None, gate: asyncio.Event | None = None) -> None:
        self.data = data
        self.width = width
        self.height = height
        self.refuse = refuse
        self.gate = gate
        self.calls = 0

    async def capture(self) -> OneShotResult:
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.refuse is not None:
            raise CaptureSourceError(self.refuse, f"fake one-shot refused: {self.refuse.value}")
        return OneShotResult(self.data, self.width, self.height)


class FakeCaptureSources:
    """`CaptureSourceRegistry` factice : une fabrique par canal ; chaque source créée est gardée."""

    def __init__(
        self,
        continuous: Mapping[CaptureChannel, Callable[[], FakeCaptureSource]] | None = None,
        one_shot: Mapping[CaptureChannel, Callable[[], FakeOneShotSource]] | None = None,
        *,
        platform_supported: bool = True,
    ) -> None:
        self._continuous = dict(continuous or {})
        self._one_shot = dict(one_shot or {})
        self.platform_supported = platform_supported
        self.created: list[FakeCaptureSource | FakeOneShotSource] = []

    def _check(self, channel: CaptureChannel, source: str | None, factories: Mapping) -> Callable:
        if not self.platform_supported:
            raise CaptureError(CaptureErrorCode.UNSUPPORTED_PLATFORM, "fake platform has no capture support")
        if source not in (None, FAKE_SOURCE) or channel not in factories:
            raise CaptureError(CaptureErrorCode.UNSUPPORTED_SOURCE, f"no fake source {source!r} for {channel}")
        return factories[channel]

    def continuous(self, channel: CaptureChannel, *, source: str | None, device: str) -> FakeCaptureSource:
        made = self._check(channel, source, self._continuous)()
        self.created.append(made)
        return made

    def one_shot(self, channel: CaptureChannel, *, source: str | None, device: str) -> FakeOneShotSource:
        made = self._check(channel, source, self._one_shot)()
        self.created.append(made)
        return made

    def source_name(self, channel: CaptureChannel, mode: CaptureMode, source: str | None) -> str:
        return FAKE_SOURCE


# ------------------------------------------------------------------ stockage défaillant


def _os_error(code: int) -> OSError:
    return OSError(code, os.strerror(code))


class _FailingSpool:
    def __init__(self, inner, owner: FailingPayloads) -> None:  # noqa: ANN001 - ArtifactSpool
        self._inner = inner
        self._owner = owner

    @property
    def size(self) -> int:
        return self._inner.size

    def _fail(self, code: int, what: str) -> ArtifactPayloadError:
        cause = _os_error(code)
        error = ArtifactPayloadError(PAYLOAD_FAILED, Path("fake"), f"{what}: {type(cause).__name__}: {cause}")
        error.__cause__ = cause
        return error

    def write(self, data: bytes) -> int:
        limit = self._owner.fail_write_after
        if limit is not None and self._inner.size + len(data) > limit:
            raise self._fail(self._owner.write_errno, "write")
        return self._inner.write(data)

    def write_at(self, offset: int, data: bytes) -> None:
        self._inner.write_at(offset, data)

    def sync(self) -> None:
        self._inner.sync()

    def finalize(self) -> int:
        if self._owner.fail_finalize is not None:
            self._inner.close()
            raise self._fail(self._owner.fail_finalize, "finalize")
        return self._inner.finalize()

    def close(self) -> None:
        self._inner.close()


class FailingPayloads:
    """`ArtifactPayloadStore` qui échoue sur commande (disque plein par défaut), sinon délègue."""

    def __init__(self, inner: ArtifactPayloadStore, *, fail_open: int | None = None,
                 fail_write_after: int | None = None, write_errno: int = errno.ENOSPC,
                 fail_finalize: int | None = None) -> None:
        self._inner = inner
        self.fail_open = fail_open
        self.fail_write_after = fail_write_after
        self.write_errno = write_errno
        self.fail_finalize = fail_finalize

    def root(self) -> Path:
        return self._inner.root()

    def path_of(self, payload_ref: str) -> Path:
        return self._inner.path_of(payload_ref)

    def ensure_folder(self, artifact_id: str) -> Path:
        return self._inner.ensure_folder(artifact_id)

    def open_spool(self, artifact_id: str, name: str):  # noqa: ANN201 - ArtifactSpool
        if self.fail_open is not None:
            error = ArtifactPayloadError(PAYLOAD_FAILED, Path("fake"), "open refused")
            error.__cause__ = _os_error(self.fail_open)
            raise error
        return _FailingSpool(self._inner.open_spool(artifact_id, name), self)

    def write_payload(self, artifact_id: str, name: str, data: bytes) -> int:
        if self.fail_write_after is not None and len(data) > self.fail_write_after:
            error = ArtifactPayloadError(PAYLOAD_FAILED, Path("fake"), "write refused")
            error.__cause__ = _os_error(self.write_errno)
            raise error
        return self._inner.write_payload(artifact_id, name, data)

    def inspect(self, artifact_id: str, name: str) -> PayloadInfo:
        return self._inner.inspect(artifact_id, name)

    def promote_partial(self, artifact_id: str, name: str) -> int:
        return self._inner.promote_partial(artifact_id, name)

    def remove_folder(self, artifact_id: str) -> bool:
        return self._inner.remove_folder(artifact_id)

"""Chaîne réelle pour la Slice 09 (session-context-recording) : Core (sources de capture factices) →
`LocalProtocolServer` → `CoreSessionTransport` → vrai `ControlCenter` (aiohttp `TestServer`).

Aucun micro, aucun écran, aucun réseau : l'audio est un WAV PCM16 déterministe
écrit d'un coup par `FakeCaptureSource`, la transcription un fournisseur
scripté (`ScriptedSTT`), l'écran une source factice (« vidéo » opaque) et une
capture d'écran PNG 1×1. Tout vit sous `tmp_path`.
"""

from __future__ import annotations

import array
import asyncio
import json
import math
from pathlib import Path
import socket
import time

from aiohttp.test_utils import TestClient, TestServer

from jarvis.adapters.fake_capture import FakeCaptureSource, FakeCaptureSources, FakeOneShotSource
from jarvis.audio.wav_pcm import pcm16_wav
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.capture import CaptureChannel
from jarvis.domain.results import TranscriptionResult
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.core_sessions import CoreSessionTransport
from tests.fakes.remotion_authoring import ScriptedCompiler

TOKEN = "c" * 48
RATE = 16_000


def _pcm(ms: int, amplitude: int) -> bytes:
    count = RATE * ms // 1000
    return array.array("h", [int(amplitude * math.sin(2 * math.pi * 180 * i / RATE)) for i in range(count)]).tobytes()


#: Trois phrases : parole 1,0-2,5 s, 3,5-5,0 s et 6,0-7,5 s.
THREE_PHRASES_WAV = pcm16_wav(_pcm(1000, 15) + _pcm(1500, 9000) + _pcm(1000, 15) + _pcm(1500, 9000)
                              + _pcm(1000, 15) + _pcm(1500, 9000) + _pcm(1000, 15), sample_rate=RATE)


class ScriptedSTT:
    """Fournisseur de transcription scripté : « phrase N » à chaque segment."""

    def __init__(self) -> None:
        self.calls = 0

    async def transcribe(self, audio) -> TranscriptionResult:  # noqa: ANN001
        self.calls += 1
        return TranscriptionResult(text=f"phrase {self.calls}", duration_ms=5, provider="fake", model="fake-stt")


def fake_sources() -> FakeCaptureSources:
    return FakeCaptureSources(
        continuous={
            CaptureChannel.AUDIO: lambda: FakeCaptureSource(frame=THREE_PHRASES_WAV, payload_name="source.wav",
                                                            mime_type="audio/wav"),
            CaptureChannel.SCREEN: lambda: FakeCaptureSource(payload_name="screen.mp4", mime_type="video/mp4"),
        },
        one_shot={CaptureChannel.SCREEN: lambda: FakeOneShotSource()},
    )


async def until(predicate, timeout: float = 10.0) -> None:  # noqa: ANN001
    deadline = time.monotonic() + timeout
    while not await predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.05)


class CaptureStack:
    """`async with CaptureStack(tmp_path) as stack` : `stack.core`, `stack.core_url`, `stack.cc` (TestClient)."""

    def __init__(self, tmp_path: Path, *, stt: ScriptedSTT | None = None, transcription: bool = True) -> None:
        self.tmp_path = tmp_path
        self.stt = stt or ScriptedSTT()
        self.transcription = transcription

    async def __aenter__(self) -> "CaptureStack":
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.data_root = self.tmp_path / "data"
        self.core = JarvisCoreApplication(
            data_root=self.data_root, capture_sources=fake_sources(),
            recording_transcription=(lambda: self.stt) if self.transcription else None,
            authoring_compiler=ScriptedCompiler())   # Remotion Slice 15: an agent draft is compiled before it is written; no Node here
        await self.core.start()
        self.core.transcripts._poll_s = 0.05  # rattrapage rapide en test
        self.server = LocalProtocolServer(self.core, host="127.0.0.1", port=port, token=TOKEN)
        await self.server.start()
        self.core_url = f"http://127.0.0.1:{port}"
        token_file = self.tmp_path / "core.token"
        token_file.write_text(TOKEN, encoding="utf-8")
        self.sessions = CoreSessionTransport(host="127.0.0.1", port=port, token_file=token_file)
        runtime = self.tmp_path / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        self.center = ControlCenter(runtime_root=runtime, project_root=self.tmp_path)
        self.center.sessions = self.sessions
        self.cc = TestClient(TestServer(self.center._app))
        await self.cc.start_server()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.cc.close()
        await self.sessions.close()
        await self.server.stop()
        await self.core.stop()

    @property
    def cc_port(self) -> int:
        return self.cc.server.port

    async def call(self, method: str, path: str, **kwargs) -> tuple[int, object, str]:
        """Requête au Control Center (Host de bouclage, sans Origin : comme le serveur MCP)."""

        response = await self.cc.request(method, path, **kwargs)
        text = await response.text()
        try:
            body = json.loads(text)
        except ValueError:
            body = None
        return response.status, body, text

    def trace(self) -> list[dict]:
        path = self.tmp_path / "runtime" / "trace.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

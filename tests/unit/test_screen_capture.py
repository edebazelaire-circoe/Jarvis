"""Capture d'écran et enregistrement d'écran du bureau (handoff session-context-recording, Slice 07).

Contrat : `docs/capture.md` › *Screen capture*. Aucun vrai écran ni vrai
encodeur dans le cas général : `FakeDisplays` remplace GDI, `FakeEncoder`
joue ffmpeg (fragments MP4 synthétiques écrits dans le `.partial`, sortie,
arrêt lent, plantage scénarisés) ; spool et base réels sous `tmp_path`.

Les tests marqués `real_ffmpeg` utilisent le binaire de l'extra `capture`
avec une **mire synthétique** (`lavfi testsrc`, jamais le bureau) ; ils sont
sautés quand ffmpeg n'est pas installé. Le test d'orphelin utilise un vrai
processus enfant (Windows seulement), sans ffmpeg.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import io
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
import zlib

import pytest

from jarvis.adapters.artifact_payloads import FileArtifactPayloads
from jarvis.adapters.screen_capture import (
    DESKTOP_SOURCE, FfmpegProcess, FragmentedMp4Repair, ScreenCaptureSources, extract_frame, find_ffmpeg,
    probe_duration_ms, recording_args,
)
from jarvis.adapters.sqlite_artifacts import SQLiteArtifactRepository
from jarvis.adapters.sqlite_captures import SQLiteCaptureRepository
from jarvis.adapters.sqlite_session_activity import SQLiteActivityLedger
from jarvis.adapters.sqlite_session_context import SQLiteContextRepository
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.adapters.sqlite_workspace_board import SQLiteBoardRepository
from jarvis.adapters.windows_display import Display, Frame, order_displays, parse_display_token, pick_display
from jarvis.core.artifact_service import ArtifactService
from jarvis.core.capture_service import CaptureAssociation, CaptureService
from jarvis.domain.artifacts import ArtifactKind, ArtifactState
from jarvis.domain.capture import CaptureChannel, CaptureError, CaptureErrorCode, CaptureMode, CaptureState
from jarvis.domain.session_activity import ActivityKind, ActivityQuery
from jarvis.domain.session_context import create_context
from jarvis.domain.v2 import utc_now
from jarvis.domain.workspace_board import default_board, open_session
from jarvis.media.fmp4 import scan
from jarvis.media.png import PNG_SIGNATURE, bgra_to_png, png_size
from jarvis.ports.capture import CaptureSourceError, RepairTarget

SCREEN = CaptureChannel.SCREEN
FFMPEG = find_ffmpeg()
real_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg absent: install the 'capture' extra to run")
windows_only = pytest.mark.skipif(os.name != "nt", reason="Job Object containment is Windows-only")


async def until(predicate, timeout: float = 3.0) -> None:  # noqa: ANN001
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.005)


# ------------------------------------------------------------------ MP4 synthétique


def box(kind: bytes, payload: bytes = b"") -> bytes:
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


HEADER = box(b"ftyp", b"isom\x00\x00\x02\x00") + box(b"moov", b"\x00" * 24)
FRAGMENT = box(b"moof", b"\x00" * 16) + box(b"mdat", b"\x07" * 120)


def test_scan_counts_complete_fragments_and_finds_the_torn_tail():
    data = HEADER + FRAGMENT + FRAGMENT + box(b"moof", b"\x00" * 16) + box(b"mdat", b"\x07" * 120)[:50]
    found = scan(io.BytesIO(data), len(data))
    assert (found.usable, found.fragments) == (True, 2)
    assert found.readable_end == len(HEADER + FRAGMENT * 2) and found.torn_bytes == len(data) - found.readable_end


def test_scan_handles_64_bit_sizes_and_refuses_headers_without_fragments():
    large = struct.pack(">I4sQ", 1, b"mdat", 16 + 10) + b"\x00" * 10
    data = HEADER + box(b"moof", b"\x00" * 16) + large
    assert scan(io.BytesIO(data), len(data)).fragments == 1
    assert not scan(io.BytesIO(HEADER), len(HEADER)).usable
    no_moov = box(b"ftyp", b"isom") + FRAGMENT
    assert not scan(io.BytesIO(no_moov), len(no_moov)).usable
    broken = HEADER + struct.pack(">I4s", 3, b"moof")
    assert scan(io.BytesIO(broken), len(broken)).problem == "bad_box_size:moof"


# ------------------------------------------------------------------ PNG


def test_png_is_valid_rgb_with_the_right_size_and_channel_order():
    width, height = 3, 2
    bgra = bytes([10, 20, 30, 255] * (width * height))  # B=10 G=20 R=30
    data = bgra_to_png(width, height, bgra)
    assert data.startswith(PNG_SIGNATURE) and png_size(data) == (3, 2)
    offset, chunks = 8, {}
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset:offset + 4])
        kind, body = data[offset + 4:offset + 8], data[offset + 8:offset + 8 + length]
        (crc,) = struct.unpack(">I", data[offset + 8 + length:offset + 12 + length])
        assert crc == zlib.crc32(kind + body) & 0xFFFFFFFF
        chunks[kind] = body
        offset += 12 + length
    raw = zlib.decompress(chunks[b"IDAT"])
    assert raw == (b"\x00" + bytes([30, 20, 10]) * width) * height
    assert list(chunks) == [b"IHDR", b"IDAT", b"IEND"]


def test_png_refuses_a_buffer_of_the_wrong_size():
    with pytest.raises(ValueError):
        bgra_to_png(2, 2, b"\x00" * 15)
    with pytest.raises(ValueError):
        png_size(b"GIF89a")


# ------------------------------------------------------------------ écrans


def display(name: str = "display1", *, left: int = 0, width: int = 4, height: int = 2, primary: bool = True,
            dpi: int = 120) -> Display:
    return Display(name=name, device=f"\\\\.\\{name.upper()}", left=left, top=0, width=width, height=height,
                   primary=primary, dpi=dpi)


def test_displays_are_named_primary_first_then_left_to_right():
    ordered = order_displays([("\\\\.\\DISPLAY5", 1920, 0, 1920, 1080, False, 96),
                              ("\\\\.\\DISPLAY3", -1280, 0, 1280, 1024, False, 96),
                              ("\\\\.\\DISPLAY1", 0, 0, 1920, 1080, True, 120)])
    assert [(d.name, d.device[-8:], d.scale) for d in ordered] == [
        ("display1", "DISPLAY1", 1.25), ("display2", "DISPLAY3", 1.0), ("display3", "DISPLAY5", 1.0)]
    assert parse_display_token("default") is None and parse_display_token("display2") == 2
    with pytest.raises(ValueError):
        parse_display_token("monitor1")
    assert pick_display(ordered, "default").name == "display1"
    with pytest.raises(CaptureSourceError) as missing:
        pick_display(ordered, "display4")
    assert missing.value.code is CaptureErrorCode.SOURCE_UNAVAILABLE


class FakeDisplays:
    def __init__(self, displays: list[Display] | None = None, *, grab_error: CaptureSourceError | None = None):
        self.current = list(displays or [display()])
        self.grab_error = grab_error

    def displays(self) -> list[Display]:
        return list(self.current)

    def grab(self, token: str) -> Frame:
        if self.grab_error is not None:
            raise self.grab_error
        chosen = pick_display(self.current, token)
        return Frame(chosen, chosen.width, chosen.height, bytes([1, 2, 3, 255]) * (chosen.width * chosen.height))


# ------------------------------------------------------------------ faux encodeur


@dataclass
class Script:
    write_header: bool = True
    exit_before_ready: int | None = None
    ignore_q: bool = False
    stop_code: int = 0
    stderr: list[str] = field(default_factory=lambda: ["[gdigrab] warning"])


class FakeEncoder:
    """`EncoderProcess` scénarisé ; écrit de vraies boîtes MP4 dans le chemin reçu (dernier argument)."""

    def __init__(self, args, script: Script) -> None:  # noqa: ANN001
        self.args = list(args)
        self.path = Path(self.args[-1])
        self.script = script
        self.code: int | None = script.exit_before_ready
        self.stop_requests = 0
        self.killed = False
        self.closed = False
        if script.write_header and script.exit_before_ready is None:
            with open(self.path, "wb") as handle:  # ffmpeg -y : tronque puis écrit
                handle.write(HEADER)

    def fragment(self, count: int = 1) -> None:
        with open(self.path, "ab") as handle:
            handle.write(FRAGMENT * count)

    def exit(self, code: int) -> None:
        self.code = code

    def poll(self) -> int | None:
        return self.code

    def request_stop(self) -> None:
        self.stop_requests += 1
        if self.code is None and not self.script.ignore_q:
            self.fragment()
            self.code = self.script.stop_code

    def wait(self, timeout_s: float) -> int | None:
        deadline = time.monotonic() + timeout_s
        while self.code is None and time.monotonic() < deadline:
            time.sleep(0.01)
        return self.code

    def kill(self) -> None:
        self.killed = True
        self.code = 1

    def stderr_tail(self) -> list[str]:
        return list(self.script.stderr)

    def close(self) -> None:
        self.closed = True


@dataclass
class Env:
    root: Path
    state: SQLiteStateRepository
    artifacts: ArtifactService
    service: CaptureService
    displays: FakeDisplays
    encoders: list[FakeEncoder]

    async def aclose(self) -> None:
        await self.service.close()
        await self.state.close()

    async def events(self, *kinds: ActivityKind):
        return await self.artifacts.activity(ActivityQuery(kinds=kinds, limit=500))


async def make_env(root: Path, *, script: Script | None = None, displays: FakeDisplays | None = None,
                   repairs=None, seed: bool = True, ffmpeg: str | None = "ffmpeg.exe",  # noqa: ANN001
                   **options) -> Env:  # noqa: ANN003
    state = SQLiteStateRepository(root / "state" / "jarvis.sqlite3")
    await state.initialize()
    artifacts = ArtifactService(SQLiteArtifactRepository(state), SQLiteActivityLedger(state),
                                FileArtifactPayloads(root))
    if seed:
        boards, contexts = SQLiteBoardRepository(state), SQLiteContextRepository(state)
        board = default_board(now=utc_now())
        await boards.save_board(board)
        session = open_session(board, now=utc_now())
        await boards.save_session(session)
        transition = create_context(session, (), now=utc_now())
        await contexts.commit_contexts(transition.changed)
        association = CaptureAssociation(session.jarvis_session_id, transition.active.context_id)
    else:
        session = await SQLiteBoardRepository(state).current_session()
        contexts = await SQLiteContextRepository(state).list_contexts(session.jarvis_session_id)
        association = CaptureAssociation(session.jarvis_session_id, contexts[-1].context_id)
    fake = displays or FakeDisplays()
    encoders: list[FakeEncoder] = []

    def spawn(args):  # noqa: ANN001, ANN202
        made = FakeEncoder(args, script or Script())
        encoders.append(made)
        return made

    async def associate() -> CaptureAssociation:
        return association

    settings = {"spawn": spawn, "probe": lambda path: 4800, "ready_timeout_s": 1.0, "stop_grace_s": 0.3,
                "kill_wait_s": 0.3, "stall_s": 30.0, "watch_interval_s": 0.02, "display_check_s": 0.05, **options}
    sources = ScreenCaptureSources(displays_factory=lambda: fake, ffmpeg_locator=lambda: ffmpeg, platform_name="nt",
                                   **settings)
    service = CaptureService(SQLiteCaptureRepository(state), artifacts, sources, association=associate,
                             repairs=repairs, start_timeout_s=3.0, stop_timeout_s=3.0)
    return Env(root, state, artifacts, service, fake, encoders)


def payload(env: Env, artifact_id: str, name: str) -> Path:
    return env.root / "artifacts" / artifact_id / name


# ------------------------------------------------------------------ registre


def test_the_registry_serves_desktop_on_screen_only_and_says_why_it_refuses():
    sources = ScreenCaptureSources(displays_factory=FakeDisplays, ffmpeg_locator=lambda: None, platform_name="nt")
    assert sources.source_name(SCREEN, CaptureMode.ONE_SHOT, None) == DESKTOP_SOURCE
    for channel, source in ((CaptureChannel.AUDIO, None), (SCREEN, "window")):
        with pytest.raises(CaptureError) as refused:
            sources.one_shot(channel, source=source, device="default")
        assert refused.value.code is CaptureErrorCode.UNSUPPORTED_SOURCE
    with pytest.raises(CaptureError) as invalid:
        sources.one_shot(SCREEN, source=None, device="monitor-2")
    assert invalid.value.code is CaptureErrorCode.INVALID_CAPTURE
    with pytest.raises(CaptureError) as no_ffmpeg:
        sources.continuous(SCREEN, source=None, device="default")
    assert no_ffmpeg.value.code is CaptureErrorCode.SOURCE_UNAVAILABLE and "capture" in str(no_ffmpeg.value)
    elsewhere = ScreenCaptureSources(displays_factory=FakeDisplays, ffmpeg_locator=lambda: "ff", platform_name="posix")
    with pytest.raises(CaptureError) as platform:
        elsewhere.one_shot(SCREEN, source=None, device="default")
    assert platform.value.code is CaptureErrorCode.UNSUPPORTED_PLATFORM


def test_find_ffmpeg_honours_the_explicit_setting(tmp_path, monkeypatch):
    exe = tmp_path / "ffmpeg.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv("JARVIS_FFMPEG_EXE", str(exe))
    assert find_ffmpeg() == str(exe)
    monkeypatch.setenv("JARVIS_FFMPEG_EXE", str(tmp_path / "missing.exe"))
    assert find_ffmpeg() is None


def test_recording_args_are_explicit_and_bounded_to_the_display(tmp_path):
    args = recording_args("ff", display("display2", left=1920, width=1919, height=1080, primary=False),
                          tmp_path / "screen.mp4.partial", fps=5)
    joined = " ".join(args)
    assert "-f gdigrab" in joined and "-offset_x 1920" in joined and "-video_size 1919x1080" in joined
    assert "-c:v libx264" in joined and "-tune zerolatency" in joined and "-g 50" in joined
    assert "+frag_keyframe+empty_moov+default_base_moof" in joined and "-frag_duration 1000000" in joined
    assert args[-3:] == ["mp4", "-y", str(tmp_path / "screen.mp4.partial")] and args[-4] == "-f"


# ------------------------------------------------------------------ capture d'écran


async def test_a_screenshot_is_a_complete_png_artifact_with_display_facts(tmp_path):
    env = await make_env(tmp_path, displays=FakeDisplays([display(), display("display2", left=4, primary=False,
                                                                             dpi=96, width=6, height=3)]))
    try:
        record = await env.service.screenshot()
        assert (record.state, record.mode, record.source) == (CaptureState.COMPLETE, CaptureMode.ONE_SHOT, "desktop")
        artifact = await env.artifacts.get(record.artifact_id)
        assert (artifact.kind, artifact.state, artifact.mime_type) == (ArtifactKind.SCREENSHOT, ArtifactState.COMPLETE,
                                                                       "image/png")
        assert (artifact.width, artifact.height) == (4, 2)
        meta = artifact.metadata
        assert (meta["display"], meta["dpi"], meta["dpi_scale"], meta["display_primary"]) == ("display1", 120, 1.25,
                                                                                               True)
        assert meta["capture_backend"] == "gdi_bitblt" and meta["captured_at"].endswith("+00:00")
        data = payload(env, record.artifact_id, "screenshot.png").read_bytes()
        assert png_size(data) == (4, 2) and artifact.size_bytes == len(data)

        second = await env.service.screenshot(_options(device="display2"))
        other = await env.artifacts.get(second.artifact_id)
        assert (other.width, other.height, other.metadata["display"]) == (6, 3, "display2")
    finally:
        await env.aclose()


def _options(**values):  # noqa: ANN003, ANN202
    from jarvis.core.capture_service import CaptureOptions

    return CaptureOptions(**values)


@pytest.mark.parametrize("code", [CaptureErrorCode.PERMISSION_DENIED, CaptureErrorCode.SOURCE_UNAVAILABLE])
async def test_a_refused_screenshot_fails_with_its_stable_code(tmp_path, code):
    env = await make_env(tmp_path, displays=FakeDisplays(grab_error=CaptureSourceError(code, "BitBlt refused")))
    try:
        with pytest.raises(CaptureError) as refused:
            await env.service.screenshot()
        assert refused.value.code is code
        record = await env.service.get(refused.value.capture_id)
        artifact = await env.artifacts.get(record.artifact_id)
        assert (record.state, record.error_code, artifact.state) == (CaptureState.FAILED, code.value,
                                                                     ArtifactState.FAILED)
    finally:
        await env.aclose()


async def test_a_missing_display_is_source_unavailable(tmp_path):
    env = await make_env(tmp_path)
    try:
        with pytest.raises(CaptureError) as refused:
            await env.service.screenshot(_options(device="display3"))
        assert refused.value.code is CaptureErrorCode.SOURCE_UNAVAILABLE
    finally:
        await env.aclose()


# ------------------------------------------------------------------ enregistrement


async def test_a_recording_writes_the_spool_through_the_encoder_and_finalizes_complete(tmp_path):
    env = await make_env(tmp_path)
    try:
        record = await env.service.start(SCREEN)
        encoder = env.encoders[-1]
        assert encoder.path == payload(env, record.artifact_id, "screen.mp4.partial")
        encoder.fragment(3)
        await until(lambda: env.service.status().captures[0].bytes_written == len(HEADER + FRAGMENT * 3))
        final = await env.service.stop(record.capture_id)

        assert (final.state, final.error_code, final.gaps) == (CaptureState.COMPLETE, None, 0)
        assert encoder.stop_requests == 1 and not encoder.killed and encoder.closed
        artifact = await env.artifacts.get(record.artifact_id)
        assert (artifact.kind, artifact.state, artifact.mime_type) == (ArtifactKind.SCREEN_RECORDING,
                                                                       ArtifactState.COMPLETE, "video/mp4")
        assert (artifact.duration_ms, artifact.width, artifact.height) == (4800, 4, 2)
        meta = artifact.metadata
        assert (meta["fps"], meta["container"], meta["video_codec"], meta["duration_source"]) == (
            5, "mp4_fragmented", "h264", "probe")
        assert meta["encoder_exit_code"] == 0 and meta["display"] == "display1" and meta["dpi_scale"] == 1.25
        final_bytes = payload(env, record.artifact_id, "screen.mp4").read_bytes()
        assert final_bytes == HEADER + FRAGMENT * 4 and artifact.size_bytes == len(final_bytes)
        assert final.bytes_written == len(final_bytes)
        assert not payload(env, record.artifact_id, "screen.mp4.partial").exists()
    finally:
        await env.aclose()


async def test_screen_and_audio_style_concurrency_one_recording_per_display(tmp_path):
    env = await make_env(tmp_path, displays=FakeDisplays([display(), display("display2", left=4, primary=False)]))
    try:
        first = await env.service.start(SCREEN)
        with pytest.raises(CaptureError) as held:
            await env.service.start(SCREEN)
        assert held.value.code is CaptureErrorCode.ALREADY_ACTIVE and held.value.capture_id == first.capture_id
        other = await env.service.start(SCREEN, _options(device="display2"))
        shot = await env.service.screenshot()  # une capture ponctuelle ne gêne jamais un enregistrement
        assert shot.state is CaptureState.COMPLETE
        for record in (first, other):
            assert (await env.service.stop(record.capture_id)).state is CaptureState.COMPLETE
    finally:
        await env.aclose()


async def test_an_encoder_that_dies_mid_recording_is_source_lost_and_partial(tmp_path):
    env = await make_env(tmp_path)
    try:
        record = await env.service.start(SCREEN)
        encoder = env.encoders[-1]
        encoder.fragment(2)
        encoder.exit(-22)
        await until(lambda: not env.service.status().captures, timeout=3.0)
        final = await env.service.get(record.capture_id)
        assert (final.state, final.error_code, final.stop_reason.value) == (CaptureState.PARTIAL, "source_lost",
                                                                            "source_lost")
        artifact = await env.artifacts.get(record.artifact_id)
        assert artifact.state is ArtifactState.PARTIAL and artifact.size_bytes == len(HEADER + FRAGMENT * 2)
        gaps = await env.events(ActivityKind.CAPTURE_GAP)
        assert [e.data["reason"] for e in gaps] == ["source_lost"]
    finally:
        await env.aclose()


async def test_a_display_unplugged_mid_recording_stops_it_as_source_lost(tmp_path):
    env = await make_env(tmp_path, displays=FakeDisplays([display(), display("display2", left=4, primary=False)]))
    try:
        record = await env.service.start(SCREEN, _options(device="display2"))
        env.encoders[-1].fragment()
        env.displays.current = [display()]
        await until(lambda: not env.service.status().captures, timeout=3.0)
        final = await env.service.get(record.capture_id)
        assert (final.state, final.error_code) == (CaptureState.PARTIAL, "source_lost")
        assert env.encoders[-1].stop_requests == 1, "arrêt propre de l'encodeur après la perte"
    finally:
        await env.aclose()


async def test_an_encoder_that_writes_nothing_stalls_into_source_lost(tmp_path):
    env = await make_env(tmp_path, stall_s=0.2)
    try:
        record = await env.service.start(SCREEN)
        await until(lambda: not env.service.status().captures, timeout=3.0)
        final = await env.service.get(record.capture_id)
        assert (final.state, final.error_code) == (CaptureState.PARTIAL, "source_lost")
        assert env.encoders[-1].killed
    finally:
        await env.aclose()


async def test_a_slow_encoder_is_killed_after_its_grace_and_the_evidence_is_partial(tmp_path):
    env = await make_env(tmp_path, script=Script(ignore_q=True))
    try:
        record = await env.service.start(SCREEN)
        env.encoders[-1].fragment(2)
        final = await env.service.stop(record.capture_id)
        assert (final.state, final.error_code) == (CaptureState.PARTIAL, "source_timeout")
        artifact = await env.artifacts.get(record.artifact_id)
        assert artifact.state is ArtifactState.PARTIAL and artifact.metadata["encoder_killed"] is True
        assert artifact.metadata["duration_source"] == "wall_clock", "pas de mesure après un kill"
    finally:
        await env.aclose()


@pytest.mark.parametrize(("stderr", "code"), [
    (["Error writing trailer: No space left on device"], CaptureErrorCode.STORAGE_FULL),
    (["Conversion failed!"], CaptureErrorCode.WRITE_FAILED),
])
async def test_a_nonzero_exit_at_stop_is_partial_with_the_encoder_cause(tmp_path, stderr, code):
    env = await make_env(tmp_path, script=Script(stop_code=1, stderr=stderr))
    try:
        record = await env.service.start(SCREEN)
        final = await env.service.stop(record.capture_id)
        assert (final.state, final.error_code) == (CaptureState.PARTIAL, code.value)
    finally:
        await env.aclose()


@pytest.mark.parametrize(("script", "stderr_code"), [
    (Script(exit_before_ready=1, stderr=["Failed to capture image (error 5): Access is denied."]),
     CaptureErrorCode.PERMISSION_DENIED),
    (Script(exit_before_ready=1, stderr=["Unknown input format: 'gdigrab'"]), CaptureErrorCode.SOURCE_UNAVAILABLE),
    (Script(write_header=False), CaptureErrorCode.SOURCE_UNAVAILABLE),
])
async def test_an_encoder_that_cannot_start_fails_the_capture_and_frees_the_display(tmp_path, script, stderr_code):
    env = await make_env(tmp_path, script=script, ready_timeout_s=0.3)
    try:
        with pytest.raises(CaptureError) as refused:
            await env.service.start(SCREEN)
        assert refused.value.code is stderr_code
        failed = await env.service.get(refused.value.capture_id)
        assert failed.state is CaptureState.FAILED and env.encoders[-1].closed
        env.encoders.clear()
        assert not env.service.status().captures
    finally:
        await env.aclose()


# ------------------------------------------------------------------ réparation après la mort de Core


def _die(env: Env) -> None:
    """Mort brutale simulée : la source s'arrête sans finaliser, rien n'est écrit en base."""

    for run in list(env.service._runs.values()):
        source = run.source
        source._stopping.set()
        source._watcher.join(2)
    env.service._runs.clear()
    env.service._holders.clear()


def _target(tmp_path: Path, data: bytes, *, final: bool = False) -> RepairTarget:
    from jarvis.domain.capture import new_capture

    path = tmp_path / ("screen.mp4" if final else "screen.mp4.partial")
    path.write_bytes(data)
    record = new_capture(channel=SCREEN, mode=CaptureMode.CONTINUOUS, source="desktop", now=utc_now())
    return RepairTarget(capture=record, artifact_id="jart_x", partial_path=tmp_path / "screen.mp4.partial",
                        final_path=tmp_path / "screen.mp4", partial_bytes=None if final else len(data),
                        final_bytes=len(data) if final else None)


def test_repair_trims_the_torn_fragment_in_place_and_measures(tmp_path):
    torn = HEADER + FRAGMENT * 2 + FRAGMENT[:40]
    repair = FragmentedMp4Repair(ffmpeg_locator=lambda: "ff", probe=lambda ff, path: 2000)
    outcome = repair.repair(_target(tmp_path, torn))
    assert (outcome.repaired, outcome.usable, outcome.duration_ms) == (True, True, 2000)
    assert (tmp_path / "screen.mp4.partial").read_bytes() == HEADER + FRAGMENT * 2
    assert outcome.detail == "mp4_fragments=2 trimmed_bytes=40"
    clean = FragmentedMp4Repair(ffmpeg_locator=lambda: None, probe=lambda ff, path: None).repair(
        _target(tmp_path, HEADER + FRAGMENT, final=True))
    assert (clean.repaired, clean.usable, clean.duration_ms) == (False, True, None)
    assert clean.detail.endswith("duration_unknown")


def test_repair_declares_a_file_without_any_fragment_unusable(tmp_path):
    outcome = FragmentedMp4Repair(ffmpeg_locator=lambda: None).repair(_target(tmp_path, HEADER + FRAGMENT[:30]))
    assert (outcome.usable, outcome.repaired) == (False, False) and "fragments=0" in outcome.detail


async def test_core_death_mid_recording_recovers_a_readable_partial(tmp_path):
    first = await make_env(tmp_path)
    record = await first.service.start(SCREEN)
    first.encoders[-1].fragment(2)
    _die(first)
    with open(payload(first, record.artifact_id, "screen.mp4.partial"), "ab") as handle:
        handle.write(FRAGMENT[:25])  # fragment déchiré par la mort
    await first.aclose()

    repair = FragmentedMp4Repair(ffmpeg_locator=lambda: "ff", probe=lambda ff, path: 2000)
    second = await make_env(tmp_path, repairs={SCREEN: repair}, seed=False)
    try:
        report = await second.service.recover()
        assert report.partial == (record.capture_id,)
        artifact = await second.artifacts.get(record.artifact_id)
        assert (artifact.state, artifact.duration_ms, artifact.size_bytes) == (
            ArtifactState.PARTIAL, 2000, len(HEADER + FRAGMENT * 2))
        recovered = await second.service.get(record.capture_id)
        assert recovered.error_code == "recoverable_partial"
        assert recovered.data["repair"] == "mp4_fragments=2 trimmed_bytes=25"
    finally:
        await second.aclose()


async def test_core_death_before_the_first_fragment_is_failed_not_a_fake_partial(tmp_path):
    first = await make_env(tmp_path)
    record = await first.service.start(SCREEN)
    _die(first)
    await first.aclose()

    second = await make_env(tmp_path, repairs={SCREEN: FragmentedMp4Repair(ffmpeg_locator=lambda: None)}, seed=False)
    try:
        report = await second.service.recover()
        assert report.failed == (record.capture_id,)
        artifact = await second.artifacts.get(record.artifact_id)
        assert (artifact.state, artifact.error_code) == (ArtifactState.FAILED, "capture_interrupted")
        assert payload(second, record.artifact_id, "screen.mp4.partial").exists(), "preuve gardée"
        recovered = await second.service.get(record.capture_id)
        assert (recovered.state, recovered.error_code) == (CaptureState.FAILED, "capture_interrupted")
    finally:
        await second.aclose()


# ------------------------------------------------------------------ spool confié à un écrivain externe


def test_a_handed_over_spool_measures_the_file_and_refuses_its_own_writes(tmp_path):
    from jarvis.ports.artifacts import ArtifactPayloadError

    store = FileArtifactPayloads(tmp_path)
    spool = store.open_spool("jart_ext", "screen.mp4")
    path = spool.hand_over()
    assert path.name == "screen.mp4.partial" and path.exists()
    path.write_bytes(HEADER)
    assert spool.size == len(HEADER)
    with pytest.raises(ArtifactPayloadError):
        spool.write(b"x")
    with pytest.raises(ArtifactPayloadError):
        spool.hand_over()
    assert spool.finalize() == len(HEADER)
    assert (tmp_path / "artifacts" / "jart_ext" / "screen.mp4").read_bytes() == HEADER


# ------------------------------------------------------------------ orphelin impossible (vrai processus)


_HARNESS = """
import sys, time
sys.path.insert(0, {root!r})
from jarvis.adapters.screen_capture import FfmpegProcess
encoder = FfmpegProcess({args!r})
print(encoder.pid, flush=True)
time.sleep(120)
"""


def _alive(pid: int) -> bool:
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x00100000 | 0x1000, False, pid)  # SYNCHRONIZE | QUERY_LIMITED
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT : vivant
    finally:
        kernel32.CloseHandle(handle)


def _run_harness(args: list[str]) -> tuple[subprocess.Popen, int]:
    root = str(Path(__file__).resolve().parents[2])
    harness = subprocess.Popen([sys.executable, "-c", _HARNESS.format(root=root, args=args)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    line = harness.stdout.readline().strip()
    assert line.isdigit(), harness.stderr.read()
    return harness, int(line)


def _wait_dead(pid: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while _alive(pid):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True


@windows_only
def test_the_encoder_dies_with_core_even_on_a_hard_kill():
    harness, child = _run_harness([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        assert _alive(child), "l'encodeur tourne tant que Core vit"
        harness.kill()  # TerminateProcess : aucune chance de nettoyer
        harness.wait(10)
        assert _wait_dead(child), "Job Object KILL_ON_JOB_CLOSE : pas d'encodeur orphelin"
    finally:
        if _alive(child):
            subprocess.run(["taskkill", "/PID", str(child), "/F"], capture_output=True)
        harness.stdout.close()
        harness.stderr.close()


# ------------------------------------------------------------------ vrai ffmpeg (mire synthétique)


def _synthetic_args(output: Path, *, seconds: int | None = None) -> list[str]:
    assert FFMPEG is not None
    desktop = recording_args(FFMPEG, display(width=320, height=240), output, fps=5)
    tail = desktop[desktop.index("desktop") + 1:]
    source = ["-re", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=5" + (f":duration={seconds}" if seconds else "")]
    return [FFMPEG, "-hide_banner", "-nostats", "-loglevel", "warning", *source, *tail]


@real_ffmpeg
def test_real_encoder_output_is_playable_and_frames_can_be_extracted(tmp_path):
    output = tmp_path / "clip.mp4"
    done = subprocess.run(_synthetic_args(output, seconds=2), capture_output=True, timeout=60)
    assert done.returncode == 0, done.stderr[-300:]
    with open(output, "rb") as handle:
        found = scan(handle, output.stat().st_size)
    assert found.usable and found.torn_bytes == 0 and found.fragments >= 2
    assert 1800 <= (probe_duration_ms(FFMPEG, output) or 0) <= 2200
    frame = extract_frame(FFMPEG, output, at_ms=1000)
    assert png_size(frame) == (320, 240)
    with pytest.raises(CaptureSourceError):
        extract_frame(FFMPEG, tmp_path / "missing.mp4", at_ms=0)


@real_ffmpeg
@windows_only
def test_real_encoder_killed_with_core_leaves_a_recoverable_file(tmp_path):
    output = tmp_path / "screen.mp4.partial"
    harness, encoder = _run_harness(_synthetic_args(output))
    try:
        deadline = time.monotonic() + 15
        while (not output.exists() or output.stat().st_size < 2000) and time.monotonic() < deadline:
            time.sleep(0.1)
        time.sleep(2.5)
        harness.kill()
        harness.wait(10)
        assert _wait_dead(encoder), "ffmpeg meurt avec Core"
    finally:
        if _alive(encoder):
            subprocess.run(["taskkill", "/PID", str(encoder), "/F"], capture_output=True)
        harness.stdout.close()
        harness.stderr.close()
    size = output.stat().st_size
    record_target = RepairTarget(capture=None, artifact_id="jart_x", partial_path=output,  # type: ignore[arg-type]
                                 final_path=tmp_path / "screen.mp4", partial_bytes=size, final_bytes=None)
    outcome = FragmentedMp4Repair(ffmpeg_locator=lambda: FFMPEG).repair(record_target)
    assert outcome.usable and (outcome.duration_ms or 0) >= 1000, outcome

"""The pinned ffmpeg / ffprobe wrapper of the rendered-frame quality gates (native-studio-playback-fix Slice 14).

Pure parts always run (sizes read from the headers, the concat list, error mapping, the tool lookup). The decoding, sheets and video run
with the real compositor binaries of an existing install (`JARVIS_REMOTION_RUNTIME_DIR`), skipped otherwise.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

from jarvis.adapters import remotion_media_tools as M
from jarvis.media.png import bgra_to_png
from tests.fakes.remotion_player_stack import runtime_dir_from_env

RUNTIME = runtime_dir_from_env()


def png(path: Path, width: int, height: int, bgra: bytes | None = None) -> Path:
    path.write_bytes(bgra_to_png(width, height, bgra or b"\x20\x40\x60\xff" * (width * height)))
    return path


def jpeg_header(width: int, height: int) -> bytes:
    """SOI, an APP0 segment, then SOF0 with the size: what `image_size` reads (no pixels needed)."""

    app0 = b"\xff\xe0" + (16).to_bytes(2, "big") + b"JFIF\x00" + b"\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = b"\xff\xc0" + (17).to_bytes(2, "big") + b"\x08" + height.to_bytes(2, "big") + width.to_bytes(2, "big") + b"\x03" + b"\x00" * 9
    return M.JPEG_SOI + app0 + sof0


def test_the_size_is_read_from_a_png_and_a_jpeg_header(tmp_path):
    assert M.image_size(png(tmp_path / "a.png", 7, 3)) == (7, 3)
    (tmp_path / "b.jpg").write_bytes(jpeg_header(1920, 1080))
    assert M.image_size(tmp_path / "b.jpg") == (1920, 1080)
    (tmp_path / "c.bin").write_bytes(b"not an image")
    with pytest.raises(M.MediaToolError) as caught:
        M.image_size(tmp_path / "c.bin")
    assert caught.value.code == "media_tool_input_invalid"


@pytest.mark.parametrize("size,expected", [((1280, 720), (320, 180)), ((1920, 1080), (320, 180)), ((1080, 1920), (320, 568)),
                                           ((4000, 10), (320, 2))])
def test_the_work_size_keeps_the_aspect_and_an_even_height(size, expected):
    assert M.work_size(size) == expected


def test_the_concat_list_quotes_paths_and_carries_durations(tmp_path):
    listing = M._concat_list([(tmp_path / "it's.jpg", 0.25), (tmp_path / "b.jpg", None)], tmp_path)
    text = listing.read_text(encoding="utf-8")
    assert text.startswith("ffconcat version 1.0\n") and "it'\\''s.jpg'" in text and "duration 0.2500" in text
    assert text.count("duration") == 1 and "\\" not in text.replace("'\\''", "")


def test_a_tool_that_cannot_start_fails_or_times_out_says_so_in_its_own_words(tmp_path):
    with pytest.raises(M.MediaToolError) as missing:
        M._run([str(tmp_path / "no-ffmpeg.exe"), "-version"])
    assert missing.value.code == "media_tool_unavailable"
    with pytest.raises(M.MediaToolError) as failed:
        M._run([sys.executable, "-c", "import sys; sys.stderr.write('boom from the tool'); sys.exit(3)"])
    assert failed.value.code == "media_tool_failed" and "boom from the tool" in failed.value.detail and "exited 3" in failed.value.detail
    with pytest.raises(M.MediaToolError) as slow:
        M._run([sys.executable, "-c", "import time; time.sleep(5)"], timeout_s=0.5)
    assert slow.value.code == "media_tool_timeout"


def test_the_compositor_tool_is_found_under_the_runtime_or_none(tmp_path):
    assert M.compositor_tool(tmp_path, "ffmpeg") is None
    folder = tmp_path / "node_modules" / "@remotion" / "compositor-win32-x64-msvc"
    folder.mkdir(parents=True)
    (folder / "ffprobe.exe").write_bytes(b"")
    assert M.compositor_tool(tmp_path, "ffprobe") == folder / "ffprobe.exe" and M.compositor_tool(tmp_path, "ffmpeg") is None


def test_a_contact_sheet_needs_cells_and_columns(tmp_path):
    with pytest.raises(ValueError):
        M.contact_sheet(Path("ffmpeg"), [], columns=2, out=tmp_path / "s.jpg")
    with pytest.raises(ValueError):
        M.encode_flow_video(Path("ffmpeg"), [], out=tmp_path / "v.mp4")


# ------------------------------------------------------------------ the real binaries (opt-in)

real = pytest.mark.skipif(RUNTIME is None, reason="needs JARVIS_REMOTION_RUNTIME_DIR (an existing Remotion install)")


@real
def test_decoding_a_png_gives_its_luma_at_the_work_width(tmp_path):
    ffmpeg = M.compositor_tool(RUNTIME, "ffmpeg")
    half = b"".join((b"\xff\xff\xff\xff" if x < 320 else b"\x00\x00\x00\xff") for _y in range(360) for x in range(640))
    gray = M.decode_gray(ffmpeg, png(tmp_path / "half.png", 640, 360, half))
    assert (gray.width, gray.height) == (320, 180)
    assert gray.pixels[10] > 240 and gray.pixels[300] < 15
    frames = M.decode_gray_batch(ffmpeg, [tmp_path / "half.png"] * 3)
    assert len(frames) == 3 and frames[2].pixels == gray.pixels


@real
def test_a_sheet_and_a_video_are_made_and_probed(tmp_path):
    ffmpeg, ffprobe = M.compositor_tool(RUNTIME, "ffmpeg"), M.compositor_tool(RUNTIME, "ffprobe")
    a = png(tmp_path / "a.png", 640, 360)
    b = png(tmp_path / "b.png", 1080, 1920, b"\xa0\x20\x20\xff" * (1080 * 1920))
    sheet = M.contact_sheet(ffmpeg, [a, b, None], columns=2, out=tmp_path / "sheet.jpg")
    assert M.image_size(sheet) == (4 + 2 * (M.CELL_WIDTH + 4), 4 + 2 * (M.CELL_HEIGHT + 4))
    video = M.encode_flow_video(ffmpeg, [(a, 0.5), (a, 0.7)], out=tmp_path / "v.mp4")
    facts = M.probe_video(ffprobe, video)
    assert facts["codec"] == "h264" and facts["width"] == M.DEFAULT_VIDEO_WIDTH and facts["duration_ms"] == 1200 and facts["frames"] == 12, facts


def test_the_video_ticks_follow_the_page_clock():
    a, b, c = Path("a.jpg"), Path("b.jpg"), Path("c.jpg")
    assert M.video_ticks([(a, 0.25), (b, 0.1), (c, 0.3)], 10) == [a, a, a, b, c, c, c]
    assert M.video_ticks([(a, 0.01)], 10) == [a]

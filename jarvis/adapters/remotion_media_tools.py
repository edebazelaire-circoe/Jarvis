"""The pinned ffmpeg / ffprobe of the Remotion capability, for rendered-frame quality (native-studio-playback-fix Slice 14).

Contract: `docs/presentation-studio.md` > *Rendered-frame quality gates (Level 3, Slice 14)*. The binaries are the ones Remotion ships
(`node_modules/@remotion/compositor-*`), the same the render runner already uses to verify an MP4 (`compositor_tool`): no second media
stack, no download. Every call is a bounded child process (`timeout`), argument list only (no shell), stderr kept for the error.

- `decode_gray` / `decode_gray_batch`: JPEG / PNG -> `GrayFrame` (luma, `WORK_WIDTH` wide) for `jarvis.media.frame_quality`;
- `contact_sheet`: frames tiled into one small JPEG (one row per scene, or one pair per transition);
- `encode_flow_video`: timed captures -> a short low-bitrate H.264 MP4 (`DEFAULT_VIDEO_*`);
- `probe_video`: width, height, frame count and duration of an MP4 (the evidence of a recording).
"""

from __future__ import annotations

from collections.abc import Sequence
import json
import os
from pathlib import Path
import subprocess
import tempfile

from jarvis.media.frame_quality import WORK_WIDTH, GrayFrame
from jarvis.media.png import PNG_SIGNATURE, bgra_to_png

JPEG_SOI = bytes((0xFF, 0xD8))

#: Recording of the 9-scene flow: small on purpose (disk is a shared resource): 10 i/s, 640 px wide, CRF 34.
DEFAULT_VIDEO_FPS = 10
DEFAULT_VIDEO_WIDTH = 640
DEFAULT_VIDEO_CRF = 34
#: Contact-sheet cell (pixels) and JPEG quality (ffmpeg `-q:v`, 2 best .. 31 worst).
CELL_WIDTH, CELL_HEIGHT = 320, 180
SHEET_QUALITY = 5
TIMEOUT_S = 120.0
_STDERR_TAIL = 600


class MediaToolError(RuntimeError):
    """A media tool call that failed, with a stable `code` and the tool's own words in `detail`."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def compositor_tool(runtime_dir: Path, name: str) -> Path | None:
    """`ffmpeg` / `ffprobe` of the installed Remotion compositor package under `runtime_dir`, or `None`."""

    modules = Path(runtime_dir) / "node_modules" / "@remotion"
    try:
        entries = sorted(os.scandir(modules), key=lambda e: e.name)
    except OSError:
        return None  # no runtime installed: the caller says the tool is unavailable
    for entry in entries:
        if entry.name.startswith("compositor-"):
            for candidate in (f"{name}.exe", name):
                if (Path(entry.path) / candidate).is_file():
                    return Path(entry.path) / candidate
    return None


def _run(argv: Sequence[str], *, stdin: bytes | None = None, timeout_s: float = TIMEOUT_S) -> bytes:
    try:
        done = subprocess.run(list(argv), input=stdin, capture_output=True, timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired:
        raise MediaToolError("media_tool_timeout", f"{Path(argv[0]).name} did not finish within {timeout_s:.0f} s") from None
    except OSError as exc:
        raise MediaToolError("media_tool_unavailable", f"{type(exc).__name__}: {Path(argv[0]).name} could not start") from None
    if done.returncode != 0:
        tail = done.stderr.decode("utf-8", "replace").strip()[-_STDERR_TAIL:]
        raise MediaToolError("media_tool_failed", f"{Path(argv[0]).name} exited {done.returncode}: {tail}")
    return done.stdout


def image_size(image: Path) -> tuple[int, int]:
    """`(width, height)` read from a PNG `IHDR` or a JPEG `SOFn` header (the ffmpeg of Remotion has no PGM/PPM encoder: the decoded size
    is computed here, then the pixels come out as raw luma)."""

    data = Path(image).read_bytes()[:256 * 1024]
    if data[:8] == PNG_SIGNATURE and data[12:16] == b"IHDR":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:2] == JPEG_SOI:
        pos = 2
        while pos + 9 < len(data):
            if data[pos] != 0xFF:
                pos += 1
                continue
            marker = data[pos + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                return int.from_bytes(data[pos + 7:pos + 9], "big"), int.from_bytes(data[pos + 5:pos + 7], "big")
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                pos += 2
                continue
            pos += 2 + int.from_bytes(data[pos + 2:pos + 4], "big")
    raise MediaToolError("media_tool_input_invalid", f"not a PNG or JPEG with a readable size: {Path(image).name}")


def work_size(size: tuple[int, int], width: int = WORK_WIDTH) -> tuple[int, int]:
    """The decoded size: `width` wide, aspect kept, height even and at least 2."""

    w, h = size
    return width, max(2, round(width * h / w / 2) * 2)


def _raw(ffmpeg: Path, inputs: list[str], *, size: tuple[int, int], pix_fmt: str, frames: int | None = 1,
         timeout_s: float = TIMEOUT_S) -> bytes:
    """Decoded pixels on stdout. The ffmpeg Remotion ships is minimal (no PGM/PPM encoder, no rawvideo muxer or demuxer, no tile / pad /
    fps filter): raw frames go through `image2pipe` + the `rawvideo` encoder, sized here, composed in Python."""

    w, h = size
    return _run([str(ffmpeg), "-v", "error", "-nostdin", *inputs, "-vf", f"scale={w}:{h}:flags=area",
                 *(["-frames:v", str(frames)] if frames else []), "-f", "image2pipe", "-vcodec", "rawvideo", "-pix_fmt", pix_fmt, "-"],
                timeout_s=timeout_s)


def decode_gray(ffmpeg: Path, image: Path, *, width: int = WORK_WIDTH) -> GrayFrame:
    """One image -> luma at `width` pixels (height keeps the aspect ratio, even)."""

    w, h = work_size(image_size(image), width)
    out = _raw(ffmpeg, ["-i", str(image)], size=(w, h), pix_fmt="gray")
    if len(out) != w * h:
        raise MediaToolError("media_tool_output_invalid", f"{len(out)} bytes decoded for a {w}x{h} luma frame")
    return GrayFrame(w, h, out)


def _concat_list(entries: Sequence[tuple[Path, float | None]], folder: Path) -> Path:
    listing = folder / "inputs.txt"
    lines = ["ffconcat version 1.0"]
    for path, seconds in entries:
        lines.append("file '" + str(Path(path).resolve()).replace("\\", "/").replace("'", "'\\''") + "'")
        if seconds is not None:
            lines.append(f"duration {seconds:.4f}")
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return listing


def decode_gray_batch(ffmpeg: Path, images: Sequence[Path], *, width: int = WORK_WIDTH) -> list[GrayFrame]:
    """Images of the SAME size -> luma frames, one ffmpeg process for all of them (the captures of a recording)."""

    if not images:
        return []
    w, h = work_size(image_size(images[0]), width)
    with tempfile.TemporaryDirectory(prefix="jq-") as folder:
        listing = _concat_list([(p, None) for p in images], Path(folder))
        raw = _raw(ffmpeg, ["-f", "concat", "-safe", "0", "-i", str(listing), "-fps_mode", "passthrough"], size=(w, h), pix_fmt="gray",
                   frames=None, timeout_s=TIMEOUT_S * 3)
    size = w * h
    if len(raw) != size * len(images):
        raise MediaToolError("media_tool_output_invalid", f"{len(raw) // size} frame(s) decoded for {len(images)} image(s)")
    return [GrayFrame(w, h, raw[i * size:(i + 1) * size]) for i in range(len(images))]


def _fit(size: tuple[int, int], box: tuple[int, int]) -> tuple[int, int]:
    w, h = size
    scale = min(box[0] / w, box[1] / h)
    return max(2, int(w * scale) // 2 * 2), max(2, int(h * scale) // 2 * 2)


def contact_sheet(ffmpeg: Path, cells: Sequence[Path | None], *, columns: int, out: Path) -> Path:
    """Cells tiled `columns` wide, row after row, into one JPEG: `CELL_WIDTH` x `CELL_HEIGHT` per cell, aspect kept, letterboxed on dark
    grey, a 4-pixel gutter. A `None` cell stays empty (a scene shorter than the sampled roles)."""

    if columns < 1 or not cells:
        raise ValueError("a contact sheet needs at least one cell and one column")
    rows, gap = -(-len(cells) // columns), 4
    sheet_w, sheet_h = gap + columns * (CELL_WIDTH + gap), gap + rows * (CELL_HEIGHT + gap)
    canvas = bytearray(b"\x10\x10\x10\xff" * (sheet_w * sheet_h))
    for index, cell in enumerate(cells):
        x0, y0 = gap + (index % columns) * (CELL_WIDTH + gap), gap + (index // columns) * (CELL_HEIGHT + gap)
        for y in range(CELL_HEIGHT):
            start = ((y0 + y) * sheet_w + x0) * 4
            canvas[start:start + CELL_WIDTH * 4] = b"\x30\x30\x30\xff" * CELL_WIDTH
        if cell is None:
            continue
        w, h = _fit(image_size(cell), (CELL_WIDTH, CELL_HEIGHT))
        pixels = _raw(ffmpeg, ["-i", str(cell)], size=(w, h), pix_fmt="bgra")
        if len(pixels) != w * h * 4:
            raise MediaToolError("media_tool_output_invalid", f"{len(pixels)} bytes decoded for a {w}x{h} cell")
        ox, oy = x0 + (CELL_WIDTH - w) // 2, y0 + (CELL_HEIGHT - h) // 2
        for y in range(h):
            start = ((oy + y) * sheet_w + ox) * 4
            canvas[start:start + w * 4] = pixels[y * w * 4:(y + 1) * w * 4]
    with tempfile.TemporaryDirectory(prefix="jq-") as folder:
        png = Path(folder) / "sheet.png"
        png.write_bytes(bgra_to_png(sheet_w, sheet_h, bytes(canvas)))
        _run([str(ffmpeg), "-v", "error", "-nostdin", "-y", "-i", str(png), "-frames:v", "1", "-q:v", str(SHEET_QUALITY), str(out)])
    return out


def video_ticks(timed: Sequence[tuple[Path, float]], fps: int) -> list[Path]:
    """One capture per output frame: at each tick `n / fps` of the page's clock, the capture on screen then (the concat demuxer's own
    durations drop or stretch the last entry: measured; one entry per tick is exact)."""

    ticks: list[Path] = []
    start = 0.0
    total = sum(seconds for _p, seconds in timed)
    count = max(1, int(total * fps + 0.5))  # half up: a capture shown half a tick still gets its frame
    index = 0
    for n in range(count):
        at = n / fps
        while index + 1 < len(timed) and start + timed[index][1] <= at:
            start += timed[index][1]
            index += 1
        ticks.append(Path(timed[index][0]))
    return ticks


def encode_flow_video(ffmpeg: Path, timed: Sequence[tuple[Path, float]], *, out: Path, fps: int = DEFAULT_VIDEO_FPS,
                      width: int = DEFAULT_VIDEO_WIDTH, crf: int = DEFAULT_VIDEO_CRF) -> Path:
    """`timed` = `(capture, seconds it stayed on screen)` in order -> H.264 MP4 at a constant `fps` whose clock is the page's clock."""

    if not timed:
        raise ValueError("a recording needs at least one capture")
    w, h = work_size(image_size(timed[0][0]), width)
    with tempfile.TemporaryDirectory(prefix="jq-") as folder:
        listing = _concat_list([(p, 1 / fps) for p in video_ticks(timed, fps)], Path(folder))
        _run([str(ffmpeg), "-v", "error", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-r", str(fps),
              "-fps_mode", "cfr", "-vf", f"scale={w}:{h}:flags=area,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
              "-crf", str(crf), "-movflags", "+faststart", "-an", str(out)], timeout_s=TIMEOUT_S * 3)
    return out


def probe_video(ffprobe: Path, video: Path) -> dict[str, object]:
    """`{width, height, frames, duration_ms, codec}` of the first video stream."""

    raw = _run([str(ffprobe), "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
                "stream=codec_name,width,height,nb_read_frames:format=duration", "-of", "json", str(video)])
    try:
        data = json.loads(raw.decode("utf-8"))
        stream = data["streams"][0]
        return {"codec": stream["codec_name"], "width": int(stream["width"]), "height": int(stream["height"]),
                "frames": int(stream["nb_read_frames"]), "duration_ms": round(float(data["format"]["duration"]) * 1000)}
    except (ValueError, KeyError, IndexError) as exc:
        raise MediaToolError("media_tool_output_invalid", f"{type(exc).__name__}: unreadable ffprobe answer") from None

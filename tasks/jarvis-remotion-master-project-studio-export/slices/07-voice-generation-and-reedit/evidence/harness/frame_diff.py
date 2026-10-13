"""Frame check between two whole-video exports (Slice 07 step 7): each MP4 sampled at 6 fps (every 5th frame at 30 fps), 96x54 grayscale PNG through the gate's
ffmpeg (its build has no psnr filter and no raw muxer), decoded here in pure Python; mean absolute difference per frame (0..255), summarised
per scene range. `python frame_diff.py <a.mp4> <b.mp4> <frames_per_scene> <scenes> <out.json>`.
"""
from __future__ import annotations

import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import zlib

import bench


def png_gray(path: Path) -> tuple[int, int, bytes]:
    data = path.read_bytes()
    pos, idat, width, height, color = 8, b"", 0, 0, 0
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, color = struct.unpack(">IIBB", body[:10])
            assert depth == 8 and color == 0, (depth, color)
        elif kind == b"IDAT":
            idat += body
        pos += 12 + length
    raw, out, prev = zlib.decompress(idat), bytearray(), bytearray(width)
    for row in range(height):
        f, line = raw[row * (width + 1)], bytearray(raw[row * (width + 1) + 1:(row + 1) * (width + 1)])
        for i in range(width):
            a = line[i - 1] if i else 0
            b, c = prev[i], (prev[i - 1] if i else 0)
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out += line
        prev = line
    return width, height, bytes(out)


def frames(mp4: Path, folder: Path) -> list[bytes]:
    folder.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(bench.FFMPEG), "-y", "-v", "error", "-i", str(mp4), "-vf", "scale=96:54", "-r", "6",
                    "-pix_fmt", "gray", str(folder / "f%04d.png")], check=True)
    return [png_gray(p)[2] for p in sorted(folder.glob("f*.png"))]


def main() -> None:
    a, b, per, scenes, out = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), Path(sys.argv[5])
    with tempfile.TemporaryDirectory() as tmp:
        fa, fb = frames(a, Path(tmp) / "a"), frames(b, Path(tmp) / "b")
    assert len(fa) == len(fb), (len(fa), len(fb))
    diffs = [sum(abs(x - y) for x, y in zip(p, q)) / len(p) for p, q in zip(fa, fb)]
    step = per // 5
    result = {"method": "6 fps samples, 96x54 grayscale, mean absolute difference 0..255 (a vs b)", "a": a.name, "b": b.name,
              "scenes": {f"scene{k + 1}": {"sampled_frames": len(diffs[k * step:(k + 1) * step]),
                                           "max": round(max(diffs[k * step:(k + 1) * step]), 2),
                                           "mean": round(sum(diffs[k * step:(k + 1) * step]) / step, 2)} for k in range(scenes)}}
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()

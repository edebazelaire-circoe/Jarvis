"""Frame captures of a finished deck, the same way for both sides, for the blinded side-by-side review (HV-RFX-13-01).

The deck's whole timeline (scenes in order) is sampled at the same relative moments, `SAMPLES` points, 960x540 JPEG/PNG:
- Jarvis side: the deck in the isolated stack, rendered by Core's guarded render host (`POST .../render/preview`, the route this Slice adds);
- direct side: the throw-away Remotion project, rendered by `npx remotion still` (its own compositions, in `Root.tsx` order).

`python frames.py jarvis <run> <presentation_id>` (stack up) / `python frames.py direct <run>`; frames land in `<run>/frames/`.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

import bench

SAMPLES = (0.06, 0.19, 0.31, 0.44, 0.56, 0.69, 0.81, 0.94)


def timeline_points(durations: list[int]) -> list[tuple[int, int]]:
    """(index of the scene, local frame) for each relative moment of the whole timeline."""

    total = sum(durations)
    points = []
    for share in SAMPLES:
        at = min(total - 1, int(share * total))
        for index, length in enumerate(durations):
            if at < length:
                points.append((index, at))
                break
            at -= length
    return points


def jarvis(run: str, pid: str) -> None:
    m = bench.meta(run)
    out = bench.run_dir(run) / "frames"
    out.mkdir(exist_ok=True)
    _, doc = bench.core(m, "GET", f"/v1/presentation-studio/presentations/{pid}")
    variant = next(v for v in doc["variants"] if v["variant_id"] == doc["presentation"]["active_variant_id"])
    scenes = []
    for scene in variant["scenes"]:
        _, source = bench.core(m, "GET", f"/v1/presentation-studio/presentations/{pid}/variants/{variant['variant_id']}/scenes/{scene['scene_id']}/source")
        scenes.append((scene["scene_id"], source["manifest"]["source"]["composition"]["duration_in_frames"]))
    wanted: dict[int, list[int]] = {}
    for index, frame in timeline_points([d for _, d in scenes]):
        wanted.setdefault(index, []).append(frame)
    shots = []
    for index, frames in sorted(wanted.items()):
        status, body = bench.core(m, "POST", "/v1/local-capabilities/remotion/render/preview",
                                  {"presentation_id": pid, "variant_id": variant["variant_id"], "scene_id": scenes[index][0], "frames": frames},
                                  timeout=200)
        if status != 200:
            raise SystemExit(f"preview of scene {index} failed: {status} {body}")
        for item in body["preview"]["frames"]:
            target = out / f"{len(shots) + 1:02d}-scene{index + 1}-f{item['frame']}.jpg"
            shutil.copyfile(item["path"], target)
            shots.append(target.name)
    (out / "frames.json").write_text(json.dumps({"presentation_id": pid, "variant_id": variant["variant_id"], "scenes": scenes,
                                                 "samples": SAMPLES, "shots": shots}, indent=1), encoding="utf-8")
    print(json.dumps(shots))


def direct(run: str) -> None:
    project = Path(bench.meta(run)["project"])
    out = bench.run_dir(run) / "frames"
    out.mkdir(exist_ok=True)
    listed = subprocess.run("npx remotion compositions src/index.ts", cwd=project, capture_output=True, text=True, encoding="utf-8", errors="replace", shell=True,
                            timeout=300)
    rows = [line.split() for line in listed.stdout.splitlines() if re.match(r"^\S+\s+\d+\s+\d+x\d+\s+\d+", line.strip())]
    comps = [(row[0], int(row[3])) for row in rows]
    if not comps:
        raise SystemExit(f"no composition listed: {listed.stdout[-800:]} {listed.stderr[-800:]}")
    shots = []
    for index, frame in timeline_points([d for _, d in comps]):
        name = comps[index][0]
        target = out / f"{len(shots) + 1:02d}-{name}-f{frame}.png"
        if target.exists():  # resumable: a busy host can time a browser out; the next call keeps what was rendered
            shots.append(target.name)
            continue
        done = subprocess.run(f"npx remotion still src/index.ts {name} \"{target}\" --frame={frame} --scale=0.5", cwd=project,
                              capture_output=True, text=True, encoding="utf-8", errors="replace", shell=True, timeout=300)
        if done.returncode != 0:
            raise SystemExit(f"still {name}@{frame} failed: {done.stderr[-800:]}")
        shots.append(target.name)
    (out / "frames.json").write_text(json.dumps({"compositions": comps, "samples": SAMPLES, "shots": shots}, indent=1), encoding="utf-8")
    print(json.dumps(shots))


if __name__ == "__main__":
    if sys.argv[1] == "jarvis":
        jarvis(sys.argv[2], sys.argv[3])
    else:
        direct(sys.argv[2])

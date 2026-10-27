"""The representative still of a paused scene is the same in the page and in Core (presentation-edition-v1 Slice 09, PM decision).

Variants rests a paused scene on it (`control_center_prefab_host.js` › `representativeFrame`, host option `rest`), and Core renders an
image or a PDF of a scene on it when no frame is named (`presentation_render_plan.representative_frame`). One rule, two places: the end of
the entrance the scene declares with its first timed anchor, else the middle of the scene, clamped. This test runs both on the same cases.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from jarvis.domain.presentation_render_plan import representative_frame

HOST_JS = Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center_prefab_host.js"

#: (duration in frames, fps, first timed anchor in ms or None, expected frame)
CASES = [(90, 30, None, 45), (300, 30, 1000, 30), (241, 30, None, 120), (90, 30, 60_000, 89), (240, 25, 2000, 50), (1, 30, None, 0), (90, 10, 250, 3)]


def test_page_and_core_choose_the_same_representative_frame():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = (f"const H=require({json.dumps(str(HOST_JS))});"
              f"process.stdout.write(JSON.stringify({json.dumps(CASES)}.map(([d,f,ms])=>H.representativeFrame({{durationInFrames:d,fps:f}},ms===null?null:ms))));")
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    page = json.loads(done.stdout)
    core = []
    for frames, fps, ms, _ in CASES:
        anchors = [] if ms is None else [{"anchor_id": "a", "label": "A", "at_ms": ms}]
        package = SimpleNamespace(files={"presentation/variant.json": json.dumps({"scenes": [{"scene_id": "pss_a", "anchors": anchors}]}).encode()})
        core.append(representative_frame(package, SimpleNamespace(scene_id="pss_a", duration_in_frames=frames, fps=fps)))
    assert page == core == [expected for *_, expected in CASES]

"""Rendered-frame quality gates on REAL frames (handoff jarvis-remotion-native-studio-playback-fix, Slice 14, steps 1, 2 and 5).

VRAI Core (with the real `RemotionRenderRunner`), the real guarded render host through Core's preview route (Slice 13), VRAI Control
Center and Chrome for the scene's page; free ports and a throw-away data root (`RemotionStack`); never the live Jarvis. Opt-in:
`JARVIS_REMOTION_RUNTIME_DIR` (an existing Remotion install, never a new one), Node and Chrome; skipped otherwise. The data root must stay
short (`docs/remotion-render.md` § 12): run with a short `--basetemp`.

Three decks, the same smoke path (first, entry, middle, exit and last frame of every scene, rendered by the guarded host; transition
frames = last of scene k beside first of scene k+1) and the same detectors (`jarvis.media.frame_quality`):

- the Slice 03 gate deck (9 scenes, `release_gate` profile): no blocking finding;
- a Slice 13 native deck (the TSX the agent wrote in run `jn4`, `authored` profile): no blocking finding, its fades are warnings;
- the control deck (`remotion_quality_world.CONTROL_SCENES`): every detector fires where it must (black frame, text cut by the frame,
  missing font, missing image, a scene ending on black) — the positive control of the false-negative side.

Evidence (`JARVIS_QUALITY_EVIDENCE_DIR`): `<deck>-smoke.json` (durations, per-frame metrics, findings, the four separate report sections),
`<deck>-contact.jpg` (one row per scene), `<deck>-transitions.jpg` (one row per hand-over).
"""

from __future__ import annotations

import shutil
import time

import pytest

from jarvis.media import frame_quality as Q
from tests.fakes.remotion_player_stack import RemotionStack, runtime_dir_from_env
from tests.unit.presentation_playback_gate_world import harness, make_deck, open_variants, run_long, scrub_to
from tests.unit.remotion_quality_world import (
    CONTROL_SCENES, SCENE_DOM_PROBE, control_deck, deck_summary, dom_findings, media_tools, native_deck, quality_options, scene_list,
    smoke_deck, write_evidence,
)

RUNTIME = runtime_dir_from_env()
pytestmark = pytest.mark.skipif(RUNTIME is None or shutil.which("node") is None,
                                reason="needs JARVIS_REMOTION_RUNTIME_DIR (an existing Remotion install), node and Chrome")


async def page_pass(stack: RemotionStack, pid: str) -> dict[str, list]:
    """The scene's page, scene by scene: Variants opened on the deck, the slider moved to the middle of each scene, the page probe read in
    every live sandbox page. `{S<n>: [probe record, ...]}`."""

    _vid, scenes = await scene_list(stack, pid)
    plan = open_variants(pid)
    for k, scene in enumerate(scenes):
        comp = scene["composition"]
        plan += [{"eval": scrub_to(k, int(comp["duration_in_frames"] / comp["fps"] / 2), legacy_local_frame=0)}, {"wait": 1200},
                 {"value": f"dom_S{k + 1}", "expr": SCENE_DOM_PROBE, "scope": "sandboxes"}]
    result = await run_long(stack.page_url, plan, timeout=300)
    reads = result["reads"]
    harness("failed" not in reads, reads.get("failed"))
    return {f"S{k + 1}": reads.get(f"dom_S{k + 1}") or [] for k in range(len(scenes))}


async def run_smoke(tmp_path, name: str, build, profile: Q.Profile, *, with_page: bool) -> dict:
    ffmpeg, _ffprobe = media_tools(RUNTIME)
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME, core_options=quality_options) as stack:
        pid = await build(stack)
        started = time.monotonic()
        result = await smoke_deck(stack, pid, ffmpeg=ffmpeg, work=tmp_path / "frames", profile=profile, name=name)
        result["smoke_s"] = round(time.monotonic() - started, 1)
        if with_page:
            started = time.monotonic()
            pages = await page_pass(stack, pid)
            result["page_s"] = round(time.monotonic() - started, 1)
            for scene, records in pages.items():
                result["findings"] += dom_findings(records, scene=scene)
            result["page_probe"] = {scene: [{"page": r.get("page"), "text": r.get("text"), "fonts": r.get("fonts"), "assets": r.get("assets"),
                                             "overflow": r.get("overflow")} for r in records] for scene, records in pages.items()}
    summary = deck_summary(result)
    write_evidence(f"{name}-smoke", summary, {f"{name}-contact.jpg": result["contact"],
                                              **({f"{name}-transitions.jpg": result["transitions"]} if result["transitions"] else {})})
    shutil.rmtree(tmp_path / "frames", ignore_errors=True)
    return result


def blocking(result: dict) -> list[dict]:
    return [f.to_dict() for f in result["findings"] if f.severity is Q.Severity.BLOCKING]


async def test_the_gate_deck_smoke_frames_have_no_blocking_finding(tmp_path):
    async def build(stack):
        pid, _vid = await make_deck(stack)
        return pid
    result = await run_smoke(tmp_path, "gate", build, Q.Profile.RELEASE_GATE, with_page=True)
    assert all(row.get("http") == 200 for row in result["scenes"]) and len(result["scenes"]) == 9, result["scenes"]
    assert blocking(result) == [], blocking(result)
    assert all(len(row["frames"]) == 5 for row in result["scenes"]), "first, entry, middle, exit, last of every scene"
    seen = {scene: " | ".join(record.get("text") or "" for record in records) for scene, records in result["page_probe"].items()}
    assert all(f"{scene} " in text for scene, text in seen.items()) and len(seen) == 9, f"the page pass visited every scene: {seen}"


async def test_a_native_deck_smoke_reports_its_fades_as_warnings_and_blocks_nothing(tmp_path):
    async def build(stack):
        pid, _vid, _titles = await native_deck(stack)
        return pid
    result = await run_smoke(tmp_path, "native", build, Q.Profile.AUTHORED, with_page=True)
    assert all(row.get("http") == 200 for row in result["scenes"]), result["scenes"]
    assert blocking(result) == [], blocking(result)
    assert len({record["page"] for records in result["page_probe"].values() for record in records}) == 4, "one page per scene source"


async def test_every_detector_fires_on_the_control_deck(tmp_path):
    async def build(stack):
        pid, _vid, _titles = await control_deck(stack)
        return pid
    result = await run_smoke(tmp_path, "control", build, Q.Profile.RELEASE_GATE, with_page=True)
    by_scene: dict[str, set[str]] = {}
    for finding in result["findings"]:
        by_scene.setdefault(finding.scene or "", set()).add(finding.code)
    missed = {f"S{k + 1} {title}": sorted(expected - by_scene.get(f"S{k + 1}", set()))
              for k, (title, _body, expected) in enumerate(CONTROL_SCENES) if expected - by_scene.get(f"S{k + 1}", set())}
    assert missed == {}, {"missed": missed, "found": {k: sorted(v) for k, v in by_scene.items()}}
    assert "static_scene" in by_scene.get("S1", set()), "a black scene never changes"

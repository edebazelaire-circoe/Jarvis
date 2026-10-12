"""The 9-scene flow, recorded and measured on its real pixels (handoff jarvis-remotion-native-studio-playback-fix, Slice 14).

VRAI Core, VRAI Control Center, VRAI Chrome sans tête, VRAI Player Remotion de Variantes, sur des ports libres et une racine jetable
(`RemotionStack`) ; jamais le Jarvis vivant. Same 9-scene gate deck as Slices 03 and 05 (`presentation_playback_gate_world.DECK`: 3, 8
and 30 s scenes, 24 to 60 i/s, a score that aims at 8 s per item), same page probe, same « Lire » of Variants. Opt-in:
`JARVIS_REMOTION_RUNTIME_DIR`, Node and Chrome; skipped otherwise.

Added by this Slice: the whole play is RECORDED (`record` action of `_remotion_stage_browser.mjs`: one JPEG of the Variants Player about
every 100 ms, each with the Player's own frame and the transport slider read at the same instant), and the recording is measured with the
pure detectors of `jarvis.media.frame_quality`:

- transition flash: no black or blank capture (`flash_findings`), at any hand-over;
- time carry: every scene enters on its frame 0 (`playback_findings`);
- stale progress bar: the transport slider stays on the composition frame derived from the Player's clock (`composition_clock`), and the
  scene's own drawn progress bar matches the scene's frame (`stale_progress_findings`, `bar_share`);
- cut at 8 s: every scene plays to its last frame for its authored length, the 30 s one included (`playback_findings`);
- frozen playback: no run of identical pictures while it plays (`frozen_spans`).

The scene's page (fonts, assets, text out of the frame) is read scene by scene in `test_remotion_frame_quality_real.py` (`page_pass`).

A negative control plants a black layer and a held slider in the PAGE (never in the product): the same measure must catch both.

Evidence (`JARVIS_QUALITY_EVIDENCE_DIR`): `flow.mp4` (the complete play, 10 i/s, 640 px, CRF 34), `flow-markers.json` (the deterministic
composition markers of every scene beside where each scene was seen in the video), `flow-contact.jpg` (per scene: first, middle and last
capture), `flow-transitions.jpg` (per hand-over: the capture before and after), `flow.json` (metrics, findings, durations).
"""

from __future__ import annotations

from pathlib import Path
import shutil
import time

import pytest

from jarvis.adapters.remotion_media_tools import contact_sheet, decode_gray_batch, encode_flow_video, probe_video
from jarvis.domain.composition_clock import SceneManifest, build_composition
from jarvis.media import frame_quality as Q
from tests.fakes.remotion_player_stack import RemotionStack, runtime_dir_from_env
from tests.unit.presentation_playback_gate_world import (
    DECK, PAGE_PROBE, PREFABS, READ_PROBE, SCENE_IDS, VISIBLE_RECT, VSTATE, frames_of, harness, make_deck, run_long,
)
from tests.unit.remotion_quality_world import media_tools, write_evidence
from tests.unit.test_presentation_continuous_playback_browser import EXPLORER_READY, LIRE, PHASE, per_scene

RUNTIME = runtime_dir_from_env()
pytestmark = pytest.mark.skipif(RUNTIME is None or shutil.which("node") is None,
                                reason="needs JARVIS_REMOTION_RUNTIME_DIR (an existing Remotion install), node and Chrome")

ENDED = f"({PHASE}==='ended')"
#: Read with every capture: the Variants Player's own frame and the transport slider (composition frame), in one evaluation.
READ_ONE = (f"(()=>{{const s={VSTATE};const sl=document.querySelector('#jvStudioExplorer [role=\"slider\"]');"
            "return {s,slider:sl&&sl.getAttribute('aria-valuenow')!==null?+sl.getAttribute('aria-valuenow'):null}})()")
CAPTURE_EVERY_MS = 100


def composition():
    return build_composition([SceneManifest(SCENE_IDS[k], "Scene", fps, seconds * fps) for k, (seconds, fps, _a, _b) in enumerate(DECK)])


def markers(cmap, rec: list) -> list[dict]:
    """Deterministic markers (composition frames and ms, from the manifests only) beside the video time of the first capture of each scene."""

    t0 = rec[0][0]
    seen: dict[str, int] = {}
    for ms, _file, read in rec:
        scene = ((read or {}).get("s") or {}).get("scene")
        if scene and scene not in seen:
            seen[scene] = ms - t0
    out = []
    for span in cmap.scenes:
        label = f"S{span.index + 1}"
        out.append({"scene": label, "scene_id": span.scene_id, "fps": span.fps, "duration_in_frames": span.duration_in_frames,
                    "start_frame": span.start, "start_ms": round(1000 * span.start / cmap.fps), "end_ms": round(1000 * span.end / cmap.fps),
                    "seen_in_video_ms": seen.get(label)})
    return out


def measure_recording(ffmpeg, rec: list, cmap):
    """Captures -> `(files, luma frames, findings, samples)`: transition flash on every capture, stale progress (transport and the scene's
    own bar) on every capture of a playing scene that is not in the middle of a hand-over."""

    files = [Path(f) for _ms, f, _r in rec]
    frames = decode_gray_batch(ffmpeg, files)
    metrics = [Q.measure(g) for g in frames]
    findings: list[Q.Finding] = Q.flash_findings([(ms, m) for (ms, _f, _r), m in zip(rec, metrics)])
    # stale progress: transport (composition frame) and the scene's own bar against the Player's frame of the same instant
    samples = []
    reads_s = [((r or {}).get("s") or {}) for _ms, _f, r in rec]
    for i, ((ms, _f, read), gray) in enumerate(zip(rec, frames)):
        s = reads_s[i]
        if not s.get("playing") or not s.get("scene") or s.get("frame") is None:
            continue
        if i + 1 < len(rec) and reads_s[i + 1].get("scene") != s["scene"]:
            continue   # a hand-over happens between this read and the next: the pixels may already be the next scene's (checked by flash / carry)
        k = int(s["scene"][1:]) - 1
        duration, fps = frames_of(k), DECK[k][1]
        nxt = next((reads_s[j] for j in range(i + 1, len(rec)) if reads_s[j].get("scene") == s["scene"]), s)
        gap_ms = (rec[i + 1][0] - ms) if i + 1 < len(rec) else CAPTURE_EVERY_MS
        # what the sampling cannot know: the Player's frame read moves in steps (the next read of the same Player bounds it) and the
        # pixels are captured up to one interval after the read
        drift = abs(int(nxt.get("frame") or s["frame"]) - s["frame"]) + gap_ms / 1000 * fps
        samples.append({"ms": ms, "transport": read.get("slider"), "expected": cmap.frame_of(k, min(s["frame"], duration - 1)),
                        "transport_tolerance": round(drift * cmap.fps / fps), "bar_share": Q.bar_share(gray),
                        "local_share": s["frame"] / (duration - 1), "bar_tolerance": drift / (duration - 1)})
    findings += Q.stale_progress_findings(samples, fps=cmap.fps)
    return files, frames, findings, samples


async def test_the_recorded_nine_scene_flow_has_no_flash_carry_stale_bar_cut_or_freeze(tmp_path):
    ffmpeg, ffprobe = media_tools(RUNTIME)
    shots = tmp_path / "rec"
    shots.mkdir()
    cmap = composition()
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _vid = await make_deck(stack)
        for prefab in PREFABS:   # compiled once, like a deck already previewed (the Slice 05 measure is warm too)
            status, _h, _t = await stack.get(f"/api/remotion/player/{prefab}/1")
            harness(status == 200, f"{prefab} did not compile")
        plan: list[dict] = [{"until": "!!window.JarvisStudioExplorer", "ms": 20000, "required": True, "as": "explorer_api"}, {"eval": PAGE_PROBE},
                            {"eval": f"JarvisStudioExplorer.open({{presentation_id:'{pid}',fullscreen:false}})"}, {**EXPLORER_READY, "required": True,
                                                                                                                   "as": "explorer_ready"},
                            {"wait": 1500}, {"eval": f"window.__clip={VISIBLE_RECT}"}, {"clickExpr": LIRE},
                            {"until": f"({PHASE}==='playing')", "ms": 30000, "required": True, "as": "playing"},
                            {"record": str(shots), "ms": 150000, "everyMs": CAPTURE_EVERY_MS, "untilExpr": ENDED, "readExpr": READ_ONE,
                             "clipExpr": "window.__clip", "scale": 0.5, "quality": 55, "as": "rec"},
                            {"wait": 1500}, {"value": "after_hold", "expr": VSTATE}, {"value": "probe", "expr": READ_PROBE}]
        began = time.time()
        result = await run_long(stack.page_url, plan, timeout=540)
        wall = round(time.time() - began, 1)
    reads = result["reads"]
    harness("failed" not in reads, reads.get("failed"))
    rec = reads.get("rec") or []
    harness(len(rec) > 100, f"too few captures: {len(rec)}")
    files, frames, findings, samples = measure_recording(ffmpeg, rec, cmap)
    probe = reads.get("probe")
    harness(probe, "no page probe")
    scenes = per_scene(probe, "explorer")
    rows = [{"scene": s["scene"], "duration_in_frames": frames_of(int(s["scene"][1:]) - 1), "fps": DECK[int(s["scene"][1:]) - 1][1],
             "max_frame": s["max_frame"], "played_ms": s["played_ms"], "first_frame": (s["first_play"] or [None, None])[1]}
            for s in scenes[1:]]   # S1 was the preview's scene before « Lire » (Slice 05: its first play may be the preview's own)
    findings += Q.playback_findings(rows)
    findings += Q.frozen_spans([(ms, g, bool(((r or {}).get("s") or {}).get("playing"))) for (ms, _f, r), g in zip(rec, frames)])
    # evidence: video, markers, per-scene and per-transition sheets
    timed = [(files[i], max(0.02, (rec[i + 1][0] - rec[i][0]) / 1000 if i + 1 < len(rec) else CAPTURE_EVERY_MS / 1000)) for i in range(len(rec))]
    video = encode_flow_video(ffmpeg, timed, out=tmp_path / "flow.mp4")
    facts = probe_video(ffprobe, video)
    by_scene: dict[str, list[int]] = {}
    changes: list[int] = []
    previous = None
    for i, (_ms, _f, read) in enumerate(rec):
        scene = ((read or {}).get("s") or {}).get("scene")
        if scene:
            by_scene.setdefault(scene, []).append(i)
            if previous and scene != previous:
                changes.append(i)
            previous = scene
    cells = []
    for k in range(len(DECK)):
        seen = by_scene.get(f"S{k + 1}", [])
        cells += [files[seen[0]], files[seen[len(seen) // 2]], files[seen[-1]]] if seen else [None, None, None]
    flow_contact = contact_sheet(ffmpeg, cells, columns=3, out=tmp_path / "flow-contact.jpg")
    pairs = [p for i in changes for p in (files[i - 1], files[i])]
    flow_transitions = contact_sheet(ffmpeg, pairs, columns=2, out=tmp_path / "flow-transitions.jpg") if pairs else None
    mark = markers(cmap, rec)
    report = Q.report_sections(findings)
    evidence = {"wall_s": wall, "captures": len(rec), "capture_every_ms": CAPTURE_EVERY_MS,
                "recorded_ms": rec[-1][0] - rec[0][0], "composition_ms": round(1000 * cmap.total_frames / cmap.fps), "video": facts,
                "scenes": rows, "scene_changes_in_video": [{"at_ms": rec[i][0] - rec[0][0], "to": rec[i][2]["s"]["scene"]} for i in changes],
                "stale_samples": len(samples),
                # the measured margins behind the stale-progress thresholds (false-positive evidence)
                "transport_gap_ms_max": max((round(abs(x["transport"] - x["expected"]) * 1000 / cmap.fps) for x in samples
                                             if x["transport"] is not None), default=None),
                "scene_bar_gap_max": round(max((abs(x["bar_share"] - x["local_share"]) for x in samples), default=0.0), 3),
                "scene_bar_gap_beyond_sampling_max": round(max((abs(x["bar_share"] - x["local_share"]) - x["bar_tolerance"] for x in samples),
                                                               default=0.0), 3),
                "held_after_end": reads.get("after_hold"), "report": report,
                "console_errors": [line for line in result.get("console", []) if "error" in str(line).lower()][:20]}
    write_evidence("flow", evidence, {"flow.mp4": video, "flow-contact.jpg": flow_contact,
                                      **({"flow-transitions.jpg": flow_transitions} if flow_transitions else {})})
    write_evidence("flow-markers", {"composition_fps": cmap.fps, "total_frames": cmap.total_frames, "markers": mark})
    shutil.rmtree(shots, ignore_errors=True)   # keep only the committed evidence (disk)
    blocking = [f.to_dict() for f in findings if f.severity is Q.Severity.BLOCKING]
    assert blocking == [], blocking
    assert [f.to_dict() for f in findings if f.code == "frozen_playback"] == [], "the gate deck's scenes move on every frame"
    assert [s["scene"] for s in scenes][-9:] == [f"S{n}" for n in range(1, 10)], [s["scene"] for s in scenes]
    assert len(changes) == 8 and all(m["seen_in_video_ms"] is not None for m in mark), mark
    assert facts["codec"] == "h264" and facts["duration_ms"] >= 0.95 * evidence["composition_ms"], facts


#: Negative control, planted in the PAGE (never in the product): a black layer over the Player for 500 ms across the S1 -> S2 hand-over,
#: and a transport slider held on frame 0. The same measure must then find a transition flash and a stale progress bar.
PLANT = ("(()=>{const c=window.__clip;const d=document.createElement('div');d.style.cssText='position:fixed;left:'+c.x+'px;top:'+c.y+'px;width:'"
         "+c.width+'px;height:'+c.height+'px;background:#000;z-index:2147483647;display:none';document.body.appendChild(d);"
         "setTimeout(()=>{d.style.display='block';setTimeout(()=>{d.style.display='none'},500)},2700);"
         "const sl=document.querySelector('#jvStudioExplorer [role=\"slider\"]');if(sl)new MutationObserver(()=>{"
         "if(sl.getAttribute('aria-valuenow')!=='0')sl.setAttribute('aria-valuenow','0')}).observe(sl,{attributes:true,attributeFilter:['aria-valuenow']});"
         "return !!sl})()")
S2_UNDER_WAY = f"(()=>{{const s={VSTATE};return !!s&&s.scene==='S2'&&s.frame>=90}})()"


async def test_a_planted_flash_and_a_held_transport_are_caught_on_the_real_captures(tmp_path):
    ffmpeg, _ffprobe = media_tools(RUNTIME)
    shots = tmp_path / "rec"
    shots.mkdir()
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _vid = await make_deck(stack)
        for prefab in PREFABS[:2]:
            status, _h, _t = await stack.get(f"/api/remotion/player/{prefab}/1")
            harness(status == 200, f"{prefab} did not compile")
        plan = [{"until": "!!window.JarvisStudioExplorer", "ms": 20000, "required": True, "as": "explorer_api"}, {"eval": PAGE_PROBE},
                {"eval": f"JarvisStudioExplorer.open({{presentation_id:'{pid}',fullscreen:false}})"}, {**EXPLORER_READY, "required": True,
                                                                                                       "as": "explorer_ready"},
                {"wait": 1500}, {"eval": f"window.__clip={VISIBLE_RECT}"}, {"clickExpr": LIRE},
                {"until": f"({PHASE}==='playing')", "ms": 30000, "required": True, "as": "playing"}, {"value": "planted", "expr": PLANT},
                {"record": str(shots), "ms": 20000, "everyMs": CAPTURE_EVERY_MS, "untilExpr": S2_UNDER_WAY, "readExpr": READ_ONE,
                 "clipExpr": "window.__clip", "scale": 0.5, "quality": 55, "as": "rec"}]
        result = await run_long(stack.page_url, plan, timeout=240)
    reads = result["reads"]
    harness("failed" not in reads and reads.get("planted") is True, reads.get("failed") or "the slider was not found to hold")
    _files, _frames, findings, samples = measure_recording(ffmpeg, reads.get("rec") or [], composition())
    found = sorted({f.code for f in findings})
    write_evidence("flow-negative-control", {"captures": len(reads.get("rec") or []), "stale_samples": len(samples), "codes": found,
                                             "findings": [f.to_dict() for f in findings][:12]})
    shutil.rmtree(shots, ignore_errors=True)
    assert "transition_flash" in found and "stale_progress" in found, found

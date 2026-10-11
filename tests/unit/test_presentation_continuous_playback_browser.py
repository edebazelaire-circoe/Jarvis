"""Lecture continue de bout en bout (handoff jarvis-remotion-native-studio-playback-fix, Slice 05), dans un VRAI Chrome.

VRAI Core, VRAI Control Center, VRAI Player Remotion, sur des ports libres et une racine jetable (`RemotionStack`), jamais le Jarvis
vivant. Même présentation de 9 scènes que la porte de la Slice 03 (`presentation_playback_gate_world.DECK` : 3 s, 8 s et 30 s, de 24 à
60 i/s, une partition qui vise 8 s par élément), même sonde de page. Opt-in : `JARVIS_REMOTION_RUNTIME_DIR`, Node et Chrome ; sinon ignoré.

Mesuré à chaque frontière : dernière image du Player qui sort, première image du Player qui entre, écart (ms), captures blanches, vides ou
hybrides (une capture dont les couleurs disent la scène k+1 pendant que le cadre visible est encore celui de la scène k). Deux surfaces :

- Variantes (la surface du contrat, § 2) : « Lire » enchaîne les 9 scènes dans le lecteur intégré, Variantes reste ouvert, Core ne lance
  aucune lecture ; la scène de 30 s joue ses 900 images ; la dernière image est tenue ;
- la fenêtre de scène d'une lecture `all` (retirée par la Slice 09, mais elle partage l'hôte) : plus aucune scène sautée.

Preuves (JSON + PNG réduits, chemin personnel masqué) : `JARVIS_PLAYBACK_GATE_EVIDENCE_DIR`, en pratique
`tasks/jarvis-remotion-native-studio-playback-fix/slices/05-continuous-remotion-sequencing/evidence/`.

Les aides de mesure viennent de `presentation_playback_gate_world.py` (Slice 03), importées telles quelles (jamais modifiées ici).
"""

from __future__ import annotations

import shutil
import time

import pytest

from tests.fakes.remotion_player_stack import RemotionStack, runtime_dir_from_env
from tests.unit.presentation_playback_gate_world import (
    DECK, PAGE_PROBE, PLAYBACK, PREFABS, READ_PROBE, VISIBLE, VISIBLE_RECT, CorePoller, blank_spans, bursts_classified, first_play,
    frame_rows, frames_of, make_deck, next_boundary, player_clocks, record, run_long, transition_shots, wraps,
)
from tests.unit.test_remotion_player_realpage_browser import http_step

RUNTIME = runtime_dir_from_env()
pytestmark = pytest.mark.skipif(RUNTIME is None or shutil.which("node") is None,
                                reason="needs JARVIS_REMOTION_RUNTIME_DIR (an existing Remotion install), node and Chrome")

EXPLORER_READY = {"until": "(()=>{const f=[...document.querySelectorAll('#jvStudioExplorer iframe[data-remotion-stage]')].find(x=>!x.classList.contains('sc-prefab-staged'));"
                           "try{return !!f&&f.contentWindow.__remotionStage.state().phase==='ready'}catch(e){return false}})()", "ms": 120000}
LIRE = ("(()=>{const b=document.querySelector('#jvStudioExplorer .jvx-play button[data-act=\"continuous\"]');if(!b)return null;"
        "const r=b.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()")
PHASE = "(window.JarvisStudioExplorer&&JarvisStudioExplorer.playback.view().phase)"
ENDED = f"({PHASE}==='ended')"
STATE = f"(()=>{{const f={VISIBLE};try{{return f?f.contentWindow.__remotionStage.state():null}}catch(e){{return null}}}})()"
#: The run is over on the stage window: S9 (240 frames) holds its last frame.
RUN_FINAL = f"(()=>{{const s={STATE};return !!s&&s.duration===240&&s.frame===239&&!s.playing}})()"
LABEL = "(()=>{const b=document.querySelector('#jvStudioExplorer .jvx-play button[data-act=\"continuous\"]');return b?b.textContent.trim():null})()"


def harness(ok: object, why: object) -> None:
    if not ok:
        pytest.fail(f"harness: {why}")


def scene_of_uid(probe: dict) -> dict[int, str]:
    return {row[2]: row[4] for row in probe["ev"] if row[1] == "mount"}


def visible_uid_at(probe: dict, ms: int, place: str) -> int | None:
    """The frame the page showed at `ms` (last sampler row at or before it)."""

    shown = None
    for at, rec in probe["rows"]:
        if at > ms:
            break
        shown = next((uid for uid, p, v, *_ in rec if v and p == place), shown)
    return shown


def play_after(probe: dict, uid: int, ms: int) -> tuple[int, int] | None:
    """`(ms, frame)` of the first `playing` clock of this Player once it was on screen. A frame loaded ahead may blip `playing` at its
    stage page's `ready` before the host pauses it on frame 0 (hidden, Slice 06 removes the stage's own play-on-ready): not its start."""

    return next(((at, frame) for at, frame, playing in player_clocks(probe).get(uid, []) if playing and at >= ms - 50), None)


def boundaries(probe: dict, place: str) -> list[dict]:
    """Per scene change on screen: the outgoing Player's last frame and when it was reached, the incoming Player's first frame and when it
    started to move, the gap between the two, and when the incoming frame became the visible one."""

    clocks = player_clocks(probe)
    scene_of = scene_of_uid(probe)
    lives = [(row[0], row[2]) for row in probe["ev"] if row[1] == "live" and scene_of.get(row[2])]
    out = []
    for (_ms_a, a), (live_b, b) in zip(lives, lives[1:]):
        scene_a, scene_b = scene_of.get(a), scene_of.get(b)
        if not scene_a or not scene_b or scene_a == scene_b:
            continue
        last_a = max(clocks.get(a, []), key=lambda c: c[1], default=None)
        end_a = next((c for c in clocks.get(a, []) if last_a and c[1] == last_a[1]), None)
        start_b = play_after(probe, b, live_b)
        out.append({"from": scene_a, "to": scene_b, "out_last_frame": last_a[1] if last_a else None,
                    "out_expected_last": frames_of(int(scene_a[1:]) - 1) - 1, "out_end_ms": end_a[0] if end_a else None,
                    "in_live_ms": live_b, "in_first_frame": start_b[1] if start_b else None, "in_first_play_ms": start_b[0] if start_b else None,
                    "gap_ms": None if not (end_a and start_b) else start_b[0] - end_a[0]})
    return out


def per_scene(probe: dict, place: str) -> list[dict]:
    clocks = player_clocks(probe)
    scene_of = scene_of_uid(probe)
    rows = frame_rows(probe)
    shown = []
    for ms, uid in [(row[0], row[2]) for row in probe["ev"] if row[1] == "live"]:
        scene = scene_of.get(uid)
        if not scene:
            continue
        own = clocks.get(uid, [])
        start = play_after(probe, uid, ms) if shown else first_play(probe, uid)
        end = next((c for c in own if c[1] == frames_of(int(scene[1:]) - 1) - 1 and (start is None or c[0] >= start[0])), None)
        shown.append({"uid": uid, "scene": scene, "live_ms": ms, "first_play": start, "max_frame": max((c[1] for c in own), default=None),
                      "played_ms": None if not (start and end) else end[0] - start[0],
                      "wraps": wraps([c for c in own if start is None or c[0] >= start[0]]),
                      "duration": next((s[5] for s in rows.get(uid, []) if s[5]), None)})
    return shown


def hybrids(probe: dict, bursts: dict, place: str) -> list[dict]:
    """Captures whose colours say one scene while the page shows another scene's frame (the Slice 03 hybrid frame), plus blank captures.

    A capture is stamped when it is REQUESTED (`performance.now()` before `Page.captureScreenshot`); its pixels are from some moment up
    to the next request. Colours of scene k+1 are therefore legitimate when scene k+1's frame became the visible one before that next
    request. Anything else (scene k+1's colours while scene k's frame is still the one on screen, or no scene at all) is reported."""

    scene_of = scene_of_uid(probe)
    lives: dict[str, list[int]] = {}
    for row in probe["ev"]:
        if row[1] == "live" and scene_of.get(row[2]):
            lives.setdefault(scene_of[row[2]], []).append(row[0])
    bad = []
    for key, shots in bursts.items():
        for index, (raw_ms, cls, name) in enumerate(shots):
            ms = round(raw_ms - probe["t0"])   # the burst is stamped with the page's `performance.now()`, the probe from its own start
            until = round(shots[index + 1][0] - probe["t0"]) if index + 1 < len(shots) else ms + 100
            uid = visible_uid_at(probe, ms, place)
            expected = scene_of.get(uid) if uid else None
            if cls.startswith("S") and (cls == expected or any(ms - 50 <= live <= until for live in lives.get(cls, []))):
                continue
            bad.append({"burst": key, "ms": ms, "next_shot_ms": until, "pixels": cls, "visible_frame_scene": expected, "file": name})
    return bad


# ---------------------------------------------------------------------------------------------------------------- Variants

async def test_variants_plays_the_whole_deck_continuously_each_scene_from_frame_zero_for_its_authored_length(tmp_path):
    """PX-5 / PX-6 in Variants: « Lire » plays S1 frame 0 to the final frame of S9 with no stop, no blank and no hybrid frame; every scene
    starts on its frame 0 and plays all of its frames (the 30 s scene its 900 frames, not cut at its 8 s target); Variants stays open, Core
    starts no run; the final frame is held."""

    shots = tmp_path / "shots"
    shots.mkdir()
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _vid = await make_deck(stack)
        for prefab in PREFABS:   # compile every scene once, like a deck that was already previewed: the hand-overs are then measured warm
            status, _h, _t = await stack.get(f"/api/remotion/player/{prefab}/1")
            assert status == 200, prefab
        plan: list[dict] = [{"until": "!!window.JarvisStudioExplorer", "ms": 20000}, {"eval": PAGE_PROBE},
                            {"eval": f"JarvisStudioExplorer.open({{presentation_id:'{pid}',fullscreen:false}})"}, EXPLORER_READY, {"wait": 1500},
                            {"eval": f"window.__clip={VISIBLE_RECT}"}, {"value": "label_before", "expr": LABEL}, {"clickExpr": LIRE},
                            {"until": f"({PHASE}==='playing')", "ms": 30000}, {"value": "label_playing", "expr": LABEL}]
        for boundary in range(1, 9):
            plan += [{"until": f"({next_boundary()})||{ENDED}", "ms": 70000, "required": True, "as": f"variants_boundary_{boundary}"},
                     {"burst": str(shots), "ms": 1600, "clipExpr": "window.__clip", "prefix": f"v{boundary}", "as": f"burst{boundary}"}]
        plan += [{"until": ENDED, "ms": 70000, "required": True, "as": "variants_ended"}, {"value": "ended_at", "expr": "Math.round(performance.now()-__pg.t0)"},
                 {"wait": 5000}, {"value": "after_hold", "expr": STATE}, {"value": "label_end", "expr": LABEL},
                 {"value": "open", "expr": "JarvisStudioExplorer.isOpen()"}, {"value": "view", "expr": "JarvisStudioExplorer.playback.view()"},
                 {"value": "stats", "expr": "JarvisStudioExplorer.playback.stats()"}, {"shot": str(tmp_path / "variants-end.png")},
                 {"value": "probe", "expr": READ_PROBE}, http_step(stack, "core", "GET", PLAYBACK)]
        async with CorePoller(stack) as poll:
            began = time.time()
            result = await run_long(stack.page_url, plan, timeout=900)
            took = time.time() - began
        reads = result["reads"]
        probe = reads.get("probe")
        harness(probe, reads.get("failed"))
        bursts = {k: bursts_classified(v) for k, v in reads.items() if k.startswith("burst") and isinstance(v, list)}
        evidence = {"wall_s": round(took, 1), "failed": reads.get("failed"), "labels": [reads.get("label_before"), reads.get("label_playing"), reads.get("label_end")],
                    "explorer_open_at_end": reads.get("open"), "view_end": reads.get("view"), "held_after_5s": reads.get("after_hold"),
                    "sequencer_boundaries": (reads.get("stats") or {}).get("boundaries"),
                    "boundaries": boundaries(probe, "explorer"), "scenes": per_scene(probe, "explorer"),
                    "blank_spans_ms": blank_spans(probe, place="explorer"), "hybrid_or_blank_captures": hybrids(probe, bursts, "explorer"),
                    "captures": {k: len(v) for k, v in bursts.items()},
                    "core_runs_seen": sorted({r.get("phase") for r in poll.rows if r.get("phase")}),
                    "orders": [row for row in probe["ev"] if row[1] == "order"], "console_errors": [l for l in result.get("console", []) if "error" in str(l).lower()][:20]}
        picked = [p for burst in bursts.values() for p in transition_shots(burst, shots, 2)]
        record("variants_continuous", evidence, picked + [tmp_path / "variants-end.png"])
        harness("failed" not in reads, reads.get("failed"))
        assert evidence["labels"] == ["Lire", "Pause", "Rejouer"], evidence["labels"]
        assert evidence["explorer_open_at_end"] is True, "Variants never closes to play"
        assert set(evidence["core_runs_seen"]) <= {"idle", "stopped"}, f"Core started a run: {evidence['core_runs_seen']}"
        shown = [s["scene"] for s in evidence["scenes"]]
        assert shown[-9:] == [f"S{n}" for n in range(1, 10)] and len(shown) == 9, f"scenes shown in order, once each: {shown}"
        for scene in evidence["scenes"][1:]:   # S1 was the preview's scene before « Lire »: its first play may be the preview's own
            n = int(scene["scene"][1:]) - 1
            assert scene["first_play"] and scene["first_play"][1] == 0, scene
            assert scene["max_frame"] == frames_of(n) - 1 and scene["wraps"] == [], scene
        s3 = next(s for s in evidence["scenes"] if s["scene"] == "S3")
        assert s3["max_frame"] == 899 and s3["played_ms"] is not None and s3["played_ms"] >= 29000, s3
        for b in evidence["boundaries"]:
            assert b["out_last_frame"] == b["out_expected_last"] and b["in_first_frame"] == 0, b
        assert evidence["blank_spans_ms"] == [], evidence["blank_spans_ms"]
        assert evidence["hybrid_or_blank_captures"] == [], evidence["hybrid_or_blank_captures"]
        held = evidence["held_after_5s"]
        assert held and held["frame"] == held["duration"] - 1 and held["playing"] is False, f"the final frame is held: {held}"
        assert evidence["view_end"]["phase"] == "ended" and evidence["view_end"]["frame"] == evidence["view_end"]["total_frames"] - 1


# ---------------------------------------------------------------------------------------------------------------- run stage

async def test_the_run_stage_chained_play_shows_every_scene_from_frame_zero_without_a_skip(tmp_path):
    """The shared host fixes on the run stage window (until Slice 09 retires it): `scope: all` from cold compiles shows the 9 scenes in order,
    each from frame 0 to its last frame; no scene skipped, no blank, no hybrid frame; no Core deadline moves a scene."""

    shots = tmp_path / "shots"
    shots.mkdir()
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _vid = await make_deck(stack)
        status, started = await stack.call("POST", f"{PLAYBACK}/start", json={
            "actor": "user", "presentation_id": pid, "role": "user_presenter", "scope": "all"})
        assert status == 200 and started["state"]["scope"] == "all", started
        ready = {"until": f"(()=>{{const s={STATE};return !!s&&s.phase==='ready'}})()", "ms": 120000}
        plan: list[dict] = [{"eval": PAGE_PROBE}, ready]
        for boundary in range(1, 9):
            plan += [{"until": f"({next_boundary()})||({RUN_FINAL})", "ms": 150000, "required": True, "as": f"run_boundary_{boundary}"},
                     {"burst": str(shots), "ms": 1600, "clipExpr": VISIBLE_RECT, "prefix": f"r{boundary}", "as": f"burst{boundary}"}]
        plan += [{"until": RUN_FINAL, "ms": 150000, "required": True, "as": "run_final"}, {"wait": 3000}, {"value": "probe", "expr": READ_PROBE},
                 http_step(stack, "where", "GET", PLAYBACK)]
        async with CorePoller(stack) as poll:
            began = time.time()
            result = await run_long(stack.page_url, plan, timeout=1200)
            took = time.time() - began
        reads = result["reads"]
        probe = reads.get("probe")
        harness(probe, reads.get("failed"))
        bursts = {k: bursts_classified(v) for k, v in reads.items() if k.startswith("burst") and isinstance(v, list)}
        state = ((reads.get("where") or {}).get("body") or {}).get("state") or {}
        evidence = {"wall_s": round(took, 1), "expected_s": sum(s for s, _f, _a, _b in DECK), "failed": reads.get("failed"),
                    "boundaries": boundaries(probe, "board"), "scenes": per_scene(probe, "board"),
                    "blank_spans_ms": blank_spans(probe, place="board"), "hybrid_or_blank_captures": hybrids(probe, bursts, "board"),
                    "core_scenes_entered": sorted({r.get("scene") for r in poll.rows if r.get("scene")}),
                    "where_end": {k: state.get(k) for k in ("phase", "scope", "position")},
                    "deadline_traces": [k for k in stack.kinds() if "autoplay_deadline" in k],
                    "page_segments": [row for row in probe["ev"] if row[1] in ("tl", "segment", "order")], "core": poll.rows}
        picked = [p for burst in bursts.values() for p in transition_shots(burst, shots, 2)]
        record("run_stage_continuous", evidence, picked)
        harness("failed" not in reads, reads.get("failed"))
        shown = [s["scene"] for s in evidence["scenes"]]
        assert shown == [f"S{n}" for n in range(1, 10)], f"scenes shown: {shown}"
        for scene in evidence["scenes"]:
            n = int(scene["scene"][1:]) - 1
            assert scene["first_play"] and scene["first_play"][1] == 0, scene
            assert scene["max_frame"] == frames_of(n) - 1 and scene["wraps"] == [], scene
        assert evidence["blank_spans_ms"] == [], evidence["blank_spans_ms"]
        assert evidence["hybrid_or_blank_captures"] == [], evidence["hybrid_or_blank_captures"]

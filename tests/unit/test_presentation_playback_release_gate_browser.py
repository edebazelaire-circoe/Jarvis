"""Porte de release « lecture de présentation » (handoff jarvis-remotion-native-studio-playback-fix, Slice 03).

VRAI Core, VRAI Control Center, VRAI Chrome sans tête, VRAI Player Remotion, sur des ports libres et une racine jetable
(`RemotionStack`) ; jamais le Jarvis vivant. Opt-in comme les autres épreuves Remotion réelles : `JARVIS_REMOTION_RUNTIME_DIR` = le
dossier `runtime/` d'une installation Remotion existante (jamais une installation de plus), Node et Chrome ; sinon tout est ignoré.

Cible normative : `docs/presentation-studio.md` > *Presentation experience contract (Level 2, 2026-10)* (§ 2 un seul Player, celui de
Variantes ; § 3 une seule horloge, la composition, Core n'a pas d'horloge média ; § 4 transport de la vidéo continue ; § 5 présentation
contre vidéo). Chaque épreuve affirme le comportement du CONTRAT sur une présentation de 9 scènes aux durées et cadences mêlées
(`presentation_playback_gate_world.DECK`) ; celles qui échouent sur la base de la tâche sont `xfail(strict=True, raises=AssertionError)`
avec le défaut et la Slice qui le corrige : une correction conforme au contrat les fait passer (XPASS strict = retirer la marque).

Une mesure cassée (pilote, précondition expirée, refus de Core au montage du décor) n'est jamais « attendue » : elle passe par
`harness()` (`pytest.fail`), jamais par `AssertionError`. Les contrôles sont trouvés par rôle et nom du contrat (barre « Lire », menu
« Lire seulement cette scène », `role="slider"`, liste des scènes) ; les sélecteurs d'aujourd'hui (`.jvx-play`, `.rs-scrub`, `.rs-time`,
la bande `#jvStudioBand` de FINAL) ne servent qu'à mesurer le défaut actuel et sont reciblés sur le Player de Variantes par les
Slices 06/09/10. Constats : `tasks/jarvis-remotion-native-studio-playback-fix/slices/03-reproduce-timeline-and-transition-failures/evidence/`.

    JARVIS_REMOTION_RUNTIME_DIR=<runtime> [JARVIS_PLAYBACK_GATE_EVIDENCE_DIR=<dossier>] \\
      python -m pytest tests/unit/test_presentation_playback_release_gate_browser.py -q -p no:cacheprovider -k "not play_all_shows"
    (puis `-k play_all_shows` seul : environ 4 min aujourd'hui, à cause de l'arrêt mesuré)
"""

from __future__ import annotations

import shutil
import time

import pytest

from tests.fakes.remotion_player_stack import RemotionStack, runtime_dir_from_env
from tests.unit.presentation_playback_gate_world import (
    DECK, PAGE_PROBE, PLAYBACK, READ_PROBE, READOUTS, SCENE_IDS, TARGET_MS, VISIBLE, VISIBLE_RECT, VSTATE, CorePoller, blank_spans,
    bursts_classified, first_play, frame_rows, frames_of, gesture, harness, make_deck, next_boundary, open_variants, player_clocks,
    readout_problems, record, run_long, run_state, scrub_to, thumbnail, transition_shots, variants_scene_ready, wraps,
)
from tests.unit.test_remotion_player_realpage_browser import http_step

RUNTIME = runtime_dir_from_env()
pytestmark = pytest.mark.skipif(RUNTIME is None or shutil.which("node") is None,
                                reason="needs JARVIS_REMOTION_RUNTIME_DIR (an existing Remotion install), node and Chrome")

STATE = f"(()=>{{const f={VISIBLE};try{{return f?f.contentWindow.__remotionStage.state():null}}catch(e){{return null}}}})()"
READY = {"until": f"(()=>{{const s={STATE};return !!s&&s.phase==='ready'}})()", "ms": 90000, "required": True, "as": "ready"}
#: The run is over: the last scene (S9, 240 frames) holds its last frame and the band says scene 9/9 (band: today only, Slice 09 retargets).
FINAL = (f"(()=>{{const s={STATE};const w=document.querySelector('#jvStudioBand .jvsp-where');"
         f"return !!s&&s.duration===240&&s.frame===239&&!s.playing&&!!w&&w.textContent.includes('Scène 9/9')}})()")
NOW = {"expr": "Math.round(performance.now()-__pg.t0)"}


def scene_of_uid(probe: dict) -> dict[int, str]:
    return {row[2]: row[4] for row in probe["ev"] if row[1] == "mount"}


def variants_uids(probe: dict, scene: str) -> list[int]:
    return [row[2] for row in probe["ev"] if row[1] == "mount" and row[3] == "explorer" and row[4] == scene]


def frame_orders_after(probe: dict, since_ms: int) -> list:
    """Host orders that carry a frame (a seek / a play from a frame) given to any Player after `since_ms`."""

    return [row for row in probe.get("ev", []) if row[1] == "order" and row[0] >= since_ms and row[4] is not None]


def core_enter_ms(core_rows: list[dict], epoch: int) -> dict[int, int]:
    out: dict[int, int] = {}
    for row in core_rows:
        if row.get("scene") and row["scene"] not in out:
            out[row["scene"]] = row["at"] - epoch
    return out


def http(stack: RemotionStack, name: str, method: str, path: str, body: dict | None = None) -> dict:
    return http_step(stack, name, method, path, body)


def core_view(answer: dict | None) -> dict | None:
    state = ((answer or {}).get("body") or {}).get("state") or {}
    tl = state.get("timeline") or {}
    return {"scope": state.get("scope"), "phase": state.get("phase"), "scene": (state.get("scene") or {}).get("number"),
            "play_ms": tl.get("play_ms"), "from": tl.get("from_frame"), "until": tl.get("until_frame"), "seq": tl.get("seq"),
            "item_ms": (state.get("elapsed") or {}).get("item_ms"), "item_target_ms": (state.get("elapsed") or {}).get("item_target_ms")}


def presenter_start(stack: RemotionStack, pid: str, scene_index: int | None = None, scope: str | None = None) -> list[dict]:
    """Plan steps: a presenter run (`user_presenter`) started through Core's start route while Variants is open (§ 5), optionally moved to a
    scene and played in a scope. The answers are checked with `check_http()` by the caller (`start`, `goto`, `play`)."""

    steps = [http(stack, "start", "POST", f"{PLAYBACK}/start", {"actor": "user", "presentation_id": pid, "role": "user_presenter"})]
    if scene_index:
        steps.append(http(stack, "goto", "POST", f"{PLAYBACK}/goto", {"actor": "user", "scene_id": SCENE_IDS[scene_index]}))
    if scope:
        steps.append(http(stack, "play", "POST", f"{PLAYBACK}/play", {"actor": "user", "scope": scope}))
    return steps


def check_http(reads: dict, *names: str) -> None:
    for name in names:
        answer = reads.get(name) or {}
        harness(answer.get("status") == 200, f"Core refused `{name}`: {answer}")


# ---------------------------------------------------------------------------------------------------------------- (c) chained play (Board today)

async def test_play_all_shows_every_scene_in_order_from_frame_zero_without_stall_blank_or_cut(tmp_path):
    """(c) « tout jouer » (`scope: all`): each of the 9 scenes becomes visible within 1.5 s of Core entering it, plays from its frame 0 to its
    last frame (the 30 s scene is not cut at its 8 s score target), no instant without a ready frame, no replay (§ 4.2)."""

    shots = tmp_path / "shots"
    shots.mkdir()
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _vid = await make_deck(stack)
        status, started = await stack.call("POST", f"{PLAYBACK}/start", json={
            "actor": "user", "presentation_id": pid, "role": "user_presenter", "scope": "all"})
        harness(status == 200 and started["state"]["scope"] == "all", f"start scope all refused: {started}")
        plan: list[dict] = [{"eval": PAGE_PROBE}, READY]
        for boundary in range(1, 9):
            plan += [{"until": f"({next_boundary()})||({FINAL})", "ms": 70000},
                     {"burst": str(shots), "ms": 1800, "clipExpr": VISIBLE_RECT, "prefix": f"b{boundary}", "as": f"burst{boundary}"}]
            if boundary == 2:   # 4 s after the S2 -> S3 boundary: S3 playing, or S2 held while the band says scene 3/9 (the stall)
                plan += [{"wait": 2500}, {"shot": str(tmp_path / "stall.png")}, {"value": "at_stall_shot", "expr": READOUTS}]
        plan += [{"until": FINAL, "ms": 70000}, {"wait": 3000}, {"value": "probe", "expr": READ_PROBE}, http(stack, "where", "GET", PLAYBACK)]
        async with CorePoller(stack) as poll:
            began = time.time()
            result = await run_long(stack.page_url, plan)
            took = time.time() - began
        reads = result["reads"]
        harness("failed" not in reads and reads.get("probe"), reads.get("failed"))
        probe = reads["probe"]
        evidence = analyse_play_all(probe, reads, poll.rows)
        evidence["wall_s"] = round(took, 1)
        evidence["at_stall_shot"] = reads.get("at_stall_shot")
        boundary_shots = [p for burst in evidence["bursts"].values() for p in transition_shots(burst, shots, 2)]
        record("play_all", {"evidence": evidence, "page_epoch": probe["epoch"], "core": poll.rows, "probe_ev": probe["ev"], "band": probe["band"]},
               boundary_shots + [tmp_path / "stall.png"])
        shown = [s["scene"] for s in evidence["per_scene"]]
        assert shown == [f"S{n}" for n in range(1, 10)], f"scenes shown: {shown}; never shown: {evidence['never_shown']}"
        for scene in evidence["per_scene"]:
            n = int(scene["scene"][1:]) - 1
            assert scene["first_play"] and scene["first_play"][1] == 0, scene
            assert scene["max_frame"] == frames_of(n) - 1, scene      # the 30 s scene is not cut at its 8 s target
            assert scene["wraps"] == [] and scene["entry_latency_ms"] is not None and scene["entry_latency_ms"] <= 1500, scene
        assert evidence["blank_spans_ms"] == [], evidence["blank_spans_ms"]
        assert all(c.startswith("S") for burst in evidence["bursts"].values() for _t, c, _f in burst), "a white / empty capture at a boundary"


def analyse_play_all(probe: dict, reads: dict, core_rows: list[dict]) -> dict:
    rows = frame_rows(probe)
    clocks = player_clocks(probe)
    scene_of = scene_of_uid(probe)
    enter = core_enter_ms(core_rows, probe["epoch"])
    per_scene = []
    for ms, uid in [(row[0], row[2]) for row in probe["ev"] if row[1] == "live"]:
        scene = scene_of.get(uid)
        number = int(scene[1:]) if scene else None
        per_scene.append({"uid": uid, "scene": scene, "live_ms": ms, "core_enter_ms": enter.get(number),
                          # Core starts the run before Chrome loads the page: a scene entered before the probe existed counts from the probe's epoch
                          "entry_latency_ms": None if number not in enter else ms - max(enter[number], 0),
                          "duration": next((s[5] for s in rows.get(uid, []) if s[5]), None), "first_play": first_play(probe, uid),
                          "max_frame": max((c[1] for c in clocks.get(uid, [])), default=None), "wraps": wraps(clocks.get(uid, []))})
    shown = {s["scene"] for s in per_scene}
    stalls = []
    for number, ms in sorted(enter.items()):
        if f"S{number}" not in shown:
            following = enter.get(number + 1)
            stalls.append({"scene": f"S{number}", "core_enter_ms": ms, "core_left_ms": following,
                           "held_previous_ms": None if following is None else following - ms})
    bursts = {key: bursts_classified(value) for key, value in reads.items() if key.startswith("burst") and isinstance(value, list)}
    return {"mounted_frames": [(row[0], row[2], row[4], row[5]) for row in probe["ev"] if row[1] == "mount"],
            "per_scene": per_scene, "never_shown": stalls, "blank_spans_ms": blank_spans(probe, place="board"), "bursts": bursts,
            "core_scopes": sorted({r.get("scope") for r in core_rows if r.get("scope")}),
            "expected_s": sum(s for s, _f, _a, _b in DECK),
            "where_end": {k: ((reads.get("where") or {}).get("body") or {}).get("state", {}).get(k) for k in ("phase", "scope", "position")}}


# ---------------------------------------------------------------------------------------------------------------- (d) one clock, continuous video in Variants

async def variants_clock_run(tmp_path) -> dict:
    """Continuous video in Variants (§ 4): S3 (30 s at 30 fps, score target 8 s) chosen by its thumbnail and played with « Lire seulement
    cette scène » (today: no such control, the preview plays by itself). What the viewer reads at 2.6 s; a scrub (§ 4.6) to 20 s into S3;
    the end (held on 899). Measured once per module, shared by the tests below."""

    cached = globals().get("_VARIANTS_CLOCKS")
    if cached:
        return cached
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _vid = await make_deck(stack)
        held = f"(()=>{{const s={VSTATE};return !!s&&s.scene==='S3'&&s.frame===899&&!s.playing}})()"
        plan = open_variants(pid) + [
            thumbnail(2), variants_scene_ready(2),
            {"value": "gesture", "expr": gesture("scene_only", legacy=False)},
            {"until": f"(()=>{{const s={VSTATE};return !!s&&s.scene==='S3'&&s.frame>=78}})()", "ms": 30000, "required": True, "as": "at_frame_78"},
            {"value": "at_2_6", "expr": READOUTS}, {"shot": str(tmp_path / "clocks-2_6s.png")},
            {"value": "scrub_at", **NOW}, {"value": "scrub_kind", "expr": scrub_to(2, 20, legacy_local_frame=600)},
            {"wait": 1500}, {"value": "after_scrub", "expr": READOUTS}, {"shot": str(tmp_path / "clocks-after-scrub.png")},
            {"until": held, "ms": 25000, "as": "held_on_899"}, {"value": "held", "expr": READOUTS}, {"wait": 3000},
            {"value": "held_later", "expr": READOUTS}, {"value": "probe", "expr": READ_PROBE}]
        result = await run_long(stack.page_url, plan, timeout=300)
        reads = result["reads"]
        harness("failed" not in reads and reads.get("probe"), reads.get("failed"))
        harness(reads.get("scrub_kind"), "no scrub control in Variants (neither the contract slider nor today's stage scrub)")
        probe = reads["probe"]
        clocks = player_clocks(probe)
        uids = variants_uids(probe, "S3")
        own = sorted((c for u in uids for c in clocks.get(u, [])), key=lambda c: c[0])
        after = [c for c in own if c[0] >= reads["scrub_at"]]
        reached = next((ms for ms, frame, _p in after if frame >= 890), None)
        evidence = {k: reads.get(k) for k in ("gesture", "at_2_6", "scrub_kind", "scrub_at", "after_scrub", "held_on_899", "held", "held_later")}
        evidence.update({"player_reached_end_ms": reached, "wraps_after_scrub": wraps(after),
                         "frame_orders_after_scrub_500ms": frame_orders_after(probe, reads["scrub_at"] + 500),
                         "frame_orders_after_end": frame_orders_after(probe, reached) if reached is not None else [],
                         "first_play": first_play(probe, uids[0]) if uids else None, "failed": None})
        record("variants_clocks_S3", {"evidence": evidence, "probe_ev": probe.get("ev")},
               [tmp_path / "clocks-2_6s.png", tmp_path / "clocks-after-scrub.png"])
        globals()["_VARIANTS_CLOCKS"] = evidence
        return evidence


async def test_one_clock_every_time_readout_shows_the_composition_time(tmp_path):
    """(d) § 4.8 / § 6 #18: at 2.6 s into S3 every visible time readout shows the Player's composition time f/fps (11 s + 2.6 s) over the
    composition length (74 s): no score time (x / 0:08) and no scene-local time shown as media time; at least one readout exists."""

    evidence = await variants_clock_run(tmp_path)
    problems = readout_problems(evidence["at_2_6"], 2)
    assert problems == [], f"readouts {evidence['at_2_6']['readouts']}: {problems}"


async def test_a_scrub_of_the_player_bar_moves_the_shared_clock(tmp_path):
    """(d) § 4.6 / § 4.8: after a scrub to 20 s into S3, the Player shows it, and every visible readout, the scene label and the strip selection
    derive from the Player frame; no host or follower order re-seeks the Player afterwards."""

    evidence = await variants_clock_run(tmp_path)
    after = evidence["after_scrub"]
    player = after.get("player") or {}
    assert player.get("scene") == "S3" and (player.get("frame") or 0) >= 600, f"the Player did not take the scrub: {player}"
    assert after["label"] == 3 and after["selected"] == SCENE_IDS[2], f"label {after['label']} / strip {after['selected']} vs Player S3"
    assert evidence["frame_orders_after_scrub_500ms"] == [], f"re-seeked after the user's scrub: {evidence['frame_orders_after_scrub_500ms']}"
    problems = readout_problems(after, 2)
    assert problems == [], f"readouts {after['readouts']}: {problems}"


async def test_after_a_forward_scrub_the_scene_ends_once_and_holds_its_last_frame(tmp_path):
    """(d) § 4.7: after a scrub to 20 s, « Lire seulement cette scène » plays S3 to frame 899 and HOLDS it: no wrap to 0, and no later order
    moves it (no follower jump such as 612 -> 835)."""

    evidence = await variants_clock_run(tmp_path)
    assert evidence["wraps_after_scrub"] == [], f"the Player looped after the scrub: {evidence['wraps_after_scrub']}"
    later = (evidence["held_later"] or {}).get("player") or {}
    assert evidence["held_on_899"] is True and later.get("frame") == 899 and later.get("playing") is False, f"not held on 899: {later}"
    assert evidence["frame_orders_after_end"] == [], f"an order moved the Player after its end: {evidence['frame_orders_after_end']}"


# ---------------------------------------------------------------------------------------------------------------- (d)/(e) continuous-video scrub (§ 4.6)

async def test_a_video_scrub_back_while_playing_is_honoured(tmp_path):
    """(e)/(d) § 4.6, continuous video: S2 playing past 1.5 s, the user scrubs back to its start; 1.5 s later the Player plays on from there
    (local frame 25-60, still playing) and no order re-seeked it to another clock."""

    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _vid = await make_deck(stack)
        plan = open_variants(pid) + [
            thumbnail(1), variants_scene_ready(1), {"value": "gesture", "expr": gesture("play", legacy=False)},
            {"until": f"(()=>{{const s={VSTATE};return !!s&&s.scene==='S2'&&s.playing&&s.frame>=45}})()", "ms": 30000, "required": True,
             "as": "playing_45"},
            {"value": "scrub_at", **NOW}, {"value": "scrub_kind", "expr": scrub_to(1, 0, legacy_local_frame=0)},
            {"wait": 1500}, {"value": "after", "expr": VSTATE}, {"value": "probe", "expr": READ_PROBE}]
        result = await run_long(stack.page_url, plan, timeout=240)
        reads = result["reads"]
        harness("failed" not in reads and reads.get("scrub_kind"), reads.get("failed") or "no scrub control")
        evidence = {k: reads.get(k) for k in ("gesture", "scrub_kind", "after")}
        evidence["frame_orders_after_scrub_500ms"] = frame_orders_after(reads["probe"], reads["scrub_at"] + 500)
        record("video_scrub_playing_S2", evidence)
        after = reads["after"] or {}
        assert after.get("scene") == "S2" and 25 <= (after.get("frame") or -1) <= 60 and after.get("playing") is True, after
        assert evidence["frame_orders_after_scrub_500ms"] == [], evidence


async def test_a_video_scrub_while_paused_is_kept(tmp_path):
    """(e)/(d) § 4.3 / § 4.6, continuous video paused on S2: a scrub to 2 s then to 6 s into S2 leaves the Player paused exactly there."""

    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _vid = await make_deck(stack)
        paused = f"(()=>{{const s={VSTATE};return !!s&&s.scene==='S2'&&!s.playing}})()"
        plan = open_variants(pid) + [
            thumbnail(1), variants_scene_ready(1), {"wait": 1000}, {"value": "gesture", "expr": gesture("pause", legacy=True)},
            {"until": paused, "ms": 5000, "required": True, "as": "paused"},
            {"value": "scrub1", "expr": scrub_to(1, 2, legacy_local_frame=60)}, {"wait": 1500}, {"value": "at_2s", "expr": VSTATE},
            {"value": "scrub2", "expr": scrub_to(1, 6, legacy_local_frame=180)}, {"wait": 1500}, {"value": "at_6s", "expr": VSTATE}]
        result = await run_long(stack.page_url, plan, timeout=240)
        reads = result["reads"]
        harness("failed" not in reads and reads.get("scrub1") and reads.get("scrub2"), reads.get("failed") or "no scrub control")
        evidence = {k: reads.get(k) for k in ("gesture", "scrub1", "at_2s", "at_6s")}
        record("video_scrub_paused_S2", evidence)
        assert (reads["at_2s"] or {}).get("frame") == 60 and reads["at_2s"]["playing"] is False, evidence
        assert (reads["at_6s"] or {}).get("frame") == 180 and reads["at_6s"]["playing"] is False, evidence


# ---------------------------------------------------------------------------------------------------------------- (e) presenter run (§ 5)

async def presenter_s3_run(tmp_path) -> dict:
    """A presenter run started while Variants is open (§ 5), moved to S3 and played in `scene` scope: the scrubber state, and the end."""

    cached = globals().get("_PRESENTER_S3")
    if cached:
        return cached
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _vid = await make_deck(stack)
        player = run_state(900)
        plan = open_variants(pid) + presenter_start(stack, pid, 2, "scene") + [
            {"until": f"(()=>{{const s={player};return !!s&&s.phase==='ready'&&s.frame>=30}})()", "ms": 60000, "required": True, "as": "run_playing"},
            {"value": "scrubbers", "expr": SCRUBBERS},
            {"until": f"(()=>{{const s={player};return !!s&&s.frame===899&&!s.playing}})()", "ms": 45000, "as": "held_on_899"},
            {"value": "held", "expr": player}, {"value": "probe", "expr": READ_PROBE}]
        result = await run_long(stack.page_url, plan, timeout=300)
        reads = result["reads"]
        harness("failed" not in reads, reads.get("failed"))
        check_http(reads, "start", "goto", "play")
        probe = reads["probe"]
        uid = next((row[2] for row in probe["ev"] if row[1] == "mount" and row[4] == "S3"), None)
        evidence = {"scrubbers": reads.get("scrubbers"), "held_on_899": reads.get("held_on_899"), "held": reads.get("held"),
                    "first_play": first_play(probe, uid) if uid else None, "failed": None}
        record("presenter_S3", evidence)
        globals()["_PRESENTER_S3"] = evidence
        return evidence


#: Every visible, enabled scrubber: the contract slider of Variants and today's stage-page scrub, anywhere on the page.
SCRUBBERS = ("(()=>{const out=[];const vis=el=>el.getClientRects().length&&!el.closest('[hidden]');"
             "const x=document.querySelector('#jvStudioExplorer');for(const s of (x?x.querySelectorAll('[role=\"slider\"]'):[]))"
             "out.push({kind:'variants-slider',disabled:s.getAttribute('aria-disabled')==='true',text:s.getAttribute('aria-disabled')==='true'?(s.title||s.getAttribute('aria-description')||''):''});"
             "for(const f of document.querySelectorAll('iframe[data-remotion-stage]')){try{const r=f.contentDocument.querySelector('.rs-scrub');"
             "if(r&&vis(r)&&vis(f))out.push({kind:'stage-scrub',disabled:r.disabled||r.getAttribute('aria-disabled')==='true'})}catch(e){}}return out})()")


async def test_a_30s_composition_with_an_8s_score_target_plays_to_its_last_frame(tmp_path):
    """(c)/(E) § 3 / § 5: the score's `target_duration_ms` (8 s) never cuts a 30 s Remotion composition: S3 starts on frame 0 and holds 899."""

    evidence = await presenter_s3_run(tmp_path)
    assert evidence["held_on_899"] is True and evidence["held"]["frame"] == 899 and evidence["held"]["playing"] is False, evidence["held"]
    assert evidence["first_play"] and evidence["first_play"][1] == 0, evidence["first_play"]


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S03 repro: defect D/F — a presenter run has no read-only Variants scrubber; the stage "
                                                              "page's own scrub stays usable and fights the score — fixed by Slice 09/10")
async def test_a_presenter_run_scrubber_is_read_only(tmp_path):
    """(e) § 5: in a presenter run the Variants scrubber exists and is `aria-disabled` (« La partition mène la présentation »); no enabled
    scrubber exists anywhere else on the page."""

    evidence = await presenter_s3_run(tmp_path)
    scrubbers = evidence["scrubbers"] or []
    assert any(s["kind"] == "variants-slider" for s in scrubbers), f"no Variants scrubber during the presenter run: {scrubbers}"
    assert all(s["disabled"] for s in scrubbers), f"an enabled scrubber during a presenter run: {scrubbers}"


async def test_a_manual_scene_without_anchor_plays_once_and_holds_its_last_frame(tmp_path):
    """(e) § 5: presenter run, S1 (3 s, no anchor): its item plays the scene once from frame 0 and holds frame 89; it never wraps by itself."""

    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _vid = await make_deck(stack)
        player = run_state(90)
        plan = open_variants(pid) + presenter_start(stack, pid) + [
            {"until": f"(()=>{{const s={player};return !!s&&s.phase==='ready'}})()", "ms": 60000, "required": True, "as": "run_ready"},
            {"wait": 8000}, {"value": "end", "expr": player}, {"value": "probe", "expr": READ_PROBE}, http(stack, "core", "GET", PLAYBACK)]
        result = await run_long(stack.page_url, plan, timeout=240)
        reads = result["reads"]
        harness("failed" not in reads, reads.get("failed"))
        check_http(reads, "start")
        probe = reads["probe"]
        clocks = player_clocks(probe)
        uids = [row[2] for row in probe["ev"] if row[1] == "mount" and row[4] == "S1" and row[2] in clocks]
        harness(uids, "no S1 Player clock recorded")
        uid = max(uids, key=lambda u: len(clocks[u]))
        evidence = {"wraps": wraps(clocks[uid]), "first_play": first_play(probe, uid), "end": reads.get("end"),
                    "core": core_view(reads.get("core")), "orders": [row for row in probe["ev"] if row[1] == "order"], "clocks": clocks[uid][:60]}
        record("manual_anchorless_S1", evidence)
        assert evidence["wraps"] == [], f"the Player looped {len(evidence['wraps'])} times in 8 s: {evidence['wraps'][:3]}"
        assert evidence["first_play"] and evidence["first_play"][1] == 0, evidence["first_play"]
        end = evidence["end"] or {}
        assert end.get("frame") == 89 and end.get("playing") is False, f"not held on its last frame: {end}"


# ---------------------------------------------------------------------------------------------------------------- (a) Variants: slide change

async def explorer_run(tmp_path) -> dict:
    cached = globals().get("_EXPLORER")
    if cached:
        return cached
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _vid = await make_deck(stack)
        plan = open_variants(pid) + [
            {"wait": 2000}, {"shot": str(tmp_path / "explorer-S1.png")},
            {"eval": f"window.__clip={VISIBLE_RECT}"}, {"value": "click_1_3", **NOW},
            thumbnail(2), {"burst": str(tmp_path), "ms": 1500, "clipExpr": "window.__clip", "prefix": "x13", "as": "burst_1_3"},
            variants_scene_ready(2), {"wait": 3000}, {"value": "click_3_4", **NOW},
            thumbnail(3), {"burst": str(tmp_path), "ms": 1500, "clipExpr": "window.__clip", "prefix": "x34", "as": "burst_3_4"},
            variants_scene_ready(3), {"wait": 2000}, {"value": "probe", "expr": READ_PROBE}]
        result = await run_long(stack.page_url, plan, timeout=300)
        reads = result["reads"]
        harness("failed" not in reads and reads.get("probe"), reads.get("failed"))
        probe = reads["probe"]
        clocks, scene_of = player_clocks(probe), scene_of_uid(probe)
        frames = []
        for uid, scene in scene_of.items():
            frames.append({"uid": uid, "scene": scene, "first_play": first_play(probe, uid), "wraps": wraps(clocks.get(uid, [])),
                           "mount_ms": next(r[0] for r in probe["ev"] if r[1] == "mount" and r[2] == uid),
                           "ready_ms": next((r[0] for r in probe["ev"] if r[1] == "status" and r[2] == uid and r[3] == "ready"), None),
                           "gone_ms": next((r[0] for r in probe["ev"] if r[1] == "gone" and r[2] == uid), None)})
        evidence = {"frames": frames, "blank_spans_ms": blank_spans(probe, place="explorer"),
                    "bursts": {k: bursts_classified(v) for k, v in reads.items() if k.startswith("burst") and isinstance(v, list)},
                    "clicks_ms": {"S1->S3": reads.get("click_1_3"), "S3->S4": reads.get("click_3_4")},
                    "orders": [row for row in probe["ev"] if row[1] == "order"], "failed": None}
        for key, click, target in (("burst_1_3", reads.get("click_1_3"), "S3"), ("burst_3_4", reads.get("click_3_4"), "S4")):
            burst = evidence["bursts"].get(key) or []
            first_scene = next((t for t, c, _f in burst if c == target), None)
            evidence.setdefault("click_to_first_scene_pixels_ms", {})[key] = None if first_scene is None or click is None else first_scene - click
        record("explorer_preview", evidence,
               [tmp_path / "explorer-S1.png"] + [p for burst in evidence["bursts"].values() for p in transition_shots(burst, tmp_path, 4)])
        globals()["_EXPLORER"] = evidence
        return evidence


async def test_variants_slide_change_never_shows_an_empty_preview(tmp_path):
    """(a) § 4.2 / § 4.5: a thumbnail click keeps a ready picture on screen: no interval without a ready Variants frame, never a dark capture."""

    evidence = await explorer_run(tmp_path)
    harness(evidence["failed"] is None, evidence["failed"])
    assert evidence["blank_spans_ms"] == [], f"empty preview spans (start ms, duration ms): {evidence['blank_spans_ms']}"
    seen = [c for burst in evidence["bursts"].values() for _t, c, _f in burst]
    assert seen and all(c.startswith("S") for c in seen), f"click -> first scene pixels (ms): {evidence['click_to_first_scene_pixels_ms']}"


# ---------------------------------------------------------------------------------------------------------------- (a)/(b) Variants: opening, play gestures

async def scene_only_run(tmp_path, scene_index: int, wait_ms: int) -> dict:
    """Variants opened; the scene chosen by its thumbnail; its state 1.5 s after it is ready (§ 4.1: paused on frame 0); then « Lire seulement
    cette scène » (today: « Jouer cette slide », the defect being measured); `wait_ms` later, what Variants shows."""

    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _vid = await make_deck(stack)
        plan = open_variants(pid)
        if scene_index:
            plan += [thumbnail(scene_index), variants_scene_ready(scene_index)]
        plan += [{"wait": 1500}, {"value": "opened", "expr": VSTATE}, {"value": "gesture_at", **NOW},
                 {"value": "gesture", "expr": gesture("scene_only", legacy=True)}, {"wait": wait_ms},
                 {"value": "after", "expr": READOUTS}, {"value": "probe", "expr": READ_PROBE}, http(stack, "core", "GET", PLAYBACK)]
        result = await run_long(stack.page_url, plan, timeout=300)
        reads = result["reads"]
        harness("failed" not in reads and reads.get("gesture"), reads.get("failed") or "neither « Lire seulement cette scène » nor « Jouer cette slide »")
        check_http(reads, "core")
        probe = reads["probe"]
        clocks = player_clocks(probe)
        scene = f"S{scene_index + 1}"
        own = sorted((c for u in variants_uids(probe, scene) for c in clocks.get(u, [])), key=lambda c: c[0])
        after = [c for c in own if c[0] >= reads["gesture_at"]]
        return {"opened": reads.get("opened"), "gesture": reads.get("gesture"), "after": reads.get("after"), "core": core_view(reads.get("core")),
                "first_play_after_gesture": next(((ms, f) for ms, f, p in after if p), None),
                "max_frame_after_gesture": max((c[1] for c in after), default=None), "wraps_after_gesture": wraps(after)}


def assert_plays_once_and_holds(evidence: dict, scene: str, last: int) -> None:
    after = evidence["after"] or {}
    player = after.get("player") or {}
    assert after.get("open") is True, f"Variants closed after « {evidence['gesture']} »"
    assert (evidence["core"] or {}).get("phase") in (None, "idle", "stopped"), f"Core started a run (§ 5 table: video semantics): {evidence['core']}"
    assert evidence["first_play_after_gesture"] and evidence["first_play_after_gesture"][1] == 0, evidence
    assert evidence["max_frame_after_gesture"] == last and evidence["wraps_after_gesture"] == [], evidence
    assert player.get("scene") == scene and player.get("frame") == last and player.get("playing") is False, f"not held on {last}: {player}"


async def test_variants_preview_plays_a_slide_once_and_holds(tmp_path):
    """(a) § 4.1: Variants opens paused on frame 0 of S1; § 5 table: « Lire seulement cette scène » plays S1 from frame 0 to 89 once and holds
    89 paused, Variants still open."""

    evidence = await scene_only_run(tmp_path, 0, 6000)
    record("variants_scene_only_S1", evidence)
    opened = evidence["opened"] or {}
    assert opened.get("frame") == 0 and opened.get("playing") is False, f"Variants did not open paused on frame 0: {opened}"
    assert_plays_once_and_holds(evidence, "S1", 89)


async def test_variants_play_this_slide_plays_the_slide_in_scene_scope(tmp_path):
    """(b) § 5 table: on S3, « Lire seulement cette scène » keeps Variants open and its Player plays S3 from frame 0 to 899, then holds 899."""

    evidence = await scene_only_run(tmp_path, 2, 33000)
    record("variants_scene_only_S3", evidence)
    assert_plays_once_and_holds(evidence, "S3", 899)


async def test_variants_play_all_plays_the_whole_presentation_inside_variants(tmp_path):
    """(b) § 4.2: « Lire » (today « Tout jouer ») keeps Variants open, and the Variants Player itself crosses into S2 at its local frame 0."""

    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _vid = await make_deck(stack)
        plan = open_variants(pid) + [{"wait": 500}, {"value": "gesture", "expr": gesture("play", legacy=True)}, {"wait": 6500},
                                     {"value": "after", "expr": READOUTS}, {"shot": str(tmp_path / "play-all-after-6s.png")},
                                     http(stack, "core", "GET", PLAYBACK), {"value": "probe", "expr": READ_PROBE}]
        result = await run_long(stack.page_url, plan, timeout=240)
        reads = result["reads"]
        harness("failed" not in reads and reads.get("gesture"), reads.get("failed") or "neither « Lire » nor « Tout jouer »")
        probe = reads["probe"]
        clocks = player_clocks(probe)
        s2 = variants_uids(probe, "S2")
        evidence = {"gesture": reads["gesture"], "variants_open": (reads.get("after") or {}).get("open"),
                    "variants_player": (reads.get("after") or {}).get("player"), "core": core_view(reads.get("core")),
                    "variants_S2_first_play": next((first_play(probe, u) for u in s2 if first_play(probe, u)), None),
                    "frames": [(r[0], r[2], r[3], r[4]) for r in probe["ev"] if r[1] == "mount"]}
        record("variants_play_all", evidence, [tmp_path / "play-all-after-6s.png"])
        del clocks
        assert evidence["variants_open"] is True, f"Variants closed after « {evidence['gesture']} »"
        assert evidence["variants_S2_first_play"] and evidence["variants_S2_first_play"][1] == 0, \
            f"the Variants Player never entered S2 at frame 0: {evidence['variants_player']}"


assert TARGET_MS == 8000 and frames_of(2) == 900   # the fixture the reasons above speak of

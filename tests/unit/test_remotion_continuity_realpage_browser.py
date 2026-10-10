"""Lecture continue d'une présentation Remotion, dans le VRAI Control Center, un VRAI Chrome, un Core isolé (Slice 23).

Opt-in comme les Slices 10 et 12 (`JARVIS_REMOTION_RUNTIME_DIR` = le dossier `runtime/` d'une installation Remotion existante, Node, Chrome).
Ne démarre ni n'arrête jamais le Jarvis vivant : Core, Control Center et bac à sable vivent sur des ports libres et une racine jetable.

Ce que le test MESURE (un échantillonneur de la page lit, toutes les 50 ms, chaque cadre de scène : identité, phase, image, lecture) :

- « jouer tout » (`start {scope: all}`) enchaîne trois scènes de trois segments chacune SANS geste : chaque scène a un seul cadre, ne repart
  jamais en arrière (aucune image plus petite que la précédente dans un même cadre), la fenêtre n'est jamais vide, la scène suivante est
  prête avant qu'on y passe (aucun cadre en chargement visible) et la dernière image du dernier élément est tenue ;
- chaque scène joue ses images de 0 à la dernière dans l'ordre, une seule fois (pas de rejeu : la lecture ne reprend pas du début de segment
  après s'être arrêtée, ce qui arrivait toutes les ~4 s) ;
- l'arrêt entre deux segments d'une même scène est court (le temps d'un aller-retour vers Core) ;
- « jouer la slide » (`play {scope: scene}`) joue la scène courante d'un bout à l'autre puis TIENT sa dernière image, sans passer à la suivante,
  et `play {scope: all}` reprend à partir de là.
"""

from __future__ import annotations

import shutil

import pytest

from jarvis.adapters.remotion_compiler import shipped_engine_pin
from jarvis.domain.remotion_source import Composition
from tests.fakes.remotion_player_stack import RemotionStack, runtime_dir_from_env
from tests.fakes.remotion_scene import scene_candidate
from tests.unit.test_remotion_player_realpage_browser import PROPS, READY, SAMPLE, SCENE_TSX, http_step, noise, record_evidence, run, scene

RUNTIME = runtime_dir_from_env()
pytestmark = pytest.mark.skipif(RUNTIME is None or shutil.which("node") is None,
                                reason="needs JARVIS_REMOTION_RUNTIME_DIR (an existing Remotion install), node and Chrome")

PREFABS = [f"presentation-studio.p000000000001.s00000000000{n}" for n in (1, 2, 3)]
SCENES = [f"pss_00000000000{n}" for n in (1, 2, 3)]
PLAYBACK = "/v1/presentation-studio/playback"
#: 30 images/s, 150 images (5 s). Ancres à 1 s et 2,5 s = images 30 et 75 : segments [0,29] [30,74] [75,149].
ANCHORS = [{"anchor_id": "intro", "label": "Intro", "at_ms": 1000}, {"anchor_id": "middle", "label": "Milieu", "at_ms": 2500}]

#: Un cadre est décrit par `[uid, phase, image, lecture]` ; l'échantillon par `[ms, nombre de cadres dans la page, [cadres visibles]]`.
SAMPLER = """(()=>{window.__log=[];window.__t0=performance.now();setInterval(()=>{
 const all=[...document.querySelectorAll('iframe[data-remotion-stage]')];
 const live=all.filter(f=>!f.classList.contains('sc-prefab-staged')&&f.style.visibility!=='hidden');
 const rec=live.map(f=>{let s=null;try{s=f.contentWindow.__remotionStage.state()}catch(e){}
  if(!f.__uid)f.__uid=(window.__uid=(window.__uid||0)+1);return [f.__uid,s&&s.phase,s&&s.frame,s&&s.playing]});
 window.__log.push([Math.round(performance.now()-window.__t0),all.length,rec]);},50);})()"""


def item(n: int, scene_index: int, nxt: int | None, anchor: str | None = None) -> dict:
    visual = [{"kind": "reveal", "scene_id": SCENES[scene_index], "anchor_id": anchor}] if anchor else []
    return {"item_id": f"psi_{n:012d}", "scene_id": SCENES[scene_index], "presenter": "user", "kind": "speech", "note": f"Element {n}",
            **({"next_item_id": f"psi_{nxt:012d}"} if nxt else {}), **({"visual": visual} if visual else {})}


async def make_chain(stack: RemotionStack) -> str:
    for prefab_id, title in zip(PREFABS, "ABC"):
        await stack.core.prefabs.save(scene_candidate(
            prefab_id, engine=shipped_engine_pin(), title=title, composition=Composition("Scene", 1280, 720, 30, 150),
            files={"src/Scene.tsx": SCENE_TSX}, props=PROPS, sample=SAMPLE), actor="user")
    base = "/v1/presentation-studio/presentations"
    _, created = await stack.call("POST", base, json={"title": "Continue"})
    pid, variant = created["presentation"]["presentation_id"], created["variants"][0]
    vid = variant["variant_id"]
    scenes = [{**scene(SCENES[i], PREFABS[i], f"Scene {i + 1}"), "anchors": ANCHORS} for i in range(3)]
    status, saved = await stack.call("PUT", f"{base}/{pid}/variants/{vid}", json={
        "expected_revision": variant["revision"], "title": variant["title"], "scenes": scenes,
        "art_direction_id": variant["art_direction_id"], "score_id": variant["score_id"]})
    assert status == 200, saved
    items = []
    for index in range(3):
        n = index * 3 + 1
        last = index == 2
        items += [item(n, index, n + 1), item(n + 1, index, n + 2, "intro"), item(n + 2, index, None if last else n + 3, "middle")]
    status, made = await stack.call("POST", f"{base}/{pid}/variants/{vid}/score", json={
        "expected_variant_revision": saved["revision"], "start_item_id": items[0]["item_id"], "items": items, "cues": [],
        "sequences": [], "recovery_points": []})
    assert status == 201, made
    status, art = await stack.call("POST", f"{base}/{pid}/variants/{vid}/art-direction/fallback",
                                   json={"expected_variant_revision": saved["revision"] + 1})
    assert status == 201, art
    return pid


def per_frame(log: list) -> dict[int, list[tuple[int, str, int, bool]]]:
    """Les échantillons de chaque cadre visible : `{uid: [(ms, phase, image, lecture)]}`."""

    out: dict[int, list] = {}
    for ms, _count, visible in log:
        for uid, phase, frame, playing in visible:
            out.setdefault(uid, []).append((ms, phase, frame, playing))
    return out


def backwards(samples: list) -> list[tuple[int, int, int]]:
    """Les reculs d'image dans un même cadre : `(ms, avant, après)` ; vide = la lecture ne repart jamais en arrière."""

    return [(b[0], a[2], b[2]) for a, b in zip(samples, samples[1:]) if a[2] is not None and b[2] is not None and b[2] < a[2]]


def stops_between_segments(samples: list, stop_frames=(29, 74)) -> list[int]:
    """Durée (ms) de chaque arrêt sur une image d'arrêt de segment avant que la lecture ne reparte, dans un cadre."""

    gaps, since = [], None
    for ms, _phase, frame, playing in samples:
        if frame in stop_frames and not playing and since is None:
            since = ms
        elif since is not None and (playing or frame not in stop_frames):
            gaps.append(ms - since)
            since = None
    return gaps


async def test_play_all_chains_three_scenes_without_a_restart_a_replay_or_a_blank_and_play_scene_holds_its_last_image(tmp_path):
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid = await make_chain(stack)
        status, started = await stack.call("POST", f"{PLAYBACK}/start", json={
            "actor": "user", "presentation_id": pid, "role": "user_presenter", "scope": "all"})
        assert status == 200 and started["state"]["scope"] == "all", started
        first = started["state"]["timeline"]
        assert first["auto"] is True and first["prefab"] == f"{PREFABS[0]}@1" and (first["from_frame"], first["until_frame"]) == (0, 29)
        # --- page 1: nobody touches anything, the presentation plays itself: 3 scenes x 5 s, plus the swaps
        one = await run(stack.page_url, [
            {"wait": 500}, READY, {"eval": SAMPLER},
            {"until": "document.querySelector('iframe[data-remotion-stage]') && window.__log.length>0 && window.__log.slice(-1)[0][2].length>0 "
                      "&& window.__uid>=3 && window.__log.slice(-1)[0][2][0][2]>=149", "ms": 90000},
            {"wait": 3500},                                # the last image is HELD: nothing moves after the end
            {"value": "log", "expr": "window.__log"},
            {"value": "frames", "expr": "document.querySelectorAll('iframe[data-remotion-stage]').length"},
            {"value": "shot_state", "expr": "document.querySelector('iframe[data-remotion-stage]').contentWindow.__remotionStage.state().frame"},
            http_step(stack, "where", "GET", PLAYBACK)])
        reads = one["reads"]
        assert "failed" not in reads, reads
        frames = per_frame(reads["log"])
        assert sorted(frames) == [1, 2, 3], f"one frame per scene, never a remount: {sorted(frames)}"
        for uid, samples in frames.items():
            assert backwards(samples) == [], f"scene {uid} went backwards (a restart or a replay): {backwards(samples)}"
            assert max(s[2] for s in samples) == 149, f"scene {uid} did not reach its last image"
            assert {s[1] for s in samples} == {"ready"}, f"scene {uid} was visible while not ready"
            # played once, in order: the images seen cover the whole composition with no big hole beyond one report period
            seen = sorted({s[2] for s in samples})
            assert seen[0] <= 10 and seen[-1] == 149   # the first image seen is one of the opening ones (the frame number reaches the page 4 times a second)
        # the window is never empty and the scene to come never shows up loading: from the first ready on, always exactly one visible frame
        started_at = next(ms for ms, _n, vis in reads["log"] if vis)
        assert all(len(vis) == 1 for ms, _n, vis in reads["log"] if ms >= started_at), "the window was empty or doubled at some moment"
        # the order of the scenes
        order = [uid for uid in dict.fromkeys(vis[0][0] for _ms, _n, vis in reads["log"] if vis)]
        assert order == [1, 2, 3]
        # the stop between two segments of a scene is short (a round trip to Core, not a poll period)
        stops = [gap for samples in frames.values() for gap in stops_between_segments(samples)]
        assert max(stops, default=0) < 900, stops   # (no stop at all: the order to go on beat the 50 ms sampler)
        # at the end the scope is handed back and the last image of the last element is held
        where = reads["where"]["body"]["state"]
        assert where["scope"] == "manual" and where["position"]["index"] == 9 and where["phase"] == "playing", where
        assert reads["shot_state"] == 149
        assert not noise(one), noise(one)
        evidence = {"scenes": len(frames), "samples": len(reads["log"]), "max_stop_between_segments_ms": max(stops, default=0),
                    "stops_ms": stops, "backwards": 0, "frames_per_scene": {str(k): [min(s[2] for s in v), max(s[2] for s in v)] for k, v in frames.items()},
                    "swap_gaps_ms": swap_gaps(reads["log"])}
        # --- "play the slide": from the middle of the run, the current scene only, then it holds
        status, moved = await stack.call("POST", f"{PLAYBACK}/goto", json={"actor": "user", "position": 4})
        assert status == 200, moved
        status, scene_play = await stack.call("POST", f"{PLAYBACK}/play", json={"actor": "user", "scope": "scene"})
        assert status == 200 and scene_play["state"]["scope"] == "scene" and scene_play["state"]["position"]["index"] == 4, scene_play
        two = await run(stack.page_url, [
            {"wait": 500}, READY, {"eval": SAMPLER}, {"wait": 9000},
            {"value": "log", "expr": "window.__log"}, http_step(stack, "where", "GET", PLAYBACK)])
        where = two["reads"]["where"]["body"]["state"]
        assert where["scope"] == "manual" and where["position"]["index"] == 6 and where["scene"]["scene_id"] == SCENES[1], where
        shown = per_frame(two["reads"]["log"])
        assert len(shown) == 1, "playing one slide never leaves it"
        (samples,) = shown.values()
        assert backwards(samples) == [] and samples[-1][2] == 149 and not samples[-1][3], "the slide ends on its last image and holds it"
        assert not noise(two), noise(two)
        record_evidence("continuity_play_all_then_scene", {"play_all": evidence, "play_scene": {"samples": len(samples), "last": samples[-1]}})


def swap_gaps(log: list) -> list[int]:
    """Pour chaque changement de cadre visible : le temps (ms) entre le dernier échantillon de l'ancien et le premier du nouveau."""

    gaps, previous = [], None
    for ms, _count, visible in log:
        if not visible:
            continue
        uid = visible[0][0]
        if previous is not None and uid != previous[0]:
            gaps.append(ms - previous[1])
        previous = (uid, ms)
    return gaps

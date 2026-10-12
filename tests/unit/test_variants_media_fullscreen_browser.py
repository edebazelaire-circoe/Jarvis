"""Son, plein écran de la scène et touches de Variantes dans un VRAI Chrome (handoff jarvis-remotion-native-studio-playback-fix, Slice 08).

VRAI Core, VRAI Control Center, VRAI Player Remotion dans son bac à sable d'origine dédiée (`RemotionStack`, ports libres, racine jetable),
jamais le Jarvis vivant. La présentation de `variants_media_world.MEDIA_DECK` : 16:9 (1920x1080) et 4:3 avec un vrai `<Audio>` (un WAV de
6 s), 9:16 et 1:1 sans son. Opt-in : `JARVIS_REMOTION_RUNTIME_DIR`, Node et Chrome ; sinon ignoré.

Prouvé ici (contrat 2026-10 § 4.12 à § 4.16, PX-12) :
- son : muet à l'ouverture ; un VRAI clic sur « Son » (politique d'autoplay par défaut) rend la scène audible à travers le cadre isolé
  d'une autre origine ; l'élément `<audio>` de Remotion suit l'image (écart mesuré dans le même instant que l'image dessinée), après un saut
  et à la frontière de scène ; le cadre préchargé reste muet ; `M` coupe ;
- sans délégation d'autoplay, le refus du navigateur est dit (message, pastille sur l'image, bouton marqué) et un clic dans l'image le
  lève ; sans AUCUN geste (clic synthétique), le son est refusé et dit, la lecture n'est jamais figée ; avec
  `--autoplay-policy=no-user-gesture-required` (la mesure de référence), le même chemin sans geste joue avec le son ;
- plein écran (1080p) : « Plein écran » met la SCÈNE seule en plein écran (ni arbre, ni métadonnées, ni actions, ni bande), l'image entière
  à son format sur fond noir pour 16:9, 4:3, 9:16 et 1:1, `f` et l'état de lecture gardés, le transport en surimpression se cache en lecture
  et revient au mouvement, `F` quitte et rend le focus à l'ouvreur, `Échap` quitte le plein écran sans fermer ni mettre en pause, le suivant
  ferme Variantes ; la scène garde son format au redimensionnement ;
- touches frappées DANS la scène (cadre d'une autre origine qui a le focus) : chacune agit une fois ; une touche postée par la scène sans le
  focus est refusée ;
- mouvement réduit, rechargement de Chrome, longue session (plein écran, lecture, changements de scène répétés) : aucune animation d'interface,
  aucun cadre ni écouteur qui s'accumule.

Preuves (JSON, PNG réduits, `summary.json`, chemin personnel masqué) : `JARVIS_PLAYBACK_GATE_EVIDENCE_DIR`, en pratique
`tasks/jarvis-remotion-native-studio-playback-fix/slices/08-media-fullscreen-stability/evidence/`.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.domain import remotion_sandbox as sb
from tests.fakes.remotion_player_stack import RemotionStack, runtime_dir_from_env
from tests.unit.presentation_playback_gate_world import evidence_dir, record, redact
from tests.unit.variants_media_world import (
    AUDIO_TAGS, FRAME, FS_BTN, FULLSCREEN, LIRE, MEDIA, SOUND_BTN, X, content_box, make_media_deck, run_media,
)

RUNTIME = runtime_dir_from_env()
pytestmark = pytest.mark.skipif(RUNTIME is None or shutil.which("node") is None,
                                reason="needs JARVIS_REMOTION_RUNTIME_DIR (an existing Remotion install), node and Chrome")

NEXT = f"{X} [role=\"toolbar\"] [aria-label=\"Scène suivante\"]"
STAGE_CENTER = (f"(()=>{{const f={FRAME};if(!f)return null;const r=f.getBoundingClientRect();return {{x:r.left+r.width/2,y:r.top+r.height/2}}}})()")
FOCUS_STAGE = "document.querySelector('#jvStudioExplorer .jvx-stage').focus()"
VIEW = "JarvisStudioExplorer.playback.view()"
GEOMETRY = ("(()=>{const st=document.querySelector('#jvStudioExplorer .jvx-stage').getBoundingClientRect();"
            f"const f={FRAME};const fr=f?f.getBoundingClientRect():null;const pv=document.querySelector('#jvStudioExplorer .jvx-preview').getBoundingClientRect();"
            "return {stage:[Math.round(st.width),Math.round(st.height)],ratio:Math.round(st.width/st.height*1000)/1000,"
            "frame:fr?[Math.round(fr.width),Math.round(fr.height)]:null,inside:st.left>=pv.left-1&&st.right<=pv.right+1&&st.top>=pv.top-1,"
            "overflowX:document.documentElement.scrollWidth>innerWidth}})()")
LEAKS = ("({iframes:document.querySelectorAll('iframe[data-remotion-stage]').length,nodes:document.getElementsByTagName('*').length,"
         "winMessage:(getEventListeners(window).message||[]).length,winResize:(getEventListeners(window).resize||[]).length,"
         "docKeydown:(getEventListeners(document).keydown||[]).length,docFullscreen:(getEventListeners(document).fullscreenchange||[]).length,"
         "heapMb:Math.round(performance.memory.usedJSHeapSize/1048576)})")
FPS = 30


def media_is(scene: int, cond: str = "true") -> str:
    return f"(()=>{{const s={MEDIA};return s.scene==='S{scene}'&&s.phase!==undefined&&({cond})}})()"


def opened(pid: str) -> list[dict]:
    return [{"until": "!!window.JarvisStudioExplorer", "ms": 20000, "required": True, "as": "explorer_api"},
            {"eval": f"JarvisStudioExplorer.open({{presentation_id:'{pid}',fullscreen:false}})"},
            {"until": media_is(1, "s.phase==='paused'&&s.frames.length>=1&&s.frames[0].phase==='ready'"), "ms": 120000, "required": True,
             "as": "variants_ready"}]


def sync_ms(sample: dict) -> float | None:
    """Gap, in ms, between Remotion's `<audio>` and the frame the scene drew at the same instant (`|t - frame/fps|`)."""

    if not sample or not sample.get("audio") or sample.get("frame") is None:
        return None
    return round(abs(sample["audio"]["t"] - sample["frame"] / FPS) * 1000)


def summarize(key: str, payload: dict) -> None:
    folder = evidence_dir()
    if folder is None:
        return
    path = folder / "summary.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"slice": "08-media-fullscreen-stability"}
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "jarvis"], capture_output=True, text=True, check=False).stdout.strip()
    data.update({"tested_head": head + (" + uncommitted jarvis/ changes" if dirty else ""),
                 "runtime": "headless Chrome over CDP, RemotionStack on free loopback ports, throw-away data root; the live Jarvis was never contacted",
                 key: payload})
    path.write_text(redact(json.dumps(data, indent=1, ensure_ascii=False, default=str)), encoding="utf-8")


def harness_ok(result: dict) -> dict:
    reads = result["reads"]
    assert "failed" not in reads, f"harness: {reads['failed']}"
    return reads


# ---------------------------------------------------------------------------------------------------------------- sound (§ 4.14)

async def test_a_real_click_on_son_makes_the_sandboxed_scene_audible_in_sync_and_only_the_scene_on_screen_plays_sound(tmp_path):
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _ = await make_media_deck(stack)
        sample = {"value": None, "expr": AUDIO_TAGS, "scope": "sandbox"}
        plan = opened(pid) + [
            {"wait": 1200}, {"value": "opening", "expr": MEDIA}, {"value": "opening_frames", "expr": AUDIO_TAGS, "scope": "sandboxes"},
            {"click": SOUND_BTN},
            {"until": media_is(1, "s.wanted===true&&s.muted===false"), "ms": 8000, "required": True, "as": "sound_on"},
            {"value": "on", "expr": MEDIA}, {"value": "on_frames", "expr": AUDIO_TAGS, "scope": "sandboxes"},
            {"click": LIRE}, {"until": media_is(1, "s.playing&&s.frame>=45"), "ms": 30000, "required": True, "as": "s1_playing"},
            dict(sample, value="s1_a"), {"wait": 400}, dict(sample, value="s1_b"), {"wait": 400}, dict(sample, value="s1_c"),
            {"value": "s1_frames", "expr": AUDIO_TAGS, "scope": "sandboxes"}, {"value": "s1_media", "expr": MEDIA},
            # a jump back of one second inside the scene, playing (the slider's own key)
            {"eval": "document.querySelector('#jvStudioExplorer [role=\"slider\"]').focus()"}, {"key": "ArrowLeft"},
            {"wait": 900}, dict(sample, value="seek_a"), {"wait": 300}, dict(sample, value="seek_b"),
            # the boundary into S2 (4:3, its own `<Audio>`): the incoming Player gets the sound, in sync
            {"until": media_is(2, "s.playing&&s.frame>=20"), "ms": 30000, "required": True, "as": "s2_playing"},
            dict(sample, value="s2_a"), {"wait": 400}, dict(sample, value="s2_b"),
            {"value": "s2_frames", "expr": AUDIO_TAGS, "scope": "sandboxes"}, {"value": "s2_media", "expr": MEDIA},
            # `M` on the stage turns it off
            {"eval": FOCUS_STAGE}, {"key": "m"},
            {"until": media_is(2, "s.wanted===false&&s.muted===true"), "ms": 5000, "as": "m_off"},
            {"value": "off", "expr": MEDIA}, {"value": "off_frames", "expr": AUDIO_TAGS, "scope": "sandboxes"},
        ]
        reads = harness_ok(await run_media(stack.page_url, plan))
    syncs = {k: sync_ms(reads[k]) for k in ("s1_a", "s1_b", "s1_c", "seek_a", "seek_b", "s2_a", "s2_b")}
    opening = reads["opening"]
    live_s1 = [f for f in reads["s1_frames"] if f.get("title", "").startswith("A ")]
    staged_s2 = [f for f in reads["s1_frames"] if f.get("title", "").startswith("B ")]
    evidence = {"opening": opening, "on": reads["on"], "syncs_ms": syncs, "s1_frames": reads["s1_frames"], "s2_frames": reads["s2_frames"],
                "off": reads["off"], "off_frames": reads["off_frames"],
                **{k: reads[k] for k in ("s1_a", "s1_b", "s1_c", "seek_a", "seek_b", "s2_a", "s2_b")}}
    checks = {
        "muted at opening (page, stage page and the Player's own <audio>)": opening["wanted"] is False and opening["muted"] is True
            and opening["button"]["pressed"] == "false" and all(f["audio"] is None or f["audio"]["muted"] for f in reads["opening_frames"]),
        "a real click on « Son » unmutes the scene through the cross-origin sandbox": reads["on"]["muted"] is False and reads["on"]["blocked"] is False
            and reads["on"]["button"]["pressed"] == "true" and any(f["audio"] and f["audio"]["muted"] is False for f in reads["on_frames"]),
        "the scene on screen plays its <audio>, unmuted": all(reads[k]["audio"] and not reads[k]["audio"]["paused"] and not reads[k]["audio"]["muted"]
                                                         for k in ("s1_a", "s1_b", "s1_c")),
        "audio and image within 200 ms in S1, after a jump and after the boundary": all(v is not None and v <= 200 for v in syncs.values()),
        "the preloaded S2 frame stays muted while S1 plays": bool(live_s1) and bool(staged_s2)
            and all(f["audio"] is None or f["audio"]["muted"] for f in staged_s2),
        "S2 on screen gets the sound (persisted across the scene change)": reads["s2_media"]["wanted"] is True and reads["s2_media"]["muted"] is False
            and reads["s2_a"]["audio"] is not None and reads["s2_a"]["audio"]["muted"] is False,
        "only one audible Player at any sample": all(sum(1 for f in reads[k] if f["audio"] and not f["audio"]["muted"] and not f["audio"]["paused"]) <= 1
                                                     for k in ("s1_frames", "s2_frames")),
        "M turns the sound off": reads["m_off"] and reads["off"]["button"]["pressed"] == "false"
            and all(f["audio"] is None or f["audio"]["muted"] for f in reads["off_frames"]),
    }
    record("sound", {"checks": checks, **evidence})
    summarize("sound", {"checks": checks, "syncs_ms": syncs})
    assert all(checks.values()), {k: v for k, v in checks.items() if not v}


async def test_without_autoplay_delegation_the_refusal_is_said_and_one_click_in_the_image_lifts_it(tmp_path, monkeypatch):
    # The frame as it was before Slice 08 (`allow=""`): Chrome then wants a gesture IN the frame (measured; see the README).
    monkeypatch.setitem(sb.IFRAME_ATTRIBUTES, "allow", "")
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _ = await make_media_deck(stack)
        plan = opened(pid) + [
            {"wait": 1000}, {"click": SOUND_BTN},
            {"until": media_is(1, "s.blocked===true"), "ms": 8000, "as": "blocked_said"},
            {"value": "blocked", "expr": MEDIA}, {"value": "blocked_audio", "expr": AUDIO_TAGS, "scope": "sandbox"},
            {"value": "allow_attr", "expr": f"(()=>{{const f={FRAME};return f.contentDocument.querySelector('iframe').getAttribute('allow')}})()"},
            {"clickExpr": STAGE_CENTER},
            {"until": media_is(1, "s.blocked===false&&s.muted===false"), "ms": 8000, "as": "lifted_by_click"},
            {"value": "lifted", "expr": MEDIA},
            {"click": LIRE}, {"until": media_is(1, "s.playing&&s.frame>=30"), "ms": 30000, "required": True, "as": "playing"},
            {"value": "playing_audio", "expr": AUDIO_TAGS, "scope": "sandbox"},
            {"burst": str(tmp_path), "ms": 1, "scale": 0.5, "prefix": "lifted",
             "clipExpr": "(()=>{const r=document.querySelector('#jvStudioExplorer .jvx-preview').getBoundingClientRect();return {x:r.left,y:r.top,width:r.width,height:r.height}})()"},
        ]
        reads = harness_ok(await run_media(stack.page_url, plan))
    blocked, lifted = reads["blocked"], reads["lifted"]
    checks = {
        "the frame really had no delegation": reads["allow_attr"] == "",
        "the refusal is said in French with what to do (notice, pill on the image, marked button)": reads["blocked_said"]
            and "Cliquez une fois dans l'image" in blocked["notice"] and "cliquez une fois dans l'image" in blocked["pill"]
            and blocked["button"]["state"] == "blocked" and blocked["muted"] is True,
        "the Player was never unmuted against the browser (no frozen playback)": reads["blocked_audio"]["audio"] is None or reads["blocked_audio"]["audio"]["muted"],
        "one real click in the image lifts the refusal": reads["lifted_by_click"] and lifted["pill"] == "" and lifted["button"]["state"] is None,
        "the scene then plays with its sound": reads["playing_audio"]["audio"] is not None and not reads["playing_audio"]["audio"]["muted"]
            and not reads["playing_audio"]["audio"]["paused"],
    }
    shots = sorted(tmp_path.glob("lifted-*.png"))[:1]
    record("sound-refused", {"checks": checks, "blocked": blocked, "lifted": lifted, "playing_audio": reads["playing_audio"]}, shots)
    summarize("sound_refused", {"checks": checks})
    assert all(checks.values()), {k: v for k, v in checks.items() if not v}


@pytest.mark.parametrize("policy", ["default", "no-user-gesture-required"])
async def test_a_sound_wish_without_any_gesture_is_refused_and_said_and_never_freezes_playback(tmp_path, policy):
    """No CDP click at all (`element.click()` from script: no user activation anywhere). The default policy refuses the sound; Remotion would
    wait for an AudioContext that never starts, so the frame re-mutes the Player and says it (the image keeps moving). The browser flag that
    lifts the policy is the reference measure: the same path then plays with sound."""

    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _ = await make_media_deck(stack)
        plan = opened(pid) + [
            {"wait": 800}, {"eval": f"document.querySelector('{SOUND_BTN}').click()"}, {"wait": 600},
            {"value": "wish", "expr": MEDIA},
            {"eval": f"document.querySelector('{LIRE}').click()"},
            {"until": media_is(1, "s.phase==='playing'"), "ms": 10000, "as": "asked"},
            {"wait": 3500}, {"value": "later", "expr": MEDIA}, {"value": "later_audio", "expr": AUDIO_TAGS, "scope": "sandbox"},
            {"wait": 1000}, {"value": "later2", "expr": MEDIA},
            {"value": "activation", "expr": "navigator.userActivation.hasBeenActive"},
        ]
        args = "--autoplay-policy=no-user-gesture-required" if policy != "default" else ""
        reads = harness_ok(await run_media(stack.page_url, plan, chrome_args=args))
    later, later2 = reads["later"], reads["later2"]
    moving = later2["frame"] is not None and later["frame"] is not None and later2["frame"] > later["frame"]
    if policy == "default":
        checks = {
            "no user activation anywhere": reads["activation"] is False,
            "the refusal is said (blocked, notice, pill)": later["blocked"] is True and "refusé le son" in later["notice"] and later["pill"] != "",
            "the Player is muted again, never left waiting for audio": later["muted"] is True,
            "playback is never frozen: the image keeps moving": moving,
        }
    else:
        checks = {
            "no user activation anywhere": reads["activation"] is False,
            "with the policy lifted, the same path plays with sound": later["blocked"] is False and later["muted"] is False
                and reads["later_audio"]["audio"] is not None and not reads["later_audio"]["audio"]["muted"]
                and not reads["later_audio"]["audio"]["paused"],
            "playback moves": moving,
        }
    record(f"sound-no-gesture-{policy}", {"checks": checks, "wish": reads["wish"], "later": later, "later2": later2,
                                           "later_audio": reads["later_audio"], "chrome_args": args})
    summarize(f"sound_no_gesture_{policy}", {"checks": checks})
    assert all(checks.values()), {k: v for k, v in checks.items() if not v}


# ---------------------------------------------------------------------------------------------------------------- fullscreen (§ 4.12, PX-12)

async def test_fullscreen_shows_only_the_whole_slide_letterboxed_keeps_f_and_play_state_and_escape_is_nested(tmp_path):
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _ = await make_media_deck(stack)
        shots = tmp_path / "shots"
        shots.mkdir()
        full = "({x:0,y:0,width:innerWidth,height:innerHeight})"

        def shot(name: str) -> dict:
            return {"burst": str(shots), "ms": 1, "scale": 0.25, "clipExpr": full, "prefix": name, "as": f"shot_{name}"}
        plan = opened(pid) + [
            {"value": "windowed_1080", "expr": GEOMETRY},
            {"click": LIRE}, {"until": media_is(1, "s.playing&&s.frame>=10"), "ms": 30000, "required": True, "as": "playing"},
            {"value": "before", "expr": VIEW},
            {"click": FS_BTN},
            {"until": "document.fullscreenElement===document.querySelector('#jvStudioExplorer .jvx-theater')", "ms": 5000, "required": True,
             "as": "entered"},
            {"value": "in", "expr": FULLSCREEN}, {"value": "in_view", "expr": VIEW},
            {"wait": 2900}, {"value": "hidden", "expr": FULLSCREEN}, shot("S1"),
            {"until": media_is(2, "s.playing&&s.frame>=8"), "ms": 30000, "required": True, "as": "s2"}, shot("S2"),
            {"until": media_is(3, "s.playing&&s.frame>=8"), "ms": 30000, "required": True, "as": "s3"}, shot("S3"),
            {"value": "s3_fs", "expr": FULLSCREEN},
            {"mouse": "mouseMoved", "atExpr": "({x:innerWidth/2,y:innerHeight/2})"}, {"wait": 150}, {"value": "poked", "expr": FULLSCREEN},
            {"until": media_is(4, "s.playing&&s.frame>=5"), "ms": 30000, "required": True, "as": "s4"},
            {"until": "document.querySelector('#jvStudioExplorer .jvx-theater').getAttribute('data-chrome')==='hidden'", "ms": 3000}, shot("S4"),
            {"key": " "}, {"until": f"{VIEW}.phase==='paused'", "ms": 5000, "as": "paused_by_space"}, {"wait": 400},
            {"value": "paused_in", "expr": VIEW}, {"value": "paused_fs", "expr": FULLSCREEN}, {"wait": 2800},
            {"value": "paused_later", "expr": FULLSCREEN},
            {"key": "f"}, {"until": "!document.fullscreenElement", "ms": 5000, "as": "left_by_f"}, {"wait": 400},
            {"value": "out", "expr": FULLSCREEN}, {"value": "out_view", "expr": VIEW},
            # window resizes keep the stage's format
            {"size": [1600, 900]}, {"wait": 500}, {"value": "windowed_1600", "expr": GEOMETRY},
            {"size": [1024, 768]}, {"wait": 500}, {"value": "windowed_1024", "expr": GEOMETRY},
            {"size": [1920, 1080]}, {"wait": 500},
            # Échap: nested, never a pause
            {"click": LIRE}, {"until": f"{VIEW}.phase==='playing'", "ms": 5000},
            {"click": FS_BTN}, {"until": "!!document.fullscreenElement", "ms": 5000, "as": "entered_again"}, {"wait": 300},
            {"key": "Escape"}, {"until": "!document.fullscreenElement", "ms": 5000, "as": "left_by_escape"}, {"wait": 600},
            {"value": "after_escape", "expr": f"({{open:JarvisStudioExplorer.isOpen(),view:{VIEW}}})"},
            {"key": "Escape"}, {"wait": 600}, {"value": "after_escape2", "expr": "JarvisStudioExplorer.isOpen()"},
        ]
        reads = harness_ok(await run_media(stack.page_url, plan, viewport="1920x1080"))
    boxes = {name: content_box(Path(reads[f"shot_{name}"][0][1])) for name in ("S1", "S2", "S3", "S4")}
    expected = {"S1": 1920 / 1080, "S2": 1024 / 768, "S3": 720 / 1280, "S4": 1.0}
    inside, before, in_view = reads["in"], reads["before"], reads["in_view"]
    out = reads["out"]
    geoms = {k: reads[k] for k in ("windowed_1080", "windowed_1600", "windowed_1024")}
    checks = {
        "the STAGE is the fullscreen element (not the workspace)": inside["element"] == "stage" and inside["mode"] == "fullscreen",
        "no tree, metadata, actions or strip in fullscreen": not (inside["tree"] or inside["meta"] or inside["actions"] or inside["strip"]),
        "the stage and the Player fill the screen": inside["stage"] == [0, 0, 1920, 1080] and inside["frame"] == [0, 0, 1920, 1080],
        "entering keeps f and the play state": in_view["phase"] == "playing" and in_view["frame"] >= before["frame"],
        "the transport hides itself while playing and comes back on a move": reads["hidden"]["chrome"] == "hidden"
            and reads["hidden"]["noteOpacity"] == "0" and reads["poked"]["chrome"] == "shown",
        "the complete slide at its own format, black bars (16:9, 4:3, 9:16, 1:1)": all(
            boxes[k]["ratio"] is not None and abs(boxes[k]["ratio"] - expected[k]) / expected[k] < 0.03 for k in boxes),
        "paused in fullscreen: the transport stays": reads["paused_by_space"] and reads["paused_later"]["chrome"] == "shown",
        "F leaves; f and the paused state are kept; the focus goes back to the opener": reads["left_by_f"] and out["element"] is None
            and reads["out_view"]["phase"] == "paused" and reads["out_view"]["frame"] == reads["paused_in"]["frame"]
            and out["focus"] in ("jvx-btn", "Plein écran", "Quitter le plein écran"),
        "the stage keeps 16:9 inside the preview at every window size": all(abs(g["ratio"] - 16 / 9) < 0.01 and g["inside"] and not g["overflowX"]
                                                                          and g["frame"] == g["stage"] or (g["frame"] and abs(g["frame"][0] - g["stage"][0]) <= 2)
                                                                          for g in geoms.values()),
        "the first Échap leaves fullscreen only, never pauses": reads["left_by_escape"] and reads["after_escape"]["open"] is True
            and reads["after_escape"]["view"]["phase"] == "playing",
        "the next Échap closes Variants": reads["after_escape2"] is False,
    }
    picked = [Path(reads[f"shot_{k}"][0][1]) for k in ("S1", "S2", "S3", "S4")]
    record("fullscreen", {"checks": checks, "boxes": boxes, "inside": inside, "hidden": reads["hidden"], "poked": reads["poked"],
                          "before": before, "in_view": in_view, "paused_in": reads["paused_in"], "out": out, "out_view": reads["out_view"],
                          "geometry": geoms, "after_escape": reads["after_escape"]},
           picked)
    summarize("fullscreen", {"checks": checks, "boxes": {k: v["ratio"] for k, v in boxes.items()}})
    assert all(checks.values()), {k: v for k, v in checks.items() if not v}


# ---------------------------------------------------------------------------------------------------------------- keys in the scene (§ 4.15)

async def test_keys_typed_in_the_focused_scene_act_once_and_a_scene_without_the_focus_cannot_press_them(tmp_path):
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _ = await make_media_deck(stack)
        in_scene = "(()=>{const a=document.activeElement;return !!a&&a.tagName==='IFRAME'&&!!a.closest('#jvStudioExplorer .jvx-stage')})()"
        plan = opened(pid) + [
            {"wait": 800}, {"clickExpr": STAGE_CENTER}, {"wait": 300}, {"value": "focus_in_scene", "expr": in_scene},
            {"key": " "}, {"until": f"{VIEW}.phase==='playing'", "ms": 5000, "as": "space_plays"}, {"wait": 700},
            {"value": "after_space", "expr": MEDIA},
            {"key": " "}, {"until": f"{VIEW}.phase==='paused'", "ms": 5000, "as": "space_pauses"}, {"wait": 300},
            {"key": "ArrowRight"}, {"until": media_is(2), "ms": 30000, "as": "arrow_next"}, {"wait": 800},
            {"value": "after_arrow", "expr": f"({{media:{MEDIA},view:{VIEW}}})"},
            {"clickExpr": STAGE_CENTER}, {"wait": 300}, {"key": "m"}, {"wait": 800}, {"value": "after_m", "expr": MEDIA},
            # the scene posts a key while the focus is in the tree: refused by the stage page, nothing moves
            {"eval": "document.querySelector('#jvStudioExplorer .jvx-row').focus()"}, {"wait": 200},
            {"value": "before_forged", "expr": f"({{media:{MEDIA},view:{VIEW}}})"},
            {"eval": "parent.postMessage({rs:1,type:'key',key:' '},'*');parent.postMessage({rs:1,type:'key',key:'Escape'},'*')", "scope": "sandbox"},
            {"wait": 800}, {"value": "after_forged", "expr": f"({{media:{MEDIA},view:{VIEW},open:JarvisStudioExplorer.isOpen()}})"},
            # Échap typed in the scene: the nested rule (no menu, no dialog, no fullscreen) closes Variants. Checked BEFORE any fullscreen:
            # in headless Chrome, once the page has been fullscreen, an Échap typed in the cross-origin frame is not delivered to it any
            # more (measured, 6 s later too; the top document still gets it). The physical keys are a Human check.
            {"clickExpr": STAGE_CENTER}, {"wait": 300}, {"value": "escape_focus", "expr": in_scene}, {"key": "Escape"}, {"wait": 800},
            {"value": "after_escape", "expr": "JarvisStudioExplorer.isOpen()"},
            # reopened: F typed in the scene enters the stage fullscreen (the key is the gesture); Échap leaves
        ] + opened(pid)[1:] + [
            {"wait": 800}, {"clickExpr": STAGE_CENTER}, {"wait": 300}, {"key": "f"},
            {"until": "!!document.fullscreenElement", "ms": 5000, "as": "f_from_scene"}, {"wait": 300},
            {"value": "fs", "expr": FULLSCREEN}, {"key": "Escape"}, {"until": "!document.fullscreenElement", "ms": 5000, "as": "f_leaves"},
        ]
        reads = harness_ok(await run_media(stack.page_url, plan))
    arrow = reads["after_arrow"]
    forged_before, forged_after = reads["before_forged"], reads["after_forged"]
    checks = {
        "a click puts the focus in the cross-origin scene": reads["focus_in_scene"] is True,
        "Space typed in the scene plays, then pauses (once each)": reads["space_plays"] and reads["space_pauses"]
            and reads["after_space"]["keysRelayed"] == 1,
        "→ typed in the scene goes to the next scene once (S2, frame 0)": reads["arrow_next"] and arrow["media"]["scene"] == "S2"
            and arrow["view"]["scene_index"] == 1 and arrow["view"]["phase"] == "paused",
        "M typed in the scene toggles the sound once": reads["after_m"]["sound"]["toggles"] == 1 and reads["after_m"]["sound"]["on"] is True,
        "F typed in the scene enters the stage fullscreen (the key is the gesture); Échap leaves": reads["f_from_scene"]
            and reads["fs"]["element"] == "stage" and reads["f_leaves"],
        "a key posted by the scene without the focus is refused, nothing moves": forged_after["media"]["keysRefused"] >= 2
            and forged_after["view"]["phase"] == forged_before["view"]["phase"] and forged_after["view"]["frame"] == forged_before["view"]["frame"]
            and forged_after["open"] is True,
        "Échap typed in the scene closes Variants (nested rule)": reads["after_escape"] is False,
    }
    record("scene-keys", {"checks": checks, **{k: reads[k] for k in ("after_space", "after_arrow", "after_m", "fs", "before_forged", "after_forged",
                                                                      "escape_focus")}})
    summarize("scene_keys", {"checks": checks})
    assert all(checks.values()), {k: v for k, v in checks.items() if not v}


# ---------------------------------------------------------------------------------------------------------------- robustness

async def test_reduced_motion_reload_and_a_long_session_leave_no_animation_no_leak_and_a_stable_frame_count(tmp_path):
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _ = await make_media_deck(stack)
        cycle = [
            {"click": FS_BTN}, {"until": "!!document.fullscreenElement", "ms": 5000}, {"wait": 300},
            {"key": "f"}, {"until": "!document.fullscreenElement", "ms": 5000}, {"wait": 200},
            {"click": NEXT}, {"wait": 500}, {"click": LIRE}, {"wait": 500},
        ]
        plan = [{"media": [{"name": "prefers-reduced-motion", "value": "reduce"}]}] + opened(pid) + [
            {"value": "leaks0", "expr": LEAKS, "cli": True}, {"value": "sandboxes0", "expr": "1", "scope": "sandboxes"},
            {"click": LIRE}, {"until": media_is(1, "s.playing&&s.frame>=5"), "ms": 30000, "required": True},
            {"click": FS_BTN}, {"until": "!!document.fullscreenElement", "ms": 5000, "required": True}, {"wait": 2900},
            {"value": "reduced_hidden", "expr": FULLSCREEN},
            {"value": "reduced_any_transition", "expr": "[...document.querySelectorAll('#jvStudioExplorer *')].filter(e=>{const c=getComputedStyle(e);"
                                                         "return (c.transitionDuration.split(',').some(d=>parseFloat(d)>0))||c.animationName!=='none'}).length"},
            {"key": "f"}, {"until": "!document.fullscreenElement", "ms": 5000},
        ] + cycle * 10 + [
            {"wait": 1500}, {"value": "leaks1", "expr": LEAKS, "cli": True}, {"value": "sandboxes1", "expr": "1", "scope": "sandboxes"},
            {"value": "host_stats", "expr": "JarvisStudioExplorer.stats()"},
            {"reload": True},
        ] + opened(pid) + [
            {"wait": 800}, {"value": "reloaded", "expr": MEDIA}, {"value": "reloaded_fs", "expr": FULLSCREEN},
            {"value": "leaks2", "expr": LEAKS, "cli": True},
        ]
        reads = harness_ok(await run_media(stack.page_url, plan, timeout=900))
    l0, l1, l2 = reads["leaks0"], reads["leaks1"], reads["leaks2"]
    checks = {
        "reduced motion: the overlay hides without a fade and no UI transition or animation runs": reads["reduced_hidden"]["chrome"] == "hidden"
            and reads["reduced_hidden"]["noteTransition"] == "0s" and reads["reduced_any_transition"] == 0,
        "long session: at most the live frame and the one loaded ahead": l1["iframes"] <= 2 and len(reads["sandboxes1"]) <= 2,
        "long session: no listener accumulates": all(l1[k] == l0[k] for k in ("winMessage", "winResize", "docKeydown", "docFullscreen")),
        "long session: the DOM does not grow": l1["nodes"] - l0["nodes"] < 60,
        "after a Chrome reload Variants opens muted, windowed, paused on S1 frame 0": reads["reloaded"]["wanted"] is False
            and reads["reloaded"]["muted"] is True and reads["reloaded"]["scene"] == "S1" and reads["reloaded"]["f"] == 0
            and reads["reloaded_fs"]["element"] is None,
    }
    record("robustness", {"checks": checks, "leaks": {"start": l0, "after_10_cycles": l1, "after_reload": l2},
                          "sandboxes": [len(reads["sandboxes0"]), len(reads["sandboxes1"])], "reduced": reads["reduced_hidden"],
                          "reloaded": reads["reloaded"]})
    summarize("robustness", {"checks": checks, "leaks": {"start": l0, "after_10_cycles": l1}})
    assert all(checks.values()), {k: v for k, v in checks.items() if not v}

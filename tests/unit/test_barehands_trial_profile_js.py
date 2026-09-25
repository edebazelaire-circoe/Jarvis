"""Profil d'essai Bare Hands (tâche adaptative, Slice 04 ; § 17, décision 48).

Ce que ce fichier épingle :

- **un seul chemin** vers le moteur : `composeEffective` compose l'enregistré
  (réglages v2 + profil v3) et le delta d'essai, en trois couches lisibles, avec
  une préséance explicite (essai > rangé > réglage > défaut) par clé, et par
  main et par canal pour les seuils ;
- les tolérances clic / glissement sont **indépendantes**, et aucune
  composition enregistrée ne sort des bornes d'essai (QA : sensibilité 0,25 +
  `travelSlopNorm` calibré rendait 107 / 233 px et refusait tout essai) ;
- `JarvisBarehands.trial` : appliquer, **relire** chez le moteur, défaire,
  accepter — reçus structurés, codes nommés, rien de rangé sur un échec,
  rechargement = retour à l'enregistré ;
- les seuils par main atteignent **vraiment** le moteur (latéralité du jeton
  passée au moteur de pincement), à travers le vrai `createController` ;
- migration du profil v2 → v3 sans perte, `jitterPx`/`reachNorm` ne calibrent
  plus, parité JS/Python des valeurs acceptées ;
- un clic de ~60 ms à 30 images/s, manqué avec `pressFrames=2`, passe sous un
  essai `pressFrames=1` ;
- le rejeu de la calibration suit la clé du moteur image par image ;
- l'aide lit la durée de réveil **effective**.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.runtime import barehands_profile as profile

from test_barehands_lifecycle_js import WORLD  # noqa: E402
from test_barehands_tools_settings_js import browser, run_node as run_page  # noqa: E402
from test_barehands_cards_js import browser as cards_browser, run_node as run_cards  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
SCRIPT = RUNTIME / "control_center_barehands.js"
CONTRACTS = RUNTIME / "control_center_barehands_contracts.js"
RECORDER = RUNTIME / "control_center_barehands_recorder.js"
CALIBRATION = RUNTIME / "control_center_barehands_calibration.js"
HAND_ART = RUNTIME / "control_center_barehands_hand_art.js"
HUD = RUNTIME / "control_center_barehands_hud.js"


def run_node(tmp_path: Path, source: str, name: str = "trial") -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / f"barehands-{name}.cjs"
    script.write_text(
        f"const C=require({json.dumps(str(CONTRACTS))});\n"
        "global.JarvisBarehandsContracts=C;\n"
        f"const R=require({json.dumps(str(RECORDER))});\n"
        "global.JarvisBarehandsRecorder=R;\n"
        f"const Core=require({json.dumps(str(SCRIPT))});\n"
        "const B=Core;\n"
        f"global.JarvisBarehandsHandArt=require({json.dumps(str(HAND_ART))});\n"
        f"const K=require({json.dumps(str(CALIBRATION))});\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "const refused=fn=>{try{fn();return null}catch(e){return e.code||e.name||String(e)}};\n"
        "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True,
                          encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# ------------------------------------------------------------------ composition


def test_precedence_is_trial_then_stored_then_setting_then_default_per_hand_and_channel(tmp_path):
    result = run_node(tmp_path, """
      const settings=C.normalizeSettings({assistance:.8});
      const profile=C.normalizeProfile({hands:{left:{pressRatio:.2,releaseRatio:.35}},
        tuning:{releaseMs:120,targetZonePx:10}});
      const compose=trial=>Core.composeEffective({contracts:C,settings,profile,trial,viewportWidth:1000});
      const saved=compose({});
      const trial=compose({pressRatio:.24,releaseMs:90,assistance:.3});
      const secondary=compose({secondaryReleaseRatio:.5});
      out({
        saved:{left:saved.hands.left,right:saved.hands.right,releaseMs:saved.engine.releaseMs,
          pressFrames:saved.engine.pressFrames,assistance:saved.interaction.assistance,
          zone:saved.interaction.targetZonePx,sources:saved.sources},
        trial:{left:trial.hands.left.primary,right:trial.hands.right.primary,
          leftSecondary:trial.hands.left.secondary,releaseMs:trial.engine.releaseMs,
          assistance:trial.interaction.assistance,sources:trial.sources},
        secondary:{left:secondary.hands.left.secondary,right:secondary.hands.right.secondary,
          leftPrimary:secondary.hands.left.primary},
        layers:Object.keys(trial.layers),trialLayer:trial.layers.trial,
        savedLayerLeft:trial.layers.saved.hands.left.primary,
        effectiveLeft:trial.layers.effective.left.pressRatio,
      });
    """)
    s = result["saved"]
    assert s["left"]["primary"] == {"pressRatio": 0.2, "releaseRatio": 0.35}
    assert s["left"]["secondary"] is None and s["right"]["primary"] is None, "non mesuré : défaut du moteur"
    assert s["releaseMs"] == 120 and s["sources"]["releaseMs"] == "tuning"
    assert s["pressFrames"] == 2 and s["sources"]["pressFrames"] == "default"
    assert s["assistance"] == 0.8 and s["sources"]["assistance"] == "settings"
    assert s["zone"] == 10
    t = result["trial"]
    # Un essai de pressRatio n'est plus masqué par le seuil calibré de la main.
    assert t["left"] == {"pressRatio": 0.24, "releaseRatio": 0.35}, "essai > profil, l'autre moitié reste mesurée"
    assert t["right"] == {"pressRatio": 0.24, "releaseRatio": 0.42}, "essai > défaut"
    assert t["leftSecondary"] is None, "canal par canal : le secondaire n'est pas touché"
    assert t["releaseMs"] == 90 and t["sources"]["releaseMs"] == "trial", "essai > rangé"
    assert t["assistance"] == 0.3 and t["sources"]["assistance"] == "trial"
    sec = result["secondary"]
    assert sec["left"] == {"pressRatio": 0.28, "releaseRatio": 0.5}
    assert sec["right"] == {"pressRatio": 0.28, "releaseRatio": 0.5}
    assert sec["leftPrimary"] == {"pressRatio": 0.2, "releaseRatio": 0.35}
    assert result["layers"] == ["saved", "trial", "effective"]
    assert result["trialLayer"] == {"pressRatio": 0.24, "releaseMs": 90, "assistance": 0.3}
    assert result["savedLayerLeft"] == {"pressRatio": 0.2, "releaseRatio": 0.35}
    assert result["effectiveLeft"] == 0.24


def test_click_and_drag_slop_are_independent_and_never_leave_the_trial_bounds(tmp_path):
    result = run_node(tmp_path, """
      const compose=(settings,profile,trial,width)=>Core.composeEffective({contracts:C,
        settings:C.normalizeSettings(settings),profile:profile?C.normalizeProfile(profile):null,
        trial:trial||{},viewportWidth:width||1000});
      const factory=compose({});
      const sens2=compose({sensitivity:2});
      const qa=compose({sensitivity:.25},{hands:{left:{travelSlopNorm:.014}}},{},1920);
      const measured=compose({},{hands:{left:{travelSlopNorm:.01}}},{},1000);
      const tunedDrag=compose({},{tuning:{dragSlopPx:40}});
      const tunedBoth=compose({sensitivity:2},{tuning:{clickSlopPx:10,dragSlopPx:60}});
      const clickOverTravel=compose({},{hands:{left:{travelSlopNorm:.014}},tuning:{dragSlopPx:12}},{},2560);
      const trialDrag=compose({sensitivity:.25},{hands:{left:{travelSlopNorm:.014}}},{dragSlopPx:70,clickSlopPx:20},1920);
      /* L'essai que la QA voyait refusé : validé contre la base effective. */
      const base=qa.baseFor('left');
      out({factory:[factory.engine.clickSlopPx,factory.engine.dragSlopPx],
        sens2:[sens2.engine.clickSlopPx,sens2.engine.dragSlopPx],
        qa:[qa.engine.clickSlopPx,qa.engine.dragSlopPx],qaNotes:qa.notes.map(n=>n.code),
        measured:[measured.engine.clickSlopPx,measured.engine.dragSlopPx],
        tunedDrag:[tunedDrag.engine.clickSlopPx,tunedDrag.engine.dragSlopPx],
        tunedBoth:[tunedBoth.engine.clickSlopPx,tunedBoth.engine.dragSlopPx],
        raised:[clickOverTravel.engine.clickSlopPx,clickOverTravel.engine.dragSlopPx,
          clickOverTravel.notes.map(n=>n.code)],
        trialDrag:[trialDrag.engine.clickSlopPx,trialDrag.engine.dragSlopPx],
        qaTrial:C.validateTrialPatch({dragSlopPx:70},base).ok,
        bounds:[C.TRIAL_KEYS.clickSlopPx.min,C.TRIAL_KEYS.clickSlopPx.max,
          C.TRIAL_KEYS.dragSlopPx.min,C.TRIAL_KEYS.dragSlopPx.max],
        extremes:[0.25,4].flatMap(sensitivity=>[0.002,0.014].map(norm=>{
          const c=compose({sensitivity},{hands:{left:{travelSlopNorm:norm}}},{},3840);
          return [c.engine.clickSlopPx,c.engine.dragSlopPx]})),
      });
    """)
    assert result["factory"] == [12, 26]
    assert result["sens2"] == [6, 13]
    assert result["bounds"] == [3, 48, 6, 104]
    assert result["qa"] == [48, 104], "la sensibilité basse + la mesure sont bornées, pas 107 / 233"
    assert result["qaNotes"] == ["slop_bounded", "slop_bounded"]
    assert result["qaTrial"] is True, "un essai de glissement n'est plus refusé à cause de la base"
    assert result["measured"][0] == pytest.approx(10) and result["measured"][1] == pytest.approx(10 * 26 / 12)
    assert result["tunedDrag"] == [12, 40], "le glissement se règle seul"
    assert result["tunedBoth"] == [5, 30], "rangé à sensibilité 1, divisé par la sensibilité"
    assert result["raised"][0] == pytest.approx(0.014 * 2560)
    assert result["raised"][1] == result["raised"][0] and result["raised"][2] == ["drag_raised_to_click"]
    assert result["trialDrag"] == [20, 70], "un essai fixe la valeur effective telle quelle"
    for click, drag in result["extremes"]:
        assert 3 <= click <= 48 and 6 <= drag <= 104 and click <= drag


# ------------------------------------------------------------------ la page


#: Le serveur double de la route du profil range aussi `tuning` et la version,
#: comme la vraie (`barehands_profile.apply`) ; la parité de la charge utile
#: avec la vraie route est tenue plus bas.
TUNING_ROUTE = r"""
const baseApi=global.api;
global.api=async(path,opts)=>{
  if(String(path).endsWith('/profile')&&opts&&opts.method==='POST'&&!server.profileFail){
    const body=JSON.parse(opts.body);
    const answer=await baseApi(path,opts);
    server.profile.tuning=body.tuning;server.profile.schema_version=body.schema_version;
    return Object.assign({},answer,{tuning:body.tuning,schema_version:body.schema_version});
  }
  return baseApi(path,opts);
};
"""

PAGE_TAIL = r"""
await settle();
const T=BAREHANDS.trial;
const read=()=>BAREHANDS.engine().readback;
const pinch=key=>read().pinch.template.unknown.primary[key];
"""


def page(setup: str = "") -> str:
    """La page, avec un état de serveur posé **avant** son chargement."""

    return browser(TUNING_ROUTE + setup) + PAGE_TAIL


PAGE = page()


def test_apply_reads_back_rollback_restores_exactly_and_every_refusal_is_named(tmp_path):
    result = run_page(tmp_path, PAGE + """
      const before=JSON.stringify(read());
      const beforeTargets=JSON.stringify(BAREHANDS.adapters.interaction.targetOptions());
      const first=T.apply({pressFrames:1,releaseMs:120,minCutoffHz:2,targetZonePx:18,targetZoneHoldPx:24,
        pointingEnterMs:200,wakeHoldMs:1500,assistance:.9});
      const afterFirst={pressFrames:pinch('pressFrames'),releaseMs:pinch('releaseMs'),
        cutoff:read().tracking.template.minCutoffHz,zone:BAREHANDS.adapters.interaction.targetOptions(),
        enterMs:read().pointing.interaction.pointingEnterMs,watchEnterMs:read().pointing.watch.pointingEnterMs,
        wake:BAREHANDS.engine().wakeHoldMs};
      const second=T.apply({pressRatio:.2,clickSlopPx:8});
      const hands=BAREHANDS.engine().hands;
      const mid=JSON.stringify(read());
      const status=T.status();
      const back=T.rollback();
      const afterBack=JSON.stringify(read());
      const all=T.rollback({all:true});
      const restored=JSON.stringify(read())===before
        &&JSON.stringify(BAREHANDS.adapters.interaction.targetOptions())===beforeTargets;
      const refusals={
        unknown:T.apply({nope:1}),notWired:T.apply({jitterPx:3}),out:T.apply({pressFrames:9}),
        notInt:T.apply({pressFrames:1.5}),empty:T.apply({}),notObject:T.apply('pressFrames'),
        wide:T.apply({pressFrames:1,releaseFrames:1,releaseMs:10,releaseDeltaRatio:.1,releaseDoubtMaxMs:200,
          clickMaxMs:300,clickStillnessMin:.4,minCutoffHz:1,betaCutoff:.01}),
        inverted:T.apply({clickSlopPx:40}),anchor:T.apply({releaseRatio:.6}),
        proto:T.apply({toString:1}),nothing:T.rollback(),nothingToAccept:await T.accept()};
      const untouched=JSON.stringify(read())===before;
      out({first,second,afterFirst,hands,changed:mid!==before,status:{active:status.active,
        trialId:status.trialId,trial:status.trial,savedPress:status.saved.hands.left.primary,
        effectivePress:status.effective.left.pressRatio},
        back,backRestoredFirst:afterBack!==mid,all,restored,refusals,untouched,
        history:T.history().map(h=>[h.kind,h.code,h.trialId])});
    """)
    first = result["first"]
    assert first["ok"] is True and first["code"] is None and first["trialId"] == "tr-1"
    assert first["rejected"] == [] and isinstance(first["appliedAt"], (int, float))
    assert first["applied"] == {"pressFrames": 1, "releaseMs": 120, "minCutoffHz": 2, "targetZonePx": 18,
                                "targetZoneHoldPx": 24, "pointingEnterMs": 200, "wakeHoldMs": 1500,
                                "assistance": 0.9}
    a = result["afterFirst"]
    assert a["pressFrames"] == 1 and a["releaseMs"] == 120 and a["cutoff"] == 2
    assert a["zone"] == {"assistance": 0.9, "targetZonePx": 18, "targetZoneHoldPx": 24, "targetAssistPx": 24}
    assert a["enterMs"] == 200 and a["watchEnterMs"] == 200 and a["wake"] == 1500
    second = result["second"]
    assert second["ok"] is True and second["trialId"] == "tr-2"
    assert second["applied"] == {"pressRatio": 0.2, "clickSlopPx": 8}
    for handedness in ("left", "right", "unknown"):
        assert result["hands"][handedness]["primary"]["pressRatio"] == 0.2
    assert result["changed"] is True
    st = result["status"]
    assert st["active"] is True and st["trialId"] == "tr-2"
    assert st["trial"]["pressRatio"] == 0.2 and st["trial"]["pressFrames"] == 1
    assert st["savedPress"] is None and st["effectivePress"] == 0.2
    back = result["back"]
    assert back["ok"] is True and back["trialId"] == "tr-2" and back["undone"] == ["tr-2"]
    assert back["applied"] == {"pressRatio": 0.28, "clickSlopPx": 12}, "la valeur d'avant, relue"
    assert result["all"]["ok"] is True and result["all"]["undone"] == ["tr-1"]
    assert result["restored"] is True, "l'état effectif d'avant revient exactement"
    codes = {name: receipt["code"] for name, receipt in result["refusals"].items()}
    assert codes == {
        "unknown": "barehands_trial_key_unknown",
        "notWired": "barehands_trial_key_not_wired",
        "out": "barehands_trial_value_out_of_bounds",
        "notInt": "barehands_trial_value_invalid",
        "empty": "barehands_trial_patch_empty",
        "notObject": "barehands_trial_patch_invalid",
        "wide": "barehands_trial_patch_too_wide",
        "inverted": "barehands_trial_invariant_violated",
        "anchor": "barehands_trial_invariant_violated",
        "proto": "barehands_trial_key_unknown",
        "nothing": "barehands_trial_nothing_to_rollback",
        "nothingToAccept": "barehands_trial_nothing_to_accept",
    }
    for receipt in result["refusals"].values():
        assert receipt["ok"] is False and receipt["applied"] == {} and receipt["appliedAt"] is None
    assert result["untouched"] is True, "un refus ne touche pas au moteur"
    kinds = [h[0] for h in result["history"]]
    assert kinds[:4] == ["apply", "apply", "rollback", "rollback_all"]
    assert "apply_refused" in kinds and "accept_refused" in kinds


def test_a_trial_on_a_calibrated_hand_is_validated_against_that_hand(tmp_path):
    """La base d'une main calibrée n'est pas celle du moteur entier : un
    `pressRatio` au-dessus du relâchement **mesuré** de la main gauche se
    refuse, alors qu'il tiendrait sous le défaut 0,42."""

    result = run_page(tmp_path, page(
        "server.profile.hands={left:{press_ratio:.2,release_ratio:.3},right:{},unknown:{}};\n") + """
      const refused=T.apply({pressRatio:.32});
      const ok=T.apply({pressRatio:.25});
      out({refused,ok,left:BAREHANDS.engine().hands.left.primary});
    """)
    assert result["refused"]["code"] == "barehands_trial_invariant_violated"
    assert result["refused"]["rejected"][0]["handedness"] == "left"
    assert result["ok"]["ok"] is True
    assert result["left"] == {"pressRatio": 0.25, "releaseRatio": 0.3}


def test_accept_persists_exactly_the_trial_and_the_engine_keeps_the_same_values(tmp_path):
    result = run_page(tmp_path, PAGE + """
      await BAREHANDS.settings({sensitivity:2});
      await settle();
      const calls=()=>server.calls.filter(c=>c.body).length;
      T.apply({pressFrames:1,clickSlopPx:5,dragSlopPx:20,assistance:.7});
      T.apply({secondaryPressRatio:.2,secondaryReleaseRatio:.5});
      const during={click:pinch('clickSlopPx'),drag:pinch('dragSlopPx')};
      const before=calls();
      const receipt=await T.accept();
      await settle();
      const posted=server.calls.filter(c=>c.body&&String(c.path).endsWith('/profile')).pop().body;
      const settingsPosted=server.calls.filter(c=>c.body&&!String(c.path).endsWith('/profile')).pop().body;
      out({receipt,during,writes:calls()-before,tuning:posted.tuning,hands:posted.hands,version:posted.schema_version,
        assistance:settingsPosted.assistance,sensitivity:settingsPosted.sensitivity,
        after:{click:pinch('clickSlopPx'),drag:pinch('dragSlopPx'),frames:pinch('pressFrames'),
          secondary:BAREHANDS.engine().hands.right.secondary,
          assistance:BAREHANDS.adapters.interaction.targetOptions().assistance},
        status:T.status().active,profileTuning:BAREHANDS.profile().tuning,
        calibrated:BAREHANDS.profile().calibrated});
    """)
    r = result["receipt"]
    assert r["ok"] is True and r["code"] is None and r["trialId"] == "tr-2"
    assert r["accepted"] == {"pressFrames": 1, "clickSlopPx": 5, "dragSlopPx": 20, "assistance": 0.7,
                             "secondaryPressRatio": 0.2, "secondaryReleaseRatio": 0.5}
    assert r["applied"]["clickSlopPx"] == pytest.approx(5) and r["applied"]["dragSlopPx"] == pytest.approx(20)
    assert result["writes"] == 2, "un profil, un réglage — rien d'autre"
    tuned = {k: v for k, v in result["tuning"].items() if v is not None}
    # Rangés à sensibilité 1 : 5 px effectifs sous une sensibilité 2.
    assert tuned == {"press_frames": 1, "click_slop_px": 10, "drag_slop_px": 40}
    for handedness in ("left", "right", "unknown"):
        hand = result["hands"][handedness]
        assert hand["secondary_press_ratio"] == 0.2 and hand["secondary_release_ratio"] == 0.5
        assert hand["press_ratio"] is None, "le canal primaire n'a pas été essayé"
    assert result["version"] == 3
    assert result["assistance"] == 0.7 and result["sensitivity"] == 2
    after = result["after"]
    assert after["click"] == pytest.approx(result["during"]["click"])
    assert after["drag"] == pytest.approx(result["during"]["drag"])
    assert after["frames"] == 1 and after["assistance"] == 0.7
    assert after["secondary"] == {"pressRatio": 0.2, "releaseRatio": 0.5}
    assert result["status"] is False, "accepté : plus d'essai en cours"
    assert result["profileTuning"]["pressFrames"] == 1
    assert result["calibrated"] is True


def test_a_failed_accept_leaves_the_saved_state_untouched_and_the_trial_running(tmp_path):
    result = run_page(tmp_path, PAGE + """
      const savedBefore=JSON.stringify(server.profile);
      const settingsBefore=JSON.stringify(server.state);
      T.apply({pressFrames:1});
      server.profileFail='disque plein';
      const failed=await T.accept();
      server.profileFail=null;
      const profileUntouched=JSON.stringify(server.profile)===savedBefore;
      const stillTrial=T.status().active&&pinch('pressFrames')===1;
      /* Échec du second rangement : le premier est défait. */
      T.apply({assistance:.9});
      server.fail='refusé';
      const second=await T.accept();
      server.fail=null;
      const compensated=server.calls.filter(c=>c.body&&String(c.path).endsWith('/profile')).map(c=>c.body.tuning.press_frames);
      out({failed,profileUntouched,settingsUntouched:JSON.stringify(server.state)===settingsBefore,
        stillTrial,second,compensated,stillActive:T.status().active,
        savedFrames:BAREHANDS.profile().tuning.pressFrames});
    """)
    assert result["failed"]["ok"] is False and result["failed"]["code"] == "barehands_trial_accept_failed"
    assert result["failed"]["stage"] == "profile" and result["failed"]["trialId"] == "tr-1"
    assert result["profileUntouched"] is True and result["settingsUntouched"] is True
    assert result["stillTrial"] is True, "l'essai reste en cours, le moteur aussi"
    second = result["second"]
    assert second["code"] == "barehands_trial_accept_failed" and second["stage"] == "settings"
    assert second["compensated"] is True
    # Premier rangement (1), puis la compensation qui remet le profil d'avant (null).
    assert result["compensated"][-2:] == [1, None]
    assert result["stillActive"] is True
    assert result["savedFrames"] is None


def test_reloading_the_page_or_leaving_calibration_rolls_the_trial_back(tmp_path):
    result = run_page(tmp_path, PAGE + """
      T.apply({pressFrames:1,wakeHoldMs:1800});
      const during=[pinch('pressFrames'),BAREHANDS.engine().wakeHoldMs];
      /* Sortie de calibration sans acceptation : la page défait l'essai. */
      const discarded=T.discard('calibration_cancelled');
      const afterExit=[pinch('pressFrames'),BAREHANDS.engine().wakeHoldMs,T.status().active];
      T.apply({pressFrames:3});
      delete require.cache[require.resolve(SCRIPT_PATH)];
      require(SCRIPT_PATH);
      await settle();
      const P=window.JarvisBarehands;
      out({during,discarded,afterExit,reloaded:[P.engine().readback.pinch.template.unknown.primary.pressFrames,
        P.trial.status().active,P.trial.history().length],saved:server.calls.filter(c=>c.body).length});
    """)
    assert result["during"] == [1, 1800]
    assert result["discarded"]["ok"] is True and result["discarded"]["undone"] == ["tr-1"]
    assert result["afterExit"] == [2, 1000, False]
    assert result["reloaded"] == [2, False, 0], "un rechargement repart de l'enregistré"
    assert result["saved"] == 0, "un essai non accepté n'a rien écrit"


def test_the_page_wires_one_composition_path_and_discards_on_calibration_exit():
    page = SCRIPT.read_text(encoding="utf-8")
    for gone in ("function applyToEngine", "function applyProfile", "function travelSlopFor",
                 "const RATIO="):
        assert gone not in page, gone
    assert page.count("controller.configure(") == 2, "pushEffective (et son retour arrière) seulement"
    assert "trials.discard('calibration_saved')" in page and "trials.discard('calibration_cancelled')" in page


# ------------------------------------------------------------------ par main, vrai contrôleur


def test_per_hand_thresholds_and_trials_reach_the_live_engine_through_the_real_controller(tmp_path):
    result = run_node(tmp_path, WORLD + """
      const profile=C.normalizeProfile({hands:{left:{pressRatio:.2,releaseRatio:.3},
        right:{pressRatio:.22,releaseRatio:.36}}});
      let composition=Core.composeEffective({contracts:C,settings:C.normalizeSettings({}),profile,trial:{}});
      const run=handedness=>{
        const w=world({result:{landmarks:[hand(.65,1.8)],handedness:[[{categoryName:handedness,score:.95}]]}});
        w.deps.handOverrides=(h,c)=>composition.hands[h][c]?{...composition.hands[h][c]}:null;
        const controller=Core.createController(w.deps);
        return {w,controller};
      };
      const start=async({w,controller})=>{
        controller.enable();
        await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));
        controller.activate();
        await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));
        w.steps(6);
      };
      const left=run('Left');await start(left);
      const right=run('Right');await start(right);
      const track=c=>c.controller.options().readback.pinch.tracks[0];
      const before={left:track(left).primary.pressRatio,right:track(right).primary.pressRatio,
        leftKey:track(left).handedness};
      /* Un essai de pressRatio : trial > profil, pour les deux mains. */
      composition=Core.composeEffective({contracts:C,settings:C.normalizeSettings({}),profile,trial:{pressRatio:.25}});
      left.controller.configure(composition.engine);right.controller.configure(composition.engine);
      const during={left:[track(left).primary.pressRatio,track(left).primary.releaseRatio],
        right:[track(right).primary.pressRatio,track(right).primary.releaseRatio]};
      out({before,during});
    """)
    assert result["before"] == {"left": 0.2, "right": 0.22, "leftKey": "left"}
    assert result["during"] == {"left": [0.25, 0.3], "right": [0.25, 0.36]}


# ------------------------------------------------------------------ invariants


def test_every_trial_invariant_pair_is_refused_before_it_reaches_the_engine(tmp_path):
    result = run_page(tmp_path, PAGE + """
      const before=JSON.stringify(read());
      const out_={};
      for(const rule of C.TRIAL_INVARIANTS){
        if(!C.TRIAL_KEYS[rule.low]||!C.TRIAL_KEYS[rule.high]){
          /* L'ancre : un relâchement au-dessus de wakeGapMin. */
          out_[rule.low+'/'+rule.high]=T.apply({[rule.low]:.5}).code;continue;
        }
        const lo=C.TRIAL_KEYS[rule.low],hi=C.TRIAL_KEYS[rule.high];
        /* Des bornes qui ne se croisent pas rendent la paire inversable par
           aucun essai : sûre par construction, et dite comme telle. */
        if(lo.min>=hi.max){out_[rule.low+'/'+rule.high]='unreachable';continue}
        if(lo.max<hi.min||(rule.strict?lo.max<hi.min:lo.max<=hi.min)){
          out_[rule.low+'/'+rule.high]='disjoint';continue;
        }
        /* Le haut à son minimum, le bas juste au-dessus (ou égal si strict). */
        const high=hi.min,low=rule.strict?Math.max(lo.min,high):Math.min(lo.max,high+lo.step);
        out_[rule.low+'/'+rule.high]=T.apply({[rule.low]:low,[rule.high]:high}).code;
      }
      out({codes:out_,untouched:JSON.stringify(read())===before,rules:C.TRIAL_INVARIANTS.length});
    """)
    assert result["rules"] == 8
    for pair, code in result["codes"].items():
        if pair == "stillSpeedPx/moveSpeedPx":
            # 8–80 contre 200–900 : aucun essai ne peut l'inverser.
            assert code == "disjoint", pair
            continue
        assert code == "barehands_trial_invariant_violated", pair
    assert result["untouched"] is True
    assert "pointingFoldStartPalms/pointingFoldEndPalms" in result["codes"]
    assert "pointingExitScore/pointingEnterScore" in result["codes"]


def test_every_advertised_key_has_bounds_a_store_and_a_live_reader(tmp_path):
    """D4 : chaque clé annoncée se relit chez le moteur **après** un essai —
    appliquée seule à sa borne la plus éloignée du défaut qui reste valide."""

    result = run_page(tmp_path, PAGE + """
      const report={};
      for(const key of C.TRIAL_ADVERTISED_KEYS){
        const k=C.TRIAL_KEYS[key];
        const candidates=[k.min,k.max,k.default+k.step,k.default-k.step].filter(v=>v>=k.min&&v<=k.max&&v!==k.default);
        let receipt=null;
        for(const value of candidates){
          receipt=T.apply({[key]:value});
          if(receipt.ok)break;
        }
        report[key]={ok:receipt.ok,code:receipt.code,store:k.store&&k.store.kind,
          applied:receipt.ok?receipt.applied[key]:null,asked:receipt.ok?T.status().trial[key]:null};
        T.rollback({all:true});
      }
      out({report,notAdvertised:C.TRIAL_KEY_NAMES.filter(k=>!C.TRIAL_ADVERTISED_KEYS.includes(k))});
    """)
    assert result["notAdvertised"] == ["jitterPx"]
    for key, row in result["report"].items():
        assert row["ok"] is True, (key, row)
        assert row["store"] in ("profile", "settings", "tuning"), key
        assert row["applied"] == pytest.approx(row["asked"]), key


# ------------------------------------------------------------------ profil v3


def test_a_v2_profile_migrates_without_loss_and_unread_metrics_no_longer_calibrate(tmp_path):
    result = run_node(tmp_path, """
      const v2={schemaVersion:2,updatedAt:5,hands:{left:{pressRatio:.2,releaseRatio:.3,jitterPx:3,
        travelSlopNorm:.01,reachNorm:{x:.1,y:.1,w:.5,h:.5},quality:.8}},stages:{neutral:{status:'ok',samples:4}}};
      const read=C.normalizeProfile(v2);
      const metricsOnly=C.normalizeProfile({schemaVersion:2,hands:{left:{jitterPx:3,reachNorm:{x:0,y:0,w:.5,h:.5},quality:.9}}});
      out({read,metricsOnly:metricsOnly.calibrated,foreign:refused(()=>C.normalizeProfile({schemaVersion:4})),
        bounds:C.PROFILE_TUNING_BOUNDS,pairs:C.PROFILE_TUNING_PAIRS,wire:C.PROFILE_TUNING_WIRE_KEYS,
        tuningOnly:C.normalizeProfile({tuning:{wakeHoldMs:1500}}).calibrated,
        clampedInt:C.normalizeProfile({tuning:{pressFrames:1.6}}).tuning.pressFrames,
        brokenPair:C.normalizeProfile({tuning:{pointingExitScore:.6,pointingEnterScore:.3,releaseMs:90}}).tuning});
    """)
    read = result["read"]
    assert read["schemaVersion"] == 3 and read["calibrated"] is True and read["updatedAt"] == 5
    assert read["hands"]["left"]["jitterPx"] == 3 and read["hands"]["left"]["reachNorm"]["w"] == 0.5
    assert read["hands"]["left"]["travelSlopNorm"] == 0.01 and read["stages"]["neutral"]["status"] == "ok"
    assert all(v is None for v in read["tuning"].values())
    assert result["metricsOnly"] is False, "jitterPx/reachNorm sans lecteur ne calibrent plus"
    assert result["foreign"] == "barehands_schema_version_unsupported"
    assert result["tuningOnly"] is True
    assert result["clampedInt"] == 2
    broken = result["brokenPair"]
    assert broken["pointingExitScore"] is None and broken["pointingEnterScore"] is None
    assert broken["releaseMs"] == 90, "une paire inversée tombe en entier, le reste reste"
    # Parité avec le serveur.
    wire = result["wire"]
    assert set(wire.values()) == set(profile.TUNING_BOUNDS)
    for key, spec in result["bounds"].items():
        low, high, default, integer = profile.TUNING_BOUNDS[wire[key]]
        assert (spec["min"], spec["max"], spec["default"], spec["integer"]) == pytest.approx(
            (low, high, default, integer)), key
    assert [(wire[p["low"]], wire[p["high"]], p["strict"]) for p in result["pairs"]] == list(profile.TUNING_PAIRS)
    assert profile.SCHEMA_VERSION == 3 and profile.MIGRATED_SCHEMA_VERSIONS == (1, 2)
    assert profile.METRIC_KEYS == ("jitter_px", "reach_norm", "quality")


def test_the_server_migrates_v2_refuses_bad_tuning_and_archives_a_newer_profile():
    v2 = {"schema_version": 2, "hands": {"left": {"press_ratio": 0.2, "release_ratio": 0.3, "jitter_px": 2.0}}}
    loaded = profile.load({profile.SETTING_KEY: v2})
    assert loaded["hands"]["left"]["press_ratio"] == 0.2 and loaded["hands"]["left"]["jitter_px"] == 2.0
    assert all(v is None for v in loaded["tuning"].values()) and loaded["calibrated"] is True
    only_jitter = profile.load({profile.SETTING_KEY: {"schema_version": 2, "hands": {"left": {"jitter_px": 2.0}}}})
    assert only_jitter["calibrated"] is False and only_jitter["hands"]["left"]["jitter_px"] == 2.0

    settings: dict = {}
    saved = profile.apply(settings, {"schema_version": 3, "tuning": {"press_frames": 1, "wake_hold_ms": 1500}})
    assert saved["tuning"]["press_frames"] == 1 and saved["calibrated"] is True
    assert profile.load(settings)["tuning"]["wake_hold_ms"] == 1500
    for bad, code in (({"press_frames": 1.5}, "barehands_profile_out_of_range"),
                      ({"press_frames": 9}, "barehands_profile_out_of_range"),
                      ({"press_frames": True}, "barehands_profile_not_derived"),
                      ({"grip": 1}, "barehands_profile_unknown_field"),
                      ({"pointing_exit_score": 0.6, "pointing_enter_score": 0.3}, "barehands_profile_tuning_invalid"),
                      ({"click_slop_px": 50}, "barehands_profile_tuning_invalid")):
        before = dict(settings)
        with pytest.raises(profile.BarehandsProfileError) as caught:
            profile.apply(settings, {"schema_version": 3, "tuning": bad})
        assert caught.value.code == code, bad
        assert settings == before, "un refus n'écrit rien"

    newer = {profile.SETTING_KEY: {"schema_version": 4, "tuning": {"x": 1}}}
    assert profile.describe(newer)["unreadable"] is True
    profile.apply(newer, {"schema_version": 3})
    assert newer["barehands_calibration_profile_archived_v4"] == {"schema_version": 4, "tuning": {"x": 1}}


def test_the_payload_an_accept_builds_is_accepted_by_the_real_route(tmp_path):
    result = run_page(tmp_path, PAGE + """
      await BAREHANDS.settings({sensitivity:.5});
      T.apply({pressFrames:1,clickSlopPx:30,dragSlopPx:90,pointingFoldStartPalms:1.35,pointingFoldEndPalms:1.7,
        pressRatio:.24,releaseRatio:.4});
      await T.accept();
      out(server.calls.filter(c=>c.body&&String(c.path).endsWith('/profile')).pop().body);
    """)
    settings: dict = {}
    saved = profile.apply(settings, result)
    assert saved["tuning"]["click_slop_px"] == 15 and saved["tuning"]["drag_slop_px"] == 45
    assert saved["tuning"]["press_frames"] == 1
    assert saved["hands"]["right"]["press_ratio"] == 0.24 and saved["hands"]["right"]["release_ratio"] == 0.4


# ------------------------------------------------------------------ 30 images/s


def test_a_60ms_click_at_30fps_is_missed_with_two_frames_and_registers_under_a_one_frame_trial(tmp_path):
    result = run_node(tmp_path, """
      /* Un clic vif de ~60 ms vu à 30 images/s : une seule image sous le seuil
         d'appui, encadrée par deux images de fermeture / réouverture. */
      const ratios=[.8,.8,.5,.12,.5,.8,.8,.8,.8,.8,.8,.8];
      const play=options=>{
        const ch=Core.createPinchChannel('primary',options);
        const events=[];
        ratios.forEach((ratio,i)=>{
          for(const e of ch.update({handTrackId:1,ratio,other:.9,confidence:1,quality:1,stillness:1,
            now:i*33,x:100,y:100,palmX:100,palmY:100,anchorX:100,anchorY:100}))events.push(e.phase+(e.intent?':'+e.intent:''));
        });
        return events;
      };
      const saved=Core.composeEffective({contracts:C,settings:C.normalizeSettings({}),profile:null,trial:{}});
      const trial=Core.composeEffective({contracts:C,settings:C.normalizeSettings({}),profile:null,trial:{pressFrames:1}});
      out({saved:play(saved.engine),trial:play(trial.engine),bounds:[C.TRIAL_KEYS.pressFrames.min,C.TRIAL_KEYS.pressFrames.max]});
    """)
    assert not any(e.startswith("down") for e in result["saved"]), "pressFrames=2 manque le clic à 30 images/s"
    assert result["trial"][0].startswith("down") and "up:click" in result["trial"]
    assert result["bounds"] == [1, 4]


# ------------------------------------------------------------------ rejeu et aide


def test_the_calibration_replay_follows_the_engine_key_frame_by_frame(tmp_path):
    result = run_node(tmp_path, """
      /* La piste commence sous `unknown` (seuil d'usine 0,28) puis le moteur la
         résout `left` (seuil 0,45 / 0,6) avant un pincement qui ne descend
         qu'à 0,4 : seul le seuil de `left` le voit. */
      const opts={unknown:{},left:{pressRatio:.45,releaseRatio:.6}};
      const asked=[];
      const make=key=>{asked.push(key);return Core.createPinchChannel('primary',opts[key])};
      const rows=[];
      for(let i=0;i<40;i+=1){
        const t=i*16;
        const ratio=i>=20&&i<26?.4:.8;
        rows.push({t,handTrackId:1,primaryRatio:ratio,secondaryRatio:.9,primaryConfidence:1,quality:1,stillness:1,
          pinchHandedness:i<10?'unknown':'left',filteredX:0,filteredY:0,palmX:0,palmY:0,pointerX:0,pointerY:0});
      }
      out({contacts:K.replayPinchContacts(rows,'primary',make,250),asked});
    """)
    assert result["asked"] == ["unknown", "left"]
    assert len(result["contacts"]) == 1 and result["contacts"][0]["down"] is not None


def test_the_help_card_reads_the_effective_wake_hold(tmp_path):
    """L'aide disait la constante du contrat (1 s) quel que soit le réglage :
    elle relit maintenant la durée que le moteur exige."""

    result = run_cards(tmp_path, cards_browser() + r"""
      const receipt=BAREHANDS.trial.apply({wakeHoldMs:1500});
      await BAREHANDS.showHelp();
      await settle();
      const shown=textOf(cardRoot);
      out({receipt:receipt.ok,shown:/tenez 1,5 seconde/.test(shown),
        model:CARDS.helpModel({wakeHoldMs:1500}).wake.holdMs,fallback:CARDS.helpModel().wake.holdMs,
        fallbackText:/tenez 1 seconde/.test(CARDS.helpModel().wake.text)});
    """)
    assert result == {"receipt": True, "shown": True, "model": 1500, "fallback": 1000, "fallbackText": True}

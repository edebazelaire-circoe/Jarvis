"""Épisodes de pincement et latences d'appui/relâchement (Slice 02 adaptative).

Tâche `jarvis-bare-hands-adaptive-calibration-benchmark`, décisions 35 et 43.
Exécuté par node sur les **vrais** modules : le segmenteur et la dérivation de
la calibration, le vrai canal de pincement du moteur (`createPinchChannel`)
rejoué pour les latences, les vrais contrats et le vrai enregistreur.

Ce que ce fichier épingle :

- **un geste vaut une voix** : un pincement tenu deux secondes ne pèse pas plus
  qu'un clic vif de 80 ms, et un clic vif calibre aussi bien qu'un pincement
  appuyé ;
- **les phases et les latences suivent la vérité synthétique** à 30 et à 60
  images/s, à une image près — la vérité d'appui et de relâchement étant ce
  que les réglages documentés du détecteur (`pressFrames`, `releaseFrames`,
  `releaseMs`, `releaseDeltaRatio`) font d'une trajectoire connue ;
- **ce qui n'a pas été vu n'est pas deviné** : flux coupé, épisode tronqué,
  trou, images douteuses — refusés sous un code, jamais complétés ;
- **la dérivation garde ses refus** (`TOO_FEW_SAMPLES`, `NOT_SEPARABLE`,
  `OUT_OF_BAND`) et ses invariants (`press < release`, relâchement primaire
  sous `wakeGapMin`) ;
- **la séance porte la preuve** par les contrats de la Slice 01 : épisodes
  `createPinchEpisode`, jeu de mesures `createMeasurementSet`, événements
  `pinch_press`/`pinch_release` validés par `validateSessionSample`.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
CONTRACTS = RUNTIME / "control_center_barehands_contracts.js"
RECORDER = RUNTIME / "control_center_barehands_recorder.js"
BAREHANDS = RUNTIME / "control_center_barehands.js"
CALIBRATION = RUNTIME / "control_center_barehands_calibration.js"
HAND_ART = RUNTIME / "control_center_barehands_hand_art.js"

# Le pilote du parcours de calibration est **réutilisé**, pas recopié : un
# second double de DOM décrirait un autre parcours sous le même nom.
from test_barehands_calibration_js import DOM, DRIVER  # noqa: E402

#: Trajectoires synthétiques et vérité terrain, partagées par les tests.
#: `pinch(spec)` : un rapport ouvert tenu, une fermeture linéaire, un minimum
#: tenu, une réouverture linéaire. La vérité des bords est **analytique** ;
#: celle des appuis et relâchements se lit sur la grille d'images avec les
#: réglages documentés du détecteur — pas en rejouant le détecteur.
HELPERS = r"""
const D=Core.DEFAULTS;
const shapeOf=(pinches,open)=>t=>{
  for(const p of pinches){
    const a=t-p.at;
    if(a<0)continue;
    if(a<p.closeMs)return open-(open-p.closed)*a/p.closeMs;
    if(a<p.closeMs+p.holdMs)return p.closed;
    const b=a-p.closeMs-p.holdMs;
    if(b<p.openMs)return p.closed+(open-p.closed)*b/p.openMs;
  }
  return open;
};
/* Un flux d'enregistrements de scalaires, comme `deps.onMeasure` les publie. */
const streamOf=(fps,total,shape,extra)=>{
  const dt=1000/fps,out=[];
  for(let k=0;k*dt<=total;k+=1){
    const t=k*dt;
    const row={t,handTrackId:7,handedness:'right',primaryRatio:shape(t),secondaryRatio:.9,
      primaryConfidence:1,secondaryConfidence:0,primaryWorldRatio:.1,secondaryWorldRatio:.9,
      quality:.9,stillness:.8,palmX:600,palmY:400,filteredX:610,filteredY:380,pointerX:610,pointerY:380};
    out.push(extra?Object.assign(row,extra(t,k,row)):row);
  }
  return out;
};
const o=K.options({});
let refN=1;
const ctx=(options,extra)=>Object.assign({options:options||o,
  detector:()=>Core.createPinchChannel('primary',{}),lostGraceMs:D.lostGraceMs,
  stage:'pinch_primary',nextRef:()=>`ep-${refN++}`},extra||{});
const measure=(stream,channel,c)=>K.measurePinchEpisodes(stream,channel||'primary',c||ctx());
/* Vérité : le bord du minimum est à 90 % de la fermeture (bord à 10 % de la
   profondeur), celui de la réouverture à 10 % de la réouverture. */
const truthOf=(p)=>({startT:p.at+.1*p.closeMs,minimumT:p.at+.9*p.closeMs,
  openingT:p.at+p.closeMs+p.holdMs+.1*p.openMs,endT:p.at+p.closeMs+p.holdMs+.9*p.openMs});
/* Vérité d'appui et de relâchement, sur la grille d'images, avec les réglages
   documentés du détecteur (contrat § 5) : `pressFrames` images d'affilée sous
   `pressRatio` ; puis `releaseFrames` images au-dessus de
   `min(releaseRatio, plus serré + releaseDeltaRatio)` couvrant `releaseMs`. */
const detectorTruth=(fps,shape,p,opts)=>{
  const s=Object.assign({},D,opts||{}),dt=1000/fps;
  let run=0,down=null,tight=Infinity,first=null,count=0;
  for(let k=0;k*dt<=p.at+p.closeMs+p.holdMs+p.openMs+1000;k+=1){
    const t=k*dt;if(t<p.at-50)continue;
    const r=shape(t);
    if(down===null){
      run=r<=s.pressRatio?run+1:0;
      if(run>=s.pressFrames){down=t;tight=r}
      continue;
    }
    const opensAt=Math.min(s.releaseRatio,tight+s.releaseDeltaRatio);
    if(r>opensAt){
      if(first===null)first=t;
      count+=1;
      if(count>=s.releaseFrames&&t-first>=s.releaseMs)return {down,up:t};
    }else{first=null;count=0;tight=Math.min(tight,r)}
  }
  return {down,up:null};
};
/* Le quantile d'avant (q.1 / q.9 sur toutes les images), recopié ici **comme
   référence de parité** : la dérivation qui le portait a été supprimée. */
const allFrames=(ratios,opts)=>{
  const closed=C.quantile(ratios,.1),open=C.quantile(ratios,.9),sep=open-closed;
  return {closed,open,pressRatio:closed+sep*opts.pressAt,releaseRatio:closed+sep*opts.releaseAt};
};
"""


def run_node(tmp_path: Path, source: str, calibration_driver: bool = False) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "barehands-episodes.cjs"
    # Le pilote du parcours (`calOf`, `hand`, `skipStep`…) lit le moteur sous
    # le nom `B` et le vocabulaire de dessin en global.
    driver = ("const B=Core;\n"
              f"global.JarvisBarehandsHandArt=require({json.dumps(str(HAND_ART))});\n"
              if calibration_driver else "")
    script.write_text(
        f"const C=require({json.dumps(str(CONTRACTS))});\n"
        "global.JarvisBarehandsContracts=C;\n"
        f"const R=require({json.dumps(str(RECORDER))});\n"
        "global.JarvisBarehandsRecorder=R;\n"
        f"const Core=require({json.dumps(str(BAREHANDS))});\n"
        + driver
        + f"const K=require({json.dumps(str(CALIBRATION))});\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "const refused=fn=>{try{fn();return null}catch(e){return e.code||e.name||String(e)}};\n"
        "(async()=>{" + HELPERS + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True,
                          encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# ------------------------------------------------------------------ segmenteur


@pytest.mark.parametrize("fps", [30, 60])
def test_phases_and_latencies_match_the_synthetic_ground_truth_within_one_frame(tmp_path, fps):
    """Trois vitesses de pincement — vif (100 ms), franc, tenu — à 30 et à 60
    images/s. Bords de phases à une image près de la vérité analytique ;
    latences d'appui et de relâchement à une image près de ce que les réglages
    documentés du détecteur font de la même trajectoire."""

    result = run_node(tmp_path, f"""
      const fps={fps};
      const pinches=[
        {{at:407,closeMs:35,holdMs:30,openMs:35,closed:.1}},     // clic vif, 100 ms
        {{at:1213,closeMs:90,holdMs:120,openMs:110,closed:.12}},
        {{at:2311,closeMs:160,holdMs:900,openMs:220,closed:.08}}, // pincement tenu
      ];
      const shape=shapeOf(pinches,.8);
      const m=measure(streamOf(fps,4200,shape));
      out({{dt:1000/fps,rejected:m.rejected,episodes:m.episodes.map((ep,i)=>{{
        const truth=truthOf(pinches[i]),det=detectorTruth(fps,shape,pinches[i]);
        const minimumT=ep.startT+ep.closingMs,openingT=minimumT+ep.minimumMs;
        return {{ep,truth,det,minimumT,openingT,
          pressTruth:det.down===null?null:det.down-truth.minimumT,
          releaseTruth:det.up===null?null:det.up-truth.openingT}};
      }})}});
    """)
    dt = result["dt"]
    assert result["rejected"] == []
    assert len(result["episodes"]) == 3
    for row in result["episodes"]:
        ep, truth = row["ep"], row["truth"]
        assert ep["complete"] is True and ep["channel"] == "primary"
        assert abs(ep["startT"] - truth["startT"]) <= dt
        assert abs(row["minimumT"] - truth["minimumT"]) <= dt
        assert abs(row["openingT"] - truth["openingT"]) <= dt
        assert abs(ep["endT"] - truth["endT"]) <= dt
        assert ep["closingMs"] + ep["minimumMs"] + ep["openingMs"] == pytest.approx(ep["durationMs"])
        assert ep["baselineBefore"] == pytest.approx(0.8) and ep["baselineAfter"] == pytest.approx(0.8)
        assert ep["closingVelocity"] > 0 and ep["openingVelocity"] > 0
        assert ep["travelPx"] == 0 and ep["quality"] == pytest.approx(0.9)
        # Le détecteur a tranché (confiance 1, qualité bonne) : la latence
        # est **mesurée** et suit la vérité à une image près.
        assert row["pressTruth"] is not None
        assert abs(ep["pressLatencyMs"] - row["pressTruth"]) <= dt
        assert row["releaseTruth"] is not None
        assert abs(ep["releaseLatencyMs"] - row["releaseTruth"]) <= dt
    # Le pincement tenu ne ment pas sur sa durée ; le vif non plus.
    fast, _, held = (row["ep"] for row in result["episodes"])
    assert fast["durationMs"] < 150 and held["minimumMs"] > 800


def test_a_fast_click_missed_by_the_detector_is_a_measured_miss_not_a_zero(tmp_path):
    """Un clic de 60 ms à 30 images/s n'a qu'une image sous `pressRatio` :
    `pressFrames=2` ne le tranche pas. L'épisode existe (la main a pincé), son
    appui est `null` — un appui manqué, la preuve dont la Slice 04 aura besoin
    pour `pressFrames` — et son relâchement aussi : rien à relâcher."""

    result = run_node(tmp_path, """
      const p={at:405,closeMs:25,holdMs:10,openMs:25,closed:.1};
      const shape=shapeOf([p],.8);
      const m=measure(streamOf(30,1200,shape));
      out({episodes:m.episodes,det:detectorTruth(30,shape,p),
        // Même flux, un détecteur qui tranche à la première image.
        loose:measure(streamOf(30,1200,shape),'primary',
          ctx(o,{detector:()=>Core.createPinchChannel('primary',{pressFrames:1})})).episodes});
    """)
    assert result["det"]["down"] is None
    assert len(result["episodes"]) == 1
    assert result["episodes"][0]["pressLatencyMs"] is None
    assert result["episodes"][0]["releaseLatencyMs"] is None
    # Les options **effectives** comptent : c'est le vrai détecteur qu'on rejoue.
    assert result["loose"][0]["pressLatencyMs"] is not None


def test_noise_and_missing_frames_do_not_change_what_an_episode_is(tmp_path):
    """Bruit déterministe de ±0,03 paume et une image sur cinq perdue : les
    mêmes trois épisodes, aux mêmes bords à deux images près. Le bruit du
    traqueur ne fait jamais un épisode de plus."""

    result = run_node(tmp_path, """
      const pinches=[{at:400,closeMs:80,holdMs:100,openMs:90,closed:.1},
        {at:1300,closeMs:80,holdMs:100,openMs:90,closed:.1},
        {at:2200,closeMs:80,holdMs:100,openMs:90,closed:.1}];
      const shape=shapeOf(pinches,.8);
      let seed=12345;const rnd=()=>{seed=(seed*1103515245+12345)%2147483648;return seed/2147483648};
      const clean=measure(streamOf(60,3000,shape));
      const noisy=measure(streamOf(60,3000,t=>shape(t)+(rnd()-.5)*.06));
      const holed=measure(streamOf(60,3000,shape).filter((_,k)=>k%5!==3));
      out({clean:clean.episodes.map(e=>e.startT),noisy:noisy.episodes.map(e=>e.startT),
        holed:holed.episodes.map(e=>e.startT),rejected:[noisy.rejected,holed.rejected],
        pressHoled:holed.episodes.map(e=>e.pressLatencyMs)});
    """)
    assert len(result["clean"]) == 3
    assert len(result["noisy"]) == 3 and len(result["holed"]) == 3
    assert result["rejected"] == [[], []]
    for clean, noisy, holed in zip(result["clean"], result["noisy"], result["holed"]):
        assert abs(clean - noisy) <= 2 * 1000 / 60
        assert abs(clean - holed) <= 2 * 1000 / 60
    assert all(value is not None for value in result["pressHoled"])


def test_incomplete_episodes_are_refused_with_a_code_never_completed(tmp_path):
    """Ce qui n'a pas été vu n'est pas deviné. Flux qui commence en pleine
    fermeture, flux qui finit avant la réouverture, trou de 300 ms au milieu du
    minimum, images douteuses au milieu de la fermeture : chaque cas est
    refusé sous son code, et le pincement complet voisin reste compté."""

    result = run_node(tmp_path, """
      const full={at:1400,closeMs:80,holdMs:100,openMs:90,closed:.1};
      const run=(pinches,total,filter,extra)=>{
        const rows=streamOf(60,total,shapeOf(pinches,.8),extra);
        return measure(filter?rows.filter(filter):rows);
      };
      out({
        startsClosed:Object.assign(run([{at:-60,closeMs:80,holdMs:100,openMs:90,closed:.1},full],2200),
          {truncatedPress:K.replayPinchContacts(streamOf(60,2200,shapeOf([{at:-60,closeMs:80,holdMs:100,
            openMs:90,closed:.1},full],.8)),'primary',()=>Core.createPinchChannel('primary',{}),D.lostGraceMs)[0].down}),
        endsClosed:run([full,{at:2000,closeMs:80,holdMs:900,openMs:90,closed:.1}],2300),
        gap:run([{at:400,closeMs:80,holdMs:500,openMs:90,closed:.1},full],2200,row=>row.t<500||row.t>800),
        doubtful:run([{at:400,closeMs:80,holdMs:100,openMs:90,closed:.1},full],2200,null,
          t=>t>420&&t<700?{quality:.1}:{}),
        codes:C.EPISODE_REJECTS,
      });
    """)
    assert result["codes"] == ["barehands_episode_no_open_before", "barehands_episode_no_reopen",
                               "barehands_episode_gap", "barehands_episode_not_measured"]
    # Un trou au milieu du minimum coupe le pincement en deux moitiés : chacune
    # est refusée, aucune n'est recollée à l'autre.
    for case, codes in (("startsClosed", ["barehands_episode_no_open_before"]),
                        ("endsClosed", ["barehands_episode_no_reopen"]),
                        ("gap", ["barehands_episode_gap", "barehands_episode_gap"]),
                        ("doubtful", ["barehands_episode_gap"])):
        measured = result[case]
        assert [r["code"] for r in measured["rejected"]] == codes, case
        assert len(measured["episodes"]) == 1, case
        assert measured["episodes"][0]["startT"] > 1400, case
    # Le contact du pincement tronqué (tranché dès les premières images) n'est
    # pas prêté à l'épisode suivant : celui-ci a son propre appui, juste après
    # le début de son minimum.
    assert result["startsClosed"]["truncatedPress"] is not None
    assert 0 < result["startsClosed"]["episodes"][0]["pressLatencyMs"] < 100


# ------------------------------------------------------------------ dérivation


@pytest.mark.parametrize("fps", [30, 60])
def test_fast_clicks_and_slow_pinches_calibrate_to_the_same_thresholds(tmp_path, fps):
    """**Le critère d'acceptation de la Slice.** Même main (ouverte 0,75,
    fermée 0,12), deux façons de pincer : quatre clics vifs de 60 à 100 ms,
    ou quatre pincements appuyés tenus une seconde. Les épisodes dérivent les
    mêmes seuils ; le quantile sur toutes les images d'avant, lui, les
    déplaçait selon la façon de pincer."""

    result = run_node(tmp_path, f"""
      const fps={fps};
      const fast=[400,1100,1800,2500].map((at,i)=>({{at:at+i*7,closeMs:25+5*i,holdMs:15,openMs:30,closed:.12}}));
      const slow=[400,2100,3800,5500].map(at=>({{at,closeMs:150,holdMs:1000,openMs:200,closed:.12}}));
      const read=(pinches,total)=>{{
        const shape=shapeOf(pinches,.75);
        const rows=streamOf(fps,total,shape);
        const m=measure(rows);
        return {{n:m.episodes.length,derived:K.deriveEpisodeHysteresis(m.episodes,o,{{span:m.span,releaseCeiling:D.wakeGapMin}}),
          old:allFrames(rows.map(r=>r.primaryRatio),o)}};
      }};
      out({{fast:read(fast,3100),slow:read(slow,7300)}});
    """)
    fast, slow = result["fast"], result["slow"]
    assert fast["n"] == 4 and slow["n"] == 4
    assert fast["derived"]["ok"] is True and slow["derived"]["ok"] is True
    # Un clic vif à 30 images/s ne tombe pas toujours sur son minimum : la
    # médiane de ses minima reste à moins de 0,05 paume du pincement tenu.
    assert abs(fast["derived"]["pressRatio"] - slow["derived"]["pressRatio"]) < 0.05
    assert abs(fast["derived"]["releaseRatio"] - slow["derived"]["releaseRatio"]) < 0.05
    for side in (fast, slow):
        d = side["derived"]
        assert d["closed"] < d["pressRatio"] < d["releaseRatio"] < d["open"]
        assert d["releaseRatio"] < 0.46, "relâchement primaire sous wakeGapMin"
    # Le quantile d'avant, lui, ne voyait presque pas le minimum d'un clic vif :
    # il plaçait le « fermé » bien plus haut que la main ne se ferme.
    assert fast["old"]["closed"] - slow["old"]["closed"] > 0.1


def test_each_gesture_weighs_once_whatever_its_frame_count(tmp_path):
    """Trois clics vifs profonds (minimum 0,10) et un pincement tenu peu
    profond (0,30). Par épisodes, le « fermé » est la médiane des minima —
    0,10 — et allonger le pincement tenu d'une à quatre secondes ne le bouge
    pas. Sur toutes les images, le pincement tenu écrasait les trois clics."""

    result = run_node(tmp_path, """
      const read=holdMs=>{
        const pinches=[{at:400,closeMs:40,holdMs:20,openMs:40,closed:.10},
          {at:1000,closeMs:40,holdMs:20,openMs:40,closed:.10},
          {at:1600,closeMs:40,holdMs:20,openMs:40,closed:.10},
          {at:2200,closeMs:150,holdMs,openMs:200,closed:.30}];
        const rows=streamOf(60,2200+holdMs+900,shapeOf(pinches,.8));
        const m=measure(rows);
        return {n:m.episodes.length,derived:K.deriveEpisodeHysteresis(m.episodes,o,{span:m.span}),
          old:allFrames(rows.map(r=>r.primaryRatio),o)};
      };
      out({short:read(1000),long:read(4000)});
    """)
    short, long = result["short"], result["long"]
    assert short["n"] == 4 and long["n"] == 4
    assert short["derived"]["closed"] == pytest.approx(0.10)
    assert long["derived"]["pressRatio"] == pytest.approx(short["derived"]["pressRatio"])
    assert long["derived"]["releaseRatio"] == pytest.approx(short["derived"]["releaseRatio"])
    assert short["old"]["closed"] == pytest.approx(0.30), "l'ancien quantile : le geste le plus long gagne"


def test_parity_with_the_all_frames_quantile_on_the_gestures_it_was_built_for(tmp_path):
    """Là où l'ancienne dérivation était juste — des pincements appuyés,
    réguliers, tenus — la nouvelle rend les mêmes seuils à 0,03 paume près. Le
    remplacement change le cas qu'il corrige, pas celui qui marchait."""

    result = run_node(tmp_path, """
      const pinches=[500,2300,4100,5900].map(at=>({at,closeMs:120,holdMs:700,openMs:150,closed:.15}));
      const rows=streamOf(30,7000,shapeOf(pinches,.62));
      const m=measure(rows);
      out({derived:K.deriveEpisodeHysteresis(m.episodes,o,{span:m.span}),
        old:allFrames(rows.map(r=>r.primaryRatio),o)});
    """)
    derived, old = result["derived"], result["old"]
    assert derived["ok"] is True
    assert derived["pressRatio"] == pytest.approx(old["pressRatio"], abs=0.03)
    assert derived["releaseRatio"] == pytest.approx(old["releaseRatio"], abs=0.03)


def test_the_derivation_keeps_its_named_refusals_and_invariants(tmp_path):
    """Pas de défaut plausible : trop peu d'épisodes, une main qui ne sépare
    jamais ses deux états, un relâchement qui ne tient pas sous la posture de
    réveil — chacun son motif. Et le plafond de relâchement primaire est une
    borne du moteur, dite (`releaseCapped`), que le canal secondaire n'a pas."""

    result = run_node(tmp_path, """
      const episodesOf=(pinches,open,total)=>measure(streamOf(60,total,shapeOf(pinches,open)));
      const three=[400,1300,2200].map(at=>({at,closeMs:80,holdMs:100,openMs:90,closed:.1}));
      const wide=episodesOf(three,.8,3000);
      const shallow=episodesOf([400,1300,2200].map(at=>({at,closeMs:80,holdMs:100,openMs:90,closed:.35})),.9,3000);
      const two=episodesOf(three.slice(0,2),.8,2000);
      // Un « pincement » de 0,05 paume : la main ne sépare jamais rien.
      const flat=measure(streamOf(60,3000,t=>.42+.025*Math.sin(t/60)));
      const derive=(m,ceiling)=>K.deriveEpisodeHysteresis(m.episodes,o,{span:m.span,releaseCeiling:ceiling});
      out({
        primary:derive(wide,D.wakeGapMin),secondary:derive(wide,null),
        shallow:derive(shallow,D.wakeGapMin),shallowSecondary:derive(shallow,null),
        two:derive(two,D.wakeGapMin),flat:derive(flat,D.wakeGapMin),
        flatEpisodes:flat.episodes.length,
        stricter:K.deriveEpisodeHysteresis(wide.episodes,K.options({pinchEpisodesMin:4}),{span:wide.span}),
        options:{
          zero:refused(()=>K.options({pinchEpisodesMin:0})),
          fraction:refused(()=>K.options({pinchEpisodesMin:1.5})),
          edge:refused(()=>K.options({episodeEdge:.5})),
          gap:refused(()=>K.options({episodeGapMs:0})),
          baseline:refused(()=>K.options({episodeBaselineMs:0})),
          settle:refused(()=>K.options({pinchSettleMs:K.DEFAULTS.stageTimeoutMs})),
          clearance:refused(()=>K.options({wakeClearancePalms:.2})),
          one:refused(()=>K.options({pinchRepeats:1})),
        },
      });
    """)
    primary, secondary = result["primary"], result["secondary"]
    assert primary["ok"] is True and primary["releaseCapped"] is True
    assert primary["releaseRatio"] == pytest.approx(0.46 - 0.02)
    assert primary["pressRatio"] < primary["releaseRatio"]
    assert secondary["ok"] is True and secondary["releaseCapped"] is False
    assert secondary["releaseRatio"] > 0.46, "le secondaire ne répond pas de la posture de réveil"
    # Fermé à 0,35, ouvert à 0,9 : l'appui (0,54) passe au-dessus du plafond.
    assert result["shallow"] == {**result["shallow"], "ok": False, "reason": "barehands_stage_out_of_band"}
    assert result["shallowSecondary"]["ok"] is True
    assert result["two"]["ok"] is False and result["two"]["reason"] == "barehands_stage_too_few_samples"
    assert result["two"]["samples"] == 2
    assert result["flatEpisodes"] == 0
    assert result["flat"]["reason"] == "barehands_stage_not_separable"
    assert result["stricter"]["reason"] == "barehands_stage_too_few_samples"
    for case in ("zero", "fraction", "edge", "gap", "baseline", "settle", "clearance"):
        assert result["options"][case] == "RangeError", case
    assert result["options"]["one"] is None, "une répétition demandée reste possible : l'étape redemande"


# ------------------------------------------------------------------ détecteur rejoué


def test_the_secondary_channel_is_segmented_and_timed_on_its_own_detector(tmp_path):
    """Le pouce-majeur a ses épisodes, chronométrés par le canal secondaire du
    moteur ; le canal primaire du même flux, resté ouvert, n'en a aucun."""

    result = run_node(tmp_path, """
      const pinches=[400,1300,2200].map(at=>({at,closeMs:70,holdMs:120,openMs:90,closed:.1}));
      const shape=shapeOf(pinches,.8);
      const rows=streamOf(60,3000,shape,t=>({primaryRatio:.9,secondaryRatio:shape(t),
        primaryConfidence:0,secondaryConfidence:1,primaryWorldRatio:.9,secondaryWorldRatio:.1}));
      const c=ctx(o,{stage:'pinch_secondary',detector:()=>Core.createPinchChannel('secondary',{})});
      out({secondary:measure(rows,'secondary',c),primary:measure(rows,'primary',c).episodes.length,
        det:detectorTruth(60,shape,pinches[0]),truth:truthOf(pinches[0])});
    """)
    episodes = result["secondary"]["episodes"]
    assert len(episodes) == 3 and result["primary"] == 0
    assert {ep["channel"] for ep in episodes} == {"secondary"}
    assert {ep["stage"] for ep in episodes} == {"pinch_secondary"}
    press_truth = result["det"]["down"] - result["truth"]["minimumT"]
    assert abs(episodes[0]["pressLatencyMs"] - press_truth) <= 1000 / 60


def test_relative_release_shortens_the_measured_release_latency(tmp_path):
    """La réouverture lente d'un pincement très serré : le relâchement
    **relatif** (`releaseDeltaRatio`, 0,15) tranche bien avant le seuil absolu
    (0,42). Le rejeu le voit parce qu'il rejoue le vrai détecteur, et chaque
    latence suit la vérité à une image près."""

    result = run_node(tmp_path, """
      const pinches=[400,1600,2800].map(at=>({at,closeMs:80,holdMs:150,openMs:600,closed:.05}));
      const shape=shapeOf(pinches,.8);
      const rows=streamOf(60,3800,shape);
      const timed=delta=>measure(rows,'primary',ctx(o,{detector:()=>Core.createPinchChannel('primary',
        {releaseDeltaRatio:delta})})).episodes.map(ep=>ep.releaseLatencyMs);
      const truth=delta=>pinches.map(p=>detectorTruth(60,shape,p,{releaseDeltaRatio:delta}).up
        -truthOf(p).openingT);
      out({relative:timed(.15),absolute:timed(.6),truthRelative:truth(.15),truthAbsolute:truth(.6)});
    """)
    for measured, truth in ((result["relative"], result["truthRelative"]),
                            (result["absolute"], result["truthAbsolute"])):
        assert len(measured) == 3
        for value, expected in zip(measured, truth):
            assert abs(value - expected) <= 1000 / 60
    assert all(r < a - 100 for r, a in zip(result["relative"], result["absolute"]))


def test_the_replay_honours_quality_confidence_and_the_world_veto(tmp_path):
    """Le détecteur rejoué est le vrai : une confiance de canal sous
    `pinchConfidenceMin`, ou un rapport 3D au-dessus de `worldVetoRatio`,
    n'entre jamais en contact — l'épisode existe, son appui est manqué. Et une
    main perdue plus de `lostGraceMs` annule son contact comme le moteur."""

    result = run_node(tmp_path, """
      const pinches=[400,1300,2200].map(at=>({at,closeMs:70,holdMs:120,openMs:90,closed:.1}));
      const shape=shapeOf(pinches,.8);
      const press=extra=>measure(streamOf(60,3000,shape,extra)).episodes.map(ep=>ep.pressLatencyMs);
      const replay=Core.DEFAULTS.lostGraceMs;
      const lost=K.replayPinchContacts(streamOf(60,3000,shape).filter(r=>r.t<500||r.t>500+replay+50),
        'primary',()=>Core.createPinchChannel('primary',{}),replay);
      out({trusted:press(),unsure:press(()=>({primaryConfidence:.2})),
        vetoed:press(()=>({primaryWorldRatio:.9})),lost});
    """)
    assert all(value is not None for value in result["trusted"])
    assert result["unsure"] == [None, None, None]
    assert result["vetoed"] == [None, None, None]
    # Le contact du premier pincement est annulé par la purge, pas relâché.
    assert result["lost"][0]["up"] is None
    assert all(contact["up"] is not None for contact in result["lost"][1:])


def test_the_engine_hands_the_replay_the_exact_options_of_each_hand(tmp_path):
    """La couture `channelOptionsFor` rend ce qu'un canal de cette main reçoit
    — réglages vivants et profil de la main — et la page la passe au parcours
    (`pinchChannel`) : le rejeu tourne sur les seuils que la main vit."""

    result = run_node(tmp_path, """
      const engine=Core.createPinchIntentEngine({releaseMs:90},{handOverrides:(hand,channel)=>
        hand==='left'&&channel==='primary'?{pressRatio:.2,releaseRatio:.35}:null});
      engine.configure({releaseFrames:3});
      out({left:engine.channelOptionsFor('left','primary'),right:engine.channelOptionsFor('right','primary'),
        leftSecondary:engine.channelOptionsFor('left','secondary'),
        frozen:Object.isFrozen(engine.channelOptionsFor('left','primary'))});
    """)
    assert result["left"] == {"releaseMs": 90, "releaseFrames": 3, "pressRatio": 0.2, "releaseRatio": 0.35}
    assert result["right"] == {"releaseMs": 90, "releaseFrames": 3}
    assert result["leftSecondary"] == {"releaseMs": 90, "releaseFrames": 3}
    assert result["frozen"] is True
    page = BAREHANDS.read_text(encoding="utf-8")
    assert "pinchChannel:(channel,handedness)=>Core.createPinchChannel(channel," in page
    assert "controller.pinchChannelOptions(handedness,channel)" in page


# ------------------------------------------------------------------ séance


def test_the_calibration_session_carries_episodes_measurements_and_events(tmp_path):
    """Le parcours réel, étape de pincement primaire, nourri comme le
    contrôleur le nourrit. Une répétition demandée, trois épisodes exigés :
    l'étape **redemande** au lieu d'échouer, puis dérive ses seuils des
    épisodes et range la preuve par les contrats de la Slice 01 — épisodes,
    jeu de mesures, événements `pinch_press` / `pinch_release` qui portent la
    latence et désignent l'épisode. Le profil garde sa forme v2. Rien ne
    survit à la sortie."""

    result = run_node(tmp_path, DOM + DRIVER + """
      const logs=[];
      const cal=calOf({log:(level,message,detail)=>logs.push([level,message,detail]),
        options:{stageHoldMs:300,stageTimeoutMs:8000,stageMinSamples:10,pinchRepeats:1}});
      cal.start();
      while(cal.stepId()!=='pinch_primary')skipStep(cal);
      readOn(cal);
      const pinches=[300,1000,1700,2400,3100].map(at=>({at,closeMs:60,holdMs:60,openMs:70,closed:.1}));
      const shape=shapeOf(pinches,.8);
      const origin=clock;
      for(const row of streamOf(60,3900,shape)){
        clock=origin+row.t;
        cal.feed({now:clock,hands:[Object.assign(hand({}),row,{t:clock})]});
        if(cal.phase()==='result')break;
      }
      const session=cal.session();
      const step=[cal.stepId(),cal.phase()];
      const validated=session.samples.map(s=>{try{R.validateSessionSample(s);return true}catch(e){return e.code}});
      const measurementsOk=(()=>{try{C.createMeasurementSet(session.measurements);return true}catch(e){return e.code}})();
      document.fire('keydown',{key:'Escape'});
      out({step,episodes:session.episodes,measurements:session.measurements,history:session.samples,
        validated,measurementsOk,historyOn:session.history,
        logged:logs.filter(l=>l[1]==='[barehands] calibration.episodes').map(l=>l[2]),
        stageLog:logs.filter(l=>String(l[1]).includes('pinch_primary')).map(l=>l[2]),
        after:cal.session()});
    """, calibration_driver=True)
    assert result["step"] == ["pinch_primary", "result"], "l'étape primaire s'est soldée"
    episodes = result["episodes"]
    # Le premier pincement arme l'étape et n'est pas vu en entier : trois
    # complets exigés, donc l'étape a redemandé au-delà de sa répétition.
    assert len(episodes) >= 3
    assert all(ep["kind"] == "pinch_episode" and ep["stage"] == "pinch_primary" for ep in episodes)
    refs = [ep["ref"] for ep in episodes]
    assert refs == [f"ep-{i}" for i in range(1, len(refs) + 1)]
    assert result["measurementsOk"] is True
    for ref in refs:
        assert set(result["measurements"][ref]) == {
            "press_latency_ms", "release_latency_ms", "episode_duration_ms", "episode_min_ratio",
            "open_baseline_ratio", "closing_velocity", "opening_velocity", "episode_travel_px",
            "episode_quality"}
    assert result["historyOn"] is True
    kinds = [s["event"]["kind"] for s in result["history"]]
    assert kinds.count("pinch_press") == len(episodes)
    assert kinds.count("pinch_release") == len(episodes)
    assert all(v is True for v in result["validated"])
    first = result["history"][0]
    assert first["ref"] == "se-1" and first["event"]["ref"] == "ep-1"
    assert first["event"]["channel"] == "primary"
    assert first["event"]["latencyMs"] == pytest.approx(episodes[0]["pressLatencyMs"])
    assert first["t"] >= 0 and first["stage"] == "pinch_primary"
    logged = result["logged"]
    assert len(logged) == 1 and logged[0]["episodes"] == len(episodes)
    assert logged[0]["missedPress"] == 0
    derived = [d for d in result["stageLog"] if d and "pressRatio" in d][0]
    assert derived["samples"] == len(episodes)
    assert derived["pressRatio"] < derived["releaseRatio"] < 0.46
    assert result["after"] is None, "la séance s'efface avec le parcours (décision 41)"

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
# Le monde injecté du cycle de vie : le **vrai** contrôleur, sans navigateur.
from test_barehands_lifecycle_js import WORLD  # noqa: E402

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
    const row={t,handTrackId:7,handedness:'right',pinchHandedness:'unknown',primaryRatio:shape(t),secondaryRatio:.9,
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
/* Un double pincement : la main ne se rouvre qu'à `mid` entre les deux. */
const doubleShape=(at,open,mid,closed,closeMs,openMs)=>t=>{
  const a=t-at,seg=[[0,open],[closeMs,closed],[closeMs+40,closed],[closeMs+40+openMs,mid],
    [closeMs+140+openMs,mid],[2*closeMs+140+openMs,closed],[2*closeMs+180+openMs,closed],
    [2*closeMs+180+2*openMs,open]];
  if(a<=0)return open;
  for(let i=1;i<seg.length;i+=1)if(a<=seg[i][0]){
    const [t0,r0]=seg[i-1],[t1,r1]=seg[i];return r0+(r1-r0)*(a-t0)/(t1-t0);
  }
  return open;
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
      const shallow=episodesOf([400,1300,2200].map(at=>({at,closeMs:80,holdMs:100,openMs:90,closed:.40})),.9,3000);
      // Fermé à 0,25, ouvert à 0,80 : appui 0,44 au plan, relâchement ramené à 0,44.
      const tight=episodesOf([400,1300,2200].map(at=>({at,closeMs:80,holdMs:100,openMs:90,closed:.25})),.8,3000);
      const two=episodesOf(three.slice(0,2),.8,2000);
      // Un « pincement » de 0,05 paume : la main ne sépare jamais rien.
      const flat=measure(streamOf(60,3000,t=>.42+.025*Math.sin(t/60)));
      const derive=(m,ceiling)=>K.deriveEpisodeHysteresis(m.episodes,o,{span:m.span,releaseCeiling:ceiling});
      out({
        primary:derive(wide,D.wakeGapMin),secondary:derive(wide,null),
        shallow:derive(shallow,D.wakeGapMin),shallowSecondary:derive(shallow,null),
        two:derive(two,D.wakeGapMin),flat:derive(flat,D.wakeGapMin),
        flatEpisodes:flat.episodes.length,tight:derive(tight,D.wakeGapMin),
        stricter:K.deriveEpisodeHysteresis(wide.episodes,K.options({pinchEpisodesMin:4}),{span:wide.span}),
        options:{
          zero:refused(()=>K.options({pinchEpisodesMin:0})),
          fraction:refused(()=>K.options({pinchEpisodesMin:1.5})),
          edge:refused(()=>K.options({episodeEdge:.5})),
          gap:refused(()=>K.options({episodeGapMs:0})),
          baseline:refused(()=>K.options({episodeBaselineMs:0})),
          settle:refused(()=>K.options({pinchSettleMs:K.DEFAULTS.stageTimeoutMs})),
          clearance:refused(()=>K.options({wakeClearancePalms:.2})),
          hysteresis:refused(()=>K.options({hysteresisMinPalms:0})),
          hysteresisWide:refused(()=>K.options({hysteresisMinPalms:.12})),
          lookback:refused(()=>K.options({pinchLookbackMs:K.DEFAULTS.episodeBaselineMs})),
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
    # Fermé à 0,40, ouvert à 0,9 : relâchement ramené à 0,44, l'appui abaissé
    # à 0,39 pour garder l'hystérésis tomberait sous le fermé — refusé.
    assert result["shallow"] == {**result["shallow"], "ok": False, "reason": "barehands_stage_out_of_band"}
    # L'utilisateur ordinaire que le plafond collait à 0,018 d'hystérésis :
    # l'appui est abaissé pour garder 0,05, et le verdict le dit.
    tight = result["tight"]
    assert tight["ok"] is True and tight["releaseCapped"] is True and tight["pressCapped"] is True
    assert tight["releaseRatio"] - tight["pressRatio"] == pytest.approx(0.05)
    assert tight["pressRatio"] > tight["closed"]
    assert primary["pressCapped"] is False
    assert result["shallowSecondary"]["ok"] is True
    assert result["two"]["ok"] is False and result["two"]["reason"] == "barehands_stage_too_few_samples"
    assert result["two"]["samples"] == 2
    assert result["flatEpisodes"] == 0
    assert result["flat"]["reason"] == "barehands_stage_not_separable"
    assert result["stricter"]["reason"] == "barehands_stage_too_few_samples"
    for case in ("zero", "fraction", "edge", "gap", "baseline", "settle", "clearance",
                 "hysteresis", "hysteresisWide", "lookback"):
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


# ------------------------------------------------------------------ reprise QA : segmenteur


def test_a_hesitation_shallower_than_the_separation_is_not_a_pinch(tmp_path):
    """La règle du pincement est `separationMinPalms` (0,12), pas la moitié :
    une hésitation de 0,09 paume n'est pas un épisode, un creux de 0,13 en
    est un."""

    result = run_node(tmp_path, """
      const dip=depth=>measure(streamOf(60,1600,shapeOf([{at:400,closeMs:80,holdMs:100,openMs:90,
        closed:.8-depth}],.8))).episodes.length;
      out({hesitation:dip(.09),pinch:dip(.13)});
    """)
    assert result == {"hesitation": 0, "pinch": 1}


def test_a_stream_cut_mid_reopening_is_refused_not_completed(tmp_path):
    """Le flux s'arrête pendant la réouverture, à mi-hauteur : la ligne de base
    d'après n'a pas été vue. Refus `no_reopen`, jamais un épisode dont
    l'ouvert vaudrait 0,5."""

    result = run_node(tmp_path, """
      const p={at:400,closeMs:80,holdMs:100,openMs:300,closed:.1};
      const rows=streamOf(60,2000,shapeOf([p],.8)).filter(r=>r.t<=p.at+180+120);
      const m=measure(rows);
      out({episodes:m.episodes.length,codes:m.rejected.map(r=>r.code),last:rows[rows.length-1].primaryRatio});
    """)
    assert 0.3 < result["last"] < 0.6
    assert result["episodes"] == 0
    assert result["codes"] == ["barehands_episode_no_reopen"]


def test_a_partial_reopening_neither_moves_the_bottom_edge_nor_pulls_the_open_level_down(tmp_path):
    """Double pincement sans réouverture complète entre les deux (0,80 → 0,10 →
    0,40 → 0,10 → 0,80). Deux épisodes, et :

    - le bord du minimum se prend sur la **plus petite** profondeur (0,30) :
      sur la plus grande il tomberait au-dessus de la réouverture partielle ;
    - l'ouvert de chaque épisode est la **vraie** main ouverte (0,80), pas la
      réouverture partielle (0,40) qui tirait l'ouvert au milieu du geste ;
    - quand les deux lignes de base ne diffèrent que du bruit (0,80 / 0,76),
      c'est la plus basse qui compte : la réouverture la moins ample doit
      encore relâcher."""

    result = run_node(tmp_path, """
      const shape=doubleShape(400,.8,.4,.1,600,300);
      const m=measure(streamOf(60,4000,shape));
      const [a,b]=m.episodes;
      // Bord du minimum, vérité analytique : 10 % de la plus petite profondeur.
      const minThr=.1+.1*(.4-.1);
      const truth=400+600*(.8-minThr)/(.8-.1);
      const near=[400,1300,2200].map(at=>({at,closeMs:80,holdMs:100,openMs:90,closed:.1}));
      const nearShape=t=>{const r=shapeOf(near,.8)(t);return t>560&&t<1000?Math.min(r,.76):r};
      const n=measure(streamOf(60,3000,nearShape));
      out({count:m.episodes.length,minimumT:a.startT+a.closingMs,truth,
        baselines:[a.baselineBefore,a.baselineAfter,b.baselineBefore,b.baselineAfter],
        opens:m.episodes.map(ep=>K.episodeOpen(ep,o)),
        measured:m.episodes.map(ep=>K.episodeMeasures(ep,o).open_baseline_ratio),
        derived:K.deriveEpisodeHysteresis(m.episodes,K.options({pinchEpisodesMin:2}),{span:m.span}),
        nearBaselines:n.episodes.map(ep=>[ep.baselineBefore,ep.baselineAfter]),
        nearOpens:n.episodes.map(ep=>K.episodeOpen(ep,o)),
        // Réouverture à 0,65 : 21 % de la profondeur, au-delà de `episodeEdge`.
        midOpens:measure(streamOf(60,4000,doubleShape(400,.8,.65,.1,300,300))).episodes.map(ep=>K.episodeOpen(ep,o))});
    """)
    assert result["count"] == 2
    assert abs(result["minimumT"] - result["truth"]) < 2
    assert result["baselines"][1] == pytest.approx(0.4, abs=0.01)
    assert result["opens"] == pytest.approx([0.8, 0.8])
    assert result["measured"] == result["opens"]
    assert result["derived"]["open"] == pytest.approx(0.8)
    # Le bruit entre deux lignes de base : la plus basse.
    first = result["nearBaselines"][0]
    assert first[1] == pytest.approx(0.76, abs=0.005) and first[0] == pytest.approx(0.8)
    assert result["nearOpens"][0] == pytest.approx(0.76, abs=0.005)
    # Un écart de 21 % de la profondeur est déjà une réouverture partielle.
    assert result["midOpens"] == pytest.approx([0.8, 0.8])


def test_closed_is_the_median_of_the_minima_not_the_deepest(tmp_path):
    """Un geste aberrant, plus profond que les autres, ne fait pas le
    « fermé » : c'est la médiane des minima (0,10), pas le plus bas (0,02)."""

    result = run_node(tmp_path, """
      const pinches=[400,1300,2200,3100].map((at,i)=>({at,closeMs:80,holdMs:100,openMs:90,closed:i===2?.02:.10}));
      const m=measure(streamOf(60,4000,shapeOf(pinches,.8)));
      out({n:m.episodes.length,derived:K.deriveEpisodeHysteresis(m.episodes,o,{span:m.span})});
    """)
    assert result["n"] == 4
    assert result["derived"]["closed"] == pytest.approx(0.10)


def test_a_contact_held_across_two_episodes_is_released_by_neither(tmp_path):
    """Un détecteur qui ne relâche qu'à 0,75 (options effectives d'une main) et
    un double pincement qui ne se rouvre qu'à 0,50 entre les deux : le contact
    du premier tient jusqu'après le second. Son `up` n'est **pas** le
    relâchement du premier épisode (collé : `null`), ni un appui du second."""

    result = run_node(tmp_path, """
      const shape=doubleShape(400,.8,.5,.1,120,150);
      const rows=streamOf(60,2500,shape);
      const c=ctx(o,{detector:()=>Core.createPinchChannel('primary',{releaseRatio:.75,releaseDeltaRatio:1})});
      const m=measure(rows,'primary',c);
      out({episodes:m.episodes.map(ep=>[ep.pressLatencyMs,ep.releaseLatencyMs]),
        contacts:K.replayPinchContacts(rows,'primary',c.detector,D.lostGraceMs)});
    """)
    assert len(result["contacts"]) == 1 and result["contacts"][0]["up"] is not None
    (press1, release1), (press2, release2) = result["episodes"]
    assert press1 is not None
    assert release1 is None, "relâché après le début de l'épisode suivant : collé"
    assert press2 is None and release2 is None


def test_the_replay_uses_the_key_the_engine_resolved_not_the_token_handedness(tmp_path):
    """Le jeton dit `right` ; le moteur de pincement, lui, a résolu cette piste
    sous `unknown` (`pinchHandedness`). Le rejeu demande **cette** clé — les
    options que la main a vécues —, pas celle du jeton."""

    result = run_node(tmp_path, """
      const pinches=[400,1300,2200].map(at=>({at,closeMs:80,holdMs:100,openMs:90,closed:.1}));
      const asked=[];
      const detector=key=>{asked.push(key);
        return Core.createPinchChannel('primary',key==='left'?{pressRatio:.05,releaseRatio:.5}:{})};
      const run=key=>measure(streamOf(60,3000,shapeOf(pinches,.8),()=>({pinchHandedness:key})),'primary',
        ctx(o,{detector})).episodes.map(ep=>ep.pressLatencyMs);
      const unknown=run('unknown'),left=run('left');
      out({asked:[...new Set(asked)],unknown,left});
    """)
    assert result["asked"] == ["unknown", "left"]
    assert all(v is not None for v in result["unknown"])
    assert result["left"] == [None, None, None], "sous `left`, le seuil d'appui 0,05 n'est jamais atteint"


def test_replay_options_are_the_options_the_live_engine_used_for_that_track(tmp_path):
    """Par le **vrai** contrôleur (monde injecté du cycle de vie) : le jeton est
    `left`, et le profil a des seuils pour `left`. Depuis la Slice 04
    adaptative, le moteur de pincement reçoit la latéralité du jeton et résout
    la piste sous `left` (il la résolvait sous `unknown`, et les seuils
    calibrés par main n'atteignaient jamais le moteur). La mesure porte cette
    clé-là, et les options que la page passe au rejeu pour elle sont
    exactement celles que le moteur a demandées pour cette piste — et celles
    que son canal lit vraiment."""

    result = run_node(tmp_path, WORLD + """
      const asked=[];
      const overrides=(h,c)=>h==='left'?{pressRatio:.2,releaseRatio:.3}
        :h==='unknown'&&c==='primary'?{pressRatio:.25,releaseRatio:.4}:null;
      const w=world({options:{releaseMs:90},result:{landmarks:[hand(.65,1.8)],
        handedness:[[{categoryName:'Left',score:.95}]]}});
      w.deps.handOverrides=(h,c)=>{asked.push([h,c]);return overrides(h,c)};
      const seen=[];
      w.deps.onMeasure=r=>seen.push(r);
      const controller=Core.createController(w.deps);
      controller.enable();
      await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));
      controller.activate();
      await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));
      w.steps(12);
      const hands=seen.flatMap(r=>r.hands);
      const key=hands[0].pinchHandedness;
      const live=[...new Set(asked.filter(a=>a[1]==='primary').map(a=>a[0]))];
      const track=controller.options().readback.pinch.tracks[0];
      out({tokens:[...new Set(hands.map(h=>h.handedness))],keys:[...new Set(hands.map(h=>h.pinchHandedness))],live,
        replay:controller.pinchChannelOptions(key,'primary'),
        expected:Object.assign({},w.deps.options,overrides(live[0],'primary')),
        channel:track.primary.pressRatio,channelRelease:track.primary.releaseRatio});
    """)
    assert result["tokens"] == ["left"]
    assert result["keys"] == ["left"]
    assert result["live"] == ["left"], "le moteur n'a demandé ses surcharges que sous cette clé"
    assert result["replay"] == result["expected"]
    assert result["replay"]["pressRatio"] == 0.2
    # Le canal vivant de la main lit les seuils calibrés de `left`.
    assert result["channel"] == 0.2 and result["channelRelease"] == 0.3


# ------------------------------------------------------------------ reprise QA : le parcours

#: Le pilote des étapes de pincement : aller à l'étape, jouer une trajectoire
#: au rythme du contrôleur (60 images/s), s'arrêter au verdict.
FLOW = r"""
const logs=[];
const flowOf=(options,stageId)=>{
  const cal=calOf({log:(level,message,detail)=>logs.push([level,message,detail]),options});
  cal.start();
  while(cal.stepId()!==stageId)skipStep(cal);
  readOn(cal);
  return cal;
};
let runAt=null;
const play=(cal,shape,total,extra)=>{
  const origin=clock;
  for(const row of streamOf(60,total,t=>shape(t,origin),extra)){
    clock=origin+row.t;
    cal.feed({now:clock,hands:[Object.assign(hand({}),row,{t:clock})]});
    if(runAt===null&&cal.phase()==='running')runAt=clock;
    if(cal.phase()==='review')return true;
  }
  return false;
};
const reportOf=(cal,label)=>{
  verdictOver(cal);
  while(cal.isRunning()&&stepActions(flowRoot()).includes('skip'))skipStep(cal);
  const row=reportRows().find(r=>r[0]===label);
  return row?{status:row[1],detail:row[2]}:null;
};
const episodesLog=()=>logs.filter(l=>l[1]==='[barehands] calibration.episodes').map(l=>l[2]);
const verdictLog=stage=>logs.filter(l=>l[1]===`[barehands] calibration ${stage} : ok`
  ||l[1]===`[barehands] calibration ${stage} : failed`).map(l=>l[2]);
"""


def run_flow(tmp_path: Path, source: str) -> object:
    return run_node(tmp_path, DOM + DRIVER + FLOW + source, calibration_driver=True)


def test_a_hand_that_rests_under_the_factory_release_arms_on_a_real_pinch_and_counts_every_one(tmp_path):
    """Une main ouverte à 0,38, fermée à 0,12 : sous le relâchement d'usine
    (0,42) même au repos. Elle n'arme **pas** l'étape en restant ouverte, elle
    l'arme sur son premier vrai pincement, et ses quatre pincements comptent —
    le premier compris, puisque les images d'avant l'armement amorcent le flux :
    quatre demandés, quatre épisodes. Le rapport dit l'unité."""

    result = run_flow(tmp_path, """
      const cal=flowOf({stageTimeoutMs:8000,pinchRepeats:4},'pinch_primary');
      play(cal,t=>.38+.004*Math.sin(t/40),1500);
      const restPhase=cal.phase();
      const pinches=[300,1000,1700,2400].map(at=>({at,closeMs:80,holdMs:100,openMs:90,closed:.12}));
      const done=play(cal,shapeOf(pinches,.38),4000);
      const session=cal.session();
      out({restPhase,done,episodes:session.episodes.length,
        firstStart:session.episodes[0].startT-runAt,
        verdict:verdictLog('pinch_primary')[0],
        row:reportOf(cal,'Pincement pouce-index')});
    """)
    assert result["restPhase"] == "armed", "une main au repos n'arme rien"
    assert result["done"] is True
    assert result["episodes"] == 4, "le pincement qui arme est un épisode complet"
    assert result["firstStart"] < 0, "il a commencé avant l'armement"
    assert result["verdict"]["ok"] is True and result["verdict"]["samples"] == 4
    assert result["verdict"]["closed"] == pytest.approx(0.12, abs=0.01)
    assert result["row"]["status"] == "jf-ok"
    assert result["row"]["detail"] == "mesuré (4 épisode(s))"


def test_a_pinch_stage_that_expires_keeps_and_reports_what_it_measured(tmp_path):
    """Deux pincements, puis plus rien jusqu'à l'échéance. L'étape range et
    journalise ses deux épisodes, et échoue sur `TOO_FEW_SAMPLES` avec **deux
    épisodes** à l'appui — pas « temps écoulé » avec un compte d'images."""

    result = run_flow(tmp_path, """
      const cal=flowOf({stageTimeoutMs:5000,pinchRepeats:4},'pinch_primary');
      const pinches=[300,1000].map(at=>({at,closeMs:80,holdMs:100,openMs:90,closed:.1}));
      const done=play(cal,shapeOf(pinches,.8),8000);
      const session=cal.session();
      out({done,episodes:session.episodes.length,logged:episodesLog(),
        row:reportOf(cal,'Pincement pouce-index'),stages:null});
    """)
    assert result["done"] is True
    assert result["episodes"] == 2
    assert len(result["logged"]) == 1
    assert result["logged"][0]["final"] is True and result["logged"][0]["episodes"] == 2
    assert result["row"]["status"] == "jf-failed"
    assert "pas assez de mesures" in result["row"]["detail"]


def test_a_stage_whose_last_baseline_straddles_the_deadline_completes(tmp_path):
    """Le quatrième pincement s'achève 100 ms avant l'échéance ; l'attente de
    sa ligne de base d'après (`pinchSettleMs`, 300 ms) la chevauche. L'étape
    est **mesurée**, pas « temps écoulé »."""

    result = run_flow(tmp_path, """
      const cal=flowOf({stageTimeoutMs:5000,pinchRepeats:4},'pinch_primary');
      /* En temps absolu : le quatrième pincement se place une fois l'instant
         d'armement connu, pour s'achever ~100 ms avant l'échéance. */
      const origin0=clock;
      const base=[300,1300,2300].map(at=>({at:origin0+at,closeMs:80,holdMs:100,openMs:90,closed:.1}));
      let fourth=null;
      const abs=T=>shapeOf(fourth?base.concat([fourth]):base,.8)(T);
      play(cal,(t,origin)=>abs(origin+t),600);
      fourth={at:runAt+5000-100-260,closeMs:80,holdMs:100,openMs:90,closed:.1};
      const done=play(cal,(t,origin)=>abs(origin+t),9000);
      const verdict=verdictLog('pinch_primary')[0];
      out({done,verdict,episodes:cal.session().episodes.length,
        lastEnd:cal.session().episodes.slice(-1)[0].endT-runAt,
        deadlinePassed:clock-runAt>=5000,row:reportOf(cal,'Pincement pouce-index')});
    """)
    assert result["done"] is True
    assert result["deadlinePassed"] is True
    assert result["verdict"]["ok"] is True
    assert result["episodes"] == 4
    assert 4800 < result["lastEnd"] < 5000, "le dernier pincement finit juste avant l'échéance"
    assert result["row"]["status"] == "jf-ok"


def test_the_stage_waits_for_the_last_baseline_before_cutting(tmp_path):
    """Le dernier pincement se rouvre vite jusqu'à 0,74, puis finit de s'ouvrir
    lentement jusqu'à 0,80. L'épisode est complet dès 0,74 ; l'étape attend
    `pinchSettleMs` avant de découper, et sa ligne de base d'après dit la main
    rouverte (≈ 0,77), pas l'instant où l'épisode s'est complété (0,74)."""

    result = run_flow(tmp_path, """
      const cal=flowOf({stageTimeoutMs:8000,pinchRepeats:4},'pinch_primary');
      const base=[300,1000,1700].map(at=>({at,closeMs:80,holdMs:100,openMs:90,closed:.1}));
      const shape=t=>{
        const a=t-2400;
        if(a<0)return shapeOf(base,.8)(t);
        if(a<80)return .8-.7*a/80;
        if(a<180)return .1;
        const b=a-180;
        if(b<60)return .1+.64*b/60;
        if(b<360)return .74+.06*(b-60)/300;
        return .8;
      };
      play(cal,shape,4000);
      const eps=cal.session().episodes;
      out({n:eps.length,after:eps[eps.length-1].baselineAfter});
    """)
    assert result["n"] == 4
    assert result["after"] > 0.755


def test_low_quality_frames_still_reach_the_replayed_detector(tmp_path):
    """Des images de qualité 0,3 pendant la fermeture : sous le seuil de la
    calibration (0,4), au-dessus du plancher du moteur (0,25) — le moteur les
    croit et tranche l'appui dessus. Le flux de l'étape les garde, donc la
    latence mesurée est celle du rejeu sur **toutes** les images, pas sur les
    seules bonnes."""

    result = run_flow(tmp_path, """
      const cal=flowOf({stageTimeoutMs:8000,pinchRepeats:4},'pinch_primary');
      const pinches=[300,1300,2300,3300].map(at=>({at,closeMs:300,holdMs:100,openMs:90,closed:.1}));
      const shape=shapeOf(pinches,.8);
      const extra=(t,k,row)=>row.primaryRatio<.3&&row.primaryRatio>.12?{quality:.3}:{};
      play(cal,shape,5000,extra);
      const flow=cal.session().episodes.map(ep=>ep.pressLatencyMs);
      const rows=streamOf(60,5000,shape,extra);
      const all=measure(rows).episodes.map(ep=>ep.pressLatencyMs);
      const good=measure(rows.filter(r=>r.quality>=.4)).episodes.map(ep=>ep.pressLatencyMs);
      out({flow,all,good});
    """)
    assert len(result["flow"]) == 4
    assert result["all"] != result["good"], "la sonde voit bien une différence"
    assert result["flow"] == pytest.approx(result["all"], abs=1e-6)


def test_a_stage_where_the_detector_never_pressed_says_so_and_invents_no_press(tmp_path):
    """Pincement secondaire franc, mais le rapport 3D veto chaque appui : des
    seuils se dérivent, et le détecteur n'a rien tranché. L'étape est mesurée
    **avec un avertissement nommé**, à l'écran et au rapport ; aucun
    `pinch_press` n'est inventé dans la séance."""

    result = run_flow(tmp_path, """
      const cal=flowOf({stageTimeoutMs:8000,pinchRepeats:4},'pinch_secondary');
      const pinches=[300,1000,1700,2400].map(at=>({at,closeMs:80,holdMs:100,openMs:90,closed:.1}));
      const shape=shapeOf(pinches,.8);
      play(cal,shape,4000,t=>({primaryRatio:.9,secondaryRatio:shape(t),primaryConfidence:0,
        secondaryConfidence:1,secondaryWorldRatio:.9}));
      const session=cal.session();
      const note=text(flowRoot(),C.DOM.flowNoteClass)[0];
      out({episodes:session.episodes.map(ep=>[ep.channel,ep.pressLatencyMs]),
        /* Les événements de **pincement** : la séance porte aussi les
           décisions de revue (Slice 07 adaptative), qui ne sont pas des
           appuis. */
        kinds:session.samples.map(s=>s.event.kind).filter(k=>/^pinch_/.test(k)),note,
        verdict:verdictLog('pinch_secondary')[0],codes:C.EPISODE_WARNINGS,
        row:reportOf(cal,'Pincement pouce-majeur')});
    """)
    assert result["codes"] == ["barehands_episode_press_never_detected",
                               "barehands_episode_press_out_of_reach"]
    assert result["episodes"] == [["secondary", None]] * 4
    assert result["kinds"] == [], "un appui manqué ne s'invente pas un instant"
    assert result["verdict"]["ok"] is True
    assert result["verdict"]["warnings"] == ["barehands_episode_press_never_detected"]
    assert result["verdict"]["missedPress"] == 4
    assert "aucun appui" in result["note"]
    assert result["row"]["status"] == "jf-ok"
    assert result["row"]["detail"] == "mesuré (4 épisode(s)) — aucun appui n’a été détecté pendant ces pincements"


def test_a_timid_pinch_is_told_to_pinch_harder_and_ends_as_not_separable(tmp_path):
    """Repos à 0,50, « pincements » jusqu'à 0,42 : 0,08 paume, plus que le
    tremblement, moins que `separationMinPalms`. L'étape ne s'arme pas (ni sur
    une profondeur de moitié), elle dit **quoi faire** — « Pincez plus
    franchement » avec le temps qui reste —, et au bout de l'échéance elle se
    solde sur le motif qui dit ce qui manque : inséparable, pas une attente
    sans fin."""

    result = run_flow(tmp_path, """
      const cal=flowOf({stageTimeoutMs:5000,pinchRepeats:4},'pinch_primary');
      const pinches=Array.from({length:12},(_,i)=>({at:300+i*600,closeMs:120,holdMs:100,openMs:150,closed:.42}));
      const shape=shapeOf(pinches,.50);
      play(cal,shape,2500);
      const midPhase=cal.phase();
      const midNote=text(flowRoot(),C.DOM.flowNoteClass)[0];
      const done=play(cal,(t,origin)=>shape(t+2500),6000);
      out({midPhase,midNote,done,verdict:verdictLog('pinch_primary')[0],
        row:reportOf(cal,'Pincement pouce-index')});
    """)
    assert result["midPhase"] == "armed", "0,08 paume n'arme pas l'étape"
    assert result["midNote"].startswith("Pincez plus franchement")
    assert "s’arrêtera dans" in result["midNote"]
    assert result["done"] is True
    assert result["verdict"]["armed"] is False
    assert result["row"]["status"] == "jf-failed"
    assert "ne se distinguent pas" in result["row"]["detail"]


def test_opening_a_hand_held_closed_through_the_reading_does_not_arm(tmp_path):
    """Pincement tenu pendant la lecture, puis main rouverte et gardée ouverte :
    aucun pincement n'a été fait. L'étape reste armée, sans l'invite du
    pincement timide (une main qui s'ouvre franchement n'est pas timide). Le
    « sommet » en cours après une montée n'est pas un sommet confirmé."""

    result = run_flow(tmp_path, """
      const cal=flowOf({stageTimeoutMs:5000,pinchRepeats:4},'pinch_primary');
      play(cal,t=>t<500?.1:t<700?.1+.65*(t-500)/200:.75,4000);
      out({phase:cal.phase(),note:text(flowRoot(),C.DOM.flowNoteClass)[0]});
    """)
    assert result["phase"] == "armed"
    assert result["note"].startswith("À vous")


def test_the_lookback_only_keeps_the_recent_past(tmp_path):
    """Main fermée à l'ouverture de l'attente, rouverte, posée deux secondes,
    puis quatre pincements. Les images d'avant l'armement amorcent le flux,
    mais **seulement** les `pinchLookbackMs` récentes : le pincement tenu du
    début, tronqué, n'y entre pas et ne se refuse pas au journal."""

    result = run_flow(tmp_path, """
      const cal=flowOf({stageTimeoutMs:8000,pinchRepeats:4},'pinch_primary');
      const pinches=[2600,3300,4000,4700].map(at=>({at,closeMs:80,holdMs:100,openMs:90,closed:.1}));
      play(cal,t=>t<400?.1:t<600?.1+.7*(t-400)/200:shapeOf(pinches,.8)(t),6000);
      out({logged:episodesLog(),n:cal.session().episodes.length});
    """)
    assert result["n"] == 4
    assert result["logged"][0]["rejected"] == {}


def test_warnings_name_what_happened_and_only_that(tmp_path):
    """Un appui manqué sur quatre n'est pas « aucun appui détecté » ; un geste
    sur quatre qui n'atteint pas l'appui dérivé l'est pour
    `PRESS_OUT_OF_REACH` (moins de `pressReachMin`, 90 %)."""

    result = run_flow(tmp_path, """
      const cal=flowOf({stageTimeoutMs:8000,pinchRepeats:4},'pinch_primary');
      const pinches=[300,1000,1700,2400].map((at,i)=>({at,closeMs:80,holdMs:100,openMs:90,closed:i===3?.45:.1}));
      play(cal,shapeOf(pinches,.8),4000,t=>t<700?{primaryConfidence:0}:{});
      const verdict=verdictLog('pinch_primary')[0];
      out({verdict,episodes:cal.session().episodes.map(ep=>ep.pressLatencyMs===null),
        row:reportOf(cal,'Pincement pouce-index')});
    """)
    verdict = result["verdict"]
    assert result["episodes"][0] is True and result["episodes"][1] is False
    assert verdict["ok"] is True
    assert verdict["pressReach"] == pytest.approx(0.75)
    assert verdict["warnings"] == ["barehands_episode_press_out_of_reach"]
    assert result["row"]["detail"].endswith("une partie de ces pincements n’atteint pas le seuil d’appui dérivé")


def test_a_press_a_hair_above_the_closed_level_is_refused(tmp_path):
    """Minima de 0,36 à 0,40, ouvert à 0,75 : le relâchement est ramené sous la
    posture de réveil, l'appui abaissé pour l'hystérésis tomberait à 0,39 —
    à un cheveu du fermé (0,38), un pincement sur cinq ne l'atteindrait
    jamais. Refusé (`OUT_OF_BAND`), pas « mesuré » en silence. Et le quantile
    du parcours refuse un `q` hors de [0,1] au lieu de le rabattre."""

    result = run_node(tmp_path, """
      const eps=mins=>mins.map(m=>({complete:true,minRatio:m,baselineBefore:.75,baselineAfter:.75}));
      const d=mins=>K.deriveEpisodeHysteresis(eps(mins),o,{releaseCeiling:D.wakeGapMin});
      out({hair:d([.36,.37,.38,.39,.40]),wide:d([.30,.32,.34,.36,.38]),
        reach:d([.1,.1,.1,.1,.40]),
        q:[refused(()=>K.quantile([1,2,3],1.5)),refused(()=>K.quantile([1,2,3],-.1)),K.quantile([1,2,3],1)]});
    """)
    assert result["hair"]["ok"] is False and result["hair"]["reason"] == "barehands_stage_out_of_band"
    wide = result["wide"]
    assert wide["ok"] is True and wide["pressRatio"] >= wide["closed"] + 0.025
    assert result["reach"]["ok"] is True and result["reach"]["pressReach"] == pytest.approx(0.8)
    assert result["q"] == ["RangeError", "RangeError", 3]


def test_the_engine_key_survives_the_calibration_keep_list_into_the_replay(tmp_path):
    """La clé du moteur de pincement (`pinchHandedness`, que la couture du vrai
    contrôleur publie — voir le test par `createController`) traverse la
    sélection `KEEP` du parcours jusqu'au rejeu. Ici elle vaut `left` sous un
    jeton `right`, pour se distinguer du repli `unknown`."""

    result = run_flow(tmp_path, """
      const asked=[];
      const cal=calOf({options:{stageTimeoutMs:8000,pinchRepeats:4},
        pinchChannel:(channel,key)=>{asked.push(key);return B.createPinchChannel(channel,{})}});
      cal.start();
      while(cal.stepId()!=='pinch_primary')skipStep(cal);
      readOn(cal);
      const pinches=[300,1000,1700,2400].map(at=>({at,closeMs:80,holdMs:100,openMs:90,closed:.1}));
      play(cal,shapeOf(pinches,.8),4000,()=>({pinchHandedness:'left'}));
      out({asked:[...new Set(asked)],phase:cal.phase()});
    """)
    assert result["phase"] == "review"
    assert result["asked"] == ["left"]


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
        if(cal.phase()==='review')break;
      }
      const session=cal.session();
      const step=[cal.stepId(),cal.phase()];
      const validated=session.samples.map(s=>{try{R.validateSessionSample(s);return true}catch(e){return e.code}});
      const measurementsOk=(()=>{try{C.createMeasurementSet(session.measurements);return true}catch(e){return e.code}})();
      escapeTwice();
      out({step,episodes:session.episodes,measurements:session.measurements,history:session.samples,
        validated,measurementsOk,historyOn:session.history,
        logged:logs.filter(l=>l[1]==='[barehands] calibration.episodes').map(l=>l[2]),
        stageLog:logs.filter(l=>String(l[1]).includes('pinch_primary')).map(l=>l[2]),
        after:cal.session()});
    """, calibration_driver=True)
    assert result["step"] == ["pinch_primary", "review"], "l'étape primaire s'est soldée"
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
    # Slice 07 adaptative : la séance porte aussi les décisions de revue (les
    # deux étapes passées pour arriver ici), sur la même horloge ; le premier
    # **pincement** est celui du premier épisode.
    first = next(s for s in result["history"] if s["event"]["kind"] == "pinch_press")
    assert first["ref"].startswith("se-") and first["event"]["ref"] == "ep-1"
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

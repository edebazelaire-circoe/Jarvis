"""Banc d'essai Bare Hands « Tester » (tâche adaptative, Slice 08), par node.

Ce qui est épinglé ici (contrat lisible : § 17, décisions 60 à 64) :

- **le plan** : la même graine rejoue la même disposition ; deux graines
  tirent des dispositions équivalentes (même multi-ensemble de classes, aucun
  repli au-dessus de la fenêtre minimale), des tirages indépendants par
  exercice, des coordonnées arrondies ; sous la fenêtre minimale, refus codé
  avec une phrase d'utilisateur ;
- **le déroulé** passe par le **vrai** moteur, joué par l'**utilisateur
  réaliste** de référence (`tests/fixtures/barehands_benchmark_driver.cjs` :
  réaction, dépassement, erreur de visée, tremblement, relâchement lent,
  fermetures parasites, fatigue) ; même profil + même graine + même trace →
  même résultat ; chaque métrique est la statistique de ses échantillons ;
- **chaque jugement du déroulé** se prouve par un geste qui le déclenche :
  ratés, mauvaises cibles, trois tentatives, délais dépassés sans clic manqué,
  lâchers trop tôt et tolérance de dépôt, faux appuis primaires (et pas
  secondaires), faux clics, curseurs et cibles non voulus après la grâce,
  reprises, retard, tremblement mesuré une fois posé — insensible au temps de
  réaction ;
- **lecture seule** : dépendance d'écriture refusée, vue écrite refusée, rien
  ne change sur le vrai chemin effectif, et aucune image brute ne survit ;
- **le score** : défauts de profil → sa dimension baisse ; dimension nulle →
  global plafonné à 25 ; déséquilibre puni plus qu'une médiocrité égale ;
  dimension manquante → pas de global ;
- **la comparaison** : même utilisateur, même profil → aucun « amélioré » ni
  « régressé » ; `releaseMs` 150 → 110 → « amélioré » ; ordre par `runAt` ;
  classe, suite ou fenêtre différentes → non comparable ; déterministe.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from test_barehands_lifecycle_js import WORLD  # noqa: E402
from test_barehands_trial_profile_js import RIG  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
DRIVER = ROOT / "tests" / "fixtures" / "barehands_benchmark_driver.cjs"
MODULE = RUNTIME / "control_center_barehands_benchmark.js"
PAGE = RUNTIME / "control_center_barehands.js"
DOC = ROOT / "docs" / "barehands-contracts.md"


def run_node(tmp_path: Path, source: str, name: str = "bench") -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / f"barehands-{name}.cjs"
    script.write_text(
        f"const D=require({json.dumps(str(DRIVER))});\n"
        "const {C,B,K,T,G,BM}=D;const Core=B;\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "const refused=fn=>{try{fn();return null}catch(e){return e.code||e.name||String(e)}};\n"
        "const metricsOf=r=>Object.fromEntries(r.result.exercises.map(e=>[e.kind,e.metrics]));\n"
        "const outcomes=r=>r.log.filter(l=>l[1]==='barehands.benchmark_trial').map(l=>l[2]);\n"
        "const trial=patch=>({trial:patch,source:'trial',trialRef:'tr-1'});\n"
        "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True,
                          encoding="utf-8", timeout=240, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# ------------------------------------------------------------------ le plan


def test_the_same_seed_replays_the_same_layout_and_a_small_window_is_refused(tmp_path):
    result = run_node(tmp_path, """
      const vp={width:1280,height:720};
      const a=BM.layoutPlan(BM.generatePlan(123),vp),b=BM.layoutPlan(BM.generatePlan(123),vp);
      const c=BM.layoutPlan(BM.generatePlan(124),vp);
      const plan=BM.generatePlan(123);
      let small=null;try{BM.layoutPlan(plan,{width:1280,height:699})}catch(e){small={code:e.code,reason:e.reason}}
      out({same:BM.canonicalJson(a)===BM.canonicalJson(b),differ:BM.canonicalJson(a)!==BM.canonicalJson(c),
        valid:BM.canonicalJson(C.createBenchmarkPlan(plan))===BM.canonicalJson(plan),
        kinds:plan.exercises.map(e=>e.kind),planClass:plan.planClass,
        badSeed:refused(()=>BM.generatePlan(-1)),hugeSeed:refused(()=>BM.generatePlan(2**32)),
        small,check:BM.viewportCheck({width:1024,height:768}),ok:BM.viewportCheck({width:1280,height:700}),
        runnerSmall:refused(()=>BM.createBenchmarkRunner({contracts:C,core:B,target:T,geometry:G,calibration:K,
          profile:BM.profileView({composition:B.composeEffective({contracts:C}),source:'defaults'}),plan,
          viewport:{width:1200,height:800},pinchChannel:()=>null})),
        otherClass:refused(()=>C.createBenchmarkPlan({...plan,planClass:'bh-bench-9'}))});
    """)
    assert result["same"] is True and result["differ"] is True and result["valid"] is True
    assert sorted(result["kinds"]) == sorted(["target_acquisition", "no_click_tracking", "nearby_targets",
                                              "drag_drop", "moving_target", "chained"])
    assert result["planClass"] == "bh-bench-1"
    assert result["badSeed"] == result["hugeSeed"] == "barehands_benchmark_seed_invalid"
    assert result["small"]["code"] == "barehands_benchmark_viewport_too_small"
    assert "1280 × 700" in result["small"]["reason"] and "Agrandissez" in result["small"]["reason"]
    assert result["check"]["ok"] is False and "1024 × 768" in result["check"]["reason"]
    assert result["ok"] == {"ok": True, "code": None, "reason": None}
    assert result["runnerSmall"] == "barehands_benchmark_viewport_too_small"
    assert result["otherClass"] == "barehands_benchmark_invalid"


def test_two_seeds_draw_equivalent_but_different_layouts_without_any_fallback(tmp_path):
    """La règle d'équivalence : même multi-ensemble de classes pour toute
    graine, aucun repli à la fenêtre minimale comme en grand, distances dans
    ±8 %, leurres et étoiles espacés, cible attendue et ordre tirés, tirages
    indépendants d'un exercice à l'autre, coordonnées au centième."""

    result = run_node(tmp_path, """
      const rows={};
      for(const vp of [{width:1280,height:700},{width:1920,height:1080}]){
        const sig=new Set(),positions=new Set(),expectedIdx=new Set(),orders=new Set();
        let fallbacks=0,distOut=0,crowded=0,samePermutation=0,unrounded=0,outside=0;
        for(let s=1;s<=200;s+=1){
          const L=BM.layoutPlan(BM.generatePlan((s*2654435761)>>>0),vp),f=L.field;
          fallbacks+=L.fallbacks;
          const cls={};
          const ta=L.exercises.find(e=>e.kind==='target_acquisition'),nb=L.exercises.find(e=>e.kind==='nearby_targets');
          for(const e of L.exercises){
            cls[e.kind]=e.trials.map(t=>e.kind==='target_acquisition'?`${t.sizeClass}/${t.distanceClass}`
              :e.kind==='nearby_targets'?t.gapPx:e.kind==='moving_target'?t.speedPxPerS
              :e.kind==='drag_drop'?BM.BANDS.drag_drop.offsetsPx.find(o=>Math.abs(t.offsetPx/o-1)<=.0800001)
              :e.kind==='no_click_tracking'?t.mode:'c').sort().join(',');
            for(const t of e.trials)for(const st of (t.stars||[])){
              positions.add(`${st.x}|${st.y}`);
              if(Math.abs(Math.round(st.x*100)-st.x*100)>1e-6||Math.abs(Math.round(st.y*100)-st.y*100)>1e-6)unrounded+=1;
              if(st.x<f.x0+st.size/2-1e-6||st.x>f.x1-st.size/2+1e-6||st.y<f.y0+st.size/2-1e-6||st.y>f.y1-st.size/2+1e-6)outside+=1;
            }
          }
          for(const t of ta.trials){
            const d=t.distancePx/BM.BANDS.target_acquisition.distancesPx[t.distanceClass]-1;
            if(Math.abs(d)>.0801)distOut+=1;
            const [target,...decoys]=t.stars;
            for(const q of decoys)if(Math.hypot(q.x-target.x,q.y-target.y)<120||Math.hypot(q.x-t.from.x,q.y-t.from.y)<120)crowded+=1;
          }
          for(const t of L.exercises.find(e=>e.kind==='no_click_tracking').trials)
            for(let i=0;i<t.stars.length;i+=1)for(let j=i+1;j<t.stars.length;j+=1)
              if(Math.hypot(t.stars[i].x-t.stars[j].x,t.stars[i].y-t.stars[j].y)<140)crowded+=1;
          for(const t of nb.trials)expectedIdx.add(t.stars.findIndex(x=>x.expected));
          const order=ta.trials.map(t=>`${t.sizeClass}/${t.distanceClass}`).join(',');
          orders.add(order);
          const perm=list=>list.map(x=>BM.BANDS.target_acquisition.schedule.findIndex(y=>`${y[0]}/${y[1]}`===x));
          const nperm=nb.trials.map(t=>[0,1,2,0,1,2].indexOf(BM.BANDS.nearby_targets.gapsPx.indexOf(t.gapPx)));
          if(JSON.stringify(perm(order.split(',')).map(i=>i%3))===JSON.stringify(nperm))samePermutation+=1;
          sig.add(JSON.stringify(cls));
        }
        rows[`${vp.width}x${vp.height}`]={distinct:sig.size,sample:JSON.parse([...sig][0]),fallbacks,distOut,crowded,
          positions:positions.size,expected:[...expectedIdx].sort(),orders:orders.size,samePermutation,unrounded,outside};
      }
      out(rows);
    """)
    for size, row in result.items():
        assert row["distinct"] == 1, (size, "une graine a changé la difficulté, pas seulement la disposition")
        assert row["fallbacks"] == 0, (size, "un repli a raccourci une distance ou retiré un leurre")
        assert row["distOut"] == 0 and row["crowded"] == 0 and row["outside"] == 0 and row["unrounded"] == 0, (size, row)
        assert row["positions"] > 3000
        assert row["expected"] == [0, 1, 2], "la cible attendue d'un groupe doit être tirée, pas fixe"
        assert row["orders"] > 100, "l'ordre des classes doit être tiré par la graine"
        assert row["samePermutation"] < 20, "deux exercices ne doivent pas partager le même tirage"
        assert row["sample"]["target_acquisition"] == "0/1,0/2,1/0,1/1,2/0,2/2"
        assert row["sample"]["no_click_tracking"] == "aim,aim,natural,natural"


# ------------------------------------------------------------------ le déroulé


def test_same_profile_seed_and_trace_give_the_same_self_consistent_result(tmp_path):
    result = run_node(tmp_path, """
      const a=await D.runSynthetic({seed:77,performerSeed:4,user:'typical'});
      const b=await D.runSynthetic({seed:77,performerSeed:4,user:'typical'});
      const replayed=await D.runSynthetic({seed:77,replay:a.trace});
      const other=await D.runSynthetic({seed:78,performerSeed:4,user:'typical'});
      const consistent=a.result.exercises.every(e=>Object.keys(e.metrics).every(m=>e.metrics[m]===BM.statOf(m,e.samples[m])));
      out({same:BM.canonicalJson(a.result)===BM.canonicalJson(b.result),
        replay:BM.canonicalJson(a.result)===BM.canonicalJson(replayed.result),
        differs:BM.canonicalJson(a.result)!==BM.canonicalJson(other.result),
        comparable:C.benchmarkComparable(a.result,other.result),consistent,
        simulatedMs:a.simulatedMs,frames:a.frames,measured:a.measured,result:a.result,
        events:[...new Set(a.log.map(l=>l[1]))]});
    """)
    assert result["same"] is True and result["replay"] is True
    assert result["differs"] is True and result["comparable"] is True
    assert result["consistent"] is True, "chaque métrique doit être la statistique de ses échantillons"
    assert result["simulatedMs"] <= 120000, "un banc tient en deux minutes"
    assert result["measured"] >= result["frames"]
    r = result["result"]
    assert r["viewport"] == {"width": 1280, "height": 720, "scale": 4}
    assert len(r["profileFingerprint"]) == 16
    for exercise in r["exercises"]:
        assert set(exercise["samples"]) == set(exercise["metrics"])
        assert all(len(v) <= 64 for v in exercise["samples"].values())
    assert {"barehands.benchmark_started", "barehands.benchmark_trial", "barehands.benchmark_exercise",
            "barehands.benchmark_done"} <= set(result["events"])


def test_the_runner_reads_the_real_engine_and_refuses_to_run_without_it(tmp_path):
    result = run_node(tmp_path, """
      const comp=B.composeEffective({contracts:C,settings:C.SETTINGS_DEFAULTS,profile:null,trial:{},session:{},viewportWidth:1280});
      const base={contracts:C,core:B,target:T,geometry:G,calibration:K,profile:BM.profileView({composition:comp,source:'defaults'}),
        plan:BM.generatePlan(1),viewport:{width:1280,height:720},pinchChannel:(c,h)=>B.createPinchChannel(c,{})};
      const without=(k,v)=>refused(()=>BM.createBenchmarkRunner({...base,[k]:v}));
      const noCore=name=>{const core={...B};delete core[name];return without('core',core)};
      const r=BM.createBenchmarkRunner(base);
      out({ok:!!r,noResolver:noCore('createTargetResolver'),noObserver:noCore('createSelectionObserver'),
        noEngine:noCore('createInteractionEngine'),noFrame:noCore('createPracticeFrame'),noHand:noCore('resolverHandOf'),
        noEpisodes:without('calibration',{options:K.options}),noChannel:without('pinchChannel',null),
        early:refused(()=>r.result({runAt:1})),
        twice:(()=>{r.start(0);return refused(()=>r.start(1))})(),
        noClock:refused(()=>r.frame({hands:[]}))});
    """)
    assert result["ok"] is True
    for key in ("noResolver", "noObserver", "noEngine", "noFrame", "noHand", "noEpisodes", "noChannel"):
        assert result[key] == "barehands_benchmark_invalid", key
    assert result["early"] == "barehands_benchmark_incomplete"
    assert result["twice"] == "barehands_benchmark_already_started"
    assert result["noClock"] == "barehands_benchmark_invalid"
    page = PAGE.read_text(encoding="utf-8")
    body = page.split("function resolveTargets(tokens){", 1)[1].split("const at={x:token.x", 1)[0]
    assert "Core.resolverHandOf(contact,token,assistance)" in body
    assert "token.pointing!==false" not in body


def test_selection_judging_flags_misses_wrong_targets_attempts_and_timeouts(tmp_path):
    """Chaque jugement de sélection, déclenché par un geste réaliste :

    - une personne maladroite sans assistance rate (clics dans le vide) et
      reprend la présélection ;
    - une visée à ±40 px sans assistance épuise ses trois tentatives
      (`failed`) avant l'échéance ;
    - une main qui ne pince jamais dépasse chaque échéance : des délais, pas
      des clics manqués, et aucune acquisition (elle n'est jamais censurée) ;
    - des voisines à 8 px avec une grande erreur de visée prennent la
      mauvaise étoile."""

    result = run_node(tmp_path, """
      const clumsy=await D.runSynthetic({seed:4242,performerSeed:3,user:'clumsy',...trial({assistance:0})});
      const wild=await D.runSynthetic({seed:4242,performerSeed:3,user:'typical',userOverrides:{aimErrorPx:40},...trial({assistance:0})});
      const idle=await D.runSynthetic({seed:4242,performerSeed:3,user:'typical',userOverrides:{strayPerMin:0},performer:{pinch:false}});
      let wrong=0;
      for(let s=0;s<3;s+=1){const r=await D.runSynthetic({seed:9000+s,performerSeed:s+1,user:'typical',userOverrides:{aimErrorPx:14}});
        wrong+=metricsOf(r).nearby_targets.wrong_target_count}
      const typical=await D.runSynthetic({seed:4242,performerSeed:3,user:'typical'});
      out({clumsy:metricsOf(clumsy),wild:metricsOf(wild),wildOutcomes:outcomes(wild).map(o=>o.outcome),
        idle:metricsOf(idle),idleMs:outcomes(idle).filter(o=>o.kind==='target_acquisition').map(o=>o.ms),wrong,
        typical:metricsOf(typical)});
    """)
    clumsy = result["clumsy"]
    assert clumsy["target_acquisition"]["missed_click_count"] >= 1
    assert clumsy["target_acquisition"]["reacquisition_count"] >= 1
    assert "failed" in result["wildOutcomes"], "trois tentatives ratées doivent solder l'essai avant l'échéance"
    idle = result["idle"]
    for kind in ("target_acquisition", "nearby_targets", "moving_target"):
        assert idle[kind]["timeout_count"] == {"target_acquisition": 6, "nearby_targets": 6, "moving_target": 4}[kind]
        assert idle[kind]["acquisition_ms"] is None, "une acquisition jamais faite n'est pas une durée"
    assert idle["target_acquisition"]["missed_click_count"] == 0, "un délai dépassé n'est pas un clic manqué"
    assert all(3990 <= ms <= 4040 for ms in result["idleMs"]), result["idleMs"]
    assert result["wrong"] >= 1, "des voisines serrées doivent produire des mauvaises cibles"
    typical = result["typical"]
    assert typical["target_acquisition"]["reacquisition_count"] <= 6
    assert 1200 <= typical["target_acquisition"]["acquisition_ms"] <= 2000


def test_drag_judging_counts_early_drops_and_holds_the_drop_tolerance(tmp_path):
    result = run_node(tmp_path, """
      const good=await D.runSynthetic({seed:31,performerSeed:2,user:'typical'});
      const short=await D.runSynthetic({seed:31,performerSeed:2,user:'typical',performer:{dropShort:.5}});
      const near=await D.runSynthetic({seed:31,performerSeed:2,user:'typical',performer:{dropShort:.8}});
      out({good:metricsOf(good),short:metricsOf(short),near:metricsOf(near),
        tolerance:K.options().dropTolerancePx});
    """)
    good, short, near = result["good"], result["short"], result["near"]
    assert good["drag_drop"]["drag_success_rate"] == 1 and good["drag_drop"]["premature_drop_count"] == 0
    assert good["drag_drop"]["placement_error_px"] < result["tolerance"]
    # À mi-chemin, chaque lâcher est trop tôt, dans le glisser-déposer comme dans l'enchaîné.
    assert short["drag_drop"]["premature_drop_count"] >= 3 and short["drag_drop"]["drag_success_rate"] < 1
    assert short["chained"]["premature_drop_count"] >= 1
    # À 80 % du trajet (60 à 100 px de la destination) : chaque premier lâcher
    # est hors tolérance, donc trop tôt ; la reprise, elle, dépose.
    assert near["drag_drop"]["premature_drop_count"] == 5
    assert near["drag_drop"]["drag_success_rate"] == 1
    assert near["drag_drop"]["placement_error_px"] < result["tolerance"]


def test_negative_examples_count_what_the_engine_did_after_the_grace(tmp_path):
    """Sans clic : l'utilisateur réaliste qui passe de la visée au mouvement
    ordinaire ne compte **aucun** curseur ni aucune cible (grâce + remise à
    zéro par essai) ; une posture de visée gardée en mouvement ordinaire
    compte curseurs et cibles ; des fermetures parasites comptent des appuis
    **primaires** (pas secondaires) et des faux clics sur les étoiles."""

    result = run_node(tmp_path, """
      const clean=[];
      for(let s=0;s<4;s+=1){const r=await D.runSynthetic({seed:500+s,performerSeed:s+1,user:'typical',userOverrides:{strayPerMin:0}});
        clean.push(metricsOf(r).no_click_tracking)}
      const aiming=await D.runSynthetic({seed:500,performerSeed:1,user:'typical',userOverrides:{strayPerMin:0},performer:{naturalPosture:'aim'}});
      const strays=await D.runSynthetic({seed:500,performerSeed:1,user:'typical',userOverrides:{strayPerMin:30,strayGap:.12}});
      out({clean,aiming:metricsOf(aiming).no_click_tracking,strays:metricsOf(strays).no_click_tracking});
    """)
    for row in result["clean"]:
        assert row["unintended_pointer_rate"] == 0 and row["unintended_target_rate"] == 0, row
        assert row["false_press_rate"] == 0 and row["false_click_count"] == 0, row
    aiming = result["aiming"]
    assert aiming["unintended_pointer_rate"] > 0 and aiming["unintended_target_rate"] > 0
    strays = result["strays"]
    assert strays["false_press_rate"] > 0 and strays["false_secondary_press_rate"] == 0
    assert strays["false_click_count"] >= 1


def test_pointer_stability_is_tremor_once_posed_not_reaction_time(tmp_path):
    """Le tremblement se mesure une fois le jeton posé, en passe-haut : le
    temps de réaction seul (0 contre 300 ms) ne le bouge presque pas, un
    tremblement de 4 px le multiplie. Et la fonction pure : une arrivée suivie
    d'un jeton posé ne compte que la partie posée ; un jeton qui ne se pose
    jamais ne rend rien."""

    result = run_node(tmp_path, """
      const jitter=async o=>{const r=await D.runSynthetic({seed:600,performerSeed:2,user:'typical',
        userOverrides:{strayPerMin:0,...o}});return metricsOf(r).no_click_tracking.pointer_jitter_px};
      const fast=await jitter({reactionMs:[0,0]}),slow=await jitter({reactionMs:[300,300]}),shaky=await jitter({tremorPx:4});
      let seed=3;const rnd=()=>{seed=(seed*1103515245+12345)%2147483648;return seed/2147483648-.5};
      const arrive=[];for(let i=0;i<60;i+=1){const t=i*33;const x=i<20?i*30:600+rnd()*2;arrive.push({t,x,y:100+(i<20?0:rnd()*2)})}
      const moving=Array.from({length:60},(_,i)=>({t:i*33,x:i*20,y:0}));
      const settledOnly=BM.settledJitter(arrive),settledPart=BM.settledJitter(arrive.slice(20));
      out({fast,slow,shaky,settledOnly,settledPart,moving:BM.settledJitter(moving),short:BM.settledJitter(arrive.slice(0,4))});
    """)
    assert abs(result["fast"] - result["slow"]) < 0.3, result
    assert result["shaky"] > result["slow"] + 1, result
    assert result["settledOnly"] is not None and result["settledOnly"] < 3, "l'arrivée ne doit pas compter"
    assert result["moving"] is None and result["short"] is None


def test_pointer_lag_rises_with_a_slower_filter(tmp_path):
    result = run_node(tmp_path, """
      const lag=async o=>metricsOf(await D.runSynthetic({seed:700,performerSeed:1,user:'typical',...o})).moving_target.pointer_lag_ms;
      out({base:await lag({}),slow:await lag(trial({minCutoffHz:.3,betaCutoff:0}))});
    """)
    assert 5 <= result["base"] <= 60
    assert result["slow"] > result["base"] * 2


# ------------------------------------------------------------------ lecture seule


def test_the_benchmark_refuses_write_capable_dependencies_and_views_refuse_writes(tmp_path):
    result = run_node(tmp_path, """
      const comp=B.composeEffective({contracts:C,settings:C.SETTINGS_DEFAULTS,profile:null,trial:{},session:{},viewportWidth:1280});
      const view=BM.profileView({composition:comp,source:'defaults'});
      const base={contracts:C,core:B,target:T,geometry:G,calibration:K,profile:view,
        plan:BM.generatePlan(1),viewport:{width:1280,height:720},pinchChannel:(c,h)=>B.createPinchChannel(c,{})};
      const extra=k=>refused(()=>BM.createBenchmarkRunner({...base,[k]:()=>{}}));
      const doors=BM.readOnly({apply(){},nested:{save(){},value:1}});
      out({save:extra('save'),trials:extra('trials'),settings:extra('settings'),persistProfile:extra('persistProfile'),
        apply:extra('apply'),controller:extra('controller'),
        set:refused(()=>{view.targets.targetSwitchPx=0}),top:refused(()=>{view.source='saved'}),
        del:refused(()=>{delete view.assistance}),define:refused(()=>Object.defineProperty(view,'x',{value:1})),
        proto:refused(()=>Object.setPrototypeOf(view.targets,{})),
        frozen:Object.isFrozen(view)&&Object.isFrozen(view.targets),
        doors:[typeof doors.apply,typeof doors.nested.save,doors.nested.value],
        intact:view.targets.targetSwitchPx===comp.interaction.targetSwitchPx,
        trialWithoutRef:refused(()=>BM.profileView({composition:comp,source:'trial'})),
        refWithoutTrial:refused(()=>BM.profileView({composition:comp,source:'saved',trialRef:'tr-1'}))});
    """)
    code = "barehands_benchmark_read_only"
    for key in ("save", "trials", "settings", "persistProfile", "apply", "controller", "set", "top", "del",
                "define", "proto"):
        assert result[key] == code, key
    assert result["frozen"] is True
    assert result["doors"] == ["undefined", "undefined", 1], "une vue ne transporte aucune porte"
    assert result["intact"] is True
    assert result["trialWithoutRef"] == result["refWithoutTrial"] == "barehands_benchmark_profile_invalid"


def test_a_benchmark_on_the_live_effective_path_mutates_nothing_and_keeps_no_raw_frame(tmp_path):
    result = run_node(tmp_path, WORLD + RIG + """
      const R=await rig();
      const receipt=R.T.apply({releaseMs:120});
      const calls={configure:0};
      const configure=R.controller.configure.bind(R.controller);
      R.controller.configure=p=>{calls.configure+=1;return configure(p)};
      const snap=()=>JSON.stringify({settings:R.state.settings,profile:R.state.profile,status:R.T.status(),
        delta:R.T.delta(),history:R.T.history(),effective:R.path.effective().layers,session:R.path.session(),
        engine:R.controller.options(),persisted:R.persisted});
      const before=snap();
      const st=R.T.status();
      const run=await D.runSynthetic({seed:5,user:'typical',composition:R.path.effective(),source:'trial',trialRef:st.trialId});
      out({receipt:receipt.ok,same:before===snap(),calls,persisted:R.persisted.length,
        source:run.result.profileSource,trialRef:run.result.trialRef,active:R.T.status().active,retained:run.retained});
    """)
    assert result["receipt"] is True and result["active"] is True
    assert result["same"] is True, "le banc a changé l'état des réglages, du profil ou de l'essai"
    assert result["calls"]["configure"] == 0 and result["persisted"] == 0
    assert result["source"] == "trial" and result["trialRef"] == "tr-1"
    assert result["retained"] == 0, "aucune image brute ne survit au banc"


# ------------------------------------------------------------------ le score


RESULT = """
const PERFECT={acquisition_ms:900,missed_click_count:0,wrong_target_count:0,reacquisition_count:0,press_latency_ms:30,
  false_click_count:0,false_press_rate:0,false_secondary_press_rate:0,unintended_target_rate:0,unintended_pointer_rate:0,
  pointer_jitter_px:.5,target_ambiguity:.3,drag_success_rate:1,premature_drop_count:0,placement_error_px:8,
  release_latency_ms:60,pointer_lag_ms:20,transition_ms:900,timeout_count:0};
const exercisesOf=metrics=>BM.SUITE.map((e,i)=>({ref:`ex-${i+1}`,kind:e.kind,trials:e.trials,
  metrics:Object.fromEntries(C.BENCHMARK_EXERCISE_METRICS[e.kind].map(m=>[m,metrics[m]===undefined?PERFECT[m]:metrics[m]]))}));
const result=(metrics,o)=>C.createBenchmarkResult({ref:'bm-1',seed:1,runAt:1,profileSource:'saved',
  viewport:{width:1280,height:720,scale:4},exercises:exercisesOf(metrics||{}),...(o||{})});
"""


def test_a_catastrophic_dimension_caps_the_global_and_imbalance_costs_more_than_evenness(tmp_path):
    result = run_node(tmp_path, RESULT + """
      const s=m=>BM.scoreResult(result(m));
      const perfect=s({});
      const falsePos=s({false_press_rate:40,false_secondary_press_rate:40,false_click_count:4,
        unintended_target_rate:40,unintended_pointer_rate:40});
      const release=s({release_latency_ms:2000,premature_drop_count:3});
      /* Deux systèmes aux dimensions de même moyenne arithmétique : l'un
         égal partout, l'autre très bon sauf une dimension faible. */
      const even=s({pointer_jitter_px:3.5,transition_ms:2500});        // deux dimensions à 50
      const uneven=s({pointer_jitter_px:6,transition_ms:1200});        // 0 et 100
      /* Dans une dimension : latences parfaites, lâchers trop tôt une fois
         sur deux. La moyenne arithmétique des six scores rendrait 66,7. */
      const lopsided=s({release_latency_ms:80,premature_drop_count:3});
      const missing=BM.scoreResult({...result({}),exercises:result({}).exercises.map(e=>e.kind==='no_click_tracking'
        ?{...e,metrics:{...e.metrics,pointer_jitter_px:null}}:e)});
      out({perfect:perfect.global,falsePos:falsePos.global,fp:falsePos.dimensions.false_positive_resistance.score,
        release:release.global,even:even.global,uneven:uneven.global,
        dims:{even:[even.dimensions.pointer_stability.score,even.dimensions.transitions.score],
          uneven:[uneven.dimensions.pointer_stability.score,uneven.dimensions.transitions.score]},
        lopsided:lopsided.dimensions.release_reliability.score,
        missing:missing.global,keys:Object.keys(perfect),metric:perfect.dimensions.acquisition.metrics[0]});
    """)
    assert result["perfect"]["score"] == 100
    assert result["fp"] == 0
    fp = result["falsePos"]
    # Sept dimensions parfaites, une nulle : la moyenne géométrique seule
    # rendrait ~56, l'arithmétique 87,5 ; le plafond garde 25.
    assert fp["weakest"] == "false_positive_resistance" and fp["capped"] is True and fp["score"] <= 25
    assert result["release"]["weakest"] == "release_reliability" and result["release"]["score"] <= 25
    assert result["dims"]["even"] == [50, 50] and result["dims"]["uneven"] == [0, 100]
    assert result["uneven"]["score"] < result["even"]["score"], "le déséquilibre doit coûter plus que l'égalité"
    assert result["uneven"]["capped"] is True
    assert result["lopsided"] < 30, "une métrique nulle doit peser dans sa dimension, pas se diluer"
    # Une dimension manquante : pas de global, et elle est nommée.
    assert result["missing"]["score"] is None and result["missing"]["unmeasured"] == ["pointer_stability"]
    assert result["metric"]["value"] == 900 and result["metric"]["unit"] == "ms"
    assert "result" in result["keys"] and "subject" in result["keys"]
    assert "skill" not in json.dumps(result).lower()


def test_the_anchors_rank_the_reference_user_and_real_defects_sensibly(tmp_path):
    """Les ancres se jugent sur l'utilisateur de référence : réaliste et bien
    réglé, il obtient au moins 80 partout ; un relâchement lent (250 ms), un
    tremblement de 4 px, une assistance coupée pour une personne maladroite
    font tomber chacun leur dimension sous 75."""

    result = run_node(tmp_path, """
      const dims=async o=>{const s=BM.scoreResult((await D.runSynthetic({seed:4242,performerSeed:3,user:'typical',...o})).result);
        return Object.fromEntries(Object.entries(s.dimensions).map(([k,v])=>[k,v.score]))};
      out({base:await dims({userOverrides:{strayPerMin:0}}),release:await dims(trial({releaseMs:250})),
        tremor:await dims({userOverrides:{tremorPx:4,strayPerMin:0}}),
        clumsy:await dims({user:'clumsy',...trial({assistance:0})})});
    """)
    assert all(score >= 80 for score in result["base"].values()), result["base"]
    assert result["release"]["release_reliability"] < 75
    assert result["tremor"]["pointer_stability"] < 75
    assert result["clumsy"]["selection_accuracy"] < 75


def test_every_metric_score_moves_in_the_expected_direction(tmp_path):
    result = run_node(tmp_path, """
      const rows=[];
      for(const [name,spec] of Object.entries(BM.METRIC_SCORING)){
        const better=C.CALIBRATION_METRIC[name].better;
        const trials=spec.per==='trial'?4:1;
        const at=v=>BM.metricScore(name,spec.per==='trial'?v*trials:v,trials);
        const worse=better==='lower'?spec.bad+Math.abs(spec.bad-spec.good):spec.bad-Math.abs(spec.bad-spec.good)/2;
        rows.push({name,good:at(spec.good),bad:at(spec.bad),beyond:at(worse),mid:at((spec.good+spec.bad)/2),
          dir:better==='lower'?spec.good<spec.bad:spec.good>spec.bad});
      }
      const scored=new Set(Object.keys(BM.METRIC_SCORING));
      out({rows,missing:C.BENCHMARK_DIMENSIONS.flatMap(d=>C.BENCHMARK_DIMENSION_METRICS[d]).filter(m=>!scored.has(m)),
        stat:C.BENCHMARK_DIMENSIONS.flatMap(d=>C.BENCHMARK_DIMENSION_METRICS[d]).filter(m=>!BM.METRIC_STAT[m])});
    """)
    assert result["missing"] == [] and result["stat"] == []
    for row in result["rows"]:
        assert row["dir"] is True and row["good"] == 100 and row["bad"] == 0 and row["beyond"] == 0, row
        assert row["mid"] == 50, row


# ------------------------------------------------------------------ avant / après


def test_same_user_same_profile_never_reads_as_improved_or_regressed(tmp_path):
    result = run_node(tmp_path, """
      const verdicts={};
      for(let i=0;i<5;i+=1){
        const a=(await D.runSynthetic({seed:8000+2*i,performerSeed:2*i+1,user:'typical',runAt:1})).result;
        const b=(await D.runSynthetic({seed:8001+2*i,performerSeed:2*i+2,user:'typical',runAt:2})).result;
        const c=BM.compareResults(a,b);
        for(const [k,v] of Object.entries({...c.dimensions,global:c.global}))(verdicts[k]||(verdicts[k]=[])).push(v.verdict);
      }
      out(verdicts);
    """)
    for name, verdicts in result.items():
        assert "improved" not in verdicts and "regressed" not in verdicts, (name, verdicts)


def test_a_real_release_change_is_detected_in_its_dimension_only(tmp_path):
    result = run_node(tmp_path, """
      const rows=[];
      for(let i=0;i<3;i+=1){
        const before=(await D.runSynthetic({seed:8100+2*i,performerSeed:2*i+1,user:'typical',runAt:10,...trial({releaseMs:150})})).result;
        const after=(await D.runSynthetic({seed:8101+2*i,performerSeed:2*i+2,user:'typical',runAt:20,...trial({releaseMs:110})})).result;
        const c=BM.compareResults(before,after),back=BM.compareResults(after,before),rev=BM.compareResults({...after,runAt:5},before);
        rows.push({release:c.dimensions.release_reliability,others:Object.entries(c.dimensions)
          .filter(([k])=>k!=='release_reliability').map(([k,v])=>v.verdict),
          sameAsSwapped:BM.canonicalJson(c)===BM.canonicalJson(back),reversed:rev.dimensions.release_reliability.verdict,
          again:BM.canonicalJson(c)===BM.canonicalJson(BM.compareResults(before,after))});
      }
      out(rows);
    """)
    for row in result:
        release = row["release"]
        assert release["verdict"] == "improved", release
        assert release["delta"] > 0
        latency = next(m for m in release["metrics"] if m["metric"] == "release_latency_ms")
        assert latency["verdict"] == "improved" and latency["ci"][0] >= 2
        assert all(v["delta"] < 0 for v in latency["values"])
        assert "improved" not in row["others"] and "regressed" not in row["others"]
        assert row["sameAsSwapped"] is True, "l'ordre est celui de runAt, pas des arguments"
        assert row["reversed"] == "regressed"
        assert row["again"] is True, "la même paire rend les mêmes intervalles"


def test_results_under_another_class_suite_or_window_are_not_comparable(tmp_path):
    result = run_node(tmp_path, RESULT + """
      const a=result({}),b=result({},{runAt:2,seed:2});
      out({ok:BM.compareResults(a,b).comparable,
        suite:BM.compareResults(a,{...b,exercises:b.exercises.slice(0,5)}),
        viewport:BM.compareResults(a,{...b,viewport:{width:1920,height:1080,scale:4}}),
        rounded:BM.compareResults(a,{...b,viewport:{width:1283,height:718,scale:4}}).comparable,
        scale:BM.compareResults(a,{...b,viewport:{width:1280,height:720,scale:6}}).reason,
        classes:C.BENCHMARK_PLAN_CLASSES,
        noSamples:BM.compareResults(a,b).unsampled.length>0});
    """)
    assert result["ok"] is True
    assert result["suite"] == {"comparable": False, "code": "barehands_benchmark_not_comparable", "reason": "suite"}
    assert result["viewport"]["reason"] == "viewport" and result["scale"] == "viewport"
    assert result["rounded"] is True, "la classe de fenêtre arrondit à 10 px"
    assert result["noSamples"] is True, "une métrique sans échantillons est signalée, pas inventée"


# ------------------------------------------------------------------ résumés


def test_the_summary_store_posts_contract_results_and_surfaces_server_refusals(tmp_path):
    result = run_node(tmp_path, RESULT + """
      const calls=[];
      const ok=BM.createSummaryStore({fetch:async(url,init)=>{calls.push([url,init.method,init.body?JSON.parse(init.body):null]);
        return {ok:true,json:async()=>({id:'abc',stored:1})}}});
      const saved=await ok.save(result({}));
      await ok.list();await ok.clear();
      const ko=BM.createSummaryStore({fetch:async()=>({ok:false,status:400,headers:{get:k=>k==='X-Jarvis-Error-Code'?'barehands_benchmark_invalid':null},
        text:async()=>'refusé'})});
      let error=null;try{await ko.save(result({}))}catch(e){error=[e.code,e.message]}
      let local=null;try{await ok.save({...result({}),frames:[]})}catch(e){local=e.code}
      out({saved,calls:calls.map(c=>[c[0],c[1]]),body:calls[0][2],error,local});
    """)
    assert result["saved"] == {"id": "abc", "stored": 1}
    assert result["calls"] == [["/api/barehands/benchmarks", "POST"], ["/api/barehands/benchmarks", "GET"],
                               ["/api/barehands/benchmarks", "DELETE"]]
    assert result["body"]["kind"] == "benchmark_result" and result["body"]["viewport"]["width"] == 1280
    assert result["error"][0] == "barehands_benchmark_invalid" and "400" in result["error"][1]
    assert result["local"] == "barehands_session_key_unknown"


def test_the_module_never_names_user_skill_and_is_inserted_in_the_page():
    source = MODULE.read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    code = re.sub(r"(?m)^\s*//.*$", "", code)
    assert "skill" not in code.lower()
    assert "précision de l" not in code.lower()
    from jarvis.runtime import control_center as cc

    assert cc.BAREHANDS_BENCHMARK_SCRIPT_FILE == MODULE.name
    html = (RUNTIME / "control_center.html").read_text(encoding="utf-8")
    assert html.index(cc.BAREHANDS_BENCHMARK_SCRIPT_MARKER) < html.index(cc.BAREHANDS_SCRIPT_MARKER)
    assert html.index(cc.BAREHANDS_CONTRACTS_SCRIPT_MARKER) < html.index(cc.BAREHANDS_BENCHMARK_SCRIPT_MARKER)
    doc = DOC.read_text(encoding="utf-8")
    for decision in ("Décision 60", "Décision 61", "Décision 62", "Décision 63", "Décision 64"):
        assert decision in doc, decision

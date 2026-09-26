"""Banc d'essai Bare Hands « Tester » (tâche adaptative, Slice 08), par node.

Ce qui est épinglé ici (contrat lisible : § 17, décisions 60 à 64) :

- **le plan** : la même graine rejoue la même disposition, octet pour octet ;
  deux graines tirent des dispositions **différentes mais équivalentes** (même
  multi-ensemble de classes de difficulté, positions et ordre différents) ;
  le plan est un plan du contrat (`createBenchmarkPlan`) ;
- **le déroulé** passe par le **vrai** moteur : un utilisateur synthétique
  (`tests/fixtures/barehands_benchmark_driver.cjs`) devant le vrai
  `createController`, et le vrai résolveur, le vrai constat de sélection, le
  vrai moteur de captures sur le vrai cadre d'entraînement, le vrai
  segmenteur d'épisodes. Même profil + même graine + même trace → le même
  résultat, JSON canonique identique ;
- **lecture seule** : une dépendance d'écriture est refusée, une vue écrite
  lève `barehands_benchmark_read_only`, et un banc joué sur le vrai chemin
  effectif (essai en cours compris) ne change ni réglage, ni profil, ni essai,
  ni composition, et n'appelle aucune porte d'écriture ;
- **le score** : chaque défaut injecté fait baisser **sa** dimension et laisse
  les autres dans leur bande de bruit ; une dimension catastrophique plafonne
  le global quelle que soit la force des autres ; les métriques brutes
  voyagent avec le score, et rien ne s'appelle « skill » ;
- **la comparaison** : mêmes profils sur dispositions différentes → inchangé ;
  défaut → régressé ; défaut corrigé → amélioré ; suites différentes → non
  comparable.
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
        "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True,
                          encoding="utf-8", timeout=120, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# ------------------------------------------------------------------ le plan


def test_the_same_seed_replays_the_same_layout_and_the_plan_is_a_contract_plan(tmp_path):
    result = run_node(tmp_path, """
      const vp={width:1280,height:720};
      const a=BM.layoutPlan(BM.generatePlan(123),vp),b=BM.layoutPlan(BM.generatePlan(123),vp);
      const c=BM.layoutPlan(BM.generatePlan(124),vp);
      const plan=BM.generatePlan(123);
      out({same:BM.canonicalJson(a)===BM.canonicalJson(b),differ:BM.canonicalJson(a)!==BM.canonicalJson(c),
        valid:BM.canonicalJson(C.createBenchmarkPlan(plan))===BM.canonicalJson(plan),
        kinds:plan.exercises.map(e=>e.kind),planClass:plan.planClass,
        badSeed:refused(()=>BM.generatePlan(-1)),hugeSeed:refused(()=>BM.generatePlan(2**32)),
        smallWindow:refused(()=>BM.layoutPlan(plan,{width:500,height:300})),
        otherClass:refused(()=>C.createBenchmarkPlan({...plan,planClass:'bh-bench-9'}))});
    """)
    assert result["same"] is True and result["differ"] is True and result["valid"] is True
    assert sorted(result["kinds"]) == sorted(["target_acquisition", "no_click_tracking", "nearby_targets",
                                              "drag_drop", "moving_target", "chained"])
    assert result["planClass"] == "bh-bench-1"
    assert result["badSeed"] == result["hugeSeed"] == "barehands_benchmark_seed_invalid"
    assert result["smallWindow"] == "barehands_benchmark_viewport_invalid"
    assert result["otherClass"] == "barehands_benchmark_invalid"


def test_two_seeds_draw_equivalent_but_different_layouts(tmp_path):
    """La règle d'équivalence de la classe `bh-bench-1` : pour 40 graines,
    le multi-ensemble des classes de difficulté est identique, la difficulté
    de Fitts totale reste dans ±`distanceJitter`, tout tient dans le champ —
    et les positions, elles, changent."""

    result = run_node(tmp_path, """
      const vp={width:1280,height:720};
      const sig=[],fitts=[],positions=new Set(),outside=[];
      for(let s=1;s<=40;s+=1){
        const L=BM.layoutPlan(BM.generatePlan(s*2654435761>>>0),vp);
        const f=L.field;
        const inField=(p,m)=>p.x>=f.x0+m-1e-6&&p.x<=f.x1-m+1e-6&&p.y>=f.y0+m-1e-6&&p.y<=f.y1-m+1e-6;
        const classes={};let id=0;
        for(const e of L.exercises){
          const list=e.trials.map(t=>{
            if(e.kind==='target_acquisition'){id+=Math.log2(t.distancePx/t.stars[0].size+1);return `${t.sizeClass}/${t.distanceClass}`}
            if(e.kind==='nearby_targets')return String(t.gapPx);
            if(e.kind==='moving_target')return String(t.speedPxPerS);
            if(e.kind==='drag_drop')return String(BM.BANDS.drag_drop.offsetsPx.find(o=>Math.abs(t.offsetPx/o-1)<=BM.BANDS.distanceJitter+1e-9));
            if(e.kind==='no_click_tracking')return t.mode;
            return 'chain';
          });
          classes[e.kind]=list.slice().sort().join(',');
          for(const t of e.trials)for(const st of (t.stars||[])){positions.add(`${Math.round(st.x)}|${Math.round(st.y)}`);
            if(!inField(st,st.size/2))outside.push([e.kind,st.x,st.y])}
        }
        sig.push(JSON.stringify(classes));fitts.push(id);
      }
      out({distinct:new Set(sig).size,sample:JSON.parse(sig[0]),fittsMin:Math.min(...fitts),fittsMax:Math.max(...fitts),
        positions:positions.size,outside:outside.slice(0,3)});
    """)
    assert result["distinct"] == 1, "une graine a changé la difficulté, pas seulement la disposition"
    assert result["sample"]["target_acquisition"] == "0/1,0/2,1/0,1/1,2/0,2/2"
    assert result["sample"]["nearby_targets"] == "14,14,22,22,8,8"
    assert result["sample"]["no_click_tracking"] == "aim,aim,natural,natural"
    # ±8 % de distance sur des cibles de taille fixe : l'indice de Fitts total
    # bouge peu d'une graine à l'autre.
    assert result["fittsMax"] - result["fittsMin"] < 1.2
    assert result["positions"] > 1000, "les dispositions doivent vraiment changer"
    assert result["outside"] == []


# ------------------------------------------------------------------ le déroulé


def test_same_profile_seed_and_trace_give_the_same_result_through_the_real_engine(tmp_path):
    result = run_node(tmp_path, """
      const a=await D.runSynthetic({seed:77});
      const b=await D.runSynthetic({seed:77});
      const replayed=await D.runSynthetic({seed:77,replay:a.trace});
      const other=await D.runSynthetic({seed:78});
      out({same:BM.canonicalJson(a.result)===BM.canonicalJson(b.result),
        replay:BM.canonicalJson(a.result)===BM.canonicalJson(replayed.result),
        differs:BM.canonicalJson(a.result)!==BM.canonicalJson(other.result),
        comparable:C.benchmarkComparable(a.result,other.result),
        frames:a.frames,measured:a.measured,
        result:a.result,
        events:[...new Set(a.log.map(l=>l[1]))],
        trials:a.log.filter(l=>l[1]==='barehands.benchmark_trial').map(l=>l[2].outcome)});
    """)
    assert result["same"] is True, "deux runs identiques ont rendu deux résultats"
    assert result["replay"] is True, "la même trace rejouée a rendu un autre résultat"
    assert result["differs"] is True and result["comparable"] is True
    assert result["measured"] >= result["frames"], "chaque image passe par la couture de mesure du vrai contrôleur"
    r = result["result"]
    assert r["kind"] == "benchmark_result" and r["seed"] == 77 and r["profileSource"] == "defaults"
    assert len(r["profileFingerprint"]) == 16
    # Chaque métrique de chaque exercice est présente, et mesurée sur ce profil
    # par défaut : le banc ne rend pas un tableau de `null`.
    for exercise in r["exercises"]:
        assert all(value is not None for value in exercise["metrics"].values()), exercise
    # Le chemin normal se journalise : début, essais, exercices, fin.
    assert {"barehands.benchmark_started", "barehands.benchmark_trial", "barehands.benchmark_exercise",
            "barehands.benchmark_done"} <= set(result["events"])
    assert result["trials"].count("success") == len(result["trials"]) == 26


def test_the_runner_reads_the_real_engine_and_refuses_to_run_without_it(tmp_path):
    """Pas de moteur, pas de banc : chaque pièce réelle manquante se refuse à
    la construction, et la page partage la règle de la main du résolveur
    (`resolverHandOf`) au lieu d'en garder une copie."""

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
    assert "token.pointing!==false" not in body, "la règle de survol doit vivre dans le bloc pur, une fois"


# ------------------------------------------------------------------ lecture seule


def test_the_benchmark_refuses_write_capable_dependencies_and_views_refuse_writes(tmp_path):
    result = run_node(tmp_path, """
      const comp=B.composeEffective({contracts:C,settings:C.SETTINGS_DEFAULTS,profile:null,trial:{},session:{},viewportWidth:1280});
      const view=BM.profileView({composition:comp,source:'defaults'});
      const base={contracts:C,core:B,target:T,geometry:G,calibration:K,profile:view,
        plan:BM.generatePlan(1),viewport:{width:1280,height:720},pinchChannel:(c,h)=>B.createPinchChannel(c,{})};
      const extra=k=>refused(()=>BM.createBenchmarkRunner({...base,[k]:()=>{}}));
      out({save:extra('save'),trials:extra('trials'),settings:extra('settings'),persistProfile:extra('persistProfile'),
        apply:extra('apply'),controller:extra('controller'),
        set:refused(()=>{view.targets.targetSwitchPx=0}),top:refused(()=>{view.source='saved'}),
        del:refused(()=>{delete view.assistance}),define:refused(()=>Object.defineProperty(view,'x',{value:1})),
        proto:refused(()=>Object.setPrototypeOf(view.targets,{})),
        intact:view.targets.targetSwitchPx===comp.interaction.targetSwitchPx,
        readOnlyCode:BM.READ_ONLY,
        trialWithoutRef:refused(()=>BM.profileView({composition:comp,source:'trial'})),
        refWithoutTrial:refused(()=>BM.profileView({composition:comp,source:'saved',trialRef:'tr-1'}))});
    """)
    code = "barehands_benchmark_read_only"
    assert result["readOnlyCode"] == code
    for key in ("save", "trials", "settings", "persistProfile", "apply", "controller"):
        assert result[key] == code, key
    for key in ("set", "top", "del", "define", "proto"):
        assert result[key] == code, key
    assert result["intact"] is True
    assert result["trialWithoutRef"] == result["refWithoutTrial"] == "barehands_benchmark_profile_invalid"


def test_a_benchmark_on_the_live_effective_path_mutates_nothing(tmp_path):
    """Le vrai chemin effectif de la page (`createEffectivePath`), un vrai
    contrôleur qui suit une main, un **essai en cours** : on joue un banc entier
    sur la composition effective, puis on compare réglages, profil, essai,
    composition et journal d'essai, et on compte chaque porte d'écriture."""

    result = run_node(tmp_path, WORLD + RIG + """
      const R=await rig();
      const receipt=R.T.apply({releaseMs:120});
      const calls={configure:0,configureTargets:0,persist:0};
      const configure=R.controller.configure.bind(R.controller);
      R.controller.configure=p=>{calls.configure+=1;return configure(p)};
      const snap=()=>JSON.stringify({settings:R.state.settings,profile:R.state.profile,status:R.T.status(),
        delta:R.T.delta(),history:R.T.history(),effective:R.path.effective().layers,session:R.path.session(),
        engine:R.controller.options(),persisted:R.persisted});
      const before=snap();
      const st=R.T.status();
      const run=await D.runSynthetic({seed:5,composition:R.path.effective(),source:'trial',trialRef:st.trialId});
      const after=snap();
      out({receipt:receipt.ok,same:before===after,calls,persisted:R.persisted.length,
        source:run.result.profileSource,trialRef:run.result.trialRef,active:R.T.status().active});
    """)
    assert result["receipt"] is True and result["active"] is True
    assert result["same"] is True, "le banc a changé l'état des réglages, du profil ou de l'essai"
    assert result["calls"]["configure"] == 0
    assert result["persisted"] == 0
    assert result["source"] == "trial" and result["trialRef"] == "tr-1"


# ------------------------------------------------------------------ le score


def test_each_injected_defect_lowers_its_own_dimension_and_leaves_the_others_in_their_band(tmp_path):
    """Un défaut du **profil** (ou de la trace), le même utilisateur, la même
    graine : la dimension visée tombe au-delà de sa bande de bruit, les autres
    restent dedans."""

    result = run_node(tmp_path, """
      const score=async o=>BM.scoreResult((await D.runSynthetic({seed:9,...o})).result);
      const base=await score({});
      const trial=patch=>({trial:patch,source:'trial',trialRef:'tr-1'});
      const cases={
        release_reliability:await score(trial({releaseMs:250,releaseFrames:5})),
        false_positive_resistance:await score({...trial({pressRatio:.36,releaseRatio:.42}),strayEveryMs:900,strayGap:.3}),
        pointer_stability:await score({tremorPx:10}),
        selection_accuracy:await score(trial({assistance:0})),
      };
      const dims=s=>Object.fromEntries(Object.entries(s.dimensions).map(([k,v])=>[k,v.score]));
      out({base:dims(base),cases:Object.fromEntries(Object.entries(cases).map(([k,s])=>[k,dims(s)])),
        bands:BM.NOISE_BANDS,
        latency:[base.dimensions.release_reliability.metrics.find(m=>m.metric==='release_latency_ms').value,
          cases.release_reliability.dimensions.release_reliability.metrics.find(m=>m.metric==='release_latency_ms').value]});
    """)
    base, bands = result["base"], result["bands"]
    for target, scores in result["cases"].items():
        assert scores[target] <= base[target] - bands[target], (target, scores[target], base[target])
        for name, value in scores.items():
            if name == target or (target == "selection_accuracy" and name == "acquisition"):
                continue
            assert abs(value - base[name]) < bands[name], (target, name, value, base[name])
    # Et la cause brute est là, pas seulement le score : la latence de
    # relâchement mesurée a monté.
    assert result["latency"][1] > result["latency"][0] + 100


RESULT = """
const exercisesOf=metrics=>BM.SUITE.map((e,i)=>({ref:`ex-${i+1}`,kind:e.kind,trials:e.trials,
  metrics:Object.fromEntries(C.BENCHMARK_EXERCISE_METRICS[e.kind].map(m=>[m,metrics[m]===undefined?PERFECT[m]:metrics[m]]))}));
const PERFECT={acquisition_ms:900,missed_click_count:0,wrong_target_count:0,reacquisition_count:0,press_latency_ms:30,
  false_click_count:0,false_press_rate:0,false_secondary_press_rate:0,unintended_target_rate:0,unintended_pointer_rate:0,
  pointer_jitter_px:1,target_ambiguity:.3,drag_success_rate:1,premature_drop_count:0,placement_error_px:8,
  release_latency_ms:60,pointer_lag_ms:20,transition_ms:900};
const result=(metrics,o)=>C.createBenchmarkResult({ref:'bm-1',seed:1,runAt:1,profileSource:'saved',
  exercises:exercisesOf(metrics||{}),...(o||{})});
"""


def test_a_catastrophic_dimension_cannot_be_hidden_by_strong_ones(tmp_path):
    result = run_node(tmp_path, RESULT + """
      const perfect=BM.scoreResult(result({}));
      const falsePos=BM.scoreResult(result({false_press_rate:40,false_secondary_press_rate:40,false_click_count:4,
        unintended_target_rate:40,unintended_pointer_rate:40}));
      const release=BM.scoreResult(result({release_latency_ms:2000,premature_drop_count:3}));
      const allMid=BM.scoreResult(result({acquisition_ms:2350,release_latency_ms:215,pointer_jitter_px:5.75,
        pointer_lag_ms:100,press_latency_ms:160,transition_ms:2400,placement_error_px:44,drag_success_rate:.7}));
      const partial=BM.scoreResult({...result({}),exercises:result({}).exercises.map(e=>
        ({...e,metrics:Object.fromEntries(Object.keys(e.metrics).map(k=>[k,['drag_drop','chained','no_click_tracking','moving_target'].includes(e.kind)?null:e.metrics[k]]))}))});
      out({perfect:perfect.global,falsePos:falsePos.global,fp:falsePos.dimensions.false_positive_resistance.score,
        release:release.global,allMid:allMid.global,partial:partial.global,
        margin:BM.WEAK_CAP_MARGIN,keys:Object.keys(perfect),dimKeys:Object.keys(perfect.dimensions.acquisition),
        metric:perfect.dimensions.acquisition.metrics[0]});
    """)
    assert result["perfect"]["score"] == 100
    fp = result["falsePos"]
    assert result["fp"] == 0
    # Sept dimensions parfaites et une nulle : la moyenne géométrique seule
    # rendrait ~56 ; le plafond la ramène à la plus faible + 25.
    assert fp["weakest"] == "false_positive_resistance" and fp["capped"] is True
    assert fp["score"] <= 0 + result["margin"]
    assert result["release"]["weakest"] == "release_reliability"
    assert result["release"]["score"] <= result["margin"]
    # Un système moyen partout n'est pas plafonné : c'est la faiblesse isolée
    # que le plafond vise, pas la médiocrité uniforme.
    assert result["allMid"]["capped"] is False
    assert 30 < result["allMid"]["score"] < 70
    # Moins de six dimensions mesurées : pas de global.
    assert result["partial"]["score"] is None and len(result["partial"]["unmeasured"]) >= 3
    # Les métriques brutes voyagent avec le score, et rien ne s'appelle skill.
    assert result["metric"]["value"] == 900 and result["metric"]["unit"] == "ms"
    assert "result" in result["keys"] and "subject" in result["keys"]
    flat = json.dumps(result).lower()
    assert "skill" not in flat and "user_accuracy" not in flat


def test_every_metric_score_moves_in_the_expected_direction(tmp_path):
    """Chaque rampe va dans le sens de `better` du contrat, est bornée à
    [0, 100], et rend 100 à son ancre `good` et 0 à son ancre `bad`."""

    result = run_node(tmp_path, """
      const rows=[];
      for(const [name,spec] of Object.entries(BM.METRIC_SCORING)){
        const better=C.CALIBRATION_METRIC[name].better;
        const trials=spec.per==='trial'?4:1;
        const at=v=>BM.metricScore(name,spec.per==='trial'?v*trials:v,trials);
        const worse=better==='lower'?spec.bad+Math.abs(spec.bad-spec.good):spec.bad-Math.abs(spec.bad-spec.good)/2;
        rows.push({name,better,good:at(spec.good),bad:at(spec.bad),beyond:at(worse),mid:at((spec.good+spec.bad)/2),
          dir:better==='lower'?spec.good<spec.bad:spec.good>spec.bad});
      }
      const scored=new Set(Object.keys(BM.METRIC_SCORING));
      out({rows,missing:C.BENCHMARK_DIMENSIONS.flatMap(d=>C.BENCHMARK_DIMENSION_METRICS[d]).filter(m=>!scored.has(m)),
        nullIsNull:BM.metricScore('acquisition_ms',null,1)});
    """)
    assert result["missing"] == []
    assert result["nullIsNull"] is None
    for row in result["rows"]:
        assert row["dir"] is True, row
        assert row["good"] == 100 and row["bad"] == 0 and row["beyond"] == 0, row
        assert row["mid"] == 50, row


# ------------------------------------------------------------------ avant / après


def test_comparison_verdicts_noise_band_and_learning_note(tmp_path):
    result = run_node(tmp_path, """
      const run=async o=>(await D.runSynthetic(o)).result;
      const trial=patch=>({trial:patch,source:'trial',trialRef:'tr-1'});
      const a=await run({seed:11,runAt:1000});
      const b=await run({seed:12,runAt:2000,performerSeed:2});
      const bad=await run({seed:13,runAt:3000,...trial({releaseMs:250,releaseFrames:5})});
      const fixed=await run({seed:14,runAt:4000});
      const same=BM.compareResults(a,b),worse=BM.compareResults(a,bad),better=BM.compareResults(bad,fixed);
      const reversed=BM.compareResults(bad,a);
      const shorter={...a,exercises:a.exercises.slice(0,5)};
      const replay=BM.compareResults(a,{...a,runAt:5000});
      out({same:Object.fromEntries(Object.entries(same.dimensions).map(([k,v])=>[k,v.verdict])),
        worse:worse.dimensions.release_reliability,better:better.dimensions.release_reliability.verdict,
        reversedBefore:reversed.before.runAt,
        notComparable:BM.compareResults(a,shorter),layoutsDiffer:same.layoutsDiffer,note:same.note,
        replayNote:replay.note,replayDiffer:replay.layoutsDiffer,sameProfile:same.sameProfile,
        worseSameProfile:worse.sameProfile,band:worse.dimensions.release_reliability.noiseBand});
    """)
    assert set(result["same"].values()) == {"unchanged"}, result["same"]
    worse = result["worse"]
    assert worse["verdict"] == "regressed" and worse["delta"] <= -worse["noiseBand"]
    assert result["better"] == "improved"
    # L'ordre avant/après est celui de `runAt`, pas celui des arguments.
    assert result["reversedBefore"] == 1000
    assert result["notComparable"] == {"comparable": False, "code": "barehands_benchmark_not_comparable",
                                       "reason": "suite"}
    assert result["layoutsDiffer"] is True and "atténué, pas éliminé" in result["note"]
    assert result["replayDiffer"] is False and "mémoire de la disposition" in result["replayNote"]
    assert result["sameProfile"] is True and result["worseSameProfile"] is False
    assert result["band"] == 8


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
    assert result["body"]["kind"] == "benchmark_result" and "exercises" in result["body"]
    assert result["error"][0] == "barehands_benchmark_invalid" and "400" in result["error"][1]
    assert result["local"] == "barehands_session_key_unknown", "une clé hors schéma ne part jamais"


def test_the_module_never_names_user_skill_and_is_inserted_in_the_page():
    source = MODULE.read_text(encoding="utf-8")
    # Le code, commentaires ôtés : aucun identifiant, aucune clé, aucun texte
    # rendu ne dit « skill » (les commentaires, eux, disent pourquoi).
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

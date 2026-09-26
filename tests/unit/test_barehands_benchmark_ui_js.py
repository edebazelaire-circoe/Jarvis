"""Bare Hands — l'écran « Tester » (tâche adaptative, Slice 09).

`docs/barehands-contracts.md` § 17, décisions 65 à 68. Ce que ces tests tiennent :

- un run entier passe par le **vrai** contrôleur, le **vrai** déroulé de la
  Slice 08 et la **vraie** coque plein cadre, devant un utilisateur
  synthétique réaliste qui lit ce que l'écran du test dessine ;
- le moteur est tenu éveillé pendant un run et **rendu** à chaque sortie (fin,
  panne, Quitter, Échap, croix, calibration) ;
- une panne du déroulé arrête le run proprement, **se voit** et se journalise ;
- la fenêtre trop petite est refusée avant le départ, avec sa phrase ;
- le rapport : dimensions d'abord, global secondaire et `null`-sûr, dimension
  faible → exercice de calibration ; aucun mot d'« habileté » ;
- le rangement (`save`/`list`) et l'avant/après pour chaque verdict, y compris
  « pas de conclusion » et « ne se compare pas » ;
- l'écran n'écrit ni réglage, ni profil, ni essai.

Harnais : le double de DOM de `test_barehands_calibration_js.py` (qui tombe comme
le vrai), la vraie coque (`createFlowOverlay`), et l'appareil de la Slice 08
(`tests/fixtures/barehands_benchmark_driver.cjs`, `createRig`).
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_barehands_calibration_js import DOM  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
DRIVER = ROOT / "tests" / "fixtures" / "barehands_benchmark_driver.cjs"
UI = RUNTIME / "control_center_barehands_benchmark_ui.js"
DOC = ROOT / "docs" / "barehands-contracts.md"

#: Les mots qui feraient du test une note de la personne (décision 40 : la
#: qualité d'interaction du système, jamais l'habileté de l'utilisateur).
BANNED = re.compile(
    r"skill|habilet|compétence|précision de l.utilisateur|votre précision|votre niveau|user accuracy",
    re.IGNORECASE,
)

HARNESS = r"""
const {B,K,T,G,BM}=D;
global.JarvisBarehandsContracts=C;
global.JarvisBarehandsBenchmark=BM;
const U=require(UI_PATH);
clock=Date.UTC(2026,8,26,8,0,0);
const timers=[];
const settle=async()=>{for(let i=0;i<12;i+=1)await new Promise(r=>setImmediate(r))};
/* Le magasin : la **même** forme que la vraie route (`{results:[{id,result}],
   skipped,max}`), et le résultat validé par le contrat comme le fait
   `createSummaryStore` avant l'envoi. */
function memoryStore(){
  const saved=[];let n=0;
  const s={saved,calls:[],fail:null,listFail:null,
    async list(){s.calls.push('list');
      if(s.listFail)throw Object.assign(new Error(s.listFail),{code:'barehands_benchmark_store_failed'});
      return {results:saved.slice().sort((a,b)=>a.result.runAt-b.result.runAt),skipped:0,max:20}},
    async save(r){s.calls.push('save');
      if(s.fail)throw Object.assign(new Error(s.fail),{code:'barehands_benchmark_store_failed'});
      const result=C.createBenchmarkResult(r);const id=`run-${++n}`;saved.push({id,result});
      return {id,stored:saved.length,dropped:0,duplicate:false}},
    async clear(){s.calls.push('clear');const k=saved.length;saved.length=0;return {cleared:k,backups:0}},
  };
  return s;
}
const IDLE=Object.freeze({phase:'idle',t:0,exerciseRef:null,kind:null,trial:0,trials:0,mode:null,step:null,stars:[],
  frame:null,destination:null,aimSpot:null,preview:[],exercises:6,exerciseIndex:-1});
async function makeFlow(o){
  const opts=o||{};
  const events=[];
  let flow=null;
  const rig=await D.createRig(Object.assign({startAt:1000},opts.rig||{}),(m,controller)=>{
    if(flow&&flow.running())flow.feed(m,controller.semantics());
  });
  const vp=opts.viewport||{width:1280,height:720};
  const overlay=K.createFlowOverlay({document,now:()=>clock});
  const store=opts.store||memoryStore();
  const realRunner=plan=>BM.createBenchmarkRunner({contracts:C,core:B,target:T,geometry:G,calibration:K,
    profile:BM.profileView({composition:rig.composition,source:opts.source||'defaults',
      trialRef:opts.trialRef===undefined?null:opts.trialRef}),
    plan,viewport:{width:vp.width,height:vp.height,cx:vp.width/2,cy:vp.height/2},pinchChannel:rig.pinchChannel,log:()=>{}});
  flow=U.createBenchmarkFlow({document,overlay,now:()=>clock,engineNow:()=>rig.now(),
    setInterval:(fn,ms)=>{timers.push({fn,ms});return timers.length},clearInterval:id=>{if(timers[id-1])timers[id-1]=null},
    viewport:()=>vp,seed:()=>opts.seed===undefined?7:opts.seed,calibrationSteps:K.STEPS,
    createRunner:opts.createRunner?plan=>opts.createRunner(plan,realRunner):realRunner,
    store,
    onRunStart:()=>events.push('runStart'),onRunEnd:why=>events.push(`runEnd:${why}`),
    onClose:why=>events.push(`close:${why}`),
    calibrate:stage=>{events.push(`calibrate:${stage}`);return {ok:true}},
    log:(level,event,data)=>events.push([level,event,data])});
  const human=opts.user===undefined?'typical':opts.user;
  const base=D.createPerformer({seed:opts.performerSeed||3,viewport:vp,tremorPx:human?0:.4,
    aimHoldMs:human?D.USERS[human].aimHoldMs:undefined});
  const performer=human?D.humanize(base,D.USERS[human],opts.performerSeed||3):base;
  let frames=0;
  const step=()=>{
    const p=performer.next(rig.now(),rig.dt,flow.state()||IDLE);
    rig.show(opts.handless&&opts.handless(frames)?null:p);
    rig.tick();clock+=rig.dt;frames+=1;
    /* Le chien de garde de la page tourne à 100 ms ; ici à chaque image. */
    for(const t of timers.slice())if(t)t.fn();
  };
  /* Échauffement : la main se pose avant l'accueil, comme une personne. */
  for(let i=0;i<30;i+=1)step();
  return {flow,rig,events,overlay,store,vp,step,frames:()=>frames,
    until:async(pred,cap)=>{for(let i=0;i<(cap||12000)&&!pred();i+=1)step();await settle();return pred()},
    toReport:async()=>{
      for(let i=0;i<12000&&flow.running();i+=1)step();
      await settle();
      return flow.screen();
    }};
}
const root=()=>flowRoot();
const heading=()=>{const h=deep(root()).find(n=>n.tagName==='H2');return h?h.textContent:null};
const note=()=>text(root(),C.DOM.flowNoteClass)[0];
const shown=()=>deep(root()).map(n=>n.textContent).filter(Boolean).join(' \n ');
const attrs=(name)=>deep(root()).filter(n=>n.getAttribute&&n.getAttribute(name)!==null);
const kindOf=n=>n.getAttribute('data-bench');
const keepAwake=h=>h.events.filter(e=>typeof e==='string'&&/^run(Start|End)/.test(e));
"""


def run_node(tmp_path: Path, source: str, name: str = "benchui") -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / f"barehands-{name}.cjs"
    script.write_text(
        f"const D=require({json.dumps(str(DRIVER))});\n"
        f"const UI_PATH={json.dumps(str(UI))};\n"
        "const C=D.C;\n"
        + DOM
        + HARNESS
        + "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True,
                          encoding="utf-8", timeout=300, check=False)
    assert done.returncode == 0, done.stderr[-4000:]
    return json.loads(done.stdout)


#: Ce que l'écran dessine pendant un run, relevé image par image : par type
#: d'exercice (et mode), les nœuds du champ, la destination et sa tolérance.
SAMPLE = r"""
const fieldOf=()=>deep(root()).find(n=>String(n.className||'')==='jb-field')||null;
const drawn=()=>{
  const f=fieldOf();if(!f)return null;
  return deep(f).filter(n=>n!==f).map(n=>({cls:n.className,star:n.getAttribute('data-bench-star'),
    expected:n.getAttribute('data-expected'),quiet:n.getAttribute('data-quiet'),preview:n.getAttribute('data-preview'),
    drop:n.getAttribute('data-bench-drop'),tol:n.getAttribute('data-tolerance'),frame:n.getAttribute('data-bench-frame'),
    aim:n.getAttribute('data-bench-aim'),objectId:n.getAttribute('data-object-id'),
    left:n.style.left,top:n.style.top,width:n.style.width,height:n.style.height}));
};
"""


def test_a_full_run_goes_through_the_real_engine_and_ends_on_the_report(tmp_path):
    """Accueil → consigne → exercices → résultats, sur le **vrai** contrôleur,
    le **vrai** déroulé et la **vraie** coque, devant un utilisateur réaliste
    qui ne lit que ce que l'écran du test lui montre. Le moteur est tenu
    éveillé du premier essai au dernier, et rendu à la fin."""

    result = run_node(tmp_path, SAMPLE + """
      const h=await makeFlow();
      const engineBefore=JSON.stringify(h.rig.controller.options());
      const compositionBefore=JSON.stringify(h.rig.composition);
      const opened=h.flow.open();
      await settle();
      const start={screen:h.flow.screen(),title:heading(),focus:document.activeElement&&document.activeElement.tagName,
        viewport:attrs('data-viewport').map(n=>n.getAttribute('data-viewport')),
        actions:stepActions(root()),text:shown(),bench:root().getAttribute('data-bench')};
      press(root(),'start');
      const brief={screen:h.flow.screen(),title:heading(),running:h.flow.running(),events:keepAwake(h),
        actions:stepActions(root()),note:note()};
      const kinds={},texts=[shown()];let movingXs=[];let lastExercise=-1;
      let previews=0;
      for(let i=0;i<12000&&h.flow.running();i+=1){
        h.step();
        const st=h.flow.state();
        if(h.flow.screen()!=='run'||!st)continue;
        if(st.exerciseIndex!==lastExercise){lastExercise=st.exerciseIndex;texts.push(shown())}
        const key=st.kind+(st.mode?':'+st.mode:'')+(st.step!==null&&st.step!==undefined?':'+st.step:'');
        const d=drawn();
        if(d&&d.some(n=>n.preview==='1'))previews+=1;
        if(d&&d.length&&!kinds[key])kinds[key]={nodes:d,note:note()};
        if(st.kind==='moving_target'&&st.phase==='live'&&d){const s=d.find(n=>n.star);if(s)movingXs.push(s.left)}
      }
      await settle();
      const rows=attrs('data-dimension').map(n=>[n.getAttribute('data-dimension'),n.getAttribute('data-score'),n.getAttribute('data-weak')]);
      const order=deep(root()).filter(n=>n.getAttribute&&(n.getAttribute('data-dimension')||n.getAttribute('data-global')))
        .map(n=>n.getAttribute('data-dimension')?'dim':'global');
      out({opened,start,brief,kinds,previews,moving:[...new Set(movingXs)].length,
        report:{screen:h.flow.screen(),title:heading(),focus:document.activeElement&&document.activeElement.tagName,
          rows,order,save:h.flow.saveState(),saved:h.store.saved.length,actions:stepActions(root()),text:shown(),
          bench:root().getAttribute('data-bench')},
        events:keepAwake(h),running:h.flow.running(),
        untouched:JSON.stringify(h.rig.controller.options())===engineBefore
          &&JSON.stringify(h.rig.composition)===compositionBefore,
        logs:h.events.filter(e=>Array.isArray(e)).map(e=>e[1]),
        texts:texts.join(' | '),dims:C.BENCHMARK_DIMENSIONS});
    """, name="fullrun")

    start = result["start"]
    assert result["opened"]["ok"] is True
    assert start["screen"] == "start" and start["bench"] == "start"
    assert start["title"] == "Tester Bare Hands"
    assert start["focus"] == "H2", "le focus suit l'écran : le titre, jamais une commande qui engage"
    assert start["viewport"] == ["vp100"]
    assert start["actions"] == ["start", "close"]
    assert "ne change aucun réglage" in start["text"]
    # La consigne du premier exercice : le temps du déroulé ne court pas
    # pendant la lecture, et le moteur est déjà tenu éveillé.
    brief = result["brief"]
    assert brief["screen"] == "brief" and brief["running"] is True
    assert brief["title"] == "Prendre une étoile"
    assert brief["events"] == ["runStart"]
    assert brief["actions"] == ["ready", "pause"]
    assert "Exercice 1 sur 6" in brief["note"]

    kinds = result["kinds"]
    # Jamais un nœud que la page prendrait pour une cible réelle.
    for key, seen in kinds.items():
        for node in seen["nodes"]:
            assert node["objectId"] is None, key
            assert "sc-node" not in node["cls"], key
    acq = [n["expected"] for n in kinds["target_acquisition"]["nodes"] if n["star"]]
    assert acq.count("1") == 1 and acq.count("0") >= 1, "une étoile pleine, des leurres"
    drag = kinds["drag_drop"]["nodes"]
    drop = next(n for n in drag if n["drop"])
    window = next(n for n in drag if n["frame"])
    tol = float(drop["tol"])
    assert tol == 48, "tolérance de dépôt de la classe vp100 (`runner.dropTolerancePx()`)"
    # La destination : l'empreinte de la fenêtre plus la tolérance de chaque côté.
    assert int(drop["width"][:-2]) == int(window["width"][:-2]) + 2 * tol
    assert int(drop["height"][:-2]) == int(window["height"][:-2]) + 2 * tol
    assert any(n["aim"] for n in kinds["no_click_tracking:aim"]["nodes"]), "le point à viser est entouré"
    assert all(n["quiet"] == "1" for n in kinds["no_click_tracking:natural"]["nodes"] if n["star"])
    assert "Ne pincez pas" in kinds["no_click_tracking:natural"]["note"]
    assert "Essai 1 sur 6" in kinds["target_acquisition"]["note"]
    assert {"chained:0", "chained:1", "chained:2"} <= set(kinds)
    assert result["moving"] > 20, "la cible mobile bouge : c'est l'exercice, même en mouvement réduit"
    assert result["previews"] > 50, "la présélection du vrai résolveur est dessinée en anneau"

    report = result["report"]
    assert report["screen"] == "report" and report["title"] == "Résultats du test"
    assert report["focus"] == "H2"
    # Les dimensions d'abord, dans l'ordre du contrat ; le global ensuite.
    assert [r[0] for r in report["rows"]] == result["dims"]
    assert report["order"] == ["dim"] * 8 + ["global"]
    assert report["save"] == "saved" and report["saved"] == 1
    assert "Résultat enregistré" in report["text"]
    assert "Premier test" in report["text"], "aucun test comparable encore"
    assert report["actions"] == ["rerun", "history", "close"]
    assert "grande fenêtre (1280 × 720)" in report["text"]
    assert "26 septembre 2026" in report["text"]
    # Le moteur a été rendu à la fin, et le chemin normal se journalise.
    assert result["events"] == ["runStart", "runEnd:fini"]
    assert result["running"] is False
    assert result["untouched"] is True, "le moteur et la composition sortent du test tels qu'ils y sont entrés"
    for event in ("barehands.benchmark_run_started", "barehands.benchmark_run_done", "barehands.benchmark_saved"):
        assert event in result["logs"], event
    for text in (start["text"], result["texts"], report["text"]):
        assert not BANNED.search(text), BANNED.search(text)


def test_a_window_too_small_is_refused_before_start_with_its_reason(tmp_path):
    """Sous la plus petite classe (1024 × 560), le test ne commence pas : la
    phrase du banc est montrée, « Commencer » n'est pas offert, et le moteur
    n'est jamais tenu éveillé."""

    result = run_node(tmp_path, """
      const h=await makeFlow({viewport:{width:1000,height:540}});
      h.flow.open();await settle();
      const answer=h.flow.start();
      out({screen:h.flow.screen(),actions:stepActions(root()),answer,
        refused:attrs('data-viewport').map(n=>[n.getAttribute('data-viewport'),n.getAttribute('role'),n.textContent]),
        events:keepAwake(h),logs:h.events.filter(e=>Array.isArray(e)).map(e=>[e[1],e[2].code||null])});
    """, name="viewport")

    assert result["screen"] == "start"
    assert result["actions"] == ["recheck", "close"]
    assert result["answer"]["ok"] is False
    assert result["answer"]["code"] == "barehands_benchmark_viewport_too_small"
    refused = result["refused"][0]
    assert refused[0] == "refused" and refused[1] == "alert"
    assert "Agrandissez la fenêtre à au moins 1024 × 560" in refused[2]
    assert "1000 × 540" in refused[2]
    assert result["events"] == []
    assert ["barehands.benchmark_viewport_refused", "barehands_benchmark_viewport_too_small"] in result["logs"]


def test_a_runner_failure_stops_the_run_cleanly_and_is_seen_and_logged(tmp_path):
    """**Une panne du déroulé se voit** : l'écran dit sa cause et son code,
    l'erreur est journalisée (niveau erreur → Error Logs), le moteur est rendu,
    et plus aucune image n'entre. Même chose quand la fabrique refuse."""

    result = run_node(tmp_path, """
      let calls=0;
      const h=await makeFlow({createRunner:(plan,real)=>{
        const r=real(plan);
        return Object.assign({},r,{frame:f=>{calls+=1;
          if(calls===40)throw Object.assign(new Error('image illisible'),{code:'barehands_test_boom'});return r.frame(f)}});
      }});
      h.flow.open();await settle();press(root(),'start');
      await h.until(()=>h.flow.screen()==='failed',3000);
      const failed={screen:h.flow.screen(),title:heading(),running:h.flow.running(),
        alert:attrs('data-failure').map(n=>[n.getAttribute('data-failure'),n.getAttribute('role'),n.textContent]),
        actions:stepActions(root()),events:keepAwake(h),failure:h.flow.failure(),
        errors:h.events.filter(e=>Array.isArray(e)&&e[0]==='error').map(e=>[e[1],e[2].code])};
      const before=calls;for(let i=0;i<60;i+=1)h.step();
      const after=calls;
      h.flow.exit('fermer');
      /* La fabrique elle-même refuse. */
      const k=await makeFlow({createRunner:()=>{throw Object.assign(new Error('profil illisible'),{code:'barehands_benchmark_invalid'})}});
      k.flow.open();await settle();
      const answer=k.flow.start();
      out({failed,before,after,refusedStart:{answer,screen:k.flow.screen(),events:keepAwake(k),
        alert:attrs('data-failure').map(n=>n.getAttribute('data-failure'))}});
    """, name="failure")

    failed = result["failed"]
    assert failed["screen"] == "failed" and failed["running"] is False
    assert failed["title"] == "Le test s’est interrompu"
    assert failed["alert"][0][0] == "barehands_test_boom"
    assert failed["alert"][0][1] == "alert"
    assert "image illisible" in failed["alert"][0][2] and "barehands_test_boom" in failed["alert"][0][2]
    assert failed["actions"] == ["restart", "close"]
    assert failed["events"] == ["runStart", "runEnd:panne"]
    assert ["barehands.benchmark_frame_failed", "barehands_test_boom"] in failed["errors"]
    assert result["after"] == result["before"], "plus aucune image n'entre après la panne"
    refused = result["refusedStart"]
    assert refused["answer"]["ok"] is False and refused["answer"]["code"] == "barehands_benchmark_invalid"
    assert refused["screen"] == "failed" and refused["events"] == []
    assert refused["alert"] == ["barehands_benchmark_invalid"]


def test_escape_pauses_then_quits_and_the_engine_is_released_on_every_exit(tmp_path):
    """Échap en deux temps : la première pression met en **pause** (le temps
    du déroulé s'arrête), la seconde **quitte**. Reprendre repasse par la
    consigne. La croix et « Quitter le test » quittent aussi ; chaque sortie
    rend le moteur, et rien n'est enregistré."""

    result = run_node(tmp_path, """
      const h=await makeFlow();
      h.flow.open();await settle();press(root(),'start');
      await h.until(()=>h.flow.screen()==='run'&&h.flow.state()&&h.flow.state().phase==='live',600);
      for(let i=0;i<30;i+=1)h.step();
      const tBefore=h.flow.state().t;
      document.fire('keydown',{key:'Escape'});
      const paused={screen:h.flow.screen(),title:heading(),actions:stepActions(root()),note:note(),running:h.flow.running(),
        field:deep(root()).some(n=>String(n.className||'')==='jb-field')};
      for(let i=0;i<90;i+=1)h.step();     // trois secondes de pause
      const tPaused=h.flow.state().t;
      press(root(),'resume');
      const resumed=h.flow.screen();
      await h.until(()=>h.flow.screen()==='run',200);
      h.step();h.step();
      const tAfter=h.flow.state().t;
      document.fire('keydown',{key:'Escape'});
      const again=h.flow.screen();
      document.fire('keydown',{key:'Escape'});
      const closed={open:h.flow.isOpen(),root:!!root(),events:h.events.filter(e=>typeof e==='string'),saved:h.store.saved.length};
      /* La croix pendant un exercice, puis « Quitter le test » depuis la pause. */
      const x=await makeFlow();x.flow.open();await settle();press(root(),'start');
      await x.until(()=>x.flow.screen()==='run',200);
      deep(root()).find(n=>n.getAttribute&&n.getAttribute('data-flow-close')).fire('click');
      const cross=x.events.filter(e=>typeof e==='string');
      const q=await makeFlow();q.flow.open();await settle();press(root(),'start');
      press(root(),'pause');press(root(),'quit');
      const quit=q.events.filter(e=>typeof e==='string');
      /* Hors run : deux pressions sous deux secondes ferment ; trop tard, la
         seconde ré-arme. */
      const s=await makeFlow();s.flow.open();await settle();
      document.fire('keydown',{key:'Escape'});
      const armed={open:s.flow.isOpen(),note:note()};
      clock+=2500;
      document.fire('keydown',{key:'Escape'});
      const late=s.flow.isOpen();
      document.fire('keydown',{key:'Escape'});
      out({paused,tBefore,tPaused,tAfter,resumed,again,closed,cross,quit,armed,late,
        startClosed:s.flow.isOpen(),startEvents:s.events.filter(e=>typeof e==='string')});
    """, name="escape")

    paused = result["paused"]
    assert paused["screen"] == "paused" and paused["title"] == "Test en pause"
    assert paused["actions"] == ["resume", "quit"]
    assert "Échap à nouveau" in paused["note"]
    assert paused["running"] is True, "une pause tient encore le moteur éveillé"
    assert paused["field"] is False, "rien à viser pendant la pause"
    assert result["tPaused"] == result["tBefore"], "le temps du déroulé est arrêté"
    assert result["resumed"] == "brief", "reprendre relit la consigne"
    # Après reprise, le déroulé voit un temps continu : pause et consigne en
    # sont retirées.
    assert 0 < result["tAfter"] - result["tBefore"] < 400
    assert result["again"] == "paused"
    assert result["closed"]["open"] is False and result["closed"]["root"] is False
    assert result["closed"]["events"] == ["runStart", "runEnd:escape", "close:escape"]
    assert result["closed"]["saved"] == 0, "quitter n'enregistre rien"
    assert result["cross"] == ["runStart", "runEnd:fermeture", "close:fermeture"]
    assert result["quit"] == ["runStart", "runEnd:quitter", "close:quitter"]
    assert result["armed"]["open"] is True and "Échap" in result["armed"]["note"]
    assert result["late"] is True
    assert result["startClosed"] is False
    assert result["startEvents"] == ["close:escape"], "hors run : aucun moteur à rendre"


def test_frames_without_a_hand_still_advance_the_run_and_the_screen_says_so(tmp_path):
    """La couture du contrôleur ne tire que sur une main observée. Le chien de
    garde du flux fait avancer les échéances avec des images vides, et l'écran
    dit « aucune main vue » — un essai ne peut pas attendre pour toujours."""

    result = run_node(tmp_path, """
      const h=await makeFlow({handless:n=>n>=60});
      h.flow.open();await settle();press(root(),'start');
      await h.until(()=>h.flow.screen()==='run'&&h.flow.state()&&h.flow.state().phase==='live',400);
      const t0=h.flow.state().t,trial0=h.flow.state().trial;
      for(let i=0;i<200;i+=1)h.step();
      out({note:note(),dt:h.flow.state().t-t0,
        trial:[trial0,h.flow.state().trial,h.flow.state().exerciseIndex],screen:h.flow.screen()});
    """, name="handless")

    assert "Aucune main vue" in result["note"]
    assert result["dt"] > 5000, "les échéances avancent sans main"
    assert result["trial"][1] > result["trial"][0] or result["trial"][2] > 0, "un essai sans main expire"


#: Des runs réels du même utilisateur synthétique, sous deux profils : les
#: réglages d'usine, et un relâchement volontairement lent (Slice 08 : la
#: fiabilité du relâchement passe de ~98 à ~47).
PAIR = r"""
const T0=Date.UTC(2026,8,25,9,0,0);
const slow={trial:{releaseMs:250,releaseFrames:5},source:'trial',trialRef:'tr-1'};
const run=async(o,runAt)=>(await D.runSynthetic(Object.assign({user:'typical'},o,{runAt}))).result;
const entry=(id,result)=>({id,result});
"""


def test_a_weak_dimension_is_explained_and_links_to_its_calibration_exercise(tmp_path):
    """Un relâchement lent rend `release_reliability` faible : la ligne le
    dit en mots simples, nomme ce qui pèse, et propose « Tenir puis
    relâcher » — qui ferme le test et ouvre la calibration à cet exercice.
    Les mesures brutes sont là, repliées, derrière un bouton clavier."""

    result = run_node(tmp_path, PAIR + """
      const h=await makeFlow({rig:slow,source:'trial',trialRef:'tr-1'});
      h.flow.open();await settle();press(root(),'start');
      await h.toReport();
      const weak=attrs('data-weak').filter(n=>n.getAttribute('data-weak')==='1').map(n=>n.getAttribute('data-dimension'));
      const row=attrs('data-dimension').find(n=>n.getAttribute('data-dimension')==='release_reliability');
      const link=deep(row).find(n=>n.getAttribute&&n.getAttribute('data-calibrate'));
      const toggle=deep(row).find(n=>n.getAttribute&&n.getAttribute('data-details'));
      const details=deep(row).find(n=>String(n.className||'')==='jb-details');
      const hiddenBefore=details.hidden;
      toggle.fire('click');
      const expanded={aria:toggle.getAttribute('aria-expanded'),hidden:details.hidden,controls:toggle.getAttribute('aria-controls'),
        id:details.id,metrics:deep(details).filter(n=>n.getAttribute&&n.getAttribute('data-metric')).map(n=>n.getAttribute('data-metric'))};
      const text=deep(row).map(n=>n.textContent).join(' ');
      const meta=shown();
      link.fire('click');
      await settle();
      out({weak,link:[link.getAttribute('data-calibrate'),link.textContent,link.tagName,link.getAttribute('type')],
        hiddenBefore,expanded,text,meta,after:{open:h.flow.isOpen(),events:h.events.filter(e=>typeof e==='string')},
        score:row.getAttribute('data-score')});
    """, name="weak")

    assert "release_reliability" in result["weak"]
    assert float(result["score"]) < 60
    assert result["link"][0] == "hold_release"
    assert result["link"][1] == "Calibrer « Tenir puis relâcher »…"
    assert result["link"][2:] == ["BUTTON", "button"]
    assert "Le relâchement arrive tard" in result["text"]
    assert "Ce qui pèse le plus" in result["text"] and "ms" in result["text"]
    assert result["hiddenBefore"] is True
    assert result["expanded"]["aria"] == "true" and result["expanded"]["hidden"] is False
    assert result["expanded"]["controls"] == result["expanded"]["id"]
    assert "release_latency_ms" in result["expanded"]["metrics"]
    assert "réglage d’essai" in result["meta"]
    assert result["after"]["open"] is False
    assert result["after"]["events"][-2:] == ["close:calibration", "calibrate:hold_release"]
    assert not BANNED.search(result["text"] + result["meta"])


def test_a_missing_dimension_leaves_the_global_uncalculated_and_named(tmp_path):
    """Une dimension non mesurée n'est ni bonne ni mauvaise : le global n'est
    pas calculé, et l'écran dit **laquelle** manque — jamais un nombre inventé."""

    result = run_node(tmp_path, PAIR + """
      const r=await run({seed:4},T0);
      const copy=JSON.parse(JSON.stringify(r));
      for(const e of copy.exercises)if(e.metrics.transition_ms!==undefined){e.metrics.transition_ms=null;e.samples.transition_ms=[]}
      const h=await makeFlow();h.flow.open();await settle();
      h.flow.showReport(entry('fixture',C.createBenchmarkResult(copy)));
      const transitions=attrs('data-dimension').find(n=>n.getAttribute('data-dimension')==='transitions');
      out({global:attrs('data-global').map(n=>[n.getAttribute('data-global'),n.textContent]),
        score:transitions.getAttribute('data-score'),row:deep(transitions).map(n=>n.textContent).join(' '),
        weak:transitions.getAttribute('data-weak'),save:attrs('data-save').length});
    """, name="nullglobal")

    assert result["global"][0][0] == "null"
    assert result["global"][0][1] == "Indice global non calculé — non mesuré : Enchaînements."
    assert result["score"] == "null" and result["weak"] == "0"
    assert "non mesuré" in result["row"]
    assert result["save"] == 0, "un résultat relu n'a pas d'état d'enregistrement à dire"


def test_saving_and_listing_go_through_the_store_and_failures_are_seen(tmp_path):
    """Le résultat se range par le magasin (`save`), la liste se relit
    (`list`) ; une panne de l'un ou de l'autre se voit à l'écran, avec la
    cause et le code, et se journalise au niveau erreur. Réessayer range."""

    result = run_node(tmp_path, """
      const store=memoryStore();store.listFail='réseau coupé';
      const h=await makeFlow({store});
      h.flow.open();await settle();
      const listFailed={status:attrs('data-history').map(n=>[n.getAttribute('data-kind'),n.textContent]),
        actions:stepActions(root())};
      store.listFail=null;store.fail='disque plein';
      press(root(),'start');
      await h.toReport();
      const saveFailed=attrs('data-save').map(n=>[n.getAttribute('data-save'),n.getAttribute('data-kind'),n.textContent]);
      const retry=stepActions(root());
      store.fail=null;
      press(root(),'save');await settle();
      const saved=attrs('data-save').map(n=>[n.getAttribute('data-save'),n.textContent]);
      out({listFailed,saveFailed,retry,saved,calls:store.calls,count:store.saved.length,
        errors:h.events.filter(e=>Array.isArray(e)&&e[0]==='error').map(e=>[e[1],e[2].code]),
        report:heading(),actions:stepActions(root())});
    """, name="store")

    assert result["listFailed"]["status"][0][0] == "bad"
    assert "réseau coupé" in result["listFailed"]["status"][0][1]
    assert result["listFailed"]["actions"] == ["start", "close"], "une liste illisible n'empêche pas de tester"
    assert result["saveFailed"][0][:2] == ["failed", "bad"]
    assert result["saveFailed"][0][2] == "Résultat non enregistré : disque plein (barehands_benchmark_store_failed)"
    assert result["retry"][0] == "save", "réessayer l'enregistrement est offert"
    assert result["saved"][0][0] == "saved"
    assert result["count"] == 1
    assert result["calls"][0] == "list"
    assert result["calls"].count("save") == 2
    assert ["barehands.benchmark_list_failed", "barehands_benchmark_store_failed"] in result["errors"]
    assert ["barehands.benchmark_save_failed", "barehands_benchmark_store_failed"] in result["errors"]
    assert result["report"] == "Résultats du test"
    assert "save" not in result["actions"] and "history" in result["actions"]


def test_before_after_shows_every_verdict_and_explains_the_rest(tmp_path):
    """L'avant/après, depuis `compareResults` : amélioré, dégradé, inchangé,
    « pas de conclusion » (avec « Relancez le test ») et « ne se compare
    pas ». Par défaut, le plus récent test comparable **avant** celui qu'on
    regarde ; un autre se choisit ; les non comparables disent pourquoi. Les
    mises en garde (dispositions, même personne) sont toujours là."""

    result = run_node(tmp_path, PAIR + """
      const base=await run({seed:11},T0);
      const slowR=await run(Object.assign({seed:12},slow),T0+3600e3);
      const again=await run({seed:13},T0+7200e3);
      /* Pas de conclusion : deux échantillons de transition de chaque côté,
         très écartés — trop peu pour un intervalle. */
      const few=(r,v,t)=>{const c=JSON.parse(JSON.stringify(r));c.runAt=t;
        for(const e of c.exercises)if(e.kind==='chained'){e.samples.transition_ms=[v,v];e.metrics.transition_ms=v}
        return C.createBenchmarkResult(c)};
      const fewA=few(base,1400,T0+10800e3),fewB=few(base,3400,T0+14400e3);
      /* Une autre taille de fenêtre : ne se compare pas. */
      const small=JSON.parse(JSON.stringify(base));small.viewport={width:1100,height:640,scale:4};small.runAt=T0+1800e3;
      const store=memoryStore();
      const add=(id,r)=>store.saved.push({id,result:C.createBenchmarkResult(r)});
      add('base',base);add('slow',slowR);add('again',again);add('small',small);
      const h=await makeFlow({store});h.flow.open();await settle();
      const view=async(id,partnerId)=>{
        const e=store.saved.find(x=>x.id===id);
        h.flow.showReport(e);
        const teaser=attrs('data-compare-teaser')[0];
        const tease=[teaser.getAttribute('data-partner'),teaser.textContent];
        const offered=stepActions(root());
        if(partnerId)h.flow.showCompare(store.saved.find(x=>x.id===partnerId));
        else if(offered.includes('compare'))press(root(),'compare');
        return {tease,offered,title:heading(),rows:attrs('data-verdict').filter(n=>n.tagName==='LI')
            .map(n=>[n.getAttribute('data-dimension'),n.getAttribute('data-verdict'),n.getAttribute('data-reason'),
              deep(n).map(k=>k.textContent).join(' ')]),
          global:attrs('data-global-verdict').map(n=>n.getAttribute('data-global-verdict')),
          notes:deep(root()).filter(n=>String(n.className||'')==='jb-notes').flatMap(n=>n.children.map(c=>c.textContent)),
          picker:deep(root()).filter(n=>n.getAttribute&&n.getAttribute('data-comparable')!==null)
            .map(n=>[n.getAttribute('data-comparable'),n.getAttribute('data-reason'),n.textContent]),
          pressed:deep(root()).filter(n=>n.getAttribute&&n.getAttribute('aria-pressed')==='true').map(n=>n.getAttribute('data-run')),
          text:shown()};
      };
      const regressed=await view('slow');
      const improved=await view('again');
      store.saved.push({id:'fewA',result:fewA},{id:'fewB',result:fewB});
      const inconclusive=await view('fewB','fewA');
      const notComparable=await view('small');
      /* Choisir un autre partenaire dans la liste. */
      h.flow.showReport(store.saved.find(x=>x.id==='again'));
      press(root(),'compare');
      const pick=deep(root()).find(n=>n.getAttribute&&n.getAttribute('data-run')==='base');
      pick.fire('click');
      const picked=deep(root()).filter(n=>n.getAttribute&&n.getAttribute('aria-pressed')==='true').map(n=>n.getAttribute('data-run'));
      out({regressed,improved,inconclusive,notComparable,picked,
        pickedVerdicts:C.BENCHMARK_DIMENSIONS.map(n=>h.flow.comparison().dimensions[n].verdict),
        direct:BM.compareResults(small,base)});
    """, name="compare")

    def verdicts(view):
        return {r[0]: r[1] for r in view["rows"]}

    reg = result["regressed"]
    assert reg["tease"][0] == "base", "le plus récent comparable avant celui-ci"
    assert reg["title"] == "Avant / après"
    assert verdicts(reg)["release_reliability"] == "regressed"
    assert "Dégradé" in next(r[3] for r in reg["rows"] if r[0] == "release_reliability")
    assert "Dispositions différentes" in reg["notes"][0]
    assert any("même personne" in n for n in reg["notes"])
    assert any("réglages d’usine avant, réglage d’essai après" in n for n in reg["notes"])
    # Les non comparables sont nommés dans la liste, avec leur raison.
    small = [p for p in reg["picker"] if p[0] == "0"]
    assert small and small[0][1] == "viewport" and "une autre taille de fenêtre" in small[0][2]
    assert reg["pressed"] == ["base"]

    imp = result["improved"]
    assert imp["tease"][0] == "slow"
    assert verdicts(imp)["release_reliability"] == "improved"
    assert "Amélioré" in next(r[3] for r in imp["rows"] if r[0] == "release_reliability")
    assert "unchanged" in verdicts(imp).values()
    assert any("Inchangé" in r[3] for r in imp["rows"] if r[1] == "unchanged")

    inc = result["inconclusive"]
    row = next(r for r in inc["rows"] if r[0] == "transitions")
    assert row[1] == "inconclusive" and row[2] == "too_few_samples"
    assert "Pas de conclusion" in row[3] and "Relancez le test" in row[3]
    assert any("Les deux tests ont mesuré les mêmes réglages" in n for n in inc["notes"])

    nc = result["notComparable"]
    assert nc["tease"][0] == "none" and "compare" not in nc["offered"]
    assert "Aucun test précédent comparable" in nc["tease"][1] and "une autre taille de fenêtre" in nc["tease"][1]
    assert result["direct"] == {"comparable": False, "code": "barehands_benchmark_not_comparable", "reason": "viewport"}

    assert result["picked"] == ["base"]
    assert len(result["pickedVerdicts"]) == 8
    for view in (reg, imp, inc, nc):
        assert not BANNED.search(view["text"]), BANNED.search(view["text"])


def test_every_word_the_screen_can_show_avoids_skill_wording(tmp_path):
    """Le vocabulaire entier de l'écran (dimensions, métriques, exercices,
    verdicts, mises en garde) décrit le système, jamais la personne ; chaque
    dimension mène à une étape de calibration qui existe ; la feuille n'anime
    rien de décoratif."""

    result = run_node(tmp_path, """
      const words=[];
      const walk=v=>{if(typeof v==='string')words.push(v);else if(v&&typeof v==='object')Object.values(v).forEach(walk)};
      walk([U.DIMENSION_TEXT,U.METRIC_TEXT,U.EXERCISE_TEXT,U.MODE_TEXT,U.VERDICT_TEXT,U.SOURCE_TEXT,U.NOT_COMPARABLE_TEXT,
        U.SAME_PERSON_TEXT,U.SAME_PROFILE_TEXT,U.RERUN_TEXT]);
      out({words,dims:Object.keys(U.DIMENSION_TEXT),map:U.DIMENSION_CALIBRATION,stages:C.STAGES,
        titles:Object.values(U.DIMENSION_CALIBRATION).map(s=>U.calibrationTitle(K.STEPS,s)),
        metrics:Object.keys(U.METRIC_TEXT).sort(),
        scored:[...new Set(C.BENCHMARK_DIMENSIONS.flatMap(d=>C.BENCHMARK_DIMENSION_METRICS[d]))].sort(),
        contractDims:C.BENCHMARK_DIMENSIONS,style:U.STYLE});
    """, name="words")

    for word in result["words"]:
        assert not BANNED.search(word), word
    assert result["dims"] == result["contractDims"] == list(result["map"].keys())
    assert set(result["map"].values()) <= set(result["stages"])
    assert result["titles"] == [
        "Viser et cliquer", "Viser et cliquer", "7A · Bouger librement", "Tenir puis relâcher",
        "6C · Déposer", "7B · Viser sans cliquer", "Pincement pouce-index", "6A · Déplacer",
    ]
    assert result["metrics"] == result["scored"], "chaque métrique brute a son nom en français"
    style = result["style"]
    assert "@keyframes" not in style and "animation:" not in style.replace("animation:none", "")
    assert "prefers-reduced-motion:reduce" in style


# ------------------------------------------------------------------ la page

from test_barehands_tools_settings_js import (  # noqa: E402
    CAMERA, SCRIPT, TIMERS, browser, run_node as run_browser,
)

BENCH = RUNTIME / "control_center_barehands_benchmark.js"

#: La page réelle, avec le vrai banc et le vrai écran du test — dont la
#: fabrique est **enveloppée** pour capturer ce que la page lui donne. Le
#: double de navigateur n'a pas de MediaPipe : un run réel n'y démarre pas, mais
#: chaque porte que la page confie au flux s'exerce directement.
PAGE_SETUP = (
    f"const BENCH_PATH={json.dumps(str(BENCH))};\n"
    f"const UI_PATH={json.dumps(str(UI))};\n"
    + r"""
global.window.innerWidth=1280;global.window.innerHeight=720;
global.JarvisBarehandsBenchmark=require(BENCH_PATH);
global.window.JarvisBarehandsBenchmark=global.JarvisBarehandsBenchmark;
const UIreal=require(UI_PATH);
const captured={};
global.JarvisBarehandsBenchmarkUi=Object.assign({},UIreal,{createBenchmarkFlow:deps=>{
  captured.deps=deps;captured.flow=UIreal.createBenchmarkFlow(deps);return captured.flow}});
const fetched=[];
global.window.fetch=async(url,init)=>{fetched.push([url,(init&&init.method)||'GET']);
  return {ok:true,status:200,headers:{get:()=>null},json:async()=>({results:[],skipped:0,max:20}),text:async()=>''}};
"""
)


def test_the_page_opens_the_test_by_its_own_gate_and_never_writes_a_setting(tmp_path):
    """La page : « Tester… » a sa section et son bouton (à contour, la
    calibration a le bouton plein), ses refus sous ses codes, et le flux ne
    reçoit **aucune** porte d'écriture. La couture de mesure et l'éveil du
    moteur s'ouvrent au début d'un run et se rendent à sa fin ; la calibration
    est refusée tant que le test est à l'écran ; rien n'écrit un réglage, un
    profil ni un essai."""

    result = run_browser(tmp_path, CAMERA + browser(PAGE_SETUP) + TIMERS + """
      await openTab();
      const panel={bench:byAttr('id','barehandsBenchmark'),calib:byAttr('id','barehandsCalibrate'),
        section:byAttr('id',BAREHANDS.SECTION.benchmark)};
      const off=await BAREHANDS.benchmark();
      await BAREHANDS.enable();await settle();
      const noCamera=await BAREHANDS.benchmark();
      const before=JSON.stringify(server.calls);
      const d=captured.deps;
      const keys=Object.keys(d).sort();
      d.onRunStart();
      const opened=BAREHANDS.benchmarkState();
      const seam=BAREHANDS.measureSeam();
      d.onRunEnd('fini');
      const released=BAREHANDS.benchmarkState();
      const plan=window.JarvisBarehandsBenchmark.generatePlan(5);
      const runner=d.createRunner(plan);
      runner.start(0);
      for(let t=16;t<3000;t+=16)runner.frame({t,hands:[],contacts:[],events:[]});
      const listed=await d.store.list();
      captured.flow.open();
      const busy=await BAREHANDS.calibrate();
      const state=BAREHANDS.benchmarkState();
      const exited=BAREHANDS.exitOverlay();
      const after=BAREHANDS.benchmarkState();
      const focus=await d.calibrate('hold_release');
      out({panel:{bench:!!panel.bench,benchClass:panel.bench&&panel.bench.className,
          calibClass:panel.calib&&panel.calib.className,section:!!panel.section},
        off,noCamera,keys,opened,seam,released,layout:runner.layout().viewportClass,runnerState:runner.state().phase,
        listed,fetched,busy,state,exited,after,focus,
        writes:JSON.parse(before).length===server.calls.length?[]:server.calls.slice(JSON.parse(before).length)
          .filter(c=>c.body!==null&&!String(c.path).endsWith('/calibration-session')),
        served:require('fs').readFileSync(SCRIPT_PATH,'utf8').includes('>Tester…</button>')});
    """, name="benchpage")

    assert result["panel"]["bench"] is True and result["panel"]["section"] is True
    assert "primary" not in result["panel"]["benchClass"], "Tester a un bouton à contour"
    assert "primary" in result["panel"]["calibClass"], "Calibrer garde le bouton plein"
    assert result["served"] is True
    assert result["off"]["ok"] is False and result["off"]["code"] == "barehands_benchmark_lifecycle_off"
    assert result["noCamera"]["ok"] is False and result["noCamera"]["code"] == "barehands_benchmark_no_camera"
    # Aucune porte d'écriture dans ce que la page confie au flux.
    for banned in ("save", "saveSettings", "saveProfile", "trials", "settings", "profile", "persist", "apply"):
        assert banned not in result["keys"], banned
    assert "store" in result["keys"] and "createRunner" in result["keys"]
    assert result["opened"]["measuring"] is True and result["opened"]["keptAwake"] is True
    assert "benchmark" in result["seam"]
    assert result["released"]["measuring"] is False and result["released"]["keptAwake"] is False
    assert result["layout"] == "vp100" and result["runnerState"] in ("live", "gap")
    assert result["listed"] == {"results": [], "skipped": 0, "max": 20}
    # La liste relue par le magasin, puis à l'ouverture de l'accueil : des
    # lectures seulement, sur la route des résumés.
    assert result["fetched"] == [["/api/barehands/benchmarks", "GET"]] * 2
    assert result["busy"]["ok"] is False and result["busy"]["code"] == "barehands_flow_busy"
    assert "Le test est déjà à l’écran. Quittez-le" in result["busy"]["reason"]
    assert result["state"]["open"] is True and result["state"]["screen"] == "start"
    assert result["exited"] == {"ok": True, "flow": "benchmark", "closed": True}
    assert result["after"]["open"] is False and result["after"]["keptAwake"] is False
    # La calibration conseillée passe par la porte de la calibration, avec ses refus.
    assert result["focus"]["ok"] is False and result["focus"]["code"] == "barehands_calibration_no_camera"
    assert result["writes"] == [], "le test n'écrit ni réglage, ni profil, ni essai"


def test_the_page_focuses_the_calibration_on_the_advised_exercise_by_skipping_with_a_reason(tmp_path):
    """`startCalibrationAt` : la calibration s'ouvre par sa porte, puis chaque
    écran avant l'exercice conseillé est passé par la porte publique
    `skip('later')` — la raison est rangée, rien n'est enregistré. Exercé sur
    le vrai parcours (double de DOM de la calibration), avec la même boucle
    que la page."""

    source = SCRIPT.read_text(encoding="utf-8")
    start = source.index("async function startCalibrationAt(stage){")
    body = source[start:source.index("\n  }\n", start) + 4]
    assert "flow.skip('later')" in body
    assert "startCalibration()" in body
    assert "save" not in body.replace("enregistrez", ""), "la porte ne sauve rien"

    from test_barehands_calibration_js import run_node as run_calibration
    result = run_calibration(tmp_path, DOM + r"""
      const cal=K.createCalibration({overlay:K.createFlowOverlay({document,now}),now,document,
        setInterval:()=>1,clearInterval:()=>{},engineDefaults:B.DEFAULTS,
        pinchChannel:(c,h)=>B.createPinchChannel(c,{}),wakeDetector:()=>B.createWakeDetector({}),
        viewport:()=>({width:1280,height:720}),save:async()=>{saves+=1}});
      let saves=0;
      cal.start();
      let skipped=0;const stage='hold_release';
      while(cal.isRunning()&&cal.stepId()!==stage&&skipped<=C.STAGES.length){
        const passed=cal.skip('later');if(!passed||passed.ok!==true)break;skipped+=1;
      }
      out({step:cal.stepId(),skipped,reviews:cal.session().reviews.map(r=>[r.stage,r.decision,r.reason]),saves});
    """, name="focus")

    assert result["step"] == "hold_release"
    assert result["skipped"] == 3
    assert result["reviews"] == [["neutral", "skipped", "later"], ["c_pose", "skipped", "later"],
                                 ["pinch_primary", "skipped", "later"]]
    assert result["saves"] == 0


def test_the_screen_is_served_after_the_benchmark_and_before_the_pointer():
    """L'écran du test lit le banc et la page le lit : l'ordre d'insertion
    dans la page servie est donc banc → écran → pointeur."""

    html = (RUNTIME / "control_center.html").read_text(encoding="utf-8")
    server = (RUNTIME / "control_center.py").read_text(encoding="utf-8")
    bench = html.index("/*__CONTROL_CENTER_BAREHANDS_BENCHMARK_JS__*/")
    screen = html.index("/*__CONTROL_CENTER_BAREHANDS_BENCHMARK_UI_JS__*/")
    pointer = html.index("/*__CONTROL_CENTER_BAREHANDS_JS__*/")
    assert bench < screen < pointer
    assert 'BAREHANDS_BENCHMARK_UI_SCRIPT_FILE = "control_center_barehands_benchmark_ui.js"' in server
    assert "BAREHANDS_BENCHMARK_UI_SCRIPT_MARKER," in server


def test_the_history_reopens_a_past_run_and_clearing_takes_two_presses(tmp_path):
    """« Résultats précédents » liste les tests rangés du plus récent au plus
    ancien et rouvre chacun ; « Effacer tous les résultats… » demande une
    seconde pression, puis vide le magasin."""

    result = run_node(tmp_path, PAIR + """
      const a=await run({seed:21},T0),b=await run({seed:22},T0+3600e3);
      const store=memoryStore();store.saved.push({id:'a',result:a},{id:'b',result:b});
      const h=await makeFlow({store});h.flow.open();await settle();
      const startActions=stepActions(root());
      press(root(),'history');
      const runs=attrs('data-run').map(n=>n.getAttribute('data-run'));
      const title=heading();
      press(root(),'clear');
      const armed={count:store.saved.length,note:note()};
      press(root(),'clear');await settle();
      const cleared={count:store.saved.length,calls:store.calls.filter(c=>c==='clear').length,runs:attrs('data-run').length,
        actions:stepActions(root())};
      out({startActions,runs,title,armed,cleared});
    """, name="history")

    assert result["startActions"] == ["start", "history", "close"]
    assert result["title"] == "Tests enregistrés"
    assert result["runs"] == ["b", "a"], "du plus récent au plus ancien"
    assert result["armed"]["count"] == 2 and "Appuyez de nouveau" in result["armed"]["note"]
    assert result["cleared"]["count"] == 0 and result["cleared"]["calls"] == 1
    assert result["cleared"]["runs"] == 0
    assert "clear" not in result["cleared"]["actions"]

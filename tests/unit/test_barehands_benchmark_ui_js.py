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
  /* `skew` avance l'horloge du moteur vue par le flux sans faire tourner la
     caméra (une longue pause, une échéance). */
  const time={skew:0};
  flow=U.createBenchmarkFlow({document,overlay,now:()=>clock,engineNow:()=>rig.now()+time.skew,
    setInterval:(fn,ms)=>{timers.push({fn,ms});return timers.length},clearInterval:id=>{if(timers[id-1])timers[id-1]=null},
    viewport:()=>vp,seed:()=>opts.seed===undefined?7:opts.seed,calibrationSteps:K.STEPS,
    createRunner:opts.createRunner?plan=>opts.createRunner(plan,realRunner):realRunner,
    canStart:opts.canStart,
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
  return {flow,rig,events,overlay,store,vp,step,time,frames:()=>frames,
    timers:()=>timers.filter(Boolean).length,
    beat:()=>{for(const t of timers.slice())if(t)t.fn()},
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
      const kicker=()=>find(root(),'jf-kicker')[0].children[0].textContent;
      const meta=()=>deadlineText(root());
      const brief={screen:h.flow.screen(),title:heading(),running:h.flow.running(),events:keepAwake(h),
        actions:stepActions(root()),note:note(),kicker:kicker(),deadline:meta()[1]};
      const kinds={},texts=[shown()];let movingXs=[];let lastExercise=-1;
      let previews=0,starPreviews=0;
      for(let i=0;i<12000&&h.flow.running();i+=1){
        h.step();
        const st=h.flow.state();
        if(h.flow.screen()!=='run'||!st)continue;
        if(st.exerciseIndex!==lastExercise){lastExercise=st.exerciseIndex;texts.push(shown())}
        const key=st.kind+(st.mode?':'+st.mode:'')+(st.step!==null&&st.step!==undefined?':'+st.step:'');
        const d=drawn();
        if(d&&d.some(n=>n.preview==='1'))previews+=1;
        if(d&&d.some(n=>n.star&&n.preview==='1'))starPreviews+=1;
        if(d&&d.length&&!kinds[key])kinds[key]={nodes:d,note:note()};
        if(st.kind==='moving_target'&&st.phase==='live'&&d){const s=d.find(n=>n.star);if(s)movingXs.push(s.left)}
      }
      await settle();
      const rows=attrs('data-dimension').map(n=>[n.getAttribute('data-dimension'),n.getAttribute('data-score'),n.getAttribute('data-weak')]);
      const order=deep(root()).filter(n=>n.getAttribute&&(n.getAttribute('data-dimension')||n.getAttribute('data-global')))
        .map(n=>n.getAttribute('data-dimension')?'dim':'global');
      out({opened,start,brief,kinds,previews,starPreviews,moving:[...new Set(movingXs)].length,
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
    assert brief["kicker"] == "Exercice 1 sur 6", "une seule numérotation : l'exercice"
    assert brief["deadline"] == "", "pas de « n s restantes » : le compte à rebours de la consigne suffit"
    assert "6 essais" in brief["note"]

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
    assert result["starPreviews"] > 20, "sur les étoiles aussi, pas seulement sur la fenêtre"

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
    # En mots d'utilisateur : ni « POST … → 500 », ni le message technique.
    assert result["listFailed"]["status"][0][1] == (
        "Résultats précédents indisponibles : le serveur n’a pas pu ranger ou relire les résultats.")
    assert result["listFailed"]["actions"] == ["start", "close"], "une liste illisible n'empêche pas de tester"
    assert result["saveFailed"][0][:2] == ["failed", "bad"]
    assert result["saveFailed"][0][2] == (
        "Résultat non enregistré : le serveur n’a pas pu ranger ou relire les résultats. Réessayez l’enregistrement.")
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
/* `gate.open` simule un moteur qui a sa caméra : la porte réelle de la page
   (`canStart`) est consultée sinon. */
const gate={open:false};
global.JarvisBarehandsBenchmarkUi=Object.assign({},UIreal,{createBenchmarkFlow:deps=>{
  captured.deps=deps;
  captured.flow=UIreal.createBenchmarkFlow(Object.assign({},deps,{canStart:()=>gate.open?{ok:true}:deps.canStart()}));
  return captured.flow}});
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
    assert result["busy"]["reason"] == (
        "Le test est déjà à l’écran. Fermez-le (croix en haut à droite, touche Échap, ou « ferme la surimpression ») "
        "avant de lancer la calibration.")
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


# ------------------------------------------------------------------ reprise QA

#: Un déroulé factice qui ne finit jamais : un essai d'acquisition, figé.
FAKE_RUNNER = r"""
const FROZEN=Object.freeze({phase:'live',t:0,exerciseRef:'ex-1',kind:'target_acquisition',trial:1,trials:6,mode:null,
  step:null,stars:[],frame:null,destination:null,aimSpot:null,preview:[],exercises:6,exerciseIndex:0});
const neverEnding=()=>({start:()=>FROZEN,frame:()=>FROZEN,done:()=>false,dropTolerancePx:()=>48,state:()=>FROZEN});
/* Un déroulé réel dont on garde chaque image reçue. */
const recorded=[];
const recording=(plan,real)=>{const r=real(plan);return Object.assign({},r,{frame:f=>{recorded.push(f);return r.frame(f)}})};
"""


def test_the_screen_models_weakness_the_capped_global_and_the_default_partner(tmp_path):
    """Les modèles purs : faible sous 60 (et pas sous 40), global « limité »
    quand le plafond a joué, partenaire par défaut = le plus récent
    comparable **avant**, sinon le plus récent comparable ; la présélection ne
    lit que le canal primaire d'un essai en cours ; un score qui repose sur
    zéro événement le dit."""

    result = run_node(tmp_path, PAIR + """
      const fake=score=>({dimensions:Object.fromEntries(C.BENCHMARK_DIMENSIONS.map(n=>[n,{score,metrics:[]}])),
        global:{score:null,unmeasured:[],weakest:null,capped:false},result:{exercises:[]}});
      const weak=s=>U.dimensionRows(fake(s),K.STEPS)[0].weak;
      const perfect=await run({user:null,seed:5},T0);
      const rows=U.dimensionRows(BM.scoreResult(perfect),K.STEPS);
      const later=Object.assign(JSON.parse(JSON.stringify(perfect)),{runAt:T0+3600e3});
      const target={id:'t',result:perfect};
      out({w45:weak(45),w59:weak(59),w60:weak(60),
        capped:U.globalLine({global:{score:70,capped:true,weakest:'reactivity',unmeasured:[]}}).text,
        uncapped:U.globalLine({global:{score:70,capped:false,weakest:'reactivity',unmeasured:[]}}).text,
        partner:(U.defaultPartner(target,[{id:'later',result:C.createBenchmarkResult(later)}])||{}).id||null,
        preview:BM.previewOf([{channel:'primary',key:'o:bench:t1'},{channel:'secondary',key:'o:bench:t2'},
          {channel:'primary',key:null},{channel:'primary',key:'o:bench:t1'}],true),
        previewGap:BM.previewOf([{channel:'primary',key:'o:bench:t1'}],false),
        falsePositive:rows.find(r=>r.dimension==='false_positive_resistance'),
        acquisition:rows.find(r=>r.dimension==='acquisition').noEvents});
    """, name="models")

    assert result["w45"] is True and result["w59"] is True and result["w60"] is False
    assert "limité par la dimension la plus faible (Réactivité)" in result["capped"]
    assert "limité" not in result["uncapped"]
    assert result["partner"] == "later", "sans test antérieur, le plus récent comparable"
    assert result["preview"] == ["t1"], "le canal primaire seul, sans doublon"
    assert result["previewGap"] == []
    fp = result["falsePositive"]
    assert fp["noEvents"] is True, "l'utilisateur de contrôle ne déclenche rien : 100 repose sur zéro événement"
    assert any("aucun événement mesuré" in m["text"] for m in fp["metrics"])
    assert result["acquisition"] is False


def test_a_dimension_verdict_never_contradicts_its_score(tmp_path):
    """Reprise QA : « Atteinte · amélioré · 46 → 34 ». Une métrique améliorée
    ne suffit plus : si une autre recule (même sans preuve) ou si le score de
    la dimension recule au-delà de la marge, « pas de conclusion », avec la
    raison et la métrique en cause à l'écran."""

    result = run_node(tmp_path, PAIR + """
      const base=await run({seed:31},T0);
      /* Avant : des acquisitions deux fois plus lentes. Après : rapides, mais
         la moitié des essais de sélection arrivés à leur échéance. */
      const remake=(r,fn,runAt)=>{const c=JSON.parse(JSON.stringify(r));c.runAt=runAt;
        for(const e of c.exercises){fn(e);for(const name of Object.keys(e.samples))e.metrics[name]=BM.statOf(name,e.samples[name])}
        return C.createBenchmarkResult(c)};
      const before=remake(base,e=>{if(e.samples.acquisition_ms)e.samples.acquisition_ms=e.samples.acquisition_ms.map(v=>Math.round(v*2.2))},T0);
      const after=remake(base,e=>{if(e.samples.timeout_count)e.samples.timeout_count=e.samples.timeout_count.map((v,i)=>i%2?1:0)},T0+3600e3);
      const cmp=BM.compareResults(before,after);
      const all=[];
      for(const [a,b] of [[base,after]])for(const name of C.BENCHMARK_DIMENSIONS)all.push(cmp.dimensions[name]);
      const rows=U.comparisonRows(cmp);
      out({acq:{verdict:cmp.dimensions.acquisition.verdict,reason:cmp.dimensions.acquisition.reason,
          against:cmp.dimensions.acquisition.against,delta:cmp.dimensions.acquisition.delta,
          metrics:cmp.dimensions.acquisition.metrics.map(m=>[m.metric,m.verdict])},
        row:rows.find(r=>r.dimension==='acquisition'),
        consistent:all.every(d=>d.verdict!=='improved'||(d.delta===null||d.delta>-BM.PRACTICAL_MARGIN))
          &&all.every(d=>d.verdict!=='regressed'||(d.delta===null||d.delta<BM.PRACTICAL_MARGIN)),
        texts:Object.values(U.INCONCLUSIVE_TEXT)});
    """, name="contradiction")

    acq = result["acq"]
    assert dict(acq["metrics"])["acquisition_ms"] == "improved"
    assert acq["verdict"] == "inconclusive", acq
    assert acq["reason"] in ("metrics_disagree", "contradicts_score", "metric_against")
    row = result["row"]
    assert row["verdict"] == "inconclusive" and row["reason"] == acq["reason"]
    assert "Relancez le test" in row["text"]
    assert result["consistent"] is True


def test_turning_bare_hands_off_or_resizing_mid_run_stops_it_and_saves_nothing(tmp_path):
    """Reprise QA : Bare Hands éteint pendant le run (la page appelle
    `abort`), ou la fenêtre qui change de classe ou rétrécit : le run s'arrête,
    l'écran dit pourquoi, rien n'est rangé, le moteur est rendu. Une fenêtre
    qui grandit dans la même classe ne change rien."""

    result = run_node(tmp_path, """
      const h=await makeFlow();h.flow.open();await settle();press(root(),'start');
      await h.until(()=>h.flow.screen()==='run',400);
      const aborted=h.flow.abort('barehands_benchmark_lifecycle_off','Bare Hands a été éteint pendant le test.');
      for(let i=0;i<200;i+=1)h.step();
      await settle();
      const off={aborted,screen:h.flow.screen(),events:keepAwake(h),saved:h.store.saved.length,
        alert:attrs('data-failure').map(n=>[n.getAttribute('data-failure'),n.textContent]),
        level:h.events.filter(e=>Array.isArray(e)&&e[1]==='barehands.benchmark_aborted').map(e=>e[0])};
      h.flow.exit('fermer');
      const vp={width:1280,height:720};
      const g=await makeFlow({viewport:vp});g.flow.open();await settle();press(root(),'start');
      await g.until(()=>g.flow.screen()==='run',400);
      vp.width=1400;vp.height=760;           // plus grande, même classe : on continue
      for(let i=0;i<30;i+=1)g.step();
      const grown=g.flow.screen();
      vp.width=1100;vp.height=620;           // autre classe : on arrête
      g.step();
      await settle();
      const shrunk={screen:g.flow.screen(),events:keepAwake(g),saved:g.store.saved.length,text:shown(),
        alert:attrs('data-failure').map(n=>[n.getAttribute('data-failure'),n.textContent])};
      g.flow.exit('fermer');
      /* Même classe, mais plus petite que la fenêtre du tirage. */
      const vp2={width:1400,height:760};
      const s=await makeFlow({viewport:vp2});s.flow.open();await settle();press(root(),'start');
      vp2.width=1300;
      s.step();
      const same={screen:s.flow.screen(),code:(s.flow.failure()||{}).code};
      out({off,grown,shrunk,same});
    """, name="offresize")

    off = result["off"]
    assert off["aborted"] is True and off["screen"] == "failed"
    assert off["events"] == ["runStart", "runEnd:panne"]
    assert off["saved"] == 0, "un run arrêté ne range jamais de résultat"
    assert off["alert"][0][0] == "barehands_benchmark_lifecycle_off"
    assert "éteint" in off["alert"][0][1]
    assert off["level"] == ["warn"], "une extinction voulue n'est pas une panne"
    assert result["grown"] == "run"
    shrunk = result["shrunk"]
    assert shrunk["screen"] == "failed" and shrunk["saved"] == 0
    assert shrunk["events"] == ["runStart", "runEnd:panne"]
    assert shrunk["alert"][0][0] == "barehands_benchmark_viewport_changed"
    assert "1280 × 720 → 1100 × 620" in shrunk["alert"][0][1], "la fenêtre du tirage, pas une intermédiaire"
    assert "Relancez le test" in shrunk["alert"][0][1]
    assert shrunk["text"].count("Rien n’a été enregistré") + shrunk["text"].count("Rien n’est enregistré") == 1,         "une seule fois à l'écran"
    assert result["same"] == {"screen": "failed", "code": "barehands_benchmark_viewport_changed"}


def test_the_start_screen_follows_the_window_and_keeps_the_refusal_visible(tmp_path):
    """L'accueil suit la fenêtre (il restait sur sa première taille), et un
    refus se lit en premier, sans défiler."""

    result = run_node(tmp_path, """
      const vp={width:1280,height:720};
      const h=await makeFlow({viewport:vp});h.flow.open();await settle();
      const before=[attrs('data-viewport')[0].getAttribute('data-viewport'),stepActions(root())];
      vp.width=1000;vp.height=540;h.beat();
      const page=deep(root()).find(n=>String(n.className||'')==='jb-page');
      const after=[attrs('data-viewport')[0].getAttribute('data-viewport'),stepActions(root()),
        page.children[0].getAttribute('data-viewport')];
      vp.width=1100;vp.height=640;h.beat();
      out({before,after,back:attrs('data-viewport')[0].getAttribute('data-viewport')});
    """, name="startresize")

    assert result["before"] == ["vp100", ["start", "close"]]
    assert result["after"] == ["refused", ["recheck", "close"], "refused"], "le refus est le premier élément"
    assert result["back"] == "vp80"


def test_pause_time_never_counts_and_the_exercise_deadline_still_holds(tmp_path):
    """Reprise QA : l'échéance de 6 minutes porte sur le temps des exercices.
    Vingt minutes de pause ne tuent pas le run (un rappel doux au bout de
    cinq) ; sept minutes d'exercice sans fin, si."""

    result = run_node(tmp_path, FAKE_RUNNER + """
      const h=await makeFlow({createRunner:()=>neverEnding()});
      h.flow.open();await settle();press(root(),'start');press(root(),'ready');
      press(root(),'pause');
      h.time.skew+=6*60e3;h.beat();
      const reminded=note();
      h.time.skew+=14*60e3;h.beat();
      const paused=h.flow.screen();
      press(root(),'resume');press(root(),'ready');
      h.time.skew+=5*60e3;h.beat();
      const stillRunning=h.flow.screen();
      h.time.skew+=2*60e3;h.beat();
      out({reminded,paused,stillRunning,end:h.flow.screen(),code:(h.flow.failure()||{}).code,events:keepAwake(h)});
    """, name="deadline")

    assert "Toujours en pause" in result["reminded"]
    assert result["paused"] == "paused"
    assert result["stillRunning"] == "run", "la pause n'a pas été comptée"
    assert result["end"] == "failed" and result["code"] == "barehands_benchmark_run_timeout"
    assert result["events"] == ["runStart", "runEnd:panne"]


def test_the_runner_sees_one_continuous_clock_on_hands_events_and_frames(tmp_path):
    """Après une pause, les temps des mains **et** des événements de pincement
    reçoivent le même décalage que l'image ; la fin d'une consigne ne pousse
    pas d'image vide pour le temps de lecture ; une consigne sépare chaque
    exercice ; la progression avance."""

    result = run_node(tmp_path, FAKE_RUNNER + """
      const h=await makeFlow({createRunner:recording});
      h.flow.open();await settle();press(root(),'start');
      await h.until(()=>h.flow.screen()==='run',400);
      for(let i=0;i<60;i+=1)h.step();
      press(root(),'pause');for(let i=0;i<60;i+=1)h.step();
      press(root(),'resume');for(let i=0;i<20;i+=1)h.step();
      const before=recorded.length;
      press(root(),'ready');h.beat();
      const pushedOnReady=recorded.length-before;
      const cut=recorded.length;
      const screens=[];let last=null,progress=0;
      for(let i=0;i<12000&&h.flow.running();i+=1){
        h.step();
        if(h.flow.screen()!==last){last=h.flow.screen();screens.push(last)}
        const bar=find(root(),C.DOM.flowProgressClass)[0];
        if(bar)progress=Math.max(progress,Number(bar.children[0].getAttribute('data-at')));
      }
      const after=recorded.slice(cut);
      const handsOk=after.filter(f=>f.hands.length).every(f=>f.hands.every(x=>x.t===f.t));
      const withEvents=after.filter(f=>f.events.length);
      const eventsOk=withEvents.every(f=>f.events.every(e=>e.t===null||(e.t<=f.t+1&&e.t>=f.t-500)));
      out({pushedOnReady,handsOk,events:withEvents.length,eventsOk,briefs:screens.filter(s=>s==='brief').length,progress});
    """, name="clock")

    assert result["pushedOnReady"] == 0, "aucune image vide pour le temps de lecture"
    assert result["handsOk"] is True
    assert result["events"] > 5 and result["eventsOk"] is True
    assert result["briefs"] >= 5, "une consigne avant chaque exercice suivant"
    assert result["progress"] > 0.8


def test_a_late_save_updates_in_place_and_an_unsaved_result_survives_browsing(tmp_path):
    """Reprise QA : un enregistrement qui aboutit tard ne redessine pas le
    rapport (les mesures dépliées restent dépliées) ; un résultat non rangé
    survit à la navigation dans l'historique et garde « Réessayer » ; une
    liste relue recalcule un partenaire qui n'est plus rangé."""

    result = run_node(tmp_path, PAIR + """
      const store=memoryStore();
      const early=await run({seed:41},T0);store.saved.push({id:'early',result:C.createBenchmarkResult(early)});
      let release=null;
      const realSave=store.save;
      store.save=r=>new Promise((ok,ko)=>{release={ok:()=>ok(realSave(r)),ko:()=>ko(Object.assign(new Error('POST /api/barehands/benchmarks → 500'),{code:'barehands_benchmark_store_failed'}))}});
      const h=await makeFlow({store});h.flow.open();await settle();press(root(),'start');
      await h.toReport();
      const toggle=deep(root()).find(n=>n.getAttribute&&n.getAttribute('data-details')==='acquisition');
      toggle.fire('click');
      release.ko();await settle();
      const sameToggle=deep(root()).find(n=>n.getAttribute&&n.getAttribute('data-details')==='acquisition');
      const kept={same:sameToggle===toggle,expanded:sameToggle.getAttribute('aria-expanded'),
        save:attrs('data-save').map(n=>n.textContent)[0],actions:stepActions(root())};
      press(root(),'history');
      const listed=attrs('data-run').map(n=>n.getAttribute('data-run'));
      deep(root()).find(n=>n.getAttribute&&n.getAttribute('data-run')==='early').fire('click');
      press(root(),'history');
      deep(root()).find(n=>n.getAttribute&&n.getAttribute('data-run')==='unsaved').fire('click');
      const reopened={actions:stepActions(root()),save:attrs('data-save').map(n=>n.getAttribute('data-save'))[0]};
      press(root(),'save');release.ok();await settle();
      const done={save:attrs('data-save').map(n=>n.getAttribute('data-save'))[0],unsaved:h.flow.unsaved(),count:store.saved.length};
      /* Le partenaire n'est plus rangé (un autre onglet a effacé) : la liste
         relue le recalcule. */
      const before=attrs('data-compare-teaser')[0].getAttribute('data-partner');
      store.saved.splice(store.saved.findIndex(e=>e.id==='early'),1);
      await h.flow.reload();await settle();
      const partnerAfter=attrs('data-compare-teaser')[0].getAttribute('data-partner');
      out({kept,listed,reopened,done,before,partnerAfter});
    """, name="latesave")

    kept = result["kept"]
    assert kept["same"] is True and kept["expanded"] == "true", "le rapport n'a pas été redessiné"
    assert "POST" not in kept["save"] and "→ 500" not in kept["save"]
    assert kept["actions"][0] == "save"
    assert result["listed"][0] == "unsaved"
    assert result["reopened"] == {"actions": result["reopened"]["actions"], "save": "failed"}
    assert result["reopened"]["actions"][0] == "save"
    assert result["done"]["save"] == "saved" and result["done"]["unsaved"] is None
    assert result["done"]["count"] == 2
    assert result["before"] == "early"
    assert result["partnerAfter"] == "none"


def test_a_non_comparable_partner_is_explained_and_exit_stops_the_watchdog(tmp_path):
    """Comparer à un test d'une autre taille de fenêtre : « ne se comparent
    pas », sans verdicts. Et fermer arrête la montre du flux."""

    result = run_node(tmp_path, PAIR + """
      const base=await run({seed:51},T0);
      const small=JSON.parse(JSON.stringify(base));small.viewport={width:1100,height:640,scale:4};small.runAt=T0+60e3;
      const store=memoryStore();store.saved.push({id:'base',result:C.createBenchmarkResult(base)},
        {id:'small',result:C.createBenchmarkResult(small)});
      const h=await makeFlow({store});h.flow.open();await settle();
      h.flow.showReport(store.saved[0]);
      h.flow.showCompare(store.saved[1]);
      const nc={notice:attrs('data-not-comparable').map(n=>[n.getAttribute('data-not-comparable'),n.textContent]),
        verdicts:attrs('data-verdict').length};
      const running=h.timers();
      h.flow.exit('fermer');
      out({nc,running,after:h.timers()});
    """, name="noncomparable")

    assert result["nc"]["notice"][0][0] == "viewport"
    assert "ne se comparent pas : une autre taille de fenêtre" in result["nc"]["notice"][0][1]
    assert result["nc"]["verdicts"] == 0
    assert result["after"] == result["running"] - 1, "la montre du flux s'arrête avec lui"


#: La calibration réelle, dont la fabrique est enveloppée pour tenir le
#: parcours que la page construit (et le démarrer sans caméra).
CAL_SETUP = r"""
const CALreal=global.JarvisBarehandsCalibration;
const capturedCal={};
/* Les démonstrations de main de la calibration sont des SVG. */
global.document.createElementNS=(ns,tag)=>global.document.createElement(tag);
global.JarvisBarehandsCalibration=Object.assign({},CALreal,{createCalibration:deps=>{
  capturedCal.deps=deps;capturedCal.flow=CALreal.createCalibration(deps);return capturedCal.flow}});
"""


def test_the_page_ends_a_run_when_bare_hands_goes_off_and_never_turns_the_camera_on(tmp_path):
    """Sur la vraie page (le double de navigateur n'a pas de MediaPipe : le
    moteur y est « en panne » dès l'allumage) :

    - la porte d'entrée réelle refuse un run sans caméra (`no_camera`) et,
      Bare Hands éteint, refuse « Relancer le test » (`lifecycle_off`) **sans
      rien allumer** — la caméra reste éteinte ;
    - la porte ouverte (simulée), un run pose la couture et l'éveil **sur le
      moteur** sans réveiller un moteur qui n'est pas en veille ; éteindre
      Bare Hands pendant le run l'arrête, rien n'est rangé, les deux sont
      rendus ; `onClose` seul les rend aussi ;
    - le profil mesuré se dit « usine », « essai » ou « enregistrés »."""

    result = run_browser(tmp_path, CAMERA + browser(PAGE_SETUP + CAL_SETUP) + TIMERS + """
      await openTab();
      await BAREHANDS.enable();await settle();
      const d=captured.deps||(await BAREHANDS.benchmark(),captured.deps);
      const flow=captured.flow;
      flow.open();await settle();
      const lifeBefore=BAREHANDS.lifecycleStatus().lifecycle;
      /* 1. La porte réelle : moteur en panne → refus, écran inchangé. */
      const noCamera=flow.start();
      const afterNoCamera=flow.screen();
      /* 2. Porte ouverte (un moteur qui aurait sa caméra) : le run part. */
      gate.open=true;
      const started=flow.start();
      await settle();
      const during={state:BAREHANDS.benchmarkState(),seam:BAREHANDS.measureSeam(),
        life:BAREHANDS.lifecycleStatus().lifecycle,screen:flow.screen()};
      await BAREHANDS.disable();await settle();
      const afterOff={state:BAREHANDS.benchmarkState(),screen:flow.screen(),
        failure:flow.failure(),seam:BAREHANDS.measureSeam(),
        posts:fetched.filter(f=>f[1]==='POST').length};
      /* 3. « Relancer le test » depuis l'interruption, éteint : refusé, rien
         ne s'allume. */
      gate.open=false;
      const refusedOff=flow.start();await settle();
      const offCheck={life:BAREHANDS.lifecycleStatus().lifecycle,enabled:BAREHANDS.state().enabled,
        screen:flow.screen(),engine:BAREHANDS.benchmarkState().engine};
      /* `onClose` seul (sans fin de run) rend la couture et l'éveil. */
      d.onRunStart();
      const reopened=BAREHANDS.benchmarkState().engine;
      const offAfterSeam=BAREHANDS.lifecycleStatus().lifecycle;
      d.onClose('fermeture');
      const closed=BAREHANDS.benchmarkState().engine;
      /* La source du profil mesuré. */
      const sourceOf=()=>{const plan=window.JarvisBarehandsBenchmark.generatePlan(3);const r=d.createRunner(plan);
        logged.length=0;r.start(0);const line=logged.find(l=>l[1].includes('benchmark_started'));
        return line?JSON.parse(line[1].slice(line[1].indexOf('{'))).profileSource:null};
      const defaults=sourceOf();
      const trial=BAREHANDS.adapters.trials.apply({releaseMs:90});
      const underTrial=sourceOf();
      BAREHANDS.adapters.trials.discard('test');
      await settle();
      await BAREHANDS.settings({assistance:.9});await settle();
      const saved=sourceOf();
      out({lifeBefore,noCamera,afterNoCamera,started,during,afterOff,refusedOff,offCheck,reopened,offAfterSeam,closed,
        defaults,trialOk:trial&&trial.ok,underTrial,saved});
    """, name="benchoff")

    assert result["lifeBefore"] == "error"
    assert result["noCamera"]["code"] == "barehands_benchmark_no_camera"
    assert result["afterNoCamera"] == "start", "un refus ne change pas d'écran"
    assert result["started"]["ok"] is True
    during = result["during"]
    assert during["state"]["running"] is True, during
    assert during["state"]["engine"] == {"onMeasure": True, "keepAwake": True}, "posés sur le moteur"
    assert "benchmark" in during["seam"]
    assert during["life"] == "error", "un moteur qui n'est pas en veille n'est pas réveillé"
    off = result["afterOff"]
    assert off["screen"] == "failed"
    assert off["failure"]["code"] == "barehands_benchmark_lifecycle_off"
    assert off["state"]["running"] is False
    assert off["state"]["engine"] == {"onMeasure": False, "keepAwake": False}, "rendus au moteur"
    assert "benchmark" not in off["seam"]
    assert off["posts"] == 0, "rien n'est rangé"
    assert result["refusedOff"]["code"] == "barehands_benchmark_lifecycle_off"
    assert result["offCheck"] == {"life": "off", "enabled": False, "screen": "failed",
                                  "engine": {"onMeasure": False, "keepAwake": False}}, "la caméra reste éteinte"
    assert result["reopened"] == {"onMeasure": True, "keepAwake": True}
    assert result["offAfterSeam"] == "off", "poser l'éveil n'allume jamais depuis Éteint"
    assert result["closed"] == {"onMeasure": False, "keepAwake": False}
    assert result["defaults"] == "defaults"
    assert result["trialOk"] is True and result["underTrial"] == "trial"
    assert result["saved"] == "saved"


def test_the_page_refuses_the_test_during_a_calibration_and_its_button_says_why(tmp_path):
    """La calibration ouverte refuse le test (et le dit dans ses mots) ; le
    bouton « Tester… » de l'onglet appelle la porte et suit l'état de Bare
    Hands (grisé éteint, actif allumé)."""

    result = run_browser(tmp_path, CAMERA + browser(PAGE_SETUP + CAL_SETUP) + TIMERS + """
      await openTab();
      const tester=()=>byAttr('id','barehandsBenchmark');
      tester().fire('click');await settle();
      const clickedOff=logged.filter(l=>l[1].includes('test refusé')).map(l=>l[1]);
      await BAREHANDS.enable();await settle();
      await renderTab();await settle();
      const enabledState=tester().disabled;
      await BAREHANDS.disable();await settle();
      const disabledState=tester().disabled;
      await BAREHANDS.enable();await settle();
      await BAREHANDS.calibrate();
      capturedCal.flow.start();
      const busy=await BAREHANDS.benchmark();
      out({clickedOff,enabledState,disabledState,busy});
    """, name="benchbusy")

    assert any("barehands_benchmark_lifecycle_off" in line for line in result["clickedOff"]), \
        "le bouton appelle la porte du test"
    assert result["enabledState"] is False
    assert result["disabledState"] is True
    assert result["busy"]["ok"] is False and result["busy"]["code"] == "barehands_flow_busy"
    assert result["busy"]["reason"] == (
        "La calibration est déjà à l’écran. Quittez-la (bouton « Quitter », touche Échap, ou « ferme la "
        "surimpression ») avant de lancer le test.")


def test_every_rerun_goes_through_the_entry_gate(tmp_path):
    """Reprise QA, round 3 : « Commencer », « Relancer le test » depuis le
    rapport, l'avant/après ou l'interruption passent tous par la porte
    d'entrée de la page (`canStart`). Refusé : l'écran ne change pas, la
    ligne du bas dit pourquoi, rien n'est tenu éveillé."""

    result = run_node(tmp_path, """
      const gate={ok:true};
      const h=await makeFlow({canStart:()=>gate.ok?{ok:true}:{ok:false,code:'barehands_benchmark_lifecycle_off',
        reason:'Bare Hands est éteint : choisissez Veille ou Actif.'}});
      h.flow.open();await settle();
      gate.ok=false;
      press(root(),'start');
      const fromStart={screen:h.flow.screen(),note:note(),events:keepAwake(h)};
      gate.ok=true;press(root(),'start');
      await h.toReport();
      gate.ok=false;
      press(root(),'rerun');
      const fromReport={screen:h.flow.screen(),note:note(),events:keepAwake(h)};
      const abortOutsideRun=h.flow.abort('x','y');
      gate.ok=true;press(root(),'rerun');
      h.flow.abort('barehands_benchmark_lifecycle_off','Bare Hands a été éteint pendant le test.');
      gate.ok=false;
      const fromFailed=[h.flow.screen()];
      press(root(),'restart');
      fromFailed.push(h.flow.screen(),note());
      out({abortOutsideRun,fromStart,fromReport,fromFailed,runs:keepAwake(h).filter(e=>e==='runStart').length,
        refused:h.events.filter(e=>Array.isArray(e)&&e[1]==='barehands.benchmark_start_refused').length});
    """, name="gate")

    assert result["fromStart"] == {"screen": "start", "note": "Bare Hands est éteint : choisissez Veille ou Actif.",
                                   "events": []}
    assert result["fromReport"]["screen"] == "report" and "éteint" in result["fromReport"]["note"]
    assert result["abortOutsideRun"] is False, "abort hors run ne fait rien"
    assert result["fromFailed"][:2] == ["failed", "failed"] and "éteint" in result["fromFailed"][2]
    assert result["runs"] == 2, "seuls les runs que la porte a laissés passer sont partis"
    assert result["refused"] == 3


def test_the_page_sends_what_the_calibration_replaces_and_shows_it_the_saved_profile(tmp_path):
    """La page passe `replaces` sur le fil (clés au nom du fil) et donne au
    parcours le profil enregistré pour le rapport « avant → après »."""

    result = run_browser(tmp_path, CAMERA + browser(PAGE_SETUP + CAL_SETUP) + TIMERS + """
      await openTab();
      await BAREHANDS.enable();await settle();
      await BAREHANDS.calibrate();
      const d=capturedCal.deps;
      const saved=d.savedProfile(),view=BAREHANDS.profile();
      await d.save({schemaVersion:3,updatedAt:1800000000000,hands:{right:{pressRatio:.3,releaseRatio:.45}},
        stages:{pinch_primary:{status:'ok',reason:null,samples:4}},
        replaces:{hands:{right:['pressRatio','releaseRatio']},stages:['pinch_primary']}});
      out({sameAsView:saved!==null&&saved===view,written:server.profileWrites[server.profileWrites.length-1]});
    """, name="calwire")

    assert result["sameAsView"] is True
    written = result["written"]
    assert written["replaces"] == {"hands": {"right": ["press_ratio", "release_ratio"]}, "stages": ["pinch_primary"]}
    assert written["hands"]["right"]["press_ratio"] == 0.3
    assert set(written["stages"]) == {"pinch_primary"}


def test_keep_awake_never_turns_a_switched_off_engine_on(tmp_path):
    """Audit de la reprise QA (round 3), pour la calibration comme pour le
    test : la dépendance d'éveil ne réveille qu'un moteur **en veille**.
    Allumé puis éteint avec `keepAwake` vrai, le moteur reste éteint et ne
    redemande pas la caméra."""

    result = run_node(tmp_path, """
      let asked=0,now=0;const frames=new Map();let id=0;
      const deps={options:{},handOverrides:()=>null,
        getUserMedia:async()=>{asked+=1;return {getTracks:()=>[],getVideoTracks:()=>[]}},
        createLandmarker:async()=>({detectForVideo:()=>({landmarks:[]}),close(){}}),
        attachVideo:async()=>({element:{},width:480,height:480,currentTime:()=>now,dispose(){}}),
        overlay:{mount(){},unmount(){},render(){},watch(){},showDiagnostics(){}},
        interaction:{hover(){},click(){},clear(){},takeClicks:()=>[]},
        requestFrame:fn=>{const k=++id;frames.set(k,fn);return k},cancelFrame:k=>{frames.delete(k)},
        now:()=>now,viewport:()=>({width:1280,height:720}),keepAwake:()=>true,onStatus(){}};
      const ctl=B.createController(deps);
      const tick=n=>{for(let i=0;i<n;i+=1){now+=33;const p=[...frames.values()];frames.clear();p.forEach(f=>f())}};
      await ctl.enable();await settle();tick(10);
      const awake=ctl.state();
      await ctl.disable();await settle();
      const before=asked;
      tick(60);await settle();
      out({awake,off:ctl.state(),askedAfterOff:asked-before});
    """, name="keepawake")

    assert result["awake"] in ("active", "running"), "en veille, l'éveil réveille (c'est son rôle)"
    assert result["off"] == "off"
    assert result["askedAfterOff"] == 0, "éteint, rien ne redemande la caméra"


def test_a_deliberate_sleep_ends_the_open_calibration_or_test_and_says_so(tmp_path):
    """Slice 10 (résidu de la QA de la Slice 07) : un parcours ouvert tient le
    moteur éveillé (`keepAwake`), donc une mise en veille **demandée** (bouton,
    voix, `JarvisBarehands.sleep()`) était défaite à l'image suivante. La
    veille demandée gagne : elle ferme d'abord le parcours par sa sortie
    ordinaire (rien d'enregistré), le dit, rend l'éveil, puis endort."""

    result = run_browser(tmp_path, CAMERA + browser(PAGE_SETUP + CAL_SETUP) + TIMERS + """
      await openTab();
      const subs=[];const baseToast=global.toast;global.toast=t=>{subs.push(t&&t.sub);baseToast(t)};
      await BAREHANDS.enable();await settle();
      await BAREHANDS.calibrate();
      capturedCal.flow.start();
      const calibrating=[capturedCal.flow.isRunning(),BAREHANDS.benchmarkState().engine.keepAwake];
      logged.length=0;toasts.length=0;subs.length=0;
      await BAREHANDS.sleep();await settle();
      const afterCal={running:capturedCal.flow.isRunning(),keepAwake:BAREHANDS.benchmarkState().engine.keepAwake,
        seam:BAREHANDS.measureSeam(),toasts:toasts.slice(),sub:subs.slice(-1)[0],
        logged:logged.some(l=>l[1].includes('barehands.sleep_ends_flow'))};
      /* Avec un essai en cours : la phrase dit qu'il est défait, et il l'est. */
      await BAREHANDS.activate();await settle();
      await BAREHANDS.calibrate();capturedCal.flow.start();
      const applied=BAREHANDS.adapters.trials.apply({releaseMs:90});
      subs.length=0;
      await BAREHANDS.sleep();await settle();
      const withTrial={applied:!!(applied&&applied.ok),sub:subs.slice(-1)[0],
        active:BAREHANDS.adapters.trials.status().active};
      /* Le test, maintenant : un run ouvert par la porte, puis la veille. */
      const d=captured.deps||(await BAREHANDS.benchmark(),captured.deps);
      const flow=captured.flow;flow.open();await settle();
      gate.open=true;flow.start();await settle();
      const running=BAREHANDS.benchmarkState().running;
      toasts.length=0;
      await BAREHANDS.sleep();await settle();
      const afterTest={running:BAREHANDS.benchmarkState().running,engine:BAREHANDS.benchmarkState().engine,
        toasts:toasts.slice(),posts:fetched.filter(f=>f[1]==='POST'&&String(f[0]).includes('benchmarks')).length};
      /* Rien d'ouvert : la veille ne dit rien de plus. */
      toasts.length=0;await BAREHANDS.sleep();await settle();
      out({calibrating,afterCal,withTrial,running,afterTest,idle:toasts.slice()});
    """, name="sleepwins")

    assert result["calibrating"][0] is True
    after = result["afterCal"]
    assert after["running"] is False, "la calibration est fermée par la veille demandée"
    assert after["keepAwake"] is False and "calibration" not in after["seam"]
    assert after["toasts"] == ["info"] and after["logged"] is True
    assert "essai" not in after["sub"], "sans essai, la phrase n'en promet pas l'annulation"
    trial = result["withTrial"]
    assert trial["applied"] is True
    assert "l’essai en cours est défait" in trial["sub"] and trial["active"] is False
    assert result["running"] is True
    test = result["afterTest"]
    assert test["running"] is False and test["engine"] == {"onMeasure": False, "keepAwake": False}
    assert test["toasts"] == ["info"] and test["posts"] == 0
    assert result["idle"] == []


def test_the_profile_panel_lists_only_what_calibrates_and_names_the_metrics_apart(tmp_path):
    """Slice 10 (décision 39 : pas de lecteur, pas de calibration) : sous
    « Calibré », une main ne liste que les clés qu'un lecteur du moteur
    applique ; tremblement, portée et qualité sont dites **à part**, comme des
    mesures sans effet sur le moteur."""

    result = run_browser(tmp_path, CAMERA + browser(PAGE_SETUP + CAL_SETUP) + TIMERS + """
      await openTab();
      server.profile={...server.profile,hands:{left:{},unknown:{},right:{press_ratio:.3,release_ratio:.45,
        jitter_px:2.5,quality:.8}},stages:{},updated_at:1800000000000};
      await BAREHANDS.enable();await settle();
      await BAREHANDS.calibrate();
      const d=capturedCal.deps;
      await d.save({schemaVersion:3,updatedAt:1800000000000,hands:{right:{pressRatio:.3,releaseRatio:.45}},
        stages:{pinch_primary:{status:'ok',reason:null,samples:4}},
        replaces:{hands:{right:['pressRatio','releaseRatio']},stages:['pinch_primary']}});
      await settle();await renderTab();await settle();
      const panel=byAttr('id','barehandsProfile');
      out({html:panel?panel.innerHTML:null});
    """, name="profilepanel")

    html = result["html"]
    assert html and "Calibré" in html
    main = html.split('<span data-metrics-only="1">')[0]
    assert "seuil de pincement" in main
    assert "tremblement au repos" not in main and "qualité de la mesure" not in main
    assert "sans effet sur le moteur" in html and "tremblement au repos" in html

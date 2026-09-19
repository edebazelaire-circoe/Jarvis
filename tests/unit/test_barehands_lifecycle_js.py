"""Cycle de vie OFF/SLEEP/ACTIVE et réveil en C (Slice 02), exécutés par node.

Une posture devant une caméra ne se teste pas ici. Ce qui l'est : la lecture du
« C » de réveil et ce qu'elle refuse (pincement, poing, main ouverte), le
maintien d'une seconde qui s'accumule, se garde à travers un trou du traqueur
puis retombe, les transitions dans les deux sens — allumage vers la veille,
réveil par la posture, réveil et mise en veille par l'interface, retour en
veille après 30 s sans main — le budget d'images du guetteur, et la libération
de la caméra sur **tous** les chemins d'arrêt, voulus comme subis.

L'horloge est injectée : aucune attente réelle, aucun minuteur.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
SCRIPT = RUNTIME / "control_center_barehands.js"
CONTRACTS = RUNTIME / "control_center_barehands_contracts.js"


def run_node(tmp_path: Path, source: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "barehands-lifecycle.cjs"
    script.write_text(
        f"const B=require({json.dumps(str(SCRIPT))});\n"
        f"const C=require({json.dumps(str(CONTRACTS))});\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


#: Main synthétique. Paume de 0,2 (poignet 0,5/0,8 → base du majeur 0,5/0,6) ;
#: l'index pointe vers le haut à `reach` paumes du poignet, le pouce est à
#: `gap` paumes du bout de l'index. Un C tient dans ces deux nombres.
HAND = """
function hand(gap,reach=1.8){
  const lm=Array.from({length:21},()=>({x:.5,y:.5,z:0}));
  lm[0]={x:.5,y:.8,z:0};lm[9]={x:.5,y:.6,z:0};
  lm[8]={x:.5,y:.8-.2*reach,z:0};
  lm[4]={x:.5+.2*gap,y:lm[8].y,z:0};
  return lm;
}
const C_POSE={landmarks:[hand(.65)]},NO_HAND={landmarks:[]};
"""

#: Monde injecté : horloge, vidéo, caméra, surimpression et boucle d'images
#: sont des doubles. `step(ms)` avance le temps d'un cran et déclenche les
#: rappels d'animation en attente ; rien n'attend réellement.
WORLD = HAND + """
function world(opts){
  const o=opts||{};
  const log=[],frames=new Map();let frameId=0,detections=0;
  const state={now:0,videoTime:0,result:o.result||NO_HAND,frozen:false,throws:false};
  const track={stopped:false,listeners:{},
    addEventListener(k,fn){this.listeners[k]=fn},stop(){this.stopped=true;log.push('track.stop')}};
  const stream={getTracks:()=>[track],getVideoTracks:()=>[track]};
  const deps={
    options:o.options||{},
    getUserMedia:async()=>{log.push('camera.open');return stream},
    createLandmarker:async()=>{log.push('model.load');
      return {detectForVideo:()=>{detections+=1;if(state.throws)throw new Error('suivi mort');return state.result},
              close(){log.push('model.close')}}},
    /* Caméra carrée : les distances sont isotropes, donc la main synthétique
       se mesure comme dans les tests de `cPoseScore`, sans facteur d'aspect. */
    attachVideo:async()=>({element:{},width:480,height:480,
      currentTime:()=>state.videoTime,dispose(){log.push('video.dispose')}}),
    overlay:{mount(){log.push('overlay.mount')},unmount(){log.push('overlay.unmount')},
      render(t){log.push('render:'+t.length)},
      watch(w){log.push('watch:'+(w?(w.present?'1':'0')+':'+w.progress.toFixed(2):'off'))}},
    interaction:{hover(){},click(){log.push('click')},clear(){log.push('hover.clear')}},
    requestFrame:fn=>{const id=++frameId;frames.set(id,fn);return id},
    cancelFrame:id=>{frames.delete(id);log.push('frame.cancel')},
    now:()=>state.now,viewport:()=>({width:100,height:100}),
    onStatus:s=>log.push('status:'+s.state+':'+s.code),
  };
  const step=ms=>{state.now+=(ms===undefined?16:ms);if(!state.frozen)state.videoTime+=1;
    const pending=[...frames.values()];frames.clear();pending.forEach(fn=>fn())};
  const steps=(n,ms)=>{for(let i=0;i<n;i+=1)step(ms)};
  return {deps,log,track,state,step,steps,frames,seen:()=>detections};
}
"""


# --------------------------------------------------------------- posture en C


def test_the_wake_posture_is_a_c_and_nothing_else(tmp_path):
    """Décision 5 : le réveil est un pré-pincement tenu. Un pincement en cours,
    un poing et une main ouverte doivent tous marquer zéro, sinon la veille se
    réveille toute seule dès qu'une main passe."""

    result = run_node(tmp_path, HAND + """
      const score=(gap,reach)=>B.cPoseScore(hand(gap,reach),1);
      out({
        c:score(.65),wide:score(.75),tight:score(.55),
        pinch:score(.2),pinching:score(.4),fist:score(.65,1),open:score(1.3),
        unusable:[B.cPoseScore([],1),B.cPoseScore(null,1),
                  B.cPoseScore(Array.from({length:21},()=>({x:.3,y:.3})),1)],
        scaleFree:score(.65)===B.cPoseScore(hand(.65).map(p=>({x:.5+(p.x-.5)/3,y:.5+(p.y-.5)/3,z:0})),1),
      });
    """)
    assert result["c"] == 1 and result["wide"] == 1 and result["tight"] == 1
    # Sous `wakeGapMin` : c'est le pincement, qui a son propre rôle.
    assert result["pinch"] == 0 and result["pinching"] == 0
    # Index replié : un poing dont l'écart pouce-index tombe dans la bande.
    assert result["fist"] == 0
    assert result["open"] == 0
    # Main absente ou aplatie : pas de score, pas de réveil.
    assert result["unusable"] == [None, None, None]
    # Mesuré en paumes : une main deux fois plus loin donne le même score.
    assert result["scaleFree"] is True


def test_the_band_that_actually_sustains_a_hold_is_the_one_documented(tmp_path):
    """`wakeGapMin`/`wakeGapMax`/`wakeIndexMin` sont les **zéros du score**, pas
    les seuils de réveil : les plages s'adoucissent sur `wakeSoft` et il faut
    tenir `wakeScore`. Le commit de la Slice 02, le contrat et le LOG citaient
    les zéros — 10 % d'erreur sur la portée, dans les nombres mêmes que la
    Slice 08 doit calibrer. Balayage contre forme close, puis contre le
    tableau publié."""

    result = run_node(tmp_path, HAND + """
      const D=B.DEFAULTS;
      const s=(D.wakeGapMax-D.wakeGapMin)*D.wakeSoft;
      const closed={gapMin:D.wakeGapMin+s*D.wakeScore,gapMax:D.wakeGapMax-s*D.wakeScore,
                    reachMin:D.wakeIndexMin*(1+D.wakeSoft*D.wakeScore)};
      const sustains=(gap,reach)=>B.cPoseScore(hand(gap,reach),1)>=D.wakeScore;
      let lo=null,hi=null;
      for(let g=.30;g<1.20;g+=1e-4)if(sustains(g,2.5)){if(lo===null)lo=g;hi=g}
      let reach=null;
      for(let r=1.0;r<2.5;r+=1e-4)if(sustains(.65,r)){reach=r;break}
      out({closed,measured:{gapMin:lo,gapMax:hi,reachMin:reach},
           /* Juste dedans compte, juste dehors ne compte pas : la bande est
              bien une frontière, pas une coïncidence de pas de balayage. */
           edges:[sustains(closed.gapMin+1e-6,2.5),sustains(closed.gapMin-1e-3,2.5),
                  sustains(closed.gapMax-1e-6,2.5),sustains(closed.gapMax+1e-3,2.5),
                  sustains(.65,closed.reachMin+1e-6),sustains(.65,closed.reachMin-1e-3)],
           /* Les zéros ne soutiennent rien : c'est tout le propos. */
           atZeroCrossings:[sustains(D.wakeGapMin,2.5),sustains(D.wakeGapMax,2.5),
                            sustains(.65,D.wakeIndexMin)]});
    """)
    band = (
        round(result["measured"]["gapMin"], 3),
        round(result["measured"]["gapMax"], 3),
        round(result["measured"]["reachMin"], 3),
    )
    assert band == (0.499, 0.811, 1.485)
    for key in ("gapMin", "gapMax", "reachMin"):
        assert result["measured"][key] == pytest.approx(result["closed"][key], abs=1e-4), key
    assert result["edges"] == [True, False, True, False, True, False]
    assert result["atZeroCrossings"] == [False, False, False]
    # La bande publiée est celle-là, en toutes lettres : un défaut qui bouge
    # sans que le tableau bouge fait tomber ce test avant la Slice 08.
    contract = (ROOT / "docs" / "barehands-contracts.md").read_text(encoding="utf-8")
    assert "0,499 à 0,811 paume" in contract
    assert "≥ 1,485 paume" in contract


def test_the_wake_hold_accumulates_survives_a_gap_and_resets(tmp_path):
    """Le maintien compte le temps où la posture est tenue *d'affilée*. Un trou
    court est un raté du traqueur et se pardonne ; un trou long remet à zéro."""

    result = run_node(tmp_path, """
      const d=B.createWakeDetector({wakeHoldMs:1000,wakeGraceMs:400});
      const hold=[];
      for(const t of [0,200,400,600,800,1000,1200])hold.push(d.update(1,t));
      const after=d.update(1,1400);
      const gap=B.createWakeDetector({wakeHoldMs:1000,wakeGraceMs:400});
      gap.update(1,0);gap.update(1,200);
      const tolerated=gap.update(0,400);       // un trou : la progression tient
      const resumed=gap.update(1,600);
      const credited=gap.update(1,800);        // la posture tenue recompte
      const lost=[gap.update(0,1000),gap.update(0,1600)];  // 600 ms sans posture
      const again=gap.update(1,1800);
      out({
        progress:hold.map(h=>Number(h.progress.toFixed(2))),
        fired:hold.map(h=>h.wake),
        onlyOnce:after.wake,
        tolerated:Number(tolerated.progress.toFixed(2)),
        resumed:Number(resumed.progress.toFixed(2)),
        credited:Number(credited.progress.toFixed(2)),
        lost:lost.map(l=>Number(l.progress.toFixed(2))),
        again:Number(again.progress.toFixed(2)),
      });
    """)
    # La première mesure ne crédite rien : une posture qui apparaît ne gagne pas
    # le temps passé sans elle.
    assert result["progress"] == [0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.0]
    assert result["fired"] == [False, False, False, False, False, True, False]
    assert result["onlyOnce"] is False
    # Le trou garde l'acquis (200 ms), mais ne le crédite pas : le temps sans
    # posture n'est jamais compté, et la mesure qui reprend repart de là.
    assert result["tolerated"] == 0.2 and result["resumed"] == 0.2
    assert result["credited"] == 0.4
    # Au-delà de la tolérance, la progression tombe et le réveil redevient possible.
    assert result["lost"] == [0.4, 0.0]
    assert result["again"] == 0.0


def test_a_watcher_slower_than_its_own_grace_is_refused_at_construction(tmp_path):
    """N-A. Le guetteur n'appelle le détecteur qu'une fois par
    `wakeIntervalMs` : le `dt` que voit `createWakeDetector` **est** cette
    cadence. Au-delà de `wakeGraceMs`, chaque mesure arrive après un trou plus
    long que la grâce, le maintien repart de zéro à chaque image et la posture
    en C ne peut plus jamais aboutir — 0 ms crédité sur dix secondes de C
    parfait, sans erreur, sans trace et sans test rouge (tous les tests de
    réveil passent la cadence en surcharge explicite).

    `options()` tenait déjà deux invariants de paire de cette forme
    (`pressRatio < releaseRatio`, `wakeGapMin < wakeGapMax`) ; voici le
    troisième. Le cas limite `interval === grace` reste permis : un trou
    **égal** à la grâce n'est pas au-delà."""

    result = run_node(tmp_path, WORLD + """
      // `options()` n'est pas exporté : on l'atteint par la fabrique qui
      // l'appelle, c'est-à-dire par le chemin qu'emprunte vraiment le réglage.
      const refused=opts=>{try{B.createWakeDetector(opts);return null}catch(e){return e.name}};
      // Le mécanisme, mesuré sur le détecteur seul : des mesures espacées de
      // plus que la grâce ne créditent rien, quelle que soit la posture.
      const starved=B.createWakeDetector({wakeHoldMs:1000,wakeGraceMs:400});
      let held=0;
      for(let t=0;t<=10000;t+=500)held=starved.update(1,t).heldMs;
      // Et le refus, à la construction plutôt qu'au premier C tenu en vain.
      const shipping=refused({wakeIntervalMs:200,wakeGraceMs:400});
      const equal=refused({wakeIntervalMs:400,wakeGraceMs:400});
      const slower=refused({wakeIntervalMs:500,wakeGraceMs:400});
      const tighterGrace=refused({wakeIntervalMs:200,wakeGraceMs:100});
      let message='';
      try{B.createWakeDetector({wakeIntervalMs:500,wakeGraceMs:400})}catch(e){message=e.message}
      // Un contrôleur ne se construit pas non plus sur un réglage impossible.
      let controller=null;
      try{B.createController(world({options:{wakeIntervalMs:500,wakeGraceMs:400}}).deps)}
      catch(e){controller=e.name}
      out({held,shipping,equal,slower,tighterGrace,controller,
           names:['wakeIntervalMs','wakeGraceMs'].map(k=>message.includes(k)),
           defaults:[B.DEFAULTS.wakeIntervalMs,B.DEFAULTS.wakeGraceMs]});
    """)
    # Dix secondes de posture parfaite, échantillonnées plus lentement que la
    # grâce : rien n'est crédité. C'est la panne silencieuse que l'invariant
    # rend impossible à configurer.
    assert result["held"] == 0
    # Le réglage d'usine et le cas limite passent ; au-delà, refus.
    assert result["shipping"] is None and result["equal"] is None
    assert result["slower"] == "RangeError" and result["tighterGrace"] == "RangeError"
    assert result["controller"] == "RangeError"
    # Le message nomme les deux réglages : un refus qui ne dit pas quoi changer
    # se contourne en remettant l'autre nombre au hasard.
    assert result["names"] == [True, True]
    # Et le défaut livré respecte l'invariant qu'il vient de poser.
    assert result["defaults"] == [200, 400]
    assert result["defaults"][0] <= result["defaults"][1]


def test_a_watcher_sampling_exactly_at_its_grace_still_wakes(tmp_path):
    """Le cas limite, de bout en bout : `wakeIntervalMs === wakeGraceMs` est le
    réglage le plus lent qui reste légal, et il doit encore réveiller. Un
    invariant trop strict (`<` au lieu de `<=`) refuserait un réglage qui
    marche ; trop lâche, il laisse passer celui qui ne marche jamais."""

    result = run_node(tmp_path, WORLD + """
      const w=world({result:C_POSE,options:{wakeIntervalMs:400,wakeHoldMs:1000,wakeGraceMs:400}});
      const c=B.createController(w.deps);
      await c.enable();
      const progress=[];
      for(let i=0;i<5;i+=1){w.step(400);progress.push(w.log.filter(l=>l.startsWith('watch:')).pop())}
      out({state:c.state(),progress,woken:w.log.includes('status:active:woken')});
    """)
    # Quatre mesures consécutives : 0, 400, 800 puis 1200 ms — le maintien
    # aboutit, et l'anneau s'est bien rempli en chemin plutôt que de sauter.
    assert result["progress"][:3] == ["watch:1:0.00", "watch:1:0.40", "watch:1:0.80"]
    assert result["state"] == "active" and result["woken"] is True


def test_a_gap_between_two_samples_is_time_nobody_observed(tmp_path):
    """Le trou entre deux mesures n'est pas du maintien : c'est du temps que
    personne n'a regardé. `dt` était du temps mural non borné, si bien que deux
    mesures tenues à 60 s d'écart validaient la seconde de maintien — une
    caméra figée (le guetteur sort avant d'appeler ici), un onglet en
    arrière-plan ou un écran rabattu faisaient entrer en interaction sur une
    seule image vaguement en C, et l'anneau de la décision 5 sautait de 0 à
    100 % sans jamais se dessiner."""

    result = run_node(tmp_path, WORLD + """
      const far=B.createWakeDetector({wakeHoldMs:1000,wakeGraceMs:400});
      const before=far.update(1,0);
      const after=far.update(1,60000);            // deux mesures, 60 s d'écart
      /* Ni en une fois, ni en tranches : cinq mesures tenues, chacune au-delà
         de la tolérance, ne créditent toujours rien. */
      const sliced=B.createWakeDetector({wakeHoldMs:1000,wakeGraceMs:400});
      const slices=[0,401,802,1203,1604].map(t=>Number(sliced.update(1,t).progress.toFixed(2)));
      /* Un trou ne met pas le maintien en pause : il le perd. 600 ms acquises,
         un gel, puis la posture revient — le compte repart de zéro. */
      const resumed=B.createWakeDetector({wakeHoldMs:1000,wakeGraceMs:400});
      for(const t of [0,200,400,600])resumed.update(1,t);
      const stalled=resumed.update(1,60000);
      const next=resumed.update(1,60200);
      /* Le même trou vu du contrôleur : caméra figée en veille, posture en C
         avant et après. L'anneau continue de dire la vérité pendant le gel. */
      const w=world({result:C_POSE,options:{wakeIntervalMs:200,wakeHoldMs:1000,wakeGraceMs:400}});
      const c=B.createController(w.deps);
      await c.enable();
      w.steps(4,200);                             // 600 ms de posture tenue
      const held=w.log.filter(l=>l.startsWith('watch:')).pop();
      const mark=w.log.length;
      w.state.frozen=true;w.steps(300,200);       // 60 s d'horloge, aucune image neuve
      const during=w.log.slice(mark).filter(l=>l.startsWith('watch:'));
      w.state.frozen=false;w.step(200);           // une image en bande, 60 s plus tard
      out({before:before.progress,
           after:{progress:after.progress,wake:after.wake,heldMs:after.heldMs},
           slices,stalled:stalled.progress,next:Number(next.progress.toFixed(2)),
           held,frozenWatches:during.length,frozenLast:during[during.length-1],
           state:c.state(),woke:w.log.includes('status:active:woken'),
           ring:w.log.filter(l=>l.startsWith('watch:')).pop()});
    """)
    # Deux mesures tenues à 60 s d'écart : rien de crédité, aucun réveil.
    assert result["before"] == 0
    assert result["after"] == {"progress": 0, "wake": False, "heldMs": 0}
    assert result["slices"] == [0.0, 0.0, 0.0, 0.0, 0.0]
    # Le trou perd l'acquis au lieu de le mettre en pause.
    assert result["stalled"] == 0 and result["next"] == 0.2
    # Contrôleur : 600 ms tenues avant le gel…
    assert result["held"] == "watch:1:0.60"
    # … pendant le gel l'anneau est tenu à jour et retombe, au lieu de rester
    # figé sur une progression que plus rien n'alimente.
    assert result["frozenWatches"] == 300
    assert result["frozenLast"] == "watch:0:0.00"
    # … et l'image d'après le gel ouvre un maintien neuf, elle ne le conclut pas.
    assert result["state"] == "sleep" and result["woke"] is False
    assert result["ring"] == "watch:1:0.00"


# ------------------------------------------------------------- transitions


def test_turning_barehands_on_lands_in_sleep_not_in_interaction(tmp_path):
    """Décision 4 : allumer, c'est guetter. Rien n'interagit tant que
    l'utilisateur n'a pas réveillé."""

    result = run_node(tmp_path, WORLD + """
      const w=world();const c=B.createController(w.deps);
      const state=await c.enable();
      w.steps(3,16);
      out({state,lifecycle:C.lifecycleOfControllerState(state),log:w.log,
           clicked:w.log.includes('click'),rendered:w.log.some(l=>l.startsWith('render:'))});
    """)
    assert result["state"] == "sleep" and result["lifecycle"] == "sleep"
    assert result["log"][:4] == ["status:starting:starting", "model.load", "camera.open", "overlay.mount"]
    assert "status:sleep:sleep" in result["log"]
    # La veille ne survole pas, ne clique pas et ne pose aucun jeton.
    assert result["clicked"] is False and result["rendered"] is False


def test_holding_the_c_pose_wakes_and_interaction_starts(tmp_path):
    result = run_node(tmp_path, WORLD + """
      const w=world({result:C_POSE,options:{wakeIntervalMs:200,wakeHoldMs:1000,wakeGraceMs:400}});
      const c=B.createController(w.deps);
      await c.enable();
      w.steps(5,200);
      const before=c.state();
      const progress=w.log.filter(l=>l.startsWith('watch:1')).pop();
      w.step(200);
      const after=c.state();
      out({before,progress,after,woken:w.log.includes('status:active:woken'),
           lifecycle:[C.lifecycleOfControllerState(before),C.lifecycleOfControllerState(after)]});
    """)
    # Cinq mesures : la posture est tenue depuis 800 ms, pas encore une seconde.
    assert result["before"] == "sleep" and result["progress"] == "watch:1:0.80"
    assert result["after"] == "active" and result["woken"] is True
    assert result["lifecycle"] == ["sleep", "active"]


def test_a_c_pose_released_too_early_never_wakes(tmp_path):
    result = run_node(tmp_path, WORLD + """
      const w=world({result:C_POSE,options:{wakeIntervalMs:200,wakeHoldMs:1000,wakeGraceMs:400}});
      const c=B.createController(w.deps);
      await c.enable();
      for(let i=0;i<4;i+=1){w.step(200)}
      w.state.result=NO_HAND;w.steps(4,200);      // posture relâchée
      w.state.result=C_POSE;w.steps(3,200);       // reprise : le compte repart
      out({state:c.state(),last:w.log.filter(l=>l.startsWith('watch:')).pop()});
    """)
    assert result["state"] == "sleep"
    # Trois mesures après la reprise : 400 ms des 1000 exigées.
    assert result["last"] == "watch:1:0.40"


def test_the_ui_control_activates_and_sleeps_in_both_directions(tmp_path):
    """Décision 4 : un bouton doit pouvoir activer et désactiver, sans geste."""

    result = run_node(tmp_path, WORLD + """
      const w=world();const c=B.createController(w.deps);
      await c.enable();
      const awake=await c.activate();
      w.state.result={landmarks:[hand(.2)]};   // main pincée : interaction vivante
      w.step(16);
      const rendered=w.log.some(l=>l.startsWith('render:'));
      const asleep=c.sleep();
      const fromOff=world();const c2=B.createController(fromOff.deps);
      const direct=await c2.activate();        // depuis OFF : allume puis réveille
      out({awake,rendered,asleep,direct,
           statuses:w.log.filter(l=>l.startsWith('status:')),
           camera:fromOff.log.includes('camera.open')});
    """)
    assert result["awake"] == "active" and result["asleep"] == "sleep"
    assert result["rendered"] is True
    # Activer depuis OFF allume la caméra avant d'interagir.
    assert result["direct"] == "active" and result["camera"] is True
    assert result["statuses"] == [
        "status:starting:starting", "status:sleep:sleep", "status:active:active", "status:sleep:sleep",
    ]


def test_thirty_seconds_without_a_usable_hand_returns_to_sleep(tmp_path):
    """Décision 7. Une main vue réarme le délai ; une caméra figée ne doit pas
    laisser l'interaction active pour toujours."""

    result = run_node(tmp_path, WORLD + """
      const w=world({result:{landmarks:[hand(.2)]},options:{sleepTimeoutMs:30000}});
      const c=B.createController(w.deps);
      await c.enable();await c.activate();
      w.steps(60,1000);                       // une main vue chaque seconde
      const kept=c.state();
      w.state.result=NO_HAND;
      w.steps(29,1000);
      const still=c.state();
      w.step(1000);
      const slept=c.state();
      const frozen=world({result:{landmarks:[hand(.2)]},options:{sleepTimeoutMs:30000}});
      const c2=B.createController(frozen.deps);
      await c2.enable();await c2.activate();
      frozen.state.frozen=true;               // la vidéo ne bouge plus
      frozen.steps(31,1000);
      out({kept,still,slept,frozenState:c2.state(),
           idle:w.log.includes('status:sleep:idle_sleep'),camera:w.track.stopped});
    """)
    assert result["kept"] == "active" and result["still"] == "active"
    assert result["slept"] == "sleep" and result["idle"] is True
    assert result["frozenState"] == "sleep"
    # Le retour en veille garde la caméra : c'est SLEEP, pas OFF.
    assert result["camera"] is False


# --------------------------------------------------------- budget de la veille


def test_sleep_runs_a_fraction_of_the_inferences_that_interaction_runs(tmp_path):
    """SLEEP est un état de fond, caméra ouverte : son coût est l'inférence
    MediaPipe, donc elle est cadencée. ACTIVE suit chaque image."""

    result = run_node(tmp_path, WORLD + """
      /* Aucune surcharge : c'est la **cadence par défaut** qui est promise à
         l'écran et dans le contrat, donc c'est elle qu'il faut couvrir. Passée
         en argument, muter le défaut 200 → 500 ne faisait rien tomber. */
      const asleep=world();
      const c=B.createController(asleep.deps);
      await c.enable();asleep.steps(60,16);
      const awake=world();
      const c2=B.createController(awake.deps);
      await c2.enable();await c2.activate();awake.steps(60,16);
      out({sleep:asleep.seen(),active:awake.seen(),state:[c.state(),c2.state()],
           interval:B.DEFAULTS.wakeIntervalMs});
    """)
    # 60 images à 16 ms = 960 ms : cinq inférences à 5 images/s, contre une par
    # image en interaction.
    assert result["sleep"] == 5
    assert result["active"] == 60
    assert result["interval"] == 200
    assert result["state"] == ["sleep", "active"]


# ------------------------------------------------------- libération de caméra


def test_every_stop_path_releases_the_camera(tmp_path):
    """La caméra ne doit fuir par aucun chemin : arrêt depuis la veille, arrêt
    depuis l'interaction, échec du suivi dans l'un ou l'autre état."""

    result = run_node(tmp_path, WORLD + """
      const paths={};
      const check=w=>({stopped:w.track.stopped,
        released:['model.close','video.dispose','overlay.unmount'].every(k=>w.log.includes(k)),
        frames:w.frames.size});
      const fromSleep=world();const a=B.createController(fromSleep.deps);
      await a.enable();fromSleep.step(16);a.disable();
      paths.sleep={...check(fromSleep),state:a.state()};
      const fromActive=world({result:{landmarks:[hand(.2)]}});const b=B.createController(fromActive.deps);
      await b.enable();await b.activate();fromActive.step(16);b.disable();
      paths.active={...check(fromActive),state:b.state()};
      const sleepFails=world();const d=B.createController(sleepFails.deps);
      await d.enable();sleepFails.state.throws=true;sleepFails.step(16);
      paths.sleepError={...check(sleepFails),state:d.state(),
        code:sleepFails.log.filter(l=>l.startsWith('status:')).pop()};
      const activeFails=world({result:{landmarks:[hand(.2)]}});const e=B.createController(activeFails.deps);
      await e.enable();await e.activate();activeFails.state.throws=true;activeFails.step(16);
      paths.activeError={...check(activeFails),state:e.state(),
        code:activeFails.log.filter(l=>l.startsWith('status:')).pop()};
      out(paths);
    """)
    for name in ("sleep", "active", "sleepError", "activeError"):
        path = result[name]
        assert path["stopped"] is True, name
        assert path["released"] is True, name
        assert path["frames"] == 0, name
    assert result["sleep"]["state"] == "off" and result["active"]["state"] == "off"
    assert result["sleepError"]["state"] == "error"
    assert result["sleepError"]["code"] == "status:error:tracking_failed"
    assert result["activeError"]["state"] == "error"
    assert result["activeError"]["code"] == "status:error:tracking_failed"


def test_a_malformed_landmark_skips_a_frame_instead_of_ending_the_session(tmp_path):
    """`usableHand` promettait une validation qu'il ne faisait pas : il comptait
    les points sans les regarder. Un seul point absent faisait lever
    `cPoseScore`, que la boucle d'images convertit en `tracking_failed` —
    caméra rendue, ERROR, toast de 9 s, pour une image. Et « exploitable » se
    disait de deux façons dans le même contrôleur : 8 points pour poser un
    jeton, 9 pour le guetteur, alors que le minuteur de la décision 7 se
    réarme sur les jetons."""

    result = run_node(tmp_path, WORLD + """
      const broken=hand(.65);broken[4]=undefined;   // pouce absent
      const short=hand(.65).slice(0,9);             // pas de base du majeur
      const nan=hand(.65);nan[8]={x:NaN,y:.3,z:0};  // index sans coordonnée
      const frame={viewport:{width:100,height:100},aspect:1,now:0};
      const t=B.createHandTracker({});
      const tokens=[short,broken,nan,hand(.65)].map(lm=>t.update({landmarks:[lm]},frame).tokens.length);
      const w=world({result:{landmarks:[broken]},options:{wakeIntervalMs:200}});
      const c=B.createController(w.deps);
      await c.enable();
      w.steps(10,200);                              // dix images malformées d'affilée
      const survived=c.state();
      w.state.result=C_POSE;w.steps(6,200);         // la posture revient, le réveil marche
      out({survived,after:c.state(),woke:w.log.includes('status:active:woken'),
           usable:[hand(.65),broken,short,nan,[],null].map(B.usableLandmarks),
           scores:[B.cPoseScore(broken,1),B.cPoseScore(short,1),B.cPoseScore(nan,1)],
           ratios:[B.pinchRatio(broken,1),B.pinchRatio(nan,1)],
           tokens});
    """)
    # Une seule définition d'« exploitable », et elle regarde les entrées.
    assert result["usable"] == [True, False, False, False, False, False]
    # Les mesures refusent au lieu de lever : c'est ce qui rend l'image sautable.
    assert result["scores"] == [None, None, None] and result["ratios"] == [None, None]
    # Les jetons partagent cette définition : plus de main « exploitable » pour
    # le minuteur de veille et inexploitable pour le guetteur.
    assert result["tokens"] == [0, 0, 0, 1]
    # Dix images malformées ne coûtent ni la caméra ni la session.
    assert result["survived"] == "sleep"
    assert result["after"] == "active" and result["woke"] is True


def test_switching_off_after_a_failure_does_not_overwrite_the_cause(tmp_path):
    """`state !== OFF` disait « allumé » d'un état qui ne tient rien. Couper
    l'interrupteur depuis ERROR remplaçait donc « Caméra refusée — Autorisez la
    caméra… » par « Barehands arrêté — caméra libérée » : une phrase fausse, à
    la place de la seule information utile."""

    result = run_node(tmp_path, WORLD + """
      const w=world();
      w.deps.getUserMedia=async()=>{const e=new Error('non');e.name='NotAllowedError';throw e};
      const c=B.createController(w.deps);
      await c.enable();
      const engaged=B.isEngagedState(c.state());
      const afterError=w.log.filter(l=>l.startsWith('status:')).pop();
      const off=c.disable();        // appelé quand même : le message doit rester juste
      out({engaged,afterError,off,last:w.log.filter(l=>l.startsWith('status:')).pop(),
           live:B.isLiveState('error')});
    """)
    # Rien n'est tenu : la page n'a plus de raison d'appeler `disable()`, donc
    # la cause reste à l'écran.
    assert result["engaged"] is False and result["live"] is False
    assert result["afterError"] == "status:error:camera_denied"
    # Appelé explicitement, `disable()` dit « éteint », jamais « caméra libérée ».
    assert result["off"] == "off" and result["last"] == "status:off:off"


def test_cancelling_a_start_still_confirms_that_the_camera_was_released(tmp_path):
    """N-C. `disable()` demandait « Bare Hands **fonctionne** » (`isLiveState`)
    là où la question est « quelque chose est-il **tenu** ? » (`isEngagedState`).
    STARTING tombait donc du mauvais côté : décocher l'interrupteur pendant
    l'invite de permission émettait `off`, que la page ne notifie pas — aucun
    toast du tout.

    RÈGLE ZÉRO : la caméra est rendue de façon **asynchrone** ici, `track.stop()`
    n'arrivant qu'une fois `getUserMedia` résolu. Sans un mot à l'écran,
    l'utilisateur annule et n'a aucune confirmation que la webcam s'est éteinte.
    Une annulation est un arrêt voulu ; elle se dit. ERROR, lui, reste muet :
    c'est le cas que le correctif de la Slice 02 visait, et il ne bouge pas."""

    result = run_node(tmp_path, WORLD + """
      const w=world();
      const open=w.deps.getUserMedia;
      let unblock;
      const prompt=new Promise(r=>{unblock=r});
      // La permission est en vol : l'humain n'a pas encore répondu à l'invite.
      w.deps.getUserMedia=async c=>{await prompt;return open(c)};
      const ctrl=B.createController(w.deps);
      const starting=ctrl.enable();          // volontairement pas attendu
      // Le modèle se charge d'abord ; on laisse les micro-tâches filer jusqu'à
      // ce que le démarrage soit réellement posé sur l'invite de la caméra.
      await new Promise(r=>setImmediate(r));
      const during=ctrl.state();
      const stoppedBefore=w.track.stopped;
      const off=ctrl.disable();              // l'utilisateur décoche
      const said=w.log.filter(l=>l.startsWith('status:')).pop();
      unblock();await starting;              // la caméra arrive après coup
      out({during,off,said,stoppedBefore,stoppedAfter:w.track.stopped,
           engaged:B.isEngagedState('starting'),live:B.isLiveState('starting'),
           state:ctrl.state()});
    """)
    assert result["during"] == "starting"
    # Ce que le correctif rétablit : le mot « arrêté · caméra libérée », que la
    # page notifie, au lieu du `off` silencieux.
    assert result["off"] == "off" and result["said"] == "status:off:disabled"
    # Et la raison pour laquelle il fallait le dire : la caméra n'était pas
    # encore là au moment du clic, elle n'est rendue qu'après.
    assert result["stoppedBefore"] is False and result["stoppedAfter"] is True
    # Les deux prédicats ne répondent pas à la même question ; c'est le second
    # qui gouverne ce qu'on **rend**, donc ce qu'on annonce.
    assert result["engaged"] is True and result["live"] is False
    assert result["state"] == "off"


def test_a_broken_overlay_is_not_blamed_on_the_camera(tmp_path):
    """`teardown` enveloppait chaque appel à la surimpression, les transitions
    non : un anneau qui lève sortait sous « Suivi interrompu — caméra
    libérée », une cause inventée à la place de la vraie. L'arrêt reste le
    même, le motif devient exact."""

    result = run_node(tmp_path, WORLD + """
      const w=world();const c=B.createController(w.deps);
      await c.enable();
      w.deps.overlay.watch=()=>{throw new Error('DOM parti')};
      w.step(200);
      out({state:c.state(),last:w.log.filter(l=>l.startsWith('status:')).pop(),
           stopped:w.track.stopped,frames:w.frames.size});
    """)
    assert result["state"] == "error"
    assert result["last"] == "status:error:overlay_failed"
    # ERROR ne tient rien, quelle que soit la cause qui y mène.
    assert result["stopped"] is True and result["frames"] == 0


def test_a_camera_lost_in_sleep_is_reported_like_one_lost_in_interaction(tmp_path):
    result = run_node(tmp_path, WORLD + """
      const w=world();const c=B.createController(w.deps);
      await c.enable();
      w.track.listeners.ended();
      out({state:c.state(),last:w.log.filter(l=>l.startsWith('status:')).pop(),stopped:w.track.stopped});
    """)
    assert result["state"] == "error"
    assert result["last"] == "status:error:camera_ended"
    assert result["stopped"] is True


def test_the_idle_timer_now_reads_a_real_usable_hand_and_says_so_on_screen(tmp_path):
    """Décision 7 : 30 s **sans main exploitable** ramènent ACTIVE en veille.
    La Slice 02 a dû lire « exploitable » comme « une main quelconque », faute
    de qualité à lire, et l'a noté comme une approximation à fermer. Elle se
    ferme ici.

    Une main dont un point utile sort du cadre est une main dont le traqueur
    extrapole les points : elle tenait l'interaction éveillée indéfiniment,
    parce qu'elle produisait un jeton. Elle produit toujours un jeton — la
    masquer dirait « je ne te vois pas », ce qui est faux — mais elle ne
    réarme plus le minuteur, et l'écran le dit avant que la veille arrive :
    le jeton se dessine pâle et la pastille compte les mains crues à part."""

    result = run_node(tmp_path, WORLD + """
      const shift=(lm,dx)=>lm.map(p=>({x:p.x+dx,y:p.y,z:0}));
      /* Main ouverte, pas la posture en C : ce test mesure le **minuteur**, et
         un C ferait entrer le réveil dans la mesure. Depuis la reprise de la
         Slice 03 le guetteur lit la même qualité (voir
         `test_the_watcher_wakes_on_the_same_hand_the_idle_timer_would_keep`) ;
         une main ouverte ne réveille de toute façon jamais. */
      const clean={landmarks:[hand(1.3)]};
      const edged={landmarks:[shift(hand(1.3),.24)]};   // le pouce touche le bord

      const good=world({result:clean});
      const cg=B.createController(good.deps);
      await cg.enable();await cg.activate();
      good.steps(200,200);                              // 40 s de main franche
      const stayed=cg.state();

      const poor=world({result:edged});
      const cp=B.createController(poor.deps);
      await cp.enable();await cp.activate();
      const before=cp.state();
      poor.steps(200,200);
      const slept=cp.state();

      // Le jeton existe dans les deux cas : c'est la confiance qui diffère.
      const t=B.createHandTracker({});
      const f=now=>({viewport:{width:100,height:100},aspect:1,now});
      const seenClean=t.update(clean,f(0)).tokens[0];
      const u=B.createHandTracker({});
      const seenEdged=u.update(edged,f(0)).tokens[0];
      out({stayed,before,slept,
           reason:poor.log.filter(l=>l.startsWith('status:')).pop(),
           quality:[seenClean.quality,seenEdged.quality],
           counted:[B.usableQuality(seenClean.quality),B.usableQuality(seenEdged.quality)],
           tokens:[!!seenClean,!!seenEdged],
           features:cp.features().length});
    """)
    assert result["stayed"] == "active", "une main franche doit tenir l'interaction éveillée"
    assert result["before"] == "active"
    assert result["slept"] == "sleep"
    assert result["reason"] == "status:sleep:idle_sleep"
    # Les deux mains portent un jeton ; une seule des deux compte.
    assert result["tokens"] == [True, True]
    assert result["counted"] == [True, False]
    assert result["quality"][0] > result["quality"][1]
    # Les traits ne survivent pas à l'interaction qu'ils décrivent.
    assert result["features"] == 0


def test_the_watcher_wakes_on_the_same_hand_the_idle_timer_would_keep(tmp_path):
    """R4 : la décision 7 était fermée d'un côté et rouverte de l'autre. Le
    minuteur d'ACTIVE se réarme sur `usableQuality` ; le guetteur de la veille,
    lui, ne lisait que les points, jamais la qualité. Une main que
    l'interaction refuse pouvait donc la **démarrer**.

    Le cycle mesuré, sur une main de qualité 0,125 tenant un C à 0,93 :
    `active` → 30 s → `sleep:idle_sleep` → réveillée une seconde plus tard →
    30 s → … sans fin. Chaque tour appelle `interaction.clear()` et
    `tracker.reset()` : toutes les identités détruites, toutes les fentes de
    pointeur réallouées, deux pastilles par tour. Le commentaire de
    `usableQuality` affirmait déjà **une** définition partagée ; il y en avait
    deux. C'est le commentaire qu'on a rendu vrai, pas l'inverse : une
    définition plus large côté veille ne peut produire que ce cycle.

    La main refusée **reste dessinée**, et l'anneau n'avance pas : l'écran dit
    « je te vois » et « ça ne prend pas », au lieu de la faire disparaître
    (RÈGLE ZÉRO)."""

    result = run_node(tmp_path, WORLD + """
      // Le C de la Slice 02, déplacé jusqu'à ce que le pouce frôle le bord
      // droit : la posture est intacte (elle ne se mesure qu'en distances),
      // la qualité tombe sous le plancher.
      const shift=(lm,dx)=>lm.map(p=>({x:p.x+dx,y:p.y,z:0}));
      const edgedC={landmarks:[shift(hand(.65),.365)]};

      const poor=world({result:edgedC});
      const cp=B.createController(poor.deps);
      await cp.enable();
      poor.steps(300,200);                     // 60 s de guet, deux cycles possibles
      const asleep=cp.state();
      const statuses=poor.log.filter(l=>l.startsWith('status:'));

      // Témoin : la même posture bien cadrée réveille toujours.
      const good=world({result:C_POSE});
      const cg=B.createController(good.deps);
      await cg.enable();
      good.steps(30,200);
      const awake=cg.state();

      // Ce que la main refusée vaut, des deux côtés de la frontière.
      const lm=edgedC.landmarks[0];
      out({asleep,awake,statuses,
           score:Number(B.cPoseScore(lm,1,{}).toFixed(3)),
           quality:Number(B.handQuality(lm,1,1,{}).toFixed(3)),
           counted:B.usableQuality(B.handQuality(lm,1,1,{})),
           // Vue à l'écran malgré tout, et l'anneau reste à zéro.
           drawn:poor.log.filter(l=>l==='watch:1:0.00').length,
           hidden:poor.log.filter(l=>l==='watch:0:0.00').length});
    """)
    # La posture est bonne, la main ne l'est pas : c'est bien le cas de la QA.
    assert result["score"] > 0.9
    assert result["quality"] < 0.25 and result["counted"] is False
    # Soixante secondes de C parfait tenu par une main refusée : rien ne bouge.
    assert result["asleep"] == "sleep"
    assert result["statuses"] == ["status:starting:starting", "status:sleep:sleep"], (
        "la veille a réveillé sur une main que l'interaction refuse")
    # Et la même posture, bien cadrée, réveille : ce n'est pas le réveil qu'on
    # a cassé, c'est la définition qu'on a alignée.
    assert result["awake"] == "active"
    # Vue, dessinée à chaque mesure du guetteur, et l'anneau ne progresse pas.
    assert result["drawn"] > 100
    # Une seule image sans main : l'entrée en veille, peinte avant que la
    # première inférence ait eu lieu. Après, la main refusée est **vue** :
    # la faire disparaître dirait « je ne te vois pas », ce qui est faux.
    assert result["hidden"] == 1, "une main refusée n'est pas une main absente"


# ------------------------------------------------------------------ parité


def test_the_semantic_engines_run_in_interaction_and_never_in_the_watcher(tmp_path):
    """Slice 04, et la contrainte que la Slice 02 a laissée derrière elle : le
    budget d'images de la veille est un acquis mesuré (5 inférences contre 60),
    et le travail sémantique n'a rien à y faire — la veille n'a qu'une
    question, la posture de réveil, à laquelle `createWakeDetector` répond
    déjà.

    Et la sortie sémantique ne survit jamais à ce qu'elle décrit : revenir en
    veille la vide, comme les traits de mouvement de la Slice 03. Une posture
    affichée pour une main que plus rien ne regarde serait pire qu'un écran
    vide."""

    result = run_node(tmp_path, WORLD + """
      const w=world({result:C_POSE,options:{wakeIntervalMs:200,wakeHoldMs:1000,wakeGraceMs:400}});
      const c=B.createController(w.deps);
      await c.enable();
      w.steps(3,200);
      const watching=c.semantics();
      await c.activate();
      w.steps(3,16);
      const interacting=c.semantics();
      c.sleep();
      const asleep=c.semantics();
      out({
        watching:[watching.gestures.postures.length,watching.gestures.events.length,
                  watching.pinch.contacts.length],
        interacting:[interacting.gestures.postures.length,
                     interacting.gestures.events.length,
                     interacting.pinch.contacts.length],
        /* Ce que la main tenue produit : un C reconnu, et les deux canaux de
           pincement au repos sur la même main. */
        gesture:[...new Set(interacting.gestures.events.map(e=>e.gesture+':'+e.scope))],
        channels:interacting.pinch.contacts.map(c=>c.channel+':'+c.state),
        asleep:[asleep.gestures.postures.length,asleep.pinch.contacts.length],
        /* Aucune capture n'existe encore (Slice 06) : rien n'est étouffé. */
        suppressed:interacting.gestures.suppressed.length,
      });
    """)
    # En veille : le guetteur, et rien d'autre.
    assert result["watching"] == [0, 0, 0]
    # En interaction : une main, une posture lue, les deux canaux suivis.
    assert result["interacting"][0] == 1 and result["interacting"][2] == 2
    assert result["gesture"] == ["c_pose:hand"]
    assert result["channels"] == ["primary:open", "secondary:open"]
    assert result["suppressed"] == 0
    assert result["asleep"] == [0, 0]


def test_the_controller_states_and_timings_still_match_the_contract(tmp_path):
    """Le bloc pur est chargé seul par node : il ne peut pas lire le contrat et
    recopie donc ses noms et ses durées. Ce test est ce qui interdit la dérive."""

    result = run_node(tmp_path, """
      out({
        states:B.STATES,lifecycles:C.LIFECYCLES,lifecycle:C.LIFECYCLE,
        live:[C.LIVE_LIFECYCLES,['off','sleep','active','error','autre'].map(C.isLiveLifecycle)],
        mapped:B.STATES.map(C.lifecycleOfControllerState),
        legacy:C.lifecycleOfControllerState('running'),
        unknown:[C.lifecycleOfControllerState('nimporte quoi'),
                 C.lifecycleOfControllerState(undefined),C.lifecycleOfControllerState(null)],
        sleepMs:[B.DEFAULTS.sleepTimeoutMs,C.SLEEP_TIMEOUT_MS,C.SETTINGS_DEFAULTS.sleepTimeoutMs],
        holdMs:[B.DEFAULTS.wakeHoldMs,C.WAKE_HOLD_MS],
        intervalMs:[B.DEFAULTS.wakeIntervalMs,C.WAKE_INTERVAL_MS],
        qualityFloor:[B.DEFAULTS.qualityFloor,C.HAND_QUALITY_FLOOR],
        wakeGraceMs:B.DEFAULTS.wakeGraceMs,
        watcherFitsItsGrace:B.DEFAULTS.wakeIntervalMs<=B.DEFAULTS.wakeGraceMs,
        tuning:['minCutoffHz','betaCutoff','dCutoffHz','filterResetMs','stillSpeedPx','moveSpeedPx',
                'matchRadiusPalms','predictMs','trackVelocityBlend',
                'qualityFloor','qualityEdge','qualityPalmMin','qualityComplete','qualityWarmupFrames']
          .map(k=>[k,B.DEFAULTS[k]]),
        semantics:['pinchMarginRatio','pinchConfidenceMin',
                   'clickMaxMs','clickSlopPx','dragSlopPx','clickStillnessMin',
                   'fingerCurledPalms','fingerExtendedPalms','postureScore','postureHoldMs',
                   'doubleCloseMs','clapPalms','clapSpeedPalms','gestureCooldownMs']
          .map(k=>[k,B.DEFAULTS[k]]),
        fingerBand:B.DEFAULTS.fingerCurledPalms<B.DEFAULTS.fingerExtendedPalms,
        clickUnderDrag:B.DEFAULTS.clickSlopPx<B.DEFAULTS.dragSlopPx,
        retired:['smoothing','handednessBonusPalms'].map(k=>B.DEFAULTS[k]===undefined),
        watchesPerSecond:1000/B.DEFAULTS.wakeIntervalMs,
        liveStates:[B.LIVE_STATES,B.STATES.filter(B.isLiveState)],
        engaged:B.STATES.filter(B.isEngagedState),
        failureCodes:[C.FAILURE_CODES,C.FAILURE_CODES.filter(k=>!!B.MESSAGES[k])],
        classified:['NotAllowedError','NotFoundError','NotReadableError','Autre']
          .map(name=>C.isFailureCode(B.classifyError(Object.assign(new Error('x'),{name})))),
        messageKeys:Object.keys(B.MESSAGES).filter(k=>!C.isFailureCode(k)),
        wakeClass:C.DOM.wakeClass,
      });
    """)
    assert result["lifecycle"] == {"OFF": "off", "SLEEP": "sleep", "ACTIVE": "active", "ERROR": "error"}
    assert result["lifecycles"] == ["off", "sleep", "active", "error"]
    # Chacun des quatre noms du contrat est un état du contrôleur, et chacun des
    # cinq états du contrôleur se lit dans le vocabulaire du contrat.
    assert set(result["lifecycles"]) <= set(result["states"])
    assert result["mapped"] == ["off", "off", "sleep", "active", "error"]
    # `starting` vaut `off` : rien n'interagit tant que la caméra n'est pas là.
    assert result["mapped"][result["states"].index("starting")] == "off"
    # Une panne ne se lit pas « éteint » : c'est tout l'objet d'ERROR.
    assert result["mapped"][result["states"].index("error")] == "error"
    assert result["live"] == [["sleep", "active"], [False, True, True, False, False]]
    assert result["legacy"] == "active"
    assert result["unknown"] == ["off", "off", "off"]
    assert result["sleepMs"] == [30000, 30000, 30000]
    assert result["holdMs"] == [1000, 1000]
    # N4 : la cadence du guetteur est promise « 5 images par seconde » dans le
    # contrat *et* à l'écran. Le test de budget la passait en surcharge
    # explicite, si bien que muter le défaut ne faisait rien tomber.
    assert result["intervalMs"] == [200, 200]
    assert result["watchesPerSecond"] == 5
    # N-A : la cadence du guetteur et la tolérance de trou ne sont pas deux
    # nombres indépendants — le `dt` que voit le détecteur **est** la cadence.
    # `interval > grace` désactive le réveil en silence, `options()` le refuse,
    # et le défaut livré doit évidemment respecter son propre invariant.
    assert result["wakeGraceMs"] == 400
    assert result["watcherFitsItsGrace"] is True
    # Slice 03 : le plancher de qualité est le seul nombre de cette Slice que
    # le contrat possède aussi — c'est lui qui dit « une main exploitable »
    # (décision 7), des deux côtés de la frontière.
    assert result["qualityFloor"] == [0.25, 0.25]
    # Les autres sont des réglages du moteur, mais ils sont épinglés ici pour
    # la même raison que `wakeIntervalMs` (N4) : un défaut que personne
    # n'affirme se mute sans rien faire tomber, et le contrat lisible le
    # publie. Changer l'un d'eux, c'est reporter la valeur ici et dans
    # `docs/barehands-contracts.md`.
    assert result["tuning"] == [
        ["minCutoffHz", 1.2], ["betaCutoff", 0.012], ["dCutoffHz", 1], ["filterResetMs", 400],
        ["stillSpeedPx", 28], ["moveSpeedPx", 420],
        ["matchRadiusPalms", 1.6], ["predictMs", 120],
        ["trackVelocityBlend", 0.5],
        ["qualityFloor", 0.25], ["qualityEdge", 0.04], ["qualityPalmMin", 0.06],
        ["qualityComplete", 0.6], ["qualityWarmupFrames", 3],
    ]
    # Slice 04 : quatorze réglages de plus, même règle — un défaut que personne
    # n'affirme se mute sans rien faire tomber, et le contrat lisible les
    # publie. Changer l'un d'eux, c'est le reporter ici **et** dans
    # `docs/barehands-contracts.md`.
    assert result["semantics"] == [
        ["pinchMarginRatio", 0.18], ["pinchConfidenceMin", 0.5],
        ["clickMaxMs", 400], ["clickSlopPx", 12], ["dragSlopPx", 26],
        ["clickStillnessMin", 0.5],
        ["fingerCurledPalms", 1.15], ["fingerExtendedPalms", 1.6],
        ["postureScore", 0.7], ["postureHoldMs", 250],
        ["doubleCloseMs", 600], ["clapPalms", 1.4], ["clapSpeedPalms", 2.5],
        ["gestureCooldownMs", 500],
    ]
    # Deux relations, pas deux nombres libres : un doigt ne peut pas être
    # « replié » plus loin qu'il n'est « tendu » (`options()` le refuse), et la
    # tolérance d'un clic reste sous celle qui déclenche un glissement — au
    # dessus, aucun contact ne pourrait rester indécis jusqu'au relâchement.
    assert result["fingerBand"] is True and result["clickUnderDrag"] is True
    # `smoothing` a été retiré, pas laissé inerte : `options` le refuse.
    # `handednessBonusPalms` l'a rejoint à la reprise de la Slice 03 : une prime
    # soustraite au coût d'appariement renversait la géométrie sous 0,35 paume
    # de séparation, et la latéralité est désormais une clé secondaire, sans
    # nombre à régler. Laissé dans les défauts, il aurait été un réglage inerte.
    assert result["retired"] == [True, True]
    # `LIVE_STATES` est au bloc pur ce que `LIVE_LIFECYCLES` est au contrat.
    assert result["liveStates"] == [["sleep", "active"], ["sleep", "active"]]
    assert result["liveStates"][0] == result["live"][0]
    # « Tenu et à rendre » n'est pas « fonctionne » : un démarrage en vol en est,
    # et son annulation est ce qui libère la caméra qui arrive. ERROR, non : il
    # a déjà tout rendu, et l'y mettre referait passer un arrêt subi pour voulu.
    assert result["engaged"] == ["starting", "sleep", "active"]
    # N9 : le vocabulaire des codes d'ERROR est promis par le contrat et détenu
    # par le moteur ; sans parité, c'est exactement la dérive qu'ERROR évite.
    assert result["failureCodes"][0] == result["failureCodes"][1]
    assert set(result["failureCodes"][0]) == {
        "camera_denied", "camera_missing", "camera_busy", "camera_ended",
        "camera_unsupported", "assets_missing", "tracking_failed",
        "overlay_failed", "start_failed",
    }
    assert result["classified"] == [True, True, True, True]
    # Le reste de `MESSAGES` raconte le cycle de vie, il ne motive pas une panne.
    assert result["messageKeys"] == [
        "off", "starting", "sleep", "active", "woken", "idle_sleep", "disabled",
    ]
    assert result["wakeClass"] == "jh-wake"


def test_a_camera_failure_is_not_the_same_state_as_a_user_switching_off(tmp_path):
    """Constat de la revue de la Slice 01 : à trois états, une caméra refusée,
    une webcam occupée et un modèle absent se lisaient tous « éteint » — donc
    « voulu ». Le cycle de vie doit distinguer les deux, et le motif précis
    doit survivre à côté de l'état, pas être aplati dedans."""

    result = run_node(tmp_path, WORLD + """
      const denied=world();
      denied.deps.getUserMedia=async()=>{const e=new Error('non');e.name='NotAllowedError';throw e};
      const statuses=[];denied.deps.onStatus=s=>statuses.push(s);
      const c=B.createController(denied.deps);
      await c.enable();
      const broken=C.lifecycleOfControllerState(c.state());
      const off=world();const c2=B.createController(off.deps);
      await c2.enable();c2.disable();
      const last=statuses[statuses.length-1];
      out({broken,quiet:C.lifecycleOfControllerState(c2.state()),
           code:last.code,title:last.title,live:C.isLiveLifecycle(broken),
           released:denied.log.includes('model.close'),frames:denied.frames.size});
    """)
    assert result["broken"] == "error" and result["quiet"] == "off"
    assert result["broken"] != result["quiet"]
    # Le motif reste lisible à côté de l'état, avec son message pour l'écran.
    assert result["code"] == "camera_denied"
    assert "Caméra refusée" in result["title"]
    # ERROR ne tient rien : le modèle chargé est rendu avant qu'il soit publié,
    # et aucune boucle d'images ne survit.
    assert result["live"] is False
    assert result["released"] is True and result["frames"] == 0


def test_the_wake_ring_draws_a_circular_progress():
    """Décision 5 : « circular progress feedback ». La même mécanique que
    l'anneau de pincement, sur la variable que la surimpression écrit.

    Le **nom** de la classe, lui, n'est pas pinné ici : il appartient au
    contrat, et c'est
    `test_barehands_contracts_js::test_the_style_sheets_agree_with_the_dom_names_the_contract_owns`
    qui compare la feuille au contrat pour les quatre noms d'un coup. Deux
    littéraux Python qui s'accordent ne prouvent rien."""

    source = SCRIPT.read_text(encoding="utf-8")
    assert source.count("conic-gradient(currentColor calc(var(--jh-progress,0) * 1turn)") == 2

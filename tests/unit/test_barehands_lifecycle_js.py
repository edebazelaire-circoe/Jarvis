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
      const asleep=world({options:{wakeIntervalMs:200}});
      const c=B.createController(asleep.deps);
      await c.enable();asleep.steps(60,16);
      const awake=world({options:{wakeIntervalMs:200}});
      const c2=B.createController(awake.deps);
      await c2.enable();await c2.activate();awake.steps(60,16);
      out({sleep:asleep.seen(),active:awake.seen(),state:[c.state(),c2.state()]});
    """)
    # 60 images à 16 ms = 960 ms : cinq inférences à 5 images/s, contre une par
    # image en interaction.
    assert result["sleep"] == 5
    assert result["active"] == 60
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


# ------------------------------------------------------------------ parité


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


def test_the_wake_ring_is_styled_where_the_contract_says_it_is():
    """La feuille de style ne peut pas lire le contrat : ce test le fait pour
    elle, comme pour les autres noms du DOM."""

    source = SCRIPT.read_text(encoding="utf-8")
    assert "#jarvisHands .jh-wake{" in source
    # Progression circulaire (décision 5) : la même mécanique que l'anneau de
    # pincement, sur la variable que la surimpression écrit.
    assert "conic-gradient(currentColor calc(var(--jh-progress,0) * 1turn)" in source

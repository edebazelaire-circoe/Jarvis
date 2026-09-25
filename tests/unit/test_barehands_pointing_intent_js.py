"""Intention de pointer et exemples négatifs (tâche adaptative, Slice 03), par node.

Décision 46 : suivre une main, vouloir pointer et montrer un curseur sont trois
états. Ce qui est vérifié ici : la posture de visée (le C prolongé vers le
pincement) et ce qu'elle refuse ; la machine `none → candidate → pointing`,
ses deux hystérésis et son indépendance à la cadence ; le contrôleur qui
**suit** toutes les mains mais ne fait **dessiner** que celles qui visent — en
interaction comme en veille —, qui garde visible une main qui pince ou qui
tient une prise, qui nettoie à la perte et au changement de cycle de vie, et
qui dit tout cela en événements de séance du contrat.

Décision 47 : l'exercice « Bouger sans cliquer », joué sur des traces
synthétiques par le **vrai** parcours : les faux événements comptés, leurs
taux par minute d'exposition, et la même trace qui rend deux fois les mêmes
nombres.

L'horloge est injectée : aucune attente réelle, aucun minuteur.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

# Les doubles existants, réutilisés plutôt que recopiés : le monde du cycle de
# vie (caméra, vidéo, boucle d'images), le pilote du parcours de calibration et
# le double de DOM de l'aperçu de cible.
from test_barehands_calibration_js import DOM, DRIVER  # noqa: E402
from test_barehands_lifecycle_js import WORLD  # noqa: E402
from test_barehands_target_js import BROWSER, run_node as run_page  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
BAREHANDS = RUNTIME / "control_center_barehands.js"
CONTRACTS = RUNTIME / "control_center_barehands_contracts.js"
RECORDER = RUNTIME / "control_center_barehands_recorder.js"
CALIBRATION = RUNTIME / "control_center_barehands_calibration.js"
HAND_ART = RUNTIME / "control_center_barehands_hand_art.js"
DOC = ROOT / "docs" / "barehands-contracts.md"


def run_node(tmp_path: Path, source: str, name: str = "pointing") -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / f"barehands-{name}.cjs"
    script.write_text(
        f"const C=require({json.dumps(str(CONTRACTS))});\n"
        "global.JarvisBarehandsContracts=C;\n"
        f"const R=require({json.dumps(str(RECORDER))});\n"
        "global.JarvisBarehandsRecorder=R;\n"
        f"const B=require({json.dumps(str(BAREHANDS))});\n"
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


#: La main du monde du cycle de vie laisse le bout du majeur au centre de
#: l'image ; celle-ci le replie contre la paume, loin du pouce, pour que le
#: canal secondaire ne se lise pas par accident. `pinch2` pose le pouce sur le
#: majeur : un clic droit.
HANDS = """
function aimHand(gap,reach=1.8){
  const lm=hand(gap,reach);
  lm[12]={x:.42,y:.66,z:0};
  return lm;
}
function pinch2(){const lm=aimHand(.65);lm[4]={x:lm[12].x+.01,y:lm[12].y,z:0};return lm}
"""


# ------------------------------------------------------------- la posture


def test_the_pointing_posture_is_the_c_extended_toward_the_pinch(tmp_path):
    """Pas de nouveau modèle de geste : le C de `cPoseScore`, prolongé sous sa
    bande jusqu'au contact. Une main ouverte, un poing, un clic droit et une
    main illisible ne visent pas."""

    result = run_node(tmp_path, WORLD + HANDS + """
      const score=lm=>B.pointingPostureScore(lm,1,{});
      out({
        c:score(aimHand(.65)),
        prePinch:score(aimHand(.36)),cAtPrePinch:B.cPoseScore(aimHand(.36),1),
        contact:score(aimHand(.15)),
        open:score(aimHand(1.3)),fist:score(aimHand(.65,1)),secondary:score(pinch2()),
        unusable:[score([]),score(null)],
        /* La couture entre les deux rampes : aucun trou sous le seuil
           d'entrée entre le pré-pincement et le C. */
        seam:Math.min(...Array.from({length:46},(_,i)=>score(aimHand(.30+i*.01)))),
      });
    """)
    assert result["c"] == 1
    # Sous la bande du C, là où le C seul tombait à zéro : c'est un
    # pré-pincement, et il vise.
    assert result["cAtPrePinch"] == 0 and result["prePinch"] == 1
    assert result["contact"] == 1
    assert result["open"] == 0 and result["fist"] == 0 and result["secondary"] == 0
    assert result["unusable"] == [None, None]
    assert result["seam"] >= 0.5


# ------------------------------------------------------------- la machine


MACHINE = """
const run=(trace,fps,o)=>{
  const m=B.createPointingIntent(o||{});
  const states=[],events=[];
  for(let t=0;t<=trace.end;t+=1000/fps){
    const h=trace.at(t);
    const r=m.update({now:t,hands:h?[Object.assign({handTrackId:1},h)]:[]});
    states.push([Math.round(t),r.hands.length?r.hands[0].state:'absent']);
    for(const e of r.events)events.push([e.kind,Math.round(e.t)]);
  }
  return {states,events};
};
const firstAt=(states,state)=>{const hit=states.find(s=>s[1]===state);return hit?hit[0]:null};
"""


def test_the_intent_enters_holds_and_leaves_with_two_hysteresis(tmp_path):
    """Entrée : score d'entrée (posture × immobilité) tenu `pointingEnterMs`.
    Maintien : la **posture** seule, au-dessus de `pointingExitScore`. Perte :
    `pointingExitMs` sous ce seuil. Et une main qui pince pointe d'office."""

    result = run_node(tmp_path, MACHINE + """
      // Visée franche, immobile : candidate tout de suite, pointe à 150 ms.
      const aim=run({end:600,at:()=>({posture:1,stillness:1,quality:1})},60);
      /* Entre les deux seuils (0,4) : on ne s'y engage pas, mais une visée
         établie y tient. */
      const between=run({end:600,at:()=>({posture:.4,stillness:1,quality:1})},60);
      const holds=run({end:1400,at:t=>({posture:t<400?1:.4,stillness:1,quality:1})},60);
      // La posture se perd : 300 ms plus tard, et pas avant, la visée finit.
      const lost=run({end:1400,at:t=>({posture:t<400?1:0,stillness:1,quality:1})},60);
      /* À pleine vitesse, le score d'entrée vaut 0,4 × posture : une main qui
         file ne s'engage pas. Mais une visée établie survit à la vitesse. */
      const fast=run({end:600,at:()=>({posture:1,stillness:0,quality:1})},60);
      const aimThenFast=run({end:1400,at:t=>({posture:1,stillness:t<300?1:0,quality:1})},60);
      /* Une main douteuse n'entre pas ; une visée établie survit à un suivi
         qui se dégrade tant que la posture tient. */
      const doubtful=run({end:600,at:()=>({posture:1,stillness:1,quality:.1})},60);
      const aimThenDoubt=run({end:1400,at:t=>({posture:1,stillness:1,quality:t<300?1:.1})},60);
      // Une main qui pince pointe d'office, quelle que soit sa posture.
      const engaged=run({end:200,at:t=>({posture:0,stillness:0,quality:1,engaged:t>=100})},60);
      out({aim,between,holds,lost,fast,aimThenFast,doubtful,aimThenDoubt,engaged,
        defaults:[B.DEFAULTS.pointingEnterScore,B.DEFAULTS.pointingExitScore,
          B.DEFAULTS.pointingEnterMs,B.DEFAULTS.pointingExitMs,B.DEFAULTS.pointingMotionFloor],
        inverted:refused(()=>B.createPointingIntent({pointingEnterScore:.3,pointingExitScore:.5})),
        equal:refused(()=>B.createPointingIntent({pointingEnterScore:.4,pointingExitScore:.4})),
        noClock:refused(()=>B.createPointingIntent({}).update({now:NaN,hands:[]}))});
    """)
    assert result["defaults"] == [0.5, 0.3, 150, 300, 0.4]
    aim = result["aim"]
    assert aim["states"][0] == [0, "candidate"]
    start = [e for e in aim["events"] if e[0] == "pointing_intent_start"]
    assert len(start) == 1 and 150 <= start[0][1] < 150 + 17
    assert all(state != "pointing" for t, state in aim["states"] if t < 150)
    assert {state for _, state in result["between"]["states"]} == {"none"}
    assert result["holds"]["states"][-1][1] == "pointing"
    assert [e[0] for e in result["holds"]["events"]] == ["pointing_intent_start"]
    lost = result["lost"]
    end = [e for e in lost["events"] if e[0] == "pointing_intent_end"]
    assert len(end) == 1 and 700 <= end[0][1] <= 700 + 34
    assert {state for _, state in result["fast"]["states"]} == {"none"}
    assert result["aimThenFast"]["states"][-1][1] == "pointing"
    assert {state for _, state in result["doubtful"]["states"]} == {"none"}
    assert result["aimThenDoubt"]["states"][-1][1] == "pointing"
    engaged = result["engaged"]
    assert [e[0] for e in engaged["events"]] == ["pointing_intent_start"]
    assert 100 <= engaged["events"][0][1] < 117
    # Un seuil de maintien au-dessus du seuil d'entrée se refuse ; l'égalité,
    # « pas d'hystérésis », reste permise. Une horloge inutilisable aussi.
    assert result["inverted"] == "RangeError" and result["equal"] is None
    assert result["noClock"] == "tracking_failed"


def test_the_intent_is_the_same_at_every_frame_rate(tmp_path):
    """Durées en millisecondes, premier instant qui ne crédite rien : la même
    trace échantillonnée à 15, 30, 60 et 120 images/s rend les mêmes
    transitions, chacune à deux périodes d'image près au plus (l'instant où
    un changement commence est lu sur une image, celui où sa durée est
    atteinte sur une autre)."""

    result = run_node(tmp_path, MACHINE + """
      /* Une visée, un passage entre les seuils, une vraie perte, une reprise
         brève (sous 150 ms : rien) puis une visée tenue. */
      const posture=t=>t<200?0:t<900?1:t<1300?.4:t<1800?0:t<1900?1:t<2000?0:t<2600?1:0;
      const trace={end:3200,at:t=>({posture:posture(t),stillness:1,quality:1})};
      const rates=[15,30,60,120];
      out(rates.map(fps=>({fps,events:run(trace,fps).events})));
    """)
    kinds = [[e[0] for e in rate["events"]] for rate in result]
    assert all(k == kinds[0] for k in kinds), kinds
    assert kinds[0] == ["pointing_intent_start", "pointing_intent_end",
                        "pointing_intent_start", "pointing_intent_end"]
    for i in range(len(kinds[0])):
        times = [rate["events"][i][1] for rate in result]
        # Deux images à 15 images/s : 134 ms.
        assert max(times) - min(times) <= 134, (i, times)


def test_a_lost_hand_keeps_its_intent_for_the_grace_then_says_it_ended(tmp_path):
    """Une image manquée ne fait pas clignoter le curseur ; une main partie
    pour de bon finit sa visée **en le disant** ; un trou d'observation plus
    long que la tolérance est une perte ; `reset` termine tout ce qui visait."""

    result = run_node(tmp_path, """
      const m=B.createPointingIntent({});
      const seen=t=>m.update({now:t,hands:[{handTrackId:7,posture:1,stillness:1,quality:1}]});
      for(let t=0;t<=300;t+=33)seen(t);
      const blink=m.update({now:350,hands:[]});
      const back=seen(383);
      const gone=[];
      for(let t=416;t<=900;t+=33){const r=m.update({now:t,hands:[]});gone.push(...r.events.map(e=>[e.kind,e.handTrackId]))}
      /* Un trou de 500 ms entre deux observations : rien ne l'atteste. */
      const g=B.createPointingIntent({});
      for(let t=0;t<=300;t+=33)g.update({now:t,hands:[{handTrackId:1,posture:1,stillness:1,quality:1}]});
      const jump=g.update({now:800,hands:[{handTrackId:1,posture:1,stillness:1,quality:1}]});
      const r=B.createPointingIntent({});
      for(let t=0;t<=300;t+=33)r.update({now:t,hands:[{handTrackId:'a',posture:1,stillness:1,quality:1},
        {handTrackId:'b',posture:0,stillness:1,quality:1}]});
      out({blink:blink.events.length,back:back.hands[0].state,gone,
        jump:[jump.events.map(e=>e.kind),jump.hands[0].state],
        reset:r.reset(400).map(e=>[e.kind,e.handTrackId]),after:r.snapshot().length});
    """)
    assert result["blink"] == 0 and result["back"] == "pointing"
    assert result["gone"] == [["pointing_intent_end", 7]]
    assert result["jump"] == [["pointing_intent_end"], "candidate"]
    assert result["reset"] == [["pointing_intent_end", "a"]]
    assert result["after"] == 0


def test_the_engine_names_are_the_contract_names_and_the_keys_are_trial_keys(tmp_path):
    """Recopie tenue par parité (le bloc pur se charge seul) : les événements
    que le contrôleur émet sont ceux du contrat, et chaque réglage de
    l'intention est une clé d'essai lue par `createPointingIntent`."""

    result = run_node(tmp_path, """
      const keys=Object.keys(B.DEFAULTS).filter(k=>/^pointing/.test(k));
      out({events:Object.values(B.POINTING_EVENT),known:C.SESSION_EVENTS,keys,
        trial:keys.map(k=>C.TRIAL_KEYS[k]&&[C.TRIAL_KEYS[k].default===B.DEFAULTS[k],
          C.TRIAL_KEYS[k].reader,C.TRIAL_KEYS[k].family]),
        invariant:C.TRIAL_INVARIANTS.some(r=>r.low==='pointingExitScore'&&r.high==='pointingEnterScore'),
        refused:C.validateTrialPatch({pointingExitScore:.6},{pointingEnterScore:.5}).code,
        states:B.POINTING_STATES});
    """)
    assert set(result["events"]) <= set(result["known"])
    assert sorted(result["keys"]) == sorted(["pointingEnterScore", "pointingExitScore",
                                             "pointingEnterMs", "pointingExitMs", "pointingMotionFloor"])
    assert all(t == [True, "createPointingIntent", "pointing"] for t in result["trial"]), result["trial"]
    assert result["invariant"] is True
    assert result["refused"] == "barehands_trial_invariant_violated"
    assert result["states"] == ["none", "candidate", "pointing"]


# ------------------------------------------------------------- le contrôleur


CONTROLLER = WORLD + HANDS + """
const rig=(opts)=>{
  const w=world(Object.assign({result:{landmarks:[aimHand(1.3)]}},opts||{}));
  const renders=[],events=[],measures=[];
  w.deps.overlay.render=tokens=>renders.push(tokens.map(t=>({id:t.id,shown:t.shown,intent:t.intent})));
  const hovered=[];
  w.deps.interaction.hover=tokens=>hovered.push(tokens.length);
  w.deps.onSessionEvent=e=>events.push([e.kind,Math.round(e.t)]);
  w.deps.onMeasure=r=>measures.push(r.hands.map(h=>({pointing:h.pointing,shown:h.pointerShown,
    score:h.pointingScore,pressed:h.pressed,secondaryPressed:h.secondaryPressed,targeted:h.targeted})));
  let held=[];
  w.deps.captures=()=>held;
  const c=B.createController(w.deps);
  return {w,c,renders,events,measures,hovered,hold:ids=>{held=ids}};
};
const pose=(r,lm)=>{r.w.state.result={landmarks:[lm]}};
const lastShown=r=>{const last=r.renders[r.renders.length-1]||[];return last.map(t=>t.shown)};
"""


def test_a_tracked_hand_without_intent_draws_no_token_but_stays_tracked(tmp_path):
    """**Décision 46, en interaction.** Une main ouverte qui bouge est suivie —
    jetons rendus à la surimpression, survol et couture de mesure nourris, la
    veille réarmée — mais **aucun** jeton n'est à dessiner. Le C l'allume après
    150 ms, le pré-pincement la garde, la perte l'éteint 300 ms plus tard, et
    chaque transition est un événement de séance du contrat."""

    result = run_node(tmp_path, CONTROLLER + """
      const r=rig();
      await r.c.enable();await r.c.activate();
      r.w.steps(40,33);                          // 1,3 s de main ouverte
      const open={shown:lastShown(r),renders:r.renders.length,hovered:r.hovered.slice(-1)[0],
        measured:r.measures.slice(-1)[0],events:r.events.slice()};
      pose(r,aimHand(.65));r.w.steps(3,33);
      const early=lastShown(r);
      r.w.steps(4,33);
      const aimed=lastShown(r);
      pose(r,aimHand(.36));r.w.steps(10,33);
      const prePinch=lastShown(r);
      pose(r,aimHand(1.3));r.w.steps(6,33);
      const fading=lastShown(r);
      r.w.steps(6,33);
      const gone=lastShown(r);
      // Quarante secondes de main ouverte : suivie, donc la session reste active.
      r.w.steps(1200,33);
      out({open,early,aimed,prePinch,fading,gone,events:r.events,state:r.c.state(),
        snapshot:r.c.pointing()});
    """)
    open_ = result["open"]
    assert open_["shown"] == [False], "une main ouverte ne dessine pas de jeton"
    assert open_["renders"] >= 30 and open_["hovered"] == 1, "mais elle est rendue et survolée"
    assert open_["measured"][0]["pointing"] is False and open_["measured"][0]["shown"] is False
    assert open_["events"] == []
    assert result["early"] == [False], "un C qui commence ne dessine pas encore"
    assert result["aimed"] == [True]
    assert result["prePinch"] == [True]
    assert result["fading"] == [True], "la perte attend 300 ms"
    assert result["gone"] == [False]
    kinds = [e[0] for e in result["events"]]
    assert kinds == ["pointing_intent_start", "pointer_shown",
                     "pointing_intent_end", "pointer_hidden"]
    assert result["state"] == "active", "une main suivie sans intention garde la session éveillée"
    assert [h["state"] for h in result["snapshot"]] == ["none"]


def test_a_pinch_or_a_held_capture_keeps_the_token_whatever_the_posture(tmp_path):
    """Un contact en cours et une prise tenue **se voient** : la main pointe
    d'office. La couture de mesure dit ce que le moteur a décidé (`pressed`)."""

    result = run_node(tmp_path, CONTROLLER + """
      const r=rig();
      await r.c.enable();await r.c.activate();
      r.w.steps(10,33);
      const before=lastShown(r);
      // Un pincement franc, main ouverte avant : le contact l'engage.
      pose(r,aimHand(.12));r.w.steps(6,33);
      const pinching=lastShown(r);
      const pressed=r.measures.slice(-1)[0][0].pressed;
      pose(r,aimHand(1.3));r.w.steps(20,33);
      const released=lastShown(r);
      // Une prise tenue par cette main, posture ouverte : le jeton reste.
      const id=r.renders.slice(-1)[0][0].id;
      r.hold([id]);r.w.steps(3,33);
      const holding=lastShown(r);
      r.w.steps(30,33);
      const stillHolding=lastShown(r);
      r.hold([]);r.w.steps(12,33);
      const dropped=lastShown(r);
      out({before,pinching,pressed,released,holding,stillHolding,dropped});
    """)
    assert result["before"] == [False]
    assert result["pinching"] == [True] and result["pressed"] is True
    assert result["released"] == [False]
    assert result["holding"] == [True] and result["stillHolding"] == [True]
    assert result["dropped"] == [False]


def test_a_low_quality_hand_never_starts_aiming_but_an_aim_survives_a_doubtful_frame(tmp_path):
    """Une main que le suivi ne croit pas ne s'engage pas — elle ne dessine
    rien. Une visée établie ne disparaît pas parce que le suivi se dégrade :
    le jeton se dessine alors pâle (règle de la surimpression)."""

    result = run_node(tmp_path, CONTROLLER + """
      const shift=(lm,dx)=>lm.map(p=>({x:p.x+dx,y:p.y,z:0}));
      const edged=shift(aimHand(.65),.365);
      const r=rig({result:{landmarks:[edged]}});
      await r.c.enable();await r.c.activate();
      r.w.steps(30,33);
      const doubtful=lastShown(r);
      const r2=rig({result:{landmarks:[aimHand(.65)]}});
      await r2.c.enable();await r2.c.activate();
      r2.w.steps(10,33);
      const aimed=lastShown(r2);
      /* Glissée vers le bord, une image après l'autre : la même piste, dont
         la qualité tombe sous le plancher en chemin. */
      for(let i=1;i<=30;i+=1){pose(r2,shift(aimHand(.65),.365*i/30));r2.w.step(33)}
      r2.w.steps(10,33);
      out({doubtful,aimed,kept:lastShown(r2),
        quality:B.handQuality(edged,1,1,{})});
    """)
    assert result["quality"] < 0.25
    assert result["doubtful"] == [False]
    assert result["aimed"] == [True] and result["kept"] == [True]


def test_every_lifecycle_change_ends_the_aim_and_hides_the_pointer_out_loud(tmp_path):
    """Mise en veille et extinction : chaque intention établie finit et chaque
    curseur disparaît, **dit** — aucun lecteur ne garde un curseur ouvert sur
    une main que plus personne ne suit."""

    result = run_node(tmp_path, CONTROLLER + """
      const r=rig({result:{landmarks:[aimHand(.65)]}});
      await r.c.enable();await r.c.activate();
      r.w.steps(10,33);
      const before=r.events.length;
      r.c.sleep();
      const slept=r.events.slice(before);
      await r.c.activate();r.w.steps(10,33);
      const again=r.events.length;
      r.c.disable();
      out({slept,off:r.events.slice(again),snapshot:r.c.pointing().length});
    """)
    assert [e[0] for e in result["slept"]] == ["pointing_intent_end", "pointer_hidden"]
    assert [e[0] for e in result["off"]] == ["pointing_intent_end", "pointer_hidden"]
    assert result["snapshot"] == 0


def test_sleep_draws_nothing_for_ordinary_motion_and_the_ring_only_for_a_wake_posture(tmp_path):
    """**Décision 46, en veille.** Une main qui bouge ordinairement ne dessine
    rien — pas même un anneau à zéro. L'anneau apparaît quand la posture de
    réveil commence, avance, et disparaît quand elle se perd."""

    result = run_node(tmp_path, CONTROLLER + """
      const r=rig();
      await r.c.enable();
      const log=()=>r.w.log.filter(l=>l.startsWith('watch:'));
      r.w.steps(30,200);                        // 6 s de main ouverte
      const open=log().slice(1);
      const mark=log().length;
      pose(r,aimHand(.65));r.w.steps(3,200);
      const c=log().slice(mark);
      pose(r,aimHand(1.3));
      const mark2=log().length;
      r.w.steps(4,200);
      out({open,c,lost:log().slice(mark2),state:r.c.state()});
    """)
    assert result["open"] and all(entry.startswith("watch:0:") for entry in result["open"])
    assert all(entry.startswith("watch:1:") for entry in result["c"]), result["c"]
    progress = [float(entry.split(":")[2]) for entry in result["c"]]
    assert progress == sorted(progress) and progress[-1] > 0
    assert result["lost"][-1].startswith("watch:0:")
    assert result["state"] == "sleep"


# ------------------------------------------------------------- la page


def test_the_overlay_draws_only_the_hands_that_aim_and_still_counts_the_others(tmp_path):
    """La surimpression **réelle** : un jeton `shown:false` n'a pas d'élément
    dans l'arbre (ni caché ni transparent), la pastille compte toujours les
    mains suivies, et un jeton sans `shown` (console, doubles) se dessine."""

    result = run_page(tmp_path, BROWSER + """
      const tokens=()=>registry.filter(el=>el.className===C.DOM.tokenClass&&el.parent).length;
      const badge=()=>registry.find(el=>el.className===C.DOM.badgeClass&&el.parent).textContent;
      const t=(id,shown)=>Object.assign(token(id,100*id,100),shown===undefined?{}:{shown});
      overlay.render([t(1,false),t(2,false)]);
      const none={drawn:tokens(),badge:badge()};
      overlay.render([t(1,true),t(2,false)]);
      const one={drawn:tokens(),badge:badge()};
      overlay.render([t(1,false),t(2,false)]);
      const cleared=tokens();
      overlay.render([t(1),t(2)]);
      out({none,one,cleared,legacy:tokens()});
    """)
    assert result["none"] == {"drawn": 0, "badge": "MAINS · 2"}
    assert result["one"] == {"drawn": 1, "badge": "MAINS · 2"}
    assert result["cleared"] == 0, "un curseur qui perd l'intention quitte l'arbre"
    assert result["legacy"] == 2


def test_a_hand_that_does_not_aim_lights_up_no_window_edge(tmp_path):
    """Le survol des zones (décision 3 bis) est un retour de **visée** : une
    main qui passe sans viser n'allume pas le bord d'une fenêtre. Sous
    intention de pointer il revient ; un pincement le remplace toujours."""

    result = run_page(tmp_path, BROWSER + """
      const win=star('obj-1',{left:200,top:100,width:300,height:200},'window','Tâche A');
      global.page=[win];
      const shot=(pointing,state)=>{
        frame([Object.assign(token(1,210,200),{pointing})],[contact(1,state||'open')]);
        return [previews().length,interaction.targets().length]};
      out({passing:shot(false),aiming:shot(true),pinching:shot(false,'pinching')});
      interaction.clear();
    """)
    assert result["passing"] == [0, 0]
    assert result["aiming"] == [1, 0]
    assert result["pinching"] == [1, 1], "un contact vise toujours, et se publie"


def test_the_page_wires_the_session_events_only_while_calibrating():
    """La couture des événements de séance suit la règle de la couture de
    mesures : posée par `startMeasuring`, retirée par `stopMeasuring` ; et la
    calibration reçoit le **vrai** guetteur de réveil du contrôleur."""

    source = BAREHANDS.read_text(encoding="utf-8")
    start = source[source.index("function startMeasuring(){"):source.index("function stopMeasuring(){")]
    stop = source[source.index("function stopMeasuring(){"):]
    stop = stop[:stop.index("\n")]
    assert "controllerDeps.onSessionEvent=" in start and "flow.observe(event)" in start
    assert "delete controllerDeps.onSessionEvent" in stop
    assert "wakeDetector:()=>controller.wakeDetector()" in source
    assert "wakeDetector:()=>createWakeDetector(liveOptions)" in source


# ------------------------------------------------------------- l'exercice


NEGATIVE = DOM + DRIVER + """
/* Sept étapes passées : on arrive à « Bouger sans cliquer ». */
const toNegatives=cal=>{cal.start();for(let i=0;i<7;i+=1)skipStep(cal);return cal.stepId()};
const NEG_OPTIONS={stageHoldMs:300,stageTimeoutMs:8000,stageMinSamples:10,pinchRepeats:2,
  negativeMs:3000,negativeMinMs:1000};
/* 7A : une trace de mouvement ordinaire, 33 ms par image. Un faux appui, un
   faux clic droit, une cible prise, une posture en C tenue 1,5 s (un réveil
   que la veille aurait fait) et un curseur affiché, observé du contrôleur. */
const naturalTrace=cal=>{
  for(let i=0;i<110;i+=1){
    clock+=33;
    if(i===20)cal.observe({kind:'pointer_shown',t:clock,score:.8});
    if(i===24)cal.observe({kind:'pointer_hidden',t:clock,score:null});
    cal.feed({now:clock,hands:[hand({handTrackId:1,
      pressed:i>=10&&i<13,secondaryPressed:i>=30&&i<32,targeted:i>=50&&i<53,
      cPose:i>=40&&i<85?.9:.05,pointerShown:i>=20&&i<24})]});
  }
};
const summary=cal=>{const s=cal.session();return {
  falseEvents:s.falseEvents.map(e=>[e.falseKind,e.stage,e.exerciseRef,e.sampleRef!==null,e.t]),
  measurements:s.measurements,
  samples:s.samples.filter(x=>x.event).map(x=>[x.event.kind,x.event.falseKind,x.stage,x.exerciseRef])}};
"""


def test_the_natural_motion_exercise_counts_every_false_trigger_as_a_rate(tmp_path):
    """**Décision 47, 7A.** Tout ce qui se déclenche pendant un mouvement
    ordinaire est faux : chaque front est un `createFalseEvent` qui désigne son
    échantillon de séance, et le temps se solde en **taux par minute
    d'exposition** sous la référence de l'exercice."""

    result = run_node(tmp_path, NEGATIVE + """
      const logs=[];
      const cal=calOf({options:NEG_OPTIONS,log:(l,m,d)=>logs.push([m,d])});
      const at=toNegatives(cal);
      readOn(cal);
      const sub=cal.sub();
      naturalTrace(cal);
      const note=text(flowRoot(),C.DOM.flowNoteClass)[0];
      const logged=logs.find(l=>l[0]==='[barehands] calibration.negatives');
      out({at,sub,note,phase:cal.phase(),step:cal.stepId(),logged:logged&&logged[1],...summary(cal)});
    """, name="natural")
    assert result["at"] == "natural_motion"
    assert result["sub"] == {"at": 0, "total": 2, "id": "natural_motion"}
    assert result["phase"] == "result" and result["step"] == "natural_motion"
    kinds = [e[0] for e in result["falseEvents"]]
    assert sorted(kinds) == sorted(["false_press", "unintended_pointer", "false_secondary_press",
                                    "unintended_wake", "unintended_target"])
    assert all(e[1] == "natural_motion" and e[2] == "ex-1" and e[3] for e in result["falseEvents"])
    counts = result["logged"]["counts"]
    exposure = result["logged"]["exposureMs"]
    assert counts == {"false_press": 1, "false_secondary_press": 1, "unintended_wake": 1,
                      "unintended_target": 1, "unintended_pointer": 1}
    assert 3000 <= exposure < 3100
    rates = result["measurements"]["ex-1"]
    for name in ("false_press_rate", "false_secondary_press_rate", "unintended_wake_rate",
                 "unintended_target_rate", "unintended_pointer_rate"):
        assert rates[name] == pytest.approx(60000 / result["logged"]["exposureMs"], rel=1e-3), name
    # L'historique porte les faits et leurs marques, dans le vocabulaire du
    # contrat — et l'événement du contrôleur tel quel.
    samples = result["samples"]
    assert ["pointer_shown", None, "natural_motion", "ex-1"] in samples
    assert ["pointer_hidden", None, "natural_motion", "ex-1"] in samples
    assert sum(1 for s in samples if s[0] == "false_event") == 5
    assert ["pinch_press", None, "natural_motion", "ex-1"] in samples
    assert "faux appui" in result["note"] and "7A · Bouger librement" in result["note"]


def test_the_same_trace_gives_the_same_counts_twice(tmp_path):
    """Reproductible : deux séances fraîches, la même trace, les mêmes faux
    événements aux mêmes instants de séance et les mêmes taux."""

    result = run_node(tmp_path, NEGATIVE + """
      const play=()=>{const cal=calOf({options:NEG_OPTIONS});
        toNegatives(cal);readOn(cal);naturalTrace(cal);const s=summary(cal);cal.exit('test');return s};
      const a=play(),b=play();
      out({same:JSON.stringify(a)===JSON.stringify(b),a});
    """, name="replay")
    assert result["same"] is True
    assert len(result["a"]["falseEvents"]) == 5


def test_aiming_without_clicking_counts_presses_but_not_the_wanted_pointer(tmp_path):
    """**Décision 47, 7B.** Le curseur y est voulu et la posture de visée est
    celle du réveil : ni `unintended_pointer` ni `unintended_wake`. Un appui y
    reste faux. Le temps s'arme sur un jeton **à l'écran**, et se solde quand
    le jeton s'est posé sur les trois points sans pincer."""

    result = run_node(tmp_path, NEGATIVE + """
      const cal=calOf({options:NEG_OPTIONS});
      toNegatives(cal);readOn(cal);
      feedUntil(cal,{cPose:.05});              // 7A sans faute (pas de C tenu)
      const verdict7A=text(flowRoot(),C.DOM.flowNoteClass)[0];
      verdictOver(cal);
      const at=cal.stepId();
      readOn(cal);
      const aim=cal.aim();
      // Jeton caché : le temps attend, il ne mesure rien.
      feed(cal,20,{pointerShown:false});
      const waiting=cal.phase();
      const spots=[[282,259],[998,259],[640,504]];
      let pressedOnce=false;
      for(const [x,y] of spots){
        for(let i=0;i<30;i+=1){
          clock+=33;
          const press=!pressedOnce&&i===5;if(press)pressedOnce=true;
          if(i===0)cal.observe({kind:'pointer_shown',t:clock,score:.9});
          cal.feed({now:clock,hands:[hand({handTrackId:1,pointerShown:true,pointerX:x,pointerY:y,
            cPose:.95,pressed:press})]});
        }
      }
      const rows=(()=>{verdictOver(cal);return reportRows()})();
      out({verdict7A,at,aim,waiting,rows,...summary(cal)});
    """, name="aimNoClick")
    assert "mesuré" in result["verdict7A"]
    assert result["at"] == "aim_no_click"
    assert result["aim"] == {"points": 3, "hits": 0, "at": 0}
    assert result["waiting"] == "armed", "sans jeton à l'écran, viser n'a pas commencé"
    kinds = [(e[0], e[1]) for e in result["falseEvents"]]
    assert kinds == [("false_press", "aim_no_click")]
    rates = result["measurements"]["ex-2"]
    assert set(rates) == {"false_press_rate", "false_secondary_press_rate", "unintended_target_rate"}
    assert rates["false_press_rate"] > 0 and rates["unintended_target_rate"] == 0
    labels = {row[0]: row for row in result["rows"]}
    assert labels["7A · Bouger librement"][1] == "jf-ok"
    assert "aucun faux déclenchement" in labels["7A · Bouger librement"][2]
    assert labels["7B · Viser sans cliquer"][1] == "jf-ok"
    assert "1 faux appui(s)" in labels["7B · Viser sans cliquer"][2]
    assert "points visés : 3 sur 3" in labels["7B · Viser sans cliquer"][2]


def test_an_old_profile_without_the_negative_stages_still_loads(tmp_path):
    """Compatibilité : `STAGE` gagne deux étapes **en fin**. Un profil v2
    enregistré avant elles se relit — elles valent `skipped` — des deux côtés
    (contrat de page et serveur)."""

    from jarvis.runtime import barehands_profile

    result = run_node(tmp_path, """
      const seven=Object.fromEntries(['neutral','c_pose','pinch_primary','pinch_secondary','aim','drag','resize']
        .map(s=>[s,{status:'ok',reason:null,samples:3}]));
      const p=C.normalizeProfile({schemaVersion:2,updatedAt:1,hands:{},stages:seven});
      out({stages:C.STAGES,version:C.PROFILE_SCHEMA_VERSION,
        natural:p.stages.natural_motion,aim:p.stages.aim_no_click,kept:p.stages.resize.status});
    """, name="oldProfile")
    assert result["stages"][-2:] == ["natural_motion", "aim_no_click"]
    assert result["version"] == 2
    assert result["natural"]["status"] == "skipped" and result["aim"]["status"] == "skipped"
    assert result["kept"] == "ok"
    assert list(barehands_profile.STAGES) == result["stages"]


def test_the_contract_documents_decisions_46_and_47():
    doc = DOC.read_text(encoding="utf-8")
    section = doc[doc.index("## 17. Calibration adaptative"):]
    assert "### Décision 46" in section and "### Décision 47" in section
    for name in ("createPointingIntent", "pointingPostureScore", "onSessionEvent",
                 "natural_motion", "aim_no_click", "negativeMinMs", "unintended_pointer_rate"):
        assert name in section, name

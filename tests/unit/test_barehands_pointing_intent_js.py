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
#: Le contrat étendu du § 12 (Slice 10) : tous les noms du contrat, plus la
#: calibration adaptative et le banc — ce que lisent les modules de page.
ADAPTIVE = RUNTIME / "control_center_barehands_adaptive.js"
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
        f"const C=require({json.dumps(str(ADAPTIVE))});\n"
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
  // Majeur, annulaire et auriculaire repliés contre la paume : viser, c'est
  // l'index seul déplié.
  lm[12]={x:.42,y:.66,z:0};lm[16]={x:.45,y:.68,z:0};lm[20]={x:.55,y:.7,z:0};
  return lm;
}
/* Les mêmes doigts **dépliés** (majeur écarté du pouce, de l'autre côté de
   l'index) : une main plate, ou détendue. */
function flatHand(gap,reach=1.8){
  const lm=hand(gap,reach);
  lm[12]={x:.4,y:.8-.2*reach*.98,z:0};lm[16]={x:.34,y:.8-.2*reach*.92,z:0};lm[20]={x:.3,y:.8-.2*reach*.8,z:0};
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
        trial:keys.map(k=>C.TRIAL_KEYS[k]&&[k,C.TRIAL_KEYS[k].default===B.DEFAULTS[k],
          C.TRIAL_KEYS[k].reader,C.TRIAL_KEYS[k].family]),
        foldInvariant:C.TRIAL_INVARIANTS.some(r=>r.low==='pointingFoldStartPalms'&&r.high==='pointingFoldEndPalms'&&r.strict),
        foldRefused:[C.validateTrialPatch({pointingFoldStartPalms:1.55},{pointingFoldEndPalms:1.55}).code,
          refused(()=>B.createPointingIntent({pointingFoldStartPalms:1.6,pointingFoldEndPalms:1.6}))],
        /* Plancher d'essai de la perte : la cadence du guetteur de veille. */
        exitMin:C.TRIAL_KEYS.pointingExitMs.min,wakeInterval:B.DEFAULTS.wakeIntervalMs,
        invariant:C.TRIAL_INVARIANTS.some(r=>r.low==='pointingExitScore'&&r.high==='pointingEnterScore'),
        refused:C.validateTrialPatch({pointingExitScore:.6},{pointingEnterScore:.5}).code,
        states:B.POINTING_STATES});
    """)
    assert set(result["events"]) <= set(result["known"])
    assert sorted(result["keys"]) == sorted(["pointingEnterScore", "pointingExitScore",
                                             "pointingEnterMs", "pointingExitMs", "pointingMotionFloor",
                                             "pointingFoldStartPalms", "pointingFoldEndPalms"])
    fold_reader = "pointingPostureScore, wakePostureScore ← createController"
    for key, same, reader, family in result["trial"]:
        assert same is True and family == "pointing", key
        assert reader == (fold_reader if "Fold" in key else "createPointingIntent"), key
    assert result["foldInvariant"] is True
    assert result["foldRefused"] == ["barehands_trial_invariant_violated", "RangeError"]
    assert result["exitMin"] == 200 == result["wakeInterval"]
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
/* Jusqu'aux négatifs : tout ce qui précède est passé (Slice 07 adaptative :
   tenue et dépôt compris — le dépôt, sans destination possible avec ce banc,
   s'ouvre en revue et se passe aussi). */
const toNegatives=cal=>{cal.start();for(let i=0;i<12&&cal.stepId()!=='natural_motion';i+=1)skipStep(cal);return cal.stepId()};
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
      wakePose:i>=40&&i<85?.9:.05,pointerShown:i>=20&&i<24})]});
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
    assert result["phase"] == "review" and result["step"] == "natural_motion"
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
      // 7A sans faute (pas de C tenu) ; le verdict se lit en revue.
      const verdict7A=feedUntil(cal,{wakePose:.05}).note;
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
            wakePose:.95,pressed:press})]});
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
    # Slice 07 adaptative : la tenue et le dépôt s'insèrent à leur place de
    # jeu ; les négatives restent les dernières.
    assert result["stages"][-2:] == ["natural_motion", "aim_no_click"]
    assert result["version"] == 3  # v3 depuis la Slice 04 adaptative ; un v2 se relit
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


# ------------------------------------------------------------- reprise QA


#: Géométrie réaliste de la QA : repère en paumes (y vers le haut), paume de
#: 0,1 image ; bouts de doigts fléchis joint par joint depuis leur base.
QA_HAND = r"""
const P=(x,y)=>({x:.5+.1*x,y:.8-.1*y,z:0});
function qaHand({index,middle,thumb,ring,pinky}){
  const lm=Array.from({length:21},(_,i)=>P(0,.5+i*.01));
  lm[0]=P(0,0);lm[9]=P(0,1);lm[5]=P(-.3,.95);lm[13]=P(.25,.93);lm[17]=P(.45,.82);
  lm[8]=P(...index);lm[12]=P(...middle);lm[4]=P(...thumb);
  lm[16]=P(...(ring||[.25,.7]));lm[20]=P(...(pinky||[.45,.65]));
  lm[1]=P(-.2,.2);lm[2]=P(-.4,.45);lm[3]=P(-.55,.7);
  lm[6]=P(-.32,1.4);lm[7]=P(-.34,1.65);lm[10]=P(0,1.5);lm[11]=P(0,1.8);
  return lm;
}
const tip=(mx,my,L,deg)=>{let y=my,a=0;for(const l of L){a+=deg;y+=l*Math.cos(a*Math.PI/180)}return [mx,y]};
const IDX=[.45,.27,.22],MID=[.5,.3,.22],RING=[.47,.28,.21],PINKY=[.37,.21,.19];
const relaxed=(d,thumb)=>qaHand({index:tip(-.3,.95,IDX,d),middle:tip(0,1,MID,d),thumb:thumb||[-.7,1.0],
  ring:tip(.25,.93,RING,d),pinky:tip(.45,.82,PINKY,d)});
const aimScore=lm=>Number(B.pointingPostureScore(lm,1,{}).toFixed(3));
"""


def test_a_flat_or_relaxed_still_hand_does_not_aim_and_a_real_aim_does(tmp_path):
    """**Reprise QA, majeur.** Le C et le pré-pincement ne lisaient que le
    pouce et l'index : une main plate (doigts serrés, pouce le long de
    l'index), une main détendue fléchie de 20 à 30°, un pouce posé contre
    l'index marquaient 0,57 à 1, donc un menton posé sur la main montrait un
    curseur. Viser, c'est l'index **seul** déplié : les trois autres doigts
    repliés plafonnent le score. Le C du réveil, lui, ne change pas."""

    result = run_node(tmp_path, QA_HAND + """
      out({
        flat:aimScore(qaHand({index:[-.2,1.9],middle:[0,2],thumb:[-.45,1.2],ring:[.2,1.85],pinky:[.4,1.6]})),
        flatWakeC:Number(B.cPoseScore(qaHand({index:[-.2,1.9],middle:[0,2],thumb:[-.45,1.2],ring:[.2,1.85],pinky:[.4,1.6]}),1).toFixed(3)),
        relaxed20:aimScore(relaxed(20)),relaxed30:aimScore(relaxed(30)),
        thumbResting:[aimScore(relaxed(20,[-.7,1.2])),aimScore(relaxed(20,[-.5,1.3]))],
        c:aimScore(qaHand({index:[-.35,1.9],middle:[0,.7],thumb:[-.9,1.5]})),
        pointing:aimScore(qaHand({index:[-.35,1.9],middle:[0,.7],thumb:[-.55,1.35]})),
        prePinch:aimScore(qaHand({index:[-.35,1.6],middle:[0,.7],thumb:[-.1,1.35]})),
        /* Un doigt illisible ne prouve pas qu'il est replié. */
        unreadable:(()=>{const lm=qaHand({index:[-.35,1.9],middle:[0,.7],thumb:[-.9,1.5]});
          lm[16]={x:NaN,y:NaN};return aimScore(lm)})(),
        /* Pré-pincement dont le majeur touche le pouce : un clic droit, pas
           une visée (le majeur replié à demi ne suffit pas à l'écarter). */
        prePinchSecondary:aimScore(qaHand({index:[-.35,1.6],middle:[-.08,1.33],thumb:[-.1,1.35]})),
        thresholds:[B.DEFAULTS.fingerCurledPalms,B.DEFAULTS.fingerExtendedPalms],
      });
    """)
    assert result["flat"] == 0
    assert result["flatWakeC"] == 1, "le C du réveil n'est pas touché par cette reprise"
    assert result["relaxed20"] < 0.3 and result["relaxed30"] < 0.3
    assert result["thumbResting"] == [0, 0]
    assert result["c"] == 1 and result["pointing"] == 1 and result["prePinch"] == 1
    assert result["unreadable"] == 0
    assert result["prePinchSecondary"] == 0
    assert result["thresholds"] == [1.15, 1.6]


def test_the_entry_hold_is_continuous_and_a_candidate_falls_back(tmp_path):
    """Reprise QA : une image sous `pointingEnterScore` remet le chronomètre
    d'entrée à zéro (la candidate reste tant qu'elle tient
    `pointingExitScore`) ; sous `pointingExitScore`, la candidate retombe."""

    result = run_node(tmp_path, MACHINE + """
      const dip=run({end:700,at:t=>({posture:t<100?1:t<200?.4:1,stillness:1,quality:1})},60);
      const drop=run({end:100,at:t=>({posture:t<20?1:.1,stillness:1,quality:1})},60);
      out({dip,drop});
    """)
    starts = [e[1] for e in result["dip"]["events"] if e[0] == "pointing_intent_start"]
    assert len(starts) == 1 and 350 <= starts[0] <= 367, starts
    assert [s for t, s in result["dip"]["states"] if 100 < t < 200] and all(
        s == "candidate" for t, s in result["dip"]["states"] if 100 < t < 200)
    assert result["drop"]["states"][0][1] == "candidate"
    assert result["drop"]["states"][-1][1] == "none"


def test_a_pinch_approach_engages_and_live_settings_reach_the_intent(tmp_path):
    """Un pincement **en approche** (`pinching`) engage déjà une main plate ;
    `configure` atteint les machines d'intention ; la couture de mesure dit
    quand une cible est résolue (`targeted`)."""

    result = run_node(tmp_path, CONTROLLER + """
      const r=rig({result:{landmarks:[flatHand(1.3)]}});
      await r.c.enable();await r.c.activate();
      r.w.steps(10,33);
      const flat=lastShown(r);
      pose(r,flatHand(.36));r.w.steps(4,33);
      const approach=lastShown(r);
      const contacts=r.c.semantics().pinch.contacts.map(c=>[c.channel,c.state]);
      const posture=B.pointingPostureScore(flatHand(.36),1,{});
      // Réglage vivant : 600 ms d'entrée au lieu de 150.
      const s=rig({result:{landmarks:[aimHand(1.3)]}});
      await s.c.enable();await s.c.activate();
      s.c.configure({pointingEnterMs:600});
      s.w.steps(5,33);
      pose(s,aimHand(.65));s.w.steps(10,33);
      const at330=lastShown(s);
      s.w.steps(10,33);
      const at660=lastShown(s);
      // Une cible résolue pour cette main : la couture le dit.
      const t=rig({result:{landmarks:[aimHand(.65)]}});
      let id=null;
      t.w.deps.interaction.targets=()=>id===null?[]:[{handTrackId:id,channel:'primary'}];
      await t.c.enable();await t.c.activate();
      t.w.steps(3,33);
      id=t.renders.slice(-1)[0][0].id;
      t.w.steps(2,33);
      out({flat,approach,contacts,posture,at330,at660,
        targeted:t.measures.slice(-1)[0][0].targeted,untargeted:t.measures[0][0].targeted});
    """)
    assert result["flat"] == [False]
    assert result["posture"] == 0, "une main plate ne vise pas"
    assert ["primary", "pinching"] in result["contacts"], result["contacts"]
    assert result["approach"] == [True], "un pincement qui approche se voit"
    assert result["at330"] == [False] and result["at660"] == [True]
    assert result["untargeted"] is False and result["targeted"] is True


def test_the_sleep_ring_never_hides_a_wake_and_a_doubtful_c_is_hinted(tmp_path):
    """Reprise QA. Sous des réglages d'essai permis (`wakeScore` 0,3,
    `pointingEnterScore` 0,9), un C moyen fait avancer le réveil sans
    atteindre l'intention : l'anneau se montre **dès que le maintien
    progresse**, et le réveil ne se fait jamais en silence. Et `configure`
    atteint le guetteur réel, qui réveille alors sous le nouveau maintien —
    comme le rejeu de la calibration."""

    result = run_node(tmp_path, CONTROLLER + """
      const r=rig({options:{wakeScore:.3,pointingEnterScore:.9}});
      await r.c.enable();
      const cScore=B.cPoseScore(aimHand(.5),1,{});
      pose(r,aimHand(.5));
      const shown=[];
      for(let i=0;i<8&&r.c.state()==='sleep';i+=1){r.w.step(200);
        shown.push(r.w.log.filter(l=>/^watch:[01]:/.test(l)).slice(-1)[0])}
      const s=rig();
      await s.c.enable();
      s.c.configure({wakeHoldMs:400});
      pose(s,aimHand(.65));
      let samples=0;
      while(s.c.state()==='sleep'&&samples<10){s.w.step(200);samples+=1}
      const replay=s.c.wakeDetector();
      let fired=null;
      for(let t=0;t<=1000&&fired===null;t+=200)if(replay.update(1,t).wake)fired=t;
      out({cScore,shown,woke:r.c.state(),samples,state:s.c.state(),fired});
    """)
    assert 0.3 <= result["cScore"] < 0.9
    assert result["woke"] == "active"
    progressing = [entry for entry in result["shown"] if float(entry.split(":")[2]) > 0]
    assert progressing and all(entry.startswith("watch:1:") for entry in progressing), result["shown"]
    assert result["state"] == "active" and result["samples"] <= 4
    assert result["fired"] == 400


def test_the_overlay_hints_a_doubtful_c_in_sleep(tmp_path):
    """La main vue mais pas crue qui forme le C : anneau pâle, et la pastille
    dit quoi faire."""

    result = run_page(tmp_path, BROWSER + """
      const wake=()=>registry.find(el=>el.className===C.DOM.wakeClass&&el.parent);
      const badge=()=>registry.find(el=>el.className===C.DOM.badgeClass&&el.parent).textContent;
      overlay.watch({present:true,doubtful:true,progress:0,x:10,y:10});
      const doubt=[wake().classList.contains('doubt'),badge()];
      overlay.watch({present:true,progress:.4,x:10,y:10});
      out({doubt,sure:[wake().classList.contains('doubt'),badge()]});
    """)
    assert result["doubt"] == [True, "MAINS · VEILLE · rapprochez la main"]
    assert result["sure"] == [False, "MAINS · VEILLE 40%"]


def test_the_negative_exercise_counts_only_what_it_should(tmp_path):
    """Reprise QA : l'exposition exclut les trous (`negativeGapMs`) ; le
    réveil rejoué ignore les mains que la veille ne croirait pas et suit la
    cadence du guetteur ; une échéance au-delà de `negativeMinMs` rend son
    verdict ; en 7B un point ne se compte pas sous un pincement, et c'est la
    main **qui vise** qui compte."""

    result = run_node(tmp_path, NEGATIVE + """
      const logs=[];
      const opts=Object.assign({},NEG_OPTIONS,{negativeMs:20000});
      const cal=calOf({options:opts,log:(l,m,d)=>logs.push([m,d])});
      toNegatives(cal);readOn(cal);
      /* Les instants où le guetteur de veille rejoué mesure : la même règle
         (un écart d'au moins `wakeIntervalMs`), depuis la première image
         mesurée de l'exercice. */
      let fed=0,sampledAt=-Infinity;
      const f=(dt,over)=>{clock+=dt;fed+=1;
        const sample=fed>2&&clock-sampledAt>=B.DEFAULTS.wakeIntervalMs;
        if(sample)sampledAt=clock;
        const o=typeof over==='function'?over(sample):over;
        cal.feed({now:clock,hands:[hand(Object.assign({handTrackId:1,wakePose:.05},o||{}))]})};
      f(33);f(33);                               // armement
      for(let i=0;i<10;i+=1)f(33);               // 297 ms exposées
      f(400);                                    // un trou : n'expose rien
      for(let i=0;i<10;i+=1)f(33);
      /* Un C tenu par une main **douteuse** : la veille ne la croirait pas. */
      for(let i=0;i<50;i+=1)f(33,{wakePose:.95,quality:.1});
      /* Puis une main sûre, sans C, plus longtemps que la grâce du guetteur :
         un réveil déjà compté ne masque pas le suivant. */
      for(let i=0;i<20;i+=1)f(33);
      /* Un C qui n'apparaît qu'aux images où le guetteur de veille mesure
         (une toutes les sept, soit 231 ms) : la veille réveillerait, un
         rejeu à pleine cadence ne verrait qu'un C clignotant. */
      for(let i=0;i<63;i+=1)f(33,sample=>({wakePose:sample?.95:.05}));
      const exposure=(()=>{clock+=9000;cal.tick();return logs.find(l=>l[0]==='[barehands] calibration.negatives')})();
      const verdict=cal.phase();
      const kinds=cal.session().falseEvents.map(e=>e.falseKind);
      /* 7B : un pincement tenu sur le point n'est pas une visée ; une main au
         repos (jeton caché) ne cache pas celle qui vise. */
      verdictOver(cal);readOn(cal);
      const spot=[282,259];
      const two=(over)=>{clock+=33;cal.feed({now:clock,hands:[
        hand({handTrackId:2,pointerShown:false,wakePose:.05}),
        hand(Object.assign({handTrackId:1,pointerShown:true,pointerX:spot[0],pointerY:spot[1],wakePose:.05},over||{}))]})};
      for(let i=0;i<40;i+=1)two({pressed:true});
      const whilePressed=cal.aim().hits;
      for(let i=0;i<25;i+=1)two({});
      out({exposure:exposure&&exposure[1].exposureMs,verdict,kinds,whilePressed,afterDwell:cal.aim().hits});
    """, name="negRework")
    # Le trou de 400 ms est exclu, et les images d'une main douteuse
    # n’exposent rien : 9 + 10 + 19 + 63 intervalles de 33 ms.
    assert result["exposure"] == 33 * (9 + 10 + 19 + 63), result["exposure"]
    assert result["verdict"] == "review", "une exposition au-delà du minimum rend son verdict"
    assert result["kinds"] == ["unintended_wake"], result["kinds"]
    assert result["whilePressed"] == 0
    assert result["afterDwell"] == 1


# ------------------------------------------------ « le C qui réveille est le C qui vise »


#: Les géométries de la QA (`posture2`) : doigts fléchis joint par joint, vus
#: de face (la flexion raccourcit le doigt) ou de côté (elle le couche vers le
#: pouce) ; le pouce posé à un écart donné du bout de l'index.
POSTURE2 = r"""
const P2=(x,y)=>({x:.5+.1*x,y:.8-.1*y,z:0});
const MCP={index:[-.3,.95],middle:[0,1],ring:[.25,.93],pinky:[.45,.82]};
const LEN={index:[.45,.27,.22],middle:[.5,.3,.22],ring:[.47,.28,.21],pinky:[.37,.21,.19]};
const bend=(f,d,side)=>{let [x,y]=MCP[f],a=0;for(const l of LEN[f]){a+=d;
  if(side)x-=l*Math.sin(a*Math.PI/180);y+=l*Math.cos(a*Math.PI/180)}return [x,y]};
function hand2(tips,thumb){
  const lm=Array.from({length:21},(_,i)=>P2(0,.5+i*.01));
  lm[0]=P2(0,0);lm[9]=P2(0,1);lm[5]=P2(...MCP.index);lm[13]=P2(...MCP.ring);lm[17]=P2(...MCP.pinky);
  lm[1]=P2(-.2,.2);lm[2]=P2(-.4,.45);lm[3]=P2(-.55,.7);
  lm[8]=P2(...tips.index);lm[12]=P2(...tips.middle);lm[16]=P2(...tips.ring);lm[20]=P2(...tips.pinky);lm[4]=P2(...thumb);
  return lm;
}
const thumbAt=(idx,gap)=>[idx[0]+gap*Math.cos(225*Math.PI/180),idx[1]+gap*Math.sin(225*Math.PI/180)];
const wholeC=(d,side)=>{const t={index:bend('index',d,side),middle:bend('middle',d,side),
  ring:bend('ring',d,side),pinky:bend('pinky',d,side)};return hand2(t,thumbAt(t.index,.65))};
const indexC=(d,side,gap)=>{const idx=bend('index',8,side);
  return hand2({index:idx,middle:bend('middle',d,side),ring:bend('ring',d,side),pinky:bend('pinky',d,side)},
    thumbAt(idx,gap===undefined?.65:gap))};
const FLAT={index:[-.2,1.9],middle:[0,2],ring:[.2,1.85],pinky:[.4,1.6]};
const flat2=()=>hand2(FLAT,[-.45,1.2]);
const relaxed2=(d,thumb)=>hand2({index:bend('index',d),middle:bend('middle',d),ring:bend('ring',d),
  pinky:bend('pinky',d)},thumb||[-.7,1.0]);
const two=lm=>[Number(B.pointingPostureScore(lm,1,{}).toFixed(2)),Number(B.wakePostureScore(lm,1,{}).toFixed(2))];
"""


def test_the_posture_table_accepts_curved_fingers_and_rejects_flat_or_relaxed_hands(tmp_path):
    """Le tableau que la décision 46 publie, pour la visée **et** le réveil
    (même facteur de repli). Ce qui se perd est dit : un C de toute la main
    fléchi de moins de ~45°, ou un C à l'index seul dont les autres doigts ne
    sont fléchis que de 30°/joint, ont leurs bouts à la même portée qu'une
    main détendue à 20–30° — la géométrie ne les sépare pas, et la reprise
    choisit de rejeter la main détendue."""

    result = run_node(tmp_path, POSTURE2 + """
      out({
        flat:two(flat2()),flatC:Number(B.cPoseScore(flat2(),1).toFixed(2)),
        relaxed20:two(relaxed2(20)),relaxed30:two(relaxed2(30)),
        thumbAlong:[two(relaxed2(20,[-.5,1.3])),two(relaxed2(30,[-.5,1.3]))],
        wholeSide45:two(wholeC(45,true)),wholeSide40:two(wholeC(40,true)),wholeFront25:two(wholeC(25,false)),
        indexFront40:two(indexC(40,false)),indexSide50:two(indexC(50,true)),indexFront30:two(indexC(30,false)),
        prePinchFront40:two(indexC(40,false,.3)),
        okSign:two(hand2({index:bend('index',25,true),middle:bend('middle',0,true),ring:bend('ring',0,true),
          pinky:bend('pinky',0,true)},thumbAt(bend('index',25,true),.3))),
        defaults:[B.DEFAULTS.pointingFoldStartPalms,B.DEFAULTS.pointingFoldEndPalms],
      });
    """)
    # Rejets : main plate (dont le C seul valait 1), détendue, pouce le long.
    assert result["flat"] == [0, 0] and result["flatC"] == 1
    assert result["relaxed20"][0] < 0.3 and result["relaxed20"][1] < 0.3
    assert result["relaxed30"][0] < 0.3 and result["relaxed30"][1] < 0.3
    assert all(score < 0.3 for pair in result["thumbAlong"] for score in pair)
    # Acceptations : doigts courbés.
    assert result["wholeSide45"][0] >= 0.5 and result["wholeSide45"][1] >= 0.5
    assert result["indexFront40"] == [1, 1] and result["indexSide50"][0] >= 0.5
    assert result["prePinchFront40"][0] == 1
    # Perdus, et publiés comme tels.
    assert result["wholeSide40"][0] < 0.5 and result["wholeFront25"] == [0, 0]
    assert result["indexFront30"][0] < 0.3
    # Le « OK » ne vise pas avant le contact : l'approche du pincement engage.
    assert result["okSign"] == [0, 0]
    assert result["defaults"] == [1.45, 1.6]


def test_a_flat_hand_cannot_wake_and_a_curved_c_wakes_then_aims(tmp_path):
    """Même facteur en veille : une main plate, pouce le long de l'index — C
    parfait au sens de `cPoseScore` — ne fait ni anneau ni réveil ; un C de
    toute la main, doigts courbés, réveille puis vise."""

    result = run_node(tmp_path, CONTROLLER + POSTURE2 + """
      const flat=rig({result:{landmarks:[flat2()]}});
      await flat.c.enable();
      flat.w.steps(40,200);
      const flatRing=flat.w.log.filter(l=>/^watch:1:/.test(l)).length;
      const curved=rig({result:{landmarks:[wholeC(45,true)]}});
      await curved.c.enable();
      let n=0;while(curved.c.state()==='sleep'&&n<20){curved.w.step(200);n+=1}
      const woke=curved.c.state();
      curved.w.steps(10,33);
      out({flat:flat.c.state(),flatRing,woke,samples:n,aims:lastShown(curved)});
    """)
    assert result["flat"] == "sleep" and result["flatRing"] == 0
    assert result["woke"] == "active" and result["samples"] <= 7
    assert result["aims"] == [True]


def test_live_fold_settings_reach_the_watcher_and_the_aim(tmp_path):
    """Les options vivantes atteignent les deux scores de posture : resserrer
    le repli par `configure` empêche le réveil (guetteur) et la visée
    (interaction) d'une main dont les doigts sont à 1,5 paume."""

    result = run_node(tmp_path, CONTROLLER + """
      const loose=aimHand(.65);
      for(const i of [12,16,20])loose[i]={x:.5,y:.5,z:0};   // bouts à 1,5 paume
      const a=rig({result:{landmarks:[loose]}});
      await a.c.enable();
      a.c.configure({pointingFoldStartPalms:1.3,pointingFoldEndPalms:1.45});
      a.w.steps(15,200);
      const b=rig({result:{landmarks:[loose]}});
      await b.c.enable();await b.c.activate();
      b.w.steps(10,33);
      const before=lastShown(b);
      b.c.configure({pointingFoldStartPalms:1.3,pointingFoldEndPalms:1.45});
      b.w.steps(15,33);
      const c=rig({result:{landmarks:[loose]}});
      await c.c.enable();c.w.steps(15,200);
      out({strict:a.c.state(),before,after:lastShown(b),loose:c.c.state(),
        score:B.wakePostureScore(loose,1,{})});
    """)
    assert 0.5 <= result["score"] < 1
    assert result["loose"] == "active", "témoin : aux réglages d'usine, cette main réveille"
    assert result["strict"] == "sleep"
    assert result["before"] == [True] and result["after"] == [False]


def test_a_setting_that_is_not_the_watchers_keeps_a_wake_hold_in_progress(tmp_path):
    """`configure` ne reconstruit le guetteur que pour **ses** réglages : un
    maintien de C en cours survit à un réglage d'intention, et repart à zéro
    sous un réglage de réveil."""

    result = run_node(tmp_path, CONTROLLER + """
      const play=patch=>{
        const r=rig({result:{landmarks:[aimHand(.65)]}});
        return r.c.enable().then(()=>{
          r.w.steps(4,200);                       // 600 ms de C tenus
          r.c.configure(patch);
          let n=0;while(r.c.state()==='sleep'&&n<20){r.w.step(200);n+=1}
          return n;
        });
      };
      out({other:await play({pointingEnterMs:200}),wake:await play({wakeScore:.45})});
    """)
    assert result["other"] <= 2, "le maintien de 600 ms est gardé"
    assert result["wake"] >= 5, "un réglage du guetteur repart à zéro"


def test_the_c_stage_judges_the_wake_posture_and_names_flat_fingers(tmp_path):
    """L'étape du C répond à « est-ce que mon C réveille ? » sur la posture
    **du réveil** (`wakePose`) : un C parfait aux doigts dépliés échoue, et la
    phrase dit de courber les trois autres doigts."""

    result = run_node(tmp_path, DOM + DRIVER + """
      const cal=calOf();cal.start();
      feedUntil(cal,{});
      const c={cPose:.9,gapPalms:.65,indexReachPalms:1.8,secondaryRatio:.9};
      const note=feedUntil(cal,Object.assign({wakePose:.1},c)).note;
      out({note,step:cal.stepId()});
    """, name="cFlat")
    assert result["step"] == "pinch_primary"
    assert "courbez-les" in result["note"] and "main plate" in result["note"]


# ------------------------------------------------ le C de l'utilisateur, réglé
#
# Retour du 28/09/2026 (retours-utilisateur/1790590267) : l'étape du C refusait
# « pouce et index sont trop proches » un C serré que l'utilisateur voulait
# comme réveil, et un essai `wakeScore` 0,5 → 0,4 n'y changeait rien. Le
# plancher d'écart du C (`wakeGapMin`) est désormais une clé d'essai rangée,
# et l'étape juge contre la bande **effective** du moteur.


def test_a_tight_c_wakes_once_the_c_floor_is_lowered_with_the_release(tmp_path):
    """Le vrai contrôleur, la vraie géométrie : un C à 0,44 paume ne réveille
    pas aux réglages d'usine (bande tenue à partir de 0,499), et réveille sous
    `wakeGapMin` 0,37 avec le relâchement primaire abaissé sous lui — ce que
    l'assistant pose en essai."""

    result = run_node(tmp_path, CONTROLLER + """
      const play=patch=>{
        const r=rig({result:{landmarks:[aimHand(.44)]}});
        return r.c.enable().then(()=>{
          if(patch)r.c.configure(patch);
          r.w.steps(15,200);
          return {state:r.c.state(),band:r.c.wakeOptions()};
        });
      };
      const tuned={wakeGapMin:.37,releaseRatio:.33};
      out({factory:await play(null),tuned:await play(tuned),
        scores:[B.wakePostureScore(aimHand(.44),1,{}),B.wakePostureScore(aimHand(.44),1,tuned)]});
    """)
    assert result["scores"][0] < 0.5 <= result["scores"][1]
    assert result["factory"]["state"] == "sleep", "témoin : ce C serré ne réveille pas aux réglages d'usine"
    assert result["tuned"]["state"] == "active"
    assert result["factory"]["band"]["wakeGapMin"] == 0.46
    assert result["tuned"]["band"]["wakeGapMin"] == 0.37 and result["tuned"]["band"]["releaseRatio"] == 0.33


def test_the_c_stage_judges_against_the_effective_wake_band_not_the_factory_one(tmp_path):
    """L'étape du C lit la bande du réveil **chez le moteur** (`wakeOptions`),
    essai en cours compris. L'essai de la séance du 28/09 (`wakeScore` 0,4) :
    un C tenu à 0,45 échouait encore, jugé contre 0,5 ; il passe désormais. Un
    refus « trop proches » dit l'écart mesuré et le réglage, et l'écart du C
    est rangé comme mesure de séance (`c_pose_gap_palms`)."""

    result = run_node(tmp_path, DOM + DRIVER + """
      const c={cPose:.45,wakePose:.45,gapPalms:.48,indexReachPalms:1.8,secondaryRatio:.9};
      const play=extra=>{
        const logs=[];
        const cal=calOf(Object.assign({log:(l,m,d)=>logs.push([m,d])},extra||{}));cal.start();
        feedUntil(cal,{});
        const r=feedUntil(cal,c);
        const rows=Object.values(cal.session().measurements).filter(m=>m&&m.c_pose_gap_palms!==undefined);
        const detail=(logs.filter(([m])=>/calibration c_pose/.test(m)).pop()||[])[1]||{};
        return {status:r.review&&r.review.status,note:r.note,rows,cause:detail.cause||null,
          gapMin:detail.gapMin,lines:r.review?r.review.lines.map(l=>l.metric):null};
      };
      out({factory:play(),trial:play({wakeOptions:()=>({wakeScore:.4})}),
        floor:play({wakeOptions:()=>({wakeScore:.5,wakeGapMin:.4})}),
        tight:play({wakeOptions:()=>({wakeScore:.5})})});
    """, name="cBand")
    assert result["factory"]["status"] == "failed", "témoin : jugé contre la bande d'usine (0,5)"
    assert result["factory"]["cause"] == "gap_low"
    assert "trop proches" in result["factory"]["note"]
    assert "0,48 paume" in result["factory"]["note"] and "0,50 paume" in result["factory"]["note"]
    assert result["trial"]["status"] == "ok", "l'essai wakeScore 0,4 atteint l'étape"
    assert result["tight"]["status"] == "failed" and result["tight"]["cause"] == "gap_low"
    # Un plancher abaissé : l'écart n'est plus « trop proche » ; reste le score
    # (0,45 sous 0,5), dit comme tel.
    assert result["floor"]["cause"] == "score"
    assert result["floor"]["gapMin"] == pytest.approx(0.445)
    for run in result.values():
        assert run["rows"] == [{"c_pose_gap_palms": 0.48}]
        assert run["lines"] == ["c_pose_gap_palms"]

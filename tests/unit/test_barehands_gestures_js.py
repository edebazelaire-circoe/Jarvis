"""Moteur de gestes sémantiques et intention de pincement (Slice 04), exécutés
par node.

Une main devant une caméra ne se teste pas ici. Ce qui l'est : que chaque
posture se déclenche sur la sienne et sur aucune autre ; qu'un geste global ne
vole pas la main à une manipulation capturée, et que la seule exception
déclarée — la main ouverte, sortie de secours — la vole bel et bien ; que les
deux canaux de pincement (pouce-index, pouce-majeur) soient indépendants et ne
se déclenchent pas l'un pour l'autre ; qu'une **fermeture de main entière** ne
passe pour aucun des deux ; que l'hystérésis empêche le clignotement au seuil ;
et qu'un clic se distingue d'un glissement par la durée, le déplacement et
l'**immobilité publiée par la Slice 03**.

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
    script = tmp_path / "barehands-gestures.cjs"
    script.write_text(
        f"const B=require({json.dumps(str(SCRIPT))});\n"
        f"const C=require({json.dumps(str(CONTRACTS))});\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "const refused=fn=>{try{fn();return null}catch(e){return e.code||e.name}};\n"
        "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


#: Main synthétique, en coordonnées d'image normalisées et à aspect 1. Le
#: poignet est en bas, la paume monte, et les quatre doigts se posent en
#: éventail — chacun à `reach` paumes du poignet **sur son rayon**, si bien que
#: la portée lue est exactement celle demandée, quel que soit l'angle. Le pouce
#: se pose à `gap` paumes du bout du doigt nommé par `pinch` : c'est lui qui
#: fait un pincement primaire, un pincement secondaire ou un C.
HAND = """
const RAD=d=>d*Math.PI/180;
const FAN={index:-25,middle:-8,ring:8,pinky:25};
function hand(opts){
  const o=Object.assign({cx:.5,cy:.5,palm:.2,index:1.85,middle:2,ring:1.85,pinky:1.7,
    pinch:'index',gap:.65,thumbAngle:-70,thumbReach:1.2},opts||{});
  const lm=Array.from({length:21},()=>({x:o.cx,y:o.cy,z:0}));
  const wrist={x:o.cx,y:o.cy+o.palm/2,z:0};
  lm[0]=wrist;lm[9]={x:o.cx,y:o.cy-o.palm/2,z:0};
  const at=(deg,reach)=>({x:wrist.x+o.palm*reach*Math.sin(RAD(deg)),
                          y:wrist.y-o.palm*reach*Math.cos(RAD(deg)),z:0});
  lm[8]=at(o.indexAngle===undefined?FAN.index:o.indexAngle,o.index);
  lm[12]=at(FAN.middle,o.middle);
  lm[16]=at(FAN.ring,o.ring);lm[20]=at(FAN.pinky,o.pinky);
  const anchor=o.pinch==='index'?lm[8]:o.pinch==='middle'?lm[12]:null;
  lm[4]=anchor?{x:anchor.x+o.palm*o.gap,y:anchor.y,z:0}:at(o.thumbAngle,o.thumbReach);
  return lm;
}
/* Les cinq postures de référence. `C_HAND` : index tendu, les trois autres
   repliés, pouce écarté sans toucher. `FIST` : tout replié. `OPEN` : tout
   tendu, pouce au large. `PRIMARY`/`SECONDARY` : le pouce touche l'index ou le
   majeur (décisions 20 et 21). */
const C_HAND=o=>hand(Object.assign({middle:.9,ring:.9,pinky:.9,gap:.65},o||{}));
const FIST=o=>hand(Object.assign({index:.9,middle:.9,ring:.9,pinky:.9,gap:.18},o||{}));
const OPEN=o=>hand(Object.assign({pinch:null},o||{}));
const PRIMARY=o=>hand(Object.assign({pinch:'index',gap:.15},o||{}));
const SECONDARY=o=>hand(Object.assign({pinch:'middle',gap:.15},o||{}));
/* Le clic droit le plus dangereux : pouce sur le majeur, index **écarté**.
   Les quatre doigts sont tendus et le pouce est loin de l'index — tout ce qui
   fait une main ouverte, sur une main qui pince. */
const SPLAYED=o=>SECONDARY(Object.assign({indexAngle:-45},o||{}));

/* Entrée des moteurs. `x`/`y` sont des pixels de la fenêtre — la position
   filtrée de la Slice 03 — et `anchorX`/`anchorY` le point de visée figé. */
const input=(id,landmarks,extra)=>Object.assign(
  {handTrackId:id,landmarks,x:100,y:100,anchorX:100,anchorY:100,stillness:1,quality:1},
  extra||{});
const pinchFrames=(engine,steps)=>{
  const events=[];
  for(const step of steps)events.push(...engine.update(step).events);
  return events;
};
const gestureFrames=(engine,steps)=>{
  const events=[],suppressed=[];
  for(const step of steps){const o=engine.update(step);
    events.push(...o.events);suppressed.push(...o.suppressed)}
  return {events,suppressed};
};
const names=list=>list.map(e=>e.gesture+':'+e.phase);
const phases=list=>list.map(e=>e.channel+':'+e.phase);
"""


# ------------------------------------------------------------- vocabulaire


def test_each_posture_fires_on_its_own_hand_and_on_none_of_the_others(tmp_path):
    """La question de fond de la Slice : cinq gestes, et aucun qui se déclenche
    sur la main d'un autre. Trois postures se lisent sur la même main, donc
    elles ne peuvent pas être trois seuils indépendants — chacune doit exclure
    les deux autres **par construction** :

    - le poing veut quatre doigts repliés, la main ouverte les veut tendus :
      elles s'excluent par l'extension ;
    - le C et la main ouverte partagent des doigts, mais pas l'écart du pouce.
      `wakeGapMax` est, par sa propre définition (Slice 02), « l'écart où le
      score du C tombe à zéro côté main ouverte » : le relire ici est ce qui
      rend les deux exclusives sans ajouter un seuil de plus à calibrer.

    Et les deux pincements ne sont **aucune** des trois : un pincement en cours
    ne doit jamais réveiller ni fermer quoi que ce soit."""

    result = run_node(tmp_path, HAND + """
      const read=lm=>{const p=B.handPosture(lm,1,{});
        return {c:Number(p.scores.c_pose.toFixed(3)),open:Number(p.scores.open_palm.toFixed(3)),
                fist:Number(p.scores.fist.toFixed(3)),gap:Number(p.gapPalms.toFixed(3))}};
      const D=B.DEFAULTS;
      out({
        c:read(C_HAND()),open:read(OPEN()),fist:read(FIST()),
        primary:read(PRIMARY()),secondary:read(SECONDARY()),splayed:read(SPLAYED()),
        /* Les deux écarts que la garantie doit couvrir : un clic droit laisse
           l'écart pouce-index **dans la bande du C**, et l'index écarté le
           pousse au-delà de `wakeGapMax`, là où vit la main ouverte. */
        bands:[Number(B.DEFAULTS.wakeGapMin.toFixed(3)),Number(B.DEFAULTS.wakeGapMax.toFixed(3))],
        vocabulary:B.GESTURES,postures:B.POSTURE_GESTURES,
        /* Mesurée en paumes : la même main deux fois plus loin de la caméra
           donne exactement les mêmes scores. */
        scaleFree:JSON.stringify(read(C_HAND()))===JSON.stringify(read(C_HAND({palm:.08}))),
        /* Une main partielle ne porte pas de posture : elle est sautée, elle
           ne se lit pas « posture relâchée ». */
        partial:[B.handPosture(C_HAND().slice(0,13),1,{}),
                 B.handPosture([],1,{}),B.handPosture(null,1,{})],
        boundary:[D.fingerCurledPalms,D.fingerExtendedPalms,D.wakeGapMax],
        postureScore:D.postureScore,
      });
    """)
    assert result["vocabulary"] == ["c_pose", "open_palm", "fist", "double_close", "clap"]
    assert result["postures"] == ["c_pose", "open_palm", "fist"]
    # Chaque posture marque 1 chez elle et 0 partout ailleurs.
    assert result["c"]["c"] == 1 and result["c"]["open"] == 0 and result["c"]["fist"] == 0
    assert result["open"]["open"] == 1 and result["open"]["c"] == 0 and result["open"]["fist"] == 0
    assert result["fist"]["fist"] == 1 and result["fist"]["c"] == 0 and result["fist"]["open"] == 0
    # Un pincement n'est aucune des trois : aucun des trois scores n'atteint le
    # seuil qui ferait compter une posture. Et ce n'est pas gratuit — les deux
    # formes ci-dessous sont précisément celles qui, sans la garantie,
    # marqueraient plein :
    #   * le clic droit pousse le pouce **de côté**, pas vers l'index, donc son
    #     écart pouce-index atterrit en plein milieu de la bande du C — un clic
    #     droit tenu une seconde réveillait la veille ;
    #   * le même clic droit avec l'index écarté a quatre doigts tendus et le
    #     pouce au large : tout ce qui définit une main ouverte.
    for channel in ("primary", "secondary", "splayed"):
        scores = [result[channel][key] for key in ("c", "open", "fist")]
        assert max(scores) < result["postureScore"], (channel, scores)
    low, high = result["bands"]
    assert low < result["secondary"]["gap"] < high, "le clic droit vise bien la bande du C"
    assert result["splayed"]["gap"] > high, "et celui-ci vise la main ouverte"
    # La main ouverte est au-delà de la bande du C ; le C reste dedans.
    assert result["open"]["gap"] > result["boundary"][2] > result["c"]["gap"]
    assert result["scaleFree"] is True
    assert result["partial"] == [None, None, None]


def test_a_posture_is_announced_only_once_it_has_been_held(tmp_path):
    """Une posture qui s'annonce à la première image bonne clignote : la main
    traverse le champ, passe une image par un poing approximatif et une action
    part. `postureHoldMs` est ce qui l'en empêche, et la progression qu'il
    produit est ce que la Slice 05 dessinera.

    Le temps non observé ne se crédite pas — troisième application dans ce
    fichier de la leçon de la reprise de la Slice 02 : une posture qui vient
    d'apparaître ne gagne pas le temps passé sans elle, et un trou plus long
    que `lostGraceMs` la fait recommencer."""

    result = run_node(tmp_path, HAND + """
      const engine=B.createGestureEngine({});
      const at=(now,lm)=>({hands:lm?[{handTrackId:0,landmarks:lm}]:[],now,aspect:1});
      const held=[];
      /* Deux images de main ouverte **avant** le poing : la main est là, vue,
         mesurée — mais elle ne tient pas encore la posture. Ce temps-là ne doit
         rien créditer au poing qui suit, sinon la première image de poing
         arrive avec 200 ms d'avance. */
      engine.update(at(-200,OPEN()));engine.update(at(-100,OPEN()));
      for(const now of [0,100,200,300])held.push(engine.update(at(now,FIST())));
      const released=engine.update(at(400,OPEN()));
      // Un trou plus long que la grâce d'identité : tout recommence.
      const engine2=B.createGestureEngine({});
      const far=[engine2.update(at(0,FIST())),engine2.update(at(5000,FIST())),
                 engine2.update(at(5100,FIST()))];
      out({
        phases:held.map(h=>names(h.events).join(',')),
        progress:held.map(h=>h.postures.length?Number(h.postures[0].progress.fist.toFixed(2)):null),
        released:names(released.events),
        /* Une posture relâchée puis reprise ne repart pas de son acquis. */
        farPhases:far.map(f=>names(f.events).join(',')),
      });
    """)
    # Première image : la posture apparaît, elle ne crédite rien.
    assert result["progress"] == [0.0, 0.4, 0.8, 1.0]
    # Tant qu'elle monte, elle se dit « hold » avec sa progression ; à
    # l'arrivée, et une seule fois, « start ».
    assert result["phases"] == ["fist:hold", "fist:hold", "fist:hold", "fist:start"]
    # Relâcher dans une main ouverte, c'est aussi commencer une main ouverte :
    # les postures ne s'attendent pas les unes les autres.
    assert result["released"] == ["open_palm:hold", "fist:end"]
    # Deux mesures à 5 s d'écart ne font pas un maintien : la seconde rouvre.
    assert result["farPhases"] == ["fist:hold", "fist:hold", "fist:hold"]


# ------------------------------------------------------------- arbitrage


def test_a_global_gesture_does_not_steal_an_active_capture(tmp_path):
    """Architecture §4 : « un geste global ne vole pas la main à une
    manipulation capturée, **sauf autorisation explicite** ». Trois choses à
    prouver, parce qu'une seule ne suffirait pas :

    1. le geste global se tait pendant une capture ;
    2. l'autorisation explicite existe vraiment — sans elle la branche serait
       du code mort. La main ouverte est la sortie de secours : une
       manipulation qu'on ne peut pas abandonner est un piège ;
    3. la portée `hand` ne se tait que pour **sa** main : décision 12, deux
       mains manipulent indépendamment, et la main libre garde ses gestes.

    Et l'arbitrage se décide à la publication, pas à la reconnaissance : la
    posture garde sa progression pendant la capture, sinon relâcher ferait
    réapparaître un geste à moitié construit."""

    result = run_node(tmp_path, HAND + """
      const step=(engine,now,hands,captured)=>engine.update({hands,now,aspect:1,captured});
      const two=(a,b)=>[{handTrackId:0,landmarks:a},{handTrackId:1,landmarks:b}];
      // La main 0 tient une capture ; la main 1 est libre.
      const engine=B.createGestureEngine({});
      const held=[];
      for(const now of [0,100,200,300])held.push(step(engine,now,two(FIST(),FIST()),[0]));
      const last=held[held.length-1];
      // Main ouverte des deux côtés : la sortie de secours passe malgré tout.
      const palm=B.createGestureEngine({});
      const opened=[];
      for(const now of [0,100,200,300])opened.push(step(palm,now,two(OPEN(),OPEN()),[0,1]));
      /* Un geste **global** pendant qu'une seule des deux mains est capturée :
         c'est la portée, pas l'identité de la main, qui doit le faire taire.
         La main 1 ne tient rien, et son claquement se tait quand même. */
      const global_=B.createGestureEngine({});
      const clap=(dx,now,captured)=>global_.update({now,aspect:1,captured,hands:[
        {handTrackId:0,landmarks:OPEN({cx:.5-dx})},{handTrackId:1,landmarks:OPEN({cx:.5+dx})}]});
      clap(.2,0,[0]);
      const clapped=clap(.025,100,[0]);
      const free=B.createGestureEngine({});
      const freeClap=(dx,now)=>free.update({now,aspect:1,captured:[],hands:[
        {handTrackId:0,landmarks:OPEN({cx:.5-dx})},{handTrackId:1,landmarks:OPEN({cx:.5+dx})}]});
      freeClap(.2,0);
      const clappedFree=freeClap(.025,100);
      out({
        published:names(last.events),suppressed:last.suppressed.map(e=>e.gesture+':'+e.handTrackId+':'+e.reason),
        globalDuringCapture:[names(clapped.events).filter(n=>n.startsWith('clap')),
                             clapped.suppressed.map(e=>e.gesture+':'+e.handTrackId+':'+e.reason)],
        globalWhenFree:names(clappedFree.events).filter(n=>n.startsWith('clap')),
        // Le geste de la main capturée est reconnu quand même : sa progression
        // a bien couru pendant qu'il se taisait.
        progress:last.postures.map(p=>[p.handTrackId,Number(p.progress.fist.toFixed(2))]),
        escape:names(opened[opened.length-1].events),
        escapeSuppressed:opened[opened.length-1].suppressed.length,
        rules:[C.gestureScope('open_palm'),C.gestureScope('fist'),C.gestureScope('clap'),
               C.gestureAllowedDuringCapture('open_palm'),C.gestureAllowedDuringCapture('fist')],
        unknownRule:refused(()=>C.gestureScope('wave')),
        /* Le contrat et le moteur lisent la même table. */
        parity:B.GESTURES.every(g=>B.GESTURE_RULES[g].scope===C.gestureScope(g)
          &&B.GESTURE_RULES[g].duringCapture===C.gestureAllowedDuringCapture(g)),
        shared:[C.isGestureSuppressed('clap',null,[0]),C.isGestureSuppressed('clap',null,[]),
                C.isGestureSuppressed('fist',1,[0]),C.isGestureSuppressed('fist',0,[0]),
                C.isGestureSuppressed('open_palm',0,[0])],
      });
    """)
    # La main capturée ne publie rien ; la main libre publie son poing.
    assert result["published"] == ["fist:start"]
    assert result["suppressed"] == ["fist:0:capture_active"]
    assert result["progress"] == [[0, 1.0], [1, 1.0]]
    # L'autorisation explicite : les deux mains sont capturées, la main ouverte
    # passe tout de même — deux fois, une par main.
    assert result["escape"] == ["open_palm:start", "open_palm:start"]
    assert result["escapeSuppressed"] == 0
    # Le claquement n'appartient à aucune main : sans la portée, il ne serait
    # jamais étouffé, puisque son `handTrackId` est `null`.
    assert result["globalDuringCapture"] == [[], ["clap:null:capture_active"]]
    assert result["globalWhenFree"] == ["clap:end"]
    assert result["rules"] == ["global", "hand", "global", True, False]
    assert result["unknownRule"] == "barehands_gesture_unknown"
    assert result["parity"] is True
    # `global` se tait dès qu'une main quelconque tient ; `hand` seulement pour
    # la sienne ; l'autorisée ne se tait jamais.
    assert result["shared"] == [True, False, False, True, False]


def test_a_double_close_needs_two_closures_inside_the_window(tmp_path):
    """Le double se compte sur deux fermetures **commencées** dans
    `doubleCloseMs`. Trop lent, ce sont deux poings ; trop rapproché sans
    réouverture, c'est un poing tenu. Et le poing garde ses propres
    événements : un consommateur lié au poing et un consommateur lié au double
    ne se volent pas, ils se choisissent à la liaison."""

    result = run_node(tmp_path, HAND + """
      const sequence=(gaps,engine)=>{
        const events=[];
        for(const [now,lm] of gaps)events.push(...engine.update(
          {hands:[{handTrackId:0,landmarks:lm}],now,aspect:1}).events);
        return names(events).filter(n=>!n.endsWith(':hold'));
      };
      // Deux fermetures : 0-250 (start), ouvert, 400-650 (start) — 400 ms
      // entre les deux débuts, dans la fenêtre de 600.
      const quick=sequence([[0,FIST()],[250,FIST()],[300,OPEN()],
                            [400,FIST()],[650,FIST()]],B.createGestureEngine({}));
      /* Les mêmes, espacées de 700 ms entre les deux **débuts** : deux poings,
         pas un double. Les images restent dans la grâce d'identité — au-delà, la
         main serait purgée et le double ne serait pas refusé par la fenêtre
         mais par l'oubli, ce qui ne prouverait rien de la fenêtre. */
      const slow=sequence([[0,FIST()],[250,FIST()],[300,OPEN()],[500,OPEN()],
                           [700,FIST()],[800,FIST()],[950,FIST()]],B.createGestureEngine({}));
      // Un poing simplement tenu longtemps n'est pas un double.
      const holdOn=sequence([[0,FIST()],[250,FIST()],[500,FIST()],[750,FIST()],
                             [1000,FIST()]],B.createGestureEngine({}));
      out({quick,slow,holdOn,windowMs:B.DEFAULTS.doubleCloseMs});
    """)
    assert result["windowMs"] == 600
    assert result["quick"] == ["fist:start", "fist:end", "fist:start", "double_close:end"]
    assert result["slow"] == ["fist:start", "fist:end", "fist:start"]
    assert result["holdOn"] == ["fist:start"]


def test_a_clap_needs_two_palms_closing_fast_and_then_debounces(tmp_path):
    """Deux paumes proches ne font pas un claquement : deux mains posées côte à
    côte franchiraient la distance sans que rien ne se passe. Il faut une
    **vitesse de rapprochement**, mesurée entre deux images observées — et une
    seule annonce, sinon les images suivantes, encore proches, en émettraient
    une par image."""

    result = run_node(tmp_path, HAND + """
      const engine=B.createGestureEngine({});
      const pair=(dx,now)=>({now,aspect:1,hands:[
        {handTrackId:0,landmarks:OPEN({cx:.5-dx})},
        {handTrackId:1,landmarks:OPEN({cx:.5+dx})}]});
      // Rapprochement franc : 0,4 → 0,05 d'écart en 100 ms.
      const fast=[engine.update(pair(.2,0)),engine.update(pair(.025,100)),
                  engine.update(pair(.025,200)),engine.update(pair(.025,300))];
      // Deux mains déjà jointes, immobiles : aucune vitesse, aucun claquement.
      const still=B.createGestureEngine({});
      const quiet=[still.update(pair(.025,0)),still.update(pair(.025,100)),
                   still.update(pair(.025,200))];
      // Une seule main : rien à claquer contre.
      const alone=B.createGestureEngine({}).update(
        {now:0,aspect:1,hands:[{handTrackId:0,landmarks:OPEN()}]});
      out({fast:fast.map(f=>names(f.events).filter(n=>n.startsWith('clap')).length),
           quiet:quiet.map(q=>names(q.events).filter(n=>n.startsWith('clap')).length),
           alone:names(alone.events).filter(n=>n.startsWith('clap')).length,
           scope:fast[1].events.filter(e=>e.gesture==='clap').map(e=>[e.scope,e.handTrackId,e.phase])});
    """)
    # Une annonce, à l'image du rapprochement, et une seule.
    assert result["fast"] == [0, 1, 0, 0]
    assert result["quiet"] == [0, 0, 0]
    assert result["alone"] == 0
    # Deux mains, aucun propriétaire : le claquement est global et anonyme.
    assert result["scope"] == [["global", None, "end"]]


# ------------------------------------------------------------- pincement


def test_the_two_pinch_channels_are_independent_and_never_cross_trigger(tmp_path):
    """Décisions 20 et 21 : le primaire est pouce-index, le secondaire
    pouce-majeur. Le clic droit est un **doigt**, jamais un appui long
    (décision 22) — donc il doit partir tout de suite sur le bon doigt, et
    jamais sur l'autre, quelle que soit la durée.

    Et les deux mains sont indépendantes (décision 12) : la main qui pince à
    l'index et la main qui pince au majeur ne se répondent pas."""

    result = run_node(tmp_path, HAND + """
      const engine=B.createPinchIntentEngine({});
      const frame=(now,hands)=>({hands,now,aspect:1});
      const events=[];
      for(const now of [0,16,32,48]){
        events.push(...engine.update(frame(now,[
          input(0,PRIMARY()),input(1,SECONDARY(),{x:300,y:300,anchorX:300,anchorY:300})])).events);
      }
      const down=events.filter(e=>e.phase==='down');
      const contacts=engine.update(frame(64,[
        input(0,PRIMARY()),input(1,SECONDARY(),{x:300,y:300,anchorX:300,anchorY:300})])).contacts;
      out({
        down:down.map(e=>[e.handTrackId,e.channel,e.x,e.y]),
        channels:B.PINCH_CHANNELS,fingers:C.PINCH_FINGERS,
        /* Le canal qui ne pince pas reste ouvert et sans confiance. */
        contacts:contacts.map(c=>[c.handTrackId,c.channel,c.state,Number(c.confidence.toFixed(2))]),
        phases:phases(events.filter(e=>e.phase!=='move')),
      });
    """)
    assert result["channels"] == ["primary", "secondary"]
    assert result["fingers"] == {"primary": ["thumbTip", "indexTip"], "secondary": ["thumbTip", "middleTip"]}
    # Chaque main descend sur son canal, à son ancre de visée, et pas sur l'autre.
    assert result["down"] == [[0, "primary", 100, 100], [1, "secondary", 300, 300]]
    assert result["contacts"] == [
        [0, "primary", "pressed", 1.0], [0, "secondary", "open", 0.0],
        [1, "primary", "open", 0.0], [1, "secondary", "pressed", 1.0],
    ]
    # Aucun `down` en double, aucun canal croisé.
    # L'ordre est celui des images, pas celui des mains : à chaque image, les
    # deux mains avancent ensemble.
    assert result["phases"] == ["primary:approach", "secondary:approach",
                                "primary:down", "secondary:down"]


def test_a_whole_hand_closure_is_not_a_right_click(tmp_path):
    """Le défaut que la marge existe pour empêcher. Une main qui se ferme
    rapproche le pouce de l'index **et** du majeur : les deux rapports tombent
    ensemble, et un moteur qui regarderait chaque canal isolément lirait un
    clic droit dans un poing. La confiance d'un canal est donc ce qui le
    **sépare** de l'autre — nulle quand les deux se valent.

    C'est la ligne « rejeter la fermeture de main entière comme clic droit » du
    contrat de la Slice, et elle ne coûte pas le vrai pincement : celui-là a
    trois doigts tendus de l'autre côté."""

    result = run_node(tmp_path, HAND + """
      const ratios=lm=>[Number(B.pinchRatioFor(lm,1,'primary').toFixed(3)),
                        Number(B.pinchRatioFor(lm,1,'secondary').toFixed(3))];
      const run=lm=>{
        const engine=B.createPinchIntentEngine({});
        const events=[];
        for(const now of [0,16,32,48])events.push(...engine.update(
          {hands:[input(0,lm)],now,aspect:1}).events);
        return {events:phases(events),
          confidence:engine.update({hands:[input(0,lm)],now:64,aspect:1})
            .contacts.map(c=>Number(c.confidence.toFixed(2)))};
      };
      out({fistRatios:ratios(FIST()),primaryRatios:ratios(PRIMARY()),
           secondaryRatios:ratios(SECONDARY()),
           fist:run(FIST()),primary:run(PRIMARY()),secondary:run(SECONDARY()),
           margin:B.DEFAULTS.pinchMarginRatio,floor:B.DEFAULTS.pinchConfidenceMin});
    """)
    # Dans un poing, les deux rapports sont tous deux sous le seuil de
    # pincement : c'est bien le cas dangereux, pas un cas écarté d'avance.
    assert result["fistRatios"][0] < 0.28 and result["fistRatios"][1] < 0.28
    # Et pourtant : aucun contact, sur aucun des deux canaux.
    assert result["fist"]["events"] == []
    assert max(result["fist"]["confidence"]) < result["floor"], "sous le plancher des deux côtés"
    # Le vrai pincement n'y perd rien.
    assert result["primary"]["events"] == ["primary:approach", "primary:down"]
    assert result["secondary"]["events"] == ["secondary:approach", "secondary:down"]
    assert result["primary"]["confidence"] == [1.0, 0.0]
    assert result["secondary"]["confidence"] == [0.0, 1.0]


def test_hysteresis_keeps_a_finger_on_the_threshold_from_flickering(tmp_path):
    """Un doigt posé pile sur `pressRatio` traverse le seuil plusieurs fois par
    seconde. Sans hystérésis, chaque passage est un contact : une fenêtre
    saisie et lâchée dix fois, ou dix clics droits. Remonter exige
    `releaseRatio`, strictement plus haut — et c'est cet écart, pas la
    stabilité du doigt, qui tient."""

    result = run_node(tmp_path, HAND + """
      const engine=B.createPinchIntentEngine({});
      const events=[];
      // Deux images sous le seuil (il en faut `pressFrames`), puis une
      // oscillation au-dessus de `pressRatio` mais sous `releaseRatio`.
      const gaps=[.27,.27,.35,.27,.35,.27,.35];
      gaps.forEach((gap,i)=>{events.push(...engine.update(
        {hands:[input(0,PRIMARY({gap}))],now:i*16,aspect:1}).events)});
      const oscillating=phases(events.filter(e=>e.phase!=='move'));
      // Franchir `releaseRatio` relâche pour de bon.
      events.push(...engine.update({hands:[input(0,OPEN())],now:200,aspect:1}).events);
      out({oscillating,all:phases(events.filter(e=>e.phase!=='move')),
           thresholds:[B.DEFAULTS.pressRatio,B.DEFAULTS.releaseRatio,B.DEFAULTS.pressFrames]});
    """)
    assert result["thresholds"] == [0.28, 0.42, 2]
    # Une seule descente, malgré trois retours au-dessus de `pressRatio`.
    assert result["oscillating"] == ["primary:approach", "primary:down"]
    assert result["all"] == ["primary:approach", "primary:down", "primary:up"]


def test_a_click_and_a_drag_are_told_apart_by_travel_duration_and_stillness(tmp_path):
    """Décision 22 : la durée et le déplacement du pincement primaire servent à
    l'intention. Trois contacts, trois conclusions :

    - court, immobile, sur place → **clic** ;
    - la main part → **glissement**, tranché en cours de route : une main qui
      revient d'où elle est venue a tout de même glissé ;
    - court et presque sur place, mais la main **file** au relâchement →
      glissement aussi. C'est là que l'immobilité de la Slice 03 fait le
      travail : sans elle, un geste franc dont le pincement se ferme une image
      au passage serait lu comme un clic.

    L'immobilité lue est celle que le moteur **publie** (dérivée du point
    filtré, relissée), jamais la dérivée interne du filtre One Euro, qui lit
    40 px/s sur une main parfaitement immobile."""

    result = run_node(tmp_path, HAND + """
      const contact=steps=>{
        const engine=B.createPinchIntentEngine({});
        const events=[];
        for(const s of steps)events.push(...engine.update(
          {hands:[input(0,s.open?OPEN():PRIMARY({gap:.15}),
            {x:s.x,y:100,anchorX:100,anchorY:100,stillness:s.still===undefined?1:s.still})],
           now:s.now,aspect:1}).events);
        const up=events.filter(e=>e.phase==='up')[0];
        return up?{intent:up.intent,travelPx:Math.round(up.travelPx),durationMs:up.durationMs}:null;
      };
      const click=contact([{now:0,x:100},{now:16,x:100},{now:200,x:100},{now:250,x:100,open:1}]);
      const drag=contact([{now:0,x:100},{now:16,x:100},{now:100,x:180},{now:200,x:260},
                          {now:250,x:260,open:1}]);
      const backAndForth=contact([{now:0,x:100},{now:16,x:100},{now:100,x:200},
                                  {now:200,x:100},{now:250,x:100,open:1}]);
      const flying=contact([{now:0,x:100},{now:16,x:100},{now:100,x:106},
                            {now:150,x:108,open:1,still:.05}]);
      /* Les images restent dans la grâce d'identité : au-delà, le contact
         serait **annulé**, pas relâché — c'est du temps non observé. */
      const slow=contact([{now:0,x:100},{now:16,x:100},{now:200,x:100},{now:400,x:100},
                          {now:600,x:100},{now:800,x:100},{now:950,x:100,open:1}]);
      out({click,drag,backAndForth,flying,slow,
           settings:[B.DEFAULTS.clickMaxMs,B.DEFAULTS.clickSlopPx,B.DEFAULTS.dragSlopPx,
                     B.DEFAULTS.clickStillnessMin],
           intents:C.PINCH_INTENTS});
    """)
    assert result["intents"] == ["undecided", "click", "drag"]
    assert result["settings"] == [400, 12, 26, 0.5]
    # Le contact commence à la **seconde** image sous le seuil (`pressFrames`),
    # donc la durée se compte de là, pas du premier frôlement.
    assert result["click"] == {"intent": "click", "travelPx": 0, "durationMs": 234}
    assert result["drag"]["intent"] == "drag" and result["drag"]["travelPx"] == 160
    # Repartie d'où elle venait : déplacement nul au relâchement, mais le
    # maximum parcouru reste, et il a tranché en chemin.
    assert result["backAndForth"] == {"intent": "drag", "travelPx": 100, "durationMs": 234}
    # Presque sur place et courte, mais la main file : pas un clic.
    assert result["flying"]["intent"] == "drag" and result["flying"]["travelPx"] < 12
    # Immobile et sur place, mais trop longue pour un clic.
    assert result["slow"]["intent"] == "drag" and result["slow"]["durationMs"] == 934


def test_a_tap_made_too_soon_after_a_fast_reach_is_read_as_a_drag(tmp_path):
    """Ce que le **temps d'établissement** de la vitesse de la Slice 03 coûte au
    clic de la Slice 04, mesuré de bout en bout plutôt que raisonné : la
    trajectoire passe par le vrai filtre et la vraie immobilité, et c'est leur
    sortie qui nourrit le moteur d'intention.

    `stillness ≥ clickStillnessMin` (0,5) veut dire « vitesse publiée
    ≤ 224 px/s », et cette vitesse-là est lissée à 1 Hz : après une approche à
    900 px/s, elle met ~250 ms à retomber sous 224. Donc un contact relâché
    moins de ~250 ms après l'arrêt de la main se conclut **`drag`, même avec un
    déplacement nul**.

    Un clic délibéré reste possible — la fenêtre `[~250 ms, clickMaxMs]` n'est
    pas vide, et le second cas le montre — mais un tapotement immédiat après un
    geste rapide ne passe pas. Le sens de l'erreur est le bon (un faux `drag`,
    jamais un faux `click`), et `clickStillnessMin` est le seul nombre qui
    déplace la frontière : la Slice 08 le calibrera devant une caméra réelle.

    Ce test est ici, dans le fichier qui possède clic et glissement, parce que
    c'est ici qu'il faut le relire le jour où l'un des deux nombres bouge."""

    result = run_node(tmp_path, HAND + """
      /* Trajectoire réelle : 900 px/s pendant 1 s puis arrêt net, à travers le
         filtre et l'immobilité de la Slice 03. */
      const f=B.createPointerFilter({}),s=B.createStillness({});
      const rows=[];let x=100;
      for(let i=0;i<200;i+=1){
        const at=i*16,v=at<1000?900:0;
        x+=v*.016;
        const m=f.update({x,y:0},at);
        const st=s.update(m.speedPxPerSec,at);
        if(at>=1000)rows.push({t:at-1000,x:m.x,stillness:st.stillness});
      }
      const near=ms=>rows.reduce((best,r)=>
        Math.abs(r.t-ms)<Math.abs(best.t-ms)?r:best,rows[0]);
      /* Contact : pincé de `down` à `up` (millisecondes après l'arrêt de la
         main), l'ancre figée au point où il commence. */
      const tap=(down,up)=>{
        const engine=B.createPinchIntentEngine({});
        const anchor=near(down);
        const events=[];
        for(const r of rows){
          if(r.t<down-32||r.t>up+16)continue;
          const closed=r.t>=down&&r.t<=up;
          events.push(...engine.update({hands:[input(0,closed?PRIMARY({gap:.15}):OPEN(),
            {x:r.x,y:0,anchorX:anchor.x,anchorY:0,stillness:r.stillness})],
            now:1000+r.t,aspect:1}).events);
        }
        const released=events.filter(e=>e.phase==='up')[0];
        return released?{intent:released.intent,travelPx:Math.round(released.travelPx),
          durationMs:Math.round(released.durationMs),
          stillnessAtRelease:Number(near(up).stillness.toFixed(2))}:null;
      };
      out({quick:tap(0,150),deliberate:tap(0,350),settled:tap(600,750),
           floor:B.DEFAULTS.clickStillnessMin});
    """)
    assert result["floor"] == 0.5, result
    # Tapotement immédiat : rien n'a bougé, la durée tient largement dans
    # `clickMaxMs`, et c'est pourtant un glissement — la vitesse publiée n'a pas
    # encore admis que la main s'était arrêtée.
    assert result["quick"]["intent"] == "drag"
    assert result["quick"]["travelPx"] <= 12
    assert result["quick"]["durationMs"] <= 400
    assert result["quick"]["stillnessAtRelease"] < 0.5
    # Le même contact tenu jusqu'au-delà de ~250 ms : clic, sans rien changer
    # d'autre. La fenêtre du clic existe, elle commence juste plus tard.
    assert result["deliberate"]["intent"] == "click"
    assert result["deliberate"]["stillnessAtRelease"] >= 0.5
    # Main posée depuis longtemps : le cas nominal, jamais en cause ici.
    assert result["settled"]["intent"] == "click"
    assert result["settled"]["stillnessAtRelease"] == 1


def test_a_lost_hand_cancels_its_contact_instead_of_releasing_it(tmp_path):
    """Une main qui disparaît au milieu d'un pincement n'a pas cliqué : un `up`
    ferait partir l'action que la perte vient d'interrompre. La grâce est celle
    de l'identité (`lostGraceMs`) — un trou d'une image ne coûte ni l'identité
    ni le contact, la Slice 03 l'a posé pour le glissement — et la même règle
    vaut à l'arrêt volontaire.

    `cancel` est la seule phase sans coordonnées : au moment où l'on annule, on
    ne sait plus où est la main. Le contrat l'écrit ainsi."""

    result = run_node(tmp_path, HAND + """
      const engine=B.createPinchIntentEngine({});
      const at=(now,hands)=>engine.update({hands,now,aspect:1});
      at(0,[input(0,PRIMARY())]);at(16,[input(0,PRIMARY())]);
      // Une image sans la main : la grâce tient, rien n'est annulé.
      const blink=at(100,[]);
      const back=at(150,[input(0,PRIMARY())]);
      // Puis une absence plus longue que la grâce.
      const gone=at(600,[]);
      const engine2=B.createPinchIntentEngine({});
      engine2.update({hands:[input(0,PRIMARY())],now:0,aspect:1});
      engine2.update({hands:[input(0,PRIMARY())],now:16,aspect:1});
      const stopped=engine2.cancelAll(32);
      out({blink:phases(blink.events),back:phases(back.events),
           gone:phases(gone.events),
           position:gone.events.map(e=>[e.x,e.y]),
           stopped:phases(stopped),size:[engine.size(),engine2.size()],
           graceMs:B.DEFAULTS.lostGraceMs});
    """)
    assert result["graceMs"] == 250
    # Un clignotement ne coûte rien : ni annulation, ni relâchement.
    assert result["blink"] == [] and result["back"] == []
    assert result["gone"] == ["primary:cancel"]
    assert result["position"] == [[None, None]], "seul `cancel` n'a rien à viser"
    assert result["stopped"] == ["primary:cancel"]
    assert result["size"] == [0, 0]


# ------------------------------------------------------- refus et parité


def test_a_malformed_frame_is_skipped_by_both_engines(tmp_path):
    """La règle de la reprise de la Slice 02, appliquée aux deux moteurs de
    celle-ci : une image malformée se **saute**, elle n'arrête rien et surtout
    elle ne se lit pas comme un relâchement — sinon un point manquant au milieu
    d'un glissement le terminerait, et l'objet tomberait là où la main n'est
    pas.

    `usableLandmarks` reste la seule définition d'« ai-je les points que je
    lis » ; la Slice 04 la **paramètre** plutôt que de l'élargir, parce
    qu'élargir aurait refusé une main partielle que le réveil sait pourtant
    mesurer."""

    result = run_node(tmp_path, HAND + """
      const broken=PRIMARY();broken[12]=undefined;      // pas de bout de majeur
      const nan=PRIMARY();nan[20]={x:NaN,y:.3,z:0};     // auriculaire sans coordonnée
      const short=PRIMARY().slice(0,13);                // ni annulaire ni auriculaire
      const engine=B.createPinchIntentEngine({});
      const frames=[];
      frames.push(engine.update({hands:[input(0,PRIMARY())],now:0,aspect:1}));
      frames.push(engine.update({hands:[input(0,PRIMARY())],now:16,aspect:1}));
      // Deux images sans le majeur : le contact primaire continue.
      frames.push(engine.update({hands:[input(0,broken)],now:32,aspect:1}));
      frames.push(engine.update({hands:[input(0,broken)],now:48,aspect:1}));
      const still=engine.update({hands:[input(0,PRIMARY())],now:64,aspect:1});
      // Le moteur de gestes saute l'image plutôt que de finir la posture.
      const gestures=B.createGestureEngine({});
      const posture=[];
      for(const [now,lm] of [[0,FIST()],[100,FIST()],[200,short],[300,FIST()]])
        posture.push(names(gestures.update({hands:[{handTrackId:0,landmarks:lm}],now,aspect:1}).events));
      out({
        contact:frames.map(f=>phases(f.events)),
        alive:still.contacts.filter(c=>c.channel==='primary').map(c=>c.state),
        posture,
        /* Chaque moteur déclare les points qu'il lit ; le prédicat reste
           unique et **total** — jamais une exception dans la boucle d'images. */
        needs:[B.USED_LANDMARKS,B.SECONDARY_LANDMARKS,B.POSTURE_LANDMARKS],
        usable:[B.usableLandmarks(short),B.usableLandmarks(short,B.POSTURE_LANDMARKS),
                B.usableLandmarks(nan,B.POSTURE_LANDMARKS),B.usableLandmarks(PRIMARY(),B.POSTURE_LANDMARKS)],
        totals:[B.usableLandmarks(null,B.POSTURE_LANDMARKS),
                B.usableLandmarks(PRIMARY(),'bruit'),
                [PRIMARY(),short].map(B.usableLandmarks).join(',')],
      });
    """)
    # Le contact descend, puis les deux images estropiées ne produisent rien —
    # ni `up`, ni `cancel` — et le contact est toujours là ensuite.
    assert result["contact"] == [["primary:approach"], ["primary:down"], [], []]
    assert result["alive"] == ["pressed"]
    # La posture ne se termine pas sur une image sautée ; elle reprend où elle
    # en était et s'annonce.
    assert result["posture"] == [["fist:hold"], ["fist:hold"], [], ["fist:start"]]
    assert result["needs"] == [[0, 4, 8, 9], [0, 4, 12, 9], [0, 4, 8, 9, 12, 16, 20]]
    # Treize points suffisent au pincement primaire, pas aux postures.
    assert result["usable"] == [True, False, False, True]
    # Total, toujours : un second argument qui n'est pas une liste de points
    # (l'indice qu'un `.map` passe) retombe sur l'ensemble par défaut.
    assert result["totals"] == [False, True, "true,true"]


def test_everything_the_engines_emit_is_accepted_by_the_contract(tmp_path):
    """Le bloc pur est chargé seul par node : il ne peut pas lire le contrat, et
    porte donc sa propre forme de travail — comme `STATE` porte celle de
    `LIFECYCLE` depuis la Slice 02. Ce qui traverse les Slices, ce sont
    `createGestureEvent` et `createPinchEvent`.

    Sans ce test, les deux formes divergent en silence et la panne sort trois
    Slices plus loin, chez le consommateur. On fait donc passer **tout** ce que
    les moteurs émettent par les deux fabriques, phase par phase, et on vérifie
    que le vocabulaire est le même des deux côtés."""

    result = run_node(tmp_path, HAND + """
      const gestures=B.createGestureEngine({});
      const pinch=B.createPinchIntentEngine({});
      const produced=[],contacts=[];
      const at=(now,lm,x)=>{
        produced.push(...gestures.update({hands:[{handTrackId:0,landmarks:lm}],now,aspect:1}).events);
        contacts.push(...pinch.update({hands:[input(0,lm,{x:x===undefined?100:x})],now,aspect:1}).events);
      };
      /* Un échantillon de chaque phase des deux vocabulaires, dans l'ordre :
         un poing tenu puis rouvert, un second poing (donc une double
         fermeture), un pincement complet, enfin une posture et un contact
         interrompus par la disparition de la main. */
      at(0,FIST());at(100,FIST());at(200,FIST());at(300,FIST());at(400,OPEN());
      at(450,FIST());at(550,FIST());at(650,FIST());at(700,FIST());at(750,OPEN());
      at(800,PRIMARY());at(816,PRIMARY());at(860,PRIMARY(),260);at(900,OPEN(),260);
      // Un contact court et immobile : l'intention `click`, à côté du `drag`.
      at(930,PRIMARY());at(946,PRIMARY());at(960,OPEN());
      for(const now of [1000,1100,1200,1300])at(now,C_HAND());
      for(const now of [1350,1366])contacts.push(...pinch.update(
        {hands:[input(0,PRIMARY())],now,aspect:1}).events);
      produced.push(...gestures.update({hands:[],now:1700,aspect:1}).events);
      contacts.push(...pinch.cancelAll(1700));
      const pair=B.createGestureEngine({});
      const clap=(dx,now)=>pair.update({now,aspect:1,hands:[
        {handTrackId:0,landmarks:OPEN({cx:.5-dx})},{handTrackId:1,landmarks:OPEN({cx:.5+dx})}]}).events;
      clap(.2,0);produced.push(...clap(.025,100));
      out({
        gesturePhases:[...new Set(produced.map(e=>e.phase))].sort(),
        gestureNames:[...new Set(produced.map(e=>e.gesture))].sort(),
        pinchPhases:[...new Set(contacts.map(e=>e.phase))].sort(),
        /* Le contrat accepte chaque événement tel quel : même vocabulaire,
           mêmes champs requis, mêmes refus. */
        gesturesAccepted:produced.every(e=>C.createGestureEvent(e).kind==='gesture'),
        pinchAccepted:contacts.every(e=>C.createPinchEvent({...e,slot:0}).kind==='pinch'),
        intentsCarried:[...new Set(contacts.map(e=>C.createPinchEvent({...e,slot:0}).intent))].sort(),
        vocabulary:[B.GESTURES,C.GESTURES,
                    Object.keys(B.GESTURE_PHASE).map(k=>B.GESTURE_PHASE[k]),C.GESTURE_PHASES,
                    B.PINCH_CHANNELS,C.PINCH_CHANNELS,
                    Object.keys(B.PINCH_PHASE).map(k=>B.PINCH_PHASE[k]),C.PINCH_PHASES,
                    Object.keys(B.PINCH_INTENT).map(k=>B.PINCH_INTENT[k]),C.PINCH_INTENTS],
        /* Une intention inconnue se refuse, elle ne retombe pas sur « clic » —
           la conclusion n'est pas un défaut. */
        badIntent:refused(()=>C.createPinchEvent({channel:'primary',phase:'up',handTrackId:'a',
          x:1,y:2,intent:'peut-être'})),
        defaultIntent:C.createPinchEvent({channel:'primary',phase:'up',handTrackId:'a',x:1,y:2}).intent,
      });
    """)
    assert result["gesturesAccepted"] is True and result["pinchAccepted"] is True
    # Les quatre phases de geste et les cinq de pincement sont réellement
    # produites : une parité sur un vocabulaire jamais émis ne prouve rien.
    assert result["gesturePhases"] == ["cancel", "end", "hold", "start"]
    assert result["gestureNames"] == ["c_pose", "clap", "double_close", "fist", "open_palm"]
    assert result["pinchPhases"] == ["approach", "cancel", "down", "move", "up"]
    assert result["intentsCarried"] == ["click", "drag", "undecided"]
    assert result["badIntent"] == "barehands_pinch_intent_unknown"
    assert result["defaultIntent"] == "undecided"
    # Les deux côtés de la frontière nomment les mêmes choses.
    pairs = result["vocabulary"]
    for index in range(0, len(pairs), 2):
        assert pairs[index] == pairs[index + 1], pairs[index]

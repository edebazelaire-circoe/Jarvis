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
  lm[12]=at(o.middleAngle===undefined?FAN.middle:o.middleAngle,o.middle);
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
/* Un pincement **en cours**, main immobile : `t` va de 0 (ouvert) à 1 (fermé),
   `share` dit quelle part de la fermeture l'index fait en se repliant — le
   reste, c'est le pouce qui vient. Un vrai pincement a `share` autour de 1 :
   c'est l'index qui bouge. Le poignet et la base du majeur, eux, ne bougent
   pas du tout, ce qui est exactement le point. */
const PINCHING=(t,share,o)=>hand(Object.assign(
  {pinch:'index',index:1.85-.5*t*share,gap:.65-.5*t},o||{}));
/* Le poing le plus courant, et le plus dangereux : le pouce replié **en
   travers** de la paume, loin de l'index et du majeur. Ce n'est pas un
   pincement, et la marge entre les deux canaux le lisait pourtant comme un
   clic droit de confiance 1. */
const FIST_THUMB_ACROSS=o=>FIST(Object.assign({pinch:null,thumbAngle:20,thumbReach:.55},o||{}));

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


# ------------------------------------------- de la géométrie aux intentions


def test_a_real_pinch_driven_from_landmark_geometry_is_a_click_not_a_drag(tmp_path):
    """**Le test qui manquait.** Tous les autres du chapitre « pincement »
    nourrissent le moteur à la main — `x:100, y:100, anchorX:100, stillness:1`
    — si bien que le cas `click` y avait `travelPx: 0` *par construction*.
    Aucun ne faisait passer une vraie géométrie de main par le traqueur et le
    filtre de la Slice 03, et c'est exactement là que vivait le défaut.

    Mesuré de bout en bout, main **parfaitement immobile**, un seul pincement
    textbook en 1920×1080 : le déplacement était lu sur le bout de l'index,
    c'est-à-dire sur le doigt qui *fait* le pincement primaire. Il parcourt un
    demi-palme en se refermant, soit 39,4 px contre un `dragSlopPx` de 26 — et
    `dragSlopPx` latche `drag` sans retour. `intent: click` était
    **inatteignable pour une vraie main**.

    La Slice 03 a corrigé le même défaut une couche plus haut, dans les mêmes
    termes : elle ancre l'identité sur le **centre de la paume** « parce que
    l'index parcourt plusieurs paumes pendant un pincement, et qu'une main qui
    pince se lirait comme une main qui saute ». Ici elle se lisait comme une
    main qui glisse. Le déplacement d'un contact se mesure donc au même repère.
    Le jeton, lui, continue de suivre l'index : c'est ce que l'utilisateur
    vise, et ce sont deux questions différentes."""

    result = run_node(tmp_path, HAND + """
      const VIEWPORT={width:1920,height:1080};
      /* Une main posée qui pince puis relâche, du traqueur au moteur.
         `anchor` dit quel point le moteur reçoit comme position de la **main** :
         le centre de la paume (`palm`) ou le bout de l'index (`tip`, l'ancien). */
      const run=opts=>{
        const o=Object.assign({share:1,palm:.16,drift:0,anchor:'palm'},opts||{});
        const tracker=B.createHandTracker({}),engine=B.createPinchIntentEngine({});
        const events=[];let clicks=0;
        for(let i=0;i<26;i+=1){
          const now=i*16;
          // 6 images ouvertes, 6 de fermeture, 10 tenues, puis relâchement.
          const t=i<6?0:i<12?(i-6)/6:i<22?1:0;
          const lm=PINCHING(t,o.share,{cx:.5+(o.drift*i)/25,palm:o.palm});
          const out=tracker.update({landmarks:[lm]},{viewport:VIEWPORT,aspect:16/9,now});
          clicks+=out.clicks.length;
          const token=out.tokens[0];
          events.push(...engine.update({hands:[{handTrackId:token.id,landmarks:lm,
            x:token.filteredX,y:token.filteredY,
            anchorX:token.x,anchorY:token.y,
            palmX:o.anchor==='palm'?token.palmX:token.filteredX,
            palmY:o.anchor==='palm'?token.palmY:token.filteredY,
            stillness:token.stillness,quality:token.quality}],now,aspect:16/9}).events);
        }
        const up=events.filter(e=>e.phase==='up')[0];
        return {legacyClicks:clicks,moves:events.filter(e=>e.phase==='move').length,
          intent:up&&up.intent,travelPx:up&&Number(up.travelPx.toFixed(1)),
          durationMs:up&&up.durationMs};
      };
      const sizes=[.12,.16,.20];
      out({
        // L'index fait toute la fermeture : le vrai pincement.
        palmAnchor:sizes.map(palm=>run({palm})),
        // Le même geste mesuré sur le bout de l'index : le défaut, épinglé.
        tipAnchor:sizes.map(palm=>run({palm,anchor:'tip'})),
        // Même quand l'index ne fait que la moitié de la fermeture, le mesurer
        // sur lui sur-évalue le déplacement.
        halfShare:run({share:.5,anchor:'tip'}),
        halfSharePalm:run({share:.5}),
        // Une main qui traverse réellement l'écran continue de glisser.
        travelling:run({drift:.2}),
        slop:[B.DEFAULTS.clickSlopPx,B.DEFAULTS.dragSlopPx],
      });
    """)
    assert result["slop"] == [12, 26]
    # Trois tailles de paume, un clic à chaque fois, et un déplacement qui tient
    # dans `clickSlopPx` — la main n'a pas bougé, le moteur le dit enfin.
    for measured in result["palmAnchor"]:
        assert measured["intent"] == "click", measured
        assert measured["travelPx"] <= 12, measured
        assert measured["durationMs"] <= 400, measured
    # Le même geste lu sur le bout de l'index : `drag`, et le déplacement grandit
    # avec la paume — c'est le doigt qui se referme, pas la main qui part.
    assert [m["intent"] for m in result["tipAnchor"]] == ["drag", "drag", "drag"]
    assert result["tipAnchor"][2]["travelPx"] > 26
    assert result["tipAnchor"][2]["travelPx"] > result["tipAnchor"][0]["travelPx"]
    # Même à mi-part, le bout de l'index sur-évalue : c'est structurel, pas un
    # effet de seuil.
    assert result["halfShare"]["travelPx"] > result["halfSharePalm"]["travelPx"]
    assert result["halfSharePalm"]["intent"] == "click"
    # Une main qui traverse vraiment reste un glissement : la correction ne rend
    # pas le moteur aveugle au déplacement, elle le mesure au bon endroit.
    assert result["travelling"]["intent"] == "drag"
    assert result["travelling"]["travelPx"] > 26
    # Et le chemin de clic hérité (Slices 00-03) n'a pas bougé : un clic, une
    # fois, sur chacun de ces gestes.
    for key in ("palmAnchor", "tipAnchor"):
        assert [m["legacyClicks"] for m in result[key]] == [1, 1, 1], key
    assert result["travelling"]["legacyClicks"] == 1
    # Note pour la Slice 06 : la main n'a pas translaté et le moteur émet tout
    # de même des `move`, parce que la position filtrée **suit l'index**. Ce
    # sont deux questions différentes, et c'est voulu.
    assert result["palmAnchor"][1]["moves"] > 0


def test_losing_the_held_channels_own_fingertip_is_not_a_release(tmp_path):
    """Une image malformée se saute **par canal**, pas par image.

    Les deux canaux ne lisent pas le même bout de doigt : le primaire veut
    `INDEX_TIP`, le secondaire `MIDDLE_TIP`. L'image n'était sautée que si les
    **deux** étaient illisibles, si bien que perdre exactement le doigt du canal
    qui tient laissait l'image passer — et un `null` fait retomber l'hystérésis
    à `open`, donc **émet un `up`**.

    Ce n'est pas un cas d'école : `MIDDLE_TIP` est le point le plus
    probablement occulté d'un pincement pouce-majeur, le pouce étant devant. Le
    consommateur lâchait l'objet et recevait un clic droit au milieu d'un
    glissement, sur une main qui n'avait rien relâché.

    Le test d'origine coupait le doigt du canal **au repos** pendant que l'autre
    tenait : le canal qui tient ne voyait jamais de `null`, et l'angle mort
    était exactement là."""

    result = run_node(tmp_path, HAND + """
      const blind=(lm,at)=>{const copy=lm.map(p=>p);copy[at]=undefined;return copy};
      /* Un contact établi sur `lm`, puis deux images où le doigt `at` manque,
         puis le retour de la main entière. */
      const run=(lm,at)=>{
        const engine=B.createPinchIntentEngine({});
        const frames=[];
        for(const now of [0,16])frames.push(engine.update({hands:[input(0,lm)],now,aspect:1}));
        for(const now of [32,48])frames.push(engine.update(
          {hands:[input(0,blind(lm,at))],now,aspect:1}));
        const back=engine.update({hands:[input(0,lm)],now:64,aspect:1});
        const channel=at===B.LM.MIDDLE_TIP?'secondary':'primary';
        const own=list=>list.filter(c=>c.channel===channel);
        return {events:frames.map(f=>phases(f.events)),
          blindRatios:frames[2].contacts.map(c=>c.channel+':'+c.ratio),
          blindState:own(frames[2].contacts).map(c=>c.state),
          alive:own(back.contacts).map(c=>c.state),
          intent:own(back.contacts).map(c=>c.intent)};
      };
      /* Contrôle : les deux doigts perdus d'un coup — l'image est sautée en
         entier, et ce comportement-là était déjà juste. */
      const both=()=>{
        const engine=B.createPinchIntentEngine({});
        for(const now of [0,16])engine.update({hands:[input(0,PRIMARY())],now,aspect:1});
        const lost=blind(blind(PRIMARY(),B.LM.INDEX_TIP),B.LM.MIDDLE_TIP);
        const gone=engine.update({hands:[input(0,lost)],now:32,aspect:1});
        return {events:phases(gone.events),contacts:gone.contacts.length};
      };
      out({secondary:run(SECONDARY(),B.LM.MIDDLE_TIP),
           primary:run(PRIMARY(),B.LM.INDEX_TIP),
           both:both()});
    """)
    for channel in ("primary", "secondary"):
        measured = result[channel]
        # Descente, puis deux images aveugles qui n'émettent **rien** : ni `up`,
        # ni `cancel`, ni `approach`.
        assert measured["events"] == [
            ["%s:approach" % channel], ["%s:down" % channel], [], []
        ], channel
        # Le canal aveugle se publie tout de même, avec un rapport `null` :
        # disparaître serait une autre façon de dire « relâché ».
        assert "%s:null" % channel in measured["blindRatios"], channel
        assert measured["blindState"] == ["pressed"], channel
        # Et le contact est toujours là, dans le même état, à l'image d'après.
        assert measured["alive"] == ["pressed"], channel
        assert measured["intent"] == ["undecided"], channel
    # Les deux doigts perdus : l'image entière est sautée, rien n'est publié.
    assert result["both"] == {"events": [], "contacts": 0}


def test_a_closed_fist_can_never_start_a_contact_whatever_the_margin(tmp_path):
    """« Rejeter la fermeture de main entière comme clic droit » — la ligne du
    contrat de la Slice, tenue cette fois par une **garantie** plutôt que par
    une marge bien choisie.

    La marge entre les deux canaux n'écartait le poing du dépôt que de 0,02
    paume : desserrez-le un peu et il passe ; repliez le pouce **en travers de
    la paume** — le poing le plus courant, celui où le pouce ne touche rien —
    et il produisait un clic droit de confiance **1,0**. Le même nombre, tiré
    dans l'autre sens, bloquait un pincement primaire légitime dès que le majeur
    suivait l'index. Deux contraintes contradictoires sur une seule constante.

    Une main fermée se reconnaît à ce qu'elle *est* — les quatre doigts repliés
    — et `handPosture` mesurait déjà cette extension. Le moteur de pincement lit
    donc `handClosure`, la même mesure et les mêmes deux constantes, et la
    multiplie à la confiance."""

    result = run_node(tmp_path, HAND + """
      const run=lm=>{
        const engine=B.createPinchIntentEngine({});
        const events=[];
        for(const now of [0,16,32,48])events.push(...engine.update(
          {hands:[input(0,lm)],now,aspect:1}).events);
        const last=engine.update({hands:[input(0,lm)],now:64,aspect:1});
        const closure=B.handClosure(lm,1,{});
        return {events:phases(events),
          confidence:Number(Math.max(...last.contacts.map(c=>c.confidence)).toFixed(3)),
          closure:closure===null?null:Number(closure.toFixed(3))};
      };
      const fists={
        pinned:FIST(),
        looser:FIST({index:.8,middle:.8,ring:.8,pinky:.8}),
        loose:FIST({index:.7,middle:.7,ring:.7,pinky:.7}),
        thumbAcross:FIST_THUMB_ACROSS(),
        thumbAcrossLoose:FIST_THUMB_ACROSS({index:.8,middle:.8,ring:.8,pinky:.8}),
      };
      const real={primary:PRIMARY(),secondary:SECONDARY(),splayed:SPLAYED(),
                  closing:PINCHING(1,1)};
      /* Le majeur qui suit l'index : ce que la marge bloquait de l'autre côté.
         Le balayage part de l'éventail du dépôt (17°) et resserre jusqu'à ce
         que les deux doigts se confondent. */
      const following={};
      for(const sep of [17,13,11,9,8,7,6,5,4,3,2,1,0]){
        const lm=PRIMARY({indexAngle:-25,middleAngle:-25+sep});
        following[sep]={...run(lm),
          gapPalms:Number((B.pinchRatioFor(lm,1,'secondary')
                          -B.pinchRatioFor(lm,1,'primary')).toFixed(3))};
      }
      out({
        fists:Object.fromEntries(Object.entries(fists).map(([k,lm])=>[k,run(lm)])),
        real:Object.fromEntries(Object.entries(real).map(([k,lm])=>[k,run(lm)])),
        following,
        /* La garantie tient sur la **définition** du poing, pas sur une valeur :
           quatre doigts sous `fingerCurledPalms` donnent une fermeture pleine,
           et un seul doigt tendu suffit à la lever. */
        boundary:[B.DEFAULTS.fingerCurledPalms,B.DEFAULTS.fingerExtendedPalms],
        oneFingerUp:Number(B.handClosure(FIST({index:1.85}),1,{}).toFixed(3)),
        /* Elle se lit sur les doigts **présents** : refuser de conclure sans
           l'auriculaire voudrait dire « aucun pincement ne commence pendant
           qu'il est caché », or c'est le premier que l'occlusion emporte. */
        withoutPinky:(()=>{const lm=FIST();lm[20]=undefined;
          return Number(B.handClosure(lm,1,{}).toFixed(3))})(),
        withoutFingers:(()=>{const lm=FIST();
          for(const at of [8,12,16,20])lm[at]=undefined;return B.handClosure(lm,1,{})})(),
        margin:B.DEFAULTS.pinchMarginRatio,floor:B.DEFAULTS.pinchConfidenceMin,
        /* Sans la fermeture, la marge seule laisserait passer : les rapports
           bruts d'un poing au pouce en travers sont très séparés. */
        rawMargin:(()=>{const lm=FIST_THUMB_ACROSS();
          const p=B.pinchRatioFor(lm,1,'primary'),s=B.pinchRatioFor(lm,1,'secondary');
          return Number(Math.min(1,Math.max(0,(p-s)/B.DEFAULTS.pinchMarginRatio)).toFixed(3))})(),
      });
    """)
    assert result["boundary"] == [1.15, 1.6]
    assert result["margin"] == 0.12 and result["floor"] == 0.5
    # Cinq poings, aucun contact, et une confiance **exactement** nulle : ce
    # n'est pas « sous le plancher de peu », c'est zéro par construction.
    for name, measured in result["fists"].items():
        assert measured["events"] == [], name
        assert measured["confidence"] == 0.0, name
        assert measured["closure"] == 1.0, name
    # Sans le second témoin, ce poing-là aurait la confiance maximale : la marge
    # ne le rejetait pas, elle le **certifiait**.
    assert result["rawMargin"] == 1.0
    # La garantie ne coûte rien à un vrai pincement : il lui reste des doigts
    # tendus, donc une fermeture nulle et une confiance intacte.
    for name, measured in result["real"].items():
        channel = "secondary" if name in ("secondary", "splayed") else "primary"
        assert measured["closure"] == 0.0, name
        assert measured["events"] == ["%s:approach" % channel, "%s:down" % channel], name
    # Un seul doigt relevé lève la fermeture : le poing n'est pas un seuil flou,
    # c'est « tous les doigts repliés ».
    assert result["oneFingerUp"] == 0.0
    # Et elle se lit sur les doigts présents ; sans aucun d'eux, elle se tait
    # (`null`) plutôt que de deviner — le moteur prend alors le repli prudent.
    assert result["withoutPinky"] == 1.0
    assert result["withoutFingers"] is None
    # L'autre moitié du défaut. Libérée de la fermeture, la marge admet le majeur
    # qui suit l'index partout sauf dans une fenêtre de deux degrés.
    admitted = [sep for sep, m in result["following"].items() if m["events"]]
    refused = sorted(int(sep) for sep, m in result["following"].items() if not m["events"])
    assert refused == [4, 5], result["following"]
    assert len(admitted) == 11
    # Le décrochage était à 8° : 7° et 9° passent désormais, et confortablement.
    for sep in ("7", "8", "9"):
        assert result["following"][sep]["confidence"] >= 0.6, sep
    # Ce qui reste refusé n'est pas un artefact de seuil : c'est une **égalité
    # géométrique**. Le bout du majeur y est à moins de 0,06 paume (~5 mm) de
    # l'écart du pouce à l'index — le majeur occupe le point de pincement, et
    # aucune distance ne peut alors nommer le canal. Refuser est la bonne
    # réponse : un contact sur le mauvais canal, c'est un clic droit involontaire.
    for sep in ("4", "5"):
        assert result["following"][sep]["gapPalms"] < 0.06, sep
    assert min(result["following"][sep]["gapPalms"] for sep in ("7", "8", "9")) >= 0.06


def test_a_published_gesture_always_gets_exactly_one_terminal_phase(tmp_path):
    """L'arbitrage de capture s'appliquait à **toutes** les phases, `end` et
    `cancel` comprises. Or un `start` et un `end` ne demandent pas la même
    chose : un `start` demande d'agir, et l'étouffer ne coûte que l'action qui
    n'a pas eu lieu ; un `end`/`cancel` **rend** quelque chose sur quoi le
    consommateur a déjà agi, et l'étouffer le laisse accroché pour toujours.

    Le cas de la main perdue était pire : le moteur étouffait le `cancel` puis
    effaçait l'état de la main dans la foulée, si bien que plus rien ne pouvait
    corriger — un poing latché à vie.

    L'autre moitié du même invariant : un `end` partait après un `start`
    étouffé, et un consommateur qui apparie les deux croyait relâcher ce qu'il
    n'avait jamais pris.

    Invariant : **tout `start` publié reçoit exactement une phase terminale, et
    aucune phase terminale n'arrive sans `start`.**"""

    result = run_node(tmp_path, HAND + """
      const one=lm=>[{handTrackId:0,landmarks:lm}];
      // Quatre images de poing : `postureHoldMs` tenu, donc `fist:start`.
      const held=(engine,captured)=>{
        const events=[],suppressed=[];
        for(const now of [0,100,200,300]){
          const o=engine.update({hands:one(FIST()),now,aspect:1,captured});
          events.push(...o.events);suppressed.push(...o.suppressed);
        }
        return {events:names(events),suppressed:names(suppressed)};
      };
      // 1. Annoncé libre, puis une capture est prise, puis la main s'ouvre.
      const a=B.createGestureEngine({});
      const opened=held(a,[]);
      const ending=a.update({hands:one(OPEN()),now:400,aspect:1,captured:[0]});
      // 2. Annoncé libre, capture prise, puis la main est **perdue**.
      const b=B.createGestureEngine({});
      held(b,[]);
      const lost=b.update({hands:[],now:1000,aspect:1,captured:[0]});
      // 3. `start` étouffé dès le départ : pas de fin orpheline au relâchement.
      const c=B.createGestureEngine({});
      const muted=held(c,[0]);
      const after=c.update({hands:one(OPEN()),now:400,aspect:1,captured:[0]});
      // 4. `start` étouffé, puis la main est perdue : rien à rendre non plus.
      const d=B.createGestureEngine({});
      held(d,[0]);
      const mutedLost=d.update({hands:[],now:1000,aspect:1,captured:[0]});
      /* 5. L'invariant, compté sur une séquence entière et deux mains : la 0
         capturée par intermittence, la 1 capturée à un autre moment. */
      const e=B.createGestureEngine({});
      const two=lm=>[{handTrackId:0,landmarks:lm},{handTrackId:1,landmarks:lm}];
      const seen=[];
      const script=[[0,FIST(),[]],[100,FIST(),[]],[200,FIST(),[0]],[300,FIST(),[0]],
                    [400,FIST(),[0]],[500,OPEN(),[0]],[600,OPEN(),[]],
                    [700,FIST(),[]],[800,FIST(),[]],[900,FIST(),[1]],[1000,FIST(),[1]],
                    [1100,OPEN(),[1]],[2000,OPEN(),[]]];
      for(const [now,lm,captured] of script)
        seen.push(...e.update({hands:two(lm),now,aspect:1,captured}).events);
      seen.push(...e.update({hands:[],now:3000,aspect:1,captured:[0,1]}).events);
      const tally={};
      for(const ev of seen.filter(x=>B.POSTURE_GESTURES.includes(x.gesture))){
        const mark=ev.phase==='start'?'s'
          :(ev.phase==='end'||ev.phase==='cancel')?'t':null;
        if(!mark)continue;
        const key=ev.gesture+'#'+ev.handTrackId;
        tally[key]=(tally[key]||'')+mark;
      }
      out({
        opened,ending:{events:names(ending.events),suppressed:names(ending.suppressed)},
        lost:{events:names(lost.events),suppressed:names(lost.suppressed),size:b.size()},
        muted,after:{events:names(after.events),suppressed:names(after.suppressed)},
        mutedLost:{events:names(mutedLost.events),suppressed:names(mutedLost.suppressed)},
        tally,
      });
    """)
    # 1. Le poing s'annonce pendant que rien n'est capturé…
    assert result["opened"]["events"] == ["fist:hold", "fist:hold", "fist:hold", "fist:start"]
    assert result["opened"]["suppressed"] == []
    # …et sa fin passe **malgré** la capture prise entre-temps. Sans cela, le
    # consommateur restait accroché au poing pour toujours.
    assert result["ending"]["events"] == ["open_palm:hold", "fist:end"]
    assert result["ending"]["suppressed"] == []
    # 2. Main perdue pendant la capture : `cancel` délivré. C'était la dernière
    # occasion — la ligne suivante efface l'état de la main.
    assert result["lost"]["events"] == ["fist:cancel"]
    assert result["lost"]["suppressed"] == []
    assert result["lost"]["size"] == 0
    # 3. `start` étouffé : tout est étouffé, et rien d'orphelin ne suit.
    assert result["muted"]["events"] == []
    assert result["muted"]["suppressed"] == [
        "fist:hold", "fist:hold", "fist:hold", "fist:start",
    ]
    assert [name for name in result["after"]["events"] if name.startswith("fist")] == []
    assert [name for name in result["after"]["suppressed"] if name.startswith("fist")] == []
    # 4. Ni à la perte de la main.
    assert result["mutedLost"] == {"events": [], "suppressed": []}
    # 5. L'invariant sur toute la séquence : `start` et phase terminale
    # strictement alternés, jamais deux de suite, jamais une fin d'abord.
    assert result["tally"], "la séquence doit produire des postures"
    for key, order in result["tally"].items():
        assert "ss" not in order and "tt" not in order, (key, order)
        assert order.startswith("s"), (key, order)
        assert order.count("s") == order.count("t"), (key, order)


def test_a_c_whose_thumb_nears_the_middle_finger_fades_instead_of_falling_off_a_cliff(tmp_path):
    """Le rejet du pincement secondaire par `cPoseScore` était un `return 0` sec
    au-dessus de `releaseRatio` — la **seule** frontière non adoucie d'un
    fichier qui adoucit toutes les autres, et pour la raison qu'elles le sont :
    une main posée dessus clignote sur le tremblement du traqueur, n'aboutit
    jamais au maintien d'une seconde, et ne dit pas pourquoi.

    Deux problèmes, donc : le seuil — `releaseRatio`, et non l'entrée réelle en
    contact — et la falaise. La garde est maintenant une rampe sur la bande que
    l'hystérésis possède déjà : zéro sous `pressRatio`, le seuil où le contact
    **entre**, et le plus proche de l'état de contact qu'un score sans mémoire
    puisse lire ; pleine au-dessus de `releaseRatio`.

    Ce qu'elle doit continuer d'empêcher n'a pas bougé : un clic droit franc ne
    réveille pas la veille."""

    result = run_node(tmp_path, HAND + """
      const score=lm=>B.cPoseScore(lm,1,{});
      const D=B.DEFAULTS;
      /* Le majeur seul se déplace : l'écart pouce-index et la portée de l'index
         ne bougent pas, donc **seule** la garde du canal secondaire change. Le
         rapport secondaire vaut exactement `d`. C'est le cas physique du
         constat : un C dont le majeur est à demi replié vers le pouce. */
      const base=C_HAND();
      const nearing=d=>{const lm=base.map(p=>p);
        lm[12]={x:lm[4].x+d*.2,y:lm[4].y,z:0};return lm};
      const sweep=[];
      for(let d=.10;d<=.601;d+=.025)
        sweep.push([Number(d.toFixed(3)),Number(score(nearing(d)).toFixed(3))]);
      /* Ce que la falaise annulait, compté : les poses dont la seule géométrie
         du C est bonne et dont le pouce passe simplement près du majeur. Le
         témoin « avant » est la règle d'alors, rejouée ici. */
      let valid=0,cliffed=0,graded=0,restored=0,stillZero=0;
      for(let mid=.8;mid<=1.61;mid+=.1)
       for(let dx=-.9;dx<=.91;dx+=.1)
        for(let dy=-.9;dy<=.91;dy+=.1){
          const lm=hand({middle:mid,ring:.9,pinky:.9,pinch:null});
          lm[4]={x:lm[8].x+dx*.2,y:lm[8].y+dy*.2,z:0};
          // La géométrie du C seule : la garde désarmée par ses propres seuils.
          const bare=B.cPoseScore(lm,1,{pressRatio:.001,releaseRatio:.002});
          if(bare<D.wakeScore)continue;
          valid+=1;
          const secondary=B.pinchRatioFor(lm,1,'secondary');
          const before=(secondary!==null&&secondary<D.releaseRatio)?0:bare;
          if(before>=D.wakeScore)continue;
          cliffed+=1;
          const now=score(lm);
          if(now>=D.wakeScore)restored+=1;
          if(now>0)graded+=1;else stillZero+=1;
        }
      out({sweep,valid,cliffed,graded,restored,stillZero,
           /* Ce que la garde doit continuer d'empêcher, inchangé. */
           realRightClick:[score(SECONDARY()),score(SPLAYED())],
           baseScore:score(base),
           thresholds:[D.pressRatio,D.releaseRatio,D.wakeScore]});
    """)
    assert result["thresholds"] == [0.28, 0.42, 0.5]
    assert result["baseScore"] == 1
    # Un clic droit franc ne réveille toujours pas : c'est toute la raison
    # d'être de la garde, et elle n'a pas bougé d'un pouce.
    assert result["realRightClick"] == [0, 0]
    # La falaise annulait des poses que la géométrie du C accepte…
    assert result["valid"] > 1000 and result["cliffed"] > 100
    # …dont une part repasse au-dessus du seuil de maintien, et une part de plus
    # gagne un score gradué au lieu d'un zéro sec.
    assert result["restored"] > 0
    assert result["graded"] > result["restored"]
    # Les dernières restent à zéro, et c'est juste : le pouce y touche vraiment
    # le majeur (rapport sous `pressRatio`), donc c'est un pincement, pas un C.
    assert result["stillZero"] > 0
    # Continuité : en traversant la bande, le score monte par paliers. Le plus
    # grand saut d'un échantillon au suivant reste petit — c'est **ça** qui
    # empêche le clignotement, là où la falaise sautait de 0 à 1 d'un coup.
    values = [value for _, value in result["sweep"]]
    assert values[0] == 0 and values[-1] == 1
    jumps = [abs(b - a) for a, b in zip(values, values[1:])]
    assert max(jumps) <= 0.2, result["sweep"]
    # Et elle est monotone : plus le pouce s'éloigne du majeur, plus le C vaut.
    assert values == sorted(values), result["sweep"]
    # Les bornes sont bien celles de l'hystérésis, pas deux nombres de plus.
    inside = [value for ratio, value in result["sweep"] if 0.28 < ratio < 0.42]
    assert all(0 < value < 1 for value in inside), result["sweep"]


def test_the_engine_refuses_a_truncated_click_tolerance_and_never_throws_on_an_unknown_gesture(tmp_path):
    """Deux défauts de la même famille, et c'est la **troisième** fois que
    celle-ci se présente sur cette tâche.

    `clickSlopPx` au-dessus de `dragSlopPx` est silencieusement tronqué : le
    glissement se tranche en cours de route à `dragSlopPx`, donc le contact est
    déjà `drag` quand le test du clic s'exécute.
    `createPinchIntentEngine({clickSlopPx:100, dragSlopPx:26})` était **accepté**
    et ne changeait rien — la Slice 08 aurait monté la tolérance pour une main
    tremblante, sans effet, sans erreur et sans test rouge. Le contrat l'écrivait
    déjà ; il se refuse désormais là où il se lit. L'égalité reste permise :
    elle ne tronque rien.

    Et la table `GESTURE_RULES` se lisait à nu dans la publication : une sixième
    posture ajoutée un jour aurait levé **dans la boucle d'images**, donc en
    `tracking_failed` — caméra rendue, session terminée, pour un nom manquant.
    Le repli est le plus silencieux possible : portée globale et aucune
    autorisation pendant une capture, donc un geste sans règle ne peut jamais
    voler la main à une manipulation en cours. Le contrat, lui, refuse : c'est
    la bonne réponse hors de la boucle, là où le refus se lit."""

    result = run_node(tmp_path, HAND + """
      const message=fn=>{try{fn();return null}catch(e){return e.name}};
      out({
        truncated:message(()=>B.createPinchIntentEngine({clickSlopPx:100,dragSlopPx:26})),
        // Le cas limite : égal ne tronque rien, donc reste permis.
        equal:message(()=>B.createPinchIntentEngine({clickSlopPx:26,dragSlopPx:26})),
        under:message(()=>B.createPinchIntentEngine({clickSlopPx:10,dragSlopPx:26})),
        // Le même refus partout où ces réglages entrent.
        channel:message(()=>B.createPinchChannel('primary',{clickSlopPx:100,dragSlopPx:26})),
        tracker:message(()=>B.createHandTracker({clickSlopPx:100,dragSlopPx:26})),
        // Les quatre autres refus de construction n'ont pas bougé.
        others:[message(()=>B.createPinchIntentEngine({pressRatio:.5,releaseRatio:.4})),
                message(()=>B.createPinchIntentEngine({fingerCurledPalms:2,fingerExtendedPalms:1})),
                message(()=>B.createWakeDetector({wakeIntervalMs:500,wakeGraceMs:400})),
                message(()=>B.createPointerFilter({smoothing:.45})),
                message(()=>B.createHandTrackManager({handednessBonusPalms:.35}))],
        // Un geste sans règle : la publication ne lève pas, elle se tait.
        unknown:[B.gestureRuleFor('wave').scope,B.gestureRuleFor('wave').duringCapture],
        known:B.GESTURES.map(g=>B.gestureRuleFor(g)===B.GESTURE_RULES[g]),
        contract:refused(()=>C.gestureScope('wave')),
      });
    """)
    assert result["truncated"] == "RangeError"
    assert result["equal"] is None and result["under"] is None
    assert result["channel"] == "RangeError" and result["tracker"] == "RangeError"
    assert result["others"] == ["RangeError"] * 5
    # Le repli le plus silencieux : global, jamais permis pendant une capture.
    assert result["unknown"] == ["global", False]
    assert all(result["known"]), "un geste connu garde sa propre règle"
    assert result["contract"] == "barehands_gesture_unknown"

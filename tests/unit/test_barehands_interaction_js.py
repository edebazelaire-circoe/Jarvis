"""Moteur d'interaction, captures et géométrie bimanuelle (Slice 06), par node.

Ce que ce fichier épingle, décision par décision :

- une zone déplace le cadre entier, et une main seule ne redimensionne jamais
  (10, 11) ;
- deux zones compatibles du **même** cadre le redimensionnent, avec les côtés
  que `combineCaptures` a attribués — jamais une seconde lecture des zones ici
  (11, 16, 17) ;
- deux mains sur deux objets restent indépendantes (12) ;
- une capture est latchée jusqu'au relâchement (13) ;
- ZONE + CORPS ne forme pas un redimensionnement, et CORPS + CORPS ne déplace
  rien (8, 14) ;
- la même zone deux fois se refuse, et le refus se **dit** (15) ;
- les mains qui se croisent ne retournent pas le cadre : il se borne à sa taille
  minimale (18) ;
- `RESIZE → MOVE` se rebase, donc le cadre ne saute pas (19).

Et deux choses qu'aucun test de moteur ne voit tout seul : que les pixels de la
fenêtre deviennent des unités de scène **une fois**, au bon endroit, et que la
chaîne entière — points de main, traqueur, filtre, intention, résolveur, moteur,
géométrie, commande — produise une seule géométrie, en unités.

La géométrie et les contrats ne sont **pas** simulés : ce sont les vrais
modules. Seuls la scène (le monde) et le DOM (la compatibilité) sont des
doubles, parce qu'ils sont précisément ce que node n'a pas.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.runtime.control_center import (
    BAREHANDS_SCRIPT_MARKER,
    SCENE_INTERACT_SCRIPT_MARKER,
    SCENE_PAGE_SCRIPT_MARKER,
    ControlCenter,
)

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
SCRIPT = RUNTIME / "control_center_barehands.js"
CONTRACTS = RUNTIME / "control_center_barehands_contracts.js"
TARGET = RUNTIME / "control_center_barehands_target.js"
CALIBRATION = RUNTIME / "control_center_barehands_calibration.js"
RECORDER = RUNTIME / "control_center_barehands_recorder.js"
SCENE_INTERACT = RUNTIME / "control_center_scene_interact.js"
SCENE_PAGE = RUNTIME / "control_center_scene_page.js"
PAGE_HTML = RUNTIME / "control_center.html"


def run_node(tmp_path: Path, source: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "barehands-interaction.cjs"
    script.write_text(
        f"const SCRIPT_PATH={json.dumps(str(SCRIPT))};\n"
        f"const CALIBRATION_PATH={json.dumps(str(CALIBRATION))};\n"
        f"const RECORDER_PATH={json.dumps(str(RECORDER))};\n"
        f"const TARGET_PATH={json.dumps(str(TARGET))};\n"
        f"const SCENE_INTERACT_PATH={json.dumps(str(SCENE_INTERACT))};\n"
        f"const B=require(SCRIPT_PATH);\n"
        f"const C=require({json.dumps(str(CONTRACTS))});\n"
        "const G=require(SCENE_INTERACT_PATH);\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "const refused=fn=>{try{fn();return null}catch(e){return e.code||e.name||String(e)}};\n"
        "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=40, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


#: Le moteur avec les **vrais** contrats et la **vraie** géométrie ; seuls le
#: monde (la scène) et le DOM sont des doubles.
FIXTURE = """
const makeWorld=(objects)=>{
  const log={begins:[],previews:[],commits:[],cancels:[]};
  return {log,api:{
    begin(id){
      const o=objects[id];
      log.begins.push(id);
      return o?{objectId:id,box:Object.assign({},o.box),representation:o.representation}:null;
    },
    preview(id,box){log.previews.push({id,box:Object.assign({},box)})},
    commit(id,box,mode){log.commits.push({id,box:Object.assign({},box),mode})},
    cancel(id){log.cancels.push(id)},
    viewport(){return {scale:6}},
  }};
};
const makeDom=(scrollable)=>{
  const log=[];
  return {log,api:{
    scrollable(target){return (scrollable||[]).includes(String(target&&target.objectId))
      ||(scrollable||[]).includes(String(target&&target.kind))},
    emit(event,ctx){log.push({type:event.type,x:event.x,y:event.y,dx:event.dx,dy:event.dy,
      pointerId:event.pointerId,channel:event.channel,objectId:event.objectId,
      axes:[...event.axes],cancelled:!!(ctx&&ctx.cancelled)})},
  }};
};
const engineOf=o=>B.createInteractionEngine(Object.assign({contracts:C,geometry:G},o||{}));
/* Un jeton : où la main **vise** (l'index) et où elle **est** (la paume). Les
   deux, parce qu'ils ne servent pas à la même chose — et c'est la paume qui
   déplace un cadre. */
const tok=(id,x,y,px,py)=>({id,x,y,
  palmX:px===undefined?x:px,palmY:py===undefined?y:py});
const tgt=(id,objectId,region,zone,extra)=>Object.assign({
  handTrackId:id,channel:'primary',locked:true,objectId,region,zone,
  kind:'scene_object',representation:'window',actionable:true,
  boundsPx:{x:0,y:0,w:600,h:400},distancePx:0},extra||{});
const ev=(id,phase,x,y,channel)=>({handTrackId:id,channel:channel||'primary',phase,
  x:x===undefined?null:x,y:y===undefined?null:y});
const held=(id,intent,channel)=>({handTrackId:id,channel:channel||'primary',
  state:'pressed',intent:intent||'drag'});
const boxes=log=>log.previews.map(p=>[p.box.x,p.box.y,p.box.w,p.box.h]);
"""


# --------------------------------------------------------------- géométrie pure


def test_a_side_no_hand_holds_is_the_anchor_and_the_others_move(tmp_path):
    """Le redimensionnement par côtés généralise la poignée unique de la souris
    sans la remplacer : un côté **absent** de la table ne bouge pas, c'est lui
    l'ancre. C'est ce qui fait qu'une main sur le bord droit ne déplace pas le
    bord gauche, et qu'un coin haut-gauche laisse le coin bas-droit où il est.
    """

    result = run_node(tmp_path, FIXTURE + """
      const start={x:0,y:0,w:64,h:40};
      const at=sides=>{const b=G.resizeBySides(start,sides,'window');return [b.x,b.y,b.w,b.h]};
      out({
        right:at({right:10}),
        left:at({left:-10}),
        bottom:at({bottom:6}),
        topLeftCorner:at({top:-6,left:-10}),
        /* Deux mains, deux côtés opposés du même axe : c'est un
           redimensionnement légitime, pas un conflit. */
        bothHorizontal:at({left:-10,right:10}),
        untouched:at({}),
      });
    """)
    assert result["right"] == [0, 0, 74, 40]
    assert result["left"] == [-10, 0, 74, 40], "le bord droit doit rester où il est"
    assert result["bottom"] == [0, 0, 64, 46]
    assert result["topLeftCorner"] == [-10, -6, 74, 46]
    assert result["bothHorizontal"] == [-10, 0, 84, 40]
    assert result["untouched"] == [0, 0, 64, 40]


def test_hands_that_cross_clamp_at_the_minimum_and_never_invert(tmp_path):
    """**Décision 18.** Deux mains qui se croisent ne retournent pas le cadre :
    la taille est bornée au minimum de la forme, donc jamais négative, et le
    manque se répartit au prorata de ce que chaque main a demandé — une seule
    règle pour une main qui pousse et pour deux.

    Le balayage va jusqu'à dix fois la taille du cadre : une inversion se verrait
    comme une largeur négative ou comme un `x` qui dépasse son bord droit."""

    result = run_node(tmp_path, FIXTURE + """
      const min=G.MIN_SIZE.window;
      const rows=[];
      for(let push=0;push<=400;push+=13){
        const b=G.resizeBySides({x:-32,y:-20,w:64,h:40},{left:push,right:-push},'window');
        rows.push([b.x,b.y,b.w,b.h]);
      }
      /* Une seule main qui pousse au-delà du bord opposé : même bornage, et le
         bord immobile reste immobile. */
      const oneHand=G.resizeBySides({x:-32,y:-20,w:64,h:40},{left:500},'window');
      const capsule=G.resizeBySides({x:0,y:0,w:40,h:8},{top:60,bottom:-60},'capsule');
      /* Croisement **asymétrique** : une main a poussé dix fois plus que
         l'autre. Le manque se répartit au prorata, donc le cadre s'arrête près
         de la main qui a le moins bougé — un partage en deux parts égales
         l'emmènerait ailleurs, sans que la taille minimale le dise. */
      const lopsided=G.resizeBySides({x:-32,y:-20,w:64,h:40},{left:200,right:-20},'window');
      /* Contre un bord : pas ici. Les bords de l'écran et des commandes sont
         ceux de la tenue de la page (`createHold`), communs à la souris et à la
         main ; ce calcul ne connaît que les tailles de la forme. */
      const atEdge=G.resizeBySides({x:-152,y:-20,w:64,h:40},{left:-400,right:-200},'window');
      out({rows,min,oneHand:[oneHand.x,oneHand.y,oneHand.w,oneHand.h],
        capsule:[capsule.x,capsule.y,capsule.w,capsule.h],
        capsuleMin:G.MIN_SIZE.capsule,
        lopsided:[lopsided.x,lopsided.y,lopsided.w,lopsided.h],
        atEdge:[atEdge.x,atEdge.y,atEdge.w,atEdge.h],
        safe:G.SAFE_AREA});
    """)
    minimum = result["min"]
    for x, y, w, h in result["rows"]:
        assert w >= minimum["w"], "la largeur est passée sous le minimum"
        assert h >= minimum["h"]
        assert w > 0 and h > 0, "le cadre s'est retourné"
    # Poussée au maximum : exactement la taille minimale, et toujours pas inversé.
    assert result["rows"][-1][2] == minimum["w"]
    assert result["oneHand"][2] == minimum["w"]
    # Le bord droit n'a pas bougé : -32 + 64 = 32.
    assert result["oneHand"][0] + result["oneHand"][2] == 32
    assert result["capsule"][3] == result["capsuleMin"]["h"]
    # Au prorata : la main qui a poussé dix fois plus recule dix fois plus. Un
    # partage en deux parts égales donnerait x = -22 + 9, soit le cadre posé
    # loin de là où les mains l'ont laissé.
    # Le prorata exact vaut x = 168 - 196 × 200/220 = -10,18… (bords des mains
    # à 168 et 12), au dixième d'unité. Il valait -12,9 tant que la zone sûre
    # rabattait le bord gauche à 138 avant le partage (22/09/2026 : les bords
    # sont ceux de la tenue, plus ceux de la zone sûre).
    assert result["lopsided"] == [-10.2, -20, 40, 40]
    # Deux mains qui tirent le même cadre vers la gauche : les deux bords
    # suivent leur main, la taille reste entre ses bornes — et c'est la tenue
    # de la page qui l'arrête au bord de l'écran, comme pour la souris.
    assert result["atEdge"] == [-552, -20, 264, 40]


def test_window_pixels_become_scene_units_exactly_once(tmp_path):
    """La conversion n'a qu'un endroit, et c'est `manipulateBox`. Le moteur
    mesure en **pixels de la fenêtre** (comme `clientX`), la scène vit en unités
    (±160 × ±90), et `vp.scale` vaut ~6 px/unité en 1080p.

    Le leurre est le défaut lui-même : 60 pixels passés tels quels feraient
    60 **unités**, c'est-à-dire un tiers de la scène au lieu de dix unités. Le
    test compare les deux et exige la seconde."""

    result = run_node(tmp_path, FIXTURE + """
      const start={x:0,y:0,w:64,h:40};
      const vp={scale:6};
      const moved=G.manipulateBox({start,representation:'window',mode:'move',
        axes:['x','y'],deltaPx:{dx:60,dy:-30},vp});
      const resized=G.manipulateBox({start,representation:'window',mode:'resize',
        axes:['x'],sidesPx:{right:60},vp});
      /* Un axe neutralisé (décision 17) ne bouge pas, même si une main tire
         dessus : `axes` est ce que le contrat a laissé. */
      const neutralized=G.manipulateBox({start,representation:'window',mode:'resize',
        axes:['x'],sidesPx:{right:60,bottom:60},vp});
      /* Et l'écriture naïve, pour mémoire : les pixels pris pour des unités. */
      const naive=G.resizeBySides(start,{right:60},'window');
      out({moved:[moved.x,moved.y,moved.w,moved.h],
        resized:[resized.x,resized.y,resized.w,resized.h],
        neutralized:[neutralized.x,neutralized.y,neutralized.w,neutralized.h],
        naive:[naive.x,naive.y,naive.w,naive.h],
        badSide:refused(()=>G.manipulateBox({start,representation:'window',mode:'resize',
          axes:['x','y'],sidesPx:{diagonal:10},vp}))});
    """)
    assert result["moved"] == [10, -5, 64, 40], "60 px à 6 px/unité font 10 unités"
    assert result["resized"] == [0, 0, 74, 40]
    assert result["neutralized"] == [0, 0, 74, 40], "l'axe y n'était pas dans `axes`"
    assert result["naive"] == [0, 0, 124, 40], "le leurre : des pixels lus comme des unités"
    assert result["badSide"] == "RangeError"


def test_rebasing_makes_the_very_next_step_a_no_op(tmp_path):
    """**Décision 19**, sa forme la plus nue : rebaser, c'est dire « la
    référence est le cadre tel qu'il est, et les mains là où elles sont ». Le pas
    suivant vaut donc exactement zéro.

    Sans cela, le cadre rattraperait d'un coup tout ce que l'autre main avait
    fait — c'est le saut que la décision interdit."""

    result = run_node(tmp_path, FIXTURE + """
      const start={x:0,y:0,w:64,h:40};
      const vp={scale:6};
      /* Une main a déjà élargi de 20 unités. */
      const grown=G.manipulateBox({start,representation:'window',mode:'resize',
        axes:['x'],sidesPx:{right:120},vp});
      const rebased=G.rebaseManipulation(grown,{'7':{x:500,y:300}});
      const still=G.manipulateBox({start:rebased.start,representation:'window',mode:'move',
        axes:['x','y'],deltaPx:{dx:0,dy:0},vp});
      const then=G.manipulateBox({start:rebased.start,representation:'window',mode:'move',
        axes:['x','y'],deltaPx:{dx:60,dy:0},vp});
      out({grown:[grown.x,grown.y,grown.w,grown.h],
        anchors:rebased.anchorsPx,
        still:[still.x,still.y,still.w,still.h],
        then:[then.x,then.y,then.w,then.h],
        /* Une ancre illisible n'entre pas : la main sans position ne tire rien. */
        dropped:G.rebaseManipulation(grown,{'7':{x:'?',y:3}}).anchorsPx});
    """)
    assert result["grown"] == [0, 0, 84, 40]
    assert result["anchors"] == {"7": {"x": 500, "y": 300}}
    assert result["still"] == [0, 0, 84, 40], "le pas suivant doit être nul"
    assert result["then"] == [10, 0, 84, 40]
    assert result["dropped"] == {}


def test_a_maximum_under_its_minimum_is_refused_where_the_constants_are_read(tmp_path):
    """La paire de constantes de forme, et la raison pour laquelle elle se refuse :
    `clamp(v, lo, hi)` rend **`hi`** quand `lo > hi`. Un maximum passé sous le
    minimum ferait donc gagner le maximum, et la décision 18 s'inverserait en
    silence — aucune exception, aucun test rouge, juste une capsule qu'on peut
    réduire à rien.

    Il n'y a pas de constructeur ici : le refus se pose là où les constantes se
    lisent, au chargement du module. Le test le prouve en chargeant une copie
    mutée.

    **Et il vérifie le rayon du refus, pas seulement son existence** (Slice 11).
    La levée est rattrapée sur place : ce module est le **premier** du `<script>`
    unique de la page servie, donc une levée qui en sortait blanchissait le
    Control Center entier — la scène, la timeline, le Test Lab et Bare Hands —
    pour une constante de capsule. Confinée, la panne garde sa portée : le
    module ne s'installe pas, la console porte la cause sous un nom cherchable,
    et ce qui lit `JarvisSceneInteract` échoue à son tour de façon confinée.
    Refuser et blanchir ne sont pas la même chose."""

    result = run_node(tmp_path, FIXTURE + """
      const fs=require('fs');
      const source=fs.readFileSync(SCENE_INTERACT_PATH,'utf8');
      const broken=source.replace('MAX_SIZE=Object.freeze({capsule:Object.freeze({w:160,h:10})})',
                                  'MAX_SIZE=Object.freeze({capsule:Object.freeze({w:8,h:4})})');
      const errors=[];const realError=console.error;
      console.error=(...a)=>errors.push(a.map(String).join(' '));
      const saved=globalThis.JarvisSceneInteract;
      delete globalThis.JarvisSceneInteract;
      const escaped=refused(()=>{new Function(broken)()});
      const installed=typeof globalThis.JarvisSceneInteract!=='undefined';
      globalThis.JarvisSceneInteract=saved;
      console.error=realError;
      out({mutated:broken!==source,escaped,installed,errors,
        /* Et le défaut qu'il attrape, mesuré sur la fonction elle-même : sans le
           refus, la capsule descendrait sous sa largeur minimale de 16. */
        healthy:G.resizeBySides({x:0,y:0,w:40,h:7},{right:-400},'capsule').w,
        min:G.MIN_SIZE.capsule.w});
    """)
    assert result["mutated"] is True, "la constante visée a changé de nom"
    # Le module refuse **et** ne s'installe pas : les deux moitiés comptent.
    assert result["installed"] is False, "une paire de constantes inversée s'est installée quand même"
    assert any("scene.interact_not_installed" in line for line in result["errors"]), result["errors"]
    assert any("MAX_SIZE.capsule" in line for line in result["errors"]), result["errors"]
    # Et rien n'est sorti du module : c'est ce qui sauve le reste de la page.
    assert result["escaped"] is None, "la levée est sortie du module et emporte tout le `<script>`"
    assert result["healthy"] == result["min"] == 16


# ------------------------------------------------------ captures : une main


def test_one_zone_moves_the_whole_frame_and_never_resizes_it(tmp_path):
    """**Décisions 10 et 11.** Une capture de zone déplace le cadre entier ; il
    faut **deux** zones compatibles pour redimensionner. Une main qui tire le
    bord droit emporte donc l'objet, elle ne l'étire pas — sa taille est la même
    à la fin qu'au début.

    Et rien ne bouge tant que la main n'a pas **glissé** : le seuil est celui de
    la Slice 04 (`dragSlopPx`, mesuré sur la paume), pas un nombre de plus. Sans
    lui, un clic sur un bord déplacerait le cadre — et l'épinglerait, puisque
    toute géométrie de l'utilisateur épingle."""

    result = run_node(tmp_path, FIXTURE + """
      const world=makeWorld({win:{box:{x:0,y:0,w:64,h:40},representation:'window'}});
      const e=engineOf({world:world.api});
      const steps=[];
      const frame=(now,x,y,events,contacts)=>{
        const step=e.update({now,tokens:[tok(1,x,y)],targets:[tgt(1,'win','edge','right')],
          events:events||[],contacts:contacts||[]});
        steps.push(step.interactions.map(i=>i.type));
        return step;
      };
      frame(0,500,300,[ev(1,'down',500,300)],[{handTrackId:1,channel:'primary',state:'pressed',intent:'undecided'}]);
      /* Un contact indécis : la capture est prise (décision 13) mais rien ne
         bouge encore. */
      frame(16,505,300,[],[{handTrackId:1,channel:'primary',state:'pressed',intent:'undecided'}]);
      const beforeArming=world.log.previews.length;
      frame(32,560,300,[],[held(1,'drag')]);
      frame(48,620,300,[],[held(1,'drag')]);
      const last=e.update({now:64,tokens:[tok(1,620,300)],targets:[],
        events:[ev(1,'up',620,300)],contacts:[]});
      out({beforeArming,steps,
        previews:boxes(world.log),
        commits:world.log.commits.map(c=>[c.id,c.mode,c.box.x,c.box.y,c.box.w,c.box.h]),
        lastTypes:last.interactions.map(i=>i.type),
        cancels:world.log.cancels,
        captured:e.capturedHands()});
    """)
    assert result["beforeArming"] == 0, "un contact indécis ne déplace rien"
    # Le seuil décide **si** la main glisse, jamais **de combien** : à l'image
    # où l'intention bascule, le cadre rattrape les 60 px parcourus depuis la
    # descente (10 unités), et l'image suivante en ajoute 60 autres. Sans ce
    # rattrapage, le curseur devançait le cadre de tout le seuil pendant le
    # geste entier, puis le cadre se posait en arrière de la main qui le
    # lâchait.
    assert result["previews"] == [[10, 0, 64, 40], [20, 0, 64, 40]], result["previews"]
    assert result["previews"][-1][2] == 64 and result["previews"][-1][3] == 40, (
        "une seule main ne redimensionne jamais"
    )
    assert [c[1] for c in result["commits"]] == ["move"]
    assert result["commits"][0][2:] == [20, 0, 64, 40]
    assert result["cancels"] == []
    assert result["captured"] == []
    # Aucun clic publié : la main a déplacé, elle n'a pas cliqué.
    assert "click" not in sum(result["steps"], []) + result["lastTypes"]
    assert "move" in sum(result["steps"], [])


def test_a_hand_that_opens_to_let_go_no_longer_drags_the_frame(tmp_path):
    """Le relâchement se confirme sur quelques images, pendant lesquelles la
    main s'ouvre et se retire : la paume bouge encore. Le cadre suivait cette
    paume brute et se posait à côté de là où on l'avait vu en lâchant
    (22/09/2026). La paume de la première image ouverte (`releasing`) vaut
    désormais pour toute la confirmation — et si le pincement revient, la main
    reprend là où elle est."""

    result = run_node(tmp_path, FIXTURE + """
      const world=makeWorld({win:{box:{x:0,y:0,w:64,h:40},representation:'window'}});
      const e=engineOf({world:world.api});
      const opening=Object.assign(held(1,'drag'),{releasing:true});
      const frame=(now,x,contacts,events)=>e.update({now,tokens:[tok(1,x,300)],
        targets:[tgt(1,'win','edge','right')],events:events||[],contacts});
      frame(0,500,[{handTrackId:1,channel:'primary',state:'pressed',intent:'undecided'}],[ev(1,'down',500,300)]);
      frame(16,560,[held(1,'drag')]);
      frame(32,620,[held(1,'drag')]);
      const beforeOpening=world.log.previews.length;
      /* La main s'ouvre et part vers la droite pendant la confirmation. */
      frame(48,680,[opening]);
      frame(64,740,[opening]);
      const whileOpening=world.log.previews.length-beforeOpening;
      e.update({now:80,tokens:[tok(1,800,300)],targets:[],events:[ev(1,'up',800,300)],contacts:[]});
      /* Second geste : le pincement revient après une image douteuse. */
      const again=makeWorld({win:{box:{x:0,y:0,w:64,h:40},representation:'window'}});
      const e2=engineOf({world:again.api});
      const frame2=(now,x,contacts,events)=>e2.update({now,tokens:[tok(1,x,300)],
        targets:[tgt(1,'win','edge','right')],events:events||[],contacts});
      frame2(0,500,[{handTrackId:1,channel:'primary',state:'pressed',intent:'undecided'}],[ev(1,'down',500,300)]);
      frame2(16,560,[held(1,'drag')]);
      frame2(32,620,[opening]);
      frame2(48,680,[held(1,'drag')]);
      out({whileOpening,commits:world.log.commits.map(c=>[c.box.x,c.box.y]),
        resumed:boxes(again.log).map(b=>b[0])});
    """)
    # Pas un aperçu de plus pendant que la main s'ouvre, et le cadre est posé
    # là où il était à la première image ouverte (620 px → 20 unités).
    assert result["whileOpening"] == 0
    assert result["commits"] == [[20, 0]]
    # Le pincement revenu, la main reprend où elle est : 680 px → 30 unités.
    assert result["resumed"] == [10, 30]


def test_the_pinch_channel_says_when_a_release_is_being_confirmed(tmp_path):
    """`releasing` dans les contacts publiés : vrai de la première image ouverte
    jusqu'à la confirmation du relâchement, faux avant et après."""

    result = run_node(tmp_path, """
      const ch=B.createPinchChannel('primary',{});
      const s=(now,ratio)=>ch.update({handTrackId:1,ratio,other:1,confidence:1,quality:1,stillness:1,
        now,x:100,y:100,palmX:100,palmY:100,anchorX:100,anchorY:100});
      const seen=[];
      for(const [now,ratio] of [[0,.1],[33,.1],[66,.9],[100,.9],[133,.9],[166,.9]]){s(now,ratio);seen.push([ch.state(),ch.releasing()])}
      out(seen);
    """)
    states = [state for state, _ in result]
    releasing = [flag for _, flag in result]
    assert states[1] == "pressed" and states[-1] == "open", states
    # Pincé : rien ne se relâche ; première image ouverte : ça se confirme.
    assert releasing[:2] == [False, False] and releasing[2] is True, releasing
    # Confirmé : plus rien à confirmer.
    assert releasing[-1] is False


def test_a_click_on_a_manipulation_zone_moves_nothing_and_stays_a_click(tmp_path):
    """Le pendant du test précédent : un contact court sur un bord ne déplace
    rien et reste un **clic**. C'est ce qui protège la décision 9 d'un effet de
    bord irréversible — toute géométrie de l'utilisateur épingle l'objet, donc un
    bord qui bougerait d'un pixel à chaque clic épinglerait la scène entière sans
    que personne ne l'ait demandé."""

    result = run_node(tmp_path, FIXTURE + """
      const world=makeWorld({win:{box:{x:0,y:0,w:64,h:40},representation:'window'}});
      const e=engineOf({world:world.api});
      e.update({now:0,tokens:[tok(1,500,300)],targets:[tgt(1,'win','edge','right')],
        events:[ev(1,'down',500,300)],contacts:[{handTrackId:1,channel:'primary',state:'pressed',intent:'undecided'}]});
      e.update({now:16,tokens:[tok(1,503,301)],targets:[tgt(1,'win','edge','right')],
        events:[],contacts:[{handTrackId:1,channel:'primary',state:'pressed',intent:'undecided'}]});
      const last=e.update({now:120,tokens:[tok(1,503,301)],targets:[],
        events:[ev(1,'up',503,301)],contacts:[]});
      out({types:last.interactions.map(i=>i.type),
        object:last.interactions.map(i=>i.objectId),
        begins:world.log.begins,previews:world.log.previews.length,
        commits:world.log.commits.length,driven:e.drivenHands()});
    """)
    assert result["types"] == ["click"]
    assert result["object"] == ["win"]
    assert result["begins"] == [], "la scène n'a même pas été sollicitée"
    assert result["previews"] == 0 and result["commits"] == 0
    assert result["driven"] == [], "le clic hérité doit pouvoir partir"


def test_the_body_of_a_window_is_content_and_the_body_of_a_star_is_its_only_grip(tmp_path):
    """**Décision 8 contre décision D3.** Le corps d'une capsule ou d'une fenêtre
    est de l'interaction de **contenu** : le tirer ne déplace pas le cadre, et
    c'est le critère d'acceptation « BODY ne déplace jamais un cadre par
    accident ».

    Mais une étoile `point` ou `signal` n'a **pas** de zones (elle n'est pas
    redimensionnable) : son corps est sa seule prise, et « déplaçable seulement »
    ne peut pas vouloir dire « pas déplaçable ». La règle se lit donc sur la
    représentation, jamais sur la classe dessinée."""

    result = run_node(tmp_path, FIXTURE + """
      const run=(representation)=>{
        const world=makeWorld({obj:{box:{x:0,y:0,w:64,h:40},representation}});
        const dom=makeDom([]);
        const e=engineOf({world:world.api,dom:dom.api});
        const target=tgt(1,'obj','body',null,{representation});
        e.update({now:0,tokens:[tok(1,500,300)],targets:[target],
          events:[ev(1,'down',500,300)],contacts:[held(1,'undecided')]});
        e.update({now:16,tokens:[tok(1,560,300)],targets:[target],events:[],contacts:[held(1,'drag')]});
        e.update({now:32,tokens:[tok(1,620,300)],targets:[target],events:[],contacts:[held(1,'drag')]});
        const last=e.update({now:48,tokens:[tok(1,620,300)],targets:[],events:[ev(1,'up',620,300)],contacts:[]});
        return {previews:boxes(world.log),commits:world.log.commits.length,
          dom:dom.log.map(d=>d.type),
          last:last.interactions.map(i=>i.type)};
      };
      out({window:run('window'),capsule:run('capsule'),point:run('point'),signal:run('signal')});
    """)
    for zoned in ("window", "capsule"):
        assert result[zoned]["previews"] == [], f"{zoned} : le corps a déplacé le cadre"
        assert result[zoned]["commits"] == 0
        # Contenu d'une étoile : **aucune séquence de pointeur**. La page de
        # scène lit un glissement de pointeur sur `.sc-node` comme un
        # déplacement de cadre : l'émettre ferait par un autre chemin
        # exactement ce que la décision 8 interdit. Il reste un `select`, qui
        # ne déplace rien.
        assert result[zoned]["dom"] == ["select"], result[zoned]["dom"]
        assert result[zoned]["last"] == ["select"]
    for moveOnly in ("point", "signal"):
        assert len(result[moveOnly]["previews"]) > 0, f"{moveOnly} : l'étoile ne se déplace plus"
        assert result[moveOnly]["commits"] == 1
        # `move` traverse l'adaptateur DOM sans qu'il en fasse rien : il n'y a
        # pas d'équivalent de pointeur à un déplacement de cadre, c'est la scène
        # qui l'applique.
        assert set(result[moveOnly]["dom"]) == {"move"}
    for case in result.values():
        assert not [kind for kind in case["dom"] if kind.startswith("drag_")], (
            "une séquence de pointeur est partie sur une étoile"
        )


# ----------------------------------------------------- captures : deux mains


def test_two_zones_on_one_frame_resize_it_with_the_sides_the_contract_gave(tmp_path):
    """**Décisions 11, 16 et 17**, et la raison pour laquelle ce moteur lit
    `byHand[id].sides` plutôt que les axes : deux mains peuvent tenir le même axe
    par deux **côtés opposés**, ce qui est un redimensionnement légitime, et une
    lecture par axes seuls y verrait un conflit.

    Trois couples, trois attributions, et on regarde ce que le cadre fait :

    - deux bords opposés : les deux axes travaillent, chacun d'un côté ;
    - bord + coin qui se recouvrent (16) : le **bord** garde le côté partagé, le
      coin ne garde que l'autre ;
    - deux coins sur un même côté (17) : ce côté est neutralisé, son axe
      disparaît, et la dimension correspondante ne change pas d'une unité."""

    result = run_node(tmp_path, FIXTURE + """
      const run=(zoneA,zoneB,moveA,moveB)=>{
        const world=makeWorld({win:{box:{x:-32,y:-20,w:64,h:40},representation:'window'}});
        const e=engineOf({world:world.api});
        const targets=[tgt(1,'win','edge',zoneA),tgt(2,'win','edge',zoneB)];
        if(C.CORNERS.includes(zoneA))targets[0]=tgt(1,'win','corner',zoneA);
        if(C.CORNERS.includes(zoneB))targets[1]=tgt(2,'win','corner',zoneB);
        const at=(n,a,b)=>[tok(1,a.x,a.y),tok(2,b.x,b.y)];
        const home={x:400,y:300},away={x:900,y:700};
        e.update({now:0,tokens:at(0,home,away),targets,
          events:[ev(1,'down',home.x,home.y),ev(2,'down',away.x,away.y)],
          contacts:[held(1,'undecided'),held(2,'undecided')]});
        /* Les deux mains glissent ensemble : le plan s'arme une fois, et la
           signature ne change plus. */
        const after=(k)=>({x:home.x+moveA[0]*k,y:home.y+moveA[1]*k});
        const afterB=(k)=>({x:away.x+moveB[0]*k,y:away.y+moveB[1]*k});
        const published=[];
        for(let k=1;k<=4;k+=1){
          const step=e.update({now:16*k,tokens:at(k,after(k),afterB(k)),targets,events:[],
            contacts:[held(1,'drag'),held(2,'drag')]});
          for(const interaction of step.interactions)
            if(interaction.type==='resize')published.push([...interaction.axes]);
        }
        const verdict=C.combineCaptures(
          C.createCapture({handTrackId:1,objectId:'win',region:C.CORNERS.includes(zoneA)?'corner':'edge',zone:zoneA}),
          C.createCapture({handTrackId:2,objectId:'win',region:C.CORNERS.includes(zoneB)?'corner':'edge',zone:zoneB}));
        e.update({now:200,tokens:at(5,after(4),afterB(4)),targets:[],
          events:[ev(1,'up',0,0),ev(2,'up',0,0)],contacts:[]});
        const commit=world.log.commits[0];
        return {axes:[...verdict.axes],mode:verdict.mode,
          byHand:Object.keys(verdict.byHand).sort().map(id=>[id,[...verdict.byHand[id].sides]]),
          /* Les axes voyagent **dans l'événement publié** : c'est ce que le
             contrat promet (`axes` repris tel quel de `combineCaptures`) et ce
             qu'un consommateur lira pour savoir ce qui a bougé. */
          published:[...new Set(published.map(a=>a.join('')))],
          commit:commit?[commit.mode,commit.box.x,commit.box.y,commit.box.w,commit.box.h]:null};
      };
      out({
        opposite:run('left','right',[-60,0],[60,0]),
        edgeAndCorner:run('right','top_right',[60,0],[0,-60]),
        twoCornersSharingRight:run('top_right','bottom_right',[60,-60],[60,60]),
        oppositeCorners:run('top_left','bottom_right',[-60,-60],[60,60]),
      });
    """)
    opposite = result["opposite"]
    assert opposite["mode"] == "resize" and opposite["axes"] == ["x"]
    assert opposite["published"] == ["x"], "l'événement ne porte pas ses axes"
    # 40 unités de chaque côté (240 px à 6 px/unité, comptés depuis la
    # **descente** : le seuil dit si la main glisse, pas de combien) :
    # 64 + 80, hauteur intacte — l'axe y n'était tenu par personne.
    assert opposite["commit"] == ["resize", -72, -20, 144, 40]

    shared = result["edgeAndCorner"]
    assert shared["byHand"] == [["1", ["right"]], ["2", ["top"]]], (
        "décision 16 : le bord garde le côté partagé, le coin ne garde que l'autre"
    )
    assert shared["axes"] == ["x", "y"]
    # Le bord droit emmène la largeur, le coin ne tire que sur le haut : le
    # bord gauche et le bas n'ont bougé d'aucune unité.
    assert shared["commit"] == ["resize", -32, -60, 104, 80]

    neutral = result["twoCornersSharingRight"]
    assert neutral["axes"] == ["y"], "décision 17 : le côté partagé neutralise son axe"
    assert neutral["published"] == ["y"]
    assert neutral["commit"][3] == 64, "la largeur ne doit pas avoir changé d'une unité"
    assert neutral["commit"][4] == 120, "les deux coins tirent chacun son côté vertical"
    assert neutral["commit"][1] == -32, "le bord gauche est resté où il était"

    corners = result["oppositeCorners"]
    assert corners["axes"] == ["x", "y"]
    assert corners["published"] == ["xy"]
    assert corners["commit"] == ["resize", -72, -60, 144, 120]


def test_a_body_and_a_zone_never_form_a_resize(tmp_path):
    """**Décisions 14 et 10.** ZONE + CORPS ne forme pas un redimensionnement :
    le déplacement appartient à la **seule main qui tient la zone**, et elle tire
    les deux axes. C'est `combineCaptures` qui le dit (`mode: move`,
    `body_is_not_a_resize_handle`), et le moteur ne fait que l'appliquer — ce
    pourquoi la capture de corps entre bien dans le couple au lieu d'être filtrée
    avant : la filtrer rendrait la règle inatteignable et la réécrirait ici."""

    result = run_node(tmp_path, FIXTURE + """
      const world=makeWorld({win:{box:{x:0,y:0,w:64,h:40},representation:'window'}});
      const dom=makeDom([]);
      const e=engineOf({world:world.api,dom:dom.api});
      const targets=[tgt(1,'win','edge','right'),tgt(2,'win','body',null)];
      const step=(k,a,b)=>e.update({now:16*k,tokens:[tok(1,a,300),tok(2,b,700)],targets,
        events:k===0?[ev(1,'down',a,300),ev(2,'down',b,700)]:[],
        contacts:[held(1,k===0?'undecided':'drag'),held(2,k===0?'undecided':'drag')]});
      step(0,400,900);
      for(let k=1;k<=3;k+=1)step(k,400+60*k,900-60*k);
      const verdict=C.combineCaptures(
        C.createCapture({handTrackId:1,objectId:'win',region:'edge',zone:'right'}),
        C.createCapture({handTrackId:2,objectId:'win',region:'body'}));
      e.update({now:500,tokens:[],targets:[],events:[ev(1,'up',0,0),ev(2,'up',0,0)],contacts:[]});
      const commit=world.log.commits[0];
      out({mode:verdict.mode,reason:verdict.reason,
        byHand:Object.keys(verdict.byHand),
        commit:[commit.mode,commit.box.x,commit.box.y,commit.box.w,commit.box.h]});
    """)
    assert result["mode"] == "move" and result["reason"] == "body_is_not_a_resize_handle"
    assert result["byHand"] == ["1"], "seule la main qui tient la zone déplace"
    # La main de zone est partie de 180 px vers la droite depuis sa descente :
    # 30 unités, taille intacte — et la main de corps, partie dans l'autre sens,
    # n'a rien tiré du tout.
    assert result["commit"] == ["move", 30, 0, 64, 40]


def test_two_bodies_on_one_window_carry_nothing_away(tmp_path):
    """**Décision 8.** Deux mains dans le contenu d'une fenêtre ne l'emportent
    pas. Le défaut que la reprise de la Slice 01 a corrigé dans le contrat était
    exactement celui-là — une branche qui déclenchait dès que **l'une** des deux
    captures était un corps — et ce test est ce qui l'empêche de revenir par le
    moteur."""

    result = run_node(tmp_path, FIXTURE + """
      const world=makeWorld({win:{box:{x:0,y:0,w:64,h:40},representation:'window'}});
      const e=engineOf({world:world.api});
      const targets=[tgt(1,'win','body',null),tgt(2,'win','body',null)];
      e.update({now:0,tokens:[tok(1,400,300),tok(2,900,700)],targets,
        events:[ev(1,'down',400,300),ev(2,'down',900,700)],
        contacts:[held(1,'undecided'),held(2,'undecided')]});
      for(let k=1;k<=3;k+=1)
        e.update({now:16*k,tokens:[tok(1,400+60*k,300),tok(2,900-60*k,700)],targets,
          events:[],contacts:[held(1,'drag'),held(2,'drag')]});
      const verdict=C.combineCaptures(
        C.createCapture({handTrackId:1,objectId:'win',region:'body'}),
        C.createCapture({handTrackId:2,objectId:'win',region:'body'}));
      out({mode:verdict.mode,reason:verdict.reason,
        begins:world.log.begins,previews:world.log.previews.length,
        commits:world.log.commits.length});
    """)
    assert result["mode"] is None and result["reason"] == "both_captures_are_body"
    assert result["begins"] == [] and result["previews"] == 0 and result["commits"] == 0


def test_the_same_zone_twice_is_refused_and_the_screen_says_so(tmp_path):
    """**Décision 15.** Deux captures de la **même** zone se refusent : aucune
    des deux ne déplace, et les deux restent latchées jusqu'au relâchement
    (décision 13).

    RÈGLE ZÉRO : un refus qui ne se voit pas est une main qui insiste sans effet,
    indiscernable d'une panne. La raison remonte donc, telle quelle."""

    result = run_node(tmp_path, FIXTURE + """
      const world=makeWorld({win:{box:{x:0,y:0,w:64,h:40},representation:'window'}});
      const dom=makeDom([]);
      const e=engineOf({world:world.api,dom:dom.api});
      const targets=[tgt(1,'win','edge','right'),tgt(2,'win','edge','right')];
      e.update({now:0,tokens:[tok(1,400,300),tok(2,420,320)],targets,
        events:[ev(1,'down',400,300),ev(2,'down',420,320)],
        contacts:[held(1,'undecided'),held(2,'undecided')]});
      const step=e.update({now:16,tokens:[tok(1,500,300),tok(2,520,320)],targets,
        events:[],contacts:[held(1,'drag'),held(2,'drag')]});
      const held2=e.update({now:32,tokens:[tok(1,600,300),tok(2,620,320)],targets,
        events:[],contacts:[held(1,'drag'),held(2,'drag')]});
      const whileRefused=world.log.previews.length;
      const domDuring=[...new Set(dom.log.map(d=>d.type))];
      /* Une main se retire : l'autre tient toujours sa zone, et redevient
         simplement un déplacement (décision 10). */
      const released=e.update({now:48,tokens:[tok(1,600,300)],targets:[targets[0]],
        events:[ev(2,'up',620,320)],contacts:[held(1,'drag')]});
      const after=e.update({now:64,tokens:[tok(1,660,300)],targets:[targets[0]],
        events:[],contacts:[held(1,'drag')]});
      out({refusals:step.refusals.map(r=>r.reason),
        stillRefused:held2.refusals.map(r=>r.reason),
        /* Refusée ne veut pas dire « retombée en contenu » : une zone n'est
           jamais du contenu, donc rien ne part non plus vers le DOM. */
        dom:domDuring,
        /* Et au relâchement : ni sélection — une zone n'est jamais du contenu
           — ni clic, parce que le contact a **glissé** (`drag` décidé en cours
           de route). Refusé ou non, un glissement n'est pas un clic. */
        releasedTypes:released.interactions.map(i=>i.type),
        previews:whileRefused,
        stillHeld:step.captures.sort(),
        afterPreviews:world.log.previews.length,
        afterBoxes:boxes(world.log),
        afterTypes:[...new Set(after.interactions.map(i=>i.type))]});
    """)
    assert result["refusals"] == ["same_zone_rejected"]
    assert result["stillRefused"] == ["same_zone_rejected"], "le refus se redit à chaque image"
    assert result["previews"] == 0, "aucune des deux mains ne déplace"
    assert result["dom"] == [], "une zone refusée est partie traîner du contenu"
    assert result["releasedTypes"] == [], result["releasedTypes"]
    assert result["stillHeld"] == [1, 2], "les deux captures restent latchées"
    assert result["afterPreviews"] > 0, "une main restée seule déplace de nouveau"
    assert result["afterTypes"] == ["move"]
    # Et elle part de là où elle est, pas de sa descente : 60 px depuis le
    # retrait de l'autre main, pas 260 depuis le début.
    assert result["afterBoxes"] == [[10, 0, 64, 40]]


def test_a_right_click_never_joins_a_manipulation(tmp_path):
    """**Décisions 21 et 23.** Le clic droit est une **intention**, pas une
    partie du cadre : un coin visé au pouce-majeur est rouge, pas jaune. Seules
    les captures du canal primaire entrent donc dans un couple, et une main qui
    fait un clic droit sur un bord ne redimensionne rien — même si une autre
    main tient le bord opposé.

    Sans cette règle, tenir un objet d'une main et ouvrir son menu de l'autre
    l'étirerait au passage."""

    result = run_node(tmp_path, FIXTURE + """
      const world=makeWorld({win:{box:{x:-32,y:-20,w:64,h:40},representation:'window'}});
      const e=engineOf({world:world.api});
      const right=Object.assign(tgt(2,'win','edge','right'),{channel:'secondary'});
      const targets=[tgt(1,'win','edge','left'),right];
      e.update({now:0,tokens:[tok(1,400,300),tok(2,900,300)],targets,
        events:[ev(1,'down',400,300),Object.assign(ev(2,'down',900,300),{channel:'secondary'})],
        contacts:[held(1,'undecided'),held(2,'undecided','secondary')]});
      for(let k=1;k<=3;k+=1)
        e.update({now:16*k,tokens:[tok(1,400-60*k,300),tok(2,900+60*k,300)],targets,
          events:[],contacts:[held(1,'drag'),held(2,'drag','secondary')]});
      const last=e.update({now:200,tokens:[tok(1,220,300),tok(2,1080,300)],targets:[],
        events:[ev(1,'up',220,300),Object.assign(ev(2,'up',1080,300),{channel:'secondary'})],
        contacts:[]});
      const commit=world.log.commits[0];
      out({commits:world.log.commits.length,
        commit:[commit.mode,commit.box.x,commit.box.y,commit.box.w,commit.box.h],
        types:last.interactions.map(i=>[i.type,i.channel])});
    """)
    # Un déplacement, jamais un redimensionnement : la main droite ne comptait pas.
    assert result["commits"] == 1
    assert result["commit"] == ["move", -62, -20, 64, 40]
    # Et le clic droit fait ce qu'il doit : un contexte au relâchement.
    assert ["context", "secondary"] in result["types"]


def test_two_hands_on_two_objects_stay_independent(tmp_path):
    """**Décision 12.** Deux mains sur deux objets distincts ne se couplent pas :
    chacune déplace le sien, chacune valide le sien, et aucune ne lit la
    géométrie de l'autre."""

    result = run_node(tmp_path, FIXTURE + """
      const world=makeWorld({a:{box:{x:-40,y:0,w:64,h:40},representation:'window'},
                             b:{box:{x:40,y:0,w:40,h:7},representation:'capsule'}});
      const e=engineOf({world:world.api});
      const targets=[tgt(1,'a','edge','right'),tgt(2,'b','edge','left',{representation:'capsule'})];
      e.update({now:0,tokens:[tok(1,400,300),tok(2,900,700)],targets,
        events:[ev(1,'down',400,300),ev(2,'down',900,700)],
        contacts:[held(1,'undecided'),held(2,'undecided')]});
      for(let k=1;k<=3;k+=1)
        e.update({now:16*k,tokens:[tok(1,400+60*k,300),tok(2,900,700+60*k)],targets,
          events:[],contacts:[held(1,'drag'),held(2,'drag')]});
      e.update({now:500,tokens:[],targets:[],events:[ev(1,'up',0,0),ev(2,'up',0,0)],contacts:[]});
      out({commits:world.log.commits.map(c=>[c.id,c.mode,c.box.x,c.box.y,c.box.w,c.box.h]).sort()});
    """)
    # Chacun déplacé sur son propre axe, et rien de l'un dans l'autre.
    assert result["commits"] == [
        ["a", "move", -10, 0, 64, 40],
        ["b", "move", 40, 30, 40, 7],
    ]


def test_a_capture_latches_until_release(tmp_path):
    """**Décision 13.** La capture est figée à la descente : l'objet, la région
    et la zone. Le moteur ne relit pas la cible à chaque image — et le test le
    prouve en lui **mentant** après la descente, avec une cible qui désigne un
    autre objet et une autre zone. C'est l'objet saisi qui bouge, jusqu'au
    relâchement."""

    result = run_node(tmp_path, FIXTURE + """
      const world=makeWorld({a:{box:{x:0,y:0,w:64,h:40},representation:'window'},
                             b:{box:{x:100,y:0,w:64,h:40},representation:'window'}});
      const e=engineOf({world:world.api});
      e.update({now:0,tokens:[tok(1,400,300)],targets:[tgt(1,'a','edge','right')],
        events:[ev(1,'down',400,300)],contacts:[held(1,'undecided')]});
      /* La main a glissé de 30 px : la cible dynamique désignerait maintenant
         l'autre objet, par son coin. La capture, elle, ne bouge pas. */
      for(let k=1;k<=3;k+=1)
        e.update({now:16*k,tokens:[tok(1,400+60*k,300)],targets:[tgt(1,'b','corner','top_left')],
          events:[],contacts:[held(1,'drag')]});
      e.update({now:500,tokens:[],targets:[],events:[ev(1,'up',0,0)],contacts:[]});
      out({begins:world.log.begins,
        commits:world.log.commits.map(c=>[c.id,c.box.x,c.box.w,c.box.h])});
    """)
    assert result["begins"] == ["a"], "l'objet capturé a changé en cours de geste"
    assert result["commits"] == [["a", 30, 64, 40]]


def test_releasing_one_hand_from_a_resize_continues_as_a_move_with_no_jump(tmp_path):
    """**Décision 19.** Une main quitte le redimensionnement : l'autre continue
    en déplacement, et le cadre **ne saute pas**.

    Le saut est ce qui arriverait sans rebasage : la main restante a déjà
    parcouru 120 px depuis sa descente, et ces 120 px seraient réinterprétés d'un
    coup comme un déplacement du cadre entier. Le test mesure donc l'image du
    changement : elle doit être identique à la précédente."""

    result = run_node(tmp_path, FIXTURE + """
      const world=makeWorld({win:{box:{x:-32,y:-20,w:64,h:40},representation:'window'}});
      const e=engineOf({world:world.api});
      const targets=[tgt(1,'win','edge','left'),tgt(2,'win','edge','right')];
      const shot=[];
      const take=()=>{const p=world.log.previews;shot.push(p.length?[p[p.length-1].box.x,p[p.length-1].box.y,
        p[p.length-1].box.w,p[p.length-1].box.h]:null)};
      e.update({now:0,tokens:[tok(1,400,300),tok(2,900,300)],targets,
        events:[ev(1,'down',400,300),ev(2,'down',900,300)],
        contacts:[held(1,'undecided'),held(2,'undecided')]});
      for(let k=1;k<=2;k+=1){
        e.update({now:16*k,tokens:[tok(1,400-60*k,300),tok(2,900+60*k,300)],targets,
          events:[],contacts:[held(1,'drag'),held(2,'drag')]});
        take();
      }
      const resized=shot[shot.length-1];
      /* La main 2 se retire **sans que la main 1 ne bouge** : l'image suivante
         doit être exactement la même boîte. */
      e.update({now:48,tokens:[tok(1,280,300)],targets:[targets[0]],
        events:[ev(2,'up',1020,300)],contacts:[held(1,'drag')]});
      take();
      const rebased=shot[shot.length-1];
      /* Puis la main 1 repart : le cadre se déplace, il ne s'étire plus. */
      e.update({now:64,tokens:[tok(1,220,300)],targets:[targets[0]],
        events:[],contacts:[held(1,'drag')]});
      take();
      e.update({now:500,tokens:[],targets:[],events:[ev(1,'up',0,0)],contacts:[]});
      /* Et le cas qui n'a l'air de rien : la main perdue **revient** sous une
         autre identité de piste (au-delà de `lostGraceMs`, c'est une main
         neuve) et reprend le bord opposé. L'attribution a changé sans que le
         mode ni les axes ne changent : si la signature ne disait pas *qui*
         tient *quoi*, la nouvelle main n'aurait jamais d'ancre — elle tirerait
         dans le vide, pour toujours. */
      const again=makeWorld({win:{box:{x:-32,y:-20,w:64,h:40},representation:'window'}});
      const e2=engineOf({world:again.api});
      const pair=[tgt(1,'win','edge','left'),tgt(2,'win','edge','right')];
      e2.update({now:0,tokens:[tok(1,400,300),tok(2,900,300)],targets:pair,
        events:[ev(1,'down',400,300),ev(2,'down',900,300)],
        contacts:[held(1,'undecided'),held(2,'undecided')]});
      e2.update({now:16,tokens:[tok(1,340,300),tok(2,960,300)],targets:pair,
        events:[],contacts:[held(1,'drag'),held(2,'drag')]});
      e2.update({now:32,tokens:[tok(1,280,300),tok(2,1020,300)],targets:pair,
        events:[],contacts:[held(1,'drag'),held(2,'drag')]});
      const widened=boxes(again.log).pop();
      /* La main 2 se perd, la main 3 reprend le même bord. */
      const back=[tgt(1,'win','edge','left'),tgt(3,'win','edge','right')];
      e2.update({now:48,tokens:[tok(1,280,300),tok(3,1020,300)],targets:back,
        events:[ev(2,'cancel'),ev(3,'down',1020,300)],
        contacts:[held(1,'drag'),held(3,'undecided')]});
      e2.update({now:64,tokens:[tok(1,280,300),tok(3,1080,300)],targets:back,
        events:[],contacts:[held(1,'drag'),held(3,'drag')]});
      e2.update({now:80,tokens:[tok(1,280,300),tok(3,1140,300)],targets:back,
        events:[],contacts:[held(1,'drag'),held(3,'drag')]});
      out({resized,rebased,after:shot[shot.length-1],
        commits:world.log.commits.map(c=>[c.mode,c.box.x,c.box.y,c.box.w,c.box.h]),
        widened,regrabbed:boxes(again.log).pop()});
    """)
    # Deux mains ont écarté le cadre de 120 px chacune depuis leur descente :
    # 20 unités par côté, donc 64 + 40.
    assert result["resized"] == [-52, -20, 104, 40]
    # Le retrait d'une main ne bouge rien : c'est le rebasage.
    assert result["rebased"] == result["resized"], "le cadre a sauté au retrait d'une main"
    # Puis 60 px de paume = 10 unités de déplacement, taille inchangée.
    assert result["after"] == [-62, -20, 104, 40]
    assert result["commits"] == [["move", -62, -20, 104, 40]]
    # La main revenue sous une autre identité tire pour de bon : le cadre
    # s'élargit encore de 20 unités, alors que le mode et les axes n'ont pas
    # changé. Sans « qui tient quoi » dans la signature, elle n'aurait pas
    # d'ancre et ne tirerait plus jamais rien.
    assert result["widened"] == [-52, -20, 104, 40]
    assert result["regrabbed"] == [-52, -20, 124, 40], result["regrabbed"]


# ----------------------------------------------- refus, annulation et contenu


def test_every_reason_the_contract_can_return_is_handled(tmp_path):
    """`combineCaptures` rend quatre motifs que le chemin réel n'atteint pas tous
    — `same_hand_twice` est écarté par la construction du couple,
    `object_unidentified` par le regroupement, `axes_all_neutralized` est un filet
    du contrat. Un motif non traité serait un silence : ni géométrie, ni refus, ni
    trace.

    Le test substitue donc un `combineCaptures` qui rend chaque motif à son tour
    et regarde ce que le moteur en fait. C'est la seule façon d'exercer les
    branches que la réalité ne produit pas — et de garantir qu'un motif **futur**
    tombe dans le refus plutôt que dans le vide."""

    result = run_node(tmp_path, FIXTURE + """
      const run=(verdict)=>{
        const world=makeWorld({win:{box:{x:0,y:0,w:64,h:40},representation:'window'}});
        const contracts=Object.assign({},C,{combineCaptures:(a,b)=>b?verdict:C.combineCaptures(a,b)});
        const e=B.createInteractionEngine({contracts,geometry:G,world:world.api});
        const targets=[tgt(1,'win','edge','left'),tgt(2,'win','edge','right')];
        e.update({now:0,tokens:[tok(1,400,300),tok(2,900,300)],targets,
          events:[ev(1,'down',400,300),ev(2,'down',900,300)],
          contacts:[held(1,'undecided'),held(2,'undecided')]});
        /* Deux images : la première arme le plan (et le rebase, donc elle ne
           bouge rien), la seconde le fait avancer. */
        e.update({now:16,tokens:[tok(1,340,300),tok(2,960,300)],targets,
          events:[],contacts:[held(1,'drag'),held(2,'drag')]});
        const step=e.update({now:32,tokens:[tok(1,280,300),tok(2,1020,300)],targets,
          events:[],contacts:[held(1,'drag'),held(2,'drag')]});
        return {refusals:step.refusals.map(r=>r.reason),
          previews:world.log.previews.length,
          box:world.log.previews.length?boxes(world.log).pop():null};
      };
      const none=(reason)=>({mode:null,axes:[],byHand:{},reason});
      out({
        sameHand:run(none('same_hand_twice')),
        unidentified:run({mode:'independent',axes:[],byHand:{},reason:'object_unidentified'}),
        bothBody:run(none('both_captures_are_body')),
        neutralized:run(none('axes_all_neutralized')),
        sameZone:run(none('same_zone_rejected')),
        unknown:run(none('a_reason_from_the_future')),
      });
    """)
    # Une main deux fois : le couple n'existe pas, la première capture déplace seule.
    assert result["sameHand"]["refusals"] == [] and result["sameHand"]["previews"] > 0
    assert result["sameHand"]["box"] == [-20, 0, 64, 40]
    # Objets non identifiés : indépendants, donc aucun couple et aucun refus.
    assert result["unidentified"]["refusals"] == [] and result["unidentified"]["previews"] == 0
    # Deux corps : rien, et c'est la décision 8 — pas un refus à afficher.
    assert result["bothBody"]["refusals"] == [] and result["bothBody"]["previews"] == 0
    # Axes tous neutralisés, même zone, motif inconnu : refus, jamais silence.
    assert result["neutralized"]["refusals"] == ["axes_all_neutralized"]
    assert result["sameZone"]["refusals"] == ["same_zone_rejected"]
    assert result["unknown"]["refusals"] == ["a_reason_from_the_future"]
    for case in ("neutralized", "sameZone", "unknown"):
        assert result[case]["previews"] == 0


def test_a_lost_hand_cancels_the_manipulation_and_commits_nothing(tmp_path):
    """La perte donne un `cancel`, **jamais** un `up` : le cadre revient où il
    était et rien ne part à Core — la même réponse que `pointercancel` à la
    souris. Traiter l'annulation comme un relâchement court validerait une
    géométrie dont on ne sait plus si la main l'a voulue.

    Trois routes y mènent, et les trois comptent : le canal qui annule, la main
    qui disparaît du suivi sans un mot (filet de grâce), et l'arrêt volontaire
    (veille, extinction)."""

    result = run_node(tmp_path, FIXTURE + """
      const scenario=(how)=>{
        const world=makeWorld({win:{box:{x:0,y:0,w:64,h:40},representation:'window'}});
        const e=engineOf({world:world.api});
        const target=[tgt(1,'win','edge','right')];
        e.update({now:0,tokens:[tok(1,400,300)],targets:target,
          events:[ev(1,'down',400,300)],contacts:[held(1,'undecided')]});
        for(let k=1;k<=3;k+=1)
          e.update({now:16*k,tokens:[tok(1,400+60*k,300)],targets:target,
            events:[],contacts:[held(1,'drag')]});
        let last=null;
        if(how==='channel')
          last=e.update({now:64,tokens:[tok(1,580,300)],targets:target,
            events:[ev(1,'cancel')],contacts:[]});
        else if(how==='vanished'){
          /* La main disparaît : le filet compte la grâce contre l'observation. */
          for(let k=1;k<=40;k+=1)
            last=e.update({now:64+50*k,tokens:[],targets:[],events:[],contacts:[]});
        }else last={interactions:e.cancelAll(64)};
        return {commits:world.log.commits.length,cancels:world.log.cancels,
          types:last.interactions.map(i=>i.type),captures:e.capturedHands()};
      };
      out({channel:scenario('channel'),vanished:scenario('vanished'),stopped:scenario('stop')});
    """)
    for how in ("channel", "vanished", "stopped"):
        assert result[how]["commits"] == 0, f"{how} : une annulation a validé une géométrie"
        assert result[how]["cancels"] == ["win"], f"{how} : le cadre n'est pas revenu"
        assert result[how]["captures"] == []
        # Et surtout : aucune action, ni clic, ni sélection.
        assert "click" not in result[how]["types"] and "select" not in result[how]["types"]


def test_body_content_is_dispatched_by_the_semantics_of_the_target(tmp_path):
    """**Décision 8**, sa moitié contenu. Ce qu'une capture de corps fait se lit
    sur la **sémantique** de la cible, pas sur le pixel qu'elle occupe : un champ
    se sélectionne, une zone qui défile défile, le reste se traîne. Et le canal
    secondaire est un **doigt**, pas une durée (décision 22) : son relâchement
    est un clic droit, qu'il ait glissé ou non.

    Le `pointerId` de chaque événement vient de la fente de la main : deux mains
    ne parlent plus sous une identité unique (constat F2)."""

    result = run_node(tmp_path, FIXTURE + """
      const run=(kind,channel,scrollable)=>{
        const dom=makeDom(scrollable?[kind]:[]);
        const e=engineOf({dom:dom.api,slotOf:id=>Number(id)-1});
        const target=Object.assign(tgt(1,null,'body',null),{kind,representation:null,channel});
        const step=(k,x,events,contacts)=>e.update({now:16*k,tokens:[tok(1,x,300)],
          targets:[target],events:events||[],contacts:contacts||[]});
        step(0,400,[Object.assign(ev(1,'down',400,300),{channel})],
          [{handTrackId:1,channel,state:'pressed',intent:'undecided'}]);
        for(let k=1;k<=2;k+=1)
          step(k,400+40*k,[],[{handTrackId:1,channel,state:'pressed',intent:'drag'}]);
        const last=e.update({now:64,tokens:[tok(1,480,300)],targets:[],
          events:[Object.assign(ev(1,'up',480,300),{channel})],contacts:[]});
        return {dom:dom.log.map(d=>[d.type,d.dx,d.dy,d.pointerId,d.cancelled]),
          semantics:last.interactions.map(i=>i.type)};
      };
      out({
        button:run('button','primary',false),
        field:run('field','primary',false),
        scroller:run('card','primary',true),
        rightClick:run('button','secondary',false),
        cancelled:(()=>{
          const dom=makeDom([]);
          const e=engineOf({dom:dom.api});
          const target=Object.assign(tgt(1,null,'body',null),{kind:'button',representation:null});
          e.update({now:0,tokens:[tok(1,400,300)],targets:[target],
            events:[ev(1,'down',400,300)],contacts:[held(1,'undecided')]});
          e.update({now:16,tokens:[tok(1,440,300)],targets:[target],events:[],contacts:[held(1,'drag')]});
          e.update({now:32,tokens:[tok(1,480,300)],targets:[target],events:[ev(1,'cancel')],contacts:[]});
          return dom.log.map(d=>[d.type,d.cancelled]);
        })(),
        pointerRange:C.isBareHandsPointerId(C.pointerIdForSlot(0)),
      });
    """)
    assert [row[0] for row in result["button"]["dom"]] == ["drag_start", "drag_move", "drag_end"]
    assert result["button"]["semantics"] == ["drag_end"]
    assert result["button"]["dom"][0][3] == 9001, "la fente 0 garde le pointeur historique"
    # Un champ se sélectionne : aucune séquence de glissement, un `select` à la fin.
    assert [row[0] for row in result["field"]["dom"]] == ["select"]
    assert result["field"]["semantics"] == ["select"]
    # Une zone qui défile porte son déplacement, en pixels de la fenêtre —
    # à partir de l'image qui suit la prise, comme un glissement.
    assert [row[0] for row in result["scroller"]["dom"]] == ["scroll"]
    assert [row[1] for row in result["scroller"]["dom"]] == [40]
    # Clic droit : un contexte au relâchement, et rien traîné entre-temps.
    assert [row[0] for row in result["rightClick"]["dom"]] == ["context"]
    assert result["rightClick"]["semantics"] == ["context"]
    # Une annulation ferme le glissement sans le relâcher.
    assert result["cancelled"] == [["drag_start", False], ["drag_end", True]]
    assert result["pointerRange"] is True


def test_the_engine_refuses_to_be_built_without_the_rules_it_must_not_rewrite(tmp_path):
    """Le bloc pur ne peut pas lire les contrats (node le charge seul) : la
    règle des couples et la géométrie lui sont **injectées**, comme `pickRegion`
    l'est au résolveur de la Slice 05. Construit sans elles, il se refuse plutôt
    que d'en écrire une seconde copie — c'est exactement la duplication que le
    module de contrat existe pour éviter."""

    result = run_node(tmp_path, FIXTURE + """
      const partial=(drop)=>{const c=Object.assign({},C);delete c[drop];return c};
      out({
        nothing:refused(()=>B.createInteractionEngine()),
        noContracts:refused(()=>B.createInteractionEngine({geometry:G})),
        noCombine:refused(()=>B.createInteractionEngine({contracts:partial('combineCaptures'),geometry:G})),
        noSides:refused(()=>B.createInteractionEngine({contracts:partial('SIDE_AXIS'),geometry:G})),
        noZoneSides:refused(()=>B.createInteractionEngine({contracts:partial('zoneSides'),geometry:G})),
        noGeometry:refused(()=>B.createInteractionEngine({contracts:C})),
        halfGeometry:refused(()=>B.createInteractionEngine({contracts:C,
          geometry:{manipulateBox(){},resizable(){},sameBox(){}}})),
        built:!!B.createInteractionEngine({contracts:C,geometry:G}),
        /* Et le moteur n'a pas sa propre table des côtés. Le garde ne cherche
           plus le **nom** `SIDE_AXIS` — une table renommée `AXIS_OF`, ou
           écrite sans `Object.freeze`, passait tranquillement : il cherche la
           **forme**, c'est-à-dire un côté de cadre associé à un axe, qui est
           tout ce qu'une seconde copie pourrait être. */
        source:!/\\b(left|right|top|bottom)\\b\\s*:\\s*['"]?[xy]['"]?/.test(require('fs')
          .readFileSync(SCRIPT_PATH,'utf8').split('Moteur d’interaction et captures')[1]||''),
      });
    """)
    for case in ("nothing", "noContracts", "noCombine", "noSides", "noZoneSides",
                 "noGeometry", "halfGeometry"):
        assert result[case] == "RangeError", case
    assert result["built"] is True
    assert result["source"] is True, "le moteur a redérivé la table des côtés"


# ------------------------------------------------ suspension et reprise


#: Les cinq façons dont une manipulation **saute un tour** alors que son plan
#: survit. Chacune laissait la course de la main s'accumuler pour l'appliquer
#: d'un coup à la reprise.
SUSPENSIONS = ("same_zone", "neutralized", "not_resizable", "viewport", "lost")


def test_a_plan_that_skipped_a_frame_is_rebased_when_it_resumes(tmp_path):
    """**Décision 19, et son second déclencheur.** La signature dit *qui tient
    quoi* : elle attrape une main qui entre, une main qui se retire, un axe
    neutralisé, une main re-détectée sous une **autre** identité. Elle ne peut
    pas dire « ce plan n'a pas tourné à l'image précédente ».

    Or un plan survit à cinq suspensions au moins — la même zone prise deux fois
    (décision 15), les axes tous neutralisés, une forme qui ne se redimensionne
    pas, une fenêtre de scène non mesurable, et surtout **une main que le suivi
    perd le temps d'un clignement puis retrouve au même identifiant**, ailleurs.
    Pendant ce temps la main continue de voyager ; sans rebasage à la reprise,
    tout ce voyage s'appliquait en une image, et le cadre se posait là où il
    tombait.

    Le test mesure donc l'image de la **reprise** : elle doit être exactement la
    dernière image conduite, comme le test de la décision 19 mesure l'image de
    la transition."""

    result = run_node(tmp_path, FIXTURE + """
      const run=(how)=>{
        const shape=how==='not_resizable'?'point':'window';
        const world=makeWorld({win:{box:shape==='point'?{x:0,y:0,w:6,h:6}:{x:0,y:0,w:64,h:40},
          representation:shape}});
        let vp={scale:6};
        world.api.viewport=()=>vp;
        const neutral={mode:null,axes:[],byHand:{},reason:'axes_all_neutralized'};
        const contracts=how==='neutralized'
          ?Object.assign({},C,{combineCaptures:(a,b)=>b?neutral:C.combineCaptures(a,b)})
          :C;
        const e=B.createInteractionEngine({contracts,geometry:G,world:world.api});
        const solo=[tgt(1,'win','edge','right')];
        const pair=[solo[0],tgt(2,'win','edge',how==='same_zone'?'right':'left')];
        const seen=[];
        const frame=(now,tokens,targets,events,contacts)=>{
          const step=e.update({now,tokens,targets,events:events||[],contacts:contacts||[]});
          seen.push({previews:world.log.previews.length,
            box:world.log.previews.length?boxes(world.log).pop():null,
            refusals:step.refusals.map(r=>r.reason)});
        };
        /* Une main tient le bord droit et déplace le cadre de 60 px = 10 unités. */
        frame(0,[tok(1,400,300)],solo,[ev(1,'down',400,300)],[held(1,'undecided')]);
        frame(16,[tok(1,460,300)],solo,[],[held(1,'drag')]);
        frame(32,[tok(1,520,300)],solo,[],[held(1,'drag')]);
        const driven=seen[seen.length-1];
        /* Puis la suspension, pendant que la main voyage de 360 px — 60 unités,
           un cinquième de la zone sûre. */
        const away=[700,880];
        if(how==='lost'){
          for(const k of [0,1,2])frame(48+16*k,[],[],[],[]);
        }else if(how==='viewport'){
          vp=null;
          frame(48,[tok(1,700,300)],solo,[],[held(1,'drag')]);
          frame(64,[tok(1,880,300)],solo,[],[held(1,'drag')]);
          frame(80,[tok(1,880,300)],solo,[],[held(1,'drag')]);
        }else{
          frame(48,[tok(1,520,300),tok(2,530,300)],pair,
            [ev(2,'down',530,300)],[held(1,'drag'),held(2,'undecided')]);
          for(const k of [0,1])frame(64+16*k,[tok(1,away[k],300),tok(2,530,300)],pair,
            [],[held(1,'drag'),held(2,'drag')]);
        }
        const suspended=seen[seen.length-1];
        /* La reprise, **sans que la main ne bouge** : l'image doit être la même. */
        if(how==='lost')frame(96,[tok(1,880,300)],solo,[],[held(1,'drag')]);
        else if(how==='viewport'){vp={scale:6};frame(96,[tok(1,880,300)],solo,[],[held(1,'drag')])}
        else frame(96,[tok(1,880,300),tok(2,530,300)],solo,
          [ev(2,'up',530,300)],[held(1,'drag')]);
        const resumed=seen[seen.length-1];
        /* Et elle repart de là où elle est : 60 px de plus, 10 unités de plus. */
        frame(112,[tok(1,940,300)],solo,[],[held(1,'drag')]);
        const after=seen[seen.length-1];
        return {driven:driven.box,duringRefusals:suspended.refusals,
          frozen:suspended.previews===driven.previews,
          resumed:resumed.box,quiet:resumed.previews===driven.previews,
          after:after.box};
      };
      const all={};
      for(const how of ['same_zone','neutralized','not_resizable','viewport','lost'])all[how]=run(how);
      out(all);
    """)
    reasons = {"same_zone": ["same_zone_rejected"], "neutralized": ["axes_all_neutralized"],
               "not_resizable": ["frame_not_resizable"], "viewport": ["viewport_unavailable"],
               # Un clignement du suivi n'est pas un refus : il ne dure qu'une
               # image ou deux, et une ligne qui clignote à l'écran dirait moins
               # que le jeton de main qui disparaît déjà.
               "lost": []}
    for how in SUSPENSIONS:
        case = result[how]
        size = [6, 6] if how == "not_resizable" else [64, 40]
        assert case["driven"] == [20, 0] + size, (how, case["driven"])
        assert case["duringRefusals"] == reasons[how], (how, case["duringRefusals"])
        assert case["frozen"] is True, f"{how} : le cadre a bougé pendant la suspension"
        # L'image de la reprise est **identique** : rien n'a été publié, donc
        # rien n'a sauté.
        assert case["resumed"] == case["driven"], f"{how} : le cadre a sauté à la reprise"
        assert case["quiet"] is True, f"{how} : la reprise a publié un aperçu"
        # Puis la suite repart d'où la main est, pas d'où elle était.
        assert case["after"] == [30, 0] + size, (how, case["after"])


def test_a_hand_lost_for_a_blink_freezes_the_frame_instead_of_teleporting_it(tmp_path):
    """La suspension la plus banale, et la seule que l'utilisateur rencontre
    vraiment : la caméra cligne au milieu d'un glissement. La capture survit
    (`lostGraceMs`), la main revient **sous le même identifiant de piste** —
    donc la signature ne change pas — mais 440 px plus loin.

    Sans le second déclencheur, ces 440 px devenaient 68 unités en une image. Ce
    test les mesure en unités de scène pour que le chiffre reste lisible."""

    result = run_node(tmp_path, FIXTURE + """
      const world=makeWorld({win:{box:{x:0,y:0,w:64,h:40},representation:'window'}});
      const e=engineOf({world:world.api});
      const solo=[tgt(1,'win','edge','right')];
      e.update({now:0,tokens:[tok(1,400,300)],targets:solo,
        events:[ev(1,'down',400,300)],contacts:[held(1,'undecided')]});
      e.update({now:16,tokens:[tok(1,460,300)],targets:solo,events:[],contacts:[held(1,'drag')]});
      const plansBefore=e.plans().map(p=>p.signature);
      /* Ce que l'armement a publié — le rattrapage du seuil, 60 px — et qui
         n'a rien à voir avec la reprise : c'est **cette** marque qui ne doit
         plus bouger. */
      const previewsBefore=world.log.previews.length;
      /* Trois images sans main, puis la même piste, 440 px plus loin. */
      for(const k of [0,1,2])e.update({now:32+16*k,tokens:[],targets:[],events:[],contacts:[]});
      const alive=e.capturedHands();
      const back=e.update({now:80,tokens:[tok(1,900,300)],targets:solo,
        events:[],contacts:[held(1,'drag')]});
      const plansAfter=e.plans().map(p=>p.signature);
      out({plansBefore,alive,plansAfter,previewsBefore,
        previews:world.log.previews.length,
        refusals:back.refusals.map(r=>r.reason),
        types:back.interactions.map(i=>i.type)});
    """)
    # La capture a survécu au clignement, et la signature est restée la même :
    # c'est précisément ce qu'elle ne peut pas voir.
    assert result["alive"] == [1]
    assert result["plansAfter"] == result["plansBefore"] == ["move|xy|1:right"]
    # Rien n'a été publié à la reprise : ni aperçu, ni déplacement, ni refus.
    assert result["previews"] == result["previewsBefore"], "le cadre a téléporté de 68 unités"
    assert result["types"] == [] and result["refusals"] == []


def test_a_one_frame_dropout_during_a_two_hand_resize_says_nothing_and_moves_nothing(tmp_path):
    """Une image sans l'une des deux mains n'est pas un geste : c'est un trou du
    suivi. Le cadre ne bouge donc **pas du tout** pendant ce trou — ni de
    travers, ce qu'il faisait quand le côté de la main absente servait encore
    d'ancre, ni en publiant pour une main qui n'a pas de paume, ce qui posait
    `barehands_interaction_invalid` à l'écran, mot pour mot.

    RÈGLE ZÉRO, dans l'autre sens : un code interne affiché à l'utilisateur ne
    dit rien de ce qui se passe. Ici il n'y a rien à dire — la main revient à
    l'image suivante — et le silence est la bonne réponse, à condition que rien
    ne bouge pendant ce temps."""

    result = run_node(tmp_path, FIXTURE + """
      const world=makeWorld({win:{box:{x:-32,y:-20,w:64,h:40},representation:'window'}});
      const dom=makeDom([]);
      const e=engineOf({world:world.api,dom:dom.api});
      const targets=[tgt(1,'win','edge','left'),tgt(2,'win','edge','right')];
      const both=[held(1,'drag'),held(2,'drag')];
      e.update({now:0,tokens:[tok(1,400,300),tok(2,900,300)],targets,
        events:[ev(1,'down',400,300),ev(2,'down',900,300)],
        contacts:[held(1,'undecided'),held(2,'undecided')]});
      e.update({now:16,tokens:[tok(1,340,300),tok(2,960,300)],targets,events:[],contacts:both});
      e.update({now:32,tokens:[tok(1,280,300),tok(2,1020,300)],targets,events:[],contacts:both});
      const widened=boxes(world.log).pop();
      const previews=world.log.previews.length;
      /* La main 2 manque une image. La main 1, elle, continue de voyager. */
      const blink=e.update({now:48,tokens:[tok(1,220,300)],targets,events:[],contacts:both});
      const during=world.log.previews.length===previews?widened:boxes(world.log).pop();
      /* Elle revient là où elle serait allée : le cadre reprend **de là**. */
      const resume=e.update({now:64,tokens:[tok(1,220,300),tok(2,1080,300)],targets,
        events:[],contacts:both});
      const resumed=world.log.previews.length===previews?widened:boxes(world.log).pop();
      e.update({now:80,tokens:[tok(1,160,300),tok(2,1140,300)],targets,events:[],contacts:both});
      out({widened,during,resumed,after:boxes(world.log).pop(),
        blinkRefusals:blink.refusals.map(r=>r.reason),
        resumeRefusals:resume.refusals.map(r=>r.reason),
        blinkTypes:blink.interactions.map(i=>i.type),
        dom:[...new Set(dom.log.map(d=>d.type))]});
    """)
    assert result["widened"] == [-52, -20, 104, 40]
    # Rien pendant le trou : pas de redimensionnement de travers, pas d'événement.
    assert result["during"] == result["widened"], "le cadre s'est redimensionné de travers"
    assert result["blinkTypes"] == []
    # Et surtout : pas un code interne à l'écran.
    assert result["blinkRefusals"] == [], result["blinkRefusals"]
    assert "barehands_interaction_invalid" not in result["blinkRefusals"]
    # La reprise ne saute pas, puis les deux mains écartent de nouveau.
    assert result["resumed"] == result["widened"], "le cadre a sauté au retour de la main"
    assert result["resumeRefusals"] == []
    assert result["after"] == [-62, -20, 124, 40], result["after"]
    assert result["dom"] == ["resize"]


def test_a_scene_that_cannot_be_measured_refuses_instead_of_moving_six_times_too_far(tmp_path):
    """La fenêtre de la scène est ce qui convertit les pixels en unités (~6 px
    par unité en 1080p). Absente, `pxToUnits` retombait à 1:1 **en silence** :
    60 px de paume devenaient 60 unités au lieu de 10, un cinquième de la zone
    sûre pour un geste de trois centimètres.

    Un repli silencieux sur une mauvaise échelle est pire qu'un refus : le geste
    part six fois trop loin et l'utilisateur ne sait pas pourquoi."""

    result = run_node(tmp_path, FIXTURE + """
      const run=(viewport)=>{
        const world=makeWorld({win:{box:{x:0,y:0,w:64,h:40},representation:'window'}});
        world.api.viewport=viewport;
        const e=engineOf({world:world.api});
        const solo=[tgt(1,'win','edge','right')];
        e.update({now:0,tokens:[tok(1,400,300)],targets:solo,
          events:[ev(1,'down',400,300)],contacts:[held(1,'undecided')]});
        e.update({now:16,tokens:[tok(1,460,300)],targets:solo,events:[],contacts:[held(1,'drag')]});
        const step=e.update({now:32,tokens:[tok(1,520,300)],targets:solo,events:[],contacts:[held(1,'drag')]});
        e.update({now:48,tokens:[],targets:[],events:[ev(1,'up',520,300)],contacts:[]});
        return {refusals:step.refusals.map(r=>r.reason),
          box:world.log.previews.length?boxes(world.log).pop():null,
          commits:world.log.commits.length};
      };
      out({good:run(()=>({scale:6})),
        missing:run(()=>null),
        zero:run(()=>({scale:0})),
        absent:run(undefined)});
    """)
    assert result["good"]["box"] == [20, 0, 64, 40] and result["good"]["refusals"] == []
    for how in ("missing", "zero", "absent"):
        assert result[how]["refusals"] == ["viewport_unavailable"], how
        assert result[how]["box"] is None, f"{how} : le cadre a bougé sans échelle"
        assert result[how]["commits"] == 0, f"{how} : une géométrie fausse est partie à Core"
    # Un monde qui **lance** n'est pas un cas de ce moteur : la page enveloppe
    # chaque appel de scène (`sceneCall`) et rend `null` — qui tombe dans le
    # refus ci-dessus, par le même chemin.


def test_two_hands_on_a_move_only_star_let_the_first_one_keep_moving_it(tmp_path):
    """**Décision 8 contre décision D3**, et le cas que la décision 8 seule
    laissait muet. Deux corps ne déplacent pas une fenêtre : chaque main y fait
    son interaction de contenu, plus bas. Sur une étoile `point` ou `signal`, ce
    raisonnement tombe — son corps n'est pas du contenu, c'est sa **seule**
    prise, et la boucle de contenu la saute elle aussi. Le résultat était un
    cadre figé, aucune interaction, et **aucun refus** : l'étoile qu'une main
    traînait s'arrêtait net, sans un mot.

    Ce qui est décidé ici : la **première** main (la plus ancienne à la
    descente) continue de déplacer l'étoile, et la seconde se dit à l'écran.
    Une étoile `point` fait six unités ; deux mains dessus, c'est presque
    toujours la seconde qui arrive par accident sur un geste en cours — et
    « l'attraper à deux mains et tirer » est la première chose qu'on essaie sur
    une forme dont on vient d'apprendre qu'elle ne se redimensionne pas. Geler
    le geste en cours punirait la main qui avait raison ; le refus, lui,
    explique."""

    result = run_node(tmp_path, FIXTURE + """
      const world=makeWorld({star:{box:{x:0,y:0,w:6,h:6},representation:'point'}});
      const dom=makeDom([]);
      const e=engineOf({world:world.api,dom:dom.api});
      const body=(id)=>Object.assign(tgt(id,'star','body',null),{representation:'point'});
      const solo=[body(1)];
      const pair=[body(1),body(2)];
      e.update({now:0,tokens:[tok(1,400,300)],targets:solo,
        events:[ev(1,'down',400,300)],contacts:[held(1,'undecided')]});
      e.update({now:16,tokens:[tok(1,460,300)],targets:solo,events:[],contacts:[held(1,'drag')]});
      e.update({now:32,tokens:[tok(1,520,300)],targets:solo,events:[],contacts:[held(1,'drag')]});
      const alone=boxes(world.log).pop();
      /* La seconde main se pose sur la même étoile. */
      const joined=e.update({now:48,tokens:[tok(1,520,300),tok(2,524,304)],targets:pair,
        events:[ev(2,'down',524,304)],contacts:[held(1,'drag'),held(2,'undecided')]});
      /* La première continue de tirer ; la seconde ne tire rien. */
      const held2=e.update({now:64,tokens:[tok(1,580,300),tok(2,524,304)],targets:pair,
        events:[],contacts:[held(1,'drag'),held(2,'drag')]});
      const together=boxes(world.log).pop();
      const release=e.update({now:80,tokens:[tok(1,580,300),tok(2,524,304)],targets:pair,
        events:[ev(2,'up',524,304)],contacts:[held(1,'drag')]});
      const afterRelease=boxes(world.log).pop();
      e.update({now:96,tokens:[tok(1,640,300)],targets:solo,events:[],contacts:[held(1,'drag')]});
      const last=boxes(world.log).pop();
      e.update({now:112,tokens:[],targets:[],events:[ev(1,'up',640,300)],contacts:[]});
      out({alone,together,afterRelease,last,
        joinedRefusals:joined.refusals.map(r=>[r.handTrackId,r.reason]),
        heldRefusals:held2.refusals.map(r=>r.reason),
        releaseTypes:release.interactions.map(i=>i.type),
        moves:[...new Set(held2.interactions.map(i=>i.type))],
        dom:[...new Set(dom.log.map(d=>d.type))],
        commits:world.log.commits.map(c=>[c.mode,c.box.x,c.box.y])});
    """)
    assert result["alone"] == [20, 0, 6, 6]
    # La seconde main se dit, et **à chaque image** du maintien — pas seulement
    # à celle où elle arrive.
    assert result["joinedRefusals"] == [[2, "star_moves_with_one_hand"]], result["joinedRefusals"]
    assert result["heldRefusals"] == ["star_moves_with_one_hand"]
    # Pendant ce temps la première main continue : 60 px de plus, 10 unités.
    assert result["together"] == [30, 0, 6, 6], result["together"]
    assert result["moves"] == ["move"]
    # Le corps d'une étoile n'est jamais du contenu : le double journalise tout
    # ce qui se publie, et il n'y a là aucune séquence de contenu — la page, elle,
    # ne dispatche rien pour un `move` ni pour un `click`.
    assert result["dom"] == ["move"], result["dom"]
    assert not ({"drag_start", "drag_move", "drag_end", "scroll", "select"} & set(result["dom"]))
    # Au retrait de la seconde main, le cadre ne saute pas — et la seconde main
    # ayant **glissé** (son contact est passé en `drag`), son relâchement n'est
    # pas un clic : sur une étoile déjà sélectionnée, il ouvrirait son menu.
    assert result["afterRelease"] == result["together"], "l'étoile a sauté au retrait"
    assert result["releaseTypes"] == []
    assert result["last"] == [40, 0, 6, 6]
    assert result["commits"] == [["move", 40, 0]]


def test_a_disabled_target_never_opens_a_capture(tmp_path):
    """**Décision 3, en profondeur.** Le résolveur de la Slice 05 est la porte :
    il ne publie plus rien de non actionnable. Ce refus-ci est donc
    inatteignable par le chemin réel — il existe parce que le moteur est
    **injectable**, et que rien ne garantit que son prochain appelant sera ce
    résolveur-là. Sans lui, un contrôle désactivé recevrait une vraie séquence
    `pointerdown`/`pointermove`/`pointerup`, et un champ `inert` prendrait le
    focus.

    L'absence du champ reste crue, elle : « personne n'a rien dit » n'est pas
    « non »."""

    result = run_node(tmp_path, FIXTURE + """
      const run=(actionable)=>{
        const dom=makeDom([]);
        const e=engineOf({dom:dom.api});
        const target=Object.assign(tgt(1,null,'body',null),
          {kind:'button',representation:null,actionable});
        const step=e.update({now:0,tokens:[tok(1,400,300)],targets:[target],
          events:[ev(1,'down',400,300)],contacts:[held(1,'undecided')]});
        e.update({now:16,tokens:[tok(1,440,300)],targets:[target],events:[],contacts:[held(1,'drag')]});
        e.update({now:32,tokens:[tok(1,480,300)],targets:[target],events:[],contacts:[held(1,'drag')]});
        const up=e.update({now:48,tokens:[tok(1,480,300)],targets:[],
          events:[ev(1,'up',480,300)],contacts:[]});
        return {refusals:step.refusals.map(r=>r.reason),captures:step.captures,
          dom:dom.log.map(d=>d.type),types:up.interactions.map(i=>i.type)};
      };
      out({disabled:run(false),actionable:run(true),unsaid:run(undefined)});
    """)
    assert result["disabled"]["refusals"] == ["target_not_actionable"]
    assert result["disabled"]["captures"] == [] and result["disabled"]["dom"] == []
    assert result["disabled"]["types"] == [], "un contrôle désactivé a été cliqué"
    for how in ("actionable", "unsaid"):
        assert result[how]["refusals"] == [], how
        assert result[how]["dom"] == ["drag_start", "drag_move", "drag_end"], how


def test_two_hands_on_the_same_side_refuse_instead_of_ending_the_session(tmp_path):
    """L'invariant que `combineCaptures` garantit (décisions 16 et 17, vérifié
    sur les 64 couples de zones) était gardé ici par une **erreur lancée hors de
    la boucle d'images** : le contrat qui dérive un jour aurait fini la session
    de suivi, au lieu de sauter une image.

    C'est exactement la règle que `publish` suit cent soixante-dix lignes plus
    haut, et que cette tâche a déjà dû réparer trois fois : un refus codé dans
    une boucle d'images se dit et se saute."""

    result = run_node(tmp_path, FIXTURE + """
      const world=makeWorld({win:{box:{x:0,y:0,w:64,h:40},representation:'window'}});
      const broken={mode:'resize',axes:['x'],byHand:{
        1:{sides:['right'],axes:['x']},2:{sides:['right'],axes:['x']}},reason:null};
      const contracts=Object.assign({},C,{combineCaptures:(a,b)=>b?broken:C.combineCaptures(a,b)});
      const e=B.createInteractionEngine({contracts,geometry:G,world:world.api});
      const targets=[tgt(1,'win','edge','right'),tgt(2,'win','edge','left')];
      const both=[held(1,'drag'),held(2,'drag')];
      e.update({now:0,tokens:[tok(1,900,300),tok(2,400,300)],targets,
        events:[ev(1,'down',900,300),ev(2,'down',400,300)],
        contacts:[held(1,'undecided'),held(2,'undecided')]});
      const thrown=refused(()=>e.update({now:16,tokens:[tok(1,960,300),tok(2,340,300)],
        targets,events:[],contacts:both}));
      const step=e.update({now:32,tokens:[tok(1,1020,300),tok(2,280,300)],
        targets,events:[],contacts:both});
      out({thrown,refusals:step.refusals.map(r=>r.reason),
        previews:world.log.previews.length,alive:e.capturedHands().sort()});
    """)
    assert result["thrown"] is None, "le moteur a terminé la session sur un contrat dérivé"
    assert result["refusals"] == ["side_held_twice"]
    assert result["previews"] == 0
    # Et le suivi continue : les deux captures sont encore là.
    assert result["alive"] == [1, 2]


# ------------------------------------------------------ la chaîne entière


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
  lm[8]=at(FAN.index,o.index);lm[12]=at(FAN.middle,o.middle);
  lm[16]=at(FAN.ring,o.ring);lm[20]=at(FAN.pinky,o.pinky);
  const anchor=o.pinch==='index'?lm[8]:o.pinch==='middle'?lm[12]:null;
  lm[4]=anchor?{x:anchor.x+o.palm*o.gap,y:anchor.y,z:0}:at(o.thumbAngle,o.thumbReach);
  return lm;
}
const PINCHING=(t,o)=>hand(Object.assign({pinch:'index',index:1.85-.5*t,gap:.65-.5*t},o||{}));
"""


def test_two_real_hands_on_one_frame_resize_it_and_commit_one_geometry(tmp_path):
    """**Le test qui compte.** Tous les autres donnent les pixels, les contacts
    ou les cibles à la main. Celui-ci part de **points de main** et traverse
    toute la pile : traqueur et filtre (Slice 03), intention de pincement
    (Slice 04), résolveur de cible (Slice 05), moteur de captures et géométrie
    de scène (Slice 06), jusqu'à la commande envoyée.

    Ce qu'il attrape, et qu'aucun test de couche ne verrait : un **mélange
    d'espaces**. Un leurre exprimé en unités de scène (±160 × ±90) est dans les
    candidates et ne doit jamais gagner ; et la géométrie validée doit être en
    unités — des pixels passés tels quels donneraient une largeur bornée à la
    zone sûre au lieu d'une dizaine d'unités.

    Il attrape aussi ce qui traverse les couches sans être visible dans aucune :
    que les deux mains reçoivent deux identités et deux captures, que le côté
    tiré par chacune vienne du contrat, et que la **hauteur** ne change pas d'une
    unité quand seul l'axe x est tenu."""

    result = run_node(tmp_path, FIXTURE + HAND + """
      const VIEWPORT={width:1920,height:1080};
      const posOf=cx=>({cx,cy:.5});
      /* Les doigts se ferment sur les six premières images, puis les mains
         s'écartent. `toScreen` applique le **miroir** de la caméra frontale :
         deux `cx` qui se rapprochent s'écartent à l'écran. */
      const pose=i=>{
        const t=Math.min(1,i/6);
        const spread=Math.max(0,i-8)*.003;
        return [PINCHING(t,posOf(.36-spread)),PINCHING(t,posOf(.64+spread))];
      };
      const FRAMES=27;
      /* Première passe, sans cible : on **observe** où chaque main vise au
         moment où son contact se ferme, parce que le bout de l'index parcourt
         un demi-palme en se refermant (leçon des Slices 03 et 04) et qu'un
         cadre posé sur la position d'avant ne serait plus sous le doigt. */
      const measure=()=>{
        const tracker=B.createHandTracker({}),pinch=B.createPinchIntentEngine({});
        const seen=new Map();
        for(let i=0;i<FRAMES;i+=1){
          const lm=pose(i),now=i*16;
          const step=tracker.update({landmarks:lm},{viewport:VIEWPORT,aspect:16/9,now});
          const observed=step.tokens.map(token=>({handTrackId:token.id,
            landmarks:lm[step.trackIds.indexOf(token.id)],
            x:token.filteredX,y:token.filteredY,anchorX:token.x,anchorY:token.y,
            palmX:token.palmX,palmY:token.palmY,
            stillness:token.stillness,quality:token.quality}));
          for(const contact of pinch.update({hands:observed,now,aspect:16/9}).contacts){
            if(contact.channel!=='primary'||contact.state!=='pressed')continue;
            if(seen.has(String(contact.handTrackId)))continue;
            const token=step.tokens.find(t=>String(t.id)===String(contact.handTrackId));
            seen.set(String(contact.handTrackId),{x:token.x,y:token.y});
          }
        }
        return [...seen.values()].sort((a,b)=>a.x-b.x);
      };
      const aimed=measure();
      if(aimed.length!==2)throw new Error('les deux mains doivent descendre en contact');
      const leftAim=aimed[0],rightAim=aimed[1];
      const tracker=B.createHandTracker({}),pinch=B.createPinchIntentEngine({});
      const resolver=B.createTargetResolver({pickRegion:C.pickRegion});
      const world=makeWorld({win:{box:{x:-32,y:-20,w:64,h:40},representation:'window'}});
      const dom=makeDom([]);
      const engine=B.createInteractionEngine({contracts:C,geometry:G,
        world:world.api,dom:dom.api,slotOf:id=>Number(id),
        onRelease:(id,channel)=>resolver.release(id,channel)});

      /* Le cadre est posé pour que chaque index tombe **sur** un bord vertical,
         au milieu de la hauteur : chaque main tient donc un bord, et les deux
         bords sont opposés — un redimensionnement légitime sur le seul axe x. */
      const top=Math.min(leftAim.y,rightAim.y)-150;
      const frame={objectId:'win',kind:'scene_object',representation:'window',zoned:true,
        actionable:true,boundsPx:{x:leftAim.x,y:top,w:rightAim.x-leftAim.x,h:300}};
      /* Le leurre : la même chose exprimée en unités de scène. Il contient
         l'origine, donc il gagnerait si les jetons arrivaient normalisés. */
      const decoy={objectId:'unites-de-scene',kind:'scene_object',representation:'window',
        zoned:true,actionable:true,boundsPx:{x:-160,y:-90,w:320,h:180}};
      const candidates=[decoy,frame];
      candidates.forEach((c,i)=>{c.ref=i});

      const regions=new Set(),objects=new Set(),modes=new Set();
      let lastStep=null;
      const track=(i)=>{
        const lm=pose(i);
        const now=i*16;
        const step=tracker.update({landmarks:lm},{viewport:VIEWPORT,aspect:16/9,now});
        const observed=step.tokens.map(token=>({handTrackId:token.id,
          landmarks:lm[step.trackIds.indexOf(token.id)],
          x:token.filteredX,y:token.filteredY,anchorX:token.x,anchorY:token.y,
          palmX:token.palmX,palmY:token.palmY,
          stillness:token.stillness,quality:token.quality}));
        const out=pinch.update({hands:observed,now,aspect:16/9});
        const hands=out.contacts.filter(c=>c.channel==='primary').map(c=>{
          const token=step.tokens.find(t=>String(t.id)===String(c.handTrackId));
          return {handTrackId:c.handTrackId,channel:c.channel,state:c.state,x:token.x,y:token.y};
        });
        const targets=resolver.update({now,candidates,hands}).map(target=>Object.assign({},target,
          {feedback:C.feedbackRole(target.region,target.channel)}));
        /* Ce qui compte est la cible **figée** : c'est elle que la capture prend
           (décision 13). En approche, l'aperçu est dynamique et suit un index
           qui parcourt un demi-palme en se refermant. */
        for(const target of targets){
          if(!target.locked)continue;
          regions.add(`${target.region}:${target.zone||''}`);objects.add(target.objectId);
        }
        lastStep=engine.update({now,tokens:step.tokens,targets,
          contacts:out.contacts,events:out.events});
        for(const interaction of lastStep.interactions)modes.add(interaction.type);
        return {now,tokens:step.tokens};
      };
      let frameAt=null;
      for(let i=0;i<FRAMES;i+=1)frameAt=track(i);
      /* Relâchement des deux mains : la géométrie part à Core, une fois. */
      const lastNow=frameAt.now+16;
      engine.update({now:lastNow,tokens:frameAt.tokens,targets:[],
        contacts:[],events:[
          {handTrackId:frameAt.tokens[0].id,channel:'primary',phase:'up',x:frameAt.tokens[0].x,y:frameAt.tokens[0].y},
          {handTrackId:frameAt.tokens[1].id,channel:'primary',phase:'up',x:frameAt.tokens[1].x,y:frameAt.tokens[1].y}]});
      const commit=world.log.commits[0]||null;
      out({
        hands:aimed.length,
        identities:aimed.length,
        aims:[Math.round(leftAim.x),Math.round(rightAim.x)],
        inWindow:leftAim.x>0&&rightAim.x<VIEWPORT.width,
        regions:[...regions].sort(),objects:[...objects],
        interactions:[...modes].sort(),
        commits:world.log.commits.length,
        commit:commit?[commit.mode,commit.box.x,commit.box.y,commit.box.w,commit.box.h]:null,
        domEvents:dom.log.map(d=>d.type),
        safe:G.SAFE_AREA,
      });
    """)
    # Deux mains, deux identités, en pixels de la fenêtre.
    assert result["hands"] == 2 and result["identities"] == 2
    assert result["inWindow"] is True
    # Chaque main a tenu un bord vertical, et le leurre en unités de scène n'a
    # jamais gagné.
    assert result["objects"] == ["win"], result["objects"]
    assert set(result["regions"]) <= {"edge:left", "edge:right"}, result["regions"]
    assert {"edge:left", "edge:right"} == set(result["regions"])
    # Un redimensionnement, jamais un déplacement : deux zones compatibles.
    assert "resize" in result["interactions"]
    assert "move" not in result["interactions"]
    # Aucune sortie de pointeur : une manipulation de cadre n'est pas un
    # glissement de souris, et rien n'a été cliqué au passage.
    assert set(result["domEvents"]) == {"resize"}, result["domEvents"]
    # Une seule géométrie envoyée, en unités de scène, dans la zone sûre.
    assert result["commits"] == 1
    mode, x, y, w, h = result["commit"]
    assert mode == "resize"
    assert h == 40, "seul l'axe x était tenu : la hauteur ne doit pas changer"
    assert w > 64, "les mains se sont écartées"
    assert w < 140, "des pixels pris pour des unités auraient explosé la largeur"
    safe = result["safe"]
    assert safe["x0"] <= x and x + w <= safe["x1"]
    assert safe["y0"] <= y and y + h <= safe["y1"]


# ----------------------------------------------------------------- dans le DOM

#: Le même double de DOM que la Slice 05, augmenté de ce que la Slice 06
#: consomme : des événements dispatchés qu'on peut relire, et une scène qui
#: publie ses cadres manipulables.
#:
#: Et **augmenté de ce qui fait un élément** : `nodeType`, la chaîne des parents
#: par `parentElement`, les tailles de défilement, et un `getComputedStyle`
#: global. Sans elles, `scrollHost` sortait à la première itération, tout
#: élément était « ne défile pas », et les tests de cette page affirmaient une
#: sémantique de **glissement** pour des éléments que le produit traite en
#: **défilement** — le chemin réel de défilement n'était exécuté par aucun test.
#: Les valeurs suivent le rectangle, comme dans un vrai document : un élément
#: qui n'a pas plus de contenu que de boîte ne défile pas.
BROWSER = """
const registry=[];
const node=(opts)=>{
  const o=Object.assign({sel:[],rect:null,id:'',dataset:{},label:'',scroll:null},opts||{});
  const classes=new Set();
  const r=o.rect||{left:0,top:0,width:0,height:0};
  const s=o.scroll||null;
  const el={children:[],className:'',id:o.id,textContent:o.label,offsetWidth:1,
    sel:o.sel,dataset:o.dataset,attrs:{},parent:null,events:[],
    nodeType:1,
    clientWidth:r.width,clientHeight:r.height,
    scrollWidth:s&&s.width!==undefined?s.width:r.width,
    scrollHeight:s&&s.height!==undefined?s.height:r.height,
    scrollLeft:s&&s.left!==undefined?s.left:0,
    scrollTop:s&&s.top!==undefined?s.top:0,
    overflow:s?(s.overflow||'auto'):'visible',
    style:{setProperty(k,v){this[k]=v}},
    classList:{add:c=>classes.add(c),remove:c=>classes.delete(c),
      toggle:(c,on)=>{if(on)classes.add(c);else classes.delete(c)},
      contains:c=>classes.has(c)},
    classes,
    matches(sel){return String(sel).split(',').some(one=>el.sel.includes(one.trim()))},
    closest(sel){let cur=el;while(cur){if(cur.matches&&cur.matches(sel))return cur;cur=cur.parent}return null},
    getAttribute(k){return k==='aria-label'?(o.label||null):(el.attrs[k]===undefined?null:el.attrs[k])},
    setAttribute(k,v){el.attrs[k]=String(v)},
    getBoundingClientRect(){return o.rect||{left:0,top:0,width:0,height:0}},
    focus(){el.events.push({type:'focus'})},
    dispatchEvent(event){el.events.push(event);return true},
    appendChild(c){c.parent=el;el.children.push(c);return c},
    remove(){if(!el.parent)return;const at=el.parent.children.indexOf(el);
      if(at>=0)el.parent.children.splice(at,1);el.parent=null}};
  /* `parentElement`, et non `parent` : c'est le nom que remonte la chaîne des
     ancêtres dans un document, donc c'est celui que le produit lit. */
  Object.defineProperty(el,'parentElement',{get(){return el.parent}});
  registry.push(el);
  return el;
};
global.getComputedStyle=el=>({overflowY:(el&&el.overflow)||'visible',
  overflowX:(el&&el.overflow)||'visible'});
global.page=[];
global.window={addEventListener(){},innerWidth:1000,innerHeight:800};
global.document={createElement:()=>node(),
  getElementById:id=>registry.find(el=>el.id===id&&el.parent)||null,
  head:node(),body:node(),
  elementFromPoint:(x,y)=>global.page.filter(el=>{
    const r=el.getBoundingClientRect();
    return x>=r.left&&x<=r.left+r.width&&y>=r.top&&y<=r.top+r.height}).pop()||null,
  querySelectorAll:sel=>global.page.filter(el=>el.matches(sel))};
global.navigator={mediaDevices:null};
global.performance={now:()=>global.clock||0};
global.clock=0;
global.requestAnimationFrame=()=>0;global.cancelAnimationFrame=()=>{};
global.setTimeout=()=>0;
global.MouseEvent=class{constructor(type,init){Object.assign(this,init||{});this.type=type}};
global.PointerEvent=class{constructor(type,init){Object.assign(this,init||{});this.type=type}};
global.WheelEvent=class{constructor(type,init){Object.assign(this,init||{});this.type=type}};
global.JarvisBarehandsContracts=C;
global.window.JarvisBarehandsContracts=C;
global.JarvisBarehandsTarget=require(TARGET_PATH);
/* Parcours de calibration (Slice 08) : la page l'insere entre les contrats
   et le pointeur, qui le lit pour poser `calibrate()` sur sa surface gelee. */
global.JarvisBarehandsCalibration=require(CALIBRATION_PATH);
/* Slice 06 : la géométrie de la scène est insérée bien avant le pointeur. */
global.JarvisSceneInteract=G;
/* Et la scène publie ses cadres manipulables — la vraie couture est lue par
   `window.JarvisScene.frames`, à l'appel et non au chargement. */
const sceneLog={begins:[],previews:[],commits:[],cancels:[]};
const sceneObjects={};
global.window.JarvisScene={frames:{
  begin(id){sceneLog.begins.push(id);const o=sceneObjects[id];
    return o?{objectId:id,box:Object.assign({},o.box),representation:o.representation}:null},
  preview(id,box){sceneLog.previews.push({id,box:Object.assign({},box)})},
  commit(id,box,mode){sceneLog.commits.push({id,box:Object.assign({},box),mode})},
  cancel(id){sceneLog.cancels.push(id)},
  viewport(){return {scale:6}},
}};
delete require.cache[require.resolve(SCRIPT_PATH)];
require(SCRIPT_PATH);
const api=window.JarvisBarehands;
const overlay=api.adapters.overlay;
overlay.mount();
const interaction=api.adapters.interaction;
const root=()=>document.body.children[0];
const star=(id,rect,representation,label)=>node({sel:['.sc-node[data-object-id]'],rect,
  dataset:{objectId:id,representation},label:label||id});
const button=(rect,label)=>node({sel:['button'],rect,label:label||''});
/* Une carte : du contenu ordinaire, ni étoile ni champ — donc ce que la
   décision 8 laisse décider à l'élément lui-même. */
const card=(rect,scroll,label)=>node({sel:['.acard'],rect,scroll,label:label||'Carte'});
const token=(id,x,y,px,py)=>({id,x,y,palmX:px===undefined?x:px,palmY:py===undefined?y:py,
  progress:0,state:'pressed',click:false,hover:false,quality:1});
const contact=(id,state,intent,channel)=>({handTrackId:id,channel:channel||'primary',
  state,intent:intent||'undecided',ratio:.3,confidence:1});
const shot=(now,tokens,contacts,events)=>{
  global.clock=now;
  interaction.readContacts(()=>contacts||[]);
  interaction.readPinch(()=>events||[]);
  interaction.hover(tokens);
};
"""


def test_the_legacy_click_is_held_back_on_the_frame_the_hand_just_moved(tmp_path):
    """Le détecteur hérité (`createPinchDetector`, prouvé identique sur 336 000
    pas) rend un clic à **chaque** relâchement, glissement compris. Sans porte,
    tout déplacement à mains nues se terminait donc par un clic sur l'objet
    qu'on venait de poser — et, sur une étoile déjà sélectionnée, par
    l'ouverture de son menu.

    Ce qui est touché est la **livraison** du clic, pas sa mesure : le détecteur
    n'est pas modifié, et un contact qui n'a rien déplacé clique comme avant.

    Le test conduit le **vrai** bloc navigateur : la collecte lit l'arbre, la
    résolution fige la cible, le moteur ouvre la capture et la scène est tenue
    par sa vraie couture."""

    result = run_node(tmp_path, BROWSER + """
      const win=star('obj-1',{left:200,top:100,width:400,height:300},'window','Tâche A');
      global.page=[win];
      sceneObjects['obj-1']={box:{x:-32,y:-20,w:64,h:40},representation:'window'};
      /* Le doigt se pose sur le bord droit du cadre, à mi-hauteur. */
      const edge={x:600,y:250};
      shot(0,[token(1,edge.x,edge.y)],[contact(1,'pressed')],
        [{handTrackId:1,channel:'primary',phase:'down',x:edge.x,y:edge.y}]);
      const aimed=interaction.targets().map(t=>`${t.region}:${t.zone||''}`);
      const captured=interaction.captures();
      /* La main glisse : l'intention bascule, le cadre suit. */
      shot(16,[token(1,edge.x,edge.y,edge.x+60,edge.y)],[contact(1,'pressed','drag')],[]);
      shot(32,[token(1,edge.x,edge.y,edge.x+120,edge.y)],[contact(1,'pressed','drag')],[]);
      const duringDrag=interaction.click({id:1,x:edge.x,y:edge.y});
      /* Relâchement : la géométrie part, et le clic hérité de cette image-là
         est encore retenu. */
      shot(48,[token(1,edge.x,edge.y,edge.x+120,edge.y)],[],
        [{handTrackId:1,channel:'primary',phase:'up',x:edge.x,y:edge.y}]);
      const atRelease=interaction.click({id:1,x:edge.x,y:edge.y});
      const movedEvents=win.events.map(e=>e.type);
      /* Puis une main qui n'a rien tenu : le clic repart comme avant. */
      win.events.length=0;
      shot(200,[token(1,edge.x,edge.y)],[],[]);
      const afterwards=interaction.click({id:1,x:edge.x,y:edge.y});
      out({aimed,captured,duringDrag,atRelease,afterwards,
        movedEvents,plainEvents:win.events.map(e=>e.type),
        begins:sceneLog.begins,commits:sceneLog.commits.map(c=>[c.id,c.mode,c.box.w]),
        previews:sceneLog.previews.length});
    """)
    assert result["aimed"] == ["edge:right"], result["aimed"]
    assert result["captured"] == [1]
    # Pendant et à la fin du geste : aucun clic livré, aucun événement DOM.
    assert result["duringDrag"] is False and result["atRelease"] is False
    assert result["movedEvents"] == [], result["movedEvents"]
    # La scène a bien été tenue, et une seule géométrie est partie.
    assert result["begins"] == ["obj-1"]
    assert result["previews"] > 0
    assert [c[:2] for c in result["commits"]] == [["obj-1", "move"]]
    assert result["commits"][0][2] == 64, "une seule main ne redimensionne jamais"
    # Et le chemin hérité est intact pour qui n'a rien déplacé.
    assert result["afterwards"] is True
    assert result["plainEvents"] == [
        "pointerdown", "mousedown", "pointerup", "mouseup", "click",
    ]


def test_the_click_comes_from_the_intent_engine_on_release_at_the_aimed_point(tmp_path):
    """**Le clic DOM n'a plus qu'une source : le moteur d'intention.**

    Avant, le détecteur hérité cliquait à l'**entrée** du contact, sur le
    rapport brut — sans qualité de suivi, sans rejet du poing, sans marge entre
    canaux — et chaque prise commençait donc par un clic sur ce qu'elle
    saisissait. Désormais : rien à la descente, un seul clic au relâchement
    d'un contact qui n'a pas glissé, livré après l'image (`takeClicks`), et
    **au point visé à la descente** — au relâchement, le point filtré suit
    l'index qui se rouvre et peut être sorti du bouton. Un contact qui a glissé
    ne clique pas, et une extinction jette ce qui n'était pas encore livré."""

    result = run_node(tmp_path, BROWSER + """
      const b=button({left:100,top:100,width:120,height:40},'Activer');
      global.page=[b];
      const at={x:160,y:120};
      const own=()=>b.events.map(e=>e.type).filter(t=>!/over|out|enter|leave/.test(t));
      shot(0,[token(1,at.x,at.y)],[contact(1,'pressed')],
        [{handTrackId:1,channel:'primary',phase:'down',x:at.x,y:at.y}]);
      const atDown={dom:own(),queued:interaction.takeClicks()};
      shot(16,[token(1,at.x,at.y)],[contact(1,'pressed')],[]);
      /* Relâchement : le point filtré est parti à droite, hors du bouton. */
      shot(200,[token(1,at.x,at.y)],[],
        [{handTrackId:1,channel:'primary',phase:'up',x:at.x+100,y:at.y}]);
      const queued=interaction.takeClicks();
      const delivered=queued.map(c=>interaction.click(c));
      const clicked=own();
      const again=interaction.takeClicks();
      b.events.length=0;
      /* Un contact qui glisse : aucun clic, ni pendant ni au relâchement. */
      shot(300,[token(1,at.x,at.y)],[contact(1,'pressed')],
        [{handTrackId:1,channel:'primary',phase:'down',x:at.x,y:at.y}]);
      shot(316,[token(1,at.x+30,at.y,at.x+60,at.y)],[contact(1,'pressed','drag')],[]);
      shot(332,[token(1,at.x+30,at.y,at.x+60,at.y)],[],
        [{handTrackId:1,channel:'primary',phase:'up',x:at.x+30,y:at.y}]);
      const draggedClicks=interaction.takeClicks();
      const draggedDom=own();
      /* Un clic décidé mais pas encore livré ne survit pas à une extinction. */
      shot(400,[token(1,at.x,at.y)],[contact(1,'pressed')],
        [{handTrackId:1,channel:'primary',phase:'down',x:at.x,y:at.y}]);
      shot(500,[token(1,at.x,at.y)],[],
        [{handTrackId:1,channel:'primary',phase:'up',x:at.x,y:at.y}]);
      interaction.clear();
      out({atDown,queued,delivered,clicked,again,draggedClicks,draggedDom,
        afterClear:interaction.takeClicks()});
    """)
    assert result["atDown"] == {"dom": [], "queued": []}, "la descente ne clique plus"
    assert [(str(c["id"]), c["x"], c["y"]) for c in result["queued"]] == [("1", 160, 120)], (
        "le clic vise l'ancre de la descente")
    assert result["delivered"] == [True]
    # La séquence d'une souris, focus compris (un bouton se focalise).
    assert result["clicked"] == ["pointerdown", "mousedown", "focus", "pointerup", "mouseup", "click"]
    assert result["again"] == [], "un clic ne se livre qu'une fois"
    assert result["draggedClicks"] == []
    assert "click" not in result["draggedDom"]
    assert result["afterClear"] == []


def test_the_page_dispatches_compatibility_events_for_content_only(tmp_path):
    """Architecture § 7 : « ne pas encoder tout le comportement en `PointerEvent`
    synthétiques ». Les événements du DOM restent une sortie de
    **compatibilité** pour le contenu, là où la page écoute déjà une souris — et
    ils portent une identité de pointeur **par main** (constat F2), jamais le
    littéral d'hier."""

    result = run_node(tmp_path, BROWSER + """
      const b=button({left:100,top:100,width:120,height:40},'Activer');
      global.page=[b];
      const at={x:160,y:120};
      shot(0,[token(1,at.x,at.y)],[contact(1,'pressed')],
        [{handTrackId:1,channel:'primary',phase:'down',x:at.x,y:at.y}]);
      shot(16,[token(1,at.x+30,at.y,at.x+60,at.y)],[contact(1,'pressed','drag')],[]);
      shot(32,[token(1,at.x+60,at.y,at.x+120,at.y)],[contact(1,'pressed','drag')],[]);
      shot(48,[token(1,at.x+60,at.y,at.x+120,at.y)],[],
        [{handTrackId:1,channel:'primary',phase:'up',x:at.x+60,y:at.y}]);
      const dragged=b.events.map(e=>[e.type,e.pointerId,e.pointerType]);
      b.events.length=0;
      /* Clic droit : un `contextmenu`, bouton 2, et rien traîné. */
      shot(100,[token(1,at.x,at.y)],[contact(1,'pressed',undefined,'secondary')],
        [{handTrackId:1,channel:'secondary',phase:'down',x:at.x,y:at.y}]);
      shot(116,[token(1,at.x,at.y)],[],
        [{handTrackId:1,channel:'secondary',phase:'up',x:at.x,y:at.y}]);
      const context=b.events.map(e=>[e.type,e.button]);
      const contextTypes=api.interactions().map(i=>i.type);
      b.events.length=0;
      /* Perte de la main au milieu d'un glissement : `pointercancel`, **jamais**
         `pointerup`. Un relâchement déclencherait l'action que l'arrêt vient
         justement d'interrompre. */
      shot(200,[token(1,at.x,at.y)],[contact(1,'pressed')],
        [{handTrackId:1,channel:'primary',phase:'down',x:at.x,y:at.y}]);
      shot(216,[token(1,at.x+30,at.y,at.x+60,at.y)],[contact(1,'pressed','drag')],[]);
      shot(232,[token(1,at.x+60,at.y,at.x+120,at.y)],[],
        [{handTrackId:1,channel:'primary',phase:'cancel'}]);
      out({dragged,context,types:contextTypes,
        lost:b.events.map(e=>e.type),
        slotZero:C.pointerIdForSlot(0),
        scene:sceneLog.begins});
    """)
    # Le survol hérité (`pointerover`/`mouseover`) reste ce qu'il était : ce qui
    # nous appartient est la séquence de contact.
    kinds = [row[0] for row in result["dragged"] if "over" not in row[0] and "out" not in row[0]]
    assert kinds == ["pointerdown", "mousedown", "pointermove", "mousemove", "pointerup", "mouseup"]
    # Identité par main : une seule main ici, donc la fente 0 — dont le
    # pointeur **vaut** 9001, le littéral d'hier. Ce qui a changé n'est pas la
    # valeur, c'est qu'elle vienne de la fente : deux mains donnent deux
    # identités (voir le test qui les fait glisser ensemble).
    assert {row[1] for row in result["dragged"] if row[1] is not None} == {9001}
    assert result["slotZero"] == 9001
    # Le type de pointeur reste celui du contrat (`POINTER_TYPE`), qui se fait
    # passer pour une souris afin que la page d'aujourd'hui l'écoute.
    assert {row[2] for row in result["dragged"] if row[2]} == {"mouse"}
    assert result["context"] == [["contextmenu", 2]]
    assert result["types"] == ["context"]
    # Perte : une annulation, jamais un relâchement.
    lost = [kind for kind in result["lost"] if "over" not in kind and "out" not in kind]
    assert lost == ["pointerdown", "mousedown", "pointercancel"], lost
    assert "pointerup" not in lost and "click" not in lost
    # Un bouton n'est pas un cadre : la scène n'a jamais été sollicitée.
    assert result["scene"] == []


def test_a_scrollable_element_really_scrolls_and_never_drags(tmp_path):
    """**Décision 8**, sa moitié la plus fragile : le chemin de défilement
    **réel**, celui qui trouve l'ancêtre qui défile et qui déplace vraiment son
    contenu.

    Il n'était exécuté par aucun test, et le double de DOM ne pouvait pas
    l'atteindre : sans `nodeType`, sans `parentElement`, sans tailles de
    défilement et sans `getComputedStyle`, `scrollHost` sortait à la première
    itération et **tout** élément était « ne défile pas ». Les tests de cette
    page affirmaient donc une sémantique de glissement pour des éléments que le
    produit traite en défilement.

    Ce qui est épinglé maintenant : l'ancêtre **le plus proche** qui défile, le
    déplacement exact (la main tire le contenu), aucun double défilement, et
    aucune séquence de pointeur — un élément qui défile ne se traîne pas."""

    result = run_node(tmp_path, BROWSER + """
      const run=(how)=>{
        const room={ancestor:{height:900,width:1200,top:500,left:300},
          self:{height:900,width:1200,top:500,left:300},
          /* Une boîte qui ne déborde **que** de largeur : l'autre moitié du
             test de `scrollHost`, qu'aucun défilement vertical ne couvre. */
          wide:{width:1200,left:300},
          /* Déborde, mais ne défile pas : `overflow:hidden` est une boîte
             rognée, pas une zone de défilement. */
          hidden:{height:900,width:1200,top:500,left:300,overflow:'hidden'},
          none:null}[how];
        const panel=node({sel:[],rect:{left:100,top:100,width:400,height:300},scroll:room});
        const c=card({left:120,top:140,width:360,height:200},
          how==='self'?{height:800,width:1200,top:500,left:300}:null);
        panel.appendChild(c);
        global.page=[c];
        const at={x:300,y:240};
        shot(0,[token(1,at.x,at.y)],[contact(1,'pressed')],
          [{handTrackId:1,channel:'primary',phase:'down',x:at.x,y:at.y}]);
        const kind=interaction.targets().map(t=>t.kind);
        /* La main s'arme, puis tire de 20 px à droite et 30 px vers le bas. */
        shot(16,[token(1,at.x,at.y)],[contact(1,'pressed','drag')],[]);
        shot(32,[token(1,at.x+20,at.y+30)],[contact(1,'pressed','drag')],[]);
        const semantics=api.interactions().map(i=>[i.type,i.dx,i.dy]);
        shot(48,[token(1,at.x+20,at.y+30)],[],
          [{handTrackId:1,channel:'primary',phase:'up',x:at.x+20,y:at.y+30}]);
        const seq=el=>el.events.map(e=>e.type).filter(t=>t.indexOf('over')<0&&t.indexOf('out')<0);
        return {kind,semantics,
          panel:[panel.scrollTop,panel.scrollLeft],card:[c.scrollTop,c.scrollLeft],
          panelEvents:seq(panel),cardEvents:seq(c),
          wheel:[...panel.events,...c.events].filter(e=>e.type==='wheel')
            .map(e=>[e.deltaX,e.deltaY])};
      };
      out({ancestor:run('ancestor'),self:run('self'),wide:run('wide'),
        hidden:run('hidden'),none:run('none')});
    """)
    for how in ("ancestor", "self", "wide", "hidden", "none"):
        assert result[how]["kind"] == ["card"], (how, result[how]["kind"])
    # L'ancêtre qui défile prend le déplacement, **exactement** et sur les deux
    # axes : 500 → 470 et 300 → 280, parce que la main tire le contenu vers elle.
    assert result["ancestor"]["semantics"] == [["scroll", 20, 30]]
    assert result["ancestor"]["panel"] == [470, 280], result["ancestor"]["panel"]
    # Et l'élément lui-même n'a pas bougé : pas de double défilement.
    assert result["ancestor"]["card"] == [0, 0]
    assert result["ancestor"]["cardEvents"] == [], "un élément qui défile a été traîné"
    assert result["ancestor"]["wheel"] == [[-20, -30]]
    # Le plus proche gagne : quand l'élément défile lui-même, l'ancêtre ne bouge pas.
    assert result["self"]["card"] == [470, 280], result["self"]["card"]
    assert result["self"]["panel"] == [500, 300], "l'ancêtre a défilé en plus de l'élément"
    # Une boîte qui ne déborde que de **largeur** défile aussi : la hauteur n'est
    # pas ce qui décide.
    assert result["wide"]["semantics"] == [["scroll", 20, 30]]
    assert result["wide"]["panel"] == [-30, 280], result["wide"]["panel"]
    # Ce qui déborde ne défile pas pour autant : `overflow:hidden` est une boîte
    # rognée. La main la traîne, elle ne la fait pas défiler — et c'est le style
    # calculé qui le dit, pas la seule taille.
    assert result["hidden"]["semantics"] == [["drag_move", 0, 0]]
    assert result["hidden"]["panel"] == [500, 300], "une boîte rognée a défilé"
    assert result["hidden"]["cardEvents"][:2] == ["pointerdown", "mousedown"]
    # Et sans rien qui défile, c'est un glissement — la vraie séquence de pointeur.
    assert result["none"]["semantics"] == [["drag_move", 0, 0]]
    assert result["none"]["cardEvents"] == ["pointerdown", "mousedown", "pointermove",
                                            "mousemove", "pointerup", "mouseup"]
    assert result["none"]["wheel"] == []
    assert result["none"]["panel"] == [0, 0] and result["none"]["card"] == [0, 0]


def test_two_hands_speak_under_two_pointer_identities_through_the_dom(tmp_path):
    """Critère d'acceptation : « identité de pointeur unique et stable par
    main ». Le constat F2 était l'inverse — deux mains parlaient sous le même
    `9001`, et la page ne pouvait pas les distinguer.

    Le test fait glisser **deux** mains en même temps, sur deux éléments, et lit
    les identités telles que le DOM les reçoit : deux, distinctes, et les mêmes
    d'une image à l'autre."""

    result = run_node(tmp_path, BROWSER + """
      const a=button({left:100,top:100,width:120,height:40},'Un');
      const b=button({left:400,top:100,width:120,height:40},'Deux');
      global.page=[a,b];
      const pa={x:160,y:120},pb={x:460,y:120};
      shot(0,[token(1,pa.x,pa.y),token(2,pb.x,pb.y)],
        [contact(1,'pressed'),contact(2,'pressed')],
        [{handTrackId:1,channel:'primary',phase:'down',x:pa.x,y:pa.y},
         {handTrackId:2,channel:'primary',phase:'down',x:pb.x,y:pb.y}]);
      for(const k of [1,2])
        shot(16*k,[token(1,pa.x+10*k,pa.y),token(2,pb.x+10*k,pb.y)],
          [contact(1,'pressed','drag'),contact(2,'pressed','drag')],[]);
      shot(48,[token(1,pa.x+20,pa.y),token(2,pb.x+20,pb.y)],[],
        [{handTrackId:1,channel:'primary',phase:'up',x:pa.x+20,y:pa.y},
         {handTrackId:2,channel:'primary',phase:'up',x:pb.x+20,y:pb.y}]);
      const ids=el=>[...new Set(el.events.filter(e=>e.pointerId!==undefined&&e.pointerId!==null)
        .map(e=>e.pointerId))];
      out({first:ids(a),second:ids(b),
        inRange:[...ids(a),...ids(b)].every(id=>C.isBareHandsPointerId(id)),
        types:a.events.map(e=>e.type).filter(t=>t.indexOf('over')<0&&t.indexOf('out')<0)});
    """)
    # Une identité par main, stable sur tout le geste, et deux **différentes**.
    assert len(result["first"]) == 1 and len(result["second"]) == 1
    assert result["first"] != result["second"], "deux mains sous la même identité de pointeur"
    assert result["inRange"] is True
    assert result["types"] == ["pointerdown", "mousedown", "pointermove", "mousemove",
                               "pointerup", "mouseup"]


def test_a_grip_the_contract_refuses_is_written_on_the_screen(tmp_path):
    """RÈGLE ZÉRO. Deux mains sur la même zone ne manipulent rien (décision 15) :
    sans un mot à l'écran, c'est une main qui insiste sans effet, indiscernable
    d'une panne — et c'est la première question qu'on se pose devant un cadre qui
    ne bouge pas.

    La raison remonte donc jusqu'à la ligne qui porte déjà les gestes étouffés,
    et une raison **inconnue** s'affiche telle quelle : ce nom est la seule
    information que cette ligne transporte."""

    result = run_node(tmp_path, BROWSER + """
      const win=star('obj-1',{left:200,top:100,width:400,height:300},'window','Tâche A');
      global.page=[win];
      sceneObjects['obj-1']={box:{x:-32,y:-20,w:64,h:40},representation:'window'};
      const edge={x:600,y:250};
      shot(0,[token(1,edge.x,edge.y),token(2,edge.x-2,edge.y+6)],
        [contact(1,'pressed'),contact(2,'pressed')],
        [{handTrackId:1,channel:'primary',phase:'down',x:edge.x,y:edge.y},
         {handTrackId:2,channel:'primary',phase:'down',x:edge.x-2,y:edge.y+6}]);
      shot(16,[token(1,edge.x,edge.y,edge.x+80,edge.y),token(2,edge.x-2,edge.y+6,edge.x+80,edge.y+6)],
        [contact(1,'pressed','drag'),contact(2,'pressed','drag')],[]);
      const refusal=interaction.refusal();
      /* Et la surimpression l'écrit, telle quelle. */
      overlay.render([],refusal);
      const line=root().children.find(el=>el.className===C.DOM.noteClass);
      const said=line.textContent;
      overlay.render([],'a_reason_from_the_future');
      const unknown=line.textContent;
      overlay.render([],'');
      out({refusal,said,unknown,hidden:line.style.display,
        begins:sceneLog.begins,previews:sceneLog.previews.length,
        captured:interaction.captures().sort()});
    """)
    assert result["refusal"] == "same_zone_rejected"
    assert "PRISE REFUSÉE" in result["said"] and "même zone" in result["said"]
    # Une raison inconnue n'est pas remplacée par une phrase générique.
    assert "a_reason_from_the_future" in result["unknown"]
    assert result["hidden"] == "none"
    # Rien n'a bougé, et les deux captures restent latchées (décision 13).
    assert result["begins"] == [] and result["previews"] == 0
    assert result["captured"] == [1, 2]


# -------------------------------------------------------------- dans la page


async def test_the_page_serves_the_scene_geometry_before_the_pointer_that_reads_it(tmp_path):
    """Constat F3 de la Slice 00, appliqué à une dépendance **nouvelle** : la
    Slice 06 n'ajoute aucun module de page, mais le pointeur lit désormais
    `JarvisSceneInteract` au chargement de son bloc navigateur. Servi après lui,
    la page casserait à l'insertion — pas à l'usage, et pas dans les tests.

    L'ordre complet est donc : géométrie de la scène → contrats → cible →
    pointeur → page de scène."""

    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    page = (await control.index(None)).text
    raw = PAGE_HTML.read_text(encoding="utf-8")
    assert (
        raw.index(SCENE_INTERACT_SCRIPT_MARKER)
        < raw.index(BAREHANDS_SCRIPT_MARKER)
        < raw.index(SCENE_PAGE_SCRIPT_MARKER)
    )
    # Les repères sont consommés : c'est le code servi, pas le commentaire.
    for marker in (SCENE_INTERACT_SCRIPT_MARKER, BAREHANDS_SCRIPT_MARKER, SCENE_PAGE_SCRIPT_MARKER):
        assert marker not in page
    order = [
        page.index("root.JarvisSceneInteract=api"),
        page.index("const GEOMETRY=JarvisSceneInteract"),
        page.index("window.JarvisScene=Object.freeze"),
    ]
    assert order == sorted(order), "la géométrie de la scène doit précéder le pointeur"


def test_the_scene_publishes_a_frame_seam_that_reuses_its_own_geometry(tmp_path):
    """La page de scène tient le cadre pour Bare Hands, et **réutilise** ce que
    la souris utilise : la même prise (`holdTarget`, `takeHold`) et le même
    bureau des tenues (`desk.to`, `desk.drop`, `desk.cancel` — 22/09/2026). Une seconde géométrie aurait donné
    deux bornages, deux épinglages et une seule documentation ; c'est ce qui
    s'était produit : `frames.commit` enregistrait la boîte dessinée sans
    défaire le tour, et l'objet sautait au lâcher. Le comportement est prouvé
    dans `test_scene_hold_contract.py`.

    Vérifié par lecture de source, faute de harnais DOM pour `installJarvisScene`
    — le même résidu que la Slice 05 a laissé pour `data-representation`, et le
    même renvoi : la validation runtime de la Slice 11."""

    source = SCENE_PAGE.read_text(encoding="utf-8")
    seam = source.split("cadres tenus à mains nues")[1].split("function onPointerDown")[0]
    for name in ("holdTarget(id)", "takeHold('hand',[id],{},'Déplacement')", "desk.to(handle,id,box,mode)",
                 "desk.drop(handle,kind)", "desk.cancel(handle)", "handle.hold.start(id)", "viewportNow()"):
        assert name in seam, name
    # Aucune géométrie calculée ici : elle vient du module pur.
    assert "clampBox" not in seam and "pxToUnits" not in seam
    # La souris gagne sur une main : le geste le plus explicite des deux — et
    # réciproquement, une main ne vole pas un nœud que la souris tient déjà.
    #
    # **Les deux moitiés portent sur toute la sélection, pas sur le seul objet
    # pris.** Depuis la fusion d'`origin/main`, un glissement souris emmène ses
    # voisins sélectionnés (`carried`), et `holdNode` est donc écrit par les
    # deux chemins pour chacun d'eux. Ne libérer que `id` laisserait une main
    # tenir un cadre que la souris déplace, et le `holdNode(member.id,false)`
    # du lâcher couperait le fil de cette main sans qu'elle le sache.
    assert "for(const member of carried)frames.cancel(member.id);" in source, (
        "la souris ne libère pas toutes les mains des objets qu'elle emmène"
    )
    assert "gesture.id===id||(gesture.carried||[]).some(member=>member.id===id)" in seam, (
        "une main peut encore saisir un voisin que la souris est en train de déplacer"
    )
    # Éteinte, la scène ne rend **pas** de fenêtre : `begin` avait sa porte,
    # `viewport` non — et une échelle absente vaut six fois trop de course, en
    # silence, côté Bare Hands (qui la refuse maintenant).
    assert "viewport(){return enabled&&root?viewportNow():null}" in seam
    # Et la couture est publiée.
    assert "frames," in source.split("window.JarvisScene=Object.freeze")[1]


# ------------------------------------------ Slice 07 : le cadre d'entraînement
#
# Ce que ces tests épinglent n'est pas « la calibration affiche une fenêtre »,
# c'est que **la fenêtre d'entraînement est la vraie chose**. Le bac à sable
# n'est donc pas un double ici : c'est `createPracticeFrame`, branché comme
# `world` du **vrai** moteur d'interaction, avec les **vrais** contrats et la
# **vraie** géométrie de scène. Si une règle de manipulation était réécrite
# quelque part pour l'exercice, elle divergerait ici et ces tests le diraient.


#: Le bac à sable réel en guise de monde, et une échelle de scène qu'on peut
#: éteindre — c'est la moitié technique de la divergence D4.
PRACTICE = """
const benchOf=opts=>{
  const o=opts||{};
  const scene={on:o.scene!==false,painted:[]};
  const frame=B.createPracticeFrame({geometry:G,
    viewport:()=>scene.on?{scale:6,width:1280,height:720,cx:640,cy:360}:null,
    paint:box=>scene.painted.push([box.x,box.y,box.w,box.h]),
    box:o.box});
  return {frame,scene,api:frame.world};
};
const asBox=b=>[b.x,b.y,b.w,b.h];
"""


def test_the_practice_frame_is_moved_by_one_zone_through_the_real_engine(tmp_path):
    """**6A, et elle exige une vraie capture de zone.**

    Trois prises, trois issues, et aucune n'est décidée par la calibration :

    - un **bord** tenu d'une main déplace le cadre entier (décision 10) ;
    - le **corps** d'une fenêtre est du contenu, pas une poignée de cadre
      (décision 8) : il ne déplace rien, donc 6A ne peut pas se solder en
      attrapant le milieu de la fenêtre ;
    - et le relâchement rend un `commit` de mode `move` **dont la boîte a
      changé**, qui est exactement ce que la sous-étape constate.

    Le cadre ne bouge qu'une fois la prise **armée** (`intent: drag`) : un clic
    sur un bord ne le déplace pas d'une unité, sans quoi il s'épinglerait au
    passage.
    """

    result = run_node(tmp_path, FIXTURE + PRACTICE + """
      const run=(region,zone)=>{
        const bench=benchOf();
        const e=engineOf({world:bench.api});
        const id=bench.frame.objectId;
        const targets=[tgt(1,id,region,zone)];
        const home={x:400,y:300};
        e.update({now:0,tokens:[tok(1,home.x,home.y)],targets,
          events:[ev(1,'down',home.x,home.y)],contacts:[held(1,'undecided')]});
        /* Pas encore armee : rien ne bouge, et rien n'est meme commence. */
        const beforeArming=bench.frame.drain().length;
        for(let k=1;k<=4;k+=1)
          e.update({now:16*k,tokens:[tok(1,home.x+30*k,home.y+12*k)],targets,
            events:[],contacts:[held(1,'drag')]});
        e.update({now:200,tokens:[tok(1,520,348)],targets:[],
          events:[ev(1,'up',520,348)],contacts:[]});
        const log=bench.frame.drain();
        const commit=log.filter(x=>x.type==='commit')[0]||null;
        return {beforeArming,
          types:[...new Set(log.map(x=>x.type))],
          box:asBox(bench.frame.box()),origin:asBox(bench.frame.origin()),
          commit:commit?[commit.mode,commit.moved,commit.sized].concat(asBox(commit.box)):null,
          painted:bench.scene.painted.length};
      };
      out({edge:run('edge','right'),corner:run('corner','top_left'),
        body:run('body',null)});
    """)

    edge = result["edge"]
    # Un clic sur un bord n'ouvre aucun plan : rien n'a bougé avant l'armement.
    assert edge["beforeArming"] == 0, (
        "un appui non armé déplaçait le cadre d'une unité — et l'épinglait au passage"
    )
    # La prise armée ouvre un plan, prévisualise, puis valide.
    assert edge["types"] == ["begin", "preview", "commit"]
    assert edge["commit"][0] == "move"
    assert edge["commit"][1] is True and edge["commit"][2] is False, (
        "6A constate un déplacement, et rien d'autre"
    )
    # 30 px par image sur quatre images, à 6 px/unité : 120 px => 20 unités en x,
    # 48 px => 8 en y. La conversion est celle de `manipulateBox`, pas la nôtre.
    # Le compte dit le **rebasage** (decision 19) : le plan s'ouvre a l'image qui
    # l'arme et prend *cette* paume pour ancre, donc la course utile va de la 1re
    # a la 4e image - trois pas, pas quatre. 30 px x 3 = 90 px, a 6 px/unite =
    # 15 unites en x ; 12 px x 3 = 36 px = 6 en y. Un cadre parti de 20 et 8
    # signalerait que l'image d'armement a ete comptee deux fois.
    assert edge["commit"][3:] == [-32 + 15, -20 + 6, 64, 40]
    assert edge["painted"] > 0, "ce que le moteur calcule est ce qui est dessiné"
    # Un coin déplace aussi le cadre entier : une zone est une poignée de cadre.
    assert result["corner"]["commit"][0] == "move"
    assert result["corner"]["commit"][1] is True
    # **Le corps d'une fenêtre est du contenu** (décision 8) : il n'ouvre aucun
    # plan, donc 6A ne se solde pas en attrapant le milieu de la fenêtre.
    assert result["body"]["types"] == []
    assert result["body"]["commit"] is None
    assert result["body"]["box"] == result["body"]["origin"]


def test_the_practice_frame_resizes_only_on_two_distinct_compatible_zones(tmp_path):
    """**6B, et les trois façons de ne pas la réussir.**

    Ce test est le cœur de la sous-étape : ce qui décide qu'un couple de prises
    redimensionne n'est écrit **nulle part** dans la calibration — c'est
    `combineCaptures`, par le moteur, sur le cadre d'entraînement. Quatre
    couples, et un seul produit un redimensionnement :

    - deux bords **opposés** : le cadre grandit, et 6B se solde ;
    - la **même zone** deux fois (`same_zone_rejected`) : rien ;
    - deux **corps** (`both_captures_are_body`, décision 8) : rien ;
    - et une seule main sur une zone : c'est un `move`, donc pas un
      redimensionnement — la sous-étape ne peut pas se solder par erreur en
      déplaçant la fenêtre à une main.
    """

    result = run_node(tmp_path, FIXTURE + PRACTICE + """
      const run=(a,b,moveA,moveB)=>{
        const bench=benchOf();
        const e=engineOf({world:bench.api});
        const id=bench.frame.objectId;
        const mk=(hand,spec)=>tgt(hand,id,spec.region,spec.zone);
        const targets=[mk(1,a)];
        if(b)targets.push(mk(2,b));
        const home={x:300,y:300},away={x:900,y:300};
        const events=[ev(1,'down',home.x,home.y)];
        if(b)events.push(ev(2,'down',away.x,away.y));
        const contacts=[held(1,'undecided')];
        if(b)contacts.push(held(2,'undecided'));
        const toks=k=>{
          const list=[tok(1,home.x+moveA[0]*k,home.y+moveA[1]*k)];
          if(b)list.push(tok(2,away.x+moveB[0]*k,away.y+moveB[1]*k));
          return list;
        };
        /* Les refus sont **vides a chaque image** (ils decrivent un instant) :
           on les ramasse au vol, sinon le refus de la 2e image serait invisible
           depuis la derniere. */
        const seen=[];
        const run1=f=>{for(const r of (f.refusals||[]))seen.push(r.reason)};
        run1(e.update({now:0,tokens:toks(0),targets,events,contacts}));
        const drag=[held(1,'drag')];if(b)drag.push(held(2,'drag'));
        for(let k=1;k<=4;k+=1)
          run1(e.update({now:16*k,tokens:toks(k),targets,events:[],contacts:drag}));
        const ups=[ev(1,'up',0,0)];if(b)ups.push(ev(2,'up',0,0));
        run1(e.update({now:200,tokens:toks(4),targets:[],events:ups,contacts:[]}));
        const log=bench.frame.drain();
        const commit=log.filter(x=>x.type==='commit')[0]||null;
        return {commit:commit?[commit.mode,commit.moved,commit.sized].concat(asBox(commit.box)):null,
          refusals:[...new Set(seen)],
          box:asBox(bench.frame.box())};
      };
      const edge=z=>({region:'edge',zone:z});
      const body={region:'body',zone:null};
      out({
        opposite:run(edge('left'),edge('right'),[-60,0],[60,0]),
        sameZone:run(edge('right'),edge('right'),[60,0],[60,0]),
        bothBodies:run(body,body,[60,0],[60,0]),
        oneHand:run(edge('right'),null,[60,0],null),
      });
    """)

    # **Le seul couple qui redimensionne.** 60 px par image sur quatre images,
    # à 6 px/unité : chaque bord recule de 40 unités, donc 64 + 80 = 144.
    opposite = result["opposite"]
    assert opposite["commit"][0] == "resize"
    assert opposite["commit"][2] is True, "6B constate un redimensionnement"
    # Trois pas utiles apres le rebasage d'armement : 60 px x 3 = 180 px, soit
    # 30 unites par bord. Le cadre passe de 64 a 124 de large et son bord gauche
    # recule de 30. La hauteur ne bouge pas d'une unite : deux bords de l'axe x
    # ne touchent pas y, et c'est `combineCaptures` qui l'a decide, pas ce test.
    assert opposite["commit"][3:] == [-62, -20, 124, 40]

    # **La même zone deux fois ne se redimensionne pas** (décision 15), et le
    # refus se dit : sans lui, deux mains sur le même bord auraient été un
    # redimensionnement confiant et faux.
    assert result["sameZone"]["commit"] is None
    assert "same_zone_rejected" in result["sameZone"]["refusals"]
    assert result["sameZone"]["box"] == [-32, -20, 64, 40]

    # **Deux corps ne sont pas une poignée de cadre** (décision 8).
    assert result["bothBodies"]["commit"] is None
    assert result["bothBodies"]["box"] == [-32, -20, 64, 40]

    # **Une seule main déplace, elle ne redimensionne jamais** (décision 11) :
    # 6B ne peut donc pas se solder en traînant la fenêtre d'une main.
    assert result["oneHand"]["commit"][0] == "move"
    assert result["oneHand"]["commit"][2] is False, "aucune taille n'a changé"


def test_the_practice_frame_inherits_min_size_no_inversion_and_the_lost_hand(tmp_path):
    """**Les règles de production s'appliquent au cadre d'entraînement**, parce
    que ce sont les mêmes — elles ne sont pas recopiées pour l'exercice.

    Trois, et chacune a déjà coûté quelque chose ailleurs :

    - deux mains qui se croisent **bornent** le cadre à la taille minimale d'une
      fenêtre au lieu de le retourner (décision 18) ;
    - une main perdue **suspend** la manipulation au lieu de laisser l'autre
      tirer le cadre de travers, et la reprise **rebase** donc le cadre ne
      rattrape pas d'un coup la course de la suspension (décision 19) ;
    - la boîte reste dans la zone sûre de la scène.
    """

    result = run_node(tmp_path, FIXTURE + PRACTICE + """
      /* Deux mains qui se croisent tres au-dela du centre du cadre. */
      const crossed=(function(){
        const bench=benchOf();
        const e=engineOf({world:bench.api});
        const id=bench.frame.objectId;
        const targets=[tgt(1,id,'edge','left'),tgt(2,id,'edge','right')];
        const home={x:300,y:300},away={x:900,y:300};
        e.update({now:0,tokens:[tok(1,home.x,home.y),tok(2,away.x,away.y)],targets,
          events:[ev(1,'down',home.x,home.y),ev(2,'down',away.x,away.y)],
          contacts:[held(1,'undecided'),held(2,'undecided')]});
        for(let k=1;k<=10;k+=1)
          e.update({now:16*k,tokens:[tok(1,home.x+80*k,300),tok(2,away.x-80*k,300)],
            targets,events:[],contacts:[held(1,'drag'),held(2,'drag')]});
        e.update({now:400,tokens:[],targets:[],
          events:[ev(1,'up',0,0),ev(2,'up',0,0)],contacts:[]});
        return asBox(bench.frame.box());
      })();
      /* Une main disparait au milieu du geste, puis revient ailleurs. */
      const lost=(function(){
        const bench=benchOf();
        const e=engineOf({world:bench.api});
        const id=bench.frame.objectId;
        const targets=[tgt(1,id,'edge','left'),tgt(2,id,'edge','right')];
        const both=k=>[tok(1,300+10*k,300),tok(2,900+10*k,300)];
        e.update({now:0,tokens:both(0),targets,
          events:[ev(1,'down',300,300),ev(2,'down',900,300)],
          contacts:[held(1,'undecided'),held(2,'undecided')]});
        e.update({now:16,tokens:both(1),targets,events:[],
          contacts:[held(1,'drag'),held(2,'drag')]});
        const afterOne=asBox(bench.frame.box());
        /* La seconde main disparait : la manipulation **se suspend**. Le jeton
           qui reste continue pourtant de courir, tres loin. */
        for(let k=2;k<=8;k+=1)
          e.update({now:16*k,tokens:[tok(1,300+200*k,300)],targets,events:[],
            contacts:[held(1,'drag')]});
        const whileLost=asBox(bench.frame.box());
        /* Elle revient : le cadre ne doit pas rattraper d'un coup les 1 400 px
           parcourus pendant la suspension. */
        e.update({now:160,tokens:[tok(1,300+200*8,300),tok(2,900,300)],targets,
          events:[],contacts:[held(1,'drag'),held(2,'drag')]});
        const afterReturn=asBox(bench.frame.box());
        return {afterOne,whileLost,afterReturn};
      })();
      out({crossed,lost,min:G.MIN_SIZE.window,safe:G.SAFE_AREA});
    """)

    minimum = result["min"]
    x, y, w, h = result["crossed"]
    assert w == minimum["w"], "des mains qui se croisent retournaient le cadre"
    assert w > 0 and h > 0
    assert result["safe"]["x0"] <= x and x + w <= result["safe"]["x1"]

    lost = result["lost"]
    # Pendant la suspension, le cadre ne bouge **pas** : laisser la main
    # survivante tirer seule le redimensionnerait de travers.
    assert lost["whileLost"] == lost["afterOne"], (
        "la main restée seule a continué de redimensionner pendant le clignement"
    )
    # Et la reprise rebase : 1 400 px de course accumulée ne s'appliquent pas
    # d'un coup (mesuré à 68 unités quand ce rebasage manquait).
    assert lost["afterReturn"] == lost["afterOne"], (
        "le cadre a rattrapé d'un coup la course de la suspension"
    )


def test_the_practice_frame_never_reaches_the_scene_and_dies_with_the_exercise(tmp_path):
    """**Le bac à sable, et c'est la promesse produit de cette sous-étape.**

    Le cadre d'entraînement se manipule comme un objet de la scène et n'en est
    pas un : sa géométrie ne part nulle part. Deux garanties, et la seconde est
    structurelle :

    - `commit` **retient** la boîte et ne l'envoie pas — il n'y a aucun chemin
      d'ici vers `commitUserGeometry` ;
    - après `close()`, les quatre portes rendent `null` et `owns()` est faux :
      une image en retard ne peut pas ressusciter un cadre que l'utilisateur
      vient de quitter, ni le faire entrer dans la scène par la porte de
      derrière.

    Et l'identifiant est **nommé pour ne ressembler à aucun objet de Core** :
    c'est ce qui permet à la façade de la page de le router vers le bac à sable
    sans jamais interroger la scène.
    """

    result = run_node(tmp_path, FIXTURE + PRACTICE + """
      const bench=benchOf();
      const e=engineOf({world:bench.api});
      const id=bench.frame.objectId;
      const targets=[tgt(1,id,'edge','right')];
      e.update({now:0,tokens:[tok(1,300,300)],targets,
        events:[ev(1,'down',300,300)],contacts:[held(1,'undecided')]});
      for(let k=1;k<=3;k+=1)
        e.update({now:16*k,tokens:[tok(1,300+40*k,300)],targets,events:[],
          contacts:[held(1,'drag')]});
      e.update({now:100,tokens:[tok(1,420,300)],targets:[],
        events:[ev(1,'up',420,300)],contacts:[]});
      const moved=asBox(bench.frame.box());
      const ownedBefore=bench.frame.owns(id);
      const closed=bench.frame.close();
      /* Apres la fermeture : plus rien ne repond, et une image en retard ne
         peut donc pas rouvrir un plan. */
      const after={
        begin:bench.api.begin(id),
        preview:bench.api.preview(id,{x:0,y:0,w:80,h:50}),
        commit:bench.api.commit(id,{x:0,y:0,w:80,h:50},'move'),
        cancel:bench.api.cancel(id),
        owns:bench.frame.owns(id),
        drained:bench.frame.drain().length,
        closedTwice:bench.frame.close(),
      };
      out({id,moved,ownedBefore,closed,after,
        viewport:bench.api.viewport(),
        offScene:benchOf({scene:false}).api.viewport(),
        defaultBox:asBox(B.createPracticeFrame({geometry:G,viewport:()=>({scale:6})}).box()),
        pinned:B.PRACTICE_OBJECT_ID});
    """)

    # L'identifiant ne peut pas entrer en collision avec un objet de Core : il
    # ne ressemble pas à un identifiant de scène, et c'est délibéré.
    assert result["id"] == result["pinned"] == "barehands:practice-frame"
    # Le geste a bien eu lieu, et sa boîte est retenue **localement**.
    assert result["moved"] != [-32, -20, 64, 40]
    assert result["ownedBefore"] is True and result["closed"] is True
    # Après le démontage, les quatre portes se taisent.
    after = result["after"]
    assert after["begin"] is None and after["preview"] is None
    assert after["commit"] is None and after["cancel"] is None
    assert after["owns"] is False and after["drained"] == 0
    assert after["closedTwice"] is False, "un démontage est idempotent"
    # L'échelle vient de la scène, et scène éteinte elle vaut `null` : c'est la
    # divergence D4, côté technique.
    assert result["viewport"]["scale"] == 6
    assert result["offScene"] is None
    # La boîte de départ est bornée par `clampBox`, pas par une constante
    # recopiée : elle tient dans la zone sûre et au-dessus du minimum.
    assert result["defaultBox"] == [-32, -20, 64, 40]


def test_the_page_routes_the_practice_frame_away_from_the_scene(tmp_path):
    """**La garantie est structurelle, pas déclarative.**

    Le module précédent prouve que le bac à sable ne persiste rien ; celui-ci
    prouve que la page ne lui fait pas court-circuiter la scène par accident.
    La façade `world` du moteur interroge le cadre d'entraînement **avant** la
    scène, donc tant qu'il revendique son identifiant, aucune des quatre portes
    de `JarvisScene.frames` n'est traversée pour lui — et `commitUserGeometry`
    est inatteignable pour l'exercice.

    `viewport`, elle, n'est **pas** détournée, et c'est délibéré : l'échelle
    appartient à la scène, elle est la même pour le cadre d'entraînement et pour
    un vrai cadre, et c'est ce qui rend le geste appris ici transposable.
    """

    source = SCRIPT.read_text(encoding="utf-8")
    seam = source.split("const world={")[1].split("\n    };")[0]
    # Les quatre portes demandent d'abord au banc, puis seulement a la scene :
    # tant que le banc revendique l'identifiant, `sceneCall` n'est pas atteint.
    for door in ("begin", "preview", "commit", "cancel"):
        body = seam.split(door + "(objectId")[1].split("sceneCall")[0]
        assert "held(objectId)" in body, door
        assert "return bench?bench.world." in body, door
        assert "sceneCall('" + door + "'" in seam, door
    # L'echelle, elle, va toujours a la scene - jamais au banc (divergence D4).
    assert "viewport:()=>sceneCall('viewport',null)" in seam
    # Et le routage a **un seul** proprietaire, qui peut le retirer.
    assert "usePractice(frame)" in source and "practice=null" in source


def test_the_practice_frame_refuses_to_be_built_without_the_canonical_pieces(tmp_path):
    """**Il n'y a aucune géométrie dans le bac à sable, et il le prouve en
    refusant de se construire sans.**

    Deux refus à la construction, et les deux disent la même chose : ce module
    ne calcule rien. Sans `geometry`, il ne pourrait pas borner sa boîte de
    départ ni savoir si une boîte a changé — et les réécrire ici ferait diverger
    l'exercice du vrai cadre qu'il doit imiter. Sans `viewport`, il devrait
    inventer une échelle, ce que la divergence D4 interdit explicitement.
    """

    result = run_node(tmp_path, FIXTURE + """
      const refused=fn=>{try{fn();return null}catch(e){return String(e&&e.message||e)}};
      out({
        noGeometry:refused(()=>B.createPracticeFrame({viewport:()=>({scale:6})})),
        halfGeometry:refused(()=>B.createPracticeFrame({geometry:{clampBox:()=>({})},
          viewport:()=>({scale:6})})),
        noViewport:refused(()=>B.createPracticeFrame({geometry:G})),
        built:!!B.createPracticeFrame({geometry:G,viewport:()=>null}).objectId,
      });
    """)
    assert "geometry" in result["noGeometry"] and "clampBox" in result["noGeometry"]
    assert result["halfGeometry"] is not None, "une géométrie à moitié n'en est pas une"
    assert "viewport" in result["noViewport"]
    # Une échelle absente **à l'exécution** n'empêche pas la construction : c'est
    # la calibration qui décide alors de passer l'étape, avec un motif nommé.
    assert result["built"] is True

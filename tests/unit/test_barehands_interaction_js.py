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
      /* Et contre le bord de la zone sûre : le cadre s'arrête, il ne sort pas.
         Sans la réentrée finale, le partage du manque le pousse dehors. */
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
    # partage en deux parts égales donnerait x = -22, soit le cadre posé neuf
    # unités à gauche de là où les mains l'ont laissé.
    assert result["lopsided"] == [-13, -20, 40, 40]
    # Contre le bord : la taille minimale **et** la zone sûre, les deux.
    left, _, width, _ = result["atEdge"]
    assert width == minimum["w"]
    assert left == result["safe"]["x0"], "le cadre est sorti de la zone sûre"


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
    mutée."""

    result = run_node(tmp_path, FIXTURE + """
      const fs=require('fs');
      const source=fs.readFileSync(SCENE_INTERACT_PATH,'utf8');
      const broken=source.replace('MAX_SIZE=Object.freeze({capsule:Object.freeze({w:160,h:10})})',
                                  'MAX_SIZE=Object.freeze({capsule:Object.freeze({w:8,h:4})})');
      out({mutated:broken!==source,
        refusal:refused(()=>{new Function(broken)()}),
        /* Et le défaut qu'il attrape, mesuré sur la fonction elle-même : sans le
           refus, la capsule descendrait sous sa largeur minimale de 16. */
        healthy:G.resizeBySides({x:0,y:0,w:40,h:7},{right:-400},'capsule').w,
        min:G.MIN_SIZE.capsule.w});
    """)
    assert result["mutated"] is True, "la constante visée a changé de nom"
    assert result["refusal"] == "RangeError"
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
    # L'armement **rebase** : à l'image où l'intention bascule, le déplacement
    # vaut zéro et rien n'est dessiné — les 160 px déjà parcourus depuis la
    # descente ne sont pas réinterprétés d'un coup. Le premier aperçu est donc
    # celui de l'image suivante, 60 px plus loin.
    assert result["previews"] == [[10, 0, 64, 40]], result["previews"]
    assert result["previews"][-1][2] == 64 and result["previews"][-1][3] == 40, (
        "une seule main ne redimensionne jamais"
    )
    assert [c[1] for c in result["commits"]] == ["move"]
    assert result["commits"][0][2:] == [10, 0, 64, 40]
    assert result["cancels"] == []
    assert result["captured"] == []
    # Aucun clic publié : la main a déplacé, elle n'a pas cliqué.
    assert "click" not in sum(result["steps"], []) + result["lastTypes"]
    assert "move" in sum(result["steps"], [])


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
    # 30 unités de chaque côté (180 px à 6 px/unité, depuis l'armement) :
    # 64 + 60, hauteur intacte — l'axe y n'était tenu par personne.
    assert opposite["commit"] == ["resize", -62, -20, 124, 40]

    shared = result["edgeAndCorner"]
    assert shared["byHand"] == [["1", ["right"]], ["2", ["top"]]], (
        "décision 16 : le bord garde le côté partagé, le coin ne garde que l'autre"
    )
    assert shared["axes"] == ["x", "y"]
    # Le bord droit emmène la largeur, le coin ne tire que sur le haut : le
    # bord gauche et le bas n'ont bougé d'aucune unité.
    assert shared["commit"] == ["resize", -32, -50, 94, 70]

    neutral = result["twoCornersSharingRight"]
    assert neutral["axes"] == ["y"], "décision 17 : le côté partagé neutralise son axe"
    assert neutral["published"] == ["y"]
    assert neutral["commit"][3] == 64, "la largeur ne doit pas avoir changé d'une unité"
    assert neutral["commit"][4] == 100, "les deux coins tirent chacun son côté vertical"
    assert neutral["commit"][1] == -32, "le bord gauche est resté où il était"

    corners = result["oppositeCorners"]
    assert corners["axes"] == ["x", "y"]
    assert corners["published"] == ["xy"]
    assert corners["commit"] == ["resize", -62, -50, 124, 100]


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
    # La main de zone est partie de 120 px vers la droite depuis l'armement :
    # 20 unités, taille intacte — et la main de corps, partie dans l'autre sens,
    # n'a rien tiré du tout.
    assert result["commit"] == ["move", 20, 0, 64, 40]


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
        /* Et au relâchement : une zone qui n'a rien déplacé a **cliqué**, elle
           n'a pas sélectionné du contenu — une zone n'est jamais du contenu. */
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
    assert result["releasedTypes"] == ["click"], result["releasedTypes"]
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
    assert result["commit"] == ["move", -52, -20, 64, 40]
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
        ["a", "move", -20, 0, 64, 40],
        ["b", "move", 40, 20, 40, 7],
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
    assert result["commits"] == [["a", 20, 64, 40]]


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
    # Deux mains ont écarté le cadre de 60 px chacune depuis l'armement :
    # 10 unités par côté, donc 64 + 20.
    assert result["resized"] == [-42, -20, 84, 40]
    # Le retrait d'une main ne bouge rien : c'est le rebasage.
    assert result["rebased"] == result["resized"], "le cadre a sauté au retrait d'une main"
    # Puis 60 px de paume = 10 unités de déplacement, taille inchangée.
    assert result["after"] == [-52, -20, 84, 40]
    assert result["commits"] == [["move", -52, -20, 84, 40]]
    # La main revenue sous une autre identité tire pour de bon : le cadre
    # s'élargit encore de 10 unités, alors que le mode et les axes n'ont pas
    # changé. Sans « qui tient quoi » dans la signature, elle n'aurait pas
    # d'ancre et ne tirerait plus jamais rien.
    assert result["widened"] == [-42, -20, 84, 40]
    assert result["regrabbed"] == [-42, -20, 104, 40], result["regrabbed"]


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
    assert result["sameHand"]["box"] == [-10, 0, 64, 40]
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
        /* Et le moteur n'a pas sa propre table des côtés : il lit celle du
           contrat, sous son nom. */
        source:!/SIDE_AXIS\\s*=\\s*Object\\.freeze/.test(require('fs')
          .readFileSync(SCRIPT_PATH,'utf8').split('Moteur d’interaction et captures')[1]||''),
      });
    """)
    for case in ("nothing", "noContracts", "noCombine", "noSides", "noZoneSides",
                 "noGeometry", "halfGeometry"):
        assert result[case] == "RangeError", case
    assert result["built"] is True
    assert result["source"] is True, "le moteur a redérivé la table des côtés"


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
BROWSER = """
const registry=[];
const node=(opts)=>{
  const o=Object.assign({sel:[],rect:null,id:'',dataset:{},label:''},opts||{});
  const classes=new Set();
  const el={children:[],className:'',id:o.id,textContent:o.label,offsetWidth:1,
    sel:o.sel,dataset:o.dataset,attrs:{},parent:null,events:[],
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
  registry.push(el);
  return el;
};
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
        scene:sceneLog.begins});
    """)
    # Le survol hérité (`pointerover`/`mouseover`) reste ce qu'il était : ce qui
    # nous appartient est la séquence de contact.
    kinds = [row[0] for row in result["dragged"] if "over" not in row[0] and "out" not in row[0]]
    assert kinds == ["pointerdown", "mousedown", "pointermove", "mousemove", "pointerup", "mouseup"]
    # Identité par main, dans la plage du contrat — jamais le littéral 9001 ici.
    assert {row[1] for row in result["dragged"] if row[1] is not None} == {9001}
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
    la souris utilise : `drawnBox`, `previewAt`, `holdNode`, `commitUserGeometry`.
    Une seconde géométrie aurait donné deux bornages, deux épinglages et une
    seule documentation.

    Vérifié par lecture de source, faute de harnais DOM pour `installJarvisScene`
    — le même résidu que la Slice 05 a laissé pour `data-representation`, et le
    même renvoi : la validation runtime de la Slice 11."""

    source = SCENE_PAGE.read_text(encoding="utf-8")
    seam = source.split("cadres tenus à mains nues")[1].split("function onPointerDown")[0]
    for name in ("drawnBox(id)", "holdNode(id,true)", "previewAt(", "commitUserGeometry(",
                 "viewportNow()", "I.sameBox(box,start)"):
        assert name in seam, name
    # Aucune géométrie calculée ici : elle vient du module pur.
    assert "clampBox" not in seam and "pxToUnits" not in seam
    # La souris gagne sur une main : le geste le plus explicite des deux — et
    # réciproquement, une main ne vole pas un nœud que la souris tient déjà.
    assert "frames.cancel(id);" in source
    assert "if(gesture&&gesture.id===id)return null;" in seam
    # Et la couture est publiée.
    assert "frames," in source.split("window.JarvisScene=Object.freeze")[1]

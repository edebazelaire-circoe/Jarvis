"""Le contrat du déplacement 2D de la scène (22/09/2026).

Plainte de l'utilisateur : « Il y a toujours des énormes bugs sur le
déplacement 2D. Je me tape des murs invisibles, des décalages quand je lâche
l'objet... C'est un ENFER ! C'est totalement à revoir. »

Le contrat, pour la souris, Bare Hands (`JarvisScene.frames`) et le clavier, à
n'importe quelle phase du tour, à n'importe quelle ampleur, gravitation allumée
ou éteinte, pour toutes les formes et quatre tailles d'écran :

1. pendant le geste, le point saisi de l'objet **dessiné** reste sous le
   pointeur (≤ 1 px) tant que l'objet dessiné reste dans l'écran visible réel,
   moins les commandes de la page réellement présentes — aucun autre mur ;
2. au lâcher, l'objet dessiné reste là où il était à la dernière image (≤ 1 px) ;
3. le reprendre ensuite ne le fait pas sauter (≤ 1 px pour un geste de 5 px) ;
4. le champ est en pause pendant toute tenue (vérifié côté page, voir
   `test_scene_renderer_logic.py`).

Prouvé en exécutant avec node les fichiers mêmes que la page reçoit
(`control_center_scene_layout.js`, `control_center_scene_interact.js`), la page
étant remplacée par ce qu'elle fait du DOM : `transform` porte la place (ou
l'aperçu), `translate` le tour — interpolé entre les 64 images-clés comme le
navigateur le fait, figé pendant la tenue — ou le décalage fixe d'un objet
immobile rapproché par l'ampleur. La mesure se prend sur ce dessin, jamais sur
les paramètres d'où il sort.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

import pytest

RUNTIME = Path(__file__).resolve().parents[2] / "jarvis" / "runtime"
LAYOUT_JS = RUNTIME / "control_center_scene_layout.js"
INTERACT_JS = RUNTIME / "control_center_scene_interact.js"

SCREENS = [(1280, 720), (1920, 1080), (2560, 1080), (2560, 1440)]

#: Le DOM de la page, réduit à ce qui place un nœud, et les trois chemins
#: d'entrée tels que la page les compose (`beginHold`, `showHold`,
#: `commitHold`, `frames`, `keyAdjust`).
PRELUDE = r"""
const L=require(PATHS.layout),I=require(PATHS.interact);
const STEPS=L.orbitSteps();
const hyp=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y);
/* Ce que le navigateur dessine : le décalage `translate` d'un nœud à la
   fraction `turn` de la période — l'animation interpolée entre deux images-clés
   (phase comprise), ou le décalage fixe d'un objet immobile. */
function translateOf(node,field,turn){
  const track=L.orbitTrack(node,field);
  if(track){
    const local=(((turn-track.delayMs/field.ms)%1)+1)%1;
    const t=local*L.ORBIT_STEPS,k=Math.min(L.ORBIT_STEPS-1,Math.floor(t)),f=t-k;
    const a=STEPS[k],b=STEPS[k+1];
    return {x:(a.x+(b.x-a.x)*f)*track.rx-track.dx,y:(a.y+(b.y-a.y)*f)*track.ry-track.dy};
  }
  const rest=L.orbitRest(node,field);
  return rest?{x:rest.x,y:rest.y}:{x:0,y:0};
}
/* Une scène d'un ou plusieurs objets, rendue : le champ (qui tourne
   vraiment, ou `null`), et le centre dessiné de chaque nœud. */
function scene(W,H,objects,{gain=1,gravity=true,turn=0}={}){
  const vp=L.viewport(W,H);
  const nodes=objects.map(o=>({id:o.id,...L.nodeGeometry(vp,o.representation,o.box)}));
  const field=gravity?L.orbitField(nodes,vp,{gain,rate:1}):null;
  const drawn=id=>{const n=nodes.find(n=>n.id===id);const t=translateOf(n,field,turn);return {x:n.cx+t.x,y:n.cy+t.y}};
  return {vp,nodes,field,turn,drawn,objects};
}
/* La page prend : les nœuds sont tenus (le champ se fige), leur `translate`
   reste celui de la prise, et la tenue commence. */
function grab(sc,ids,controls){
  const members=ids.map(id=>{const o=sc.objects.find(o=>o.id===id);return {id,representation:o.representation,box:o.box}});
  const hold=I.createHold({layout:L,vp:sc.vp,field:sc.field,turn:sc.turn,area:I.holdArea(sc.vp,controls||[]),members});
  const frozen=new Map(ids.map(id=>{const n=sc.nodes.find(n=>n.id===id);return [id,translateOf(n,sc.field,sc.turn)]}));
  const at=new Map(ids.map(id=>[id,sc.drawn(id)]));
  /* Ce que l'écran montre de l'objet tenu : l'aperçu dans `transform`, le
     décalage figé dans `translate`. */
  const shown=id=>{const o=members.find(m=>m.id===id);const n=L.nodeGeometry(sc.vp,o.representation,hold.preview(id));
    const t=frozen.get(id);return {x:n.cx+t.x,y:n.cy+t.y,box:{left:n.box.left+t.x,top:n.box.top+t.y,width:n.box.width,height:n.box.height}}};
  return {hold,shown,at,members};
}
/* Le lâcher et le rendu qui suit : la place part (attente optimiste, épingle),
   le champ est recalculé sur la nouvelle scène, le tour reprend où il était. */
function drop(sc,g,id){
  const place=g.hold.place(id);
  const objects=sc.objects.map(o=>o.id===id?{...o,box:place}:o);
  const next=scene(sc.vp.width,sc.vp.height,objects,{gain:sc.field?sc.field.scale:1,gravity:!!sc.field,turn:sc.turn});
  return {place,next,drawn:next.drawn(id)};
}
/* L'étendue dessinée d'une boîte tenue (repère du dessin, unités) est-elle
   dans l'aire ? */
function inside(area,box,representation){
  const d=L.drawnBox(representation,box),e=1e-6;
  if(d.x<area.x0-e||d.y<area.y0-e||d.x+d.w>area.x1+e||d.y+d.h>area.y1+e)return false;
  return !area.obstacles.some(o=>o.x0<d.x+d.w-e&&o.x1>d.x+e&&o.y0<d.y+d.h-e&&o.y1>d.y+e);
}
/* Les trois entrées, composées comme la page les compose. */
const DEVICES={
  /* Souris : l'écart du pointeur depuis l'appui, converti une fois. */
  mouse(sc,g,id,dx,dy){g.hold.moveBy(I.pxToUnits(sc.vp,dx,dy))},
  /* Bare Hands : le moteur calcule dans la boîte que `frames.begin` lui a
     rendue (`hold.start`), puis `frames.preview(id, box, mode)`. */
  hands(sc,g,id,dx,dy){
    const box=I.manipulateBox({start:g.hold.start(id),representation:g.members[0].representation,mode:'move',
      axes:['x','y'],deltaPx:{dx,dy},vp:sc.vp});
    g.hold.to(id,box,'move');
  },
};
"""


def run_node(tmp_path: Path, body: str, data: Any = None) -> Any:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    paths = {"layout": str(LAYOUT_JS), "interact": str(INTERACT_JS)}
    index = len(list(tmp_path.glob("scene-hold-*.cjs")))
    data_file = tmp_path / f"scene-hold-{index}.json"
    data_file.write_text(json.dumps(data), encoding="utf-8")
    script = tmp_path / f"scene-hold-{index}.cjs"
    script.write_text(
        f"const PATHS={json.dumps(paths)};\n"
        f"const D=JSON.parse(require('fs').readFileSync({json.dumps(str(data_file))},'utf8'));\n"
        + PRELUDE
        + "(async()=>{\n" + body + "\n})().then(v=>console.log(JSON.stringify(v)),e=>{console.error(e&&e.stack||e);process.exit(1)});\n",
        encoding="utf-8",
    )
    result = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


#: Le balayage commun : un geste par cas, mesuré pendant, au lâcher et à la
#: reprise. Renvoie le pire écart de chaque clause et le cas qui l'a produit.
SWEEP = r"""
function sweep(cases,device){
  const worst={during:0,drop:0,regrab:0,escaped:0,tracked:0,walled:0};
  const where={};
  const note=(key,value,info)=>{if(value>worst[key]){worst[key]=value;where[key]=info}};
  for(const c of cases){
    const obj={id:'a',representation:c.rep,box:c.box};
    const sc=scene(c.W,c.H,[obj],{gain:c.gain,gravity:c.gravity,turn:c.turn});
    const g=grab(sc,['a'],c.controls);
    const area=I.holdArea(sc.vp,c.controls||[]);
    const at=g.at.get('a');
    let last=null;
    for(const [dx,dy] of c.moves){
      device(sc,g,'a',dx,dy);
      const shown=g.shown('a');
      const wanted=I.dragBox(g.hold.start('a'),dx/sc.vp.scale,dy/sc.vp.scale);
      if(inside(area,wanted,c.rep)){
        worst.tracked++;
        note('during',hyp(shown,{x:at.x+dx,y:at.y+dy}),{...c,dx,dy});
      }else{
        worst.walled++;
        /* Arrêté : jamais au-delà de l'écran visible ni sous une commande. */
        if(!inside(area,g.hold.drawn('a'),c.rep))note('escaped',1,{...c,dx,dy});
      }
      last=shown;
    }
    const after=drop(sc,g,'a');
    note('drop',hyp(after.drawn,last),{...c,place:after.place});
    /* Reprise : 5 px vers le centre de l'écran, pour ne pas buter sur un bord. */
    const sc2=after.next,g2=grab(sc2,['a'],c.controls),at2=g2.at.get('a');
    const step=at2.x>sc2.vp.cx?-5:5;
    DEVICES.mouse(sc2,g2,'a',step,0);
    note('regrab',hyp(g2.shown('a'),{x:at2.x+step,y:at2.y}),{...c,place:after.place});
  }
  return {worst:Object.fromEntries(Object.entries(worst).map(([k,v])=>[k,Math.round(v*100)/100])),where};
}
function cases(){
  const out=[];
  const shapes=[
    ['point',{x:97,y:-3,w:6,h:6}],            // étoile admissible, loin du centre
    ['point',{x:-95.1,y:-42.9,w:6,h:6}],      // hors de son ellipse (scène réelle de l'utilisateur)
    ['point',{x:-3,y:-3,w:6,h:6}],            // sur le visage
    ['capsule',{x:-140,y:55,w:40,h:7}],       // capsule en bas à gauche
    ['capsule',{x:-20,y:-20,w:40,h:40}],      // capsule plus haute que son maximum
    ['window',{x:57.7,y:-65.2,w:64,h:40}],    // fenêtre
    ['window',{x:90,y:-12,w:40,h:24}],        // petite fenêtre, dessinée en capsule à 1280×720
  ];
  const moves=[[60,0],[150,40],[300,-80],[-600,100],[-900,-500],[1500,0],[20,700],[5,0]];
  for(const [W,H] of D.screens)for(const turn of [0,.25,.5])for(const gain of [.5,1,1.3])for(const gravity of [true,false]){
    if(!gravity&&(gain!==1||turn!==0))continue;
    for(const [rep,box] of shapes)out.push({W,H,turn,gain,gravity,rep,box,moves});
  }
  return out;
}
"""


def _assert_contract(result: dict[str, Any]) -> None:
    worst, where = result["worst"], result["where"]
    assert worst["tracked"] > 1000 and worst["walled"] > 100, worst
    assert worst["during"] <= 1.0, where.get("during")
    assert worst["escaped"] == 0, where.get("escaped")
    assert worst["drop"] <= 1.0, where.get("drop")
    assert worst["regrab"] <= 1.0, where.get("regrab")


def test_a_mouse_drag_keeps_the_drawn_object_under_the_pointer_and_where_it_was_dropped(tmp_path):
    """Clauses 1 à 3, à la souris : 4 écrans × 3 phases du tour × 3 ampleurs,
    gravitation allumée et éteinte, sept formes, huit gestes chacun — des petits,
    des grands, et d'autres qui partent au-delà du bord.

    Avant le 22/09/2026 : au demi-tour, une étoile tirée vers la droite
    s'arrêtait à 24 px de sa prise (l'ellipse bornait la place non tournée) ;
    gravitation éteinte, une étoile ne dépassait pas +624 px sur 960 en 1080p ;
    et une place déjà hors ellipse sautait de 467 px à la première prise."""

    result = run_node(tmp_path, SWEEP + "return sweep(cases(),DEVICES.mouse);", {"screens": SCREENS})
    _assert_contract(result)


def test_a_bare_hands_move_goes_through_the_same_hold_and_is_committed_where_it_was_dropped(tmp_path):
    """Les mêmes cas, par `JarvisScene.frames` : `begin` rend la boîte
    **dessinée**, le moteur calcule dedans (`manipulateBox`), `preview` et
    `commit` passent par la même tenue que la souris.

    Avant : `frames.commit` enregistrait la boîte telle quelle, sans défaire le
    tour — 300 à 417 px de saut au lâcher, en miroir du geste."""

    result = run_node(tmp_path, SWEEP + "return sweep(cases(),DEVICES.hands);", {"screens": SCREENS})
    _assert_contract(result)


def test_the_keyboard_moves_from_where_the_object_is_drawn_and_lands_there(tmp_path):
    """Maj+flèches, comme la page les compose (`keyAdjust`) : chaque pas part
    de l'objet dessiné, la tenue borne, et le lâcher (`flushKeyEdit`) passe par
    la même place que la souris. Avant : la boîte dessinée était enregistrée
    sans défaire le tour, et le champ tournait sous l'aperçu."""

    result = run_node(tmp_path, r"""
      const out={drop:0,step:0,cases:0};
      const k=(key,mods)=>I.keyIntent({key,...(mods||{})});
      const keys=[k('ArrowRight',{shiftKey:true}),k('ArrowDown',{shiftKey:true,ctrlKey:true}),k('ArrowLeft',{shiftKey:true}),
        k('ArrowUp',{shiftKey:true,ctrlKey:true}),k('ArrowRight',{shiftKey:true,ctrlKey:true})];
      for(const [W,H] of D.screens)for(const turn of [0,.25,.5])for(const gain of [.5,1,1.3])
      for(const [rep,box] of [['point',{x:40,y:-20,w:6,h:6}],['capsule',{x:20,y:-30,w:40,h:7}],['point',{x:-95.1,y:-42.9,w:6,h:6}]]){
        out.cases++;
        const sc=scene(W,H,[{id:'a',representation:rep,box}],{gain,turn});
        const g=grab(sc,['a']);
        const at=g.at.get('a');let expected={...at};
        for(const intent of keys){
          const drawn=g.hold.drawn('a'),start=g.hold.start('a');
          const wanted=I.applyKey(drawn,intent,rep);
          g.hold.moveBy({dx:wanted.x-start.x,dy:wanted.y-start.y});
          expected={x:expected.x+intent.dx*sc.vp.scale,y:expected.y+intent.dy*sc.vp.scale};
          out.step=Math.max(out.step,hyp(g.shown('a'),expected));
        }
        const last=g.shown('a'),after=drop(sc,g,'a');
        out.drop=Math.max(out.drop,hyp(after.drawn,last));
      }
      return out;
    """, {"screens": SCREENS})
    assert result["cases"] == 108
    assert result["step"] <= 1.0
    assert result["drop"] <= 1.0


def test_a_capsule_resized_at_any_turn_stays_where_its_handle_left_it(tmp_path):
    """Poignée de la souris (`resizeBox`) et côtés de Bare Hands
    (`manipulateBox` en `resize`), capsule tournante, à 1/8, 1/4 et 1/2 tour.
    Avant : la boîte redimensionnée était enregistrée sans défaire le tour, et
    la capsule repartait d'un quart ou d'un demi-tour au lâcher."""

    result = run_node(tmp_path, r"""
      const out={box:0,cases:0};
      for(const [W,H] of D.screens)for(const turn of [.125,.25,.5])for(const gain of [.5,1,1.3])
      for(const path of ['mouse','hands']){
        out.cases++;
        const sc=scene(W,H,[{id:'a',representation:'capsule',box:{x:20,y:-30,w:40,h:7}}],{gain,turn});
        const g=grab(sc,['a']);
        for(const [dx,dy] of [[60,0],[120,12],[240,12]]){
          const u=I.pxToUnits(sc.vp,dx,dy);
          if(path==='mouse')g.hold.resizeTo('a',I.resizeBox(g.hold.start('a'),u.dx,u.dy,'capsule'));
          else g.hold.to('a',I.manipulateBox({start:g.hold.start('a'),representation:'capsule',mode:'resize',
            axes:['x','y'],sidesPx:{right:dx,bottom:dy},vp:sc.vp}),'resize');
        }
        const last=g.shown('a').box,after=drop(sc,g,'a');
        const n=after.next.nodes[0],t=translateOf(n,after.next.field,turn);
        const box={left:n.box.left+t.x,top:n.box.top+t.y,width:n.box.width,height:n.box.height};
        out.box=Math.max(out.box,Math.abs(box.left-last.left),Math.abs(box.top-last.top),
          Math.abs(box.width-last.width),Math.abs(box.height-last.height));
      }
      return out;
    """, {"screens": SCREENS})
    assert result["cases"] == 72
    assert result["box"] <= 1.0


def test_the_only_walls_are_the_visible_screen_and_the_controls_actually_there(tmp_path):
    """« Je me tape des murs invisibles. » Une étoile va jusqu'aux quatre coins
    de l'écran **visible** — pas de la zone sûre, calibrée pour 1280 × 720, qui
    laissait 132 à 452 px interdits aux bords d'un grand écran, ni de l'ellipse
    du tour. Une commande présente arrête l'objet contre elle, et seulement là
    où elle est : à côté, le bord de l'écran reste atteignable."""

    result = run_node(tmp_path, r"""
      const out={};
      for(const [W,H] of D.screens){
        const sc=scene(W,H,[{id:'a',representation:'point',box:{x:10,y:10,w:6,h:6}}],{turn:.5});
        const reach=[];
        for(const [dx,dy] of [[-4000,-4000],[4000,-4000],[4000,4000],[-4000,4000]]){
          const g=grab(sc,['a']);
          DEVICES.mouse(sc,g,'a',dx,dy);
          const b=g.shown('a').box;
          reach.push(Math.round(Math.max(Math.min(b.left,W-b.left-b.width),Math.min(b.top,H-b.top-b.height))*10)/10);
        }
        out[`${W}x${H}`]=reach;
      }
      /* Une commande en bas au centre (l'indication vocale, 300 × 40 px). */
      const W=1920,H=1080,hint={left:810,top:1018,width:300,height:40};
      const sc=scene(W,H,[{id:'a',representation:'point',box:{x:-3,y:40,w:6,h:6}}]);
      const under=grab(sc,['a'],[hint]);DEVICES.mouse(sc,under,'a',0,2000);
      const beside=grab(sc,['a'],[hint]);DEVICES.mouse(sc,beside,'a',-600,2000);
      /* Glisser le long du bas jusque sous la commande : arrêté contre son flanc. */
      const along=grab(sc,['a'],[hint]);DEVICES.mouse(sc,along,'a',-600,2000);DEVICES.mouse(sc,along,'a',0,2000);
      const bottom=b=>Math.round((b.top+b.height)*10)/10,right=b=>Math.round((b.left+b.width)*10)/10;
      out.hint={underBottom:bottom(under.shown('a').box),besideBottom:bottom(beside.shown('a').box),
        alongRight:right(along.shown('a').box),hintTop:hint.top,hintLeft:hint.left};
      return out;
    """, {"screens": SCREENS})
    for key, reach in result.items():
        if key == "hint":
            continue
        # Chaque coin à moins d'un pixel du bord réel de l'écran.
        assert all(r <= 1.0 for r in reach), (key, reach)
    hint = result["hint"]
    assert hint["underBottom"] <= hint["hintTop"] + 1  # arrêté contre la commande
    assert hint["besideBottom"] >= 1080 - 1             # à côté d'elle : le bas de l'écran
    assert hint["alongRight"] <= hint["hintLeft"] + 1   # le long du bas : arrêté contre son flanc


def test_an_object_already_under_a_control_or_off_screen_is_not_pulled_in_at_the_grab(tmp_path):
    """Une place posée hors de l'écran (cerveau) ou sous une commande ne fait
    pas sauter l'objet à la prise : la borne l'empêche seulement d'aller plus
    loin, elle ne le rabat pas."""

    result = run_node(tmp_path, r"""
      const W=1920,H=1080,bar={left:0,top:0,width:1920,height:60};
      const out={};
      for(const [name,box,controls] of [['offRight',{x:170,y:0,w:6,h:6},[]],['underBar',{x:0,y:-90,w:6,h:6},[bar]]]){
        const sc=scene(W,H,[{id:'a',representation:'point',box}],{gravity:false});
        const g=grab(sc,['a'],controls),at=g.at.get('a');
        DEVICES.mouse(sc,g,'a',-5,5);
        const back=hyp(g.shown('a'),{x:at.x-5,y:at.y+5});
        const g2=grab(sc,['a'],controls);DEVICES.mouse(sc,g2,'a',40,-40);
        const further=g2.shown('a');
        out[name]={back:Math.round(back*100)/100,furtherX:Math.round((further.x-at.x)*10)/10,furtherY:Math.round((further.y-at.y)*10)/10};
      }
      return out;
    """)
    assert result["offRight"]["back"] <= 1.0 and result["underBar"]["back"] <= 1.0
    # Plus loin dehors : retenu sur l'axe qui sort, libre sur l'autre.
    assert result["offRight"]["furtherX"] == 0 and result["offRight"]["furtherY"] == -40
    assert result["underBar"]["furtherY"] == 0 and result["underBar"]["furtherX"] == 40


def test_a_selection_moves_as_one_block_and_stops_together(tmp_path):
    """Plusieurs objets emmenés : le même écart pour tous, et quand l'un touche
    le bord, **tous** s'arrêtent — chacun s'arrêtant sur son propre bord, la
    sélection se déformait. Chaque membre est posé au lâcher là où il était
    dessiné, quel que soit le tour."""

    result = run_node(tmp_path, r"""
      const objects=[{id:'a',representation:'point',box:{x:100,y:0,w:6,h:6}},
        {id:'b',representation:'capsule',box:{x:-60,y:30,w:40,h:7}},{id:'c',representation:'window',box:{x:-100,y:-60,w:64,h:40}}];
      const sc=scene(1920,1080,objects,{turn:.37,gain:.8});
      const g=grab(sc,['a','b','c']);
      const gap=()=>{const a=g.shown('a'),b=g.shown('b'),c=g.shown('c');return [b.x-a.x,b.y-a.y,c.x-a.x,c.y-a.y]};
      const before=gap();
      DEVICES.mouse(sc,g,'a',3000,0);
      const after=gap();
      const shown=Object.fromEntries(['a','b','c'].map(id=>[id,g.shown(id)]));
      let drop=0;let cur=sc;
      for(const id of ['a','b','c']){
        const place=g.hold.place(id);
        cur={...cur,objects:cur.objects.map(o=>o.id===id?{...o,box:place}:o)};
      }
      const next=scene(1920,1080,cur.objects,{turn:.37,gain:.8});
      for(const id of ['a','b','c'])drop=Math.max(drop,hyp(next.drawn(id),shown[id]));
      /* Le tour a pu mettre n'importe lequel des trois le plus à droite : c'est
         lui qui touche le bord, et les autres s'arrêtent avec lui. */
      const right=Math.max(...['a','b','c'].map(id=>shown[id].box.left+shown[id].box.width));
      return {deform:Math.max(...before.map((v,i)=>Math.abs(v-after[i]))),drop,rightEdge:Math.round(right*10)/10};
    """)
    assert result["deform"] <= 0.01
    assert result["rightEdge"] == pytest.approx(1920, abs=1)
    assert result["drop"] <= 1.0


def test_an_object_whose_turn_does_not_fit_stays_still_instead_of_being_walled(tmp_path):
    """Un objet dont le tour ne tient pas à sa place **ne tourne pas** : il
    n'est plus ramené sur son ellipse. La décision se lit sur la forme dessinée
    (une petite fenêtre dessinée en capsule tourne), la même partout, et le
    champ ne dépend pas de la place des objets."""

    result = run_node(tmp_path, r"""
      /* Le nœud tel que le modèle de vue le fabrique, écrit avec les seules
         fonctions qui existaient avant la tenue : ce test lit le même contrat
         sur l'ancien code et sur le nouveau. */
      const nodeIn=(vp,rep,box)=>{const s=L.toScreen(vp,L.drawnBox(rep,box)),shape=L.compactShape(rep,s);
        return {representation:rep,shape,compact:shape!==rep,box:s,cx:Math.round((s.left+s.width/2)*10)/10,cy:Math.round((s.top+s.height/2)*10)/10}};
      const vp=L.viewport(1920,1080);
      const node=(rep,box)=>nodeIn(vp,rep,box);
      const field=L.orbitField([node('point',{x:20,y:0,w:6,h:6})],vp);
      /* Une petite fenêtre que la page dessine en capsule, et dont le tour tient. */
      const small=nodeIn(L.viewport(1280,720),'window',{x:10,y:-12,w:40,h:24});
      return {
        fits:!!L.orbitTrack(node('point',{x:40,y:-20,w:6,h:6}),field),
        outside:L.orbitTrack(node('point',{x:-95.1,y:-42.9,w:6,h:6}),field),
        centre:L.orbitTrack(node('point',{x:-3,y:-3,w:6,h:6}),field),
        smallShape:small.shape,
        smallTurns:!!L.orbitTrack(small,L.orbitField([small],L.viewport(1280,720))),
        onlyOutside:!!L.orbitField([node('point',{x:140,y:70,w:6,h:6})],vp),
        dragged:I.dragBox({x:97,y:-3,w:6,h:6},200,0),
      };
    """)
    assert result["fits"] is True
    assert result["outside"] is None
    # Sur le visage : un tour de rayon nul, sans cas particulier.
    assert result["centre"]["rx"] == 0 and result["centre"]["ry"] == 0
    assert result["smallShape"] == "capsule" and result["smallTurns"] is True
    # Le champ existe dès qu'une forme peut tourner, où qu'elle soit.
    assert result["onlyOutside"] is True
    # Déplacer ne borne plus rien : c'est la tenue qui connaît l'écran.
    assert result["dragged"] == {"x": 297, "y": -3, "w": 6, "h": 6}


def test_below_unit_amplitude_every_point_of_the_screen_has_exactly_one_place(tmp_path):
    """L'ampleur sous 1 dessine un objet qui tourne à `ampleur × rayon` ; un
    objet immobile dessiné à sa place laisserait une couronne que personne ne
    peut atteindre — l'objet lâché là sauterait. Le rapprochement des objets
    immobiles (`orbitRest`) la referme : pour tout point dessiné, la place rendue
    par `holdPlace` est redessinée sur ce point."""

    result = run_node(tmp_path, r"""
      let worst=0,count=0;
      for(const gain of [.3,.5,.8,1,1.3])for(const turn of [0,.2,.5,.75]){
        const vp=L.viewport(1920,1080);
        const field=L.orbitField([L.nodeGeometry(vp,'point',{x:0,y:0,w:6,h:6})],vp,{gain});
        for(let x=-155;x<=150;x+=5)for(let y=-85;y<=80;y+=5){
          const held={x,y,w:6,h:6};
          const place=L.holdPlace(vp,'point',held,field,turn);
          const want=L.nodeGeometry(vp,'point',held),got=L.orbitDrawnPoint(L.nodeGeometry(vp,'point',place),field,turn);
          worst=Math.max(worst,Math.hypot(got.x-want.cx,got.y-want.cy));count++;
        }
      }
      return {worst:Math.round(worst*100)/100,count};
    """)
    assert result["count"] > 30000
    assert result["worst"] <= 1.0


def test_rewriting_a_node_content_never_drops_its_gesture_or_orbit_state(tmp_path):
    """`fill` réécrit le contenu d'un nœud — et le premier lâcher d'un objet non
    épinglé change son contenu (l'épingle). Il retirait `sc-settling`, et la
    transition de 420 ms rejouait une excursion de 200 à 400 px ; pendant une
    tenue, il retirait `sc-dragging` et `sc-orbit` (l'objet sautait de son
    décalage sous la main)."""

    result = run_node(tmp_path, r"""
      const current=['sc-node','sc-point','sc-kind-agent','sc-tone-agent','sc-exec-running','sc-orbit','sc-settling','sc-dragging','sc-selected','sc-stopping','sc-anim','sc-compact'];
      return L.nodeClassName(['sc-node','sc-point','sc-kind-agent','sc-tone-agent','sc-exec-completed','sc-pinned'],current).split(' ');
    """)
    for kept in ("sc-orbit", "sc-settling", "sc-dragging", "sc-selected", "sc-stopping", "sc-anim"):
        assert kept in result
    # Le contenu, lui, est remplacé : l'ancien état d'exécution et la forme compacte partent.
    assert "sc-exec-running" not in result and "sc-compact" not in result
    assert "sc-exec-completed" in result and "sc-pinned" in result
    assert len(result) == len(set(result))

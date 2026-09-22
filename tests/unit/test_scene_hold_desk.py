"""Le bureau des tenues (`I.createHoldDesk`) et l'heure du champ
(`I.createFieldClock`), cinquième tour de QA du déplacement 2D (22/09/2026).

La QA a mesuré, sur d6155b8 :

1. reprendre un objet **pendant son dégel** (clic de 120 ms, nouvel appui
   80 ms plus tard, glissement) : l'objet restait collé ~290 ms puis sautait
   de 92 à 144 px — l'animation du dégel écrasait l'aperçu, et la prise partait
   de la place calculée au lieu de ce qui était affiché ;
2. un drapeau de dégel laissé posé (main puis souris sur le même objet, la
   main annulée) : le premier aperçu le consommait, l'objet restait figé
   ~400 ms puis sautait jusqu'à 137 px ;
3. une refonte (fenêtre redimensionnée pendant la tenue) gardait le centre et
   pas le point saisi (56 px pour une fenêtre saisie à 12 % / 15 %), et un
   pointeur sorti de la fenêtre réduite laissait 442 à 496 px d'écart
   permanent à son retour.

Tout ce que la page faisait des tenues vit maintenant dans le bureau, sans DOM ;
la page ne garde que les événements et l'écriture des styles. Ces tests
composent le bureau **avec une page réduite à ce qu'elle dessine** (`PAGE`) :
`transform` porte la place ou l'aperçu, `translate` le tour, ou l'écart figé
d'un objet tenu (`sc-held`), et une animation de `transform` le dégel —
interpolée comme le navigateur le fait. La mesure se prend sur ce dessin.
"""

from __future__ import annotations

from pathlib import Path

from tests.unit.test_scene_hold_contract import SCREENS, run_node

PAGE_JS = Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center_scene_page.js"

#: La page, réduite à ce qu'elle dessine et à ce qu'elle dit au bureau.
PAGE = r"""
const cssEase=t=>{let lo=0,hi=1;
  for(let i=0;i<40;i++){const m=(lo+hi)/2,x=3*.42*m*(1-m)**2+3*.58*m*m*(1-m)+m**3;if(x<t)lo=m;else hi=m}
  const m=(lo+hi)/2;return 3*m*m*(1-m)+m**3};
function page(W,H,objects,{gain=1,gravity=true,rate=1,t0=1790003799000,controls=[]}={}){
  const P={now:t0,vp:L.viewport(W,H),controls,measured:0,sent:[],desync:new Map()};
  const boxes=new Map(objects.map(o=>[o.id,{...o.box}])),reps=new Map(objects.map(o=>[o.id,o.representation]));
  const nodeAt=(vp,id)=>({id,...L.nodeGeometry(vp,reps.get(id),boxes.get(id))});
  const fieldFor=vp=>gravity?L.orbitField([...boxes.keys()].map(id=>nodeAt(vp,id)),vp,{gain,rate}):null;
  P.field=fieldFor(P.vp);
  /* L'élément de chaque nœud : figé (`sc-held` + `translate`), l'aperçu
     (`transform`), le dégel en cours (animation de `transform`), posé ou non. */
  const els=new Map([...boxes.keys()].map(id=>[id,{held:false,frozen:null,preview:null,anim:null,placed:true}]));
  P.els=els;
  const view={
    hold(id,on){const e=els.get(id);e.held=on;if(!on)e.placed=false},
    freeze(id,translate){const [x,y]=translate.split(' ').map(parseFloat);els.get(id).frozen={x,y}},
    preview(id,box){els.get(id).preview={...box}},
    stopThaw(id){els.get(id).anim=null;P.desk.thawEnded(id)},
  };
  P.desk=I.createHoldDesk({layout:L,now:()=>P.now,field:()=>P.field,fieldFor,viewport:()=>P.vp,
    controls:()=>{P.measured++;return P.controls},
    node:id=>boxes.has(id)?{node:nodeAt(P.vp,id),box:{...boxes.get(id)},representation:reps.get(id)}:null,
    /* Ce que l'animation d'un nœud libre dessine, lu sur elle (`shownOffset`). */
    shown:id=>{const e=els.get(id),n=nodeAt(P.vp,id);if(e.held||e.frozen||e.anim||!P.field||!L.orbitTrack(n,P.field))return undefined;
      return translateOf(n,P.field,L.orbitTurnAt(P.now+(P.desync.get(id)||0),P.field))},
    view,commit:(id,box,kind)=>{boxes.set(id,{...box});els.get(id).placed=false;P.sent.push({id,box,kind});return Promise.resolve()},
    log:()=>{}});
  /* `position()` de la page : le nœud posé à sa place, le tour repris, le
     dégel éventuel lancé (`desk.positioned`). */
  function position(id){
    const e=els.get(id),n=nodeAt(P.vp,id);
    if(e.anim)view.stopThaw(id);
    e.frozen=null;e.preview=null;e.placed=true;P.desync.delete(id);   // reposé : remis à l'heure (`syncOrbit`)
    const spec=P.desk.positioned(id,n,L.drawnRect(n));
    if(spec)e.anim={start:P.now,duration:spec.duration,delta:spec.delta,keyframes:spec.keyframes};
  }
  /* Un rendu : le champ, la refonte éventuelle, les nœuds libres reposés. */
  P.render=()=>{P.field=fieldFor(P.vp);P.desk.refresh();for(const [id,e] of els)if(!e.held&&!e.placed)position(id)};
  P.tick=ms=>{P.now+=ms};
  P.frames=(ms,each)=>{for(let t=0;t<ms;t+=16){P.tick(16);P.render();if(each)each()}};
  /* Ce que l'écran montre : le centre dessiné et le rectangle dessiné (px). */
  P.shown=id=>{
    const e=els.get(id);
    if(e.frozen){
      const n=L.nodeGeometry(P.vp,reps.get(id),e.preview||boxes.get(id)),r=L.drawnRect(n);
      return {x:n.cx+e.frozen.x,y:n.cy+e.frozen.y,rect:{left:r.left+e.frozen.x,top:r.top+e.frozen.y,width:r.width,height:r.height},
        box:{left:n.box.left+e.frozen.x,top:n.box.top+e.frozen.y,width:n.box.width,height:n.box.height}};
    }
    const n=nodeAt(P.vp,id),t=P.field?translateOf(n,P.field,L.orbitTurnAt(P.now+(P.desync.get(id)||0),P.field)):{x:0,y:0};
    let lift={x:0,y:0};
    if(e.anim){
      const k=(P.now-e.anim.start)/e.anim.duration;
      if(k>=1){e.anim=null;P.desk.thawEnded(id)}
      else{const f=1-cssEase(k);lift={x:e.anim.delta.x*f,y:e.anim.delta.y*f}}
    }
    const r=L.drawnRect(n);
    const u={x:t.x+lift.x,y:t.y+lift.y};
    return {x:n.cx+u.x,y:n.cy+u.y,rect:{left:r.left+u.x,top:r.top+u.y,width:r.width,height:r.height},
      box:{left:n.box.left+u.x,top:n.box.top+u.y,width:n.box.width,height:n.box.height}};
  };
  P.box=id=>({...boxes.get(id)});
  return P;
}
/* Le point de l'objet dessiné à la fraction (fx, fy) de son rectangle. */
const at=(P,id,fx,fy)=>{const r=P.shown(id).rect;return {x:r.left+fx*r.width,y:r.top+fy*r.height}};
/* Le même, dans la boîte de l'objet (px) : une fenêtre devenue pilule
   compacte à la petite taille garde sa boîte, pas son dessin. */
const inBox=(P,id,fx,fy)=>{const b=P.shown(id).box;return {x:b.left+fx*b.width,y:b.top+fy*b.height}};
const within=(p,r)=>p.x>=r.left-.5&&p.x<=r.left+r.width+.5&&p.y>=r.top-.5&&p.y<=r.top+r.height+.5;
const OBJECTS=[{id:'p',representation:'point',box:{x:40,y:-20,w:6,h:6}},
  {id:'c',representation:'capsule',box:{x:-40,y:30,w:40,h:7}},
  {id:'w',representation:'window',box:{x:10,y:10,w:30,h:20}}];
"""


def run_desk(tmp_path: Path, body: str, data=None):
    return run_node(tmp_path, PAGE + body, data)


def test_1_a_new_hold_during_a_thaw_starts_from_what_is_shown(tmp_path):
    """Point 1. Clic de 120 ms (le dégel démarre), nouvel appui 80 ms plus
    tard, glissement par pas de 5 px : à l'appui l'objet ne bouge pas, et
    pendant tout le glissement le point saisi reste sous le pointeur (≤ 1 px) —
    le dégel est arrêté par la prise, rien ne l'écrase ensuite. Souris,
    clavier et Bare Hands ; vitesses 1 et 4 ; ampleurs .5, 1 et 1,3."""

    result = run_desk(tmp_path, r"""
      let worst=0,jump=0,animations=0,cases=0,thawed=0;
      for(const [W,H] of D.screens)for(const rate of [1,4])for(const gain of [.5,1,1.3])for(const o of OBJECTS)
      for(const source of ['mouse','key','hand']){
        const P=page(W,H,OBJECTS,{gain,rate});
        P.frames(500);
        const pointer=at(P,o.id,.5,.5);
        const click=P.desk.take('mouse',[o.id],{pointer});
        P.frames(120);
        P.desk.cancel(click);
        P.frames(80);                                             // le dégel est en cours
        if(P.els.get(o.id).anim)thawed++;
        const before=P.shown(o.id),press=at(P,o.id,.5,.5);
        const h=P.desk.take(source,[o.id],{pointer:press});
        const after=P.shown(o.id);
        jump=Math.max(jump,hyp(before,after));
        const scale=P.vp.scale;
        for(let k=1;k<=20;k++){
          let want;
          if(source==='mouse'){P.desk.drag(h,press.x+5*k,press.y+2*k);want={x:before.x+5*k,y:before.y+2*k}}
          else if(source==='key'){const i=I.keyIntent({key:'ArrowRight',shiftKey:true});P.desk.key(h,i);want={x:before.x+i.dx*k*scale,y:before.y}}
          else{const box=I.manipulateBox({start:h.hold.start(o.id),representation:o.representation,mode:'move',axes:['x','y'],
                 deltaPx:{dx:5*k,dy:2*k},vp:P.vp});P.desk.to(h,o.id,box,'move');want={x:before.x+5*k,y:before.y+2*k}}
          P.tick(16);P.render();
          if(P.els.get(o.id).anim)animations++;
          worst=Math.max(worst,hyp(P.shown(o.id),want));
        }
        cases++;
      }
      return {worst,jump,animations,cases,thawed};
    """, {"screens": SCREENS})
    assert result["cases"] == 4 * 2 * 3 * 3 * 3
    assert result["thawed"] > result["cases"] / 3        # la reprise tombe bien pendant un dégel
    assert result["jump"] <= 1.0, result
    assert result["animations"] == 0, result
    assert result["worst"] <= 1.0, result


def test_1_a_take_freezes_what_the_animation_draws_even_when_it_drifted(tmp_path):
    """Point 1, la même règle hors dégel : la prise fige l'objet **là où son
    animation le dessine**. Une animation décalée de l'heure murale (relancée
    par le navigateur, garde de dérive pas encore passée : jusqu'à 30 ms
    tolérées, et bien plus entre deux passes) faisait sauter l'objet à
    l'appui — 9 à 18 px mesurés à la vitesse 4 — quand la page remettait tout
    à l'heure pour calculer la prise."""

    result = run_desk(tmp_path, r"""
      let jump=0,follow=0,cases=0;
      for(const [W,H] of D.screens)for(const lag of [-400,-30,25,700])for(const o of OBJECTS){
        const P=page(W,H,OBJECTS,{rate:4,gain:1.3});
        P.frames(300);
        P.desync.set(o.id,lag);
        const before=P.shown(o.id),press=at(P,o.id,.5,.5);
        const h=P.desk.take('mouse',[o.id],{pointer:press});
        jump=Math.max(jump,hyp(P.shown(o.id),before));
        for(let k=1;k<=10;k++){P.desk.drag(h,press.x+6*k,press.y+3*k);P.tick(16);P.render();
          follow=Math.max(follow,hyp(P.shown(o.id),{x:before.x+6*k,y:before.y+3*k}))}
        cases++;
      }
      return {jump,follow,cases};
    """, {"screens": SCREENS})
    assert result["cases"] == 4 * 4 * 3
    assert result["jump"] <= 0.01, result
    assert result["follow"] <= 1.0, result


def test_1_the_thaw_itself_glides_and_ends_on_the_turn(tmp_path):
    """Le dégel doux lui-même, image par image (60 images/s) : un clic de
    150 ms à la vitesse 1 ne bouge pas l'objet de plus d'un pixel par image ;
    un appui de 500 ms à la vitesse 4 glisse sans à-coup ; à la fin, l'objet
    est sur son tour."""

    result = run_desk(tmp_path, r"""
      const out=[];
      for(const [rate,hold] of [[1,150],[4,500]]){
        const P=page(1920,1080,OBJECTS,{rate,gain:1.3});
        P.frames(200);
        const h=P.desk.take('mouse',['p'],{pointer:at(P,'p',.5,.5)});
        P.frames(hold);
        let prev=P.shown('p'),step=0;
        P.desk.cancel(h);
        let started=false;
        P.frames(800,()=>{const s=P.shown('p');step=Math.max(step,hyp(s,prev));prev=s;started=started||!!P.els.get('p').anim});
        const n={...L.nodeGeometry(P.vp,'point',P.box('p'))},t=translateOf(n,P.field,L.orbitTurnAt(P.now,P.field));
        out.push({rate,step,started,end:hyp(P.shown('p'),{x:n.cx+t.x,y:n.cy+t.y}),left:P.desk.displayed('p')});
      }
      return out;
    """)
    slow, fast = result
    assert slow["started"] and fast["started"]
    assert slow["step"] <= 1.0, slow
    assert fast["step"] <= 2.5, fast
    for row in result:
        assert row["end"] <= 0.01 and row.get("left") is None, row


def test_2_a_thaw_is_never_consumed_by_a_preview_nor_left_behind(tmp_path):
    """Point 2. La main prend, la souris prend le même objet, la main annule :
    l'objet reste tenu par la souris — aucun dégel, aucun drapeau laissé — et
    suit le pointeur ; son lâcher se pose sans animation. Et une annulation
    suivie d'une reprise par la main **dans la même image** ne lance aucun
    dégel."""

    result = run_desk(tmp_path, r"""
      const out=[];
      for(const o of OBJECTS){
        const P=page(1920,1080,OBJECTS,{gain:1.3,rate:4});
        P.frames(300);
        const hand=P.desk.take('hand',[o.id],{});
        P.frames(100);
        const press=at(P,o.id,.5,.5),before=P.shown(o.id);
        const mouse=P.desk.take('mouse',[o.id],{pointer:press});
        P.desk.cancel(hand);
        let worst=0,anim=0;
        for(let k=1;k<=30;k++){
          P.desk.drag(mouse,press.x+4*k,press.y-3*k);P.tick(16);P.render();
          if(P.els.get(o.id).anim)anim++;
          worst=Math.max(worst,hyp(P.shown(o.id),{x:before.x+4*k,y:before.y-3*k}));
        }
        const last=P.shown(o.id);
        P.desk.drop(mouse,'move');P.render();                  // le rendu du lâcher, à la même image
        const dropped=hyp(P.shown(o.id),last);
        P.frames(600,()=>{if(P.els.get(o.id).anim)anim++});
        /* Annulée puis reprise par la main dans la même image. */
        const m2=P.desk.take('mouse',[o.id],{pointer:at(P,o.id,.5,.5)});
        P.frames(200);
        const b2=P.shown(o.id);
        P.desk.cancel(m2);
        const h2=P.desk.take('hand',[o.id],{});
        P.frames(300,()=>{if(P.els.get(o.id).anim)anim++});
        const still=hyp(P.shown(o.id),b2);
        const box=I.manipulateBox({start:h2.hold.start(o.id),representation:o.representation,mode:'move',axes:['x','y'],deltaPx:{dx:30,dy:0},vp:P.vp});
        P.desk.to(h2,o.id,box,'move');P.tick(16);P.render();
        const moved=hyp(P.shown(o.id),{x:b2.x+30,y:b2.y});
        out.push({id:o.id,worst,anim,dropped,still,moved,held:P.desk.heldIds()});
      }
      return out;
    """)
    for row in result:
        assert row["anim"] == 0, row
        assert row["worst"] <= 1.0 and row["dropped"] <= 1.0, row
        assert row["still"] <= 1.0 and row["moved"] <= 1.0, row
        assert row["held"] == [row["id"]], row


def test_3_a_rebase_keeps_the_grabbed_point_and_the_pointer_recaptures(tmp_path):
    """Point 3. La fenêtre du navigateur passe de 1920×1080 à 1280×720 pendant
    la tenue d'un objet saisi hors de son centre (12 % / 15 %) : le point saisi
    reste sous le pointeur. Le pointeur sort de la fenêtre réduite (l'objet
    s'arrête au bord) puis revient : l'objet le rattrape, sans écart. Et si la
    refonte elle-même borne l'objet (pointeur resté hors de la fenêtre
    réduite), le pointeur le rattrape à son retour."""

    result = run_desk(tmp_path, r"""
      const out=[];
      const objs=[{id:'w',representation:'window',box:{x:-20,y:-15,w:40,h:28}},
        {id:'c',representation:'capsule',box:{x:-30,y:5,w:44,h:7}},
        {id:'far',representation:'window',box:{x:60,y:-10,w:30,h:20}}];
      for(const gravity of [true,false])for(const id of ['w','c','far']){
        const P=page(1920,1080,objs,{gravity});
        P.frames(100);
        const press=inBox(P,id,.12,.15);
        const h=P.desk.take('mouse',[id],{pointer:press});
        P.desk.drag(h,press.x+20,press.y+10);
        P.tick(16);P.render();
        const pointer={x:press.x+20,y:press.y+10};
        P.vp=L.viewport(1280,720);
        P.desk.drag(h,pointer.x,pointer.y);P.tick(16);P.render();
        const kept=hyp(inBox(P,id,.12,.15),pointer),under=within(pointer,P.shown(id).rect);
        P.desk.drag(h,1600,pointer.y);P.tick(16);P.render();         // hors de la fenêtre réduite
        const r=P.shown(id).rect;
        const edge=Math.abs(r.left+r.width-1280);
        const back={x:400,y:300};
        P.desk.drag(h,back.x,back.y);P.tick(16);P.render();
        const recaptured=hyp(inBox(P,id,.12,.15),back);
        out.push({id,gravity,kept,under,edge,recaptured});
      }
      return out;
    """)
    for row in result:
        if row["id"] != "far":
            assert row["kept"] <= 1.0 and row["under"], row
        assert row["edge"] <= 1.0, row
        assert row["recaptured"] <= 1.0, row


def test_4_a_drop_on_the_same_place_does_not_animate(tmp_path):
    """Point 4. Un glissement ramené à son point de départ puis lâché : rien ne
    part à Core, et l'objet reste là, sans animation — le lâcher n'est pas un
    abandon."""

    result = run_desk(tmp_path, r"""
      const out=[];
      for(const gravity of [true,false])for(const o of OBJECTS){
        const P=page(1920,1080,OBJECTS,{rate:4,gain:1.3,gravity});
        P.frames(200);
        const press=at(P,o.id,.5,.5);
        const h=P.desk.take('mouse',[o.id],{pointer:press});
        P.desk.drag(h,press.x+30,press.y);P.frames(300);P.desk.drag(h,press.x,press.y);P.tick(16);P.render();
        const last=P.shown(o.id);
        const sent=P.desk.drop(h,'move');
        let anim=0;P.render();if(P.els.get(o.id).anim)anim++;
        out.push({id:o.id,gravity,sent:sent.length,anim,moved:hyp(P.shown(o.id),last),turns:!!P.field&&!!L.orbitTrack(L.nodeGeometry(P.vp,o.representation,o.box),P.field)});
      }
      return out;
    """)
    for row in result:
        # Un objet qui tourne a gardé son dessin pendant que le champ tournait :
        # sa place a changé et part ; un objet immobile retombe sur la sienne.
        assert row["sent"] == (1 if row["turns"] else 0), row
        assert row["anim"] == 0 and row["moved"] <= 1.0, row


def test_5_the_controls_are_measured_once_per_change_not_per_move(tmp_path):
    """Point 5. Les commandes de la page ne sont mesurées qu'à la prise et
    quand elles ont changé (`controlsChanged` : redimensionnement, observateur
    de taille) — pas à chaque mouvement. Et une commande apparue pendant le
    geste borne bien la suite."""

    result = run_desk(tmp_path, r"""
      const P=page(1920,1080,OBJECTS);
      const press=at(P,'w',.5,.5);
      const h=P.desk.take('mouse',['w'],{pointer:press});
      const afterTake=P.measured;
      for(let k=1;k<=40;k++){P.desk.drag(h,press.x+k,press.y);P.tick(16);P.render()}
      const afterMoves=P.measured;
      P.controls=[{left:0,top:0,width:1920,height:400}];
      P.desk.controlsChanged();
      P.desk.drag(h,press.x+41,press.y-2000);P.tick(16);P.render();
      for(let k=1;k<=10;k++)P.desk.drag(h,press.x+41,press.y-2000-k);
      return {afterTake,afterMoves,afterChange:P.measured,top:P.shown('w').rect.top};
    """)
    assert result["afterTake"] == 1 and result["afterMoves"] == 1, result
    assert result["afterChange"] == 2, result
    assert result["top"] >= 400 - 0.5, result


def test_the_hand_relay_after_a_rebase_resumes_where_the_hand_wanted(tmp_path):
    """Bare Hands après une refonte qui borne l'objet (la fenêtre rétrécit sous
    une fenêtre saisie près du bord droit) : le moteur continue depuis sa
    boîte ; revenu assez loin, l'objet est là où la main le veut — le
    rattrapage d'un mur ordinaire, sans écart permanent."""

    result = run_desk(tmp_path, r"""
      const objs=[{id:'w',representation:'window',box:{x:60,y:-10,w:30,h:20}}];
      const out=[];
      for(const gravity of [true,false]){
        const P=page(1920,1080,objs,{gravity});
        const h=P.desk.take('hand',['w'],{});
        const start=h.hold.start('w');
        const engine=du=>({...start,x:start.x+du});
        P.desk.to(h,'w',engine(2),'move');P.tick(16);P.render();
        const c0=P.shown('w');                                     // centre (px), avant
        P.vp=L.viewport(1280,720);
        P.desk.to(h,'w',engine(2),'move');P.tick(16);P.render();  // refonte : bornée au bord
        const bounded=P.shown('w');
        P.desk.to(h,'w',engine(2-60),'move');P.tick(16);P.render();
        const s=P.vp.scale;
        out.push({gravity,out:c0.x-bounded.x,error:Math.abs(P.shown('w').x-(c0.x-60*s))});
      }
      return out;
    """)
    for row in result:
        assert row["out"] > 100, row           # la refonte a bien borné
        assert row["error"] <= 1.0, row


def test_the_field_clock_is_the_one_of_the_frame_on_screen():
    """L'heure du champ (`I.createFieldClock`) : l'heure murale de l'image
    affichée (horloge du document, pas l'instant) ; la dérive mesurée à la même
    image (une image lente n'en est pas une) ; la remise à l'heure au retour
    d'un onglet, tout de suite puis aux deux images suivantes."""

    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node absent")
    runtime = PAGE_JS.parent
    script = r"""
      const L=require(%s),I=require(%s);
      const s={date:1790003799123,perf:500000,timeline:500000-900};
      const frames=[];
      const clock=I.createFieldClock({layout:L,date:()=>s.date,perf:()=>s.perf,timeline:()=>s.timeline,frame:f=>frames.push(f)});
      const field={ms:240000};
      const wall=clock.wall();
      const onTime=clock.drifted(L.orbitTurnAt(wall,field)*field.ms,field);
      const late=clock.drifted(L.orbitTurnAt(wall-40,field)*field.ms,field);
      let syncs=0;clock.resyncOnReturn(()=>syncs++);
      const now=syncs;while(frames.length)frames.shift()();
      console.log(JSON.stringify({wall,onTime,late,now,after:syncs,turn:clock.turn(field),time:clock.time(field),
        still:clock.time(null),expectTurn:L.orbitTurnAt(wall,field)}));
    """ % (json.dumps(str(runtime / "control_center_scene_layout.js")), json.dumps(str(runtime / "control_center_scene_interact.js")))
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True)
    r = json.loads(out.stdout)
    assert r["wall"] == 1790003799123 - 900
    assert r["onTime"] is False and r["late"] is True
    assert r["now"] == 1 and r["after"] == 3
    assert r["turn"] == r["expectTurn"] and abs(r["time"] - r["turn"] * 240000) < 1e-6
    assert r["still"] == 0


def test_the_page_wires_every_hold_and_clock_through_the_desk():
    """Le câblage restant de la page, une ligne par chemin : chaque entrée
    passe par le bureau (prise à l'appui, glissement, lâcher, abandon doux —
    Échap du clavier comme clic de la souris et annulation de la main), le dégel
    n'est lancé que sur ce que le bureau rend, et l'heure vient de l'horloge du
    champ."""

    page = PAGE_JS.read_text(encoding="utf-8")
    body = lambda start, end: page[page.index(start):page.index(end)]
    down = body("function onPointerDown(", "function onPointerMove(")
    assert "gesture.handle=takeHold('mouse'," in down
    move = body("function onPointerMove(", "function endGesture(")
    assert "desk.drag(g.handle," in move and "takeHold(" not in move
    up = body("function onPointerUp(", "function dropGesture(")
    assert "if(g.menuOpened||!g.moved){" in up and "desk.cancel(g.handle);" in up
    assert "desk.drop(g.handle,g.mode)" in body("function dropGesture(", "function cancelGesture(")
    assert "desk.cancel(g.handle)" in body("function cancelGesture(", "function onPointerCancel(")
    assert "desk.cancel(edit.handle);" in body("function cancelKeyEdit(", "/* ------------------------------------------------------------ menu */")
    assert "desk.drop(edit.handle,kind)" in body("function flushKeyEdit(", "function cancelKeyEdit(")
    frames = body("  const frames=Object.freeze({", "    /* La même porte que `begin`")
    assert "const handle=takeHold('hand',[id],{},'Déplacement');" in frames
    assert "desk.to(handle,id,box,mode);" in frames and "desk.drop(handle,kind)" in frames
    assert "cancel(id){if(framesRelease(id))scheduleRender()}" in frames
    assert "desk.cancel(handle);" in body("function framesRelease(", "  const frames=Object.freeze({")
    position = body("  function position(el,node,field){", "  function startThaw(")
    assert "if(free&&desk){const spec=desk.positioned(node.id,node,rect);if(spec)startThaw(record,spec)}" in position
    thaw = body("  function startThaw(", "  function stopThaw(")
    assert "record.el.animate(spec.keyframes,{duration:spec.duration,easing:spec.easing})" in thaw
    assert "if(typeof record.el.animate!=='function'){desk.thawEnded(record.el.dataset.objectId);return}" in thaw
    assert "function frameWall(){\n    return clock?clock.wall():Date.now();" in page
    # Le bureau calcule ce qui est **montré** : à l'heure de l'instant, pas à
    # celle de l'horloge du document (restée en arrière quand rien ne bouge
    # sur le fil principal).
    assert "createHoldDesk({layout:L,now:()=>Date.now()," in page
    assert "if(clock&&clock.drifted(anim.currentTime,lastField)){" in page
    assert "if(clock)clock.resyncOnReturn(syncFieldToWall);" in page
    assert "function onResize(){if(desk)desk.controlsChanged();" in page
    assert "new ResizeObserver(()=>desk.controlsChanged())" in page

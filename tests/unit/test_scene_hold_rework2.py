"""Second tour de QA du déplacement 2D (22/09/2026) : un test par défaut relevé
(A à G), qui échoue sur 43f909c, et des tests de comportement pour les
mutations qui survivaient (figer la tenue, relais Bare Hands, place la plus
proche).

Même harnais que `test_scene_hold_contract.py` : les modules purs que la page
reçoit, le DOM remplacé par ce qu'il dessine. Le câblage de la page, faute de
harnais DOM, est vérifié sur le fichier servi (`test_scene_renderer_logic.py`
et ici, points D et F).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.test_scene_hold_contract import SCREENS, run_node

PAGE_JS = Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center_scene_page.js"


def test_a_the_hold_takes_the_object_where_the_hand_grabbed_it_not_where_it_turned_to(tmp_path):
    """A. Entre l'appui et le seuil du glissement, l'objet continue de tourner ;
    la tenue ne commence qu'au seuil. Elle le ramène au point de l'appui
    (`hold.shift`) : sinon l'écart restait sous le pointeur jusqu'au lâcher
    (2,9 px à la vitesse 1, 11 à 20 px à la vitesse 4). Un clic sans
    mouvement, lui, ne fige rien et ne déplace rien."""

    result = run_node(tmp_path, r"""
      let worst=0,cases=0;
      for(const [W,H] of D.screens)for(const gain of [.5,1,1.3])for(const lag of [.00125,.005,.02]){
        const objects=[{id:'a',representation:'point',box:{x:40,y:-20,w:6,h:6}},{id:'c',representation:'capsule',box:{x:-40,y:30,w:40,h:7}}];
        for(const id of ['a','c']){
          const down=scene(W,H,objects,{gain,turn:.1});
          const node=down.nodes.find(n=>n.id===id);
          const grabbedAt=L.orbitDrawnPoint(node,down.field,.1);
          /* Le seuil franchi `lag` de tour plus tard (300 ms à la vitesse 1 : .00125). */
          const later=scene(W,H,objects,{gain,turn:.1+lag});
          const g=grab(later,[id]);
          const start=L.nodeGeometry(later.vp,objects.find(o=>o.id===id).representation,g.hold.start(id));
          g.hold.shift({dx:(grabbedAt.x-start.cx)/later.vp.scale,dy:(grabbedAt.y-start.cy)/later.vp.scale});
          DEVICES.mouse(later,g,id,80,-40);
          worst=Math.max(worst,hyp(g.shown(id),{x:grabbedAt.x+80,y:grabbedAt.y-40}));cases++;
          const last=g.shown(id),after=drop(later,g,id,.01);
          worst=Math.max(worst,hyp(after.drawn,last));
        }
      }
      return {worst,cases};
    """, {"screens": SCREENS})
    assert result["cases"] == 72
    assert result["worst"] <= 1.0


def test_b_a_still_object_nudged_across_its_boundary_stays_still_while_it_can(tmp_path):
    """B. **Justifié, pas corrigé** (le comportement est celui de 43f909c ; ce
    test le fige et tue la mutation « la place la plus fidèle seulement »).
    L'étoile immobile posée en (-101, -25) est à moins d'un pixel de la
    frontière de son ellipse. Poussée vers le centre, tant qu'une place
    immobile la dessine à moins d'un pixel du pointeur, c'est elle qui
    l'emporte — la plus proche de la place de départ. Au-delà (2 px et plus),
    aucune place immobile ne peut la dessiner sous le pointeur : la règle « un
    objet tourne s'il est dans son ellipse » l'interdit, et la clause 2 du
    contrat (≤ 1 px au lâcher) prime ; l'objet tourne, son dessin restant à
    moins d'un pixel. Le 2/6 080 de la simulation et le 9/10 du navigateur
    sont le même phénomène : la simulation échantillonne une grille de
    2 unités, le QA a choisi une étoile sur la frontière."""

    result = run_node(tmp_path, r"""
      const vp=L.viewport(1920,1080);
      const out=[];
      /* Le cas du QA, et des étoiles posées juste au-delà de leur frontière, tout
         autour du centre : poussées vers le centre de 0,5 à 5 px. */
      const boxes=[{x:-101,y:-25,w:6,h:6}];
      for(const angle of [.3,1.2,2.2,3.5,4.4,5.6]){
        const inset=L.orbitInset({x:0,y:0,w:6,h:6})*1.0003;
        boxes.push({x:inset*L.ORBIT_AXES.ax*Math.cos(angle)-3,y:inset*L.ORBIT_AXES.ay*Math.sin(angle)-3,w:6,h:6});
      }
      for(const box of boxes)for(const gain of [1,1.3])for(const turn of [.1,.37,.6])for(const px of [.5,.8,3,5]){
        const node=L.nodeGeometry(vp,'point',box);
        const field=L.orbitField([node],vp,{gain,rate:1});
        if(L.orbitHolds(node,field))continue;
        const c={x:box.x+3,y:box.y+3},len=Math.hypot(c.x,c.y);
        const hold=I.createHold({layout:L,vp,field,turn,area:I.holdArea(vp,[]),members:[{id:'a',representation:'point',box}]});
        hold.moveBy({dx:-c.x/len*px/vp.scale,dy:-c.y/len*px/vp.scale});
        const place=hold.place('a',turn),after=L.nodeGeometry(vp,'point',place);
        const off=hold.offset('a'),pv=L.nodeGeometry(vp,'point',hold.preview('a')),drawn=L.orbitDrawnPoint(after,field,turn);
        out.push({box,gain,turn,px,turns:L.orbitHolds(after,field),
          moved:Math.hypot(place.x-box.x,place.y-box.y),error:Math.hypot(drawn.x-pv.cx-off.x,drawn.y-pv.cy-off.y)});
      }
      return out;
    """)
    assert len(result) > 100
    for row in result:
        assert row["error"] <= 1.0, row
        if row["px"] < 1:
            assert row["turns"] is False and row["moved"] <= 0.5, row


def test_c_and_g_the_wall_clock_is_the_one_of_the_frame_on_screen(tmp_path):
    """C et G. Les animations avancent sur l'horloge du document, qui n'avance
    qu'à chaque image — et pas du tout dans un onglet caché. Leur donner l'heure
    de l'instant (`Date.now()`) pendant que cette horloge était restée 900 ms en
    arrière les mettait en avance de 900 ms à l'image suivante : 5 à 12 px de
    saut sur des objets que personne n'avait touchés, au retour d'un onglet. Et
    la garde de dérive, en comparant l'instant à l'image, voyait une dérive à
    chaque image lente (sous 33 images/s)."""

    result = run_node(tmp_path, r"""
      const ms=240000;
      /* Onglet qui revient : l'horloge du document est restée 900 ms en arrière. */
      const now=1790003799123,perf=500000,timeline=perf-900;
      const set=L.orbitFrameWall(now,perf,timeline);            // l'heure donnée aux animations
      const nextFrameTimeline=perf+16;                           // l'image suivante, horloge reprise
      const animationThen=set+(nextFrameTimeline-timeline);
      const wallThen=now+16;
      /* Image lente (40 ms) : l'animation est exactement à l'heure de son image. */
      const frame=perf-40,animation=L.orbitFrameWall(now,perf,frame);
      return {aheadAfterReturn:Math.round(animationThen-wallThen),
        gapSlowFrame:L.orbitClockGap(animation,L.orbitFrameWall(now,perf,frame),ms),
        gapNaive:L.orbitClockGap(animation,now,ms),
        wrap:L.orbitClockGap(ms-5,5,ms),noTimeline:L.orbitFrameWall(now,perf,undefined)};
    """)
    assert abs(result["aheadAfterReturn"]) <= 1
    assert result["gapSlowFrame"] == 0 and result["gapNaive"] == 40
    assert result["wrap"] == 10
    assert result["noTimeline"] == 1790003799123


def test_d_a_speed_change_resyncs_every_animation_that_shares_the_clock():
    """D. Vitesse changée : les nœuds reposés étaient remis à l'heure, le calque
    des fils non — les fils décrochaient de leurs étoiles jusqu'à 2 s (180° de
    la vitesse 4 à 1), puis sautaient. Toute modification de la période ou du
    champ remet **toutes** les animations à l'heure dans le même rendu."""

    page = PAGE_JS.read_text(encoding="utf-8")
    render = page[page.index("  function render(){"):page.index("function markFresh(")]
    assert "const clockKey=field?`${field.ms}|${field.scale}|${field.cx}|${field.cy}`:'';" in render
    assert "if(clockKey!==fieldClockKey){fieldClockKey=clockKey;if(field)syncFieldToWall()}" in render


def test_e_a_rebased_hold_stays_on_the_visible_screen(tmp_path):
    """E. La fenêtre rétrécit pendant la tenue : l'objet tenu près du bord droit
    restait hors de l'écran, et sa place enregistrée hors du cadre (x = 148,6
    et 200,2). La refonte le re-borne dans la nouvelle zone visible ; et les
    bords suivent les commandes qui apparaissent pendant le geste (`setArea`)."""

    result = run_node(tmp_path, r"""
      const out=[];
      for(const [rep,box] of [['point',{x:40,y:-20,w:6,h:6}],['capsule',{x:-40,y:30,w:40,h:7}]])for(const gravity of [true,false]){
        const sc=scene(1920,1080,[{id:'a',representation:rep,box}],{turn:.2,gravity});
        const g=grab(sc,['a']);DEVICES.mouse(sc,g,'a',4000,0);             // contre le bord droit
        const vp=L.viewport(1366,768);
        const field=gravity?L.orbitField([L.nodeGeometry(vp,rep,box)],vp,{gain:1,rate:1}):null;
        g.hold.rebase({vp,field,turn:.2,area:I.holdArea(vp,[])});
        const n=L.nodeGeometry(vp,rep,g.hold.preview('a')),off=g.hold.offset('a'),r=L.drawnRect(n);
        const right=r.left+r.width+off.x;
        const place=g.hold.place('a',.2);
        /* Un bandeau apparaît en haut pendant le geste : la tenue ne passe pas dessous. */
        g.hold.setArea(I.holdArea(vp,[{left:0,top:0,width:1366,height:200}]));
        g.hold.moveBy({dx:0,dy:-4000});
        const n2=L.nodeGeometry(vp,rep,g.hold.preview('a')),r2=L.drawnRect(n2);
        out.push({rep,gravity,right:Math.round(right*10)/10,placeRight:place.x+place.w,visibleRight:vp.visible.x1,
          top:Math.round((r2.top+off.y)*10)/10});
      }
      return out;
    """)
    for row in result:
        assert row["right"] <= 1366 + 0.5, row
        assert row["placeRight"] <= row["visibleRight"] + 12, row  # dans le cadre visible, à l'écart d'orbite près
        assert row["top"] >= 200 - 0.5, row


def test_f_keyboard_and_hand_never_hold_the_same_object():
    """F. Clavier et Bare Hands sur le même objet : deux tenues se disputaient
    son décalage figé. Comme avec la souris, la seconde main est refusée."""

    page = PAGE_JS.read_text(encoding="utf-8")
    frames = page[page.index("  const frames=Object.freeze({"):page.index("    preview(id,box,mode){")]
    assert "if(keyEdit&&keyEdit.id===id)return null;" in frames
    keys = page[page.index("function keyAdjust("):page.index("function flushKeyEdit(")]
    assert keys.index("if(barehandsHeld.has(id)){") < keys.index("tryHold(")


def test_the_frozen_translate_of_a_hold_is_its_grab_offset(tmp_path):
    """Mutation « la tenue n'est jamais figée » : ce que la page pose sur chaque
    objet tenu (`I.freezeStyles`) est l'écart dessin − place de la prise, tel
    que l'animation le dessinait à cet instant — c'est lui qui empêche l'objet
    de dériver sous la main."""

    result = run_node(tmp_path, r"""
      const objects=[{id:'a',representation:'point',box:{x:40,y:-20,w:6,h:6}},{id:'b',representation:'capsule',box:{x:-60,y:30,w:40,h:7}}];
      const sc=scene(1920,1080,objects,{turn:.3,gain:.8});
      const g=grab(sc,['a','b']);
      return I.freezeStyles(g.hold).map(({id,translate})=>{
        const n=sc.nodes.find(n=>n.id===id),t=translateOf(n,sc.field,sc.turn);
        const [x,y]=translate.split(' ').map(parseFloat);
        return {id,gap:Math.hypot(x-t.x,y-t.y),moving:Math.hypot(t.x,t.y)};
      });
    """)
    assert [row["id"] for row in result] == ["a", "b"]
    for row in result:
        assert row["moving"] > 10, row  # un vrai décalage d'orbite, pas zéro
        assert row["gap"] <= 0.2, row


def test_the_bare_hands_relay_continues_from_the_engine_box_after_a_rebase(tmp_path):
    """Mutation « relais transparent » : après une refonte, le moteur Bare Hands
    calcule encore depuis sa boîte de départ, dans l'ancien repère. Sa première
    boîte suivante devient la référence, seuls ses écarts comptent : sans cela,
    le cadre sautait de toute la distance entre les deux repères."""

    result = run_node(tmp_path, r"""
      const relay=I.createRelay();
      const before=relay.map({x:10,y:5,w:40,h:7});                 // avant toute refonte : tel quel
      relay.rebased({x:-30,y:12,w:40,h:7});                         // la tenue refondue montre cette boîte
      const first=relay.map({x:14,y:5,w:40,h:7});                   // première boîte du moteur ensuite
      const next=relay.map({x:17,y:3,w:42,h:7});                    // il continue : +3, -2, +2 de largeur
      return {before,first,next};
    """)
    assert result["before"] == {"x": 10, "y": 5, "w": 40, "h": 7}
    assert result["first"] == {"x": -30, "y": 12, "w": 40, "h": 7}
    assert result["next"] == {"x": -27, "y": 10, "w": 42, "h": 7}

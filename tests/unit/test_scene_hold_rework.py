"""Reprise QA du contrat du déplacement 2D (22/09/2026) : un test par défaut
relevé, qui échouait sur la première version de la tenue (6116f35).

1. l'heure du tour se **calcule** (murale), elle ne se lit plus dans le DOM ;
2. au-dessus de l'ampleur 1, un objet immobile reposé reste immobile ;
3. et 5. le champ continue de tourner pendant la tenue — seul l'objet tenu est
   figé — et le lâcher pose l'objet là où il est **à l'instant du lâcher** ;
4. ce qui s'arrête aux bords est le rectangle réellement dessiné ;
6. la tenue se refonde quand la fenêtre ou le champ changent sous la main.

Même harnais que `test_scene_hold_contract.py` : les modules purs que la page
reçoit, le DOM remplacé par ce qu'il dessine.
"""

from __future__ import annotations

import pytest

from tests.unit.test_scene_hold_contract import SCREENS, run_node


def test_the_turn_is_a_pure_function_of_the_wall_clock(tmp_path):
    """Point 1. `L.orbitTurnAt(Date.now(), field)` est la seule source de
    l'angle : deux onglets (ou un rechargement) au même instant ont le même
    tour, et l'angle ne dépend d'aucun calque du DOM — il se lisait sur
    l'animation des fils, absente quand l'utilisateur les masque, et retombait
    à zéro sous des étoiles qui tournaient (saut au lâcher de 64 à 216 px)."""

    result = run_node(tmp_path, r"""
      const vp=L.viewport(1920,1080);
      const field=L.orbitField([L.nodeGeometry(vp,'point',{x:40,y:-20,w:6,h:6})],vp,{gain:1,rate:1});
      const now=1790003799123;
      const tabA=L.orbitTurnAt(now,field),tabB=L.orbitTurnAt(now,field);
      /* Le lâcher calculé au tour réel (et non à zéro) pose l'objet sous la main. */
      const turn=L.orbitTurnAt(now,field);
      const sc=scene(1920,1080,[{id:'a',representation:'point',box:{x:40,y:-20,w:6,h:6}}],{turn});
      const g=grab(sc,['a']);DEVICES.mouse(sc,g,'a',100,40);
      const last=g.shown('a'),after=drop(sc,g,'a');
      return {tabA,tabB,expected:(now%field.ms)/field.ms,later:L.orbitTurnAt(now+field.ms/4,field),
        still:L.orbitTurnAt(now,null),drop:hyp(after.drawn,last)};
    """)
    assert result["tabA"] == result["tabB"] == pytest.approx(result["expected"])
    assert result["later"] == pytest.approx((result["expected"] + 0.25) % 1)
    assert result["still"] == 0
    assert result["drop"] <= 1.0


def test_above_unit_amplitude_a_still_object_put_back_stays_still(tmp_path):
    """Point 2. À l'ampleur 1,3, un même point dessiné peut venir d'une place
    qui tourne et d'une place qui ne tourne pas. Reprendre un objet immobile et
    le reposer d'un pixel le faisait tourner, sa place enregistrée partant de
    l'autre côté de l'écran (3 432 objets sur 6 080). La place la plus proche de
    celle de départ l'emporte ; à la frontière exacte de l'ellipse seulement, un
    objet peut changer de branche — sans que son dessin bouge."""

    result = run_node(tmp_path, r"""
      const out={};
      for(const gain of [.5,1,1.3])for(const turn of [.25,.5]){
        let n=0,flipped=0,drawnJump=0;
        const vp=L.viewport(1920,1080);
        for(let x=-150;x<=140;x+=2)for(let y=-80;y<=75;y+=2){
          const box={x,y,w:6,h:6};
          const node=L.nodeGeometry(vp,'point',box);
          const field=L.orbitField([node],vp,{gain,rate:1});
          if(L.orbitHolds(node,field))continue;
          n++;
          const hold=I.createHold({layout:L,vp,field,turn,area:I.holdArea(vp,[]),members:[{id:'a',representation:'point',box}]});
          hold.moveBy({dx:.2,dy:0});
          const place=hold.place('a');
          const after=L.nodeGeometry(vp,'point',place);
          if(L.orbitHolds(after,field))flipped++;
          const before=L.orbitDrawnPoint(node,field,turn),now=L.orbitDrawnPoint(after,field,turn);
          drawnJump=Math.max(drawnJump,Math.hypot(now.x-before.x-.2*vp.scale,now.y-before.y));
        }
        out[`${gain}/${turn}`]={n,flipped,drawnJump:Math.round(drawnJump*100)/100};
      }
      return out;
    """)
    for key, row in result.items():
        assert row["n"] > 1000, key
        assert row["flipped"] <= 4, (key, row)
        assert row["drawnJump"] <= 1.0, (key, row)


def test_the_field_keeps_turning_during_a_hold_and_the_drop_is_placed_for_its_own_instant(tmp_path):
    """Points 3 et 5. Arrêter le champ entier pendant une tenue le décalait de
    la durée du geste par rapport à l'heure murale : l'autre onglet s'en
    trouvait décalé, et un rechargement faisait sauter les étoiles non tenues.
    Désormais seul l'objet tenu est figé (son décalage de prise), le champ
    continue, et le lâcher — 3 s, 30 s ou un quart de tour plus tard — pose
    l'objet exactement où il est. Les objets non tenus, eux, sont au même
    endroit dans tous les onglets et après un rechargement : leur dessin ne
    dépend que de l'heure murale."""

    result = run_node(tmp_path, r"""
      let worst=0,cases=0;
      for(const [W,H] of D.screens)for(const gain of [.5,1,1.3])for(const later of [3000,30000,60000]){
        const objects=[{id:'a',representation:'point',box:{x:40,y:-20,w:6,h:6}},{id:'b',representation:'capsule',box:{x:-60,y:30,w:40,h:7}}];
        const sc=scene(W,H,objects,{gain,turn:.1});
        const g=grab(sc,['a']);DEVICES.mouse(sc,g,'a',-180,-120);
        const last=g.shown('a');
        const after=drop(sc,g,'a',later/sc.field.ms);
        worst=Math.max(worst,hyp(after.drawn,last));cases++;
      }
      /* Deux onglets, dont un où l'on tient un objet : l'objet non tenu est
         dessiné au même pixel dans les deux, puisque rien ne s'est arrêté. */
      const objects=[{id:'b',representation:'capsule',box:{x:-60,y:30,w:40,h:7}}];
      const now=1790003799123+45000;
      const tab=()=>{const vp=L.viewport(1920,1080);const f=L.orbitField([L.nodeGeometry(vp,'capsule',objects[0].box)],vp,{gain:1,rate:1});
        return scene(1920,1080,objects,{turn:(now%f.ms)/f.ms}).drawn('b')};
      return {drop:worst,cases,tabs:hyp(tab(),tab())};
    """, {"screens": SCREENS})
    assert result["cases"] == 36
    assert result["drop"] <= 1.0
    assert result["tabs"] == 0


def test_what_stops_at_the_edge_is_the_rectangle_actually_drawn(tmp_path):
    """Point 4. Une étoile est dessinée sur 26 px, sa boîte en fait 36 en
    1080p : la tenue bornait la boîte, et l'étoile s'arrêtait 5 à 9 px avant le
    bord de l'écran ou le dock. Pour chaque forme, le rectangle dessiné touche
    le bord."""

    result = run_node(tmp_path, r"""
      const out=[];
      for(const [W,H] of D.screens)for(const [rep,box] of [['point',{x:10,y:10,w:6,h:6}],['capsule',{x:-20,y:0,w:40,h:7}],['window',{x:-20,y:-12,w:40,h:24}]]){
        const sc=scene(W,H,[{id:'a',representation:rep,box}],{gravity:false});
        for(const [dx,dy] of [[5000,0],[-5000,0],[0,5000],[0,-5000]]){
          const g=grab(sc,['a']);DEVICES.mouse(sc,g,'a',dx,dy);
          const r=g.shown('a').rect;
          const gap=dx>0?W-r.left-r.width:dx<0?r.left:dy>0?H-r.top-r.height:r.top;
          out.push(Math.abs(Math.round(gap*10)/10));
        }
      }
      return out;
    """, {"screens": SCREENS})
    assert max(result) <= 0.5, result


def test_a_hold_rebases_when_the_window_or_the_field_change_under_the_hand(tmp_path):
    """Point 6. Ampleur changée depuis un autre onglet, gravitation coupée,
    fenêtre redimensionnée pendant qu'on tient un objet : le lâcher défaisait
    un tour qui n'existait plus (50 à 626 px de décalage). La tenue se refonde
    (`rebase`) : l'objet reste au pixel où il est dessiné, la main repart de là
    où elle est, et le lâcher le pose sous elle dans le nouveau repère."""

    result = run_node(tmp_path, r"""
      const out={};
      const box={x:40,y:-20,w:6,h:6},cap={x:-60,y:30,w:40,h:7};
      for(const [label,next] of [['ampleur 1,3',{W:1920,H:1080,gain:1.3,gravity:true}],['ampleur 0,5',{W:1920,H:1080,gain:.5,gravity:true}],
        ['gravitation coupée',{W:1920,H:1080,gain:1,gravity:false}],['fenêtre 1366×768',{W:1366,H:768,gain:1,gravity:true}]])
      for(const [rep,b] of [['point',box],['capsule',cap]]){
        const sc=scene(1920,1080,[{id:'a',representation:rep,box:b}],{turn:.2});
        const g=grab(sc,['a']);DEVICES.mouse(sc,g,'a',100,-50);
        const vpBefore=sc.vp,before=g.shown('a');
        /* Le rendu suivant : autre fenêtre ou autre champ, même instant. */
        const vp=L.viewport(next.W,next.H);
        const field=next.gravity?L.orbitField([L.nodeGeometry(vp,rep,b)],vp,{gain:next.gain,rate:1}):null;
        const changed=g.hold.signature()!==I.holdSignature(vp,field);
        g.hold.rebase({vp,field,turn:.2,area:I.holdArea(vp,[])});
        /* Ce que la page montre : l'aperçu, et le nouveau décalage figé. */
        const off=g.hold.offset('a'),n=L.nodeGeometry(vp,rep,g.hold.preview('a'));
        const shown={x:n.cx+off.x,y:n.cy+off.y};
        /* La main repart de là où elle est : 60 px de plus, vers le centre. */
        g.hold.moveBy(I.pxToUnits(vp,-60,0));
        const n2=L.nodeGeometry(vp,rep,g.hold.preview('a')),moved={x:n2.cx+off.x,y:n2.cy+off.y};
        const place=g.hold.place('a',.2);
        const pn=L.nodeGeometry(vp,rep,place);
        const f2=next.gravity?L.orbitField([pn],vp,{gain:next.gain,rate:1}):null;
        const drawn=L.orbitDrawnPoint(pn,f2,.2);
        out[label+' '+rep]={changed,atRebase:hyp(shown,before),follows:Math.round((shown.x-moved.x)*10)/10,drop:hyp(drawn,moved)};
      }
      return out;
    """)
    for key, row in result.items():
        assert row["changed"] is True, key
        assert row["atRebase"] <= 1.0, (key, row)
        assert row["follows"] == pytest.approx(60, abs=1), (key, row)
        assert row["drop"] <= 1.0, (key, row)

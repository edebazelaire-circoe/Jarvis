"""Mouse side descriptors share Bare Hands geometry and the existing hold desk."""
from __future__ import annotations

import pytest

from tests.unit.test_scene_hold_desk import run_desk
from tests.unit.test_scene_hold_contract import run_node


@pytest.mark.parametrize("side", ["top", "right", "bottom", "left", "top-left", "top-right", "bottom-left", "bottom-right"])
def test_mouse_edges_use_side_geometry_and_keep_opposite_anchor(tmp_path, side):
    result = run_desk(tmp_path, """
      const side=D.side,P=page(1920,1080,[{id:'w',representation:'window',box:{x:-20,y:-10,w:40,h:20}}],{gravity:false});
      const pointer=at(P,'w',.5,.5),h=P.desk.take('mouse',['w'],{mode:'resize',sides:side,pointer});
      const dx=side.includes('left')?-18:side.includes('right')?18:0;
      const dy=side.includes('top')?-12:side.includes('bottom')?12:0;
      P.desk.drag(h,pointer.x+dx,pointer.y+dy,false);
      const got=h.hold.drawn('w'),sides={};
      for(const s of side.split('-'))sides[s]=I.MANIPULATION_SIDES[s]==='x'?dx/P.vp.scale:dy/P.vp.scale;
      return {got,wanted:I.resizeBySides(h.resizeStart,sides,'window'),before:h.resizeStart};
    """, {"side": side})
    assert result["got"] == result["wanted"]
    before, got = result["before"], result["got"]
    if "left" in side:
        assert got["x"] + got["w"] == pytest.approx(before["x"] + before["w"])
    else:
        assert got["x"] == before["x"]
    if "top" in side:
        assert got["y"] + got["h"] == pytest.approx(before["y"] + before["h"])
    else:
        assert got["y"] == before["y"]


def test_shift_rebases_without_jump_and_locks_current_ratio_until_release(tmp_path):
    result = run_desk(tmp_path, """
      const P=page(1920,1080,[{id:'w',representation:'window',box:{x:-20,y:-10,w:40,h:20}}],{gravity:false});
      const p=at(P,'w',1,1),h=P.desk.take('mouse',['w'],{mode:'resize',pointer:p});
      P.desk.drag(h,p.x+30,p.y+5,false);const free=h.hold.drawn('w');
      P.desk.drag(h,p.x+30,p.y+5,true);const pressed=h.hold.drawn('w');
      P.desk.drag(h,p.x+60,p.y+10,true);const locked=h.hold.drawn('w');
      P.desk.drag(h,p.x+60,p.y+10,false);const released=h.hold.drawn('w');
      P.desk.drag(h,p.x+90,p.y+10,false);const end=h.hold.drawn('w');
      return {free,pressed,locked,released,end};
    """)
    assert result["free"] == result["pressed"]
    assert result["locked"] == result["released"]
    assert result["locked"]["w"] / result["locked"]["h"] == pytest.approx(result["free"]["w"] / result["free"]["h"], abs=.01)
    assert result["end"]["h"] == result["released"]["h"]
    assert result["end"]["w"] > result["released"]["w"]


def test_shift_at_start_and_controls_keep_ratio_within_bounds(tmp_path):
    result = run_desk(tmp_path, """
      const P=page(1280,720,[{id:'w',representation:'window',box:{x:-20,y:-10,w:40,h:20}}],{gravity:false});
      const p=at(P,'w',1,1),h=P.desk.take('mouse',['w'],{mode:'resize',pointer:p,aspectLocked:true});
      P.desk.drag(h,p.x+2000,p.y+20,true);
      const box=h.hold.drawn('w');return {box,shown:P.shown('w').rect,area:I.holdArea(P.vp,[])};
    """)
    assert result["box"]["w"] / result["box"]["h"] == pytest.approx(2, abs=.01)
    assert result["shown"]["left"] + result["shown"]["width"] <= 1280.1
    assert result["shown"]["top"] + result["shown"]["height"] <= 720.1


def test_bare_hands_side_math_and_minimum_are_unchanged_without_shift(tmp_path):
    result = run_node(tmp_path, """
      const start={x:0,y:0,w:40,h:20},out=[];
      for(const side of I.RESIZE_HANDLES){const sides={};for(const s of side.split('-'))sides[s]=s==='left'||s==='top'?1000:-1000;
        const b=I.resizeBySides(start,sides,'window');out.push({b,min:I.MIN_SIZE.window});}
      return out;
    """)
    for row in result:
        assert row["b"]["w"] >= row["min"]["w"]
        assert row["b"]["h"] >= row["min"]["h"]

"""Pure visual arrangement, canonical layout wire and bounded stale-aware undo."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.domain.scene import SceneActor, SceneCommand, SceneCommandOutcome, apply_scene_command
from jarvis.protocol.scene_wire import MAX_SCENE_COMMAND_BYTES, compact_json
from tests.unit.test_scene_batch import scene


MODULE = Path(__file__).resolve().parents[2] / "jarvis/runtime/control_center_scene_organize.js"
MEMBERS = [{"id": "a", "box": {"x": -30, "y": -20, "w": 40, "h": 24}, "representation": "window"},
           {"id": "b", "box": {"x": 30, "y": -15, "w": 45, "h": 30}, "representation": "window"},
           {"id": "c", "box": {"x": -10, "y": 30, "w": 35, "h": 25}, "representation": "capsule"}]


def run(body, data=MEMBERS):
    if not shutil.which("node"):
        pytest.skip("node absent")
    script = f"const A=require({json.dumps(str(MODULE))}),D={json.dumps(data)};console.log(JSON.stringify((()=>{{{body}}})()));"
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.mark.parametrize("action", ["row", "column", "grid", "custom", "left", "center", "right", "top", "middle", "bottom", "distributeX", "distributeY", "width", "height", "size"])
def test_every_action_is_deterministic_with_finite_positive_targets(action):
    result = run("const action=D.action;return {a:A.plan(D.members,action,{rows:3,cols:8,scale:6}),b:A.plan(D.members.slice().reverse(),action,{rows:3,cols:8,scale:6})}", {"action": action, "members": MEMBERS})
    a = {m["id"]: m["box"] for m in result["a"]}
    b = {m["id"]: m["box"] for m in result["b"]}
    assert a == b
    assert all(box["w"] > 0 and box["h"] > 0 for box in a.values())
    if action == "row":
        boxes = sorted(a.values(), key=lambda x: x["x"])
        assert all(z["x"] >= x["x"] + x["w"] for x, z in zip(boxes, boxes[1:]))
    if action == "width":
        assert {box["w"] for box in a.values()} == {45}
    if action == "height":
        assert {box["h"] for box in a.values()} == {30}


def test_custom_grid_and_size_refusals_are_explicit():
    result = run("const errors=[];for(const [action,opts] of [['custom',{rows:1,cols:2}],['custom',{rows:100,cols:8}],['row',{area:{x0:0,x1:10,y0:0,y1:10}}]])try{A.plan(D,action,opts)}catch(e){errors.push(e.message)};D[0].representation='point';try{A.plan(D,'size')}catch(e){errors.push(e.message)};return errors")
    assert len(result) == 4
    assert "redimensionnables" in result[-1]


def test_planner_wire_is_accepted_by_canonical_atomic_reducer():
    before = scene()
    members = [{"id": item.object_id, "representation": item.representation.value, "box": item.geometry.to_payload()}
               for item in before.objects if item.object_id in {"n1", "n2", "n3"}]
    wire = run("const planned=A.plan(D,'row'),by=new Map(D.map(m=>[m.id,m]));return A.command(planned.map(m=>({id:m.id,before:by.get(m.id).box,after:m.box})),true)", members)
    command = SceneCommand.from_payload({**wire, "actor": SceneActor.USER.value})
    update = apply_scene_command(before, command)
    assert update.outcome is SceneCommandOutcome.APPLIED
    assert update.snapshot.revision == before.revision + 1 and len(update.patch.ops) == 3


def test_wire_budget_accounts_for_python_float_encoding_and_refuses_unsendable_undo():
    result = run("const targets=Array.from({length:512},(_,i)=>({id:'n'+i,before:{x:0,y:0,w:10,h:10},after:{x:i,y:1,w:11,h:12}}));const cmd=A.command(targets,true);let refused=false;try{A.checkBudget(targets)}catch(e){refused=true};return {cmd,bytes:A.wireBytes(cmd),limit:A.WIRE_BYTES,refused,small:A.wireBytes(A.command(targets.slice(0,24),true))}")
    parsed = SceneCommand.from_payload({**result["cmd"], "actor": "user"}).to_payload()
    assert len(compact_json(parsed).encode("utf-8")) <= result["bytes"]
    assert result["limit"] == MAX_SCENE_COMMAND_BYTES
    assert result["refused"] is True and result["small"] < result["limit"]


def test_undo_is_short_lived_and_never_overwrites_newer_geometry_or_new_board():
    result = run("""
      let now=0;const history=A.createHistory({now:()=>now,limit:2,ttlMs:100});
      const target={id:'a',before:{x:0,y:0,w:40,h:24},after:{x:10,y:0,w:40,h:24},representation:'window'};
      const state={scene_id:'s',epoch:'e',objects:new Map([['a',{geometry:target.after,visibility:'visible',representation:'window'}]])};
      const entry={scene_id:'s',epoch:'e',board_id:'b',targets:[target]};history.record(entry);
      const valid=history.take(state,'b');history.record(entry);state.objects.get('a').geometry={...target.after,x:11};
      let stale=false;try{history.take(state,'b')}catch(e){stale=true}
      history.record(entry);let board=false;try{history.take(state,'other')}catch(e){board=true}
      history.record(entry);now=101;return {valid,stale,board,expired:history.size()};
    """)
    assert result["valid"]["command"]["targets"][0]["expected_geometry"]["x"] == 10
    assert "pin" not in result["valid"]["command"]
    assert result["stale"] and result["board"] and result["expired"] == 0

"""Conformance Python <-> JS de l'horloge de composition (handoff jarvis-remotion-native-studio-playback-fix, Slice 04).

Une seule arithmétique : `jarvis/domain/composition_clock.py` (Core) et son portage direct
`jarvis/runtime/control_center_composition_clock.js` (navigateur). La même table de vecteurs passe dans les deux (node pour le JS) et
doit donner exactement le même résultat, erreurs comprises (même code) : chaque image de chaque composition (`locate`), chaque image
native de chaque scène (`frame_of`), chaque navigation et chaque tic. `fromWire` refait le calcul sur la carte servie par Core et
refuse une carte falsifiée ou d'une autre clé. Contrat : `docs/presentation-studio.md` > *Composition clock (Level 3)*.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from jarvis.domain.composition_clock import (
    CompositionError, SceneManifest, Seek, Transport, build_composition, pause, play, seek, tick, to_wire,
)

ROOT = Path(__file__).resolve().parents[2]
CLOCK_JS = ROOT / "jarvis" / "runtime" / "control_center_composition_clock.js"

_SLICE03 = [["s1", 24, 72], ["s2", 25, 200], ["s3", 30, 900], ["s4", 60, 180], ["s5", 24, 192], ["s6", 25, 750],
            ["s7", 30, 90], ["s8", 60, 480], ["s9", 24, 720]]
CASES: list[dict[str, Any]] = [
    {"name": "slice03-mixed-fps", "scenes": _SLICE03, "transitions": None},
    {"name": "irregular", "scenes": [["a", 25, 199], ["b", 60, 7], ["c", 24, 1], ["d", 30, 901]], "transitions": None},
    {"name": "overlap", "scenes": [["a", 30, 90], ["b", 24, 240], ["c", 60, 120]], "transitions": [0, 15, 30]},
    {"name": "overlap-qa", "scenes": [["a", 30, 90], ["b", 30, 90]], "transitions": [0, 15]},
    {"name": "odd-fps", "scenes": [["a", 7, 13], ["b", 11, 29], ["c", 120, 5]], "transitions": [0, 3, 2]},
    {"name": "one-scene", "scenes": [["only", 30, 90]], "transitions": None},
    {"name": "empty", "scenes": [], "transitions": None},
    {"name": "bad-fps", "scenes": [["a", 30, 90], ["b", 0, 10]], "transitions": None},
    {"name": "bad-duration", "scenes": [["a", 30, 0]], "transitions": None},
    {"name": "duplicate", "scenes": [["a", 30, 9], ["a", 30, 9]], "transitions": None},
    {"name": "bad-overlap", "scenes": [["a", 30, 90], ["b", 30, 90]], "transitions": [0, 90]},
    {"name": "first-overlap", "scenes": [["a", 30, 90], ["b", 30, 90]], "transitions": [1, 0]},
]
SEEKS = [("next", None), ("previous", None), ("scene", 0), ("scene", 1), ("scene", 99), ("scrub", 0), ("scrub", 17), ("scrub", -1),
         ("home", None), ("end", None), ("step", 1), ("step", -1), ("step", 2), ("replay", None)]


def _err(exc: CompositionError) -> dict[str, Any]:
    return {"error": exc.code}


def _state(t: Transport) -> list[Any]:
    return [t.frame, t.playing, t.ended]


def _py_case(case: dict[str, Any]) -> dict[str, Any]:
    try:
        cmap = build_composition([SceneManifest(s, "Scene", fps, d) for s, fps, d in case["scenes"]], case["transitions"])
    except CompositionError as exc:
        return {"build": _err(exc)}
    out: dict[str, Any] = {"build": {"fps": cmap.fps, "total": cmap.total_frames,
                                     "spans": [[s.start, s.length, s.transition_in] for s in cmap.scenes]}}
    locate = []
    for f in range(-1, cmap.total_frames + 1):
        try:
            p = cmap.locate(f)
            locate.append([p.scene_index, p.local_frame, p.native_frame, p.local_progress, cmap.next_start(f), cmap.previous_start(f)])
        except CompositionError as exc:
            locate.append(_err(exc))
    out["locate"] = locate
    frame_of = []
    for i in range(-1, len(cmap.scenes) + 1):
        natives = range(-1, cmap.scenes[i].duration_in_frames + 1) if 0 <= i < len(cmap.scenes) else [0]
        for n in natives:
            try:
                frame_of.append(cmap.frame_of(i, n))
            except CompositionError as exc:
                frame_of.append(_err(exc))
    out["frame_of"] = frame_of
    probes = sorted({0, 1, cmap.last_frame, *(s.start for s in cmap.scenes), *(max(0, s.start - 1) for s in cmap.scenes)})
    transport = []
    for f in probes:
        for playing in (False, True):
            for ended in (False, True):
                state = Transport(f, playing, ended)
                row: list[Any] = [_state(play(cmap, state)), _state(pause(cmap, state))]
                for kind, value in SEEKS:
                    try:
                        row.append(_state(seek(cmap, state, Seek(kind), value)))
                    except CompositionError as exc:
                        row.append(_err(exc))
                transport.append(row)
    out["transport"] = transport
    ticks = []
    starts = sorted({*probes, *(s.start + s.length // 2 for s in cmap.scenes)})
    for f in starts:
        for playing in (False, True):
            for ended in (False, True):
                state = Transport(f, playing, ended)
                for i, span in enumerate(cmap.scenes):
                    for n in (-1, 0, span.duration_in_frames // 2, span.duration_in_frames - 1, span.duration_in_frames):
                        for scene_ended in (False, True):
                            try:
                                ticks.append(_state(tick(cmap, state, i, n, scene_ended=scene_ended)))
                            except CompositionError as exc:
                                ticks.append(_err(exc))
    out["tick"] = ticks
    out["wire"] = to_wire(cmap, key="cmp_test")
    return out


JS_DRIVER = r"""
const C=require(PATHS.clock);
const err=e=>{if(!(e instanceof C.CompositionError))throw e;return {error:e.code}};
const st=t=>[t.frame,t.playing,t.ended];
function jsCase(c){
  let map;
  try{map=C.build(c.scenes.map(([s,fps,d])=>({scene_id:s,composition_id:'Scene',fps,duration_in_frames:d})),c.transitions)}
  catch(e){return {build:err(e)}}
  const out={build:{fps:map.fps,total:map.total_frames,spans:map.scenes.map(s=>[s.start,s.length,s.transition_in])}};
  out.locate=[];
  for(let f=-1;f<=map.total_frames;f++){
    try{const p=map.locate(f);out.locate.push([p.scene_index,p.local_frame,p.native_frame,p.local_progress,map.nextStart(f),map.previousStart(f)])}
    catch(e){out.locate.push(err(e))}
  }
  out.frame_of=[];
  for(let i=-1;i<=map.scenes.length;i++){
    const natives=i>=0&&i<map.scenes.length?Array.from({length:map.scenes[i].duration_in_frames+2},(_,k)=>k-1):[0];
    for(const n of natives){try{out.frame_of.push(map.frameOf(i,n))}catch(e){out.frame_of.push(err(e))}}
  }
  const probes=Array.from(new Set([0,1,map.last_frame,...map.scenes.map(s=>s.start),...map.scenes.map(s=>Math.max(0,s.start-1))])).sort((a,b)=>a-b);
  out.transport=[];
  for(const f of probes)for(const playing of [false,true])for(const ended of [false,true]){
    const state=C.transport(f,playing,ended);
    const row=[st(C.play(map,state)),st(C.pause(map,state))];
    for(const [kind,value] of D.seeks){try{row.push(st(C.seek(map,state,kind,value===null?undefined:value)))}catch(e){row.push(err(e))}}
    out.transport.push(row);
  }
  out.tick=[];
  const starts=Array.from(new Set([...probes,...map.scenes.map(s=>s.start+Math.floor(s.length/2))])).sort((a,b)=>a-b);
  for(const f of starts)for(const playing of [false,true])for(const ended of [false,true]){
    const state=C.transport(f,playing,ended);
    map.scenes.forEach((span,i)=>{
      for(const n of [-1,0,Math.floor(span.duration_in_frames/2),span.duration_in_frames-1,span.duration_in_frames])
        for(const sceneEnded of [false,true]){try{out.tick.push(st(C.tick(map,state,i,n,sceneEnded)))}catch(e){out.tick.push(err(e))}}
    });
  }
  return out;
}
const results=D.cases.map(jsCase);
const wires=D.wires.map(w=>{
  const ok=C.fromWire(w.wire,{key:w.wire.key});
  const checks={total:ok.total_frames,key:ok.key};
  const forged=JSON.parse(JSON.stringify(w.wire));forged.scenes[forged.scenes.length-1].length+=1;forged.total_frames+=1;
  try{C.fromWire(forged,{key:forged.key})}catch(e){checks.forged=err(e)}
  try{C.fromWire(w.wire,{key:'cmp_other'})}catch(e){checks.other_key=err(e)}
  try{C.fromWire(Object.assign({},w.wire,{version:2}),{key:w.wire.key})}catch(e){checks.version=err(e)}
  try{C.fromWire(w.wire)}catch(e){checks.no_key=err(e)}
  try{C.fromWire(w.wire,{})}catch(e){checks.empty_key=err(e)}
  return checks;
});
return {results,wires};
"""


def _run_node(tmp_path: Path, data: dict[str, Any]) -> Any:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    data_file = tmp_path / "clock-data.json"
    data_file.write_text(json.dumps(data), encoding="utf-8")
    script = tmp_path / "clock.cjs"
    script.write_text(
        f"const PATHS={json.dumps({'clock': str(CLOCK_JS)})};\n"
        f"const D=JSON.parse(require('fs').readFileSync({json.dumps(str(data_file))},'utf8'));\n"
        "const run=()=>{" + JS_DRIVER + "};\n"
        "process.stdout.write(JSON.stringify(run()));\n", encoding="utf-8")
    result = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_python_and_js_give_the_same_answer_for_every_vector(tmp_path):
    expected = [_py_case(case) for case in CASES]
    wires = [{"name": c["name"], "wire": r["wire"]} for c, r in zip(CASES, expected) if "wire" in r]
    js = _run_node(tmp_path, {"cases": CASES, "seeks": [[k, v] for k, v in SEEKS], "wires": wires})
    for case, py, got in zip(CASES, expected, js["results"]):
        py = {k: v for k, v in py.items() if k != "wire"}
        for part in py:
            assert got[part] == py[part], f"{case['name']}: {part} differs between Python and JS"
    assert [r["build"].get("error") for r in expected] == [None, None, None, None, None, None, "composition_empty",
                                                            "composition_scene_invalid", "composition_scene_invalid",
                                                            "composition_scene_invalid", "composition_transition_invalid",
                                                            "composition_transition_invalid"]
    for wire, checks in zip(wires, js["wires"]):
        assert checks["total"] == wire["wire"]["total_frames"] and checks["key"] == "cmp_test"
        assert checks["forged"] == {"error": "composition_wire_mismatch"}          # a map that does not add up is refused
        assert checks["other_key"] == {"error": "composition_wire_mismatch"}       # a stale or foreign map is never reused
        assert checks["version"] == {"error": "composition_wire_mismatch"}
        assert checks["no_key"] == checks["empty_key"] == {"error": "composition_key_required"}   # the stale-map check cannot be skipped

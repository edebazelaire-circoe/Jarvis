"""Variables typées d'une scène Remotion éditées en direct, dans le VRAI Control Center, un VRAI Chrome, un Core isolé (Slice 13).

Opt-in comme `test_remotion_player_realpage_browser.py` (même banc, même harnais `scripts/remotion_player_harness.py`) : exige une
installation Remotion existante (`JARVIS_REMOTION_RUNTIME_DIR`), Node et Chrome ; sans eux ces épreuves sont ignorées.

Prouvé (mesuré, dans le bac à sable) : `control.set` sur une couleur, un texte, un espacement, un décalage (stagger) et une série de
données met le Player à jour **sans remontage ni rendu** (le même document du bac à sable : un marqueur tiré à l'évaluation du
module survit, même génération de la page de scène, un seul cadre, aucune nouvelle description ni compilation au journal) ; une valeur
hors bornes est refusée par Core (rien ne change) ; des valeurs piégées envoyées à la page de scène (`__proto__`, couleur invalide,
clé inconnue) ne traversent jamais (la scène garde ses dernières valeurs valides, la page compte et dit le refus) ; une valeur ou une
base périmée est rejetée (CAS) ; `control.reset` rend le défaut ; l'état enregistré est celui des seules éditions validées.
"""

from __future__ import annotations

import json

import pytest

from tests.fakes.remotion_player_stack import RemotionStack
from tests.unit.test_remotion_player_realpage_browser import (
    A, READY, RUNTIME, SANDBOX, SHELL, STAGE, control, edit_step, http_step, noise, record_evidence, run, scene,
)

pytestmark = pytest.mark.skipif(RUNTIME is None, reason="needs JARVIS_REMOTION_RUNTIME_DIR (an existing Remotion install), node and Chrome")

S1 = "pss_000000000001"
SCENE_TSX = """import React from "react";
import {AbsoluteFill, useCurrentFrame} from "remotion";

const mounted = String(Math.random());   // evaluated once per sandbox document: a reload or a remount changes it

export default function Scene(props: {title: string; accent: string; gap: number; stagger: number; data?: {series: number[]}}) {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{background: "#101820", padding: props.gap}}>
      <h1 id="title" style={{color: props.accent}}>{props.title}</h1>
      <p id="gap" style={{color: "#fff"}}>{String(props.gap)}</p>
      <p id="stagger" style={{color: "#fff"}}>{String(props.stagger)}</p>
      <p id="series" style={{color: "#fff"}}>{(props.data?.series ?? []).join(",")}</p>
      <p id="mark" style={{color: "#fff"}}>{mounted}</p>
      <p id="frame" style={{color: "#fff"}}>{String(frame)}</p>
    </AbsoluteFill>
  );
}
"""
PROPS = {"type": "object", "properties": {"title": {"type": "string", "default": "Bonjour", "max_length": 80},
                                          "accent": {"type": "color", "default": "#3366ff"},
                                          "gap": {"type": "integer", "default": 8, "min": 0, "max": 100},
                                          "stagger": {"type": "number", "default": 2, "min": 0, "max": 30}}}
DATA = {"type": "object", "properties": {"series": {"type": "array", "max_items": 5, "default": [], "items": {"type": "number"}}}}
SAMPLE = {"props": {"title": "Bonjour", "accent": "#3366ff", "gap": 8, "stagger": 2}, "data": {"series": [1]}}
CONTROLS = [
    {"control_id": "headline", "path": "props.title", "label": "Titre", "group": "content"},
    {"control_id": "accent", "path": "props.accent", "label": "Accent", "group": "visual", "default": "#3366ff"},
    {"control_id": "gap", "path": "props.gap", "label": "Écart", "group": "layout", "bounds": {"min": 0, "max": 60}},
    {"control_id": "stagger", "path": "props.stagger", "label": "Décalage", "group": "motion"},
    {"control_id": "series", "path": "data.series", "label": "Série", "group": "content"},
]

TITLE = "document.querySelector('#title').textContent"
LOOK = ("(()=>{const t=document.querySelector('#title');return {title:t.textContent,color:getComputedStyle(t).color,"
        "gap:document.querySelector('#gap').textContent,stagger:document.querySelector('#stagger').textContent,"
        "series:document.querySelector('#series').textContent,padding:getComputedStyle(document.querySelector('#title').parentElement).paddingTop,"
        "mark:document.querySelector('#mark').textContent}})()")
GEN = f"{STAGE}.contentWindow.__remotionStage.state().generation"
REFUSED = f"{STAGE}.contentWindow.__remotionStage.state().propsRefused"
# the hostile messages a page of the user's own origin could post to the stage page (only the window host is allowed to)
HOSTILE = """(async()=>{const w=document.querySelector('iframe[data-remotion-stage]').contentWindow;const o=location.origin;
  const nap=()=>new Promise(r=>setTimeout(r,80));   // the stage coalesces a burst (the last wins): space them so each one is judged
  const send=async(props,data)=>{w.postMessage(Object.assign({rsh:1,type:'props',props},data?{data}:{}),o);await nap()};
  await send({accent:'red'});await send({gap:9999});await send({unknown:1});await send(JSON.parse('{"__proto__":{"polluted":true}}'));
  await send({title:'x'},JSON.parse('{"series":[1],"constructor":{"prototype":{}}}'));await send({stagger:'fast'});return 6})()"""


def a_scene(scene_id: str = S1) -> dict:
    return {**scene(scene_id, A, "Premier"), "props": {"title": "Premier", "accent": "#3366ff", "gap": 8, "stagger": 2},
            "data": {"series": [1]}, "controls": CONTROLS}


async def test_typed_variables_update_the_player_without_a_remount_or_a_render_and_unsafe_ones_never_cross(tmp_path):
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        # the data block is part of the published manifest (the stack helper publishes props only)
        from jarvis.adapters.remotion_compiler import shipped_engine_pin
        from tests.fakes.remotion_scene import scene_candidate
        await stack.core.prefabs.save(scene_candidate(A, engine=shipped_engine_pin(), title="Un", files={"src/Scene.tsx": SCENE_TSX},
                                                      props=PROPS, data=DATA, sample=SAMPLE), actor="user")
        pid, vid = await stack.presentation([a_scene()])
        status, started = await stack.start(pid)
        assert status == 200 and started["state"]["phase"] == "playing", started
        variants = f"/v1/presentation-studio/presentations/{pid}/variants/{vid}"
        shot_before, shot_after = str(tmp_path / "controls_before.png"), str(tmp_path / "controls_after.png")
        result = await run(stack.page_url, [
            {"wait": 500}, READY, {"wait": 800},
            {"value": "initial", "expr": LOOK, **SANDBOX},
            {"value": "generation_before", "expr": GEN},
            {"shot": shot_before},
            # --- colour, text, spacing, stagger and data in ONE control.set transaction (the voice and the inspector send this very op)
            edit_step(stack, "edit1", control(S1, "accent", "#ff0000"), control(S1, "headline", "Titre modifié"),
                      control(S1, "gap", 40), control(S1, "stagger", 5.5), control(S1, "series", [3, 1, 4])),
            {"until": "document.querySelector('#series').textContent==='3,1,4'", "ms": 8000, **SANDBOX},
            {"value": "after_edit", "expr": LOOK, **SANDBOX},
            {"shot": shot_after},
            # --- Core refuses a value outside the control's bounds: nothing changes on screen
            edit_step(stack, "too_big", control(S1, "gap", 500)),
            edit_step(stack, "bad_colour", control(S1, "accent", "red")),
            edit_step(stack, "bad_series", control(S1, "series", [1, 2, 3, 4, 5, 6])),
            {"wait": 400},
            {"value": "after_refusals", "expr": LOOK, **SANDBOX},
            # --- hostile values posted straight to the stage page never cross into the sandbox
            {"value": "hostile_sent", "expr": HOSTILE},
            {"wait": 300},
            {"value": "after_hostile", "expr": LOOK, **SANDBOX},
            {"value": "refused_count", "expr": REFUSED},
            {"value": "stage_phase", "expr": SHELL},
            {"value": "polluted", "expr": "({}).polluted===undefined", **SANDBOX},
            # --- CAS: a base that moved and a value that moved are both rejected, nothing applied
            http_step(stack, "stale_base", "POST", variants + "/edits",
                      {"actor": "user", "mode": "commit", "basis": {"variant_revision": 1}, "ops": [control(S1, "gap", 12)]}),
            edit_step(stack, "stale_value", {**control(S1, "gap", 12), "if_current": 7}),
            {"wait": 400},
            {"value": "after_stale", "expr": LOOK, **SANDBOX},
            # --- inspector reset semantics: control.reset gives back the curated default (colour) or the manifest default (title)
            edit_step(stack, "reset", {"op": "control.reset", "scene_id": S1, "control_id": "accent", "if_current": "#ff0000"},
                      {"op": "control.reset", "scene_id": S1, "control_id": "headline"}),
            {"until": f"{TITLE}==='Bonjour'", "ms": 8000, **SANDBOX},
            {"value": "after_reset", "expr": LOOK, **SANDBOX},
            # --- the whole time: one stage frame, same page-of-the-scene generation, same sandbox document
            {"value": "generation_after", "expr": GEN},
            {"value": "frames", "expr": "document.querySelectorAll('iframe[data-remotion-stage]').length"},
            {"value": "shell", "expr": SHELL},
        ])
        reads = result["reads"]
        assert "failed" not in reads, reads
        assert reads["initial"]["title"] == "Premier" and reads["initial"]["color"] == "rgb(51, 102, 255)" and reads["initial"]["gap"] == "8"
        assert reads["initial"]["series"] == "1" and reads["initial"]["padding"] == "8px"
        for name in ("edit1", "reset"):
            assert reads[name]["status"] == 200, (name, reads[name])
        assert reads["after_edit"] == {**reads["after_edit"], "title": "Titre modifié", "color": "rgb(255, 0, 0)", "gap": "40", "stagger": "5.5",
                                       "series": "3,1,4", "padding": "40px"}, "colour, text, spacing, stagger and data all landed"
        assert reads["after_edit"]["mark"] == reads["initial"]["mark"], "the sandbox document was not reloaded: no remount, no render"
        for name in ("too_big", "bad_colour", "bad_series"):
            assert reads[name]["status"] in (400, 409) and reads[name]["body"].get("status") != "applied", (name, reads[name])
        assert reads["after_refusals"] == reads["after_edit"], "a refused value changes nothing on screen"
        assert reads["hostile_sent"] == 6 and reads["refused_count"] >= 6, "every hostile message was refused by the page of the scene"
        assert reads["after_hostile"] == reads["after_edit"], "none of them reached the scene; it kept its last valid values"
        assert reads["polluted"] is True and reads["stage_phase"]["phase"] == "ready"
        assert reads["stale_base"]["status"] == 409 and reads["stale_base"]["body"]["status"] == "stale", reads["stale_base"]
        assert reads["stale_value"]["status"] == 409 and reads["stale_value"]["body"]["status"] == "refused"
        assert "no longer what the edit expected" in json.dumps(reads["stale_value"]["body"]), "the stale value is named, not applied"
        assert reads["after_stale"]["gap"] == "40", "neither a stale base nor a stale value was applied"
        assert reads["after_reset"]["color"] == "rgb(51, 102, 255)" and reads["after_reset"]["title"] == "Bonjour"
        assert reads["after_reset"]["gap"] == "40" and reads["after_reset"]["mark"] == reads["initial"]["mark"]
        assert reads["generation_after"] == reads["generation_before"] and reads["frames"] == 1
        assert not noise(result), noise(result)
        # the saved state is the validated edits only
        status, variant = await stack.call("GET", variants)
        assert status == 200, variant
        saved = next(item for item in variant["scenes"] if item["scene_id"] == S1)
        assert saved["props"].get("gap") == 40 and saved["props"].get("stagger") == 5.5 and saved["data"] == {"series": [3, 1, 4]}
        assert saved["props"].get("accent") == "#3366ff" and "title" not in saved["props"], "reset: curated default written, other key unset"
        kinds = stack.kinds()
        trace = [row["kind"] for row in stack.trace()]
        assert kinds.count("core.remotion_player.described") == 1 and kinds.count("remotion.compile.done") <= 2, \
            "ten edits, no new description and no recompilation: nothing was rendered or rebuilt"
        assert "remotion.stage.props_rejected" in trace, "the refusals are journalled by the page of the scene"
        record_evidence("typed_controls", {"reads": reads, "console": result["console"][-30:], "errors": result["errors"],
                                           "journal": sorted(set(kinds) | set(trace)),
                                           "described": kinds.count("core.remotion_player.described"),
                                           "compiled": kinds.count("remotion.compile.done"), "saved_scene": saved}, shot_before, shot_after)

"""L'inspecteur du Studio sur la VRAIE page du Control Center, avec un VRAI Core et un VRAI Chrome (jarvis-interactive-presentation-studio, Slice 07).

Rien n'est simule sauf l'ecran sans tete (`tests/fakes/presentation_studio_inspector_browser.py`) : Core isole (racine de donnees et ports
a lui, jamais le Jarvis vivant), Control Center reel, prefab `custom` publie par la vraie route, gestes de souris et touches CDP reels.

Prouve de bout en bout : les widgets generes de l'introspection (un par type), le glissement d'un curseur (le cadre d'apercu bouge, RIEN
n'est ecrit tant que la poignee n'est pas relachee : empreinte du fichier de la variante), UN enregistrement au relachement identique a
l'ordre equivalent de l'agent (parite voix / interface, octet pour octet), annuler / retablir, la base perimee, le rechargement 409, la
lecture en cours (inspecteur cache, touches au lecteur), l'accessibilite et deux tailles d'ecran.

Les captures d'ecran sont ecrites dans `JARVIS_INSPECTOR_SHOTS` quand la variable est posee (sinon dans `tmp_path`).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re

import pytest

from tests.fakes.presentation_studio_inspector_browser import (
    CONTROLS, PREVIEW_OBJECT, S1, S2, S3, InspectorRig, drive,
)
from tests.unit.test_presentation_studio_playback_routes import score

pytestmark = pytest.mark.asyncio

PANEL = "#jvStudioInspector"
VIEW = "JarvisStudioInspector.instance.view()"
STATS = "JarvisStudioInspector.instance.stats()"
OPEN = [{"click": "#openStudioInspector"},
        {"until": "!!document.querySelector('#jvStudioInspector [data-control-id=\"size\"]')", "ms": 20000},
        {"wait": 300}]


def row(control_id: str) -> str:
    return f'{PANEL} [data-control-id="{control_id}"]'


def range_of(control_id: str) -> str:
    return f"{row(control_id)} input[type=range]"


def tab(group: str) -> dict:
    return {"click": f"#jviTab-{group}"}


#: The browser itself logs every 4xx answer of a fetch: a typed refusal or a stale base (HTTP 400/409) is a designed answer, not noise.
HTTP_REFUSAL = "Failed to load resource: the server responded with a status of 4"


def noise(result: dict, expected: tuple[str, ...] = ()) -> list:
    """Errors and warnings are noise; the inspector's own `[studio-inspector]` info trail is not. `expected`: substrings a test provokes on purpose."""

    lines = [c for c in result["console"] if c["type"] in ("error", "warning", "exception", "log-error", "log-warning", "assert")
             and "favicon.ico" not in c["text"]           # the served page has no icon: baseline noise of every Control Center page
             and not any(item in c["text"] for item in expected)]
    return result["errors"] + lines


def shots_dir(tmp_path: Path) -> Path:
    target = os.environ.get("JARVIS_INSPECTOR_SHOTS")
    if target:
        Path(target).mkdir(parents=True, exist_ok=True)
        return Path(target)
    return tmp_path


def select_and_type(control_id: str, text: str, selector: str = "input[type=text]") -> list:
    field = f"{row(control_id)} {selector}"
    return [{"eval": f"(()=>{{const f=document.querySelector({json.dumps(field)});f.focus();f.select()}})()"}, {"type": text}]


MASKS = (re.compile(r'"(presentation_id|variant_id|art_direction_id|score_id)": "[^"]*"'), re.compile(r'"revision": \d+'),
         re.compile(r'"(created_at|updated_at)": "[^"]*"'))


def durable(path: Path) -> str:
    """The stored variant document with the revision metadata and the per-presentation ids masked: what must be identical."""

    text = path.read_text(encoding="utf-8")
    for pattern in MASKS:
        text = pattern.sub(lambda m: f'"{m.group(1) if m.lastindex else "revision"}": MASKED', text)
    return text


# ------------------------------------------------------------------ rendu, accessibilite

async def test_the_panel_renders_a_widget_per_type_from_the_introspection_with_no_console_noise(tmp_path):
    async with InspectorRig(tmp_path) as rig:
        result = await drive(rig.url, [
            *OPEN,
            {"value": "rows", "expr": f"[...document.querySelectorAll('{PANEL} [data-control-id]')].map(e=>e.dataset.controlId)"},
            {"value": "kinds", "expr": f"""Object.fromEntries([...document.querySelectorAll('{PANEL} [data-control-id]')].map(r=>[r.dataset.controlId,
              [...r.querySelectorAll('input,textarea,select,button')].filter(n=>!n.classList.contains('jvi-reset')).map(n=>n.tagName.toLowerCase()+(n.type&&n.tagName==='INPUT'?':'+n.type:'')+(n.getAttribute('role')?'#'+n.getAttribute('role'):''))]))"""},
            {"value": "tabs", "expr": f"[...document.querySelectorAll('{PANEL} [role=tab]')].map(t=>[t.textContent,t.getAttribute('aria-selected')])"},
            {"value": "chip", "expr": f"document.querySelector('{PANEL} .jvi-da').textContent"},
            {"value": "geometry", "expr": f"(()=>{{const r=document.querySelector('{PANEL}').getBoundingClientRect();return [Math.round(r.left),Math.round(r.top),Math.round(r.width),Math.round(r.height)]}})()"},
            {"value": "dock", "expr": "(()=>{const b=document.getElementById('openStudioInspector');return [b.getAttribute('aria-expanded'),b.classList.contains('active')]})()"},
            {"value": "stats", "expr": f"JSON.stringify({STATS})"},
        ])
        reads = result["reads"]
        assert "failed" not in reads, reads
        assert reads["rows"] == [c["control_id"] for c in CONTROLS]
        kinds = reads["kinds"]
        assert kinds["size"][0] == "input:range" and kinds["tilt"][0] == "input:range" and kinds["delay"] == ["button", "input:number", "button"]
        assert kinds["glow"] == ["button#switch"] and kinds["layout"] == ["button#radio"] * 3 and kinds["easing"] == ["select"]
        assert kinds["accent"] == ["input:color", "input:text"] and kinds["palette"].count("input:color") == 2 and kinds["tags"] == ["textarea"]
        assert reads["tabs"] == [["Contenu5", "true"], ["Style3", "false"], ["Mise en page3", "false"], ["Mouvement3", "false"]]
        assert "Fallback" in reads["chip"] and "contraste" in reads["chip"]
        assert reads["geometry"][0] + reads["geometry"][2] <= 1280 - 60 and reads["geometry"][1] >= 0, "docked left of the dock buttons, inside the page"
        assert reads["dock"] == ["true", True]
        assert not noise(result), noise(result)
        info = [c["text"] for c in result["console"] if c["text"].startswith("[studio-inspector]")]
        assert any("opened" in line for line in info) and any("scene_loaded" in line and '"controls":14' in line for line in info)


async def test_accessibility_every_control_is_named_focusable_in_order_and_contrast_holds(tmp_path):
    async with InspectorRig(tmp_path) as rig:
        plan: list = [*OPEN]
        for group in ("content", "visual", "layout", "motion"):
            plan += [tab(group), {"wait": 150}, {"ax": f"ax_{group}", "root": f"{PANEL} [role=tabpanel]:not([hidden])"}]
        plan += [
            {"ax": "ax_chrome", "root": PANEL},
            {"value": "contrast", "expr": """(()=>{
              const lin=c=>{c/=255;return c<=0.03928?c/12.92:Math.pow((c+0.055)/1.055,2.4)};
              const lum=([r,g,b])=>0.2126*lin(r)+0.7152*lin(g)+0.0722*lin(b);
              const parse=s=>{const m=s.match(/[\\d.]+/g).map(Number);return {rgb:m.slice(0,3),a:m.length>3?m[3]:1}};
              const page=[5,8,11], panel=parse(getComputedStyle(document.getElementById('jvStudioInspector')).backgroundColor);
              const base=panel.rgb.map((c,i)=>c*panel.a+page[i]*(1-panel.a));
              const out=[];
              for(const sel of ['.jvi-title','.jvi-label','.jvi-meaning','.jvi-state','.jvi-default','.jvi-count','.jvi-tab','.jvi-field','.jvi-chip','.jvi-theme li']){
                for(const el of document.querySelectorAll('#jvStudioInspector '+sel)){
                  if(!el.offsetParent&&el.tagName!=='LI')continue;
                  const fg=parse(getComputedStyle(el).color);
                  const bg=getComputedStyle(el).backgroundColor==='rgba(0, 0, 0, 0)'?base:parse(getComputedStyle(el).backgroundColor).rgb;
                  const f=fg.rgb.map((c,i)=>c*fg.a+bg[i]*(1-fg.a));
                  const [a,b]=[lum(f),lum(bg)].sort((x,y)=>y-x);
                  out.push([sel,Math.round((a+0.05)/(b+0.05)*100)/100]);
                }
              }
              return out})()"""},
            {"value": "tab_order", "expr": f"""(()=>{{const items=[...document.querySelectorAll('{PANEL} button,{PANEL} input,{PANEL} select,{PANEL} textarea,{PANEL} summary')]
              .filter(n=>!n.disabled&&n.tabIndex>=0&&n.offsetParent!==null);
              return items.slice(0,12).map(n=>n.getAttribute('aria-label')||n.id||n.textContent.slice(0,16))}})()"""},
            {"focus": f"{PANEL} .jvi-icon:not(:disabled), {PANEL} .jvi-title"}, {"key": "Tab"}, {"key": "Tab"},
            {"value": "focus_ring", "expr": f"""(()=>{{const b=document.activeElement;const cs=getComputedStyle(b);return [b.className||b.tagName,cs.outlineStyle,cs.outlineWidth]}})()"""},
            {"axe": "axe", "root": PANEL},
        ]
        result = await drive(rig.url, plan)
        reads = result["reads"]
        assert "failed" not in reads, reads
        interactive = {"button", "slider", "textbox", "combobox", "switch", "radio", "tab", "spinbutton", "checkbox", "searchbox", "link"}
        unnamed = []
        seen_roles = set()
        for key in ("ax_content", "ax_visual", "ax_layout", "ax_motion", "ax_chrome"):
            for node in reads[key]:
                if node["role"] in interactive:
                    seen_roles.add(node["role"])
                    if not node["name"].strip():
                        unnamed.append((key, node["role"]))
        assert not unnamed, f"interactive elements without an accessible name: {unnamed}"
        assert {"slider", "textbox", "switch", "radio", "combobox", "tab", "button", "spinbutton"} <= seen_roles, seen_roles
        names = [n["name"] for n in reads["ax_layout"]]
        assert any(name == "Taille (curseur)" for name in names) and any(name == "Taille" for name in names)
        switch = next(n for n in reads["ax_visual"] if n["role"] == "switch")
        assert switch["name"] == "Halo"
        low = [(sel, ratio) for sel, ratio in reads["contrast"] if ratio < 4.5]
        assert reads["contrast"] and not low, f"text under 4.5:1 : {low}"
        assert reads["tab_order"][:3] == ["Annuler la dernière modification", "Rétablir la modification annulée", "Fermer l'inspecteur"] or \
            "Annuler la dernière modification" not in reads["tab_order"], reads["tab_order"]
        assert reads["focus_ring"][1] != "none" and reads["focus_ring"][2] != "0px", f"a visible focus ring after Tab: {reads['focus_ring']}"
        if reads["axe"] is not None:
            assert reads["axe"] == [], reads["axe"]
        assert not noise(result), noise(result)


# ------------------------------------------------------------------ geste, apercu, une ecriture

async def test_dragging_a_slider_moves_the_preview_frame_writes_nothing_and_release_writes_once(tmp_path):
    async with InspectorRig(tmp_path) as rig:
        file = rig.variant_file()
        _, before = await rig.core.call("GET", f"/{rig.pid}/variants/{rig.vid}")
        slider = range_of("size")
        result = await drive(rig.url, [
            *OPEN, tab("layout"), {"wait": 200},
            {"frameUntil": {"object_id": PREVIEW_OBJECT, "expr": "document.documentElement.style.getPropertyValue('--size')==='1'", "ms": 15000}},
            {"hashFile": "h0", "path": str(file)},
            {"mouseDown": {"selector": slider, "frac": 0.2}},
            {"mouseMove": {"selector": slider, "frac": 0.4}}, {"mouseMove": {"selector": slider, "frac": 0.6}},
            {"mouseMove": {"selector": slider, "frac": 0.8}},
            {"wait": 600},
            {"frameValue": "frame_size", "object_id": PREVIEW_OBJECT, "expr": "document.documentElement.style.getPropertyValue('--size')"},
            {"value": "drag_state", "expr": f"JSON.stringify({{stats:{STATS},draft:{VIEW}.pendingDrafts,number:document.querySelector('{row('size')} input[type=number]').value,"
                                          f"label:document.querySelector('{row('size')} .jvi-state').textContent}})"},
            {"hashFile": "h_mid", "path": str(file)},
            {"value": "revision_mid", "expr": f"fetch('/api/presentation-studio/presentations/{rig.pid}/variants/{rig.vid}').then(r=>r.json()).then(v=>v.revision)"},
            {"value": "shown_mid", "expr": f"fetch('/api/presentation-studio/presentations/{rig.pid}/variants/{rig.vid}/scenes/{S1}/controls').then(r=>r.json()).then(v=>v.controls.find(c=>c.control_id==='size').current)"},
            {"shot": str(shots_dir(tmp_path) / "drag-1280x720.png")},
            {"mouseUp": {"selector": slider, "frac": 0.8}},
            {"wait": 1200},
            {"hashFile": "h_end", "path": str(file)},
            {"value": "end_state", "expr": f"JSON.stringify({{stats:{STATS},draft:{VIEW}.pendingDrafts,size:{VIEW}.controls.find(c=>c.control_id==='size'),history:{VIEW}.history,"
                                         f"saved:document.querySelector('{row('size')} .jvi-state').textContent}})"},
            {"frameValue": "frame_end", "object_id": PREVIEW_OBJECT, "expr": "document.documentElement.style.getPropertyValue('--size')"},
        ])
        reads = result["reads"]
        assert "failed" not in reads, reads
        assert reads["h_mid"] == reads["h0"], "mid-drag: the variant file is byte-identical, nothing was written"
        assert reads["revision_mid"] == before["revision"] and reads["shown_mid"] == 1, "Core still holds the old value and revision"
        assert abs(float(reads["frame_size"]) - 1.56) < 0.02, f"the preview frame follows the finger live: {reads['frame_size']}"
        mid = json.loads(reads["drag_state"])
        assert mid["stats"]["commits"] == 0 and 1 <= mid["stats"]["previews"] <= 8 and mid["draft"] == ["size"]
        assert "non enregistré" in mid["label"] and float(mid["number"]) == 1.56
        assert reads["h_end"] != reads["h0"], "the release wrote the document"
        end = json.loads(reads["end_state"])
        assert end["stats"]["commits"] == 1 and end["size"] == {"control_id": "size", "current": 1.56, "is_set": True}
        assert end["history"] == {"undo": 1, "redo": 0} and end["draft"] == []
        assert float(reads["frame_end"]) == 1.56
        _, after = await rig.core.call("GET", f"/{rig.pid}/variants/{rig.vid}")
        assert after["revision"] == before["revision"] + 1, "exactly one revision for the whole gesture"
        assert after["scenes"][0]["props"]["size"] == 1.56
        assert not noise(result), noise(result)
        trace = [e for e in rig.core.stack.trace() if e.get("kind") == "presentation_studio.request.relayed"]
        modes = [(e["data"]["action"], e["data"]["mode"]) for e in trace if e["data"]["action"] == "studio_edit"]
        assert modes.count(("studio_edit", "commit")) == 1 and modes.count(("studio_edit", "preview")) >= 1


async def test_a_gui_edit_and_the_equivalent_agent_edit_leave_the_same_durable_document(tmp_path):
    """Acceptance: the user visually tunes parameters and gets exactly what the same Jarvis command gives (actor user vs brain)."""

    async with InspectorRig(tmp_path) as rig:
        plan = [
            *OPEN,
            tab("layout"), {"drag": {"selector": range_of("size"), "from": 0.2, "to": 0.8, "steps": 12, "ms": 10}}, {"wait": 900},
            tab("visual"), {"click": f"{row('glow')} [role=switch]"}, {"wait": 500},
            *select_and_type("accent", "#ff8800"), {"key": "Enter"}, {"wait": 600},
            tab("layout"), {"click": f'{row("layout")} [role=radio][data-value="right"]'}, {"wait": 500},
            tab("content"), *select_and_type("title", "Nouveau titre"), {"key": "Enter"}, {"wait": 600},
            tab("motion"), *select_and_type("delay", "2.5", "input[type=number]"), {"key": "Enter"}, {"wait": 600},
            {"value": "stats", "expr": f"JSON.stringify({STATS})"},
        ]
        result = await drive(rig.url, plan)
        reads = result["reads"]
        assert "failed" not in reads, reads
        assert json.loads(reads["stats"])["commits"] == 6, reads["stats"]
        gui = json.loads(rig.variant_file().read_text(encoding="utf-8"))
        props = gui["scenes"][0]["props"]
        assert props["size"] == 1.56 and props["glow"] is True and props["accent"] == "#ff8800"
        assert props["layout"] == "right" and props["title"] == "Nouveau titre" and props["delay"] == 2.5
        twin, twin_vid, _ = await rig.new_presentation("Atelier du cadran")      # created after the page ran: the inspector edited `rig.pid`
        ops = [("size", props["size"]), ("glow", True), ("accent", "#ff8800"), ("layout", "right"), ("title", "Nouveau titre"), ("delay", 2.5)]
        for control_id, value in ops:
            applied = await rig.edit({"ops": [{"op": "control.set", "scene_id": S1, "control_id": control_id, "value": value}]},
                                     actor="brain", pid=twin, vid=twin_vid)
            assert applied["status"] == "applied" and applied["actor"] == "brain", applied
        assert durable(rig.variant_file()) == durable(rig.variant_file(twin, twin_vid)), \
            "the interface and the voice's door produce byte-identical documents (except revision metadata and ids)"
        assert not noise(result), noise(result)


async def test_reset_and_undo_redo_through_the_buttons_and_the_keyboard_match_the_history_routes(tmp_path):
    async with InspectorRig(tmp_path) as rig:
        result = await drive(rig.url, [
            *OPEN,
            tab("visual"), {"click": f"{row('glow')} [role=switch]"}, {"wait": 500},
            tab("layout"), {"click": f'{row("layout")} [role=radio][data-value="left"]'}, {"wait": 500},
            {"value": "two", "expr": f"JSON.stringify({VIEW}.history)"},
            {"click": f"{PANEL} [aria-label='Annuler la dernière modification']"}, {"wait": 700},
            {"value": "after_undo", "expr": f"JSON.stringify({{layout:{VIEW}.controls.find(c=>c.control_id==='layout'),history:{VIEW}.history}})"},
            tab("visual"), {"focus": f"{row('glow')} [role=switch]"}, {"key": "z", "ctrl": True}, {"wait": 700},
            {"value": "after_key", "expr": f"JSON.stringify({{glow:{VIEW}.controls.find(c=>c.control_id==='glow'),history:{VIEW}.history}})"},
            {"key": "y", "ctrl": True}, {"wait": 700},
            {"value": "after_redo", "expr": f"JSON.stringify({{glow:{VIEW}.controls.find(c=>c.control_id==='glow'),history:{VIEW}.history}})"},
            tab("layout"), {"click": f"{row('size')} .jvi-reset"}, {"wait": 600},
            {"value": "after_reset", "expr": f"JSON.stringify({{size:{VIEW}.controls.find(c=>c.control_id==='size'),history:{VIEW}.history}})"},
        ])
        reads = result["reads"]
        assert "failed" not in reads, reads
        assert json.loads(reads["two"]) == {"undo": 2, "redo": 0}
        undone = json.loads(reads["after_undo"])
        assert undone["layout"] == {"control_id": "layout", "current": "center", "is_set": False} and undone["history"] == {"undo": 1, "redo": 1}
        keyed = json.loads(reads["after_key"])
        assert keyed["glow"]["is_set"] is False and keyed["history"] == {"undo": 0, "redo": 2}
        redone = json.loads(reads["after_redo"])
        assert redone["glow"]["current"] is True and redone["history"] == {"undo": 1, "redo": 1}
        reset = json.loads(reads["after_reset"])
        assert reset["size"] == {"control_id": "size", "current": 1, "is_set": False}, "reset removes the key: the prefab's default shows"
        assert reset["history"] == {"undo": 2, "redo": 0}, "a reset is one more undoable step; a new edit clears redo"
        assert not noise(result), noise(result)


async def test_a_typed_refusal_shows_core_s_words_logs_it_and_the_relay_journals_the_status(tmp_path):
    async with InspectorRig(tmp_path) as rig:
        result = await drive(rig.url, [
            *OPEN,
            *select_and_type("code", "abc"), {"key": "Enter"}, {"wait": 800},
            {"value": "msg", "expr": f"document.querySelector('{row('code')} .jvi-msg').textContent"},
            {"value": "field", "expr": f"[document.querySelector('{row('code')} input').value,document.querySelector('{row('code')} input').getAttribute('aria-invalid')]"},
            {"value": "row_class", "expr": f"document.querySelector('{row('code')}').className"},
        ])
        reads = result["reads"]
        assert "failed" not in reads, reads
        assert "Valeur refusée par Core" in reads["msg"] and "code" in reads["msg"]
        assert reads["field"] == ["ABC", "true"] and "is-bad" in reads["row_class"]
        warn = [c["text"] for c in result["console"] if c["type"] == "warning" and "edit_refused" in c["text"]]
        assert warn and "presentation_studio_value_refused" in warn[0], result["console"][-6:]
        assert not noise(result, (HTTP_REFUSAL, "[studio-inspector] edit_refused")), noise(result)
        journal = [e for e in rig.core.stack.trace() if e.get("kind") == "presentation_studio.request.relayed" and e["data"]["action"] == "studio_edit"]
        assert journal and journal[-1]["data"]["status"] == 400 and journal[-1]["data"]["code"] == "presentation_studio_value_refused"
        _, variant = await rig.core.call("GET", f"/{rig.pid}/variants/{rig.vid}")
        assert "code" not in variant["scenes"][0]["props"], "a refused edit wrote nothing"


async def test_a_change_made_through_the_api_in_between_is_reported_as_stale_and_never_overwritten(tmp_path):
    async with InspectorRig(tmp_path) as rig:
        edit_url = f"/api/presentation-studio/presentations/{rig.pid}/variants/{rig.vid}/edits"
        other = ("fetch(%s,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:'commit',"
                 "basis:{variant_revision:%s.revision},ops:[{op:'control.set',scene_id:%s,control_id:'accent',value:'#00ff00'},"
                 "{op:'control.set',scene_id:%s,control_id:'size',value:1.25}]})}).then(r=>r.json()).then(j=>j.status)"
                 % (json.dumps(edit_url), VIEW, json.dumps(S1), json.dumps(S1)))
        slider = range_of("size")
        result = await drive(rig.url, [
            *OPEN, tab("layout"), {"wait": 200},
            {"mouseDown": {"selector": slider, "frac": 0.2}}, {"mouseMove": {"selector": slider, "frac": 0.7}}, {"wait": 500},
            {"value": "other", "expr": other},                 # the "voice" edits the same scene while the thumb is held
            {"mouseUp": {"selector": slider, "frac": 0.7}}, {"wait": 1200},
            {"value": "msg", "expr": f"document.querySelector('{row('size')} .jvi-msg').textContent"},
            {"value": "state", "expr": f"JSON.stringify({{size:{VIEW}.controls.find(c=>c.control_id==='size'),accent:{VIEW}.controls.find(c=>c.control_id==='accent').current,stats:{STATS}}})"},
            {"click": f"{row('size')} .jvi-msg button"}, {"wait": 1000},
            {"value": "reapplied", "expr": f"JSON.stringify({VIEW}.controls.find(c=>c.control_id==='size'))"},
        ])
        reads = result["reads"]
        assert "failed" not in reads, reads
        assert reads["other"] == "applied"
        state = json.loads(reads["state"])
        assert "Valeurs relues" in reads["msg"] and ("n'a pas été appliqué" in reads["msg"] or "pendant votre réglage" in reads["msg"])
        assert state["accent"] == "#00ff00", "the other writer's change is shown, not lost"
        assert state["stats"]["staleHandled"] >= 1
        _, variant = await rig.core.call("GET", f"/{rig.pid}/variants/{rig.vid}")
        assert variant["scenes"][0]["props"]["accent"] == "#00ff00"
        assert not noise(result, (HTTP_REFUSAL, "[studio-inspector] edit_stale")), noise(result)


async def test_a_scene_being_reloaded_answers_409_and_the_inspector_waits_visibly_then_commits(tmp_path):
    async with InspectorRig(tmp_path) as rig:
        service = rig.core.stack.core.presentation_studio
        attempts = {"n": 0}

        def busy(presentation_id: str, variant_id: str, scene_id: str) -> bool:
            attempts["n"] += 1
            return attempts["n"] <= 2           # the first two write attempts meet a scene whose source is reloading

        service.set_scene_guard(busy)
        result = await drive(rig.url, [
            *OPEN, tab("visual"),
            {"click": f"{row('glow')} [role=switch]"},
            {"until": f"!!{VIEW}.reloading", "ms": 6000},
            {"value": "waiting", "expr": f"JSON.stringify({{reloading:{VIEW}.reloading,status:document.querySelector('{PANEL} .jvi-status:not([hidden])').textContent,"
                                         f"spin:!document.querySelector('{PANEL} .jvi-spin').hidden}})"},
            {"shot": str(shots_dir(tmp_path) / "reloading-1280x720.png")},
            {"until": f"{VIEW}.controls.find(c=>c.control_id==='glow').current===true", "ms": 15000},
            {"value": "end", "expr": f"JSON.stringify({{reloading:{VIEW}.reloading,stats:{STATS},glow:{VIEW}.controls.find(c=>c.control_id==='glow')}})"},
        ])
        service.set_scene_guard(None)
        reads = result["reads"]
        assert "failed" not in reads, reads
        waiting = json.loads(reads["waiting"])
        assert waiting["reloading"]["max"] == 5 and "Rechargement en cours" in waiting["status"] and waiting["spin"] is True
        end = json.loads(reads["end"])
        assert end["glow"]["current"] is True and end["reloading"] is None and end["stats"]["commits"] == 1 and end["stats"]["reloadRetries"] >= 1
        _, variant = await rig.core.call("GET", f"/{rig.pid}/variants/{rig.vid}")
        assert variant["scenes"][0]["props"]["glow"] is True
        assert not noise(result, (HTTP_REFUSAL, "[studio-inspector] reload_wait")), noise(result)


# ------------------------------------------------------------------ lecture en cours

async def test_while_a_run_plays_the_inspector_is_hidden_and_inert_and_the_keys_go_to_the_player(tmp_path):
    async with InspectorRig(tmp_path) as rig:
        status, made = await rig.core.call("POST", f"/{rig.pid}/variants/{rig.vid}/score", json=score((await rig.core.call("GET", f"/{rig.pid}/variants/{rig.vid}"))[1]["revision"]))
        assert status == 201, made
        start = json.dumps({"presentation_id": rig.pid, "role": "user_presenter"})
        stage = '[data-object-id^="studio-stage-"]'
        pos = "(window.JarvisStudioPlayer.view().position||{}).index"
        result = await drive(rig.url, [
            *OPEN,
            {"value": "before", "expr": f"[{VIEW}.open,document.getElementById('jvStudioInspector').hidden]"},
            {"value": "start", "expr": f"fetch('/api/presentation-studio/playback/start',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:{json.dumps(start)}}}).then(r=>r.json()).then(j=>j.status)"},
            {"until": f"!!document.querySelector('{stage}') && {VIEW}.available===false", "ms": 20000},
            {"wait": 400},
            {"value": "hidden", "expr": f"""(()=>{{const p=document.getElementById('jvStudioInspector');const b=document.getElementById('openStudioInspector');
              const r=p.getBoundingClientRect();return {{hidden:p.hidden,inert:p.inert,display:getComputedStyle(p).display,w:r.width,dockDisabled:b.disabled,title:b.title,
              reason:{VIEW}.hiddenReason,open:{VIEW}.open,phase:window.JarvisStudioPlayer.view().phase}}}})()"""},
            {"click": f"{stage} .sc-wtitle"},
            {"value": "p0", "expr": pos}, {"key": "ArrowRight"}, {"until": f"{pos}===2", "ms": 8000},
            {"value": "p1", "expr": pos}, {"key": "End"}, {"until": f"{pos}===3", "ms": 8000},
            {"value": "p2", "expr": pos},
            {"value": "stat", "expr": f"JSON.stringify({STATS})"},
            {"shot": str(shots_dir(tmp_path) / "playback-hidden-1280x720.png")},
            {"value": "stop", "expr": "fetch('/api/presentation-studio/playback/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).then(r=>r.json()).then(j=>j.status)"},
            {"until": f"{VIEW}.available===true", "ms": 15000},
            {"value": "after", "expr": f"[document.getElementById('openStudioInspector').disabled,{VIEW}.open,document.getElementById('jvStudioInspector').hidden]"},
        ])
        reads = result["reads"]
        assert "failed" not in reads, reads
        assert reads["before"] == [True, False]
        assert reads["start"] == "applied"
        hidden = reads["hidden"]
        assert hidden["hidden"] is True and hidden["inert"] is True and hidden["display"] == "none" and hidden["w"] == 0
        assert hidden["dockDisabled"] is True and "pendant une présentation" in hidden["title"] and hidden["reason"] == "playback" and hidden["open"] is False
        assert (reads["p0"], reads["p1"], reads["p2"]) == (1, 2, 3), "navigation keys reach the player, not the inspector"
        stat = json.loads(reads["stat"])
        assert stat["commits"] == 0 and stat["previews"] == 0
        assert reads["after"] == [False, False, True], "after the run: available again, not forced open"
        assert not noise(result), noise(result)


# ------------------------------------------------------------------ deux tailles d'ecran

@pytest.mark.parametrize("viewport,name", [("1280x720", "desktop"), ("360x740", "phone")])
async def test_the_panel_fits_the_screen_and_every_group_is_reachable_at_both_sizes(tmp_path, viewport, name):
    async with InspectorRig(tmp_path) as rig:
        width, height = (int(x) for x in viewport.split("x"))
        result = await drive(rig.url, [
            *OPEN, {"wait": 500},
            {"shot": str(shots_dir(tmp_path) / f"panel-{viewport}-content.png")},
            tab("visual"), {"wait": 300}, {"shot": str(shots_dir(tmp_path) / f"panel-{viewport}-visual.png")},
            tab("layout"), {"wait": 300}, {"shot": str(shots_dir(tmp_path) / f"panel-{viewport}-layout.png")},
            {"value": "geometry", "expr": f"""(()=>{{const p=document.getElementById('jvStudioInspector').getBoundingClientRect();
              const main=document.querySelector('{PANEL} .jvi-main').getBoundingClientRect();
              const d=document.getElementById('openStudioInspector').getBoundingClientRect();
              return {{panel:[p.left,p.top,p.right,p.bottom],main:[main.height,document.querySelector('{PANEL} .jvi-main').scrollHeight],dock:[d.left,d.top,d.right,d.bottom],
                vw:innerWidth,vh:innerHeight,hscroll:document.documentElement.scrollWidth>innerWidth,
                overflowX:document.querySelector('{PANEL}').scrollWidth>document.querySelector('{PANEL}').clientWidth}}}})()"""},
            {"value": "rowwidths", "expr": f"[...document.querySelectorAll('{PANEL} [role=tabpanel]:not([hidden]) .jvi-row')].every(r=>r.scrollWidth<=r.clientWidth+1)"},
            {"value": "touch", "expr": f"[...document.querySelectorAll('{PANEL} button,{PANEL} input:not([type=range])')].filter(n=>n.offsetParent&&!n.disabled).map(n=>n.getBoundingClientRect()).filter(r=>r.height<24||r.width<24).length"},
        ], viewport=viewport)
        reads = result["reads"]
        assert "failed" not in reads, reads
        g = reads["geometry"]
        assert g["panel"][0] >= 0 and g["panel"][2] <= g["vw"] and g["panel"][1] >= 0 and g["panel"][3] <= g["vh"]
        assert g["hscroll"] is False and g["overflowX"] is False, "no horizontal scroll at any width"
        assert g["main"][0] > 120, f"the scrolling list keeps real height ({g['main'][0]}px) beside the pinned preview and tabs"
        assert g["panel"][2] <= g["dock"][0] + 1, "the panel never covers the dock buttons"
        if name == "phone":
            assert g["panel"][2] - g["panel"][0] >= 250
        assert reads["rowwidths"] is True and reads["touch"] == 0, "no row overflows; every target is at least 24 px"
        assert not noise(result), noise(result)


async def test_reduced_motion_stops_the_spinner_and_the_page_stays_quiet(tmp_path):
    async with InspectorRig(tmp_path) as rig:
        result = await drive(rig.url, [
            {"click": "#openStudioInspector"},
            {"value": "anim", "expr": f"getComputedStyle(document.querySelector('{PANEL} .jvi-spin')).animationName"},
            {"until": f"!!document.querySelector('{row('size')}')", "ms": 20000},
            {"value": "transition", "expr": f"getComputedStyle(document.querySelector('{row('glow')} [role=switch]')).transitionDuration"},
        ], reduced_motion=True)
        reads = result["reads"]
        assert "failed" not in reads, reads
        assert reads["anim"] == "none" and reads["transition"] in ("0s", "0s, 0s")
        assert not noise(result), noise(result)


# ------------------------------------------------------------------ rework (QA-1 B1): a native number field steps, the inspector coalesces

async def test_arrow_keys_on_a_number_field_leave_one_history_entry_and_one_revision(tmp_path):
    """Chrome fires `change` on EVERY arrow press of a type=number field: five presses used to be five undo entries (and a self-inflicted stale)."""

    async with InspectorRig(tmp_path) as rig:
        _, before = await rig.core.call("GET", f"/{rig.pid}/variants/{rig.vid}")
        field = f"{row('tilt')} input[type=number]"
        result = await drive(rig.url, [
            *OPEN, tab("layout"), {"focus": field}, {"value": "start", "expr": f"document.querySelector('{field}').value"},
            *[step for _ in range(5) for step in ({"key": "ArrowUp"}, {"wait": 55})],
            {"value": "during", "expr": f"JSON.stringify({{commits:{STATS}.commits,drafts:{VIEW}.pendingDrafts,shown:document.querySelector('{field}').value}})"},
            {"wait": 1500},
            {"value": "end", "expr": f"JSON.stringify({{stats:{STATS},history:{VIEW}.history,tilt:{VIEW}.controls.find(c=>c.control_id==='tilt'),revision:{VIEW}.revision}})"},
        ])
        reads = result["reads"]
        assert "failed" not in reads, reads
        during = json.loads(reads["during"])
        assert during["commits"] == 0 and during["drafts"] == ["tilt"] and during["shown"] == "5", during
        end = json.loads(reads["end"])
        assert end["stats"]["commits"] == 1 and end["stats"]["staleHandled"] == 0 and end["history"] == {"undo": 1, "redo": 0}, end
        assert end["tilt"] == {"control_id": "tilt", "current": 5, "is_set": True} and end["revision"] == before["revision"] + 1
        _, after = await rig.core.call("GET", f"/{rig.pid}/variants/{rig.vid}")
        assert after["revision"] == before["revision"] + 1, "one revision for five presses"
        assert not noise(result), noise(result)


async def test_holding_arrow_up_for_two_seconds_commits_at_most_three_times(tmp_path):
    async with InspectorRig(tmp_path) as rig:
        field = f"{row('speed')} input[type=number]"
        result = await drive(rig.url, [
            *OPEN, tab("motion"), {"focus": field},
            {"hold": {"key": "ArrowUp", "ms": 2000, "interval": 33}}, {"wait": 1500},
            {"value": "end", "expr": f"JSON.stringify({{stats:{STATS},history:{VIEW}.history,speed:{VIEW}.controls.find(c=>c.control_id==='speed').current}})"},
        ])
        reads = result["reads"]
        assert "failed" not in reads, reads
        end = json.loads(reads["end"])
        assert 1 <= end["stats"]["commits"] <= 3 and end["history"]["undo"] <= 3, end
        assert end["speed"] > 620 and end["stats"]["staleHandled"] == 0, "the auto-repeat really stepped the value, and never against its own write"
        assert not noise(result), noise(result)


async def test_the_mouse_wheel_on_a_focused_number_field_is_one_history_entry(tmp_path):
    async with InspectorRig(tmp_path) as rig:
        field = f"{row('delay')} input[type=number]"
        result = await drive(rig.url, [
            *OPEN, tab("motion"), {"focus": field},
            {"wheel": {"selector": field, "deltaY": -100, "count": 5, "interval": 50}}, {"wait": 1500},
            {"value": "end", "expr": f"JSON.stringify({{stats:{STATS},history:{VIEW}.history,delay:{VIEW}.controls.find(c=>c.control_id==='delay').current}})"},
        ])
        reads = result["reads"]
        assert "failed" not in reads, reads
        end = json.loads(reads["end"])
        assert end["stats"]["commits"] <= 1 and end["history"]["undo"] <= 1 and end["stats"]["staleHandled"] == 0, end
        assert not noise(result), noise(result)


# ------------------------------------------------------------------ merge with Slice 06 QA-2: a source reload is not a conflict

async def test_an_edit_made_right_after_a_source_reload_is_applied_not_reported_as_stale(tmp_path):
    """Real Core: inspector commit -> source reload (bumps the variant revision and re-pins the scene) -> inspector commit at once."""

    async with InspectorRig(tmp_path) as rig:
        source_url = f"/api/presentation-studio/presentations/{rig.pid}/variants/{rig.vid}/source-edits"
        reload_ = ("fetch(%s,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({basis:{variant_revision:%s.revision},"
                   "scene_id:%s,files:{style:'.dial{opacity:.99}'}})}).then(r=>r.json()).then(j=>j.status)" % (json.dumps(source_url), VIEW, json.dumps(S1)))
        result = await drive(rig.url, [
            *OPEN, tab("visual"), {"click": f"{row('glow')} [role=switch]"}, {"wait": 700},
            {"value": "reload", "expr": reload_},                       # the scene's source is republished: the revision moves, no control changes
            tab("layout"), {"click": f'{row("layout")} [role=radio][data-value="right"]'}, {"wait": 1500},
            {"value": "end", "expr": f"JSON.stringify({{stats:{STATS},msg:document.querySelector('{row('layout')} .jvi-msg').textContent,"
                                     f"layout:{VIEW}.controls.find(c=>c.control_id==='layout'),history:{VIEW}.history,"
                                     f"src:(document.querySelector('{PANEL} .jvi-top .jvi-default:last-child')||{{}}).textContent}})"},
        ])
        reads = result["reads"]
        assert "failed" not in reads, reads
        assert reads["reload"] in ("repinned", "reloaded"), reads["reload"]
        end = json.loads(reads["end"])
        assert end["layout"] == {"control_id": "layout", "current": "right", "is_set": True} and end["msg"] == "", end
        assert end["stats"]["commits"] == 2 and end["history"]["undo"] == 1, "the reload drops the old ring (documented); the new edit starts a new one"
        _, variant = await rig.core.call("GET", f"/{rig.pid}/variants/{rig.vid}")
        props = variant["scenes"][0]["props"]
        assert props["glow"] is True and props["layout"] == "right" and variant["scenes"][0]["source_revision"] >= 1
        assert not noise(result, (HTTP_REFUSAL, "[studio-inspector] stale_rebased", "[studio-inspector] edit_stale")), noise(result)

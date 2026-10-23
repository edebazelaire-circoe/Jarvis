"""Onglet Architecture mesuré dans un vrai navigateur (jarvis-architecture-agents-settings-editor, Slice 04).

Une page STATIQUE (fichier temporaire) charge le module et son adaptateur de fixture, avec les jetons de thème
lus dans `control_center.html` ; aucun Control Center n'est servi, le JARVIS vivant n'est jamais visé. Chrome sans
tête rejoue de vraies touches et de vrais gestes (harnais `_architecture_settings_browser.mjs`). Ce que le
fichier prouve :

- modules puis liaisons atteignables au Tab, Entrée ouvre l'inspecteur, Échap rend le focus ;
- Maj+F10 et le clic droit ouvrent le menu d'un cerveau, flèches et Échap y naviguent ;
- glisser un nœud n'appelle que `saveLayout`, jamais une écriture de topologie ;
- les états de liaison diffèrent par le trait (et pas seulement la couleur) ;
- `prefers-reduced-motion` coupe la pulsation des ports.

Le test se saute proprement si Chrome ou node est absent. `JARVIS_BROWSER_SHOTS=<dossier>` garde les captures.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "jarvis" / "runtime" / "control_center_architecture_settings.js"
PAGE = ROOT / "jarvis" / "runtime" / "control_center.html"
FIXTURE = ROOT / "tests" / "fixtures" / "architecture_snapshot_fixture_ui.json"
HARNESS = Path(__file__).parent / "_architecture_settings_browser.mjs"

CHROME_CANDIDATES = (
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
)


def _chrome() -> str:
    for candidate in CHROME_CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("chrome") or shutil.which("google-chrome")
    if found:
        return found
    pytest.skip("Chrome absent")


def all_states_snapshot() -> dict:
    """Le fixture + une liaison supprimable et un port de création : tous les états visibles à la fois."""
    snap = copy.deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8")))
    core = next(n for n in snap["nodes"] if n["id"] == "core")
    core["ports"].append({"id": "notes", "direction": "out", "channel": "event", "family": "brain_event"})
    tool = next(n for n in snap["nodes"] if n["id"] == "tool")
    tool["ports"].append({"id": "notes_in", "direction": "in", "channel": "event", "family": "brain_event"})
    snap["connections"].append({
        "id": "voice.delegate->tool.notes_in", "source": {"node": "voice", "port": "delegate"},
        "target": {"node": "tool", "port": "notes_in"}, "channel": "request", "purpose": "Liaison de démonstration",
        "enabled": True, "mutability": "creatable_removable", "locked_reason": "", "impact_when_disabled": "",
        "applies": "next_turn", "pending": None, "governed_by": None, "binding": "demo"})
    snap["creatable"] = [{"source": {"node": "core", "port": "notes"}, "target": {"node": "tool", "port": "notes_in"},
                          "channel": "event", "purpose": "Notes de Core vers le Tool Brain"}]
    for c in snap["connections"]:
        if c["id"] == "core.events->tool.events":
            c["pending"] = {"enabled": True, "applies": "core_restart"}
    return snap


def theme_tokens() -> str:
    html = PAGE.read_text(encoding="utf-8")
    return "\n".join(re.findall(r"^:root\{[^}]*\}$", html, flags=re.M))


def build_page(tmp_path: Path, snapshot: dict, layout: dict | None = None) -> Path:
    page = tmp_path / "architecture_demo.html"
    page.write_text(f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Architecture (démo)</title>
<style>{theme_tokens()}
html,body{{margin:0;background:radial-gradient(1200px 600px at 30% -10%,rgba(80,120,255,.14),transparent 60%),var(--bg);color:var(--text);
  font:14px/1.5 "Segoe UI Variable Text","Segoe UI",system-ui,sans-serif}}
main{{padding:24px 16px;max-width:1360px;margin:0 auto}}</style></head>
<body><main><div id="host"></div></main>
<script src="{MODULE.as_uri()}"></script>
<script>
window.__events=[];window.__configured=[];
const A=window.JarvisArchitectureSettings;
window.__adapter=A.createFixtureAdapter({json.dumps(snapshot)},{{layout:{json.dumps(layout or {"revision": None, "positions": {}})}}});
const host=document.getElementById('host');
host.addEventListener('architecture:configure-brain',e=>window.__events.push(e.detail));
window.__view=A.mount(host,{{adapter:window.__adapter,onConfigureBrain:(id,d)=>window.__configured.push([id,d.source])}});
</script></body></html>""", encoding="utf-8")
    return page


def run_plan(tmp_path: Path, page: Path, steps: list, width=1360, height=980, reduced=False) -> list:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    chrome = _chrome()
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"width": width, "height": height, "reducedMotion": reduced, "steps": steps}), encoding="utf-8")
    done = subprocess.run([node, str(HARNESS), str(page), chrome, str(plan)], capture_output=True, text=True,
                          encoding="utf-8", timeout=120, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def shots_dir(tmp_path: Path) -> Path:
    target = Path(os.environ.get("JARVIS_BROWSER_SHOTS") or tmp_path)
    target.mkdir(parents=True, exist_ok=True)
    return target


FOCUSED = "(()=>{const a=document.activeElement;return a&&(a.getAttribute('data-arch-node')||a.getAttribute('data-arch-conn')||a.getAttribute('data-arch-menu')||a.id||a.tagName)})()"
WRITES = "window.__adapter.calls.filter(c=>!['load','loadLayout'].includes(c[0])).map(c=>c[0])"


def test_tab_reaches_nodes_then_links_enter_inspects_and_escape_returns(tmp_path):
    snap = json.loads(FIXTURE.read_text(encoding="utf-8"))
    page = build_page(tmp_path, snap)
    n_nodes, n_links = len(snap["nodes"]), len(snap["connections"])
    # Point de départ : le bouton « Changer dans Avancé » du bandeau (avant « Relire »).
    steps = [{"eval": "document.querySelector('[data-settings-open]').focus();document.querySelector('[data-settings-open]').getAttribute('data-settings-open')"},
             {"key": "Tab"}]  # -> Relire
    order = []
    for _ in range(n_nodes * 3 + n_links):
        steps += [{"key": "Tab"}, {"eval": FOCUSED}]
    out = run_plan(tmp_path, page, steps)
    assert out[0] == "architecture_compat"
    order = [v for v in out[3::2]]
    nodes = [n["id"] for n in snap["nodes"]]
    links = [c["id"] for c in snap["connections"]]
    visited_nodes = [v for v in order if v in nodes]
    visited_links = [v for v in order if v in links]
    assert visited_nodes[:n_nodes] == nodes
    assert set(visited_links) == set(links)
    # Tous les modules viennent avant la première liaison.
    assert order.index(links[0]) > max(order.index(n) for n in nodes) or order.index(visited_links[0]) > order.index(nodes[-1])

    sel_link = '.arch-label[data-arch-conn="voice.delegate->core.request"]'
    out = run_plan(tmp_path, page, [
        {"eval": f"document.querySelector('{sel_link}').focus();1"},
        {"key": "Enter"},
        {"eval": "[document.activeElement.tagName, document.querySelector('[data-arch-inspector]').textContent]"},
        {"key": "Escape"},
        {"eval": FOCUSED},
        {"eval": "document.querySelector('[data-arch-node=\"core\"]').focus();1"},
        {"key": "Enter"},
        {"eval": "[document.activeElement.tagName, document.querySelector('[data-arch-inspector] h3').textContent]"},
    ])
    tag, text = out[2]
    assert tag == "H3" and "Voice Brain" in text and "Core Brain" in text and "La voix répond seule" in text
    assert "Prise d’effet" in text and "au prochain tour de parole" in text
    assert out[4] == "voice.delegate->core.request"
    assert out[7] == ["H3", "Core Brain"]


def test_shift_f10_and_right_click_open_the_brain_menu_and_configure_emits_the_event(tmp_path):
    page = build_page(tmp_path, json.loads(FIXTURE.read_text(encoding="utf-8")))
    out = run_plan(tmp_path, page, [
        {"eval": "document.querySelector('[data-arch-node=\"voice\"]').focus();1"},
        {"key": "F10", "shift": True},
        {"eval": "[document.activeElement.getAttribute('data-arch-menu'), [...document.querySelectorAll('.arch-menu [role=menuitem]')].map(e=>e.textContent.trim())]"},
        {"key": "ArrowDown"},
        {"eval": FOCUSED},
        {"key": "Escape"},
        {"eval": "[document.querySelector('.arch-menu')===null, document.activeElement.getAttribute('data-arch-node')]"},
        {"click": '[data-arch-node="core"] .arch-node-name', "button": "right"},
        {"eval": "document.querySelector('.arch-menu').getAttribute('data-arch-menu-for')"},
        {"key": "Enter"},
        {"eval": "[window.__configured, window.__events, document.querySelector('.arch-menu')===null]"},
        {"click": '[data-arch-menu-btn="tool"]'},
        {"eval": "document.querySelector('.arch-menu').getAttribute('data-arch-menu-for')"},
        {"click": '[data-arch-node="mic"] .arch-node-name', "button": "right"},
        {"eval": "document.querySelector('.arch-menu')===null"},
    ])
    first, items = out[2]
    assert first == "configure" and items[0] == "Configurer…" and "Inspecter" in items
    # Aucun cerveau du fixture n'a d'activation modifiable : pas d'entrée Activer/Désactiver.
    assert not any(i in ("Activer", "Désactiver") for i in items)
    assert out[4] == "inspect"
    assert out[6] == [True, "voice"]
    assert out[8] == "core"
    configured, events, closed = out[10]
    assert configured == [["core", "menu"]] and events == [{"nodeId": "core", "field": None, "source": "menu"}] and closed
    assert out[12] == "tool"
    # Un endpoint n'est pas un cerveau : le clic droit n'ouvre aucun menu.
    assert out[14] is True


def test_dragging_a_node_saves_layout_only_and_moves_its_links(tmp_path):
    page = build_page(tmp_path, json.loads(FIXTURE.read_text(encoding="utf-8")))
    shots = shots_dir(tmp_path)
    edge = "document.querySelector('[data-arch-edge=\"voice.delegate->core.request\"] .arch-edge').getAttribute('d')"
    out = run_plan(tmp_path, page, [
        {"eval": edge},
        {"shot": str(shots / "architecture-default.png")},
        {"eval": "[document.querySelector('[data-arch-node=\"core\"]').style.left, document.querySelector('[data-arch-node=\"core\"]').style.top]"},
        {"drag": '[data-arch-node="core"] .arch-node-sub', "dx": 120, "dy": 60},
        {"wait": 300},
        {"eval": edge},
        {"eval": "[document.querySelector('[data-arch-node=\"core\"]').style.left, document.querySelector('[data-arch-node=\"core\"]').style.top]"},
        {"eval": WRITES},
        {"eval": "JSON.stringify(window.__adapter.calls.find(c=>c[0]==='saveLayout'))"},
        {"eval": "[document.querySelector('[data-arch-layout-note]').textContent, window.__view.state.selected]"},
        {"eval": "document.querySelector('[data-arch-node=\"core\"]').focus();1"},
        {"key": "ArrowRight", "shift": True},
        {"wait": 900},
        {"eval": WRITES},
    ])
    out.pop(1)
    assert out[0] != out[4], "la liaison suit le nœud"
    (x0, y0), (x1, y1) = [tuple(int(v[:-2]) for v in pair) for pair in (out[1], out[5])]
    assert (x1 - x0, y1 - y0) == (120, 60)
    assert out[6] == ["saveLayout"], "glisser n'écrit que la disposition"
    saved = json.loads(out[7])
    assert saved[1]["base_revision"] is None and saved[1]["positions"]["core"] == {"x": x1, "y": y1}
    note, selected = out[8]
    assert "Disposition enregistrée" in note and selected is None, "le glisser ne sélectionne pas"
    assert out[12] == ["saveLayout", "saveLayout"], "Maj+flèche déplace et enregistre la disposition seule"


def test_states_differ_by_stroke_and_reduced_motion_stops_the_pulse(tmp_path):
    page = build_page(tmp_path, all_states_snapshot())
    style = """(()=>{const r={};for(const g of document.querySelectorAll('[data-arch-edge]')){const p=g.querySelector('.arch-edge');const s=getComputedStyle(p);
      r[g.getAttribute('data-arch-edge')]={dash:s.strokeDasharray,width:s.strokeWidth,opacity:s.opacity,casing:!!g.querySelector('.arch-casing'),
      glyph:document.querySelector('.arch-label[data-arch-conn="'+g.getAttribute('data-arch-edge')+'"]').innerHTML.includes('<svg')}}return r})()"""
    shots = shots_dir(tmp_path)
    out = run_plan(tmp_path, page, [
        {"eval": style},
        {"shot": str(shots / "architecture-all-states.png")},
        {"click": '[data-arch-port-source="core/notes"]'},
        {"eval": "[document.querySelectorAll('[data-arch-port-target]').length, getComputedStyle(document.querySelector('[data-arch-port-target]')).animationName]"},
        {"click": '.arch-label[data-arch-conn="core.events->tool.events"]'},
        {"shot": str(shots / "architecture-inspector-pending.png")},
    ], reduced=True)
    s = out[0]
    locked, on, off = s["mic.audio_out->voice.audio_in"], s["voice.delegate->core.request"], s["core.events->tool.events"]
    removable, governed = s["voice.delegate->tool.notes_in"], s["core.agents->subagents.spawn"]
    assert locked["casing"] and locked["dash"] == "none" and float(locked["width"][:-2]) > float(on["width"][:-2])
    assert on["dash"] == "none" and not on["casing"]
    assert off["dash"] != "none" and float(off["opacity"]) < 1
    assert removable["dash"] not in ("none", off["dash"])
    assert governed["dash"] not in ("none", off["dash"], removable["dash"])
    assert all(v["glyph"] for v in s.values())
    count, animation = out[3]
    assert count == 1 and animation == "none"


def test_narrow_viewport_stacks_the_inspector_without_page_scroll(tmp_path):
    page = build_page(tmp_path, json.loads(FIXTURE.read_text(encoding="utf-8")))
    shots = shots_dir(tmp_path)
    out = run_plan(tmp_path, page, [
        {"eval": "[document.documentElement.scrollWidth<=window.innerWidth, getComputedStyle(document.querySelector('.arch-main')).gridTemplateColumns.split(' ').length]"},
        {"shot": str(shots / "architecture-narrow.png")},
    ], width=420, height=900)
    assert out[0] == [True, 1]


GEOMETRY = """(()=>{
  const box=e=>{const r=e.getBoundingClientRect();return {l:r.left,t:r.top,r:r.right,b:r.bottom,id:e.getAttribute('data-arch-conn')||e.getAttribute('data-arch-node')}};
  const hit=(a,b,g)=>a.l<b.r-g&&b.l<a.r-g&&a.t<b.b-g&&b.t<a.b-g;
  const inside=(x,y,r,g)=>x>r.l-g&&x<r.r+g&&y>r.t-g&&y<r.b+g;
  const labels=[...document.querySelectorAll('.arch-label')].map(box),nodes=[...document.querySelectorAll('.arch-node')].map(box);
  const bad=[];
  labels.forEach((a,i)=>labels.slice(i+1).forEach(b=>{if(hit(a,b,0))bad.push('libellé/libellé '+a.id+' | '+b.id)}));
  for(const a of labels)for(const n of nodes)if(hit(a,n,0))bad.push('libellé/nœud '+a.id+' | '+n.id);
  for(const p of document.querySelectorAll('.arch-edges .arch-edge')){
    const id=p.parentNode.getAttribute('data-arch-edge'),m=p.getScreenCTM(),q=p.getPointAtLength(p.getTotalLength());
    const x=m.a*q.x+m.c*q.y+m.e,y=m.b*q.x+m.d*q.y+m.f;
    for(const a of labels)if(inside(x,y,a,3))bad.push('pointe masquée par un libellé '+id+' | '+a.id);
    for(const n of nodes)if(inside(x,y,n,1))bad.push('pointe sous un nœud '+id+' | '+n.id);
  }
  const world=document.querySelector('[data-arch-world]').getBoundingClientRect();
  for(const a of labels)if(a.l<world.left||a.t<world.top)bad.push('libellé hors du canevas '+a.id);
  for(const p of document.querySelectorAll('.arch-edges .arch-edge')){const r=p.getBoundingClientRect();
    if(r.left<world.left-1||r.top<world.top-1)bad.push('liaison hors du canevas '+p.parentNode.getAttribute('data-arch-edge'))}
  const cols=new Set(nodes.map(n=>Math.round(n.l))).size;
  return {bad,cols,labels:labels.length,scroll:document.documentElement.scrollWidth<=window.innerWidth};
})()"""


@pytest.mark.parametrize("mode", ["duplex", "simple"])
@pytest.mark.parametrize("width,cols", [(1360, 3), (1100, 2), (420, 1)])
def test_no_label_overlaps_a_label_or_a_node_and_no_arrow_tip_is_hidden(tmp_path, mode, width, cols):
    snap = json.loads((ROOT / "tests" / "fixtures" / f"architecture_snapshot_{mode}.json").read_text(encoding="utf-8"))
    page = build_page(tmp_path, snap)
    shot = shots_dir(tmp_path) / f"architecture-{mode}-{width}.png"
    out = run_plan(tmp_path, page, [{"eval": GEOMETRY}, {"shot": str(shot)}], width=width, height=1500 if width < 800 else 1000)
    g = out[0]
    assert g["labels"] == len(snap["connections"])
    assert g["cols"] == cols
    assert g["bad"] == []
    assert g["scroll"], "aucun défilement horizontal de la page"


def test_the_menu_opened_by_its_button_gives_focus_back_to_that_button(tmp_path):
    page = build_page(tmp_path, json.loads(FIXTURE.read_text(encoding="utf-8")))
    out = run_plan(tmp_path, page, [
        {"eval": "document.querySelector('[data-arch-menu-btn=\"core\"]').focus();1"},
        {"key": "Enter"},
        {"eval": "document.activeElement.getAttribute('data-arch-menu')"},
        {"key": "Escape"},
        {"eval": "document.activeElement.getAttribute('data-arch-menu-btn')"},
    ])
    assert out[2] == "configure" and out[4] == "core"

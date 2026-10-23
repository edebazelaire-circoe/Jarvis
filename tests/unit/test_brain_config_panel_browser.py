"""Fenêtre de configuration d'un cerveau mesurée dans un vrai navigateur (jarvis-architecture-agents-settings-editor,
Slice 05).

Une page STATIQUE (fichier temporaire) monte le canevas de la Slice 04 et la fenêtre de la Slice 05, chacun avec son
adaptateur de fixture, câblés comme la Slice 07 le fera (`onConfigureBrain` -> `JarvisBrainConfigPanel.open`).
Aucun Control Center n'est servi, le JARVIS vivant n'est jamais visé. Chrome sans tête rejoue de vraies touches et
de vrais gestes (harnais `_architecture_settings_browser.mjs`). Ce que le fichier prouve :

- « Configurer… » ouvre la fenêtre, le focus y entre, Tab y tourne, Échap ferme et rend le focus au nœud ou au
  bouton « … » qui l'a ouverte ; le graphe reste visible à côté ;
- la tendance de délégation se règle au clavier (radiogroup), Échap avec un brouillon demande confirmation ;
- « Voir sur le graphe » sélectionne la liaison sur le canevas sans fermer la fenêtre ni rien écrire ;
- l'en-tête se glisse ; sous 720 px la fenêtre devient un panneau en bas, sans défilement horizontal ;
- `prefers-reduced-motion` coupe les transitions.

Le test se saute proprement si Chrome ou node est absent. `JARVIS_BROWSER_SHOTS=<dossier>` garde les captures.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.unit.test_architecture_settings_browser import FIXTURE as CANVAS_FIXTURE
from tests.unit.test_architecture_settings_browser import run_plan, shots_dir, theme_tokens
from tests.unit.test_brain_config_panel_js import fixture, tool_brain

ROOT = Path(__file__).resolve().parents[2]
CANVAS = ROOT / "jarvis" / "runtime" / "control_center_architecture_settings.js"
PANEL = ROOT / "jarvis" / "runtime" / "control_center_brain_config_panel.js"


def build_page(tmp_path: Path) -> Path:
    snap = json.loads(CANVAS_FIXTURE.read_text(encoding="utf-8"))
    # Les cerveaux du fixture du canevas s'appellent voice, core, tool_brain (ids du runtime) : la fenêtre reçoit l'id du nœud.
    configs = {"core": fixture("core"), "voice": fixture("voice"), "tool_brain": tool_brain()}
    page = tmp_path / "brain_config_demo.html"
    page.write_text(f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Fenêtre du cerveau (démo)</title>
<style>{theme_tokens()}
html,body{{margin:0;background:radial-gradient(1200px 600px at 30% -10%,rgba(80,120,255,.14),transparent 60%),var(--bg);color:var(--text);
  font:14px/1.5 "Segoe UI Variable Text","Segoe UI",system-ui,sans-serif}}
main{{padding:24px 16px;max-width:1360px;margin:0 auto}}</style></head>
<body><main><div id="canvas"></div><div id="panels"></div></main>
<script src="{CANVAS.as_uri()}"></script>
<script src="{PANEL.as_uri()}"></script>
<script>
const A=window.JarvisArchitectureSettings,P=window.JarvisBrainConfigPanel;
window.__focused=[];window.__saved=[];
window.__bc=P.createFixtureAdapter({json.dumps(configs)});
const canvas=document.getElementById('canvas'),panels=document.getElementById('panels');
window.__view=A.mount(canvas,{{adapter:A.createFixtureAdapter({json.dumps(snap)}),onConfigureBrain:(id,d)=>{{
  window.__panel=P.open(panels,{{adapter:window.__bc,brainId:id,field:d.field,
    returnFocus:P.canvasReturnFocus(canvas,id,d),
    anchor:()=>canvas.querySelector('[data-arch-node="'+id+'"]'),
    nodeLabel:nid=>{{const n=(window.__view.state.snapshot.nodes||[]).find(x=>x.id===nid);return n?n.label:nid}},
    onFocusConnection:cid=>{{window.__focused.push(cid);window.__view.select('connection',cid)}},
    onSaved:d=>window.__saved.push([d.field,d.applies])}});
}}}});
</script></body></html>""", encoding="utf-8")
    return page


IN_PANEL = "(()=>{const a=document.activeElement,w=document.querySelector('.bcp-win');return !!(w&&a&&w.contains(a))})()"
ACTIVE = "(()=>{const a=document.activeElement;return a&&(a.getAttribute('data-bcp-key')||a.getAttribute('data-arch-node')||a.getAttribute('data-arch-menu-btn')||a.tagName)})()"
OPEN_CORE_BY_MENU = [{"eval": "document.querySelector('[data-arch-node=\"core\"]').focus();1"}, {"key": "F10", "shift": True},
                     {"key": "Enter"}, {"wait": 300}]
GONE = "document.querySelector('.bcp-win')===null"


def test_configure_opens_the_window_tab_stays_inside_and_escape_returns_to_the_node(tmp_path):
    page = build_page(tmp_path)
    shots = shots_dir(tmp_path)
    steps = OPEN_CORE_BY_MENU + [
        {"eval": f"[{IN_PANEL},{ACTIVE},document.querySelector('.bcp-win').getAttribute('role')]"},
        {"eval": """(()=>{const w=document.querySelector('.bcp-win').getBoundingClientRect(),c=document.querySelector('.arch-canvas').getBoundingClientRect();
          const ox=Math.max(0,Math.min(w.right,c.right)-Math.max(w.left,c.left)),oy=Math.max(0,Math.min(w.bottom,c.bottom)-Math.max(w.top,c.top));
          const n=document.querySelector('[data-arch-node="core"]').getBoundingClientRect();
          const nx=Math.max(0,Math.min(w.right,n.right)-Math.max(w.left,n.left)),ny=Math.max(0,Math.min(w.bottom,n.bottom)-Math.max(w.top,n.top));
          return {covered:(ox*oy)/(c.width*c.height),node:nx*ny,inViewport:w.left>=0&&w.top>=0&&w.right<=innerWidth&&w.bottom<=innerHeight}})()"""},
        {"shot": str(shots / "brain-config-core.png")},
    ]
    for _ in range(45):
        steps += [{"key": "Tab"}, {"eval": IN_PANEL}]
    steps += [{"key": "Tab", "shift": True}, {"eval": IN_PANEL}, {"key": "Escape"}, {"eval": f"[{GONE},{ACTIVE}]"}]
    out = run_plan(tmp_path, page, steps)
    assert out[4] == [True, "title", "dialog"]
    geo = out[5]
    # Slice 07 : la fenêtre ne couvre plus le nœud configuré ; elle passe à gauche de l'écran quand le nœud tombe sous la
    # colonne de droite, au prix d'un peu plus de canevas couvert (le graphe reste lisible à plus de moitié).
    assert geo["inViewport"] and geo["covered"] < 0.5 and geo["node"] == 0, f"le graphe reste visible : {geo}"
    trapped = out[8:8 + 90:2]
    assert all(trapped), "Tab ne sort jamais de la fenêtre"
    assert out[-3] is True
    assert out[-1] == [True, "core"], "Échap ferme et rend le focus au nœud"


def test_the_menu_button_gets_the_focus_back(tmp_path):
    page = build_page(tmp_path)
    out = run_plan(tmp_path, page, [
        {"eval": "document.querySelector('[data-arch-menu-btn=\"core\"]').focus();1"},
        {"key": "Enter"}, {"key": "Enter"}, {"wait": 300},
        {"eval": IN_PANEL}, {"key": "Escape"}, {"eval": f"[{GONE},{ACTIVE}]"},
    ])
    assert out[4] is True and out[6] == [True, "core"]
    out2 = run_plan(tmp_path, page, [
        {"eval": "document.querySelector('[data-arch-menu-btn=\"core\"]').focus();1"},
        {"key": "Enter"}, {"key": "Enter"}, {"wait": 300}, {"key": "Escape"},
        {"eval": "document.activeElement.hasAttribute('data-arch-menu-btn')"},
    ])
    assert out2[-1] is True, "le focus revient au bouton « … », pas au nœud"


def test_delegation_by_keyboard_then_escape_asks_then_apply_saves(tmp_path):
    page = build_page(tmp_path)
    shots = shots_dir(tmp_path)
    checked = "(()=>{const r=document.querySelector('[data-bcp-radio=\"delegation\"][aria-checked=\"true\"]');return [r.getAttribute('data-bcp-value'),document.activeElement===r,document.querySelector('[data-bcp-level]').textContent]})()"
    out = run_plan(tmp_path, page, OPEN_CORE_BY_MENU + [
        {"eval": "document.querySelector('[data-bcp-radio=\"delegation\"][aria-checked=\"true\"]').focus();document.querySelectorAll('[data-bcp-radio=\"delegation\"]').length"},
        {"key": "ArrowRight"},
        {"eval": checked},
        {"shot": str(shots / "brain-config-delegation-draft.png")},
        {"key": "Escape"},
        {"eval": f"[document.querySelector('[data-bcp-confirm]')&&document.querySelector('[data-bcp-confirm]').getAttribute('data-bcp-confirm'),{ACTIVE}]"},
        {"shot": str(shots / "brain-config-close-guard.png")},
        {"key": "Escape"},
        {"eval": f"[document.querySelector('[data-bcp-confirm]')===null,{IN_PANEL},Object.keys(window.__panel.state.draft)]"},
        {"click": "[data-bcp-act=\"apply\"]"},
        {"wait": 300},
        {"eval": "[window.__bc.calls.filter(c=>c[0]==='patch').map(c=>c[2].delegation),window.__saved,document.querySelector('[data-bcp-saved=\"delegation\"]').textContent]"},
        {"shot": str(shots / "brain-config-saved.png")},
        {"key": "Escape"},
        {"eval": GONE},
    ])
    assert out[4] == 5
    value, focused, level = out[6]
    assert value == "proactive" and focused and "Proactive" in level and "dépasse une réponse immédiate" in level
    assert out[9] == ["close", "confirm-keep"]
    assert out[12] == [True, True, ["delegation"]]
    patched, saved, chip = out[15]
    assert patched == ["proactive"] and saved == [["delegation", "core_restart"]]
    assert "Enregistré" in chip and "au prochain démarrage de Core" in chip
    assert out[-1] is True, "sans brouillon, Échap ferme sans demander"


def test_a_governed_link_opens_on_delegation_and_see_on_graph_selects_without_writing(tmp_path):
    page = build_page(tmp_path)
    shots = shots_dir(tmp_path)
    out = run_plan(tmp_path, page, [
        {"click": '.arch-label[data-arch-conn="core.agents->subagents.spawn"]'},
        {"click": '[data-arch-act="governed"]'},
        {"wait": 300},
        {"eval": "[document.activeElement.getAttribute('data-bcp-radio'),document.activeElement.getAttribute('aria-checked')]"},
        {"click": '[data-bcp-conn="voice.delegate->core.request"]'},
        {"eval": f"[window.__focused,window.__view.state.selected,document.querySelector('.bcp-win')!==null,window.__bc.calls.filter(c=>c[0]==='patch').length]"},
        {"shot": str(shots / "brain-config-see-on-graph.png")},
    ])
    assert out[3] == ["delegation", "true"], "ouverte sur le champ gouverneur"
    focused, selected, still_open, writes = out[5]
    assert focused == ["voice.delegate->core.request"] and selected == {"type": "connection", "id": "voice.delegate->core.request"}
    assert still_open and writes == 0


def test_the_header_drags_the_window_and_replacing_with_a_draft_asks(tmp_path):
    page = build_page(tmp_path)
    shots = shots_dir(tmp_path)
    left = "[parseInt(document.querySelector('.bcp-win').style.left),parseInt(document.querySelector('.bcp-win').style.top)]"
    out = run_plan(tmp_path, page, OPEN_CORE_BY_MENU + [
        {"eval": left},
        {"drag": ".bcp-head .bcp-sub", "dx": 240, "dy": 60},
        {"eval": left},
        # Rendue à sa place, à gauche : le nœud Voice reste libre pour le clic droit qui suit.
        {"drag": ".bcp-head .bcp-sub", "dx": -240, "dy": 0},
        {"eval": "window.__panel.setDraft('instructions','Brouillon en cours');1"},
        {"click": '[data-arch-node="voice"] .arch-node-name', "button": "right"},
        {"key": "Enter"},
        {"wait": 200},
        {"eval": f"[document.querySelector('[data-bcp-confirm]').getAttribute('data-bcp-confirm'),window.__panel.brainId,document.querySelectorAll('.bcp-win').length,{ACTIVE}]"},
        {"shot": str(shots / "brain-config-replace-guard.png")},
        {"click": '[data-bcp-act="confirm-discard"]'},
        {"wait": 300},
        {"eval": "[window.__panel.brainId,document.querySelectorAll('.bcp-win').length,document.querySelector('[data-bcp-field=\"delegation\"]').textContent]"},
        {"shot": str(shots / "brain-config-voice.png")},
    ])
    (x0, y0), (x1, y1) = out[4], out[6]
    # La fenêtre est presque aussi haute que la fenêtre du navigateur : verticalement, elle reste bornée à l'écran.
    assert x1 - x0 == 240 and 8 <= y1 <= y0 + 60  # posée à gauche (Slice 07), elle se glisse vers la droite
    assert out[12] == ["replace", "core", 1, "confirm-keep"]
    brain, count, delegation = out[16]
    assert brain == "voice" and count == 1 and "Sans objet" in delegation and "onglet Sous-agents" in delegation


def test_narrow_viewport_turns_it_into_a_bottom_panel_without_page_scroll(tmp_path):
    page = build_page(tmp_path)
    shots = shots_dir(tmp_path)
    out = run_plan(tmp_path, page, [
        {"eval": "window.__view.configure('core',{source:'menu'});1"},
        {"wait": 400},
        {"eval": "(()=>{const r=document.querySelector('.bcp-win').getBoundingClientRect();return {l:r.left,r:Math.round(innerWidth-r.right),b:Math.round(innerHeight-r.bottom),scrim:getComputedStyle(document.querySelector('.bcp-scrim')).display,scroll:document.documentElement.scrollWidth<=innerWidth,grip:getComputedStyle(document.querySelector('.bcp-grip')).display}})()"},
        {"shot": str(shots / "brain-config-narrow.png")},
    ], width=420, height=900)
    g = out[2]
    assert g == {"l": 8, "r": 8, "b": 8, "scrim": "block", "scroll": True, "grip": "none"}


def test_reduced_motion_cuts_the_transitions(tmp_path):
    page = build_page(tmp_path)
    out = run_plan(tmp_path, page, [
        {"eval": "window.__view.configure('core',{source:'menu'});1"}, {"wait": 300},
        {"eval": "[getComputedStyle(document.querySelector('.bcp-seg')).transitionDuration,getComputedStyle(document.querySelector('.bcp-btn')).transitionDuration]"},
    ], reduced=True)
    assert out[2] == ["0s", "0s"]


def test_an_instructions_conflict_keeps_the_typed_draft_and_shows_the_server_text(tmp_path):
    page = build_page(tmp_path)
    shots = shots_dir(tmp_path)
    out = run_plan(tmp_path, page, OPEN_CORE_BY_MENU + [
        {"eval": "const t=document.querySelector('[data-bcp-input=\"instructions\"]');t.scrollIntoView();t.focus();t.value='Mon brouillon tapé';t.dispatchEvent(new Event('input',{bubbles:true}));"
                 "window.__bc.tamper('core',c=>{c.fields.instructions.value='Texte posé ailleurs.';c.fields.instructions.effective_revision='e-other'});1"},
        {"eval": "[document.activeElement.getAttribute('data-bcp-key'),document.querySelector('[data-bcp-field=\"instructions\"] .bcp-dirty')!==null,document.querySelector('[data-bcp-act=\"apply\"]').disabled]"},
        {"click": '[data-bcp-act="apply"]'},
        {"wait": 300},
        {"eval": "[document.querySelector('[data-bcp-error]').textContent,document.querySelector('[data-bcp-input=\"instructions\"]').value,document.querySelector('.bcp-pre').textContent]"},
        {"eval": "document.querySelector('[data-bcp-error]').scrollIntoView();1"},
        {"shot": str(shots / "brain-config-conflict.png")},
    ])
    assert out[5] == ["instructions", True, False], "la saisie garde le focus et marque le champ"
    error, draft, server = out[8]
    assert "Modifié ailleurs : Instructions" in error and "brain_config_revision_stale" in error and "HTTP 409" in error
    assert draft == "Mon brouillon tapé"
    assert server == "Texte posé ailleurs."

"""Onglet Sous-agents mesuré dans un vrai navigateur (jarvis-architecture-agents-settings-editor, Slice 06).

Une page STATIQUE (fichier temporaire) charge le module, son module de routage et l'adaptateur de fixture, avec
la feuille de style de `control_center.html` ; aucun Control Center n'est servi, le JARVIS vivant n'est jamais
visé. Chrome sans tête rejoue de vraies touches (harnais `_subagent_settings_browser.mjs`). Ce que le fichier
prouve :

- un candidat se réordonne au clavier seul (Entrée sur Monter, Alt + flèches), le focus suit le candidat ;
- le repli se bascule à l'Espace, Tab atteint « Enregistrer pour ce rôle », l'écriture ne vise que ce rôle ;
- la vue d'ensemble s'ouvre au clavier et donne le focus à son titre ;
- un candidat indisponible diffère par le trait et le texte, pas seulement la couleur ;
- à 390 px, aucun défilement horizontal ; `prefers-reduced-motion` coupe les transitions.

Le test se saute proprement si Chrome ou node est absent. `JARVIS_BROWSER_SHOTS=<dossier>` garde les captures.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from jarvis.runtime.control_center import ControlCenter

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
PAGE = RUNTIME / "control_center.html"
FIXTURE = ROOT / "tests" / "fixtures" / "subagent_role_routing.json"
HARNESS = Path(__file__).parent / "_subagent_settings_browser.mjs"

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


def page_styles() -> str:
    html = PAGE.read_text(encoding="utf-8")
    return html[html.index("<style>") + len("<style>"):html.index("</style>")]


def build_page(tmp_path: Path, selected: str = "qa") -> Path:
    roles = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)._subagent_roles_payload({})
    routing = json.loads(FIXTURE.read_text(encoding="utf-8"))
    page = tmp_path / "subagents_demo.html"
    scripts = "".join(f'<script src="{(RUNTIME / name).as_uri()}"></script>' for name in
                      ("control_center_role_identity.js", "control_center_subagent_routing.js", "control_center_subagents_settings.js"))
    page.write_text(f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Sous-agents (démo)</title>
<style>{page_styles()}
html,body{{height:auto;overflow:auto;background:radial-gradient(1200px 600px at 30% -10%,rgba(80,120,255,.14),transparent 60%),var(--bg);
  font:14px/1.5 "Segoe UI Variable Text","Segoe UI",system-ui,sans-serif}}
main{{box-sizing:border-box;height:100vh;padding:24px 16px;max-width:1360px;margin:0 auto}}
#host{{height:100%}}</style></head>
<body><main class="set-shell"><div id="host"></div></main>
{scripts}
<script>
const ROLES={json.dumps(roles)};
window.__opened=[];
window.__adapter=JarvisSubagentRouting.createFixtureAdapter({json.dumps(routing)});
const fetch=async p=>p==='/api/subagent-roles'?ROLES:{{tasks:[]}};
window.__view=JarvisSubagentSettings.create(document.getElementById('host'),{{fetch,routing:window.__adapter,openTab:t=>window.__opened.push(t)}});
window.__ready=window.__view.load().then(()=>window.__view.routeReady()).then(()=>window.__view.select({json.dumps(selected)}));
</script></body></html>""", encoding="utf-8")
    return page


def run_plan(tmp_path: Path, page: Path, steps: list, width=1360, height=900, reduced=False) -> list:
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


FOCUSED = ("(()=>{const a=document.activeElement;if(!a)return null;"
           "return [a.getAttribute('data-sar-cand-op')||a.getAttribute('data-sar-route-save')&&'save'||a.id||a.tagName,"
           "a.getAttribute('data-sar-cand-i')]})()")
ORDER = ("(window.__view.state.routeDrafts.qa||window.__view.state.route.snap.roles.find(r=>r.role_id==='qa'))"
         ".candidates.map(c=>c.model)")
WRITES = "window.__adapter.calls.filter(c=>c[0]!=='load')"


def test_candidates_reorder_and_save_with_the_keyboard_only(tmp_path):
    page = build_page(tmp_path)
    shots = shots_dir(tmp_path)
    steps = [
        {"eval": "window.__ready.then(()=>document.querySelectorAll('[data-sar-role]').length)"},
        {"shot": str(shots / "s06-desktop-qa.png")},
        # Entrée sur « Monter » du 2e candidat : il passe premier ; « Monter » y est désactivé, le focus prend « Descendre ».
        {"eval": "document.querySelector('[data-sar-cand-op=\"up\"][data-sar-cand-i=\"1\"]').focus();1"},
        {"key": "Enter"}, {"eval": ORDER}, {"eval": FOCUSED},
        # Alt + flèche bas sur la commande focalisée : il redescend, le focus le suit.
        {"key": "ArrowDown", "alt": True}, {"eval": ORDER}, {"eval": FOCUSED},
        {"key": "ArrowUp", "alt": True}, {"eval": ORDER},
        # Espace sur le repli, puis Tab jusqu'à « Enregistrer pour ce rôle ».
        {"eval": "document.querySelector('[data-sar-fallback=\"qa\"]').focus();1"},
        {"key": " "}, {"eval": "window.__view.state.routeDrafts.qa.allow_general_fallback"},
    ]
    steps += [{"key": "Tab"}, {"eval": FOCUSED}] * 6
    steps += [{"shot": str(shots / "s06-desktop-qa-draft.png")}]
    out = run_plan(tmp_path, page, steps)
    assert out[0] == 7
    assert out[4] == ["petit", "disparu", "gpt-o"] and out[5] == ["down", "0"]
    assert out[7] == ["disparu", "petit", "gpt-o"] and out[8] == ["down", "1"]
    assert out[10] == ["petit", "disparu", "gpt-o"]
    assert out[13] is False
    tabbed = [v for v in out[14:-1] if isinstance(v, list)]
    assert ["save", None] in tabbed, tabbed


def test_saving_from_the_keyboard_writes_only_the_selected_role(tmp_path):
    page = build_page(tmp_path)
    steps = [
        {"eval": "window.__ready.then(()=>1)"},
        {"eval": "document.querySelector('[data-sar-cand-op=\"remove\"][data-sar-cand-i=\"2\"]').focus();1"},
        {"key": "Enter"},
        {"eval": "document.querySelector('[data-sar-route-save=\"qa\"]').focus();1"},
        {"key": "Enter"}, {"wait": 150},
        {"eval": WRITES},
        {"eval": "document.activeElement&&document.activeElement.hasAttribute('data-sar-route-notice')"},
        {"eval": "document.querySelector('[data-sar-live]').textContent"},
    ]
    out = run_plan(tmp_path, page, steps)
    assert out[6] == [["put", "qa", {"base_revision": "rr-1", "allow_general_fallback": True,
                                     "candidates": [{"agent": "claude", "model": "disparu"}, {"agent": "claude", "model": "petit"}]}]]
    assert out[7] is True and "ce rôle seul" in out[8]


def test_overview_opens_from_the_keyboard_and_unavailability_is_not_color_only(tmp_path):
    page = build_page(tmp_path)
    shots = shots_dir(tmp_path)
    style = ("(()=>{const li=document.querySelector('.sar-cand.unavailable');const s=getComputedStyle(li);"
             "return [s.borderTopStyle,li.textContent.includes('Indisponible')]})()")
    steps = [
        {"eval": "window.__ready.then(()=>1)"},
        {"eval": style},
        {"eval": "document.querySelector('[data-sar-overview]').focus();1"},
        {"key": "Enter"},
        {"eval": "document.activeElement&&document.activeElement.id"},
        {"eval": "document.querySelectorAll('.sar-ov-row').length"},
        {"shot": str(shots / "s06-desktop-overview.png")},
    ]
    out = run_plan(tmp_path, page, steps)
    assert out[1] == ["dashed", True]
    assert out[4] == "sar-title" and out[5] == 7


def test_narrow_width_has_no_horizontal_scroll_and_reduced_motion_stops_transitions(tmp_path):
    page = build_page(tmp_path)
    shots = shots_dir(tmp_path)
    overflow = ("(()=>{const h=document.getElementById('host');const wide=[...h.querySelectorAll('*')].filter(e=>e.getBoundingClientRect().right>innerWidth+1)"
                ".map(e=>e.className||e.tagName).slice(0,5);return [document.documentElement.scrollWidth<=innerWidth,wide]})()")
    steps = [
        {"eval": "window.__ready.then(()=>1)"},
        {"eval": overflow},
        {"eval": "document.querySelector('.sar-route').scrollIntoView();1"},
        {"shot": str(shots / "s06-narrow-qa-models.png")},
        {"eval": "getComputedStyle(document.querySelector('.sar-op')).transitionDuration"},
        {"eval": "window.__view.showOverview(true);1"},
        {"eval": overflow},
        {"shot": str(shots / "s06-narrow-overview.png")},
    ]
    out = run_plan(tmp_path, page, steps, width=390, height=844, reduced=True)
    assert out[1] == [True, []], out[1]
    assert re.fullmatch(r"0s(, 0s)*", out[4]), out[4]
    assert out[6] == [True, []], out[6]

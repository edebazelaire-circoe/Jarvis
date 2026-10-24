"""Onglet Sous-agents mesuré dans un vrai navigateur (jarvis-architecture-agents-settings-editor, Slice 06).

Une page STATIQUE (fichier temporaire) charge le module, son module de routage et l'adaptateur de fixture, avec
la feuille de style de `control_center.html` ; aucun Control Center n'est servi, le JARVIS vivant n'est jamais
visé. Chrome sans tête rejoue de vraies touches (harnais `_architecture_settings_browser.mjs`). Ce que le fichier
prouve :

- un candidat se réordonne au clavier seul (Entrée sur Monter, Alt + flèches), le focus suit le candidat ;
- le repli se bascule à l'Espace, Tab atteint « Enregistrer pour ce rôle », l'écriture ne vise que ce rôle ;
- (refonte-ui-settings, Slice 03) les actions « … » d'une ligne se déplient et se replient au clavier, l'en-tête
  d'une colonne de la matrice ouvre les modèles du rôle ; le tableau de bord tient les sept rôles sans débordement ;
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
from tests.unit.settings_visual import VIEWPORTS, VIEWS, capture_steps, stub
from tests.unit.test_wake_word_settings_browser import drive, eval_, got, key, served  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
PAGE = RUNTIME / "control_center.html"
FIXTURE = ROOT / "tests" / "fixtures" / "subagent_role_routing.json"
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


ACTIVE = ("(()=>{const a=document.activeElement;if(!a)return null;return a.id||a.getAttribute('data-sar-menu-act')"
          "||(a.hasAttribute('data-sar-more')&&'more:'+a.getAttribute('data-sar-more'))||a.tagName})()")
MENU = "(()=>{const m=document.querySelector('[data-sar-menu]');return m?m.getAttribute('data-sar-menu'):null})()"


def test_role_actions_and_matrix_reach_the_models_from_the_keyboard_and_unavailability_is_not_color_only(tmp_path):
    """Refonte Slice 03 : « … » d'une ligne (divulgation, Échap rend le focus), en-tête de la matrice → Modèles."""
    page = build_page(tmp_path)
    shots = shots_dir(tmp_path)
    style = ("(()=>{const li=document.querySelector('.sar-cand.unavailable');const s=getComputedStyle(li);"
             "const mx=document.querySelector('.sar-mx-on.unavailable .sar-mx-pos');"
             "return [s.borderTopStyle,li.textContent.includes('Indisponible'),getComputedStyle(mx).borderTopStyle,"
             "mx.parentElement.textContent.includes('indisponible')]})()")
    steps = [
        {"eval": "window.__ready.then(()=>1)"},
        {"eval": style},
        # Tab depuis la ligne choisie atteint son « … » ; Entrée déplie, le focus entre dans la liste d'actions.
        {"eval": "document.querySelector('[data-sar-role=\"qa\"]').focus();1"},
        {"key": "Tab"}, {"eval": ACTIVE},
        {"key": "Enter"}, {"eval": MENU}, {"eval": ACTIVE},
        {"key": "ArrowDown"}, {"eval": ACTIVE},
        {"shot": str(shots / "s03-row-actions.png")},
        # Échap replie sans fermer quoi que ce soit d'autre et rend le focus au bouton « … ».
        {"key": "Escape"}, {"eval": MENU}, {"eval": ACTIVE},
        # « Régler les modèles » mène au titre de la section Modèles du rôle.
        {"key": "Enter"}, {"key": "ArrowDown"}, {"key": "Enter"}, {"eval": MENU}, {"eval": ACTIVE},
        # En-tête de colonne de la matrice : la fiche d'un autre rôle s'ouvre sur ses modèles.
        {"eval": "document.querySelector('[data-sar-route-goto=\"coder\"]').focus();1"},
        {"key": "Enter"}, {"eval": ACTIVE},
        {"eval": "document.querySelector('.sar-row.selected').getAttribute('data-sar-row')"},
        {"eval": "document.querySelectorAll('.sar-row').length"},
    ]
    out = run_plan(tmp_path, page, steps, width=1672, height=941)
    assert out[1] == ["dashed", True, "dashed", True]
    assert out[4] == "more:qa"
    assert out[6] == "qa" and out[7] == "fiche"
    assert out[9] == "models"
    assert out[12] is None and out[13] == "more:qa"
    assert out[17] is None and out[18] == "sar-models-qa"
    assert out[21] == "sar-models-coder" and out[22] == "coder" and out[23] == 7


def test_full_registry_board_at_reference_size_without_page_overflow(tmp_path):
    """Les sept rôles du registre servi et l'instantané figé : aucun rôle écarté, aucun débordement de page ; la
    matrice seule défile en largeur si elle n'a pas la place."""
    page = build_page(tmp_path)
    shots = shots_dir(tmp_path)
    measure = ("(()=>{const q=s=>document.querySelector(s);const rows=[...document.querySelectorAll('.sar-row')];"
               "return {page:document.documentElement.scrollWidth-innerWidth,rows:rows.length,"
               "panels:[...document.querySelectorAll('.sar-board .set-panel')].map(p=>p.id),"
               "heads:[...document.querySelectorAll('.sar-rows-head .sar-h')].map(h=>h.textContent).filter(Boolean),"
               "brains:/Brains/.test(document.body.textContent),"
               "rowH:Math.round(Math.max(...rows.map(r=>r.getBoundingClientRect().height)))}})()")
    steps = [
        {"eval": "window.__ready.then(()=>1)"},
        {"eval": measure},
        {"eval": "scrollTo(0,0);1"},
        {"shot": str(shots / "s03-board-1672.png")},
    ]
    out = run_plan(tmp_path, page, steps, width=1672, height=941)
    m = out[1]
    assert m["page"] <= 0 and m["rows"] == 7 and m["brains"] is False, m
    assert m["panels"] == ["sar-p-overview", "sar-p-policy", "sar-p-roles", "sar-p-matrix", "sar-p-rules"], m
    assert m["heads"] == ["Rôle", "Modèle préféré", "Source", "Repli", "Outils", "Conditions d’usage"], m
    assert m["rowH"] < 110, m  # densité : une ligne de rôle tient sur une rangée


def test_narrow_width_has_no_horizontal_scroll_and_reduced_motion_stops_transitions(tmp_path):
    page = build_page(tmp_path)
    shots = shots_dir(tmp_path)
    # Le contenu d'un conteneur qui défile seul (la matrice) est rogné par lui : il ne compte pas comme débordement.
    overflow = ("(()=>{const h=document.getElementById('host');const wide=[...h.querySelectorAll('*')].filter(e=>e.getBoundingClientRect().right>innerWidth+1&&!e.parentElement.closest('.set-table-scroll'))"
                ".map(e=>e.className||e.tagName).slice(0,5);return [document.documentElement.scrollWidth<=innerWidth,wide]})()")
    steps = [
        {"eval": "window.__ready.then(()=>1)"},
        {"eval": overflow},
        {"eval": "document.querySelector('.sar-route').scrollIntoView();1"},
        {"shot": str(shots / "s06-narrow-qa-models.png")},
        {"eval": "getComputedStyle(document.querySelector('.sar-op')).transitionDuration"},
        {"eval": "document.getElementById('sar-p-matrix').scrollIntoView();1"},
        {"eval": overflow},
        {"shot": str(shots / "s03-narrow-matrix.png")},
        {"eval": "(()=>{const s=document.querySelector('.sar-matrix-shell .set-table-scroll');return s.scrollWidth>=s.clientWidth}" + ")()"},
    ]
    out = run_plan(tmp_path, page, steps, width=390, height=844, reduced=True)
    assert out[1] == [True, []], out[1]
    assert re.fullmatch(r"0s(, 0s)*", out[4]), out[4]
    assert out[6] == [True, []], out[6]


def test_changing_harness_then_adding_works_in_the_browser(tmp_path):
    """QA S06 (B1) : choisir un autre harness, revenir, puis ajouter au clavier."""
    page = build_page(tmp_path, selected="coder")
    shots = shots_dir(tmp_path)
    change = ("(v=>{const s=document.querySelector('[data-sar-add-agent=\"coder\"]');s.focus();s.value=v;"
              "s.dispatchEvent(new Event('change',{bubbles:true}));const m=document.querySelector('[data-sar-add-model=\"coder\"]');"
              "return [m.disabled,m.value,document.querySelector('[data-sar-add=\"coder\"]').disabled]})")
    disabled = ("(()=>{const b=document.querySelector('.sar-op:disabled');const s=getComputedStyle(b);"
                "return [s.opacity,s.borderTopStyle,s.cursor]})()")
    steps = [
        {"eval": "window.__ready.then(()=>1)"},
        {"eval": change + "('codex')"},
        {"eval": change + "('claude')"},
        {"eval": "document.querySelector('[data-sar-add=\"coder\"]').focus();1"},
        {"key": "Enter"},
        {"eval": "window.__view.state.routeDrafts.coder.candidates.map(c=>c.agent+':'+c.model)"},
        {"eval": disabled},
        {"eval": "document.querySelector('.sar-route').scrollIntoView();1"},
        {"shot": str(shots / "s06-fix-harness-add.png")},
    ]
    out = run_plan(tmp_path, page, steps)
    assert out[1] == [True, "__none__", True]  # Codex indisponible : rien à ajouter, dit tel quel
    assert out[2] == [False, "", False]       # retour sur Claude : « Modèle par défaut du CLI » choisi
    assert out[5] == ["claude:petit", "claude:"]
    assert out[6] == ["1", "dashed", "not-allowed"]


# --- Dans le vrai shell des Réglages (refonte-ui-settings, Slice 03) ------------------------------------------------
# Control Center isolé (fixture `served` : runtime temporaire, jamais le JARVIS vivant) ; la politique des rôles est
# l'instantané figé, servi à la page par `stub` : la capture montre des listes réelles de plusieurs candidats.


SHELL_MEASURE = """(()=>{const h=document.querySelector('[data-subagent-settings-host]');
  return {rows:h.querySelectorAll('.sar-row').length,panels:[...h.querySelectorAll('.set-panel')].map(p=>p.id),
    brains:[...document.querySelectorAll('#modalTabs [role=tab]')].map(t=>t.textContent.trim()),
    open:document.getElementById('overlay').classList.contains('open')}})()"""


async def test_board_in_the_settings_shell_captures_and_keeps_escape_inside_the_row_actions(served, tmp_path):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    shots = Path(os.environ.get("JARVIS_BROWSER_SHOTS") or tmp_path)
    shots.mkdir(parents=True, exist_ok=True)
    names = ["wide", "narrow"]
    menu = [eval_("document.querySelector('[data-sar-more=\"qa\"]').click(),1"),
            eval_("new Promise(r=>setTimeout(()=>r(1),120))"),
            eval_("document.activeElement&&document.activeElement.getAttribute('data-sar-menu-act')", "menu_focus"),
            key("Escape"), eval_("new Promise(r=>setTimeout(()=>r(1),120))"),
            eval_("[!!document.querySelector('[data-sar-menu]'),document.getElementById('overlay').classList.contains('open'),"
                  "document.activeElement&&document.activeElement.getAttribute('data-sar-more')]", "after_escape")]
    steps = capture_steps(VIEWS["subagents"], shots, "s03-after", viewports=names, ext="jpg",
                          stubs=[stub("/api/subagent-role-routing", fixture)], extra=[eval_(SHELL_MEASURE, "measure")])
    steps[0]["actions"] += menu
    out = await drive(served.url, steps)
    assert out["console"] == [], out["console"]
    for name, step in zip(names, out["steps"]):
        assert all(a["ok"] for a in step["actions"] if a.get("a") == "wait"), name
        assert got(step, "overflow")["page"] == 0 and max(got(step, "overflow")["containers"].values()) == 0, name
        m = got(step, "measure")
        assert m["rows"] == len(fixture["roles"]) and m["open"], m
        assert m["panels"] == ["sar-p-overview", "sar-p-policy", "sar-p-roles", "sar-p-matrix", "sar-p-rules"], m
        assert m["brains"] == ["Architecture", "Sous-agents"], m  # pas d'onglet « Brains »
        width, height = VIEWPORTS[name]
        assert (shots / f"s03-after-{width}x{height}.jpg").stat().st_size > 10_000
    first = out["steps"][0]
    assert got(first, "menu_focus") == "fiche"
    assert got(first, "after_escape") == [False, True, "qa"]  # Échap replie les actions, les Réglages restent ouverts

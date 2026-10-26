"""Interface de l'édition Presentation, dans un vrai Chrome sans tête (jarvis-presentation-edition-v1, Slice 08).

Contrat : `docs/control-center-shell.md` › *Product edition UI* ; données : `docs/product-edition.md`. La page est
celle que `ControlCenter.index` sert, marquée comme le serveur la marque (`page_edition_markup`) ; seul `fetch` est un
double (`_status_centre_browser.mjs` : `/api/boards/edition` rend la charge de Core, `POST /api/boards` suit la même
règle que Core, `POST /api/presentation-studio/presentations` crée une ligne du rail). Ce que ce fichier épingle :

- édition `presentation` : Trace, Test Lab, MCP et Prefabs ne sont ni montrés ni atteignables (clic, tabulation,
  raccourci) ; les Réglages montrent quatre catégories (« Connexions », sans Avancé ni Architecture & Agents) et une
  cible cachée ouvre la première catégorie, jamais une page vide ;
- création de Board : Présentation seule disponible ; Assistant et Réunion « Bientôt disponible », `aria-disabled`,
  et un clic n'envoie AUCUNE requête ; le Board créé est un Board Présentation ; un Board hérité d'un autre type est
  listé, jamais basculé ;
- lecture de l'édition tombée : l'écran le dit avec sa cause, rien n'est créable, « Réessayer » relit Core ;
- accueil des présentations : visible vide dans un Board Présentation, quatre étapes, « Nouvelle présentation »
  qui crée par Core ; ni « Remotion » ni « Remotion Studio… » dans le rail ;
- édition `full` : inchangée (dix outils, six catégories, trois types, rail vide caché, moteur nommé).

Captures : `JARVIS_S08_SHOTS=<dossier>` y écrit les états montrés à la validation Human (HV-UI-01).
Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.domain.product_edition import FULL_EDITION, PRESENTATION_EDITION
from jarvis.runtime.product_edition_env import page_edition_markup
from tests.unit.test_boards_card_browser import _chrome, _served_page

HARNESS = Path(__file__).parent / "_status_centre_browser.mjs"
SHOTS = os.environ.get("JARVIS_S08_SHOTS")
PRESENTATION = PRESENTATION_EDITION.to_payload()
FULL = FULL_EDITION.to_payload()
DEVELOPER_TOOLS = {"TRC": '.dock button[data-panel="trace"]', "LAB": "#openTestLab", "MCP": "#openMcpInspector",
                   "PFB": "#openPrefabs"}

#: Une boîte visible (ni `display:none`, ni sous `[hidden]`) ou `null`.
SHOWN = r"""(sel=>{const e=document.querySelector(sel);if(!e)return null;const cs=getComputedStyle(e);
  if(cs.display==='none'||cs.visibility==='hidden'||e.closest('[hidden]'))return false;const r=e.getBoundingClientRect();return r.width>0&&r.height>0})"""
KINDS = r"""[...document.querySelectorAll('#boardsCreateKindPick .bd-kindpick')].map(b=>({kind:b.dataset.kind,avail:b.getAttribute('data-bd-avail'),
  disabled:b.getAttribute('aria-disabled'),role:b.getAttribute('role'),tag:(b.querySelector('.bd-kindtag')||{}).textContent||'',
  tagShown:!!b.querySelector('.bd-kindtag:not([hidden])'),description:b.getAttribute('aria-description')||''}))"""
NOTE = "(n=>n&&!n.hidden?{text:n.querySelector('p').textContent,tone:n.dataset.tone,retry:!n.querySelector('#boardsKindRetry').hidden}:null)(document.getElementById('boardsKindNote'))"
FOCUS = "(()=>{const a=document.activeElement;return a?(a.id||a.dataset.kind||a.dataset.panel||a.tagName):null})()"


def _page(tmp_path: Path, edition: str | None) -> Path:
    """La page servie ; `edition` : marquée comme le serveur la marque pour cette édition (`None` : non marquée)."""

    page = _served_page(tmp_path)
    if edition is not None:
        env = {"JARVIS_PRODUCT_EDITION": edition}
        page.write_text(page_edition_markup(page.read_text(encoding="utf-8"), env), encoding="utf-8")
    return page


def _drive(tmp_path: Path, plan: list, edition: str | None) -> list:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    chrome = _chrome()
    page = _page(tmp_path, edition)
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    done = subprocess.run([node, str(HARNESS), str(page), chrome, "@" + str(plan_file)],
                          capture_output=True, text=True, encoding="utf-8", timeout=560, check=False)
    assert done.returncode == 0, done.stderr[-4000:]
    return json.loads(done.stdout)


def _shot(name: str, wait: int = 200) -> list:
    if not SHOTS:
        return []
    Path(SHOTS).mkdir(parents=True, exist_ok=True)
    return [["shot", "shot_" + name, str(Path(SHOTS) / f"{name}.png"), wait]]


def _no_errors(step: dict) -> None:
    bad = [line for line in step["console"] if line["type"] in ("exception", "error")]
    assert bad == [], bad


def _type(selector: str, value: str) -> str:
    return (f"(e=>{{e.focus();e.value={json.dumps(value)};e.dispatchEvent(new Event('input',{{bubbles:true}}));"
            f"return e.value}})(document.querySelector({json.dumps(selector)}))")


def _boards(*rows) -> list:
    return [{"board_id": board_id, "title": title, "status": "active", "board_kind": kind} for board_id, title, kind in rows]


# ------------------------------------------------------------------ surfaces de développement


@pytest.mark.parametrize("width, height", [(1440, 900), (600, 800)])
def test_presentation_hides_the_developer_tools_everywhere(tmp_path, width, height):
    actions = [
        ["eval", "shown", "({" + ",".join(f"{code}:{SHOWN}({json.dumps(sel)})" for code, sel in DEVELOPER_TOOLS.items())
         + f",SET:{SHOWN}('#openSettings'),WSP:{SHOWN}('#openWorkspace'),INS:{SHOWN}('#openStudioInspector')}})", 50],
        ["eval", "markup", "document.documentElement.getAttribute('data-developer-surfaces')", 50],
        ["click", "more", "#dockMore", 250],
        ["eval", "popShown", f"({{TRC:{SHOWN}('.dock button[data-panel=\"trace\"]'),SET:{SHOWN}('#openSettings')}})", 50],
        *_shot(f"after-launcher-{width}x{height}"),
        ["key", "esc", "Escape", 150],
        ["key", "down", "ArrowDown", 200],
        ["eval", "first", FOCUS, 50],
        ["key", "end", "End", 150],
        ["eval", "last", FOCUS, 50],
        ["key", "esc2", "Escape", 150],
        ["eval", "blur", "document.activeElement.blur(),1", 50],
        ["key", "t", "t", 300],
        ["eval", "trace", "document.getElementById('panel').classList.contains('open')", 50],
    ]
    step = _drive(tmp_path, [{"width": width, "height": height, "seed": {"edition": PRESENTATION}, "actions": actions}],
                  "presentation")[0]
    _no_errors(step)
    r = step["results"]
    assert r["markup"] == "hidden"
    assert r["shown"] == {"TRC": False, "LAB": False, "MCP": False, "PFB": False, "SET": False, "WSP": False, "INS": False}, \
        "every popover tool is folded at rest"
    assert r["popShown"] == {"TRC": False, "SET": True}
    assert r["first"] == "openSettings" and r["last"] == "openStudioInspector", "the roving list skips the hidden tools"
    assert r["trace"] is False, "the Trace shortcut does not open a hidden surface"


def test_presentation_settings_show_four_categories_and_never_a_hidden_page(tmp_path):
    actions = [
        ["eval", "open", "openSettingsHub({source:'test'}),1", 500],
        ["eval", "cards", "[...document.querySelectorAll('#settingsHubGrid [data-hub-category]')].map(c=>[c.dataset.hubCategory,c.querySelector('.set-hub-name').textContent])", 50],
        *_shot("after-settings-hub-1440x900"),
        ["eval", "close", "closeSettingsHub(),1", 400],
        ["eval", "target", "openSettingsTab('prompts'),1", 800],
        ["eval", "landed", "({category:SET.category,rail:[...document.querySelectorAll('#settingsCategories [role=tab],#settingsCategories button')].map(b=>b.textContent.trim()).filter(Boolean)})", 50],
        ["eval", "close2", "closeSettings(),1", 300],
        ["eval", "barehands", "window.JarvisSettingsRegistry.targetShown('barehands',window.JarvisSettingsRegistry.page,settingsEditionOptions())", 50],
    ]
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": {"edition": PRESENTATION}, "actions": actions}],
                  "presentation")[0]
    _no_errors(step)
    r = step["results"]
    assert r["cards"] == [["voice_audio", "Personnalisation"], ["memory_knowledge", "Mémoire & Connaissances"],
                          ["interface_interactions", "Interface & Interactions"], ["connections", "Connexions"]]
    assert r["landed"]["category"] == "voice_audio", "a hidden target opens the first shown category"
    assert not any("Avancé" in label or "Architecture" in label for label in r["landed"]["rail"]), r["landed"]


# ------------------------------------------------------------------ création de Board


def test_presentation_board_creation_offers_presentation_only_and_sends_nothing_for_the_others(tmp_path):
    actions = [
        ["click", "card", "#boardsButton", 600],
        *_shot("after-boards-grid-1440x900"),
        ["click", "new", "#boardsNewBoard", 400],
        ["eval", "kinds", KINDS, 50],
        ["eval", "focus", FOCUS, 50],
        ["eval", "note", NOTE, 50],
        *_shot("after-board-kinds-1440x900"),
        ["click", "meeting", '#boardsCreateKindPick [data-kind="meeting"]', 300],
        ["eval", "afterMeeting", f"({{screen:document.getElementById('boardsPanel').getAttribute('data-bd-screen'),note:{NOTE}}})", 50],
        ["key", "assistantKey", "ArrowLeft", 100],
        ["click", "assistant", '#boardsCreateKindPick [data-kind="assistant"]', 300],
        ["eval", "afterAssistant", "document.getElementById('boardsPanel').getAttribute('data-bd-screen')", 50],
        ["click", "presentation", '#boardsCreateKindPick [data-kind="presentation"]', 300],
        ["eval", "screen", "document.getElementById('boardsPanel').getAttribute('data-bd-screen')", 50],
        ["eval", "typed", _type("#boardsCreateTitle", "Pitch client"), 50],
        ["click", "create", "#boardsCreate", 900],
    ]
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": {"edition": PRESENTATION}, "actions": actions}],
                  "presentation")[0]
    _no_errors(step)
    r = step["results"]
    kinds = {k["kind"]: k for k in r["kinds"]}
    assert kinds["presentation"]["avail"] == "available" and kinds["presentation"]["disabled"] is None
    for kind in ("assistant", "meeting"):
        assert kinds[kind]["avail"] == "soon" and kinds[kind]["disabled"] == "true" and kinds[kind]["role"] == "radio"
        assert kinds[kind]["tag"] == "Bientôt disponible" and kinds[kind]["tagShown"]
        assert "bientôt disponible" in kinds[kind]["description"]
    assert r["focus"] == "presentation", "the kind screen lands on the only available kind"
    assert r["note"]["tone"] == "info" and "Assistant et Réunion arrivent bientôt" in r["note"]["text"]
    assert r["afterMeeting"]["screen"] == "kind" and "Réunion : bientôt disponible" in r["afterMeeting"]["note"]["text"]
    assert r["afterAssistant"] == "kind" and r["screen"] == "name"
    posts = [b for b in step["bodies"] if b["path"] == "/api/boards"]
    assert posts == [{"path": "/api/boards", "body": {"title": "Pitch client", "board_kind": "presentation"}}], step["bodies"]
    assert "POST /api/boards/switch" not in step["calls"]


def test_a_legacy_board_is_listed_but_never_switched(tmp_path):
    seed = {"edition": PRESENTATION, "boards": _boards(("default", "Pitch", "presentation"), ("old", "Ancien assistant", "assistant")),
            "activeBoard": "default"}
    actions = [
        ["click", "card", "#boardsButton", 700],
        ["eval", "row", "(li=>({avail:li.getAttribute('data-bd-avail'),state:li.querySelector('[data-role=state]').textContent,"
                        "disabled:li.querySelector('.bd-pick').getAttribute('aria-disabled'),"
                        "tools:[...li.querySelectorAll('.bd-tools [data-bd-action]')].map(b=>b.dataset.bdAction)}))"
                        "(document.querySelector('#boardsList [data-board-id=\"old\"]'))", 50],
        ["click", "pick", '#boardsList [data-board-id="old"] .bd-pick', 500],
        ["eval", "noteText", "document.getElementById('boardsNote').textContent", 50],
        *_shot("after-legacy-board-1440x900"),
    ]
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed, "actions": actions}], "presentation")[0]
    _no_errors(step)
    r = step["results"]
    assert r["row"]["avail"] == "soon" and r["row"]["disabled"] == "true" and r["row"]["state"] == "Bientôt disponible"
    assert {"rename", "inspect", "archive"} <= set(r["row"]["tools"]), "a legacy Board stays readable, renamable, archivable"
    assert "POST /api/boards/switch" not in step["calls"], step["calls"]
    assert "ne s’ouvre pas" in r["noteText"]


def test_an_unreadable_edition_says_so_and_retries(tmp_path):
    seed = {"edition": PRESENTATION, "editionFail": {"status": 503, "code": "core_unreachable"}}
    actions = [
        ["click", "card", "#boardsButton", 500],
        ["click", "new", "#boardsNewBoard", 400],
        ["eval", "kinds", KINDS, 50],
        ["eval", "note", NOTE, 50],
        *_shot("after-board-kinds-unreadable-1440x900"),
        ["click", "presentation", '#boardsCreateKindPick [data-kind="presentation"]', 200],
        ["eval", "screen", "document.getElementById('boardsPanel').getAttribute('data-bd-screen')", 50],
        ["eval", "coreBack", "window.__sc.editionFail=null,1", 50],
        ["click", "retry", "#boardsKindRetry", 800],
        ["eval", "kindsAfter", KINDS, 50],
        ["eval", "noteAfter", NOTE, 50],
    ]
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed, "actions": actions}], "presentation")[0]
    r = step["results"]
    assert all(k["avail"] == "unknown" and k["disabled"] == "true" for k in r["kinds"]), r["kinds"]
    assert r["note"]["tone"] == "bad" and r["note"]["retry"] and "Types de Board illisibles" in r["note"]["text"]
    assert "Core ne répond pas" in r["note"]["text"], "the real cause is said, not a generic one"
    assert r["screen"] == "kind", "nothing is creatable while Core has not answered"
    assert {k["kind"]: k["avail"] for k in r["kindsAfter"]} == {"assistant": "soon", "presentation": "available", "meeting": "soon"}
    assert r["noteAfter"]["tone"] == "info"
    assert not any(b["path"] == "/api/boards" for b in step["bodies"])


# ------------------------------------------------------------------ accueil des présentations


@pytest.mark.parametrize("width, height", [(1440, 900), (1280, 720), (600, 800)])
def test_the_presentation_home_shows_the_journey_and_creates_through_core(tmp_path, width, height):
    seed = {"edition": PRESENTATION, "rail": False, "boards": _boards(("default", "Pitch client", "presentation"))}
    drawer = width <= 700
    actions = [
        ["eval", "settle", "1", 1500],
        *([["click", "tab", "#presentationRail .jvr-tool", 400]] if drawer else []),
        ["eval", "rail", "(h=>({visible:!h.hidden,home:!!h.querySelector('.jvr-homebox:not([hidden]) .jvr-step'),"
                         "steps:[...h.querySelectorAll('.jvr-step strong')].map(s=>s.textContent),"
                         "acts:[...h.querySelectorAll('[data-home-act]')].map(b=>b.dataset.homeAct),"
                         "newShown:!h.querySelector('.jvr-new').hidden,text:h.textContent}))(document.getElementById('presentationRail'))", 50],
        *_shot(f"after-presentation-home-{width}x{height}"),
        ["click", "create", '#presentationRail [data-home-act="create"]', 300],
        ["eval", "dialog", "(d=>d?{title:d.querySelector('h2').textContent,focus:document.activeElement.tagName}:null)(document.querySelector('.jvr-dialog'))", 50],
        ["eval", "typed", _type(".jvr-dialog input", "Bilan annuel"), 50],
        *_shot(f"after-presentation-create-{width}x{height}"),
        ["click", "ok", ".jvr-dialog .jvr-row button:last-child", 1500],
        ["eval", "after", "(h=>({cards:[...h.querySelectorAll('.jvr-item')].map(b=>b.getAttribute('aria-label')),"
                          "note:h.querySelector('.jvr-note').textContent,home:!!h.querySelector('.jvr-homebox:not([hidden])')}))"
                          "(document.getElementById('presentationRail'))", 50],
        *_shot(f"after-presentation-created-{width}x{height}"),
        ["rclick", "menu", "#presentationRail .jvr-item", 300],
        ["eval", "items", "[...document.querySelectorAll('.jvr-menu [role=menuitem]')].map(b=>b.textContent)", 50],
    ]
    step = _drive(tmp_path, [{"width": width, "height": height, "seed": seed, "actions": actions}], "presentation")[0]
    _no_errors(step)
    r = step["results"]
    assert r["rail"]["visible"] and r["rail"]["home"], r["rail"]
    assert r["rail"]["steps"] == ["Rassemblez vos sources", "Créez la présentation", "Faites écrire les scènes",
                                  "Relisez, présentez, exportez"]
    assert r["rail"]["acts"] == ["dossier", "create", "chat"] and r["rail"]["newShown"]
    for word in ("Remotion", "npm", "MCP", "CLI"):
        assert word not in r["rail"]["text"], word
    assert r["dialog"] == {"title": "Nouvelle présentation", "focus": "INPUT"}
    posts = [b for b in step["bodies"] if b["path"] == "/api/presentation-studio/presentations"]
    assert posts == [{"path": "/api/presentation-studio/presentations", "body": {"title": "Bilan annuel"}}], "no engine is named"
    assert r["after"]["cards"] and r["after"]["cards"][0].startswith("Bilan annuel, Présentation :"), r["after"]
    assert not r["after"]["home"] and "créée" in r["after"]["note"]
    assert "Remotion Studio…" not in r["items"] and "Présenter" in r["items"], r["items"]


def test_a_failed_creation_says_its_cause_and_the_home_stays(tmp_path):
    seed = {"edition": PRESENTATION, "rail": False, "boards": _boards(("default", "Pitch", "presentation")),
            "createFail": {"status": 409, "code": "presentation_studio_limit_reached"}}
    actions = [
        ["eval", "settle", "1", 1500],
        ["click", "create", "#presentationRail .jvr-new", 300],
        ["eval", "typed", _type(".jvr-dialog input", "Encore une"), 50],
        ["click", "ok", ".jvr-dialog .jvr-row button:last-child", 1200],
        ["eval", "after", "(h=>({note:h.querySelector('.jvr-note').textContent,kind:h.querySelector('.jvr-note').dataset.kind,"
                          "home:!!h.querySelector('.jvr-homebox:not([hidden])'),busy:h.querySelector('.jvr-new').getAttribute('aria-disabled')}))"
                          "(document.getElementById('presentationRail'))", 50],
    ]
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed, "actions": actions}], "presentation")[0]
    r = step["results"]["after"]
    assert r["kind"] == "failed" and "nombre maximal" in r["note"], r
    assert r["home"] and r["busy"] is None, "the home stays and the button is usable again"


# ------------------------------------------------------------------ édition full inchangée


def test_full_edition_is_unchanged(tmp_path):
    seed = {"edition": FULL, "rail": False, "boards": _boards(("default", "Jarvis", "presentation"))}
    actions = [
        ["eval", "markup", "document.documentElement.getAttribute('data-developer-surfaces')", 50],
        ["click", "more", "#dockMore", 250],
        ["eval", "tools", "({" + ",".join(f"{code}:{SHOWN}({json.dumps(sel)})" for code, sel in DEVELOPER_TOOLS.items()) + "})", 50],
        ["key", "esc", "Escape", 150],
        ["eval", "hub", "openSettingsHub({source:'test'}),[...document.querySelectorAll('#settingsHubGrid [data-hub-category]')].length", 300],
        ["eval", "names", "[...document.querySelectorAll('#settingsHubGrid .set-hub-name')].map(n=>n.textContent)", 50],
        ["eval", "close", "closeSettingsHub(),1", 400],
        ["click", "card", "#boardsButton", 500],
        ["click", "new", "#boardsNewBoard", 400],
        ["eval", "kinds", KINDS, 50],
        ["eval", "note", NOTE, 50],
        ["key", "esc2", "Escape", 200],
        ["key", "esc3", "Escape", 200],
        ["eval", "rail", "document.getElementById('presentationRail').hidden", 50],
    ]
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed, "actions": actions}], None)[0]
    _no_errors(step)
    r = step["results"]
    assert r["markup"] == "__JARVIS_DEVELOPER_SURFACES__" or r["markup"] == "visible"
    assert r["tools"] == {"TRC": True, "LAB": True, "MCP": True, "PFB": True}
    assert r["hub"] == 6 and "Plugins & MCP" in r["names"] and "Avancé & Diagnostics" in r["names"]
    assert all(k["avail"] == "available" and k["disabled"] is None for k in r["kinds"]), r["kinds"]
    assert r["note"] is None
    assert r["rail"] is True, "an empty rail stays hidden in full"

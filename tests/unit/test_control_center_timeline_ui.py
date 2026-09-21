"""Contrat de page de la chronologie de conversation (Slice 05).

La logique est prouvée par `test_control_center_timeline_js.py` (node) ; ici :
le module est bien inséré dans la page servie, l'entrée du dock et la vue
plein écran portent leurs rôles ARIA, les quatre lanes sont étiquetées par du
texte (la couleur ne porte jamais seule le sens), chaque élément que le bloc
navigateur cherche existe, et le thème Cosmos connaît le nouvel outil.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from jarvis.runtime.control_center import TIMELINE_SCRIPT_MARKER, ControlCenter

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "jarvis" / "runtime" / "control_center.html"
MODULE = ROOT / "jarvis" / "runtime" / "control_center_timeline.js"
WORK = ROOT / "jarvis" / "runtime" / "control_center_work.js"


def section(html: str) -> str:
    start = html.index('<section class="tl" id="timeline"')
    return html[start: html.index("</section>", start)]


async def test_the_timeline_module_is_injected_in_the_served_page(tmp_path):
    served = (await ControlCenter(runtime_root=tmp_path, project_root=tmp_path).index(None)).text
    assert TIMELINE_SCRIPT_MARKER not in served
    assert "const JarvisTimelineCore=(function(){" in served
    assert "(function installJarvisTimeline(){" in served
    # After the page helpers it may call, inside the same classic script.
    assert served.index("const $=s=>document.querySelector(s)") < served.index("const JarvisTimelineCore=")
    assert served.index("const JarvisTimelineCore=") < served.index("</script>")


def test_the_dock_opens_a_full_screen_dialog_with_labelled_controls():
    html = PAGE.read_text(encoding="utf-8")
    dock = html[html.index('<nav class="dock"'): html.index("</nav>", html.index('<nav class="dock"'))]
    button = re.search(r'<button id="openTimeline"[^>]*>CNV</button>', dock)
    assert button, "timeline entry missing from the dock"
    for attribute in ('aria-haspopup="dialog"', 'aria-expanded="false"', 'aria-controls="timeline"', 'title="Conversation'):
        assert attribute in button.group(0)
    view = section(html)
    head = view[: view.index(">")]
    for attribute in ('role="dialog"', 'aria-modal="true"', 'aria-labelledby="tlTitle"', 'aria-describedby="tlHelp"', " hidden"):
        assert attribute in head
    assert re.search(r'id="tlTitle"><svg[^>]*aria-hidden="true">.*?</svg><span class="tl-tt">Conversation</span></h2>', view)
    assert re.search(r'<label class="tl-field"><span>Conversation</span><select id="tlConversation">', view)
    assert re.search(r'<fieldset class="tl-seg"><legend>[^<]+</legend><label><input type="radio" name="tlFilter" value="all" checked>', view)
    assert 'name="tlFilter" value="public"' in view
    assert 'id="tlStatus" role="status"' in view and 'id="tlAnnounce" aria-live="polite"' in view
    assert 'id="tlRetry" hidden>Réessayer maintenant</button>' in view
    assert 'aria-label="Fermer la chronologie (Échap)"' in view and 'aria-label="Fermer le détail (Échap)"' in view
    assert '<aside class="tl-drawer" id="tlDrawer" aria-labelledby="tlDrawerTitle" hidden>' in view
    # The scroll region is itself focusable: a click in empty space keeps the focus inside the dialog.
    assert 'id="tlScroll" role="region" tabindex="0" aria-label="Chronologie : quatre lanes sur un même axe de temps"' in view
    help_text = re.search(r'<p class="sr" id="tlHelp">([^<]+)</p>', view).group(1)
    for key in ("Flèches haut et bas", "gauche et droite", "Entrée", "Échap"):
        assert key in help_text
    zoom = re.findall(r'<option value="(\d+)"( selected)?>', view[view.index('id="tlZoom"'):])
    assert [value for value, _ in zoom][:5] == ["20", "40", "60", "100", "160"] and ("60", " selected") in zoom
    assert "const DEFAULT_PPS=60;" in MODULE.read_text(encoding="utf-8")  # the selected option is the module default


def test_every_lane_is_labelled_by_text_in_the_locked_order_and_colors(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    lanes = json.loads(subprocess.run(
        [node, "-e", f"process.stdout.write(JSON.stringify(require({json.dumps(str(MODULE))}).LANES))"],
        capture_output=True, text=True, encoding="utf-8", timeout=30, check=True).stdout)
    view = section(PAGE.read_text(encoding="utf-8"))
    heads = re.findall(r'<div class="tl-hcell" data-lane="(\w+)"><svg[^>]*aria-hidden="true">.*?</svg><span>([^<]+)</span>', view)
    assert heads == [(lane["id"], lane["label"]) for lane in lanes]
    assert [lane["id"] for lane in lanes] == ["user", "mouth", "brain", "subagent"]
    empties = dict(re.findall(r'<p class="tl-lempty" data-empty="(\w+)" hidden>([^<]+)</p>', view))
    assert empties == {lane["id"]: lane["empty"] for lane in lanes}
    css = PAGE.read_text(encoding="utf-8")
    tokens = re.search(r"\.tl\{--tl-user:(#[0-9a-f]{6});--tl-mouth:(#[0-9a-f]{6});--tl-brain:(#[0-9a-f]{6});--tl-sub:(#[0-9a-f]{6})", css)
    assert tokens, "lane color tokens missing"
    user, mouth, brain, sub = (tuple(int(t[i:i + 2], 16) for i in (1, 3, 5)) for t in tokens.groups())
    assert min(user) > 235  # white
    assert mouth[2] > 240 and mouth[0] < mouth[1] < mouth[2]  # light blue
    assert brain[0] > 240 and brain[0] > brain[1] > brain[2]  # orange
    assert sub[0] > 240 and sub[1] < 120 and sub[2] < 120  # red
    assert re.search(r"\.tl\{[^}]*backdrop-filter:blur\(\d+px\)", css)  # dark, blurred full-screen background
    assert re.search(r"\.tl-e:focus-visible\{outline:\d+px solid", css)
    assert re.search(r"@media\(prefers-reduced-motion:reduce\)\{[^\n]*\.tl-status \.tl-led\{animation:none", css)
    assert re.search(r"\.tl-x\{min-width:(4[4-9]|[5-9]\d)px;min-height:(4[4-9]|[5-9]\d)px", css)  # touch target >= 44 px
    narrow = css[css.index("@media(max-width:700px){\n  /* Écran étroit"):]
    assert ".tl-field>span{position:absolute" in narrow[:1200]  # field labels kept for screen readers, not drawn
    # Public text is never clamped: no line clamp on card text, the text wraps.
    card_text = re.search(r"\.tl-t\{[^}]*\}", css).group(0)
    assert "line-clamp" not in card_text and "pre-wrap" in card_text


def test_every_element_the_browser_block_looks_up_exists():
    html = PAGE.read_text(encoding="utf-8")
    source = MODULE.read_text(encoding="utf-8")
    browser = source[source.index("(function installJarvisTimeline(){"):]
    wanted = set(re.findall(r"q\('#(\w+)'\)", browser)) | set(re.findall(r"getElementById\('(\w+)'\)", browser))
    assert {"timeline", "openTimeline", "tlConversation", "tlDrawer", "tlItems", "tlScroll"} <= wanted
    # Slice 06 panels are built inside the drawer by the module itself.
    missing = sorted(i for i in wanted if f'id="{i}"' not in html and f'id="{i}"' not in browser)
    assert not missing, missing
    for selector in re.findall(r"\[data-(count|empty)=\"\$\{lane\.id\}\"\]", browser):
        assert f'data-{selector}="subagent"' in html


def test_the_cosmos_theme_knows_every_dock_tool_and_moves_the_pills():
    """Le thème Cosmos connaît CHAQUE outil du dock, et les pastilles passent sous lui.

    Slice 11 du Test Lab : un sixième outil (`openTestLab`) a rejoint le dock. Un
    outil que `setCosmosTools` ignore garde son libellé texte au milieu d'une rangée
    d'icônes, et une rangée plus large recouvre les pastilles — donc les deux
    constantes se recalculent ici plutôt que de se découvrir à l'écran.
    """
    work = WORK.read_text(encoding="utf-8")
    html = PAGE.read_text(encoding="utf-8")
    dock = html[html.index('<nav class="dock"') : html.index("</nav>")]
    tools = re.findall(r"<button (?:id|data-panel)=\"([^\"]+)\"", dock)
    assert len(tools) == 6, tools
    for name in ("timeline", "testlab", "trace", "settings", "errors", "agents"):
        assert f"{name}:`<svg ${{common}}>" in work or f"'{name}'," in work, name
    assert "['openTimeline','timeline',2]" in work and "['openTestLab','testlab',3]" in work
    assert "[null,'errors',6]" in work
    # 6 × 34 px + 5 × 6 px = 234 px de rangée depuis right:18px, puis 10 px de marge.
    assert 'html[data-jarvis-theme="cosmos"] .bgpills{top:22px;right:262px;' in work
    # Dock vertical : 6 × 52 px + 5 × 10 px = 362 px, centré, plus 12 px de marge.
    assert ".bgpills{position:absolute;z-index:40;right:30px;top:calc(50% + 193px);" in html


def test_the_timeline_module_parses_with_node():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    completed = subprocess.run([node, "--check", str(MODULE)], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr


def test_page_shortcuts_never_cross_the_open_timeline():
    html = PAGE.read_text(encoding="utf-8")
    handler = html[html.index("window.addEventListener('keydown',event=>{\n  if(SET.capture"):]
    handler = handler[: handler.index("\n});")]
    guard = handler.index("if(timeline&&!timeline.hidden)return;")
    assert guard < handler.index("const match=")  # ignored before any shortcut is resolved


def test_the_open_dialog_makes_the_rest_of_the_page_inert_and_restores_it():
    source = MODULE.read_text(encoding="utf-8")
    browser = source[source.index("(function installJarvisTimeline(){"):]
    assert "S.inerted=[...document.body.children].filter(n=>n!==root&&!n.inert&&n.tagName!=='SCRIPT');" in browser
    assert "for(const node of S.inerted)node.inert=true;" in browser[browser.index("function openView(){"):browser.index("function closeView(){")]
    assert "for(const node of S.inerted)node.inert=false;" in browser[browser.index("function closeView(){"):]
    trap = browser[browser.index("if(event.key==='Tab'){"):]
    assert "n.tabIndex>=0" in trap[:600]  # roving entries (tabindex -1) never enter the trap list


def test_the_cosmos_theme_keeps_the_voice_state_readable_on_a_phone():
    work = WORK.read_text(encoding="utf-8")
    narrow = work[work.index('@media(max-width:700px){\n  html[data-jarvis-theme="cosmos"] .dock{right:10px;top:10px}'):]
    narrow = narrow[: narrow.index("\n}")]
    pills = re.search(r"\.bgpills\{right:(\d+)px;top:(\d+)px\}", narrow)
    assert pills and int(pills.group(2)) >= 50  # pills move below the 34 px tool row instead of covering the state
    panel_top = int(re.search(r"\.panel\{left:10px;right:10px;top:(\d+)px", narrow).group(1))
    assert panel_top > int(pills.group(2)) + 28


def test_dot_labels_are_bounded_and_never_widen_the_scroll_area():
    css = PAGE.read_text(encoding="utf-8")
    tip = re.search(r"\.tl-tip\{[^}]*\}", css).group(0)
    assert "position:fixed" in tip and "white-space:normal" in tip and "overflow-wrap:anywhere" in tip
    assert re.search(r"max-width:min\(\d+rem,calc\(100vw - \d+px\)\)", tip)
    title = re.search(r"\.tl-drawer h3\{[^}]*\}", css).group(0)
    assert "min-width:0" in title and "overflow-wrap:anywhere" in title and "white-space:nowrap" not in title
    source = MODULE.read_text(encoding="utf-8")
    assert "function placeTips(){" in source and "area.right-margin-w" in source


def test_the_toolbar_offers_search_transcript_and_export_as_labelled_disclosure_buttons():
    html = PAGE.read_text(encoding="utf-8")
    view = section(html)
    group = re.search(r'<div class="tl-acts" role="group" aria-label="[^"]+">(.*?)</div>', view, re.S)
    assert group, "Slice 06 action group missing from the timeline toolbar"
    buttons = re.findall(r'<button type="button" class="tl-act" id="(\w+)" aria-controls="tlDrawer" aria-expanded="false" '
                         r'title="[^"]+"><svg[^>]*aria-hidden="true">.*?</svg><span class="tl-al">([^<]+)</span></button>',
                         group.group(1), re.S)
    assert buttons == [("tlSearchOpen", "Rechercher"), ("tlTranscriptOpen", "Transcription"),
                       ("tlExportOpen", "Exporter JSONL")]
    narrow = html[html.index("@media(max-width:700px){\n  /* Écran étroit"):]
    narrow = narrow[: narrow.index("\n}")]
    assert ".tl-al{position:absolute;width:1px" in narrow  # icon-only on a phone, label kept for screen readers
    assert re.search(r"\.tl-act\{min-width:36px;min-height:36px", narrow)
    assert ".tl-acts{order:-1" in narrow  # icons join the conversation row instead of adding a toolbar row


def test_panels_share_the_drawer_escape_and_focus_rules():
    source = MODULE.read_text(encoding="utf-8")
    browser = source[source.index("(function installJarvisTimeline(){"):]
    assert "if(S.selected)closeDrawer(true);else if(S.panel)closePanel(true);else closeView();" in browser
    assert "if(S.panel)closePanel(false);" in browser[browser.index("function openDetail(id){"):]
    close_view = browser[browser.index("function closeView(){"):browser.index("async function loadConversations")]
    assert "closePanel(false);" in close_view  # closing the view aborts in-flight search/transcript/export
    assert 'role="search"' in browser and 'aria-label="Résultats de recherche"' in browser
    close_panel = browser[browser.index("function closePanel("):browser.index("function renderPanel(")]
    for job in ("S.search.controller.abort()", "S.transcript.controller.abort()", "S.exportJob.controller.abort()"):
        assert job in close_panel
    assert "data-tl-cancel" in browser and "data-tl-retry-job" in browser
    assert "T.exportSummary(" in browser and "export_incomplete" in browser  # a download without trailer is an error
    try_jump = browser[browser.index("function tryJump(){"):browser.index("async function loadTranscript(")]
    assert "matchMedia('(max-width:1099px)')" in try_jump and "closePanel(false)" in try_jump  # drawer never hides it
    assert "T.trackNewEntries(" in browser  # behaviour tested in test_control_center_timeline_js.py


def test_transcript_panel_requests_the_local_offset_and_export_panel_maps_broken_streams():
    source = MODULE.read_text(encoding="utf-8")
    browser = source[source.index("(function installJarvisTimeline(){"):]
    load = browser[browser.index("async function loadTranscript("):browser.index("function saveBlob(")]
    assert "T.transcriptUrl(conv,mode,offset)" in load and "T.localOffsetMinutes()" in load
    export = browser[browser.index("async function runExport("):]
    assert "T.exportFailure(error,{received:job.received,timedOut:!!job.timedOut})" in export

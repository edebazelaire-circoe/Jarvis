"""Contrat de page du Chat (handoff jarvis-unified-chat-and-board-drop, Slice 06).

Le comportement est prouvé dans un vrai Chrome par
`test_control_center_chat_browser.py` ; ici, sur le texte : les deux modules
sont insérés dans la page servie (modèle avant vue, après les fonctions de page
qu'ils appellent), l'onglet et le panneau portent leurs ids et rôles ARIA, le
panneau réutilise `.panel`, les toasts remontent au-dessus de l'onglet, le
module n'appelle que les routes du Chat (`docs/chat.md`) et ne pose jamais de
contenu d'événement en HTML.
"""

from __future__ import annotations

from pathlib import Path
import re

from jarvis.runtime.control_center import (
    CHAT_MODEL_SCRIPT_MARKER,
    CHAT_SCRIPT_MARKER,
    ControlCenter,
)

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "jarvis" / "runtime" / "control_center.html"
MODULE = ROOT / "jarvis" / "runtime" / "control_center_chat.js"


def _chat_markup(html: str) -> str:
    start = html.index('<button type="button" class="chat-tab" id="chatTab"')
    return html[start: html.index("</section>", start)]


async def test_markers_are_replaced_model_before_view_inside_the_page_script(tmp_path):
    served = (await ControlCenter(runtime_root=tmp_path, project_root=tmp_path).index(None)).text
    assert CHAT_MODEL_SCRIPT_MARKER not in served and CHAT_SCRIPT_MARKER not in served
    model_at = served.index("root.JarvisChatModel=api")
    view_at = served.index("root.JarvisChat=api")
    assert served.index("function closePanel(){") < model_at < view_at < served.rindex("</script>")
    assert served.index("const $=s=>document.querySelector(s)") < view_at


def test_tab_and_panel_ids_roles_and_reuse_of_panel():
    markup = _chat_markup(PAGE.read_text(encoding="utf-8"))
    tab = re.search(r'<button type="button" class="chat-tab" id="chatTab"[^>]*>CHAT</button>', markup)
    assert tab, "the Chat tab is a real button labelled in text"
    for attribute in ('aria-controls="chatPanel"', 'aria-expanded="false"', 'aria-label="Chat · écrire à Jarvis"'):
        assert attribute in tab.group(0)
    head = re.search(r'<section class="panel chat-panel" id="chatPanel"[^>]*>', markup).group(0)
    assert 'aria-labelledby="chatTitle"' in head and " hidden" in head
    assert '<h2 id="chatTitle">Chat</h2>' in markup
    assert 'id="chatClose" aria-label="Fermer le chat (Échap)"' in markup
    assert 'id="chatFeed" role="status"' in markup
    assert re.search(r'<ol class="chat-log" id="chatLog" role="log" aria-live="polite" aria-relevant="additions" '
                     r'aria-label="[^"]+" tabindex="0">', markup)
    assert 'id="chatLock" role="status" hidden' in markup
    assert 'id="chatSwitch" hidden>Passer au chat</button>' in markup
    assert '<label class="chat-sr" for="chatInput">' in markup
    assert re.search(r'<textarea id="chatInput"[^>]*maxlength="8192"[^>]*aria-describedby="chatLockText chatHint"', markup)
    assert 'id="chatSendStatus" role="alert" hidden' in markup
    assert 'id="chatRetry" hidden>Réessayer</button>' in markup
    assert 'id="chatSend">Envoyer</button>' in markup
    assert 'id="chatTimeline">Voir la chronologie complète</button>' in markup
    # Every id the view looks up exists in the page.
    module = MODULE.read_text(encoding="utf-8")
    ids = re.search(r"const DOM=Object\.freeze\(\{(.*?)\}\);", module, re.S).group(1)
    for element_id in re.findall(r":'(chat\w+)'", ids):
        assert f'id="{element_id}"' in markup, element_id


def test_layout_rules_tab_bottom_right_toasts_above_it_one_panel_at_a_time():
    html = PAGE.read_text(encoding="utf-8")
    assert re.search(r"\.chat-tab\{position:absolute;z-index:32;right:18px;bottom:18px;width:52px;height:40px;", html)
    # Toasts: 18 px + tab (40 px) + 10 px; the open-panel offset still applies.
    assert ".toasts{position:fixed;right:18px;bottom:68px;" in html
    assert "#app:has(.panel.open)~.toasts{right:calc(98px + min(560px,100vw - 120px))" in html
    assert "@media(prefers-reduced-motion:reduce){.chat-panel.open," in html
    assert "async function openPanel(name){if(window.JarvisChat)window.JarvisChat.close();" in html
    assert "function closePanel(){if(window.JarvisChat)window.JarvisChat.close();" in html
    # The tab and the panel live in #app, so `#app:has(.panel.open)~.toasts` sees the Chat panel.
    app = html[html.index('<div id="app">'): html.index('<div class="ctxmenu"')]
    assert 'id="chatTab"' in app and 'id="chatPanel"' in app


def test_the_view_only_calls_chat_routes_and_never_the_agent_bridge():
    module = MODULE.read_text(encoding="utf-8")
    assert "/api/agent/ask" not in module and "/api/agent/send" not in module
    assert "/api/agent" not in module.replace("Les routes `/api/agent/*` contournent", "")
    routes = set(re.findall(r"'(/api/[A-Za-z0-9_/.-]+)'", module))
    assert routes == {"/api/chat/state", "/api/conversations/events", "/api/chat/turns", "/api/chat/voice/disable"}
    assert "projection=chat" in module and "wait_ms=" in module
    assert "LOCK_NAME='jarvis.chat.'" in module and "ifAvailable:true" in module


def test_no_event_content_reaches_html():
    module = MODULE.read_text(encoding="utf-8")
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "DOMParser", "createContextualFragment"):
        assert sink not in module, sink
    # Message text is a text node.
    assert "doc.createTextNode(item.text==null?'':String(item.text))" in module

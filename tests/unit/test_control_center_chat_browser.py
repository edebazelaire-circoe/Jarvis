"""Le Chat, mesuré dans un vrai Chrome sans tête (handoff jarvis-unified-chat-and-board-drop, Slice 06).

La page est celle que `ControlCenter.index` sert ; seul `fetch` est un double
(`_chat_browser.mjs`) : un faux Core en mémoire qui admet les tours, écrit les
événements canoniques et suit le canal vocal. Ce que ce fichier épingle, et
qu'aucune lecture de la page ne prouve : l'emplacement réel (rectangles,
`elementFromPoint`), le parcours au clavier avec de vraies touches, le verrou
vocal et la bascule, la primauté du serveur (409), le changement de Board, la
reprise avec le même `client_request_id`, l'écran étroit, le mouvement réduit,
une seule attente longue par profil et aucune lecture panneau fermé.

Captures (desktop, 480 px de haut, Board/Studio ouverts) : écrites dans
`JARVIS_S6_EVIDENCE_DIR` quand la variable est posée, sinon dans `tmp_path`.
Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.unit.test_interaction_mode_hud_browser import _chrome, _served_page

HARNESS = Path(__file__).parent / "_chat_browser.mjs"
READ = {"value": "r"}
OPEN = {"click": "#chatTab"}
SHOT_PREFIX = "2026-10-14-s06-"


def _shot(tmp_path: Path, name: str) -> dict:
    folder = Path(os.environ.get("JARVIS_S6_EVIDENCE_DIR") or tmp_path)
    folder.mkdir(parents=True, exist_ok=True)
    return {"shot": str(folder / f"{SHOT_PREFIX}{name}.png")}


def _drive(tmp_path: Path, actions: list, *, width: int = 1440, height: int = 900, setup: str = "",
           reduced_motion: bool = False, extra: Path | None = None) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    chrome = _chrome()
    page = _served_page(tmp_path)
    step = {"width": width, "height": height, "setup": setup, "reducedMotion": reduced_motion, "actions": actions}
    if extra is not None:
        step["extra"] = str(extra)
    done = subprocess.run([node, str(HARNESS), str(page), chrome, json.dumps(step)],
                          capture_output=True, text=True, encoding="utf-8", timeout=240, check=False)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert "failed" not in out["reads"], out["reads"].get("failed")
    assert out["errors"] == [], out["errors"]
    assert [line for line in out["console"] if line.startswith("error")] == [], out["console"]
    return out


def _overlap(a: dict | None, b: dict | None) -> bool:
    if not a or not b:
        return False
    return min(a["r"], b["r"]) > max(a["l"], b["l"]) and min(a["b"], b["b"]) > max(a["t"], b["t"])


def _until(js: str, ms: int = 5000, name: str | None = None) -> dict:
    return {"until": js, "ms": ms, "name": name or js}


BUBBLES = "document.querySelectorAll('#chatLog .chat-msg').length"
TOAST = {"eval": "toast({title:'Notification de test',sub:'au-dessus de l’onglet',ms:60000});1"}


def test_opens_bottom_right_no_overlap_with_dock_and_toasts(tmp_path):
    out = _drive(tmp_path, [
        TOAST, {"value": "closed"}, OPEN, _until(f"{BUBBLES}===4"), {"wait": 300}, READ, _shot(tmp_path, "desktop-1440x900"),
        {"click": ".dock button[data-panel=errors]"}, {"wait": 300}, {"value": "errors"},
        OPEN, {"wait": 300}, {"value": "back"},
    ])
    closed, r = out["reads"]["closed"], out["reads"]["r"]
    tab, dock = r["tab"], r["dock"]
    assert (tab["r"], tab["b"]) == (1440 - 18, 900 - 18), "fixed bottom right, right:18px bottom:18px"
    assert r["tabHit"] is True and not _overlap(tab, dock)
    # Toasts sit above the tab (18 + 40 + 10 px), panel closed; panel open, they move to its left.
    # Chat closed: toasts sit left of the dock column, bottom right — never over the tab, the dock (AGT) or the pills.
    assert not _overlap(closed["toasts"], tab) and not _overlap(closed["toasts"], dock) and not _overlap(closed["toast"], closed["agt"])
    assert r["open"] and r["expanded"] == "true" and r["panel"]["z"] == "33"
    assert not _overlap(r["panel"], tab) and not _overlap(r["panel"], dock) and not _overlap(r["toasts"], r["panel"])
    assert r["inputHit"] is True and r["active"] == "chatInput"
    # Hydrated from 0 with the chat projection, then ONE long-poll from the last cursor.
    calls = r["fake"]["calls"]
    assert "GET /api/conversations/events?conversation_id=conv-a&after_sequence=0&limit=500&projection=chat" in calls
    assert not any("wait_ms" in c for c in calls if "projection=chat" in c), "the Chat never holds a request open"
    assert not any("/api/agent/" in c for c in calls)
    # Bubbles by textContent: HTML-looking content stays text, line breaks are kept.
    assert [b["role"] for b in r["bubbles"]] == ["user", "brain", "user", "brain"]
    assert r["bubbles"][2]["text"] == "Montre <b>gras</b> & <img src=x onerror=alert(1)>" and r["bubbles"][2]["elements"] == 1
    assert r["bubbles"][3]["text"] == "Voici le plan :\n1. Lire\n2. Résumer"
    assert r["sub"] == "Board · Jarvis" and r["feed"] == "En direct"
    # One side panel at a time.
    errors, back = out["reads"]["errors"], out["reads"]["back"]
    assert errors["sideOpen"] and not errors["open"] and errors["expanded"] == "false"
    assert back["open"] and not back["sideOpen"]


def test_keyboard_enter_shift_enter_tab_order(tmp_path):
    out = _drive(tmp_path, [
        {"eval": "document.getElementById('chatTab').focus();1"}, {"key": "Enter"}, _until(f"{BUBBLES}===4"),
        {"value": "opened", "expr": "document.activeElement.id"},
        {"type": "Ligne 1"}, {"key": "Shift+Enter"}, {"type": "Ligne 2"}, {"value": "typed"},
        {"key": "Enter"}, _until(f"{BUBBLES}===6", name="answered"), {"value": "sent"},
        # Double send: a slow relay, Enter twice, then the button.
        {"eval": "window.__chat.turnPlan='slow';1"}, {"type": "Une seule fois"}, {"key": "Enter"}, {"key": "Enter"},
        {"click": "#chatSend"}, {"wait": 150}, {"value": "sending"}, _until(f"{BUBBLES}===8", name="once"),
        {"value": "double"},
        {"eval": "document.getElementById('chatClose').focus();1"},
        {"key": "Tab"}, {"value": "t1", "expr": "document.activeElement.id"},
        {"key": "Tab"}, {"value": "t2", "expr": "document.activeElement.id"},
        {"key": "Tab"}, {"value": "t3", "expr": "document.activeElement.id"},
        {"key": "Tab"}, {"value": "t4", "expr": "document.activeElement.id"},
        {"key": "Shift+Tab"}, {"value": "t5", "expr": "document.activeElement.id"},
        {"key": "Escape"}, {"wait": 100}, {"value": "escaped"},
    ])
    reads = out["reads"]
    assert reads["opened"] == "chatInput", "Enter on the tab opens the panel and puts the cursor in the composer"
    assert reads["typed"]["composer"]["value"] == "Ligne 1\nLigne 2" and reads["typed"]["fake"]["turns"] == []
    sent = reads["sent"]
    assert reads["until:answered"] is True
    assert sent["fake"]["turns"][0]["content"] == "Ligne 1\nLigne 2"
    assert sent["bubbles"][4] == {"role": "user", "text": "Ligne 1\nLigne 2", "who": "Vous", "elements": 1}
    assert sent["bubbles"][5]["text"] == "Réponse : Ligne 1\nLigne 2"
    assert sent["composer"]["value"] == "" and sent["active"] == "chatInput"
    sending = reads["sending"]
    assert sending["composer"]["readOnly"] is True and sending["composer"]["sendDisabled"] == "true"
    assert sending["composer"]["sendText"].startswith("Envoi…")
    assert reads["until:once"] is True
    assert [t["content"] for t in reads["double"]["fake"]["turns"]] == ["Ligne 1\nLigne 2", "Une seule fois"]
    # Slice 07b: « Joindre » sits between the composer and Envoyer.
    assert [reads[k] for k in ("t1", "t2", "t3", "t4", "t5")] == ["chatTimeline", "chatLog", "chatInput", "chatAttach", "chatInput"]
    escaped = reads["escaped"]
    assert escaped["open"] is False and escaped["active"] == "chatTab"


def test_pending_is_a_state_not_a_bubble_until_accepted(tmp_path):
    out = _drive(tmp_path, [
        {"eval": "window.__chat.acceptMs=1200;window.__chat.replyMs=null;1"}, OPEN, _until(f"{BUBBLES}===4"),
        {"type": "Tu es là ?"}, {"key": "Enter"}, {"wait": 400}, {"value": "before"},
        _until(f"{BUBBLES}===5", name="accepted"), {"wait": 200}, {"value": "after"},
    ])
    before, after = out["reads"]["before"], out["reads"]["after"]
    assert len(before["bubbles"]) == 4, "no final bubble before user.transcript.accepted"
    assert any(n.startswith("chat-note|") and "Message transmis" in n for n in before["notes"])
    assert before["composer"]["value"] == ""
    assert after["bubbles"][-1]["text"] == "Tu es là ?"
    assert any("Jarvis traite votre message" in n for n in after["notes"])


def test_locked_when_voice_active_and_explains(tmp_path):
    out = _drive(tmp_path, [
        OPEN, _until(f"{BUBBLES}===4"), {"type": "x"}, {"key": "Enter"}, {"wait": 300}, READ, _shot(tmp_path, "voice-locked"),
    ], setup="window.__chat.lockVoice('active','voice_active')")
    r = out["reads"]["r"]
    assert len(r["bubbles"]) == 4, "history stays readable"
    assert r["composer"]["ariaDisabled"] == "true" and r["composer"]["readOnly"] is True
    assert r["composer"]["disabled"] is False and r["active"] == "chatInput", "aria-disabled, not disabled: focus stays"
    assert r["composer"]["value"] == "" and r["fake"]["turns"] == []
    assert r["lock"]["hidden"] is False and "Désactivez le vocal pour écrire" in r["lock"]["text"]
    assert r["lock"]["switchHidden"] is False and r["lock"]["switchText"] == "Passer au chat"
    assert r["composer"]["sendDisabled"] == "true"


def test_switch_to_chat_unlocks_after_ack(tmp_path):
    out = _drive(tmp_path, [
        OPEN, _until(f"{BUBBLES}===4"), {"click": "#chatSwitch"}, {"wait": 250}, {"value": "switching"},
        _until("document.getElementById('chatInput').getAttribute('aria-disabled')==='false'", name="unlocked"),
        {"wait": 100}, READ,
    ], setup="window.__chat.lockVoice('active','voice_active')")
    switching, r = out["reads"]["switching"], out["reads"]["r"]
    assert switching["lock"]["text"] == "Arrêt du vocal…" and switching["lock"]["switchHidden"] is True
    assert switching["composer"]["ariaDisabled"] == "true"
    assert out["reads"]["until:unlocked"] is True
    assert r["lock"]["hidden"] is True and r["composer"]["readOnly"] is False and r["active"] == "chatInput"
    assert len(r["fake"]["disables"]) == 1 and len(r["fake"]["disables"][0]["client_request_id"]) == 36
    assert any("chat.voice_switched" in line for line in out["console"])


def test_switch_failure_stays_locked(tmp_path):
    out = _drive(tmp_path, [
        OPEN, _until(f"{BUBBLES}===4"), {"click": "#chatSwitch"},
        _until("document.getElementById('chatSwitch').textContent==='Réessayer'&&!document.getElementById('chatSwitch').hidden",
               name="failed"), READ,
    ], setup="window.__chat.lockVoice('active','voice_active');window.__chat.disablePlan='fail'")
    r = out["reads"]["r"]
    assert out["reads"]["until:failed"] is True
    assert r["composer"]["ariaDisabled"] == "true"
    assert "ne s’est pas arrêté (voice_disable_failed)" in r["lock"]["text"] and r["lock"]["tone"] == "bad"


def test_server_409_overrides_ui(tmp_path):
    out = _drive(tmp_path, [
        OPEN, _until(f"{BUBBLES}===4"), {"eval": "window.__chat.turnPlan='locked';1"},
        {"type": "Écrit pendant le réveil"}, {"key": "Enter"}, {"wait": 300}, {"value": "at_once"},
        {"wait": 1500}, READ,
    ])
    for r in (out["reads"]["at_once"], out["reads"]["r"]):
        assert r["composer"]["ariaDisabled"] == "true", "the server guard wins over the writable UI"
        assert "Désactivez le vocal pour écrire" in r["lock"]["text"]
        assert r["composer"]["value"] == "Écrit pendant le réveil", "nothing typed is lost"
        assert len(r["bubbles"]) == 4
    assert out["reads"]["at_once"]["snap"]["serverLock"]["reason"] == "voice_active"


def test_board_switch_rescopes(tmp_path):
    board = lambda b, c: {"eval": f"window.__chat.board('{b}','{c}');1"}  # noqa: E731
    value = "document.getElementById('chatInput').value"
    out = _drive(tmp_path, [
        OPEN, _until(f"{BUBBLES}===4"), {"type": "Brouillon pour Jarvis"}, board("board_b", "conv-b"),
        _until(f"{BUBBLES}===2", name="rescoped"), {"wait": 200}, READ,
        # A draft belongs to its conversation: back on A, it comes back; on B the field was empty.
        board("default", "conv-a"), _until(f"{BUBBLES}===4&&{value}==='Brouillon pour Jarvis'", name="draft_back"),
        {"eval": "document.getElementById('chatInput').select();1"}, {"type": "Pour Atlas"},
        # The server's not-foreground refusal re-reads the state; the text stays a draft of ITS Board.
        {"eval": "window.__chat.turnPlan='not_foreground';1"}, {"key": "Enter"},
        _until(f"{BUBBLES}===2", name="realigned"), {"wait": 200}, {"value": "realigned"},
        board("default", "conv-a"), _until(f"{value}==='Pour Atlas'", name="kept_on_a"),
    ])
    r, realigned = out["reads"]["r"], out["reads"]["realigned"]
    assert [b["text"] for b in r["bubbles"]] == ["Ouvre le Board Atlas", "Board Atlas ouvert."]
    assert r["snap"]["conversation_id"] == "conv-b" and r["composer"]["value"] == "", "Board A's text never shows on B"
    assert "GET /api/conversations/events?conversation_id=conv-b&after_sequence=0&limit=500&projection=chat" in r["fake"]["calls"]
    assert out["reads"]["until:draft_back"] is True
    assert out["reads"]["until:realigned"] is True
    assert realigned["snap"]["conversation_id"] == "conv-b" and realigned["composer"]["value"] == ""
    assert realigned["sendStatus"]["hidden"] is False and "Le Board affiché a changé" in realigned["sendStatus"]["text"]
    assert out["reads"]["until:kept_on_a"] is True
    assert [t["conversation_id"] for t in realigned["fake"]["turns"]] == ["conv-a"], "never sent to B"


def test_retry_reuses_client_request_id(tmp_path):
    out = _drive(tmp_path, [
        OPEN, _until(f"{BUBBLES}===4"), {"eval": "window.__chat.turnPlan='timeout_once';1"},
        {"type": "Rapport ?"}, {"key": "Enter"},
        _until("!document.getElementById('chatSendStatus').hidden", name="unknown"), {"value": "unknown"},
        {"click": "#chatRetry"}, _until(f"{BUBBLES}===6", name="answered"), {"wait": 300}, READ,
        {"type": "Autre message"}, {"key": "Enter"}, _until(f"{BUBBLES}===8", name="next"), {"value": "next"},
    ])
    unknown, r, nxt = out["reads"]["unknown"], out["reads"]["r"], out["reads"]["next"]
    assert "Jarvis Core ne répond pas (core_timeout)" in unknown["sendStatus"]["text"]
    assert "sans doublon" in unknown["sendStatus"]["text"] and unknown["sendStatus"]["retryHidden"] is False
    assert unknown["composer"]["value"] == "Rapport ?"
    first, second = r["fake"]["turns"]
    assert first["client_request_id"] == second["client_request_id"] and first["content"] == second["content"]
    assert [b["text"] for b in r["bubbles"]].count("Rapport ?") == 1, "the replay is a duplicate, not a second turn"
    assert r["sendStatus"]["hidden"] is True and r["composer"]["value"] == ""
    assert nxt["fake"]["turns"][2]["client_request_id"] != first["client_request_id"], "a new message, a new id"


@pytest.mark.parametrize("width,height,name", [(480, 800, "narrow-480w"), (1024, 480, "low-480h")])
def test_narrow_viewport_480px(tmp_path, width, height, name):
    out = _drive(tmp_path, [TOAST, OPEN, _until(f"{BUBBLES}===4"), {"wait": 300}, READ, _shot(tmp_path, f"{name}-{width}x{height}")],
                 width=width, height=height)
    r = out["reads"]["r"]
    tab, panel = r["tab"], r["panel"]
    for rect in (tab, panel, r["input"], r["send"]):
        assert rect["l"] >= 0 and rect["t"] >= 0 and rect["r"] <= width and rect["b"] <= height, rect
    assert r["tabHit"] is True and r["inputHit"] is True
    assert not _overlap(tab, panel) and not _overlap(tab, r["dock"])
    assert r["scrollWidth"] <= width
    assert r["input"]["h"] >= 40 and r["panel"]["h"] - r["input"]["h"] > 150, "the history keeps room"


def test_reduced_motion(tmp_path):
    pending = [OPEN, _until(f"{BUBBLES}===4"), {"eval": "window.__chat.replyMs=null;1"}, {"type": "Attente"},
               {"key": "Enter"}, _until(f"{BUBBLES}===5"), READ]
    normal = _drive(tmp_path, pending)["reads"]["r"]
    reduced = _drive(tmp_path, pending, reduced_motion=True)["reads"]["r"]
    assert normal["motion"] == {"panel": "chatIn", "dots": "chatDot"}
    assert reduced["motion"] == {"panel": "none", "dots": "none"}


def test_one_reader_per_profile_and_none_when_closed_or_hidden(tmp_path):
    hold = "navigator.locks.request('jarvis.chat.conv-a',()=>new Promise(r=>{window.__release=r}));1"
    count = "window.__chat.calls.filter(c=>c.includes('/api/chat/')||c.includes('/api/conversations/')).length"
    events = "window.__chat.calls.filter(c=>c.includes('/api/conversations/events')).length"
    out = _drive(tmp_path, [
        # Another holder of the lock: this tab is a follower and reads NO event (it waits for the leader's broadcast).
        {"eval": hold}, OPEN, {"wait": 2500}, {"value": "follower"}, {"value": "follower_events", "expr": events},
        {"eval": "window.__release();1"}, _until("window.JarvisChat.instance.snapshot().feed.role==='leader'", ms=7000, name="leader"),
        _until(f"{BUBBLES}===4", name="hydrated"),
        {"eval": "document.getElementById('chatClose').click();1"}, {"wait": 300},
        {"value": "closed_at", "expr": count}, {"wait": 3500}, {"value": "closed_after", "expr": count},
        OPEN, {"wait": 600},
        {"eval": "Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'));1"},
        {"wait": 300}, {"value": "hidden_at", "expr": count}, {"wait": 3500}, {"value": "hidden_after", "expr": count},
    ])
    reads = out["reads"]
    follower = reads["follower"]
    assert follower["snap"]["feed"]["role"] == "follower" and reads["follower_events"] == 0
    assert any("/api/chat/state" in c for c in follower["fake"]["calls"]), "the state stays a per-tab short read"
    assert reads["until:leader"] is True and reads["until:hydrated"] is True
    assert reads["closed_after"] == reads["closed_at"], "closed panel: no request at all"
    assert reads["hidden_after"] == reads["hidden_at"], "hidden tab: no request at all"


def test_cadence_short_reads_one_at_a_time(tmp_path):
    """1,5 s au repos, 0,5 s pendant 20 s après un envoi ; jamais deux requêtes du Chat en vol dans un onglet."""

    probe = ("(()=>{const C=window.__chat,f=window.fetch;C.inflight=0;C.maxInflight=0;C.times=[];"
             "window.fetch=async(p,i)=>{const chat=String(p).includes('/api/chat/state')||String(p).includes('projection=chat');"
             "if(chat){C.inflight++;C.maxInflight=Math.max(C.maxInflight,C.inflight);if(String(p).includes('/api/chat/state'))C.times.push(Date.now())}"
             "try{return await f(p,i)}finally{if(chat)C.inflight--}};return 1})()")
    gaps = "(()=>{const t=window.__chat.times.slice(-4);return t.slice(1).map((x,i)=>x-t[i])})()"
    out = _drive(tmp_path, [
        {"eval": probe}, OPEN, _until(f"{BUBBLES}===4"), {"wait": 5000}, {"value": "idle", "expr": gaps},
        {"type": "Vite"}, {"key": "Enter"}, {"wait": 2500}, {"value": "fast", "expr": gaps},
        {"value": "max", "expr": "window.__chat.maxInflight"},
    ])
    reads = out["reads"]
    assert all(1300 <= gap <= 2200 for gap in reads["idle"]), reads["idle"]
    assert all(gap <= 900 for gap in reads["fast"]), reads["fast"]
    assert reads["max"] == 1, "state and events reads are sequential"


def test_late_reply_note_after_the_configured_delay(tmp_path):
    out = _drive(tmp_path, [
        OPEN, _until(f"{BUBBLES}===4"), {"eval": "window.JarvisChat.config.replyDeadlineMs=1500;window.__chat.replyMs=null;1"},
        {"type": "Long travail"}, {"key": "Enter"}, _until(f"{BUBBLES}===5"),
        _until("!!document.querySelector('#chatLog .chat-note.late')", name="late"), READ,
    ])
    r = out["reads"]["r"]
    assert out["reads"]["until:late"] is True
    late = [n for n in r["notes"] if n.startswith("chat-note late|")]
    assert late == ["chat-note late|Toujours en cours, ou réponse non affichable ici —voir la chronologie complète"], r["notes"]
    assert len(r["bubbles"]) == 5, "never a fake reply"


def test_edited_text_after_unknown_outcome_is_a_new_message(tmp_path):
    out = _drive(tmp_path, [
        OPEN, _until(f"{BUBBLES}===4"), {"eval": "window.__chat.turnPlan='timeout_once';1"},
        {"type": "Rapport ?"}, {"key": "Enter"}, _until("!document.getElementById('chatSendStatus').hidden"),
        {"type": " complet"}, {"wait": 100}, {"value": "edited"},
        {"key": "Enter"}, _until(f"{BUBBLES}>=6", name="sent"), {"wait": 300}, READ,
    ])
    edited, r = out["reads"]["edited"], out["reads"]["r"]
    assert "sans doublon" not in edited["sendStatus"]["text"] and edited["sendStatus"]["retryHidden"] is True
    assert "NOUVEAU message" in edited["sendStatus"]["text"] and "peut-être déjà été reçu" in edited["sendStatus"]["text"]
    first, second = r["fake"]["turns"]
    assert second["content"] == "Rapport ? complet" and second["client_request_id"] != first["client_request_id"]


def test_core_side_failures_name_jarvis_core(tmp_path):
    out = _drive(tmp_path, [OPEN, {"wait": 2000}, READ], setup="window.__chat.stateError='core_unreachable'")
    r = out["reads"]["r"]
    assert r["lock"]["text"] == "Jarvis Core ne répond pas." and r["composer"]["ariaDisabled"] == "true"
    # No conversation known yet: no events read at all (never `conversation_id=null`).
    assert not any("/api/conversations/events" in c for c in r["fake"]["calls"]), r["fake"]["calls"]


def test_pills_tab_stays_whole_and_clickable_and_panel_spares_it(tmp_path):
    pills = "window.__chat.background={counts:{failed:1,attention:2,done:3,said:1},unread:7,seq:1,sources:{}}"
    out = _drive(tmp_path, [TOAST, {"wait": 1200}, {"value": "closed"}, OPEN, _until(f"{BUBBLES}===4"), {"wait": 300}, READ,
                            _shot(tmp_path, "pills-1440x900"), {"click": "#chatTab"}, {"wait": 200}, {"value": "toggled"}],
                 setup=pills)
    closed, r = out["reads"]["closed"], out["reads"]["r"]
    assert closed["pills"] is not None, "the pills are shown"
    for seen in (closed, r):
        tab = seen["tab"]
        assert seen["tabHit"] is True and tab["l"] >= 0 and tab["r"] <= 1440 and tab["b"] <= 900
        assert not _overlap(tab, seen["pills"]) and not _overlap(tab, seen["dock"])
    assert not _overlap(closed["toasts"], closed["pills"]) and not _overlap(closed["toast"], closed["agt"])
    assert not _overlap(r["panel"], r["tab"]), "the open panel never covers the tab"
    assert out["reads"]["toggled"]["open"] is False, "the tab still closes the panel by a real click"


@pytest.mark.parametrize("theme", ["default", "cosmos"])
def test_narrow_toasts_spare_the_panel_header_and_voice_hint_hides(tmp_path, theme):
    cosmos = [{"eval": "window.JarvisThemeAPI.activate('cosmos',{persist:false});1"}, {"wait": 600}] if theme == "cosmos" else []
    out = _drive(tmp_path, [*cosmos, OPEN, _until(f"{BUBBLES}===4"), TOAST, {"wait": 1500}, READ,
                            _shot(tmp_path, f"narrow-toast-{theme}-600x800")], width=600, height=800)
    r = out["reads"]["r"]
    assert r["toast"] is not None
    assert not _overlap(r["toast"], r["head"]) and not _overlap(r["toast"], r["close"]) and r["closeHit"] is True
    assert not _overlap(r["toast"], r["input"]) and r["inputHit"] is True
    assert r["voicehint"] == "hidden"


def test_board_and_studio_open_alongside(tmp_path):
    """Évidence : panneau Boards ouvert au-dessus du Chat ; l'inspecteur du Studio, s'il s'ouvre, ferme le Chat."""

    out = _drive(tmp_path, [
        OPEN, _until(f"{BUBBLES}===4"), {"eval": "document.getElementById('boardsButton').click();1"}, {"wait": 500}, READ, _shot(tmp_path, "board-panel-open"),
        {"eval": "document.getElementById('boardsButton').click();1"}, {"wait": 200},
        {"value": "studio_opened", "expr": "!!(window.JarvisStudioInspector&&window.JarvisStudioInspector.instance&&window.JarvisStudioInspector.instance.open())"},
        {"wait": 400}, {"value": "studio"}, _shot(tmp_path, "studio-inspector-open"),
    ])
    r, studio = out["reads"]["r"], out["reads"]["studio"]
    assert r["open"] and r["boardsPanel"] is not None and int(r["boardsPanel"]["z"]) > int(r["panel"]["z"])
    if out["reads"]["studio_opened"]:
        assert studio["open"] is False, "one side panel at a time"


@pytest.mark.parametrize("width,height", [(1440, 900), (600, 800)])
def test_cosmos_theme_keeps_tab_panel_and_dock_apart(tmp_path, width, height):
    cosmos = {"eval": "window.JarvisThemeAPI.activate('cosmos',{persist:false});1"}
    out = _drive(tmp_path, [cosmos, {"wait": 600}, OPEN, _until(f"{BUBBLES}===4"), {"wait": 300}, READ,
                            _shot(tmp_path, f"cosmos-{width}x{height}")], width=width, height=height)
    r = out["reads"]["r"]
    assert not _overlap(r["panel"], r["tab"]) and not _overlap(r["tab"], r["dock"]) and not _overlap(r["panel"], r["dock"])
    assert r["tabHit"] is True and r["inputHit"] is True
    assert r["panel"]["b"] <= r["tab"]["t"] - 10 + 0.5


# ---------- Polish QA S06, réglé en Slice 07b ----------

def test_core_hang_blames_core_not_the_control_center(tmp_path):
    """(a) Le relais rend 504 `core_timeout` à 10 s ; la lecture d'état l'attend (13 s) au lieu de couper à 8 s
    et d'accuser le Control Center. Pendant l'attente, la ligne d'état le dit, avec son compteur."""

    hang = ("(()=>{const C=window.__chat,f=window.fetch;window.fetch=async(p,i)=>{"
            "if(C.hang&&String(p)==='/api/chat/state'){await new Promise(r=>setTimeout(r,10200));"
            "return new Response(JSON.stringify({ok:false,code:'core_timeout',error:'',core_status:null}),{status:504})}"
            "return f(p,i)};return 1})()")
    out = _drive(tmp_path, [
        {"eval": hang}, OPEN, _until(f"{BUBBLES}===4"), {"eval": "window.__chat.hang=true;1"}, {"wait": 6000},
        {"value": "waiting"}, _until("document.getElementById('chatLockText').textContent!==''", ms=12000, name="locked"),
        READ,
    ])
    waiting, r = out["reads"]["waiting"], out["reads"]["r"]
    assert waiting["feed"] == "Jarvis tarde à répondre · lecture de l’état", waiting["feed"]
    assert out["reads"]["until:locked"] is True
    assert r["lock"]["text"] == "Jarvis Core ne répond pas.", r["lock"]["text"]
    assert r["snap"]["state"] is not None and r["snap"]["view"]["locked"] is True


def test_retry_in_flight_never_sticks_at_zero(tmp_path):
    """(b) Échéance de reprise passée et requête en file : « nouvel essai en cours » et un compteur qui monte."""

    fail = ("(()=>{const C=window.__chat,f=window.fetch;window.fetch=async(p,i)=>{const u=String(p);"
            "if(C.failEvents&&u.includes('/api/conversations/events'))return new Response(JSON.stringify({ok:false,code:'core_unreachable',error:''}),{status:503});"
            "if(C.queue&&u==='/api/chat/state')await new Promise(r=>setTimeout(r,C.queue));"
            "return f(p,i)};return 1})()")
    texts = "(()=>{const t=document.getElementById('chatFeedText').textContent,c=document.getElementById('chatFeedTime').textContent;return t+'|'+c})()"
    out = _drive(tmp_path, [
        {"eval": fail}, OPEN, _until(f"{BUBBLES}===4"), {"eval": "window.__chat.failEvents=true;1"},
        _until("document.getElementById('chatFeedText').textContent.startsWith('Lecture interrompue')", name="failing"),
        # The next read waits 4 s in the "browser queue" (the state read ahead of it).
        {"eval": "window.__chat.queue=4000;1"}, {"wait": 3500}, {"value": "a", "expr": texts}, {"wait": 1500}, {"value": "b", "expr": texts},
    ])
    a, b = out["reads"]["a"], out["reads"]["b"]
    for seen in (a, b):
        assert "dans 0 s" not in seen, seen
    in_flight = [x for x in (a, b) if "nouvel essai en cours" in x]
    assert in_flight, (a, b)
    secs = [int(x.split("|")[1].split(" ")[0]) for x in in_flight]
    assert len(secs) < 2 or secs[1] > secs[0], "the counter moves"


def test_one_coherent_status_never_live_beside_the_lock(tmp_path):
    """(c) État illisible : la ligne d'état ne dit plus « En direct » à côté du verrou « ne répond pas »."""

    out = _drive(tmp_path, [
        OPEN, _until(f"{BUBBLES}===4"), {"value": "live"}, {"eval": "window.__chat.stateError='core_unreachable';1"},
        _until("!document.getElementById('chatLock').hidden", name="locked"), {"wait": 1200}, READ,
        {"eval": "window.__chat.stateError=null;1"}, _until("document.getElementById('chatFeedText').textContent==='En direct'", name="back"),
    ])
    live, r = out["reads"]["live"], out["reads"]["r"]
    assert live["feed"] == "En direct"
    assert r["lock"]["text"] == "Jarvis Core ne répond pas."
    assert r["feed"].startswith("Connexion interrompue · Jarvis Core ne répond pas · nouvel essai"), r["feed"]
    assert out["reads"]["until:back"] is True


def test_follower_rows_stay_bounded_after_many_hellos(tmp_path):
    """(d) Un suiveur qui reçoit l'historique plusieurs fois (un `rows` par `hello` de chaque onglet) ne garde
    qu'une ligne par événement : pas de doublon, mémoire bornée."""

    hold = "navigator.locks.request('jarvis.chat.conv-a',()=>new Promise(r=>{window.__release=r}));1"
    # A fake leader in the same page: answers every hello with the whole history, and replays it 6 more times.
    leader = ("(()=>{const ch=new BroadcastChannel('jarvis.chat.conv-a');const rows=()=>window.__chat.rows.filter(r=>r.event.conversation_id==='conv-a');"
              "window.__hellos=0;ch.onmessage=e=>{if(e.data&&e.data.type==='hello'){window.__hellos++;"
              "ch.postMessage({type:'rows',rows:rows(),cursor:window.__chat.seq})}};"
              "window.__replay=()=>{for(let i=0;i<6;i++)ch.postMessage({type:'rows',rows:rows(),cursor:window.__chat.seq})};return 1})()")
    out = _drive(tmp_path, [
        {"eval": hold}, {"eval": leader}, OPEN, _until(f"{BUBBLES}===4", name="hydrated"),
        {"value": "first", "expr": "window.JarvisChat.instance.snapshot().feed"},
        {"eval": "window.__replay();1"}, {"wait": 800}, READ,
    ])
    first, r = out["reads"]["first"], out["reads"]["r"]
    assert first["role"] == "follower" and first["heldRows"] == 4
    assert r["snap"]["feed"]["heldRows"] == 4, "six more copies of the history: still one row per event"
    assert len(r["bubbles"]) == 4


def test_low_viewport_toast_spares_the_panel_and_its_hint(tmp_path):
    """(e) 1024×480 : la notification ne mord plus sur le panneau ni sur l'indice « Entrée »."""

    hint = "(()=>{const r=document.getElementById('chatHint').getBoundingClientRect();return {l:r.left,t:r.top,r:r.right,b:r.bottom}})()"
    out = _drive(tmp_path, [TOAST, OPEN, _until(f"{BUBBLES}===4"), {"wait": 300}, READ, {"value": "hint", "expr": hint},
                            _shot(tmp_path, "low-480h-toast-1024x480")], width=1024, height=480)
    r = out["reads"]["r"]
    assert r["toast"] is not None
    assert not _overlap(r["toast"], r["panel"]), (r["toast"], r["panel"])
    assert not _overlap(r["toast"], out["reads"]["hint"])
    assert r["toast"]["l"] >= 0

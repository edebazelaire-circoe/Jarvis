"""Pièces jointes du Chat, mesurées dans un vrai Chrome sans tête (handoff jarvis-unified-chat-and-board-drop, Slice 07b).

La page est celle que `ControlCenter.index` sert. Doubles : le faux Core de
`_chat_browser.mjs` (`fetch`) et le faux relais de pièces jointes de
`_chat_attachments_browser.mjs` (`XMLHttpRequest`, la seule route
`POST /api/chat/uploads`). Les fichiers sont de VRAIS fichiers sur disque,
posés par CDP : `DOM.setFileInputFiles` (bouton « Joindre »), le sélecteur
natif intercepté (`Page.fileChooserOpened`, clavier) et un vrai
glisser-déposer `Input.dispatchDragEvent`.

Les douze cas du contrat (`slices/07b-chat-attachments-ui/SLICE.md` › *Contrat
Slice 00*), chacun nommé comme lui. Contrat : `docs/chat.md` › *Attachments*
(UI). Captures dans `JARVIS_S7B_EVIDENCE_DIR` quand la variable est posée.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.unit.test_control_center_chat_browser import BUBBLES, OPEN, READ, _drive, _until

EXTRA = Path(__file__).parent / "_chat_attachments_browser.mjs"
SHOT_PREFIX = "2026-10-15-s7b-"
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x35\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82")
FILES = "document.querySelectorAll('#chatFiles .chat-file')"
READY = f"[...{FILES}].filter(li=>li.dataset.status==='ready'||li.dataset.status==='unreadable').length"
SNAP = "window.JarvisChat.instance.snapshot()"


def _files(tmp_path: Path) -> dict[str, str]:
    folder = tmp_path / "files"
    folder.mkdir(exist_ok=True)
    data = {
        "photo.png": PNG,
        "notes.txt": "Ordre du jour\n1. Budget\n".encode("utf-8"),
        "archive.zip": b"PK\x03\x04" + bytes(range(256)) * 4,
        "rapport.pdf": b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n",
        "film.mov": b"\x00\x00\x00\x14ftypqt  " + bytes(2048),
    }
    out = {}
    for name, body in data.items():
        (folder / name).write_bytes(body)
        out[name] = str(folder / name)
    return out


def _shot(tmp_path: Path, name: str) -> dict:
    folder = Path(os.environ.get("JARVIS_S7B_EVIDENCE_DIR") or tmp_path)
    folder.mkdir(parents=True, exist_ok=True)
    return {"shot": str(folder / f"{SHOT_PREFIX}{name}.png")}


def _run(tmp_path: Path, actions: list, **options) -> dict:
    return _drive(tmp_path, actions, extra=EXTRA, **options)


def _ids(read: dict) -> list[str]:
    return [u["id"] for u in read["uploads"]]


UPLOADS = {"value": "uploads", "expr": "window.__chat.uploads.slice()"}


def test_select_two_files_then_send(tmp_path):
    f = _files(tmp_path)
    out = _run(tmp_path, [
        OPEN, _until(f"{BUBBLES}===4"),
        {"files": "#chatFile", "paths": [f["photo.png"], f["notes.txt"]]}, {"wait": 60}, {"value": "uploading"},
        _until(f"{READY}===2", name="ready"), {"value": "ready"}, _shot(tmp_path, "two-ready-1440x900"),
        {"type": "Voici les deux fichiers"}, {"key": "Enter"},
        _until(f"{BUBBLES}===6", name="answered"), {"wait": 200}, READ, UPLOADS, _shot(tmp_path, "sent-1440x900"),
    ])
    reads = out["reads"]
    uploading = reads["uploading"]
    assert [x["status"] for x in uploading["files"]] == ["uploading", "uploading"]
    assert uploading["files"][0]["state"].startswith("Envoi ") and uploading["composer"]["sendDisabled"] == "true"
    assert reads["until:ready"] is True
    ready = reads["ready"]
    assert [(x["name"], x["status"], x["state"]) for x in ready["files"]] == [
        ("photo.png", "ready", "Prête"), ("notes.txt", "ready", "Prête")]
    assert ready["attNote"] == "Ajoutez un message pour accompagner les fichiers."
    # One request per file, multipart client_upload_id THEN file, a UUID v4 each.
    uploads = reads["uploads"]
    assert [u["name"] for u in uploads] == ["photo.png", "notes.txt"]
    assert all(u["order"] == ["client_upload_id", "file"] and len(u["id"]) == 36 and u["id"][14] == "4" for u in uploads)
    r = reads["r"]
    turn = r["fake"]["turns"][-1]
    assert turn["content"] == "Voici les deux fichiers"
    assert turn["attachments"] == ["jart_up_" + u["id"].replace("-", "")[:40] for u in uploads]
    # The user bubble: the count from attributes.attachment_count, names from the local state of the sent message.
    assert r["bubbles"][4]["text"] == "Voici les deux fichiers"
    assert r["attLines"] == ["2 pièces jointesphoto.png · notes.txt"]
    assert r["files"] == [] and r["composer"]["value"] == "", "sent attachments leave the composer"
    assert not any("photo.png" in line or "notes.txt" in line for line in out["console"]), "no file name in the journal"


def test_drop_two_files_on_panel(tmp_path):
    """Acceptation : un fichier SÉLECTIONNÉ et deux DÉPOSÉS, de types différents, partent dans un même message."""

    f = _files(tmp_path)
    out = _run(tmp_path, [
        OPEN, _until(f"{BUBBLES}===4"),
        {"files": "#chatFile", "paths": [f["rapport.pdf"]]},
        {"drop": "#chatLog", "paths": [f["photo.png"], f["notes.txt"]]}, {"wait": 60}, {"value": "dropped"},
        _until(f"{READY}===3", name="ready"), {"type": "Trois pièces"}, {"key": "Enter"},
        _until(f"{BUBBLES}===6", name="answered"), {"wait": 200}, READ, UPLOADS,
    ])
    reads = out["reads"]
    assert [x["name"] for x in reads["dropped"]["files"]] == ["rapport.pdf", "photo.png", "notes.txt"]
    assert reads["dropped"]["drop"] is False, "the drop overlay goes away after the drop"
    assert reads["until:ready"] is True
    turn = reads["r"]["fake"]["turns"][-1]
    assert len(turn["attachments"]) == 3 and len(set(turn["attachments"])) == 3
    assert sorted(u["type"] for u in reads["uploads"]) == ["application/pdf", "image/png", "text/plain"]
    assert reads["r"]["attLines"][-1].startswith("3 pièces jointes")
    assert any("chat.attached" in line and '"via":"drop"' in line for line in out["console"])


def test_drop_outside_panel_ignored(tmp_path):
    f = _files(tmp_path)
    # Seen from `window` (after every page listener): was the browser's default — open the file — cancelled?
    probe = ("window.__dz=[];for(const t of ['dragover','drop'])window.addEventListener(t,e=>window.__dz.push("
             "[t,e.defaultPrevented,e.dataTransfer.dropEffect]));1")
    out = _run(tmp_path, [
        {"eval": probe}, OPEN, _until(f"{BUBBLES}===4"), {"value": "before", "expr": "location.href"},
        {"drop": "#chatTab", "paths": [f["photo.png"]]}, {"wait": 300},
        {"drop": ".dock", "paths": [f["notes.txt"]]}, {"wait": 300},
        {"value": "after", "expr": "location.href"}, {"value": "events", "expr": "window.__dz"}, READ, UPLOADS,
    ])
    reads = out["reads"]
    assert reads["after"] == reads["before"]
    assert reads["uploads"] == [] and reads["r"]["files"] == [], "a file dropped elsewhere does nothing"
    over = [e for e in reads["events"] if e[0] == "dragover"]
    assert over and all(e[1] is True and e[2] == "none" for e in over), "default cancelled, the drop is refused"
    assert [e for e in reads["events"] if e[0] == "drop" and e[1] is not True] == [], "never opened by the browser"


def test_unreadable_format_announced(tmp_path):
    f = _files(tmp_path)
    out = _run(tmp_path, [
        OPEN, _until(f"{BUBBLES}===4"), {"files": "#chatFile", "paths": [f["archive.zip"], f["photo.png"]]},
        _until(f"{READY}===2", name="ready"), {"wait": 100}, READ, _shot(tmp_path, "unreadable-1440x900"),
        {"type": "Analyse"}, {"key": "Enter"}, _until(f"{BUBBLES}===6", name="sent"), {"wait": 200}, {"value": "sent"},
    ])
    r = out["reads"]["r"]
    zip_row = r["files"][0]
    assert zip_row["status"] == "unreadable"
    assert zip_row["state"] == "Prête · jointe, mais le Brain ne pourra pas la lire", "said BEFORE sending"
    assert r["files"][1]["status"] == "ready"
    sent = out["reads"]["sent"]
    assert len(sent["fake"]["turns"][-1]["attachments"]) == 2, "stored and sent, never dropped silently"
    assert "archive.zip (non lisible par le Brain)" in sent["attLines"][-1]


def test_too_large_shows_limit(tmp_path):
    f = _files(tmp_path)
    out = _run(tmp_path, [
        {"eval": "window.__chat.uploadPlans['film.mov']='big';1"}, OPEN, _until(f"{BUBBLES}===4"),
        {"files": "#chatFile", "paths": [f["film.mov"]]},
        _until(f"{FILES}[0]&&{FILES}[0].dataset.status==='failed'", name="failed"), READ, _shot(tmp_path, "too-large-1440x900"),
        {"type": "Le film"}, {"key": "Enter"}, {"wait": 300}, {"value": "held"},
    ])
    r, held = out["reads"]["r"], out["reads"]["held"]
    row = r["files"][0]
    assert row["state"] == "Trop volumineux : 1 Mo au plus par fichier.", "the bound Core states"
    assert row["act"] is None, "retrying the same file would be refused the same way"
    assert r["attNote"] == "Une pièce est en échec : réessayez-la ou retirez-la avant d’envoyer."
    assert held["fake"]["turns"] == [], "no silent loss: the message waits until the failed file is handled"
    assert any("chat.upload_failed" in line and "upload_too_large" in line for line in out["console"])


def test_retry_reuses_client_upload_id(tmp_path):
    """Issue inconnue → même id (Core rejoue, aucun doublon) ; échec connu → nouvel id ;
    reprise au même id qui apprend l'échec (409 `upload_conflict`) → nouvel id, aussitôt, une fois."""

    f = _files(tmp_path)
    failed = lambda i: f"{FILES}[{i}]&&{FILES}[{i}].dataset.status==='failed'"  # noqa: E731
    out = _run(tmp_path, [
        {"eval": "Object.assign(window.__chat.uploadPlans,{'photo.png':'network_once','notes.txt':'incomplete',"
                 "'rapport.pdf':'timeout_then_failed'});1"},
        OPEN, _until(f"{BUBBLES}===4"),
        {"files": "#chatFile", "paths": [f["photo.png"], f["notes.txt"], f["rapport.pdf"]]},
        _until(f"{failed(0)}&&{failed(1)}&&{failed(2)}", name="failed"), READ, _shot(tmp_path, "retry-1440x900"),
        {"eval": "window.__chat.uploadPlans['notes.txt']=null;1"},
        {"click": "#chatFiles .chat-file:nth-child(1) .chat-file-act"},
        {"click": "#chatFiles .chat-file:nth-child(2) .chat-file-act"},
        {"click": "#chatFiles .chat-file:nth-child(3) .chat-file-act"},
        _until(f"{READY}===3", ms=8000, name="ready"), UPLOADS, {"value": "ready"},
    ])
    reads = out["reads"]
    states = [x["state"] for x in reads["r"]["files"]]
    assert states[0].startswith("Control Center injoignable.") and "sans doublon" in states[0]
    assert states[1] == "Envoi coupé avant la fin." and "sans doublon" not in states[1]
    assert states[2].startswith("Jarvis Core ne répond pas.") and "sans doublon" in states[2]
    assert all(x["act"] == "Réessayer" for x in reads["r"]["files"])
    assert reads["until:ready"] is True
    by_name: dict[str, list] = {}
    for u in reads["uploads"]:
        by_name.setdefault(u["name"], []).append(u)
    photo, notes, pdf = by_name["photo.png"], by_name["notes.txt"], by_name["rapport.pdf"]
    # Unknown outcome: the same id, and Core's replay is the same Artifact (no duplicate).
    assert [u["id"] for u in photo] == [photo[0]["id"]] * 2 and [u["outcome"] for u in photo] == ["lost", "replayed"]
    # Known failure: a NEW id (the failed row answers 409 to the old one).
    assert len(notes) == 2 and notes[0]["id"] != notes[1]["id"] and notes[1]["outcome"] == "created"
    # Unknown outcome that had failed in Core: same id → 409 upload_conflict → new id at once.
    assert [u["outcome"] for u in pdf] == ["core_timeout", "upload_conflict", "created"]
    assert pdf[0]["id"] == pdf[1]["id"] != pdf[2]["id"]
    ids = reads["ready"]["snap"]["attachments"]["ids"]
    assert len(ids) == len(set(ids)) == 3


def test_remove_before_send(tmp_path):
    f = _files(tmp_path)
    out = _run(tmp_path, [
        {"eval": "window.__chat.uploadPlans['rapport.pdf']='hang';1"}, OPEN, _until(f"{BUBBLES}===4"),
        {"files": "#chatFile", "paths": [f["photo.png"], f["notes.txt"], f["rapport.pdf"]]},
        _until(f"{READY}===2", name="two"), {"value": "before"},
        {"click": "#chatFiles .chat-file:nth-child(3) .chat-file-x"},
        {"click": "#chatFiles .chat-file:nth-child(1) .chat-file-x"}, {"wait": 100}, {"value": "removed"},
        {"type": "Seulement les notes"}, {"key": "Enter"}, _until(f"{BUBBLES}===6", name="sent"), {"wait": 200}, READ, UPLOADS,
    ])
    reads = out["reads"]
    assert reads["before"]["files"][2]["status"] == "uploading"
    assert [x["name"] for x in reads["removed"]["files"]] == ["notes.txt"]
    assert reads["removed"]["active"] == "chatInput", "focus goes back to the composer"
    uploads = reads["uploads"]
    assert [u["outcome"] for u in uploads if u["name"] == "rapport.pdf"] == ["aborted"], "an upload in flight is cancelled"
    notes_id = next(u["id"] for u in uploads if u["name"] == "notes.txt")
    assert reads["r"]["fake"]["turns"][-1]["attachments"] == ["jart_up_" + notes_id.replace("-", "")[:40]]
    assert reads["r"]["attLines"][-1] == "1 pièce jointenotes.txt"


def test_send_blocked_while_uploading(tmp_path):
    f = _files(tmp_path)
    out = _run(tmp_path, [
        {"eval": "window.__chat.uploadPlans['photo.png']='slow';1"}, OPEN, _until(f"{BUBBLES}===4"),
        {"files": "#chatFile", "paths": [f["photo.png"]]}, {"type": "Avec la photo"}, {"wait": 1300},
        {"key": "Enter"}, {"click": "#chatSend"}, {"wait": 150}, {"value": "held"}, _shot(tmp_path, "uploading-1440x900"),
        _until(f"{READY}===1", ms=6000, name="ready"), {"key": "Enter"}, _until(f"{BUBBLES}===6", name="sent"), READ,
    ])
    held, r = out["reads"]["held"], out["reads"]["r"]
    assert held["fake"]["turns"] == [] and held["composer"]["value"] == "Avec la photo"
    assert held["composer"]["sendDisabled"] == "true"
    assert held["attNote"] == "Envoi possible dès que la pièce est prête."
    row = held["files"][0]
    assert row["status"] == "uploading" and row["state"].startswith("Envoi ") and row["time"].endswith(" s"), "motion + counter"
    assert out["reads"]["until:ready"] is True
    assert len(r["fake"]["turns"]) == 1 and len(r["fake"]["turns"][0]["attachments"]) == 1


def test_text_required_with_files(tmp_path):
    f = _files(tmp_path)
    out = _run(tmp_path, [
        OPEN, _until(f"{BUBBLES}===4"), {"files": "#chatFile", "paths": [f["notes.txt"]]},
        _until(f"{READY}===1", name="ready"), {"eval": "document.getElementById('chatInput').focus();1"},
        {"key": "Enter"}, {"click": "#chatSend"}, {"wait": 200}, READ, _shot(tmp_path, "text-required-1440x900"),
    ])
    r = out["reads"]["r"]
    assert r["fake"]["turns"] == [], "no file-only message"
    assert r["attNote"] == "Ajoutez un message pour accompagner les fichiers."
    assert r["snap"]["attachments"]["ids"] and r["files"][0]["status"] == "ready", "the file stays attached"
    assert any("chat.turn_held" in line and "text_required" in line for line in out["console"])


def test_board_switch_marks_pending_attachments(tmp_path):
    f = _files(tmp_path)
    board = lambda b, c: {"eval": f"window.__chat.board('{b}','{c}');1"}  # noqa: E731
    out = _run(tmp_path, [
        OPEN, _until(f"{BUBBLES}===4"), {"files": "#chatFile", "paths": [f["photo.png"]]}, _until(f"{READY}===1", name="ready"),
        board("board_b", "conv-b"), _until(f"{BUBBLES}===2", name="rescoped"), {"wait": 200}, {"value": "on_b"},
        _shot(tmp_path, "board-switch-1440x900"),
        {"type": "Sur Atlas"}, {"key": "Enter"}, _until(f"{BUBBLES}===4", name="sent_b"), {"value": "sent_b"},
        board("default", "conv-a"), _until(f"{BUBBLES}===4&&{READY}===1", name="back"), {"value": "back"},
        board("board_b", "conv-b"),
        _until(f"{SNAP}.conversation_id==='conv-b'&&{FILES}[0].dataset.status==='stale'", name="b_again"),
        {"click": "#chatFiles .chat-file:nth-child(1) .chat-file-act"}, _until(f"{READY}===1", name="rebound"),
        {"value": "rebound"}, UPLOADS,
    ])
    reads = out["reads"]
    on_b = reads["on_b"]
    assert [(x["status"], x["act"]) for x in on_b["files"]] == [("stale", "Renvoyer ici")]
    assert on_b["files"][0]["state"].startswith("À renvoyer")
    assert reads["sent_b"]["fake"]["turns"][-1] == {"conversation_id": "conv-b", "client_request_id":
                                                    reads["sent_b"]["fake"]["turns"][-1]["client_request_id"],
                                                    "content": "Sur Atlas"}, "never sent silently to the new conversation"
    assert reads["back"]["files"][0]["status"] == "ready", "back on its Board, the file is ready again"
    first, again = reads["uploads"][0]["id"], reads["uploads"][-1]["id"]
    assert len(reads["uploads"]) == 2 and first != again, "« Renvoyer ici » uploads into the new context with a new id"
    assert reads["rebound"]["snap"]["attachments"]["items"][0]["cid"] == "conv-b"


def test_voice_lock_blocks_send_not_preparation(tmp_path):
    f = _files(tmp_path)
    out = _run(tmp_path, [
        OPEN, _until(f"{BUBBLES}===4"), {"files": "#chatFile", "paths": [f["notes.txt"]]},
        _until(f"{READY}===1", name="ready"), {"eval": "document.getElementById('chatSend').click();1"},
        {"wait": 300}, READ, _shot(tmp_path, "voice-locked-1440x900"),
    ], setup="window.__chat.lockVoice('active','voice_active')")
    r = out["reads"]["r"]
    assert out["reads"]["until:ready"] is True, "preparing is allowed while the voice holds the conversation"
    assert r["attach"]["ariaDisabled"] == "false"
    assert r["composer"]["ariaDisabled"] == "true" and "Désactivez le vocal pour écrire" in r["lock"]["text"]
    assert r["fake"]["turns"] == [], "sending is refused while chat_writable is false"


def test_keyboard_accessible_attach_button(tmp_path):
    f = _files(tmp_path)
    out = _run(tmp_path, [
        OPEN, _until(f"{BUBBLES}===4"), {"eval": "document.getElementById('chatInput').focus();1"},
        {"key": "Tab"}, {"value": "focused", "expr": "document.activeElement.id"},
        {"value": "label", "expr": "(()=>{const b=document.activeElement;return [b.tagName,b.type,b.textContent,b.title]})()"},
        {"key": "Enter"}, {"wait": 300}, {"value": "chooser_after_enter", "expr": "1"},
        {"chooserFiles": [f["notes.txt"]]}, _until(f"{READY}===1", name="ready"),
        {"key": "Space"}, {"wait": 300}, {"chooserFiles": [f["photo.png"]]}, _until(f"{READY}===2", name="ready2"),
        {"key": "Tab"}, {"value": "next", "expr": "document.activeElement.id"},
        {"eval": "document.querySelector('#chatFiles .chat-file-x').focus();1"},
        {"value": "remove_label", "expr": "document.activeElement.getAttribute('aria-label')"},
        {"key": "Enter"}, {"wait": 150}, READ,
    ])
    reads = out["reads"]
    assert reads["focused"] == "chatAttach"
    assert reads["label"][:3] == ["BUTTON", "button", "Joindre"] and "déposer" in reads["label"][3]
    assert reads["choosers"] == 2, "Enter and Space on « Joindre » open the native file chooser"
    assert reads["until:ready"] is True and reads["until:ready2"] is True
    assert reads["next"] == "chatSend"
    assert reads["remove_label"] == "Retirer notes.txt"
    assert [x["name"] for x in reads["r"]["files"]] == ["photo.png"] and reads["r"]["active"] == "chatInput"


# ---------- Rework QA S7b ----------

BOARD = lambda b, c: {"eval": f"window.__chat.board('{b}','{c}');1"}  # noqa: E731
QUICK = {"eval": "window.JarvisChat.config.tickMs=250;1"}
DRAFT_A = {"value": "draft_a", "expr": "localStorage.getItem('jarvis.chat.draft.conv-a')"}
INTERRUPTED = "Envoi interrompu par le rechargement de la page : joignez le fichier à nouveau."


@pytest.mark.parametrize("finish_on", ["b", "a"])
def test_board_round_trip_keeps_the_live_upload(tmp_path, finish_on):
    """QA S7b BLOCKING 1 : un aller-retour de Board n'est pas un rechargement. Envoi lent sur A, passage sur B,
    retour sur A — que l'envoi ait fini sur B ou soit encore en cours au retour : UNE ligne, l'état vivant,
    et l'envoi part ensuite. Jamais « interrompu par le rechargement » sans rechargement."""

    f = _files(tmp_path)
    slow = 2500 if finish_on == "b" else 6000
    finished = f"{SNAP}.attachments.items.length===1&&{SNAP}.attachments.items[0].state==='ready'"
    back = _until(f"{SNAP}.conversation_id==='conv-a'&&{BUBBLES}===4&&{FILES}.length>=1", name="back")
    wait_b = [_until(finished, ms=8000, name="finished_on_b")] if finish_on == "b" else [{"wait": 200}]
    out = _run(tmp_path, [
        QUICK, {"eval": f"window.__chat.slowMs={slow};window.__chat.uploadPlans['photo.png']='slow';1"},
        OPEN, _until(f"{BUBBLES}===4"), {"files": "#chatFile", "paths": [f["photo.png"]]}, {"wait": 300},
        BOARD("board_b", "conv-b"), _until(f"{SNAP}.conversation_id==='conv-b'&&{BUBBLES}===2", name="on_b"),
        *wait_b, {"value": "on_b"},
        BOARD("default", "conv-a"), back, {"wait": 700}, {"value": "back_a"},
        _shot(tmp_path, f"board-round-trip-{finish_on}-1440x900"),
        _until(f"{READY}===1", ms=8000, name="ready"), {"wait": 300}, {"value": "ready_a"}, DRAFT_A,
        {"type": "Après le retour"}, {"key": "Enter"}, _until(f"{BUBBLES}===6", name="sent"), {"wait": 200}, READ, UPLOADS,
    ])
    reads = out["reads"]
    assert reads["until:on_b"] is True and reads["until:back"] is True
    if finish_on == "b":
        assert reads["until:finished_on_b"] is True
    assert [x["status"] for x in reads["on_b"]["files"]] == ["stale"]
    rows = reads["back_a"]["files"]
    assert len(rows) == 1, rows
    assert rows[0]["name"] == "photo.png" and rows[0]["state"] != INTERRUPTED
    assert rows[0]["status"] == ("ready" if finish_on == "b" else "uploading"), rows
    assert [x["status"] for x in reads["ready_a"]["files"]] == ["ready"]
    assert "interrupted" not in (reads["draft_a"] or ""), "the reload record follows the live upload, even seen from B"
    assert len(reads["uploads"]) == 1, "one upload, never restarted by the round trip"
    turn = reads["r"]["fake"]["turns"][-1]
    assert turn["conversation_id"] == "conv-a" and turn["content"] == "Après le retour"
    assert turn["attachments"] == ["jart_up_" + reads["uploads"][0]["id"].replace("-", "")[:40]]
    assert reads["r"]["files"] == [] and reads["r"]["sendStatus"]["hidden"] is True


def test_real_reload_during_upload_shows_interrupted_once(tmp_path):
    """Un VRAI rechargement pendant un envoi : la pièce revient une fois, « interrompu par le rechargement »,
    et ni un tic ni un aller-retour de Board ne la double."""

    f = _files(tmp_path)
    out = _run(tmp_path, [
        QUICK, {"eval": "window.__chat.uploadPlans['photo.png']='hang';1"}, OPEN, _until(f"{BUBBLES}===4"),
        {"files": "#chatFile", "paths": [f["photo.png"]]}, {"wait": 300}, DRAFT_A,
        {"reload": True}, QUICK, _until(f"{BUBBLES}===4&&{FILES}.length>=1", ms=8000, name="reloaded"), {"wait": 600},
        {"value": "after_reload"}, _shot(tmp_path, "reload-interrupted-1440x900"),
        BOARD("board_b", "conv-b"), _until(f"{SNAP}.conversation_id==='conv-b'&&{BUBBLES}===2", name="on_b"),
        BOARD("default", "conv-a"), _until(f"{SNAP}.conversation_id==='conv-a'&&{BUBBLES}===4", name="back"), {"wait": 600},
        {"value": "back_a"}, {"click": "#chatFiles .chat-file-x"}, {"wait": 100},
        {"type": "Sans la photo"}, {"key": "Enter"}, _until(f"{BUBBLES}===6", name="sent"), READ,
    ])
    reads = out["reads"]
    record = reads["draft_a"]
    assert record and '"interrupted":true' in record and '"clientUploadId"' in record, record
    assert reads["until:reloaded"] is True
    for name in ("after_reload", "back_a"):
        rows = reads[name]["files"]
        assert [(x["name"], x["status"], x["state"], x["act"]) for x in rows] == [("photo.png", "failed", INTERRUPTED, None)], name
        assert reads[name]["composer"]["sendDisabled"] == "true"
    assert reads["until:sent"] is True and reads["r"]["fake"]["turns"][-1]["content"] == "Sans la photo"


ROW_CHECK = """(()=>{
  const R=e=>e.getBoundingClientRect(),list=document.getElementById('chatFiles'),panel=R(document.getElementById('chatPanel'));
  const inside=(a,b)=>a.width>0&&a.height>0&&a.top>=b.top-0.5&&a.bottom<=b.bottom+0.5&&a.left>=b.left-0.5&&a.right<=b.right+0.5;
  const hits=(el,box)=>{const r=R(el),h=document.elementFromPoint(r.left+Math.min(r.width/2,8),r.top+r.height/2);return !!h&&(el.contains(h)||h.contains(el))&&box.contains(h)};
  const rows=[...list.querySelectorAll('.chat-file')].map(li=>{
    li.scrollIntoView({block:'nearest'});
    const r=R(li),l=R(list),text=li.querySelector('.chat-file-text'),x=li.querySelector('.chat-file-x'),name=li.querySelector('.chat-file-name');
    return {h:Math.round(r.height),clipped:li.scrollHeight>li.clientHeight+1,inList:inside(r,l),state:inside(R(text),r)&&hits(text,li),
      x:inside(R(x),r)&&hits(x,li),name:inside(R(name),r)};
  });
  const row=R(document.querySelector('#chatCompose .chat-row')),send=R(document.getElementById('chatSend')),
    attach=R(document.getElementById('chatAttach')),hint=document.getElementById('chatHint');
  return {rows,scrolls:list.scrollHeight>list.clientHeight+1,listH:list.clientHeight,panel:{t:panel.top,b:panel.bottom,l:panel.left,r:panel.right},
    rowInside:inside(row,panel)&&inside(send,panel)&&inside(attach,panel),
    rowHit:hits(document.getElementById('chatSend'),document.getElementById('chatPanel')),
    input:Math.round(R(document.getElementById('chatInput')).height),hintH:Math.round(R(hint).height),
    note:!document.getElementById('chatAttNote').hidden&&inside(R(document.getElementById('chatAttNote')),panel),
    scrollWidth:document.documentElement.scrollWidth};
})()"""


@pytest.mark.parametrize("width,height", [(1440, 900), (1024, 480), (600, 800)])
def test_ten_files_rows_keep_their_content_and_composer_stays_in_panel(tmp_path, width, height):
    """QA S7b BLOCKING 2 : dix pièces (la borne par défaut de Core). Chaque ligne garde nom, état et × ; la liste,
    bornée, défile ; la rangée Joindre/Envoyer reste dans le panneau."""

    folder = tmp_path / "ten"
    folder.mkdir()
    paths = []
    for i in range(10):
        ext = ["png", "txt", "zip", "pdf", "mov"][i % 5]
        name = f"piece-{i:02d}-{'un-nom-de-fichier-vraiment-tres-long-' if i == 3 else ''}{ext}.{ext}"
        (folder / name).write_bytes(PNG if ext == "png" else b"x" * (64 + i))
        paths.append(str(folder / name))
    big = "piece-04-mov.mov"
    out = _run(tmp_path, [
        {"eval": f"window.__chat.uploadPlans['{big}']='big';1"}, OPEN, _until(f"{BUBBLES}===4"),
        {"files": "#chatFile", "paths": paths},
        _until(f"{SNAP}.attachments.uploading===0&&{FILES}.length===10", ms=8000, name="settled"),
        {"wait": 300}, {"value": "layout", "expr": ROW_CHECK}, {"eval": "document.getElementById('chatFiles').scrollTop=0;1"},
        {"wait": 100}, _shot(tmp_path, f"ten-files-{width}x{height}"), READ,
    ], width=width, height=height)
    reads = out["reads"]
    assert reads["until:settled"] is True
    lay = reads["layout"]
    assert len(lay["rows"]) == 10
    bad = [(i, row) for i, row in enumerate(lay["rows"])
           if row["clipped"] or not (row["inList"] and row["state"] and row["x"] and row["name"])]
    assert bad == [], bad
    assert all(row["h"] >= 40 for row in lay["rows"]), [row["h"] for row in lay["rows"]]
    assert lay["scrolls"] is True, "ten rows scroll inside the bounded list"
    assert lay["rowInside"] is True and lay["rowHit"] is True, lay
    assert lay["note"] is True, "the failed file's instruction stays visible"
    assert lay["input"] >= 40 and lay["hintH"] <= 18, lay
    assert lay["scrollWidth"] <= width
    states = {x["status"] for x in reads["r"]["files"]}
    assert {"ready", "unreadable", "failed"} <= states


def test_sent_names_are_bidi_isolated(tmp_path):
    """Un U+202E dans un nom ne retourne pas le nom suivant : chaque nom dans son `<bdi>` (texte seulement)."""

    folder = tmp_path / "bidi"
    folder.mkdir()
    rlo = folder / "rapport‮gnp.exe"
    plain = folder / "notes.txt"
    rlo.write_bytes(b"MZ" + bytes(64))
    plain.write_bytes(b"Ordre du jour\n")
    names = ("(()=>[...document.querySelectorAll('#chatLog .chat-att-names')].slice(-1).map(n=>({html:n.children.length,"
             "bdi:[...n.querySelectorAll('bdi')].map(b=>[b.textContent,getComputedStyle(b).unicodeBidi,b.children.length])}))[0])()")
    out = _run(tmp_path, [
        OPEN, _until(f"{BUBBLES}===4"), {"files": "#chatFile", "paths": [str(rlo), str(plain)]},
        _until(f"{READY}===2", name="ready"), {"type": "Deux noms"}, {"key": "Enter"},
        _until(f"{BUBBLES}===6", name="sent"), {"wait": 200}, {"value": "names", "expr": names}, READ,
    ])
    got = out["reads"]["names"]
    assert got["bdi"] == [["rapport‮gnp.exe", "isolate", 0], ["notes.txt", "isolate", 0]]
    assert got["html"] == 2, "only the two isolates, no markup from a name"
    assert out["reads"]["r"]["attLines"][-1] == "2 pièces jointesrapport‮gnp.exe (non lisible par le Brain) · notes.txt"


@pytest.mark.parametrize("theme", ["default", "cosmos"])
def test_hint_stays_on_one_line(tmp_path, theme):
    cosmos = [{"eval": "window.JarvisThemeAPI.activate('cosmos',{persist:false});1"}, {"wait": 600}] if theme == "cosmos" else []
    hint = ("(()=>{const h=document.getElementById('chatHint');return {h:Math.round(h.getBoundingClientRect().height),"
            "full:h.scrollWidth<=h.clientWidth+1,text:h.textContent}})()")
    f = _files(tmp_path)
    out = _run(tmp_path, [*cosmos, OPEN, _until(f"{BUBBLES}===4"), {"files": "#chatFile", "paths": [f["notes.txt"], f["archive.zip"]]},
                          _until(f"{READY}===2", name="ready"), {"type": "Message Cosmos"}, {"wait": 200},
                          {"value": "hint", "expr": hint}, _shot(tmp_path, f"hint-{theme}-1440x900")])
    got = out["reads"]["hint"]
    assert got["h"] <= 18 and got["full"] is True, got
    assert got["text"] == "Entrée envoie · Maj+Entrée : à la ligne"

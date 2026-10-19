"""Dossier plein écran, dans un vrai Chrome sans tête (wheel-dossier-refactor, Slice 07).

Contrat : `docs/dossier.md` › *Full-screen Dossier (UI)*. La page est celle que `ControlCenter.index` sert ;
`fetch` est le double de `_status_centre_browser.mjs` (graine `dsr` : Boards, entrées, fichiers de mémoire ;
registre ; canal de navigation `__sc.navPush`). Ce que ce fichier épingle, par vrais clics et vraies touches :

- la roue ouvre le Dossier du Board affiché ; Échap revient au Board, le focus revient d'où il était parti ;
- grands arbres (100 entrées, dossiers imbriqués), documents longs (« Lire la suite »), images, onglets multiples
  et côte à côte ; repli en onglets et tiroirs en format étroit ;
- Board archivé (lecture seule, rien ne s'écrit), Core indisponible (dit, réessayable) ;
- bascule de Board pendant l'ouverture : jamais le titre de A sur le contenu de B ;
- édition par `memory/write` + `expected_sha256` ; conflit 409 visible, texte gardé ;
- Afficher sur le Board = `…/dossier/present` (201 créé, 200 repris) ;
- canal Jarvis -> page : ordre pris au long-poll, reçu signé du jeton de page, refus codés.

Preuves visuelles : `JARVIS_S07_DOSSIER_EVIDENCE_DIR=<dossier>` y écrit les captures. Se saute sans Chrome ni node.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.unit.test_status_centre_browser import _drive

EVIDENCE = os.environ.get("JARVIS_S07_DOSSIER_EVIDENCE_DIR")
SIZES = ((1920, 1032), (1280, 720), (600, 800))
A, B, ARCH = "board_atlas", "board_budget", "board_old"
IMG = "jart_" + "1" * 32
TRS = "jart_" + "2" * 32

REPORT = """# Compte rendu du comité du 14 octobre

Le comité valide **le budget 2027** sous réserve du chiffrage des licences.

## Décisions

- Budget de fonctionnement : *reconduit* à l'identique.
- Licences : chiffrage demandé à `Achats` pour le 30 octobre.
- Recrutement : un poste ouvert au T1.

> Les montants définitifs seront arrêtés au prochain comité.

Voir aussi https://intranet.exemple/budget pour le détail.
"""
DECISION = "# Décision budget\n\nLe budget est reconduit, les licences sont chiffrées à part.\n"
LONG = "# Journal de projet\n\n" + "".join(f"Paragraphe {i} : le travail avance, une ligne de journal assez longue pour peser.\n\n"
                                          for i in range(1, 2400))


def _mem(path: str, kind: str = "note", *, minutes: int = 60, size: int = 400) -> dict:
    folder = path.rsplit("/", 1)[0] if "/" in path else ""
    title = "Résumé du Board" if path == "summary.md" else path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return {"entry_id": f"memory:{path}", "source": "memory", "kind": kind, "title": title, "open": "text",
            "folder": folder, "path": path, "size": size, "modified_at": f"2026-10-18T{10 + minutes // 60:02d}:{minutes % 60:02d}:00+00:00"}


def _art(artifact_id: str, kind: str, title: str, *, open_: str, preview: str | None = None) -> dict:
    return {"entry_id": f"artifact:{artifact_id}", "source": "artifact", "kind": kind, "title": title, "open": open_,
            "preview": preview, "state": "complete", "modified_at": "2026-10-18T09:00:00+00:00",
            "added_at": "2026-10-18T09:00:00+00:00", "provenance": "déposé sur le Board"}


def seed(*, active: str = A, big: bool = False) -> dict:
    entries = [_mem("summary.md", "memory_summary", minutes=200), _mem("comptes-rendus/comite-14-octobre.md", minutes=180),
               _mem("notes/decision-budget.md", minutes=150), _mem("notes/journal.md", minutes=120, size=len(LONG)),
               _art(IMG, "image", "Schéma d'architecture", open_="media", preview="schema.png"),
               _art(TRS, "transcript", "Transcription du 18/10/2026 14:05", open_="text", preview="Bonjour à tous…")]
    files = {"summary.md": {"text": "# Projet Atlas\n\nObjectif : livrer la refonte du portail avant décembre. Budget validé le 14 octobre.\n", "sha": "s1"},
             "comptes-rendus/comite-14-octobre.md": {"text": REPORT, "sha": "s2"},
             "notes/decision-budget.md": {"text": DECISION, "sha": "s3"},
             "notes/journal.md": {"text": LONG, "sha": "s4"}}
    if big:
        for i in range(94):
            folder = f"archives/{2020 + i % 5}/lot-{i % 7}"
            path = f"{folder}/piece-{i:03d}.md"
            entries.append(_mem(path, minutes=i))
            files[path] = {"text": f"# Pièce {i}\n\nContenu {i}.\n", "sha": f"p{i}"}
    boards = {
        A: {"board": {"board_id": A, "title": "Projet Atlas", "board_kind": "presentation", "status": "active", "writable": True},
            "entries": entries, "files": files},
        B: {"board": {"board_id": B, "title": "Budget 2027", "board_kind": "meeting", "status": "active", "writable": True},
            "entries": [_mem("notes/arbitrages.md")], "files": {"notes/arbitrages.md": {"text": "# Arbitrages\n\nRien encore.\n", "sha": "b1"}}},
        ARCH: {"board": {"board_id": ARCH, "title": "Ancien salon", "board_kind": "assistant", "status": "archived", "writable": False},
               "entries": [_mem("notes/bilan.md")], "files": {"notes/bilan.md": {"text": "# Bilan\n\nSalon clos.\n", "sha": "o1"}}},
    }
    registry = {IMG: {"artifact_id": IMG, "kind": "screenshot", "mime_type": "image/png", "has_payload": True, "text": None},
                TRS: {"artifact_id": TRS, "kind": "transcript", "mime_type": "text/plain", "has_payload": False,
                      "text": "Bonjour à tous. Nous ouvrons la séance sur le budget.", "text_truncated": False}}
    return {"objects": [], "dsr": {"boards": boards}, "registry": registry, "activeBoard": active,
            "boards": [{"board_id": A, "title": "Projet Atlas", "status": "active", "board_kind": "presentation"},
                       {"board_id": B, "title": "Budget 2027", "status": "active", "board_kind": "meeting"}]}


OPEN_DOSSIER = [["click", "wheel", "#toolWheel .tw-anchor", 400],
                ["click", "dossierSlot", "#toolWheel [data-tw-slot=dossier] .tw-dot", 900],
                ["click", "openRow", "#toolWheel .tw-item[data-tw-item='open']", 900]]
STATE = "JarvisDossier.state()"
HEAD = "document.getElementById('dsrTitle').textContent"
DOC = "[...document.querySelectorAll('#dossierView article.dsr-doc')].map(a=>a.dataset.entry)"
PROSE = "(document.querySelector('#dossierView article.dsr-doc .dsr-prose')||{}).innerText||''"
TABS = "[...document.querySelectorAll('#dossierView [role=tab]')].map(t=>t.textContent)"
ROW = "#dossierView [data-open='{}']"


def _shot(name: str, size: tuple[int, int]) -> list:
    if not EVIDENCE:
        return []
    Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
    return [["shot", f"shot:{name}", str(Path(EVIDENCE) / f"{name}-{size[0]}x{size[1]}.png"), 150]]


def _no_errors(step: dict) -> None:
    bad = [line for line in step["console"] if line["type"] in ("error", "exception")]
    assert not bad, bad


FOCUS = "(()=>{const a=document.activeElement;return a?(a.id?'#'+a.id:a.className||a.tagName):null})()"
RECEIPTS = "window.__sc.receipts||[]"
NOTICE = "document.getElementById('dsrNotice').hidden?'':document.getElementById('dsrNotice').textContent"
FLASH = "[...document.querySelectorAll('#dossierView .dsr-flash')].map(n=>n.textContent)"
TYPE = ("(()=>{const t=document.querySelector('#dossierView textarea');t.value=t.value+'\\nAjout de Clarice.';"
        "t.dispatchEvent(new Event('input',{bubbles:true}));return t.value.length})()")
CID = "c" * 20


def _act(act: str, entry: str) -> str:
    return f"#dossierView [data-act='{act}'][data-entry='{entry}']"


def _open(entry: str, wait: int = 700) -> list:
    return ["click", f"open:{entry}", ROW.format(entry), wait]


def _js_open_board(board: str) -> list:
    return ["eval", f"openBoard:{board}", f"JarvisDossier.openBoard('{board}').ok", 900]


def _writes(step: dict) -> list:
    return [b["body"] for b in step["bodies"] if b["path"].endswith("/memory/write")]


# ------------------------------------------------------------------ ouverture, fermeture, focus


def test_the_wheel_opens_the_displayed_boards_dossier_and_escape_returns_to_the_board(tmp_path):
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed(), "actions": [
        *OPEN_DOSSIER, ["eval", "state", STATE, 600], ["eval", "head", HEAD, 50],
        ["eval", "inert", "[...document.body.children].filter(n=>n.inert).length>0", 50],
        ["eval", "focusIn", "document.getElementById('dossierView').contains(document.activeElement)", 50],
        ["key", "esc", "Escape", 500], ["eval", "after", STATE, 50], ["eval", "focus", FOCUS, 50],
        ["eval", "inertAfter", "[...document.body.children].filter(n=>n.inert).length", 50],
    ]}])[0]
    r = step["results"]
    assert r["state"]["open"] is True and r["state"]["boardId"] == A and r["state"]["follow"] is True
    assert "Dossier" in r["head"] and "Présentation" in r["head"] and "Projet Atlas" in r["head"], r["head"]
    assert r["inert"] is True and r["focusIn"] is True, "focus trapped in the full-screen view, the rest inert"
    assert r["after"]["open"] is False and r["inertAfter"] == 0
    assert "tw-anchor" in str(r["focus"]), f"focus back on the wheel anchor, got {r['focus']}"
    assert any(c.startswith(f"GET /api/workspace/boards/{A}/dossier") for c in step["calls"])
    _no_errors(step)


def test_tab_never_leaves_the_dossier_and_escape_closes_inner_layers_first(tmp_path):
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed(), "actions": [
        *OPEN_DOSSIER, _open("memory:notes/decision-budget.md"),
        ["tabto", "tabs", "#toolWheel", 400, 45],
        ["click", "menu", _act("present-menu", "memory:notes/decision-budget.md"), 300],
        ["eval", "menuOpen", "!!document.getElementById('dsrMenu')", 50],
        ["key", "esc1", "Escape", 300], ["eval", "menuAfter", "!!document.getElementById('dsrMenu')", 50],
        ["eval", "stillOpen", "JarvisDossier.isOpen()", 50],
        ["key", "esc2", "Escape", 400], ["eval", "closed", "JarvisDossier.isOpen()", 50],
    ]}])[0]
    r = step["results"]
    assert not any(stop["inside"] for stop in r["tabs"]), "Tab cycles inside the Dossier, never reaches the wheel"
    assert r["menuOpen"] is True and r["menuAfter"] is False and r["stillOpen"] is True
    assert r["closed"] is False
    _no_errors(step)


# ------------------------------------------------------------------ grands arbres, documents longs, images, onglets


def test_large_tree_long_document_image_and_side_by_side(tmp_path):
    folder = "[...document.querySelectorAll('#dossierView .dsr-nav[data-section^=\"f:\"]')].length"
    step = _drive(tmp_path, [{"width": 1920, "height": 1032, "seed": seed(big=True), "actions": [
        *OPEN_DOSSIER, ["eval", "count", "JarvisDossier.state().list", 300], ["eval", "folders", folder, 50],
        ["click", "twisty", "#dossierView [data-twisty='archives']", 300], ["eval", "foldersAfter", folder, 50],
        ["click", "twisty2", "#dossierView [data-twisty='archives']", 300],
        ["click", "section", "#dossierView [data-section='f:archives/2021']", 400],
        ["eval", "rows", "document.querySelectorAll('#dossierView .dsr-browse .dsr-row').length", 50],
        ["click", "home", "#dossierView [data-section='home']", 300],
        _open("memory:notes/journal.md", 900),
        ["eval", "long", "document.querySelectorAll('#dossierView .dsr-prose p').length", 50],
        ["eval", "reveal", f"document.querySelector(\"{_act('more-text', 'memory:notes/journal.md')}\").scrollIntoView();1", 200],
        ["click", "more", _act("more-text", "memory:notes/journal.md"), 900],
        ["eval", "longer", "document.querySelectorAll('#dossierView .dsr-prose p').length", 50],
        ["click", "back", "#dossierView [data-tab='browse']", 300],
        _open(f"artifact:{IMG}", 900),
        ["eval", "img", "(document.querySelector('#dossierView .dsr-figure img')||{}).src||''", 50],
        ["click", "back2", "#dossierView [data-tab='browse']", 300],
        _open("memory:comptes-rendus/comite-14-octobre.md", 900),
        ["eval", "tabs", TABS, 50],
        ["click", "compare", _act("compare-menu", "memory:comptes-rendus/comite-14-octobre.md"), 300],
        ["click", "pick", "#dossierView [data-act='compare'][data-value='memory:notes/journal.md']", 900],
        ["eval", "docs", DOC, 50],
        *_shot("deux-entrees-cote-a-cote", (1920, 1032)),
    ]}])[0]
    r = step["results"]
    assert r["count"]["count"] == 100 and r["count"]["total"] == 100, r["count"]
    assert r["folders"] > r["foldersAfter"] >= 1, (r["folders"], r["foldersAfter"])
    assert r["rows"] > 0
    assert 0 < r["long"] < r["longer"], "a long note reads by chunks, « Lire la suite » appends"
    assert r["img"].endswith(f"/api/artifacts/{IMG}/payload"), r["img"]
    assert len(r["tabs"]) == 4, r["tabs"]
    assert r["docs"] == ["memory:comptes-rendus/comite-14-octobre.md", "memory:notes/journal.md"], r["docs"]
    _no_errors(step)


def test_narrow_screen_falls_back_to_tabs_and_drawers(tmp_path):
    org_shown = "getComputedStyle(document.getElementById('dsrOrg')).display!=='none'"
    step = _drive(tmp_path, [{"width": 600, "height": 800, "seed": seed(), "actions": [
        ["eval", "open", "JarvisDossier.open().ok", 900], ["eval", "org", org_shown, 50],
        ["click", "drawer", "#dsrOrgToggle", 300], ["eval", "orgOpen", org_shown, 50],
        ["eval", "onTop", "(()=>{const o=document.getElementById('dsrOrg').getBoundingClientRect();"
         "return [...Array(6)].every((_,i)=>document.getElementById('dsrOrg').contains(document.elementFromPoint(o.left+o.width/2,o.top+40+i*90)))})()", 50],
        ["click", "notes", "#dossierView [data-section='c:notes']", 400], ["eval", "orgClosed", org_shown, 50],
        _open("memory:notes/decision-budget.md"), ["click", "back", "#dossierView [data-tab='browse']", 300],
        ["click", "drawer2", "#dsrOrgToggle", 300], ["click", "home", "#dossierView [data-section='home']", 300],
        _open("memory:comptes-rendus/comite-14-octobre.md"),
        ["eval", "compare", "!!document.querySelector(\"#dossierView [data-act='compare-menu']\")", 50],
        ["eval", "docs", DOC, 50], ["eval", "layout", "JarvisDossier.state().layout", 50],
        ["eval", "overflow", "document.documentElement.scrollWidth<=innerWidth&&document.getElementById('dossierView').scrollWidth<=innerWidth", 50],
    ]}])[0]
    r = step["results"]
    assert r["open"] is True and r["org"] is False and r["orgOpen"] is True and r["orgClosed"] is False
    assert r["onTop"] is True, "the drawer is drawn above the masked summary excerpt (QA S07)"
    assert r["compare"] is False and r["docs"] == ["memory:comptes-rendus/comite-14-octobre.md"], "no side by side under 900 px"
    assert r["layout"]["narrow"] is True and r["layout"]["split"] is False
    assert r["overflow"] is True, "no horizontal scroll at 600 px"
    _no_errors(step)


# ------------------------------------------------------------------ Board archivé, Core indisponible, bascule


def test_an_archived_board_reads_and_writes_nothing(tmp_path):
    entry = "memory:notes/bilan.md"
    step = _drive(tmp_path, [{"width": 1280, "height": 720, "seed": seed(), "actions": [
        _js_open_board(ARCH), ["eval", "head", HEAD, 50], ["eval", "notice", NOTICE, 50],
        _open(entry), ["eval", "prose", PROSE, 50],
        ["eval", "edit", f"document.querySelector(\"{_act('edit', entry)}\").getAttribute('aria-disabled')", 50],
        ["click", "tryEdit", _act("edit", entry), 300],
        ["eval", "editor", "!!document.querySelector('#dossierView textarea')", 50],
        ["click", "present", _act("present-menu", entry), 300],
        ["eval", "menu", "!!document.getElementById('dsrMenu')", 50], ["eval", "why", NOTICE, 50],
    ]}])[0]
    r = step["results"]
    assert "Archivé" in r["head"] and "Ancien salon" in r["head"]
    assert "archivé" in r["notice"] and "Salon clos" in r["prose"]
    assert r["edit"] == "true" and r["editor"] is False and r["menu"] is False and "archivé" in r["why"], r["why"]
    assert not [c for c in step["calls"] if c.startswith("POST") and ("/workspace/" in c)], "nothing is written on an archived Board"
    _no_errors(step)


def test_core_unavailable_is_said_and_retry_recovers(tmp_path):
    s = seed()
    s["dsrFail"] = {"list": {"status": 503, "code": "core_unreachable"}}
    step = _drive(tmp_path, [{"width": 1280, "height": 720, "seed": s, "actions": [
        ["eval", "open", "JarvisDossier.open().ok", 900],
        ["eval", "error", "(document.querySelector('#dossierView .dsr-error')||{}).textContent||''", 50],
        ["eval", "heal", "delete window.__sc.dsrFail;1", 50],
        ["click", "retry", "#dossierView [data-act='reload']", 700],
        ["eval", "list", "JarvisDossier.state().list", 50],
        ["eval", "lose", "window.__sc.statusFail=true;1", 2000], ["eval", "notice", NOTICE, 50],
        ["eval", "lost", "JarvisDossier.state().coreLost", 50],
    ]}])[0]
    r = step["results"]
    assert "Core ne répond pas" in r["error"] and "core_unreachable" in r["error"], r["error"]
    assert r["list"]["status"] == "ok" and r["list"]["count"] == 6
    assert r["lost"] is True and "Core ne répond pas" in r["notice"]
    # Le battement perdu fait dire la console ; seules les erreurs du Dossier comptent ici.
    assert not [line for line in step["console"] if line["type"] == "exception"]


def test_a_board_switch_rebinds_the_dossier_never_title_a_with_content_b(tmp_path):
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed(), "actions": [
        ["eval", "open", "JarvisDossier.open().ok", 900], _open("memory:notes/decision-budget.md"),
        ["eval", "switch", f"window.__sc.activeBoard='{B}';1", 2600],
        ["eval", "head", HEAD, 50], ["eval", "state", STATE, 50], ["eval", "notice", NOTICE, 50],
        ["eval", "rows", "[...document.querySelectorAll('#dossierView .dsr-row-title')].map(n=>n.textContent)", 50],
    ]}])[0]
    r = step["results"]
    assert "Budget 2027" in r["head"] and "Projet Atlas" not in r["head"], r["head"]
    assert r["state"]["boardId"] == B and r["state"]["tabs"] == [], "the documents of A are closed"
    assert r["rows"] == ["arbitrages"], r["rows"]
    assert "a changé" in r["notice"]
    _no_errors(step)


# ------------------------------------------------------------------ édition et conflit, Afficher sur le Board


def test_edit_saves_with_the_read_sha_and_a_conflict_keeps_the_text(tmp_path):
    entry = "memory:notes/decision-budget.md"
    path = "notes/decision-budget.md"
    touch = f"window.__sc.dsrTouch('{A}','{path}','# Décision budget\\n\\nChangé par Jarvis entre-temps.\\n')"
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed(), "actions": [
        ["eval", "open", "JarvisDossier.open().ok", 900], _open(entry),
        ["click", "edit", _act("edit", entry), 500], ["eval", "typed", TYPE, 100],
        ["click", "save", _act("save", entry), 900], ["eval", "flash", FLASH, 50], ["eval", "prose", PROSE, 50],
        ["click", "edit2", _act("edit", entry), 500], ["eval", "typed2", TYPE, 100],
        ["eval", "touch", touch, 50],
        ["click", "save2", _act("save", entry), 900],
        ["eval", "conflict", "(document.querySelector('#dossierView .dsr-conflict')||{}).textContent||''", 50],
        ["eval", "draft", "document.querySelector('#dossierView textarea').value", 50],
        ["eval", "theirs", "(document.querySelector('#dossierView .dsr-theirs')||{}).textContent||''", 50],
        *_shot("edition-conflit", (1440, 900)),
        ["eval", "reveal", f"document.querySelector(\"{_act('save', entry)}\").scrollIntoView();1", 200],
        ["click", "save3", _act("save", entry), 900], ["eval", "flash3", FLASH, 50],
    ]}])[0]
    r = step["results"]
    sent = _writes(step)
    assert sent[0]["expected_sha256"] == "s3" and sent[0]["mode"] == "replace" and sent[0]["path"] == path
    assert any("Enregistré" in f for f in r["flash"]) and "Ajout de Clarice." in r["prose"]
    assert "a changé depuis votre lecture" in r["conflict"] and "rien n’a été écrit" in r["conflict"]
    assert r["draft"].endswith("Ajout de Clarice.") and "Changé par Jarvis" in r["theirs"], "draft kept, disk version shown"
    assert len(sent) == 3 and sent[2]["expected_sha256"] != sent[1]["expected_sha256"], "the overwrite is explicit, new sha"
    assert any("Enregistré" in f for f in r["flash3"])
    _no_errors(step)


def test_afficher_sur_le_board_presents_the_same_source(tmp_path):
    entry = "memory:comptes-rendus/comite-14-octobre.md"
    pick = "#dsrMenu [data-act='present'][data-value='{}']"
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed(), "actions": [
        ["eval", "open", "JarvisDossier.open().ok", 900], _open(entry),
        ["click", "menu", _act("present-menu", entry), 300],
        ["eval", "items", "[...document.querySelectorAll('#dsrMenu [role=menuitem]')].map(n=>n.dataset.value)", 50],
        ["click", "window", pick.format("window"), 700], ["eval", "flash1", FLASH, 50],
        ["click", "menu2", _act("present-menu", entry), 300], ["click", "capsule", pick.format("capsule"), 700],
        ["eval", "flash2", FLASH, 50],
    ]}])[0]
    r = step["results"]
    sent = [b["body"] for b in step["bodies"] if b["path"].endswith("/dossier/present")]
    assert r["items"] == ["window", "capsule", "point"]
    assert sent == [{"entry_id": entry, "representation": "window"}, {"entry_id": entry, "representation": "capsule"}]
    assert "Affiché sur le Board" in r["flash1"][0] and "Déjà sur le Board" in r["flash2"][0]
    assert not [c for c in step["calls"] if "/memory/write" in c], "presenting copies nothing"
    _no_errors(step)


# ------------------------------------------------------------------ canal Jarvis -> page


def _nav(entry: str, board: str = A, n: int = 0) -> list:
    cmd = {"id": f"{CID}{n:04d}", "action": "open_entry", "board_id": board, "entry_id": entry}
    return ["eval", f"nav{n}", f"window.__sc.navPush({json.dumps(cmd)})", 1400]


def test_jarvis_opens_entries_through_the_channel_and_says_what_it_did(tmp_path):
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed(), "actions": [
        _nav("memory:comptes-rendus/comite-14-octobre.md", n=1), ["eval", "s1", STATE, 50],
        _nav("memory:notes/decision-budget.md", n=2), ["eval", "docs", DOC, 50],
        _nav("memory:notes/arbitrages.md", board=B, n=3), _nav("memory:absent.md", n=4),
        ["eval", "receipts", RECEIPTS, 50],
    ]}])[0]
    r = step["results"]
    assert r["s1"]["open"] is True and r["s1"]["active"] == "memory:comptes-rendus/comite-14-octobre.md"
    assert r["s1"]["tabs"] == [{"entryId": "memory:comptes-rendus/comite-14-octobre.md", "opener": "jarvis"}]
    assert r["docs"] == ["memory:comptes-rendus/comite-14-octobre.md", "memory:notes/decision-budget.md"], \
        "two documents asked together are shown side by side"
    by = {x["id"][-4:]: x for x in r["receipts"]}
    assert by["0001"]["body"] == {"state": "opened"} and by["0002"]["body"] == {"state": "opened"}
    assert by["0003"]["body"]["state"] == "refused" and by["0003"]["body"]["code"] == "board_not_displayed"
    assert by["0004"]["body"]["code"] == "entry_not_found"
    assert all(x["token"] == "__JARVIS_DOSSIER_PAGE_TOKEN__" for x in r["receipts"]), "each receipt carries the page token"
    _no_errors(step)


def test_jarvis_is_refused_while_variantes_covers_the_screen(tmp_path):
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed(), "actions": [
        ["eval", "run", "document.documentElement.classList.add('jvx-run');1", 50],
        _nav("memory:notes/decision-budget.md", n=5), ["eval", "receipts", RECEIPTS, 50],
        ["eval", "open", "JarvisDossier.isOpen()", 50],
    ]}])[0]
    r = step["results"]
    assert r["receipts"][0]["body"]["code"] == "dossier_unavailable" and "Variantes" in r["receipts"][0]["body"]["reason"]
    assert r["open"] is False
    _no_errors(step)


# ------------------------------------------------------------------ preuves (captures de la Slice seulement)


@pytest.mark.skipif(not EVIDENCE, reason="captures de la Slice seulement (JARVIS_S07_DOSSIER_EVIDENCE_DIR)")
@pytest.mark.parametrize("size", SIZES)
def test_evidence_captures(tmp_path, size):
    s = seed()
    s["dsrFail"] = {"list": {"status": 503, "code": "core_unreachable"}}
    steps = _drive(tmp_path, [
        {"width": size[0], "height": size[1], "seed": seed(), "actions": [
            ["eval", "open", "JarvisDossier.open().ok", 1000], *_shot("accueil", size),
            _open("memory:comptes-rendus/comite-14-octobre.md", 900), *_shot("entree-texte", size),
            ["click", "back", "#dossierView [data-tab='browse']", 300], _open(f"artifact:{IMG}", 900), *_shot("image", size),
            ["click", "ctx", "#dsrCtxToggle", 300], ["click", "adv", "#dossierView .dsr-adv summary", 900],
            *_shot("vue-avancee", size)]},
        {"width": size[0], "height": size[1], "seed": seed(), "actions": [
            _js_open_board(ARCH), _open("memory:notes/bilan.md", 800), *_shot("board-archive", size)]},
        {"width": size[0], "height": size[1], "seed": s, "actions": [
            ["eval", "open", "JarvisDossier.open().ok", 1000], *_shot("core-indisponible", size)]},
        {"width": size[0], "height": size[1], "seed": seed(), "actions": [
            _nav("memory:comptes-rendus/comite-14-octobre.md", n=1), _nav("memory:notes/decision-budget.md", n=2),
            *_shot("ouverture-par-jarvis", size)]},
        {"width": size[0], "height": size[1], "seed": seed(), "actions": [
            ["eval", "open", "JarvisDossier.open().ok", 900], _open("memory:notes/decision-budget.md"),
            ["click", "edit", _act("edit", "memory:notes/decision-budget.md"), 500], ["eval", "typed", TYPE, 100],
            ["eval", "touch", f"window.__sc.dsrTouch('{A}','notes/decision-budget.md','# Décision budget\\n\\nChangé entre-temps.\\n')", 50],
            ["eval", "reveal", f"document.querySelector(\"{_act('save', 'memory:notes/decision-budget.md')}\").scrollIntoView();1", 200],
            ["click", "save", _act("save", "memory:notes/decision-budget.md"), 900],
            ["eval", "top", "document.querySelector('#dossierView .dsr-conflict').scrollIntoView();1", 200], *_shot("edition-conflit", size)]},
    ])
    for step in steps[:2] + steps[3:]:
        _no_errors(step)


# ------------------------------------------------------------------ QA Slice 07 : une modification ne se perd jamais en silence

DRAFT = "(document.querySelector(\"#dossierView textarea[data-entry='memory:notes/decision-budget.md']\")||{}).value||''"


def _edit_decision() -> list:
    entry = "memory:notes/decision-budget.md"
    return [["eval", "open", "JarvisDossier.open().ok", 900], _open(entry),
            ["click", "edit", _act("edit", entry), 600], ["eval", "typed", TYPE, 150]]


def test_a_jarvis_order_after_a_board_switch_never_drops_an_unsaved_edit(tmp_path):
    """B1 : bascule (le Dossier reste sur Atlas, avis), puis Jarvis demande une entrée de Budget 2027 : refusé."""

    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed(), "actions": [
        *_edit_decision(),
        ["eval", "switch", f"window.__sc.activeBoard='{B}';1", 2600], ["eval", "held", STATE, 50],
        _nav("memory:notes/arbitrages.md", board=B, n=7),
        ["eval", "receipts", RECEIPTS, 50], ["eval", "after", STATE, 50], ["eval", "draft", DRAFT, 50],
        ["eval", "notice", NOTICE, 50], ["eval", "head", HEAD, 50],
    ]}])[0]
    r = step["results"]
    assert r["held"]["boardId"] == A and r["held"]["follow"] is False
    [receipt] = r["receipts"]
    assert receipt["body"]["state"] == "refused" and receipt["body"]["code"] == "edit_in_progress", receipt
    assert r["after"]["boardId"] == A and "Projet Atlas" in r["head"]
    assert r["draft"].endswith("Ajout de Clarice."), "the draft is intact"
    assert "Jarvis voulait ouvrir" in r["notice"] and "arbitrages" in r["notice"], r["notice"]
    assert not [c for c in step["calls"] if "/memory/write" in c]
    _no_errors(step)


def test_an_edited_tab_is_never_evicted_and_closing_asks_first(tmp_path):
    """B2 : une modification, puis huit autres entrées : l'onglet modifié reste ; close() demande « Abandonner ? »."""

    others = [f"memory:archives/{2020 + i % 5}/lot-{i % 7}/piece-{i:03d}.md" for i in range(8)]
    opens = [["eval", f"o{i}", f"JarvisDossier.openEntry({{entry_id:'{e}'}}).then(r=>r.ok)", 500] for i, e in enumerate(others)]
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed(big=True), "actions": [
        *_edit_decision(), *opens,
        ["eval", "tabs", "JarvisDossier.state().tabs", 50],
        ["eval", "closed", "JarvisDossier.close()", 400], ["eval", "open", "JarvisDossier.isOpen()", 50],
        ["eval", "ask", "!!document.querySelector(\"#dossierView [data-fk='discard-no']\")", 50],
        ["eval", "draft", DRAFT, 50],
    ]}])[0]
    r = step["results"]
    ids = [t["entryId"] for t in r["tabs"]]
    assert len(ids) == 8 and "memory:notes/decision-budget.md" in ids, ids
    assert [t for t in r["tabs"] if t["entryId"] == "memory:notes/decision-budget.md"][0].get("dirty") is True
    assert r["closed"] is False and r["open"] is True and r["ask"] is True, "closing asks « Abandonner ? »"
    assert r["draft"].endswith("Ajout de Clarice.")
    _no_errors(step)


def test_renaming_says_so(tmp_path):
    """QA S07 : le message « Renommé : … » survit à la relecture du document."""

    entry = "memory:notes/decision-budget.md"
    setv = ("(()=>{const i=document.querySelector(\"#dossierView [data-fk='move-input']\");i.value='notes/decision-budget-2027.md';"
            "i.dispatchEvent(new Event('input',{bubbles:true}));return i.value})()")
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed(), "actions": [
        ["eval", "open", "JarvisDossier.open().ok", 900], _open(entry),
        ["click", "more", _act("more-menu", entry), 300], ["click", "form", "#dsrMenu [data-act='move-form']", 300],
        ["eval", "set", setv, 100], ["click", "go", "#dossierView form[data-form='move'] button[type='submit']", 1200],
        ["eval", "flash", FLASH, 50], ["eval", "state", STATE, 50],
    ]}])[0]
    r = step["results"]
    assert any("Renommé : notes/decision-budget-2027.md" in f for f in r["flash"]), r["flash"]
    assert r["state"]["active"] == "memory:notes/decision-budget-2027.md"
    _no_errors(step)


def test_core_stopped_while_the_control_center_answers_is_said_as_core_lost(tmp_path):
    """QA S07 1 (Slice 08) : Core arrêté, le Control Center répond encore ; le bloc `boards` du statut arrive sans
    Board actif et avec son erreur. Le Dossier dit « Core ne répond pas » (et non « pas le Board affiché ») et
    Afficher sur le Board ne part pas sur le réseau ; il revient quand Core répond."""
    entry = "memory:comptes-rendus/comite-14-octobre.md"
    down = ("window.__sc.status={boards:{available:false,active:null,jarvis_session_id:null,bindings:[],"
            "error:{code:'core_unreachable',message:'Core injoignable'}}};1")
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed(), "actions": [
        ["eval", "open", "JarvisDossier.open().ok", 900], _open(entry),
        ["eval", "down", down, 2200], ["eval", "lost", "JarvisDossier.state().coreLost", 50], ["eval", "notice", NOTICE, 50],
        ["click", "menu", _act("present-menu", entry), 300],
        ["eval", "items", "[...document.querySelectorAll('#dsrMenu [role=menuitem]')].map(n=>n.dataset.value)", 50],
        ["click", "window", "#dsrMenu [data-act='present'][data-value='window']", 500], ["eval", "flash", FLASH, 50],
        ["eval", "up", "delete window.__sc.status;1", 2200], ["eval", "back", "JarvisDossier.state().coreLost", 50],
    ]}])[0]
    r = step["results"]
    assert r["lost"] is True and "Core ne répond pas" in r["notice"], r["notice"]
    sent = [b for b in step["bodies"] if b["path"].endswith("/dossier/present")]
    assert sent == [], "nothing goes to the network while Core does not answer"
    assert all("pas le Board affiché" not in f for f in r["flash"]), r["flash"]
    assert any("Core ne répond pas" in f for f in r["flash"]) or not r["items"], r
    assert r["back"] is False


def test_an_old_present_message_is_not_shown_during_an_edit(tmp_path):
    """QA S07 4 (Slice 08) : « Déjà sur le Board » restait affiché pendant la modification et le conflit."""
    entry = "memory:comptes-rendus/comite-14-octobre.md"
    pick = "#dsrMenu [data-act='present'][data-value='{}']"
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed(), "actions": [
        ["eval", "open", "JarvisDossier.open().ok", 900], _open(entry),
        ["click", "menu", _act("present-menu", entry), 300], ["click", "window", pick.format("window"), 700],
        ["click", "menu2", _act("present-menu", entry), 300], ["click", "again", pick.format("window"), 700],
        ["eval", "before", FLASH, 50],
        ["click", "edit", _act("edit", entry), 600], ["eval", "during", FLASH, 50],
    ]}])[0]
    r = step["results"]
    assert any("Déjà sur le Board" in f for f in r["before"]), r["before"]
    assert r["during"] == [], r["during"]
    _no_errors(step)


def test_a_note_read_once_is_listed_by_its_heading(tmp_path):
    """Polish S07 impl 7 (Slice 08) : la liste montrait le nom du fichier (« decision-budget ») alors que le document
    ouvert montrait son titre `#` (« Décision budget ») ; une note lue est listée par son titre."""
    rows = "[...document.querySelectorAll('#dossierView .dsr-row-title')].map(n=>n.textContent)"
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed(), "actions": [
        ["eval", "open", "JarvisDossier.open().ok", 900], ["eval", "before", rows, 50],
        _open("memory:notes/decision-budget.md"),
        ["click", "browse", "#dossierView [data-tab='browse']", 400], ["eval", "after", rows, 50],
    ]}])[0]
    r = step["results"]
    assert "decision-budget" in r["before"], r["before"]
    assert "Décision budget" in r["after"] and "decision-budget" not in r["after"], r["after"]
    _no_errors(step)


def test_a_board_switch_during_afficher_sur_le_board_leaves_no_endless_wait(tmp_path):
    """QA S08 B2 : le Board change pendant « Afficher sur le Board » ; la réponse périmée est écartée, et
    « Affichage sur le Board… N s » ne reste pas affiché indéfiniment."""
    entry = "memory:comptes-rendus/comite-14-octobre.md"
    s = seed()
    s["dsrDelayMs"] = {"present": 2500}
    status = "(document.getElementById('dsrStatus')||document.querySelector('#dossierView .dsr-status')||{}).textContent||''"
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": s, "actions": [
        ["eval", "open", "JarvisDossier.open().ok", 900], _open(entry),
        ["click", "menu", _act("present-menu", entry), 300],
        ["click", "window", "#dsrMenu [data-act='present'][data-value='window']", 300],
        ["eval", "during", status, 50],
        ["eval", "switch", f"window.__sc.activeBoard='{B}';1", 4500],
        ["eval", "after", status, 50], ["eval", "state", STATE, 50],
    ]}])[0]
    r = step["results"]
    assert "Affichage sur le Board" in r["during"], r["during"]
    assert r["state"]["boardId"] == B
    assert "Affichage sur le Board" not in r["after"], r["after"]
    _no_errors(step)


def test_a_hanging_status_never_piles_up_and_is_said_lost(tmp_path):
    """QA S08 B1 : `refreshStatus` n'avait ni garde ni échéance ; un statut qui ne répond pas empilait une lecture
    par seconde et la page restait figée sans dire « statut perdu ». Une seule lecture en vol, abandonnée à 4 s."""
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed(), "actions": [
        ["eval", "open", "JarvisDossier.open().ok", 900],
        ["eval", "hang", "window.__sc.statusHang=true;1", 6500],
        ["eval", "lost", "JarvisDossier.state().coreLost", 50],
        ["eval", "max", "window.__sc.statusMax||0", 50],
        ["eval", "heal", "window.__sc.statusHang=false;1", 6500],
        ["eval", "back", "JarvisDossier.state().coreLost", 50],
    ]}])[0]
    r = step["results"]
    assert r["max"] == 1, ("one status read in flight at most", r["max"])
    assert r["lost"] is True, "said lost after the 4 s deadline, never frozen on the last state"
    assert r["back"] is False

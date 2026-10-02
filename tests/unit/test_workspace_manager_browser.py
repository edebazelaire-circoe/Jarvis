"""Sessions & Boards dans un vrai Chrome, contre un vrai Core et un vrai Control Center (Slice 07).

Monde semé par les propriétaires canoniques (`tests/unit/test_workspace_inspection_api.build`) :
Sessions (une ouverte, plus de vingt closes), Boards dont un archivé, liaisons,
Contexts, Artefacts liés avec provenance, fichiers de mémoire. Aucun double de
`fetch` : la page servie par `ControlCenter.index` parle au relais
`/api/workspace/*`, qui parle à Core sur SQLite et à la racine de données.

Le parcours : ouvrir `WSP`, parcourir les vues, écrire, renommer puis supprimer
un fichier de mémoire (confirmation dans le panneau), voir les trois lignes
`board.memory.*` dans le journal de la Session, constater qu'un Board archivé
n'offre aucune écriture, lire la provenance d'un artefact. Puis le serveur est
interrogé : fichiers sur disque, lignes du journal (`origin: user`), Board actif
inchangé (aucune activation).

Captures : `tmp_path`, ou le dossier `JARVIS_S7_EVIDENCE_DIR` quand il est donné.
Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil

import pytest

from jarvis.adapters.board_memory_store import FileBoardMemoryStore
from jarvis.domain.board_memory import BoardMemoryPath
from jarvis.ports.board_memory import WriteMode
from tests.fakes.capture_stack import CaptureStack
from tests.unit.test_interaction_mode_hud_browser import _chrome
from tests.unit.test_workspace_inspection_api import build

HARNESS = Path(__file__).parent / "_workspace_browser.mjs"


def _js(value: object) -> str:
    return json.dumps(value)


def _plan(w, open_session: str) -> dict:
    a, arch = w.board_a, w.board_archived
    tab = lambda view: {"do": f"document.getElementById('wsp-tab-{view}').click()"}  # noqa: E731
    panel = "document.getElementById('wspPanel')"
    text = f"{panel}.textContent"
    notice = "(document.querySelector('#wspPanel .wsp-notice')||{textContent:''}).textContent"
    select = lambda sel, value: {"do": f"(()=>{{const s=document.getElementById('{sel}');s.value={_js(value)};"  # noqa: E731
                                       "s.dispatchEvent(new Event('change',{bubbles:true}))})()"}
    form_value = lambda prefix, value: (f"(()=>{{const f=document.querySelector('[id^={prefix}]');"  # noqa: E731
                                        f"f.value={_js(value)};return true}})()")
    submit = "document.querySelector('#wspPanel form[data-form=\"memory-save\"] [type=submit]').click()"
    return {"width": 1440, "height": 900, "steps": [
        {"do": "document.getElementById('openWorkspace').click()"},
        {"wait": f"{text}.includes('Liaison au premier plan')&&{text}.includes('Premier plan')||{text}.includes('Aucune liaison au premier plan')"},
        {"get": "overview", "expr": text},
        {"get": "rank", "expr": "getComputedStyle(document.getElementById('workspaceManager')).zIndex"},
        {"shot": "01-overview.png"},
        tab("sessions"),
        {"wait": f"{text}.includes('Charger la suite')"},
        {"get": "sessions_first", "expr": "document.querySelectorAll('#wspPanel [data-act=session-toggle]').length"},
        {"shot": "02-sessions.png"},
        {"do": "document.querySelector('#wspPanel [data-act=sessions-more]').click()"},
        {"wait": f"{text}.includes('fin de la liste')"},
        {"get": "sessions_all", "expr": "document.querySelectorAll('#wspPanel [data-act=session-toggle]').length"},
        tab("boards"),
        {"wait": f"document.querySelector('#wspPanel [data-act=board-toggle][data-id={a}]')"},
        {"do": f"document.querySelector('#wspPanel [data-act=board-toggle][data-id={a}]').click()"},
        {"wait": f"{text}.includes('Liaisons dans les Sessions')"},
        {"get": "boards", "expr": text},
        {"shot": "03-boards.png"},
        tab("relations"),
        {"wait": f"{text}.includes('Liaison')&&document.querySelector('#wspPanel .wsp-root')"},
        {"shot": "04-relations-session.png"},
        select("wspRelScope", "board"),
        select("wspRelId", a),
        {"do": "document.querySelector('#wspPanel form[data-form=\"relations-pick\"] [type=submit]').click()"},
        {"wait": f"{text}.includes('Artefacts liés')&&{text}.includes('Références legacy')"},
        {"get": "relations_board", "expr": text},
        {"shot": "05-relations-board.png"},
        tab("memory"),
        {"wait": "document.getElementById('wspMemBoard')"},
        select("wspMemBoard", a),
        {"wait": f"document.querySelector('#wspPanel [data-act=memory-open][data-path=\"summary.md\"]')"},
        {"do": "document.querySelector('#wspPanel [data-act=memory-open][data-path=\"summary.md\"]').click()"},
        {"wait": "document.querySelector('#wspPanel .wsp-text')"},
        {"shot": "06-memory-read.png"},
        {"do": "document.querySelector('#wspPanel [data-act=memory-form][data-kind=create]').click()"},
        {"wait": "document.querySelector('[id^=wspFormPath-]')"},
        {"do": form_value("wspFormPath-", "notes/s7-ui.md")},
        {"do": form_value("wspFormContent-", "Écrit depuis Sessions & Boards.\n")},
        {"do": submit},
        {"wait": f"{notice}.includes('créé')"},
        {"get": "written", "expr": notice},
        # Le fichier écrit est relu puis rouvert APRÈS l'avis : on attend sa lecture.
        {"wait": "(document.querySelector('#wspPanel .wsp-text')||{textContent:''}).textContent.includes('Écrit depuis')"},
        {"get": "opened", "expr": "(document.querySelector('#wspPanel .wsp-text')||{textContent:''}).textContent"},
        {"shot": "07-memory-written.png"},
        {"do": "document.querySelector('#wspPanel .wsp-memfile [data-act=memory-form][data-kind=move]').click()"},
        {"wait": "document.querySelector('[id^=wspFormTo-]')"},
        {"do": form_value("wspFormTo-", "notes/s7-renamed.md")},
        {"do": submit},
        {"wait": f"{notice}.includes('→')"},
        {"get": "moved", "expr": notice},
        {"wait": "document.querySelector('#wspPanel .wsp-memfile [data-act=memory-delete-ask][data-path=\"notes/s7-renamed.md\"]')"},
        {"do": "document.querySelector('#wspPanel .wsp-memfile [data-act=memory-delete-ask][data-path=\"notes/s7-renamed.md\"]').click()"},
        {"wait": "document.querySelector('#wspPanel .wsp-confirm')"},
        {"get": "confirm", "expr": "document.querySelector('#wspPanel .wsp-confirm').textContent"},
        {"get": "confirm_focus", "expr": "document.activeElement&&document.activeElement.id"},
        {"get": "confirm_go_bg", "expr": "getComputedStyle(document.getElementById('wspConfirmGo')).backgroundColor"},
        {"shot": "08-memory-confirm-delete.png"},
        {"do": "document.getElementById('wspConfirmGo').click()"},
        {"wait": f"{notice}.includes('supprimé définitivement')"},
        {"get": "deleted", "expr": notice},
        {"get": "tree_after", "expr": "document.querySelector('#wspPanel .wsp-memtree').textContent"},
        {"shot": "09-memory-deleted.png"},
        # Un refus réel du serveur, dit dans le formulaire : créer un fichier qui existe.
        {"do": "document.querySelector('#wspPanel [data-act=memory-form][data-kind=create]').click()"},
        {"wait": "document.querySelector('[id^=wspFormPath-]')"},
        {"do": form_value("wspFormPath-", "summary.md")},
        {"do": form_value("wspFormContent-", "doublon")},
        {"do": submit},
        {"wait": f"{text}.includes('memory_exists · HTTP 409')"},
        {"get": "refused", "expr": "document.querySelector('#wspPanel form[data-form=\"memory-save\"]').textContent"},
        {"shot": "14-memory-refusal.png"},
        {"do": "document.querySelector('#wspPanel [data-act=memory-cancel]').click()"},
        tab("sessions"),
        {"wait": f"document.querySelector('#wspPanel [data-act=session-toggle][data-id={open_session}]')"},
        {"do": f"document.querySelector('#wspPanel [data-act=session-toggle][data-id={open_session}]').click()"},
        {"wait": f"{text}.includes('board.memory.deleted')"},
        {"get": "ledger", "expr": "document.querySelector('#wspPanel .wsp-ledger').textContent"},
        {"do": "document.querySelector('#wspPanel .wsp-ledger tr:last-child').scrollIntoView({block:'center'})"},
        {"shot": "10-session-ledger.png"},
        tab("memory"),
        {"wait": "document.getElementById('wspMemBoard')"},
        select("wspMemBoard", arch),
        {"wait": f"{text}.includes('vieux.md')"},
        {"get": "archived", "expr": panel + ".innerHTML"},
        {"shot": "11-memory-archived-read-only.png"},
        tab("artifacts"),
        select("wspArtScope", "board"),
        select("wspArtId", w.board_b),
        {"do": "document.querySelector('#wspPanel form[data-form=\"artifacts-filter\"] [type=submit]').click()"},
        {"wait": f"document.querySelector('#wspPanel [data-act=artifact-toggle][data-id={w.art_audio}]')"},
        {"do": f"document.querySelector('#wspPanel [data-act=artifact-toggle][data-id={w.art_audio}]').click()"},
        {"wait": f"{text}.includes('Provenance')&&{text}.includes('Boards liés')"},
        {"get": "artifact", "expr": text},
        {"shot": "12-artifacts-provenance.png"},
        {"do": "document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))"},
        {"get": "closed", "expr": "document.getElementById('workspaceManager').hidden"},
    ]}


@pytest.mark.asyncio
async def test_the_manager_reads_writes_moves_and_deletes_memory_against_the_real_stack(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    chrome = _chrome()
    shots = Path(os.environ.get("JARVIS_S7_EVIDENCE_DIR") or tmp_path / "shots")
    shots.mkdir(parents=True, exist_ok=True)
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        # Un historique réaliste : plus d'une page de Sessions.
        for _ in range(21):
            await stack.core.sessions.start_new_session()
        open_session = (await stack.core.sessions.current()).session.jarvis_session_id
        store = FileBoardMemoryStore(stack.data_root)
        store.write(w.board_b, BoardMemoryPath("summary.md"), "# B\nRefonte du tableau de bord\n", mode=WriteMode.CREATE)
        store.write(w.board_b, BoardMemoryPath("decisions/2026-10.md"), "- garder le thème sombre\n", mode=WriteMode.CREATE)
        # Les routes `/api/boards*` relaient vers ce Core (la pile de capture ne les branche pas).
        stack.center.board_routes._transport = stack.sessions
        active_before = (await stack.call("GET", "/api/boards/active"))[1]

        proc = await asyncio.create_subprocess_exec(
            node, str(HARNESS), f"http://127.0.0.1:{stack.cc_port}/", chrome, json.dumps(_plan(w, open_session)), str(shots),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=240)
        assert proc.returncode == 0, err.decode("utf-8", "replace")
        seen = json.loads(out.decode("utf-8"))

        memory = stack.data_root / "boards" / w.board_a / "memory" / "notes"
        assert not (memory / "s7-ui.md").exists() and not (memory / "s7-renamed.md").exists()
        events = (await stack.call("GET", f"/api/workspace/sessions/{open_session}/activity?limit=100"))[1]["events"]
        rows = [(e["kind"], e["data"].get("path") or e["data"].get("to"), e["data"]["origin"])
                for e in events if e["kind"].startswith("board.memory.")]
        assert rows == [("board.memory.written", "notes/s7-ui.md", "user"),
                        ("board.memory.moved", "notes/s7-renamed.md", "user"),
                        ("board.memory.deleted", "notes/s7-renamed.md", "user")]
        assert (await stack.call("GET", "/api/boards/active"))[1] == active_before, "nothing was activated"

    r = seen["results"]
    assert r["rank"] == "55"
    assert "Projet B" in r["overview"] and open_session in r["overview"] and "Context actif" in r["overview"]
    assert r["sessions_first"] == 20 and r["sessions_all"] == 23
    assert "Références héritées (legacy)" in r["boards"] and "Réunion" in r["boards"]
    assert "Artefacts liés" in r["relations_board"]
    assert "notes/s7-ui.md" in r["written"] and "journal n°" in r["written"]
    assert r["opened"] == "Écrit depuis Sessions & Boards.\n"
    assert "notes/s7-ui.md" in r["moved"] and "notes/s7-renamed.md" in r["moved"]
    assert "notes/s7-renamed.md" in r["confirm"] and "Projet A" in r["confirm"] and "pas de corbeille" in r["confirm"]
    assert r["confirm_focus"] == "wspConfirmCancel", "the safe choice has the focus"
    assert r["confirm_go_bg"] == "rgb(255, 101, 119)", "the destructive button is the solid danger colour"
    assert "supprimé définitivement" in r["deleted"] and "s7-renamed" not in r["tree_after"]
    assert "Un élément porte déjà ce nom" in r["refused"] and "summary.md" in r["refused"]
    for kind in ("board.memory.written", "board.memory.moved", "board.memory.deleted"):
        assert kind in r["ledger"], kind
    assert "Board archivé : mémoire en lecture seule." in r["archived"]
    assert 'data-act="memory-form"' not in r["archived"] and 'data-act="memory-delete-ask"' not in r["archived"]
    assert "derived_from" in r["artifact"] or "Aucune relation" in r["artifact"]
    assert "Lien explicite" in r["artifact"]
    assert r["closed"] is True
    taken = {k[5:] for k in r if k.startswith("shot:")}
    assert len(taken) == 13 and taken <= {p.name for p in shots.glob("*.png")}
    refusal = [line for line in seen["console"] if "workspace.memory_mutation_failed" in line["text"]]
    assert len(refusal) == 1 and '"code":"memory_exists"' in refusal[0]["text"], "the forced refusal is logged, once"
    bad = [line for line in seen["console"] if line["type"] == "exception"
           or (line["type"] == "error" and "[workspace]" in line["text"] and line not in refusal)]
    assert bad == [], bad


@pytest.mark.asyncio
async def test_on_a_narrow_screen_the_memory_view_stacks_without_horizontal_scroll(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    chrome = _chrome()
    shots = Path(os.environ.get("JARVIS_S7_EVIDENCE_DIR") or tmp_path / "shots")
    shots.mkdir(parents=True, exist_ok=True)
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        stack.center.board_routes._transport = stack.sessions
        a = w.board_a
        plan = {"width": 700, "height": 900, "steps": [
            {"do": "document.getElementById('openWorkspace').click()"},
            {"wait": "document.getElementById('wsp-tab-memory')"},
            {"do": "document.getElementById('wsp-tab-memory').click()"},
            {"wait": "document.getElementById('wspMemBoard')"},
            {"do": f"(()=>{{const s=document.getElementById('wspMemBoard');s.value='{a}';s.dispatchEvent(new Event('change',{{bubbles:true}}))}})()"},
            {"wait": "document.querySelector('#wspPanel [data-act=memory-open][data-path=\"notes/plan.md\"]')"},
            {"do": "document.querySelector('#wspPanel [data-act=memory-open][data-path=\"notes/plan.md\"]').click()"},
            {"wait": "document.querySelector('#wspPanel .wsp-memfile [data-act=memory-delete-ask]')"},
            {"do": "document.querySelector('#wspPanel .wsp-memfile [data-act=memory-delete-ask]').click()"},
            {"wait": "document.querySelector('#wspPanel .wsp-confirm')"},
            {"get": "overflow", "expr": "(()=>{const p=document.getElementById('wspPanel');return p.scrollWidth-p.clientWidth})()"},
            {"get": "stacked", "expr": "(()=>{const t=document.querySelector('.wsp-memtree').getBoundingClientRect(),"
                                       "f=document.querySelector('.wsp-memfile').getBoundingClientRect();return f.top>=t.bottom})()"},
            {"shot": "13-narrow-memory-confirm.png"},
        ]}
        proc = await asyncio.create_subprocess_exec(
            node, str(HARNESS), f"http://127.0.0.1:{stack.cc_port}/", chrome, json.dumps(plan), str(shots),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=120)
        assert proc.returncode == 0, err.decode("utf-8", "replace")
        r = json.loads(out.decode("utf-8"))["results"]
        assert stack.data_root.joinpath("boards", a, "memory", "notes", "plan.md").exists(), "asking deleted nothing"
    assert r["overflow"] <= 0, "no horizontal scroll"
    assert r["stacked"] is True

"""La carte « Présentations · moteur » dans la VRAIE page du Control Center, un VRAI Chrome sans tête, un Core isolé (Slice 20).

Core réel + serveur de protocole réel + `ControlCenter` réel, sur des ports libres et une racine de données jetable (jamais le JARVIS
vivant). Chrome pilote la page : créer avec Remotion (rien d'autre que le titre n'est envoyé), refuser puis accepter la confirmation
Slidecar (le corps porte `engine` + `experimental_confirmed`, jamais d'acteur : le relais le pose), dupliquer en expérience (nouveau
document, source intacte), le badge du moteur dans la liste, le diagnostic d'un Remotion qui ne peut pas jouer (aucun repli), la
persistance après rechargement, et la tenue à 390 px.

Opt-in comme les autres épreuves de page : se saute sans Chrome ou sans node.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil

import pytest

from tests.unit.test_presentation_studio_engine_human import World

HARNESS = Path(__file__).parent / "_studio_engine_browser.mjs"
CHROME = next((Path(p) for p in (
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe") if Path(p).is_file()), None)
NODE = shutil.which("node")
EVIDENCE = os.environ.get("JARVIS_ENGINE_UI_EVIDENCE")  # a directory: screenshots and the measured JSON are copied there

pytestmark = [pytest.mark.engine_gate, pytest.mark.skipif(CHROME is None or NODE is None, reason="needs Chrome and node")]

OPEN = "(JarvisMcpInspector.open(),document.getElementById('mcpViewPlugins').click(),true)"
TEXT = lambda css: f"(document.querySelector({json.dumps(css)})||{{textContent:null}}).textContent"  # noqa: E731
ROWS = ("Array.from(document.querySelectorAll('#sveList .sve-row')).map(r=>({title:r.querySelector('.sve-title').textContent,"
        "engine:r.dataset.engine,badge:r.querySelector('.chip').textContent,copy:!!r.querySelector('[data-copy]')}))")
CONFIRM_OPEN = "!document.getElementById('confirmBack').hidden"


async def drive(url: str, plan: list[dict], tmp_path: Path) -> dict:
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    process = await asyncio.create_subprocess_exec(NODE, str(HARNESS), url, str(CHROME), str(plan_file),
                                                   stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(process.communicate(), timeout=150)
    except asyncio.TimeoutError:
        process.kill()
        raise
    assert process.returncode == 0, err.decode("utf-8", "replace")[-1500:]
    return json.loads(out.decode("utf-8"))


def posts(result: dict) -> list[dict]:
    return [{**row, "json": json.loads(row["body"]) if row["body"] else None} for row in result["network"] if row["method"] == "POST"]


async def test_the_human_flow_in_the_real_page(tmp_path):
    async with World(tmp_path) as world:
        shot_main, shot_confirm, shot_narrow = (str(tmp_path / n) for n in ("engine_card.png", "engine_confirm.png", "engine_card_390.png"))
        url = str(world.cc.make_url("/"))
        result = await drive(url, [
            {"nav": True}, {"viewport": [1280, 900]},
            {"read": "opened", "expr": OPEN},
            {"until": "!!document.querySelector('#sveCard .sve-card')", "ms": 8000},
            {"until": f"{TEXT('#sveRemotion')}.includes('Indisponible')", "ms": 10000},
            # --- initial reading: Remotion by default, its real failure diagnosed, no Slidecar anywhere, no fallback said otherwise
            {"read": "chips", "expr": f"[{TEXT('#sveDefault')},{TEXT('#sveRemotion')},{TEXT('#sveSlidecar')}]"},
            {"read": "diag", "expr": TEXT("#sveDiag")},
            {"read": "diag_action", "expr": "!!document.querySelector('#sveRepairGo')"},
            {"read": "warn_visible_when_closed", "expr": "document.querySelector('#sveWarn').checkVisibility()"},
            {"shot": shot_main},
            # --- create with Remotion: the body is only the title
            {"type": "#sveTitleInput", "text": "Plan Remotion"},
            {"click": "#sveCreate"},
            {"until": "document.querySelectorAll('#sveList .sve-row').length===1", "ms": 8000},
            {"read": "after_remotion", "expr": ROWS},
            # --- Slidecar: open the experimental area, the warning is visible, cancel creates nothing
            {"type": "#sveTitleInput", "text": "Essai Slidecar"},
            {"click": "#sveExp summary"},
            {"read": "warn_visible_when_open", "expr": "document.querySelector('#sveWarn').checkVisibility()"},
            {"read": "warn_text", "expr": TEXT("#sveWarn")},
            {"type": "#sveReason", "text": "comparer le rendu"},
            {"click": "#sveCreateSlidecar"},
            {"until": CONFIRM_OPEN, "ms": 4000},
            {"read": "confirm_title", "expr": TEXT("#confirmTitle")},
            {"read": "confirm_text", "expr": TEXT("#confirmBody")},
            {"shot": shot_confirm},
            {"click": "#confirmCancel"},
            {"wait": 400},
            {"read": "after_cancel", "expr": ROWS},
            # --- confirm: created, journaled, badge says experimental
            {"click": "#sveCreateSlidecar"},
            {"until": CONFIRM_OPEN, "ms": 4000},
            {"click": "#confirmGo"},
            {"until": "document.querySelectorAll('#sveList .sve-row').length===2", "ms": 8000},
            {"read": "after_slidecar", "expr": ROWS},
            {"until": f"{TEXT('#sveSlidecar')}.includes('1 document')", "ms": 8000},
            {"read": "slidecar_chip", "expr": TEXT("#sveSlidecar")},
            # --- duplicate as a Slidecar experiment: a new document, confirmation first
            {"click": "#sveList .sve-row[data-engine=remotion] [data-copy]"},
            {"until": CONFIRM_OPEN, "ms": 4000},
            {"read": "copy_confirm", "expr": TEXT("#confirmBody")},
            {"click": "#confirmGo"},
            {"until": "document.querySelectorAll('#sveList .sve-row').length===3", "ms": 8000},
            {"read": "after_copy", "expr": ROWS},
            {"click": "#sveLog summary"},
            {"read": "journal", "expr": "Array.from(document.querySelectorAll('#sveLog .sve-events li')).map(l=>l.textContent)"},
            {"read": "journal_title", "expr": TEXT("#sveLog summary")},
            # --- reload: the engine of each document is durable, the badges are the same
            {"nav": True},
            {"read": "opened2", "expr": OPEN},
            {"until": "document.querySelectorAll('#sveList .sve-row').length===3", "ms": 10000},
            {"read": "after_reload", "expr": ROWS},
            # --- narrow
            {"viewport": [390, 900]}, {"wait": 300},
            {"read": "narrow", "expr": "(()=>{const c=document.querySelector('#sveCard .sve-card');const r=c.getBoundingClientRect();"
                                       "return {fits:c.scrollWidth<=c.clientWidth+1,left:r.left,right:r.right,vw:innerWidth}})()"},
            {"shot": shot_narrow},
        ], tmp_path)
        reads = result["reads"]
        assert reads["opened"] is True
        # initial state: Remotion default and not ready, with its real reason; no Slidecar; nothing offered as a replacement
        assert reads["chips"][0] == "Défaut : Remotion" and "Indisponible" in reads["chips"][1] and "0 document" in reads["chips"][2]
        assert "Raison" in reads["diag"] and "Remotion" in reads["diag"] and "Aucune présentation Slidecar n’est affichée à la place" in reads["diag"]
        assert reads["diag_action"] is False, "a Core without a Remotion adapter cannot be repaired from the page"
        assert reads["warn_visible_when_closed"] is False and reads["warn_visible_when_open"] is True
        assert "expérimental" in reads["warn_text"].lower() and "Aucun repli" in reads["warn_text"]
        # Remotion creation: exactly the title, no engine, no actor
        created = [p for p in posts(result) if p["url"].endswith("/api/presentation-studio/presentations")]
        assert created[0]["json"] == {"title": "Plan Remotion"}
        assert reads["after_remotion"] == [{"title": "Plan Remotion", "engine": "remotion", "badge": "Remotion", "copy": True}]
        # the confirmation: shown, read, cancelled creates nothing and sends nothing
        assert "Slidecar" in reads["confirm_title"] and "expérimental" in reads["confirm_title"]
        assert "Aucun repli" in reads["confirm_text"] and "journal" in reads["confirm_text"]
        assert len(reads["after_cancel"]) == 1 and len(created) == 2, "the cancelled confirmation sent nothing (1 Remotion + 1 confirmed Slidecar)"
        assert created[1]["json"] == {"title": "Essai Slidecar", "engine": "slidecar", "experimental_confirmed": True,
                                      "reason": "comparer le rendu"}
        assert all("actor" not in (p["json"] or {}) for p in posts(result)), "the page never names an actor: the relay does"
        slidecar = [r for r in reads["after_slidecar"] if r["engine"] == "slidecar"]
        assert slidecar == [{"title": "Essai Slidecar", "engine": "slidecar", "badge": "Slidecar · expérimental", "copy": False}]
        assert reads["slidecar_chip"].startswith("Slidecar : 1 document")
        # copy: confirmation text says the source is untouched; a third document, Slidecar, derived title
        assert "n’est pas modifiée" in reads["copy_confirm"]
        assert sorted((r["title"], r["engine"]) for r in reads["after_copy"]) == sorted([
            ("Essai Slidecar", "slidecar"), ("Plan Remotion (Slidecar)", "slidecar"), ("Plan Remotion", "remotion")])
        experiment = [p for p in posts(result) if p["url"].endswith("/experiment")]
        assert len(experiment) == 1 and experiment[0]["json"] == {"experimental_confirmed": True}
        kinds = " ".join(reads["journal"])
        assert "Création" in kinds and "Copie « expérience »" in kinds and "acteur : vous" in kinds and "comparer le rendu" in kinds
        assert "(2)" in reads["journal_title"]
        # persistence: same documents, same badges after a full reload
        assert sorted((r["title"], r["engine"], r["badge"]) for r in reads["after_reload"]) == sorted(
            (r["title"], r["engine"], r["badge"]) for r in reads["after_copy"])
        # narrow: the card stays inside the viewport
        assert reads["narrow"]["fits"] is True and reads["narrow"]["left"] >= 0 and reads["narrow"]["right"] <= reads["narrow"]["vw"] + 1
        # no console error from the page code (a failed /api/status of the bare test world is not one of ours)
        ours = [line for line in result["console"] if "studio-engine" in line and line.startswith(("error", "exception"))]
        assert ours == [], ours
        # Core side: three documents, two Slidecar, the diagnostics journal says who and why
        listing = (await world.core_call("GET", "/v1/presentation-studio/presentations"))[1]["presentations"]
        assert sorted(row["engine"] for row in listing) == ["remotion", "slidecar", "slidecar"]
        assert len(world.sink.of(".slidecar_created")) == 1 and len(world.sink.of(".slidecar_experiment_created")) == 1
        assert {row["data"]["actor"] for row in world.sink.of(".slidecar_created")} == {"human"}
        if EVIDENCE:
            Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
            for shot in (shot_main, shot_confirm, shot_narrow):
                shutil.copyfile(shot, Path(EVIDENCE) / Path(shot).name)
            (Path(EVIDENCE) / "ui_engine_flow.json").write_text(json.dumps(
                {"reads": reads, "posts": posts(result), "core_listing": listing,
                 "core_events": [row for row in world.sink.rows if "slidecar" in row["kind"] or "engine_" in row["kind"]]},
                ensure_ascii=False, indent=2), encoding="utf-8")


async def test_a_broken_remotion_is_diagnosed_and_repaired_from_the_page_without_ever_showing_slidecar(tmp_path):
    from tests.unit.test_local_capability_host import FakeRunner
    runner = FakeRunner()
    async with World(tmp_path, capability_runner=runner) as world:
        shot_missing, shot_failed, shot_ok = (str(tmp_path / n) for n in ("repair_missing.png", "repair_failed.png", "repair_done.png"))
        CHIPS = f"[{TEXT('#sveRemotion')},{TEXT('#sveDiag')},{TEXT('#sveRepairGo')}]"
        # step 1: not installed -> guidance + one button; cancelling the confirmation sends nothing
        first = await drive(str(world.cc.make_url("/")), [
            {"nav": True}, {"viewport": [1280, 900]}, {"read": "opened", "expr": OPEN},
            {"until": f"{TEXT('#sveDiag')}&&{TEXT('#sveDiag')}.includes('pas installé')", "ms": 12000},
            {"read": "missing", "expr": CHIPS},
            {"shot": shot_missing},
            {"click": "#sveRepairGo"}, {"until": CONFIRM_OPEN, "ms": 4000},
            {"read": "confirm", "expr": TEXT("#confirmBody")}, {"read": "confirm_title", "expr": TEXT("#confirmTitle")},
            {"click": "#confirmCancel"}, {"wait": 300},
            {"read": "after_cancel", "expr": CHIPS},
        ], tmp_path)
        assert "Indisponible" in first["reads"]["missing"][0] and first["reads"]["missing"][2] == "Installer Remotion"
        assert "270 Mo" in first["reads"]["missing"][1] and "Aucune présentation Slidecar n’est affichée à la place" in first["reads"]["missing"][1]
        assert "Installer Remotion" in first["reads"]["confirm_title"] and "Aucun repli" in first["reads"]["confirm"]
        assert [p for p in first["network"] if "/install" in p["url"] or "/repair" in p["url"]] == [], "cancel sends nothing"
        assert runner.calls == []

        runner.install_error = RuntimeError("npm ERR! network unreachable")
        second = await drive(str(world.cc.make_url("/")), [
            {"nav": True}, {"viewport": [1280, 900]}, {"read": "opened", "expr": OPEN},
            {"until": f"{TEXT('#sveRepairGo')}==='Installer Remotion'", "ms": 12000},
            {"click": "#sveRepairGo"}, {"until": CONFIRM_OPEN, "ms": 4000}, {"click": "#confirmGo"},
            {"until": f"{TEXT('#sveRepairGo')}==='Réparer Remotion'", "ms": 12000},
            {"read": "failed", "expr": CHIPS},
            {"shot": shot_failed},
        ], tmp_path)
        failed = second["reads"]["failed"]
        installs = [p for p in second["network"] if p["method"] == "POST" and p["url"].endswith("/remotion/install")]
        assert len(installs) == 1 and json.loads(installs[0]["body"] or "{}") == {}, "the page sends no parameter"
        assert "L’installation de Remotion a échoué" in failed[1] and "local_capability_install_failed" in failed[1] and "network" in failed[1]
        assert "Indisponible" in failed[0]

        runner.install_error = None
        third = await drive(str(world.cc.make_url("/")), [
            {"nav": True}, {"viewport": [1280, 900]}, {"read": "opened", "expr": OPEN},
            {"until": f"{TEXT('#sveRepairGo')}==='Réparer Remotion'", "ms": 12000},
            {"click": "#sveRepairGo"}, {"until": CONFIRM_OPEN, "ms": 4000},
            {"read": "confirm_title", "expr": TEXT("#confirmTitle")}, {"click": "#confirmGo"},
            {"until": "!document.querySelector('#sveDiag')", "ms": 15000},
            {"read": "after", "expr": CHIPS}, {"read": "list", "expr": ROWS},
            {"shot": shot_ok},
        ], tmp_path)
        assert "Réparer l’environnement Remotion" in third["reads"]["confirm_title"]
        assert any(p["url"].endswith("/remotion/repair") for p in third["network"] if p["method"] == "POST")
        assert "Prêt" in third["reads"]["after"][0]
        assert third["reads"]["list"] == [] and not [r for r in world.sink.rows if r["kind"].endswith("slidecar_used")]
        # the only console error the page may log is its own record of the scripted install failure (the visible failure is logged, not hidden)
        ours = [line for r in (first, second, third) for line in r["console"] if "studio-engine" in line and line.startswith(("error", "exception"))]
        assert all("action_failed" in line for line in ours), ours
        if EVIDENCE:
            Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
            for shot in (shot_missing, shot_failed, shot_ok):
                shutil.copyfile(shot, Path(EVIDENCE) / Path(shot).name)


async def test_hostile_text_is_inert_unreadable_documents_are_visible_and_a_double_click_acts_once(tmp_path):
    """QA F3 (problems are rows, not dropped), the dynamic XSS check (titles, reasons, journal, problems) and the double-dialog / double-submit guard."""

    async with World(tmp_path) as world:
        evil_title = '<img src=x onerror="window.__xss=1">'
        evil_reason = '"><script>window.__xss=2</script><b id="pwn">x</b>'
        status, made = await world.core_call("POST", "/v1/presentation-studio/presentations",
                                             json={"title": evil_title, "engine": "slidecar", "actor": "user",
                                                   "experimental_confirmed": True, "reason": evil_reason})
        assert status == 201
        _, broken = await world.core_call("POST", "/v1/presentation-studio/presentations", json={"title": "Cassée"})
        manifest = world.manifest(broken["presentation"]["presentation_id"])
        document = json.loads(manifest.read_text(encoding="utf-8"))
        document["engine"] = "powerpoint"
        manifest.write_text(json.dumps(document), encoding="utf-8")
        before = manifest.read_bytes()
        result = await drive(str(world.cc.make_url("/")), [
            {"nav": True}, {"viewport": [1280, 900]}, {"read": "opened", "expr": OPEN},
            {"until": "document.querySelectorAll('#sveList .sve-row').length===1", "ms": 10000},
            {"click": "#sveLog summary"},
            {"read": "rows", "expr": ROWS},
            {"read": "problems", "expr": "Array.from(document.querySelectorAll('#sveProblems .sve-problem')).map(r=>r.textContent)"},
            {"read": "journal", "expr": "Array.from(document.querySelectorAll('#sveLog .sve-events li')).map(l=>l.textContent)"},
            {"read": "inert", "expr": "({xss:window.__xss===undefined,pwn:!document.getElementById('pwn'),"
                                      "img:!document.querySelector('#sveCard img'),script:!document.querySelector('#sveCard script'),"
                                      "titleLiteral:document.querySelector('#sveList .sve-title').textContent})"},
            {"shot": str(tmp_path / "hostile.png")},
            # double click on the Slidecar button: ONE dialog, ONE request
            {"type": "#sveTitleInput", "text": "Double"},
            {"click": "#sveExp summary"},
            {"read": "dbl", "expr": "(()=>{const b=document.getElementById('sveCreateSlidecar');b.click();b.click();b.click();"
                                    "return {open:!document.getElementById('confirmBack').hidden,confirming:JarvisStudioEngine.state.confirming}})()"},
            {"click": "#confirmGo"},
            {"until": "document.querySelectorAll('#sveList .sve-row').length===2", "ms": 8000},
            # double submit of the Remotion form: ONE request
            {"type": "#sveTitleInput", "text": "Un seul"},
            {"read": "dbl_submit", "expr": "(()=>{const f=document.getElementById('sveNew');f.requestSubmit();f.requestSubmit();return true})()"},
            {"until": "document.querySelectorAll('#sveList .sve-row').length===3", "ms": 8000},
            {"wait": 500},
            {"read": "final_rows", "expr": ROWS},
        ], tmp_path)
        reads = result["reads"]
        assert reads["rows"][0]["title"] == evil_title and reads["rows"][0]["engine"] == "slidecar"
        assert len(reads["problems"]) == 1 and "Document illisible" in reads["problems"][0] and "engine must be one of" in reads["problems"][0]
        assert reads["inert"] == {"xss": True, "pwn": True, "img": True, "script": True, "titleLiteral": evil_title}
        assert any(evil_reason in line for line in reads["journal"]), "the hostile reason is shown as text"
        assert reads["dbl"] == {"open": True, "confirming": True}
        created = [p["json"] for p in posts(result) if p["url"].endswith("/api/presentation-studio/presentations")]
        assert [c["title"] for c in created] == ["Double", "Un seul"], created
        assert len(reads["final_rows"]) == 3
        assert manifest.read_bytes() == before, "an unreadable document is shown, never modified or converted"
        assert result["reads"]["opened"] is True


async def test_the_card_speaks_french_about_the_adapter_reason_and_keeps_the_technical_text(tmp_path):
    async with World(tmp_path) as world:
        result = await drive(str(world.cc.make_url("/")), [
            {"nav": True}, {"viewport": [1280, 900]}, {"read": "opened", "expr": OPEN},
            {"until": f"{TEXT('#sveDiag')}&&{TEXT('#sveDiag')}.includes('Raison')", "ms": 12000},
            {"read": "diag", "expr": "Array.from(document.querySelectorAll('#sveDiag code')).map(c=>c.textContent)"},
            {"read": "text", "expr": TEXT("#sveDiag")},
        ], tmp_path)
        assert "ce Core n’a pas d’adaptateur Remotion" in result["reads"]["text"]
        assert any("no Remotion adapter" in code for code in result["reads"]["diag"]), "the technical reason stays visible"

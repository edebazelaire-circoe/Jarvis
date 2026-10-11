"""Le rail des presentations de bout en bout : VRAI Core (racine de donnees et ports a lui), VRAI Control Center (relais), VRAI Chrome.

Aucun double : la liste vient de `GET /api/presentation-studio/rail` relaye vers Core, les gestes (masquer, archiver, renommer) ecrivent
`rail.json` dans le vrai magasin de fichiers, la pastille bleue / orange est l'etat de travail de Core (pose par la porte du cerveau,
`POST .../work`), la fenetre monte le vrai prefab (`lab.dial`) dans un cadre sandboxe, le Studio est le vrai explorateur de variantes.
Banc : `tests/fakes/presentation_studio_inspector_browser.py`. Contrat : `docs/presentation-studio.md` > *Rail des presentations*.
"""

from __future__ import annotations

import json

import pytest

from tests.fakes.presentation_studio_inspector_browser import InspectorRig, drive
from tests.unit.test_control_center_presentation_rail_browser import BLUE, GREEN, ORANGE
from tests.unit.test_presentation_studio_playback_routes import score

pytestmark = pytest.mark.asyncio

ITEMS = "[...document.querySelectorAll('#presentationRail .jvr-item')].map(b=>[b.querySelector('.jvr-name').textContent,b.dataset.state,getComputedStyle(b.querySelector('.jvr-dot')).backgroundColor])"
CONTEXT = "document.querySelector('#presentationRail .jvr-item[data-id=\"%s\"]').dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:120,clientY:130}))"
HTTP_REFUSAL = "Failed to load resource: the server responded with a status of 4"


def noise(result: dict) -> list:
    lines = [c for c in result["console"] if c["type"] in ("error", "warning", "exception", "log-error", "log-warning", "assert")
             and "favicon.ico" not in c["text"] and HTTP_REFUSAL not in c["text"]]
    return result["errors"] + lines


async def test_the_rail_lists_real_presentations_with_their_real_work_state_and_the_gestures_write_the_store(tmp_path):
    async with InspectorRig(tmp_path) as rig:
        core = rig.core
        pid2, vid2, _ = await rig.new_presentation("Bilan trimestriel")
        pid3, _, _ = await rig.new_presentation("Roadmap produit")
        pid4, _, _ = await rig.new_presentation("Ancienne version")
        # a second variant on the first presentation: the Studio's variant bar needs two
        status, branch = await core.call("POST", f"/{rig.pid}/variants", json={"title": "Autre ton", "actor": "user"})
        assert status == 201, branch
        # the agent works on #2 and failed on #3; #4 is archived
        await core.client.presentation_studio_work(pid2, {"event": "begin", "label": "presentation_edit"})
        await core.client.presentation_studio_work(pid3, {"event": "failure", "code": "presentation_studio_storage_io", "message": "disque plein"})
        await core.client.presentation_studio_rail_act(pid4, {"action": "archive", "actor": "user"})

        result = await drive(rig.url, [
            {"until": "!!window.JarvisPresentationRail", "ms": 20000},
            {"eval": "JarvisPresentationRail.setPref('shown')"},
            {"until": "JarvisPresentationRail.state().loaded===true&&document.querySelectorAll('#presentationRail .jvr-item').length>=3", "ms": 20000},
            {"value": "items", "expr": ITEMS},
            {"value": "folds", "expr": "[...document.querySelectorAll('#presentationRail .jvr-fold')].map(b=>b.textContent.trim())"},
            {"value": "palette", "expr": "(()=>{const a=document.querySelector('#barehandsPalette').getBoundingClientRect(),b=document.querySelector('#presentationRail').getBoundingClientRect();return [a.right,b.left]})()"},
            {"shot": str(tmp_path / "rail.png")},
            # hide Roadmap through the real context menu and the real relay
            {"eval": CONTEXT % pid3},
            {"until": "!!document.querySelector('.jvr-menu:not([hidden])')", "ms": 5000},
            {"value": "menu", "expr": "[...document.querySelectorAll('.jvr-menu button')].map(b=>b.dataset.act)"},
            {"click": ".jvr-menu button[data-act=\"hide\"]"},
            {"until": "document.querySelectorAll('#presentationRail .jvr-item').length===2", "ms": 8000},
            {"value": "after_hide", "expr": ITEMS},
            # open the window on the first presentation: the real prefab is mounted in a sandboxed frame
            {"eval": f"document.querySelector('#presentationRail .jvr-item[data-id=\"{rig.pid}\"]').click()"},
            {"until": "!!document.querySelector('#jvPresWindow:not([hidden]) .jvw-pip')", "ms": 15000},
            {"value": "window", "expr": "(()=>{const w=document.querySelector('#jvPresWindow');return {title:w.querySelector('.jvw-title').textContent,pips:w.querySelectorAll('.jvw-pip').length,chip:w.querySelector('.jvw-chip').textContent,veil:w.querySelector('.jvw-veil').hidden,frames:w.querySelectorAll('iframe').length}})()"},
            {"shot": str(tmp_path / "window.png")},
            # the Studio from the menu: windowed, rail docked, variant bar, play buttons
            {"click": "#jvPresWindow .jvw-bar button:nth-of-type(3)"},
            {"until": "!!window.JarvisStudioExplorer&&JarvisStudioExplorer.isOpen&&JarvisStudioExplorer.isOpen()", "ms": 15000},
            {"until": "document.querySelectorAll('#jvStudioExplorer .jvx-vchip').length===2", "ms": 15000},
            {"wait": 500},
            {"value": "studio", "expr": "(()=>{const r=document.querySelector('#presentationRail').getBoundingClientRect(),x=document.querySelector('#jvStudioExplorer').getBoundingClientRect();return {docked:document.documentElement.classList.contains('jvr-studio'),railLeft:r.left,railTop:r.top,explorerLeft:x.left,railInert:!!document.querySelector('#presentationRail').closest('[inert]'),chips:document.querySelectorAll('#jvStudioExplorer .jvx-vchip').length,play:[...document.querySelectorAll('#jvStudioExplorer .jvx-play button')].map(b=>b.textContent.trim()),windowOpen:!document.querySelector('#jvPresWindow').hidden,fullscreen:!!document.fullscreenElement}})()"},
            {"shot": str(tmp_path / "studio.png")},
            # the rail stays usable inside the Studio: its menu opens above it
            {"eval": CONTEXT % pid2},
            {"until": "!!document.querySelector('.jvr-menu:not([hidden])')", "ms": 5000},
            {"value": "studio_menu", "expr": "(()=>{const m=document.querySelector('.jvr-menu').getBoundingClientRect();const top=document.elementFromPoint(m.left+20,m.top+20);return {onTop:!!top&&!!top.closest('.jvr-menu'),z:getComputedStyle(document.querySelector('.jvr-menu')).zIndex}})()"},
            {"key": "Escape"},
            {"value": "studio_still_open", "expr": "JarvisStudioExplorer.isOpen()"},
            # variant bar: ] steps to the other variant
            {"eval": "document.querySelector('#jvStudioExplorer').dispatchEvent(new KeyboardEvent('keydown',{key:']',bubbles:true,cancelable:true}))"},
            {"wait": 600},
            {"value": "stepped", "expr": "[...document.querySelectorAll('#jvStudioExplorer .jvx-vchip')].map(b=>b.getAttribute('aria-pressed'))"},
        ], viewport="1440x900", timeout=300)
        reads = result["reads"]
        assert [i[0] for i in reads["items"]] == ["Atelier du cadran", "Bilan trimestriel", "Roadmap produit"] or sorted(i[0] for i in reads["items"]) == sorted(["Atelier du cadran", "Bilan trimestriel", "Roadmap produit"])
        by_name = {name: (state, color) for name, state, color in reads["items"]}
        assert by_name["Bilan trimestriel"] == ("working", BLUE), "real work state from Core: the agent is working"
        assert by_name["Roadmap produit"] == ("problem", ORANGE), "real failure from Core"
        assert by_name["Atelier du cadran"] == ("done", GREEN)
        assert [f.replace(" ", "") for f in reads["folds"]] == ["▸Archivées(1)"]
        assert reads["palette"][1] > reads["palette"][0], "right of the tool palette"
        assert reads["menu"] == ["open", "studio", "edit", "play", "hide", "rename", "ack", "archive"]
        assert sorted(i[0] for i in reads["after_hide"]) == ["Atelier du cadran", "Bilan trimestriel"]
        assert reads["window"]["title"] == "Atelier du cadran" and reads["window"]["pips"] == 3 and reads["window"]["chip"].startswith("variante #")
        assert reads["studio"]["docked"] is True and reads["studio"]["railLeft"] == 8 and reads["studio"]["explorerLeft"] > 150
        assert reads["studio"]["railInert"] is False and reads["studio"]["chips"] == 2 and reads["studio"]["fullscreen"] is False
        assert reads["studio"]["play"] == ["Jouer cette slide", "Lire"] and reads["studio"]["windowOpen"] is False
        assert reads["studio_menu"]["onTop"] is True and reads["studio_still_open"] is True, "Escape in the rail menu does not close the Studio"
        assert sorted(reads["stepped"]) == ["false", "true"]
        assert not noise(result), noise(result)

        # what the page wrote is in the real store, beside the manifest, and the manifest did not move
        rail_file = tmp_path / "data" / "presentations" / pid3 / "rail.json"
        assert json.loads(rail_file.read_text(encoding="utf-8"))["hidden"] is True
        status, view = await core.call("GET", f"/{pid3}")
        assert status == 200 and view["presentation"]["revision"] == 1 and view["presentation"]["schema_version"] == 3
        assert json.loads((tmp_path / "data" / "presentations" / pid4 / "rail.json").read_text(encoding="utf-8"))["archived"] is True
        listing = await core.client.presentation_studio_rail()
        rows = {r["title"]: r for r in listing["presentations"]}
        assert rows["Roadmap produit"]["hidden"] is True and rows["Ancienne version"]["archived"] is True


async def test_archive_confirm_rename_and_restore_through_the_real_page(tmp_path):
    async with InspectorRig(tmp_path) as rig:
        core = rig.core
        pid2, _, _ = await rig.new_presentation("A supprimer")
        result = await drive(rig.url, [
            {"until": "!!window.JarvisPresentationRail", "ms": 20000},
            {"eval": "JarvisPresentationRail.setPref('shown')"},
            {"until": "document.querySelectorAll('#presentationRail .jvr-item').length===2", "ms": 20000},
            {"eval": CONTEXT % pid2},
            {"until": "!!document.querySelector('.jvr-menu:not([hidden])')", "ms": 5000},
            {"click": ".jvr-menu button[data-act=\"archive\"]"},
            {"until": "!!document.querySelector('.jvr-dialog-back:not([hidden]) .jvr-dialog')", "ms": 5000},
            {"value": "dialog", "expr": "document.querySelector('.jvr-dialog').textContent"},
            {"click": ".jvr-dialog button[data-danger]"},
            {"until": "document.querySelectorAll('#presentationRail .jvr-item').length===1", "ms": 8000},
            {"click": "#presentationRail .jvr-fold"},
            {"value": "archived", "expr": ITEMS},
            # an archived row offers only "restore"
            {"eval": "document.querySelector('#presentationRail .jvr-item[data-dim=\"true\"]').dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:120,clientY:130}))"},
            {"until": "!!document.querySelector('.jvr-menu:not([hidden])')", "ms": 5000},
            {"value": "archived_menu", "expr": "[...document.querySelectorAll('.jvr-menu button')].map(b=>b.dataset.act)"},
            {"click": ".jvr-menu button[data-act=\"restore\"]"},
            {"until": "!document.querySelector('#presentationRail .jvr-fold')&&document.querySelectorAll('#presentationRail .jvr-item').length===2", "ms": 8000},
            # rename
            {"eval": CONTEXT % pid2},
            {"until": "!!document.querySelector('.jvr-menu:not([hidden])')", "ms": 5000},
            {"click": ".jvr-menu button[data-act=\"rename\"]"},
            {"until": "!!document.querySelector('.jvr-dialog input')", "ms": 5000},
            {"eval": "(()=>{const i=document.querySelector('.jvr-dialog input');i.value='Sauvee et renommee'})()"},
            {"key": "Enter"},
            {"until": "[...document.querySelectorAll('#presentationRail .jvr-name')].some(n=>n.textContent==='Sauvee et renommee')", "ms": 8000},
            {"value": "final", "expr": ITEMS},
        ], viewport="1440x900", timeout=240)
        reads = result["reads"]
        assert "final" in reads, (reads, [c for c in result["console"] if "presentation-rail" in c["text"]][-6:])
        assert "restaure" in reads["dialog"] and "Rien n’est effacé" in reads["dialog"]
        assert [i[0] for i in reads["archived"]][-1] == "A supprimer"
        assert reads["archived_menu"] == ["restore"]
        assert "Sauvee et renommee" in [i[0] for i in reads["final"]]
        assert not noise(result), noise(result)
        status, view = await core.call("GET", f"/{pid2}")
        assert view["presentation"]["title"] == "Sauvee et renommee" and view["presentation"]["revision"] == 2
        rail_doc = json.loads((tmp_path / "data" / "presentations" / pid2 / "rail.json").read_text(encoding="utf-8"))
        assert rail_doc["archived"] is False and rail_doc["hidden"] is False


async def test_the_studio_plays_one_slide_or_everything_through_the_real_playback_routes(tmp_path):
    async with InspectorRig(tmp_path) as rig:
        core = rig.core
        revision = (await core.call("GET", f"/{rig.pid}/variants/{rig.vid}"))[1]["revision"]
        status, made = await core.call("POST", f"/{rig.pid}/variants/{rig.vid}/score", json=score(revision))
        assert status == 201, made
        result = await drive(rig.url, [
            {"until": "!!window.JarvisStudioExplorer", "ms": 20000},
            {"eval": f"JarvisStudioExplorer.open({{presentation_id:'{rig.pid}',fullscreen:false}})"},
            {"until": "!!document.querySelector('#jvStudioExplorer .jvx-scene')", "ms": 20000},
            {"click": "#jvStudioExplorer .jvx-scene:nth-child(2)"},
            {"wait": 400},
            {"value": "scene", "expr": "document.querySelector('#jvStudioExplorer .jvx-scene-line .jvx-scene-title').textContent"},
            {"click": "#jvStudioExplorer .jvx-play button:nth-child(1)"},
            {"until": "(()=>{const v=JarvisStudioPlayer.view();return !!v&&v.running===true})()", "ms": 20000},
            {"wait": 800},
            {"value": "view", "expr": "(()=>{const v=JarvisStudioPlayer.view();return {role:v.role,phase:v.phase,pid:v.presentation_id,position:v.position}})()"},
            {"value": "explorer_open", "expr": "JarvisStudioExplorer.isOpen()"},
        ], viewport="1440x900", timeout=240)
        reads = result["reads"]
        state = (await core.client.presentation_studio_playback_state())["state"]
        assert reads["scene"] == "Chiffres"
        assert reads["explorer_open"] is False, (reads, "the Studio closes when the run starts")
        assert state["role"] == "rehearsal" and state["presentation_id"] == rig.pid, state
        assert not noise(result), noise(result)

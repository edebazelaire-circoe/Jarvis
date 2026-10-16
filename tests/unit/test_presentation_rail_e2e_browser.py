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
from tests.unit.test_presentation_studio_rail import _still

pytestmark = pytest.mark.asyncio

ITEMS = "[...document.querySelectorAll('#presentationRail .jvr-item:not([data-ws])')].map(b=>[b.querySelector('.jvr-name').textContent,b.dataset.state,getComputedStyle(b.querySelector('.jvr-dot')).backgroundColor])"
CONTEXT = "document.querySelector('#presentationRail .jvr-item[data-id=\"%s\"]').dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:120,clientY:130}))"
HTTP_REFUSAL = "Failed to load resource: the server responded with a status of 4"


def png(width: int, height: int) -> bytes:
    """A real PNG (gradient), the bytes a still render would hold: the preview goes through the real relay and Core payload route."""

    import struct
    import zlib

    rows = b"".join(b"\x00" + bytes(v for x in range(width) for v in (40 + x * 160 // width, 60 + y * 120 // height, 140)) for y in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


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
        # Slice 07 (D10): a real still render of the first presentation is its card's preview (real registry, real relay, real payload)
        still = await _still(core, rig.pid, width=160, height=90, payload=png(160, 90))

        result = await drive(rig.url, [
            {"until": "!!window.JarvisPresentationRail", "ms": 20000},
            {"eval": "JarvisPresentationRail.setPref('shown')"},
            {"until": "JarvisPresentationRail.state().loaded===true&&document.querySelectorAll('#presentationRail .jvr-item:not([data-ws])').length>=3", "ms": 20000},
            {"value": "items", "expr": ITEMS},
            {"value": "folds", "expr": "[...document.querySelectorAll('#presentationRail .jvr-folds .jvr-fold')].map(b=>b.textContent.trim())"},
            {"until": "[...document.querySelectorAll('#presentationRail .jvr-thumb img')].every(i=>i.complete)", "ms": 8000},
            {"value": "zone", "expr": "(()=>{const b=s=>{const r=document.querySelector(s).getBoundingClientRect();return {l:r.left,t:r.top,r:r.right,b:r.bottom}};return {palette:b('#barehandsPalette'),rail:b('#presentationRail'),dock:b('.dock'),chat:b('#chatTab'),vw:innerWidth}})()"},
            # Stage B: the still is linked to the active Board by Core, so the real workspace route lists it under « Sur ce Board »
            {"until": "[...document.querySelectorAll('#presentationRail .jvr-ws .jvr-item img')].some(i=>i.complete&&i.naturalWidth>0)", "ms": 15000},
            {"value": "board_items", "expr": "[...document.querySelectorAll('#presentationRail .jvr-ws .jvr-item')].map(b=>[b.querySelector('.jvr-name').textContent,b.dataset.ws,b.dataset.state,(i=>i?i.complete&&i.naturalWidth===160:null)(b.querySelector('img'))])"},
            {"value": "preview", "expr":"(()=>{const i=document.querySelector('#presentationRail .jvr-thumb img');return i?{src:i.getAttribute('src'),ok:i.complete&&i.naturalWidth===160}:null})()"},
            {"shot": str(tmp_path / "rail.png")},
            # hide Roadmap through the real context menu and the real relay
            {"eval": CONTEXT % pid3},
            {"until": "!!document.querySelector('.jvr-menu:not([hidden])')", "ms": 5000},
            {"value": "menu", "expr": "[...document.querySelectorAll('.jvr-menu button')].map(b=>b.dataset.act)"},
            {"click": ".jvr-menu button[data-act=\"hide\"]"},
            {"until": "document.querySelectorAll('#presentationRail .jvr-item:not([data-ws])').length===2", "ms": 8000},
            {"value": "after_hide", "expr": ITEMS},
            # a click on the first presentation opens Variants on it, windowed (Slice 09 of native-studio-playback-fix: the floating
            # window host is retired, Variants is the one surface): rail docked, the tree's two variants, transport (Slice 10: the variant bar
            # is merged into the tree, `[` `]` stay)
            {"eval": f"document.querySelector('#presentationRail .jvr-item[data-id=\"{rig.pid}\"]').click()"},
            {"until": "!!window.JarvisStudioExplorer&&JarvisStudioExplorer.isOpen&&JarvisStudioExplorer.isOpen()", "ms": 15000},
            {"until": "JarvisStudioExplorer.state().live===2", "ms": 15000},
            {"wait": 500},
            {"value": "studio", "expr": "(()=>{const r=document.querySelector('#presentationRail').getBoundingClientRect(),x=document.querySelector('#jvStudioExplorer').getBoundingClientRect();return {docked:document.documentElement.classList.contains('jvr-studio'),railLeft:r.left,railRight:r.right,railTop:r.top,explorerLeft:x.left,explorerRight:x.right,railInert:!!document.querySelector('#presentationRail').closest('[inert]'),chips:JarvisStudioExplorer.state().live,vbar:document.querySelectorAll('#jvStudioExplorer .jvx-vbar,#jvStudioExplorer .jvx-vchip').length,play:[...document.querySelectorAll('#jvStudioExplorer .jvx-transport button')].filter(b=>!b.hidden).map(b=>b.getAttribute('aria-label')||b.textContent.trim()),windowOpen:!!document.querySelector('#jvPresWindow'),pid:JarvisStudioExplorer.state().presentation_id,fullscreen:!!document.fullscreenElement}})()"},
            {"shot": str(tmp_path / "studio.png")},
            # the rail stays usable inside the Studio: its menu opens above it
            {"eval": CONTEXT % pid2},
            {"until": "!!document.querySelector('.jvr-menu:not([hidden])')", "ms": 5000},
            {"value": "studio_menu", "expr": "(()=>{const m=document.querySelector('.jvr-menu').getBoundingClientRect();const top=document.elementFromPoint(m.left+20,m.top+20);return {onTop:!!top&&!!top.closest('.jvr-menu'),z:getComputedStyle(document.querySelector('.jvr-menu')).zIndex}})()"},
            {"key": "Escape"},
            {"value": "studio_still_open", "expr": "JarvisStudioExplorer.isOpen()"},
            # ] steps to the other variant (the tree's selection follows)
            {"value": "before_step", "expr": "JarvisStudioExplorer.state().selected"},
            {"eval": "document.querySelector('#jvStudioExplorer').dispatchEvent(new KeyboardEvent('keydown',{key:']',bubbles:true,cancelable:true}))"},
            {"wait": 600},
            {"value": "stepped", "expr": "[JarvisStudioExplorer.state().selected,document.querySelectorAll('#jvStudioExplorer .jvx-row[aria-selected=\"true\"]').length]"},
        ], viewport="1440x900", timeout=300)
        reads = result["reads"]
        assert [i[0] for i in reads["items"]] == ["Atelier du cadran", "Bilan trimestriel", "Roadmap produit"] or sorted(i[0] for i in reads["items"]) == sorted(["Atelier du cadran", "Bilan trimestriel", "Roadmap produit"])
        by_name = {name: (state, color) for name, state, color in reads["items"]}
        assert by_name["Bilan trimestriel"] == ("working", BLUE), "real work state from Core: the agent is working"
        assert by_name["Roadmap produit"] == ("problem", ORANGE), "real failure from Core"
        assert by_name["Atelier du cadran"] == ("done", GREEN)
        assert [f.replace(" ", "") for f in reads["folds"]] == ["▸Archivées(1)"]
        zone = reads["zone"]
        # Slice 07 (D10) migrates « right of the tool palette » to the right zone: never over the left column, the launcher or the chat tab
        assert zone["rail"]["l"] > zone["palette"]["r"] and zone["rail"]["r"] == zone["vw"] - 18 and zone["rail"]["t"] >= zone["dock"]["b"]
        assert zone["rail"]["b"] <= zone["chat"]["t"]
        assert reads["preview"] == {"src": f"/api/artifacts/{still}/payload", "ok": True}, "the real still, through the bounded payload route"
        assert ["Rendu image", "presentation_still", "done", True] in reads["board_items"], ("Stage B through the real workspace route", reads["board_items"])
        assert reads["menu"] == ["open", "studio", "edit", "play", "hide", "rename", "ack", "archive"]  # « Remotion Studio… » (Slice 11)
        assert sorted(i[0] for i in reads["after_hide"]) == ["Atelier du cadran", "Bilan trimestriel"]
        assert reads["studio"]["pid"] == rig.pid, "the rail click opens Variants on that presentation"
        # Slice 07 (D10): the docking is mirrored, the rail is the right column and Variants stops at its left edge
        assert reads["studio"]["docked"] is True and reads["studio"]["railRight"] == 1440 - 8 and reads["studio"]["explorerLeft"] == 0
        assert reads["studio"]["explorerRight"] <= reads["studio"]["railLeft"]
        assert reads["studio"]["railInert"] is False and reads["studio"]["chips"] == 2 and reads["studio"]["fullscreen"] is False
        assert reads["studio"]["vbar"] == 0, "Slice 10: no variant bar (merged into the tree)"
        # Slice 06 (native-studio-playback-fix): one transport toolbar; « Jouer cette slide » became the « ⋯ » entry « Lire seulement cette scène »;
        # Slice 10: « Présenter » is on the scene row under it
        assert reads["studio"]["play"] == ["Scène précédente", "Début de la slide", "Reculer de 5 secondes", "Lire", "Avancer de 5 secondes", "Scène suivante", "Son", "Plein écran", "Plus de lecture"] and reads["studio"]["windowOpen"] is False
        assert reads["studio_menu"]["onTop"] is True and reads["studio_still_open"] is True, "Escape in the rail menu does not close the Studio"
        assert reads["stepped"][0] != reads["before_step"] and reads["stepped"][1] == 1, (reads["before_step"], reads["stepped"])
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
            {"until": "document.querySelectorAll('#presentationRail .jvr-item:not([data-ws])').length===2", "ms": 20000},
            {"eval": CONTEXT % pid2},
            {"until": "!!document.querySelector('.jvr-menu:not([hidden])')", "ms": 5000},
            {"click": ".jvr-menu button[data-act=\"archive\"]"},
            {"until": "!!document.querySelector('.jvr-dialog-back:not([hidden]) .jvr-dialog')", "ms": 5000},
            {"value": "dialog", "expr": "document.querySelector('.jvr-dialog').textContent"},
            {"click": ".jvr-dialog button[data-danger]"},
            {"until": "document.querySelectorAll('#presentationRail .jvr-item:not([data-ws])').length===1", "ms": 8000},
            {"click": "#presentationRail .jvr-folds .jvr-fold"},
            {"value": "archived", "expr": ITEMS},
            # an archived row offers only "restore"
            {"eval": "document.querySelector('#presentationRail .jvr-item[data-dim=\"true\"]').dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:120,clientY:130}))"},
            {"until": "!!document.querySelector('.jvr-menu:not([hidden])')", "ms": 5000},
            {"value": "archived_menu", "expr": "[...document.querySelectorAll('.jvr-menu button')].map(b=>b.dataset.act)"},
            {"click": ".jvr-menu button[data-act=\"restore\"]"},
            {"until": "!document.querySelector('#presentationRail .jvr-folds .jvr-fold')&&document.querySelectorAll('#presentationRail .jvr-item:not([data-ws])').length===2", "ms": 8000},
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


async def test_read_only_this_scene_never_starts_a_run_nor_closes_variants(tmp_path):
    """Contract § 5 table / PX-21 (native-studio-playback-fix Slice 06): « Jouer cette slide » used to start a `rehearsal` run through the
    playback routes and close Variants. It is now the « ⋯ » entry « Lire seulement cette scène »: video semantics in the Variants Player, no
    run, Variants stays open (the rehearsal is « Présenter › Répétition », Slice 07). This deck is HTML: the entry says why there is no video."""

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
            {"until": "JarvisStudioExplorer.playback.view().phase==='unavailable'", "ms": 20000},
            {"value": "scene", "expr": "document.querySelector('#jvStudioExplorer .jvx-scene-line .jvx-scene-title').textContent"},
            {"value": "lire", "expr": "(()=>{const b=document.querySelector('#jvStudioExplorer [role=\"toolbar\"] [data-act=\"continuous\"]');return [b.getAttribute('aria-disabled'),b.title]})()"},
            {"click": "#jvStudioExplorer [role=\"toolbar\"] [data-act=\"continuous\"]"},
            {"wait": 800},
            {"value": "auto", "expr": "JarvisStudioExplorer.state().auto.on"},
            {"value": "pressed", "expr": "document.querySelector('#jvStudioExplorer [data-act=\"continuous\"]').getAttribute('aria-pressed')"},
            {"click": "#jvStudioExplorer [aria-haspopup=\"menu\"]"},
            {"until": "!!document.querySelector('#jvStudioExplorer .jvx-menu')", "ms": 5000},
            {"value": "menu", "expr": "[...document.querySelectorAll('#jvStudioExplorer .jvx-menu [role=\"menuitem\"]')].map(b=>b.textContent)"},
            {"value": "explorer_open", "expr": "JarvisStudioExplorer.isOpen()"},
        ], viewport="1440x900", timeout=240)
        reads = result["reads"]
        state = (await core.client.presentation_studio_playback_state())["state"]
        assert reads["scene"] == "Chiffres"
        assert reads["lire"][0] == "false" and "slides" in reads["lire"][1], "« Lire » plays the slides by their own rhythm when there is no video"
        assert reads["auto"] is True and reads["pressed"] == "true", "the automatic play is running inside Variants, the button says so"
        assert any("Recommencer à la fin" in item for item in reads["menu"]), "the overflow menu offers the automatic play's loop"
        assert reads["explorer_open"] is True, "Variants stays open"
        assert state.get("running") is not True and state.get("role") != "rehearsal", f"no run started: {state}"
        assert not noise(result), noise(result)

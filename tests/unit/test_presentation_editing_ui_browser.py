"""Editing a presentation from Variants on the REAL Control Center page (presentation-edition-v1, Slice 09).

Real: Core behind the real protocol server (own data root and ports, never the live Jarvis), the real Control Center relay and page, a
`custom` prefab published by the real route, variants grown by the real operations (`tests/fakes/explorer_browser.py`), real CDP clicks
and keys. Nothing of the edit path is simulated: the editor writes through `POST .../edits` of the relay, Core's variant is read back.

Proved (contract `docs/presentation-studio.md` › *Editing from Variants (V1)*):

- « Modifier » under the stage opens the editor beside Variants, ON TOP of it (hit-testable, not inert), on the variant and the scene ON
  SCREEN — a non-active branch included — and says so in words (variant number, « active » / « non active », scene k of n);
- the editor follows the scene chosen in Variants, and Variants follows the scene chosen in the editor;
- a committed change is Core's: the variant file holds it, and Variants re-reads the variant (the preview frame shows the new title) with
  no optimistic copy of the editor's value;
- « Annuler » names the scene it changes; an undo of a change made on ANOTHER scene brings that scene on screen in both, and only that
  scene's value goes back (the other scenes are byte-identical in Core);
- in the `presentation` edition without developer mode Variants offers neither « Remotion Studio » nor its scene door nor its state line,
  and the editor hides the engine's source line; with `JARVIS_DEVELOPER_MODE=1` they are back (I-006);
- three window sizes keep « Modifier » reachable and the editor whole.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fakes.explorer_browser import PREVIEW_OBJECT, S1, S2, ExplorerRig, drive
from tests.unit.test_presentation_studio_explorer_browser import noise, shots_dir

pytestmark = pytest.mark.asyncio

HOST = "#jvStudioExplorer"
PANEL = "#jvStudioInspector"
EDIT = f"{HOST} [data-act=edit_scene]"
READY = {"until": "JarvisStudioExplorer.state().open&&JarvisStudioExplorer.state().preview.status==='ready'", "ms": 30000}
EDITOR_READY = {"until": f"(()=>{{const p=document.querySelector('{PANEL}');const v=JarvisStudioInspector.instance.view();"
                         f"return !!p&&!p.hidden&&!v.loading&&v.controls.length>0}})()", "ms": 20000}
CONTEXT = f"document.querySelector('{PANEL} [data-role=edit-context]').textContent"
ON_TOP = (f"(()=>{{const p=document.querySelector('{PANEL}');const r=p.getBoundingClientRect();"
          f"const hit=document.elementFromPoint(r.left+r.width/2,r.top+Math.min(160,r.height/2));"
          f"return JSON.stringify({{onTop:!!hit&&!!hit.closest('{PANEL}'),inert:p.inert||!!p.closest('[inert]'),"
          f"left:Math.round(r.left),right:Math.round(r.right),vw:innerWidth,"
          f"stage:Math.round(document.querySelector('{HOST} .jvx-stage').getBoundingClientRect().right)}})}})()")
SHOWN = "(sel=>{const e=document.querySelector(sel);if(!e)return null;const cs=getComputedStyle(e);if(cs.display==='none'||e.closest('[hidden]'))return false;" \
        "for(let n=e;n;n=n.parentElement){if(getComputedStyle(n).display==='none')return false}const r=e.getBoundingClientRect();return r.width>0&&r.height>0})"


def open_variants(rig: ExplorerRig, variant: int | None = None) -> dict:
    extra = f",variant_id:'{rig.vids[variant]}'" if variant else ""
    return {"eval": f"JarvisStudioExplorer.open({{presentation_id:'{rig.pid}',fullscreen:false{extra}}})"}


def scene_button(scene_id: str) -> str:
    return f'{HOST} .jvx-scene[data-scene="{scene_id}"]'


def stored_scenes(rig: ExplorerRig, vid: str) -> dict:
    doc = json.loads(rig.variant_file(vid).read_text(encoding="utf-8"))
    return {s["scene_id"]: s for s in doc["scenes"]}


async def test_modifier_edits_the_variant_and_scene_on_screen_and_variants_reads_core_back(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", "presentation")
    monkeypatch.delenv("JARVIS_DEVELOPER_MODE", raising=False)
    async with ExplorerRig(tmp_path, variants=2) as rig:
        # #2 is a NON-active branch: « Modifier » must edit it (the one on screen), never the active #1.
        before_active = stored_scenes(rig, rig.vids[1])
        shots = shots_dir(tmp_path)
        result = await drive(rig.url, [
            open_variants(rig, 2), READY,
            {"until": f"{SHOWN}('{EDIT}')", "ms": 10000},
            {"value": "developer", "expr": "JSON.stringify({surfaces:document.documentElement.getAttribute('data-developer-surfaces'),"
                                           f"door:{SHOWN}('{HOST} [data-act=remotion_studio]'),line:{SHOWN}('{HOST} .jvx-rms'),"
                                           f"scene_door:{SHOWN}('{HOST} [data-act=remotion_studio_scene]')}})"},
            {"click": scene_button(S2)},
            {"until": f"JarvisStudioExplorer.state().preview.scene==='{S2}'", "ms": 5000},
            {"click": EDIT}, EDITOR_READY,
            {"value": "context", "expr": CONTEXT},
            {"value": "editing", "expr": "JSON.stringify(JarvisStudioInspector.instance.view())"},
            {"value": "layer", "expr": ON_TOP},
            {"value": "srcline", "expr": f"{SHOWN}('{PANEL} [data-surface=developer]')"},
            {"shot": str(shots / "s09-edit-docked-1280x720.png")},
            # Variants -> editor: another scene on screen, the editor follows.
            {"click": scene_button(S1)},
            {"until": f"JarvisStudioInspector.instance.view().scene_id==='{S1}'&&!JarvisStudioInspector.instance.view().loading", "ms": 10000},
            {"value": "followed", "expr": CONTEXT},
            # A real edit of the title of S1 on #2.
            {"focus": f"{PANEL} input[type=text]"}, {"eval": f"document.querySelector('{PANEL} input[type=text]').select()"},
            {"type": "Titre modifié S09"}, {"key": "Enter"},
            {"until": "(()=>{const h=JarvisStudioInspector.instance.view().history;return !!h&&h.undo>0})()", "ms": 15000},
            {"frameUntil": {"object_id": PREVIEW_OBJECT, "expr": "!!document.querySelector('h2')&&document.querySelector('h2').textContent==='Titre modifié S09'", "ms": 20000}},
            {"value": "frame_after_edit", "expr": "JarvisStudioExplorer.state().preview.status"},
            # Editor -> Variants: the editor's scene picker brings Variants along; then undo the S1 change from S2.
            {"eval": f"(s=>{{s.value='{S2}';s.dispatchEvent(new Event('change'))}})(document.getElementById('jviScene'))"},
            {"until": f"JarvisStudioExplorer.state().preview.scene==='{S2}'&&!JarvisStudioInspector.instance.view().loading", "ms": 10000},
            {"value": "undo_label", "expr": f"(b=>b.getAttribute('aria-description')+' | '+b.title)(document.querySelector('{PANEL} .jvi-bar button[aria-label^=Annuler]'))"},
            {"click": f"{PANEL} .jvi-bar button[aria-label^=Annuler]"},
            {"until": f"JarvisStudioInspector.instance.view().scene_id==='{S1}'&&JarvisStudioExplorer.state().preview.scene==='{S1}'", "ms": 15000},
            {"until": f"(document.querySelector('{PANEL} .jvi-status')||{{}}).textContent.includes('annulée')", "ms": 10000},
            {"value": "undone", "expr": f"document.querySelector('{PANEL} .jvi-status').textContent"},
            {"frameUntil": {"object_id": PREVIEW_OBJECT, "expr": "!!document.querySelector('h2')&&document.querySelector('h2').textContent!=='Titre modifié S09'", "ms": 20000}},
        ])
        reads = result["reads"]
        assert "failed" not in reads, reads.get("failed")
        dev = json.loads(reads["developer"])
        assert dev == {"surfaces": "hidden", "door": False, "line": False, "scene_door": False}, dev
        assert reads["srcline"] is False, "the engine's source line is a developer surface"
        context = reads["context"]
        assert "scène 2 sur 3" in context and "variante #2" in context and "non active" in context, context
        editing = json.loads(reads["editing"])
        assert editing["variant_id"] == rig.vids[2] and editing["scene_id"] == S2, "the variant and the scene ON SCREEN, not the active one"
        layer = json.loads(reads["layer"])
        assert layer["onTop"] and not layer["inert"], layer
        assert layer["stage"] <= layer["left"], ("Variants makes room for the editor", layer)
        assert "scène 1 sur 3" in reads["followed"]
        assert "scène 1" in reads["undo_label"] and "autre scène" in reads["undo_label"], reads["undo_label"]
        assert "Modification annulée : scène 1" in reads["undone"], reads["undone"]
        # Core holds the truth: #2's S1 went back, S2 and S3 untouched; the active #1 never moved.
        after = stored_scenes(rig, rig.vids[2])
        assert after[S1]["props"]["title"] != "Titre modifié S09"
        assert stored_scenes(rig, rig.vids[1]) == before_active, "editing a branch never touches the active variant"
        assert not noise(result, ("Failed to load resource: the server responded with a status of 4",)), noise(result)


async def test_developer_mode_shows_the_remotion_studio_door_again(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", "presentation")
    monkeypatch.setenv("JARVIS_DEVELOPER_MODE", "1")
    async with ExplorerRig(tmp_path, variants=1) as rig:
        result = await drive(rig.url, [
            open_variants(rig), READY,
            {"until": f"{SHOWN}('{EDIT}')", "ms": 10000},
            {"value": "developer", "expr": "JSON.stringify({surfaces:document.documentElement.getAttribute('data-developer-surfaces'),"
                                           f"door:{SHOWN}('{HOST} [data-act=remotion_studio]')}})"},
        ])
        dev = json.loads(result["reads"]["developer"])
        assert dev == {"surfaces": "visible", "door": True}, dev


@pytest.mark.parametrize("viewport", ["1440x900", "600x800"])
async def test_the_editor_stays_whole_and_modifier_reachable_at_every_size(tmp_path, monkeypatch, viewport):
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", "presentation")
    monkeypatch.delenv("JARVIS_DEVELOPER_MODE", raising=False)
    async with ExplorerRig(tmp_path, variants=1) as rig:
        shots = shots_dir(tmp_path)
        result = await drive(rig.url, [
            open_variants(rig), READY,
            {"until": f"{SHOWN}('{EDIT}')", "ms": 10000},
            {"click": EDIT}, EDITOR_READY,
            {"value": "layer", "expr": ON_TOP},
            {"value": "scroll", "expr": "document.documentElement.scrollWidth<=innerWidth"},
            {"shot": str(shots / f"s09-edit-docked-{viewport}.png")},
            {"key": "Escape"},
            {"until": f"document.querySelector('{PANEL}').hidden", "ms": 5000},
            {"value": "variants_open", "expr": "JarvisStudioExplorer.state().open"},
        ], viewport=viewport)
        reads = result["reads"]
        layer = json.loads(reads["layer"])
        assert layer["onTop"] and not layer["inert"] and layer["right"] <= layer["vw"] and layer["left"] >= 0, layer
        assert reads["scroll"] is True
        assert reads["variants_open"] is True, "Escape in the editor closes the editor only"

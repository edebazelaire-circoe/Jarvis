"""Présentations d'un Board dans un vrai Chrome, contre un vrai Core et un vrai Control Center (Remotion Slice 08).

Même harnais CDP que `test_workspace_manager_browser.py` (`_workspace_browser.mjs`) : la page SERVIE parle au relais
`/api/workspace/*`, qui parle à un Core réel sur SQLite et à une racine de données isolée sous `tmp_path` (ports libres
tirés par `CaptureStack`, jamais le JARVIS vivant). Monde semé par les propriétaires canoniques : une source Remotion figée
puis modifiée (périmée) avec un rendu en cours, une source figée dont le dossier a été perdu (supprimée), un rendu partagé
avec un autre Board. Se saute si Chrome ou node manque. Captures : `tmp_path` ou `JARVIS_S8_EVIDENCE_DIR`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil

import pytest

from tests.fakes.capture_stack import CaptureStack
from tests.unit.test_interaction_mode_hud_browser import _chrome

HARNESS = Path(__file__).parent / "_workspace_browser.mjs"


async def _freeze(stack: CaptureStack, pid: str, vid: str) -> str:
    c = stack.core
    view = await c.presentation_studio.get(pid)
    variant = next(v for v in view.variants if v.variant_id == vid)
    began = await c.presentation_artifacts.begin_snapshot(
        pid, vid, expected_presentation_revision=view.presentation.revision, expected_variant_revision=variant.revision)
    spool = c.artifacts.open_spool(await c.artifacts.get(began["artifact_id"]))
    data = b"PK-" + began["artifact_id"].encode()
    spool.write(data)
    spool.finalize()
    await c.presentation_artifacts.finalize_snapshot(began["artifact_id"], content_sha256=hashlib.sha256(data).hexdigest())
    return began["artifact_id"]


async def _world(stack: CaptureStack) -> dict:
    c = stack.core
    other = (await c.boards.create({"title": "Autre Board"})).board_id
    home = (await c.boards.create({"title": "Atelier de lancement"})).board_id
    await c.boards.switch(home)
    first = await c.presentation_studio.create({"title": "Lancement produit"})
    pid, vid = first.presentation.presentation_id, first.presentation.active_variant_id
    snap = await _freeze(stack, pid, vid)
    video = (await c.presentation_artifacts.begin_render(snap, "mp4")).artifact_id
    pdf = (await c.presentation_artifacts.begin_render(snap, "pdf")).artifact_id
    await c.artifacts.fail(pdf, error_code="render_failed")
    await c.workspace.artifact_link(other, video)  # a render also shown on another Board
    variant = (await c.presentation_studio.get(pid)).variants[0].to_document()
    await c.presentation_studio.save_variant(pid, vid, {  # the source moves on: the frozen copy is now stale
        "expected_revision": variant["revision"], "title": variant["title"] + " v2", "scenes": variant["scenes"],
        "art_direction_id": variant["art_direction_id"], "score_id": variant["score_id"]})
    second = await c.presentation_studio.create({"title": "Source perdue"})
    gone, gone_vid = second.presentation.presentation_id, second.presentation.active_variant_id
    gone_snap = await _freeze(stack, gone, gone_vid)
    shutil.rmtree(stack.data_root / "presentations" / gone)
    return {"home": home, "other": other, "pid": pid, "vid": vid, "snap": snap, "video": video, "pdf": pdf,
            "gone": gone, "gone_snap": gone_snap}


def _plan(w: dict, *, width: int, height: int, shots: bool = True) -> dict:
    panel = "document.getElementById('wspPanel')"
    text = f"{panel}.textContent"
    sections = f"{panel}.querySelector('#wspPresTitle').closest('section')"
    steps = [
        {"do": "document.getElementById('openWorkspace').click()"},
        {"wait": "document.getElementById('wsp-tab-artifacts')"},
        {"do": "document.getElementById('wsp-tab-artifacts').click()"},
        {"wait": f"{text}.includes('Présentations de ce Board')&&{text}.includes('Lancement produit')"},
        {"wait": "document.getElementById('wspStatus').dataset.tone!=='busy'"},
        {"get": "section", "expr": f"{sections}.textContent"},
        {"get": "overflow", "expr": f"(()=>{{const p={panel};return p.scrollWidth-p.clientWidth}})()"},
        {"get": "source_cards", "expr": f"{sections}.querySelectorAll('.wsp-psrc').length"},
        {"get": "tree_order", "expr": f"[...{sections}.querySelectorAll('.wsp-psrc')].map(s=>"
                                      "[...s.querySelectorAll('.wsp-node')].map(n=>n.textContent.trim()).join('>')).join('|')"},
        {"get": "kinds", "expr": "[...document.getElementById('wspArtKind').options].map(o=>o.textContent).join('|')"},
        {"get": "disabled_open", "expr": f"{sections}.querySelectorAll('[data-act=source-open][disabled]').length"},
    ]
    if shots:
        steps.append({"shot": f"s8-board-presentations-{width}.png"})
    steps += [
        # A render opens as an artifact with its provenance (« rendu de » the snapshot), by id.
        {"do": f"{sections}.querySelector('[data-act=artifact-show][data-id={w['video']}]').click()"},
        {"wait": f"{text}.includes('Provenance')&&{text}.includes('rendu de')"},
        {"get": "render_detail", "expr": "document.getElementById('wspArtifactOpen')?document.getElementById('wspArtifactOpen').textContent:''"},
        {"get": "render_boards", "expr": f"{text}.includes('Autre Board')"},
    ]
    if shots:
        steps.append({"shot": f"s8-render-provenance-{width}.png"})
    steps += [
        # « Ouvrir la source » asks the Studio explorer by identifier; the panel closes only when it accepted.
        {"do": f"{sections}.querySelector('[data-act=source-open][data-presentation={w['pid']}]:not([disabled])').click()"},
        {"wait": "document.getElementById('workspaceManager').hidden||document.querySelector('#wspPanel .wsp-notice')"},
        {"get": "after_open_hidden", "expr": "document.getElementById('workspaceManager').hidden"},
        {"get": "after_open_notice", "expr": "(document.querySelector('#wspPanel .wsp-notice')||{textContent:''}).textContent"},
        {"get": "explorer_open", "expr": "!!(window.JarvisStudioExplorer&&window.JarvisStudioExplorer.isOpen())"},
    ]
    if shots:
        steps.append({"shot": f"s8-open-source-{width}.png"})
    return {"width": width, "height": height, "steps": steps}


async def _run(tmp_path, width, height):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    chrome = _chrome()
    shots = Path(os.environ.get("JARVIS_S8_EVIDENCE_DIR") or tmp_path / "shots")
    shots.mkdir(parents=True, exist_ok=True)
    async with CaptureStack(tmp_path) as stack:
        w = await _world(stack)
        stack.center.board_routes._transport = stack.sessions
        proc = await asyncio.create_subprocess_exec(
            node, str(HARNESS), f"http://127.0.0.1:{stack.cc_port}/", chrome,
            json.dumps(_plan(w, width=width, height=height)), str(shots),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=420)
        assert proc.returncode == 0, err.decode("utf-8", "replace")
        return w, json.loads(out.decode("utf-8")), shots


@pytest.mark.asyncio
async def test_the_board_shows_source_snapshot_and_renders_with_their_states_in_a_real_browser(tmp_path):
    w, seen, shots = await _run(tmp_path, 1440, 900)
    r = seen["results"]
    text = r["section"]
    assert r["source_cards"] == 2
    assert "Lancement produit" in text and w["gone"] in text, "a vanished source is named by its reference"
    assert "Source modifiée depuis" in text, "the frozen copy of the edited source is shown as stale"
    assert "Source supprimée" in text and "Ouvrir la source" in text
    assert "MP4" in text and "PDF" in text and "Échoué" in text, "the failed render is visible, not hidden"
    assert "Remotion" in text and "Aussi sur" in text and "Autre Board" in text
    assert "Source>Copie figée>Rendu>Rendu" in r["tree_order"] and "Source>Copie figée" in r["tree_order"], r["tree_order"]
    assert r["disabled_open"] == 2, "a vanished source offers no open (source + its variant)"
    assert "Présentation figée" in r["kinds"] and "Présentation (vidéo)" in r["kinds"]
    assert r["overflow"] <= 0
    assert "rendu de" in r["render_detail"] and w["snap"] in r["render_detail"]
    assert r["render_boards"] is True
    # The explorer either took over (panel closed) or its refusal is shown in the panel: never silence.
    assert r["after_open_hidden"] is True or r["after_open_notice"].strip() != ""
    taken = {k[5:] for k in r if k.startswith("shot:")}
    assert len(taken) == 3 and taken <= {p.name for p in shots.glob("*.png")}
    bad = [line for line in seen["console"] if line["type"] == "exception"
           or (line["type"] == "error" and "[workspace]" in line["text"])]
    assert bad == [], bad


@pytest.mark.asyncio
async def test_on_a_narrow_screen_the_presentation_tree_does_not_scroll_sideways(tmp_path):
    _, seen, _ = await _run(tmp_path, 700, 900)
    assert seen["results"]["overflow"] <= 0 and seen["results"]["source_cards"] == 2

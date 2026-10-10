"""Semantic catalog in the Control Center prefab library, in a REAL headless Chrome, against an isolated REAL Core
(jarvis-remotion-presentation-integration, Slice 17).

Nothing is simulated but the display: a real Core (own ports, temporary data root) holding the shipped base prefabs plus three
custom versions (a v3 HTML component, a v3 Remotion composition, and a legacy v1 one), the real Control Center page relaying
`/api/prefabs`, real CDP clicks. Proved: the type / engine / stack filters narrow the list, an engine a prefab does not
support reads `non pris en charge` in words on the row, a derived contract says it is derived, the editable parameters stay
closed until opened, upstream is shown as declared and unverified, and the console holds no error.
"""

from __future__ import annotations

import os
from pathlib import Path

import aiohttp
import pytest

from tests.fakes.capture_stack import TOKEN
from tests.fakes.prefabs import candidate
from tests.fakes.remotion_scene import scene_candidate
from tests.unit.test_presentation_studio_player_realpage_browser import _no_noise, _until, drive
from tests.unit.test_presentation_studio_routes import Core

AUTH = {"Authorization": f"Bearer {TOKEN}"}
SHOT_DIR = os.environ.get("JARVIS_S17_SHOTS")

UPSTREAM = {"name": "remotion-dev/template", "url": "https://github.com/remotion-dev/template", "ref": "v4", "license": "MIT"}
SCENE_ID = "team.intro-scene"
HTML_ID = "team.badge"


def html_v3():
    raw = candidate("test.counter")
    raw["manifest"] = {**raw["manifest"], "id": HTML_ID, "title": "Badge déclaré", "schema_version": 3,
                       "catalog": {"type": "component", "compatibility": {"slidecar": "native", "remotion": "adapter"},
                                   "stack": ["html", "css", "javascript"], "license": "Apache-2.0",
                                   "dependencies": [{"name": "d3", "version": "7.9.0"}]}}
    return raw


def scene_v3():
    raw = scene_candidate(SCENE_ID)
    raw["manifest"] = {**raw["manifest"], "schema_version": 3, "title": "Intro Remotion",
                       "catalog": {"type": "composition", "compatibility": {"remotion": "native"},
                                   "stack": ["react", "remotion", "typescript"], "license": "MIT", "upstream": UPSTREAM,
                                   "dependencies": [{"name": "remotion", "version": "4.0.534"}]}}
    return raw


async def publish(core: Core, raw) -> None:
    async with core.http.post(core.stack.core_url + "/v1/prefabs", headers=AUTH, json={"actor": "user", "candidate": raw}) as r:
        assert r.status == 201, await r.text()


def shot(name: str) -> list:
    return [{"shot": str(Path(SHOT_DIR) / f"{name}.png")}] if SHOT_DIR else []


async def test_the_library_browses_by_type_engine_and_stack_and_never_guesses_a_compatibility(tmp_path):
    async with Core(tmp_path) as core:
        await publish(core, html_v3())
        await publish(core, scene_v3())
        await publish(core, {**candidate("test.counter"), "manifest": {**candidate("test.counter")["manifest"],
                                                                         "id": "team.legacy", "title": "Ancien compteur"}})
        url = f"http://127.0.0.1:{core.stack.cc_port}/"
        rows = "[...document.querySelectorAll('#pfbList .pfb-row')].map(r=>r.dataset.id)"
        select = lambda sel, value: {"eval": (  # noqa: E731
            f"(()=>{{const s=document.querySelector('{sel}');s.value={value!r};s.dispatchEvent(new Event('change',{{bubbles:true}}))}})()")}
        result = await drive(url, [
            {"size": [1400, 900]}, {"wait": 500},
            {"click": "#openPrefabs"}, _until("document.querySelectorAll('#pfbList .pfb-row').length>=8", 15000),
            {"wait": 800},
            {"value": "all", "expr": rows},
            {"value": "type_options", "expr": "[...document.querySelectorAll('#pfbType option')].map(o=>o.value)"},
            {"value": "engine_options", "expr": "[...document.querySelectorAll('#pfbEngine option')].map(o=>o.value)"},
            {"value": "stack_options", "expr": "[...document.querySelectorAll('#pfbStack option')].map(o=>o.value)"},
            {"value": "legacy_row", "expr": "document.getElementById('pfb-row-team.legacy').getAttribute('aria-label')"},
            {"value": "scene_row", "expr": "document.getElementById('pfb-row-team.intro-scene').getAttribute('aria-label')"},
            *shot("list-all"),
            select("#pfbType", "composition"), {"wait": 300}, {"value": "composition", "expr": rows},
            select("#pfbType", ""), select("#pfbEngine", "remotion"), {"wait": 300}, {"value": "remotion", "expr": rows},
            select("#pfbEngine", "slidecar"), select("#pfbStack", "react"), {"wait": 300}, {"value": "slidecar_react", "expr": rows},
            {"value": "empty_state", "expr": "document.getElementById('pfbListState').textContent"},
            {"click": "#pfbClearSemantic"}, {"wait": 300},
            {"value": "cleared", "expr": f"[{rows}.length, document.getElementById('pfbType').value, document.getElementById('pfbEngine').value]"},
            select("#pfbEngine", "remotion"), select("#pfbStack", "react"), {"wait": 300},
            {"click": "#pfb-row-team\\.intro-scene"}, _until("!!document.querySelector('.pfb-catalog .pfb-cdl')", 10000),
            {"wait": 400},
            {"value": "section_html", "expr": "document.querySelector('.pfb-catalog').outerHTML.slice(0,300)"},
            {"value": "declared_hint", "expr": "document.querySelector('.pfb-catalog .pfb-sechint').textContent"},
            {"value": "detail", "expr": "document.querySelector('.pfb-catalog .pfb-cdl').textContent"},
            {"value": "params_open_before", "expr": "document.getElementById('pfbParams').open"},
            {"value": "params_summary", "expr": "document.querySelector('#pfbParams summary').textContent"},
            {"value": "no_preview", "expr": "document.getElementById('pfbNoPreview').textContent"},
            {"value": "describedby", "expr": "['pfbPlace','pfbForkOpen'].map(i=>{const b=document.getElementById(i);const d=document.getElementById(b.getAttribute('aria-describedby'));return d&&d.className==='pfb-acthint'&&d.textContent.includes('Remotion')})"},
            {"value": "place_disabled", "expr": "[document.getElementById('pfbPlace').disabled, document.getElementById('pfbForkOpen').disabled]"},
            {"eval": "document.getElementById('pfbParams').scrollIntoView({block:'center'})"}, {"wait": 200},
            {"click": "#pfbParams summary"}, {"wait": 200},
            {"value": "params_open_after", "expr": "document.getElementById('pfbParams').open"},
            {"value": "params_text", "expr": "document.getElementById('pfbParams').textContent"},
            *shot("detail-composition"),
            select("#pfbEngine", ""), select("#pfbStack", ""), {"wait": 300},
            {"eval": "document.getElementById('pfb-row-team.legacy').scrollIntoView({block:'center'})"}, {"wait": 200},
            {"click": "#pfb-row-team\\.legacy"},
            _until("(document.querySelector('.pfb-catalog .pfb-sechint')||{textContent:''}).textContent.includes('d\\u00e9duit')", 10000),
            {"value": "legacy_state", "expr": "[document.getElementById('pfbDetailTitle').textContent, document.getElementById('pfbType').value, document.getElementById('pfbEngine').value, document.querySelectorAll('#pfbList .pfb-row').length]"},
            {"value": "legacy_detail", "expr": "document.querySelector('.pfb-catalog .pfb-cdl').textContent"},
            *shot("detail-legacy"),
            {"size": [390, 800]}, {"wait": 400},
            {"value": "narrow_overflow", "expr": "document.documentElement.scrollWidth<=innerWidth+1"},
            {"value": "semantic_visible", "expr": "(()=>{const r=document.querySelector('.pfb-semantic').getBoundingClientRect();return r.width>0&&r.right<=innerWidth+1})()"},
            *shot("narrow"),
        ])
        reads = result["reads"]
    assert "failed" not in reads, (reads.get("failed"), result["console"][-8:])
    base_ids = {"jarvis.browser", "jarvis.checklist", "jarvis.document", "jarvis.table", "jarvis.window"}
    assert set(reads["all"]) == base_ids | {HTML_ID, SCENE_ID, "team.legacy"}
    assert reads["type_options"] == ["", "component", "composition", "page", "presentation", "asset"]
    assert reads["engine_options"] == ["", "slidecar", "remotion"]
    assert reads["stack_options"] == ["", "css", "html", "javascript", "react", "remotion", "typescript"]
    # The row says it in words, for every engine, including the unsupported one (not guessed, not hidden).
    assert "composant" in reads["legacy_row"] and "slidecar natif" in reads["legacy_row"] and "remotion non pris en charge" in reads["legacy_row"]
    assert "composition" in reads["scene_row"] and "slidecar non pris en charge" in reads["scene_row"] and "remotion natif" in reads["scene_row"]
    assert reads["composition"] == [SCENE_ID]
    assert set(reads["remotion"]) == {SCENE_ID, HTML_ID}  # an adapter counts as compatible, never as native
    assert reads["slidecar_react"] == [] and "Aucun prefab" in reads["empty_state"]
    assert reads["cleared"][0] == len(reads["all"]) and reads["cleared"][1:] == ["", ""]
    assert "Déclaré par le manifeste" in reads["declared_hint"]
    detail = reads["detail"]
    for needle in ("Composition", "Slidecar non pris en charge", "Remotion natif", "react", "typescript", "4.0.534", "MIT",
                   "remotion-dev/template", "@ v4", "https://github.com/remotion-dev/template", "Core ne l’a pas vérifié"):
        assert needle in detail, (needle, detail)
    assert reads["describedby"] == [True, True]
    assert "source Remotion" in reads["no_preview"] and reads["place_disabled"] == [True, True]
    assert reads["params_open_before"] is False and reads["params_open_after"] is True, "parameters open on demand only"
    assert "Paramètres éditables (" in reads["params_summary"] and reads["params_text"].strip()
    legacy = reads["legacy_detail"]
    assert reads["legacy_state"][0] == "Ancien compteur", reads["legacy_state"]
    assert "Composant" in legacy and "Slidecar natif" in legacy and "Remotion non pris en charge" in legacy
    assert "non déclarée" in legacy and "aucun (créé sur ce poste)" in legacy
    assert reads["narrow_overflow"] is True and reads["semantic_visible"] is True
    _no_noise(result)

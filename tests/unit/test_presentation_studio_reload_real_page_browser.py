"""Le rechargement a chaud sur la VRAIE page du Control Center, avec un VRAI Core (jarvis-interactive-presentation-studio, Slice 06).

Aucun pont de test ici : `JarvisCoreApplication` + `LocalProtocolServer` + `ControlCenter` (la chaine du banc de capture) servent la
page que l'utilisateur ouvre ; la vraie page de scene dessine les fenetres de la scene globale, monte leurs cadres avec le vrai
hote (donc `swapPrefix` et `onOutcome` branches par `control_center_scene_page.js`), et le module de rechargement envoie ses
rapports par le vrai relais. Le prefab est la base livree `jarvis.window`.

Prouve ce que le pont ne peut pas prouver : que le cablage de la page de scene (hote, rapport, relais, Core) tient de bout en
bout. Le cadre est lu comme un contenu non fiable (CDP, `jarvis.instance.object_id`), jamais autrement.
"""

from __future__ import annotations

import json

import pytest

from jarvis.domain.scene import (
    Representation, SceneActor, SceneCommand, SceneGeometry, SceneObjectFields, SceneObjectKind, SceneOp, ScenePayload,
    ScenePrefabRef,
)
from jarvis.runtime.scene_view import CoreSceneTransport, CoreSceneView
from tests.fakes.presentation_studio_reload_browser import drive
from tests.unit.test_presentation_studio_edit_routes import RELAY, S1, new_presentation
from tests.unit.test_presentation_studio_reload_routes import start_run
from tests.unit.test_presentation_studio_routes import Core

pytestmark = pytest.mark.asyncio

LISTENERS = "[window,document,document.body].map(t=>Object.values(getEventListeners(t)).flat().length).reduce((a,b)=>a+b,0)"
USER_WINDOWS = ("user-a", "user-b")


class Url:
    def __init__(self, url: str) -> None:
        self.url = url


async def real_page(tmp_path):
    core = Core(tmp_path)
    await core.__aenter__()
    pid, vid, revision = await new_presentation(core)
    # the real Control Center gets the scene proxy a production process has (the capture stack has none)
    port = int(core.stack.core_url.rsplit(":", 1)[1])
    center = core.stack.center
    center.scene_view = CoreSceneView(CoreSceneTransport(host="127.0.0.1", port=port, token_file=core.stack.tmp_path / "core.token"),
                                      journal=center.journal)
    stage_id, revision = await start_run(core, pid, vid)       # a REAL playback run: its window is `studio-stage-<run_id>`
    for index, object_id in enumerate(USER_WINDOWS):
        await core.stack.core.scene.apply(SceneCommand(
            op=SceneOp.UPSERT_OBJECT, actor=SceneActor.USER, object_id=object_id, fields=SceneObjectFields(
                kind=SceneObjectKind.WINDOW, category="note", representation=Representation.WINDOW,
                geometry=SceneGeometry(200 + index * 140, 0, 120, 80),
                payload=ScenePayload(title=object_id, prefab=ScenePrefabRef("jarvis.window", 1, {}, {})))))
    return core, pid, vid, revision, stage_id


def edit(pid, vid, revision, files, *, extra="{}") -> dict:
    expression = ("JarvisStudioReload.instance.applySourceEdit(Object.assign({presentation_id:%s,variant_id:%s,scene_id:%s,revision:%d,"
                  "title:'Ouverture',files:JSON.parse(%s)},%s)).catch(e=>({thrown:e.code,message:e.message}))"
                  % (json.dumps(pid), json.dumps(vid), json.dumps(S1), revision, json.dumps(json.dumps(files)), extra))
    return {"value": "edit", "expr": expression}


def prelude(stage_id: str) -> list:
    steps: list = [
        {"until": "document.querySelectorAll('iframe.sc-prefab-frame').length>=3", "ms": 30000},
        {"wait": 1200},
        {"eval": "window.__nodes=Object.fromEntries([...document.querySelectorAll('[data-object-id]')]"
                 ".map(e=>[e.dataset.objectId,e.querySelector('iframe.sc-prefab-frame')]))"},
    ]
    for oid in (stage_id, *USER_WINDOWS):
        steps.append({"frameEval": "window.__born='born-'+Math.random().toString(36).slice(2)", "object_id": oid})
    steps.append({"framesValue": "listeners_before", "expr": LISTENERS})
    return steps


def survey(tag: str, stage_id: str) -> list:
    steps: list = [
        {"value": f"{tag}:same_nodes", "expr": "Object.fromEntries(Object.entries(window.__nodes).map(([id,n])=>[id,"
                                              "document.querySelector('[data-object-id=\"'+id+'\"] iframe')===n]))"},
        {"value": f"{tag}:iframes", "expr": "document.querySelectorAll('iframe.sc-prefab-frame').length"},
        {"value": f"{tag}:band", "expr": "(()=>{const b=document.getElementById('jvStudioReloadBand');"
                                        "return b?{kind:b.dataset.kind,text:b.textContent}:null})()"},
        {"value": f"{tag}:sandboxes", "expr": "[...document.querySelectorAll('iframe.sc-prefab-frame')].map(f=>[f.getAttribute('sandbox'),f.getAttribute('allow')])"},
    ]
    for oid in (stage_id, *USER_WINDOWS):
        steps.append({"frameValue": f"{tag}:born:{oid}", "object_id": oid, "expr": "window.__born||null"})
    steps.append({"framesValue": f"{tag}:listeners", "expr": LISTENERS})
    return steps


async def test_a_good_edit_on_the_real_page_reloads_only_the_stage_frame_and_reports_the_mount_through_the_real_relay(tmp_path):
    core, pid, vid, revision, stage_id = await real_page(tmp_path)
    try:
        out = await drive(Url(f"http://127.0.0.1:{core.stack.cc_port}"), tmp_path, [
            *prelude(stage_id),
            edit(pid, vid, revision, {"style": "body{outline:3px solid #ff7a59}"}),
            {"wait": 600},
            {"frameValue": "outline", "object_id": stage_id,
             "expr": "getComputedStyle(document.body).outlineStyle==='solid'"},
            *survey("end", stage_id),
        ])
        reads = out["reads"]
        assert "failed" not in reads, reads["failed"]
        result = reads["edit"]
        assert result["status"] == "reloaded" and result["mounted"] is True, result        # the report crossed page -> relay -> Core
        assert reads["end:same_nodes"] == {stage_id: False, "user-a": True, "user-b": True}
        for oid in USER_WINDOWS:
            assert reads[f"end:born:{oid}"] and reads["end:listeners"][oid] == reads["listeners_before"][oid]
        assert reads[f"end:born:{stage_id}"] is None and reads["end:iframes"] == 3
        assert reads["end:sandboxes"] == [["allow-scripts", None]] * 3
        assert reads["end:band"]["kind"] == "ok" and "rechargée" in reads["end:band"]["text"]
        assert reads["outline"] is True                                                    # the new style is really applied
        scene = next(s for s in (await core.stack.core.presentation_studio.get_variant(pid, vid)).scenes if s.scene_id == S1)
        assert scene.prefab.prefab_id.startswith("presentation-studio.p") and scene.last_valid_pin is None and scene.source_revision == 1
        assert [e for e in core.stack.trace() if e.get("kind") == "presentation_studio.request.relayed"
                and e["data"]["action"] == "studio_mount_report"], "the page's report did not go through the relay"
        assert out["errors"] == [], out["errors"]
    finally:
        await core.__aexit__(None, None, None)


async def test_a_bad_edit_on_the_real_page_is_rolled_back_and_the_stage_frame_is_never_replaced(tmp_path):
    core, pid, vid, revision, stage_id = await real_page(tmp_path)
    try:
        out = await drive(Url(f"http://127.0.0.1:{core.stack.cc_port}"), tmp_path, [
            *prelude(stage_id),
            edit(pid, vid, revision, {"behavior": "jarvis.on('init', function () { throw new Error('boom at mount'); });"}),
            {"wait": 600},
            *survey("end", stage_id),
        ])
        reads = out["reads"]
        assert "failed" not in reads, reads["failed"]
        result = reads["edit"]
        assert result["status"] == "rolled_back" and result["code"] == "presentation_studio_mount_failed" and result["reason"] == "frame"
        assert "boom at mount" in result["message"]
        assert reads["end:same_nodes"] == {stage_id: True, "user-a": True, "user-b": True}     # the live frame is the very same node
        for oid in (stage_id, *USER_WINDOWS):
            assert reads[f"end:born:{oid}"] and reads["end:listeners"][oid] == reads["listeners_before"][oid], oid
        assert reads["end:iframes"] == 3
        assert reads["end:band"]["kind"] == "bad" and "annulée" in reads["end:band"]["text"]
        scene = next(s for s in (await core.stack.core.presentation_studio.get_variant(pid, vid)).scenes if s.scene_id == S1)
        assert scene.prefab.prefab_id == "jarvis.window" and scene.last_valid_pin is None and scene.source_revision == 2
        block = (await core.stack.core.scene.snapshot()).get_object(stage_id).payload.prefab
        assert (block.prefab_id, block.version) == ("jarvis.window", 1)
    finally:
        await core.__aexit__(None, None, None)

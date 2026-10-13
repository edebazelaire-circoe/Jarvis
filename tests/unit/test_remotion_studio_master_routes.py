"""Master target through the real routes (handoff jarvis-remotion-master-project-studio-export, Slice 05; `docs/remotion-master-project.md`
§ 9, § 11).

A real Core (real prefab store, real presentation studio, real `MasterProjectReader`) behind the real `LocalProtocolServer`, the real
Control Center in front, a fake Studio runner and a fake capability runner (no process). Proved: `GET .../master-project` gives the plan view
and writes nothing, the Control Center relays the same read; the Studio routes take the master body (ready -> schema 2, stale -> 409 with the
current key, incompatible -> 409 with the reason, mixed body -> 400, no acknowledgment -> 400) and refuse `publish` on a master.
"""

from __future__ import annotations

import pytest

from jarvis.adapters.file_local_capability_store import FileLocalCapabilityStore
from jarvis.domain.remotion_source import Composition
from jarvis.runtime.presentation_studio_relay import STUDIO_ROUTE, _READ_ROUTES
from tests.fakes.capture_stack import TOKEN
from tests.fakes.remotion_scene import SAMPLE, scene_candidate, scene_files
from tests.fakes.remotion_studio import FakeStudioRunner
from tests.unit.test_local_capability_host import FakeRunner
from tests.unit.test_presentation_studio_routes import Core, variant_body
from tests.unit.test_presentation_studio_upgrades_routes import tree

STUDIO = "/v1/local-capabilities/remotion/studio"
PREFABS = [f"presentation-studio.p000000000001.s00000000000{n}" for n in range(1, 4)]
SCENES = [f"pss_00000000000{c}" for c in "abc"]


def at(pid, vid):
    return f"/{pid}/variants/{vid}/master-project"


def remotion_scene(scene_id, prefab_id):
    return {"scene_id": scene_id, "prefab": {"id": prefab_id, "version": 1}, "title": scene_id, **SAMPLE}


class Rig:
    def __init__(self, core: Core, studio: FakeStudioRunner) -> None:
        self.core, self.studio = core, studio

    async def studio_call(self, method: str, path: str, **kwargs):
        async with self.core.http.request(method, self.core.stack.core_url + STUDIO + path,
                                          headers={"Authorization": f"Bearer {TOKEN}"}, **kwargs) as response:
            return response.status, await response.json(content_type=None)


@pytest.fixture
async def rig(tmp_path):
    studio = FakeStudioRunner()
    async with Core(tmp_path, local_capability_runner=FakeRunner(), local_capability_store=FileLocalCapabilityStore(tmp_path.resolve()),
                    remotion_studio_runner=studio) as core:
        prefabs = core.stack.core.prefabs
        for n, prefab_id in enumerate(PREFABS):
            composition = Composition("Scene", 1280, 720, 24 if n == 2 else 30, 90) if n == 2 else None
            await prefabs.save(scene_candidate(prefab_id, files=scene_files(f"// {n}\n"),
                                               **({"composition": composition} if composition else {})), actor="user")
        assert (await core.client.local_capability_action("remotion", "install"))["capability"]["status"] == "ready"
        yield Rig(core, studio)


async def deck(rig: Rig, prefabs) -> tuple[str, str]:
    _, created = await rig.core.call("POST", "", json={"title": "Maitre"})
    pid, variant = created["presentation"]["presentation_id"], created["variants"][0]
    status, saved = await rig.core.call("PUT", f"/{pid}/variants/{variant['variant_id']}",
                                        json=variant_body(variant, scenes=[remotion_scene(SCENES[i], p) for i, p in enumerate(prefabs)]))
    assert status == 200, saved
    return pid, variant["variant_id"]


def master_body(pid, vid, key, **extra):
    return {"kind": "variant_master", "presentation_id": pid, "variant_id": vid, "project_key": key,
            "acknowledge_unsandboxed_project": True, **extra}


def test_the_control_center_relays_the_read_only():
    assert ("GET", "studio_master_project", "/{presentation_id}/variants/{variant_id}/master-project") in _READ_ROUTES


async def test_the_live_readiness_read_is_the_plan_view_writes_nothing_and_is_relayed(rig):
    pid, vid = await deck(rig, PREFABS[:2])
    before = tree(rig.core, pid)
    status, body = await rig.core.call("GET", at(pid, vid))
    assert status == 200, body
    master = body["master"]
    assert master["status"] == "ready" and master["project_key"].startswith("mpk_") and master["variant_id"] == vid
    assert master["composition"] == {"id": "JarvisPresentation", "width": 1280, "height": 720, "fps": 30, "duration_in_frames": 180}
    assert [s["scene_id"] for s in master["scenes"]] == SCENES[:2] and "reason" not in master
    assert tree(rig.core, pid) == before and "launch" not in rig.studio.calls, "reading the plan writes nothing, starts nothing"
    status, via, _ = await rig.core.stack.call("GET", STUDIO_ROUTE + at(pid, vid))
    assert status == 200 and via == body
    status, missing = await rig.core.call("GET", at(pid, "psv_" + "0" * 32))
    assert status == 404 and missing["error"]["code"] == "presentation_studio_unknown_variant"
    status, refused = await rig.core.call("GET", at(pid, vid) + "?x=1")
    assert status == 400


async def test_an_incompatible_variant_reads_its_reason_and_the_studio_refuses_it(rig):
    pid, vid = await deck(rig, PREFABS)                                   # scene 3 is 24 fps
    _, body = await rig.core.call("GET", at(pid, vid))
    assert body["master"]["status"] == "incompatible" and body["master"]["reason"] == "master_fps_mismatch"
    assert "project_key" not in body["master"]
    status, refused = await rig.studio_call("POST", "/open", json=master_body(pid, vid, "mpk_" + "a" * 24))
    assert status == 409 and refused["error"]["code"] == "remotion_studio_master_incompatible"
    assert refused["error"]["reason"] == "master_fps_mismatch" and SCENES[2] in refused["error"]["scene_ids"]
    assert "launch" not in rig.studio.calls


async def test_the_studio_routes_open_a_master_refuse_a_stale_key_and_never_publish_it(rig):
    pid, vid = await deck(rig, PREFABS[:2])
    _, body = await rig.core.call("GET", at(pid, vid))
    key = body["master"]["project_key"]
    status, stale = await rig.studio_call("POST", "/open", json=master_body(pid, vid, "mpk_" + "0" * 24))
    assert status == 409 and stale["error"]["code"] == "remotion_studio_master_stale"
    assert (stale["error"]["project_key"], stale["error"]["scene_count"]) == (key, 2) and "variant_revision" in stale["error"]
    for bad, code in (({**master_body(pid, vid, key), "prefab_id": PREFABS[0]}, "remotion_studio_invalid"),
                      ({k: v for k, v in master_body(pid, vid, key).items() if k != "acknowledge_unsandboxed_project"},
                       "remotion_studio_ack_required")):
        status, refused = await rig.studio_call("POST", "/open", json=bad)
        assert status == 400 and refused["error"]["code"] == code
    status, opened = await rig.studio_call("POST", "/open", json=master_body(pid, vid, key))
    assert status == 200 and opened["studio"]["target"]["kind"] == "variant_master" and opened["studio"]["pin"] is None
    assert rig.studio.state["schema"] == 2 and any(p.startswith(f"src/scenes/{SCENES[1]}/") for p in rig.studio.work)
    status, synced = await rig.studio_call("POST", "/sync", json={})
    assert status == 400 and synced["error"]["code"] == "remotion_studio_ack_required"
    status, again = await rig.studio_call("POST", "/sync", json=master_body(pid, vid, key, discard_unpublished=True))
    assert status == 200 and again["studio"]["syncs"] == 1
    status, restarted = await rig.studio_call("POST", "/restart", json=master_body(pid, vid, key))
    assert status == 200 and restarted["studio"]["restarts"] == 1
    status, published = await rig.studio_call("POST", "/publish", json={
        "presentation_id": pid, "variant_id": vid, "scene_id": SCENES[0], "base": {"prefab_id": PREFABS[0], "version": 1},
        "digest": "0" * 64, "confirm_publish": True})
    assert status == 409 and published["error"]["code"] == "remotion_studio_publish_master_unsupported"
    status, scene = await rig.studio_call("POST", "/open", json={"prefab_id": PREFABS[0], "version": 1, "acknowledge_unsandboxed_scene": True})
    assert status == 200 and scene["studio"]["target"] == {"kind": "scene", "prefab_id": PREFABS[0], "version": 1}
    assert rig.studio.state["schema"] == 1 and rig.studio.launches.count(None) == 2, "back to a scene in the same process"


def test_the_page_client_sends_the_master_body_with_its_own_acknowledgment_and_reads_the_plan(tmp_path):
    """Minimal client plumbing (the Variants entrypoints are Slice 08): a master body gets `acknowledge_unsandboxed_project`, never the
    scene field; a scene body is unchanged; `masterProject` reads the relayed plan view."""

    from tests.unit.test_control_center_remotion_studio import run_node

    result = run_node(tmp_path, """
      const calls=[];
      const client=C.createClient({fetchImpl:async(path,options)=>{calls.push([path,options.method,options.body||null]);
        return {ok:true,status:200,json:async()=>({studio:{status:'ready'},master:{status:'ready',project_key:'mpk_x'}})}}});
      const body={kind:C.MASTER_KIND,presentation_id:'pst_1',variant_id:'psv_2',project_key:'mpk_x'};
      for(const action of ['open','sync','restart'])await client.write(action,body);
      await client.write('open',{prefab_id:'a',version:3});
      const plan=await client.masterProject('pst 1','psv/2');
      return {calls,plan,errors:[C.errorText('remotion_studio_master_stale'),C.errorText('remotion_studio_master_incompatible'),
        C.errorText('remotion_studio_publish_master_unsupported')]};""")
    master = '{"kind":"variant_master","presentation_id":"pst_1","variant_id":"psv_2","project_key":"mpk_x","acknowledge_unsandboxed_project":true}'
    assert [c[2] for c in result["calls"][:3]] == [master] * 3 and [c[0].rsplit("/", 1)[1] for c in result["calls"][:3]] == ["open", "sync", "restart"]
    assert result["calls"][3][2] == '{"prefab_id":"a","version":3,"acknowledge_unsandboxed_scene":true}'
    assert result["calls"][4][:2] == ["/api/presentation-studio/presentations/pst%201/variants/psv%2F2/master-project", "GET"]
    assert result["plan"] == {"status": "ready", "project_key": "mpk_x"} and all(result["errors"])

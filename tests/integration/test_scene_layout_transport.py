"""Real SQLite + local Core HTTP + Control Center relay for arbitrary layouts."""

import json

from jarvis.protocol import scene_wire
from tests.integration.test_scene_transport import core, placed_note, snapshot_of, stack  # noqa: F401 - pytest fixtures


def layout_wire(*, compare=False):
    targets = [{"object_id": "n0", "geometry": {"x": 1, "y": 2, "w": 20, "h": 15}},
               {"object_id": "n1", "geometry": {"x": 25, "y": 2, "w": 30, "h": 15}}]
    if compare:
        for index, target in enumerate(targets):
            target["expected_geometry"] = {"x": 20 * index, "y": 0, "w": 10, "h": 10}
    return {"schema_version": 1, "op": "layout_selection", "actor": "user",
            "selection": {"ids": ["n0", "n1"]}, "targets": targets, "pin": True}


async def seed(process):
    for index in range(2):
        status, body, _ = await process.request("POST", "/v1/scene/commands", json=placed_note(f"n{index}", 20 * index))
        assert status == 200 and body["outcome"] == "applied"


async def test_core_applies_one_layout_revision_and_refuses_stale_compare_without_writes(core):
    await seed(core)
    status, body, _ = await core.request("POST", "/v1/scene/commands", json=layout_wire(compare=True))
    assert status == 200 and body["outcome"] == "applied" and body["revision"] == 3
    assert body["batch"]["changed_ids"] == ["n0", "n1"]
    assert len(body["patch"]["ops"]) == 2 and body["patch"]["revision"] == 3
    before = await snapshot_of(core)
    status, refused, _ = await core.request("POST", "/v1/scene/commands", json=layout_wire(compare=True))
    assert status == 200 and (refused["outcome"], refused["reason"], refused["revision"], refused["patch"]) == (
        "invalid", "geometry_changed", 3, None)
    assert refused["batch"]["refused"] == [{"id": object_id, "reason": "geometry_changed", "field": "ids"}
                                           for object_id in ("n0", "n1")]
    assert await snapshot_of(core) == before


async def test_control_center_forces_user_and_omits_large_patch_while_poll_delivers_it(stack):
    process, _, client = stack
    await seed(process)
    before = await (await client.get("/api/scene")).json()
    command = layout_wire(compare=True)
    forbidden = await client.post("/api/scene/commands", json={**command, "actor": "brain"})
    assert forbidden.status == 403
    command.pop("actor")
    response = await client.post("/api/scene/commands", json=command)
    body = await response.json()
    assert response.status == 200 and body["outcome"] == "applied" and body["revision"] == 3
    assert body["patch"] is None and body["patch_omitted"] is True
    assert body["batch"]["matched_ids"] == body["batch"]["changed_ids"] == ["n0", "n1"]
    query = (f"/api/scene/patches?scene_id={before['scene_id']}&epoch={before['epoch']}"
             "&after=2&wait_s=0")
    patches = await (await client.get(query)).json()
    assert len(patches["patches"]) == 1
    objects = [op["object"] for op in patches["patches"][0]["ops"]]
    assert [item["geometry"] for item in objects] == [target["geometry"] for target in command["targets"]]
    assert all(item["constraints"]["placed_by"] == "user" and item["constraints"]["pinned_by_user"] for item in objects)


async def test_bad_geometry_or_selection_mismatch_is_400_and_runtime_is_403(core):
    await seed(core)
    before = await snapshot_of(core)
    for malformed in ("geometry", "selection"):
        command = layout_wire()
        if malformed == "geometry":
            command["targets"][1]["geometry"]["w"] = -1
        else:
            command["selection"]["ids"].append("missing-target")
        status, answer, _ = await core.request("POST", "/v1/scene/commands", json=command)
        assert status == 400 and answer["error"]["code"] == "invalid_request"
    status, answer, _ = await core.request("POST", "/v1/scene/commands", json={**layout_wire(), "actor": "runtime"})
    assert status == 403 and answer["error"]["code"] == scene_wire.SCENE_ACTOR_FORBIDDEN
    assert await snapshot_of(core) == before


async def test_bounded_512_member_request_over_wire_budget_is_413_never_chunked(core):
    await seed(core)
    before = await snapshot_of(core)
    ids = [f"{i:03d}" + "x" * 125 for i in range(512)]
    box = {"x": 0, "y": 0, "w": 10, "h": 10}
    command = {"schema_version": 1, "op": "layout_selection", "actor": "user", "selection": {"ids": ids},
               "targets": [{"object_id": object_id, "geometry": box, "expected_geometry": box} for object_id in ids]}
    assert len(scene_wire.compact_json(command).encode("utf-8")) > scene_wire.MAX_SCENE_COMMAND_BYTES
    status, answer, _ = await core.request("POST", "/v1/scene/commands", data=json.dumps(command))
    assert status == 413 and answer["error"]["code"] == scene_wire.PAYLOAD_TOO_LARGE
    assert await snapshot_of(core) == before

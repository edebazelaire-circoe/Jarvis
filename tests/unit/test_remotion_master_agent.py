"""Voice generation and re-edit on the master path (handoff jarvis-remotion-master-project-studio-export, Slice 07;
`docs/remotion-master-project.md` § 12).

What this file proves:
- the § 3 user sentences live once (`remotion_master_sentences`), word for word as the contract, and the agent's compact `master` block
  only PROJECTS the plan view Core computed (never decides readiness);
- the agent sees readiness where it already looks: `presentation_inspect` variant (real Core: an HTML deck is incompatible, said with its
  sentence), `presentation_source` write and preview, `presentation_draft_assemble`; a failed readiness read never fails the call it rides;
- `remotion_export` `scope`: `master` = the whole video (mp4 only, no `scene_id`), labelled as such; absent or `scene` = today's body
  byte for byte, labelled « une scène seule »; an incompatible variant is refused with the § 3 sentence, scene exports offered, nothing
  written after the refusal;
- a standing source edit (new version + repin) changes the live `project_key` with no sync call, and the next whole-video export renders
  the new pin (real studio, prefab store, source-edit service, packager and render service; fake browser and compiler only);
- the native authoring defaults: a native bundle gets 1920x1080 @ 30 for what it leaves out; guided bundles keep 1280x720.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re

import pytest

from jarvis.domain.remotion_master_project import MasterReason
from jarvis.domain.remotion_master_sentences import REASON_SENTENCES, UNKNOWN_REASON_SENTENCE, agent_view, reason_sentence
from jarvis.protocol.client import CoreProtocolError
from jarvis.runtime.presentation_studio_mcp_support import PresentationToolError
from jarvis.runtime.presentation_studio_mcp_tools import PresentationTools
from tests.unit.remotion_mcp_world import JOB, PID, SID, VID, make_tools

ROOT = Path(__file__).resolve().parents[2]
KEY = "mpk_" + "1" * 24
READY = {"presentation_id": PID, "variant_id": VID, "variant_revision": 5, "generator_version": 1, "status": "ready", "project_key": KEY,
         "composition": {"id": "JarvisPresentation", "width": 1920, "height": 1080, "fps": 30, "duration_in_frames": 450},
         "scenes": [{"scene_id": SID}, {"scene_id": "pss_aaaaaaaaaaaa"}, {"scene_id": "pss_bbbbbbbbbbbb"}], "public_assets": [],
         "totals": {"files": 20, "bytes": 9000}}
COLLISION = {"presentation_id": PID, "variant_id": VID, "variant_revision": 5, "generator_version": 1, "status": "incompatible",
             "reason": "master_public_asset_collision",
             "detail": f"public/voice.mp3: scene 1 ({SID}) and scene 2 (pss_aaaaaaaaaaaa) bring different files at one path",
             "scene_ids": [SID, "pss_aaaaaaaaaaaa"]}


# ------------------------------------------------------------------ sentences and the compact view


def test_every_reason_has_the_contract_sentence_word_for_word():
    text = (ROOT / "docs" / "remotion-master-project.md").read_text(encoding="utf-8")
    rows = dict(re.findall(r"^\| \d+ \| `(master_[a-z_]+)` \| [^|]+ \| « (.+) » \|$", text, re.M))
    assert set(rows) == {reason.value for reason in MasterReason} == {reason.value for reason in REASON_SENTENCES}
    for reason, sentence in REASON_SENTENCES.items():
        assert rows[reason.value] == sentence, reason


def test_the_placeholders_are_filled_from_the_detail_or_left_generic():
    assert reason_sentence("master_public_asset_collision", COLLISION["detail"]) == (
        "Deux scènes utilisent le même nom de fichier « public/voice.mp3 » pour des contenus différents.")
    assert reason_sentence("master_public_asset_collision", "") == "Deux scènes utilisent le même nom de fichier pour des contenus différents."
    assert "(scène 2)" in reason_sentence("master_source_unavailable", "scene 2 (pss_aaaaaaaaaaaa): prefab_store_missing")
    assert reason_sentence("master_source_unavailable", "") == (
        "La source d'une scène est introuvable ou altérée : la vidéo entière n'est pas disponible.")
    assert reason_sentence("master_fps_mismatch") == REASON_SENTENCES[MasterReason.FPS_MISMATCH]
    assert reason_sentence("master_from_the_future") == UNKNOWN_REASON_SENTENCE, "an unknown reason is never re-labelled"


def test_the_agent_view_projects_the_plan_and_adds_nothing_it_did_not_read():
    assert agent_view(READY) == {"status": "ready", "variant_revision": 5, "project_key": KEY, "scenes": 3, "duration_s": 15.0,
                                 "spec": "1920x1080@30"}
    view = agent_view(COLLISION)
    assert view["status"] == "incompatible" and view["reason"] == "master_public_asset_collision"
    assert "« public/voice.mp3 »" in view["say"] and view["scene_ids"] == [SID, "pss_aaaaaaaaaaaa"] and "project_key" not in view
    assert agent_view({"status": "incompatible", "reason": "master_empty", "detail": "", "scene_ids": []}) == {
        "status": "incompatible", "reason": "master_empty", "say": REASON_SENTENCES[MasterReason.EMPTY]}


# ------------------------------------------------------------------ readiness where the agent already looks


class MasterCore:
    """The typed Core client, scripted: a variant, a source edit that stands, a preview, an assembly, and the master plan view."""

    def __init__(self, master: dict | Exception) -> None:
        self.master = master
        self.calls: list[str] = []

    async def call(self, fn):
        return await fn(self)

    def __getattr__(self, name):
        async def method(*args):
            self.calls.append(name)
            if name == "presentation_studio_master_project":
                if isinstance(self.master, Exception):
                    raise self.master
                return {"master": self.master}
            if name == "presentation_studio_work":
                return {}
            if name == "presentation_studio_variant":
                return {"revision": 5, "scenes": [{"scene_id": SID, "title": "Un", "prefab": {"id": "p"}}]}
            if name == "presentation_studio_source_edit":
                return {"status": "reloaded", "prefab": {"id": "p", "version": 2}, "previous": {"id": "p", "version": 1}, "mounted": True}
            if name == "remotion_render_preview":
                return {"preview": {"prefab": {"id": "p", "version": 2}, "frames": [{"frame": 1, "path": "f.jpg"}], "elapsed_ms": 9}}
            if name == "presentation_studio_authoring_assemble":
                return {"status": "assembled", "presentation_id": PID, "active_variant_id": VID, "report": {"warnings": []}}
            raise AssertionError(name)
        return method


async def test_inspect_variant_carries_the_master_block():
    core = MasterCore(READY)
    out = await PresentationTools(core).inspect("variant", presentation_id=PID, variant_id=VID)
    assert out["master"]["status"] == "ready" and out["master"]["project_key"] == KEY and out["master"]["scenes"] == 3
    assert "presentation_studio_master_project" in core.calls


async def test_a_standing_source_write_and_a_preview_carry_the_block_after_the_write():
    core = MasterCore(COLLISION)
    tools = PresentationTools(core)
    wrote = await tools.source("write", presentation_id=PID, variant_id=VID, scene_id=SID, files={"src/Scene.tsx": "x"})
    assert wrote["status"] == "reloaded" and wrote["master"]["reason"] == "master_public_asset_collision"
    assert core.calls.index("presentation_studio_master_project") > core.calls.index("presentation_studio_source_edit"), "read AFTER"
    seen = await tools.source("preview", presentation_id=PID, variant_id=VID, scene_id=SID, frames=[1])
    assert seen["master"]["status"] == "incompatible" and "public/voice.mp3" in seen["master"]["say"]


async def test_the_assembled_deck_says_at_once_whether_it_is_one_whole_video():
    core = MasterCore(READY)
    out = await PresentationTools(core).draft("assemble", brief={"title": "T"}, draft={"scenes": []})
    assert out["master"] == agent_view(READY)


@pytest.mark.parametrize("failure", [CoreProtocolError(503, "core_stopping", "stopping"), OSError("connection reset")])
async def test_a_failed_readiness_read_never_fails_the_call_it_rides_and_is_journaled(tmp_path, failure):
    from jarvis.runtime.journal import RuntimeJournal

    core = MasterCore(failure)
    tools = PresentationTools(core, journal=RuntimeJournal(tmp_path))
    out = await tools.source("write", presentation_id=PID, variant_id=VID, scene_id=SID, files={"src/Scene.tsx": "x"})
    assert out["status"] == "reloaded" and out["master"]["status"] == "unknown" and out["master"]["error"]
    rows = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(r["kind"] == "presentation_studio.master_unread" and r["level"] == "warning" for r in rows)


async def test_real_core_inspect_variant_reads_the_live_plan(tmp_path):
    """Real Core over the real protocol: the playable world's scenes are HTML prefabs, so the whole video is not available, said."""

    from tests.unit.presentation_studio_mcp_world import open_world

    core, world = await open_world(tmp_path)
    try:
        out = await world.tools.inspect("variant")
        master = out["master"]
        assert master["status"] == "incompatible" and master["reason"] == "master_engine_not_remotion", master
        assert master["say"] == REASON_SENTENCES[MasterReason.ENGINE_NOT_REMOTION]
        assert world.spy.named("presentation_studio_master_project"), "read through the typed client, the route Studio and UI read"
    finally:
        await core.__aexit__(None, None, None)


# ------------------------------------------------------------------ remotion_export scope


MASTER_JOB = {"job_id": JOB, "artifact_id": "jart_x", "state": "queued", "phase": "queued", "format": "mp4", "percent": 0, "elapsed_s": 0.0,
              "can_cancel": True, "error_code": None, "scope": "master", "project_key": KEY, "scene_count": 3, "scene_id": None}


async def test_the_whole_video_export_sends_scope_master_and_says_it_is_the_whole_video(tmp_path):
    tools, core, _ = make_tools(tmp_path, turn=True)

    async def create(body):
        core._record("remotion_render_create", body)
        return {"job": MASTER_JOB}

    core.remotion_render_create = create
    out = await tools.export("start", format="mp4", settings={"scope": "master"}, user_request="exporte la vidéo")
    (request,) = core.named("remotion_render_create")[0]
    assert request["settings"] == {"scope": "master"} and "scene_id" not in request["settings"]
    assert out["video"] == "whole" and "vidéo entière (3 scènes)" in out["say"]
    assert out["job"]["scope"] == "master" and out["job"]["project_key"] == KEY and out["job"]["scene_count"] == 3


@pytest.mark.parametrize("settings", [None, {"scope": "scene", "scene_id": SID}, {"scene_id": SID}])
async def test_a_scene_export_keeps_todays_body_and_never_calls_itself_the_video(tmp_path, settings):
    tools, core, _ = make_tools(tmp_path, turn=True)
    out = await tools.export("start", format="mp4", settings=settings, user_request="exporte la scène")
    (request,) = core.named("remotion_render_create")[0]
    assert "scope" not in request.get("settings", {}), "an explicit scene scope is never sent: the body is today's"
    assert request.get("settings", {}) == ({"scene_id": SID} if settings else {})
    assert out["video"] == "scene" and "pas la vidéo entière" in out["say"] and out["job"]["scope"] == "scene"


@pytest.mark.parametrize("fmt,settings,code", [
    ("mp4", {"scope": "master", "scene_id": SID}, "invalid_setting"), ("still", {"scope": "master"}, "invalid_format"),
    ("pdf", {"scope": "master"}, "invalid_format"), ("mp4", {"scope": "variant"}, "invalid_setting")])
async def test_invalid_scope_combinations_are_refused_before_anything_is_sent(tmp_path, fmt, settings, code):
    tools, core, _ = make_tools(tmp_path, turn=True)
    with pytest.raises(PresentationToolError) as caught:
        await tools.export("start", format=fmt, settings=settings, user_request="exporte la vidéo")
    assert caught.value.code == code
    assert core.calls == [], "refused before the turn check and before any Core call"


async def test_an_incompatible_variant_is_refused_with_its_sentence_scene_exports_offered_and_nothing_changed(tmp_path):
    tools, core, _ = make_tools(tmp_path, turn=True)
    core.refusals["remotion_render_create"] = CoreProtocolError(
        409, "presentation_render_master_incompatible", "the whole video cannot be built",
        details={"reason": "master_fps_mismatch", "detail": f"scene 1 ({SID}) is 30 fps, scene 2 (pss_aaaaaaaaaaaa) is 25 fps",
                 "scene_ids": [SID, "pss_aaaaaaaaaaaa"]})
    with pytest.raises(PresentationToolError) as caught:
        await tools.export("start", format="mp4", settings={"scope": "master"}, user_request="exporte la vidéo")
    message = str(caught.value)
    assert caught.value.code == "presentation_render_master_incompatible"
    assert REASON_SENTENCES[MasterReason.FPS_MISMATCH] in message and "scope scene" in message and "Rien n'a été exporté ni modifié" in message
    assert core.writes == ["remotion_render_create"], "one attempt, no retry, no other write (no variant is rewritten)"


async def test_the_server_schema_admits_scope_and_refuses_anything_else():
    from mcp.server.fastmcp.exceptions import ToolError
    from mcp.shared.memory import create_connected_server_and_client_session

    from jarvis.runtime.remotion_mcp import build_server

    class Recorder:
        def __init__(self):
            self.seen = []

        async def export(self, op, **kwargs):
            self.seen.append(kwargs["settings"])
            return {"ok": True}

    recorder = Recorder()
    server = build_server(tools=recorder)  # type: ignore[arg-type]
    async with create_connected_server_and_client_session(server._mcp_server) as session:
        listed = {t.name: t for t in (await session.list_tools()).tools}
        settings = json.dumps(listed["remotion_export"].inputSchema)
        assert '"scope"' in settings and '"master"' in settings
        done = await session.call_tool("remotion_export", {"op": "start", "format": "mp4", "settings": {"scope": "master"},
                                                           "user_request": "exporte la vidéo"})
        assert not done.isError and recorder.seen == [{"scope": "master"}]
        bad = await session.call_tool("remotion_export", {"op": "start", "format": "mp4", "settings": {"scope": "all"}, "user_request": "x"})
        assert bad.isError and recorder.seen == [{"scope": "master"}]
    assert ToolError  # the strict server turns schema refusals into tool errors (above): nothing reached the tools


# ------------------------------------------------------------------ a standing edit refreshes the whole video (real service stack)


NEW_SCENE_MARK = "#2d6cdf"


@pytest.fixture
async def stack(tmp_path):
    from jarvis.core.presentation_artifacts import PresentationArtifacts
    from jarvis.core.presentation_render_service import PresentationRenderService
    from jarvis.core.presentation_snapshot_packager import PresentationPackager
    from jarvis.core.remotion_master_project import MasterProjectReader
    from tests.fakes.presentation_world import T0, PresentationWorld
    from tests.fakes.remotion_edit_rig import RemotionRig
    from tests.fakes.remotion_render import FakeRenderRunner

    (tmp_path / "rig").mkdir()
    rig = await RemotionRig(tmp_path / "rig").open()
    world = await PresentationWorld().open(tmp_path / "world")
    runtime = {"remotion_version": "4.0.534"}
    snapshots = PresentationArtifacts(rig.studio, world.artifacts, world.links, diagnostics=world.sink)
    packager = PresentationPackager(studio=rig.studio, artifacts=world.artifacts, snapshots=snapshots, prefabs=rig.prefabs,
                                    resolver=world.resolver, runtime=lambda: runtime, clock=lambda: T0, diagnostics=world.sink)
    reader = MasterProjectReader(studio=rig.studio, prefabs=rig.prefabs)
    runner = FakeRenderRunner(tmp_path / "runner")
    service = PresentationRenderService(artifacts=world.artifacts, snapshots=snapshots, packager=packager, runner=runner,
                                        installed_engine=runner.installed_engine, diagnostics=world.sink, live_master=reader.live_plan,
                                        new_job_id=iter(f"rj_{n:012x}" for n in range(1, 99)).__next__)
    try:
        yield rig, reader, service, runner
    finally:
        await service.stop()
        await world.close()
        await rig.close()


async def finished(service, job_id: str) -> dict:
    for _ in range(1000):
        view = service.get(job_id)
        if view["state"] in ("complete", "failed", "cancelled"):
            return view
        await asyncio.sleep(0.01)
    raise AssertionError(service.get(job_id))


async def export_master(rig, service) -> dict:
    view = await rig.studio.get(rig.pid)
    variant = next(v for v in view.variants if v.variant_id == rig.vid)
    job = await service.export(presentation_id=rig.pid, variant_id=rig.vid, expected_presentation_revision=view.presentation.revision,
                               expected_variant_revision=variant.revision, authorised_boards={"default"}, render_format="mp4",
                               settings={"scope": "master"})
    return job


async def test_a_standing_source_edit_changes_the_key_and_the_next_whole_video_export_renders_the_new_pin(stack):
    from tests.fakes.remotion_edit_rig import SCENE_TSX, SID as EDITED

    rig, reader, service, runner = stack
    before = await reader.live_plan(rig.pid, rig.vid)
    assert before.ready, before.to_wire()
    first = await export_master(rig, service)
    assert first["scope"] == "master" and first["project_key"] == before.project_key and first["scene_count"] == 2
    assert (await finished(service, first["job_id"]))["state"] == "complete"

    edited_tsx = SCENE_TSX.replace("#101820", NEW_SCENE_MARK)
    result = await rig.edit({"sources": {"src/Scene.tsx": edited_tsx}}, actor="brain")   # what presentation_source write sends
    assert result.status.stood, result.to_dict()

    after = await reader.live_plan(rig.pid, rig.vid)
    assert after.ready and after.project_key != before.project_key, "no sync call: the live plan follows the repin"
    edited = next(s for s in after.scenes if s.scene_id == EDITED)
    assert (edited.prefab_id, edited.version) == (result.prefab.prefab_id, result.prefab.version)

    second = await export_master(rig, service)
    assert second["job_id"] != first["job_id"] and second.get("deduplicated") is not True, "never the older derivative"
    assert second["project_key"] == after.project_key
    assert (await finished(service, second["job_id"]))["state"] == "complete"
    mounted = runner.files[second["job_id"]][f"src/scenes/{EDITED}/Scene.tsx"]
    assert NEW_SCENE_MARK.encode() in mounted and b"#101820" not in mounted, "the new pin is what the whole video renders"
    assert NEW_SCENE_MARK.encode() not in runner.files[first["job_id"]][f"src/scenes/{EDITED}/Scene.tsx"]


# ------------------------------------------------------------------ authoring defaults and guidance


def test_a_native_bundle_gets_the_native_deck_spec_and_a_guided_bundle_keeps_its_default():
    from jarvis.domain.presentation_studio_authoring_remotion import (
        DEFAULT_COMPOSITION, NATIVE_DEFAULT_COMPOSITION, generate_source,
    )
    from jarvis.adapters.remotion_compiler import shipped_engine_pin

    raw = {"title": "Scene", "files": {"src/Scene.tsx": "export default function Scene() { return null; }\n"}}
    native = generate_source("s1", raw, shipped_engine_pin(), "b", native=True).candidate["manifest"]["source"]["composition"]
    guided = generate_source("s1", raw, shipped_engine_pin(), "b").candidate["manifest"]["source"]["composition"]
    assert (native["width"], native["height"], native["fps"]) == (1920, 1080, 30) == tuple(NATIVE_DEFAULT_COMPOSITION[k] for k in ("width", "height", "fps"))
    assert (guided["width"], guided["height"], guided["fps"]) == (1280, 720, 30) == tuple(DEFAULT_COMPOSITION[k] for k in ("width", "height", "fps"))
    partial = generate_source("s1", {**raw, "composition": {"duration_in_frames": 90}}, shipped_engine_pin(), "b", native=True)
    assert partial.candidate["manifest"]["source"]["composition"]["width"] == 1920


def test_the_native_guide_and_the_author_playbook_teach_one_whole_video_by_construction():
    from jarvis.domain.presentation_studio_authoring_guide import MASTER_HINT, NATIVE_DECK_SPEC, draft_guide
    from jarvis.runtime.presentation_playbooks import AUTHOR_PLAYBOOK

    guide = draft_guide("native")
    assert guide["draft"]["master"] == MASTER_HINT and MASTER_HINT in AUTHOR_PLAYBOOK
    for needle in ("width, height", "fps", "1920x1080", "presentation_source read", "public/", "staticFile()", "getInputProps", "master"):
        assert needle in MASTER_HINT, needle
    for needle in ("require", "\\u"):
        assert needle in guide["draft"]["isolation"], needle
    for bundle in guide["example"]["draft"]["prefabs"]:
        spec = bundle["remotion"]["composition"]
        assert {k: spec[k] for k in NATIVE_DECK_SPEC} == NATIVE_DECK_SPEC == {"width": 1920, "height": 1080, "fps": 30}
    assert "n'ouvre pas Remotion Studio" in AUTHOR_PLAYBOOK
    # Native stays permissive: the hint is about technical compatibility, never a content or style rule.
    for forbidden in ("props.theme", "controls", "partition"):
        assert forbidden not in MASTER_HINT


def test_the_guided_example_and_layouts_keep_their_spec():
    from jarvis.domain.presentation_studio_authoring_guide import draft_guide

    guided = draft_guide()
    assert guided["example"]["draft"]["prefabs"][0]["remotion"]["composition"]["width"] == 1280
    assert all(layout["remotion"]["composition"]["width"] == 1280 for layout in guided["layouts"].values())


def test_the_brain_prompt_routes_the_video_to_scope_master_and_never_calls_a_scene_the_video():
    from jarvis.runtime.claude_local import BRAIN_REMOTION_PROMPT

    for needle in ("scope master", "la vidéo entière", "master.status", "une scène exportée n'est jamais « la vidéo »",
                   "un ancien export n'est pas la vidéo à jour"):
        assert needle in BRAIN_REMOTION_PROMPT, needle

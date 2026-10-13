"""Master Remotion project planner (handoff jarvis-remotion-master-project-studio-export, Slice 03; `docs/remotion-master-project.md` §2-5).

Pure planner matrix on real parsed sources (`tests.fakes.remotion_scene`), then the live read seam and the frozen builder on a real
`PresentationWorld` (real `PrefabService`, real packager): the same pins give the same key from the live variant and from the snapshot.
"""

from __future__ import annotations

import hashlib
import json
import re

import pytest

from jarvis.core.remotion_master_project import MasterProjectReader
from jarvis.domain import remotion_master_project as M
from jarvis.domain.prefab import PrefabRef
from jarvis.domain.presentation_studio import StudioScene
from jarvis.domain.presentation_studio_engine import Engine
from jarvis.domain.remotion_master_generated import BOUNDARY_FILE, PACKAGE_FILE, PRESENTATION_FILE, ROOT_FILE, is_generated
from jarvis.domain.remotion_master_project import MasterInputs, MasterReason as R, PinSource, plan_master
from jarvis.domain.remotion_source import Composition, EnginePin, decode_candidate_files, parse_source, parse_source_block
from tests.fakes.presentation_world import SCENE_ID, PresentationWorld
from tests.fakes.remotion_scene import COMPOSITION, ENGINE, PNG_1X1, SCENE_TSX, scene_candidate, scene_files

IDS = ("pss_00000000000a", "pss_00000000000b", "pss_00000000000c", "pss_00000000000d")
PREFABS = tuple(f"presentation-studio.p000000000001.s00000000000{n}" for n in range(1, 5))
RED_PNG = bytes.fromhex("89504e470d0a1a0a") + b"\x00" * 24  # valid PNG signature, different bytes


def source(files=None, composition: Composition = COMPOSITION, engine: EnginePin = ENGINE):
    candidate = scene_candidate(files=files or scene_files(), composition=composition, engine=engine)
    return parse_source(parse_source_block(candidate["manifest"]["source"]),
                        decode_candidate_files(candidate["sources"], candidate["assets"]))


def scene(n: int, *, version: int = 1, title: str = "", props=None, data=None) -> StudioScene:
    return StudioScene(IDS[n], PrefabRef(PREFABS[n], version), title=title, props=dict(props or {}), data=dict(data or {}))


def inputs(scenes, pins, *, engine=Engine.REMOTION, revision=3, live=None) -> MasterInputs:
    return MasterInputs("pst_" + "0" * 32, "psv_" + "0" * 32, revision, engine, tuple(scenes), pins, live or {})


def pin(n: int, version: int = 1):
    return (PREFABS[n], version)


def three(**sources):
    """A homogeneous 3-scene variant: same spec, same engine, each its own pin."""

    scenes = [scene(n) for n in range(3)]
    pins = {pin(n): PinSource.remotion(sources.get(f"s{n}") or source()) for n in range(3)}
    return scenes, pins


def generated_props(text: str) -> dict[int, dict]:
    """`{position: props}` as the generated `Presentation.tsx` hands them to each scene (`JSON.parse` of a JSON string literal)."""

    return {int(n): json.loads(json.loads(literal))
            for n, literal in re.findall(r'^const props(\d+): Record<string, unknown> = JSON\.parse\((".*")\);$', text, flags=re.M)}


def failed(plan, reason):
    assert plan.status is M.MasterStatus.INCOMPATIBLE and plan.reason is reason, (plan.reason, plan.detail)
    assert plan.project_key is None and len(plan.detail) <= M.MAX_DETAIL_CHARS
    return plan


# ------------------------------------------------------------------ ready and the key


def test_a_homogeneous_three_scene_variant_is_ready_and_its_plan_is_deterministic():
    scenes, pins = three()
    plan = plan_master(inputs(scenes, pins))
    assert plan.ready and M.PROJECT_KEY.fullmatch(plan.project_key)
    assert plan == plan_master(inputs(scenes, pins)) and plan.to_wire() == plan_master(inputs(scenes, pins)).to_wire()
    assert plan.composition.to_dict() == {"id": "JarvisPresentation", "width": 1280, "height": 720, "fps": 30, "duration_in_frames": 270}
    assert [(s.scene_id, s.from_frame, s.duration_in_frames) for s in plan.scenes] == [(IDS[0], 0, 90), (IDS[1], 90, 90), (IDS[2], 180, 90)]
    first = plan.scenes[0]
    assert (first.mount, first.entry, first.engine_version) == (f"src/scenes/{IDS[0]}/", f"src/scenes/{IDS[0]}/Scene.tsx", "4.0.534")
    # one identical public/dot.png in every pin: merged once, owned by the three scenes
    assert [a.to_dict()["path"] for a in plan.public_assets] == ["public/dot.png"]
    assert plan.public_assets[0].scene_ids == IDS[:3]
    assert set(plan.generated) == {PACKAGE_FILE, ROOT_FILE, PRESENTATION_FILE, BOUNDARY_FILE} and all(map(is_generated, plan.generated))
    modules = source().block.modules
    assert plan.totals.files == 3 * len(modules) + 1 + 4
    assert plan.totals.bytes == (3 * sum(len(source().files[m]) for m in modules) + len(PNG_1X1)
                                 + sum(len(b) for b in plan.generated.values()))


def test_the_key_is_exactly_the_documented_canonical_digest():
    scenes, pins = three()
    plan = plan_master(inputs(scenes, pins))
    digest = source().digest
    empty = hashlib.sha256(b'{"data":{},"props":{}}').hexdigest()
    expected = {"generator_version": 1, "spec": [1280, 720, 30],
                "scenes": [[IDS[n], PREFABS[n], 1, digest, empty] for n in range(3)],
                "public_assets": [["public/dot.png", hashlib.sha256(PNG_1X1).hexdigest()]]}
    canonical = json.dumps(expected, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    assert plan.project_key == "mpk_" + hashlib.sha256(canonical).hexdigest()[:24]


def test_the_generated_composition_follows_the_variant_order_and_the_merged_props():
    scenes, pins = three()
    scenes[1] = scene(1, props={"title": "Deux"})
    plan = plan_master(inputs(scenes, pins))
    root = plan.generated[ROOT_FILE].decode()
    assert 'id="JarvisPresentation"' in root and "durationInFrames={270}" in root and "fps={30}" in root
    text = plan.generated[PRESENTATION_FILE].decode()
    assert text.index(f"../scenes/{IDS[0]}/Scene") < text.index(f"../scenes/{IDS[1]}/Scene") < text.index(f"../scenes/{IDS[2]}/Scene")
    assert generated_props(text)[2] == {"title": "Deux"} and text.count("<Series.Sequence durationInFrames={90}>") == 3
    assert f'import Scene1 from "../scenes/{IDS[0]}/Scene.tsx";' in text, "the exact entry file, extension included"
    assert "jarvis_master_scene_failed:" in plan.generated[BOUNDARY_FILE].decode()
    assert json.loads(plan.generated[PACKAGE_FILE]) == {"name": "jarvis-studio-master", "private": True, "version": "0.0.0"}


def test_reorder_repin_new_version_props_data_and_scene_count_change_the_key():
    scenes, pins = three()
    base = plan_master(inputs(scenes, pins)).project_key
    reordered = plan_master(inputs([scenes[2], scenes[0], scenes[1]], pins))
    assert reordered.project_key != base and [s.scene_id for s in reordered.scenes] == [IDS[2], IDS[0], IDS[1]]
    edited = source(scene_files(title_suffix="// v2\n"))
    repinned = plan_master(inputs([scenes[0], scene(1, version=2), scenes[2]], {**pins, pin(1, 2): PinSource.remotion(edited)}))
    assert repinned.ready and repinned.project_key != base
    same_bytes = plan_master(inputs([scenes[0], scene(1, version=2), scenes[2]], {**pins, pin(1, 2): PinSource.remotion(source())}))
    assert same_bytes.project_key not in (base, repinned.project_key), "the exact version is an input, even with identical bytes"
    assert plan_master(inputs([scenes[0], scene(1, props={"title": "x"}), scenes[2]], pins)).project_key != base
    assert plan_master(inputs([scenes[0], scene(1, data={"k": 1}), scenes[2]], pins)).project_key != base
    assert plan_master(inputs(scenes[:2], pins)).project_key != base
    assert plan_master(inputs([*scenes, scene(3)], {**pins, pin(3): PinSource.remotion(source())})).project_key != base


def test_a_title_rename_or_a_no_op_revision_bump_keeps_the_key_and_carries_the_new_basis():
    scenes, pins = three()
    base = plan_master(inputs(scenes, pins, revision=3))
    renamed = plan_master(inputs([scene(0, title="Intro"), scenes[1], scenes[2]], pins, revision=4))
    assert renamed.project_key == base.project_key and renamed.variant_revision == 4 and base.variant_revision == 3
    assert dict(renamed.generated) == dict(base.generated), "a title never reaches a generated file"


def test_the_same_pin_twice_is_mounted_twice_with_one_merged_asset():
    s0 = source()
    plan = plan_master(inputs([scene(0), StudioScene(IDS[1], PrefabRef(PREFABS[0], 1))], {pin(0): PinSource.remotion(s0)}))
    assert plan.ready and [s.mount for s in plan.scenes] == [f"src/scenes/{IDS[0]}/", f"src/scenes/{IDS[1]}/"]
    assert plan.public_assets[0].scene_ids == IDS[:2]


# ------------------------------------------------------------------ reasons, in their order


def test_reason_codes_are_declared_in_the_contract_order():
    from tests.unit.test_remotion_master_project_docs import PLANNER_CODES
    assert tuple(r.value for r in R) == PLANNER_CODES


def test_an_empty_variant_comes_first_even_for_a_slidecar_presentation():
    failed(plan_master(inputs([], {}, engine=Engine.SLIDECAR)), R.EMPTY)


def test_a_non_remotion_engine_or_a_non_remotion_pin_is_engine_not_remotion_before_an_unavailable_pin():
    scenes, pins = three()
    plan = failed(plan_master(inputs(scenes, pins, engine=Engine.SLIDECAR)), R.ENGINE_NOT_REMOTION)
    assert plan.scene_ids == () and "slidecar" in plan.detail
    mixed = {**pins, pin(1): PinSource.not_remotion("x@1 is an HTML prefab, not a Remotion source"),
             pin(2): PinSource.unavailable("y@1 is tampered")}
    plan = failed(plan_master(inputs(scenes, mixed)), R.ENGINE_NOT_REMOTION)
    assert plan.scene_ids == (IDS[1],) and "scene 2" in plan.detail and "HTML" in plan.detail


def test_an_unknown_or_tampered_pin_is_source_unavailable_naming_the_scenes():
    scenes, pins = three()
    plan = failed(plan_master(inputs(scenes, {pin(0): pins[pin(0)], pin(2): PinSource.unavailable("p@1 is tampered")})),
                  R.SOURCE_UNAVAILABLE)
    assert plan.scene_ids == (IDS[1], IDS[2]) and "scene 2" in plan.detail and "scene 3" in plan.detail


def test_different_engine_pins_are_an_engine_mismatch():
    other = EnginePin("remotion", "4.0.535", "19.3.0", "b" * 64)
    scenes, pins = three(s1=source(engine=other))
    plan = failed(plan_master(inputs(scenes, pins)), R.ENGINE_MISMATCH)
    assert "4.0.534" in plan.detail and "4.0.535" in plan.detail and plan.scene_ids == IDS[:3]
    same_version_other_lock = EnginePin("remotion", "4.0.534", "19.3.0", "c" * 64)
    plan = failed(plan_master(inputs(*three(s2=source(engine=same_version_other_lock)))), R.ENGINE_MISMATCH)
    assert "version 4.0.534 with 2 different locks" in plan.detail, plan.detail


def test_mixed_fps_then_mixed_dimensions_are_typed_and_fps_is_checked_first():
    fps = Composition("Scene", 1280, 720, 25, 90)
    plan = failed(plan_master(inputs(*three(s2=source(composition=fps)))), R.FPS_MISMATCH)
    assert "scene 3" in plan.detail and "fps 30" in plan.detail
    size = Composition("Scene", 1920, 1080, 30, 90)
    plan = failed(plan_master(inputs(*three(s1=source(composition=size)))), R.DIMENSIONS_MISMATCH)
    assert "1280x720" in plan.detail and "scene 2" in plan.detail
    both = Composition("Scene", 1920, 1080, 60, 90)
    failed(plan_master(inputs(*three(s1=source(composition=both)))), R.FPS_MISMATCH)


def test_relative_imports_inside_the_scene_are_kept_and_escaping_ones_are_refused():
    assert plan_master(inputs(*three())).ready  # ./lib/Title and ./theme.json resolve inside the scene
    escaping = {**scene_files(), "src/Scene.tsx": SCENE_TSX.replace('"./lib/Title"', '"../../scenes/other/Title"')}
    plan = failed(plan_master(inputs(*three(s1=source(escaping)))), R.SOURCE_IMPORT_REFUSED)
    assert plan.scene_ids == (IDS[1],) and "../../scenes/other/Title" in plan.detail
    dangling = {**scene_files(), "src/Scene.tsx": SCENE_TSX.replace('"./lib/Title"', '"./lib/Missing"')}
    failed(plan_master(inputs(*three(s0=source(dangling)))), R.SOURCE_IMPORT_REFUSED)


def test_a_bare_specifier_outside_the_allowed_list_is_refused():
    bare = {**scene_files(), "src/lib/Title.tsx": 'import _ from "lodash";\n' + scene_files()["src/lib/Title.tsx"]}
    plan = failed(plan_master(inputs(*three(s2=source(bare)))), R.SOURCE_IMPORT_REFUSED)
    assert "lodash" in plan.detail and plan.scene_ids == (IDS[2],)


def test_a_scene_reading_get_input_props_is_refused_but_a_comment_is_not():
    reader = {**scene_files(), "src/lib/Title.tsx": scene_files()["src/lib/Title.tsx"] + "export const p = () => getInputProps();\n"}
    plan = failed(plan_master(inputs(*three(s0=source(reader)))), R.INPUT_PROPS_READER)
    assert "src/lib/Title.tsx" in plan.detail and plan.scene_ids == (IDS[0],)
    commented = {**scene_files(), "src/lib/Title.tsx": scene_files()["src/lib/Title.tsx"] + "// never call getInputProps here\n"}
    assert plan_master(inputs(*three(s0=source(commented)))).ready


def test_different_bytes_or_a_case_only_spelling_at_one_public_path_collide_without_rewrite():
    other = {**scene_files(), "public/dot.png": RED_PNG}
    plan = failed(plan_master(inputs(*three(s2=source(other)))), R.PUBLIC_ASSET_COLLISION)
    assert "public/dot.png" in plan.detail and plan.scene_ids == (IDS[0], IDS[2])
    cased = {**{k: v for k, v in scene_files().items() if k != "public/dot.png"}, "public/Dot.png": PNG_1X1}
    cased["src/Scene.tsx"] = SCENE_TSX.replace('staticFile("dot.png")', 'staticFile("Dot.png")')
    plan = failed(plan_master(inputs(*three(s1=source(cased)))), R.PUBLIC_ASSET_COLLISION)
    assert "public/Dot.png" in plan.detail and "spelled public/dot.png" in plan.detail and plan.scene_ids == (IDS[0], IDS[1])


def test_frozen_live_copies_take_part_in_the_collision_check_and_the_totals_but_not_in_the_key():
    scenes, pins = three()
    base = plan_master(inputs(scenes, pins))
    live = {pin(0): {"sales.json": b'{"a":1}'}, pin(1): {"sales.json": b'{"a":1}'}}
    frozen = plan_master(inputs(scenes, pins, live=live))
    assert frozen.ready and frozen.project_key == base.project_key
    row = next(a for a in frozen.public_assets if a.path == "public/live/sales.json")
    assert row.scene_ids == IDS[:2] and row.live and frozen.totals.files == base.totals.files + 1
    plan = failed(plan_master(inputs(scenes, pins, live={**live, pin(2): {"sales.json": b'{"a":2}'}})), R.PUBLIC_ASSET_COLLISION)
    assert "public/live/sales.json" in plan.detail and plan.scene_ids == (IDS[0], IDS[2])
    own = {**scene_files(), "public/live/sales.png": RED_PNG}
    clash = failed(plan_master(inputs(*three(s1=source(own)), live={pin(0): {"sales.png": PNG_1X1}})), R.PUBLIC_ASSET_COLLISION)
    assert clash.scene_ids == (IDS[0], IDS[1])


def test_the_workspace_bounds_count_generated_files_and_are_inclusive(monkeypatch):
    many = {**scene_files(), **{f"src/parts/m{i:02d}.ts": f"export const v{i} = {i};\n" for i in range(60)}}
    big = source(many)
    scenes = [scene(n % 4) if n < 4 else StudioScene(f"pss_00000000001{n}", PrefabRef(PREFABS[0], 1)) for n in range(7)]
    plan = failed(plan_master(inputs(scenes, {pin(n): PinSource.remotion(big) for n in range(4)})), R.PROJECT_TOO_LARGE)
    assert "files" in plan.detail and len(plan.scene_ids) == 7
    ready = plan_master(inputs(*three()))
    monkeypatch.setattr(M, "MAX_MASTER_FILES", ready.totals.files)
    monkeypatch.setattr(M, "MAX_MASTER_BYTES", ready.totals.bytes)
    assert plan_master(inputs(*three())).ready
    monkeypatch.setattr(M, "MAX_MASTER_BYTES", ready.totals.bytes - 1)
    failed(plan_master(inputs(*three())), R.PROJECT_TOO_LARGE)
    monkeypatch.setattr(M, "MAX_MASTER_BYTES", ready.totals.bytes)
    monkeypatch.setattr(M, "MAX_MASTER_FILES", ready.totals.files - 1)
    failed(plan_master(inputs(*three())), R.PROJECT_TOO_LARGE)


def test_the_whole_video_is_bounded_to_9000_frames_inclusive():
    assert M.MAX_MASTER_RENDER_FRAMES == 9000
    at = Composition("Scene", 1280, 720, 30, 3000)
    over = Composition("Scene", 1280, 720, 30, 3001)
    plan = plan_master(inputs(*three(s0=source(composition=at), s1=source(composition=at), s2=source(composition=at))))
    assert plan.ready and plan.composition.duration_in_frames == 9000
    plan = failed(plan_master(inputs(*three(s0=source(composition=over), s1=source(composition=at), s2=source(composition=at)))),
                  R.TOO_LONG)
    assert "9001" in plan.detail


def test_the_first_failing_check_wins():
    fps = Composition("Scene", 1280, 720, 25, 90)
    other = {**scene_files(), "public/dot.png": RED_PNG}
    failed(plan_master(inputs(*three(s1=source(other, composition=fps)))), R.FPS_MISMATCH)
    bare = {**scene_files(), "src/lib/Title.tsx": 'import _ from "lodash";\n'}
    failed(plan_master(inputs(*three(s1=source(other), s2=source(bare)))), R.SOURCE_IMPORT_REFUSED)


# ------------------------------------------------------------------ wire view


MACHINE = ("C:\\", "C:/", "/Users/", "/home/", "\\\\", ".jarvis", "AppData")


def test_the_wire_view_has_exactly_the_contract_fields_and_no_machine_path():
    ready = plan_master(inputs(*three())).to_wire()
    assert set(ready) == {"presentation_id", "variant_id", "variant_revision", "generator_version", "status", "project_key", "composition",
                          "scenes", "public_assets", "totals"}
    assert set(ready["scenes"][0]) == {"scene_id", "prefab_id", "version", "source_digest", "engine_version", "from_frame",
                                       "duration_in_frames", "entry", "mount"}
    assert set(ready["public_assets"][0]) == {"path", "sha256", "bytes", "scene_ids"}
    scenes, pins = three()
    bad = plan_master(inputs(scenes, {**pins, pin(1): PinSource.unavailable("p@1 is tampered")})).to_wire()
    assert set(bad) == {"presentation_id", "variant_id", "variant_revision", "generator_version", "status", "reason", "detail", "scene_ids"}
    for wire in (ready, bad):
        text = json.dumps(wire)
        assert not any(marker in text for marker in MACHINE), text
        json.loads(text)


# ------------------------------------------------------------------ live seam and frozen builder on a real world


@pytest.fixture
async def world(tmp_path):
    w = await PresentationWorld().open(tmp_path, runtime={"remotion_version": "4.0.534"})
    try:
        yield w
    finally:
        await w.close()


async def _add_scenes(world, pid, vid, extra):
    variant = (await world.studio.get(pid)).variants[0].to_document()
    await world.studio.save_variant(pid, vid, {"expected_revision": variant["revision"], "title": variant["title"],
                                               "scenes": variant["scenes"] + extra, "art_direction_id": None, "score_id": None})


async def test_live_and_frozen_plans_of_the_same_pins_give_the_same_key(world):
    pid, vid = await world.new_presentation(props={"title": "Un"})
    second = await world.prefabs.save(scene_candidate(PREFABS[1]), actor="user")
    await _add_scenes(world, pid, vid, [{"scene_id": IDS[1], "prefab": {"id": PREFABS[1], "version": second.version},
                                         "props": {"title": "Deux"}}])
    reader = MasterProjectReader(studio=world.studio, prefabs=world.prefabs, diagnostics=world.sink)
    live = await reader.live_plan(pid, vid)
    assert live.ready and [s.scene_id for s in live.scenes] == [SCENE_ID, IDS[1]], live.detail
    assert "core.remotion_master.planned" in world.sink.kinds()
    snapshot = (await world.freeze(pid, vid))["artifact_id"]
    frozen = plan_master(M.frozen_inputs(await world.packager.read_snapshot(snapshot)))
    assert frozen.ready and frozen.project_key == live.project_key
    assert frozen.scenes[1].props["title"] == "Deux" and frozen.scenes[1].props == live.scenes[1].props


async def test_only_the_active_pin_is_mounted_when_a_scene_holds_other_pins(world):
    pid, vid = await world.new_presentation()
    odd = await world.prefabs.save(scene_candidate(PREFABS[2], composition=Composition("Scene", 640, 360, 60, 30)), actor="user")
    variant = (await world.studio.get(pid)).variants[0].to_document()
    base = variant["scenes"][0]
    stamp = "2026-10-10T09:00:00.000000Z"
    items = [{"variant_id": "psx_000000000001", "label": "A", "rationale": "", "source": "current", "created_by": "user", "created_at": stamp},
             {"variant_id": "psx_000000000002", "label": "B", "rationale": "", "source": "psx_000000000001", "created_by": "user",
              "created_at": stamp, "content": {"prefab": {"id": PREFABS[2], "version": odd.version}, "props": {}, "data": {},
                                              "controls": [], "anchors": []}}]
    held = {**base, "scene_variants": {"current_id": "psx_000000000001", "items": items}}
    await world.studio.save_variant(pid, vid, {"expected_revision": variant["revision"], "title": variant["title"], "scenes": [held],
                                               "art_direction_id": None, "score_id": None})
    snapshot = (await world.freeze(pid, vid))["artifact_id"]
    package = await world.packager.read_snapshot(snapshot)
    assert any(r["prefab_id"] == PREFABS[2] for r in package.manifest["prefabs"]), "the package holds the stored alternative"
    frozen_in = M.frozen_inputs(package)
    assert set(frozen_in.pins) == {(base["prefab"]["id"], base["prefab"]["version"])}
    plan = plan_master(frozen_in)
    assert plan.ready and plan.composition.fps == 30 and [s.prefab_id for s in plan.scenes] == [base["prefab"]["id"]]


async def test_the_live_seam_reports_an_unknown_pin_and_an_html_pin_as_typed_reasons(world):
    pid, vid = await world.new_presentation()
    reader = MasterProjectReader(studio=world.studio, prefabs=world.prefabs)
    await _add_scenes(world, pid, vid, [{"scene_id": IDS[1], "prefab": {"id": "jarvis.counter", "version": 1}}])
    plan = failed(await reader.live_plan(pid, vid), R.ENGINE_NOT_REMOTION)
    assert plan.scene_ids == (IDS[1],) and "HTML" in plan.detail
    pid2, vid2 = await world.new_presentation(prefab_id=PREFABS[3])
    await _add_scenes(world, pid2, vid2, [{"scene_id": IDS[1], "prefab": {"id": PREFABS[3], "version": 9}}])
    plan = failed(await reader.live_plan(pid2, vid2), R.SOURCE_UNAVAILABLE)
    assert plan.scene_ids == (IDS[1],) and "unknown version" in plan.detail


async def test_a_frozen_pin_whose_files_no_longer_match_is_source_unavailable(world):
    from jarvis.domain.presentation_snapshot_package import FrozenPackage
    pid, vid = await world.new_presentation()
    package = await world.packager.read_snapshot((await world.freeze(pid, vid))["artifact_id"])
    files = dict(package.files)
    path = next(p for p in files if p.endswith("/src/lib/Title.tsx"))
    files[path] = files[path] + b"// changed\n"
    plan = failed(plan_master(M.frozen_inputs(FrozenPackage(package.manifest, files))), R.SOURCE_UNAVAILABLE)
    assert "source digest" in plan.detail and plan.scene_ids == (SCENE_ID,)


# ------------------------------------------------------------------ QA polish (Slice 03 QA findings 1-4)


def test_a_relative_import_that_leaves_the_scene_root_is_refused_even_if_it_resolves_standalone():
    climbing = {**scene_files(), "src/Scene.tsx": SCENE_TSX.replace('"./lib/Title"', '"../src/lib/Title"')}
    plan = failed(plan_master(inputs(*three(s1=source(climbing)))), R.SOURCE_IMPORT_REFUSED)
    assert "../src/lib/Title" in plan.detail and "once mounted" in plan.detail and plan.scene_ids == (IDS[1],)
    deep = {**scene_files(), "src/lib/Title.tsx": 'import {palette} from "../theme.json";\n' + scene_files()["src/lib/Title.tsx"]}
    assert plan_master(inputs(*three(s0=source(deep)))).ready, "a parent import that stays inside src/ is kept"


@pytest.mark.parametrize("call", ["import(`./lib/${name}`)", "require(`lodash`)", 'import("./lib/Title")'])
def test_a_dynamic_import_is_refused_whatever_the_quoting(call):
    files = {**scene_files(), "src/lib/Title.tsx": scene_files()["src/lib/Title.tsx"] + f"const name = 'Title';\nexport const lazy = () => {call};\n"}
    candidate = scene_candidate(files=files)
    from jarvis.domain.remotion_source import RemotionSource
    raw = parse_source_block(candidate["manifest"]["source"])
    unguarded = RemotionSource(raw, decode_candidate_files(candidate["sources"], candidate["assets"]))  # an old version, before the guard
    plan = failed(plan_master(inputs(*three(s2=unguarded))), R.SOURCE_IMPORT_REFUSED)
    assert "dynamic import" in plan.detail and plan.scene_ids == (IDS[2],)


def test_an_entry_beside_a_same_stem_module_is_imported_by_its_exact_file():
    twin = {**scene_files(), "src/Scene.ts": "export const other = 1;\n"}
    plan = plan_master(inputs(*three(s0=source(twin))))
    assert plan.ready
    assert f'from "../scenes/{IDS[0]}/Scene.tsx";' in plan.generated[PRESENTATION_FILE].decode()


def test_a_proto_prop_stays_an_own_key_of_the_scene_props():
    scenes, pins = three()
    plan = plan_master(inputs([scene(0, props={"__proto__": {"x": 1}, "title": "t"}), *scenes[1:]], pins))
    text = plan.generated[PRESENTATION_FILE].decode()
    assert "JSON.parse(" in text and generated_props(text)[1] == {"__proto__": {"x": 1}, "title": "t"}

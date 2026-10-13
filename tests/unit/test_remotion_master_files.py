"""Master workspace file map (handoff jarvis-remotion-master-project-studio-export, Slice 04; `docs/remotion-master-project.md` §6).

Pure: a ready plan (built by the Slice 03 planner on real parsed sources) to the exact `{path: bytes}` the runners write. The real bundle,
composition and frame proof is `test_remotion_master_files_real.py`.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from jarvis.domain import remotion_master_files as F
from jarvis.domain.remotion_master_files import MasterFilesError, plan_master_files
from jarvis.domain.remotion_master_generated import BOUNDARY_FILE, PACKAGE_FILE, PRESENTATION_FILE, ROOT_FILE
from jarvis.domain.remotion_master_project import MasterAsset, MasterTotals, PinSource, plan_master
from tests.fakes.remotion_scene import PNG_1X1, scene_files
from tests.unit.test_remotion_master_project import IDS, generated_props, inputs, pin, scene, source, three

GENERATED = {PACKAGE_FILE, ROOT_FILE, PRESENTATION_FILE, BOUNDARY_FILE}


def distinct():
    """Three pins whose sources share every path (`src/Scene.tsx`, `src/lib/Title.tsx`…) but differ in bytes."""

    sources = [source(scene_files(title_suffix=f"// scene {n}\n")) for n in range(3)]
    scenes = [scene(n, props={"title": f"T{n}"}) for n in range(3)]
    return plan_master(inputs(scenes, {pin(n): PinSource.remotion(sources[n], props_defaults={"accent": "#000000"}) for n in range(3)})), sources


def test_the_file_map_is_deterministic_and_sorted():
    plan, _ = distinct()
    files = plan_master_files(plan)
    assert files == plan_master_files(distinct()[0]) and list(files) == sorted(files)
    assert GENERATED <= set(files)


def test_each_scene_is_mounted_byte_for_byte_in_its_own_namespace():
    plan, sources = distinct()
    files = plan_master_files(plan)
    for n, src in enumerate(sources):
        for module in src.block.modules:
            assert files[f"src/scenes/{IDS[n]}/{module[len('src/'):]}"] == src.files[module], (n, module)
    titles = {files[f"src/scenes/{IDS[n]}/lib/Title.tsx"] for n in range(3)}
    assert len(titles) == 3, "no scene receives another pin's bytes"
    scene_paths = [p for p in files if p.startswith("src/scenes/")]
    assert len(scene_paths) == 3 * len(sources[0].block.modules)
    assert set(files) == GENERATED | set(scene_paths) | {"public/dot.png"}
    assert files["public/dot.png"] == PNG_1X1


def test_the_map_equals_the_plan_totals_and_holds_frozen_live_copies():
    scenes, pins = three()
    plan = plan_master(inputs(scenes, pins, live={pin(0): {"sales.json": b'{"a":1}'}}))
    files = plan_master_files(plan)
    assert (len(files), sum(map(len, files.values()))) == (plan.totals.files, plan.totals.bytes)
    assert files["public/live/sales.json"] == b'{"a":1}'


def test_the_generated_presentation_wires_merged_props_per_scene():
    plan, _ = distinct()
    text = plan_master_files(plan)[PRESENTATION_FILE].decode()
    assert generated_props(text) == {n + 1: {"accent": "#000000", "title": f"T{n}"} for n in range(3)}, text


def test_a_plan_that_is_not_ready_has_no_workspace():
    scenes, pins = three()
    bad = plan_master(inputs(scenes, {**pins, pin(1): PinSource.unavailable("x@1 is tampered")}))
    with pytest.raises(MasterFilesError, match="incompatible"):
        plan_master_files(bad)


@pytest.mark.parametrize("tamper", ["mount", "scene_id", "asset", "generated", "duplicate"])
def test_paths_that_would_escape_or_collide_are_refused(tamper):
    plan = plan_master(inputs(*three()))
    if tamper == "mount":
        plan = replace(plan, scenes=(replace(plan.scenes[0], mount="src/scenes/../../x/"), *plan.scenes[1:]))
    elif tamper == "scene_id":
        plan = replace(plan, scenes=(replace(plan.scenes[0], scene_id="pss_../../x", mount="src/scenes/pss_../../x/"), *plan.scenes[1:]))
    elif tamper == "asset":
        plan = replace(plan, public_assets=(MasterAsset("public/../studio-root.tsx", "0" * 64, 1, (IDS[0],), False, b"x"),))
    elif tamper == "generated":
        plan = replace(plan, generated={**plan.generated, "remotion.config.ts": b"x"})
    else:
        plan = replace(plan, public_assets=(*plan.public_assets, MasterAsset("public/DOT.png", "0" * 64, 1, (IDS[0],), False, b"x")))
    with pytest.raises(MasterFilesError):
        plan_master_files(plan)


def test_the_workspace_bound_is_rechecked(monkeypatch):
    plan = plan_master(inputs(*three()))
    monkeypatch.setattr(F, "MAX_MASTER_FILES", plan.totals.files - 1)
    with pytest.raises(MasterFilesError, match="bound"):
        plan_master_files(plan)


# ------------------------------------------------------------------ QA rework (Slice 04 P2): each defence fails on its own branch


def _with_extra(plan, path: str, data: bytes = b"x"):
    """The plan plus one public asset, its totals adjusted so that only the branch under test can refuse it."""

    extra = MasterAsset(path, "0" * 64, len(data), (IDS[0],), False, data)
    return replace(plan, public_assets=(*plan.public_assets, extra),
                   totals=MasterTotals(plan.totals.files + 1, plan.totals.bytes + len(data)))


def test_a_path_written_twice_is_refused_by_the_write_check():
    plan = plan_master(inputs(*three()))
    with pytest.raises(MasterFilesError, match="would be written twice"):
        plan_master_files(_with_extra(plan, "public/dot.png"))


def test_a_bad_path_with_matching_totals_is_refused_by_the_path_check():
    plan = plan_master(inputs(*three()))
    with pytest.raises(MasterFilesError, match=r"segment '\.\.' is not allowed"):
        plan_master_files(_with_extra(plan, "public/../studio-root.tsx"))


def test_the_byte_bound_is_rechecked(monkeypatch):
    plan = plan_master(inputs(*three()))
    monkeypatch.setattr(F, "MAX_MASTER_BYTES", plan.totals.bytes - 1)
    with pytest.raises(MasterFilesError, match="bound"):
        plan_master_files(plan)
    monkeypatch.setattr(F, "MAX_MASTER_BYTES", plan.totals.bytes)
    assert len(plan_master_files(plan)) == plan.totals.files, "the bound is inclusive"


def test_a_plan_whose_totals_differ_from_the_map_is_refused():
    plan = plan_master(inputs(*three()))
    for totals in (MasterTotals(plan.totals.files, plan.totals.bytes + 1), MasterTotals(plan.totals.files + 1, plan.totals.bytes), None):
        with pytest.raises(MasterFilesError, match="differs from the plan totals"):
            plan_master_files(replace(plan, totals=totals))

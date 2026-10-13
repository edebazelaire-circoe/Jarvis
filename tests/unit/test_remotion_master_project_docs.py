"""Level 2 conformance of `docs/remotion-master-project.md` (handoff jarvis-remotion-master-project-studio-export, Slice 02).

Slice 03 implemented the planner (§ 2, § 3, § 5 are Level 3, `jarvis/domain/remotion_master_project.py`); Slices 04-08 follow. These tests pin what Slices 03-08 build against: the reason codes and their order, the
`project_key` inputs, the bounds, the composition id, the acknowledgment and scope names, the terminology, and that the scene-lane documents
qualify their single-scene sentences instead of contradicting the new contract. They also check that the new names do not collide with any
code that exists today and that the scene-lane constants the contract keeps unchanged are still the ones in the code.
"""

from __future__ import annotations

from pathlib import Path
import re

from jarvis.adapters import remotion_studio_runner as runner
from jarvis.domain import presentation_render as render
from jarvis.domain import presentation_snapshot_package as package
from jarvis.domain import remotion_master_project as master
from jarvis.domain.presentation_studio import PresentationStudioErrorCode
from jarvis.domain.remotion_compile import SCENE_ALLOWED_IMPORTS
from jarvis.domain.remotion_source import COMPOSITION_ID
from jarvis.domain.remotion_studio import StudioErrorCode

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
NAME = "remotion-master-project.md"
DOC = (DOCS / NAME).read_text(encoding="utf-8")
STATUS = "Level 2 — contract; implementation in Slices 03-08 of handoff jarvis-remotion-master-project-studio-export"
LINK = f"]({NAME})"

PLANNER_CODES = ("master_empty", "master_engine_not_remotion", "master_source_unavailable", "master_engine_mismatch", "master_fps_mismatch",
                 "master_dimensions_mismatch", "master_source_import_refused", "master_input_props_reader", "master_public_asset_collision",
                 "master_project_too_large", "master_too_long")
ENVELOPE_CODES = {"remotion_studio_master_incompatible": "409", "remotion_studio_master_stale": "409",
                  "remotion_studio_publish_master_unsupported": "409", "presentation_render_master_incompatible": "409",
                  "presentation_render_master_scene_failed": "job failure"}


def flat(text: str) -> str:
    """Whitespace-insensitive view: the page wraps its prose at about 145 columns."""

    return re.sub(r"\s+", " ", text)


def section(title: str) -> str:
    start = DOC.index(title)
    nxt = DOC.find("\n## ", start + 1)
    return DOC[start: nxt if nxt != -1 else len(DOC)]


LEVEL_3_SECTIONS = ("## 2. MasterProjectPlan — Level 3 (Slice 03)", "## 3. Readiness and reason codes — Level 3 (Slice 03)",
                    "## 5. `project_key` — Level 3 (Slice 03)")


def test_the_page_states_level_2_and_claims_level_3_only_for_the_implemented_planner_sections():
    assert f"Status: **{STATUS}.**" in DOC
    assert "Shipped so far: § 2, § 3 and § 5, the pure planner (Level 3 (Slice 03)" in flat(DOC)
    rest = DOC.replace("*Composition clock (Level 3)*", "").replace("Level 3 (Slice 03)", "").replace("(Level 3, Slice 03)", "")
    assert "Level 3" not in rest, "only the Slice 03 sections claim Level 3"
    for heading in LEVEL_3_SECTIONS:
        assert "\n" + heading + "\n" in DOC, heading
    assert "| MasterProjectPlan, readiness codes, `project_key`, asset merge | 3 (Slice 03) | 3 | 03 |" in DOC


def test_the_level_3_sections_name_their_implementation_and_its_conformance_test():
    text = flat(section("## 2. MasterProjectPlan"))
    for needle in ("`jarvis/domain/remotion_master_project.py`", "`plan_master(inputs) -> MasterProjectPlan`", "`frozen_inputs(package)`",
                   "`MasterProjectReader.live_plan(presentation_id, variant_id)`", "`jarvis/domain/remotion_master_generated.py`",
                   "`tests/unit/test_remotion_master_project.py`"):
        assert needle in text, needle
    assert [r.value for r in master.MasterReason] == list(PLANNER_CODES)


def test_the_planner_reason_codes_are_listed_in_their_fixed_order_with_a_sentence_each():
    rows = re.findall(r"^\| (\d+) \| `(master_[a-z_]+)` \| [^|]+ \| « .+ » \|$", section("## 3. Readiness"), flags=re.M)
    assert [code for _, code in rows] == list(PLANNER_CODES)
    assert [int(n) for n, _ in rows] == list(range(1, len(PLANNER_CODES) + 1))
    assert "reports the **first** failing check as `reason`" in DOC


def test_the_envelope_codes_are_documented_with_their_status_and_collide_with_nothing_that_exists():
    text = section("## 3. Readiness")
    for code, status in ENVELOPE_CODES.items():
        assert re.search(rf"^\| `{code}` \| {status}[^|]* \|", text, flags=re.M), code
    existing = ({c.value for c in StudioErrorCode} | {c.value for c in render.RenderErrorCode}
                | {c.value for c in PresentationStudioErrorCode})
    assert not (set(ENVELOPE_CODES) | set(PLANNER_CODES)) & existing, "a new code reuses a name that already means something"
    for reused in ("remotion_studio_ack_required", "presentation_render_invalid", "presentation_studio_stale_revision",
                   "remotion_studio_unpublished_edits", "remotion_studio_invalid", "presentation_studio_scene_edited_in_remotion"):
        assert f"`{reused}`" in DOC and reused in existing, reused


def test_the_project_key_inputs_and_non_inputs_are_pinned():
    text = section("## 5. `project_key`")
    assert '`project_key = "mpk_" + sha256(canonical_json(inputs))[:24]`' in text
    for needle in ("`generator_version`", "`MASTER_GENERATOR_VERSION`", "the master spec `[width, height, fps]`",
                   "`[scene_id, prefab_id, version, source_digest, props_digest]`", "**instance** `{\"props\": …, \"data\": …}`",
                   "the sorted list of `[path, sha256]`"):
        assert flat(needle) in flat(text), needle
    assert flat("Not inputs: the Presentation title, the variant name, the variant `revision`, `presentation_id`, `variant_id`") in flat(text)
    for consequence in ("a title rename or a no-op revision bump keeps the key", "a repin (voice edit), a reorder, a new source version",
                        "an instance props/data change"):
        assert consequence in flat(text), consequence


def test_the_bounds_are_the_decided_ones_and_the_scene_bounds_are_unchanged_in_the_code():
    for needle in ("`MAX_MASTER_RENDER_FRAMES = 9000`", "≤ 400 files and ≤ 64 MiB", "capped at 3600 s (unchanged)",
                   "`300 s + 1 s/frame`", "the scene bound `MAX_RENDER_FRAMES = 3600` unchanged"):
        assert flat(needle) in flat(DOC), needle
    assert render.MAX_RENDER_FRAMES == 3600 and render.TIMEOUT_CAP_S == 3600.0
    assert render.TIMEOUT_BASE_S == 300.0 and render.TIMEOUT_PER_FRAME_S == 1.0
    assert runner.MAX_WORK_FILES == 400 and runner.MAX_WORK_BYTES == 64 * 1024 * 1024
    assert package.MAX_PACKAGE_FILES >= 400 and package.MAX_PACKAGE_BYTES == 64 * 1024 * 1024, "400 / 64 MiB is the minimum of both"
    assert not hasattr(render, "MAX_MASTER_RENDER_FRAMES") or render.MAX_MASTER_RENDER_FRAMES == 9000
    assert master.MAX_MASTER_RENDER_FRAMES == 9000 and master.MASTER_GENERATOR_VERSION == 1
    assert (master.MAX_MASTER_FILES, master.MAX_MASTER_BYTES) == (min(runner.MAX_WORK_FILES, package.MAX_PACKAGE_FILES), 64 * 1024 * 1024)


def test_the_composition_id_is_valid_for_remotion_and_jarvis_and_the_draft_id_is_rejected():
    assert DOC.count('`JarvisPresentation`') >= 2 and 'id="JarvisPresentation"' in DOC
    assert COMPOSITION_ID.fullmatch("JarvisPresentation") and master.MASTER_COMPOSITION_ID == "JarvisPresentation"
    assert not COMPOSITION_ID.fullmatch("JARVIS_PRESENTATION"), "Remotion 4.0.534 refuses an underscore"
    assert "`JARVIS_PRESENTATION` (the handoff's draft) is refused by Remotion 4.0.534 and is never used" in DOC


def test_the_studio_target_acknowledgment_state_and_unpublished_policy_are_named():
    text = section("## 9. Studio master target")
    for needle in ('"kind": "variant_master"', '"acknowledge_unsandboxed_project": true', "binds to\nthat `project_key`",
                   "**the scene count**", "`schema: 1`", "`schema: 2`", "The reader accepts 1", "`remotion_studio_state_unreadable`",
                   "**generated**", "**per-scene**", "**shared**", "`discard_unpublished: true`", "only when class-2 edits on X exist",
                   "refused `remotion_studio_publish_master_unsupported` before any read", "never follows a new key by itself",
                   "no second Studio process"):
        assert flat(needle) in flat(text), needle
    assert "`acknowledge_unsandboxed_scene`" in (DOCS / "remotion-studio.md").read_text(encoding="utf-8"), "the scene ack keeps its name"


def test_the_render_scope_key_artifact_metadata_and_failure_are_pinned():
    text = section("## 10. Whole-video render scope")
    for needle in ("`settings.scope`", '| absent or `"scene"` |', '| `"master"` |', "`scene_id` is invalid", "`format` must be `mp4`",
                   '`render_scope: "master"`', "`render_project_key`", "`render_scene_count`", "`cancelRender`",
                   "`presentation_render_master_scene_failed`", "an audio stream must exist", "one `rendered_from` relation",
                   "`GET /v1/local-capabilities/remotion/render/master?snapshot_id=…`"):
        assert flat(needle) in flat(text), needle
    assert "scope" not in render.SETTINGS_KEYS or "scope" in text, "the key the code admits is the documented one"


def test_the_layout_generated_set_and_guard_recheck_are_pinned():
    text = section("## 6. Workspace layout")
    for needle in ("src/scenes/<scene_id>/**", "src/master/Presentation.tsx", "`package.json`, `studio-root.tsx`, `src/master/**`",
                   '"jarvis-studio-master"', "`plan_master_files`"):
        assert flat(needle) in flat(text), needle
    assert "`SCENE_ALLOWED_IMPORTS`" in DOC and "react" in SCENE_ALLOWED_IMPORTS and "remotion" in SCENE_ALLOWED_IMPORTS


def test_the_terminology_separates_the_master_composition_from_the_variants_composition_clock():
    terms = section("## 0. Terms")
    assert "| **master Remotion Composition** |" in terms and "| **Variants composition clock** |" in terms
    assert "It is **compatibility playback**, not a Remotion Composition" in terms
    studio = (DOCS / "presentation-studio.md").read_text(encoding="utf-8")
    clock = studio[studio.index("### Composition clock (Level 3)"):studio.index("### Continuous sequencing in Variants")]
    assert "timebase of the **Variants composition clock** (compatibility playback)" in clock and LINK in clock


def test_the_security_review_accepts_the_master_root_for_studio_and_render_only_and_keeps_the_player_rejection():
    studio = (DOCS / "presentation-studio.md").read_text(encoding="utf-8")
    clock = studio[studio.index("### Composition clock (Level 3)"):studio.index("### Continuous sequencing in Variants")]
    rejection = clock.index("**Rejected for now: a generated multi-scene root**")
    review = clock.index("**Security review (2026-10-13): master root for Remotion Studio and render only.**")
    assert rejection < review
    assert "This rejection **stays true for the Variants Player**" in clock
    for needle in ("**accepted for Remotion Studio (already unsandboxed under explicit acknowledgment) and the guarded render host only**",
                   "never for the Variants Player", "**(a) guards for N merged sources.**", "`master_source_import_refused`",
                   "**(b) per-scene failure isolation.**", "**(c) combined budget and the same guards.**", "400 files and 64 MiB",
                   "**(d) pins and the hot-reload gate.**", "is **not** a hot-reload or publish source in A+B", STATUS):
        assert flat(needle) in flat(clock), needle
    assert "accepted for **Remotion Studio" not in DOC and "stays **rejected for\nthe Variants Player**" in DOC


def test_the_scene_lane_documents_qualify_their_single_scene_sentences_and_link_the_contract():
    for name, needles in {
        "remotion-render.md": ("| **Une scène par export.** |", "- **Une scène par export** (aujourd'hui)", "| `scene_id` | tous |",
                               "puis UNE scène (l'aperçu reste de portée de scène"),
        "remotion-studio.md": ("| **Le Studio ne sert que la source de la scène choisie** (cible de scène, livrée",
                               "**La porte de Variantes (native-studio-playback-fix Slice 11).** (prévu"),
        "presentation-studio.md": ("on **one scene pin**, in its own browser tab (planned",),
    }.items():
        text = (DOCS / name).read_text(encoding="utf-8")
        for needle in needles:
            line = next((l for l in text.splitlines() if needle in l), None)
            assert line is not None, (name, needle)
            assert LINK in line, (name, needle, "the qualified sentence links the master contract")
    for name in ("remotion-render.md", "remotion-studio.md", "remotion-source.md", "presentation-studio.md", "ARCHITECTURE.md"):
        text = (DOCS / name).read_text(encoding="utf-8")
        assert LINK in text and STATUS in text, name


def test_the_contract_index_registers_the_page_and_this_test():
    report = (DOCS / "remotion-integration-release.md").read_text(encoding="utf-8")
    index = report[report.index("## Contract index"):]
    row = next(l for l in index.splitlines() if f"`{NAME}`" in l)
    assert "`test_remotion_master_project_docs.py`" in row and STATUS in row
    assert "`tests/unit/test_remotion_master_project_docs.py`" in DOC

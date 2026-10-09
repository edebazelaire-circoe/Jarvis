"""The store's whole-Presentation creation (jarvis-interactive-presentation-studio, Slice 11).

`FilePresentationStudioStore.create` gained `scores` and `art_directions`: a Presentation assembled by the authoring planner is
published as ONE folder by ONE rename, scores and art directions included, so a crash can never leave a Presentation whose variants
cite a score that is not there. Everything the Slice 02 `create` guarantees still holds for the new parts.
"""

from __future__ import annotations

import os

import pytest

from jarvis.adapters import file_presentation_studio_store as store_module
from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C

PID = "pst_" + "a" * 32
VID = "psv_" + "b" * 32
VID2 = "psv_" + "c" * 32
SCORE, SCORE2 = "psr_" + "1" * 12, "psr_" + "2" * 12
ART = "psd_" + "3" * 12


@pytest.fixture
def store(tmp_path) -> FilePresentationStudioStore:
    return FilePresentationStudioStore(tmp_path)


def code_of(action) -> C:
    with pytest.raises(PresentationStudioError) as caught:
        action()
    return caught.value.code


def test_a_whole_presentation_is_created_with_its_scores_and_art_directions(store, tmp_path):
    store.create(PID, "M\n", {VID: "A\n", VID2: "B\n"}, {SCORE: "S1\n", SCORE2: "S2\n"}, {ART: "D\n"})
    assert (store.read_manifest(PID), store.read_variant(PID, VID), store.read_variant(PID, VID2)) == ("M\n", "A\n", "B\n")
    assert (store.read_score(PID, SCORE), store.read_score(PID, SCORE2), store.read_art_direction(PID, ART)) == ("S1\n", "S2\n", "D\n")
    assert store.list_documents(PID, "scores") == (SCORE, SCORE2) and store.list_documents(PID, "art_directions") == (ART,)
    assert sorted(p.name for p in (tmp_path / "presentations").iterdir()) == [PID]       # published, no staging left


def test_the_old_three_argument_call_is_unchanged(store, tmp_path):
    store.create(PID, "M\n", {VID: "A\n"})
    assert not (tmp_path / "presentations" / PID / "scores").exists() and not (tmp_path / "presentations" / PID / "art_directions").exists()


def test_an_id_of_the_wrong_shape_is_refused_before_any_disk_access(store, tmp_path):
    for scores, arts in (({"psr_x": "S"}, {}), ({"../psr": "S"}, {}), ({}, {"psd_zz": "D"}), ({}, {"psd_/../x": "D"})):
        assert code_of(lambda: store.create(PID, "M", {VID: "A"}, scores, arts)) is C.INVALID_PRESENTATION
    assert not (tmp_path / "presentations").exists()


def test_a_failure_part_way_leaves_no_presentation_and_no_staging(store, tmp_path, monkeypatch):
    real = store_module._write_file
    calls = []

    def dying(path, text):
        calls.append(path.name)
        if path.name.startswith("psd_"):
            raise OSError("disk full")
        return real(path, text)

    monkeypatch.setattr(store_module, "_write_file", dying)
    assert code_of(lambda: store.create(PID, "M", {VID: "A"}, {SCORE: "S"}, {ART: "D"})) is C.STORAGE_IO
    assert calls[-1].startswith("psd_") and "presentation.json" not in calls            # the manifest is written last: never reached
    assert sorted(p.name for p in (tmp_path / "presentations").iterdir()) == []         # staging with its subfolders removed whole


def test_an_existing_id_is_refused_and_nothing_of_the_new_parts_leaks_in(store, tmp_path):
    store.create(PID, "M\n", {VID: "A\n"})
    assert code_of(lambda: store.create(PID, "N", {VID: "B"}, {SCORE: "S"}, {ART: "D"})) is C.ALREADY_EXISTS
    assert store.read_manifest(PID) == "M\n" and not (tmp_path / "presentations" / PID / "scores").exists()
    assert [p.name for p in (tmp_path / "presentations").iterdir()] == [PID]


def test_the_sweep_removes_an_interrupted_staging_that_holds_scores_and_art_directions(store, tmp_path):
    base = tmp_path / "presentations"
    staging = base / ".staging-0123456789abcdef"
    for folder in ("variants", "scores", "art_directions"):
        (staging / folder).mkdir(parents=True)
        (staging / folder / "x.json").write_text("{}", encoding="utf-8")
    (staging / "stray.txt").write_text("x", encoding="utf-8")
    report = store.sweep()
    assert report.removed == (".staging-0123456789abcdef",) and report.failed == ()
    assert not staging.exists()
    assert store.scan().presentation_ids == ()                      # a staging is never listed as a Presentation


def test_a_staging_with_a_foreign_folder_is_left_for_a_human_and_reported(store, tmp_path):
    staging = tmp_path / "presentations" / ".staging-fedcba9876543210"
    (staging / "elsewhere").mkdir(parents=True)
    report = store.sweep()
    assert report.removed == () and report.failed == (".staging-fedcba9876543210",) and staging.exists()
    assert os.path.isdir(staging / "elsewhere")

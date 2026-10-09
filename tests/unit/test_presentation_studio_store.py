"""Magasin de fichiers des Presentations (jarvis-interactive-presentation-studio, Slice 02).

Écriture atomique, création tout ou rien, balayage, lecture défensive (lien,
taille, UTF-8), ids comme composants de chemin. Le test d'arrêt brutal avec un
vrai sous-processus est dans `test_presentation_studio_crash.py`.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from jarvis.adapters import file_presentation_studio_store as store_module
from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.domain.presentation_studio import (
    MAX_DOCUMENT_BYTES, MAX_PRESENTATIONS, PresentationStudioError, PresentationStudioErrorCode as C,
)

PID = "pst_" + "a" * 32
VID = "psv_" + "b" * 32
VID2 = "psv_" + "c" * 32


@pytest.fixture
def store(tmp_path) -> FilePresentationStudioStore:
    return FilePresentationStudioStore(tmp_path)


def code_of(action) -> C:
    with pytest.raises(PresentationStudioError) as caught:
        action()
    return caught.value.code


def created(store, pid=PID, variants=None) -> None:
    store.create(pid, '{"manifest": 1}\n', variants if variants is not None else {VID: '{"variant": 1}\n'})


def test_an_empty_installation_lists_nothing_and_creates_nothing(store, tmp_path):
    assert store.scan().presentation_ids == () and not (tmp_path / "presentations").exists()
    assert store.sweep().removed == ()  # no tree: nothing to sweep, nothing created
    assert not (tmp_path / "presentations").exists()


def test_create_then_read_back_through_the_store(store, tmp_path):
    created(store, variants={VID: "A\n", VID2: "B\n"})
    assert store.read_manifest(PID) == '{"manifest": 1}\n'
    assert (store.read_variant(PID, VID), store.read_variant(PID, VID2)) == ("A\n", "B\n")
    assert store.scan().presentation_ids == (PID,)
    assert sorted(p.name for p in (tmp_path / "presentations").iterdir()) == [PID]  # no staging left


def test_create_refuses_an_existing_id_and_leaves_it_untouched(store, tmp_path):
    created(store)
    assert code_of(lambda: store.create(PID, "other", {VID: "other"})) is C.ALREADY_EXISTS
    assert store.read_manifest(PID) == '{"manifest": 1}\n'
    assert [p.name for p in (tmp_path / "presentations").iterdir()] == [PID]  # staging removed after the refusal


def test_a_failed_create_leaves_no_presentation_folder(store, tmp_path, monkeypatch):
    real = store_module._write_file

    def failing(path: Path, text: str) -> None:
        if path.name == "presentation.json":
            raise OSError(28, "No space left on device")
        real(path, text)

    monkeypatch.setattr(store_module, "_write_file", failing)
    error = pytest.raises(PresentationStudioError, store.create, PID, "m", {VID: "v"}).value
    assert error.code is C.STORAGE_IO and "No space" in error.message
    assert store.scan().presentation_ids == () and list((tmp_path / "presentations").iterdir()) == []


def test_replace_is_all_old_or_all_new_and_leaves_no_temporary(store, tmp_path):
    created(store)
    store.write_variant(PID, VID, "new variant\n")
    store.write_manifest(PID, "new manifest\n")
    assert (store.read_variant(PID, VID), store.read_manifest(PID)) == ("new variant\n", "new manifest\n")
    assert sorted(p.name for p in (tmp_path / "presentations" / PID).rglob("*") if p.is_file()) == sorted([
        f"{VID}.json", "presentation.json"])


def test_a_failed_replace_keeps_the_old_text_and_cleans_its_temporary(store, tmp_path, monkeypatch):
    created(store)

    def refuse(source, target):
        raise PermissionError(13, "locked")

    monkeypatch.setattr(store_module, "replace_with_retry", refuse)
    assert code_of(lambda: store.write_variant(PID, VID, "lost")) is C.STORAGE_IO
    monkeypatch.undo()
    assert store.read_variant(PID, VID) == '{"variant": 1}\n'
    assert not [p for p in (tmp_path / "presentations" / PID).rglob("*.tmp")]


def test_a_new_variant_file_can_be_added_to_an_existing_presentation(store):
    created(store)
    store.write_variant(PID, VID2, "second\n")
    assert store.read_variant(PID, VID2) == "second\n"


def test_unknown_things_are_typed_not_found(store):
    assert code_of(lambda: store.read_manifest(PID)) is C.UNKNOWN_PRESENTATION
    assert code_of(lambda: store.write_manifest(PID, "x")) is C.UNKNOWN_PRESENTATION
    assert code_of(lambda: store.write_variant(PID, VID, "x")) is C.UNKNOWN_PRESENTATION
    created(store)
    assert code_of(lambda: store.read_variant(PID, VID2)) is C.UNKNOWN_VARIANT


def test_ids_are_path_components_and_must_have_the_exact_shape(store):
    for bad in ("..", "../x", "pst_" + "a" * 31, "PST_" + "a" * 32, PID + "/x", PID + "\\x", "", "pst_" + "g" * 32):
        assert code_of(lambda: store.read_manifest(bad)) is C.INVALID_PRESENTATION, bad
        assert code_of(lambda: store.create(bad, "m", {})) is C.INVALID_PRESENTATION, bad
    created(store)
    for bad in ("..", "../../presentation", VID + "/..", "psv_" + "b" * 31):
        assert code_of(lambda: store.read_variant(PID, bad)) is C.INVALID_PRESENTATION, bad
        assert code_of(lambda: store.write_variant(PID, bad, "x")) is C.INVALID_PRESENTATION, bad


def test_a_folder_without_manifest_is_corrupt_not_unknown(store, tmp_path):
    (tmp_path / "presentations" / PID).mkdir(parents=True)
    error = pytest.raises(PresentationStudioError, store.read_manifest, PID).value
    assert error.code is C.CORRUPT_DOCUMENT and "does not exist" in error.message


def test_reads_refuse_oversize_non_utf8_and_non_files(store, tmp_path):
    created(store)
    folder = tmp_path / "presentations" / PID
    (folder / "presentation.json").write_bytes(b"x" * (MAX_DOCUMENT_BYTES + 1))
    assert code_of(lambda: store.read_manifest(PID)) is C.CORRUPT_DOCUMENT
    (folder / "presentation.json").write_bytes(b"\xff\xfe\x00bad")
    assert code_of(lambda: store.read_manifest(PID)) is C.CORRUPT_DOCUMENT
    (folder / "presentation.json").unlink()
    (folder / "presentation.json").mkdir()
    assert code_of(lambda: store.read_manifest(PID)) is C.CORRUPT_DOCUMENT


def test_a_linked_presentation_folder_is_refused_and_reported(store, tmp_path):
    created(store)
    target = tmp_path / "elsewhere"
    target.mkdir()
    link = tmp_path / "presentations" / ("pst_" + "d" * 32)
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        if os.name != "nt" or subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                                             capture_output=True).returncode != 0:
            pytest.skip("neither symlink privilege nor a directory junction available")
    scan = store.scan()
    assert scan.presentation_ids == (PID,) and [p.name for p in scan.problems] == [link.name]
    assert code_of(lambda: store.read_manifest(link.name)) is C.STORAGE_IO


def test_scan_reports_strange_folders_and_ignores_loose_files(store, tmp_path):
    created(store)
    base = tmp_path / "presentations"
    (base / "not-an-id").mkdir()
    (base / "notes.txt").write_text("x", encoding="utf-8")
    scan = store.scan()
    assert scan.presentation_ids == (PID,) and [(p.name, p.reason) for p in scan.problems] == [
        ("not-an-id", "folder name is not a presentation id")]


def test_scan_is_bounded(store, tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "MAX_PRESENTATIONS", 3)
    for i in range(5):
        (tmp_path / "presentations" / f"pst_{i:032x}").mkdir(parents=True, exist_ok=True)
    scan = store.scan()
    assert len(scan.presentation_ids) == 3 and "more than 3" in scan.problems[0].reason
    assert MAX_PRESENTATIONS == 256


def test_sweep_removes_only_our_leftovers_never_a_document(store, tmp_path):
    created(store)
    base = tmp_path / "presentations"
    stale = base / ".staging-0123456789abcdef"
    (stale / "variants").mkdir(parents=True)
    (stale / "variants" / f"{VID}.json").write_text("half", encoding="utf-8")
    (stale / "presentation.json.12345678.tmp").write_text("x", encoding="utf-8")
    (base / PID / "presentation.json.deadbeef.tmp").write_text("torn", encoding="utf-8")
    (base / PID / "variants" / f"{VID}.json.cafe0123.tmp").write_text("torn", encoding="utf-8")
    (base / PID / "notes.tmp").write_text("keep: not our naming", encoding="utf-8")
    (base / ".staging-not-ours").mkdir()
    report = store.sweep()
    assert sorted(report.removed) == sorted([".staging-0123456789abcdef", f"{PID}/presentation.json.deadbeef.tmp",
                                              f"{PID}/{VID}.json.cafe0123.tmp"])
    assert report.failed == ()
    assert not stale.exists() and (base / PID / "notes.tmp").exists() and (base / ".staging-not-ours").exists()
    assert store.read_manifest(PID) == '{"manifest": 1}\n' and store.read_variant(PID, VID) == '{"variant": 1}\n'


def test_a_leftover_temporary_never_blocks_the_next_save(store, tmp_path):
    created(store)
    (tmp_path / "presentations" / PID / "variants" / f"{VID}.json.00000000.tmp").write_text("torn", encoding="utf-8")
    store.write_variant(PID, VID, "fine\n")
    assert store.read_variant(PID, VID) == "fine\n"


def test_the_windows_path_limit_is_a_typed_refusal(store, tmp_path, monkeypatch):
    if os.name != "nt":
        pytest.skip("Windows MAX_PATH only")
    deep = FilePresentationStudioStore(tmp_path / ("d" * 120))
    (tmp_path / ("d" * 120)).mkdir()
    error = pytest.raises(PresentationStudioError, deep.create, PID, "m", {VID: "v"}).value
    assert error.code is C.STORAGE_IO and "limit" in error.message


# ------------------------------------------------------------------ rework (QA-1 B1, P2)

def test_a_read_retries_when_windows_refuses_the_open_once(store, monkeypatch):
    created(store)
    real_open, calls = open, []

    def flaky(path, mode="r", *args, **kwargs):
        calls.append(path)
        if len(calls) == 1:
            raise PermissionError(13, "sharing violation")
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(store_module, "open", flaky, raising=False)
    assert store.read_manifest(PID) == '{"manifest": 1}\n' and len(calls) == 2


def test_a_read_that_is_always_refused_is_a_typed_storage_error(store, monkeypatch):
    created(store)

    def refuse(path, mode="r", *args, **kwargs):
        raise PermissionError(13, "sharing violation")

    monkeypatch.setattr(store_module, "open", refuse, raising=False)
    assert code_of(lambda: store.read_manifest(PID)) is C.STORAGE_IO


def test_a_save_landing_between_inspection_and_open_is_not_corruption(store, tmp_path, monkeypatch):
    created(store)
    real_open, swapped = open, []

    def racing(path, mode="r", *args, **kwargs):
        if not swapped:  # the save's atomic replace lands exactly here: new inode under the same name
            swapped.append(True)
            store.write_manifest(PID, "newer\n")
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(store_module, "open", racing, raising=False)
    assert store.read_manifest(PID) == "newer\n"  # re-inspected, not "replaced between inspection and opening"


def test_a_file_that_keeps_changing_is_reported_after_bounded_attempts(store, monkeypatch):
    created(store)
    real_open, count = open, []

    def always_racing(path, mode="r", *args, **kwargs):
        if str(path).endswith("presentation.json"):
            count.append(1)
            store.write_manifest(PID, f"gen {len(count)}\n")
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(store_module, "open", always_racing, raising=False)
    error = pytest.raises(PresentationStudioError, store.read_manifest, PID).value
    assert error.code is C.CORRUPT_DOCUMENT and "kept changing" in error.message
    assert len([1 for c in count]) >= store_module.READ_ATTEMPTS


# ------------------------------------------------------------------ partition (Slice 10)

SID = "psr_" + "0" * 11 + "1"


def test_a_score_file_is_written_atomically_beside_the_variants_and_read_back(store, tmp_path):
    created(store)
    store.write_score(PID, SID, '{"score": 1}\n')
    assert store.read_score(PID, SID) == '{"score": 1}\n'
    assert (tmp_path / "presentations" / PID / "scores" / f"{SID}.json").is_file()
    store.write_score(PID, SID, '{"score": 2}\n')  # replaces, whole
    assert store.read_score(PID, SID) == '{"score": 2}\n'
    assert list((tmp_path / "presentations" / PID / "scores").glob("*.tmp")) == []
    assert store.read_variant(PID, VID) == '{"variant": 1}\n' and store.read_manifest(PID) == '{"manifest": 1}\n'


def test_score_reads_and_writes_are_typed_refusals_for_unknown_things_and_bad_ids(store):
    created(store)
    assert code_of(lambda: store.read_score(PID, SID)) is C.UNKNOWN_SCORE  # no scores/ folder yet
    store.write_score(PID, SID, "x\n")
    assert code_of(lambda: store.read_score(PID, "psr_" + "f" * 12)) is C.UNKNOWN_SCORE
    assert code_of(lambda: store.write_score("pst_" + "0" * 32, SID, "x")) is C.UNKNOWN_PRESENTATION
    for bad in ("../x", "psr_..", "psr_XYZ", "psv_" + "0" * 32, "", "psr_" + "0" * 13):
        assert code_of(lambda bad=bad: store.read_score(PID, bad)) is C.INVALID_PRESENTATION
        assert code_of(lambda bad=bad: store.write_score(PID, bad, "x")) is C.INVALID_PRESENTATION
    assert code_of(lambda: store.read_score("../../x", SID)) is C.INVALID_PRESENTATION


def test_an_oversize_score_is_corrupt_not_read(store, tmp_path):
    created(store)
    store.write_score(PID, SID, "x\n")
    path = tmp_path / "presentations" / PID / "scores" / f"{SID}.json"
    path.write_bytes(b"x" * (MAX_DOCUMENT_BYTES + 1))
    assert code_of(lambda: store.read_score(PID, SID)) is C.CORRUPT_DOCUMENT


def test_sweep_clears_a_score_temporary_and_never_a_score_document(store, tmp_path):
    created(store)
    store.write_score(PID, SID, "keep\n")
    leftover = tmp_path / "presentations" / PID / "scores" / f"{SID}.json.cafe0123.tmp"
    leftover.write_text("torn", encoding="utf-8")
    report = store.sweep()
    assert report.removed == (f"{PID}/{SID}.json.cafe0123.tmp",) and report.failed == ()
    assert store.read_score(PID, SID) == "keep\n"


def test_a_failed_score_replace_keeps_the_old_text_and_cleans_its_temporary(store, tmp_path, monkeypatch):
    created(store)
    store.write_score(PID, SID, "old\n")

    def boom(source, target):
        raise PermissionError("locked")

    monkeypatch.setattr(store_module, "replace_with_retry", boom)
    assert code_of(lambda: store.write_score(PID, SID, "new\n")) is C.STORAGE_IO
    monkeypatch.undo()
    assert store.read_score(PID, SID) == "old\n"
    assert list((tmp_path / "presentations" / PID / "scores").glob("*.tmp")) == []


# ------------------------------------------------------------------ direction artistique (Slice 09)

AID = "psd_" + "0" * 11 + "1"


def test_an_art_direction_file_is_written_atomically_beside_the_variants_and_read_back(store, tmp_path):
    created(store)
    store.write_art_direction(PID, AID, '{"art": 1}\n')
    assert store.read_art_direction(PID, AID) == '{"art": 1}\n'
    assert (tmp_path / "presentations" / PID / "art_directions" / f"{AID}.json").is_file()
    store.write_art_direction(PID, AID, '{"art": 2}\n')  # replaces, whole
    assert store.read_art_direction(PID, AID) == '{"art": 2}\n'
    assert list((tmp_path / "presentations" / PID / "art_directions").glob("*.tmp")) == []
    assert store.read_variant(PID, VID) == '{"variant": 1}\n' and store.read_manifest(PID) == '{"manifest": 1}\n'


def test_art_direction_reads_and_writes_are_typed_refusals_for_unknown_things_and_bad_ids(store):
    created(store)
    assert code_of(lambda: store.read_art_direction(PID, AID)) is C.UNKNOWN_ART_DIRECTION  # no art_directions/ folder yet
    store.write_art_direction(PID, AID, "x\n")
    assert code_of(lambda: store.read_art_direction(PID, "psd_" + "f" * 12)) is C.UNKNOWN_ART_DIRECTION
    assert code_of(lambda: store.write_art_direction("pst_" + "0" * 32, AID, "x")) is C.UNKNOWN_PRESENTATION
    for bad in ("../x", "psd_..", "psd_XYZ", "psr_" + "0" * 12, "", "psd_" + "0" * 13, "psd_" + "0" * 11 + "\n"):
        assert code_of(lambda bad=bad: store.read_art_direction(PID, bad)) is C.INVALID_PRESENTATION
        assert code_of(lambda bad=bad: store.write_art_direction(PID, bad, "x")) is C.INVALID_PRESENTATION
    assert code_of(lambda: store.read_art_direction("../../x", AID)) is C.INVALID_PRESENTATION


def test_an_oversize_art_direction_is_corrupt_not_read(store, tmp_path):
    created(store)
    store.write_art_direction(PID, AID, "x\n")
    path = tmp_path / "presentations" / PID / "art_directions" / f"{AID}.json"
    path.write_bytes(b"x" * (MAX_DOCUMENT_BYTES + 1))
    assert code_of(lambda: store.read_art_direction(PID, AID)) is C.CORRUPT_DOCUMENT


def test_sweep_clears_an_art_direction_temporary_and_never_an_art_direction_document(store, tmp_path):
    created(store)
    store.write_art_direction(PID, AID, "keep\n")
    leftover = tmp_path / "presentations" / PID / "art_directions" / f"{AID}.json.cafe0123.tmp"
    leftover.write_text("torn", encoding="utf-8")
    report = store.sweep()
    assert report.removed == (f"{PID}/{AID}.json.cafe0123.tmp",) and report.failed == ()
    assert store.read_art_direction(PID, AID) == "keep\n"


def test_a_failed_art_direction_replace_keeps_the_old_text_and_cleans_its_temporary(store, tmp_path, monkeypatch):
    created(store)
    store.write_art_direction(PID, AID, "old\n")

    def boom(source, target):
        raise PermissionError("locked")

    monkeypatch.setattr(store_module, "replace_with_retry", boom)
    assert code_of(lambda: store.write_art_direction(PID, AID, "new\n")) is C.STORAGE_IO
    monkeypatch.undo()
    assert store.read_art_direction(PID, AID) == "old\n"
    assert list((tmp_path / "presentations" / PID / "art_directions").glob("*.tmp")) == []


def test_art_directions_and_scores_live_in_separate_folders(store, tmp_path):
    created(store)
    store.write_art_direction(PID, AID, "a\n")
    store.write_score(PID, "psr_" + "0" * 11 + "1", "s\n")
    folder = tmp_path / "presentations" / PID
    assert sorted(p.name for p in (folder / "art_directions").iterdir()) == [f"{AID}.json"]
    assert sorted(p.name for p in (folder / "scores").iterdir()) == ["psr_000000000001.json"]

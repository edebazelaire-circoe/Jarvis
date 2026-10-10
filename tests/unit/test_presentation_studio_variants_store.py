"""Zone `archive/` du magasin de fichiers (jarvis-interactive-presentation-studio, Slice 16).

`move_variant` (un seul renommage, jamais un remplacement ni une copie), `list_documents` (zones fermées, noms exacts),
`read_archived_variant`, balayage des temporaires de la zone, défenses de chemin (lien, jonction). Le contrat est dans
`docs/presentation-studio.md` › *Variant graph and operations contract*.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C

PID = "pst_" + "a" * 32
VID = "psv_" + "b" * 32
VID2 = "psv_" + "c" * 32
SCORE = "psr_" + "1" * 12


@pytest.fixture
def store(tmp_path) -> FilePresentationStudioStore:
    made = FilePresentationStudioStore(tmp_path)
    made.create(PID, '{"manifest": 1}\n', {VID: "A\n", VID2: "B\n"})
    return made


def code_of(action) -> C:
    with pytest.raises(PresentationStudioError) as caught:
        action()
    return caught.value.code


def folder(tmp_path: Path) -> Path:
    return tmp_path / "presentations" / PID


def test_a_move_is_one_rename_both_ways_and_the_bytes_are_untouched(store, tmp_path):
    before = (folder(tmp_path) / "variants" / f"{VID}.json").read_bytes()
    assert not (folder(tmp_path) / "archive").exists()  # the area appears with the first archive, not before
    store.move_variant(PID, VID, "archive")
    assert not (folder(tmp_path) / "variants" / f"{VID}.json").exists()
    assert (folder(tmp_path) / "archive" / f"{VID}.json").read_bytes() == before
    assert store.read_archived_variant(PID, VID) == "A\n" and store.list_documents(PID, "archive") == (VID,)
    assert code_of(lambda: store.read_variant(PID, VID)) is C.UNKNOWN_VARIANT
    store.move_variant(PID, VID, "variants")
    assert store.read_variant(PID, VID) == "A\n" and store.list_documents(PID, "archive") == ()


def test_a_move_never_replaces_and_never_invents(store, tmp_path):
    store.move_variant(PID, VID, "archive")
    (folder(tmp_path) / "variants" / f"{VID}.json").write_bytes(b"another A\n")  # a second copy appears
    assert code_of(lambda: store.move_variant(PID, VID, "archive")) is C.ALREADY_EXISTS
    assert code_of(lambda: store.move_variant(PID, VID, "variants")) is C.ALREADY_EXISTS
    assert store.read_archived_variant(PID, VID) == "A\n" and store.read_variant(PID, VID) == "another A\n"
    assert code_of(lambda: store.move_variant(PID, "psv_" + "d" * 32, "archive")) is C.UNKNOWN_VARIANT
    assert code_of(lambda: store.move_variant(PID, "psv_" + "e" * 32, "variants")) is C.UNKNOWN_VARIANT
    assert code_of(lambda: store.move_variant("pst_" + "9" * 32, VID, "archive")) is C.UNKNOWN_PRESENTATION
    assert code_of(lambda: store.move_variant(PID, VID, "elsewhere")) is C.INVALID_PRESENTATION


def test_ids_are_exact_path_components_for_the_new_calls(store):
    for bad in ("../x", "psv_x", "psv_" + "B" * 32, "psv_" + "b" * 31 + "\n"):
        assert code_of(lambda bad=bad: store.move_variant(PID, bad, "archive")) is C.INVALID_PRESENTATION
        assert code_of(lambda bad=bad: store.read_archived_variant(PID, bad)) is C.INVALID_PRESENTATION
    assert code_of(lambda: store.list_documents("../x", "variants")) is C.INVALID_PRESENTATION
    assert code_of(lambda: store.list_documents(PID, "../scores")) is C.INVALID_PRESENTATION
    assert code_of(lambda: store.list_documents(PID, "presentation.json")) is C.INVALID_PRESENTATION


def test_listing_names_documents_by_exact_id_and_ignores_everything_else(store, tmp_path):
    area = folder(tmp_path) / "scores"
    area.mkdir()
    for name in (f"{SCORE}.json", f"{SCORE}.json.deadbeef.tmp", "notes.json", "psr_XYZ.json", "psr_" + "2" * 12):
        (area / name).write_text("x", encoding="utf-8")
    (area / ("psr_" + "3" * 12 + ".json")).mkdir()  # a folder named like a document is not one
    assert store.list_documents(PID, "scores") == (SCORE,)
    assert store.list_documents(PID, "variants") == (VID, VID2)
    assert store.list_documents(PID, "archive") == () and store.list_documents("pst_" + "7" * 32, "variants") == ()


def test_a_linked_archive_folder_is_refused_not_followed(store, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    link = folder(tmp_path) / "archive"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError:
        if os.name != "nt" or subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True).returncode != 0:
            pytest.skip("neither symlink privilege nor a directory junction available")
    assert code_of(lambda: store.move_variant(PID, VID, "archive")) is C.STORAGE_IO
    assert code_of(lambda: store.list_documents(PID, "archive")) is C.STORAGE_IO
    assert (folder(tmp_path) / "variants" / f"{VID}.json").exists() and not list(outside.iterdir()), "nothing was moved through the link"


def test_sweep_clears_our_temporaries_in_the_archive_area_and_never_a_document(store, tmp_path):
    store.move_variant(PID, VID, "archive")
    leftover = folder(tmp_path) / "archive" / f"{VID2}.json.cafe0123.tmp"
    leftover.write_text("torn", encoding="utf-8")
    report = store.sweep()
    assert f"{PID}/{VID2}.json.cafe0123.tmp" in report.removed and not leftover.exists()
    assert store.read_archived_variant(PID, VID) == "A\n"


def test_the_flush_refusal_of_a_move_is_told_once(tmp_path, monkeypatch):
    from jarvis.adapters import file_presentation_studio_store as module
    told = []
    store = FilePresentationStudioStore(tmp_path, on_flush_refused=told.append)
    store.create(PID, "m\n", {VID: "A\n", VID2: "B\n"})
    monkeypatch.setattr(module, "_sync_folder", lambda folder: False)
    store.move_variant(PID, VID, "archive")
    store.move_variant(PID, VID2, "archive")
    assert told == ["move"], "the move stands, the refused flush is reported once per run"


# ------------------------------------------------------------------ un seul renommage, jamais copie puis suppression (QA-1 P3, P4)

def test_a_move_is_a_single_rename_never_a_copy_then_delete(store, tmp_path, monkeypatch):
    import shutil

    source = folder(tmp_path) / "variants" / f"{VID}.json"
    inode = os.stat(source).st_ino

    def forbidden(*args, **kwargs):
        pytest.fail("a move must not copy bytes nor delete a file")

    for name in ("copyfile", "copy", "copy2", "copyfileobj", "move"):
        monkeypatch.setattr(shutil, name, forbidden)
    monkeypatch.setattr(os, "remove", forbidden)
    if os.name == "nt":
        monkeypatch.setattr(os, "unlink", forbidden)  # on POSIX the old name is unlinked after the hard link (same inode)
    store.move_variant(PID, VID, "archive")
    target = folder(tmp_path) / "archive" / f"{VID}.json"
    assert not source.exists() and target.read_bytes() == b"A\n"
    if inode:
        assert os.stat(target).st_ino == inode, "the very same file got its new name: no content was rewritten"


def test_the_posix_primitive_links_then_drops_the_old_name_and_never_replaces(tmp_path):
    from jarvis.adapters.file_presentation_studio_store import _rename_no_replace

    source, target, other = tmp_path / "a.json", tmp_path / "b.json", tmp_path / "c.json"
    source.write_bytes(b"A")
    inode = os.stat(source).st_ino
    _rename_no_replace(source, target, posix=True)
    assert not source.exists() and target.read_bytes() == b"A" and (not inode or os.stat(target).st_ino == inode)
    other.write_bytes(b"other")
    source.write_bytes(b"B")
    with pytest.raises(FileExistsError):
        _rename_no_replace(source, other, posix=True)
    assert source.read_bytes() == b"B" and other.read_bytes() == b"other", "neither file was touched"
    with pytest.raises(FileExistsError):
        _rename_no_replace(source, other, posix=False)


def test_the_posix_fallback_without_hard_links_still_refuses_an_existing_target(tmp_path, monkeypatch):
    from jarvis.adapters.file_presentation_studio_store import _rename_no_replace

    def no_links(*args, **kwargs):
        raise PermissionError("no hard links here")

    monkeypatch.setattr(os, "link", no_links)
    source, target = tmp_path / "a.json", tmp_path / "b.json"
    source.write_bytes(b"A")
    _rename_no_replace(source, target, posix=True)
    assert target.read_bytes() == b"A" and not source.exists()
    source.write_bytes(b"B")
    with pytest.raises(FileExistsError):
        _rename_no_replace(source, target, posix=True)
    assert target.read_bytes() == b"A"


# ------------------------------------------------------------------ copie du manifeste d'une ancienne version (QA-1 O1)

def test_the_first_rewrite_of_an_older_manifest_keeps_its_exact_bytes_once_and_never_replaces_them(tmp_path):
    made = FilePresentationStudioStore(tmp_path)
    v1 = b'{"schema_version": 1,\r\n "x": "\xc3\xa9"}\r\n'
    made.create(PID, "placeholder\n", {VID: "A\n"})
    (folder(tmp_path) / "presentation.json").write_bytes(v1)
    made.write_manifest(PID, '{"schema_version": 2, "n": 1}\n')
    backup = folder(tmp_path) / "presentation.json.v1.bak"
    assert backup.read_bytes() == v1, "byte for byte, line endings and accents included"
    made.write_manifest(PID, '{"schema_version": 2, "n": 2}\n')
    (folder(tmp_path) / "presentation.json").write_bytes(b'{"schema_version": 1, "x": "again"}\n')  # even a v1 coming back later
    made.write_manifest(PID, '{"schema_version": 2, "n": 3}\n')
    assert backup.read_bytes() == v1, "kept once, never overwritten"
    assert made.sweep().failed == () and backup.exists(), "the sweep never deletes it"
    assert [p.name for p in folder(tmp_path).glob("*.bak")] == ["presentation.json.v1.bak"]


def test_no_copy_is_made_when_nothing_older_is_replaced(tmp_path):
    made = FilePresentationStudioStore(tmp_path)
    made.create(PID, '{"schema_version": 2}\n', {VID: "A\n"})
    made.write_manifest(PID, '{"schema_version": 2, "n": 1}\n')
    made.write_manifest(PID, "not json at all\n")
    made.write_manifest(PID, '{"schema_version": 3}\n')  # garbage before it: no readable older version, no copy
    assert not list(folder(tmp_path).glob("*.bak"))

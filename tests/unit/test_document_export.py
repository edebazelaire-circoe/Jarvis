"""Export explicite (presentation-edition-v1 Slice 03, `docs/export.md`) : nom, collisions, bornes de la racine, copie atomique.

Aucun test ne touche le vrai dossier Documents : la racine vient d'un résolveur simulé sous `tmp_path`.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from jarvis.adapters import export_destination as dest_module
from jarvis.adapters.export_destination import ExportDestination, check_root_shape, link_like
from jarvis.adapters.known_folders import KnownFolderError, documents_folder
from jarvis.domain.artifacts import ArtifactKind
from jarvis.domain.document_export import (
    EXPORT_CLASSES, FALLBACK_STEM, MAX_COLLISIONS, MAX_STEM_CHARS, TEMP_SUFFIX, ExportError, ExportErrorCode as E,
    candidate_names, default_stem, export_class_of, file_stem,
)

REPO = Path(__file__).resolve().parents[2]


def destination(tmp_path, *, forbidden=(), override=None, documents=None):
    docs = tmp_path / "home" / "Documents"
    docs.mkdir(parents=True, exist_ok=True)
    return ExportDestination(forbidden=forbidden or (tmp_path / "data",), override=override,
                             documents=documents or (lambda: docs)), docs


def source_file(tmp_path, data=b"payload bytes" * 100, name="render.mp4"):
    folder = tmp_path / "data" / "artifacts" / "jart_x"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(data)
    return path, len(data), hashlib.sha256(data).hexdigest()


def junction(link: Path, target: Path) -> None:
    if os.name != "nt":
        os.symlink(target, link, target_is_directory=True)
        return
    import _winapi
    _winapi.CreateJunction(str(target), str(link))


# ------------------------------------------------------------------ classes et noms


def test_the_exportable_classes_are_the_three_existing_final_derivatives_and_nothing_else():
    assert {c.kind for c in EXPORT_CLASSES.values()} == {ArtifactKind.PRESENTATION_VIDEO, ArtifactKind.PRESENTATION_STILL,
                                                        ArtifactKind.PRESENTATION_PDF}
    assert {(c.format, c.extension, c.mime_type) for c in EXPORT_CLASSES.values()} == {
        ("mp4", ".mp4", "video/mp4"), ("still", ".png", "image/png"), ("pdf", ".pdf", "application/pdf")}
    for internal in (ArtifactKind.PRESENTATION_SNAPSHOT, ArtifactKind.SCREENSHOT):
        with pytest.raises(ExportError) as caught:
            export_class_of(internal)
        assert caught.value.code is E.SOURCE_NOT_EXPORTABLE and caught.value.status == 409


@pytest.mark.parametrize("raw, expected", [
    ("Atelier", "Atelier"),
    ("..\\..\\Windows\\System32\\evil", "Windows System32 evil"),
    ("../../etc/passwd", "etc passwd"),
    ("C:\\Users\\x\\Desktop\\out", "C Users x Desktop out"),
    ('a<b>c:d"e|f?g*h', "a b c d e f g h"),
    ("nom.   ", "nom"),
    ("..", FALLBACK_STEM), ("", FALLBACK_STEM), (None, FALLBACK_STEM), ("   ", FALLBACK_STEM),
    ("CON", "_CON"), ("nul.txt", "_nul.txt"), ("COM1", "_COM1"), ("Console", "Console"),
    ("tab\there\nnew", "tab here new"),
])
def test_a_file_stem_is_one_safe_component(raw, expected):
    stem = file_stem(raw)
    assert stem == expected
    assert "/" not in stem and "\\" not in stem and ":" not in stem and stem not in (".", "..")


def test_a_long_title_is_bounded_and_the_default_name_says_the_class():
    assert len(file_stem("x" * 500)) == MAX_STEM_CHARS
    assert default_stem("Atelier", EXPORT_CLASSES[ArtifactKind.PRESENTATION_VIDEO]) == "Atelier - video"
    assert default_stem(None, EXPORT_CLASSES[ArtifactKind.PRESENTATION_PDF]) == f"{FALLBACK_STEM} - pdf"


def test_collision_candidates_never_reuse_a_name_and_are_bounded():
    names = list(candidate_names("Atelier", ".mp4"))
    assert names[:3] == ["Atelier.mp4", "Atelier (2).mp4", "Atelier (3).mp4"]
    assert len(names) == MAX_COLLISIONS == len(set(names))


# ------------------------------------------------------------------ forme de la racine


@pytest.mark.parametrize("raw", ["", "relative\\path", "C:\\", "C:/", "\\\\server\\share\\Jarvis", "//server/share/x",
                                 "\\\\?\\C:\\Users\\x", "C:\\Users\\..\\Windows", "/"])
def test_an_unsafe_root_shape_is_refused(raw):
    with pytest.raises(ExportError) as caught:
        check_root_shape(raw)
    assert caught.value.code is E.DESTINATION_UNSAFE


def test_a_drive_root_from_the_documents_api_is_refused(tmp_path):
    anchor = Path(tmp_path.anchor)
    d = ExportDestination(forbidden=(tmp_path / "data",), documents=lambda: anchor)
    # `<drive>\Jarvis` would be the root: the Documents base itself is a drive root, refused
    with pytest.raises(ExportError) as caught:
        d.resolve()
    assert caught.value.code is E.DESTINATION_UNSAFE


def test_the_documents_api_failure_is_a_typed_unavailable_root(tmp_path):
    def broken():
        raise KnownFolderError("SHGetKnownFolderPath(FOLDERID_Documents) failed: HRESULT 0x80070002")
    d = ExportDestination(forbidden=(), documents=broken)
    assert d.describe() == {"available": False, "root": "Documents\\Jarvis", "code": "export_destination_unavailable",
                            "message": "SHGetKnownFolderPath(FOLDERID_Documents) failed: HRESULT 0x80070002"}


@pytest.mark.skipif(os.name != "nt", reason="Windows known-folder API")
def test_the_real_documents_api_answers_an_absolute_folder_without_creating_anything():
    found = documents_folder()
    assert found.is_absolute() and found.parent != found


# ------------------------------------------------------------------ racine : rien avant le premier export


def test_describing_or_resolving_the_root_creates_nothing(tmp_path):
    d, docs = destination(tmp_path)
    assert d.describe() == {"available": True, "root": "Documents\\Jarvis", "exists": False}
    root, exists = d.resolve()
    assert root == docs / "Jarvis" and exists is False and list(docs.iterdir()) == []


def test_a_first_export_creates_documents_jarvis_and_copies_the_bytes(tmp_path):
    d, docs = destination(tmp_path)
    src, size, sha = source_file(tmp_path)
    out = d.copy_in(src, stem="Atelier - video", extension=".mp4", expected_size=size, expected_sha256=sha)
    final = docs / "Jarvis" / "Atelier - video.mp4"
    assert out.file_name == final.name and out.size_bytes == size and out.sha256 == sha and out.renamed is False
    assert final.read_bytes() == src.read_bytes() and src.exists(), "a copy: the canonical payload stays in place"
    assert [p.name for p in (docs / "Jarvis").iterdir()] == [final.name], "no temporary file is left behind"


def test_a_collision_takes_the_next_numbered_name_and_never_overwrites(tmp_path):
    d, docs = destination(tmp_path)
    (docs / "Jarvis").mkdir()
    (docs / "Jarvis" / "Atelier.mp4").write_bytes(b"user's own file")
    (docs / "Jarvis" / "Atelier (2).mp4").mkdir()  # even a folder takes a name
    src, size, sha = source_file(tmp_path)
    out = d.copy_in(src, stem="Atelier", extension=".mp4", expected_size=size, expected_sha256=sha)
    assert out.file_name == "Atelier (3).mp4" and out.renamed is True
    assert (docs / "Jarvis" / "Atelier.mp4").read_bytes() == b"user's own file"


def test_all_names_taken_is_a_typed_refusal(tmp_path, monkeypatch):
    d, docs = destination(tmp_path)
    monkeypatch.setattr(dest_module, "candidate_names", lambda stem, ext: iter([f"{stem}{ext}"]))
    (docs / "Jarvis").mkdir()
    (docs / "Jarvis" / "A.mp4").write_bytes(b"x")
    src, size, sha = source_file(tmp_path)
    with pytest.raises(ExportError) as caught:
        d.copy_in(src, stem="A", extension=".mp4", expected_size=size, expected_sha256=sha)
    assert caught.value.code is E.COLLISION_EXHAUSTED
    assert sorted(p.name for p in (docs / "Jarvis").iterdir()) == ["A.mp4"], "the temporary file is removed"


def test_a_name_taken_between_check_and_rename_moves_to_the_next(tmp_path, monkeypatch):
    d, docs = destination(tmp_path)
    real = dest_module._rename_no_replace
    raced = []

    def racing(temp, final):
        if not raced:
            raced.append(final.name)
            final.write_bytes(b"concurrent")  # another export won the name
        return real(temp, final)
    monkeypatch.setattr(dest_module, "_rename_no_replace", racing)
    src, size, sha = source_file(tmp_path)
    out = d.copy_in(src, stem="A", extension=".pdf", expected_size=size, expected_sha256=sha)
    assert raced == ["A.pdf"] and out.file_name == "A (2).pdf"
    assert (docs / "Jarvis" / "A.pdf").read_bytes() == b"concurrent"


def test_a_payload_that_does_not_match_its_record_is_not_kept(tmp_path):
    d, docs = destination(tmp_path)
    src, size, _sha = source_file(tmp_path)
    with pytest.raises(ExportError) as caught:
        d.copy_in(src, stem="A", extension=".mp4", expected_size=size, expected_sha256="0" * 64)
    assert caught.value.code is E.SOURCE_UNAVAILABLE
    assert list((docs / "Jarvis").iterdir()) == []
    with pytest.raises(ExportError) as caught:
        d.copy_in(src, stem="A", extension=".mp4", expected_size=size + 1, expected_sha256=None)
    assert caught.value.code is E.SOURCE_UNAVAILABLE and list((docs / "Jarvis").iterdir()) == []


def test_a_failure_during_the_copy_removes_the_temporary_file(tmp_path, monkeypatch):
    d, docs = destination(tmp_path)
    src, size, sha = source_file(tmp_path)

    def boom(temp, root, stem, ext):
        assert temp.name.endswith(TEMP_SUFFIX) and temp.parent == docs / "Jarvis" and temp.exists()
        raise OSError("disk went away")
    monkeypatch.setattr(ExportDestination, "_publish", lambda self, *a: boom(*a))
    with pytest.raises(OSError):
        d.copy_in(src, stem="A", extension=".mp4", expected_size=size, expected_sha256=sha)
    assert list((docs / "Jarvis").iterdir()) == []


def test_a_missing_canonical_payload_is_a_typed_refusal(tmp_path):
    d, _docs = destination(tmp_path)
    with pytest.raises(ExportError) as caught:
        d.copy_in(tmp_path / "nope.mp4", stem="A", extension=".mp4", expected_size=None, expected_sha256=None)
    assert caught.value.code is E.SOURCE_UNAVAILABLE


# ------------------------------------------------------------------ évasion : jonctions, liens, points d'analyse


def test_a_junction_as_the_export_folder_is_refused_and_nothing_is_written_through_it(tmp_path):
    d, docs = destination(tmp_path)
    elsewhere = tmp_path / "Desktop"
    elsewhere.mkdir()
    junction(docs / "Jarvis", elsewhere)
    src, size, sha = source_file(tmp_path)
    with pytest.raises(ExportError) as caught:
        d.copy_in(src, stem="outside", extension=".mp4", expected_size=size, expected_sha256=sha)
    assert caught.value.code is E.DESTINATION_UNSAFE
    assert list(elsewhere.iterdir()) == []
    assert d.describe()["code"] == "export_destination_unsafe"


def test_a_documents_folder_reached_through_a_junction_is_refused(tmp_path):
    real = tmp_path / "real-docs"
    real.mkdir()
    linked = tmp_path / "linked-docs"
    junction(linked, real)
    d = ExportDestination(forbidden=(tmp_path / "data",), documents=lambda: linked)
    src, size, sha = source_file(tmp_path)
    with pytest.raises(ExportError) as caught:
        d.copy_in(src, stem="A", extension=".mp4", expected_size=size, expected_sha256=sha)
    assert caught.value.code is E.DESTINATION_UNSAFE and list(real.iterdir()) == []


def test_a_symbolic_link_as_the_export_folder_is_refused(tmp_path):
    d, docs = destination(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    try:
        os.symlink(target, docs / "Jarvis", target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links need a privilege on this machine")
    with pytest.raises(ExportError) as caught:
        d.resolve(create=True)
    assert caught.value.code is E.DESTINATION_UNSAFE


def test_a_file_named_like_the_export_folder_is_refused(tmp_path):
    d, docs = destination(tmp_path)
    (docs / "Jarvis").write_bytes(b"not a folder")
    with pytest.raises(ExportError) as caught:
        d.resolve(create=True)
    assert caught.value.code is E.DESTINATION_UNSAFE


def test_a_canonical_payload_that_is_a_link_is_refused(tmp_path):
    d, _docs = destination(tmp_path)
    real, size, sha = source_file(tmp_path)
    link = real.with_name("link.mp4")
    try:
        os.symlink(real, link)
    except OSError:
        pytest.skip("symbolic links need a privilege on this machine")
    with pytest.raises(ExportError) as caught:
        d.copy_in(link, stem="A", extension=".mp4", expected_size=size, expected_sha256=sha)
    assert caught.value.code is E.SOURCE_UNAVAILABLE


def _stat(mode, attributes=0, tag=0):
    return SimpleNamespace(st_mode=mode, st_file_attributes=attributes, st_reparse_tag=tag)


def test_reparse_points_are_link_like_except_onedrive_cloud_folders():
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    assert link_like(_stat(stat.S_IFDIR)) is False
    assert link_like(_stat(stat.S_IFLNK)) is True
    assert link_like(_stat(stat.S_IFDIR, reparse, 0xA0000003)) is True   # junction (mount point)
    assert link_like(_stat(stat.S_IFDIR, reparse, 0xA000000C)) is True   # symbolic link
    assert link_like(_stat(stat.S_IFDIR, reparse, 0x80000013)) is True   # any other reparse point (dedup...)
    assert link_like(_stat(stat.S_IFDIR, reparse, 0x9000001A)) is False  # IO_REPARSE_TAG_CLOUD
    assert link_like(_stat(stat.S_IFDIR, reparse, 0x9000601A)) is False  # IO_REPARSE_TAG_CLOUD_6


# ------------------------------------------------------------------ destinations interdites


@pytest.mark.parametrize("where", ["data", "data/CONTEXT_GLOBAL", "data/CONTEXT_GLOBAL/sub"])
def test_an_override_inside_internal_storage_is_forbidden(tmp_path, where):
    data = tmp_path / "data"
    (data / "CONTEXT_GLOBAL" / "sub").mkdir(parents=True)
    d = ExportDestination(forbidden=(data, data / "CONTEXT_GLOBAL"), override=str(tmp_path / where / "exports"))
    with pytest.raises(ExportError) as caught:
        d.resolve(create=True)
    assert caught.value.code is E.DESTINATION_FORBIDDEN
    assert not (tmp_path / where / "exports").exists()


def test_a_root_that_contains_internal_storage_is_forbidden(tmp_path):
    docs = tmp_path / "Documents"
    (docs / "Jarvis" / "data").mkdir(parents=True)
    d = ExportDestination(forbidden=(docs / "Jarvis" / "data",), documents=lambda: docs)
    with pytest.raises(ExportError) as caught:
        d.resolve()
    assert caught.value.code is E.DESTINATION_FORBIDDEN


def test_the_environment_forbids_data_global_context_runtime_program_and_product_home(tmp_path):
    local = tmp_path / "Local"
    env = {"LOCALAPPDATA": str(local), "JARVIS_RUNTIME_DIR": str(tmp_path / "rt"),
           "JARVIS_EXPORT_ROOT": str(tmp_path / "rt" / "exports")}
    (tmp_path / "rt").mkdir()
    d = ExportDestination.from_environment(data_root=tmp_path / "data", environ=env)
    with pytest.raises(ExportError) as caught:
        d.resolve()
    assert caught.value.code is E.DESTINATION_FORBIDDEN
    from jarvis.installation import CODE_ROOT
    d = ExportDestination.from_environment(data_root=tmp_path / "data",
                                           environ={**env, "JARVIS_EXPORT_ROOT": str(CODE_ROOT / "exports")})
    with pytest.raises(ExportError) as caught:
        d.resolve()
    assert caught.value.code is E.DESTINATION_FORBIDDEN


def test_the_installed_product_home_is_forbidden(tmp_path, monkeypatch):
    from jarvis.installation import Installation, InstallMode, ProductHome
    home = tmp_path / "Local" / "CIRCOE" / "Jarvis"
    home.mkdir(parents=True)
    monkeypatch.setattr("jarvis.installation.detect_installation",
                        lambda env=None, code_root=None: Installation(InstallMode.INSTALLED, tmp_path, ProductHome(home)))
    d = ExportDestination.from_environment(data_root=tmp_path / "data",
                                           environ={"JARVIS_RUNTIME_DIR": str(tmp_path / "rt"),
                                                    "JARVIS_EXPORT_ROOT": str(home / "exports")})
    with pytest.raises(ExportError) as caught:
        d.resolve()
    assert caught.value.code is E.DESTINATION_FORBIDDEN


def test_the_override_label_never_names_the_users_path(tmp_path):
    (tmp_path / "ok").mkdir()
    d = ExportDestination(forbidden=(tmp_path / "data",), override=str(tmp_path / "ok" / "exports"))
    assert d.describe() == {"available": True, "root": "JARVIS_EXPORT_ROOT", "exists": False}


# ------------------------------------------------------------------ régression : personne d'autre n'écrit chez l'utilisateur


def test_only_the_export_adapter_resolves_the_users_documents_folder():
    users = []
    for path in (REPO / "jarvis").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in ("documents_folder", "FOLDERID_DOCUMENTS", "SHGetKnownFolderPath", "EXPORT_ROOT_ENV")):
            users.append(path.relative_to(REPO).as_posix())
    assert sorted(users) == ["jarvis/adapters/export_destination.py", "jarvis/adapters/known_folders.py"]

"""Mémoire de Board sur disque : racine, lecture bornée, écritures atomiques, refus de sortie.

Handoff board-memory-workspace-inspector, Slice 02. Contrat : `docs/boards.md`
› *Board memory*. Racines temporaires (`tmp_path`) seulement. Les tentatives
d'évasion utilisent une **vraie** jonction Windows et un vrai lien symbolique.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.adapters import board_memory_store
from jarvis.adapters.board_memory_store import (
    MAX_APPEND_FILE_BYTES, MAX_TREE_DEPTH, TEMP_PREFIX, FileBoardMemoryStore,
)
from jarvis.domain.board_memory import MAX_MEMORY_IO_BYTES, BoardMemoryError, BoardMemoryErrorCode, BoardMemoryPath
from jarvis.domain.workspace_board import BoardError, BoardErrorCode
from jarvis.ports.board_memory import (
    MEMORY_STORE_FAILED, MEMORY_STORE_UNSAFE, BoardMemoryUnavailable, MemoryEntryKind, WriteMode,
)

BOARD = "board_0123456789abcdef"
C = BoardMemoryErrorCode


def P(value: str) -> BoardMemoryPath:  # noqa: N802
    return BoardMemoryPath.parse(value)


@pytest.fixture
def data_root(tmp_path) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    return root


@pytest.fixture
def store(data_root) -> FileBoardMemoryStore:
    return FileBoardMemoryStore(data_root)


def memory(data_root: Path, board_id: str = BOARD) -> Path:
    return data_root / "boards" / board_id / "memory"


def refused(code: BoardMemoryErrorCode, call, *args, **kwargs):  # noqa: ANN001, ANN201
    with pytest.raises(BoardMemoryError) as caught:
        call(*args, **kwargs)
    assert caught.value.code is code, caught.value
    return caught.value


def junction(link: Path, target: Path) -> None:
    """Vraie jonction NTFS (`mklink /J`) ; `skip` motivé seulement si Windows la refuse."""

    if os.name != "nt":
        pytest.skip("NTFS junctions exist only on Windows; the symlink test covers POSIX")
    import _winapi

    try:
        _winapi.CreateJunction(str(target), str(link))
    except OSError as exc:  # pragma: no cover - depends on the host
        pytest.skip(f"junction creation refused by the host: {exc}")


def symlink(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation impossible here (Windows needs Developer Mode or the privilege): {exc}")


@pytest.fixture
def outside(tmp_path) -> Path:
    """Dossier hors de la mémoire, avec un secret qu'aucune opération ne doit lire ni toucher."""

    folder = tmp_path / "outside"
    folder.mkdir()
    (folder / "secret.txt").write_text("needle secret", encoding="utf-8")
    return folder


# ------------------------------------------------------------------ racine


def test_the_root_is_derived_from_the_board_id_and_created_lazily(store, data_root):
    assert store.memory_root_locator(BOARD) == f"boards/{BOARD}/memory"
    assert not (data_root / "boards").exists()  # rien sans opération
    tree = store.tree(BOARD)
    assert (tree.path, tree.entries, tree.truncated) == ("", (), False)
    assert memory(data_root).is_dir()
    assert store.tree("default").entries == ()  # le Board par défaut aussi
    assert memory(data_root, "default").is_dir()


def test_exists_never_creates_the_root(store, data_root):
    # Slice 04 : l'inspection demande d'abord si la racine existe, sans la créer.
    assert store.exists(BOARD) is False
    assert not (data_root / "boards").exists()
    store.tree(BOARD)
    assert store.exists(BOARD) is True


def test_exists_refuses_a_root_that_is_a_junction(store, data_root, outside):
    (data_root / "boards" / BOARD).mkdir(parents=True)
    junction(memory(data_root), outside)
    with pytest.raises(BoardMemoryUnavailable) as caught:
        store.exists(BOARD)
    assert caught.value.code == MEMORY_STORE_UNSAFE


@pytest.mark.parametrize("board_id", ["../x", "board_A", "Board_1", "board_", "", None, "board_a/b"])
def test_an_invalid_board_id_is_refused_before_any_disk_access(store, data_root, board_id):
    with pytest.raises(BoardError) as caught:
        store.tree(board_id)
    assert caught.value.code is BoardErrorCode.INVALID_BOARD
    assert not (data_root / "boards").exists()


@pytest.mark.parametrize(("raw", "code"), [
    ("../escape.md", C.MEMORY_PATH_ESCAPE), ("a/../../b", C.MEMORY_PATH_ESCAPE), ("/etc/passwd", C.MEMORY_PATH_ESCAPE),
    ("C:/Windows/win.ini", C.MEMORY_PATH_ESCAPE), ("\\\\host\\share", C.MEMORY_PATH_ESCAPE),
    ("CON", C.MEMORY_PATH_INVALID), ("notes/nul.txt", C.MEMORY_PATH_INVALID), ("a\\b", C.MEMORY_PATH_INVALID),
    ("ab:stream", C.MEMORY_PATH_INVALID), ("x" * 241, C.MEMORY_PATH_INVALID),
])
def test_traversal_absolute_and_reserved_paths_never_reach_the_store(raw, code):
    # Le seul chemin qu'accepte le magasin est un `BoardMemoryPath` : le refus précède tout accès disque.
    refused(code, BoardMemoryPath.parse, raw)


def test_a_root_that_is_a_junction_is_refused_unsafe(store, data_root, outside):
    (data_root / "boards" / BOARD).mkdir(parents=True)
    junction(memory(data_root), outside)
    with pytest.raises(BoardMemoryUnavailable) as caught:
        store.read(BOARD, P("secret.txt"))
    assert caught.value.code == MEMORY_STORE_UNSAFE
    with pytest.raises(BoardMemoryUnavailable):
        store.write(BOARD, P("planted.md"), "x", mode=WriteMode.CREATE)
    assert sorted(os.listdir(outside)) == ["secret.txt"]


# ------------------------------------------------------------------ évasion par lien sous la racine


def test_a_real_junction_inside_memory_is_never_followed(store, data_root, outside):
    store.mkdir(BOARD, P("notes"))
    junction(memory(data_root) / "notes" / "door", outside)

    refused(C.MEMORY_PATH_ESCAPE, store.read, BOARD, P("notes/door/secret.txt"))
    refused(C.MEMORY_PATH_ESCAPE, store.stat, BOARD, P("notes/door"))
    refused(C.MEMORY_PATH_ESCAPE, store.write, BOARD, P("notes/door/planted.md"), "x", mode=WriteMode.CREATE)
    refused(C.MEMORY_PATH_ESCAPE, store.mkdir, BOARD, P("notes/door/sub"))
    refused(C.MEMORY_PATH_ESCAPE, store.move, BOARD, P("notes/door"), P("moved"))
    refused(C.MEMORY_PATH_ESCAPE, store.tree, BOARD, P("notes/door"))
    refused(C.MEMORY_PATH_ESCAPE, store.search, BOARD, "needle", path=P("notes/door"))

    listed = {e.path: e for e in store.tree(BOARD, depth=MAX_TREE_DEPTH).entries}
    assert listed["notes/door"].kind is MemoryEntryKind.LINK
    assert not any(path.startswith("notes/door/") for path in listed)  # jamais parcourue
    assert store.search(BOARD, "needle").matches == ()

    assert store.delete(BOARD, P("notes"), recursive=True) == 2  # la jonction elle-même, puis `notes`
    assert not (memory(data_root) / "notes").exists()
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "needle secret"
    assert sorted(os.listdir(outside)) == ["secret.txt"]


def test_a_real_symlink_inside_memory_is_never_followed(store, data_root, outside):
    store.tree(BOARD)
    symlink(memory(data_root) / "secret.md", outside / "secret.txt")
    refused(C.MEMORY_PATH_ESCAPE, store.read, BOARD, P("secret.md"))
    refused(C.MEMORY_PATH_ESCAPE, store.write, BOARD, P("secret.md"), "overwritten", mode=WriteMode.REPLACE)
    refused(C.MEMORY_PATH_ESCAPE, store.write, BOARD, P("secret.md"), "more", mode=WriteMode.APPEND)
    assert store.search(BOARD, "needle").matches == ()
    assert store.delete(BOARD, P("secret.md")) == 1  # retire le lien, pas la cible
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "needle secret"


def test_a_file_where_a_folder_is_expected_is_a_conflict(store):
    store.write(BOARD, P("plan.md"), "x", mode=WriteMode.CREATE)
    refused(C.MEMORY_CONFLICT, store.read, BOARD, P("plan.md/child.md"))
    refused(C.MEMORY_CONFLICT, store.write, BOARD, P("plan.md/child.md"), "x", mode=WriteMode.CREATE)
    refused(C.MEMORY_CONFLICT, store.tree, BOARD, P("plan.md"))
    store.mkdir(BOARD, P("dir"))
    refused(C.MEMORY_CONFLICT, store.read, BOARD, P("dir"))
    refused(C.MEMORY_CONFLICT, store.write, BOARD, P("dir"), "x", mode=WriteMode.REPLACE)
    refused(C.MEMORY_CONFLICT, store.mkdir, BOARD, P("plan.md"))


@pytest.mark.skipif(os.name != "nt", reason="MAX_PATH is a Windows limit")
def test_a_file_path_above_max_path_is_refused_before_writing(tmp_path):
    deep = tmp_path / ("d" * max(1, 200 - len(str(tmp_path))))
    deep.mkdir()
    store = FileBoardMemoryStore(deep)
    store.tree(BOARD)
    refused(C.MEMORY_PATH_INVALID, store.write, BOARD, P("n" * 60 + ".md"), "x", mode=WriteMode.CREATE)
    assert store.tree(BOARD).entries == ()


# ------------------------------------------------------------------ écriture


def test_create_replace_append_read_and_restart(store, data_root):
    created = store.write(BOARD, P("decisions/2026/summary.md"), "Décision : oui\n", mode=WriteMode.CREATE)
    assert created.created and created.entry.kind is MemoryEntryKind.FILE
    assert created.sha256 == hashlib.sha256("Décision : oui\n".encode()).hexdigest()
    refused(C.MEMORY_EXISTS, store.write, BOARD, P("decisions/2026/summary.md"), "y", mode=WriteMode.CREATE)

    store.write(BOARD, P("decisions/2026/summary.md"), "ligne 2\n", mode=WriteMode.APPEND)
    again = FileBoardMemoryStore(data_root)  # redémarrage : tout est sur disque
    text = again.read(BOARD, P("decisions/2026/summary.md"))
    assert text.text == "Décision : oui\nligne 2\n" and text.eof and text.size == len(text.text.encode())

    refused(C.MEMORY_CONFLICT, again.write, BOARD, P("decisions/2026/summary.md"), "z", mode=WriteMode.REPLACE,
            expected_sha256="0" * 64)
    replaced = again.write(BOARD, P("decisions/2026/summary.md"), "neuf", mode=WriteMode.REPLACE,
                           expected_sha256=text.sha256)
    assert not replaced.created
    assert again.read(BOARD, P("decisions/2026/summary.md")).text == "neuf"
    refused(C.MEMORY_CONFLICT, again.write, BOARD, P("absent.md"), "z", mode=WriteMode.REPLACE,
            expected_sha256="0" * 64)
    assert again.write(BOARD, P("upsert.md"), "a", mode=WriteMode.REPLACE).created
    assert again.write(BOARD, P("log.md"), "a", mode=WriteMode.APPEND).created


def test_size_limits_on_write_read_and_append(store, data_root):
    refused(C.MEMORY_TOO_LARGE, store.write, BOARD, P("big.md"), "x" * (MAX_MEMORY_IO_BYTES + 1),
            mode=WriteMode.CREATE)
    assert store.write(BOARD, P("max.md"), "é" * (MAX_MEMORY_IO_BYTES // 2), mode=WriteMode.CREATE).entry.size == \
        MAX_MEMORY_IO_BYTES
    refused(C.MEMORY_TOO_LARGE, store.read, BOARD, P("max.md"), max_bytes=MAX_MEMORY_IO_BYTES + 1)
    (memory(data_root) / "huge.md").write_bytes(b"a" * MAX_APPEND_FILE_BYTES)
    refused(C.MEMORY_TOO_LARGE, store.write, BOARD, P("huge.md"), "b", mode=WriteMode.APPEND)
    assert (memory(data_root) / "huge.md").stat().st_size == MAX_APPEND_FILE_BYTES


def test_paged_read_never_splits_a_utf8_character(store):
    store.write(BOARD, P("u.md"), "aé€😀z", mode=WriteMode.CREATE)  # 1 + 2 + 3 + 4 + 1 octets
    pages, offset = [], 0
    while True:
        page = store.read(BOARD, P("u.md"), offset=offset, max_bytes=4)
        pages.append(page.text)
        offset = page.next_offset
        if page.eof:
            break
    assert "".join(pages) == "aé€😀z"
    assert all(pages)
    refused(C.MEMORY_NOT_TEXT, store.read, BOARD, P("u.md"), offset=2)  # au milieu de « é »


def test_binary_and_non_utf8_files_are_listed_but_never_read(store, data_root):
    store.tree(BOARD)
    (memory(data_root) / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00needle")
    (memory(data_root) / "latin1.txt").write_bytes("needle café".encode("latin-1"))
    refused(C.MEMORY_NOT_TEXT, store.read, BOARD, P("image.png"))
    refused(C.MEMORY_NOT_TEXT, store.read, BOARD, P("latin1.txt"))
    refused(C.MEMORY_NOT_TEXT, store.write, BOARD, P("image.png"), "more", mode=WriteMode.APPEND)
    sizes = {e.path: e.size for e in store.tree(BOARD).entries}
    assert sizes == {"image.png": 16, "latin1.txt": 11}
    found = store.search(BOARD, "needle")
    assert (found.matches, found.files_scanned, found.files_skipped) == ((), 0, 2)


def test_atomic_replace_leaves_no_temporary_and_keeps_the_old_file_on_failure(store, data_root, monkeypatch):
    for n in range(5):
        store.write(BOARD, P("notes/a.md"), f"version {n}", mode=WriteMode.REPLACE)
        store.write(BOARD, P("notes/log.md"), f"{n}\n", mode=WriteMode.APPEND)
    folder = memory(data_root) / "notes"
    assert sorted(os.listdir(folder)) == ["a.md", "log.md"]

    def broken(source, target):  # noqa: ANN001, ANN202
        raise PermissionError(13, "locked by another process")

    monkeypatch.setattr(board_memory_store, "replace_with_retry", broken)
    with pytest.raises(BoardMemoryUnavailable) as caught:
        store.write(BOARD, P("notes/a.md"), "half written", mode=WriteMode.REPLACE)
    assert caught.value.code == MEMORY_STORE_FAILED and "locked" in str(caught.value)
    assert store.read(BOARD, P("notes/a.md")).text == "version 4"
    assert sorted(os.listdir(folder)) == ["a.md", "log.md"]


def test_a_temporary_left_by_a_crash_is_never_listed_nor_searched(store, data_root):
    store.write(BOARD, P("a.md"), "needle", mode=WriteMode.CREATE)
    (memory(data_root) / f"{TEMP_PREFIX}deadbeef.tmp").write_text("needle partial", encoding="utf-8")
    tree = store.tree(BOARD)
    assert [e.path for e in tree.entries] == ["a.md"] and tree.skipped == 1
    assert [m.path for m in store.search(BOARD, "needle").matches] == ["a.md"]


# ------------------------------------------------------------------ arbre et recherche


def test_tree_is_sorted_depth_bounded_and_entry_bounded(store):
    for path in ("b.md", "A.md", "dir/z.md", "dir/sub/deep.md", "dir/sub/deeper/x.md", "c/one.md"):
        store.write(BOARD, P(path), "x", mode=WriteMode.CREATE)
    shallow = store.tree(BOARD, depth=1)
    assert [e.path for e in shallow.entries] == ["A.md", "b.md", "c", "dir"]
    two = store.tree(BOARD, depth=2)
    assert [(e.path, e.depth) for e in two.entries] == [
        ("A.md", 1), ("b.md", 1), ("c", 1), ("c/one.md", 2), ("dir", 1), ("dir/sub", 2), ("dir/z.md", 2)]
    assert {e.kind for e in two.entries if e.path in ("c", "dir")} == {MemoryEntryKind.DIRECTORY}
    assert all(e.size is None for e in two.entries if e.kind is MemoryEntryKind.DIRECTORY)
    bounded = store.tree(BOARD, depth=MAX_TREE_DEPTH, max_entries=3)
    assert len(bounded.entries) == 3 and bounded.truncated
    sub = store.tree(BOARD, P("dir/sub"), depth=1)
    assert [e.path for e in sub.entries] == ["dir/sub/deep.md", "dir/sub/deeper"]
    refused(C.MEMORY_NOT_FOUND, store.tree, BOARD, P("missing"))
    with pytest.raises(ValueError):
        store.tree(BOARD, depth=MAX_TREE_DEPTH + 1)
    with pytest.raises(ValueError):
        store.tree(BOARD, max_entries=0)


def test_search_is_literal_case_insensitive_and_bounded(store):
    store.write(BOARD, P("a.md"), "Alpha NEEDLE\nrien\nneedle (x)\n", mode=WriteMode.CREATE)
    store.write(BOARD, P("sub/b.md"), "needle.*\n", mode=WriteMode.CREATE)
    found = store.search(BOARD, "needle")
    assert [(m.path, m.line) for m in found.matches] == [("a.md", 1), ("a.md", 3), ("sub/b.md", 1)]
    assert found.files_scanned == 2 and not found.truncated
    assert [m.path for m in store.search(BOARD, ".*").matches] == ["sub/b.md"]  # littéral, pas une regex
    limited = store.search(BOARD, "needle", limit=2)
    assert len(limited.matches) == 2 and limited.truncated
    assert [m.path for m in store.search(BOARD, "needle", path=P("sub")).matches] == ["sub/b.md"]
    for bad in ("", "  ", "a\nb", "x" * 201):
        with pytest.raises(ValueError):
            store.search(BOARD, bad)


# ------------------------------------------------------------------ mkdir, move, delete


def test_mkdir_move_and_delete(store, data_root):
    entry, created = store.mkdir(BOARD, P("projets/alpha"))
    assert created and entry.kind is MemoryEntryKind.DIRECTORY
    assert store.mkdir(BOARD, P("projets/alpha"))[1] is False
    store.write(BOARD, P("projets/alpha/plan.md"), "plan", mode=WriteMode.CREATE)
    store.write(BOARD, P("autre.md"), "autre", mode=WriteMode.CREATE)

    refused(C.MEMORY_EXISTS, store.move, BOARD, P("autre.md"), P("projets/alpha/plan.md"))
    refused(C.MEMORY_CONFLICT, store.move, BOARD, P("projets"), P("projets/alpha/inside"))
    refused(C.MEMORY_NOT_FOUND, store.move, BOARD, P("absent.md"), P("x.md"))
    moved = store.move(BOARD, P("projets/alpha"), P("archive/2026/alpha"))
    assert moved.path == "archive/2026/alpha" and moved.kind is MemoryEntryKind.DIRECTORY
    assert store.read(BOARD, P("archive/2026/alpha/plan.md")).text == "plan"
    renamed = store.move(BOARD, P("autre.md"), P("Autre.md"))  # casse seule
    assert renamed.path == "Autre.md"

    refused(C.MEMORY_CONFLICT, store.delete, BOARD, P("archive"))  # non vide, pas récursif
    assert store.delete(BOARD, P("archive"), recursive=True) == 4  # plan.md, alpha, 2026, archive
    assert store.delete(BOARD, P("Autre.md")) == 1
    assert store.delete(BOARD, P("projets")) == 1  # vidé par le déplacement
    store.mkdir(BOARD, P("vide"))
    assert store.delete(BOARD, P("vide")) == 1
    refused(C.MEMORY_NOT_FOUND, store.delete, BOARD, P("vide"))
    assert store.tree(BOARD, depth=MAX_TREE_DEPTH).entries == ()
    assert memory(data_root).is_dir()  # la racine n'est jamais retirée


def test_names_differing_only_by_case_are_one_entry_on_every_system(store, data_root):
    """NTFS ignore la casse ; le magasin l'ignore partout, et rend les noms tels que stockés."""

    store.write(BOARD, P("summary.md"), "v1", mode=WriteMode.CREATE)
    store.mkdir(BOARD, P("Notes"))
    store.write(BOARD, P("Notes/plan.md"), "plan", mode=WriteMode.CREATE)

    refused(C.MEMORY_EXISTS, store.write, BOARD, P("Summary.md"), "v2", mode=WriteMode.CREATE)
    refused(C.MEMORY_EXISTS, store.move, BOARD, P("Notes/plan.md"), P("SUMMARY.MD"))
    assert store.mkdir(BOARD, P("notes"))[0].path == "Notes"  # déjà là : pas un doublon
    refused(C.MEMORY_CONFLICT, store.mkdir, BOARD, P("SUMMARY.md"))  # un fichier occupe ce nom

    # Lecture, état et remplacement passent par le nom stocké, jamais par l'orthographe reçue.
    assert store.stat(BOARD, P("SUMMARY.md")).path == "summary.md"
    assert store.read(BOARD, P("Summary.MD")).path == "summary.md"
    replaced = store.write(BOARD, P("Summary.md"), "v2", mode=WriteMode.REPLACE)
    assert replaced.entry.path == "summary.md" and not replaced.created
    assert store.write(BOARD, P("NOTES/autre.md"), "x", mode=WriteMode.CREATE).entry.path == "Notes/autre.md"
    assert store.tree(BOARD, P("notes")).path == "Notes"
    assert [e.path for e in store.tree(BOARD, depth=2).entries] == ["Notes", "Notes/autre.md", "Notes/plan.md",
                                                                    "summary.md"]
    assert sorted(p.name for p in memory(data_root).iterdir()) == ["Notes", "summary.md"]

    # Renommer la même entrée en changeant la casse seule : permis, nom neuf stocké.
    assert store.move(BOARD, P("notes/PLAN.md"), P("notes/Plan.md")).path == "Notes/Plan.md"
    assert sorted(p.name for p in (memory(data_root) / "Notes").iterdir()) == ["Plan.md", "autre.md"]
    assert store.move(BOARD, P("NOTES/plan.md"), P("Notes/Plan.md")).path == "Notes/Plan.md"  # rien à faire
    refused(C.MEMORY_CONFLICT, store.move, BOARD, P("notes"), P("NOTES/sub"))  # dans lui-même
    assert store.delete(BOARD, P("SUMMARY.MD")) == 1
    assert not (memory(data_root) / "summary.md").exists()


def test_name_comparison_follows_ntfs_simple_uppercase_not_casefold():
    key = board_memory_store._name_key
    assert key("Résumé.md") == key("RÉSUMÉ.MD")
    assert key("straße") != key("STRASSE")  # deux fichiers pour NTFS


# ------------------------------------------------------------------ course : dossier remplacé entre vérification et acte
# Un processus local hostile remplace un dossier par une jonction vers `outside`
# au pire moment : le crochet (monkeypatch) se place exactement entre la
# vérification et l'acte. Vraies jonctions NTFS, donc Windows seulement.

windows_only = pytest.mark.skipif(os.name != "nt", reason="the swap uses a real NTFS junction")


def swap_for_junction(folder: Path, outside: Path) -> Path:
    """Remplace `folder` par une jonction vers `outside` ; rend où le vrai dossier a été mis."""

    away = folder.with_name(folder.name + "-away")
    os.rename(folder, away)
    junction(folder, outside)
    return away


@windows_only
def test_write_publishes_nothing_when_the_parent_becomes_a_junction_before_the_replace(store, data_root, outside,
                                                                                       monkeypatch):
    store.write(BOARD, P("notes/a.md"), "v1", mode=WriteMode.CREATE)
    original = board_memory_store._open_temporary

    def hostile(parent, data, relative):  # noqa: ANN001, ANN202
        swap_for_junction(memory(data_root) / "notes", outside)
        return original(parent, data, relative)  # le temporaire atterrit dans `outside`

    monkeypatch.setattr(board_memory_store, "_open_temporary", hostile)
    with pytest.raises(BoardMemoryUnavailable) as caught:
        store.write(BOARD, P("notes/a.md"), "planted", mode=WriteMode.REPLACE)
    assert caught.value.code == MEMORY_STORE_UNSAFE and "stopped before acting" in str(caught.value)
    assert sorted(os.listdir(outside)) == ["secret.txt"]  # ni fichier publié, ni temporaire laissé
    assert (memory(data_root) / "notes-away" / "a.md").read_text(encoding="utf-8") == "v1"


@windows_only
def test_write_reports_unsafe_when_the_parent_is_swapped_during_the_replace(store, data_root, outside, monkeypatch):
    store.write(BOARD, P("notes/a.md"), "v1", mode=WriteMode.CREATE)
    real_replace = board_memory_store.replace_with_retry

    def hostile(source, target):  # noqa: ANN001, ANN202
        away = swap_for_junction(memory(data_root) / "notes", outside)
        real_replace(away / source.name, target)  # le remplacement suit la jonction : atterrit dehors

    monkeypatch.setattr(board_memory_store, "replace_with_retry", hostile)
    with pytest.raises(BoardMemoryUnavailable) as caught:
        store.write(BOARD, P("notes/a.md"), "landed", mode=WriteMode.REPLACE)
    assert caught.value.code == MEMORY_STORE_UNSAFE and "not undone" in str(caught.value)
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "needle secret"


@windows_only
def test_move_does_nothing_when_the_target_parent_becomes_a_junction(store, data_root, outside, monkeypatch):
    store.write(BOARD, P("a.md"), "moi", mode=WriteMode.CREATE)
    store.mkdir(BOARD, P("dest"))
    original = FileBoardMemoryStore._ensure_folders

    def hostile(self, root, parts, relative):  # noqa: ANN001, ANN202
        found = original(self, root, parts, relative)
        swap_for_junction(memory(data_root) / "dest", outside)
        return found

    monkeypatch.setattr(FileBoardMemoryStore, "_ensure_folders", hostile)
    with pytest.raises(BoardMemoryUnavailable) as caught:
        store.move(BOARD, P("a.md"), P("dest/a.md"))
    assert caught.value.code == MEMORY_STORE_UNSAFE
    assert sorted(os.listdir(outside)) == ["secret.txt"]
    assert (memory(data_root) / "a.md").read_text(encoding="utf-8") == "moi"


@windows_only
def test_recursive_delete_never_removes_through_a_folder_swapped_after_counting(store, data_root, outside,
                                                                               monkeypatch):
    store.write(BOARD, P("notes/sub/secret.txt"), "mine", mode=WriteMode.CREATE)
    original = board_memory_store._collect

    def hostile(*args):  # noqa: ANN002, ANN202
        doomed = original(*args)
        swap_for_junction(memory(data_root) / "notes" / "sub", outside)  # même nom de fichier dehors
        return doomed

    monkeypatch.setattr(board_memory_store, "_collect", hostile)
    with pytest.raises(BoardMemoryUnavailable) as caught:
        store.delete(BOARD, P("notes"), recursive=True)
    assert caught.value.code == MEMORY_STORE_UNSAFE
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "needle secret"


@windows_only
def test_mkdir_reports_unsafe_when_a_parent_becomes_a_junction_between_two_levels(store, data_root, outside,
                                                                                 monkeypatch):
    store.mkdir(BOARD, P("a"))
    real_mkdir = os.mkdir

    def hostile(path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        if Path(path).name == "b":
            swap_for_junction(memory(data_root) / "a", outside)
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(os, "mkdir", hostile)
    with pytest.raises(BoardMemoryUnavailable) as caught:
        store.mkdir(BOARD, P("a/b/c"))
    assert caught.value.code == MEMORY_STORE_UNSAFE
    assert not (outside / "b" / "c").exists()  # rien créé plus bas que le dossier vu trop tard


def test_mkdir_maps_a_disk_failure_after_creation(store, monkeypatch):
    original = FileBoardMemoryStore._ensure_folders

    def vanishing(self, root, parts, relative):  # noqa: ANN001, ANN202
        folder, rel, chain = original(self, root, parts, relative)
        os.rmdir(folder)  # retiré par un tiers avant l'inspection finale
        return folder, rel, chain

    monkeypatch.setattr(FileBoardMemoryStore, "_ensure_folders", vanishing)
    refused(C.MEMORY_NOT_FOUND, store.mkdir, BOARD, P("gone"))


# ------------------------------------------------------------------ mutations survivantes (QA S2)


def test_read_refuses_a_file_swapped_between_inspection_and_opening(store, data_root, monkeypatch):
    store.write(BOARD, P("a.md"), "inspected", mode=WriteMode.CREATE)
    original = FileBoardMemoryStore._existing

    def swapping(self, root, path):  # noqa: ANN001, ANN202
        found = original(self, root, path)
        other = memory(data_root) / "other.md"
        other.write_text("substituted", encoding="utf-8")
        os.replace(other, found[0])  # autre fichier, autre identité, même nom
        return found

    monkeypatch.setattr(FileBoardMemoryStore, "_existing", swapping)
    refused(C.MEMORY_PATH_ESCAPE, store.read, BOARD, P("a.md"))


def test_create_never_overwrites_a_file_that_appears_before_publication(store, data_root, monkeypatch):
    store.mkdir(BOARD, P("notes"))
    original = board_memory_store._open_temporary

    def racing(parent, data, relative):  # noqa: ANN001, ANN202
        (parent / "new.md").write_text("original", encoding="utf-8")  # un autre écrivain, après la vérification
        return original(parent, data, relative)

    monkeypatch.setattr(board_memory_store, "_open_temporary", racing)
    refused(C.MEMORY_EXISTS, store.write, BOARD, P("notes/new.md"), "mine", mode=WriteMode.CREATE)
    assert (memory(data_root) / "notes" / "new.md").read_text(encoding="utf-8") == "original"
    assert os.listdir(memory(data_root) / "notes") == ["new.md"]  # temporaire retiré


def test_recursive_delete_above_the_entry_bound_removes_nothing(store, data_root, monkeypatch):
    for n in range(5):
        store.write(BOARD, P(f"big/{n}.md"), "x", mode=WriteMode.CREATE)
    monkeypatch.setattr(board_memory_store, "MAX_DELETE_ENTRIES", 3)
    refused(C.MEMORY_TOO_LARGE, store.delete, BOARD, P("big"), recursive=True)
    assert len(os.listdir(memory(data_root) / "big")) == 5
    monkeypatch.setattr(board_memory_store, "MAX_DELETE_ENTRIES", 6)  # 5 fichiers + le dossier
    assert store.delete(BOARD, P("big"), recursive=True) == 6


# ------------------------------------------------------------------ temporaires et condensé


def test_a_taken_temporary_name_is_never_removed_and_another_is_drawn(store, data_root, monkeypatch):
    store.mkdir(BOARD, P("notes"))
    taken = memory(data_root) / "notes" / f"{TEMP_PREFIX}aaaaaaaa.tmp"
    taken.write_text("another writer", encoding="utf-8")
    names = iter(["a" * 32, "b" * 32])
    monkeypatch.setattr(board_memory_store, "uuid", SimpleNamespace(uuid4=lambda: SimpleNamespace(hex=next(names))))
    store.write(BOARD, P("notes/a.md"), "mine", mode=WriteMode.CREATE)
    assert taken.read_text(encoding="utf-8") == "another writer"
    assert store.read(BOARD, P("notes/a.md")).text == "mine"


def test_temporary_names_are_refused_to_clients_whatever_the_case():
    for raw in (f"{TEMP_PREFIX}deadbeef.tmp", f"notes/{TEMP_PREFIX.upper()}x.TMP"):
        refused(C.MEMORY_PATH_INVALID, BoardMemoryPath.parse, raw)


def test_read_gives_the_whole_file_sha256_up_to_one_mebibyte_only(store, data_root):
    store.tree(BOARD)
    small = b"a" * board_memory_store.MAX_READ_HASH_BYTES
    (memory(data_root) / "small.md").write_bytes(small)
    (memory(data_root) / "large.md").write_bytes(small + b"b")
    page = store.read(BOARD, P("small.md"), offset=1024, max_bytes=16)
    assert page.sha256 == hashlib.sha256(small).hexdigest() and page.size == len(small)
    large = store.read(BOARD, P("large.md"), offset=len(small), max_bytes=16)
    assert (large.sha256, large.text, large.size, large.eof) == (None, "b", len(small) + 1, True)


def test_a_temporary_substituted_before_publication_is_neither_published_nor_removed(store, data_root, monkeypatch):
    store.mkdir(BOARD, P("notes"))
    original = board_memory_store._open_temporary

    def substituting(parent, data, relative):  # noqa: ANN001, ANN202
        temporary, own = original(parent, data, relative)
        foreign = parent / "foreign.bin"
        foreign.write_text("not ours", encoding="utf-8")
        os.replace(foreign, temporary)  # même nom, autre fichier
        return temporary, own

    monkeypatch.setattr(board_memory_store, "_open_temporary", substituting)
    with pytest.raises(BoardMemoryUnavailable) as caught:
        store.write(BOARD, P("notes/a.md"), "mine", mode=WriteMode.CREATE)
    assert caught.value.code == MEMORY_STORE_UNSAFE
    (left,) = os.listdir(memory(data_root) / "notes")  # pas publié, et pas retiré : il n'est pas à nous
    assert left.startswith(TEMP_PREFIX)
    assert (memory(data_root) / "notes" / left).read_text(encoding="utf-8") == "not ours"


def test_a_file_above_the_hash_bound_is_never_read_whole(store, data_root, monkeypatch):
    store.tree(BOARD)
    (memory(data_root) / "large.md").write_bytes(b"a" * (board_memory_store.MAX_READ_HASH_BYTES + 1))

    def forbidden(head, handle):  # noqa: ANN001, ANN202
        raise AssertionError("a file above MAX_READ_HASH_BYTES must not be hashed")

    monkeypatch.setattr(board_memory_store, "_bounded_sha256", forbidden)
    assert store.read(BOARD, P("large.md"), max_bytes=16).sha256 is None

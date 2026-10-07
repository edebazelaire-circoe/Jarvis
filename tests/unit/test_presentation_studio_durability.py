"""Garantie de durabilite d'un commit acquitte (jarvis-interactive-presentation-studio, Slice 08).

Un commit est durable AVANT d'etre acquitte : temporaire `fsync`e, remplacement atomique, puis vidage du dossier (l'entree
de repertoire elle-meme). Aucun tampon, aucune minuterie : rien a vider a l'arret. Ici l'ordre des appels systeme est
pris en flagrant delit (fichier, remplacement, dossier), l'echec du vidage n'annule pas un commit deja remplace, et un
commit acquitte est lisible par un lecteur neuf sans autre appel.
Contrat : `docs/presentation-studio.md` > *Persistence and undo contract*.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.adapters import file_presentation_studio_store as module
from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.core.presentation_studio_autosave import PresentationStudioHistory
from jarvis.core.presentation_studio_edit import PresentationStudioEditService
from jarvis.core.presentation_studio_service import PresentationStudioService

PID = "pst_" + "a" * 32
VID = "psv_" + "b" * 32


def test_the_folder_flush_is_accepted_by_this_platform_and_never_raises_on_a_missing_folder(tmp_path):
    assert module._sync_folder(tmp_path) is True
    assert module._sync_folder(tmp_path / "missing") is False  # best effort: the replace already happened


def test_the_write_order_is_file_fsync_then_replace_then_folder_flush(tmp_path, monkeypatch):
    calls: list[str] = []
    real_fsync, real_replace, real_sync = module.os.fsync, module.replace_with_retry, module._sync_folder
    monkeypatch.setattr(module.os, "fsync", lambda fd: (calls.append("fsync"), real_fsync(fd))[1])
    monkeypatch.setattr(module, "replace_with_retry", lambda s, t: (calls.append("replace"), real_replace(s, t))[1])
    monkeypatch.setattr(module, "_sync_folder", lambda f: (calls.append("folder"), real_sync(f))[1])
    store = FilePresentationStudioStore(tmp_path)
    store.create(PID, "{}\n", {VID: "{}\n"})
    calls.clear()
    store.write_variant(PID, VID, '{"gen": 1}\n')
    assert calls == ["fsync", "replace", "folder"]
    assert store.read_variant(PID, VID) == '{"gen": 1}\n'


def test_a_failing_fsync_never_replaces_the_document_and_leaves_no_temporary(tmp_path, monkeypatch):
    store = FilePresentationStudioStore(tmp_path)
    store.create(PID, "{}\n", {VID: '{"gen": 0}\n'})

    def refuse(fd):
        raise OSError(5, "I/O error (injected)")

    monkeypatch.setattr(module.os, "fsync", refuse)
    with pytest.raises(Exception) as caught:
        store.write_variant(PID, VID, '{"gen": 1}\n')
    assert "storage_io" in str(caught.value)
    monkeypatch.undo()
    assert store.read_variant(PID, VID) == '{"gen": 0}\n'  # the old document, whole: nothing was acknowledged
    assert not list(Path(tmp_path).rglob("*.tmp"))


def test_a_folder_flush_the_platform_refuses_does_not_undo_a_replaced_document(tmp_path, monkeypatch):
    store = FilePresentationStudioStore(tmp_path)
    store.create(PID, "{}\n", {VID: '{"gen": 0}\n'})
    monkeypatch.setattr(module, "_flush_folder_nt" if module.os.name == "nt" else "_flush_folder_posix", lambda f: False)
    store.write_variant(PID, VID, '{"gen": 1}\n')  # best effort: no exception, the commit stands
    assert store.read_variant(PID, VID) == '{"gen": 1}\n'


async def test_an_acknowledged_commit_is_already_on_disk_for_a_fresh_reader_with_nothing_to_flush(tmp_path):
    studio = PresentationStudioService(FilePresentationStudioStore(tmp_path))
    history = PresentationStudioHistory(studio)
    edit = PresentationStudioEditService(studio, history=history)
    history.bind(edit)
    view = await studio.create({"title": "Atelier"})
    pid, vid = view.presentation.presentation_id, view.presentation.active_variant_id
    base = await studio.get_variant(pid, vid)
    scene = {"scene_id": "pss_000000000001", "prefab": {"id": "jarvis.window", "version": 1}, "title": "Un"}
    await studio.save_variant(pid, vid, {"expected_revision": base.revision, "title": base.title, "scenes": [scene],
                                         "art_direction_id": None, "score_id": None})
    result = await edit.edit(pid, vid, {"actor": "user", "mode": "commit", "basis": {"variant_revision": base.revision + 1},
                                        "ops": [{"op": "scene.rename", "scene_id": scene["scene_id"], "title": "Deux"}]})
    assert result.committed and result.revision == base.revision + 2
    # no flush, no close, no shutdown hook: a brand new store object reads the acknowledged state straight away
    fresh = PresentationStudioService(FilePresentationStudioStore(tmp_path))
    stored = await fresh.get_variant(pid, vid)
    assert (stored.revision, stored.scenes[0].title) == (result.revision, "Deux")
    # and the undo is the same kind of commit: durable at its acknowledgement, a new revision
    undone = await history.undo(pid, vid, {"actor": "user"})
    stored = await fresh.get_variant(pid, vid)
    assert undone.status.value == "applied" and (stored.revision, stored.scenes[0].title) == (undone.revision, "Un")
    for owner in (studio, history, edit):  # the contract has no buffer to drain: nothing to call at shutdown
        assert not any(name in dir(owner) for name in ("flush", "debounce", "schedule_autosave"))

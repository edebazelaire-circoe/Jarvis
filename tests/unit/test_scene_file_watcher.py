"""Fenêtre de scène liée à un fichier : le résumé suit le fichier sans tour du cerveau."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from jarvis.adapters.sqlite_scene import SQLiteSceneRepository
from jarvis.adapters.file_change_notifier import FileChangeNotifier
from jarvis.core.scene_file_watcher import (
    SCENE_FILE_REFRESHED_KIND,
    SCENE_FILE_WATCH_UNAVAILABLE_KIND,
    SceneFileWatcher,
    render_file_summary,
)
from jarvis.core.scene_service import SceneService
from jarvis.domain.scene import (
    MAX_PAYLOAD_SUMMARY_CHARS,
    SceneActor,
    SceneCommand,
    SceneObjectFields,
    SceneObjectKind,
    SceneOp,
    ScenePayload,
    SceneSnapshot,
)


class Diag:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None):
        self.events.append((kind, data or {}))


async def _window(scene: SceneService, path: str, summary: str = "copie figée") -> str:
    update = await scene.apply(SceneCommand(
        op=SceneOp.UPSERT_OBJECT, actor=SceneActor.BRAIN, object_id="brain-window-1",
        fields=SceneObjectFields(kind=SceneObjectKind.WINDOW, category="note",
                                 payload=ScenePayload(title="Fichier", summary=summary, source_path=path)),
    ))
    assert update.patch is not None
    return "brain-window-1"


async def _summary(scene: SceneService, object_id: str) -> str:
    return (await scene.snapshot()).get_object(object_id).payload.summary


def _write(path: Path, text: str, bump: int) -> None:
    path.write_text(text, encoding="utf-8")
    # mtime strictement croissant : un système de fichiers à gros grain ne doit pas masquer l'écriture.
    stamp = 1_800_000_000 + bump
    os.utime(path, (stamp, stamp))


@pytest.fixture
async def scene(tmp_path):
    service = SceneService(SQLiteSceneRepository(tmp_path / "scene.sqlite3"))
    await service.start()
    yield service
    await service.close()


def test_source_path_round_trips_and_stays_off_the_wire_when_empty() -> None:
    assert "source_path" not in ScenePayload(title="a").to_payload()
    payload = ScenePayload(title="a", source_path="C:/x/y.md")
    assert ScenePayload.from_payload(payload.to_payload()) == payload


def test_render_truncates_and_says_so_and_refuses_binary() -> None:
    long = "x" * 5000
    shown = render_file_summary(long.encode())
    assert len(shown) <= MAX_PAYLOAD_SUMMARY_CHARS and shown.endswith("non affichée)")
    assert "binaire" in render_file_summary(b"MZ\x00\x01")
    assert render_file_summary(b"a\r\nb\x07c") == "a\nb c"
    ScenePayload(summary=shown)


async def _until(predicate, timeout: float = 3.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if await predicate():
            return True
        await asyncio.sleep(0.01)
    return await predicate()


async def _shows(scene, object_id: str, text: str, timeout: float = 3.0) -> bool:
    async def predicate() -> bool:
        return await _summary(scene, object_id) == text
    return await _until(predicate, timeout)


class FakeNotifier:
    """Notificateur sans système de fichiers : le test pousse lui-même les événements."""

    available = True

    def __init__(self, loop, callback) -> None:
        self.callback, self.watched, self.closed = callback, set(), False

    def watch(self, directory):
        self.watched.add(os.path.normcase(os.path.abspath(directory)))
        return True

    def keep_only(self, directories):
        self.watched &= {os.path.normcase(os.path.abspath(d)) for d in directories}

    def close(self):
        self.closed = True


async def test_an_event_rewrites_the_summary_and_nothing_polls(scene, tmp_path, monkeypatch) -> None:
    import jarvis.core.scene_file_watcher as module

    target = tmp_path / "note.md"
    _write(target, "# version 1", 1)
    diag = Diag()
    watcher = SceneFileWatcher(scene, diagnostics=diag, debounce_s=0.01, notifier_factory=FakeNotifier)
    object_id = await _window(scene, str(target))
    watcher.start()
    try:
        assert await _shows(scene, object_id, "# version 1")  # lien nouveau : lu aussitôt
        assert watcher._notifier.watched == {os.path.normcase(str(tmp_path))}

        calls = []
        real = module._signature
        monkeypatch.setattr(module, "_signature", lambda path: calls.append(path) or real(path))
        await asyncio.sleep(0.4)
        assert calls == []  # sans événement, le fichier n'est jamais relu

        _write(target, "# version 2", 2)
        watcher.notify_changed(str(target))
        assert await _shows(scene, object_id, "# version 2")
        assert [k for k, _ in diag.events].count(SCENE_FILE_REFRESHED_KIND) == 2

        revision = (await scene.snapshot()).revision
        watcher.notify_changed(str(target))  # événement sans changement de contenu : aucune révision de plus
        await asyncio.sleep(0.2)
        assert (await scene.snapshot()).revision == revision
        watcher.notify_changed(str(tmp_path / "autre.md"))  # fichier non lié : ignoré
    finally:
        await watcher.stop()
    assert watcher._notifier is None


async def test_a_burst_of_events_reads_once(scene, tmp_path, monkeypatch) -> None:
    import jarvis.core.scene_file_watcher as module

    target = tmp_path / "note.md"
    _write(target, "v1", 1)
    watcher = SceneFileWatcher(scene, debounce_s=0.05, notifier_factory=FakeNotifier)
    object_id = await _window(scene, str(target))
    watcher.start()
    try:
        assert await _shows(scene, object_id, "v1")
        calls = []
        real = module._signature
        monkeypatch.setattr(module, "_signature", lambda path: calls.append(path) or real(path))
        _write(target, "v2", 2)
        for _ in range(5):
            watcher.notify_changed(str(target))
            await asyncio.sleep(0.01)
        assert await _shows(scene, object_id, "v2")
        await asyncio.sleep(0.15)
        assert len(calls) == 1
    finally:
        await watcher.stop()


async def test_unlinking_releases_the_watch(scene, tmp_path) -> None:
    target = tmp_path / "note.md"
    _write(target, "v1", 1)
    watcher = SceneFileWatcher(scene, debounce_s=0.01, notifier_factory=FakeNotifier)
    object_id = await _window(scene, str(target))
    watcher.start()
    try:
        assert await _shows(scene, object_id, "v1")
        await scene.apply(SceneCommand(
            op=SceneOp.PATCH_OBJECT, actor=SceneActor.BRAIN, object_id=object_id,
            fields=SceneObjectFields(payload=ScenePayload(title="Fichier", summary="libre", source_path="")),
        ))

        async def released() -> bool:
            return not watcher._notifier.watched and not watcher._linked
        assert await _until(released)
        _write(target, "v2", 2)
        watcher.notify_changed(str(target))
        await asyncio.sleep(0.2)
        assert await _summary(scene, object_id) == "libre"
    finally:
        await watcher.stop()


async def test_a_replaced_file_blinks_nothing_and_a_removed_one_is_said(scene, tmp_path) -> None:
    target = tmp_path / "note.md"
    _write(target, "v1", 1)
    watcher = SceneFileWatcher(scene, debounce_s=0.01, missing_confirm_s=0.15, notifier_factory=FakeNotifier)
    object_id = await _window(scene, str(target))
    watcher.start()
    try:
        assert await _shows(scene, object_id, "v1")
        target.unlink()
        watcher.notify_changed(str(target))
        await asyncio.sleep(0.05)
        assert await _summary(scene, object_id) == "v1"  # une seule absence : on attend
        _write(target, "v2", 2)
        watcher.notify_changed(str(target))
        assert await _shows(scene, object_id, "v2")
        await asyncio.sleep(0.3)
        assert await _summary(scene, object_id) == "v2"

        target.unlink()
        watcher.notify_changed(str(target))

        async def said() -> bool:
            return "introuvable" in await _summary(scene, object_id)
        assert await _until(said)
    finally:
        await watcher.stop()


async def test_without_a_notifier_the_file_is_read_at_link_time_and_the_gap_is_said(scene, tmp_path) -> None:
    class Unavailable(FakeNotifier):
        def watch(self, directory):
            return False

    target = tmp_path / "note.md"
    _write(target, "v1", 1)
    diag = Diag()
    watcher = SceneFileWatcher(scene, diagnostics=diag, notifier_factory=Unavailable)
    object_id = await _window(scene, str(target))
    watcher.start()
    try:
        assert await _shows(scene, object_id, "v1")
        assert SCENE_FILE_WATCH_UNAVAILABLE_KIND in [k for k, _ in diag.events]
    finally:
        await watcher.stop()


@pytest.mark.skipif(not FileChangeNotifier.available, reason="notifications du système de fichiers : Windows")
async def test_the_operating_system_tells_us_and_the_window_follows(scene, tmp_path) -> None:
    """Preuve réelle : aucun `notify_changed`, c'est le noyau qui prévient, y compris pour un remplacement atomique."""

    target = tmp_path / "note.md"
    target.write_text("v1", encoding="utf-8")
    watcher = SceneFileWatcher(scene, notifier_factory=FileChangeNotifier)
    object_id = await _window(scene, str(target))
    watcher.start()
    try:
        assert await _shows(scene, object_id, "v1")
        target.write_text("v2 écrit sur place", encoding="utf-8")
        assert await _shows(scene, object_id, "v2 écrit sur place", 2.0)

        scratch = tmp_path / "note.md.tmp"
        scratch.write_text("v3 par remplacement", encoding="utf-8")
        os.replace(scratch, target)
        assert await _shows(scene, object_id, "v3 par remplacement", 2.0)

        later = tmp_path / "plus" / "tard" / "note2.md"  # dossier qui n'existe pas encore
        await scene.apply(SceneCommand(
            op=SceneOp.UPSERT_OBJECT, actor=SceneActor.BRAIN, object_id="brain-window-2",
            fields=SceneObjectFields(kind=SceneObjectKind.WINDOW, category="note",
                                     payload=ScenePayload(title="Plus tard", summary="x", source_path=str(later))),
        ))
        assert await _shows(scene, "brain-window-2", f"Fichier introuvable : {later}")
        later.parent.mkdir(parents=True)
        later.write_text("apparu", encoding="utf-8")
        assert await _shows(scene, "brain-window-2", "apparu", 2.0)
    finally:
        await watcher.stop()

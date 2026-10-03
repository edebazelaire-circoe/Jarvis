"""Fenêtre de scène liée à un fichier : le résumé suit le fichier sans tour du cerveau."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from jarvis.adapters.sqlite_scene import SQLiteSceneRepository
from jarvis.core.scene_file_watcher import (
    SCENE_FILE_REFRESHED_KIND,
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


async def test_a_modified_file_rewrites_the_window_summary(scene, tmp_path) -> None:
    target = tmp_path / "note.md"
    _write(target, "# version 1", 1)
    diag = Diag()
    watcher = SceneFileWatcher(scene, diagnostics=diag)
    object_id = await _window(scene, str(target))

    assert await watcher.poll_once() == 1
    assert await _summary(scene, object_id) == "# version 1"
    assert await watcher.poll_once() == 0  # rien n'a changé : aucune révision de plus
    revision = (await scene.snapshot()).revision

    _write(target, "# version 2\nnouvelle ligne", 2)
    assert await watcher.poll_once() == 1
    assert await _summary(scene, object_id) == "# version 2\nnouvelle ligne"
    assert (await scene.snapshot()).revision == revision + 1
    assert [k for k, _ in diag.events].count(SCENE_FILE_REFRESHED_KIND) == 2


async def test_a_replaced_file_blinks_nothing_and_a_removed_one_is_said(scene, tmp_path) -> None:
    target = tmp_path / "note.md"
    _write(target, "v1", 1)
    watcher = SceneFileWatcher(scene)
    object_id = await _window(scene, str(target))
    await watcher.poll_once()

    target.unlink()
    assert await watcher.poll_once() == 0  # une seule absence : on attend
    assert await _summary(scene, object_id) == "v1"
    _write(target, "v2", 2)
    assert await watcher.poll_once() == 1 and await _summary(scene, object_id) == "v2"

    target.unlink()
    await watcher.poll_once()
    await watcher.poll_once()
    assert "introuvable" in await _summary(scene, object_id)


async def test_the_background_loop_follows_the_file(scene, tmp_path) -> None:
    target = tmp_path / "note.md"
    _write(target, "v1", 1)
    watcher = SceneFileWatcher(scene, poll_s=0.02)
    object_id = await _window(scene, str(target))
    watcher.start()
    try:
        for _ in range(100):
            if await _summary(scene, object_id) == "v1":
                break
            await asyncio.sleep(0.02)
        assert await _summary(scene, object_id) == "v1"
        _write(target, "v2", 2)
        for _ in range(100):
            if await _summary(scene, object_id) == "v2":
                break
            await asyncio.sleep(0.02)
        assert await _summary(scene, object_id) == "v2"
    finally:
        await watcher.stop()

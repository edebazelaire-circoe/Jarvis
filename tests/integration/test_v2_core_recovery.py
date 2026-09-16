from __future__ import annotations

import pytest

from jarvis.core.scene_service import SCENE_UNAVAILABLE_KIND, SceneState
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.scene import (
    ExecState, RelationKind, SceneActor, SceneCommand, SceneCommandOutcome, SceneGeometry, SceneObjectFields,
    SceneObjectKind, SceneOp, ScenePayload, SceneRelation, Visibility, WorkRef,
)
from jarvis.domain.v2 import TurnKind
from jarvis.ports.scene import SceneStoreErrorCode, SceneUnavailableError


@pytest.mark.asyncio
async def test_core_headless_restart_preserves_conversation(tmp_path):
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    conversation = await core.conversations.create()
    await core.conversations.append_turn(conversation.id, TurnKind.USER, "Question", correlation_id="one")
    await core.stop()

    core2 = JarvisCoreApplication(data_root=tmp_path)
    await core2.start()
    context = await core2.conversations.rehydration_context(conversation.id)
    assert context["conversation_id"] == conversation.id
    assert context["recent_turns"][-1]["content"] == "Question"
    await core2.stop()


# --- scène constellation (handoff jarvis-constellation-scene-runtime, Slice 02) ---


class _Journal:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None):
        self.events.append((kind, level, data or {}))


def _scene_commands():
    def star(object_id):
        return SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=SceneActor.RUNTIME, object_id=object_id, fields=SceneObjectFields(
            kind=SceneObjectKind.AGENT, category="research", exec_state=ExecState.RUNNING,
            work_ref=WorkRef(source="claude", external_id=object_id)))

    return [
        star("star-a"),
        star("star-b"),
        SceneCommand(op=SceneOp.LINK, actor=SceneActor.RUNTIME, relation=SceneRelation("rel-ab", RelationKind.PARENT_OF, "star-a", "star-b")),
        SceneCommand(op=SceneOp.SET_GEOMETRY, actor=SceneActor.USER, object_id="star-a", geometry=SceneGeometry(120, 80, 48, 48)),
        SceneCommand(op=SceneOp.PIN, actor=SceneActor.USER, object_id="star-a"),
        SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=SceneActor.BRAIN, object_id="art-1", fields=SceneObjectFields(
            kind=SceneObjectKind.ARTIFACT, category="research", payload=ScenePayload(title="Synthèse"))),
        SceneCommand(op=SceneOp.ARCHIVE, actor=SceneActor.USER, object_id="star-b"),
    ]


@pytest.mark.asyncio
async def test_core_restart_restores_the_identical_scene_twice(tmp_path):
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    for command in _scene_commands():
        assert (await core.scene.apply(command)).outcome is SceneCommandOutcome.APPLIED
    first = await core.scene.snapshot()
    await core.stop()
    assert (tmp_path / "state" / "scene.sqlite3").is_file()

    core2 = JarvisCoreApplication(data_root=tmp_path)
    await core2.start()
    restored = await core2.scene.snapshot()
    assert restored == first
    assert restored.revision == 7 and restored.archived_ids == ("star-b",)
    assert [entry.object.object_id for entry in await core2.scene.archived_history()] == ["star-b"]
    update = await core2.scene.apply(SceneCommand(op=SceneOp.SET_VISIBILITY, actor=SceneActor.BRAIN, object_id="art-1", visibility=Visibility.HIDDEN))
    assert update.snapshot.revision == 8
    second = await core2.scene.snapshot()
    await core2.stop()

    core3 = JarvisCoreApplication(data_root=tmp_path)
    await core3.start()
    assert await core3.scene.snapshot() == second
    assert (await core3.scene.snapshot()).scene_id == first.scene_id
    await core3.stop()


@pytest.mark.asyncio
async def test_core_keeps_running_when_the_scene_file_is_corrupted(tmp_path):
    scene_file = tmp_path / "state" / "scene.sqlite3"
    scene_file.parent.mkdir(parents=True)
    scene_file.write_bytes(b"not a scene database" * 64)
    journal = _Journal()
    core = JarvisCoreApplication(data_root=tmp_path, diagnostics=journal)
    await core.start()
    assert core.health.ready and core.health.status == "ok"
    assert core.scene.availability.state is SceneState.UNAVAILABLE
    assert core.scene.availability.code is SceneStoreErrorCode.CORRUPTED
    assert [(kind, level) for kind, level, _ in journal.events if kind == SCENE_UNAVAILABLE_KIND] == [(SCENE_UNAVAILABLE_KIND, "error")]
    with pytest.raises(SceneUnavailableError):
        await core.scene.snapshot()
    conversation = await core.conversations.create()
    await core.conversations.append_turn(conversation.id, TurnKind.USER, "Toujours là", correlation_id="scene-down")
    await core.stop()
    assert scene_file.read_bytes() == b"not a scene database" * 64

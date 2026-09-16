"""Service Core de la scène (handoff jarvis-constellation-scene-runtime, Slice 02).

Ce qui doit tenir :

- les commandes concurrentes sont sérialisées : révisions consécutives, une
  écriture à la fois, événements publiés dans l'ordre ;
- rien n'est publié avant d'être persisté ; un échec d'écriture n'avance ni
  la révision ni l'anneau, ne publie rien, est journalisé et rendu à
  l'appelant ;
- l'anneau de patchs est borné et dit `resync_required` quand il ne couvre
  plus l'écart ;
- un stockage refusé au démarrage rend la scène indisponible sans lever.
"""

from __future__ import annotations

import asyncio

import pytest

from jarvis.adapters.sqlite_scene import SQLiteSceneRepository
from jarvis.core.scene_service import (
    CORE_SCENE_UPDATED,
    PATCH_RING_SIZE,
    SCENE_COMMAND_REFUSED_KIND,
    SCENE_LOADED_KIND,
    SCENE_PERSIST_FAILED_KIND,
    SCENE_PUBLISH_FAILED_KIND,
    SCENE_UNAVAILABLE_KIND,
    SceneService,
    SceneState,
)
from jarvis.core.v2_services import CoreEventBus
from jarvis.domain.scene import (
    ExecState,
    SceneActor,
    SceneCommand,
    SceneCommandOutcome,
    SceneObjectFields,
    SceneObjectKind,
    SceneOp,
    ScenePatch,
    SceneRefusal,
    SceneSnapshot,
    apply_scene_patch,
)
from jarvis.ports.scene import (
    ArchivedSceneObject,
    SceneCommandSink,
    ScenePersistenceError,
    SceneReader,
    SceneStoreError,
    SceneStoreErrorCode,
    SceneUnavailableError,
)


class RecordingDiagnostics:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def emit(self, kind: str, message: str, *, level: str = "info", data: dict | None = None) -> None:
        self.events.append((kind, level, data or {}))

    def kinds(self, kind: str) -> list[tuple[str, dict]]:
        return [(level, data) for name, level, data in self.events if name == kind]


class MemoryRepository:
    """`SceneRepository` en mémoire, avec pannes et lenteur injectables."""

    def __init__(self) -> None:
        self.stored: SceneSnapshot | None = None
        self.history: list[ArchivedSceneObject] = []
        self.fail_initialize: Exception | None = None
        self.fail_commit: Exception | None = None
        self.commit_delay = 0.0
        self.commit_started = asyncio.Event()
        self.in_commit = 0
        self.max_in_commit = 0
        self.commits: list[int] = []
        self.closed = False

    async def initialize(self) -> None:
        if self.fail_initialize is not None:
            raise self.fail_initialize

    async def load(self) -> SceneSnapshot | None:
        return self.stored

    async def create(self, scene_id: str) -> SceneSnapshot:
        self.stored = SceneSnapshot(scene_id=scene_id)
        return self.stored

    async def commit(self, previous: SceneSnapshot, patch: ScenePatch, result: SceneSnapshot) -> None:
        self.in_commit += 1
        self.max_in_commit = max(self.max_in_commit, self.in_commit)
        self.commit_started.set()
        try:
            if self.commit_delay:
                await asyncio.sleep(self.commit_delay)
            else:
                await asyncio.sleep(0)
            if self.fail_commit is not None:
                raise self.fail_commit
            assert self.stored == previous, "the service must commit from the stored revision"
            self.stored = result
            self.commits.append(patch.revision)
        finally:
            self.in_commit -= 1

    async def archived_history(self, *, object_id=None, limit=100):
        return tuple(self.history)

    async def close(self) -> None:
        self.closed = True


def star(object_id: str, **fields) -> SceneCommand:
    values = {"kind": SceneObjectKind.AGENT, "category": "agent", "exec_state": ExecState.RUNNING, **fields}
    return SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=SceneActor.RUNTIME, object_id=object_id, fields=SceneObjectFields(**values))


async def started(repository=None, *, ring: int = PATCH_RING_SIZE):
    repository = repository or MemoryRepository()
    events = CoreEventBus()
    queue = events.subscribe(max_queue=1024)
    diagnostics = RecordingDiagnostics()
    service = SceneService(repository, events=events, diagnostics=diagnostics, patch_ring_size=ring)
    availability = await service.start()
    assert availability.state is SceneState.READY
    return service, repository, queue, diagnostics


def drain(queue: asyncio.Queue) -> list:
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


def test_service_implements_both_ports():
    for protocol in (SceneCommandSink, SceneReader):
        for name, member in vars(protocol).items():
            if callable(member) and not name.startswith("_"):
                assert callable(getattr(SceneService, name, None)), (protocol.__name__, name)


async def test_start_creates_a_stable_scene_and_journals_it(tmp_path):
    path = tmp_path / "scene.sqlite3"
    service, _, _, diagnostics = await started(SQLiteSceneRepository(path))
    first = await service.snapshot()
    assert first.revision == 0 and first.scene_id
    assert diagnostics.kinds(SCENE_LOADED_KIND)[0][1]["created"] is True
    await service.apply(star("star-a"))
    await service.close()

    again, _, _, diagnostics = await started(SQLiteSceneRepository(path))
    reloaded = await again.snapshot()
    assert reloaded.scene_id == first.scene_id
    assert reloaded.revision == 1
    assert diagnostics.kinds(SCENE_LOADED_KIND) == [
        ("info", {"scene_id": first.scene_id, "revision": 1, "objects": 1, "relations": 0, "archived_ids": 0, "created": False})
    ]
    await again.close()


async def test_concurrent_commands_are_serialized_with_consecutive_revisions():
    repository = MemoryRepository()
    repository.commit_delay = 0.001
    service, _, queue, _ = await started(repository)
    updates = await asyncio.gather(*(service.apply(star(f"star-{index}")) for index in range(40)))

    assert sorted(update.snapshot.revision for update in updates) == list(range(1, 41))
    assert repository.max_in_commit == 1
    assert repository.commits == list(range(1, 41))
    published = drain(queue)
    assert [event.payload["revision"] for event in published] == list(range(1, 41))
    snapshot = await service.snapshot()
    assert snapshot.revision == 40 and len(snapshot.objects) == 40
    assert repository.stored == snapshot


async def test_concurrent_commands_on_real_sqlite_persist_every_revision(tmp_path):
    path = tmp_path / "scene.sqlite3"
    service, _, queue, _ = await started(SQLiteSceneRepository(path))
    await asyncio.gather(*(service.apply(star(f"star-{index}")) for index in range(12)))
    snapshot = await service.snapshot()
    await service.close()
    reopened = SQLiteSceneRepository(path)
    await reopened.initialize()
    assert await reopened.load() == snapshot
    await reopened.close()
    assert [event.payload["revision"] for event in drain(queue)] == list(range(1, 13))


@pytest.mark.parametrize(
    "failure",
    [OSError("disk full"), SceneStoreError(SceneStoreErrorCode.STORAGE_IO, "database is locked")],
)
async def test_persistence_failure_advances_nothing_and_publishes_nothing(failure):
    service, repository, queue, diagnostics = await started()
    await service.apply(star("star-a"))
    drain(queue)
    before = await service.snapshot()

    repository.fail_commit = failure
    with pytest.raises(ScenePersistenceError, match="scene revision 2 was not persisted") as caught:
        await service.apply(star("star-b"))
    assert caught.value.code is SceneStoreErrorCode.STORAGE_IO
    assert caught.value.__cause__ is failure
    assert await service.snapshot() is before
    assert drain(queue) == []
    window = await service.patches_since(1)
    assert window.revision == 1 and window.patches == () and not window.resync_required
    assert diagnostics.kinds(SCENE_PERSIST_FAILED_KIND) == [
        ("error", {"scene_id": before.scene_id, "revision": 1, "attempted_revision": 2, "code": "storage_io",
                   "error": f"{type(failure).__name__}: {failure}"})
    ]
    assert service.availability.state is SceneState.READY

    # Transitoire : la commande suivante reprend la même révision.
    repository.fail_commit = None
    update = await service.apply(star("star-b"))
    assert update.snapshot.revision == 2
    assert [event.payload["revision"] for event in drain(queue)] == [2]


async def test_a_diverged_store_makes_the_scene_unavailable():
    service, repository, queue, diagnostics = await started()
    repository.fail_commit = SceneStoreError(SceneStoreErrorCode.REVISION_CONFLICT, "stored scene holds revision 7")
    with pytest.raises(ScenePersistenceError) as caught:
        await service.apply(star("star-a"))
    assert caught.value.code is SceneStoreErrorCode.REVISION_CONFLICT
    assert service.availability.state is SceneState.UNAVAILABLE
    for read in (service.snapshot(), service.patches_since(0), service.apply(star("star-b"))):
        with pytest.raises(SceneUnavailableError, match="scene is unavailable: SceneStoreError: stored scene holds revision 7"):
            await read
    assert drain(queue) == []
    assert diagnostics.kinds(SCENE_PERSIST_FAILED_KIND)[0][1]["code"] == "revision_conflict"


async def test_refused_and_duplicate_commands_neither_persist_nor_publish():
    service, repository, queue, diagnostics = await started()
    await service.apply(star("star-a"))
    drain(queue)
    refused = SceneCommand(op=SceneOp.ARCHIVE, actor=SceneActor.BRAIN, object_id="star-a")
    for _ in range(3):
        update = await service.apply(refused)
        assert update.outcome is SceneCommandOutcome.REJECTED_AUTHORITY
        assert update.reason is SceneRefusal.OP_NOT_ALLOWED
    duplicate = await service.apply(star("star-a"))
    assert duplicate.outcome is SceneCommandOutcome.DUPLICATE
    assert repository.commits == [1]
    assert drain(queue) == []
    assert (await service.snapshot()).revision == 1
    # Journalisé une fois par (acteur, op, issue, motif) ; le doublon est silencieux.
    assert diagnostics.kinds(SCENE_COMMAND_REFUSED_KIND) == [
        ("info", {"actor": "brain", "op": "archive", "outcome": "rejected_authority", "reason": "op_not_allowed"})
    ]


async def test_published_payload_carries_scene_id_revision_and_an_applicable_patch():
    service, _, queue, _ = await started()
    before = await service.snapshot()
    update = await service.apply(star("star-a"))
    (event,) = drain(queue)
    assert event.message_type == CORE_SCENE_UPDATED
    assert set(event.payload) == {"scene_id", "revision", "patch"}
    assert event.payload["scene_id"] == before.scene_id
    assert event.payload["revision"] == 1
    assert event.payload["patch"] == update.patch.to_payload()
    assert event.payload["patch"]["schema_version"] == 1
    assert apply_scene_patch(before, ScenePatch.from_payload(event.payload["patch"])) == await service.snapshot()


async def test_patch_ring_is_bounded_and_signals_resync():
    service, _, _, _ = await started(ring=4)
    scene_id = (await service.snapshot()).scene_id
    for index in range(6):
        await service.apply(star(f"star-{index}"))

    def revisions(window):
        return [patch.revision for patch in window.patches]

    current = await service.patches_since(6)
    assert (current.revision, current.patches, current.resync_required) == (6, (), False)
    assert revisions(await service.patches_since(3)) == [4, 5, 6]
    covered = await service.patches_since(2, scene_id=scene_id)
    assert revisions(covered) == [3, 4, 5, 6] and not covered.resync_required
    for revision, other_scene in ((1, None), (0, None), (7, None), (-1, None), (4, "another-scene")):
        window = await service.patches_since(revision, scene_id=other_scene)
        assert window.resync_required and window.patches == (), revision
        assert (window.scene_id, window.revision) == (scene_id, 6)
    with pytest.raises(TypeError):
        await service.patches_since("3")


async def test_after_restart_the_empty_ring_requires_resync_for_older_revisions(tmp_path):
    path = tmp_path / "scene.sqlite3"
    service, _, _, _ = await started(SQLiteSceneRepository(path))
    await service.apply(star("star-a"))
    await service.apply(star("star-b"))
    await service.close()
    again, _, _, _ = await started(SQLiteSceneRepository(path))
    assert (await again.patches_since(1)).resync_required
    assert not (await again.patches_since(2)).resync_required
    update = await again.apply(star("star-c"))
    assert [patch.revision for patch in (await again.patches_since(2)).patches] == [update.patch.revision] == [3]
    await again.close()


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (SceneStoreError(SceneStoreErrorCode.SCHEMA_NEWER, "scene store schema 2 is newer than supported 1"), "schema_newer"),
        (SceneStoreError(SceneStoreErrorCode.CORRUPTED, "file is not a database"), "corrupted"),
        (PermissionError("access denied"), "storage_io"),
    ],
)
async def test_start_refusal_leaves_the_scene_unavailable_without_raising(failure, code):
    repository = MemoryRepository()
    repository.fail_initialize = failure
    diagnostics = RecordingDiagnostics()
    events = CoreEventBus()
    queue = events.subscribe()
    service = SceneService(repository, events=events, diagnostics=diagnostics)
    availability = await service.start()
    assert availability.state is SceneState.UNAVAILABLE
    assert availability.code.value == code
    assert repository.closed
    assert diagnostics.kinds(SCENE_UNAVAILABLE_KIND) == [("error", {"code": code, "error": f"{type(failure).__name__}: {failure}"})]
    with pytest.raises(SceneUnavailableError) as caught:
        await service.apply(star("star-a"))
    assert caught.value.code.value == code
    with pytest.raises(SceneUnavailableError):
        await service.archived_history()
    assert drain(queue) == []
    # Un second start ne retente pas en silence : l'état reste lisible.
    assert (await service.start()).state is SceneState.UNAVAILABLE


async def test_start_refusal_on_a_real_corrupted_file(tmp_path):
    path = tmp_path / "scene.sqlite3"
    path.write_bytes(b"garbage" * 1000)
    diagnostics = RecordingDiagnostics()
    service = SceneService(SQLiteSceneRepository(path), diagnostics=diagnostics)
    availability = await service.start()
    assert (availability.state, availability.code) == (SceneState.UNAVAILABLE, SceneStoreErrorCode.CORRUPTED)
    assert "file is not a database" in diagnostics.kinds(SCENE_UNAVAILABLE_KIND)[0][1]["error"]
    assert path.read_bytes() == b"garbage" * 1000
    await service.close()


async def test_cancelled_caller_does_not_split_disk_and_memory():
    repository = MemoryRepository()
    repository.commit_delay = 0.05
    service, _, queue, _ = await started(repository)
    caller = asyncio.create_task(service.apply(star("star-a")))
    await repository.commit_started.wait()
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    # La commande en vol se termine : disque, mémoire et bus restent d'accord.
    update = await service.apply(star("star-b"))
    assert update.snapshot.revision == 2
    assert repository.commits == [1, 2]
    assert repository.stored == await service.snapshot()
    assert [event.payload["revision"] for event in drain(queue)] == [1, 2]


async def test_publish_failure_keeps_the_persisted_revision_and_is_journaled():
    class BrokenBus(CoreEventBus):
        async def publish(self, event):
            raise RuntimeError("bus closed")

    repository = MemoryRepository()
    diagnostics = RecordingDiagnostics()
    service = SceneService(repository, events=BrokenBus(), diagnostics=diagnostics)
    await service.start()
    update = await service.apply(star("star-a"))
    assert update.snapshot.revision == 1 == repository.stored.revision
    assert diagnostics.kinds(SCENE_PUBLISH_FAILED_KIND) == [
        ("error", {"scene_id": update.snapshot.scene_id, "revision": 1, "error": "RuntimeError: bus closed"})
    ]


async def test_archived_objects_leave_the_snapshot_but_stay_queryable(tmp_path):
    service, _, _, _ = await started(SQLiteSceneRepository(tmp_path / "scene.sqlite3"))
    await service.apply(star("star-a"))
    await service.apply(SceneCommand(op=SceneOp.ARCHIVE, actor=SceneActor.USER, object_id="star-a"))
    snapshot = await service.snapshot()
    assert snapshot.objects == () and snapshot.archived_ids == ("star-a",)
    (entry,) = await service.archived_history(object_id="star-a")
    assert (entry.object.object_id, entry.revision, entry.object.active) == ("star-a", 2, False)
    await service.close()
    with pytest.raises(SceneUnavailableError, match="scene is closed"):
        await service.snapshot()


def test_ring_size_is_bounded():
    for size in (0, PATCH_RING_SIZE + 1):
        with pytest.raises(ValueError):
            SceneService(MemoryRepository(), patch_ring_size=size)

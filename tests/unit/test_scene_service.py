"""Service Core de la scène (handoff jarvis-constellation-scene-runtime, Slice 02).

Ce qui doit tenir :

- les commandes concurrentes sont sérialisées : révisions consécutives, une
  écriture à la fois, patchs rangés dans l'ordre ;
- rien n'est exposé avant d'être persisté ; un échec d'écriture n'avance ni la
  révision ni l'anneau, ne réveille aucune attente, est journalisé et rendu à
  l'appelant ;
- l'anneau de patchs est borné et dit `resync_required` quand il ne couvre
  plus l'écart ;
- `wait_for_revision` se réveille sur une révision commise, rend la main à
  l'échéance (bornée), sur fermeture ou indisponibilité, et une attente
  annulée ne laisse rien derrière elle ;
- aucune commande de scène n'atteint `CoreEventBus` (donc `/v1/events`) ;
- un stockage refusé au démarrage rend la scène indisponible sans lever.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from jarvis.adapters.sqlite_scene import SQLiteSceneRepository
from jarvis.core import scene_service as scene_service_module
from jarvis.core.scene_service import (
    MAX_REVISION_WAIT_S,
    PATCH_RING_SIZE,
    SCENE_COMMAND_REFUSED_KIND,
    SCENE_LOADED_KIND,
    SCENE_PERSIST_FAILED_KIND,
    SCENE_UNAVAILABLE_KIND,
    SceneService,
    SceneState,
)
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.scene import (
    ExecState,
    SceneActor,
    SceneCommand,
    SceneCommandOutcome,
    SceneGeometry,
    SceneObjectFields,
    SceneObjectKind,
    SceneOp,
    ScenePatch,
    SceneRefusal,
    SceneSnapshot,
    apply_scene_patch,
)
from tests.unit.test_sqlite_scene import FailingConnection
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

    async def initialize(self) -> bool:
        if self.fail_initialize is not None:
            raise self.fail_initialize
        created = self.stored is None
        if created:
            self.stored = SceneSnapshot(scene_id="scene-memory")
        return created

    async def load(self) -> SceneSnapshot:
        return self.stored

    async def commit(self, previous: SceneSnapshot, patch: ScenePatch, result: SceneSnapshot) -> None:
        self.in_commit += 1
        self.max_in_commit = max(self.max_in_commit, self.in_commit)
        self.commit_started.set()
        try:
            await asyncio.sleep(self.commit_delay)
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
    diagnostics = RecordingDiagnostics()
    service = SceneService(repository, diagnostics=diagnostics, patch_ring_size=ring)
    availability = await service.start()
    assert availability.state is SceneState.READY
    return service, repository, diagnostics


async def ring_revisions(service: SceneService) -> list[int]:
    return [patch.revision for patch in (await service.patches_since(0)).patches]


async def settle() -> None:
    """Laisser tourner la boucle : une attente bloquée le reste ensuite."""

    for _ in range(5):
        await asyncio.sleep(0)


def pending_event_waiters(service: SceneService) -> int:
    # Détail d'implémentation d'`asyncio.Event` : seul moyen de prouver qu'une
    # attente annulée ne reste pas inscrite.
    return len(getattr(service._changed, "_waiters", ()))


def test_service_implements_both_ports():
    for protocol in (SceneCommandSink, SceneReader):
        for name, member in vars(protocol).items():
            if callable(member) and not name.startswith("_"):
                assert callable(getattr(SceneService, name, None)), (protocol.__name__, name)


def test_service_takes_no_event_bus():
    assert "events" not in inspect.signature(SceneService).parameters
    assert not hasattr(scene_service_module, "CORE_SCENE_UPDATED")


async def test_start_creates_a_stable_scene_and_journals_it(tmp_path):
    path = tmp_path / "scene.sqlite3"
    service, _, diagnostics = await started(SQLiteSceneRepository(path))
    first = await service.snapshot()
    assert first.revision == 0 and first.scene_id
    assert diagnostics.kinds(SCENE_LOADED_KIND)[0][1]["created"] is True
    await service.apply(star("star-a"))
    await service.close()

    again, _, diagnostics = await started(SQLiteSceneRepository(path))
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
    service, _, _ = await started(repository)
    updates = await asyncio.gather(*(service.apply(star(f"star-{index}")) for index in range(40)))

    assert sorted(update.snapshot.revision for update in updates) == list(range(1, 41))
    assert repository.max_in_commit == 1
    assert repository.commits == list(range(1, 41))
    assert await ring_revisions(service) == list(range(1, 41))
    snapshot = await service.snapshot()
    assert snapshot.revision == 40 and len(snapshot.objects) == 40
    assert repository.stored == snapshot


async def test_concurrent_commands_on_real_sqlite_persist_every_revision(tmp_path):
    path = tmp_path / "scene.sqlite3"
    service, _, _ = await started(SQLiteSceneRepository(path))
    await asyncio.gather(*(service.apply(star(f"star-{index}")) for index in range(12)))
    snapshot = await service.snapshot()
    assert await ring_revisions(service) == list(range(1, 13))
    await service.close()
    reopened = SQLiteSceneRepository(path)
    await reopened.initialize()
    assert await reopened.load() == snapshot
    await reopened.close()


@pytest.mark.parametrize(
    "failure",
    [OSError("disk full"), SceneStoreError(SceneStoreErrorCode.STORAGE_IO, "database is locked")],
)
async def test_persistence_failure_advances_nothing_and_wakes_no_waiter(failure):
    service, repository, diagnostics = await started()
    await service.apply(star("star-a"))
    before = await service.snapshot()
    waiter = asyncio.create_task(service.wait_for_revision(1, timeout_s=5))
    await settle()

    repository.fail_commit = failure
    with pytest.raises(ScenePersistenceError, match="scene revision 2 was not persisted") as caught:
        await service.apply(star("star-b"))
    assert caught.value.code is SceneStoreErrorCode.STORAGE_IO
    assert caught.value.__cause__ is failure
    assert await service.snapshot() is before
    await settle()
    assert not waiter.done()
    window = await service.patches_since(1)
    assert window.revision == 1 and window.patches == () and not window.resync_required
    assert diagnostics.kinds(SCENE_PERSIST_FAILED_KIND) == [
        ("error", {"scene_id": before.scene_id, "revision": 1, "attempted_revision": 2, "code": "storage_io",
                   "error": f"{type(failure).__name__}: {failure}"})
    ]
    assert service.availability.state is SceneState.READY

    # Transitoire : la commande suivante reprend la même révision et réveille l'attente.
    repository.fail_commit = None
    update = await service.apply(star("star-b"))
    assert update.snapshot.revision == 2
    assert await asyncio.wait_for(waiter, 1) == 2
    assert await ring_revisions(service) == [1, 2]


async def test_a_diverged_store_makes_the_scene_unavailable_and_wakes_waiters():
    service, repository, diagnostics = await started()
    waiter = asyncio.create_task(service.wait_for_revision(0, timeout_s=5))
    await settle()
    repository.fail_commit = SceneStoreError(SceneStoreErrorCode.REVISION_CONFLICT, "stored scene holds revision 7")
    with pytest.raises(ScenePersistenceError) as caught:
        await service.apply(star("star-a"))
    assert caught.value.code is SceneStoreErrorCode.REVISION_CONFLICT
    assert service.availability.state is SceneState.UNAVAILABLE
    with pytest.raises(SceneUnavailableError, match="scene is unavailable"):
        await asyncio.wait_for(waiter, 1)
    reads = (service.snapshot(), service.patches_since(0), service.wait_for_revision(0, timeout_s=5), service.apply(star("star-b")))
    for read in reads:
        with pytest.raises(SceneUnavailableError, match="scene is unavailable: SceneStoreError: stored scene holds revision 7"):
            await read
    assert diagnostics.kinds(SCENE_PERSIST_FAILED_KIND)[0][1]["code"] == "revision_conflict"


async def test_refused_and_duplicate_commands_neither_persist_nor_wake():
    service, repository, diagnostics = await started()
    await service.apply(star("star-a"))
    waiter = asyncio.create_task(service.wait_for_revision(1, timeout_s=0.2))
    refused = SceneCommand(op=SceneOp.ARCHIVE, actor=SceneActor.BRAIN, object_id="star-a")
    for _ in range(3):
        update = await service.apply(refused)
        assert update.outcome is SceneCommandOutcome.REJECTED_AUTHORITY
        assert update.reason is SceneRefusal.OP_NOT_ALLOWED
    duplicate = await service.apply(star("star-a"))
    assert duplicate.outcome is SceneCommandOutcome.DUPLICATE
    assert repository.commits == [1]
    assert await waiter == 1
    assert (await service.snapshot()).revision == 1
    # Journalisé une fois par (acteur, op, issue, motif) ; le doublon est silencieux.
    assert diagnostics.kinds(SCENE_COMMAND_REFUSED_KIND) == [
        ("info", {"actor": "brain", "op": "archive", "outcome": "rejected_authority", "reason": "op_not_allowed"})
    ]


async def test_ring_patches_replay_exactly_onto_the_previous_snapshot():
    service, _, _ = await started()
    before = await service.snapshot()
    update = await service.apply(star("star-a"))
    (patch,) = (await service.patches_since(0)).patches
    assert patch == update.patch
    assert patch.to_payload()["schema_version"] == 1
    assert apply_scene_patch(before, ScenePatch.from_payload(patch.to_payload())) == await service.snapshot()


async def test_patch_ring_is_bounded_and_signals_resync():
    service, _, _ = await started(ring=4)
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
    service, _, _ = await started(SQLiteSceneRepository(path))
    await service.apply(star("star-a"))
    await service.apply(star("star-b"))
    await service.close()
    again, _, _ = await started(SQLiteSceneRepository(path))
    assert (await again.patches_since(1)).resync_required
    assert not (await again.patches_since(2)).resync_required
    update = await again.apply(star("star-c"))
    assert [patch.revision for patch in (await again.patches_since(2)).patches] == [update.patch.revision] == [3]
    await again.close()


# --- attente de révision (long-poll de la Slice 03) -------------------------------------------


async def test_waiter_is_woken_by_a_commit():
    service, _, _ = await started()
    loop = asyncio.get_running_loop()
    started_at = loop.time()
    waiter = asyncio.create_task(service.wait_for_revision(0, timeout_s=10))
    await settle()
    assert not waiter.done()
    await service.apply(star("star-a"))
    assert await asyncio.wait_for(waiter, 1) == 1
    assert loop.time() - started_at < 2
    assert pending_event_waiters(service) == 0


async def test_a_revision_already_past_returns_at_once_and_a_timeout_returns_it_unchanged():
    service, _, _ = await started()
    await service.apply(star("star-a"))
    loop = asyncio.get_running_loop()
    assert await asyncio.wait_for(service.wait_for_revision(0, timeout_s=10), 0.5) == 1
    started_at = loop.time()
    assert await service.wait_for_revision(1, timeout_s=0.05) == 1
    assert 0.03 <= loop.time() - started_at < 1
    for timeout in (0, -3, float("-inf")):
        assert await asyncio.wait_for(service.wait_for_revision(1, timeout_s=timeout), 0.5) == 1
    # Un client en avance (autre scène) attend l'échéance puis lit la révision réelle.
    assert await service.wait_for_revision(99, timeout_s=0.01) == 1
    for bad in ("1", None, float("nan"), True):
        with pytest.raises(TypeError):
            await service.wait_for_revision(0, timeout_s=bad)
    with pytest.raises(TypeError):
        await service.wait_for_revision("0", timeout_s=1)


async def test_wait_is_clamped_to_the_maximum(monkeypatch):
    assert MAX_REVISION_WAIT_S == 30.0
    monkeypatch.setattr(scene_service_module, "MAX_REVISION_WAIT_S", 0.05)
    service, _, _ = await started()
    loop = asyncio.get_running_loop()
    started_at = loop.time()
    assert await asyncio.wait_for(service.wait_for_revision(0, timeout_s=3600), 2) == 0
    assert loop.time() - started_at < 1
    assert await asyncio.wait_for(service.wait_for_revision(0, timeout_s=float("inf")), 2) == 0


async def test_a_waiter_ahead_by_several_revisions_waits_for_the_one_it_asked():
    service, _, _ = await started()
    waiter = asyncio.create_task(service.wait_for_revision(2, timeout_s=5))
    await service.apply(star("star-a"))
    await service.apply(star("star-b"))
    await settle()
    assert not waiter.done()
    await service.apply(star("star-c"))
    assert await asyncio.wait_for(waiter, 1) == 3


async def test_close_wakes_every_waiter_with_an_explicit_unavailability():
    service, _, _ = await started()
    waiters = [asyncio.create_task(service.wait_for_revision(0, timeout_s=10)) for _ in range(5)]
    await settle()
    await service.close()
    results = await asyncio.wait_for(asyncio.gather(*waiters, return_exceptions=True), 1)
    assert all(isinstance(result, SceneUnavailableError) and "scene is closed" in str(result) for result in results)
    with pytest.raises(SceneUnavailableError, match="scene is closed"):
        await service.wait_for_revision(0, timeout_s=10)


async def test_cancelled_waiters_leave_nothing_behind():
    service, _, _ = await started()
    baseline = asyncio.all_tasks()
    waiters = [asyncio.create_task(service.wait_for_revision(0, timeout_s=10)) for _ in range(20)]
    await settle()
    assert pending_event_waiters(service) == 20
    for waiter in waiters:
        waiter.cancel()
    results = await asyncio.gather(*waiters, return_exceptions=True)
    assert all(isinstance(result, asyncio.CancelledError) for result in results)
    await settle()
    assert pending_event_waiters(service) == 0
    assert asyncio.all_tasks() == baseline
    # Le service reste pleinement utilisable.
    survivor = asyncio.create_task(service.wait_for_revision(0, timeout_s=5))
    await settle()
    await service.apply(star("star-a"))
    assert await asyncio.wait_for(survivor, 1) == 1


async def test_many_concurrent_waiters_each_get_a_revision_past_their_own():
    service, _, _ = await started()
    waiters = [(after, asyncio.create_task(service.wait_for_revision(after, timeout_s=5))) for after in range(5) for _ in range(40)]
    await settle()
    for index in range(5):
        await service.apply(star(f"star-{index}"))
    for after, waiter in waiters:
        revision = await asyncio.wait_for(waiter, 2)
        assert after < revision <= 5
    assert pending_event_waiters(service) == 0


async def test_scene_commands_never_reach_the_core_event_bus(tmp_path):
    """Garde de régression : `/v1/events` relaie tout le bus à Voice."""

    # `scene_repository` : la garde porte sur le bus, pas sur SQLite.
    core = JarvisCoreApplication(data_root=tmp_path, scene_repository=MemoryRepository())
    await core.start()
    published = []
    original = core.events.publish

    async def spy(event):
        published.append(event)
        await original(event)

    core.events.publish = spy
    commands = [
        star("star-a"),
        star("star-b"),
        SceneCommand(op=SceneOp.SET_GEOMETRY, actor=SceneActor.USER, object_id="star-a", geometry=SceneGeometry(1, 2, 30, 30)),
        SceneCommand(op=SceneOp.ARCHIVE, actor=SceneActor.BRAIN, object_id="star-a"),
        SceneCommand(op=SceneOp.ARCHIVE, actor=SceneActor.USER, object_id="star-b"),
        star("star-a"),
    ]
    for command in commands:
        await core.scene.apply(command)
    assert await core.scene.wait_for_revision(0, timeout_s=1) == 4
    try:
        scene_events = [
            event for event in published
            if "scene" in event.message_type or {"scene_id", "patch"} & set(event.payload)
        ]
        assert scene_events == []
    finally:
        core.events.publish = original
        await core.stop()


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
    service = SceneService(repository, diagnostics=diagnostics)
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
    with pytest.raises(SceneUnavailableError):
        await asyncio.wait_for(service.wait_for_revision(0, timeout_s=10), 0.5)
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
    service, _, _ = await started(repository)
    caller = asyncio.create_task(service.apply(star("star-a")))
    await repository.commit_started.wait()
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    # La commande en vol se termine : disque, mémoire et anneau restent d'accord.
    update = await service.apply(star("star-b"))
    assert update.snapshot.revision == 2
    assert repository.commits == [1, 2]
    assert repository.stored == await service.snapshot()
    assert await ring_revisions(service) == [1, 2]


async def test_archived_objects_leave_the_snapshot_but_stay_queryable(tmp_path):
    service, _, _ = await started(SQLiteSceneRepository(tmp_path / "scene.sqlite3"))
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


# --- stockage coincé (reprise QA de la Slice 02) -------------------------------------------


async def test_a_fatal_storage_error_makes_the_scene_unavailable():
    service, repository, diagnostics = await started()
    waiter = asyncio.create_task(service.wait_for_revision(0, timeout_s=5))
    await settle()
    repository.fail_commit = SceneStoreError(SceneStoreErrorCode.STORAGE_IO, "connection left inside a transaction", fatal=True)
    with pytest.raises(ScenePersistenceError) as caught:
        await service.apply(star("star-a"))
    assert caught.value.code is SceneStoreErrorCode.STORAGE_IO
    assert (service.availability.state, service.availability.code) == (SceneState.UNAVAILABLE, SceneStoreErrorCode.STORAGE_IO)
    with pytest.raises(SceneUnavailableError):
        await asyncio.wait_for(waiter, 1)
    (level, data), = diagnostics.kinds(SCENE_PERSIST_FAILED_KIND)
    assert (level, data["code"]) == ("error", "storage_io")


@pytest.mark.parametrize(("fail_at", "after", "rollback_fails", "state"), [
    (0, True, False, SceneState.READY),        # BEGIN a ouvert la transaction puis levé : annulée
    (2, False, True, SceneState.UNAVAILABLE),  # écriture en échec et ROLLBACK impossible
])
async def test_real_store_failures_after_begin_or_on_rollback(tmp_path, fail_at, after, rollback_fails, state):
    repository = SQLiteSceneRepository(tmp_path / "scene.sqlite3")
    service, _, diagnostics = await started(repository)
    real = repository._conn
    repository._conn = FailingConnection(real, fail_at=fail_at, after=after, rollback_fails=rollback_fails)
    try:
        with pytest.raises(ScenePersistenceError) as caught:
            await service.apply(star("star-a"))
    finally:
        repository._conn = real
    assert caught.value.code is SceneStoreErrorCode.STORAGE_IO
    assert service.availability.state is state
    assert diagnostics.kinds(SCENE_PERSIST_FAILED_KIND)[0][0] == "error"
    if state is SceneState.READY:
        assert (await service.apply(star("star-a"))).snapshot.revision == 1
    else:
        with pytest.raises(SceneUnavailableError, match="left inside a transaction"):
            await service.apply(star("star-a"))
    await service.close()
    reopened = SQLiteSceneRepository(tmp_path / "scene.sqlite3")
    await reopened.initialize()
    assert (await reopened.load()).revision == (1 if state is SceneState.READY else 0)
    await reopened.close()

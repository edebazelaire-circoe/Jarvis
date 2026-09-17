"""Projection runtime de l'état de travail vers la scène (handoff jarvis-constellation-scene-runtime, Slice 04).

Pièces réelles : `WorkStateStore`, `CoreEventBus`, `SceneService` (dépôt en
mémoire ou SQLite). Ce qui doit tenir :

- un sous-agent (`kind = agent`) et un job (`kind = job`) deviennent des
  étoiles ; une commande shell ou une tâche `other`, jamais ;
- le lien parent → enfant apparaît dans quelque ordre que les étoiles arrivent,
  jamais vers un parent shell ;
- `failed` / `interrupted` / `blocked` posent un seul signal vivant par travail ;
  quitter l'état le retire (lien délié), `failed` reste ;
- une fin ne change ni visibilité ni disposition ; une étoile archivée ne renaît
  pas et ne produit aucun refus journalisé ;
- doublons et rejeux ne font pas bouger la révision ; un trou ou un autre
  `store_id` réconcilient sans rien effacer ;
- une scène indisponible est journalisée une fois par panne, puis la projection
  réconcilie au retour ; l'arrêt de Core ne rencontre jamais une scène fermée ;
- rien n'est publié sur le bus pour la scène.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from jarvis.adapters.sqlite_scene import SQLiteSceneRepository
from jarvis.core.scene_projector import (
    SCENE_PROJECTION_CONFLICT_KIND,
    SCENE_PROJECTION_DESATURATED_KIND,
    SCENE_PROJECTION_PENDING_OVERFLOW_KIND,
    SCENE_PROJECTION_SATURATED_KIND,
    SCENE_PROJECTION_FAILED_KIND,
    SCENE_PROJECTION_RECONCILED_KIND,
    SCENE_PROJECTION_RESTORED_KIND,
    SCENE_PROJECTION_UNAVAILABLE_KIND,
    SCENE_SIGNAL_RAISED_KIND,
    SCENE_SIGNAL_RETIRED_KIND,
    SCENE_STAR_CREATED_KIND,
    SceneProjector,
    parent_relation_id,
    signal_object_id,
    star_object_id,
)
from jarvis.core.scene_service import SCENE_COMMAND_REFUSED_KIND, SceneService, SceneState
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.core.v2_services import CoreEventBus
from jarvis.core.work_state import CORE_WORK_UPDATED, WorkStateStore
from jarvis.domain._checks import MAX_ID_CHARS
from jarvis.domain.scene import (
    MAX_SCENE_OBJECTS,
    Disposition,
    ExecState,
    PlacedBy,
    RelationKind,
    SceneActor,
    SceneCommand,
    SceneConstraints,
    SceneGeometry,
    SceneObject,
    SceneObjectFields,
    SceneObjectKind,
    SceneOp,
    ScenePayload,
    SceneRelation,
    SceneSnapshot,
    Visibility,
    WorkRef,
    is_live_signal,
)
from jarvis.domain.v2 import Job, ProtocolEnvelope
from jarvis.domain.work_state import WorkLink, WorkObservation, WorkStatus
from jarvis.ports.scene import SceneStoreError, SceneStoreErrorCode
from tests.unit.test_scene_service import MemoryRepository, RecordingDiagnostics

#: Proche de l'horloge réelle : Core date ses propres interruptions avec elle.
T0 = datetime.now(timezone.utc)


def obs(external_id: str, status: WorkStatus = WorkStatus.RUNNING, *, at: int = 0, source: str = "claude", **fields) -> WorkObservation:
    fields.setdefault("kind", "agent")
    return WorkObservation(source=source, external_id=external_id, status=status, observed_at=T0 + timedelta(seconds=at), **fields)


class Stack:
    def __init__(
        self, *, repository=None, queue_size: int = 512, stop_drain_s: float = 2.0, work_max_items: int = 64, **projector
    ) -> None:
        self.diagnostics = RecordingDiagnostics()
        self.events = CoreEventBus(diagnostics=self.diagnostics)
        self.work = WorkStateStore(events=self.events, diagnostics=self.diagnostics, max_items=work_max_items)
        self.repository = repository or MemoryRepository()
        self.scene = SceneService(self.repository, diagnostics=self.diagnostics)
        projector.setdefault("saturation_warning_interval_s", 0)
        self.projector = SceneProjector(
            work=self.work, scene=self.scene, events=self.events, diagnostics=self.diagnostics,
            queue_size=queue_size, retry_min_s=0.01, retry_max_s=0.05, stop_drain_s=stop_drain_s, **projector,
        )

    async def __aenter__(self) -> Stack:
        await self.scene.start()
        self.projector.start()
        await settled(self.projector)
        return self

    async def __aexit__(self, *exc) -> None:
        await self.projector.stop()
        await self.scene.close()

    async def observe(self, *observations: WorkObservation) -> None:
        for observation in observations:
            await self.work.observe(observation)
        await settled(self.projector)

    async def snapshot(self):
        return await self.scene.snapshot()


async def settled(projector: SceneProjector, *, timeout: float = 30.0) -> None:
    """Attendre que la projection ait tout traité (file vide, rien à réconcilier, boucle au repos)."""

    async def idle() -> None:
        while True:
            queue = projector._queue
            if projector._dirty is None and projector._idle.is_set() and (queue is None or queue.empty()):
                # Un tour de boucle de plus : l'événement pris vient peut-être d'être traité.
                await asyncio.sleep(0)
                if projector._idle.is_set() and (queue is None or queue.empty()):
                    return
            await asyncio.sleep(0.005)

    await asyncio.wait_for(idle(), timeout)


def ids(snapshot) -> set[str]:
    return {item.object_id for item in snapshot.objects}


# --- étoiles ------------------------------------------------------------------


async def test_a_sub_agent_becomes_a_runtime_star_carrying_work_truth():
    async with Stack() as stack:
        await stack.observe(obs("toolu_A", label="Audit du dépôt", link=WorkLink(work_id="w-1"), summary="début"))
        snapshot = await stack.snapshot()

    star = snapshot.get_object("claude:toolu_A")
    assert star is not None and snapshot.revision == 1
    assert (star.kind, star.category, star.exec_state, star.origin) == (SceneObjectKind.AGENT, "agent", ExecState.RUNNING, SceneActor.RUNTIME)
    assert star.work_ref == WorkRef(source="claude", external_id="toolu_A", work_id="w-1")
    assert star.payload == ScenePayload(title="Audit du dépôt", summary="début")
    assert (star.geometry, star.visibility, star.constraints.placed_by) == (None, Visibility.VISIBLE, PlacedBy.RUNTIME)
    assert stack.diagnostics.kinds(SCENE_STAR_CREATED_KIND) == [
        ("info", {"object_id": "claude:toolu_A", "kind": "agent", "source": "claude", "status": "running"})
    ]


@pytest.mark.parametrize("kind", ["shell", "other", ""])
async def test_shell_and_other_tasks_never_become_stars(kind):
    async with Stack() as stack:
        await stack.observe(obs("bash_1", kind=kind, label="npm test"), obs("bash_1", WorkStatus.FAILED, at=1, kind=kind))
        snapshot = await stack.snapshot()
    assert snapshot.objects == () and snapshot.revision == 0


async def test_a_task_that_turns_out_to_be_an_agent_becomes_a_star_then():
    async with Stack() as stack:
        await stack.observe(obs("t-1", kind="other"))
        assert (await stack.snapshot()).objects == ()
        await stack.observe(obs("t-1", at=1, kind="agent", label="Sous-agent"))
        assert ids(await stack.snapshot()) == {"claude:t-1"}


async def test_a_core_job_becomes_a_job_star_and_its_end_is_projected(tmp_path):
    release = asyncio.Event()

    class Worker:
        async def execute(self, job):
            await release.wait()
            return {"ok": True}

        async def cancel(self, job_id):
            return None

    core = JarvisCoreApplication(data_root=tmp_path / "data", workers={"demo": Worker()})
    await core.start()
    try:
        job = await core.jobs.submit(Job(kind="demo", payload={}))
        star_id = star_object_id("job", job.id)
        await wait_for_state(core, star_id, ExecState.RUNNING)
        star = (await core.scene.snapshot()).get_object(star_id)
        assert (star.kind, star.category, star.payload.title) == (SceneObjectKind.JOB, "job", "demo")
        release.set()
        await wait_for_state(core, star_id, ExecState.COMPLETED)
    finally:
        await core.stop()


async def wait_for_state(core: JarvisCoreApplication, object_id: str, state: ExecState) -> None:
    async def reached() -> None:
        while True:
            item = (await core.scene.snapshot()).get_object(object_id)
            if item is not None and item.exec_state is state:
                return
            await asyncio.sleep(0.01)

    await asyncio.wait_for(reached(), 5)


# --- topologie ----------------------------------------------------------------


@pytest.mark.parametrize("child_first", [False, True], ids=["parent-first", "child-first"])
async def test_a_nested_sub_agent_is_linked_to_its_parent_in_any_order(child_first):
    parent = obs("parent", label="Parent")
    child = obs("child", label="Enfant", parent_external_id="parent")
    grandchild = obs("grand", label="Petit-enfant", parent_external_id="child")
    order = (grandchild, child, parent) if child_first else (parent, child, grandchild)
    async with Stack() as stack:
        await stack.observe(*order)
        snapshot = await stack.snapshot()

    links = {(item.from_id, item.to_id) for item in snapshot.relations if item.kind is RelationKind.PARENT_OF}
    assert links == {("claude:parent", "claude:child"), ("claude:child", "claude:grand")}
    assert snapshot.get_relation(parent_relation_id("claude:child")).from_id == "claude:parent"


async def test_a_shell_parent_gives_no_star_and_no_link():
    async with Stack() as stack:
        await stack.observe(obs("bash", kind="shell"), obs("agent", parent_external_id="bash"))
        snapshot = await stack.snapshot()
    assert ids(snapshot) == {"claude:agent"} and snapshot.relations == ()


async def test_same_external_id_in_another_source_is_another_star_and_not_a_parent():
    async with Stack() as stack:
        await stack.observe(obs("x", source="job", kind="job"), obs("y", parent_external_id="x"))
        snapshot = await stack.snapshot()
    assert ids(snapshot) == {"job:x", "claude:y"} and snapshot.relations == ()


# --- signaux ------------------------------------------------------------------


async def test_a_failure_attaches_one_signal_carrying_its_error_class_and_message():
    async with Stack() as stack:
        await stack.observe(obs("a", label="Recherche"), obs("a", WorkStatus.FAILED, at=1, error_class="provider_error", summary="quota\r\ndépassé\x07"))
        snapshot = await stack.snapshot()

    star_id = "claude:a"
    signal_id = signal_object_id(star_id)
    assert signal_id == "attention!claude:a"
    signal = snapshot.get_object(signal_id)
    assert (signal.kind, signal.category, signal.exec_state, signal.origin) == (SceneObjectKind.ATTENTION, "failed", ExecState.FAILED, SceneActor.RUNTIME)
    assert signal.payload.title == "provider_error"
    assert signal.payload.summary == "quota\ndépassé"
    assert signal.work_ref == WorkRef("claude", "a")
    assert is_live_signal(snapshot, signal_id)
    assert snapshot.get_relation(signal_id).to_id == star_id
    assert snapshot.get_object(star_id).exec_state is ExecState.FAILED
    assert len(stack.diagnostics.kinds(SCENE_SIGNAL_RAISED_KIND)) == 1


async def test_blocked_then_running_retires_the_signal_and_blocked_again_raises_the_same_one():
    async with Stack() as stack:
        await stack.observe(obs("a"), obs("a", WorkStatus.BLOCKED, at=1, activity="attend une réponse"))
        blocked = await stack.snapshot()
        signal_id = signal_object_id("claude:a")
        assert is_live_signal(blocked, signal_id)
        assert blocked.get_object(signal_id).payload.summary == "attend une réponse"

        await stack.observe(obs("a", at=2, activity="reprend"))
        running = await stack.snapshot()
        assert not is_live_signal(running, signal_id)
        assert running.get_object(signal_id).exec_state is ExecState.RUNNING
        assert running.get_object("claude:a").exec_state is ExecState.RUNNING
        assert len(running.objects) == 2  # le signal retiré reste, un seul par travail

        await stack.observe(obs("a", WorkStatus.BLOCKED, at=3), obs("a", WorkStatus.FAILED, at=4, error_class="timeout"))
        failed = await stack.snapshot()
        assert is_live_signal(failed, signal_id) and len(failed.objects) == 2
        assert (failed.get_object(signal_id).category, failed.get_object(signal_id).payload.title) == ("failed", "timeout")
        # Fin définitive : un constat répété ne retire rien.
        await stack.observe(obs("a", WorkStatus.FAILED, at=5, error_class="timeout"))
        assert is_live_signal(await stack.snapshot(), signal_id)
    assert len(stack.diagnostics.kinds(SCENE_SIGNAL_RETIRED_KIND)) == 1
    assert len(stack.diagnostics.kinds(SCENE_SIGNAL_RAISED_KIND)) == 2


async def test_a_reopened_interruption_retires_its_signal_and_completion_needs_none():
    async with Stack() as stack:
        await stack.work.ingest(batch("cc-1", obs("a")))
        await stack.work.ingest(batch("cc-2", obs("b")))  # autre instance : `a` interrompu par Core
        await settled(stack.projector)
        interrupted = await stack.snapshot()
        signal_id = signal_object_id("claude:a")
        assert interrupted.get_object("claude:a").exec_state is ExecState.INTERRUPTED
        assert interrupted.get_object(signal_id).payload.title == "producer_restarted"
        assert is_live_signal(interrupted, signal_id)

        # Le revendicateur courant le dit vivant, après l'interruption posée par Core.
        await stack.work.ingest(batch("cc-2", obs("a", at=3_600)))
        await settled(stack.projector)
        reopened = await stack.snapshot()
        assert reopened.get_object("claude:a").exec_state is ExecState.RUNNING
        assert not is_live_signal(reopened, signal_id)
        await stack.observe(obs("a", WorkStatus.COMPLETED, at=3_601))
        done = await stack.snapshot()
    assert not is_live_signal(done, signal_id)
    assert done.get_object(signal_id).exec_state is ExecState.COMPLETED
    assert done.get_object(signal_object_id("claude:b")) is None


def batch(producer: str, *observations: WorkObservation):
    from jarvis.domain.work_state import WorkObservationBatch

    return WorkObservationBatch(source="claude", producer_id=producer, observations=observations)


async def test_a_signal_id_taken_by_the_brain_is_left_alone_and_reported_once():
    # Depuis le Slice 06, le domaine refuse cet identifiant au cerveau
    # (`reserved_id`) : le conflit ne vient plus que d'une scène déjà stockée.
    from jarvis.domain.scene import (
        ExecState, PlacedBy, RelationKind, SceneConstraints, SceneObject, SceneObjectKind, SceneRefusal, SceneRelation,
        SceneSnapshot,
    )

    signal_id = signal_object_id("claude:a")
    repository = MemoryRepository()
    repository.stored = SceneSnapshot(
        scene_id="scene-memory", revision=2,
        objects=(
            SceneObject(object_id="claude:a", kind=SceneObjectKind.AGENT, category="agent", origin=SceneActor.RUNTIME,
                        constraints=SceneConstraints(placed_by=PlacedBy.RUNTIME), exec_state=ExecState.RUNNING),
            SceneObject(object_id=signal_id, kind=SceneObjectKind.ATTENTION, category="note", origin=SceneActor.BRAIN,
                        constraints=SceneConstraints(placed_by=PlacedBy.BRAIN), layer=300, payload=ScenePayload(title="à regarder")),
        ),
        relations=(SceneRelation(signal_id, RelationKind.EXPLAINS, signal_id, "claude:a"),),
    )
    async with Stack(repository=repository) as stack:
        refused = await stack.scene.apply(
            SceneCommand(op=SceneOp.ATTACH_SIGNAL, actor=SceneActor.BRAIN, object_id=signal_object_id("claude:z"),
                         target_id="claude:a", fields=SceneObjectFields(category="note"))
        )
        assert refused.reason is SceneRefusal.RESERVED_ID
        refused_before = len(stack.diagnostics.kinds(SCENE_COMMAND_REFUSED_KIND))
        await stack.observe(obs("a"), obs("a", WorkStatus.BLOCKED, at=1), obs("a", at=2), obs("a", WorkStatus.FAILED, at=3))
        snapshot = await stack.snapshot()
    note = snapshot.get_object(signal_id)
    assert (note.origin, note.payload.title, note.category) == (SceneActor.BRAIN, "à regarder", "note")
    assert is_live_signal(snapshot, signal_id)
    assert len(stack.diagnostics.kinds(SCENE_PROJECTION_CONFLICT_KIND)) == 1
    assert len(stack.diagnostics.kinds(SCENE_COMMAND_REFUSED_KIND)) == refused_before


# --- fin, archivage, composition ---------------------------------------------


async def test_completion_keeps_the_star_active_visible_and_where_the_user_put_it():
    async with Stack() as stack:
        await stack.observe(obs("a"), obs("b"))
        geometry = SceneGeometry(10, 20, 40, 40)
        await stack.scene.apply(SceneCommand(op=SceneOp.SET_GEOMETRY, actor=SceneActor.USER, object_id="claude:a", geometry=geometry))
        await stack.scene.apply(SceneCommand(op=SceneOp.SET_VISIBILITY, actor=SceneActor.USER, object_id="claude:b", visibility=Visibility.HIDDEN))
        await stack.observe(obs("a", WorkStatus.COMPLETED, at=1), obs("b", WorkStatus.CANCELLED, at=1, error_class="killed"))
        snapshot = await stack.snapshot()
    a, b = snapshot.get_object("claude:a"), snapshot.get_object("claude:b")
    assert (a.exec_state, a.disposition, a.visibility, a.geometry) == (ExecState.COMPLETED, Disposition.ACTIVE, Visibility.VISIBLE, geometry)
    assert (b.exec_state, b.disposition, b.visibility) == (ExecState.CANCELLED, Disposition.ACTIVE, Visibility.HIDDEN)
    assert snapshot.relations == ()  # ni fin normale ni annulation ne posent de signal


async def test_a_user_archived_star_never_resurrects_and_causes_no_refusal():
    async with Stack() as stack:
        await stack.observe(obs("a"), obs("child", parent_external_id="a"))
        await stack.scene.apply(SceneCommand(op=SceneOp.ARCHIVE, actor=SceneActor.USER, object_id="claude:a"))
        archived = await stack.snapshot()
        await stack.observe(obs("a", at=1, summary="toujours là"), obs("a", WorkStatus.FAILED, at=2, error_class="boom"))
        assert await stack.projector._reconcile("test")  # une réconciliation complète ne la ressuscite pas non plus
        snapshot = await stack.snapshot()
    assert snapshot == archived
    assert snapshot.is_archived("claude:a") and snapshot.get_object(signal_object_id("claude:a")) is None
    assert stack.projector.stats.skipped_archived >= 3
    assert stack.diagnostics.kinds(SCENE_COMMAND_REFUSED_KIND) == []


async def test_the_projection_never_overwrites_a_payload_the_brain_rewrote():
    async with Stack() as stack:
        await stack.observe(obs("a", label="Titre runtime"))
        await stack.observe(obs("a", at=1, summary="premier résumé"))
        assert (await stack.snapshot()).get_object("claude:a").payload.summary == "premier résumé"
        brain = ScenePayload(title="Titre du cerveau", summary="ma lecture")
        await stack.scene.apply(SceneCommand(op=SceneOp.PATCH_OBJECT, actor=SceneActor.BRAIN, object_id="claude:a", fields=SceneObjectFields(payload=brain, category="research")))
        await stack.observe(obs("a", WorkStatus.COMPLETED, at=2, summary="résumé final"))
        star = (await stack.snapshot()).get_object("claude:a")
    assert (star.payload, star.category, star.exec_state) == (brain, "research", ExecState.COMPLETED)


# --- idempotence, trous, réinitialisation -------------------------------------


async def test_duplicate_observations_and_replayed_events_change_no_revision():
    async with Stack() as stack:
        await stack.observe(obs("p"), obs("a", parent_external_id="p"), obs("a", WorkStatus.FAILED, at=1, error_class="boom"))
        before = await stack.snapshot()
        await stack.observe(obs("a", WorkStatus.FAILED, at=1, error_class="boom"), obs("p", at=0))
        # Rejeu brut d'un événement déjà vu, puis réconciliation complète.
        item = (await stack.work.snapshot()).items[0]
        await stack.events.publish(ProtocolEnvelope(message_type=CORE_WORK_UPDATED, payload={"store_id": stack.work.store_id, "revision": item.revision, "previous_status": None, "item": item.to_payload()}))
        await settled(stack.projector)
        assert await stack.projector._reconcile("test")
        after = await stack.snapshot()
    assert after == before and after.revision == before.revision
    assert stack.projector.stats.stale_events >= 1 and stack.projector.stats.refused == 0


async def test_a_revision_gap_from_a_saturated_queue_is_reconciled_without_eviction():
    repository = MemoryRepository()
    repository.commit_delay = 0.01
    async with Stack(repository=repository, queue_size=2) as stack:
        for index in range(12):
            await stack.work.observe(obs(f"t{index}", label=f"tâche {index}"))
        for index in range(12):
            await stack.work.observe(obs(f"t{index}", WorkStatus.COMPLETED, at=1))
        await settled(stack.projector)
        snapshot = await stack.snapshot()
    assert ids(snapshot) == {f"claude:t{index}" for index in range(12)}
    assert {item.exec_state for item in snapshot.objects} == {ExecState.COMPLETED}
    assert stack.events.dropped_total > 0 and stack.events.evicted_total == 0
    assert stack.projector.stats.gaps >= 1
    reasons = [data["reason"] for _, data in stack.diagnostics.kinds(SCENE_PROJECTION_RECONCILED_KIND)]
    assert reasons[0] == "start" and "revision_gap" in reasons


class SwitchableWork:
    """Source de travail dont on remplace le magasin : réinitialisation du travail Core."""

    def __init__(self, store: WorkStateStore) -> None:
        self.store = store

    @property
    def store_id(self) -> str:
        return self.store.store_id

    async def snapshot(self):
        return await self.store.snapshot()


async def test_a_new_work_store_is_reconciled_without_deleting_existing_stars():
    stack = Stack()
    source = SwitchableWork(stack.work)
    stack.projector = SceneProjector(work=source, scene=stack.scene, events=stack.events, diagnostics=stack.diagnostics, retry_min_s=0.01)
    async with stack:
        await stack.observe(obs("old"), obs("kept"))
        source.store = WorkStateStore(events=stack.events, diagnostics=stack.diagnostics)
        await source.store.observe(obs("kept", WorkStatus.COMPLETED, at=1))
        await source.store.observe(obs("new"))
        await settled(stack.projector)
        snapshot = await stack.snapshot()
    assert ids(snapshot) == {"claude:old", "claude:kept", "claude:new"}
    assert snapshot.get_object("claude:old").exec_state is ExecState.RUNNING  # marquage au redémarrage : Slice 10
    assert snapshot.get_object("claude:kept").exec_state is ExecState.COMPLETED
    assert stack.projector.stats.store_changes >= 1
    assert "store_changed" in [data["reason"] for _, data in stack.diagnostics.kinds(SCENE_PROJECTION_RECONCILED_KIND)]


async def test_per_event_work_is_bounded_and_the_snapshot_is_read_only_when_a_star_is_born():
    async with Stack() as stack:
        calls = 0
        original = stack.work.snapshot

        async def counting():
            nonlocal calls
            calls += 1
            return await original()

        stack.work.snapshot = counting
        await stack.observe(obs("a"))
        assert calls == 1  # naissance : enfants arrivés avant
        await stack.observe(*(obs("a", at=index, activity=f"étape {index}") for index in range(1, 20)))
        await stack.observe(obs("bash", kind="shell"))
    assert calls == 1


# --- résilience ---------------------------------------------------------------


async def test_a_failing_scene_write_is_journaled_once_then_the_projection_recovers():
    repository = MemoryRepository()
    async with Stack(repository=repository) as stack:
        repository.fail_commit = SceneStoreError(SceneStoreErrorCode.STORAGE_IO, "disk is full")
        for index in range(5):
            await stack.work.observe(obs(f"t{index}"))

        async def outage_seen() -> bool:
            return len(stack.diagnostics.kinds(SCENE_PROJECTION_UNAVAILABLE_KIND)) >= 1

        await until_true(outage_seen, timeout=30)
        assert (await stack.snapshot()).objects == ()
        assert stack.scene.availability.state is SceneState.READY
        assert len(stack.diagnostics.kinds(SCENE_PROJECTION_UNAVAILABLE_KIND)) == 1

        repository.fail_commit = None
        await settled(stack.projector)
        snapshot = await stack.snapshot()
        assert stack.projector.running
    assert ids(snapshot) == {f"claude:t{index}" for index in range(5)}
    unavailable = stack.diagnostics.kinds(SCENE_PROJECTION_UNAVAILABLE_KIND)
    assert len(unavailable) == 1 and unavailable[0][0] == "warning" and unavailable[0][1]["code"] == "storage_io"
    restored = stack.diagnostics.kinds(SCENE_PROJECTION_RESTORED_KIND)
    assert len(restored) == 1 and restored[0][1]["suppressed"] >= 1


async def test_a_scene_refused_at_start_is_journaled_once_and_never_breaks_the_work_pipeline():
    repository = MemoryRepository()
    repository.fail_initialize = SceneStoreError(SceneStoreErrorCode.CORRUPTED, "bad file")
    stack = Stack(repository=repository)
    await stack.scene.start()
    stack.projector.start()
    other = stack.events.subscribe(max_queue=64)
    try:
        for index in range(20):
            await stack.work.observe(obs(f"t{index}"))

        async def retried() -> bool:
            return stack.projector.stats.outages > 1 and other.qsize() == 20

        await until_true(retried, timeout=30)
        assert stack.work.revision == 20 and other.qsize() == 20 and stack.events.evicted_total == 0
        assert stack.projector.running
        assert len(stack.diagnostics.kinds(SCENE_PROJECTION_UNAVAILABLE_KIND)) == 1
        assert stack.projector.stats.outages > 1
    finally:
        stack.events.unsubscribe(other)
        await stack.projector.stop()
        await stack.scene.close()


async def test_an_unexpected_projection_error_is_reported_once_and_skipped():
    async with Stack() as stack:
        original = stack.scene.apply
        failures = 2

        async def flaky(command):
            nonlocal failures
            if failures:
                failures -= 1
                raise RuntimeError("unexpected")
            return await original(command)

        stack.scene.apply = flaky
        await stack.observe(obs("a"), obs("b"), obs("c"))
        snapshot = await stack.snapshot()
    assert ids(snapshot) == {"claude:c"}
    failed = stack.diagnostics.kinds(SCENE_PROJECTION_FAILED_KIND)
    assert len(failed) == 1 and failed[0][0] == "error" and "RuntimeError" in failed[0][1]["error"]
    assert stack.projector.running is False  # arrêtée proprement par la sortie du contexte


async def test_the_projection_publishes_nothing_on_the_bus():
    async with Stack() as stack:
        published: list[str] = []
        original = stack.events.publish

        async def spy(event):
            published.append(event.message_type)
            await original(event)

        stack.events.publish = spy
        await stack.observe(obs("p"), obs("a", parent_external_id="p"), obs("a", WorkStatus.BLOCKED, at=1), obs("a", at=2))
        assert len((await stack.snapshot()).objects) == 3
    assert set(published) == {CORE_WORK_UPDATED} and len(published) == 4


async def test_stop_drains_what_is_already_queued_within_its_bound():
    repository = MemoryRepository()
    repository.commit_delay = 0.02
    stack = Stack(repository=repository)
    async with stack:
        for index in range(5):
            await stack.work.observe(obs(f"t{index}"))
        await stack.projector.stop()  # sans attendre : ces fins étaient déjà en file
        assert ids(await stack.snapshot()) == {f"claude:t{index}" for index in range(5)}

    slow = MemoryRepository()
    slow.commit_delay = 0.5
    bounded = Stack(repository=slow, stop_drain_s=0.1)
    async with bounded:
        for index in range(5):
            await bounded.work.observe(obs(f"t{index}"))
        loop = asyncio.get_running_loop()
        started = loop.time()
        await bounded.projector.stop()
        assert loop.time() - started < 1.0  # borne de vidage, plus au plus une écriture en vol
        assert len((await bounded.snapshot()).objects) < 5


# --- saturation (QA F1) ----------------------------------------------------------


def nearly_full(free: int) -> MemoryRepository:
    """Dépôt dont la scène tient déjà des artefacts du cerveau, à `free` places de la limite."""

    repository = MemoryRepository()
    fillers = tuple(
        SceneObject(f"art-{index:03d}", SceneObjectKind.ARTIFACT, "note", SceneConstraints(PlacedBy.BRAIN), SceneActor.BRAIN)
        for index in range(MAX_SCENE_OBJECTS - free)
    )
    repository.stored = SceneSnapshot(scene_id="scene-memory", objects=fillers)
    return repository


def space_tasks() -> list[asyncio.Task]:
    return [task for task in asyncio.all_tasks() if task.get_name() == "jarvis-scene-projector-space" and not task.done()]


async def archive(stack: Stack, *object_ids: str) -> None:
    for object_id in object_ids:
        update = await stack.scene.apply(SceneCommand(op=SceneOp.ARCHIVE, actor=SceneActor.USER, object_id=object_id))
        assert update.changed


async def until_true(predicate, *, timeout: float = 30.0) -> None:
    async def poll() -> None:
        while not await predicate():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(poll(), timeout)


async def test_a_full_scene_defers_stars_says_so_once_and_catches_up_oldest_first_after_archive():
    # Magasin de travail à 2 éléments : les travaux différés en sont élagués,
    # le rattrapage ne dépend pas de l'instantané de Core.
    async with Stack(repository=nearly_full(2), work_max_items=2) as stack:
        for index in range(6):
            await stack.observe(obs(f"a{index}", label=f"tâche {index}"), obs(f"a{index}", WorkStatus.COMPLETED, at=1))
        full = await stack.snapshot()
        assert len(full.objects) == MAX_SCENE_OBJECTS and stack.scene.capacity.saturated
        assert {f"claude:a{index}" for index in range(6)} & ids(full) == {"claude:a0", "claude:a1"}
        assert stack.projector.pending_count == 4
        assert len((await stack.work.snapshot()).items) == 2
        saturated = stack.diagnostics.kinds(SCENE_PROJECTION_SATURATED_KIND)
        assert saturated == [("warning", {"objects": MAX_SCENE_OBJECTS, "object_limit": MAX_SCENE_OBJECTS, "pending": 1, "suppressed_episodes": 0})]
        assert stack.diagnostics.kinds(SCENE_COMMAND_REFUSED_KIND) == []  # différé avant d'écrire : aucun refus

        # L'utilisateur archive 3 objets : 3 étoiles manquées reviennent, sans nouvel événement de travail.
        await archive(stack, "art-000", "art-001", "art-002")

        async def three_back() -> bool:
            return stack.projector.pending_count == 1

        await until_true(three_back)
        await settled(stack.projector)
        caught = await stack.snapshot()
        assert {"claude:a2", "claude:a3", "claude:a4"} <= ids(caught) and "claude:a5" not in ids(caught)
        assert caught.get_object("claude:a2").exec_state is ExecState.COMPLETED
        assert caught.get_object("claude:a2").payload.title == "tâche 2"
        assert stack.diagnostics.kinds(SCENE_PROJECTION_DESATURATED_KIND) == []

        await archive(stack, "art-003")

        async def all_back() -> bool:
            return stack.projector.pending_count == 0

        await until_true(all_back)
        await settled(stack.projector)
        assert "claude:a5" in ids(await stack.snapshot())
    assert stack.projector.stats.caught_up == 4
    desaturated = stack.diagnostics.kinds(SCENE_PROJECTION_DESATURATED_KIND)
    assert len(desaturated) == 1 and desaturated[0][0] == "info"
    assert desaturated[0][1]["dropped"] == 0 and desaturated[0][1]["deferred"] >= 4
    assert len(stack.diagnostics.kinds(SCENE_PROJECTION_SATURATED_KIND)) == 1


async def test_a_deferred_signal_and_its_parent_link_are_restored_when_space_frees():
    async with Stack(repository=nearly_full(2)) as stack:
        await stack.observe(obs("parent"), obs("running"))
        await stack.observe(obs("child", parent_external_id="parent"), obs("running", WorkStatus.FAILED, at=1, error_class="boom"))
        full = await stack.snapshot()
        assert "claude:child" not in ids(full) and signal_object_id("claude:running") not in ids(full)
        assert stack.projector.pending_count == 2

        await archive(stack, "art-000", "art-001")

        async def restored() -> bool:
            return stack.projector.pending_count == 0

        await until_true(restored)
        await settled(stack.projector)
        snapshot = await stack.snapshot()
    assert is_live_signal(snapshot, signal_object_id("claude:running"))
    assert snapshot.get_relation(parent_relation_id("claude:child")).from_id == "claude:parent"


async def test_the_pending_set_is_bounded_and_forgets_the_oldest_with_one_warning():
    async with Stack(repository=nearly_full(0), work_max_items=2, max_pending=3) as stack:
        for index in range(5):
            await stack.observe(obs(f"a{index}"), obs(f"a{index}", WorkStatus.COMPLETED, at=1))
        assert stack.projector.pending_count == 3 and stack.projector.stats.pending_dropped == 2
        assert [level for level, _ in stack.diagnostics.kinds(SCENE_PROJECTION_PENDING_OVERFLOW_KIND)] == ["warning"]

        await archive(stack, *(f"art-{index:03d}" for index in range(5)))

        async def drained() -> bool:
            return stack.projector.pending_count == 0

        await until_true(drained)
        await settled(stack.projector)
        snapshot = await stack.snapshot()
    assert {f"claude:a{index}" for index in range(5)} & ids(snapshot) == {"claude:a2", "claude:a3", "claude:a4"}
    (_, desaturated), = stack.diagnostics.kinds(SCENE_PROJECTION_DESATURATED_KIND)
    assert desaturated["dropped"] == 2


async def test_a_pending_work_keeps_its_rank_when_it_changes_and_the_oldest_comes_back_first():
    async with Stack(repository=nearly_full(0)) as stack:
        await stack.observe(obs("first"), obs("second"))
        await stack.observe(obs("second", at=1, activity="avance"), obs("first", at=2, activity="avance aussi"))
        assert stack.projector.pending_count == 2
        await archive(stack, "art-000")

        async def one_back() -> bool:
            return stack.projector.pending_count == 1

        await until_true(one_back)
        await settled(stack.projector)
        snapshot = await stack.snapshot()
    assert "claude:first" in ids(snapshot) and "claude:second" not in ids(snapshot)
    assert snapshot.get_object("claude:first").exec_state is ExecState.RUNNING


async def test_running_work_takes_a_freed_slot_before_a_backlog_of_finished_work():
    """QA O1 : Décision 4, un sous-agent en cours devient une étoile avant l'arriéré terminé."""

    async with Stack(repository=nearly_full(0), work_max_items=3) as stack:
        for index in range(4):
            await stack.observe(obs(f"done{index}"), obs(f"done{index}", WorkStatus.COMPLETED, at=1))
        await stack.observe(obs("fresh", at=2))
        assert stack.projector.pending_count == 5
        await archive(stack, "art-000")

        async def one_created() -> bool:
            return stack.projector.pending_count == 4

        await until_true(one_created)
        await settled(stack.projector)
        snapshot = await stack.snapshot()
        assert "claude:fresh" in ids(snapshot)
        assert not {f"claude:done{index}" for index in range(4)} & ids(snapshot)
        # Puis les terminés, plus anciens d'abord.
        await archive(stack, "art-001")

        async def two_created() -> bool:
            return stack.projector.pending_count == 3

        await until_true(two_created)
        assert "claude:done0" in ids(await stack.snapshot())


async def test_a_new_running_event_is_projected_before_the_finished_backlog_catches_up():
    async with Stack(repository=nearly_full(0), work_max_items=3) as stack:
        await stack.observe(obs("old"), obs("old", WorkStatus.COMPLETED, at=1))
        assert stack.projector.pending_count == 1
        # Place libérée sans que la veille ne le voie encore, puis un nouveau sous-agent arrive.
        stack.projector._stopping = True  # veille inerte pour ce test
        await stack.projector._stop_watch()
        await archive(stack, "art-000")
        await stack.observe(obs("new", at=2))
        snapshot = await stack.snapshot()
    assert "claude:new" in ids(snapshot) and "claude:old" not in ids(snapshot)


async def test_the_pending_bound_drops_the_oldest_finished_work_before_active_work():
    async with Stack(repository=nearly_full(0), work_max_items=4, max_pending=2) as stack:
        await stack.observe(obs("active"))
        await stack.observe(obs("done"), obs("done", WorkStatus.COMPLETED, at=1))
        await stack.observe(obs("third"))
        assert list(key[1] for key in stack.projector._pending) == ["active", "third"]
        assert stack.projector.stats.pending_dropped == 1


async def test_the_episode_closes_when_the_last_pending_entry_fails_and_the_next_one_is_announced():
    """QA R3 : attente vidée par un échec de rattrapage = fin d'épisode, veille arrêtée."""

    async with Stack(repository=nearly_full(0)) as stack:
        await stack.observe(obs("only"))
        original = stack.projector._project_item

        async def boom(item):
            if item.external_id == "only":
                raise RuntimeError("qa boom")
            return await original(item)

        stack.projector._project_item = boom
        await archive(stack, "art-000")

        async def emptied() -> bool:
            return stack.projector.pending_count == 0

        await until_true(emptied)
        await settled(stack.projector)
        stack.projector._project_item = original
        assert stack.projector._saturation is None

        async def watcher_gone() -> bool:
            return space_tasks() == []

        await until_true(watcher_gone, timeout=30)
        assert len(stack.diagnostics.kinds(SCENE_PROJECTION_DESATURATED_KIND)) == 1

        await stack.observe(obs("fill"), obs("next"))
        assert stack.projector.pending_count == 1
    assert len(stack.diagnostics.kinds(SCENE_PROJECTION_SATURATED_KIND)) == 2  # intervalle 0 : pas de limitation ici


async def test_saturation_warnings_are_throttled_across_archive_one_create_one_cycles():
    """QA R2 : à la limite, un épisode par sous-agent ; au plus un avertissement par intervalle."""

    clock = [1_000.0]
    async with Stack(
        repository=nearly_full(0), saturation_warning_interval_s=600, monotonic=lambda: clock[0]
    ) as stack:
        for cycle in range(5):
            await stack.observe(obs(f"n{cycle}"))
            await archive(stack, f"art-{cycle:03d}")

            async def caught() -> bool:
                return stack.projector.pending_count == 0

            await until_true(caught)
            await settled(stack.projector)
            clock[0] += 60

        async def watcher_gone() -> bool:
            return space_tasks() == []

        await until_true(watcher_gone, timeout=30)  # la veille s'arrête à chaque fin d'épisode
        clock[0] += 600
        await stack.observe(obs("late"))
    saturated = stack.diagnostics.kinds(SCENE_PROJECTION_SATURATED_KIND)
    assert [data["suppressed_episodes"] for _, data in saturated] == [0, 4]
    # La fin n'est dite que pour les épisodes annoncés.
    assert len(stack.diagnostics.kinds(SCENE_PROJECTION_DESATURATED_KIND)) == 1


async def test_a_scene_full_refusal_raced_by_another_writer_is_deferred_too():
    async with Stack(repository=nearly_full(1)) as stack:
        original = stack.scene.apply
        raced = False

        async def racing(command):
            nonlocal raced
            if not raced and command.actor is SceneActor.RUNTIME and command.op is SceneOp.UPSERT_OBJECT:
                raced = True  # l'utilisateur prend la dernière place entre le contrôle et l'écriture
                await original(SceneCommand(
                    op=SceneOp.UPSERT_OBJECT, actor=SceneActor.USER, object_id="note-last",
                    fields=SceneObjectFields(kind=SceneObjectKind.ARTIFACT, category="note"),
                ))
            return await original(command)

        stack.scene.apply = racing
        await stack.observe(obs("a"))
        assert raced and stack.projector.pending_count == 1 and "claude:a" not in ids(await stack.snapshot())
        assert len(stack.diagnostics.kinds(SCENE_PROJECTION_SATURATED_KIND)) == 1
        await archive(stack, "note-last")

        async def back() -> bool:
            return stack.projector.pending_count == 0

        await until_true(back)
        assert "claude:a" in ids(await stack.snapshot())


async def test_space_is_rechecked_periodically_even_without_a_scene_revision():
    async with Stack(repository=nearly_full(0), saturation_retry_s=0.05) as stack:
        await stack.observe(obs("late"))
        assert stack.projector.pending_count == 1
        # Place libérée sans révision visible par la veille (magasin modifié en
        # dessous) : seul le contrôle périodique peut la voir.
        stack.scene._snapshot = SceneSnapshot(
            scene_id="scene-memory", revision=stack.scene._snapshot.revision, objects=stack.scene._snapshot.objects[1:]
        )
        stack.repository.stored = stack.scene._snapshot

        async def created() -> bool:
            return stack.projector.pending_count == 0

        await until_true(created)
        assert "claude:late" in ids(await stack.snapshot())


# --- arrêt de Core ------------------------------------------------------------


class BlockingWorker:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def execute(self, job):
        self.started.set()
        await asyncio.Event().wait()
        return {}

    async def cancel(self, job_id):
        return None


async def test_core_stop_stops_the_projection_before_closing_the_scene_and_lands_job_ends(tmp_path):
    diagnostics = RecordingDiagnostics()
    worker = BlockingWorker()
    core = JarvisCoreApplication(data_root=tmp_path / "data", workers={"demo": worker}, diagnostics=diagnostics)
    await core.start()
    job = await core.jobs.submit(Job(kind="demo", payload={}))
    star_id = star_object_id("job", job.id)
    await wait_for_state(core, star_id, ExecState.RUNNING)

    await core.stop()

    assert core.health.status == "stopped"
    assert core.scene_projector.running is False and core.scene.availability.state is SceneState.CLOSED
    assert diagnostics.kinds(SCENE_PROJECTION_UNAVAILABLE_KIND) == []
    assert diagnostics.kinds(SCENE_PROJECTION_FAILED_KIND) == []
    repository = SQLiteSceneRepository(tmp_path / "data" / "state" / "scene.sqlite3")
    try:
        await repository.initialize()
        persisted = await repository.load()
    finally:
        await repository.close()
    # La fin posée par l'arrêt des jobs a atteint la scène avant sa fermeture.
    assert persisted.get_object(star_id).exec_state is ExecState.CANCELLED


async def test_no_space_watcher_survives_core_stop_even_with_deferrals_during_the_drain(tmp_path):
    """QA R1 (scénario `drain`) : des fins publiées pendant l'arrêt sont différées, sans veille orpheline."""

    core = JarvisCoreApplication(data_root=tmp_path / "data", scene_repository=nearly_full(0))
    await core.start()
    original_stop = core.jobs.stop

    async def jobs_stop() -> bool:
        for index in range(30):
            await core.work_state.observe(obs(f"d{index}"))
        return await original_stop()

    core.jobs.stop = jobs_stop
    # Une veille déjà vivante avant l'arrêt (création différée) doit aussi s'éteindre.
    await core.work_state.observe(obs("before-stop"))
    await settled(core.scene_projector)
    assert len(space_tasks()) == 1
    await core.stop()
    await asyncio.sleep(0)
    assert space_tasks() == [] and core.scene_projector._watch is None
    assert core.scene.availability.state is SceneState.CLOSED


@pytest.mark.parametrize("failing", ["back_brain", "jobs"])
async def test_every_early_return_of_core_stop_still_stops_the_projection_and_closes_the_scene(tmp_path, monkeypatch, failing):
    diagnostics = RecordingDiagnostics()
    core = JarvisCoreApplication(data_root=tmp_path / "data", diagnostics=diagnostics)
    await core.start()
    await core.work_state.observe(obs("a"))

    async def refuse() -> bool:
        return False

    monkeypatch.setattr(getattr(core, failing), "stop", refuse)
    await core.stop()

    assert core.health.status in {"state_persistence_unknown", "cleanup_unknown"}
    assert core.scene_projector.running is False and core.scene.availability.state is SceneState.CLOSED
    await core.work_state.observe(obs("a", WorkStatus.FAILED, at=1, error_class="late"))
    await asyncio.sleep(0.05)
    assert diagnostics.kinds(SCENE_PROJECTION_UNAVAILABLE_KIND) == []
    await core.state.close()


async def test_core_stop_raising_in_back_brain_still_closes_the_scene(tmp_path, monkeypatch):
    core = JarvisCoreApplication(data_root=tmp_path / "data")
    await core.start()

    async def explode() -> bool:
        raise RuntimeError("back brain stop failed")

    monkeypatch.setattr(core.back_brain, "stop", explode)
    with pytest.raises(RuntimeError):
        await core.stop()
    assert core.scene_projector.running is False and core.scene.availability.state is SceneState.CLOSED
    await core.state.close()


# --- identifiants --------------------------------------------------------------


def test_object_ids_are_readable_bounded_deterministic_and_collision_safe():
    assert star_object_id("claude", "toolu_01") == "claude:toolu_01"
    assert signal_object_id("claude:toolu_01") == "attention!claude:toolu_01"
    assert parent_relation_id("claude:toolu_01") == "parent_of!claude:toolu_01"

    long_a, long_b = "x" * 127 + "a", "x" * 127 + "b"
    first, second = star_object_id("claude", long_a), star_object_id("claude", long_b)
    assert first != second and first == star_object_id("claude", long_a)
    assert len(first) <= MAX_ID_CHARS and first.startswith("claude#") and ":xxxx" in first
    # Une forme courte qui imite une forme hachée garde sa tête de jeton : pas de collision.
    assert star_object_id("claude", first.split(":", 1)[1]) != first
    trailing = star_object_id("job", "y" * 60 + " " * 80)
    assert trailing == trailing.strip() and len(trailing) <= MAX_ID_CHARS

    for star in (first, star_object_id("claude", "z" * 128), star_object_id("attention", "x")):
        signal, relation = signal_object_id(star), parent_relation_id(star)
        assert len(signal) <= MAX_ID_CHARS and len(relation) <= MAX_ID_CHARS
        assert signal != star and relation != signal
    # Une source nommée « attention » ne produit pas l'identifiant d'un signal.
    assert star_object_id("attention", "claude:a") != signal_object_id("claude:a")


async def test_long_external_ids_and_hostile_text_are_projected_without_crashing():
    async with Stack() as stack:
        long_id = "toolu_" + "é" * 122
        await stack.observe(
            obs(long_id, label="é" * 160),
            obs("child", parent_external_id=long_id, summary="a\x00b\x1b[31m\rc"),
            obs(long_id, WorkStatus.FAILED, at=1, error_class="boom", summary="x" * 1_000),
        )
        snapshot = await stack.snapshot()
    star_id = star_object_id("claude", long_id)
    assert len(star_id) <= MAX_ID_CHARS
    assert snapshot.get_object(star_id).payload.title == "é" * 160
    assert snapshot.get_object("claude:child").payload.summary == "a b [31m\nc"
    assert len(snapshot.get_object(signal_object_id(star_id)).payload.summary) == 240
    assert snapshot.get_relation(parent_relation_id("claude:child")).from_id == star_id
    assert stack.projector.stats.failures == 0

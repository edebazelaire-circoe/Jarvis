"""Réconciliation de la scène au redémarrage de Core (handoff jarvis-constellation-scene-runtime, Slice 10).

Pièces réelles : `WorkStateStore`, `CoreEventBus`, `SceneService` (dépôt en
mémoire ou SQLite), `SceneProjector`, et `JarvisCoreApplication` pour les jobs.
Ce qui doit tenir :

- au démarrage, seules les étoiles d'exécution runtime non terminées passent
  à `unknown` ; rien d'autre ne bouge (terminées, signaux, cerveau,
  utilisateur, artefacts, pierres tombales, géométrie, épingle, visibilité) ;
- une observation du même `(source, external_id)` rend l'état réel, avant ou
  après la fin de la grâce (le signal est alors retiré comme d'habitude) ;
- à la fin de la grâce : `interrupted` et un seul signal
  `core_restarted_unobserved` par étoile, signal d'abord ;
- scène pleine : l'interruption attend une place, derrière le travail actif ;
- l'arrêt annule la minuterie ; un arrêt brutal pendant la grâce (ou entre
  le signal et l'étoile) remarque sans second signal ;
- un job terminé en base dit sa vraie issue, un job repris par
  `JobService.recover` est interrompu avec son signal.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from jarvis.adapters.sqlite_scene import SQLiteSceneRepository
from jarvis.core.scene_projector import (
    CORE_RESTARTED_UNOBSERVED,
    RESTART_GRACE_S,
    SCENE_PROJECTION_DESATURATED_KIND,
    SCENE_PROJECTION_FAILED_KIND,
    SCENE_PROJECTION_SATURATED_KIND,
    SCENE_RESTART_GRACE_EXPIRED_KIND,
    SCENE_RESTART_MARKED_KIND,
    SCENE_RESTART_STAR_KIND,
    SCENE_SIGNAL_RAISED_KIND,
    SCENE_SIGNAL_RETIRED_KIND,
    SceneProjector,
    signal_object_id,
    star_object_id,
)
from jarvis.core.scene_service import SCENE_COMMAND_REFUSED_KIND, SceneState
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.scene import (
    MAX_SCENE_OBJECTS,
    ExecState,
    PlacedBy,
    RelationKind,
    SceneActor,
    SceneCommand,
    SceneCommandOutcome,
    SceneConstraints,
    SceneGeometry,
    SceneObject,
    SceneObjectFields,
    SceneObjectKind,
    SceneOp,
    ScenePayload,
    SceneRefusal,
    SceneRelation,
    SceneSnapshot,
    Visibility,
    WorkRef,
    apply_scene_command,
    is_live_signal,
)
from jarvis.domain.v2 import Job, JobStatus
from jarvis.domain.work_state import WorkStatus
from tests.unit.test_scene_projector import Stack, archive, obs, settled, until_true
from tests.unit.test_scene_service import MemoryRepository, RecordingDiagnostics

GRACE_TASK = "jarvis-scene-restart-grace"


# ------------------------------------------------------------------ fabrique


def star(object_id: str, state: ExecState, *, kind: SceneObjectKind = SceneObjectKind.AGENT, **extra) -> SceneObject:
    source, external_id = object_id.split(":", 1)
    extra.setdefault("constraints", SceneConstraints(placed_by=PlacedBy.RUNTIME))
    return SceneObject(
        object_id=object_id, kind=kind, category=kind.value, origin=SceneActor.RUNTIME, exec_state=state,
        work_ref=WorkRef(source=source, external_id=external_id), payload=ScenePayload(title=f"tâche {external_id}"),
        layer=100, **extra,
    )


def signal(star_id: str, state: ExecState, title: str) -> tuple[SceneObject, SceneRelation]:
    source, external_id = star_id.split(":", 1)
    signal_id = signal_object_id(star_id)
    item = SceneObject(
        object_id=signal_id, kind=SceneObjectKind.ATTENTION, category=state.value, origin=SceneActor.RUNTIME,
        constraints=SceneConstraints(placed_by=PlacedBy.RUNTIME), exec_state=state, layer=300,
        work_ref=WorkRef(source=source, external_id=external_id), payload=ScenePayload(title=title),
    )
    return item, SceneRelation(signal_id, RelationKind.EXPLAINS, signal_id, star_id)


def seeded_scene() -> SceneSnapshot:
    """Une scène d'une vie précédente : tout ce que le marquage doit laisser tel quel, et ce qu'il marque."""

    blocked_signal, blocked_link = signal("claude:blk", ExecState.BLOCKED, "blocked")
    failed_signal, failed_link = signal("claude:fail", ExecState.FAILED, "TimeoutError")
    objects = (
        star("claude:run", ExecState.RUNNING, geometry=SceneGeometry(10, 10, 6, 6),
             constraints=SceneConstraints(placed_by=PlacedBy.USER, pinned_by_user=True)),
        star("claude:pend", ExecState.PENDING),
        star("claude:blk", ExecState.BLOCKED),
        blocked_signal,
        star("claude:hid", ExecState.RUNNING, visibility=Visibility.HIDDEN),
        star("claude:done", ExecState.COMPLETED),
        star("claude:fail", ExecState.FAILED),
        failed_signal,
        star("job:j1", ExecState.RUNNING, kind=SceneObjectKind.JOB),
        SceneObject(object_id="brain-artifact-1", kind=SceneObjectKind.ARTIFACT, category="research", origin=SceneActor.BRAIN,
                    constraints=SceneConstraints(placed_by=PlacedBy.BRAIN), layer=120, payload=ScenePayload(title="Liens")),
        SceneObject(object_id="user-note", kind=SceneObjectKind.ATTENTION, category="note", origin=SceneActor.USER,
                    constraints=SceneConstraints(placed_by=PlacedBy.USER), layer=300, payload=ScenePayload(title="à voir")),
    )
    relations = (
        blocked_link,
        failed_link,
        SceneRelation("brain-explains-1", RelationKind.EXPLAINS, "brain-artifact-1", "claude:done"),
    )
    return SceneSnapshot(scene_id="scene-memory", revision=40, objects=objects, relations=relations, archived_ids=("claude:gone",))


MARKED = ("claude:run", "claude:pend", "claude:blk", "claude:hid", "job:j1")


def repository_with(snapshot: SceneSnapshot) -> MemoryRepository:
    repository = MemoryRepository()
    repository.stored = snapshot
    return repository


class RestartStack(Stack):
    """`Stack` démarrée comme Core : scène, marquage de redémarrage, puis projection."""

    async def __aenter__(self) -> RestartStack:
        await self.scene.start()
        await self.projector.reconcile_restart()
        self.projector.start()
        await settled(self.projector)
        return self


def grace_tasks() -> list[asyncio.Task]:
    return [task for task in asyncio.all_tasks() if task.get_name() == GRACE_TASK and not task.done()]


async def grace_expired(stack: Stack) -> None:
    async def expired() -> bool:
        return bool(stack.diagnostics.kinds(SCENE_RESTART_GRACE_EXPIRED_KIND))

    await until_true(expired)
    await settled(stack.projector)


def unobserved_signals(snapshot: SceneSnapshot) -> list[SceneObject]:
    return [item for item in snapshot.objects if item.kind is SceneObjectKind.ATTENTION and item.payload.title == CORE_RESTARTED_UNOBSERVED]


# ------------------------------------------------------------------ marquage


async def test_core_start_marks_only_non_terminal_runtime_execution_stars_unknown():
    before = seeded_scene()
    async with RestartStack(repository=repository_with(before)) as stack:
        after = await stack.snapshot()
        assert stack.projector.restart_tracked_count == len(MARKED)
        assert len(grace_tasks()) == 1

    assert after.revision == before.revision + len(MARKED)  # une révision par étoile marquée, rien d'autre
    for item in before.objects:
        now = after.get_object(item.object_id)
        if item.object_id in MARKED:
            assert now == replace(item, exec_state=ExecState.UNKNOWN), item.object_id
        else:
            assert now == item, item.object_id
    assert after.relations == before.relations and after.archived_ids == before.archived_ids
    assert [item.object_id for item in after.objects] == [item.object_id for item in before.objects]
    assert stack.diagnostics.kinds(SCENE_RESTART_MARKED_KIND) == [("info", {
        "marked": 5, "already_unknown": 0, "tracked": 5, "terminal_untouched": 2, "job_outcomes": 0,
        "grace_s": RESTART_GRACE_S, "sample": sorted(MARKED),
    })]
    per_star = stack.diagnostics.kinds(SCENE_RESTART_STAR_KIND)
    assert {data["object_id"] for _, data in per_star} == set(MARKED) and {level for level, _ in per_star} == {"debug"}
    assert stack.diagnostics.kinds(SCENE_COMMAND_REFUSED_KIND) == []
    assert stack.diagnostics.kinds(SCENE_SIGNAL_RAISED_KIND) == []
    assert grace_tasks() == []  # l'arrêt a annulé la minuterie


def test_runtime_may_write_unknown_on_its_own_execution_star_and_nobody_else_may():
    scene = SceneSnapshot(scene_id="s", objects=(
        star("claude:run", ExecState.RUNNING),
        SceneObject(object_id="brain-note", kind=SceneObjectKind.WINDOW, category="note", origin=SceneActor.BRAIN,
                    constraints=SceneConstraints(placed_by=PlacedBy.BRAIN), layer=220),
    ))

    def patch(actor: SceneActor, object_id: str):
        return apply_scene_command(scene, SceneCommand(
            op=SceneOp.PATCH_OBJECT, actor=actor, object_id=object_id, fields=SceneObjectFields(exec_state=ExecState.UNKNOWN)))

    applied = patch(SceneActor.RUNTIME, "claude:run")
    assert applied.outcome is SceneCommandOutcome.APPLIED and applied.snapshot.get_object("claude:run").exec_state is ExecState.UNKNOWN
    assert patch(SceneActor.BRAIN, "claude:run").reason is SceneRefusal.EXECUTION_TRUTH
    assert patch(SceneActor.USER, "claude:run").reason is SceneRefusal.EXECUTION_TRUTH
    assert patch(SceneActor.RUNTIME, "brain-note").reason is SceneRefusal.RUNTIME_KIND


# ------------------------------------------------------------------ réobservation et grâce


async def test_a_reobserved_star_gets_its_real_state_back_and_is_never_interrupted():
    async with RestartStack(repository=repository_with(seeded_scene()), restart_grace_s=0.3) as stack:
        await stack.observe(
            obs("run", label="tâche run"),
            obs("blk", WorkStatus.BLOCKED, label="tâche blk", activity="attend une réponse"),
            obs("blk", label="tâche blk", at=1),
            obs("pend", WorkStatus.INTERRUPTED, at=1, error_class="process_stopped"),
        )
        restored = await stack.snapshot()
        await grace_expired(stack)
        final = await stack.snapshot()

    assert restored.get_object("claude:run").exec_state is ExecState.RUNNING
    assert restored.get_object("claude:blk").exec_state is ExecState.RUNNING
    assert not is_live_signal(restored, signal_object_id("claude:blk"))  # retiré comme d'habitude
    # Revue interrompue par son producteur (redémarrage du CLI) : son signal à elle, pas celui de la grâce.
    assert final.get_object(signal_object_id("claude:pend")).payload.title == "process_stopped"
    assert final.get_object("claude:run").exec_state is ExecState.RUNNING
    assert final.get_object("claude:run").constraints.pinned_by_user is True
    unobserved = {item.work_ref.external_id for item in unobserved_signals(final)}
    assert unobserved == {"hid", "j1"}
    assert stack.diagnostics.kinds(SCENE_RESTART_GRACE_EXPIRED_KIND) == [("info", {
        "tracked": 5, "reobserved": 3, "interrupted": 2, "deferred": 0, "left": 0, "failed": 0, "grace_s": 0.3,
    })]


async def test_grace_expiry_interrupts_each_unobserved_star_with_one_signal_first():
    before = seeded_scene()
    async with RestartStack(repository=repository_with(before), restart_grace_s=0.05) as stack:
        await grace_expired(stack)
        after = await stack.snapshot()
        revision_after_expiry = after.revision
        assert grace_tasks() == []

    for star_id in MARKED:
        assert after.get_object(star_id).exec_state is ExecState.INTERRUPTED, star_id
        signal_id = signal_object_id(star_id)
        attention = after.get_object(signal_id)
        assert (attention.kind, attention.origin, attention.category, attention.exec_state) == (
            SceneObjectKind.ATTENTION, SceneActor.RUNTIME, "interrupted", ExecState.INTERRUPTED)
        assert attention.payload.title == CORE_RESTARTED_UNOBSERVED and attention.payload.summary
        assert attention.work_ref == after.get_object(star_id).work_ref
        assert is_live_signal(after, signal_id)
    assert len(unobserved_signals(after)) == len(MARKED)  # un par étoile, le signal « bloqué » repris sur place
    assert len([item for item in after.objects if item.kind is SceneObjectKind.ATTENTION]) == len(MARKED) + 2
    # Rien d'autre n'a bougé.
    for object_id in ("claude:done", "claude:fail", signal_object_id("claude:fail"), "brain-artifact-1", "user-note"):
        assert after.get_object(object_id) == before.get_object(object_id)
    assert after.get_object("claude:run").geometry == SceneGeometry(10, 10, 6, 6)
    assert after.get_object("claude:hid").visibility is Visibility.HIDDEN
    assert after.archived_ids == ("claude:gone",)
    # Signal d'abord : chaque interruption = signal puis étoile, dans cet ordre de révisions.
    raised = stack.diagnostics.kinds(SCENE_SIGNAL_RAISED_KIND)
    assert sorted(data["target_id"] for _, data in raised) == sorted(set(MARKED) - {"claude:blk"})  # le bloqué était déjà vivant
    assert {data["error_class"] for _, data in raised} == {CORE_RESTARTED_UNOBSERVED}
    assert revision_after_expiry == before.revision + len(MARKED) + 2 * len(MARKED)
    assert stack.diagnostics.kinds(SCENE_RESTART_GRACE_EXPIRED_KIND)[0][1]["interrupted"] == len(MARKED)


async def test_a_star_reobserved_after_the_grace_retires_its_signal():
    async with RestartStack(repository=repository_with(seeded_scene()), restart_grace_s=0.05) as stack:
        await grace_expired(stack)
        await stack.observe(obs("run", label="tâche run"))
        snapshot = await stack.snapshot()
    signal_id = signal_object_id("claude:run")
    assert snapshot.get_object("claude:run").exec_state is ExecState.RUNNING
    assert not is_live_signal(snapshot, signal_id)
    assert snapshot.get_object(signal_id).exec_state is ExecState.RUNNING
    assert [data["object_id"] for _, data in stack.diagnostics.kinds(SCENE_SIGNAL_RETIRED_KIND)] == [signal_id]


async def test_the_real_work_in_core_wins_at_grace_expiry_even_if_its_event_was_missed():
    async with RestartStack(repository=repository_with(seeded_scene()), restart_grace_s=0.2) as stack:
        # L'observation atteint Core mais pas la projection (événement perdu).
        stack.events.unsubscribe(stack.projector._queue)
        await stack.work.observe(obs("hid", WorkStatus.COMPLETED, label="tâche hid"))
        await grace_expired(stack)
        snapshot = await stack.snapshot()
    assert snapshot.get_object("claude:hid").exec_state is ExecState.COMPLETED
    assert snapshot.get_object(signal_object_id("claude:hid")) is None


async def test_an_archived_star_during_the_grace_is_left_alone():
    async with RestartStack(repository=repository_with(seeded_scene()), restart_grace_s=0.2) as stack:
        await archive(stack, "claude:pend")
        await grace_expired(stack)
        snapshot = await stack.snapshot()
    assert snapshot.is_archived("claude:pend") and snapshot.get_object(signal_object_id("claude:pend")) is None
    assert stack.diagnostics.kinds(SCENE_RESTART_GRACE_EXPIRED_KIND)[0][1]["left"] == 1
    assert stack.diagnostics.kinds(SCENE_COMMAND_REFUSED_KIND) == []


# ------------------------------------------------------------------ saturation


def full_scene_with_stars(*star_ids: str) -> MemoryRepository:
    stars = tuple(star(star_id, ExecState.RUNNING) for star_id in star_ids)
    fillers = tuple(
        SceneObject(f"art-{index:03d}", SceneObjectKind.ARTIFACT, "note", SceneConstraints(PlacedBy.BRAIN), SceneActor.BRAIN)
        for index in range(MAX_SCENE_OBJECTS - len(stars))
    )
    return repository_with(SceneSnapshot(scene_id="scene-memory", objects=stars + fillers))


async def test_a_full_scene_marks_without_slots_and_defers_expiry_signals_behind_active_work():
    async with RestartStack(repository=full_scene_with_stars("claude:a", "claude:b", "claude:c"), restart_grace_s=0.05) as stack:
        marked = await stack.snapshot()
        assert {marked.get_object(f"claude:{name}").exec_state for name in "abc"} == {ExecState.UNKNOWN}
        await stack.observe(obs("a", label="tâche a"))  # revue : pas de place requise
        await grace_expired(stack)
        await stack.observe(obs("new", label="nouvelle"))  # travail actif différé, arrivé après
        waiting = await stack.snapshot()
        # Signal d'abord : sans place, l'étoile reste « état inconnu ».
        assert waiting.get_object("claude:b").exec_state is ExecState.UNKNOWN
        assert waiting.get_object("claude:c").exec_state is ExecState.UNKNOWN
        assert waiting.get_object("claude:a").exec_state is ExecState.RUNNING
        assert stack.projector.pending_count == 3
        assert stack.diagnostics.kinds(SCENE_RESTART_GRACE_EXPIRED_KIND)[0][1]["deferred"] == 2
        assert len(stack.diagnostics.kinds(SCENE_PROJECTION_SATURATED_KIND)) == 1

        await archive(stack, "art-000", "art-001")
        await until_true(lambda: _pending_at_most(stack, 1))
        await settled(stack.projector)
        partial = await stack.snapshot()
        # Le travail actif passe d'abord, puis l'interruption la plus ancienne.
        assert partial.get_object("claude:new") is not None
        assert partial.get_object("claude:b").exec_state is ExecState.INTERRUPTED
        assert is_live_signal(partial, signal_object_id("claude:b"))
        assert partial.get_object("claude:c").exec_state is ExecState.UNKNOWN

        # Revue pendant l'attente : l'état réel remplace l'interruption en attente.
        await stack.observe(obs("c", WorkStatus.COMPLETED, label="tâche c"))
        final = await stack.snapshot()
        assert stack.projector.pending_count == 0

    assert final.get_object("claude:c").exec_state is ExecState.COMPLETED
    assert final.get_object(signal_object_id("claude:c")) is None
    assert stack.diagnostics.kinds(SCENE_COMMAND_REFUSED_KIND) == []
    assert len(stack.diagnostics.kinds(SCENE_PROJECTION_DESATURATED_KIND)) == 1


async def _pending_at_most(stack: Stack, count: int) -> bool:
    return stack.projector.pending_count <= count


async def test_a_deferred_expiry_signal_is_caught_up_when_space_frees():
    async with RestartStack(repository=full_scene_with_stars("claude:a"), restart_grace_s=0.05) as stack:
        await grace_expired(stack)
        assert (await stack.snapshot()).get_object("claude:a").exec_state is ExecState.UNKNOWN
        await archive(stack, "art-000")
        await until_true(lambda: _pending_at_most(stack, 0))
        await settled(stack.projector)
        snapshot = await stack.snapshot()
    assert snapshot.get_object("claude:a").exec_state is ExecState.INTERRUPTED
    assert snapshot.get_object(signal_object_id("claude:a")).payload.title == CORE_RESTARTED_UNOBSERVED
    assert stack.projector.stats.restart_interrupted == 1


# ------------------------------------------------------------------ arrêt, arrêt brutal, idempotence


async def test_stop_cancels_the_grace_timer_before_and_after_start():
    repository = repository_with(seeded_scene())
    stack = RestartStack(repository=repository, restart_grace_s=RESTART_GRACE_S)
    await stack.scene.start()
    await stack.projector.reconcile_restart()
    assert stack.projector.restart_marking_pending and grace_tasks() == []  # demandé : rien avant la boucle
    await stack.projector.stop()  # jamais démarrée
    assert grace_tasks() == []
    await stack.scene.close()

    async with RestartStack(repository=repository, restart_grace_s=RESTART_GRACE_S) as again:
        assert len(grace_tasks()) == 1
    assert grace_tasks() == [] and again.projector.running is False


async def test_a_crash_mid_grace_remarks_and_raises_each_signal_once(tmp_path):
    path = tmp_path / "scene.sqlite3"

    async def run(grace_s: float, *, expire: bool) -> Stack:
        stack = RestartStack(repository=SQLiteSceneRepository(path), restart_grace_s=grace_s)
        async with stack:
            if expire:
                await grace_expired(stack)
        return stack

    seed = Stack(repository=SQLiteSceneRepository(path))
    async with seed:
        for name in ("a", "b"):
            await seed.observe(obs(name, label=f"tâche {name}"))
    first = await run(RESTART_GRACE_S, expire=False)  # arrêt pendant la grâce
    assert first.diagnostics.kinds(SCENE_RESTART_MARKED_KIND)[0][1]["marked"] == 2

    second = await run(0.05, expire=True)
    assert second.diagnostics.kinds(SCENE_RESTART_MARKED_KIND)[0][1] | {"sample": []} == {
        "marked": 0, "already_unknown": 2, "tracked": 2, "terminal_untouched": 0, "job_outcomes": 0,
        "grace_s": 0.05, "sample": [],
    }
    assert len(second.diagnostics.kinds(SCENE_SIGNAL_RAISED_KIND)) == 2

    third = await run(0.05, expire=False)
    assert third.diagnostics.kinds(SCENE_RESTART_MARKED_KIND)[0][1]["tracked"] == 0
    assert third.diagnostics.kinds(SCENE_SIGNAL_RAISED_KIND) == []
    check = Stack(repository=SQLiteSceneRepository(path))
    async with check:
        snapshot = await check.snapshot()
    assert len(unobserved_signals(snapshot)) == 2
    assert {snapshot.get_object(f"claude:{name}").exec_state for name in "ab"} == {ExecState.INTERRUPTED}


async def test_a_crash_between_the_signal_and_the_star_write_never_doubles_the_signal():
    attention, link = signal("claude:a", ExecState.INTERRUPTED, CORE_RESTARTED_UNOBSERVED)
    attention = replace(attention, payload=ScenePayload(title=CORE_RESTARTED_UNOBSERVED,
                                                        summary="Core a redémarré et aucun producteur n'a redit ce travail pendant la grâce : il est considéré comme interrompu."))
    scene = SceneSnapshot(scene_id="scene-memory", objects=(star("claude:a", ExecState.UNKNOWN), attention), relations=(link,))
    async with RestartStack(repository=repository_with(scene), restart_grace_s=0.05) as stack:
        await grace_expired(stack)
        snapshot = await stack.snapshot()
    assert snapshot.get_object("claude:a").exec_state is ExecState.INTERRUPTED
    assert stack.diagnostics.kinds(SCENE_SIGNAL_RAISED_KIND) == []
    assert len(unobserved_signals(snapshot)) == 1 and snapshot.revision == 1  # seule l'étoile a été écrite


async def test_a_scene_unavailable_at_start_leaves_the_marking_to_the_loop():
    repository = repository_with(seeded_scene())
    stack = RestartStack(repository=repository, restart_grace_s=RESTART_GRACE_S)
    await stack.scene.start()
    real_snapshot = stack.scene.snapshot
    calls = 0

    async def failing_once():
        nonlocal calls
        calls += 1
        if calls == 1:
            from jarvis.ports.scene import SceneStoreErrorCode, SceneUnavailableError

            raise SceneUnavailableError(SceneStoreErrorCode.UNAVAILABLE, "scène indisponible (test)")
        return await real_snapshot()

    stack.scene.snapshot = failing_once
    await stack.projector.reconcile_restart()
    assert stack.diagnostics.kinds(SCENE_RESTART_MARKED_KIND) == []
    stack.projector.start()
    try:
        await settled(stack.projector)
        snapshot = await real_snapshot()
    finally:
        await stack.projector.stop()
        await stack.scene.close()
    assert {snapshot.get_object(star_id).exec_state for star_id in MARKED} == {ExecState.UNKNOWN}
    assert len(stack.diagnostics.kinds(SCENE_RESTART_MARKED_KIND)) == 1
    assert stack.diagnostics.kinds(SCENE_PROJECTION_FAILED_KIND) == []


# ------------------------------------------------------------------ jobs (Core réel)


class _Worker:
    async def execute(self, job):
        return {}

    async def cancel(self, job_id):
        return None


async def test_a_recovered_job_is_interrupted_with_its_signal_and_a_finished_job_keeps_its_outcome(tmp_path):
    data = tmp_path / "data"
    core0 = JarvisCoreApplication(data_root=data, workers={"demo": _Worker()})
    await core0.start()
    now = datetime.now(timezone.utc)
    running = Job(kind="demo", status=JobStatus.RUNNING, started_at=now)
    finished = Job(kind="demo", status=JobStatus.COMPLETED, started_at=now, completed_at=now, result={})
    failed = Job(kind="demo", status=JobStatus.FAILED, started_at=now, completed_at=now, error="TimeoutError: trop long")
    for job in (running, finished, failed):
        await core0.state.save_job(job)
        update = await core0.scene.apply(SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=SceneActor.RUNTIME, object_id=star_object_id("job", job.id),
                                                      fields=SceneObjectFields(kind=SceneObjectKind.JOB, category="job", exec_state=ExecState.RUNNING,
                                                                               work_ref=WorkRef(source="job", external_id=job.id))))
        assert update.changed
    await core0.stop()

    diagnostics = RecordingDiagnostics()
    core = JarvisCoreApplication(data_root=data, workers={"demo": _Worker()}, diagnostics=diagnostics, scene_restart_grace_s=0.2)
    await core.start()
    try:
        async def expired() -> bool:
            return bool(diagnostics.kinds(SCENE_RESTART_GRACE_EXPIRED_KIND))

        await until_true(expired)
        await settled(core.scene_projector)
        snapshot = await core.scene.snapshot()
    finally:
        await core.stop()

    assert grace_tasks() == []
    recovered = snapshot.get_object(star_object_id("job", running.id))
    assert recovered.exec_state is ExecState.INTERRUPTED
    assert snapshot.get_object(signal_object_id(recovered.object_id)).payload.title == "core_restarted"
    assert snapshot.get_object(star_object_id("job", finished.id)).exec_state is ExecState.COMPLETED
    assert snapshot.get_object(signal_object_id(star_object_id("job", finished.id))) is None
    assert snapshot.get_object(star_object_id("job", failed.id)).exec_state is ExecState.FAILED
    assert snapshot.get_object(signal_object_id(star_object_id("job", failed.id))).payload.title == "TimeoutError"
    assert unobserved_signals(snapshot) == []
    assert diagnostics.kinds(SCENE_RESTART_MARKED_KIND)[0][1]["job_outcomes"] == 2
    assert diagnostics.kinds(SCENE_RESTART_GRACE_EXPIRED_KIND)[0][1] | {"grace_s": 0} == {
        "tracked": 3, "reobserved": 3, "interrupted": 0, "deferred": 0, "left": 0, "failed": 0, "grace_s": 0,
    }


async def test_core_stop_during_the_grace_leaves_no_task_and_closes_the_scene(tmp_path):
    data = tmp_path / "data"
    core0 = JarvisCoreApplication(data_root=data)
    await core0.start()
    await core0.scene.apply(SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=SceneActor.RUNTIME, object_id="claude:a",
                                         fields=SceneObjectFields(kind=SceneObjectKind.AGENT, category="agent", exec_state=ExecState.RUNNING,
                                                                  work_ref=WorkRef(source="claude", external_id="a"))))
    await core0.stop()
    core = JarvisCoreApplication(data_root=data)
    await core.start()
    await until_true(lambda: _marking_done(core.scene_projector))
    assert len(grace_tasks()) == 1
    assert (await core.scene.snapshot()).get_object("claude:a").exec_state is ExecState.UNKNOWN
    await core.stop()
    assert grace_tasks() == [] and core.scene.availability.state is SceneState.CLOSED


async def test_observe_persisted_outcomes_only_speaks_for_finished_real_jobs(tmp_path):
    core = JarvisCoreApplication(data_root=tmp_path / "data", workers={"demo": _Worker()})
    await core.start()
    try:
        now = datetime.now(timezone.utc)
        jobs = {
            "done": Job(kind="demo", status=JobStatus.COMPLETED, started_at=now, completed_at=now),
            "odd": Job(kind="demo", status=JobStatus.FAILED, started_at=now, completed_at=now, error="Érreur: accentuée"),
            "cut": Job(kind="demo", status=JobStatus.INTERRUPTED, started_at=now, completed_at=now, error="core_restarted"),
            "stop": Job(kind="demo", status=JobStatus.CANCELLED, started_at=now, completed_at=now),
            "live": Job(kind="demo", status=JobStatus.RUNNING, started_at=now),
            "spec": Job(kind="back_brain", status=JobStatus.COMPLETED, started_at=now, completed_at=now,
                        payload={"scope": "speculative_analysis"}),
        }
        for job in jobs.values():
            await core.state.save_job(job)
        count = await core.jobs.observe_persisted_outcomes({**{job.id: None for job in jobs.values()}, "absent": None})
        items = {item.external_id: item for item in (await core.work_state.snapshot()).items}
    finally:
        await core.stop()
    assert count == 4  # ni le job en cours, ni le spéculatif, ni l'inconnu
    by_name = {name: items.get(job.id) for name, job in jobs.items()}
    assert (by_name["done"].status, by_name["done"].error_class) == (WorkStatus.COMPLETED, None)
    assert (by_name["odd"].status, by_name["odd"].error_class) == (WorkStatus.FAILED, "error")
    assert (by_name["cut"].status, by_name["cut"].error_class) == (WorkStatus.INTERRUPTED, "core_restarted")
    assert (by_name["stop"].status, by_name["stop"].error_class) == (WorkStatus.CANCELLED, None)
    assert by_name["live"] is None and by_name["spec"] is None


async def _marking_done(projector: SceneProjector) -> bool:
    return not projector.restart_marking_pending and projector.stats.reconciliations > 0


# ------------------------------------------------------------------ suivi final : disponibilité, boucle, work_id


class _SlowCommits(MemoryRepository):
    def __init__(self, snapshot: SceneSnapshot, delay: float) -> None:
        super().__init__()
        self.stored = snapshot
        self.commit_delay = delay


def running_scene(count: int) -> SceneSnapshot:
    return SceneSnapshot(scene_id="scene-memory", objects=tuple(star(f"claude:s{index}", ExecState.RUNNING) for index in range(count)))


@pytest.mark.parametrize("stars", [0, 60])
async def test_core_readiness_never_waits_for_the_marking(tmp_path, stars):
    repository = _SlowCommits(running_scene(stars), delay=0.05)  # 60 étoiles × 50 ms = 3 s de marquage
    core = JarvisCoreApplication(data_root=tmp_path / "data", scene_repository=repository, scene_restart_grace_s=RESTART_GRACE_S)
    loop = asyncio.get_running_loop()
    started = loop.time()
    await core.start()
    ready_after = loop.time() - started
    try:
        assert core.health.ready and ready_after < 1.0
        if stars:
            assert core.scene_projector.restart_marking_pending or core.scene_projector.stats.restart_marked < stars
        await until_true(lambda: _marking_done(core.scene_projector), timeout=15)
        snapshot = await core.scene.snapshot()
        assert {item.exec_state for item in snapshot.objects} <= {ExecState.UNKNOWN}
        assert len(grace_tasks()) == (1 if stars else 0)  # la grâce part après le marquage
    finally:
        await core.stop()
    assert grace_tasks() == []


async def test_no_work_event_is_projected_before_the_marking_completes():
    repository = _SlowCommits(running_scene(20), delay=0.02)
    async with Stack(repository=repository, restart_grace_s=RESTART_GRACE_S) as stack:
        await stack.projector.stop()  # repartir d'une projection arrêtée, marquage demandé comme Core
    stack = Stack(repository=repository, restart_grace_s=RESTART_GRACE_S)
    await stack.scene.start()
    await stack.projector.reconcile_restart()
    stack.projector.start()
    try:
        # Pendant le marquage (≈ 0,4 s), deux observations arrivent : l'une redit s0 en cours, l'autre en fait un échec.
        await asyncio.sleep(0.05)
        assert stack.projector.restart_marking_pending
        await stack.work.observe(obs("s0", label="tâche s0"))
        await stack.work.observe(obs("s1", WorkStatus.FAILED, label="tâche s1", at=1))
        await settled(stack.projector, timeout=10)
        snapshot = await stack.snapshot()
    finally:
        await stack.projector.stop()
        await stack.scene.close()
    assert snapshot.get_object("claude:s0").exec_state is ExecState.RUNNING  # jamais réécrite `unknown` après coup
    assert snapshot.get_object("claude:s1").exec_state is ExecState.FAILED
    assert stack.projector.restart_tracked_count == 18
    assert stack.diagnostics.kinds(SCENE_RESTART_MARKED_KIND)[0][1]["marked"] == 20


async def test_stopping_during_the_marking_leaves_no_task_and_no_timer():
    for delay in (0.0, 0.05, 0.15):
        repository = _SlowCommits(running_scene(10), delay=0.03)
        stack = Stack(repository=repository, restart_grace_s=0.05)
        await stack.scene.start()
        await stack.projector.reconcile_restart()
        stack.projector.start()
        await asyncio.sleep(delay)
        await stack.projector.stop()

        def leftovers() -> list[str]:
            return [task.get_name() for task in asyncio.all_tasks() if task.get_name().startswith("jarvis-scene") and not task.done()]

        # Borné : une tâche annulée finit en quelques tours de boucle ; une tâche oubliée resterait au-delà.
        deadline = asyncio.get_running_loop().time() + 5
        while leftovers() and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)
        left = leftovers()
        await stack.scene.close()
        assert left == [], delay


async def test_a_non_store_failure_at_grace_expiry_backs_off_and_never_starves_the_loop():
    async with RestartStack(repository=repository_with(seeded_scene()), restart_grace_s=0.05) as stack:
        real = stack.work.snapshot
        calls = 0

        async def failing():
            nonlocal calls
            calls += 1
            # Rend la main une fois : une régression qui boucle à vide se voit
            # alors au compteur (des milliers d'appels) au lieu de figer le test.
            await asyncio.sleep(0)
            raise RuntimeError("work snapshot defect (test)")

        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0.001)

        stack.work.snapshot = failing
        task = asyncio.create_task(ticker())
        await asyncio.sleep(0.4)
        task.cancel()
        spun = calls
        stack.work.snapshot = real
        await grace_expired(stack)
    assert 1 <= spun <= 20  # attente croissante de 10 à 50 ms (bornes du Stack), réconciliation comprise : pas 20 000
    assert ticks >= 10  # ~27 sous Windows (horloge de 15 ms) ; une boucle à vide n en laisse passer aucun
    failed = [data for _, data in stack.diagnostics.kinds(SCENE_PROJECTION_FAILED_KIND)]
    assert [data["where"] for data in failed].count("restart_grace") == 1
    assert stack.diagnostics.kinds(SCENE_RESTART_GRACE_EXPIRED_KIND)[0][1]["interrupted"] == len(MARKED)


async def test_a_job_outcome_read_back_after_a_restart_keeps_the_brain_work_id(tmp_path):
    class Done:
        async def execute(self, job, progress=None):
            return {}

        async def cancel(self, job_id):
            return None

    data = tmp_path / "data"
    core = JarvisCoreApplication(data_root=data, workers={"demo": Done()})
    await core.start()
    job = await core.jobs.submit(Job(kind="demo"), work_id="brain-work-42", correlation_id="corr-1")
    star_id = star_object_id("job", job.id)

    async def completed() -> bool:
        item = (await core.scene.snapshot()).get_object(star_id)
        return item is not None and item.exec_state is ExecState.COMPLETED
    await until_true(completed)
    running = Job(kind="demo", status=JobStatus.RUNNING, started_at=datetime.now(timezone.utc))
    await core.state.save_job(running)
    for object_id, work_id in ((star_id, "brain-work-42"), (star_object_id("job", running.id), "brain-work-43")):
        await core.scene.apply(SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=SceneActor.RUNTIME, object_id=object_id, fields=SceneObjectFields(
            kind=SceneObjectKind.JOB, category="job", exec_state=ExecState.RUNNING,
            work_ref=WorkRef(source="job", external_id=object_id.split(":", 1)[1], work_id=work_id))))
    await core.stop()  # image d'arrêt brutal : fin écrite en base, étoile restée « en cours »

    core = JarvisCoreApplication(data_root=data, workers={"demo": Done()}, scene_restart_grace_s=0.3)
    await core.start()
    try:
        await until_true(lambda: _marking_done(core.scene_projector))
        await settled(core.scene_projector)
        snapshot = await core.scene.snapshot()
        items = {item.external_id: item for item in (await core.work_state.snapshot()).items}
    finally:
        await core.stop()
    finished = snapshot.get_object(star_id)
    assert (finished.exec_state, finished.work_ref.work_id) == (ExecState.COMPLETED, "brain-work-42")
    assert items[job.id].link.work_id == "brain-work-42"  # l'état de travail le retrouve aussi
    recovered = snapshot.get_object(star_object_id("job", running.id))
    # `recover` : la ligne `jobs` n'a pas de work_id ; l'étoile garde le sien.
    assert (recovered.exec_state, recovered.work_ref.work_id) == (ExecState.INTERRUPTED, "brain-work-43")
    assert snapshot.get_object(signal_object_id(recovered.object_id)).work_ref.work_id == "brain-work-43"


async def test_a_back_brain_outcome_read_back_rebuilds_its_link_like_recover(tmp_path):
    from tests.unit.test_back_brain_tasks import ControlledWorker, admitted, settle, submit

    data = tmp_path / "data"
    worker = ControlledWorker()
    core = JarvisCoreApplication(data_root=data, workers={"back_brain": worker})
    await core.start()
    _, admission = await admitted(core)
    accepted = await submit(core, admission)
    await asyncio.wait_for(worker.started.wait(), 2)
    worker.release.set()
    await settle(core, accepted.job_id)
    star_id = star_object_id("job", accepted.job_id)

    async def completed() -> bool:
        item = (await core.scene.snapshot()).get_object(star_id)
        return item is not None and item.exec_state is ExecState.COMPLETED
    await until_true(completed)
    before = (await core.scene.snapshot()).get_object(star_id).work_ref
    await core.scene.apply(SceneCommand(op=SceneOp.PATCH_OBJECT, actor=SceneActor.RUNTIME, object_id=star_id,
                                        fields=SceneObjectFields(exec_state=ExecState.RUNNING)))
    await core.stop()

    core = JarvisCoreApplication(data_root=data, workers={"back_brain": ControlledWorker()}, scene_restart_grace_s=0.3)
    await core.start()
    try:
        await until_true(lambda: _marking_done(core.scene_projector))
        await settled(core.scene_projector)
        item = {entry.external_id: entry for entry in (await core.work_state.snapshot()).items}[accepted.job_id]
        after = (await core.scene.snapshot()).get_object(star_id)
    finally:
        await core.stop()
    assert before.work_id == accepted.job_id
    assert item.link.work_id == accepted.job_id and item.link.correlation_id is not None
    assert (after.exec_state, after.work_ref.work_id) == (ExecState.COMPLETED, accepted.job_id)


def test_the_projector_refuses_a_non_positive_grace():
    for grace in (0, -1, float("nan")):
        with pytest.raises(ValueError):
            SceneProjector(work=None, scene=None, events=None, restart_grace_s=grace)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("raw", "expected", "refused"),
    [(None, RESTART_GRACE_S, False), ("", RESTART_GRACE_S, False), ("2.5", 2.5, False), ("3600", 3600.0, False),
     ("0", RESTART_GRACE_S, True), ("-4", RESTART_GRACE_S, True), ("nan", RESTART_GRACE_S, True),
     ("3601", RESTART_GRACE_S, True), ("soixante", RESTART_GRACE_S, True)],
)
def test_the_restart_grace_is_read_from_the_environment_and_a_bad_value_is_reported(monkeypatch, raw, expected, refused):
    from jarvis.app import _scene_restart_grace_from_env

    if raw is None:
        monkeypatch.delenv("JARVIS_SCENE_RESTART_GRACE_S", raising=False)
    else:
        monkeypatch.setenv("JARVIS_SCENE_RESTART_GRACE_S", raw)
    value, error = _scene_restart_grace_from_env()
    assert value == expected and (error is not None) is refused

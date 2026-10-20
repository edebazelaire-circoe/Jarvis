"""Rôles, relations typées et éphémères dans la scène (handoff organic-agent-orchestration, Slice 08).

Pièces réelles : `WorkStateStore`, `CoreEventBus`, `SceneService` (mémoire ou SQLite), `SceneProjector` et
`MissionHistoryService` sur une base `jarvis.sqlite3` temporaire. Ce qui doit tenir :

- le rôle d'une étoile vit dans `role_ref`, champ réservé au runtime (jamais `category`) : le cerveau et
  l'utilisateur ne l'écrivent pas ; il vient de l'historique des missions (instance, mission, propriétaire
  courant), à défaut du `role_id` de Work State, jamais d'un libellé ;
- chaque relation réelle (délégation, communication, Adversary, QA, relais) devient un lien de scène distinct,
  d'identifiant déterministe, porteur de sa `RelationRef` ; Adversary et communication à N participants : un lien
  par paire ; le cerveau ne les pose ni ne les délie ;
- rien n'est projeté pour une instance sans étoile (aucun nœud futur) et l'historique n'écrit jamais `exec_state`
  (une mission `live_unknown` ne fait rien passer « en cours ») ;
- un travail éphémère n'a aucune ligne de scène persistée, ni pendant, ni après sa réussite, ni après un
  redémarrage ; s'il échoue, son étoile naît à ce moment-là ;
- la projection ne lit que `instance_for_work` et `mission_view`, jamais Conversation Events.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.adapters.sqlite_scene import SQLiteSceneRepository
from jarvis.core import scene_projector as projector_module
from jarvis.core.mission_history import MissionHistoryService
from jarvis.core.scene_projector import (
    SCENE_EPHEMERAL_SKIPPED_KIND,
    SCENE_MISSION_PROJECTED_KIND,
    SCENE_MISSION_PROJECTION_FAILED_KIND,
    SCENE_STAR_CREATED_KIND,
    SceneProjector,
    agent_relation_links,
    signal_object_id,
    star_object_id,
)
from jarvis.core.scene_service import SCENE_MIGRATED_KIND, SceneService
from jarvis.core.v2_services import CoreEventBus
from jarvis.core.work_state import WorkStateStore
from jarvis.domain.agent_relations import AgentRelationKind as K
from jarvis.domain.agent_relations import ParticipantPosition as P
from jarvis.domain.agent_relations import RelationOutcome, RelationStatus
from jarvis.domain.mission_history import InstanceView, MissionTree, StoredInstance
from jarvis.domain.relation_runtime import delegation_relation_id
from jarvis.domain.scene import (
    AGENT_RELATION_KINDS,
    AgentRelationState,
    ExecState,
    PlacedBy,
    RelationKind,
    RelationRef,
    RoleRef,
    SceneActor,
    SceneCommand,
    SceneCommandOutcome,
    SceneConstraints,
    SceneObject,
    SceneObjectFields,
    SceneObjectKind,
    SceneOp,
    ScenePayload,
    SceneRefusal,
    SceneRelation,
    SceneSnapshot,
    WorkRef,
    apply_scene_command,
    is_runtime_reserved_id,
)
from jarvis.domain.work_state import WorkObservation, WorkStatus
from jarvis.ports.mission_history import MissionHistoryUnavailable
from tests.fakes.mission_history import SOURCE, at, instance, mission, open_store, relation
from tests.unit.test_relations_runtime_service import (
    Clock, declare_successor, member, owner, packet, w,
)
from tests.unit.test_scene_projector import settled
from tests.unit.test_scene_service import MemoryRepository, RecordingDiagnostics


# ------------------------------------------------------------------ domaine


def star(object_id: str = "claude:A", *, role: RoleRef | None = None, kind=SceneObjectKind.AGENT) -> SceneObject:
    return SceneObject(object_id=object_id, kind=kind, category=kind.value,
                       constraints=SceneConstraints(placed_by=PlacedBy.RUNTIME),
                       origin=SceneActor.RUNTIME, exec_state=ExecState.RUNNING,
                       work_ref=WorkRef(source="claude", external_id=object_id.split(":", 1)[1]), role_ref=role)


def two_stars(**relations) -> SceneSnapshot:
    return SceneSnapshot(scene_id="scene", objects=(star("claude:A"), star("claude:B")), **relations)


REF = RelationRef(relation_id="rel_1", mission_id="mis_A")


def test_a_role_ref_is_explicit_bounded_and_only_on_an_agent_star():
    role = RoleRef(role_id="qa", instance_id="ainst_1", mission_id="mis_A", mission_owner=True)
    assert RoleRef.from_payload(role.to_payload()) == role
    for bad in ("Quality Analyst", "", "q", "qa!"):
        with pytest.raises(ValueError):
            RoleRef(role_id=bad)
    with pytest.raises(ValueError):
        RoleRef(role_id="coder", mission_owner=True)  # propriétaire sans mission
    with pytest.raises(ValueError):
        star("claude:J", role=RoleRef(role_id="coder"), kind=SceneObjectKind.JOB)
    # Absent du fil quand il vaut `None` : la forme v1 d'un objet est inchangée, et se relit.
    plain = star()
    assert "role_ref" not in plain.to_payload()
    assert SceneObject.from_payload(plain.to_payload()) == plain
    carried = star(role=role)
    assert SceneObject.from_payload(carried.to_payload()) == carried


def test_only_runtime_writes_role_ref_and_category_stays_free():
    scene = SceneSnapshot(scene_id="scene", objects=(star(role=RoleRef(role_id="coder")),))
    forged = SceneCommand(op=SceneOp.PATCH_OBJECT, actor=SceneActor.BRAIN, object_id="claude:A",
                          fields=SceneObjectFields(role_ref=RoleRef(role_id="qa")))
    update = apply_scene_command(scene, forged)
    assert (update.outcome, update.reason) == (SceneCommandOutcome.REJECTED_AUTHORITY, SceneRefusal.EXECUTION_TRUTH)
    # La catégorie reste au cerveau : elle ne dit pas le rôle et ne le touche pas.
    recolored = apply_scene_command(scene, SceneCommand(op=SceneOp.PATCH_OBJECT, actor=SceneActor.BRAIN,
                                                        object_id="claude:A",
                                                        fields=SceneObjectFields(category="qa")))
    assert recolored.outcome is SceneCommandOutcome.APPLIED
    assert recolored.snapshot.get_object("claude:A").role_ref == RoleRef(role_id="coder")
    # Runtime : sur une étoile agent seulement, refus du réducteur ailleurs (jamais une exception).
    signal = SceneObject(object_id="attention!claude:A", kind=SceneObjectKind.ATTENTION, category="failed",
                         constraints=SceneConstraints(placed_by=PlacedBy.RUNTIME), origin=SceneActor.RUNTIME)
    scene = SceneSnapshot(scene_id="scene", objects=(star(), signal))
    update = apply_scene_command(scene, SceneCommand(op=SceneOp.PATCH_OBJECT, actor=SceneActor.RUNTIME,
                                                     object_id=signal.object_id,
                                                     fields=SceneObjectFields(role_ref=RoleRef(role_id="qa"))))
    assert (update.outcome, update.reason) == (SceneCommandOutcome.INVALID, SceneRefusal.ROLE_REF_KIND)


def test_an_agent_relation_carries_its_mission_ref_and_only_runtime_poses_it():
    with pytest.raises(ValueError):
        SceneRelation("qa!rel_1", RelationKind.QA, "claude:A", "claude:B")  # sans relation réelle
    with pytest.raises(ValueError):
        SceneRelation("x", RelationKind.PARENT_OF, "claude:A", "claude:B", ref=REF)
    link = SceneRelation("qa!rel_1", RelationKind.QA, "claude:A", "claude:B", ref=REF)
    assert SceneRelation.from_payload(link.to_payload()) == link
    assert "ref" not in SceneRelation("p", RelationKind.PARENT_OF, "claude:A", "claude:B").to_payload()
    scene = two_stars()
    for actor in (SceneActor.BRAIN, SceneActor.USER):
        # Sous un id libre comme sous l'id du runtime : jamais d'une composition.
        for rid in ("mon-lien", "qa!rel_1"):
            forged = replace(link, relation_id=rid)
            update = apply_scene_command(scene, SceneCommand(op=SceneOp.LINK, actor=actor, relation=forged))
            assert update.outcome is SceneCommandOutcome.REJECTED_AUTHORITY, (actor, rid)
    posed = apply_scene_command(scene, SceneCommand(op=SceneOp.LINK, actor=SceneActor.RUNTIME, relation=link))
    assert posed.outcome is SceneCommandOutcome.APPLIED
    scene = posed.snapshot
    # Ni délié par le cerveau, ni réécrit (`ref`) par lui ; la couche, si.
    update = apply_scene_command(scene, SceneCommand(op=SceneOp.UNLINK, actor=SceneActor.BRAIN, relation_id="qa!rel_1"))
    assert (update.outcome, update.reason) == (SceneCommandOutcome.REJECTED_AUTHORITY, SceneRefusal.RUNTIME_OWNED)
    closed = RelationRef(relation_id="rel_1", mission_id="mis_A", state=AgentRelationState.CLOSED, outcome="approved")
    update = apply_scene_command(scene, SceneCommand(op=SceneOp.LINK, actor=SceneActor.BRAIN,
                                                     relation=replace(link, ref=closed, layer=60)))
    assert (update.outcome, update.reason) == (SceneCommandOutcome.REJECTED_AUTHORITY, SceneRefusal.EXECUTION_TRUTH)
    layered = apply_scene_command(scene, SceneCommand(op=SceneOp.LINK, actor=SceneActor.USER,
                                                      relation=replace(link, layer=60)))
    assert layered.outcome is SceneCommandOutcome.APPLIED
    # Le runtime met la référence à jour et garde la couche choisie par l'utilisateur.
    refreshed = apply_scene_command(layered.snapshot, SceneCommand(op=SceneOp.LINK, actor=SceneActor.RUNTIME,
                                                                   relation=replace(link, ref=closed)))
    assert refreshed.outcome is SceneCommandOutcome.APPLIED
    assert refreshed.snapshot.get_relation("qa!rel_1") == replace(link, ref=closed, layer=60)
    # Le runtime ne délie pas un lien d'agent : une relation réelle ne disparaît pas de l'historique.
    update = apply_scene_command(scene, SceneCommand(op=SceneOp.UNLINK, actor=SceneActor.RUNTIME, relation_id="qa!rel_1"))
    assert (update.outcome, update.reason) == (SceneCommandOutcome.REJECTED_AUTHORITY, SceneRefusal.RUNTIME_RELATION)
    for kind in AGENT_RELATION_KINDS:
        assert is_runtime_reserved_id(f"{kind.value}!rel_x") and is_runtime_reserved_id(f"{kind.value}#abc!x")


def test_relation_links_are_deterministic_directed_or_pairwise():
    directed = relation("rel_q", K.QA, "mis_A", [("ainst_Q", P.REVIEWER), ("ainst_B", P.REVIEWED)])
    assert agent_relation_links(directed) == (("qa!rel_q", "ainst_Q", "ainst_B"),)
    trio = relation("rel_c", K.COMMUNICATION, "mis_A", [("ainst_A", P.MEMBER), ("ainst_B", P.MEMBER), ("ainst_C", P.MEMBER)])
    assert agent_relation_links(trio) == (
        ("communication!rel_c!ainst_A~ainst_B", "ainst_A", "ainst_B"),
        ("communication!rel_c!ainst_A~ainst_C", "ainst_A", "ainst_C"),
        ("communication!rel_c!ainst_B~ainst_C", "ainst_B", "ainst_C"),
    )
    long_ids = relation("rel_" + "x" * 60, K.ADVERSARY, "mis_A",
                        [("ainst_" + "a" * 40, P.PRODUCER), ("ainst_" + "b" * 40, P.PRODUCER)])
    [(link_id, _a, _b)] = agent_relation_links(long_ids)
    assert len(link_id) <= 128 and link_id.startswith("adversary#") and is_runtime_reserved_id(link_id)
    assert agent_relation_links(long_ids) == agent_relation_links(long_ids)


# ------------------------------------------------------------------ montage réel


def agent_obs(key: str, status: WorkStatus = WorkStatus.RUNNING, *, minute: float = 0.1, ephemeral: bool = False,
              role_id: str | None = None, error_class: str | None = None) -> WorkObservation:
    return WorkObservation(source=SOURCE, external_id=key, status=status, observed_at=at(minute), kind="agent",
                           label=f"Agent {key}", ephemeral=ephemeral, role_id=role_id, error_class=error_class)


class World:
    """Core réduit : bus, Work State, historique des missions et scène, comme `JarvisCoreApplication` les relie."""

    def __init__(self, state_store, *, clock: Clock, scene_repository=None, missions=None,
                 mission_min_interval_s: float = 0, mission_refresh_s: float = 0.02) -> None:
        self.clock = clock
        self.diagnostics = RecordingDiagnostics()
        self.events = CoreEventBus(diagnostics=self.diagnostics)
        self.work = WorkStateStore(events=self.events, diagnostics=self.diagnostics, clock=clock)
        self.store = state_store
        self.service = MissionHistoryService(state_store, work_state=self.work, diagnostics=self.diagnostics,
                                             clock=clock, sweep_interval_s=None)
        self.scene = SceneService(scene_repository or MemoryRepository(), diagnostics=self.diagnostics)
        self.projector = SceneProjector(
            work=self.work, scene=self.scene, events=self.events, diagnostics=self.diagnostics, retry_min_s=0.01,
            retry_max_s=0.05, missions=missions if missions is not None else self.service,
            mission_min_interval_s=mission_min_interval_s, mission_refresh_s=mission_refresh_s,
        )

    async def start(self, *, restart: bool = False) -> World:
        await self.scene.start()
        if restart:
            await self.projector.reconcile_restart()
        self.projector.start()
        await settled(self.projector)
        return self

    async def stop(self) -> None:
        await self.projector.stop()
        await self.scene.close()

    async def observe(self, *observations: WorkObservation) -> None:
        for observation in observations:
            await self.work.observe(observation)
            item = next(i for i in self.work.current_snapshot().items if i.key == (SOURCE, observation.external_id))
            await self.service.observe_work_item(item)
        await settled(self.projector)

    async def refreshed(self) -> SceneSnapshot:
        """Deux tours de rafraîchissement des missions suivies, puis l'instantané."""

        for _ in range(2):
            target = self.projector.stats.missions_projected + 1
            for _ in range(500):
                if self.projector.stats.missions_projected >= target:
                    break
                await asyncio.sleep(0.01)
            await settled(self.projector)
        return await self.scene.snapshot()


@pytest.fixture
async def world(tmp_path):
    state, store = await open_store(tmp_path / "jarvis.sqlite3")
    built = await World(store, clock=Clock()).start()
    yield built
    await built.stop()
    await built.service.stop()
    await state.close()


async def declared_team(world: World) -> None:
    """A (coder, Mission Owner racine), B et C (producteurs), Q (qa) : déclarés au hook, puis observés."""

    await owner(world, "A")
    for key, role in (("B", "coder"), ("C", "coder"), ("Q", "qa")):
        await member(world, key, "A", role)
    await world.observe(*(agent_obs(key, role_id=role) for key, role in
                          (("A", "coder"), ("B", "coder"), ("C", "coder"), ("Q", "qa"))))


async def instance_id(world: World, key: str) -> str:
    return (await world.store.find_instance(SOURCE, key)).instance.instance_id


async def test_roles_and_owner_reach_the_stars_from_mission_history(world):
    await declared_team(world)
    scene = await world.refreshed()
    roles = {key: scene.get_object(star_object_id(SOURCE, key)).role_ref for key in "ABCQ"}
    assert roles["A"] == RoleRef(role_id="coder", instance_id=await instance_id(world, "A"), mission_id="mis_A",
                                 mission_owner=True)
    assert roles["Q"].role_id == "qa" and roles["Q"].mission_owner is False and roles["Q"].mission_id == "mis_A"
    # La catégorie reste celle de la nature : le rôle n'y est jamais rangé.
    assert {scene.get_object(star_object_id(SOURCE, key)).category for key in "ABCQ"} == {"agent"}
    [projected, *_] = world.diagnostics.kinds(SCENE_MISSION_PROJECTED_KIND)
    assert projected[0] == "info" and projected[1]["mission_id"] == "mis_A"


async def test_qa_adversary_and_communication_become_distinct_typed_links(world):
    await declared_team(world)
    qa = await world.service.open_relation(caller=w("Q"), kind=K.QA, purpose="Relire B",
                                           participants=[(w("Q"), P.REVIEWER), (w("B"), P.REVIEWED)])
    duel = await world.service.open_relation(caller=w("A"), kind=K.ADVERSARY, purpose="Deux caches",
                                             participants=[(w("B"), P.PRODUCER), (w("C"), P.PRODUCER)])
    talk = await world.service.open_relation(caller=w("A"), kind=K.COMMUNICATION, purpose="Nommer le module",
                                             participants=[(w("A"), P.MEMBER), (w("B"), P.MEMBER),
                                                           (w("C"), P.MEMBER)])
    scene = await world.refreshed()
    stars = {await instance_id(world, key): star_object_id(SOURCE, key) for key in "ABCQ"}
    by_kind: dict[RelationKind, list[SceneRelation]] = {}
    for link in scene.relations:
        by_kind.setdefault(link.kind, []).append(link)
    [qa_link] = by_kind[RelationKind.QA]
    assert (qa_link.relation_id, qa_link.from_id, qa_link.to_id) == (f"qa!{qa.relation_id}", stars[qa.endpoints()[0]],
                                                                      stars[qa.endpoints()[1]])
    assert qa_link.ref == RelationRef(relation_id=qa.relation_id, mission_id="mis_A")
    [duel_link] = by_kind[RelationKind.ADVERSARY]
    assert {duel_link.from_id, duel_link.to_id} == {star_object_id(SOURCE, "B"), star_object_id(SOURCE, "C")}
    assert len(by_kind[RelationKind.COMMUNICATION]) == 3  # trois membres : un lien par paire, une même ref
    assert {link.ref.relation_id for link in by_kind[RelationKind.COMMUNICATION]} == {talk.relation_id}
    # Le verdict QA atteint le lien (état et issue), la couche reste.
    await world.service.finish_relation(caller=w("Q"), relation_id=qa.relation_id, outcome=RelationOutcome.APPROVED)
    await world.service.finish_relation(caller=w("A"), relation_id=duel.relation_id, outcome=RelationOutcome.WINNER,
                                        winner=w("B"))
    scene = await world.refreshed()
    assert scene.get_relation(f"qa!{qa.relation_id}").ref.state is AgentRelationState.CLOSED
    assert scene.get_relation(f"qa!{qa.relation_id}").ref.outcome == "approved"
    assert scene.get_relation(duel_link.relation_id).ref.outcome == "winner"
    # Rien d'autre n'a bougé : le statut d'exécution reste celui de Work State.
    assert {scene.get_object(star_object_id(SOURCE, key)).exec_state for key in "ABCQ"} == {ExecState.RUNNING}


async def test_delegation_and_handoff_are_projected_with_the_current_owner(world):
    await declared_team(world)
    await owner(world, "L", parent="A", role="research-lead")
    await world.observe(agent_obs("L", role_id="research-lead"))
    pending = await world.service.prepare_handoff(caller=w("A"), purpose="Contexte neuf", packet=packet())
    await declare_successor(world, "S", pending.handoff_id)
    await world.observe(agent_obs("S", role_id="coder"))
    scene = await world.refreshed()
    delegation = scene.get_relation(f"delegation!{delegation_relation_id('mis_L')}")
    assert (delegation.from_id, delegation.to_id) == (star_object_id(SOURCE, "A"), star_object_id(SOURCE, "L"))
    assert scene.get_object(star_object_id(SOURCE, "L")).role_ref.mission_owner is True  # sous-mission (D04)
    [handoff] = [link for link in scene.relations if link.kind is RelationKind.HANDOFF]
    assert (handoff.from_id, handoff.to_id) == (star_object_id(SOURCE, "A"), star_object_id(SOURCE, "S"))
    assert (handoff.ref.state, handoff.ref.outcome) == (AgentRelationState.CLOSED, "transferred")
    # Propriétaire courant : le successeur ; le prédécesseur garde son rôle, plus la responsabilité (D03, D14).
    assert scene.get_object(star_object_id(SOURCE, "S")).role_ref.mission_owner is True
    assert scene.get_object(star_object_id(SOURCE, "A")).role_ref.mission_owner is False
    assert scene.get_object(star_object_id(SOURCE, "A")).role_ref.role_id == "coder"


async def test_no_star_or_link_is_invented_for_an_instance_without_a_star(world):
    await owner(world, "A")
    await member(world, "Q", "A", "qa")
    await world.observe(agent_obs("A", role_id="coder"))  # Q est déclaré, son travail n'a jamais été vu
    await world.service.open_relation(caller=w("Q"), kind=K.QA, purpose="Relire A",
                                      participants=[(w("Q"), P.REVIEWER), (w("A"), P.REVIEWED)])
    scene = await world.refreshed()
    assert {item.object_id for item in scene.objects} == {star_object_id(SOURCE, "A")}
    assert scene.relations == ()
    # Dès que le travail de Q existe, son étoile naît de Work State et le lien suit.
    await world.observe(agent_obs("Q", role_id="qa"))
    scene = await world.refreshed()
    assert [link.kind for link in scene.relations] == [RelationKind.QA]


async def test_a_work_role_without_history_is_projected_alone_and_never_from_a_label(world):
    await world.observe(agent_obs("X", role_id="research"))
    await world.observe(WorkObservation(source=SOURCE, external_id="Y", status=WorkStatus.RUNNING, observed_at=at(0.2),
                                        kind="agent", label="[qa] Relecteur"))
    scene = await world.scene.snapshot()
    assert scene.get_object(star_object_id(SOURCE, "X")).role_ref == RoleRef(role_id="research")
    assert scene.get_object(star_object_id(SOURCE, "Y")).role_ref is None


# ------------------------------------------------------------------ éphémères (D08)


async def test_a_successful_ephemeral_leaves_no_persistent_scene_row(world):
    before = (await world.scene.snapshot()).revision
    await world.observe(agent_obs("E", ephemeral=True), agent_obs("E", WorkStatus.COMPLETED, minute=0.3, ephemeral=True))
    scene = await world.scene.snapshot()
    assert scene.get_object(star_object_id(SOURCE, "E")) is None
    assert scene.revision == before and not scene.archived_ids  # rien d'écrit, rien d'archivé
    [(level, data)] = world.diagnostics.kinds(SCENE_EPHEMERAL_SKIPPED_KIND)  # une ligne par travail
    assert level == "info" and data["object_id"] == star_object_id(SOURCE, "E")
    assert world.projector.stats.skipped_ephemeral == 2


async def test_a_failed_ephemeral_is_projected_when_it_fails(world):
    await world.observe(agent_obs("F", ephemeral=True))
    assert (await world.scene.snapshot()).get_object(star_object_id(SOURCE, "F")) is None
    await world.observe(agent_obs("F", WorkStatus.FAILED, minute=0.3, ephemeral=True, error_class="tool_error"))
    scene = await world.scene.snapshot()
    star_id = star_object_id(SOURCE, "F")
    assert scene.get_object(star_id).exec_state is ExecState.FAILED
    assert scene.get_object(signal_object_id(star_id)) is not None
    [(_level, created)] = world.diagnostics.kinds(SCENE_STAR_CREATED_KIND)
    assert created["object_id"] == star_id and created["ephemeral_lowered"] is True


async def test_history_unavailable_keeps_the_stars_and_says_it_once(tmp_path):
    class Down:
        calls = 0

        async def instance_for_work(self, work_source, work_external_id):
            Down.calls += 1
            raise MissionHistoryUnavailable("find_instance", "database is locked")

        async def mission_view(self, mission_id):
            raise AssertionError("not reached")

    state, store = await open_store(tmp_path / "jarvis.sqlite3")
    world = await World(store, clock=Clock(), missions=Down()).start()
    try:
        await world.observe(agent_obs("A", role_id="coder"), agent_obs("B", role_id="qa"))
        scene = await world.scene.snapshot()
        assert {item.object_id for item in scene.objects} == {star_object_id(SOURCE, "A"), star_object_id(SOURCE, "B")}
        assert all(item.role_ref is None for item in scene.objects)
        [(level, data)] = world.diagnostics.kinds(SCENE_MISSION_PROJECTION_FAILED_KIND)
        assert level == "warning" and "database is locked" in data["error"]
        assert world.projector.stats.mission_failures == Down.calls == 2
    finally:
        await world.stop()
        await state.close()


# ------------------------------------------------------------------ redémarrage


async def test_restart_keeps_roles_and_relations_never_invents_status_nor_resurrects_an_ephemeral(tmp_path):
    state, store = await open_store(tmp_path / "jarvis.sqlite3")
    scene_path = tmp_path / "scene.sqlite3"
    clock = Clock()
    first = await World(store, clock=clock, scene_repository=SQLiteSceneRepository(scene_path)).start()
    await declared_team(first)
    qa = await first.service.open_relation(caller=w("Q"), kind=K.QA, purpose="Relire B",
                                           participants=[(w("Q"), P.REVIEWER), (w("B"), P.REVIEWED)])
    await first.observe(agent_obs("A", WorkStatus.COMPLETED, minute=0.5, role_id="coder"))
    await first.observe(agent_obs("E", ephemeral=True), agent_obs("E", WorkStatus.COMPLETED, minute=0.6, ephemeral=True))
    lived = await first.refreshed()
    await first.stop()
    await first.service.stop()
    # Pendant l'arrêt de Core, la relation est close dans l'historique (fait durable, pas d'exécution).
    await store.close_relation(qa.relation_id, RelationOutcome.FINDINGS, at(40), closed_by=qa.participant_ids[0])
    clock.minute = 90.0  # mission bien plus vieille que la grâce des orphelines : Core n'en sait plus rien
    second = World(store, clock=clock, scene_repository=SQLiteSceneRepository(scene_path))
    second.service._born = at(0)  # Core né depuis plus que la grâce (voir `_is_orphan`)
    await second.start(restart=True)
    try:
        scene = await second.refreshed()
        tree, _views = await second.service.mission_view("mis_A")
        assert second.service.live_unknown(tree) == frozenset({"mis_A"})
        # Les étoiles et leurs rôles survivent ; rien n'est ressuscité ni ajouté.
        assert {item.object_id for item in scene.objects} == {item.object_id for item in lived.objects}
        assert star_object_id(SOURCE, "E") not in {item.object_id for item in scene.objects}
        assert all(item.role_ref == lived.get_object(item.object_id).role_ref for item in scene.objects)
        # Statut : celui du redémarrage de la scène (inconnu ou terminé), jamais « en cours » tiré de l'historique.
        assert scene.get_object(star_object_id(SOURCE, "A")).exec_state is ExecState.COMPLETED
        assert {scene.get_object(star_object_id(SOURCE, key)).exec_state for key in "BCQ"} == {ExecState.UNKNOWN}
        # La relation close pendant l'arrêt est rattrapée par la relecture des missions des étoiles persistées.
        link = scene.get_relation(f"qa!{qa.relation_id}")
        assert (link.ref.state, link.ref.outcome) == (AgentRelationState.CLOSED, "findings")
    finally:
        await second.stop()
        await second.service.stop()
        await state.close()


# ------------------------------------------------------------------ sources


class Recording:
    """Source de missions qui enregistre ce que la projection lui demande."""

    def __init__(self, tree: MissionTree) -> None:
        self.tree = tree
        self.calls: list[str] = []

    async def instance_for_work(self, work_source, work_external_id):
        self.calls.append("instance_for_work")
        for stored in self.tree.instances:
            if stored.instance.work_identity == (work_source, work_external_id):
                return InstanceView(stored)
        return None

    async def mission_view(self, mission_id):
        self.calls.append("mission_view")
        return self.tree, ()


async def test_the_projection_reads_only_instance_for_work_and_mission_view(tmp_path):
    tree = MissionTree(
        root_mission_id="mis_A", missions=(mission("mis_A", "ainst_A"),),
        instances=(StoredInstance(instance("ainst_A", mission="mis_A", owner=True, external="A")),
                   StoredInstance(instance("ainst_B", mission="mis_A", external="B"))),
        relations=(relation("rel_h", K.HANDOFF, "mis_A", [("ainst_A", P.PREDECESSOR), ("ainst_B", P.SUCCESSOR)],
                            handoff=packet(), status=RelationStatus.CLOSED, closed_at=at(2),
                            outcome=RelationOutcome.TRANSFERRED),),
    )
    source = Recording(tree)
    state, store = await open_store(tmp_path / "jarvis.sqlite3")
    world = await World(store, clock=Clock(), missions=source).start()
    try:
        await world.observe(agent_obs("A"), agent_obs("B"))
        scene = await world.refreshed()
        assert scene.get_relation("handoff!rel_h").ref == RelationRef(relation_id="rel_h", mission_id="mis_A",
                                                                       state=AgentRelationState.CLOSED,
                                                                       outcome="transferred")
        assert set(source.calls) == {"instance_for_work", "mission_view"}
    finally:
        await world.stop()
        await state.close()
    # Ni Conversation Events, ni journal de diagnostic comme source : le module ne les connaît pas.
    text = Path(projector_module.__file__).read_text(encoding="utf-8")
    for forbidden in ("conversation_events", "ConversationEvent", "subagent_conversation", "trace.jsonl"):
        assert forbidden not in text, forbidden


# ------------------------------------------------------------------ migration v1 -> v2


async def test_a_v1_scene_built_from_its_frozen_snapshot_migrates_after_a_backup_and_keeps_every_row(tmp_path):
    """Base v1 construite depuis `tests/schema/scene.v1.sql`, avec l'étoile d'une éphémère persistée par la v1."""

    import json
    import sqlite3

    path = tmp_path / "scene.sqlite3"
    ddl = (Path(__file__).resolve().parents[1] / "schema" / "scene.v1.sql").read_text(encoding="utf-8")
    legacy = star("claude:toolu_eph")  # rien dans la ligne ne dit « éphémère » : ni drapeau, ni rôle
    legacy = replace(legacy, exec_state=ExecState.COMPLETED, payload=ScenePayload(title="Liste de courses"))
    ordinary = replace(star("claude:toolu_ord"), exec_state=ExecState.COMPLETED)
    rows = [(item.object_id, index, json.dumps(item.to_payload(), ensure_ascii=False, separators=(",", ":"), sort_keys=True))
            for index, item in enumerate((legacy, ordinary))]
    link = SceneRelation("parent_of!claude:toolu_eph", RelationKind.PARENT_OF, "claude:toolu_ord", "claude:toolu_eph")
    conn = sqlite3.connect(path)
    try:
        # Le fichier figé range index avant tables (ordre alphabétique des types) : tables d'abord.
        statements = [line for line in ddl.splitlines() if line and not line.startswith("--")]
        for statement in sorted(statements, key=lambda text: not text.startswith("CREATE TABLE")):
            conn.execute(statement)
        conn.execute("INSERT INTO schema_version(version) VALUES (1)")
        conn.execute("INSERT INTO scene_meta VALUES (1, 'scene-v1', 7, 1, '2026-10-01T00:00:00+00:00', "
                     "'2026-10-01T00:00:00+00:00')")
        conn.executemany("INSERT INTO scene_objects(object_id, position, data) VALUES (?, ?, ?)", rows)
        conn.execute("INSERT INTO scene_relations VALUES (?, 0, ?)",
                     (link.relation_id, json.dumps(link.to_payload(), sort_keys=True)))
        conn.commit()
    finally:
        conn.close()

    def content(target: Path) -> tuple:
        db = sqlite3.connect(target)
        try:
            return (db.execute("SELECT version FROM schema_version").fetchall(),
                    db.execute("SELECT object_id, position, data FROM scene_objects ORDER BY position").fetchall(),
                    db.execute("SELECT relation_id, data FROM scene_relations").fetchall(),
                    db.execute("SELECT scene_id, revision, wire_schema_version FROM scene_meta").fetchall())
        finally:
            db.close()

    before = content(path)
    diagnostics = RecordingDiagnostics()
    service = SceneService(SQLiteSceneRepository(path), diagnostics=diagnostics)
    await service.start()
    snapshot = await service.snapshot()
    await service.close()
    after = content(path)
    assert diagnostics.kinds(SCENE_MIGRATED_KIND) == [("info", {"from": 1, "to": 2, "backup": "scene.sqlite3.v1.bak"})]
    assert after[0] == [(2,)] and before[0] == [(1,)]
    assert after[1:] == before[1:]  # aucune ligne réécrite, effacée ni ajoutée
    assert content(tmp_path / "scene.sqlite3.v1.bak") == before  # sauvegarde automatique d'abord
    assert [item.object_id for item in snapshot.objects] == ["claude:toolu_eph", "claude:toolu_ord"]
    assert all(item.role_ref is None for item in snapshot.objects) and snapshot.relations == (link,)

    # Sur cette scène migrée : l'étoile v1 de l'éphémère reste une étoile terminée ordinaire (aucun retrait
    # automatique), une éphémère nouvelle n'y entre jamais.
    state, store = await open_store(tmp_path / "jarvis.sqlite3")
    world = await World(store, clock=Clock(), scene_repository=SQLiteSceneRepository(path)).start()
    try:
        await world.observe(agent_obs("toolu_eph", WorkStatus.COMPLETED, minute=0.4, ephemeral=True),
                            agent_obs("toolu_new", ephemeral=True),
                            agent_obs("toolu_new", WorkStatus.COMPLETED, minute=0.5, ephemeral=True))
        scene = await world.scene.snapshot()
        assert [item.object_id for item in scene.objects] == ["claude:toolu_eph", "claude:toolu_ord"]
        assert scene.get_object("claude:toolu_eph").exec_state is ExecState.COMPLETED and not scene.archived_ids
    finally:
        await world.stop()
        await state.close()


# ------------------------------------------------------------------ reprise QA (B1, N1)


async def test_a_merged_closure_never_creates_a_star_for_unprojected_work(world):
    """B1 : le relais clôt un doublon fusionné par `cancelled` / `merged`, sans drapeau éphémère (work_ingress)."""

    from jarvis.runtime.work_ingress import MERGED

    assert projector_module.MERGED_CLOSURE == MERGED
    await world.observe(agent_obs("E", ephemeral=True))
    await world.observe(WorkObservation(source=SOURCE, external_id="E", status=WorkStatus.CANCELLED,
                                        observed_at=at(0.3), error_class=MERGED))
    scene = await world.scene.snapshot()
    assert scene.get_object(star_object_id(SOURCE, "E")) is None
    assert scene.get_object(signal_object_id(star_object_id(SOURCE, "E"))) is None
    assert world.projector.stats.skipped_merged == 1
    # Un travail déjà projeté garde le comportement d'avant : la clôture atteint son étoile.
    await world.observe(agent_obs("D"))
    await world.observe(WorkObservation(source=SOURCE, external_id="D", status=WorkStatus.CANCELLED,
                                        observed_at=at(0.4), error_class=MERGED))
    assert (await world.scene.snapshot()).get_object(star_object_id(SOURCE, "D")).exec_state is ExecState.CANCELLED


def single_mission_tree(*relations) -> MissionTree:
    return MissionTree(
        root_mission_id="mis_A", missions=(mission("mis_A", "ainst_A"),),
        instances=(StoredInstance(instance("ainst_A", mission="mis_A", owner=True, external="A")),
                   StoredInstance(instance("ainst_B", mission="mis_A", external="B")),
                   StoredInstance(instance("ainst_C", mission="mis_A", external="C"))),
        relations=relations,
    )


async def recorded_world(tmp_path, source, **projector):
    state, store = await open_store(tmp_path / "jarvis.sqlite3")
    return await World(store, clock=Clock(), missions=source, **projector).start(), state


async def test_a_role_written_on_a_finished_star_never_changes_its_exec_state(tmp_path):
    """M08 : l'étoile est déjà terminée quand son rôle arrive ; `exec_state` reste celui de Work State."""

    world, state = await recorded_world(tmp_path, Recording(single_mission_tree()))
    try:
        await world.observe(agent_obs("A", WorkStatus.COMPLETED, minute=0.2))
        scene = await world.refreshed()
        star_a = scene.get_object(star_object_id(SOURCE, "A"))
        assert star_a.role_ref == RoleRef(role_id="coder", instance_id="ainst_A", mission_id="mis_A", mission_owner=True)
        assert star_a.exec_state is ExecState.COMPLETED
    finally:
        await world.stop()
        await state.close()


async def test_a_relation_with_a_starless_participant_does_not_cost_the_next_ones(tmp_path):
    """M06 : la QA vers C (sans étoile) n'est pas projetée, l'Adversary A/B qui suit l'est, sans échec journalisé."""

    tree = single_mission_tree(
        relation("rel_q", K.QA, "mis_A", [("ainst_C", P.REVIEWER), ("ainst_A", P.REVIEWED)]),
        relation("rel_d", K.ADVERSARY, "mis_A", [("ainst_A", P.PRODUCER), ("ainst_B", P.PRODUCER)], minute=2),
    )
    world, state = await recorded_world(tmp_path, Recording(tree))
    try:
        await world.observe(agent_obs("A"), agent_obs("B"))
        scene = await world.refreshed()
        assert [link.relation_id for link in scene.relations] == ["adversary!rel_d!ainst_A~ainst_B"]
        assert world.diagnostics.kinds(projector_module.SCENE_PROJECTION_FAILED_KIND) == []
    finally:
        await world.stop()
        await state.close()


def test_brain_and_user_cannot_create_under_any_runtime_reserved_relation_id():
    """M05 : tous les préfixes du runtime sont réservés, liens d'agent compris, quelle que soit la nature posée."""

    scene = two_stars()
    for rid in ("attention!x", "parent_of!x", "qa!x", "qa#abc!x", "delegation!x", "communication!x",
                "adversary#y!z", "handoff!x"):
        assert is_runtime_reserved_id(rid), rid
        for actor in (SceneActor.BRAIN, SceneActor.USER):
            forged = SceneRelation(rid, RelationKind.GROUPS, "claude:A", "claude:B")
            update = apply_scene_command(scene, SceneCommand(op=SceneOp.LINK, actor=actor, relation=forged))
            assert (update.outcome, update.reason) == (SceneCommandOutcome.REJECTED_AUTHORITY,
                                                       SceneRefusal.RESERVED_ID), rid
    assert not is_runtime_reserved_id("brain-groups-1")


class ManyMissions:
    """Une mission ouverte et vide par id : compte les lectures."""

    def __init__(self) -> None:
        self.reads: list[str] = []

    async def instance_for_work(self, work_source, work_external_id):
        return None

    async def mission_view(self, mission_id):
        self.reads.append(mission_id)
        return MissionTree(root_mission_id=mission_id, missions=(mission(mission_id, "ainst_X"),), instances=(),
                           relations=()), ()


async def test_a_refresh_pass_reads_at_most_sixteen_missions_and_rotates(tmp_path):
    """M10 : 20 missions suivies, une passe en lit 16 ; la suivante commence par les 4 autres."""

    source = ManyMissions()
    world, state = await recorded_world(tmp_path, source, mission_refresh_s=3600)
    try:
        ids = [f"mis_{index:02d}" for index in range(20)]
        for mission_id in ids:
            world.projector._watch_mission(mission_id)
        await world.projector._refresh_missions()
        assert len(source.reads) == projector_module.MAX_MISSIONS_PER_REFRESH == 16
        first = list(source.reads)
        source.reads.clear()
        await world.projector._refresh_missions()
        assert source.reads[:4] == [mission_id for mission_id in ids if mission_id not in first]
    finally:
        await world.stop()
        await state.close()


async def test_events_read_a_mission_at_most_once_per_interval(tmp_path):
    """M11 : constats rapprochés de deux membres, une lecture ; la mission reste à relire au tour suivant."""

    source = Recording(single_mission_tree())
    world, state = await recorded_world(tmp_path, source, mission_min_interval_s=60, mission_refresh_s=3600)
    try:
        await world.observe(agent_obs("A"))
        await world.observe(WorkObservation(source=SOURCE, external_id="A", status=WorkStatus.RUNNING,
                                            observed_at=at(0.2), kind="agent", label="Agent A", activity="outil 2"))
        await world.observe(agent_obs("B", minute=0.3))
        assert source.calls.count("mission_view") == 1
        assert "mis_A" in world.projector._missions_due
    finally:
        await world.stop()
        await state.close()

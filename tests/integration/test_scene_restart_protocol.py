"""Chemins de redémarrage de bout en bout (handoff jarvis-constellation-scene-runtime, Slice 10).

Chaîne réelle : tracker Claude → observateur → `WorkIngressForwarder` →
`CoreWorkTransport` → `POST /v1/work/observations` → `WorkStateStore` →
`SceneProjector` → scène SQLite, avec un vrai `LocalProtocolServer` et un
nouveau jeton à chaque démarrage de Core. Grâce courte (pas d'attente de 60 s).

- Core redémarre, le Control Center renvoie son état : étoile rendue à l'état
  du tracker, jamais interrompue à tort ;
- Core et Control Center tombent, seul Core revient : « état inconnu » puis
  `interrupted` et son signal à la fin de la grâce ; le terminé ne bouge pas ;
- le Control Center redémarre seul (nouveau producteur) : Core interrompt ce
  que la nouvelle instance ne redit pas, la scène suit ;
- le CLI du cerveau redémarre : le tracker interrompt ses sous-agents, la scène suit ;
- un jeton périmé est relu et le lot renvoyé aussitôt, sans délai croissant.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from jarvis.core.scene_projector import (
    CORE_RESTARTED_UNOBSERVED,
    SCENE_RESTART_GRACE_EXPIRED_KIND,
    SCENE_RESTART_MARKED_KIND,
    signal_object_id,
)
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.scene import ExecState, SceneSnapshot, is_live_signal
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime.agent_tasks import AgentTaskTracker
from jarvis.runtime.work_ingress import CoreWorkTransport, TrackerWorkObserver, WorkIngressForwarder
from tests.integration.test_work_state_protocol import free_port
from tests.unit.test_scene_projector import settled
from tests.unit.test_scene_service import RecordingDiagnostics


class Host:
    """Un Core réel servi sur un port fixe, redémarrable avec un nouveau jeton."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.port = free_port()
        self.token_file = root / "core.token"
        self.core: JarvisCoreApplication | None = None
        self.server: LocalProtocolServer | None = None
        self.diagnostics = RecordingDiagnostics()
        self.starts = 0

    async def start(self, *, grace_s: float = 60.0) -> JarvisCoreApplication:
        self.starts += 1
        token = chr(ord("a") + self.starts) * 48
        self.token_file.write_text(token, encoding="utf-8")
        self.diagnostics = RecordingDiagnostics()
        self.core = JarvisCoreApplication(data_root=self.root / "data", diagnostics=self.diagnostics, scene_restart_grace_s=grace_s)
        await self.core.start()
        self.server = LocalProtocolServer(self.core, host="127.0.0.1", port=self.port, token=token)
        await self.server.start()
        return self.core

    async def stop(self) -> None:
        if self.server is not None:
            await self.server.stop()
        if self.core is not None:
            await self.core.stop()
        self.server = self.core = None

    async def scene(self) -> SceneSnapshot:
        assert self.core is not None
        await settled(self.core.scene_projector)
        return await self.core.scene.snapshot()

    def kinds(self, kind: str) -> list[dict]:
        return [data for _, data in self.diagnostics.kinds(kind)]


class ControlCenter:
    """Le tracker et le relais d'un Control Center, sans page ni agent."""

    def __init__(self, host: Host, *, retry_min_s: float = 0.02, retry_max_s: float = 0.05, resync_interval_s: float = 0.05) -> None:
        self.tracker = AgentTaskTracker(provider="claude")
        self.forwarder = WorkIngressForwarder(
            source="claude",
            transport=CoreWorkTransport(host="127.0.0.1", port=host.port, token_file=host.token_file),
            flush_interval_s=0, retry_min_s=retry_min_s, retry_max_s=retry_max_s, resync_interval_s=resync_interval_s,
        )
        observer = TrackerWorkObserver(self.tracker, self.forwarder.offer)
        self.tracker.subscribe(observer.sync)
        self.forwarder.on_resync = observer.resync

    def agent(self, task_id: str, description: str) -> None:
        self.tracker.observe_claude({"type": "system", "subtype": "task_started", "task_id": task_id, "description": description, "task_type": "local_agent"})

    def done(self, task_id: str) -> None:
        self.tracker.observe_claude({"type": "system", "subtype": "task_notification", "task_id": task_id, "status": "completed", "summary": "Fini."})

    async def kill(self) -> None:
        """Processus tué : plus rien ne part, rien n'est interrompu côté tracker."""

        task, self.forwarder._task = self.forwarder._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self.forwarder.transport.close()


async def until(predicate, *, timeout: float = 10.0) -> None:
    async def poll() -> None:
        while not await predicate():
            await asyncio.sleep(0.02)

    await asyncio.wait_for(poll(), timeout)


def state_of(snapshot: SceneSnapshot, object_id: str) -> ExecState | None:
    item = snapshot.get_object(object_id)
    return None if item is None else item.exec_state


async def test_a_restarted_core_gets_the_star_back_from_the_control_center_without_a_false_interruption(tmp_path):
    host = Host(tmp_path)
    await host.start()
    cc = ControlCenter(host)
    cc.forwarder.start()
    try:
        cc.agent("a1", "Recherche")
        cc.agent("b1", "Tests")
        cc.done("b1")
        await until(lambda: _states(host, {"claude:a1": ExecState.RUNNING, "claude:b1": ExecState.COMPLETED}))
        await host.stop()  # arrêt de Core : le tracker, lui, sait toujours a1 en cours

        await host.start(grace_s=1.0)
        assert host.kinds(SCENE_RESTART_MARKED_KIND)[0] | {"sample": None} == {
            "marked": 1, "already_unknown": 0, "tracked": 1, "terminal_untouched": 1, "job_outcomes": 0, "grace_s": 1.0, "sample": None,
        }
        await until(lambda: _states(host, {"claude:a1": ExecState.RUNNING}))
        await until(lambda: _expired(host))
        snapshot = await host.scene()
    finally:
        await cc.forwarder.aclose()
        await host.stop()
    assert state_of(snapshot, "claude:a1") is ExecState.RUNNING and state_of(snapshot, "claude:b1") is ExecState.COMPLETED
    assert snapshot.get_object(signal_object_id("claude:a1")) is None
    assert host.kinds(SCENE_RESTART_GRACE_EXPIRED_KIND) == [
        {"tracked": 1, "reobserved": 1, "interrupted": 0, "deferred": 0, "left": 0, "failed": 0, "grace_s": 1.0}
    ]


async def test_without_any_producer_the_star_is_unknown_then_interrupted_with_its_signal(tmp_path):
    host = Host(tmp_path)
    await host.start()
    cc = ControlCenter(host)
    cc.forwarder.start()
    try:
        cc.agent("a1", "Recherche")
        cc.agent("b1", "Tests")
        cc.done("b1")
        await until(lambda: _states(host, {"claude:a1": ExecState.RUNNING, "claude:b1": ExecState.COMPLETED}))
        await cc.kill()
        await host.stop()
        completed_before = (await _read_scene(tmp_path)).get_object("claude:b1")

        await host.start(grace_s=0.4)
        assert state_of(await host.core.scene.snapshot(), "claude:a1") is ExecState.UNKNOWN
        await until(lambda: _expired(host))
        snapshot = await host.scene()
    finally:
        await host.stop()
    star = snapshot.get_object("claude:a1")
    attention = snapshot.get_object(signal_object_id("claude:a1"))
    assert star.exec_state is ExecState.INTERRUPTED
    assert attention.payload.title == CORE_RESTARTED_UNOBSERVED and is_live_signal(snapshot, attention.object_id)
    assert snapshot.get_object("claude:b1") == completed_before  # le terminé survit tel quel


async def test_a_control_center_restart_interrupts_what_the_new_instance_does_not_report(tmp_path):
    host = Host(tmp_path)
    await host.start()
    first = ControlCenter(host)
    first.forwarder.start()
    second = ControlCenter(host)
    try:
        first.agent("a1", "Recherche")
        first.agent("a2", "Audit")
        await until(lambda: _states(host, {"claude:a1": ExecState.RUNNING, "claude:a2": ExecState.RUNNING}))
        await first.kill()  # Control Center tué : son CLI et ses sous-agents avec lui

        second.forwarder.start()
        second.agent("c1", "Nouvelle recherche")
        await until(lambda: _states(host, {"claude:a1": ExecState.INTERRUPTED, "claude:a2": ExecState.INTERRUPTED, "claude:c1": ExecState.RUNNING}))
        snapshot = await host.scene()
    finally:
        await second.forwarder.aclose()
        await host.stop()
    for star_id in ("claude:a1", "claude:a2"):
        assert snapshot.get_object(signal_object_id(star_id)).payload.title == "producer_restarted"
    assert host.kinds(SCENE_RESTART_GRACE_EXPIRED_KIND) == []  # Core n'a pas redémarré : rien à trancher


async def test_a_brain_cli_restart_interrupts_its_sub_agents_in_the_scene(tmp_path):
    host = Host(tmp_path)
    await host.start()
    cc = ControlCenter(host)
    cc.forwarder.start()
    try:
        cc.tracker.process_started()
        cc.agent("a1", "Recherche")
        await until(lambda: _states(host, {"claude:a1": ExecState.RUNNING}))
        cc.tracker.process_started()  # nouveau processus du cerveau
        await until(lambda: _states(host, {"claude:a1": ExecState.INTERRUPTED}))
        snapshot = await host.scene()
    finally:
        await cc.forwarder.aclose()
        await host.stop()
    assert snapshot.get_object(signal_object_id("claude:a1")).payload.title == "process_stopped"


async def test_a_brain_restart_seen_only_after_a_core_restart_is_reported_as_the_tracker_says(tmp_path):
    host = Host(tmp_path)
    await host.start()
    cc = ControlCenter(host)
    cc.forwarder.start()
    try:
        cc.agent("a1", "Recherche")
        await until(lambda: _states(host, {"claude:a1": ExecState.RUNNING}))
        await cc.kill()
        await host.stop()
        cc.tracker.process_started()  # le cerveau redémarre pendant que Core est arrêté

        await host.start(grace_s=1.0)
        cc.forwarder.start()
        await until(lambda: _states(host, {"claude:a1": ExecState.INTERRUPTED}))
        await until(lambda: _expired(host))
        snapshot = await host.scene()
    finally:
        await cc.forwarder.aclose()
        await host.stop()
    assert snapshot.get_object(signal_object_id("claude:a1")).payload.title == "process_stopped"
    assert host.kinds(SCENE_RESTART_GRACE_EXPIRED_KIND)[0]["interrupted"] == 0


async def test_a_stale_token_is_reread_and_the_batch_resent_at_once(tmp_path):
    host = Host(tmp_path)
    await host.start()
    # Délai croissant énorme : seul le renvoi immédiat peut réussir dans ce test.
    cc = ControlCenter(host, retry_min_s=30.0, retry_max_s=30.0, resync_interval_s=30.0)
    try:
        cc.agent("a1", "Recherche")
        assert await cc.forwarder.flush() is True
        await host.stop()
        await host.start(grace_s=5.0)
        cc.agent("a2", "Audit")
        assert await cc.forwarder.flush() is True  # 401 → jeton relu → même lot accepté
        assert await cc.forwarder.flush() is True  # renvoi complet armé par le nouveau `store_id`
        snapshot = await host.scene()
    finally:
        await cc.forwarder.aclose()
        await host.stop()
    assert state_of(snapshot, "claude:a1") is ExecState.RUNNING and state_of(snapshot, "claude:a2") is ExecState.RUNNING


async def _states(host: Host, expected: dict[str, ExecState]) -> bool:
    if host.core is None:
        return False
    snapshot = await host.core.scene.snapshot()
    return all(state_of(snapshot, object_id) is state for object_id, state in expected.items())


async def _expired(host: Host) -> bool:
    return bool(host.kinds(SCENE_RESTART_GRACE_EXPIRED_KIND))


async def _read_scene(root: Path) -> SceneSnapshot:
    from jarvis.adapters.sqlite_scene import SQLiteSceneRepository

    repository = SQLiteSceneRepository(root / "data" / "state" / "scene.sqlite3")
    try:
        await repository.initialize()
        return await repository.load()
    finally:
        await repository.close()

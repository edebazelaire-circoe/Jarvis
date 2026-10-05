"""Slice 02 (P1) - le mode suit Core pendant toute la vie du processus Voice.

Avant, le seul abonnement au flux Core vivait dans `SpeechScheduler`, créé
avec une session ACTIVE continue : au repos, et toujours sur
`voice_arch=legacy`, l'observateur restait au défaut. Choisir PRESENTATION
dans le HUD n'ouvrait rien avant le prochain réveil, et le refus explicite de
legacy ne se disait jamais.

Ce que cette suite prouve, par comportement :

- au repos (BACKGROUND, aucun ordonnanceur), un changement de mode atteint le
  contrôleur PRESENTATION, une fois ;
- l'instantané est relu à **chaque** abonnement, pas seulement au premier ;
- deux livraisons d'une même révision (ordonnanceur + suiveur) ne préviennent
  les abonnés qu'une fois ;
- sur legacy, le refus est visible une fois, et aucun micro n'est pris ;
- une coupure de Core ne tue pas le suiveur, et se dit en une ligne.

La sémantique « le genre de Board ne change pas le mode » est déjà tenue par
`test_board_service.py`, `test_board_protocol.py` et
`test_board_memory_contract.py` ; elle n'est pas répétée ici.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from jarvis.audio import input_ownership
from jarvis.core.interaction_mode import INTERACTION_MODE_CHANGED
from jarvis.domain.interaction_mode import InteractionMode
from jarvis.domain.v2 import ProtocolEnvelope, VoiceLifecycleState
from jarvis.runtime.interaction_mode_observer import (
    FOLLOWER_OUTAGE_KIND,
    FOLLOWER_RESUMED_KIND,
    InteractionModeObserver,
    follow_core_mode,
)
from tests.unit.test_interaction_mode_control_plane import CHAMPS_DE_JOURNAL_AUTORISES

EPOCH = "life-1"
REFUSAL = (
    "PRESENTATION demande une session vocale continue : sur « un tour par appui » "
    "(voice_arch=legacy) aucun tour adressé ne peut s'ouvrir."
)


@pytest.fixture(autouse=True)
def clean_input_registry():
    """Le compte de propriétaires d'entrée est un état de **processus**."""

    input_ownership.reset_for_test()
    yield
    input_ownership.reset_for_test()


# ==========================================================================
# Doubles
# ==========================================================================


class RecordingJournal:
    def __init__(self) -> None:
        self.entries: list[dict[str, object]] = []

    def emit(self, kind, message, *, level="info", data=None) -> None:  # noqa: ANN001
        self.entries.append({"kind": kind, "message": message, "level": level, "data": data or {}})

    def of_kind(self, kind: str) -> list[dict[str, object]]:
        return [entry for entry in self.entries if entry["kind"] == kind]


class FakeCore:
    """Core vu de Voice : un bus qui **diffuse** à chaque abonné, comme `CoreEventBus`.

    Diffuser compte : l'ordonnanceur et le suiveur sont deux abonnés, et un
    double qui distribuerait chaque évènement à un seul d'entre eux ferait
    passer un vol d'évènement pour une déduplication.
    """

    def __init__(self, *, snapshot: dict[str, object] | None = None, failures: int = 0) -> None:
        self.snapshot = snapshot or {"mode": "assistant", "revision": 0, "epoch": EPOCH}
        self.failures = failures
        self.subscriptions = 0
        self.snapshot_reads = 0
        self.closed = False
        self._streams: list[asyncio.Queue[ProtocolEnvelope | None]] = []

    async def events(self, *, on_connected=None):  # noqa: ANN001
        self.subscriptions += 1
        if self.failures > 0:
            self.failures -= 1
            raise ConnectionRefusedError("Core injoignable")
        queue: asyncio.Queue[ProtocolEnvelope | None] = asyncio.Queue()
        self._streams.append(queue)
        try:
            if on_connected is not None:
                on_connected()
            while True:
                envelope = await queue.get()
                if envelope is None:
                    return
                yield envelope
        finally:
            self._streams.remove(queue)

    async def interaction_mode(self) -> dict[str, object]:
        self.snapshot_reads += 1
        return dict(self.snapshot)

    def publish(self, envelope: ProtocolEnvelope) -> None:
        for queue in self._streams:
            queue.put_nowait(envelope)

    def drop_streams(self) -> None:
        """Le bus évince ses abonnés : chaque flux se tait sans erreur."""

        for queue in self._streams:
            queue.put_nowait(None)

    @property
    def listening(self) -> int:
        return len(self._streams)

    async def close(self) -> None:
        self.closed = True


def mode_changed(mode: str, revision: int) -> ProtocolEnvelope:
    return ProtocolEnvelope(
        message_type=INTERACTION_MODE_CHANGED,
        payload={"mode": mode, "revision": revision, "epoch": EPOCH},
    )


class IdleWake:
    """Une pile d'éveil qui ne détecte jamais rien : Voice reste au repos."""

    def __init__(self) -> None:
        self.closed = False
        self._never = asyncio.Event()

    async def detections(self):
        await self._never.wait()
        yield "jamais"  # pragma: no cover - jamais atteint

    async def suspend(self) -> None: ...

    async def suspend_for_active_session(self) -> None: ...

    async def resume(self) -> None: ...

    async def close(self) -> None:
        self.closed = True


class FakeCoordinator:
    """Le contrôleur PRESENTATION vu du runtime : il compte ce qu'il reçoit."""

    def __init__(self) -> None:
        self.observed: list[object] = []
        self.closed = False

    def observe_mode(self, mode: object) -> None:
        self.observed.append(mode)

    async def aclose(self, reason: str = "") -> None:
        self.closed = True


class FakeSignals:
    def __init__(self) -> None:
        self.alerts: list[str | None] = []

    def alert(self, message: str | None) -> None:
        self.alerts.append(message)


async def until(predicate, timeout: float = 3.0) -> None:  # noqa: ANN001
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        assert loop.time() < deadline, "condition jamais atteinte"
        await asyncio.sleep(0.005)


async def settle() -> None:
    """Laisser tourner la boucle : ce qui devait arriver est arrivé."""

    for _ in range(20):
        await asyncio.sleep(0)


def runtime_for(core: FakeCore, *, presentation, voice_arch=None, wakeword=None):  # noqa: ANN001
    from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
    from jarvis.v2_config import VoiceArchitecture

    async def factory(context):  # noqa: ANN001
        raise AssertionError("aucune session temps réel n'est ouverte dans ce test")

    return PersistentVoiceRuntime(
        wakeword=wakeword or IdleWake(), core=core, realtime_factory=factory, auto_turn=True,
        voice_arch=voice_arch or VoiceArchitecture.CONTINUOUS_BRAIN, presentation=presentation,
    )


async def stop(runtime, task: asyncio.Task) -> None:  # noqa: ANN001
    runtime.request_switch_exit()
    await asyncio.wait_for(task, timeout=3.0)


# ==========================================================================
# Tests
# ==========================================================================


async def test_mode_change_while_voice_is_idle_reaches_the_coordinator() -> None:
    """Au repos, sans ordonnanceur, le changement de mode atteint le contrôleur."""

    core = FakeCore()
    coordinator = FakeCoordinator()
    runtime = runtime_for(core, presentation=coordinator)
    task = asyncio.create_task(runtime.run())
    try:
        await until(lambda: core.listening == 1)
        await until(lambda: core.snapshot_reads == 1)
        assert runtime.runtime.state is VoiceLifecycleState.BACKGROUND
        assert runtime._speech is None, "aucun ordonnanceur : seul le suiveur peut livrer"

        core.publish(mode_changed("presentation", 1))
        await until(lambda: runtime.interaction_mode.mode is InteractionMode.PRESENTATION)
        await settle()

        assert coordinator.observed == [InteractionMode.PRESENTATION]
        assert runtime.runtime.state is VoiceLifecycleState.BACKGROUND
    finally:
        await stop(runtime, task)
    assert core.listening == 0, "la fermeture du runtime annule le suiveur"
    assert core.closed


async def test_snapshot_adopted_on_each_reconnect() -> None:
    """Chaque abonnement relit l'instantané : ce qui a changé pendant le trou est rattrapé."""

    core = FakeCore(snapshot={"mode": "presentation", "revision": 1, "epoch": EPOCH})
    observer = InteractionModeObserver()
    task = asyncio.create_task(follow_core_mode(observer, core, None, backoff=0))
    try:
        await until(lambda: observer.mode is InteractionMode.PRESENTATION)
        assert core.snapshot_reads == 1

        # Pendant la coupure, l'utilisateur revient à SIMPLE ; l'évènement est perdu.
        core.snapshot = {"mode": "assistant", "revision": 2, "epoch": EPOCH}
        core.drop_streams()
        await until(lambda: core.subscriptions == 2 and core.snapshot_reads == 2)
        await until(lambda: observer.mode is InteractionMode.ASSISTANT)

        assert observer.revision == 2
        assert not task.done()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_double_delivery_notifies_listeners_once() -> None:
    """Ordonnanceur et suiveur livrent la même révision : un seul appel d'abonné."""

    from jarvis.runtime.speech_scheduler import SpeechScheduler

    core = FakeCore()
    observer = InteractionModeObserver()
    calls: list[InteractionMode] = []
    observer.add_listener(calls.append)
    scheduler = SpeechScheduler(
        core=SimpleNamespace(), conversation_id="conv-02", session=SimpleNamespace(),
        interaction_mode=observer,
    )
    task = asyncio.create_task(follow_core_mode(observer, core, None, backoff=0))
    try:
        await until(lambda: core.listening == 1 and core.snapshot_reads == 1)
        envelope = mode_changed("presentation", 1)

        core.publish(envelope)
        await until(lambda: observer.mode is InteractionMode.PRESENTATION)
        await scheduler.handle_core_event(envelope)
        await settle()

        assert calls == [InteractionMode.PRESENTATION]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_legacy_architecture_refuses_presentation_visibly_once() -> None:
    """Sur legacy, le refus se dit **au changement de mode**, une fois, sans prendre le micro."""

    from jarvis.runtime.presentation_runtime import PresentationCoordinator, PresentationWakeRouter
    from jarvis.v2_config import VoiceArchitecture

    journal = RecordingJournal()
    signals = FakeSignals()
    builds: list[str] = []

    def build(session_id: str):  # noqa: ANN202
        builds.append(session_id)
        raise AssertionError("la séance (et son hub micro) ne doit jamais être construite")

    holder: dict[str, object] = {}
    coordinator = PresentationCoordinator(
        router=PresentationWakeRouter(simple=IdleWake(), journal=journal),
        build=build, journal=journal, signals=signals,
        # La pré-condition de `jarvis/app.py`, lue sur le runtime.
        precondition=lambda: None if holder["voice"].continuous else REFUSAL,
    )
    core = FakeCore()
    runtime = runtime_for(core, presentation=coordinator, voice_arch=VoiceArchitecture.LEGACY,
                          wakeword=coordinator.router)
    holder["voice"] = runtime
    assert not runtime.continuous
    task = asyncio.create_task(runtime.run())
    try:
        await until(lambda: core.listening == 1 and core.snapshot_reads == 1)

        core.publish(mode_changed("presentation", 1))
        await until(lambda: coordinator.entry_failures == 1)
        # La même révision relivrée (instantané d'une reprise) ne redit rien.
        core.publish(mode_changed("presentation", 1))
        await settle()

        assert [message for message in signals.alerts if message] == [REFUSAL]
        refused = [entry for entry in journal.entries
                   if entry["data"].get("code") == "presentation_architecture_unsupported"]  # type: ignore[union-attr]
        assert [entry["kind"] for entry in refused] == ["presentation.runtime.entry_refused"]
        assert refused[0]["level"] == "error"
        assert builds == [], "aucun hub construit, donc aucun micro ouvert"
        assert input_ownership.open_input_stream_count() == 0
        assert coordinator.audio is None
    finally:
        await stop(runtime, task)


async def test_follower_survives_core_outage_and_says_so_once() -> None:
    """Trois échecs d'abonnement : une ligne de coupure, une de reprise, et le mode rattrapé."""

    journal = RecordingJournal()
    core = FakeCore(snapshot={"mode": "presentation", "revision": 4, "epoch": EPOCH}, failures=3)
    observer = InteractionModeObserver()
    task = asyncio.create_task(follow_core_mode(observer, core, journal, backoff=0))
    try:
        await until(lambda: observer.mode is InteractionMode.PRESENTATION)
        assert core.subscriptions == 4
        assert not task.done(), "le suiveur ne lève jamais"

        outages = journal.of_kind(FOLLOWER_OUTAGE_KIND)
        assert len(outages) == 1
        assert outages[0]["level"] == "warning"
        assert outages[0]["data"]["code"] == "interaction_mode_follower_outage"  # type: ignore[index]
        assert "ConnectionRefusedError" in str(outages[0]["message"])
        assert len(journal.of_kind(FOLLOWER_RESUMED_KIND)) == 1

        # Une seconde coupure, distincte, a droit à sa propre ligne.
        core.drop_streams()
        await until(lambda: core.subscriptions == 5 and core.listening == 1)
        assert len(journal.of_kind(FOLLOWER_OUTAGE_KIND)) == 2
        assert len(journal.of_kind(FOLLOWER_RESUMED_KIND)) == 2

        # Codes et noms de type seulement : la liste des champs de toute ligne
        # `interaction.mode.*` (`test_interaction_mode_control_plane.py`).
        for entry in journal.entries:
            assert set(entry["data"]) <= CHAMPS_DE_JOURNAL_AUTORISES, entry  # type: ignore[arg-type]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_the_refusal_alert_clears_when_the_mode_leaves_presentation() -> None:
    """Polish (p5) : l'alerte de refus ne reste pas à l'écran une fois revenu en SIMPLE.

    Le canal d'alerte est partagé : un contrôleur qui n'a rien posé n'efface rien.
    """

    from jarvis.runtime.presentation_runtime import PresentationCoordinator, PresentationWakeRouter

    journal, signals = RecordingJournal(), FakeSignals()
    coordinator = PresentationCoordinator(
        router=PresentationWakeRouter(simple=IdleWake(), journal=journal),
        build=lambda session_id: pytest.fail("un refus ne construit aucune séance"),
        journal=journal, signals=signals, precondition=lambda: REFUSAL,
    )
    untouched = FakeSignals()
    quiet = PresentationCoordinator(
        router=PresentationWakeRouter(simple=IdleWake(), journal=journal),
        build=lambda session_id: pytest.fail("SIMPLE ne compose rien"),
        journal=journal, signals=untouched,
    )
    try:
        await coordinator.apply(InteractionMode.PRESENTATION)
        assert signals.alerts == [REFUSAL]

        await coordinator.apply(InteractionMode.ASSISTANT)
        assert signals.alerts == [REFUSAL, None], "l'alerte s'efface au retour en SIMPLE"
        await coordinator.apply(InteractionMode.ASSISTANT)
        assert signals.alerts == [REFUSAL, None], "une fois"
        assert [entry["data"]["code"] for entry in journal.of_kind("presentation.runtime.alert_cleared")] == [
            "presentation_alert_cleared"]

        await quiet.apply(InteractionMode.ASSISTANT)
        assert untouched.alerts == [], "rien posé, rien effacé"
    finally:
        await coordinator.aclose()
        await quiet.aclose()


async def test_follower_rereads_the_token_after_an_independent_core_restart(tmp_path) -> None:
    """Polish (p4) : Core redémarre seul avec un jeton neuf ; le suiveur le relit et suit.

    Le vrai client, le vrai serveur loopback : la poignée de main refusée est
    un vrai 401 de `/v1/events`, pas une exception imitée.
    """

    from jarvis.core.v2_app import JarvisCoreApplication
    from jarvis.protocol.client import LocalCoreClient
    from jarvis.protocol.server import LocalProtocolServer
    from jarvis.runtime.interaction_mode_observer import FOLLOWER_TOKEN_KIND
    from tests.integration.test_v2_brain_protocol import free_port

    first, second = "a" * 48, "b" * 48
    token_file = tmp_path / "core.token"
    token_file.write_text(first, encoding="utf-8")
    port = free_port()
    core = JarvisCoreApplication(data_root=tmp_path / "data")
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=first)
    await server.start()
    client = LocalCoreClient(host="127.0.0.1", port=port, token=first)
    journal, observer = RecordingJournal(), InteractionModeObserver()
    task = asyncio.create_task(follow_core_mode(observer, client, journal, backoff=0.01, token_file=token_file))
    other = LocalCoreClient(host="127.0.0.1", port=port, token=second)
    try:
        # Abonné : l'instantané relu à la connexion porte l'époque de Core.
        await until(lambda: observer.epoch is not None)

        # Core « redémarre » seul : il n'accepte plus que son jeton neuf, écrit
        # sur disque, et la connexion d'avant tombe. (Arrêter le serveur pour de
        # bon attendrait ~30 s la fermeture du WebSocket ouvert ; du point de
        # vue du client, c'est la même chose.)
        server.token = second
        token_file.write_text(second, encoding="utf-8")
        await client.close()

        await until(lambda: len(journal.of_kind(FOLLOWER_RESUMED_KIND)) == 1, timeout=5.0)
        await other.set_interaction_mode(InteractionMode.PRESENTATION.value)
        await until(lambda: observer.mode is InteractionMode.PRESENTATION, timeout=5.0)

        assert client.token == second
        [reread] = journal.of_kind(FOLLOWER_TOKEN_KIND)
        assert reread["data"] == {"code": "interaction_mode_follower_token_reread"}
        assert first not in str(journal.entries) and second not in str(journal.entries), "jamais le jeton"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await other.close()
        await client.close()
        await server.stop()
        await core.stop()

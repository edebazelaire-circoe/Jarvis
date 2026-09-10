from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from jarvis.domain.v2 import AddressingDecision
from jarvis.runtime.realtime_audio import ConservativeAddressingClassifier
from jarvis.runtime.voice_v2 import UsefulActivityTracker


class FakeClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)
    def now(self): return self.value
    async def sleep(self, seconds): self.value += timedelta(seconds=seconds)
    def advance(self, seconds): self.value += timedelta(seconds=seconds)


def test_ambient_noise_does_not_extend_active_session():
    clock = FakeClock()
    tracker = UsefulActivityTracker(timeout_s=10, clock=clock)
    clock.advance(8)
    tracker.reset(AddressingDecision.AMBIENT)
    clock.advance(3)
    assert tracker.expired() is True


def test_a_routed_uncertain_turn_does_not_extend_the_active_session():
    """Décision 44 : router vers le cerveau n'est pas réarmer le minuteur.

    Un tour `UNCERTAIN` part désormais au cerveau en mode continu, mais il ne
    vaut toujours pas activité utile : seul un tour adressé — ou un signe de vie
    du cerveau (Décision 32) — rend du temps à la session. Sans cette
    séparation, une conversation de fond assez longue tiendrait la session
    ouverte indéfiniment, ce que la Décision 10 interdit.
    """
    clock = FakeClock()
    tracker = UsefulActivityTracker(timeout_s=10, clock=clock)
    clock.advance(8)
    tracker.reset(AddressingDecision.UNCERTAIN)
    clock.advance(3)
    assert tracker.expired() is True


def test_addressed_followup_resets_useful_timer():
    clock = FakeClock()
    tracker = UsefulActivityTracker(timeout_s=10, clock=clock)
    clock.advance(8)
    tracker.reset(AddressingDecision.ADDRESSED)
    clock.advance(3)
    assert tracker.expired() is False


def test_a_zero_timeout_never_expires():
    """`0` veut dire « jamais » : seule une action explicite rend la main."""
    clock = FakeClock()
    tracker = UsefulActivityTracker(timeout_s=0, clock=clock)
    assert tracker.expired() is False
    clock.advance(24 * 3600)
    tracker.reset(AddressingDecision.AMBIENT)
    assert tracker.expired() is False


def test_contextual_addressing_is_conservative():
    classifier = ConservativeAddressingClassifier()
    assert classifier.classify("Jarvis donne-moi l'heure", active=False) is AddressingDecision.ADDRESSED
    assert classifier.classify("une longue conversation ambiante entre plusieurs personnes qui ne concerne pas du tout l'assistant", active=True) is AddressingDecision.UNCERTAIN
    assert classifier.classify("Et demain ?", active=True) is AddressingDecision.ADDRESSED


def test_a_real_request_without_wake_prefix_is_classified_uncertain():
    """Le défaut à l'origine de la Décision 44, énoncé sur de vraies phrases.

    Ces deux demandes sont on ne peut plus adressées, mais dépassent huit mots
    sans commencer par « jarvis » ni finir par « ? » : le classifieur rend
    `UNCERTAIN`. C'est pour cela que la surface ne peut pas être l'arbitre de
    l'intention en mode continu — elle jetait ces tours-là en silence.
    """
    classifier = ConservativeAddressingClassifier()
    assert classifier.classify(
        "Regarde dans mon Drive le fichier des comptes de janvier et donne moi le total", active=True
    ) is AddressingDecision.UNCERTAIN
    assert classifier.classify(
        "Peux tu me preparer un resume de tous les mails recus hier matin s il te plait", active=True
    ) is AddressingDecision.UNCERTAIN


def test_jarvis_mute_is_classified_addressed_so_it_never_becomes_uncertain():
    """Garde de conception : le routage `UNCERTAIN` ne peut pas avaler un mute.

    « Jarvis mute » est reconnu **après** le garde d'adressage, donc la commande
    ne survit que si elle est classée `ADDRESSED`. Elle l'est par construction —
    toute phrase commençant par « jarvis » l'est, session active ou non — et ce
    test le fige : si le classifieur changeait, le mute partirait au cerveau au
    lieu de couper la voix.
    """
    classifier = ConservativeAddressingClassifier()
    for text in ("Jarvis mute", "jarvis, mute", "JARVIS MUTE"):
        assert classifier.classify(text, active=True) is AddressingDecision.ADDRESSED
        assert classifier.classify(text, active=False) is AddressingDecision.ADDRESSED


class _StubBridge:
    def __init__(self, tool_in_flight: bool) -> None:
        self.tool_in_flight = tool_in_flight


class _RecordingJournal:
    def __init__(self) -> None:
        self.kinds: list[str] = []

    def emit(self, kind: str, message: str, *, level: str = "info", data=None) -> None:  # noqa: ANN001
        del message, level, data
        self.kinds.append(kind)


def _expired_runtime(*, tool_in_flight: bool, timeout_s: float = 10, journal=None):  # noqa: ANN001
    """Un runtime ACTIVE dont le délai d'inactivité vient d'expirer."""
    from jarvis.domain.v2 import VoiceLifecycleState
    from jarvis.runtime.voice_v2 import PersistentVoiceRuntime

    clock = FakeClock()
    runtime = PersistentVoiceRuntime(
        wakeword=None,  # type: ignore[arg-type]
        core=None,  # type: ignore[arg-type]
        realtime_factory=None,  # type: ignore[arg-type]
        active_timeout_s=timeout_s,
        clock=clock,
        journal=journal,
    )
    runtime.runtime.state = VoiceLifecycleState.ACTIVE
    runtime._bridge = _StubBridge(tool_in_flight)
    clock.advance(30)
    return runtime, clock


async def test_the_inactivity_timeout_never_cuts_a_running_tool():
    """L'incident du 8 septembre à 15:48:17 : Claude travaillait encore — la
    console le montrait — quand les 90 s de délai d'inactivité ont rendu la
    main. Sans un mot, sans vocal, et le résultat n'avait plus où revenir."""
    runtime, clock = _expired_runtime(tool_in_flight=True)

    assert await runtime.check_timeout() is False
    # Le compteur est reparti : la session tient tant que l'outil travaille.
    clock.advance(5)
    assert runtime.activity.expired() is False


async def test_the_inactivity_timeout_still_ends_an_idle_session():
    """Le garde-fou ne doit pas devenir une session éternelle."""
    runtime, _ = _expired_runtime(tool_in_flight=False)
    muted: list[int] = []

    async def fake_mute() -> None:
        muted.append(1)

    runtime.mute = fake_mute  # type: ignore[method-assign]

    assert await runtime.check_timeout() is True
    assert muted == [1]


@pytest.mark.parametrize("tool_in_flight", [False, True])
async def test_a_zero_timeout_never_mutes_nor_reports_a_deferral(tool_in_flight):
    """Délai à 0 : la boucle de supervision interroge chaque seconde, et rien
    ne doit en sortir — ni mute, ni un `voice.timeout_deferred` par tic."""
    journal = _RecordingJournal()
    runtime, clock = _expired_runtime(tool_in_flight=tool_in_flight, timeout_s=0, journal=journal)
    muted: list[int] = []

    async def fake_mute() -> None:
        muted.append(1)

    runtime.mute = fake_mute  # type: ignore[method-assign]

    for _ in range(3):
        clock.advance(3600)
        assert await runtime.check_timeout() is False
    assert muted == []
    assert "voice.timeout" not in journal.kinds
    assert "voice.timeout_deferred" not in journal.kinds

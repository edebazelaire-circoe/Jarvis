from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


def test_addressed_followup_resets_useful_timer():
    clock = FakeClock()
    tracker = UsefulActivityTracker(timeout_s=10, clock=clock)
    clock.advance(8)
    tracker.reset(AddressingDecision.ADDRESSED)
    clock.advance(3)
    assert tracker.expired() is False


def test_contextual_addressing_is_conservative():
    classifier = ConservativeAddressingClassifier()
    assert classifier.classify("Jarvis donne-moi l'heure", active=False) is AddressingDecision.ADDRESSED
    assert classifier.classify("une longue conversation ambiante entre plusieurs personnes qui ne concerne pas du tout l'assistant", active=True) is AddressingDecision.UNCERTAIN
    assert classifier.classify("Et demain ?", active=True) is AddressingDecision.ADDRESSED

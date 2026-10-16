"""`VoiceChannelService` : demande idempotente, expiration, acquittements, réveil pendant `switching`."""

from __future__ import annotations

import inspect
import uuid

import pytest

from jarvis.core.voice_channel import MAX_REMEMBERED_REQUESTS, VoiceChannelService
from jarvis.domain.voice_channel import VOICE_DISABLE_TIMEOUT_S


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class Diagnostics:
    def __init__(self) -> None:
        self.lines: list[tuple[str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None):
        self.lines.append((kind, data or {}))

    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.lines]


@pytest.fixture
def env():
    clock, diagnostics = Clock(), Diagnostics()
    return VoiceChannelService(diagnostics=diagnostics, clock=clock), clock, diagnostics


class Voice:
    """Un processus Voice : une incarnation, un `seq` croissant."""

    def __init__(self, service: VoiceChannelService, incarnation: str = "voice-a") -> None:
        self.service, self.incarnation, self.seq = service, incarnation, 0

    def report(self, state: str, ack: dict | None = None) -> dict:
        self.seq += 1
        return self.service.report({"schema_version": 1, "voice_incarnation_id": self.incarnation, "seq": self.seq,
                                    "lifecycle_state": state, "conversation_id": "conv-1", "ack": ack})


def cid() -> str:
    return str(uuid.uuid4())


def test_write_gate_is_synchronous():
    assert not inspect.iscoroutinefunction(VoiceChannelService.write_gate)


def test_unknown_at_start_then_absent_then_reported(env):
    service, clock, _ = env
    assert service.write_gate() == "voice_unknown"
    clock.now += 5.0
    assert service.write_gate() is None
    assert service.snapshot()["voice"]["state"] == "absent"
    Voice(service).report("active")
    assert service.write_gate() == "voice_active"


def test_disable_round_trip_accepted(env):
    service, clock, diagnostics = env
    voice = Voice(service)
    voice.report("active")
    client_id = cid()

    status, body = service.disable({"client_request_id": client_id})
    assert status == 202 and body["state"] == "switching" and body["request_id"].startswith("vcr-")
    assert service.write_gate() == "voice_switching"

    clock.now += 1.0
    answer = voice.report("active")
    assert answer["disable_request"]["request_id"] == body["request_id"]
    assert isinstance(answer["disable_request"]["requested_at"], str)

    clock.now += 0.5
    answer = voice.report("background", ack={"request_id": body["request_id"], "result": "accepted", "code": None})
    assert answer["disable_request"] is None
    snapshot = service.snapshot()
    assert snapshot["chat_writable"] is True and snapshot["locked_reason"] is None
    assert snapshot["voice"]["state"] == "background"
    assert snapshot["voice"]["request"] == {"request_id": body["request_id"], "status": "accepted", "code": None}
    assert diagnostics.kinds() == ["core.voice_channel.disable_requested", "core.voice_channel.disable_settled"]
    # ids et codes seulement
    assert set(diagnostics.lines[0][1]) == {"request_id", "voice_state"}


def test_same_client_request_id_is_idempotent(env):
    service, clock, _ = env
    Voice(service).report("active")
    client_id = cid()
    first = service.disable({"client_request_id": client_id})
    revision = service.revision
    again = service.disable({"client_request_id": client_id})

    assert again[1]["request_id"] == first[1]["request_id"]
    assert service.revision == revision
    # Une autre demande pendant la première : on rend la demande en cours, pas une seconde.
    other = service.disable({"client_request_id": cid()})
    assert other[1]["request_id"] == first[1]["request_id"]


def test_nothing_to_do_when_absent_or_background(env):
    service, clock, _ = env
    clock.now += 6.0
    assert service.disable({"client_request_id": cid()}) == (200, {"state": "absent", "request_id": None,
                                                                    "status": None})
    Voice(service).report("background")
    assert service.disable({"client_request_id": cid()})[1]["request_id"] is None


def test_request_during_startup_grace_is_created(env):
    service, _, _ = env
    status, body = service.disable({"client_request_id": cid()})
    assert status == 202 and body["request_id"] is not None


def test_request_expires_after_ten_seconds(env):
    service, clock, diagnostics = env
    voice = Voice(service)
    voice.report("active")
    _, body = service.disable({"client_request_id": cid()})

    clock.now += VOICE_DISABLE_TIMEOUT_S - 0.1
    voice.report("active")
    assert service.write_gate() == "voice_switching"
    clock.now += 0.1
    assert service.write_gate() == "voice_active"
    request = service.snapshot()["voice"]["request"]
    assert request == {"request_id": body["request_id"], "status": "expired", "code": "voice_disable_expired"}
    assert voice.report("active")["disable_request"] is None
    assert diagnostics.lines[-1] == ("core.voice_channel.disable_settled",
                                     {"request_id": body["request_id"], "status": "expired",
                                      "code": "voice_disable_expired"})
    # Un acquittement tardif ne change plus rien.
    voice.report("background", ack={"request_id": body["request_id"], "result": "accepted", "code": None})
    assert service.snapshot()["voice"]["request"]["status"] == "expired"


def test_failed_ack_falls_back_to_the_last_report(env):
    service, _, _ = env
    voice = Voice(service)
    voice.report("active")
    _, body = service.disable({"client_request_id": cid()})

    voice.report("error", ack={"request_id": body["request_id"], "result": "failed", "code": "voice_disable_failed"})

    snapshot = service.snapshot()
    assert snapshot["voice"]["state"] == "error" and snapshot["locked_reason"] == "voice_error"
    assert snapshot["voice"]["request"]["status"] == "failed"
    assert snapshot["voice"]["request"]["code"] == "voice_disable_failed"
    # Réessayer : une nouvelle demande est possible.
    assert service.disable({"client_request_id": cid()})[0] == 202


def test_accepted_ack_with_a_non_background_state_is_a_failure(env):
    service, _, _ = env
    voice = Voice(service)
    voice.report("active")
    _, body = service.disable({"client_request_id": cid()})
    voice.report("error", ack={"request_id": body["request_id"], "result": "accepted", "code": None})
    assert service.snapshot()["voice"]["request"]["status"] == "failed"
    assert service.snapshot()["voice"]["request"]["code"] == "voice_disable_failed"


def test_background_without_ack_settles_the_request(env):
    service, _, _ = env
    voice = Voice(service)
    voice.report("active")
    service.disable({"client_request_id": cid()})
    voice.report("background")  # mute par délai ou par la touche
    assert service.snapshot()["voice"]["request"]["status"] == "accepted"
    assert service.write_gate() is None


def test_wake_up_during_switching_stays_locked_and_relocks_after(env):
    service, clock, _ = env
    voice = Voice(service)
    voice.report("active")
    _, body = service.disable({"client_request_id": cid()})
    voice.report("background", ack={"request_id": body["request_id"], "result": "accepted", "code": None})
    assert service.write_gate() is None
    voice.report("connecting")  # réveil : le Chat se reverrouille
    assert service.write_gate() == "voice_connecting"

    _, again = service.disable({"client_request_id": cid()})
    voice.report("connecting")  # réveil pendant switching : toujours verrouillé
    assert service.write_gate() == "voice_switching"
    clock.now += VOICE_DISABLE_TIMEOUT_S
    voice.report("active")
    assert service.write_gate() == "voice_active"
    assert service.snapshot()["voice"]["request"]["status"] == "expired"


def test_stale_seq_is_ignored_and_journaled(env):
    service, _, diagnostics = env
    send = lambda seq, state: service.report({"schema_version": 1, "voice_incarnation_id": "voice-a", "seq": seq,  # noqa: E731
                                              "lifecycle_state": state, "conversation_id": None, "ack": None})
    assert send(5, "background")["accepted"] is True
    assert send(5, "active")["accepted"] is False
    assert send(3, "active")["accepted"] is False
    assert service.write_gate() is None
    assert diagnostics.kinds().count("core.voice_channel.report_rejected") == 2
    # Nouvelle incarnation (Voice relancé) : remplace, même avec un seq plus petit.
    assert service.report({"schema_version": 1, "voice_incarnation_id": "voice-b", "seq": 1,
                           "lifecycle_state": "active", "conversation_id": None, "ack": None})["accepted"] is True
    assert service.write_gate() == "voice_active"


def test_report_age_and_revision(env):
    service, clock, _ = env
    assert service.snapshot()["voice"]["report_age_ms"] is None
    voice = Voice(service)
    voice.report("active")
    revision = service.revision
    voice.report("active")  # même état : pas de révision
    assert service.revision == revision
    clock.now += 0.4
    assert service.snapshot()["voice"]["report_age_ms"] == 400
    voice.report("background")
    assert service.revision == revision + 1


def test_a_new_core_has_a_new_epoch():
    assert VoiceChannelService().epoch != VoiceChannelService().epoch


@pytest.mark.parametrize("payload", [None, [], {}, {"client_request_id": "nope"}, {"client_request_id": 4},
                                     {"client_request_id": str(uuid.uuid4()), "x": 1}])
def test_disable_payload_is_strict(env, payload):
    with pytest.raises(ValueError):
        env[0].disable(payload)


def test_remembered_requests_are_bounded(env):
    service, clock, _ = env
    voice = Voice(service)
    for _ in range(MAX_REMEMBERED_REQUESTS + 5):
        voice.report("active")
        _, body = service.disable({"client_request_id": cid()})
        voice.report("error", ack={"request_id": body["request_id"], "result": "failed", "code": None})
    assert len(service._requests) == MAX_REMEMBERED_REQUESTS


def test_a_broken_journal_never_changes_the_lock():
    class Broken:
        def emit(self, *args, **kwargs):
            raise OSError("disk full")

    service = VoiceChannelService(diagnostics=Broken())
    service.report({"schema_version": 1, "voice_incarnation_id": "voice-a", "seq": 1,
                    "lifecycle_state": "active", "conversation_id": None, "ack": None})
    assert service.disable({"client_request_id": cid()})[0] == 202
    assert service.write_gate() == "voice_switching"

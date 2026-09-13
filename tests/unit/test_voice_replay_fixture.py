from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from tests.replay.voice_replay import (
    MAX_INT64,
    MAX_STEPS,
    MAX_TIMELINE_MS,
    ReplayClock,
    ReplayDriver,
    ReplayFixtureError,
    load_replay_fixture,
    loads_replay_fixture,
)


FIXTURES = Path(__file__).parents[1] / "fixtures" / "voice_replay"
SCENARIOS = {
    "thinking_pause_wait",
    "stale_ack_35_9s",
    "backend_nonblocking_85_7s",
    "spoken_divergence",
    "bus_cluster_7",
    "confirmed_interrupt_missing_item",
    "provider_cancel_after_generation",
    "missing_terminal_stall",
    "manual_close_late_results",
}


def valid_document() -> dict[str, object]:
    return {
        "schema": "jarvis.voice_replay",
        "schema_version": 1,
        "scenario_id": "valid_scenario",
        "origin": "2026-09-11T15:43:35+02:00",
        "provenance": {
            "source_path": "tasks/example/sources/transcript.md",
            "source_kind": "human_trace_reconstruction",
            "reported": [{"source_ref": "lines 1-2", "fact": "reported fact"}],
            "derived": [{"source_ref": "lines 1-2", "fact": "derived relation"}],
            "constructed": [{"source_ref": "fixture design", "fact": "synthetic identifier"}],
        },
        "steps": [
            {
                "at_ms": 0,
                "port": "user",
                "action": "turn",
                "data": {"turn_id": "turn-1", "content_tag": "synthetic_turn"},
            }
        ],
    }


def encoded(document: dict[str, object]) -> str:
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"))


def raises_code(document: dict[str, object], code: str) -> None:
    with pytest.raises(ReplayFixtureError) as caught:
        loads_replay_fixture(encoded(document))
    assert caught.value.code == code


def test_all_sanitized_incident_fixtures_load_with_traceable_provenance():
    paths = sorted(FIXTURES.glob("*.json"))
    fixtures = [load_replay_fixture(path) for path in paths]

    assert {fixture.scenario_id for fixture in fixtures} == SCENARIOS
    assert all(fixture.provenance.reported for fixture in fixtures)
    assert all(fixture.provenance.constructed for fixture in fixtures)
    assert all(fixture.provenance.source_path.endswith("transcript-2026-09-11.md") for fixture in fixtures)
    assert next(f for f in fixtures if f.scenario_id == "stale_ack_35_9s").steps[-1].at_ms == 35_900
    bus = next(f for f in fixtures if f.scenario_id == "bus_cluster_7")
    assert sum(step.kind == "owner.candidate" for step in bus.steps) == 7
    assert sum(step.kind == "owner.rejected" for step in bus.steps) == 7


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("schema", "jarvis.other", "fixture_schema_unsupported"),
        ("schema_version", True, "fixture_version_unsupported"),
        ("schema_version", 2, "fixture_version_unsupported"),
        ("scenario_id", "../escape", "fixture_scenario_invalid"),
        ("origin", "2026-09-11T15:43:35", "fixture_origin_invalid"),
    ],
)
def test_header_rejects_wrong_schema_version_id_and_naive_time(field, value, code):
    document = valid_document()
    document[field] = value
    raises_code(document, code)


@pytest.mark.parametrize("where", ["fixture", "provenance", "evidence", "step"])
def test_unknown_fields_are_rejected_at_every_structured_level(where):
    document = valid_document()
    if where == "fixture":
        document["surprise"] = True
    elif where == "provenance":
        document["provenance"]["surprise"] = True  # type: ignore[index]
    elif where == "evidence":
        document["provenance"]["reported"][0]["surprise"] = True  # type: ignore[index]
    else:
        document["steps"][0]["surprise"] = True  # type: ignore[index]
    raises_code(document, "fixture_shape_invalid")


def test_duplicate_keys_and_nonfinite_numbers_are_rejected_before_decode():
    raw = encoded(valid_document())
    duplicate = raw.replace('"schema":"jarvis.voice_replay"', '"schema":"jarvis.voice_replay","schema":"jarvis.voice_replay"')
    with pytest.raises(ReplayFixtureError) as duplicate_error:
        loads_replay_fixture(duplicate)
    assert duplicate_error.value.code == "fixture_duplicate_field"

    nonfinite = raw.replace('"at_ms":0', '"at_ms":NaN')
    with pytest.raises(ReplayFixtureError) as nonfinite_error:
        loads_replay_fixture(nonfinite)
    assert nonfinite_error.value.code == "fixture_nonfinite_number"

    overflow = raw.replace('"at_ms":0', '"at_ms":1e999')
    with pytest.raises(ReplayFixtureError) as overflow_error:
        loads_replay_fixture(overflow)
    assert overflow_error.value.code == "fixture_nonfinite_number"


@pytest.mark.parametrize("at_ms", [True, -1, 1.5, "1", 10**100, MAX_TIMELINE_MS + 1])
def test_timestamps_are_nonnegative_integer_milliseconds(at_ms):
    document = valid_document()
    document["steps"][0]["at_ms"] = at_ms  # type: ignore[index]
    raises_code(document, "fixture_timeline_invalid")


def test_timeline_accepts_documented_seven_day_boundary():
    document = valid_document()
    document["steps"][0]["at_ms"] = MAX_TIMELINE_MS  # type: ignore[index]
    assert loads_replay_fixture(encoded(document)).steps[0].at_ms == MAX_TIMELINE_MS


def test_timestamps_may_tie_but_never_go_backwards():
    document = valid_document()
    document["steps"] = [
        {"at_ms": 1, "port": "control", "action": "checkpoint", "data": {"checkpoint_id": "a"}},
        {"at_ms": 1, "port": "control", "action": "checkpoint", "data": {"checkpoint_id": "b"}},
    ]
    assert len(loads_replay_fixture(encoded(document)).steps) == 2
    document["steps"][1]["at_ms"] = 0  # type: ignore[index]
    raises_code(document, "fixture_timeline_invalid")


@pytest.mark.parametrize(
    ("port", "action"),
    [("shell", "run"), ("provider", "arbitrary_method"), ("owner", "output_done")],
)
def test_action_vocabulary_is_closed_and_port_specific(port, action):
    document = valid_document()
    document["steps"][0].update(port=port, action=action)  # type: ignore[index]
    raises_code(document, "fixture_action_unknown")


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda data: data.pop("turn_id"), "fixture_action_data_invalid"),
        (lambda data: data.update(surprise="value"), "fixture_action_data_invalid"),
        (lambda data: data.update(turn_id="x" * 129), "fixture_value_too_long"),
        (lambda data: data.update(turn_id="unsafe id"), "fixture_action_data_invalid"),
        (lambda data: data.update(addressing="maybe"), "fixture_action_data_invalid"),
    ],
)
def test_action_payload_rejects_missing_unknown_unbounded_and_invalid_enum_fields(mutate, code):
    document = valid_document()
    mutate(document["steps"][0]["data"])  # type: ignore[index]
    raises_code(document, code)


@pytest.mark.parametrize(
    "data",
    [
        {"candidate_id": "candidate", "kind": "ack", "intent_epoch": True},
        {"candidate_id": "candidate", "kind": "ack", "ttl_ms": False},
        {"candidate_id": "candidate", "kind": "ack", "intent_epoch": MAX_INT64 + 1},
        {"candidate_id": "candidate", "kind": "ack", "ttl_ms": 10**100},
        {"candidate_id": "candidate", "kind": "ack", "ttl_ms": MAX_TIMELINE_MS + 1},
    ],
)
def test_action_integer_fields_reject_booleans(data):
    document = valid_document()
    document["steps"] = [{"at_ms": 0, "port": "scheduler", "action": "enqueue", "data": data}]
    raises_code(document, "fixture_action_data_invalid")


def test_action_boolean_fields_reject_integers_and_output_busy_requires_identity():
    document = valid_document()
    document["steps"] = [
        {
            "at_ms": 0,
            "port": "device",
            "action": "release",
            "data": {"output_id": "output", "provider_still_active": 1},
        }
    ]
    raises_code(document, "fixture_action_data_invalid")

    document["steps"] = [{"at_ms": 0, "port": "device", "action": "output_busy", "data": {}}]
    raises_code(document, "fixture_action_data_invalid")


@pytest.mark.parametrize(("category", "field", "length"), [("reported", "source_ref", 161), ("derived", "fact", 513)])
def test_provenance_evidence_strings_are_bounded(category, field, length):
    document = valid_document()
    document["provenance"][category][0][field] = "x" * length  # type: ignore[index]
    raises_code(document, "fixture_value_too_long")


def test_size_step_count_encoding_and_source_path_are_bounded(tmp_path):
    with pytest.raises(ReplayFixtureError) as too_large:
        loads_replay_fixture(" " * (64 * 1024 + 1))
    assert too_large.value.code == "fixture_too_large"

    document = valid_document()
    document["steps"] = [
        {"at_ms": index, "port": "control", "action": "checkpoint", "data": {}}
        for index in range(MAX_STEPS + 1)
    ]
    raises_code(document, "fixture_steps_exceeded")

    with pytest.raises(ReplayFixtureError) as encoding_error:
        loads_replay_fixture(b"\xff")
    assert encoding_error.value.code == "fixture_encoding_invalid"

    document = valid_document()
    document["provenance"]["source_path"] = "../private/transcript.md"  # type: ignore[index]
    raises_code(document, "fixture_provenance_invalid")

    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b" " * (64 * 1024 + 1))
    with pytest.raises(ReplayFixtureError) as file_error:
        load_replay_fixture(oversized)
    assert file_error.value.code == "fixture_too_large"


def test_payload_is_deeply_immutable():
    fixture = loads_replay_fixture(encoded(valid_document()))
    with pytest.raises(TypeError):
        fixture.steps[0].data["turn_id"] = "changed"  # type: ignore[index]


def test_replay_clock_exposes_coherent_wall_monotonic_and_nanosecond_time():
    origin = datetime(2026, 9, 11, 15, 43, 35, tzinfo=timezone.utc)
    clock = ReplayClock(origin, monotonic_start=10.25)
    clock.advance_to_ms(35_900)

    assert clock.elapsed_ms == 35_900
    assert clock.now() == datetime(2026, 9, 11, 15, 44, 10, 900_000, tzinfo=timezone.utc)
    assert clock.monotonic() == pytest.approx(46.15)
    assert clock.monotonic_ns() == 46_150_000_000

    with pytest.raises(ReplayFixtureError) as backwards:
        clock.advance_to_ms(35_899)
    assert backwards.value.code == "clock_went_backwards"

    with pytest.raises(ReplayFixtureError) as too_far:
        ReplayClock(origin).advance_to_ms(MAX_TIMELINE_MS + 1)
    assert too_far.value.code == "clock_target_invalid"


@pytest.mark.parametrize("start", [True, -1, float("nan"), float("inf")])
def test_replay_clock_rejects_invalid_monotonic_start(start):
    with pytest.raises(ReplayFixtureError) as caught:
        ReplayClock(datetime.now(timezone.utc), monotonic_start=start)
    assert caught.value.code == "clock_start_invalid"


async def test_driver_only_advances_and_calls_exact_sync_or_async_handlers():
    document = valid_document()
    document["steps"] = [
        {"at_ms": 5, "port": "user", "action": "turn", "data": {"turn_id": "turn-a", "content_tag": "opaque_tag"}},
        {"at_ms": 9, "port": "control", "action": "checkpoint", "data": {"checkpoint_id": "opaque_checkpoint"}},
    ]
    fixture = loads_replay_fixture(encoded(document))
    clock = ReplayClock(fixture.origin)
    observed: list[tuple[str, int, str]] = []

    def user_handler(step):
        observed.append((step.kind, clock.elapsed_ms, step.data["content_tag"]))

    async def checkpoint_handler(step):
        observed.append((step.kind, clock.elapsed_ms, step.data["checkpoint_id"]))

    await ReplayDriver(clock).run(
        fixture,
        {"user.turn": user_handler, "control.checkpoint": checkpoint_handler},
    )

    assert observed == [
        ("user.turn", 5, "opaque_tag"),
        ("control.checkpoint", 9, "opaque_checkpoint"),
    ]


async def test_driver_fails_closed_when_action_handler_is_missing():
    fixture = loads_replay_fixture(encoded(valid_document()))
    with pytest.raises(ReplayFixtureError) as caught:
        await ReplayDriver(ReplayClock(fixture.origin)).run(fixture, {})
    assert caught.value.code == "replay_handler_missing"

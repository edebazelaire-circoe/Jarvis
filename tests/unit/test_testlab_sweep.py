"""The sweep declaration, its expansion, its record and its store (docs/testlab.md, "Sweeps")."""

from __future__ import annotations

from dataclasses import replace

import pytest

from jarvis.testlab.diagnostics import ParameterSpec, ParameterType
from jarvis.testlab.filesystem_sweep_store import FilesystemSweepStore
from jarvis.testlab.identity import format_run_id, format_sweep_id
from jarvis.testlab.outcomes import RunOutcomeClass
from jarvis.testlab.profiles import ProfileName
from jarvis.testlab.runs import RunFailure, RunStatus
from jarvis.testlab.selftest import SELFTEST_DIAGNOSTIC_ID, selftest_spec
from jarvis.testlab.store import (
    STORE_CONFLICT,
    SweepNotFoundError,
    SweepPage,
    SweepQuery,
    SweepRecordCorruptError,
    TestLabStoreError,
)
from jarvis.testlab.sweeps import (
    MAX_SWEEP_POINTS,
    MAX_SWEEP_RUNS,
    SweepError,
    SweepPoint,
    SweepPointResult,
    SweepRecord,
    SweepRunOutcome,
    SweepSpec,
    SweepStatus,
    SweepTarget,
    SweptParameter,
    check_sweep_spec,
    expand_points,
)
from jarvis.testlab.validation import TestLabError
from tests.fakes.testlab import T0, at

SPEC = selftest_spec()
ALLOWLIST = (ParameterSpec("voice.echo_guard_ms", ParameterType.INT, 400, minimum=0, maximum=5000),)


def axis(name="value", target=SweepTarget.PARAMETER, values=(0, 1, 2)) -> SweptParameter:
    return SweptParameter(name, target, values)


def sweep(**changes) -> SweepSpec:
    values = dict(diagnostic_id=SELFTEST_DIAGNOSTIC_ID, profile=ProfileName.VIRTUAL, swept=(axis(),))
    values.update(changes)
    return SweepSpec(**values)


# ------------------------------------------------------------ the declaration

def test_a_sweep_declares_its_axes_and_counts_its_runs():
    spec = sweep(swept=(axis(values=(0, 1)), axis("sleep_ms", values=(0, 5, 10))), repetitions=2)
    assert (spec.point_count, spec.run_count) == (6, 12)


def test_a_range_expands_to_explicit_values_at_construction():
    assert SweptParameter.from_range("value", SweepTarget.PARAMETER, start=0, stop=10, step=5).values == (0, 5, 10)
    assert SweptParameter.from_range("value", SweepTarget.PARAMETER, start=10, stop=0, step=-5).values == (10, 5, 0)


def test_a_float_range_does_not_drift():
    values = SweptParameter.from_range("ratio", SweepTarget.PARAMETER, start=0.0, stop=1.0, step=0.1).values
    assert len(values) == 11 and values[3] == 0.3 and values[-1] == 1.0


@pytest.mark.parametrize("arguments", [
    dict(start=0, stop=10, step=0),
    dict(start=0, stop=10, step=-1),
    dict(start=0, stop=1000, step=1),  # over MAX_SWEEP_VALUES
])
def test_an_impossible_range_is_refused(arguments):
    with pytest.raises(TestLabError):
        SweptParameter.from_range("value", SweepTarget.PARAMETER, **arguments)


def test_an_axis_needs_distinct_values():
    with pytest.raises(TestLabError, match="repeats a value"):
        axis(values=(1, 1))
    with pytest.raises(TestLabError, match="non-empty"):
        axis(values=())


def test_a_sweep_needs_at_least_one_axis():
    with pytest.raises(TestLabError, match="1 to 4 axes"):
        sweep(swept=())


def test_a_name_cannot_be_both_swept_and_fixed():
    with pytest.raises(TestLabError, match="both swept and fixed"):
        sweep(parameters={"value": 3})


def test_an_axis_cannot_be_declared_twice():
    with pytest.raises(TestLabError, match="same name twice"):
        sweep(swept=(axis(), axis(values=(7, 8))))


def test_a_sweep_that_would_explode_is_refused_as_a_whole():
    wide = tuple(SweptParameter(name, SweepTarget.PARAMETER, tuple(range(8)))
                 for name in ("value", "sleep_ms", "a.b", "c.d"))
    with pytest.raises(TestLabError, match=f"over {MAX_SWEEP_POINTS}"):
        sweep(swept=wide)
    with pytest.raises(TestLabError, match=f"over {MAX_SWEEP_RUNS}"):
        sweep(swept=(SweptParameter("value", SweepTarget.PARAMETER, tuple(range(64))),), repetitions=16)


def test_a_sweep_round_trips_and_fingerprints_its_declaration():
    spec = sweep(parameters={"sleep_ms": 5}, title="latency budget", repetitions=2)
    assert SweepSpec.from_dict(spec.to_dict()) == spec
    assert spec.fingerprint() == sweep(parameters={"sleep_ms": 5}, title="latency budget",
                                       repetitions=2).fingerprint()
    assert spec.fingerprint() != replace(spec, repetitions=3).fingerprint()


def test_a_sweep_document_is_strict():
    payload = sweep().to_dict()
    payload["unexpected"] = 1
    with pytest.raises(TestLabError, match="testlab_fields_mismatch"):
        SweepSpec.from_dict(payload)


# -------------------------------------------------------------- expansion

def test_the_expansion_is_the_cartesian_product_with_the_last_axis_fastest():
    points = expand_points(sweep(swept=(axis(values=(0, 1)), axis("sleep_ms", values=(10, 20)))))
    assert [dict(point.values) for point in points] == [
        {"value": 0, "sleep_ms": 10}, {"value": 0, "sleep_ms": 20},
        {"value": 1, "sleep_ms": 10}, {"value": 1, "sleep_ms": 20}]
    assert [point.index for point in points] == [0, 1, 2, 3]


def test_a_swept_override_lands_in_the_overrides_not_the_parameters():
    points = expand_points(sweep(swept=(axis("voice.echo_guard_ms", SweepTarget.OVERRIDE, (100, 200)),),
                                 parameters={"value": 0}))
    assert dict(points[0].parameters) == {"value": 0}
    assert dict(points[0].overrides) == {"voice.echo_guard_ms": 100}


def test_a_point_labels_itself_for_a_human():
    point = expand_points(sweep(swept=(axis(values=(3,)),)))[0]
    assert point.label == "value=3"
    assert SweepPoint.from_dict(point.to_dict()) == point


def test_the_expansion_is_deterministic():
    spec = sweep(swept=(axis(values=(0, 1)), axis("sleep_ms", values=(10, 20))))
    assert [point.to_dict() for point in expand_points(spec)] == [point.to_dict() for point in expand_points(spec)]


# ----------------------------------------------- validation against a spec

def test_a_valid_sweep_returns_its_points():
    assert len(check_sweep_spec(sweep(), SPEC)) == 3


def test_a_swept_parameter_must_be_declared():
    with pytest.raises(SweepError, match="not declared by the diagnostic"):
        check_sweep_spec(sweep(swept=(axis("not.declared", values=(1, 2)),)), SPEC)


def test_a_swept_value_must_satisfy_the_declaration():
    with pytest.raises(SweepError, match="value"):
        check_sweep_spec(sweep(swept=(axis(values=(0, 5000)),)), SPEC)  # maximum is 1000


def test_a_fixed_parameter_must_be_declared_and_valid():
    with pytest.raises(SweepError, match="not a declared parameter"):
        check_sweep_spec(sweep(parameters={"nope": 1}), SPEC)
    with pytest.raises(SweepError):
        check_sweep_spec(sweep(parameters={"sleep_ms": -5}), SPEC)


def test_a_swept_override_must_be_in_the_manifest_allowlist():
    with pytest.raises(SweepError, match="override allowlist"):
        check_sweep_spec(sweep(swept=(axis("voice.echo_guard_ms", SweepTarget.OVERRIDE, (100, 200)),)), SPEC)
    points = check_sweep_spec(sweep(swept=(axis("voice.echo_guard_ms", SweepTarget.OVERRIDE, (100, 200)),)),
                              SPEC, ALLOWLIST)
    assert len(points) == 2


def test_a_fixed_override_must_be_in_the_allowlist_too():
    with pytest.raises(SweepError, match="override allowlist"):
        check_sweep_spec(sweep(overrides={"voice.echo_guard_ms": 100}), SPEC)


def test_a_profile_the_diagnostic_does_not_declare_is_refused():
    with pytest.raises(SweepError, match="does not declare profile"):
        check_sweep_spec(sweep(profile=ProfileName.LIVE), SPEC)


def test_a_sweep_of_another_diagnostic_is_refused():
    with pytest.raises(SweepError, match="another diagnostic"):
        check_sweep_spec(sweep(diagnostic_id="voice.self_echo"), SPEC)


def test_check_sweep_spec_takes_the_right_types():
    with pytest.raises(SweepError, match="SweepSpec"):
        check_sweep_spec({"diagnostic_id": "x"}, SPEC)


# ----------------------------------------------------------------- record

def a_record(**changes) -> SweepRecord:
    values = dict(sweep_id=format_sweep_id(T0, "a" * 16), created_at=T0, spec=sweep(), status=SweepStatus.RUNNING,
                  diagnostic_version=1, diagnostic_fingerprint=SPEC.fingerprint(),
                  points=tuple(SweepPointResult(point) for point in expand_points(sweep())))
    values.update(changes)
    return SweepRecord(**values)


def an_outcome(nonce="1" * 16, outcome=RunOutcomeClass.PASSED) -> SweepRunOutcome:
    return SweepRunOutcome(format_run_id(T0, nonce), RunStatus.PASSED, outcome)


def test_a_sweep_record_round_trips():
    record = a_record(status=SweepStatus.COMPLETED, finished_at=at(5000),
                      points=(SweepPointResult(expand_points(sweep())[0], (an_outcome(),)),))
    assert SweepRecord.from_dict(record.to_dict()) == record


def test_a_sweep_record_ties_its_id_to_its_creation_time():
    with pytest.raises(TestLabError, match="created_at must equal"):
        a_record(created_at=at(5))


def test_finished_at_is_set_exactly_when_the_sweep_is_terminal():
    with pytest.raises(TestLabError, match="finished_at is set exactly"):
        a_record(finished_at=at(5000))
    with pytest.raises(TestLabError, match="finished_at is set exactly"):
        a_record(status=SweepStatus.COMPLETED)


def test_a_failed_sweep_records_why():
    with pytest.raises(TestLabError, match="failed sweep records why"):
        a_record(status=SweepStatus.FAILED, finished_at=at(5000))


def test_a_record_counts_its_outcomes_and_lists_its_runs():
    record = a_record(points=(SweepPointResult(expand_points(sweep())[0],
                                               (an_outcome(), an_outcome("2" * 16, RunOutcomeClass.INCONCLUSIVE))),))
    assert record.outcome_counts() == {"inconclusive": 1, "passed": 1}
    assert len(record.run_ids) == 2


def test_a_point_that_could_not_run_keeps_its_reason():
    result = SweepPointResult(expand_points(sweep())[0], (), RunFailure("sweep_failed", "no worker"))
    assert SweepPointResult.from_dict(result.to_dict()) == result
    assert result.outcomes == () and result.run_ids == ()


# ------------------------------------------------------------------ store

def test_a_sweep_is_stored_read_back_and_listed(tmp_path):
    store = FilesystemSweepStore(tmp_path / "store")
    record = a_record()
    assert store.put_sweep(record) == record
    assert store.get_sweep(record.sweep_id) == record
    page = store.list_sweeps()
    assert isinstance(page, SweepPage) and page.sweeps == (record,)


def test_a_running_sweep_record_is_rewritten_as_it_progresses(tmp_path):
    store = FilesystemSweepStore(tmp_path / "store")
    record = a_record()
    store.put_sweep(record)
    updated = replace(record, points=(SweepPointResult(expand_points(sweep())[0], (an_outcome(),)),))
    store.put_sweep(updated)
    assert store.get_sweep(record.sweep_id) == updated


def test_a_terminal_sweep_record_is_immutable(tmp_path):
    store = FilesystemSweepStore(tmp_path / "store")
    record = a_record(status=SweepStatus.COMPLETED, finished_at=at(5000))
    store.put_sweep(record)
    with pytest.raises(TestLabStoreError) as failure:
        store.put_sweep(replace(record, points=()))
    assert failure.value.code == STORE_CONFLICT and "terminal sweep is immutable" in failure.value.detail


def test_an_unknown_sweep_is_not_found(tmp_path):
    store = FilesystemSweepStore(tmp_path / "store")
    with pytest.raises(SweepNotFoundError):
        store.get_sweep(format_sweep_id(T0, "f" * 16))
    with pytest.raises(TestLabStoreError, match="tls-"):
        store.get_sweep("not-a-sweep-id")


def test_a_corrupt_sweep_record_is_reported_and_never_skipped(tmp_path):
    store = FilesystemSweepStore(tmp_path / "store")
    record = a_record()
    store.put_sweep(record)
    (tmp_path / "store" / "sweeps" / record.sweep_id / "sweep.json").write_text("{", encoding="utf-8")
    with pytest.raises(SweepRecordCorruptError):
        store.get_sweep(record.sweep_id)
    page = store.list_sweeps()
    assert page.sweeps == () and [item.entry for item in page.corrupt] == [record.sweep_id]


def test_a_stray_directory_is_reported_as_corrupt(tmp_path):
    store = FilesystemSweepStore(tmp_path / "store")
    store.put_sweep(a_record())
    (tmp_path / "store" / "sweeps" / "not-a-sweep").mkdir()
    assert [item.entry for item in store.list_sweeps().corrupt] == ["not-a-sweep"]


def test_the_summary_artifact_is_stored_beside_the_record(tmp_path):
    store = FilesystemSweepStore(tmp_path / "store")
    record = a_record()
    store.put_sweep(record)
    store.put_sweep_summary(record.sweep_id, {"schema": "jarvis.testlab.sweep_summary", "points": []})
    assert store.get_sweep_summary(record.sweep_id)["points"] == []
    with pytest.raises(SweepNotFoundError):
        store.get_sweep_summary(format_sweep_id(T0, "e" * 16))


def test_a_sweep_without_a_summary_says_so(tmp_path):
    store = FilesystemSweepStore(tmp_path / "store")
    record = a_record()
    store.put_sweep(record)
    with pytest.raises(SweepNotFoundError, match="summary.json is missing"):
        store.get_sweep_summary(record.sweep_id)


def test_a_sweep_listing_pages(tmp_path):
    store = FilesystemSweepStore(tmp_path / "store")
    records = [a_record(sweep_id=format_sweep_id(T0, f"{index:016x}")) for index in range(3)]
    for record in records:
        store.put_sweep(record)
    page = store.list_sweeps(SweepQuery(limit=2))
    assert len(page.sweeps) == 2 and page.next_cursor == page.sweeps[-1].sweep_id
    rest = store.list_sweeps(SweepQuery(limit=2, after_sweep_id=page.next_cursor))
    assert len(rest.sweeps) == 1 and rest.next_cursor is None


def test_a_sweep_summary_is_written_once_like_a_terminal_record(tmp_path):
    """Consistency with `put_sweep`: the conclusion of an experiment is not edited."""
    store = FilesystemSweepStore(tmp_path / "store")
    record = a_record(status=SweepStatus.COMPLETED, finished_at=at(5000))
    store.put_sweep(record)
    store.put_sweep_summary(record.sweep_id, {"points": [], "note": "first"})
    with pytest.raises(TestLabStoreError) as failure:
        store.put_sweep_summary(record.sweep_id, {"points": [], "note": "second"})
    assert failure.value.code == STORE_CONFLICT and "not rewritten" in failure.value.detail
    assert store.get_sweep_summary(record.sweep_id)["note"] == "first"

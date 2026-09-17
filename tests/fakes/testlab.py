"""Shared Test Lab contract builders for tests (docs/testlab.md). Deterministic: fixed clock, fixed nonces."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jarvis.testlab.diagnostics import (
    AssertionSpec,
    Comparator,
    DiagnosticSpec,
    MetricDirection,
    MetricSpec,
    MetricUnit,
    ParameterSpec,
    ParameterType,
    ScoreComponent,
    ScoreContract,
    ScoreMethod,
    resolve_parameters,
)
from jarvis.testlab.identity import format_run_id
from jarvis.testlab.profiles import Capability, CostBounds, ProfileName, ProfileSpec
from jarvis.testlab.runs import CodeIdentity, RunStatus, TestRun

T0 = datetime(2026, 9, 17, 10, 58, 0, 123000, tzinfo=timezone.utc)
NONCE = "0123456789abcdef"
REVISION = "0eae289" + "0" * 33
CONFIG = "c" * 64
ENVIRONMENT = {"os": "windows", "os_version": "10.0.26200", "python_version": "3.14.6", "host.cpu_count": 8}


def at(ms: int) -> datetime:
    return T0 + timedelta(milliseconds=ms)


def virtual_profile() -> ProfileSpec:
    return ProfileSpec(ProfileName.VIRTUAL, "testlab.virtual.conversation", CostBounds(60, 0))


def live_profile() -> ProfileSpec:
    return ProfileSpec(ProfileName.LIVE, "testlab.live.realtime", CostBounds(120, 0.5),
                       frozenset({Capability.REALTIME_PROVIDER}))


def guided_profile() -> ProfileSpec:
    return ProfileSpec(ProfileName.HARDWARE_GUIDED, "testlab.hardware.guided", CostBounds(600, 1),
                       frozenset({Capability.REALTIME_PROVIDER, Capability.AUDIO_INPUT_DEVICE,
                                  Capability.AUDIO_OUTPUT_DEVICE, Capability.HUMAN_PRESENCE}))


def self_echo_spec(**changes) -> DiagnosticSpec:
    values = dict(
        diagnostic_id="voice.self_echo",
        version=1,
        title="No false self barge-in",
        domain="voice",
        profiles={profile.name: profile for profile in (virtual_profile(), live_profile(), guided_profile())},
        metrics=(
            MetricSpec("barge_in.false_count", MetricUnit.COUNT, MetricDirection.LOWER_BETTER),
            MetricSpec("speech.ready_to_play_ms", MetricUnit.MS, MetricDirection.LOWER_BETTER),
            MetricSpec("output.stopped", MetricUnit.BOOLEAN, MetricDirection.HIGHER_BETTER),
        ),
        assertions=(
            AssertionSpec("no_false_barge_in", "barge_in.false_count", Comparator.EQ, 0, True),
            AssertionSpec("output_stops", "output.stopped", Comparator.EQ, True, True),
            AssertionSpec("ready_fast", "speech.ready_to_play_ms", Comparator.LE, 800, False),
        ),
        score=ScoreContract(ScoreMethod.WEIGHTED_MEAN, (ScoreComponent("speech.ready_to_play_ms", 1, 200, 2000),)),
        parameters=(
            ParameterSpec("echo.level_db", ParameterType.FLOAT, -20, minimum=-60, maximum=0),
            ParameterSpec("turns", ParameterType.INT, 3, minimum=1, maximum=20),
            ParameterSpec("aec", ParameterType.BOOL, True),
            ParameterSpec("mode", ParameterType.ENUM, "duplex", choices=("duplex", "half")),
            ParameterSpec("label", ParameterType.STR, "baseline", max_length=32),
        ),
        description="Jarvis must not interrupt itself on its own echo.",
    )
    values.update(changes)
    return DiagnosticSpec(**values)


def queued_run(spec: DiagnosticSpec | None = None, **changes) -> TestRun:
    spec = spec or self_echo_spec()
    values = dict(
        run_id=format_run_id(T0, NONCE),
        diagnostic_id=spec.diagnostic_id,
        diagnostic_version=spec.version,
        profile=ProfileName.VIRTUAL,
        status=RunStatus.QUEUED,
        created_at=T0,
        code=CodeIdentity(REVISION, False),
        config_fingerprint=CONFIG,
        diagnostic_fingerprint=spec.fingerprint(),
        parameters=resolve_parameters(spec.parameters, {"turns": 5}),
        environment=ENVIRONMENT,
    )
    values.update(changes)
    return TestRun(**values)

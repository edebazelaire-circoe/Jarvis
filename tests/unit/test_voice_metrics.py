from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from jarvis.core.latency import (
    BRAIN_TURN_ACCEPTED,
    FIRST_BRAIN_AUDIO,
    FIRST_PUBLIC_PROGRESS,
    LOCAL_OUTPUT_STOPPED,
    WORK_COMPLETED,
)
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.pricing import PricingMetadata, TokenPricingMetadata
from jarvis.runtime.voice_metrics import COUNT_KEYS, LATENCY_KEYS, VoiceSessionMetricRecorder


CONVERSATION = "benchmark-conversation"
SESSION = "benchmark:session/one"


class FakeTime:
    def __init__(self) -> None:
        self.mono = 10.0
        self.wall = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)

    def monotonic(self) -> float:
        return self.mono

    def now(self) -> datetime:
        return self.wall


def event(channel: str, offset_ms: float, **data: object) -> dict[str, object]:
    timestamp = datetime(2026, 9, 13, 12, tzinfo=timezone.utc) + timedelta(milliseconds=offset_ms)
    return {"ts": timestamp.isoformat(), "kind": channel, "level": "info", "message": "safe",
            "data": {"conversation_id": CONVERSATION, "session_id": SESSION, **data}}


def timeline() -> list[dict[str, object]]:
    return [
        event("voice.latency.brain_turn_accepted", 25, measure=BRAIN_TURN_ACCEPTED,
              elapsed_ms=25.0, correlation_id="corr"),
        event("voice.speech.queued", 0, speech_id="speech", kind="result", correlation_id="corr"),
        event("voice.speech.dispatched", 100, speech_id="speech", queue_wait_ms=100.0,
              correlation_id="corr"),
        event("voice.speech.queued", 30, speech_id="ack", kind="ack", correlation_id="corr"),
        event("voice.latency.output_first_write", 150, speech_id="ack", output_id="ack-output",
              segment_id="segment", elapsed_ms=150.0, delivery_boundary="successful_native_write"),
        event("voice.latency.first_audible_write", 150, speech_id="ack", output_id="ack-output",
              segment_id="segment", elapsed_ms=150.0, delivery_boundary="successful_native_write"),
        event("voice.latency.provider_first_pcm", 200, speech_id="speech", output_id="output",
              elapsed_ms=200.0, delivery_boundary="provider_pcm_received"),
        event("voice.latency.playback_attempted", 220, speech_id="speech", output_id="output",
              elapsed_ms=220.0, delivery_boundary="before_device_write"),
        event("voice.latency.output_first_write", 250, speech_id="speech", output_id="output",
              segment_id="segment", elapsed_ms=250.0, delivery_boundary="successful_native_write"),
        event("audio.drain_result", 300, output_id="output", elapsed_ms=10.0, status="completed"),
        event("voice.latency.first_brain_audio", 250, measure=FIRST_BRAIN_AUDIO, elapsed_ms=80.0),
        event("core.brain.latency.first_public_progress", 400, measure=FIRST_PUBLIC_PROGRESS,
              elapsed_ms=400.0, work_id="work", correlation_id="corr"),
        event("core.brain.latency.work_completed", 1000, measure=WORK_COMPLETED,
              elapsed_ms=1000.0, work_id="work", correlation_id="corr"),
        event("voice.barge_in", 1200, measure=LOCAL_OUTPUT_STOPPED, elapsed_ms=15.0),
        event("voice.barge_in_rejected", 1250),
        event("voice.speech.output_stalled", 1300),
        event("voice.speech.superseded", 1350, speech_id="ack", kind="ack"),
        event("voice.state.spoken_diverged", 1400, speech_id="speech"),
        event("core.brain.backend_task_started", 0, work_id="work", correlation_id="corr"),
        event("core.brain.backend_task_result", 1000, work_id="work", correlation_id="corr", status="completed"),
        event("voice.live.delegation", 200, status="accepted", job_id="job"),
        event("voice.live.delegation", 900, status="append_acknowledged", job_id="job"),
        event("voice.realtime.usage", 950, input_tokens=120, output_tokens=30,
              duration_seconds=12.0, source="provider_snapshot"),
    ]


def recorder(tmp_path, architecture: str = "duplex") -> tuple[VoiceSessionMetricRecorder, FakeTime]:  # noqa: ANN001
    fake = FakeTime()
    value = VoiceSessionMetricRecorder(
        runtime_root=tmp_path,
        journal=SimpleNamespace(),
        architecture=architecture,
        provider_id="openai",
        model_id="gpt-live-1",
        configuration_id=f"config-{architecture}",
        pricing={"schema_version": 1, "model_id": "gpt-live-1", "currency": "usd",
                 "price_per_minute": .2, "source": "fixture",
                 "effective_at": "2026-09-13T00:00:00+00:00"},
        clock=fake.monotonic,
        wall_clock=fake.now,
    )
    value.start(conversation_id=CONVERSATION, session_id=SESSION)
    return value, fake


def test_synthetic_timeline_produces_decomposed_machine_and_text_reports(tmp_path):
    value, fake = recorder(tmp_path)
    for row in timeline():
        value.observe(row)
    value.annotate("late correction", outcome="pass", note="correction retained")
    value.annotate("unnecessary_acknowledgement", outcome="fail", note="audible ACK added no value")
    fake.mono += 5
    fake.wall += timedelta(seconds=5)
    report = value.finish(status="stopped", live_record=SimpleNamespace(
        active_seconds=60.0, provider_usage_seconds=30.0, provider_usage_final=True))

    metrics = report["latency_metrics"]
    assert tuple(metrics) == LATENCY_KEYS
    assert metrics["provider_first_pcm_ms"]["samples_ms"] == [200.0]
    assert metrics["playback_attempt_ms"]["samples_ms"] == [220.0]
    assert metrics["time_to_first_audible_reaction_ms"]["samples_ms"] == [150.0]
    assert metrics["time_to_first_useful_answer_ms"]["samples_ms"] == [250.0]
    assert metrics["frontend_blocking_ms"]["samples_ms"] == [25.0]
    assert metrics["speech_queue_wait_ms"]["samples_ms"] == [100.0]
    assert metrics["brain_speech_to_first_audio_ms"]["samples_ms"] == [80.0]
    assert metrics["delegation_latency_ms"]["samples_ms"] == [700.0]
    assert metrics["device_drain_ms"]["samples_ms"] == [10.0]
    assert report["event_counts"] == {key: 1 for key in COUNT_KEYS}
    assert report["session_duration_seconds"] == 5.0
    assert report["live_active_seconds"] == 60.0
    assert report["provider_usage_seconds"] == 30.0
    assert report["provider_usage"] == {"duration_seconds": 30.0, "input_tokens": 120,
                                        "output_tokens": 30, "final": True,
                                        "source": "live_lifecycle"}
    assert report["provider_usage_components"][0]["role"] == "surface"
    assert report["cost_estimate"]["amount"] == pytest.approx(.1)
    assert report["cost_estimate"]["pricing_schema_version"] == 1

    json_files = list((tmp_path / "benchmarks" / "voice-sessions").glob("*.json"))
    text_files = list((tmp_path / "benchmarks" / "voice-sessions").glob("*.txt"))
    assert len(json_files) == len(text_files) == 1
    assert json.loads(json_files[0].read_text(encoding="utf-8")) == report
    assert "time_to_first_useful_answer_ms" in text_files[0].read_text(encoding="utf-8")
    assert "safe" not in json_files[0].read_text(encoding="utf-8")
    with pytest.raises(RuntimeError, match="already finished"):
        value.finish(status="stopped")


@pytest.mark.parametrize("architecture", ["simple", "front_brain", "duplex"])
def test_all_architectures_emit_the_same_metric_shape(tmp_path, architecture):  # noqa: ANN001
    value, _ = recorder(tmp_path / architecture, architecture)
    report = value.finish(status="stopped")
    assert tuple(report["latency_metrics"]) == LATENCY_KEYS
    assert tuple(report["event_counts"]) == COUNT_KEYS
    assert all(metric["count"] == 0 and metric["mean_ms"] is None
               for metric in report["latency_metrics"].values())


def test_trace_suffix_collects_core_process_events_and_filters_other_sessions(tmp_path):
    journal = RuntimeJournal(tmp_path)
    value = VoiceSessionMetricRecorder(runtime_root=tmp_path, journal=journal,
        architecture="front_brain", provider_id="openai", model_id="model",
        configuration_id="config")
    value.start(conversation_id=CONVERSATION, session_id=SESSION)
    journal.emit("voice.latency.brain_turn_accepted", "accepted",
        data={"conversation_id": CONVERSATION, "session_id": SESSION, "correlation_id": "corr"})
    RuntimeJournal(tmp_path).emit("core.brain.backend_task_started", "started",
        data={"conversation_id": CONVERSATION, "correlation_id": "corr", "work_id": "ours"})
    RuntimeJournal(tmp_path).emit("core.brain.backend_task_started", "other",
        data={"conversation_id": "other", "correlation_id": "other", "work_id": "other"})
    report = value.finish(status="stopped")
    assert report["event_counts"]["backend_task_started"] == 1


def test_pricing_rejects_unversioned_wrong_model_or_naive_date():
    base = {"schema_version": 1, "model_id": "model", "currency": "eur",
            "price_per_minute": 1, "source": "catalog", "effective_at": "2026-09-13T00:00:00+00:00"}
    assert PricingMetadata.parse(base, model_id="model") is not None
    for bad in ({**base, "schema_version": 2}, {**base, "schema_version": True},
                {**base, "model_id": "other"},
                {**base, "effective_at": "2026-09-13T00:00:00"}):
        assert PricingMetadata.parse(bad, model_id="model") is None


def test_prompt_text_and_raw_trace_messages_never_enter_the_report(tmp_path):
    value, _ = recorder(tmp_path)
    value.identify_frontend(session_id=SESSION, prompt_applications=[{
        "program_id": "voice.simple.session",
        "layer_revisions": ["default:1"],
        "static_fingerprint": "a" * 64,
        "application": "acknowledged",
        "effective_text": "PRIVATE PROMPT BODY",
    }])
    value.observe({**event("voice.speech.output_stalled", 10),
                   "message": "PRIVATE TRACE MESSAGE"})
    value.annotate("private note", outcome="pass", note="PRIVATE ANNOTATION")
    report = value.finish(status="stopped")
    rendered = json.dumps(report)
    assert "PRIVATE" not in rendered
    assert report["prompt_applications"] == [{
        "program_id": "voice.simple.session", "layer_revisions": ["default:1"],
        "static_fingerprint": "a" * 64, "application": "acknowledged",
    }]
    assert report["annotations"][0]["note_length"] == len("PRIVATE ANNOTATION")


def test_core_result_without_a_session_admission_is_not_attributed(tmp_path):
    value, _ = recorder(tmp_path)
    value.observe(event("core.brain.backend_task_result", 10, work_id="old-work",
                        correlation_id="old-correlation", status="completed"))
    value.observe(event("core.brain.latency.work_completed", 10, work_id="old-work",
                        correlation_id="old-correlation", measure=WORK_COMPLETED, elapsed_ms=10.0))
    report = value.finish(status="stopped")
    assert report["event_counts"]["backend_task_result"] == 0
    assert report["latency_metrics"]["backend_result_ms"]["count"] == 0


def test_front_brain_component_usage_is_aggregated_without_text(tmp_path):
    value, _ = recorder(tmp_path)
    value.components = [
        {"role": "surface", "provider_id": "openai", "model_id": "gpt-live-1"},
        {"role": "analysis", "provider_id": "openai", "model_id": "gpt-5.6-luna"},
    ]
    value.observe(event("voice.hint.analysis", 10, component_role="analysis",
                        usage={"input_tokens": 10, "output_tokens": 3, "total_tokens": 13},
                        usage_source="provider", program_id="front_brain.openai.analysis",
                        layer_revisions=["default:1"], static_fingerprint="b" * 64,
                        application="sent"))
    value.observe(event("voice.hint.analysis", 20, component_role="analysis",
                        usage={"input_tokens": 20, "output_tokens": 4, "total_tokens": 24},
                        usage_source="provider"))
    report = value.finish(status="stopped")
    analysis = report["provider_usage_components"][1]
    assert analysis["usage"]["requests"] == 2
    assert analysis["usage"]["source"] == "provider"
    assert analysis["usage"]["input_tokens"] == 30
    assert analysis["usage"]["output_tokens"] == 7
    assert analysis["usage"]["total_tokens"] == 37
    assert report["prompt_applications"][-1]["static_fingerprint"] == "b" * 64


def test_report_commit_marker_is_retryable_after_json_replace_failure(tmp_path, monkeypatch):
    import jarvis.runtime.voice_metrics as module

    value, fake = recorder(tmp_path)
    real_replace = module.replace_with_retry
    failed = False

    def fail_json_once(source, target):  # noqa: ANN001
        nonlocal failed
        if not failed and str(target).endswith(".json"):
            failed = True
            raise OSError("injected commit failure")
        return real_replace(source, target)

    monkeypatch.setattr(module, "replace_with_retry", fail_json_once)
    with pytest.raises(OSError, match="commit"):
        value.finish(status="stopped")
    root = tmp_path / "benchmarks" / "voice-sessions"
    assert list(root.glob("*.json")) == []
    assert len(list(root.glob("*.txt"))) == 1
    fake.mono += 30
    fake.wall += timedelta(seconds=30)
    value.observe(event("voice.speech.output_stalled", 20))
    report = value.finish(status="stopped")
    assert len(list(root.glob("*.json"))) == len(list(root.glob("*.txt"))) == 1
    assert report["terminal_status"] == "stopped"
    assert report["session_duration_seconds"] == 0.0
    assert report["event_counts"]["output_stall"] == 0


def test_token_pricing_is_versioned_and_can_estimate_analysis_cost(tmp_path):
    metadata = {"schema_version": 1, "model_id": "gpt-5.6-luna", "currency": "usd",
                "input_price_per_million_tokens": 2.0,
                "output_price_per_million_tokens": 8.0,
                "source": "fixture", "effective_at": "2026-09-13T00:00:00+00:00"}
    assert TokenPricingMetadata.parse(metadata, model_id="gpt-5.6-luna") is not None
    assert TokenPricingMetadata.parse({**metadata, "schema_version": True}, model_id="gpt-5.6-luna") is None
    value, _ = recorder(tmp_path)
    value.components = [
        {"role": "surface", "provider_id": "openai", "model_id": "gpt-live-1"},
        {"role": "analysis", "provider_id": "openai", "model_id": "gpt-5.6-luna"},
    ]
    value.pricing = {"analysis": metadata}
    value.observe(event("voice.hint.analysis", 10,
                        usage={"input_tokens": 1_000_000, "output_tokens": 500_000},
                        usage_source="provider"))
    report = value.finish(status="stopped")
    assert report["provider_usage_components"][1]["cost_estimate"]["amount"] == pytest.approx(6.0)


def test_correlated_back_brain_usage_is_aggregated_and_priced(tmp_path):
    metadata = {"schema_version": 1, "model_id": "chosen-model", "currency": "usd",
                "input_price_per_million_tokens": 3.0,
                "output_price_per_million_tokens": 9.0,
                "source": "fixture", "effective_at": "2026-09-13T00:00:00+00:00"}
    value, _ = recorder(tmp_path)
    value.components = [
        {"role": "surface", "provider_id": "openai", "model_id": "gpt-live-1"},
        {"role": "backend", "provider_id": "openai", "model_id": "chosen-model"},
    ]
    value.pricing = {"backend": metadata}
    value.observe(event("voice.latency.brain_turn_accepted", 1, correlation_id="admitted"))
    value.observe(event("core.back_brain.provider_usage", 10, correlation_id="admitted",
                        work_id="job-a", usage_source="provider", provider="openai", model="chosen-model",
                        usage={"input_tokens": 1_000_000, "output_tokens": 500_000}))
    value.observe(event("core.back_brain.provider_usage", 20, correlation_id="other",
                        session_id="other-session", work_id="job-other", usage_source="provider",
                        usage={"input_tokens": 9_000_000, "output_tokens": 9_000_000}))
    report = value.finish(status="stopped")
    backend = report["provider_usage_components"][1]
    assert {key: backend["usage"][key] for key in
            ("requests", "source", "input_tokens", "output_tokens")} == {
                "requests": 1, "source": "provider",
                "input_tokens": 1_000_000, "output_tokens": 500_000,
            }
    assert backend["cost_estimate"]["amount"] == pytest.approx(7.5)


def test_backend_identity_mismatch_is_explicit_and_disables_pricing(tmp_path):
    metadata = {"schema_version": 1, "model_id": "configured-model", "currency": "usd",
                "input_price_per_million_tokens": 3.0,
                "output_price_per_million_tokens": 9.0,
                "source": "fixture", "effective_at": "2026-09-13T00:00:00+00:00"}
    value, _ = recorder(tmp_path)
    value.components = [
        {"role": "surface", "provider_id": "openai", "model_id": "gpt-live-1"},
        {"role": "backend", "provider_id": "openai", "model_id": "configured-model"},
    ]
    value.pricing = {"backend": metadata}
    value.observe(event("voice.latency.brain_turn_accepted", 1, correlation_id="admitted"))
    value.observe(event("core.back_brain.provider_usage", 10, correlation_id="admitted",
                        work_id="job-a", usage_source="provider", provider="anthropic",
                        model="actually-used", usage={"input_tokens": 10, "output_tokens": 2}))
    backend = value.finish(status="stopped")["provider_usage_components"][1]
    assert backend["usage"]["observed_provider_id"] == "anthropic"
    assert backend["usage"]["observed_model_id"] == "actually-used"
    assert backend["usage"]["identity_matches_component"] is False
    assert backend["cost_estimate"] is None


def test_voice_event_without_exact_session_is_excluded_after_restart(tmp_path):
    value, _ = recorder(tmp_path)
    row = event("voice.speech.output_stalled", 10)
    row["data"].pop("session_id")
    value.observe(row)
    report = value.finish(status="stopped")
    assert report["event_counts"]["output_stall"] == 0


def test_advisory_and_unplayed_superseded_ack_do_not_invent_quality_failures(tmp_path):
    value, _ = recorder(tmp_path)
    value.observe(event("voice.barge_in.provider_advisory", 10, relation="awaiting_owner"))
    value.observe(event("voice.barge_in.provider_advisory", 20, relation="after_owner_stop"))
    value.observe(event("voice.speech.superseded", 30, speech_id="ack", kind="ack"))
    report = value.finish(status="stopped")
    assert report["event_counts"]["false_or_rejected_barge_in"] == 0
    assert report["event_counts"]["unnecessary_acknowledgement"] == 0

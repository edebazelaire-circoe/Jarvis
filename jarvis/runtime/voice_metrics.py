"""Comparable per-session voice metrics derived from canonical diagnostics."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import time
from typing import Any
import uuid

from jarvis.adapters.file_replace import replace_with_retry
from jarvis.core.latency import (
    BRAIN_TURN_ACCEPTED,
    FIRST_BRAIN_AUDIO,
    FIRST_PUBLIC_PROGRESS,
    LOCAL_OUTPUT_STOPPED,
    WORK_COMPLETED,
)
from jarvis.runtime.pricing import PricingMetadata, TokenPricingMetadata


SCHEMA = "jarvis.voice_benchmark.session"
SCHEMA_VERSION = 1
MAX_EVENTS = 20_000
MAX_TRACE_BYTES = 16 * 1024 * 1024

LATENCY_KEYS = (
    "provider_first_pcm_ms",
    "playback_attempt_ms",
    "time_to_first_audible_reaction_ms",
    "time_to_first_useful_answer_ms",
    "frontend_blocking_ms",
    "delegation_latency_ms",
    "speech_queue_wait_ms",
    "brain_speech_to_first_audio_ms",
    "backend_first_progress_ms",
    "backend_result_ms",
    "user_interrupt_stop_ms",
    "device_drain_ms",
)
COUNT_KEYS = (
    "backend_task_started",
    "backend_task_result",
    "stale_cancellation",
    "user_interruption",
    "false_or_rejected_barge_in",
    "output_stall",
    "unnecessary_acknowledgement",
    "intended_spoken_divergence",
)
_MEASURE_TO_KEY = {
    BRAIN_TURN_ACCEPTED: "frontend_blocking_ms",
    FIRST_BRAIN_AUDIO: "brain_speech_to_first_audio_ms",
    FIRST_PUBLIC_PROGRESS: "backend_first_progress_ms",
    WORK_COMPLETED: "backend_result_ms",
    LOCAL_OUTPUT_STOPPED: "user_interrupt_stop_ms",
}
_USEFUL_SPEECH_KINDS = {"result", "question", "error", "progress", "conversation"}
_DELEGATION_KINDS = {"voice.back_brain.delegation", "voice.live.delegation"}
_DELEGATION_TERMINALS = {
    "append_acknowledged", "append_unconfirmed", "stale", "completed", "failed",
    "cancelled", "interrupted", "unavailable",
}


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def _when(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _safe_prompt(applications: object) -> list[dict[str, object]]:
    from jarvis.runtime.voice_switch import prompt_transition_evidence
    return prompt_transition_evidence(applications)


def _safe_components(value: object, *, provider_id: str, model_id: str) -> list[dict[str, str]]:
    raw = value if isinstance(value, (list, tuple)) else ()
    result: list[dict[str, str]] = []
    for item in raw[:8]:
        if not isinstance(item, dict):
            continue
        component: dict[str, str] = {}
        for key in ("role", "provider_id", "model_id"):
            field = item.get(key)
            if not isinstance(field, str) or not field.strip() or len(field) > 256:
                component = {}
                break
            component[key] = field.strip()
        if component and component["role"] not in {entry["role"] for entry in result}:
            result.append(component)
    if not result:
        result.append({"role": "surface", "provider_id": provider_id, "model_id": model_id})
    return result


def _summary(values: list[float]) -> dict[str, object]:
    if not values:
        return {"count": 0, "samples_ms": [], "min_ms": None, "max_ms": None, "mean_ms": None}
    rounded = [round(value, 1) for value in values]
    return {"count": len(rounded), "samples_ms": rounded, "min_ms": min(rounded),
            "max_ms": max(rounded), "mean_ms": round(sum(rounded) / len(rounded), 1)}


def _component_usage(value: object) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    return {
        "duration_seconds": source.get("duration_seconds"),
        "input_tokens": source.get("input_tokens"),
        "output_tokens": source.get("output_tokens"),
        "total_tokens": source.get("total_tokens"),
        "cached_tokens": source.get("cached_tokens"),
        "reasoning_tokens": source.get("reasoning_tokens"),
        "requests": source.get("requests"),
        "final": source.get("final"),
        "source": source.get("source") or "unavailable",
        "observed_provider_id": source.get("observed_provider_id"),
        "observed_model_id": source.get("observed_model_id"),
        "identity_consistent": source.get("identity_consistent"),
    }


class VoiceSessionMetricRecorder:
    """Write exactly one immutable report for one attempted frontend session.

    Core and Voice are separate processes but append to the same trace. The
    recorder therefore bookmarks the trace at activation and reads that bounded
    suffix at close. Correlation IDs filter out unrelated concurrent activity.
    """

    def __init__(self, *, runtime_root: Path, journal, architecture: str, provider_id: str,
                 model_id: str, configuration_id: str, pricing: object = None, components: object = None,
                 clock=time.monotonic, wall_clock=None) -> None:
        self.runtime_root, self.journal, self.clock = Path(runtime_root), journal, clock
        self.wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self.architecture, self.provider_id, self.model_id = architecture, provider_id, model_id
        self.configuration_id, self.pricing = configuration_id, pricing
        self.components = _safe_components(components, provider_id=provider_id, model_id=model_id)
        self.session_id: str | None = None
        self.conversation_id: str | None = None
        self.started_wall: datetime | None = None
        self.started_mono: float | None = None
        self.prompt_applications: list[dict[str, object]] = []
        self.annotations: list[dict[str, object]] = []
        self._events: list[dict[str, Any]] = []
        self._trace_offset = 0
        self._trace_evidence_complete = True
        self._finished = False
        self._pending_report: dict[str, object] | None = None

    def start(self, *, conversation_id: str, session_id: str | None = None) -> None:
        if self.started_mono is not None:
            raise RuntimeError("metric session already started")
        self.session_id = session_id or str(uuid.uuid4())
        self.conversation_id = conversation_id
        self.started_wall = self.wall_clock().astimezone(timezone.utc)
        self.started_mono = self.clock()
        path = getattr(self.journal, "trace_path", None)
        try:
            self._trace_offset = Path(path).stat().st_size if path is not None else 0
        except OSError:
            self._trace_offset = 0

    def identify_frontend(self, *, session_id: str, prompt_applications: object) -> None:
        if self._finished:
            raise RuntimeError("metric session already finished")
        self.session_id = session_id
        self.prompt_applications = _safe_prompt(prompt_applications)

    def observe(self, event: dict[str, Any]) -> None:
        """Accept deterministic synthetic events without a filesystem journal."""
        if self.started_mono is not None and not self._finished and isinstance(event, dict):
            self._events.append(event)

    def annotate(self, name: str, *, outcome: str, note: str = "") -> None:
        if (not isinstance(name, str) or not name or len(name) > 120
                or outcome not in {"pass", "fail", "uncertain"}
                or not isinstance(note, str) or len(note) > 1000):
            raise ValueError("invalid benchmark annotation")
        encoded = note.encode("utf-8")
        self.annotations.append({
            "name": name,
            "outcome": outcome,
            "note_length": len(note),
            "note_fingerprint": hashlib.sha256(encoded).hexdigest() if encoded else None,
        })

    def finish(self, *, status: str, live_record=None) -> dict[str, object]:
        if self.started_mono is None or self.started_wall is None or self.session_id is None:
            raise RuntimeError("metric session is not started")
        if self._finished:
            raise RuntimeError("metric session already finished")
        if status not in {"stopped", "failed", "uncertain"}:
            raise ValueError("invalid metric terminal status")
        if self._pending_report is not None:
            self._write(self._pending_report)
            self._finished = True
            return self._pending_report
        events = [*self._events, *self._read_trace_suffix()]
        relevant = [event for event in events if self._belongs(event)]
        traced_prompt_applications = _safe_prompt([
            event.get("data") for event in relevant
            if event.get("kind") == "voice.hint.analysis"
            and isinstance(event.get("data"), dict)
            and isinstance(event["data"].get("static_fingerprint"), str)
        ])
        prompt_applications = list(self.prompt_applications)
        for application in traced_prompt_applications:
            if application not in prompt_applications:
                prompt_applications.append(application)
        latencies, counts, traced_usage = self._derive(relevant)
        duration = max(0.0, self.clock() - self.started_mono)
        live_active = _finite(getattr(live_record, "active_seconds", None))
        lifecycle_usage = _finite(getattr(live_record, "provider_usage_seconds", None))
        surface_usage = traced_usage.get("surface") if isinstance(traced_usage.get("surface"), dict) else {}
        traced_duration = _finite(surface_usage.get("duration_seconds"))
        provider_usage = lifecycle_usage if lifecycle_usage is not None else traced_duration
        provider_final = (bool(getattr(live_record, "provider_usage_final", False))
                          if live_record is not None else surface_usage.get("source") == "provider_final")
        provider_usage_record = {
            "duration_seconds": provider_usage,
            "input_tokens": surface_usage.get("input_tokens"),
            "output_tokens": surface_usage.get("output_tokens"),
            "final": provider_final,
            "source": "live_lifecycle" if lifecycle_usage is not None else surface_usage.get("source"),
        }
        basis_seconds = provider_usage if provider_usage is not None else live_active
        basis = "provider_usage" if provider_usage is not None else "live_active_seconds"
        pricing_by_role = self.pricing if isinstance(self.pricing, dict) and any(
            role in self.pricing for role in {"surface", "analysis", "backend"}) else {}
        surface_pricing = pricing_by_role.get("surface") if pricing_by_role else self.pricing
        price = PricingMetadata.parse(surface_pricing, model_id=self.model_id)
        cost = price.estimate(basis_seconds, basis=basis) if price is not None and basis_seconds is not None else None
        component_usage = []
        for component in self.components:
            role = component["role"]
            usage = _component_usage(provider_usage_record if role == "surface" else traced_usage.get(role, {}))
            component_cost = cost if role == "surface" else None
            token_price = TokenPricingMetadata.parse(
                pricing_by_role.get(role) if pricing_by_role else None,
                model_id=component["model_id"],
            )
            input_tokens, output_tokens = usage.get("input_tokens"), usage.get("output_tokens")
            identity_matches = True
            if role == "backend":
                identity_matches = (
                    usage.get("identity_consistent") is True
                    and usage.get("observed_provider_id") == component["provider_id"]
                    and usage.get("observed_model_id") == component["model_id"]
                )
                usage["identity_matches_component"] = identity_matches
            if (identity_matches and token_price is not None
                    and type(input_tokens) is int and type(output_tokens) is int):
                component_cost = token_price.estimate(input_tokens=input_tokens, output_tokens=output_tokens)
            component_usage.append({**component, "usage": usage, "cost_estimate": component_cost})
        identity = {"architecture": self.architecture, "provider_id": self.provider_id,
                    "model_id": self.model_id, "configuration_id": self.configuration_id,
                    "components": self.components, "prompt_applications": prompt_applications}
        fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        report = {
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            **identity,
            "session_fingerprint": fingerprint,
            "started_at": self.started_wall.isoformat(),
            "ended_at": self.wall_clock().astimezone(timezone.utc).isoformat(),
            "session_duration_seconds": round(duration, 3),
            "terminal_status": status,
            "live_active_seconds": live_active,
            "provider_usage_seconds": provider_usage,
            "provider_usage_final": provider_final,
            "provider_usage": provider_usage_record,
            "provider_usage_components": component_usage,
            "trace_evidence_complete": self._trace_evidence_complete,
            "latency_metrics": {key: _summary(latencies[key]) for key in LATENCY_KEYS},
            "event_counts": counts,
            "annotations": list(self.annotations),
            "cost_estimate": cost,
        }
        self._pending_report = report
        self._write(report)
        self._finished = True
        return report

    def _read_trace_suffix(self) -> list[dict[str, Any]]:
        path = getattr(self.journal, "trace_path", None)
        if path is None:
            return []
        try:
            with Path(path).open("rb") as handle:
                handle.seek(self._trace_offset)
                raw = handle.read(MAX_TRACE_BYTES + 1)
        except OSError:
            self._trace_evidence_complete = False
            return []
        if len(raw) > MAX_TRACE_BYTES:
            self._trace_evidence_complete = False
            raw = raw[:MAX_TRACE_BYTES]
        rows: list[dict[str, Any]] = []
        lines = raw.splitlines()
        if len(lines) > MAX_EVENTS:
            self._trace_evidence_complete = False
        for line in lines[:MAX_EVENTS]:
            try:
                value = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._trace_evidence_complete = False
                continue
            if isinstance(value, dict):
                rows.append(value)
        return rows

    def _belongs(self, event: dict[str, Any]) -> bool:
        data = event.get("data")
        data = data if isinstance(data, dict) else {}
        conversation = data.get("conversation_id")
        session = data.get("session_id")
        if session is not None:
            return session == self.session_id and (conversation is None or conversation == self.conversation_id)
        return str(event.get("kind") or "").startswith("core.") and conversation == self.conversation_id

    def _derive(self, events: list[dict[str, Any]]) -> tuple[dict[str, list[float]], dict[str, int], dict[str, object]]:
        latencies = {key: [] for key in LATENCY_KEYS}
        counts = {key: 0 for key in COUNT_KEYS}
        speech_kinds: dict[str, str] = {}
        direct_outputs: set[str] = set()
        delegations: dict[str, datetime] = {}
        provider_usage: dict[str, object] = {}
        admitted_correlations: set[str] = set()
        backend_work_ids: set[str] = set()
        useful_segments: set[str] = set()
        divergent_speeches: set[str] = set()

        # Core has no frontend session id. A Core correlation belongs to this
        # report only when a session-bound Voice event proves the same origin.
        for event in events:
            data = event.get("data")
            data = data if isinstance(data, dict) else {}
            if data.get("session_id") == self.session_id and not str(event.get("kind") or "").startswith("core."):
                correlation = data.get("correlation_id")
                if isinstance(correlation, str) and correlation:
                    admitted_correlations.add(correlation)
            if event.get("kind") == "voice.speech.queued" and isinstance(data.get("speech_id"), str):
                speech_kinds[data["speech_id"]] = str(data.get("kind") or "")
            if event.get("kind") == "voice.conversation.requested" and isinstance(data.get("output_id"), str):
                direct_outputs.add(data["output_id"])
        for event in events:
            if event.get("kind") != "core.brain.backend_task_started":
                continue
            data = event.get("data")
            data = data if isinstance(data, dict) else {}
            if data.get("correlation_id") in admitted_correlations and isinstance(data.get("work_id"), str):
                backend_work_ids.add(data["work_id"])

        for event in events:
            kind = str(event.get("kind") or "")
            data = event.get("data")
            data = data if isinstance(data, dict) else {}
            if kind.startswith("core.") and data.get("correlation_id") not in admitted_correlations:
                session_owned_usage = (
                    kind == "core.back_brain.provider_usage"
                    and data.get("session_id") == self.session_id
                    and data.get("conversation_id") == self.conversation_id
                )
                if not session_owned_usage:
                    continue
            instant = _when(event.get("ts"))
            measure = str(data.get("measure") or "")
            elapsed = _finite(data.get("elapsed_ms"))
            target = _MEASURE_TO_KEY.get(measure)
            work_owned = data.get("work_id") in backend_work_ids
            if (target is not None and elapsed is not None
                    and (measure not in {FIRST_PUBLIC_PROGRESS, WORK_COMPLETED} or work_owned)):
                latencies[target].append(elapsed)
            if kind == "voice.latency.first_audible_write" and elapsed is not None:
                latencies["time_to_first_audible_reaction_ms"].append(elapsed)
            elif kind == "voice.latency.provider_first_pcm" and elapsed is not None:
                latencies["provider_first_pcm_ms"].append(elapsed)
            elif kind == "voice.latency.playback_attempted" and elapsed is not None:
                latencies["playback_attempt_ms"].append(elapsed)
            elif kind == "audio.drain_result" and data.get("status") == "completed" and elapsed is not None:
                latencies["device_drain_ms"].append(elapsed)

            speech_id = data.get("speech_id")
            output_id = data.get("output_id")
            if kind == "voice.speech.dispatched":
                queue_wait = _finite(data.get("queue_wait_ms"))
                if queue_wait is not None:
                    latencies["speech_queue_wait_ms"].append(queue_wait)

            if kind == "voice.latency.output_first_write" and elapsed is not None:
                useful = (isinstance(speech_id, str) and speech_kinds.get(speech_id) in _USEFUL_SPEECH_KINDS)
                useful = useful or (isinstance(output_id, str) and output_id in direct_outputs)
                segment = data.get("segment_id")
                segment_key = segment if isinstance(segment, str) else f"output:{output_id}"
                if useful and segment_key not in useful_segments:
                    useful_segments.add(segment_key)
                    latencies["time_to_first_useful_answer_ms"].append(elapsed)

            if kind == "core.brain.backend_task_started" and work_owned:
                counts["backend_task_started"] += 1
            elif kind == "core.brain.backend_task_result" and work_owned:
                counts["backend_task_result"] += 1
            if kind in {"voice.speech.superseded", "voice.speech.expired", "core.brain.replies_superseded"}:
                counts["stale_cancellation"] += 1
            if kind == "voice.barge_in":
                counts["user_interruption"] += 1
            if kind in {"voice.barge_in_rejected", "voice.barge_in_ignored"}:
                counts["false_or_rejected_barge_in"] += 1
            if kind == "voice.speech.output_stalled":
                counts["output_stall"] += 1
            if (kind == "voice.state.spoken_diverged" and isinstance(speech_id, str)
                    and speech_id not in divergent_speeches):
                divergent_speeches.add(speech_id)
                counts["intended_spoken_divergence"] += 1
            if kind == "voice.realtime.usage":
                surface = provider_usage.setdefault("surface", {})
                assert isinstance(surface, dict)
                duration = _finite(data.get("duration_seconds"))
                if duration is not None:
                    surface["duration_seconds"] = duration
                for name in ("input_tokens", "output_tokens"):
                    value = data.get(name)
                    if type(value) is int and value >= 0:
                        surface[name] = value
                if isinstance(data.get("source"), str):
                    surface["source"] = data["source"]
            elif kind == "voice.hint.analysis" and isinstance(data.get("usage"), dict):
                analysis = provider_usage.setdefault("analysis", {"requests": 0, "source": data.get("usage_source")})
                assert isinstance(analysis, dict)
                analysis["requests"] = int(analysis.get("requests", 0)) + 1
                for name in ("input_tokens", "output_tokens", "total_tokens", "cached_tokens", "reasoning_tokens"):
                    value = data["usage"].get(name)
                    if type(value) is int and value >= 0:
                        analysis[name] = int(analysis.get(name, 0)) + value
            elif kind == "core.back_brain.provider_usage" and isinstance(data.get("usage"), dict):
                backend = provider_usage.setdefault("backend", {"requests": 0, "source": data.get("usage_source")})
                assert isinstance(backend, dict)
                first_backend_request = int(backend.get("requests", 0)) == 0
                backend["requests"] = int(backend.get("requests", 0)) + 1
                observed_provider, observed_model = data.get("provider"), data.get("model")
                observed = (
                    observed_provider.strip() if isinstance(observed_provider, str) and 0 < len(observed_provider.strip()) <= 256 else None,
                    observed_model.strip() if isinstance(observed_model, str) and 0 < len(observed_model.strip()) <= 256 else None,
                )
                previous = (backend.get("observed_provider_id"), backend.get("observed_model_id"))
                if first_backend_request:
                    backend["observed_provider_id"], backend["observed_model_id"] = observed
                    backend["identity_consistent"] = None not in observed
                elif previous != observed:
                    backend["identity_consistent"] = False
                for name in ("input_tokens", "output_tokens", "total_tokens", "cached_tokens", "reasoning_tokens"):
                    value = data["usage"].get(name)
                    if type(value) is int and value >= 0:
                        backend[name] = int(backend.get(name, 0)) + value

            if kind in _DELEGATION_KINDS and isinstance(data.get("job_id"), str) and instant is not None:
                job_id, delegation_status = data["job_id"], str(data.get("status") or "")
                if delegation_status == "accepted":
                    delegations.setdefault(job_id, instant)
                elif delegation_status in _DELEGATION_TERMINALS:
                    started = delegations.pop(job_id, None)
                    if started is not None:
                        latencies["delegation_latency_ms"].append(max(0.0, (instant - started).total_seconds() * 1000))
        counts["unnecessary_acknowledgement"] += sum(
            annotation["name"] == "unnecessary_acknowledgement" and annotation["outcome"] == "fail"
            for annotation in self.annotations
        )
        return latencies, counts, provider_usage

    def _write(self, report: dict[str, object]) -> None:
        root = self.runtime_root / "benchmarks" / "voice-sessions"
        root.mkdir(parents=True, exist_ok=True)
        readable = re.sub(r"[^A-Za-z0-9._-]", "_", self.session_id or "session")[:80] or "session"
        digest = hashlib.sha256((self.session_id or "session").encode()).hexdigest()[:12]
        stem = f"{readable}-{digest}"
        json_path = root / f"{stem}.json"
        summary_path = root / f"{stem}.txt"
        metric_lines = []
        for key, value in report["latency_metrics"].items():
            metric_lines.append(f"{key}: count={value['count']} mean_ms={value['mean_ms']}")
        lines = [
            f"Voice session {self.session_id}",
            f"{self.architecture} | {self.provider_id}/{self.model_id}",
            f"configuration={self.configuration_id} fingerprint={report['session_fingerprint']}",
            f"status={report['terminal_status']} duration={report['session_duration_seconds']:.3f}s",
            f"trace_evidence_complete={report['trace_evidence_complete']}",
            "provider_usage=" + json.dumps(report["provider_usage"], sort_keys=True),
            "provider_usage_components=" + json.dumps(report["provider_usage_components"], sort_keys=True),
            "cost_estimate=" + json.dumps(report["cost_estimate"], sort_keys=True),
            "event_counts=" + json.dumps(report["event_counts"], sort_keys=True),
            "annotations=" + json.dumps(report["annotations"], sort_keys=True),
            *metric_lines,
        ]
        json_tmp = json_path.with_suffix(json_path.suffix + ".tmp")
        summary_tmp = summary_path.with_suffix(summary_path.suffix + ".tmp")
        try:
            # The JSON file is the commit marker: a visible machine report
            # always has its human-readable companion already in place.
            json_tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            summary_tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
            replace_with_retry(summary_tmp, summary_path)
            replace_with_retry(json_tmp, json_path)
        finally:
            json_tmp.unlink(missing_ok=True)
            summary_tmp.unlink(missing_ok=True)

"""Replay / evaluation harness of the Tool Brain (handoff jarvis-tool-brain-ui-orchestrator, Slice 10).

Contract: `docs/tool-brain-contracts.md` section 18. Run: `.venv/Scripts/python.exe -m tests.replay.tool_brain_replay`.

A *scenario* (`tests/fixtures/tool_brain_replay/*.json`, schema `tool_brain.replay/1`) is a recorded conversation
moment: the scene and Boards the user sees, then ordered *steps* (Jarvis intents, speech progress, wakes, world changes,
clock advances, decision steps, queue pumps). The harness drives the REAL stack, no mock of the logic under test:

    wake -> ToolBrainRuntime (perception, manifest, validate_call) -> ToolBrainActionQueue -> UiActionExecutor
         -> SceneService.apply_if (SQLite scene + prefab catalog) / board switcher spy

with a fake monotonic clock (no sleeping: coalescing, rate limit, backoff and expiry advance by `advance`). Only the
*decider* varies:

- `scripted` (default, deterministic, CI): the scenario carries the decider replies as wire payloads, decoded by the
  same strict codec as a model answer (`reply_from_payload`), so a recorded model answer can be pasted as a fixture;
- `rule`: `RuleToolBrainDecider`;
- `--live`: `ModelToolBrainDecider` on the tool-less Claude CLI (`JARVIS_TOOL_BRAIN_MODEL`), same scenarios, soft scoring.

Scoring (`score`) has two layers:

1. **Invariants** (never negotiable, hard failures in every mode): no action reaches a mutation owner unless the runtime
   judged it `would_apply`; no speech-bound action executes after an interruption; no action is applied twice; no write
   happens outside the queue; the scene still holds after the run.
2. **Metrics** (reported, compared to scenario expectations in scripted mode): decisions by outcome, proposed /
   would_apply / rejected actions with refusal codes, queue end states, executed, churn (cancelled + invalidated per
   queued), replans, and per-step wall time.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import jarvis
from jarvis.adapters.file_prefab_library import FilePrefabLibrary
from jarvis.adapters.sqlite_scene import SQLiteSceneRepository
from jarvis.core.prefab_service import PrefabService
from jarvis.core.scene_service import SceneService
from jarvis.domain.scene import (
    SceneActor, SceneCommand, SceneGeometry, SceneObjectFields, SceneObjectKind, SceneOp, ScenePayload, Visibility,
)
from jarvis.domain.scene_selection import SceneSelection
from jarvis.domain.workspace_board import Board
from jarvis.ports.tool_brain import DeciderError, ToolBrainReply, reply_from_payload
from jarvis.runtime.mcp_catalog import build_catalog
from jarvis.runtime.tool_brain_decider import RuleToolBrainDecider
from jarvis.runtime.tool_brain_executor import UiActionExecutor, default_adapters
from jarvis.runtime.tool_brain_perception import SpeechSection
from jarvis.runtime.tool_brain_queue import DONE, SCHEDULED, ToolBrainActionQueue
from jarvis.runtime.tool_brain_runtime import (
    BACKOFF, COALESCING, DECIDED, IDLE, RATE_LIMITED, UNCHANGED, ToolBrainConfig, ToolBrainMode, ToolBrainRuntime,
    WakeClass,
)

SCHEMA = "tool_brain.replay/1"
REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "tool_brain_replay"
PACKAGE = Path(jarvis.__file__).resolve().parent / "prefabs" / "base"
AT = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
DISPLAY = "jarvis-display"
#: Queue statuses where the action never mutated anything.
_NEVER_RAN = {"cancelled", "invalidated", "expired", "superseded", "pending", "failed"}
SPEECH_TRIGGERS = {"speech_chunk", "speech", "intent"}
MAX_SETTLE_ROUNDS = 8


class ScenarioError(ValueError):
    """The fixture itself is malformed (never a Tool Brain failure)."""


# ------------------------------------------------------------------ fixtures


def load_scenario(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise ScenarioError(f"{path.name}: schema must be {SCHEMA!r}")
    for key in ("id", "title", "scene", "steps"):
        if key not in data:
            raise ScenarioError(f"{path.name}: missing {key!r}")
    return data


def load_scenarios(directory: Path = FIXTURES, only: set[str] | None = None) -> list[dict[str, Any]]:
    loaded = [load_scenario(path) for path in sorted(directory.glob("*.json"))]
    ids = [item["id"] for item in loaded]
    if len(set(ids)) != len(ids):
        raise ScenarioError("duplicate scenario ids")
    return [item for item in loaded if not only or item["id"] in only]


# ------------------------------------------------------------------ doubles


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class BoardsSpy:
    """Read side of the Boards for the runtime + the switch seam the executor calls. Counts switches."""

    def __init__(self, boards: list[Mapping[str, Any]], active: str) -> None:
        self._boards = [Board(board_id=item["id"], title=item.get("title", item["id"]), created_at=AT, updated_at=AT)
                        for item in boards]
        self.active = active
        self.switch_calls: list[str] = []

    async def list(self, *, include_archived: bool = False):
        return tuple(self._boards)

    async def active_board_id(self):
        return self.active

    async def switch(self, board_id: str, *, origin: str = "protocol"):  # not the executor seam, see `switcher`
        raise AssertionError("the executor must go through the injected switcher")

    async def switcher(self, board_id: str) -> Mapping[str, Any]:
        self.switch_calls.append(board_id)
        previous, self.active = self.active, board_id
        return {"status": "applied" if previous != board_id else "unchanged", "board_id": board_id,
                "previous_board_id": previous}


class SceneSpy:
    """Delegates to the real `SceneService`, counting every write (the only path must be `apply_if`)."""

    def __init__(self, service: SceneService) -> None:
        self._service = service
        self.apply_if_calls = 0
        self.other_writes = 0

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    async def apply_if(self, *args, **kwargs):
        self.apply_if_calls += 1
        return await self._service.apply_if(*args, **kwargs)

    async def apply(self, *args, **kwargs):
        self.other_writes += 1
        return await self._service.apply(*args, **kwargs)

    async def seed(self, command):
        return await self._service.apply(command)


class ScriptedDecider:
    """Plays the scenario's recorded replies in order (the last one repeats), through the production codec."""

    name = "scripted"

    def __init__(self, replies: list[Any]) -> None:
        self._replies = list(replies) or [{}]
        self.requests: list[Any] = []
        self.mode = "up"

    async def decide(self, request, *, timeout_s):
        self.requests.append(request)
        if self.mode == "fail":
            raise DeciderError("tool_brain_decider_failed", "scripted outage")
        payload = self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]
        if isinstance(payload, Mapping) and "error" in payload:
            raise DeciderError(str(payload["error"].get("code", "tool_brain_decider_failed")),
                               str(payload["error"].get("detail", "")))
        return reply_from_payload(payload, model="scripted")


class RecordingModel:
    """Wraps the text model of the live decider: keeps every prompt and raw answer as evidence, caps the calls."""

    supports_images = False

    def __init__(self, inner: Any, *, max_calls: int) -> None:
        self._inner, self.model, self.max_calls = inner, inner.model, max_calls
        self.calls: list[dict[str, Any]] = []

    async def complete(self, prompt: str, *, timeout_s: float, images=()):
        from jarvis.ports.context_enrichment import MODEL_FAILED, EnrichmentModelError

        if len(self.calls) >= self.max_calls:
            raise EnrichmentModelError(MODEL_FAILED, f"replay call budget of {self.max_calls} reached")
        entry: dict[str, Any] = {"n": len(self.calls) + 1, "prompt": prompt, "prompt_bytes": len(prompt.encode("utf-8"))}
        self.calls.append(entry)
        started = time.perf_counter()
        try:
            reply = await self._inner.complete(prompt, timeout_s=timeout_s)
        except Exception as exc:  # noqa: BLE001 - recorded then re-raised: the decider maps it to a typed failure
            entry.update(wall_ms=round((time.perf_counter() - started) * 1000), error=f"{type(exc).__name__}: {exc}")
            raise
        entry.update(wall_ms=round((time.perf_counter() - started) * 1000), reply=reply.text,
                     reply_bytes=len(reply.text.encode("utf-8")), cli_duration_ms=reply.duration_ms,
                     cost_usd=reply.cost_usd, usage=dict(reply.usage or {}), model=reply.model)
        return reply


# ------------------------------------------------------------------ rig


@dataclass
class Rig:
    scenario: dict[str, Any]
    clock: FakeClock
    scene: SceneSpy
    boards: BoardsSpy
    queue: ToolBrainActionQueue
    runtime: ToolBrainRuntime
    decider: Any
    speech: SpeechSection | None = None
    live: bool = False
    intents: list[Mapping[str, Any]] = field(default_factory=list)
    speech_raw: dict[str, Any] | None = None
    log: list[dict[str, Any]] = field(default_factory=list)
    violations: list[dict[str, Any]] = field(default_factory=list)
    #: Timing checks made *during* the replay (`expect_hidden` steps): "appropriate timing" for scripted scenarios.
    timing_mismatches: list[str] = field(default_factory=list)
    step_ms: list[dict[str, Any]] = field(default_factory=list)


def _note_command(spec: Mapping[str, Any]) -> SceneCommand:
    placed = spec.get("placed", True)
    return SceneCommand(
        op=SceneOp.UPSERT_OBJECT, actor=SceneActor.BRAIN, object_id=spec["id"],
        fields=SceneObjectFields(
            kind=SceneObjectKind.ARTIFACT, category="note", payload=ScenePayload(title=spec.get("title", spec["id"])),
            geometry=SceneGeometry(spec.get("x", 0), spec.get("y", 0), spec.get("w", 10), spec.get("h", 10))
            if placed else None,
            visibility=Visibility.HIDDEN if spec.get("hidden") else Visibility.VISIBLE))


def speech_section(spec: Mapping[str, Any] | None) -> SpeechSection | None:
    if not spec:
        return None
    phases = spec.get("phases", "P")
    return SpeechSection("wired", {"chains": [{
        "chain": spec.get("chain", "r1"), "corr": spec.get("corr", "c1"), "n": len(phases),
        "state": spec.get("state", "playing"), "phases": phases, "chunks": list(spec.get("chunks", []))}],
        "obsolete_chunk_ids": list(spec.get("obsolete", []))})


async def build_rig(scenario: Mapping[str, Any], workdir: Path, catalog: Mapping[str, Any],
                    decider_factory: Callable[[Mapping[str, Any]], Any], *, decision_timeout_s: float = 30.0,
                    intents_source: Callable[[str, str | None], list[Mapping[str, Any]]] | None = None) -> Rig:
    prefabs = PrefabService(FilePrefabLibrary(PACKAGE, workdir / "prefab-data"))
    await prefabs.start()
    service = SceneService(SQLiteSceneRepository(workdir / "scene.sqlite3"), prefab_validator=prefabs)
    await service.start()
    for spec in scenario["scene"].get("objects", []):
        result = await service.apply(_note_command(spec))
        if result.outcome.value != "applied":
            raise ScenarioError(f"{scenario['id']}: cannot seed {spec['id']}: {result.outcome}")
    spy = SceneSpy(service)
    boards_cfg = scenario["scene"].get("boards") or [{"id": "default", "title": "Principal"}]
    boards = BoardsSpy(boards_cfg, scenario["scene"].get("active_board", boards_cfg[0]["id"]))
    clock = FakeClock()
    adapters = default_adapters(spy, boards, board_switcher=boards.switcher)
    queue = ToolBrainActionQueue(clock=clock, supported=lambda server, tool: (server, tool) in adapters)
    holder: list[ToolBrainRuntime] = []
    executor = UiActionExecutor(spy, boards, queue, adapters,
                                gate=lambda: bool(holder) and holder[0].mode is ToolBrainMode.ACTIVE)
    decider = decider_factory(scenario)
    rig = Rig(scenario, clock, spy, boards, queue, None, decider)  # type: ignore[arg-type]

    async def catalog_now():
        return catalog

    rig.runtime = ToolBrainRuntime(
        spy, boards, lambda: rig.decider, config=ToolBrainConfig(
            mode=ToolBrainMode.ACTIVE, min_interval_s=1.0, decision_timeout_s=decision_timeout_s),
        catalog=catalog_now, speech_source=lambda: rig.speech, intents_source=intents_source or (lambda c, k: list(rig.intents)),
        queue=queue, executor=executor, clock=clock, wall_clock=lambda: AT)
    holder.append(rig.runtime)
    rig._service = service  # type: ignore[attr-defined]
    rig._prefabs = prefabs  # type: ignore[attr-defined]
    return rig


async def close_rig(rig: Rig) -> None:
    await rig._service.close()  # type: ignore[attr-defined]


# ------------------------------------------------------------------ steps


def _speech_dead(rig: Rig, record) -> bool:
    """Is the speech this action is bound to interrupted / obsolete *now*? (the invariant I2 oracle)"""

    if rig.speech_raw is None:
        return False
    chain = (rig.speech_raw.get("chains") or [{}])[0]
    obsolete = set(rig.speech_raw.get("obsolete_chunk_ids") or [])
    trigger = record.trigger
    if chain.get("state") == "interrupted":
        return True
    if trigger.chunk_id and trigger.chunk_id in obsolete:
        return True
    return any(item.get("id") == trigger.chunk_id and item.get("ph") == "obsolete" for item in chain.get("chunks", []))


async def _settle_decision(rig: Rig) -> str:
    """Run `step()` until a decision (advancing the fake clock through coalescing / rate limit / backoff)."""

    last = IDLE
    for _ in range(MAX_SETTLE_ROUNDS):
        last = await rig.runtime.step()
        if last in {DECIDED, UNCHANGED, IDLE}:
            return last
        wait = rig.runtime._wait_for(last)  # noqa: SLF001 - the runtime's own next-deadline arithmetic, not duplicated
        rig.clock.advance(wait + 0.001)
    return last


async def run_step(rig: Rig, step: Mapping[str, Any]) -> None:
    kind = step["do"]
    started = time.perf_counter()
    entry: dict[str, Any] = {"do": kind}
    if kind == "intents":
        rig.intents = list(step["set"])
    elif kind == "speech":
        rig.speech_raw = None if step.get("clear") else {
            "chains": [{"chain": step.get("chain", "r1"), "corr": step.get("corr", "c1"),
                        "n": len(step.get("phases", "P")), "state": step.get("state", "playing"),
                        "phases": step.get("phases", "P"), "chunks": list(step.get("chunks", []))}],
            "obsolete_chunk_ids": list(step.get("obsolete", []))}
        rig.speech = speech_section(None if step.get("clear") else step)
    elif kind == "wake":
        rig.runtime.wake(WakeClass(step["class"]), step.get("reason", "replay"), urgent=step.get("urgent"),
                         conversation_id=step.get("conversation_id", "conv-1"),
                         correlation_id=step.get("correlation_id", "c1"))
    elif kind == "event":
        rig.runtime.note_event(step["name"])
    elif kind == "advance":
        rig.clock.advance(float(step["seconds"]))
    elif kind == "decide":
        entry["result"] = await _settle_decision(rig)
        decision = rig.runtime.decisions()[-1] if rig.runtime.decisions() else None
        entry["decision"] = decision.decision_id if decision else None
    elif kind == "pump":
        before = {view.record.action_id for view in rig.queue.views() if view.status in {DONE, SCHEDULED}}
        speech_view = {view.record.action_id: view.record for view in rig.queue.views()}
        entry["executed"] = await rig.runtime.pump()
        for view in rig.queue.views():
            if view.status == DONE and view.record.action_id not in before \
                    and view.record.trigger.kind in SPEECH_TRIGGERS and _speech_dead(rig, speech_view[view.record.action_id]):
                rig.violations.append({"invariant": "obsolete_speech_action_executed",
                                       "action_id": view.record.action_id})
    elif kind == "expect_hidden":  # timing oracle (scripted only: a model may legitimately choose another valid timing)
        if rig.live:
            entry["skipped"] = "live"
        hidden = sorted(o.object_id for o in (await rig.scene.snapshot()).objects if o.visibility is Visibility.HIDDEN)
        if not rig.live and hidden != sorted(step["ids"]):
            rig.timing_mismatches.append(f"after step {len(rig.log)}: hidden {hidden} != {sorted(step['ids'])}")
    elif kind == "archive":
        await rig._service.apply(SceneCommand(  # noqa: SLF001 - the user acting on the scene, not the Tool Brain
            op=SceneOp.ARCHIVE_SELECTION, actor=SceneActor.USER, selection=SceneSelection(ids=tuple(step["ids"]))))
    elif kind == "decider":
        if hasattr(rig.decider, "mode"):
            rig.decider.mode = step["mode"]
        if step["mode"] == "absent":
            rig.decider = None
    else:
        raise ScenarioError(f"unknown step {kind!r}")
    entry["wall_ms"] = round((time.perf_counter() - started) * 1000, 2)
    rig.log.append(entry)
    if kind in {"decide", "pump"}:
        rig.step_ms.append({"step": kind, "ms": entry["wall_ms"]})


# ------------------------------------------------------------------ scoring


async def score(rig: Rig) -> dict[str, Any]:
    decisions = rig.runtime.decisions(64)
    status = rig.runtime.status()
    views = rig.queue.views()
    admitted: dict[str, str] = {}  # action_id -> verdict of the decision that produced it
    proposed = would_apply = rejected = 0
    rejected_codes: dict[str, int] = {}
    for decision in decisions:
        for verdict in decision.actions:
            proposed += 1
            if verdict.verdict == "would_apply":
                would_apply += 1
            else:
                rejected += 1
                for refusal in verdict.refusals:
                    code = str(refusal.get("code"))
                    rejected_codes[code] = rejected_codes.get(code, 0) + 1
            if verdict.queued and verdict.queued.get("action_id"):
                admitted[verdict.queued["action_id"]] = verdict.verdict
    by_status: dict[str, int] = {}
    for view in views:
        by_status[view.status] = by_status.get(view.status, 0) + 1
    violations = list(rig.violations)
    for view in views:  # I1: a mutation owner only ever sees what the runtime judged legal
        if view.status in {DONE, SCHEDULED} and admitted.get(view.record.action_id) != "would_apply":
            violations.append({"invariant": "executed_without_would_apply", "action_id": view.record.action_id})
    scene_done = sum(1 for view in views if view.status == DONE and view.record.server == DISPLAY) \
        + sum(1 for view in views if view.status == DONE and view.record.server == "jarvis-surface")
    board_done = sum(1 for view in views if view.status in {DONE, SCHEDULED} and view.record.tool == "board_switch")
    if rig.scene.apply_if_calls > scene_done:  # I3: one write per executed action (a refused write is not counted: owner rejects before)
        violations.append({"invariant": "double_or_orphan_mutation", "apply_if_calls": rig.scene.apply_if_calls,
                           "done_scene_actions": scene_done})
    if len(rig.boards.switch_calls) > board_done:
        violations.append({"invariant": "double_board_switch", "calls": len(rig.boards.switch_calls),
                           "done": board_done})
    if rig.scene.other_writes:  # I4: the Tool Brain never writes outside the queue
        violations.append({"invariant": "write_outside_queue", "count": rig.scene.other_writes})
    queued = sum(1 for view in views)
    churn = (by_status.get("cancelled", 0) + by_status.get("invalidated", 0)) / queued if queued else 0.0
    snapshot = await rig.scene.snapshot()
    positions = {obj.object_id: obj.geometry.x for obj in snapshot.objects if obj.geometry is not None}
    decisions_wire = [{"decision_id": d.decision_id, "outcome": d.outcome, "decider": d.decider, "model": d.model,
                       "classes": d.trigger.get("classes"), "rounds": d.rounds,
                       "inspections": [dict(i) for i in d.inspections], "rationale": d.rationale,
                       "perception_bytes": d.perception_bytes, "manifest_tools": d.manifest_tools,
                       "error_code": d.error_code, "cost_usd": d.cost_usd,
                       "actions": [{"tool": a.action.tool, "arguments": dict(a.action.arguments),
                                    "trigger": a.action.trigger, "verdict": a.verdict,
                                    "refusal_codes": [str(r.get("code")) for r in a.refusals],
                                    "queued": dict(a.queued) if a.queued else None, "reason": a.action.reason}
                                   for a in d.actions]} for d in decisions]
    return {
        "scenario": rig.scenario["id"], "violations": violations,
        "metrics": {
            "decisions": len(decisions), "outcomes": [d.outcome for d in decisions],
            "proposed": proposed, "would_apply": would_apply, "rejected": rejected, "rejected_codes": rejected_codes,
            "queue": by_status, "executed": by_status.get(DONE, 0) + by_status.get(SCHEDULED, 0),
            "churn": round(churn, 3), "replans": status["counters"].get("replans", 0),
            "invalid_proposal_rate": round(rejected / proposed, 3) if proposed else 0.0,
            "final_x": positions, "hidden": sorted(o.object_id for o in snapshot.objects
                                                   if o.visibility is Visibility.HIDDEN),
            "timing_mismatches": list(rig.timing_mismatches), "active_board": rig.boards.active,
            "switch_calls": list(rig.boards.switch_calls), "apply_if_calls": rig.scene.apply_if_calls,
            "step_ms_max": max((item["ms"] for item in rig.step_ms), default=0.0)},
        "decisions": decisions_wire, "steps": rig.log}


def check_expectations(report: Mapping[str, Any], expect: Mapping[str, Any]) -> list[str]:
    """Scripted mode: exact expectations of a scenario. Returns human-readable mismatches (empty = pass)."""

    metrics, problems = report["metrics"], []
    if "outcomes" in expect and metrics["outcomes"] != expect["outcomes"]:
        problems.append(f"outcomes {metrics['outcomes']} != {expect['outcomes']}")
    for key in ("proposed", "would_apply", "rejected", "executed", "replans", "active_board"):
        if key in expect and metrics[key] != expect[key]:
            problems.append(f"{key} {metrics[key]!r} != {expect[key]!r}")
    for status, count in (expect.get("queue") or {}).items():
        if metrics["queue"].get(status, 0) != count:
            problems.append(f"queue[{status}] {metrics['queue'].get(status, 0)} != {count}")
    for code in expect.get("rejected_codes", []):
        if code not in metrics["rejected_codes"]:
            problems.append(f"rejected code {code!r} missing in {metrics['rejected_codes']}")
    problems.extend(metrics["timing_mismatches"])
    if "hidden" in expect and metrics["hidden"] != sorted(expect["hidden"]):
        problems.append(f"hidden {metrics['hidden']} != {sorted(expect['hidden'])}")
    for object_id, x in (expect.get("final_x") or {}).items():
        if metrics["final_x"].get(object_id) != x:
            problems.append(f"x[{object_id}] {metrics['final_x'].get(object_id)!r} != {x!r}")
    return problems


# ------------------------------------------------------------------ run


def scripted_factory(scenario: Mapping[str, Any]) -> Any:
    spec = scenario.get("decider") or {}
    if spec.get("kind") == "rule":
        return RuleToolBrainDecider()
    if spec.get("kind") == "absent":
        return None
    return ScriptedDecider(list(spec.get("replies") or [{}]))


async def run_scenario(scenario: Mapping[str, Any], catalog: Mapping[str, Any],
                       decider_factory: Callable[[Mapping[str, Any]], Any] = scripted_factory, *,
                       decision_timeout_s: float = 30.0, live: bool = False) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="tb-replay-") as tmp:
        rig = await build_rig(scenario, Path(tmp), catalog, decider_factory, decision_timeout_s=decision_timeout_s)
        rig.live = live
        try:
            started = time.perf_counter()
            for step in scenario["steps"]:
                await run_step(rig, step)
            report = await score(rig)
            report["wall_ms"] = round((time.perf_counter() - started) * 1000, 1)
            report["mode"] = "live" if live else (scenario.get("decider") or {}).get("kind", "scripted")
            if not live:
                report["expectation_mismatches"] = check_expectations(report, scenario.get("expect") or {})
            else:
                report["expectation_mismatches"] = check_live(report, scenario.get("live_expect") or {})
            return report
        finally:
            await close_rig(rig)


def check_live(report: Mapping[str, Any], expect: Mapping[str, Any]) -> list[str]:
    """Live mode: soft expectations (a model is not byte-deterministic): bounds, never exact plans."""

    metrics, problems = report["metrics"], []
    if "max_rejected" in expect and metrics["rejected"] > expect["max_rejected"]:
        problems.append(f"rejected {metrics['rejected']} > {expect['max_rejected']}")
    if "min_completed" in expect and metrics["outcomes"].count("completed") < expect["min_completed"]:
        problems.append(f"completed decisions {metrics['outcomes'].count('completed')} < {expect['min_completed']}")
    if "max_executed" in expect and metrics["executed"] > expect["max_executed"]:
        problems.append(f"executed {metrics['executed']} > {expect['max_executed']}")
    if "hidden" in expect and metrics["hidden"] != sorted(expect["hidden"]):
        problems.append(f"hidden at the end {metrics['hidden']} != {sorted(expect['hidden'])}")
    problems.extend(f"timing: {item}" for item in metrics["timing_mismatches"])
    return problems


async def run_all(scenarios: list[dict[str, Any]], decider_factory=scripted_factory, **kwargs) -> list[dict[str, Any]]:
    catalog = await build_catalog()
    return [await run_scenario(item, catalog, decider_factory, **kwargs) for item in scenarios]


def summarize(reports: list[Mapping[str, Any]]) -> dict[str, Any]:
    failed = [r["scenario"] for r in reports if r["violations"] or r["expectation_mismatches"]]
    return {"scenarios": len(reports), "failed": failed, "invariant_violations": sum(len(r["violations"]) for r in reports),
            "mismatches": sum(len(r["expectation_mismatches"]) for r in reports),
            "executed": sum(r["metrics"]["executed"] for r in reports),
            "proposed": sum(r["metrics"]["proposed"] for r in reports),
            "rejected": sum(r["metrics"]["rejected"] for r in reports)}


# ------------------------------------------------------------------ live


def live_decider_factory(model_holder: list[RecordingModel], *, runtime_root: Path, max_calls: int):
    """`ModelToolBrainDecider` on the production CLI provider (tool-less, no MCP, no session), calls recorded."""

    import os

    from jarvis.runtime.tool_brain_decider import ModelToolBrainDecider, tool_brain_decider_provider

    provider = tool_brain_decider_provider(lambda: {}, cwd=REPO, runtime_root=runtime_root, environ=os.environ)

    def factory(scenario: Mapping[str, Any]) -> Any:
        real = provider()
        if real is None:
            raise RuntimeError("no native Claude CLI available for the live decider")
        recording = RecordingModel(real._model, max_calls=max_calls - sum(len(m.calls) for m in model_holder))  # noqa: SLF001
        model_holder.append(recording)
        return ModelToolBrainDecider(recording)

    return factory


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def call_stats(calls: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Latency, size, token and cost distribution of recorded model calls (the performance baseline, contract 18.4)."""

    done = [c for c in calls if "reply" in c]
    wall = [float(c["wall_ms"]) for c in done]
    cli = [float(c["cli_duration_ms"]) for c in done if c.get("cli_duration_ms") is not None]
    cost = [float(c["cost_usd"]) for c in done if c.get("cost_usd") is not None]
    usage = [c.get("usage") or {} for c in done]
    return {
        "calls": len(calls), "answered": len(done), "errors": len(calls) - len(done),
        "wall_ms": {"p50": _percentile(wall, 0.5), "p95": _percentile(wall, 0.95), "max": max(wall, default=None)},
        "cli_ms": {"p50": _percentile(cli, 0.5), "p95": _percentile(cli, 0.95)},
        "prompt_bytes": {"min": min((c["prompt_bytes"] for c in calls), default=None),
                         "max": max((c["prompt_bytes"] for c in calls), default=None)},
        "reply_bytes_p50": _percentile([float(c["reply_bytes"]) for c in done], 0.5),
        "cache_creation_tokens_p50": _percentile([float(u.get("cache_creation_input_tokens", 0)) for u in usage], 0.5),
        "cache_read_tokens_max": max((u.get("cache_read_input_tokens", 0) for u in usage), default=0),
        "output_tokens_p50": _percentile([float(u.get("output_tokens", 0)) for u in usage], 0.5),
        "thinking_tokens_max": max((u.get("thinking_tokens", 0) for u in usage), default=0),
        "cost_usd": {"total": round(sum(cost), 4), "per_call_p50": _percentile(cost, 0.5)}}


async def bench(iterations: int = 30) -> dict[str, Any]:
    """Local (non-model) latency baseline: every stage between a trigger and a UI mutation, wall clock, this machine.

    The decider is instantaneous here on purpose: what is measured is the Tool Brain's own overhead, the model call is
    measured separately by `--live` (`call_stats`). Contract 18.4.
    """

    from jarvis.runtime.tool_brain_choices import build_manifest, read_ui_state, scope_tools, validate_call
    from jarvis.runtime.tool_brain_executor import executable_tools
    from jarvis.runtime.tool_brain_perception import build_perception

    catalog = await build_catalog()
    objects = [{"id": f"brain-note-{i:02d}", "title": f"Note {i}", "x": i * 12, "y": 0, "hidden": i % 2 == 0}
               for i in range(12)]
    reply = {"actions": [{"server": DISPLAY, "tool": "scene_update_object", "reason": "bench",
                          "arguments": {"object_id": "brain-note-00", "visibility": "visible"}}]}
    scenario = {"id": "bench", "scene": {"objects": objects}, "steps": [],
                "decider": {"kind": "scripted", "replies": [reply]}}
    samples: dict[str, list[float]] = {}

    def keep(name: str, started: float) -> None:
        samples.setdefault(name, []).append((time.perf_counter() - started) * 1000)

    with tempfile.TemporaryDirectory(prefix="tb-bench-") as tmp:
        rig = await build_rig(scenario, Path(tmp), catalog, scripted_factory)
        sizes: dict[str, int] = {}
        try:
            for index in range(iterations):
                started = time.perf_counter()
                state = await read_ui_state(rig.scene, rig.boards)
                keep("read_ui_state", started)
                started = time.perf_counter()
                perception = build_perception(state)
                keep("build_perception", started)
                started = time.perf_counter()
                full = build_manifest(catalog, state)
                keep("build_manifest_full", started)
                started = time.perf_counter()
                names = scope_tools(full, executable=lambda server, tool: (server, tool) in executable_tools(),
                                    wake_classes=["user_turn"])
                scoped = build_manifest(catalog, state, include_tools=names)
                keep("scope_and_build_manifest", started)
                started = time.perf_counter()
                validate_call(DISPLAY, "scene_update_object", {"object_id": "brain-note-00", "visibility": "visible"}, state)
                keep("validate_call", started)
                sizes = {"perception_bytes": perception.size_bytes,
                         "manifest_full_bytes": len(json.dumps(full, separators=(",", ":"), ensure_ascii=False).encode()),
                         "manifest_scoped_bytes": len(json.dumps(scoped, separators=(",", ":"), ensure_ascii=False).encode()),
                         "manifest_scoped_tools": len(names), "manifest_full_tools": len(full["tools"])}
                # trigger -> decision recorded and action queued (instant decider); the target toggles so each commit is real
                rig.decider._replies = [{"actions": [{"server": DISPLAY, "tool": "scene_update_object", "reason": "bench",  # noqa: SLF001
                                                      "arguments": {"object_id": "brain-note-00",
                                                                    "visibility": "visible" if index % 2 else "hidden"}}]}]
                rig.runtime.wake(WakeClass.USER_TURN, "bench", conversation_id="conv-1", correlation_id=f"c{index}")
                started = time.perf_counter()
                await _settle_decision(rig)
                keep("trigger_to_queued(step, instant decider)", started)
                # queued -> executed by the owner (SQLite commit included)
                started = time.perf_counter()
                await rig.runtime.pump()
                keep("queued_to_executed(pump)", started)
                rig.clock.advance(2.0)
            # invalidation -> replan decision: the target disappears under a queued action (10 distinct objects)
            for index in range(1, 11):
                target = f"brain-note-{index:02d}"
                rig.decider._replies = [{"actions": [{"server": DISPLAY, "tool": "scene_update_object", "reason": "bench",
                                                      "arguments": {"object_id": target, "visibility": "visible"}}]}]  # noqa: SLF001
                rig.runtime.wake(WakeClass.USER_TURN, "bench", conversation_id="conv-1", correlation_id=f"d{index}")
                await _settle_decision(rig)
                await rig._service.apply(SceneCommand(op=SceneOp.ARCHIVE_SELECTION, actor=SceneActor.USER,  # noqa: SLF001
                                                      selection=SceneSelection(ids=(target,))))
                started = time.perf_counter()
                await rig.runtime.pump()  # claims, revalidates, invalidates, wakes the runtime
                await _settle_decision(rig)  # the replan decision starts at once (urgent wake)
                keep("invalidation_to_replan_decision(pump+step)", started)
                rig.clock.advance(2.0)
        finally:
            await close_rig(rig)
    table = {name: {"p50_ms": round(_percentile(v, 0.5), 2), "p95_ms": round(_percentile(v, 0.95), 2),
                    "max_ms": round(max(v), 2)} for name, v in samples.items()}
    return {"iterations": iterations, "scene_objects": 12, **sizes, "stages": table}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tool_brain_replay", description=__doc__.split("\n\n")[0])
    parser.add_argument("--scenario", action="append", help="scenario id (repeatable); default all")
    parser.add_argument("--decider", choices=("scripted", "rule"), default="scripted")
    parser.add_argument("--live", action="store_true", help="real ModelToolBrainDecider (paid, needs the native claude CLI)")
    parser.add_argument("--max-calls", type=int, default=12, help="live model call budget")
    parser.add_argument("--out", type=Path, help="write the JSON report (and, live, the prompts/answers) here")
    parser.add_argument("--bench", action="store_true", help="local (non-model) latency baseline, then exit")
    parser.add_argument("--fixtures", type=Path, default=FIXTURES)
    args = parser.parse_args(argv)
    if args.bench:
        result = asyncio.run(bench())
        print(json.dumps(result, indent=1))
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / "bench.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
        return 0
    scenarios = load_scenarios(args.fixtures, set(args.scenario or []))
    if not scenarios:
        print("no scenario matches", file=sys.stderr)
        return 2
    calls: list[RecordingModel] = []
    if args.live:
        with tempfile.TemporaryDirectory(prefix="tb-live-runtime-") as runtime_root:
            scenarios = [item for item in scenarios if (item.get("decider") or {}).get("live", True)]
            factory = live_decider_factory(calls, runtime_root=Path(runtime_root), max_calls=args.max_calls)
            reports = asyncio.run(run_all(scenarios, factory, decision_timeout_s=90.0, live=True))
    else:
        factory = (lambda s: RuleToolBrainDecider()) if args.decider == "rule" else scripted_factory
        reports = asyncio.run(run_all(scenarios, factory))
    summary = summarize(reports)
    for report in reports:
        flag = "FAIL" if report["violations"] or report["expectation_mismatches"] else "ok"
        metrics = report["metrics"]
        print(f"{flag:4} {report['scenario']:28} decisions={metrics['outcomes']} proposed={metrics['proposed']} "
              f"rejected={metrics['rejected']} executed={metrics['executed']} queue={metrics['queue']}"
              + "".join(f"\n       ! {item}" for item in report["violations"] + report["expectation_mismatches"]))
    print(json.dumps(summary))
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "report.json").write_text(json.dumps({"summary": summary, "reports": reports}, indent=1,
                                                         ensure_ascii=False), encoding="utf-8")
        if calls:
            flat = [entry for model in calls for entry in model.calls]
            (args.out / "model-calls.json").write_text(json.dumps([c.calls for c in calls], indent=1,
                                                                  ensure_ascii=False), encoding="utf-8")
            (args.out / "performance.json").write_text(json.dumps(call_stats(flat), indent=1), encoding="utf-8")
            print(json.dumps(call_stats(flat)))
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())

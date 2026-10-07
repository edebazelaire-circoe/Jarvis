#!/usr/bin/env python3
"""Real-session validation of the Tool Brain in an ISOLATED Core (handoff jarvis-tool-brain-ui-orchestrator, Slice 10).

Contract: `docs/tool-brain-contracts.md` section 18.5. Run (from the repo root):

    .venv/Scripts/python.exe scripts/tool_brain_live_session.py --out <evidence dir>
    .venv/Scripts/python.exe scripts/tool_brain_live_session.py --decider model --scenario active --out <dir>   # paid

What is real: `JarvisCoreApplication` on a temp data root (SQLite scene, conversation event log, Boards), the HTTP
`LocalProtocolServer` on an ephemeral loopback port, `LocalCoreClient` (scene commands, `ui_intent_publish` route,
conversation events), `build_tool_brain` exactly as `jarvis/app.py` calls it, the ownership arbiter and its file, the runtime
loop with the real clock. What is stubbed: the main brain turn (a backend that only holds a turn in flight) and, unless
`--decider model`, the decision model (a stub that honours valid `reveal` intents with `scene_update_object`).

Safety: NEVER touches the Human's live Jarvis. The ports 17653/17654 are refused outright, the data and runtime roots are
fresh temp directories, the decider is the only paid thing and only with `--decider model`.

Scenarios: `shadow` (decides, executes nothing, Jarvis keeps the screen), `active` (executes a reversible op through the
owner, takes ownership, then the decider is killed -> `jarvis_direct` fallback and queue flushed), and `timeline` (renders the
real recorded events in headless Chrome over CDP and measures the Tool Brain lane).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FORBIDDEN_PORTS = {17653, 17654}
A = "brain-note-a"
B = "brain-note-b"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    if port in FORBIDDEN_PORTS:  # pragma: no cover - ephemeral ports never land there, but never trust
        raise SystemExit("refusing to use a port of the live Jarvis")
    return port


class StubDecider:
    """Honours every valid `reveal` intent with a reversible `scene_update_object`; counts its calls; can be killed."""

    name = "stub"

    def __init__(self) -> None:
        self.calls = 0
        self.killed = False

    async def decide(self, request, *, timeout_s):
        from jarvis.ports.tool_brain import DeciderError, ProposedAction, ToolBrainReply

        self.calls += 1
        if self.killed:
            raise DeciderError("tool_brain_decider_failed", "stub decider killed by the validation")
        actions = []
        for item in request.intents:
            if item.get("ref_refusals") or item.get("kind") != "reveal":
                continue
            for ref in item.get("refs", []):
                if ref.get("kind") == "object":
                    actions.append(ProposedAction("jarvis-display", "scene_update_object",
                                                  {"object_id": ref["id"], "visibility": "visible"},
                                                  "reveal what Jarvis names", item.get("intent_id")))
        return ToolBrainReply(actions=tuple(actions[:6]), rationale="stub: honour valid reveal intents", model="stub")


async def wait_until(predicate, *, timeout_s: float, what: str, step_s: float = 0.1):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        value = predicate()
        if asyncio.iscoroutine(value):
            value = await value
        if value:
            return value
        await asyncio.sleep(step_s)
    raise TimeoutError(f"timed out after {timeout_s}s waiting for {what}")


async def session(mode: str, decider_kind: str, *, kill_decider: str | None, out: Path, label: str | None = None) -> dict[str, Any]:
    from tests.unit.test_v2_brain_orchestrator import SlowBackend, wait_idle

    from jarvis.core.v2_app import JarvisCoreApplication
    from jarvis.domain.conversation_events import encode_conversation_event
    from jarvis.domain.scene import (
        SceneActor, SceneCommand, SceneGeometry, SceneObjectFields, SceneObjectKind, SceneOp, ScenePayload, Visibility,
    )
    from jarvis.domain.v2 import BrainTurnInput
    from jarvis.protocol.client import LocalCoreClient
    from jarvis.protocol.server import LocalProtocolServer
    from jarvis.runtime import tool_brain_wiring
    from jarvis.runtime.journal import RuntimeJournal
    from jarvis.runtime.tool_brain_ownership import read_ownership
    from jarvis.runtime.tool_brain_runtime import WakeClass

    root = Path(tempfile.mkdtemp(prefix=f"tb-session-{mode}-"))
    data_root, runtime_root = root / "data", root / "runtime"
    runtime_root.mkdir(parents=True)
    port = free_port()
    token = "s" * 32
    stub = StubDecider()
    original = tool_brain_wiring.tool_brain_decider_provider
    holder: dict[str, Any] = {}
    if decider_kind == "stub":
        tool_brain_wiring.tool_brain_decider_provider = lambda *a, **k: (lambda: None if holder.get("absent") else stub)
    env = {"JARVIS_TOOL_BRAIN": mode, "JARVIS_TOOL_BRAIN_TICK_S": "5"}
    label = label or mode
    report: dict[str, Any] = {"mode": mode, "decider": decider_kind, "port": port, "kill": kill_decider, "steps": []}

    def step(name: str, **data: Any) -> None:
        report["steps"].append({"t": round(time.monotonic() - started, 2), "step": name, **data})
        print(f"[{mode}] +{report['steps'][-1]['t']:>6}s {name} {json.dumps(data, default=str)[:300]}")

    started = time.monotonic()
    decision_budget_s = 90 if decider_kind == "model" else 20
    core = JarvisCoreApplication(data_root=data_root, diagnostics=RuntimeJournal(runtime_root))
    await core.start()
    backend = SlowBackend()
    core.brain._backend = backend
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=token)
    await server.start()
    built = tool_brain_wiring.build_tool_brain(core, control_settings=lambda: {}, cwd=ROOT, runtime_root=runtime_root,
                                               diagnostics=RuntimeJournal(runtime_root), environ=env)
    client = LocalCoreClient(host="127.0.0.1", port=port, token=token)
    try:
        assert built is not None, "JARVIS_TOOL_BRAIN did not build a Tool Brain"
        runtime, sources = built
        runtime.start()
        sources.start()
        step("core_up", port=port, data_root_is_temp=True, mode=runtime.mode.value)

        for object_id, x in ((A, 0), (B, 100)):  # two hidden notes, seeded through the real HTTP route
            command = SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=SceneActor.BRAIN, object_id=object_id,
                                   fields=SceneObjectFields(kind=SceneObjectKind.ARTIFACT, category="note",
                                                            payload=ScenePayload(title=f"Note {object_id[-1].upper()}"),
                                                            geometry=SceneGeometry(x, 0, 10, 10),
                                                            visibility=Visibility.HIDDEN))
            answer = await client.scene_command(command.to_payload())
            assert answer.get("outcome") == "applied", answer
        snapshot = await client.scene_snapshot()
        step("scene_seeded", revision=snapshot["revision"], hidden=_hidden(snapshot))

        conversation = await client.create_conversation()
        conversation_id = conversation["id"]
        core.brain._speech_authority = None
        await core.brain.submit(BrainTurnInput(conversation_id=conversation_id, correlation_id="corr-1", text="Montre la note A"))
        await asyncio.wait_for(backend.started.wait(), 10)
        if mode == "active":
            # Realistic order: the Tool Brain owns the screen only after one completed, healthy decision (contract 16). The
            # turn that starts the conversation is that proof; the intent that follows is then the Tool Brain's to act on.
            await wait_until(lambda: (read_ownership(runtime_root).ownership == "tool_brain") or None,
                             timeout_s=decision_budget_s, what="ownership tool_brain after the first decision")
            step("owner_proven", ownership=read_ownership(runtime_root).ownership)
        answer = await client.publish_ui_intent({"kind": "reveal", "refs": [{"kind": "object", "id": A}],
                                                 "timing": "now", "subject": "note A"})
        step("intent_published", accepted=answer.get("accepted"), intent_id=answer.get("intent_id"))

        decision = await wait_until(lambda: next((d for d in runtime.decisions() if d.outcome == "completed" and d.actions), None),
                                    timeout_s=decision_budget_s, what="a completed decision that proposes an action")
        step("decision", outcome=decision.outcome, decider=decision.decider, model=decision.model,
             latency_ms=decision.latency_ms, actions=[(a.action.tool, a.verdict, a.action.trigger, (a.queued or {}).get("outcome")) for a in decision.actions],
             prefetched=[i.get("prefetched") for i in decision.inspections])
        after = await client.scene_snapshot()
        if mode == "shadow":
            await asyncio.sleep(2.0)
            after = await client.scene_snapshot()
            report["shadow_executed_nothing"] = _hidden(after) == _hidden(snapshot) and runtime.status().get("queue") is None
            report["ownership"] = read_ownership(runtime_root).ownership
            step("shadow_checked", hidden=_hidden(after), executed_nothing=report["shadow_executed_nothing"],
                 ownership=report["ownership"], would_apply=[a.verdict for a in decision.actions])
        else:
            try:
                visible = await wait_until(lambda: _visible_async(client, A), timeout_s=30, what="note A visible")
            except TimeoutError:
                views = [(v.record.tool, v.record.trigger.to_dict(), v.status, v.code) for v in runtime._action_queue.views()]  # noqa: SLF001
                step("note_a_never_visible", queue=views, speech=str(runtime._speech() if runtime._speech else None)[:200])  # noqa: SLF001
                raise
            step("reversible_op_executed", note_a_visible=bool(visible), status=runtime.status()["queue"])
            report["executed_reversible_op"] = bool(visible)
            owner = await wait_until(lambda: (read_ownership(runtime_root).ownership == "tool_brain") or None,
                                     timeout_s=25, what="ownership tool_brain")
            view = read_ownership(runtime_root)
            report["ownership_after_first_decision"] = view.ownership
            step("ownership", ownership=view.ownership, reason=view.reason)
            if kill_decider:
                hidden_before_kill = _hidden(await client.scene_snapshot())
                stub.killed = kill_decider == "failing"  # the decider answers with errors ...
                holder["absent"] = kill_decider == "unavailable"  # ... or is gone altogether (no model configured)
                # two failing decisions (backoff 5 s between) -> `decider_failing`, then Jarvis gets the screen back
                for n in (2, 3):
                    await core.brain.submit(BrainTurnInput(conversation_id=conversation_id, correlation_id=f"corr-{n}",
                                                           text=f"Montre encore {n}"))
                    runtime.wake(WakeClass.USER_TURN, f"validation kill {n}", urgent=True, conversation_id=conversation_id, correlation_id=f"corr-{n}")
                    await asyncio.sleep(0.2)
                fell_back = await wait_until(lambda: (read_ownership(runtime_root).ownership == "jarvis_direct") or None,
                                             timeout_s=60, what="fallback to jarvis_direct")
                view = read_ownership(runtime_root)
                report["fallback"] = {"ownership": view.ownership, "reason": view.reason,
                                      "queue_pending": runtime.status()["queue"]["pending"],
                                      "ui_untouched_by_outage": _hidden(await client.scene_snapshot()) == hidden_before_kill}
                step("decider_killed_fallback", ownership=view.ownership, reason=view.reason,
                     pending=runtime.status()["queue"]["pending"], failures=runtime.status()["consecutive_failures"])
        backend.release.set()
        await wait_idle(core.brain)
        await _settle_events(core)
        page = await client.list_conversation_events(conversation_id, limit=500)
        events = [encode_conversation_event(stored.event) for stored in page.events]
        types = [e["event_type"] for e in events]
        tb = [e for e in events if e.get("actor") == "tool_brain"]
        report["events"] = {"total": len(events), "tool_brain": len(tb), "tool_brain_types": sorted({e["event_type"] for e in tb})}
        step("events", **report["events"])
        (out / f"events-{label}.json").write_text(json.dumps(events, indent=1, ensure_ascii=False), encoding="utf-8")
        report["decisions"] = [d.to_dict() for d in runtime.decisions()]
        report["status"] = runtime.status()
        report["journal_tool_brain_lines"] = _journal(runtime_root)
        return report
    finally:
        tool_brain_wiring.tool_brain_decider_provider = original
        try:
            await client.close()
        finally:
            if built is not None:
                await built[1].close()
                await built[0].close()
            await server.stop()
            await core.stop()


def _hidden(snapshot: dict[str, Any]) -> list[str]:
    objects = snapshot["snapshot"]["objects"]
    return sorted(o["object_id"] for o in objects if o.get("visibility") == "hidden")


async def _visible_async(client, object_id: str):
    snapshot = await client.scene_snapshot()
    return True if object_id not in _hidden(snapshot) else None


async def _settle_events(core) -> None:
    from tests.fakes.conversation_events import wait_emitter_settled

    await wait_emitter_settled(core.conversation_event_emitter)


def _journal(runtime_root: Path) -> list[dict[str, Any]]:
    path = runtime_root / "runtime" / "trace.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "tool_brain" in line:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            rows.append({k: row.get(k) for k in ("kind", "level", "message") if k in row} | {"data": row.get("data")})
    return rows[-80:]


def render_timeline(out: Path, events_file: Path) -> dict[str, Any]:
    """Real recorded events in the real served page (headless Chrome over CDP): lanes, bars, accessible names."""

    import pytest

    from tests.unit.test_control_center_timeline_browser import LANES, OPEN, _drive, _page
    from tests.unit.test_interaction_mode_hud_browser import _shots

    events = json.loads(events_file.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="tb-timeline-") as tmp:
        tmp_path = Path(tmp)
        page = _page(tmp_path, events)
        shot, shot_right = out / "timeline-real-session.png", out / "timeline-real-session-scrolled-right.png"
        plan = [{"width": 1440, "height": 900, "actions": [
            *OPEN, {"a": "eval", "expr": LANES},
            {"a": "eval", "expr": """(()=>{const bars=[...document.querySelectorAll('#tlItems .tl-tool_brain.tl-railbar')];
              const dots=[...document.querySelectorAll('#tlItems .tl-tool_brain.tl-dot')];
              return {bars:bars.map(b=>({status:[...b.classList].find(c=>c.startsWith('st-')),label:b.getAttribute('aria-label')})),
                      dots:dots.map(d=>d.getAttribute('aria-label'))}})()"""},
            {"a": "shot", "path": str(shot)},
            {"a": "eval", "expr": "(()=>{const s=document.getElementById('tlScroll');s.scrollLeft=s.scrollWidth;return [s.scrollLeft,s.scrollWidth,s.clientWidth]})()"},
            {"a": "shot", "path": str(shot_right)}]}]
        try:
            seen = _drive(page, plan)[0]["actions"]
        except pytest.skip.Exception as skipped:  # Chrome or node absent: said, never faked
            return {"rendered": False, "reason": str(skipped)}
    lanes, measured = seen[2]["value"], seen[3]["value"]
    return {"rendered": bool(seen[1].get("ok", True)), "lanes_shown": lanes["shown"], "columns": lanes["columns"],
            "counts": lanes["counts"], "tool_brain_bars": measured["bars"], "tool_brain_dots": measured["dots"],
            "screenshots": [shot.name, shot_right.name], "scroll_extent": seen[5].get("value")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--decider", choices=("stub", "model"), default="stub")
    parser.add_argument("--scenario", action="append", choices=("shadow", "active", "timeline"),
                        help="default: all three")
    args = parser.parse_args()
    if os.environ.get("JARVIS_CORE_PORT") in {str(p) for p in FORBIDDEN_PORTS}:
        raise SystemExit("JARVIS_CORE_PORT points at the live Jarvis: refusing")
    args.out.mkdir(parents=True, exist_ok=True)
    wanted = args.scenario or ["shadow", "active", "timeline"]
    result: dict[str, Any] = {}
    if "shadow" in wanted:
        result["shadow"] = asyncio.run(session("shadow", args.decider, kill_decider=None, out=args.out))
    if "active" in wanted:
        result["active"] = asyncio.run(session("active", args.decider, kill_decider="failing" if args.decider == "stub" else None, out=args.out))
        if args.decider == "stub":
            result["active_unavailable"] = asyncio.run(session("active", args.decider, kill_decider="unavailable",
                                                               out=args.out, label="active-unavailable"))
    if "timeline" in wanted and (args.out / "events-active.json").exists():
        result["timeline"] = render_timeline(args.out, args.out / "events-active.json")
        print(json.dumps(result["timeline"], indent=1))
    (args.out / f"session-{args.decider}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str),
                                                            encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

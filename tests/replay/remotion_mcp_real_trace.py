"""Real-model traces of the `jarvis-remotion` tools (jarvis-remotion-presentation-integration, Slice 21). NOT a test: it spends money.

`python -m tests.replay.remotion_mcp_real_trace [scenario ...] [--raw-dir=DIR] [--budget=USD]` runs the real Claude CLI (`claude -p`, stream-json)
with the very prompt program the brain gets (`conversation_display_studio_session`: base + display + presentations + `BRAIN_REMOTION_PROMPT` +
planner), the real `jarvis-display`, `jarvis-presentation` and `jarvis-remotion` MCP servers (stdio children of the CLI), against an ISOLATED
in-process Core (random port, scratch data root, its own token). The live JARVIS is never touched. The CLI has no built-in tool but `ToolSearch`.

What is real and what is scripted (said in the evidence too):
- real: the brain, the prompts, the three MCP servers, Core's Presentation Studio routes (edits, source requests, engine view), the attestation route's
  contract (`GET /api/presentation-studio/agent/turn`, answered here by a stand-in Control Center whose answer the scenario sets: an addressed user turn
  or a turn Core opened alone);
- scripted: the Remotion CAPABILITY routes of Core (`/v1/local-capabilities/remotion*`, render jobs, imports). The harness test Core has no local
  capability store, so a small stateful front serves those shapes (not installed -> installing; render job queued) and forwards everything else to the
  real Core. The real routes are proven by the Core route tests; what these traces judge is the brain's CHOICES (tool, arguments, order, refusal handling).

Output: `evidence/remotion-real-traces.{json,md}` (redacted like the Slice 21 harness) and the raw stream in `--raw-dir` (never committed).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

import json as _json
import subprocess

import aiohttp
from aiohttp import web

from jarvis.domain.prompt_registry import PromptTarget
from jarvis.runtime import claude_local, display_mcp, presentation_studio_mcp, remotion_mcp
from jarvis.runtime.presentation_studio_mcp_support import PresentationMcpTarget
from jarvis.runtime.prompt_runtime import prompt_channel, resolve_prompt
from jarvis.runtime.settings_mcp import ConsoleMcpTarget
from tests.replay.presentation_studio_mcp_real_trace import MODEL, summarize
from tests.replay.presentation_studio_mcp_rig import ID_PATTERN
from tests.unit.test_presentation_studio_playback_routes import presentation_with_score
from tests.unit.test_presentation_studio_routes import TOKEN, Core

EVIDENCE = (Path(__file__).resolve().parents[2] / "tasks" / "jarvis-remotion-presentation-integration" / "slices"
            / "21-voice-tools-and-toolbrain" / "evidence")
JOB = "rj_0a1b2c3d4e5f"


def run_cli(text: str, *, session: str | None, configs: list[Path], prompt: str, cwd: Path, env: dict[str, str], budget: float,
            tools: str) -> list[dict[str, Any]]:
    """One `claude -p` turn. `tools` is the built-in tool list (`ToolSearch`, plus `Agent` when the scenario judges a delegation brief)."""

    command = ["claude", "-p", text, "--output-format", "stream-json", "--verbose", "--strict-mcp-config", "--model", MODEL,
               "--tools", tools, "--permission-mode", "bypassPermissions", "--disable-slash-commands",
               "--max-budget-usd", f"{budget:.2f}", "--append-system-prompt", prompt]
    for path in configs:
        command += ["--mcp-config", str(path)]
    if session:
        command += ["--resume", session]
    done = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", timeout=900)
    events = []
    for line in done.stdout.splitlines():
        try:
            events.append(_json.loads(line))
        except ValueError:
            continue
    if not events:
        raise RuntimeError(f"no stream from the CLI: {done.stderr[-500:]}")
    return events


class CapabilityStub:
    """The scripted Remotion capability of Core: just enough state to see what the brain does with it (every request is recorded)."""

    def __init__(self, status: str) -> None:
        self.status = status
        self.seen: list[dict[str, Any]] = []
        self.job_state: str | None = None

    def capability(self) -> dict[str, Any]:
        return {"family": "local_capability", "capability_id": "remotion", "display_name": "Remotion", "status": self.status,
                "install_status": "installed" if self.status in ("ready", "running") else self.status, "process_status": "stopped",
                "health": "ok" if self.status == "ready" else "unknown", "enabled": True, "pinned": {"remotion": "4.0.0"},
                "update_required": False, "last_error_code": None, "last_error_detail": None}

    def job(self) -> dict[str, Any]:
        return {"job_id": JOB, "artifact_id": "jart_demo", "state": self.job_state or "queued", "phase": "queued", "format": "mp4", "percent": 0,
                "frames_done": 0, "frames_total": 90, "elapsed_s": 0.0, "timeout_s": 390, "can_cancel": self.job_state != "cancelled",
                "error_code": None, "queue_position": 0}

    async def handle(self, request: web.Request) -> web.Response | None:
        path, method = request.path, request.method
        if not (path.startswith("/v1/local-capabilities") or path.startswith("/v1/remotion/")):
            return None
        body = await request.json() if request.can_read_body else None
        self.seen.append({"method": method, "path": path, "body_keys": sorted(body) if isinstance(body, dict) else None})
        if path == "/v1/local-capabilities/remotion" and method == "GET":
            return web.json_response({"capability": self.capability()})
        if path == "/v1/local-capabilities/remotion/install" and method == "POST":
            self.status = "installing"
            return web.json_response({"capability": self.capability()}, status=202)
        if path == "/v1/local-capabilities/remotion/studio" and method == "GET":
            return web.json_response({"studio": {"status": "stopped", "work_copy": {"modified_files": []}, "last_error_code": None}})
        if path == "/v1/local-capabilities/remotion/render" and method == "GET":
            return web.json_response({"render": {"ready": self.status == "ready", "reason": None, "browser": "chrome 154"}})
        if path == "/v1/local-capabilities/remotion/render/jobs" and method == "GET":
            return web.json_response({"jobs": [self.job()] if self.job_state else []})
        if path == "/v1/local-capabilities/remotion/render/jobs" and method == "POST":
            self.job_state = "queued"
            return web.json_response({"job": self.job()}, status=202)
        if path.startswith("/v1/local-capabilities/remotion/render/jobs/"):
            if path.endswith("/cancel"):
                self.job_state = "cancelled"
            return web.json_response({"job": self.job()})
        return web.json_response({"error": {"code": "remotion_import_unavailable", "message": "this harness Core has no importer"}}, status=503)


async def front(core_port: int, stub: CapabilityStub) -> tuple[web.AppRunner, int]:
    """The Core the MCP servers see: the capability stub for its routes, the real isolated Core for everything else."""

    session = aiohttp.ClientSession()

    async def handler(request: web.Request) -> web.Response:
        answered = await stub.handle(request)
        if answered is not None:
            return answered
        data = await request.read()
        async with session.request(request.method, f"http://127.0.0.1:{core_port}{request.path_qs}", data=data or None,
                                   headers={k: v for k, v in request.headers.items() if k.lower() in ("authorization", "content-type")}) as upstream:
            return web.Response(body=await upstream.read(), status=upstream.status, content_type=upstream.content_type)

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handler)
    app.on_cleanup.append(lambda _: session.close())
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, site._server.sockets[0].getsockname()[1]  # noqa: SLF001 - the ephemeral port the OS gave us


async def control_center(attested: dict[str, bool]) -> tuple[web.AppRunner, int, list[tuple[str, str]]]:
    """Stand-in Control Center: only the turn attestation matters here (`attested['value']` is what the scenario says the real turn is)."""

    seen: list[tuple[str, str]] = []

    async def reply(request: web.Request) -> web.Response:
        seen.append((request.method, request.path))
        if request.path.endswith("/agent/turn"):
            return web.json_response({"ok": True, "addressed_user_turn": attested["value"]})
        if request.path.endswith("/explorer/state"):
            return web.json_response({"state": "closed"})
        return web.json_response({"state": "closed"})

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", reply)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, site._server.sockets[0].getsockname()[1], seen  # noqa: SLF001


SYSTEM_TURN = ("[Tour ouvert par Core, pas par l'utilisateur] Le travail de fond signale que l'environnement Remotion n'est pas installé sur ce poste "
               "et que la présentation ouverte en a besoin. Décide de la suite.")

SCENARIOS: dict[str, dict[str, Any]] = {
    "install-addressed": {"capability": "not_installed", "attested": True, "turns": ["Installe Remotion."]},
    "install-ambient": {"capability": "not_installed", "attested": False, "turns": [SYSTEM_TURN]},
    # The same words as the addressed install, but the Control Center says the turn is NOT the user's (Core opened it, or it was not addressed):
    # what does the brain do with the typed refusal (retry, route around it, tell the user)?
    "install-unattested": {"capability": "not_installed", "attested": False, "turns": ["Installe Remotion."]},
    "studio-then-export": {"capability": "ready", "attested": True,
                           "turns": ["Ouvre le Studio sur la deuxième scène.", "Exporte ma présentation en MP4."]},
    "slidecar-refusal": {"capability": "ready", "attested": True, "turns": ["Passe cette présentation en Slidecar."]},
    # `Agent` is given to the brain here ONLY to read the delegation brief it writes for the source edit (the sub-agent itself has no Core route in this rig).
    "source-delegation": {"capability": "ready", "attested": True, "tools": "ToolSearch,Agent",
                          "turns": ["Refais la deuxième scène avec un autre style, plus sobre."]},
    "props-then-source": {"capability": "ready", "attested": True,
                          "turns": ["Mets le texte de la deuxième scène à « Bientôt ».",
                                    "Change la couleur du titre de la deuxième scène.",
                                    "Refais la deuxième scène avec un autre style, plus sobre."]},
}


def clean_name(name: str) -> str:
    return (name.replace("mcp__jarvis-remotion__", "remotion:").replace("mcp__jarvis-presentation__", "")
            .replace("mcp__jarvis-display__", "display:"))


async def run_scenario(name: str, spec: dict[str, Any], raw_dir: Path, budget: float) -> dict[str, Any]:
    # Same explicit opt-out as `tests/conftest.py`: the seeded scenes are HTML (`jarvis.window`) in a document the default engine would call `remotion`.
    import jarvis.core.v2_app as v2_app

    v2_app.ENGINE_GATE_DEFAULT = False
    work = Path(tempfile.mkdtemp(prefix=f"s21rem-{name}-"))
    (work / "core").mkdir()
    core = Core(work / "core")
    await core.__aenter__()
    attested = {"value": bool(spec["attested"])}
    cc_runner, cc_port, cc_seen = await control_center(attested)
    stub = CapabilityStub(spec["capability"])
    front_runner, front_port = await front(int(core.stack.core_url.rsplit(":", 1)[1]), stub)
    try:
        pid, vid = await presentation_with_score(core)
        runtime = work / "runtime"
        runtime.mkdir()
        token_file = work / "core.token"
        token_file.write_text(TOKEN, encoding="utf-8")
        display_target = display_mcp.DisplayMcpTarget("127.0.0.1", front_port, token_file, runtime)
        target = PresentationMcpTarget(display_target, ConsoleMcpTarget("127.0.0.1", cc_port, runtime))
        configs = [display_mcp.write_mcp_config(display_target, runtime), presentation_studio_mcp.write_mcp_config(target, runtime),
                   remotion_mcp.write_mcp_config(target, runtime)]
        resolution = resolve_prompt(PromptTarget("backend", None, "claude", None, None, "conversation_display_studio_session"), variables={})
        prompt = prompt_channel(resolution, "cli.append_system_prompt")
        assert claude_local.BRAIN_REMOTION_PROMPT[:30] in prompt, "the Remotion prompt block reaches the model"
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2]), "PYTHONUTF8": "1"}
        aliases: dict[str, str] = {}

        def alias(value: str) -> str:
            if value not in aliases:
                prefix = value.split("_", 1)[0]
                aliases[value] = f"<{prefix}{sum(1 for v in aliases.values() if v.startswith('<' + prefix)) + 1}>"
            return aliases[value]

        turns, session, raw = [], None, []
        for text in spec["turns"]:
            events = await asyncio.get_running_loop().run_in_executor(
                None, lambda t=text, s=session: run_cli(t, session=s, configs=configs, prompt=prompt, cwd=work, env=env, budget=budget,
                                    tools=spec.get("tools", "ToolSearch")))
            raw.append({"user": text, "events": events})
            summary = summarize(events, alias)
            for call in summary["calls"]:
                call["tool"] = clean_name(call["tool"])
            session = summary.get("session_id") or session
            briefs = [ID_PATTERN.sub(lambda m: alias(m.group(0)), str((block.get("input") or {}).get("prompt", "")))[:3000]
                      for event in events if event.get("type") == "assistant"
                      for block in event.get("message", {}).get("content", []) if block.get("type") == "tool_use" and block.get("name") in ("Agent", "Task")]
            turns.append({"user": text, **summary, "delegation_briefs": briefs})
        (raw_dir / f"{name}.raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
        journal = runtime / "trace.jsonl"
        rows = []
        for line in (journal.read_text(encoding="utf-8", errors="replace").splitlines() if journal.exists() else []):
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        server_rows = [{k: (alias(v) if isinstance(v, str) and ID_PATTERN.fullmatch(v) else v) for k, v in {"kind": r.get("kind"), **(r.get("data") or {})}.items()
                        if k in ("kind", "tool", "op", "code", "status", "speech")}
                       for r in rows if str(r.get("kind", "")).startswith(("remotion_mcp.tool", "presentation_studio.tool"))]
        engine = await core.client.presentation_studio_engine() if hasattr(core.client, "presentation_studio_engine") else {}
        listed = (await core.client.presentation_studio_list())["presentations"]
        return {
            "scenario": name, "model": MODEL, "attested_turn": spec["attested"], "capability_at_start": spec["capability"], "turns": turns,
            "server_journal": server_rows,
            "capability_requests": stub.seen, "capability_at_end": stub.status, "render_job_at_end": stub.job_state,
            "attestation_reads": sum(1 for m, p in cc_seen if p.endswith("/agent/turn")),
            "engine_at_end": {"default": engine.get("default_engine"), "presentations": [(p.get("engine")) for p in listed]},
        }
    finally:
        await front_runner.cleanup()
        await cc_runner.cleanup()
        await core.__aexit__(None, None, None)
        shutil.rmtree(work, ignore_errors=True)


def render(result: dict[str, Any]) -> str:
    lines = ["# Remotion agent tools - real-model traces (Slice 21)", "",
             f"Real Claude (`{result['model']}`) through the CLI, the real prompt program (`conversation_display_studio_session`, Remotion block "
             f"{result['remotion_prompt_chars']} chars), the real `jarvis-display` / `jarvis-presentation` / `jarvis-remotion` servers, an isolated Core. "
             "The Remotion capability routes are a SCRIPTED stub (no local capability store in the harness Core); presentations, edits, source requests and "
             "the engine view are the real Core. The turn attestation is answered by a stand-in Control Center per scenario. Redacted: ids are aliases, "
             "arguments' texts are `<text>`; final answers are quoted.", "",
             f"Total cost: ${result['total_cost_usd']:.2f}, {result['total_calls']} tool calls over {len(result['scenarios'])} scenarios.", ""]
    for s in result["scenarios"]:
        lines += [f"## {s['scenario']} (attested user turn: {s['attested_turn']}, capability at start: {s['capability_at_start']})", ""]
        for turn in s["turns"]:
            lines += [f"User: \"{turn['user'][:200]}\" - {turn.get('turns')} model turns, {turn.get('duration_ms')} ms, ${(turn.get('cost_usd') or 0):.3f}", "",
                      "| # | tool | arguments | result |", "| --- | --- | --- | --- |"]
            for c in turn["calls"]:
                outcome = c.get("code") or c.get("status") or ("error" if c.get("is_error") else "ok")
                lines.append(f"| {c['n']} | {c['tool']} | `{json.dumps(c['arguments'], ensure_ascii=False)[:200]}` | {outcome} / {c.get('speech')} |")
            for brief in turn.get("delegation_briefs") or []:
                lines += ["", "Delegation brief written by the brain (ids aliased):", "", "> " + brief.replace(chr(10), chr(10) + "> ")]
            lines += ["", f"Final answer ({turn['final_answer_chars']} chars): {turn['final_answer']}", ""]
        lines += [f"Capability requests seen by the stub: {s['capability_requests']}", "",
                  f"Capability at end: {s['capability_at_end']}; render job: {s['render_job_at_end']}; attestation reads: {s['attestation_reads']}; "
                  f"engines at end: {s['engine_at_end']}", ""]
    return "\n".join(lines) + "\n"


async def main_async(names: list[str], raw_dir: Path, budget: float) -> int:
    raw_dir.mkdir(parents=True, exist_ok=True)
    scenarios = []
    for name in names or list(SCENARIOS):
        print("running", name, flush=True)
        scenarios.append(await run_scenario(name, SCENARIOS[name], raw_dir, budget))
        print("  done", name, flush=True)
    total = sum((t.get("cost_usd") or 0) for s in scenarios for t in s["turns"])
    result = {"kind": "remotion real-model traces", "slice": 21, "model": MODEL, "scenarios": scenarios, "total_cost_usd": round(total, 4),
              "total_calls": sum(len(t["calls"]) for s in scenarios for t in s["turns"]),
              "prompt_program": "conversation_display_studio_session", "remotion_prompt_chars": len(claude_local.BRAIN_REMOTION_PROMPT)}
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    suffix = "" if not names else "." + "+".join(names)
    (EVIDENCE / f"remotion-real-traces{suffix}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    (EVIDENCE / f"remotion-real-traces{suffix}.md").write_text(render(result), encoding="utf-8")
    print(f"wrote traces, cost ${total:.2f}")
    return 0


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    raw = Path(next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--raw-dir=")), tempfile.gettempdir())) / "s21-remotion-raw"
    budget = float(next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--budget=")), "1.00"))
    return asyncio.run(main_async(args, raw, budget))


if __name__ == "__main__":
    sys.exit(main())

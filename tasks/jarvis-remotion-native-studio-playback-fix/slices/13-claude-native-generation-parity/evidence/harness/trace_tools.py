"""Read real traces of both sides into one shape: per agent, the ordered tool calls with their outcome, errors, elapsed time, tokens.

- direct side: the `claude -p --output-format stream-json` file of the run (`stream.jsonl`);
- Jarvis side: the Claude CLI session of the brain (`~/.claude/projects/<cwd>/<session>.jsonl`) and its sub-agent side chains
  (`<session>/subagents/agent-*.jsonl`), found from the brain session id the run recorded, plus Jarvis's own `runtime/trace.jsonl`.

`python trace_tools.py summary <run>` prints a compact table; `calls <run>` the call list. Used by `collect_evidence.py`.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

import bench

PROJECTS = Path.home() / ".claude" / "projects"
#: A tool result that is an error, or a Jarvis tool result that is a refusal the author must fix.
REFUSAL_MARKS = ('"status":"refused"', '"status": "refused"', '"status":"refused_validation"', '"ok_gate":false', "Refus ")


def _rows(path: Path) -> list[dict]:
    out = []
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text", "") if isinstance(c, dict) and c.get("type") == "text" else
                        ("[image]" if isinstance(c, dict) and c.get("type") == "image" else "") for c in content)
    return ""


def calls_of(rows: list[dict]) -> list[dict]:
    """Ordered tool calls with their results (matched by tool_use_id), timestamps when the rows carry them."""

    pending: dict[str, dict] = {}
    ordered: list[dict] = []
    for row in rows:
        message = row.get("message") or {}
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        if row.get("type") == "assistant":
            for c in content:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    call = {"id": c.get("id"), "name": c.get("name"), "input": c.get("input"), "ts": row.get("timestamp"),
                            "parent": row.get("parent_tool_use_id")}
                    pending[c.get("id")] = call
                    ordered.append(call)
        elif row.get("type") == "user":
            for c in content:
                if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in pending:
                    text = _text(c.get("content"))
                    call = pending[c["tool_use_id"]]
                    call["error"] = bool(c.get("is_error"))
                    call["refused"] = call["error"] or any(mark in text[:600] for mark in REFUSAL_MARKS)
                    call["result_head"] = text[:400]
                    call["result_ts"] = row.get("timestamp")
    return ordered


def usage_of(rows: list[dict]) -> dict[str, int]:
    total = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    seen = set()
    for row in rows:
        message = row.get("message") or {}
        if row.get("type") != "assistant" or not isinstance(message, dict):
            continue
        key = message.get("id")
        if key in seen:
            continue
        seen.add(key)
        for name in total:
            total[name] += int((message.get("usage") or {}).get(name) or 0)
    return total


def jarvis_sources(run: str) -> dict[str, Path]:
    m = bench.meta(run)
    session = m.get("brain_session_id")
    if not session:
        raise SystemExit(f"{run}: no brain_session_id (run jarvis-collect first)")
    folder = next((p for p in PROJECTS.iterdir() if (p / f"{session}.jsonl").exists()), None)
    if folder is None:
        raise SystemExit(f"{run}: session {session} not found under {PROJECTS}")
    found = {"brain": folder / f"{session}.jsonl"}
    for side in sorted((folder / session / "subagents").glob("agent-*.jsonl")):
        found[side.stem] = side
    return found


def summary(run: str) -> dict[str, Any]:
    m = bench.meta(run)
    agents: dict[str, Any] = {}
    if m.get("side") == "direct":
        rows = bench.stream_events(run)
        result = next((r for r in reversed(rows) if r.get("type") == "result"), {})
        calls = calls_of(rows)
        agents["direct"] = {"calls": calls, "usage": usage_of(rows)}
        totals = {"cost_usd": result.get("total_cost_usd"), "duration_ms": result.get("duration_ms"), "num_turns": result.get("num_turns")}
    else:
        for name, path in jarvis_sources(run).items():
            rows = _rows(path)
            meta_file = path.with_suffix(".meta.json")
            description = json.loads(meta_file.read_text(encoding="utf-8")).get("description") if meta_file.exists() else "brain"
            agents[name] = {"description": description, "calls": calls_of(rows), "usage": usage_of(rows),
                            "first_ts": next((r.get("timestamp") for r in rows if r.get("timestamp")), None),
                            "last_ts": next((r.get("timestamp") for r in reversed(rows) if r.get("timestamp")), None)}
        trace = bench.run_dir(run) / "runtime" / "trace.jsonl"
        costs = [r["data"]["total_cost_usd"] for r in _rows(trace)
                 if r.get("kind") == "agent.event" and isinstance(r.get("data"), dict) and r["data"].get("total_cost_usd") is not None]
        totals = {"cost_usd_last_brain_result": costs[-1] if costs else None, "brain_results": len(costs)}
    return {"run": run, "side": m.get("side"), "topic": m.get("topic") or (m.get("turns") or [{}])[0].get("topic"), "totals": totals,
            "agents": agents}


def table(data: dict[str, Any]) -> str:
    lines = [f"run {data['run']} ({data['side']}, {data['topic']}): {json.dumps(data['totals'])}"]
    for name, agent in data["agents"].items():
        calls = agent["calls"]
        names: dict[str, int] = {}
        for call in calls:
            names[call["name"]] = names.get(call["name"], 0) + 1
        refused = [c for c in calls if c.get("refused")]
        lines.append(f"  {name} [{agent.get('description', '')}] calls={len(calls)} refused/errors={len(refused)} usage={agent['usage']}")
        lines.append(f"    by tool: {names}")
        for c in refused:
            lines.append(f"    ! {c['name']}: {c.get('result_head', '')[:220]!r}")
    return "\n".join(lines)


if __name__ == "__main__":
    command, run = sys.argv[1], sys.argv[2]
    data = summary(run)
    if command == "summary":
        print(table(data))
    elif command == "calls":
        for agent, body in data["agents"].items():
            for call in body["calls"]:
                print(agent, call["name"], json.dumps(call["input"], ensure_ascii=False)[:160], "REFUSED" if call.get("refused") else "")

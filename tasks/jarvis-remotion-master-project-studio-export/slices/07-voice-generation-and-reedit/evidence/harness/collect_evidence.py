"""Copy the Slice 07 real-trace run into the committed evidence folder, redacted (adapted from native-studio-playback-fix Slice 13's
`collect_evidence.py`, same redaction rules).

`python collect_evidence.py <run>` (BENCH_ROOT set) writes `evidence/runs/<run>/`:
- `cli/brain.jsonl` and `cli/agent-*.jsonl`: the brain's Claude CLI session and each sub-agent's side chain. Image bytes become
  `[image omitted]`, `<system-reminder>` blocks `[system reminder omitted]`, the CLI `init` events keep only model, permission mode,
  version, tool and MCP server NAMES (no skills, plugins, agents, memory paths); attachment / file-history rows are dropped;
- `jarvis-trace.jsonl`: Jarvis's own runtime journal without its polling rows;
- `out/`: the two whole-video MP4 probes (`export1.probe.json`, `export2.probe.json`, ffprobe streams + the derivative's `render_*`
  metadata), frames of both exports at the same seconds (480 px JPEG), `frame-diff.json`; the MP4 files themselves stay out (size);
- `metrics.json`: per agent, tool calls by tool, refusals with their words, elapsed time, tokens; the turns with the brain's answers.

Redaction targets (home folder, scratch roots, user names) are derived at runtime, never written here.
"""
from __future__ import annotations

import getpass
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

import bench
import trace_tools

EVIDENCE = bench.HERE.parent
#: Any run of backslashes (raw, JSON-escaped, or double-escaped JSON nested in a JSON string) or a slash.
SEP = r"(?:\\+|/)"
NOISY_KINDS = {"core.presentation_studio.listed", "presentation_studio.request.relayed", "agent.event"}
INIT_KEEP = ("type", "subtype", "model", "permissionMode", "claude_code_version", "tools", "mcp_servers")


def _names() -> list[str]:
    names = {os.environ.get("USERNAME", ""), os.environ.get("USER", ""), Path.home().name}
    try:
        names.add(getpass.getuser())
    except (KeyError, OSError):
        pass
    return sorted(n for n in names if len(n) >= 3)


def _rules() -> list[tuple[re.Pattern[str], str]]:
    home = Path.home()
    drive = home.drive.rstrip(":")
    # The last part may already read `<user>` (a file redacted by an older rule set): redacting twice gives the same text.
    parts = [re.escape(p) for p in home.parts[1:-1]] + [rf"(?:{re.escape(home.name)}|<user>)"]
    home_re = rf"(?:{re.escape(drive)}:|/{re.escape(drive.lower())})" + "".join(SEP + p for p in parts)
    # The user's temp folder under home, read from the OS (never spelled out here); outside home it is redacted on its own.
    system_temp = Path(tempfile.gettempdir())
    try:
        temp = home_re + "".join(SEP + re.escape(p) for p in system_temp.relative_to(home).parts)
    except ValueError:
        temp = SEP.join(re.escape(p.rstrip("\\/")) for p in system_temp.parts)
    bench_root = temp + SEP + re.escape(bench.root().name)
    rules = [(re.compile(bench_root, re.I), "<bench>"), (re.compile(temp, re.I), "<temp>"), (re.compile(home_re, re.I), "<home>")]
    rules += [(re.compile(r"(?<![A-Za-z])" + re.escape(n) + r"(?![a-z])", re.I), "<user>") for n in _names()]
    return rules


RULES = _rules()
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)


def redact(text: str) -> str:
    for pattern, repl in RULES:
        text = pattern.sub(repl, text)
    return text


def _clean(value):
    if isinstance(value, dict):
        if value.get("type") == "image":
            return {"type": "image", "source": "[image omitted]"}
        if value.get("type") == "base64" and "data" in value:
            return {**value, "data": "[image omitted]"}
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, str):
        return REMINDER.sub("[system reminder omitted]", value)
    return value


def clean_row(row: dict) -> dict | None:
    if row.get("type") == "system" and row.get("subtype") == "init":
        kept = {k: row.get(k) for k in INIT_KEEP if k in row}
        kept["mcp_servers"] = [s.get("name") if isinstance(s, dict) else s for s in row.get("mcp_servers") or []]
        return kept
    if row.get("type") in ("attachment", "file-history-snapshot", "summary"):
        return None
    return _clean(row)


def write_jsonl(source: Path, target: Path, *, kinds_out: set[str] = frozenset()) -> int:
    rows = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as out:
        for line in source.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("kind") in kinds_out:
                continue
            row = clean_row(row)
            if row is None:
                continue
            out.write(redact(json.dumps(row, ensure_ascii=False)) + "\n")
            rows += 1
    return rows


def _seconds(start: str | None, end: str | None) -> float | None:
    from datetime import datetime
    if not start or not end:
        return None
    parse = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))  # noqa: E731
    return round((parse(end) - parse(start)).total_seconds(), 1)


def metrics(run: str) -> dict:
    data = trace_tools.summary(run)
    m = bench.meta(run)
    out = {"run": run, "model": m.get("model"), "tested_head": m.get("tested_head"), "totals": data["totals"], "agents": {}}
    for name, agent in data["agents"].items():
        calls = agent["calls"]
        by_tool: dict[str, int] = {}
        for call in calls:
            by_tool[call["name"]] = by_tool.get(call["name"], 0) + 1
        out["agents"][name] = {
            "description": agent.get("description"), "tool_calls": len(calls), "by_tool": by_tool,
            "calls": [{"ts": c.get("ts"), "tool": c["name"].split("__")[-1],
                       "input": redact(json.dumps(c.get("input"), ensure_ascii=False))[:240],
                       "result": redact(c.get("result_head", ""))[:240], "refused": bool(c.get("refused"))} for c in calls],
            "refused_or_error": [{"tool": c["name"], "result": redact(c.get("result_head", "")[:300])} for c in calls if c.get("refused")],
            "usage": agent["usage"], "elapsed_s": _seconds(agent.get("first_ts"), agent.get("last_ts"))}
    out["turns"] = [{"text": redact(t["text"])[:240], "brain_answer_s": t.get("elapsed_s"),
                     "answer": redact(json.dumps(t.get("answer"), ensure_ascii=False))[:700]} for t in m.get("turns") or []]
    return out


def collect(run: str) -> dict:
    target = EVIDENCE / "runs" / run
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    root = bench.run_dir(run)
    files: dict[str, int] = {}
    for name, path in trace_tools.jarvis_sources(run).items():
        files[f"cli/{name}.jsonl"] = write_jsonl(path, target / "cli" / f"{name}.jsonl")
    trace = root / "runtime" / "trace.jsonl"
    if trace.exists():
        files["jarvis-trace.jsonl"] = write_jsonl(trace, target / "jarvis-trace.jsonl", kinds_out=NOISY_KINDS)
    out = target / "out"
    out.mkdir()
    for path in sorted((root / "out").iterdir()):
        if path.suffix in (".json", ".jpg"):
            data = path.read_bytes()
            (out / path.name).write_bytes(redact(data.decode("utf-8")).encode("utf-8") if path.suffix == ".json" else data)
    result = metrics(run)
    result["files"] = files
    (target / "metrics.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    return result


def redact_in_place(folder: Path) -> list[str]:
    """Re-applies `redact` to every committed text file under `folder` (after a rule fix); returns the files it changed."""
    changed = []
    for path in sorted(folder.rglob("*")):
        if path.suffix not in (".jsonl", ".json", ".md", ".txt") or not path.is_file():
            continue
        text = path.read_bytes().decode("utf-8")  # bytes: line endings stay as committed
        if (clean := redact(text)) != text:
            path.write_bytes(clean.encode("utf-8"))
            changed.append(str(path.relative_to(folder)))
    return changed


if __name__ == "__main__":
    if sys.argv[1] == "--redact-in-place":
        print(json.dumps(redact_in_place(Path(sys.argv[2])), ensure_ascii=False))
        raise SystemExit(0)
    summary = collect(sys.argv[1])
    print(json.dumps({"totals": summary["totals"], "files": summary["files"]}, ensure_ascii=False))

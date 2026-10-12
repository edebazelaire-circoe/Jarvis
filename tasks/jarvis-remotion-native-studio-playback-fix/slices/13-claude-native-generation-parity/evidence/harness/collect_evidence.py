"""Copy the runs of the benchmark into the committed evidence folder, redacted, with one metrics file per run and the blinded frame sets.

`python collect_evidence.py` (BENCH_ROOT set): for each run of `RUNS`, writes `evidence/runs/<run>/`:
- `metrics.json`: tool calls by tool, refusals and errors (avoidable or environmental, as `CLASSIFY` says), elapsed time, cost, tokens;
- the raw traces: direct `stream.jsonl`; Jarvis the brain's CLI session, each sub-agent's side chain, and Jarvis's `trace.jsonl` without
  its polling rows. Image bytes are replaced by `[image omitted]`, `<system-reminder>` blocks by `[system reminder omitted]`, and the
  CLI `init` events keep only model, permission mode, tool and MCP server NAMES (no skills, plugins, agents, paths);
- `sources/`: the TSX each side produced (direct: the project's `src/`; Jarvis: the scene sources Core serves);
then `evidence/blind/<topic>/deck-A|deck-B/` (frames of the final deck of each side, side hidden; the key is `blind/key.json`).

Redaction targets are derived at runtime (home folder, scratch root, user names), never written here: the same rules as the Remotion
handoff's `privacy_sweep.py`.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess

import bench
import trace_tools

EVIDENCE = bench.HERE.parent
FFMPEG = bench.GATE / "node_modules" / "@remotion" / "compositor-win32-x64-msvc" / "ffmpeg.exe"
#: run -> (side, topic, role in the benchmark)
RUNS = {
    "d-jarvis-1": "direct run 1", "d-jarvis-2": "direct run 2", "d-iguard-1": "direct run 1", "d-iguard-2": "direct run 2",
    "j-base-jarvis": "Jarvis BEFORE (HEAD 40cb68a8, guided chain)",
    "j-native-jarvis": "Jarvis native, run 1 (harness defect: data root path too long for Chrome, previews refused)",
    "jn2": "Jarvis native, run 2 (Core and Control Center killed from outside mid-run)",
    "jn3": "Jarvis native, run 3 (same external kill)",
    "jn4": "Jarvis native, run 4 (final code for this topic) + the two remotion_studio turns",
    "ji1": "Jarvis native, iGuard run 1", "ji2": "Jarvis native, iGuard run 2 (after the key-format and warnings fixes)",
}
#: The final deck of each side per topic, for the blinded review.
BLIND = {"jarvis": {"direct": "d-jarvis-1", "jarvis": "jn4"}, "iguard": {"direct": "d-iguard-1", "jarvis": "ji2"}}
SEP = r"(?:\\\\|\\|/)"
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
    home_re = rf"(?:{re.escape(drive)}:|/{re.escape(drive.lower())})" + "".join(SEP + re.escape(p) for p in home.parts[1:])
    scratch = home_re + SEP + "AppData" + SEP + "Local" + SEP + "Temp" + SEP + r"claude" + SEP + r"[^\\/\"\s]+" + SEP + r"[0-9a-f-]{36}" + SEP + "scratchpad"
    short = home_re + SEP + "AppData" + SEP + "Local" + SEP + "Temp" + SEP + "s13b"
    rules = [(re.compile(scratch, re.I), "<scratch>"), (re.compile(short, re.I), "<bench>"), (re.compile(home_re, re.I), "<home>")]
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
    out = {"run": run, "label": RUNS[run], "side": data["side"], "topic": data["topic"], "totals": data["totals"], "agents": {}}
    for name, agent in data["agents"].items():
        calls = agent["calls"]
        by_tool: dict[str, int] = {}
        for call in calls:
            by_tool[call["name"]] = by_tool.get(call["name"], 0) + 1
        out["agents"][name] = {
            "description": agent.get("description"), "tool_calls": len(calls), "by_tool": by_tool,
            "refused_or_error": [{"tool": c["name"], "result": redact(c.get("result_head", "")[:300])} for c in calls if c.get("refused")],
            "frames_viewed": sum(1 for c in calls if c["name"] == "Read" and str((c.get("input") or {}).get("file_path", "")).lower().endswith((".png", ".jpg", ".jpeg"))),
            "usage": agent["usage"], "elapsed_s": _seconds(agent.get("first_ts"), agent.get("last_ts"))}
    if data["side"] == "jarvis":
        turns = m.get("turns") or []
        out["turns"] = [{"text": redact(t["text"])[:200], "brain_answer_s": t.get("elapsed_s"),
                         "answer": redact(json.dumps(t.get("answer"), ensure_ascii=False))[:600]} for t in turns]
    return out


def collect_run(run: str) -> dict:
    target = EVIDENCE / "runs" / run
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    root = bench.run_dir(run)
    m = bench.meta(run)
    files: dict[str, int] = {}
    if m.get("side") == "direct":
        files["stream.jsonl"] = write_jsonl(root / "stream.jsonl", target / "stream.jsonl")
        for path in sorted((root / "project" / "src").rglob("*")):
            if path.is_file():
                dest = target / "sources" / path.relative_to(root / "project")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(redact(path.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
    else:
        for name, path in trace_tools.jarvis_sources(run).items():
            files[f"{name}.jsonl"] = write_jsonl(path, target / "cli" / f"{name}.jsonl")
        trace = root / "runtime" / "trace.jsonl"
        if trace.exists():
            files["jarvis-trace.jsonl"] = write_jsonl(trace, target / "jarvis-trace.jsonl", kinds_out=NOISY_KINDS)
        collected = root / "collected"
        for path in sorted(collected.rglob("*")) if collected.exists() else []:
            if path.is_file() and path.suffix in (".tsx", ".ts", ".json") and path.name != "agent-tasks.json":
                rel = path.relative_to(collected).parts
                # `<presentation>/<variant>/<scene>/...` shortened to `<deck n>/<scene>/...` (Windows path limit in the repository)
                deck = sorted(p.name for p in collected.iterdir() if p.is_dir()).index(rel[0]) + 1
                dest = target / "sources" / f"deck{deck}" / Path(*rel[2:])
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(redact(path.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
    kept_meta = {k: m.get(k) for k in ("side", "topic", "model", "budget_usd", "pack_sha256", "tested_head", "argv_flags", "decks") if k in m}
    kept_meta["brief"] = redact(m.get("brief") or ((m.get("turns") or [{}])[0].get("text") or ""))
    (target / "meta.json").write_text(redact(json.dumps(kept_meta, indent=1, ensure_ascii=False)), encoding="utf-8")
    result = metrics(run)
    result["files"] = files
    (target / "metrics.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    return result


def blind_sets() -> dict:
    key = {}
    for topic, sides in BLIND.items():
        order = ["direct", "jarvis"]
        random.Random(int(hashlib.sha256(f"slice-13-blind-{topic}".encode()).hexdigest(), 16)).shuffle(order)
        key[topic] = {}
        for letter, side in zip("AB", order):
            run = sides[side]
            source = bench.run_dir(run) / "frames"
            dest = EVIDENCE / "blind" / topic / f"deck-{letter}"
            if dest.exists():
                shutil.rmtree(dest)
            dest.mkdir(parents=True)
            shots = sorted(p for p in source.iterdir() if p.suffix in (".png", ".jpg"))
            for index, shot in enumerate(shots, start=1):
                # One format for both sides (the side must not show in the file type): 960x540 JPEG through the gate runtime's own
                # ffmpeg (no imaging package in the venv), metadata dropped.
                subprocess.run([str(FFMPEG), "-v", "error", "-y", "-i", str(shot), "-vf", "scale=960:540", "-q:v", "3", "-map_metadata", "-1",
                                str(dest / f"{index:02d}.jpg")], check=True, capture_output=True, timeout=60)
            key[topic][f"deck-{letter}"] = {"side": side, "run": run, "frames": len(shots)}
    (EVIDENCE / "blind" / "key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    return key


if __name__ == "__main__":
    summary = {run: collect_run(run) for run in RUNS}
    (EVIDENCE / "runs" / "index.json").write_text(json.dumps(
        {run: {"label": r["label"], "totals": r["totals"],
               "agents": {a: {k: v for k, v in body.items() if k in ("description", "tool_calls", "frames_viewed", "elapsed_s")}
                          | {"refused_or_error": len(body["refused_or_error"])} for a, body in r["agents"].items()}}
         for run, r in summary.items()}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(blind_sets(), indent=1))

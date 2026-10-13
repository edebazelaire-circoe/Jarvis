"""Slice 13 parity benchmark harness: the same brief to an isolated Jarvis and to a direct `claude -p` in a throw-away Remotion project.

Every run lives under BENCH_ROOT/<run> (a scratch folder, never the repository, never the live Jarvis data root). Long agent runs are
started detached and polled in bounded chunks (`wait`), so that no single command of the operator runs for more than a few minutes.

Subcommands (python bench.py <cmd> ...):
  direct-start <run> <topic> [--model M] [--budget USD]   throw-away Remotion project (gate runtime deps only) + detached `claude -p`
  jarvis-up <run> [--model M]                              isolated Core + Control Center (strict MCP) on free ports, fresh data root
  jarvis-ask <run> <topic|--text T> [--timeout S]          one addressed text turn through POST /api/agent/ask
  wait <run> [--max S]                                     poll until the run is idle (direct: result event; jarvis: brain idle, no task)
  status <run>                                             one progress line
  jarvis-down <run>                                        kill the isolated stack (process trees it started, nothing else)

Isolation: `--strict-mcp-config` on both sides; the direct side also runs with `--safe-mode` (no CLAUDE.md, skills, plugins, hooks of
the user's home) and cannot run `npm install`. Real costs are read from the CLI's own `result` events and logged per run.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
BRN = HERE.parents[5]
PY = os.environ.get("BENCH_PYTHON", r"C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe")
GATE = Path(os.environ.get("BENCH_GATE_RUNTIME", r"C:/Projects/jarvis/_remotion-runtime-gate"))
ROOT = Path(os.environ["BENCH_ROOT"]) if os.environ.get("BENCH_ROOT") else None
CHROME = os.environ.get("BENCH_CHROME", r"C:/Program Files/Google/Chrome/Application/chrome.exe")
PACK_SOURCES = {"jarvis": BRN / "README.md", "iguard": Path(r"C:/Projects/IGuard/README.md")}
DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


def root() -> Path:
    if ROOT is None:
        raise SystemExit("set BENCH_ROOT to a scratch folder")
    ROOT.mkdir(parents=True, exist_ok=True)
    return ROOT


def run_dir(run: str) -> Path:
    path = root() / run
    path.mkdir(parents=True, exist_ok=True)
    return path


def meta(run: str, **update: object) -> dict:
    path = run_dir(run) / "meta.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if update:
        data.update(update)
        path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return data


def pack(topic: str) -> Path:
    folder = root() / "packs" / topic
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "README.md"
    if not target.exists():
        shutil.copyfile(PACK_SOURCES[topic], target)
    return folder


def brief(topic: str) -> str:
    spec = json.loads((HERE / "briefs.json").read_text(encoding="utf-8"))
    t = spec["topics"][topic]
    return spec["template"].format(subject=t["subject"], audience=t["audience"], pack=pack(topic).as_posix())


def sha256(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def junction(link: Path, target: Path) -> None:
    if not link.exists():
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)


def shadow_node_modules(project: Path) -> None:
    """A REAL `node_modules` folder whose entries are junctions to the read-only gate runtime: Remotion's bundler writes its webpack cache
    to `node_modules/.cache`, which must land in the throw-away project, never in the gate (a whole-folder junction would write there)."""

    folder = project / "node_modules"
    folder.mkdir(exist_ok=True)
    for entry in (GATE / "node_modules").iterdir():
        if entry.name == ".cache":
            continue
        if entry.is_dir():
            junction(folder / entry.name, entry)
        elif not (folder / entry.name).exists():
            shutil.copyfile(entry, folder / entry.name)


# ------------------------------------------------------------------ direct side

PROJECT_FILES = {
    "remotion.config.ts": (
        "import {Config} from '@remotion/cli/config';\n\n"
        "Config.setVideoImageFormat('jpeg');\n"
        "Config.setOverwriteOutput(true);\n"
        "// The machine's Chrome (no download on this host).\n"
        "Config.setBrowserExecutable({chrome});\n"
        "Config.setChromeMode('chrome-for-testing');\n"),
    "tsconfig.json": json.dumps({"compilerOptions": {"target": "ES2022", "module": "commonjs", "jsx": "react-jsx", "strict": True,
                                                     "esModuleInterop": True, "skipLibCheck": True, "noEmit": True,
                                                     "moduleResolution": "node", "lib": ["dom", "es2022"]},
                                 "include": ["src"]}, indent=2) + "\n",
    "src/index.ts": "import {registerRoot} from 'remotion';\nimport {RemotionRoot} from './Root';\n\nregisterRoot(RemotionRoot);\n",
    "src/Root.tsx": ("import React from 'react';\n\n"
                     "export const RemotionRoot: React.FC = () => {\n  return <></>;\n};\n"),
}


def direct_start(args: argparse.Namespace) -> None:
    d = run_dir(args.run)
    project = d / "project"
    project.mkdir(exist_ok=True)
    package = json.loads((GATE / "package.json").read_text(encoding="utf-8"))
    package.update(name="deck", description="Remotion project",
                   scripts={"start": "remotion studio src/index.ts", "build": "remotion bundle src/index.ts"})
    (project / "package.json").write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
    for rel, text in PROJECT_FILES.items():
        target = project / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text.replace("{chrome}", json.dumps(CHROME)), encoding="utf-8")
    shadow_node_modules(project)
    text = brief(args.topic)
    stream = d / "stream.jsonl"
    argv = [shutil.which("claude") or "claude", "-p", text, "--model", args.model, "--output-format", "stream-json", "--verbose",
            "--safe-mode", "--strict-mcp-config", "--permission-mode", "bypassPermissions", "--max-budget-usd", str(args.budget),
            "--disallowedTools", "Bash(npm install*)", "Bash(npm i *)", "Bash(npm add*)", "Bash(npx create*)", "Bash(pnpm*)",
            "Bash(yarn*)", "PowerShell(npm install*)", "PowerShell(npm i *)"]
    with open(stream, "wb") as out, open(d / "stderr.txt", "wb") as err:
        proc = subprocess.Popen(argv, cwd=project, stdout=out, stderr=err, stdin=subprocess.DEVNULL, creationflags=DETACHED)
    meta(args.run, side="direct", topic=args.topic, model=args.model, budget_usd=args.budget, brief=text, pid=proc.pid,
         started_epoch=time.time(), project=str(project), pack_sha256=sha256(pack(args.topic) / "README.md"),
         argv_flags=[a for a in argv[3:] if a.startswith("--")])
    print(json.dumps({"run": args.run, "pid": proc.pid, "project": str(project)}))


def stream_events(run: str) -> list[dict]:
    path = run_dir(run) / "stream.jsonl"
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def alive(pid: int | None) -> bool:
    if not pid:
        return False
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


# ------------------------------------------------------------------ Jarvis side

def jarvis_env(m: dict) -> dict:
    d = Path(m["dir"])
    env = {**os.environ, "PYTHONPATH": str(BRN), "JARVIS_DATA_ROOT": str(d / "data"), "JARVIS_RUNTIME_DIR": str(d / "runtime"),
           "JARVIS_CORE_PORT": str(m["core_port"]), "JARVIS_CORE_HOST": "127.0.0.1", "JARVIS_UI_PORT": str(m["cc_port"]),
           "JARVIS_REMOTION_SANDBOX_HOST": "127.0.0.2", "JARVIS_REMOTION_SANDBOX_PORT": str(m["sandbox_port"]),
           "JARVIS_REMOTION_STUDIO_PORT": str(m["studio_port"]), "JARVIS_VISUALIZER_ENABLED": "0", "JARVIS_WINDOWS_NOTIFICATIONS": "0",
           "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    if m.get("model"):
        env["JARVIS_CLAUDE_MODEL"] = m["model"]
    return env


def jarvis_up(args: argparse.Namespace) -> None:
    d = run_dir(args.run)
    sys.path.insert(0, str(BRN))
    from tests.fakes.remotion_player_stack import provision_runtime
    (d / "data").mkdir(exist_ok=True)
    (d / "runtime").mkdir(exist_ok=True)
    provision_runtime(d / "data", GATE)
    m = meta(args.run, side="jarvis", dir=str(d), model=args.model, core_port=free_port(), cc_port=free_port(), sandbox_port=free_port(),
             studio_port=free_port(), tested_head=subprocess.run(["git", "-C", str(BRN), "rev-parse", "HEAD"], capture_output=True,
                                                                 text=True).stdout.strip())
    env = jarvis_env(m)
    pids = []
    for name, argv, ready in (("core", [PY, "-m", "jarvis", "core"], "ready on"),
                              ("cc", [PY, str(HERE / "run_cc_strict.py")], "Control Center ready on")):
        log = d / f"{name}.out"
        with open(log, "wb") as out:
            proc = subprocess.Popen(argv, cwd=BRN, env=env, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    creationflags=DETACHED)
        pids.append(proc.pid)
        meta(args.run, pids=pids)
        for _ in range(450):
            time.sleep(0.2)
            if ready in log.read_text(encoding="utf-8", errors="replace"):
                break
            if proc.poll() is not None:
                raise SystemExit(f"{name} died: {log.read_text(encoding='utf-8', errors='replace')[-1500:]}")
        else:
            raise SystemExit(f"{name} not ready")
    meta(args.run, up_epoch=time.time())
    print(json.dumps({"run": args.run, "core": m["core_port"], "cc": m["cc_port"], "pids": pids}))


def cc(m: dict, method: str, path: str, body: object = None, timeout: float = 60) -> tuple[int, object]:
    req = urllib.request.Request(f"http://127.0.0.1:{m['cc_port']}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()[:2000].decode("utf-8", "replace")


def core(m: dict, method: str, path: str, body: object = None, timeout: float = 120) -> tuple[int, object]:
    token = (Path(m["dir"]) / "runtime" / "core.token").read_text(encoding="utf-8").strip()
    req = urllib.request.Request(f"http://127.0.0.1:{m['core_port']}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()[:4000].decode("utf-8", "replace")


def jarvis_ask(args: argparse.Namespace) -> None:
    m = meta(args.run)
    text = args.text or brief(args.topic)
    turns = m.get("turns", [])
    started = time.time()
    status, body = cc(m, "POST", "/api/agent/ask", {"text": text, "context": {"addressing": "addressed"}, "timeout_s": args.timeout},
                      timeout=args.timeout + 30)
    turns.append({"text": text, "topic": args.topic, "sent_epoch": started, "elapsed_s": round(time.time() - started, 1), "status": status,
                  "answer": body if not isinstance(body, dict) else {k: body.get(k) for k in ("text", "answer", "ok", "error", "reply") if k in body}})
    extra = {"pack_sha256": sha256(pack(args.topic) / "README.md")} if args.topic else {}
    meta(args.run, turns=turns, **extra)
    print(json.dumps(turns[-1], ensure_ascii=False)[:3000])


def jarvis_tasks(m: dict) -> dict:
    status, body = cc(m, "GET", "/api/agent/tasks", timeout=20)
    return body if status == 200 and isinstance(body, dict) else {}


def jarvis_line(m: dict) -> tuple[bool, str]:
    tasks = jarvis_tasks(m)
    brain = tasks.get("brain") or {}
    running = [t for t in tasks.get("tasks", []) if t.get("status") in ("running", "pending", "async_launched")]
    idle = not brain.get("busy") and not running
    desc = "; ".join(f"{t.get('description', '')[:50]}:{t.get('status')}:{t.get('tool_uses')}" for t in tasks.get("tasks", []))
    return idle, f"brain_busy={brain.get('busy')} tasks=[{desc}] activity={str(brain.get('activity'))[:80]}"


def jarvis_collect(args: argparse.Namespace) -> None:
    """Every presentation of the run: documents, scene sources (as Core serves them to an agent), agent tasks, the CLI session id."""

    m = meta(args.run)
    out = run_dir(args.run) / "collected"
    out.mkdir(exist_ok=True)
    status, listing = core(m, "GET", "/v1/presentation-studio/presentations")
    decks = []
    for row in (listing or {}).get("presentations", []) if status == 200 else []:
        pid = row["presentation_id"]
        _, doc = core(m, "GET", f"/v1/presentation-studio/presentations/{pid}")
        deck = {"presentation_id": pid, "title": row.get("title"), "revision": row.get("revision"), "variants": []}
        for variant in (doc or {}).get("variants", []):
            vid = variant["variant_id"]
            scenes = []
            for scene in variant.get("scenes", []):
                sid = scene["scene_id"]
                s, source = core(m, "GET", f"/v1/presentation-studio/presentations/{pid}/variants/{vid}/scenes/{sid}/source")
                folder = out / pid / vid / sid
                folder.mkdir(parents=True, exist_ok=True)
                if s == 200 and isinstance(source, dict):
                    for path, text in (source.get("sources") or {}).items():
                        target = folder / path
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(text if isinstance(text, str) else json.dumps(text), encoding="utf-8")
                    (folder / "manifest.json").write_text(json.dumps(source.get("manifest"), indent=1, ensure_ascii=False), encoding="utf-8")
                scenes.append({"scene_id": sid, "title": scene.get("title"), "prefab": scene.get("prefab"),
                               "source_status": s})
            deck["variants"].append({"variant_id": vid, "revision": variant.get("revision"), "title": variant.get("title"),
                                     "scenes": scenes})
        decks.append(deck)
    tasks = jarvis_tasks(m)
    (out / "agent-tasks.json").write_text(json.dumps(tasks, indent=1, ensure_ascii=False), encoding="utf-8")
    meta(args.run, decks=decks, brain_session_id=(tasks.get("brain") or {}).get("session_id"), collected_epoch=time.time())
    print(json.dumps(decks, ensure_ascii=False)[:2000])


def jarvis_down(args: argparse.Namespace) -> None:
    m = meta(args.run)
    for pid in m.get("pids", []):
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
    meta(args.run, down_epoch=time.time())
    print("down", m.get("pids"))


# ------------------------------------------------------------------ both

def status_line(run: str) -> tuple[bool, str]:
    m = meta(run)
    if m.get("side") == "direct":
        rows = stream_events(run)
        result = next((r for r in reversed(rows) if r.get("type") == "result"), None)
        tools = sum(1 for r in rows if r.get("type") == "assistant"
                    for c in (r.get("message") or {}).get("content", []) if isinstance(c, dict) and c.get("type") == "tool_use")
        done = result is not None or not alive(m.get("pid"))
        cost = result.get("total_cost_usd") if result else None
        return done, f"events={len(rows)} tool_calls={tools} done={done} cost={cost} elapsed={round(time.time() - m['started_epoch'])}s"
    return jarvis_line(m)


def wait(args: argparse.Namespace) -> None:
    deadline = time.time() + min(args.max, 560)
    idle_since = None
    while True:
        done, line = status_line(args.run)
        if done:
            idle_since = idle_since or time.time()
            if time.time() - idle_since >= args.settle:
                print("IDLE", line)
                return
        else:
            idle_since = None
        if time.time() > deadline:
            print("RUNNING", line)
            return
        time.sleep(10)


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("direct-start"); s.add_argument("run"); s.add_argument("topic"); s.add_argument("--model", default="sonnet")
    s.add_argument("--budget", type=float, default=4.0)
    s = sub.add_parser("jarvis-up"); s.add_argument("run"); s.add_argument("--model", default="sonnet")
    s = sub.add_parser("jarvis-ask"); s.add_argument("run"); s.add_argument("topic", nargs="?"); s.add_argument("--text")
    s.add_argument("--timeout", type=float, default=500)
    s = sub.add_parser("wait"); s.add_argument("run"); s.add_argument("--max", type=float, default=540)
    s.add_argument("--settle", type=float, default=20)
    s = sub.add_parser("status"); s.add_argument("run")
    s = sub.add_parser("jarvis-down"); s.add_argument("run")
    s = sub.add_parser("jarvis-collect"); s.add_argument("run")
    args = p.parse_args()
    if args.cmd == "direct-start":
        direct_start(args)
    elif args.cmd == "jarvis-up":
        jarvis_up(args)
    elif args.cmd == "jarvis-ask":
        jarvis_ask(args)
    elif args.cmd == "wait":
        wait(args)
    elif args.cmd == "status":
        print(status_line(args.run)[1])
    elif args.cmd == "jarvis-collect":
        jarvis_collect(args)
    elif args.cmd == "jarvis-down":
        jarvis_down(args)


if __name__ == "__main__":
    main()

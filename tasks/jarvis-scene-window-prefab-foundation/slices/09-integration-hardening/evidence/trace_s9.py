"""Traces réelles S09 (cycle de vie complet des prefabs) : Core 18993 + Control Center 18994 isolés, CLI Claude réel.

Harnais de la Slice 07 (`../../07-agent-prefab-operations/evidence/trace_s7.py`, même lanceur
`run_cc_strict.py` en `--strict-mcp-config`), avec trois ajouts :
- chaque tour attend que le travail délégué soit fini (`agent.subagent.started` = `finished`, puis le
  `result` du relais du cerveau, puis 8 s sans nouveau rang) : un seul fichier par tour, sous-agents compris ;
- `tick <nom> <n>` coche les n premiers éléments de la fenêtre `jarvis.checklist` par de VRAIS clics souris
  dans le cadre sandboxé (Chrome sans tête, `tick_probe.mjs`) : cadre → hôte → `POST /api/prefabs/events` ;
- `new_session <nom>` ouvre une nouvelle Session (`POST /api/sessions/new`, comme le bouton de l'écran).

Usage (depuis la racine du worktree, `S09_SCRATCH` = racine jetable) :
  python trace_s9.py start | ask <nom> "<texte>" | tick <nom> <n> | new_session <nom> | state <nom> | stop
Sorties : `out/<nom>.json` (rangs de `runtime/trace.jsonl` du tour, réponse, état avant/après).
Ports 18993/18994 seulement, jamais 17653/17654 ni la base vivante.
"""
import json, os, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

S = Path(__file__).parent
S07 = S.parents[1] / "07-agent-prefab-operations" / "evidence"
PY = r"C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe"
REPO = str(S.parents[4])
CHROME = r"C:/Program Files/Google/Chrome/Application/chrome.exe"
CORE, CC = 18993, 18994
root = Path(os.environ["S09_SCRATCH"])
data, rt = root / "data", root / "runtime"
OUT = S / "out"
env = {**os.environ, "PYTHONPATH": REPO, "JARVIS_DATA_ROOT": str(data), "JARVIS_RUNTIME_DIR": str(rt),
       "JARVIS_CORE_PORT": str(CORE), "JARVIS_CORE_HOST": "127.0.0.1", "JARVIS_UI_PORT": str(CC),
       "JARVIS_SCENE_ENABLED": "1", "JARVIS_VISUALIZER_ENABLED": "0", "PYTHONIOENCODING": "utf-8",
       "PYTHONUNBUFFERED": "1"}


def launch(args, name, ready):
    log = open(root / f"{name}.out", "w", encoding="utf-8")
    p = subprocess.Popen([PY, *args], cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT,
                         creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008)  # DETACHED_PROCESS
    (root / f"{name}.pid").write_text(str(p.pid))
    for _ in range(300):
        time.sleep(0.2)
        if ready in (root / f"{name}.out").read_text(encoding="utf-8", errors="replace"):
            return
        if p.poll() is not None:
            raise SystemExit(f"{name} died")
    raise SystemExit(f"{name} not ready")


def http(url, method="GET", body=None, headers=None, timeout=900):
    r = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                               headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def cc(method, path, body=None, timeout=900):
    return http(f"http://127.0.0.1:{CC}{path}", method, body, timeout=timeout)


def core(method, path, body=None):
    tok = (rt / "core.token").read_text().strip()
    return http(f"http://127.0.0.1:{CORE}{path}", method, body, {"Authorization": f"Bearer {tok}"})


def trace():
    p = rt / "trace.jsonl"
    rows = []
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                rows.append({"kind": "unreadable_line"})  # Core et CC écrivent le même fichier
    return rows


def state():
    _, snap = core("GET", "/v1/scene/snapshot")
    windows = [{"object_id": o["object_id"], "title": o["payload"].get("title"), "prefab": o["payload"].get("prefab")}
               for o in snap["snapshot"]["objects"] if o["kind"] == "window"]
    lib = data / "prefabs"
    files = sorted(str(p.relative_to(lib)).replace("\\", "/") for p in lib.rglob("publication.json")) if lib.exists() else []
    pubs = {f: json.loads((lib / f).read_text("utf-8"))["provenance"] for f in files}
    _, current = cc("GET", "/api/sessions/current")
    session = (current or {}).get("session") or {}
    return {"revision": snap["snapshot"]["revision"], "windows": windows, "library": pubs,
            "session_id": session.get("jarvis_session_id"), "conversation_id": ((current or {}).get("binding") or {}).get("conversation_id")}


def dump(name, payload):
    OUT.mkdir(exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def settle(mark, limit_s=900):
    """Attendre la fin du travail délégué du tour (voir l'en-tête) ; rend les rangs depuis la marque."""

    deadline, last_len, quiet_since = time.time() + limit_s, -1, time.time()
    while time.time() < deadline:
        rows = trace()[mark:]
        kinds = [r.get("kind") for r in rows]
        started, finished = kinds.count("agent.subagent.started"), kinds.count("agent.subagent.finished")
        if len(rows) != last_len:
            last_len, quiet_since = len(rows), time.time()
        relayed = True
        if finished:
            last_finished = max(i for i, k in enumerate(kinds) if k == "agent.subagent.finished")
            relayed = any(r.get("kind") == "agent.event" and r.get("message") == "result" for r in rows[last_finished:])
        if started == finished and relayed and time.time() - quiet_since >= 8:
            return rows
        time.sleep(2)
    return trace()[mark:] + [{"kind": "harness.settle_timeout"}]


def turn(name, send):
    mark = len(trace())
    before = state()
    started = time.time()
    answer = send()
    answered_s = round(time.time() - started, 1)
    rows = settle(mark)
    dump(name, {"answered_s": answered_s, "settled_s": round(time.time() - started, 1), "answer": answer,
                "before": before, "after": state(), "rows": rows})
    tools = [(r["kind"], r.get("data", {}).get("tool"), r.get("data", {}).get("code") or r.get("data", {}).get("outcome"))
             for r in rows if str(r.get("kind", "")).startswith(("display.", "agent.subagent"))]
    print(json.dumps({"answer": answer, "display_rows": tools}, ensure_ascii=False, indent=1)[:6000])


cmd = sys.argv[1]
if cmd == "start":
    root.mkdir(parents=True, exist_ok=True)
    launch(["-m", "jarvis", "core"], "core", "ready on")
    launch([str(S07 / "run_cc_strict.py")], "cc", "Control Center ready on")
    print("started")
elif cmd == "ask":
    name, text = sys.argv[2], sys.argv[3]
    turn(name, lambda: cc("POST", "/api/agent/ask", {"text": text, "timeout_s": 600,
                                                    "context": {"addressing": "addressed"}}))
elif cmd == "tick":
    name, count = sys.argv[2], int(sys.argv[3])
    mark, before = len(trace()), state()
    win = next(w for w in reversed(before["windows"]) if w["prefab"] and w["prefab"]["id"] == "jarvis.checklist")
    probe = subprocess.run(["node", str(S / "tick_probe.mjs"), f"http://127.0.0.1:{CC}/", CHROME, win["object_id"],
                            str(count)], capture_output=True, text=True, encoding="utf-8", timeout=180)
    time.sleep(2)
    dump(name, {"probe": json.loads(probe.stdout.strip().splitlines()[-1]) if probe.stdout.strip() else probe.stderr[-2000:],
                "window": win["object_id"], "before": before, "after": state(), "rows": trace()[mark:]})
    print(probe.stdout[-3000:], probe.stderr[-1500:])
elif cmd == "new_session":
    name = sys.argv[2]
    before = state()
    status, body = cc("POST", "/api/sessions/new", {"origin": "user"})
    time.sleep(2)
    dump(name, {"status": status, "body": body, "before": before, "after": state()})
    print(status, json.dumps(body, ensure_ascii=False)[:1500])
elif cmd == "state":
    dump(sys.argv[2], state())
    print(json.dumps(state(), ensure_ascii=False, indent=1)[:4000])
elif cmd == "stop":
    for name in ("cc", "core"):
        pid = root / f"{name}.pid"
        if pid.exists():
            subprocess.run(["taskkill", "/T", "/F", "/PID", pid.read_text()], capture_output=True)
    print("stopped")

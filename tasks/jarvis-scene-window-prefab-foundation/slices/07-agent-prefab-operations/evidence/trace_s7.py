"""Traces réelles S07 (prefabs du cerveau) : Core 18993 + Control Center 18994 isolés, CLI Claude réel en --strict-mcp-config.

Usage (depuis la racine du worktree) :
  python trace_s7.py start                 # lance Core et le Control Center (racines de scratch), attend « ready »
  python trace_s7.py ask <nom> "<texte>"   # un tour par POST /api/agent/ask (context.addressing = addressed)
  python trace_s7.py core_turn <nom> "<texte>"  # un tour par Core (/v1/conversations/{id}/brain-turns) : Conversation
                                                # Events et contexte de tour (prefab_events) réels
  python trace_s7.py notify <nom>          # un geste notify `checklist_completed` sur la fenêtre checklist, relais CC
  python trace_s7.py state <nom>           # scène + bibliothèque de données
  python trace_s7.py stop

Chaque commande écrit `out/<nom>.json` : lignes de `runtime/trace.jsonl` depuis la marque, réponse, état.
Racines : `S07_SCRATCH` (données et runtime jetables, jamais la base vivante). Ports 18993/18994 seulement.
"""
import json, os, subprocess, sys, time, urllib.error, urllib.request, uuid
from pathlib import Path

S = Path(__file__).parent
PY = r"C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe"
REPO = r"C:/Projects/jarvis/bpf"
CORE, CC = 18993, 18994
root = Path(os.environ["S07_SCRATCH"])
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
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


def state():
    _, snap = core("GET", "/v1/scene/snapshot")
    windows = [{"object_id": o["object_id"], "title": o["payload"].get("title"), "prefab": o["payload"].get("prefab")}
               for o in snap["snapshot"]["objects"] if o["kind"] == "window"]
    lib = data / "prefabs"
    files = sorted(str(p.relative_to(lib)) for p in lib.rglob("publication.json")) if lib.exists() else []
    pubs = {f: json.loads((lib / f).read_text("utf-8"))["provenance"] for f in files}
    return {"revision": snap["snapshot"]["revision"], "windows": windows, "library": pubs}


def dump(name, payload):
    OUT.mkdir(exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def turn(name, send):
    mark = len(trace())
    before = state()
    started = time.time()
    answer = send()
    time.sleep(3)
    rows = trace()[mark:]
    dump(name, {"elapsed_s": round(time.time() - started, 1), "answer": answer, "before": before, "after": state(),
                "rows": rows})
    tools = [(r["kind"], r.get("data", {}).get("tool"), r.get("data", {}).get("code") or r.get("data", {}).get("outcome"))
             for r in rows if r["kind"].startswith("display.")]
    print(json.dumps({"answer": answer, "display_rows": tools}, ensure_ascii=False, indent=1)[:6000])


cmd = sys.argv[1]
if cmd == "start":
    root.mkdir(parents=True, exist_ok=True)
    launch(["-m", "jarvis", "core"], "core", "ready on")
    launch([str(S / "run_cc_strict.py")], "cc", "Control Center ready on")
    print("started")
elif cmd == "ask":
    name, text = sys.argv[2], sys.argv[3]
    turn(name, lambda: cc("POST", "/api/agent/ask", {"text": text, "timeout_s": 600,
                                                    "context": {"addressing": "addressed"}}))
elif cmd == "core_turn":
    name, text = sys.argv[2], sys.argv[3]

    def send():
        _, current = cc("GET", "/api/sessions/current")
        conv = current["binding"]["conversation_id"]
        mark = len(trace())
        status, ack = core("POST", f"/v1/conversations/{conv}/brain-turns",
                           {"content": text, "correlation_id": str(uuid.uuid4()), "source": "text",
                            "addressing": "addressed"})
        deadline = time.time() + 600
        while time.time() < deadline:
            if any(r["kind"] == "agent.event" and r.get("message") == "result" for r in trace()[mark:]):
                break
            time.sleep(2)
        return {"status": status, "ack": ack, "conversation_id": conv}
    turn(name, send)
elif cmd == "notify":
    name = sys.argv[2]
    win = next(w for w in state()["windows"] if w["prefab"] and w["prefab"]["id"] == "jarvis.checklist")
    items = win["prefab"]["data"].get("items", [])
    st, body = cc("POST", "/api/prefabs/events", {"object_id": win["object_id"], "prefab": {
        "id": "jarvis.checklist", "version": win["prefab"]["version"]}, "event": "checklist_completed",
        "payload": {"count": len(items)}})
    dump(name, {"status": st, "body": body, "window": win["object_id"]})
    print(st, body)
elif cmd == "state":
    dump(sys.argv[2], state())
    print(json.dumps(state(), ensure_ascii=False, indent=1)[:4000])
elif cmd == "stop":
    for name in ("cc", "core"):
        pid = root / f"{name}.pid"
        if pid.exists():
            subprocess.run(["taskkill", "/T", "/F", "/PID", pid.read_text()], capture_output=True)
    print("stopped")

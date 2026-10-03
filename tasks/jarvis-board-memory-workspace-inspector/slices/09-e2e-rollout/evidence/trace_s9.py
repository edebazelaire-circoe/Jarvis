"""Trace réelle S09 : sous-agent délégué sur un Board ARCHIVÉ (mémoire + historique de Sessions), premier plan inchangé."""
import json, os, subprocess, sys, time, urllib.request, uuid
from pathlib import Path
S = Path(__file__).parent
PY = r"C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe"
BBM = r"C:/Projects/jarvis/bbm"
CORE, CC = 18971, 18972
root = S / "trace"; data, rt = root / "data", root / "runtime"
OUT = S / "trace_out"; OUT.mkdir(exist_ok=True)
env = {**os.environ, "PYTHONPATH": BBM, "JARVIS_DATA_ROOT": str(data), "JARVIS_RUNTIME_DIR": str(rt),
       "JARVIS_CORE_PORT": str(CORE), "JARVIS_CORE_HOST": "127.0.0.1", "JARVIS_UI_PORT": str(CC),
       "JARVIS_VISUALIZER_ENABLED": "0", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
procs = []

def launch(args, name, ready):
    log = open(root / f"{name}.out", "w", encoding="utf-8")
    p = subprocess.Popen([PY, *args], cwd=BBM, env=env, stdout=log, stderr=subprocess.STDOUT)
    procs.append(p)
    for _ in range(300):
        time.sleep(0.2)
        if ready in (root / f"{name}.out").read_text(encoding="utf-8", errors="replace"): return p
        if p.poll() is not None: raise SystemExit(f"{name} died")
    raise SystemExit(f"{name} not ready")

def cc(method, path, body=None):
    r = urllib.request.Request(f"http://127.0.0.1:{CC}{path}", method=method,
                               data=json.dumps(body).encode() if body is not None else None,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=60) as resp: return json.loads(resp.read())
    except urllib.error.HTTPError as e: raise SystemExit(f"{method} {path} {e.code} {e.read()[:300]}")

def core(method, path, body=None):
    tok = (rt / "core.token").read_text().strip()
    r = urllib.request.Request(f"http://127.0.0.1:{CORE}{path}", method=method,
                               data=json.dumps(body).encode() if body is not None else None,
                               headers={"Content-Type": "application/json", "Authorization": f"Bearer {tok}"})
    with urllib.request.urlopen(r, timeout=60) as resp: return resp.status, json.loads(resp.read())

def trace():
    p = rt / "trace.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []

def files(board):
    base = data / "boards" / board
    return sorted((str(p.relative_to(base)), p.stat().st_size, p.stat().st_mtime_ns) for p in base.rglob("*")) if base.exists() else []

def state(kepler):
    cur = cc("GET", "/api/sessions/current")
    sid = cur["session"]["jarvis_session_id"]
    sess = cc("GET", f"/api/workspace/sessions/{sid}")
    act = cc("GET", f"/api/workspace/sessions/{sid}/activity?limit=100")["events"]
    kb = cc("GET", f"/api/boards/{kepler}")["board"]
    return {"jarvis_session_id": sid, "active_board_id": cur["session"]["active_board_id"],
            "visited_board_ids": cur["session"]["visited_board_ids"],
            "foreground_binding": {k: cur["binding"].get(k) for k in ("board_id", "conversation_id", "lifecycle", "status", "jarvis_session_id")},
            "speech_authority": sess.get("speech_authority"),
            "session_boards": [(b["board_id"], (b.get("binding") or {}).get("lifecycle")) for b in sess["boards"]],
            "kepler": {k: kb.get(k) for k in ("status", "last_opened_at", "updated_at", "title", "board_kind")},
            "kepler_files": files(kepler),
            "board_ledger_rows": [(e["kind"], e["data"].get("board_id"), e["data"].get("origin")) for e in act if e["kind"].startswith("board.")],
            "sessions_total": len(cc("GET", "/api/workspace/sessions?limit=100")["sessions"])}

try:
    launch(["-m", "jarvis", "core"], "core", "ready on")
    launch([str(S / "run_cc_strict.py")], "cc", "Control Center ready on")
    time.sleep(3)
    # Mise en place : Kepler (meeting) travaillé dans une Session 1, mémoire écrite, puis Session neuve, Kepler archivé.
    kepler = cc("POST", "/api/boards", {"title": "Projet Kepler", "board_kind": "meeting"})["board"]["board_id"]
    cc("POST", "/api/boards/switch", {"board_id": kepler})
    w = f"/api/workspace/boards/{kepler}/memory/write"
    cc("POST", w, {"path": "summary.md", "content": "# Projet Kepler\nRevue fournisseurs terminée. Voir decisions.md.\n"})
    cc("POST", w, {"path": "decisions.md", "content": "- Fournisseur retenu : LYRA (code KEPLER-31).\n- Lancement reporté au 12 novembre.\n"})
    old_session = cc("GET", "/api/sessions/current")["session"]["jarvis_session_id"]
    cc("POST", "/api/boards/switch", {"board_id": "default"})
    cc("POST", "/api/sessions/new", {"expected_session_id": old_session})
    time.sleep(3)
    cc("POST", f"/api/boards/{kepler}/archive")
    atlas = cc("POST", "/api/boards", {"title": "Projet Atlas"})["board"]["board_id"]
    cc("POST", "/api/boards/switch", {"board_id": atlas})
    time.sleep(5)
    before = state(kepler)
    (OUT / "state-0-before.json").write_text(json.dumps({"kepler": kepler, "old_session": old_session, **before}, ensure_ascii=False, indent=1), encoding="utf-8")
    conv = before["foreground_binding"]["conversation_id"]
    mark = len(trace())
    text = ("Envoie un sous-agent inspecter l'ancien Board archivé « Projet Kepler » sans l'ouvrir : qu'il lise sa "
            "mémoire et l'historique de ses Sessions, puis me dise ce qui avait été décidé et dans quelle Session.")
    st, ack = core("POST", f"/v1/conversations/{conv}/brain-turns",
                   {"content": text, "correlation_id": str(uuid.uuid4()), "source": "text", "addressing": "addressed"})
    print("turn", st, ack.get("turn_id") or ack)
    deadline = time.time() + 300
    while time.time() < deadline:
        kinds = [r["kind"] for r in trace()[mark:]]
        if "core.brain.notice_relayed" in kinds or "agent.unsolicited_result" in kinds:
            break
        time.sleep(2)
    time.sleep(15)
    after = state(kepler)
    (OUT / "state-1-after.json").write_text(json.dumps(after, ensure_ascii=False, indent=1), encoding="utf-8")
    rows = trace()[mark:]
    (OUT / "trace-rows.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    costs = [r["data"].get("cost_usd") for r in rows if isinstance(r.get("data"), dict) and r["data"].get("cost_usd") is not None]
    diff = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
    print(json.dumps({"diff": diff, "costs": costs, "kinds": sorted({r["kind"] for r in rows})}, ensure_ascii=False, indent=1))
finally:
    for p in procs:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)

"""Bac à sable Slice 12 : Core + Control Center isolés (31653/31654) depuis le worktree orch12.

Sous-commandes courtes (< 5 min chacune) :

  trial.py start            démarre Core puis Control Center (cerveau haiku, aucun tour envoyé), détachés
  trial.py seed <n> [qa]    joue n missions research-lead par les vraies routes de Core : faits produits par le
                            vrai hook (`routing_hook.run`), déclarations, relations (Adversary, QA), Work State,
                            clôture par Core ; qa = approved (défaut) | rejected | none
  trial.py check            lit candidats et catalogue par le Control Center, essaie une promotion sans page
  trial.py stop             arrête tout par arbre de PID et vérifie les ports

Refuse de démarrer si un port du bac à sable écoute ; ne touche jamais 17653/17654.
"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ORCH = Path("C:/Projects/jarvis/orch12")
PY = "C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe"
BASE = Path("C:/Users/Clarice/AppData/Local/Temp/claude/C--Projects-jarvis-jarvis/7314dd51-936a-4614-8684-8f4233075b7c/scratchpad/s12")
STATE = BASE / "state.json"
CORE_PORT, UI_PORT = 31653, 31654
HOST = "127.77.0.1"
UI = f"http://127.0.0.1:{UI_PORT}"
CORE = f"http://{HOST}:{CORE_PORT}"


def listening(port):
    for host in (HOST, "127.0.0.1"):
        with socket.socket() as sock:
            sock.settimeout(0.3)
            if sock.connect_ex((host, port)) == 0:
                return True
    return False


def request(method, url, body=None, token=None, headers=None, timeout=15.0):
    head = {"Content-Type": "application/json", **(headers or {})}
    if token:
        head["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=head, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def state():
    return json.loads(STATE.read_text(encoding="utf-8"))


def token():
    return (Path(state()["runtime"]) / "core.token").read_text().strip()


def start():
    if STATE.exists():
        print("state.json exists: stop first"); return 2
    for port in (CORE_PORT, UI_PORT):
        if listening(port):
            print(f"port {port} already listening: refusing"); return 2
    run = BASE / f"run-{int(time.time())}"
    data, runtime = run / "data", run / "runtime"
    data.mkdir(parents=True); runtime.mkdir(parents=True)
    env = {**os.environ, "JARVIS_DATA_ROOT": str(data), "JARVIS_RUNTIME_DIR": str(runtime),
           "JARVIS_CORE_PORT": str(CORE_PORT), "JARVIS_UI_PORT": str(UI_PORT), "JARVIS_VISUALIZER_ENABLED": "0",
           "JARVIS_OPEN_BROWSER": "0", "PYTHONUTF8": "1", "JARVIS_CLAUDE_MODEL": "haiku"}
    env.pop("JARVIS_CORE_TOKEN_FILE", None)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    core = subprocess.Popen([PY, "-m", "jarvis", "core"], cwd=ORCH, env=env, creationflags=flags,
                            stdout=(run / "core.out").open("w"), stderr=subprocess.STDOUT)
    STATE.write_text(json.dumps({"run": str(run), "runtime": str(runtime), "core": core.pid, "cc": None}),
                     encoding="utf-8")
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            if (runtime / "core.token").exists() and request("GET", f"{CORE}/v1/health", token=token())[0] == 200:
                break
        except Exception:  # noqa: BLE001 - pas encore prêt
            pass
        time.sleep(0.5)
    else:
        print("core not healthy"); return 3
    cc = subprocess.Popen([PY, "-m", "jarvis", "control-center"], cwd=ORCH, env=env, creationflags=flags,
                          stdout=(run / "cc.out").open("w"), stderr=subprocess.STDOUT)
    st = state(); st["cc"] = cc.pid; STATE.write_text(json.dumps(st), encoding="utf-8")
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            if request("GET", f"{UI}/api/work-methods")[0] == 200:
                print(f"ready core={core.pid} cc={cc.pid} run={run}"); return 0
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1)
    print("control center not ready"); return 4


def hook_fact(hook_root, description, tool_use_id, caller=None):
    sys.path.insert(0, str(ORCH))
    from jarvis.runtime import agent_declarations, routing_hook
    event = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_use_id": tool_use_id, "session_id": "sb12",
             "tool_input": {"description": description, "prompt": "Faites-le.", "subagent_type": "general-purpose",
                            "run_in_background": True}}
    if caller:
        event["agent_id"] = caller
    routing_hook.run(event, hook_root)
    found = [item.fact for item in agent_declarations.scan(hook_root).facts if item.fact.tool_use_id == tool_use_id]
    return found[-1].to_payload()


def observe(tok, items, status):
    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    batch = {"source": "claude", "producer_id": "sb12", "observations": [
        {"source": "claude", "external_id": ext, "status": status, "kind": "agent", "label": ext,
         "observed_at": now, "role_id": role, **({"parent_external_id": parent} if parent else {})}
        for ext, role, parent in items]}
    code, body = request("POST", f"{CORE}/v1/work/observations", batch, token=tok)
    assert code == 200, (code, body)


def seed(count, qa):
    tok = token()
    hook_root = BASE / f"hook-{int(time.time())}"
    hook_root.mkdir()
    stamp = int(time.time()) % 100000
    for n in range(count):
        o, a, b, q = (f"toolu_{k}{stamp}{n}" for k in "oabq")
        owner = hook_fact(hook_root, f"[general] [research-lead] Comparer deux bibliothèques {n}", o)
        print("owner fact work_method:", owner.get("work_method"), "chosen:", owner.get("work_method_chosen"))
        code, body = request("POST", f"{CORE}/v1/missions/declarations",
                             {"declarations": [{"fact": owner, "work_source": "claude", "work_external_id": o}]},
                             token=tok)
        print("owner", code, [r["outcome"] for r in body.get("results", [])], body.get("results", [{}])[0].get("code"))
        observe(tok, [(o, "research-lead", None)], "running")
        items = []
        for ext, desc in ((a, "[general] [web-research] Angle A"), (b, "[general] [web-research] Angle B"),
                          (q, "[general] [qa] Relire la synthèse")):
            fact = hook_fact(hook_root, desc, ext, caller=f"agent-{o}")
            items.append({"fact": fact, "work_source": "claude", "work_external_id": ext, "parent_work_external_id": o})
        code, body = request("POST", f"{CORE}/v1/missions/declarations", {"declarations": items}, token=tok)
        print("members", code, [(r["outcome"], r.get("code")) for r in body.get("results", [])])
        observe(tok, [(a, "web-research", o), (b, "web-research", o), (q, "qa", o)], "running")
        ref = lambda ext: {"work_source": "claude", "work_external_id": ext}  # noqa: E731
        code, rel = request("POST", f"{CORE}/v1/missions/relations", {
            "caller": ref(o), "kind": "adversary", "purpose": "Confronter les deux angles",
            "participants": [{"ref": ref(a), "position": "producer"}, {"ref": ref(b), "position": "producer"}]},
            token=tok)
        print("adversary open", code, rel.get("relation", {}).get("relation_id") or rel)
        if code == 200:
            code, closed = request("POST", f"{CORE}/v1/missions/relations/{rel['relation']['relation_id']}/close",
                                   {"caller": ref(o), "outcome": "synthesis", "summary": "Synthèse des deux angles"},
                                   token=tok)
            print("adversary close", code, closed.get("relation", {}).get("outcome") or closed)
        if qa != "none":
            code, rel = request("POST", f"{CORE}/v1/missions/relations", {
                "caller": ref(o), "kind": "qa", "purpose": "Relire la synthèse",
                "participants": [{"ref": ref(q), "position": "reviewer"}, {"ref": ref(a), "position": "reviewed"}]},
                token=tok)
            print("qa open", code, rel.get("relation", {}).get("relation_id") or rel)
            if code == 200:
                code, closed = request("POST", f"{CORE}/v1/missions/relations/{rel['relation']['relation_id']}/close",
                                       {"caller": ref(q), "outcome": qa, "summary": "Verdict du relecteur"},
                                       token=tok)
                print("qa close", code, closed.get("relation", {}).get("outcome") or closed)
        observe(tok, [(a, "web-research", o), (b, "web-research", o), (q, "qa", o)], "completed")
        observe(tok, [(o, "research-lead", None)], "completed")
        mission_id = owner.get("mission_id")
        for _ in range(20):
            code, view = request("GET", f"{CORE}/v1/missions/{mission_id}", token=tok)
            status = next((m["status"] for m in view.get("missions", []) if m["mission_id"] == mission_id), None)
            if status and status != "open":
                break
            time.sleep(0.5)
        print("mission", mission_id, "status", status, "relations",
              [(r["kind"], r.get("outcome")) for r in view.get("relations", [])])


def check():
    code, body = request("GET", f"{UI}/api/work-methods/candidates")
    print("candidates", code, json.dumps({"scan": body.get("scan"), "thresholds": body.get("thresholds")}))
    for c in body.get("candidates", []):
        print(" ", c["candidate_id"], c["role_id"], c["method_id"], c["relation_kinds"], c["status"], c["reason"],
              f"uses={c['uses']} +{c['positive']} -{c['negative']} ?{c['unrated']}", "refs", c["evidence_refs"][:6])
    code, cat = request("GET", f"{UI}/api/work-methods")
    print("catalogue latest", code, cat.get("latest"))
    eligible = [c for c in body.get("candidates", []) if c["status"] == "candidate" and c.get("draft")]
    if eligible:
        c = eligible[0]
        code, refused = request("POST", f"{UI}/api/work-methods/promotions",
                                {"candidate_id": c["candidate_id"], "expected_version": c["draft"]["version"] - 1,
                                 "method": c["draft"]})
        print("promotion without a page:", code, refused)
    out = BASE / "evidence"
    out.mkdir(exist_ok=True)
    (out / f"candidates-{int(time.time())}.json").write_text(json.dumps(body, ensure_ascii=False, indent=1),
                                                             encoding="utf-8")


def stop():
    st = state()
    for pid in (st.get("cc"), st.get("core")):
        if pid:
            r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True)
            print(f"taskkill {pid}: {r.returncode} {r.stdout.strip()[:200]} {r.stderr.strip()[:200]}")
    time.sleep(2)
    for port in (CORE_PORT, UI_PORT):
        print(f"port {port} listening after stop: {listening(port)}")
    STATE.unlink()


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "start":
        sys.exit(start())
    if cmd == "seed":
        seed(int(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else "approved")
    elif cmd == "check":
        check()
    elif cmd == "stop":
        stop()

"""Bac à sable Slice 08 : Core + Control Center isolés depuis orch08 (ports 30653/30654), par étapes courtes.

Usage : python sandbox.py <étape> [argument]
  prepare           base de scène v1 construite depuis tests/schema/scene.v1.sql (avec une étoile d'éphémère v1)
  start             Core puis Control Center, détachés ; PIDs dans state.json
  send <scénario>   envoie un scénario au cerveau (haiku) et attend la fin du travail (borné)
  probe             producteur synthétique `sandbox` : une éphémère réussie, une éphémère échouée
  report <nom>      instantanés scène, travail, missions et lignes de trace utiles -> out/<nom>/
  restart-core      arrête Core (PID), le relance, attend sa santé
  stop              arrête tout par PID, vérifie les ports
Refuse de démarrer si un port du bac à sable écoute déjà. Ne touche jamais 17653/17654 (JARVIS vivant).
"""

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ORCH = Path("C:/Projects/jarvis/orch08")
PY = "C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe"
BASE = Path("C:/Users/Clarice/AppData/Local/Temp/claude/C--Projects-jarvis-jarvis/7314dd51-936a-4614-8684-8f4233075b7c/scratchpad/s08")
DATA, RUNTIME, OUT = BASE / "data", BASE / "runtime", BASE / "out"
STATE = BASE / "state.json"
CORE_PORT, UI_PORT = 30653, 30654
HOST = "127.77.0.1"
UI = f"http://127.0.0.1:{UI_PORT}"
CORE = f"http://{HOST}:{CORE_PORT}"
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}

SCENARIOS = {
    # Slice 06 (evidence/run-qa.txt) : Mission Owner coder, producteur coder, relecteur qa, relation QA réelle.
    "qa": ("Ceci est un essai technique, pas une demande à cadrer. Lance exactement un sous-agent avec l'outil Agent, "
           "au premier plan (run_in_background false), subagent_type general-purpose, description « [code] [coder] "
           "Sonde S08 QA », et pour consigne le texte entre guillemets doubles ci-dessous, mot pour mot. \"N'écrivez ni "
           "ne modifiez aucun fichier du dépôt ; les outils de relation de JARVIS sont permis. 1) Lancez avec l'outil "
           "Agent, au premier plan, subagent_type general-purpose, description [code] [coder] Producteur S08, consigne : "
           "Proposez en trois lignes une fonction Python is_palindrome(s) et rendez seulement le code. 2) Notez "
           "l'agentId que l'outil Agent rend pour ce producteur. 3) Lancez au premier plan un relecteur : description "
           "[code] [qa] Relecture S08, consigne : Relisez le code ci-dessous, écrit par l'agent d'agentId <l'agentId>, "
           "puis suivez votre bloc RELATION QA : ouvrez la relation QA, publiez au moins un constat, rendez votre "
           "verdict ; le code : <le code>. 4) Rapportez le verdict et l'identifiant rel_ de la relation.\" Quand il a "
           "fini, dis-moi seulement sa réponse."),
    # Slice 05 : une éphémère réelle qui réussit.
    "ephemeral": ("Ceci est un essai technique. Lance exactement un sous-agent avec l'outil Agent, au premier plan, "
                  "subagent_type general-purpose, description « [éphémère] [general] Sonde S08 éphémère », consigne : "
                  "« Répondez EPH_OK. » Puis dis-moi seulement sa réponse."),
}


def log(text: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {text}"
    print(line, flush=True)
    with (BASE / "sandbox.log").open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def listening(port: int) -> bool:
    for host in (HOST, "127.0.0.1"):
        with socket.socket() as sock:
            sock.settimeout(0.3)
            if sock.connect_ex((host, port)) == 0:
                return True
    return False


def token() -> str:
    return (RUNTIME / "core.token").read_text().strip()


def call(method: str, url: str, body: dict | None = None, *, auth: bool = False, timeout: float = 10.0):
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["Authorization"] = f"Bearer {token()}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def wait(predicate, timeout: float, step: float = 1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            value = predicate()
        except Exception:  # noqa: BLE001 - pas encore prêt
            value = None
        if value:
            return value
        time.sleep(step)
    return None


def env() -> dict:
    values = {**os.environ, "JARVIS_DATA_ROOT": str(DATA), "JARVIS_RUNTIME_DIR": str(RUNTIME),
              "JARVIS_CORE_PORT": str(CORE_PORT), "JARVIS_UI_PORT": str(UI_PORT), "JARVIS_VISUALIZER_ENABLED": "0",
              "JARVIS_OPEN_BROWSER": "0", "JARVIS_CLAUDE_MODEL": "haiku", "PYTHONUTF8": "1",
              "JARVIS_SCENE_RESTART_GRACE_S": "20"}
    values.pop("JARVIS_CORE_TOKEN_FILE", None)
    return values


def spawn(name: str) -> int:
    # Détaché et hors du job de l'outil : survit à la fin de cette commande, arrêté par PID à `stop`.
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | 0x01000000
    out = (BASE / f"{name}.out").open("a", encoding="utf-8")
    proc = subprocess.Popen([PY, "-m", "jarvis", name], cwd=ORCH, env=env(), creationflags=flags, stdout=out,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    return proc.pid


def state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save(values: dict) -> None:
    STATE.write_text(json.dumps(values, indent=1))


def kill(pid: int) -> None:
    result = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True)
    log(f"taskkill {pid}: {result.returncode} {result.stdout.strip()} {result.stderr.strip()}")


def core_healthy() -> bool:
    return (RUNTIME / "core.token").exists() and call("GET", f"{CORE}/v1/health", auth=True)[0] == 200


# ------------------------------------------------------------------ étapes


def prepare() -> int:
    scene = DATA / "state" / "scene.sqlite3"
    if scene.exists():
        log(f"{scene} existe déjà : rien n'est écrasé")
        return 2
    scene.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    ddl = (ORCH / "tests" / "schema" / "scene.v1.sql").read_text(encoding="utf-8")
    statements = [line for line in ddl.splitlines() if line and not line.startswith("--")]

    def star(object_id: str, title: str) -> dict:
        source, external = object_id.split(":", 1)
        return {"object_id": object_id, "kind": "agent", "category": "agent",
                "constraints": {"placed_by": "runtime", "pinned_by_user": False}, "origin": "runtime",
                "exec_state": "completed", "representation": "point", "geometry": None, "layer": 100, "order": 0,
                "visibility": "visible", "disposition": "active",
                "work_ref": {"source": source, "external_id": external, "work_id": None},
                "payload": {"title": title, "summary": "", "items": []}}

    conn = sqlite3.connect(scene)
    try:
        for statement in sorted(statements, key=lambda text: not text.startswith("CREATE TABLE")):
            conn.execute(statement)
        conn.execute("INSERT INTO schema_version(version) VALUES (1)")
        conn.execute("INSERT INTO scene_meta VALUES (1, 'scene-s08-v1', 2, 1, '2026-10-19T08:00:00+00:00', "
                     "'2026-10-19T08:00:00+00:00')")
        rows = [star("claude:toolu_v1_ephemere", "Liste de courses (éphémère v1)"),
                star("claude:toolu_v1_ordinaire", "Audit ordinaire v1")]
        for index, row in enumerate(rows):
            conn.execute("INSERT INTO scene_objects VALUES (?, ?, ?)",
                         (row["object_id"], index, json.dumps(row, ensure_ascii=False, separators=(",", ":"),
                                                              sort_keys=True)))
        conn.commit()
    finally:
        conn.close()
    log(f"base de scène v1 construite : {scene}")
    return 0


def start() -> int:
    for port in (CORE_PORT, UI_PORT):
        if listening(port):
            log(f"port {port} déjà à l'écoute : refus")
            return 2
    values = state()
    values["core"] = spawn("core")
    log(f"core pid {values['core']}")
    save(values)
    if not wait(core_healthy, 90):
        log("core pas en bonne santé")
        return 3
    values["control-center"] = spawn("control-center")
    log(f"control center pid {values['control-center']}")
    save(values)
    ok = wait(lambda: call("GET", f"{UI}/api/agent")[1].get("state") in {"running", "idle", "ready"}, 120)
    log(f"agent prêt : {bool(ok)}")
    return 0 if ok else 4


def items() -> list[dict]:
    return call("GET", f"{CORE}/v1/work/snapshot", auth=True)[1].get("items", [])


def send(name: str) -> int:
    before = {item["external_id"] for item in items()}
    status, _ = call("POST", f"{UI}/api/agent/send", {"text": SCENARIOS[name]}, timeout=30)
    log(f"envoi {name}: {status}")
    started = time.time()

    def done():
        fresh = [item for item in items() if item["external_id"] not in before]
        return fresh and all(item["status"] in TERMINAL for item in fresh) and time.time() - started > 20

    finished = wait(done, 270, 3.0)
    log(f"travail {name} terminé : {bool(finished)} après {time.time() - started:.0f} s")
    return 0 if finished else 5


def probe() -> int:
    now = lambda: time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())  # noqa: E731
    base = {"source": "sandbox", "kind": "agent", "ephemeral": True}
    batches = [
        [{**base, "external_id": "eph-ok", "status": "running", "label": "Éphémère synthétique réussie",
          "observed_at": now()}],
        [{**base, "external_id": "eph-ok", "status": "completed", "label": "Éphémère synthétique réussie",
          "observed_at": now()}],
        [{**base, "external_id": "eph-fail", "status": "running", "label": "Éphémère synthétique échouée",
          "observed_at": now()}],
        [{**base, "external_id": "eph-fail", "status": "failed", "label": "Éphémère synthétique échouée",
          "error_class": "probe_failure", "summary": "échec provoqué par la sonde S08", "observed_at": now()}],
    ]
    for batch in batches:
        time.sleep(1.1)
        for item in batch:
            item["observed_at"] = now()
        status, body = call("POST", f"{CORE}/v1/work/observations",
                            {"source": "sandbox", "producer_id": "s08-probe", "observations": batch}, auth=True)
        log(f"observation {batch[0]['external_id']} {batch[0]['status']}: {status} {body.get('outcomes')}")
    return 0


def report(name: str) -> int:
    target = OUT / name
    target.mkdir(parents=True, exist_ok=True)
    scene = call("GET", f"{CORE}/v1/scene/snapshot", auth=True)[1]
    (target / "scene_snapshot.json").write_text(json.dumps(scene, ensure_ascii=False, indent=1), encoding="utf-8")
    work = items()
    (target / "work_snapshot.json").write_text(json.dumps(work, ensure_ascii=False, indent=1), encoding="utf-8")
    missions = {}
    for item in work:
        status, body = call("GET", f"{CORE}/v1/missions/work/{item['source']}/{item['external_id']}", auth=True)
        mission_id = body.get("mission_id") if status == 200 else None
        if mission_id and mission_id not in missions:
            missions[mission_id] = call("GET", f"{CORE}/v1/missions/{mission_id}", auth=True)[1]
    for obj in (scene.get("snapshot") or {}).get("objects", []):
        mission_id = (obj.get("role_ref") or {}).get("mission_id")
        if mission_id and mission_id not in missions:
            missions[mission_id] = call("GET", f"{CORE}/v1/missions/{mission_id}", auth=True)[1]
    (target / "missions.json").write_text(json.dumps(missions, ensure_ascii=False, indent=1), encoding="utf-8")
    keys = ("core.scene.", "mission_history.", "agent.declared")
    lines = [line for line in (RUNTIME / "trace.jsonl").read_text(encoding="utf-8", errors="replace").splitlines()
             if any(key in line for key in keys)]
    (target / "trace_scene.jsonl").write_text("\n".join(lines[-400:]), encoding="utf-8")
    # Lecture humaine.
    snap = scene.get("snapshot") or {}
    summary = [f"== scène révision {snap.get('revision')} ({len(snap.get('objects', []))} objets, "
               f"{len(snap.get('relations', []))} liens, {len(snap.get('archived_ids', []))} archivés)"]
    for obj in snap.get("objects", []):
        summary.append(f"  {obj['kind']:9} {obj['object_id']:48} exec={obj['exec_state']:11} "
                       f"title={obj['payload'].get('title', '')[:40]!r} role_ref={obj.get('role_ref')}")
    for rel in snap.get("relations", []):
        summary.append(f"  lien {rel['kind']:13} {rel['relation_id'][:70]:70} {rel['from_id']} -> {rel['to_id']} "
                       f"ref={rel.get('ref')}")
    summary.append("== travail")
    for item in work:
        summary.append(f"  {item['source']}:{item['external_id']} {item['status']} ephemeral={item.get('ephemeral')} "
                       f"role={item.get('role_id')} label={item.get('label', '')[:50]!r}")
    summary.append("== missions")
    for mission_id, body in missions.items():
        summary.append(f"  {mission_id}: {json.dumps({k: body.get(k) for k in ('status', 'live_unknown')}, ensure_ascii=False)}"
                       f" relations={[(r.get('kind'), r.get('status'), r.get('outcome')) for r in body.get('relations', [])]}")
    summary.append("== trace (scène)")
    for line in lines:
        if "core.scene." in line and any(k in line for k in ("ephemeral", "mission", "migrated", "star_created",
                                                                 "restart_marked", "restart_grace")):
            summary.append("  " + line[:400])
    (target / "summary.txt").write_text("\n".join(summary), encoding="utf-8")
    print("\n".join(summary[:120]))
    return 0


def restart_core() -> int:
    values = state()
    kill(values["core"])
    wait(lambda: not listening(CORE_PORT), 20, 0.5)
    log(f"port {CORE_PORT} après arrêt : {listening(CORE_PORT)}")
    values["core"] = spawn("core")
    save(values)
    log(f"core relancé pid {values['core']}")
    ok = wait(core_healthy, 90)
    log(f"core en bonne santé : {bool(ok)}")
    return 0 if ok else 3


def stop() -> int:
    values = state()
    for name in ("control-center", "core"):
        if name in values:
            kill(values[name])
    time.sleep(3)
    for port in (CORE_PORT, UI_PORT):
        log(f"port {port} à l'écoute : {listening(port)}")
    return 0


if __name__ == "__main__":
    BASE.mkdir(parents=True, exist_ok=True)
    step = sys.argv[1]
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    steps = {"prepare": prepare, "start": start, "probe": probe, "restart-core": restart_core, "stop": stop}
    if step in ("send", "report"):
        sys.exit({"send": send, "report": report}[step](arg))
    sys.exit(steps[step]())

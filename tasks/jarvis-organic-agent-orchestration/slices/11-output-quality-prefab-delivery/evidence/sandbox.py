"""Bac à sable Slice 11 : Core + Control Center isolés (ports 29653/29654) depuis orch11, cerveau haiku, un scénario,
capture de la page par le navigateur sans tête du dépôt, puis arrêt par arbre de PID.

Copie adaptée de scratchpad/s05/scripts/sandbox.py. Usage : python sandbox.py <scenario>.
Ne touche jamais le JARVIS vivant (17653/17654) ni la Slice 06 (27653/27654) : refuse de démarrer si un des ports
du bac à sable écoute déjà.
"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ORCH = Path("C:/Projects/jarvis/orch11")
PY = "C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe"
BASE = Path("C:/Users/Clarice/AppData/Local/Temp/claude/C--Projects-jarvis-jarvis/7314dd51-936a-4614-8684-8f4233075b7c/scratchpad/s11")
CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe"
CORE_PORT, UI_PORT = 29653, 29654
HOST = "127.77.0.1"
WAIT_S = 230

PRE = ("Ceci est un essai technique, pas une demande à cadrer. Lance exactement un sous-agent avec l'outil Agent, au "
       "premier plan (run_in_background false), subagent_type general-purpose, ")
SCENARIOS = {
    "simple": "Combien de fichiers Markdown y a-t-il dans le dossier docs/legacy du dépôt ? Réponds par un nombre.",
    "simple_mo": PRE + (
        "description « [code] [coder] Compter les fichiers legacy », et pour consigne : « Combien de fichiers Markdown "
        "y a-t-il dans le dossier docs/legacy du dépôt ? Répondez par un nombre. » Quand il a fini, dis-moi seulement "
        "sa réponse."),
    "compare": PRE + (
        "description « [general] [research-lead] Comparatif validation Python », et pour consigne : « L'utilisateur "
        "veut une comparaison sérieuse de pydantic, attrs et marshmallow (performance, ergonomie, validation, "
        "écosystème, licence) pour choisir celle de son prochain service. Travaillez à partir de vos connaissances, "
        "sans recherche web et sans lancer d'autre agent. » Quand il a fini, relaie son compte rendu en deux phrases."),
    "fallback": PRE + (
        "description « [general] [research-lead] Rapport licences voix », et pour consigne : « L'utilisateur veut un "
        "court rapport sur les licences de trois moteurs de synthèse vocale libres (Piper, Coqui XTTS, Kokoro). "
        "Travaillez à partir de vos connaissances, sans recherche web et sans lancer d'autre agent. Affichez-le "
        "uniquement dans le prefab circoe.rapport-licences ; s'il est refusé, n'essayez aucun autre prefab ni "
        "aucune autre fenêtre. » Quand il a fini, relaie son compte rendu tel quel."),
    "fallback_table": PRE + (
        "description « [general] [research-lead] Comparatif éditeurs », et pour consigne : « L'utilisateur veut "
        "comparer VS Code, Zed et Neovim sur dix critères (vitesse, extensions, LSP, débogage, terminal, Git, "
        "collaboration, IA, configuration, licence). Travaillez à partir de vos connaissances, sans recherche web et "
        "sans lancer d'autre agent. Affichez un seul tableau jarvis.table avec une colonne par critère (dix "
        "colonnes en plus de celle des éditeurs, sans en fusionner aucune) ; s'il est refusé, n'essayez aucune "
        "autre forme d'affichage. » Quand il a fini, relaie son compte rendu tel quel."),
}


def listening(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.3)
        if sock.connect_ex((HOST, port)) == 0:
            return True
    with socket.socket() as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def get(url: str, token: str | None = None, timeout: float = 5.0):
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def post(url: str, body: dict, timeout: float = 30.0):
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, json.loads(response.read() or b"{}")


def wait(predicate, timeout: float, step: float = 0.5):
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


def kill_tree(proc: subprocess.Popen, log) -> None:
    if proc.poll() is None:
        result = subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, text=True)
        log(f"taskkill {proc.pid}: {result.returncode} {result.stdout.strip()} {result.stderr.strip()}")
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        log(f"pid {proc.pid} still alive after taskkill")


def shoot(out: Path, runtime: Path, log) -> None:
    plan = [{"name": "scene", "width": 1600, "height": 1000, "actions": [
        {"a": "wait", "expr": "document.querySelectorAll('.sc-prefab-frame').length>0", "timeoutMs": 15000},
        {"a": "eval", "expr": "new Promise(r=>setTimeout(()=>r(1),2500))"},
        {"a": "eval", "expr": "Array.from(document.querySelectorAll('.sc-prefab-frame')).map(f=>{const r=f.getBoundingClientRect();return [r.left,r.top,r.width,r.height]})"},
        {"a": "shot", "path": str(out / "scene.png")}]}]
    plan_file = out / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    try:
        result = subprocess.run(["node", str(ORCH / "tests/unit/_interaction_mode_browser.mjs"),
                                 f"http://127.0.0.1:{UI_PORT}/", CHROME, f"@{plan_file}", str(runtime)],
                                capture_output=True, text=True, timeout=90, cwd=ORCH)
        (out / "browser.json").write_text(result.stdout[:200000] + "\n--stderr--\n" + result.stderr[:20000],
                                          encoding="utf-8")
        log(f"browser harness exit {result.returncode}")
    except subprocess.TimeoutExpired:
        log("browser harness timeout")


def main() -> int:
    scenario = sys.argv[1]
    run = BASE / f"run-{scenario}-{int(time.time())}"
    data, runtime = run / "data", run / "runtime"
    out = BASE / f"out-{scenario}"
    out.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    logf = (out / "sandbox.log").open("w", encoding="utf-8")

    def log(text: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {text}"
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    log(f"run dir {run}")
    for port in (CORE_PORT, UI_PORT):
        if listening(port):
            log(f"port {port} already listening: refusing to start")
            return 2
    env = {**os.environ, "JARVIS_DATA_ROOT": str(data), "JARVIS_RUNTIME_DIR": str(runtime),
           "JARVIS_CORE_PORT": str(CORE_PORT), "JARVIS_UI_PORT": str(UI_PORT), "JARVIS_VISUALIZER_ENABLED": "0",
           "JARVIS_OPEN_BROWSER": "0", "JARVIS_CLAUDE_MODEL": "haiku", "PYTHONUTF8": "1"}
    env.pop("JARVIS_CORE_TOKEN_FILE", None)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP
    core = subprocess.Popen([PY, "-m", "jarvis", "core"], cwd=ORCH, env=env, creationflags=flags,
                            stdout=(out / "core.out").open("w"), stderr=subprocess.STDOUT)
    log(f"core pid {core.pid}")
    cc = None
    try:
        token_file = runtime / "core.token"
        ok = wait(lambda: token_file.exists() and get(f"http://{HOST}:{CORE_PORT}/v1/health",
                                                      token_file.read_text().strip())[0] == 200, 60)
        log(f"core healthy: {bool(ok)}")
        if not ok:
            return 3
        token = token_file.read_text().strip()
        cc = subprocess.Popen([PY, "-m", "jarvis", "control-center"], cwd=ORCH, env=env, creationflags=flags,
                              stdout=(out / "cc.out").open("w"), stderr=subprocess.STDOUT)
        log(f"control center pid {cc.pid}")
        ui = f"http://127.0.0.1:{UI_PORT}"
        ok = wait(lambda: get(f"{ui}/api/agent")[1].get("state") in {"running", "idle", "ready"}, 90, 1.0)
        log(f"agent state: {get(f'{ui}/api/agent')[1].get('state')} ok={bool(ok)}")
        if not ok:
            return 4
        time.sleep(3)
        log(f"send: {post(f'{ui}/api/agent/send', {'text': SCENARIOS[scenario]})[0]}")
        start = time.time()

        def answered():
            transcript = get(f"{ui}/api/agent/transcript")[1]
            text = json.dumps(transcript, ensure_ascii=False)
            items = get(f"http://{HOST}:{CORE_PORT}/v1/work/snapshot", token)[1].get("items", [])
            busy = any(item["status"] not in {"completed", "failed", "cancelled", "interrupted"} for item in items)
            return (not busy) and '"type": "result"' in text and time.time() - start > 15
        done = wait(answered, WAIT_S, 3.0)
        log(f"turn finished: {bool(done)} after {time.time() - start:.0f}s")
        time.sleep(3)
        snapshot = get(f"http://{HOST}:{CORE_PORT}/v1/scene/snapshot", token)[1]
        (out / "scene_snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8")
        work = get(f"http://{HOST}:{CORE_PORT}/v1/work/snapshot", token)[1]
        (out / "work_snapshot.json").write_text(json.dumps(work, ensure_ascii=False, indent=1), encoding="utf-8")
        missions = {}
        for item in work.get("items", []):
            status_code, body = get(f"http://{HOST}:{CORE_PORT}/v1/missions/work/{item['source']}/{item['external_id']}",
                                    token)
            missions[item["external_id"]] = {"status": status_code, "body": body, "role_id": item.get("role_id")}
        (out / "missions.json").write_text(json.dumps(missions, ensure_ascii=False, indent=1), encoding="utf-8")
        transcript = get(f"{ui}/api/agent/transcript")[1]
        (out / "transcript.json").write_text(json.dumps(transcript, ensure_ascii=False, indent=1)[:400000],
                                             encoding="utf-8")
        tasks = get(f"{ui}/api/agent/tasks")[1]
        (out / "tasks.json").write_text(json.dumps(tasks, ensure_ascii=False, indent=1)[:400000], encoding="utf-8")
        prefab_windows = [obj for obj in snapshot.get("snapshot", {}).get("objects", [])
                          if (obj.get("payload") or {}).get("prefab")]
        log(f"prefab windows: {[(o['object_id'], o['payload']['prefab']['id']) for o in prefab_windows]}")
        if prefab_windows:
            shoot(out, runtime, log)
        log("report written")
        return 0
    finally:
        if cc is not None:
            kill_tree(cc, log)
        kill_tree(core, log)
        for port in (CORE_PORT, UI_PORT):
            log(f"port {port} listening after stop: {listening(port)}")
        logf.close()


if __name__ == "__main__":
    sys.exit(main())

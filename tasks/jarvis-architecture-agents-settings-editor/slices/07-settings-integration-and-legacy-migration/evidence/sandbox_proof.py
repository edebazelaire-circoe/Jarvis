"""Preuves S07 en bac à sable : un Control Center lancé depuis le worktree arch-s07, ports 27653/27654, racines au
scratchpad. Démarre, sonde, prouve, arrête SEULEMENT le PID lancé (sans /T). Jamais le JARVIS vivant."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

WORKTREE = Path(r"C:\Projects\jarvis\arch-s07")
PY = Path(r"C:\Projects\jarvis\jarvis\.venv\Scripts\python.exe")
SCRATCH = Path(r"C:\Users\Clarice\AppData\Local\Temp\claude\C--Projects-jarvis-jarvis\05b93d8a-1916-4b86-866a-f10f71884561\scratchpad")
SANDBOX = SCRATCH / "s07-sandbox"
SHOTS = SCRATCH / "s07-shots"
RUNTIME = SANDBOX / "runtime"
UI = "http://127.0.0.1:27654"
LOG: list[str] = []


def say(line: str) -> None:
    LOG.append(line)
    print(line, flush=True)


def http(method: str, path: str, body: object | None = None) -> tuple[int, object]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(UI + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "null")


def conn(snapshot: dict, cid: str) -> dict:
    return next(c for c in snapshot["connections"] if c["id"] == cid)


def main() -> int:
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX)  # bac à sable de cette preuve seulement (aucune base du JARVIS vivant)
    (SANDBOX / "data").mkdir(parents=True)
    RUNTIME.mkdir(parents=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    # Architecture vocale Duplex, comme le poste de l'utilisateur (audit S00) : la liaison Voix → Core est basculable.
    (RUNTIME / "control-center-settings.json").write_text(json.dumps({"voice_architecture": {
        "schema_version": 1, "compatibility": None,
        "config": {"architecture": "duplex", "conversation_model": {"provider_id": "openai", "model_id": "gpt-live-1"}}}},
        indent=2), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("JARVIS_")}
    env.update(JARVIS_DATA_ROOT=str(SANDBOX / "data"), JARVIS_RUNTIME_DIR=str(RUNTIME), JARVIS_CORE_PORT="27653",
               JARVIS_UI_PORT="27654", JARVIS_VISUALIZER_ENABLED="0", PYTHONIOENCODING="utf-8")
    out = open(SANDBOX / "control-center.log", "w", encoding="utf-8")
    proc = subprocess.Popen([str(PY), "-m", "jarvis", "control-center"], cwd=WORKTREE, env=env, stdout=out,
                            stderr=subprocess.STDOUT)
    say(f"control-center lancé : PID {proc.pid}, cwd {WORKTREE}, UI {UI}, runtime {RUNTIME}")
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(UI + "/api/status", timeout=2).read()
                break
            except (urllib.error.URLError, OSError):
                if proc.poll() is not None:
                    say("le Control Center s'est arrêté au démarrage, voir control-center.log")
                    return 1
                time.sleep(0.5)
        else:
            say("Control Center injoignable après 60 s")
            return 1
        return prove(env)
    finally:
        proc.terminate()  # TerminateProcess sur CE PID seulement, pas d'arbre (/T)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        out.close()
        say(f"control-center arrêté : PID {proc.pid}, code {proc.returncode}")
        (SANDBOX / "evidence.log").write_text("\n".join(LOG) + "\n", encoding="utf-8")


def prove(env: dict) -> int:
    # (a) graphe réel, une liaison basculable réelle, un refus verrouillé
    status, snap = http("GET", "/api/architecture")
    say(f"(a) GET /api/architecture -> {status} ; voix {snap['voice_architecture']['id']} ; nœuds "
        f"{[n['id'] for n in snap['nodes']]}")
    link = conn(snap, "voice.delegate->core.request")
    say(f"(a) liaison voice.delegate->core.request : enabled={link['enabled']} mutability={link['mutability']} "
        f"binding={link['binding']} applies={link['applies']}")
    status, body = http("POST", "/api/architecture/connections/voice.delegate->core.request",
                        {"base_revision": snap["revision"], "enabled": False})
    settings = json.loads((RUNTIME / "control-center-settings.json").read_text(encoding="utf-8"))
    sys.path.insert(0, str(WORKTREE))
    from jarvis.runtime.voice_architecture_config import load_voice_architecture
    read = load_voice_architecture(settings, environ={}).config
    switch = (RUNTIME / ".voice_switch_request")
    say(f"(a) POST coupure -> {status} ok={body['ok']} changed={body['changed']} ; réglage persisté "
        f"brain_orchestration={settings['voice_architecture']['config'].get('brain_orchestration')} ; lu par le "
        f"runtime (load_voice_architecture) brain_orchestration={read.brain_orchestration} ; demande de bascule Voice "
        f"écrite={switch.is_file()}")
    status, refused = http("POST", "/api/architecture/connections/mic.audio_out->voice.audio_in",
                           {"base_revision": body["snapshot"]["revision"], "enabled": False})
    say(f"(a) POST liaison verrouillée mic->voice -> {status} code={refused['code']} raison=« {refused['reason']} »")
    status, stale = http("POST", "/api/architecture/connections/voice.delegate->core.request",
                         {"base_revision": snap["revision"], "enabled": True})
    say(f"(a) POST révision périmée -> {status} code={stale['code']}")
    status, back = http("POST", "/api/architecture/connections/voice.delegate->core.request",
                        {"base_revision": body["snapshot"]["revision"], "enabled": True})
    settings = json.loads((RUNTIME / "control-center-settings.json").read_text(encoding="utf-8"))
    say(f"(a) POST remise -> {status} changed={back['changed']} ; brain_orchestration="
        f"{settings['voice_architecture']['config'].get('brain_orchestration')}")

    # (b) cerveau Core : délégation never puis standard, graphe cohérent
    status, core = http("GET", "/api/brains/core/config")
    fields = core["fields"]
    say(f"(b) GET /api/brains/core/config -> {status} ; provider={fields['provider']['value']} "
        f"model={fields['model']['value'] or '(défaut)'} delegation={fields['delegation']['value']} "
        f"catalog={core['catalog']['status']} ; choix de modèle servis={len(fields['model']['choices'])}")
    status, never = http("PATCH", "/api/brains/core/config", {"base_revision": core["revision"], "delegation": "never"})
    _, graph = http("GET", "/api/architecture")
    spawn = conn(graph, "core.agents->subagents.spawn")
    store = json.loads((RUNTIME / "brain-config.json").read_text(encoding="utf-8"))
    say(f"(b) PATCH delegation=never -> {status} changed={never.get('changed')} applies={never.get('applies')} ; "
        f"brain-config.json core={store['brains']['core']['delegation']} ; graphe spawn enabled={spawn['enabled']} "
        f"mutability={spawn['mutability']} governed_by={spawn['governed_by']}")
    status, std = http("PATCH", "/api/brains/core/config",
                       {"base_revision": never["config"]["revision"], "delegation": "standard"})
    _, graph = http("GET", "/api/architecture")
    say(f"(b) PATCH delegation=standard -> {status} ; graphe spawn enabled="
        f"{conn(graph, 'core.agents->subagents.spawn')['enabled']}")
    status, stale = http("PATCH", "/api/brains/core/config", {"base_revision": core["revision"], "delegation": "rare"})
    say(f"(b) PATCH révision périmée -> {status} code={stale['code']}")

    # (c) politique d'un rôle, puis décision du hook hors ligne
    status, policy = http("GET", "/api/subagent-role-routing")
    qa = next(r for r in policy["roles"] if r["role_id"] == "qa")
    say(f"(c) GET /api/subagent-role-routing -> {status} ; révision {policy['revision']} ; qa provenance="
        f"{qa['provenance']} ; harnesses servis={[h.get('agent') or h.get('id') for h in policy['harnesses']]}")
    status, put = http("PUT", "/api/subagent-role-routing/qa", {
        "base_revision": policy["revision"], "allow_general_fallback": True,
        "candidates": [{"agent": "claude", "model": "claude-haiku-4-5"}]})
    qa = next(r for r in put["snapshot"]["roles"] if r["role_id"] == "qa") if put.get("ok") else {}
    say(f"(c) PUT /api/subagent-role-routing/qa -> {status} ok={put.get('ok')} code={put.get('code')} ; "
        f"provenance={qa.get('provenance')} candidats={[(c['agent'], c['model'], c['available']) for c in qa.get('candidates', [])]}")
    event = {"hook_event_name": "PreToolUse", "session_id": "s07-sandbox", "tool_name": "Agent", "tool_use_id": "toolu_s07_qa",
             "tool_input": {"description": "[general] [qa] Relire le diff de la Slice 07",
                            "prompt": "Relis le diff et liste les défauts bloquants.", "subagent_type": "general-purpose"}}
    hook = subprocess.run([str(PY), "-m", "jarvis", "routing-hook", "--runtime-root", str(RUNTIME)], cwd=WORKTREE,
                          env=env, input=json.dumps(event), capture_output=True, text=True, encoding="utf-8", timeout=120)
    say(f"(c) routing-hook -> code {hook.returncode} ; sortie : {hook.stdout.strip()[:400]}")
    decided = []
    trace = RUNTIME / "trace.jsonl"
    if trace.is_file():
        for line in trace.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("kind") == "agent.routing.decided":
                decided.append(row)
    for row in decided[-1:]:
        data = row.get("data") or {}
        say(f"(c) trace agent.routing.decided : level={row.get('level')} role_id={data.get('role_id')} "
            f"provenance={data.get('provenance')} reason={data.get('reason')} message=« {row.get('message')} »")
    if not decided:
        say("(c) aucune ligne agent.routing.decided dans trace.jsonl")
    kinds = {}
    for line in trace.read_text(encoding="utf-8").splitlines() if trace.is_file() else []:
        try:
            k = json.loads(line).get("kind")
        except ValueError:
            continue
        kinds[k] = kinds.get(k, 0) + 1
    say("journal (trace.jsonl) : " + ", ".join(f"{k}×{v}" for k, v in sorted(kinds.items())
                                               if k and k.split(".")[0] in {"architecture", "brain_config", "voice",
                                                                            "subagent_role_routing", "agent"}))

    # (d) la page dans un Chrome sans tête (harnais garde contre le JARVIS vivant)
    return browser()


def browser() -> int:
    sys.path.insert(0, str(WORKTREE))
    from tests.unit.test_wake_word_settings_browser import CHROME_CANDIDATES, HARNESS, click, eval_, key, open_settings, wait
    chrome = next((str(c) for c in CHROME_CANDIDATES if c.is_file()), None)
    node = shutil.which("node")
    if not chrome or not node:
        say("(d) Chrome ou node absent : navigateur non exercé")
        return 1
    shot = lambda name: {"a": "shot", "path": str(SHOTS / name)}  # noqa: E731
    plan = [{"width": 1440, "height": 900, "actions": [
        wait("!!document.getElementById('openSettings')"), click("#dockMore"), *open_settings(),
        click("#settingsCategories [data-category=agents_models]"),
        wait("!!document.querySelector('[data-architecture-page] [data-arch-node=core]')", 15000),
        eval_("[...document.querySelectorAll('#modalTabs [role=tab]')].map(b=>b.textContent)", "tabs"),
        eval_("(ARCH.view.state.snapshot.nodes||[]).map(n=>n.id)", "nodes"),
        shot("sandbox-architecture.png"),
        click("[data-architecture-page] [data-arch-menu-btn=core]"),
        wait("!!document.querySelector('[data-arch-menu=configure]')"), click("[data-arch-menu=configure]"),
        wait("!!document.querySelector('.bcp-win [data-bcp-radio=delegation]')", 10000),
        shot("sandbox-core-window.png"),
        eval_("document.querySelector('.bcp-win').getAttribute('aria-label')||document.querySelector('.bcp-win').textContent.slice(0,40)", "window"),
        key("Escape"), wait("document.querySelector('.bcp-win')===null"),
        eval_("[SET.open,SET.section]", "after_escape"),
        click("#modalTabs [data-section=subagents]"),
        wait("!!document.querySelector('[data-sar-route]')", 20000),
        shot("sandbox-subagents.png"),
        eval_("[SET.section,document.querySelectorAll('[data-sar-role]').length,!!document.querySelector('[data-sar-route]')]", "subagents"),
    ]}]
    done = subprocess.run([node, str(HARNESS), UI + "/", chrome, json.dumps(plan)], capture_output=True, text=True,
                          encoding="utf-8", timeout=240)
    if done.returncode != 0:
        say(f"(d) harnais en échec : {done.stderr[:600]}")
        return 1
    result = json.loads(done.stdout)
    actions = result["steps"][0]["actions"]
    values = {a.get("id"): a.get("value") for a in actions if a.get("id")}
    waits = [a for a in actions if a.get("a") == "wait"]
    say(f"(d) attentes tenues : {sum(1 for w in waits if w['ok'])}/{len(waits)}")
    for name in ("tabs", "nodes", "window", "after_escape", "subagents"):
        say(f"(d) {name} = {values.get(name)}")
    say(f"(d) requêtes : {sorted({(r['method'], r['path']) for r in result['requests'] if r['path'].startswith('/api/')})}")
    say(f"(d) erreurs console : {result['console']}")
    say(f"(d) captures : {[p.name for p in sorted(SHOTS.glob('sandbox-*.png'))]}")
    return 0 if all(w["ok"] for w in waits) else 1


if __name__ == "__main__":
    raise SystemExit(main())

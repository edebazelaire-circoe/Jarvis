"""Preuves S08 en bac à sable : un Control Center lancé depuis le worktree arch-s08, ports 27653/27654, racines au
scratchpad, variables JARVIS_* héritées retirées. Démarre, sonde, prouve, arrête SEULEMENT le PID lancé (sans /T),
après avoir arrêté par l'API le CLI cerveau qu'il a lui-même lancé. Jamais le JARVIS vivant.

Phases (une par appel, l'état du bac à sable persiste entre elles ; `prep` seule le recrée) :
  prep      bac à sable neuf : ancien control-center-settings.json, catalogue de modèles figé (fixture), copie « avant »
  graph     scénarios 1-5 du graphe (snapshot réel, liaisons basculables relues par le runtime, verrouillée, création)
  brain1    cerveau Core, vrai CLI `claude` : modèle + `never` (argv, outils du CLI), puis `proactive`, `exploratory`
  brain2    vrai CLI en `standard` (prompt), `never` posé à chaud -> le hook refuse un vrai appel Agent
  roles     politique du rôle qa -> vrai appel Agent [general] [qa] -> le hook choisit le candidat ; autres rôles intacts
  browser   page réelle : onglets, alias, contrôles interdits, clavier, sept rôles pilotés par les données, captures
  migrate   comparaison du fichier de réglages « avant » / « après » (aucune clé perdue)
"""
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

WORKTREE = Path(r"C:\Projects\jarvis\arch-s08")
BASE = Path(r"C:\Users\Clarice\AppData\Local\Temp\claude\C--Projects-jarvis-jarvis\05b93d8a-1916-4b86-866a-f10f71884561\scratchpad\base-ad1e")
PY = Path(r"C:\Projects\jarvis\jarvis\.venv\Scripts\python.exe")
SCRATCH = Path(r"C:\Users\Clarice\AppData\Local\Temp\claude\C--Projects-jarvis-jarvis\05b93d8a-1916-4b86-866a-f10f71884561\scratchpad")
SANDBOX = SCRATCH / "s08-sandbox"
SHOTS = SCRATCH / "s08-shots"
RUNTIME = SANDBOX / "runtime"
UI = "http://127.0.0.1:27654"
FAKE_KEY = "sk-ant-s08-fixture-not-a-real-key"  # fixture : jamais envoyée à un fournisseur (catalogue figé en cache)
FIXTURE_MODELS = ["claude-haiku-4-5", "claude-sonnet-4-5"]
LIVE_PORTS = {"17653", "17654"}
LOG: list[str] = []
RESULT: dict = {}


def say(line: str) -> None:
    LOG.append(line)
    print(line, flush=True)


def http(method: str, path: str, body: object | None = None, timeout: float = 60) -> tuple[int, object]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(UI + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw or "null")
        except ValueError:
            return exc.code, raw


def conn(snapshot: dict, cid: str) -> dict:
    return next(c for c in snapshot["connections"] if c["id"] == cid)


def settings_now() -> dict:
    return json.loads((RUNTIME / "control-center-settings.json").read_text(encoding="utf-8"))


def trace_rows(kinds: set[str] | None = None, since: int = 0) -> list[dict]:
    path = RUNTIME / "trace.jsonl"
    rows = []
    if not path.is_file():
        return rows
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if i < since:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if kinds is None or row.get("kind") in kinds:
            rows.append(row)
    return rows


def trace_len() -> int:
    path = RUNTIME / "trace.jsonl"
    return len(path.read_text(encoding="utf-8").splitlines()) if path.is_file() else 0


def env_for_sandbox() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("JARVIS_")}
    env.update(JARVIS_DATA_ROOT=str(SANDBOX / "data"), JARVIS_RUNTIME_DIR=str(RUNTIME), JARVIS_CORE_PORT="27653",
               JARVIS_UI_PORT="27654", JARVIS_VISUALIZER_ENABLED="0", PYTHONIOENCODING="utf-8")
    return env


def ports_free() -> bool:
    import socket
    for port in (27653, 27654):
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return False
    return True


class ControlCenterSandbox:
    def __enter__(self):
        if not ports_free():
            raise SystemExit("ports 27653/27654 occupés : rien n'est lancé")
        self.env = env_for_sandbox()
        assert not any(self.env.get(k, "").endswith(p) for k in ("JARVIS_CORE_PORT", "JARVIS_UI_PORT") for p in LIVE_PORTS)
        self.out = open(SANDBOX / "control-center.log", "a", encoding="utf-8")
        self.proc = subprocess.Popen([str(PY), "-m", "jarvis", "control-center"], cwd=WORKTREE, env=self.env,
                                     stdout=self.out, stderr=subprocess.STDOUT)
        say(f"control-center lancé : PID {self.proc.pid}, cwd {WORKTREE}, UI {UI}, runtime {RUNTIME}")
        for _ in range(160):
            try:
                urllib.request.urlopen(UI + "/api/status", timeout=2).read()
                return self
            except (urllib.error.URLError, OSError):
                if self.proc.poll() is not None:
                    raise SystemExit("le Control Center s'est arrêté au démarrage, voir control-center.log")
                time.sleep(0.5)
        raise SystemExit("Control Center injoignable après 80 s")

    def __exit__(self, *exc):
        try:
            status, body = http("POST", "/api/agent/kill", {}, timeout=60)  # le CLI cerveau que CE Control Center a lancé
            say(f"arrêt du CLI cerveau par l'API du bac à sable -> {status}")
        except Exception as error:  # noqa: BLE001
            say(f"arrêt du CLI cerveau : {type(error).__name__}")
        self.proc.terminate()  # TerminateProcess sur CE PID seulement, pas d'arbre (/T)
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.out.close()
        say(f"control-center arrêté : PID {self.proc.pid}, code {self.proc.returncode}")
        return False


def cmdline(pid: int) -> str:
    script = f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine"
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                          text=True, encoding="utf-8", timeout=30).stdout.strip()


def argv_value(line: str, flag: str) -> str | None:
    """Valeur d'une option dans une ligne de commande Windows (guillemets simples gérés)."""
    import shlex
    try:
        parts = shlex.split(line, posix=False)
    except ValueError:
        return None
    if flag not in parts:
        return None
    value = parts[parts.index(flag) + 1]
    return value.strip('"')


def disallowed(line: str) -> list[str]:
    import shlex
    parts = shlex.split(line, posix=False)
    if "--disallowedTools" not in parts:
        return []
    out = []
    for item in parts[parts.index("--disallowedTools") + 1:]:
        if item.startswith("--"):
            break
        out.append(item.strip('"'))
    return out


def launch_brain(label: str, *, new_conversation: bool = True) -> dict:
    """Relance le CLI cerveau de CE Control Center (conversation neuve) et relève ce qui a vraiment été lancé."""
    since = trace_len()
    # Sans Core dans le bac à sable, une conversation neuve (`restart` + `new_conversation`) est refusée
    # (`core_unreachable`) : arrêt puis démarrage du CLI de CE Control Center, qui relit réglages et tendance.
    http("POST", "/api/agent/kill", {}, timeout=60)
    status, body = http("POST", "/api/agent/start", {}, timeout=120)
    started = [r for r in trace_rows({"agent.start"}, since) if (r.get("data") or {}).get("pid")]
    if status != 200 or not started:
        say(f"[{label}] relance -> {status} ; agent.start absent : {str(body)[:300]}")
        return {}
    data = started[-1]["data"]
    pid = int(data["pid"])
    line = cmdline(pid)
    prompt_file = argv_value(line, "--append-system-prompt-file")
    prompt = Path(prompt_file).read_text(encoding="utf-8") if prompt_file and Path(prompt_file).is_file() else None
    launched = json.loads((RUNTIME / "brain-delegation-launched.json").read_text(encoding="utf-8"))
    info = {"pid": pid, "model_arg": argv_value(line, "--model"), "disallowed": disallowed(line),
            "has_settings_hook": "routing-hook" in line, "trace_delegation": data.get("delegation"),
            "trace_spawn_tools_removed": data.get("spawn_tools_removed"), "trace_model": data.get("model"),
            "launched_file": {k: launched.get(k) for k in ("delegation", "pid")}, "prompt_len": len(prompt or ""),
            "prompt_file": prompt_file}
    say(f"[{label}] CLI lancé PID {pid} : --model={info['model_arg']} --disallowedTools={info['disallowed']} "
        f"hook={info['has_settings_hook']} ; agent.start delegation={info['trace_delegation']} "
        f"spawn_tools_removed={info['trace_spawn_tools_removed']} model={info['trace_model']} ; "
        f"brain-delegation-launched.json={info['launched_file']} ; consigne {info['prompt_len']} car.")
    info["prompt"] = prompt
    return info


def ask(label: str, text: str, timeout_s: float = 240) -> dict:
    since = trace_len()
    status, body = http("POST", "/api/agent/ask", {"text": text, "timeout_s": timeout_s}, timeout=timeout_s + 30)
    rows = trace_rows(None, since)
    reply = body.get("text") if isinstance(body, dict) else None
    say(f"[{label}] ask -> {status} ; réponse : « {str(reply or body)[:240]} »")
    return {"status": status, "body": body, "rows": rows}


def init_tools(rows: list[dict]) -> tuple[list[str] | None, str | None]:
    for row in rows:
        data = row.get("data") or {}
        if row.get("kind") == "agent.event" and data.get("type") == "system" and data.get("subtype") == "init":
            return list(data.get("tools") or []) if "tools" in data else None, data.get("model")
    return None, None


def tool_uses(rows: list[dict]) -> list[dict]:
    uses = []
    for row in rows:
        data = row.get("data") or {}
        if row.get("kind") != "agent.event" or data.get("type") != "assistant":
            continue
        for block in ((data.get("message") or {}).get("content") or []):
            if isinstance(block, dict) and block.get("type") == "tool_use":
                uses.append({"name": block.get("name"), "id": block.get("id"),
                             "description": (block.get("input") or {}).get("description"),
                             "model": (block.get("input") or {}).get("model"),
                             "parent": data.get("parent_tool_use_id")})
    return uses


def assistant_models(rows: list[dict]) -> list[tuple[str | None, str | None]]:
    seen = []
    for row in rows:
        data = row.get("data") or {}
        if row.get("kind") == "agent.event" and data.get("type") == "assistant":
            item = (data.get("parent_tool_use_id"), (data.get("message") or {}).get("model"))
            if item not in seen:
                seen.append(item)
    return seen


# ----------------------------------------------------------------------------------------------------------- prep

OLD_SETTINGS = {
    # Forme d'un poste réel avant la tâche (clés écrites par `POST /api/settings` sur main ad1e7f4d) ; aucun secret réel.
    "agent_cli": "claude",
    "agent_cli_settings": {"claude": {"command": "claude", "model": "", "permission_mode": "bypassPermissions"},
                           "codex": {"command": "codex", "model": "", "permission_mode": "default"}},
    "agent_routing": {"enabled": False, "profiles": {
        "general": {"candidates": [{"agent": "claude", "model": "claude-sonnet-4-5"}]},
        "code": {"candidates": [{"agent": "claude", "model": "claude-sonnet-4-5"}], "allow_general_fallback": True}}},
    "agent_behavior": {"response_verbosity": "concise", "politeness": "formal"},
    "agenda_reminders": {"enabled": True, "lead_minutes": 10},
    "voice_architecture": {"schema_version": 1, "compatibility": None, "config": {
        "architecture": "duplex", "conversation_model": {"provider_id": "openai", "model_id": "gpt-live-1"}}},
    "realtime_voice": "cedar", "voice_turn_mode": "auto", "manual_wake_key": "f9", "active_timeout_s": "90",
    "audio_input_device": "", "audio_output_device": "", "voice_stack": "openai", "voice_arch": "",
    "anthropic_api_key": FAKE_KEY,
    "scene": {"enabled": False},
    "barehands": {"enabled": False},
}


def prep() -> int:
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX)  # bac à sable de cette preuve seulement (aucune base du JARVIS vivant)
    (SANDBOX / "data").mkdir(parents=True)
    RUNTIME.mkdir(parents=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    (RUNTIME / "control-center-settings.json").write_text(json.dumps(OLD_SETTINGS, indent=2), encoding="utf-8")
    shutil.copy2(RUNTIME / "control-center-settings.json", SANDBOX / "settings-before.json")
    sys.path.insert(0, str(WORKTREE))
    from jarvis.runtime.model_catalog import ModelCatalog
    catalog = {"anthropic": {"provider": "anthropic", "fetched_at": time.time(),
                             "models": [{"id": m, "label": m, "roles": ["text"]} for m in FIXTURE_MODELS],
                             "_credential_fingerprint": ModelCatalog._credential_fingerprint("anthropic", FAKE_KEY)}}
    (RUNTIME / "model-catalog.json").write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    say(f"prep : bac à sable neuf {SANDBOX} ; réglages anciens (duplex gpt-live-1, agent_routing Dupliqué) ; "
        f"catalogue figé anthropic {FIXTURE_MODELS} (empreinte de la clé fixture)")
    return 0


# ---------------------------------------------------------------------------------------------------------- graph

def graph() -> int:
    sys.path.insert(0, str(WORKTREE))
    from jarvis.runtime.live_delegation import LiveDelegationController
    from jarvis.runtime.tool_brain_wiring import resolve_mode
    from jarvis.runtime.voice_architecture_config import load_voice_architecture
    from jarvis.runtime.voice_composition import resolve_voice_composition
    with ControlCenterSandbox():
        status, snap = http("GET", "/api/architecture")
        composition = resolve_voice_composition(settings_now(), environ={})
        say(f"(1) GET /api/architecture -> {status} ; architecture {snap['voice_architecture']['id']} "
            f"(composition runtime : {type(composition.selection.config).__name__ if composition else None}, stack {composition.stack_id if composition else None}) ; nœuds "
            f"{[(n['id'], n['state']['state'] if isinstance(n.get('state'), dict) else n.get('state')) for n in snap['nodes']]}")
        expected = ["mic", "voice", "core", "tool_brain", "subagents", "speakers"]  # duplex : pas de Luna
        say(f"(1) nœuds attendus pour duplex (docs/architecture-graph.md § 2) {expected} : "
            f"{'identiques' if [n['id'] for n in snap['nodes']] == expected else 'DIFFÉRENTS'}")
        say("(1) liaisons : " + "; ".join(f"{c['id']} {c['mutability']} enabled={c['enabled']}" for c in snap["connections"]))

        def delegation_path() -> str:
            config = load_voice_architecture(settings_now(), environ={}).config
            return LiveDelegationController(object(), brain_orchestration=config.brain_orchestration)._path

        before = delegation_path()
        status, off = http("POST", "/api/architecture/connections/voice.delegate->core.request",
                           {"base_revision": snap["revision"], "enabled": False})
        after = delegation_path()
        switch = RUNTIME / ".voice_switch_request"
        say(f"(2) coupure voice.delegate->core.request -> {status} ok={off['ok']} changed={off['changed']} ; chemin de "
            f"délégation Live construit par le runtime depuis les réglages relus : {before} -> {after} ; demande de "
            f"bascule Voice déposée={switch.is_file()}")
        status, back = http("POST", "/api/architecture/connections/voice.delegate->core.request",
                            {"base_revision": off["snapshot"]["revision"], "enabled": True})
        say(f"(3) remise -> {status} changed={back['changed']} ; chemin : {delegation_path()}")

        mode_before = resolve_mode(settings_now(), {})
        tb = conn(back["snapshot"], "core.events->tool_brain.wake")
        status, on = http("POST", "/api/architecture/connections/core.events->tool_brain.wake",
                          {"base_revision": back["snapshot"]["revision"], "enabled": not tb["enabled"]})
        mode_on = resolve_mode(settings_now(), {})
        status2, restore = http("POST", "/api/architecture/connections/core.events->tool_brain.wake",
                                {"base_revision": on["snapshot"]["revision"], "enabled": tb["enabled"]})
        say(f"(2/3) Tool Brain core.events->tool_brain.wake : {status} puis {status2} ; mode lu par "
            f"tool_brain_wiring.resolve_mode (démarrage de Core) : {mode_before[0].value} -> {mode_on[0].value} -> "
            f"{resolve_mode(settings_now(), {})[0].value} ; pending après bascule={conn(on['snapshot'], 'core.events->tool_brain.wake').get('pending')}")

        cur = restore["snapshot"]["revision"]
        file_before = (RUNTIME / "control-center-settings.json").read_bytes()
        status, locked = http("POST", "/api/architecture/connections/mic.audio_out->voice.audio_in",
                              {"base_revision": cur, "enabled": False})
        _, again = http("GET", "/api/architecture")
        say(f"(4) liaison verrouillée mic->voice -> {status} code={locked['code']} raison=« {locked['reason']} » ; "
            f"réglages inchangés={file_before == (RUNTIME / 'control-center-settings.json').read_bytes()} ; révision "
            f"inchangée={again['revision'] == cur} ; enabled={conn(again, 'mic.audio_out->voice.audio_in')['enabled']}")
        status, gov = http("POST", "/api/architecture/connections/core.agents->subagents.spawn",
                           {"base_revision": cur, "enabled": False})
        say(f"(4) liaison gouvernée core->subagents -> {status} code={gov['code']} raison=« {gov['reason']} »")
        status, created = http("POST", "/api/architecture/connections", {
            "base_revision": cur, "source": {"node": "speakers", "port": "audio_in"},
            "target": {"node": "mic", "port": "audio_out"}, "channel": "audio"})
        status2, created2 = http("POST", "/api/architecture/connections", {
            "base_revision": cur, "source": {"node": "core", "port": "speech"},
            "target": {"node": "tool_brain", "port": "wake"}, "channel": "event"})
        _, after_create = http("GET", "/api/architecture")
        say(f"(5) création invalide (sens) -> {status} code={created['code']} ; création sans mécanisme -> {status2} "
            f"code={created2['code']} raison=« {created2['reason']} » ; liaisons inchangées="
            f"{len(after_create['connections']) == len(again['connections'])} ; réglages inchangés="
            f"{file_before == (RUNTIME / 'control-center-settings.json').read_bytes()}")
        status, layout = http("GET", "/api/architecture/layout")
        say(f"(5) disposition (interface seule) -> {status} ; fichier séparé architecture-layout.json : "
            f"{(RUNTIME / 'architecture-layout.json').exists()}")
        kinds: dict = {}
        for row in trace_rows():
            k = row.get("kind") or ""
            if k.split(".")[0] in {"architecture", "voice"}:
                kinds[k] = kinds.get(k, 0) + 1
        say(f"journal : {kinds}")
    return 0


# --------------------------------------------------------------------------------------------------------- brain

SPAWN_REQUEST = ("Test de bac à sable : lance maintenant exactement UN sous-agent avec l'outil Agent "
                 "(subagent_type general-purpose, description « [general] [qa] Vérifier une addition »), "
                 "consigne du sous-agent : « Réponds seulement le résultat de 2+2. ». Ne fais rien d'autre et rapporte "
                 "sa réponse en une phrase. Si l'outil Agent n'existe pas ou est refusé, dis-le en une phrase.")


def patch_core(field: str, value: object) -> tuple[int, dict]:
    _, core = http("GET", "/api/brains/core/config")
    return http("PATCH", "/api/brains/core/config", {"base_revision": core["revision"], field: value})


def brain1() -> int:
    with ControlCenterSandbox():
        status, core = http("GET", "/api/brains/core/config")
        choices = [(c["value"], c.get("available")) for c in core["fields"]["model"]["choices"]]
        say(f"(6) GET /api/brains/core/config -> {status} ; provider={core['fields']['provider']['value']} "
            f"model={core['fields']['model']['value'] or '(défaut)'} delegation={core['fields']['delegation']['value']} "
            f"catalog={core['catalog']['status']} ; choix servis={choices}")
        status, body = patch_core("model", "claude-haiku-4-5")
        store = settings_now()["agent_cli_settings"]["claude"]["model"]
        say(f"(6) PATCH model=claude-haiku-4-5 -> {status} changed={body.get('changed')} applies={body.get('applies')} ; "
            f"agent_cli_settings.claude.model={store}")
        status, body = patch_core("delegation", "never")
        say(f"(7) PATCH delegation=never -> {status} ; brain-config.json="
            f"{json.loads((RUNTIME / 'brain-config.json').read_text(encoding='utf-8'))['brains']['core']['delegation']}")
        never = launch_brain("never")
        result = ask("never", SPAWN_REQUEST)
        tools, model = init_tools(result["rows"])
        uses = tool_uses(result["rows"])
        say(f"(6/7) CLI réel en never : modèle annoncé par le CLI (init)={model} ; outils de lancement dans l'init du CLI={sorted({'Agent','Task'} & set(tools)) if tools is not None else None} ; Agent="
            f"{('Agent' in tools) if tools is not None else 'init non journalisé'} Task={('Task' in tools) if tools is not None else '-'} ; "
            f"appels d'outil={[(u['name'], u['description']) for u in uses]}")
        RESULT["never"] = {k: v for k, v in never.items() if k != "prompt"}
        RESULT["never"].update(init_model=model, init_has_agent=(None if tools is None else "Agent" in tools), uses=uses)
        prompts = {"never": never.get("prompt")}
        for level in ("proactive", "exploratory"):
            status, _ = patch_core("delegation", level)
            info = launch_brain(level)
            prompts[level] = info.get("prompt")
            RESULT[level] = {k: v for k, v in info.items() if k != "prompt"}
        (SANDBOX / "prompts-brain1.json").write_text(json.dumps(prompts, ensure_ascii=False, indent=1), encoding="utf-8")
        status, _ = patch_core("delegation", "standard")
        say(f"remise delegation=standard -> {status}")
    (SANDBOX / "result-brain1.json").write_text(json.dumps(RESULT, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def brain2() -> int:
    with ControlCenterSandbox():
        std = launch_brain("standard")
        (SANDBOX / "prompt-standard.txt").write_text(std.get("prompt") or "", encoding="utf-8")
        RESULT["standard"] = {k: v for k, v in std.items() if k != "prompt"}
        status, body = patch_core("delegation", "never")
        say(f"(7) never posé à chaud (CLI vivant lancé en standard, outil Agent présent) -> {status}")
        result = ask("hook-never", SPAWN_REQUEST)
        tools, model = init_tools(result["rows"])
        refused = [r for r in result["rows"] if r.get("kind") == "agent.spawn_refused"]
        uses = tool_uses(result["rows"])
        say(f"(7) CLI standard : outil de lancement (Agent/Task) dans l'init={sorted({'Agent','Task'} & set(tools)) if tools is not None else 'init non journalisé'} ; "
            f"appels d'outil={[(u['name'], u['id']) for u in uses]} ; agent.spawn_refused="
            f"{[((r.get('data') or {}).get('code'), (r.get('data') or {}).get('tool_use_id')) for r in refused]}")
        RESULT["hook_never"] = {"init_has_agent": None if tools is None else "Agent" in tools, "uses": uses,
                                "refused": [r.get("data") for r in refused]}
        status, _ = patch_core("delegation", "standard")
        say(f"remise delegation=standard -> {status}")
    (SANDBOX / "result-brain2.json").write_text(json.dumps(RESULT, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


# --------------------------------------------------------------------------------------------------------- roles

def offline_hook(description: str, env: dict) -> dict:
    event = {"hook_event_name": "PreToolUse", "session_id": "s08-sandbox", "tool_name": "Agent",
             "tool_use_id": "toolu_s08_" + str(int(time.time() * 1000)),
             "tool_input": {"description": description, "prompt": "Réponds seulement 4.", "subagent_type": "general-purpose"}}
    since = trace_len()
    hook = subprocess.run([str(PY), "-m", "jarvis", "routing-hook", "--runtime-root", str(RUNTIME)], cwd=WORKTREE,
                          env=env, input=json.dumps(event), capture_output=True, text=True, encoding="utf-8", timeout=120)
    decided = [r for r in trace_rows({"agent.routing.decided"}, since)]
    data = (decided[-1].get("data") or {}) if decided else {}
    out = hook.stdout.strip()
    try:
        parsed = json.loads(out) if out else {}
    except ValueError:
        parsed = {}
    updated = ((parsed.get("hookSpecificOutput") or {}).get("updatedInput") or {})
    return {"code": hook.returncode, "decision": (parsed.get("hookSpecificOutput") or {}).get("permissionDecision"),
            "model_out": updated.get("model"), "agent_model": data.get("agent_model"), "role_id": data.get("role_id"), "provenance": data.get("provenance"),
            "reason": data.get("reason"), "model": data.get("model"), "level": decided[-1].get("level") if decided else None}


def roles() -> int:
    with ControlCenterSandbox() as cc:
        status, before = http("GET", "/api/subagent-role-routing")
        view = lambda snap: {r["role_id"]: (r["provenance"], [(c["agent"], c["model"], c["available"]) for c in r["candidates"]],
                                            (r.get("preview") or {}).get("kind") or r.get("preview")) for r in snap["roles"]}
        say(f"(9) GET /api/subagent-role-routing -> {status} ; {len(before['roles'])} rôles ; avant : {view(before)}")
        hooks_before = {d: offline_hook(d, cc.env) for d in ("[general] [qa] Relire", "[code] [coder] Corriger")}
        say(f"(9) hook hors ligne avant : {hooks_before}")
        # Cerveau sur haiku (phase brain1) ; le rôle qa sur sonnet : le modèle du sous-agent se distingue de celui du cerveau.
        status, put = http("PUT", "/api/subagent-role-routing/qa", {
            "base_revision": before["revision"], "allow_general_fallback": False,
            "candidates": [{"agent": "claude", "model": "claude-sonnet-4-5"}]})
        after = put["snapshot"]
        changed = {k for k in view(before) if view(before)[k] != view(after)[k]}
        say(f"(9) PUT qa=[claude/claude-sonnet-4-5] -> {status} ok={put.get('ok')} ; rôles dont la vue change : {sorted(changed)} ; "
            f"qa après : {view(after)['qa']}")
        hooks_after = {d: offline_hook(d, cc.env) for d in ("[general] [qa] Relire", "[code] [coder] Corriger")}
        say(f"(9) hook hors ligne après : {hooks_after}")
        status, stale = http("PUT", "/api/subagent-role-routing/qa", {
            "base_revision": before["revision"], "allow_general_fallback": False,
            "candidates": [{"agent": "claude", "model": "claude-haiku-4-5"}]})
        say(f"(9) PUT révision périmée -> {status} code={stale.get('code')}")
        # (10) un candidat enregistré hors catalogue reste visible avec sa raison
        status, ghost = http("PUT", "/api/subagent-role-routing/research", {
            "base_revision": after["revision"], "allow_general_fallback": True,
            "candidates": [{"agent": "claude", "model": "claude-retired-9"}, {"agent": "claude", "model": "claude-sonnet-4-5"}]})
        arch = next((r for r in (ghost.get("snapshot") or {}).get("roles", []) if r["role_id"] == "research"), None)
        say(f"(10) PUT research avec un modèle hors catalogue -> {status} ok={ghost.get('ok')} code={ghost.get('code')} ; candidats : "
            f"{[(c['model'], c['available'], c.get('unavailable_reason')) for c in (arch or {}).get('candidates', [])]}")
        if ghost.get("ok"):
            status, restored = http("DELETE", f"/api/subagent-role-routing/research?base_revision={ghost['snapshot']['revision']}")
            say(f"(10) restauration de l'héritage (DELETE) -> {status} ; provenance="
                f"{next(r for r in restored['snapshot']['roles'] if r['role_id'] == 'research')['provenance']}")
        # vrai CLI en tendance proactive (scénario 8) : un vrai appel Agent [general] [qa], le hook choisit le candidat
        status, _ = patch_core("delegation", "proactive")
        say(f"(8) delegation=proactive -> {status}")
        info = launch_brain("roles")
        result = ask("roles", SPAWN_REQUEST, timeout_s=300)
        decided = [r for r in result["rows"] if r.get("kind") == "agent.routing.decided"]
        uses = tool_uses(result["rows"])
        models = assistant_models(result["rows"])
        applied = [r.get("data") for r in result["rows"] if r.get("kind") == "agent.role_applied"]
        say(f"(9) vrai appel : outils={[(u['name'], u['description'], u['model']) for u in uses]} ; décisions du hook="
            f"{[((r.get('data') or {}).get('role_id'), (r.get('data') or {}).get('provenance'), (r.get('data') or {}).get('reason'), (r.get('data') or {}).get('model'), r.get('level')) for r in decided]} ; "
            f"agent.role_applied={[(a or {}).get('role_id') for a in applied]} ; modèles des messages (parent, modèle)={models}")
        RESULT["roles"] = {"before": view(before), "after": view(after), "changed": sorted(changed),
                           "hooks_before": hooks_before, "hooks_after": hooks_after, "uses": uses,
                           "decided": [r.get("data") for r in decided], "models": models, "launch": {k: v for k, v in info.items() if k != "prompt"}}
        status, _ = patch_core("delegation", "standard")
        say(f"remise delegation=standard -> {status}")
        # remettre qa en héritage
        _, cur = http("GET", "/api/subagent-role-routing")
        status, _ = http("DELETE", f"/api/subagent-role-routing/qa?base_revision={cur['revision']}")
        say(f"restauration qa -> {status}")
    (SANDBOX / "result-roles.json").write_text(json.dumps(RESULT, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


# ------------------------------------------------------------------------------------------------------- browser

def browser() -> int:
    sys.path.insert(0, str(WORKTREE))
    from tests.unit.test_wake_word_settings_browser import CHROME_CANDIDATES, HARNESS, click, eval_, key, open_settings, wait
    from tests.unit.test_architecture_agents_settings_browser import GEOMETRY, IN_PANEL, OPEN_CORE, TOUR
    chrome = next((str(c) for c in CHROME_CANDIDATES if c.is_file()), None)
    node = shutil.which("node")
    if not chrome or not node:
        say("navigateur : Chrome ou node absent")
        return 1
    shot = lambda name: {"a": "shot", "path": str(SHOTS / name)}  # noqa: E731
    focused = "(()=>{const e=document.activeElement;return e?[e.tagName,e.getAttribute('data-arch-node')||e.getAttribute('data-arch-menu')||e.getAttribute('data-arch-menu-btn')||e.id||e.className]:null})()"
    open_cat = [wait("!!document.getElementById('openSettings')"), click("#dockMore"), *open_settings(),
                click("#settingsCategories [data-category=agents_models]"),
                wait("!!document.querySelector('[data-architecture-page] [data-arch-node=core]')", 15000)]
    plan = [
        {"width": 1440, "height": 900, "actions": [
            *open_cat, shot("s08-architecture.png"),
            eval_(TOUR, "tour"),
            # liens profonds
            eval_("(async()=>{const p=ms=>new Promise(r=>setTimeout(r,ms)),o={};for(const id of ['main_agent','subagent_models','memory']){selectTab('voice_audio');await p(200);selectTab(id);await p(600);o[id]=[SET.category,SET.section]}return o})()", "deep"),
            eval_("[SET.open,SET.category,SET.section]", "after_deep"),
            click("#settingsCategories [data-category=agents_models]"),
            eval_("(selectTab('architecture'),0)"),
            wait("!!document.querySelector('[data-architecture-page] [data-arch-node=core]')", 15000),
            wait("new Promise(r=>setTimeout(()=>r(true),2000))", 5000),  # le canevas relit le graphe puis se redessine
            # clavier : focus sur le nœud Core, Maj+F10 ouvre son menu, flèches, Entrée « Configurer… »
            eval_("(()=>{const n=document.querySelector('[data-architecture-page] [data-arch-node=core]');if(n)n.focus();return !!n})()", "node_focusable"),
            eval_(focused, "focus_node"),
            key("F10", shift=True), wait("!!document.querySelector('[data-arch-menu=configure]')", 4000),
            eval_(focused, "focus_menu"),
            key("Escape"), wait("!document.querySelector('[data-arch-menu=configure]')", 4000),
            wait("new Promise(r=>setTimeout(()=>r(true),300))", 2000),
            eval_("[" + focused + ",SET.open,SET.section]", "after_menu_escape"),
            eval_("(()=>{const n=document.querySelector('[data-architecture-page] [data-arch-node=core]');if(n)n.focus();return !!n})()", "node_focusable"),
            key("F10", shift=True), wait("!!document.querySelector('[data-arch-menu=configure]')", 4000),
            eval_("(()=>{const items=[...document.querySelectorAll('[data-arch-menu] , [data-arch-menu]')];return [...document.querySelectorAll('[role=menuitem]')].map(e=>e.textContent.trim())})()", "menu_items"),
            eval_(focused, "focus_menu_2"), key("Enter"),
            wait("!!document.querySelector('.bcp-win [data-bcp-radio=delegation]')", 10000),
            eval_(GEOMETRY, "geometry"), eval_(IN_PANEL, "focus_in_window"),
            key("Tab"), key("Tab"), key("Tab"), key("Tab"), key("Tab", shift=True), eval_(IN_PANEL, "tab_kept"),
            shot("s08-core-window.png"),
            key("Escape"), wait("document.querySelector('.bcp-win')===null", 4000),
            eval_("[" + focused + ",SET.open,SET.section]", "after_window_escape"),
            # menu contextuel au clic droit sur un nœud
            eval_("(()=>{const n=document.querySelector('[data-architecture-page] [data-arch-node=tool_brain]');const r=n.getBoundingClientRect();n.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:r.left+20,clientY:r.top+20}));return !!document.querySelector('[data-arch-menu=configure]')})()", "context_menu"),
            key("Escape"),
            # onglet Sous-agents : rôles pilotés par les données
            click("#modalTabs [data-section=subagents]"),
            wait("!!document.querySelector('[data-sar-route]')", 20000),
            eval_("(async()=>{const r=await (await fetch('/api/subagent-roles')).json();const reg=(r.roles||r).map(x=>x.id||x.role_id);"
                  "const dom=[...document.querySelectorAll('[data-sar-role]')].map(e=>e.getAttribute('data-sar-role'));"
                  "const rr=await (await fetch('/api/subagent-role-routing')).json();return {registry:reg,dom:[...new Set(dom)],routing:rr.roles.map(x=>x.role_id)}})()", "roles"),
            shot("s08-subagents.png"),
        ]},
    ]
    for step in plan:  # une évaluation qui lève est consignée comme valeur, le parcours continue
        for action in step["actions"]:
            if action.get("a") == "eval":
                action["expr"] = "(async()=>{try{return await (" + action["expr"] + ")}catch(e){return 'ERR: '+e.message}})()"
    done = subprocess.run([node, str(HARNESS), UI + "/", chrome, json.dumps(plan)], capture_output=True, text=True,
                          encoding="utf-8", timeout=400)
    if done.returncode != 0:
        say(f"navigateur : harnais en échec : {done.stderr[:800]}")
        return 1
    result = json.loads(done.stdout)
    actions = result["steps"][0]["actions"]
    values = {a.get("id"): a.get("value") for a in actions if a.get("id")}
    waits = [a for a in actions if a.get("a") == "wait"]
    say(f"navigateur : attentes tenues {sum(1 for w in waits if w['ok'])}/{len(waits)} ; échouées : {[w.get('expr') for w in waits if not w['ok']]}")
    tour = values.get("tour") or {}
    say(f"(12) onglets de la catégorie : {tour.get('categories', {}).get('agents_models')} ; interdits sur architecture : "
        f"{(tour.get('sections') or {}).get('architecture', {}).get('forbidden')} / libellés {(tour.get('sections') or {}).get('architecture', {}).get('forbiddenLabels')} ; "
        f"sur subagents : {(tour.get('sections') or {}).get('subagents', {}).get('forbidden')} / {(tour.get('sections') or {}).get('subagents', {}).get('forbiddenLabels')}")
    flat = [label for labels in (tour.get("categories") or {}).values() for label in labels]
    say(f"(12) « Brains » dans un onglet : {'Brains' in flat} ; « Agent principal » : {'Agent principal' in flat} ; "
        f"Runtime & CLI porte commande/permission/mode/profils/inventaire : "
        f"{[(tour.get('sections') or {}).get('runtime_cli', {}).get(k) for k in ('cmd', 'perm', 'mode', 'routing', 'catalog')]}")
    say(f"liens profonds : {values.get('deep')} ; anciens id (tour) : {tour.get('legacy')}")
    for name in ("after_deep", "node_focusable", "focus_node", "focus_menu", "after_menu_escape", "focus_menu_2", "menu_items", "geometry", "focus_in_window", "tab_kept",
                 "after_window_escape", "context_menu", "roles"):
        say(f"clavier/données : {name} = {values.get(name)}")
    say(f"requêtes /api : {sorted({(r['method'], r['path']) for r in result['requests'] if r['path'].startswith('/api/')})}")
    say(f"erreurs console : {result['console']}")
    RESULT["browser"] = {k: values.get(k) for k in values}
    (SANDBOX / "result-browser.json").write_text(json.dumps(RESULT, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if all(w["ok"] for w in waits) else 1


def browser_phase() -> int:
    with ControlCenterSandbox():
        return browser()


# ------------------------------------------------------------------------------------------------------- migrate

def leaves(value, prefix=""):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from leaves(v, f"{prefix}.{k}" if prefix else k)
    else:
        yield prefix, value


def migrate() -> int:
    before = json.loads((SANDBOX / "settings-before.json").read_text(encoding="utf-8"))
    with ControlCenterSandbox():
        status, served = http("GET", "/api/settings")
        # Enregistrer de Comportement à pied, comme la page : la charge complète du brouillon, valeurs inchangées.
        sys.path.insert(0, str(WORKTREE))
        status_core, core = http("GET", "/api/brains/core/config")
        say(f"(migration) GET /api/settings -> {status} ; fenêtre Core : model={core['fields']['model']['value'] or '(défaut)'} "
            f"delegation={core['fields']['delegation']['value']} (aucun brain-config.json écrit avant : "
            f"{not (RUNTIME / 'brain-config.json').exists() or 'présent après les phases précédentes'})")
        _, routing = http("GET", "/api/subagent-role-routing")
        say(f"(migration) rôles : {[(r['role_id'], r['provenance']) for r in routing['roles']]} ; compat="
            f"{routing.get('compatibility')}")
    after = settings_now()
    b, a = dict(leaves(before)), dict(leaves(after))
    lost = sorted(k for k in b if k not in a)
    changed = sorted(k for k in b if k in a and a[k] != b[k])
    added = sorted(k for k in a if k not in b)
    say(f"(migration) réglages « avant » vs « après » toutes phases : clés perdues={lost} ; valeurs changées={changed} ; "
        f"clés ajoutées={added}")
    RESULT["migrate"] = {"lost": lost, "changed": {k: [b[k], a[k]] for k in changed}, "added": added}
    (SANDBOX / "result-migrate.json").write_text(json.dumps(RESULT, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


PHASES = {"prep": prep, "graph": graph, "brain1": brain1, "brain2": brain2, "roles": roles, "browser": browser_phase,
          "migrate": migrate}

if __name__ == "__main__":
    phase = sys.argv[1]
    say(f"=== phase {phase} ({time.strftime('%Y-%m-%d %H:%M:%S')}) ===")
    try:
        code = PHASES[phase]()
    finally:
        with open(SCRATCH / "s08-sandbox-evidence.log", "a", encoding="utf-8") as fh:
            fh.write("\n".join(LOG) + "\n")
    raise SystemExit(code)

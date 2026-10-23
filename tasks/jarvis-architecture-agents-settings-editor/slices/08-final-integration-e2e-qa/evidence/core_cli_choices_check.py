import json, sys, time
sys.path.insert(0, r"C:\Projects\jarvis\arch-s08")
import s08_sandbox as S
# catalogue fixture rafraîchi (sa fraîcheur n'est pas l'objet de ce contrôle)
p = S.RUNTIME / "model-catalog.json"; c = json.loads(p.read_text(encoding="utf-8")); c["anthropic"]["fetched_at"] = time.time()
p.write_text(json.dumps(c, indent=2), encoding="utf-8")
with S.ControlCenterSandbox():
    _, core = S.http("GET", "/api/brains/core/config")
    S.say("(6) choix servis : CLI " + str([(c["value"], c["available"], c.get("state"), c.get("reason")) for c in core["fields"]["provider"]["choices"]])
          + " ; modèle " + str([(c["value"], c["available"], c.get("state")) for c in core["fields"]["model"]["choices"]]))
    status, body = S.http("PATCH", "/api/brains/core/config", {"base_revision": core["revision"], "model": ""})
    S.say(f"(6) PATCH model='' (retour au défaut du CLI) -> {status} code={body.get('code')} raison=« {body.get('reason')} »")
    if status == 200:
        _, core = S.http("GET", "/api/brains/core/config")
        status, body = S.http("PATCH", "/api/brains/core/config", {"base_revision": core["revision"], "model": "claude-haiku-4-5"})
        S.say(f"(6) PATCH model=claude-haiku-4-5 (remise) -> {status}")
    _, core = S.http("GET", "/api/brains/core/config")
    status, body = S.http("PATCH", "/api/brains/core/config", {"base_revision": core["revision"], "provider": "claude", "model": "claude-haiku-4-5"})
    S.say(f"(6) PATCH provider=claude + model (même CLI) -> {status} code={body.get('code')}")
    _, core = S.http("GET", "/api/brains/core/config")
    status, body = S.http("PATCH", "/api/brains/core/config", {"base_revision": core["revision"], "provider": "codex", "model": ""})
    S.say(f"(6) PATCH provider=codex -> {status} code={body.get('code')} raison=« {body.get('reason')} » ; agent_cli={S.settings_now().get('agent_cli')}")
    if status == 200:
        _, core = S.http("GET", "/api/brains/core/config")
        status, body = S.http("PATCH", "/api/brains/core/config", {"base_revision": core["revision"], "provider": "claude", "model": "claude-haiku-4-5"})
        S.say(f"(6) PATCH provider=claude (retour) -> {status} code={body.get('code')} ; agent_cli={S.settings_now().get('agent_cli')}")
    time.sleep(3)
    S.say("(6) bascule de CLI réelle : " + str([(r.get("kind"), (r.get("data") or {}).get("agent_cli") or (r.get("data") or {}).get("code"))
                                              for r in S.trace_rows({"agent.switch", "agent.start", "agent.stop", "brain_config.agents_reconfigured", "agent.unavailable"})][-8:]))

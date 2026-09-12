"""Le moment où un modèle interdit ne peut plus partir.

Le cerveau nomme un profil ; le CLI, lui, nomme un modèle. Entre les deux, ce
hook est le seul endroit qui a le pouvoir de corriger. Ce qui est prouvé ici :
un modèle hors réglages est réécrit et non subi, un profil sans candidat est
refusé en clair, et aucune panne de ce hook ne peut paralyser le cerveau.
"""

from __future__ import annotations

import json

from jarvis.domain import routing
from jarvis.runtime import agent_routing, routing_hook
from jarvis.runtime.journal import read_jsonl_tail

CLAUDE = {
    "id": "claude",
    "label": "Claude Code",
    "model_provider": "anthropic",
    "capabilities": [routing.CODE, routing.SEMANTIC, routing.COMPUTER_USE],
    "available": True,
    "error": "",
}
CODEX = {
    "id": "codex",
    "label": "Codex CLI",
    "model_provider": "openai",
    "capabilities": [routing.CODE, routing.SEMANTIC],
    "available": True,
    "error": "",
}
MODELS = {
    "anthropic": [{"id": "grand", "label": "Grand", "roles": ("text",)}, {"id": "petit", "label": "Petit", "roles": ("text",)}],
    "openai": [{"id": "gpt-o", "label": "GPT O", "roles": ("text",)}],
}


def pool(*agents):
    return agent_routing.build_candidates(agents or (CLAUDE,), MODELS)


def policy(*candidates: dict, profile: str = "code", enabled: bool = True) -> routing.RoutingPolicy:
    settings: dict = {}
    agent_routing.apply(settings, {"enabled": enabled, "profiles": {profile: {"candidates": list(candidates)}}})
    return agent_routing.load_policy(settings)


def call(description: str = "[code] Corriger le bug", model: str = "", **extra) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Agent",
        "tool_use_id": "toolu-1",
        "tool_input": {"description": description, "prompt": "Fais-le.", "model": model, **extra},
    }


def applied(output: dict) -> str:
    return (output.get("hookSpecificOutput") or {}).get("permissionDecision", "")


def updated(output: dict) -> dict:
    return (output.get("hookSpecificOutput") or {}).get("updatedInput", {})


# --------------------------------------------------------------------- profil


def test_the_profile_is_read_from_the_bracket_the_brain_is_asked_to_write():
    assert routing_hook.read_profile({"description": "[code] Corriger le bug"}) == "code"
    assert routing_hook.read_profile({"description": " [ Desktop ] Ouvrir le devis"}) == "desktop"
    assert routing_hook.read_profile({"description": "", "prompt": "[fast] Résume"}) == "fast"


def test_an_absent_or_invented_profile_falls_back_to_general_without_guessing():
    """Deviner le profil d'après le texte serait rendre au modèle le choix qu'on
    lui retire : sans marqueur valide, c'est « general »."""

    assert routing_hook.read_profile({"description": "Corriger le bug de code"}) == routing.GENERAL_PROFILE
    assert routing_hook.read_profile({"description": "[kode] Corriger"}) == routing.GENERAL_PROFILE
    assert routing_hook.read_profile({}) == routing.GENERAL_PROFILE


def test_the_marker_never_reaches_what_the_user_reads():
    assert routing_hook.strip_profile("[code] Corriger le bug") == "Corriger le bug"


def test_the_brain_is_told_how_to_name_a_profile():
    from jarvis.runtime.claude_local import BRAIN_SYSTEM_PROMPT

    assert routing_hook.PROFILE_RULE in BRAIN_SYSTEM_PROMPT
    for name in routing.TASK_PROFILE_IDS:
        assert f"[{name}]" in routing_hook.PROFILE_RULE


# ------------------------------------------------------------------ décision


def test_a_model_outside_the_settings_is_rewritten_not_obeyed():
    chosen = policy({"agent": "claude", "model": "grand"})
    output, decision = routing_hook.decide(call(model="un-modele-inconnu"), chosen, pool())

    assert applied(output) == "allow"
    assert updated(output) == {"model": "grand"}
    assert decision.reason == routing.REASON_PREFERRED


def test_a_model_already_conform_is_left_strictly_alone():
    chosen = policy({"agent": "claude", "model": "grand"})
    output, decision = routing_hook.decide(call(model="grand"), chosen, pool())

    assert output == {}
    assert decision.model == "grand"


def test_an_unavailable_preferred_model_hands_the_subagent_to_the_next_allowed_one():
    chosen = policy({"agent": "claude", "model": "disparu"}, {"agent": "claude", "model": "petit"})
    candidates = agent_routing.with_saved(pool(), chosen)

    output, decision = routing_hook.decide(call(model="grand"), chosen, candidates)

    assert updated(output) == {"model": "petit"}
    assert decision.reason == routing.REASON_FALLBACK
    assert decision.fallback_code == routing.REJECT_MODEL_UNAVAILABLE


def test_a_profile_with_no_usable_candidate_is_refused_in_plain_language():
    chosen = policy({"agent": "claude", "model": "disparu"})
    candidates = agent_routing.with_saved(pool(), chosen)

    output, decision = routing_hook.decide(call(), chosen, candidates)

    assert applied(output) == "deny"
    reason = output["hookSpecificOutput"]["permissionDecisionReason"]
    assert "réglages" in reason and decision is None


def test_a_policy_that_only_allows_another_cli_does_not_pretend_to_route_there():
    """L'outil `Agent` tourne dans le processus Claude : aucun réglage ne peut
    en faire sortir un sous-agent. Mieux vaut le dire que le laisser croire."""

    chosen = policy({"agent": "codex", "model": "gpt-o"})
    output, _ = routing_hook.decide(call(), chosen, pool(CLAUDE, CODEX))

    assert applied(output) == "deny"


def test_an_off_policy_leaves_the_cli_exactly_as_it_was():
    chosen = policy({"agent": "claude", "model": "grand"}, enabled=False)
    output, decision = routing_hook.decide(call(model="n-importe-quoi"), chosen, pool())

    assert output == {}
    assert decision.reason == routing.REASON_COMPATIBILITY


def test_a_profile_left_empty_also_leaves_the_cli_alone():
    chosen = policy({"agent": "claude", "model": "grand"}, profile="fast")
    output, decision = routing_hook.decide(call("[general] Dis bonjour"), chosen, pool())

    assert output == {} and decision.reason == routing.REASON_COMPATIBILITY


def test_a_tool_that_is_not_a_subagent_launch_is_none_of_the_hook_s_business():
    chosen = policy({"agent": "claude", "model": "grand"})
    output, decision = routing_hook.decide({"tool_name": "Read", "tool_input": {}}, chosen, pool())

    assert output == {} and decision is None


def test_the_desktop_profile_needs_a_candidate_that_can_drive_the_machine():
    limited = dict(CLAUDE, capabilities=[routing.CODE, routing.SEMANTIC])
    chosen = policy({"agent": "claude", "model": "grand"}, profile="desktop")

    output, _ = routing_hook.decide(call("[desktop] Ouvre le devis"), chosen, pool(limited))

    assert applied(output) == "deny"


# ---------------------------------------------------------------- bout en bout


def _write_settings(tmp_path, payload: dict) -> None:
    settings: dict = {}
    agent_routing.apply(settings, payload)
    (tmp_path / "control-center-settings.json").write_text(json.dumps(settings), encoding="utf-8")


def test_the_hook_reads_the_settings_file_and_answers_on_its_own(tmp_path, monkeypatch):
    monkeypatch.setattr(routing_hook, "local_agents", lambda: [CLAUDE])
    (tmp_path / "model-catalog.json").write_text(
        json.dumps({"anthropic": {"provider": "anthropic", "models": MODELS["anthropic"], "fetched_at": 0, "key_hint": "x"}}),
        encoding="utf-8",
    )
    _write_settings(tmp_path, {"enabled": True, "profiles": {"code": {"candidates": [{"agent": "claude", "model": "petit"}]}}})

    output = routing_hook.run(call(model="grand"), tmp_path)

    assert updated(output) == {"model": "petit"}
    # La preuve est dans la trace, en codes : de quoi expliquer le choix.
    [event] = [e for e in read_jsonl_tail(tmp_path / "trace.jsonl") if e["kind"] == "agent.routing.decided"]
    assert event["data"]["profile"] == "code"
    assert event["data"]["requested_model"] == "grand"
    assert event["data"]["model"] == "petit"
    assert event["data"]["reason"] == routing.REASON_PREFERRED
    # Ni consigne, ni texte libre du modèle : rien qui ressemble à un raisonnement.
    assert "Fais-le." not in json.dumps(event, ensure_ascii=False)


def test_the_hook_without_any_settings_says_nothing(tmp_path):
    assert routing_hook.run(call(), tmp_path) == {}


def test_a_broken_routing_policy_never_paralyses_the_brain(tmp_path, monkeypatch):
    _write_settings(tmp_path, {"enabled": True, "profiles": {"code": {"candidates": [{"agent": "claude"}]}}})

    def boom() -> list:
        raise RuntimeError("catalogue illisible")

    monkeypatch.setattr(routing_hook, "local_agents", boom)

    assert routing_hook.run(call(), tmp_path) == {}
    # La panne est dite, une fois, là où les erreurs vivent.
    [failure] = [e for e in read_jsonl_tail(tmp_path / "errors.jsonl") if e["kind"] == "agent.routing.failed"]
    assert failure["data"]["code"] == "routing_hook_failed"


def test_the_cli_is_handed_this_hook_and_nothing_else(tmp_path):
    declared = json.loads(routing_hook.hook_settings(tmp_path, python="C:/py.exe"))

    [entry] = declared["hooks"]["PreToolUse"]
    assert entry["matcher"] == "Agent|Task"
    command = entry["hooks"][0]["command"]
    assert "routing-hook" in command and str(tmp_path) in command
    # Chemins entre guillemets : un dossier avec une espace ne doit pas couper
    # la commande en deux.
    assert command.startswith('"C:/py.exe"')
    assert list(declared) == ["hooks"]


def test_the_running_brain_is_launched_with_that_hook(tmp_path, monkeypatch):
    import asyncio

    from jarvis.runtime import claude_local
    from jarvis.runtime.claude_local import ClaudeLocalAgent

    started: list[list[str]] = []

    class _Empty:
        async def readline(self) -> bytes:
            return b""

    class _Process:
        pid = 1
        returncode = 0

        def __init__(self) -> None:
            self.stdin = None
            self.stdout = _Empty()
            self.stderr = _Empty()

        async def wait(self) -> int:
            return 0

    async def fake_exec(*args, **kwargs):  # noqa: ANN002, ANN003
        started.append(list(args))
        return _Process()

    monkeypatch.setattr(claude_local.asyncio, "create_subprocess_exec", fake_exec)
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path)
    asyncio.run(_start(agent))

    argv = started[0]
    declared = json.loads(argv[argv.index("--settings") + 1])
    assert declared["hooks"]["PreToolUse"][0]["matcher"] == "Agent|Task"


async def _start(agent) -> None:  # noqa: ANN001
    await agent.start()

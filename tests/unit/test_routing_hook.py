"""Le moment où un modèle interdit ne peut plus partir.

Le cerveau nomme un profil ; le CLI, lui, nomme un modèle. Entre les deux, ce
hook est le seul endroit qui a le pouvoir de corriger. Ce qui est prouvé ici :
un modèle hors réglages est réécrit et non subi, un profil sans candidat est
refusé en clair, et aucune panne de ce hook ne peut paralyser le cerveau.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import time

import pytest

from jarvis.domain import routing
from jarvis.domain.agent_charter import CHARTER_MARK
from jarvis.runtime import agent_routing, routing_hook
from jarvis.runtime.catalog_view import CatalogViewService
from jarvis.runtime.journal import read_jsonl_tail
from jarvis.runtime.model_catalog import ModelCatalog

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


def routed_model(output: dict) -> str:
    """Le modèle imposé par l'aiguillage, ou \"\" quand il n'a rien imposé.

    L'entrée réécrite est renvoyée entière (la charte du chantier s'y ajoute) :
    ce qui prouve l'aiguillage est donc la valeur de `model`, pas l'existence
    d'une réécriture."""
    return str(updated(output).get("model") or "")


def brief_of(output: dict) -> str:
    return str(updated(output).get("prompt") or "")


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
    settings: dict = {"anthropic_api_key": "sk-ant-test"}
    agent_routing.apply(settings, payload)
    (tmp_path / "control-center-settings.json").write_text(json.dumps(settings), encoding="utf-8")


def _cached_models(provider: str, api_key: str, models: list[dict], *, fetched_at: float | None = None) -> dict:
    return {
        "provider": provider,
        "models": models,
        "fetched_at": time.time() if fetched_at is None else fetched_at,
        "_credential_fingerprint": ModelCatalog._credential_fingerprint(provider, api_key),
    }


def test_the_hook_reads_the_settings_file_and_answers_on_its_own(tmp_path, monkeypatch):
    monkeypatch.setattr(routing_hook, "local_agents", lambda: [CLAUDE])
    (tmp_path / "model-catalog.json").write_text(
        json.dumps({"anthropic": _cached_models("anthropic", "sk-ant-test", MODELS["anthropic"])}),
        encoding="utf-8",
    )
    _write_settings(tmp_path, {"enabled": True, "profiles": {"code": {"candidates": [{"agent": "claude", "model": "petit"}]}}})

    output = routing_hook.run(call(model="grand"), tmp_path)

    assert routed_model(output) == "petit"
    # L'entrée repart entière : la consigne et la description survivent à la
    # réécriture du modèle, quelle que soit la façon dont le CLI l'applique.
    assert brief_of(output).endswith("Fais-le.")
    assert updated(output)["description"] == "[code] Corriger le bug"
    # La preuve est dans la trace, en codes : de quoi expliquer le choix.
    [event] = [e for e in read_jsonl_tail(tmp_path / "trace.jsonl") if e["kind"] == "agent.routing.decided"]
    assert event["data"]["profile"] == "code"
    assert event["data"]["requested_model"] == "grand"
    assert event["data"]["model"] == "petit"
    assert event["data"]["reason"] == routing.REASON_PREFERRED
    # Ni consigne, ni texte libre du modèle : rien qui ressemble à un raisonnement.
    assert "Fais-le." not in json.dumps(event, ensure_ascii=False)


@pytest.mark.parametrize("active_key", ["sk-rotated-1234", ""])
def test_private_cached_model_is_never_routable_after_key_rotation_or_removal(
    tmp_path, monkeypatch, active_key,
):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(routing_hook, "local_agents", lambda: [CLAUDE])
    (tmp_path / "model-catalog.json").write_text(
        json.dumps({
            "anthropic": _cached_models(
                "anthropic",
                "sk-original-1234",
                [{"id": "private-model", "roles": ["text"]}],
            ),
        }),
        encoding="utf-8",
    )
    settings: dict = {"anthropic_api_key": active_key}
    agent_routing.apply(settings, {
        "enabled": True,
        "profiles": {"code": {"candidates": [{"agent": "claude", "model": "private-model"}]}},
    })
    (tmp_path / "control-center-settings.json").write_text(json.dumps(settings), encoding="utf-8")

    candidates = routing_hook.offline_candidates(
        tmp_path,
        agent_routing.load_policy(settings),
        settings=settings,
    )
    private = next(item for item in candidates if item.model == "private-model")

    assert private.available is False
    assert applied(routing_hook.run(call(), tmp_path)) == "deny"


def test_stale_saved_model_is_nonselectable_in_view_and_noneligible_in_hook(tmp_path, monkeypatch):
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    stale_payload = {
        **_cached_models(
            "anthropic",
            "sk-ant-test",
            MODELS["anthropic"],
            fetched_at=(now - timedelta(days=1)).timestamp(),
        ),
    }
    (tmp_path / "model-catalog.json").write_text(
        json.dumps({"anthropic": stale_payload}), encoding="utf-8",
    )
    chosen = policy({"agent": "claude", "model": "petit"})
    monkeypatch.setattr(routing_hook, "local_agents", lambda: [CLAUDE])
    settings: dict = {"anthropic_api_key": "sk-ant-test"}
    agent_routing.apply(settings, {
        "enabled": True,
        "profiles": {"code": {"candidates": [{"agent": "claude", "model": "petit"}]}},
    })

    candidates = routing_hook.offline_candidates(tmp_path, chosen, now=now, settings=settings)
    stale = next(item for item in candidates if item.model == "petit")
    view = CatalogViewService().subagents(
        agents=[CLAUDE],
        catalogs={"anthropic": {**stale_payload, "source": "cache"}},
        saved=[routing.CandidateRef("claude", "petit")],
        now=now,
    ).to_dict()
    comparison = next(item for item in view["items"] if item["identity"]["model_id"] == "petit")

    assert stale.available is False
    assert "non vérifiée" in stale.unavailable_reason
    assert comparison["availability"]["state"] == "configured_unverified"
    assert comparison["availability"]["selectable"] is False
    output, decision = routing_hook.decide(call(model="grand"), chosen, candidates)
    assert applied(output) == "deny" and decision is None
    with pytest.raises(routing.NoEligibleCandidateError):
        routing_hook.resolve_for(
            "code", chosen, candidates, override=routing.CandidateRef("claude", "petit"),
        )


def test_the_hook_without_any_settings_imposes_no_model_and_still_signs_the_brief(tmp_path):
    """Sans réglages, l'aiguillage n'a pas d'opinion — la charte, si.

    Elle ne dépend d'aucun réglage : un poste sans politique d'aiguillage ne
    doit pas envoyer ses sous-agents sans leur dire de quoi ils répondent."""

    output = routing_hook.run(call(), tmp_path)

    assert routed_model(output) == ""
    assert brief_of(output).startswith(CHARTER_MARK)
    assert brief_of(output).endswith("Fais-le.")


def test_a_byte_order_mark_never_silently_switches_routing_off(tmp_path, monkeypatch):
    """Mesuré sur cette machine : PowerShell préfixe stdin d'une marque d'ordre
    d'octets, et le Bloc-notes en ajoute une au fichier de réglages. Les refuser
    éteindrait l'aiguillage sans aucun message."""

    monkeypatch.setattr(routing_hook, "local_agents", lambda: [CLAUDE])
    (tmp_path / "model-catalog.json").write_text(
        json.dumps({"anthropic": _cached_models("anthropic", "sk-ant-test", MODELS["anthropic"])}),
        encoding="utf-8",
    )
    settings: dict = {"anthropic_api_key": "sk-ant-test"}
    agent_routing.apply(settings, {"enabled": True, "profiles": {"code": {"candidates": [{"agent": "claude", "model": "petit"}]}}})
    # Le fichier tel que le Bloc-notes le réécrit.
    (tmp_path / "control-center-settings.json").write_text(json.dumps(settings), encoding="utf-8-sig")

    assert routing_hook.load_settings(tmp_path) == settings
    assert routed_model(routing_hook.run(call(model="grand"), tmp_path)) == "petit"


def test_the_hook_reads_a_marked_event_from_its_standard_input(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(routing_hook, "local_agents", lambda: [CLAUDE])
    (tmp_path / "model-catalog.json").write_text(
        json.dumps({"anthropic": _cached_models("anthropic", "sk-ant-test", MODELS["anthropic"])}),
        encoding="utf-8",
    )
    _write_settings(tmp_path, {"enabled": True, "profiles": {"code": {"candidates": [{"agent": "claude", "model": "petit"}]}}})

    import io
    import sys

    monkeypatch.setattr(sys, "stdin", io.StringIO("﻿" + json.dumps(call(model="grand"))))
    assert routing_hook.main(["--runtime-root", str(tmp_path)]) == 0

    assert json.loads(capsys.readouterr().out)["hookSpecificOutput"]["updatedInput"]["model"] == "petit"


def test_a_broken_routing_policy_never_paralyses_the_brain(tmp_path, monkeypatch):
    _write_settings(tmp_path, {"enabled": True, "profiles": {"code": {"candidates": [{"agent": "claude"}]}}})

    def boom() -> list:
        raise RuntimeError("catalogue illisible")

    monkeypatch.setattr(routing_hook, "local_agents", boom)

    # L'aiguillage se tait ; la charte, elle, ne dépend pas du catalogue.
    output = routing_hook.run(call(), tmp_path)
    assert routed_model(output) == ""
    assert brief_of(output).startswith(CHARTER_MARK)
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


# ===========================================================================
# Charte du chantier
# ===========================================================================


def test_the_charter_is_signed_on_the_brief_the_brain_wrote():
    """Le cerveau décrit le problème ; le rôle, lui, est posé par le code.

    Le 18/09/2026 sa consigne prescrivait la preuve à fournir, et le sous-agent
    l'a remplie sur la mauvaise grandeur. La charte arrive donc avant elle, sur
    l'appel lui-même, et dit ce qui prouve quoi."""

    signed = brief_of(routing_hook.run(call(), pathlib.Path("."))) if False else None
    change = routing_hook.charter_input(call())

    assert change is not None
    brief = str(change["prompt"])
    assert brief.startswith(CHARTER_MARK)
    assert brief.endswith("Fais-le.")
    # Les quatre règles qui manquaient au tour raté.
    for rule in ("fais-la\néchouer sur le code actuel", "couche où l'utilisateur perçoit",
                 "arrête-toi et\ndis-le", "QUESTION", "BLOQUÉ"):
        assert rule in brief, rule
    assert signed is None


def test_a_brief_already_signed_is_never_signed_twice():
    """Un chantier qui délègue à son tour passe par le même hook : deux chartes
    se contrediraient sur le rôle, et la seconde repousserait la vraie demande
    hors de vue."""

    once = routing_hook.charter_input(call())
    twice = routing_hook.charter_input(call(prompt=str(once["prompt"])))

    assert twice is None


def test_the_profile_marker_stays_in_front_of_the_charter():
    """Le profil se lit au premier mot entre crochets : la charte ne l'enterre
    pas, sans quoi l'aiguillage d'un appel imbriqué retomberait sur general."""

    change = routing_hook.charter_input(call(prompt="[fast] Résume ce fichier."))

    assert str(change["prompt"]).startswith("[fast] ")
    assert routing_hook.read_profile({"prompt": str(change["prompt"])}) == "fast"


def test_nothing_is_signed_when_there_is_no_brief_and_no_subagent():
    assert routing_hook.charter_input(call(prompt="")) is None
    assert routing_hook.charter_input({"tool_name": "Bash", "tool_input": {"prompt": "ls"}}) is None


def test_a_refused_profile_stays_refused_and_carries_no_charter(tmp_path, monkeypatch):
    """Un refus ne part pas : il n'y a pas de chantier à cadrer, et la charte
    ne doit pas transformer un « deny » en « allow »."""

    monkeypatch.setattr(routing_hook, "local_agents", lambda: [CODEX])
    _write_settings(tmp_path, {"enabled": True, "profiles": {"code": {"candidates": [{"agent": "claude", "model": "petit"}],
                                                                      "allow_general_fallback": False}}})

    output = routing_hook.run(call(), tmp_path)

    assert applied(output) == "deny"
    assert updated(output) == {}

"""Un rôle de sous-agent se règle par famille sur le CLI Claude (décision du Human, HV-ARCH-007, 2026-10-24).

L'outil `Agent` ne prend qu'une famille (`sonnet|opus|haiku|fable`) que le CLI résout vers sa version courante
(Sonnet = Sonnet 5.5 aujourd'hui). Prouvé ici : l'onglet Sous-agents sert une entrée par famille au lieu des
identifiants trompeurs du catalogue ; une politique déjà enregistrée par identifiant marche encore, s'affiche par
sa famille et n'est pas réécrite à la lecture ; la trace `agent.routing.decided` dit la famille demandée et
l'identifiant d'origine ; les candidats non Claude (Codex) ne changent pas. Contrat : `docs/subagent-roles.md` § 10.
"""

from __future__ import annotations

import json

from jarvis.domain import model_family, role_routing, routing
from jarvis.domain.routing import CandidateRef, ModelCandidate
from jarvis.domain.subagent_roles import role_by_id
from jarvis.runtime import agent_routing, routing_hook, subagent_role_routing as store_module
from jarvis.runtime.journal import read_jsonl_tail
from jarvis.runtime.subagent_role_routing import RoleRoutingStore

CLAUDE = {
    "id": "claude", "label": "Claude Code", "model_provider": "anthropic",
    "capabilities": [routing.CODE, routing.SEMANTIC], "available": True, "error": "",
}
CODEX = {
    "id": "codex", "label": "Codex CLI", "model_provider": "openai",
    "capabilities": [routing.CODE, routing.SEMANTIC], "available": True, "error": "",
}
MODELS = {
    "anthropic": [
        {"id": "claude-sonnet-4-5", "label": "Claude Sonnet 4.5", "roles": ("text",)},
        {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5", "roles": ("text",)},
        {"id": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5", "roles": ("text",)},
        {"id": "maison", "label": "Maison", "roles": ("text",)},
    ],
    "openai": [{"id": "gpt-o", "label": "GPT O", "roles": ("text",)}, {"id": "claude-sonnet-4-5", "label": "?", "roles": ("text",)}],
}


def pool() -> list[ModelCandidate]:
    return agent_routing.build_candidates([CLAUDE, CODEX], MODELS)


def ref(model: str, agent: str = "claude") -> dict:
    return {"agent": agent, "model": model}


def profiles(enabled: bool = True, **lists) -> routing.RoutingPolicy:
    settings: dict = {}
    agent_routing.apply(settings, {"enabled": enabled, "profiles": {name: {"candidates": value} for name, value in lists.items()}})
    return agent_routing.load_policy(settings)


def snapshot(tmp_path, policy: routing.RoutingPolicy | None = None, candidates=None) -> dict:
    policy = policy or profiles(enabled=False)
    document = store_module.load_document(tmp_path)
    return json.loads(json.dumps(store_module.describe(
        document, policy, store_module.enrich(candidates if candidates is not None else pool(), policy, document))))


def role(payload: dict, role_id: str) -> dict:
    return next(item for item in payload["roles"] if item["role_id"] == role_id)


def write_legacy(tmp_path, candidates: list[dict]) -> bytes:
    """Une politique enregistrée avant la décision : identifiants complets, écrite à la main comme par l'ancienne version."""
    raw = {"schema_version": 1, "revision": 4, "roles": {"qa": {"candidates": candidates, "allow_general_fallback": False}}}
    path = tmp_path / store_module.STORE_FILE
    path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    return path.read_bytes()


# ------------------------------------------------------------------ domaine


def test_a_claude_id_is_read_as_its_family_and_nothing_else_is_guessed():
    assert model_family.family_of("claude-sonnet-4-5") == "sonnet"
    assert model_family.family_of("claude-3-5-haiku-20241022") == "haiku"
    assert model_family.family_of("Opus") == "opus"
    assert model_family.family_of("maison") is None and model_family.family_of("") is None
    assert model_family.normalize_ref(CandidateRef("claude", "claude-opus-5-5")) == CandidateRef("claude", "opus")
    # Un autre CLI garde ses identifiants, même s'ils ressemblent à ceux de Claude.
    assert model_family.normalize_ref(CandidateRef("codex", "claude-sonnet-4-5")) == CandidateRef("codex", "claude-sonnet-4-5")
    assert model_family.family_label("sonnet") == "Sonnet (version courante du CLI)"


def test_the_claude_catalogue_collapses_to_one_entry_per_family():
    collapsed = model_family.collapse_candidates(pool())
    claude = [(item.model, item.model_label) for item in collapsed if item.agent == "claude"]
    assert claude == [
        ("", agent_routing.DEFAULT_MODEL_LABEL),
        ("sonnet", "Sonnet (version courante du CLI)"),
        ("haiku", "Haiku (version courante du CLI)"),
        ("maison", "Maison"),
    ]
    assert [item.model for item in collapsed if item.agent == "codex"] == ["", "gpt-o", "claude-sonnet-4-5"]
    assert model_family.collapse_candidates(collapsed) == collapsed  # idempotent


def test_a_family_is_available_when_any_of_its_ids_is():
    items = [
        ModelCandidate("claude", "claude-sonnet-4-5", available=False, unavailable_reason="retiré", agent_label="Claude Code"),
        ModelCandidate("claude", "claude-sonnet-5-5", available=True, agent_label="Claude Code"),
        ModelCandidate("claude", "claude-opus-4-1", available=False, unavailable_reason="clé absente", agent_label="Claude Code"),
    ]
    sonnet, opus = model_family.collapse_candidates(items)
    assert (sonnet.model, sonnet.available, sonnet.unavailable_reason) == ("sonnet", True, "")
    assert (opus.model, opus.available, opus.unavailable_reason) == ("opus", False, "clé absente")


def test_a_legacy_id_in_a_role_policy_resolves_to_its_family_and_keeps_the_saved_id():
    document = role_routing.RoleRoutingDocument(1, {"qa": role_routing.RolePolicy(
        "qa", (CandidateRef("claude", "claude-opus-4-1"), CandidateRef("claude", "claude-sonnet-4-5")))})
    decision = role_routing.resolve_for_role(role_by_id("qa"), None, document, profiles(), pool())
    # Pas d'Opus au catalogue : repli sur la famille Sonnet, que le CLI lance dans sa version courante.
    assert (decision.model, decision.saved_model, decision.reason) == ("sonnet", "claude-sonnet-4-5", routing.REASON_FALLBACK)
    assert decision.fallback_from == CandidateRef("claude", "opus")
    assert decision.as_dict()["saved_model"] == "claude-sonnet-4-5"


def test_an_inherited_role_reads_its_profile_list_by_family_too():
    policy = profiles(code=[ref("claude-haiku-4-5")], general=[ref("claude-sonnet-4-5")])
    decision = role_routing.resolve_for_role(role_by_id("coder"), None, role_routing.EMPTY_DOCUMENT, policy, pool())
    # `claude-haiku-4-5` n'est pas au catalogue (`claude-haiku-4-5-20251001` l'est) : la famille, elle, y est.
    assert (decision.model, decision.saved_model, decision.provenance) == ("haiku", "claude-haiku-4-5", "inherited:code")


def test_a_family_policy_has_no_saved_id_and_codex_keeps_its_ids():
    document = role_routing.RoleRoutingDocument(1, {"qa": role_routing.RolePolicy(
        "qa", (CandidateRef("codex", "gpt-o"), CandidateRef("claude", "sonnet")))})
    decision = role_routing.resolve_for_role(role_by_id("qa"), None, document, profiles(), pool())
    assert (decision.agent, decision.model, decision.saved_model) == ("codex", "gpt-o", "")
    host_only = [item for item in pool() if item.agent == "claude"]
    decision = role_routing.resolve_for_role(role_by_id("qa"), None, document, profiles(), host_only)
    assert (decision.agent, decision.model, decision.saved_model) == ("claude", "sonnet", "")
    assert "saved_model" not in decision.as_dict()


# ------------------------------------------------------------- onglet Sous-agents


def test_the_tab_offers_one_choice_per_claude_family_never_a_misleading_version(tmp_path):
    payload = snapshot(tmp_path)
    harness = {item["id"]: item for item in payload["harnesses"]}
    claude_models = [(m["model"], m["label"]) for m in harness["claude"]["models"]]
    assert claude_models == [
        ("", agent_routing.DEFAULT_MODEL_LABEL),
        ("sonnet", "Sonnet (version courante du CLI)"),
        ("haiku", "Haiku (version courante du CLI)"),
        ("maison", "Maison"),
    ]
    assert not any(m.startswith("claude-") for m, _ in claude_models)
    assert [m["model"] for m in harness["codex"]["models"]] == ["", "gpt-o", "claude-sonnet-4-5"]


def test_a_legacy_policy_shows_as_its_family_and_the_file_is_not_rewritten(tmp_path):
    before = write_legacy(tmp_path, [ref("claude-sonnet-4-5"), ref("claude-sonnet-5-5"), ref("gpt-o", "codex")])

    qa = role(snapshot(tmp_path), "qa")
    sonnet, codex = qa["candidates"]  # deux identifiants Sonnet : un seul choix affiché
    assert (sonnet["model"], sonnet["saved_model"], sonnet["available"], sonnet["selectable"]) == (
        "sonnet", "claude-sonnet-4-5", True, True)
    assert sonnet["label"] == "Claude Code · Sonnet (version courante du CLI)"
    assert (codex["model"], codex["position"]) == ("gpt-o", 1) and "saved_model" not in codex
    assert (qa["preview"]["model"], qa["preview"]["saved_model"]) == ("sonnet", "claude-sonnet-4-5")
    assert (tmp_path / store_module.STORE_FILE).read_bytes() == before


def test_saving_a_role_stores_families(tmp_path):
    store = RoleRoutingStore(tmp_path)
    store.put("qa", {"candidates": [ref("claude-sonnet-4-5"), ref("sonnet"), ref("gpt-o", "codex")]}, "rr-0")
    saved = json.loads((tmp_path / store_module.STORE_FILE).read_text(encoding="utf-8"))
    assert saved["roles"]["qa"]["candidates"] == [ref("sonnet"), ref("gpt-o", "codex")]
    assert "saved_model" not in role(snapshot(tmp_path), "qa")["candidates"][0]


def test_the_inherited_fallback_list_is_shown_by_family(tmp_path):
    policy = profiles(enabled=True, general=[ref("claude-sonnet-4-5")])
    qa = role(snapshot(tmp_path, policy), "qa")
    assert [(c["model"], c.get("saved_model")) for c in qa["candidates"]] == [("sonnet", "claude-sonnet-4-5")]
    assert qa["preview"]["model"] == "sonnet"


# ------------------------------------------------------------------- hook


def _hook_env(tmp_path, monkeypatch, settings: dict) -> None:
    monkeypatch.setattr(routing_hook, "local_agents", lambda: [CLAUDE])
    monkeypatch.setattr(routing_hook, "offline_candidates",
                        lambda root, policy, settings=None, extra_refs=(): agent_routing.with_saved(pool(), policy, extra_refs=extra_refs))
    (tmp_path / "control-center-settings.json").write_text(json.dumps(settings), encoding="utf-8")


def call(description: str, model: str = "") -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_use_id": "toolu-1",
            "tool_input": {"description": description, "prompt": "Fais-le.", "model": model}}


def routed(output: dict) -> str:
    return str(((output.get("hookSpecificOutput") or {}).get("updatedInput") or {}).get("model") or "")


def decided(tmp_path) -> dict:
    [event] = [e for e in read_jsonl_tail(tmp_path / "trace.jsonl") if e["kind"] == "agent.routing.decided"]
    return event


def test_the_hook_runs_a_legacy_role_policy_on_its_family_and_says_so(tmp_path, monkeypatch):
    _hook_env(tmp_path, monkeypatch, {"agent_routing": {"enabled": False}})
    before = write_legacy(tmp_path, [ref("claude-sonnet-4-5")])

    output = routing_hook.run(call("[general] [qa] Relire", model="opus"), tmp_path)

    assert routed(output) == "sonnet"
    assert "Sonnet (version courante du CLI), enregistré « claude-sonnet-4-5 »" in (
        output["hookSpecificOutput"]["permissionDecisionReason"])
    event = decided(tmp_path)
    assert (event["data"]["model"], event["data"]["model_family"], event["data"]["agent_model"]) == ("sonnet", "sonnet", "sonnet")
    assert event["data"]["saved_model"] == "claude-sonnet-4-5"
    assert "modèle Sonnet (version courante du CLI), enregistré « claude-sonnet-4-5 »" in event["message"]
    assert (tmp_path / store_module.STORE_FILE).read_bytes() == before


def test_the_hook_runs_a_family_role_policy_without_inventing_a_saved_id(tmp_path, monkeypatch):
    _hook_env(tmp_path, monkeypatch, {"agent_routing": {"enabled": False}})
    RoleRoutingStore(tmp_path).put("qa", {"candidates": [ref("haiku")]}, "rr-0")

    assert routed(routing_hook.run(call("[general] [qa] Relire"), tmp_path)) == "haiku"
    event = decided(tmp_path)
    assert (event["data"]["model"], event["data"]["model_family"]) == ("haiku", "haiku")
    assert "saved_model" not in event["data"]
    assert "modèle Haiku (version courante du CLI)" in event["message"] and "enregistré" not in event["message"]

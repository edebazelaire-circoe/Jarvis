"""Le routage par rôle : chaque rôle a son ordre de candidats, hérite sinon de son profil.

Prouvé ici (Slice 03, `jarvis-architecture-agents-settings-editor`) : isolation entre rôles, ordre
préféré, repli sur le profil général, raisons d'indisponibilité en aller-retour, héritage depuis le
`default_profile`, révision périmée refusée en `409`, et le hook qui applique la politique du rôle,
y compris en mode Dupliqué, sans rien changer aux appels sans rôle.

La fixture `tests/fixtures/subagent_role_routing.json` (forme de la lecture, pour la Slice 06) est
produite par ce code : `JARVIS_WRITE_ROLE_ROUTING_FIXTURE=1 pytest tests/unit/test_subagent_role_routing.py`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.domain import role_routing, routing
from jarvis.domain.routing import CandidateRef, NoEligibleCandidateError
from jarvis.domain.subagent_roles import ROLES, role_by_id
from jarvis.runtime import agent_routing, routing_hook, subagent_role_routing as store_module
from jarvis.runtime.journal import read_jsonl_tail
from jarvis.runtime.subagent_role_routing import RoleRoutingStore, RoleRoutingStaleError
from jarvis.runtime.subagent_role_routing_http import ROUTE, SubagentRoleRoutingApi

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "subagent_role_routing.json"

CLAUDE = {
    "id": "claude", "label": "Claude Code", "model_provider": "anthropic",
    "capabilities": [routing.CODE, routing.SEMANTIC, routing.COMPUTER_USE], "available": True, "error": "",
}
CODEX = {
    "id": "codex", "label": "Codex CLI", "model_provider": "openai",
    "capabilities": [routing.CODE, routing.SEMANTIC], "available": False,
    "error": "« codex » est introuvable dans le PATH.",
}
MODELS = {
    "anthropic": [{"id": "grand", "label": "Grand", "roles": ("text",)}, {"id": "petit", "label": "Petit", "roles": ("text",)}],
    "openai": [{"id": "gpt-o", "label": "GPT O", "roles": ("text",)}],
}


def ref(model: str, agent: str = "claude") -> dict:
    return {"agent": agent, "model": model}


def pool():
    return agent_routing.build_candidates([CLAUDE, CODEX], MODELS)


def profiles(enabled: bool = True, **lists) -> routing.RoutingPolicy:
    settings: dict = {}
    agent_routing.apply(settings, {"enabled": enabled, "profiles": {name: {"candidates": value} for name, value in lists.items()}})
    return agent_routing.load_policy(settings)


def call(description: str, model: str = "") -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_use_id": "toolu-1",
            "tool_input": {"description": description, "prompt": "Fais-le.", "model": model}}


def routed(output: dict) -> str:
    return str(((output.get("hookSpecificOutput") or {}).get("updatedInput") or {}).get("model") or "")


def decision_of(output: dict) -> str:
    return (output.get("hookSpecificOutput") or {}).get("permissionDecision", "")


# ---------------------------------------------------------------- domaine


def test_a_role_without_explicit_policy_inherits_its_default_profile_list():
    policy = profiles(code=[ref("petit")], general=[ref("grand")])
    coder = role_by_id("coder")
    effective = role_routing.effective_policy(coder, role_routing.EMPTY_DOCUMENT, policy)
    assert effective.provenance == "inherited:code"
    assert [c.model for c in effective.candidates] == ["petit"]
    qa = role_routing.effective_policy(role_by_id("qa"), role_routing.EMPTY_DOCUMENT, policy)
    assert qa.provenance == "inherited:general" and [c.model for c in qa.candidates] == ["grand"]


def test_the_alias_reviewer_is_the_qa_role_never_a_second_one():
    assert role_routing.canonical_role("reviewer").id == "qa"
    with pytest.raises(routing.RoutingError) as caught:
        role_routing.canonical_role("inconnu")
    assert caught.value.code == "role_routing_unknown_role"


def test_the_first_eligible_candidate_of_the_role_wins_and_a_missing_one_hands_over():
    document = role_routing.RoleRoutingDocument(1, {"qa": role_routing.RolePolicy(
        "qa", (CandidateRef("claude", "disparu"), CandidateRef("claude", "petit")))})
    decision = role_routing.resolve_for_role(role_by_id("qa"), None, document, profiles(), pool())
    assert (decision.model, decision.reason, decision.provenance) == ("petit", routing.REASON_FALLBACK, "explicit")
    assert decision.fallback_from == CandidateRef("claude", "disparu")
    assert decision.fallback_code == routing.REJECT_UNKNOWN
    assert decision.as_dict()["role_id"] == "qa"


def test_an_exhausted_role_falls_back_to_general_only_when_allowed():
    policy = profiles(general=[ref("grand")])
    only_missing = (CandidateRef("claude", "disparu"),)
    allowed = role_routing.RoleRoutingDocument(1, {"qa": role_routing.RolePolicy("qa", only_missing, True)})
    decision = role_routing.resolve_for_role(role_by_id("qa"), None, allowed, policy, pool())
    assert (decision.model, decision.reason) == ("grand", routing.REASON_GENERAL_FALLBACK)

    refused = role_routing.RoleRoutingDocument(1, {"qa": role_routing.RolePolicy("qa", only_missing, False)})
    with pytest.raises(NoEligibleCandidateError) as caught:
        role_routing.resolve_for_role(role_by_id("qa"), None, refused, policy, pool())
    assert role_by_id("qa").name in str(caught.value)


# ---------------------------------------------------------------- stockage


def test_changing_one_role_changes_no_other_role_and_bumps_the_revision(tmp_path):
    store = RoleRoutingStore(tmp_path)
    policy = profiles(code=[ref("petit")], general=[ref("grand")])
    before = {e.role_id: e for e in role_routing.effective_policies(store.load().document, policy)}

    document = store.put("qa", {"candidates": [ref("petit")]}, "rr-0")

    after = {e.role_id: e for e in role_routing.effective_policies(document, policy)}
    assert document.revision == 1
    assert after["qa"].provenance == "explicit" and [c.model for c in after["qa"].candidates] == ["petit"]
    for role in ROLES:
        if role.id != "qa":
            assert after[role.id] == before[role.id], role.id
    # Rien n'a été matérialisé pour les autres rôles : ils héritent toujours, sans écriture.
    stored = json.loads((tmp_path / store_module.STORE_FILE).read_text(encoding="utf-8"))
    assert list(stored["roles"]) == ["qa"]


def test_a_stale_revision_is_refused_and_nothing_is_written(tmp_path):
    store = RoleRoutingStore(tmp_path)
    store.put("coder", {"candidates": [ref("grand")]}, "rr-0")
    with pytest.raises(RoleRoutingStaleError) as caught:
        store.put("qa", {"candidates": [ref("petit")]}, "rr-0")
    assert caught.value.code == "role_routing_revision_stale" and caught.value.current == "rr-1"
    assert store.load().document.for_role("qa") is None


def test_restore_returns_the_role_to_inheritance(tmp_path):
    store = RoleRoutingStore(tmp_path)
    store.put("reviewer", {"candidates": [ref("petit")], "allow_general_fallback": False}, "rr-0")
    assert store.load().document.for_role("qa").allow_general_fallback is False
    document = store.restore("qa", "rr-1")
    assert document.for_role("qa") is None and document.revision == 2
    with pytest.raises(routing.RoutingError) as caught:
        store.restore("qa", "rr-2")
    assert caught.value.code == "role_routing_not_explicit"


def test_invalid_lists_are_refused_with_stable_codes(tmp_path):
    store = RoleRoutingStore(tmp_path)
    for payload, code in (
        ({"candidates": []}, "role_routing_empty_candidates"),
        ({"candidates": [ref("petit"), ref("petit")]}, "routing_duplicate_candidate"),
        ({"candidates": [ref("x", agent="nope")]}, "routing_unknown_agent"),
        ({}, "role_routing_bad_payload"),
        ({"candidates": [ref("petit")], "allow_general_fallback": "oui"}, "role_routing_bad_payload"),
    ):
        with pytest.raises(routing.RoutingError) as caught:
            store.put("qa", payload, "rr-0")
        assert caught.value.code == code, payload
    assert not (tmp_path / store_module.STORE_FILE).exists()


def test_an_unreadable_store_is_reported_and_never_overwritten(tmp_path):
    (tmp_path / store_module.STORE_FILE).write_text("{pas du json", encoding="utf-8")
    loaded = store_module.load(tmp_path)
    assert loaded.error_code == "role_routing_store_unreadable" and loaded.document.roles == {}
    with pytest.raises(routing.RoutingError) as caught:
        RoleRoutingStore(tmp_path).put("qa", {"candidates": [ref("petit")]}, "rr-0")
    assert caught.value.code == "role_routing_store_unreadable"
    assert (tmp_path / store_module.STORE_FILE).read_text(encoding="utf-8") == "{pas du json"


def test_an_entry_for_a_retired_role_survives_other_writes(tmp_path):
    (tmp_path / store_module.STORE_FILE).write_text(json.dumps(
        {"schema_version": 1, "revision": 4, "roles": {"ancien": {"candidates": [ref("grand")]}}}), encoding="utf-8")
    RoleRoutingStore(tmp_path).put("qa", {"candidates": [ref("petit")]}, "rr-4")
    stored = json.loads((tmp_path / store_module.STORE_FILE).read_text(encoding="utf-8"))
    assert stored["roles"]["ancien"] == {"candidates": [ref("grand")]} and stored["revision"] == 5


# ---------------------------------------------------------------- lecture


def _read_model(tmp_path: Path) -> dict:
    store = RoleRoutingStore(tmp_path)
    store.put("qa", {"candidates": [ref("disparu"), ref("petit"), ref("gpt-o", agent="codex")]}, "rr-0")
    policy = profiles(enabled=False, code=[ref("petit")], general=[ref("grand")])
    document = store.load().document
    return store_module.describe(document, policy, store_module.enrich(pool(), policy, document))


def test_unavailable_candidates_stay_visible_with_their_reason_round_trip(tmp_path):
    payload = json.loads(json.dumps(_read_model(tmp_path)))
    qa = next(role for role in payload["roles"] if role["role_id"] == "qa")
    missing, petit, codex = qa["candidates"]
    assert (missing["model"], missing["available"]) == ("disparu", False)
    assert missing["unavailable_reason"] == agent_routing.MISSING_MODEL_REASON
    assert petit["available"] and petit["selectable"] and petit["position"] == 1
    assert codex["available"] is False and "introuvable" in codex["unavailable_reason"]
    assert qa["preview"]["outcome"] == "selected" and qa["preview"]["model"] == "petit"
    assert qa["binding"] is True  # explicite : lie même en Dupliqué
    coder = next(role for role in payload["roles"] if role["role_id"] == "coder")
    assert coder["provenance"] == "inherited:code" and coder["binding"] is False
    assert coder["preview"]["outcome"] == "cli_default"
    assert payload["compatibility"]["delegation_mode"] == "duplicate"
    assert [role["role_id"] for role in payload["roles"]] == [role.id for role in ROLES if role.enabled]


def test_the_shared_fixture_is_the_shape_this_code_produces(tmp_path):
    payload = _read_model(tmp_path)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if os.environ.get("JARVIS_WRITE_ROLE_ROUTING_FIXTURE") == "1":
        FIXTURE.write_text(text, encoding="utf-8")
    assert FIXTURE.read_text(encoding="utf-8") == text, (
        "Fixture périmée : JARVIS_WRITE_ROLE_ROUTING_FIXTURE=1 pytest tests/unit/test_subagent_role_routing.py"
    )


# ---------------------------------------------------------------- hook


def test_the_hook_applies_the_role_policy_and_leaves_role_less_calls_alone():
    policy = profiles(code=[ref("grand")], general=[ref("grand")])
    document = role_routing.RoleRoutingDocument(1, {"qa": role_routing.RolePolicy("qa", (CandidateRef("claude", "petit"),))})

    output, decision = routing_hook.decide(call("[code] [qa] Relire le diff", model="grand"), policy, pool(),
                                           role_policies=document)
    assert routed(output) == "petit"
    assert (decision.role_id, decision.provenance, decision.profile) == ("qa", "explicit", "code")
    assert "politique du rôle" in output["hookSpecificOutput"]["permissionDecisionReason"]

    # Le même profil, sans rôle : la politique du profil, comme avant.
    output, decision = routing_hook.decide(call("[code] Corriger", model="petit"), policy, pool(), role_policies=document)
    assert routed(output) == "grand" and decision.role_id == ""

    # Un rôle sans politique explicite, profil annoncé : exactement le routage par profil d'avant.
    output, decision = routing_hook.decide(call("[code] [research] Lire", model="petit"), policy, pool(),
                                           role_policies=document)
    assert routed(output) == "grand" and decision.provenance == "inherited:code"


def test_a_role_announced_alone_inherits_its_default_profile():
    policy = profiles(code=[ref("petit")], general=[ref("grand")])
    _output, decision = routing_hook.decide(call("[coder] Écrire le module"), policy, pool())
    assert (decision.profile, decision.model, decision.provenance) == ("code", "petit", "inherited:code")


def test_the_hook_process_applies_an_explicit_role_even_in_duplicate_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(routing_hook, "local_agents", lambda: [CLAUDE])
    monkeypatch.setattr(routing_hook, "offline_candidates",
                        lambda root, policy, settings=None, extra_refs=(): agent_routing.with_saved(pool(), policy, extra_refs=extra_refs))
    (tmp_path / "control-center-settings.json").write_text(json.dumps({"agent_routing": {"enabled": False}}), encoding="utf-8")
    RoleRoutingStore(tmp_path).put("qa", {"candidates": [ref("petit")]}, "rr-0")

    assert routed(routing_hook.run(call("[general] [qa] Relire", model="grand"), tmp_path)) == "petit"
    # Dupliqué, pas de rôle explicite : le CLI garde la main, aucun modèle imposé.
    assert routed(routing_hook.run(call("[general] [research] Lire"), tmp_path)) == ""

    events = [e for e in read_jsonl_tail(tmp_path / "trace.jsonl") if e["kind"] == "agent.routing.decided"]
    qa_event = next(e for e in events if e["data"].get("role_id") == "qa")
    assert qa_event["data"]["provenance"] == "explicit" and qa_event["data"]["reason"] == routing.REASON_PREFERRED
    assert "rôle qa (explicit)" in qa_event["message"]


# ---------------------------------------------------------------- HTTP


class _Journal:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None):
        self.events.append((kind, level, data or {}))


async def _client(tmp_path: Path, journal: _Journal, *, fail_catalog: bool = False):
    async def candidates():
        if fail_catalog:
            raise TimeoutError("catalog")
        return pool(), {}

    api = SubagentRoleRoutingApi(RoleRoutingStore(tmp_path), settings=lambda: {}, candidates=candidates, journal=journal)
    app = web.Application()
    app.add_routes(api.routes())
    return TestClient(TestServer(app))


async def test_http_put_stale_and_restore(tmp_path):
    journal = _Journal()
    async with await _client(tmp_path, journal) as client:
        read = await (await client.get(ROUTE)).json()
        assert read["revision"] == "rr-0" and len(read["roles"]) == 7

        ok = await client.put(f"{ROUTE}/qa", json={"base_revision": "rr-0", "candidates": [ref("petit")]})
        body = await ok.json()
        assert ok.status == 200 and body["ok"] and body["snapshot"]["revision"] == "rr-1"

        stale = await client.put(f"{ROUTE}/coder", json={"base_revision": "rr-0", "candidates": [ref("petit")]})
        body = await stale.json()
        assert stale.status == 409 and body["code"] == "role_routing_revision_stale" and body["snapshot"]["revision"] == "rr-1"

        unknown = await client.put(f"{ROUTE}/nope", json={"base_revision": "rr-1", "candidates": [ref("petit")]})
        assert unknown.status == 404 and (await unknown.json())["code"] == "role_routing_unknown_role"

        bad = await client.put(f"{ROUTE}/qa", json={"base_revision": "rr-1", "candidates": []})
        assert bad.status == 422 and (await bad.json())["code"] == "role_routing_empty_candidates"

        restored = await client.delete(f"{ROUTE}/qa", params={"base_revision": "rr-1"})
        body = await restored.json()
        qa = next(role for role in body["snapshot"]["roles"] if role["role_id"] == "qa")
        assert restored.status == 200 and qa["provenance"] == "inherited:general"
    kinds = [kind for kind, _level, _data in journal.events]
    assert "subagent_role_routing.saved" in kinds and "subagent_role_routing.restored" in kinds
    assert any(data.get("code") == "role_routing_revision_stale" for _k, _l, data in journal.events)


async def test_http_read_survives_a_failing_catalog(tmp_path):
    journal = _Journal()
    RoleRoutingStore(tmp_path).put("qa", {"candidates": [ref("petit")]}, "rr-0")
    async with await _client(tmp_path, journal, fail_catalog=True) as client:
        response = await client.get(ROUTE)
        body = await response.json()
    assert response.status == 200 and body["catalog"]["status"] == "unavailable"
    qa = next(role for role in body["roles"] if role["role_id"] == "qa")
    assert qa["candidates"][0]["available"] is False
    assert "Catalogue des candidats indisponible" in qa["candidates"][0]["unavailable_reason"]
    assert any(level == "error" for _k, level, _d in journal.events)


# ---------------------------------------------------------------- reprise QA


@pytest.mark.parametrize("content", [
    {"schema_version": 1, "revision": 2, "roles": ["qa"]},
    {"schema_version": 1, "revision": 2, "roles": {"qa": "claude:petit"}},
    {"schema_version": 1, "revision": 2, "roles": {"qa": {"candidates": "petit"}}},
    {"schema_version": 1, "revision": 2, "roles": {"qa": {"candidates": [{"model": "petit"}]}}},
    {"schema_version": 1, "revision": "7", "roles": {}},
    {"schema_version": 1, "roles": {}},
    {"schema_version": 1, "revision": 2, "roles": {"qa": {"candidates": [ref("petit")], "allow_general_fallback": "false"}}},
])
def test_valid_json_that_is_not_a_policy_is_unreadable_never_coerced_or_overwritten(tmp_path, content):
    text = json.dumps(content)
    (tmp_path / store_module.STORE_FILE).write_text(text, encoding="utf-8")
    loaded = store_module.load(tmp_path)
    assert loaded.error_code == "role_routing_store_unreadable" and loaded.document.roles == {}
    assert store_module.load_document(tmp_path).roles == {}  # le hook hérite de tout
    for revision in ("rr-0", "rr-2", "rr-7"):
        with pytest.raises(routing.RoutingError) as caught:
            RoleRoutingStore(tmp_path).put("qa", {"candidates": [ref("petit")]}, revision)
        assert caught.value.code == "role_routing_store_unreadable"
    assert (tmp_path / store_module.STORE_FILE).read_text(encoding="utf-8") == text


def test_a_role_list_without_any_host_candidate_is_refused_at_write(tmp_path):
    with pytest.raises(routing.RoutingError) as caught:
        RoleRoutingStore(tmp_path).put("qa", {"candidates": [ref("gpt-o", agent="codex")]}, "rr-0")
    assert caught.value.code == "role_routing_no_host_candidate" and "Claude" in str(caught.value)
    assert not (tmp_path / store_module.STORE_FILE).exists()


def test_an_explicit_role_with_nothing_usable_passes_through_in_duplicate_and_is_refused_in_auto():
    document = role_routing.RoleRoutingDocument(1, {"qa": role_routing.RolePolicy(
        "qa", (CandidateRef("claude", "disparu"),), False)})
    output, decision = routing_hook.decide(call("[general] [qa] Relire", model="grand"),
                                           profiles(enabled=False), pool(), role_policies=document)
    assert decision_of(output) != "deny" and routed(output) == ""  # rien d'imposé : le CLI garde la main
    assert decision.reason == role_routing.REASON_ROLE_PASSTHROUGH and decision.considered[0].code == routing.REJECT_UNKNOWN

    output, decision = routing_hook.decide(call("[general] [qa] Relire", model="grand"),
                                           profiles(enabled=True), pool(), role_policies=document)
    assert decision_of(output) == "deny" and decision is None


def _hook_root(tmp_path, monkeypatch, *, enabled: bool, **lists) -> Path:
    monkeypatch.setattr(routing_hook, "local_agents", lambda: [CLAUDE])
    monkeypatch.setattr(routing_hook, "offline_candidates",
                        lambda root, policy, settings=None, extra_refs=(): agent_routing.with_saved(pool(), policy, extra_refs=extra_refs))
    settings: dict = {}
    agent_routing.apply(settings, {"enabled": enabled, "profiles": {k: {"candidates": v} for k, v in lists.items()}})
    (tmp_path / "control-center-settings.json").write_text(json.dumps(settings), encoding="utf-8")
    return tmp_path


def _routing_events(root: Path) -> list[dict]:
    return [e for e in read_jsonl_tail(root / "trace.jsonl") if e["kind"].startswith("agent.routing")]


def test_route_passthrough_in_duplicate_is_journalled_as_a_warning(tmp_path, monkeypatch):
    root = _hook_root(tmp_path, monkeypatch, enabled=False)
    (root / store_module.STORE_FILE).write_text(json.dumps(
        {"schema_version": 1, "revision": 1, "roles": {"qa": {"candidates": [ref("disparu")], "allow_general_fallback": False}}}),
        encoding="utf-8")
    output = routing_hook.run(call("[general] [qa] Relire"), root)
    assert decision_of(output) != "deny"
    [event] = [e for e in _routing_events(root) if e["kind"] == "agent.routing.decided"]
    assert event["level"] == "warning" and event["data"]["reason"] == "role_passthrough"
    assert "le CLI garde la main" in event["message"]


def test_route_with_a_corrupt_role_file_in_auto_keeps_profile_routing(tmp_path, monkeypatch):
    root = _hook_root(tmp_path, monkeypatch, enabled=True, general=[ref("grand")])
    (root / store_module.STORE_FILE).write_text("{abîmé", encoding="utf-8")
    assert routed(routing_hook.run(call("[general] [qa] Relire"), root)) == "grand"
    [event] = [e for e in _routing_events(root) if e["kind"] == "agent.routing.decided"]
    assert event["data"]["provenance"] == "inherited:general"


def test_route_explicit_role_in_duplicate_leaves_role_less_calls_untouched(tmp_path, monkeypatch):
    root = _hook_root(tmp_path, monkeypatch, enabled=False, general=[ref("grand")])
    RoleRoutingStore(root).put("qa", {"candidates": [ref("petit")]}, "rr-0")
    output = routing_hook.run(call("[general] Résumer"), root)
    assert routed(output) == "" and not [e for e in _routing_events(root) if e["kind"] == "agent.routing.decided"]


def test_route_a_policy_that_raises_never_blocks_the_call(tmp_path, monkeypatch):
    root = _hook_root(tmp_path, monkeypatch, enabled=True)

    def broken(_root):
        raise RuntimeError("boom")

    monkeypatch.setattr(store_module, "load_document", broken)
    output = routing_hook.run(call("[general] [qa] Relire"), root)
    assert decision_of(output) != "deny"
    assert any(e["kind"] == "agent.routing.failed" and e["data"]["code"] == "routing_hook_failed" for e in _routing_events(root))


def test_route_coder_alone_in_auto_uses_its_default_code_profile(tmp_path, monkeypatch):
    root = _hook_root(tmp_path, monkeypatch, enabled=True, code=[ref("petit")], general=[ref("grand")])
    assert routed(routing_hook.run(call("[coder] Écrire le module"), root)) == "petit"
    [event] = [e for e in _routing_events(root) if e["kind"] == "agent.routing.decided"]
    assert (event["data"]["profile"], event["data"]["role_id"], event["data"]["provenance"]) == ("code", "coder", "inherited:code")


async def test_http_a_successful_write_whose_reread_fails_stays_ok_with_a_degraded_snapshot(tmp_path):
    journal = _Journal()

    def settings():
        # Seule la relecture lit les réglages : l'écriture réussit, l'instantané qui suit échoue.
        raise OSError("disque")

    async def candidates():
        return pool(), {}

    api = SubagentRoleRoutingApi(RoleRoutingStore(tmp_path), settings=settings, candidates=candidates, journal=journal)
    app = web.Application()
    app.add_routes(api.routes())
    async with TestClient(TestServer(app)) as client:
        response = await client.put(f"{ROUTE}/reviewer", json={"base_revision": "rr-0", "candidates": [ref("petit")]})
        body = await response.json()
        read = await client.get(ROUTE)
        read_body = await read.json()
    assert response.status == 200 and body["ok"] is True
    assert body["snapshot"]["degraded"]["code"] == "role_routing_snapshot_failed"
    assert RoleRoutingStore(tmp_path).load().document.for_role("qa") is not None
    assert read.status == 500 and read_body["code"] == "role_routing_snapshot_failed"
    saved = next(data for kind, _l, data in journal.events if kind == "subagent_role_routing.saved")
    assert (saved["role_id"], saved["role_marker"]) == ("qa", "reviewer")

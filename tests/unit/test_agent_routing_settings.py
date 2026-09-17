"""La politique d'aiguillage enregistrée : ce qui survit, ce qui est refusé.

Un réglage qui disparaît sans le dire est pire qu'une erreur : l'utilisateur
croit avoir choisi. Ces tests tiennent surtout à ça — une écriture invalide ne
mord pas sur les réglages précédents, et une préférence devenue indisponible
reste affichée au lieu d'être effacée.
"""

from __future__ import annotations

import json

import pytest

from jarvis.domain import routing
from jarvis.domain.routing import CandidateRef, RoutingError, resolve
from jarvis.runtime import agent_routing, cli_catalog

CLAUDE = {
    "id": "claude",
    "label": "Claude Code",
    "model_provider": "anthropic",
    "capabilities": [routing.CODE, routing.SEMANTIC],
    "available": True,
    "error": "",
}
CODEX = {
    "id": "codex",
    "label": "Codex CLI",
    "model_provider": "openai",
    "capabilities": [routing.CODE, routing.SEMANTIC],
    "available": False,
    "error": "« codex » est introuvable dans le PATH.",
}
MODELS = {
    "anthropic": [{"id": "modele-a", "label": "Modèle A"}, {"id": "modele-b", "label": "Modèle B"}],
    "openai": [{"id": "modele-o", "label": "Modèle O"}],
}


def saved(*candidates: dict, profile: str = "code", **entry) -> dict:
    return {
        agent_routing.SETTING_KEY: {
            "enabled": True,
            "profiles": {profile: {"candidates": list(candidates), **entry}},
        }
    }


# ------------------------------------------------------------------- lecture


def test_settings_without_any_routing_keep_today_s_behaviour():
    policy = agent_routing.load_policy({})

    assert policy.enabled is False
    # Les quatre profils existent quand même : l'écran doit pouvoir les montrer.
    assert [entry.profile for entry in policy.profiles] == list(routing.TASK_PROFILE_IDS)
    assert all(entry.candidates == () for entry in policy.profiles)


def test_a_damaged_routing_block_never_prevents_the_screen_from_opening():
    for broken in ("n'importe quoi", [], {"profiles": "cassé"}, {"profiles": {"code": 7}}):
        policy = agent_routing.load_policy({agent_routing.SETTING_KEY: broken})
        assert [entry.profile for entry in policy.profiles] == list(routing.TASK_PROFILE_IDS)


def test_an_unreadable_candidate_is_dropped_without_losing_the_others():
    policy = agent_routing.load_policy(saved({"agent": "claude", "model": "modele-a"}, "cassé", {"model": "sans-agent"}))
    assert policy.for_profile("code").candidates == (CandidateRef("claude", "modele-a"),)


def test_a_profile_absent_from_the_file_is_allowed_by_default():
    policy = agent_routing.load_policy(saved({"agent": "claude"}))
    general = policy.for_profile("general")
    assert (general.enabled, general.allow_general_fallback, general.candidates) == (True, True, ())


# ------------------------------------------------------------------ écriture


def test_a_policy_survives_the_round_trip_through_the_settings_file(tmp_path):
    settings: dict = {}
    agent_routing.apply(
        settings,
        {
            "enabled": True,
            "profiles": {
                "code": {"candidates": [{"agent": "claude", "model": "modele-a"}, {"agent": "codex", "model": ""}]},
                "fast": {"enabled": False, "allow_general_fallback": False},
            },
        },
    )

    # Tel qu'il sera relu au prochain démarrage : par le fichier, pas par la mémoire.
    path = tmp_path / "control-center-settings.json"
    path.write_text(json.dumps(settings), encoding="utf-8")
    policy = agent_routing.load_policy(json.loads(path.read_text(encoding="utf-8")))

    assert policy.enabled is True
    assert policy.for_profile("code").candidates == (CandidateRef("claude", "modele-a"), CandidateRef("codex", ""))
    fast = policy.for_profile("fast")
    assert (fast.enabled, fast.allow_general_fallback) == (False, False)


def test_a_partial_save_leaves_the_untouched_profiles_alone():
    settings = saved({"agent": "claude", "model": "modele-a"})
    agent_routing.apply(settings, {"profiles": {"general": {"candidates": [{"agent": "codex"}]}}})

    policy = agent_routing.load_policy(settings)
    assert policy.for_profile("code").candidates == (CandidateRef("claude", "modele-a"),)
    assert policy.for_profile("general").candidates == (CandidateRef("codex", ""),)
    # `enabled` non fourni : la valeur en place ne bouge pas.
    assert policy.enabled is True


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"profiles": {"kode": {"candidates": []}}}, "routing_unknown_profile"),
        ({"profiles": {"code": {"candidates": [{"agent": "astra"}]}}}, "routing_unknown_agent"),
        ({"profiles": {"code": {"candidates": [{"agent": "claude"}, {"agent": "claude"}]}}}, "routing_duplicate_candidate"),
        ({"profiles": {"code": {"candidates": "claude"}}}, "routing_bad_candidates"),
        ({"profiles": {"code": {"candidates": ["claude:modele-a"]}}}, "routing_bad_candidate"),
        ({"profiles": []}, "routing_bad_payload"),
    ],
)
def test_an_invalid_write_is_refused_whole_and_changes_nothing(payload, code):
    settings = saved({"agent": "claude", "model": "modele-a"})
    before = json.dumps(settings, sort_keys=True)

    with pytest.raises(RoutingError) as error:
        agent_routing.apply(settings, payload)

    assert error.value.code == code
    assert json.dumps(settings, sort_keys=True) == before


def test_an_agent_that_is_not_installed_can_still_be_chosen_in_advance():
    """La disponibilité se mesure au moment d'aiguiller, pas au moment de régler :
    interdire d'enregistrer un CLI éteint rendrait les réglages inutilisables."""

    settings: dict = {}
    agent_routing.apply(settings, {"profiles": {"code": {"candidates": [{"agent": "codex", "model": "modele-o"}]}}})
    assert agent_routing.load_policy(settings).for_profile("code").candidates == (CandidateRef("codex", "modele-o"),)


# ----------------------------------------------------------------- candidats


def test_the_candidates_come_from_what_is_installed_and_from_the_live_catalogue():
    candidates = agent_routing.build_candidates([CLAUDE, CODEX], MODELS)

    keys = [(item.agent, item.model) for item in candidates]
    # Le « modèle par défaut » d'abord, puis ce que le fournisseur déclare.
    assert keys == [
        ("claude", ""),
        ("claude", "modele-a"),
        ("claude", "modele-b"),
        ("codex", ""),
        ("codex", "modele-o"),
    ]
    assert all(item.available for item in candidates if item.agent == "claude")
    # Un CLI absent rend tous ses couples inutilisables, avec la raison mesurée.
    absent = [item for item in candidates if item.agent == "codex"]
    assert all(not item.available and "PATH" in item.unavailable_reason for item in absent)


def test_a_saved_candidate_that_left_the_catalogue_stays_visible_and_unusable():
    policy = agent_routing.load_policy(saved({"agent": "claude", "model": "modele-disparu"}))
    enriched = agent_routing.with_saved(agent_routing.build_candidates([CLAUDE], MODELS), policy)

    ghost = next(item for item in enriched if item.model == "modele-disparu")
    assert ghost.available is False
    assert ghost.unavailable_reason == agent_routing.MISSING_MODEL_REASON
    # Et il n'est pas sélectionnable pour autant.
    assert all(not (item.available and item.model == "modele-disparu") for item in enriched)


def test_the_candidates_are_also_served_grouped_by_harness_for_a_two_step_choice():
    """L'écran choisit un harness puis un de ses modèles : une liste unique de
    tous les couples est illisible passé quelques modèles."""

    groups = agent_routing.group_by_harness(agent_routing.build_candidates([CLAUDE, CODEX], MODELS))

    assert [group["id"] for group in groups] == ["claude", "codex"]
    claude = groups[0]
    assert claude["label"] == "Claude Code"
    # Le défaut du CLI d'abord, puis les modèles du fournisseur — et seulement
    # ceux de ce harness.
    assert [entry["model"] for entry in claude["models"]] == ["", "modele-a", "modele-b"]
    assert claude["models"][0]["label"] == agent_routing.DEFAULT_MODEL_LABEL
    assert claude["models"][1]["label"] == "Modèle A"
    assert claude["available"] is True
    # Un CLI absent reste proposé, avec la raison mesurée : le cacher ferait
    # croire qu'il n'existe pas.
    codex = groups[1]
    assert codex["available"] is False and "PATH" in codex["unavailable_reason"]
    assert [entry["model"] for entry in codex["models"]] == ["", "modele-o"]
    assert all(not entry["available"] for entry in codex["models"])


def test_a_saved_candidate_that_vanished_keeps_its_place_in_the_two_step_choice():
    policy = agent_routing.load_policy(saved({"agent": "claude", "model": "modele-disparu"}))
    enriched = agent_routing.with_saved(agent_routing.build_candidates([CLAUDE], MODELS), policy)

    claude = next(group for group in agent_routing.group_by_harness(enriched) if group["id"] == "claude")

    ghost = next(entry for entry in claude["models"] if entry["model"] == "modele-disparu")
    assert ghost["available"] is False and ghost["unavailable_reason"] == agent_routing.MISSING_MODEL_REASON
    # Un modèle disparu ne rend pas tout le harness inutilisable.
    assert claude["available"] is True and claude["unavailable_reason"] == ""


def test_a_candidate_alive_in_the_catalogue_is_still_not_eligible_if_it_is_not_allowed():
    """Le catalogue du fournisseur propose ; seuls les réglages autorisent."""

    settings = saved({"agent": "claude", "model": "modele-a"})
    policy = agent_routing.load_policy(settings)
    candidates = agent_routing.build_candidates([CLAUDE], MODELS)

    decision = resolve(routing.RoutingIntent(profile="code"), policy, candidates)

    assert decision.model == "modele-a"
    assert [entry["model"] for entry in decision.as_dict()["considered"]] == ["modele-a"]


def test_the_real_cli_specs_declare_the_capabilities_the_profiles_need():
    """Sans capacité déclarée, aucun profil exigeant ne trouverait jamais personne."""

    claude = cli_catalog.spec_for("claude")
    assert routing.CODE in claude.capabilities and routing.SEMANTIC in claude.capabilities
    assert set(cli_catalog.spec_for("codex").capabilities) <= set(routing.CAPABILITIES)
    assert set(claude.capabilities) <= set(routing.CAPABILITIES)
    # Décrites au client comme le reste de la fiche du CLI.
    described = cli_catalog.describe(claude, command="claude", detection={"available": True})
    assert described["capabilities"] == list(claude.capabilities)


# -------------------------------------------------------------- description


def test_the_described_payload_carries_no_secret_and_no_hardcoded_model():
    settings = {
        **saved({"agent": "claude", "model": "modele-a"}),
        "credentials": [{"id": "c1", "provider": "anthropic", "value": "sk-ultra-secret"}],
        "openai_api_key": "sk-autre-secret",
    }
    policy = agent_routing.load_policy(settings)
    payload = agent_routing.describe(policy, agent_routing.build_candidates([CLAUDE], MODELS))

    blob = json.dumps(payload, ensure_ascii=False)
    assert "secret" not in blob and "sk-" not in blob
    assert [entry["id"] for entry in payload["profiles"]] == list(routing.TASK_PROFILE_IDS)
    # Les modèles proposés viennent du catalogue passé, pas du code.
    assert {entry["model"] for entry in payload["candidates"] if entry["model"]} == {"modele-a", "modele-b"}
    # Les deux niveaux décrivent les mêmes couples : l'écran regroupe, il
    # n'invente rien.
    grouped = {(group["id"], entry["model"]) for group in payload["harnesses"] for entry in group["models"]}
    assert grouped == {(entry["agent"], entry["model"]) for entry in payload["candidates"]}

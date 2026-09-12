"""Le cerveau dit le besoin, les réglages disent le droit, le runtime tranche.

Tout ce qui est prouvé ici est déterministe et sans I/O : les candidats sont
fabriqués à la main, comme le feront `cli_catalog` et `model_catalog` à
l'exécution. Ce qui compte n'est pas qu'un modèle soit choisi, mais qu'aucun
modèle interdit, absent ou incapable ne puisse l'être.
"""

from __future__ import annotations

import pytest

from jarvis.domain.routing import (
    CODE,
    COMPUTER_USE,
    REASON_COMPATIBILITY,
    REASON_FALLBACK,
    REASON_GENERAL_FALLBACK,
    REASON_OVERRIDE,
    REASON_PREFERRED,
    REJECT_AGENT_UNAVAILABLE,
    REJECT_MISSING_CAPABILITY,
    REJECT_MODEL_UNAVAILABLE,
    REJECT_NOT_ALLOWED,
    REJECT_UNKNOWN,
    SEMANTIC,
    TASK_PROFILE_IDS,
    CandidateRef,
    ModelCandidate,
    NoEligibleCandidateError,
    ProfilePolicy,
    RoutingError,
    RoutingIntent,
    RoutingPolicy,
    describe_profiles,
    profile_spec,
    resolve,
)

CAPABLE = frozenset({CODE, SEMANTIC})


def candidate(agent: str, model: str, *, available: bool = True, capabilities=CAPABLE, reason: str = "") -> ModelCandidate:
    return ModelCandidate(
        agent=agent,
        model=model,
        capabilities=frozenset(capabilities),
        available=available,
        unavailable_reason=reason,
    )


def ref(agent: str, model: str = "") -> CandidateRef:
    return CandidateRef(agent=agent, model=model)


def policy(*candidates: CandidateRef, profile: str = "code", **options) -> RoutingPolicy:
    return RoutingPolicy(enabled=True, profiles=(ProfilePolicy(profile=profile, candidates=candidates, **options),))


def intent(profile: str = "code", **options) -> RoutingIntent:
    return RoutingIntent(profile=profile, **options)


# ------------------------------------------------------------------ vocabulaire


def test_the_four_profiles_cover_the_uses_the_user_named():
    assert TASK_PROFILE_IDS == ("desktop", "code", "fast", "general")
    # Un profil impose ses capacités : « code avancé » ne peut pas tomber sur un
    # candidat qui ne sait pas coder, quoi qu'autorise la politique.
    assert profile_spec("code").requires == (CODE,)
    assert profile_spec("desktop").requires == (COMPUTER_USE,)
    assert profile_spec("general").requires == ()


def test_an_unknown_profile_is_refused_rather_than_silently_general():
    with pytest.raises(RoutingError) as error:
        profile_spec("kode")
    assert error.value.code == "routing_unknown_profile"


def test_the_profiles_are_described_without_a_single_model_name():
    described = describe_profiles()
    assert [entry["id"] for entry in described] == list(TASK_PROFILE_IDS)
    assert all(entry["label"] and entry["description"] for entry in described)


def test_a_candidate_is_read_as_an_object_never_as_a_glued_string():
    parsed = CandidateRef.parse({"agent": "Claude", "model": "opus-x"})
    assert parsed == ref("claude", "opus-x")
    for bad in ("claude:opus", {"model": "opus"}, None):
        with pytest.raises(RoutingError) as error:
            CandidateRef.parse(bad)
        assert error.value.code == "routing_bad_candidate"


# -------------------------------------------------------------- compatibilité


def test_without_an_enabled_policy_nothing_changes_for_the_running_agent():
    """Le modèle configuré du CLI reste maître : c'est une décision, pas un trou."""

    decision = resolve(intent(), RoutingPolicy(), [candidate("claude", "opus-x")])
    assert decision.reason == REASON_COMPATIBILITY
    assert (decision.agent, decision.model) == ("", "")


def test_a_profile_left_empty_falls_back_to_the_current_behaviour():
    enabled_but_empty = RoutingPolicy(enabled=True, profiles=(ProfilePolicy(profile="code"),))
    assert resolve(intent(), enabled_but_empty, [candidate("claude", "opus-x")]).reason == REASON_COMPATIBILITY


def test_a_profile_switched_off_does_not_route_either():
    off = policy(ref("claude", "opus-x"), enabled=False)
    assert resolve(intent(), off, [candidate("claude", "opus-x")]).reason == REASON_COMPATIBILITY


# ------------------------------------------------------------------- sélection


def test_the_first_allowed_candidate_wins_and_the_order_is_the_preference():
    chosen = policy(ref("claude", "opus-x"), ref("codex", "gpt-y"))
    decision = resolve(intent(), chosen, [candidate("claude", "opus-x"), candidate("codex", "gpt-y")])
    assert (decision.agent, decision.model, decision.reason) == ("claude", "opus-x", REASON_PREFERRED)
    assert decision.fallback_from is None
    # Le choix est explicable sans raisonnement caché : un verdict par candidat vu.
    assert [entry["eligible"] for entry in decision.as_dict()["considered"]] == [True]


def test_the_same_inputs_always_give_the_same_answer():
    fixed = policy(ref("claude", "opus-x"), ref("codex", "gpt-y"))
    pool = [candidate("codex", "gpt-y"), candidate("claude", "opus-x")]
    assert {resolve(intent(), fixed, pool).ref for _ in range(5)} == {ref("claude", "opus-x")}


def test_an_unavailable_preferred_model_hands_over_to_the_next_allowed_one():
    chosen = policy(ref("claude", "opus-x"), ref("codex", "gpt-y"))
    pool = [candidate("claude", "opus-x", available=False, reason="Modèle retiré du service."), candidate("codex", "gpt-y")]

    decision = resolve(intent(), chosen, pool)

    assert (decision.agent, decision.model, decision.reason) == ("codex", "gpt-y", REASON_FALLBACK)
    assert decision.fallback_from == ref("claude", "opus-x")
    assert decision.fallback_code == REJECT_MODEL_UNAVAILABLE
    # La raison du refus voyage avec la décision : de quoi déboguer un mauvais
    # choix sans relire les logs du fournisseur.
    assert decision.as_dict()["considered"][0]["detail"] == "Modèle retiré du service."


def test_an_uninstalled_agent_is_rejected_by_its_own_code():
    chosen = policy(ref("codex"), ref("claude", "opus-x"))
    pool = [candidate("codex", "", available=False, reason="« codex » est introuvable dans le PATH."), candidate("claude", "opus-x")]

    decision = resolve(intent(), chosen, pool)

    assert decision.ref == ref("claude", "opus-x")
    assert decision.fallback_code == REJECT_AGENT_UNAVAILABLE


def test_a_candidate_that_left_the_provider_catalogue_is_reported_unknown_not_used():
    chosen = policy(ref("claude", "modele-disparu"), ref("claude", "opus-x"))
    decision = resolve(intent(), chosen, [candidate("claude", "opus-x")])
    assert decision.ref == ref("claude", "opus-x")
    assert decision.fallback_code == REJECT_UNKNOWN


def test_a_candidate_without_the_required_capability_is_never_selected():
    chosen = policy(ref("claude", "petit"), ref("claude", "opus-x"))
    pool = [candidate("claude", "petit", capabilities={SEMANTIC}), candidate("claude", "opus-x")]

    decision = resolve(intent(), chosen, pool)

    assert decision.ref == ref("claude", "opus-x")
    assert decision.fallback_code == REJECT_MISSING_CAPABILITY
    assert decision.as_dict()["considered"][0]["detail"] == CODE


def test_a_capability_asked_by_the_task_itself_also_filters():
    """Le profil pose un plancher ; l'intention peut exiger davantage, jamais moins."""

    chosen = policy(ref("claude", "opus-x"), ref("codex", "gpt-y"), profile="general")
    pool = [candidate("claude", "opus-x", capabilities={CODE}), candidate("codex", "gpt-y", capabilities={CODE, COMPUTER_USE})]

    decision = resolve(intent("general", requires=frozenset({COMPUTER_USE})), chosen, pool)

    assert decision.ref == ref("codex", "gpt-y")


def test_a_candidate_the_user_did_not_allow_stays_out_even_when_it_is_perfect():
    """Le catalogue du fournisseur ne rend éligible que ce que les réglages ouvrent."""

    chosen = policy(ref("claude", "opus-x"))
    pool = [candidate("claude", "opus-x"), candidate("codex", "gpt-y")]

    decision = resolve(intent(), chosen, pool)

    assert decision.ref == ref("claude", "opus-x")
    assert [entry["model"] for entry in decision.as_dict()["considered"]] == ["opus-x"]


# --------------------------------------------------------------------- recours


def test_an_exhausted_profile_may_borrow_the_general_list():
    chosen = RoutingPolicy(
        enabled=True,
        profiles=(
            ProfilePolicy(profile="code", candidates=(ref("claude", "opus-x"),)),
            ProfilePolicy(profile="general", candidates=(ref("codex", "gpt-y"),)),
        ),
    )
    pool = [candidate("claude", "opus-x", available=False, reason="Clé refusée."), candidate("codex", "gpt-y")]

    decision = resolve(intent(), chosen, pool)

    assert (decision.ref, decision.reason) == (ref("codex", "gpt-y"), REASON_GENERAL_FALLBACK)
    assert decision.fallback_from == ref("claude", "opus-x")


def test_a_profile_that_refuses_the_general_list_fails_loudly_instead():
    chosen = RoutingPolicy(
        enabled=True,
        profiles=(
            ProfilePolicy(profile="code", candidates=(ref("claude", "opus-x"),), allow_general_fallback=False),
            ProfilePolicy(profile="general", candidates=(ref("codex", "gpt-y"),)),
        ),
    )
    pool = [candidate("claude", "opus-x", available=False), candidate("codex", "gpt-y")]

    with pytest.raises(NoEligibleCandidateError) as error:
        resolve(intent(), chosen, pool)
    assert error.value.code == "routing_no_candidate"


def test_no_usable_candidate_names_every_refusal_rather_than_taking_a_forbidden_one():
    chosen = policy(ref("claude", "opus-x"), ref("codex", "gpt-y"))
    pool = [
        candidate("claude", "opus-x", available=False, reason="Clé refusée."),
        candidate("codex", "gpt-y", capabilities={SEMANTIC}),
        candidate("claude", "libre"),
    ]

    with pytest.raises(NoEligibleCandidateError) as error:
        resolve(intent(), chosen, pool)

    codes = [verdict.code for verdict in error.value.verdicts]
    assert codes == [REJECT_MODEL_UNAVAILABLE, REJECT_MISSING_CAPABILITY]


# ----------------------------------------------------------------- imposition


def test_a_valid_user_override_wins_over_the_preferred_candidate():
    chosen = policy(ref("claude", "opus-x"), ref("codex", "gpt-y"))
    pool = [candidate("claude", "opus-x"), candidate("codex", "gpt-y")]

    decision = resolve(intent(override=ref("codex", "gpt-y")), chosen, pool)

    assert (decision.ref, decision.reason) == (ref("codex", "gpt-y"), REASON_OVERRIDE)


def test_an_override_outside_the_allowlist_is_refused():
    """Imposer n'est pas contourner : la politique reste au-dessus."""

    chosen = policy(ref("claude", "opus-x"))
    pool = [candidate("claude", "opus-x"), candidate("codex", "gpt-y")]

    with pytest.raises(NoEligibleCandidateError) as error:
        resolve(intent(override=ref("codex", "gpt-y")), chosen, pool)

    assert [verdict.code for verdict in error.value.verdicts] == [REJECT_NOT_ALLOWED]


def test_an_override_on_an_unavailable_candidate_is_refused_too():
    chosen = policy(ref("claude", "opus-x"))
    pool = [candidate("claude", "opus-x", available=False, reason="Clé refusée.")]

    with pytest.raises(NoEligibleCandidateError) as error:
        resolve(intent(override=ref("claude", "opus-x")), chosen, pool)

    assert [verdict.code for verdict in error.value.verdicts] == [REJECT_MODEL_UNAVAILABLE]


def test_an_override_still_needs_the_capabilities_of_the_profile():
    chosen = policy(ref("claude", "petit"))
    pool = [candidate("claude", "petit", capabilities={SEMANTIC})]

    with pytest.raises(NoEligibleCandidateError) as error:
        resolve(intent(override=ref("claude", "petit")), chosen, pool)

    assert [verdict.code for verdict in error.value.verdicts] == [REJECT_MISSING_CAPABILITY]


def test_an_override_is_free_while_no_policy_constrains_the_profile():
    """Sans politique activée, l'utilisateur garde la main — mais le candidat
    doit exister et convenir : la disponibilité n'est jamais négociable."""

    decision = resolve(intent(override=ref("claude", "opus-x")), RoutingPolicy(), [candidate("claude", "opus-x")])
    assert decision.reason == REASON_OVERRIDE

    with pytest.raises(NoEligibleCandidateError):
        resolve(intent(override=ref("claude", "fantome")), RoutingPolicy(), [candidate("claude", "opus-x")])

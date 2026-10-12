"""Branches, comparaison, composition, lecture, explorateur, modèles, rédaction : les outils `jarvis-presentation` contre un vrai Core (Slice 21).

Même monde que `test_presentation_studio_mcp.py` (vrai Core, client espionné, Control Center factice). Contrat : `docs/presentation-studio.md` >
*Agent and voice operations (Slice 21)*.
"""

from __future__ import annotations

import json

import pytest

from jarvis.runtime.presentation_studio_mcp_support import PresentationToolError
from tests.unit.presentation_studio_mcp_world import I1, I2, I3, S1, S2, S3, World, bare_presentation, open_world

ATTESTED = ("GET", "/api/presentation-studio/agent/turn")


@pytest.fixture
async def world(tmp_path):
    core, built = await open_world(tmp_path)
    try:
        yield built
    finally:
        await core.__aexit__(None, None, None)


async def refused(awaitable) -> PresentationToolError:
    with pytest.raises(PresentationToolError) as caught:
        await awaitable
    return caught.value


async def numbered(world: World) -> dict[int, str]:
    graph = await world.tools.inspect("presentation")
    return {v["number"]: v["variant_id"] for v in graph["variants"]["items"]}


# ------------------------------------------------------------------ branches : créer, renommer, activer, archiver (confirmation canonique)

async def test_make_a_variant_branches_the_active_one_and_says_its_number(world):
    out = await world.tools.variant("create", title="Version sobre", rationale="Moins de couleurs")
    assert out["status"] == "created" and out["variant_number"] == 2 and out["speech"] == "say" and "2" in out["say"]
    ids = await numbered(world)
    assert set(ids) == {1, 2} and ids[2] == out["variant_id"]
    (args, _), = world.spy.named("presentation_studio_create_branch")
    assert args[1]["actor"] == "brain" and "source_variant_id" not in args[1]
    renamed = await world.tools.variant("rename", variant_id=ids[2], title="Sobre")
    assert renamed["status"] == "renamed" and renamed["speech"] == "silent"
    activated = await world.tools.variant("activate", variant_id=ids[2])
    assert activated["status"] == "activated"
    assert (await world.tools.inspect("presentation"))["active_variant_id"] == ids[2]


async def test_a_branch_needs_a_title_and_a_known_source(world):
    assert (await refused(world.tools.variant("create"))).code == "title_required"
    bad = await refused(world.tools.variant("create", title="x", source_variant_id="psv_" + "0" * 32))
    assert bad.code == "presentation_studio_unknown_variant" and bad.choices["presentations"]


async def test_deleting_a_branch_is_archive_behind_plan_token_and_the_users_yes(world):
    await world.tools.variant("create", title="B")
    ids = await numbered(world)
    # no plan yet: the model cannot invent a token or skip the question
    for kwargs in ({}, {"confirmation": "psk_1.deadbeef", "confirmed": True}):
        error = await refused(world.tools.variant("archive", variant_id=ids[2], **kwargs))
        assert error.code == "presentation_studio_confirmation_required"
    assert not world.spy.named("presentation_studio_archive"), "Core was never asked to archive"
    plan = await world.tools.variant("archive_plan", variant_id=ids[2])
    assert plan["status"] == "confirmation_required" and plan["speech"] == "say" and "2" in plan["say"]
    assert [a["number"] for a in plan["affected"]["items"]] == [2] and plan["confirmation"].startswith("psk_")
    # the plan alone changes nothing
    assert set(await numbered(world)) == {1, 2}
    # a token without the user's yes (confirmed missing) is not enough either
    error = await refused(world.tools.variant("archive", variant_id=ids[2], confirmation=plan["confirmation"]))
    assert error.code == "presentation_studio_confirmation_required"
    done = await world.tools.variant("archive", variant_id=ids[2], confirmation=plan["confirmation"], confirmed=True)
    assert done["status"] == "archived" and done["speech"] == "say"
    assert set(await numbered(world)) == {1}
    # replayed: the plan is spent, nothing is archived twice
    again = await refused(world.tools.variant("archive", variant_id=ids[2], confirmation=plan["confirmation"], confirmed=True))
    assert again.code == "presentation_studio_confirmation_required"
    restored = await world.tools.variant("restore", variant_id=ids[2])
    assert restored["status"] == "restored" and set(await numbered(world)) == {1, 2}


async def test_core_stays_the_judge_of_the_token_when_the_set_changed_since_the_plan(world):
    await world.tools.variant("create", title="B")
    ids = await numbered(world)
    plan = await world.tools.variant("archive_plan", variant_id=ids[2])
    await world.tools.variant("create", title="Enfant de B", source_variant_id=ids[2])   # the set to archive grew
    error = await refused(world.tools.variant("archive", variant_id=ids[2], confirmation=plan["confirmation"], confirmed=True))
    assert error.code == "presentation_studio_confirmation_stale"
    assert set(await numbered(world)) == {1, 2, 3}, "nothing was archived"


async def test_the_active_variant_is_protected_and_the_plan_says_so(world):
    plan = await world.tools.variant("archive_plan", variant_id=world.vid)
    assert plan["status"] == "blocked" or plan.get("requires_new_active") or plan.get("blocked")
    assert plan["speech"] == "say" and not plan.get("confirmation")


async def test_the_fallback_art_direction_is_created_on_demand_and_said(world):
    pid, vid = await bare_presentation(world.core)
    _, doc = await world.core.call("GET", f"/{pid}/variants/{vid}")
    assert not doc.get("art_direction_id")
    out = await world.tools.variant("art_direction_fallback", presentation_id=pid, variant_id=vid)
    assert out["status"] == "created" and out["provenance"] == "fallback" and out["speech"] == "say"
    (args, _), = world.spy.named("presentation_studio_fallback_art_direction")
    assert args[2] == {"expected_variant_revision": doc["revision"]}, "the revision is read, not invented"


# ------------------------------------------------------------------ comparer et mélanger

async def test_compare_these_four_opens_a_four_up_view_and_stays_silent(world):
    for title in ("B", "C", "D"):
        await world.tools.variant("create", title=title)
    ids = await numbered(world)
    out = await world.tools.compare("open", variant_ids=[ids[1], ids[2], ids[3], ids[4]])
    assert out["layout"] == "four_up" and out["speech"] == "silent" and len(out["variants"]) == 4
    assert all(v["revision"] >= 1 for v in out["variants"])
    focus = await world.tools.compare("focus", pair=[ids[1], ids[3]])
    assert focus["layout"] == "focus" and focus["pair"] == [ids[1], ids[3]]
    nav = await world.tools.compare("navigate", variant_id=ids[1], step="next")
    assert nav["navigation"]["origin"]["variant_id"] == ids[1]
    mode = await world.tools.compare("mode", mode="independent")
    assert mode["mode"] == "independent"
    closed = await world.tools.compare("close")
    assert closed["active"] is False and (await world.tools.inspect("compare"))["active"] is False


async def test_a_comparison_needs_two_or_four_known_live_variants(world):
    ids = await numbered(world)
    assert (await refused(world.tools.compare("open", variant_ids=[ids[1]]))).code == "invalid_selection"
    assert (await refused(world.tools.compare("open", variant_ids=["psv_nope", ids[1]]))).code == "invalid_id"
    assert (await refused(world.tools.compare("navigate", variant_id=ids[1]))).code == "invalid_target"
    unknown = await refused(world.tools.compare("open", variant_ids=[ids[1], "psv_" + "0" * 32]))
    assert unknown.code == "presentation_studio_unknown_variant"


async def test_compose_plans_then_creates_a_new_child_and_leaves_the_sources_alone(world):
    await world.tools.variant("create", title="Autre ton")
    ids = await numbered(world)
    before = [json.dumps((await world.core.call("GET", f"/{world.pid}/variants/{v}"))[1], sort_keys=True) for v in ids.values()]
    request = {"title": "Mélange", "base": ids[1], "narrative": ids[2]}
    early = await refused(world.tools.compose("create", request))
    assert early.code == "plan_required"
    planned = await world.tools.compose("plan", request)
    assert planned["ok_plan"] is True and planned["conflicts"] == [] and planned["speech"] == "silent"
    out = await world.tools.compose("create", request)
    assert out["status"] == "created" and out["variant_number"] == 3 and out["speech"] == "say" and out["activated"] is not True
    after = [json.dumps((await world.core.call("GET", f"/{world.pid}/variants/{v}"))[1], sort_keys=True) for v in ids.values()]
    assert after == before, "the sources are inputs"
    provenance = await world.tools.inspect("composition", variant_id=out["variant_id"])
    assert {d["dimension"] for d in provenance["dimensions"]} == {"scenes", "narrative", "motion", "art_direction"}
    (args, _), = world.spy.named("presentation_studio_compose")
    assert args[1]["actor"] == "brain" and args[1]["source_revisions"], "the revisions of the last view are passed"
    stale = await refused(world.tools.compose("create", {**request, "title": "Autre"}))
    assert stale.code == "plan_required", "a different request needs its own plan"


async def test_a_refused_composition_hands_the_conflicts_back_verbatim_with_their_fix(world):
    await world.tools.variant("create", title="B")
    ids = await numbered(world)
    # a scene id that is not a scene of the source: scene_not_in_source
    request = {"title": "Cassé", "base": ids[1], "scenes": [{"from": ids[2], "scene_ids": ["pss_0000000000ff"]}]}
    planned = await world.tools.compose("plan", request)
    assert planned["ok_plan"] is False and planned["conflicts"][0]["code"] == "scene_not_in_source" and planned["conflicts"][0]["fix"]
    error = await refused(world.tools.compose("create", request))
    assert error.code == "plan_required" or "scene_not_in_source" in str(error)


# ------------------------------------------------------------------ lecture, répétition, navigation

async def test_a_user_turn_lets_the_brain_start_a_rehearsal_and_navigation_is_silent(world):
    world.cc.answers[ATTESTED] = (200, {"ok": True, "addressed_user_turn": True})
    started = await world.tools.play("start", role="rehearsal")
    assert started["status"] == "applied" and started["speech"] == "silent" and started["state"]["phase"] == "playing"
    state = (await world.tools.inspect("playback"))["state"]
    assert state["role"] == "rehearsal" and state["presentation_id"] == world.pid and state["stage_object_id"]
    for op, kwargs in (("next", {}), ("previous", {}), ("goto", {"item_id": I3}), ("goto", {"scene_id": S2}), ("goto", {"position": 1}),
                       ("pause", {}), ("resume", {})):
        out = await world.tools.play(op, **kwargs)
        assert out["speech"] == "silent" and "say" not in out, (op, kwargs)
    assert (await world.tools.inspect("playback"))["state"]["scene"]["title"] == "Un"
    stopped = await world.tools.play("stop")
    assert stopped["state"]["phase"] == "stopped" and stopped["speech"] == "silent"


async def test_playback_commands_check_their_arguments_and_core_refusals_say_why(world):
    world.cc.answers[ATTESTED] = (200, {"ok": True, "addressed_user_turn": True})
    assert (await refused(world.tools.play("start", role="presenter"))).code == "invalid_role"
    assert (await refused(world.tools.play("goto"))).code == "invalid_target"
    assert (await refused(world.tools.play("goto", item_id="psi_1", scene_id=S1))).code == "invalid_target"
    assert (await refused(world.tools.play("goto", item_id="not-an-item"))).code == "invalid_id"
    assert (await refused(world.tools.play("reveal", anchor_id="Bad Anchor"))).code == "invalid_id"
    assert (await refused(world.tools.play("jump"))).code == "unknown_op"
    not_running = await refused(world.tools.play("next"))
    assert not_running.code == "not_running"
    await world.tools.play("start", role="rehearsal")
    at_start = await refused(world.tools.play("previous"))
    assert at_start.code == "at_start" and "Refus at_start" in str(at_start)
    twice = await refused(world.tools.play("start", role="rehearsal"))
    assert twice.code == "already_running"


async def test_a_serious_start_without_art_direction_is_refused_with_the_fix(world):
    world.cc.answers[ATTESTED] = (200, {"ok": True, "addressed_user_turn": True})
    pid, vid = await bare_presentation(world.core)
    error = await refused(world.tools.play("start", role="user_presenter", presentation_id=pid, variant_id=vid))
    assert error.code == "presentation_studio_art_direction_required" and "art_direction_fallback" in str(error)
    fixed = await world.tools.variant("art_direction_fallback", presentation_id=pid, variant_id=vid)
    assert fixed["status"] == "created"
    started = await world.tools.play("start", role="user_presenter", presentation_id=pid, variant_id=vid)
    assert started["status"] == "applied" and started["state"]["art_direction"] == "fallback"


# ------------------------------------------------------------------ explorateur et plein écran (page)

async def test_open_the_explorer_sends_the_ids_and_reports_the_mode_the_page_observed(world):
    route = "/api/presentation-studio/explorer/commands"
    world.cc.answers[("POST", route)] = (200, {"state": "opened", "mode": "windowed", "fullscreen": "unsupported",
                                               "presentation_id": world.pid, "variant_id": world.vid})
    out = await world.tools.view("explorer_open", variant_id=world.vid)
    assert out["mode"] == "windowed" and out["speech"] == "silent" and "needs_gesture" not in out
    method, sent_route, body = world.cc.requests[-1]
    assert (method, sent_route) == ("POST", route)
    assert body == {"action": "open", "presentation_id": world.pid, "variant_id": world.vid, "fullscreen": True}
    world.cc.answers[("POST", route)] = (200, {"state": "opened", "mode": "fullscreen_armed", "fullscreen": "needs_gesture"})
    armed = await world.tools.view("explorer_open", fullscreen=True)
    assert armed["needs_gesture"] is True and armed["speech"] == "say" and "clique" in armed["say"]
    world.cc.answers[("POST", route)] = (200, {"state": "closed"})
    assert (await world.tools.view("explorer_close"))["speech"] == "silent"
    assert world.cc.requests[-1][2] == {"action": "close"}


async def test_the_explorer_refusals_come_from_the_page_and_name_their_cause(world):
    route = "/api/presentation-studio/explorer/commands"
    world.cc.answers[("POST", route)] = (200, {"state": "refused", "code": "explorer_run_in_progress", "reason": "lecture"})
    error = await refused(world.tools.view("explorer_open"))
    assert error.code == "explorer_run_in_progress" and "arrête-la d'abord" in str(error) and "Variantes la montre" in str(error)
    world.cc.answers[("POST", route)] = (504, {"ok": False, "code": "explorer_no_visible_page", "error": "aucune page"})
    assert (await refused(world.tools.view("explorer_open"))).code == "explorer_no_visible_page"


async def test_stage_fullscreen_needs_a_run_opens_variants_on_it_and_only_arms_the_variants_stage(world):
    """Slice 09: the run plays in Variants, so `stage_fullscreen_enter` targets the Variants STAGE (`studio-explorer-stage`, the Player and
    its transport), after opening Variants on the run (windowed, receipt); it only ARMS fullscreen: the user's click enters it."""

    error = await refused(world.tools.view("stage_fullscreen_enter"))
    assert error.code == "no_run"
    world.cc.answers[ATTESTED] = (200, {"ok": True, "addressed_user_turn": True})
    world.cc.answers[("POST", "/api/presentation-studio/explorer/commands")] = (200, {"state": "opened", "mode": "windowed"})
    await world.tools.play("start", role="rehearsal")
    stage = (await world.tools.inspect("playback"))["state"]["stage_object_id"]
    assert stage.startswith("variants-run-"), "the run's surface is a Variants surface, never a Board window"
    world.cc.answers[("POST", "/api/fullscreen/commands")] = (200, {"state": "needs_gesture"})
    out = await world.tools.view("stage_fullscreen_enter")
    assert out["needs_gesture"] is True and out["speech"] == "say" and "plein écran" in out["note"]
    assert world.cc.requests[-2][1] == "/api/presentation-studio/explorer/commands"
    assert world.cc.requests[-2][2] == {"action": "open", "presentation_id": world.pid, "variant_id": world.vid, "fullscreen": False}
    assert world.cc.requests[-1][2] == {"action": "enter", "object_id": "studio-explorer-stage", "keys": "none"}
    world.cc.answers[("POST", "/api/presentation-studio/explorer/commands")] = (200, {"state": "refused", "code": "explorer_dialog_open",
                                                                                       "reason": "formulaire"})
    assert (await refused(world.tools.view("stage_fullscreen_enter"))).code == "explorer_dialog_open"
    world.cc.answers[("POST", "/api/fullscreen/commands")] = (200, {"state": "exited"})
    left = await world.tools.view("fullscreen_exit")
    assert left["speech"] == "silent" and world.cc.requests[-1][2] == {"action": "exit"}


async def test_a_start_is_shown_in_variants_and_without_a_visible_page_the_run_pauses_with_a_typed_refusal(world):
    """§ 5 « Voice and MCP » (Slice 09): `presentation_play start` opens Variants on the run (windowed, never fullscreen) with the page's
    receipt; with no visible page to show it, the run is paused and the start answers `surface_unavailable`; never a Board window."""

    world.cc.answers[ATTESTED] = (200, {"ok": True, "addressed_user_turn": True})
    route = "/api/presentation-studio/explorer/commands"
    world.cc.answers[("POST", route)] = (200, {"state": "opened", "mode": "windowed"})
    out = await world.tools.play("start", role="rehearsal")
    assert out["surface"] == "variants" and out["state"]["phase"] == "playing"
    opened = [r for r in world.cc.requests if r[1] == route][-1][2]
    assert opened == {"action": "open", "presentation_id": world.pid, "variant_id": world.vid, "fullscreen": False}
    assert (await world.core.stack.core.scene.snapshot()).objects == (), "never a Board window"
    await world.tools.play("stop")
    world.cc.answers[("POST", route)] = (504, {"ok": False, "code": "explorer_no_visible_page", "error": "aucune page"})
    error = await refused(world.tools.play("start", role="rehearsal"))
    assert error.code == "surface_unavailable" and "mise en pause" in str(error) and "explorer_no_visible_page" in str(error)
    assert (await world.tools.inspect("playback"))["state"]["phase"] == "paused", "Jarvis never presents to an empty screen"


@pytest.mark.parametrize("code, says, never", [
    ("explorer_dialog_open", "un formulaire y est ouvert", "ouvrir l'interface"),
    ("explorer_command_busy", "une autre commande de l'explorateur était en cours", "ouvrir l'interface"),
    ("explorer_no_visible_page", "ouvrir l'interface de JARVIS", "formulaire"),
])
async def test_surface_unavailable_gives_the_advice_of_the_pages_own_reason(world, code, says, never):
    """Slice 09 rework: a page that refused because a form is open or another explorer command was in flight IS visible: the sentence
    never says « open the JARVIS interface » there; it says what to do for that reason, and the run is paused either way."""

    world.cc.answers[ATTESTED] = (200, {"ok": True, "addressed_user_turn": True})
    route = "/api/presentation-studio/explorer/commands"
    status = 504 if code == "explorer_no_visible_page" else 200
    world.cc.answers[("POST", route)] = ((status, {"ok": False, "code": code, "error": "x"}) if status == 504 else
                                         (200, {"state": "refused", "code": code, "reason": "x"}))
    error = await refused(world.tools.play("start", role="rehearsal"))
    text = str(error)
    assert error.code == "surface_unavailable" and code in text and "mise en pause" in text
    assert says in text and never not in text, text
    if code != "explorer_no_visible_page":
        assert "presentation_view window_open" in text and "presentation_play resume" in text
    assert (await world.tools.inspect("playback"))["state"]["phase"] == "paused"


async def test_a_start_waits_for_variants_within_the_pages_own_deadlines_not_30_s(world):
    """Slice 09 rework: the start waits for the page's receipt at most delivery (4 s) + final receipt (10 s) + 2 s margin, then pauses:
    Jarvis never presents to an empty screen for 30 s."""

    from jarvis.domain.presentation_studio_explorer import DELIVERY_DEADLINE_S, WORK_DEADLINE_MAX_S
    from jarvis.runtime.presentation_studio_mcp_tools import HOST_IN_VARIANTS_TIMEOUT_S

    world.cc.answers[ATTESTED] = (200, {"ok": True, "addressed_user_turn": True})
    route = "/api/presentation-studio/explorer/commands"
    world.cc.answers[("POST", route)] = (200, {"state": "opened", "mode": "windowed"})
    await world.tools.play("start", role="rehearsal")
    waited = [t for (_m, r, _b), t in zip(world.cc.requests, world.cc.timeouts) if r == route]
    assert waited == [HOST_IN_VARIANTS_TIMEOUT_S] == [DELIVERY_DEADLINE_S + WORK_DEADLINE_MAX_S + 2.0]
    assert HOST_IN_VARIANTS_TIMEOUT_S <= 16.0


async def test_window_ops_open_and_close_variants_windowed_with_the_pages_receipt(world):
    """The floating window host is retired (Slice 09): `window_open` / `window_close` keep their names for the brain's habits and now
    open / close Variants, windowed, through the explorer's command channel (a receipt, never a blind screen request)."""

    route = "/api/presentation-studio/explorer/commands"
    world.cc.answers[("POST", route)] = (200, {"state": "opened", "mode": "windowed", "presentation_id": world.pid, "variant_id": world.vid})
    out = await world.tools.view("window_open", presentation_id=world.pid)
    assert out["status"] == "opened" and out["mode"] == "windowed"
    assert world.cc.requests[-1][1] == route and world.cc.requests[-1][2] == {"action": "open", "presentation_id": world.pid, "fullscreen": False}
    world.cc.answers[("POST", route)] = (200, {"state": "closed"})
    closed = await world.tools.view("window_close")
    assert closed["status"] == "closed" and world.cc.requests[-1][2] == {"action": "close"}
    assert not [r for r in world.cc.requests if r[1].endswith("/rail/display")], "no screen request for a window that no longer exists"


async def test_the_explorer_mirror_is_read_as_dated_and_advisory(world):
    world.cc.answers[("GET", "/api/presentation-studio/explorer/state")] = (200, {
        "state": "open", "mode": "fullscreen", "presentation_id": world.pid, "variant_id": world.vid, "age_s": 4})
    world.cc.answers[("GET", "/api/fullscreen/state")] = (200, {"state": "entered", "object_id": "x"})
    out = await world.tools.inspect("explorer")
    assert out["explorer"]["state"] == "open" and out["fullscreen"]["state"] == "entered" and "il y a N s" in out["note"]
    # the open explorer is the presentation in question when none is named
    assert (await world.tools.inspect("variant"))["presentation_id"] == world.pid


# ------------------------------------------------------------------ rédaction et modèles

async def test_a_refused_draft_returns_the_complete_report_verbatim_and_writes_nothing(world):
    before = (await world.client.presentation_studio_list())["presentations"]
    out = await world.tools.draft("assemble", brief={}, draft={})
    assert out["status"] == "refused" and out["report"]["failures"] and out["report"]["stage"] == "brief" and out["speech"] == "silent"
    assert (await world.client.presentation_studio_list())["presentations"] == before
    checked = await world.tools.draft("check", brief={}, draft={})
    assert checked["status"] == "checked" and checked["report"]["failures"] == out["report"]["failures"]
    (args, _), = world.spy.named("presentation_studio_authoring_assemble")
    assert args[0]["actor"] == "brain"


async def test_a_template_plan_lists_the_choices_and_nothing_is_published(world):
    out = await world.tools.template("plan", plan={"kind": "presentation", "title": "Modele", "slug": "modele"})
    scenes = out["plan"]["scenes"]["items"]
    assert out["status"] == "planned" and scenes and all(c["control_id"] for c in scenes[0]["controls"]["items"])
    assert out["plan"]["selection_required"] is True
    listing = await world.tools.inspect("templates")
    assert listing["templates"]["total"] == 0, "a plan publishes nothing"
    refusal = await refused(world.tools.template("promote", plan={"kind": "presentation", "title": "Modele", "slug": "modele"}))
    assert refusal.code.startswith("presentation_studio_")
    assert (await refused(world.tools.template("instantiate", template_id="ptp_nope"))).code == "invalid_id"


async def test_the_brain_can_neither_acknowledge_a_licence_nor_keep_assets_nor_promote_without_a_user_turn(world):
    """QA B1: `licence_ack`, `keep_assets` and `promote` are the user's. The plan stays permitted; no value of the plan reaches Core."""

    base = {"kind": "presentation", "title": "Modele", "slug": "modele"}
    for extra in ({"licence_ack": ["GPL-3.0"]}, {"keep_assets": True}):
        for op in ("plan", "promote"):
            world.cc.answers[ATTESTED] = (200, {"ok": True, "addressed_user_turn": True})   # even in a user turn: these two are never the brain's
            refusal = await refused(world.tools.template(op, plan={**base, **extra}))
            assert refusal.code == "presentation_studio_template_user_only", (op, extra)
    assert world.spy.named("presentation_studio_template_plan") == [] and world.spy.named("presentation_studio_template_promote") == []
    world.cc.answers[ATTESTED] = (200, {"ok": True, "addressed_user_turn": False})
    refusal = await refused(world.tools.template("promote", plan={**base, "scenes": []}))
    assert refusal.code == "presentation_studio_template_user_only" and world.spy.named("presentation_studio_template_promote") == []
    planned = await world.tools.template("plan", plan=base)      # the plan needs no attestation: it writes nothing
    assert planned["status"] == "planned"
    world.cc.answers[ATTESTED] = (200, {"ok": True, "addressed_user_turn": True})
    scenes = [{"scene_id": s["scene_id"], "dimensions": [], "parameters": []} for s in planned["plan"]["scenes"]["items"]]
    reached = await refused(world.tools.template("promote", plan={**base, "scenes": scenes}))
    assert reached.code == "presentation_studio_template_leak", "in an attested user turn the call REACHES Core (which then judges the content)"
    (args, _), = world.spy.named("presentation_studio_template_promote")[-1:]
    assert args[2]["actor"] == "brain" and "licence_ack" not in args[2] and "keep_assets" not in args[2]


async def test_a_licence_string_in_a_plan_is_clipped_and_marked_untrusted_for_the_brain(world):
    plan = world.tools._template_plan_view({"ok": False, "licences": {"L" * 300: ["scene:s1"] * 20, "MIT": ["scene:s2"]}, "scenes": [], "findings": []})
    assert all(len(name) <= 64 for name in plan["licences"]) and "licences" in plan["untrusted"]
    assert all(len(rows["items"] if isinstance(rows, dict) else rows) <= 8 for rows in plan["licences"].values())

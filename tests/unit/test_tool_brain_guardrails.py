"""Garde-fous mécaniques des actions irréversibles (handoff jarvis-tool-brain-ui-orchestrator, S8).

Contrat : `docs/tool-brain-contracts.md` §16.3. Scène, file, exécuteur et `read_ui_state` réels (comme les adaptateurs S7) ;
seule la source de preuve (registre d'intentions, tours utilisateur) est scénarisée. Ce qui doit tenir :

- `scene_archive` n'est exécutable que par la garde : sans preuve, sans tour utilisateur, sans garde, rien ne s'écrit ;
- avec la preuve (intention `dismiss` visant chaque objet, ce tour, tour utilisateur récent) elle s'exécute et rend un reçu ;
- jamais sur un objet épinglé par l'utilisateur ni du runtime ; ids explicites ; bornes ; débit par tour et par fenêtre ;
- le masquage en masse confirmé est gardé comme l'archive ; les actions réversibles restent libres ;
- un refus de garde est final : typé, tracé, et il ne réveille pas le décideur (pas de martèlement).
"""

from __future__ import annotations

import pytest

from jarvis.domain.scene import SceneActor, SceneCommand, SceneOp, Visibility
from jarvis.domain.scene_selection import SceneSelection
from jarvis.runtime.tool_brain_choices import read_ui_state
from jarvis.runtime.tool_brain_guardrails import (
    BULK_HIDE, GUARD_CODES, GUARD_UNCONFIGURED, IRREVERSIBLE, DestructiveGuard, GuardrailConfig, UserTurnLedger,
    guard_class, is_guarded,
)
from jarvis.runtime.tool_brain_queue import DONE, INVALIDATED, ActionRecord, Trigger, preconditions_from
from tests.unit.test_tool_brain_adapters import A, B, C, DISPLAY, get, run, stack  # noqa: F401 - `stack` is a fixture

CONV, CORR = "conv-1", "corr-1"


class Evidence:
    """Le registre d'intentions de Core, scénarisé."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], list[dict]] = {}
        self.broken = False

    def dismiss(self, ids, *, conv=CONV, corr=CORR, kind="dismiss", ref_kind="object") -> None:
        self.rows.setdefault((conv, corr), []).append({
            "intent_id": f"ui-{len(self.rows)}", "conversation_id": conv, "correlation_id": corr, "kind": kind,
            "refs": [{"kind": ref_kind, "id": item} for item in ids], "subject": "", "timing": "now"})

    def __call__(self, conv, corr):
        if self.broken:
            raise OSError("registry unreadable")
        return self.rows.get((conv, corr), [])


@pytest.fixture
def armed(stack):  # noqa: F811
    """Une garde réelle câblée à l'exécuteur, un tour utilisateur récent et une preuve vide."""

    evidence, turns = Evidence(), UserTurnLedger(clock=stack.clock)
    turns.note(CONV, CORR)
    stack.executor._guard = DestructiveGuard(intents=evidence, user_turns=turns, clock=stack.clock)
    stack.evidence, stack.turns = evidence, turns
    return stack


async def archive(rig, action_id, ids, **kw):
    return await run(rig, action_id, DISPLAY, "scene_archive", {"object_ids": list(ids)},
                     conversation_id=kw.pop("conv", CONV), correlation_id=kw.pop("corr", CORR), **kw)


def codes(result):
    return [item["code"] for item in result.detail.get("refusals", ())]


async def archived(rig, object_id) -> bool:
    return (await rig.scene.snapshot()).is_archived(object_id)


# ------------------------------------------------------------------ classification (ToolMeta, jamais une liste recopiée)


def test_the_guarded_set_is_read_from_toolmeta_and_the_bulk_hide_confirmation():
    assert guard_class(DISPLAY, "scene_archive", {"object_ids": ["a"]}) == IRREVERSIBLE and is_guarded(DISPLAY, "scene_archive")
    assert guard_class(DISPLAY, "scene_update_many", {"visibility": "hidden", "confirm": True}) == BULK_HIDE
    for tool, arguments in (("scene_update_many", {"visibility": "hidden"}), ("scene_update_many", {"visibility": "visible", "confirm": True}),
                            ("scene_move", {"dx": 1, "dy": 1}), ("scene_pin", {"pinned": True}), ("scene_update_object", {}),
                            ("scene_inspect", {}), ("unknown_tool", {})):
        assert guard_class(DISPLAY, tool, arguments) is None, tool
    assert guard_class("no-such-server", "scene_archive", {}) is None


# ------------------------------------------------------------------ fermé par défaut, preuve, tour utilisateur


async def test_without_a_configured_guard_the_archive_is_closed_and_nothing_is_written(stack):  # noqa: F811
    writes = stack.scene.writes
    result = await archive(stack, "a1", [A])
    assert (result.status, result.code) == (INVALIDATED, GUARD_UNCONFIGURED) and result.detail["guard"] is True
    assert stack.scene.writes == writes and not await archived(stack, A)


async def test_archive_without_a_dismiss_intent_is_refused_and_with_it_the_object_is_archived_with_a_receipt(armed):
    refused = await archive(armed, "a1", [A])
    assert (refused.status, refused.code) == (INVALIDATED, "no_user_intent_evidence") and not await archived(armed, A)
    armed.evidence.dismiss([A])
    armed.clock.now += 6  # the queue's own thrash guard refuses the identical action for 5 s after an invalidation
    done = await archive(armed, "a2", [A])
    assert (done.status, done.code) == (DONE, "applied") and await archived(armed, A)
    assert done.detail["archived"] == [{"id": A, "kind": "artifact", "title": A}]  # the receipt: what was removed


async def test_the_evidence_must_cover_every_target_be_a_dismiss_on_an_object_of_this_turn(armed):
    armed.evidence.dismiss([A], kind="reveal")  # wrong intent kind
    armed.evidence.dismiss([A], ref_kind="board")  # wrong ref kind
    armed.evidence.dismiss([A], corr="corr-other")  # another turn
    armed.evidence.dismiss([A], conv="conv-other")  # another conversation
    assert codes(await archive(armed, "a1", [A])) == ["no_user_intent_evidence"]
    armed.evidence.dismiss([A])
    result = await archive(armed, "a2", [A, B])  # B is not covered
    assert codes(result) == ["no_user_intent_evidence"] and result.detail["refusals"][0]["ids"] == [B]
    assert not await archived(armed, A) and not await archived(armed, B)


async def test_a_turn_that_is_not_a_user_turn_or_has_no_context_never_authorizes_an_archive(armed):
    armed.evidence.dismiss([A], corr="corr-system")
    armed.evidence.dismiss([A], corr="")
    system = await archive(armed, "a1", [A], corr="corr-system")  # evidence exists but nobody spoke in that turn
    assert (system.status, system.code) == (INVALIDATED, "not_user_turn")
    armed.clock.now += 6
    blank = await run(armed, "a2", DISPLAY, "scene_archive", {"object_ids": [A]})  # safety tick: no conversation turn
    assert (blank.status, blank.code) == (INVALIDATED, "no_turn_context")
    assert not await archived(armed, A)


async def test_an_old_user_turn_is_no_longer_evidence(armed):
    armed.evidence.dismiss([A])
    armed.clock.now += 121
    result = await archive(armed, "a1", [A])
    assert (result.status, result.code) == (INVALIDATED, "turn_too_old") and not await archived(armed, A)


async def test_an_unreadable_intent_registry_fails_closed_and_says_so(armed):
    armed.evidence.broken = True
    result = await archive(armed, "a1", [A])
    assert (result.status, result.code) == (INVALIDATED, "evidence_unreadable") and not await archived(armed, A)
    assert "registry unreadable" in result.detail["refusals"][0]["detail"]


# ------------------------------------------------------------------ cibles : explicites, bornées, protégées


async def test_never_a_filter_never_too_many_and_never_pinned_or_runtime_owned_objects(armed):
    armed.evidence.dismiss([A, B, C, "claude:task-1"])
    await armed.scene.service.apply(SceneCommand(op=SceneOp.PIN_SELECTION, actor=SceneActor.USER,
                                                 selection=SceneSelection(ids=(B,))))
    by_filter = await run(armed, "f", DISPLAY, "scene_archive", {"select": {"kind": "artifact"}},
                          conversation_id=CONV, correlation_id=CORR)
    assert (by_filter.status, by_filter.code) == (INVALIDATED, "targets_not_explicit")
    pinned = await archive(armed, "p", [B])
    assert (pinned.status, pinned.code) == (INVALIDATED, "protected_pinned") and pinned.detail["refusals"][0]["ids"] == [B]
    owned = await archive(armed, "r", ["claude:task-1"])
    assert (owned.status, owned.code) == (INVALIDATED, "protected_runtime_owned")
    mixed = await archive(armed, "m", [A, B])  # one protected object refuses the whole action: all or nothing
    assert codes(mixed) == ["protected_pinned"] and not await archived(armed, A)
    too_many = DestructiveGuard(intents=armed.evidence, user_turns=armed.turns, clock=armed.clock,
                                config=GuardrailConfig(max_targets=1))
    armed.executor._guard = too_many
    broad = await archive(armed, "t", [A, C])
    assert (broad.status, broad.code) == (INVALIDATED, "too_many_targets")


async def test_the_adapter_itself_refuses_a_filter_even_if_the_guard_were_bypassed(armed):
    from jarvis.runtime.tool_brain_adapters import SceneArchiveAdapter
    from jarvis.runtime.tool_brain_executor import ExecContext

    outcome = await SceneArchiveAdapter(armed.scene).execute({"select": {"kind": "artifact"}}, ExecContext(None))
    assert (outcome.status, outcome.code) == ("refused", "unsupported_argument") and not await archived(armed, A)


# ------------------------------------------------------------------ débit


async def test_one_guarded_action_per_turn_and_a_bounded_budget_per_window(armed):
    for object_id in (A, B, C):
        armed.evidence.dismiss([object_id])
    first = await archive(armed, "a1", [A])
    assert first.status == DONE
    same_turn = await archive(armed, "a2", [B])
    assert (same_turn.status, same_turn.code) == (INVALIDATED, "rate_limited_turn") and not await archived(armed, B)
    # a new user turn resets the per-turn budget, the window budget (5 objects / 10 min) keeps counting
    armed.turns.note(CONV, "corr-2")
    armed.evidence.dismiss([B, C], corr="corr-2")
    armed.executor._guard._config = GuardrailConfig(max_targets_per_window=2)
    over = await archive(armed, "a3", [B, C], corr="corr-2")
    assert (over.status, over.code) == (INVALIDATED, "rate_limited_window")
    armed.clock.now += 601  # the window slides
    armed.turns.note(CONV, "corr-3")  # a re-noted corr-2 would keep its first-seen age (120 s window): a new turn it is
    armed.evidence.dismiss([B, C], corr="corr-3")
    assert (await archive(armed, "a4", [B, C], corr="corr-3")).status == DONE


# ------------------------------------------------------------------ masquage en masse confirmé


async def test_a_confirmed_bulk_hide_needs_the_same_evidence_but_a_reversible_hide_stays_free(armed):
    free = await run(armed, "h1", DISPLAY, "scene_update_object", {"object_id": A, "visibility": "hidden"})
    assert free.status == DONE  # reversible: autonomous, no evidence asked
    await run(armed, "h2", DISPLAY, "scene_update_object", {"object_id": A, "visibility": "visible"})
    args = {"object_ids": [A, B, C], "visibility": "hidden", "confirm": True}
    refused = await run(armed, "b1", DISPLAY, "scene_update_many", args, conversation_id=CONV, correlation_id=CORR)
    assert (refused.status, refused.code) == (INVALIDATED, "no_user_intent_evidence")
    assert (await get(armed, C)).visibility is Visibility.VISIBLE
    armed.evidence.dismiss([A, B, C])
    armed.clock.now += 6
    allowed = await run(armed, "b2", DISPLAY, "scene_update_many", args, conversation_id=CONV, correlation_id=CORR)
    assert allowed.status == DONE and (await get(armed, C)).visibility is Visibility.HIDDEN


async def test_the_unconfirmed_broad_hide_keeps_its_own_refusal_and_is_not_a_guard_case(armed):
    result = await run(armed, "b0", DISPLAY, "scene_update_many", {"object_ids": [A, B, C], "visibility": "hidden"})
    assert (result.status, result.code) == (INVALIDATED, "selection_too_broad") and "guard" not in result.detail


# ------------------------------------------------------------------ refus final, tracé, sans martèlement


async def test_a_guard_refusal_is_final_typed_traced_and_never_a_reason_to_replan(armed):
    from jarvis.runtime.tool_brain_runtime import ToolBrainConfig, ToolBrainMode, ToolBrainRuntime

    result = await archive(armed, "a1", [A])
    assert result.detail["guard"] is True and result.code in GUARD_CODES
    trace = next(data for kind, level, data in armed.traces if kind == "tool_brain.action.invalidated")
    assert trace["code"] == "no_user_intent_evidence"

    woken = []
    runtime = ToolBrainRuntime(object(), object(), lambda: None, config=ToolBrainConfig(mode=ToolBrainMode.SHADOW))
    runtime.wake = lambda *a, **k: woken.append((a, k))
    _, record = armed.results[-1]
    runtime._on_action_result(result, record)
    assert woken == [] and runtime.status()["counters"]["guard_refused"] == 1  # a replan would re-propose the same removal
    plain = type(result)("a9", INVALIDATED, "unknown_object", {"refusals": []})
    runtime._on_action_result(plain, record)
    assert len(woken) == 1  # ordinary invalidations still replan


def test_the_user_turn_ledger_only_knows_turns_it_was_told_about_and_is_bounded():
    clock = [10.0]
    ledger = UserTurnLedger(clock=lambda: clock[0], capacity=2)
    ledger.note("c", "k1"); ledger.note("c", "k2"); ledger.note(None, "k3"); ledger.note("c", "")
    clock[0] = 15.0
    assert ledger.age_s("c", "k1") == 5.0 and ledger.age_s("c", "k2") == 5.0
    assert ledger.age_s("c", "k3") is None and ledger.age_s(None, None) is None
    ledger.note("c", "k4")  # k1 is forgotten: capacity is a bound, not a cache
    assert ledger.age_s("c", "k1") is None and ledger.age_s("c", "k4") == 0.0


def test_a_guard_codes_table_is_the_documented_one():
    assert GUARD_CODES == {
        "guard_unconfigured", "no_turn_context", "not_user_turn", "turn_too_old", "targets_not_explicit",
        "too_many_targets", "protected_pinned", "protected_runtime_owned", "no_user_intent_evidence",
        "evidence_unreadable", "rate_limited_turn", "rate_limited_window", "scene_unavailable"}


# ------------------------------------------------------------------ S8 rework (independent QA F5, F8a)


def test_a_repeated_user_transcript_event_does_not_refresh_the_turn_age():
    clock = [10.0]
    ledger = UserTurnLedger(clock=lambda: clock[0])
    ledger.note("c", "k1")
    clock[0] = 100.0
    ledger.note("c", "k1")  # same correlation id again: first-seen time governs the 120 s window
    clock[0] = 130.0
    assert ledger.age_s("c", "k1") == 120.0


async def test_a_guarded_action_without_a_scene_snapshot_is_refused_not_unchecked(armed):
    import dataclasses

    armed.evidence.dismiss([A])
    state = await read_ui_state(armed.scene, armed.boards)
    record = ActionRecord("g1", DISPLAY, "scene_archive", {"object_ids": [A]}, trigger=Trigger.from_payload(None),
                          planned_from=state.ref(), preconditions=preconditions_from(state.ref()),
                          conversation_id=CONV, correlation_id=CORR)
    refusals = armed.executor._guard.check(record, dataclasses.replace(state, scene=None))
    assert [item.code for item in refusals] == ["scene_unavailable"]
    bulk = dataclasses.replace(record, tool="scene_update_many",
                               arguments={"select": {"category": "note"}, "visibility": "hidden", "confirm": True})
    assert [item.code for item in armed.executor._guard.check(bulk, dataclasses.replace(state, scene=None))] == ["scene_unavailable"]


async def test_a_bulk_hide_by_filter_acts_on_exactly_the_set_the_evidence_covered(armed):
    seen = []
    inner = armed.executor._adapters[(DISPLAY, "scene_update_many")]

    class Spy:
        async def execute(self, arguments, context):
            seen.append(dict(arguments))
            return await inner.execute(arguments, context)

    armed.executor._adapters[(DISPLAY, "scene_update_many")] = Spy()
    armed.evidence.dismiss([A, B, C])
    result = await run(armed, "b1", DISPLAY, "scene_update_many",
                       {"select": {"category": "note"}, "visibility": "hidden", "confirm": True},
                       conversation_id=CONV, correlation_id=CORR)
    assert result.status == DONE
    assert "select" not in seen[0] and sorted(seen[0]["object_ids"]) == sorted([A, B, C])

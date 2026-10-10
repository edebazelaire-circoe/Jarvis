"""Silence under PRESENTATION, voice and interface parity, correlation with the canonical events (jarvis-interactive-presentation-studio, Slice 21).

Real Core, real playback and edit services, the real PRESENTATION policy matrix (`presentation_policy`, `presentation_response`), the real
conversation-event emitter. Contract: `docs/presentation-studio.md` > *Agent and voice operations (Slice 21)*.
"""

from __future__ import annotations

import json

import pytest

from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.presentation_policy import PRESENTATION_POLICY, PresentationSituation, may_speak
from jarvis.domain.presentation_response import admit_presentation_speech, classify_addressed_situation
from jarvis.domain.presentation_studio_edit import ALLOWED_EDIT_OPS, OpName, StudioActor
from jarvis.domain.v2 import SpeechKind
from jarvis.runtime.presentation_studio_mcp_tools import EDIT_FIELDS, EDIT_OPS, OPERATION_EVENTS
from tests.unit.presentation_studio_mcp_world import S1, S2, S3, World, open_world

ATTESTED = ("GET", "/api/presentation-studio/agent/turn")


@pytest.fixture
async def world(tmp_path):
    core, built = await open_world(tmp_path)
    try:
        yield built
    finally:
        await core.__aexit__(None, None, None)


# ------------------------------------------------------------------ PRESENTATION : silence par défaut

def test_the_utterances_of_the_brief_are_visual_commands_the_policy_keeps_silent():
    for sentence in ("montre toutes les variantes", "ouvre la 37", "compare ces quatre", "mélange la structure de A avec le ton de B",
                     "affiche la variante deux", "ferme l'explorateur", "archive la branche trois"):
        situation, mark = classify_addressed_situation(sentence)
        assert situation is PresentationSituation.VISUAL_COMMAND, (sentence, mark)
        assert admit_presentation_speech(situation=situation, kind=SpeechKind.RESULT).admitted is False, sentence
    # a real request to speak keeps its voice, and a question keeps its answer
    assert classify_addressed_situation("dis-moi quelles variantes existent")[0] is PresentationSituation.EXPLICIT_SPEAK_REQUEST
    assert classify_addressed_situation("pourquoi la variante deux est plus courte")[0] is PresentationSituation.KNOWLEDGE_QUESTION


def test_a_tool_result_marked_silent_is_the_confirmation_row_and_only_safety_speech_passes():
    row = PRESENTATION_POLICY[PresentationSituation.COMMAND_CONFIRMATION]
    assert row.voice_allowed is False and not row.speech_kinds
    assert not any(may_speak(PresentationSituation.COMMAND_CONFIRMATION, kind) for kind in (SpeechKind.RESULT, SpeechKind.ACK, SpeechKind.PROGRESS))
    # what the tools mark `say` is exactly what the matrix lets through: a refusal (ERROR) and a confirmation question (QUESTION)
    assert may_speak(PresentationSituation.COMMAND_ERROR, SpeechKind.ERROR)
    assert may_speak(PresentationSituation.VISUAL_COMMAND, SpeechKind.QUESTION)
    assert not may_speak(PresentationSituation.VISUAL_COMMAND, SpeechKind.RESULT)


async def test_every_successful_visual_gesture_is_silent_and_carries_no_sentence(world):
    world.cc.answers[ATTESTED] = (200, {"ok": True, "addressed_user_turn": True})
    world.cc.answers[("POST", "/api/presentation-studio/explorer/commands")] = (200, {"state": "opened", "mode": "windowed"})
    await world.tools.variant("create", title="B")
    await world.tools.variant("create", title="C")
    graph = await world.tools.inspect("presentation")
    ids = [v["variant_id"] for v in graph["variants"]["items"]]
    results = [
        await world.tools.view("explorer_open"),
        await world.tools.view("explorer_close"),
        await world.tools.compare("open", variant_ids=ids[:2]),
        await world.tools.compare("mode", mode="independent"),
        await world.tools.compare("close"),
        await world.tools.edit([{"op": "control.set", "scene_id": S1, "control_id": "body", "value": "Silence"}]),
        await world.tools.inspect("scene", scene_id=S1),
        await world.tools.play("start", role="rehearsal"),
        await world.tools.play("next"),
        await world.tools.play("goto", scene_id=S1),
        await world.tools.play("pause"),
        await world.tools.play("resume"),
        await world.tools.play("stop"),
        await world.tools.variant("activate", variant_id=ids[1]),
        await world.tools.variant("rename", variant_id=ids[1], title="Renommée"),
        await world.tools.undo(variant_id=world.vid),
    ]
    for result in results:
        assert result["speech"] == "silent" and "say" not in result, result


async def test_what_is_said_is_a_new_fact_a_question_a_click_or_a_refusal(world):
    created = await world.tools.variant("create", title="Fait nouveau")
    assert created["speech"] == "say" and created["say"]
    world.cc.answers[("POST", "/api/presentation-studio/explorer/commands")] = (200, {"state": "opened", "mode": "fullscreen_armed"})
    click = await world.tools.view("explorer_open")
    ask = await world.tools.edit([{"op": "scene.remove", "scene_id": S3}])
    plan = await world.tools.variant("archive_plan", variant_id=created["variant_id"])
    for result in (click, ask, plan):
        assert result["speech"] == "say" and result["say"] and len(result["say"]) < 140, result


# ------------------------------------------------------------------ parité voix / interface

def test_the_tool_vocabulary_is_a_subset_of_the_one_vocabulary_both_actors_share():
    core_ops = {op.value for op in OpName}
    assert set(EDIT_OPS) <= core_ops and set(EDIT_FIELDS) == set(EDIT_OPS)
    # Slice 05: the actor is a label, not a second vocabulary; the tools offer neither the undo forms nor a whole-scene body
    for op in EDIT_OPS:
        assert OpName(op) in ALLOWED_EDIT_OPS[StudioActor.BRAIN] and OpName(op) in ALLOWED_EDIT_OPS[StudioActor.USER], op
    assert not {"scene.restore_values", "scene_variant.restore_set", "scene.add", "scene.set_controls"} & set(EDIT_OPS)


async def test_the_same_semantic_operations_by_voice_and_by_the_interface_reach_the_same_state(world):
    other = await world.client.presentation_studio_create_branch(world.pid, {"title": "Jumeau", "actor": "user"})
    twin = other["variant"]["variant_id"]
    _, a = await world.core.call("GET", f"/{world.pid}/variants/{world.vid}")
    _, b = await world.core.call("GET", f"/{world.pid}/variants/{twin}")
    ops = [{"op": "control.set", "scene_id": S1, "control_id": "body", "value": "Meme resultat"},
           {"op": "scene.rename", "scene_id": S2, "title": "Renommee"},
           {"op": "scene.reorder", "scene_id": S2, "to_index": 0}]
    voice = await world.tools.edit(ops, variant_id=world.vid, revision=a["revision"])
    gui = await world.client.presentation_studio_edit(world.pid, twin, {
        "actor": "user", "mode": "commit", "basis": {"variant_revision": b["revision"]}, "ops": ops})
    assert voice["status"] == gui["status"] == "applied" and voice["tier"] == gui["tier"]
    _, a2 = await world.core.call("GET", f"/{world.pid}/variants/{world.vid}")
    _, b2 = await world.core.call("GET", f"/{world.pid}/variants/{twin}")
    assert json.dumps(a2["scenes"], sort_keys=True) == json.dumps(b2["scenes"], sort_keys=True)
    # and the undo of each is the same inverse
    voice_undo = await world.tools.undo(variant_id=world.vid)
    gui_undo = await world.client.presentation_studio_undo(world.pid, twin, {"actor": "user"})
    assert voice_undo["status"] == gui_undo["status"] == "applied"
    _, a3 = await world.core.call("GET", f"/{world.pid}/variants/{world.vid}")
    _, b3 = await world.core.call("GET", f"/{world.pid}/variants/{twin}")
    assert json.dumps(a3["scenes"], sort_keys=True) == json.dumps(b3["scenes"], sort_keys=True)


async def test_the_archive_door_is_the_same_for_both_and_the_gui_token_does_not_open_the_voice_door(world):
    made = await world.client.presentation_studio_create_branch(world.pid, {"title": "Cible", "actor": "user"})
    target = made["variant"]["variant_id"]
    gui_plan = await world.client.presentation_studio_archive_plan(world.pid, target, {"actor": "user"})
    # a token the user's page obtained is not a plan this process made: the voice cannot reuse it
    from jarvis.runtime.presentation_studio_mcp_support import PresentationToolError

    with pytest.raises(PresentationToolError) as caught:
        await world.tools.variant("archive", variant_id=target, confirmation=gui_plan["confirmation"], confirmed=True)
    assert caught.value.code == "presentation_studio_confirmation_required"
    voice_plan = await world.tools.variant("archive_plan", variant_id=target)
    assert voice_plan["confirmation"].startswith("psk_")


# ------------------------------------------------------------------ corrélation avec les événements canoniques

def test_every_correlated_operation_names_an_event_the_conversation_registry_knows():
    registered = {t.value for t in T}
    assert OPERATION_EVENTS and {e for e in OPERATION_EVENTS.values() if e} <= registered


async def test_a_tool_call_leaves_one_journal_line_that_points_at_the_canonical_event(world):
    seen: list = []
    world.core.stack.core.conversation_event_emitter.add_listener(seen.append)
    world.cc.answers[ATTESTED] = (200, {"ok": True, "addressed_user_turn": True})
    edit = await world.tools.edit([{"op": "control.set", "scene_id": S1, "control_id": "body", "value": "Trace"}])
    made = await world.tools.variant("create", title="Corrélée")
    await world.tools.play("start", role="rehearsal")
    await world.tools.play("stop")
    await world.core.stack.core.conversation_event_emitter.stop()
    rows = [row for row in world.journal_rows() if row.get("kind") == "presentation_studio.tool"]
    by_tool = {(r["data"]["tool"], r["data"]["op"]): r["data"] for r in rows}
    edit_row = by_tool[("presentation_edit", "commit")]
    assert edit_row["event"] == T.SYSTEM_PRESENTATION_STUDIO_EDIT_COMMITTED.value and edit_row["revision"] == edit["revision"]
    assert by_tool[("presentation_variant", "create")]["event"] == T.SYSTEM_PRESENTATION_STUDIO_VARIANT_CHANGED.value
    assert by_tool[("presentation_play", "start")]["event"] == T.SYSTEM_PRESENTATION_STUDIO_PLAYBACK_CHANGED.value
    assert len({r["correlation_id"] for r in by_tool.values()}) == len(by_tool), "one correlation id per call"
    # the event Core posted for that very edit carries the same ids and revision, and the actor label `brain`
    committed = [e for e in seen if e.event_type is T.SYSTEM_PRESENTATION_STUDIO_EDIT_COMMITTED]
    assert [dict(e.attributes)["revision"] for e in committed] == [edit["revision"]] and dict(committed[0].attributes)["source"] == "brain"
    assert [dict(e.attributes)["variant_id"] for e in committed] == [edit_row["variant_id"]]
    assert any(e.event_type is T.SYSTEM_PRESENTATION_STUDIO_VARIANT_CHANGED for e in seen) and made["variant_number"] == 2
    assert any(e.event_type is T.SYSTEM_PRESENTATION_STUDIO_PLAYBACK_CHANGED for e in seen)


async def test_the_journal_never_carries_a_title_a_value_or_a_spoken_line(world):
    await world.tools.edit([{"op": "control.set", "scene_id": S1, "control_id": "body", "value": "SECRET-VALEUR"}])
    await world.tools.variant("create", title="SECRET-TITRE", rationale="SECRET-RAISON")
    await world.tools.draft("check", brief={"title": "SECRET-BRIEF"}, draft={})
    text = json.dumps(world.journal_rows(), ensure_ascii=False)
    assert "SECRET" not in text and "presentation_studio.tool" in text


async def test_a_refusal_is_journalled_with_its_code_and_no_content(world):
    from jarvis.runtime.presentation_studio_mcp_support import PresentationToolError

    with pytest.raises(PresentationToolError):
        await world.tools.edit([{"op": "control.set", "scene_id": S1, "control_id": "ghost", "value": "SECRET-X"}])
    failed = [r for r in world.journal_rows() if r.get("kind") == "presentation_studio.tool_failed"]
    assert failed and failed[-1]["data"]["code"].startswith("presentation_studio_") and "SECRET" not in json.dumps(failed)

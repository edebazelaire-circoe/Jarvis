"""Propriété des gestes de source (Remotion Slice 21) : petit changement = props, structurel = demande de source, et rien ne part d'un tour ambiant.

Vrai Core derrière le vrai protocole (le monde de `jarvis-presentation`). `presentation_edit` garde son partage : un contrôle (`control.set`)
est un changement de props, sans tour attesté exigé (comportement de la Slice 21 d'origine) ; `scene.source_request` démarre l'édition de la
source par un sous-agent et n'est permise que dans un tour adressé de l'utilisateur.
"""

from __future__ import annotations

import pytest

from jarvis.runtime.presentation_studio_mcp_support import PresentationToolError
from tests.unit.presentation_studio_mcp_world import S1, World, open_world

ATTESTED = ("GET", "/api/presentation-studio/agent/turn")
SOURCE = {"op": "scene.source_request", "scene_id": S1, "intent": "refais la scène avec un autre style"}


@pytest.fixture
async def world(tmp_path):
    core, built = await open_world(tmp_path)
    try:
        yield built
    finally:
        await core.__aexit__(None, None, None)


async def test_a_source_request_in_a_turn_that_is_not_the_users_is_refused_and_nothing_reaches_core(world: World):
    for answer in (None, (200, {"ok": True, "addressed_user_turn": False}), (503, None), (200, {"addressed_user_turn": "yes"})):
        if answer is not None:
            world.cc.answers[ATTESTED] = answer
        with pytest.raises(PresentationToolError) as caught:
            await world.tools.edit([SOURCE])
        assert caught.value.code == "presentation_studio_source_request_user_only", answer
    assert world.spy.named("presentation_studio_edit") == []


async def test_a_source_request_in_an_addressed_user_turn_reaches_core_as_the_brain(world: World):
    world.cc.answers[ATTESTED] = (200, {"ok": True, "addressed_user_turn": True})
    result = await world.tools.edit([SOURCE])
    (args, _), = world.spy.named("presentation_studio_edit")
    sent = args[2]
    assert sent["actor"] == "brain" and [o["op"] for o in sent["ops"]] == ["scene.source_request"]
    assert result["committed"] is True and result["source_requests"], "la demande est enregistrée pour l'édition de la source"
    assert "n'appelle pas scene.source_request" in result["next_step"], "le résultat dit qui fait la suite (QA trace réelle : le cerveau déléguait avant d'enregistrer)"


async def test_a_preview_of_a_source_request_writes_nothing_and_needs_no_turn(world: World):
    result = await world.tools.edit([SOURCE], mode="preview")
    assert result.get("committed") in (False, None)
    assert "next_step" not in result


async def test_a_small_change_is_a_props_edit_that_needs_no_source_gesture(world: World):
    """« change la couleur du titre » : un contrôle, jamais une demande de source."""

    result = await world.tools.edit([{"op": "control.set", "scene_id": S1, "control_id": "body", "value": "Neuf"}])
    assert result["committed"] is True
    ops = [o["op"] for a, k in world.spy.named("presentation_studio_edit") for o in a[2]["ops"]]
    assert ops == ["control.set"]


# ---- Remotion Slice 21 rework (QA B1): Core is the authority, the tool layer only carries the attestation to it.

async def _brain_source_edit(world: World, **extra):
    variant = await world.client.presentation_studio_variant(world.pid, world.vid)
    return await world.client.presentation_studio_source_edit(world.pid, world.vid, {
        "actor": "brain", "basis": {"variant_revision": variant["revision"]}, "scene_id": S1, "files": {"style": "p{color:#102030}"}, **extra})


async def test_the_tool_carries_the_attested_origin_and_core_ties_the_later_source_edit_to_that_record(world: World):
    from jarvis.protocol.client import CoreProtocolError

    world.cc.answers[ATTESTED] = (200, {"ok": True, "addressed_user_turn": True})
    recorded = await world.tools.edit([SOURCE])
    (args, _), = world.spy.named("presentation_studio_edit")
    assert args[2]["origin"] == "explicit_user_request"
    request_id = recorded["source_requests"][0]["request_id"]
    with pytest.raises(CoreProtocolError) as caught:           # the sub-agent forgot the id: Core refuses, whatever the tool layer did
        await _brain_source_edit(world)
    assert (caught.value.status, caught.value.code) == (403, "presentation_studio_source_request_required")
    done = await _brain_source_edit(world, request_id=request_id)
    assert done["status"] in ("reloaded", "repinned", "reloaded_state_reset") and done["request_id"] == request_id
    with pytest.raises(CoreProtocolError) as caught:           # consumed by the success: a second edit needs a renewed request
        await _brain_source_edit(world, request_id=request_id)
    assert caught.value.code == "presentation_studio_source_request_required"


async def test_core_itself_refuses_to_record_a_brain_source_request_without_the_origin(world: World):
    """A caller that bypasses the tool layer (a sub-agent with the Core token) gets no record, hence no later edit."""

    variant = await world.client.presentation_studio_variant(world.pid, world.vid)
    from jarvis.protocol.client import CoreProtocolError

    with pytest.raises(CoreProtocolError) as caught:
        await world.client.presentation_studio_edit(world.pid, world.vid, {
            "actor": "brain", "mode": "commit", "basis": {"variant_revision": variant["revision"]}, "ops": [SOURCE]})
    assert (caught.value.status, caught.value.code) == (403, "presentation_studio_source_request_required")
    assert world.core.stack.core.presentation_studio_edit.pending_source_requests() == ()

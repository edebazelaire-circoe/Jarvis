"""Intention d'interface de Jarvis (Tool Brain, Slice 4) : typage, canal Core, évènement, péremption.

Réel : domaine, registre, `BrainOrchestrator`, serveur de protocole (aiohttp `TestServer`), client, outil MCP
`ui_intent_publish` (transport relié au vrai client) et store d'évènements ; les tours sont des `SlowBackend`.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from jarvis.core.ui_intents import MAX_INTENTS_PER_TURN, UiIntentRefused, UiIntentRegistry
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.conversation_events import ConversationEventType as T, is_forbidden_key
from jarvis.domain.ui_intent import (
    MAX_REFS, PROVIDER_OF_REF, UiIntentDraft, UiIntentKind, UiIntentRef, UiIntentRefKind, UiIntentTiming,
)
from jarvis.runtime.mcp_tool_meta import CHOICE_PROVIDERS, tool_meta
from jarvis.runtime.tool_brain_intents import (
    DUE, OBSOLETE, PENDING, UNANCHORED, anchor_chunk_id, check_intent_refs, intent_status,
)
from jarvis.runtime.tool_brain_speech import ChunkEvidence, SpeechProgressTracker
from tests.fakes.conversation_events import wait_emitter_settled
from tests.unit.test_conversation_event_producers import of_type, stored
from tests.unit.test_tool_brain_speech import TEXT, snapshot_for
from tests.unit.test_v2_brain_orchestrator import SlowBackend, wait_idle

NOW = datetime(2026, 10, 7, tzinfo=timezone.utc)


def draft(**changes):
    base = {"kind": "reveal", "refs": [{"kind": "object", "id": "agent:abc123"}], "timing": "with_speech", "paragraph": 1}
    return UiIntentDraft.from_payload({**base, **changes})


# --- domaine -------------------------------------------------------------------------------------------


def test_a_valid_intent_round_trips_and_ref_kinds_map_to_s2_choice_providers():
    original = draft(refs=[{"kind": "object", "id": "agent:abc123"}, {"kind": "board", "id": "board_x1"}],
                     subject="le résultat")
    assert UiIntentDraft.from_payload(original.to_payload()) == original
    assert original.kind is UiIntentKind.REVEAL and original.timing is UiIntentTiming.WITH_SPEECH
    # Une seule table de correspondance, et chaque cible existe dans le vocabulaire canonique de S2.
    assert set(PROVIDER_OF_REF) == set(UiIntentRefKind)
    assert set(PROVIDER_OF_REF.values()) <= set(CHOICE_PROVIDERS)


@pytest.mark.parametrize("payload, message", [
    ({"kind": "teleport"}, "kind must be one of"),
    ({"timing": "whenever"}, "timing must be one of"),
    ({"refs": "agent:1"}, "refs must be a list"),
    ({"refs": [{"kind": "window", "id": "x"}]}, "ref kind must be one of"),
    ({"refs": [{"kind": "object", "id": "has space"}]}, "stable id"),
    ({"refs": [{"kind": "object", "id": "x"}] * 2}, "unique"),
    ({"refs": [{"kind": "object", "id": f"o{i}"} for i in range(MAX_REFS + 1)]}, "at most"),
    ({"refs": [], "subject": ""}, "needs refs or a subject"),
    ({"subject": "x" * 81}, "subject must be one line"),
    ({"subject": "a\nb"}, "subject must be one line"),
    ({"paragraph": 16}, "paragraph must be an integer"),
    ({"paragraph": True}, "paragraph must be an integer"),
    ({"timing": "now", "paragraph": 0}, "only applies to timing with_speech"),
    ({"x_geometry": {"x": 1}}, "unknown ui intent fields"),
    ({"layout": "grid"}, "unknown ui intent fields"),
])
def test_invalid_intents_are_refused_with_a_message_naming_the_rule_not_the_value(payload, message):
    with pytest.raises(ValueError, match=message):
        draft(**payload)


def test_an_intent_is_a_declaration_not_a_command_so_no_low_level_field_exists():
    fields = set(draft().to_payload())
    assert fields == {"kind", "refs", "subject", "timing", "paragraph"}
    assert not any(word in field for field in fields for word in ("x", "y", "geometry", "layer", "tool", "command"))
    assert {item.value for item in UiIntentKind} == {"reveal", "attention", "relevance", "dismiss"}


# --- registre ------------------------------------------------------------------------------------------


def test_the_registry_is_bounded_per_turn_and_per_conversation_and_never_grows_without_end():
    ids = iter(f"ui-{n}" for n in range(10_000))
    registry = UiIntentRegistry(clock=lambda: NOW, id_factory=lambda: next(ids))
    for _ in range(MAX_INTENTS_PER_TURN):
        registry.publish("conv", "corr-1", draft())
    with pytest.raises(UiIntentRefused) as refusal:
        registry.publish("conv", "corr-1", draft())
    assert refusal.value.code == "too_many_intents"
    for turn in range(2, 14):
        for _ in range(MAX_INTENTS_PER_TURN):
            registry.publish("conv", f"corr-{turn}", draft())
    assert len(registry.list("conv")) == 64 and registry.forgotten == 8 * 13 - 64
    assert len(registry.list("conv", correlation_id="corr-13")) == MAX_INTENTS_PER_TURN
    assert registry.list("conv", correlation_id="corr-1") == ()  # le plus ancien tour a été oublié
    assert registry.list("other") == ()


# --- Core, protocole, évènement ------------------------------------------------------------------------


async def test_publishing_during_a_turn_attaches_the_intent_and_records_one_contentless_event(tmp_path):
    backend = SlowBackend()
    core = JarvisCoreApplication(data_root=tmp_path / "data")
    await core.start()
    core.brain._backend = backend
    try:
        conversation = await core.conversations.create()
        from jarvis.domain.v2 import BrainTurnInput
        await core.brain.submit(BrainTurnInput(conversation_id=conversation.id, correlation_id="corr-ui", text="Montre-moi"))
        await asyncio.wait_for(backend.started.wait(), 5)
        payload = draft(subject="résultat confidentiel").to_payload()
        result = core.brain.publish_ui_intent(payload, conversation_id=conversation.id)
        assert result["accepted"] and result["correlation_id"] == "corr-ui" and result["ref_count"] == 1
        # Sans conversation donnée : celle qui a la parole (sans Boards : le dernier tour reçu), même tour en vol.
        core.brain._speech_authority = None
        assert core.brain.publish_ui_intent(payload)["correlation_id"] == "corr-ui"
        listed = core.brain.list_ui_intents(conversation.id, correlation_id="corr-ui")
        assert [item["intent_id"] for item in listed][0] == result["intent_id"] and len(listed) == 2
        backend.release.set()
        await wait_idle(core.brain)
        await wait_emitter_settled(core.conversation_event_emitter)
        events = of_type(await stored(core, conversation.id), T.BRAIN_UI_INTENT_PUBLISHED)
        assert len(events) == 2
        event = events[0]
        assert event.correlation_id == "corr-ui" and event.content is None and event.span_id is None
        assert dict(event.attributes) == {"kind": "reveal", "timing": "with_speech", "ref_count": 1, "paragraph": 1}
        # Ni le sujet, ni les ids visés ne quittent le registre : jamais dans l'évènement.
        wire = json.dumps(dict(event.attributes))
        assert "confidentiel" not in wire and "agent:abc123" not in wire
        assert not any(is_forbidden_key(key) for key in event.attributes)
    finally:
        await core.stop()


async def test_without_a_turn_in_flight_the_intent_is_refused_never_retained(tmp_path):
    core = JarvisCoreApplication(data_root=tmp_path / "data")
    await core.start()
    try:
        conversation = await core.conversations.create()
        with pytest.raises(UiIntentRefused) as refusal:
            core.brain.publish_ui_intent(draft().to_payload(), conversation_id=conversation.id)
        assert refusal.value.code == "no_turn_in_flight"
        with pytest.raises(UiIntentRefused):
            core.brain.publish_ui_intent(draft().to_payload(), conversation_id=conversation.id, correlation_id="old")
        with pytest.raises(ValueError, match="kind must be one of"):
            core.brain.publish_ui_intent({"kind": "x"}, conversation_id=conversation.id)
        assert core.brain.list_ui_intents(conversation.id) == []
    finally:
        await core.stop()


async def test_the_whole_channel_tool_to_core_over_the_real_protocol(tmp_path):
    """`ui_intent_publish` (outil MCP) -> transport -> client -> `POST /v1/ui-intents` -> Core -> évènement."""

    from aiohttp.test_utils import TestServer
    from jarvis.domain.v2 import BrainTurnInput
    from jarvis.protocol.client import LocalCoreClient
    from jarvis.protocol.server import LocalProtocolServer
    from jarvis.runtime.display_mcp import DisplayToolError, SceneDisplayTools

    backend = SlowBackend()
    core = JarvisCoreApplication(data_root=tmp_path / "data")
    await core.start()
    core.brain._backend = backend
    token = "t" * 32
    server = TestServer(LocalProtocolServer(core, host="127.0.0.1", port=0, token=token)._app())
    await server.start_server()
    client = LocalCoreClient(host="127.0.0.1", port=server.port, token=token)

    class Transport:
        async def ui_intent_publish(self, intent, *, connect_timeout_s, read_timeout_s):
            return await client.publish_ui_intent(intent, connect_timeout_s=connect_timeout_s, read_timeout_s=read_timeout_s)

        async def close(self):
            await client.close()

    tools = SceneDisplayTools(Transport())
    try:
        core.brain._speech_authority = None  # la conversation qui parle est celle du dernier tour (sans Boards)
        conversation = await client.create_conversation()
        # Avant tout tour : refus attribué, lisible, rien de retenu.
        with pytest.raises(DisplayToolError) as refused:
            await tools.publish_ui_intent(kind="reveal", subject="le résultat")
        assert refused.value.code == "no_turn_in_flight"
        await core.brain.submit(BrainTurnInput(conversation_id=conversation["id"], correlation_id="corr-ch", text="Montre"))
        await asyncio.wait_for(backend.started.wait(), 5)
        answer = await tools.publish_ui_intent(
            kind="attention", refs=[{"kind": "object", "id": "agent:abc123"}], timing="with_speech", paragraph=0)
        assert answer["correlation_id"] == "corr-ch" and answer["kind"] == "attention" and answer["ref_count"] == 1
        # Arguments invalides : refusés avant tout envoi.
        with pytest.raises(DisplayToolError) as invalid:
            await tools.publish_ui_intent(kind="reveal", refs=[{"kind": "object", "id": "x y"}])
        assert invalid.value.code == "invalid_argument"
        for _ in range(MAX_INTENTS_PER_TURN):
            try:
                await tools.publish_ui_intent(kind="relevance", subject="encore")
            except DisplayToolError as exc:
                assert exc.code == "too_many_intents"
                break
        else:
            raise AssertionError("the per-turn bound never refused")
        backend.release.set()
        await wait_idle(core.brain)
    finally:
        await tools.close()
        await server.close()
        await core.stop()


async def test_the_http_route_rejects_unknown_fields_and_a_conversation_less_read(tmp_path):
    from aiohttp import ClientSession
    from aiohttp.test_utils import TestServer
    from jarvis.protocol.server import LocalProtocolServer

    core = JarvisCoreApplication(data_root=tmp_path / "data")
    await core.start()
    token = "t" * 32
    server = TestServer(LocalProtocolServer(core, host="127.0.0.1", port=0, token=token)._app())
    await server.start_server()
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with ClientSession() as http:
            base = f"http://127.0.0.1:{server.port}/v1/ui-intents"
            async with http.post(base, headers=headers, json={"intent": draft().to_payload(), "tool": "scene_move"}) as response:
                assert response.status == 400
            async with http.get(base, headers=headers) as response:
                assert response.status == 400
            async with http.post(base, json={"intent": draft().to_payload()}) as response:
                assert response.status in (401, 403)  # jeton exigé comme toute route de Core
    finally:
        await server.close()
        await core.stop()


# --- outil MCP : métadonnées ---------------------------------------------------------------------------


def test_the_publish_tool_is_a_jarvis_tool_not_a_ui_action_so_the_tool_brain_manifest_excludes_it():
    meta = tool_meta("jarvis-display", "ui_intent_publish")
    assert meta.ui_surface is None and meta.reversibility is None and meta.choice_providers == {}
    assert meta.side_effect == "write"


# --- refs et péremption --------------------------------------------------------------------------------


def test_intent_refs_are_checked_against_the_s2_choice_providers_with_owner_codes():
    from jarvis.runtime.tool_brain_choices import PROVIDERS
    from tests.unit.test_tool_brain_choices import _state  # état de monde de S2

    state = _state()
    objects = [choice.value for choice in PROVIDERS["scene.object"].list_choices(state)]
    good = UiIntentDraft(UiIntentKind.REVEAL, (UiIntentRef(UiIntentRefKind.OBJECT, objects[0]),))
    assert check_intent_refs(good, state) == ()
    bad = UiIntentDraft(UiIntentKind.REVEAL, (UiIntentRef(UiIntentRefKind.OBJECT, "agent:ghost"),
                                              UiIntentRef(UiIntentRefKind.BOARD, "board_ghost")))
    codes = [item.code for item in check_intent_refs(bad, state)]
    assert codes == ["unknown_object", "board_not_found"]


def test_anchor_chunk_id_is_the_canonical_chunk_of_the_paragraph():
    from jarvis.domain.speech_presentation import presentation_chunk_ids, semantic_text_spans

    ids = presentation_chunk_ids("req-1", semantic_text_spans(TEXT))
    assert anchor_chunk_id(draft(paragraph=2), "req-1", TEXT) == ids[2]
    assert anchor_chunk_id(draft(paragraph=7), "req-1", TEXT) is None  # hors réponse : pas d'ancrage
    assert anchor_chunk_id(draft(timing="now", paragraph=None), "req-1", TEXT) is None


def progress_for(statuses, **kwargs):
    snap, ids, _ = snapshot_for(statuses, **kwargs)
    return SpeechProgressTracker().observe(snap, {ids[1]: ChunkEvidence(500, 2000)}).data


@pytest.mark.parametrize("statuses, paragraph, expected", [
    (["started", "deferred", "deferred"], 0, DUE),
    (["started", "deferred", "deferred"], 1, PENDING),
    (["completed", "started", "deferred"], 1, DUE),
    (["completed", "interrupted", "deferred"], 1, DUE),       # coupé en plein paragraphe : le début a été dit
    (["completed", "interrupted", "deferred"], 2, OBSOLETE),  # la suite ne sera jamais dite
    (["completed", "completed", "superseded"], 2, OBSOLETE),
    (["deferred", "deferred", "deferred"], 0, PENDING),
    (["started", "deferred", "deferred"], 9, OBSOLETE),       # paragraphe inexistant
])
def test_with_speech_intents_follow_the_paragraph_and_interruption_makes_the_future_obsolete(statuses, paragraph, expected):
    assert intent_status(draft(paragraph=paragraph), "corr-1", progress_for(statuses)) == expected


def test_timing_variants_and_unanchored_speech():
    started = progress_for(["started", "deferred", "deferred"])
    assert intent_status(draft(timing="now", paragraph=None), "corr-1", started) == DUE
    assert intent_status(draft(timing="now", paragraph=None), "other", {"chains": []}) == DUE
    assert intent_status(draft(timing="after_speech", paragraph=None), "corr-1", started) == PENDING
    assert intent_status(draft(timing="after_speech", paragraph=None), "corr-1",
                         progress_for(["completed", "completed", "completed"])) == DUE
    assert intent_status(draft(timing="after_speech", paragraph=None), "corr-1",
                         progress_for(["completed", "interrupted", "deferred"])) == OBSOLETE
    assert intent_status(draft(paragraph=None), "corr-1", started) == DUE          # début de réponse dit
    assert intent_status(draft(paragraph=None), "corr-1", progress_for(["deferred"] * 3)) == PENDING
    assert intent_status(draft(paragraph=0), "unknown-turn", started) == UNANCHORED

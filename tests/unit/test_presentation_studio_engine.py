"""Presentation engine semantics (handoff jarvis-remotion-presentation-integration, Slice 02).

Contract: `docs/presentation-engine.md`. Policy tests double as mutation guards: each negative test fails if the matching
rule (no agent choice, no fallback, legacy default, undeclared = unsupported) is weakened.
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
import inspect
import itertools
import json
from pathlib import Path

import pytest

from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.core.presentation_studio_service import PresentationStudioService
from jarvis.domain import presentation_studio as ps
from jarvis.domain import presentation_studio_engine as eng
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_engine import (
    CAPABILITIES, DEFAULT_ENGINE, LEGACY_ENGINE, POLICY, Capability, Engine, EngineActor, EngineAvailability, EngineIdentity,
    Support,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "presentation_studio"
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def refused(call, code: C) -> PresentationStudioError:
    with pytest.raises(PresentationStudioError) as caught:
        call()
    assert caught.value.code is code, caught.value
    return caught.value


# ------------------------------------------------------------------ identity and defaults

def test_the_forced_default_is_remotion_and_the_legacy_engine_is_slidecar_spelled_canonically():
    assert DEFAULT_ENGINE is Engine.REMOTION and LEGACY_ENGINE is Engine.SLIDECAR
    assert {e.value for e in Engine} == {"slidecar", "remotion"}  # never "sidecar"


def test_a_new_presentation_is_remotion_unless_a_person_chose_otherwise():
    assert ps.new_presentation("Bilan", NOW).presentation.engine is Engine.REMOTION
    assert ps.new_presentation("Bilan", NOW, engine=Engine.SLIDECAR).presentation.engine is Engine.SLIDECAR


def test_a_stored_document_with_no_engine_reads_as_slidecar_and_is_not_converted():
    old = fixture("presentation.v2.json")
    assert "engine" not in old
    parsed = ps.parse_presentation(old)
    assert parsed.engine is Engine.SLIDECAR
    assert eng.engine_of_document(None) is Engine.SLIDECAR
    assert parsed.to_document()["engine"] == "slidecar" and parsed.to_document()["schema_version"] == 3
    # a v1 manifest travels the whole chain
    assert ps.parse_presentation(fixture("presentation.v1.json")).engine is Engine.SLIDECAR


def test_a_remotion_document_round_trips_and_an_unknown_engine_is_refused_by_name():
    document = {**fixture("presentation.v3.json"), "engine": "remotion"}
    parsed = ps.parse_presentation(document)
    assert parsed.engine is Engine.REMOTION and parsed.to_document() == document
    for bad in ("Remotion", "sidecar", "", None, 3, ["remotion"]):
        error = refused(lambda bad=bad: ps.parse_presentation({**document, "engine": bad}), C.INVALID_PRESENTATION)
        assert "engine" in error.message


def test_the_summary_makes_the_engine_observable():
    assert ps.parse_presentation(fixture("presentation.v2.json")).summary()["engine"] == "slidecar"
    assert ps.new_presentation("x", NOW).presentation.summary()["engine"] == "remotion"


async def test_the_service_creates_remotion_and_a_create_body_cannot_carry_an_engine(tmp_path):
    service = PresentationStudioService(FilePresentationStudioStore(tmp_path), clock=lambda: NOW)
    view = await service.create({"title": "Atelier"})
    assert view.presentation.engine is Engine.REMOTION
    for body in ({"title": "x", "engine": "slidecar"}, {"title": "x", "engine": "remotion"}):
        with pytest.raises(PresentationStudioError) as caught:
            await service.create(body)
        assert caught.value.code is C.INVALID_PRESENTATION and "unknown keys" in caught.value.message
    again = await service.get(view.presentation.presentation_id)
    assert again.presentation.engine is Engine.REMOTION


def test_an_update_body_cannot_change_the_engine():
    with pytest.raises(PresentationStudioError):
        ps.parse_presentation_update({"expected_revision": 1, "title": "x", "resources": [], "engine": "slidecar"})


# ------------------------------------------------------------------ selection policy

def test_nothing_named_gives_the_default_to_every_actor():
    for actor in EngineActor:
        assert POLICY.select(None, actor) is Engine.REMOTION


@pytest.mark.parametrize("requested", ["slidecar", "remotion", Engine.SLIDECAR, Engine.REMOTION])
@pytest.mark.parametrize("actor", [EngineActor.AGENT, EngineActor.SYSTEM, "agent", "brain", "", None, "HUMAN"])
def test_only_a_human_can_name_an_engine_an_agent_cannot_even_name_the_default(requested, actor):
    refused(lambda: POLICY.select(requested, actor), C.ENGINE_SELECTION_REFUSED)


def test_a_human_may_pick_either_engine_and_a_typo_is_invalid_not_defaulted():
    assert POLICY.select("slidecar", EngineActor.HUMAN) is Engine.SLIDECAR
    assert POLICY.select("remotion", "human") is Engine.REMOTION
    for typo in ("sidecar", "Slidecar", "html", "", 7):
        refused(lambda typo=typo: POLICY.select(typo, EngineActor.HUMAN), C.INVALID_PRESENTATION)


def test_the_refusal_names_the_default_and_never_the_other_engine_as_a_way_out():
    message = refused(lambda: POLICY.select("slidecar", EngineActor.AGENT), C.ENGINE_SELECTION_REFUSED).message
    assert "remotion" in message and "only a person" in message


# ------------------------------------------------------------------ no fallback

READY = EngineAvailability(True)
DOWN = EngineAvailability(False, "node is not installed", "run the one-time setup")


@pytest.mark.parametrize("engine,other_state", list(itertools.product(Engine, [READY, DOWN])))
def test_an_unavailable_engine_is_a_typed_failure_whatever_the_other_engine_says(engine, other_state):
    other = Engine.SLIDECAR if engine is Engine.REMOTION else Engine.REMOTION
    error = refused(lambda: eng.resolve_engine(engine, {engine: DOWN, other: other_state}), C.ENGINE_UNAVAILABLE)
    assert engine.value in error.message and "node is not installed" in error.message and "run the one-time setup" in error.message
    assert error.status == 409


def test_remotion_down_with_slidecar_ready_never_yields_slidecar():
    for state in ({Engine.REMOTION: DOWN, Engine.SLIDECAR: READY}, {Engine.SLIDECAR: READY}):
        refused(lambda state=state: eng.resolve_engine(Engine.REMOTION, state), C.ENGINE_UNAVAILABLE)


def test_resolution_is_always_the_requested_engine_or_a_failure():
    for engine, state in itertools.product(Engine, [READY, DOWN, None]):
        availability = {} if state is None else {engine: state}
        try:
            resolved = eng.resolve_engine(engine, availability)
        except PresentationStudioError as exc:
            assert exc.code is C.ENGINE_UNAVAILABLE and state is not READY
        else:
            assert resolved.engine is engine and state is READY


def test_resolution_reads_the_state_of_the_requested_engine_only():
    reads: list = []

    class Spy(dict):
        def get(self, key, default=None):
            reads.append(key)
            return super().get(key, default)

    refused(lambda: eng.resolve_engine(Engine.REMOTION, Spy({Engine.REMOTION: DOWN, Engine.SLIDECAR: READY})), C.ENGINE_UNAVAILABLE)
    assert reads == [Engine.REMOTION]


def test_a_not_ready_state_must_say_why():
    with pytest.raises(ValueError):
        EngineAvailability(False)


def test_the_resolution_gate_names_no_concrete_engine():
    """Mutation guard: re-introducing a fallback means naming a concrete engine or a default inside the gate."""

    tree = ast.parse(inspect.getsource(eng.resolve_engine))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not names & {"SLIDECAR", "REMOTION", "LEGACY_ENGINE", "DEFAULT_ENGINE"}, names


# ------------------------------------------------------------------ capabilities and triage

def test_every_engine_declares_every_capability_and_slidecar_has_no_export():
    for engine in Engine:
        assert set(CAPABILITIES[engine]) == set(Capability)
    assert eng.capability_of(Engine.SLIDECAR, Capability.EXPORT) is Support.UNSUPPORTED
    assert eng.capability_of(Engine.REMOTION, Capability.EXPORT) is Support.NATIVE
    assert eng.capability_of(Engine.SLIDECAR, Capability.MOTION) is Support.ADAPTER


def test_an_unsupported_capability_is_a_typed_refusal_not_a_silent_skip():
    refused(lambda: eng.require_capability(Engine.SLIDECAR, Capability.EXPORT), C.ENGINE_UNSUPPORTED)
    assert eng.require_capability(Engine.SLIDECAR, Capability.MOTION) is Support.ADAPTER
    assert eng.require_capability(Engine.REMOTION, Capability.EXPORT) is Support.NATIVE


def test_undeclared_compatibility_is_unsupported_never_guessed():
    for declared in (None, {}, {"slidecar": "native"}):
        assert eng.classify_compatibility(declared, Engine.REMOTION) is Support.UNSUPPORTED
    assert eng.classify_compatibility({"remotion": "adapter"}, Engine.REMOTION) is Support.ADAPTER
    assert eng.classify_compatibility({Engine.REMOTION: "native"}, Engine.REMOTION) is Support.NATIVE
    refused(lambda: eng.classify_compatibility({"remotion": "maybe"}, Engine.REMOTION), C.INVALID_PRESENTATION)
    refused(lambda: eng.classify_compatibility({"flash": "native"}, Engine.REMOTION), C.INVALID_PRESENTATION)


def test_a_legacy_html_prefab_is_native_in_slidecar_and_refused_in_remotion():
    legacy = eng.legacy_html_compatibility()
    assert eng.require_compatible(legacy, Engine.SLIDECAR) is Support.NATIVE
    error = refused(lambda: eng.require_compatible(legacy, Engine.REMOTION, what="jarvis.window"), C.ENGINE_UNSUPPORTED)
    assert "jarvis.window" in error.message and "remotion" in error.message
    assert eng.require_compatible({"remotion": "adapter"}, Engine.REMOTION) is Support.ADAPTER


# ------------------------------------------------------------------ manifest metadata

def test_engine_identity_round_trips_and_derives_its_capabilities():
    identity = EngineIdentity(Engine.REMOTION, "4.0.200")
    document = identity.to_dict()
    assert document["engine"] == "remotion" and document["engine_version"] == "4.0.200"
    assert document["capabilities"]["export"] == "native"
    assert EngineIdentity.from_dict(document) == identity
    assert EngineIdentity.from_dict({"engine": "slidecar"}) == EngineIdentity(Engine.SLIDECAR, None)


def test_engine_identity_refuses_forged_capabilities_unknown_keys_and_bad_versions():
    forged = EngineIdentity(Engine.SLIDECAR).to_dict()
    forged["capabilities"]["export"] = "native"
    refused(lambda: EngineIdentity.from_dict(forged), C.INVALID_PRESENTATION)
    refused(lambda: EngineIdentity.from_dict({"engine": "remotion", "path": "C:/x"}), C.INVALID_PRESENTATION)
    refused(lambda: EngineIdentity.from_dict({"engine_version": "1"}), C.INVALID_PRESENTATION)
    refused(lambda: EngineIdentity(Engine.REMOTION, "x" * 41), C.INVALID_PRESENTATION)


def test_the_new_error_codes_have_http_statuses():
    assert [ps.HTTP_STATUS[c] for c in (C.ENGINE_UNAVAILABLE, C.ENGINE_UNSUPPORTED, C.ENGINE_SELECTION_REFUSED)] == [409, 409, 403]

"""Vocabulaire et moteur d'edition semantique du Studio (jarvis-interactive-presentation-studio, Slice 05) : domaine pur.

Classification par niveau (table), analyse de la requete, transaction tout-ou-rien, preconditions, cles dangereuses,
operations inverses (rejouer l'inverse retablit les scenes a l'octet pres), comparaison par forme stockee.
Contrat : `docs/presentation-studio.md` > *Semantic edit contract*.
"""

from __future__ import annotations

import json

import pytest

from jarvis.domain.prefab import InputType, PrefabRef, canonical_json, parse_manifest
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_edit import (
    ALLOWED_EDIT_OPS, MAX_OPS, MAX_UNDO_BYTES, UNSAFE_KEYS, ControlReset, ControlSet, EditMode, EditRefusal,
    EditResult, EditStatus, EditTier, OpName, RestoreValues, SceneAdd, SceneRemove, SceneRename, SceneReorder, SceneSetControls,
    SourceRequest, StudioActor, actor_refusal, apply_ops, classify_op, highest_tier, parse_edit_request, parse_op,
    scenes_changed, undo_record, unsafe_key_in,
)
from jarvis.domain.presentation_studio_scene import ControlBounds, ScoreAnchor, StudioControl, StudioScene
from tests.fakes.prefabs import candidate

PID = "pst_" + "a" * 32
VID = "psv_" + "b" * 32
S1, S2, S3 = "pss_0000000000a1", "pss_0000000000a2", "pss_0000000000a3"
PIN = PrefabRef("test.counter", 1)
MANIFEST = parse_manifest(candidate()["manifest"])
MANIFESTS = {("test.counter", 1): MANIFEST}

CONTROLS = (
    StudioControl("headline", "props.label", "Titre", "content", "Texte"),
    StudioControl("density", "props.mode", "Densite", "layout", bounds=ControlBounds(choices=("compact", "full"))),
    StudioControl("start_count", "data.count", "Valeur", "content", default=10, bounds=ControlBounds(min=0, max=100)),
    StudioControl("notes", "data.notes", "Notes", "content", bounds=ControlBounds(max_length=50)),
    StudioControl("history", "data.history", "Historique", "content"),
)


def scene(scene_id=S1, **kw) -> StudioScene:
    kw.setdefault("title", "Ouverture")
    kw.setdefault("props", {"label": "Visiteurs"})
    kw.setdefault("data", {"count": 12})
    kw.setdefault("controls", CONTROLS)
    return StudioScene(scene_id, PIN, **kw)


def scenes3() -> tuple[StudioScene, ...]:
    return (scene(S1), scene(S2, title="Milieu"), scene(S3, title="Fin"))


def run(scenes, *ops, actor=StudioActor.USER):
    return apply_ops(scenes, ops, MANIFESTS, presentation_id=PID, variant_id=VID, actor=actor, basis_revision=1)


def refusal(scenes, *ops) -> EditRefusal:
    with pytest.raises(EditRefusal) as caught:
        run(scenes, *ops)
    return caught.value


def stored(scenes) -> str:
    return canonical_json([s.to_dict() for s in scenes])


# ------------------------------------------------------------------ niveaux

NODE = {"label": InputType.STRING, "count": InputType.INTEGER, "history": InputType.ARRAY, "mode": InputType.ENUM}


@pytest.mark.parametrize("op, node, tier", [
    (ControlSet(S1, "headline", "x"), InputType.STRING, EditTier.CONTROL),
    (ControlSet(S1, "start_count", 3), InputType.INTEGER, EditTier.CONTROL),
    (ControlSet(S1, "density", "full"), InputType.ENUM, EditTier.CONTROL),
    (ControlSet(S1, "history", []), InputType.ARRAY, EditTier.STRUCTURE),  # a list changes the shape of the content
    (ControlReset(S1, "headline"), InputType.STRING, EditTier.CONTROL),
    (ControlReset(S1, "history"), InputType.ARRAY, EditTier.STRUCTURE),
    (RestoreValues(S1, {}, {}), None, EditTier.CONTROL),
    (SceneAdd(scene(S3)), None, EditTier.STRUCTURE),
    (SceneRemove(S1), None, EditTier.STRUCTURE),
    (SceneReorder(S1, 1), None, EditTier.STRUCTURE),
    (SceneRename(S1, "x"), None, EditTier.STRUCTURE),
    (SceneSetControls(S1, ()), None, EditTier.STRUCTURE),
    (SourceRequest(S1, "make the number glow"), None, EditTier.SOURCE),
])
def test_the_tier_comes_from_the_operation_and_the_control_metadata(op, node, tier):
    assert classify_op(op, node) is tier


def test_a_request_is_as_high_as_its_highest_operation():
    assert highest_tier([EditTier.CONTROL, EditTier.STRUCTURE]) is EditTier.STRUCTURE
    assert highest_tier([EditTier.SOURCE, EditTier.CONTROL, EditTier.STRUCTURE]) is EditTier.SOURCE
    assert highest_tier([]) is EditTier.CONTROL
    plan = run(scenes3(), ControlSet(S1, "headline", "a"), SceneRename(S2, "b"))
    assert plan.tier is EditTier.STRUCTURE and [o["tier"] for o in plan.outcomes] == ["control", "structure"]
    assert run(scenes3(), ControlSet(S1, "history", [{"delta": 1}])).tier is EditTier.STRUCTURE
    assert run(scenes3(), SourceRequest(S1, "glow")).tier is EditTier.SOURCE


def test_both_actors_hold_the_whole_vocabulary_and_an_unknown_actor_cannot_be_parsed():
    assert set(ALLOWED_EDIT_OPS) == set(StudioActor)
    for actor in StudioActor:
        assert ALLOWED_EDIT_OPS[actor] == frozenset(OpName)
        assert actor_refusal(actor, [ControlSet(S1, "headline", "x"), SourceRequest(S1, "glow")]) is None
    for bad in ("system", "runtime", "USER", "", None, 1):
        with pytest.raises(PresentationStudioError) as caught:
            parse_edit_request({"actor": bad, "mode": "commit", "basis": {"variant_revision": 1},
                                "ops": [{"op": "scene.remove", "scene_id": S1}]})
        assert caught.value.code is C.INVALID_PRESENTATION


# ------------------------------------------------------------------ analyse

def request_body(*ops, **changes) -> dict:
    return {"actor": "user", "mode": "commit", "basis": {"variant_revision": 3}, "ops": list(ops), **changes}


def test_every_operation_round_trips_through_its_wire_form():
    ops = [ControlSet(S1, "headline", "x", ("old",)), ControlReset(S1, "headline"), RestoreValues(S1, {"a": 1}, {}),
           SceneAdd(scene(S3), 1), SceneRemove(S1), SceneReorder(S1, 2), SceneRename(S1, "x"),
           SceneSetControls(S1, CONTROLS[:2]), SourceRequest(S1, "glow")]
    assert {op.NAME for op in ops} == set(OpName)
    for op in ops:
        assert parse_op(json.loads(json.dumps(op.to_dict()))) == op


def test_a_well_formed_request_parses():
    parsed = parse_edit_request(request_body({"op": "control.set", "scene_id": S1, "control_id": "headline",
                                              "value": "Bonjour"}, {"op": "scene.reorder", "scene_id": S1, "to_index": 2}))
    assert (parsed.actor, parsed.mode, parsed.basis_revision) == (StudioActor.USER, EditMode.COMMIT, 3)
    assert parsed.op_names == ("control.set", "scene.reorder")


@pytest.mark.parametrize("body", [
    request_body(),  # no operation
    request_body(*[{"op": "scene.remove", "scene_id": S1}] * (MAX_OPS + 1)),
    {**request_body({"op": "scene.remove", "scene_id": S1}), "extra": 1},
    {"actor": "user", "mode": "commit", "ops": [{"op": "scene.remove", "scene_id": S1}]},  # no basis: a blind write
    request_body({"op": "scene.remove", "scene_id": S1}, basis={"variant_revision": 0}),
    request_body({"op": "scene.remove", "scene_id": S1}, basis={"variant_revision": True}),
    request_body({"op": "scene.remove", "scene_id": S1}, mode="dry_run"),
    request_body({"op": "scene.delete", "scene_id": S1}),
    request_body({"op": "scene.remove", "scene_id": "nope"}),
    request_body({"op": "scene.remove", "scene_id": S1, "selection": "x"}),  # a runtime key has its own code
    request_body({"op": "control.set", "scene_id": S1, "control_id": "headline"}),  # no value
    request_body({"op": "scene.reorder", "scene_id": S1, "to_index": -1}),
    request_body({"op": "scene.reorder", "scene_id": S1, "to_index": True}),
    request_body({"op": "scene.source_request", "scene_id": S1, "intent": "  padded "}),
    request_body({"op": "scene.source_request", "scene_id": S1, "intent": "x" * 401}),
    request_body({"op": "scene.source_request", "scene_id": S1, "intent": "two\nlines"}),
    request_body("not an object"),
    "not an object",
])
def test_malformed_requests_are_refused_with_a_coded_error(body):
    with pytest.raises(PresentationStudioError) as caught:
        parse_edit_request(body)
    assert caught.value.code in (C.INVALID_PRESENTATION, C.RUNTIME_STATE_REFUSED)


def test_a_scene_added_without_an_id_gets_one_from_the_injected_source():
    parsed = parse_edit_request(request_body({"op": "scene.add", "scene": {"prefab": {"id": "test.counter", "version": 1}}}),
                                new_id=lambda: S3)
    assert parsed.ops[0].scene.scene_id == S3


# ------------------------------------------------------------------ controles

def test_set_changes_only_the_declared_path_and_reports_before_and_after():
    base = scenes3()
    plan = run(base, ControlSet(S1, "headline", "Bonjour"))
    assert plan.scenes[0].props == {"label": "Bonjour"} and plan.scenes[1:] == base[1:]
    assert plan.outcomes[0] | {} == {**plan.outcomes[0], "before": "Visiteurs", "after": "Bonjour", "changed": True,
                                     "was_set": True, "is_set": True, "index": 0, "op": "control.set",
                                     "tier": "control"}
    assert base[0].props == {"label": "Visiteurs"}  # the input is never mutated


def test_a_numeric_literal_change_is_a_real_change_even_when_python_calls_the_values_equal():
    data = candidate()["manifest"]
    data["inputs"]["data"]["properties"]["ratio"] = {"type": "number", "min": 0, "max": 10}
    manifests = {("test.counter", 1): parse_manifest(data)}
    ratio = StudioControl("ratio", "data.ratio", "Ratio", "visual")
    start = (scene(data={"count": 1, "ratio": 1}, controls=(*CONTROLS, ratio)),)
    plan = apply_ops(start, [ControlSet(S1, "ratio", 1.0)], manifests, presentation_id=PID, variant_id=VID,
                     actor=StudioActor.USER, basis_revision=1)
    assert start[0] == plan.scenes[0]  # the trap: dataclass equality says "unchanged"
    assert plan.outcomes[0]["changed"] is True and len(plan.inverse) == 1
    assert plan.scenes[0].to_dict()["data"]["ratio"] == 1.0 and type(plan.scenes[0].data["ratio"]) is float


def test_a_set_to_the_same_value_is_a_no_op_without_an_inverse():
    plan = run(scenes3(), ControlSet(S1, "headline", "Visiteurs"))
    assert plan.outcomes[0]["changed"] is False and plan.inverse == []
    assert not scenes_changed(scenes3(), plan.scenes)


def test_stored_forms_are_compared_never_python_equality():
    one, true, flo = (scene(data={"count": v}) for v in (1, True, 1.0))
    assert one == true == flo  # the trap: dataclass equality
    assert scenes_changed((one,), (true,)) and scenes_changed((one,), (flo,))


@pytest.mark.parametrize("value", [-1, 101, True, 1.5, "7", None, [1]])
def test_a_bad_value_for_the_integer_control_is_refused(value):
    caught = refusal(scenes3(), ControlSet(S1, "start_count", value))
    assert caught.code is C.VALUE_REFUSED and caught.index == 0 and not caught.stale


def test_curated_bounds_are_enforced_on_top_of_the_manifest():
    assert refusal(scenes3(), ControlSet(S1, "notes", "x" * 51)).code is C.VALUE_REFUSED
    assert refusal(scenes3(), ControlSet(S1, "density", "huge")).code is C.VALUE_REFUSED
    assert run(scenes3(), ControlSet(S1, "notes", "x" * 50)).outcomes[0]["changed"] is True


def test_an_unknown_scene_or_control_is_refused_and_points_to_the_source_request():
    assert refusal(scenes3(), ControlSet("pss_00000000ffff", "headline", "x")).code is C.UNKNOWN_SCENE
    unknown = refusal(scenes3(), ControlSet(S1, "glow", "x"))
    assert unknown.code is C.UNKNOWN_CONTROL and "scene.source_request" in unknown.message


def test_if_current_is_a_precondition_on_what_the_inspector_shows():
    ok = run(scenes3(), ControlSet(S1, "headline", "A", ("Visiteurs",)))
    assert ok.scenes[0].props["label"] == "A"
    stale = refusal(scenes3(), ControlSet(S1, "headline", "A", ("Autre",)))
    assert stale.stale and stale.code is C.STALE_REVISION
    # the displayed value falls back to the curated default when nothing is set
    assert run(scenes3(), ControlSet(S1, "notes", "n", ("",))).outcomes[0]["changed"] is True
    fresh = (scene(data={}),)
    assert run(fresh, ControlSet(S1, "start_count", 11, (10,))).scenes[0].data == {"count": 11}
    # 1 / true / 1.0 are three different expectations
    assert refusal((scene(data={"count": 1}),), ControlSet(S1, "start_count", 2, (True,))).stale


def test_reset_writes_the_curated_default_or_unsets_the_key():
    to_default = run(scenes3(), ControlReset(S1, "start_count"))
    assert to_default.scenes[0].data == {"count": 10}
    unset = run(scenes3(), ControlReset(S1, "headline"))
    assert unset.scenes[0].props == {} and unset.outcomes[0]["is_set"] is False
    again = run(unset.scenes, ControlReset(S1, "headline"))
    assert again.outcomes[0]["changed"] is False and again.inverse == []


# ------------------------------------------------------------------ cles dangereuses

@pytest.mark.parametrize("value", [
    {"__proto__": {"x": 1}}, [{"a": {"constructor": 1}}], {"prototype": 1}, [[[{"__proto__": 1}]]],
])
def test_a_reserved_key_anywhere_in_a_value_is_found(value):
    assert unsafe_key_in(value) in UNSAFE_KEYS


def test_a_value_too_deep_or_too_large_is_never_walked_to_the_end():
    deep: object = 1
    for _ in range(40):
        deep = [deep]
    assert unsafe_key_in(deep) == "<too deep or too large>"
    assert unsafe_key_in(list(range(5000))) == "<too deep or too large>"
    assert unsafe_key_in({"label": "ok", "items": [1, 2, {"a": "b"}]}) is None


def test_a_set_with_a_reserved_key_in_its_value_is_refused_before_the_schema():
    caught = refusal(scenes3(), ControlSet(S1, "history", [{"delta": 1, "__proto__": {"polluted": True}}]))
    assert caught.code is C.INVALID_PRESENTATION and "reserved key" in caught.message


@pytest.mark.parametrize("name", sorted(UNSAFE_KEYS))
def test_a_control_whose_path_names_a_reserved_property_is_never_written(name):
    # The path grammar of a control accepts these names (prefab PROPERTY_NAME does too): the edit layer is the guard.
    bad = StudioControl("evil", f"props.{name}", "Evil", "content")
    target = scene(controls=(*CONTROLS, bad))
    caught = refusal((target,), ControlSet(S1, "evil", "x"))
    assert caught.code is C.INVALID_PRESENTATION and "reserved property name" in caught.message
    assert refusal((scene(),), SceneSetControls(S1, (bad,))).code is C.INVALID_PRESENTATION
    assert refusal((), SceneAdd(target)).code is C.INVALID_PRESENTATION
    assert "polluted" not in json.dumps(target.to_dict())


def test_restored_values_with_a_reserved_key_are_refused():
    assert refusal(scenes3(), RestoreValues(S1, {"__proto__": 1}, {})).code is C.INVALID_PRESENTATION


def test_a_non_object_intermediate_is_never_overwritten():
    nested = StudioControl("deep", "props.label.inner", "Deep", "content")
    target = scene(controls=(*CONTROLS, nested), props={"label": "text"})
    caught = refusal((target,), ControlSet(S1, "deep", "x"))
    assert caught.code in (C.VALUE_REFUSED, C.SCENE_INCOMPATIBLE)
    assert target.props == {"label": "text"}


# ------------------------------------------------------------------ structure

def test_structure_operations_on_stable_ids():
    base = scenes3()
    added = run(base, SceneAdd(scene("pss_0000000000a4", title="Ajout"), 1))
    assert [s.scene_id for s in added.scenes] == [S1, "pss_0000000000a4", S2, S3]
    assert [s.scene_id for s in run(base, SceneRemove(S2)).scenes] == [S1, S3]
    assert [s.scene_id for s in run(base, SceneReorder(S1, 2)).scenes] == [S2, S3, S1]
    assert run(base, SceneRename(S3, "Conclusion")).scenes[2].title == "Conclusion"
    assert run(base, SceneReorder(S2, 1)).outcomes[0]["changed"] is False


def test_structure_refusals():
    base = scenes3()
    assert refusal(base, SceneAdd(scene(S1))).code is C.INVALID_PRESENTATION  # duplicate id
    assert refusal(base, SceneAdd(scene("pss_0000000000a9"), 9)).code is C.INVALID_PRESENTATION
    assert refusal(base, SceneRemove("pss_00000000ffff")).code is C.UNKNOWN_SCENE
    assert refusal(base, SceneReorder(S1, 3)).code is C.INVALID_PRESENTATION
    assert refusal(base, SceneRename(S1, "x" * 81)).code is C.INVALID_PRESENTATION
    many = tuple(scene(f"pss_{i:012x}") for i in range(64))
    assert refusal(many, SceneAdd(scene("pss_0000000000ff"))).code is C.LIMIT_REACHED


def test_set_controls_must_keep_the_anchors_and_the_manifest_consistent():
    with_anchor = scene(anchors=(ScoreAnchor("beat", "Repere", "start_count"),))
    caught = refusal((with_anchor,), SceneSetControls(S1, CONTROLS[:1]))
    assert caught.code is C.INVALID_PRESENTATION and "beat" in caught.message
    missing = StudioControl("ghost", "props.nope", "Ghost", "content")
    assert refusal(scenes3(), SceneSetControls(S1, (missing,))).code is C.SCENE_INCOMPATIBLE
    assert run(scenes3(), SceneSetControls(S1, CONTROLS[:2])).scenes[0].controls == CONTROLS[:2]


def test_a_source_request_changes_nothing_and_is_recorded_only():
    plan = run(scenes3(), SourceRequest(S2, "make the number glow"))
    assert plan.scenes == scenes3() and plan.tier is EditTier.SOURCE and plan.inverse == []
    assert plan.outcomes[0]["effect"] == "recorded_only" and plan.outcomes[0]["changed"] is False
    assert plan.outcomes[0]["request_id"].startswith("psq_") and plan.sources[0].intent == "make the number glow"
    assert refusal(scenes3(), SourceRequest("pss_00000000ffff", "x")).code is C.UNKNOWN_SCENE


# ------------------------------------------------------------------ transaction

def test_the_first_refused_operation_cancels_the_whole_batch_and_names_its_index():
    base = scenes3()
    before = stored(base)
    caught = refusal(base, ControlSet(S1, "headline", "A"), SceneRename(S2, "B"), ControlSet(S3, "start_count", 999),
                     SceneRemove(S1))
    assert caught.index == 2 and caught.code is C.VALUE_REFUSED
    assert stored(base) == before  # nothing partial: the engine works on copies


def test_operations_see_the_effect_of_the_ones_before_them():
    added = scene("pss_0000000000a4")
    plan = run(scenes3(), SceneAdd(added), ControlSet("pss_0000000000a4", "headline", "Neuf"), SceneReorder("pss_0000000000a4", 0))
    assert [s.scene_id for s in plan.scenes][0] == "pss_0000000000a4" and plan.scenes[0].props["label"] == "Neuf"
    assert refusal(scenes3(), SceneRemove(S1), ControlSet(S1, "headline", "x")).index == 1


# ------------------------------------------------------------------ annulation

BATCHES = {
    "set": [ControlSet(S1, "headline", "Autre"), ControlSet(S2, "start_count", 7)],
    "reset": [ControlReset(S1, "start_count"), ControlReset(S1, "headline")],
    "array": [ControlSet(S1, "history", [{"delta": 3}, {"delta": -4, "ratio": 0.25}])],
    "add_remove": [SceneAdd(scene("pss_0000000000a4"), 0), SceneRemove(S2)],
    "reorder_rename": [SceneReorder(S1, 2), SceneRename(S3, "Autre titre"), SceneRename(S3, "Encore")],
    "controls": [SceneSetControls(S1, CONTROLS[:2]), ControlSet(S1, "headline", "Z")],
    "mixed": [SceneRemove(S1), ControlSet(S2, "headline", "M"), SceneAdd(scene(S1, title="Re"), 2), SceneReorder(S1, 0)],
    "set_then_unset": [ControlSet(S1, "notes", "n"), ControlReset(S1, "notes")],
}


@pytest.mark.parametrize("name", sorted(BATCHES))
def test_replaying_the_inverse_restores_the_scenes_byte_for_byte(name):
    base = scenes3()
    forward = run(base, *BATCHES[name])
    assert scenes_changed(base, forward.scenes) or name == "set_then_unset"
    record = undo_record(forward, presentation_id=PID, variant_id=VID, restores_revision=1, applies_at_revision=2)
    assert record["available"] and record["applies_at_revision"] == 2 and record["restores_revision"] == 1
    wire = json.loads(json.dumps(record["ops"]))  # through JSON, as the ring will hold it
    back = run(forward.scenes, *[parse_op(op) for op in wire])
    assert stored(back.scenes) == stored(base)
    # and the undo of the undo is the forward edit again (redo)
    again = run(back.scenes, *[parse_op(op) for op in back.inverse])
    assert stored(again.scenes) == stored(forward.scenes)


def test_an_undo_record_is_bounded(monkeypatch):
    plan = run(scenes3(), SceneRemove(S1), SceneRemove(S2))
    small = undo_record(plan, presentation_id=PID, variant_id=VID, restores_revision=1, applies_at_revision=2)
    assert small["available"] is True and small["bytes"] < MAX_UNDO_BYTES
    monkeypatch.setattr("jarvis.domain.presentation_studio_edit.MAX_UNDO_BYTES", small["bytes"] - 1)
    record = undo_record(plan, presentation_id=PID, variant_id=VID, restores_revision=1, applies_at_revision=2)
    assert record["available"] is False and record["reason"] == "too_large" and "ops" not in record


def test_a_no_op_batch_has_nothing_to_undo():
    plan = run(scenes3(), ControlSet(S1, "headline", "Visiteurs"), SceneRename(S1, "Ouverture"))
    assert plan.inverse == [] and not scenes_changed(scenes3(), plan.scenes)


def test_the_results_wire_form_is_stable_and_carries_an_error_envelope_only_when_not_applied():
    ok = EditResult(EditStatus.APPLIED, EditMode.COMMIT, StudioActor.BRAIN, PID, VID, 1, 2, committed=True, changed=True,
                    tier=EditTier.CONTROL)
    assert ok.http_status == 200 and "error" not in ok.to_dict() and ok.to_dict()["basis"] == {"variant_revision": 1}
    stale = EditResult(EditStatus.STALE, EditMode.COMMIT, StudioActor.USER, PID, VID, 1, 5, code=C.STALE_REVISION.value, message="m")
    assert stale.http_status == 409 and stale.to_dict()["error"] == {"code": C.STALE_REVISION.value, "message": "m"}
    refused = EditResult(EditStatus.REFUSED, EditMode.PREVIEW, StudioActor.USER, PID, VID, 1, 1,
                         code=C.UNKNOWN_CONTROL.value, message="m", failed_index=0)
    assert refused.http_status == 404 and refused.to_dict()["failed_index"] == 0
    assert refused.to_dict()["status"] == "refused" and refused.to_dict()["committed"] is False


# ------------------------------------------------------------------ rework QA-1

def nested_manifests():
    data = candidate()["manifest"]
    data["inputs"]["props"]["properties"]["style"] = {
        "type": "object", "properties": {"tone": {"type": "string", "max_length": 10}}}
    data["inputs"]["props"]["properties"]["__proto__"] = {"type": "string", "max_length": 10}
    return {("test.counter", 1): parse_manifest(data)}


def run_with(manifests, scenes, *ops):
    return apply_ops(scenes, ops, manifests, presentation_id=PID, variant_id=VID, actor=StudioActor.BRAIN, basis_revision=1)


def test_restore_values_is_refused_on_any_path_without_a_declared_control():
    base = scenes3()
    for props, data, where in (({"label": "Visiteurs", "accent": "#ff0000"}, {"count": 12}, "props.accent"),
                               ({"label": "Visiteurs"}, {"count": 12, "link": "https://evil.example/x"}, "data.link")):
        caught = refusal(base, RestoreValues(S1, props, data))
        assert caught.code is C.UNKNOWN_CONTROL and where in caught.message and caught.index == 0
    # a path that holds an undeclared key today cannot be dropped either
    seeded = (scene(props={"label": "Visiteurs", "accent": "#00ff00"}),)
    assert refusal(seeded, RestoreValues(S1, {"label": "Visiteurs"}, {"count": 12})).code is C.UNKNOWN_CONTROL
    assert run(seeded, RestoreValues(S1, {"label": "Autre", "accent": "#00ff00"}, {"count": 12})).outcomes[0]["changed"]


def test_restore_values_under_a_list_control_is_structure_and_a_plain_one_is_control():
    lst = run(scenes3(), RestoreValues(S1, {"label": "Visiteurs"}, {"count": 12, "history": [{"delta": 1}]}))
    assert lst.tier is EditTier.STRUCTURE
    assert run(scenes3(), RestoreValues(S1, {"label": "Z"}, {"count": 12})).tier is EditTier.CONTROL
    forward = run(scenes3(), ControlSet(S1, "history", [{"delta": 1}]))
    back = run(forward.scenes, *[parse_op(op) for op in forward.inverse])
    assert forward.tier is EditTier.STRUCTURE and back.tier is EditTier.STRUCTURE


@pytest.mark.parametrize("initial", [{"label": "Visiteurs"}, {"label": "Visiteurs", "style": {}}])
def test_the_undo_of_a_nested_set_passes_the_restore_rule_and_is_exact(initial):
    manifests = nested_manifests()
    tone = StudioControl("tone", "props.style.tone", "Ton", "visual")
    base = (scene(props=initial, controls=(*CONTROLS, tone)),)
    forward = run_with(manifests, base, ControlSet(S1, "tone", "chaud"))
    assert forward.scenes[0].props["style"] == {"tone": "chaud"}
    back = run_with(manifests, forward.scenes, *[parse_op(op) for op in forward.inverse])
    assert stored(back.scenes) == stored(base) and list(back.scenes[0].props) == list(base[0].props)


def test_a_scene_added_with_a_reserved_key_in_its_own_values_is_refused():
    manifests = nested_manifests()
    evil = scene("pss_0000000000a4", props={"label": "x", "__proto__": "polluted"})
    caught = apply_refusal(manifests, evil)
    assert caught.code is C.INVALID_PRESENTATION and "reserved key" in caught.message
    assert run_with(manifests, scenes3(), SceneAdd(scene("pss_0000000000a4"))).outcomes[0]["changed"]


def apply_refusal(manifests, added):
    with pytest.raises(EditRefusal) as caught:
        run_with(manifests, scenes3(), SceneAdd(added))
    return caught.value


def test_the_set_and_the_reset_keep_the_key_order_of_the_scene_values():
    base = (scene(props={"label": "Visiteurs"}, data={"notes": "n", "count": 12}),)
    plan = run(base, ControlSet(S1, "start_count", 13))
    assert list(plan.scenes[0].data) == ["notes", "count"]
    back = run(plan.scenes, *[parse_op(op) for op in plan.inverse])
    assert list(back.scenes[0].data) == ["notes", "count"] and stored(back.scenes) == stored(base)

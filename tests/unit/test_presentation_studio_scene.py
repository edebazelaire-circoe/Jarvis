"""Scene logique et controles declares du Studio (jarvis-interactive-presentation-studio, Slice 04) : domaine pur.

Validation du schema de controle, bornes et enumerations, widgets derives du manifeste, compatibilite avec un vrai
`PrefabManifest` (fixture `test.counter`), introspection, stabilite des ids, plafond de charge de 16 KiB, entrees
mal formees. Contrat : `docs/presentation-studio.md` > *Scene and control contract*.
"""

from __future__ import annotations

import copy
import json

import pytest

from jarvis.domain import presentation_studio as ps
from jarvis.domain import presentation_studio_scene as sc
from jarvis.domain.prefab import InputType, PrefabRef, parse_input_schema, parse_manifest
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_scene import (
    ControlBounds, ControlGroup, ControlWidget, ScenePreview, ScoreAnchor, StudioControl, StudioScene,
)
from jarvis.domain.scene import MAX_PAYLOAD_BYTES, ScenePayload, ScenePrefabRef
from tests.fakes.prefabs import candidate

SCENE_ID = "pss_0000000000a1"
PIN = PrefabRef("test.counter", 1)


def refused(action, code: C = C.INVALID_PRESENTATION, contains: str = "") -> PresentationStudioError:
    with pytest.raises(PresentationStudioError) as caught:
        action()
    assert caught.value.code is code, caught.value
    assert contains in caught.value.message, caught.value.message
    return caught.value


def manifest(**changes):
    return parse_manifest(candidate(**changes)["manifest"])


def control(control_id="headline", path="props.label", label="Titre", group="content", meaning="", **kw):
    return StudioControl(control_id, path, label, group, meaning, **kw)


CONTROLS = (
    control("headline", "props.label", "Titre", "content", "Texte principal du compteur"),
    control("accent_color", "props.accent", "Couleur d'accent", "visual", "Couleur du chiffre"),
    control("density", "props.mode", "Densite", "layout", "Compact ou complet",
            bounds=ControlBounds(choices=("compact",))),
    control("start_count", "data.count", "Valeur", "content", "Valeur affichee", default=10,
            bounds=ControlBounds(min=0, max=100)),
    control("notes", "data.notes", "Notes", "content", bounds=ControlBounds(max_length=50)),
)


def scene(**kw) -> StudioScene:
    kw.setdefault("data", {"count": 12})
    return StudioScene(SCENE_ID, PIN, **kw)


def full_scene(**kw) -> StudioScene:
    kw.setdefault("title", "Ouverture")
    kw.setdefault("section", "Intro")
    kw.setdefault("controls", CONTROLS)
    kw.setdefault("props", {"label": "Visiteurs", "mode": "compact"})
    kw.setdefault("anchors", (ScoreAnchor("reveal_count", "Reveler le chiffre", "start_count"),
                              ScoreAnchor("beat", "Repere")))
    kw.setdefault("preview", ScenePreview("Le chiffre cle", "Un grand nombre sur fond sombre"))
    return scene(**kw)


# ------------------------------------------------------------------ schema d'un controle

def test_a_control_round_trips_and_keeps_only_what_it_sets():
    c = CONTROLS[3]
    assert c.to_dict() == {"control_id": "start_count", "path": "data.count", "label": "Valeur", "group": "content",
                           "meaning": "Valeur affichee", "default": 10, "bounds": {"min": 0, "max": 100}}
    assert StudioControl.from_dict(c.to_dict()) == c
    bare = control()
    assert bare.to_dict() == {"control_id": "headline", "path": "props.label", "label": "Titre", "group": "content",
                              "meaning": ""}  # no default and no bounds: nothing invented
    assert StudioControl.from_dict(bare.to_dict()) == bare and bare.root == "props" and bare.keys == ("label",)


@pytest.mark.parametrize("control_id", ["", "Headline", "1st", "a-b", "a b", "x" * 41, "é", "a.b"])
def test_a_control_id_is_a_closed_slug(control_id):
    refused(lambda: control(control_id=control_id), contains="control_id")


@pytest.mark.parametrize("path", ["props", "data", "", "style.color", "props.", "props.a-b", "props.a[0]", "props.0a",
                                  "props.a.b.c.d", "PROPS.a", "props..a", "props.a ", "props.__proto__x y", "css.color"])
def test_a_path_is_an_object_property_path_of_props_or_data_only(path):
    refused(lambda: control(path=path), contains="path must be props.<name> or data.<name>")


def test_the_deepest_path_is_the_manifest_depth_limit():
    assert control(path="props.a.b.c").keys == ("a", "b", "c")
    refused(lambda: control(path="props.a.b.c.d"))


@pytest.mark.parametrize(("name", "value"), [("label", ""), ("label", "x" * 41), ("label", "a\nb"), ("label", " a"),
                                             ("label", 5), ("meaning", "x" * 161), ("meaning", "a\tb"),
                                             ("meaning", " lead")])
def test_label_and_meaning_are_short_printable_lines(name, value):
    kw = {"label": "Titre", "meaning": ""}
    kw[name] = value
    refused(lambda: StudioControl("headline", "props.label", kw["label"], "content", kw["meaning"]), contains=name)


def test_the_group_is_a_closed_family():
    assert {g.value for g in ControlGroup} == {"content", "visual", "layout", "motion"}
    refused(lambda: control(group="css"), contains="group must be one of")
    assert control(group=ControlGroup.MOTION).group is ControlGroup.MOTION


@pytest.mark.parametrize("default", [float("nan"), float("inf"), {1, 2}, object(), "x" * 2001, {"a": ["y" * 2000]}])
def test_a_default_is_pure_bounded_json(default):
    refused(lambda: control(default=default), contains="default")


@pytest.mark.parametrize("bounds", [
    {"min": 5, "max": 1}, {"min": True}, {"max": float("nan")}, {"min": "1"}, {"max_length": 0}, {"max_length": 1.5},
    {"max_items": -1}, {"choices": ["a", "a"]}, {"choices": [1]}, {"choices": [""]}, {"choices": "ab"},
    {"choices": [str(i) for i in range(33)]}])
def test_malformed_bounds_are_refused(bounds):
    refused(lambda: ControlBounds.from_dict(bounds), contains="bounds")


def test_bounds_refuse_unknown_keys_so_there_is_no_style_escape_hatch():
    refused(lambda: ControlBounds.from_dict({"min": 1, "css": "x"}), contains="unknown keys css")
    refused(lambda: StudioControl.from_dict({**CONTROLS[0].to_dict(), "style": {"color": "red"}}),
            contains="unknown keys style")
    refused(lambda: StudioControl.from_dict({"control_id": "a", "path": "props.a", "label": "A"}), contains="missing")


# ------------------------------------------------------------------ la scene

def test_a_scene_round_trips_with_all_its_metadata():
    original = full_scene()
    wire = original.to_dict()
    assert list(wire) == ["scene_id", "prefab", "title", "section", "props", "data", "controls", "anchors", "preview",
                        "source_revision", "last_valid_pin"]
    assert StudioScene.from_dict(json.loads(json.dumps(wire))) == original
    assert wire["anchors"][1] == {"anchor_id": "beat", "label": "Repere", "control_id": None}
    assert wire["preview"] == {"caption": "Le chiffre cle", "alt": "Un grand nombre sur fond sombre"}


def test_a_bare_pin_is_a_valid_scene_with_defaults_and_the_alias_keeps_the_slice_02_name():
    bare = StudioScene.from_dict({"scene_id": SCENE_ID, "prefab": {"id": "test.counter", "version": 1}})
    assert bare == StudioScene(SCENE_ID, PIN) and ps.SceneRef is StudioScene
    assert (bare.title, bare.section, bare.props, bare.data, bare.controls, bare.anchors) == ("", "", {}, {}, (), ())


def test_a_scene_owns_private_copies_of_its_values():
    props = {"label": "A", "nested": {"k": [1]}}
    built = scene(props=props)
    props["label"] = "changed"
    props["nested"]["k"].append(2)
    assert built.props == {"label": "A", "nested": {"k": [1]}}
    built.to_dict()["props"]["label"] = "mutated"
    built.instance().props["label"] = "mutated"
    assert built.props["label"] == "A"


@pytest.mark.parametrize(("change", "message"), [
    ({"scene_id": "pss_xyz"}, "not a valid id"), ({"prefab": {"id": "test.counter", "version": 1}}, "PrefabRef"),
    ({"title": "x" * 81}, "title"), ({"title": " a"}, "title"), ({"title": "a\nb"}, "title"),
    ({"section": "x" * 41}, "section"), ({"section": "a\tb"}, "section"),
    ({"props": ["not", "an", "object"]}, "object"), ({"data": "no"}, "object"),
    ({"props": {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": 1}}}}}}}}}}, "nested deeper"),
    ({"props": {"k" * 65: 1}}, "key"), ({"props": {"a": "x\x00y"}}, "control characters"),
    ({"props": {"a": float("nan")}}, "finite"), ({"preview": {"caption": "x"}}, "ScenePreview"),
])
def test_a_scene_is_checked_at_construction(change, message):
    kw = {"scene_id": SCENE_ID, "prefab": PIN, **change}
    refused(lambda: StudioScene(**kw), contains=message)


def test_dictionary_input_is_checked_like_constructor_input():
    base = full_scene().to_dict()
    for path, value, message in [("controls", "no", "must be lists"), ("anchors", {}, "must be lists"),
                                 ("props", [], "must be an object"), ("title", 5, "title"),
                                 ("controls", [{}] * 33, "at most 32 controls"),
                                 ("anchors", [{}] * 17, "at most 32 controls and 16 anchors"),
                                 ("preview", {"caption": "x" * 121}, "caption"), ("prefab", {"id": "test.counter"}, "exactly"),
                                 ("controls", [5], "must be a JSON object")]:
        refused(lambda: StudioScene.from_dict({**base, path: value}), contains=message)
    refused(lambda: StudioScene.from_dict([]), contains="JSON object")


def test_runtime_handles_have_no_place_in_a_scene():
    for key in ("object_id", "window_id", "stage_object_id", "iframe", "playback", "position", "undo_stack"):
        refused(lambda: StudioScene.from_dict({**full_scene().to_dict(), key: "x"}),
                C.RUNTIME_STATE_REFUSED, "runtime-only state")
    # ...but a prefab's own data may legitimately use such words as VALUES
    assert StudioScene(SCENE_ID, PIN, data={"focus": 1, "selected": True}).data["focus"] == 1


def test_controls_and_anchors_are_unique_bounded_and_closed():
    refused(lambda: full_scene(controls=(CONTROLS[0], CONTROLS[0])), contains="control_id appears twice")
    refused(lambda: full_scene(controls=(CONTROLS[0], control("other", "props.label"))), contains="control path appears")
    refused(lambda: full_scene(anchors=(ScoreAnchor("a", "A"), ScoreAnchor("a", "B"))), contains="anchor_id appears twice")
    refused(lambda: full_scene(anchors=(ScoreAnchor("a", "A", "nope"),)), contains="does not declare")
    many = tuple(control(f"c{i}", f"props.p{i}") for i in range(33))
    refused(lambda: full_scene(controls=many), contains="controls exceed 32")
    assert len(full_scene(controls=many[:32], anchors=()).controls) == 32
    refused(lambda: full_scene(anchors=tuple(ScoreAnchor(f"a{i}", "A") for i in range(17))), contains="anchors exceed 16")
    refused(lambda: ScoreAnchor("Bad", "A"), contains="anchor_id")
    refused(lambda: ScoreAnchor("ok", ""), contains="label")
    refused(lambda: ScoreAnchor("ok", "A", "Bad Id"), contains="control_id")
    refused(lambda: ScenePreview("x" * 121), contains="caption")
    refused(lambda: ScenePreview("", "x" * 201), contains="alt")
    assert full_scene().control("density").path == "props.mode" and full_scene().control("zz") is None


# ------------------------------------------------------------------ plafond de charge (16 KiB)

def test_the_payload_cap_is_the_global_scene_cap_counted_the_same_way():
    base = StudioScene(SCENE_ID, PIN, title="t", data={"notes": ""})
    room = MAX_PAYLOAD_BYTES - base.budget()["bytes"]
    exact = StudioScene(SCENE_ID, PIN, title="t", data={"notes": "a" * room})
    budget = exact.budget()
    assert budget == {"bytes": MAX_PAYLOAD_BYTES, "limit": 16_384, "remaining": 0}
    assert len(json.dumps(exact.payload().to_payload(), ensure_ascii=False, separators=(",", ":")).encode()) == 16_384
    assert isinstance(exact.payload(), ScenePayload) and exact.payload().prefab.key == "test.counter@1"
    refused(lambda: StudioScene(SCENE_ID, PIN, title="t", data={"notes": "a" * (room + 1)}), contains="16384")


def test_the_cap_counts_bytes_not_characters_and_includes_the_title_and_both_blocks():
    base = StudioScene(SCENE_ID, PIN, data={"notes": "é" * 10}).budget()["bytes"]
    assert StudioScene(SCENE_ID, PIN, data={"notes": "e" * 10}).budget()["bytes"] == base - 10
    assert StudioScene(SCENE_ID, PIN, title="Titre", data={"notes": "é" * 10}).budget()["bytes"] > base
    assert StudioScene(SCENE_ID, PIN, props={"a": "x"}, data={"notes": "é" * 10}).budget()["bytes"] > base
    refused(lambda: StudioScene(SCENE_ID, PIN, props={"a": "é" * 4100}, data={"b": "é" * 4100}), contains="payload exceeds")


def test_what_the_studio_accepts_is_what_the_scene_service_accepts():
    block = ScenePrefabRef("test.counter", 1, {"p": "x" * 100}, {"d": [1, 2, 3]})
    studio = StudioScene(SCENE_ID, PIN, title="Titre", props=block.props, data=block.data)
    assert studio.payload() == ScenePayload(title="Titre", prefab=block)
    assert studio.instance() == block and studio.instance().to_payload() == block.to_payload()


# ------------------------------------------------------------------ widgets, bornes effectives

@pytest.mark.parametrize(("raw", "widget"), [
    ({"type": "string"}, "text_line"), ({"type": "text"}, "text_area"), ({"type": "boolean"}, "toggle"),
    ({"type": "color"}, "color"), ({"type": "enum", "values": ["a", "b"]}, "choice"), ({"type": "url"}, "url"),
    ({"type": "integer"}, "number"), ({"type": "integer", "min": 0}, "number"), ({"type": "integer", "min": 0, "max": 9}, "slider"),
    ({"type": "number", "min": 0, "max": 1}, "slider"), ({"type": "number", "max": 1}, "number"),
    ({"type": "array", "items": {"type": "string"}}, "list")])
def test_the_widget_comes_from_the_manifest_input_type(raw, widget):
    assert sc.widget_for(parse_input_schema(raw)) is ControlWidget(widget)


def test_a_curated_range_can_make_a_free_number_a_slider_but_never_the_reverse():
    node = parse_input_schema({"type": "integer", "min": 0})
    assert sc.widget_for(node) is ControlWidget.NUMBER
    assert sc.widget_for(node, ControlBounds(max=10)) is ControlWidget.SLIDER
    bounded = parse_input_schema({"type": "integer", "min": 0, "max": 9})
    assert sc.widget_for(bounded, ControlBounds(max=5)) is ControlWidget.SLIDER


def test_every_input_type_has_a_widget_except_object_which_is_never_a_control():
    assert {t for t in InputType} - {InputType.OBJECT} == {
        InputType.STRING, InputType.TEXT, InputType.NUMBER, InputType.INTEGER, InputType.BOOLEAN, InputType.COLOR,
        InputType.ENUM, InputType.URL, InputType.ARRAY}
    for raw in ({"type": t} for t in ("string", "text", "number", "integer", "boolean", "color", "url")):
        sc.widget_for(parse_input_schema(raw))
    assert "object" in sc.bounds_problem(parse_input_schema({"type": "object"}), ControlBounds())


def test_effective_bounds_are_the_intersection_of_manifest_and_curation():
    m = manifest()
    node = lambda path: sc.node_of(m, control(path=path))  # noqa: E731
    assert sc.effective_bounds(node("data.count"), ControlBounds()) == {"min": 0, "max": 1_000_000}
    assert sc.effective_bounds(node("data.count"), ControlBounds(min=5, max=50)) == {"min": 5, "max": 50}
    assert sc.effective_bounds(node("props.label"), ControlBounds()) == {"max_length": 40}
    assert sc.effective_bounds(node("props.label"), ControlBounds(max_length=10)) == {"max_length": 10}
    assert sc.effective_bounds(node("props.mode"), ControlBounds()) == {"choices": ["compact", "full"]}
    assert sc.effective_bounds(node("props.mode"), ControlBounds(choices=("full",))) == {"choices": ["full"]}
    assert sc.effective_bounds(node("data.history"), ControlBounds(max_items=3)) == {"max_items": 3}
    assert sc.effective_bounds(node("props.accent"), ControlBounds()) == {}
    assert sc.effective_bounds(node("data.link"), ControlBounds()) == {}


# ------------------------------------------------------------------ compatibilite avec le manifeste

def test_a_well_formed_scene_is_compatible_with_its_manifest():
    assert sc.check_scene(full_scene(), manifest()) == []


def bad(controls, **kw):
    return sc.check_scene(full_scene(controls=controls, anchors=(), **kw), manifest())


def test_a_path_the_manifest_does_not_declare_is_refused():
    errors = bad((control("ghost", "props.colour"),))
    assert errors == ["control ghost: props.colour is not declared by test.counter@1"]
    assert bad((control("deep", "props.label.more"),))[0].endswith("is not declared by test.counter@1")


def test_an_array_is_a_list_control_but_a_nested_object_property_path_is_followed():
    assert sc.check_scene(full_scene(controls=(control("hist", "data.history", bounds=ControlBounds(max_items=3)),),
                                     anchors=()), manifest()) == []
    raw = candidate(inputs={"props": {"type": "object", "properties": {"box": {"type": "object", "properties": {
        "w": {"type": "integer", "min": 1, "max": 9, "default": 3}, "inner": {"type": "object", "properties": {
            "c": {"type": "color"}}}}}}}, "data": {"type": "object", "properties": {}}}, sample={"props": {}, "data": {}}, events={})
    nested = parse_manifest(raw["manifest"])
    s = StudioScene(SCENE_ID, PIN, props={"box": {"w": 4}}, controls=(
        control("box_width", "props.box.w"), control("inner_color", "props.box.inner.c")))
    assert sc.check_scene(s, nested) == []
    described = sc.describe_scene(s, nested, order=0)["controls"]
    assert [(c["control_id"], c["current"], c["is_set"]) for c in described] == [
        ("box_width", 4, True), ("inner_color", None, False)]
    refused_object = StudioScene(SCENE_ID, PIN, controls=(control("box", "props.box"),))
    assert "binds an object" in sc.check_scene(refused_object, nested)[0]


@pytest.mark.parametrize(("path", "bounds", "message"), [
    ("data.count", ControlBounds(min=-1), "outside the manifest range"),
    ("data.count", ControlBounds(max=2_000_000), "outside the manifest range"),
    ("data.count", ControlBounds(min=0.5), "must be an integer"),
    ("data.count", ControlBounds(max_length=5), "accepts ['max', 'min']"),
    ("props.label", ControlBounds(max_length=41), "above the manifest limit 40"),
    ("props.label", ControlBounds(min=1), "accepts ['max_length']"),
    ("props.mode", ControlBounds(choices=("compact", "huge")), "not values of the manifest enum"),
    ("props.mode", ControlBounds(max_length=3), "accepts ['choices']"),
    ("props.accent", ControlBounds(choices=("#ffffff",)), "no curated bounds"),
    ("data.history", ControlBounds(max_items=9), "must be within [0, 8]"),
    ("data.history", ControlBounds(max_items=99), "must be within"),
])
def test_curated_bounds_may_narrow_the_manifest_never_widen_or_change_its_kind(path, bounds, message):
    errors = bad((control("c", path, bounds=bounds),))
    assert len(errors) == 1 and message in errors[0], errors


def test_curated_bounds_inside_the_manifest_are_accepted():
    ok = (control("a", "data.count", bounds=ControlBounds(min=0, max=1_000_000)),
          control("b", "props.label", bounds=ControlBounds(max_length=40)),
          control("c", "props.mode", bounds=ControlBounds(choices=("full", "compact"))),
          control("d", "data.history", bounds=ControlBounds(max_items=8)))
    assert bad(ok) == []


def test_a_curated_default_must_satisfy_the_schema_and_the_curated_bounds():
    assert bad((control("c", "data.count", default=50, bounds=ControlBounds(min=0, max=100)),)) == []
    assert "default" in bad((control("c", "data.count", default="ten"),))[0]
    assert "at most 100" in bad((control("c", "data.count", default=500, bounds=ControlBounds(max=100)),))[0]
    assert "must be one of" in bad((control("c", "props.mode", default="huge"),))[0]
    assert "#rrggbb" in bad((control("c", "props.accent", default="red"),))[0]
    assert "exceeds 40" in bad((control("c", "props.label", default="x" * 41),))[0]
    assert "exceeds 5" in bad((control("c", "props.label", default="x" * 6, bounds=ControlBounds(max_length=5)),))[0]


def test_a_stored_value_must_satisfy_the_manifest_and_the_curated_bounds():
    c = (control("n", "data.count", bounds=ControlBounds(min=10, max=20)),)
    assert sc.check_scene(full_scene(controls=c, anchors=(), data={"count": 15}), manifest()) == []
    assert "at least 10" in sc.check_scene(full_scene(controls=c, anchors=(), data={"count": 5}), manifest())[0]
    assert "at most 20" in sc.check_scene(full_scene(controls=c, anchors=(), data={"count": 25}), manifest())[0]
    assert "at most 1000000" in sc.check_scene(full_scene(controls=(control("n", "data.count"),), anchors=(),
                                                          data={"count": 5_000_000}), manifest())[0]
    assert "expected a finite integer" in sc.check_scene(full_scene(controls=c, anchors=(), data={"count": 1.5}),
                                                         manifest())[0]
    assert "expected a finite integer" in sc.check_scene(full_scene(controls=c, anchors=(), data={"count": True}),
                                                         manifest())[0]
    only_compact = (control("m", "props.mode", bounds=ControlBounds(choices=("compact",))),)
    assert "must be one of ['compact']" in sc.check_scene(
        full_scene(controls=only_compact, anchors=(), props={"mode": "full"}), manifest())[0]
    short = (control("l", "props.label", bounds=ControlBounds(max_length=3)),)
    assert "exceeds 3" in sc.check_scene(full_scene(controls=short, anchors=(), props={"label": "long"}), manifest())[0]
    few = (control("h", "data.history", bounds=ControlBounds(max_items=1)),)
    assert "at most 1" in sc.check_scene(full_scene(controls=few, anchors=(), data={"count": 1, "history": [
        {"delta": 1}, {"delta": 2}]}), manifest())[0]


def test_the_pin_must_be_the_manifest_the_scene_is_checked_against():
    other = parse_manifest(candidate(version=2)["manifest"])
    assert "the scene pins test.counter@1" in sc.check_scene(full_scene(), other)[0]


def test_check_scene_reports_every_problem_up_to_a_bound():
    many = tuple(control(f"c{i}", f"props.missing{i}") for i in range(30))
    errors = sc.check_scene(full_scene(controls=many, anchors=()), manifest())
    assert len(errors) == sc.MAX_CHECK_ERRORS == 20 and all(len(e) <= 200 for e in errors)


# ------------------------------------------------------------------ introspection

def test_discovery_answers_what_is_editable_with_resolved_semantic_controls():
    s, m = full_scene(), manifest()
    answer = sc.describe_scene(s, m, order=3)
    assert answer["scene_id"] == SCENE_ID and answer["order"] == 3 and answer["title"] == "Ouverture"
    assert answer["section"] == "Intro" and answer["prefab"] == {"id": "test.counter", "version": 1}
    assert answer["problems"] == [] and answer["preview"]["caption"] == "Le chiffre cle"
    assert answer["stage"] == {"mode": "patch_stable_window", "prefab_key": "test.counter@1"}
    assert answer["payload"] == s.budget() and answer["payload"]["limit"] == 16_384
    assert [a["anchor_id"] for a in answer["anchors"]] == ["reveal_count", "beat"]
    by_id = {c["control_id"]: c for c in answer["controls"]}
    assert list(by_id) == ["headline", "accent_color", "density", "start_count", "notes"]  # authored order
    assert by_id["headline"] == {
        "control_id": "headline", "label": "Titre", "group": "content", "meaning": "Texte principal du compteur",
        "path": "props.label", "type": "string", "widget": "text_line", "required": False,
        "bounds": {"max_length": 40}, "default": "Count", "current": "Visiteurs", "is_set": True}
    assert by_id["accent_color"]["widget"] == "color" and by_id["accent_color"]["current"] == "#6ee7ff"  # manifest default
    assert by_id["accent_color"]["is_set"] is False
    assert by_id["density"]["bounds"] == {"choices": ["compact"]} and by_id["density"]["widget"] == "choice"
    assert by_id["start_count"]["required"] is True and by_id["start_count"]["default"] == 10  # curated default wins
    assert by_id["start_count"]["bounds"] == {"min": 0, "max": 100} and by_id["start_count"]["widget"] == "slider"
    assert by_id["start_count"]["current"] == 12
    assert by_id["notes"]["widget"] == "text_area" and by_id["notes"]["bounds"] == {"max_length": 50}
    json.dumps(answer)  # plain JSON all the way down


def test_control_ids_are_stable_across_calls_edits_and_a_storage_round_trip():
    m = manifest()
    first = sc.describe_scene(full_scene(), m, order=0)
    assert sc.describe_scene(full_scene(), m, order=0) == first
    edited = full_scene(props={"label": "Autre", "mode": "compact"}, data={"count": 99}, title="Autre titre")
    ids = lambda a: [(c["control_id"], c["path"], c["widget"], c["bounds"]) for c in a["controls"]]  # noqa: E731
    assert ids(sc.describe_scene(edited, m, order=2)) == ids(first)  # values change, identity does not
    reloaded = StudioScene.from_dict(json.loads(json.dumps(full_scene().to_dict())))
    assert sc.describe_scene(reloaded, m, order=0) == first
    shuffled = full_scene(controls=tuple(reversed(CONTROLS)), anchors=())
    assert [c["control_id"] for c in sc.describe_scene(shuffled, m, order=0)["controls"]] == [
        c.control_id for c in reversed(CONTROLS)]  # order is the author's, ids do not depend on it


def test_a_scene_without_controls_still_describes_itself():
    answer = sc.describe_scene(scene(), manifest(), order=0)
    assert answer["controls"] == [] and answer["anchors"] == [] and answer["problems"] == []
    assert answer["payload"]["bytes"] > 0 and answer["preview"] == {"caption": "", "alt": ""}


def test_an_incompatible_scene_describes_its_problems_and_no_half_resolved_controls():
    answer = sc.describe_scene(full_scene(controls=(control("ghost", "props.nope"),), anchors=()), manifest(), order=0)
    assert answer["controls"] == [] and "props.nope is not declared" in answer["problems"][0]


# ------------------------------------------------------------------ proposition depuis un manifeste

def test_suggested_controls_are_a_deterministic_scalar_starting_point_valid_for_the_manifest():
    m = manifest()
    first = sc.suggest_controls(m)
    assert first == sc.suggest_controls(manifest())
    assert [(c.control_id, c.path, c.group.value) for c in first] == [
        ("label", "props.label", "content"), ("accent", "props.accent", "visual"), ("mode", "props.mode", "visual"),
        ("count", "data.count", "visual"), ("notes", "data.notes", "content"), ("link", "data.link", "content")]
    assert all(c.bounds.is_empty() and c.default is None for c in first)  # bounds stay the manifest's own
    assert sc.check_scene(StudioScene(SCENE_ID, PIN, data={"count": 1}, controls=first), m) == []
    assert not any("history" in c.path for c in first)  # an array is structure, not a quick control


def test_suggested_ids_stay_unique_when_props_and_data_share_a_name():
    raw = candidate(inputs={"props": {"type": "object", "properties": {"title": {"type": "string", "description": "Titre."}}},
                            "data": {"type": "object", "properties": {"title": {"type": "string"},
                                                                       "fontSize": {"type": "integer", "min": 1, "max": 9}}}},
                    sample={"props": {}, "data": {}}, events={})
    suggested = sc.suggest_controls(parse_manifest(raw["manifest"]))
    assert [c.control_id for c in suggested] == ["title", "data_title", "font_size"]
    assert suggested[0].meaning == "Titre." and len({c.control_id for c in suggested}) == 3


def test_suggestions_are_capped():
    props = {f"p{i}": {"type": "string"} for i in range(32)}
    raw = candidate(inputs={"props": {"type": "object", "properties": props},
                            "data": {"type": "object", "properties": {f"d{i}": {"type": "string"} for i in range(5)}}},
                    sample={"props": {}, "data": {}}, events={})
    assert len(sc.suggest_controls(parse_manifest(raw["manifest"]))) == sc.MAX_CONTROLS


# ------------------------------------------------------------------ dans le document de variante

def variant_with(scenes):
    doc = copy.deepcopy(json.loads(open("tests/fixtures/presentation_studio/variant.v3.json", encoding="utf-8").read()))
    doc["scenes"] = scenes
    return doc


def test_rich_scenes_round_trip_through_the_variant_document_and_its_text_form():
    scenes = [full_scene().to_dict(), full_scene().to_dict() | {"scene_id": "pss_0000000000a2"}]
    variant = ps.parse_variant(variant_with(scenes))
    assert variant.scenes[0] == full_scene() and variant.to_document()["scenes"] == scenes
    again = ps.parse_variant(ps.load_document(ps.dump_document(variant.to_document())))
    assert again == variant and variant.to_document()["schema_version"] == ps.VARIANT_SCHEMA_VERSION == 3
    assert ps.SCHEMA_VERSION == 2  # Slice 04 left it at 1; Slice 16 added the variant graph metadata (manifest v2)


def test_an_old_variant_with_bare_pins_is_upgraded_and_a_v1_reader_contract_is_kept():
    v1 = json.loads(open("tests/fixtures/presentation_studio/variant.v1.json", encoding="utf-8").read())
    assert v1["schema_version"] == 1 and set(v1["scenes"][0]) == {"scene_id", "prefab"}
    upgraded = ps.upgrade_document(v1, ps.SCHEMA_VARIANT)
    assert upgraded["schema_version"] == 3 and upgraded["scenes"][0]["controls"] == []
    assert upgraded["scenes"][0]["source_revision"] == 0 and upgraded["scenes"][0]["last_valid_pin"] is None
    assert v1["schema_version"] == 1 and "controls" not in v1["scenes"][0]  # the input is never mutated
    assert set(ps.UPGRADES[ps.SCHEMA_VARIANT]) == {1, 2} and set(ps.UPGRADES[ps.SCHEMA_PRESENTATION]) == {1}
    refused(lambda: ps.upgrade_document({**v1, "schema_version": 4}, ps.SCHEMA_VARIANT),
            C.UNSUPPORTED_SCHEMA_VERSION, "schema_version 4")


def test_a_scene_inside_a_variant_is_refused_with_the_scene_path():
    bad_scene = full_scene().to_dict()
    bad_scene["controls"][0]["path"] = "css.color"
    refused(lambda: ps.parse_variant(variant_with([bad_scene])), contains="path must be props.<name>")
    refused(lambda: ps.parse_variant(variant_with([{**full_scene().to_dict(), "object_id": "obj_1"}])),
            C.RUNTIME_STATE_REFUSED, "object_id")
    refused(lambda: ps.parse_variant(variant_with([full_scene().to_dict()] * 2)), contains="same scene_id twice")


def test_the_shared_checks_module_keeps_its_names_and_the_title_limit_matches_the_prefab_limit():
    from jarvis.domain import presentation_studio_checks as checks
    from jarvis.domain.prefab import MAX_TITLE_CHARS
    assert checks.MAX_TITLE == MAX_TITLE_CHARS == ps.MAX_TITLE
    assert ps.PresentationStudioError is checks.PresentationStudioError and ps.HTTP_STATUS is checks.HTTP_STATUS
    assert ps.SCENE_ID is checks.SCENE_ID and checks.is_scene_id("pss_0123456789ab")
    assert not checks.is_scene_id("pss_0123456789AB") and not checks.is_scene_id(None) and not checks.is_scene_id("pss_0123456789ab\n")
    assert (ps.HTTP_STATUS[C.UNKNOWN_SCENE], ps.HTTP_STATUS[C.SCENE_INCOMPATIBLE],
            ps.HTTP_STATUS[C.PREFAB_UNAVAILABLE]) == (404, 400, 409)

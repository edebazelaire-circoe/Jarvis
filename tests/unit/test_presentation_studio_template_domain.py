"""Domaine pur de la promotion de modeles : roles, espaces reserves, detection, parametrage, requetes et document (Slice 20).

Aucun disque, aucun service. Le comportement bout en bout est dans `test_presentation_studio_template_service.py`.
Contrat : `docs/presentation-studio.md` > *Template and prefab promotion contract*.
"""

from __future__ import annotations

import copy
import json

import pytest

from jarvis.core.presentation_studio_template import _guard_scan
from jarvis.domain.prefab import parse_input_schema, parse_manifest, validate_value
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_art_direction_authoring import generate_fallback_profile
from jarvis.domain.presentation_studio_scene import StudioControl, StudioScene
from jarvis.domain.presentation_studio_template import (
    SCHEMA_TEMPLATE, StudioTemplate, TemplateKind, TemplateScene, parse_instantiate, parse_promote, parse_template, prefab_id_for,
    template_scene_dicts, template_scene_id,
)
from jarvis.domain.presentation_studio_template_sanitize import (
    DA_SECTIONS, LOOK_TYPES, Leaf, SelectionError, build_scene, compose_profile, content_terms, content_values, is_term, leaf_role,
    leaves, normalise, placeholder, sanitize_da_sections, scan_text, scan_value,
)
from tests.fakes.prefabs import candidate

MANIFEST = candidate()["manifest"]
FILES = {k: v for k, v in candidate().items() if k != "manifest"}


def control(control_id, path, group, label="Reglage"):
    return StudioControl(control_id, path, label, group)


CONTROLS = (control("headline", "props.label", "content"), control("accent", "props.accent", "visual"),
            control("density", "props.mode", "motion"), control("count", "data.count", "content"),
            control("history", "data.history", "content"))


def build(*, dimensions=(), parameters=(), props=None, data=None, terms=frozenset(), manifest=None, controls=CONTROLS, anchors=()):
    return build_scene(manifest=manifest or MANIFEST, files=FILES, props=props or {"label": "Visiteurs", "accent": "#ff0000", "mode": "full"},
                       data=data or {"count": 12, "history": [{"delta": 3}]}, controls=controls, anchors=anchors,
                       dimensions=dimensions, parameters=parameters, terms=terms, key="s1", title="Modele", description="", tags=())


# ------------------------------------------------------------------ roles, feuilles, espaces reserves

def test_the_leaves_of_a_manifest_are_its_scalars_and_arrays_in_declaration_order():
    paths = [leaf.path for root in ("props", "data") for leaf in leaves(MANIFEST["inputs"][root], root)]
    assert paths == ["props.label", "props.accent", "props.mode", "data.count", "data.notes", "data.link", "data.history"]


@pytest.mark.parametrize(("path", "group", "role"), [
    ("props.accent", "visual", "look"), ("props.accent", "content", "content"), ("props.mode", None, "look"),
    ("props.label", "visual", "content"), ("data.count", None, "content"), ("data.count", "layout", "look"),
    ("data.history", "motion", "content"), ("data.link", None, "content")])
def test_a_leaf_is_look_only_when_it_is_a_scalar_setting_and_not_content(path, group, role):
    root = path.split(".")[0]
    leaf = next(x for x in leaves(MANIFEST["inputs"][root], root) if x.path == path)
    ctl = None if group is None else control("c", path, group)
    assert leaf_role(leaf, ctl) == role
    assert (leaf.type in LOOK_TYPES) or role == "content"


@pytest.mark.parametrize("node", [
    {"type": "string"}, {"type": "string", "max_length": 3}, {"type": "text", "max_length": 5}, {"type": "number", "min": 5},
    {"type": "number", "min": -9, "max": -3}, {"type": "integer", "min": 2, "max": 9}, {"type": "boolean"}, {"type": "color"},
    {"type": "enum", "values": ["b", "a"]}, {"type": "url"}, {"type": "array", "items": {"type": "string"}},
    {"type": "array", "min_items": 2, "items": {"type": "integer", "min": 1}},
    {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}, "b": {"type": "boolean"}}}])
def test_a_placeholder_is_neutral_and_valid_for_its_node(node):
    value = placeholder(node, "name")
    _, problems = validate_value(parse_input_schema(node), value)
    assert problems == (), (node, value)
    if node["type"] in ("string", "text"):
        assert "name"[:2] in value and len(value) <= node.get("max_length", 2000)


def test_a_term_is_specific_enough_to_be_searched_for():
    assert [is_term(t) for t in ("Visiteurs", "full", "ab12", "Q3 2025", "compact", "   ", "----", "Le chiffre")] == [
        True, False, True, True, True, False, False, True]
    assert normalise("  Le   CHIFFRE\n d'affaires ") == "le chiffre d'affaires"
    assert content_terms([{"a": ["Visiteurs", "no"], "b": 3}, "Visiteurs", None]) == frozenset({"visiteurs"})
    assert len(content_terms([f"valeur numero {n}" for n in range(1000)])) == 400, "bounded"


# ------------------------------------------------------------------ detection

@pytest.mark.parametrize(("text", "code"), [
    ("see pss_0000000000a1 here", "project_identifier"), ("id pst_" + "a" * 32, "project_identifier"),
    ("load presentation-studio.hero", "project_identifier"), ("el user-prefab-0123456789ab", "project_identifier"),
    ("studio-stage-run_1", "project_identifier"), ("C:\\Users\\x\\a.png", "local_path"), ("D:/data/a.png", "local_path"),
    ("open /home/me/a.png now", "local_path"), ("see ~/.jarvis/data", "local_path"), ("file:///etc/passwd", "local_path"),
    ("\\\\server\\share\\a", "local_path"), ("le chiffre d'affaires du trimestre", "project_content")])
def test_project_material_is_found_and_the_message_never_holds_the_value(text, code):
    found = scan_text("source.template", text, frozenset({"le chiffre d'affaires du trimestre"}))
    assert code in {f.code for f in found} and all(f.blocking for f in found if f.code == code)
    assert text not in json.dumps([f.to_dict() for f in found])
    assert all("Users" not in f.message and "chiffre" not in f.message for f in found)


@pytest.mark.parametrize("text", [
    "const mode = 'compact'; el.className = 'count';", '<svg xmlns="http://www.w3.org/2000/svg"></svg>', "a.prefab_id = 'jarvis.window'",
    "var pss = 1; var psx_ = 2;", "https://example.com/a is a url but not a project one", "pst_short"])
def test_ordinary_code_is_not_a_leak(text):
    assert [f for f in scan_text("source.behavior", text, frozenset({"visiteurs"})) if f.blocking] == []


def test_urls_and_large_embedded_assets_are_warnings_only_in_the_source():
    text = '<a href="https://docs.example.org/x">x</a> <img src="data:image/png;base64,' + "A" * 3000 + '">'
    found = scan_text("source.template", text, frozenset(), urls=True)
    assert {(f.code, f.blocking) for f in found} == {("external_url", False), ("embedded_asset", False)}
    assert scan_text("manifest", text, frozenset()) == []


def test_scan_value_walks_keys_and_nested_values_and_is_bounded_in_depth():
    deep = value = {}
    for _ in range(40):
        value["k"] = {}
        value = value["k"]
    assert scan_value("record", deep, frozenset()) == []
    found = scan_value("record", {"a": ["x", {"pss_0000000000a1": "y"}]}, frozenset())
    assert [f.code for f in found] == ["project_identifier"]


# ------------------------------------------------------------------ parametrage d'une scene

def test_the_source_manifest_is_never_modified_and_the_result_is_a_valid_prefab_manifest():
    before = copy.deepcopy(MANIFEST)
    built = build(dimensions=("accent",), parameters=("headline", "count"))
    assert MANIFEST == before
    parsed = parse_manifest({**built.candidate["manifest"], "id": "studio-template.x", "version": 1})
    assert parsed.sample_props["label"] == "[label]" and parsed.sample_props["accent"] == "#ff0000"
    props = built.candidate["manifest"]["inputs"]["props"]["properties"]
    assert props["accent"]["default"] == "#ff0000" and props["label"]["default"] == "[label]" and props["mode"]["default"] == "full"
    assert built.candidate["manifest"]["aliases"] == [] and built.candidate["manifest"]["title"] == "Modele"


def test_chosen_dimensions_and_parameters_are_the_only_controls_kept_and_their_curated_defaults_are_dropped():
    ctl = StudioControl("headline", "props.label", "Titre", "content", default="Mon titre")
    built = build(parameters=("headline",), controls=(ctl, *CONTROLS[1:]))
    assert [c["control_id"] for c in built.controls] == ["headline"] and built.controls[0]["default"] is None
    assert built.roles == {"headline": {"kind": "parameter", "role": "content", "type": "string"}}
    assert built.stripped["controls_dropped"] == 4


def test_anchors_survive_only_with_a_kept_control():
    anchors = ({"anchor_id": "a1", "label": "Un", "control_id": "count"}, {"anchor_id": "a2", "label": "Deux", "control_id": "accent"},
               {"anchor_id": "a3", "label": "Trois", "control_id": None})
    built = build(parameters=("count",), anchors=anchors)
    assert [a["anchor_id"] for a in built.anchors] == ["a1", "a3"] and built.stripped["anchors_dropped"] == 1


def test_content_is_neutralised_in_defaults_samples_and_values_and_nothing_of_it_is_left():
    built = build(parameters=("headline",), data={"count": 99, "notes": "Rapport trimestriel", "history": [{"delta": 41}]})
    text = json.dumps([built.candidate["manifest"], built.props, built.data])
    for secret in ("Visiteurs", "Rapport trimestriel", "41", "99"):
        assert secret not in text, secret
    assert built.data["history"] == [] and built.data["notes"] == "[notes]" and built.stripped["content_values"] >= 3


@pytest.mark.parametrize(("kwargs", "fragment"), [
    ({"dimensions": ("headline",)}, "project content"), ({"dimensions": ("count",)}, "project content"),
    ({"dimensions": ("history",)}, "project content"), ({"dimensions": ("ghost",)}, "not controls of this scene"),
    ({"parameters": ("ghost",)}, "not controls of this scene"), ({"dimensions": ("accent", "accent")}, "twice"),
    ({"dimensions": ("accent",), "parameters": ("accent",)}, "both as dimension and as parameter")])
def test_an_incoherent_selection_is_refused_by_name_without_values(kwargs, fragment):
    with pytest.raises(SelectionError) as caught:
        build(**kwargs)
    assert fragment in str(caught.value) and "Visiteurs" not in str(caught.value)


def test_a_motion_control_over_an_enum_is_a_dimension_and_keeps_the_scene_value():
    built = build(dimensions=("density",), props={"label": "x", "mode": "compact"})
    assert built.candidate["manifest"]["inputs"]["props"]["properties"]["mode"]["default"] == "compact"
    assert built.props["mode"] == "compact"


def test_a_nested_content_leaf_and_a_required_one_without_a_default_still_get_valid_neutral_values():
    manifest = copy.deepcopy(MANIFEST)
    manifest["inputs"]["data"]["properties"]["card"] = {"type": "object", "required": ["name"], "properties": {
        "name": {"type": "string", "max_length": 6}, "stars": {"type": "integer", "min": 1, "max": 5, "default": 3}}}
    manifest["sample"]["data"]["card"] = {"name": "Alice"}
    built = build(manifest=manifest, data={"count": 1, "card": {"name": "Dupont", "stars": 5}})
    assert built.data["card"] == {"name": "[name]", "stars": 3} or built.data["card"]["name"] == "[name]"
    assert "Dupont" not in json.dumps(built.candidate["manifest"]) and "Alice" not in json.dumps(built.candidate["manifest"])


def test_a_source_that_cannot_accept_a_neutral_value_is_a_blocking_finding():
    manifest = copy.deepcopy(MANIFEST)
    manifest["inputs"]["props"]["properties"]["code"] = {"type": "string", "pattern": "[0-9]{4}"}
    manifest["sample"]["props"]["code"] = "1234"
    built = build(manifest=manifest, props={"code": "9876"})
    assert [f.code for f in built.findings if f.blocking] == ["placeholder_unfit"]
    assert "9876" not in json.dumps([f.to_dict() for f in built.findings])


def test_hard_coded_content_in_the_source_is_found_by_the_terms_of_the_project():
    leaky = dict(FILES, template='<h2>Visiteurs du mois</h2><p data-jv-text="data.count"></p>')
    built = build_scene(manifest=MANIFEST, files=leaky, props={}, data={"count": 1}, controls=CONTROLS, anchors=(), dimensions=(),
                        parameters=(), terms=content_terms(["Visiteurs du mois"]), key="s2", title="T", description="", tags=())
    assert [(f.code, f.where) for f in built.findings if f.blocking] == [("project_content", "scene:s2.source.template")]


def test_content_values_lists_only_content_leaves():
    values = content_values(MANIFEST, CONTROLS, {"label": "Visiteurs", "accent": "#ff0000", "mode": "compact"},
                            {"count": 12, "history": [{"delta": 1}]})
    assert values == ["Visiteurs", 12, [{"delta": 1}]] and "compact" not in values


# ------------------------------------------------------------------ direction artistique

def profile_dict():
    document = generate_fallback_profile({"title": "Atelier"}).to_dict()
    document["imagery"]["motifs"] = ["logo maison"]
    document["references"] = [{"kind": "document", "locator": "docs/charte.pdf", "title": "Charte"}]
    return document


def test_art_direction_sections_lose_references_name_provenance_and_motifs_unless_kept():
    sections, counts, findings = sanitize_da_sections(profile_dict(), ["palette", "imagery"], keep_motifs=False, terms=frozenset())
    assert sorted(sections) == ["imagery", "palette"] and sections["imagery"]["motifs"] == [] and findings == []
    assert counts == {"references_dropped": 1, "motifs_dropped": 1, "sections_dropped": 5}
    kept, _, found = sanitize_da_sections(profile_dict(), ["imagery"], keep_motifs=True, terms=frozenset({"logo maison"}))
    assert kept["imagery"]["motifs"] == ["logo maison"] and [f.code for f in found] == ["project_content"]


def test_a_composed_profile_is_complete_and_free_of_the_projects_provenance():
    sections, _, _ = sanitize_da_sections(profile_dict(), list(DA_SECTIONS), keep_motifs=False, terms=frozenset())
    profile = compose_profile(sections, "Charte sobre")
    document = profile.to_dict()
    assert document["name"] == "Charte sobre" and document["references"] == []
    assert document["provenance"]["origin"] == "provided" and document["provenance"]["fallback"] is False
    assert document["palette"] == profile_dict()["palette"]


def test_sections_that_do_not_stand_alone_are_refused_by_the_closed_vocabulary_rules():
    sections, _, _ = sanitize_da_sections(profile_dict(), ["dataviz"], keep_motifs=False, terms=frozenset())
    sections["dataviz"]["series"] = ["#101010", "#111111", "#121212"]
    with pytest.raises(PresentationStudioError) as caught:
        compose_profile(sections, "x")
    assert caught.value.code is C.INVALID_PRESENTATION and "contrast" in caught.value.message


def test_overlaying_on_a_base_keeps_its_name_references_and_other_sections():
    base = profile_dict()
    motion = {"motion": generate_fallback_profile({"title": "Autre"}).to_dict()["motion"]}
    document = compose_profile(motion, None, base).to_dict()
    assert document["name"] == base["name"] and document["references"] == base["references"] and document["palette"] == base["palette"]
    assert document["provenance"]["sections"]["motion"] == "provided"


# ------------------------------------------------------------------ requetes

def body(**extra):
    return {"kind": "presentation", "slug": "rapport", "title": "Rapport", **extra}


GOOD = [{"scene_id": "pss_0000000000a1", "dimensions": ["accent"], "parameters": ["headline"]}]


@pytest.mark.parametrize(("raw", "fragment"), [
    (body(kind="deck"), "kind must be"), (body(slug="Bad Slug"), "slug"), (body(slug="a" * 25), "slug"), (body(title=" x"), "title"),
    (body(description="a\nb"), "description"), (body(tags=["A"]), "tags"), (body(tags=["a", "a"]), "tags"), (body(tags=["a"] * 9), "tags"),
    (body(actor="system"), "actor"), (body(expected_revision=0), "expected_revision"), (body(extra=1), "unknown keys"),
    (body(scenes="x"), "scenes"), (body(scenes=[{"scene_id": "nope", "dimensions": [], "parameters": []}]), "scene id"),
    (body(scenes=[{"scene_id": "pss_0000000000a1", "dimensions": []}]), "missing keys"),
    (body(scenes=[{"scene_id": "pss_0000000000a1", "dimensions": ["A"], "parameters": []}]), "control ids"),
    (body(scenes=GOOD + GOOD), "twice"), (body(art_direction={"sections": []}), "sections"),
    (body(art_direction={"sections": ["nope"]}), "sections"), (body(art_direction={"sections": ["palette", "palette"]}), "sections"),
    (body(art_direction={"sections": ["palette"], "motifs": "maybe"}), "motifs"),
    (body(kind="scene", scenes=GOOD + [{**GOOD[0], "scene_id": "pss_0000000000a2"}]), "exactly one"),
    (body(kind="motion", scenes=GOOD), "no scenes"), (body(kind="motion", art_direction={"sections": ["motion"]}), "implied"),
    (body(kind="art_direction", scenes=GOOD), "no scenes"), ("not an object", "JSON object")])
def test_a_malformed_promotion_request_is_refused_with_a_message_that_names_the_field(raw, fragment):
    with pytest.raises(PresentationStudioError) as caught:
        parse_promote(raw, strict=False)
    assert caught.value.code in (C.INVALID_PRESENTATION, C.RUNTIME_STATE_REFUSED) and fragment in caught.value.message


def test_the_selection_is_optional_for_a_plan_and_mandatory_for_a_promotion():
    assert parse_promote(body(), strict=False).scenes is None
    for raw in (body(), body(kind="art_direction")):
        with pytest.raises(PresentationStudioError) as caught:
            parse_promote(raw, strict=True)
        assert caught.value.code is C.TEMPLATE_SELECTION_REQUIRED
    request = parse_promote(body(scenes=GOOD, tags=["a-b"], description="Une phrase.", art_direction={"sections": ["palette"], "motifs": "keep"}),
                            strict=True)
    assert request.kind is TemplateKind.PRESENTATION and request.scenes[0].parameters == ("headline",)
    assert request.art_direction.keep_motifs is True and request.actor == "user"
    assert parse_promote(body(kind="motion"), strict=True).art_direction is None


def test_an_instantiation_request_is_strict():
    assert parse_instantiate(None).actor == "user"
    assert parse_instantiate({"title": "T", "presentation_id": "pst_" + "0" * 32, "variant_id": "psv_" + "0" * 32,
                              "expected_revision": 3}).expected_revision == 3
    for raw in ({"extra": 1}, {"title": ""}, {"presentation_id": "x"}, {"actor": "system"}, {"expected_revision": "3"}):
        with pytest.raises(PresentationStudioError):
            parse_instantiate(raw)


def test_the_request_guard_refuses_a_hostile_structure_before_any_domain_code():
    deep: dict = {}
    node = deep
    for _ in range(80):
        node["k"] = {}
        node = node["k"]
    for raw in (deep, {"title": "x" * 100_001}, {"n": 2 ** 60}, {"n": float("inf")}):
        with pytest.raises(PresentationStudioError):
            _guard_scan(raw)
    _guard_scan(body())


# ------------------------------------------------------------------ document

def make_template() -> StudioTemplate:
    scene = StudioScene.from_dict({"scene_id": template_scene_id("ptp_000000000001", 0),
                                   "prefab": {"id": "studio-template.x-1", "version": 1}, "props": {"label": "[label]"},
                                   "data": {"count": 0}}, "scene")
    return StudioTemplate("ptp_000000000001", TemplateKind.PRESENTATION, "Rapport", "", ("a",), (TemplateScene("s1", "Intro", scene),),
                          {"sections": {"palette": profile_dict()["palette"]}}, ({"scene_key": "s1", "control_id": "count"},),
                          (), {"stripped": {}}, {"presentation_id": "pst_" + "0" * 32}, "user", "2026-10-09T09:00:00.000000Z")


def test_a_template_round_trips_and_its_summary_has_no_scene_content():
    template = make_template()
    again = parse_template(json.loads(json.dumps(template.to_document())))
    assert again.to_document() == template.to_document() and again.canonical() == template.canonical()
    summary = template.summary()
    assert summary["scene_count"] == 1 and summary["has_art_direction"] is True and "scenes" not in summary


@pytest.mark.parametrize("change", [
    {"manifest": {}}, {"template": "<p>"}, {"schema": "other"}, {"kind": "deck"}, {"template_id": "ptp_x"}, {"created_by": "system"},
    {"scenes": "x"}, {"revision": 0}, {"art_direction": {"sections": {"nope": {}}}}, {"art_direction": {"sections": {}}}])
def test_a_document_with_an_unknown_key_or_a_wrong_field_is_refused(change):
    document = make_template().to_document()
    document.update(change)
    with pytest.raises(PresentationStudioError):
        parse_template(document)


def test_a_newer_schema_is_refused_with_its_own_code():
    document = make_template().to_document()
    document["schema_version"] = 2
    with pytest.raises(PresentationStudioError) as caught:
        parse_template(document)
    assert caught.value.code is C.UNSUPPORTED_SCHEMA_VERSION and document["schema"] == SCHEMA_TEMPLATE


def test_instantiated_scene_dicts_get_new_ids_and_no_reload_state():
    template = make_template()
    ids = iter(f"pss_{n:012x}" for n in range(1, 9))
    first = template_scene_dicts(template, lambda: next(ids))
    assert first[0]["scene_id"] == "pss_000000000001" and "source_revision" not in first[0] and "last_valid_pin" not in first[0]
    assert StudioScene.from_dict(first[0], "scene").prefab.prefab_id == "studio-template.x-1"
    assert template_scene_id("ptp_000000000001", 0) != template_scene_id("ptp_000000000001", 1)
    assert prefab_id_for("a", None) == "studio-template.a" and prefab_id_for("a", 2) == "studio-template.a-2"


def test_leaf_is_a_plain_value_object():
    assert Leaf("props.a", {"type": "string"}).root == "props"

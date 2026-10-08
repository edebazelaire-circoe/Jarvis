"""Contrat du domaine des Presentations (jarvis-interactive-presentation-studio, Slice 02).

Aller-retour, entrées mal formées, bornes, exclusion de l'état d'exécution,
versionnage (refus d'une version future, montée d'une ancienne), cohérence
entre la Presentation et ses variantes. Contrat : `docs/presentation-studio.md`
› *Presentation contract*.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from jarvis.domain import presentation_studio as ps
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "presentation_studio"
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def refused(action, code: C | None = None, contains: str = "") -> PresentationStudioError:
    with pytest.raises(PresentationStudioError) as caught:
        action()
    if code is not None:
        assert caught.value.code is code, caught.value
    assert contains in caught.value.message
    return caught.value


def view_documents() -> dict:
    return {"presentation": fixture("presentation.v1.json"),
            "variants": [fixture("variant.parent.v1.json"), fixture("variant.v1.json")]}


# ------------------------------------------------------------------ aller-retour

def test_fixture_documents_round_trip_byte_for_byte_semantically():
    presentation = ps.parse_presentation(fixture("presentation.v2.json"))
    variant = ps.parse_variant(fixture("variant.v2.json"))
    assert presentation.to_document() == fixture("presentation.v2.json")
    assert variant.to_document() == fixture("variant.v2.json")
    # a Slice 02 file (v1, bare pins) is read through the upgrade step and rewritten as v2, nothing reinterpreted
    old = ps.parse_variant(fixture("variant.v1.json"))
    # Slice 16: a Slice 02 manifest (v1, bare index entries) is read through its own step: defaults, nothing reinterpreted
    old_manifest = ps.parse_presentation(fixture("presentation.v1.json"))
    assert [e.variant_number for e in old_manifest.variants] == [1, 2] and old_manifest.archived == ()
    assert {e.created_by for e in old_manifest.variants} == {"system"} and old_manifest.variant_counter == 2
    assert old.to_document() == fixture("variant.v2.json") and old == variant
    assert [s.prefab for s in old.scenes] == [s.prefab for s in variant.scenes]
    assert variant.scenes[0].prefab.version == 2 and variant.scenes[1].prefab.prefab_id == "jarvis.window"
    assert [r.locator for r in presentation.resources] == ["https://example.org/rapport", "doc:drive-file-1"]


def test_a_whole_view_validates_and_serialises_through_text():
    view = ps.validate_documents(view_documents())
    assert view.active_variant().title == "Version sobre"
    again = ps.validate_documents({"presentation": ps.load_document(ps.dump_document(view.presentation.to_document())),
                                   "variants": [ps.load_document(ps.dump_document(v.to_document()))
                                                for v in view.variants]})
    assert again == view


def test_a_new_presentation_has_one_empty_active_variant_numbered_one():
    view = ps.new_presentation("Atelier", NOW)
    p, v = view.presentation, view.variants[0]
    assert (p.revision, p.variant_counter, len(view.variants), v.variant_number) == (1, 1, 1, 1)
    assert p.active_variant_id == v.variant_id and v.scenes == () and v.parent_variant_id is None
    assert v.art_direction_id is None and v.score_id is None and p.resources == ()
    assert p.created_at == "2026-10-07T12:00:00.000000Z" and ps.is_presentation_id(p.presentation_id)
    assert ps.is_variant_id(v.variant_id) and p.presentation_id != ps.new_presentation("x", NOW).presentation.presentation_id


def test_naive_timestamps_are_refused():
    refused(lambda: ps.stamp(datetime(2026, 10, 7)), C.INVALID_PRESENTATION, "timezone-aware")


# ------------------------------------------------------------------ entrées mal formées

def mutate(document: dict, path: str, value) -> dict:
    result = copy.deepcopy(document)
    target = result
    *head, last = path.split(".")
    for part in head:
        target = target[int(part)] if part.isdigit() else target[part]
    if value is KeyError:
        del target[last]
    elif last.isdigit():
        target[int(last)] = value
    else:
        target[last] = value
    return result


PRESENTATION_BAD = [
    ("title", "", "non-empty"),
    ("title", "  spaced ", "surrounding spaces"),
    ("title", "a\nb", "single printable line"),
    ("title", "x" * 81, "exceeds 80"),
    ("title", 12, "must be a string"),
    ("presentation_id", "pst_xyz", "not a valid id"),
    ("presentation_id", "../../etc", "not a valid id"),
    ("active_variant_id", "psv_00000000000000000000000000000009", "not a live variant"),
    ("variant_counter", 1, "below an indexed"),
    ("variant_counter", True, "integer"),
    ("variant_counter", 10_001, "integer"),
    ("revision", 0, "integer"),
    ("revision", 1.5, "integer"),
    ("created_at", "2026-10-07", "UTC timestamp"),
    ("created_at", "2026-13-45T00:00:00.000000Z", "not a real date"),
    ("variants", {}, "must be lists"),
    ("variants.1.variant_number", 1, "unique"),
    ("variants.0.variant_id", "psv_00000000000000000000000000000002", "unique"),
    ("resources.0.kind", "folder", "not a resource kind"),
    ("resources.1", {"kind": "web_page", "locator": "https://example.org/rapport"}, "twice"),
    ("resources.0.locator", "javascript:alert(1)", "schéma"),
    ("resources.0.locator", "<script>", "balisage"),
    ("resources.0.locator", "x" * 301, "exceeds"),
    ("resources.0.descriptor", {"series": [1]}, "unknown keys descriptor"),
]


@pytest.mark.parametrize(("path", "value", "message"), PRESENTATION_BAD)
def test_a_malformed_presentation_is_refused_with_a_reason(path, value, message):
    refused(lambda: ps.parse_presentation(mutate(fixture("presentation.v1.json"), path, value)),
            C.INVALID_PRESENTATION, message)


VARIANT_BAD = [
    ("variant_id", "psv_1", "not a valid id"),
    ("variant_number", 0, "integer"),
    ("parent_variant_id", "psv_00000000000000000000000000000002", "own parent"),
    ("parent_variant_id", "pst_00000000000000000000000000000001", "not a valid id"),
    ("scenes.0.scene_id", "pss_xyz", "not a valid id"),
    ("scenes.1.scene_id", "pss_000000000001", "same scene_id twice"),
    ("scenes.0.prefab", {"id": "Bad Id", "version": 1}, "not a valid prefab id"),
    ("scenes.0.prefab", {"id": "jarvis.window", "version": 0}, "1..9999"),
    ("scenes.0.prefab", {"id": "jarvis.window", "version": 1, "props": {}}, "exactly {id, version}"),
    ("scenes.0.prefab", {"id": "jarvis.window", "version": "1"}, "1..9999"),
    ("scenes.0.manifest", {"title": "copie du prefab"}, "unknown keys manifest"),
    ("art_direction_id", "psr_000000000001", "not a valid id"),
    ("score_id", "psd_000000000001", "not a valid id"),
    ("scenes", "none", "must be a list"),
]


@pytest.mark.parametrize(("path", "value", "message"), VARIANT_BAD)
def test_a_malformed_variant_is_refused_with_a_reason(path, value, message):
    refused(lambda: ps.parse_variant(mutate(fixture("variant.v1.json"), path, value)), C.INVALID_PRESENTATION, message)


@pytest.mark.parametrize("key", ["revision", "scenes", "presentation_id", "parent_variant_id"])
def test_a_missing_key_is_refused(key):
    refused(lambda: ps.parse_variant(mutate(fixture("variant.v1.json"), key, KeyError)), C.INVALID_PRESENTATION,
            "missing keys")


def test_a_missing_schema_marker_is_refused():
    refused(lambda: ps.parse_variant(mutate(fixture("variant.v1.json"), "schema", KeyError)), C.INVALID_PRESENTATION,
            "schema must be")
    refused(lambda: ps.parse_variant(mutate(fixture("variant.v1.json"), "schema_version", KeyError)),
            C.INVALID_PRESENTATION, "positive integer")


def test_unknown_keys_are_refused_not_ignored():
    for document, parse in ((fixture("presentation.v1.json"), ps.parse_presentation),
                            (fixture("variant.v1.json"), ps.parse_variant)):
        refused(lambda: parse({**document, "notes": "extra"}), C.INVALID_PRESENTATION, "unknown keys notes")


def test_non_objects_and_wrong_schema_are_refused():
    refused(lambda: ps.parse_presentation([]), C.INVALID_PRESENTATION, "JSON object")
    refused(lambda: ps.parse_presentation(fixture("variant.v1.json")), C.INVALID_PRESENTATION, "schema must be")
    refused(lambda: ps.parse_variant(mutate(fixture("variant.v1.json"), "schema_version", "1")), C.INVALID_PRESENTATION,
            "positive integer")
    refused(lambda: ps.parse_variant(mutate(fixture("variant.v1.json"), "schema_version", 0)), C.INVALID_PRESENTATION,
            "positive integer")


def test_text_loading_is_strict(tmp_path):
    refused(lambda: ps.load_document((FIXTURES / "malformed.json").read_text(encoding="utf-8")),
            C.INVALID_PRESENTATION, "not valid JSON")
    refused(lambda: ps.load_document('{"a": 1, "a": 2}'), C.INVALID_PRESENTATION, "duplicate JSON key")
    refused(lambda: ps.load_document('{"a": NaN}'), C.INVALID_PRESENTATION, "nonfinite")
    refused(lambda: ps.load_document("[" * 100_000), C.INVALID_PRESENTATION, "not valid JSON")


# ------------------------------------------------------------------ bornes

def test_collection_and_size_bounds():
    scenes = [{"scene_id": f"pss_{i:012x}", "prefab": {"id": "jarvis.window", "version": 1}}
              for i in range(ps.MAX_SCENES + 1)]
    refused(lambda: ps.parse_variant({**fixture("variant.v1.json"), "scenes": scenes}), C.INVALID_PRESENTATION,
            f"exceed {ps.MAX_SCENES}")
    assert len(ps.parse_variant({**fixture("variant.v1.json"), "scenes": scenes[:ps.MAX_SCENES]}).scenes) == 64
    resources = [{"kind": "note", "locator": f"note:{i}"} for i in range(ps.MAX_RESOURCES + 1)]
    refused(lambda: ps.parse_presentation({**fixture("presentation.v1.json"), "resources": resources}),
            C.INVALID_PRESENTATION, f"exceed {ps.MAX_RESOURCES}")
    refused(lambda: ps.load_document(" " * (ps.MAX_DOCUMENT_BYTES + 1)), C.INVALID_PRESENTATION, "exceeds")
    refused(lambda: ps.dump_document({"pad": "x" * ps.MAX_DOCUMENT_BYTES}), C.LIMIT_REACHED, "exceed")
    index = [{"variant_id": f"psv_{i:032x}", "variant_number": i + 1} for i in range(ps.MAX_VARIANTS + 1)]
    refused(lambda: ps.parse_presentation({**fixture("presentation.v1.json"), "variants": index,
                                           "active_variant_id": index[0]["variant_id"], "variant_counter": 65}),
            C.INVALID_PRESENTATION, f"1..{ps.MAX_VARIANTS} variants")


# ------------------------------------------------------------------ état d'exécution

RUNTIME_PAYLOADS = [
    ("object_id", "obj_1"), ("window_id", "w1"), ("stage_object_id", "o"), ("element", "#frame"), ("dom", "<div>"),
    ("iframe", {}), ("handle", 3), ("playback", {"state": "running"}), ("position", 4), ("score_position", 3),
    ("reveal_progress", 0.5), ("detours", []), ("auxiliary_resources", []), ("undo_stack", []), ("session_id", "s"),
]


@pytest.mark.parametrize(("key", "value"), RUNTIME_PAYLOADS)
def test_runtime_state_is_refused_in_every_document_with_its_own_code(key, value):
    refused(lambda: ps.parse_presentation({**fixture("presentation.v1.json"), key: value}), C.RUNTIME_STATE_REFUSED, key)
    refused(lambda: ps.parse_variant({**fixture("variant.v1.json"), key: value}), C.RUNTIME_STATE_REFUSED, key)
    scene = mutate(fixture("variant.v1.json"), "scenes.0", {**fixture("variant.v1.json")["scenes"][0], key: value})
    refused(lambda: ps.parse_variant(scene), C.RUNTIME_STATE_REFUSED, key)


def test_runtime_state_is_refused_in_request_bodies_too():
    refused(lambda: ps.parse_variant_update({"expected_revision": 1, "title": "t", "scenes": [], "art_direction_id": None,
                                             "score_id": None, "playback": {}}), C.RUNTIME_STATE_REFUSED, "playback")
    refused(lambda: ps.parse_presentation_update({"expected_revision": 1, "title": "t", "resources": [],
                                                  "active_variant_id": "psv_" + "0" * 32, "object_id": "x"}),
            C.RUNTIME_STATE_REFUSED, "object_id")


def test_a_scene_object_id_cannot_be_stored_as_a_resource():
    refused(lambda: ps.resource_from_dict({"kind": "scene_object", "locator": "obj-1"}), C.RUNTIME_STATE_REFUSED,
            "runtime handle")
    refused(lambda: ps.resource_from_dict({"kind": "note", "locator": "scene:obj-1"}), C.RUNTIME_STATE_REFUSED,
            "runtime handle")


def test_a_resource_is_a_reference_never_a_payload():
    refused(lambda: ps.resource_from_dict({"kind": "chart_descriptor", "locator": "chart:q3",
                                           "descriptor": {"series": [1, 2]}}), C.INVALID_PRESENTATION, "descriptor")
    assert ps.resource_to_dict(ps.resource_from_dict({"kind": "dataset", "locator": "dataset:sales"})) == {
        "kind": "dataset", "locator": "dataset:sales", "title": ""}


def test_the_domain_stores_no_prefab_definition_fields():
    keys = set(fixture("variant.v2.json")["scenes"][0]) | set(fixture("variant.v2.json")["scenes"][0]["prefab"])
    assert keys == {"scene_id", "prefab", "id", "version", "title", "section", "props", "data", "controls", "anchors",
                    "preview"}  # instance VALUES and curated controls, never a definition
    for forbidden in ("manifest", "template", "style", "behavior", "html", "css", "js", "inputs", "events"):
        refused(lambda: ps.parse_variant(mutate(fixture("variant.v2.json"), "scenes.0." + forbidden, "x")),
                C.INVALID_PRESENTATION, "unknown keys")


# ------------------------------------------------------------------ versionnage

def test_a_newer_schema_version_is_refused_not_read_best_effort():
    error = refused(lambda: ps.parse_presentation(fixture("presentation.future.json")),
                    C.UNSUPPORTED_SCHEMA_VERSION, "schema_version 3")
    assert "left untouched" in error.message and error.status == 409


def test_an_older_version_goes_through_the_upgrade_chain():
    def v1_to_v2(document: dict) -> dict:
        document = dict(document)
        document["title"] = document.pop("name")
        return document

    old = {**fixture("presentation.v1.json"), "name": "Ancien"}
    del old["title"]
    upgraded = ps.upgrade_document(old, ps.SCHEMA_PRESENTATION, current=2,
                                   upgrades={ps.SCHEMA_PRESENTATION: {1: v1_to_v2}})
    assert upgraded["title"] == "Ancien" and upgraded["schema_version"] == 2 and "name" not in upgraded
    assert old["schema_version"] == 1 and "name" in old  # the input is never mutated


def test_a_missing_upgrade_step_is_corruption_not_a_guess():
    refused(lambda: ps.upgrade_document(fixture("presentation.v1.json"), ps.SCHEMA_PRESENTATION, current=3,
                                        upgrades={ps.SCHEMA_PRESENTATION: {}}), C.CORRUPT_DOCUMENT, "no upgrade step")


def test_current_version_is_two_and_every_schema_has_an_upgrade_table():
    assert ps.SCHEMA_VERSION == 2 and set(ps.UPGRADES) == {ps.SCHEMA_PRESENTATION, ps.SCHEMA_VARIANT, ps.SCHEMA_SCORE,
                                                    ps.SCHEMA_ART_DIRECTION}


# ------------------------------------------------------------------ cohérence

def test_consistency_between_the_index_and_the_variants():
    docs = view_documents()
    refused(lambda: ps.validate_documents({**docs, "variants": docs["variants"][:1]}), C.INVALID_PRESENTATION, "differ")
    refused(lambda: ps.validate_documents({**docs, "variants": docs["variants"] + docs["variants"][:1]}),
            C.INVALID_PRESENTATION, "twice")
    other = mutate(docs["variants"][1], "presentation_id", "pst_" + "9" * 32)
    refused(lambda: ps.validate_documents({**docs, "variants": [docs["variants"][0], other]}), C.INVALID_PRESENTATION,
            "another presentation")
    renumbered = mutate(docs["variants"][1], "variant_number", 7)
    refused(lambda: ps.validate_documents({**docs, "variants": [docs["variants"][0], renumbered]}), C.INVALID_PRESENTATION,
            "number differs")
    orphan = mutate(docs["variants"][1], "parent_variant_id", "psv_" + "8" * 32)
    refused(lambda: ps.validate_documents({**docs, "variants": [docs["variants"][0], orphan]}), C.INVALID_PRESENTATION,
            "parent outside")
    refused(lambda: ps.validate_documents({"presentation": docs["presentation"]}), C.INVALID_PRESENTATION, "missing keys")


# ------------------------------------------------------------------ corps de mise à jour

def test_update_bodies_are_exact_and_typed():
    update = ps.parse_variant_update({"expected_revision": 4, "title": "t", "art_direction_id": None, "score_id": None,
                                      "scenes": fixture("variant.v1.json")["scenes"]})
    assert update.expected_revision == 4 and [s.scene_id for s in update.scenes] == ["pss_000000000001", "pss_000000000002"]
    refused(lambda: ps.parse_variant_update({"expected_revision": 0, "title": "t", "scenes": [],
                                             "art_direction_id": None, "score_id": None}), C.INVALID_PRESENTATION, "integer")
    refused(lambda: ps.parse_variant_update({"expected_revision": 1, "title": "t", "scenes": []}), C.INVALID_PRESENTATION,
            "missing keys")
    refused(lambda: ps.parse_create({"title": "ok", "extra": 1}), C.INVALID_PRESENTATION, "unknown keys")
    refused(lambda: ps.parse_create({"title": ""}), C.INVALID_PRESENTATION, "non-empty")
    assert ps.parse_create({"title": "Atelier"}) == "Atelier"


def test_every_error_code_has_a_status_and_the_message_is_bounded():
    assert set(ps.HTTP_STATUS) == set(C)
    error = PresentationStudioError(C.STORAGE_IO, "x" * 1000)
    assert len(error.message) <= ps.MAX_ERROR_CHARS and error.status == 500


# ------------------------------------------------------------------ rework (QA-1 P1, P3, P4)

def test_a_lone_surrogate_is_a_400_style_refusal_not_a_crash():
    refused(lambda: ps.resource_from_dict({"kind": "note", "locator": "note:ok", "title": "a\ud800b"}),
            C.INVALID_PRESENTATION, "cannot be stored")
    refused(lambda: ps.resource_from_dict({"kind": "note", "locator": "note:a\ud800b"}),
            C.INVALID_PRESENTATION, "printable")
    refused(lambda: ps.dump_document({"x": "a\ud800b"}), C.INVALID_PRESENTATION, "cannot be stored")


def test_parent_cycles_are_refused_not_only_self_parent():
    docs = view_documents()
    first, second = docs["variants"]
    cyclic_first = {**first, "parent_variant_id": second["variant_id"]}  # second's parent is first: a -> b -> a
    refused(lambda: ps.validate_documents({**docs, "variants": [cyclic_first, second]}), C.INVALID_PRESENTATION,
            "parent cycle")
    third_id = "psv_" + "3" * 32
    third = {**first, "variant_id": third_id, "variant_number": 3, "parent_variant_id": second["variant_id"]}
    presentation = {**docs["presentation"], "variant_counter": 3,
                    "variants": [*docs["presentation"]["variants"], {"variant_id": third_id, "variant_number": 3}]}
    cyclic_first = {**first, "parent_variant_id": third_id}  # first -> third -> second -> first
    refused(lambda: ps.validate_documents({"presentation": presentation, "variants": [cyclic_first, second, third]}),
            C.INVALID_PRESENTATION, "parent cycle")
    assert ps.validate_documents({"presentation": presentation, "variants": [first, second, third]})  # a chain is fine


def test_timestamps_accept_ascii_digits_only():
    refused(lambda: ps.parse_presentation(mutate(fixture("presentation.v1.json"), "created_at",
                                                 "٢٠٢٦-10-07T08:00:00.000000Z")), C.INVALID_PRESENTATION, "UTC timestamp")


# ------------------------------------------------------------------ Slice 04 : hygiene des localisateurs (report QA-1 de la Slice 02, P5)

@pytest.mark.parametrize("locator", ["doc:a\x00b", "doc:a\nb", "doc:a\tb", " doc:a", "doc:a ", "doc:a\x7f",
                                     "file:///C:\\Windows\\x", "doc:..\\secret", "https://h/a/../b", "file:///a/../b",
                                     "doc:%2e%2e/x", "note:a/%2E%2E/b", "dataset:..", "https://h/?x=/../y"])
def test_a_locator_with_control_characters_backslashes_or_dot_dot_segments_is_refused(locator):
    refused(lambda: ps.resource_from_dict({"kind": "document", "locator": locator}), C.INVALID_PRESENTATION, "locator")


@pytest.mark.parametrize("locator", ["scene:abc", "SCENE:abc", "scene%3Aabc", "scene%3aobj_1", "Scene%3A1"])
def test_a_scene_locator_is_a_runtime_handle_even_when_percent_encoded(locator):
    refused(lambda: ps.resource_from_dict({"kind": "document", "locator": locator}), C.RUNTIME_STATE_REFUSED,
            "runtime handle")


@pytest.mark.parametrize("locator", ["https://example.org/a.b/c..d", "doc:drive-file-1", "dataset:sales.2026",
                                     "https://example.org/v1.0/..x", "chart:q3"])
def test_ordinary_locators_still_pass_the_hygiene_gate(locator):
    assert ps.resource_from_dict({"kind": "web_page", "locator": locator}).locator == locator


# ------------------------------------------------------------------ Slice 04 rework : hygiene a point fixe, Unicode, UNC, file://

@pytest.mark.parametrize("locator", [
    "scene%253Aabc", "doc:%252e%252e/etc", "doc:%252E%252E%252Fx", "note:x%00y", "note:x%0ay",
    "note:x%0d%0ay", "note:x%2500y", "doc:a%e2%80%8bb", "doc:a%e2%80%aeb", "doc:" + chr(0x200b) + "x",
    "doc:a" + chr(0x202e) + "b", "doc:a" + chr(0x2066) + "b", "doc:a" + chr(0xfeff) + "b", "doc:a" + chr(0x00a0) + "b",
    "file:///etc/passwd", "file://host/share/x", "FILE://x", "file:%2f%2fhost/x", "//host/share/x", "%2f%2fhost/share",
])
def test_locator_hygiene_decodes_to_a_fixpoint_and_refuses_invisible_unc_and_file_forms(locator):
    with pytest.raises(PresentationStudioError) as caught:
        ps.resource_from_dict({"kind": "document", "locator": locator})
    assert caught.value.code in (C.INVALID_PRESENTATION, C.RUNTIME_STATE_REFUSED), caught.value


@pytest.mark.parametrize("locator", [
    chr(0x200b) + "scene:abc", "scene" + chr(0xff1a) + "abc", chr(0x0455) + "cene:abc", chr(0xff53) + "cene:abc",
    "SCENE%253Aabc", "scene%253a1"])
def test_lookalike_and_multiply_encoded_scene_locators_are_not_stored(locator):
    with pytest.raises(PresentationStudioError) as caught:
        ps.resource_from_dict({"kind": "note", "locator": locator})
    assert caught.value.code in (C.INVALID_PRESENTATION, C.RUNTIME_STATE_REFUSED), caught.value
    if locator.startswith(("SCENE%", "scene%")) or "scene" + chr(0xff1a) in locator or locator.startswith(chr(0xff53)):
        assert caught.value.code is C.RUNTIME_STATE_REFUSED  # folded to a scene: handle


@pytest.mark.parametrize("locator", [
    "https://example.org/a%20b?q=100%", "https://example.org/a%20b/c%2Fd", "https://example.org/caf%C3%A9",
    "doc:drive-file-1", "note:notes/2026 plan", "https://example.org/a%E0%A4%A", "https://x.org/100%25",
    "dataset:sales.2026", "C:/Users/me/doc.pdf", "chart:q3", "https://example.org/v1.0/..x"])
def test_ordinary_locators_with_a_normal_percent_escape_still_pass(locator):
    assert ps.resource_from_dict({"kind": "document", "locator": locator}).locator == locator


def test_a_locator_that_never_stops_decoding_is_refused():
    from urllib.parse import quote

    text = "doc:a b"
    for _ in range(7):
        text = quote(text, safe="")
    refused(lambda: ps.resource_from_dict({"kind": "document", "locator": text}), C.INVALID_PRESENTATION,
            "percent-encoded more than")
    once = quote("doc:a b", safe=":")
    assert ps.resource_from_dict({"kind": "document", "locator": once}).locator == once

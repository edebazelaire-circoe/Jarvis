"""Profil de direction artistique (jarvis-interactive-presentation-studio, Slice 09) : schéma, provenance, contraste en
chiffres, vocabulaires clos, chaînes hostiles dans chaque champ, mapping du thème, `require_art_direction`.

Pur, sans disque. Contrat : `docs/presentation-studio.md` › *Art direction contract*.
"""

from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path
import random
import re
from types import SimpleNamespace

import pytest

from jarvis.domain import presentation_studio_art_direction as ad
from jarvis.domain.prefab import canonical_json
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from tests.fakes import presentation_studio_art_direction as fx

ROOT = Path(__file__).resolve().parents[2]


def refused(raw, code: C = C.INVALID_PRESENTATION) -> PresentationStudioError:
    with pytest.raises(PresentationStudioError) as caught:
        ad.parse_profile(raw)
    assert caught.value.code is code, caught.value
    return caught.value


def ok(raw) -> ad.ArtDirectionProfile:
    return ad.parse_profile(raw)


# ------------------------------------------------------------------ schéma, aller-retour, canonique


def test_a_profile_round_trips_through_json_to_the_same_canonical_text():
    for doc in (fx.base_dict(), fx.full_dict()):
        profile = ok(doc)
        wire = json.loads(json.dumps(profile.to_dict()))
        again = ok(wire)
        assert again.canonical() == profile.canonical() == canonical_json(doc if doc is not None else wire)


def test_key_order_does_not_change_the_canonical_identity():
    doc = fx.full_dict()
    shuffled = json.loads(json.dumps(doc, sort_keys=True))
    keys = list(shuffled["palette"])
    random.Random(4).shuffle(keys)
    shuffled["palette"] = {k: shuffled["palette"][k] for k in keys}
    assert ok(doc).canonical() == ok(shuffled).canonical()


def test_the_stored_document_is_strict_versioned_and_round_trips():
    raw = json.loads(fx.FIXTURE.read_text(encoding="utf-8"))
    assert raw["schema"] == "jarvis.presentation_studio.art_direction" and raw["schema_version"] == 1
    art = ad.parse_art_direction(raw)
    assert canonical_json(art.to_document()) == canonical_json(raw) == art.canonical()
    assert re.fullmatch(r"psd_[0-9a-f]{12}", art.art_direction_id)


def test_a_newer_schema_version_is_refused_untouched_and_an_older_shape_is_not_guessed():
    raw = fx.document()
    with pytest.raises(PresentationStudioError) as newer:
        ad.parse_art_direction({**raw, "schema_version": 2})
    assert newer.value.code is C.UNSUPPORTED_SCHEMA_VERSION
    for bad in (0, -1, True, "1", None, 1.0):
        with pytest.raises(PresentationStudioError):
            ad.parse_art_direction({**raw, "schema_version": bad})
    with pytest.raises(PresentationStudioError):
        ad.parse_art_direction({**raw, "schema": "jarvis.presentation_studio.score"})


def test_every_nested_object_refuses_an_unknown_key_and_a_missing_key():
    doc = fx.full_dict()
    for path in fx.objects(doc):
        target = doc if not path else _at(doc, path)
        refused(fx.set_path(doc, (path + ".spare") if path else "spare", 1))
        if path == "provenance.sections":
            continue  # a map: any subset of the sections is legal
        for key in list(target):
            if path.startswith("references.") and key == "title":
                continue  # a reference's title is optional by the Slice 02 contract
            smaller = copy.deepcopy(doc)
            _delete(smaller, f"{path}.{key}" if path else key)
            refused(smaller)


def _at(doc, path):
    node = doc
    for part in path.split("."):
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def _delete(doc, path):
    parts = path.split(".")
    node = doc
    for part in parts[:-1]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    if isinstance(node, list):
        del node[int(parts[-1])]
    else:
        del node[parts[-1]]


def test_a_runtime_state_key_gets_its_own_code_and_is_never_stored():
    refused({**fx.base_dict(), "position": 3}, C.RUNTIME_STATE_REFUSED)
    refused(fx.set_path(fx.base_dict(), "palette.selected", True), C.RUNTIME_STATE_REFUSED)


def test_the_document_names_its_ids_and_stamps_strictly():
    raw = fx.document()
    for key, value in (("art_direction_id", "psr_000000000001"), ("art_direction_id", "psd_XYZ"), ("variant_id", "x"),
                       ("presentation_id", "psv_" + "a" * 32), ("revision", 0), ("revision", True), ("created_at", "yesterday"),
                       ("updated_at", "2026-13-40T00:00:00.000000Z"), ("spare", 1)):
        with pytest.raises(PresentationStudioError):
            ad.parse_art_direction({**raw, key: value})
    with pytest.raises(PresentationStudioError):
        ad.parse_art_direction({k: v for k, v in raw.items() if k != "profile"})


def test_create_and_update_bodies_are_exact():
    profile = fx.base_dict()
    assert ad.parse_art_direction_create({"expected_variant_revision": 3, "profile": profile}).expected_variant_revision == 3
    assert ad.parse_art_direction_update({"expected_revision": 2, "profile": profile}).expected_revision == 2
    for body in ({"expected_variant_revision": 0, "profile": profile}, {"expected_variant_revision": True, "profile": profile},
                 {"expected_variant_revision": 1}, {"profile": profile}, {"expected_variant_revision": 1, "profile": profile, "x": 1},
                 [], None):
        with pytest.raises(PresentationStudioError):
            ad.parse_art_direction_create(body)
    for body in ({"expected_revision": "1", "profile": profile}, {"expected_revision": 1}, {"expected_revision": 1, "profile": []}):
        with pytest.raises(PresentationStudioError):
            ad.parse_art_direction_update(body)


# ------------------------------------------------------------------ provenance


def test_provenance_is_provided_inferred_or_generated_per_profile_and_per_section():
    for origin in ad.Origin:
        doc = fx.set_path(fx.set_path(fx.base_dict(), "provenance.fallback", False), "provenance.origin", origin.value)
        profile = ok(doc)
        assert profile.provenance.origin is origin
        assert all(profile.provenance.origin_of(section) is origin for section in ad.Section)
    mixed = ok(fx.full_dict())
    assert mixed.provenance.origin_of(ad.Section.PALETTE) is ad.Origin.PROVIDED
    assert mixed.provenance.origin_of(ad.Section.MOTION) is ad.Origin.GENERATED
    assert mixed.provenance.origin_of(ad.Section.SHAPES) is ad.Origin.INFERRED  # not listed: the profile's own origin


def test_provenance_refuses_an_unknown_origin_a_foreign_section_and_a_false_fallback():
    base = fx.base_dict()
    for origin in ("invented", "PROVIDED", "", None, 1, ["provided"]):
        refused(fx.set_path(base, "provenance.origin", origin))
    for key in ("palette ", "colors", "references", "", "PALETTE"):
        refused(fx.set_path(base, "provenance.sections", {key: "provided"}))
    refused(fx.set_path(base, "provenance.sections", {"palette": "guessed"}))
    refused(fx.set_path(base, "provenance.sections", ["palette"]))
    inferred = fx.set_path(base, "provenance.origin", "inferred")
    refused(inferred)  # fallback is still true: a fallback profile is generated by definition
    refused(fx.set_path(fx.set_path(inferred, "provenance.fallback", True), "provenance.sections", {}))
    refused(fx.set_path(base, "provenance.fallback", "yes"))
    refused(fx.set_path(base, "provenance.fallback", 1))


def test_confidence_is_a_finite_number_between_zero_and_one_and_never_a_bool():
    base = fx.base_dict()
    for good in (0, 1, 0.0, 1.0, 0.5, 0.123456):
        assert 0.0 <= ok(fx.set_path(base, "provenance.confidence", good)).provenance.confidence <= 1.0
    assert ok(fx.set_path(base, "provenance.confidence", 0.123456)).provenance.confidence == 0.123  # canonical: 3 decimals
    assert isinstance(ok(fx.set_path(base, "provenance.confidence", 1)).provenance.confidence, float)
    for bad in (-0.01, 1.01, float("nan"), float("inf"), True, False, "0.5", None, [], {}):
        refused(fx.set_path(base, "provenance.confidence", bad))
    one, one_float = ok(fx.set_path(base, "provenance.confidence", 1)), ok(fx.set_path(base, "provenance.confidence", 1.0))
    assert one.canonical() == one_float.canonical()  # 1 and 1.0 are one stored value, compared by canonical JSON


def test_notes_are_bounded_untrusted_text():
    base = fx.base_dict()
    many = fx.set_path(base, "provenance.notes", [f"n{i}" for i in range(ad.MAX_NOTES)])
    assert len(ok(many).provenance.notes) == ad.MAX_NOTES
    refused(fx.set_path(base, "provenance.notes", [f"n{i}" for i in range(ad.MAX_NOTES + 1)]))
    refused(fx.set_path(base, "provenance.notes", ["x" * (ad.MAX_NOTE_CHARS + 1)]))
    ok(fx.set_path(base, "provenance.notes", ["x" * ad.MAX_NOTE_CHARS]))
    for bad in ("", " lead", "trail ", "a\nb", "a\x00b", "a\u200bb", "a\u202eb", "\ud800", 5, None):
        refused(fx.set_path(base, "provenance.notes", [bad]))
    refused(fx.set_path(base, "provenance.notes", "a single string"))


# ------------------------------------------------------------------ contraste (chiffres)


def test_contrast_ratio_matches_the_wcag_reference_values():
    assert ad.contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)
    assert ad.contrast_ratio("#ffffff", "#ffffff") == pytest.approx(1.0)
    assert ad.contrast_ratio("#767676", "#ffffff") == pytest.approx(4.54, abs=0.01)  # the well-known AA boundary grey
    assert ad.contrast_ratio("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)
    assert ad.contrast_ratio("#ffffff", "#767676") == ad.contrast_ratio("#767676", "#ffffff")  # symmetric
    assert ad.contrast_ratio("#ff0000", "#00ff00") == pytest.approx(2.91, abs=0.01)
    assert ad.relative_luminance("#ffffff") == pytest.approx(1.0) and ad.relative_luminance("#000000") == 0.0
    with pytest.raises(PresentationStudioError):
        ad.contrast_ratio("red", "#ffffff")


def light(**palette) -> dict:
    doc = fx.base_dict()
    doc["palette"] = {**doc["palette"], "background": "#ffffff", "surface": "#ffffff", "surface_opacity": 100,
                      "text": "#000000", "muted": "#595959", "accent": "#0000ff", "accent_alt": None, "gradients": [],
                      **palette}
    doc["dataviz"]["series"] = ["#0000ff", "#990000", "#005500"]
    return doc


def test_text_on_background_needs_4_5_to_1_at_the_boundary():
    assert ok(light(text="#767676", muted="#767676")).palette.text == "#767676"  # 4.54
    err = refused(light(text="#777777", muted="#767676"))
    assert "text on background" in err.message and "4.48" in err.message and "4.5" in err.message


def test_muted_accent_and_alt_accent_need_3_to_1_each_on_their_own_pair():
    assert ok(light(muted="#949494")).palette.muted == "#949494"  # 3.03
    assert "muted on background" in refused(light(muted="#959595")).message  # 2.99
    assert "accent on background" in refused(light(accent="#ffff00")).message
    assert "accent_alt on background" in refused(light(accent_alt="#eeeeee")).message
    assert ok(light(accent_alt="#0055ff")).palette.accent_alt == "#0055ff"


def test_the_surface_is_judged_where_it_is_seen_composited_on_the_background_at_its_opacity():
    dark = light(background="#101010", text="#f0f0f0", muted="#c0c0c0", accent="#66aaff")
    dark["dataviz"]["series"] = ["#66aaff", "#ffcc00", "#33dd99"]
    assert ok({**dark, "palette": {**dark["palette"], "surface": "#ffffff", "surface_opacity": 30}})  # 30% white on near-black
    with pytest.raises(PresentationStudioError) as caught:
        ad.parse_profile({**dark, "palette": {**dark["palette"], "surface": "#ffffff", "surface_opacity": 100}})
    assert "on surface" in caught.value.message  # the same white, opaque: light text on a white card is unreadable
    translucent = ad.parse_profile({**dark, "palette": {**dark["palette"], "surface": "#ffffff", "surface_opacity": 30}}).palette
    assert translucent.effective_surface() == ad.blend("#ffffff", "#101010", 0.3) != "#ffffff"


def test_a_gradient_must_carry_its_text_on_every_stop():
    gradient = {"gradient_id": "g", "kind": "linear", "angle": 90, "text_token": "text",
                "stops": [{"color": "#ffffff", "at": 0}, {"color": "#dddddd", "at": 100}]}
    assert ok(light(gradients=[gradient])).palette.gradients[0].gradient_id == "g"
    bad = {**gradient, "stops": [{"color": "#ffffff", "at": 0}, {"color": "#222222", "at": 100}]}
    err = refused(light(gradients=[bad]))
    assert "gradient g at 100%" in err.message  # the failing stop is named
    inverse = {**gradient, "text_token": "background"}  # white text on near-white stops
    assert "background on gradient g" in refused(light(gradients=[inverse])).message


def test_data_series_need_3_to_1_on_the_background_and_must_be_distinct():
    ok(light())
    refused(fx.set_path(light(), "dataviz.series", ["#0000ff", "#990000", "#fafafa"]))
    refused(fx.set_path(light(), "dataviz.series", ["#0000ff", "#0000ff", "#990000"]))
    refused(fx.set_path(light(), "dataviz.series", ["#0000ff", "#990000"]))
    refused(fx.set_path(light(), "dataviz.series", ["#0000ff"] * 3 + ["#990000"] * 6))


def test_contrast_report_lists_every_pair_with_its_measured_ratio_and_threshold():
    report = ok(fx.full_dict()).palette.contrast_report()
    names = {row["pair"] for row in report}
    assert {"text on background", "text on surface", "muted on background", "muted on surface",
            "accent on background", "accent_alt on background"} <= names
    assert any(name.startswith("text on gradient backdrop") for name in names)
    assert all(row["ok"] and row["ratio"] >= row["required"] for row in report)
    assert {row["required"] for row in report} == {4.5, 3.0}


def test_every_palette_the_module_builds_passes_the_numeric_check_on_every_combination():
    from jarvis.domain import presentation_studio_art_direction_authoring as au

    for archetype in au.ARCHETYPES:
        for accent in range(3):
            profile = au.build_archetype_profile(archetype, accent, name="x", provenance=ad.Provenance(ad.Origin.GENERATED))
            assert all(row["ok"] for row in profile.palette.contrast_report()), (archetype, accent)


# ------------------------------------------------------------------ pas d'injection : chaque champ, chaque chaîne


def _free_text_paths(doc) -> set[str]:
    paths = set()
    for path, value in fx.leaves(doc):
        parts = path.split(".")
        if parts[0] == "name" or parts[:2] == ["provenance", "notes"] or parts[:2] == ["imagery", "motifs"] \
                or (parts[0] == "references" and parts[-1] == "title"):
            paths.add(path)
    return paths


def test_hostile_strings_are_refused_in_every_field_that_is_not_declared_free_text():
    doc = fx.full_dict()
    free = _free_text_paths(doc)
    checked = 0
    for path, value in fx.leaves(doc):
        if path in free:
            continue
        for hostile in fx.HOSTILE:
            with pytest.raises(PresentationStudioError):
                ad.parse_profile(fx.set_path(doc, path, hostile))
            checked += 1
    assert checked > 1500 and "name" in free  # the sweep really covers the whole document


def test_hostile_strings_are_refused_as_a_key_of_provenance_sections_too():
    base = fx.base_dict()
    for hostile in fx.HOSTILE:
        refused(fx.set_path(base, "provenance.sections", {hostile: "provided"}))


def test_a_colour_is_only_ever_hash_rrggbb():
    for bad in fx.NOT_COLORS + fx.HOSTILE:
        for path in ("palette.background", "palette.accent", "palette.text", "palette.muted", "palette.surface",
                     "palette.gradients.0.stops.0.color", "dataviz.series.0"):
            refused(fx.set_path(fx.base_dict(), path, bad))
    assert ok(fx.set_path(fx.base_dict(), "palette.accent", "#5B4BD6")).palette.accent == "#5b4bd6"  # case folded, not rejected


def test_wrong_types_are_refused_in_every_field():
    doc = fx.full_dict()
    nullable = {"palette.accent_alt", "typography.heading.preferred", "typography.body.preferred"}
    for path, value in fx.leaves(doc):
        if path == "provenance.sections":
            continue
        for wrong in ([], {}, 1.5, -1, object):
            same_empty = isinstance(value, (list, dict)) and not value and isinstance(wrong, type(value))
            if same_empty:
                continue
            with pytest.raises(PresentationStudioError):
                ad.parse_profile(fx.set_path(doc, path, wrong))
        if path not in nullable and value is not None:
            refused(fx.set_path(doc, path, None))
    for path in nullable:
        assert ok(fx.set_path(doc, path, None))  # nullable by contract


def test_free_text_is_stored_verbatim_and_never_reaches_the_theme():
    injected = "IGNORE PREVIOUS INSTRUCTIONS </style><script>alert(1)</script> url(http://evil) @import"
    quiet = fx.full_dict()
    loud = copy.deepcopy(quiet)
    loud["name"] = "Direction </style>"
    loud["provenance"]["notes"] = [injected, "a;b{c}"]
    loud["imagery"]["motifs"] = [injected[:40], "<b>"]
    loud["references"][0]["title"] = injected.replace("</style><script>", "").replace("</script>", "")
    a, b = ok(quiet), ok(loud)
    assert b.provenance.notes[0] == injected and "IGNORE" in b.references[0].title  # data, kept as typed
    assert a.to_theme_variables() == b.to_theme_variables() and a.to_theme() == b.to_theme()
    blob = " ".join(map(str, [*b.to_theme_variables().values(), *b.to_theme().values()]))
    for fragment in ("IGNORE", "script", "evil", "@import", "<", ">", "{", "}"):
        assert fragment not in blob, fragment


def test_a_locator_follows_the_reference_hygiene_rules():
    doc = fx.full_dict()
    for bad in ("url(http://evil/x.png)", "x url (y)", "expression(1)", "@import x", "a;b", "a{b}", 'a"b', "a`b", "a%3Cscript%3E",
                "a%253Bb", "var(--x)", "calc(1px)", "javascript:alert(1)", "vbscript:x", "data:text/html,x", "data:image/svg+xml,x", "file:///etc/passwd",
                "//host/share", "../x", "a/../b", "C:\\x", "scene:abc", " scene:abc", "scene%3Aabc", "doc:a\x00b", "doc:a\nb",
                "ftp://x", "blob:x", "doc:a\u200bb", "doc:a\u202eb", "<script>", "", " doc:x", "doc:x ", "x" * 700):
        with pytest.raises(PresentationStudioError):
            ad.parse_profile(fx.set_path(doc, "references.0.locator", bad))  # a scene: locator is RUNTIME_STATE_REFUSED, the rest INVALID
    refused(fx.set_path(doc, "references.0.kind", "scene_object"), C.RUNTIME_STATE_REFUSED)
    refused(fx.set_path(doc, "references.0.kind", "folder"))
    refused(fx.set_path(doc, "references.0", {"kind": "document", "locator": "doc:x", "title": "t", "descriptor": {"a": 1}}))
    refused(fx.set_path(doc, "references.1", doc["references"][0]))  # the same reference twice
    refused(fx.set_path(doc, "references", doc["references"] * 7))  # more than 12
    ok(fx.set_path(doc, "references", []))
    ok(fx.set_path(doc, "references.0.locator", "doc:folder/brand%20guide"))


def test_references_are_capped_and_hold_only_kind_locator_title():
    doc = fx.full_dict()
    doc["references"] = [{"kind": "document", "locator": f"doc:r{n}", "title": ""} for n in range(ad.MAX_REFERENCES)]
    assert len(ok(doc).references) == ad.MAX_REFERENCES
    doc["references"].append({"kind": "document", "locator": "doc:one-more", "title": ""})
    refused(doc)
    assert set(ok(fx.full_dict()).to_dict()["references"][0]) == {"kind", "locator", "title"}


# ------------------------------------------------------------------ vocabulaires clos


ENUM_PATHS = {
    "palette.gradients.0.kind": ad.GradientKind, "palette.gradients.0.text_token": ad.TextToken,
    "typography.heading.stack": ad.FontStack, "typography.body.stack": ad.FontStack,
    "typography.text_size": ad.TextSize, "typography.scale_ratio": ad.ScaleRatio, "typography.label_case": ad.LabelCase,
    "spacing.density": ad.Density, "spacing.margin": ad.Margin, "shapes.elevation": ad.Elevation,
    "imagery.photo": ad.PhotoStyle, "imagery.illustration": ad.IllustrationStyle, "imagery.icons": ad.IconStyle,
    "imagery.treatment": ad.ImageTreatment, "dataviz.mode": ad.SeriesMode, "dataviz.grid": ad.GridStyle,
    "dataviz.labels": ad.LabelPlacement, "dataviz.emphasis": ad.Emphasis, "motion.tempo": ad.Tempo,
    "motion.easing": ad.Easing, "motion.transition": ad.TransitionStyle, "motion.reduced_motion": ad.ReducedMotion,
}


def test_every_closed_vocabulary_accepts_each_member_and_nothing_else():
    doc = fx.base_dict()
    for path, kind in ENUM_PATHS.items():
        for member in kind:
            if path.endswith("gradients.0.kind") and member is ad.GradientKind.RADIAL:
                continue  # needs angle 0, covered below
            if path.endswith("text_token") and member is ad.TextToken.BACKGROUND:
                continue  # background text over its own gradient stop is 1:1: refused by the contrast rule, tested there
            ok(fx.set_path(doc, path, member.value))
        for bad in ("", "Calm", member.value.upper(), member.value + " ", "none;", "x", 3, None, True, ["calm"]):
            if bad == member.value.upper() == member.value:
                continue
            with pytest.raises(PresentationStudioError):
                ad.parse_profile(fx.set_path(doc, path, bad))


def test_closed_numeric_sets_accept_their_members_only():
    doc = fx.base_dict()
    for path, allowed in (("motion.enter_ms", ad.DURATIONS_MS), ("motion.exit_ms", ad.DURATIONS_MS),
                          ("motion.emphasis_ms", ad.DURATIONS_MS), ("motion.stagger_ms", ad.STAGGERS_MS),
                          ("typography.heading_weight", ad.HEADING_WEIGHTS), ("typography.body_weight", ad.BODY_WEIGHTS)):
        for value in allowed:
            ok(fx.set_path(doc, path, value))
        for bad in (-1, 1, 50, 999, 10**9, 1.0, True, "200", None):
            if bad in allowed and not isinstance(bad, bool):
                continue
            refused(fx.set_path(doc, path, bad))


def test_numeric_bounds_are_enforced_at_both_ends():
    doc = fx.base_dict()
    for path, low, high in (("shapes.radius_px", 0, ad.MAX_RADIUS_PX), ("shapes.stroke_px", 0, ad.MAX_STROKE_PX),
                            ("palette.surface_opacity", ad.MIN_SURFACE_OPACITY, ad.MAX_SURFACE_OPACITY),
                            ("palette.gradients.0.angle", 0, 359), ("palette.gradients.0.stops.0.at", 0, 99)):
        ok(fx.set_path(doc, path, low))
        ok(fx.set_path(doc, path, high))
        refused(fx.set_path(doc, path, low - 1))
        refused(fx.set_path(doc, path, high + 1))
        refused(fx.set_path(doc, path, float(low)))
        refused(fx.set_path(doc, path, True))


def test_gradient_structure_rules():
    doc = fx.full_dict()
    stops = doc["palette"]["gradients"][0]["stops"]
    refused(fx.set_path(doc, "palette.gradients.0.stops", stops[:1]))
    refused(fx.set_path(doc, "palette.gradients.0.stops", [{"color": "#ffffff", "at": n * 10} for n in range(6)]))
    refused(fx.set_path(doc, "palette.gradients.0.stops", [{"color": "#ffffff", "at": 50}, {"color": "#ffffff", "at": 50}]))
    refused(fx.set_path(doc, "palette.gradients.0.stops", [{"color": "#ffffff", "at": 60}, {"color": "#ffffff", "at": 10}]))
    refused(fx.set_path(doc, "palette.gradients.1.angle", 45))  # radial: angle 0
    refused(fx.set_path(doc, "palette.gradients.1.gradient_id", doc["palette"]["gradients"][0]["gradient_id"]))  # duplicate id
    refused(fx.set_path(doc, "palette.gradients.0.gradient_id", "Backdrop"))
    refused(fx.set_path(doc, "palette.gradients.0.gradient_id", "1x"))
    refused(fx.set_path(doc, "palette.gradients.0.gradient_id", "x" * 41))
    one = doc["palette"]["gradients"][0]
    refused(fx.set_path(doc, "palette.gradients", [{**one, "gradient_id": f"g{n}"} for n in range(ad.MAX_GRADIENTS + 1)]))
    assert len(ok(fx.set_path(doc, "palette.gradients", [{**one, "gradient_id": f"g{n}"} for n in range(ad.MAX_GRADIENTS)])).palette.gradients) == ad.MAX_GRADIENTS


def test_reduced_motion_is_mandatory_and_never_keep_the_motion():
    doc = fx.base_dict()
    assert {m.value for m in ad.ReducedMotion} == {"fade_only", "static"}
    refused({**doc, "motion": {k: v for k, v in doc["motion"].items() if k != "reduced_motion"}})
    for bad in ("none", "keep", "full", "", None):
        refused(fx.set_path(doc, "motion.reduced_motion", bad))


# ------------------------------------------------------------------ typographie : piles sûres uniquement


def test_font_stacks_are_constants_of_the_module_never_a_received_string():
    assert set(ad.FONT_STACK_CSS) == set(ad.FontStack) == set(ad.FONT_CLASS)
    for stack, css in ad.FONT_STACK_CSS.items():
        assert re.fullmatch(r'[A-Za-z0-9 ,"\-]+', css), (stack, css)  # families, quotes, commas: nothing else
        assert not re.search(r"url|expression|import|javascript|var\(|;|\{|\}|\\|<|>|@", css, re.I)
        assert css.rstrip().split(",")[-1].strip() in {"sans-serif", "serif", "monospace"}  # always ends on a generic family


def test_a_declared_family_is_a_plain_name_and_goes_first_in_quotes():
    doc = fx.base_dict()
    for good in ("Inter", "Playfair Display", "Source Sans 3", "IBM-Plex", "A", "a1", "x" * 40):
        profile = ok(fx.set_path(doc, "typography.heading.preferred", good))
        assert profile.typography.heading.css().startswith(f'"{good}", ')
    for bad in ("", " Inter", "Inter ", "In  ter", "-Inter", "Inter-", "Inter;", 'Inter"', "Inter'", "In\\ter", "Inter, serif", "x" * 41,
                "Inter\n", "Intér", "Inter(1)", "url(x)", "1Inter", "Inter\u202e"):
        refused(fx.set_path(doc, "typography.heading.preferred", bad))
    refused(fx.set_path(doc, "typography.heading.preferred", 5))
    refused(fx.set_path(doc, "typography.heading", {"stack": "system_sans"}))  # preferred is required (null allowed)


# ------------------------------------------------------------------ thème : seules les variables --jv-* connues


SAFE_VALUE = re.compile(
    r'(#[0-9a-f]{6}|rgba\([0-9]{1,3},[0-9]{1,3},[0-9]{1,3},(?:0\.[0-9]{2}|1\.00|0\.97|0\.16|0\.09)\)|[0-9]+(?:\.[0-9]+)?|[0-9]+px'
    r'|(?:"[A-Za-z0-9 -]{1,40}", )?[A-Za-z0-9 ,"\-]+)\Z')


def _shell_variables() -> set[str]:
    css = (ROOT / "jarvis/prefabs/runtime/shell.css").read_text(encoding="utf-8")
    root = css[css.index(":root{"):css.index("}", css.index(":root{"))]
    return set(re.findall(r"(--jv-[a-z]+):", root))


def _host_theme_keys() -> set[str]:
    shim = (ROOT / "jarvis/prefabs/runtime/shim.js").read_text(encoding="utf-8")
    line = next(line for line in shim.splitlines() if "var THEME_VARS" in line)
    return set(re.findall(r"(\w+):'--jv-", line))


def test_the_theme_touches_only_declared_shell_variables_and_only_host_theme_keys():
    profile = ok(fx.full_dict())
    variables = profile.to_theme_variables()
    assert set(variables) == ad.ALLOWED_THEME_VARIABLES
    assert ad.ALLOWED_THEME_VARIABLES <= _shell_variables()  # every name exists in shell.css :root: no new variable is invented
    theme = profile.to_theme()
    assert set(theme) == set(ad.HOST_THEME_KEYS) == _host_theme_keys()  # exactly what `shim.js` THEME_VARS applies


def test_every_theme_value_is_a_token_in_the_closed_grammar_for_every_shipped_direction():
    from jarvis.domain import presentation_studio_art_direction_authoring as au

    forbidden = re.compile(r"url|expression|import|javascript|var\(|calc\(|;|\{|\}|\\|<|>|@|\n|/\*", re.I)
    for archetype in au.ARCHETYPES:
        for accent in range(3):
            profile = au.build_archetype_profile(archetype, accent, name="x", provenance=ad.Provenance(ad.Origin.GENERATED))
            for name, value in profile.to_theme_variables().items():
                assert SAFE_VALUE.fullmatch(value), (name, value)
                assert not forbidden.search(value), (name, value)
            for key, value in profile.to_theme().items():
                assert isinstance(value, (str, float)) and not forbidden.search(str(value)), (key, value)


def test_the_theme_values_follow_the_profile():
    profile = ok(fx.set_path(fx.set_path(fx.full_dict(), "shapes.radius_px", 14), "spacing.density", "airy"))
    variables = profile.to_theme_variables()
    assert variables["--jv-radius"] == "14px" and variables["--jv-gap"] == "10px"
    assert variables["--jv-accent"] == profile.palette.accent and variables["--jv-ground"] == profile.palette.background
    assert variables["--jv-font"].startswith('"Inter"') is False  # body font: only the heading carries the declared family here
    assert ok(fx.set_path(fx.full_dict(), "typography.body.preferred", "Inter")).to_theme_variables()["--jv-font"].startswith('"Inter", ')
    for size, scale in ad.TEXT_SCALE.items():
        assert ok(fx.set_path(fx.full_dict(), "typography.text_size", size.value)).to_theme()["scale"] == scale


def test_the_theme_is_deterministic_and_does_not_alias_profile_state():
    profile = ok(fx.full_dict())
    first = profile.to_theme_variables()
    first["--jv-accent"] = "#000000"
    assert profile.to_theme_variables()["--jv-accent"] == profile.palette.accent
    assert canonical_json(ok(fx.full_dict()).to_theme_variables()) == canonical_json(ok(fx.full_dict()).to_theme_variables())


def test_gradient_and_easing_css_are_built_only_from_validated_tokens():
    profile = ok(fx.full_dict())
    for gradient in profile.palette.gradients:
        css = ad.gradient_css(gradient)
        assert re.fullmatch(r"(linear-gradient\([0-9]{1,3}deg|radial-gradient\(circle)(, #[0-9a-f]{6} [0-9]{1,3}%)+\)", css), css
    assert ad.gradient_css(profile.palette.gradients[0]).startswith("linear-gradient(160deg, ")
    for easing in ad.Easing:
        assert re.fullmatch(r"linear|cubic-bezier\([0-9., -]+\)", ad.easing_css(easing))
    with pytest.raises(PresentationStudioError):
        ad.easing_css("ease; background:url(x)")


def test_parse_length_accepts_only_a_number_and_a_closed_unit():
    assert (ad.parse_length("8px"), ad.parse_length("0.5rem"), ad.parse_length("1em"), ad.parse_length("0px")) == (8, 8, 16, 0)
    assert ad.parse_length("999px") == ad.MAX_RADIUS_PX  # a pill radius is clamped, not refused
    for bad in ("8", "8pt", "8%", "calc(1px)", "var(--r)", "url(x)", "8px;", "8 px", "-1px", "+1px", "1e3px", ".5px", "8px }",
                "", None, 8, "８px", "8PX", "expression(1)", "8px\n"):
        with pytest.raises(PresentationStudioError):
            ad.parse_length(bad)


# ------------------------------------------------------------------ classement de chaque champ (anti-régression)


def test_every_field_of_the_model_is_classified_whatever_its_annotation():
    classified = ad.FREE_TEXT_FIELDS | ad.ID_FIELDS | ad.TOKEN_FIELDS | ad.STRUCTURE_FIELDS
    assert not (ad.FREE_TEXT_FIELDS & ad.TOKEN_FIELDS) and not (ad.FREE_TEXT_FIELDS & ad.STRUCTURE_FIELDS)
    unclassified = [f"{cls.__name__}.{f.name}" for cls in ad.MODEL_CLASSES for f in dataclasses.fields(cls)
                    if f.name not in classified]
    assert unclassified == [], f"classify these fields (free text, id, token, or structure): {unclassified}"
    # a loose annotation is how a payload field sneaks in: refused outright
    loose = [f"{cls.__name__}.{f.name}" for cls in ad.MODEL_CLASSES for f in dataclasses.fields(cls)
             if re.search(r"\b(Any|object|dict|bytes)\b", str(f.type))]
    assert loose == [], loose


def test_free_text_fields_are_exactly_the_ones_that_accept_arbitrary_printable_text():
    doc = fx.full_dict()
    accepting = set()
    for path, _ in fx.leaves(doc):
        try:
            ad.parse_profile(fx.set_path(doc, path, "plain words & things ; ok (maybe) url(x)"))
        except PresentationStudioError:
            continue
        accepting.add(path)
    assert accepting == _free_text_paths(doc), accepting ^ _free_text_paths(doc)


def test_the_module_is_pure_no_io_no_network_no_database():
    for name in ("presentation_studio_art_direction.py", "presentation_studio_art_direction_authoring.py"):
        source = (ROOT / "jarvis" / "domain" / name).read_text(encoding="utf-8")
        for needle in ("import os", "import socket", "import urllib", "import requests", "import aiohttp", "pathlib", "open(",
                       "sqlite", "subprocess", "import time", "datetime.now", "random", "eval(", "exec("):
            assert needle not in source, (name, needle)


# ------------------------------------------------------------------ « chaque variante sérieuse résout une DA »


class Lookup:
    def __init__(self, art=None) -> None:
        self.art, self.calls = art, []

    def find(self, presentation_id, art_direction_id):
        self.calls.append((presentation_id, art_direction_id))
        return self.art


def variant(art_direction_id=fx.AD_ID, **changes):
    return SimpleNamespace(presentation_id=fx.PRESENTATION, variant_id=fx.VARIANT, art_direction_id=art_direction_id, **changes)


def test_require_art_direction_matrix():
    art = ad.ArtDirection(fx.AD_ID, fx.PRESENTATION, fx.VARIANT, ok(fx.full_dict()), 1, fx.STAMP, fx.STAMP)
    # serious: resolved / missing / dangling
    got = ad.require_art_direction(variant(), Lookup(art), serious=True)
    assert got.status is ad.Resolution.RESOLVED and got.art_direction is art and not got.is_fallback
    with pytest.raises(PresentationStudioError) as missing:
        ad.require_art_direction(variant(None), Lookup(), serious=True)
    assert missing.value.code is C.ART_DIRECTION_REQUIRED and missing.value.status == 409
    with pytest.raises(PresentationStudioError) as dangling:
        ad.require_art_direction(variant(), Lookup(None), serious=True)
    assert dangling.value.code is C.UNKNOWN_ART_DIRECTION and dangling.value.status == 404
    # exploratory: lighter
    assert ad.require_art_direction(variant(), Lookup(art), serious=False).status is ad.Resolution.RESOLVED
    none = ad.require_art_direction(variant(None), Lookup(), serious=False)
    assert (none.status, none.art_direction) == (ad.Resolution.MISSING, None)
    gone = ad.require_art_direction(variant(), Lookup(None), serious=False)
    assert (gone.status, gone.art_direction) == (ad.Resolution.DANGLING, None)
    # serious is the default: a caller that forgets the flag is strict
    with pytest.raises(PresentationStudioError):
        ad.require_art_direction(variant(None), Lookup())


def test_require_art_direction_does_not_look_up_a_missing_id_and_asks_with_the_right_ids():
    probe = Lookup()
    ad.require_art_direction(variant(None), probe, serious=False)
    assert probe.calls == []
    art = ad.ArtDirection(fx.AD_ID, fx.PRESENTATION, fx.VARIANT, ok(fx.base_dict()), 1, fx.STAMP, fx.STAMP)
    probe = Lookup(art)
    ad.require_art_direction(variant(), probe)
    assert probe.calls == [(fx.PRESENTATION, fx.AD_ID)]


def test_a_fallback_direction_resolves_and_says_so():
    art = ad.ArtDirection(fx.AD_ID, fx.PRESENTATION, fx.VARIANT, fx.base_profile(), 1, fx.STAMP, fx.STAMP)
    got = ad.require_art_direction(variant(), Lookup(art), serious=True)
    assert got.status is ad.Resolution.RESOLVED and got.is_fallback
    assert got.art_direction.profile.provenance.origin is ad.Origin.GENERATED  # inspectable origin


def test_a_document_that_names_another_variant_or_art_direction_is_a_data_fault():
    for kwargs in ({"variant_id": "psv_" + "c" * 32}, {"presentation_id": "pst_" + "c" * 32}, {"art_direction_id": "psd_00000000ffff"}):
        ids = {"art_direction_id": fx.AD_ID, "presentation_id": fx.PRESENTATION, "variant_id": fx.VARIANT, **kwargs}
        art = ad.ArtDirection(profile=ok(fx.base_dict()), revision=1, created_at=fx.STAMP, updated_at=fx.STAMP, **ids)
        for serious in (True, False):
            with pytest.raises(PresentationStudioError) as caught:
                ad.require_art_direction(variant(), Lookup(art), serious=serious)
            assert caught.value.code is C.CORRUPT_DOCUMENT


def test_serious_must_be_a_real_boolean():
    for bad in (1, 0, "true", None, [], 1.0):
        with pytest.raises(PresentationStudioError) as caught:
            ad.require_art_direction(variant(), Lookup(), serious=bad)
        assert caught.value.code is C.INVALID_PRESENTATION


def test_the_two_new_error_codes_have_a_status_and_a_name():
    assert C.UNKNOWN_ART_DIRECTION.value == "presentation_studio_unknown_art_direction"
    assert C.ART_DIRECTION_REQUIRED.value == "presentation_studio_art_direction_required"
    assert PresentationStudioError(C.UNKNOWN_ART_DIRECTION, "x").status == 404
    assert PresentationStudioError(C.ART_DIRECTION_REQUIRED, "x").status == 409


def test_schema_registry_knows_the_new_document_kind():
    from jarvis.domain import presentation_studio as ps

    assert ps.SCHEMA_ART_DIRECTION == "jarvis.presentation_studio.art_direction"
    assert ps.CURRENT_VERSIONS[ps.SCHEMA_ART_DIRECTION] == 1 and ps.UPGRADES[ps.SCHEMA_ART_DIRECTION] == {}
    assert ps.is_art_direction_id("psd_0123456789ab") and not ps.is_art_direction_id("psr_0123456789ab")
    assert not ps.is_art_direction_id("psd_0123456789AB") and not ps.is_art_direction_id("psd_0123456789abc")
    assert not ps.is_art_direction_id(None) and not ps.is_art_direction_id(5)

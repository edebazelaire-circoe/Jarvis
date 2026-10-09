"""Domaine des prefabs (Slice 02) : manifeste strict, schémas d'entrée, valeurs, lint, publication, verrou.

Contrat : `docs/prefabs.md` › *Manifest*, *Input schema*, *Hygiene lint*, *Publication and provenance*.
"""

from __future__ import annotations

import copy
import json

import pytest

from jarvis.domain import prefab as p
from tests.fakes.prefabs import FIXTURES, candidate


def schema(raw: dict, **kwargs) -> p.InputSchema:
    return p.parse_input_schema(raw, "s", **kwargs)


def errors_of(raw_candidate: dict) -> tuple[str, ...]:
    with pytest.raises(p.PrefabDefinitionError) as caught:
        p.parse_candidate(raw_candidate)
    return caught.value.errors


# ------------------------------------------------------------------ identité, classification


@pytest.mark.parametrize("value", ["jarvis.window", "test.counter", "a.b.c.d", "my_lab.check-list"])
def test_prefab_ids_accepted(value):
    assert p.is_prefab_id(value)


@pytest.mark.parametrize("value", ["window", "Jarvis.window", "a..b", ".a.b", "a.b.c.d.e", "1a.b", "a.b ", "a/b.c",
                                   "events", "a." + "b" * 40, 7, None])
def test_prefab_ids_refused(value):
    assert not p.is_prefab_id(value)


def test_classification_is_derived_from_the_namespace():
    assert p.prefab_class("jarvis.window") is p.PrefabClass.BASE
    assert p.prefab_class("jarvisx.window") is p.PrefabClass.CUSTOM
    assert p.prefab_class("test.counter") is p.PrefabClass.CUSTOM
    assert p.parse_candidate(candidate(id="jarvis.counter")).manifest.prefab_class is p.PrefabClass.BASE


@pytest.mark.parametrize("value,expected", [("1", 1), ("9999", 9999), ("01", None), ("0", None), ("10000", None),
                                            ("v1", None), ("", None)])
def test_version_folder_names(value, expected):
    assert p.version_folder_name(value) == expected


@pytest.mark.parametrize("value", [0, 10000, True, 1.0, "1"])
def test_versions_refused(value):
    assert not p.is_version(value)


# ------------------------------------------------------------------ fixtures


def test_the_valid_fixture_parses_with_defaults_applied_to_the_sample():
    bundle = p.parse_candidate(candidate())
    manifest = bundle.manifest
    assert manifest.ref == p.PrefabRef("test.counter", 1)
    assert manifest.sample_props == {"label": "Count", "accent": "#6ee7ff", "mode": "full"}
    assert manifest.sample_data == {"count": 3, "notes": "", "history": []}
    assert set(manifest.events) == {"incremented", "reset_requested"}
    assert manifest.events["incremented"].payload.properties["count"].type is p.InputType.INTEGER
    assert manifest.default_size == (40.0, 24.0)


@pytest.mark.parametrize("fixture,needle", [
    ("test.bad_unknown_key", "unknown fields for type string"),
    ("test.bad_provenance", "provenance"),
    ("test.bad_sample", "sample.data.count: must be at least 0"),
    ("test.bad_ref", "$ref 'data.missing' names no input"),
    ("test.bad_writes", "names keys absent from inputs.data"),
    ("test.bad_depth", "schema nesting exceeds depth 4"),
    ("test.bad_lint", "forbidden tag <script>"),
])
def test_each_bad_fixture_is_refused_for_its_reason(fixture, needle):
    errors = errors_of(candidate(fixture))
    assert any(needle in item for item in errors), errors


def test_every_bad_fixture_folder_is_covered():
    folders = {path.name for path in FIXTURES.iterdir() if path.name.startswith("test.bad_")}
    assert folders == {"test.bad_unknown_key", "test.bad_provenance", "test.bad_sample", "test.bad_ref",
                       "test.bad_writes", "test.bad_depth", "test.bad_lint"}


# ------------------------------------------------------------------ manifeste strict


def test_unknown_top_level_keys_are_refused():
    assert any("unknown fields ['theme']" in item for item in errors_of(candidate(theme="dark")))


@pytest.mark.parametrize("field", sorted(p.PROVENANCE_FIELDS))
def test_any_provenance_field_in_a_candidate_is_refused(field):
    errors = errors_of(candidate(**{field: None}))
    assert any("provenance is written by Core" in item for item in errors)


def test_missing_required_fields_are_named():
    raw = candidate()
    del raw["manifest"]["sample"], raw["manifest"]["files"]
    assert any("missing fields ['files', 'sample']" in item for item in errors_of(raw))


@pytest.mark.parametrize("changes,needle", [
    ({"schema": "jarvis.other"}, "schema:"),
    ({"schema_version": 3}, "schema:"),
    ({"schema_version": True}, "schema:"),
    ({"version": 0}, "version:"),
    ({"version": "1"}, "version:"),
    ({"title": ""}, "title:"),
    ({"title": "x" * 81}, "title:"),
    ({"title": "a\nb"}, "title:"),
    ({"description": "x" * 601}, "description:"),
    ({"family": "Window"}, "family:"),
    ({"family": "w" * 33}, "family:"),
    ({"tags": ["t"] * 17}, "tags:"),
    ({"aliases": ["x" * 41]}, "aliases:"),
    ({"scene": {"kind": "agent"}}, "scene:"),
    ({"scene": {"kind": "window", "default_size": {"w": 0, "h": 10}}}, "scene.default_size:"),
    ({"scene": {"kind": "window", "default_size": {"w": 10, "h": 1e9}}}, "scene.default_size:"),
    ({"files": {"template": "index.html", "style": "style.css", "behavior": "behavior.js"}}, "files:"),
    ({"inputs": {"props": {"type": "object"}}}, "inputs:"),
    ({"inputs": {"props": {"type": "string"}, "data": {"type": "object"}}}, "inputs.props:"),
    ({"sample": {"props": {}}}, "sample:"),
])
def test_manifest_field_rules(changes, needle):
    assert any(item.startswith(needle) for item in errors_of(candidate(**changes))), changes


def test_errors_are_collected_together_and_bounded():
    errors = errors_of(candidate(title="", family="Bad", tags="x", version=0))
    assert len(errors) >= 4
    many = {f"k{index}": {"type": "nope"} for index in range(30)}
    raw = candidate()
    raw["manifest"]["inputs"]["props"]["properties"] = many
    errors = errors_of(raw)
    assert len(errors) <= p.MAX_ERRORS
    assert all(len(item) <= p.MAX_ERROR_CHARS for item in errors)


def test_error_messages_never_echo_a_huge_value():
    raw = candidate(id="x" * 5000)
    errors = errors_of(raw)
    assert all(len(item) <= p.MAX_ERROR_CHARS for item in errors)


def test_manifest_size_is_bounded():
    raw = candidate(description="")
    raw["manifest"]["tags"] = []
    raw["manifest"]["inputs"]["props"]["properties"] = {
        f"p{index}": {"type": "enum", "values": [f"{value:02d}" + "v" * 30 for value in range(32)]}
        for index in range(32)}
    assert any("bytes, at most" in item for item in errors_of(raw))


# ------------------------------------------------------------------ événements


def event_errors(events: dict) -> tuple[str, ...]:
    return errors_of(candidate(events=events))


def test_event_rules():
    object_payload = {"type": "object", "properties": {}}
    assert any("must match" in item for item in event_errors({"Bad": {"class": "notify", "payload": object_payload}}))
    assert any("'state' or 'notify'" in item for item in event_errors({"e": {"class": "x", "payload": object_payload}}))
    assert any("at least one" in item for item in event_errors({"e": {"class": "state", "payload": object_payload}}))
    assert any("forbidden for a notify" in item for item in event_errors(
        {"e": {"class": "notify", "writes": ["count"], "payload": object_payload}}))
    assert any("only carry the keys it writes" in item for item in event_errors(
        {"e": {"class": "state", "writes": ["count"],
               "payload": {"type": "object", "properties": {"notes": {"$ref": "data.notes"}}}}}))
    assert any("of type object" in item for item in event_errors(
        {"e": {"class": "notify", "payload": {"type": "string"}}}))
    assert any("summary" in item for item in event_errors(
        {"e": {"class": "notify", "payload": object_payload, "summary": "s" * 121}}))
    too_many = {f"e{index}": {"class": "notify", "payload": object_payload} for index in range(17)}
    assert any("at most 16 events" in item for item in event_errors(too_many))


def test_ref_reuses_an_input_schema_and_is_refused_outside_events():
    manifest = p.parse_candidate(candidate()).manifest
    assert manifest.events["incremented"].payload.properties["history"] is manifest.data.properties["history"]
    raw = candidate()
    raw["manifest"]["inputs"]["data"]["properties"]["copy"] = {"$ref": "data.count"}
    assert any("$ref is allowed only in event payload schemas" in item for item in errors_of(raw))


# ------------------------------------------------------------------ schémas et valeurs, type par type


@pytest.mark.parametrize("node,good,bad", [
    ({"type": "string", "max_length": 5}, "abc", ["abcdef", "a\nb", 3, None]),
    ({"type": "string", "pattern": "^[a-z]+$"}, "abc", ["ABC", "a1"]),
    ({"type": "text", "max_length": 10}, "a\nb\tc", ["x" * 11, "a\rb", "a\x00b", 1]),
    ({"type": "number", "min": 0, "max": 1}, 0.5, [-0.1, 2, float("nan"), float("inf"), True, "1"]),
    ({"type": "integer", "min": 1}, 3, [0, 1.5, True, "3"]),
    ({"type": "boolean"}, False, [0, "false", None]),
    ({"type": "color"}, "#A0b1c2", ["#fff", "red", "#gggggg", 1]),
    ({"type": "enum", "values": ["a", "b"]}, "b", ["c", 1]),
    ({"type": "url"}, "https://example.com/x?y=1", ["javascript:alert(1)", "ftp://h/x", "http://", "https://a b",
                                                   "x" * 3000]),
    ({"type": "array", "items": {"type": "integer"}, "max_items": 2, "min_items": 1}, [1, 2], [[], [1, 2, 3],
                                                                                              ["a"], "x"]),
    ({"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}, {"a": "x"},
     [{}, {"a": "x", "b": 1}, [], {"a": 1}]),
])
def test_every_input_type_accepts_and_refuses(node, good, bad):
    parsed = schema(node)
    assert p.validate_value(parsed, good)[1] == ()
    for value in bad:
        assert p.validate_value(parsed, value)[1], value


@pytest.mark.parametrize("node", [
    {"type": "string", "max_length": 2001},
    {"type": "string", "pattern": "[a-z]+"},
    {"type": "string", "pattern": "^(unclosed$"},
    {"type": "text", "max_length": 12001},
    {"type": "text", "format": "html"},
    {"type": "number", "min": 2, "max": 1},
    {"type": "integer", "min": 0.5},
    {"type": "enum", "values": []},
    {"type": "enum", "values": ["a", "a"]},
    {"type": "enum", "values": ["a"] * 33},
    {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["b"]},
    {"type": "object", "properties": {"bad name": {"type": "string"}}},
    {"type": "object", "properties": {f"p{index}": {"type": "boolean"} for index in range(33)}},
    {"type": "array"},
    {"type": "array", "items": {"type": "string"}, "max_items": 257},
    {"type": "array", "items": {"type": "string"}, "min_items": 3, "max_items": 2},
    {"type": "boolean", "max_length": 3},
    {"type": "string", "default": 3},
    {"type": "string", "description": "d" * 201},
    {"type": "date"},
    "string",
])
def test_invalid_schema_nodes_are_refused(node):
    with pytest.raises(p.PrefabDefinitionError):
        schema(node)


def test_depth_bound_counts_from_the_root():
    leaf: dict = {"type": "string"}
    node = leaf
    for _ in range(4):
        node = {"type": "object", "properties": {"x": node}}
    schema(node)  # profondeur 4 : accepté
    with pytest.raises(p.PrefabDefinitionError, match="depth 4"):
        schema({"type": "array", "items": node})


def test_defaults_are_applied_recursively_and_copied():
    parsed = schema({"type": "object", "properties": {
        "tags": {"type": "array", "items": {"type": "string"}, "default": ["a"]},
        "rows": {"type": "array", "items": {"type": "object", "properties": {
            "done": {"type": "boolean", "default": False}, "label": {"type": "string"}}, "required": ["label"]}}}})
    value, errors = p.validate_value(parsed, {"rows": [{"label": "x"}]})
    assert errors == ()
    assert value == {"tags": ["a"], "rows": [{"label": "x", "done": False}]}
    value["tags"].append("mutated")
    assert p.validate_value(parsed, {"rows": []})[0]["tags"] == ["a"]


def test_value_errors_are_named_by_path_and_bounded():
    parsed = schema({"type": "object", "properties": {"rows": {"type": "array", "items": {"type": "integer"}}}})
    _, errors = p.validate_value(parsed, {"rows": ["a"] * 100}, "data")
    assert errors[0] == "data.rows[0]: expected a finite integer, got 'a'"
    assert len(errors) == p.MAX_ERRORS


# ------------------------------------------------------------------ lint


@pytest.mark.parametrize("tag", ["script", "style", "iframe", "object", "embed", "base", "link", "meta", "form", "area"])
def test_lint_refuses_each_forbidden_template_tag(tag):
    assert any(f"<{tag}>" in item for item in p.lint_sources(f"<div><{tag.upper()} x='1'></div>", "", ""))


@pytest.mark.parametrize("template", ['<img src="x" onerror="go()">', "<div\nonClick='x'>", "<a/onmouseover=1>"])
def test_lint_refuses_inline_handlers(template):
    assert any("on*=" in item for item in p.lint_sources(template, "", ""))


def test_lint_leaves_text_that_merely_mentions_on():
    assert p.lint_sources("<p>Someone = me; turn on = yes</p>", "", "") == ()


@pytest.mark.parametrize("style,refused", [
    ("@import 'x.css';", True), ("@IMPORT url(data:x)", True), (".a{background:url(http://x/y.png)}", True),
    (".a{background:url( 'https://x')}", True), (".a{background:url(data:image/png;base64,AA==)}", False),
    (".a{background:url( \"data:image/svg+xml,x\")}", False),
])
def test_lint_style(style, refused):
    assert bool(p.lint_sources("", style, "")) is refused


def test_lint_behavior_refuses_a_closing_script_tag():
    assert p.lint_sources("", "", "var x = '</SCRIPT>';")
    assert p.lint_sources("", "", "var x = '<script>';") == ()


def test_source_sizes_are_bounded():
    raw = candidate()
    raw["behavior"] = "x" * (p.MAX_BEHAVIOR_BYTES + 1)
    assert any("behavior: is" in item for item in errors_of(raw))


def test_candidate_shape_is_exact():
    with pytest.raises(p.PrefabDefinitionError, match="exactly"):
        p.parse_candidate({**candidate(), "extra": 1})
    with pytest.raises(p.PrefabDefinitionError, match="exactly"):
        p.parse_candidate([])


# ------------------------------------------------------------------ empreinte, publication


def test_fingerprint_is_stable_and_uses_the_prompt_registry_canonical_json():
    from jarvis.domain.prompt_registry import fingerprint

    raw = candidate()
    bundle = p.parse_candidate(raw)
    reordered = dict(reversed(list(raw["manifest"].items())))
    assert p.parse_bundle(reordered, raw["template"], raw["style"], raw["behavior"]).fingerprint() \
        == bundle.fingerprint()
    assert bundle.fingerprint() == fingerprint({"manifest": raw["manifest"], "template": raw["template"],
                                                "style": raw["style"], "behavior": raw["behavior"]})
    changed = p.parse_bundle(raw["manifest"], raw["template"] + " ", raw["style"], raw["behavior"])
    assert changed.fingerprint() != bundle.fingerprint()


def test_with_version_does_not_touch_the_original():
    raw = candidate()
    renumbered = p.with_version(raw["manifest"], 7)
    assert renumbered["version"] == 7 and raw["manifest"]["version"] == 1


def publication(origin, prefab_id="test.counter", version=2, derived=None, base_edit=None, actor="user"):
    return p.Publication(prefab_id, version, "a" * 64, "2026-10-03T12:00:00Z",
                         p.Provenance(p.ProvenanceOrigin(origin), p.CreatorActor(actor), derived, base_edit))


def test_publication_round_trip_for_every_origin():
    record = p.BaseEditRecord("make the checklist bigger please", "conversation_event:evt-1")
    cases = [
        publication("custom", version=1),
        publication("fork", derived=p.PrefabRef("jarvis.window", 1)),
        publication("revision", derived=p.PrefabRef("test.counter", 1)),
        publication("base", "jarvis.window", 1, actor="system"),
        publication("base_edit", "jarvis.window", 2, p.PrefabRef("jarvis.window", 1), record, actor="brain"),
    ]
    for item in cases:
        text = item.render()
        assert p.Publication.decode_text(text) == item
        assert json.loads(text)["schema"] == p.PUBLICATION_SCHEMA


@pytest.mark.parametrize("build", [
    lambda: publication("custom", derived=p.PrefabRef("x.y", 1)),
    lambda: publication("fork"),
    lambda: publication("fork", derived=p.PrefabRef("test.counter", 1)),
    lambda: publication("revision", derived=p.PrefabRef("other.id", 1)),
    lambda: publication("base_edit", "jarvis.window", 2, p.PrefabRef("jarvis.window", 1)),
    lambda: publication("custom", "jarvis.window", 1),
    lambda: publication("base", "test.counter", 1, actor="system"),
    lambda: p.BaseEditRecord("short", "conversation_event:e"),
    lambda: p.BaseEditRecord("long enough request here", "event:e"),
    lambda: p.BaseEditRecord("long enough request here", "conversation_event:e", confirmed_by_user=False),
    lambda: p.Publication("test.counter", 1, "nothex", "2026-10-03T12:00:00Z",
                          p.Provenance(p.ProvenanceOrigin.CUSTOM, p.CreatorActor.USER)),
    lambda: p.Publication("test.counter", 1, "a" * 64, "2026-10-03 12:00",
                          p.Provenance(p.ProvenanceOrigin.CUSTOM, p.CreatorActor.USER)),
])
def test_publication_invariants(build):
    with pytest.raises(p.PrefabDefinitionError):
        build()


def test_publication_decode_is_strict():
    body = publication("custom", version=1).to_dict()
    for broken in ({**body, "extra": 1}, {**body, "schema_version": 2},
                   {**body, "provenance": {**body["provenance"], "note": "x"}}):
        with pytest.raises(p.PrefabDefinitionError):
            p.Publication.from_dict(broken)
    with pytest.raises(p.PrefabDefinitionError, match="not valid JSON"):
        p.Publication.decode_text("{")
    with pytest.raises(p.PrefabDefinitionError, match="exceeds"):
        p.Publication.decode_text(" " * (p.MAX_PUBLICATION_BYTES + 1))


# ------------------------------------------------------------------ verrou


def test_lock_coverage_reports_unlocked_drift_and_orphans():
    lock = p.CatalogLock((p.LockEntry("jarvis.window", 1, "a" * 64), p.LockEntry("jarvis.table", 1, "b" * 64)))
    found = {("jarvis.window", 1): "c" * 64, ("jarvis.document", 1): "d" * 64}
    codes = sorted(code for code, _ in p.check_lock_coverage(found, lock))
    assert codes == [p.LOCK_DRIFT, p.LOCK_ORPHAN, p.LOCK_UNLOCKED]
    assert p.check_lock_coverage({("jarvis.table", 1): "b" * 64}, p.CatalogLock((lock.entries[1],))) == ()


def test_lock_decode_round_trip_and_strictness():
    lock = p.CatalogLock((p.LockEntry("jarvis.window", 1, "a" * 64),))
    assert p.CatalogLock.decode_text(lock.render()) == lock
    for text in ('{"schema": "jarvis.prefab.catalog_lock", "schema_version": 1}',
                 '{"schema": "x", "schema_version": 1, "entries": []}',
                 json.dumps({"schema": p.CATALOG_LOCK_SCHEMA, "schema_version": 1,
                             "entries": [{"prefab_id": "test.counter", "version": 1, "fingerprint": "a" * 64}]}),
                 json.dumps({"schema": p.CATALOG_LOCK_SCHEMA, "schema_version": 1,
                             "entries": [lock.entries[0].to_dict()] * 2})):
        with pytest.raises(p.PrefabDefinitionError):
            p.CatalogLock.decode_text(text)


# ------------------------------------------------------------------ événements d'état (pour la Slice 04)


@pytest.fixture
def counter() -> p.PrefabManifest:
    return p.parse_candidate(candidate()).manifest


def test_state_event_ok_returns_the_merged_defaulted_data(counter):
    current = {"count": 3, "notes": "", "history": []}
    check = p.check_state_event(counter, "incremented", {"count": 4, "history": [{"delta": 1}]},
                                {"count": 3, "history": []}, current)
    assert check.outcome is p.StateEventOutcome.OK
    assert check.merged == {"count": 4, "notes": "", "history": [{"delta": 1, "ratio": 0.5}]}


def test_state_event_basis_mismatch_is_stale(counter):
    check = p.check_state_event(counter, "incremented", {"count": 4}, {"count": 2}, {"count": 3})
    assert check.outcome is p.StateEventOutcome.STALE
    # `1` et `true` ne sont pas égaux pour la comparaison du basis.
    check = p.check_state_event(counter, "incremented", {"count": 4}, {"count": True}, {"count": 1})
    assert check.outcome is p.StateEventOutcome.STALE


@pytest.mark.parametrize("event,payload,basis,needle", [
    ("missing", {"count": 1}, {"count": 0}, "not declared"),
    ("reset_requested", {"from": 1}, {}, "notify event"),
    ("incremented", {}, {}, "non-empty object"),
    ("incremented", {"notes": "x"}, {"notes": ""}, "undeclared keys"),
    ("incremented", {"count": -1}, {"count": 0}, "must be at least 0"),
    ("incremented", {"count": 1}, None, "basis must be an object"),
    ("incremented", {"history": [{"delta": 1}] * 9}, {"history": []}, "at most 8"),
])
def test_state_event_refusals(counter, event, payload, basis, needle):
    check = p.check_state_event(counter, event, payload, basis, {"count": 0, "notes": "", "history": []})
    assert check.outcome is p.StateEventOutcome.REFUSED
    assert needle in check.detail and len(check.detail) <= p.MAX_ERROR_CHARS


def test_state_event_payload_size_is_bounded(counter):
    manifest_raw = copy.deepcopy(candidate()["manifest"])
    manifest_raw["inputs"]["data"]["properties"]["notes"]["max_length"] = 12000
    manifest_raw["events"]["incremented"]["writes"].append("notes")
    manifest_raw["events"]["incremented"]["payload"]["properties"]["notes"] = {"$ref": "data.notes"}
    manifest = p.parse_manifest(manifest_raw)
    # Borne d'un événement d'état = borne de la charge d'un objet de scène (16 Kio, A5) : 9 000 octets passent.
    assert p.MAX_STATE_EVENT_PAYLOAD_BYTES == 16 * 1024 and p.MAX_NOTIFY_PAYLOAD_BYTES == 8 * 1024
    check = p.check_state_event(manifest, "incremented", {"notes": "x" * 9000}, {}, {"count": 0})
    assert check.outcome is p.StateEventOutcome.OK
    check = p.check_state_event(manifest, "incremented", {"notes": "x" * 16400}, {"notes": ""}, {"count": 0})
    assert check.outcome is p.StateEventOutcome.REFUSED and "at most 16384" in check.detail


def test_a_missing_basis_key_reads_as_null_like_a_missing_data_key(counter):
    """Reprise QA S04 F2 : une seule règle. Clé absente = `null`, dans la basis comme dans les données."""

    # Le cadre n'a jamais vu `history` et Core ne l'a pas : la première écriture passe.
    check = p.check_state_event(counter, "incremented", {"count": 4, "history": [{"delta": 1}]}, {"count": 3},
                                {"count": 3})
    assert check.outcome is p.StateEventOutcome.OK
    assert check.merged == {"count": 4, "notes": "", "history": [{"delta": 1, "ratio": 0.5}]}
    # Basis sans `count` = `null`, et Core a `count` : périmé, pas un refus.
    check = p.check_state_event(counter, "incremented", {"count": 1}, {}, {"count": 0})
    assert check.outcome is p.StateEventOutcome.STALE
    # `null` explicite et clé absente sont la même basis.
    explicit = p.check_state_event(counter, "incremented", {"history": []}, {"history": None}, {"count": 0})
    absent = p.check_state_event(counter, "incremented", {"history": []}, {}, {"count": 0})
    assert explicit.outcome is absent.outcome is p.StateEventOutcome.OK


@pytest.mark.parametrize("detail, paths", [
    ("win: invalid_definition: x.y@1: props.accent: must be a #rrggbb colour, got 'sk-hunter2'",
     ["props.accent"]),
    ("data.items[3].label: exceeds 200 characters; data.count: expected a finite integer, got True",
     ["data.items[3].label", "data.count"]),
    ("props.mode: must be one of ['a', 'b'], got 'data.secret'", ["props.mode"]),
    ("props.mode: must be one of ['a'], got 'data.secret-cut-by-a-trunc…", ["props.mode"]),
    ("payload.note: got \"it's data.inside\"; basis.count must contain finite JSON values only",
     ["payload.note", "basis.count"]),
])
def test_detail_paths_name_inputs_never_values(detail, paths):
    assert p.detail_paths(detail) == paths


# ------------------------------------------------------------------ rework S2 (constats QA)


def test_state_event_with_a_non_finite_basis_is_a_bounded_refusal(counter):
    check = p.check_state_event(counter, "incremented", {"count": 4}, {"count": float("nan")}, {"count": 3})
    assert check.outcome is p.StateEventOutcome.REFUSED
    assert "basis" in check.detail and len(check.detail) <= p.MAX_ERROR_CHARS


def nested_ref_event(levels: int) -> dict:
    """Un événement notify dont le `$ref` vers `data.history` (profondeur 2) est posé au niveau `levels`."""

    node: dict = {"$ref": "data.history"}
    for _ in range(levels):
        node = {"type": "object", "properties": {"x": node}}
    return {"deep": {"class": "notify", "payload": node}}


def test_ref_depth_counts_the_inlined_subtree():
    p.parse_candidate(candidate(events=nested_ref_event(2)))  # 2 + 2 = 4 : accepté
    errors = event_errors(nested_ref_event(3))  # 3 + 2 = 5 : la profondeur effective dépasse 4
    assert any("$ref 'data.history'" in item and "depth 4" in item for item in errors), errors


@pytest.mark.parametrize("build", [
    lambda: publication("revision", version=2, derived=p.PrefabRef("test.counter", 2)),
    lambda: publication("revision", version=2, derived=p.PrefabRef("test.counter", 5)),
    lambda: publication("base_edit", "jarvis.window", 2, p.PrefabRef("jarvis.window", 3),
                        p.BaseEditRecord("make the checklist bigger please", "conversation_event:e"), actor="brain"),
])
def test_a_revision_derives_from_an_earlier_version(build):
    with pytest.raises(p.PrefabDefinitionError, match="earlier version"):
        build()


def test_a_bundle_within_its_file_bounds_is_always_fingerprintable():
    raw = candidate()
    # Pire cas de l'échappement JSON : un caractère de contrôle (1 octet) devient `\u0001` (6 octets).
    bundle = p.parse_bundle(raw["manifest"], "\x01" * p.MAX_TEMPLATE_BYTES, "\x01" * p.MAX_STYLE_BYTES,
                            "\x01" * p.MAX_BEHAVIOR_BYTES)
    assert len(bundle.fingerprint()) == 64


@pytest.mark.parametrize("template", ['<img title=">" onerror=x>', "<img alt='a>b' onload=go()>",
                                      '<a title="x"onclick=1>'])
def test_lint_handler_check_survives_a_quoted_greater_than(template):
    assert any("on*=" in item for item in p.lint_sources(template, "", ""))


def test_lint_handler_check_ignores_handler_text_inside_a_quoted_value():
    assert p.lint_sources('<p title="onclick=1">x</p>', "", "") == ()


@pytest.mark.parametrize("style,refused", [
    ('.a{background:image-set("https://x/a.png" 1x)}', True),
    (".a{background:-webkit-image-set('http://x/a.png' 1x, 'data:image/png;base64,AA==' 2x)}", True),
    ('.a{background:IMAGE-SET( "x.png" 1x)}', True),
    ('.a{background:image-set("data:image/png;base64,AA==" 1x, url(data:image/png;base64,AA==) 2x)}', False),
    ('.a{background:image-set("data:image/avif;base64,AA==" type("image/avif"))}', False),
])
def test_lint_style_image_set(style, refused):
    assert bool(p.lint_sources("", style, "")) is refused


def test_lint_reports_an_iframe_pair_once():
    errors = p.lint_sources("<iframe src='x'></iframe>", "", "")
    assert sum("<iframe>" in item for item in errors) == 1


def test_clip_message_is_the_one_truncation_rule():
    assert p.clip_message("x" * p.MAX_ERROR_CHARS) == "x" * p.MAX_ERROR_CHARS
    clipped = p.clip_message("x" * (p.MAX_ERROR_CHARS + 5))
    assert len(clipped) == p.MAX_ERROR_CHARS and clipped.endswith("…")

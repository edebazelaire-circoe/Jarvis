"""Partition du Studio : modèle pur, validations, déterminisme (jarvis-interactive-presentation-studio, Slice 10).

Aucune E/S. Contrat : `docs/presentation-studio.md` › *Score and cue contract*. Données : `tests/fakes/presentation_studio_score.py`
(12 scènes, partition mixte avec une séquence verrouillée) et `tests/fixtures/presentation_studio/score.full12.json`.
"""

from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path
import typing

import pytest

from jarvis.domain import presentation_studio as ps
from jarvis.domain import presentation_studio_score as sc
from jarvis.domain.prefab import canonical_json
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_scene import ControlBounds, ScoreAnchor, StudioControl, StudioScene
from tests.fakes import presentation_studio_score as data
from tests.fakes.presentation_studio_score import cue_id, item_id, scene_id

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "presentation_studio"


def refused(document, code: C = C.INVALID_PRESENTATION, match: str | None = None) -> PresentationStudioError:
    with pytest.raises(PresentationStudioError) as caught:
        sc.parse_score(document)
    assert caught.value.code is code, caught.value
    if match:
        assert match in caught.value.message, caught.value.message
    return caught.value


def edit(mutate):
    """Document complet modifié par `mutate(doc)` : une seule altération par test."""

    doc = copy.deepcopy(data.document())
    mutate(doc)
    return doc


def item_of(doc, n: int) -> dict:
    return next(i for i in doc["items"] if i["item_id"] == item_id(n))


# ------------------------------------------------------------------ la partition complète

def test_the_full_presentation_is_an_inspectable_score_of_twelve_scenes():
    score = data.score()
    assert len(data.scenes()) == 12 and len({i.scene_id for i in score.items}) == 12
    presenters = {i.presenter for i in score.items}
    assert presenters == {sc.Presenter.USER, sc.Presenter.JARVIS, sc.Presenter.NONE}
    assert [i.kind for i in score.items].count(sc.ItemKind.SILENCE) == 3
    assert len(score.sequences) == 1 and score.sequences[0].sequence_id == "demo"
    assert [i.item_id for i in score.chain()] == [i.item_id for i in score.items]  # authored order = graph order
    assert sc.check_score(score, data.scenes()) == []


def test_the_committed_fixture_is_exactly_what_the_builder_writes():
    text = (FIXTURES / "score.full12.json").read_text(encoding="utf-8")
    assert text.replace("\r\n", "\n") == ps.dump_document(data.score().to_document())
    assert canonical_json(json.loads(text)) == data.score().canonical()


def test_the_canonical_json_round_trips_and_ignores_key_order():
    score = data.score()
    again = sc.parse_score(json.loads(score.canonical()))
    assert again.canonical() == score.canonical()
    shuffled = json.loads(json.dumps(data.document(), sort_keys=True))  # same content, other key order
    assert sc.parse_score(shuffled).canonical() == score.canonical()
    assert sc.parse_score(json.loads(ps.dump_document(score.to_document()))).canonical() == score.canonical()


def test_the_order_is_the_item_graph_not_a_clock():
    score = data.score()
    order = score.playback_order()
    assert order[:9] == tuple(item_id(n) for n in range(1, 10))
    assert order[9:11] == (item_id(8), item_id(9))  # the declared loop, once
    assert order[11:] == tuple(item_id(n) for n in (10, 11, 12))
    # durations are soft targets summed over the expanded order; an item without a target counts 0
    assert score.estimated_duration_ms() == 8000 + 4000 + 9000
    # no timestamp-like field on an item: ordering never depends on a wall clock
    assert not any("at" == f.name or f.name.endswith("_at") or f.name.startswith("start_ms")
                   for f in dataclasses.fields(sc.ScoreItem))


def test_tracks_are_inspectable_views_with_explicit_silence():
    score = data.score()
    jarvis = score.track(sc.Track.JARVIS_SPEECH)
    assert [e["item_id"] for e in jarvis if e.get("silence")] == [item_id(3), item_id(7), item_id(12)]
    assert all("text" not in e and "note" not in e for e in jarvis if e.get("silence"))
    assert {e["item_id"] for e in score.track(sc.Track.USER_SPEECH)} == {item_id(n) for n in (2, 5, 8, 10)}
    assert [e["item_id"] for e in score.track(sc.Track.CUES)] == [item_id(2), item_id(4), item_id(8)]
    assert [e["armable"] for e in score.track(sc.Track.CUES)] == [True, False, True]
    assert [e["item_id"] for e in score.track(sc.Track.MOTION)] == [item_id(3)]
    assert next(e for e in jarvis if e["item_id"] == item_id(6))["sequence_id"] == "demo"


def test_a_cue_resolves_to_its_item_from_canonical_state():
    score = data.score()
    assert score.resolve_cue(cue_id(1)).item_id == item_id(2)
    assert score.resolve_cue("psc_ffffffffffff") is None


# ------------------------------------------------------------------ silence

def test_silence_is_a_first_class_state_validated_as_such():
    silent = sc.ScoreItem(item_id(1), scene_id(1), "none", "silence", label="pause")
    assert silent.presenter is sc.Presenter.NONE and silent.kind is sc.ItemKind.SILENCE and not silent.text
    for extra in ({"text": "bonjour"}, {"note": "say something"}):
        with pytest.raises(PresentationStudioError, match="silence item carries no speech"):
            sc.ScoreItem(item_id(1), scene_id(1), "none", "silence", **extra)
    with pytest.raises(PresentationStudioError, match="exactly presenter none"):
        sc.ScoreItem(item_id(1), scene_id(1), "none", "speech")
    with pytest.raises(PresentationStudioError, match="exactly presenter none"):
        sc.ScoreItem(item_id(1), scene_id(1), "jarvis", "silence", text="x")


def test_a_silence_item_may_still_act_visually_and_keeps_a_soft_target():
    doc = data.document()
    three = item_of(doc, 3)
    assert three["motion"] and three["target_duration_ms"] == 4000 and three["presenter"] == "none"
    assert sc.parse_score(doc).item(item_id(3)).motion[0].kind is sc.ActionKind.CONTROL_SET


@pytest.mark.parametrize("fields", [{"text": "", "note": ""}, {"text": "a", "note": "b"}])
def test_a_speaking_item_needs_exactly_one_of_text_or_note(fields):
    with pytest.raises(PresentationStudioError, match="exactly one of text or note"):
        sc.ScoreItem(item_id(1), scene_id(1), "jarvis", "speech", **fields)


def test_only_a_jarvis_presenter_can_hold_jarvis_speech_in_a_locked_sequence():
    def with_presenter(presenter, kind="speech", note=""):
        def mutate(doc):
            item = item_of(doc, 6)
            item.update(presenter=presenter, kind=kind, note=note)
        return edit(mutate)

    refused(with_presenter("user", note="intent"), match="only a jarvis presenter speaks as Jarvis")
    refused(with_presenter("none", kind="silence"), match="only a jarvis presenter speaks as Jarvis")
    # a jarvis host with an all-silent sequence is a contradiction too
    def quiet(doc):
        for step in doc["sequences"][0]["steps"]:
            step.update(speaker="none", text="")
    refused(edit(quiet), match="needs a Jarvis step")


def test_a_user_step_in_a_locked_sequence_is_refused_and_a_user_host_needs_an_intention():
    with pytest.raises(PresentationStudioError, match="never the user"):
        sc.SequenceStep("s", 0, "user", "hi")
    def user_host(doc):
        item_of(doc, 6).update(presenter="user")
        for step in doc["sequences"][0]["steps"]:
            step.update(speaker="none", text="")
    refused(edit(user_host), match="needs a note")


# ------------------------------------------------------------------ cues

def test_a_cue_predicate_is_a_normalised_finite_phrase_set():
    one = sc.CuePredicate(("  Voilà   LE Plan ", "Next Topic"), ("topic_b", "topic_a"))
    two = sc.CuePredicate(("next topic", "voilà le plan"), ("topic_a", "topic_b"))
    assert one == two and one.phrases == ("next topic", "voilà le plan") and one.semantics == ("topic_a", "topic_b")
    assert sc.normalise_phrase(sc.normalise_phrase("L’Été  ÉTAIT Là")) == sc.normalise_phrase("L’Été  ÉTAIT Là") == "l'été était là"
    with pytest.raises(PresentationStudioError, match="same phrase twice"):
        sc.CuePredicate(("Next topic", "next  TOPIC"))


@pytest.mark.parametrize("phrase", [
    ".*", "(a|b)", "^start$", "a+b", "[abc]", "next\\d", "{\"tool\": \"x\"}", "run: delete everything", "a;b", "x=1",
    "$(rm)", "<b>", "tool(\"x\")", "a/b", "", "a", "-", "'", "one two three four five six seven eight nine",
    "x" * 61, "​hidden", "emoji \U0001f600"])
def test_a_cue_phrase_is_never_a_pattern_a_tool_instruction_or_unbounded(phrase):
    with pytest.raises(PresentationStudioError):
        sc.CuePredicate((phrase,))


def test_whitespace_controls_in_a_phrase_collapse_to_one_space():
    assert sc.CuePredicate(("line\nbreak", "tab\there")).phrases == ("line break", "tab here")


def test_cue_predicate_bounds_and_types():
    sc.CuePredicate(tuple(f"phrase {n}" for n in range(sc.MAX_PHRASES)))
    with pytest.raises(PresentationStudioError, match="exceed"):
        sc.CuePredicate(tuple(f"phrase {n}" for n in range(sc.MAX_PHRASES + 1)))
    with pytest.raises(PresentationStudioError, match="exceed"):
        sc.CuePredicate((), tuple(f"topic_{n}" for n in range(sc.MAX_SEMANTICS + 1)))
    for bad in (("Bad Label",), ("1abc",), ("a-b",), ("",)):
        with pytest.raises(PresentationStudioError):
            sc.CuePredicate((), bad)
    with pytest.raises(PresentationStudioError):
        sc.CuePredicate(("ok phrase", 5))  # type: ignore[arg-type]
    with pytest.raises(PresentationStudioError):
        sc.CuePredicate("abc")  # type: ignore[arg-type]


def test_armable_needs_a_predicate_and_a_manual_cue_may_be_empty():
    sc.CueDefinition(cue_id(9), "manual", sc.CuePredicate(), False)
    with pytest.raises(PresentationStudioError, match="armable but its predicate is empty"):
        sc.CueDefinition(cue_id(9), "x", sc.CuePredicate(), True)
    with pytest.raises(PresentationStudioError, match="armable must be a boolean"):
        sc.CueDefinition(cue_id(9), "x", sc.CuePredicate(("go",)), 1)  # type: ignore[arg-type]


def test_cue_references_resolve_and_each_cue_names_exactly_one_item():
    def unknown(doc):
        item_of(doc, 5)["cue_id"] = cue_id(77)
    refused(edit(unknown), match="is not defined by the score")

    def shared(doc):
        item_of(doc, 5)["cue_id"] = cue_id(1)
    refused(edit(shared), match="cue use")

    def orphan(doc):
        doc["cues"].append({"cue_id": cue_id(4), "label": "never used", "armable": False})
    refused(edit(orphan), match="used by no item")

    def twice(doc):
        doc["cues"].append(copy.deepcopy(doc["cues"][0]))
    refused(edit(twice), match="cue_id appears twice")


def test_a_cue_carries_no_text_beyond_its_label_and_predicate():
    doc = data.document()
    cue = doc["cues"][0]
    for key in ("tool", "command", "action", "args", "regex", "pattern", "execute", "prompt"):
        refused(edit(lambda d, key=key: d["cues"][0].update({key: "x"})), match="unknown keys")
    refused(edit(lambda d: d["cues"][0]["predicate"].update({"regex": ".*"})), match="unknown keys")
    assert set(cue) == {"cue_id", "label", "armable", "predicate"}


# ------------------------------------------------------------------ actions : ensemble clos

def test_the_action_set_is_closed_and_every_kind_is_reversible():
    assert {k.value for k in sc.ActionKind} == {"control_set", "scene_goto", "reveal", "hide", "sequence"}
    assert sc.ActionRef.reversible is True
    for bad in ("tool_call", "shell", "mcp", "http", "speak", "", None):
        with pytest.raises(PresentationStudioError):
            sc.ActionRef(bad)  # type: ignore[arg-type]
    assert set(sc._SHAPE) == set(sc.ActionKind)  # one shape row per kind: adding a kind forces a decision here


@pytest.mark.parametrize("raw", [
    {"kind": "control_set", "scene_id": scene_id(1), "control_id": "glow"},                       # no value
    {"kind": "control_set", "scene_id": scene_id(1), "value": 1},                                  # no control
    {"kind": "scene_goto"},                                                                        # no scene
    {"kind": "scene_goto", "scene_id": scene_id(1), "control_id": "glow"},                         # foreign field
    {"kind": "reveal", "scene_id": scene_id(1)},                                                   # no anchor
    {"kind": "hide", "scene_id": scene_id(1), "anchor_id": "Bad-Id"},                              # slug
    {"kind": "sequence"}, {"kind": "sequence", "sequence_id": "demo", "value": 1},
    {"kind": "scene_goto", "scene_id": "pss_XYZ"},
    {"kind": "scene_goto", "scene_id": scene_id(1), "tool": "delete_everything"},                  # unknown key
    {"kind": "scene_goto", "scene_id": scene_id(1), "command": "rm -rf"},
    {"kind": "scene_goto", "scene_id": scene_id(1), "args": {"a": 1}},
])
def test_an_invalid_action_is_refused_before_anything_can_hold_it(raw):
    with pytest.raises(PresentationStudioError):
        sc.ActionRef.from_dict(raw)


@pytest.mark.parametrize("value", [[1], {"a": 1}, None, float("nan"), float("inf"), "x" * 201, " pad", "line\nbreak", object()])
def test_a_control_value_is_a_bounded_scalar_never_a_structure(value):
    with pytest.raises(PresentationStudioError):
        sc.ActionRef(sc.ActionKind.CONTROL_SET, scene_id(1), "glow", value=value)


@pytest.mark.parametrize("value", [True, 0, 7, 2.5, "#ff8800", "texte"])
def test_a_control_value_scalar_is_accepted(value):
    assert sc.ActionRef(sc.ActionKind.CONTROL_SET, scene_id(1), "glow", value=value).value == value


def test_actions_are_compared_by_canonical_json_never_by_equality():
    one = sc.ActionRef(sc.ActionKind.CONTROL_SET, scene_id(1), "glow", value=1)
    true = sc.ActionRef(sc.ActionKind.CONTROL_SET, scene_id(1), "glow", value=True)
    assert one == true  # Python equality conflates them...
    assert one.key() != true.key()  # ...the stored form does not
    sc.ScoreItem(item_id(1), scene_id(1), "none", "silence", motion=(one, true))  # two different actions, not a duplicate
    with pytest.raises(PresentationStudioError, match="same action twice"):
        sc.ScoreItem(item_id(1), scene_id(1), "none", "silence", motion=(one, one))


def test_a_sequence_cannot_start_another_sequence_or_hide_in_the_motion_track():
    seq = sc.ActionRef(sc.ActionKind.SEQUENCE, sequence_id="demo")
    with pytest.raises(PresentationStudioError, match="cannot start a locked sequence"):
        sc.SequenceStep("s", 0, visual=(seq,))
    with pytest.raises(PresentationStudioError, match="cannot start a locked sequence"):
        sc.ScoreItem(item_id(1), scene_id(1), "none", "silence", motion=(seq,))


def test_nothing_in_the_model_can_hold_free_text_that_would_be_executed():
    """Structural guard: every `str` field of every model class is classified, as an id/enum or as non-executed text."""

    assert {c.__name__ for c in sc.MODEL_CLASSES} == set(sc.STRUCTURE_FIELDS)
    for cls in sc.MODEL_CLASSES:
        name = cls.__name__
        for field in dataclasses.fields(cls):
            places = [registry for registry in (sc.FREE_TEXT_FIELDS, sc.ID_FIELDS, sc.STRUCTURE_FIELDS)
                      if field.name in registry.get(name, frozenset())]
            assert len(places) == 1, f"{name}.{field.name} must be classified exactly once, whatever its annotation"
    # the free-text set is exactly: spoken, shown, matched, or written as a control value
    assert sc.FREE_TEXT_FIELDS == {
        "ScoreItem": {"label", "text", "note"}, "CueDefinition": {"label"}, "CuePredicate": {"phrases"},
        "SequenceStep": {"text"}, "LockedSequence": {"label"}, "RecoveryPoint": {"label"}, "ActionRef": {"value"}}


def test_no_model_field_names_a_tool_command_or_script():
    names = {f.name for cls in sc.MODEL_CLASSES for f in dataclasses.fields(cls)}
    assert not names & {"tool", "tools", "command", "commands", "script", "code", "html", "js", "args", "arguments",
                        "shell", "url", "endpoint", "prompt", "instruction", "regex", "pattern", "eval"}


def test_an_action_takes_effect_only_through_ids_the_variant_declares():
    score = data.score()
    wrong_scene = edit(lambda d: item_of(d, 1)["visual"].__setitem__(0, {"kind": "reveal", "scene_id": scene_id(99),
                                                                          "anchor_id": "callout"}))
    problems = sc.check_score(sc.parse_score(wrong_scene), data.scenes())
    assert any("scene pss_000000000063 is not a scene of this variant" in p for p in problems)
    assert sc.check_score(score, data.scenes()[:5])  # a shorter variant leaves dangling references, all reported
    assert len(sc.check_score(score, ())) <= sc.MAX_CHECK_ERRORS


# ------------------------------------------------------------------ références contre la variante

def test_every_reference_must_resolve_in_the_variant():
    def cases(mutate):
        return sc.check_score(sc.parse_score(edit(mutate)), data.scenes())

    assert any("control nope is not declared" in p for p in cases(
        lambda d: item_of(d, 8)["visual"].__setitem__(0, {"kind": "control_set", "scene_id": scene_id(8),
                                                           "control_id": "nope", "value": 1})))
    assert any("anchor missing is not declared" in p for p in cases(
        lambda d: item_of(d, 5)["visual"].__setitem__(0, {"kind": "reveal", "scene_id": scene_id(5),
                                                           "anchor_id": "missing"})))
    assert any("is not a scene of this variant" in p for p in cases(lambda d: item_of(d, 4).update(
        scene_id=scene_id(40), visual=[{"kind": "scene_goto", "scene_id": scene_id(40)}])))


def test_a_sequence_step_action_is_validated_like_an_item_action():
    problems = sc.check_score(sc.parse_score(edit(
        lambda d: d["sequences"][0]["steps"][1]["motion"].__setitem__(
            0, {"kind": "control_set", "scene_id": scene_id(6), "control_id": "glow", "value": 99}))), data.scenes())
    assert any("sequence demo step glow_up" in p and "above the curated maximum 10" in p for p in problems)


def test_control_values_respect_the_curated_bounds_and_the_control_type():
    def set_glow(value, scene=8, track="motion"):
        def mutate(d):
            item_of(d, 3)[track] = [{"kind": "control_set", "scene_id": scene_id(scene), "control_id": "glow", "value": value}]
        return sc.check_score(sc.parse_score(edit(mutate)), data.scenes())

    assert set_glow(5) == [] and set_glow(0) == [] and set_glow(10) == []
    assert any("above the curated maximum" in p for p in set_glow(10.5))
    assert any("below the curated minimum" in p for p in set_glow(-1))
    assert any("own type" in p for p in set_glow("loud"))
    assert any("own type" in p for p in set_glow(True))  # a boolean is not a number
    assert any("belongs on the motion track" in p for p in set_glow(5, track="visual"))


def test_a_control_choices_and_string_length_are_checked_without_a_manifest():
    scene = StudioScene(scene_id(1), data.scenes()[0].prefab, props={"mode": "compact"},
                        controls=(StudioControl("mode", "props.mode", "Mode", "layout",
                                                bounds=ControlBounds(choices=("compact", "wide"))),
                                  StudioControl("name", "props.name", "Name", "content", default="x",
                                                bounds=ControlBounds(max_length=5))))

    def run(control, value):
        item = sc.ScoreItem(item_id(1), scene_id(1), "none", "silence",
                            visual=(sc.ActionRef("control_set", scene_id(1), control, value=value),))
        score = sc.Score(data.SCORE_ID, data.PRESENTATION, data.VARIANT, item.item_id, (item,), (), (), (), 1,
                         data.STAMP, data.STAMP)
        return sc.check_score(score, (scene,))

    assert run("mode", "wide") == [] and any("curated choices" in p for p in run("mode", "huge"))
    assert run("name", "short") == [] and any("exceeds 5 characters" in p for p in run("name", "toolongname"))


# ------------------------------------------------------------------ graphe : chaîne, boucles, cycles

def test_the_item_graph_is_one_chain_cycles_are_refused():
    def cycle(doc):
        item_of(doc, 12)["next_item_id"] = item_id(1)
    refused(edit(cycle), match="cycle")

    def inner_cycle(doc):
        item_of(doc, 4)["next_item_id"] = item_id(2)  # 2 -> 3 -> 4 -> 2 while 1 -> 2 : two items lead to 2
    refused(edit(inner_cycle), match="two items lead to the same next item")

    def detached_cycle(doc):
        item_of(doc, 3)["next_item_id"] = item_id(2)  # 2 -> 3 -> 2, the rest is cut off
        item_of(doc, 1)["next_item_id"] = None
    refused(edit(detached_cycle), match="not reachable")

    def self_next(doc):
        item_of(doc, 5)["next_item_id"] = item_id(5)
    with pytest.raises(PresentationStudioError, match="own next item"):
        sc.parse_score(edit(self_next))


def test_unreachable_dangling_and_duplicate_items_are_refused():
    refused(edit(lambda d: item_of(d, 5).update(next_item_id=None)), match="not reachable")
    refused(edit(lambda d: item_of(d, 5).update(next_item_id=item_id(200))), match="not an item of the score")
    refused(edit(lambda d: d.update(start_item_id=item_id(200))), match="start_item_id must name")
    refused(edit(lambda d: d["items"].append(copy.deepcopy(d["items"][0]))), match="item_id appears twice")
    refused(edit(lambda d: d.update(start_item_id=None)), match="start_item_id must name")


def test_an_empty_score_is_valid_and_needs_no_start():
    doc = edit(lambda d: d.update(start_item_id=None, items=[], cues=[], sequences=[], recovery_points=[]))
    score = sc.parse_score(doc)
    assert score.chain() == () and score.playback_order() == () and score.estimated_duration_ms() == 0
    refused(edit(lambda d: d.update(start_item_id=item_id(1), items=[], cues=[], sequences=[], recovery_points=[])),
            match="empty")


def test_a_loop_is_the_only_repetition_it_is_bounded_and_goes_backwards():
    score = data.score()
    assert score.item(item_id(9)).loop == sc.LoopSpec(item_id(8), 1)
    refused(edit(lambda d: item_of(d, 8).update(loop={"to_item_id": item_id(9), "max_repeats": 1})), match="never forward")
    refused(edit(lambda d: item_of(d, 9).update(loop={"to_item_id": item_id(8), "max_repeats": 0})))
    refused(edit(lambda d: item_of(d, 9).update(loop={"to_item_id": item_id(8), "max_repeats": sc.MAX_LOOP_REPEATS + 1})))
    refused(edit(lambda d: item_of(d, 9).update(loop={"to_item_id": item_id(222), "max_repeats": 1})), match="loop target")
    # a loop on itself repeats one item N times
    again = sc.parse_score(edit(lambda d: item_of(d, 5).update(loop={"to_item_id": item_id(5), "max_repeats": 3})))
    assert again.playback_order().count(item_id(5)) == 4


def test_nested_loops_expand_deterministically_and_runaway_expansion_is_refused():
    def chain(count: int, loops: dict[int, tuple[int, int]]):
        items = []
        for n in range(1, count + 1):
            raw = {"item_id": item_id(n), "scene_id": scene_id(1), "presenter": "none", "kind": "silence",
                   "next_item_id": item_id(n + 1) if n < count else None}
            if n in loops:
                raw["loop"] = {"to_item_id": item_id(loops[n][0]), "max_repeats": loops[n][1]}
            items.append(raw)
        return {"start_item_id": item_id(1), "items": items, "cues": [], "sequences": [], "recovery_points": []}

    def build(count, loops):
        return sc.parse_score(data.document(**chain(count, loops)))

    nested = build(3, {2: (2, 1), 3: (1, 1)})
    assert nested.playback_order() == tuple(item_id(n) for n in (1, 2, 2, 3, 1, 2, 2, 3))
    assert nested.playback_order() == build(3, {2: (2, 1), 3: (1, 1)}).playback_order()  # same input, same order
    # 4 nested loops of 8 repeats each blow the expansion bound and are refused as a whole
    with pytest.raises(PresentationStudioError, match="expand beyond"):
        build(4, {1: (1, 8), 2: (1, 8), 3: (1, 8), 4: (1, 8)})


# ------------------------------------------------------------------ séquences verrouillées

def test_locked_sequence_offsets_are_deterministic():
    one, two = data.score().sequence("demo"), sc.parse_score(data.document()).sequence("demo")
    assert one.timeline() == two.timeline() == ((0, "intro"), (3000, "glow_up"), (6500, "wrap"))
    shuffled = json.loads(json.dumps(data.document(), sort_keys=True))
    assert sc.parse_score(shuffled).sequence("demo").timeline() == one.timeline()
    assert sc.LockedSequence.from_dict(one.to_dict()) == one


@pytest.mark.parametrize("offsets", [[0, 3000, 3000], [0, 6500, 3000], [1, 3000, 6500], [0, 3000, 9000], [0, 3000, 99999]])
def test_step_offsets_start_at_zero_strictly_increase_and_end_inside_the_duration(offsets):
    def mutate(doc):
        for step, offset in zip(doc["sequences"][0]["steps"], offsets):
            step["offset_ms"] = offset
    refused(edit(mutate))


def test_a_locked_segment_has_one_exact_length_and_one_host():
    refused(edit(lambda d: item_of(d, 6).update(target_duration_ms=8000)), match="must equal its sequence duration_ms")
    refused(edit(lambda d: item_of(d, 6).update(target_duration_ms=None)), match="needs target_duration_ms")
    refused(edit(lambda d: item_of(d, 6).update(timing="soft")), match="exactly an item that starts a locked sequence")
    refused(edit(lambda d: item_of(d, 5).update(timing="locked", target_duration_ms=5000)),
            match="exactly an item that starts a locked sequence")
    refused(edit(lambda d: item_of(d, 6).update(interruption="allow")), match="cannot allow interruption")
    refused(edit(lambda d: item_of(d, 6).update(text="spoken twice")), match="speaks through its steps")

    def two_hosts(doc):
        item_of(doc, 8)["visual"].append({"kind": "sequence", "sequence_id": "demo"})
        item_of(doc, 8).update(timing="locked", interruption="refuse", target_duration_ms=9000)
    refused(edit(two_hosts), match="started by two items")

    refused(edit(lambda d: item_of(d, 6).update(visual=[], timing="soft")), match="exactly one of text or note")

    def unknown(doc):
        item_of(doc, 6)["visual"] = [{"kind": "sequence", "sequence_id": "nope"}]
    refused(edit(unknown), match="unknown locked sequence")

    def two_in_one(doc):
        item_of(doc, 6)["visual"].append({"kind": "sequence", "sequence_id": "other"})
    refused(edit(two_in_one), match="more than one locked sequence")


def test_interruption_policy_and_recovery_of_a_sequence_are_declared():
    base = data.score().sequence("demo")
    assert base.on_interrupt is sc.SequenceInterrupt.PAUSE_RESUME and base.recovery_id is None

    def abort(doc):
        doc["sequences"][0].update(on_interrupt="abort_to_recovery", recovery_id="opening")
    assert sc.parse_score(edit(abort)).sequence("demo").recovery_id == "opening"

    def abort_unknown(doc):
        doc["sequences"][0].update(on_interrupt="abort_to_recovery", recovery_id="nowhere")
    refused(edit(abort_unknown), match="unknown recovery point")
    refused(edit(lambda d: d["sequences"][0].update(on_interrupt="abort_to_recovery")), match="needs a recovery_id")
    refused(edit(lambda d: d["sequences"][0].update(recovery_id="opening")), match="forbids one")
    refused(edit(lambda d: d["sequences"][0].update(on_interrupt="ignore")), match="must be one of")


def test_a_sequence_step_does_something_and_a_silent_step_has_no_text():
    with pytest.raises(PresentationStudioError, match="does nothing"):
        sc.SequenceStep("s", 0)
    with pytest.raises(PresentationStudioError, match="required for a Jarvis step"):
        sc.SequenceStep("s", 0, "jarvis", "")
    with pytest.raises(PresentationStudioError, match="forbidden for a silent one"):
        sc.SequenceStep("s", 0, "none", "words", visual=(sc.ActionRef("scene_goto", scene_id(1)),))
    refused(edit(lambda d: d["sequences"].append(copy.deepcopy(d["sequences"][0]))), match="appears twice")
    refused(edit(lambda d: d["sequences"][0]["steps"].append(copy.deepcopy(d["sequences"][0]["steps"][0]))),
            match="step_id appears twice")


def test_a_sequence_started_by_no_item_is_refused():
    def orphan(doc):
        extra = copy.deepcopy(doc["sequences"][0])
        extra["sequence_id"] = "lonely"
        doc["sequences"].append(extra)
    refused(edit(orphan), match="started by no item")


# ------------------------------------------------------------------ reprise

def test_recovery_points_resolve():
    refused(edit(lambda d: d["recovery_points"][0].update(item_id=item_id(99))), match="names an item the score does not hold")
    refused(edit(lambda d: item_of(d, 10).update(recovery_point_id="nowhere")), match="unknown recovery point")
    refused(edit(lambda d: item_of(d, 10).update(recovery="restart_item")), match="forbid one")
    refused(edit(lambda d: item_of(d, 11).update(recovery="recovery_point")), match="needs a recovery_point_id")
    refused(edit(lambda d: d["recovery_points"].append(copy.deepcopy(d["recovery_points"][0]))), match="recovery_id appears twice")
    for policy in sc.Recovery:
        assert policy.value in {"continue_item", "restart_item", "skip_to_next", "recovery_point"}


# ------------------------------------------------------------------ bornes et sérialisation

def test_every_collection_and_text_is_bounded():
    def many_items(doc):
        items = []
        for n in range(1, sc.MAX_ITEMS + 2):
            items.append({"item_id": item_id(n), "scene_id": scene_id(1), "presenter": "none", "kind": "silence",
                          "next_item_id": item_id(n + 1) if n <= sc.MAX_ITEMS else None})
        doc.update(start_item_id=item_id(1), items=items, cues=[], sequences=[], recovery_points=[])
    refused(edit(many_items), match="exceed")

    refused(edit(lambda d: item_of(d, 1).update(text="x" * (sc.MAX_TEXT_CHARS + 1))))
    refused(edit(lambda d: item_of(d, 2).update(note="x" * (sc.MAX_NOTE_CHARS + 1))))
    refused(edit(lambda d: item_of(d, 1).update(label="x" * (sc.MAX_LABEL + 1))))
    refused(edit(lambda d: item_of(d, 1).update(text="two\nlines")))
    refused(edit(lambda d: item_of(d, 1).update(text=" padded")))
    refused(edit(lambda d: item_of(d, 1).update(text="\ud800")))
    refused(edit(lambda d: item_of(d, 1).update(target_duration_ms=0)))
    refused(edit(lambda d: item_of(d, 1).update(target_duration_ms=sc.MAX_DURATION_MS + 1)))
    refused(edit(lambda d: item_of(d, 1).update(target_duration_ms=1.5)))
    refused(edit(lambda d: item_of(d, 1).update(target_duration_ms=True)))
    refused(edit(lambda d: item_of(d, 1).update(visual=[{"kind": "scene_goto", "scene_id": scene_id(n)} for n in range(1, 6)])),
            match="exceed")
    sc.parse_score(edit(lambda d: item_of(d, 1).update(text="x" * sc.MAX_TEXT_CHARS)))
    refused(edit(lambda d: d.update(sequences=d["sequences"] * (sc.MAX_SEQUENCES + 1))), match="exceed")
    refused(edit(lambda d: d.update(recovery_points=d["recovery_points"] * 17)), match="exceed")


@pytest.mark.parametrize("level", ["document", "item", "cue", "predicate", "sequence", "step", "recovery", "action", "loop"])
def test_an_unknown_key_is_refused_at_every_level(level):
    def mutate(doc):
        target = {"document": doc, "item": item_of(doc, 1), "cue": doc["cues"][0],
                  "predicate": doc["cues"][0]["predicate"], "sequence": doc["sequences"][0],
                  "step": doc["sequences"][0]["steps"][0], "recovery": doc["recovery_points"][0],
                  "action": item_of(doc, 1)["visual"][0], "loop": item_of(doc, 9)["loop"]}[level]
        target["surprise"] = 1
    refused(edit(mutate), match="unknown keys")


def test_runtime_state_keys_get_their_own_code():
    for key in ("position", "playback_state", "reveal_progress", "detour", "cursor"):
        refused(edit(lambda d, key=key: item_of(d, 1).update({key: 1})), C.RUNTIME_STATE_REFUSED)


def test_missing_keys_wrong_types_and_ids_are_refused():
    refused(edit(lambda d: d.pop("items")), match="missing keys")
    refused(edit(lambda d: d.update(items="nope")))
    refused(edit(lambda d: d.update(score_id="psr_XYZ")))
    refused(edit(lambda d: d.update(score_id="psi_000000000001")))
    refused(edit(lambda d: d.update(presentation_id="pst_1")))
    refused(edit(lambda d: d.update(revision=0)))
    refused(edit(lambda d: d.update(created_at="yesterday")))
    refused(edit(lambda d: item_of(d, 1).update(scene_id="pss_1")))
    refused(edit(lambda d: item_of(d, 1).update(presenter="robot")), match="must be one of")
    refused(edit(lambda d: item_of(d, 1).update(timing="elastic")), match="must be one of")
    refused(edit(lambda d: item_of(d, 1).update(interruption="never")), match="must be one of")
    refused([], match="JSON object")


def test_the_score_document_is_versioned_and_a_newer_one_is_refused_untouched():
    doc = data.document()
    assert doc["schema"] == ps.SCHEMA_SCORE == "jarvis.presentation_studio.score" and doc["schema_version"] == 1
    assert ps.CURRENT_VERSIONS[ps.SCHEMA_SCORE] == ps.SCORE_SCHEMA_VERSION == 1 and ps.UPGRADES[ps.SCHEMA_SCORE] == {}
    refused(edit(lambda d: d.update(schema_version=2)), C.UNSUPPORTED_SCHEMA_VERSION)
    refused(edit(lambda d: d.update(schema="jarvis.presentation_studio.variant")), match="schema must be")
    refused(edit(lambda d: d.update(schema_version=0)))
    refused(edit(lambda d: d.pop("schema_version")))


def test_strict_json_loading_refuses_duplicates_and_non_finite_numbers():
    with pytest.raises(PresentationStudioError):
        ps.load_document('{"a": 1, "a": 2}')
    with pytest.raises(PresentationStudioError):
        ps.load_document('{"value": NaN}')
    text = ps.dump_document(data.document())
    assert sc.parse_score(ps.load_document(text)).canonical() == data.score().canonical()


def test_a_document_over_the_size_cap_is_refused_when_dumped():
    # 12 items cannot reach 256 KiB: the bound is real only at the item cap, so build the maximum
    items = [{"item_id": item_id(n), "scene_id": scene_id(1), "presenter": "jarvis", "kind": "speech",
              "text": "é" * sc.MAX_TEXT_CHARS, "next_item_id": item_id(n + 1) if n < sc.MAX_ITEMS else None}
             for n in range(1, sc.MAX_ITEMS + 1)]
    huge = data.document(start_item_id=item_id(1), items=items, cues=[], sequences=[], recovery_points=[])
    score = sc.parse_score(huge)
    with pytest.raises(PresentationStudioError) as caught:
        ps.dump_document(score.to_document())
    assert caught.value.code is C.LIMIT_REACHED


def test_create_and_update_bodies_are_exact_objects():
    content = {key: data.content()[key] for key in sc.CONTENT_KEYS}
    created = sc.parse_score_create({"expected_variant_revision": 1, **content})
    updated = sc.parse_score_update({"expected_revision": 3, **content})
    assert created.expected_variant_revision == 1 and updated.expected_revision == 3
    built = sc.new_score(data.PRESENTATION, data.VARIANT, created.content, __import__("datetime").datetime(
        2026, 10, 7, 12, tzinfo=__import__("datetime").timezone.utc), score_id=data.SCORE_ID)
    assert built.canonical() == data.score().canonical()
    for bad in ({"expected_revision": 1, **content, "extra": 1}, {**content}, {"expected_revision": 0, **content},
                {"expected_revision": "1", **content}):
        with pytest.raises(PresentationStudioError):
            sc.parse_score_update(bad)
    with pytest.raises(PresentationStudioError):
        sc.parse_score_create({"expected_revision": 1, **content})


def test_ids_are_generated_in_the_documented_shapes():
    assert sc.ITEM_ID.fullmatch(sc.new_score_item_id()) and sc.CUE_ID.fullmatch(sc.new_cue_id())
    assert ps.SCORE_ID.fullmatch(ps.new_score_id()) and ps.is_score_id(ps.new_score_id()) and not ps.is_score_id("psr_x")
    assert len({sc.new_score_item_id() for _ in range(50)}) == 50


def test_the_score_error_codes_exist_with_their_statuses():
    from jarvis.domain.presentation_studio_checks import HTTP_STATUS
    assert HTTP_STATUS[C.UNKNOWN_SCORE] == 404 and HTTP_STATUS[C.SCORE_INCOMPATIBLE] == 400
    with pytest.raises(PresentationStudioError) as caught:
        sc.raise_if_incompatible(["scene x is gone"])
    assert caught.value.code is C.SCORE_INCOMPATIBLE and caught.value.status == 400
    sc.raise_if_incompatible([])


# ------------------------------------------------------------------ rework QA-1 : classement, collisions, écritures, boucles

def _valid_instances():
    score = data.score()
    item = score.item(item_id(2))
    return {
        "ScoreItem": item, "CueDefinition": score.cues[0], "CuePredicate": score.cues[0].predicate,
        "ActionRef": item.visual[0], "SequenceStep": score.sequences[0].steps[0], "LockedSequence": score.sequences[0],
        "RecoveryPoint": score.recovery_points[0], "LoopSpec": score.item(item_id(9)).loop, "Score": score}


def test_every_model_field_is_classified_whatever_its_annotation():
    """An `Any`, `dict` or `list` field cannot slip past a "str"-substring check: the registries cover all fields."""

    assert {c.__name__ for c in sc.MODEL_CLASSES} == set(_valid_instances())
    loose = ("Any", "object", "dict", "Mapping", "bytes", "list[")
    for cls in sc.MODEL_CLASSES:
        hints = typing.get_type_hints(cls, globalns=vars(sc))
        for field in dataclasses.fields(cls):
            registries = [r for r in (sc.FREE_TEXT_FIELDS, sc.ID_FIELDS, sc.STRUCTURE_FIELDS)
                          if field.name in r.get(cls.__name__, frozenset())]
            assert len(registries) == 1, f"{cls.__name__}.{field.name} is not classified exactly once"
            if any(word in str(hints[field.name]) for word in loose):
                # a loosely typed field must be named free text on purpose (today only a control value)
                assert (cls.__name__, field.name) == ("ActionRef", "value"), (cls.__name__, field.name)
        for registry in (sc.FREE_TEXT_FIELDS, sc.ID_FIELDS, sc.STRUCTURE_FIELDS):
            assert registry.get(cls.__name__, frozenset()) <= {f.name for f in dataclasses.fields(cls)}


def test_every_id_field_really_carries_a_validator():
    """Cheap mutation guard: replace each id/enum field by junk; the model must refuse it (not just be a plain `str`)."""

    instances = _valid_instances()
    for cls_name, fields in sc.ID_FIELDS.items():
        for field in fields:
            with pytest.raises(PresentationStudioError):
                dataclasses.replace(instances[cls_name], **{field: "not an id!"})


def test_a_free_text_field_is_bounded_not_a_plain_string():
    instances = _valid_instances()
    for cls_name, fields in sc.FREE_TEXT_FIELDS.items():
        for field in fields:
            if field in ("phrases", "value"):
                continue  # tuple of normalised phrases / control scalar: covered by their own tests
            with pytest.raises(PresentationStudioError):
                dataclasses.replace(instances[cls_name], **{field: "x" * 2000})


@pytest.mark.parametrize("phrase", [
    "plаn", "план", "αlpha", "١٢ pages", "٣٣", "１２ ok-١",
    "日本語", "cafе"])
def test_phrases_in_another_script_or_with_non_ascii_digits_are_refused(phrase):
    with pytest.raises(PresentationStudioError, match="Latin letters, ASCII digits"):
        sc.CuePredicate((phrase,))


def test_accented_french_and_folded_forms_are_accepted_and_agree():
    ok = sc.CuePredicate(("À la fin", "ENCORE œuvre", "straße 33",
                          "crème-brûlée"))
    assert len(ok.phrases) == 4
    assert sc.CuePredicate(("L’hôtel",)) == sc.CuePredicate(("lʼhôtel",)) == sc.CuePredicate(("l'hôtel",))
    assert sc.CuePredicate(("l‘hôtel",)).phrases == ("l'hôtel",)
    with pytest.raises(PresentationStudioError, match="same phrase twice"):
        sc.CuePredicate(("lʼhôtel", "l'hôtel"))
    pred = sc.CuePredicate(("À la fin", "encore œuvre", "crème-brûlée", "plan 33", "façon", "Noël"))
    assert all(p == sc.normalise_phrase(p) for p in pred.phrases)
    assert sc.normalise_phrase("été") == "été"  # decomposed accents compose to the Latin letter


def test_confusable_digits_and_letters_never_alias_a_latin_phrase():
    for fake in ("plаn 33", "plan ٣٣"):
        with pytest.raises(PresentationStudioError):
            sc.CuePredicate((fake,))


def _two_cue_score(*phrases_per_cue, armable=(True, True), semantics=((), ())):
    cues = [{"cue_id": cue_id(n), "label": f"cue {n}", "armable": armable[n - 1],
             "predicate": {"phrases": list(phrases_per_cue[n - 1]), "semantics": list(semantics[n - 1])}}
            for n in range(1, len(phrases_per_cue) + 1)]
    doc = data.document()
    doc["cues"] = cues
    for item in doc["items"]:
        item.pop("cue_id", None)
    for n in range(1, len(cues) + 1):
        doc["items"][n - 1]["cue_id"] = cue_id(n)
    return sc.parse_score(doc)


def test_phrase_index_maps_normalised_phrases_to_cue_ids_and_never_refuses_a_repeat():
    score = _two_cue_score(["Passons au contexte", "suivant"], ["PASSONS  AU Contexte", "autre"])
    assert sc.phrase_index(score) == {"autre": (cue_id(2),), "passons au contexte": (cue_id(1), cue_id(2)),
                                      "suivant": (cue_id(1),)}
    assert sc.ambiguous_phrases(score) == {"passons au contexte": (cue_id(1), cue_id(2))}  # repeats are allowed, flagged
    assert sc.ambiguous_phrases(score, [cue_id(1)]) == {}  # ambiguity is a property of the armed set
    assert sc.ambiguous_phrases(score, [cue_id(1), cue_id(2)]) == {"passons au contexte": (cue_id(1), cue_id(2))}
    assert sc.ambiguous_phrases(score, []) == {} and sc.ambiguous_phrases(score, ["psc_ffffffffffff"]) == {}


def test_ambiguity_ignores_non_armable_cues_and_covers_semantic_labels():
    score = _two_cue_score(["suivant"], ["suivant"], armable=(True, False))
    assert sc.phrase_index(score) == {"suivant": (cue_id(1), cue_id(2))}
    assert sc.phrase_index(score, armable_only=True) == {"suivant": (cue_id(1),)}
    assert sc.ambiguous_phrases(score) == {}
    both = _two_cue_score(["a b"], ["c d"], semantics=(("topic_x",), ("topic_x",)))
    assert sc.semantic_index(both) == {"topic_x": (cue_id(1), cue_id(2))}
    assert sc.ambiguous_phrases(both) == {"semantic:topic_x": (cue_id(1), cue_id(2))}
    assert sc.ambiguous_phrases(data.score()) == {}  # the committed fixture is unambiguous
    assert sc.phrase_index(data.score()) == sc.phrase_index(sc.parse_score(data.document()))  # deterministic


def test_overlapping_loops_are_refused_nested_and_consecutive_ones_are_not():
    def loops(spec):
        items = [{"item_id": item_id(n), "scene_id": scene_id(1), "presenter": "none", "kind": "silence",
                  "next_item_id": item_id(n + 1) if n < 9 else None,
                  **({"loop": {"to_item_id": item_id(spec[n][0]), "max_repeats": 1}} if n in spec else {})}
                 for n in range(1, 10)]
        return data.document(start_item_id=item_id(1), items=items, cues=[], sequences=[], recovery_points=[])

    with pytest.raises(PresentationStudioError, match="never overlap partially"):
        sc.parse_score(loops({5: (2, 1), 8: (4, 1)}))
    sc.parse_score(loops({5: (2, 1), 8: (6, 1)}))      # consecutive
    sc.parse_score(loops({5: (2, 1), 4: (3, 1)}))      # nested
    with pytest.raises(PresentationStudioError, match="never overlap partially"):
        sc.parse_score(loops({5: (2, 1), 6: (5, 1)}))  # [2,5] and [5,6] share item 5: partial overlap
    sc.parse_score(loops({3: (3, 1), 5: (5, 1)}))      # two self loops


def test_an_item_cannot_belong_to_one_scene_and_goto_another():
    def contradictory(doc):
        item_of(doc, 4)["visual"] = [{"kind": "scene_goto", "scene_id": scene_id(9)}]
    refused(edit(contradictory), match="an item's own scene_goto names its scene")
    refused(edit(lambda d: item_of(d, 4)["visual"].append({"kind": "scene_goto", "scene_id": scene_id(5)})),
            match="goes to scene")
    # revealing or setting something on another scene is still fine: only navigation must agree
    sc.parse_score(edit(lambda d: item_of(d, 4)["visual"].append({"kind": "reveal", "scene_id": scene_id(5),
                                                                  "anchor_id": "callout"})))


def test_a_missing_control_in_the_bounds_check_is_a_message_not_an_assert():
    action = sc.ActionRef("control_set", scene_id(1), "ghost", value=1)
    assert "ghost" in sc._bounds_problem(data.scenes()[0], action)
    import inspect
    assert "assert " not in inspect.getsource(sc)

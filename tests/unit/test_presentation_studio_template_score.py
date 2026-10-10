"""Squelette de partition d'un modele (Remotion Slice 19) : pur, sur la partition mixte de douze scenes de la Slice 10.

Contrat : `docs/presentation-studio.md` > *Template and prefab promotion contract* > *Score skeleton*. Et les documents de modele v1 / v2.
"""

from __future__ import annotations

import copy
import json

import pytest

from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_score import ItemKind, Presenter, TimingPolicy, parse_content, parse_score
from jarvis.domain.presentation_studio_template import (
    SCHEMA_TEMPLATE, StudioTemplate, TemplateKind, parse_promote, parse_template, template_scene_id,
)
from jarvis.domain.presentation_studio_template_score import NOTE_PLACEHOLDER, instantiate_score, score_skeleton, skeleton_item_id
from tests.fakes import presentation_studio_score as data
from tests.fakes.presentation_studio_score import item_id, scene_id

TEMPLATE_ID = "ptp_0123456789ab"


def slots() -> dict[str, str]:
    return {scene_id(n): template_scene_id(TEMPLATE_ID, n - 1) for n in range(1, 13)}


def full() -> dict:
    """The stored form (`Score.to_document()`): every field present, as Core hands it to the skeleton."""

    return parse_score(data.document()).to_document()


def skeleton():
    return score_skeleton(full(), slot_of=slots(), template_id=TEMPLATE_ID)


def test_the_skeleton_keeps_the_structure_and_none_of_the_words():
    sk, dropped = skeleton()
    assert len(sk["items"]) == 12 and sk["cues"] == [] and sk["sequences"] == [] and sk["recovery_points"] == []
    source = full()
    for mine, theirs in zip(sk["items"], source["items"]):
        assert (mine["presenter"], mine["kind"], mine["target_duration_ms"]) == (theirs["presenter"], theirs["kind"], theirs["target_duration_ms"])
        assert mine["text"] == "" and mine["label"] == "" and mine["cue_id"] is None and mine["motion"] == []
        assert mine["note"] == ("" if theirs["presenter"] == "none" else NOTE_PLACEHOLDER), "never `text`: it would be spoken word for word"
    text = json.dumps(sk)
    for word in [i["text"] for i in source["items"] if i["text"]] + [i["note"] for i in source["items"] if i["note"]]:
        assert word not in text, word
    for cue in source["cues"]:
        assert cue["cue_id"] not in text
    assert dropped["cues"] == len(source["cues"]) and dropped["sequences"] == 1 and dropped["speech"] == 9, dropped
    parse_content(sk)  # the validator of the score accepts it as it stands


def test_no_identifier_of_the_source_score_survives_only_record_local_slots():
    sk, _ = skeleton()
    text = json.dumps(sk)
    for n in range(1, 13):
        assert scene_id(n) not in text and item_id(n) not in text
    assert {i["scene_id"] for i in sk["items"]} == set(slots().values())
    assert sk["items"][0]["item_id"] == skeleton_item_id(TEMPLATE_ID, 0) and sk["start_item_id"] == sk["items"][0]["item_id"]


def test_a_locked_sequence_host_becomes_an_ordinary_item_and_keeps_its_duration():
    source = full()
    host = next(i for i in source["items"] if i["timing"] == "locked")
    sk, _ = skeleton()
    mine = sk["items"][source["items"].index(host)]
    assert mine["timing"] == TimingPolicy.SOFT.value and mine["target_duration_ms"] == host["target_duration_ms"]
    assert not any(a["kind"] == "sequence" for a in mine["visual"])
    assert all(a["kind"] == "scene_goto" for item in sk["items"] for a in item["visual"]), "only the scene gotos are structure"


def test_loops_and_next_links_follow_the_new_ids():
    source = full()
    sk, _ = skeleton()
    ids = {item["item_id"] for item in sk["items"]}
    for item in sk["items"]:
        assert item["next_item_id"] is None or item["next_item_id"] in ids
        assert item["loop"] is None or item["loop"]["to_item_id"] in ids
    assert any(i["loop"] for i in source["items"]) == any(i["loop"] for i in sk["items"])


def test_instantiating_gives_fresh_item_ids_and_the_new_scene_ids():
    sk, _ = skeleton()
    new_scenes = {slot: "pss_" + f"{n:012x}" for n, slot in enumerate(slots().values(), 1)}
    first, second = instantiate_score(sk, new_scenes), instantiate_score(sk, new_scenes)
    assert {i["scene_id"] for i in first["items"]} <= set(new_scenes.values())
    assert [i["item_id"] for i in first["items"]] != [i["item_id"] for i in second["items"]], "ids are fresh each time"
    assert {i["item_id"] for i in first["items"]}.isdisjoint(i["item_id"] for i in sk["items"])
    assert first["start_item_id"] in {i["item_id"] for i in first["items"]}


def test_a_score_naming_a_scene_outside_the_template_is_not_a_skeleton():
    with pytest.raises(KeyError):
        score_skeleton(full(), slot_of={}, template_id=TEMPLATE_ID)


# ------------------------------------------------------------------ le document v1 / v2


def minimal(**extra) -> dict:
    base = {"schema": SCHEMA_TEMPLATE, "schema_version": 1, "template_id": TEMPLATE_ID, "kind": "scene", "title": "T", "description": "",
            "tags": [], "scenes": [], "art_direction": None, "parameters": [], "prefabs": [], "report": {}, "derived_from": {},
            "created_by": "user", "created_at": "2026-10-10T10:00:00.000000Z", "revision": 1}
    return {**base, **extra}


def test_a_document_is_written_at_the_lowest_version_that_expresses_it():
    template = parse_template(minimal())
    assert template.schema_version == 1 and "score" not in template.to_document() and template.to_document()["schema_version"] == 1
    with_catalog = StudioTemplate(**{**template.__dict__, "catalog": {"type": "presentation"}}) if hasattr(template, "__dict__") else None
    if with_catalog is None:  # slots dataclass: rebuild through replace
        from dataclasses import replace
        with_catalog = replace(template, catalog={"type": "presentation", "compatibility": {}})
    document = with_catalog.to_document()
    assert document["schema_version"] == 2 and document["score"] is None and document["embedded"] is None
    assert parse_template(document).catalog == {"type": "presentation", "compatibility": {}}


def test_v2_keys_inside_a_v1_document_and_unknown_versions_are_refused():
    for bad in (minimal(score=None), minimal(embedded=None), minimal(catalog=None)):
        with pytest.raises(PresentationStudioError) as caught:
            parse_template(bad)
        assert caught.value.code is C.INVALID_PRESENTATION
    with pytest.raises(PresentationStudioError) as caught:
        parse_template(minimal(schema_version=3))
    assert caught.value.code is C.UNSUPPORTED_SCHEMA_VERSION
    with pytest.raises(PresentationStudioError):
        parse_template(minimal(schema_version=0))


def test_a_scene_cannot_name_a_source_the_record_does_not_hold():
    from jarvis.domain.presentation_studio_template_remotion import content_hash

    candidate = {"manifest": {}, "template": "", "style": "", "behavior": ""}
    key = content_hash(candidate)
    document = minimal(schema_version=2, score=None, catalog=None, embedded={key: candidate}, kind="presentation")
    scene = copy.deepcopy(_scene_row())
    scene["source"] = "b" * 64
    document["scenes"] = [scene]
    with pytest.raises(PresentationStudioError):
        parse_template(document)
    scene["source"] = key
    assert parse_template(document).scenes[0].source == key
    document["embedded"] = {"a" * 64: candidate}   # a key that is not the hash of what it holds
    scene["source"] = "a" * 64
    with pytest.raises(PresentationStudioError) as caught:
        parse_template(document)
    assert caught.value.code is C.CORRUPT_DOCUMENT


def _scene_row() -> dict:
    return {"key": "s1", "label": "", "scene": data.scenes()[0].to_dict()}


@pytest.mark.parametrize("value", [["MIT", "MIT"], [""], ["x" * 121], "MIT", [1], list("abcdefghi")])
def test_licence_ack_is_a_short_list_of_distinct_names(value):
    with pytest.raises(PresentationStudioError):
        parse_promote({"kind": "scene", "title": "x", "slug": "x", "licence_ack": value}, strict=False)


def test_keep_assets_is_a_boolean_and_both_default_to_nothing_kept_nothing_acknowledged():
    request = parse_promote({"kind": "scene", "title": "x", "slug": "x"}, strict=False)
    assert request.licence_ack == () and request.keep_assets is False
    with pytest.raises(PresentationStudioError):
        parse_promote({"kind": "scene", "title": "x", "slug": "x", "keep_assets": "yes"}, strict=False)
    assert TemplateKind.PRESENTATION.value == "presentation" and Presenter.NONE.value == "none" and ItemKind.SILENCE.value == "silence"

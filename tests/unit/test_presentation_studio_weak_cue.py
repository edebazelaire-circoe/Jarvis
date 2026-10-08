"""Slice 13 rework (QA-1 P4): the non-blocking `weak_cue` lint on a score.

A cue phrase of one word, only stopwords, or under 4 letters fires on ordinary speech. The lint WARNS (it never changes whether a
score is accepted) and names the cue and the phrase position, never the phrase.
"""

from __future__ import annotations

from jarvis.domain.presentation_studio_score import parse_score, weak_cue_warnings
from tests.fakes.presentation_studio_score import document, scene_id
from tests.unit.test_presentation_studio_score_service import CUE, Env, score_body, with_score

import pytest


def score_with(phrases: list[str], *, armable: bool = True):
    doc = document()
    doc["cues"][0] = {**doc["cues"][0], "armable": armable, "predicate": {"phrases": phrases, "semantics": []}}
    if not armable:
        doc["cues"][0]["predicate"] = {"phrases": [], "semantics": []}
    return parse_score(doc)


@pytest.mark.parametrize(("phrases", "reasons"), [
    (["allez"], {"one_word"}), (["ok"], {"one_word", "only_stopwords", "under_4_letters"}),
    (["oui bon"], {"only_stopwords"}), (["le la"], {"only_stopwords"}), (["a b"], {"under_4_letters"}),
])
def test_weak_phrases_are_flagged_with_their_reasons(phrases: list[str], reasons: set[str]) -> None:
    warnings = weak_cue_warnings(score_with(phrases))
    assert len(warnings) == 1 and warnings[0]["code"] == "weak_cue" and warnings[0]["phrase_index"] == 0
    assert reasons <= set(warnings[0]["reasons"])
    assert "phrase" not in warnings[0] and not any(p in str(warnings[0]) for p in phrases[0].split() if len(p) > 3)  # never the phrase


@pytest.mark.parametrize("phrases", [["passons a la suite"], ["regardons maintenant le plan de financement"], ["prochaine diapo", "diapo suivante"]])
def test_distinctive_multi_word_phrases_are_clean(phrases: list[str]) -> None:
    assert weak_cue_warnings(score_with(phrases)) == []


def test_each_weak_phrase_of_a_cue_is_reported_by_position_and_manual_cues_are_not_linted() -> None:
    warnings = weak_cue_warnings(score_with(["passons a la suite", "allez", "ok"]))
    assert [w["phrase_index"] for w in warnings] == [0, 1]  # phrases are stored sorted: allez, ok, passons ...
    assert weak_cue_warnings(score_with([], armable=False)) == []


async def test_the_service_answer_carries_warnings_only_when_there_are_some_and_still_accepts_the_score(tmp_path) -> None:
    env = Env(tmp_path)
    service, pid, vid, answer = await with_score(env, cues=[{"cue_id": CUE, "label": "Go", "armable": True, "predicate": {"phrases": ["allez"]}}])
    assert answer["problems"] == [] and answer["score"]["revision"] == 1  # accepted, unchanged acceptance
    assert answer["warnings"] == [{"code": "weak_cue", "cue_id": CUE, "phrase_index": 0, "reasons": ["one_word", "only_stopwords"]}]
    loaded = await service.get_score(pid, vid)
    assert loaded["warnings"] == answer["warnings"] and loaded["problems"] == []
    # a clean score keeps the exact shape it always had (no `warnings` key)
    clean_service, cpid, cvid, clean = await with_score(Env(tmp_path / "second") if (tmp_path / "second").mkdir() is None else None)
    assert "warnings" not in clean and "warnings" not in await clean_service.get_score(cpid, cvid)
    assert scene_id(1)  # (fixture import kept honest)

"""Slice 13 : the pure cue matcher (`jarvis/domain/presentation_studio_cues.py`).

What is proven, with the real matcher and no double: the fire rules (whole phrase, ordered tokens, bounded fuzzy), the
token-boundary guarantee, every context veto, ambiguity -> no fire with an recorded outcome, once per generation,
cooldown, ordering, the armed-set parser, and the structural guarantee that the output type can hold no transcript.
Contract: `docs/presentation-studio.md` > *Cue following contract*.
"""

from __future__ import annotations

import ast
import dataclasses
import typing
from pathlib import Path

import pytest

from jarvis.domain.presentation_studio_cues import (
    ArmedCues, CueDecision, CueEvidence, CueMatch, CueMatcher, MatcherConfig, MatchRule, Verdict, fold_token, parse_armed,
    phrase_tokens,
)
from tests.fakes.presentation_studio_cue_corpus import CUES, armed_payload

ROOT = Path(__file__).resolve().parents[2]
A, B = CUES["A"], CUES["B"]


def armed(*cues: dict, generation: int = 1, run_id: str = "run000000001") -> ArmedCues:
    return parse_armed({"run_id": run_id, "generation": generation, "expires_in_s": 90, "cues": list(cues), "ambiguous": {}})


def cue(cue_id: str, *phrases: str) -> dict:
    return {"cue_id": cue_id, "phrases": list(phrases), "semantics": []}


def decide(phrases: list[str], text: str, *, config: MatcherConfig | None = None, now: float = 100.0) -> CueDecision:
    matcher = CueMatcher(config)
    matcher.arm(armed(cue(A, *phrases)))
    return matcher.consider("utt-1", text, now)


# ------------------------------------------------------------------ normalisation


def test_folding_is_accent_case_punctuation_and_width_insensitive() -> None:
    assert phrase_tokens("Passons À la suite !") == ("passons", "a", "la", "suite")
    assert phrase_tokens("ｐａｓｓｏｎｓ") == ("passons",)
    assert phrase_tokens("cœur  d'accord-ok") == ("coeur", "d", "accord", "ok")
    assert fold_token("ÉLÈVE") == "eleve"


def test_lookalike_letters_never_fold_to_latin() -> None:
    assert phrase_tokens("раssons") != phrase_tokens("passons")  # Cyrillic p and a
    assert decide(["passons a la suite"], "раssons à la suite").verdict is Verdict.NO_MATCH
    assert decide(["passons a la suite"], "pas​sons à la suite").verdict is Verdict.NO_MATCH


# ------------------------------------------------------------------ the three rules


def test_whole_phrase_fires_with_offsets_and_rule() -> None:
    d = decide(["passons a la suite"], "Bon, Passons à la suite.")
    assert d.verdict is Verdict.FIRE and d.match is not None
    ev = d.match.evidence
    assert (ev.rule, ev.start, ev.end) == (MatchRule.WHOLE_PHRASE, 5, 23)
    assert "Bon, Passons à la suite."[ev.start:ev.end] == "Passons à la suite"
    assert d.match.cue_id == A and d.match.generation == 1


@pytest.mark.parametrize("text", ["surpassons à la suite", "passons à la suites", "passonsalasuite", "compassons à la suite",
                                  "passons à la suitedu", "trépassons à la suite"])
def test_no_match_inside_a_word(text: str) -> None:
    assert decide(["passons a la suite"], text).verdict is Verdict.NO_MATCH


def test_ordered_tokens_allow_one_inserted_word_never_a_negation() -> None:
    d = decide(["passons a la suite"], "passons maintenant à la suite")
    assert d.verdict is Verdict.FIRE and d.match.evidence.rule is MatchRule.ORDERED_TOKENS
    assert decide(["passons a la suite"], "passons pas à la suite").verdict is Verdict.NO_MATCH
    assert decide(["passons a la suite"], "passons vraiment tout de suite à la suite").verdict is Verdict.NO_MATCH  # gap 3
    assert decide(["passons a la suite"], "passons un peu à la suite").verdict is Verdict.NO_MATCH  # gap 2 > per-gap 1


def test_ordered_tokens_need_three_words() -> None:
    assert decide(["merci beaucoup"], "merci très beaucoup").verdict is Verdict.NO_MATCH


def test_fuzzy_is_one_edit_on_a_long_word_of_a_long_phrase_only() -> None:
    phrases = ["presentons les resultats trimestriels"]
    d = decide(phrases, "présentons les résultats trimestriel")
    assert d.verdict is Verdict.FIRE and d.match.evidence.rule is MatchRule.FUZZY_PHRASE
    assert decide(phrases, "présentons les résultats semestriels").verdict is Verdict.NO_MATCH  # 3 edits
    assert decide(phrases, "présentent les résultats trimestriels").verdict is Verdict.NO_MATCH  # homophone, 2 edits
    assert decide(phrases, "présentons le résultats trimestriels").verdict is Verdict.NO_MATCH  # edit on a short token
    assert decide(phrases, "présentons les résultats trimestriel trimestriel").verdict is Verdict.FIRE
    # a short phrase never gets fuzzy: "voila la fin" -> "voila la faim" must not fire
    assert decide(["voila la fin"], "voilà la faim").verdict is Verdict.NO_MATCH
    assert decide(["voila la fin"], "voilà la fin").verdict is Verdict.FIRE


def test_the_configuration_can_narrow_the_rules() -> None:
    strict = MatcherConfig(accepted_rules=frozenset({MatchRule.WHOLE_PHRASE}))
    assert decide(["passons a la suite"], "passons maintenant à la suite", config=strict).verdict is Verdict.NO_MATCH
    assert decide(["passons a la suite"], "passons à la suite", config=strict).verdict is Verdict.FIRE


def test_a_repeated_phrase_in_one_utterance_is_one_match() -> None:
    d = decide(["passons a la suite"], "passons à la suite passons à la suite")
    assert d.verdict is Verdict.FIRE and (d.match.evidence.start, d.match.evidence.end) == (0, 18)


# ------------------------------------------------------------------ context vetoes


@pytest.mark.parametrize(("text", "verdict"), [
    ('quand je dis "passons à la suite" on avance', Verdict.QUOTED),
    ("le mot d'ordre : « passons à la suite » mais personne", Verdict.QUOTED),
    ("il a dit passons à la suite et il est parti", Verdict.QUOTED),
    ("l'expression passons à la suite est usée", Verdict.QUOTED),
    ("si on passe à la suite", Verdict.HEDGED),
    ("jamais on passe à la suite", Verdict.HEDGED),
    ("est-ce qu'on passe à la suite", Verdict.QUESTION),
    ("on passe à la suite ?", Verdict.QUESTION),
    ("pourquoi alors on passe à la suite", Verdict.QUESTION),
])
def test_context_cancels_a_match(text: str, verdict: Verdict) -> None:
    assert decide(["passons a la suite", "on passe a la suite"], text).verdict is verdict


def test_an_unclosed_quote_swallows_the_rest() -> None:
    assert decide(["passons a la suite"], 'il a crié "passons à la suite').verdict is Verdict.QUOTED


def test_the_phrase_must_be_anchored_in_its_sentence() -> None:
    mid = "elle pense que nous devrions tous ensemble passons à la suite de cette longue histoire sans fin"
    assert decide(["passons a la suite"], mid).verdict is Verdict.NOT_ANCHORED
    assert decide(["passons a la suite"], "voilà. " + mid.replace("passons", "Passons")).verdict is Verdict.NOT_ANCHORED
    # at the start or the end of its sentence it stands, whatever follows or precedes
    assert decide(["passons a la suite"], "passons à la suite de cette longue histoire sans fin").verdict is Verdict.FIRE
    assert decide(["passons a la suite"], "alors pour vous tous et pour moi passons à la suite").verdict is Verdict.FIRE
    # a sentence boundary re-anchors
    assert decide(["passons a la suite"], "Voilà pour ce point précis et détaillé. Passons à la suite.").verdict is Verdict.FIRE


def test_a_one_word_cue_needs_a_short_utterance() -> None:
    assert decide(["suivant"], "suivant").verdict is Verdict.FIRE
    assert decide(["suivant"], "ok suivant").verdict is Verdict.FIRE
    assert decide(["suivant"], "le dossier suivant concerne la facturation").verdict is Verdict.NOT_ANCHORED


# ------------------------------------------------------------------ ambiguity


def test_two_armed_cues_touched_is_ambiguous_and_records_both_ids() -> None:
    matcher = CueMatcher()
    matcher.arm(armed(cue(A, "passons a la suite"), cue(B, "pour conclure")))
    d = matcher.consider("u", "pour conclure, passons à la suite", 10.0)
    assert d.verdict is Verdict.AMBIGUOUS and d.match is None and d.candidates == (A, B)
    again = matcher.consider("u2", "passons à la suite", 20.0)  # one cue touched alone still fires (A is first in order)
    assert again.verdict is Verdict.FIRE


def test_a_phrase_two_armed_cues_share_never_fires() -> None:
    matcher = CueMatcher()
    matcher.arm(armed(cue(A, "on continue", "passons a la suite"), cue(B, "on continue")))
    d = matcher.consider("u", "bon on continue", 10.0)
    assert d.verdict is Verdict.AMBIGUOUS and d.candidates == (A, B)
    assert matcher.consider("u", "passons à la suite", 20.0).verdict is Verdict.FIRE  # A's own phrase is not shared


def test_a_shared_phrase_in_two_spellings_is_still_shared() -> None:
    matcher = CueMatcher()
    matcher.arm(armed(cue(A, "d'accord on avance"), cue(B, "d accord on avance")))  # folds to the same tokens
    assert matcher.consider("u", "d'accord on avance", 1.0).verdict is Verdict.AMBIGUOUS


# ------------------------------------------------------------------ once per generation, cooldown, order


def test_a_cue_fires_once_per_generation_and_not_again_inside_its_cooldown() -> None:
    matcher = CueMatcher()
    matcher.arm(armed(cue(A, "passons a la suite"), generation=4))
    assert matcher.consider("u1", "passons à la suite", 10.0).verdict is Verdict.FIRE
    assert matcher.consider("u2", "passons à la suite", 11.0).verdict is Verdict.ALREADY_FIRED
    assert matcher.consider("u3", "passons à la suite", 500.0).verdict is Verdict.ALREADY_FIRED  # never, in this generation
    matcher.arm(armed(cue(A, "passons a la suite"), generation=5))  # a loop re-arms it
    assert matcher.consider("u4", "passons à la suite", 12.0).verdict is Verdict.COOLDOWN  # 2 s after the last fire
    assert matcher.consider("u5", "passons à la suite", 15.0).verdict is Verdict.FIRE  # past the 4 s cooldown and 1 s gap


def test_no_two_fires_closer_than_the_minimum_interval() -> None:
    matcher = CueMatcher()
    matcher.arm(armed(cue(A, "passons a la suite"), cue(B, "pour conclure"), generation=1))
    matcher = CueMatcher(MatcherConfig(allow_skip_ahead=True))
    matcher.arm(armed(cue(A, "passons a la suite"), cue(B, "pour conclure")))
    assert matcher.consider("u1", "passons à la suite", 10.0).verdict is Verdict.FIRE
    assert matcher.consider("u2", "pour conclure", 10.5).verdict is Verdict.COOLDOWN
    assert matcher.consider("u3", "pour conclure", 11.2).verdict is Verdict.FIRE


def test_a_later_cue_does_not_fire_before_an_earlier_one_unless_allowed() -> None:
    cues = (cue(A, "passons a la suite"), cue(B, "pour conclure"))
    matcher = CueMatcher()
    matcher.arm(armed(*cues))
    assert matcher.consider("u", "pour conclure", 10.0).verdict is Verdict.ORDER_BLOCKED
    assert matcher.consider("u", "passons à la suite", 11.0).verdict is Verdict.FIRE
    assert matcher.consider("u", "pour conclure", 20.0).verdict is Verdict.FIRE  # the earlier one has fired: B is next
    loose = CueMatcher(MatcherConfig(allow_skip_ahead=True))
    loose.arm(armed(*cues))
    assert loose.consider("u", "pour conclure", 10.0).verdict is Verdict.FIRE


def test_a_retracted_match_may_fire_again() -> None:
    matcher = CueMatcher()
    matcher.arm(armed(cue(A, "passons a la suite")))
    first = matcher.consider("u1", "passons à la suite", 10.0)
    matcher.retract(first.match)
    assert matcher.consider("u2", "passons à la suite", 10.1).verdict is Verdict.FIRE


def test_arming_lifecycle() -> None:
    matcher = CueMatcher()
    assert matcher.consider("u", "passons à la suite", 1.0).verdict is Verdict.NO_ARMED
    matcher.arm(armed(cue(A, "passons a la suite")))
    assert matcher.consider("u", "passons à la suite", 1.0).verdict is Verdict.FIRE
    matcher.arm(parse_armed({"run_id": "run000000001", "generation": 2, "expires_in_s": 90, "cues": []}))  # a detour: nothing armed
    assert matcher.armed is None and matcher.consider("u", "passons à la suite", 50.0).verdict is Verdict.NO_ARMED
    matcher.arm(armed(cue(A, "passons a la suite"), generation=3))
    assert matcher.consider("u", "passons à la suite", 60.0).verdict is Verdict.FIRE  # a new generation arms it afresh
    matcher.arm(armed(cue(A, "passons a la suite"), generation=1, run_id="runother00002"))  # another run forgets everything
    assert matcher.consider("u", "passons à la suite", 60.2).verdict is Verdict.FIRE


def test_an_empty_or_oversized_text_is_no_match_never_an_error() -> None:
    matcher = CueMatcher()
    matcher.arm(armed(cue(A, "passons a la suite")))
    assert matcher.consider("u", "", 1.0).verdict is Verdict.NO_MATCH
    assert matcher.consider("u", "…", 1.0).verdict is Verdict.NO_MATCH
    assert matcher.consider("u", "x " * 50000, 1.0).verdict is Verdict.NO_MATCH
    assert matcher.consider("u", None, 1.0).verdict is Verdict.NO_MATCH  # type: ignore[arg-type]


# ------------------------------------------------------------------ the armed-set parser


def test_parse_armed_reads_the_core_answer_and_reduces_phrases_to_tokens() -> None:
    parsed = parse_armed(armed_payload("one"))
    assert parsed.run_id == "run000000001" and parsed.generation == 1 and len(parsed.cues) == 1 and not parsed.empty
    assert parsed.cues[0].phrases[0] == ("passons", "a", "la", "suite")
    assert parse_armed({"run_id": None, "generation": 0, "expires_in_s": 90.0, "cues": []}).empty


@pytest.mark.parametrize("bad", [
    None, [], "x", {}, {"run_id": 3, "generation": 1, "expires_in_s": 9, "cues": []},
    {"run_id": "r", "generation": True, "expires_in_s": 9, "cues": []},
    {"run_id": "r", "generation": -1, "expires_in_s": 9, "cues": []},
    {"run_id": "r", "generation": 1, "expires_in_s": 0, "cues": []},
    {"run_id": "r", "generation": 1, "expires_in_s": 9, "cues": "nope"},
    {"run_id": "r", "generation": 1, "expires_in_s": 9, "cues": [{"cue_id": "x", "phrases": ["a"]}]},
    {"run_id": "r", "generation": 1, "expires_in_s": 9, "cues": [{"cue_id": CUES["A"], "phrases": "passons"}]},
    {"run_id": "r", "generation": 1, "expires_in_s": 9, "cues": [{"cue_id": CUES["A"], "phrases": ["a"] * 9}]},
    {"run_id": "r", "generation": 1, "expires_in_s": 9, "cues": [{"cue_id": CUES["A"], "phrases": [3]}]},
    {"run_id": "r", "generation": 1, "expires_in_s": 9, "cues": [{"cue_id": CUES["A"], "phrases": ["x"], "semantics": ["s"] * 5}]},
    {"run_id": "r", "generation": 1, "expires_in_s": 9,
     "cues": [{"cue_id": CUES["A"], "phrases": ["a"]}] * 5},
])
def test_parse_armed_refuses_a_malformed_answer(bad: object) -> None:
    with pytest.raises(ValueError):
        parse_armed(bad)


def test_the_parse_error_never_quotes_a_phrase() -> None:
    secret = "phrase-secrete-xyz"
    with pytest.raises(ValueError) as caught:
        parse_armed({"run_id": "r", "generation": 1, "expires_in_s": 9, "cues": [{"cue_id": CUES["A"], "phrases": [secret, 3]}]})
    assert secret not in str(caught.value)


def test_semantic_labels_are_carried_and_never_matched() -> None:
    matcher = CueMatcher()
    matcher.arm(armed({"cue_id": A, "phrases": ["passons a la suite"], "semantics": ["transition"]}))
    assert matcher.consider("u", "transition", 1.0).verdict is Verdict.NO_MATCH
    assert matcher.armed.cues[0].semantics == ("transition",)


# ------------------------------------------------------------------ the output type holds no transcript


def test_constructor_guards_refuse_free_text_in_the_output() -> None:
    ev = CueEvidence("utt-1", 0, 5, MatchRule.WHOLE_PHRASE)
    for bad_id in ("passons à la suite", "", "x" * 65, "a b", 3, None):
        with pytest.raises(ValueError):
            CueEvidence(bad_id, 0, 5, MatchRule.WHOLE_PHRASE)  # type: ignore[arg-type]
    for start, end in ((-1, 3), (3, 3), (4, 2), (0, 99999), (True, 3), (0.5, 3)):
        with pytest.raises(ValueError):
            CueEvidence("utt-1", start, end, MatchRule.WHOLE_PHRASE)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        CueEvidence("utt-1", 0, 5, "whole_phrase")  # type: ignore[arg-type]
    for bad_cue in ("passons", "psc_xyz", "", None):
        with pytest.raises(ValueError):
            CueMatch(bad_cue, 1, ev)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        CueMatch(A, -1, ev)
    with pytest.raises(ValueError):
        CueMatch(A, 1, "passons à la suite")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        CueDecision(Verdict.FIRE)  # a fire without a match
    with pytest.raises(ValueError):
        CueDecision(Verdict.NO_MATCH, CueMatch(A, 1, ev))  # a match without a fire
    with pytest.raises(ValueError):
        CueDecision(Verdict.AMBIGUOUS, candidates=("passons à la suite",))  # type: ignore[arg-type]
    for frozen in (ev, CueMatch(A, 1, ev)):
        with pytest.raises(dataclasses.FrozenInstanceError):
            frozen.cue_id = "x"  # type: ignore[misc]  # noqa: B010


def test_the_output_types_have_no_free_text_field() -> None:
    """A field of type `str` is allowed only where a constructor regex guards it (an id). A new `str`, `Any`, `object`,
    `dict`, `bytes` or collection-of-text field fails here: the output cannot carry a transcript by construction."""

    allowed_str = {CueEvidence: {"utterance_id"}, CueMatch: {"cue_id"}, CueDecision: set()}
    for model, ids in allowed_str.items():
        hints = typing.get_type_hints(model)
        strings = {name for name, hint in hints.items() if hint is str or "str" in str(hint) and name not in ("candidates",)}
        assert strings == ids, (model.__name__, strings)
        for name, hint in hints.items():
            assert hint in (str, int, MatchRule, Verdict, CueEvidence, CueMatch, tuple[str, ...]) or "CueMatch" in str(hint) \
                or name == "authorizes_actions", (model.__name__, name, hint)
    assert CueMatch.authorizes_actions is False  # a match authorises nothing: Core judges and resolves
    assert "authorizes_actions" in typing.get_type_hints(CueMatch)
    assert {f.name for f in dataclasses.fields(CueMatch)} == {"cue_id", "generation", "evidence"}
    assert {f.name for f in dataclasses.fields(CueEvidence)} == {"utterance_id", "start", "end", "rule"}
    assert {f.name for f in dataclasses.fields(CueDecision)} == {"verdict", "match", "candidates"}


def test_a_decision_repr_never_contains_the_text() -> None:
    text = "Alors confidentiel marmotte passons à la suite"
    d = decide(["passons a la suite"], text)
    assert d.verdict is Verdict.FIRE
    shown = repr(d).lower()
    for word in ("confidentiel", "marmotte", "alors", "passons"):
        assert word not in shown


def test_the_domain_module_is_pure() -> None:
    tree = ast.parse((ROOT / "jarvis/domain/presentation_studio_cues.py").read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    assert names <= {"__future__", "re", "unicodedata", "collections.abc", "dataclasses", "enum", "typing",
                     "jarvis.domain.presentation_studio_armed_set", "jarvis.domain.presentation_studio_score"}, sorted(names)

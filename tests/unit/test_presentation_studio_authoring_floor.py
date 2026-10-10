"""The content floor of the first-draft gate and its false-refusal set (jarvis-interactive-presentation-studio, Slice 11 rework, QA-1 B2 and B3).

QA-1 listed drafts that passed `directed` with zero failures (empty, one-word, emoji-only, digit-varied filler, weak multi-word cues,
meaningless labels, a brief whose `must_cover` and `language` nobody read) and content the placeholder heuristics refused although it was
legitimate (`#ffffff`, `1000000`, a numeric table, `WIP`/`todo`/`lorem ipsum` as the subject). Both lists are tests here: the first must be
refused with the right code, the second must pass, and the `brief.literal_terms` allow-list is honoured with a visible warning.
"""

from __future__ import annotations

import pytest

from jarvis.domain.presentation_studio_authoring_text import (
    count_words, guess_language, label_meaningless, meaningful_words, normalise_filler, placeholder_hit, risky_constructs,
)
from tests.fakes import presentation_studio_fake_author as fa
from tests.fakes.presentation_studio_authoring_env import AuthoringEnv

FRENCH_NAMES = ("Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta", "Iota", "Kappa", "Lambda", "Mu")


@pytest.fixture
async def env(tmp_path):
    return await AuthoringEnv(tmp_path / "e").start()


def codes(report: dict, key: str = "failures") -> set[str]:
    return {f["code"] for f in report[key]}


def everywhere(draft: dict, *, body: str, line: str, headline: str = "-", titles: tuple[str, ...] | None = None) -> None:
    for index, scene in enumerate(draft["scenes"]):
        scene["data"]["body"], scene["props"]["headline"] = body, headline
        if titles:
            scene["title"] = titles[index]
    for entry in draft["score"]["items"]:
        entry["text"] = line
        entry.pop("note", None)


def numbered(draft: dict, template: str) -> None:
    for index, scene in enumerate(draft["scenes"], start=1):
        scene["data"]["body"] = template.format(n=index)


def pairs(count: int) -> str:
    return "_".join(f"{chr(97 + i // 26)}{chr(97 + i % 26)}" for i in range(count))


# (name, mutation of a good directed deck, the failure code that must now be raised)
POOR_DRAFTS = (
    ("every body and line is an ellipsis, titles are Greek letters",
     lambda b, d: everywhere(d, body="...", line="...", titles=FRENCH_NAMES), "content_thin"),
    ("one-word bodies and lines", lambda b, d: everywhere(d, body="Oui", line="Ok", headline="Alors"), "content_thin"),
    ("emoji-only bodies and lines", lambda b, d: everywhere(d, body="🔥🚀✨", line="🎉🎉🎉", headline="🎉"), "content_thin"),
    ("the body is the letter a, under real titles", lambda b, d: everywhere(d, body="a", line="Ceci est une vraie phrase dite", headline="a"),
     "content_thin"),
    ("a Jarvis note of two letters", lambda b, d: d["score"]["items"][2].update(note="xx", text=""), "content_thin"),
    ("bodies that differ only by a number", lambda b, d: numbered(d, "Voici le point numero {n} du trimestre pour tous"),
     "filler_numeric_variants"),
    ("titles Sujet 1..12", lambda b, d: [s.update(title=f"Sujet {n}") for n, s in enumerate(d["scenes"], 1)], "filler_numeric_variants"),
    ("titles that are numbers", lambda b, d: [s.update(title=str(n)) for n, s in enumerate(d["scenes"], 1)], "placeholder_text"),
    ("450 CJK characters in one scene",
     lambda b, d: d["scenes"][3]["data"].update(body="漢字仮名" * 112 + "漢字"), "text_density"),
    ("196 words glued by underscores",
     lambda b, d: d["scenes"][3]["data"].update(body=pairs(196)[:599]), "text_density"),
    ("cue: et puis voila", lambda b, d: d["score"]["items"][1].update(cue={"label": "c", "armable": True, "phrases": ["et puis voila"]}),
     "cue_stopword_phrase"),
    ("cue: oui bon d accord", lambda b, d: d["score"]["items"][1].update(cue={"label": "c", "armable": True, "phrases": ["oui bon d accord"]}),
     "cue_stopword_phrase"),
    ("cue: next slide please", lambda b, d: d["score"]["items"][1].update(cue={"label": "c", "armable": True, "phrases": ["next slide please"]}),
     "cue_stopword_phrase"),
    ("cue: ok on continue", lambda b, d: d["score"]["items"][1].update(cue={"label": "c", "armable": True, "phrases": ["ok on continue"]}),
     "cue_stopword_phrase"),
    ("a control labelled ???", lambda b, d: d["scenes"][1]["controls"][0].update(label="???"), "control_label_meaningless"),
    ("a control labelled ctrl1", lambda b, d: d["scenes"][1]["controls"][0].update(label="ctrl1"), "control_label_meaningless"),
    ("a control labelled x", lambda b, d: d["scenes"][1]["controls"][0].update(label="x"), "control_label_meaningless"),
    ("a must_cover item the deck never mentions", lambda b, d: b.update(must_cover=["cryptographie quantique"]), "must_cover_missing"),
    ("a French deck for a German brief", lambda b, d: b.update(language="de"), "language_mismatch"),
    ("an English brief over a French deck", lambda b, d: b.update(language="en"), "language_mismatch"),
)


@pytest.mark.parametrize("name, mutate, code", POOR_DRAFTS, ids=[row[0] for row in POOR_DRAFTS])
async def test_a_poor_draft_that_used_to_pass_is_now_refused_with_its_code(env, name, mutate, code):
    brief, draft = fa.brief("directed"), fa.good_deck()
    assert (await env.check(brief, draft)).body["report"]["ok"] is True          # the good deck passes: the floor is not a wall
    mutate(brief, draft)
    out = await env.assemble(brief, draft)
    assert out.status == "refused", name
    assert code in codes(out.body["report"]), (name, out.body["report"]["failures"])
    assert env.folders() == [] and env.prefab_versions() == {}


async def test_the_floor_levels_are_the_documented_ones(env):
    """One-shot refuses emptiness too; must_cover and language are warnings there (a display has no brief to honour); exploratory is light."""

    brief, draft = fa.good_one_shot()
    draft["scenes"][0]["data"]["body"], draft["scenes"][0]["title"], draft["scenes"][0]["props"]["headline"] = "...", "Alpha", "-"
    assert "content_thin" in codes((await env.check(brief, draft)).body["report"])
    brief, draft = fa.good_one_shot()
    brief.update(must_cover=["cryptographie quantique"], language="de")
    report = (await env.check(brief, draft)).body["report"]
    assert report["ok"] is True and {"must_cover_missing", "language_mismatch"} <= codes(report, "warnings")
    brief, draft = fa.exploratory(3)
    brief.update(must_cover=["cryptographie quantique"])
    assert "must_cover_missing" not in codes((await env.check(brief, draft)).body["report"], "warnings")      # off for exploratory


# ------------------------------------------------------------------ B3: what must NOT be refused

async def test_colours_numbers_and_tables_are_data_not_placeholders(env):
    brief, draft = fa.brief("directed"), fa.good_deck()                          # a dark art direction: white is the natural accent
    scene = draft["scenes"][3]
    scene["props"]["theme"] = {"accent": "#ffffff"}
    scene["data"]["body"] = "Budget total de 1000000 euros sur l'annee"
    assert (await env.check(brief, draft)).body["report"]["ok"] is True
    from tests.fakes.presentation_studio_art_direction import base_dict

    brief, draft = fa.brief("directed"), fa.good_deck(da={"mode": "profile", "profile": base_dict()})   # a light art direction: black is the accent
    for entry in draft["score"]["items"]:
        entry["visual"] = []                                                     # the fixture's orange would not keep contrast on it
    scene = draft["scenes"][3]
    scene["props"]["theme"] = {"accent": "#000000"}
    scene["data"]["body"] = "Resultats : " + " ; ".join(f"M{n}: 1.5 / 2.25 / 3" for n in range(1, 13))
    report = (await env.check(brief, draft)).body["report"]
    assert report["ok"] is True, report["failures"]                              # black text, a 12-row numeric table
    assert (await env.assemble(brief, draft)).status == "delivered"


@pytest.mark.parametrize("text", ["#ffffff", "#000000", "#00000080", "1000000", "1000000 euros", "https://example.com/todo-list",
                                  "M1: 1.5 / 2.25 / 3 ; M2: 1.5 / 2.25 / 3 ; M3: 1.5 / 2.25 / 3", "3,5 %", "2026-10-08"])
def test_literals_are_never_placeholders(text):
    assert placeholder_hit(text) is None


@pytest.mark.parametrize("text, kind", [("WIP", "todo"), ("todo", "todo"), ("Lorem ipsum", "lorem"), ("Pourquoi ???", "xxx"),
                                        ("placeholder", "blank"), ("aaaaaaaa", "repeated_char"), ("abababab", "low_variety")])
def test_prose_that_looks_like_a_placeholder_still_is_one_without_an_allowance(text, kind):
    assert placeholder_hit(text)[0] == kind


@pytest.mark.parametrize("body, terms", [("Tableau de suivi : trois taches en WIP et deux en todo", ["WIP", "todo"]),
                                         ("Typographie : le lorem ipsum sert a juger une mise en page", ["lorem ipsum"]),
                                         ("Pourquoi ??? se demandent les equipes", ["???"])])
async def test_literal_terms_lift_the_placeholder_rule_for_that_term_only_and_say_so(env, body, terms):
    brief, draft = fa.good_one_shot()
    draft["scenes"][0]["data"]["body"] = body
    refused = (await env.check(brief, draft)).body["report"]
    assert codes(refused) == {"placeholder_text"}                                # no override: refused, and the message offers the way out
    assert "literal_terms" in refused["failures"][0]["message"]
    brief["literal_terms"] = terms
    allowed = (await env.check(brief, draft)).body["report"]
    assert allowed["ok"] is True and codes(allowed, "warnings") == {"placeholder_allowed"}
    assert terms[0] not in allowed["warnings"][0]["message"]                      # the warning counts, it does not echo
    draft["scenes"][0]["data"]["body"] += " et TBD ailleurs"
    assert codes((await env.check(brief, draft)).body["report"]) == {"placeholder_text"}      # only the declared terms are allowed


async def test_the_allow_list_is_bounded_and_exploratory_only_strictness_is_validated(env):
    brief, draft = fa.good_one_shot()
    for bad in ({"literal_terms": ["t"] * 9}, {"literal_terms": ["x" * 41]}, {"literal_terms": ["two\nlines"]}, {"literal_terms": "WIP"},
                {"strict_content": True}, {"strict_content": "yes"}):
        out = await env.check({**brief, **bad}, draft)
        assert out.body["report"]["failures"][0]["code"] == "brief_invalid", bad


# ------------------------------------------------------------------ helpers

def test_the_word_counters():
    assert count_words("漢字仮名" * 10) == 20 and count_words("a_b_c d") == 4 and count_words("🔥🚀") == 0
    assert meaningful_words("...") == meaningful_words("a") == meaningful_words("🔥🚀✨") == meaningful_words("12 34") == 0
    assert meaningful_words("Le chiffre d'affaires progresse") == 4
    assert normalise_filler("Voici le POINT numéro 12 !") == normalise_filler("voici le point numero 7")


@pytest.mark.parametrize("label, meaningless", [("???", True), ("x", True), ("-", True), ("ctrl1", True), ("Control 2", True), ("12", True),
                                                ("champ_3", True), ("Couleur d'accent", False), ("Titre", False), ("Taille", False)])
def test_label_meaningless(label, meaningless):
    assert label_meaningless(label) is meaningless


def test_the_language_guess_needs_evidence_and_knows_only_french_and_english():
    french = ["Bonjour a tous, voici la revue du trimestre et ce que nous avons decide pour les equipes dans cette presentation"]
    english = ["Hello everyone, this is the review of the quarter and what we have decided for the teams in this presentation"]
    assert guess_language(french) == "fr" and guess_language(english) == "en"
    assert guess_language(["Oui"]) is None and guess_language(["Guten Tag, dies ist die Vorstellung des Quartals fur alle Teams"]) is None


def test_risky_constructs_are_named_by_kind():
    assert risky_constructs("", "", "fetch('x')") == ["network"]
    assert risky_constructs("", "", "new WebSocket(u); eval(s)") == ["eval", "network"]
    assert risky_constructs("", "", "import('./x.js')") == ["dynamic_import"]
    assert risky_constructs('<a href="javascript:alert(1)">x</a>', "", "") == ["javascript_url"]
    assert risky_constructs('<img src="https://t.example/p.png">', "", "") == ["remote_reference"]
    assert risky_constructs("", "@import 'x.css'", "") == ["remote_reference"]
    assert risky_constructs('<p data-jv-text="props.a"></p>', ".a{color:red}", "jarvis.on('init', function () {});") == []


async def test_a_published_source_with_a_network_call_is_refused_and_a_clean_one_is_not(env):
    """Remotion Slice 15: the lint in front of the wall is the Slice 06 static guard, run when the source is parsed. It is not a craft rule, so it
    refuses in EVERY workflow (the HTML `behavior_risky` lint, still true of a stored Slidecar variant, was a warning for a light candidate)."""

    brief, draft = fa.violate("prefab_invalid")
    out = await env.check(*[brief, draft])
    failure = out.body["report"]["failures"][0]
    assert codes(out.body["report"]) == {"prefab_invalid"} and "network_api" in failure["message"] and "src/Scene.tsx" in failure["message"]
    b2, d2 = fa.exploratory(3)
    dict(fa.VIOLATIONS)["prefab_invalid"](b2, d2)
    report = (await env.check(b2, d2)).body["report"]
    assert report["ok"] is False and "prefab_invalid" in codes(report)               # an error for an exploratory candidate too

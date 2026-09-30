"""Pertinence d'un outil pour une intention (plugins MCP, Slice 04 ; `docs/mcp/plugins.md` §6.4, ARCH §7.4).

Ce qui doit tenir : pliage des accents et de la casse, découpe snake/camel/kebab,
mots vides FR/EN, racinisation légère, synonymes bilingues, ordre BM25F et
départage `(-score, ordre de la source, id)`, intention vide ⇒ ordre alphabétique,
déterminisme, et la **porte de qualité** : recall@3 ≥ 0,9 sur ≥ 20 intentions
FR/EN (`tests/fixtures/tool_intents.json`), avec le vrai catalogue natif et le
chemin de documents de la passerelle.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from jarvis.domain.tool_relevance import EXPANSION_WEIGHT, SYNONYMS, ToolDoc, fold, query_weights, rank, tokens
from jarvis.runtime.mcp_catalog import build_catalog
from jarvis.runtime.tools_gateway_mcp import external_entries, native_entries

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "tool_intents.json"


def _doc(id_: str, name: str, *, label: str = "", description: str = "", params: tuple[str, ...] = (),
         texts: tuple[str, ...] = (), source: str = "s") -> ToolDoc:
    return ToolDoc(id=id_, name=name, label=label, description=description, param_names=params,
                   param_texts=texts, source=source)


# ------------------------------------------------------------------ normalisation

def test_fold_drops_accents_and_case():
    assert fold("Réunion ÉVÉNEMENT Ça") == "reunion evenement ca"


def test_tokens_split_snake_camel_kebab_and_drop_stopwords():
    assert tokens("sendMail search_messages list-events") == ["send", "mail", "search", "messag", "list", "event"]
    assert tokens("Envoyer un courriel à Paul") == ["envoyer", "courriel", "paul"]
    assert tokens("the file of the user") == ["fil", "user"]


@pytest.mark.parametrize("a, b", [
    ("messages", "message"), ("événements", "événement"), ("réunions", "réunion"), ("searches", "search"),
    ("boxes", "box"), ("meetings", "meeting"), ("created", "create"), ("creation", "create"),
])
def test_light_stem_joins_plural_and_derived_forms(a, b):
    assert tokens(a) == tokens(b)


def test_short_words_are_never_stemmed_below_three_letters():
    assert tokens("les as bus") == ["bus"]  # « bus » garde son s : il ne resterait que deux lettres


def test_synonym_groups_are_bilingual_and_symmetric():
    for word, other in (("mail", "courriel"), ("calendrier", "meeting"), ("chercher", "search"),
                        ("supprimer", "delete"), ("fichier", "document"), ("brouillon", "draft")):
        (stem,), (other_stem,) = tokens(word), tokens(other)
        assert other_stem in SYNONYMS[stem] and stem in SYNONYMS[other_stem]


def test_query_expansion_weighs_synonyms_below_the_words_said():
    weights = query_weights("envoyer un mail")
    assert weights["envoyer"] == 1.0 and weights["mail"] == 1.0
    assert weights["send"] == EXPANSION_WEIGHT and weights["courriel"] == EXPANSION_WEIGHT


# ------------------------------------------------------------------ classement

def test_bm25f_prefers_a_name_hit_over_a_description_hit():
    docs = [_doc("b", "read_notes", description="send a message to someone"),
            _doc("a", "send_message", description="deliver text")]
    ranked = rank("send message", docs)
    assert [doc.id for doc, _ in ranked] == ["a", "b"] and ranked[0][1] > ranked[1][1] > 0


def test_a_synonym_matches_but_below_the_exact_word():
    docs = [_doc("exact", "x", description="courriel"), _doc("synonym", "y", description="email")]
    ranked = rank("courriel", docs)
    assert [doc.id for doc, _ in ranked] == ["exact", "synonym"] and ranked[1][1] > 0


def test_parameter_names_and_enum_values_count():
    docs = [_doc("p", "tool_a", params=("folder",), texts=("inbox", "drafts")), _doc("q", "tool_b")]
    assert rank("drafts folder", docs)[0][0].id == "p"


def test_tie_break_is_source_order_then_id():
    docs = [_doc("z", "same", source="second"), _doc("y", "same", source="first"), _doc("x", "same", source="first"),
            _doc("w", "same", source="second")]
    # `second` apparaît d'abord dans l'entrée : il passe devant ; puis l'id.
    assert [doc.id for doc, _ in rank("same", docs)] == ["w", "z", "x", "y"]


def test_no_common_word_scores_zero():
    assert all(score == 0 for _, score in rank("zzz", [_doc("a", "alpha"), _doc("b", "beta")]))


def test_an_empty_intent_after_folding_is_alphabetical_with_zero_scores():
    ranked = rank("  les de la !! ", [_doc("b", "b"), _doc("c", "c"), _doc("a", "a")])
    assert [(doc.id, score) for doc, score in ranked] == [("a", 0.0), ("b", 0.0), ("c", 0.0)]


def test_ranking_is_deterministic():
    docs = [_doc(f"t{i}", f"tool_{i}", description=f"mail number {i % 3}") for i in range(30)]
    first = rank("envoyer mail", docs)
    assert all(rank("envoyer mail", docs) == first for _ in range(3))


# ------------------------------------------------------------------ porte de qualité (fixture)

@pytest.fixture(scope="module")
def corpus():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    catalog = asyncio.run(build_catalog())
    plugin_id = fixture["plugin"]["plugin_id"]
    tools = [{"tool_id": f"{plugin_id}.{tool['name']}", "plugin_id": plugin_id, **tool}
             for tool in fixture["external_tools"]]
    _, natives = native_entries(catalog, fixture["native_servers"])
    _, externals = external_entries([fixture["plugin"]], tools)
    return fixture, natives + externals


def test_the_fixture_covers_at_least_twenty_intents_in_french_and_english(corpus):
    fixture, docs = corpus
    assert len(fixture["intents"]) >= 20
    ids = {doc.id for doc in docs}
    for case in fixture["intents"]:
        assert set(case["expected"]) <= ids, case["intent"]
    assert any(doc.id.startswith("mcp__jarvis-display__") for doc in docs)
    assert any(doc.source == fixture["plugin"]["display_name"] for doc in docs)


def test_recall_at_3_is_at_least_ninety_percent(corpus):
    fixture, docs = corpus
    misses = []
    for case in fixture["intents"]:
        top = [doc.id for doc, _ in rank(case["intent"], docs)[:3]]
        if not set(case["expected"]) & set(top):
            misses.append((case["intent"], top))
    recall = 1 - len(misses) / len(fixture["intents"])
    assert recall >= 0.9, misses


def test_the_fixture_ranking_is_byte_identical_across_runs(corpus):
    fixture, docs = corpus
    def run():
        return json.dumps([[(doc.id, score) for doc, score in rank(case["intent"], docs)]
                           for case in fixture["intents"]])
    assert run() == run()

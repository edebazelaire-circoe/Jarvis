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
#: Jeu de **régression** (QA Slice 04) : autre persona, outils façon Graph, mais ses intentions
#: paraphrasent les ratés publiés par la QA — ce n'est pas un jeu tenu à l'écart. Il garde le
#: vocabulaire ajouté pour eux ; une formulation neuve reste une limite connue de V1 (plugins.md §7).
REGRESSION = Path(__file__).resolve().parents[1] / "fixtures" / "tool_intents_regression.json"


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
    assert tokens("the file of the user") == ["file", "user"]


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


@pytest.mark.parametrize("word, other", [
    ("reply", "réponds"), ("répondre", "reply"), ("réponse", "reply"), ("forward", "transférer"),
    ("phone", "téléphone"), ("numéro", "mobile"), ("tel", "phone"), ("task", "tâche"), ("todo", "task"),
    ("attachment", "PJ"), ("folder", "dossier"), ("share", "partager"), ("download", "télécharger"),
    ("upload", "téléverser"), ("schedule", "planifier"), ("programmer", "schedule"), ("cancel", "annuler"),
    ("retrouve", "search"),
])
def test_qa_synonym_groups_expand_both_ways(word, other):
    (other_stem,) = tokens(other)
    assert query_weights(word)[other_stem] == EXPANSION_WEIGHT


@pytest.mark.parametrize("phrase, member", [
    ("ajoute ce qu'il y a à faire", "task"), ("la pièce jointe du mail", "attachment"),
    ("faire suivre ce message", "forward"), ("envoyer un fichier sur le drive", "upload"),
])
def test_multi_word_members_expand_only_as_a_phrase(phrase, member):
    (stem,) = tokens(member)
    assert query_weights(phrase)[stem] == EXPANSION_WEIGHT


def test_a_word_of_a_phrase_alone_expands_nothing_of_its_group():
    # « envoyer un fichier » est dans le groupe upload : « envoyer un mail » ne doit pas y mener.
    assert "upload" not in query_weights("envoyer un mail")
    assert "task" not in query_weights("faire une capture")


def test_file_and_thread_do_not_share_a_stem():
    # QA 2 : « fil » (de discussion) et « file » tombaient tous deux sur `fil`.
    assert tokens("fil") != tokens("file") and tokens("files") == tokens("file") == ["file"]


@pytest.mark.parametrize("text, expected", [
    ("PDFs", ["pdf"]), ("URLs", ["url"]), ("IDs", ["ids"]), ("listIDsForUser", ["list", "ids", "user"]),
    ("HTTPServer", ["http", "server"]), ("getURLsOfPDFs", ["get", "url", "pdf"]), ("sendMail", ["send", "mail"]),
])
def test_camel_split_keeps_the_plural_s_of_an_acronym(text, expected):
    # Avant : « PDFs » → « PD » + « Fs ». « IDs » reste « ids » : deux lettres ne se racinisent jamais.
    assert tokens(text) == expected


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


def _load(path: Path):
    fixture = json.loads(path.read_text(encoding="utf-8"))
    catalog = asyncio.run(build_catalog())
    plugin_id = fixture["plugin"]["plugin_id"]
    tools = [{"tool_id": f"{plugin_id}.{tool['name']}", "plugin_id": plugin_id, **tool}
             for tool in fixture["external_tools"]]
    _, natives = native_entries(catalog, fixture["native_servers"])
    _, externals = external_entries([fixture["plugin"]], tools)
    return fixture, natives + externals


def _recall_at_3(fixture, docs) -> tuple[float, list]:
    ids = {doc.id for doc in docs}
    misses = []
    for case in fixture["intents"]:
        assert set(case["expected"]) <= ids, case["intent"]
        top = [doc.id for doc, _ in rank(case["intent"], docs)[:3]]
        if not set(case["expected"]) & set(top):
            misses.append((case["intent"], top))
    return 1 - len(misses) / len(fixture["intents"]), misses


def test_regression_recall_at_3_is_at_least_eighty_percent():
    """Les ratés publiés par la QA (Slice 04), reformulés : 0,600 (12/20) avant le vocabulaire ajouté,
    0,900 après (poids inchangés). Ne mesure pas la généralisation : une formulation neuve reste à
    5/15 selon la QA 2 (limite connue de V1, `docs/mcp/plugins.md` §7)."""

    fixture, docs = _load(REGRESSION)
    assert len(fixture["intents"]) >= 15
    assert fixture["plugin"]["plugin_id"] != json.loads(FIXTURE.read_text(encoding="utf-8"))["plugin"]["plugin_id"]
    for qa_intent in ("réponds à l'email", "transférer", "numéro de téléphone de", "ajoute une tâche",
                      "retrouve le PDF"):
        assert any(case["intent"].startswith(qa_intent) for case in fixture["intents"]), qa_intent
    recall, misses = _recall_at_3(fixture, docs)
    assert recall >= 0.8, misses


def test_original_recall_still_holds_after_the_vocabulary_rework():
    recall, misses = _recall_at_3(*_load(FIXTURE))
    assert recall >= 0.9, misses


def test_the_fixture_ranking_is_byte_identical_across_runs(corpus):
    fixture, docs = corpus
    def run():
        return json.dumps([[(doc.id, score) for doc, score in rank(case["intent"], docs)]
                           for case in fixture["intents"]])
    assert run() == run()

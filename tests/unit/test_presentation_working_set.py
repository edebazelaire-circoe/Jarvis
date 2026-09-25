"""Mémoire de séance PRESENTATION (handoff presentation-interaction-mode, Slice 04).

Ce qui doit tenir :

- chaque collection a une borne et un ordre d'éviction **déterministe** ; ce qui
  sort, sort toujours dans le même ordre, et une ressource chaude ne part jamais
  avant une jetable ;
- un producteur qui rejoue ne double rien, et deux mentions d'un même sujet se
  coalescent sans jamais réécrire la provenance ;
- une ressource évincée ne renaît pas d'une préparation tardive ;
- le fil de parole récente reste frais même quand l'enrichissement traîne —
  c'est toute la Décision D06 ;
- l'instantané ne se déchire pas : les deux moitiés viennent du même instant, et
  une opération refusée n'écrit rien ;
- quitter PRESENTATION (ou finir la séance) retire tout, immédiatement ;
- l'audio brut n'entre nulle part, et aucune parole ne se retrouve dans le
  journal.

Les assertions portent sur du **comportement** et sur des **valeurs**, jamais
sur le texte source d'un module.
"""

from __future__ import annotations

import ast
import asyncio
from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from jarvis.core.interaction_mode import InteractionModeService
from jarvis.core.presentation_working_set import (
    APPLIED_KIND,
    BOUND_KIND,
    MAX_JOURNALLED_VALUE_CHARS,
    MAX_RETIRED_RESOURCE_KEYS,
    MAX_SEEN_OBSERVATIONS,
    RETIRED_KIND,
    TAIL_KIND,
    PresentationStateResult,
    PresentationWorkingSetStore,
)
from jarvis.core.voice_state import VoiceStateDisposition
from jarvis.domain.presentation_working_set import (
    MAX_ATTENTION_ITEMS,
    MAX_ATTENTION_REASON_CHARS,
    MAX_CLAIM_CHARS,
    MAX_DESCRIPTOR_ITEMS,
    MAX_DESCRIPTOR_KEYS,
    MAX_DESCRIPTOR_TEXT_CHARS,
    MAX_ENTITY_KIND_CHARS,
    MAX_ENTITY_LABEL_CHARS,
    MAX_OPEN_QUESTIONS,
    MAX_PREPARED_RESOURCES,
    MAX_PRESENTATION_ID_CHARS,
    MAX_PROVENANCE_SOURCES,
    MAX_QUESTION_CHARS,
    MAX_REFERENCE_CHARS,
    MAX_RESOURCE_IDLE_S,
    MAX_RESOURCE_TITLE_CHARS,
    MAX_SOURCE_TITLE_CHARS,
    MAX_TAIL_CHARS,
    MAX_TAIL_ENTRIES,
    MAX_TAIL_ENTRY_CHARS,
    MAX_TOPIC_LABEL_CHARS,
    MAX_WORKING_SET_CHARS,
    MAX_WORKING_SET_CLAIMS,
    MAX_WORKING_SET_ENTITIES,
    MAX_WORKING_SET_SOURCES,
    MAX_WORKING_SET_TOPICS,
    RECORD_COLLECTIONS,
    AttentionCategory,
    AttentionItem,
    AttentionSeverity,
    ClaimStatus,
    ObservationProvenance,
    OpenQuestion,
    PreparedResource,
    PresentationClaim,
    PresentationContextSnapshot,
    PresentationEntity,
    PresentationObservation,
    PresentationSource,
    PresentationTopic,
    PresentationTranscriptTail,
    PresentationWorkingSet,
    PresentationWorkingSetError,
    ResourceKind,
    ResourceReference,
    ResourceTemperature,
    TranscriptTailEntry,
    UtteranceOrigin,
    check_descriptor,
    compact_chars,
)
import jarvis.domain.presentation_working_set as domain_module

ROOT = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)
SESSION = "presentation-1"


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


class SpyDiagnostics:
    """Journal de test : on garde tout, pour pouvoir prouver ce qui n'y est pas."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str, str, dict]] = []
        self.hook = None

    def emit(self, kind: str, message: str, *, level: str = "info", data: dict | None = None) -> None:
        self.records.append((kind, message, level, dict(data or {})))
        if self.hook is not None:
            self.hook(kind, dict(data or {}))

    def kinds(self) -> list[str]:
        return [item[0] for item in self.records]


def provenance(sequence: int = 1, *, seconds: float = 0, utterance: str | None = None,
               origin: UtteranceOrigin = UtteranceOrigin.AMBIENT) -> ObservationProvenance:
    return ObservationProvenance(
        utterance_id=utterance or f"u{sequence}", sequence=sequence,
        observed_at=at(seconds), origin=origin,
    )


def topic(index: int = 0, *, seconds: float = 0, label: str | None = None,
          sequence: int = 1) -> PresentationTopic:
    return PresentationTopic(
        topic_id=f"t{index}", label=label or f"sujet {index}",
        provenance=provenance(sequence, seconds=seconds),
        first_seen_at=at(seconds), last_seen_at=at(seconds),
    )


def entity(index: int = 0, *, seconds: float = 0) -> PresentationEntity:
    return PresentationEntity(
        entity_id=f"e{index}", label=f"entite {index}", kind="person",
        provenance=provenance(1, seconds=seconds),
        first_seen_at=at(seconds), last_seen_at=at(seconds),
    )


def claim(index: int = 0, *, seconds: float = 0, sequence: int = 1,
          status: ClaimStatus = ClaimStatus.ASSERTED, topic_id: str | None = None) -> PresentationClaim:
    return PresentationClaim(
        claim_id=f"c{index}", statement=f"affirmation {index}",
        provenance=provenance(sequence, seconds=seconds),
        first_seen_at=at(seconds), last_seen_at=at(seconds), status=status, topic_id=topic_id,
    )


def source(index: int = 0, *, seconds: float = 0) -> PresentationSource:
    return PresentationSource(
        source_id=f"s{index}", kind=ResourceKind.WEB_PAGE,
        reference=f"https://exemple.test/{index}", title=f"source {index}",
        retrieved_at=at(seconds),
    )


def reference(index: int = 0) -> ResourceReference:
    return ResourceReference(
        kind=ResourceKind.CHART_DESCRIPTOR, locator=f"chart:{index}", title=f"graphique {index}",
        descriptor={"labels": ["T1", "T2"], "values": [10, 20]},
    )


def resource(index: int = 0, *, seconds: float = 0, topic_id: str | None = None,
             temperature: ResourceTemperature = ResourceTemperature.WARM) -> PreparedResource:
    return PreparedResource(
        resource_id=f"r{index}", reference=reference(index),
        provenance=provenance(1, seconds=seconds), prepared_at=at(seconds),
        last_used_at=at(seconds), temperature=temperature, topic_id=topic_id,
    )


def question(index: int = 0, *, seconds: float = 0) -> OpenQuestion:
    return OpenQuestion(
        question_id=f"q{index}", text=f"question {index}",
        provenance=provenance(1, seconds=seconds), asked_at=at(seconds),
    )


def attention(index: int = 0, *, seconds: float = 0, claim_id: str | None = None,
              severity: AttentionSeverity = AttentionSeverity.NOTICE,
              category: AttentionCategory = AttentionCategory.CONTRADICTION,
              confidence: float = 0.5) -> AttentionItem:
    return AttentionItem(
        attention_id=f"a{index}", category=category, severity=severity, confidence=confidence,
        raised_at=at(seconds), claim_id=claim_id if claim_id is not None else f"c{index}",
    )


BUILDERS = {
    PresentationTopic: topic,
    PresentationEntity: entity,
    PresentationClaim: claim,
    PresentationSource: source,
    PreparedResource: resource,
    OpenQuestion: question,
    AttentionItem: attention,
}


def bound_store(**kwargs) -> tuple[PresentationWorkingSetStore, SpyDiagnostics]:
    sink = SpyDiagnostics()
    store = PresentationWorkingSetStore(diagnostics=sink, **kwargs)
    assert store.bind_session(SESSION).applied
    return store, sink


def observe(store: PresentationWorkingSetStore, index: int, *, seconds: float | None = None,
            text: str | None = None, **kwargs) -> PresentationStateResult:
    return store.observe(
        SESSION, f"u{index}", text if text is not None else f"phrase numero {index}",
        spoken_at=at(index if seconds is None else seconds), **kwargs,
    )


def put(store: PresentationWorkingSetStore, record, *, observation: str | None = None,
        session: str = SESSION) -> PresentationStateResult:
    key = observation or f"obs-{record.record_id}-{id(record)}"
    return store.apply(PresentationObservation(key[:MAX_PRESENTATION_ID_CHARS], session, record))


# ---------------------------------------------------------------------------
# Bornes et ordre d'éviction
# ---------------------------------------------------------------------------


def test_le_fil_recent_ne_garde_que_les_dernieres_enonciations():
    store, _ = bound_store()
    for index in range(MAX_TAIL_ENTRIES + 4):
        assert observe(store, index, text="court").applied
    tail = store.snapshot.tail
    assert len(tail.entries) == MAX_TAIL_ENTRIES
    assert [item.utterance_id for item in tail.entries] == [
        f"u{index}" for index in range(4, MAX_TAIL_ENTRIES + 4)
    ]
    assert tail.latest.utterance_id == f"u{MAX_TAIL_ENTRIES + 3}"


def test_le_fil_recent_tient_son_budget_de_caracteres():
    store, _ = bound_store()
    chunk = "a" * 500
    for index in range(MAX_TAIL_ENTRIES):
        observe(store, index, text=chunk)
    tail = store.snapshot.tail
    assert tail.text_chars <= MAX_TAIL_CHARS
    assert len(tail.entries) == MAX_TAIL_CHARS // 500
    # Ce qui reste est bien la fin, pas le début.
    assert tail.entries[-1].utterance_id == f"u{MAX_TAIL_ENTRIES - 1}"


def test_le_fil_recent_oublie_ce_qui_est_plus_vieux_que_sa_fenetre():
    store, _ = bound_store(tail_max_age_s=30)
    observe(store, 0, seconds=0)
    observe(store, 1, seconds=10)
    assert len(store.snapshot.tail.entries) == 2
    observe(store, 2, seconds=100)
    assert [item.utterance_id for item in store.snapshot.tail.entries] == ["u2"]


def test_une_parole_arrivee_trop_tard_est_dite_perimee_plutot_que_rangee_puis_jetee():
    store, _ = bound_store(tail_max_age_s=30)
    observe(store, 0, seconds=200)
    before = store.snapshot
    late = observe(store, 1, seconds=10)
    assert late.disposition is VoiceStateDisposition.STALE
    assert late.code == "presentation_tail_entry_too_old"
    assert store.snapshot is before


def test_un_balayage_explicite_vieillit_un_fil_que_plus_personne_n_alimente():
    store, _ = bound_store(tail_max_age_s=30)
    observe(store, 0, seconds=0)
    assert store.snapshot.tail.entries
    result = store.prune(now=at(500))
    assert result.applied and result.evicted == 1
    assert store.snapshot.tail.entries == ()


@pytest.mark.parametrize(
    "record_type, cap",
    [(cls, RECORD_COLLECTIONS[cls][1]) for cls in RECORD_COLLECTIONS],
)
def test_chaque_collection_de_l_ensemble_de_travail_tient_sa_borne(record_type, cap):
    store, _ = bound_store()
    build = BUILDERS[record_type]
    for index in range(cap + 3):
        assert put(store, build(index, seconds=index)).applied
    collection = RECORD_COLLECTIONS[record_type][0]
    kept = getattr(store.snapshot.working_set, collection)
    assert len(kept) == cap
    identities = {item.record_id for item in kept}
    # Les trois plus anciens sont partis, les plus récents sont là.
    assert not identities & {build(index).record_id for index in range(3)}
    assert build(cap + 2).record_id in identities


def test_les_sujets_partent_du_plus_anciennement_mentionne_au_plus_recent():
    store, _ = bound_store()
    for index in range(MAX_WORKING_SET_TOPICS):
        put(store, topic(index, seconds=index))
    # Le sujet 0 redevient le plus récent : c'est le sujet 1 qui doit tomber.
    put(store, topic(0, seconds=1_000))
    put(store, topic(99, seconds=1_001))
    kept = {item.topic_id for item in store.snapshot.working_set.topics}
    assert "t0" in kept and "t99" in kept and "t1" not in kept


def test_deux_enregistrements_de_meme_date_sont_evinces_dans_un_ordre_stable():
    kept_ids = []
    for _ in range(3):
        store, _ = bound_store()
        for index in range(MAX_WORKING_SET_TOPICS + 1):
            put(store, topic(index, seconds=0))
        kept_ids.append(tuple(item.topic_id for item in store.snapshot.working_set.topics))
    assert len(set(kept_ids)) == 1, kept_ids
    # L'identifiant tranche, donc l'ordre est total et reproductible.
    assert kept_ids[0] == tuple(sorted(kept_ids[0]))


def test_une_ressource_jetable_part_avant_une_tiede_et_une_tiede_avant_une_chaude():
    store, _ = bound_store()
    # Une chaude très ancienne, une tiède récente, une jetable encore plus récente.
    put(store, replace(resource(1, seconds=0), temperature=ResourceTemperature.HOT))
    put(store, replace(resource(2, seconds=10), temperature=ResourceTemperature.WARM))
    put(store, replace(resource(3, seconds=20), temperature=ResourceTemperature.DISCARDABLE))
    ordered = [item.resource_id for item in store.snapshot.working_set.resources]
    assert ordered == ["r3", "r2", "r1"]
    # La tête de la collection est la prochaine évincée : la jetable, pas la vieille chaude.
    for index in range(4, MAX_PREPARED_RESOURCES + 4):
        put(store, replace(resource(index, seconds=100 + index), temperature=ResourceTemperature.HOT))
    survivors = {item.resource_id for item in store.snapshot.working_set.resources}
    assert "r3" not in survivors and "r2" not in survivors


def test_un_enregistrement_trop_vieux_sort_de_l_ensemble_au_commit_suivant():
    store, _ = bound_store(record_max_age_s=60)
    put(store, claim(1, seconds=0))
    assert len(store.snapshot.working_set.claims) == 1
    put(store, claim(2, seconds=600))
    assert [item.claim_id for item in store.snapshot.working_set.claims] == ["c2"]


def test_une_observation_plus_vieille_que_le_budget_d_age_est_dite_perimee():
    store, _ = bound_store(record_max_age_s=60)
    put(store, claim(1, seconds=600))
    before = store.snapshot
    late = put(store, claim(2, seconds=0))
    assert late.disposition is VoiceStateDisposition.STALE
    assert late.code == "presentation_record_too_old"
    assert store.snapshot is before


def test_une_collection_pleine_refuse_plutot_que_d_accepter_puis_de_jeter():
    store, _ = bound_store()
    for index in range(MAX_WORKING_SET_TOPICS):
        put(store, topic(index, seconds=100 + index))
    before = store.snapshot
    refused = put(store, topic(99, seconds=0))
    assert refused.disposition is VoiceStateDisposition.CAPACITY
    assert refused.code == "presentation_topics_full"
    assert store.snapshot is before


def ident(prefix: str, index: int) -> str:
    """Un identifiant aussi long que le contrat l'autorise."""

    return (f"{prefix}{index}-" + "z" * MAX_PRESENTATION_ID_CHARS)[:MAX_PRESENTATION_ID_CHARS]


def maximal_descriptor() -> dict:
    """Le plus gros descripteur que `check_descriptor` accepte encore."""

    best = None
    for keys in range(1, MAX_DESCRIPTOR_KEYS + 1):
        for text_len in range(1, MAX_DESCRIPTOR_TEXT_CHARS + 1):
            candidate = {
                f"kkkkkkkk{i}": ["v" * text_len] * MAX_DESCRIPTOR_ITEMS for i in range(keys)
            }
            try:
                check_descriptor("d", candidate)
            except Exception:
                continue
            if best is None or compact_chars(candidate) > compact_chars(best):
                best = candidate
    assert best is not None
    return best


def maximal_working_set() -> PresentationWorkingSet:
    """L'ensemble **vraiment** maximal : chaque champ à sa borne, rien de vide.

    La première version de ce test construisait un ensemble à moitié maximal
    (identifiants courts, descripteurs vides, tuples vides) et concluait que le
    plafond tenait. Il tenait pour cet ensemble-là ; le vrai produit passait
    largement au-dessus.
    """

    prov = [
        ObservationProvenance(utterance_id=ident("u", i), sequence=9_999_999, observed_at=at(0))
        for i in range(64)
    ]
    sources = tuple(ident("s", j) for j in range(MAX_PROVENANCE_SOURCES))
    descriptor = maximal_descriptor()
    return PresentationWorkingSet(
        topics=tuple(
            PresentationTopic(topic_id=ident("t", i), label="T" * MAX_TOPIC_LABEL_CHARS,
                              provenance=prov[i], first_seen_at=at(0), last_seen_at=at(i))
            for i in range(MAX_WORKING_SET_TOPICS)
        ),
        entities=tuple(
            PresentationEntity(entity_id=ident("e", i), label="E" * MAX_ENTITY_LABEL_CHARS,
                               kind="K" * MAX_ENTITY_KIND_CHARS, provenance=prov[i],
                               first_seen_at=at(0), last_seen_at=at(i), topic_id=ident("t", 0))
            for i in range(MAX_WORKING_SET_ENTITIES)
        ),
        claims=tuple(
            PresentationClaim(claim_id=ident("c", i), statement="C" * MAX_CLAIM_CHARS,
                              provenance=prov[i], first_seen_at=at(0), last_seen_at=at(i),
                              status=ClaimStatus.CONTRADICTED, confidence=0.123456789,
                              topic_id=ident("t", 0), source_ids=sources)
            for i in range(MAX_WORKING_SET_CLAIMS)
        ),
        sources=tuple(
            PresentationSource(source_id=ident("s", i), kind=ResourceKind.WEB_PAGE,
                               reference="https://" + "r" * (MAX_REFERENCE_CHARS - 8),
                               title="S" * MAX_SOURCE_TITLE_CHARS, retrieved_at=at(i))
            for i in range(MAX_WORKING_SET_SOURCES)
        ),
        resources=tuple(
            PreparedResource(
                resource_id=ident("r", i),
                reference=ResourceReference(
                    kind=ResourceKind.CHART_DESCRIPTOR,
                    locator="chart:" + "l" * (MAX_REFERENCE_CHARS - 6),
                    title="R" * MAX_RESOURCE_TITLE_CHARS, descriptor=descriptor),
                provenance=prov[i], prepared_at=at(0), last_used_at=at(i),
                temperature=ResourceTemperature.HOT, topic_id=ident("t", 0),
                claim_id=ident("c", 0))
            for i in range(MAX_PREPARED_RESOURCES)
        ),
        questions=tuple(
            OpenQuestion(question_id=ident("q", i), text="Q" * MAX_QUESTION_CHARS,
                         provenance=prov[i], asked_at=at(i), topic_id=ident("t", 0))
            for i in range(MAX_OPEN_QUESTIONS)
        ),
        attention=tuple(
            AttentionItem(attention_id=ident("a", i), category=AttentionCategory.CONTRADICTION,
                          severity=AttentionSeverity.WARNING, confidence=0.123456789,
                          raised_at=at(i), reason="A" * MAX_ATTENTION_REASON_CHARS,
                          claim_id=ident("c", i), topic_id=ident("t", 0), source_ids=sources)
            for i in range(MAX_ATTENTION_ITEMS)
        ),
        observed_sequence=9_999_999,
        committed_at=at(100),
    )


def test_le_plafond_de_caracteres_passe_au_dessus_de_l_ensemble_reellement_maximal():
    maximal = maximal_working_set()
    assert maximal.payload_chars <= MAX_WORKING_SET_CHARS, maximal.payload_chars
    # Et le plafond reste une borne qui veut dire quelque chose : pas dix fois
    # le produit reel, sinon il ne bornerait plus rien.
    assert maximal.payload_chars > MAX_WORKING_SET_CHARS // 2, maximal.payload_chars


def test_le_plafond_de_caracteres_est_un_refus_type_et_non_une_exception(monkeypatch):
    """Une borne qu'on croit inatteignable est celle qu'on finira par atteindre."""

    store, _ = bound_store()
    monkeypatch.setattr(domain_module, "MAX_WORKING_SET_CHARS", 400)
    result = store.apply(PresentationObservation("obs-enorme", SESSION, claim(1, seconds=0)))
    assert result.disposition is VoiceStateDisposition.CAPACITY
    assert result.code == "presentation_working_set_too_large"
    assert store.snapshot.working_set.claims == ()


# ---------------------------------------------------------------------------
# Déduplication et coalescence
# ---------------------------------------------------------------------------


def test_une_observation_rejouee_ne_recompte_pas_la_mention_d_un_sujet():
    store, _ = bound_store()
    first = put(store, topic(1, seconds=0), observation="obs-1")
    replayed = put(store, topic(1, seconds=5), observation="obs-1")
    assert first.applied
    assert replayed.disposition is VoiceStateDisposition.DUPLICATE
    assert store.snapshot.working_set.topics[0].mention_count == 1
    assert replayed.revision == first.revision


def test_deux_mentions_distinctes_du_meme_sujet_sont_coalescees():
    store, _ = bound_store()
    put(store, topic(1, seconds=0), observation="obs-1")
    second = put(store, topic(1, seconds=30, label="sujet 1 precise"), observation="obs-2")
    assert second.applied and second.code == "presentation_topic_coalesced"
    kept = store.snapshot.working_set.topics
    assert len(kept) == 1
    assert kept[0].mention_count == 2
    assert kept[0].label == "sujet 1 precise"
    assert kept[0].last_seen_at == at(30)


def test_deux_fois_la_meme_contradiction_ne_font_qu_un_point_d_attention():
    store, _ = bound_store()
    put(store, attention(1, seconds=0, claim_id="c7", severity=AttentionSeverity.INFO,
                         confidence=0.2), observation="obs-1")
    merged = put(store, attention(2, seconds=5, claim_id="c7", severity=AttentionSeverity.WARNING,
                                  confidence=0.9), observation="obs-2")
    assert merged.code == "presentation_attention_coalesced"
    items = store.snapshot.working_set.attention
    assert len(items) == 1
    assert items[0].attention_id == "a1"
    # La coalescence garde le signal le plus fort des deux, jamais le plus faible.
    assert items[0].severity is AttentionSeverity.WARNING
    assert items[0].confidence == 0.9


def test_une_contradiction_toujours_signalee_ne_vieillit_pas_sur_place():
    """Un point d'attention relevé sans cesse est vivant, pas ancien."""

    store, _ = bound_store(record_max_age_s=100)
    put(store, attention(1, seconds=0, claim_id="c7"), observation="obs-1")
    put(store, attention(2, seconds=90, claim_id="c7"), observation="obs-2")
    items = store.snapshot.working_set.attention
    assert len(items) == 1 and items[0].attention_id == "a1"
    assert items[0].raised_at == at(90)
    # Et il survit donc au balayage qui l'aurait emporte avec son premier
    # horodatage.
    store.prune(now=at(150))
    assert [item.attention_id for item in store.snapshot.working_set.attention] == ["a1"]


def test_deux_contradictions_sur_deux_affirmations_restent_deux_points():
    store, _ = bound_store()
    put(store, attention(1, seconds=0, claim_id="c1"))
    put(store, attention(2, seconds=1, claim_id="c2"))
    assert len(store.snapshot.working_set.attention) == 2


def test_une_revision_de_transcription_garde_le_rang_de_l_enonciation():
    store, _ = bound_store()
    observe(store, 0, seconds=0)
    observe(store, 1, seconds=5)
    revised = store.observe(SESSION, "u0", "phrase corrigee", spoken_at=at(6), revision=1)
    assert revised.applied and revised.code == "presentation_tail_revised"
    entries = store.snapshot.tail.entries
    assert [item.utterance_id for item in entries] == ["u0", "u1"]
    assert entries[0].text == "phrase corrigee"
    assert entries[0].sequence < entries[1].sequence
    # Une correction tardive ne devient pas la parole la plus fraîche.
    assert store.snapshot.tail.latest.utterance_id == "u1"


def test_une_revision_plus_ancienne_que_celle_detenue_est_ecartee():
    store, _ = bound_store()
    observe(store, 0, seconds=0)
    store.observe(SESSION, "u0", "version 2", spoken_at=at(1), revision=2)
    stale = store.observe(SESSION, "u0", "version 1", spoken_at=at(2), revision=1)
    assert stale.disposition is VoiceStateDisposition.STALE
    assert stale.code == "presentation_tail_revision_stale"
    assert store.snapshot.tail.entries[0].text == "version 2"


def test_la_meme_revision_deux_fois_est_un_doublon_et_non_un_changement():
    store, _ = bound_store()
    observe(store, 0, seconds=0)
    before = store.snapshot
    again = store.observe(SESSION, "u0", "autre texte", spoken_at=at(1), revision=0)
    assert again.disposition is VoiceStateDisposition.DUPLICATE
    assert store.snapshot is before


def test_la_memoire_des_observations_vues_est_bornee():
    store, _ = bound_store()
    for index in range(MAX_SEEN_OBSERVATIONS + 2):
        put(store, claim(index % 3, seconds=index), observation=f"obs-{index}")
    # La toute première clé est sortie de la mémoire : elle n'est plus un doublon.
    revived = put(store, claim(0, seconds=1_000), observation="obs-0")
    assert revived.disposition is not VoiceStateDisposition.DUPLICATE


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_la_coalescence_ne_reecrit_jamais_la_provenance_ni_la_premiere_vue():
    store, _ = bound_store()
    origin = provenance(1, seconds=0, utterance="u-origine")
    first = replace(topic(1, seconds=0), provenance=origin)
    put(store, first, observation="obs-1")
    later = replace(
        topic(1, seconds=60), provenance=provenance(9, seconds=60, utterance="u-plus-tard"),
    )
    put(store, later, observation="obs-2")
    kept = store.snapshot.working_set.topics[0]
    assert kept.provenance == origin
    assert kept.first_seen_at == at(0)
    assert kept.last_seen_at == at(60)


def test_la_provenance_survit_a_l_eviction_de_l_enonciation_qu_elle_cite():
    store, _ = bound_store()
    observe(store, 0, seconds=0, text="la marge a double")
    put(store, replace(claim(1, seconds=0), provenance=provenance(1, seconds=0, utterance="u0")))
    for index in range(1, MAX_TAIL_ENTRIES + 3):
        observe(store, index, text="suite")
    assert "u0" not in {item.utterance_id for item in store.snapshot.tail.entries}
    kept = store.snapshot.working_set.claims[0]
    assert kept.provenance.utterance_id == "u0"
    assert kept.provenance.sequence == 1
    assert kept.provenance.observed_at == at(0)


def test_une_affirmation_verifiee_garde_la_provenance_de_qui_l_a_dite():
    store, _ = bound_store()
    origin = provenance(3, seconds=0, utterance="u-orateur")
    put(store, replace(claim(1, seconds=0), provenance=origin), observation="obs-1")
    put(store, replace(claim(1, seconds=30, status=ClaimStatus.CONTRADICTED), provenance=provenance(
        7, seconds=30, utterance="u-recherche")), observation="obs-2")
    kept = store.snapshot.working_set.claims[0]
    assert kept.status is ClaimStatus.CONTRADICTED
    assert kept.provenance.utterance_id == "u-orateur"


# ---------------------------------------------------------------------------
# Ressources préparées : température et non-résurrection
# ---------------------------------------------------------------------------


def test_une_ressource_dont_le_sujet_a_quitte_l_ensemble_devient_jetable():
    store, _ = bound_store()
    put(store, topic(1, seconds=0))
    put(store, resource(1, seconds=0, topic_id="t1"))
    assert store.snapshot.working_set.resources[0].temperature is ResourceTemperature.WARM
    # Le sujet est chassé par douze sujets plus récents.
    for index in range(2, MAX_WORKING_SET_TOPICS + 2):
        put(store, topic(index, seconds=index))
    assert "t1" not in {item.topic_id for item in store.snapshot.working_set.topics}
    assert store.snapshot.working_set.resources[0].temperature is ResourceTemperature.DISCARDABLE


def test_une_ressource_inutilisee_trop_longtemps_devient_jetable():
    store, _ = bound_store()
    put(store, resource(1, seconds=0))
    put(store, claim(1, seconds=MAX_RESOURCE_IDLE_S + 10))
    assert store.snapshot.working_set.resources[0].temperature is ResourceTemperature.DISCARDABLE


def test_une_ressource_qui_sert_redevient_chaude():
    store, _ = bound_store()
    put(store, resource(1, seconds=0))
    used = store.use_resource("r1", at=at(30))
    assert used.applied and used.code == "presentation_resource_used"
    kept = store.snapshot.working_set.resources[0]
    assert kept.temperature is ResourceTemperature.HOT
    assert kept.last_used_at == at(30)


def test_utiliser_une_ressource_inconnue_ne_fabrique_rien():
    store, _ = bound_store()
    result = store.use_resource("jamais-preparee", at=at(1))
    assert result.disposition is VoiceStateDisposition.IGNORED
    assert result.code == "presentation_resource_unknown"
    assert store.snapshot.working_set.resources == ()


def test_une_ressource_evincee_ne_renait_pas_d_une_preparation_tardive():
    store, _ = bound_store()
    put(store, resource(0, seconds=0), observation="obs-0")
    for index in range(1, MAX_PREPARED_RESOURCES + 1):
        put(store, resource(index, seconds=10 + index), observation=f"obs-{index}")
    assert "r0" not in {item.resource_id for item in store.snapshot.working_set.resources}
    late = put(store, resource(0, seconds=500), observation="obs-tardive")
    assert late.disposition is VoiceStateDisposition.STALE
    assert late.code == "presentation_resource_retired"
    assert "r0" not in {item.resource_id for item in store.snapshot.working_set.resources}


def test_utiliser_une_ressource_retiree_est_refuse_et_ne_la_recree_pas():
    store, _ = bound_store()
    put(store, resource(0, seconds=0), observation="obs-0")
    for index in range(1, MAX_PREPARED_RESOURCES + 1):
        put(store, resource(index, seconds=10 + index), observation=f"obs-{index}")
    result = store.use_resource("r0", at=at(600))
    assert result.disposition is VoiceStateDisposition.STALE
    assert result.code == "presentation_resource_retired"
    assert "r0" not in {item.resource_id for item in store.snapshot.working_set.resources}


def test_la_memoire_des_ressources_retirees_est_bornee():
    store, _ = bound_store()
    total = MAX_RETIRED_RESOURCE_KEYS + MAX_PREPARED_RESOURCES + 5
    for index in range(total):
        put(store, resource(index, seconds=index), observation=f"obs-{index}")
    # La toute première clé retirée a fini par être oubliée : elle repasse.
    revived = put(store, resource(0, seconds=total + 10), observation="obs-retour")
    assert revived.applied
    # Et une clé retirée récemment reste refusée.
    recent = put(store, resource(total - MAX_PREPARED_RESOURCES - 1, seconds=total + 11),
                 observation="obs-recent")
    assert recent.disposition is VoiceStateDisposition.STALE


# ---------------------------------------------------------------------------
# Le fil reste frais quand l'enrichissement traîne (D06)
# ---------------------------------------------------------------------------


def test_le_fil_reste_frais_quand_l_enrichissement_prend_du_retard():
    store, _ = bound_store()
    for index in range(5):
        observe(store, index, seconds=index, text=f"phrase {index}")
    snapshot = store.snapshot
    assert snapshot.working_set.topics == ()
    assert len(snapshot.tail.entries) == 5
    assert snapshot.enrichment_lag_entries == 5
    assert snapshot.tail.latest.utterance_id == "u4"


def test_l_instantane_dit_combien_d_enonciations_l_analyse_n_a_pas_rattrapees():
    store, _ = bound_store()
    for index in range(5):
        observe(store, index, seconds=index)
    sequences = [item.sequence for item in store.snapshot.tail.entries]
    put(store, replace(claim(1, seconds=2), provenance=provenance(sequences[2], seconds=2)))
    assert store.snapshot.enrichment_lag_entries == 2
    assert store.snapshot.working_set.observed_sequence == sequences[2]
    put(store, replace(claim(2, seconds=4), provenance=provenance(sequences[4], seconds=4)))
    assert store.snapshot.enrichment_lag_entries == 0


def test_un_deictique_se_resout_sur_la_derniere_parole_pas_sur_le_dernier_fait():
    store, _ = bound_store()
    observe(store, 0, seconds=0, text="parlons de la marge")
    put(store, replace(claim(1, seconds=0), provenance=provenance(1, seconds=0, utterance="u0")))
    observe(store, 1, seconds=20, text="et maintenant le churn")
    snapshot = store.snapshot
    # L'analyse en est restée à la marge ; la parole fraîche, elle, dit le churn.
    assert snapshot.working_set.claims[0].provenance.utterance_id == "u0"
    assert snapshot.tail.latest.text == "et maintenant le churn"
    assert snapshot.enrichment_lag_entries == 1


def test_le_retard_de_l_enrichissement_se_mesure_aussi_en_secondes():
    store, _ = bound_store()
    observe(store, 0, seconds=0)
    put(store, replace(claim(1, seconds=0), provenance=provenance(1, seconds=0, utterance="u0")))
    observe(store, 1, seconds=45)
    assert store.snapshot.enrichment_lag_s == pytest.approx(45.0)


def test_un_enrichissement_a_jour_ne_declare_aucun_retard():
    store, _ = bound_store()
    observe(store, 0, seconds=0)
    put(store, replace(claim(1, seconds=0), provenance=provenance(1, seconds=0, utterance="u0")))
    assert store.snapshot.enrichment_lag_entries == 0
    assert store.snapshot.enrichment_lag_s == 0.0


def test_une_analyse_jamais_partie_annonce_le_retard_maximal_pas_zero():
    """Le pire retard possible ne doit pas se lire comme « à jour »."""

    store, _ = bound_store()
    for index in range(10):
        observe(store, index, seconds=index * 3)
    snapshot = store.snapshot
    assert snapshot.enrichment_lag_entries == 10
    assert snapshot.enrichment_lag_s == pytest.approx(27.0)
    # Et un magasin réellement à jour, lui, rend bien zéro : les deux cas sont
    # distinguables, ce qui est tout l'objet de ce champ.
    caught_up, _ = bound_store()
    observe(caught_up, 0, seconds=0)
    put(caught_up, replace(claim(1, seconds=0),
                           provenance=provenance(1, seconds=0, utterance="u0")))
    assert caught_up.snapshot.enrichment_lag_s == 0.0


def test_un_enregistrement_sans_provenance_ne_remet_pas_le_retard_a_zero():
    """Une source trouvée n'est pas une phrase comprise."""

    store, _ = bound_store()
    for index in range(10):
        observe(store, index, seconds=index * 3)
    put(store, replace(claim(1, seconds=0), provenance=provenance(1, seconds=0, utterance="u0")))
    before_entries = store.snapshot.enrichment_lag_entries
    before_seconds = store.snapshot.enrichment_lag_s
    assert before_entries == 9 and before_seconds == pytest.approx(27.0)
    put(store, source(1, seconds=30))
    assert store.snapshot.enrichment_lag_entries == before_entries
    assert store.snapshot.enrichment_lag_s == pytest.approx(before_seconds)
    # Les deux lectures du retard disent la même chose, toujours.
    assert (store.snapshot.enrichment_lag_entries > 0) == (store.snapshot.enrichment_lag_s > 0)


# ---------------------------------------------------------------------------
# Atomicité de l'instantané
# ---------------------------------------------------------------------------


def test_une_operation_refusee_ne_change_ni_la_revision_ni_le_contenu():
    store, _ = bound_store()
    observe(store, 0, seconds=0)
    put(store, topic(1, seconds=0))
    before = store.snapshot
    refusals = [
        store.observe(SESSION, "u-trop-long", "x" * (MAX_TAIL_ENTRY_CHARS + 1), spoken_at=at(5)),
        store.observe("autre-seance", "u9", "bonjour", spoken_at=at(5)),
        store.apply("pas une observation"),
        store.apply(PresentationObservation("obs-x", "autre-seance", topic(2, seconds=5))),
    ]
    assert all(not item.applied for item in refusals)
    assert store.snapshot is before
    assert store.snapshot.revision == before.revision
    # Et le magasin non plus n'a rien écrit : l'instantané n'est pas le seul
    # état, et un refus qui salirait la mémoire des ressources retirées serait
    # invisible d'ici.
    assert store.retired_resource_ids == ()


def test_un_refus_de_capacite_n_ecrit_rien_et_ne_bannit_aucune_ressource():
    """B1(b) : une capacité pleine est transitoire, pas une condamnation."""

    store, _ = bound_store()
    for index in range(1, MAX_PREPARED_RESOURCES + 1):
        put(store, resource(index, seconds=100 + index), observation=f"obs-{index}")
    before = store.snapshot
    refused = put(store, resource(99, seconds=0), observation="obs-perdante")
    assert refused.disposition is VoiceStateDisposition.CAPACITY
    assert refused.code == "presentation_resources_full"
    assert store.snapshot is before
    assert store.retired_resource_ids == ()
    # La même ressource, préparée plus fraîche, gagne la place : Slice 08
    # reprépare après un refus de capacité, et doit pouvoir.
    again = put(store, resource(99, seconds=500), observation="obs-reprise")
    assert again.applied
    assert "r99" in {item.resource_id for item in store.snapshot.working_set.resources}


def test_l_instantane_ne_peut_pas_annoncer_une_ressource_que_le_magasin_refusera():
    """B1(a) : ce que l'instantané montre, le magasin doit savoir le servir."""

    store, _ = bound_store(record_max_age_s=60)
    for index in range(1, MAX_PREPARED_RESOURCES + 1):
        put(store, resource(index, seconds=100 + index), observation=f"obs-{index}")
    held = [item.resource_id for item in store.snapshot.working_set.resources]
    assert len(held) == MAX_PREPARED_RESOURCES
    refused = put(store, resource(99, seconds=0), observation="obs-perdante")
    assert not refused.applied
    assert store.retired_resource_ids == ()
    # Chaque ressource encore visible dans l'instantané est encore servie.
    for resource_id in held:
        assert store.use_resource(resource_id, at=at(120)).applied, resource_id


def test_un_enregistrement_observe_apres_sa_derniere_vue_est_refuse_a_la_porte():
    """La forme qui permettait à un refus d'avancer l'horloge du magasin.

    Une provenance d'aujourd'hui sur une récence d'il y a une heure : le
    magasin avançait son horloge sur la première puis jugeait l'enregistrement
    trop vieux sur la seconde, en emportant au passage ce que l'âge venait de
    condamner. Elle ne se construit plus.
    """

    with pytest.raises(ValueError):
        replace(claim(2, seconds=0), provenance=provenance(2, seconds=1_000))
    with pytest.raises(ValueError):
        replace(topic(2, seconds=0), provenance=provenance(2, seconds=1_000))
    with pytest.raises(ValueError):
        replace(resource(2, seconds=0), provenance=provenance(2, seconds=1_000))


def test_un_instantane_deja_pris_ne_bouge_pas_quand_le_magasin_ecrit():
    store, _ = bound_store()
    observe(store, 0, seconds=0)
    put(store, topic(1, seconds=0))
    taken = store.snapshot
    observe(store, 1, seconds=10)
    put(store, topic(2, seconds=10))
    assert len(taken.tail.entries) == 1
    assert len(taken.working_set.topics) == 1
    assert taken.revision < store.snapshot.revision


def test_une_lecture_faite_pendant_une_ecriture_voit_un_instant_coherent():
    """Le couple lu depuis le journal du magasin n'est jamais à moitié écrit."""

    store, sink = bound_store()
    observe(store, 0, seconds=0)
    put(store, topic(1, seconds=0))
    seen: list[tuple] = []

    def reader(kind: str, data: dict) -> None:
        snapshot = store.snapshot
        seen.append((kind, snapshot.revision, len(snapshot.tail.entries),
                     len(snapshot.working_set.topics), snapshot.counts()["topics"]))

    sink.hook = reader
    observe(store, 1, seconds=10)
    put(store, topic(2, seconds=10))
    assert len(seen) == 2
    tail_line, topic_line = seen
    # L'écriture du fil n'a pas amputé l'ensemble de travail...
    assert tail_line[2] == 2 and tail_line[3] == 1
    # ...et l'écriture de l'ensemble n'a pas amputé le fil.
    assert topic_line[2] == 2 and topic_line[3] == 2
    # Les comptes journalisés décrivent le même instant que l'instantané lu.
    assert topic_line[3] == topic_line[4]
    assert tail_line[1] < topic_line[1]


def test_une_validation_qui_leve_pendant_le_commit_laisse_l_instantane_intact(monkeypatch):
    import jarvis.core.presentation_working_set as module

    store, _ = bound_store()
    observe(store, 0, seconds=0)
    before = store.snapshot

    def explode(*args, **kwargs):
        raise ValueError("commit refuse")

    monkeypatch.setattr(module, "PresentationContextSnapshot", explode)
    with pytest.raises(ValueError):
        observe(store, 1, seconds=10)
    assert store.snapshot is before
    assert len(store.snapshot.tail.entries) == 1


def test_un_instantane_est_immuable_et_n_autorise_aucune_action():
    snapshot = PresentationContextSnapshot(
        session_id=SESSION, generation=1, revision=1, as_of=at(0),
    )
    assert snapshot.authorizes_actions is False
    with pytest.raises(FrozenInstanceError):
        snapshot.session_id = "autre"
    with pytest.raises((AttributeError, FrozenInstanceError, ValueError)):
        snapshot.authorizes_actions = True


# ---------------------------------------------------------------------------
# Cycle de vie
# ---------------------------------------------------------------------------


def filled_store(**kwargs) -> tuple[PresentationWorkingSetStore, SpyDiagnostics]:
    store, sink = bound_store(**kwargs)
    observe(store, 0, seconds=0)
    put(store, topic(1, seconds=0))
    put(store, resource(1, seconds=0))
    return store, sink


def test_quitter_presentation_retire_la_seance_immediatement():
    store, sink = filled_store()
    result = store.apply_interaction_mode("assistant")
    assert result.applied and result.code == "presentation_working_set_retired"
    snapshot = store.snapshot
    assert snapshot.session_id is None and not snapshot.active
    assert snapshot.tail.entries == () and snapshot.working_set.topics == ()
    assert RETIRED_KIND in sink.kinds()


def test_le_mode_reserve_reunion_ne_maintient_pas_une_seance_de_presentation():
    """`behaving_interaction_mode` est la lecture de comportement, pas d'affichage."""

    store, _ = filled_store()
    result = store.apply_interaction_mode("meeting")
    assert result.applied
    assert store.snapshot.session_id is None


@pytest.mark.parametrize("value", ["fromage", None, 42, b"presentation", object()])
def test_un_mode_illisible_retire_la_seance_plutot_que_de_la_laisser_vivre(value):
    store, _ = filled_store()
    assert store.apply_interaction_mode(value).applied
    assert store.snapshot.session_id is None


def test_rester_en_presentation_ne_retire_rien():
    store, _ = filled_store()
    result = store.apply_interaction_mode("presentation")
    assert result.disposition is VoiceStateDisposition.IGNORED
    assert result.code == "presentation_mode_still_active"
    assert store.snapshot.session_id == SESSION
    assert len(store.snapshot.tail.entries) == 1


def test_la_fin_de_seance_vide_les_deux_moities():
    store, _ = filled_store()
    assert store.end_session().applied
    assert store.snapshot.working_set == PresentationWorkingSet()
    assert store.snapshot.tail == PresentationTranscriptTail()


def test_retirer_une_seance_deja_retiree_ne_fait_rien_et_le_dit():
    store, _ = filled_store()
    store.end_session()
    again = store.end_session()
    assert again.disposition is VoiceStateDisposition.IGNORED
    assert again.code == "presentation_working_set_inactive"


def test_une_observation_de_la_seance_retiree_n_atterrit_pas_dans_la_suivante():
    store, _ = filled_store()
    store.end_session()
    store.bind_session("presentation-2")
    late_tail = store.observe(SESSION, "u-tardive", "reste de l'ancienne seance", spoken_at=at(50))
    late_record = put(store, topic(9, seconds=50), session=SESSION)
    assert late_tail.disposition is VoiceStateDisposition.STALE_SESSION
    assert late_record.disposition is VoiceStateDisposition.STALE_SESSION
    assert store.snapshot.tail.entries == ()
    assert store.snapshot.working_set.topics == ()


def test_lier_une_nouvelle_seance_retire_la_precedente_et_fait_monter_la_generation():
    store, _ = filled_store()
    first = store.generation
    store.bind_session("presentation-2")
    assert store.generation > first + 1  # un retrait puis une liaison
    assert store.snapshot.tail.entries == ()
    assert store.snapshot.session_id == "presentation-2"


def test_lier_deux_fois_la_meme_seance_ne_la_vide_pas():
    store, _ = filled_store()
    again = store.bind_session(SESSION)
    assert again.disposition is VoiceStateDisposition.DUPLICATE
    assert len(store.snapshot.tail.entries) == 1


def test_un_magasin_sans_seance_ecarte_tout_sans_rien_fabriquer():
    sink = SpyDiagnostics()
    store = PresentationWorkingSetStore(diagnostics=sink)
    tail = store.observe(SESSION, "u0", "bonjour", spoken_at=at(0))
    record = put(store, topic(1, seconds=0))
    assert tail.disposition is VoiceStateDisposition.IGNORED
    assert record.disposition is VoiceStateDisposition.IGNORED
    assert tail.code == record.code == "presentation_working_set_inactive"
    assert store.snapshot.revision == 0


def test_le_rang_des_enonciations_repart_de_zero_a_chaque_seance():
    """Rien ne survit à un retrait, pas même un compteur."""

    store, _ = bound_store()
    for index in range(6):
        observe(store, index, seconds=index)
    first = [item.sequence for item in store.snapshot.tail.entries]
    assert first == [1, 2, 3, 4, 5, 6]
    store.end_session()
    store.bind_session("presentation-2")
    assert store.observe("presentation-2", "u0", "nouvelle seance", spoken_at=at(0)).applied
    assert [item.sequence for item in store.snapshot.tail.entries] == [1]


def test_un_commit_qui_leve_ne_brule_pas_un_rang_d_enonciation(monkeypatch):
    import jarvis.core.presentation_working_set as module

    store, _ = bound_store()
    observe(store, 0, seconds=0)
    original = module.PresentationContextSnapshot
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        raise ValueError("commit refuse")

    monkeypatch.setattr(module, "PresentationContextSnapshot", flaky)
    with pytest.raises(ValueError):
        observe(store, 1, seconds=10)
    monkeypatch.setattr(module, "PresentationContextSnapshot", original)
    assert calls["n"] == 1
    assert observe(store, 2, seconds=20).applied
    # Le rang 2 n'a pas ete consomme par l'appel qui a leve.
    assert [item.sequence for item in store.snapshot.tail.entries] == [1, 2]


def test_rien_ne_survit_a_la_reconstruction_du_magasin():
    """Décision D13 : la séance est éphémère, et rien n'en est écrit ailleurs."""

    first, _ = filled_store()
    assert first.snapshot.working_set.topics
    second = PresentationWorkingSetStore()
    assert second.snapshot.session_id is None
    assert second.snapshot.working_set == PresentationWorkingSet()
    assert second.snapshot.tail == PresentationTranscriptTail()
    assert second.revision == 0
    # Et une nouvelle séance du même nom ne retrouve rien de l'ancienne.
    second.bind_session(SESSION)
    assert second.snapshot.working_set.topics == ()


def test_le_changement_de_mode_de_core_retire_la_seance_sans_un_tour_de_boucle():
    class Bus:
        def __init__(self) -> None:
            self.published = []

        async def publish(self, envelope) -> None:
            self.published.append(envelope)

    async def scenario() -> None:
        bus = Bus()
        service = InteractionModeService(events=bus, epoch="epoque-test")
        store, _ = filled_store()
        service.add_listener(store.apply_interaction_mode)
        await service.request("presentation", source="test")
        assert store.snapshot.session_id == SESSION
        await service.request("assistant", source="test")
        assert store.snapshot.session_id is None
        assert len(bus.published) == 2

    asyncio.run(scenario())


def test_la_seance_est_retiree_avant_que_le_changement_ne_soit_publie():
    """L'ordre est la garantie, et il doit casser si on l'inverse.

    Compter les publications *après* que tout a tourné n'ordonne rien : la
    séance serait retirée un tour de boucle plus tard et ce test passerait
    quand même. L'abonné regarde donc le bus **au moment où il est appelé**.
    """

    class Bus:
        def __init__(self) -> None:
            self.published = []

        async def publish(self, envelope) -> None:
            self.published.append(envelope)

    async def scenario() -> None:
        bus = Bus()
        service = InteractionModeService(events=bus, epoch="epoque-test")
        store, _ = filled_store()
        seen: list[tuple[int, bool]] = []

        def listener(mode):
            # Ce que le monde extérieur sait déjà au moment où la séance part.
            store.apply_interaction_mode(mode)
            seen.append((len(bus.published), store.active))

        await service.request("presentation", source="test")
        service.add_listener(listener)
        published_before = len(bus.published)
        await service.request("assistant", source="test")
        assert seen == [(published_before, False)], seen
        assert len(bus.published) == published_before + 1

    asyncio.run(scenario())


def test_un_abonne_de_mode_lit_deja_la_nouvelle_valeur_quand_il_est_appele():
    class Bus:
        async def publish(self, envelope) -> None:
            return None

    async def scenario() -> None:
        service = InteractionModeService(events=Bus(), epoch="epoque-test")
        seen: list[tuple] = []
        service.add_listener(lambda mode: seen.append((mode, service.mode, service.revision)))
        await service.request("presentation", source="test")
        assert seen and seen[0][0] is seen[0][1]
        assert seen[0][2] == 1

    asyncio.run(scenario())


def test_un_observateur_de_mode_en_echec_n_empeche_pas_le_changement_de_mode():
    class Bus:
        async def publish(self, envelope) -> None:
            return None

    class Sink:
        def __init__(self) -> None:
            self.records = []

        def emit(self, kind, message, *, level="info", data=None):
            self.records.append((kind, level, dict(data or {}), message))

    async def scenario() -> None:
        sink = Sink()
        service = InteractionModeService(events=Bus(), diagnostics=sink, epoch="epoque-test")

        def broken(mode):
            raise RuntimeError("abonne casse " + "x" * 5_000)

        service.add_listener(broken)
        state, _ = await service.request("presentation", source="test")
        assert state.mode.value == "presentation"
        failures = [item for item in sink.records if item[0] == "interaction.mode.listener_failed"]
        assert failures and failures[0][1] == "error"
        # Le message dit la vraie cause, et il est borne : il vient d'un
        # abonne, donc d'ailleurs, et rien qui vienne d'ailleurs ne remplit ce
        # journal.
        assert "RuntimeError" in failures[0][3]
        assert len(failures[0][3]) <= 200 + 64

    asyncio.run(scenario())


def test_core_cable_la_memoire_de_seance_sur_le_mode_vivant(tmp_path):
    """Le câblage existe dans la composition réelle, pas seulement dans un test.

    Un `JarvisCoreApplication` est construit pour de bon, puis on lui demande le
    mode par son propre service : la séance doit se retirer sans que ce test
    n'ait câblé quoi que ce soit lui-même.
    """

    from jarvis.core.v2_app import JarvisCoreApplication

    async def scenario() -> None:
        core = JarvisCoreApplication(data_root=tmp_path / "data")
        store = core.presentation_working_set
        assert isinstance(store, PresentationWorkingSetStore)
        assert store.bind_session(SESSION).applied
        assert store.observe(SESSION, "u0", "la marge a double", spoken_at=at(0)).applied
        await core.interaction_mode.request("presentation", source="test")
        assert store.snapshot.session_id == SESSION
        await core.interaction_mode.request("assistant", source="test")
        assert store.snapshot.session_id is None
        assert store.snapshot.tail.entries == ()

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Vie privée : pas d'audio brut, pas de parole dans le journal
# ---------------------------------------------------------------------------


RAW_AUDIO = [b"\x00\x01\x02pcm", bytearray(b"\x00\x01pcm"), memoryview(b"\x00\x01pcm")]


@pytest.mark.parametrize("payload", RAW_AUDIO)
def test_le_fil_refuse_un_tampon_d_audio_brut(payload):
    store, _ = bound_store()
    result = store.observe(SESSION, "u0", payload, spoken_at=at(0))
    assert result.disposition is VoiceStateDisposition.REJECTED
    assert result.code == "presentation_tail_entry_invalid"
    assert store.snapshot.tail.entries == ()


@pytest.mark.parametrize("payload", RAW_AUDIO)
def test_aucun_champ_de_texte_d_un_enregistrement_n_accepte_un_tampon_d_audio(payload):
    builders = [
        lambda: replace(topic(1), label=payload),
        lambda: replace(entity(1), label=payload),
        lambda: replace(entity(1), kind=payload),
        lambda: replace(claim(1), statement=payload),
        lambda: replace(source(1), reference=payload),
        lambda: replace(source(1), title=payload),
        lambda: replace(question(1), text=payload),
        lambda: replace(attention(1), reason=payload),
        lambda: ResourceReference(kind=ResourceKind.NOTE, locator=payload),
        lambda: ResourceReference(kind=ResourceKind.NOTE, locator="note:1", title=payload),
        lambda: ResourceReference(kind=ResourceKind.NOTE, locator="note:1",
                                  descriptor={"serie": [payload]}),
        lambda: TranscriptTailEntry(utterance_id="u0", sequence=1, text=payload, spoken_at=at(0)),
    ]
    for build in builders:
        with pytest.raises((TypeError, ValueError)):
            build()


def test_aucun_champ_d_enregistrement_ne_porte_un_nom_d_audio():
    """Rien ne s'appelle `pcm`, `audio`, `frames` : la forme interdit le sujet."""

    forbidden = ("audio", "pcm", "frame", "samples", "waveform", "bytes")
    for cls in RECORD_COLLECTIONS:
        for item in fields(cls):
            assert not any(word in item.name.lower() for word in forbidden), (cls, item.name)
    for item in fields(TranscriptTailEntry):
        assert not any(word in item.name.lower() for word in forbidden), item.name


def test_le_journal_ne_porte_jamais_le_texte_de_ce_qui_a_ete_dit():
    store, sink = bound_store()
    secret = "le chiffre confidentiel est quarante-deux"
    observe(store, 0, seconds=0, text=secret)
    store.observe(SESSION, "u0", secret + " corrige", spoken_at=at(1), revision=1)
    store.observe(SESSION, "u1", "x" * (MAX_TAIL_ENTRY_CHARS + 1), spoken_at=at(2))
    put(store, replace(topic(1, seconds=0), label="marge brute confidentielle"))
    put(store, replace(claim(1, seconds=0), statement=secret))
    put(store, question(1, seconds=0))
    store.end_session()
    assert sink.records
    for kind, message, _level, data in sink.records:
        blob = " ".join([kind, message, repr(data)])
        for needle in (secret, "quarante-deux", "confidentiel", "marge brute", "question 1"):
            assert needle not in blob, (kind, needle)


def test_les_cles_du_journal_restent_dans_une_liste_blanche():
    allowed = {
        "code", "collection", "record_id", "observation_id", "utterance_id", "sequence",
        "revision", "store_revision", "origin", "chars", "entries", "dropped",
        "observed_sequence", "disposition", "reason", "session_id", "generation",
        "tail_dropped", "records_dropped", "topics", "entities", "claims", "sources",
        "resources", "questions", "attention", "tail_entries", "tail_chars",
        "enrichment_lag_entries",
    }
    store, sink = bound_store()
    observe(store, 0, seconds=0)
    put(store, topic(1, seconds=0))
    put(store, resource(1, seconds=0))
    store.use_resource("r1", at=at(5))
    store.apply("pas une observation")
    store.prune(now=at(10_000))
    store.end_session()
    for kind, _message, _level, data in sink.records:
        assert set(data) <= allowed, (kind, sorted(set(data) - allowed))
        for key, value in data.items():
            assert isinstance(value, (str, int, float, bool)), (kind, key)
            if isinstance(value, str):
                assert len(value) <= MAX_JOURNALLED_VALUE_CHARS, (kind, key)


def test_le_chemin_normal_est_journalise_autant_que_les_refus():
    store, sink = bound_store()
    observe(store, 0, seconds=0)
    put(store, topic(1, seconds=0))
    kinds = sink.kinds()
    assert BOUND_KIND in kinds and TAIL_KIND in kinds and APPLIED_KIND in kinds
    assert all(level in ("info", "warning", "error") for _k, _m, level, _d in sink.records)


def test_un_journal_en_panne_n_empeche_pas_de_retenir_la_seance():
    class Broken:
        def emit(self, *args, **kwargs):
            raise RuntimeError("journal indisponible")

    store = PresentationWorkingSetStore(diagnostics=Broken())
    assert store.bind_session(SESSION).applied
    assert store.observe(SESSION, "u0", "bonjour", spoken_at=at(0)).applied
    assert len(store.snapshot.tail.entries) == 1


# ---------------------------------------------------------------------------
# Une ressource préparée est une référence, jamais un exécutable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "locator, code",
    [
        ("<script>alert(1)</script>", "presentation_resource_not_a_reference"),
        ("https://exemple.test/<img onerror=x>", "presentation_resource_not_a_reference"),
        ("javascript:alert(1)", "presentation_resource_scheme_not_allowed"),
        ("JavaScript:alert(1)", "presentation_resource_scheme_not_allowed"),
        ("data:text/html;base64,PHNjcmlwdD4=", "presentation_resource_scheme_not_allowed"),
        # Les deux que la liste noire de la premiere version laissait passer.
        ("vbscript:msgbox(1)", "presentation_resource_scheme_not_allowed"),
        ("data:image/svg+xml;base64,PHN2Zz4=", "presentation_resource_scheme_not_allowed"),
    ],
)
def test_une_ressource_preparee_refuse_une_charge_utile_executable(locator, code):
    with pytest.raises(PresentationWorkingSetError) as excinfo:
        ResourceReference(kind=ResourceKind.WEB_PAGE, locator=locator)
    assert excinfo.value.code == code
    # La meme regle protege la reference d'une source.
    with pytest.raises(PresentationWorkingSetError):
        replace(source(1), reference=locator)


@pytest.mark.parametrize(
    "locator",
    ["https://exemple.test/a", "http://exemple.test/a", "chart:marge", "scene:obj-7",
     "doc:1AbC", "file:///c/rapport.pdf", "rapports/2026/t1.pdf", "C:\\rapports\\t1.pdf",
     "identifiant-nu-42"],
)
def test_un_localisateur_legitime_passe_la_liste_blanche(locator):
    built = ResourceReference(kind=ResourceKind.DOCUMENT, locator=locator)
    assert built.locator == locator


def test_un_descripteur_ne_peut_pas_cacher_du_balisage():
    with pytest.raises(PresentationWorkingSetError):
        ResourceReference(
            kind=ResourceKind.CHART_DESCRIPTOR, locator="chart:1",
            descriptor={"titre": "<iframe src=x>"},
        )
    with pytest.raises(PresentationWorkingSetError):
        ResourceReference(
            kind=ResourceKind.CHART_DESCRIPTOR, locator="chart:1",
            descriptor={"<b>": "ok"},
        )


def test_un_descripteur_n_accepte_ni_structure_profonde_ni_objet_vivant():
    for descriptor in (
        {"serie": [{"x": 1}]},
        {"serie": {"imbrique": 1}},
        {"rappel": lambda: None},
        {"serie": [float("nan")]},
        "pas une table",
    ):
        with pytest.raises((PresentationWorkingSetError, ValueError, TypeError)):
            ResourceReference(kind=ResourceKind.CHART_DESCRIPTOR, locator="chart:1",
                              descriptor=descriptor)


def test_un_descripteur_est_borne_en_cles_en_valeurs_et_en_taille():
    with pytest.raises(ValueError):
        ResourceReference(
            kind=ResourceKind.CHART_DESCRIPTOR, locator="chart:1",
            descriptor={f"k{i}": i for i in range(MAX_DESCRIPTOR_KEYS + 1)},
        )
    with pytest.raises(ValueError):
        ResourceReference(
            kind=ResourceKind.CHART_DESCRIPTOR, locator="chart:1",
            descriptor={"serie": list(range(MAX_DESCRIPTOR_ITEMS + 1))},
        )
    with pytest.raises(ValueError):
        ResourceReference(
            kind=ResourceKind.CHART_DESCRIPTOR, locator="chart:1",
            descriptor={"a": "x" * 100, "b": "y" * 100, "c": "z" * 100, "d": "w" * 100,
                        "e": "v" * 100, "f": "u" * 100, "g": "t" * 100},
        )


def test_un_descripteur_legitime_de_graphique_passe():
    built = ResourceReference(
        kind=ResourceKind.CHART_DESCRIPTOR, locator="chart:marge",
        title="Marge brute par trimestre",
        descriptor={"labels": ["T1", "T2", "T3"], "values": [12.5, 13.0, 14.25],
                    "unit": "%", "seuil": "marge > 10"},
    )
    assert built.descriptor["seuil"] == "marge > 10"
    assert built.to_payload()["kind"] == "chart_descriptor"


@pytest.mark.parametrize(
    "build",
    [
        lambda: replace(topic(1), label="marge < 10 %"),
        lambda: replace(entity(1), label="societe <X>"),
        lambda: replace(claim(1), statement="la marge brute est < 10 % ce trimestre"),
        lambda: replace(question(1), text="pourquoi la marge est-elle < 10 % ?"),
        lambda: replace(attention(1), reason="chiffre annonce < source citee"),
    ],
)
def test_le_texte_venu_de_la_parole_garde_le_droit_au_chevron(build):
    """La regle de balisage vise les references, pas ce qui a ete dit.

    Une analyse francaise ordinaire produit « la marge < 10 % » ; la refuser
    avec un code parlant d'une *ressource* donnait a la Slice 06 une exception
    la ou elle attend une disposition typee.
    """

    built = build()
    assert "<" in str(
        getattr(built, "label", None) or getattr(built, "statement", None)
        or getattr(built, "text", None) or built.reason
    )


def test_une_affirmation_avec_un_chevron_se_range_normalement():
    store, _ = bound_store()
    result = put(store, replace(claim(1, seconds=0), statement="la marge < 10 %"))
    assert result.applied
    assert store.snapshot.working_set.claims[0].statement == "la marge < 10 %"


def test_le_texte_du_fil_peut_contenir_un_chevron_car_ce_n_est_pas_une_reference():
    store, _ = bound_store()
    assert store.observe(SESSION, "u0", "si a < b alors", spoken_at=at(0)).applied
    assert store.snapshot.tail.latest.text == "si a < b alors"


# ---------------------------------------------------------------------------
# Frontières d'architecture
# ---------------------------------------------------------------------------


def module_imports(path: Path) -> set[str]:
    found: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_ni_le_domaine_ni_le_magasin_n_importent_de_persistance():
    """Décision D13, sous forme vérifiable : rien ici ne sait écrire quelque part."""

    forbidden = ("sqlite", "adapter", "repository", "history", "jarvis.runtime", "jarvis.app")
    for relative in (
        "jarvis/domain/presentation_working_set.py",
        "jarvis/core/presentation_working_set.py",
    ):
        names = module_imports(ROOT / relative)
        leaked = {name for name in names if any(word in name.lower() for word in forbidden)}
        assert not leaked, (relative, sorted(leaked))


def test_le_magasin_ne_prend_du_port_de_diagnostic_que_le_puits():
    tree = ast.parse((ROOT / "jarvis/core/presentation_working_set.py").read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "jarvis.ports.v2"
        for alias in node.names
    }
    assert imported == {"DiagnosticSink"}


def test_le_domaine_de_la_seance_ne_depend_que_de_la_bibliotheque_standard():
    names = module_imports(ROOT / "jarvis/domain/presentation_working_set.py")
    assert {name for name in names if name.startswith("jarvis")} == {"jarvis.domain._checks"}


def test_le_magasin_parle_le_vocabulaire_de_disposition_deja_en_place():
    """Réutilisé, pas redécliné : une seule table pour « qu'est-il arrivé ? »."""

    store, _ = bound_store()
    observed = set()
    observed.add(store.bind_session(SESSION).disposition)  # DUPLICATE
    observed.add(observe(store, 0, seconds=0).disposition)  # APPLIED
    observed.add(store.observe("autre", "u1", "x", spoken_at=at(1)).disposition)  # STALE_SESSION
    observed.add(store.observe(SESSION, "u0", "x", spoken_at=at(1)).disposition)  # DUPLICATE
    observed.add(store.observe(SESSION, "u0", "x", spoken_at=at(1), revision=0).disposition)
    observed.add(store.apply(object()).disposition)  # REJECTED
    observed.add(store.use_resource("inconnue").disposition)  # IGNORED
    for index in range(MAX_WORKING_SET_TOPICS):
        put(store, topic(index, seconds=100 + index))
    observed.add(put(store, topic(99, seconds=0)).disposition)  # CAPACITY
    observed.add(store.observe(SESSION, "u0", "x", spoken_at=at(1), revision=0).disposition)
    assert observed <= set(VoiceStateDisposition)
    assert {
        VoiceStateDisposition.APPLIED, VoiceStateDisposition.DUPLICATE,
        VoiceStateDisposition.STALE_SESSION, VoiceStateDisposition.REJECTED,
        VoiceStateDisposition.IGNORED, VoiceStateDisposition.CAPACITY,
    } <= observed

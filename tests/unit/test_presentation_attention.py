"""Le point d'attention de Presentation : ce qui a le droit d'alerter (Slice 09).

D11 est verrouillée : *« une contradiction/incohérence significative crée un
petit signal sonore et un avertissement flottant. Jarvis n'explique pas
spontanément à voix haute. »*

Ce fichier tient les deux moitiés côté Python :

1. **ce qui devient une alerte**, et surtout ce qui n'en devient pas — un échec
   de recherche, une recherche sans conclusion, une pièce sans source connue,
   une confiance trop faible, un travail sans la capacité de vérifier ;
2. **ce qui ne peut jamais arriver** — rien ne parle, rien de ce qui a été dit
   dans la salle ne descend dans la trace, et écarter un avertissement ne
   touche aucun fait.

Les en-têtes de la forme « X ne peut jamais arriver » sont des cas de test ici,
et pas seulement des phrases : le LOG du handoff en a fait une règle après la
Slice 04.

La moitié visible est mesurée ailleurs, dans un vrai navigateur :
`test_presentation_attention_browser.py`.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest

from jarvis.core.presentation_attention import (
    ALLOWED_IMPORT_CLOSURE,
    MAX_ATTENTION_PER_BATCH,
    PresentationAttentionService,
)
from jarvis.core.presentation_speculative import (
    PreparedFinding,
    PresentationSpeculativeService,
    SpeculativeOutcome,
)
from jarvis.core.presentation_working_set import PresentationWorkingSetStore
from jarvis.domain.ambient_observation import AmbientTrigger, AmbientTriggerKind
from jarvis.domain.presentation_attention import (
    ALERTING_VERDICTS,
    ATTENTION_HEADLINES,
    ATTENTION_RAISED_KIND,
    HIGH_CONFIDENCE,
    MAX_ATTENTION_EVIDENCE,
    MIN_ATTENTION_CONFIDENCE,
    AttentionDecision,
    AttentionEvidence,
    AttentionRefusal,
    FactCheckAssessment,
    PresentationAttention,
    _check_alerting_table,
    attention_output_policy,
    confidence_band,
    decide_attention,
    severity_for,
)
from jarvis.domain.presentation_policy import PresentationSituation, may_speak
from jarvis.domain.presentation_speculative import SpeculativeAdmission
from jarvis.domain.presentation_working_set import (
    AttentionCategory,
    AttentionSeverity,
    ClaimStatus,
    ObservationProvenance,
    PresentationClaim,
    PresentationObservation,
    PresentationSource,
    PresentationWorkingSetError,
    ResourceKind,
    UtteranceOrigin,
)
from jarvis.domain.v2 import SpeechKind
from jarvis.runtime.background_events import (
    ATTENTION,
    MAX_ATTENTION_FIELD,
    BackgroundEvent,
    BackgroundEventLedger,
    TraceFollower,
    follow,
)

ROOT = Path(__file__).resolve().parents[2]
SESSION = "seance-09"
NOW = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)


# ==========================================================================
# 0. Fixtures — un ensemble de travail qui contient vraiment l'affirmation
# ==========================================================================


class Sink:
    """Puits de diagnostic en mémoire. Garde tout, pour qu'on puisse fouiller."""

    def __init__(self) -> None:
        self.lines: list[tuple[str, str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None):
        self.lines.append((kind, message, level, dict(data or {})))

    def kinds(self) -> list[str]:
        return [kind for kind, _, _, _ in self.lines]

    def of(self, kind: str) -> list[dict]:
        return [data for k, _, _, data in self.lines if k == kind]


def _provenance(sequence: int = 1) -> ObservationProvenance:
    return ObservationProvenance(
        utterance_id=f"utt-{sequence}", sequence=sequence, observed_at=NOW,
        origin=UtteranceOrigin.AMBIENT,
    )


def _store(*, claim_statement: str = "la marge est de 12 %") -> PresentationWorkingSetStore:
    """Un magasin lié, portant une affirmation et deux sources.

    La provenance est réelle : c'est elle qui rend la garde de provenance
    vérifiable plutôt que déclarée.
    """

    store = PresentationWorkingSetStore()
    assert store.bind_session(SESSION).applied
    # **Trois affirmations distinctes**, pas une : sans cela une « rafale » de
    # verdicts partage une clé de coalescence et le magasin les fond, de sorte
    # qu'un test de rafale ne mesure jamais une rafale (B4).
    for index in (1, 2, 3):
        claim = PresentationClaim(
            claim_id=f"claim-{index}", statement=f"{claim_statement} ({index})",
            provenance=_provenance(), first_seen_at=NOW, last_seen_at=NOW,
            status=ClaimStatus.ASSERTED, confidence=0.5, topic_id=None,
        )
        assert store.apply(PresentationObservation(f"claim-{index}", SESSION, claim)).applied
    for index in (1, 2):
        source = PresentationSource(
            source_id=f"src-{index}", kind=ResourceKind.WEB_PAGE,
            reference=f"https://exemple.test/{index}", title=f"Source {index}",
            retrieved_at=NOW,
        )
        assert store.apply(PresentationObservation(f"src-{index}", SESSION, source)).applied
    return store


def _evidence(source_id: str = "src-1") -> AttentionEvidence:
    return AttentionEvidence(
        source_id=source_id, locator="https://exemple.test/1", title="Source 1",
        resource_id="res-1",
    )


def _assessment(**over) -> FactCheckAssessment:
    base = dict(
        claim_id="claim-1", verdict=ClaimStatus.CONTRADICTED, confidence=0.9,
        evidence=(_evidence(),), topic_id=None,
        reason="la source annonce 9 %", searched=True,
    )
    base.update(over)
    return FactCheckAssessment(**base)


def _decide(assessment, *, store=None, may_verify=True, attention_id="att-1"):
    snapshot = (store or _store()).snapshot.working_set
    return decide_attention(
        assessment,
        attention_id=attention_id, raised_at=NOW,
        known_claim_ids=frozenset(c.record_id for c in snapshot.claims),
        known_source_ids=frozenset(s.record_id for s in snapshot.sources),
        may_verify=may_verify,
    )


# ==========================================================================
# 1. Une contradiction soutenue produit exactement un point d'attention
# ==========================================================================


def test_une_contradiction_soutenue_leve_un_point_d_attention():
    """Le cas nominal : verdict, pièce, source connue, confiance au-dessus du seuil."""

    decision = _decide(_assessment())
    assert decision.alerted, decision.code
    raised = decision.raised
    assert raised.category is AttentionCategory.CONTRADICTION
    assert raised.severity is AttentionSeverity.WARNING
    assert raised.claim_id == "claim-1"
    assert raised.source_ids == ("src-1",)
    assert raised.headline == ATTENTION_HEADLINES[AttentionCategory.CONTRADICTION]
    assert decision.code == "attention_raised"


def test_la_meme_contradiction_deux_fois_est_un_seul_point_et_une_seule_ligne():
    """« Deux fois la même contradiction est un seul son. »

    La coalescence du magasin de la Slice 04 porte sur
    `(catégorie, affirmation, sujet)`. Le service doit s'en servir et **ne pas
    reposer de ligne de trace** sur le second passage : sans ligne, le numéro de
    séquence du registre ne monte pas, donc rien ne sonne une seconde fois.
    """

    store, sink = _store(), Sink()
    service = PresentationAttentionService(store=store, diagnostics=sink, clock=lambda: NOW)
    service.raise_from_assessments([_assessment()], job_id="j1", session_id=SESSION,
                                   may_verify=True)
    service.raise_from_assessments([_assessment()], job_id="j2", session_id=SESSION,
                                   may_verify=True)

    raised_lines = [k for k in sink.kinds() if k == ATTENTION_RAISED_KIND]
    assert len(raised_lines) == 1, sink.kinds()
    assert service.counters.raised == 1
    assert service.counters.coalesced == 1
    assert len(store.snapshot.working_set.attention) == 1


def test_une_rafale_de_contradictions_distinctes_ne_fait_pas_une_rafale_de_sons():
    """**B4.** La borne par defaut, et des verdicts qui ne se confondent pas.

    La version precedente de ce test prouvait deux fois rien : elle abaissait
    `max_per_batch` a 1, donc **`MAX_ATTENTION_PER_BATCH` n'etait reference par
    aucun test** et pouvait valoir mille sans que rien ne bouge ; et ses deux
    verdicts partageaient une cle de coalescence, donc supprimer l'ecretage
    entier n'aurait rien change d'observable — le magasin aurait fondu le
    second et le resultat serait reste un point, une ligne, un son.

    Ici la borne est celle de production et les trois verdicts portent des
    affirmations **distinctes**, donc trois points possibles. La propriete
    mesuree est celle que la docstring nomme : le nombre de lignes posees,
    c'est-a-dire le nombre de sons.
    """

    store, sink = _store(), Sink()
    service = PresentationAttentionService(store=store, diagnostics=sink, clock=lambda: NOW)
    batch = [_assessment(claim_id=f"claim-{i}") for i in (1, 2, 3)]
    decisions = service.raise_from_assessments(batch, job_id="j1", session_id=SESSION,
                                               may_verify=True)

    assert len(decisions) == MAX_ATTENTION_PER_BATCH == 2
    assert service.counters.clipped_batch == len(batch) - MAX_ATTENTION_PER_BATCH == 1
    assert "presentation.attention.batch_clipped" in sink.kinds()
    # Le coeur : deux sons possibles, pas trois.
    assert len([k for k in sink.kinds() if k == ATTENTION_RAISED_KIND]) == 2
    assert service.counters.raised == 2
    assert {a.claim_id for a in store.snapshot.working_set.attention} == {"claim-1", "claim-2"}


# ==========================================================================
# 2. « Un échec de recherche n'est jamais une contradiction »
#    — l'en-tête est le cas de test
# ==========================================================================


def test_une_recherche_ratee_ne_devient_jamais_une_contradiction():
    """Le cas hostile, et non le cas poli.

    Un exécutant peut se tromper **dans le sens qui coûte** : rendre
    `CONTRADICTED` alors que sa recherche n'a pas abouti. Le refus est donc
    posé avant même que le verdict ne soit regardé, et c'est cet ordre-là que
    ce test épingle — un test qui n'enverrait qu'un `searched=False` poli avec
    un verdict neutre n'atteindrait jamais la garde.
    """

    decision = _decide(_assessment(verdict=ClaimStatus.CONTRADICTED, searched=False))
    assert not decision.alerted
    assert decision.refusal is AttentionRefusal.SEARCH_FAILED
    assert decision.verdict is ClaimStatus.CONTRADICTED


@pytest.mark.parametrize("verdict", [ClaimStatus.UNCERTAIN, ClaimStatus.SUPPORTED,
                                     ClaimStatus.ASSERTED])
def test_une_recherche_sans_conclusion_ne_devient_pas_une_alerte(verdict):
    """`UNCERTAIN` existe précisément pour ça (Slice 04) : vérifié sans conclure."""

    decision = _decide(_assessment(verdict=verdict))
    assert decision.refusal is AttentionRefusal.NOT_ALERTING, decision


def test_la_table_d_alerte_ne_peut_pas_accueillir_un_verdict_non_concluant(monkeypatch):
    """La garde d'import rencontre l'état qu'elle interdit, et pas seulement l'état sain.

    C'est le motif que trois Slices de suite ont payé : *une garde dont le code
    tourne à chaque import sans jamais rencontrer l'état qu'elle existe pour
    refuser*. On empoisonne donc la table et on exige le refus.
    """

    poisoned = dict(ALERTING_VERDICTS)
    poisoned[ClaimStatus.UNCERTAIN] = AttentionCategory.CONTRADICTION
    monkeypatch.setattr("jarvis.domain.presentation_attention.ALERTING_VERDICTS", poisoned)
    with pytest.raises(PresentationWorkingSetError) as refused:
        _check_alerting_table()
    assert refused.value.code == "attention_table_invalid"
    assert "uncertain" in refused.value.message


def test_la_table_saine_passe_la_garde():
    """Et elle passe : sans cette moitié, le test précédent prouverait n'importe quoi."""

    _check_alerting_table()
    assert set(ALERTING_VERDICTS) == {ClaimStatus.CONTRADICTED}
    assert set(ALERTING_VERDICTS.values()) == {AttentionCategory.CONTRADICTION}


# ==========================================================================
# 3. Preuve, provenance, confiance
# ==========================================================================


def test_sans_piece_il_n_y_a_pas_d_alerte():
    assert _decide(_assessment(evidence=())).refusal is AttentionRefusal.NO_EVIDENCE


def test_une_piece_qui_ne_designe_aucune_source_connue_est_refusee():
    """La provenance est **vérifiée** contre l'ensemble de travail, pas déclarée.

    Un exécutant qui inventerait une source passerait tous les autres
    contrôles : c'est le seul qui l'arrête.
    """

    decision = _decide(_assessment(evidence=(_evidence("src-inventee"),)))
    assert decision.refusal is AttentionRefusal.PROVENANCE_UNKNOWN


def test_une_affirmation_absente_de_l_ensemble_de_travail_est_refusee():
    decision = _decide(_assessment(claim_id="claim-fantome"))
    assert decision.refusal is AttentionRefusal.CLAIM_UNKNOWN


def test_sous_le_seuil_de_confiance_rien_n_est_signale():
    just_under = MIN_ATTENTION_CONFIDENCE - 0.01
    assert _decide(_assessment(confidence=just_under)).refusal is AttentionRefusal.LOW_CONFIDENCE
    assert _decide(_assessment(confidence=MIN_ATTENTION_CONFIDENCE)).alerted


def test_la_gravite_et_la_bande_viennent_de_la_confiance_et_de_rien_d_autre():
    """L'exécutant ne nomme ni l'une ni l'autre : la Slice 07 a payé cette leçon.

    Un producteur qui choisit son étiquette transforme un plafond en champ de
    formulaire. Ici les deux sont calculées, et le test les calcule de part et
    d'autre du seuil plutôt que de relire la table.
    """

    assert severity_for(HIGH_CONFIDENCE) is AttentionSeverity.WARNING
    assert severity_for(HIGH_CONFIDENCE - 0.01) is AttentionSeverity.NOTICE
    assert confidence_band(HIGH_CONFIDENCE) == "high"
    assert confidence_band(MIN_ATTENTION_CONFIDENCE) == "moderate"
    # Et le verdict ne peut pas les porter : le type n'a pas ces champs.
    assert not hasattr(_assessment(), "severity")
    assert not hasattr(_assessment(), "category")


def test_la_capacite_est_lue_avant_tout_le_reste():
    """Un travail qui n'avait pas le droit de vérifier n'alerte pas, quoi qu'il rende.

    Et le diagnostic rendu est bien **celui-là** et non un refus plus tardif :
    l'ordre des contrôles est ce qui rend le journal utile.
    """

    decision = _decide(_assessment(searched=False, evidence=()), may_verify=False)
    assert decision.refusal is AttentionRefusal.CAPABILITY_MISSING


def test_une_entree_qui_n_est_pas_un_verdict_est_refusee_et_nommee():
    for hostile in (None, "contradicted", 42, object(), {"verdict": "contradicted"}):
        assert _decide(hostile).refusal is AttentionRefusal.INVALID, hostile


def test_un_evenement_d_attention_ne_peut_pas_exister_sans_preuve():
    """L'en-tete du type dit « au moins une piece ». C'est donc un cas de test.

    Survivant de mutation M14 : remplacer le `or` de la garde par un `and`
    rendait `evidence=()` constructible, et **aucun test ne le voyait** — parce
    que tous passaient par `decide_attention`, qui refuse les pieces vides une
    etape plus tot. L'invariant du type n'etait garde que par celui de la
    porte, et une garde qui n'est jamais atteinte seule n'est pas gardee.
    """

    legal = dict(attention_id="att-1", category=AttentionCategory.CONTRADICTION,
                 severity=AttentionSeverity.NOTICE, confidence=0.7, raised_at=NOW,
                 claim_id="claim-1", evidence=(_evidence(),))
    assert PresentationAttention(**legal).source_ids == ("src-1",)
    for broken in ({"evidence": ()}, {"evidence": []}, {"evidence": None},
                   {"evidence": tuple(_evidence(f"src-{i}") for i in range(5))},
                   {"evidence": ("pas une piece",)}):
        with pytest.raises((TypeError, ValueError)):
            PresentationAttention(**{**legal, **broken})


def test_chaque_refus_est_compte_sous_son_propre_code():
    """Les compteurs sont l'observabilite que ce module revendique : on l'exerce.

    Survivant de mutation M20 : supprimer `counters.refuse(...)` ne cassait
    rien. Un invariant qu'on ne peut pas lire est un invariant qui derive
    (Slice 04) — mais un compteur que personne ne lit n'est pas lisible non
    plus. Les refus sont comptes **un par un**, sous le code exact, pour
    qu'aucun ne se range dans un fourre-tout (Slice 06).
    """

    store, sink = _store(), Sink()
    service = PresentationAttentionService(store=store, diagnostics=sink, clock=lambda: NOW)
    cases = [
        (_assessment(searched=False), AttentionRefusal.SEARCH_FAILED),
        (_assessment(verdict=ClaimStatus.UNCERTAIN), AttentionRefusal.NOT_ALERTING),
        (_assessment(evidence=()), AttentionRefusal.NO_EVIDENCE),
        (_assessment(claim_id="claim-fantome"), AttentionRefusal.CLAIM_UNKNOWN),
        (_assessment(evidence=(_evidence("src-inventee"),)), AttentionRefusal.PROVENANCE_UNKNOWN),
        (_assessment(confidence=0.1), AttentionRefusal.LOW_CONFIDENCE),
        ("pas un verdict", AttentionRefusal.INVALID),
    ]
    for index, (assessment, expected) in enumerate(cases):
        decisions = service.raise_from_assessments([assessment], job_id=f"j{index}",
                                                   session_id=SESSION, may_verify=True)
        assert decisions[0].refusal is expected, (index, decisions[0].code)
    service.raise_from_assessments([_assessment()], job_id="jx", session_id=SESSION,
                                   may_verify=False)

    assert service.counters.refusals == {
        AttentionRefusal.SEARCH_FAILED.value: 1,
        AttentionRefusal.NOT_ALERTING.value: 1,
        AttentionRefusal.NO_EVIDENCE.value: 1,
        AttentionRefusal.CLAIM_UNKNOWN.value: 1,
        AttentionRefusal.PROVENANCE_UNKNOWN.value: 1,
        AttentionRefusal.LOW_CONFIDENCE.value: 1,
        AttentionRefusal.INVALID.value: 1,
        AttentionRefusal.CAPABILITY_MISSING.value: 1,
    }, service.counters.refusals
    assert service.counters.assessed == 8
    assert service.counters.raised == 0
    assert sum(service.counters.refusals.values()) == service.counters.assessed


def test_une_decision_ne_peut_etre_ni_les_deux_ni_aucune():
    """L'ambiguïté que ce type existe pour supprimer, exercée aux deux bords."""

    with pytest.raises(ValueError):
        AttentionDecision()
    with pytest.raises(ValueError):
        AttentionDecision(raised=_decide(_assessment()).raised,
                          refusal=AttentionRefusal.NO_EVIDENCE)


# ==========================================================================
# 3b. « Elle ne lève jamais » — la promesse, exercée là où elle peut casser
# ==========================================================================
#
# B3 : la totalité était affirmée trois fois et fausse deux fois, et aucun test
# n'atteignait le bord. C'est la forme exacte de la mutation M14, que j'avais
# trouvée et corrigée à un endroit sans balayer la classe : elle se répétait
# trois fois de plus dans les deux mêmes modules. Une promesse de totalité
# défendue seulement là où le chemin heureux passe n'est pas défendue.


@pytest.mark.parametrize("hostile", [None, 42, object(), "des identifiants"])
def test_la_porte_ne_leve_pas_sur_un_instantane_inutilisable(hostile):
    """Les ensembles d'identifiants sont construits hors du `try` : on les casse.

    `set(None)` lève un `TypeError` nu, donc un refus **non typé** que la porte
    ne rattrape pas — et son en-tête promet qu'elle ne lève jamais. L'appelant
    de production l'enveloppe, donc ce n'était pas un plantage vivant ; c'était
    une promesse fausse, ce qui est pire, parce que le prochain appelant la
    croira.
    """

    decision = decide_attention(
        _assessment(), attention_id="att-1", raised_at=NOW,
        known_claim_ids=hostile, known_source_ids=hostile, may_verify=True,
    )
    assert not decision.alerted
    assert decision.refusal is AttentionRefusal.INVALID


def test_la_porte_nomme_un_evenement_qu_elle_ne_peut_pas_construire():
    """`NOT_CONSTRUCTIBLE` n'était atteint par rien dans tout le dépôt.

    Supprimer son `try/except` ne faisait échouer aucun test — et c'est
    pourtant la seule chose qui rende la promesse de totalité vraie sur le seul
    chemin réellement faillible de cette fonction.
    """

    decision = _decide(_assessment(), attention_id="   ")
    assert decision.refusal is AttentionRefusal.NOT_CONSTRUCTIBLE
    naive = decide_attention(
        _assessment(), attention_id="att-1",
        raised_at=datetime(2026, 9, 24, 10, 0),  # sans fuseau : refusée par la Slice 04
        known_claim_ids={"claim-1"}, known_source_ids={"src-1"}, may_verify=True,
    )
    assert naive.refusal is AttentionRefusal.NOT_CONSTRUCTIBLE


@pytest.mark.parametrize("hostile", [None, 42, object()])
def test_le_service_ne_leve_pas_sur_un_lot_qui_n_est_pas_iterable(hostile):
    """`list(assessments)` était hors de toute garde."""

    service = PresentationAttentionService(store=_store(), diagnostics=Sink(),
                                           clock=lambda: NOW)
    assert service.raise_from_assessments(hostile, job_id="j1", session_id=SESSION,
                                          may_verify=True) == ()
    assert service.counters.batches_invalid == 1


def test_le_service_ne_leve_pas_quand_le_magasin_lui_meme_casse():
    """Le magasin est total par construction — mais c'est un `Any` injecté.

    Les tests existants couvraient un magasin qui **refuse** ; aucun ne
    couvrait un magasin qui **lève**. La Slice 06 a payé exactement cette
    distinction sur son puits d'observation.
    """

    class Exploding:
        snapshot = _store().snapshot

        def apply(self, observation):
            raise RuntimeError("magasin mort")

    sink = Sink()
    service = PresentationAttentionService(store=Exploding(), diagnostics=sink,
                                           clock=lambda: NOW)
    decisions = service.raise_from_assessments([_assessment()], job_id="j1",
                                               session_id=SESSION, may_verify=True)
    assert decisions[0].alerted, "la porte accepte ; c'est le rangement qui casse"
    assert service.counters.store_failed == 1
    assert service.counters.raised == 0
    # Rien n'a été signalé : pas de ligne, donc pas de son pour un point perdu.
    assert ATTENTION_RAISED_KIND not in sink.kinds()
    assert "presentation.attention.store_failed" in sink.kinds()


def test_le_service_ne_leve_pas_quand_l_horloge_casse():
    """`_now()` était hors garde, et une horloge injectée est du code d'appelant."""

    def broken():
        raise RuntimeError("horloge morte")

    service = PresentationAttentionService(store=_store(), diagnostics=Sink(), clock=broken)
    decisions = service.raise_from_assessments([_assessment()], job_id="j1",
                                               session_id=SESSION, may_verify=True)
    # `NOT_CONSTRUCTIBLE` et non `INVALID` : ce n'est pas le verdict qui est
    # mauvais, c'est qu'il n'existe aucun instant auquel dater l'événement.
    assert decisions[0].refusal is AttentionRefusal.NOT_CONSTRUCTIBLE
    assert service.counters.raised == 0


# ==========================================================================
# 4. D11 : rien ici ne parle, et ça se lit
# ==========================================================================


def test_aucune_nature_de_parole_n_est_admise_pour_un_point_d_attention():
    """La preuve vivante de D11 : la matrice de la Slice 07, évaluée en entier.

    Pas une phrase du module, pas un commentaire : `may_speak` pour **toute**
    `SpeechKind`, plus l'absence de nature de sécurité, plus l'autorisation du
    signal non verbal — qui est la seule chose que D11 accorde.
    """

    policy = attention_output_policy()
    for kind in SpeechKind:
        assert may_speak(PresentationSituation.FACT_CHECK_ATTENTION, kind) is False, kind
    assert policy.voice_allowed is False
    assert policy.safety_speech_kinds == ()
    assert policy.requires_explicit_address is False
    assert policy.may_raise_attention_cue is True
    assert "D11" in policy.decisions


def test_un_point_d_attention_ne_peut_pas_se_declarer_autorise_ni_parlant():
    """`ClassVar`, donc `dataclasses.replace` ne peut pas les retourner.

    Même forme que `SpeculativeGrant` et `PresentationContextSnapshot`. Le test
    exerce le chemin de mutation réaliste, pas seulement la lecture.
    """

    raised = _decide(_assessment()).raised
    assert PresentationAttention.authorizes_actions is False
    assert PresentationAttention.requests_speech is False
    with pytest.raises(TypeError):
        replace(raised, requests_speech=True)
    with pytest.raises(TypeError):
        replace(raised, authorizes_actions=True)


def test_la_charge_utile_ne_porte_aucun_champ_de_parole():
    """Aucune clé ne peut transporter une demande de parole : il n'y en a pas.

    On énumère les clés effectivement émises plutôt que de lire la source, et
    on refuse tout ce qui ressemble à une sortie vocale.
    """

    payload = _decide(_assessment()).raised.to_trace_payload()
    forbidden = ("speech", "voice", "say", "tts", "spoken", "utterance", "disposition")
    assert not [key for key in payload if any(word in key for word in forbidden)], payload


# ==========================================================================
# 5. La parole ne descend pas dans la trace
# ==========================================================================


SECRET = "zorglub-quarante-deux"


def test_aucune_ligne_de_journal_ne_transporte_la_parole_de_la_salle():
    """La technique de la Slice 04 : planter une phrase et fouiller tout ce qui sort.

    `reason` est de la parole reformulée ; il vit dans l'ensemble de travail, en
    mémoire, pour le tour adressé de la Slice 10. `trace.jsonl` est un fichier
    durable partagé par trois processus, et il n'en reçoit rien.
    """

    store, sink = _store(claim_statement=f"la marge {SECRET} est de 12 %"), Sink()
    service = PresentationAttentionService(store=store, diagnostics=sink, clock=lambda: NOW)
    service.raise_from_assessments([_assessment(reason=f"la source dit {SECRET}")],
                                   job_id="j1", session_id=SESSION, may_verify=True)
    assert service.counters.raised == 1
    printed = json.dumps([list(line[:3]) + [line[3]] for line in sink.lines], default=str)
    assert SECRET not in printed, printed

    # Et il est bien resté là où il sert : sans cette moitié, le test passerait
    # pour un service qui aurait simplement tout perdu.
    kept = store.snapshot.working_set.attention[0]
    assert SECRET in kept.reason


def test_la_raison_est_absente_de_la_charge_utile_mais_presente_dans_l_enregistrement():
    raised = _decide(_assessment(reason=SECRET)).raised
    assert SECRET not in json.dumps(raised.to_trace_payload())
    assert raised.to_item().reason == SECRET


# ==========================================================================
# 6. La couture avec le registre d'arrière-plan, traversée pour de vrai
# ==========================================================================


def test_une_ligne_ecrite_par_le_service_est_classee_attention_par_le_registre(tmp_path):
    """Les deux moitiés de la couture, par le fichier qui les relie vraiment.

    Core écrit dans `trace.jsonl` ; le Control Center le suit. Ce test fait
    exactement cela — un vrai fichier, un vrai `TraceFollower` — plutôt que de
    comparer deux littéraux qui pourraient diverger en silence.
    """

    trace = tmp_path / "trace.jsonl"

    class FileSink:
        def emit(self, kind, message, *, level="info", data=None):
            with trace.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"ts": NOW.isoformat(), "kind": kind, "level": level,
                                         "message": message, "data": data or {}},
                                        ensure_ascii=False) + "\n")

    follower = TraceFollower(trace)
    follower.poll()  # se positionne à la fin, comme au démarrage de la page
    ledger = BackgroundEventLedger()

    service = PresentationAttentionService(store=_store(), diagnostics=FileSink(),
                                           clock=lambda: NOW)
    service.raise_from_assessments([_assessment()], job_id="j1", session_id=SESSION,
                                   may_verify=True)

    follow(ledger, follower)
    kept = [e for e in ledger.entries if e.kind == ATTENTION_RAISED_KIND]
    assert len(kept) == 1, ledger.entries
    entry = kept[0]
    assert entry.category == ATTENTION
    assert entry.attention is not None
    assert entry.attention["attention_id"] == "att-j1-0"
    assert entry.attention["category"] == "contradiction"
    assert entry.attention["band"] == "high"
    assert [p["locator"] for p in entry.attention["evidence"]] == ["https://exemple.test/1"]
    assert entry.detail == "1 source · confiance élevée"
    assert ledger.counts() == {"attention": 1}


def test_le_registre_survit_a_une_ligne_d_attention_malformee():
    """La trace est un fichier : rien de ce qui en sort n'est cru sur parole.

    Une ligne bancale doit donner un événement pauvre — toujours compté dans la
    pastille — et jamais une exception, qui viderait le badge de toute la
    séance.
    """

    ledger = BackgroundEventLedger()
    hostile = [
        {},
        {"attention_id": "a", "category": "contradiction", "evidence": "pas une liste"},
        {"attention_id": "a", "category": "contradiction", "evidence": [1, None, {"locator": 7}]},
        {"attention_id": "a", "category": "contradiction", "band": "<script>", "source_count": -3},
        {"attention_id": "a" * 500, "category": "c", "resource_ids": ["x"] * 99},
        # **Le cas qui atteint vraiment la borne des pieces.** La version
        # precedente de cette liste n'envoyait qu'une seule piece valide, donc
        # la borne n'etait jamais franchie et la supprimer ne cassait rien
        # (mutation M24, survivante). C'est le motif que ce handoff a
        # catalogue trois fois : un test qui execute le code d'une garde sans
        # jamais atteindre l'etat que la garde existe pour refuser.
        {"attention_id": "b", "category": "contradiction",
         "evidence": [{"source_id": "s%d" % i, "locator": "https://x.test/%d" % i,
                       "title": "t" * 900} for i in range(40)],
         "resource_ids": ["r%d" % i for i in range(40)]},
    ]
    for index, data in enumerate(hostile):
        entry = ledger.observe(ATTENTION_RAISED_KIND, "ligne", data=data, ts="")
        assert entry is not None, data
        assert entry.category == ATTENTION
    payloads = [e.attention for e in ledger.entries]
    assert payloads[0] is None  # sans identifiant ni catégorie : rien à montrer
    for payload in payloads[1:]:
        assert payload is not None
        assert len(payload["attention_id"]) <= 64
        assert payload["band"] in ("high", "moderate")
        assert payload["source_count"] >= 0
        assert len(payload["evidence"]) <= MAX_ATTENTION_EVIDENCE
        # Ni gravité ni références de ressources ne traversent plus : la
        # carte n'en dessinait rien (câblage mort, point 7 de la reprise).
        assert "resource_ids" not in payload and "severity" not in payload
        for piece in payload["evidence"]:
            assert len(piece["title"]) <= MAX_ATTENTION_FIELD
    # Et la derniere entree a bien FRANCHI la borne avant d'etre ramenee :
    # sans cette ligne, la boucle ci-dessus se contenterait de listes de un.
    assert len(payloads[-1]["evidence"]) == MAX_ATTENTION_EVIDENCE


def test_le_resume_de_statut_ne_rend_que_les_points_non_vus():
    """Ce que la page reçoit chaque seconde : les non-vus, du plus récent au plus vieux."""

    ledger = BackgroundEventLedger()
    for index in range(5):
        ledger.observe(ATTENTION_RAISED_KIND, "ligne",
                       data={"attention_id": f"att-{index}", "category": "contradiction",
                             "band": "moderate", "source_count": 1},
                       ts="")
    digest = ledger.attention_digest()
    assert [d["attention"]["attention_id"] for d in digest] == ["att-4", "att-3", "att-2"]

    ledger.acknowledge(category=ATTENTION)
    assert ledger.attention_digest() == []


def test_acquitter_ne_touche_ni_la_charge_utile_ni_l_ensemble_de_travail():
    """« Écarter un avertissement change l'état de l'interface, jamais les faits. »

    Deux moitiés, et les deux comptent : l'acquittement ne réécrit pas ce que
    l'événement disait, et il n'a aucun chemin vers le magasin — ce qui se
    constate en comparant l'instantané avant et après, identité comprise.
    """

    store = _store()
    sink = Sink()
    service = PresentationAttentionService(store=store, diagnostics=sink, clock=lambda: NOW)
    service.raise_from_assessments([_assessment()], job_id="j1", session_id=SESSION,
                                   may_verify=True)
    ledger = BackgroundEventLedger()
    raised = sink.of(ATTENTION_RAISED_KIND)[0]
    entry = ledger.observe(ATTENTION_RAISED_KIND, "ligne", data=raised, ts="")
    before_payload = json.dumps(entry.to_payload(), sort_keys=True, default=str)
    before_snapshot = store.snapshot
    before_state = json.dumps(before_snapshot.to_payload(), sort_keys=True, default=str)

    ledger.acknowledge(category=ATTENTION)
    ledger.acknowledge()

    assert json.dumps(entry.to_payload(), sort_keys=True, default=str) == before_payload
    assert store.snapshot is before_snapshot
    assert json.dumps(store.snapshot.to_payload(), sort_keys=True, default=str) == before_state
    assert len(store.snapshot.working_set.attention) == 1


def test_un_evenement_ordinaire_ne_porte_pas_de_charge_utile_d_attention():
    """L'ajout est strictement additif : rien d'autre ne gagne une clé."""

    ledger = BackgroundEventLedger()
    entry = ledger.observe("voice.speech.abandoned", "réponse retirée", data={}, ts="")
    assert entry.category == ATTENTION
    assert entry.attention is None
    assert "attention" not in entry.to_payload()
    assert BackgroundEvent(1, "", ATTENTION, "k", "l", "d").attention is None


def test_le_statut_ne_porte_le_bloc_d_attention_que_s_il_y_a_quelque_chose_a_montrer():
    """Absent quand il n'y a rien, et pas présent et vide.

    Ce bloc part **chaque seconde**, et la seconde ordinaire n'a aucun point
    d'attention. Le résumé reste donc identique à l'octet près pour tout
    consommateur existant — ce que `test_brain_delegation.py` vérifiait déjà par
    égalité stricte, et qu'une clé toujours présente cassait. Un serveur plus
    ancien se lit alors exactement comme un serveur qui n'a rien à signaler, ce
    que la page traite de la même façon.
    """

    from jarvis.runtime.control_center import ControlCenter

    import tempfile
    with tempfile.TemporaryDirectory() as root:
        control = ControlCenter(runtime_root=Path(root), project_root=Path(root))

        empty = control._background_summary()
        assert set(empty) == {"seq", "unread", "counts"}, empty
        assert "attention" not in empty

        control.background.observe(
            ATTENTION_RAISED_KIND, "Une affirmation est contredite",
            data={"attention_id": "att-1", "category": "contradiction", "band": "high",
                  "source_count": 2,
                  "evidence": [{"source_id": "src-1", "locator": "https://exemple.test/1",
                                "title": "Source 1", "resource_id": ""}]},
            ts="2026-09-24T10:00:00+00:00")

        loaded = control._background_summary()
        assert loaded["counts"] == {"attention": 1}
        assert [item["attention"]["attention_id"] for item in loaded["attention"]] == ["att-1"]
        assert loaded["attention"][0]["detail"] == "2 sources · confiance élevée"

        # Acquitté : le bloc disparaît de nouveau, sans que rien d'autre bouge.
        control.background.acknowledge(category=ATTENTION)
        seen = control._background_summary()
        assert "attention" not in seen, seen
        assert seen["seq"] == loaded["seq"]


# ==========================================================================
# 7. Le magasin refuse : alors rien n'est signalé
# ==========================================================================


def test_un_point_refuse_par_le_magasin_ne_pose_aucune_ligne():
    """« Rien n'est signalé qui ne soit rangé. »

    Un son pour un point que l'ensemble de travail n'a pas gardé donnerait un
    avertissement que la Slice 10 ne saurait pas expliquer si on le lui
    demandait — et c'est exactement ce que `HV-PRES-ALERT-01` fait faire.

    La séance passée est fausse : le magasin refuse en `STALE_SESSION`.
    """

    store, sink = _store(), Sink()
    service = PresentationAttentionService(store=store, diagnostics=sink, clock=lambda: NOW)
    decisions = service.raise_from_assessments([_assessment()], job_id="j1",
                                              session_id="autre-seance", may_verify=True)
    assert decisions[0].alerted, "la porte accepte : c'est le magasin qui refuse ensuite"
    assert ATTENTION_RAISED_KIND not in sink.kinds()
    assert service.counters.raised == 0
    assert service.counters.dropped_by_store == 1
    assert service.raised_ids == ()
    assert store.snapshot.working_set.attention == ()


def test_un_journal_en_panne_ne_ferme_pas_la_voie_mais_se_compte():
    class Broken:
        def emit(self, *args, **kwargs):
            raise RuntimeError("puits mort")

    store = _store()
    service = PresentationAttentionService(store=store, diagnostics=Broken(), clock=lambda: NOW)
    service.raise_from_assessments([_assessment()], job_id="j1", session_id=SESSION,
                                   may_verify=True)
    assert service.counters.raised == 1
    assert service.counters.diagnostic_failures >= 1
    assert len(store.snapshot.working_set.attention) == 1


# ==========================================================================
# 8. La voie spéculative : la capacité garde l'alerte comme elle garde le reste
# ==========================================================================


class Runner:
    """Un exécutant qui rend toujours le même résultat, sans rien faire d'autre."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.seen = []

    async def prepare(self, request):
        self.seen.append(request)
        return self.outcome


class RecordingRaiser:
    def __init__(self):
        self.calls = []

    def raise_from_assessments(self, assessments, *, job_id, session_id, may_verify):
        self.calls.append((tuple(assessments), job_id, session_id, may_verify))
        return ()


async def _run_lane(kind, outcome, raiser, *, store=None, diagnostics=None):
    """Faire tourner la voie de la Slice 08 **par sa vraie porte**.

    Rien n'est amorcé à la main : un déclencheur ambiant entre par
    `submit_trigger`, la voie construit elle-même le jeton depuis
    `TRIGGER_PREPARATION`, exécute, normalise, et c'est `_normalise` qui
    remet les verdicts. C'est la correction du motif que ce handoff a
    catalogué trois fois — *un test qui amorce une garde avec un état que la
    production ne peut pas atteindre*.
    """

    store = store or _store()
    service = PresentationSpeculativeService(
        store=store, runner=Runner(outcome), attention=raiser, clock=lambda: NOW,
        diagnostics=diagnostics,
    )
    assert service.bind_session(SESSION) is SpeculativeAdmission.ACCEPTED
    assert store.observe(SESSION, "utt-1", "la marge est de 12 %", spoken_at=NOW).applied
    admission = service.submit_trigger(
        AmbientTrigger(kind=kind, utterance_id="utt-1", text="la marge est de 12 %",
                       confidence=0.5))
    assert admission is SpeculativeAdmission.ACCEPTED, admission
    await service.drain()
    return service


@pytest.mark.parametrize("kind,granted", [
    (AmbientTriggerKind.CHECKABLE_CLAIM, True),
    (AmbientTriggerKind.NEW_TOPIC, False),
])
async def test_seul_un_travail_qui_pouvait_verifier_peut_alerter(kind, granted):
    """La leçon la plus chère de la Slice 08, appliquée d'avance.

    Là-bas, *le seul effet durable de la voie était le seul que la table de
    capacités ne gardait pas*. Ici l'effet est un enregistrement rangé et un
    son : il passe donc par la même table. Un déclencheur `new_topic` n'obtient
    que `RESEARCH_SEARCH` — c'est la table `TRIGGER_PREPARATION` qui le décide,
    pas ce test — et il ne peut donc pas alerter, quoi que son exécutant rende.

    Les deux moitiés sont exercées par la même fonction, de sorte qu'aucune ne
    peut passer pour la bonne raison pendant que l'autre dort.
    """

    store = _store()
    raiser = PresentationAttentionService(store=store, diagnostics=Sink(), clock=lambda: NOW)
    outcome = SpeculativeOutcome(findings=(), assessments=(_assessment(),))
    service = await _run_lane(kind, outcome, raiser, store=store)

    assert service.counters.assessments_received == 1
    # **Un seul décideur.** La voie lit le jeton et le transmet ; c'est la
    # porte du domaine qui refuse. Une version précédente décidait des deux
    # côtés et passait ensuite `True` en dur, ce qui rendait le contrôle du
    # juge et `attention_capability_missing` injoignables en production.
    if granted:
        assert raiser.counters.raised == 1
        assert raiser.counters.refusals == {}
        assert service.counters.assessments_refused_capability == 0
        assert len(store.snapshot.working_set.attention) == 1
    else:
        assert raiser.counters.raised == 0
        assert raiser.counters.refusals == {
            AttentionRefusal.CAPABILITY_MISSING.value: 1}
        assert service.counters.assessments_refused_capability == 1
        assert store.snapshot.working_set.attention == ()


async def test_un_verdict_sans_juge_branche_est_compte_et_non_perdu():
    """Aujourd'hui aucun composition root ne branche le juge : ce n'est pas rien.

    Un silence et un refus doivent se distinguer, sinon « il ne se passe rien »
    et « la voie est morte » se lisent pareil — l'ambiguïté que ce handoff
    combat depuis la Slice 05.
    """

    service = await _run_lane(AmbientTriggerKind.CHECKABLE_CLAIM,
                              SpeculativeOutcome(assessments=(_assessment(),)), None)
    assert service.counters.assessments_unjudged == 1
    assert service.counters.assessments_received == 1


async def test_un_juge_en_panne_est_rattrape_par_sa_propre_garde():
    """Et par **la sienne**, pas par celle de la normalisation au-dessus.

    Survivant de mutation M31 : retrecir `except Exception` a
    `except ZeroDivisionError` ne cassait rien, parce que `_run` rattrape tout
    de toute facon et compte le meme `failed`. Le test etait vrai sur le
    systeme et faux sur lui-meme — ce que QA avait deja trouve en Slice 06. La
    ligne de journal dit laquelle des deux gardes a servi, et c'est du
    comportement observable, pas du texte de source.
    """

    class Broken:
        def raise_from_assessments(self, *args, **kwargs):
            raise RuntimeError("juge mort")

    sink = Sink()
    service = await _run_lane(AmbientTriggerKind.CHECKABLE_CLAIM,
                              SpeculativeOutcome(assessments=(_assessment(),)), Broken(),
                              diagnostics=sink)
    # Compté sous SON nom : `failed` dit « une préparation a échoué », et
    # confondre les deux rendait invisible lequel des deux étages est en panne.
    assert service.counters.attention_failures == 1
    assert service.counters.failed == 0
    assert service.active is True
    assert "presentation.speculative.attention_failed" in sink.kinds(), sink.kinds()
    assert "presentation.speculative.normalise_failed" not in sink.kinds(), sink.kinds()


async def test_un_resultat_sans_verdict_ne_change_rien_a_la_voie_existante():
    """La compatibilité de la Slice 08 : un exécutant qui ne rend que des pistes.

    Le verdict est un ajout, pas un passage obligé. Une préparation ordinaire
    range toujours sa ressource et n'appelle jamais le juge.
    """

    store = _store()
    raiser = RecordingRaiser()
    outcome = SpeculativeOutcome(findings=(PreparedFinding(
        kind=ResourceKind.WEB_PAGE, locator="https://exemple.test/9", title="Piste"),))
    service = await _run_lane(AmbientTriggerKind.CHECKABLE_CLAIM, outcome, raiser, store=store)
    assert raiser.calls == []
    assert service.counters.assessments_received == 0
    assert service.counters.resources_staged == 1
    assert len(store.snapshot.working_set.resources) == 1


async def test_la_chaine_complete_va_du_declencheur_ambiant_au_signal():
    """De bout en bout, avec les vraies classes : déclencheur → verdict → ligne.

    C'est le seul test qui fait tourner ensemble la voie de la Slice 08, la
    porte de la Slice 09, le magasin de la Slice 04 et le registre
    d'arrière-plan. Il existe parce que chaque moitié peut être juste et la
    couture fausse — la Slice 06 l'a payé.
    """

    store, sink = _store(), Sink()
    raiser = PresentationAttentionService(store=store, diagnostics=sink, clock=lambda: NOW)
    service = await _run_lane(AmbientTriggerKind.CHECKABLE_CLAIM,
                              SpeculativeOutcome(assessments=(_assessment(),)), raiser,
                              store=store)
    assert service.counters.assessments_received == 1
    assert raiser.counters.raised == 1
    raised = sink.of(ATTENTION_RAISED_KIND)
    assert len(raised) == 1, sink.kinds()

    ledger = BackgroundEventLedger()
    entry = ledger.observe(ATTENTION_RAISED_KIND, "ligne", data=raised[0], ts="")
    assert entry.category == ATTENTION
    assert ledger.attention_digest()[0]["attention"]["category"] == "contradiction"
    assert len(store.snapshot.working_set.attention) == 1


# ==========================================================================
# 9. Fermeture d'import — la garde est une liste blanche
# ==========================================================================


def _closure(module: str) -> set[str]:
    """Modules `jarvis` chargés par l'import de `module`, dans un interpréteur neuf.

    Même technique que les Slices 06 et 08 : l'ensemble exact plutôt qu'une
    liste d'interdiction. Une liste d'interdiction ne voit que ce à quoi on a
    pensé ; QA est passée à travers les deux de la Slice 06.
    """

    code = (
        "import sys, json; before=set(sys.modules); "
        f"import {module}; "
        "print(json.dumps(sorted(m for m in set(sys.modules)-before "
        "if m.split('.')[0]=='jarvis')))"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT),
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    return set(json.loads(out.stdout))


def test_le_juge_d_attention_ne_charge_que_des_modules_declares():
    """Égalité, pas inclusion. Un import ajouté se voit, et le message dit lequel.

    Ce qui compte n'est pas « aucune arête vers la parole » — le **vocabulaire**
    de parole est là, par la matrice de la Slice 07, et c'est voulu : c'est lui
    qui rend D11 lisible d'ici. Ce que la garde tient est qu'aucun
    **producteur** de parole n'entre, et qu'aucun `jarvis.core.*` autre que ce
    module n'entre non plus.

    **Sondé de bout en bout, et le sondage vaut plus que cette assertion.**
    Un `from jarvis.runtime.speech_scheduler import SpeechScheduler` planté dans
    le module fait échouer ce test **par son nom**, en énumérant les intrus. La
    première tentative de sondage avait échoué pour la mauvaise raison — un
    chemin de module inexistant, donc un `ModuleNotFoundError` à la collecte et
    non la garde qui parle : le résultat d'un sondage se vérifie, pas seulement
    son signe. Sonde retirée, arbre vérifié.

    Cette garde n'est affirmée que dans son état sain, faute de pouvoir
    empoisonner un import sans toucher au produit ; c'est l'**égalité** qui la
    sauve — une liste d'interdiction ne voit que ce à quoi on a pensé, et QA
    était passée à travers les deux de la Slice 06.
    """

    loaded = _closure("jarvis.core.presentation_attention")
    assert loaded == set(ALLOWED_IMPORT_CLOSURE), {
        "unexpected": sorted(loaded - set(ALLOWED_IMPORT_CLOSURE)),
        "declared_but_absent": sorted(set(ALLOWED_IMPORT_CLOSURE) - loaded),
    }
    assert {m for m in loaded if m.startswith("jarvis.core.")} == {
        "jarvis.core.presentation_attention"}
    for producer in ("jarvis.core.speech_scheduler", "jarvis.core.brain_service",
                     "jarvis.core.tools", "jarvis.runtime.realtime_audio",
                     "jarvis.core.back_brain"):
        assert producer not in loaded, producer


# ==========================================================================
# 10. Les bornes que rien n'atteignait
# ==========================================================================


def test_un_identifiant_de_travail_tres_long_est_ramene_sous_la_borne():
    """Le `[:64]` n'était franchi par aucun test : tous les `job_id` font deux lettres.

    Un identifiant de travail vient de la voie spéculative, qui le construit à
    partir d'une clé dérivée de ce qui a été dit dans la salle. Le laisser
    grandir mettrait un identifiant sans borne dans la trace **et** casserait
    `presentation_id`, qui refuse au-delà de 64 — donc l'événement entier.
    """

    store, sink = _store(), Sink()
    service = PresentationAttentionService(store=store, diagnostics=sink, clock=lambda: NOW)
    decisions = service.raise_from_assessments([_assessment()], job_id="j" * 200,
                                               session_id=SESSION, may_verify=True)
    assert decisions[0].alerted, decisions[0].code
    raised = decisions[0].raised
    assert len(raised.attention_id) == 64
    assert service.counters.raised == 1
    # Et il a vraiment traversé : la ligne porte le même identifiant tronqué.
    assert sink.of(ATTENTION_RAISED_KIND)[0]["attention_id"] == raised.attention_id


def test_la_memoire_des_points_leves_est_bornee():
    """`_raised_ids` garde les seize derniers ; aucun test n'en levait plus d'un.

    C'est la mémoire que `stats()` publie, donc la seule façon de distinguer
    « rien n'a été signalé » de « l'instantané n'a pas bougé ». Sans borne, elle
    grandirait pour toute la séance.
    """

    # **Vingt affirmations distinctes.** Une première version en réutilisait
    # trois : le magasin les coalesçait sur `(catégorie, affirmation, sujet)`,
    # donc trois identifiants entraient en tout et la borne n'était jamais
    # atteinte — la mutation qui la supprimait survivait. Encore un test qui
    # exécute le code d'une garde sans jamais atteindre l'état qu'elle garde.
    store = PresentationWorkingSetStore()
    assert store.bind_session(SESSION).applied
    for index in range(20):
        assert store.apply(PresentationObservation(
            f"claim-{index}", SESSION,
            PresentationClaim(claim_id=f"claim-{index}", statement=f"affirmation {index}",
                              provenance=_provenance(), first_seen_at=NOW, last_seen_at=NOW,
                              status=ClaimStatus.ASSERTED, confidence=0.5),
        )).applied
    assert store.apply(PresentationObservation("src-1", SESSION, PresentationSource(
        source_id="src-1", kind=ResourceKind.WEB_PAGE, reference="https://exemple.test/1",
        title="Source 1", retrieved_at=NOW))).applied

    # L'horloge avance : sans cela le magasin, borne a huit points, REFUSE les
    # suivants au lieu d'evincer le plus ancien, et seuls dix arrivent — la
    # borne du service reste alors hors d'atteinte pour une seconde raison,
    # empilee sur la premiere.
    ticks = iter(NOW + timedelta(seconds=i) for i in range(100))
    service = PresentationAttentionService(store=store, diagnostics=Sink(),
                                           clock=lambda: next(ticks), max_per_batch=1)
    for index in range(20):
        service.raise_from_assessments([_assessment(claim_id=f"claim-{index}")],
                                       job_id=f"job{index}", session_id=SESSION,
                                       may_verify=True)
    # Vingt points levés, seize retenus : la borne est franchie, pas frôlée.
    assert service.counters.raised == 20
    assert len(service.raised_ids) == 16
    assert service.raised_ids[-1].startswith("att-job19")
    assert service.stats()["raised_ids"] == list(service.raised_ids)

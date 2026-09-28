"""Slice 07 : le silence est une issue normale, et il se constate.

Ce fichier couvre les trois couches du contrat de manifestation du mode
présentation, chacune à son niveau :

- le **jugement** (`jarvis/domain/presentation_response.py`) : quelle situation
  une phrase constitue, et ce que cette situation autorise à dire ;
- la **porte** (`jarvis/runtime/presentation_speech_gate.py`) : la mémoire de
  tour, le refus, et la ligne qui rend le silence lisible ;
- l'**ordonnanceur** (`jarvis/runtime/speech_scheduler.py`) : qu'une commande
  visuelle se termine réellement avec zéro parole, dans les trois architectures
  vocales, et que le mode assistant n'ait rien changé.

Aucun test ici n'affirme sur du texte source. La seule chose approchante est
`test_le_mode_assistant_ne_laisse_aucune_trace_de_presentation`, qui prouve une
**absence** de ligne de journal — une absence observable, pas une lecture de
code.
"""
from __future__ import annotations

import asyncio
import pathlib

import pytest

from jarvis.domain.interaction_mode import InteractionMode
from jarvis.domain.output_disposition import OutputDisposition
from jarvis.domain.presentation_policy import (
    PRESENTATION_POLICY,
    UNADDRESSED_SAFETY_KINDS,
    PresentationOutputPolicy,
    PresentationPolicyError,
    PresentationSituation,
    may_speak,
    policy_for,
)
from jarvis.domain.presentation_response import (
    MAX_CLASSIFIED_TEXT,
    admit_presentation_speech,
    classify_addressed_situation,
)
from jarvis.domain.reflex_policy import ReflexAction, conversational_wait_reason
from jarvis.domain.v2 import (
    AddressingDecision,
    BrainTurnInput,
    ProtocolEnvelope,
    SpeechKind,
    SpeechRequest,
)
from jarvis.runtime.presentation_speech_gate import (
    CLASSIFICATION_FAILED,
    MAX_WITHHELD_MEMORY,
    NO_FILLER_REASON,
    SPEECH_WITHHELD,
    TURN_CLASSIFIED,
    TURN_SILENT,
    PresentationSpeechGate,
)
from types import SimpleNamespace

from jarvis.domain.voice_architecture import (
    DuplexVoiceConfig,
    FrontBrainVoiceConfig,
    SimpleVoiceConfig,
    VoiceModelRef,
)
from jarvis.runtime.interaction_mode_observer import InteractionModeObserver
from jarvis.runtime.realtime_audio import RealtimeConversationBridge
from jarvis.runtime.voice_architecture_config import VoiceArchitectureSettings
from jarvis.runtime.voice_composition import resolve_voice_composition
from jarvis.runtime.speech_scheduler import REFLEX_DECIDED, SpeechScheduler
from tests.fakes.speech_context import context, source
from tests.unit.test_v2_speech_scheduler import (
    CONVERSATION, FakeCore, RecordingJournal, build_scheduler, wait_for,
)
from tests.unit.test_voice_duplex import ControllableSession, GuardedAudio, build_bridge, event, feed
from jarvis.adapters.control_center_brain import (
    ControlCenterBrainBackend,
    _turn_context,
    public_answer_kind,
)
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.runtime.control_center import BRIEF_PRESENTATION_MODE, build_agent_brief

ADDRESSED_SITUATIONS = tuple(
    situation for situation, policy in PRESENTATION_POLICY.items() if policy.requires_explicit_address
)
UNADDRESSED_SITUATIONS = tuple(
    situation for situation, policy in PRESENTATION_POLICY.items() if not policy.requires_explicit_address
)


# ---------------------------------------------------------------------------
# Le jugement : quelle situation une phrase constitue
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text, expected, evidence", [
    ("Jarvis, montre-moi le bilan", PresentationSituation.VISUAL_COMMAND, "visual_verb:montre"),
    ("ouvre le document de septembre", PresentationSituation.VISUAL_COMMAND, "visual_verb:ouvre"),
    ("masque ce qui est à droite", PresentationSituation.VISUAL_COMMAND, "visual_verb:masque"),
    ("archive les tâches terminées", PresentationSituation.VISUAL_COMMAND, "visual_verb:archive"),
    ("quel est le total ?", PresentationSituation.KNOWLEDGE_QUESTION, "question_opener:quel"),
    ("c'est bien ça ?", PresentationSituation.KNOWLEDGE_QUESTION, "question_mark"),
    ("pourquoi la marge baisse", PresentationSituation.KNOWLEDGE_QUESTION, "question_opener:pourquoi"),
    ("combien de clients en juin", PresentationSituation.KNOWLEDGE_QUESTION, "question_opener:combien"),
    ("raconte ce que fait cette équipe", PresentationSituation.EXPLICIT_SPEAK_REQUEST, "speak_request:raconte"),
    ("lis-moi les trois premiers points", PresentationSituation.EXPLICIT_SPEAK_REQUEST, "speak_request:lis_moi"),
])
def test_une_phrase_adressee_porte_sa_situation(text, expected, evidence):
    assert classify_addressed_situation(text) == (expected, evidence)


def test_montre_moi_X_et_dis_moi_Y_ne_peut_pas_etre_une_commande_visuelle():
    """Le cas nommé par la Slice 01, et la raison d'être de l'ordre de lecture.

    `VISUAL_COMMAND.voice_allowed` est **faux comme plafond** : sous cette
    situation, aucune demande ne débloque la parole. Une phrase qui demande à
    la fois l'écran et la voix doit donc être classée du côté où la voix existe,
    sinon la moitié parlée serait perdue sans recours et sans trace.
    """

    situation, evidence = classify_addressed_situation("montre-moi le bilan et dis-moi le total")

    assert situation is PresentationSituation.EXPLICIT_SPEAK_REQUEST
    assert evidence == "speak_request:dis_moi"
    assert policy_for(situation).voice_allowed
    # Et la preuve que le plafond est bien un plafond : la même phrase sans la
    # demande de parole ne peut rien dire, quelle que soit la nature demandée.
    visual, _ = classify_addressed_situation("montre-moi le bilan")
    assert not any(admit_presentation_speech(situation=visual, kind=kind).admitted
                   for kind in (SpeechKind.ACK, SpeechKind.PROGRESS, SpeechKind.RESULT))


@pytest.mark.parametrize("text", [
    "Tu peux montrer le bilan ?",
    "Montre-moi le bilan ?",
    "Jarvis, tu peux afficher le graphique ?",
    "Affiche le bilan, d'accord ?",
])
def test_une_commande_d_affichage_poliment_posee_reste_une_commande(text):
    """Le point d'interrogation ne gagne plus contre un verbe d'affichage.

    La transcription temps réel ponctue l'intonation interrogative, et « tu
    peux afficher X ? » est du français ordinaire pour un ordre d'affichage.
    Tant que le `?` passait avant le verbe, la façon la plus naturelle de
    demander un affichage rendait JARVIS bavard — c'est-à-dire recréait le
    remplissage que la Décision 09 retire, sur le cas le plus fréquent.
    """

    situation, evidence = classify_addressed_situation(text)

    assert situation is PresentationSituation.VISUAL_COMMAND and evidence.startswith("visual_verb:")
    assert not admit_presentation_speech(situation=situation, kind=SpeechKind.RESULT).admitted


@pytest.mark.parametrize("text", [
    "pourquoi tu as affiché le Q3 ?",
    "quel graphique est affiché",
])
def test_un_mot_interrogatif_en_tete_garde_la_main_sur_le_verbe_d_affichage(text):
    """Une vraie question *à propos* d'un affichage n'est pas une commande.

    C'est l'autre moitié de la règle : déplacer le `?` après le verbe sans
    garder le mot interrogatif en tête aurait mis au silence des questions
    ordinaires, c'est-à-dire échangé un défaut de bavardage contre un défaut
    de panne muette.
    """

    situation, evidence = classify_addressed_situation(text)

    assert situation is PresentationSituation.KNOWLEDGE_QUESTION
    assert evidence.startswith("question_opener:")


@pytest.mark.parametrize("text, expected", [
    ("montre le bilan, ne commente pas", PresentationSituation.VISUAL_COMMAND),
    ("affiche le graphique sans commenter", PresentationSituation.VISUAL_COMMAND),
    ("dis-moi le total", PresentationSituation.EXPLICIT_SPEAK_REQUEST),
])
def test_une_marque_de_parole_niee_ne_fait_pas_parler(text, expected):
    """Le seul cas où la cécité à la négation **inversait** l'intention.

    « montre le bilan, ne commente pas » demandait la parole *parce que*
    l'utilisateur la refusait : le marqueur `commente` était lu sans son
    « ne ». Une marque manquée fait parler par défaut, ce qui est le côté sûr ;
    une marque lue à l'envers fait exactement ce qu'on a demandé d'éviter.
    """

    assert classify_addressed_situation(text)[0] is expected


def test_le_silence_exige_une_preuve_positive():
    """Un tour adressé illisible n'est jamais mis au silence.

    Le biais est explicite : mettre au silence ce qu'on n'a pas su lire
    produirait une panne muette — exactement ce que cette Slice existe pour
    interdire. `ou` conjonction n'ouvre donc pas une question, mais l'absence
    de verbe d'affichage n'installe pas non plus le silence.
    """

    assert classify_addressed_situation("il faudrait revoir ça ensemble") == (
        PresentationSituation.KNOWLEDGE_QUESTION, "no_visual_command_evidence")
    # « ou » est une conjonction ordinaire : elle ne doit pas voler la phrase à
    # la commande d'affichage qui la porte.
    assert classify_addressed_situation("affiche le graphique ou le tableau")[0] is PresentationSituation.VISUAL_COMMAND


@pytest.mark.parametrize("value", [None, 42, b"montre", object()])
def test_un_texte_qui_n_en_est_pas_un_ne_leve_jamais(value):
    assert classify_addressed_situation(value) == (
        PresentationSituation.KNOWLEDGE_QUESTION, "no_visual_command_evidence")


def test_un_texte_demesure_est_borne_avant_lecture():
    situation, _ = classify_addressed_situation("a " * MAX_CLASSIFIED_TEXT + "montre-moi le bilan")
    # Le verbe est au-delà de la borne : il n'est pas lu, et le défaut reste la parole.
    assert situation is PresentationSituation.KNOWLEDGE_QUESTION


# ---------------------------------------------------------------------------
# Les phrases « X ne peut jamais arriver », prises comme cas de test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("situation", UNADDRESSED_SITUATIONS)
@pytest.mark.parametrize("kind", tuple(SpeechKind))
def test_une_situation_sans_adressage_explicite_ne_peut_jamais_obtenir_la_parole(situation, kind):
    """Décisions 03 et 11, vérifiées sur l'état que la garde existe pour couvrir.

    `AMBIENT_OBSERVATION` et `FACT_CHECK_ATTENTION` sont les deux lignes de la
    matrice qui ne naissent pas d'un adressage explicite. Exercer la garde sur
    une ligne adressée ne prouverait rien : c'est ici, sur ces deux lignes
    précisément, et pour **les cinq** natures — y compris les deux natures de
    sûreté que toutes les lignes adressées admettent.
    """

    verdict = admit_presentation_speech(situation=situation, kind=kind)

    assert not verdict.admitted and verdict.reason == "policy_forbids"
    assert not policy_for(situation).safety_speech_kinds


def test_une_exception_de_surete_ne_peut_pas_exister_sans_adressage_explicite():
    """L'invariante est portée par la donnée, pas par la discipline des lignes.

    Une ligne future qui accorderait une nature de sûreté sans exiger
    l'adressage explicite ne peut pas être construite : `__post_init__` la
    refuse, comme il refuse déjà `voice_allowed` sans adressage.
    """

    for situation, policy in PRESENTATION_POLICY.items():
        if policy.safety_speech_kinds:
            assert policy.requires_explicit_address, situation
    with pytest.raises(PresentationPolicyError) as raised:
        PresentationOutputPolicy(
            situation=PresentationSituation.AMBIENT_OBSERVATION,
            disposition=OutputDisposition.SILENT, voice_allowed=False,
            requires_explicit_address=False, authorizes_action=False,
            speech_kinds=(), safety_speech_kinds=(SpeechKind.ERROR,),
            may_raise_attention_cue=False, decisions=("D11",))
    assert raised.value.code == "presentation_policy_spontaneous_speech"


def test_une_nature_ne_peut_pas_etre_a_la_fois_permise_et_exceptionnelle():
    with pytest.raises(PresentationPolicyError) as raised:
        PresentationOutputPolicy(
            situation=PresentationSituation.KNOWLEDGE_QUESTION,
            disposition=OutputDisposition.VISUAL_AND_VOICE, voice_allowed=True,
            requires_explicit_address=True, authorizes_action=True,
            speech_kinds=(SpeechKind.RESULT,), safety_speech_kinds=(SpeechKind.RESULT,),
            may_raise_attention_cue=False, decisions=("D10",))
    assert raised.value.code == "presentation_policy_invalid"


@pytest.mark.parametrize("situation", ADDRESSED_SITUATIONS)
def test_une_panne_n_est_jamais_tue_sur_un_tour_adresse(situation):
    """Un échec silencieux est un défaut, pas de la discrétion."""

    assert admit_presentation_speech(situation=situation, kind=SpeechKind.ERROR).admitted
    assert may_speak(situation, SpeechKind.ERROR)


@pytest.mark.parametrize("situation", ADDRESSED_SITUATIONS)
def test_une_clarification_n_est_jamais_tue_sur_un_tour_adresse(situation):
    """La clarification requise survit à la suppression du remplissage.

    Sans elle, « montre-moi le bilan » que JARVIS n'a pas su résoudre se
    terminerait sans écran **et** sans question : l'utilisateur ne saurait même
    pas qu'il doit redemander. La nature a maintenant un producteur réel
    (`public_answer_kind`), vérifié plus bas.
    """

    assert admit_presentation_speech(situation=situation, kind=SpeechKind.QUESTION).admitted


def test_le_plafond_reste_absolu_pour_tout_le_reste():
    """Les deux natures de sûreté sont nommées ; aucune autre ne passe."""

    for situation in ADDRESSED_SITUATIONS:
        policy = policy_for(situation)
        for kind in (SpeechKind.ACK, SpeechKind.PROGRESS, SpeechKind.RESULT):
            assert may_speak(situation, kind) is (policy.voice_allowed and kind in policy.speech_kinds)
        assert set(policy.safety_speech_kinds) <= {SpeechKind.ERROR, SpeechKind.QUESTION}


@pytest.mark.parametrize("kind", tuple(SpeechKind))
def test_une_parole_sans_tour_adresse_ne_dit_que_ce_qui_est_casse(kind):
    verdict = admit_presentation_speech(situation=None, kind=kind)

    assert verdict.admitted is (kind in UNADDRESSED_SAFETY_KINDS)
    assert verdict.reason == ("unaddressed_safety_kind" if verdict.admitted else "no_addressed_turn")
    # Sans tour adressé il n'y a rien à clarifier : seule la panne s'entend.
    assert UNADDRESSED_SAFETY_KINDS == (SpeechKind.ERROR,)


def test_une_nature_de_parole_non_typee_est_refusee_bruyamment():
    with pytest.raises(TypeError):
        admit_presentation_speech(situation=PresentationSituation.KNOWLEDGE_QUESTION, kind="error")


def test_une_parole_ambiante_ne_peut_pas_naitre_faute_de_tour():
    """Le second verrou, en amont de la matrice : un tour ambiant n'est jamais soumis.

    La porte refuse `AMBIENT_OBSERVATION` ; ce contrat-ci fait qu'elle n'a
    jamais à le faire en production, parce qu'aucun tour ambiant ne peut
    atteindre le cerveau, donc aucune demande de parole ne peut en naître.
    """

    with pytest.raises(ValueError):
        BrainTurnInput(conversation_id=CONVERSATION, text="il dit que la marge monte",
                       addressing=AddressingDecision.AMBIENT)


# ---------------------------------------------------------------------------
# La porte : mémoire de tour, refus, et silence constatable
# ---------------------------------------------------------------------------


def outcome_payload(scheduler, correlation_id):
    """Lecture d'observation du tour, telle qu'un consommateur la lirait."""

    outcome = scheduler.presentation.outcome(correlation_id)
    return None if outcome is None else outcome.to_payload()


def gate(mode=InteractionMode.PRESENTATION, journal=None):
    journal = journal if journal is not None else RecordingJournal()
    holder = {"mode": mode}
    door = PresentationSpeechGate(mode=lambda: holder["mode"],
                                  trace=lambda kind, message, *, level="info", data=None:
                                  journal.emit(kind, message, level=level, data=data))
    return door, journal, holder


def test_une_commande_visuelle_se_termine_sans_un_mot_et_cela_se_lit():
    door, journal, _ = gate()
    door.note_addressed_turn("montre-moi le bilan", correlation_id="c1")

    refused = door.admit(correlation_id="c1", kind=SpeechKind.RESULT)

    assert not refused.admitted
    outcome = door.outcome("c1")
    assert outcome.silent and outcome.admitted == 0 and outcome.withheld == (SpeechKind.RESULT,)
    assert outcome.silent_reason == "silent_by_policy"
    door.settle_all()
    [line] = journal.of(TURN_SILENT)
    assert line["level"] == "info" and line["data"]["silent_reason"] == "silent_by_policy"
    assert line["data"]["situation"] == PresentationSituation.VISUAL_COMMAND.value


def test_un_tour_sans_aucune_demande_de_parole_est_une_reussite_distincte():
    """« Rien à dire » et « on lui a coupé la parole » ne se confondent pas."""

    door, journal, _ = gate()
    door.note_addressed_turn("montre-moi le bilan", correlation_id="c1")
    door.settle_all()

    [line] = journal.of(TURN_SILENT)
    assert line["data"]["silent_reason"] == "silent_no_speech" and line["data"]["withheld_count"] == 0


def test_une_vraie_question_parle_et_le_tour_n_est_pas_muet():
    door, journal, _ = gate()
    door.note_addressed_turn("quel est le total du bilan ?", correlation_id="c1")

    assert door.admit(correlation_id="c1", kind=SpeechKind.RESULT).admitted
    outcome = door.outcome("c1")
    assert not outcome.silent and outcome.silent_reason is None
    door.settle_all()
    assert journal.of(TURN_SILENT) == []


def test_le_solde_d_un_tour_n_est_ecrit_qu_une_fois():
    door, journal, _ = gate()
    door.note_addressed_turn("montre-moi le bilan", correlation_id="c1")
    door.settle_all()
    door.settle_all()
    door.note_addressed_turn("et le reste ?", correlation_id="c2")

    assert len(journal.of(TURN_SILENT)) == 1


def test_l_arrivee_d_un_tour_solde_le_precedent():
    door, journal, _ = gate()
    door.note_addressed_turn("montre-moi le bilan", correlation_id="c1")
    assert journal.of(TURN_SILENT) == []

    door.note_addressed_turn("ouvre le graphique", correlation_id="c2")

    [line] = journal.of(TURN_SILENT)
    assert line["data"]["correlation_id"] == "c1"


def test_aucune_trace_de_la_porte_ne_transporte_la_transcription():
    """Contrainte de traçage : métadonnée seulement (`Issues/002` n'est pas un modèle)."""

    door, journal, _ = gate()
    secret = "montre-moi le bilan confidentiel de Sirius"
    door.note_addressed_turn(secret, correlation_id="c1")
    door.admit(correlation_id="c1", kind=SpeechKind.RESULT)
    door.settle_all()

    rendered = repr(journal.events)
    assert journal.events and "Sirius" not in rendered and "confidentiel" not in rendered


def test_hors_presentation_la_porte_n_enregistre_rien_et_admet_tout():
    door, journal, _ = gate(InteractionMode.ASSISTANT)

    assert door.note_addressed_turn("montre-moi le bilan", correlation_id="c1") is None
    assert door.outcome("c1") is None
    for kind in SpeechKind:
        verdict = door.admit(correlation_id="c1", kind=kind)
        assert verdict.admitted and verdict.reason == "mode_not_presentation"
    assert door.allows_preamble()
    assert journal.events == []


def test_un_journal_en_panne_ne_decide_jamais_de_la_parole():
    def broken(*args, **kwargs):
        raise RuntimeError("journal mort")

    door = PresentationSpeechGate(mode=lambda: InteractionMode.PRESENTATION, trace=broken)
    door.note_addressed_turn("montre-moi le bilan", correlation_id="c1")

    assert not door.admit(correlation_id="c1", kind=SpeechKind.RESULT).admitted


def test_le_mot_d_eveil_ne_masque_pas_le_mot_interrogatif():
    """`normalized_tokens` retire « jarvis » en tête, et le classement en dépend.

    Sans ce retrait, la marque devient `no_visual_command_evidence` : la
    situation serait encore juste, mais la trace ne dirait plus pourquoi.
    """

    assert classify_addressed_situation("Jarvis, pourquoi la marge baisse") == (
        PresentationSituation.KNOWLEDGE_QUESTION, "question_opener:pourquoi")
    # La même normalisation sert la politique de réflexe : une seule vérité.
    assert conversational_wait_reason("Jarvis, ok") == "acknowledgement_only"


def test_la_liste_des_natures_retenues_est_bornee():
    """Une trace bornée reste une trace : le compte continue, la liste non."""

    door, _, _ = gate()
    door.note_addressed_turn("montre-moi le bilan", correlation_id="c1")
    for _ in range(MAX_WITHHELD_MEMORY + 25):
        door.admit(correlation_id="c1", kind=SpeechKind.RESULT)

    outcome = door.outcome("c1")
    assert len(outcome.withheld) == MAX_WITHHELD_MEMORY and outcome.silent_reason == "silent_by_policy"


def test_la_memoire_des_tours_est_bornee():
    door, _, _ = gate()
    door.max_turns = 4
    for index in range(10):
        door.note_addressed_turn("montre-moi le bilan", correlation_id=f"c{index}")

    assert door.outcome("c0") is None and door.outcome("c9") is not None


@pytest.mark.parametrize("correlation", ["", None, 42, "x" * 257])
def test_une_correlation_inutilisable_n_est_pas_retenue(correlation):
    door, _, _ = gate()

    assert door.note_addressed_turn("montre-moi le bilan", correlation_id=correlation) is None
    # Et la parole correspondante est jugée comme une parole sans tour adressé.
    assert not door.admit(correlation_id=correlation, kind=SpeechKind.RESULT).admitted
    assert door.admit(correlation_id=correlation, kind=SpeechKind.ERROR).admitted


# ---------------------------------------------------------------------------
# L'ordonnanceur : zéro parole pour de vrai
# ---------------------------------------------------------------------------


def presenting(journal=None, *, mode=InteractionMode.PRESENTATION, session=None, reflex_delay_s=0.0):
    """Ordonnanceur relié à un observateur de mode réel, pas à un double."""

    observer = InteractionModeObserver()
    observer.adopt({"mode": mode.value, "revision": 1, "epoch": "life-1"})
    scheduler = build_scheduler(FakeCore(), session or ControllableSession(), journal=journal,
                                interaction_mode=observer, reflex_delay_s=reflex_delay_s)
    return scheduler, observer


def due(scheduler):
    """Amener l'échéance du préambule : c'est là que `decide_reflex` rend PREAMBLE."""

    scheduler._reflex.due = asyncio.get_running_loop().time() - .001
    scheduler._reflex.next_check = scheduler._reflex.due


def speech(text="Le bilan est affiché.", *, kind=SpeechKind.RESULT, correlation="c1"):
    return SpeechRequest(CONVERSATION, text, correlation_id=correlation,
                         source=source(correlation, epoch=1), kind=kind)


async def test_une_commande_visuelle_ne_fait_prononcer_aucune_parole():
    journal = RecordingJournal()
    scheduler, _ = presenting(journal)
    scheduler.note_addressed_turn("montre-moi le bilan", correlation_id="c1")
    await scheduler.start()
    try:
        scheduler._enqueue(speech())
        await asyncio.sleep(.05)

        assert scheduler.session.spoken == []
        assert scheduler._pop_next() is None
        outcome = outcome_payload(scheduler, "c1")
        assert outcome["silent"] and outcome["silent_reason"] == "silent_by_policy"
        assert outcome["withheld"] == [SpeechKind.RESULT.value]
        [withheld] = journal.of(SPEECH_WITHHELD)
        assert withheld["data"]["situation"] == PresentationSituation.VISUAL_COMMAND.value
        assert "Le bilan" not in repr(journal.events)
    finally:
        await scheduler.stop()
    assert journal.of(TURN_SILENT)


async def test_une_demande_de_parole_recue_deux_fois_n_est_retenue_qu_une_fois():
    """La porte est consultée **après** la déduplication, et c'est le bon ordre.

    Une retransmission du flux Core ne doit pas doubler le compte des paroles
    retenues : le solde du tour serait faux, et la ligne de journal aussi.
    """

    journal = RecordingJournal()
    scheduler, _ = presenting(journal)
    scheduler.note_addressed_turn("montre-moi le bilan", correlation_id="c1")
    await scheduler.start()
    try:
        request = speech()
        scheduler._enqueue(request)
        scheduler._enqueue(request)
        await asyncio.sleep(.03)

        assert outcome_payload(scheduler, "c1")["withheld_count"] == 1
        assert len(journal.of(SPEECH_WITHHELD)) == 1
    finally:
        await scheduler.stop()


async def test_un_classement_en_panne_retombe_sur_la_parole_et_le_dit():
    """Le repli d'un classement en panne est la parole, jamais le silence.

    Silencer sur panne d'analyse transformerait un défaut interne en JARVIS
    muet — exactement le genre de silence que cette Slice existe pour rendre
    impossible à confondre avec une réussite.
    """

    journal = RecordingJournal()
    scheduler, _ = presenting(journal)

    def broken(text):
        raise RuntimeError("classement impossible")

    scheduler.presentation.classify = broken
    scheduler.note_addressed_turn("montre-moi le bilan", correlation_id="c1")

    [line] = journal.of(CLASSIFICATION_FAILED)
    assert line["level"] == "warning" and line["data"]["exception_type"] == "RuntimeError"
    assert scheduler.presentation.outcome("c1").evidence == "classification_failed"
    await scheduler.start()
    try:
        scheduler._enqueue(speech())
        await wait_for(lambda: len(scheduler.session.spoken) == 1)
    finally:
        await scheduler.stop()


async def test_une_vraie_question_parle_pendant_la_meme_seance():
    scheduler, _ = presenting()
    scheduler.note_addressed_turn("montre-moi le bilan", correlation_id="c1")
    scheduler.note_addressed_turn("quel est le total ?", correlation_id="c2")
    scheduler.update_speech_context(context(CONVERSATION, "c2", epoch=1))
    await scheduler.start()
    try:
        scheduler._enqueue(speech(correlation="c1"))
        scheduler._enqueue(speech("Le total est de douze millions.", correlation="c2"))
        await wait_for(lambda: len(scheduler.session.spoken) == 1)

        assert [item.correlation_id for item in scheduler.session.spoken] == ["c2"]
        assert outcome_payload(scheduler, "c2")["silent"] is False
    finally:
        await scheduler.stop()


@pytest.mark.parametrize("kind", [SpeechKind.ERROR, SpeechKind.QUESTION])
async def test_une_panne_et_une_clarification_restent_audibles_sur_une_commande_visuelle(kind):
    scheduler, _ = presenting()
    scheduler.note_addressed_turn("montre-moi le bilan", correlation_id="c1")
    await scheduler.start()
    try:
        scheduler._enqueue(speech("Je n'ai pas pu ouvrir ce document.", kind=kind))
        await wait_for(lambda: len(scheduler.session.spoken) == 1)

        assert scheduler.session.spoken[0].kind is kind
        assert outcome_payload(scheduler, "c1")["silent"] is False
    finally:
        await scheduler.stop()


async def test_un_relais_spontane_ne_parle_pas_mais_une_panne_spontanee_si():
    """Rien ne parle sans adressage explicite, sauf ce qui est cassé."""

    scheduler, _ = presenting()
    await scheduler.start()
    try:
        scheduler._enqueue(speech("Le sous-agent a terminé.", correlation="inconnu"))
        scheduler._enqueue(speech("Le sous-agent est mort.", kind=SpeechKind.ERROR, correlation="inconnu"))
        await wait_for(lambda: len(scheduler.session.spoken) == 1)
        await asyncio.sleep(.03)

        assert [item.kind for item in scheduler.session.spoken] == [SpeechKind.ERROR]
    finally:
        await scheduler.stop()


async def test_le_remplissage_est_supprime_mais_la_politique_de_reflexe_survit():
    journal = RecordingJournal()
    scheduler, observer = presenting(journal, reflex_delay_s=.01)
    scheduler._running = True
    scheduler.note_addressed_turn("compare les prix entre ces architectures", correlation_id="c1")

    scheduler.request_reflex("compare les prix entre ces architectures", correlation_id="c1")
    due(scheduler)

    await scheduler._maybe_speak_reflex()

    decision = scheduler._reflex_decisions["c1"]
    assert decision.action is ReflexAction.WAIT and decision.reason == NO_FILLER_REASON
    assert scheduler._reflex is None and scheduler.session.reflexes == []
    # Le motif est écrit : le silence du préambule est une décision, pas un trou.
    assert any(line["data"]["reason"] == NO_FILLER_REASON and line["data"]["phase"] == "deadline"
               for line in journal.of(REFLEX_DECIDED))
    await scheduler.stop()


async def test_hors_presentation_le_preambule_repart_sur_le_meme_ordonnanceur():
    """La même instance, le même tour : seul le mode change."""

    scheduler, observer = presenting(reflex_delay_s=.01, mode=InteractionMode.ASSISTANT)
    scheduler._running = True
    scheduler.request_reflex("compare les prix entre ces architectures", correlation_id="c1")
    due(scheduler)
    await scheduler._maybe_speak_reflex()

    assert len(scheduler.session.reflexes) == 1

    observer.adopt({"mode": InteractionMode.PRESENTATION.value, "revision": 2, "epoch": "life-1"})
    scheduler.note_addressed_turn("compare encore ces deux options", correlation_id="c2")
    scheduler.request_reflex("compare encore ces deux options", correlation_id="c2")
    due(scheduler)
    await scheduler._maybe_speak_reflex()

    assert scheduler._reflex_decisions["c2"].reason == NO_FILLER_REASON
    assert len(scheduler.session.reflexes) == 1
    await scheduler.stop()


TYPED_ARCHITECTURES = (
    SimpleVoiceConfig(VoiceModelRef("openai", "gpt-realtime-2.1")),
    FrontBrainVoiceConfig(VoiceModelRef("openai", "gpt-realtime-2.1-mini"),
                          VoiceModelRef("openai", "gpt-5.6-luna")),
    DuplexVoiceConfig(VoiceModelRef("openai", "gpt-live-1")),
)


@pytest.mark.parametrize("config", TYPED_ARCHITECTURES, ids=lambda item: item.architecture.value)
def test_les_trois_architectures_typees_passent_par_la_voie_directe(config):
    """Ce que le test de la voie directe, juste en dessous, couvre réellement.

    `direct_conversation` est le seul axe que le bridge distingue : SIMPLE,
    FRONT_BRAIN et DUPLEX y sont un seul chemin, et `continuous_brain` en est
    l'autre. Sans cette assertion, « la voie directe est testée » resterait une
    affirmation sur Duplex seul — exactement l'erreur qui a rendu la politique
    inerte sur trois piles de production.
    """

    resolved = resolve_voice_composition(
        {"voice_architecture": VoiceArchitectureSettings(config).to_dict()}, environ={})

    assert resolved.direct_conversation
    # L'autre chemin, celui du cerveau, reste distinct et n'est pas direct.
    assert not resolve_voice_composition({"voice_arch": "continuous_brain"}, environ={}).direct_conversation


async def direct_stack(mode):
    """Bridge + ordonnanceur de la voie directe, câblés comme `voice_v2` le fait."""

    from tests.integration.test_front_brain_composition_review import (
        CoreBoundary, DirectSessionBoundary, source as direct_source,
    )

    observer = InteractionModeObserver()
    observer.adopt({"mode": mode.value, "revision": 1, "epoch": "life-1"})
    core, current = CoreBoundary(), direct_source()
    session = DirectSessionBoundary(current)
    scheduler = SpeechScheduler(core=core, conversation_id=CONVERSATION, session=session,
                                reconnect_delay_s=.01, output_timeout_s=.1, interaction_mode=observer)
    scheduler.update_speech_context(context(CONVERSATION))
    bridge = RealtimeConversationBridge(
        core=core, session=session, conversation_id=CONVERSATION, audio=SimpleNamespace(),
        on_addressed=lambda: None, on_mute=lambda: None, continuous=True, direct_conversation=True,
        on_conversation=scheduler.request_conversation,
        on_addressed_turn=scheduler.note_addressed_turn,
        output_admission=scheduler.output_admission,
    )
    await scheduler.start()
    await wait_for(lambda: scheduler.presentation_snapshot()["source_complete"])
    return session, scheduler, bridge, current


@pytest.mark.parametrize("mode, text, responses", [
    (InteractionMode.ASSISTANT, "Jarvis, montre-moi le bilan", 1),
    (InteractionMode.ASSISTANT, "Jarvis, quel est le total ?", 1),
    (InteractionMode.PRESENTATION, "Jarvis, montre-moi le bilan", 0),
    (InteractionMode.PRESENTATION, "Jarvis, quel est le total ?", 1),
    (InteractionMode.PRESENTATION, "Jarvis, dis-moi le total", 1),
])
async def test_la_voie_directe_classe_le_tour_puis_obeit_a_la_politique(mode, text, responses):
    """Le tour arrive par un vrai transcript, pas par un amorçage à la main.

    La première version de ce test appelait `note_addressed_turn` elle-même
    avant `request_conversation` : elle exerçait le code de la porte sans
    jamais atteindre l'état que la porte existe pour juger, parce que la
    production ne l'y mettait pas. Résultat : PRESENTATION était **muet** sur
    les trois architectures typées, et le test passait.

    Ici, seul `bridge._handle_transcript` est appelé — la classification, si
    elle se produit, vient du chemin de production.
    """

    session, scheduler, bridge, _ = await direct_stack(mode)
    try:
        await bridge._handle_transcript(ProtocolEnvelope(
            "realtime.transcript", {"item_id": "input", "text": text}))
        await asyncio.sleep(.05)

        assert len(session.requests) == responses
    finally:
        await scheduler.stop()


async def test_la_voie_directe_classe_le_tour_sous_l_identite_que_l_admission_rend():
    """L'identité du tour est celle de l'admission, pas celle du cerveau.

    Sur cette voie `_last_correlation_id` reste `None` : lire cet attribut,
    comme le faisait la première version, revenait à ne rien classer du tout.
    """

    session, scheduler, bridge, current = await direct_stack(InteractionMode.PRESENTATION)
    try:
        assert bridge._last_correlation_id is None
        await bridge._handle_transcript(ProtocolEnvelope(
            "realtime.transcript", {"item_id": "input", "text": "Jarvis, montre-moi le bilan"}))
        await asyncio.sleep(.05)

        outcome = scheduler.presentation.outcome(current.correlation_id)
        assert outcome is not None and outcome.situation is PresentationSituation.VISUAL_COMMAND
        assert outcome.silent_reason == "silent_by_policy"
    finally:
        await scheduler.stop()


async def test_une_reponse_directe_refusee_n_est_comptee_qu_une_fois():
    """La déduplication précède la porte sur les deux voies, pas sur une seule."""

    journal = RecordingJournal()
    scheduler, _ = presenting(journal)
    scheduler.note_addressed_turn("montre-moi le bilan", correlation_id="c1")
    await scheduler.start()
    try:
        origin = source("c1", epoch=1)
        assert not scheduler.request_conversation(input_item_ids=("item-1",), source=origin)
        assert not scheduler.request_conversation(input_item_ids=("item-1",), source=origin)

        assert scheduler.presentation.outcome("c1").withheld == (SpeechKind.RESULT,)
        assert len(journal.of(SPEECH_WITHHELD)) == 1
    finally:
        await scheduler.stop()


async def test_un_changement_de_mode_en_cours_de_seance_est_pris_au_tour_suivant():
    """Décision D15 : le mode bouge à chaud, sans redémarrer quoi que ce soit."""

    scheduler, observer = presenting(mode=InteractionMode.ASSISTANT)
    await scheduler.start()
    try:
        scheduler.note_addressed_turn("montre-moi le bilan", correlation_id="c1")
        scheduler._enqueue(speech(correlation="c1"))
        await wait_for(lambda: len(scheduler.session.spoken) == 1)

        await scheduler.handle_core_event(ProtocolEnvelope(
            message_type="interaction.mode.changed",
            payload={"mode": InteractionMode.PRESENTATION.value, "revision": 2, "epoch": "life-1"}))
        assert observer.mode is InteractionMode.PRESENTATION
        scheduler.note_addressed_turn("montre-moi le graphique", correlation_id="c2")
        scheduler.update_speech_context(context(CONVERSATION, "c2", epoch=1))
        scheduler._enqueue(speech("Le graphique est affiché.", correlation="c2"))
        await asyncio.sleep(.05)

        assert len(scheduler.session.spoken) == 1
        assert outcome_payload(scheduler, "c2")["silent_reason"] == "silent_by_policy"
    finally:
        await scheduler.stop()


# ---------------------------------------------------------------------------
# Décision 14 : le mode assistant ne bouge pas, dans les trois architectures
# ---------------------------------------------------------------------------


#: Les trois compositions vocales, réduites à ce qui les distingue du point de
#: vue de l'ordonnanceur : Simple et Front Brain font dire un texte du cerveau,
#: Duplex fait répondre la surface elle-même.
ARCHITECTURE_SHAPES = ("simple", "front_brain", "duplex")


@pytest.mark.parametrize("architecture", ARCHITECTURE_SHAPES)
@pytest.mark.parametrize("observed", [None, InteractionMode.ASSISTANT])
async def test_le_mode_assistant_se_comporte_comme_avant_dans_les_trois_architectures(architecture, observed):
    """`observed=None` est l'ordonnanceur d'avant cette Slice : aucun observateur.

    Les deux colonnes doivent produire le même résultat, sinon l'ajout de
    l'observateur aurait changé le comportement par sa seule présence.
    """

    journal = RecordingJournal()
    if observed is None:
        scheduler = build_scheduler(FakeCore(), ControllableSession(), journal=journal, reflex_delay_s=.01)
    else:
        scheduler, _ = presenting(journal, mode=observed, reflex_delay_s=.01)
    await scheduler.start()
    try:
        scheduler.note_addressed_turn("montre-moi le bilan", correlation_id="c1")
        if architecture == "front_brain":
            # Le préambule de surface est ce qui distingue Front Brain ici : il
            # doit continuer de partir tant que le mode est assistant.
            scheduler.request_reflex("compare les prix entre ces architectures", correlation_id="c1")
            due(scheduler)
            # La décision, pas l'élocution : un préambule réellement prononcé
            # occuperait la surface et masquerait la parole vérifiée ensuite.
            assert scheduler._decide_reflex(scheduler._reflex).action is ReflexAction.PREAMBLE
            scheduler._invalidate_reflex("test_teardown")
        if architecture == "duplex":
            assert scheduler.request_conversation(input_item_ids=("item-1",), source=source("c1", epoch=1))
        else:
            scheduler._enqueue(speech(correlation="c1"))
            await wait_for(lambda: len(scheduler.session.spoken) == 1)
            assert scheduler.session.spoken[0].kind is SpeechKind.RESULT
        assert outcome_payload(scheduler, "c1") is None
    finally:
        await scheduler.stop()


@pytest.mark.parametrize("architecture", ARCHITECTURE_SHAPES)
async def test_le_mode_assistant_ne_laisse_aucune_trace_de_presentation(architecture):
    """Preuve d'**absence** : hors présentation, aucune des lignes de cette Slice.

    C'est la seule assertion d'absence du fichier, et elle porte sur des
    évènements observés, pas sur du texte source : une porte qui journaliserait
    en mode assistant aurait déjà commencé à décider quelque chose.
    """

    journal = RecordingJournal()
    scheduler, _ = presenting(journal, mode=InteractionMode.ASSISTANT, reflex_delay_s=.01)
    await scheduler.start()
    try:
        scheduler.note_addressed_turn("montre-moi le bilan", correlation_id="c1")
        if architecture == "duplex":
            scheduler.request_conversation(input_item_ids=("item-1",), source=source("c1", epoch=1))
        else:
            scheduler._enqueue(speech(correlation="c1"))
        if architecture == "front_brain":
            scheduler.request_reflex("compare les prix entre ces architectures", correlation_id="c1")
            due(scheduler)
            await scheduler._maybe_speak_reflex()
        await asyncio.sleep(.03)
    finally:
        await scheduler.stop()

    for kind in (SPEECH_WITHHELD, TURN_SILENT, TURN_CLASSIFIED):
        assert journal.of(kind) == []


def test_l_ordonnanceur_ne_peut_pas_etre_construit_sans_sa_porte():
    """La porte n'est pas optionnelle : elle existe même sans observateur de mode."""

    scheduler = SpeechScheduler(core=FakeCore(), conversation_id=CONVERSATION, session=ControllableSession())

    assert isinstance(scheduler.presentation, PresentationSpeechGate)
    assert not scheduler.presentation.active and scheduler.presentation.allows_preamble()


# ---------------------------------------------------------------------------
# Le prompt suit le runtime, il ne le remplace pas
# ---------------------------------------------------------------------------


def turn(text="montre-moi le bilan"):
    return BrainTurnInput(conversation_id=CONVERSATION, text=text)


@pytest.mark.parametrize("mode, present", [
    (InteractionMode.ASSISTANT, False),
    (InteractionMode.PRESENTATION, True),
    (InteractionMode.MEETING, True),
])
def test_le_contexte_du_tour_ne_porte_le_mode_que_lorsqu_il_change_quelque_chose(mode, present):
    """Au mode par défaut, le contexte est exactement celui d'avant (Décision 14)."""

    context_payload = _turn_context(turn(), None, interaction_mode=mode)

    assert ("interaction_mode" in context_payload) is present
    assert set(context_payload) - {"interaction_mode"} == {"addressing"}


def test_le_backend_prend_le_mode_effectif_de_core_et_jamais_un_mode_reserve():
    backend = ControlCenterBrainBackend(base_url="http://127.0.0.1:1")
    backend.observe_interaction_mode(InteractionMode.PRESENTATION)
    assert _turn_context(turn(), None, interaction_mode=backend._interaction_mode)["interaction_mode"] == "presentation"

    # REUNION est annoncé mais pas implémenté : le comportement servi reste
    # celui du mode assistant, et rien ne descend jusqu'au modèle.
    backend.observe_interaction_mode(InteractionMode.MEETING)
    assert backend._interaction_mode is InteractionMode.ASSISTANT


async def test_core_remet_le_mode_au_backend_cerveau(tmp_path):
    """Le câblage du composition root, exercé par la vraie voie — pas relu.

    Le changement passe par `request()`, la seule porte d'entrée du mode :
    un test qui appellerait `_notify` prouverait que l'abonné est appelé, pas
    qu'il est abonné au bon endroit.
    """

    seen: list[InteractionMode] = []

    class Backend:
        def observe_interaction_mode(self, value):
            seen.append(value)

    core = JarvisCoreApplication(data_root=tmp_path / "data", brain_backend=Backend())
    await core.interaction_mode.request(InteractionMode.PRESENTATION.value, source="test")
    await core.interaction_mode.request(InteractionMode.ASSISTANT.value, source="test")

    assert seen == [InteractionMode.PRESENTATION, InteractionMode.ASSISTANT]


def test_la_consigne_de_tour_ne_parle_de_presentation_que_en_presentation():
    presenting_brief = build_agent_brief({"addressing": AddressingDecision.ADDRESSED.value,
                                          "interaction_mode": InteractionMode.PRESENTATION.value},
                                         "montre-moi le bilan")
    plain_brief = build_agent_brief({"addressing": AddressingDecision.ADDRESSED.value}, "montre-moi le bilan")

    assert BRIEF_PRESENTATION_MODE in presenting_brief
    assert BRIEF_PRESENTATION_MODE not in plain_brief
    # Le tour lui-même ne bouge pas : la consigne s'ajoute, elle ne réécrit rien.
    assert presenting_brief.endswith(plain_brief.split("[Demande]")[-1])


async def test_le_contrat_tient_meme_si_le_modele_n_a_jamais_lu_la_consigne():
    """La raison d'être de la Slice : la règle ne dépend pas d'un prompt lu.

    Rien de ce test ne rend une consigne au modèle — le cerveau est un double
    qui demande la parole exactement comme s'il n'avait rien lu. La commande
    visuelle se termine quand même sans un mot.
    """

    scheduler, _ = presenting()
    scheduler.note_addressed_turn("montre-moi le bilan", correlation_id="c1")
    await scheduler.start()
    try:
        for kind in (SpeechKind.ACK, SpeechKind.PROGRESS, SpeechKind.RESULT):
            scheduler._enqueue(speech(f"Voilà, c'est affiché ({kind.value}).", kind=kind))
        await asyncio.sleep(.05)

        assert scheduler.session.spoken == []
        assert outcome_payload(scheduler, "c1")["withheld_count"] == 3
    finally:
        await scheduler.stop()


async def test_le_bridge_remet_chaque_tour_adresse_a_la_politique():
    """Le câblage du bridge, exercé par un vrai transcript — pas relu.

    Sans cet appel, la porte ne connaîtrait aucun tour : toute parole serait
    jugée « sans tour adressé », et le mode présentation deviendrait muet sauf
    pour les pannes. Un câblage manquant se voit ici, pas en production.
    """

    seen: list[tuple[str, dict[str, object]]] = []
    bridge = build_bridge(GuardedAudio(guarded=False),
                          on_addressed_turn=lambda text, **kw: seen.append((text, kw)))

    await feed(bridge, [event("realtime.transcript", text="Jarvis, montre-moi le bilan", item_id="i1")])

    assert len(seen) == 1
    text, options = seen[0]
    assert text == "Jarvis, montre-moi le bilan"
    assert options["correlation_id"].endswith(":i1")
    # Et la politique en tire bien une commande visuelle.
    assert classify_addressed_situation(text)[0] is PresentationSituation.VISUAL_COMMAND


async def test_la_composition_de_production_cable_la_politique_sur_le_bridge(monkeypatch):
    """Le composition root, vérifié sur les objets vivants — pas sur du source.

    Slice 05 a laissé une leçon : un contrat peut être entièrement juste et
    n'être branché nulle part. Ici le runtime réel est éveillé, et le bridge
    qu'il vient de construire doit tenir la méthode de l'ordonnanceur qu'il
    vient de construire — pas une autre, pas `None`.
    """

    from tests.unit.test_v2_continuous_live import (
        ContinuousSession, RecordingJournal as LiveJournal, _runtime, _wake,
    )

    session = ContinuousSession()
    journal = LiveJournal()
    runtime, wakeword, _ = _runtime(monkeypatch, session=session, journal=journal)
    run_task = await _wake(runtime, wakeword, journal)
    try:
        assert runtime._speech is not None
        assert runtime._bridge.on_addressed_turn == runtime._speech.note_addressed_turn
        assert isinstance(runtime._speech.presentation, PresentationSpeechGate)
        # Ce runtime-ci est la voie du cerveau ; l'attribut ne dit pas que le
        # point d'appel est atteignable. Les deux moitiés de cette preuve sont
        # `test_le_bridge_remet_chaque_tour_adresse_a_la_politique` (voie du
        # cerveau) et `test_la_voie_directe_classe_le_tour_puis_obeit_a_la_politique`
        # (voie directe), qui passent chacune par un vrai transcript.
        assert runtime._bridge.direct_conversation is False
    finally:
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


# ---------------------------------------------------------------------------
# La nature de parole a un producteur, et elle reste hors de portée du modèle
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("answer, expected", [
    ("De quel bilan parles-tu, le Q3 ou le Q4 ?", SpeechKind.QUESTION),
    ("Le Q3 ou le Q4 ?", SpeechKind.QUESTION),
    ("Tu veux le bilan du 30.06 ou du 31.12 ?", SpeechKind.QUESTION),
    ("Voilà le bilan. Tu veux aussi le Q4 ?", SpeechKind.RESULT),
    ("Je regarde... Tu veux quoi ?", SpeechKind.RESULT),
    ("C'est fait.", SpeechKind.RESULT),
    ("", SpeechKind.RESULT),
])
def test_une_reponse_qui_est_une_question_et_rien_d_autre_porte_la_nature_question(answer, expected):
    """Le producteur qui manquait : sans lui, la clarification était une promesse.

    `SpeechKind.QUESTION` a toute sa sémantique dans Core depuis l'origine
    (`BrainOrchestrator._revise_question`), et **aucun producteur** ne
    l'émettait : la voie était morte, et l'exception de sûreté de la matrice ne
    protégeait rien. La borne est stricte à dessein — une phrase interrogative
    et rien d'autre — pour qu'une réponse ordinaire suivie d'une question de
    politesse reste un résultat, sans quoi la nature deviendrait une porte de
    sortie qu'il suffirait de ponctuer.
    """

    assert public_answer_kind(answer) is expected


async def test_une_clarification_est_dite_sur_une_commande_visuelle_bout_en_bout():
    """Le défaut que la déviation existait pour corriger, sur le chemin réel.

    La réponse arrive avec la nature que Core vient de calculer, pas avec une
    étiquette choisie par le modèle, et la matrice l'admet par
    `safety_speech_kinds`.
    """

    clarification = "De quel bilan parles-tu, le Q3 ou le Q4 ?"
    scheduler, _ = presenting()
    scheduler.note_addressed_turn("montre-moi le bilan", correlation_id="c1")
    await scheduler.start()
    try:
        scheduler._enqueue(speech(clarification, kind=public_answer_kind(clarification)))
        await wait_for(lambda: len(scheduler.session.spoken) == 1)

        assert scheduler.session.spoken[0].kind is SpeechKind.QUESTION
        assert scheduler.presentation.outcome("c1").silent is False
    finally:
        await scheduler.stop()


#: Chaque site de production qui fabrique une `SpeechRequest`, et l'expression
#: exacte dont sa nature sort. Table déclarée : un site nouveau, ou une
#: expression changée, fait échouer ce test **par son nom**.
SPEECH_KIND_SITES = {
    "jarvis/adapters/control_center_brain.py": ["public_answer_kind(answer)", "SpeechKind.ERROR"],
    "jarvis/adapters/openai_realtime_frontend.py": ["<default>"],
    "jarvis/core/brain_service.py": ["SpeechKind.RESULT", "SpeechKind.RESULT", "SpeechKind.ERROR"],
    "jarvis/runtime/back_brain_delegation.py": ["SpeechKind.ACK if accepted else SpeechKind.ERROR"],
    # Slice 11 : la clarification du tour adressé. La **nature** est décidée par
    # la Slice 10 (`AddressedTurnOutcome.speech_kind`, littéral `SpeechKind.QUESTION`
    # dans `jarvis/core/presentation_addressed_turn.py`), la requête est bâtie
    # ici. La Slice 10 n'en construisait aucune, donc ce site n'existait pas
    # encore quand la garde a été écrite : sa page contractuelle affirmait le
    # contraire, et la correction est ce report-ci.
    #
    # Le littéral est écrit ici plutôt que recopié depuis le verdict : la garde
    # refuse un nom nu, et elle a raison — un champ recopié est un champ qu'un
    # producteur futur peut remplir autrement, alors que `VISUAL_COMMAND`
    # n'admet `QUESTION` que comme nature de **sûreté**. Le site refuse tout
    # autre verdict au lieu de le parler.
    "jarvis/runtime/speech_scheduler.py": ["SpeechKind.QUESTION"],
}

#: Fonctions de Core autorisées à décider une nature. Elles lisent le contenu,
#: elles ne lisent pas un champ rempli par l'agent.
KIND_DECIDERS = {"public_answer_kind"}


def test_aucun_site_de_production_ne_laisse_le_modele_nommer_sa_nature_de_parole():
    """Assertion sur le **source**, et sur une absence : la seule forme qui la prouve.

    Ne pas supprimer au motif de la règle « pas d'assertion sur le texte
    source » : ce test existe pour prouver qu'un appel n'existe **nulle part**,
    ce qu'aucun test de comportement ne peut faire. Même exception, et même
    raison, que `test_every_site_that_opens_a_physical_input_registers_its_owner`
    (Slice 05).

    Ce qu'il garde : la matrice admet `ERROR` et `QUESTION` malgré le plafond
    (`safety_speech_kinds`). Tant que la nature est posée par Core — un membre
    littéral de `SpeechKind`, ou l'une des fonctions de `KIND_DECIDERS`, qui
    lisent le contenu — l'agent ne peut pas franchir le plafond en écrivant un
    mot différent dans un champ. Le jour où un outil laisserait l'agent nommer
    sa nature, ce test tombe, et la question se repose avant la fusion, pas
    après.
    """

    import ast

    root = pathlib.Path(__file__).resolve().parents[2]
    found: dict[str, list[str]] = {}
    for path in sorted(root.joinpath("jarvis").rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if relative.startswith("jarvis/testlab/"):
            continue
        # `utf-8-sig` : un BOM ferait échouer `ast.parse` sur un fichier du
        # dépôt (constat de la Slice 01).
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=relative)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "SpeechRequest"):
                continue
            kinds = [keyword.value for keyword in node.keywords if keyword.arg == "kind"]
            found.setdefault(relative, []).append(
                ast.unparse(kinds[0]) if kinds else "<default>")

    # Trié : `ast.walk` ne rend pas l'ordre du source, et cette table nomme les
    # sites, pas leur position.
    assert {name: sorted(values) for name, values in found.items()} == {
        name: sorted(values) for name, values in SPEECH_KIND_SITES.items()}

    def value_positions(node, where):
        """Chaque position qui **produit** la nature, une par une."""

        if isinstance(node, ast.IfExp):
            value_positions(node.body, where)
            value_positions(node.orelse, where)
            return
        if isinstance(node, ast.Attribute):
            assert isinstance(node.value, ast.Name) and node.value.id == "SpeechKind", where
            return
        if isinstance(node, ast.Call):
            assert isinstance(node.func, ast.Name) and node.func.id in KIND_DECIDERS, where
            return
        # Un nom nu, un indice de dictionnaire, un `SpeechKind(valeur)` : tout
        # ce par quoi une nature pourrait venir d'ailleurs que de Core.
        raise AssertionError(f"{where}: la nature ne vient pas d'un membre de SpeechKind ni de KIND_DECIDERS")

    for relative, expressions in found.items():
        for expression in expressions:
            if expression != "<default>":
                value_positions(ast.parse(expression, mode="eval").body, f"{relative}: {expression}")

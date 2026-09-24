"""Observation ambiante : ce qui a été entendu dans la salle, jamais un ordre.

Décision **D03**, verrouillée : « Ambient statements can trigger understanding,
research, or fact-check preparation but cannot authorize user-visible or
persistent actions merely because they contain imperative language. » Ce module
est l'endroit où cette phrase devient une **structure de données**, pas une
convention d'appelant :

- `AmbientUtterance` et `AmbientTrigger` portent `authorizes_actions = False`
  en `ClassVar`, comme `PresentationContextSnapshot` et
  `VoiceConversationSnapshot`. Une instance qui dirait le contraire ne peut pas
  être construite, ni par `replace()`, ni par un champ oublié ;
- le vocabulaire de déclencheurs (`AmbientTriggerKind`) est **fermé** et ne
  contient que des natures d'*enquête* — une affirmation vérifiable, une
  référence à retrouver, une question restée ouverte, un sujet nouveau. Il n'y
  a aucune nature « exécuter », et il ne peut pas y en avoir sans changer ce
  fichier ;
- l'analyse bon marché (`analyse_ambient_text`) **reconnaît** l'impératif —
  « ouvre le fichier », « supprime la ligne 12 » — et ne le transforme en
  rien. `AmbientAnalysis.imperative` existe pour que ce soit *observable* :
  une garde qu'on ne peut pas compter est une intention.

Pourquoi l'enum d'adressage n'est pas élargie (G7)
--------------------------------------------------

`AddressingDecision{ADDRESSED, AMBIENT, UNCERTAIN}` (`jarvis/domain/v2.py`) est
fermée, encodée sur le fil (`protocol/server.py`) et persistée telle quelle
(`sqlite_state.py`). `AMBIENT` y est **refusé** à deux endroits —
`BrainTurnInput.__post_init__` et `VoiceTurnAdmissionRequest.__post_init__` —
et ces deux refus ne bougent pas. L'observation ambiante a donc son propre
chemin, ses propres types, et ne croise jamais l'admission adressée.

Coût
----

Tout ici est de l'analyse **bon marché** : des tests de forme sur une chaîne
déjà bornée, sans modèle, sans réseau, sans appel d'agent (D08 — le travail
cher est spéculatif et se mérite, et il appartient à la Slice 08). Le budget
visé est la dizaine de microsecondes par énonciation, mesuré par la suite.

Pur : bibliothèque standard, `jarvis.domain._checks`, et les bornes déjà posées
par `jarvis.domain.presentation_working_set` — dont ce module est le
producteur, et dont il réutilise donc les limites plutôt que d'en inventer de
secondes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, ClassVar

from jarvis.domain._checks import check_text
from jarvis.domain.presentation_working_set import (
    MAX_CLAIM_CHARS,
    MAX_ENTITY_LABEL_CHARS,
    MAX_PRESENTATION_ID_CHARS,
    MAX_QUESTION_CHARS,
    MAX_TAIL_ENTRY_CHARS,
    MAX_TOPIC_LABEL_CHARS,
    presentation_id,
)

# --------------------------------------------------------------------------
# Bornes — chacune avec sa raison, convention de `work_state` / `brain_context`
# --------------------------------------------------------------------------

#: Le texte d'une énonciation ambiante ne dépasse pas ce que le fil de séance
#: accepte : le produire plus long ne ferait que le faire refuser en aval.
MAX_AMBIENT_TEXT_CHARS = MAX_TAIL_ENTRY_CHARS

#: Combien de déclencheurs une seule énonciation peut produire. Quatre : une
#: phrase qui « déclenche » six enquêtes n'en déclenche aucune utilement, et la
#: Slice 08 doit pouvoir borner sa file sur un maximum connu.
MAX_TRIGGERS_PER_UTTERANCE = 4

#: Combien de sujets / entités une analyse bon marché propose par énonciation.
#: Deux : au-delà, l'heuristique invente plus qu'elle ne lit.
MAX_TOPICS_PER_UTTERANCE = 2
MAX_ENTITIES_PER_UTTERANCE = 4

#: Le fragment cité par un déclencheur. Même borne qu'une affirmation du
#: working set : c'est exactement ce qu'il deviendra.
MAX_TRIGGER_TEXT_CHARS = MAX_CLAIM_CHARS

#: Sous ce nombre de mots, une énonciation n'est pas une affirmation
#: vérifiable : « oui », « trois », « d'accord ». Quatre mots est le plus petit
#: sujet-verbe-complément chiffré qu'on rencontre (« la marge est de 12 »).
MIN_CLAIM_WORDS = 4


class AmbientObservationError(ValueError):
    """Refus nommé, convention de la Slice 01 : `code` stable, message humain."""

    __slots__ = ("code",)

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------
# Vocabulaires fermés
# --------------------------------------------------------------------------


class AmbientTriggerKind(StrEnum):
    """Ce qu'une phrase entendue peut faire **chercher**. Rien d'autre.

    Il n'existe volontairement aucune valeur « exécuter », « ouvrir »,
    « écrire ». Ajouter une telle valeur demanderait de modifier ce fichier et
    ferait tomber `test_aucun_declencheur_ambiant_n_autorise_une_action`, qui
    parcourt l'énumération entière.
    """

    #: Une affirmation qu'on pourrait confronter à une source (Slice 09).
    CHECKABLE_CLAIM = "checkable_claim"
    #: Un document, une page, une étude nommés : à retrouver (Slice 08).
    EXTERNAL_REFERENCE = "external_reference"
    #: Une question posée dans la salle et restée sans réponse.
    OPEN_QUESTION = "open_question"
    #: Un sujet qui vient d'apparaître dans le discours.
    NEW_TOPIC = "new_topic"


# --------------------------------------------------------------------------
# Lexiques — volontairement petits, français, et lisibles
# --------------------------------------------------------------------------

#: Ce qui ne porte aucune information : hésitations, acquiescements, amorces.
#: Une énonciation entièrement faite de ces mots est supprimée avant toute
#: analyse (« Suppress low-value filler », SLICE.md).
FILLER_WORDS = frozenset(
    {
        "euh", "euuh", "heu", "hum", "hmm", "mmh", "ben", "bah", "bon", "voila",
        "voilà", "donc", "alors", "enfin", "quoi", "hein", "ok", "okay", "oui",
        "ouais", "non", "d'accord", "daccord", "merci", "pardon", "attends",
        "attendez", "et", "mais", "du", "coup", "juste", "genre", "comment",
        "dire", "je", "veux", "on", "va", "c'est", "ca", "ça",
    }
)

_INTERROGATIVES = (
    "pourquoi", "comment", "combien", "quand", "où", "ou est", "qui", "quoi",
    "quel", "quelle", "quels", "quelles", "est-ce que", "qu'est-ce",
)

#: Les noms qui désignent une chose qu'on peut aller chercher.
_REFERENCE_NOUNS = (
    "rapport", "document", "étude", "etude", "article", "slide", "diapositive",
    "graphique", "tableau", "page", "chapitre", "annexe", "source", "dossier",
    "note", "publication", "enquête", "enquete", "bilan", "contrat",
)

#: Les formes qui rendent une phrase vérifiable sans chiffre : superlatifs,
#: absolus, comparaisons.
_ASSERTIVE_MARKERS = (
    "toujours", "jamais", "le plus", "la plus", "les plus", "premier",
    "première", "premiere", "record", "plus de", "moins de", "deux fois",
    "la moitié", "la moitie", "aucun", "tous les", "majorité", "majorite",
)

#: Verbes d'action à l'impératif ou à la deuxième personne. **Reconnus pour
#: être comptés, jamais pour être suivis** — voir l'en-tête et D03.
_IMPERATIVE_STEMS = (
    "ouvre", "ouvrez", "ferme", "fermez", "supprime", "supprimez", "efface",
    "effacez", "crée", "cree", "créez", "creez", "écris", "ecris", "écrivez",
    "ecrivez", "envoie", "envoyez", "lance", "lancez", "exécute", "execute",
    "exécutez", "executez", "installe", "installez", "affiche", "affichez",
    "montre", "montrez", "ajoute", "ajoutez", "change", "changez", "modifie",
    "modifiez", "déplace", "deplace", "renomme", "renommez", "télécharge",
    "telecharge", "rédige", "redige", "appelle", "appelez", "arrête", "arrete",
    "arrêtez", "arretez", "mets", "mettez", "va", "allez", "fais", "faites",
)

_WORD = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ'’-]+")
_DIGIT = re.compile(r"\d")
_URL = re.compile(r"(?:https?://|www\.)\S+|\b[\w-]+\.(?:fr|com|org|net|io|eu)\b", re.IGNORECASE)
_ACRONYM = re.compile(r"\b[A-Z]{2,6}\b")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")
#: Déterminants : le mot qui suit l'un d'eux est, en français courant, un nom.
#: C'est l'heuristique de sujet la moins chère qui ait une précision utilisable
#: — bien meilleure que « le mot long de la phrase », qui rend des verbes
#: conjugués (« atteint ») et pollue un ensemble de sujets borné à douze.
_DETERMINERS = frozenset(
    {
        "le", "la", "les", "l'", "un", "une", "des", "du", "notre", "nos",
        "votre", "vos", "leur", "leurs", "ce", "cet", "cette", "ces", "mon",
        "ma", "mes", "son", "sa", "ses",
    }
)

#: Mots-outils qui ne font jamais un sujet, même précédés d'un déterminant.
_TOPIC_STOPWORDS = frozenset(
    {
        "aujourd'hui", "maintenant", "beaucoup", "pendant", "toujours", "jamais",
        "vraiment", "quelque", "quelques", "certains", "certaines", "plusieurs",
        "comment", "pourquoi", "combien", "lorsque", "puisque", "parce",
        "ensuite", "d'abord", "surtout", "justement", "évidemment", "evidemment",
        "voilà", "voila", "chose", "choses", "truc", "trucs", "fois", "moment",
        "gens", "monde", "temps", "point", "partie", "suite", "reste",
    }
)


def _normalize(text: str) -> str:
    return " ".join(str(text).casefold().split())


def clip_ambient_text(text: str, limit: int = MAX_AMBIENT_TEXT_CHARS) -> str:
    """Ramener un texte de fournisseur sous sa borne, sans lever.

    Un fournisseur de transcription n'a aucune obligation de tenir nos bornes.
    Refuser sa réponse ferait perdre la parole ; la couper la garde. La coupe
    est dite par l'appelant (`ambient_text_clipped`), jamais silencieuse.
    """

    value = " ".join(str(text).split())
    if len(value) <= limit:
        return value
    return value[:limit].rstrip()


# --------------------------------------------------------------------------
# Types
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AmbientUtterance:
    """Une énonciation entendue dans la salle. **Du contexte, jamais un ordre.**

    `authorizes_actions` est un `ClassVar` fixé à `False` : la même position que
    `PresentationContextSnapshot` et `VoiceConversationSnapshot`. Il n'existe
    aucun chemin, pas même `dataclasses.replace`, par lequel une énonciation
    ambiante deviendrait autorisante.
    """

    utterance_id: str
    session_id: str
    text: str
    spoken_at: datetime
    duration_s: float = 0.0
    revision: int = 0
    #: `True` quand la coupe de durée maximale a interrompu la phrase : la
    #: suite arrivera en révision de cette même énonciation.
    truncated: bool = False

    authorizes_actions: ClassVar[bool] = False

    def __post_init__(self) -> None:
        presentation_id("utterance_id", self.utterance_id)
        presentation_id("session_id", self.session_id)
        # Le texte est de la parole : `<` y est légitime (« si a < b alors »).
        # Seuls le type et la taille comptent — et c'est le refus de tout ce
        # qui n'est pas une `str` qui interdit un tampon de PCM.
        check_text("ambient text", self.text, MAX_AMBIENT_TEXT_CHARS, single_line=False)
        if not isinstance(self.spoken_at, datetime) or self.spoken_at.tzinfo is None:
            raise AmbientObservationError(
                "ambient_utterance_naive_time", "spoken_at doit porter un fuseau horaire",
            )
        if not isinstance(self.duration_s, (int, float)) or isinstance(self.duration_s, bool):
            raise AmbientObservationError("ambient_utterance_invalid_duration", "duration_s doit être un nombre")
        if not 0.0 <= float(self.duration_s) <= 3600.0:
            raise AmbientObservationError("ambient_utterance_invalid_duration", "duration_s doit être borné")
        if type(self.revision) is not int or self.revision < 0:
            raise AmbientObservationError("ambient_utterance_invalid_revision", "revision doit être un entier positif")
        if not isinstance(self.truncated, bool):
            raise AmbientObservationError("ambient_utterance_invalid_truncated", "truncated doit être un booléen")

    @property
    def empty(self) -> bool:
        return not self.text.strip()

    def to_payload(self) -> dict[str, Any]:
        return {
            "utterance_id": self.utterance_id,
            "session_id": self.session_id,
            "text": self.text,
            "spoken_at": self.spoken_at.isoformat(),
            "duration_s": round(float(self.duration_s), 3),
            "revision": self.revision,
            "truncated": self.truncated,
            "authorizes_actions": False,
        }

    def to_journal(self) -> dict[str, Any]:
        """Forme journalisable : des compteurs et des identifiants bornés.

        **Jamais le texte.** Le fil de séance applique déjà cette règle
        (`docs/presentation-working-set.md` § Journal) ; une lane qui produit
        la parole doit l'appliquer à la source.
        """

        return {
            "utterance_id": self.utterance_id[:MAX_PRESENTATION_ID_CHARS],
            "sequence_chars": len(self.text),
            "duration_s": round(float(self.duration_s), 3),
            "revision": self.revision,
            "truncated": self.truncated,
        }


@dataclass(frozen=True, slots=True)
class AmbientTrigger:
    """Une piste d'enquête née d'une phrase entendue. Sans pouvoir d'agir.

    La Slice 08 consomme ces déclencheurs pour préparer du travail spéculatif,
    et la Slice 09 pour la vérification de faits. Ni l'une ni l'autre ne reçoit
    ici la permission d'agir : `authorizes_actions` est fixé, et
    `AmbientTriggerKind` ne contient aucune nature d'action.
    """

    kind: AmbientTriggerKind
    utterance_id: str
    text: str
    confidence: float = 0.5

    authorizes_actions: ClassVar[bool] = False

    def __post_init__(self) -> None:
        if not isinstance(self.kind, AmbientTriggerKind):
            raise AmbientObservationError("ambient_trigger_invalid_kind", "kind doit être un AmbientTriggerKind")
        presentation_id("utterance_id", self.utterance_id)
        check_text("trigger text", self.text, MAX_TRIGGER_TEXT_CHARS, single_line=False)
        if not self.text.strip():
            raise AmbientObservationError("ambient_trigger_empty", "un déclencheur cite toujours ce qui l'a produit")
        if not isinstance(self.confidence, (int, float)) or isinstance(self.confidence, bool):
            raise AmbientObservationError("ambient_trigger_invalid_confidence", "confidence doit être un nombre")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise AmbientObservationError("ambient_trigger_invalid_confidence", "confidence doit être dans [0, 1]")

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "utterance_id": self.utterance_id,
            "text": self.text,
            "confidence": round(float(self.confidence), 3),
            "authorizes_actions": False,
        }


@dataclass(frozen=True, slots=True)
class AmbientAnalysis:
    """Le résultat de l'analyse bon marché d'une énonciation.

    `filler` et `imperative` sont deux constats, pas deux permissions :
    - `filler` dit que rien ne mérite d'être rangé — la lane compte et passe ;
    - `imperative` dit que la phrase avait la forme d'un ordre, ce qui ne change
      **rien** à ce qui en sort. C'est le compteur qui rend D03 observable.
    """

    utterance_id: str
    filler: bool = False
    imperative: bool = False
    topics: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    claims: tuple[str, ...] = ()
    questions: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    triggers: tuple[AmbientTrigger, ...] = ()

    authorizes_actions: ClassVar[bool] = False

    def __post_init__(self) -> None:
        presentation_id("utterance_id", self.utterance_id)
        for name, values, limit, count in (
            ("topics", self.topics, MAX_TOPIC_LABEL_CHARS, MAX_TOPICS_PER_UTTERANCE),
            ("entities", self.entities, MAX_ENTITY_LABEL_CHARS, MAX_ENTITIES_PER_UTTERANCE),
            ("claims", self.claims, MAX_CLAIM_CHARS, MAX_TRIGGERS_PER_UTTERANCE),
            ("questions", self.questions, MAX_QUESTION_CHARS, MAX_TRIGGERS_PER_UTTERANCE),
            ("references", self.references, MAX_TRIGGER_TEXT_CHARS, MAX_TRIGGERS_PER_UTTERANCE),
        ):
            if not isinstance(values, tuple) or len(values) > count:
                raise AmbientObservationError(
                    f"ambient_analysis_invalid_{name}", f"{name} doit être un tuple d'au plus {count} valeurs",
                )
            for value in values:
                check_text(f"analysis {name}", value, limit, single_line=False)
        if not isinstance(self.triggers, tuple) or len(self.triggers) > MAX_TRIGGERS_PER_UTTERANCE:
            raise AmbientObservationError("ambient_analysis_invalid_triggers", "triggers doit être un tuple borné")
        if any(not isinstance(item, AmbientTrigger) for item in self.triggers):
            raise AmbientObservationError("ambient_analysis_invalid_triggers", "triggers ne contient que des AmbientTrigger")

    @property
    def worth_enriching(self) -> bool:
        """Y a-t-il quoi que ce soit à ranger dans l'ensemble de travail ?"""

        return not self.filler and bool(
            self.topics or self.entities or self.claims or self.questions or self.references
        )

    def to_journal(self) -> dict[str, Any]:
        """Des comptes. Jamais un sujet, jamais une affirmation, jamais le texte."""

        return {
            "filler": self.filler,
            "imperative": self.imperative,
            "topics": len(self.topics),
            "entities": len(self.entities),
            "claims": len(self.claims),
            "questions": len(self.questions),
            "references": len(self.references),
            "triggers": len(self.triggers),
        }


# --------------------------------------------------------------------------
# Analyse bon marché
# --------------------------------------------------------------------------


def is_low_value_filler(text: str) -> bool:
    """Cette énonciation ne porte-t-elle aucune information ?

    Vrai quand il n'y a pas un seul mot, ou quand tous les mots sont des
    hésitations et des acquiescements. Une phrase courte mais porteuse
    (« la marge a doublé ») n'est pas du remplissage : c'est le contenu des
    mots qui décide, pas leur nombre.
    """

    words = _WORD.findall(_normalize(text))
    if not words:
        return True
    return all(word in FILLER_WORDS for word in words)


def looks_imperative(text: str) -> bool:
    """La phrase a-t-elle la forme d'un ordre ?

    Constat, pas permission (D03). Exposé parce qu'une garde qu'on ne peut pas
    compter est une intention : la lane incrémente `imperative_utterances` et un
    test lit ce compteur pour prouver que la reconnaissance a bien eu lieu et
    que rien n'en est sorti.
    """

    normalized = _normalize(text)
    for sentence in _SENTENCE_SPLIT.split(normalized):
        words = _WORD.findall(sentence)
        if words and words[0] in _IMPERATIVE_STEMS:
            return True
    return False


def _topics(text: str) -> tuple[str, ...]:
    """Le nom qui suit un déterminant : « la **marge** », « le **rapport** ».

    Grossier et assumé. Un faux positif coûte une entrée dans un ensemble
    borné, là où un modèle coûterait un appel par énonciation — ce que D08
    interdit sur le chemin ambiant.
    """

    seen: list[str] = []
    words = _WORD.findall(_normalize(text))
    for previous, word in zip(words, words[1:]):
        if previous not in _DETERMINERS:
            continue
        if len(word) < 4 or word in FILLER_WORDS or word in _TOPIC_STOPWORDS:
            continue
        if word in seen:
            continue
        seen.append(word)
        if len(seen) >= MAX_TOPICS_PER_UTTERANCE:
            break
    return tuple(seen)


def _entities(text: str) -> tuple[str, ...]:
    """Noms propres et sigles : majuscule hors début de phrase, ou tout-capitale.

    Volontairement grossier. Un faux positif coûte une entrée bornée dans un
    ensemble borné ; un modèle coûterait un appel par énonciation, ce que D08
    interdit.
    """

    found: list[str] = []
    for sentence in _SENTENCE_SPLIT.split(" ".join(str(text).split())):
        tokens = _WORD.findall(sentence)
        for index, token in enumerate(tokens):
            proper = token[:1].isupper() and (index > 0 or token.isupper())
            if not (proper or _ACRONYM.fullmatch(token)):
                continue
            if token.casefold() in FILLER_WORDS or len(token) < 2:
                continue
            if token not in found:
                found.append(token)
            if len(found) >= MAX_ENTITIES_PER_UTTERANCE:
                return tuple(found)
    return tuple(found)


def _is_question(sentence: str) -> bool:
    normalized = _normalize(sentence)
    if not normalized:
        return False
    return normalized.endswith("?") or normalized.startswith(_INTERROGATIVES)


def _is_checkable(sentence: str) -> bool:
    normalized = _normalize(sentence)
    if len(_WORD.findall(normalized)) < MIN_CLAIM_WORDS:
        return False
    if _is_question(sentence):
        return False
    if looks_imperative(sentence):
        # Une consigne n'est pas une affirmation vérifiable. La refuser ici
        # n'est pas une garde de sécurité — D03 est tenue par les types, pas
        # par cette ligne — c'est de la justesse : « supprime la ligne 12 »
        # n'énonce aucun fait à confronter à une source.
        return False
    if _DIGIT.search(normalized):
        return True
    return any(marker in normalized for marker in _ASSERTIVE_MARKERS)


def _references(text: str) -> tuple[str, ...]:
    found: list[str] = []
    for match in _URL.findall(text):
        if match not in found:
            found.append(match)
    for sentence in _SENTENCE_SPLIT.split(" ".join(str(text).split())):
        if any(noun in _normalize(sentence) for noun in _REFERENCE_NOUNS):
            trimmed = sentence.strip()[:MAX_TRIGGER_TEXT_CHARS]
            if trimmed and trimmed not in found:
                found.append(trimmed)
    return tuple(found[:MAX_TRIGGERS_PER_UTTERANCE])


def analyse_ambient_text(utterance_id: str, text: str) -> AmbientAnalysis:
    """Analyse bon marché d'une énonciation. Aucun modèle, aucun réseau.

    L'ordre est volontaire : le remplissage sort d'abord, puis les phrases sont
    classées une à une. `imperative` est calculé dans tous les cas — y compris
    sur du remplissage — parce que c'est un compteur de garde, pas une branche.

    **Rien de ce qui sort d'ici n'autorise quoi que ce soit.** Une phrase à
    l'impératif produit exactement ce que produirait la même phrase à
    l'indicatif : au mieux une affirmation à vérifier ou une référence à
    retrouver, c'est-à-dire de l'enquête (D03).
    """

    imperative = looks_imperative(text)
    if is_low_value_filler(text):
        return AmbientAnalysis(utterance_id=utterance_id, filler=True, imperative=imperative)

    normalized_sentences = [
        sentence.strip() for sentence in _SENTENCE_SPLIT.split(" ".join(str(text).split())) if sentence.strip()
    ]
    claims: list[str] = []
    questions: list[str] = []
    for sentence in normalized_sentences:
        clipped = sentence[:MAX_CLAIM_CHARS]
        if _is_question(sentence):
            if clipped[:MAX_QUESTION_CHARS] not in questions and len(questions) < MAX_TRIGGERS_PER_UTTERANCE:
                questions.append(clipped[:MAX_QUESTION_CHARS])
        elif _is_checkable(sentence):
            if clipped not in claims and len(claims) < MAX_TRIGGERS_PER_UTTERANCE:
                claims.append(clipped)

    references = _references(text)
    topics = _topics(text)
    entities = _entities(text)

    triggers: list[AmbientTrigger] = []

    def _add(kind: AmbientTriggerKind, value: str, confidence: float) -> None:
        if len(triggers) >= MAX_TRIGGERS_PER_UTTERANCE:
            return
        triggers.append(
            AmbientTrigger(
                kind=kind, utterance_id=utterance_id,
                text=value[:MAX_TRIGGER_TEXT_CHARS], confidence=confidence,
            )
        )

    # L'ordre dit la priorité d'enquête : une affirmation chiffrée se vérifie,
    # une référence se retrouve, une question reste ouverte, un sujet se suit.
    for claim in claims:
        _add(AmbientTriggerKind.CHECKABLE_CLAIM, claim, 0.6)
    for reference in references:
        _add(AmbientTriggerKind.EXTERNAL_REFERENCE, reference, 0.5)
    for question in questions:
        _add(AmbientTriggerKind.OPEN_QUESTION, question, 0.5)
    for topic in topics:
        _add(AmbientTriggerKind.NEW_TOPIC, topic, 0.3)

    return AmbientAnalysis(
        utterance_id=utterance_id,
        filler=False,
        imperative=imperative,
        topics=topics,
        entities=entities,
        claims=tuple(claims),
        questions=tuple(questions),
        references=references,
        triggers=tuple(triggers),
    )


def utc_now() -> datetime:
    """Horloge murale du domaine, même forme que `jarvis.domain.v2.utc_now`."""

    return datetime.now(timezone.utc)


__all__ = [
    "MAX_AMBIENT_TEXT_CHARS",
    "MAX_ENTITIES_PER_UTTERANCE",
    "MAX_TOPICS_PER_UTTERANCE",
    "MAX_TRIGGERS_PER_UTTERANCE",
    "MAX_TRIGGER_TEXT_CHARS",
    "MIN_CLAIM_WORDS",
    "FILLER_WORDS",
    "AmbientAnalysis",
    "AmbientObservationError",
    "AmbientTrigger",
    "AmbientTriggerKind",
    "AmbientUtterance",
    "analyse_ambient_text",
    "clip_ambient_text",
    "is_low_value_filler",
    "looks_imperative",
    "utc_now",
]

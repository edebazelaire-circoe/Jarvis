"""Quelle situation un tour adressé constitue, et ce qu'il a le droit de dire.

Ce module est la moitié « jugement » du Slice 07. L'autre moitié — la matrice
elle-même — existe déjà en données dans `jarvis/domain/presentation_policy.py`
(Slice 01) et n'est pas redéfinie ici : on la lit, on ne la recopie pas.

Pourquoi ce module existe
-------------------------
Jusqu'ici, la seule règle « montre, ne commente pas » du dépôt était une phrase
de prompt (`jarvis/runtime/claude_local.py`, consigne d'affichage). Une phrase
de prompt tient tant que le modèle la relit : elle ne survit ni à une
reformulation, ni à un fournisseur différent, ni à une consigne concurrente.
La Décision 09 demande qu'un tour de cerveau réussi puisse ne demander *aucune*
parole ; pour que ce soit vrai, il faut que quelqu'un d'autre que le modèle ait
le droit de refuser une parole. C'est ce que ce module rend décidable, et
`jarvis/runtime/presentation_speech_gate.py` qui l'applique.

Le `BRAIN_NOT_ADDRESSED_ANSWER` (`[pas-pour-moi]`, `jarvis/domain/v2.py`) est le
précédent le plus proche : un jeton convenu que le modèle écrit pour que rien ne
soit dit. Il reste en place et n'est pas touché (Décision 14, le mode assistant
ne bouge pas), mais il n'est délibérément **pas** le modèle suivi ici : c'est
encore le modèle qui décide, et une chaîne magique mal reproduite se prononce à
voix haute. Le mode présentation décide dans le runtime.

Le plafond de `VISUAL_COMMAND`
------------------------------
`PRESENTATION_POLICY[VISUAL_COMMAND].voice_allowed` est **faux**, et c'est un
plafond, pas un défaut : sous cette situation, aucune demande ne débloque la
parole. La conséquence, portée depuis le Slice 01, est que le classement est
l'endroit où se joue « montre-moi le bilan **et dis-moi le total** » : une marque
de demande de parole l'emporte sur une marque d'affichage, sinon la moitié
parlée de la phrase serait perdue sans recours.

Le biais du classement est donc explicite : **le silence exige une preuve
positive**. Un tour adressé qu'on ne sait pas lire n'est pas mis au silence, il
est traité comme une question — parce qu'un tour muet par défaut d'analyse est
une panne muette, et que ce dépôt en a déjà payé une (voir
`SPEECH_ERROR_WITHHELD` dans `jarvis/runtime/speech_scheduler.py`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from jarvis.domain.presentation_policy import (
    UNADDRESSED_SAFETY_KINDS,
    PresentationSituation,
    may_speak,
)
from jarvis.domain.reflex_policy import normalized_tokens
from jarvis.domain.v2 import SpeechKind

#: Bornes de lecture. Le texte n'est jamais conservé par ce module ni par ses
#: appelants : seule la situation qu'il produit l'est.
MAX_CLASSIFIED_TEXT = 4096

#: Marques d'une demande explicite de parole. Elles sont cherchées **avant**
#: les marques d'affichage : voir le plafond de `VISUAL_COMMAND` ci-dessus.
#: Forme normalisée (minuscules, accents retirés, ponctuation devenue espace),
#: entourée d'espaces à la recherche pour ne pas accrocher un préfixe de mot.
SPEAK_REQUEST_MARKERS: tuple[str, ...] = (
    "dis moi", "dis nous", "dis le", "dis la", "dis les", "dis donc moi",
    "redis", "parle moi", "parle nous", "raconte", "explique", "resume moi",
    "resume nous", "lis moi", "lis nous", "lis le", "lis la", "a voix haute",
    "a l oral", "oralement", "commente", "annonce moi", "annonce nous",
    "reponds moi", "reponds nous", "detaille moi", "donne moi le detail",
)

#: Mots qui ouvrent une question en français. Cherchés **en tête** de phrase
#: seulement : « ou » et « quoi » sont aussi des mots ordinaires, et les
#: accrocher partout ferait d'« affiche le bilan ou le graphique » une question.
#: Un point d'interrogation dans le texte brut compte, lui, où qu'il soit.
QUESTION_OPENERS: tuple[str, ...] = (
    "pourquoi", "comment", "combien", "quel", "quelle", "quels", "quelles",
    "quand", "qui", "quoi", "ou", "lequel", "laquelle", "lesquels",
    "est ce que", "est ce qu", "qu est ce", "y a t il", "peux tu me dire",
    "sais tu",
)

#: Verbes de composition de l'écran. Volontairement restreint à ce qui **est**
#: de l'affichage : la scène (`BRAIN_DISPLAY_PROMPT`) parle d'ouvrir, masquer,
#: épingler, archiver, ranger. `supprime` / `efface` en sont absents exprès —
#: ils désignent aussi bien un fichier qu'un objet de scène, et mettre au
#: silence la confirmation d'une suppression de fichier serait le contraire de
#: ce que la Décision 09 demande.
#: Jetons qui nient la marque qui les suit, et fenetre de recherche en amont.
#: Trois jetons couvrent « ne me commente pas » sans aller chercher une
#: negation d'une autre proposition.
NEGATORS: frozenset[str] = frozenset({"ne", "n", "sans", "pas", "jamais", "surtout", "inutile"})
NEGATION_WINDOW = 3

VISUAL_COMMAND_VERBS: frozenset[str] = frozenset({
    "montre", "montres", "montrer", "affiche", "affiches", "afficher",
    "ouvre", "ouvres", "ouvrir", "ferme", "fermes", "fermer",
    "masque", "masques", "masquer", "cache", "caches", "cacher",
    "epingle", "epingles", "desepingle", "desepingles",
    "deplace", "deplaces", "deplacer", "agrandis", "agrandir", "reduis",
    "archive", "archives", "archiver", "range", "ranges", "ranger",
    "prepare", "prepares", "preparer", "zoome", "zoomer", "selectionne",
    "trace", "dessine", "affichage", "reaffiche", "reaffiches",
})

@dataclass(frozen=True, slots=True)
class PresentationSpeechVerdict:
    """Ce que la porte a décidé, et pourquoi. Sans aucun texte de transcription."""

    admitted: bool
    #: Situation du tour telle qu'elle a été classée. `None` quand la parole
    #: n'appartient à aucun tour adressé connu (relais spontané, notification).
    situation: PresentationSituation | None
    reason: str

    def to_payload(self) -> dict[str, object]:
        """Métadonnée de trace. Non-contenu par construction."""

        return {"admitted": self.admitted,
                "situation": self.situation.value if self.situation else None,
                "reason": self.reason}


def _negated(tokens: list[str], index: int) -> bool:
    """La marque trouvee a `index` est-elle sous une negation ?

    Fenetre de trois jetons en amont. « montre le bilan, ne commente pas »
    demandait la parole **parce que** l'utilisateur la refusait : le marqueur
    `commente` etait lu sans son « ne ». C'est le seul cas ou la cecite a la
    negation inversait l'intention au lieu de simplement la manquer.
    """

    return any(token in NEGATORS for token in tokens[max(0, index - NEGATION_WINDOW):index])


def _speak_request(tokens: list[str]) -> str | None:
    """Marque de demande explicite de parole, negations ecartees."""

    for marker in SPEAK_REQUEST_MARKERS:
        words = marker.split(" ")
        for index in range(len(tokens) - len(words) + 1):
            if tokens[index:index + len(words)] == words and not _negated(tokens, index):
                return marker.replace(" ", "_")
    return None


def classify_addressed_situation(text: object) -> tuple[PresentationSituation, str]:
    """Situation d'un tour **adresse**, et la marque qui l'a decidee.

    Ne rend jamais `AMBIENT_OBSERVATION` : un tour ambiant n'est pas classe, il
    est refuse une couche plus bas (`BrainTurnInput` refuse
    `AddressingDecision.AMBIENT`) et n'atteint donc jamais ce classement. Le
    vocabulaire ambiant reste celui de la matrice, pour que
    `admit_presentation_speech` puisse etre interroge dessus.

    L'ordre est le contrat, pas un detail d'implementation :

    1. une demande explicite de parole, non niee, l'emporte sur tout le reste ;
    2. puis un mot interrogatif **en tete** de phrase ;
    3. puis un verbe d'affichage ;
    4. puis un point d'interrogation seul ;
    5. sinon, faute de preuve de commande visuelle, on repond.

    **Le point d'interrogation passe apres le verbe d'affichage** (etape 4 et
    non 2). « Tu peux montrer le bilan ? » est du francais ordinaire pour une
    commande d'affichage, et la transcription temps reel ponctue l'intonation
    interrogative : le lire comme une question rendait bavarde la facon la plus
    naturelle de demander un affichage, c'est-a-dire exactement le remplissage
    que la Decision 09 retire. Le mot interrogatif en tete, lui, reste
    prioritaire : « pourquoi tu as affiche le Q3 » est une vraie question qui
    parle d'un affichage, et la taire serait une panne muette.
    """

    raw = text if isinstance(text, str) else ""
    raw = raw[:MAX_CLASSIFIED_TEXT]
    tokens = normalized_tokens(raw)
    phrase = " ".join(tokens)
    if (marker := _speak_request(tokens)) is not None:
        return PresentationSituation.EXPLICIT_SPEAK_REQUEST, f"speak_request:{marker}"
    for opener in QUESTION_OPENERS:
        if phrase == opener or phrase.startswith(f"{opener} "):
            return PresentationSituation.KNOWLEDGE_QUESTION, f"question_opener:{opener.replace(' ', '_')}"
    for token in tokens:
        if token in VISUAL_COMMAND_VERBS:
            return PresentationSituation.VISUAL_COMMAND, f"visual_verb:{token}"
    if "?" in raw:
        return PresentationSituation.KNOWLEDGE_QUESTION, "question_mark"
    # Aucune preuve de commande visuelle. Le silence en exige une : un tour
    # adresse qu'on ne sait pas lire est traite comme une question, jamais tu.
    return PresentationSituation.KNOWLEDGE_QUESTION, "no_visual_command_evidence"


def admit_presentation_speech(*, situation: PresentationSituation | None,
                              kind: SpeechKind) -> PresentationSpeechVerdict:
    """La parole de cette nature est-elle admise dans ce tour de présentation ?

    Un seul appel, une seule source : `may_speak`. Le plafond et ses exceptions
    de sûreté sont tous deux de la donnée de la matrice, donc il n'y a plus de
    couche au-dessus qui pourrait dire autre chose qu'elle.

    `situation=None` désigne une parole qui ne se rattache à **aucun tour
    adressé connu** : un relais spontané de fin de sous-agent, une
    notification. La matrice pose `voice_allowed ⇒ requires_explicit_address`,
    donc sans adressage, pas de parole — sauf ce que `UNADDRESSED_SAFETY_KINDS`
    nomme, pour la raison qui y est écrite.
    """

    if not isinstance(kind, SpeechKind):
        raise TypeError("admit_presentation_speech requires a typed SpeechKind")
    if situation is None:
        if kind in UNADDRESSED_SAFETY_KINDS:
            return PresentationSpeechVerdict(True, None, "unaddressed_safety_kind")
        return PresentationSpeechVerdict(False, None, "no_addressed_turn")
    if may_speak(situation, kind):
        return PresentationSpeechVerdict(True, situation, "policy_allows")
    return PresentationSpeechVerdict(False, situation, "policy_forbids")

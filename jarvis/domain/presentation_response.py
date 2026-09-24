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
    PresentationSituation,
    may_speak,
    policy_for,
)
from jarvis.domain.reflex_policy import normalized_phrase
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

#: Natures de parole que le mode présentation ne peut pas taire sans créer le
#: défaut que cette Slice existe pour interdire.
#:
#: - `ERROR` : une panne muette est un défaut, pas de la discrétion. Le
#:   16/09/2026 une parole d'erreur est restée en file et personne n'a rien
#:   entendu ; `SPEECH_ERROR_WITHHELD` a été écrit pour cela.
#: - `QUESTION` : c'est la réparation d'audition et la clarification requise.
#:   Un tour où JARVIS n'a pas compris quel « bilan » montrer et qui ne peut pas
#:   le demander meurt en silence — et l'utilisateur ne sait même pas qu'il doit
#:   redemander.
#:
#: Une nature ne **déplace** pas la situation vers une ligne plus permissive
#: sans condition : `judged_situation` refuse de promouvoir une situation qui
#: ne naît pas d'un adressage explicite (Décisions 03 et 11).
SAFETY_SITUATIONS: Mapping[SpeechKind, PresentationSituation] = {
    SpeechKind.ERROR: PresentationSituation.COMMAND_ERROR,
    SpeechKind.QUESTION: PresentationSituation.KNOWLEDGE_QUESTION,
}


@dataclass(frozen=True, slots=True)
class PresentationSpeechVerdict:
    """Ce que la porte a décidé, et pourquoi. Sans aucun texte de transcription."""

    admitted: bool
    #: Situation du tour telle qu'elle a été classée. `None` quand la parole
    #: n'appartient à aucun tour adressé connu (relais spontané, notification).
    situation: PresentationSituation | None
    #: Ligne de la matrice réellement consultée après `judged_situation`.
    judged_as: PresentationSituation | None
    reason: str

    def to_payload(self) -> dict[str, object]:
        """Métadonnée de trace. Non-contenu par construction."""

        return {"admitted": self.admitted,
                "situation": self.situation.value if self.situation else None,
                "judged_as": self.judged_as.value if self.judged_as else None,
                "reason": self.reason}


def classify_addressed_situation(text: object) -> tuple[PresentationSituation, str]:
    """Situation d'un tour **adressé**, et la marque qui l'a décidée.

    Ne rend jamais `AMBIENT_OBSERVATION` : un tour ambiant n'est pas classé, il
    est refusé une couche plus bas (`BrainTurnInput` refuse `AddressingDecision.
    AMBIENT`) et n'atteint donc jamais ce classement. Le vocabulaire ambiant
    reste celui de la matrice, pour que `admit_presentation_speech` puisse être
    interrogé dessus.

    L'ordre est le contrat, pas un détail d'implémentation :

    1. une demande explicite de parole l'emporte sur tout le reste ;
    2. puis une question ;
    3. puis une commande d'affichage ;
    4. sinon, faute de preuve de commande visuelle, on répond.
    """

    raw = text if isinstance(text, str) else ""
    raw = raw[:MAX_CLASSIFIED_TEXT]
    phrase = normalized_phrase(raw)
    padded = f" {phrase} "
    for marker in SPEAK_REQUEST_MARKERS:
        if f" {marker} " in padded:
            return PresentationSituation.EXPLICIT_SPEAK_REQUEST, f"speak_request:{marker.replace(' ', '_')}"
    if "?" in raw:
        return PresentationSituation.KNOWLEDGE_QUESTION, "question_mark"
    for opener in QUESTION_OPENERS:
        if phrase == opener or phrase.startswith(f"{opener} "):
            return PresentationSituation.KNOWLEDGE_QUESTION, f"question_opener:{opener.replace(' ', '_')}"
    for token in phrase.split(" "):
        if token in VISUAL_COMMAND_VERBS:
            return PresentationSituation.VISUAL_COMMAND, f"visual_verb:{token}"
    # Aucune preuve de commande visuelle. Le silence en exige une : un tour
    # adressé qu'on ne sait pas lire est traité comme une question, jamais tu.
    return PresentationSituation.KNOWLEDGE_QUESTION, "no_visual_command_evidence"


def judged_situation(situation: PresentationSituation, kind: SpeechKind) -> PresentationSituation:
    """Ligne de la matrice à consulter pour cette nature de parole.

    Une erreur et une question de clarification sont jugées sur leur propre
    ligne, parce que les taire crée une panne muette (voir
    `SAFETY_SITUATIONS`). C'est exactement le chemin déjà validé au Slice 01 :
    une commande qui échoue devient `COMMAND_ERROR`, elle n'est pas une
    `VISUAL_COMMAND` muette.

    **Une situation qui ne naît pas d'un adressage explicite n'est jamais
    promue.** `AMBIENT_OBSERVATION` et `FACT_CHECK_ATTENTION` sont les deux
    lignes dans ce cas ; les promouvoir donnerait la parole à ce que les
    Décisions 03 et 11 interdisent, et la condition est lue dans la matrice
    (`requires_explicit_address`) plutôt que recopiée en liste de noms, pour
    qu'une ligne ajoutée plus tard soit couverte sans qu'on y pense.
    """

    if not policy_for(situation).requires_explicit_address:
        return situation
    return SAFETY_SITUATIONS.get(kind, situation)


def admit_presentation_speech(*, situation: PresentationSituation | None,
                              kind: SpeechKind) -> PresentationSpeechVerdict:
    """La parole de cette nature est-elle admise dans ce tour de présentation ?

    `situation=None` désigne une parole qui ne se rattache à aucun tour adressé
    connu : un relais spontané de fin de sous-agent, une notification. La
    matrice pose `voice_allowed ⇒ requires_explicit_address` : sans adressage,
    pas de parole. La seule exception est `ERROR`, pour la raison écrite dans
    `SAFETY_SITUATIONS` — ce qui est cassé s'entend, même pendant une
    présentation.
    """

    if not isinstance(kind, SpeechKind):
        raise TypeError("admit_presentation_speech requires a typed SpeechKind")
    if situation is None:
        admitted = kind is SpeechKind.ERROR
        return PresentationSpeechVerdict(
            admitted, None, PresentationSituation.COMMAND_ERROR if admitted else None,
            "unaddressed_error" if admitted else "no_addressed_turn")
    judged = judged_situation(situation, kind)
    if may_speak(judged, kind):
        return PresentationSpeechVerdict(True, situation, judged, "policy_allows")
    return PresentationSpeechVerdict(False, situation, judged, "policy_forbids")

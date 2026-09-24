"""La porte qui rend le silence possible, normal, et constatable.

C'est ici que « montre, ne commente pas » cesse d'être une phrase de prompt.
L'ordonnanceur de parole (`jarvis/runtime/speech_scheduler.py`) est le seul
propriétaire de ce qui se dit ; cette porte est ce qu'il consulte avant de
mettre une parole en file, et avant de laisser partir un préambule de surface.

Ce qu'elle décide elle-même, et ce qu'elle ne fait que lire. La matrice
(`jarvis/domain/presentation_policy.py`) décide **ce qui se dit** : la porte lui
pose la question et applique la réponse, sans la nuancer. Deux règles, en
revanche, sont à elle et vivent ici parce qu'elles ne sont pas des lignes de
matrice :

- `allows_preamble()` — aucun préambule de surface en présentation. Le
  préambule n'est la parole d'aucune situation : c'est un tour de la surface,
  sans contenu par construction, donc la matrice n'a rien à en dire ;
- l'absence de tour classé (`admit` avec une corrélation inconnue) retombe sur
  `UNADDRESSED_SAFETY_KINDS`, qui est nommé dans le domaine mais appliqué ici.

Trois faits qu'elle tient, et rien d'autre :

- la **situation** de chaque tour adressé, classée une fois à la soumission du
  tour et jamais recalculée (le texte, lui, n'est pas conservé) ;
- le **compte** de ce qui a été dit et de ce qui a été retenu, par tour ;
- le **solde** du tour : un tour terminé sans une parole est une réussite, et
  il laisse une ligne qui le dit.

Ce dernier point est le point. Un tour qui se termine en silence *par
politique* et un tour qui se termine en silence *parce que quelque chose est
mort* sont indiscernables tant que personne ne l'écrit. La Slice 04 a appris
cette leçon au prix d'une invariante inobservable : ce qu'on ne peut pas
constater dérive. Donc `voice.presentation.turn_silent` est émise, au niveau
`info`, avec le compte des paroles retenues — et `outcome()` rend la même chose
en lecture, pour qu'un test puisse affirmer « ce tour a réussi sans parler »
sans lire un journal.

Hors mode présentation, cette porte est inerte : elle n'enregistre rien,
n'accumule rien et admet tout (Décision 14, le mode assistant ne bouge pas).
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable

from jarvis.domain.interaction_mode import InteractionMode
from jarvis.domain.presentation_policy import PresentationSituation
from jarvis.domain.presentation_response import (
    PresentationSpeechVerdict,
    admit_presentation_speech,
    classify_addressed_situation,
)
from jarvis.domain.v2 import SpeechKind

#: Une parole du cerveau que le mode présentation n'a pas laissé passer.
#: Métadonnée seulement : nature, situation, motif. Jamais le texte — la
#: fuite `voice.transcript_dropped` (`Issues/002`) est un défaut connu du
#: dépôt, pas un exemple à suivre.
#:
#: Nommée sous `voice.presentation.` comme ses trois soeurs, et **pas** sous
#: `voice.speech.` : `voice.speech.presentation_decided` existe déjà et y
#: désigne la *présentation* d'une parole, c'est-à-dire sa livraison. Deux sens
#: de « presentation » sur le même préfixe, dont l'un est consommé par le
#: testlab, auraient fini par être lus l'un pour l'autre.
SPEECH_WITHHELD = "voice.presentation.speech_withheld"
#: Solde d'un tour de présentation terminé sans une parole. `info` : c'est une
#: réussite, pas un incident.
TURN_SILENT = "voice.presentation.turn_silent"
#: Motif rendu à l'ordonnanceur quand un préambule de surface est refusé.
NO_FILLER_REASON = "presentation_no_filler"
#: Le tour est classé une fois, à sa soumission : la trace le dit, pour que
#: « pourquoi JARVIS s'est tu » se lise sans rejouer la séance.
TURN_CLASSIFIED = "voice.presentation.turn_classified"
#: Natures retenues gardées par tour. Au-delà, le compte continue mais la
#: liste ne grossit plus : une trace bornée reste une trace.
MAX_WITHHELD_MEMORY = 64
#: Le classement d'un tour a échoué. Le tour n'est pas perdu : il retombe sur
#: la situation qui parle, et la ligne dit qu'il y a eu repli.
CLASSIFICATION_FAILED = "voice.presentation.classification_failed"


@dataclass(slots=True)
class PresentationTurnOutcome:
    """Ce qu'un tour de présentation a manifesté. Lecture seule au dehors."""

    situation: PresentationSituation
    #: Marque de classement (`speak_request:dis_moi`, `visual_verb:montre`…),
    #: gardée pour que la trace dise *pourquoi* ce tour a été classé ainsi.
    evidence: str
    #: Paroles que la porte a laissées entrer en file. Ce n'est pas « ce que
    #: l'utilisateur a entendu » : l'ordonnanceur peut encore périmer ou
    #: remplacer une parole admise, et il le dit sur ses propres canaux.
    admitted: int = 0
    withheld: tuple[SpeechKind, ...] = ()
    settled: bool = False

    @property
    def silent(self) -> bool:
        return self.admitted == 0

    @property
    def silent_reason(self) -> str | None:
        """`None` si le tour a parlé. Sinon, laquelle des deux silences."""

        if not self.silent:
            return None
        return "silent_by_policy" if self.withheld else "silent_no_speech"

    def to_payload(self) -> dict[str, object]:
        return {"situation": self.situation.value, "evidence": self.evidence,
                "admitted": self.admitted, "withheld": [kind.value for kind in self.withheld],
                "withheld_count": len(self.withheld), "silent": self.silent,
                "silent_reason": self.silent_reason}


@dataclass(slots=True)
class PresentationSpeechGate:
    """Contrat d'exécution du mode présentation, côté parole.

    `mode` est relu à chaque décision : le mode change en cours de séance sans
    redémarrer Voice (Décision D15), donc le mémoriser ici recréerait
    exactement l'état périmé que la Slice 02 a dû réparer.
    """

    mode: Callable[[], InteractionMode]
    trace: Callable[..., None] | None = None
    #: Classement d'un tour adressé. Champ plutôt qu'appel direct pour que la
    #: reprise sur panne ci-dessous soit atteignable par un test : une garde
    #: qu'on ne peut pas faire échouer n'est pas une garde, c'est un voeu.
    classify: Callable[[object], tuple[PresentationSituation, str]] = classify_addressed_situation
    #: Tours retenus. Borné comme les autres mémoires de l'ordonnanceur.
    max_turns: int = 128
    _turns: "OrderedDict[str, PresentationTurnOutcome]" = field(default_factory=OrderedDict, init=False)

    @property
    def active(self) -> bool:
        """Le mode qui pilote le comportement est-il PRESENTATION ?

        Sans garde : `InteractionModeObserver.mode` est une lecture d'attribut
        qui ne peut pas lever, et le composition root n'injecte rien d'autre.
        Un `try` qu'aucun test ne peut atteindre est un garde imaginaire — la
        même forme que celui supprimé autour du classement.
        """

        return self.mode() is InteractionMode.PRESENTATION

    # -- tours ---------------------------------------------------------------

    def note_addressed_turn(self, text: object, *, correlation_id: object,
                            situation: PresentationSituation | None = None) -> PresentationSituation | None:
        """Classer le tour adressé qui vient d'être soumis au cerveau.

        Rend la situation retenue, ou `None` si rien n'a été retenu (hors mode
        présentation, ou corrélation inutilisable). Le texte n'est pas conservé.

        `situation` est la Slice 11 : quand le tour adressé (Slice 10) a déjà
        classé la phrase, il passe sa décision plutôt que de laisser cette
        porte reclasser. `classify` est pure et déterministe, donc reclasser ne
        serait pas *faux* — mais un appel et une vérité valent mieux que deux
        appels qui tombent d'accord par chance, et le jour où l'un des deux
        évoluerait, l'écran et la parole ne se contrediraient pas en silence.
        """

        key = _bounded_id(correlation_id)
        if key is None or not self.active:
            return None
        if isinstance(situation, PresentationSituation):
            return self._retain(key, situation, "addressed_turn")
        try:
            situation, evidence = self.classify(text)
        except Exception as exc:  # noqa: BLE001 - un classement en panne ne fait pas taire JARVIS
            # Le repli est la **parole**, jamais le silence : un tour adressé
            # qu'on n'a pas su lire doit se comporter comme un tour illisible,
            # pas comme un tour mis au silence. Silencer sur panne de classement
            # transformerait un défaut d'analyse en JARVIS muet, sans que
            # personne puisse dire pourquoi.
            situation, evidence = PresentationSituation.KNOWLEDGE_QUESTION, "classification_failed"
            self._emit(CLASSIFICATION_FAILED, "Tour de présentation non classé : repli sur la parole",
                       level="warning",
                       data={"correlation_id": key, "code": "presentation_turn_classification_failed",
                             "exception_type": type(exc).__name__, "situation": situation.value})
        return self._retain(key, situation, evidence)

    def _retain(self, key: str, situation: PresentationSituation, evidence: str) -> PresentationSituation:
        """Ranger la situation d'un tour, d'où qu'elle vienne. Un seul chemin.

        Extrait pour que la décision passée par la Slice 10 et celle classée
        ici traversent **exactement** la même mécanique : même borne, même
        clôture des tours précédents, même ligne de trace. Deux chemins
        d'enregistrement auraient fini par diverger sur l'un des trois.
        """

        outcome = PresentationTurnOutcome(situation=situation, evidence=evidence)
        self._turns[key] = outcome
        self._turns.move_to_end(key)
        while len(self._turns) > self.max_turns:
            self._turns.popitem(last=False)
        # L'arrivée d'un tour clôt les précédents : plus rien ne leur viendra.
        self.settle_all(keep=key)
        self._emit(TURN_CLASSIFIED,
                   f"Tour de présentation classé : {situation.value}",
                   data={"correlation_id": key, "situation": situation.value,
                         "evidence": evidence})
        return situation

    def outcome(self, correlation_id: object) -> PresentationTurnOutcome | None:
        """Ce qu'on sait de ce tour. Lecture d'observation, pas de décision."""

        key = _bounded_id(correlation_id)
        return None if key is None else self._turns.get(key)

    # -- parole --------------------------------------------------------------

    def admit(self, *, correlation_id: object, kind: SpeechKind,
              fields: dict[str, object] | None = None) -> PresentationSpeechVerdict:
        """Cette parole peut-elle entrer en file ?

        Hors mode présentation, tout passe, sans mémoire et sans trace : c'est
        la frontière de non-régression (Décision 14).
        """

        if not self.active:
            return PresentationSpeechVerdict(True, None, "mode_not_presentation")
        key = _bounded_id(correlation_id)
        outcome = self._turns.get(key) if key is not None else None
        verdict = admit_presentation_speech(situation=outcome.situation if outcome else None, kind=kind)
        if verdict.admitted:
            if outcome is not None:
                outcome.admitted += 1
            return verdict
        if outcome is not None and len(outcome.withheld) < MAX_WITHHELD_MEMORY:
            outcome.withheld = outcome.withheld + (kind,)
        self._emit(SPEECH_WITHHELD, "Parole retenue par la politique du mode présentation",
                   data={**(fields or {}), **verdict.to_payload(), "correlation_id": key,
                         "code": "presentation_speech_withheld"})
        return verdict

    def allows_preamble(self) -> bool:
        """Un préambule de surface est-il encore admissible ?

        Non, jamais, en mode présentation. Le préambule est par construction
        sans contenu — sa propre consigne lui interdit de donner un résultat,
        d'annoncer une progression ou de poser une question
        (`REFLEX_INSTRUCTION`, `jarvis/adapters/openai_realtime.py`). C'est
        exactement la parole qui n'apporte rien que la Décision 10 écarte.

        Ce refus ne touche que `ReflexAction.PREAMBLE`. `WAIT` et `SPEAK`
        gardent leur sens, et la réparation d'audition comme la clarification
        requise ne passent pas par là : elles arrivent en
        `SpeechKind.QUESTION`, que la matrice admet sur toutes les lignes
        adressées (`safety_speech_kinds`).
        """

        return not self.active

    def settle_all(self, *, keep: str | None = None) -> tuple[PresentationTurnOutcome, ...]:
        """Solder les tours terminés, sauf celui que `keep` désigne.

        **Pourquoi pas à la fin du travail du tour.** Le backend publie
        `COMPLETED` *avant* la parole du tour
        (`ControlCenterBrainBackend._settle_success`), donc solder sur
        `brain.work.completed` daterait le solde d'avant la seule chose qu'il
        compte. Un tour est donc soldé quand il est certain que plus rien ne
        viendra : à l'arrivée du tour suivant, et à l'arrêt de l'ordonnanceur.
        Le solde porte alors le compte définitif, au prix d'un décalage d'un
        tour sur la ligne de journal — la lecture `outcome()`, elle, est
        immédiate.

        Un tour qui a parlé ne laisse rien : c'est le cas ordinaire, déjà tracé
        par la file de parole. Un tour muet laisse une ligne, parce que c'est
        précisément celui qu'on ne peut pas distinguer d'une panne sans elle.
        """

        settled: list[PresentationTurnOutcome] = []
        for key, outcome in self._turns.items():
            if key == keep or outcome.settled:
                continue
            outcome.settled = True
            settled.append(outcome)
            if outcome.silent:
                self._emit(TURN_SILENT, "Tour de présentation terminé sans parole",
                           data={"correlation_id": key, **outcome.to_payload(),
                                 "code": "presentation_turn_silent"})
        return tuple(settled)

    # -- trace ---------------------------------------------------------------

    def _emit(self, kind: str, message: str, *, level: str = "info",
              data: dict[str, object] | None = None) -> None:
        if self.trace is None:
            return
        try:
            self.trace(kind, message, level=level, data=data or {})
        except Exception:  # noqa: BLE001
            # Un journal indisponible n'a jamais le droit de décider de la
            # parole : la porte continue, la ligne est perdue.
            pass


def _bounded_id(value: object) -> str | None:
    """Identifiant de corrélation utilisable comme clé, ou `None`."""

    if not isinstance(value, str) or not value or len(value) > 256:
        return None
    return value

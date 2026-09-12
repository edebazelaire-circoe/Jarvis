"""Port du vérificateur de locuteur (handoff Solo Owner, tâche 02).

Frontière neutre entre la capture duplex et un moteur local d'empreinte vocale.
Aucun type de moteur ne la traverse : Eagle, sherpa-onnx, SpeechBrain ou un
moteur commercial s'y branchent chacun par un adaptateur (D12).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from jarvis.domain.speaker import OwnerStateSnapshot, SpeakerVerification, VerifierAvailability


class SpeakerVerifier(Protocol):
    """Moteur local qui dit si l'audio reçu contient le propriétaire enrôlé.

    Concurrence : toutes les méthodes sont appelées depuis **un seul** fil de
    travail dédié (`jarvis/audio/speaker_shadow.py`), jamais depuis le callback
    PortAudio ni depuis la boucle asyncio — sauf `engine`, constante lue une
    fois à la construction, avant le démarrage du fil. Un appel peut donc coûter quelques
    dizaines de millisecondes de calcul ; il ne fait jamais d'E/S réseau.

    - `process` reçoit, dans l'ordre du flux, des fenêtres contiguës de PCM
      int16 mono déjà nettoyé par l'annulation d'écho, toutes de même durée,
      et rend le verdict sur l'audio accumulé depuis le dernier `reset`.
      Pendant que JARVIS parle, les trames sans parole proche lui arrivent en
      silence numérique : l'écho résiduel n'entre jamais dans sa preuve. Le
      moteur gère lui-même sa fenêtre glissante. Il peut lever : l'appelant le
      tient alors pour en panne, sans que la voix s'arrête.
    - `reset` oublie l'audio et la preuve accumulés (nouvelle session vocale,
      ou audio sauté) ; le profil du propriétaire reste chargé.
    - `close` libère le moteur ; plus aucun appel ne suit.
    - `availability` décrit l'état du moteur avant tout appel : un moteur qui
      n'est pas `ready` n'est pas consulté. `engine` l'identifie dans la
      télémétrie (nom et version, au plus 64 caractères).
    """

    @property
    def engine(self) -> str: ...

    @property
    def availability(self) -> VerifierAvailability: ...

    def reset(self) -> None: ...

    def process(self, pcm: bytes, sample_rate: int) -> SpeakerVerification: ...

    def close(self) -> None: ...


class CandidateAwareVerifier(Protocol):
    """Capacité optionnelle d'un `SpeakerVerifier` : savoir qu'un candidat acoustique s'est refermé (tâche 07).

    `finish_candidate(judge=...)` est appelé dans le même fil que `process`,
    quand la parole proche soutenue qui formait le candidat s'est tue
    (`OwnerStateMachine`, 600 ms). Deux effets :

    - `judge=True` (aucun verdict rendu dans ce candidat) : le moteur peut
      juger **une fois** la parole de ce candidat, trop brève pour sa fenêtre
      de preuve, sous une règle plus stricte qu'il porte lui-même (réponse
      brève : « oui, vas-y », « stop »). Il rend `ok` avec son verdict, ou
      `insufficient_audio` s'il n'a pas de quoi juger ;
    - toujours : la preuve accumulée est oubliée. Le candidat suivant est
      jugé sur de l'audio neuf, jamais sur la voix du précédent.

    Un moteur sans cette capacité garde le comportement d'avant : pas de
    verdict bref, preuve vidée par son seul trou de silence.
    """

    def finish_candidate(self, *, judge: bool = True) -> SpeakerVerification: ...


def supports_candidate_verdict(verifier: object) -> bool:
    """Le vérificateur sait-il qu'un candidat se referme (`CandidateAwareVerifier`) ?"""

    return callable(getattr(verifier, "finish_candidate", None))


class OwnerStateSource(Protocol):
    """Où lire l'état glissant du propriétaire (tâche 04 ; consommé à partir de la tâche 05).

    - `owner_state` : dernier `OwnerStateSnapshot` publié ; lecture sûre depuis
      n'importe quel fil (boucle asyncio comprise), sans attente.
    - `add_owner_listener(listener)` : `listener(snapshot)` est appelé à chaque
      changement **dans le fil du vérificateur**, jamais dans le callback
      PortAudio. Il rend la main aussitôt — typiquement
      `loop.call_soon_threadsafe(...)` — et ne rappelle pas la source. Au plus
      un changement par fenêtre de 100 ms. Une exception retire le
      consommateur. Rend la fonction qui le désabonne.
    - `availability` : état du vérificateur derrière la source, lisible de
      n'importe quel fil. Le barge-in Solo Owner (tâche 05) n'accorde
      l'autorité au propriétaire que tant qu'il vaut `ready`.
    """

    @property
    def availability(self) -> VerifierAvailability: ...

    @property
    def owner_state(self) -> OwnerStateSnapshot: ...

    def add_owner_listener(self, listener: Callable[[OwnerStateSnapshot], None]) -> Callable[[], None]: ...

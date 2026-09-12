"""Qui a le droit de parler à JARVIS : l'autorisation de conversation.

Deux notions se croisent dans la voix et ne doivent pas se confondre :

- l'architecture vocale (`VoiceArchitecture`, `jarvis/v2_config.py`) choisit le
  chemin de code — un tour par appui ou une conversation continue ;
- le mode de conversation, décrit ici, dit **qui** peut constituer une parole
  utilisateur : toute voix captée (`open_room`, le comportement historique) ou
  le seul propriétaire enrôlé (`solo_owner`).

La vérification du locuteur est la seule autorité sur l'identité (D05) ; le
détecteur de parole proche n'est qu'un préfiltre acoustique (D03). Aucun nom de
moteur n'apparaît ici : le moteur se choisit sur banc d'essai (D12). Le verdict
d'un vérificateur (`SpeakerVerification`) vit aussi ici ; son port est
`jarvis/ports/speaker.py`. L'état glissant du propriétaire qui en découle
(`OwnerState`, `OwnerStateSnapshot`) aussi.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from jarvis.domain.errors import ConfigurationError


class ConversationMode(StrEnum):
    """Qui peut constituer un tour utilisateur."""

    #: Comportement historique : toute parole captée peut devenir un tour.
    OPEN_ROOM = "open_room"
    #: Seul le propriétaire vérifié parle à JARVIS : les autres voix ne
    #: l'interrompent pas, ne créent pas de tour et ne comptent pas comme
    #: activité utile (D10, D11).
    SOLO_OWNER = "solo_owner"


class SpeakerVerificationMode(StrEnum):
    """Ce que JARVIS fait du verdict du vérificateur de locuteur."""

    #: Le vérificateur ne tourne pas.
    OFF = "off"
    #: Il tourne et journalise, sans rien décider : le routage audio est inchangé.
    SHADOW = "shadow"
    #: Son verdict ouvre ou ferme l'entrée.
    ENFORCE = "enforce"


#: Audio gardé en mémoire le temps de confirmer l'identité, pour rejouer le
#: début de phrase une fois le propriétaire reconnu (D08). Distinct de la courte
#: pré-écoute acoustique de `jarvis/audio/duplex.py`. Point de départ des
#: mesures, pas une valeur réglée sur poste (question ouverte 3).
DEFAULT_OWNER_BUFFER_MS = 2500
#: En dessous, le tampon ne couvre plus la fenêtre de preuve d'un vérificateur :
#: le début de phrase serait perdu avant la confirmation.
MIN_OWNER_BUFFER_MS = 500
#: Au-delà, rejouer le préfixe retarderait la réponse bien plus que la
#: confirmation « de la sous-seconde à quelques secondes » admise par D07.
MAX_OWNER_BUFFER_MS = 5000


class ConversationAuthorizationError(ConfigurationError):
    """Réglage d'autorisation refusé, avec un code stable pour l'interface."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ConversationAuthorization:
    """Autorisation de conversation, cohérente par construction.

    Le défaut est le comportement d'avant ce réglage : salle ouverte, aucun
    vérificateur. Une combinaison incohérente ne peut pas être construite :
    `solo_owner` sans vérification appliquée ferait semblant de filtrer les
    autres voix, et `enforce` en salle ouverte n'aurait personne à écarter.
    """

    mode: ConversationMode = ConversationMode.OPEN_ROOM
    verification: SpeakerVerificationMode = SpeakerVerificationMode.OFF
    owner_buffer_ms: int = DEFAULT_OWNER_BUFFER_MS

    def __post_init__(self) -> None:
        if not isinstance(self.mode, ConversationMode):
            raise TypeError("mode must be a ConversationMode")
        if not isinstance(self.verification, SpeakerVerificationMode):
            raise TypeError("verification must be a SpeakerVerificationMode")
        if isinstance(self.owner_buffer_ms, bool) or not isinstance(self.owner_buffer_ms, int):
            raise TypeError("owner_buffer_ms must be an int")
        if not MIN_OWNER_BUFFER_MS <= self.owner_buffer_ms <= MAX_OWNER_BUFFER_MS:
            raise ConversationAuthorizationError(
                "owner_buffer_out_of_range",
                f"Le tampon de vérification du propriétaire (owner_buffer_ms) doit être compris entre "
                f"{MIN_OWNER_BUFFER_MS} et {MAX_OWNER_BUFFER_MS} ms, reçu {self.owner_buffer_ms}.",
            )
        if self.mode is ConversationMode.SOLO_OWNER and self.verification is not SpeakerVerificationMode.ENFORCE:
            raise ConversationAuthorizationError(
                "solo_owner_requires_enforce",
                "Le mode Solo Owner exige la vérification du locuteur en « enforce » : en "
                f"« {self.verification.value} », rien n'écarterait les autres voix et JARVIS ferait "
                "semblant de n'écouter que vous. Pour mesurer d'abord, gardez open_room avec la "
                "vérification en « shadow ».",
            )
        if self.mode is ConversationMode.OPEN_ROOM and self.verification is SpeakerVerificationMode.ENFORCE:
            raise ConversationAuthorizationError(
                "enforce_requires_solo_owner",
                "La vérification « enforce » n'a de sens qu'en mode solo_owner : en open_room toute "
                "voix est admise, il n'y a personne à écarter. Choisissez « shadow » pour observer, "
                "ou le mode solo_owner.",
            )

    @property
    def owner_enforced(self) -> bool:
        """Vrai quand seule la voix du propriétaire peut devenir un tour."""

        return self.mode is ConversationMode.SOLO_OWNER


class VerifierAvailability(StrEnum):
    """Ce que l'on sait du vérificateur de locuteur au moment de décider."""

    #: Moteur chargé et propriétaire enrôlé.
    READY = "ready"
    #: Aucun moteur de vérification disponible.
    NOT_INSTALLED = "not_installed"
    #: Moteur présent, mais aucune voix de propriétaire enrôlée.
    NO_OWNER_PROFILE = "no_owner_profile"
    #: Moteur en panne ou profil inutilisable.
    FAILED = "failed"


class VerificationStatus(StrEnum):
    """Issue d'un appel au vérificateur : code stable pour la télémétrie."""

    #: Fenêtre jugée : `owner_score` et `owner_detected` ont un sens.
    OK = "ok"
    #: Pas assez de parole dans la fenêtre pour juger (silence, bruit, début
    #: de phrase) : ni oui ni non.
    INSUFFICIENT_AUDIO = "insufficient_audio"
    #: Moteur chargé, mais aucune voix de propriétaire enrôlée.
    NO_PROFILE = "no_profile"
    #: Aucun moteur derrière le port (vérificateur nul, moteur absent).
    UNAVAILABLE = "unavailable"
    #: Le moteur a échoué sur cette fenêtre.
    ERROR = "error"


_STATUS_AVAILABILITY: dict[VerificationStatus, VerifierAvailability] = {
    VerificationStatus.OK: VerifierAvailability.READY,
    VerificationStatus.INSUFFICIENT_AUDIO: VerifierAvailability.READY,
    VerificationStatus.NO_PROFILE: VerifierAvailability.NO_OWNER_PROFILE,
    VerificationStatus.UNAVAILABLE: VerifierAvailability.NOT_INSTALLED,
    VerificationStatus.ERROR: VerifierAvailability.FAILED,
}

#: Échelle commune des scores, quel que soit le moteur : 0 = certainement pas
#: le propriétaire, 1 = certainement lui. L'adaptateur y ramène l'échelle native
#: (similarité cosinus, rapport de vraisemblance, probabilité).
OWNER_SCORE_MIN = 0.0
OWNER_SCORE_MAX = 1.0
#: Identifiants de moteur et de profil : courts, ils partent tels quels dans la
#: télémétrie.
MAX_SPEAKER_ID_CHARS = 64


def _check_identifier(name: str, value: object, *, optional: bool) -> None:
    if value is None and optional:
        return
    if not isinstance(value, str) or not value or len(value) > MAX_SPEAKER_ID_CHARS:
        raise ValueError(f"{name} must be a non-empty string of at most {MAX_SPEAKER_ID_CHARS} characters")


@dataclass(frozen=True, slots=True)
class SpeakerVerification:
    """Verdict du vérificateur sur l'audio reçu jusqu'ici.

    Sémantique du score : `owner_score` ∈ [`OWNER_SCORE_MIN`, `OWNER_SCORE_MAX`],
    plus haut = plus probablement le propriétaire enrôlé. Il n'existe que
    lorsque la fenêtre a été jugée (`status == ok`). La décision n'est pas
    « score > 0,5 » : `owner_detected` porte le seuil calibré du moteur, et
    c'est lui qu'un consommateur lit. `evidence_ms` est la durée d'audio sur
    laquelle repose le verdict.

    Rien d'autre ne sort du moteur : ni empreinte vocale, ni audio. Ce type est
    donc journalisable tel quel.
    """

    status: VerificationStatus
    engine: str
    owner_score: float | None = None
    owner_detected: bool = False
    evidence_ms: int = 0
    profile_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, VerificationStatus):
            raise TypeError("status must be a VerificationStatus")
        _check_identifier("engine", self.engine, optional=False)
        _check_identifier("profile_id", self.profile_id, optional=True)
        if isinstance(self.evidence_ms, bool) or not isinstance(self.evidence_ms, int) or self.evidence_ms < 0:
            raise ValueError("evidence_ms must be a non-negative int")
        if not isinstance(self.owner_detected, bool):
            raise TypeError("owner_detected must be a bool")
        if self.status is not VerificationStatus.OK:
            if self.owner_score is not None or self.owner_detected:
                raise ValueError("only a judged window (status ok) carries a score or a detection")
            return
        score = self.owner_score
        if isinstance(score, bool) or not isinstance(score, (int, float)) or math.isnan(score):
            raise ValueError("a judged window must carry a numeric owner_score")
        if not OWNER_SCORE_MIN <= score <= OWNER_SCORE_MAX:
            raise ValueError(f"owner_score must lie in [{OWNER_SCORE_MIN}, {OWNER_SCORE_MAX}]")

    @property
    def availability(self) -> VerifierAvailability:
        """Ce que ce verdict dit de l'état du vérificateur."""

        return _STATUS_AVAILABILITY[self.status]


_VERIFIER_REASONS: dict[VerifierAvailability, str] = {
    VerifierAvailability.NOT_INSTALLED: "aucun vérificateur de locuteur n'est disponible",
    VerifierAvailability.NO_OWNER_PROFILE: "aucune voix de propriétaire n'est enrôlée",
    VerifierAvailability.FAILED: "le vérificateur de locuteur est en panne",
}


class AuthorizationStatus(StrEnum):
    """Ce qui s'applique réellement d'une autorisation configurée."""

    #: Le réglage s'applique tel quel.
    READY = "ready"
    #: L'observation (`shadow`) est impossible ; le routage reste celui de la
    #: salle ouverte, inchangé, et la raison doit être visible.
    DEGRADED = "degraded"
    #: Solo Owner est inapplicable : il n'est pas activé, et JARVIS ne retombe
    #: pas en silence sur la salle ouverte (question ouverte 5 : refuser et
    #: expliquer).
    REFUSED = "refused"


@dataclass(frozen=True, slots=True)
class AuthorizationAssessment:
    """Verdict de `assess_authorization`, avec un code et un message en clair."""

    status: AuthorizationStatus
    authorization: ConversationAuthorization
    verifier: VerifierAvailability
    code: str = ""
    message: str = ""

    def __post_init__(self) -> None:
        if self.status is not AuthorizationStatus.READY and not (self.code and self.message):
            raise ValueError("a degraded or refused authorization must say why")


def assess_authorization(
    authorization: ConversationAuthorization, verifier: VerifierAvailability, *, continuous: bool = True
) -> AuthorizationAssessment:
    """Confronter l'autorisation configurée à l'état réel du vérificateur.

    Fonction pure : Voice l'appelle avant d'activer une session, le Control
    Center pour prévenir — la même fonction des deux côtés, pour qu'ils
    disent la même chose (tâche 07). Seul Solo Owner peut être refusé ; la
    salle ouverte reste toujours utilisable, au pire sans observation.

    `continuous` : l'architecture vocale effective est `continuous_brain`.
    Solo Owner n'existe que là — l'architecture `legacy` n'a ni capture
    duplex ni vérificateur — et c'est la première raison dite, la plus
    actionnable : même prêt, un vérificateur n'y servirait à rien.
    """

    if authorization.owner_enforced and not continuous:
        return AuthorizationAssessment(
            AuthorizationStatus.REFUSED,
            authorization,
            verifier,
            code="solo_owner_requires_continuous_brain",
            message=(
                "Mode Solo Owner refusé : l'architecture vocale « legacy » (un tour par appui) n'a ni "
                "capture duplex ni vérificateur de locuteur. Choisissez l'architecture continuous_brain, "
                "ou repassez conversation_mode sur open_room."
            ),
        )
    if authorization.verification is SpeakerVerificationMode.OFF or verifier is VerifierAvailability.READY:
        return AuthorizationAssessment(AuthorizationStatus.READY, authorization, verifier)
    reason = _VERIFIER_REASONS[verifier]
    if authorization.owner_enforced:
        return AuthorizationAssessment(
            AuthorizationStatus.REFUSED,
            authorization,
            verifier,
            code="solo_owner_unavailable",
            message=(
                f"Mode Solo Owner refusé : {reason}. JARVIS ne peut pas reconnaître votre voix, "
                "il ne fera pas semblant de filtrer les autres : Voice n'écoute pas dans ce mode. "
                "Retour arrière : conversation_mode sur open_room, puis relancez Voice."
            ),
        )
    return AuthorizationAssessment(
        AuthorizationStatus.DEGRADED,
        authorization,
        verifier,
        code="speaker_verification_unavailable",
        message=(
            f"Vérification du locuteur en observation demandée, mais {reason} : rien n'est "
            "mesuré. La conversation reste ouverte à toutes les voix, comme avant."
        ),
    )


class OwnerState(StrEnum):
    """Qui parle en ce moment, selon la vérification glissante (tâche 04).

    Un état n'existe qu'à l'intérieur d'un candidat acoustique (parole proche
    soutenue) ; il suit le **dernier** verdict jugé, sans verrou : un étranger
    puis le propriétaire, sans silence, passe de `rejected` à
    `owner_confirmed` (D06).
    """

    #: Aucun candidat acoustique : silence, bruit bref, écho seul, ou
    #: vérificateur indisponible.
    IDLE = "idle"
    #: Parole candidate, identité pas encore jugée (preuve en cours).
    CANDIDATE = "candidate"
    #: Le dernier verdict jugé reconnaît le propriétaire.
    OWNER_CONFIRMED = "owner_confirmed"
    #: Le dernier verdict jugé ne reconnaît pas le propriétaire.
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class OwnerStateSnapshot:
    """État du propriétaire publié à chaque changement (couture des tâches 05 à 07).

    Instants en millisecondes de l'horloge du flux de capture
    (`CaptureProcessor.stream_ms`, depuis le début de la session), jamais
    l'horloge murale : ils désignent des trames, ce dont le tampon de rejeu
    (tâche 06) a besoin.

    - `sequence` croît de 1 à chaque publication, sur toute la vie du
      vérificateur ; `session` croît à chaque remise à zéro de session. Un
      consommateur écarte ce qui n'est pas plus récent que ce qu'il a vu.
    - `stream_ms` : fin de la fenêtre qui a provoqué le changement.
    - `candidate_onset_ms` : première trame du candidat acoustique en cours.
    - `owner_onset_ms` : début estimé de la parole du propriétaire, pour la
      dernière confirmation ; `confirmed_ms` : instant de cette confirmation.
      Tous deux restent posés jusqu'à la fin du candidat, même si un verdict
      ultérieur rejette.
    - `owner_score`, `evidence_ms` : le verdict qui a provoqué le changement.
    - `far_end` : JARVIS parlait pendant cette fenêtre (barge-in possible).

    Métadonnées seules : ni audio, ni empreinte vocale.
    """

    sequence: int = 0
    session: int = 0
    state: OwnerState = OwnerState.IDLE
    stream_ms: int = 0
    candidate_onset_ms: int | None = None
    owner_onset_ms: int | None = None
    confirmed_ms: int | None = None
    owner_score: float | None = None
    evidence_ms: int = 0
    far_end: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.state, OwnerState):
            raise TypeError("state must be an OwnerState")
        for name in ("sequence", "session", "stream_ms", "evidence_ms"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative int")
        if self.state is OwnerState.IDLE and self.candidate_onset_ms is not None:
            raise ValueError("an idle owner state has no candidate")
        if self.state is OwnerState.OWNER_CONFIRMED and (self.confirmed_ms is None or self.owner_onset_ms is None):
            raise ValueError("a confirmed owner state carries its onset and confirmation instants")

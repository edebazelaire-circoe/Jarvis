from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import ipaddress
import math
import os

from jarvis.domain.errors import ConfigurationError
from jarvis.domain.speaker import (
    DEFAULT_OWNER_BUFFER_MS,
    ConversationAuthorization,
    ConversationAuthorizationError,
    ConversationMode,
    SpeakerVerificationMode,
)


def validate_loopback_host(host: str) -> str:
    value = host.strip()
    if not value:
        raise ConfigurationError("JARVIS_CORE_HOST cannot be empty")
    if value.lower() == "localhost":
        return value
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ConfigurationError("JARVIS_CORE_HOST must be an IP loopback address or localhost") from exc
    if not address.is_loopback:
        raise ConfigurationError("JARVIS Core must bind to loopback only")
    return value


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(raw) if raw is not None else default
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc


TURN_MODES = {"auto": True, "manual": False}

# Défauts de modèle Realtime, pas des constantes métier (Décision 18). Ils vivent
# ici, dans la couche de configuration, et jamais dans `jarvis/core` ni
# `jarvis/domain`. `OPENAI_REALTIME_MODEL` et le champ « Modèle Realtime » des
# réglages du Control Center passent devant, dans cet ordre.
DEFAULT_REALTIME_MODEL = "gpt-realtime-2.1"

# En mode continu la surface ne raisonne plus : elle transporte l'audio, accuse
# réception et restitue la parole du cerveau. La latence prime donc sur la
# capacité, et le modèle recommandé change — c'est un défaut, pas une exigence.
DEFAULT_CONTINUOUS_SURFACE_MODEL = "gpt-realtime-2.1-mini"

# The Realtime timbres offered by gpt-realtime, lowest and most level first.
REALTIME_VOICES = ("cedar", "ash", "verse", "ballad", "echo", "sage", "alloy", "marin", "coral", "shimmer")


def parse_turn_mode(value: str | None) -> bool:
    """True when the provider closes the turn on silence, False for wake-key submit."""
    normalized = (value or "auto").strip().lower() or "auto"
    if normalized not in TURN_MODES:
        raise ConfigurationError("Voice turn mode must be 'auto' or 'manual'")
    return TURN_MODES[normalized]


class VoiceArchitecture(StrEnum):
    """Bascule de déploiement entre l'ancien cycle de vie vocal et le continu.

    Elle vit ici, et non dans les réglages de pile de `voice_stack.py`, qui dit
    explicitement ne décrire que des champs « réellement transmis au
    fournisseur » : le mode d'architecture ne part chez personne, il choisit le
    chemin de code de JARVIS.

    Le Control Center l'expose tout de même comme réglage à part (`voice_arch`
    dans `control-center-settings.json`), qui passe devant `JARVIS_VOICE_ARCH`
    au démarrage de Voice. Laissé vide, il rend la main à la variable puis à
    `default_voice_arch()` : le retour arrière par le `.env` (Décision 20)
    reste donc possible tant que l'interface n'a rien imposé.

    `LEGACY` reste le défaut tant que le mode continu n'a pas passé les recettes
    poste de travail : garder le micro ouvert pendant que les haut-parleurs
    jouent est un risque acoustique réel. Il est traité par la capture duplex
    (`jarvis/audio/duplex.py`), validée en simulation seulement.

    Ce défaut n'est pas écrit en dur : il est calculé par `default_voice_arch()`
    à partir de `CONTINUOUS_BRAIN_DEFAULT_BLOCKERS`, la porte de la Décision 34.
    """

    LEGACY = "legacy"
    CONTINUOUS_BRAIN = "continuous_brain"


# Porte de déploiement **bloquante** de la Décision 34, rendue vérifiable.
#
# La Décision 34 vide le catalogue d'outils de la surface en mode continu : plus
# rien de substantiel ne s'exécute depuis la voix, tout passe par le cerveau. La
# conséquence est écrite noir sur blanc dans la décision : « le mode continu
# dépend désormais du fait que le cerveau ait un accès équivalent. Drive est déjà
# exposé à l'agent CLI par `jarvis/runtime/drive_mcp.py` ; l'accès calendrier et
# rappels n'est **pas vérifié**. » Tant que c'est vrai, faire du continu le
# défaut retirerait ces capacités à tous les utilisateurs sans les remplacer.
#
# Cette liste est donc l'interrupteur, et non un commentaire : `default_voice_arch()`
# rend `legacy` tant qu'elle n'est pas vide. La vider est un acte délibéré, qui
# demande soit de câbler l'accès manquant, soit d'acter l'écart par écrit
# (Décision 34, « ou l'écart est accepté par écrit »). Un test échoue si le défaut
# bascule alors qu'un bloqueur subsiste.
#
# L'opt-in explicite, lui, n'est pas bloqué : `JARVIS_VOICE_ARCH=continuous_brain`
# reste accepté. C'est un défaut qui est verrouillé, pas un mode.
CONTINUOUS_BRAIN_DEFAULT_BLOCKERS: tuple[str, ...] = (
    "brain_calendar_access_unverified",
    "brain_reminder_access_unverified",
)


def continuous_brain_default_blockers() -> tuple[str, ...]:
    """Ce qui interdit encore au mode continu de devenir le défaut."""

    return CONTINUOUS_BRAIN_DEFAULT_BLOCKERS


def default_voice_arch() -> VoiceArchitecture:
    """Architecture vocale retenue quand `JARVIS_VOICE_ARCH` n'est pas posé.

    Un seul endroit décide du défaut, et il consulte la porte de la Décision 34
    plutôt qu'une constante muette : le chemin de retour arrière — retirer la
    variable d'environnement — ramène donc mécaniquement à `legacy`.
    """

    if continuous_brain_default_blockers():
        return VoiceArchitecture.LEGACY
    return VoiceArchitecture.CONTINUOUS_BRAIN


def parse_voice_arch(value: str | None) -> VoiceArchitecture:
    normalized = (value or "").strip().lower() or default_voice_arch().value
    try:
        return VoiceArchitecture(normalized)
    except ValueError as exc:
        allowed = " ou ".join(f"'{item.value}'" for item in VoiceArchitecture)
        raise ConfigurationError(f"JARVIS_VOICE_ARCH must be {allowed}") from exc


def recommended_realtime_model(voice_arch: VoiceArchitecture) -> str:
    """Modèle Realtime conseillé pour une architecture, faute de choix explicite."""

    if voice_arch is VoiceArchitecture.CONTINUOUS_BRAIN:
        return DEFAULT_CONTINUOUS_SURFACE_MODEL
    return DEFAULT_REALTIME_MODEL


# Plancher d'un délai d'activité utile non nul. En dessous, une simple pause
# pour réfléchir suffirait à renvoyer la session au fond.
MIN_ACTIVE_TIMEOUT_S = 5.0


def parse_active_timeout(raw: object, *, name: str = "JARVIS_ACTIVE_TIMEOUT_S") -> float:
    """Délai d'activité utile d'une session ACTIVE, en secondes.

    `0` veut dire « jamais » : seuls la touche de réveil, le mute vocal ou une
    panne irrécupérable rendent alors la main. Toute autre valeur doit valoir
    au moins `MIN_ACTIVE_TIMEOUT_S`. Un même validateur sert l'environnement,
    le fichier de réglages et le Control Center, pour qu'ils ne divergent pas.
    """

    if isinstance(raw, bool):
        raise ConfigurationError(f"{name} must be a number")
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{name} must be a number") from exc
    if not math.isfinite(value) or value < 0 or 0 < value < MIN_ACTIVE_TIMEOUT_S:
        raise ConfigurationError(
            f"{name} must be 0 (never time out) or >= {MIN_ACTIVE_TIMEOUT_S:g}, got {raw!r}"
        )
    return value


# Autorisation de conversation (`jarvis/domain/speaker.py`) : qui peut parler à
# JARVIS, indépendamment de `voice_arch` et de la détection de fin de tour. Ces
# clés vivent dans `control-center-settings.json` seulement, sans variable
# d'environnement. Absente ou vide, chacune retombe sur le comportement
# historique ; la vérification, elle, suit alors le mode (`enforce` en
# `solo_owner`, `off` sinon).
CONVERSATION_MODE_SETTING = "conversation_mode"
SPEAKER_VERIFICATION_SETTING = "speaker_verification"
OWNER_BUFFER_MS_SETTING = "owner_buffer_ms"
CONVERSATION_AUTHORIZATION_SETTINGS = (
    CONVERSATION_MODE_SETTING,
    SPEAKER_VERIFICATION_SETTING,
    OWNER_BUFFER_MS_SETTING,
)


def _setting_text(settings: Mapping[str, object], key: str) -> str:
    raw = settings.get(key)
    return "" if raw is None else str(raw).strip().lower()


def parse_owner_buffer_ms(raw: object) -> int:
    """Durée du tampon de vérification du propriétaire, en millisecondes entières.

    Vide ou absent : le défaut. Les bornes sont celles de
    `ConversationAuthorization`, vérifiées à sa construction.
    """

    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return DEFAULT_OWNER_BUFFER_MS
    try:
        if isinstance(raw, bool):
            raise ValueError(raw)
        value = float(raw)  # type: ignore[arg-type]
        if not value.is_integer():
            raise ValueError(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ConversationAuthorizationError(
            "owner_buffer_not_an_integer",
            f"Le tampon de vérification du propriétaire (owner_buffer_ms) attend un nombre entier "
            f"de millisecondes, reçu « {raw} ».",
        ) from exc
    return int(value)


def parse_conversation_authorization(settings: Mapping[str, object]) -> ConversationAuthorization:
    """Autorisation de conversation lue dans les réglages du Control Center.

    Un fichier antérieur à ce réglage rend exactement le comportement d'avant :
    `open_room`, vérification `off`, tampon par défaut. Une valeur inconnue ou
    une combinaison incohérente lève `ConversationAuthorizationError`, avec un
    code stable et un message en clair — jamais un repli silencieux.
    """

    mode_raw = _setting_text(settings, CONVERSATION_MODE_SETTING)
    try:
        mode = ConversationMode(mode_raw or ConversationMode.OPEN_ROOM)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in ConversationMode)
        raise ConversationAuthorizationError(
            "conversation_mode_unknown",
            f"Mode de conversation inconnu : « {mode_raw} ». Valeurs acceptées : {allowed}.",
        ) from exc
    verification_raw = _setting_text(settings, SPEAKER_VERIFICATION_SETTING)
    default_verification = (
        SpeakerVerificationMode.ENFORCE if mode is ConversationMode.SOLO_OWNER else SpeakerVerificationMode.OFF
    )
    try:
        verification = SpeakerVerificationMode(verification_raw or default_verification)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in SpeakerVerificationMode)
        raise ConversationAuthorizationError(
            "speaker_verification_unknown",
            f"Mode de vérification du locuteur inconnu : « {verification_raw} ». Valeurs acceptées : {allowed}.",
        ) from exc
    return ConversationAuthorization(
        mode=mode,
        verification=verification,
        owner_buffer_ms=parse_owner_buffer_ms(settings.get(OWNER_BUFFER_MS_SETTING)),
    )


def conversation_authorization_settings(authorization: ConversationAuthorization) -> dict[str, object]:
    """Forme écrite dans les réglages, relue telle quelle par `parse_conversation_authorization`."""

    return {
        CONVERSATION_MODE_SETTING: authorization.mode.value,
        SPEAKER_VERIFICATION_SETTING: authorization.verification.value,
        OWNER_BUFFER_MS_SETTING: authorization.owner_buffer_ms,
    }


# Vérificateur de locuteur local (handoff Solo Owner, tâche 03) : où vivent le
# modèle et le profil vocal du propriétaire, et comment le verdict est rendu.
# Mêmes règles que l'autorisation : clés plates de `control-center-settings.json`,
# sans variable d'environnement ; absentes ou vides, elles retombent sur leur
# défaut. Le profil est biométrique : son chemin par défaut est sous le dossier
# runtime, entièrement ignoré par Git.
OWNER_THRESHOLD_SETTING = "owner_threshold"
OWNER_EVIDENCE_MS_SETTING = "owner_evidence_ms"
OWNER_PROFILE_PATH_SETTING = "owner_profile_path"
OWNER_SHORT_EVIDENCE_MS_SETTING = "owner_short_evidence_ms"
OWNER_SHORT_MARGIN_SETTING = "owner_short_margin"
SPEAKER_VERIFIER_SETTINGS = (
    OWNER_THRESHOLD_SETTING,
    OWNER_EVIDENCE_MS_SETTING,
    OWNER_PROFILE_PATH_SETTING,
    OWNER_SHORT_EVIDENCE_MS_SETTING,
    OWNER_SHORT_MARGIN_SETTING,
)
SPEAKER_VERIFICATION_DIRNAME = "speaker-verification"
OWNER_PROFILE_FILENAME = "owner-voice-profile.json"
#: Parole voisée sur laquelle repose un verdict : fenêtre glissante du moteur,
#: et preuve minimale avant le premier verdict. Point de départ des mesures
#: (tâche 09), pas une valeur réglée sur poste.
DEFAULT_OWNER_EVIDENCE_MS = 1500
#: En dessous, une empreinte vocale ne distingue plus deux voix de façon fiable.
MIN_OWNER_EVIDENCE_MS = 500
#: Au-delà, la confirmation dépasserait « quelques secondes » (D07).
MAX_OWNER_EVIDENCE_MS = 4000
#: Réponses brèves du propriétaire (« oui, vas-y », « non merci », « stop »),
#: tâche 07 : un candidat qui se referme avec au moins cette parole voisée,
#: mais moins que la fenêtre de preuve et sans verdict, est jugé une fois sur
#: ce qu'il contient, au seuil durci de `owner_short_margin`. La même durée
#: sert de sous-fenêtre récente pendant que le propriétaire parle, pour
#: refermer plus tôt le flux quand une autre voix enchaîne sans silence.
#: 0 désactive les deux. Points de départ des mesures (tâche 14).
DEFAULT_OWNER_SHORT_EVIDENCE_MS = 600
#: En dessous, une empreinte ne dit presque plus rien de la voix : un « oui »
#: isolé (≈ 300 ms voisées) reste perdu, c'est le compromis retenu.
MIN_OWNER_SHORT_EVIDENCE_MS = 300
#: Seuil durci d'un verdict bref = seuil + marge ; plancher de la sous-fenêtre
#: récente = seuil − marge (hystérésis : accepter est plus exigeant que
#: garder).
DEFAULT_OWNER_SHORT_MARGIN = 0.1
MAX_OWNER_SHORT_MARGIN = 0.3


@dataclass(frozen=True, slots=True)
class SpeakerVerifierSettings:
    """Réglages du vérificateur local, chemins résolus.

    `threshold` est exprimé sur l'échelle commune des scores (`owner_score`,
    [0, 1]) ; `None` laisse le seuil calibré du moteur. `short_evidence_ms`
    `None` : ni verdict de fin de candidat ni sous-fenêtre récente.
    """

    model_dir: Path
    profile_path: Path
    threshold: float | None = None
    evidence_ms: int = DEFAULT_OWNER_EVIDENCE_MS
    short_evidence_ms: int | None = DEFAULT_OWNER_SHORT_EVIDENCE_MS
    short_margin: float = DEFAULT_OWNER_SHORT_MARGIN


def _setting_raw(settings: Mapping[str, object], key: str) -> object | None:
    raw = settings.get(key)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    return raw


def _under_runtime_root(candidate: Path, runtime_root: Path, raw: object) -> Path:
    """Le chemin, s'il reste sous `runtime_root` une fois résolu ; sinon refus codé."""

    root = Path(runtime_root).expanduser()
    try:
        resolved = candidate.resolve()
        root_resolved = root.resolve()
    except OSError as exc:  # chemin impossible à résoudre (lecteur absent, boucle)
        raise ConversationAuthorizationError(
            "owner_profile_path_invalid",
            f"Le chemin du profil vocal (owner_profile_path) est inutilisable « {raw} » : {type(exc).__name__}.",
        ) from None
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ConversationAuthorizationError(
            "owner_profile_path_outside_runtime",
            f"Le chemin du profil vocal (owner_profile_path) doit rester sous le dossier runtime "
            f"({root_resolved}), qui est ignoré par Git : « {raw} » mène à {resolved}.",
        )
    return candidate


def parse_speaker_verifier_settings(settings: Mapping[str, object], *, runtime_root: Path) -> SpeakerVerifierSettings:
    """Réglages du vérificateur lus dans les réglages du Control Center.

    Un chemin de profil relatif part du dossier runtime. Une valeur invalide
    lève `ConversationAuthorizationError` avec un code stable, jamais un repli
    silencieux sur un autre seuil.
    """

    root = Path(runtime_root) / SPEAKER_VERIFICATION_DIRNAME
    threshold: float | None = None
    raw = _setting_raw(settings, OWNER_THRESHOLD_SETTING)
    if raw is not None:
        try:
            if isinstance(raw, bool):
                raise ValueError(raw)
            threshold = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            threshold = math.nan
        if not (math.isfinite(threshold) and 0.0 < threshold <= 1.0):
            raise ConversationAuthorizationError(
                "owner_threshold_invalid",
                f"Le seuil de reconnaissance du propriétaire (owner_threshold) doit être un nombre dans ]0, 1], "
                f"reçu « {raw} ».",
            )
    evidence_ms = DEFAULT_OWNER_EVIDENCE_MS
    raw = _setting_raw(settings, OWNER_EVIDENCE_MS_SETTING)
    if raw is not None:
        try:
            if isinstance(raw, bool):
                raise ValueError(raw)
            value = float(raw)  # type: ignore[arg-type]
            if not value.is_integer():
                raise ValueError(raw)
            evidence_ms = int(value)
        except (TypeError, ValueError, OverflowError):
            evidence_ms = -1
        if not MIN_OWNER_EVIDENCE_MS <= evidence_ms <= MAX_OWNER_EVIDENCE_MS:
            raise ConversationAuthorizationError(
                "owner_evidence_invalid",
                f"La fenêtre de preuve du propriétaire (owner_evidence_ms) doit être un nombre entier de "
                f"millisecondes entre {MIN_OWNER_EVIDENCE_MS} et {MAX_OWNER_EVIDENCE_MS}, reçu « {raw} ».",
            )
    raw = _setting_raw(settings, OWNER_PROFILE_PATH_SETTING)
    if raw is None:
        profile_path = root / OWNER_PROFILE_FILENAME
    elif not isinstance(raw, str):
        raise ConversationAuthorizationError(
            "owner_profile_path_invalid",
            f"Le chemin du profil vocal (owner_profile_path) doit être un texte, reçu « {raw} ».",
        )
    else:
        candidate = Path(raw.strip()).expanduser()
        candidate = candidate if candidate.is_absolute() else Path(runtime_root) / candidate
        # L'empreinte vocale est une donnée biométrique : elle ne sort pas du
        # dossier runtime, ignoré par Git. Un réglage écrit à la main peut viser
        # « ../../voix.json » ou « C:\… » ; refusé, avec un code stable.
        profile_path = _under_runtime_root(candidate, runtime_root, raw)
    short_evidence_ms: int | None = min(DEFAULT_OWNER_SHORT_EVIDENCE_MS, evidence_ms - 100)
    raw = _setting_raw(settings, OWNER_SHORT_EVIDENCE_MS_SETTING)
    if raw is not None:
        try:
            if isinstance(raw, bool):
                raise ValueError(raw)
            value = float(raw)  # type: ignore[arg-type]
            if not value.is_integer():
                raise ValueError(raw)
            short_evidence_ms = int(value)
        except (TypeError, ValueError, OverflowError):
            short_evidence_ms = -1
        if short_evidence_ms != 0 and not MIN_OWNER_SHORT_EVIDENCE_MS <= short_evidence_ms < evidence_ms:
            raise ConversationAuthorizationError(
                "owner_short_evidence_invalid",
                f"La parole minimale d'une réponse brève (owner_short_evidence_ms) doit valoir 0 (désactivé) "
                f"ou un nombre entier de millisecondes d'au moins {MIN_OWNER_SHORT_EVIDENCE_MS} et inférieur à "
                f"la fenêtre de preuve ({evidence_ms} ms), reçu « {raw} ».",
            )
    if short_evidence_ms is not None and short_evidence_ms < MIN_OWNER_SHORT_EVIDENCE_MS:
        # 0, ou une fenêtre de preuve trop courte pour qu'une réponse brève
        # s'en distingue : pas de règle brève.
        short_evidence_ms = None
    short_margin = DEFAULT_OWNER_SHORT_MARGIN
    raw = _setting_raw(settings, OWNER_SHORT_MARGIN_SETTING)
    if raw is not None:
        try:
            if isinstance(raw, bool):
                raise ValueError(raw)
            short_margin = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            short_margin = math.nan
        if not (math.isfinite(short_margin) and 0.0 <= short_margin <= MAX_OWNER_SHORT_MARGIN):
            raise ConversationAuthorizationError(
                "owner_short_margin_invalid",
                f"La marge des réponses brèves (owner_short_margin) doit être un nombre entre 0 et "
                f"{MAX_OWNER_SHORT_MARGIN}, reçu « {raw} ».",
            )
    return SpeakerVerifierSettings(
        model_dir=root / "models",
        profile_path=profile_path,
        threshold=threshold,
        evidence_ms=evidence_ms,
        short_evidence_ms=short_evidence_ms,
        short_margin=short_margin,
    )


@dataclass(frozen=True, slots=True)
class V2Settings:
    data_root: Path
    runtime_root: Path
    core_host: str
    core_port: int
    timezone: str
    token_file: Path
    recent_turn_limit: int
    active_timeout_s: float
    realtime_model: str
    realtime_voice: str
    auto_turn: bool
    voice_arch: VoiceArchitecture

    @classmethod
    def load(cls) -> "V2Settings":
        data_root = Path(os.getenv("JARVIS_DATA_ROOT", "./data")).expanduser().resolve()
        runtime_root = Path(os.getenv("JARVIS_RUNTIME_DIR", "./runtime")).expanduser().resolve()
        port = _int_env("JARVIS_CORE_PORT", 17653)
        if not 1 <= port <= 65535:
            raise ConfigurationError("JARVIS_CORE_PORT must be between 1 and 65535")
        recent = _int_env("JARVIS_RECENT_TURN_LIMIT", 12)
        if not 1 <= recent <= 100:
            raise ConfigurationError("JARVIS_RECENT_TURN_LIMIT must be between 1 and 100")
        timeout = parse_active_timeout(os.getenv("JARVIS_ACTIVE_TIMEOUT_S", "90"))
        voice_arch = parse_voice_arch(os.getenv("JARVIS_VOICE_ARCH"))
        recommended_model = (
            DEFAULT_CONTINUOUS_SURFACE_MODEL
            if voice_arch is VoiceArchitecture.CONTINUOUS_BRAIN
            else DEFAULT_REALTIME_MODEL
        )
        model = os.getenv("OPENAI_REALTIME_MODEL", recommended_model).strip()
        # "cedar" is the low, level voice of the two gpt-realtime timbres, which is
        # the one that reads as Jarvis rather than as a generic assistant.
        voice = os.getenv("OPENAI_REALTIME_VOICE", "cedar").strip()
        if not model or not voice:
            raise ConfigurationError("Realtime model and voice must not be empty")
        auto_turn = parse_turn_mode(os.getenv("JARVIS_VOICE_TURN_MODE", "auto"))
        return cls(data_root=data_root,runtime_root=runtime_root,core_host=validate_loopback_host(os.getenv("JARVIS_CORE_HOST", "127.77.0.1")),core_port=port,timezone=os.getenv("JARVIS_TIMEZONE", "Europe/Paris").strip() or "Europe/Paris",token_file=Path(os.getenv("JARVIS_CORE_TOKEN_FILE", str(runtime_root / "core.token"))).expanduser().resolve(),recent_turn_limit=recent,active_timeout_s=timeout,realtime_model=model,realtime_voice=voice,auto_turn=auto_turn,voice_arch=voice_arch)

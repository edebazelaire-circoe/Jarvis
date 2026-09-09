from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import ipaddress
import os

from jarvis.domain.errors import ConfigurationError


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

    Elle vit ici, et non dans les réglages de pile du Control Center, pour deux
    raisons. D'abord `voice_stack.py` dit explicitement ne décrire que des champs
    « réellement transmis au fournisseur » : le mode d'architecture ne part chez
    personne, il choisit le chemin de code de JARVIS. Ensuite c'est un
    interrupteur de déploiement, pas une préférence d'utilisateur (Décision 20) :
    on doit pouvoir revenir à `legacy` en une ligne de `.env` et un
    redémarrage, sans dépendre d'un fichier de réglages écrit par l'interface.

    `LEGACY` reste le défaut tant que le mode continu n'a pas passé les recettes
    poste de travail : garder le micro ouvert pendant que les haut-parleurs
    jouent est un risque acoustique réel, jamais résolu logiciellement ici.

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


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    try:
        return float(raw) if raw is not None else default
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number") from exc


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
        timeout = _float_env("JARVIS_ACTIVE_TIMEOUT_S", 90.0)
        if timeout < 5:
            raise ConfigurationError("JARVIS_ACTIVE_TIMEOUT_S must be >= 5")
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

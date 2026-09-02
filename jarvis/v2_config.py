from __future__ import annotations

from dataclasses import dataclass
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
        model = os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime-2.1").strip()
        voice = os.getenv("OPENAI_REALTIME_VOICE", "marin").strip()
        if not model or not voice:
            raise ConfigurationError("Realtime model and voice must not be empty")
        return cls(data_root=data_root,runtime_root=runtime_root,core_host=validate_loopback_host(os.getenv("JARVIS_CORE_HOST", "127.77.0.1")),core_port=port,timezone=os.getenv("JARVIS_TIMEZONE", "Europe/Paris").strip() or "Europe/Paris",token_file=Path(os.getenv("JARVIS_CORE_TOKEN_FILE", str(runtime_root / "core.token"))).expanduser().resolve(),recent_turn_limit=recent,active_timeout_s=timeout,realtime_model=model,realtime_voice=voice)

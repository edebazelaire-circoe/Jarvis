from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import tomllib
from urllib.parse import urlparse

from .domain.errors import ConfigurationError


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} doit etre true/false")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} doit etre un nombre") from exc


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} doit etre un entier") from exc


def _loopback_url(value: str, field: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ConfigurationError(f"{field} doit etre une URL HTTP loopback")
    return value.rstrip("/")


@dataclass(frozen=True, slots=True)
class OpenAIConfig:
    api_key: str | None
    base_url: str
    transcription_model: str
    agent_model: str
    tts_model: str
    tts_voice: str
    tts_instructions: str
    timeout_s: float


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    ptt_key: str
    memory_dir: Path
    runtime_dir: Path
    log_level: str
    log_content: bool
    confirmation_timeout_s: float


@dataclass(frozen=True, slots=True)
class AudioConfig:
    sample_rate: int
    channels: int
    input_device: str | None


@dataclass(frozen=True, slots=True)
class ComponentConfig:
    enabled: bool
    url: str


@dataclass(frozen=True, slots=True)
class AppConfig:
    openai: OpenAIConfig
    runtime: RuntimeConfig
    audio: AudioConfig
    board: ComponentConfig
    visualizer: ComponentConfig

    @classmethod
    def load(cls, path: str | Path | None = None) -> "AppConfig":
        if path is None:
            path = os.getenv("JARVIS_CONFIG")
        cfg_path = Path(path) if path else Path("config/jarvis.toml")
        if not cfg_path.exists():
            example = Path("config/jarvis.example.toml")
            if not example.exists():
                raise ConfigurationError(f"Configuration introuvable: {cfg_path}")
            cfg_path = example
        try:
            data = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigurationError(f"Configuration invalide: {exc}") from exc

        o = data.get("openai", {})
        r = data.get("runtime", {})
        a = data.get("audio", {})
        b = data.get("board", {})
        v = data.get("visualizer", {})

        def required_model(env_name: str, key: str) -> str:
            value = os.getenv(env_name, str(o.get(key, ""))).strip()
            if not value:
                raise ConfigurationError(f"Modele manquant: {env_name} / openai.{key}")
            return value

        base_url = os.getenv("OPENAI_BASE_URL", str(o.get("base_url", "https://api.openai.com/v1"))).rstrip("/")
        parsed = urlparse(base_url)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise ConfigurationError("OPENAI_BASE_URL invalide")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ConfigurationError("OPENAI_BASE_URL distant doit utiliser HTTPS")

        openai = OpenAIConfig(
            api_key=os.getenv("OPENAI_API_KEY") or None,
            base_url=base_url,
            transcription_model=required_model("OPENAI_TRANSCRIPTION_MODEL", "transcription_model"),
            agent_model=required_model("OPENAI_AGENT_MODEL", "agent_model"),
            tts_model=required_model("OPENAI_TTS_MODEL", "tts_model"),
            tts_voice=os.getenv("OPENAI_TTS_VOICE", str(o.get("tts_voice", ""))).strip(),
            tts_instructions=os.getenv("OPENAI_TTS_INSTRUCTIONS", str(o.get("tts_instructions", ""))).strip(),
            timeout_s=_env_float("OPENAI_TIMEOUT_S", float(o.get("timeout_s", 45.0))),
        )
        if not openai.tts_voice:
            raise ConfigurationError("Voix TTS manquante")
        if openai.timeout_s <= 0:
            raise ConfigurationError("OPENAI_TIMEOUT_S doit etre > 0")

        memory_dir = Path(os.getenv("JARVIS_MEMORY_DIR", str(r.get("memory_dir", "./data/memory")))).expanduser().resolve()
        runtime_dir = Path(os.getenv("JARVIS_RUNTIME_DIR", str(r.get("runtime_dir", "./runtime")))).expanduser().resolve()
        runtime = RuntimeConfig(
            ptt_key=os.getenv("JARVIS_PTT_KEY", str(r.get("ptt_key", ""))).strip().lower(),
            memory_dir=memory_dir,
            runtime_dir=runtime_dir,
            log_level=os.getenv("JARVIS_LOG_LEVEL", str(r.get("log_level", "INFO"))).upper(),
            log_content=_env_bool("JARVIS_LOG_CONTENT", bool(r.get("log_content", False))),
            confirmation_timeout_s=_env_float(
                "JARVIS_CONFIRMATION_TIMEOUT_S", float(r.get("confirmation_timeout_s", 45.0))
            ),
        )
        if not runtime.ptt_key:
            raise ConfigurationError("JARVIS_PTT_KEY ne peut pas etre vide")
        if runtime.confirmation_timeout_s <= 0:
            raise ConfigurationError("Le timeout de confirmation doit etre > 0")

        audio = AudioConfig(
            sample_rate=_env_int("JARVIS_AUDIO_SAMPLE_RATE", int(a.get("sample_rate", 16000))),
            channels=_env_int("JARVIS_AUDIO_CHANNELS", int(a.get("channels", 1))),
            input_device=(os.getenv("JARVIS_AUDIO_INPUT_DEVICE", str(a.get("input_device", ""))).strip() or None),
        )
        if audio.sample_rate < 8000 or audio.sample_rate > 96000:
            raise ConfigurationError("Frequence audio hors plage")
        if audio.channels != 1:
            raise ConfigurationError("Jarvis V1 supporte uniquement l'audio mono")

        board_url = os.getenv("JARVIS_BOARD_URL", str(b.get("url", "http://127.0.0.1:8794")))
        visualizer_url = os.getenv("JARVIS_VISUALIZER_URL", str(v.get("url", "http://127.0.0.1:8790")))
        board = ComponentConfig(
            enabled=_env_bool("JARVIS_BOARD_ENABLED", bool(b.get("enabled", True))),
            url=_loopback_url(board_url, "board.url"),
        )
        visualizer = ComponentConfig(
            enabled=_env_bool("JARVIS_VISUALIZER_ENABLED", bool(v.get("enabled", True))),
            url=_loopback_url(visualizer_url, "visualizer.url"),
        )
        return cls(openai=openai, runtime=runtime, audio=audio, board=board, visualizer=visualizer)

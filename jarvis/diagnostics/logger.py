from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

SENSITIVE_KEYS = frozenset(
    {
        "text",
        "transcript",
        "prompt",
        "response",
        "body",
        "content",
        "audio",
        "api_key",
        "authorization",
    }
)


def _sanitize(value: Any, *, key: str | None = None, log_content: bool = False) -> Any:
    if key and key.lower() in SENSITIVE_KEYS and not log_content:
        if isinstance(value, (str, bytes)):
            return f"<redacted:{len(value)}>"
        return "<redacted>"
    if isinstance(value, dict):
        return {str(k): _sanitize(v, key=str(k), log_content=log_content) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(v, log_content=log_content) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class PrivacyLogger:
    """Write one machine-readable JSON object per line.

    Content-bearing fields are redacted by default. This makes the privacy
    boundary visible in the logger itself rather than depending on every
    caller remembering which fields are sensitive.
    """

    def __init__(self, logger: logging.Logger, *, log_content: bool = False) -> None:
        if not isinstance(logger, logging.Logger):
            raise TypeError("PrivacyLogger expects logging.Logger; use build_logger(runtime_dir)")
        self.logger = logger
        self.log_content = log_content

    def event(self, name: str, *, level: int = logging.INFO, **fields: Any) -> None:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": logging.getLevelName(level),
            "event": name,
            **_sanitize(fields, log_content=self.log_content),
        }
        self.logger.log(level, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def build_logger(runtime_dir: Path, *, level: str = "INFO", log_content: bool = False) -> PrivacyLogger:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("jarvis")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False
    logger.handlers.clear()
    handler = RotatingFileHandler(runtime_dir / "jarvis.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return PrivacyLogger(logger, log_content=log_content)

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class HealthCheck:
    name: str
    status: str
    required: bool
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "required": self.required,
            "message": self.message,
            "details": self.details,
        }


@dataclass(frozen=True, slots=True)
class HealthReport:
    status: str
    checks: tuple[HealthCheck, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "checks": [c.as_dict() for c in self.checks]}


async def run_health_checks(config, *, board=None, check_audio: bool = True, recorder=None) -> HealthReport:
    checks: list[HealthCheck] = []

    runtime_dir = Path(config.runtime.runtime_dir)
    try:
        runtime_dir.mkdir(parents=True, exist_ok=True)
        probe = runtime_dir / ".health-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        checks.append(HealthCheck("runtime_dir", "ok", True))
    except Exception as exc:
        checks.append(HealthCheck("runtime_dir", "fail", True, type(exc).__name__))

    if config.openai.api_key:
        checks.append(HealthCheck("openai_credentials", "ok", True))
    else:
        checks.append(HealthCheck("openai_credentials", "warn", False, "OPENAI_API_KEY absent"))

    if check_audio:
        if recorder is None:
            checks.append(HealthCheck("audio", "warn", False, "Recorder non fourni"))
        else:
            try:
                details = recorder.preflight()
                checks.append(HealthCheck("audio", "ok", True, details=details or {}))
            except Exception as exc:
                checks.append(HealthCheck("audio", "fail", True, type(exc).__name__))
    else:
        checks.append(HealthCheck("audio", "disabled", False))

    if config.board.enabled:
        if board is None:
            checks.append(HealthCheck("barehands", "warn", False, "Client non fourni"))
        else:
            try:
                ping = getattr(board, "health", None) or getattr(board, "ping", None)
                if ping is not None:
                    result = ping()
                    if hasattr(result, "__await__"):
                        await result
                checks.append(HealthCheck("barehands", "ok", False))
            except Exception as exc:
                checks.append(HealthCheck("barehands", "warn", False, type(exc).__name__))
    else:
        checks.append(HealthCheck("barehands", "disabled", False))

    if config.board.enabled or config.visualizer.enabled:
        checks.append(HealthCheck("third_party", "ok", False))
    else:
        checks.append(HealthCheck("third_party", "disabled", False))

    if any(c.status == "fail" and c.required for c in checks):
        status = "fail"
    elif any(c.status == "warn" for c in checks):
        status = "warn"
    else:
        status = "ok"
    return HealthReport(status=status, checks=tuple(checks))

"""Read-only GPT-Live lifecycle projection for the Control Center.

Core remains the source of lifecycle truth. This view keeps the last
nonterminal record when Core is temporarily unreachable so the UI cannot turn
an uncertain, potentially billable session into a reassuring OFF state.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Protocol

from jarvis.domain.live_lifecycle import LiveLifecycleState, LiveSessionRecord
from jarvis.runtime.pricing import PricingMetadata


DEFAULT_READ_TIMEOUT_S = 2.0
_VISIBLE = {
    LiveLifecycleState.STARTING,
    LiveLifecycleState.ACTIVE,
    LiveLifecycleState.IDLE_CANDIDATE,
    LiveLifecycleState.STOPPING,
    LiveLifecycleState.UNKNOWN_REAP_REQUIRED,
}


class LiveStatusReader(Protocol):
    async def live_session_status(self) -> LiveSessionRecord | None: ...
    async def close(self) -> None: ...


def _seconds_since(value: datetime, now: datetime) -> float:
    return max(0.0, (now - value).total_seconds())


def _pricing(value: object, *, model_id: str | None) -> dict[str, object] | None:
    """Accept pricing only when provenance and applicability are explicit."""
    parsed = PricingMetadata.parse(value, model_id=model_id)
    if parsed is None:
        return None
    return {"model_id": parsed.model_id, "currency": parsed.currency,
            "price_per_minute": parsed.price_per_minute, "source": parsed.source,
            "effective_at": parsed.effective_at}


def project_live_status(record: LiveSessionRecord | None, *, now: datetime,
                        runtime: dict[str, object] | None = None, pricing: object = None,
                        core_reachable: bool = True, stale: bool = False,
                        request: dict[str, object] | None = None,
                        receipt: dict[str, object] | None = None) -> dict[str, object]:
    """Turn Core truth plus scalar Voice telemetry into the public UI shape."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    runtime = runtime if isinstance(runtime, dict) else {}
    if record is None and not core_reachable:
        session_id = runtime.get("session_id") if isinstance(runtime.get("session_id"), str) else None
        return {"visible": True, "session_id": session_id, "state": "status_unavailable",
                "uncertain": True, "core_reachable": False, "stale": stale,
                "server_time": now.isoformat(), "elapsed_seconds": 0.0,
                "elapsed_basis": "unavailable", "activated_at": None, "usage": None,
                "cost_estimate": None, "idle": None,
                "warning": "Core est indisponible : aucune preuve d’absence de session Live facturable.",
                "stop": {"pending": False, "failed": False,
                         "available": session_id is not None, "can_retry": session_id is not None}}
    if record is None or record.state not in _VISIBLE:
        return {"visible": False, "state": "stopped", "core_reachable": core_reachable,
                "stale": stale, "server_time": now.isoformat(),
                "stop": {"pending": False, "failed": False}}

    activated = record.activated_at
    if activated is not None:
        elapsed = max(record.active_seconds, _seconds_since(activated, now))
        elapsed_basis = "active"
    else:
        elapsed = _seconds_since(record.created_at, now)
        elapsed_basis = "session"

    runtime_current = runtime.get("session_id") == record.session_id
    model_id = runtime.get("model_id") if runtime_current and isinstance(runtime.get("model_id"), str) else None
    idle: dict[str, object] | None = None
    remaining, timeout = runtime.get("idle_remaining_s"), runtime.get("idle_timeout_s")
    if (runtime_current and runtime.get("idle_enabled") is True
            and not isinstance(remaining, bool) and isinstance(remaining, (int, float))
            and not isinstance(timeout, bool) and isinstance(timeout, (int, float))):
        idle = {"enabled": True, "remaining_seconds": max(0.0, float(remaining)),
                "timeout_seconds": max(0.0, float(timeout)),
                "waiting_for_safe_point": runtime.get("idle_waiting_for_safe_point") is True}

    usage_seconds = record.provider_usage_seconds
    usage = None if usage_seconds is None else {
        "seconds": usage_seconds, "final": record.provider_usage_final, "source": "provider"}
    price = _pricing(pricing, model_id=model_id)
    estimate = None
    if price is not None:
        basis_seconds = usage_seconds if usage_seconds is not None else elapsed
        estimate = {"amount": float(price["price_per_minute"]) * basis_seconds / 60.0,
                    "currency": price["currency"],
                    "basis": "provider_usage" if usage_seconds is not None else "elapsed_time",
                    "source": price["source"], "effective_at": price["effective_at"],
                    "model_id": price["model_id"]}

    request_matches = isinstance(request, dict) and request.get("session_id") == record.session_id
    receipt_matches = isinstance(receipt, dict) and receipt.get("session_id") == record.session_id
    stop_failed = receipt_matches and receipt.get("status") == "failed"
    stop_pending = request_matches or (receipt_matches and receipt.get("status") == "accepted"
                                       and record.state is not LiveLifecycleState.UNKNOWN_REAP_REQUIRED)
    warning = None
    if record.state is LiveLifecycleState.UNKNOWN_REAP_REQUIRED:
        warning = "Clôture non confirmée : la session peut encore être facturable. Réessayez l’arrêt; Core poursuit la récupération."
    elif stale or not core_reachable:
        warning = "Core est momentanément illisible. Dernier état Live conservé; l’arrêt n’est pas confirmé."
    elif stop_failed:
        warning = str(receipt.get("message") or "La demande d’arrêt a échoué; réessayez.")

    return {"visible": True, "session_id": record.session_id, "state": record.state.value,
            "uncertain": record.state is LiveLifecycleState.UNKNOWN_REAP_REQUIRED or stale,
            "core_reachable": core_reachable, "stale": stale, "server_time": now.isoformat(),
            "elapsed_seconds": elapsed, "elapsed_basis": elapsed_basis,
            "activated_at": activated.isoformat() if activated else None,
            "usage": usage, "cost_estimate": estimate, "idle": idle, "warning": warning,
            "stop": {"pending": stop_pending, "failed": stop_failed,
                     "available": True,
                     "request_id": request.get("request_id") if request_matches else None,
                     "can_retry": record.state is LiveLifecycleState.UNKNOWN_REAP_REQUIRED or stop_failed}}


class CoreLiveStatusView:
    """Poll Core and retain only an unresolved record across read failures."""
    def __init__(self, reader: LiveStatusReader, *, timeout_s: float = DEFAULT_READ_TIMEOUT_S,
                 journal: Any = None) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self.reader, self.timeout_s, self.journal = reader, timeout_s, journal
        self._held: LiveSessionRecord | None = None
        self._failure_reported = False

    async def read(self) -> tuple[LiveSessionRecord | None, bool, bool]:
        try:
            record = await asyncio.wait_for(self.reader.live_session_status(), timeout=self.timeout_s)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._failure_reported and self.journal is not None:
                self.journal.emit(
                    "ui.live_status_unavailable", "Core Live lifecycle status is unavailable",
                    level="warning", data={"code": "live_status_unavailable",
                                           "exception_type": type(exc).__name__},
                )
            self._failure_reported = True
            return self._held, False, self._held is not None
        if self._failure_reported and self.journal is not None:
            self.journal.emit("ui.live_status_recovered", "Core Live lifecycle status recovered")
        self._failure_reported = False
        self._held = record if record is not None and record.state in _VISIBLE else None
        return self._held, True, False

    async def aclose(self) -> None:
        await self.reader.close()

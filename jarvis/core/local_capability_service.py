"""Façade asynchrone de l'hôte des capacités locales (Slice 04 ; `docs/local-capabilities.md` §7).

`LocalCapabilityHost` est synchrone (npm, processus). Cette façade est ce que Core et ses routes appellent :

- opérations courtes (`start`, `stop`, `health`, `enable`, `disable`) : exécutées dans un thread, réponse 200 ;
- opérations longues (`install`, `update`, `repair`, `uninstall`) : thread dédié (démon, jamais le pool par
  défaut, pour qu'un arrêt de Core n'attende pas npm). Si elles finissent en `wait_s`, réponse 200 ; sinon 202 avec
  l'état courant (`installing`...), que l'appelant relit par `GET`. Un refus de précondition (occupée, inconnue...)
  arrive dans la fenêtre et sort donc en erreur synchrone ;
- AUCUNE opération n'est lancée par le démarrage de Core : seul `reconcile()` (qui n'installe, ne lance, n'arrête rien) l'est.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import threading
from typing import Any

from jarvis.core.local_capability_host import LocalCapabilityHost
from jarvis.domain.local_capabilities import LocalCapabilityError, LocalCapabilityErrorCode as C
from jarvis.ports.v2 import DiagnosticSink

LONG_OPERATIONS = ("install", "update", "repair", "uninstall")
SHORT_OPERATIONS = ("start", "stop", "health", "enable", "disable")
OPERATIONS = (*LONG_OPERATIONS, *SHORT_OPERATIONS)
DEFAULT_WAIT_S = 2.0

_STATUS = {C.UNKNOWN: 404, C.INVALID: 400, C.RUNNER_UNAVAILABLE: 503, C.STORE_FAILED: 500, C.INTERNAL_ERROR: 500}


def http_status(code: C) -> int:
    """404 inconnue, 400 invalide, 503 sans runner, 500 défaut local ; tout autre refus de précondition : 409."""

    return _STATUS.get(code, 409)


class LocalCapabilityService:
    def __init__(self, host: LocalCapabilityHost, *, wait_s: float = DEFAULT_WAIT_S, diagnostics: DiagnosticSink | None = None) -> None:
        self._host = host
        self._wait_s = wait_s
        self._diagnostics = diagnostics
        self._threads: set[threading.Thread] = set()

    def _emit(self, kind: str, message: str, *, level: str = "info", **data: Any) -> None:
        if self._diagnostics is not None:
            self._diagnostics.emit(f"local_capability.service.{kind}", message, level=level, data=data)

    # -------------------------------------------------------------- démarrage / arrêt de Core

    def reconcile(self) -> list[dict[str, Any]]:
        """Au démarrage de Core : état stocké rendu conforme au disque et aux processus. Ne lève jamais, n'agit sur rien."""

        try:
            views = self._host.reconcile()
        except Exception as exc:  # noqa: BLE001 - un défaut de capacité ne doit jamais empêcher Core de démarrer
            self._emit("reconcile_failed", f"reconcile failed: {type(exc).__name__}", level="error")
            return []
        self._emit("reconciled", "local capabilities reconciled", count=len(views))
        return views

    async def stop(self) -> None:
        """À l'arrêt de Core : interrompt une installation en vol (arbre npm tué) sans attendre sa fin."""

        cancel = getattr(self._host.runner, "cancel_all", None)
        if callable(cancel):
            await asyncio.to_thread(cancel)

    # ----------------------------------------------------------------------------- lecture

    async def list(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._host.list_status)

    async def get(self, capability_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._host.status, capability_id)

    # --------------------------------------------------------------------------- opérations

    async def act(self, capability_id: str, operation: str) -> tuple[int, dict[str, Any]]:
        """`(200, vue)` si finie, `(202, vue courante)` si l'opération longue continue. Lève `LocalCapabilityError` sur refus."""

        if operation not in OPERATIONS:
            raise LocalCapabilityError(C.INVALID, f"unknown operation {operation[:40]!r}")
        call: Callable[[str], dict[str, Any]] = {"health": self._host.check_health}.get(operation) or getattr(self._host, operation)
        if operation in SHORT_OPERATIONS:
            return 200, await asyncio.to_thread(call, capability_id)
        future = self._spawn(call, capability_id, operation)
        done, _ = await asyncio.wait({future}, timeout=self._wait_s)
        if done:
            return 200, future.result()
        future.add_done_callback(lambda f: self._log_background(capability_id, operation, f))
        return 202, await asyncio.to_thread(self._host.status, capability_id)

    def _spawn(self, call: Callable[[str], dict[str, Any]], capability_id: str, operation: str) -> asyncio.Future:
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()

        def settle(result: Any, error: BaseException | None) -> None:
            if future.done():
                return
            future.set_exception(error) if error is not None else future.set_result(result)

        def work() -> None:
            try:
                outcome, error = call(capability_id), None
            except BaseException as exc:  # noqa: BLE001 - relayed to the awaiting coroutine or logged by the callback
                outcome, error = None, exc
            try:
                loop.call_soon_threadsafe(settle, outcome, error)
            except RuntimeError:  # la boucle est fermée (Core s'arrête) : l'état écrit par l'hôte reste la vérité
                pass
            finally:
                self._threads.discard(threading.current_thread())

        thread = threading.Thread(target=work, name=f"local-capability-{operation}-{capability_id}", daemon=True)
        self._threads.add(thread)
        thread.start()
        return future

    def _log_background(self, capability_id: str, operation: str, future: asyncio.Future) -> None:
        error = future.exception() if not future.cancelled() else None
        if error is not None:
            code = error.code.value if isinstance(error, LocalCapabilityError) else type(error).__name__
            self._emit("background_failed", f"{operation} failed after the response: {code}", level="error",
                       capability_id=capability_id, code=code)
        else:
            self._emit("background_done", f"{operation} finished after the response", capability_id=capability_id)

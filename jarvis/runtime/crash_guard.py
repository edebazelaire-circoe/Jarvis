"""Capture des morts de processus que `try/except` ne peut pas voir.

Un `except` Python ne s'exécute que si l'interpréteur est encore vivant. Trois
familles de pannes échappent donc entièrement au système d'erreurs :

* les crashs natifs (violation d'accès 0xC0000005 dans PortAudio, Porcupine…),
  où Windows tue le processus sans dérouler la pile Python ;
* les exceptions non rattrapées d'un thread ou d'une tâche asyncio orpheline ;
* la sortie fatale d'un enfant supervisé, invisible depuis le processus mort.

Ce module installe les trois filets manquants : `faulthandler` écrit la pile
Python au moment du signal fatal, les hooks d'exception routent vers le journal,
et le log de crash laissé par un processus mort est réinjecté dans le journal au
démarrage suivant pour qu'il apparaisse dans le Control Center.
"""

from __future__ import annotations

import asyncio
import atexit
from datetime import datetime, timezone
import faulthandler
import os
from pathlib import Path
import signal
import sys
import threading
import traceback
from typing import IO, Any

from jarvis.runtime.journal import RuntimeJournal


CRASH_TAIL_LINES = 80

# Un processus Windows tué par le noyau expose son NTSTATUS comme code de sortie
# signé : 0xC0000005 devient -1073741819. Sans ce décodage le code brut ne dit
# rien à l'utilisateur, et c'est exactement ce qui a été remonté sans message.
_NTSTATUS_LABELS = {
    0xC0000005: "ACCESS_VIOLATION (crash natif : accès mémoire invalide)",
    0xC000001D: "ILLEGAL_INSTRUCTION (crash natif)",
    0xC0000025: "NONCONTINUABLE_EXCEPTION (crash natif)",
    0xC000008C: "ARRAY_BOUNDS_EXCEEDED (crash natif)",
    0xC000008E: "FLOAT_DIVIDE_BY_ZERO (crash natif)",
    0xC0000094: "INTEGER_DIVIDE_BY_ZERO (crash natif)",
    0xC00000FD: "STACK_OVERFLOW (crash natif : récursion ou pile épuisée)",
    0xC0000135: "DLL_NOT_FOUND (dépendance native absente)",
    0xC0000139: "ENTRYPOINT_NOT_FOUND (DLL incompatible)",
    0xC000013A: "CONTROL_C_EXIT (interruption clavier)",
    0xC0000142: "DLL_INIT_FAILED (initialisation d'une DLL en échec)",
    0xC0000374: "HEAP_CORRUPTION (corruption du tas dans du code natif)",
    0xC0000409: "STACK_BUFFER_OVERRUN (protection de pile déclenchée)",
    0xC0000417: "INVALID_CRUNTIME_PARAMETER (appel natif invalide)",
    0x80000003: "BREAKPOINT (point d'arrêt natif)",
}

# SIGBUS n'existe pas sur Windows : la table est construite depuis ce qui est
# réellement exposé par la plateforme.
_CRASH_SIGNALS = {
    int(value)
    for value in (getattr(signal, name, None) for name in ("SIGSEGV", "SIGBUS", "SIGILL", "SIGABRT", "SIGFPE"))
    if value is not None
}

_installed_role: str | None = None
_installed_journal: RuntimeJournal | None = None
# faulthandler écrit dans ce descripteur au moment du signal fatal : il doit
# rester ouvert pour toute la vie du processus, sinon le dump est perdu.
_crash_handle: IO[str] | None = None
# Dernière exception journalisée, pour ne pas la compter deux fois.
_last_reported: BaseException | None = None


def describe_exit_code(code: int | None) -> dict[str, Any]:
    """Traduire un code de sortie en diagnostic lisible et exploitable."""
    if code is None:
        return {"exit_code": None, "label": "en cours d'exécution", "fatal": False, "native_crash": False}
    if code == 0:
        return {"exit_code": 0, "label": "arrêt normal", "fatal": False, "native_crash": False}

    detail: dict[str, Any] = {"exit_code": code, "fatal": True, "native_crash": False}
    if code < 0:
        if sys.platform == "win32" or code < -0x1000:
            status = code & 0xFFFFFFFF
            detail["ntstatus"] = f"0x{status:08X}"
            detail["native_crash"] = True
            detail["label"] = _NTSTATUS_LABELS.get(status, f"crash natif NTSTATUS 0x{status:08X}")
            return detail
        try:
            name = signal.Signals(-code).name
        except ValueError:
            name = f"signal {-code}"
        detail["signal"] = name
        detail["native_crash"] = -code in _CRASH_SIGNALS
        detail["label"] = f"tué par {name}"
        return detail

    status = code & 0xFFFFFFFF
    if status in _NTSTATUS_LABELS:
        detail["ntstatus"] = f"0x{status:08X}"
        detail["native_crash"] = True
        detail["label"] = _NTSTATUS_LABELS[status]
        return detail
    detail["label"] = f"sortie avec le code {code}"
    return detail


def crash_log_path(runtime_root: Path, role: str) -> Path:
    return runtime_root / f"crash-{role}.log"


def take_crash_log(runtime_root: Path, role: str) -> str | None:
    """Lire puis archiver le dump laissé par un processus mort.

    Renvoie le contenu et déplace le fichier, pour qu'un même crash ne soit pas
    journalisé deux fois quand le superviseur et le processus relancé le voient
    tous les deux.
    """
    path = crash_log_path(runtime_root, role)
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not text:
        try:
            path.unlink()
        except OSError:
            pass
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    archive_dir = runtime_root / "crashes"
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        path.replace(archive_dir / f"{role}-{stamp}.log")
    except OSError:
        try:
            path.unlink()
        except OSError:
            pass
    return text


def tail(text: str, lines: int = CRASH_TAIL_LINES) -> str:
    return "\n".join(text.splitlines()[-lines:])


def report_previous_crash(journal: RuntimeJournal, runtime_root: Path, role: str) -> bool:
    """Réinjecter dans le journal le dump d'un crash antérieur, s'il existe."""
    text = take_crash_log(runtime_root, role)
    if text is None:
        return False
    journal.emit(
        "process.crashed",
        f"Le processus « {role} » s'est arrêté brutalement lors de l'exécution précédente.",
        level="error",
        data={"role": role, "code": "process_native_crash", "traceback": tail(text)},
    )
    return True


def _close_crash_handle() -> None:
    """Fermer le dump du garde précédent : faulthandler écrit alors ailleurs."""
    global _crash_handle
    handle, _crash_handle = _crash_handle, None
    if handle is None:
        return
    faulthandler.disable()
    try:
        handle.close()
    except OSError:
        pass


def install_crash_guard(*, runtime_root: Path, role: str, journal: RuntimeJournal | None = None) -> RuntimeJournal:
    """Armer faulthandler et les hooks d'exception pour le processus courant."""
    global _installed_role, _installed_journal, _crash_handle

    runtime_root.mkdir(parents=True, exist_ok=True)
    journal = journal or RuntimeJournal(runtime_root)
    _installed_role, _installed_journal = role, journal

    report_previous_crash(journal, runtime_root, role)

    _close_crash_handle()
    try:
        handle = crash_log_path(runtime_root, role).open("w", encoding="utf-8", buffering=1)
    except OSError:
        handle = None
    if handle is not None:
        _crash_handle = handle
        # all_threads: le crash vient presque toujours du thread audio PortAudio,
        # pas du thread principal.
        faulthandler.enable(file=handle, all_threads=True)
        atexit.register(_close_crash_handle)

    previous_hook = sys.excepthook

    def _excepthook(exc_type, exc, tb) -> None:  # noqa: ANN001
        report_fatal(exc, context={"source": "sys.excepthook"})
        previous_hook(exc_type, exc, tb)

    sys.excepthook = _excepthook

    def _thread_excepthook(args) -> None:  # noqa: ANN001
        if args.exc_value is not None:
            report_fatal(args.exc_value, context={"source": "thread", "thread": args.thread and args.thread.name})

    threading.excepthook = _thread_excepthook
    journal.emit("process.start", f"Processus « {role} » démarré", data={"role": role, "pid": os.getpid()})
    return journal


def install_asyncio_crash_guard(loop: asyncio.AbstractEventLoop) -> None:
    """Router les exceptions de tâches orphelines vers le journal."""

    def handler(_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        exc = context.get("exception")
        message = str(context.get("message") or "Erreur asyncio non rattrapée")
        if exc is not None:
            report_fatal(exc, context={"source": "asyncio", "message": message})
        elif _installed_journal is not None:
            _installed_journal.emit(
                "process.async_error",
                message,
                level="error",
                data={"role": _installed_role, "code": "asyncio_unhandled"},
            )

    loop.set_exception_handler(handler)


def report_fatal(exc: BaseException, *, context: dict[str, Any] | None = None) -> None:
    """Journaliser une exception fatale même hors de tout handler applicatif."""
    global _last_reported
    if _installed_journal is None:
        return
    # La même exception passe par le handler de `main()` puis par
    # `sys.excepthook` en remontant : sans ce garde, chaque panne apparaît deux
    # fois dans la liste d'erreurs.
    if exc is _last_reported:
        return
    _last_reported = exc
    data: dict[str, Any] = {
        "role": _installed_role,
        "code": "process_unhandled_exception",
        "exception_type": type(exc).__name__,
        "traceback": tail("".join(traceback.format_exception(type(exc), exc, exc.__traceback__))),
    }
    if context:
        data.update({key: value for key, value in context.items() if value is not None})
    try:
        _installed_journal.emit("process.failed", f"{type(exc).__name__}: {exc}", level="error", data=data)
    except OSError:
        # Le journal est un fichier : son échec ne doit jamais masquer l'erreur
        # d'origine, qui remonte de toute façon à l'appelant.
        pass

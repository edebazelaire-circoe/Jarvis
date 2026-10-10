"""Composition du moteur Remotion (racine de composition : `jarvis/app.py`, tests) : le compilateur de la capacité locale et l'écouteur
du bac à sable, derrière la `RemotionFactory` que Core reçoit (`jarvis/ports/remotion.py`). Rien ne démarre ici."""

from __future__ import annotations

from typing import Any

from jarvis.adapters.remotion_compiler import build_remotion_compiler, shipped_engine_pin
from jarvis.ports.remotion import RemotionComposition, RemotionFactory
from jarvis.runtime.remotion_sandbox_server import RemotionSandboxServer, RemotionSandboxSettings


def remotion_factory(settings: RemotionSandboxSettings) -> RemotionFactory:
    def build(host: Any, store: Any, runner: Any, diagnostics: Any) -> RemotionComposition:
        if host is None or store is None or runner is None:
            return RemotionComposition(None, None)   # no local capability: the engine reports "no adapter", with that reason
        compiler = build_remotion_compiler(host, store, runner, diagnostics=diagnostics)

        def trace(kind: str, message: str, data: dict) -> None:
            if diagnostics is not None:
                diagnostics.emit(kind, message, level="warning" if "failed" in kind else "info", data=data)

        return RemotionComposition(compiler, RemotionSandboxServer(settings, compiler.resolve_output_file, trace=trace), None, shipped_engine_pin)

    return build


def safe_remotion_factory(make_settings: Any, report: Any = None) -> RemotionFactory:
    """`make_settings()` reads the environment. A bad value (`JARVIS_REMOTION_SANDBOX_PORT=abc`, a host that shares the Control Center's)
    must not stop Core: the engine is composed WITHOUT a sandbox and says why (typed `engine_unavailable`, visible), and `report` is told."""

    try:
        return remotion_factory(make_settings())
    except (ValueError, TypeError) as exc:   # SandboxContractError is a ValueError
        problem = f"the Remotion sandbox settings are invalid: {exc}"
        if report is not None:
            report(problem)

        def broken(host: Any, store: Any, runner: Any, diagnostics: Any) -> RemotionComposition:
            compiler = None if host is None or store is None or runner is None else build_remotion_compiler(host, store, runner, diagnostics=diagnostics)
            return RemotionComposition(compiler, None, problem, shipped_engine_pin)

        return broken

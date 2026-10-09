"""Composition du moteur Remotion (racine de composition : `jarvis/app.py`, tests) : le compilateur de la capacité locale et l'écouteur
du bac à sable, derrière la `RemotionFactory` que Core reçoit (`jarvis/ports/remotion.py`). Rien ne démarre ici."""

from __future__ import annotations

from typing import Any

from jarvis.adapters.remotion_compiler import build_remotion_compiler
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

        return RemotionComposition(compiler, RemotionSandboxServer(settings, compiler.resolve_output_file, trace=trace))

    return build

"""Ports du moteur Remotion de Core (handoff jarvis-remotion-presentation-integration, Slice 10).

Core ne connaît ni le compilateur (Node + esbuild, `jarvis/adapters/remotion_compiler.py`) ni l'écouteur du bac à sable
(`jarvis/runtime/remotion_sandbox_server.py`) : `jarvis/app.py` (racine de composition) les construit et les lui injecte par une
`RemotionFactory`, comme le magasin de capacités locales. Pas de factory = un Core sans composition Remotion : le moteur
rapporte « aucun adaptateur » et la porte du moteur reste fermée (opt-out explicite : `engine_gate=False`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class SandboxBindError(RuntimeError):
    """Le port du bac à sable n'a pas pu être ouvert : la cause réelle est dans le message."""


class RemotionCompilerPort(Protocol):
    def unavailable_reason(self) -> str | None: ...

    def compile_host(self) -> Any: ...

    def compile_scene(self, source: Any) -> Any: ...

    def resolve_output_file(self, cache_key: str, relative: str) -> Path: ...


class SandboxListenerPort(Protocol):
    @property
    def origin(self) -> str | None: ...

    @property
    def configured_origin(self) -> str: ...

    @property
    def embedder_origin(self) -> str: ...

    async def ensure_started(self) -> str: ...

    async def stop(self) -> None: ...


@dataclass(frozen=True, slots=True)
class RemotionComposition:
    compiler: RemotionCompilerPort | None
    sandbox: SandboxListenerPort | None
    #: Why the engine cannot be composed (a bad `JARVIS_REMOTION_SANDBOX_*` setting): said as-is by `engine_unavailable`, Core still starts.
    problem: str | None = None


#: `(capability_host, capability_store, capability_runner, diagnostics) -> RemotionComposition`
RemotionFactory = Callable[[Any, Any, Any, Any], RemotionComposition]

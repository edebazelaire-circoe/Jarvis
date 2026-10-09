"""Écouteur de boucle locale du bac à sable Remotion (handoff jarvis-remotion-presentation-integration, Slice 10 ;
`docs/remotion-isolation.md` § 4 et § 10).

Le second écouteur de Core : **autre adresse et autre port** que Core (`127.77.0.1:17653`) et que le Control Center
(`127.0.0.1:17654`), par défaut `127.77.0.2:17655`. Il ne sert que `SandboxResponder.respond` (Slice 06, deux routes, `GET`/`HEAD`) :
pas de jeton, pas de cookie, aucune route de Core, aucun accès à Core. Le contenu est celui de la compilation (`compiled/<clé>/`) lu
par `RemotionCompiler.resolve_output_file` (SHA-256 vérifié).

Lancé **à la demande** (`ensure_started`, au premier `describe` d'une scène Remotion), jamais au démarrage de Core : tant qu'aucune
scène Remotion n'est jouée, aucun port de plus n'est ouvert. Un port déjà pris est un échec typé (`SandboxBindError`), dit tel quel.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from aiohttp import web

from jarvis.domain import remotion_sandbox as sb
from jarvis.ports.remotion import SandboxBindError
from jarvis.runtime.remotion_sandbox import SandboxResponder, load_bootstrap

__all__ = ["DEFAULT_HOST", "DEFAULT_PORT", "RemotionSandboxServer", "RemotionSandboxSettings", "SandboxBindError"]
DEFAULT_HOST = "127.77.0.2"
DEFAULT_PORT = 17655


@dataclass(frozen=True, slots=True)
class RemotionSandboxSettings:
    """`embedder_origin` : l'origine de la page qui encadre le cadre (le Control Center), seule autorisée à l'encadrer
    (`frame-ancestors`) et seule destinataire des messages du cadre."""

    host: str
    port: int
    embedder_origin: str

    def __post_init__(self) -> None:
        if not 1 <= self.port <= 65535:
            raise ValueError("the sandbox port must be between 1 and 65535")
        sb.assert_distinct_origins(self.embedder_origin, self.origin)

    @property
    def origin(self) -> str:
        return sb.origin_of(f"http://{self.host}:{self.port}")


class RemotionSandboxServer:
    """`resolve_file(clé, chemin)` est `RemotionCompiler.resolve_output_file`. `trace(kind, message, data)` : journal."""

    def __init__(self, settings: RemotionSandboxSettings, resolve_file: Any, *, trace: Any = None) -> None:
        self._settings = settings
        self._trace = trace
        self._responder = SandboxResponder(
            resolve_file=resolve_file, embedder_origin=settings.embedder_origin, sandbox_origin=settings.origin,
            allowed_hosts=frozenset({f"{settings.host}:{settings.port}"}), bootstrap_js=load_bootstrap(), trace=trace)
        self._runner: web.AppRunner | None = None
        self._lock = asyncio.Lock()
        self._bound_port: int | None = None

    @property
    def origin(self) -> str | None:
        """L'origine servie, ou `None` tant que l'écouteur n'est pas ouvert."""

        return self._settings.origin if self._runner is not None else None

    @property
    def configured_origin(self) -> str:
        return self._settings.origin

    @property
    def embedder_origin(self) -> str:
        return self._settings.embedder_origin

    async def ensure_started(self) -> str:
        async with self._lock:
            if self._runner is not None:
                return self._settings.origin
            app = web.Application()
            app.router.add_route("*", "/{tail:.*}", self._handle)
            runner = web.AppRunner(app, access_log=None)
            await runner.setup()
            try:
                await web.TCPSite(runner, self._settings.host, self._settings.port).start()
            except OSError as exc:
                await runner.cleanup()
                if self._trace is not None:
                    self._trace("remotion.sandbox.bind_failed", "Le port du bac a sable Remotion n'a pas pu etre ouvert",
                                {"host": self._settings.host, "port": self._settings.port, "errno": exc.errno})
                raise SandboxBindError(f"cannot bind the Remotion sandbox on {self._settings.host}:{self._settings.port}: {exc}") from exc
            self._runner = runner
            if self._trace is not None:
                self._trace("remotion.sandbox.listening", "Bac a sable Remotion a l'ecoute",
                            {"origin": self._settings.origin, "embedder": self._settings.embedder_origin})
            return self._settings.origin

    async def stop(self) -> None:
        async with self._lock:
            runner, self._runner = self._runner, None
            if runner is not None:
                await runner.cleanup()

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        # Lecture disque + SHA-256 : hors de la boucle d'événements de Core.
        result = await asyncio.to_thread(self._responder.respond, request.method, request.raw_path, request.headers.get("Host"),
                                         request.headers.get("Range"))
        return web.Response(status=result.status, headers=result.headers, body=result.body)

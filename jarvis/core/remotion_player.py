"""Adaptateur d'exécution Remotion de Core : disponibilité du moteur et descripteur de lecture d'une scène (handoff
jarvis-remotion-presentation-integration, Slice 10 ; `docs/presentation-engine.md` > *Runtime wiring status*,
`docs/remotion-isolation.md` § 10).

Deux rôles, une seule vérité :

- `availability()` : l'état du moteur `remotion` tel que ses morceaux le rapportent (capacité locale `ready`/`running`, compilateur
  câblé, écouteur du bac à sable configuré). C'est la source de `EngineAvailability` pour `resolve_engine` : **il n'y a pas
  d'autre lecture** de la disponibilité de Remotion dans Core.
- `describe(prefab_id, version)` : ce qu'il faut à un navigateur pour jouer une scène : la source est relue (gardes de la Slice 06),
  compilée (`host.js` partagé, `scene.js`), l'écouteur du bac à sable ouvert à la demande, et l'adresse **de la page du cadre**
  rendue avec la composition déclarée et les valeurs par défaut des propriétés. Ne démarre aucun processus de lecture, ne
  renvoie jamais un chemin disque.

Aucun repli : un moteur qui n'est pas prêt, une capacité à réparer, une source refusée ou une erreur de compilation sont rendus
tels quels, typés (`presentation_studio_engine_unavailable`, `compile_*`, `invalid_definition`), jamais un résultat HTML.
`compile_runtime_unavailable` (état du moteur) est dit `engine_unavailable` à cette frontière (`docs/remotion-source.md` § 8).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from jarvis.domain.presentation_studio_checks import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_engine import Engine, EngineAvailability
from jarvis.domain.remotion_controls import build_input_props, input_contract
from jarvis.domain.remotion_compile import CompileErrorCode, RemotionCompileError
from jarvis.ports.v2 import DiagnosticSink
from jarvis.ports.remotion import SandboxBindError

TRACE = "core.remotion_player"
REPAIR = "install or repair the Remotion capability (POST /v1/local-capabilities/remotion/install or repair)"


class RemotionPlayerService:
    """`prefabs` : `PrefabService`. `compiler` : `RemotionCompiler` ou `None` (Core sans capacité locale). `sandbox` :
    `RemotionSandboxServer` ou `None`."""

    def __init__(self, prefabs: Any, compiler: Any | None, sandbox: Any | None, *, diagnostics: DiagnosticSink | None = None,
                 run_blocking: Callable[..., Any] = asyncio.to_thread, problem: str | None = None) -> None:
        self._prefabs, self._compiler, self._sandbox, self._diagnostics = prefabs, compiler, sandbox, diagnostics
        self._problem = problem
        self._run_blocking = run_blocking

    # ------------------------------------------------------------------ disponibilité

    def availability(self) -> EngineAvailability:
        """Prêt seulement si le compilateur est câblé, la capacité locale utilisable ET l'écouteur du bac à sable configuré."""

        if self._problem:
            return EngineAvailability(False, self._problem, "fix the Remotion sandbox settings (JARVIS_REMOTION_SANDBOX_HOST / JARVIS_REMOTION_SANDBOX_PORT) and restart Core")
        if self._compiler is None:
            return EngineAvailability(False, "this Core has no Remotion adapter (no local capability store is wired)", REPAIR)
        if self._sandbox is None:
            return EngineAvailability(False, "this Core has no Remotion sandbox listener configured", "set JARVIS_REMOTION_SANDBOX_PORT")
        problem = self._compiler.unavailable_reason()
        if problem is not None:
            return EngineAvailability(False, problem, REPAIR)
        return EngineAvailability(True)

    def sandbox_info(self) -> dict[str, Any]:
        """Pour le Control Center (CSP `frame-src` de la page qui monte le cadre) : l'origine configurée, ouverte ou non."""

        if self._sandbox is None:
            return {"configured": False, "origin": None, "embedder_origin": None, "listening": False}
        return {"configured": True, "origin": self._sandbox.configured_origin, "embedder_origin": self._sandbox.embedder_origin,
                "listening": self._sandbox.origin is not None}

    # ------------------------------------------------------------------ lecture d'une scène

    async def describe(self, prefab_id: str, version: int) -> dict[str, Any]:
        """Descripteur de lecture d'une scène Remotion. Lève : `PresentationStudioError` `engine_unavailable`,
        `PrefabStoreError` (inconnue, altérée, source refusée par les gardes), `RemotionCompileError` (échec typé)."""

        state = self.availability()
        if not state.ready:
            self._trace("describe_unavailable", "Scene Remotion non jouable : le moteur n'est pas pret", level="warning",
                        data={"prefab_id": prefab_id, "version": version, "reason": state.reason[:200]})
            raise PresentationStudioError(C.ENGINE_UNAVAILABLE, f"remotion is unavailable: {state.reason}. Repair: {state.repair}")
        source = await self._prefabs.remotion_source(prefab_id, version)
        manifest = await self._prefabs.manifest(prefab_id, version)
        assert self._compiler is not None and self._sandbox is not None
        try:
            host = await self._run_blocking(self._compiler.compile_host)
            scene = await self._run_blocking(self._compiler.compile_scene, source)
        except RemotionCompileError as exc:
            if exc.code is CompileErrorCode.RUNTIME_UNAVAILABLE:
                raise PresentationStudioError(C.ENGINE_UNAVAILABLE, f"remotion is unavailable: {exc.message}. Repair: {REPAIR}") from exc
            raise
        try:
            origin = await self._sandbox.ensure_started()
        except SandboxBindError as exc:
            self._trace("sandbox_bind_failed", "Ecouteur du bac a sable impossible a ouvrir", level="error",
                        data={"prefab_id": prefab_id, "version": version, "error": str(exc)[:240]})
            raise PresentationStudioError(C.ENGINE_UNAVAILABLE, f"remotion is unavailable: {exc}. Repair: free the port or set "
                                                                "JARVIS_REMOTION_SANDBOX_PORT") from exc
        composition = source.block.composition
        contract = input_contract(manifest, Engine.REMOTION)
        defaults = build_input_props(contract, {}, {})
        self._trace("described", "Scene Remotion prete a etre jouee", data={
            "prefab_id": prefab_id, "version": version, "scene_key": scene.cache_key, "host_key": host.cache_key,
            "reused": scene.reused, "compile_ms": scene.duration_ms, "engine_drift": scene.engine_drift})
        return {
            "kind": "remotion", "engine": "remotion", "prefab_id": prefab_id, "version": version, "title": manifest.title,
            "page_url": f"{origin}/page/{scene.cache_key}/{host.cache_key}", "sandbox_origin": origin,
            "embedder_origin": self._sandbox.embedder_origin,
            "composition": {"id": composition.composition_id, "width": composition.width, "height": composition.height,
                            "fps": composition.fps, "durationInFrames": composition.duration_in_frames},
            # Slice 13 : le contrat des `inputProps` (schémas du manifeste moins ce que Remotion ne porte pas, liste `withheld`) ;
            # la page de scène valide contre lui AVANT de rien envoyer au bac à sable. `defaults` : les inputProps sans valeur.
            "input_contract": contract, "defaults": defaults.input_props,
            "compiled": {"scene": scene.to_public(), "host": {"cache_key": host.cache_key, "reused": host.reused}},
            "engine_drift": scene.engine_drift,
        }

    def _trace(self, kind: str, message: str, *, level: str = "info", data: dict[str, Any]) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(f"{TRACE}.{kind}", message, level=level, data=data)
        except Exception:  # noqa: BLE001 - intentional: a failing journal never breaks a scene's description
            pass


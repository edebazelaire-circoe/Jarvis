"""Import d'un modèle Remotion amont dans UNE présentation (Slice 18, `docs/remotion-import.md`).

Orchestration seulement : l'origine, l'archive, la licence et l'analyse sont du domaine pur (`remotion_upstream`, `remotion_import`),
le téléchargement est un port (`UpstreamFetcher`), la publication est celle de la bibliothèque (`PrefabService.save`). Core est le
seul à parler au réseau, et le code importé n'est jamais exécuté ici : il est lu comme du texte, puis soumis aux gardes de
`SOURCE_GUARDS` (Slice 06) comme toute source.

- `plan` : télécharge, vérifie, analyse, VALIDE (gardes comprises) et rend le plan ; n'écrit rien.
- `import_template` : le même chemin, puis publie une version du prefab propre à la présentation
  (`presentation-studio.p<présentation>.s<scène>`), jamais un prefab de la bibliothèque partagée. Elle ne pose aucune scène dans le
  document : l'épinglage reste au Studio. La promotion vers la bibliothèque est une demande explicite et séparée (Slice 19).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from jarvis.domain.presentation_studio import new_scene_id
from jarvis.domain.presentation_studio_checks import PresentationStudioError
from jarvis.domain.presentation_studio_reload import source_prefab_id
from jarvis.domain.remotion_import import ImportErrorCode as E, ImportPlan, analyse_archive, parse_import_request
from jarvis.domain.remotion_source import EnginePin
from jarvis.domain.remotion_upstream import DEFAULT_ALLOWED_OWNERS, UpstreamRefusal
from jarvis.ports.prefabs import PrefabStoreError
from jarvis.ports.upstream_fetcher import UpstreamFetcher
from jarvis.ports.v2 import DiagnosticSink

#: Codes de plan -> statut HTTP. Une origine refusée est la faute de l'appelant (400/403) ; une panne amont est 502/504 ; une source
#: lue mais inacceptable (licence, dépendance, archive) est 422.
HTTP_STATUS: Mapping[str, int] = {
    E.REQUEST_INVALID: 400, E.ORIGIN_INVALID: 400, E.COMMIT_NOT_PINNED: 400, E.ORIGIN_NOT_ALLOWED: 403,
    E.REDIRECT_REFUSED: 502, E.FETCH_FAILED: 502, E.FETCH_TIMEOUT: 504, E.FETCH_TOO_LARGE: 413,
    "presentation_not_found": 404, "import_storage_failed": 500, "import_busy": 409, E.IMPORT_TIMEOUT: 504,
}


def status_of(code: str) -> int:
    return HTTP_STATUS.get(code, 422)


class RemotionImportService:
    def __init__(self, fetcher: UpstreamFetcher, prefabs: Any, studio: Any, *, engine: Callable[[], EnginePin],
                 allowed_owners: Callable[[], tuple[str, ...]] | None = None, diagnostics: DiagnosticSink | None = None,
                 clock: Callable[[], datetime] | None = None) -> None:
        self._fetcher = fetcher
        self._prefabs = prefabs
        self._studio = studio
        self._engine = engine
        self._owners = allowed_owners or (lambda: DEFAULT_ALLOWED_OWNERS)
        self._diagnostics = diagnostics
        self._clock = clock or (lambda: datetime.now(UTC))
        #: Un import à la fois : une archive tient en mémoire le temps de l'analyse, deux ne se chevauchent pas.
        self._lock = asyncio.Lock()

    def allowed_owners(self) -> tuple[str, ...]:
        return self._owners()

    async def plan(self, raw: object) -> dict[str, Any]:
        plan, _ = await self._plan(raw, need_presentation=False)
        # `guards_passed` : manifeste, bornes et gardes de la Slice 06 ont accepté la source. `compiled: false` : le plan ne compile pas
        # (esbuild peut encore refuser un import que l'analyse n'a pas vu : la compilation est le premier usage, `compile_*`).
        return {"plan": plan.to_public(), "guards_passed": True, "compiled": False, "publishes": False}

    async def import_template(self, raw: object) -> dict[str, Any]:
        plan, request = await self._plan(raw, need_presentation=True, before_fetch=self._require_presentation)
        presentation_id = request.presentation_id
        scene_id = request.scene_id or new_scene_id()
        prefab_id = source_prefab_id(presentation_id, scene_id)
        candidate = dict(plan.candidate)
        candidate["manifest"] = {**candidate["manifest"], "id": prefab_id}
        try:
            publication = await self._prefabs.save(candidate, actor="user", verified_import=True)
        except PrefabStoreError as exc:
            code = "source_guard_refused" if exc.code.value == "invalid_definition" else "import_storage_failed"
            self._refused(code, request, exc.message[:160])
            raise UpstreamRefusal(code, f"the library refused the imported source: {exc.message[:300]}", tuple(exc.errors or ())) from None
        self._trace("core.remotion_import.imported", "Modele amont importe dans la presentation", data={
            "presentation_id": presentation_id, "scene_id": scene_id, "prefab_id": publication.prefab_id,
            "version": publication.version, "upstream": request.origin.name, "commit": request.origin.commit,
            "license": plan.licence["spdx"], "modules": len(plan.modules), "assets": len(plan.assets)})
        return {"imported": True, "scope": "presentation", "presentation_id": presentation_id, "scene_id": scene_id,
                "prefab": {"prefab_id": publication.prefab_id, "version": publication.version, "fingerprint": publication.fingerprint},
                "plan": plan.to_public(), "published_to_library": False}

    async def _require_presentation(self, request: Any) -> None:
        """La présentation existe AVANT tout téléchargement : un import vers une présentation inconnue n'ouvre aucune connexion."""

        try:
            await self._studio.get(request.presentation_id)
        except PresentationStudioError as exc:
            raise UpstreamRefusal("presentation_not_found",
                                  f"presentation {request.presentation_id} is not available: {str(exc)[:160]}") from None

    async def _plan(self, raw: object, *, need_presentation: bool, before_fetch=None):
        if self._lock.locked():
            self._refused("import_busy", None, "another import is running")
            raise UpstreamRefusal("import_busy", "another import is running: retry when it is done")
        async with self._lock:
            request = None
            try:
                request = parse_import_request(raw, allowed_owners=self._owners(), need_presentation=need_presentation)
                if before_fetch is not None:
                    await before_fetch(request)
                fetched = await asyncio.to_thread(self._fetcher.fetch, request.origin)
                engine = self._engine()
                stamp = self._clock()
                plan: ImportPlan = await asyncio.to_thread(analyse_archive, fetched.data, request, engine=engine, imported_at=stamp)
            except UpstreamRefusal as exc:
                self._refused(exc.code, request, exc.message[:160])
                raise
            self._trace("core.remotion_import.planned", "Modele amont analyse", data={
                "upstream": request.origin.name, "commit": request.origin.commit, "license": plan.licence["spdx"],
                "modules": len(plan.modules), "assets": len(plan.assets), "archive_bytes": plan.archive_bytes,
                "redirects": fetched.redirects, "warnings": len(plan.warnings)})
            return plan, request

    def report_failure(self, exc: BaseException) -> None:
        """Défaut inattendu d'une route : durable, niveau error (jamais un 500 sans trace)."""

        self._trace("core.remotion_import.route_failed", "Defaut inattendu dans l'import amont", level="error",
                    data={"error_class": type(exc).__name__})

    def _refused(self, code: str, request: Any, detail: str) -> None:
        data: dict[str, Any] = {"code": code, "detail": detail}
        if request is not None:
            data.update({"upstream": request.origin.name, "commit": request.origin.commit})
        self._trace("core.remotion_import.refused", "Import amont refuse", level="warning", data=data)

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any]) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=dict(data))
        except Exception:  # noqa: BLE001 - un journal indisponible n'annule jamais un import
            pass

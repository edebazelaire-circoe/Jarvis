"""Garde de COMPILATION d'une edition de source Remotion (handoff jarvis-remotion-presentation-integration, Slice 14).

Le rechargement a chaud (`presentation_studio_reload`) valide un candidat de prefab AVANT de rien publier. Pour une scene HTML,
cette validation est structurelle (il n'y a pas d'analyseur JavaScript dans le processus). Pour une scene Remotion il y en a un,
le vrai : le compilateur de la capacite locale (esbuild dans le processus gere de la capacite Remotion, `docs/remotion-source.md`
§ 5). Ce module est la couture entre les deux : il demande au constructeur de compiler la source deja validee (chemins, gardes
d'isolation `SOURCE_GUARDS`, bornes : `parse_candidate`) et rend un refus TYPE, jamais une exception :

- `presentation_studio_source_build_failed` : la source ne compile pas (syntaxe, import refuse, export par defaut manquant, delai,
  bundle trop gros) ; `diagnostics` = `fichier:ligne:colonne texte`, `fichier` etant un chemin de la source ;
- `presentation_studio_engine_unavailable` : le moteur n'est pas pret (capacite a reparer) ; on ne valide pas a l'aveugle et on ne
  bascule JAMAIS sur un autre moteur.

Rien n'est publie, epingle ni patche quand le garde refuse : la version precedente continue de jouer. La compilation d'un contenu
deja vu est gratuite (meme contenu = meme cle de cache), et celle d'une source qui passe rechauffe le cache que le Player lira.
Les journaux ne portent ni texte de source ni valeur : un code, des comptes, la cle de cache.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from jarvis.domain.presentation_studio_checks import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_remotion_edit import format_diagnostics
from jarvis.domain.remotion_compile import RemotionCompileError
from jarvis.domain.remotion_source import RemotionSource
from jarvis.ports.prefabs import PrefabStoreError
from jarvis.ports.v2 import DiagnosticSink



class SourceBuilder(Protocol):
    """Ce que le garde demande au moteur (`RemotionPlayerService.check_build`) : compiler la source (et l'hote partage) et rendre la
    forme publique du bundle de la scene. Leve `PresentationStudioError` (`engine_unavailable`) ou `RemotionCompileError`."""

    async def check_build(self, source: RemotionSource) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class BuildRefusal:
    code: C
    message: str
    diagnostics: tuple[Mapping[str, Any], ...] = ()


class RemotionBuildGate:
    def __init__(self, builder: SourceBuilder | None, *, diagnostics: DiagnosticSink | None = None) -> None:
        self._builder, self._diagnostics = builder, diagnostics

    async def check(self, source: RemotionSource, *, scene_id: str) -> BuildRefusal | None:
        """`None` : la source compile. Sinon le refus type (rien n'a ete publie)."""

        if self._builder is None:
            return self._refuse(C.ENGINE_UNAVAILABLE, "remotion is unavailable: this Core has no Remotion adapter wired, so a "
                                "scene source cannot be built (no other engine is used instead)", scene_id)
        try:
            built = await self._builder.check_build(source)
        except RemotionCompileError as exc:
            diagnostics = tuple(row.to_dict() for row in exc.diagnostics)
            detail = format_diagnostics(diagnostics)
            code = C.ENGINE_UNAVAILABLE if exc.code.value == "compile_runtime_unavailable" else C.SOURCE_BUILD_FAILED
            text = f"{exc.code.value}: {exc.message}" + (f" - {detail}" if detail else "")
            return self._refuse(code, text, scene_id, diagnostics, compile_code=exc.code.value)
        except PresentationStudioError as exc:  # the engine says it is not ready (capability to repair): typed, never a fallback
            return self._refuse(exc.code, exc.message, scene_id)
        except PrefabStoreError as exc:  # a guard added since refuses the bytes just composed: the candidate was not buildable
            return self._refuse(C.SOURCE_INVALID, f"{exc.code.value}: {exc.message}", scene_id)
        self._trace("core.presentation_studio.reload_built", "Source de scene compilee avant publication", "info",
                    {"scene_id": scene_id, "cache_key": built.get("cache_key"), "reused": built.get("reused"),
                     "duration_ms": built.get("duration_ms"), "engine_drift": built.get("engine_drift")})
        return None

    def _refuse(self, code: C, message: str, scene_id: str, diagnostics: tuple[Mapping[str, Any], ...] = (),
                compile_code: str | None = None) -> BuildRefusal:
        self._trace("core.presentation_studio.reload_build_refused", "Source de scene non compilable : rien n'est publie", "warning",
                    {"scene_id": scene_id, "code": code.value, "compile_code": compile_code, "diagnostics": len(diagnostics)})
        return BuildRefusal(code, message, diagnostics)

    def _trace(self, kind: str, message: str, level: str, data: Mapping[str, Any]) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=dict(data))
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal never changes the verdict of a build
            pass

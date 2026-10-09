"""Contrat de compilation d'une scène Remotion : du TSX à un bundle navigateur pour le Player
(handoff jarvis-remotion-presentation-integration, Slice 05 ; `docs/remotion-source.md` §5).

Pur : types, codes d'échec typés, clés de cache, forme publique du résultat. Le processus (Node + esbuild du
verrou de la capacité Remotion), le délai et le cache disque vivent dans `jarvis.adapters.remotion_compiler`.

Deux cibles, un seul React :

- `host` : `host.js`, compilé **une fois** par jeu de paquets installés. Il expose `globalThis.__JARVIS_HOST__`
  (`react`, `react/jsx-runtime`, `react-dom`, `react-dom/client`, `remotion`, `@remotion/player`).
- `scene` : `scene.js`, une IIFE `var JarvisScene = {component}` dont les imports « nus » autorisés
  (`SCENE_ALLOWED_IMPORTS`) sont résolus vers ces globaux, jamais embarqués. Les imports relatifs ne sortent pas de
  la source. La scène ne lit ni disque, ni `node_modules`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any

COMPILE_CONTRACT = 1
SCENE_FILE = "scene.js"
HOST_FILE = "host.js"
RESULT_FILE = "compile.json"
PUBLIC_DIR = "public"
HOST_GLOBAL = "__JARVIS_HOST__"
SCENE_GLOBAL = "JarvisScene"
#: Imports « nus » qu'une scène peut écrire. Toute autre chose (`fs`, `node:*`, une URL, un paquet non installé) est
#: refusée à la compilation ; la Slice 06 peut resserrer cette liste (jamais l'élargir sans l'ajouter au `host`).
SCENE_ALLOWED_IMPORTS = ("react", "react/jsx-runtime", "react/jsx-dev-runtime", "remotion")
HOST_EXPOSED_MODULES = ("react", "react/jsx-runtime", "react/jsx-dev-runtime", "react-dom", "react-dom/client",
                        "remotion", "@remotion/player")
MAX_SCENE_BUNDLE_BYTES = 4 * 1024 * 1024
MAX_HOST_BUNDLE_BYTES = 8 * 1024 * 1024
SCENE_TIMEOUT_S = 60.0
HOST_TIMEOUT_S = 120.0
#: Entrées de cache gardées au plus (les plus récemment utilisées) et octets au plus.
CACHE_KEEP_ENTRIES = 64
CACHE_MAX_BYTES = 1024 * 1024 * 1024
CACHE_KEY = re.compile(r"(?:scene|host)-[0-9a-f]{32}\Z")
MAX_DIAGNOSTICS = 20


class CompileTarget(StrEnum):
    SCENE = "scene"
    HOST = "host"


class CompileErrorCode(StrEnum):
    #: La capacité Remotion n'est pas prête (non installée, à réparer, désactivée) : réparation = capacité locale.
    RUNTIME_UNAVAILABLE = "compile_runtime_unavailable"
    #: La source est refusée avant tout processus (chemins, bornes, manifeste).
    INVALID_SOURCE = "compile_invalid_source"
    #: Erreur de syntaxe ou de type de l'utilisateur : `diagnostics` donne fichier, ligne, colonne.
    SOURCE_ERROR = "compile_source_error"
    #: Import hors liste, hors de la source ou introuvable.
    IMPORT_REFUSED = "compile_import_refused"
    #: Le point d'entrée n'exporte pas de composant par défaut.
    ENTRY_INVALID = "compile_entry_invalid"
    TIMEOUT = "compile_timeout"
    OUTPUT_TOO_LARGE = "compile_output_too_large"
    #: Node ou esbuild a échoué ou n'a rien rendu d'exploitable (ni code utilisateur ni délai).
    COMPILER_FAILED = "compile_compiler_failed"
    #: Le cache ne peut pas être écrit ou relu (disque, droits).
    CACHE_IO = "compile_cache_io"


#: Statut HTTP conseillé aux routes de la Slice 10 (erreur de l'utilisateur ou état à réparer : 4xx ; panne : 5xx).
COMPILE_HTTP_STATUS = {
    CompileErrorCode.RUNTIME_UNAVAILABLE: 409, CompileErrorCode.INVALID_SOURCE: 400, CompileErrorCode.SOURCE_ERROR: 422,
    CompileErrorCode.IMPORT_REFUSED: 422, CompileErrorCode.ENTRY_INVALID: 422, CompileErrorCode.TIMEOUT: 504,
    CompileErrorCode.OUTPUT_TOO_LARGE: 422, CompileErrorCode.COMPILER_FAILED: 500, CompileErrorCode.CACHE_IO: 500,
}


@dataclass(frozen=True, slots=True)
class CompileDiagnostic:
    """Un constat du compilateur. `file` est un chemin **de la source** (`src/Scene.tsx`), jamais un chemin disque."""

    file: str
    line: int
    column: int
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"file": self.file, "line": self.line, "column": self.column, "text": self.text}


class RemotionCompileError(Exception):
    """Échec typé. `message` tient en une phrase, sans chemin absolu ; `diagnostics` ≤ `MAX_DIAGNOSTICS`."""

    def __init__(self, code: CompileErrorCode | str, message: str, *, diagnostics: tuple[CompileDiagnostic, ...] = ()) -> None:
        self.code = CompileErrorCode(code)
        self.message = message if len(message) <= 300 else message[:299] + "…"
        self.diagnostics = tuple(diagnostics[:MAX_DIAGNOSTICS])
        self.status = COMPILE_HTTP_STATUS[self.code]
        super().__init__(f"{self.code.value}: {self.message}")

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code.value, "message": self.message, "diagnostics": [d.to_dict() for d in self.diagnostics]}


@dataclass(frozen=True, slots=True)
class InstalledEngine:
    """Ce que la capacité a réellement installé (`install-record.json`) : fait l'identité de la compilation."""

    remotion_version: str
    react_version: str
    lock_sha256: str
    #: SHA-256 de `runtime-host.mjs` tel qu'installé : l'identité de la LOGIQUE de compilation. Une mise à niveau du
    #: compilateur (même arbre npm) ne réutilise jamais un bundle produit par l'ancien.
    compiler_sha256: str

    def to_dict(self) -> dict[str, str]:
        return {"remotion_version": self.remotion_version, "react_version": self.react_version,
                "lock_sha256": self.lock_sha256, "compiler_sha256": self.compiler_sha256}


def _key(prefix: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"{prefix}-{hashlib.sha256(canonical.encode('ascii')).hexdigest()[:32]}"


def scene_cache_key(source_digest: str, entry: str, installed: InstalledEngine, *, allowed_imports: tuple[str, ...] = SCENE_ALLOWED_IMPORTS,
                    minify: bool = True) -> str:
    """Clé de cache d'une scène : contenu de la source (pas son id ni sa version de prefab), point d'entrée, arbre installé,
    liste d'imports et minification. Deux versions de prefab au même contenu partagent la même sortie."""

    return _key("scene", {"contract": COMPILE_CONTRACT, "digest": source_digest, "entry": entry, "engine": installed.to_dict(),
                          "imports": sorted(allowed_imports), "minify": bool(minify)})


def host_cache_key(installed: InstalledEngine, *, minify: bool = True) -> str:
    return _key("host", {"contract": COMPILE_CONTRACT, "engine": installed.to_dict(), "exposed": sorted(HOST_EXPOSED_MODULES),
                         "minify": bool(minify)})


@dataclass(frozen=True, slots=True)
class CompiledFile:
    """Un fichier de sortie : chemin relatif à l'entrée de cache, taille, SHA-256."""

    path: str
    bytes: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "bytes": self.bytes, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class CompiledArtifact:
    """Résultat d'une compilation (ou de sa relecture dans le cache). `to_public()` est la seule forme à mettre dans un
    contexte de Board, une réponse HTTP ou un journal : jamais de chemin absolu, jamais de port."""

    target: CompileTarget
    cache_key: str
    files: tuple[CompiledFile, ...]
    engine_installed: InstalledEngine
    source_digest: str | None = None
    engine_pinned: dict[str, str] | None = None
    reused: bool = False
    duration_ms: int = 0
    warnings: int = 0

    @property
    def engine_drift(self) -> bool:
        """Vrai si la source a été écrite pour un autre arbre que celui installé. Signalé, jamais corrigé en silence."""

        pinned = self.engine_pinned
        if pinned is None:
            return False
        return (pinned.get("version") != self.engine_installed.remotion_version
                or pinned.get("react_version") != self.engine_installed.react_version
                or pinned.get("lock_sha256") != self.engine_installed.lock_sha256)

    @property
    def entry_file(self) -> str:
        return SCENE_FILE if self.target is CompileTarget.SCENE else HOST_FILE

    def to_public(self) -> dict[str, Any]:
        return {"contract": COMPILE_CONTRACT, "target": self.target.value, "cache_key": self.cache_key,
                "entry_file": self.entry_file, "files": [f.to_dict() for f in self.files],
                "source_digest": self.source_digest, "engine_installed": self.engine_installed.to_dict(),
                "engine_pinned": self.engine_pinned, "engine_drift": self.engine_drift, "reused": self.reused,
                "duration_ms": self.duration_ms, "warnings": self.warnings}

    def to_record(self) -> dict[str, Any]:
        """Ce qui est écrit dans `compile.json` du cache (sans `reused`, qui dépend de la lecture)."""

        record = self.to_public()
        record.pop("reused")
        record.pop("engine_drift")
        return record

    @classmethod
    def from_record(cls, raw: object) -> CompiledArtifact | None:
        """Relit `compile.json` ; `None` si la forme n'est pas la nôtre (le cache est alors reconstruit)."""

        try:
            assert isinstance(raw, dict) and raw["contract"] == COMPILE_CONTRACT
            engine = raw["engine_installed"]
            return cls(CompileTarget(raw["target"]), str(raw["cache_key"]),
                       tuple(CompiledFile(str(f["path"]), int(f["bytes"]), str(f["sha256"])) for f in raw["files"]),
                       InstalledEngine(str(engine["remotion_version"]), str(engine["react_version"]), str(engine["lock_sha256"]),
                                       str(engine["compiler_sha256"])),
                       raw.get("source_digest"), raw.get("engine_pinned"), True, int(raw.get("duration_ms", 0)),
                       int(raw.get("warnings", 0)))
        except (AssertionError, KeyError, TypeError, ValueError):
            return None

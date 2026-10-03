"""Ports de la bibliothèque de prefabs (handoff jarvis-scene-window-prefab-foundation, Slice 02).

- `PrefabLibrary` : fichiers des versions, sur deux racines — le paquet
  (`jarvis/prefabs/base/`, lecture seule) et la bibliothèque de la racine de
  données (`<data_root>/prefabs/`). Adaptateur :
  `jarvis.adapters.file_prefab_library.FilePrefabLibrary`. Il lit, publie et
  balaie ; il ne valide ni ne décide rien (le service le fait, avec le
  domaine `jarvis.domain.prefab`).
- `PrefabInstanceValidator` : validation d'un bloc d'instance de scène par
  Core (`PrefabService.validate_instance`), branché sur `SceneService` à la
  Slice 04.
- `PrefabStoreError` : refus ou panne codés, mêmes codes pour le service, les
  routes (Slices 03/07) et le MCP.
- `PrefabRuntimeSource` : le runtime injecté dans chaque cadre
  (`jarvis/prefabs/runtime/shim.js`, `shell.css`), joint au paquet d'une
  version par `PrefabService.bundle` (Slice 03). Adaptateur :
  `jarvis.adapters.file_prefab_library.FilePrefabRuntime`.

Contrat : `docs/prefabs.md` › *Storage and library*, *Modules and validation authority*.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from jarvis.domain.prefab import MAX_ERROR_CHARS, MAX_ERRORS, PrefabBundle, PrefabInstanceRef, Publication


class PrefabStoreErrorCode(StrEnum):
    UNKNOWN_PREFAB = "unknown_prefab"
    UNKNOWN_VERSION = "unknown_version"
    #: Version dont les fichiers ne correspondent plus à `publication.json` (ou illisibles) : refusée.
    TAMPERED = "tampered"
    #: Publication sur une version déjà publiée : jamais réécrite.
    VERSION_EXISTS = "version_exists"
    #: `save` sur un id `jarvis.*` : seule la porte `edit_base` publie une base.
    BASE_PROTECTED = "base_protected"
    #: Porte d'édition de base non franchie (conditions 1-4 de `docs/prefabs.md`).
    BASE_EDIT_UNCONFIRMED = "base_edit_unconfirmed"
    INVALID_DEFINITION = "invalid_definition"
    #: Disque, lien/jonction refusé, racine indisponible : panne, pas une demande refusée.
    STORAGE_IO = "storage_io"


#: Statut HTTP de chaque code, pour les routes des Slices 03/07.
PREFAB_HTTP_STATUS: Mapping[PrefabStoreErrorCode, int] = {
    PrefabStoreErrorCode.UNKNOWN_PREFAB: 404,
    PrefabStoreErrorCode.UNKNOWN_VERSION: 404,
    PrefabStoreErrorCode.TAMPERED: 409,
    PrefabStoreErrorCode.VERSION_EXISTS: 409,
    PrefabStoreErrorCode.BASE_PROTECTED: 403,
    PrefabStoreErrorCode.BASE_EDIT_UNCONFIRMED: 403,
    PrefabStoreErrorCode.INVALID_DEFINITION: 400,
    PrefabStoreErrorCode.STORAGE_IO: 500,
}


class PrefabStoreError(Exception):
    """Refus ou panne codés ; `message` ≤ `MAX_ERROR_CHARS`, `errors` ≤ `MAX_ERRORS` (définition refusée)."""

    def __init__(self, code: PrefabStoreErrorCode | str, message: str, *, errors: tuple[str, ...] = ()) -> None:
        self.code = PrefabStoreErrorCode(code)
        self.message = message if len(message) <= MAX_ERROR_CHARS else message[: MAX_ERROR_CHARS - 1] + "…"
        self.errors = tuple(errors[:MAX_ERRORS])
        self.status = PREFAB_HTTP_STATUS[self.code]
        super().__init__(f"{self.code.value}: {self.message}")


class PrefabRoot(StrEnum):
    #: `jarvis/prefabs/base/` : livré, jamais écrit à l'exécution.
    PACKAGE = "package"
    #: `<data_root>/prefabs/` : une bibliothèque par installation (par racine de données).
    DATA = "data"


@dataclass(frozen=True, slots=True)
class ScannedVersion:
    root: PrefabRoot
    prefab_id: str
    version: int
    #: `(nom, taille, mtime_ns)` des fichiers présents : clé de cache bon marché, pas une empreinte.
    signature: tuple[tuple[str, int, int], ...]


@dataclass(frozen=True, slots=True)
class ScanProblem:
    root: PrefabRoot
    #: Chemin relatif à la racine (`<id>/<version>`), jamais absolu.
    path: str
    reason: str


@dataclass(frozen=True, slots=True)
class PrefabScan:
    versions: tuple[ScannedVersion, ...] = ()
    problems: tuple[ScanProblem, ...] = ()


@dataclass(frozen=True, slots=True)
class StoredFiles:
    """Textes bruts d'une version ; `publication` est `None` si le fichier manque."""

    manifest: str
    template: str
    style: str
    behavior: str
    publication: str | None


@dataclass(frozen=True, slots=True)
class SweepReport:
    removed: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()


class PrefabLibrary(Protocol):
    """Fichiers des versions publiées ; synchrone (le service l'appelle hors de la boucle)."""

    def scan(self) -> PrefabScan: ...

    def read_version(self, root: PrefabRoot, prefab_id: str, version: int) -> StoredFiles: ...

    def publish(self, bundle: PrefabBundle, publication: Publication) -> str:
        """Écrit une version neuve dans la racine de données, atomiquement ; rend `<id>/<version>`.

        `PrefabStoreError(version_exists)` si la version existe, `storage_io` sinon.
        """

    def sweep(self) -> SweepReport: ...


@dataclass(frozen=True, slots=True)
class InstanceValidation:
    """Issue de `validate_instance` : valeurs complétées de leurs défauts si `ok`, sinon code et détail ≤ 300."""

    ok: bool
    props: Mapping[str, Any] = field(default_factory=dict)
    data: Mapping[str, Any] = field(default_factory=dict)
    code: PrefabStoreErrorCode | None = None
    detail: str = ""


class PrefabInstanceValidator(Protocol):
    async def validate_instance(self, ref: PrefabInstanceRef) -> InstanceValidation: ...


@dataclass(frozen=True, slots=True)
class PrefabRuntimeFiles:
    """Textes du runtime partagé par tous les cadres (Slice 03)."""

    shim: str
    shell_css: str


class PrefabRuntimeSource(Protocol):
    """Runtime des cadres ; synchrone (appelé hors de la boucle). `PrefabStoreError(storage_io)` s'il manque."""

    def read_runtime(self) -> PrefabRuntimeFiles: ...

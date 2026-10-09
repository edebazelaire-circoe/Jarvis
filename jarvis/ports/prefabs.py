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

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from jarvis.domain.prefab import MAX_ERRORS, PrefabBundle, PrefabInstanceRef, Publication, clip_message


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
    #: Un id a atteint ses versions vivantes (`MAX_VERSIONS_PER_ID`) ou le numéro 9999 (Slice 01a) : recours, un nouvel id.
    VERSION_LIMIT = "version_limit"
    #: La bibliothèque a atteint `MAX_PREFAB_IDS` ids (ou la part des ids de rétention) et rien ne peut être archivé.
    ID_LIMIT = "id_limit"


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
    PrefabStoreErrorCode.VERSION_LIMIT: 409,
    PrefabStoreErrorCode.ID_LIMIT: 409,
}


class PrefabStoreError(Exception):
    """Refus ou panne codés ; `message` ≤ `MAX_ERROR_CHARS`, `errors` ≤ `MAX_ERRORS` (définition refusée)."""

    def __init__(self, code: PrefabStoreErrorCode | str, message: str, *, errors: tuple[str, ...] = ()) -> None:
        self.code = PrefabStoreErrorCode(code)
        self.message = clip_message(message)
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
    #: `(racine, id, version)` de **chaque** dossier de version numéroté vu, catalogué ou non (vide, sans
    #: manifeste, lien, au-delà de la borne par id) : un numéro occupé ne s'attribue jamais à une publication.
    #: Les versions **archivées** (`retire`) y figurent aussi : un numéro retiré ne se réattribue jamais.
    version_folders: tuple[tuple[PrefabRoot, str, int], ...] = ()


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

    def retire(self, prefab_id: str, version: int) -> str:
        """Déplace une version de la racine de données vers l'archive (`prefabs/.archive/<id>/<version>`), en un
        seul renommage : ni copie à moitié faite ni donnée détruite, la version sort du catalogue mais son numéro
        reste occupé. Rend `<id>/<version>`. Jamais le paquet ni un id hors de l'espace de rétention
        (`invalid_definition`). `unknown_version` si elle n'existe pas, `storage_io`
        sinon.
        """


class PrefabPinRegistry(Protocol):
    """Qui épingle quelles versions (Slice 01a) : implémenté par le Studio, que la couche prefab n'importe pas.

    Interrogé par `PrefabService` **sous son verrou d'écriture** avant tout archivage, donc rapide (en mémoire,
    sans attente externe) : sans réponse en `PIN_REGISTRY_TIMEOUT_SECONDS` (5 s) l'appel est annulé et rien
    n'est archivé. Doit rendre **toutes** les versions épinglées (variante, variante locale, modèle, objet de
    scène, scène globale vivante et cadres que l'hôte peut recharger, document de scène du Studio, pile
    d'annulation). **Chaque** id demandé est une clé de la réponse (aucun épinglage = ensemble vide) et ses
    versions sont des entiers `1..9999` : une clé absente, un type inattendu ou une exception est une réponse
    partielle ou invalide, rien n'est archivé (`core.prefab.retention_failed`).
    """

    async def pinned_versions(self, prefab_ids: Collection[str]) -> Mapping[str, frozenset[int]]: ...


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

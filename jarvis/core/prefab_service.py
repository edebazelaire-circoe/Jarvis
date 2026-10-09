"""Catalogue des prefabs et autorité de validation dans Core (handoff
jarvis-scene-window-prefab-foundation, Slice 02).

`PrefabService` est la seule autorité sur les définitions et les instances
(`docs/prefabs.md` › *Modules and validation authority*) :

- **catalogue** = union du paquet et de la racine de données, relu par
  `PrefabLibrary.scan` ; chaque version est relue et son empreinte
  **recalculée** (`jarvis.domain.prefab`). Écart avec `publication.json`,
  manifeste invalide, fichier manquant ou illisible -> version `tampered`,
  refusée pour toute instance neuve (`core.prefab.tampered`). Même
  `(id, version)` dans les deux racines : le paquet gagne
  (`core.prefab.version_conflict`). Cache par `(racine, id, version)` et
  signature `(taille, mtime)` des fichiers : relecture au listage
  (`search`), après chaque publication, et quand une version demandée
  manque ;
- **save** : nouvel id -> `custom` (ou `fork` avec `derived_from`, qui doit
  exister et être sain), sous la borne `MAX_PREFAB_IDS` dans les deux cas ;
  id custom existant -> `revision` v+1 ; id `jarvis.*` -> `base_protected`.
  Core attribue la version (le nom du dossier) : la `version` du candidat
  est remplacée, avant l'empreinte, par le plus grand numéro **occupé** + 1
  (dossier de version numéroté dans l'une ou l'autre racine, catalogué ou
  non : un dossier vide ou refusé ne fait jamais échouer les publications
  suivantes en `version_exists`) ;
- **rétention** (Slice 01a, ids `presentation-studio.*` seulement) : à partir de
  `RETENTION_TRIGGER_VERSIONS` versions vivantes, avant la borne dure
  `MAX_VERSIONS_PER_ID` (qui compte les versions **vivantes**), `_publish`
  archive (`PrefabLibrary.retire`, renommage vers `prefabs/.archive/`) les
  versions saines que le `PrefabPinRegistry` n'épingle pas, hors les
  `RETENTION_KEEP_LAST` dernières ; un id neuf du Studio au plafond d'ids
  archive en entier le plus ancien id inutilisé. Tout sous `_write_lock`.
  Sans registre, ou s'il échoue : rien n'est archivé, borne visible
  (`version_limit` / `id_limit`). Numéros jamais réattribués (l'archive compte
  dans `_occupied`) ; au-delà de 9999, `version_limit` ;
- **edit_base** : porte d'intention explicite (conditions 1-4 du contrat),
  acteur `brain` seulement (l'UI n'édite jamais une base).
  Le témoin `user_utterance_witness(texte) -> event_id | None` est injecté ;
  Slice 07 : `v2_app` branche `ConversationUtteranceWitness`
  (`jarvis/core/prefab_witness.py`, Conversation Events). Sans témoin, ou un
  témoin qui ne trouve rien ou échoue, l'édition est refusée
  (`base_edit_unconfirmed`) ;
- **validate_instance** (port `PrefabInstanceValidator`, branché sur
  `SceneService` à la Slice 04) : version existante et saine, `props`/`data`
  validés et complétés de leurs défauts, détail ≤ 300 caractères ;
- **bundle** (Slice 03) : ce qu'un cadre exécute — manifeste, sources et le
  runtime partagé (`PrefabRuntimeSource` : `shim.js`, `shell.css`) avec sa
  version (empreinte des deux textes). Runtime absent ou illisible ->
  `storage_io` : un cadre sans runtime ne peut pas tourner, on le dit.

Les appels au magasin (disque) passent par `asyncio.to_thread` ; les
publications sont sérialisées par un verrou. Miroir diagnostic
(`core.prefab.*`) : ids, versions, codes, jamais le texte de l'utilisateur.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from jarvis.domain.prefab import (
    MAX_MANIFEST_BYTES, MAX_PREFAB_IDS, MAX_RETENTION_PREFAB_IDS, MAX_USER_REQUEST_CHARS, MAX_VERSION,
    MAX_VERSIONS_PER_ID, RETENTION_KEEP_LAST, RETENTION_TRIGGER_VERSIONS, is_retention_id,
    MIN_USER_REQUEST_CHARS, WITNESS_PREFIX, BaseEditRecord, CreatorActor, PrefabBundle, PrefabClass,
    PrefabDefinitionError, PrefabInstanceRef, PrefabManifest, PrefabRef, Provenance, ProvenanceOrigin, Publication,
    clip_message, decode_json_text, format_published_at, is_prefab_id, parse_candidate, parse_stored_bundle, prefab_class, renumber,
    validate_value,
)
from jarvis.domain.remotion_source import RemotionSource, RemotionSourceError, parse_source
from jarvis.core.prefab_retention import (
    PIN_REGISTRY_TIMEOUT_SECONDS, RETENTION_ID_GRACE_SECONDS, checked_pins, retirable_versions,
)
from jarvis.core.prefab_witness import quote_problem
from jarvis.domain.prefab_catalog import SemanticType, matches as catalog_matches
from jarvis.domain.presentation_studio_engine import Engine
from jarvis.domain.prompt_registry import fingerprint
from jarvis.domain.v2 import utc_now
from jarvis.ports.prefabs import (
    InstanceValidation, PrefabLibrary, PrefabPinRegistry, PrefabRoot, PrefabRuntimeSource, PrefabStoreError,
    PrefabStoreErrorCode,
    ScannedVersion,
)
from jarvis.ports.v2 import DiagnosticSink

#: Témoin de la porte d'édition de base : l'id de l'événement de conversation
#: où l'utilisateur a dit `user_request`, ou `None`.
UserUtteranceWitness = Callable[[str], Awaitable[str | None]]
DEFAULT_SEARCH_LIMIT = 20
MAX_SEARCH_LIMIT = 50
MAX_QUERY_CHARS = 120
#: Longueur de la version du runtime (préfixe de l'empreinte de `shim.js` + `shell.css`).
RUNTIME_VERSION_CHARS = 16
#: Acteurs qui publient par `save` (le système ne publie que les bases livrées).
SAVE_ACTORS = frozenset({CreatorActor.BRAIN, CreatorActor.USER})
#: Seul acteur de la porte d'édition de base (route `base-edits` : `actor: "brain"`) ; l'UI n'édite jamais une base.
BASE_EDIT_ACTORS = frozenset({CreatorActor.BRAIN})
_C = PrefabStoreErrorCode


class VersionStatus(StrEnum):
    OK = "ok"
    #: Fichiers différents de leur publication, manifeste invalide, fichier manquant.
    TAMPERED = "tampered"
    #: Disque ou chemin refusé à la lecture : panne, pas une falsification.
    UNREADABLE = "unreadable"


@dataclass(frozen=True, slots=True)
class CatalogVersion:
    root: PrefabRoot
    prefab_id: str
    version: int
    status: VersionStatus
    bundle: PrefabBundle | None = None
    publication: Publication | None = None
    fingerprint: str | None = None
    #: Pourquoi la version est refusée (≤ 300), vide si `ok`.
    problem: str = ""

    @property
    def ok(self) -> bool:
        return self.status is VersionStatus.OK

    @property
    def manifest(self) -> PrefabManifest | None:
        return None if self.bundle is None else self.bundle.manifest

    def history_row(self) -> dict[str, Any]:
        row: dict[str, Any] = {"version": self.version, "root": self.root.value, "status": self.status.value}
        if self.publication is not None:
            row.update(self.publication.provenance.to_dict())
            row["published_at"] = self.publication.published_at
            row["fingerprint"] = self.publication.fingerprint
        if self.problem:
            row["problem"] = self.problem
        return row


@dataclass(frozen=True, slots=True)
class PrefabSummary:
    """Ligne de catalogue (`GET /v1/prefabs`, `prefab_search`)."""

    prefab_id: str
    latest_version: int
    versions: tuple[int, ...]
    title: str
    family: str
    prefab_class: PrefabClass
    description: str
    input_names: tuple[str, ...]
    event_names: tuple[str, ...]
    base_edited: bool
    #: Contrat sémantique de la dernière version (`PrefabManifest.catalog_view`). Hors de `to_dict()` : les lignes que lit
    #: le cerveau (`prefab_search`) ne grossissent pas ; le Control Center le demande avec `?catalog=1`.
    catalog: dict[str, Any] | None = None

    def to_dict(self, *, catalog: bool = False) -> dict[str, Any]:
        body = {"id": self.prefab_id, "latest_version": self.latest_version, "versions": list(self.versions),
                "title": self.title, "family": self.family, "class": self.prefab_class.value,
                "description": self.description, "input_names": list(self.input_names),
                "event_names": list(self.event_names), "base_edited": self.base_edited}
        if catalog:
            body["catalog"] = self.catalog
        return body


@dataclass(frozen=True, slots=True)
class PrefabDetail:
    """Une version saine, sa publication et l'historique de l'id (chaîne de provenance)."""

    entry: CatalogVersion
    latest_version: int
    history: tuple[dict[str, Any], ...]

    def to_dict(self, *, include_source: bool = False, catalog: bool = False) -> dict[str, Any]:
        bundle, publication = self.entry.bundle, self.entry.publication
        assert bundle is not None and publication is not None
        body: dict[str, Any] = {"id": self.entry.prefab_id, "version": self.entry.version,
                                "latest_version": self.latest_version,
                                "class": prefab_class(self.entry.prefab_id).value,
                                "manifest": dict(bundle.manifest.raw), "publication": publication.to_dict(),
                                "history": list(self.history)}
        if catalog:
            body["catalog"] = bundle.manifest.catalog_view(parameters=True)
        if include_source:
            body["files"] = bundle.files()
            if bundle.is_remotion:  # catalogue entries hold no contents: sizes and digests only
                body["inventory"] = {path: {"bytes": size, "sha256": digest} for path, (size, digest) in bundle.inventory.items()}
        return body


@dataclass(frozen=True, slots=True)
class CandidateValidation:
    ok: bool
    errors: tuple[str, ...] = ()
    fingerprint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"ok": self.ok, "errors": list(self.errors)}
        if self.fingerprint is not None:
            body["fingerprint"] = self.fingerprint
        return body


def _definition_error(exc: PrefabDefinitionError, what: str = "candidate") -> PrefabStoreError:
    return PrefabStoreError(_C.INVALID_DEFINITION, f"{what} refused: {exc.errors[0]}", errors=exc.errors)


class PrefabService:
    """Voir l'en-tête du module."""

    def __init__(self, library: PrefabLibrary, *, user_utterance_witness: UserUtteranceWitness | None = None,
                 diagnostics: DiagnosticSink | None = None, clock: Callable[[], datetime] = utc_now,
                 runtime: PrefabRuntimeSource | None = None, pin_registry: PrefabPinRegistry | None = None) -> None:
        self._library = library
        self._runtime = runtime
        self._pin_registry = pin_registry
        self._witness = user_utterance_witness
        self._diagnostics = diagnostics
        self._clock = clock
        self._write_lock = asyncio.Lock()
        self._refresh_lock = asyncio.Lock()
        #: `(racine, id, version)` -> (signature des fichiers, version chargée).
        self._cache: dict[tuple[PrefabRoot, str, int], tuple[tuple, CatalogVersion]] = {}
        #: `(id, version)` -> version retenue (le paquet gagne).
        self._catalog: dict[tuple[str, int], CatalogVersion] = {}
        #: id -> plus grand numéro de dossier de version vu (deux racines, catalogué ou non).
        self._occupied: dict[str, int] = {}
        self._scanned = False
        #: Diagnostics déjà émis (une fois par fait, pas à chaque relecture).
        self._reported: set[tuple[Any, ...]] = set()

    # ------------------------------------------------------------ cycle de vie

    async def start(self) -> None:
        """Balaie les `.staging-*` d'un arrêt brutal puis charge le catalogue. Ne lève jamais."""

        try:
            report = await asyncio.to_thread(self._library.sweep)
        except Exception as exc:  # noqa: BLE001 - intentional: a failed sweep never blocks Core; traced below
            self._trace("core.prefab.sweep_failed", "Balayage des publications interrompues impossible",
                        level="warning", data={"error": clip_message(f"{type(exc).__name__}: {exc}")})
        else:
            if report.removed:
                self._trace("core.prefab.swept", "Publications de prefab interrompues retirées",
                            data={"removed": list(report.removed)})
            if report.failed:
                self._trace("core.prefab.sweep_failed", "Publications de prefab interrompues non retirées",
                            level="warning", data={"failed": list(report.failed)})
        try:
            await self._refresh()
        except Exception as exc:  # noqa: BLE001 - intentional: the catalogue stays empty; each request re-scans
            self._trace("core.prefab.catalog_unavailable", "Catalogue des prefabs illisible au démarrage",
                        level="error", data={"error": clip_message(f"{type(exc).__name__}: {exc}")})
            return
        healthy = sum(1 for entry in self._catalog.values() if entry.ok)
        self._trace("core.prefab.catalog_loaded", "Catalogue des prefabs chargé",
                    data={"versions": len(self._catalog), "healthy": healthy,
                          "ids": len({key[0] for key in self._catalog})})

    # ------------------------------------------------------------ catalogue

    async def _refresh(self) -> None:
        async with self._refresh_lock:
            scan = await asyncio.to_thread(self._library.scan)
            for problem in scan.problems:
                self._trace_once(("scan", problem.root, problem.path, problem.reason), "core.prefab.scan_problem",
                                 "Dossier de prefab ignoré", level="warning",
                                 data={"root": problem.root.value, "path": problem.path, "reason": problem.reason})
            seen: dict[tuple[PrefabRoot, str, int], tuple[tuple, CatalogVersion]] = {}
            for scanned in scan.versions:
                key = (scanned.root, scanned.prefab_id, scanned.version)
                cached = self._cache.get(key)
                if cached is not None and cached[0] == scanned.signature:
                    seen[key] = cached
                else:
                    seen[key] = (scanned.signature, await asyncio.to_thread(self._load, scanned))
            self._cache = seen
            catalog: dict[tuple[str, int], CatalogVersion] = {}
            for (root, prefab_id, version), (signature, entry) in sorted(seen.items(), key=lambda item: item[0][0]
                                                                          != PrefabRoot.PACKAGE):
                existing = catalog.get((prefab_id, version))
                if existing is not None:
                    self._trace_once(("conflict", prefab_id, version), "core.prefab.version_conflict",
                                     "Même version dans le paquet et la bibliothèque : le paquet gagne",
                                     level="warning", data={"prefab_id": prefab_id, "version": version})
                    continue
                catalog[(prefab_id, version)] = entry
                if not entry.ok:
                    self._trace_once(("tampered", root, prefab_id, version, signature), "core.prefab.tampered",
                                     "Version de prefab refusée : fichiers différents de leur publication",
                                     level="warning", data={"root": root.value, "prefab_id": prefab_id,
                                                            "version": version, "status": entry.status,
                                                            "problem": entry.problem})
            self._catalog = catalog
            occupied: dict[str, int] = {}
            for _, prefab_id, version in scan.version_folders:
                occupied[prefab_id] = max(version, occupied.get(prefab_id, 0))
            self._occupied = occupied
            self._scanned = True

    def _load(self, scanned: ScannedVersion) -> CatalogVersion:
        """Relit une version et recalcule son empreinte (thread)."""

        root, prefab_id, version = scanned.root, scanned.prefab_id, scanned.version

        def refused(status: VersionStatus, problem: str, **known: Any) -> CatalogVersion:
            return CatalogVersion(root, prefab_id, version, status, problem=clip_message(problem), **known)

        try:
            files = self._library.read_version(root, prefab_id, version)
        except PrefabStoreError as exc:
            status = VersionStatus.UNREADABLE if exc.code is _C.STORAGE_IO else VersionStatus.TAMPERED
            return refused(status, exc.message)
        try:
            bundle = parse_stored_bundle(decode_json_text(files.manifest, MAX_MANIFEST_BYTES, "manifest"),
                                         files.template, files.style, files.behavior, files.inventory)
        except PrefabDefinitionError as exc:
            return refused(VersionStatus.TAMPERED, f"definition on disk is invalid: {exc.errors[0]}")
        if (bundle.manifest.prefab_id, bundle.manifest.version) != (prefab_id, version):
            return refused(VersionStatus.TAMPERED, f"manifest names {bundle.manifest.prefab_id}@"
                                                   f"{bundle.manifest.version}, not its folder")
        digest = bundle.fingerprint()
        if files.publication is None:
            return refused(VersionStatus.TAMPERED, "publication.json is missing", bundle=bundle, fingerprint=digest)
        try:
            publication = Publication.decode_text(files.publication)
        except PrefabDefinitionError as exc:
            return refused(VersionStatus.TAMPERED, f"publication.json is invalid: {exc.errors[0]}", bundle=bundle,
                           fingerprint=digest)
        if (publication.prefab_id, publication.version) != (prefab_id, version):
            return refused(VersionStatus.TAMPERED, "publication.json names another version", bundle=bundle,
                           fingerprint=digest)
        if publication.fingerprint != digest:
            return refused(VersionStatus.TAMPERED, "fingerprint differs from publication.json (edited in place)",
                           bundle=bundle, publication=publication, fingerprint=digest)
        shipped = publication.provenance.origin is ProvenanceOrigin.BASE
        if shipped != (root is PrefabRoot.PACKAGE):
            return refused(VersionStatus.TAMPERED, f"origin {publication.provenance.origin.value} does not belong in "
                                                   f"the {root.value} root", bundle=bundle, publication=publication,
                           fingerprint=digest)
        return CatalogVersion(root, prefab_id, version, VersionStatus.OK, bundle, publication, digest)

    def retention_counts(self, prefab_id: str) -> dict[str, int]:
        """Lecture seule (QA-2 de la Slice 06) : `live` versions au catalogue, `newest` le plus grand numero, `archived` =
        `newest - live` (un numero retire n'est jamais reutilise : la difference est ce que la retention a deplace vers
        `prefabs/.archive/<id>/`, jamais detruit). Aucune suppression ici."""

        entries = self._entries_of(prefab_id)
        newest = entries[-1].version if entries else 0
        return {"live": len(entries), "newest": newest, "archived": max(newest - len(entries), 0),
                "trigger": RETENTION_TRIGGER_VERSIONS, "keep_last": RETENTION_KEEP_LAST}

    def _entries_of(self, prefab_id: str) -> list[CatalogVersion]:
        return sorted((entry for (pid, _), entry in self._catalog.items() if pid == prefab_id),
                      key=lambda entry: entry.version)

    async def _lookup(self, prefab_id: str, version: int | None) -> CatalogVersion:
        """Version saine demandée (la dernière saine si `version` est `None`) ; relit une fois si elle manque."""

        if not isinstance(prefab_id, str) or not is_prefab_id(prefab_id):
            raise PrefabStoreError(_C.UNKNOWN_PREFAB, "not a prefab id")
        if version is not None and (type(version) is not int or not 1 <= version <= MAX_VERSION):
            raise PrefabStoreError(_C.UNKNOWN_VERSION, f"{prefab_id}: version must be an integer 1..{MAX_VERSION}")
        for attempt in range(2):
            if not self._scanned or attempt:
                await self._refresh()
            entries = self._entries_of(prefab_id)
            if version is None:
                healthy = [entry for entry in entries if entry.ok]
                if healthy:
                    return healthy[-1]
            else:
                match = next((entry for entry in entries if entry.version == version), None)
                if match is not None:
                    if not match.ok:
                        raise PrefabStoreError(_C.TAMPERED if match.status is VersionStatus.TAMPERED
                                               else _C.STORAGE_IO, f"{prefab_id}@{version}: {match.problem}")
                    return match
        if not self._entries_of(prefab_id):
            raise PrefabStoreError(_C.UNKNOWN_PREFAB, f"no prefab {prefab_id}")
        if version is None:
            raise PrefabStoreError(_C.TAMPERED, f"every version of {prefab_id} is refused (tampered or unreadable)")
        raise PrefabStoreError(_C.UNKNOWN_VERSION, f"{prefab_id} has no version {version}")

    async def search(self, query: str | None = None, *, family: str | None = None,
                     class_filter: PrefabClass | str | None = None, semantic_type: str | None = None,
                     engine: str | None = None, stack: str | None = None, with_catalog: bool = False,
                     limit: int = DEFAULT_SEARCH_LIMIT) -> tuple[PrefabSummary, ...]:
        """Lignes du catalogue classées par pertinence (puis id) ; relit le catalogue (listage).

        `class_filter` : `base` ou `custom` (le `class` de `prefab_search`). `semantic_type`, `engine` (compatible =
        `native` ou `adapter`), `stack` : contrat sémantique de la dernière version (Slice 17).
        """

        if semantic_type is not None and semantic_type not in {item.value for item in SemanticType}:
            raise PrefabStoreError(_C.INVALID_DEFINITION, f"type must be one of {[item.value for item in SemanticType]}")
        if engine is not None and engine not in {item.value for item in Engine}:
            raise PrefabStoreError(_C.INVALID_DEFINITION, f"engine must be one of {[item.value for item in Engine]}")
        if stack is not None and not (isinstance(stack, str) and 0 < len(stack) <= 24):
            raise PrefabStoreError(_C.INVALID_DEFINITION, "stack must be a token of at most 24 characters")

        if query is not None and (not isinstance(query, str) or len(query) > MAX_QUERY_CHARS):
            raise PrefabStoreError(_C.INVALID_DEFINITION,
                                   f"query must be text of at most {MAX_QUERY_CHARS} characters")
        if type(limit) is not int or not 1 <= limit <= MAX_SEARCH_LIMIT:
            raise PrefabStoreError(_C.INVALID_DEFINITION, f"limit must be 1..{MAX_SEARCH_LIMIT}")
        try:
            wanted_class = None if class_filter is None else PrefabClass(class_filter)
        except ValueError:
            raise PrefabStoreError(_C.INVALID_DEFINITION, "class must be 'base' or 'custom'") from None
        await self._refresh()
        filtered = any(item is not None for item in (semantic_type, engine, stack))
        terms = (query or "").casefold().split()
        rows: list[tuple[int, PrefabSummary]] = []
        for prefab_id in sorted({key[0] for key in self._catalog}):
            summary = self._summary(prefab_id, catalog=with_catalog or filtered)
            if summary is None:
                continue
            if family is not None and summary.family != family:
                continue
            if wanted_class is not None and summary.prefab_class is not wanted_class:
                continue
            if filtered and not catalog_matches(summary.catalog, kind=semantic_type, engine=engine, stack=stack):
                continue
            score = self._score(summary, terms)
            if score is not None:
                rows.append((score, summary))
        rows.sort(key=lambda item: (-item[0], item[1].prefab_id))
        return tuple(summary for _, summary in rows[:limit])

    def _summary(self, prefab_id: str, *, catalog: bool = False) -> PrefabSummary | None:
        entries = self._entries_of(prefab_id)
        healthy = [entry for entry in entries if entry.ok]
        if not healthy:
            return None
        manifest = healthy[-1].manifest
        assert manifest is not None
        return PrefabSummary(
            prefab_id=prefab_id, latest_version=healthy[-1].version,
            versions=tuple(entry.version for entry in healthy), title=manifest.title, family=manifest.family,
            prefab_class=manifest.prefab_class, description=manifest.description,
            input_names=tuple(f"props.{name}" for name in manifest.props.properties)
            + tuple(f"data.{name}" for name in manifest.data.properties),
            event_names=tuple(manifest.events), catalog=manifest.catalog_view(parameters=False) if catalog else None,
            base_edited=any(entry.publication is not None
                            and entry.publication.provenance.origin is ProvenanceOrigin.BASE_EDIT for entry in healthy))

    def _score(self, summary: PrefabSummary, terms: list[str]) -> int | None:
        """Pertinence : chaque terme doit apparaître quelque part (sinon `None`).

        id exact 1000 ; alias exact 500 ; puis par terme : id 40, titre 30,
        alias 25, étiquette 20, famille 10, description 5.
        """

        if not terms:
            return 0
        manifest = self._catalog[(summary.prefab_id, summary.latest_version)].manifest
        assert manifest is not None
        phrase = " ".join(terms)
        prefab_id = summary.prefab_id.casefold()
        aliases = [alias.casefold() for alias in manifest.aliases]
        tags = [tag.casefold() for tag in manifest.tags]
        title, description = manifest.title.casefold(), manifest.description.casefold()
        score = 1000 if phrase == prefab_id else 0
        score += 500 if phrase in aliases else 0
        for term in terms:
            gained = (40 * (term in prefab_id) + 30 * (term in title) + 25 * any(term in alias for alias in aliases)
                      + 20 * any(term in tag for tag in tags) + 10 * (term in manifest.family)
                      + 5 * (term in description))
            if not gained:
                return None
            score += gained
        return score

    async def get(self, prefab_id: str, version: int | None = None) -> PrefabDetail:
        entry = await self._lookup(prefab_id, version)
        healthy = [item for item in self._entries_of(prefab_id) if item.ok]
        return PrefabDetail(entry, healthy[-1].version if healthy else entry.version,
                            tuple(item.history_row() for item in self._entries_of(prefab_id)))

    async def manifest(self, prefab_id: str, version: int) -> PrefabManifest:
        """Manifeste d'une version exacte et saine (événements, Slice 04) ; `PrefabStoreError` sinon."""

        entry = await self._lookup(prefab_id, version)
        assert entry.manifest is not None
        return entry.manifest

    async def bundle(self, prefab_id: str, version: int) -> dict[str, Any]:
        """Ce qu'un cadre exécute : manifeste, sources, et le runtime `{version, shim, shell_css}` (Slice 03)."""

        if version is None:
            raise PrefabStoreError(_C.UNKNOWN_VERSION, "a bundle names an exact version")
        entry = await self._lookup(prefab_id, version)
        assert entry.bundle is not None
        if entry.bundle.is_remotion:
            raise PrefabStoreError(_C.INVALID_DEFINITION, f"{prefab_id}@{version} is a Remotion source: it has no HTML "
                                                          "frame bundle (use remotion_source and the Remotion compiler)")
        return {"id": prefab_id, "version": version, "fingerprint": entry.fingerprint,
                "manifest": dict(entry.bundle.manifest.raw), "files": entry.bundle.files(),
                "runtime": await self._runtime_files()}

    async def remotion_source(self, prefab_id: str, version: int) -> RemotionSource:
        """Source d'une version Remotion exacte et saine (bloc + octets de chaque fichier) : l'entrée de la compilation
        (`docs/remotion-source.md`). Les octets sont **relus à la demande** (le catalogue n'en garde aucun) puis comparés aux
        SHA-256 de l'inventaire : une version modifiée depuis le dernier balayage est `tampered`. `invalid_definition` pour un
        prefab HTML ou pour une source qu'une garde de la Slice 06 refuse. Aucune écriture, aucun processus."""

        if version is None:
            raise PrefabStoreError(_C.UNKNOWN_VERSION, "a Remotion source names an exact version")
        entry = await self._lookup(prefab_id, version)
        assert entry.bundle is not None
        if not entry.bundle.is_remotion:
            raise PrefabStoreError(_C.INVALID_DEFINITION, f"{prefab_id}@{version} is an HTML prefab, not a Remotion source")
        assert entry.bundle.manifest.source is not None
        sources = await asyncio.to_thread(self._library.read_sources, entry.root, prefab_id, version)
        changed = sorted(path for path, data in sources.items()
                         if entry.bundle.inventory.get(path, (None, None))[1] != hashlib.sha256(data).hexdigest())
        if changed or set(sources) != set(entry.bundle.inventory):
            self._trace("core.prefab.tampered", "Source Remotion modifiée depuis le dernier balayage", level="warning",
                        data={"prefab_id": prefab_id, "version": version, "files": len(changed)})
            raise PrefabStoreError(_C.TAMPERED, f"{prefab_id}@{version}: source files changed since the catalogue was loaded")
        try:
            return parse_source(entry.bundle.manifest.source, sources)
        except RemotionSourceError as exc:
            raise PrefabStoreError(_C.INVALID_DEFINITION, f"{prefab_id}@{version}: {exc.errors[0]}", errors=exc.errors) from None

    async def _runtime_files(self) -> dict[str, str]:
        if self._runtime is None:
            raise PrefabStoreError(_C.STORAGE_IO, "prefab runtime unavailable: no runtime source is wired")
        try:
            files = await asyncio.to_thread(self._runtime.read_runtime)
        except PrefabStoreError as exc:
            self._trace("core.prefab.runtime_unavailable", "Runtime des cadres de prefab illisible", level="error",
                        data={"code": exc.code.value, "error": exc.message})
            raise PrefabStoreError(_C.STORAGE_IO, f"prefab runtime unavailable: {exc.message}") from None
        version = fingerprint({"shim": files.shim, "shell_css": files.shell_css})[:RUNTIME_VERSION_CHARS]
        return {"version": version, "shim": files.shim, "shell_css": files.shell_css}

    # ------------------------------------------------------------ validation

    def validate_candidate(self, candidate: object) -> CandidateValidation:
        """Validation sans écriture (`prefab_validate`) : toutes les erreurs vues, ou l'empreinte."""

        try:
            bundle = parse_candidate(candidate)
        except PrefabDefinitionError as exc:
            return CandidateValidation(False, exc.errors)
        return CandidateValidation(True, (), bundle.fingerprint())

    async def validate_instance(self, ref: PrefabInstanceRef) -> InstanceValidation:
        """Port `PrefabInstanceValidator` : version saine, `props`/`data` valides, défauts appliqués."""

        try:
            entry = await self._lookup(ref.prefab_id, ref.version)
        except PrefabStoreError as exc:
            return InstanceValidation(False, code=exc.code, detail=clip_message(exc.message))
        manifest = entry.manifest
        assert manifest is not None
        props, problems = validate_value(manifest.props, ref.props, "props")
        data, more = validate_value(manifest.data, ref.data, "data")
        problems = problems + more
        if problems:
            return InstanceValidation(False, code=_C.INVALID_DEFINITION,
                                      detail=clip_message(f"{ref.prefab_id}@{ref.version}: " + "; ".join(problems)))
        return InstanceValidation(True, props=props, data=data)

    # ------------------------------------------------------------ publication

    async def save(self, candidate: object, *, actor: CreatorActor | str,
                   derived_from: PrefabRef | None = None) -> Publication:
        """Publie un prefab custom : neuf (`custom`/`fork`) ou nouvelle version (`revision`). Jamais une base."""

        try:
            creator = CreatorActor(actor)
        except ValueError:
            creator = None
        if creator not in SAVE_ACTORS:
            raise PrefabStoreError(_C.INVALID_DEFINITION, "actor must be 'brain' or 'user'")
        try:
            bundle = parse_candidate(candidate)
        except PrefabDefinitionError as exc:
            raise _definition_error(exc) from None
        prefab_id = bundle.manifest.prefab_id
        if bundle.manifest.prefab_class is PrefabClass.BASE:
            self._trace("core.prefab.save_refused", "Publication d'une base refusée hors de la porte d'édition",
                        level="warning", data={"prefab_id": prefab_id, "actor": creator.value})
            raise PrefabStoreError(_C.BASE_PROTECTED, f"{prefab_id} is a base prefab: it changes only through the "
                                                      "base-edit gate (prefab_edit_base) with the user's explicit "
                                                      "request; save it under a new custom id instead")
        async with self._write_lock:
            await self._refresh()
            known = self._entries_of(prefab_id)
            if known:
                if derived_from is not None and derived_from.prefab_id != prefab_id:
                    raise PrefabStoreError(_C.INVALID_DEFINITION, f"{prefab_id} already exists: a revision derives "
                                                                  "from its own previous version, not from another id")
                origin, source = ProvenanceOrigin.REVISION, PrefabRef(prefab_id, known[-1].version)
            else:
                # Tout id neuf (custom comme fork) compte dans la borne du catalogue.
                await self._make_room_for_id(prefab_id)
                if derived_from is not None:
                    await self._lookup(derived_from.prefab_id, derived_from.version)
                    origin, source = ProvenanceOrigin.FORK, derived_from
                else:
                    origin, source = ProvenanceOrigin.CUSTOM, None
            publication = await self._publish(bundle, known, Provenance(origin, creator, source))
        self._trace("core.prefab.saved", "Prefab publié",
                    data={"prefab_id": prefab_id, "version": publication.version, "origin": origin.value,
                          "actor": creator.value, "fingerprint": publication.fingerprint})
        return publication

    async def edit_base(self, prefab_id: str, candidate: object, *, user_request: object, confirmed_by_user: object,
                        actor: CreatorActor | str = CreatorActor.BRAIN) -> Publication:
        """Nouvelle version d'une base `jarvis.*`, dans la racine de données, par la porte d'intention explicite."""

        try:
            creator = CreatorActor(actor)
        except ValueError:
            creator = None
        if creator not in BASE_EDIT_ACTORS:
            raise PrefabStoreError(_C.INVALID_DEFINITION, "actor must be 'brain': base edits are made by the brain "
                                                          "through prefab_edit_base, never by the UI")
        async with self._write_lock:
            await self._refresh()
            known = self._entries_of(prefab_id) if isinstance(prefab_id, str) else []
            # 1. id jarvis.* existant
            if not (isinstance(prefab_id, str) and is_prefab_id(prefab_id)
                    and prefab_class(prefab_id) is PrefabClass.BASE and known):
                self._refuse_base_edit(prefab_id, "not an existing base prefab id (jarvis.*)")
            # 2. confirmation explicite
            if confirmed_by_user is not True:
                self._refuse_base_edit(prefab_id, "confirmed_by_user must be true: ask the user to confirm first")
            # 3. demande citée, bornée
            if not isinstance(user_request, str) \
                    or not MIN_USER_REQUEST_CHARS <= len(user_request.strip()) <= MAX_USER_REQUEST_CHARS:
                self._refuse_base_edit(prefab_id, f"user_request must quote the user's own words "
                                                  f"({MIN_USER_REQUEST_CHARS}..{MAX_USER_REQUEST_CHARS} characters)")
            # 3 bis. la citation, normalisée, est assez longue et nomme ce prefab (id, titre ou alias publiés)
            problem = quote_problem(user_request, self._names_of(prefab_id, known))  # type: ignore[arg-type]
            if problem is not None:
                self._refuse_base_edit(prefab_id, problem)
            # 4. témoin : la demande se retrouve dans un tour récent de l'utilisateur
            event_id = await self._witness_of(prefab_id, user_request.strip())  # type: ignore[union-attr]
            try:
                bundle = parse_candidate(candidate)
            except PrefabDefinitionError as exc:
                raise _definition_error(exc) from None
            if bundle.manifest.prefab_id != prefab_id:
                raise PrefabStoreError(_C.INVALID_DEFINITION, f"candidate manifest id {bundle.manifest.prefab_id} "
                                                              f"differs from {prefab_id}")
            record = BaseEditRecord(user_request.strip(), f"{WITNESS_PREFIX}{event_id}")  # type: ignore[union-attr]
            provenance = Provenance(ProvenanceOrigin.BASE_EDIT, creator,
                                    PrefabRef(prefab_id, known[-1].version), record)
            publication = await self._publish(bundle, known, provenance)
        self._trace("core.prefab.base_edited", "Prefab de base modifié par la porte d'intention explicite",
                    level="warning", data={"prefab_id": prefab_id, "version": publication.version,
                                           "derived_from": known[-1].version, "witness": record.witness,
                                           "request_chars": len(record.user_request)})
        return publication

    @staticmethod
    def _names_of(prefab_id: str, known: list[CatalogVersion]) -> list[str]:
        """Ce qui nomme une base dans la bouche de l'utilisateur : dernier segment de l'id, titres et alias publiés.

        Lus dans les versions **déjà publiées** (jamais dans le candidat, qui
        pourrait s'ajouter un alias pour passer la porte).
        """

        names = [prefab_id.rsplit(".", 1)[-1].replace("_", " ")]
        for entry in known:
            if entry.bundle is not None:
                names += [entry.bundle.manifest.title, *entry.bundle.manifest.aliases]
        return names

    def _refuse_base_edit(self, prefab_id: object, reason: str) -> None:
        self._trace("core.prefab.base_edit_refused", "Édition de base refusée", level="warning",
                    data={"prefab_id": prefab_id if isinstance(prefab_id, str) else None, "reason": reason})
        raise PrefabStoreError(_C.BASE_EDIT_UNCONFIRMED, reason)

    async def _witness_of(self, prefab_id: str, user_request: str) -> str:
        if self._witness is None:
            self._refuse_base_edit(prefab_id, "no conversation witness is wired: base edits are refused")
        try:
            event_id = await self._witness(user_request)  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001 - intentional: a failing lookup is a refused gate, traced
            self._refuse_base_edit(prefab_id, clip_message(f"witness lookup failed: {type(exc).__name__}: {exc}"))
        if not isinstance(event_id, str) or not event_id.strip() or len(event_id) > 128:
            self._refuse_base_edit(prefab_id, "user_request was not found in a recent user turn: quote the user's "
                                              "own words")
        return event_id.strip()

    async def _publish(self, bundle: PrefabBundle, known: list[CatalogVersion], provenance: Provenance) -> Publication:
        """Version attribuée par Core, empreinte, publication sur disque, relecture. Sous `_write_lock`."""

        prefab_id = bundle.manifest.prefab_id
        note = ""
        if is_retention_id(prefab_id) and len(known) >= RETENTION_TRIGGER_VERSIONS:
            known, note = await self._retire_surplus(prefab_id, known)
        # Plus grand numéro occupé + 1 : un dossier de version vide, refusé ou **archivé** compte aussi, donc un
        # numéro retiré n'est jamais réattribué.
        version = max(known[-1].version if known else 0, self._occupied.get(prefab_id, 0)) + 1
        if version > MAX_VERSION:
            raise PrefabStoreError(_C.VERSION_LIMIT, f"{prefab_id} a atteint la version {MAX_VERSION}, la dernière "
                                                     "numérotable. Enregistre la source sous un nouvel id "
                                                     "(derived_from la dernière version).")
        if len(known) >= MAX_VERSIONS_PER_ID:
            raise PrefabStoreError(_C.VERSION_LIMIT, f"{prefab_id} a atteint ses {MAX_VERSIONS_PER_ID} versions "
                                                     f"vivantes{note}. Enregistre la source sous un nouvel id "
                                                     "(derived_from la dernière version).")
        try:
            numbered = renumber(bundle, version)
            publication = Publication(prefab_id, version, numbered.fingerprint(), format_published_at(self._clock()),
                                      provenance)
        except PrefabDefinitionError as exc:
            raise _definition_error(exc) from None
        try:
            await asyncio.to_thread(self._library.publish, numbered, publication)
        except PrefabStoreError as exc:
            self._trace("core.prefab.save_failed", "Publication de prefab échouée",
                        level="error" if exc.code is _C.STORAGE_IO else "warning",
                        data={"prefab_id": prefab_id, "version": version, "code": exc.code.value,
                              "error": exc.message})
            raise
        await self._refresh()
        return publication

    # ------------------------------------------------------------ rétention (Slice 01a)

    async def _pins_of(self, prefab_ids: list[str]) -> Mapping[str, frozenset[int]] | None:
        """Versions épinglées, ou `None` : sans registre, s'il échoue, tarde ou répond de travers, rien ne
        s'archive (fermé par défaut). Le registre tourne sous `_write_lock` : il est borné dans le temps."""

        if self._pin_registry is None:
            self._trace_once(("retention_inactive",), "core.prefab.retention_inactive",
                             "Rétention des sources du Studio inactive : aucun registre d'épinglages branché",
                             level="warning", data={})
            return None
        try:
            answer = await asyncio.wait_for(self._pin_registry.pinned_versions(tuple(prefab_ids)),
                                            PIN_REGISTRY_TIMEOUT_SECONDS)
            return checked_pins(answer, prefab_ids)
        except Exception as exc:  # noqa: BLE001 - intentional: an unknown pin set archives nothing; traced, surfaced
            reason = (f"no answer within {PIN_REGISTRY_TIMEOUT_SECONDS:g}s" if isinstance(exc, TimeoutError)
                      else f"{type(exc).__name__}: {exc}")
            self._trace("core.prefab.retention_failed", "Registre d'épinglages illisible : rien n'est archivé",
                        level="error", data={"ids": len(prefab_ids), "error": clip_message(reason)})
            return None

    async def _retire(self, prefab_id: str, versions: list[int]) -> list[int]:
        """Archive les `versions`, la plus ancienne d'abord. Une version qui échoue (emplacement d'archive pris,
        dossier verrouillé) est tracée et **sautée** : elle ne bloque pas les suivantes. Rend celles déplacées."""

        moved: list[int] = []
        for version in versions:
            try:
                await asyncio.to_thread(self._library.retire, prefab_id, version)
            except PrefabStoreError as exc:
                self._trace("core.prefab.retention_failed", "Archivage d'une version de prefab échoué (sautée)",
                            level="error", data={"prefab_id": prefab_id, "version": version, "code": exc.code.value,
                                                 "error": exc.message})
                continue
            moved.append(version)
        if moved:
            self._trace("core.prefab.retired", "Versions de prefab archivées (non épinglées)",
                        data={"prefab_id": prefab_id, "versions": moved, "skipped": len(versions) - len(moved)})
        return moved

    async def _retire_surplus(self, prefab_id: str, known: list[CatalogVersion]) -> tuple[list[CatalogVersion], str]:
        """Archive les versions non épinglées au-delà des `RETENTION_KEEP_LAST` dernières. Sous `_write_lock`.

        Rend `(versions vivantes, précision pour le message de limite)` ; un résultat partiel est gardé.
        """

        pinned = await self._pins_of([prefab_id])
        if pinned is None:
            return known, " (rétention indisponible : voir le journal)"
        candidates = retirable_versions(known, pinned[prefab_id], RETENTION_KEEP_LAST)
        moved = await self._retire(prefab_id, candidates)
        if moved:
            await self._refresh()
            known = self._entries_of(prefab_id)
        if len(moved) < len(candidates):
            return known, " (certaines versions n'ont pas pu être archivées : voir le journal)"
        if not moved:
            return known, " (les autres sont épinglées par le Studio ou parmi les plus récentes)"
        return known, ""

    async def _make_room_for_id(self, prefab_id: str) -> None:
        """Borne des ids pour un id neuf ; un id du Studio inutilisé peut être archivé pour lui faire de la place."""

        ids = {key[0] for key in self._catalog}
        studio = sorted(item for item in ids if is_retention_id(item))
        is_studio = is_retention_id(prefab_id)
        if len(ids) < MAX_PREFAB_IDS and not (is_studio and len(studio) >= MAX_RETENTION_PREFAB_IDS):
            return
        detail = ""
        if is_studio:
            freed, why = await self._retire_idle_id(studio)
            if freed is not None:
                await self._refresh()
                return
            detail = f" (dont {len(studio)} du Studio, au plus {MAX_RETENTION_PREFAB_IDS}) ; {why}"
        raise PrefabStoreError(_C.ID_LIMIT, f"La bibliothèque contient déjà {len(ids)} ids de prefab sur "
                                            f"{MAX_PREFAB_IDS}{detail}. Réutilise un id existant (nouvelle version).")

    async def _retire_idle_id(self, studio: list[str]) -> tuple[str | None, str]:
        """Archive en entier le plus ancien id du Studio dont aucune version n'est épinglée ni récente.

        Rend `(id archivé ou None, pourquoi aucun)`.
        """

        pinned = await self._pins_of(studio)
        if pinned is None:
            return None, "archivage indisponible, voir le journal"
        now = self._clock()
        ranked = sorted(((max(e.publication.published_at for e in self._entries_of(item) if e.publication), item)
                         for item in studio if any(e.publication for e in self._entries_of(item))))
        failed = False
        for last_published, item in ranked:
            entries = self._entries_of(item)
            age = (now - datetime.fromisoformat(last_published.replace("Z", "+00:00"))).total_seconds()
            if pinned[item] or age < RETENTION_ID_GRACE_SECONDS \
                    or any(entry.root is not PrefabRoot.DATA for entry in entries):
                continue
            versions = [entry.version for entry in entries]
            if await self._retire(item, versions) == versions:
                self._trace("core.prefab.id_retired", "Id du Studio archivé en entier (aucun épinglage)",
                            data={"prefab_id": item, "versions": len(versions)})
                return item, ""
            failed = True  # partial: what moved stays archived, the rest stays visible; try the next idle id
        return None, ("l'archivage a échoué sur les ids inutilisés, voir le journal" if failed
                      else "tous sont épinglés ou publiés depuis moins d'une heure")

    # ------------------------------------------------------------ diagnostics

    def _trace_once(self, key: tuple[Any, ...], kind: str, message: str, *, level: str = "info",
                    data: Mapping[str, Any]) -> None:
        if key in self._reported:
            return
        self._reported.add(key)
        self._trace(kind, message, level=level, data=data)

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any] | None = None) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=dict(data or {}))
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal never undoes a catalogue operation
            pass

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
  exister et être sain) ; id custom existant -> `revision` v+1 ; id
  `jarvis.*` -> `base_protected`. Core attribue la version (le nom du
  dossier) : la `version` du candidat est remplacée par max(connues) + 1
  avant l'empreinte ;
- **edit_base** : porte d'intention explicite (conditions 1-4 du contrat).
  Le témoin `user_utterance_witness(texte) -> event_id | None` est injecté ;
  la Slice 07 le branche sur les Conversation Events. Tant qu'il ne l'est
  pas (`None`, ou un témoin qui ne trouve rien), toute édition de base est
  refusée (`base_edit_unconfirmed`) ;
- **validate_instance** (port `PrefabInstanceValidator`, branché sur
  `SceneService` à la Slice 04) : version existante et saine, `props`/`data`
  validés et complétés de leurs défauts, détail ≤ 300 caractères.

Les appels au magasin (disque) passent par `asyncio.to_thread` ; les
publications sont sérialisées par un verrou. Miroir diagnostic
(`core.prefab.*`) : ids, versions, codes, jamais le texte de l'utilisateur.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from jarvis.domain.prefab import (
    MAX_ERROR_CHARS, MAX_MANIFEST_BYTES, MAX_PREFAB_IDS, MAX_USER_REQUEST_CHARS, MAX_VERSION, MAX_VERSIONS_PER_ID,
    MIN_USER_REQUEST_CHARS, WITNESS_PREFIX, BaseEditRecord, CreatorActor, PrefabBundle, PrefabClass,
    PrefabDefinitionError, PrefabInstanceRef, PrefabManifest, PrefabRef, Provenance, ProvenanceOrigin, Publication,
    decode_json_text, format_published_at, is_prefab_id, parse_bundle, parse_candidate, prefab_class,
    validate_value, with_version,
)
from jarvis.domain.v2 import utc_now
from jarvis.ports.prefabs import (
    InstanceValidation, PrefabLibrary, PrefabRoot, PrefabStoreError, PrefabStoreErrorCode, ScannedVersion,
)
from jarvis.ports.v2 import DiagnosticSink

#: Témoin de la porte d'édition de base : l'id de l'événement de conversation
#: où l'utilisateur a dit `user_request`, ou `None`.
UserUtteranceWitness = Callable[[str], Awaitable[str | None]]
DEFAULT_SEARCH_LIMIT = 20
MAX_SEARCH_LIMIT = 50
MAX_QUERY_CHARS = 120
#: Acteurs qui publient par `save` (le système ne publie que les bases livrées).
SAVE_ACTORS = frozenset({CreatorActor.BRAIN, CreatorActor.USER})
_C = PrefabStoreErrorCode


class VersionStatus:
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
    status: str
    bundle: PrefabBundle | None = None
    publication: Publication | None = None
    fingerprint: str | None = None
    #: Pourquoi la version est refusée (≤ 300), vide si `ok`.
    problem: str = ""

    @property
    def ok(self) -> bool:
        return self.status == VersionStatus.OK

    @property
    def manifest(self) -> PrefabManifest | None:
        return None if self.bundle is None else self.bundle.manifest

    def history_row(self) -> dict[str, Any]:
        row: dict[str, Any] = {"version": self.version, "root": self.root.value, "status": self.status}
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

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.prefab_id, "latest_version": self.latest_version, "versions": list(self.versions),
                "title": self.title, "family": self.family, "class": self.prefab_class.value,
                "description": self.description, "input_names": list(self.input_names),
                "event_names": list(self.event_names), "base_edited": self.base_edited}


@dataclass(frozen=True, slots=True)
class PrefabDetail:
    """Une version saine, sa publication et l'historique de l'id (chaîne de provenance)."""

    entry: CatalogVersion
    latest_version: int
    history: tuple[dict[str, Any], ...]

    def to_dict(self, *, include_source: bool = False) -> dict[str, Any]:
        bundle, publication = self.entry.bundle, self.entry.publication
        assert bundle is not None and publication is not None
        body: dict[str, Any] = {"id": self.entry.prefab_id, "version": self.entry.version,
                                "latest_version": self.latest_version, "class": prefab_class(self.entry.prefab_id).value,
                                "manifest": dict(bundle.manifest.raw), "publication": publication.to_dict(),
                                "history": list(self.history)}
        if include_source:
            body["files"] = bundle.files()
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


def _bounded(text: str) -> str:
    return text if len(text) <= MAX_ERROR_CHARS else text[: MAX_ERROR_CHARS - 1] + "…"


def _definition_error(exc: PrefabDefinitionError, what: str = "candidate") -> PrefabStoreError:
    return PrefabStoreError(_C.INVALID_DEFINITION, f"{what} refused: {exc.errors[0]}", errors=exc.errors)


class PrefabService:
    """Voir l'en-tête du module."""

    def __init__(self, library: PrefabLibrary, *, user_utterance_witness: UserUtteranceWitness | None = None,
                 diagnostics: DiagnosticSink | None = None, clock: Callable[[], datetime] = utc_now) -> None:
        self._library = library
        self._witness = user_utterance_witness
        self._diagnostics = diagnostics
        self._clock = clock
        self._write_lock = asyncio.Lock()
        self._refresh_lock = asyncio.Lock()
        #: `(racine, id, version)` -> (signature des fichiers, version chargée).
        self._cache: dict[tuple[PrefabRoot, str, int], tuple[tuple, CatalogVersion]] = {}
        #: `(id, version)` -> version retenue (le paquet gagne).
        self._catalog: dict[tuple[str, int], CatalogVersion] = {}
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
                        level="warning", data={"error": _bounded(f"{type(exc).__name__}: {exc}")})
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
                        level="error", data={"error": _bounded(f"{type(exc).__name__}: {exc}")})
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
            self._scanned = True

    def _load(self, scanned: ScannedVersion) -> CatalogVersion:
        """Relit une version et recalcule son empreinte (thread)."""

        root, prefab_id, version = scanned.root, scanned.prefab_id, scanned.version

        def refused(status: str, problem: str, **known: Any) -> CatalogVersion:
            return CatalogVersion(root, prefab_id, version, status, problem=_bounded(problem), **known)

        try:
            files = self._library.read_version(root, prefab_id, version)
        except PrefabStoreError as exc:
            status = VersionStatus.UNREADABLE if exc.code is _C.STORAGE_IO else VersionStatus.TAMPERED
            return refused(status, exc.message)
        try:
            bundle = parse_bundle(decode_json_text(files.manifest, MAX_MANIFEST_BYTES, "manifest"), files.template,
                                  files.style, files.behavior)
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
                        raise PrefabStoreError(_C.TAMPERED if match.status == VersionStatus.TAMPERED
                                               else _C.STORAGE_IO, f"{prefab_id}@{version}: {match.problem}")
                    return match
        if not self._entries_of(prefab_id):
            raise PrefabStoreError(_C.UNKNOWN_PREFAB, f"no prefab {prefab_id}")
        if version is None:
            raise PrefabStoreError(_C.TAMPERED, f"every version of {prefab_id} is refused (tampered or unreadable)")
        raise PrefabStoreError(_C.UNKNOWN_VERSION, f"{prefab_id} has no version {version}")

    async def search(self, query: str | None = None, *, family: str | None = None,
                     prefab_class: PrefabClass | str | None = None,
                     limit: int = DEFAULT_SEARCH_LIMIT) -> tuple[PrefabSummary, ...]:
        """Lignes du catalogue classées par pertinence (puis id) ; relit le catalogue (listage)."""

        if query is not None and (not isinstance(query, str) or len(query) > MAX_QUERY_CHARS):
            raise PrefabStoreError(_C.INVALID_DEFINITION, f"query must be text of at most {MAX_QUERY_CHARS} characters")
        if type(limit) is not int or not 1 <= limit <= MAX_SEARCH_LIMIT:
            raise PrefabStoreError(_C.INVALID_DEFINITION, f"limit must be 1..{MAX_SEARCH_LIMIT}")
        wanted_class = None if prefab_class is None else PrefabClass(prefab_class)
        await self._refresh()
        terms = (query or "").casefold().split()
        rows: list[tuple[int, PrefabSummary]] = []
        for prefab_id in sorted({key[0] for key in self._catalog}):
            summary = self._summary(prefab_id)
            if summary is None or (family is not None and summary.family != family) \
                    or (wanted_class is not None and summary.prefab_class is not wanted_class):
                continue
            score = self._score(summary, terms)
            if score is not None:
                rows.append((score, summary))
        rows.sort(key=lambda item: (-item[0], item[1].prefab_id))
        return tuple(summary for _, summary in rows[:limit])

    def _summary(self, prefab_id: str) -> PrefabSummary | None:
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
            event_names=tuple(manifest.events),
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

    async def bundle(self, prefab_id: str, version: int) -> dict[str, Any]:
        """Ce qu'un cadre exécute : manifeste et sources ; `runtime` (shim, shell) vient avec la Slice 03."""

        if version is None:
            raise PrefabStoreError(_C.UNKNOWN_VERSION, "a bundle names an exact version")
        entry = await self._lookup(prefab_id, version)
        assert entry.bundle is not None
        return {"id": prefab_id, "version": version, "fingerprint": entry.fingerprint,
                "manifest": dict(entry.bundle.manifest.raw), "files": entry.bundle.files(), "runtime": None}

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
            return InstanceValidation(False, code=exc.code, detail=_bounded(exc.message))
        manifest = entry.manifest
        assert manifest is not None
        props, problems = validate_value(manifest.props, ref.props, "props")
        data, more = validate_value(manifest.data, ref.data, "data")
        problems = problems + more
        if problems:
            return InstanceValidation(False, code=_C.INVALID_DEFINITION,
                                      detail=_bounded(f"{ref.prefab_id}@{ref.version}: " + "; ".join(problems)))
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
            elif derived_from is not None:
                await self._lookup(derived_from.prefab_id, derived_from.version)
                origin, source = ProvenanceOrigin.FORK, derived_from
            else:
                origin, source = ProvenanceOrigin.CUSTOM, None
                if len({key[0] for key in self._catalog}) >= MAX_PREFAB_IDS:
                    raise PrefabStoreError(_C.INVALID_DEFINITION, f"the library holds {MAX_PREFAB_IDS} prefab ids "
                                                                  "already")
            publication = await self._publish(bundle, known, Provenance(origin, creator, source))
        self._trace("core.prefab.saved", "Prefab publié",
                    data={"prefab_id": prefab_id, "version": publication.version, "origin": origin.value,
                          "actor": creator.value, "fingerprint": publication.fingerprint})
        return publication

    async def edit_base(self, prefab_id: str, candidate: object, *, user_request: object, confirmed_by_user: object,
                        actor: CreatorActor | str = CreatorActor.BRAIN) -> Publication:
        """Nouvelle version d'une base `jarvis.*`, dans la racine de données, par la porte d'intention explicite."""

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
            provenance = Provenance(ProvenanceOrigin.BASE_EDIT, CreatorActor(actor),
                                    PrefabRef(prefab_id, known[-1].version), record)
            publication = await self._publish(bundle, known, provenance)
        self._trace("core.prefab.base_edited", "Prefab de base modifié par la porte d'intention explicite",
                    level="warning", data={"prefab_id": prefab_id, "version": publication.version,
                                           "derived_from": known[-1].version, "witness": record.witness,
                                           "request_chars": len(record.user_request)})
        return publication

    def _refuse_base_edit(self, prefab_id: object, reason: str) -> None:
        self._trace("core.prefab.base_edit_refused", "Édition de base refusée", level="warning",
                    data={"prefab_id": prefab_id if isinstance(prefab_id, str) else None, "reason": reason})
        raise PrefabStoreError(_C.BASE_EDIT_UNCONFIRMED, reason)

    async def _witness_of(self, prefab_id: str, user_request: str) -> str:
        if self._witness is None:
            self._refuse_base_edit(prefab_id, "no conversation witness is wired: base edits are refused")
        try:
            event_id = await self._witness(user_request)  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001 - intentional: a failing lookup is a refused gate, traced with its cause
            self._refuse_base_edit(prefab_id, _bounded(f"witness lookup failed: {type(exc).__name__}: {exc}"))
        if not isinstance(event_id, str) or not event_id.strip() or len(event_id) > 128:
            self._refuse_base_edit(prefab_id, "user_request was not found in a recent user turn: quote the user's "
                                              "own words")
        return event_id.strip()

    async def _publish(self, bundle: PrefabBundle, known: list[CatalogVersion], provenance: Provenance) -> Publication:
        """Version attribuée par Core, empreinte, publication sur disque, relecture. Sous `_write_lock`."""

        prefab_id = bundle.manifest.prefab_id
        version = (known[-1].version if known else 0) + 1
        if version > MAX_VERSION or len(known) >= MAX_VERSIONS_PER_ID:
            raise PrefabStoreError(_C.INVALID_DEFINITION, f"{prefab_id} has reached its version limit "
                                                          f"({MAX_VERSIONS_PER_ID} versions, at most v{MAX_VERSION})")
        try:
            numbered = parse_bundle(with_version(bundle.manifest.raw, version), bundle.template, bundle.style,
                                    bundle.behavior)
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

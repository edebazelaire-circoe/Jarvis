"""The diagnostic catalog: load official manifests, describe them, keep every version.

Binding contract: `docs/testlab.md` ("Catalog"). This module is the I/O half of the
catalog (reading the manifest files and the lock); the documents, their validation and
their fingerprints are `jarvis.testlab.manifests`.

Official manifests live in `jarvis/testlab/official/<domain>/<name>.v<N>.json`, next to
the code that registers their implementations, with `catalog.lock.json` beside them.
Loading is deterministic (sorted paths), strict (one typed `CatalogError` per failure
mode) and complete (every published version is kept, so a stored `TestRun` can always be
re-checked against the declaration it was judged by).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any

from jarvis.testlab._diagnostics import SafeDiagnostics
from jarvis.testlab._fs import is_link
from jarvis.testlab.diagnostics import DiagnosticSpec
from jarvis.testlab.identity import check_diagnostic_id, check_diagnostic_version
from jarvis.testlab.implementations import (
    ImplementationEntry,
    ImplementationRegistry,
    default_implementations,
)
from jarvis.testlab.manifests import (
    CATALOG_DUPLICATE,
    CATALOG_LOCK_INVALID,
    CATALOG_NOT_FOUND,
    CATALOG_PATH_INVALID,
    CATALOG_READ_FAILED,
    CatalogError,
    CatalogLock,
    DiagnosticManifest,
    MAX_MANIFEST_BYTES,
    check_history,
    check_lock_coverage,
    check_manifest,
    check_manifest_name,
    decode_manifest_text,
)
from jarvis.testlab.primitives import DEFAULT_PRIMITIVES, PrimitiveRegistry
from jarvis.testlab.profiles import CostBounds, Capability, ProfileName
from jarvis.testlab.runs import TestRun, check_run_against_spec
from jarvis.testlab.validation import fail
from jarvis.ports.v2 import DiagnosticSink

#: Official manifests ship with the package, beside the module that registers implementations.
DEFAULT_CATALOG_ROOT = Path(__file__).resolve().parent / "official"
LOCK_FILE_NAME = "catalog.lock.json"
_MANIFEST_FILE = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*\.v[1-9][0-9]{0,8}\.json")
_DOMAIN_DIR = re.compile(r"[a-z][a-z0-9_]*")


@dataclass(frozen=True, slots=True)
class ProfileAvailability:
    """What running one diagnostic on one profile needs, costs, and whether it can run today."""

    profile: ProfileName
    implementation: ImplementationEntry
    requires: frozenset[Capability]
    cost: CostBounds

    @property
    def available(self) -> bool:
        return self.implementation.factory is not None

    def to_dict(self) -> dict[str, Any]:
        return {"profile": self.profile.value,
                "requires": sorted(item.value for item in self.requires),
                "cost": self.cost.to_dict(),
                **self.implementation.to_dict()}


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One published version: its manifest, where it lives, and its resolved profiles."""

    manifest: DiagnosticManifest
    path: str
    manifest_fingerprint: str
    profiles: Mapping[ProfileName, ProfileAvailability]

    @property
    def diagnostic(self) -> DiagnosticSpec:
        return self.manifest.diagnostic

    @property
    def diagnostic_id(self) -> str:
        return self.manifest.diagnostic_id

    @property
    def version(self) -> int:
        return self.manifest.version

    def resources_and_cost(self, profile: ProfileName) -> ProfileAvailability:
        """Capabilities, cost bounds and availability of one profile of this version."""
        availability = self.profiles.get(profile)
        if availability is None:
            raise CatalogError(CATALOG_NOT_FOUND,
                               f"{self.diagnostic_id} v{self.version} does not declare profile "
                               f"{getattr(profile, 'value', profile)}")
        return availability

    def to_dict(self) -> dict[str, Any]:
        """Introspection form for the CLI, HTTP API and UI (Slice 10)."""
        return {"diagnostic_id": self.diagnostic_id, "version": self.version, "path": self.path,
                "manifest_fingerprint": self.manifest_fingerprint,
                "diagnostic_fingerprint": self.diagnostic.fingerprint(),
                "title": self.diagnostic.title, "domain": self.diagnostic.domain,
                "description": self.diagnostic.description,
                "profiles": [self.profiles[name].to_dict() for name in self.profiles],
                "parameters": [item.to_dict() for item in self.diagnostic.parameters],
                "override_allowlist": [item.to_dict() for item in self.manifest.override_allowlist],
                "metrics": [item.to_dict() for item in self.diagnostic.metrics],
                "assertions": [item.to_dict() for item in self.diagnostic.assertions],
                "score": self.diagnostic.score.to_dict(),
                "scenario": None if self.manifest.scenario is None else self.manifest.scenario.to_dict()}


class Catalog:
    """Every official diagnostic, every version, introspectable and checked."""

    def __init__(self, entries: Iterable[CatalogEntry]) -> None:
        indexed: dict[tuple[str, int], CatalogEntry] = {}
        for entry in entries:
            if not isinstance(entry, CatalogEntry):
                raise fail("a catalog holds CatalogEntry values")
            if (entry.diagnostic_id, entry.version) in indexed:
                raise CatalogError(CATALOG_DUPLICATE,
                                   f"{entry.diagnostic_id} v{entry.version} is declared twice", path=entry.path)
            indexed[(entry.diagnostic_id, entry.version)] = entry
        self._entries = MappingProxyType(dict(sorted(indexed.items())))

    @classmethod
    def build(cls, manifests: Iterable[tuple[str, DiagnosticManifest]], lock: CatalogLock, *,
              primitives: PrimitiveRegistry = DEFAULT_PRIMITIVES,
              implementations: ImplementationRegistry | None = None) -> Catalog:
        """Validate a set of `(path, manifest)` pairs against the lock and build the catalog."""
        registry = implementations if implementations is not None else default_implementations()
        if not isinstance(lock, CatalogLock):
            raise CatalogError(CATALOG_LOCK_INVALID, "build takes a CatalogLock")
        by_key: dict[tuple[str, int], DiagnosticManifest] = {}
        entries: list[CatalogEntry] = []
        for path, manifest in manifests:
            if not isinstance(manifest, DiagnosticManifest):
                raise CatalogError(CATALOG_PATH_INVALID, "build takes DiagnosticManifest values", path=str(path))
            check_manifest_name(manifest.diagnostic_id, manifest.version, path)
            key = (manifest.diagnostic_id, manifest.version)
            if key in by_key:
                raise CatalogError(CATALOG_DUPLICATE, f"{key[0]} v{key[1]} is declared twice", path=path)
            by_key[key] = manifest
            profiles = check_manifest(manifest, primitives=primitives, implementations=registry)
            entries.append(CatalogEntry(manifest, path, manifest.fingerprint(), MappingProxyType(
                {name: ProfileAvailability(name, profiles[name], profile.requires, profile.cost)
                 for name, profile in manifest.diagnostic.profiles.items()})))
        check_history(by_key)
        check_lock_coverage(by_key, lock)
        return cls(entries)

    @property
    def entries(self) -> tuple[CatalogEntry, ...]:
        return tuple(self._entries.values())

    def list_diagnostics(self) -> tuple[CatalogEntry, ...]:
        """The latest version of every official diagnostic, by diagnostic id."""
        latest: dict[str, CatalogEntry] = {}
        for entry in self._entries.values():
            current = latest.get(entry.diagnostic_id)
            if current is None or entry.version > current.version:
                latest[entry.diagnostic_id] = entry
        return tuple(latest[name] for name in sorted(latest))

    def describe(self, diagnostic_id: str, version: int | None = None) -> CatalogEntry:
        """One version, the latest by default. Unknown id or version: `testlab_catalog_not_found`."""
        check_diagnostic_id(diagnostic_id)
        history = self.history(diagnostic_id)
        if version is None:
            return history[-1]
        check_diagnostic_version(version, "version")
        entry = self._entries.get((diagnostic_id, version))
        if entry is None:
            raise CatalogError(CATALOG_NOT_FOUND, f"{diagnostic_id} has no version {version}")
        return entry

    def history(self, diagnostic_id: str) -> tuple[CatalogEntry, ...]:
        """Every published version, oldest first. Versions are never removed: a stored run stays
        checkable against the declaration it was judged by."""
        check_diagnostic_id(diagnostic_id)
        found = tuple(entry for (name, _), entry in self._entries.items() if name == diagnostic_id)
        if not found:
            raise CatalogError(CATALOG_NOT_FOUND, f"{diagnostic_id} is not an official diagnostic")
        return found

    def versions(self, diagnostic_id: str) -> tuple[int, ...]:
        return tuple(entry.version for (name, _), entry in self._entries.items() if name == diagnostic_id)

    def published_fingerprints(self, diagnostic_id: str) -> Mapping[int, str]:
        """`{version: manifest_fingerprint}` of one diagnostic, empty when it is not published yet.

        This is the history as data, which `promote_scenario` takes so that promotion stays a
        pure function instead of importing this I/O module.
        """
        check_diagnostic_id(diagnostic_id)
        return MappingProxyType({entry.version: entry.manifest_fingerprint
                                 for (name, _), entry in self._entries.items() if name == diagnostic_id})

    def resources_and_cost(self, diagnostic_id: str, profile: ProfileName,
                           version: int | None = None) -> ProfileAvailability:
        """Capabilities, cost bounds and availability of one profile (latest version by default)."""
        return self.describe(diagnostic_id, version).resources_and_cost(profile)

    def check_run(self, run: TestRun) -> None:
        """Re-check a stored run against the exact declaration it was judged by."""
        if not isinstance(run, TestRun):
            raise fail("check_run takes a TestRun")
        check_run_against_spec(run, self.describe(run.diagnostic_id, run.diagnostic_version).diagnostic)

    def to_dict(self) -> list[dict[str, Any]]:
        return [entry.to_dict() for entry in self.list_diagnostics()]


def load_catalog(root: Path | str = DEFAULT_CATALOG_ROOT, *, primitives: PrimitiveRegistry = DEFAULT_PRIMITIVES,
                 implementations: ImplementationRegistry | None = None,
                 sink: DiagnosticSink | None = None) -> Catalog:
    """Read `<root>/catalog.lock.json` and every `<domain>/<name>.v<N>.json` under it.

    Deterministic: files are read in sorted path order. Anything else under the root (a stray
    file, a nested directory, a link, a wrong file name) fails with `testlab_catalog_path_invalid`
    rather than being skipped, so a manifest can never be silently ignored.
    """
    base = Path(root)
    diagnostics = SafeDiagnostics(sink)
    lock = CatalogLock.decode_text(_read_text(base / LOCK_FILE_NAME, LOCK_FILE_NAME), where=LOCK_FILE_NAME)
    manifests = [(path, decode_manifest_text(_read_text(base / path, path), where=path))
                 for path in _manifest_paths(base)]
    catalog = Catalog.build(manifests, lock, primitives=primitives, implementations=implementations)
    diagnostics.emit("testlab.catalog.loaded", "Test Lab catalog loaded", root=str(base),
                     diagnostics=len(catalog.list_diagnostics()), versions=len(catalog.entries))
    return catalog


def _read_text(path: Path, where: str) -> str:
    try:
        if path.stat().st_size > MAX_MANIFEST_BYTES:
            raise CatalogError(CATALOG_READ_FAILED, f"file exceeds {MAX_MANIFEST_BYTES} bytes", path=where)
        return path.read_text(encoding="utf-8")
    except CatalogError:
        raise
    except OSError as exc:
        raise CatalogError(CATALOG_READ_FAILED, type(exc).__name__, path=where) from None
    except UnicodeDecodeError:
        raise CatalogError(CATALOG_READ_FAILED, "file is not UTF-8 text", path=where) from None


def _manifest_paths(base: Path) -> tuple[str, ...]:
    """Sorted `<domain>/<file>` paths. The layout is closed: one directory per domain, one file
    per version, plus the lock at the root."""
    try:
        top = sorted(base.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        raise CatalogError(CATALOG_READ_FAILED, type(exc).__name__, path=str(base)) from None
    paths: list[str] = []
    for item in top:
        # `is_link` covers Windows junctions too: `is_symlink()` is False for one, and a junction
        # would otherwise let the loader read manifests from outside the catalog root.
        if is_link(item):
            raise CatalogError(CATALOG_PATH_INVALID, "the catalog holds no links", path=item.name)
        if item.is_file():
            if item.name != LOCK_FILE_NAME:
                raise CatalogError(CATALOG_PATH_INVALID, "only the lock file lives at the catalog root",
                                   path=item.name)
            continue
        if not item.is_dir() or _DOMAIN_DIR.fullmatch(item.name) is None:
            raise CatalogError(CATALOG_PATH_INVALID, "a catalog root entry must be a domain directory",
                               path=item.name)
        for child in sorted(item.iterdir(), key=lambda entry: entry.name):
            name = f"{item.name}/{child.name}"
            if is_link(child) or not child.is_file() or _MANIFEST_FILE.fullmatch(child.name) is None:
                raise CatalogError(CATALOG_PATH_INVALID, "a domain directory holds only <name>.v<N>.json manifests",
                                   path=name)
            paths.append(name)
    return tuple(paths)

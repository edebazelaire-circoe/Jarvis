"""Official diagnostic manifests and the catalog lock: declarative documents, no code.

Binding contract: `docs/testlab.md` ("Manifests", "Catalog"). Pure: decoding,
validation, fingerprinting and rendering only; reading the files is
`jarvis.testlab.catalog`.

A manifest (`jarvis.testlab.manifest` v1) holds the `DiagnosticSpec` of one version of
one official diagnostic, its run-local override allowlist and, optionally, the
declarative scenario it executes. Implementations are NAMES resolved by
`jarvis.testlab.implementations`; primitives are NAMES resolved by
`jarvis.testlab.primitives`. Nothing in a manifest is imported, evaluated or executed.

The catalog lock (`jarvis.testlab.catalog_lock` v1) records one semantic fingerprint per
`(diagnostic_id, version)`. Editing a published manifest without bumping its version
changes that fingerprint and fails the catalog: stored `TestRun`s keep pointing at the
declaration they were judged by (`check_run_against_spec`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json
from typing import Any

from jarvis.testlab.diagnostics import DiagnosticSpec, MAX_PARAMETERS, ParameterSpec
from jarvis.testlab.identity import (
    TESTLAB_SCHEMA_VERSION,
    check_diagnostic_id,
    check_diagnostic_version,
    diagnostic_domain,
)
from jarvis.testlab.implementations import (
    IMPLEMENTATION_UNKNOWN,
    ImplementationEntry,
    ImplementationRegistry,
)
from jarvis.testlab.primitives import (
    PRIMITIVE_PROFILE_UNSUPPORTED,
    PRIMITIVE_UNKNOWN,
    DEFAULT_PRIMITIVES,
    PrimitiveRegistry,
    ScenarioContext,
    check_scenario,
)
from jarvis.testlab.profiles import ProfileName, ProfileSpec
from jarvis.testlab.scenarios import SHAPE_ONLY, Scenario
from jarvis.testlab.validation import (
    JSON_INVALID,
    LIMIT_EXCEEDED,
    REFERENCE_INVALID,
    TestLabError,
    check_hex,
    check_name,
    check_text,
    content_fingerprint,
    decode_json_document,
    exact_fields,
    fail,
    name_for_message,
    scan_code,
    scan_private,
)

MANIFEST_SCHEMA = "jarvis.testlab.manifest"
CATALOG_LOCK_SCHEMA = "jarvis.testlab.catalog_lock"
MAX_MANIFEST_BYTES = 256 * 1024
MAX_LOCK_BYTES = 512 * 1024
MAX_LOCK_ENTRIES = 1024
MAX_MANIFEST_PATH_CHARS = 160

# Stable catalog error codes (docs/testlab.md, "Errors").
CATALOG_READ_FAILED = "testlab_catalog_read_failed"
CATALOG_JSON_INVALID = "testlab_catalog_json_invalid"
CATALOG_SCHEMA_INVALID = "testlab_catalog_schema_invalid"
CATALOG_PATH_INVALID = "testlab_catalog_path_invalid"
CATALOG_DUPLICATE = "testlab_catalog_duplicate"
CATALOG_HISTORY_GAP = "testlab_catalog_history_gap"
CATALOG_PRIMITIVE_UNKNOWN = "testlab_catalog_primitive_unknown"
CATALOG_PRIMITIVE_UNSUPPORTED = "testlab_catalog_primitive_unsupported"
CATALOG_SCENARIO_INVALID = "testlab_catalog_scenario_invalid"
CATALOG_IMPLEMENTATION_UNKNOWN = "testlab_catalog_implementation_unknown"
CATALOG_IMPLEMENTATION_PROFILE_MISMATCH = "testlab_catalog_implementation_profile_mismatch"
CATALOG_FINGERPRINT_DRIFT = "testlab_catalog_fingerprint_drift"
CATALOG_UNLOCKED = "testlab_catalog_unlocked"
CATALOG_LOCK_ORPHAN = "testlab_catalog_lock_orphan"
CATALOG_LOCK_INVALID = "testlab_catalog_lock_invalid"
CATALOG_NOT_FOUND = "testlab_catalog_not_found"


class CatalogError(TestLabError):
    """A manifest, the lock or a catalog lookup failed. `path` names the file, `cause_code`
    the inner contract error when one was translated."""

    def __init__(self, code: str, detail: str, *, path: str | None = None, cause_code: str | None = None) -> None:
        super().__init__(code, detail if path is None else f"{path}: {detail}")
        self.path = path
        self.cause_code = cause_code


def _catalog_error(code: str, exc: TestLabError, path: str | None) -> CatalogError:
    return CatalogError(code, exc.detail, path=path, cause_code=exc.code)


# ------------------------------------------------------------------ manifest

@dataclass(frozen=True, slots=True)
class DiagnosticManifest:
    """One version of one official diagnostic, as declared on disk."""

    diagnostic: DiagnosticSpec
    #: Settings a run of this diagnostic may override run-locally (never written permanently).
    override_allowlist: tuple[ParameterSpec, ...] = ()
    #: The declarative scenario this diagnostic executes; None when its implementations script it.
    scenario: Scenario | None = None
    schema_version: int = TESTLAB_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != TESTLAB_SCHEMA_VERSION:
            raise fail(f"unsupported schema_version; expected {TESTLAB_SCHEMA_VERSION}")
        if not isinstance(self.diagnostic, DiagnosticSpec):
            raise fail("manifest.diagnostic must be a DiagnosticSpec")
        if (not isinstance(self.override_allowlist, tuple)
                or any(not isinstance(item, ParameterSpec) for item in self.override_allowlist)):
            raise fail("manifest.override_allowlist must be a tuple of ParameterSpec")
        if len(self.override_allowlist) > MAX_PARAMETERS:
            raise fail(f"manifest.override_allowlist exceeds {MAX_PARAMETERS} entries", LIMIT_EXCEEDED)
        names = [item.name for item in self.override_allowlist]
        if len(set(names)) != len(names):
            raise fail("manifest.override_allowlist declares a setting twice")
        declared = {parameter.name for parameter in self.diagnostic.parameters}
        clashing = sorted(set(names) & declared)
        if clashing:
            raise fail(f"manifest.override_allowlist repeats declared parameter(s): {', '.join(clashing)}",
                       REFERENCE_INVALID)
        if self.scenario is not None and not isinstance(self.scenario, Scenario):
            raise fail("manifest.scenario must be a Scenario or null")

    @property
    def diagnostic_id(self) -> str:
        return self.diagnostic.diagnostic_id

    @property
    def version(self) -> int:
        return self.diagnostic.version

    @property
    def relative_path(self) -> str:
        """Where this version lives in the catalog: `<domain>/<rest of the id>.v<N>.json`."""
        return manifest_relative_path(self.diagnostic_id, self.version)

    def to_dict(self) -> dict[str, Any]:
        return {"schema": MANIFEST_SCHEMA, "schema_version": self.schema_version,
                "diagnostic": self.diagnostic.to_dict(),
                "override_allowlist": [item.to_dict() for item in self.override_allowlist],
                "scenario": None if self.scenario is None else self.scenario.to_dict()}

    @classmethod
    def from_dict(cls, payload: object, *, where: str | None = None) -> DiagnosticManifest:
        """Strict decode: private data, then code, then shape, then every contract.

        The scenario is decoded shape-only here; `check_manifest` resolves its primitives
        against the registry, so an unknown primitive gets its own catalog error code.
        """
        try:
            scan_private(payload, "manifest")
            scan_code(payload, "manifest")
            data = exact_fields(payload, _MANIFEST_FIELDS, "manifest")
            if data["schema"] != MANIFEST_SCHEMA or data["schema_version"] != TESTLAB_SCHEMA_VERSION:
                raise fail(f"manifest: unsupported schema; expected {MANIFEST_SCHEMA} version "
                           f"{TESTLAB_SCHEMA_VERSION}")
            allowlist = data["override_allowlist"]
            if not isinstance(allowlist, list):
                raise fail("manifest.override_allowlist must be a list")
            scenario = None if data["scenario"] is None else Scenario.from_dict(data["scenario"],
                                                                                primitives=SHAPE_ONLY)
            return cls(DiagnosticSpec.from_dict(data["diagnostic"]),
                       tuple(ParameterSpec.from_dict(item) for item in allowlist), scenario)
        except CatalogError:
            raise
        except TestLabError as exc:
            code = CATALOG_JSON_INVALID if exc.code in (JSON_INVALID,) else CATALOG_SCHEMA_INVALID
            raise _catalog_error(code, exc, where) from None

    def fingerprint(self) -> str:
        """Semantic fingerprint of the whole declaration, recorded in the catalog lock.

        It covers the diagnostic semantics (`DiagnosticSpec.fingerprint`, which excludes
        cosmetic wording), the override allowlist without its descriptions, and the scenario
        content fingerprint. The scenario is covered exactly: `TestRun.scenario_fingerprint`
        records what executed, so any scenario edit needs a new version.
        """
        return content_fingerprint({
            "diagnostic": self.diagnostic.fingerprint(),
            "override_allowlist": [{key: value for key, value in item.to_dict().items() if key != "description"}
                                   for item in self.override_allowlist],
            "scenario": None if self.scenario is None else self.scenario.fingerprint(),
        })


_MANIFEST_FIELDS = frozenset({"schema", "schema_version", "diagnostic", "override_allowlist", "scenario"})


def manifest_relative_path(diagnostic_id: str, version: int) -> str:
    """`<domain>/<rest of the id>.v<N>.json`, the one place a version may live."""
    check_diagnostic_id(diagnostic_id)
    check_diagnostic_version(version, "version")
    domain = diagnostic_domain(diagnostic_id)
    return f"{domain}/{diagnostic_id[len(domain) + 1:]}.v{version}.json"


def decode_manifest_text(text: str, *, where: str | None = None) -> DiagnosticManifest:
    """Decode manifest file text: JSON rules first (size, duplicates, NaN), then the contract."""
    try:
        payload = decode_json_document(text, max_bytes=MAX_MANIFEST_BYTES)
    except TestLabError as exc:
        raise _catalog_error(CATALOG_JSON_INVALID, exc, where) from None
    return DiagnosticManifest.from_dict(payload, where=where)


def render_manifest(manifest: DiagnosticManifest) -> str:
    """File text of a manifest: indented JSON, UTF-8, trailing newline. Fingerprints cover content,
    never formatting, so a reformat is not drift."""
    if not isinstance(manifest, DiagnosticManifest):
        raise fail("render_manifest takes a DiagnosticManifest")
    return json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def check_manifest(manifest: DiagnosticManifest, *, primitives: PrimitiveRegistry = DEFAULT_PRIMITIVES,
                   implementations: ImplementationRegistry) -> Mapping[ProfileName, ImplementationEntry]:
    """Resolve every profile implementation and check the scenario against every declared profile.

    Returns the resolved entries (a reserved name resolves to an `unavailable` entry, which is a
    declaration, not a failure). Raises `CatalogError` for an unknown implementation, a profile
    mismatch, an unknown primitive, a primitive the declared profile cannot perform, an invalid
    scenario, or a virtual-time timeline longer than a non-virtual profile's declared duration.
    """
    if not isinstance(manifest, DiagnosticManifest):
        raise fail("check_manifest takes a DiagnosticManifest")
    where = manifest.relative_path
    resolved: dict[ProfileName, ImplementationEntry] = {}
    for name, profile in manifest.diagnostic.profiles.items():
        try:
            resolved[name] = implementations.resolve(profile.implementation, name)
        except TestLabError as exc:
            code = (CATALOG_IMPLEMENTATION_UNKNOWN if exc.code == IMPLEMENTATION_UNKNOWN
                    else CATALOG_IMPLEMENTATION_PROFILE_MISMATCH)
            raise _catalog_error(code, exc, where) from None
    if manifest.scenario is not None:
        _check_manifest_scenario(manifest, primitives, where)
    return resolved


def _check_manifest_scenario(manifest: DiagnosticManifest, primitives: PrimitiveRegistry, where: str) -> None:
    context = ScenarioContext.for_diagnostic(manifest.diagnostic, manifest.override_allowlist)
    try:
        checked = check_scenario(manifest.scenario, primitives=primitives,
                                 profiles=manifest.diagnostic.profiles, context=context)
    except TestLabError as exc:
        code = {PRIMITIVE_UNKNOWN: CATALOG_PRIMITIVE_UNKNOWN,
                PRIMITIVE_PROFILE_UNSUPPORTED: CATALOG_PRIMITIVE_UNSUPPORTED}.get(exc.code, CATALOG_SCENARIO_INVALID)
        raise _catalog_error(code, exc, where) from None
    for profile in manifest.diagnostic.profiles.values():
        _check_timeline_fits(profile, checked.end_ms, where)


def _check_timeline_fits(profile: ProfileSpec, end_ms: int, where: str) -> None:
    """On a profile that spends real time, the scenario timeline is wall time: it must fit the
    declared `max_duration_s`. Virtual time is simulated, so `virtual` is exempt."""
    if profile.name is ProfileName.VIRTUAL or end_ms <= profile.cost.max_duration_s * 1000:
        return
    raise CatalogError(CATALOG_SCENARIO_INVALID,
                       f"scenario timeline ({end_ms} ms) exceeds profile {profile.name.value} "
                       f"max_duration_s ({profile.cost.max_duration_s})", path=where)


# ---------------------------------------------------------------------- lock

@dataclass(frozen=True, slots=True)
class LockEntry:
    """One published version: where it lives and the fingerprint it was published with."""

    diagnostic_id: str
    version: int
    path: str
    manifest_fingerprint: str

    def __post_init__(self) -> None:
        check_diagnostic_id(self.diagnostic_id)
        check_diagnostic_version(self.version, "version")
        check_text(self.path, "lock.path", max_chars=MAX_MANIFEST_PATH_CHARS)
        if self.path != manifest_relative_path(self.diagnostic_id, self.version):
            raise fail("lock.path must be the manifest path of that diagnostic id and version", REFERENCE_INVALID)
        check_hex(self.manifest_fingerprint, "lock.manifest_fingerprint", lengths=(64,))

    @property
    def key(self) -> tuple[str, int]:
        return self.diagnostic_id, self.version

    def to_dict(self) -> dict[str, Any]:
        return {"diagnostic_id": self.diagnostic_id, "version": self.version, "path": self.path,
                "manifest_fingerprint": self.manifest_fingerprint}

    @classmethod
    def from_dict(cls, payload: object, where: str = "lock.entries[]") -> LockEntry:
        data = exact_fields(payload, _LOCK_ENTRY_FIELDS, where)
        return cls(data["diagnostic_id"], data["version"], data["path"], data["manifest_fingerprint"])


_LOCK_ENTRY_FIELDS = frozenset({"diagnostic_id", "version", "path", "manifest_fingerprint"})


def lock_entry_for(manifest: DiagnosticManifest) -> LockEntry:
    """The lock line a manifest must be published with."""
    return LockEntry(manifest.diagnostic_id, manifest.version, manifest.relative_path, manifest.fingerprint())


@dataclass(frozen=True, slots=True)
class CatalogLock:
    """The published fingerprints, sorted by `(diagnostic_id, version)`."""

    entries: tuple[LockEntry, ...] = ()
    schema_version: int = TESTLAB_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != TESTLAB_SCHEMA_VERSION:
            raise fail(f"unsupported schema_version; expected {TESTLAB_SCHEMA_VERSION}")
        if not isinstance(self.entries, tuple) or any(not isinstance(item, LockEntry) for item in self.entries):
            raise fail("lock.entries must be a tuple of LockEntry")
        if len(self.entries) > MAX_LOCK_ENTRIES:
            raise fail(f"lock.entries exceeds {MAX_LOCK_ENTRIES} entries", LIMIT_EXCEEDED)
        keys = [entry.key for entry in self.entries]
        if len(set(keys)) != len(keys):
            raise CatalogError(CATALOG_LOCK_INVALID, "a diagnostic version is locked twice")
        object.__setattr__(self, "entries", tuple(sorted(self.entries, key=lambda entry: entry.key)))

    def get(self, diagnostic_id: str, version: int) -> LockEntry | None:
        return self.index.get((diagnostic_id, version))

    @property
    def index(self) -> Mapping[tuple[str, int], LockEntry]:
        return {entry.key: entry for entry in self.entries}

    def with_entry(self, entry: LockEntry) -> CatalogLock:
        """The lock plus one new version (the human's publication step). Never replaces a version."""
        if not isinstance(entry, LockEntry):
            raise fail("with_entry takes a LockEntry")
        if self.get(*entry.key) is not None:
            raise CatalogError(CATALOG_LOCK_INVALID,
                               f"{entry.diagnostic_id} v{entry.version} is already locked; bump the version")
        return CatalogLock((*self.entries, entry))

    def to_dict(self) -> dict[str, Any]:
        return {"schema": CATALOG_LOCK_SCHEMA, "schema_version": self.schema_version,
                "entries": [entry.to_dict() for entry in self.entries]}

    def render(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, allow_nan=False) + "\n"

    @classmethod
    def from_dict(cls, payload: object, *, where: str | None = None) -> CatalogLock:
        try:
            data = exact_fields(payload, _LOCK_FIELDS, "lock")
            if data["schema"] != CATALOG_LOCK_SCHEMA or data["schema_version"] != TESTLAB_SCHEMA_VERSION:
                raise fail(f"lock: unsupported schema; expected {CATALOG_LOCK_SCHEMA} version "
                           f"{TESTLAB_SCHEMA_VERSION}")
            if not isinstance(data["entries"], list):
                raise fail("lock.entries must be a list")
            return cls(tuple(LockEntry.from_dict(item, f"lock.entries[{index}]")
                             for index, item in enumerate(data["entries"])))
        except CatalogError:
            raise
        except TestLabError as exc:
            raise _catalog_error(CATALOG_LOCK_INVALID, exc, where) from None

    @classmethod
    def decode_text(cls, text: str, *, where: str | None = None) -> CatalogLock:
        try:
            payload = decode_json_document(text, max_bytes=MAX_LOCK_BYTES)
        except TestLabError as exc:
            raise _catalog_error(CATALOG_LOCK_INVALID, exc, where) from None
        return cls.from_dict(payload, where=where)


_LOCK_FIELDS = frozenset({"schema", "schema_version", "entries"})


def build_lock(manifests: Iterable[DiagnosticManifest]) -> CatalogLock:
    """The lock that the given manifests would publish (used to rewrite it after a promotion)."""
    return CatalogLock(tuple(lock_entry_for(manifest) for manifest in manifests))


def check_lock_coverage(manifests: Mapping[tuple[str, int], DiagnosticManifest], lock: CatalogLock) -> None:
    """Every manifest is locked with its current fingerprint, and every locked version still exists.

    An edit without a version bump fails with `testlab_catalog_fingerprint_drift`; a new manifest
    that nobody published fails with `testlab_catalog_unlocked`; a deleted version (which stored
    runs may still reference) fails with `testlab_catalog_lock_orphan`.
    """
    index = lock.index
    for key, manifest in manifests.items():
        entry = index.get(key)
        path = manifest.relative_path
        if entry is None:
            raise CatalogError(CATALOG_UNLOCKED, f"{manifest.diagnostic_id} v{manifest.version} is not in the "
                                                 "catalog lock; publish it with its fingerprint", path=path)
        if entry.manifest_fingerprint != manifest.fingerprint():
            raise CatalogError(CATALOG_FINGERPRINT_DRIFT,
                               f"{manifest.diagnostic_id} v{manifest.version} was edited in place; bump the version "
                               "or restore the published content", path=path)
    for key, entry in index.items():
        if key not in manifests:
            raise CatalogError(CATALOG_LOCK_ORPHAN,
                               f"{entry.diagnostic_id} v{entry.version} is locked but its manifest is missing; "
                               "published versions are kept so stored runs stay checkable", path=entry.path)


def check_history(manifests: Mapping[tuple[str, int], DiagnosticManifest]) -> None:
    """Versions of one diagnostic are 1..N with no hole: history is never rewritten."""
    versions: dict[str, list[int]] = {}
    for diagnostic_id, version in manifests:
        versions.setdefault(diagnostic_id, []).append(version)
    for diagnostic_id, found in sorted(versions.items()):
        expected = list(range(1, len(found) + 1))
        if sorted(found) != expected:
            raise CatalogError(CATALOG_HISTORY_GAP,
                               f"{name_for_message(diagnostic_id)} versions must be 1..{len(found)} with no hole")


def check_manifest_name(diagnostic_id: str, version: int, path: str) -> None:
    """The file path must be exactly the one its identity dictates (no second home for a version)."""
    check_name(diagnostic_id, "diagnostic_id")
    expected = manifest_relative_path(diagnostic_id, version)
    if path != expected:
        raise CatalogError(CATALOG_PATH_INVALID, f"manifest declares {diagnostic_id} v{version}, which belongs at "
                                                 f"{expected}", path=path)

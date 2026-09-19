"""Promotion: an ad-hoc scenario plus a declared skeleton become an official manifest version.

Binding contract: `docs/testlab.md` ("Promotion"). Pure: it returns the manifest CONTENT
and its fingerprint; it never writes into the repository, never reaches the network and
never runs anything. It does not import the catalog either: the published history arrives
as data (`{version: manifest_fingerprint}`), which the I/O catalog hands over with
`Catalog.published_fingerprints(diagnostic_id)`. A human reviews the returned content, writes the file at the
returned path, adds the returned lock entry and commits: promotion is a proposal, the
review is the gate.

Refusals are explicit (`PromotionRefused`, one stable code each): a version that already
exists with different semantics, a scenario primitive a declared profile cannot perform,
an assertion or expectation on an undeclared metric, an unknown primitive or
implementation, an invalid skeleton.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from jarvis.testlab.diagnostics import (
    AssertionSpec,
    DiagnosticSpec,
    MetricSpec,
    ParameterSpec,
    ScoreContract,
)
from jarvis.testlab.identity import check_diagnostic_id, check_diagnostic_version
from jarvis.testlab.implementations import ImplementationRegistry
from jarvis.testlab.manifests import (
    CATALOG_IMPLEMENTATION_PROFILE_MISMATCH,
    CATALOG_IMPLEMENTATION_UNKNOWN,
    CATALOG_PRIMITIVE_UNKNOWN,
    CATALOG_PRIMITIVE_UNSUPPORTED,
    CatalogError,
    DiagnosticManifest,
    LockEntry,
    check_manifest,
    lock_entry_for,
    render_manifest,
)
from jarvis.testlab.primitives import DEFAULT_PRIMITIVES, PrimitiveRegistry
from jarvis.testlab.profiles import ProfileSpec, profiles_by_name
from jarvis.testlab.scenarios import Scenario
from jarvis.testlab.validation import TestLabError, check_hex, exact_fields, fail, scan_code, scan_private

PROMOTION_VERSION_CONFLICT = "testlab_promotion_version_conflict"
PROMOTION_VERSION_GAP = "testlab_promotion_version_gap"
PROMOTION_PROFILE_UNSUPPORTED = "testlab_promotion_profile_unsupported"
PROMOTION_METRIC_UNDECLARED = "testlab_promotion_metric_undeclared"
PROMOTION_ASSERTION_UNDECLARED = "testlab_promotion_assertion_undeclared"
PROMOTION_PRIMITIVE_UNKNOWN = "testlab_promotion_primitive_unknown"
PROMOTION_IMPLEMENTATION_UNKNOWN = "testlab_promotion_implementation_unknown"
PROMOTION_SKELETON_INVALID = "testlab_promotion_skeleton_invalid"
PROMOTION_SCENARIO_INVALID = "testlab_promotion_scenario_invalid"


class PromotionRefused(TestLabError):
    """Promotion refused. `cause_code` keeps the inner contract error when one was translated."""

    def __init__(self, code: str, detail: str, cause_code: str | None = None) -> None:
        super().__init__(code, detail)
        self.cause_code = cause_code


@dataclass(frozen=True, slots=True)
class PromotionResult:
    """What the human publishes. Nothing is written by this module."""

    manifest: DiagnosticManifest
    #: Repo-relative path under the catalog root (`<domain>/<name>.v<N>.json`).
    path: str
    manifest_text: str
    manifest_fingerprint: str
    lock_entry: LockEntry
    #: True when this exact content is already published at this version (nothing to write).
    existing: bool = False

    @property
    def diagnostic_id(self) -> str:
        return self.manifest.diagnostic_id

    @property
    def version(self) -> int:
        return self.manifest.version

    def to_dict(self) -> dict[str, Any]:
        return {"diagnostic_id": self.diagnostic_id, "version": self.version, "path": self.path,
                "manifest_fingerprint": self.manifest_fingerprint, "existing": self.existing,
                "lock_entry": self.lock_entry.to_dict()}


#: What a human or an agent authors around a working ad-hoc scenario.
SKELETON_FIELDS = frozenset({"diagnostic_id", "title", "description", "profiles", "parameters", "metrics",
                             "assertions", "score", "override_allowlist"})


def promote_scenario(scenario: Scenario, skeleton: Mapping[str, Any], *,
                     published: Mapping[int, str] = MappingProxyType({}), version: int | None = None,
                     primitives: PrimitiveRegistry = DEFAULT_PRIMITIVES,
                     implementations: ImplementationRegistry) -> PromotionResult:
    """Turn a working ad-hoc scenario into the content of official manifest version N+1 (or 1).

    `skeleton` is the declarative part a human writes: id, title, description, profiles with
    their registered implementation names, parameters, metrics, assertions, score and override
    allowlist (same wire shapes as a manifest). `published` is the history of THAT diagnostic as
    data, `{version: manifest_fingerprint}` (`Catalog.published_fingerprints(diagnostic_id)`),
    empty for a new diagnostic: promotion reads the catalog as data, never as a module, so it
    stays pure. `version` pins the target; by default the next version is used, and an unchanged
    re-promotion returns the existing version untouched.
    """
    if not isinstance(scenario, Scenario):
        raise fail("promote_scenario takes a Scenario")
    published = _checked_history(published)
    declared = _decode_skeleton(skeleton)
    _check_references(declared, scenario)
    target = _target_version(declared, scenario, published, version)
    manifest = _build_manifest(declared, scenario, target)
    try:
        check_manifest(manifest, primitives=primitives, implementations=implementations)
    except CatalogError as exc:
        raise PromotionRefused(_REFUSALS.get(exc.code, PROMOTION_SCENARIO_INVALID), exc.detail, exc.cause_code
                               or exc.code) from None
    fingerprint = manifest.fingerprint()
    existing = published.get(target)
    if existing is not None and existing != fingerprint:
        raise PromotionRefused(PROMOTION_VERSION_CONFLICT,
                               f"{manifest.diagnostic_id} v{target} is already published with different semantics; "
                               "promote the next version instead")
    return PromotionResult(manifest, manifest.relative_path, render_manifest(manifest), fingerprint,
                           lock_entry_for(manifest), existing is not None)


_REFUSALS = {
    CATALOG_PRIMITIVE_UNKNOWN: PROMOTION_PRIMITIVE_UNKNOWN,
    CATALOG_PRIMITIVE_UNSUPPORTED: PROMOTION_PROFILE_UNSUPPORTED,
    CATALOG_IMPLEMENTATION_UNKNOWN: PROMOTION_IMPLEMENTATION_UNKNOWN,
    CATALOG_IMPLEMENTATION_PROFILE_MISMATCH: PROMOTION_IMPLEMENTATION_UNKNOWN,
}


def _decode_skeleton(skeleton: Mapping[str, Any]) -> dict[str, Any]:
    try:
        scan_private(skeleton, "skeleton")
        scan_code(skeleton, "skeleton")
        data = exact_fields(skeleton, SKELETON_FIELDS, "skeleton")
        check_diagnostic_id(data["diagnostic_id"])
        decoded = {
            "diagnostic_id": data["diagnostic_id"],
            "title": data["title"],
            "description": data["description"],
            "profiles": tuple(ProfileSpec.from_dict(item) for item in _list(data["profiles"], "skeleton.profiles")),
            "parameters": tuple(ParameterSpec.from_dict(item)
                                for item in _list(data["parameters"], "skeleton.parameters")),
            "metrics": tuple(MetricSpec.from_dict(item) for item in _list(data["metrics"], "skeleton.metrics")),
            "assertions": tuple(AssertionSpec.from_dict(item)
                                for item in _list(data["assertions"], "skeleton.assertions")),
            "score": ScoreContract.from_dict(data["score"]),
            "override_allowlist": tuple(ParameterSpec.from_dict(item)
                                        for item in _list(data["override_allowlist"],
                                                          "skeleton.override_allowlist")),
        }
    except TestLabError as exc:
        raise PromotionRefused(PROMOTION_SKELETON_INVALID, exc.detail, exc.code) from None
    return decoded


def _list(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise fail(f"{name} must be a list")
    return value


def _check_references(declared: Mapping[str, Any], scenario: Scenario) -> None:
    """Assertions and scenario expectations may only name declared metrics and assertions."""
    metrics = {metric.name for metric in declared["metrics"]}
    assertions = {assertion.assertion_id for assertion in declared["assertions"]}
    for assertion in declared["assertions"]:
        if assertion.metric not in metrics:
            raise PromotionRefused(PROMOTION_METRIC_UNDECLARED,
                                   f"assertion {assertion.assertion_id} measures undeclared metric "
                                   f"{assertion.metric}")
    for index, step in enumerate(scenario.steps):
        if step.primitive == "expect.metric" and step.args.get("metric") not in metrics:
            raise PromotionRefused(PROMOTION_METRIC_UNDECLARED,
                                   f"steps[{index}] expects an undeclared metric")
        if step.primitive == "expect.assertion" and step.args.get("assertion_id") not in assertions:
            raise PromotionRefused(PROMOTION_ASSERTION_UNDECLARED,
                                   f"steps[{index}] expects an undeclared assertion")


def _checked_history(published: object) -> Mapping[int, str]:
    """The published history as data: `{version: manifest_fingerprint}`, validated before use."""
    if not isinstance(published, Mapping):
        raise fail("published must map each published version to its manifest fingerprint")
    for version, fingerprint in published.items():
        check_diagnostic_version(version, "published version")
        check_hex(fingerprint, f"published[{version}]", lengths=(64,))
    return published


def _target_version(declared: Mapping[str, Any], scenario: Scenario, published: Mapping[int, str],
                    version: int | None) -> int:
    """The next version, unless the latest one already carries exactly this content (idempotent)."""
    latest = max(published, default=0)
    if version is None:
        if latest and _build_manifest(declared, scenario, latest).fingerprint() == published[latest]:
            return latest
        return latest + 1
    check_diagnostic_version(version, "version")
    if version not in published and version != latest + 1:
        raise PromotionRefused(PROMOTION_VERSION_GAP,
                               f"version {version} is neither published nor the next one ({latest + 1})")
    return version


def _build_manifest(declared: Mapping[str, Any], scenario: Scenario, version: int) -> DiagnosticManifest:
    try:
        spec = DiagnosticSpec(
            declared["diagnostic_id"], version, declared["title"],
            declared["diagnostic_id"].split(".", 1)[0], profiles_by_name(declared["profiles"]),
            declared["metrics"], declared["assertions"], declared["score"], declared["parameters"],
            declared["description"])
        return DiagnosticManifest(spec, declared["override_allowlist"], scenario)
    except TestLabError as exc:
        raise PromotionRefused(PROMOTION_SKELETON_INVALID, exc.detail, exc.code) from None

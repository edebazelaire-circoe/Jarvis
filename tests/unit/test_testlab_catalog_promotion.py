"""Conformance tests for ad-hoc scenario promotion (docs/testlab.md, Promotion)."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.testlab.catalog import LOCK_FILE_NAME, load_catalog
from jarvis.testlab.implementations import default_implementations
from jarvis.testlab.manifests import CatalogLock, build_lock, decode_manifest_text, render_manifest
from jarvis.testlab.primitives import AT_MS
from jarvis.testlab.promotion import (
    PROMOTION_ASSERTION_UNDECLARED,
    PROMOTION_IMPLEMENTATION_UNKNOWN,
    PROMOTION_METRIC_UNDECLARED,
    PROMOTION_PRIMITIVE_UNKNOWN,
    PROMOTION_PROFILE_UNSUPPORTED,
    PROMOTION_SKELETON_INVALID,
    PROMOTION_VERSION_CONFLICT,
    PROMOTION_VERSION_GAP,
    PromotionRefused,
    promote_scenario,
)
from jarvis.testlab.scenarios import Scenario, ScenarioStep
from jarvis.testlab.validation import FORBIDDEN_CODE, FORBIDDEN_PRIVATE_DATA

VIRTUAL_PROFILE = {"name": "virtual", "implementation": "testlab.scenario.virtual", "requires": [],
                   "cost": {"max_duration_s": 60, "max_cost_usd": 0}}
LIVE_PROFILE = {"name": "live", "implementation": "testlab.scenario.live", "requires": ["realtime_provider"],
                "cost": {"max_duration_s": 300, "max_cost_usd": 0.5}}
METRIC = {"name": "barge_in.false_confirmed_count", "unit": "count", "direction": "lower_better",
          "description": None}
ASSERTION = {"assertion_id": "no_false_barge_in", "metric": "barge_in.false_confirmed_count", "comparator": "eq",
             "threshold": 0, "blocking": True, "description": None}


def scenario(*steps: tuple[str, dict], scenario_id: str = "voice.echo_probe") -> Scenario:
    if not steps:
        steps = (("user.turn", {AT_MS: 0, "turn_id": "t1", "content_tag": "hello"}),
                 ("control.checkpoint", {AT_MS: 500, "checkpoint_id": "settled"}))
    return Scenario(scenario_id, tuple(ScenarioStep(primitive, args) for primitive, args in steps))


def skeleton(**changes) -> dict:
    document = {
        "diagnostic_id": "voice.echo_probe",
        "title": "Echo probe",
        "description": "Ad-hoc reproduction promoted after review.",
        "profiles": [dict(VIRTUAL_PROFILE)],
        "parameters": [],
        "metrics": [dict(METRIC)],
        "assertions": [dict(ASSERTION)],
        "score": {"method": "none", "components": []},
        "override_allowlist": [],
    }
    document.update(changes)
    return document


def empty_catalog(tmp_path: Path):
    root = tmp_path / "catalog"
    root.mkdir(parents=True, exist_ok=True)
    (root / LOCK_FILE_NAME).write_text(CatalogLock().render(), encoding="utf-8")
    return load_catalog(root, implementations=default_implementations())


def published(tmp_path: Path, *results):
    """Write promotion results into a catalog root the way the human reviewer would, then load it."""
    root = tmp_path / "published"
    lock = CatalogLock()
    for result in results:
        path = root / result.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(result.manifest_text, encoding="utf-8")
        lock = lock.with_entry(result.lock_entry)
    (root / LOCK_FILE_NAME).write_text(lock.render(), encoding="utf-8")
    return load_catalog(root, implementations=default_implementations())


def promote(catalog, **options):
    """Promotion takes the published history as data; the catalog only hands it over."""
    options.setdefault("scenario", scenario())
    options.setdefault("skeleton", skeleton())
    document = options.pop("skeleton")
    diagnostic_id = document.get("diagnostic_id") if isinstance(document, dict) else None
    history = (catalog.published_fingerprints(diagnostic_id)
               if isinstance(diagnostic_id, str) and diagnostic_id.count(".") == 1 else {})
    return promote_scenario(options.pop("scenario"), document, published=history,
                            implementations=default_implementations(), **options)


def refusal(catalog, **options) -> PromotionRefused:
    with pytest.raises(PromotionRefused) as caught:
        promote(catalog, **options)
    return caught.value


# ------------------------------------------------------------------ success

def test_promotion_needs_no_catalog_module_only_the_history_as_data():
    result = promote_scenario(scenario(), skeleton(), implementations=default_implementations())
    assert result.version == 1 and not result.existing
    with pytest.raises(Exception):
        promote_scenario(scenario(), skeleton(), published={1: "not-a-fingerprint"},
                         implementations=default_implementations())


def test_the_catalog_hands_the_history_over_as_data(tmp_path):
    first = promote(empty_catalog(tmp_path))
    catalog = published(tmp_path, first)
    assert dict(catalog.published_fingerprints("voice.echo_probe")) == {1: first.manifest_fingerprint}
    assert dict(catalog.published_fingerprints("voice.absent")) == {}


def test_promotion_returns_content_and_writes_nothing(tmp_path):
    catalog = empty_catalog(tmp_path)
    result = promote(catalog)

    assert (result.diagnostic_id, result.version, result.path) == ("voice.echo_probe", 1,
                                                                   "voice/echo_probe.v1.json")
    assert not result.existing
    assert not (tmp_path / "catalog" / result.path).exists()
    assert not (Path("jarvis/testlab/official") / result.path).exists()
    decoded = decode_manifest_text(result.manifest_text)
    assert decoded.fingerprint() == result.manifest_fingerprint == result.lock_entry.manifest_fingerprint
    assert decoded.scenario.fingerprint() == scenario().fingerprint()
    assert render_manifest(result.manifest) == result.manifest_text


def test_the_published_manifest_loads_as_an_official_diagnostic(tmp_path):
    result = promote(empty_catalog(tmp_path))
    catalog = published(tmp_path, result)
    entry = catalog.describe("voice.echo_probe")
    assert entry.version == 1 and entry.manifest_fingerprint == result.manifest_fingerprint
    assert entry.manifest.scenario.steps[0].primitive == "user.turn"


def test_a_changed_promotion_becomes_the_next_version_and_history_is_kept(tmp_path):
    first = promote(empty_catalog(tmp_path))
    catalog = published(tmp_path, first)
    second = promote(catalog, skeleton=skeleton(assertions=[dict(ASSERTION, threshold=1)]))
    assert second.version == 2
    assert [entry.version for entry in published(tmp_path, first, second).history("voice.echo_probe")] == [1, 2]


def test_promoting_unchanged_content_returns_the_published_version(tmp_path):
    first = promote(empty_catalog(tmp_path))
    again = promote(published(tmp_path, first))
    assert again.version == 1 and again.existing and again.manifest_fingerprint == first.manifest_fingerprint


def test_a_wording_only_repromotion_stays_on_the_published_version(tmp_path):
    first = promote(empty_catalog(tmp_path))
    catalog = published(tmp_path, first)
    reworded = promote(catalog, skeleton=skeleton(title="Echo probe, reworded"))
    assert reworded.version == 1 and reworded.existing
    assert reworded.manifest_fingerprint == first.manifest_fingerprint
    assert reworded.manifest_text != first.manifest_text  # the file may be rewritten, the lock stays
    assert published(tmp_path, reworded).describe("voice.echo_probe").diagnostic.title == "Echo probe, reworded"


def test_a_scenario_wording_change_needs_the_next_version(tmp_path):
    first = promote(empty_catalog(tmp_path))
    titled = Scenario(scenario().scenario_id, scenario().steps, title="Retitled script")
    assert promote(published(tmp_path, first), scenario=titled).version == 2


# ----------------------------------------------------------------- refusals

def test_an_existing_version_with_other_semantics_is_refused(tmp_path):
    first = promote(empty_catalog(tmp_path))
    catalog = published(tmp_path, first)
    error = refusal(catalog, version=1, skeleton=skeleton(assertions=[dict(ASSERTION, threshold=2)]))
    assert error.code == PROMOTION_VERSION_CONFLICT
    assert promote(catalog, version=1).existing


def test_a_version_that_is_neither_published_nor_next_is_refused(tmp_path):
    assert refusal(empty_catalog(tmp_path), version=5).code == PROMOTION_VERSION_GAP


def test_a_primitive_no_declared_profile_supports_is_refused(tmp_path):
    error = refusal(empty_catalog(tmp_path), skeleton=skeleton(profiles=[dict(VIRTUAL_PROFILE), dict(LIVE_PROFILE)]))
    assert error.code == PROMOTION_PROFILE_UNSUPPORTED


def test_an_unknown_primitive_is_refused(tmp_path):
    error = refusal(empty_catalog(tmp_path), scenario=scenario(("shell.run", {AT_MS: 0})))
    assert error.code == PROMOTION_PRIMITIVE_UNKNOWN


@pytest.mark.parametrize(("changes", "code"), [
    ({"assertions": [dict(ASSERTION, metric="absent.metric")]}, PROMOTION_METRIC_UNDECLARED),
    ({"metrics": [], "assertions": [dict(ASSERTION)]}, PROMOTION_METRIC_UNDECLARED),
])
def test_an_assertion_on_an_undeclared_metric_is_refused(tmp_path, changes, code):
    assert refusal(empty_catalog(tmp_path), skeleton=skeleton(**changes)).code == code


def test_an_expectation_on_an_undeclared_metric_or_assertion_is_refused(tmp_path):
    catalog = empty_catalog(tmp_path)
    metric_step = ("expect.metric", {AT_MS: 0, "metric": "absent.metric", "comparator": "le", "threshold": 1})
    assertion_step = ("expect.assertion", {AT_MS: 0, "assertion_id": "absent", "outcome": "failed"})
    assert refusal(catalog, scenario=scenario(metric_step)).code == PROMOTION_METRIC_UNDECLARED
    assert refusal(catalog, scenario=scenario(assertion_step)).code == PROMOTION_ASSERTION_UNDECLARED


def test_an_unknown_implementation_name_is_refused(tmp_path):
    profile = dict(VIRTUAL_PROFILE, implementation="jarvis.runtime.app")
    assert refusal(empty_catalog(tmp_path), skeleton=skeleton(profiles=[profile])).code == (
        PROMOTION_IMPLEMENTATION_UNKNOWN)


@pytest.mark.parametrize("changes", [
    {"assertions": [dict(ASSERTION, blocking=False)]},
    {"profiles": []},
    {"metrics": [dict(METRIC, unit="parsecs")]},
    {"diagnostic_id": "novoicedomain"},
])
def test_an_invalid_skeleton_is_refused_with_its_cause(tmp_path, changes):
    error = refusal(empty_catalog(tmp_path), skeleton=skeleton(**changes))
    assert error.code == PROMOTION_SKELETON_INVALID and error.cause_code


def test_a_skeleton_with_unknown_or_missing_fields_is_refused(tmp_path):
    catalog = empty_catalog(tmp_path)
    assert refusal(catalog, skeleton=skeleton(surprise=True)).code == PROMOTION_SKELETON_INVALID
    incomplete = skeleton()
    incomplete.pop("metrics")
    assert refusal(catalog, skeleton=incomplete).code == PROMOTION_SKELETON_INVALID


def test_a_skeleton_can_never_carry_code_or_private_data(tmp_path):
    catalog = empty_catalog(tmp_path)
    for key, cause in (("command", FORBIDDEN_CODE), ("api_key", FORBIDDEN_PRIVATE_DATA)):
        error = refusal(catalog, skeleton=skeleton(**{key: "x"}))
        assert error.code == PROMOTION_SKELETON_INVALID and error.cause_code == cause


def test_promotion_keeps_the_scenario_provenance(tmp_path):
    from jarvis.testlab.replay import load_replay_scenario

    incident = load_replay_scenario(Path("tests/fixtures/voice_replay/stale_ack_35_9s.json"))
    result = promote(empty_catalog(tmp_path), scenario=incident)
    provenance = decode_manifest_text(result.manifest_text).scenario.provenance
    assert provenance.source_path.endswith("transcript-2026-09-11.md")
    assert provenance.reported and provenance.constructed


def test_the_lock_entry_rewrites_the_lock_deterministically(tmp_path):
    result = promote(empty_catalog(tmp_path))
    catalog = published(tmp_path, result)
    assert build_lock([entry.manifest for entry in catalog.entries]).render() == CatalogLock(
        (result.lock_entry,)).render()

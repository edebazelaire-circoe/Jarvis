"""Instantané `work-methods.json` des versions promues, lu par le hook sans réseau (Slice 12, reprise QA N1a).

Dossiers temporaires seulement.
"""

from __future__ import annotations

from dataclasses import replace
import json

import pytest

from jarvis.domain.work_methods import MethodError, MethodOrigin, MethodProvenance, builtin_method
from jarvis.runtime import work_methods_snapshot as snap
from tests.fakes.mission_history import at


def promoted(version: int):
    return replace(builtin_method("deep-research"), version=version, provenance=MethodProvenance(
        origin=MethodOrigin.PROMOTED, candidate_id="wmc-0123456789abcdef", promoted_by="user", promoted_at=at(1),
        evidence_refs=("m1",)))


def test_absent_means_no_promotion(tmp_path):
    assert snap.read_promoted(tmp_path) == {} and snap.read_payloads(tmp_path) is None


def test_round_trip_keeps_only_promoted_versions_and_returns_the_latest(tmp_path):
    snap.write_snapshot(tmp_path, [promoted(3), builtin_method("quick-research"), promoted(2)])
    raw = json.loads(snap.snapshot_path(tmp_path).read_text(encoding="utf-8"))
    assert raw["schema"] == 1 and [m["version"] for m in raw["methods"]] == [2, 3]
    assert snap.read_promoted(tmp_path)["deep-research"].key == "deep-research@3"
    assert not list(tmp_path.glob(".work-methods-*.tmp"))  # écriture atomique, rien ne traîne


def test_a_plan_shaped_entry_is_refused_by_name(tmp_path):
    payload = {**promoted(2).to_payload(), "steps": ["chercher", "puis comparer"]}
    snap.snapshot_path(tmp_path).write_text(json.dumps({"schema": 1, "methods": [payload]}), encoding="utf-8")
    with pytest.raises(MethodError) as caught:
        snap.read_promoted(tmp_path)
    assert caught.value.code == "work_method_is_not_a_plan"


def test_an_oversized_or_foreign_file_is_refused(tmp_path, monkeypatch):
    snap.snapshot_path(tmp_path).write_text(json.dumps({"schema": 2, "methods": []}), encoding="utf-8")
    with pytest.raises(ValueError):
        snap.read_promoted(tmp_path)
    monkeypatch.setattr(snap, "MAX_SNAPSHOT_BYTES", 8)
    with pytest.raises(ValueError):
        snap.read_promoted(tmp_path)

"""Regles pures du rechargement a chaud (jarvis-interactive-presentation-studio, Slice 06).

Requete, candidat, continuite des valeurs studio (conservees / remises a zero nommees / refusees), rapport de montage et
forme du resultat. Aucun disque, aucun reseau. Contrat : `docs/presentation-studio.md` > *Hot reload contract*.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from jarvis.domain.prefab import PrefabRef, is_prefab_id, parse_manifest
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_edit import StudioActor
from jarvis.domain.presentation_studio_reload import (
    MountOutcome, ReloadResult, ReloadStatus, StateReset, compose_candidate, parse_mount_report, parse_source_edit,
    plan_carry_over, scene_problems, source_prefab_id, unsafe_manifest_key,
)
from jarvis.domain.presentation_studio_scene import ScoreAnchor, StudioControl, StudioScene

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "prefabs" / "test.counter" / "1"
RAW = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
SID, PID = "pss_0000000000a1", "pst_" + "ab" * 16


def manifest(mutate=None, version=2):
    raw = copy.deepcopy(RAW)
    raw["version"] = version
    if mutate:
        mutate(raw)
    return parse_manifest(raw)


def scene(**changes):
    controls = (StudioControl("headline", "props.label", "Titre", "content"),
                StudioControl("start_count", "data.count", "Valeur", "content", default=10),
                StudioControl("density", "props.mode", "Densite", "layout"))
    anchors = (ScoreAnchor("reveal", "Reveler", "start_count"), ScoreAnchor("beat", "Repere"))
    base = dict(scene_id=SID, prefab=PrefabRef("test.counter", 1), title="Ouverture", props={"label": "Visiteurs", "mode": "full"},
                data={"count": 12}, controls=controls, anchors=anchors)
    base.update(changes)
    return StudioScene(**base)


def refused(call, code=C.INVALID_PRESENTATION, needle=""):
    with pytest.raises(PresentationStudioError) as caught:
        call()
    assert caught.value.code is code and needle in caught.value.message, caught.value
    return caught.value


# ------------------------------------------------------------------ requete

def request(**changes):
    body = {"actor": "user", "basis": {"variant_revision": 3}, "scene_id": SID, "files": {"style": "p{color:red}"}}
    body.update(changes)
    return body


def test_a_source_edit_request_is_exact_and_bounded():
    parsed = parse_source_edit(request(request_id="psq_0123456789ab", allow_state_reset=True))
    assert (parsed.actor, parsed.basis_revision, parsed.scene_id) == (StudioActor.USER, 3, SID)
    assert parsed.files == {"style": "p{color:red}"} and parsed.request_id == "psq_0123456789ab" and parsed.allow_state_reset
    assert parse_source_edit(request(actor="brain")).actor is StudioActor.BRAIN
    assert parse_source_edit(request()).allow_state_reset is False  # a reset is never implicit


@pytest.mark.parametrize(("changes", "needle"), [
    ({"actor": "root"}, "actor"), ({"basis": {}}, "missing keys"), ({"basis": {"variant_revision": 0}}, "variant_revision"),
    ({"basis": {"variant_revision": True}}, "variant_revision"), ({"scene_id": 5}, "scene_id"),
    ({"files": {}}, "non-empty"), ({"files": []}, "non-empty"), ({"files": {"script": "x"}}, "unknown keys script"),
    ({"files": {"style": 3}}, "files.style"), ({"files": {"manifest": "x"}}, "files.manifest"),
    ({"files": {"behavior": "x" * (64 * 1024 + 1)}}, "exceeds"), ({"request_id": "psq_zz"}, "request_id"),
    ({"allow_state_reset": "yes"}, "boolean"), ({"extra": 1}, "unknown keys"),
])
def test_a_malformed_source_edit_is_refused_with_the_field_named(changes, needle):
    refused(lambda: parse_source_edit(request(**changes)), needle=needle)


def test_runtime_handles_are_never_part_of_a_request():
    refused(lambda: parse_source_edit(request(object_id="x")), C.RUNTIME_STATE_REFUSED)


# ------------------------------------------------------------------ candidat

def test_the_source_id_belongs_to_the_scene_and_to_the_retention_namespace():
    prefab_id = source_prefab_id(PID, SID)
    assert prefab_id == "presentation-studio.pabababababab.s0000000000a1" and is_prefab_id(prefab_id)
    assert source_prefab_id(PID, "pss_0000000000a2") != prefab_id
    assert source_prefab_id("pst_" + "cd" * 16, SID) != prefab_id  # two presentations never share a scene source


def test_a_candidate_is_the_current_source_with_only_the_given_files_replaced():
    files = {"template": (FIXTURE / "template.html").read_text(encoding="utf-8"),
             "style": (FIXTURE / "style.css").read_text(encoding="utf-8"),
             "behavior": (FIXTURE / "behavior.js").read_text(encoding="utf-8")}
    candidate = compose_candidate(RAW, files, {"style": "p{color:red}"}, prefab_id="presentation-studio.pa.s1")
    assert candidate["style"] == "p{color:red}" and candidate["template"] == files["template"]
    assert candidate["behavior"] == files["behavior"] and candidate["manifest"]["id"] == "presentation-studio.pa.s1"
    assert RAW["id"] == "test.counter"  # the pin's own manifest is not mutated
    swapped = compose_candidate(RAW, files, {"manifest": {**RAW, "title": "Autre"}}, prefab_id="presentation-studio.pa.s1")
    assert swapped["manifest"]["title"] == "Autre" and swapped["manifest"]["id"] == "presentation-studio.pa.s1"


@pytest.mark.parametrize("where", ["props", "data", "event"])
@pytest.mark.parametrize("key", ["__proto__", "constructor", "prototype"])
def test_a_manifest_declaring_a_prototype_key_is_flagged(where, key):
    raw = copy.deepcopy(RAW)
    if where == "event":
        raw["events"]["incremented"]["payload"]["properties"][key] = {"type": "integer"}
    else:
        raw["inputs"][where]["properties"][key] = {"type": "string"}
    assert unsafe_manifest_key(raw) == key
    assert unsafe_manifest_key(RAW) is None


# ------------------------------------------------------------------ continuite des valeurs studio

def test_compatible_values_controls_and_anchors_are_carried_over_unchanged():
    carried = plan_carry_over(scene(), manifest(), allow_reset=False)
    assert carried.problems == () and carried.reset is None
    assert carried.scene == scene(prefab=PrefabRef("test.counter", 2))   # only the pin moved
    assert scene_problems(scene(), manifest()) == []


def test_an_incompatible_scene_is_refused_with_problems_and_nothing_is_reset_unless_allowed():
    def retype(raw):
        raw["inputs"]["props"]["properties"]["mode"].update(values=["compact"], default="compact")  # "full" is gone
        del raw["inputs"]["data"]["properties"]["notes"]
    m = manifest(retype)
    carried = plan_carry_over(scene(), m, allow_reset=False)
    assert carried.scene is None and carried.reset is None
    assert any("props.mode" in problem for problem in carried.problems)


def test_a_reset_names_the_dropped_keys_controls_and_anchors_and_never_a_value():
    def rework(raw):
        raw["inputs"]["props"]["properties"]["mode"].update(values=["compact"], default="compact")
        del raw["inputs"]["data"]["properties"]["count"]
        raw["inputs"]["data"]["required"] = []
        raw["sample"]["data"] = {}
        raw["events"]["incremented"]["writes"] = ["history"]
        del raw["events"]["incremented"]["payload"]["properties"]["count"]
    carried = plan_carry_over(scene(data={"count": 12, "notes": "secret words"}), manifest(rework), allow_reset=True)
    assert carried.scene is not None and carried.problems == ()
    reset = carried.reset
    assert reset == StateReset(props=("mode",), data=("count",), controls=("start_count",), anchors=("reveal",))
    kept = carried.scene
    assert kept.props == {"label": "Visiteurs"} and kept.data == {"notes": "secret words"}
    assert [c.control_id for c in kept.controls] == ["headline", "density"]  # density stays: its path is still declared
    assert [(a.anchor_id, a.control_id) for a in kept.anchors] == [("reveal", None), ("beat", None)]  # the anchors stay
    assert "secret" not in json.dumps(reset.to_dict()) and "Visiteurs" not in json.dumps(reset.to_dict())


def test_a_key_that_is_now_required_without_a_default_cannot_be_reset_away():
    def require(raw):
        raw["inputs"]["data"]["required"] = ["count", "headline"]
        raw["inputs"]["data"]["properties"]["headline"] = {"type": "string"}
        raw["sample"]["data"]["headline"] = "x"
    carried = plan_carry_over(scene(), manifest(require), allow_reset=True)
    assert carried.scene is None and any("headline" in problem and "required" in problem for problem in carried.problems)


def test_an_unknown_key_in_the_scene_values_is_reported_by_name():
    carried = plan_carry_over(scene(data={"count": 1, "legacy": 5}), manifest(), allow_reset=True)
    assert carried.reset == StateReset(data=("legacy",)) and carried.scene.data == {"count": 1}


# ------------------------------------------------------------------ rapport de montage

def report(**changes):
    body = {"object_id": "obj_1", "prefab": {"id": "test.counter", "version": 2}, "outcome": "mounted"}
    body.update(changes)
    return body


def test_a_mount_report_is_what_the_host_observed_and_the_frames_words_are_clipped_to_one_line():
    ok = parse_mount_report(report())
    assert ok.outcome is MountOutcome.MOUNTED and ok.prefab == PrefabRef("test.counter", 2)
    failed = parse_mount_report(report(outcome="failed", reason="frame", message="Boom\n at <script>" + "x" * 400))
    assert failed.reason == "frame" and "\n" not in failed.message and len(failed.message) <= 300


@pytest.mark.parametrize("changes", [
    {"outcome": "ok"}, {"object_id": ""}, {"object_id": 7}, {"prefab": {"id": "Bad Id", "version": 1}},
    {"prefab": {"id": "test.counter", "version": 0}}, {"outcome": "failed", "reason": "Not A Code"},
    {"outcome": "failed", "message": 4}, {"reason": "frame"}, {"extra": 1}])
def test_a_malformed_mount_report_is_refused(changes):
    refused(lambda: parse_mount_report(report(**changes)))


# ------------------------------------------------------------------ resultat

def result(status, **changes):
    base = dict(status=status, actor=StudioActor.USER, presentation_id=PID, variant_id="psv_" + "1" * 32, scene_id=SID,
                basis_revision=3, revision=4, source_revision=1, prefab=PrefabRef("a.b", 2), previous=PrefabRef("a.b", 1))
    base.update(changes)
    return ReloadResult(**base)


@pytest.mark.parametrize(("status", "http", "stood"), [
    (ReloadStatus.RELOADED, 200, True), (ReloadStatus.RELOADED_STATE_RESET, 200, True), (ReloadStatus.REPINNED, 200, True),
    (ReloadStatus.PENDING_MOUNT, 202, True), (ReloadStatus.REFUSED_VALIDATION, 400, False),
    (ReloadStatus.ROLLED_BACK, 409, False), (ReloadStatus.STALE, 409, False)])
def test_every_status_has_one_http_answer_and_says_whether_the_new_source_stands(status, http, stood):
    answer = result(status, code="x_code", message="why")
    assert answer.http_status == http and status.stood is stood
    wire = answer.to_dict()
    assert wire["status"] == status.value and wire["prefab"] == {"id": "a.b", "version": 2}
    assert ("error" in wire) == (status in (ReloadStatus.PENDING_MOUNT, ReloadStatus.REFUSED_VALIDATION,
                                            ReloadStatus.ROLLED_BACK, ReloadStatus.STALE))


def test_a_reset_travels_in_the_result_and_the_wire_is_pure_json():
    wire = result(ReloadStatus.RELOADED_STATE_RESET, reset=StateReset(data=("count",), runtime=True)).to_dict()
    assert wire["reset"] == {"props": [], "data": ["count"], "controls": [], "anchors": [], "runtime_values": True}
    assert json.loads(json.dumps(wire)) == wire

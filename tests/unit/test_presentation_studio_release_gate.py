"""Release verifier of the Presentation Studio: the items of the Slice 11 carry-forward that need no model (jarvis-interactive-presentation-studio, Slice 22).

`scripts/verify_release.py::presentation_studio_findings` is what the release command runs after the suite; it is tested here against the
real tree (no finding) and against doctored trees (each mutation must produce its finding), so the verifier cannot pass vacuously.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil

import pytest

ROOT = Path(__file__).resolve().parents[2]
SLICES = "tasks/jarvis-interactive-presentation-studio/slices"
RIG = f"{SLICES}/11-authoring-planner-first-draft/evidence/fake-author-rig.json"


@pytest.fixture(scope="module")
def verifier():
    spec = importlib.util.spec_from_file_location("verify_release_under_test", ROOT / "scripts" / "verify_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def doctored(tmp_path: Path) -> Path:
    """A minimal tree with only what the verifier reads outside the package: the evidence and the release test files."""

    for relative in (f"{SLICES}/11-authoring-planner-first-draft/evidence", f"{SLICES}/22-end-to-end-hardening/evidence"):
        shutil.copytree(ROOT / relative, tmp_path / relative, dirs_exist_ok=True)
    (tmp_path / "tests" / "unit").mkdir(parents=True)
    for name in ("test_presentation_studio_authoring_crash.py", "test_presentation_studio_authoring_service.py",
                 "test_presentation_studio_authoring_routes.py", "test_presentation_studio_release_faults.py"):
        shutil.copy(ROOT / "tests" / "unit" / name, tmp_path / "tests" / "unit" / name)
    return tmp_path


def test_the_real_tree_has_no_finding(verifier):
    assert verifier.presentation_studio_findings() == []


def test_the_planner_is_registered_read_only_attached_to_the_programs_that_declare_the_presentation_tools():
    from jarvis.domain.presentation_studio_authoring_policy import PROMPT_ID
    from jarvis.runtime.prompt_catalog import default_prompt_registry

    registry = default_prompt_registry()
    descriptor = registry.require(PROMPT_ID)
    assert descriptor.apply_policy == "read_only" and not descriptor.editable
    declaring = {p.program_id for p in registry.programs
                 if any(step.prompt_id == "backend.claude.conversation.presentation" for step in p.steps)}
    attached = {p.program_id for p in registry.programs if any(step.prompt_id == PROMPT_ID for step in p.steps)}
    assert declaring and attached == declaring and len(declaring) == 4


def test_every_piece_of_evidence_carries_the_fingerprint_of_the_planner_in_the_code():
    from jarvis.domain.presentation_studio_authoring_policy import PROMPT_FINGERPRINT

    rig = json.loads((ROOT / RIG).read_text(encoding="utf-8"))
    assert rig["prompt"]["fingerprint"] == PROMPT_FINGERPRINT
    real = sorted((ROOT / SLICES / "22-end-to-end-hardening" / "evidence").glob("authoring-real-traces*.json"))
    assert real, "the real-model authoring traces of the release gate are committed"
    for path in real:
        assert json.loads(path.read_text(encoding="utf-8"))["planner_fingerprint"] == PROMPT_FINGERPRINT, path.name


def test_a_stale_fingerprint_in_the_evidence_is_a_finding(verifier, tmp_path):
    root = doctored(tmp_path)
    data = json.loads((root / RIG).read_text(encoding="utf-8"))
    data["prompt"]["fingerprint"] = "0" * 64
    (root / RIG).write_text(json.dumps(data), encoding="utf-8")
    assert any("fingerprint" in f and "scripted rig" in f for f in verifier.presentation_studio_findings(root))


def test_missing_evidence_and_missing_drills_are_findings(verifier, tmp_path):
    root = doctored(tmp_path)
    assert verifier.presentation_studio_findings(root) == []
    (root / "tests/unit/test_presentation_studio_authoring_crash.py").unlink()
    assert any("test_presentation_studio_authoring_crash.py" in f for f in verifier.presentation_studio_findings(root))
    (root / RIG).unlink()
    assert any("rig evidence is missing" in f for f in verifier.presentation_studio_findings(root))


def test_a_privacy_test_that_lost_its_name_is_a_finding(verifier, tmp_path):
    root = doctored(tmp_path)
    path = root / "tests/unit/test_presentation_studio_authoring_service.py"
    path.write_text(path.read_text(encoding="utf-8").replace("never_reaches_the_logs", "renamed"), encoding="utf-8")
    assert any("never_reaches_the_logs" in f for f in verifier.presentation_studio_findings(root))

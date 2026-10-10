"""Release verifier of the Remotion handoff (Slice 22): `scripts/verify_release.py::remotion_release_findings`.

Tested against the real tree (no finding) and against doctored trees (each mutation produces its finding), so the verifier cannot pass
vacuously: a renamed release test, a missing or failed evidence file, a report without a section, a leak planted in the handoff.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil

import pytest

ROOT = Path(__file__).resolve().parents[2]
TASK = "tasks/jarvis-remotion-presentation-integration"
EVIDENCE = f"{TASK}/slices/22-end-to-end-release/evidence"


@pytest.fixture(scope="module")
def verifier():
    spec = importlib.util.spec_from_file_location("verify_release_remotion_under_test", ROOT / "scripts" / "verify_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def doctored(tmp_path: Path, verifier) -> Path:
    """A minimal tree with only what the verifier reads: the release tests, the evidence of Slice 22, the report and an empty handoff."""

    shutil.copytree(ROOT / EVIDENCE, tmp_path / EVIDENCE)
    (tmp_path / "docs").mkdir()
    shutil.copy(ROOT / "docs" / "remotion-integration-release.md", tmp_path / "docs")
    for relative in verifier.REMOTION_REQUIRED_TESTS:
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / relative, tmp_path / relative)
    return tmp_path


def test_the_real_tree_has_no_finding(verifier):
    assert verifier.remotion_release_findings() == []


def test_the_clean_doctored_tree_has_no_finding(verifier, tmp_path):
    assert verifier.remotion_release_findings(doctored(tmp_path, verifier)) == []


def test_a_renamed_or_deleted_release_test_is_a_finding(verifier, tmp_path):
    root = doctored(tmp_path, verifier)
    path = root / "tests/unit/test_remotion_release_faults.py"
    path.write_text(path.read_text(encoding="utf-8").replace("def test_the_fault_matrix_covers_every_fault_of_the_release_brief(", "def renamed("), encoding="utf-8")
    assert any("test_the_fault_matrix_covers" in f for f in verifier.remotion_release_findings(root))
    (root / "tests/unit/test_remotion_release_flows.py").unlink()
    assert any("missing release test file tests/unit/test_remotion_release_flows.py" in f for f in verifier.remotion_release_findings(root))


@pytest.mark.parametrize("name", ["real-isolation.json", "real-render-happy.json", "real-render-faults.json", "real-render-hostile.json",
                                  "real-studio.json", "real-studio-late.json", "migration.json"])
def test_missing_or_failed_real_runtime_evidence_blocks_the_release(verifier, tmp_path, name):
    root = doctored(tmp_path, verifier)
    path = root / EVIDENCE / name
    data = json.loads(path.read_text(encoding="utf-8"))
    data["verdict"] = "FAILED"
    data.pop("result", None)
    path.write_text(json.dumps(data), encoding="utf-8")
    assert any(name in f and "FAILED" in f for f in verifier.remotion_release_findings(root))
    path.unlink()
    assert any(f"missing release evidence {name}" in f for f in verifier.remotion_release_findings(root))


def test_a_journey_that_lost_a_step_is_a_finding(verifier, tmp_path):
    root = doctored(tmp_path, verifier)
    path = root / EVIDENCE / "release-journey.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["steps"] = [s for s in data["steps"] if not s["step"].startswith("5_export_pdf")]
    path.write_text(json.dumps(data), encoding="utf-8")
    assert any("5_export_pdf" in f for f in verifier.remotion_release_findings(root))


def test_a_report_without_a_section_or_with_a_todo_is_a_finding(verifier, tmp_path):
    root = doctored(tmp_path, verifier)
    report = root / "docs" / "remotion-integration-release.md"
    original = report.read_text(encoding="utf-8")
    report.write_text(original.replace("## Residual risks", "## Something else"), encoding="utf-8")
    assert any("## Residual risks" in f for f in verifier.remotion_release_findings(root))
    report.write_text(original + "\nTODO: write this\n", encoding="utf-8")
    assert any("TODO" in f for f in verifier.remotion_release_findings(root))


def test_a_home_path_planted_in_the_handoff_is_a_finding(verifier, tmp_path):
    root = doctored(tmp_path, verifier)
    task = root / TASK
    task.mkdir(parents=True, exist_ok=True)
    (task / "LOG.md").write_text(f"ran in {Path.home()}\Temp\x\n", encoding="utf-8")
    assert any("privacy sweep" in f for f in verifier.remotion_release_findings(root))

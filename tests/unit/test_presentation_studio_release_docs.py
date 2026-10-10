"""The final report keeps its promises (jarvis-interactive-presentation-studio, Slice 22).

`docs/presentation-studio-release.md` names slices, tests, evidence files, Human checks and contract anchors. A name that stops existing is a
documentation defect found here, not by a reader.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs" / "presentation-studio-release.md"
PAGE = ROOT / "docs" / "presentation-studio.md"
SLICES = ROOT / "tasks" / "jarvis-interactive-presentation-studio" / "slices"


def slug(heading: str) -> str:
    """GitHub's anchor for a heading: lower case, punctuation dropped, spaces to hyphens."""

    text = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return text.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    return {slug(m.group(1)) for m in re.finditer(r"^#{1,6} (.+)$", path.read_text(encoding="utf-8"), re.M)}


def test_every_slice_folder_has_a_row_in_the_status_table():
    text = REPORT.read_text(encoding="utf-8")
    rows = {m.group(1) for m in re.finditer(r"^\| (\d{2}[ac]?) \|", text, re.M)}
    folders = {p.name.split("-", 1)[0] for p in SLICES.iterdir() if p.is_dir() and p.name[:2].isdigit()}
    assert folders <= rows, sorted(folders - rows)


def test_every_human_validation_check_of_the_handoff_is_in_the_physical_list():
    text = REPORT.read_text(encoding="utf-8")
    ids = {c["id"] for p in SLICES.glob("*/human-validation.json") for c in json.loads(p.read_text(encoding="utf-8"))["checks"]}
    assert len(ids) == 8 and all(i in text for i in ids), sorted(i for i in ids if i not in text)
    for number in range(1, 12):
        assert f"| H-{number} |" in text, number


def test_every_anchor_the_report_links_exists():
    text = REPORT.read_text(encoding="utf-8")
    pages = {"presentation-studio.md": anchors(PAGE), "prefabs.md": anchors(ROOT / "docs" / "prefabs.md"),
             "OPERATIONS.md": anchors(ROOT / "docs" / "OPERATIONS.md"), "presentation-studio-release.md": anchors(REPORT)}
    links = re.findall(r"\]\(([\w.\-]*\.md)?#([\w\-]+)\)", text)
    assert len(links) > 40
    for file, anchor in links:
        assert anchor in pages[file or "presentation-studio-release.md"], (file, anchor)


def test_every_test_and_evidence_file_the_report_names_exists():
    text = REPORT.read_text(encoding="utf-8")
    for name in set(re.findall(r"`(test_[a-z0-9_]+\.py)`", text)):
        assert (ROOT / "tests" / "unit" / name).is_file() or (ROOT / "tests" / "integration" / name).is_file(), name
    for relative in set(re.findall(r"`((?:tests|scripts)/[\w/.]+\.py)`", text)):
        assert (ROOT / relative).is_file(), relative
    evidence = SLICES / "22-end-to-end-hardening" / "evidence"
    for name in ("authoring-real-traces.md", "authoring-real-traces.json", "authoring-real-traces.missing-context.md"):
        assert (evidence / name).is_file(), name
    sources = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "tests" / "unit").glob("test_presentation_studio_release_*.py"))
    sources += (ROOT / "tests" / "unit" / "test_presentation_studio_authoring_guide.py").read_text(encoding="utf-8")
    modules = {p.stem for p in (ROOT / "tests" / "unit").glob("test_*.py")}
    for name in set(re.findall(r"`(test_[a-z0-9_]+)`", text)):
        assert name in modules or re.search(rf"def {name}\(", sources), name


def test_the_report_is_linked_from_the_concept_page_and_the_runbook_has_its_section():
    assert "presentation-studio-release.md" in PAGE.read_text(encoding="utf-8")
    operations = (ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
    assert "### Presentation Studio : release et exploitation de bout en bout (Slice 22)" in operations
    assert "presentation-studio-release.md" in operations

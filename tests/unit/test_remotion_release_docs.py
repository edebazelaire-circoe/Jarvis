"""The Remotion release report names only documents and tests that exist, and states what the release gate requires (Slice 22)."""

from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs" / "remotion-integration-release.md"


def section(title: str) -> str:
    text = REPORT.read_text(encoding="utf-8")
    start = text.index(title)
    nxt = text.find("\n## ", start + 1)
    return text[start: nxt if nxt != -1 else len(text)]


def test_every_document_the_contract_index_names_exists():
    names = re.findall(r"`([A-Za-z0-9_./-]+\.md)`", section("## Contract index"))
    assert names, "the contract index names documents"
    for name in names:
        assert (ROOT / "docs" / name).is_file(), name


def test_every_test_file_the_report_names_exists():
    text = REPORT.read_text(encoding="utf-8")
    names = set(re.findall(r"`(test_[A-Za-z0-9_]+\.py)`", text))
    assert len(names) > 20
    for name in names:
        assert (ROOT / "tests" / "unit" / name).is_file() or (ROOT / "tests" / "integration" / name).is_file(), name
    for pattern in sorted(set(re.findall(r"`(test_[A-Za-z0-9_*]+\*[A-Za-z0-9_*.]*\.py)`", text))):
        assert list((ROOT / "tests" / "unit").glob(pattern)), pattern


def test_every_script_the_report_names_exists():
    for name in set(re.findall(r"`(scripts/[a-z_]+\.py)`", REPORT.read_text(encoding="utf-8"))):
        assert (ROOT / name).is_file(), name


def test_the_report_states_the_two_release_blockers_the_open_channel_and_the_licence_decision():
    text = REPORT.read_text(encoding="utf-8")
    for needle in ("No fallback (verified)", "Privacy boundary (verified", "dns-prefetch", "OPEN, best effort", "Remotion licence", "Issue 05",
                   "H-12", "HV-21-01", "HV-16-01", "HV-11-01", "restart"):
        assert needle in text, needle

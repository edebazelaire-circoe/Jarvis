"""`docs/presentation-live-refs.md` and the package section against the code (Remotion Slice 09)."""

from __future__ import annotations

from pathlib import Path

from jarvis.domain import presentation_live_refs as lr
from jarvis.domain import presentation_snapshot_package as pkg

DOCS = Path(__file__).resolve().parents[2] / "docs"
LIVE = (DOCS / "presentation-live-refs.md").read_text(encoding="utf-8")
ARTIFACTS = (DOCS / "presentation-artifacts.md").read_text(encoding="utf-8")


def test_every_state_error_code_and_declaration_constant_is_documented():
    for state in lr.LiveRefState:
        assert f"`{state.value}`" in LIVE, state
    for code in lr.LiveRefErrorCode:
        assert code.value in LIVE + ARTIFACTS, code
    for needed in ("not_authorised", "live_ref_not_authorised", "authorised_boards", "declaration_errors"):
        assert needed in LIVE, needed
    assert "package_invalid" in ARTIFACTS and "package_failed" in ARTIFACTS and "12 segments" in ARTIFACTS
    assert lr.LIVE_REFS_PATH in LIVE and lr.LIVE_REFS_FORMAT in LIVE
    assert pkg.PACKAGE_FORMAT in ARTIFACTS and str(pkg.MAX_PACKAGE_FILES) in ARTIFACTS + LIVE


def test_the_documented_bounds_are_the_coded_ones():
    assert lr.MAX_TEXT_BYTES == 256 * 1024 and "256 KiB" in LIVE
    assert lr.MAX_BINARY_BYTES == 4 * 1024 * 1024 and "4 MiB" in LIVE
    assert lr.MAX_SET_BYTES == 16 * 1024 * 1024 and "16 MiB" in LIVE
    assert pkg.MAX_PACKAGE_BYTES == 64 * 1024 * 1024 and "64 MiB" in LIVE
    assert lr.MAX_REFS_PER_SOURCE == 32 and "24 KiB" in LIVE and lr.MAX_INLINE_TEXT_BYTES == 24 * 1024


def test_the_entry_pages_link_to_the_new_page():
    for page in ("artifacts.md", "presentation-artifacts.md", "local-data.md"):
        assert "presentation-live-refs.md" in (DOCS / page).read_text(encoding="utf-8"), page

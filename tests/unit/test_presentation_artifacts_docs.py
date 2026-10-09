"""`docs/presentation-artifacts.md` against the code and the entry pages (Remotion Slice 07)."""

from __future__ import annotations

from pathlib import Path
import re

from jarvis.core import presentation_artifacts as core
from jarvis.domain import presentation_artifacts as pa
from jarvis.domain.artifacts import ArtifactKind, ArtifactRelationKind
from jarvis.domain.presentation_studio import PresentationStudioErrorCode as C

DOCS = Path(__file__).resolve().parents[2] / "docs"
TEXT = (DOCS / "presentation-artifacts.md").read_text(encoding="utf-8")
ARTIFACTS = (DOCS / "artifacts.md").read_text(encoding="utf-8")


def test_the_page_names_every_new_kind_relation_key_and_operation():
    for kind in pa.PRESENTATION_ARTIFACT_KINDS:
        assert f"`{kind.value}`" in TEXT and f"`{kind.value}`" in ARTIFACTS, kind
    assert "`rendered_from`" in TEXT and "`rendered_from`" in ARTIFACTS
    assert ArtifactRelationKind.RENDERED_FROM.value == "rendered_from"
    keys = pa.SourceProvenance("pst_" + "a" * 32, "psv_" + "b" * 32, 1, 1, "remotion").to_metadata()
    for key in (*keys, "content_sha256", "render_format"):
        assert f"`{key}`" in TEXT, key
    for name in ("begin_snapshot", "finalize_snapshot", "begin_render", "describe_source", "boards_of_source", "sources_of_board"):
        assert f"`{name}" in TEXT and hasattr(core.PresentationArtifacts, name), name
    for code in (C.STALE_REVISION, C.UNKNOWN_PRESENTATION, C.UNKNOWN_VARIANT, C.ENGINE_UNSUPPORTED, C.INVALID_PRESENTATION):
        assert code.value in TEXT, code


def test_the_page_states_the_closed_kind_count_the_code_has():
    assert len(ArtifactKind) == 11 and "(now 11)" in TEXT
    for spec in pa.RENDERS.values():
        assert f"`{spec.payload_name}`" in TEXT or spec.payload_name in TEXT
    assert pa.SNAPSHOT_PAYLOAD_NAME in TEXT and str(pa.MAX_SNAPSHOT_ATTEMPTS) in TEXT


def test_the_entry_pages_link_here_and_name_one_board_owner():
    for page in ("presentation-studio.md", "artifacts.md", "local-data.md", "boards.md"):
        assert "presentation-artifacts.md" in (DOCS / page).read_text(encoding="utf-8"), page
    assert re.search(r"single owner\*\* of\s+\"which Boards show this\"", ARTIFACTS)
    assert "Board.artifact_refs` is not a second owner" in TEXT

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


# ------------------------------------------------------------------ Board discoverability (Slice 08)

ROOT = DOCS.parent


def test_every_artifact_kind_is_in_the_search_filter_and_labelled_by_the_control_center():
    mcp = (ROOT / "jarvis" / "runtime" / "capture_mcp.py").read_text(encoding="utf-8")
    start = mcp.index("async def artifact_search(\n        kind")
    literal = mcp[start:mcp.index("scope:", start)]
    labels = (ROOT / "jarvis" / "runtime" / "control_center_workspace.js").read_text(encoding="utf-8")
    block = labels[labels.index("const ARTIFACT_KINDS="):labels.index("const ENGINES=")]
    for kind in ArtifactKind:
        assert f'"{kind.value}"' in literal, f"artifact_search does not accept {kind.value}"
        assert f"{kind.value}:'" in block, f"ARTIFACT_KINDS has no label for {kind.value}"
    assert f"max_length={len(ArtifactKind)}" in literal
    assert "rendered_from:'rendu de'" in labels and "rendered_from:'a été rendu en'" in labels


def test_the_documented_read_routes_exist_on_core_and_on_the_relay_and_are_in_the_board_page():
    from jarvis.protocol.workspace_routes import WorkspaceProtocolRoutes
    from jarvis.runtime import workspace_relay

    core_paths = {route.path for route in WorkspaceProtocolRoutes(core=None).routes()}
    relay_paths = {path for _, _, path, _ in workspace_relay._ROUTES}
    boards = (DOCS / "boards.md").read_text(encoding="utf-8")
    for tail in ("/boards/{board_id}/presentation-sources", "/presentation-sources/{presentation_id}"):
        assert "/v1/workspace" + tail in core_paths and tail in relay_paths, tail
        assert tail in TEXT or tail.replace("{board_id}", "{id}") in TEXT, tail
        assert tail in boards, tail
    assert not any("presentation" in path for path in core_paths if path.endswith("/artifacts/{artifact_id}")), \
        "a source is never reached through an artifact route"


def test_the_page_documents_the_visible_states_the_service_returns():
    section = TEXT[TEXT.index("## Board discoverability (Slice 08)"):]
    for word in ("stale", "exists: false", "exists: null", "linked_here", "unreadable", "truncated", "presentations_unavailable"):
        assert word in section, word
    assert "Contract for Slice 08" not in TEXT, "the forward-looking contract is replaced by what shipped"

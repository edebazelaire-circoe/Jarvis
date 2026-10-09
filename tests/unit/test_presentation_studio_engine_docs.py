"""`docs/presentation-engine.md` against the code (Remotion Slice 02)."""

from __future__ import annotations

from pathlib import Path

from jarvis.domain import presentation_studio_engine as eng
from jarvis.domain.presentation_studio import PresentationStudioErrorCode as C

DOCS = Path(__file__).resolve().parents[2] / "docs"
TEXT = (DOCS / "presentation-engine.md").read_text(encoding="utf-8")


def test_the_page_states_the_capability_matrix_the_code_has():
    rows = {}
    for line in TEXT.splitlines():
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) == 3 and cells[0].startswith("`") and "(" in cells[0]:
            rows[cells[0]] = cells[1:]
    assert len(rows) == len(eng.Capability), rows
    for capability in eng.Capability:
        key = next(k for k in rows if k.startswith(f"`{capability.value}`"))
        assert rows[key] == [eng.CAPABILITIES[e][capability].value for e in (eng.Engine.SLIDECAR, eng.Engine.REMOTION)], key


def test_every_engine_code_symbol_is_named_and_the_entry_pages_link_here():
    for code in (C.ENGINE_UNAVAILABLE, C.ENGINE_UNSUPPORTED, C.ENGINE_SELECTION_REFUSED):
        assert f"`{code.value}`" in TEXT
    for symbol in ("EngineSelectionPolicy", "resolve_engine", "classify_compatibility", "legacy_html_compatibility", "EngineIdentity"):
        assert symbol in TEXT and hasattr(eng, symbol), symbol
    assert "Sidecar" not in TEXT.replace('(never "Sidecar")', "")
    assert "presentation-engine.md" in (DOCS / "presentation-studio.md").read_text(encoding="utf-8")
    assert "presentation-engine.md" in (DOCS / "prefabs.md").read_text(encoding="utf-8")

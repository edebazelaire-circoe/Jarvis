"""Level 3 conformance of *Retirement map and migration readers (Slice 15)* in `docs/presentation-studio.md`.

The section is the one index of what native-studio-playback-fix retired and of the migration readers it kept. This test pins it against
the code, statically: each retired owner is gone from the page and Core, each migration reader the section names is still there, the
stage page's own bar lives nowhere but the stage page, and the words a person or the brain reads say « Variantes ».
"""

from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "presentation-studio.md"
RUNTIME = ROOT / "jarvis" / "runtime"
HEADING = "### Retirement map and migration readers (Level 3, Slice 15)"


def _section() -> str:
    text = DOC.read_text(encoding="utf-8")
    start = text.index(HEADING)
    end = text.index("\n### ", start + len(HEADING))
    return text[start:end]


def _code(path: Path) -> str:
    """The file without its comments (a retired name may be cited in history comments)."""

    text = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        return "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//"))


def _page_code() -> dict[str, str]:
    return {p.name: _code(p) for p in RUNTIME.glob("control_center*.js")}


def test_the_section_is_level_3_and_names_every_retired_owner_and_every_reader():
    section = _section()
    for name in ("studio_stage", "studio_aux", "#jvStudioBand", "JarvisPresentationWindow", "rs-bar", "onNavigate", "chain",
                 "Variant bar", "Jouer cette slide", "8 s par slide", "explorateur", ".jvx-upgrades",
                 "LegacyStageReclaimer", "StageLedger", "RETIRED_CATEGORIES", "LEGACY_CATEGORIES", "studio-stage-[\\w-]+",
                 "open_window", "Rollback", "no SQLite schema", "test_presentation_studio_task_base_data.py", "CLEANUP.md"):
        assert name in section, name


def test_the_retired_owners_are_gone_from_the_page():
    page = _page_code()
    assert not (RUNTIME / "control_center_presentation_window.js").exists()
    for name, code in page.items():
        assert "jvStudioBand" not in code, name
        assert "JarvisPresentationWindow" not in code, name
        assert "jvx-vbar" not in code, name
    player = page["control_center_presentation_studio_player.js"]
    assert not re.search(r"\bchain\b", player), "the band's chained-play toggle is retired (Slice 15)"
    # `rs-bar` is the stage page's own bar for a Board Remotion window; no Variants or presentation module builds or styles it.
    owners = sorted(name for name, code in page.items() if "rs-bar" in code)
    assert owners == ["control_center_remotion_stage.js"], owners
    assert "rs-bar" in (RUNTIME / "control_center_remotion_stage.html").read_text(encoding="utf-8")


def test_the_migration_readers_the_section_names_are_still_there():
    stage = (ROOT / "jarvis" / "core" / "presentation_studio_stage.py").read_text(encoding="utf-8")
    assert "class LegacyStageReclaimer" in stage and "class StageLedger" in stage
    assert 'LEGACY_CATEGORIES = frozenset({STAGE_CATEGORY, AUX_CATEGORY})' in stage
    assert (ROOT / "jarvis" / "adapters" / "file_presentation_studio_stage_ledger.py").exists()
    layout = (RUNTIME / "control_center_scene_layout.js").read_text(encoding="utf-8")
    assert "RETIRED_CATEGORIES=Object.freeze(new Set(['studio_stage','studio_aux']))" in layout
    assert "LEGACY_CATEGORIES" in (RUNTIME / "tool_brain_executor.py").read_text(encoding="utf-8")
    sanitize = (ROOT / "jarvis" / "domain" / "presentation_studio_template_sanitize.py").read_text(encoding="utf-8")
    assert r"\bstudio-stage-[\w-]+" in sanitize


def test_the_presentation_tools_declare_variantes_not_explorateur():
    source = (RUNTIME / "presentation_studio_mcp.py").read_text(encoding="utf-8")
    descriptions = re.findall(r'description="([^"]*)"', source) + re.findall(r'"""(.*?)"""', source, flags=re.S)[1:]
    assert descriptions
    stale = [d for d in descriptions if "explorateur" in d.lower()]
    assert stale == [], stale

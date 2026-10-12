"""Code/documentation parity of the Variants run surface (jarvis-remotion-native-studio-playback-fix, Slice 09).

The section *Variants run surface (Level 3, Slice 09)* of `docs/presentation-studio.md` says what the code does: the surface id, the
bounds, the codes, the retired categories, the owners; every test file it cites exists; the retired viewer is really gone (its page module
and its band proofs); the Human check HV-RFX-09-01 is in OPERATIONS.
"""

from __future__ import annotations

from pathlib import Path
import re

from jarvis.core import presentation_studio_playback as playback
from jarvis.core import presentation_studio_run_surface as run_surface
from jarvis.core import presentation_studio_stage as stage
from tests.unit.test_presentation_studio_docs import page

ROOT = Path(__file__).resolve().parents[2]
TITLE = "### Variants run surface (Level 3, Slice 09)"


def section() -> str:
    text = page("presentation-studio.md")
    start = text.index(TITLE)
    return text[start:text.index("\n### ", start + len(TITLE))]


def test_the_section_states_the_surface_id_the_bounds_and_the_codes_the_code_uses():
    text = section()
    assert "variants-run-<run_id>" in text and run_surface.RunSurface.__name__ in text
    assert f"{playback.STAGE_SYNC_TIMEOUT_S:g} s" in text, "the bounded stage sync is stated with the code's value"
    assert str(run_surface.MAX_OVERLAYS) in text
    for code in ("stage_timeout", "stage_preempted", "surface_unavailable", "explorer_run_in_progress", "legacy_stage_reclaimed"):
        assert f"`{code}`" in text or code in text, code
    for category in stage.LEGACY_CATEGORIES:
        assert category in text, category
    assert "LegacyStageReclaimer" in text and ".retired-" in page("local-data.md")


def test_the_retirement_map_names_every_retired_owner_and_its_successor():
    text = section()
    for retired, successor in (("#jvStudioBand", ".jvx-presenter"), ("control_center_presentation_window.js", "Variants"),
                               ("studio-stage-<run_id>", "variants-run-<run_id>")):
        assert retired in text and successor in text, (retired, successor)


def test_every_test_file_the_section_cites_exists_and_the_retired_viewer_is_gone():
    text = section()
    cited = set(re.findall(r"`(?:tests/unit/)?(test_[a-z0-9_{},]+\.py)`", text))
    assert cited, "the Level 3 conformance cites its tests"
    for name in cited:
        if "{" in name:
            head, rest = name.split("{", 1)
            options, tail = rest.split("}", 1)
            names = [f"{head}{option}{tail}" for option in options.split(",")]
        else:
            names = [name]
        for one in names:
            assert (ROOT / "tests" / "unit" / one).exists(), one
    for gone in ("jarvis/runtime/control_center_presentation_window.js", "tests/unit/test_presentation_studio_player_browser.py",
                 "tests/unit/test_presentation_studio_player_realpage_browser.py", "tests/unit/test_presentation_studio_player_chain_js.py"):
        assert not (ROOT / gone).exists(), gone
    runtime = "".join(path.read_text(encoding="utf-8") for path in (ROOT / "jarvis" / "runtime").glob("control_center*.js"))
    built = re.findall(r"['\"]jvStudioBand['\"]|\.JarvisPresentationWindow\s*=|['\"]jv-presentation-window['\"]", runtime)
    assert built == [], f"no page code builds the retired viewer (comments may name it): {built}"


def test_the_human_check_is_in_operations():
    ops = page("OPERATIONS.md")
    assert "HV-RFX-09-01" in ops and "Variantes" in ops

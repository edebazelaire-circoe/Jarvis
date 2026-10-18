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


def test_the_escape_rule_is_precise_leaving_fullscreen_never_pauses_closing_variants_during_a_run_pauses():
    """Slice 09 rework: no unqualified « Échap never pauses » — the Échap that closes Variants mid-run pauses the run."""

    text = page("presentation-studio.md")
    rows = [line for line in text.splitlines() if line.startswith("| `Échap` |") and "then Variants" in line]
    assert rows and all("leaving fullscreen **never pauses**" in r and "closing Variants **pauses the run**" in r for r in rows), rows
    for line in text.splitlines():
        if "Échap" in line and "never pauses" in line:
            assert "only leaves fullscreen" in line or "leaving fullscreen" in line, line
    sec = section()
    assert "the `Échap` that closes Variants during a run pauses the run" in sec


def test_the_limits_say_the_hud_stays_live_and_every_active_phase_pauses_on_close():
    sec = section()
    assert 'data-keep-live="run"' in sec and "stays live and drawn above it" in sec
    assert "the interaction-mode HUD is under it" not in sec
    for phase in ("`playing`", "`resuming`", "`detour`"):
        assert phase in sec, phase
    html = (ROOT / "jarvis" / "runtime" / "control_center.html").read_text(encoding="utf-8")
    # Slice 02 de jarvis-board-ui-wheel-dossier-refactor : la carte Board (et son panneau) prend la place du
    # contrôle de mode retiré ; la présence de la voix reste visible pendant une lecture.
    assert re.search(r'<div id="boardsHud" data-keep-live="run"[^>]*></div>', html)
    assert re.search(r'<div id="boardsPanel" data-keep-live="run"[^>]*></div>', html)
    assert 'id="interactionModeHud"' not in html


def test_stale_viewer_wording_is_gone_and_the_handover_tolerance_is_stated():
    text = page("presentation-studio.md")
    assert "band cases in" not in text and "in Variants and on the run stage" not in text
    assert "until Slice 09 removes it" not in text
    assert "`control_center_presentation_window.js` (the window)" not in text
    assert "`ui.request`: `open_window`" not in text
    assert "A scene without anchors (in a `manual` run the user paces)" not in text
    frame_js = (ROOT / "jarvis" / "runtime" / "control_center_remotion_frame.js").read_text(encoding="utf-8")
    slack = re.search(r"END_SLACK_FRAMES=(\d+)", frame_js).group(1)
    assert f"`END_SLACK_FRAMES` ({slack})" in text and f"last {slack} frames or fewer" in text


def test_the_surface_unavailable_advice_and_bound_are_stated_with_the_codes_value():
    from jarvis.runtime.presentation_studio_mcp_support import SURFACE_UNAVAILABLE_ADVICE
    from jarvis.runtime.presentation_studio_mcp_tools import HOST_IN_VARIANTS_TIMEOUT_S

    sec = section()
    for code in SURFACE_UNAVAILABLE_ADVICE:
        assert f"`{code}`" in sec, code
    assert "`HOST_IN_VARIANTS_TIMEOUT_S`" in sec and f"= {HOST_IN_VARIANTS_TIMEOUT_S:g} s" in sec

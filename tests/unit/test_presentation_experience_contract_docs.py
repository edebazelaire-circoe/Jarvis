"""Conformance of the presentation experience contract (handoff jarvis-remotion-native-studio-playback-fix, Slice 02).

Only what the page itself can prove today: the Level 2 contract exists, states the decisions later Slices build
against (no per-slide timer, final-frame hold, one fullscreen, one key map, two names), and every older statement
it supersedes points to it. Behaviour is tested by Slices 04 and later, not here.
"""

from __future__ import annotations

from tests.unit.test_presentation_studio_docs import _section, page

TITLE = "## Presentation experience contract (Level 2, 2026-10)"
ANCHOR = "#presentation-experience-contract-level-2-2026-10"


def contract() -> str:
    return _section(TITLE)


def test_the_contract_section_exists_once_and_sits_before_the_playback_runtime():
    text = page("presentation-studio.md")
    assert text.count(TITLE) == 1
    assert text.index(TITLE) < text.index("## Playback runtime contract (Level 3, Slice 12)")


def test_every_numbered_part_is_present():
    text = contract()
    for n in range(1, 11):
        assert f"### 2026-10 § {n}." in text, n


def test_video_play_has_no_per_slide_timer_and_holds_the_final_frame():
    text = contract()
    for needle in ("**There is no per-slide timer.**", "Video never reads `target_duration_ms`", "**holds the final frame**",
                   "`loop: false`", "« 8 s par slide »", "**Forbidden in video playback, now and later:**",
                   "per-slide or per-scene dwell"):
        assert needle in text, needle


def test_two_names_one_runtime_one_fullscreen():
    text = contract()
    for needle in ("« Remotion Studio »", "« Variantes »", "The bare word « Studio » **must not**",
                   "**The Variants Player** is the only surface", "**One control:** the Variants header button « Plein écran »",
                   "**User-gesture rule.**", "`#jvStudioBand`", "`studio_stage`", "`JarvisPresentationWindow`", "`rs-bar`"):
        assert needle in text, needle


def test_one_key_map_covers_both_run_kinds():
    text = contract()
    assert "| Key | Continuous video (default) | Presenter run |" in text
    for key in ("`Space`", "`→` `PageDown`", "`←` `PageUp`", "`Home` / `End`", "`F`", "`M`", "`S`", "`Échap`", "`?`"):
        assert f"| {key} |" in text, key


ROWS = ("Naming", "Remotion Studio", "Remotion Studio round trip", "Variants opening", "Embedded Player, continuous play",
        "No per-slide cut", "Pause / resume", "Scene navigation", "One clock", "End", "Controls", "Fullscreen",
        "External display", "Presenter mode", "Presenter, Jarvis", "Floating viewer removed", "Keyboard and accessibility",
        "Failure", "Hot reload during play", "Detour", "Lire seulement cette scène")


def test_the_acceptance_matrix_has_each_row_under_its_name():
    text = contract()
    for number, area in enumerate(ROWS, start=1):
        assert f"| PX-{number} | {area} |" in text, (number, area)
    assert "| PX-22 |" not in text


def test_pins_and_scene_entry_decisions_are_stated():
    text = contract()
    assert "stage scene as a pin source (`studio_pins.bind_scene`" in text
    assert "the Variants Player's mounted pins register as a pin source" in text
    assert "its \"live scene\" source moves from the Board stage windows (`studio_pins.bind_scene`)" in text
    assert "A **newly entered** scene always starts on its local frame 0" in text
    assert "**except the scene-entry segment** (§ 5)" in text
    assert "the playhead (`from_frame`) is the furthest revealed anchor, also when a scene is entered" in text
    assert "Starting a run never enters fullscreen by itself" in text


def test_superseded_statements_point_to_the_contract():
    text = page("presentation-studio.md")
    for heading in ("### The stage window", "### Page: band and keyboard", "### Chained playback (scope, Slice 23)",
                    "### Studio additions (variant explorer)", "### The page\n\n> **Superseded"):
        start = text.index(heading)
        head = text[start:start + 900]
        assert "**Superseded (2026-10).**" in head and ANCHOR in head, heading
    explorer = _section("## Variant Explorer interaction contract (Level 3, Slice 18)")
    playback = explorer[explorer.index("### Playback"):]
    assert "**Superseded (2026-10).**" in playback[:600] and ANCHOR in playback[:600]
    bridge = _section("## Remotion timeline bridge (Level 3, Remotion handoff Slice 12)")
    entry = bridge.index("For the scene on the stage the playhead is")
    assert "**Superseded (2026-10).**" in bridge[entry - 400:entry] and ANCHOR in bridge[entry - 400:entry]
    assert "plays ONCE and holds its last image (it does not loop), so that the chain knows when it is done. *(Superseded 2026-10" in bridge
    for name in ("remotion-studio.md", "presentation-engine.md", "remotion-isolation.md", "OPERATIONS.md"):
        assert ANCHOR in page(name), name

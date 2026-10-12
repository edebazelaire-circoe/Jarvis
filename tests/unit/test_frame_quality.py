"""Rendered-frame quality detectors on synthetic frames (handoff jarvis-remotion-native-studio-playback-fix, Slice 14).

Contract: `docs/presentation-studio.md` > *Rendered-frame quality gates (Level 3, Slice 14)*. Each detector is pinned on a frame or a
sequence built here, both ways (it fires on the defect, it stays quiet on a clean frame), and the four regressions the Slice must catch
(transition flash, time carry, stale progress bar, cut at 8 s) are replayed from the shapes the Slice 03 baseline measured. The real
frames are in `test_remotion_frame_quality_real.py` and `test_presentation_flow_quality_browser.py` (opt-in).
"""

from __future__ import annotations

import pytest

from jarvis.domain.composition_clock import SceneManifest, build_composition
from jarvis.media import frame_quality as Q

W, H = 320, 180


def frame(fill: int = 40, *, draw=None) -> Q.GrayFrame:
    pixels = bytearray([fill]) * (W * H)
    if draw:
        draw(pixels)
    return Q.GrayFrame(W, H, bytes(pixels))


def rect(x0: int, y0: int, x1: int, y1: int, value: int = 240):
    def draw(pixels: bytearray) -> None:
        for y in range(y0, y1):
            pixels[y * W + x0:y * W + x1] = bytes([value]) * (x1 - x0)
    return draw


def strokes(x0: int, x1: int, y0: int, y1: int, value: int = 240, period: int = 3):
    """Text-like: thin vertical strokes (1 px ink, `period - 1` px gap), and a gap every few rows."""

    def draw(pixels: bytearray) -> None:
        for y in range(y0, y1):
            if y % 5 == 0:
                continue
            for x in range(x0, x1):
                if x % period == 0:
                    pixels[y * W + x] = value
    return draw


def both(*draws):
    def draw(pixels: bytearray) -> None:
        for d in draws:
            d(pixels)
    return draw


TITLE = strokes(20, 140, 20, 40)   # a title well inside the frame


def codes(findings) -> list[str]:
    return [f.code for f in findings]


def findings_of(f: Q.GrayFrame, role: Q.Role = Q.Role.MIDDLE, profile: Q.Profile = Q.Profile.RELEASE_GATE):
    return Q.frame_findings(Q.measure(f), role=role, profile=profile, scene="S1", frame=10)


# ------------------------------------------------------------------ one frame


def test_a_clean_frame_with_a_title_has_no_finding():
    assert findings_of(frame(draw=TITLE)) == []


def test_a_black_frame_is_black_and_blocks_in_the_middle_of_a_scene():
    [found] = findings_of(frame(0))
    assert found.code == "black" and found.severity is Q.Severity.BLOCKING and found.scene == "S1" and found.frame == 10


def test_a_uniform_or_smooth_frame_is_blank():
    assert codes(findings_of(frame(128))) == ["blank"]

    def gradient(pixels: bytearray) -> None:
        for y in range(H):
            for x in range(W):
                pixels[y * W + x] = 60 + x * 120 // W   # a smooth background with nothing on it
    assert codes(findings_of(frame(draw=gradient))) == ["blank"]


@pytest.mark.parametrize("role,profile,severity", [
    (Q.Role.FIRST, Q.Profile.RELEASE_GATE, Q.Severity.BLOCKING),   # the gate deck's frames always carry text (agent 0, rework)
    (Q.Role.ENTRY, Q.Profile.RELEASE_GATE, Q.Severity.BLOCKING),
    (Q.Role.EXIT, Q.Profile.RELEASE_GATE, Q.Severity.BLOCKING),
    (Q.Role.MIDDLE, Q.Profile.RELEASE_GATE, Q.Severity.BLOCKING),
    (Q.Role.LAST, Q.Profile.RELEASE_GATE, Q.Severity.BLOCKING),
    (Q.Role.PLAYBACK, Q.Profile.RELEASE_GATE, Q.Severity.BLOCKING),
    (Q.Role.FIRST, Q.Profile.AUTHORED, Q.Severity.WARNING),
    (Q.Role.ENTRY, Q.Profile.AUTHORED, Q.Severity.WARNING),
    (Q.Role.EXIT, Q.Profile.AUTHORED, Q.Severity.WARNING),
    (Q.Role.LAST, Q.Profile.AUTHORED, Q.Severity.WARNING),
    (Q.Role.MIDDLE, Q.Profile.AUTHORED, Q.Severity.BLOCKING),
])
def test_an_empty_frame_blocks_by_role_and_profile(role, profile, severity):
    [found] = findings_of(frame(0), role, profile)
    assert found.severity is severity


def test_content_touching_a_side_is_clipped_and_a_warning():
    found = findings_of(frame(draw=both(TITLE, rect(200, 60, W, 120))))   # a solid block cut by the right side
    assert codes(found) == ["edge_clipped"] and found[0].metric["side"] == "right" and found[0].severity is Q.Severity.WARNING


def test_text_strokes_cut_by_a_side_are_text_overflow_not_a_plain_clip():
    found = findings_of(frame(draw=both(TITLE, strokes(240, W, 80, 104))))   # a line of text running out on the right
    assert codes(found) == ["edge_text_overflow"] and found[0].metric["side"] == "right"
    assert found[0].metric["texture"] >= Q.THRESHOLDS.overflow_texture


@pytest.mark.parametrize("bar", [rect(0, H - 6, W, H), rect(0, H - 6, W // 2, H), rect(W // 3, H - 6, W, H)],
                         ids=["full", "growing-from-left", "ending-at-right"])
def test_a_smooth_bar_from_a_corner_of_a_side_is_not_content_cut_by_it(bar):
    """The gate deck's own progress bar (measured false positive of `edge_clipped`: 27 of 45 smoke frames before the rework): a smooth
    ink run that touches a corner of the side is a full-bleed bar, neither a clip nor text."""

    assert findings_of(frame(draw=both(TITLE, bar))) == []


def test_a_corner_run_that_is_textured_or_a_smooth_block_away_from_the_corners_is_still_reported():
    found = findings_of(frame(draw=both(TITLE, strokes(0, 120, H - 8, H))))   # text cut by the bottom, from its left corner
    assert set(codes(found)) == {"edge_text_overflow"} and {f.metric["side"] for f in found} == {"bottom", "left"}
    found = findings_of(frame(draw=both(TITLE, rect(40, H - 6, W - 40, H))))   # a smooth block cut by the bottom, no corner
    assert codes(found) == ["edge_clipped"] and found[0].metric["side"] == "bottom"


def test_a_grey_frame_must_have_the_size_it_claims():
    with pytest.raises(ValueError):
        Q.GrayFrame(4, 4, b"\x00" * 15)


# ------------------------------------------------------------------ sequences


def test_sampled_frames_that_never_change_are_a_static_scene_and_a_moving_scene_is_not():
    still = frame(draw=TITLE)
    assert codes(Q.repeated_findings([(0, still), (45, still), (89, still)], scene="S1")) == ["static_scene"]
    moving = [(n, frame(draw=both(TITLE, rect(0, H - 6, 1 + n * 3, H)))) for n in (0, 45, 89)]
    assert Q.repeated_findings(moving) == []


def test_two_equal_sampled_frames_of_a_moving_scene_are_only_information():
    a, b = frame(draw=TITLE), frame(draw=both(TITLE, rect(0, H - 6, 90, H)))
    [found] = Q.repeated_findings([(0, a), (1, a), (45, b)])
    assert found.code == "repeated_frames" and found.severity is Q.Severity.INFO and found.frame == 1


def test_a_playing_picture_that_stays_the_same_for_a_second_is_frozen_playback():
    still = frame(draw=TITLE)
    caps = [(ms, still, True) for ms in range(0, 1300, 100)]
    [found] = Q.frozen_spans(caps)
    assert found.code == "frozen_playback" and found.metric == {"from_ms": 0, "to_ms": 1200}
    assert Q.frozen_spans([(ms, still, False) for ms in range(0, 3000, 100)]) == [], "a paused, held frame is not frozen playback"
    assert Q.frozen_spans(caps[:8]) == [], "under the threshold (700 ms)"


def test_a_frozen_span_only_counts_pairs_of_captures_that_both_play():
    """The paused / playing boundary: a held, paused picture (0 to 2000 ms) then 900 ms of playing on the same picture is under the
    threshold; the pair across the boundary (paused, playing) must not stretch the run to 1000 ms."""

    still = frame(draw=TITLE)
    paused_then_playing = [(ms, still, False) for ms in range(0, 2100, 100)] + [(ms, still, True) for ms in range(2100, 3100, 100)]
    assert Q.frozen_spans(paused_then_playing) == []
    playing_then_paused = [(ms, still, True) for ms in range(0, 1000, 100)] + [(ms, still, False) for ms in range(1000, 3000, 100)]
    assert Q.frozen_spans(playing_then_paused) == []


# ------------------------------------------------------------------ the four regressions of the Slice


def test_transition_flash_a_black_capture_at_a_hand_over_blocks():
    caps = [(0, Q.measure(frame(draw=TITLE))), (100, Q.measure(frame(0))), (200, Q.measure(frame(draw=TITLE)))]
    [found] = Q.flash_findings(caps)
    assert found.code == "transition_flash" and found.severity is Q.Severity.BLOCKING and found.metric["ms"] == 100
    assert Q.flash_findings(caps[::2]) == []


@pytest.mark.parametrize("fill,kind", [(255, "blank"), (128, "blank")], ids=["white", "mid-grey"])
def test_transition_flash_a_one_frame_white_or_grey_flash_blocks_too(fill, kind):
    caps = [(0, Q.measure(frame(draw=TITLE))), (100, Q.measure(frame(fill))), (200, Q.measure(frame(draw=TITLE)))]
    [found] = Q.flash_findings(caps)
    assert found.code == "transition_flash" and found.severity is Q.Severity.BLOCKING and found.metric["ms"] == 100
    assert kind in found.detail and found.metric["mean"] == fill


def test_time_carry_a_scene_that_enters_past_its_frame_zero_blocks():
    rows = [{"scene": "S6", "duration_in_frames": 90, "fps": 30, "max_frame": 89, "played_ms": 2967, "first_frame": 37}]
    assert codes(Q.playback_findings(rows)) == ["time_carry"]
    rows[0]["first_frame"] = 0
    assert Q.playback_findings(rows) == []


def test_cut_at_8s_a_30s_scene_stopped_at_its_score_target_blocks():
    """Defect E of the handoff: a 900-frame scene whose score item targets 8 s must still play its 900 frames."""

    cut = {"scene": "S3", "duration_in_frames": 900, "fps": 30, "max_frame": 239, "played_ms": 8000, "first_frame": 0}
    [found] = Q.playback_findings([cut])
    assert found.code == "truncated" and found.severity is Q.Severity.BLOCKING and found.metric["expected_ms"] == 29967
    whole = {**cut, "max_frame": 899, "played_ms": 30007}
    assert Q.playback_findings([whole]) == []
    short = {**whole, "played_ms": 25000}   # reached its last frame, but by skipping: still cut
    assert codes(Q.playback_findings([short])) == ["truncated"]
    assert codes(Q.playback_findings([{**whole, "max_frame": None, "played_ms": None}])) == ["truncated"]


def test_stale_progress_a_transport_that_stays_behind_the_player_blocks():
    """Defect D of the handoff (Slice 03: Player at 21.3 s, readouts at 4.4 s): the transport's frame against the composition frame the
    Player's own clock gives (`CompositionMap.frame_of`)."""

    cmap = build_composition([SceneManifest("pss_1", "Scene", 30, 90), SceneManifest("pss_2", "Scene", 60, 480)])
    assert cmap.fps == 60 and cmap.frame_of(1, 120) == 180 + 120
    fine = [{"ms": 0, "transport": 300 - 20, "expected": cmap.frame_of(1, 120)}]   # 333 ms behind: the measured update cadence
    assert Q.stale_progress_findings(fine, fps=cmap.fps) == []
    stuck = [{"ms": 0, "transport": 180, "expected": cmap.frame_of(1, 300)}]   # stuck on the scene's start, Player 5 s in
    [found] = Q.stale_progress_findings(stuck, fps=cmap.fps)
    assert found.code == "stale_progress" and found.severity is Q.Severity.BLOCKING
    assert Q.stale_progress_findings([{**stuck[0], "transport_tolerance": 500}], fps=cmap.fps) == [], "the sampling tolerance is honoured"


def test_stale_progress_the_scenes_own_bar_against_its_frame():
    half = frame(draw=both(TITLE, rect(0, H - 6, W // 2, H)))
    assert Q.bar_share(half) == pytest.approx(0.5, abs=0.01)
    assert Q.stale_progress_findings([{"ms": 5, "bar_share": Q.bar_share(half), "local_share": 0.52}], fps=30) == []
    [found] = Q.stale_progress_findings([{"ms": 5, "bar_share": Q.bar_share(half), "local_share": 0.9}], fps=30)
    assert found.code == "stale_scene_bar"
    assert Q.stale_progress_findings([{"bar_share": 0.5, "local_share": 0.9, "bar_tolerance": 0.4}], fps=30) == []


def test_the_bar_is_read_inside_a_letterboxed_capture():
    def letterbox(pixels: bytearray) -> None:
        for y in range(H):
            for x in range(W):
                if y < 20 or y >= H - 20:
                    pixels[y * W + x] = 0
        rect(0, H - 26, W // 4, H - 20)(pixels)
    assert Q.content_box(frame(60, draw=letterbox)) == (0, 20, W, H - 20)
    assert Q.bar_share(frame(60, draw=letterbox)) == pytest.approx(0.25, abs=0.01)
    assert Q.bar_share(frame(60, draw=TITLE)) == 0.0


# ------------------------------------------------------------------ the scene's page


def test_a_font_list_with_nothing_available_and_no_generic_falls_back_to_the_browser_default():
    found = Q.font_findings([{"family": "JarvisNoSuchFont", "available": {"JarvisNoSuchFont": False}, "failed_faces": []}], scene="S3")
    assert codes(found) == ["font_fallback"] and found[0].severity is Q.Severity.BLOCKING


def test_a_missing_first_font_with_a_declared_stack_is_a_substitution():
    found = Q.font_findings([{"family": '"Inter", "Segoe UI", sans-serif', "available": {"Inter": False, "Segoe UI": True}}])
    assert codes(found) == ["font_substituted"] and found[0].metric["drawn"] == "Segoe UI" and found[0].severity is Q.Severity.WARNING
    assert Q.font_findings([{"family": '"Segoe UI", system-ui, sans-serif', "available": {"Segoe UI": True}}]) == []
    assert Q.font_findings([{"family": "system-ui, sans-serif", "available": {}}]) == []


def test_a_font_file_that_failed_to_load_blocks_once():
    found = Q.font_findings([{"family": "", "failed_faces": ["Brand"]}, {"family": "", "failed_faces": ["Brand"]}])
    assert codes(found) == ["font_load_failed"]


def test_a_missing_asset_blocks_and_names_only_the_file():
    [found] = Q.asset_findings([{"kind": "image", "url": "http://127.77.0.2:5555/page/scene-x/logo.png?v=2", "status": 404}])
    assert found.code == "asset_missing" and found.severity is Q.Severity.BLOCKING and found.metric["name"] == "logo.png"
    assert "127.77" not in found.detail


def test_text_out_of_the_frame_or_cut_by_its_box_is_a_warning():
    found = Q.dom_overflow_findings([{"text": "Un titre trop long", "outside": {"left": 0, "right": 613, "top": 0, "bottom": 0}},
                                     {"text": "Cut", "clipped": True}, {"text": "fine"}])
    assert codes(found) == ["text_overflow", "text_overflow"] and found[0].metric["outside"] == {"right": 613}


# ------------------------------------------------------------------ smoke path and report


@pytest.mark.parametrize("duration,expected", [
    (1, [(0, Q.Role.LAST)]),
    (2, [(0, Q.Role.EXIT), (1, Q.Role.LAST)]),
    (3, [(0, Q.Role.FIRST), (1, Q.Role.EXIT), (2, Q.Role.LAST)]),
    (90, [(0, Q.Role.FIRST), (1, Q.Role.ENTRY), (44, Q.Role.MIDDLE), (88, Q.Role.EXIT), (89, Q.Role.LAST)]),
])
def test_the_smoke_frames_of_a_scene(duration, expected):
    assert list(Q.smoke_frames(duration)) == expected
    assert len(Q.smoke_frames(duration)) <= 6, "one preview request (MAX_PREVIEW_FRAMES)"


def test_the_smoke_frames_refuse_a_scene_without_frames():
    with pytest.raises(ValueError):
        Q.smoke_frames(0)


def test_the_transition_pairs_put_the_last_frame_beside_the_next_first():
    assert Q.transition_pairs(["a", "b", "c"]) == [(("a", Q.Role.LAST), ("b", Q.Role.FIRST)), (("b", Q.Role.LAST), ("c", Q.Role.FIRST))]


def test_the_report_keeps_four_separate_sections_and_never_a_human_verdict():
    found = [Q.Finding("black", Q.Severity.BLOCKING, "x", "S1", 3), Q.Finding("edge_clipped", Q.Severity.WARNING, "y")]
    report = Q.report_sections(found, compilation={"status": "compiled"})
    assert list(report) == ["compilation", "first_draft_gate", "frame_quality", "human_assessment"]
    assert report["compilation"] == {"status": "compiled"} and report["first_draft_gate"] == {"status": "not_run_here"}
    assert report["frame_quality"]["verdict"] == "blocked" and report["frame_quality"]["counts"] == {"black": 1, "edge_clipped": 1}
    assert report["human_assessment"]["status"] == "pending"
    assert Q.verdict(found[1:]) == "warnings" and Q.verdict([]) == "clean"

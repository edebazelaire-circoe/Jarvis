"""`docs/presentation-studio.md` > *Rendered-frame quality gates* against the code (native-studio-playback-fix Slice 14).

Every finding code the detectors can emit is documented with its severity; every threshold is documented with its value; the owners,
the evidence files and the conformance tests the section names exist.
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
import re

from jarvis.adapters import remotion_media_tools as M
from jarvis.media import frame_quality as Q

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "docs" / "presentation-studio.md").read_text(encoding="utf-8")
START = DOC.index("## Rendered-frame quality gates (Level 3, native-studio-playback-fix Slice 14)")
SECTION = DOC[START:DOC.index("\n## ", START + 10)]
SOURCE = (ROOT / "jarvis" / "media" / "frame_quality.py").read_text(encoding="utf-8")


def emitted_codes() -> set[str]:
    return set(re.findall(r'Finding\(\s*"([a-z_]+)"', SOURCE)) | set(re.findall(r'code = "([a-z_]+)" if', SOURCE)) | {"blank", "render_failed"}


def test_every_finding_code_is_in_the_table():
    rows = [line for line in SECTION.splitlines() if line.startswith("| `")]
    documented = {code for line in rows for code in re.findall(r"`([a-z_]+)`", line.split("|")[1])}
    assert emitted_codes() <= documented, sorted(emitted_codes() - documented)


def test_every_threshold_is_documented_with_its_value():
    for item in fields(Q.Thresholds):
        value = getattr(Q.THRESHOLDS, item.name)
        forms = {str(value)} | ({str(int(value))} if float(value).is_integer() else set()) | {f"{round(value * 100)} %"}
        assert any(f"`{item.name}` = {form}" in SECTION for form in forms), (item.name, sorted(forms))


def test_the_blocking_codes_are_said_blocking_and_the_warnings_warnings():
    table = {line.split("|")[1].strip(): line.split("|")[3].strip() for line in SECTION.splitlines() if line.startswith("| `")}
    def severity(code: str) -> str:
        return next(sev for key, sev in table.items() if f"`{code}`" in key)
    for code in ("transition_flash", "time_carry", "truncated", "stale_progress", "stale_scene_bar", "font_fallback", "asset_missing",
                 "render_failed"):
        assert severity(code) == "**blocking**", code
    for code in ("edge_clipped", "edge_text_overflow", "frozen_playback", "font_substituted", "text_overflow"):
        assert severity(code) == "warning", code


def test_the_four_sections_and_the_human_assessment_are_stated():
    report = Q.report_sections([])
    for name in report:
        assert f"`{name}`" in SECTION, name
    assert "never stands in for the Human creative" in SECTION


def test_the_owners_tests_and_media_defaults_named_exist():
    for path in re.findall(r"`((?:jarvis|tests)/[\w/]+\.py)`", SECTION):
        assert (ROOT / path).is_file(), path
    assert f"`WORK_WIDTH` = {Q.WORK_WIDTH}" in SECTION
    assert f"{M.DEFAULT_VIDEO_FPS} i/s, {M.DEFAULT_VIDEO_WIDTH} px, CRF {M.DEFAULT_VIDEO_CRF}" in SECTION
    assert "/v1/local-capabilities/remotion/render/preview" in SECTION


def test_the_release_evidence_named_is_committed():
    evidence = ROOT / "tasks" / "jarvis-remotion-native-studio-playback-fix" / "slices" / "14-visual-quality-and-media-gates" / "evidence"
    if not evidence.is_dir():
        return  # the handoff folder leaves the repository at close-out; the contract stays
    for name in re.findall(r"`([\w-]+\.(?:mp4|json|jpg))`", SECTION):
        assert (evidence / name).is_file(), name

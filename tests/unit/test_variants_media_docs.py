"""Le contrat *Variants media and fullscreen (Level 3, Slice 08)* et § 10.6 de l'isolation, contre le code (native-studio-playback-fix)."""

from __future__ import annotations

from pathlib import Path

from jarvis.domain import remotion_sandbox as sb

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "docs" / "presentation-studio.md").read_text(encoding="utf-8")
ISOLATION = (ROOT / "docs" / "remotion-isolation.md").read_text(encoding="utf-8")
RUNTIME = ROOT / "jarvis" / "runtime"
SECTION = DOC.split("### Variants media and fullscreen (Level 3, Slice 08)", 1)[1].split("\n### ", 1)[0]


def test_the_section_names_its_owners_controls_and_tests_and_they_exist():
    for needle in ("control_center_presentation_studio_stage_media.js", "`allow=\"autoplay\"`", "numberOfSharedAudioTags: 0", "CHROME_HIDE_MS",
                   "data-object-id=\"studio-explorer-stage\"", "`Maj+F`", "HV-RFX-08-01", "keysRefused", "« Activer le son (M) »"):
        assert needle in SECTION, needle
    for path in ("tests/unit/test_variants_media_js.py", "tests/unit/test_variants_media_fullscreen_browser.py", "tests/unit/test_variants_media_export.py",
                 "jarvis/runtime/control_center_presentation_studio_stage_media.js"):
        assert (ROOT / path).is_file(), path


def test_the_contract_matches_the_code():
    media = (RUNTIME / "control_center_presentation_studio_stage_media.js").read_text(encoding="utf-8")
    child = (RUNTIME / "remotion_sandbox_child.js").read_text(encoding="utf-8")
    core = (RUNTIME / "control_center_presentation_studio_explorer_core.js").read_text(encoding="utf-8")
    assert "const CHROME_HIDE_MS=2500;" in media and "2.5 s (`CHROME_HIDE_MS`)" in SECTION
    assert "titleOff:'Activer le son (M)'" in media
    assert "numberOfSharedAudioTags:0" in child and "const AUDIO_STALL_MS=1500;" in child and "1.5 s" in SECTION
    assert "const STAGE_OBJECT_ID='studio-explorer-stage';" in core
    assert sb.IFRAME_ATTRIBUTES["allow"] == "autoplay" and '`allow="autoplay"`' in ISOLATION
    for needle in ("`sound {muted}`", "`audio {muted, blocked}`", "`key {key}`", "Résiduel de `allow=\"autoplay\"`", "numberOfSharedAudioTags: 0"):
        assert needle in ISOLATION, needle

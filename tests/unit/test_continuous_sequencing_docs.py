"""Conformité doc <-> code de la lecture continue dans Variantes (handoff jarvis-remotion-native-studio-playback-fix, Slice 05).

`docs/presentation-studio.md` > *Continuous sequencing in Variants (Level 3, Slice 05)* nomme un propriétaire, des règles et des preuves :
ce test vérifie que chacun existe et que ce que la section dit retiré l'est vraiment.
"""

from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "presentation-studio.md"
RUNTIME = ROOT / "jarvis" / "runtime"


def section(text: str, title: str) -> str:
    start = text.index(title)
    following = re.search(r"\n### ", text[start + len(title):])
    return text[start:start + len(title) + (following.start() if following else len(text))]


def test_the_section_names_its_owner_rules_and_proofs_and_they_exist():
    text = DOC.read_text(encoding="utf-8")
    body = section(text, "### Continuous sequencing in Variants (Level 3, Slice 05)")
    for needle in ("control_center_presentation_studio_sequencer.js", "JarvisStudioExplorer.playback", "fromWire", "once** more",
                   "« La variante a changé »", "**authored** length", "moveToBeginningWhenEnded: false", "« Rejouer »", "swapPrefix",
                   "queued", "hybrid frame", "takes the window", "« Chargement de la scène n sur N · s »", "« Réessayer »",
                   "Never a skip, never a Slidecar fallback", "test_presentation_continuous_playback_browser.py", "sequencer_failed"):
        assert needle in body, needle
    for path in ("jarvis/runtime/control_center_presentation_studio_sequencer.js", "tests/unit/test_continuous_sequencing_js.py",
                 "tests/unit/test_presentation_continuous_playback_browser.py"):
        assert (ROOT / path).is_file(), path
    assert "**Slice 05** (continuous sequencing), **done**" in text
    assert "(no page includes it yet)" not in text


def test_what_the_section_says_is_retired_is_retired():
    autoplay = (ROOT / "jarvis" / "core" / "presentation_studio_autoplay.py").read_text(encoding="utf-8")
    assert "GRACE_MS =" not in autoplay and "LOAD_ALLOWANCE_MS =" not in autoplay and "_played_enough" not in autoplay
    assert "return None   # a media segment: only its Player's end (`done`) moves on" in autoplay
    child = (RUNTIME / "remotion_sandbox_child.js").read_text(encoding="utf-8")
    assert "loop:false,moveToBeginningWhenEnded:false" in child and "loop:true" not in child
    host = (RUNTIME / "control_center_prefab_host.js").read_text(encoding="utf-8")
    assert "scene.prefab_preload_queued" in host


def test_the_page_loads_the_clock_and_the_sequencer_before_the_explorer():
    html = (RUNTIME / "control_center.html").read_text(encoding="utf-8")
    order = [html.index(marker) for marker in ("/*__CONTROL_CENTER_COMPOSITION_CLOCK_JS__*/", "/*__CONTROL_CENTER_PRESENTATION_STUDIO_SEQUENCER_JS__*/",
                                               "/*__CONTROL_CENTER_PRESENTATION_STUDIO_EXPLORER_JS__*/")]
    assert order == sorted(order)
    page = (RUNTIME / "control_center.py").read_text(encoding="utf-8")
    assert '"control_center_composition_clock.js"' in page and '"control_center_presentation_studio_sequencer.js"' in page
    explorer = (RUNTIME / "control_center_presentation_studio_explorer.js").read_text(encoding="utf-8")
    assert "swapPrefix:'presentation-studio.'" in explorer and "'data-act':'continuous'" in explorer and "'Tout jouer'" not in explorer

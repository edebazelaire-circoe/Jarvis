"""Code/documentation parity of « Remotion Studio » in Variants (jarvis-remotion-native-studio-playback-fix, Slice 11).

The section *Remotion Studio from Variants (Level 3, Slice 11)* of `docs/presentation-studio.md` says what the code does: its owners exist
under the names it gives, the names the user reads are the ones the code writes (PX-1: never the bare « Studio »), the spoken pointer is
the one the brain's tool returns, every test file it cites exists, and the earlier sections no longer promise Slice 11 as future work.
"""

from __future__ import annotations

from pathlib import Path
import re

from jarvis.runtime import remotion_mcp_tools
from tests.unit.test_presentation_studio_docs import page

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
DOOR = (RUNTIME / "control_center_presentation_studio_explorer_remotion.js").read_text(encoding="utf-8")
EXPLORER = (RUNTIME / "control_center_presentation_studio_explorer.js").read_text(encoding="utf-8")
CARD = (RUNTIME / "control_center_remotion_studio.js").read_text(encoding="utf-8")
RAIL = (RUNTIME / "control_center_presentation_rail.js").read_text(encoding="utf-8")
TITLE = "### Remotion Studio from Variants (Level 3, Slice 11)"


def section() -> str:
    text = page("presentation-studio.md")
    start = text.index(TITLE)
    return text[start:text.index("\n### ", start + len(TITLE))]


def test_the_owners_the_section_names_exist_under_those_names():
    text = section()
    for name in ("createRemotionDoor", "doorModel", "isRemotionManifest"):
        assert f"`{name}`" in text and f"function {name}(" in DOOR, name
    assert "`JarvisVariantsRemotionStudio`" in text and "root.JarvisVariantsRemotionStudio=api" in DOOR
    assert "window.JarvisRemotionStudioCore=JarvisRemotionStudioCore" in CARD, "the door reuses the card's core (one client)"
    assert "createClient" in DOOR and "confirmSpec" in DOOR and "fetch(" not in DOOR.replace("ctx.fetch(", ""), "no second Studio client"
    assert "`onClose`" in text and "onClose:spec.onClose" in EXPLORER
    assert "remotionStudio:Object.freeze({request:" in EXPLORER and "{act:'studio',label:'Remotion Studio…'" in RAIL
    assert "function remotionStudio(id)" in RAIL


def test_the_names_the_user_reads_are_the_ones_the_code_writes_and_never_the_bare_studio():
    text = section()
    for name in ("Remotion Studio, ouvert sur cette scène", "Ouvrir l'onglet Remotion Studio", "Remotion Studio démarre…",
                 "la variante n'a pas changé", "Ouvrir cette scène dans Remotion Studio", "Fermer Remotion Studio"):
        assert name in text, name
        assert name.replace("'", "’") in DOOR + CARD or name in DOOR + CARD, name
    # PX-1 on the card: the strings the user reads never name it « le Studio », « du Studio », « Remotion · Studio »
    shown = CARD[:CARD.index("function createClient(")] + CARD[CARD.index("installJarvisRemotionStudio"):]
    flat = [a or b for a, b in re.findall(r"'([^'\n]*)'|`([^`\n]*)`", shown)]
    bare = [s for s in flat if re.search(r"\b(le|du|au) Studio\b|Remotion · Studio|Studio Remotion", s)]
    assert bare == [], bare
    assert "Remotion · Studio" not in CARD and ">Remotion Studio</h3>" in CARD


def test_the_spoken_pointer_is_the_one_the_tool_returns():
    text = section()
    assert remotion_mcp_tools.CARD_PATH in text, "where the user clicks"
    assert "« Remotion Studio » sous la vidéo et confirme" in text
    source = (RUNTIME / "remotion_mcp_tools.py").read_text(encoding="utf-8")
    assert "clique « Remotion Studio » sous la vidéo et confirme" in source and "Ouvrir le Studio" not in source


def test_every_test_file_the_section_cites_exists():
    cited = set(re.findall(r"`(?:tests/unit/)?(test_[a-z0-9_]+\.py)`", section()))
    assert {"test_variants_remotion_studio_js.py", "test_variants_remotion_studio_browser.py", "test_variants_remotion_studio_docs.py"} <= cited
    for name in cited:
        assert (ROOT / "tests" / "unit" / name).exists(), name


def test_earlier_sections_no_longer_promise_slice_11_as_future_work():
    text = page("presentation-studio.md")
    assert "Today it is reachable only from the « Remotion · Studio » card of the MCP dialog; Slice 11 makes it reachable from Variants" not in text
    assert "« Remotion Studio » on the scene row is Slice 11." not in text
    assert "Slice 11 designs the indicator" not in text
    assert "Done by Slice 11 (*Remotion Studio from Variants (Level 3, Slice 11)*): #22" in text
    studio = page("remotion-studio.md")
    assert "carte « Remotion · Studio »\n" not in studio and "La porte de Variantes (native-studio-playback-fix Slice 11)" in studio
    runtime = page("remotion-runtime.md")
    assert "« Remotion Studio » sous la vidéo de Variantes" in runtime

"""Code/documentation parity of the Variants control audit (jarvis-remotion-native-studio-playback-fix, Slice 10).

The section *Variants control audit (Level 3, Slice 10)* of `docs/presentation-studio.md` says what the code does: its owners exist under
the names it gives, the keyboard sheet is derived from the one key map, every test file it cites exists, the retired controls are really
gone from the code, and the earlier sections no longer promise them as future work.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

from tests.unit.test_presentation_studio_docs import page

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
EXPLORER = (RUNTIME / "control_center_presentation_studio_explorer.js").read_text(encoding="utf-8")
CORE = (RUNTIME / "control_center_presentation_studio_explorer_core.js").read_text(encoding="utf-8")
MEDIA = (RUNTIME / "control_center_presentation_studio_stage_media.js").read_text(encoding="utf-8")
TITLE = "### Variants control audit (Level 3, Slice 10)"


def section() -> str:
    text = page("presentation-studio.md")
    start = text.index(TITLE)
    return text[start:text.index("\n### ", start + len(TITLE))]


def test_the_owners_the_section_names_exist_under_those_names():
    text = section()
    for name in ("openShortcuts", "setRunInert", "renderRun", "renderPresent", "buildTransport"):
        assert f"`{name}`" in text and f"function {name}(" in EXPLORER, name
    assert "`TREE_SHORTCUTS`" in text and "const TREE_SHORTCUTS=" in CORE
    for name in ("KEY_ACTIONS", "KEY_NAMES", "shortcutRows"):
        assert f"`{name}`" in text and name in MEDIA, name
    for hook in ("data-run", ".jvx-run-note", 'data-kind="shortcuts"'):
        assert hook in text, hook
    assert "setAttribute('data-run'" in EXPLORER and "jvx-run-note" in EXPLORER and "'data-kind','shortcuts'" in EXPLORER


def test_the_sheet_is_derived_from_the_key_map_and_the_section_says_the_count_label_the_code_writes():
    rows = json.loads(subprocess.run(
        ["node", "-e", f"process.stdout.write(JSON.stringify(require({json.dumps(str(RUNTIME / 'control_center_presentation_studio_stage_media.js'))}).shortcutRows('video')))"],
        capture_output=True, text=True, encoding="utf-8", check=True, timeout=60).stdout)
    assert {r["action"] for r in rows} >= {"toggle", "next", "previous", "fullscreen", "sound", "escape", "help"}
    assert "`${live} / ${MAX_LIVE} variantes`" in EXPLORER and "« 3 / 64 variantes »" in section()


def test_the_retired_controls_are_gone_from_the_code():
    for gone in ("jvx-vbar", "jvx-vchip", "renderVariantBar", "parcourir · Entrée choisir", "Fermer l'explorateur de variantes"):
        assert gone not in EXPLORER and gone not in CORE, gone
    toolbar = EXPLORER[EXPLORER.index("function buildTransport("):EXPLORER.index("function moveScene(")]
    assert "ui.present,ui.stopRun" not in toolbar and "ui.more,ui.stopRun])ui.transport.appendChild" in toolbar, \
        "« Présenter » is on the scene row, not in the playback toolbar"


def test_every_test_file_the_section_cites_exists():
    cited = set(re.findall(r"`(?:tests/unit/)?(test_[a-z0-9_]+\.py)`", section()))
    assert {"test_variants_controls_js.py", "test_variants_controls_browser.py", "test_variants_controls_docs.py"} <= cited, cited
    for name in cited:
        assert (ROOT / "tests" / "unit" / name).exists(), name


def test_earlier_sections_no_longer_promise_slice_10_as_future_work():
    text = page("presentation-studio.md")
    assert "the keyboard sheet (`?`) and the control audit are Slice 10." not in text
    assert "the keyboard sheet (`?`) is Slice 10." not in text
    assert "The tree, the actions, the variant bar and the upgrade notice are `inert`" not in text
    assert "Done by Slice 10 (*Variants control audit (Level 3, Slice 10)*)" in text, "§ 6 says which target rows are done"

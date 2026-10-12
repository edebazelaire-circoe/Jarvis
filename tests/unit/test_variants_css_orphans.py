"""No orphaned Variants style rule (native-studio-playback-fix Slice 15, cleanup).

Every `.jvx-*` class a Variants style sheet names must be a class some page module actually puts on an element. A selector without an
element is dead weight at best, and at worst a rule that silently does nothing: Slice 10 dimmed « the upgrade notice » during a run with
`.jvx-upgrades` while the notice is built as `.jvx-upg`, so it was never dimmed (found by the Slice 15 audit). Static scan, no browser.
"""

from __future__ import annotations

from pathlib import Path
import re

RUNTIME = Path(__file__).resolve().parents[2] / "jarvis" / "runtime"
MODULES = sorted(RUNTIME.glob("control_center_presentation_studio_*.js")) + [RUNTIME / "control_center_presentation_rail.js"]
SELECTOR = re.compile(r"\.(jvx-[A-Za-z0-9_-]+)")


def _classes_named_by_rules(text: str) -> set[str]:
    return set(SELECTOR.findall(text))


#: JS comments: a class named only in a comment is not built by anything (`//` after `:` is a URL, not a comment).
COMMENT = re.compile(r"""/\*[\s\S]*?\*/|(?<![:'"\\])//[^\n]*""")


def _used_outside_selectors(name: str, texts: list[str]) -> bool:
    # A use is the bare token (in a class string, a classList call, a template), not preceded by `.` (a selector), outside comments.
    bare = re.compile(r"(?<![.\w-])" + re.escape(name) + r"(?![\w-])")
    return any(bare.search(COMMENT.sub(" ", text)) for text in texts)


def test_a_class_named_only_in_a_comment_is_not_a_use():
    assert not _used_outside_selectors("jvx-ghost", ["/* el('div','jvx-ghost') */ const a=1; // el('div','jvx-ghost')\n.jvx-ghost{}"])
    assert _used_outside_selectors("jvx-real", ["const u='http://x/y';el('div','jvx-real')"])


def test_every_variants_style_rule_names_a_class_the_page_builds():
    texts = [path.read_text(encoding="utf-8") for path in MODULES]
    assert len(texts) > 10, "the Variants modules were not found"
    named = set().union(*(_classes_named_by_rules(text) for text in texts))
    assert {"jvx-upg", "jvx-treepane", "jvx-transport"} <= named
    orphans = sorted(name for name in named if not _used_outside_selectors(name, texts))
    assert orphans == [], f"style rules for classes no module builds: {orphans}"


def test_the_run_dims_the_upgrade_notice_by_the_class_it_is_built_with():
    core = (RUNTIME / "control_center_presentation_studio_explorer_core.js").read_text(encoding="utf-8")
    upgrades = (RUNTIME / "control_center_presentation_studio_explorer_upgrades.js").read_text(encoding="utf-8")
    assert "section=el('section','jvx-upg')" in upgrades
    dim = next(line for line in core.splitlines() if "[data-run] .jvx-treepane" in line)
    assert "[data-run] .jvx-upg{" in dim, dim

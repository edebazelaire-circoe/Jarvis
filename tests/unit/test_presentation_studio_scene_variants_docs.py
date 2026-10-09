"""Parité code/documentation des variantes locales d'une scène (jarvis-interactive-presentation-studio, Slice 17).

Les pages disent ce que le code fait : opérations, codes, bornes, diagnostics, chemins de modules, schéma et règle de fusion avec
la Slice 06, noms canoniques (section 16), lignes de `local-data.md`, `OPERATIONS.md`, `conversation-events.md`, `prefabs.md`.
"""

from __future__ import annotations

from pathlib import Path
import re

from jarvis.core import presentation_studio_scene_variants as core_module
from jarvis.domain import presentation_studio as ps
from jarvis.domain import presentation_studio_scene_variants as domain_module
from jarvis.domain.presentation_studio_checks import HTTP_STATUS, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_edit import OpName
from tests.unit.test_presentation_studio_docs import page

ROOT = Path(__file__).resolve().parents[2]


def section() -> str:
    text = page("presentation-studio.md")
    start = text.index("## Scene-local variant contract (Level 3, Slice 17)")
    return text[start:text.index("\n## ", start + 10)]


def names() -> str:
    text = (ROOT / "tasks" / "jarvis-interactive-presentation-studio" / "docs" / "09-canonical-names.md").read_text(encoding="utf-8")
    return text[text.index("## 21. Slice 17 amendments"):]


def test_every_operation_of_the_vocabulary_is_in_the_section_and_in_the_edit_vocabulary_table():
    text, edit = section(), page("presentation-studio.md")
    for op in (o for o in OpName if o.value.startswith("scene_variant.")):
        assert f"| `{op.value}` |" in text, op
        assert f"| `{op.value}` |" in edit[edit.index("## Semantic edit contract"):edit.index("## Persistence and undo contract")], op


def test_the_new_codes_and_their_statuses_are_documented_where_the_other_codes_are():
    text = section() + page("presentation-studio.md")[page("presentation-studio.md").index("## Semantic edit contract"):]
    for code, status in ((C.UNKNOWN_SCENE_VARIANT, 404), (C.SCENE_VARIANT_PROTECTED, 409)):
        assert HTTP_STATUS[code] == status and f"`{code.value}`" in text and f"{status}" in text
        assert f"`{code.value}`" in names()


def test_the_bounds_in_the_code_are_the_bounds_in_the_page():
    text = section()
    assert f"{domain_module.MAX_SCENE_VARIANTS} (`MAX_SCENE_VARIANTS`)" in text
    assert f"{domain_module.MAX_SET_BYTES // 1024} KiB" in text and "MAX_SET_BYTES" in text
    assert f"{domain_module.MAX_DECK_VARIANTS} (`MAX_DECK_VARIANTS`)" in text and "Measured sizes" in text and "not a delta" in text
    assert f"{domain_module.MAX_LABEL} / {domain_module.MAX_RATIONALE}" in text
    assert f"default {core_module.PREVIEW_TIMEOUT_S} s, 1..{core_module.MAX_PREVIEW_TIMEOUT_S}" in text
    assert "256 KiB" in text and "16 KiB" in text
    n = names()
    assert "`MAX_SCENE_VARIANTS` 8" in n and "`MAX_SET_BYTES` 32 KiB" in n and "`MAX_DECK_VARIANTS` 48" in n and "label 40, rationale 160" in n


def test_the_diagnostics_the_code_emits_are_documented():
    emitted = set(re.findall(r'self\._trace\(\s*"([a-z_]+)"', (ROOT / "jarvis/core/presentation_studio_scene_variants.py").read_text(encoding="utf-8")))
    emitted |= set(re.findall(r'self\._trace\("(preview_[a-z_]+)"', (ROOT / "jarvis/core/presentation_studio_preview.py").read_text(encoding="utf-8")))
    assert {"scene_variant_described", "scene_variant_previewed", "scene_variant_preview_ended", "scene_variant_promoted",
            "preview_shown", "preview_ended", "preview_timeout_failed"} <= emitted, emitted
    text, canonical = section(), names()
    for kind in emitted:
        assert re.search(r"(?<![a-z_])" + kind + r"(?![a-z_])", text), kind
        assert re.search(r"(?<![a-z_])" + kind + r"(?![a-z_])", canonical), kind


def test_the_schema_decision_and_the_merge_rule_with_slice_06_are_written():
    text = section()
    assert ps.VARIANT_SCHEMA_VERSION == 4 and set(ps.UPGRADES[ps.SCHEMA_VARIANT]) == {1, 2, 3}
    for needle in ("`VARIANT_SCHEMA_VERSION` is **4**", "`UPGRADES[variant][3]` is the **identity**", "Merge rule with Slice 06, done",
                   "One pin function", "held_pins()", "presentation_studio_scene_reloading", "live scene only", "refused while ANY scene", "`current_id`", "`selected` would have been the natural key"):
        assert needle in text, needle
    graph = page("presentation-studio.md")
    assert "Slice 17 took 4" in graph and "scene-local variants live *inside* a variant document" in graph


def test_the_modules_named_by_the_page_exist_and_the_canonical_names_list_them():
    text, canonical = section(), names()
    for module in ("jarvis/domain/presentation_studio_scene_variants.py", "jarvis/core/presentation_studio_scene_variants.py",
                   "jarvis/domain/presentation_studio_scene_variant_ops.py", "jarvis/core/presentation_studio_preview.py",
                   "jarvis/protocol/presentation_studio_scene_variants_routes.py", "jarvis/runtime/presentation_studio_scene_variants_relay.py"):
        assert (ROOT / module).is_file() and module in canonical, module
        assert module in text or Path(module).name in text, module
    for name in ("PresentationStudioSceneVariants", "SceneVariantSet", "held_pins", "show_preview", "end_preview", "transform=",
                 "psx_<12 hex>", "score_regression"):
        assert name in canonical, name


def test_the_other_pages_say_what_changed():
    assert "scene_variants" in page("local-data.md") and "Slice 17" in page("local-data.md")
    assert "Variantes locales d'une scène" in page("OPERATIONS.md")
    assert "scene_variant.create" in page("conversation-events.md") and "never an attribute" in page("conversation-events.md")
    prefabs = page("prefabs.md")
    assert "Slice 17" in prefabs and "held_pins" in prefabs
    assert "Scene-local variant" in page("presentation-studio.md")[page("presentation-studio.md").index("## Documentation levels"):]


def test_the_acceptance_rules_of_the_slice_are_stated_in_the_page():
    text = section()
    for rule in ("invisible", "permutation", "ephemeral", "paused", "archive-free", "promote", "transform", "byte"):
        assert rule in text.lower(), rule

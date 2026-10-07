"""Parité code/documentation du contrat des Presentations (jarvis-interactive-presentation-studio, Slice 02).

Les pages disent ce que le code fait : routes, codes d'erreur, diagnostics,
chemins de modules, ligne `local-data.md`, propriétaire dans `ARCHITECTURE.md`,
note de sauvegarde dans `OPERATIONS.md`, et la décision de stockage (a) : rien
du Studio dans le schéma SQLite.
"""

from __future__ import annotations

from pathlib import Path
import re

from jarvis.domain.presentation_studio import PresentationStudioErrorCode
from jarvis.protocol.presentation_studio_routes import PREFIX, PresentationStudioProtocolRoutes

ROOT = Path(__file__).resolve().parents[2]


def page(name: str) -> str:
    return (ROOT / "docs" / name).read_text(encoding="utf-8")


def _section(title: str) -> str:
    text = page("presentation-studio.md")
    start = text.index(title)
    return text[start:text.index("\n## ", start + 10)]


def scene_section() -> str:
    return _section("## Scene and control contract (Level 3)")


def contract_section() -> str:
    """The Presentation contract plus the scene contract that extends it (routes and codes are tabled in either)."""

    return _section("## Presentation contract (Level 3)") + "\n" + scene_section()


MODULES = ("jarvis/domain/presentation_studio.py", "jarvis/ports/presentation_studio.py",
           "jarvis/adapters/file_presentation_studio_store.py", "jarvis/core/presentation_studio_service.py",
           "jarvis/protocol/presentation_studio_routes.py", "jarvis/domain/presentation_studio_scene.py",
           "jarvis/domain/presentation_studio_checks.py", "jarvis/core/presentation_studio_scene_catalog.py")


def test_every_core_route_is_in_the_contract_table():
    section = contract_section()
    for route in PresentationStudioProtocolRoutes(object()).routes():
        wanted = f"| {route.method} | `{route.path}" if "{" not in route.path else f"| {route.method} | `{route.path}`"
        assert wanted in section.replace("[?limit]", ""), f"undocumented route: {route.method} {route.path}"
    assert PREFIX in section


def test_every_error_code_is_documented_and_every_documented_code_exists():
    section = contract_section()
    for code in PresentationStudioErrorCode:
        assert f"`{code.value}`" in section, code
    documented = set(re.findall(r"`(presentation_studio_[a-z_]+)`", section))
    assert documented <= {code.value for code in PresentationStudioErrorCode}, documented
    for generic in ("invalid_request", "core_unavailable", "internal_error"):
        assert f"`{generic}`" in section


def test_every_diagnostic_kind_the_service_emits_is_documented():
    source = (ROOT / "jarvis/core/presentation_studio_service.py").read_text(encoding="utf-8")
    emitted = set(re.findall(r'"core\.presentation_studio\.([a-z_]+)"', source))
    assert emitted, "no diagnostic found: the pattern drifted"
    section = contract_section()
    paragraph = section[section.index("Diagnostics `core.presentation_studio."):section.index("### Storage")]
    assert "scenes_checked" in paragraph and "scene_described" in paragraph
    missing = {kind for kind in emitted if not re.search(r"(?<![a-z_])" + kind + r"(?![a-z_])", paragraph)}
    assert not missing, missing


def test_the_owner_modules_exist_and_are_named_in_the_pages():
    architecture = page("ARCHITECTURE.md")
    for module in MODULES:
        assert (ROOT / module).is_file(), module
    for needle in ("jarvis/core/presentation_studio_service.py", "jarvis/adapters/file_presentation_studio_store.py",
                   "jarvis/domain/presentation_studio.py", "jarvis/ports/presentation_studio.py",
                   "/v1/presentation-studio/presentations*", "presentation_studio_routes.py"):
        assert needle in architecture, needle


def test_the_storage_decision_and_the_data_pages_agree():
    section = contract_section()
    assert "decision (a)" in section and "not** a `jarvis.sqlite3` v9 migration" in section
    local = page("local-data.md")
    assert "`presentations/<presentation_id>/{presentation.json, variants/<variant_id>.json}`" in local
    assert "## Presentations du Studio : `presentations/`" in local
    operations = page("OPERATIONS.md")
    assert "### Presentations du Studio : sauvegarde et restauration" in operations
    assert "presentation_studio_corrupt_document" in operations and "`presentations/`" in operations
    assert "| **implemented (Level 3)** |" in page("presentation-studio.md")


def test_no_studio_state_leaked_into_the_sqlite_schemas_or_the_repository():
    for module in ("sqlite_state.py", "sqlite_scene.py"):
        assert "presentation_studio" not in (ROOT / "jarvis" / "adapters" / module).read_text(encoding="utf-8")
    assert not list((ROOT / "tests" / "schema").glob("*presentation*"))
    committed = [p for p in (ROOT / "tests" / "fixtures" / "presentation_studio").iterdir()]
    assert committed and all(p.suffix == ".json" for p in committed)
    assert not any(p.suffix in {".sqlite3", ".bak", ".db"} for p in committed)


# ------------------------------------------------------------------ Slice 04 : contrat des scenes et des controles

def test_the_scene_contract_names_every_group_widget_and_limit_the_code_enforces():
    from jarvis.domain import presentation_studio_scene as sc
    from jarvis.domain.scene import MAX_PAYLOAD_BYTES

    section = scene_section()
    for group in sc.ControlGroup:
        assert f"`{group.value}`" in section, group
    for widget in sc.ControlWidget:
        assert f"`{widget.value}`" in section, widget
    assert f"{MAX_PAYLOAD_BYTES:,}".replace(",", " ") in section
    for needle in (f"`controls` (<= {sc.MAX_CONTROLS})", f"`anchors` (<= {sc.MAX_ANCHORS})",
                   f"`label` (<= {sc.MAX_LABEL_CHARS}), `meaning` (<= {sc.MAX_MEANING_CHARS})",
                   f"caption (<= {sc.MAX_CAPTION_CHARS})", f"alt (<= {sc.MAX_ALT_CHARS})",
                   f"`section` (<= {sc.MAX_SECTION_CHARS}"):
        assert needle in section, needle
    for symbol in ("widget_for", "effective_bounds", "suggest_controls", "describe_scene", "PrefabService.manifest",
                   "PrefabService.validate_instance", "CURRENT_VERSIONS", "UPGRADES[variant][1]"):
        assert symbol in section, symbol


def test_the_scene_contract_symbols_exist_in_the_code():
    from jarvis.core.presentation_studio_service import PresentationStudioService
    from jarvis.domain import presentation_studio as ps
    from jarvis.domain import presentation_studio_scene as sc
    from jarvis.protocol.client import LocalCoreClient

    for name in ("widget_for", "effective_bounds", "suggest_controls", "describe_scene", "check_scene"):
        assert callable(getattr(sc, name)), name
    assert callable(PresentationStudioService.describe_scene) and callable(LocalCoreClient.presentation_studio_scene_controls)
    assert ps.CURRENT_VERSIONS == {ps.SCHEMA_PRESENTATION: 1, ps.SCHEMA_VARIANT: 2} and 1 in ps.UPGRADES[ps.SCHEMA_VARIANT]
    section = scene_section()
    assert "`schema_version` **2**" in section and "the Presentation document stays 1" in section


def test_the_prefab_page_lists_the_studio_as_a_consumer_and_the_levels_table_is_updated():
    consumers = page("prefabs.md")
    consumers = consumers[consumers.index("## Consumers (Presentation seam)"):]
    assert "Presentation Studio as a consumer" in consumers and "PrefabCatalog" in consumers
    assert "presentation-studio.md#scene-and-control-contract-level-3" in consumers
    studio = page("presentation-studio.md")
    assert "| Studio scene + control |" in studio and studio.count("**implemented (Level 3)**") >= 2
    assert "scene-and-control-contract-level-3" in studio

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


def contract_section() -> str:
    text = page("presentation-studio.md")
    start = text.index("## Presentation contract (Level 3)")
    return text[start:text.index("\n## ", start + 10)]


MODULES = ("jarvis/domain/presentation_studio.py", "jarvis/ports/presentation_studio.py",
           "jarvis/adapters/file_presentation_studio_store.py", "jarvis/core/presentation_studio_service.py",
           "jarvis/protocol/presentation_studio_routes.py")


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
    source = (ROOT / MODULES[3]).read_text(encoding="utf-8")
    emitted = set(re.findall(r'"core\.presentation_studio\.([a-z_]+)"', source))
    assert emitted, "no diagnostic found: the pattern drifted"
    section = contract_section()
    paragraph = section[section.index("Diagnostics `core.presentation_studio."):section.index("### Storage")]
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

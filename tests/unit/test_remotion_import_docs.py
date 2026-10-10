"""`docs/remotion-import.md` contre le code (Slice 18) : chaque code, statut, borne, licence, route et lien cité existe et dit vrai."""

from __future__ import annotations

from pathlib import Path
import re

from jarvis.core.remotion_import_service import status_of
from jarvis.domain import remotion_import as ri
from jarvis.domain import remotion_upstream as up
from jarvis.domain.prefab_catalog import MAX_CHANGES, VERIFIED_UPSTREAM_KEYS
from jarvis.domain.remotion_compile import SCENE_ALLOWED_IMPORTS
from jarvis.protocol.remotion_import_routes import MAX_BODY_BYTES, PREFIX
from jarvis.adapters import https_upstream_fetcher as fetcher

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "docs" / "remotion-import.md").read_text(encoding="utf-8")
SECURITY = (ROOT / "docs" / "SECURITY.md").read_text(encoding="utf-8")
PREFABS = (ROOT / "docs" / "prefabs.md").read_text(encoding="utf-8")


def all_codes() -> dict[str, int]:
    names = {value for source in (up.UpstreamErrorCode, ri.ImportErrorCode) for key, value in vars(source).items()
             if not key.startswith("_") and isinstance(value, str)}
    names |= {"presentation_not_found", "import_busy", "import_storage_failed"}
    return {code: status_of(code) for code in names}


def test_every_failure_code_and_its_http_status_is_documented():
    codes = all_codes()
    assert len(codes) >= 35
    for code, status in codes.items():
        assert f"| `{code}` | {status} |" in DOC, code
    documented = set(re.findall(r"^\| `([a-z_]+)` \| \d{3} \|", DOC, re.M))
    assert documented == set(codes), documented ^ set(codes)


def test_the_documented_bounds_are_the_code_bounds():
    assert f"Archive ≤ {up.MAX_DOWNLOAD_BYTES // (1024 * 1024)} Mio" in DOC
    assert f"délai global {int(fetcher.DEFAULT_DEADLINE_S)} s" in DOC and f"min({int(fetcher.SOCKET_TIMEOUT_S)} s, temps restant)" in DOC
    assert f"échéance** de {int(up.READ_DEADLINE_S)} s" in DOC and f"(20 s)" in DOC and ri.ANALYSIS_BUDGET_S == up.READ_DEADLINE_S
    assert f"Au plus {up.MAX_REDIRECTS}" in DOC
    assert f"{up.MAX_ENTRIES} membres au plus" in DOC and f"{up.MAX_UNPACKED_BYTES // (1024 * 1024)} Mio décompressés" in DOC
    assert f"{up.MAX_READ_BYTES // (1024 * 1024)} Mio de fichiers lus" in DOC
    assert f"≤ {MAX_CHANGES} lignes" in DOC and MAX_CHANGES == ri.MAX_CHANGES == 16


def test_the_documented_origin_licence_and_dependency_policy_is_the_code_policy():
    assert up.ARCHIVE_HOST in DOC and up.REPOSITORY_HOST in DOC and "remotion-dev" in DOC and up.DEFAULT_ALLOWED_OWNERS == ("remotion-dev",)
    for spdx in up.PERMITTED_LICENCES:
        assert f"`{spdx}`" in DOC, spdx
    for module in SCENE_ALLOWED_IMPORTS:
        assert f"`{module}`" in DOC, module
    assert up.REMOTION_RUNTIME_LICENCE in DOC and "remotion_import.allowed_owners" in DOC and "control-center-settings.json" in DOC
    for key in VERIFIED_UPSTREAM_KEYS:
        assert f"`{key}`" in DOC and f"`{key}`" in PREFABS, key
    assert ri.ENTRY_NAME in DOC and ri.FALLBACK_ENTRY_NAME in DOC and ri.LICENCE_MODULE in DOC


def test_the_routes_and_the_journal_kinds_are_the_code_ones():
    assert f"`{PREFIX}/plan`" in DOC and f"`{PREFIX}`" in DOC and MAX_BODY_BYTES == 8 * 1024
    for kind in ("planned", "imported", "refused", "route_failed"):
        assert f"core.remotion_import.{kind}" in DOC, kind
    service = (ROOT / "jarvis" / "core" / "remotion_import_service.py").read_text(encoding="utf-8")
    for kind in ("planned", "imported", "refused", "route_failed"):
        assert f"core.remotion_import.{kind}" in service, kind


def test_no_control_center_relay_agent_tool_or_brain_module_references_the_importer():
    for path in (ROOT / "jarvis").rglob("*"):
        if path.suffix not in (".py", ".js", ".mjs") or path.name.startswith("remotion_import") or "remotion_upstream" in path.name:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "/v1/remotion/imports" in text or "remotion_import" in text:
            assert path.name in ("v2_app.py", "app.py", "server.py", "https_upstream_fetcher.py", "upstream_fetcher.py",
                                 "fake_upstream_fetcher.py"), f"unexpected reference to the importer in {path.relative_to(ROOT)}"


def test_the_files_the_doc_cites_exist_and_the_security_section_links_back():
    for relative in ("jarvis/domain/remotion_upstream.py", "jarvis/domain/remotion_import.py", "jarvis/core/remotion_import_service.py",
                     "jarvis/protocol/remotion_import_routes.py", "jarvis/adapters/https_upstream_fetcher.py",
                     "jarvis/adapters/fake_upstream_fetcher.py", "jarvis/ports/upstream_fetcher.py",
                     "tests/unit/test_remotion_upstream.py", "tests/unit/test_remotion_import.py",
                     "tests/unit/test_remotion_import_service.py", "tests/unit/test_remotion_import_real.py",
                     "tests/unit/test_prefab_catalog.py", "scripts/remotion_player_harness.py", "docs/remotion-source.md",
                     "docs/remotion-isolation.md", "docs/prefabs.md"):
        assert (ROOT / relative).is_file(), relative
    for link in re.findall(r"\]\(((?!http)[a-z0-9-]+\.md)(?:#[^)]*)?\)", DOC):
        assert (ROOT / "docs" / link).is_file(), link
    assert "### 20. Upstream Remotion template import" in SECURITY and "remotion-import.md" in SECURITY
    assert "remotion-import.md" in PREFABS


def test_the_library_card_never_calls_a_modified_import_verified():
    js = (ROOT / "jarvis" / "runtime" / "control_center_prefabs.js").read_text(encoding="utf-8")
    assert "verified_intact===true" in js and "modifié depuis l’import" in js and "modified_files" in js
    assert "verified_intact" in DOC and "modified_files" in DOC and "modifié depuis l'import" in DOC
    assert "protège le propriétaire, pas le commit" in DOC and "protects the owner, not the commit" in SECURITY
    assert (ROOT / "tasks" / "jarvis-remotion-presentation-integration" / "Issues" / "04-upstream-commit-reachability.md").is_file()

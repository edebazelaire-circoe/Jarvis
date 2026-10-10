"""`docs/remotion-source.md` contre le code (Slice 05) : chaque borne, code d'échec, chemin et lien cité existe et dit vrai."""

from __future__ import annotations

from pathlib import Path

from jarvis.domain import remotion_compile as rc
from jarvis.domain import remotion_source as rs
from jarvis.domain.prefab import MANIFEST_VERSIONS, RETENTION_NAMESPACE

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "docs" / "remotion-source.md").read_text(encoding="utf-8")


def mib(value: int) -> str:
    return f"{value // (1024 * 1024)} Mio"


def kib(value: int) -> str:
    return f"{value // 1024} Kio"


def test_every_failure_code_and_its_http_status_is_documented():
    for code, status in rc.COMPILE_HTTP_STATUS.items():
        assert f"| `{code.value}` | {status} |" in DOC, code


def test_the_documented_bounds_are_the_code_bounds():
    assert f"{rs.MAX_MODULES} modules ({kib(rs.MAX_MODULE_BYTES)} chacun, {mib(rs.MAX_MODULES_TOTAL_BYTES)} au total)" in DOC
    assert f"{rs.MAX_ASSETS} assets ({mib(rs.MAX_ASSET_BYTES)} chacun, {mib(rs.MAX_ASSETS_TOTAL_BYTES)} au total)" in DOC
    assert f"≤ {rs.MAX_PATH_CHARS} caractères" in DOC and f"profondeur ≤ {rs.MAX_DEPTH}" in DOC
    assert f"scène {int(rc.SCENE_TIMEOUT_S)} s" in DOC and f"host {int(rc.HOST_TIMEOUT_S)} s" in DOC
    assert f"`scene.js` ≤ {mib(rc.MAX_SCENE_BUNDLE_BYTES)}, `host.js` ≤ {mib(rc.MAX_HOST_BUNDLE_BYTES)}" in DOC
    assert f"`CACHE_KEEP_ENTRIES` = {rc.CACHE_KEEP_ENTRIES}" in DOC and "`CACHE_MAX_BYTES` = 1 Gio" in DOC
    assert rc.CACHE_MAX_BYTES == 1024 ** 3


def test_the_documented_layout_and_imports_are_the_code_ones():
    for extension in rs.MODULE_EXTENSIONS | rs.ASSET_EXTENSIONS:
        assert extension.lstrip(".") in DOC, extension
    for module in rc.SCENE_ALLOWED_IMPORTS:
        assert f"`{module}`" in DOC, module
    for module in rc.HOST_EXPOSED_MODULES:
        assert module in DOC, module
    assert rs.DEFAULT_ENTRY in DOC and rs.MODULE_ROOT in DOC and rs.ASSET_ROOT in DOC
    assert "SOURCE_GUARDS" in DOC and "SCENE_ALLOWED_IMPORTS" in DOC and "window.remotion_staticBase" in DOC
    assert rc.HOST_GLOBAL in DOC and rc.SCENE_GLOBAL in DOC


def test_the_manifest_version_rule_is_stated_as_coded():
    assert MANIFEST_VERSIONS == (1, 2, 3) and "`MANIFEST_VERSIONS = (1, 2, 3)`" in DOC
    assert rs.MANIFEST_SCHEMA_VERSION == 2 and "schema_version 2" in DOC
    assert "presentation-studio.p<12 hex>.s<12 hex>" in DOC and RETENTION_NAMESPACE == "presentation-studio."


def test_the_files_the_doc_cites_exist():
    for relative in ("jarvis/domain/remotion_source.py", "jarvis/domain/remotion_compile.py", "jarvis/adapters/remotion_compiler.py",
                     "jarvis/capabilities/remotion/runtime-host.mjs", "scripts/remotion_compile_harness.py",
                     "tests/unit/test_remotion_source.py", "tests/unit/test_remotion_source_store.py",
                     "tests/unit/test_remotion_compiler.py", "tests/unit/test_remotion_compiler_real.py",
                     "jarvis/core/presentation_studio_pins.py", "jarvis/core/prefab_retention.py",
                     "jarvis/core/presentation_studio_reload.py", "jarvis/domain/presentation_studio_reload.py"):
        assert (ROOT / relative).is_file(), relative
        assert relative in DOC or Path(relative).name in DOC or relative.split("/")[-1].removesuffix(".py") in DOC, relative


def test_the_neighbouring_docs_link_to_it():
    for name in ("prefabs.md", "local-data.md", "presentation-studio.md", "remotion-runtime.md", "presentation-engine.md"):
        assert "remotion-source.md" in (ROOT / "docs" / name).read_text(encoding="utf-8"), name

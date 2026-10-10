"""Parite code/documentation de la promotion de modeles (jarvis-interactive-presentation-studio, Slice 20).

Chaque code, constat, borne, diagnostic et route du code est dans la section « Template and prefab promotion contract » ; rien d'autre
n'y est promis. Le test de structure dit aussi qu'aucun second catalogue de prefabs n'existe.
"""

from __future__ import annotations

from pathlib import Path
import re

from jarvis.adapters import file_presentation_template_store as store_module
from jarvis.core import presentation_studio_template as core_module
from jarvis.domain import presentation_studio_template as domain_module
from jarvis.domain import presentation_studio_template_sanitize as sanitize_module
from jarvis.domain.presentation_studio_checks import HTTP_STATUS, PresentationStudioErrorCode as C

ROOT = Path(__file__).resolve().parents[2]
PAGE = (ROOT / "docs" / "presentation-studio.md").read_text(encoding="utf-8")
START = PAGE.index("## Template and prefab promotion contract")
SECTION = PAGE[START:PAGE.index("\n## ", START + 10)]
NAMES = (ROOT / "tasks" / "jarvis-interactive-presentation-studio" / "docs" / "09-canonical-names.md").read_text(encoding="utf-8")
PREFABS = (ROOT / "docs" / "prefabs.md").read_text(encoding="utf-8")


def source(*parts: str) -> str:
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


def test_the_three_new_codes_and_their_statuses_are_documented_where_the_other_codes_are():
    for code, status in ((C.UNKNOWN_TEMPLATE, 404), (C.TEMPLATE_LEAK, 409), (C.TEMPLATE_SELECTION_REQUIRED, 400)):
        assert HTTP_STATUS[code] == status
        assert f"`{code.value}`" in PAGE[:PAGE.index("## Scene and control contract")], code
        assert f"`{code.value}`" in SECTION and f"`{code.value}`" in NAMES, code


def test_every_finding_code_the_code_can_emit_is_in_the_findings_table_and_no_other():
    emitted = set(re.findall(r'Finding\("([a-z_]+)"', source("jarvis", "domain", "presentation_studio_template_sanitize.py")
                             + source("jarvis", "core", "presentation_studio_template.py")
                             + source("jarvis", "core", "presentation_studio_template_embed.py")
                             + source("jarvis", "core", "presentation_studio_template_guard.py")
                             + source("jarvis", "domain", "presentation_studio_template_remotion.py")))
    table = SECTION[SECTION.index("### Detection and validation"):SECTION.index("### Provenance")]
    documented = set(re.findall(r"^\| `([a-z_]+)`(?:, `([a-z_]+)`)? \|", table, re.MULTILINE))
    documented = {code for pair in documented for code in pair if code}
    assert emitted and emitted == documented, (emitted ^ documented)


def test_every_diagnostic_kind_the_service_emits_is_documented():
    emitted = set(re.findall(r'self\._trace\(\s*"([a-z_]+)"', source("jarvis", "core", "presentation_studio_template.py")))
    assert emitted == {"template_planned", "template_promoted", "template_refused", "template_orphans", "template_instantiated",
                       "template_instantiation_failed"}
    for kind in emitted:
        assert kind in SECTION, kind
        assert kind in NAMES or kind == "template_instantiation_failed", kind   # the last one is Remotion Slice 19 (the other handoff's table is closed)


def test_the_bounds_in_the_code_are_the_bounds_in_the_page():
    assert f"{domain_module.MAX_TEMPLATES} templates" in SECTION and f"{domain_module.MAX_TEMPLATE_BYTES // 1024} KiB per document" in SECTION
    assert f"{domain_module.MAX_TAGS})" in SECTION or f"at most {domain_module.MAX_TAGS}" in SECTION
    assert f"{domain_module.MAX_DESCRIPTION}" in SECTION and f"{sanitize_module.DATA_URI_WARN_CHARS // 1024} KiB" in SECTION
    assert f"{sanitize_module.MIN_WORD_TERM_CHARS} characters" in SECTION
    assert "128 KiB" in SECTION and "128 * 1024" in source("jarvis", "protocol", "presentation_studio_template_routes.py")
    assert domain_module.NAMESPACE == "studio-template." and "`studio-template.<slug>[-<n>]`" in SECTION
    assert store_module.TEMPLATES_DIR == "presentation_templates" and "presentation_templates/" in SECTION


def test_every_route_and_service_call_is_in_the_page_and_the_names_table():
    for call in ("plan", "promote", "list_templates", "get_template", "instantiate"):
        assert hasattr(core_module.PresentationStudioTemplates, call) and call in SECTION and call in NAMES, call
    for path in ("/templates/plan", "/templates`", "/templates[?kind=]", "/templates/{template_id}", "/templates/{template_id}/instantiate"):
        assert path in SECTION, path
    assert "/v1/presentation-studio/templates" in NAMES


def test_the_page_states_the_acceptance_the_scope_and_the_limits():
    for needle in ("without carrying accidental project-specific state", "No second catalog", "not a proof", "No broken", "has no deletion",
                   "Not promoted", "Not run in a real browser", "dimensions", "parameters"):
        assert needle.lower() in SECTION.lower() or needle.replace("No broken", "no broken").lower() in SECTION.lower(), needle
    assert "Template / promotion" in PAGE and "**implemented (Level 3)**" in PAGE[PAGE.index("| Template / promotion"):][:900]
    assert "Presentation Studio template promotion (Slice 20)" in PREFABS and "`PrefabService.save" in PREFABS


def test_there_is_no_second_prefab_catalog_in_the_modules():
    """The store holds compositions only; the one place a prefab is written is `PrefabService.save`."""

    for path in ("jarvis/adapters/file_presentation_template_store.py", "jarvis/core/presentation_studio_template.py",
                 "jarvis/domain/presentation_studio_template.py", "jarvis/domain/presentation_studio_template_sanitize.py"):
        text = source(*path.split("/")).split('"""', 2)[2]  # the code, not the module docstring
        assert "FilePrefabLibrary" not in text and "publication.json" not in text and ".publish(" not in text, path
    assert source("jarvis", "core", "presentation_studio_template.py").count("self._prefabs.save(") == 1
    # Remotion Slice 19: the second (and last) door is the instantiation of an embedded source, as a presentation-scoped prefab.
    assert source("jarvis", "core", "presentation_studio_template_embed.py").count("self._prefabs.save(") == 1
    for path in ("jarvis/core/presentation_studio_template_embed.py", "jarvis/domain/presentation_studio_template_remotion.py",
                 "jarvis/domain/presentation_studio_template_score.py", "jarvis/core/presentation_studio_template_guard.py"):
        text = source(*path.split("/")).split('"""', 2)[2]
        assert "FilePrefabLibrary" not in text and "publication.json" not in text and ".publish(" not in text, path
    assert "PrefabService.save" in domain_module.__doc__ and "second" in domain_module.__doc__.lower()


def test_the_modules_stay_small_and_cite_their_contract():
    for path in ("jarvis/adapters/file_presentation_template_store.py", "jarvis/core/presentation_studio_template.py",
                 "jarvis/domain/presentation_studio_template.py", "jarvis/domain/presentation_studio_template_sanitize.py",
                 "jarvis/protocol/presentation_studio_template_routes.py", "jarvis/runtime/presentation_studio_template_relay.py"):
        text = source(*path.split("/"))
        assert text.count("\n") < 700, path
        assert "Slice 20" in text.split('"""')[1], path


def test_the_remotion_slice_19_modules_stay_small_cite_their_contract_and_the_page_names_them():
    for path in ("jarvis/core/presentation_studio_template_embed.py", "jarvis/domain/presentation_studio_template_remotion.py",
                 "jarvis/domain/presentation_studio_template_score.py", "jarvis/core/presentation_studio_template_guard.py"):
        text = source(*path.split("/"))
        assert text.count("\n") < 400, path
        assert "Slice 19" in text.split('"""')[1], path
        assert Path(path).name.removesuffix(".py") in PAGE, path


def test_the_page_states_the_one_artefact_decision_the_score_skeleton_and_the_licence_rule():
    for needle in ("One artefact per presentation", "publishes no prefab to the library", "Score skeleton", "[intention]",
                   "licence_ack", "verified_import", "never survives a modification", "TSX is searched, never rewritten",
                   "keep_assets", "embedded_too_large", "Remotion-aware promotion", "lowest version that expresses it",
                   "template_user_only", "declared_not_reverified", "NFKC", "[instantiation échouée]", "content hash"):
        assert needle.lower() in SECTION.lower(), needle
    assert not hasattr(domain_module, "MAX_EMBEDDED_BYTES"), "no constant that the store does not enforce"
    from jarvis.domain.presentation_studio import MAX_DOCUMENT_BYTES
    assert domain_module.MAX_TEMPLATE_BYTES == MAX_DOCUMENT_BYTES and "256 KiB per document" in SECTION and "serialized" in SECTION
    assert domain_module.TEMPLATE_SCHEMA_VERSION == 2 and "v1 and v2" in SECTION


def test_every_request_key_the_code_accepts_is_documented():
    from jarvis.domain.presentation_studio_template import parse_promote

    text = source("jarvis", "domain", "presentation_studio_template.py")
    keys = re.search(r'frozenset\(\{"actor", "description", "tags", "scenes", "art_direction", "expected_revision", "licence_ack",\s+"keep_assets"\}\)', text)
    assert keys is not None
    for key in ("actor", "description", "tags", "scenes", "art_direction", "expected_revision", "licence_ack", "keep_assets"):
        assert key in SECTION, key
    assert parse_promote({"kind": "scene", "title": "x", "slug": "x", "licence_ack": ["GPL-3.0"], "keep_assets": True}, strict=False).licence_ack == ("GPL-3.0",)

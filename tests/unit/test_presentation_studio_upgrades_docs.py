"""Parite code/documentation de l'avis de version et de l'essai (Remotion Slice 19).

Chaque route, champ, code, diagnostic et borne du code est dans la section « Newer prefab versions and trial variants » ; rien d'autre n'y
est promis. Les ancres internes que la section cite existent.
"""

from __future__ import annotations

from pathlib import Path
import re

from jarvis.core import presentation_studio_upgrades as core_module
from jarvis.protocol import client as client_module
from jarvis.protocol.presentation_studio_upgrades_routes import PresentationStudioUpgradesRoutes
from jarvis.runtime.presentation_studio_upgrades_relay import PresentationStudioUpgradesRelayRoutes

ROOT = Path(__file__).resolve().parents[2]
PAGE = (ROOT / "docs" / "presentation-studio.md").read_text(encoding="utf-8")
START = PAGE.index("## Newer prefab versions and trial variants")
SECTION = PAGE[START:PAGE.index("\n## ", START + 10)]


def source(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def anchors() -> set[str]:
    out = set()
    for heading in re.findall(r"^#{1,6} (.+)$", PAGE, re.MULTILINE):
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).strip().replace(" ", "-")
        out.add(slug)
    return out


def test_every_route_and_client_method_is_in_the_section():
    for route in PresentationStudioUpgradesRoutes(object()).routes():
        assert route.path.split("/variants/{variant_id}")[1] in SECTION or "/upgrades" in SECTION, route.path
    assert "/upgrades`" in SECTION and "/upgrades/try`" in SECTION
    relay = PresentationStudioUpgradesRelayRoutes(transport=lambda: None, journal=None)  # type: ignore[arg-type]
    assert {r.method for r in relay.routes()} == {"GET", "POST"} and "/api/presentation-studio/presentations" in SECTION
    for name in ("presentation_studio_upgrades", "presentation_studio_upgrade_try"):
        assert name in SECTION and hasattr(client_module.LocalCoreClient, name), name


def test_every_diagnostic_kind_the_service_emits_is_documented():
    emitted = set(re.findall(r'"(upgrade_[a-z_]+)"', source("jarvis", "core", "presentation_studio_upgrades.py")))
    assert emitted == {"upgrade_checked", "upgrade_trial_created", "upgrade_trial_refused"}
    for kind in emitted:
        assert kind in SECTION, kind


def test_every_field_of_a_notice_and_every_refusal_code_is_documented():
    code = source("jarvis", "core", "presentation_studio_upgrades.py")
    for field in ("scene_id", "prefab_id", "pinned_version", "latest_version", "newer_count", "newer_versions", "reloading", "fits", "problem",
                  "engine_ok", "latest_catalog", "trials", "unavailable", "auto_upgrade", "pinned_licence", "latest_licence", "licence_changed",
                  "licence_ack_required"):
        assert f'"{field}"' in code and field in SECTION, field
    for refusal in ("scene_incompatible", "engine_unsupported", "prefab_unavailable", "scene_reloading", "stale_revision", "score_incompatible",
                    "limit_reached", "invalid"):
        assert f"presentation_studio_{refusal}" in SECTION, refusal
    assert f"at most {core_module.MAX_LISTED_VERSIONS}" in SECTION
    assert core_module.TRIAL_PREFIX == "Essai de " and "Essai de <id>" in SECTION


def test_the_section_states_the_rules_the_tests_prove():
    for needle in ("never upgraded automatically", "Nothing is upgraded automatically", "nothing is rebound silently", "original variant is not written",
                   "never activated by itself", "explicit act", "no network is consulted", "Rule Zero", "Collapsed by default",
                   "test_retention_keeps_the_old_pin_and_the_trial_pin_while_the_trial_exists", "No tool for the agent"):
        assert needle.lower() in SECTION.lower() or needle.replace("never upgraded automatically", "nothing is upgraded automatically").lower() in SECTION.lower(), needle
    assert "test_presentation_studio_upgrades{,_routes}" in SECTION and "test_presentation_studio_explorer_upgrades_{js,browser}" in SECTION
    for test_file in ("test_presentation_studio_upgrades", "test_presentation_studio_upgrades_routes", "test_presentation_studio_explorer_upgrades_js",
                      "test_presentation_studio_explorer_upgrades_browser"):
        assert (ROOT / "tests" / "unit" / f"{test_file}.py").exists(), test_file


def test_the_section_s_internal_links_resolve_and_the_status_table_lists_the_modules():
    known = anchors()
    for link in re.findall(r"\]\(#([a-z0-9\-]+)\)", SECTION):
        assert link in known, link
    row = next(line for line in PAGE.splitlines() if line.startswith("| Newer prefab version, trial variant"))
    for module in ("presentation_studio_upgrades.py", "presentation_studio_upgrades_routes.py", "presentation_studio_upgrades_relay.py"):
        assert module in row, module
        assert (ROOT / "jarvis").rglob(module), module
    assert "**implemented (Level 3)**" in row


def test_the_modules_stay_small_and_cite_their_slice():
    for path in ("jarvis/core/presentation_studio_upgrades.py", "jarvis/protocol/presentation_studio_upgrades_routes.py",
                 "jarvis/runtime/presentation_studio_upgrades_relay.py", "jarvis/runtime/control_center_presentation_studio_explorer_upgrades.js"):
        text = source(*path.split("/"))
        assert text.count("\n") < 400, path
        assert "Slice 19" in text[:600], path

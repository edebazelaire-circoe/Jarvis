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


def score_section() -> str:
    return _section("## Score and cue contract (Level 3)")


def art_direction_section() -> str:
    return _section("## Art direction contract (Level 3)")


def edit_section() -> str:
    return _section("## Semantic edit contract (Level 3)")


def reload_section() -> str:
    return _section("## Hot reload contract (Level 3, Slice 06)")


def history_section() -> str:
    return _section("## Persistence and undo contract (Level 3)")


def playback_section() -> str:
    return _section("## Playback runtime contract (Level 3, Slice 12)")


def contract_section() -> str:
    """The Presentation contract plus the scene contract that extends it (routes and codes are tabled in either)."""

    return (_section("## Presentation contract (Level 3)") + "\n" + scene_section() + "\n" + edit_section() + "\n"
            + score_section() + "\n" + history_section() + "\n" + playback_section() + "\n" + art_direction_section()
            + "\n" + reload_section())


MODULES = ("jarvis/domain/presentation_studio.py", "jarvis/ports/presentation_studio.py",
           "jarvis/adapters/file_presentation_studio_store.py", "jarvis/core/presentation_studio_service.py",
           "jarvis/protocol/presentation_studio_routes.py", "jarvis/domain/presentation_studio_scene.py",
           "jarvis/domain/presentation_studio_checks.py", "jarvis/core/presentation_studio_scene_catalog.py",
           "jarvis/domain/presentation_studio_score.py", "jarvis/domain/presentation_studio_art_direction.py",
           "jarvis/domain/presentation_studio_art_direction_authoring.py")


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
    assert "`presentations/<presentation_id>/{presentation.json, variants/<variant_id>.json, archive/<variant_id>.json}`" in local
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
    assert ps.CURRENT_VERSIONS == {ps.SCHEMA_PRESENTATION: 2, ps.SCHEMA_VARIANT: 3, ps.SCHEMA_SCORE: 1,
                                   ps.SCHEMA_ART_DIRECTION: 1} and {1, 2} <= set(ps.UPGRADES[ps.SCHEMA_VARIANT])
    section = scene_section()
    assert "`schema_version` **3**" in section and "the Presentation manifest is 2 since Slice 16" in section


def test_the_prefab_page_lists_the_studio_as_a_consumer_and_the_levels_table_is_updated():
    consumers = page("prefabs.md")
    consumers = consumers[consumers.index("## Consumers (Presentation seam)"):]
    assert "Presentation Studio as a consumer" in consumers and "PrefabCatalog" in consumers
    assert "presentation-studio.md#scene-and-control-contract-level-3" in consumers
    studio = page("presentation-studio.md")
    assert "| Studio scene + control |" in studio and studio.count("**implemented (Level 3)**") >= 2
    assert "scene-and-control-contract-level-3" in studio


def test_the_score_contract_names_every_enum_value_limit_and_rule_the_code_enforces():
    from jarvis.domain import presentation_studio_score as sc

    section = score_section()
    for enum in (sc.Track, sc.Presenter, sc.ItemKind, sc.TimingPolicy, sc.Interruption, sc.Recovery,
                 sc.SequenceInterrupt, sc.ActionKind):
        for member in enum:
            assert f"`{member.value}`" in section, (enum.__name__, member.value)
    for needle in (f"<= {sc.MAX_ITEMS}", f"<= {sc.MAX_CUES}", f"<= {sc.MAX_SEQUENCES}", f"<= {sc.MAX_RECOVERY_POINTS}",
                   f"1..{sc.MAX_STEPS}", f"<= {sc.MAX_TEXT_CHARS}", f"<= {sc.MAX_NOTE_CHARS}", f"up to {sc.MAX_PHRASES}",
                   f"up to {sc.MAX_SEMANTICS}", f"{sc.MIN_PHRASE_CHARS}..{sc.MAX_PHRASE_CHARS} characters",
                   f"at most {sc.MAX_PHRASE_WORDS} words", f"1..{sc.MAX_LOOP_REPEATS}",
                   f"`MAX_EXPANDED_ITEMS` = {sc.MAX_EXPANDED_ITEMS}", f"1..{sc.MAX_DURATION_MS:,}".replace(",", " "),
                   f"text <= {sc.MAX_VALUE_CHARS}"):
        assert needle in section, needle
    for phrase in ("Cycles are refused", "declared loop", "soft target", "never a pattern", "**exactly one** of",
                   "FREE_TEXT_FIELDS", "score first, then the variant", "check_score_values", "strictly increases",
                   "timeline()", "scores/<score_id>.json", "jarvis.presentation_studio.score"):
        assert phrase in section, phrase


def test_the_score_contract_symbols_exist_in_the_code():
    from jarvis.core.presentation_studio_service import PresentationStudioService
    from jarvis.domain import presentation_studio_score as sc
    from jarvis.protocol.client import LocalCoreClient

    for name in ("check_score", "check_score_values", "parse_score", "normalise_phrase", "new_score"):
        assert callable(getattr(sc, name)), name
    for method in ("create_score", "get_score", "save_score"):
        assert callable(getattr(PresentationStudioService, method)), method
    for method in ("presentation_studio_score", "presentation_studio_create_score", "presentation_studio_save_score"):
        assert callable(getattr(LocalCoreClient, method)), method
    for symbol in ("Score.track", "Score.resolve_cue", "Score.playback_order", "Score.canonical"):
        cls, name = symbol.split(".")
        assert callable(getattr(getattr(sc, cls), name)), symbol


def test_the_levels_table_and_the_status_row_say_the_score_is_implemented():
    studio = page("presentation-studio.md")
    row = next(line for line in studio.splitlines() if line.startswith("| Score, cues, timing |"))
    assert "**implemented (Level 3)**" in row and "planned" not in row and "Slice 10" in row
    assert "Score and cue contract" in studio.split("## Canonical concepts", 1)[0]
    assert "Score, cues, timing, locked sequences, recovery points (model, validators, store, routes) | 0-1 | 3 (**done**, Slice 10)" in studio
    assert "scores/<score_id>.json" in page("local-data.md")
    assert "score content behind `score_id` | **done, Slice 10**" in studio


def test_the_score_adds_no_conversation_event_and_no_sqlite_schema():
    events = page("conversation-events.md")
    assert "score.cue_satisfied" not in events and "presentation_studio.score" not in events
    source = (ROOT / "jarvis/domain/presentation_studio_score.py").read_text(encoding="utf-8")
    assert "sqlite" not in source and "import os" not in source and "open(" not in source  # pure: no I/O, no database


def test_the_score_contract_states_the_rework_rules():
    from jarvis.domain import presentation_studio_score as sc

    section = score_section()
    for phrase in ("phrase_index(score)", "ambiguous_phrases(score, armed_cue_ids)", "armed** set", "Latin-script letters",
                   "U+02BC", "non-ASCII digit", "untrusted data", "`_persist_variant`", "relinked_from",
                   "score_relinked", "overlap partially", "Slices 05, 08, 19", "Slice 12",
                   "item's own `scene_goto`"):
        assert phrase in section, phrase
    for name in ("phrase_index", "semantic_index", "ambiguous_phrases", "STRUCTURE_FIELDS"):
        assert hasattr(sc, name), name
    names = page("../tasks/jarvis-interactive-presentation-studio/docs/09-canonical-names.md")
    assert "`item_id` (was `score_item_id`" in names and "CueDefinition" in names


# ------------------------------------------------------------------ Slice 09 : direction artistique


def art_section() -> str:
    return art_direction_section()


def policy_section() -> str:
    return _section("## Art direction authoring policy (for Slice 11)")


def test_the_art_direction_contract_names_every_vocabulary_member_limit_and_threshold_the_code_enforces():
    from jarvis.domain import presentation_studio_art_direction as ad
    from jarvis.domain import presentation_studio_art_direction_authoring as au

    section = art_section()
    for enum in (ad.Origin, ad.Section, ad.GradientKind, ad.TextToken, ad.FontStack, ad.TextSize, ad.ScaleRatio, ad.LabelCase,
                 ad.Density, ad.Margin, ad.Elevation, ad.PhotoStyle, ad.IllustrationStyle, ad.IconStyle, ad.ImageTreatment,
                 ad.SeriesMode, ad.GridStyle, ad.LabelPlacement, ad.Emphasis, ad.Tempo, ad.Easing, ad.TransitionStyle,
                 ad.ReducedMotion, au.Archetype):
        for member in enum:
            assert f"`{member.value}`" in section, (enum.__name__, member.value)
    for family in (ad.DURATIONS_MS, ad.STAGGERS_MS, ad.HEADING_WEIGHTS, ad.BODY_WEIGHTS):
        assert ", ".join(map(str, family)) in section, family
    for needle in (f"(<= {ad.MAX_REFERENCES})", f"(<= {ad.MAX_NOTES}, each <= {ad.MAX_NOTE_CHARS})",
                   f"(<= {ad.MAX_GRADIENTS})", f"({ad.MIN_STOPS}..{ad.MAX_STOPS}", f"{ad.MIN_SERIES}..{ad.MAX_SERIES} distinct",
                   f"{ad.MIN_SURFACE_OPACITY}..{ad.MAX_SURFACE_OPACITY}", f"0..{ad.MAX_RADIUS_PX}", f"0..{ad.MAX_STROKE_PX}",
                   f"(<= {ad.MAX_MOTIFS} plain words, each <= {ad.MAX_MOTIF_CHARS})", f"<= {ad.MAX_FAMILY_CHARS}",
                   f"{ad.TEXT_RATIO} : 1".replace(".0", ""), f"{ad.SECONDARY_RATIO:g} : 1", f"`MIN_DIVERGENCE` = {au.MIN_DIVERGENCE}",
                   f"`n` in 1..{au.MAX_DIVERGE}", "at most 0.85"):
        assert needle in section, needle
    for axis, weight in au.AXES.items():
        assert f"{axis} {weight:.2f}" in section, axis
    for phrase in ("`FREE_TEXT_FIELDS`", "`ID_FIELDS`", "`TOKEN_FIELDS`", "`STRUCTURE_FIELDS`", "`relink_art_direction`", "`_persist_variant`",
                   "`relinked_from`", "art_direction_relinked", "untrusted data", "tightens Slice 02", "Candidates are not stored",
                   "DA first, then the variant", "`is_fallback`", "WCAG 2.x", "effective_surface()", "contrast_report()",
                   "jarvis.presentation_studio.art_direction", "art_directions/<art_direction_id>.json", "locators only"):
        assert phrase in section, phrase


def test_the_art_direction_symbols_exist_in_the_code_and_the_theme_variables_are_the_documented_ones():
    from jarvis.core.presentation_studio_service import PresentationStudioService
    from jarvis.domain import presentation_studio_art_direction as ad
    from jarvis.domain import presentation_studio_art_direction_authoring as au
    from jarvis.protocol.client import LocalCoreClient

    for name in ("parse_profile", "parse_art_direction", "contrast_ratio", "require_art_direction", "gradient_css", "easing_css",
                 "parse_length", "parse_art_direction_create", "parse_art_direction_update", "new_art_direction_document"):
        assert callable(getattr(ad, name)), name
    for name in ("generate_fallback_profile", "diverge", "profile_distance", "derive_from_signals", "parse_design_signals",
                 "parse_seed_context", "classify_family"):
        assert callable(getattr(au, name)), name
    for method in ("create_art_direction", "get_art_direction", "save_art_direction", "create_fallback_art_direction",
                   "art_direction_candidates", "require_art_direction"):
        assert callable(getattr(PresentationStudioService, method)), method
    for method in ("presentation_studio_art_direction", "presentation_studio_create_art_direction", "presentation_studio_save_art_direction",
                   "presentation_studio_fallback_art_direction", "presentation_studio_art_direction_candidates"):
        assert callable(getattr(LocalCoreClient, method)), method
    section = art_section()
    for variable in sorted(ad.ALLOWED_THEME_VARIABLES):
        assert f"`{variable}`" in section, variable
    for key in ad.HOST_THEME_KEYS:
        assert f"`{key}`" in section, key
    for module in ("jarvis/domain/presentation_studio_art_direction.py", "jarvis/domain/presentation_studio_art_direction_authoring.py"):
        assert (ROOT / module).is_file() and module in page("presentation-studio.md"), module
    assert "jarvis/domain/presentation_studio_art_direction.py" in page("ARCHITECTURE.md")


def test_the_authoring_policy_states_the_rules_slice_11_must_follow():
    section = policy_section()
    for phrase in ("provided", "inferred", "generated", "Source priority", "Inspect before asking", "Do not block on a DA question",
                   "Ask only when the answer materially changes the DA", "Never copy external project folders", "locators",
                   "Exploratory mode", "untrusted", "Say where a DA came from", "fallback", "Slices 11 and 21"):
        assert phrase in section, phrase
    order = [section.index(w) for w in ("`provided` first", "`inferred`", "`generated`")]
    assert order == sorted(order)  # the priority is written in that order


def test_the_levels_table_and_the_status_row_say_the_art_direction_is_implemented():
    studio = page("presentation-studio.md")
    row = next(line for line in studio.splitlines() if line.startswith("| Art direction |"))
    assert "**implemented (Level 3)**" in row and "planned" not in row and "Slice 09" in row
    assert "Art direction contract" in studio.split("## Canonical concepts", 1)[0]
    assert "| 0-1 | 3 (**done**, Slice 09; authoring by prompt: Slices 11, 21) |" in studio
    assert "art_directions/<art_direction_id>.json" in page("local-data.md") and "art_directions/" in page("OPERATIONS.md")
    assert "| art direction content behind `art_direction_id` | **done, Slice 09**" in studio


def test_the_prefab_page_lists_the_art_direction_as_a_producer_of_theme_tokens_only():
    consumers = page("prefabs.md")
    consumers = consumers[consumers.index("## Consumers (Presentation seam)"):]
    assert "Presentation Studio art direction (Slice 09)" in consumers and "no new channel and no new variable" in consumers
    assert "presentation-studio.md#art-direction-contract-level-3" in consumers


def test_the_art_direction_adds_no_conversation_event_no_sqlite_schema_and_no_prompt():
    events = page("conversation-events.md")
    assert "art_direction" not in events and "art direction" not in events.lower()
    for module in ("presentation_studio_art_direction.py", "presentation_studio_art_direction_authoring.py"):
        source = (ROOT / "jarvis" / "domain" / module).read_text(encoding="utf-8")
        assert "sqlite" not in source
    assert not list((ROOT / "tests" / "schema").glob("*art*"))
    # no prompt, skill or MCP tool in this Slice: the policy is text for Slice 11
    for path in (ROOT / "jarvis" / "runtime").glob("*.py"):
        if path.name.startswith("presentation_studio"):
            assert "art_direction" not in path.read_text(encoding="utf-8"), path.name


def test_the_art_direction_rework_rules_are_documented():
    section = art_section() + policy_section()
    for phrase in ("`Gradient.samples()`", "GRADIENT_SEGMENT_STEPS", "2.92 : 1", "`--jv-wash`", "4.09:1", "`accent`, `accent_alt` on the effective surface",
                   "only mentions", "`count` 1 to 6", "does not bump the variant `revision`", "compare the art direction's **own** `revision`",
                   "may be multi-line", "`require_art_direction` has callers", "Slice 12 before it plays", "`metadata:v2`", "`;` and `'` in a URL"):
        assert phrase in section, phrase
    assert "2 to 6" not in section

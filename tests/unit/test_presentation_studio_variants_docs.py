"""Le contrat documenté du graphe des variantes est celui du code (jarvis-interactive-presentation-studio, Slice 16).

Bornes, codes d'erreur et leur statut, opérations, routes, évènement (Python et miroir JS), diagnostics, schéma, documents
d'exploitation (`local-data`, `OPERATIONS`, `conversation-events`, `prefabs`), noms canoniques du handoff.
"""

from __future__ import annotations

from pathlib import Path
import re

from jarvis.core import presentation_studio_variants as service_module
from jarvis.core.presentation_studio_variant_events import VARIANT_OPS
from jarvis.core.presentation_studio_variants import PresentationStudioVariants
from jarvis.domain import presentation_studio as ps
from jarvis.domain import presentation_studio_variants as pv
from jarvis.domain.conversation_events import ATTRIBUTE_KEYS, ConversationEventType as T, event_actor, event_visibility
from jarvis.domain.presentation_studio import PresentationStudioErrorCode as C
from jarvis.protocol.client import LocalCoreClient

ROOT = Path(__file__).resolve().parents[2]
NEW_CODES = (C.ACTIVE_VARIANT_PROTECTED, C.CONFIRMATION_REQUIRED, C.CONFIRMATION_STALE, C.NOT_ARCHIVED, C.LINKED_DOCUMENT_UNSUPPORTED)
DIAGNOSTICS = ("variant_created", "variant_switched", "variant_renamed", "variant_archived", "variant_restored", "archive_planned",
               "reconciled", "reconcile_orphans", "reconcile_failed", "branch_failed", "archive_failed", "restore_failed",
               "graph_invalid", "event_failed", "history_drop_failed", "playback_variant_archived", "playback_stop_failed")


def page(name: str) -> str:
    return (ROOT / "docs" / name).read_text(encoding="utf-8")


def contract() -> str:
    text = page("presentation-studio.md")
    start = text.index("## Variant graph and operations contract (Level 3)")
    return text[start:text.index("## Playback roles and speech authority")]


def test_the_page_header_the_owner_map_and_the_level_table_say_the_contract_is_implemented():
    text = page("presentation-studio.md")
    assert "*Variant graph and operations contract* (Slice 16" in text
    row = next(line for line in text.splitlines() if line.startswith("| Presentation Variant |"))
    assert "**implemented (Level 3)**" in row and "variant-graph-and-operations-contract-level-3" in row
    assert "| Variant graph (nodes, numbers, branch, switch, archive / restore under a token" in text
    assert "(Slice 16, done)" in text and "entry condition (met by Slice 16)" in text


def test_the_documented_limits_are_the_enforced_ones():
    text = contract()
    assert pv.MAX_LIVE_VARIANTS == ps.MAX_VARIANTS == 64 and "64 live and 128 archived" in text
    assert pv.MAX_ARCHIVED_VARIANTS == 128 and pv.MAX_RATIONALE == 600 and "<= 600" in text
    assert pv.MAX_SOURCES == 4 and "(<= 4)" in text
    assert pv.CONFIRMATION_TTL_S == 600 and "valid 10 minutes" in text
    assert pv.MAX_VARIANT_COUNTER == 10_000 and "Ceiling: 10 000" in text
    assert ps.SCHEMA_VERSION == 3 and "**schema v2**" in text  # v3 (engine) is documented in presentation-engine.md


def test_every_new_code_is_in_the_error_table_and_the_graph_section_with_its_status():
    text = page("presentation-studio.md")
    section = contract()
    for code in NEW_CODES:
        assert f"`{code.value}` | {ps.HTTP_STATUS[code]} |" in text, code
        assert code.value in section, code
        assert ps.PresentationStudioError(code, "x").status == ps.HTTP_STATUS[code]


def test_every_documented_operation_exists_in_the_service_and_the_typed_client():
    section = contract()
    for method in ("create_branch", "switch", "rename", "plan_archive", "archive", "restore", "graph", "check", "start",
                   "reconcile", "pin_index", "drop_presentation"):
        assert callable(getattr(PresentationStudioVariants, method)), method
    for method in ("graph", "create_branch", "activate", "rename", "archive_plan", "archive", "restore"):
        assert callable(getattr(LocalCoreClient, f"presentation_studio_{method}")), method
    assert "presentation_studio_{graph,create_branch,activate,rename,archive_plan,archive,restore}" in section
    for route in ("/graph", "/variants", "/activate", "/rename", "/archive-plan", "/archive", "/restore"):
        assert route in section, route


def test_the_event_is_registered_on_both_sides_with_the_documented_ops_and_no_content_key():
    section = contract()
    assert T.SYSTEM_PRESENTATION_STUDIO_VARIANT_CHANGED.value == "system.presentation_studio.variant_changed"
    assert event_actor(T.SYSTEM_PRESENTATION_STUDIO_VARIANT_CHANGED).value == "system"
    assert event_visibility(T.SYSTEM_PRESENTATION_STUDIO_VARIANT_CHANGED).value == "diagnostic"
    assert VARIANT_OPS == ("created", "switched", "renamed", "archived", "restored")
    for op in VARIANT_OPS:
        assert f"`{op}`" in section, op
    assert {"variant_number", "count", "variant_id", "presentation_id", "op", "source", "revision", "status"} <= ATTRIBUTE_KEYS
    assert not {"title", "rationale"} & ATTRIBUTE_KEYS  # user content is never an attribute
    script = (ROOT / "jarvis" / "runtime" / "control_center_timeline.js").read_text(encoding="utf-8")
    assert script.count("system.presentation_studio.variant_changed") >= 3  # SPECS, DOT_TYPES, label map
    events = page("conversation-events.md")
    assert events.count("system.presentation_studio.variant_changed") >= 3 and "`variant_number` and `count`" in events


def test_every_diagnostic_named_in_the_docs_is_emitted_by_the_code_and_vice_versa():
    source = (ROOT / "jarvis" / "core" / "presentation_studio_variants.py").read_text(encoding="utf-8")
    section = contract()
    for kind in DIAGNOSTICS:
        assert kind in section, f"{kind} is not documented"
        assert kind in source or (kind.startswith("variant_") and 'f"core.presentation_studio.variant_{op}"' in source), kind
    emitted = set(re.findall(r'"core\.presentation_studio\.([a-z_]+)"', source))
    assert emitted <= set(DIAGNOSTICS), emitted - set(DIAGNOSTICS)
    assert "archive_failed" in source and "restore_failed" in source and 'f"core.presentation_studio.{failure_kind}"' in source


def test_the_operations_documents_name_the_archive_the_tool_the_hand_procedure_and_the_report():
    local = page("local-data.md")
    assert "archive/<variant_id>.json" in local and "zone `archive/`" in local and "schéma\n  v2" in local.replace("\r\n", "\n")
    operations = page("OPERATIONS.md")
    start = operations.index("### Variantes du Studio : archive, restauration et reprise")
    body = operations[start:operations.index("### Agenda : réel ou en mémoire")]
    for needle in ("archive-plan", "/archive`", "/restore`", "Restaurer à la main", "reconcile_orphans", "reconciled",
                   "presentation_studio_confirmation_required", "presentation_studio_confirmation_stale", "variant_counter",
                   "?check=1", "?archived=1"):
        assert needle in body, needle
    prefabs = page("prefabs.md")
    assert "**Slice 16**: a branch copies the scene pins" in prefabs and "pin_index()" in prefabs


def test_the_handoff_canonical_names_page_records_the_slice():
    text = (ROOT / "tasks" / "jarvis-interactive-presentation-studio" / "docs" / "09-canonical-names.md").read_text(encoding="utf-8")
    section = text[text.index("## 15. Slice 16 amendments"):]
    for needle in ("psv_<32 hex>", "psb_<12 hex>", "psp_<12 hex>", "variant_changed", "schema_version **2**", "presentation_studio_variants_routes.py",
                   "pin_index()", "ArtDirectionLink"):
        assert needle in section, needle


def test_the_contract_states_the_entry_conditions_and_the_decisions():
    section = contract()
    for needle in ("Seams and entry conditions for other Slices", "merged with Slice 09", "Slice 06 merge", "Slice 21", "Slice 18",
                   "There is no hard delete", "closed by default", "Confirmation tokens die with the process", "The manifest wins"):
        assert needle.lower() in section.lower(), needle


def test_the_service_module_header_matches_the_documented_order_of_writes():
    header = service_module.__doc__
    for needle in ("allocation", "copiés", "fichier de la variante", "validation", "le manifeste fait foi", "jamais adoptés ni supprimés"):
        assert needle in header, needle


def test_the_rework_limits_the_v1_copy_and_the_merge_conditions_are_written_down():
    section = contract()
    assert pv.MAX_RATIONALE_BYTES == 800 and "<= 800 bytes" in section and "about 254 KB" in section
    assert "presentation.json.v1.bak" in section and "never replaced, never deleted" in section
    assert "the plan itself refuses up front" in section.lower() and "os.link" in section
    start = section.index("### Entry conditions for the Slice 06 merge")
    merge = section[start:section.index("### Decisions and limits")]
    for needle in ("pin_index()", "live + archived", "StudioPinRegistry", "One `variant_pins` function", "VARIANT_SCHEMA_VERSION",
                   "3", "restart, retire old versions, restore"):
        assert needle in merge, needle
    assert "F1, unsupported, single writer" in section and "every caller is told" in section and "2, 2, 2, 3, 3, 3" in section
    assert "presentation.json.v1.bak" in page("local-data.md") and "presentation.json.v1.bak" in page("OPERATIONS.md")
    assert "Un seul Core par racine de données" in page("OPERATIONS.md")


def test_the_merge_with_slices_09_and_12_is_documented_and_the_code_names_exist():
    from jarvis.core.presentation_studio_linked import ArtDirectionLink
    from jarvis.core.presentation_studio_playback import PresentationStudioPlaybackService
    section = contract()
    assert callable(PresentationStudioPlaybackService.running_variant) and callable(PresentationStudioVariants.bind_playback)
    assert ArtDirectionLink.field == "art_direction_id" and ArtDirectionLink.area == "art_directions"
    start = section.index("### Playback and the variant graph (Slice 12 interplay)")
    playing = section[start:section.index("### Entry conditions for the Slice 06 merge")]
    for needle in ("running_variant()", "presentation_studio_variant_in_playback", "bind_playback", "playback_variant_archived",
                   "playback_stop_failed", "even with a token obtained before the run started"):
        assert needle in playing, needle
    assert C.VARIANT_IN_PLAYBACK in ps.PresentationStudioErrorCode and ps.HTTP_STATUS[C.VARIANT_IN_PLAYBACK] == 409
    assert "`presentation_studio_variant_in_playback` | 409 |" in page("presentation-studio.md")
    assert "ArtDirectionLink" in section and "**its own** art direction" in section and "stay where they are" in section
    names = (ROOT / "tasks" / "jarvis-interactive-presentation-studio" / "docs" / "09-canonical-names.md").read_text(encoding="utf-8")
    assert [(int(n), int(k)) for n, k in re.findall(r"^## (\d+)\. Slice (\d+)", names, re.M) if int(k) in (8, 12, 9, 16)] == [
        (12, 8), (13, 12), (14, 9), (15, 16)]


def test_the_start_order_and_the_check_journal_are_documented():
    section = contract()
    assert "called by Core **before** `PresentationStudioService.start()`" in section and "`source: check`" in section
    source = (ROOT / "jarvis" / "core" / "v2_app.py").read_text(encoding="utf-8")
    assert source.index("presentation_studio_variants.start()") < source.index("await self.presentation_studio.start()")

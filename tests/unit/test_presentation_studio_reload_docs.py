"""Parite code/documentation du contrat de rechargement a chaud (jarvis-interactive-presentation-studio, Slice 06).

Les pages disent ce que le code fait : statuts et statuts HTTP, delais et bornes, diagnostics, evenement canonique (Python, miroir
JS, table de `conversation-events.md`), reponse de `Core` aux espaces reserves, cas de remise a zero, decisions (pas de message
`jv:1` de plus, demandes de source non durables), recette Humaine, proprietaires, ligne consommateur et lignes de niveau.
"""

from __future__ import annotations

from pathlib import Path
import re

from jarvis.core import presentation_studio_reload as reload_module
from jarvis.domain.conversation_events import ATTRIBUTE_KEYS, ConversationEventType
from jarvis.domain.presentation_studio_checks import HTTP_STATUS, PresentationStudioErrorCode
from jarvis.domain.presentation_studio_reload import HTTP_STATUS as RELOAD_HTTP, ReloadStatus, StateReset
from tests.unit.test_presentation_studio_docs import page, reload_section

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
EVENT = "system.presentation_studio.scene_reloaded"


def js_constant(name: str, file: str = "control_center_prefab_host.js") -> int:
    return int(re.search(rf"const {name}=(\d+)", (RUNTIME / file).read_text(encoding="utf-8")).group(1))


def test_every_status_is_a_table_row_with_its_http_status():
    section = reload_section()
    for status in ReloadStatus:
        row = next((line for line in section.splitlines() if line.startswith(f"| `{status.value}` |")), None)
        assert row is not None, status
        assert f"| {RELOAD_HTTP[status]} |" in row, (status, row)


def test_the_documented_delays_and_bounds_are_the_ones_in_the_code():
    section = reload_section()
    assert reload_module.DEFAULT_MOUNT_DEADLINE_S == 8.0 and "`DEFAULT_MOUNT_DEADLINE_S` (8 s)" in section
    assert (reload_module.DEFAULT_QUIET_S, reload_module.DEFAULT_MAX_WAIT_S) == (0.4, 4.0)
    assert "0.4 s quiet, 4 s ceiling" in section
    settle = js_constant("SETTLE_MS")
    assert settle == 250 and f"`SETTLE_MS` ({settle} ms)" in section
    edit_timeout = js_constant("EDIT_TIMEOUT_MS", "control_center_presentation_studio_reload.js")
    assert edit_timeout == 50_000 and "deadline\n50 s" in section.replace("deadline 50 s", "deadline\n50 s")
    assert js_constant("REPORT_ATTEMPTS", "control_center_presentation_studio_reload.js") == 3 and "3\nattempts" in section.replace("3 attempts", "3\nattempts")
    assert js_constant("LIVE_CAP") == 24 and js_constant("BUNDLE_CACHE_CAP") == 64
    assert "ring (64)" in section.replace("result ring (64)", "ring (64)")


def test_every_diagnostic_the_reload_modules_emit_is_documented():
    section = reload_section()
    emitted = set()
    for name in ("presentation_studio_reload.py", "presentation_studio_reload_stage.py", "presentation_studio_pins.py",
                 "presentation_studio_mounts.py"):
        text = (ROOT / "jarvis" / "core" / name).read_text(encoding="utf-8")
        emitted |= set(re.findall(r'"core\.presentation_studio\.([a-z_]+)"', text))
    # `_finish` builds one name from a table: its five values are listed here so the parity is not blind to them
    emitted |= {"reload_applied", "reload_refused", "reload_stale", "reload_rolled_back", "reload_pending"}
    assert {"reload_published", "mount_reported", "pins_ready", "stage_rebound"} <= emitted or {"reload_published", "mount_reported", "pins_ready"} <= emitted
    missing = {kind for kind in emitted if f"`{kind}`" not in section}
    assert not missing, missing
    assert "No row, event or log carries a source text" in section


def test_the_reset_cases_name_every_field_of_the_reset_descriptor():
    section = reload_section()
    for field in ("props", "data", "controls", "anchors"):
        assert f"`reset.{field}`" in section, field
    assert "`reset.runtime_values`" in section and "runtime_values" in StateReset().to_dict()
    assert set(StateReset().to_dict()) == {"props", "data", "controls", "anchors", "runtime_values", "unfit"}
    assert "`allow_state_reset: true`" in section and "refused (default)" in section


def test_the_decisions_are_recorded_with_their_reasons():
    section = reload_section()
    assert "**Decision: no new `jv:1` message pair" in section and "type-confusion" in section
    assert "**Not durable, on purpose.**" in section and "Revisit when Slice 21" in section
    assert "The `presentation-studio.` namespace is now reserved" in section
    for needle in ("Crash consistency", "kill between any two steps", "`start_service`", "no window and no run"):
        assert needle in section, needle


def test_every_error_code_the_slice_added_is_in_the_contract_with_its_status():
    section = reload_section()
    for code in ("SOURCE_INVALID", "MOUNT_FAILED", "STAGE_FAILED", "RELOAD_UNAVAILABLE", "SCENE_RELOADING", "SOURCE_EDIT_RATE"):
        member = PresentationStudioErrorCode[code]
        assert f"`{member.value}` ({HTTP_STATUS[member]})" in section, member


def test_the_canonical_event_is_documented_on_both_sides_and_in_the_allowlist():
    events = page("conversation-events.md")
    assert f"| `{EVENT}` | system | I | D |" in events
    assert re.search(r"^\d+\. \*\*Presentation Studio scene hot reload \(Slice 06\)", events, re.M), "the note is missing (its number may change)"
    row = next(line for line in events.splitlines() if line.startswith(f"| `{EVENT}` | system |"))
    assert "presentation_studio_events.py" in row
    assert ConversationEventType("system.presentation_studio.scene_reloaded").value == EVENT
    timeline = (RUNTIME / "control_center_timeline.js").read_text(encoding="utf-8")
    assert timeline.count(EVENT) >= 3                                        # SPECS, DOT_TYPES, labels
    for key in ("presentation_id", "variant_id", "scene_id", "status", "revision", "source", "tier", "code", "reason"):
        assert key in ATTRIBUTE_KEYS, key


def test_the_prefab_page_the_operations_page_and_the_owner_maps_carry_the_slice():
    prefabs = page("prefabs.md")
    assert "**Studio hot swap and observed outcomes**" in prefabs and "`swapPrefix" in prefabs and "`onOutcome" in prefabs
    assert "| Presentation Studio source edit (Slice 06) |" in prefabs and "`StudioPinRegistry`" in prefabs
    assert "all satisfied by Slice 06" in prefabs and "`invalid_definition`" in prefabs
    operations = page("OPERATIONS.md")
    assert "### Rechargement à chaud d'une scène du Studio (recette de vérification Humaine)" in operations
    assert "Arrêter d'attendre" in operations and "allow_state_reset:true" in operations
    architecture = page("ARCHITECTURE.md")
    for needle in ("jarvis/core/presentation_studio_reload.py", "presentation_studio_pins.py", "POST .../variants/{id}/source-edits",
                   "control_center_presentation_studio_reload.js"):
        assert needle in architecture, needle
    assert "`schema_version` 3" in page("local-data.md") and "last_valid_pin" in page("local-data.md")
    studio = page("presentation-studio.md")
    assert "| Scene hot reload |" in studio and "Level 3 (Slice 06)" in studio and "(**done**, Slice 06)" in studio
    names = (ROOT / "tasks" / "jarvis-interactive-presentation-studio" / "docs" / "09-canonical-names.md").read_text(encoding="utf-8")
    assert "## 18. Slice 06 additions" in names and "`ReloadStatus`" in names


def test_every_module_the_page_names_exists():
    section = reload_section()
    for name in re.findall(r"`(jarvis/[a-z_/]+\.(?:py|js))`", section):
        assert (ROOT / name).is_file(), name
    for name in ("presentation_studio_reload_stage.py", "presentation_studio_mounts.py", "presentation_studio_pins.py"):
        assert name in section and (ROOT / "jarvis" / "core" / name).is_file()


def test_the_protocol_a_frame_speaks_did_not_gain_a_message():
    """Slice 06 decision: no snapshot/restore pair. The exported surface of the protocol module is pinned, so adding a message
    type is a visible change that has to update this list and the page."""

    protocol = (RUNTIME / "control_center_prefab_protocol.js").read_text(encoding="utf-8")
    assert "const HOST_TYPES=Object.freeze(['init','update','teardown','event_result'])" in protocol
    assert "const FRAME_TYPES=Object.freeze(['ready','event','resize','open_url','error'])" in protocol
    assert "const SANDBOX='allow-scripts'" in protocol and "snapshot" not in protocol.lower()


def test_the_qa_1_decisions_are_stated_in_the_contract():
    section = reload_section()
    for needle in ("structural only", "does **not** parse or run JavaScript", "not feasible in Python", "BRAIN_EDIT_LIMIT",
                   "presentation_studio_scene_reloading", "compare-and-restore", "`degraded`", "STAGE_RESTORE_ATTEMPTS",
                   "removed", "never overwrites newer work"):
        assert needle in section, needle
    operations = page("OPERATIONS.md")
    assert "n'est pas prouvé par un test" in operations

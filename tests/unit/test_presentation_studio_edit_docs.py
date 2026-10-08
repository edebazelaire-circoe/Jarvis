"""Parite code/documentation du contrat d'edition semantique (jarvis-interactive-presentation-studio, Slice 05).

Les pages disent ce que le code fait : vocabulaire, niveaux, statuts, codes, diagnostics, evenement canonique (Python, miroir
JS, table de `conversation-events.md`, liste blanche), routes du relais, ligne consommateur de `prefabs.md`, proprietaires.
"""

from __future__ import annotations

from pathlib import Path
import re

from jarvis.domain.conversation_events import ATTRIBUTE_KEYS, ConversationEventType
from jarvis.domain.presentation_studio_edit import (
    ALLOWED_EDIT_OPS, MAX_INTENT_CHARS, MAX_OPS, MAX_UNDO_BYTES, UNSAFE_KEYS, EditStatus, EditTier, OpName, StudioActor,
)
from jarvis.runtime.presentation_studio_relay import PresentationStudioRelayRoutes
from tests.unit.test_presentation_studio_docs import edit_section, history_section, page, reload_section

ROOT = Path(__file__).resolve().parents[2]
EVENT = "system.presentation_studio.edit_committed"


def test_every_operation_tier_status_and_actor_is_in_the_vocabulary_table():
    section = edit_section()
    for op in OpName:
        assert f"| `{op.value}` |" in section, op
    for tier in EditTier:
        assert f"`{tier.value}`" in section, tier
    for status in EditStatus:
        assert f"| `{status.value}` |" in section, status
    for actor in StudioActor:
        assert f"`{actor.value}`" in section
    assert set(ALLOWED_EDIT_OPS) == set(StudioActor)
    for bound in (f"<= {MAX_INTENT_CHARS} characters", f"[1..{MAX_OPS}]", f"{MAX_UNDO_BYTES // 1024} KiB"):
        assert bound in section, bound
    for name in UNSAFE_KEYS:
        assert f"`{name}`" in section, name


def test_the_documented_inverse_of_each_operation_exists_in_the_vocabulary():
    section = edit_section()
    rows = [line for line in section.splitlines() if line.startswith("| `") and "`" in line[3:] and line.count("|") >= 5]
    ops = {op.value for op in OpName}
    seen = set()
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        name = cells[0].strip("`")
        if name not in ops:
            continue
        seen.add(name)
        inverse = re.findall(r"`(scene\.[a-z_]+|control\.[a-z_]+)`", cells[3])
        assert set(inverse) <= ops, (name, inverse)
    assert seen == ops


def test_every_diagnostic_the_edit_service_emits_is_documented():
    source = (ROOT / "jarvis/core/presentation_studio_edit.py").read_text(encoding="utf-8")
    emitted = set(re.findall(r'"core\.presentation_studio\.([a-z_]+)"', source))
    assert {"edit_committed", "edit_previewed", "edit_refused", "edit_stale", "edit_source_recorded",
            "controls_suggested", "event_failed"} <= emitted
    section = edit_section()
    missing = {kind for kind in emitted if not re.search(r"(?<![a-z_])" + kind + r"(?![a-z_])", section)}
    assert not missing, missing


def test_the_relay_routes_are_the_documented_ones():
    section = edit_section() + "\n" + history_section() + "\n" + reload_section()  # undo/redo (Slice 08) and source edits (Slice 06) are the same kind of write
    relay = PresentationStudioRelayRoutes(transport=lambda: None, journal=None)  # type: ignore[arg-type]
    for route in relay.routes():
        if route.method == "POST" and not route.path.startswith("/api/presentation-studio/playback"):   # Slice 12: its own contract
            assert f"`POST {route.path}`" in section, route.path
    assert "no `PUT`" in section and "actor forced to `user`" in section
    assert "READ_GUARDED_ROUTES" in section


def test_the_canonical_event_is_documented_on_both_sides_and_the_allowlist_page():
    events = page("conversation-events.md")
    assert f"| `{EVENT}` | system | I | D |" in events and EVENT in events[events.index("7. **Presentation Studio edit"):]
    table_row = next(line for line in events.splitlines() if line.startswith(f"| `{EVENT}` | system |"))
    assert "presentation_studio_edit.py" in table_row
    allowlist = events[events.index("2. `attributes` keys must be in `ATTRIBUTE_KEYS`:"):]
    allowlist = allowlist[:allowlist.index("At most 24 keys")]
    for key in ("presentation_id", "variant_id", "scene_id", "op", "tier"):
        assert key in ATTRIBUTE_KEYS and re.search(r"(?<![a-z_])" + key + r"(?![a-z_])", allowlist), key
    js = (ROOT / "jarvis/runtime/control_center_timeline.js").read_text(encoding="utf-8")
    assert f"'{EVENT}':['system',I,D]" in js and js.count(EVENT) >= 3
    assert ConversationEventType.SYSTEM_PRESENTATION_STUDIO_EDIT_COMMITTED.value == EVENT
    assert EVENT in edit_section()


def test_the_prefab_page_architecture_and_owner_map_know_the_edit_api():
    prefabs = page("prefabs.md")
    consumers = prefabs[prefabs.index("## Consumers (Presentation seam)"):]
    assert "Presentation Studio edit API (Slice 05)" in consumers and "SceneService.apply_if" in consumers
    assert "presentation-studio.md#semantic-edit-contract-level-3" in consumers
    architecture = page("ARCHITECTURE.md")
    for needle in ("jarvis/domain/presentation_studio_edit.py", "jarvis/core/presentation_studio_edit.py",
                   "jarvis/runtime/presentation_studio_relay.py", "POST .../variants/{id}/edits"):
        assert needle in architecture, needle
    studio = page("presentation-studio.md")
    assert "| Semantic edit (3 tiers) |" in studio and "[Semantic edit contract](#semantic-edit-contract-level-3)" in studio
    assert studio.count("**implemented (Level 3)**") >= 3
    for module in ("jarvis/domain/presentation_studio_edit.py", "jarvis/core/presentation_studio_edit.py",
                   "jarvis/core/presentation_studio_events.py", "jarvis/runtime/presentation_studio_relay.py"):
        assert (ROOT / module).is_file()
        assert module.split("/")[-1].replace(".py", "") in edit_section()

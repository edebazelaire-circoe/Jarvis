"""Parite code/documentation du contrat de persistance et d'annulation (jarvis-interactive-presentation-studio, Slice 08).

Les pages disent ce que le code fait : bornes, issues et codes, raisons d'abandon, routes (Core et relais), diagnostics,
modules proprietaires, garantie de durabilite sans debounce, pages de donnees locales et d'exploitation.
"""

from __future__ import annotations

from pathlib import Path
import re

from jarvis.domain import presentation_studio_history as history
from jarvis.domain.presentation_studio_checks import PresentationStudioErrorCode as C
from jarvis.protocol.presentation_studio_routes import PREFIX, PresentationStudioProtocolRoutes
from jarvis.runtime.presentation_studio_relay import PresentationStudioRelayRoutes
from tests.unit.test_presentation_studio_docs import history_section, page

ROOT = Path(__file__).resolve().parents[2]


def test_every_bound_in_the_code_is_in_the_bounds_table():
    section = history_section()
    for needle in (f"| entries per variant (undo + redo) | {history.MAX_ENTRIES_PER_VARIANT} |",
                   f"| bytes of one entry | {history.MAX_ENTRY_BYTES // 1024} KiB (`MAX_UNDO_BYTES`) |",
                   f"| bytes per variant | {history.MAX_VARIANT_BYTES // 1024} KiB |",
                   f"| bytes in total | {history.MAX_TOTAL_BYTES // (1024 * 1024)} MiB |",
                   f"| variants tracked | {history.MAX_TRACKED_VARIANTS} |",
                   f"the {history.MAX_LISTED_ENTRIES} most recent entries"):
        assert needle in section, needle
    module = (ROOT / "jarvis/domain/presentation_studio_history.py").read_text(encoding="utf-8")
    for needle in ("| entrées par variante (annuler + rétablir) | 32 |", "| variantes suivies | 8 |", "| octets au total | 1 Mio |"):
        assert needle in module, needle  # the module docstring table says the same numbers


def test_every_status_reason_and_code_is_documented_and_every_documented_one_exists():
    section = history_section()
    for status in history.HistoryStatus:
        assert f"`{status.value}`" in section, status
    for reason in history.DropReason:
        assert f"`{reason.value}`" in section or reason in (history.DropReason.REDO_CLEARED,), reason
    assert "`redo_cleared`" in section
    for code in (C.HISTORY_UNAVAILABLE, C.HISTORY_EMPTY, C.HISTORY_STALE):
        assert f"`{code.value}`" in section, code
    assert {code for code in re.findall(r"`(presentation_studio_history_[a-z]+)`", section)} <= {
        C.HISTORY_UNAVAILABLE.value, C.HISTORY_EMPTY.value, C.HISTORY_STALE.value}
    for reason in history.DropReason:
        assert history.reason_text(reason), reason


def test_the_history_routes_are_in_the_table_and_the_relay_forces_the_actor():
    section = history_section()
    routes = {(r.method, r.path) for r in PresentationStudioProtocolRoutes(object()).routes()}
    for tail, method in (("history", "GET"), ("undo", "POST"), ("redo", "POST")):
        path = f"{PREFIX}/{{presentation_id}}/variants/{{variant_id}}/{tail}"
        assert (method, path) in routes and f"`{path}`" in section, path
    relay = PresentationStudioRelayRoutes(transport=lambda: None, journal=None)  # type: ignore[arg-type]
    for route in relay.routes():
        if route.path.endswith(("/undo", "/redo")):
            assert f"`POST {route.path.replace('{', '{').replace('}', '}')}`" in section, route.path
    assert section.count("actor forced to `user`") >= 2


def test_every_diagnostic_the_history_and_recovery_emit_is_documented():
    emitted = set()
    for module in ("jarvis/core/presentation_studio_autosave.py",):
        emitted |= set(re.findall(r'"core\.presentation_studio\.([a-z_]+)"', (ROOT / module).read_text(encoding="utf-8")))
    service = (ROOT / "jarvis/core/presentation_studio_service.py").read_text(encoding="utf-8")
    emitted |= {"recovered", "recovery_failed"} & set(re.findall(r'"core\.presentation_studio\.([a-z_]+)"', service))
    assert {"history_applied", "history_not_applied", "history_evicted", "history_dropped", "history_record_failed",
            "history_score_unchecked", "recovered", "recovery_failed"} <= emitted
    section = history_section()
    missing = {kind for kind in emitted if not re.search(r"(?<![a-z_])" + kind + r"(?![a-z_])", section)}
    assert not missing, missing


def test_the_durability_guarantee_is_stated_without_a_debounce_and_the_owner_modules_exist():
    section = history_section()
    for needle in ("there is no second persistence path", "none: nothing is buffered", "No debounce class exists on purpose",
                   "`FlushFileBuffers`", "**Not proven by a test here**", "A temporary is **never promoted**"):
        assert needle in section, needle
    for module in ("jarvis/domain/presentation_studio_history.py", "jarvis/core/presentation_studio_autosave.py"):
        assert (ROOT / module).is_file() and module in section.replace("`", ""), module
    for test in ("history", "history_service", "history_routes", "history_crash", "recovery", "durability", "history_docs"):
        assert (ROOT / f"tests/unit/test_presentation_studio_{test}.py").is_file(), test
    assert "PrefabPinRegistry" in section and "before" in section and "EditHistory.begin" in section


def test_the_concept_table_the_seams_and_the_data_pages_agree():
    studio = page("presentation-studio.md")
    assert "| **done, Slice 08** (*Persistence and undo contract*) |" in studio or "**done, Slice 08**" in studio
    assert "persistence-and-undo-contract-level-3" in studio
    row = next(line for line in studio.splitlines() if line.startswith("| Autosave + undo |"))
    assert "**implemented (Level 3)**" in row and "presentation_studio_autosave.py" in row
    local = page("local-data.md")
    assert "Historique d'annulation" in local and "redémarrage" in local and "history_unavailable" in local
    operations = page("OPERATIONS.md")
    section = operations[operations.index("### Presentations du Studio : sauvegarde et restauration"):]
    section = section[:section.index("\n### ", 10)]
    for needle in ("recovery_failed", "history_unavailable", "*.tmp", "last_recovery", ".bak"):
        assert needle in section, needle
    events = page("conversation-events.md")
    assert "undone" in events and "redone" in events

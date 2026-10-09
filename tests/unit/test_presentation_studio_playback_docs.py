"""Code/documentation parity of the playback runtime contract (jarvis-interactive-presentation-studio, Slice 12).

The pages say what the code does: phases, events, refusal codes, effects, bounds, routes (Core and relay), verbs, statuses, error
codes, diagnostics, the canonical event, the armed-cue contract, the owner modules, the local-data exception, the OPERATIONS
recipe and the temporary-behaviour entry.
"""

from __future__ import annotations

from pathlib import Path
import re

from jarvis.domain import presentation_studio_armed_set as armed
from jarvis.domain import presentation_studio_playback as pb
from jarvis.domain.presentation_studio_checks import PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_playback_requests import Verb
from jarvis.protocol.presentation_studio_playback_routes import CUES, PLAYBACK, PresentationStudioPlaybackRoutes
from jarvis.runtime.presentation_studio_relay import PresentationStudioRelayRoutes
from tests.unit.test_presentation_studio_docs import _section, page

ROOT = Path(__file__).resolve().parents[2]


def section() -> str:
    return _section("## Playback runtime contract (Level 3, Slice 12)")


def test_every_phase_event_effect_and_refusal_is_documented():
    text = section()
    for name, members in (("phase", pb.Phase), ("event", pb.EventKind), ("effect", pb.Effect), ("refusal", pb.RefusalCode)):
        for member in members:
            assert f"`{member.value}`" in text, (name, member.value)
    assert "(40 seeds x 150 events)" in text


def test_the_bounds_in_the_code_are_the_bounds_in_the_page():
    text = section()
    for needle in (f"`MAX_AUX_STACK` {pb.MAX_AUX_STACK}", "`MAX_EXPANDED_ITEMS` 2000", "`MAX_WHERE_BYTES`", f"MAX_WHERE_PHRASES {pb.MAX_WHERE_PHRASES}",
                   f"`ARM_LOOKAHEAD` {pb.ARM_LOOKAHEAD}", f"({int(armed.ARMED_SET_TTL_S)} s)",
                   f"{int(armed.REPORT_RATE_PER_S)} per second, burst {armed.REPORT_BURST}",
                   f"the last {armed.REMEMBERED_REPORTS} answers", "at most 2048 bytes"):
        assert needle in text, needle
    assert pb.MAX_WHERE_BYTES == 2048 and armed.ARMED_CHANGED == "presentation_studio.armed.changed" and armed.ARMED_CHANGED in text


def test_the_routes_verbs_statuses_and_codes_are_documented():
    text = section()
    routes = {(r.method, r.path) for r in PresentationStudioPlaybackRoutes(object()).routes()}
    assert routes == {("GET", PLAYBACK), ("GET", PLAYBACK + "/armed"), ("POST", PLAYBACK + "/{verb}"), ("POST", CUES)}
    for path in (PLAYBACK, PLAYBACK + "/armed", PLAYBACK + "/{verb}", CUES):
        assert path in text, path
    assert f"`{' '.join(v.value for v in Verb)}`" in text, "the verb list in the page is the Verb enum, in order"
    for code in (C.PLAYBACK_REFUSED, C.PLAYBACK_STAGE_FAILED, C.UNKNOWN_SCORE, C.SCORE_INCOMPATIBLE):
        assert f"`{code.value}`" in text, code
    for status in ("applied", "refused", "stage_failed"):
        assert f"`{status}`" in text
    for code in armed.ReportCode:
        if code is not armed.ReportCode.MALFORMED:
            assert f"`{code.value}`" in text, code


def test_the_relay_surface_is_documented_and_never_carries_the_armed_set_or_the_cue_report():
    text = section()
    relay = PresentationStudioRelayRoutes(transport=lambda: None, journal=None)  # type: ignore[arg-type]
    mine = {(r.method, r.path) for r in relay.routes() if r.path.startswith("/api/presentation-studio/playback")}
    assert mine == {("GET", "/api/presentation-studio/playback"),
                    *(("POST", f"/api/presentation-studio/playback/{v.value}") for v in Verb)}
    assert "not relayed" in text and "forced" in text
    relay_doc = (ROOT / "jarvis/runtime/presentation_studio_relay.py").read_text(encoding="utf-8")
    assert "Jamais relayés" in relay_doc and "playback/armed" in relay_doc and "cues/satisfied" in relay_doc


def test_every_diagnostic_the_playback_code_emits_is_documented():
    emitted: set[str] = set()
    for module in ("jarvis/core/presentation_studio_playback.py", "jarvis/core/presentation_studio_stage.py"):
        code = (ROOT / module).read_text(encoding="utf-8")
        emitted |= set(re.findall(r'self\._trace\(\s*"([a-z_]+)"', code))
    edit = (ROOT / "jarvis/core/presentation_studio_edit.py").read_text(encoding="utf-8")
    emitted |= {k for k in re.findall(r'"core\.presentation_studio\.([a-z_]+)"', edit) if k in ("overlay_rendered", "commit_listener_failed")}
    assert {"playback_started", "playback_stopped", "playback_crashed", "stage_shown", "aux_staged", "archived", "mode_restore_failed",
            "stage_ledger_unreadable", "overlay_rendered", "armed_publish_failed", "cue_report_refused"} <= emitted, emitted
    text = section()
    missing = {kind for kind in emitted if not re.search(r"(?<![a-z_])" + kind + r"(?![a-z_])", text)}
    assert not missing, missing


def test_the_canonical_event_attributes_and_statuses_are_documented():
    text = section()
    events = page("conversation-events.md")
    assert "system.presentation_studio.playback_changed" in events and "system.presentation_studio.playback_changed" in text
    source = (ROOT / "jarvis/core/presentation_studio_playback.py").read_text(encoding="utf-8")
    statuses = set(re.findall(r'status_event = "([a-z_]+)"', source)) | set(re.findall(r'self\._announce\("([a-z_]+)"\)', source))
    statuses |= set(re.findall(r'"[a-z_]+": "([a-z_]+)"', source[source.index("_STATUS_OF = {"):source.index("def _set_op")]))
    assert {"started", "stopped", "paused", "resumed", "detour", "returned", "ended", "stage_failed", "edit_committed"} <= statuses, statuses
    for status in statuses:
        assert f"`{status}`" in text, status
    assert "`role` was added to\n   `ATTRIBUTE_KEYS`" in events


def test_owners_exist_and_the_other_pages_carry_their_rows():
    text = section()
    for module in re.findall(r"`(jarvis/[a-z_/]+\.(?:py|js))`", text):
        assert (ROOT / module).is_file(), module
    for test in ("playback", "playback_service", "playback_routes", "stage", "edit_overlay", "player_js", "player_browser"):
        assert (ROOT / f"tests/unit/test_presentation_studio_{test}.py").is_file(), test
    assert "state/presentation-studio-stage-ledger.json" in page("local-data.md")
    assert "state/presentation-studio-stage-ledger.json" in page("ARCHITECTURE.md")
    assert "Lecture d'une présentation (studio, Slice 12)" in page("OPERATIONS.md")
    spec = page("presentation-speculative-preparation.md")
    assert "The Presentation Studio is a second consumer of this lifetime rule" in spec and "`StageLedger`" in spec
    assert not (ROOT / "docs/legacy/presentation-studio-art-direction-gate.md").exists()  # removed by the Slice 09 merge
    assert "art-direction-gate" not in section() and "unchecked" not in section()
    assert "[Playback runtime contract](#playback-runtime-contract-level-3-slice-12)" in page("presentation-studio.md")
    names = (ROOT / "tasks/jarvis-interactive-presentation-studio/docs/09-canonical-names.md").read_text(encoding="utf-8")
    assert "## 13. Slice 12 amendments" in names and "presentation_studio_armed_set.py" in names


def test_the_armed_cue_contract_states_what_slice_13_must_do():
    text = section()
    for needle in ("invalidate, then pull", "not relayed", "exactly those keys", "`duplicate: true`", "`ambiguous`", "expires_in_s / 3",
                   "Core never builds a `BrainTurnInput`"):
        assert needle in text, needle


def test_the_rework_contract_is_documented_with_its_constants():
    """QA-1 rework: skip_sequence, detour_invalid / 422, the follower state, the ledger scan, the reopen rule, the identity token."""

    from jarvis.adapters.file_presentation_studio_stage_ledger import KEEP_QUARANTINED
    from jarvis.core.presentation_studio_playback import FOLLOWER_GRACE_S, MAX_VIEW_BYTES
    from jarvis.core.presentation_studio_stage import MAX_STAGE_REOPENS

    text = section()
    for needle in (f"`MAX_VIEW_BYTES` {MAX_VIEW_BYTES}", f"`FOLLOWER_GRACE_S` {int(FOLLOWER_GRACE_S)} s",
                   f"`MAX_STAGE_REOPENS` {MAX_STAGE_REOPENS}", f"`KEEP_QUARANTINED` {KEEP_QUARANTINED}",
                   "`skip_sequence`", "`detour_invalid`", "**422**", "`follower: absent`", "`waiting`", "`connected`",
                   "Sortir de la séquence", ".corrupt-", "stage_ledger_scan_reclaimed", "origin=token", "capture phase",
                   "Slice 14 keeps it", "Suivi vocal indisponible", "`stage_closed_by_user`", "`stage_closed`"):
        assert needle in text, needle
    roles = page("presentation-studio.md")
    assert "Core cannot see the architecture" in roles and "still start" in roles
    assert "cannot start; the refusal reason is shown" not in roles, "the contradiction QA-1 P6 found must not come back"
    assert "Suivi vocal" in page("OPERATIONS.md") and "Sortir de la séquence" in page("OPERATIONS.md")

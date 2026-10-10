"""Code/documentation parity of the Jarvis presenter contract (jarvis-interactive-presentation-studio, Slice 14).

The page says what the code does: the constants, the problem codes, every diagnostic the presenter emits, the conversation event and
its statuses (and its mirror in the JS timeline), the owner modules and their tests, the OPERATIONS recipe, the canonical-names section.
"""

from __future__ import annotations

from pathlib import Path
import re

from jarvis.core import presentation_studio_presenter as presenter
from jarvis.domain.conversation_events import ATTRIBUTE_KEYS, ConversationEventType as T, event_actor, event_shape, event_visibility
from tests.unit.test_presentation_studio_docs import _section, page

ROOT = Path(__file__).resolve().parents[2]
TITLE = "## Jarvis presenter and locked sequences (Level 3, Slice 14)"


def section() -> str:
    return _section(TITLE)


def source() -> str:
    return (ROOT / "jarvis/core/presentation_studio_presenter.py").read_text(encoding="utf-8")


def test_the_constants_in_the_code_are_the_constants_in_the_page():
    text = section()
    for needle in (f"`START_TIMEOUT_S` {int(presenter.START_TIMEOUT_S)}", f"`LINE_TIMEOUT_S` {int(presenter.LINE_TIMEOUT_S)}",
                   f"`GAP_MS` {presenter.GAP_MS}", f"`SILENCE_DEFAULT_MS` {presenter.SILENCE_DEFAULT_MS}"):
        assert needle in text, needle


def test_every_problem_code_and_failure_reason_is_documented_on_both_pages():
    codes = {presenter.SPEECH_NOT_STARTED, presenter.SPEECH_STALLED, presenter.ANNOUNCE_REFUSED, presenter.ANNOUNCE_FAILED,
             presenter.LINE_INVALID, presenter.PRESENTER_CRASHED, *presenter._FAILURE_OF.values()}
    text, events = section(), page("conversation-events.md")
    for code in codes:
        assert f"`{code}`" in text, code
        assert f"`{code}`" in events, code


def test_every_diagnostic_the_presenter_emits_is_documented():
    emitted = set(re.findall(r'self\._trace\(\s*"([a-z_]+)"', source()))
    assert {"presenter_attached", "presenter_line_issued", "presenter_line_failed", "presenter_interrupted",
            "presenter_sequence_step", "presenter_sequence_done", "presenter_completed", "presenter_crashed"} <= emitted, emitted
    text = section()
    missing = {kind for kind in emitted if not re.search(r"(?<![a-z_])" + kind + r"(?![a-z_])", text)}
    assert not missing, missing


def test_the_event_is_registered_everywhere_and_its_statuses_are_documented():
    assert event_actor(T.SYSTEM_PRESENTATION_STUDIO_PRESENTER_CHANGED).value == "system"
    assert event_shape(T.SYSTEM_PRESENTATION_STUDIO_PRESENTER_CHANGED).value == "instant"
    assert event_visibility(T.SYSTEM_PRESENTATION_STUDIO_PRESENTER_CHANGED).value == "diagnostic"
    assert {"status", "code", "count", "role", "presentation_id", "variant_id"} <= ATTRIBUTE_KEYS
    name = "system.presentation_studio.presenter_changed"
    js = (ROOT / "jarvis/runtime/control_center_timeline.js").read_text(encoding="utf-8")
    assert js.count(name) == 3, "specs, left-rail dots and the label"
    events, text = page("conversation-events.md"), section()
    assert name in events and name in text
    statuses = set(re.findall(r'self\._emit\("([a-z_]+)"', source()))
    assert statuses == {"line_failed", "interrupted", "sequence_done", "sequence_skipped", "sequence_aborted", "completed"}, statuses
    for status in statuses:
        assert f"`{status}`" in text and f"`{status}`" in events, status
    assert "never an attribute" in events or "never an exception message" in events


def test_owners_and_conformance_tests_exist_and_the_other_pages_carry_their_rows():
    text = section()
    for module in re.findall(r"`(jarvis/[a-z_/]+\.(?:py|js))`", text):
        assert (ROOT / module).is_file(), module
    group = re.search(r"tests/unit/test_presentation_studio_\{([a-z_,]+)\}\.py", text).group(1)
    for name in group.split(","):
        assert (ROOT / f"tests/unit/test_presentation_studio_{name}.py").is_file(), name
    assert (ROOT / "tests/fakes/presentation_studio_presenter.py").is_file()
    assert "Présentation par Jarvis (studio, Slice 14)" in page("OPERATIONS.md")
    assert "[Jarvis presenter and locked sequences](#jarvis-presenter-and-locked-sequences-level-3-slice-14)" in page("presentation-studio.md")
    names = (ROOT / "tasks/jarvis-interactive-presentation-studio/docs/09-canonical-names.md").read_text(encoding="utf-8")
    assert "## 16. Slice 14 amendments" in names and "presentation_studio_presenter.py" in names


def test_the_page_states_the_decisions_the_reviewers_need():
    text = section()
    for needle in ("announce_notice", "ScoreLineNotice", "supersedes_key", "t0 + shift + offset_ms", "no drift", "preserves every remaining offset",
                   "`skip_sequence`", "user-only", "resume is the user's explicit continue", "from its start", "`recovery_position`",
                   "`abort_to_recovery`", "`pause_resume`", "`at_boundary`", "`refuse`", "`allow`", "`stage_scene_id`", "never the text of a line", "Not run live", "`epoch`", "mode restored", "tool_brain_speech"):
        assert needle in text, needle
    # the speech-authority page is untouched: the matrix, LOCKED_DECISIONS and the gate are exactly what 01c left
    policy = page("presentation-response-policy.md")
    assert "presentation_studio_presenter" not in policy and "score_line" not in policy
    code = source()
    for forbidden in ("openai", "tts", "SpeechRequest(", "speak_reserved", "session.speak", "requests.", "aiohttp"):
        assert forbidden not in code, f"the presenter owns no speech stack: {forbidden}"


def test_the_provisional_wording_of_skip_sequence_is_gone_but_the_verb_is_kept():
    text = _section("## Playback runtime contract (Level 3, Slice 12)")
    assert "Provisional escape" not in text and "Slice 14 keeps it" in text
    assert "a locked sequence nobody executes (before Slice 14)" not in text
    assert "(Slice 14: the Jarvis presenter, exact offsets from t0)" in text
    player = (ROOT / "jarvis/runtime/control_center_presentation_studio_player.js").read_text(encoding="utf-8")
    assert "provisoire" not in player.lower()


def test_the_rework_documentation_is_honest_about_started_the_slice_21_entry_condition_and_noise():
    text = section()
    assert "*generation requested*, not *first sound*" in text and "no first-audio signal" in text
    assert "the first words and the first visuals are together" not in text
    assert "Entry condition for Slice 21" in text and "MUST derive the origin from the real turn" in text
    assert "test_entry_condition_for_slice_21_a_brain_actor_with_an_explicit_request_origin_is_accepted_by_the_start_contract" in text
    assert "**not filtered for noise**" in text
    ops = page("OPERATIONS.md")
    assert "Fenêtre connue" in ops and "même clé de parole" in ops
    assert "together" not in (ROOT / "jarvis/domain/presentation_studio_sequence.py").read_text(encoding="utf-8").split("Synchronisation with speech")[1][:700]

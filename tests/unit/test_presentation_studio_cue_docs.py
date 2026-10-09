"""Code/documentation parity of the cue following contract and the R5 amendment (jarvis-interactive-presentation-studio, Slice 13)."""

from __future__ import annotations

import re
from pathlib import Path

from jarvis.domain import presentation_studio_cues as cues
from jarvis.runtime import presentation_studio_cue_follower as follower
from tests.unit.test_presentation_studio_docs import _section, page

ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "tasks/jarvis-interactive-presentation-studio"


def section() -> str:
    return _section("## Cue following contract (Level 3, Slice 13)")


def test_every_verdict_rule_state_and_counter_is_documented() -> None:
    text = section()
    for enum in (cues.Verdict, cues.MatchRule, follower.FollowerState):
        for member in enum:
            assert f"`{member.value}`" in text, (enum.__name__, member.value)
    counters = follower.FollowerCounters()
    for name in counters.to_payload():
        key = name.removeprefix("reports_")
        assert key in text or name in text, name
    for owner in ("presentation_studio_cues.py", "presentation_studio_cue_follower.py", "add_utterance_consumer", "build_cue_follower"):
        assert owner in text, owner


def test_the_defaults_in_the_code_are_the_defaults_in_the_page() -> None:
    text = section()
    m, f = cues.MatcherConfig(), follower.FollowerConfig()
    assert (m.before_tokens, m.after_tokens, m.utterance_before_tokens, m.utterance_after_tokens) == (1, 1, 6, 4)
    assert m.single_word_max_tokens == 2 and m.max_gap == 1 and m.max_total_gap == 2
    assert m.fuzzy_min_chars == 16 and m.fuzzy_min_token_chars == 6 and m.cue_cooldown_s == 4.0 and m.min_interval_s == 1.0
    assert m.allow_skip_ahead is False
    for needle in ("at most **1** content word before it and **1** after it", "at most **6** content words before it and **4** after it",
                   "| 1 / 1 / 6 / 4 |", "phrase of >= 16 characters", "of >= 6 letters", "at most 1 inserted token",
                   "| 4 s, 1 s |", "`hold_s` (4 s)", "`idle_poll_s`", "5 s deadline", "1 s doubling to 30 s", "blocked for 2 s", "throttled to one per second",
                   "`expires_in_s / 3` (30 s)", "90 s", "obeys the same backoff as a poll", "**4 tokens before** or **2 tokens after**",
                   "opaque counter id set by the lane", "`jarvis` token anywhere", "marker", "build_cue_follower", "weak_cue"):
        assert needle in text, needle
    assert f.hold_s == 4.0 and f.idle_poll_s == 5.0 and f.call_timeout_s == 5.0 and f.backoff_base_s == 1.0 and f.backoff_max_s == 30.0
    assert f.rate_backoff_s == 2.0 and f.repull_gap_s == 1.0


def test_the_quotation_window_in_the_page_is_the_one_in_the_code() -> None:
    """QA-1 P2: the page had the window reversed (4 after / 2 before). The code looks 4 tokens BEFORE and 2 AFTER."""

    import inspect

    source = inspect.getsource(cues._context_verdict)
    assert "toks[max(0, hit.first - 4):hit.first]" in source and "toks[hit.last + 1:hit.last + 3]" in source
    assert "**4 tokens before** or **2 tokens after**" in section()


def test_every_diagnostic_the_follower_writes_is_documented() -> None:
    source = (ROOT / "jarvis/runtime/presentation_studio_cue_follower.py").read_text(encoding="utf-8")
    kinds = set(re.findall(r'self\._trace\(\s*"([a-z_]+)"', source))
    assert len(kinds) >= 12, kinds
    text = section()
    for kind in kinds:
        assert kind in text, kind
        assert kind in (HANDOFF / "docs/09-canonical-names.md").read_text(encoding="utf-8"), kind


def test_the_measured_rates_in_the_page_are_the_measured_rates_of_the_corpora() -> None:
    import asyncio

    from tests.unit import test_presentation_studio_cue_corpus as corpus

    async def everything() -> dict:
        results = {name: await corpus.measure(module) for name, module in corpus.corpora().items()}
        first, second = corpus.union_split()
        results["selection"], results["held_out"] = await corpus.measure_cases(first), await corpus.measure_cases(second)
        return results

    results = asyncio.run(everything())
    text = section().replace("**", "")
    for name, r in results.items():
        cell = f"{r['cases']} ({r['positives']} / {r['negatives']})"
        fp = f"{len(r['fp'])} / {r['negatives']} = {len(r['fp']) / r['negatives']:.1%}".replace("%", " %")
        fn = f"{len(r['fn'])} / {r['positives']} = {len(r['fn']) / r['positives']:.1%}".replace("%", " %")
        assert cell in text and fp in text and fn in text, (name, cell, fp, fn)
    assert len(results["qa"]["fp"]) == 0  # the QA measured 12/50 = 24 % before the rework: it is quoted as history in the page
    assert "12 / 50" in text and "24 %" in text


def test_the_r5_amendment_is_in_the_addressed_turn_contract_and_names_the_three_enforcement_points() -> None:
    text = page("presentation-addressed-turn.md")
    start = text.index("### Amendment (handoff jarvis-interactive-presentation-studio, Slice 13, R5): armed score cues")
    amendment = text[start:text.index("\n## 13.", start)]
    for needle in ("Ambient speech may satisfy exactly one kind of thing: a score cue that is currently armed",
                   "`decide_turn_authority`", "`BrainTurnInput.__post_init__`", "`PresentationOutputPolicy.__post_init__`",
                   "`AmbientTriggerKind` stays closed", "`CueMatch(cue_id, generation, evidence)`", "Explicit address preempts, always",
                   "test_presentation_studio_cue_authority.py", "byte for byte", "pre-authorized, reversible"):
        assert needle in amendment, needle
    assert text.index("### The rule (P2)") < start  # the rule is amended after it is stated, not rewritten


def test_the_lane_conversation_event_operations_and_names_pages_say_the_same_thing() -> None:
    lane = page("presentation-ambient-lane.md")
    assert "add_utterance_consumer" in lane and "## 12. A second consumer of utterances" in lane
    events = page("conversation-events.md")
    assert "Slice 13 (cue follower) adds no event" in events and "system.presentation_studio.cue_satisfied" in events
    ops = page("OPERATIONS.md")
    assert "### Suivi des cues à la voix (studio, Slice 13)" in ops and "pile vocale OpenAI" in ops and "jamais le Jarvis vivant" in ops
    names = (HANDOFF / "docs/09-canonical-names.md").read_text(encoding="utf-8")
    assert "## 17. Slice 13 amendments" in names and "add_utterance_consumer(consumer) -> remove" in names
    studio = page("presentation-studio.md")
    assert "**done, Slice 13** (*Cue following contract*)" in studio

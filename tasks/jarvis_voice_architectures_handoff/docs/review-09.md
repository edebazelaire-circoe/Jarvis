# Task09 parent review

Accepted on 2026-09-12 after contract, independent QA, parent regression and
documentation review.

## Reviewed behavior

The immutable request binds the actual canonical input revision, optional Core
origin, selected context source, application analysis admission, configuration
and original monotonic deadline. Provisional B can use A as context without
inventing B's committed origin. Only the strict hint value crosses the model
JSON boundary; no tool, speech text, executor or authority handle is present.

The synchronous consumer holds one expected request. Consumption rechecks
current time, input, session, admission, configuration and relevant source
dependencies. Same-ID registration cannot alter the binding or renew a deadline;
late replies cannot consume a newer expectation. No action is distinct from
WAIT, and silence/preamble suggestions cannot hold ready useful content. Task06
and Task08 remain policy and output authorities. No model call or production
controller integration is claimed by this slice.

## Findings repaired

- Independent QA and parent inspection found that a 512-digit JSON confidence
  integer raised OverflowError inside math.isfinite. Bounds now reject the
  value before conversion; permanent tests cover both confidence fields.
- Parent found that the reused context message type did not validate its role.
  The request now locally requires VoiceContextRole, rejecting arbitrary roles
  while retaining USER, ASSISTANT and DEVELOPER. No unrelated contract migration.

Independent detailed evidence: `review-09-findings.md`. No finding remains open.

## Parent gate

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_front_brain_hints.py tests/unit/test_front_brain_hint_review.py tests/unit/test_voice_architecture_config.py tests/unit/test_voice_conversation_state.py tests/unit/test_reflex_gate.py tests/unit/test_speech_presentation.py tests/unit/test_speech_presentation_scheduler.py tests/unit/test_v2_architecture.py -q -W error -o asyncio_default_fixture_loop_scope=function --tb=short
```

**284 passed in 6.70 s**. Global diff whitespace check passed. The preceding
Task08 full release was green (2294 passed, 4 skipped); this pure contract slice
uses the focused dependent-layer gate instead of repeating the full release.
Real RuntimeJournal tests verify bounded identity/reason events without private
transcript or hypothesis content. Controlled fake cancellation leaves no active
analysis. No provider session, physical-device benchmark or commit was made.

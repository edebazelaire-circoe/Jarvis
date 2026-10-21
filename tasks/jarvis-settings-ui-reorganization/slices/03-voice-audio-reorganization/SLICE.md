# Slice 03 - Voice and audio reorganization

## Goal

Turn the overloaded Voice + Wake-word surfaces into a legible `Voix & audio` category for normal use, while routing low-level architecture and diagnostics to Advanced.

## Context

Voice currently contains seven internal categories and dozens of settings. Wake word is a separate top-level tab with its own diagnostics. The current surface mixes user choices, compatibility architecture, audio hardware, turn-taking tuning and read-only runtime state.

## Canonical Concepts

- `docs/06-current-settings-inventory.md`
- `docs/07-target-settings-map.md`
- `docs/voice-settings-schema.md`
- wake-word settings contract/tests

## Scope

### In Scope

- Create clear Voice sections: Conversation, Voice/transcription, Microphone & sound, Turns & interruptions, Wake word.
- Move the five wake-word editable controls into this category.
- Keep restart-required messaging and provider requirements intact.
- Keep audio device test and meaningful user-facing availability errors.
- Route Voice architecture/compatibility, deep VAD/buffer/speaker-verifier tuning and raw diagnostics to registered Advanced sections.
- Remove wake/send/interrupt key editing from Voice; replace with effective-key context + deep link to Interface shortcuts if needed.

### Out of Scope

- Do not change Voice runtime arbitration.
- Do not change provider/model catalogs.
- Do not change wake-word engine semantics or persistence.

## Dependencies

- `02-settings-shell-visual-redesign`

## Implementation Steps

1. Freshness-check Voice/wake schemas and tests.
2. Map every current Voice option ID to normal Voice or Advanced destination; leave none orphaned.
3. Recompose Voice rendering around task-oriented sections instead of seven technical sub-tabs.
4. Mount wake-word editor inside Voice and preserve its controller/error/focus lifecycle.
5. Register advanced Voice sections for Slice 08 to refine.
6. Replace the editable wake shortcut with a link/read-only effective value until Slice 06 provides its canonical editor.
7. Update unit/runtime/accessibility tests.

## Files Likely Touched

- `jarvis/runtime/control_center.html`
- `jarvis/runtime/control_center_wake_word.js`
- Voice settings rendering/schema projection helpers
- Voice/wake Settings tests

## Architecture Constraints

- Server-described Voice metadata remains authoritative.
- No duplicate editable wake shortcut.
- Restart semantics must remain accurate.

## Automated Validation

- Every persistable Voice option has exactly one destination.
- Wake-word save payload is unchanged.
- Voice settings save behavior and validation remain unchanged.
- Wake detector diagnostics remain reachable under Advanced.
- Audio test still targets selected devices.

## Acceptance Criteria

- A normal user can configure conversation, microphone, output, voice, turns and wake word without opening architecture/diagnostic internals.
- No top-level Wake-word page remains.

## Documentation Updates

Update Voice Settings documentation to describe the new surface destinations without changing underlying contracts.

## Handoff Notes

If Slice 00 finds a new Voice architecture task in flight, coordinate rather than duplicating its contract work.

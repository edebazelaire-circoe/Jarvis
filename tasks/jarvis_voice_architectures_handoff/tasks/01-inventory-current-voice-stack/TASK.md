# Task 01 — Inventory current voice, settings, providers, and baseline

## Goal

Produce an evidence-based map of the current JARVIS voice implementation before refactoring it.

## Context

The transcript proves the current surface is Realtime 2.1 Mini in a reflex-only continuous-brain architecture, but this handoff does not contain the full repository. Exact Gemini model IDs, settings structures, prompt locations, event handlers, and test paths must be discovered rather than guessed.

For this coding task, load and follow `/caveman` and `/coding-guideline` from `~/ai/skills/` before changing code.

## Scope
### In Scope
- Locate current voice session creation and teardown code.
- Locate Realtime and Gemini integrations and record exact supported model IDs/capabilities.
- Locate settings schemas/UI, prompt construction, backend/Claude wiring, sub-agent dispatch, VAD/barge-in logic, speech queue, tracing, and tests.
- Capture current config defaults and migration-sensitive fields.
- Record baseline behavior and known dirty files.

### Out of Scope
- Behavioral refactors.
- Adding GPT-Live.
- Renaming existing public config without a migration plan.

## Dependencies
- Task 00 orchestration initialized.

## Implementation Steps
- 1. Run repository inventory and git status.
- 2. Trace a voice turn end-to-end from microphone input through transcription, reflex output, backend request, speech output, cancellation, and trace emission.
- 3. Trace Settings from persistence/schema to UI controls.
- 4. Identify every prompt layer currently sent to voice and backend models.
- 5. Record exact provider/model capability facts from code/config.
- 6. Create `docs/current-code-map.md` with paths, responsibilities, event flow, and risks.
- 7. Record baseline tests and commands that currently pass.

## Files Likely Touched
- Repository-specific voice runtime modules discovered during inventory
- Settings/config modules
- Prompt construction modules
- Tracing/diagnostic modules
- tests
- docs/current-code-map.md

## Architecture Constraints
- Do not infer Gemini capabilities or model names from general knowledge; use repository evidence.
- Do not modify behavior while mapping it.
- Treat existing uncommitted changes as owned by another workstream unless proven otherwise.

## Testing Requirements
- Run existing focused voice/settings tests without changing expected behavior.
- Record any pre-existing failures separately from new work.

## Acceptance Criteria
- A fresh agent can find every major current voice/settings/prompt component from `docs/current-code-map.md`.
- Exact existing provider/model identifiers and config fields are recorded.
- Baseline test commands and current failures are documented.

## Documentation Updates
- Add `docs/current-code-map.md`; update open questions where repository inspection resolves uncertainty.

## Handoff Notes

This task converts provisional path assumptions into repository facts. Later tasks should use this map.

# Task 12 - Add Telemetry, Rollout Gates, and Repository Documentation

## Goal

Make the new architecture observable, reversible, operationally understandable, and ready for workstation acceptance; then update the Git documentation to match the implementation that actually landed.

## Context

The user explicitly did not want Git documentation updated during planning because the project code will change together with the implementation. This is the correct stage to update it.

## Scope

### In Scope

- Add privacy-safe latency/event telemetry.
- Finalize legacy/continuous rollout switch and defaults.
- Add opt-in live OpenAI smoke test if practical.
- Run Windows workstation acceptance with headphones/speakers if environment permits.
- Document known acoustic echo limitations/fallback.
- Update repository architecture/operations/config documentation.
- Produce final implementation report using the provided template.

### Out of Scope

- Removing legacy mode without acceptance evidence.
- Claiming hardware tests that were not run.
- Implementing multi-agent orchestration.

## Dependencies

Task 11.

## Implementation Steps

1. Load `/caveman` and `/coding-guideline`.
2. Add correlation-based latency metrics listed in `docs/04-testing-and-quality.md` without logging transcript bodies by default.
3. Confirm config names/defaults and rollback path.
4. Run complete automated regression gates.
5. Run opt-in real Realtime smoke test if credentials/network are available; otherwise record not run.
6. On target workstation if available, test headphones, speakers, keyboard noise, background speech, barge-in, long brain work, mute, and reactivation.
7. Record measured/observed echo/VAD behavior; keep fallback mode if needed.
8. Update `README.md`, `docs/ARCHITECTURE.md`, relevant operations/config docs, and final acceptance documentation to match actual code.
9. Write a final implementation report from `templates/final-implementation-report-template.md`.

## Files Likely Touched

- runtime journal/diagnostics modules
- `jarvis/v2_config.py`
- live/integration test configuration
- `README.md`
- `docs/ARCHITECTURE.md`
- relevant operations/config/acceptance docs
- final implementation report


## Architecture Constraints

- Preserve provider-neutral Core boundaries; no OpenAI/Claude/aiohttp/audio provider types inside Core business contracts.
- Reuse existing Jarvis V2 services and `ProtocolEnvelope` rather than creating parallel infrastructure.
- Keep Voice lifetime independent from Core job/brain lifetime.
- Do not persist or expose raw chain-of-thought.
- Add comments/docstrings for concurrency and ownership invariants, not obvious line-by-line narration.

## Documentation Updates

Update task-local handoff notes and code-level docstrings/comments required to make ownership and concurrency clear. Do not perform broad repository documentation rewrites before Task 12 unless a public contract changed and would otherwise be misleading.

## Testing Requirements

- Full unit/integration suite.
- Repository release verifier if still current.
- Opt-in live provider smoke test when credentials are available.
- Manual workstation acceptance where environment permits.

## Acceptance Criteria

- New architecture has traceable latency/interrupt/work events without default content logging.
- Rollback/legacy mode is documented and tested.
- Git documentation describes the implementation that actually exists.
- Unrun hardware/live gates are explicitly marked unverified rather than assumed successful.
- Final implementation report lists remaining risks and multi-agent work as future scope.

## Handoff Notes

Do not remove fallback behavior merely to simplify the final architecture diagram. Reliability on the actual workstation is the release gate.

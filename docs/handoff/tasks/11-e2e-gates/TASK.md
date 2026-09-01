# Task 11 - Run E2E security and quality gates

## Goal

Prouver la V1 par scenarios reproductibles et laisser un rapport final exploitable.

## Context

This is the release gate for prototype V1. It should find integration gaps rather than add features.

## Scope
### In Scope
- Charger `/caveman` et `/coding-guideline`.
- Run unit/integration/E2E tests.
- Execute demo scenarios.
- Check logs/privacy.
- Check network behavior Barehands.
- Check action policy.
- Measure latency checkpoints.
- Produce final implementation report.

### Out of Scope
- No feature expansion.
- No V2 work.

## Dependencies

Tasks 00-10 complete.

## Implementation Steps

1. Run full test suite.
2. Execute scenarios A-E from `docs/07-v1-demo-scenarios.md`.
3. Verify no runtime CDN/network requests from board except intended provider backend calls.
4. Verify no provider key reaches browser.
5. Verify forbidden tools cannot be invoked.
6. Record latency metrics.
7. Record known issues and deferred V2 items.
8. Fill final report template.
9. Mark TODO complete only if all blocking criteria pass.

## Files Likely Touched

- `tests/e2e/*`
- `FINAL-IMPLEMENTATION-REPORT.md`
- `tasks/TODO.md`
- docs for known issues

## Architecture Constraints

Do not waive a security gate to make the demo pass. If a gate fails, leave task unchecked and document blocker.

## Testing Requirements

- Full automated suite green or explicitly documented non-blocking skips.
- Voice/board/memory scenario passes.
- No general shell/action escape exists.
- No sensitive default log content.
- No remote UI dependencies.
- Restart persistence passes.
- Final report includes exact test commands and results.

## Acceptance Criteria

- All blocking E2E scenarios pass.
- Security checks pass or the V1 remains explicitly unreleased.
- Measured latency and known limitations are recorded.
- `tasks/TODO.md` and final report agree on completion status.

## Documentation Updates

Finalize docs and decision log with actual implementation deviations.

## Handoff Notes

The final report is the handoff for V2 planning. Include measured rather than claimed latency where possible.

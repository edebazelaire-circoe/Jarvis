# Task 09 - Harden and integrate Barehands

## Goal

Brancher le board gestuel a Jarvis tout en supprimant les principaux risques de la demo upstream.

## Context

Barehands is useful and portable but currently loads runtime assets from public CDNs and exposes a localhost command endpoint without Jarvis session auth.

## Scope
### In Scope
- Charger `/caveman` et `/coding-guideline`.
- Work from pinned upstream snapshot.
- Vendor Three.js/MediaPipe/WASM/model.
- CSP.
- Tokenized mutating command endpoint.
- Jarvis BoardClient.
- Health check.
- Preserve camera/gesture behavior.

### Out of Scope
- General scene vision.
- New gesture vocabulary unless required by integration.
- Major UI redesign.

## Dependencies

Tasks 01, 02, 07 complete.

## Implementation Steps

1. Mirror all runtime remote assets locally with provenance/checksums.
2. Replace imports/URLs.
3. Add CSP and confirm no network requests during normal board use.
4. Generate per-launch session token in Jarvis.
5. Require token for `/cmd` and other mutating endpoints.
6. Implement `BarehandsBoardClient`.
7. Wire `board_present` through broker/tool dispatcher.
8. Add service health probe.

## Files Likely Touched

- `third_party/barehands/*`
- `jarvis/adapters/barehands_board.py`
- `jarvis/security/session_token.py`
- integration tests

## Architecture Constraints

Do not expose OpenAI key/browser secrets. Keep service loopback-only. Upstream modifications remain clearly marked/provenanced.

## Testing Requirements

- Browser dev/network test shows no external runtime request.
- Missing/bad token gets 401/403 for command.
- Valid token can `present` card.
- Path traversal tests still pass.
- Hands can still move/open card in manual smoke test.

## Acceptance Criteria

- Barehands starts fully offline after initial install.
- Authenticated `board_present` works from Jarvis.
- Unauthenticated mutations are rejected.
- Existing hand gestures remain usable in manual smoke test.

## Documentation Updates

Update third-party manifest with modifications and vendored assets.

## Handoff Notes

If modifying upstream server is awkward, put a Jarvis-authenticated proxy in front and make the raw server inaccessible except via a private randomized port; direct hardening is preferred.

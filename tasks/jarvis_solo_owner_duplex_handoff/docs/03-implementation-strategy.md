# 03 — Implementation Strategy

## Phase A — Protect the current good behavior

1. Pin regression tests around current AEC, playback ordering, barge-in, semantic VAD, transcript filtering, and contextual acknowledgement.
2. Introduce contracts/configuration without changing runtime behavior.
3. Run speaker verification in shadow mode and collect hardware metrics.

Reason: the latest `main` fixed real race conditions. Avoid mixing identity-gating changes with another audio-concurrency rewrite.

## Phase B — Enforce Solo Owner

4. Add local owner profile/enrollment adapter.
5. Add rolling owner verification to capture.
6. Change Solo Owner barge-in authority: owner confirmation, not raw near-end.
7. Expand ring buffer and make provider speech start advisory.
8. Gate silent-JARVIS input too, so non-owner speech never reaches addressing/brain in Solo Owner.

Roll out behind settings/feature flag until workstation acceptance is green.

## Phase C — Benchmark engines

9. Create replayable benchmark cases from consented/local recordings or synthetic fixtures.
10. Compare candidate verifiers using identical preprocessed audio.
11. Keep the best quality engine that meets deployment/licensing constraints. Do not encode vendor semantics above the adapter boundary.

## Phase D — Move task truth into Core

12. Define normalized work contracts.
13. Add Core state store and events.
14. Feed Claude `AgentTaskTracker` observations into Core.
15. Feed other providers only when their event formats are actually verified.
16. Give the brain a bounded current-work snapshot.
17. Move UI projection to Core, retaining a compatibility path during migration.
18. Add speech/notification policy for meaningful work-state changes.

## Phase E — Acceptance and cleanup

19. Hardware benchmark with speakers, headset, office conversations, overlap, long sessions.
20. Remove compatibility shortcuts only after measured parity.
21. Update operations and rollout docs.

## Rollback strategy

Each behavior-heavy phase must keep a simple rollback:

- `solo_owner` can be disabled independently of `continuous_brain`.
- speaker verifier can run `shadow` without enforcement.
- existing near-end/provider confirmation path remains available for non-Solo modes during rollout.
- Core work-state migration keeps the current task UI endpoint until the new Core projection is validated.

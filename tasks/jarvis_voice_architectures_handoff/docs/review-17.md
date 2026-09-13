# Task17 orchestrator review

Accepted 2026-09-13 with no open P1/P2 finding.

The review challenged opening a new billable frontend before the old one is
terminal and treating copied UI/provider state as conversation truth. The
coordinator snapshots Core before teardown, checks local pending ownership and
Core's durable Live lease after teardown, and does not restart on uncertainty.
The handoff carries only IDs, counts and fingerprints. The replacement re-reads
Core through the canonical context selector, so unplayed assistant text cannot
enter history during switching.

Adversarial tests cover idempotent commands, stop failure, unresolved Live,
cross-process conversation continuity, active/blocked task projection,
terminal-task exclusion, prompt-text exclusion, clean supervisor restart
classification, the full architecture sequence and a model restart within
Simple. Extended test registries remain saveable without claiming an
unsupported production adapter.

The first whole-suite run exposed one P2 compatibility edge: Gemini Settings
can temporarily retain an empty model while the user completes the form, but
the switch request schema correctly requires a concrete model. Settings now
skips switch creation for that non-runnable projection rather than rejecting
the save or stopping the current frontend. The failing case and 62 neighboring
switch/configuration cases passed before the clean final release.

Sub-agent review remained unavailable because the workspace agent pool reported
exhausted credits. The orchestrator completed review locally and required the
broad 1123-test gate plus the full release gate.

# Task16 orchestrator review

Accepted 2026-09-13 with no open P1/P2 finding.

The review traced every UI state to Task13's Core record and challenged the
failure boundaries that could hide billing: Control Center restart, Core read
failure after a known session, Core unavailable before a first read, Voice
offline, a stale stop command, an accepted command without terminal evidence,
an unconfirmed provider close and a mode/settings change during the session.
None of those paths asserts STOPPED.

The browser projection was executed under Node for active, stopping, uncertain
and terminal inputs. Python tests cover authoritative elapsed time, provider
usage, strict pricing metadata, matching idle data, retained stale state,
idempotent request creation, Voice consumption and cross-session rejection.
The existing Control Center, application-loop, idle and continuous-Live tests
remain green.

Sub-agent review could not be resumed because the workspace agent pool reported
exhausted credits. The orchestrator therefore performed the Task16 adversarial
review locally and required both the broad Live/Control Center gate and the full
release gate before acceptance.

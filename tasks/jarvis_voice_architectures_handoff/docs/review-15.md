# Task15 orchestrator review

Accepted 2026-09-13 with no open P1/P2 finding.

The review compared registry programs to every inventoried send site and checked
that default resolution preserves the previous byte-for-byte prompt material.
Adversarial cases cover malformed/versioned documents, unknown IDs, stale bases,
concurrent editors, writer failure, read-only layers, private text in diagnostics,
dynamic request bounds, provider-hidden disclosure and architecture-scoped UI
projection.

The first whole-suite run exposed two review findings. Dynamic Luna JSON used the
32 KiB static-prose limit even though the real adapter already admits up to a
131072-byte request; the registry now uses its bounded document limit for dynamic
rendering while the adapter retains the stricter pre-send byte check. A legacy
test replaced `agent.ask` on a real agent instance, so method-presence detection
incorrectly inferred support for prompt evidence; dispatch now checks the actual
call signature. Both repairs were reproduced by the failing cases before the
final release passed.

Saved, sent and acknowledged remain separate. Settings writes `saved_only`.
Provider/CLI evidence is emitted only after the corresponding transport/stdin
write. Realtime session startup is acknowledged only after its matching event.
Claude resumed-session behavior is not upgraded to an acknowledgement claim.
No prompt or transcript text is stored in normal prompt telemetry.

Independent Task15A persistence review produced 26 adversarial tests and no
P1/P2. Further sub-agent review was unavailable because the workspace agent pool
reported exhausted credits, so the orchestrator completed 15B/15C review locally
and required a clean full release gate.

# Task05 parent review tracking

Accepted by parent, 2026-09-12. All checks below were reviewed against the final implementation and evidence; the explicit Task07 device boundary remains future work.

| Area | Required check |
|---|---|
| Production composition | Real OpenAI factory/runtime uses VoiceFrontend, a single provider reader and canonical Core ingress. Gemini/legacy compatibility remains explicit. |
| Lifecycle failure | Connector, update and ACK failures settle into a truthful terminal/uncertain lifecycle and finish the event iterator. Authentication/transport errors are not mislabeled timeout. |
| Cleanup ownership | Stop is idempotent under concurrency and caller cancellation. Startup cancellation cleans owned WS/client resources; injected shared HTTP remains owned by its caller. No unbounded forgotten cleanup. |
| Overflow | Bounded queues preserve an explicit overflow error and terminal lifecycle; one must not overwrite the other. Slow Core cannot silently lose transcript/terminal observations. |
| Usage | Per-response deduplication produces truthful cumulative counters; a missing response/field must not become a known underestimated total. ASR usage stays distinct. |
| Typed operations | Transport failures become stable typed outcomes while CancelledError propagates. Quiet insertion never requests a response. |
| Tool data | Bounded JSON rejects exponent overflow to infinity as well as NaN/Infinity. Malformed JSON cannot become a valid empty argument object. Tool authority remains in the existing gate. |
| Identity | Local output, provider response, provider item and provider input remain distinct. Tool/output items must not be mislabeled input. Multi-item response evidence must survive without correlation conflicts. |
| Observation order | One merged dispatch sequence; no PCM over Core HTTP; receipt/generated evidence remains distinct from delayed device evidence. |
| Input admission | Provider finality is not application admission. Rejected ambient/failed input must not become accepted intent or leave unbounded protected provisional records; test more than 64 rejected segments followed by a real accepted turn. |
| History | One migrated writer, with intended/generated/confirmed separation. No backend public summary or partial intended text promoted to heard context. Projection order follows heard order. |
| Recovery | No full JSONL scan per phrase. Pending exact history range survives failure before/after archive write; a longer confirmed prefix cannot duplicate the old prefix. |
| Retention | Bounded ledger memory preserves active work and saves eligible inactive state before eviction; failed persistence cannot claim success. |
| Device proof | Task05's real path is conservative PARTIAL/UNKNOWN until Task07's actual device drain boundary. Injected COMPLETE tests do not establish hardware behavior. See Decision21. |

Required gates: agent focused tests and production composition, parent independent targeted regressions, then the broader release check for this integration milestone. No provider/hardware access is inferred from fake transport/device tests.

## Whole-suite review

First parent release run: 2101 passed, 12 failed, 4 skipped and 1 teardown error (239.01s). Ten app tests returned an opaque object from the provider connection double, and the dotenv test returned an unconfigured AsyncMock; neither supplied the now-required startup ACK/close lifecycle. The remaining AST check expected the old direct app-to-provider call. Repair must retain the real composition chain and every existing settings, model, owner-authorization and credential-privacy assertion. Acceptance remains pending a clean release rerun.

Resolved: provider-boundary doubles now supply ACK and owned close; factory/frontend remain real. The AST check follows app → facade → canonical frontend → existing provider connector. All previous selection/owner/privacy assertions remain. Focused repair gate:54 passed (8.01s). Independent parent rerun of `scripts/verify_release.py`, with warnings as errors and function-scoped asyncio fixtures: **2113 passed, 4 skipped (226.88s); Release verification passed**. Skips are two opt-in provider calls, POSIX-only signal behavior and unavailable symlinks. `git diff --check` passed. No live account/device quality claim.

Parent additionally inspected source/work lineage, authenticated ingress and sole assistant-history writer, exact pending range replay, SQLite lock retention under repeated cancellation, canonical observation failure reconciliation and pending runtime cleanup. Parent-owned production composition tests exercise real activation/mute, facade, adapter and authenticated Core with controlled transport/device. No outstanding Task05 acceptance finding remains.

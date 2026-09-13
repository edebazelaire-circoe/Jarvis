# Live delegation authority — preparation for Tasks 11–12

Read-only inspection and proposal, 2026-09-12. This note changes no locked decision or slice status. No provider session, CLI agent turn, credentials inspection or billable request was performed. Installed CLI `--version`/`--help` and public official documentation were read.

Implementation update: this remains the historical preparation plan. Task12C now supplies typed speculative Job provenance and an enforced restricted native-Claude execution profile; Task12D supplies canonical flush, bounded delegation polling and same-session result injection. Unsupported profiles still return durable unavailable. The action-admission restrictions remain in force. Current evidence and remaining limitations: [Task12 implementation](12-implementation-evidence.md), [review](review-12.md).

## Recommended boundary

Treat a Live delegation as a request to examine a bounded context snapshot. Core can schedule useful, restricted analysis before any transcript is committed. Such a job produces facts, alternatives, a draft or an action proposal; it cannot create its own execution authority. Application admission and existing action policy remain separate decisions.

Do not synthesize a user commit to satisfy the current task-record schema. Extend Task11's job provenance explicitly before Task12 integration. Reuse Core JobService and independently owned instances of the existing CLI wrappers, as Decision20 requires. A prompt saying “analysis only” is insufficient when the child retains tools that can modify files, browser state or external services.

## Evidence and current gaps

| Inspected contract | Consequence for the implementation |
|---|---|
| `VoiceDelegationRequested(context_revision)` plus `VoiceCorrelation.provider_delegation_id` | Already models a trigger without invented text. Correlation permits `turn_id=None` and `task_id=None`. |
| `UserTranscriptDelta` / `UserTranscriptRevised`; `UserTranscriptCommitted(source=APPLICATION)` | Provisional evidence and an explicit application admission boundary exist as distinct concepts. APPLICATION cannot be used as a label for an inferred provider final. |
| `VoiceTaskRecord.source_turn_id`, `VoiceConversationState.update_task`, snapshot validation | Task references currently require a retained committed user turn. An uncommitted Live analysis job cannot be inserted here. |
| `VoiceConversationState.recent_context()` | Projects committed user text and independently confirmed heard words. It deliberately omits provisional Live input; using it alone yields an empty current request in the first Live conversation. |
| `VoiceObservationDispatcher` | Batches observations asynchronously. Provider receipt does not guarantee that Core has applied the corresponding deltas when a separate job request arrives. |
| `BrainTurnInput` | Means a complete authoritative user turn. Do not feed it a guessed task or a partial transcript merely to reach the existing backend. |
| `Job` / `JobService.submit` | Durable job identity and optional conversation/correlation already exist without requiring a voice turn. Generic agent worker and protocol ingress still need Task11. |
| `CoreToolRouter.call` | Calls policy with `explicit_request=True`; merely reaching this endpoint already assumes caller admission. The router is not a transcript/owner-admission substitute. |

Source files: `jarvis/domain/voice_events.py`, `voice_frontend.py`, `voice_state.py`, `v2.py`; `jarvis/core/voice_state.py`, `voice_ledger.py`, `v2_tools.py`; `jarvis/runtime/voice_observations.py`, `realtime_frontend_session.py`. See also [backend inventory](nonblocking-backend-integration-notes.md) and [provider contracts](verified-provider-contracts.md).

Live supplies `session.delegation.created` with provider event ID, timeline offset and delegation ID/target, but no task text or tool arguments. Input transcript deltas have intervals and no authoritative final turn event. Neither offset, silence nor a stable-looking transcript establishes consent. The application must assemble context and enforce permissions. This is the documented client-delegation design, not a missing server tool to emulate. [Official Live delegation guide](https://developers.openai.com/api/docs/guides/live-delegation), [WebSocket guide](https://developers.openai.com/api/docs/guides/voice-websockets?api=live).

## Bounded, revision-tagged work projection

Proposed request metadata, owned by Core, not a claimed existing wire schema:

| Field/group | Meaning |
|---|---|
| `conversation_id`, frontend incarnation, provider session/delegation IDs | Exact identities already known. Provider delegation ID is not a JARVIS task or turn ID. |
| `source_snapshot_revision`, source event sequence | Core's applied snapshot watermark when the work projection is captured. Adapter `context_revision` alone is not proof of this watermark. |
| Input dependencies | Retained transcript/group IDs, each revision, exact bounded text and `committed` flag; observed intervals when available; explicit omissions/unknown ordering. |
| Admission evidence reference | Application-owned speaker/addressing/admission epoch and allowed data/work scope. Text cannot self-assert these fields. |
| Context | Recent admitted context, genuinely heard assistant words, relevant verified job facts, pending action references and any provisional user continuation separately labelled. |
| Work intent | An explicitly tentative interpretation with ambiguities and allowed result kinds. This is application/analysis output, never provider-supplied task text. |
| Execution scope | Registered worker kind, approved read capabilities, concurrency/cost limits and cancellation ownership. No arbitrary command accepted from Live. |

Suggested initial projection budgets: at most 16 recent context messages, 8 provisional transcript records and 8 relevant job references; 16,384 total text characters including a maximum 8,192-character current input. These are proposed application bounds, not provider limits. Preserve full retained record identities/revisions and report omitted context; do not silently truncate away a correction and execute the surviving prefix. Raw PCM, secrets, unrelated history and unconstrained tool output are excluded. Insufficient context yields a needs-context result or a bounded pending trigger, not fabricated content.

Admission and projection run in the controller/Core path. The adapter emits metadata immediately; it does not await heavy work in the socket reader. A serialized observation/submission barrier must ensure relevant already-received deltas reach Core before projection, without claiming that all provider audio has been transcribed. If text arrives later, a still-pending trigger can be reconsidered against a newer projection.

Use dependency revisions and an application intent generation for freshness. Do not invalidate every result because the global snapshot revision changed: output audio, usage or unrelated activity can advance it. A user correction affecting the source hypothesis must mark that analysis stale or superseded before an action proposal is consumed. Keep the original immutable source projection and any successor relation; do not rewrite an old job's originating intent to match a new request.

## Two admission levels, one Core owner

1. **Admit input for analysis.** Existing audio/owner and addressing rules decide whether observations may reach conversational state and the backend. In SoloOwner, a provider transcript or delegation is not identity evidence; preserve pre-upload and authorization-loss behavior. Open-room configuration retains its own explicit policy. Ownership of this decision stays in the application, not the model.
2. **Admit a concrete request/action.** The application binds exact current intent and arguments to real user authorization, then invokes the existing Core tool/action policy. A retained provisional “oui”, a pause, an assistant claim that confirmation occurred, or a delegation event cannot resolve a pending action.

There is no provider-supported finality event to fill the second step automatically. A deliberate application submission/confirmation of the concrete request can be the explicit boundary; emit an APPLICATION commit only if the application actually accepts that complete text at that revision. If a suitable trusted UI/explicit input boundary is not wired for Live yet, action proposals remain pending. This note does not claim that such a Live UI flow already exists, and does not require an extra confirmation for work already authorized by the user.

Core's existing policy does **not** require a new yes/no for every mutation: calendar create/update and reminders can execute after an explicit unambiguous request; calendar delete/invite and Drive writes/sharing require confirmation. Preserve those distinctions. For required confirmation, use the existing action ID, stored arguments, expiry and yes/no resolution; the application must establish authorized origin before calling the endpoint. Do not pass every model-generated proposal through `CoreToolRouter.call`, which assumes `explicit_request=True`. See `jarvis/security/v2_policy.py` and `jarvis/core/v2_tools.py`.

## Real useful jobs and the available CLI restrictions

| Work class | Useful result | Admission/executor condition |
|---|---|---|
| Analysis of supplied bounded facts | Compare options, calculate from supplied numbers, summarize results, identify ambiguity, prepare a draft or proposed arguments | Can run on provisional intent with a genuinely tool-free/restricted worker. No claim of current external facts without retrieval. |
| Read research | Retrieve authorized facts or inspect allowed repository files, with sources and uncertainty | Only through enforced read capabilities, defined data/network scope and the same owner admission. Read-only filesystem access alone does not make remote tools read-only. |
| Action preparation | Structured proposal tied to current source dependencies | Produces data only. Existing Core gate decides execution after actual admission/required confirmation. |
| Authorized work | Execute within an already admitted request and existing configured permissions | Uses normal authorized job scope; a later Live delegation cannot expand it. |

Installed help checked: **codex-cli 0.154.0**, **Claude Code 2.1.269**. No inference turn was launched.

Codex supports `read-only` sandbox and separate approval policy; official docs describe read-only noninteractive runs with approvals `never`. Network access and app/MCP permissions are separate concerns. The current wrapper passes only `sandbox_mode` for restricted modes, inherits other configuration, and defaults to `danger-full-access`; it does not establish an analysis profile with verified effective network/tool restrictions. Windows enforcement must be tested for the worker actually composed, not inferred from an argv string. [OpenAI approvals and security](https://learn.chatgpt.com/docs/agent-approvals-security).

Claude offers `--tools ""` to remove built-in tools; this does not remove MCP tools. `--restricted` removes command/code tools and WebFetch unless explicitly restored and rejects bypassPermissions. MCP needs separate exclusion; `--safe-mode` disables customizations but managed policy still applies. These capabilities support a candidate analysis profile; none alone proves zero side effects. [Official CLI reference](https://code.claude.com/docs/en/cli-reference). Plan mode permits read-only exploration and, where available, classifier-approved commands: its label is not a guarantee that every possible external operation is harmless. [Official permissions reference](https://code.claude.com/docs/en/permissions).

Current `ClaudeLocalAgent.start` always adds `--chrome`, the conversational system prompt and routing settings, and defaults to bypassPermissions. It exposes no tools/MCP restriction argument. A worker-specific launch profile is therefore a real bounded Task11 gap. Reuse the wrapper/process ownership, but intersect capabilities with the admitted scope and verify effective tools, settings/hooks, MCP, Chrome, shell and descendants. Preserve the configured provider/model and normal authorized-work settings; never silently substitute a different backend because it is easier to restrict. If that backend cannot enforce a speculative profile, return analysis-unavailable or wait for admitted work instead of launching a permissive speculative child.

The smallest useful first profile is analysis of supplied context with external tools disabled, owned by the registered Task11 worker. Read research can be enabled only when the selected executor's actual allowlist and network boundary are verified. This yields real backend results while keeping the frontend responsive; it does not require a new server-side Live tool or a second agent framework.

Inventory drift: installed Claude help now advertises native `--bg` and ID-based `agents/logs/stop`. The repository wrapper does not use them. This is not evidence of durable Jarvis integration, isolated cancellation or permission enforcement, and does not change Decision20.

## Correlation, persistence and result delivery

Keep a Core-owned durable mapping from `(conversation, frontend incarnation, provider session, provider delegation ID)` to an actual accepted `Job.id`, source projection and admission scope. Allocate a local request/analysis ID for intake if needed, labelled as such. Publish a task ID only after JobService has accepted/persisted that job. Concurrent duplicate triggers/retries must converge on the same acceptance; a lost submit response must be retried with the same idempotency identity, not launch again.

Prefer a minimal additional **opaque Core job reference plus explicit source-snapshot provenance** for advisory work. Preserve the existing committed-source invariant for `VoiceTaskRecord`; do not insert a synthetic user row, borrow a nearby committed turn, reuse the delegation ID as a turn ID, or fabricate `BrainTurnInput`. Task11 must specify where its bounded advisory references/results enter canonical conversation state, with codec/migration/retention coverage if the snapshot changes. Merely hiding them in arbitrary Job payload while reporting Task11's state integration complete is insufficient.

When a request is later actually admitted, relate authorized work to the existing analysis by an explicit `derived_from` reference; retain both origins. A correction can cancel/supersede speculative work, but cancellation evidence and result freshness are separate: even a process that cannot be stopped immediately must not publish its stale proposal as current authority.

Results remain durable Core job facts across frontend replacement. The controller checks source dependency freshness, current admission and active frontend before selecting quiet or speakable delivery. For the same Live session, preserve the original delegation ID on thinking/commentary append; a replacement session cannot inherit that provider ID. Any cross-session reinjection uses supported uncorrelated context and a fresh controller decision, without claiming the user heard the old result. Each append stays within the provider's 500-token content limit. ACK confirms append processing, not speech, action execution or playback; quiet context can influence later speech. [Official Live delegation guide](https://developers.openai.com/api/docs/guides/live-delegation).

## Issues to resolve before Task12 acceptance

- **Committed-source mismatch:** extend provenance/state deliberately before testing uncommitted Live delegation. Keep snapshot evidence non-authorizing.
- **Missing restricted executor profile:** Task11 must establish actual permissions for speculative work and a result-only prompt instead of the current conversational speech/delegation prompt. A broad child plus a fake passing test is insufficient.
- **Action ingress assumption:** `explicit_request=True` in CoreToolRouter requires an upstream gate that Live deltas/delegation do not currently supply. Define the supported explicit application boundary; no silence-generated commits.
- **Task12 wording:** “map ... final state” cannot mean nonexistent transcript finality, and “actual output transcript ... spoken ledger” must retain generated versus heard evidence under Decisions19/21. This is a scope clarification to record during implementation, not a provider event to invent.
- **Projection ownership:** atomically capture applied Core dependencies despite batching, preserve rejected/unknown owner state, and define bounded pending triggers rather than unbounded buffering.

Focused acceptance cases: first-session deltas + delegation yield a real restricted analysis job with no commit; empty transcript waits/returns insufficient context; two concurrent identical triggers launch once; a late “quoique non” makes the older result stale; malicious provisional text cannot enable shell/MCP/browser writes; provider or background-job text saying “yes” cannot resolve an action; a concrete admitted request follows the existing execute/confirm distinction; a slow independent job leaves subsequent conversation usable; frontend replacement preserves its durable result but does not append an old provider delegation ID. Verify the production composition and effective executor boundary, not only tests that inject desired terminal events.

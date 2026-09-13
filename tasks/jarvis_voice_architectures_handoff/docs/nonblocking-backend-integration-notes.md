# Nonblocking backend integration preparation — Task 11

Read-only inspection, 2026-09-12. This note does not implement or complete Task11. No jobs, CLI agents, network calls or tests started for this preparation.

## Conclusion

`JobService.submit` is the existing durable, immediate-return task primitive. It runs a registered worker independently of voice lifetime, but **production registers only `memory_maintenance`**, and the local protocol exposes no generic job submit/status/cancel API. There is currently no general-purpose research/subagent entrypoint that both returns a durable task ID immediately and guarantees independence from the conversational Claude/Codex lock.

Claude native `Agent(run_in_background=true)` can do independent work once the conversational CLI chooses to launch it. Jarvis's tracker observes that launch; it does not issue it. Existing system instructions request delegation but cannot provide a structural latency guarantee. Wrapping the same `/api/agent/ask` call in another asyncio task would preserve the underlying bottleneck.

There is one additional genuine immediate independent entrypoint: `SelfDevelopmentService.start`, for explicitly enabled code work. Its narrow authority, worktree/validation/commit/push/deploy semantics make it unsuitable as a generic research executor.

## Existing immediate task primitive

Location: `jarvis/core/v2_services.py::JobService.submit` (around561).

```python
job = await core.jobs.submit(
    Job(
        kind="registered_worker_kind",
        payload={...},
        requested_by_conversation_id=conversation_id,
        idempotency_key=stable_request_key,
    ),
    work_id=originating_work_id,
    correlation_id=originating_turn_correlation_id,
)
# job.id exists now; worker completion is not awaited.
```

Exact domain: `jarvis/domain/v2.py::Job` has `id`, `kind`, `status` (initial pending), `requested_by_conversation_id`, `payload`, `result`, `error`, created/started/completed timestamps and `idempotency_key`. `JobService.submit` rejects an unregistered kind, searches existing jobs by idempotency key, saves pending job to `StateRepository`, links work/correlation IDs, and owns `_execute` in `_running`. It waits for persistence/listing, not heavy execution. Current dedup is a list/check/save sequence, not a concurrency-safe transaction; future concurrent ingress needs a focused duplicate-submission regression.

Worker port: `jarvis/ports/v2.py::JobWorker.execute(job) -> dict[str, object]` and `cancel(job_id)`. Optional `ProgressReportingJobWorker.execute_with_progress(job, JobProgressSink)` replaces execute; `JobProgressSink.emit(job_id, JobProgress)` accepts phase/fraction/public_summary. These are factual results/progress, not speech requests.

Composition: `jarvis/core/v2_app.py::JarvisCoreApplication.__init__` owns JobService and injects the workers map. `jarvis/app.py::_run_core_v2` currently constructs only `{"memory_maintenance": MemoryMaintenanceWorker(...)}`. `core/memory_maintenance.py` is the sole production generic JobWorker implementation found. It is not an agent worker.

Status storage is `SQLiteStateRepository.save_job/list_jobs`; no separate public JobService.get exists. Running completion persists result and timestamps. WorkStateStore projection receives `core.jobs` observations and publishes `core.work.updated`; this view is memory-only and is not a replacement for durable job result storage.

### Events, cancellation and lifetime

| Path | Existing behavior |
|---|---|
| Progress | `brain.work.progress`: payload `work_id`, `job_id`, `phase`, `fraction`, `public_summary`; envelope carries conversation/correlation. Coalesced to default minimum0.5s between published updates. |
| Completion | `job.completed`: payload job_id/kind/result; envelope conversation/correlation. Result persisted before event. No speech request is emitted by JobService. |
| Failure | `job.failed`: job_id/kind/error_class, conversation/correlation; detailed error retained in persisted Job. |
| Cancel | `JobService.cancel(job_id)` cancels asyncio task then calls every registered worker's cancel. `_execute` persists CANCELLED and work observation. No dedicated `job.cancelled` terminal envelope currently exists. Worker cancel failures are swallowed; cancellation acknowledgement is not proof all external work stopped. |
| Work cancel | `cancel_work(work_id)` targets linked running jobs and returns IDs. `BrainOrchestrator` uses this existing `WorkCanceller` seam. |
| Voice mute/restart | Does not call Core JobService.stop; tasks survive while Core stays alive. Same applies to frontend replacement if switch only owns frontend. |
| Core stop/restart | Stop cancels owned tasks. Recovery marks previously RUNNING durable jobs INTERRUPTED; it does not restart them. Survives frontend restart is not durable execution across Core crashes. Pending jobs interrupted before execution need explicit recovery review. |

`JarvisCoreApplication._notification_loop` converts job terminal events into desktop notifications. `_brain_notice_loop` separately calls `BrainOrchestrator.announce_notice` for spontaneous CLI answers, which currently generates speech. New frontend result routing must not inherit this automatic speech path for every completion.

## Transport boundary currently missing

`jarvis/protocol/server.py::_app` exposes conversations/context/turns/brain-turns, tools/actions confirmation, `/v1/work/observations`, `/v1/work/snapshot`, `/v1/events`. There is **no `/v1/jobs` route**. `LocalCoreClient` accordingly has no generic task-submit/cancel/status method. Existing work-observation ingress only reports state and does not execute work.

Core protocol uses loopback bearer credential and protocol-version check. New task ingress should extend this existing boundary with strict typed validation, stable IDs/idempotency, source-turn/conversation lineage and a registered worker kind allowlist. Do not accept arbitrary executable/shell command in a generic task request.

`CoreToolRouter` (`core/v2_tools.py`) is the existing application action policy/confirmation boundary for calendar/Drive/reminders. It is not a generic agent dispatch router. `V2ActionBroker` decides execute/clarify/confirm/deny; pending confirmations expire and are resolved via `/v1/actions/{action_id}/confirmation`. A delegated request must retain these permissions rather than interpreting model output, partial transcripts or delegation metadata as authorization.

## Why current agent routes do not solve the guarantee

| Callable | Exact effect and limit |
|---|---|
| `ControlCenterBrainBackend.run_turn[_with_context]` | `_run` emits accepted, awaits `_ask(text, context)` to `/api/agent/ask`, then `_settle_success` emits SPEECH and COMPLETED. Both lock contention and automatic result speech conflict with Task11's strict result-only path. |
| `/api/agent/ask` | `{text, timeout_s?, context?}`; builds `build_agent_brief(context,text)` then awaits selected `self.agent.ask`. Timeout clamp5–1800s. Returns complete outcome, no background job handle. |
| `ClaudeLocalAgent.ask` | `_ask_lock` spans send plus complete result wait. Per-message UUID improves attribution, not independent execution. |
| `ClaudeLocalAgent.send` / `/api/agent/send` | Writes user message into same persistent CLI stdin; returns agent snapshot, not durable task ID. CLI may merge messages into one turn. Bypassing ask lock does not create an independent worker and risks response attribution. |
| `CodexLocalAgent.ask` | `_turn_lock` spans `_run_turn`; CLI `codex exec [resume session_id] --json ...` with stdin prompt. |
| `CodexLocalAgent.send` | Creates one `_background_turn`, which calls the same ask lock; rejects another background turn. It does not release the conversational lock for other asks. |
| `AgentTaskTracker` | Parses native task/tool events, correlates IDs and keeps observable task state. `subscribe` observes mutations; `process_stopped` marks subtasks interrupted. No launch/cancel executor. |
| `routing_hook.py` | Claude `PreToolUse` hook for Agent/Task. Enforces model routing when Claude already decided to launch; no Jarvis task dispatcher. Comment explicitly says Jarvis does not launch these subagents. |

Correction to Task01 map: its Codex “app-server” description was inaccurate. `codex_local.py::_turn_command/_run_turn` launches CLI `exec/resume` subprocesses, one per turn, retaining session ID. No app-server transport is used here.

Permissions belong to configured agent settings: Claude start uses `--permission-mode`; Codex `_turn_command` uses configured sandbox mode (existing danger-full-access path opts out of approvals). Task11 must preserve those existing choices, not grant broader permissions merely because work moved to background. `agent.stop` kills the selected whole process/session, not one native subagent; it cannot stand in for targeted task cancellation.

## Narrow independent code-work entrypoint

### Existing CLI instance isolation contract

Both existing constructors accept keyword-only `runtime_root: Path`, `cwd: Path`, `command` (`claude`/`codex` default), `permission_mode`, and `model` (empty preserves CLI default). Each new instance starts with `session_id=None` and independent locks/state. A worker must not copy the conversational session ID or use its shared instance. Claude `start(resume=False)` prevents intentional resumption; Codex first exec has no resume until that instance receives its own session ID.

`runtime_root` controls RuntimeJournal and Claude routing-hook settings path. Per-job diagnostics isolation therefore needs routing settings supplied deliberately; blindly assigning a new empty root would lose the configured routing policy. No separate Jarvis session-id persistence file was found in these wrappers: CLI history is retained by CLI itself and the wrapper holds session ID in memory. `cwd` determines repository instructions and file authority; do not switch arbitrary workspace or bypass existing code-work worktree requirements. Bound concurrency outside the wrappers; their locks only serialize calls on one instance.

For a worker-owned instance, targeted cancel can call that instance's `stop()`, never the Control Center main agent. Claude stop aborts pending ask, terminates process, kills after3s, cancels and joins readers. Codex stop terminates/kills its process after3s; direct `ask` cancellation enters `_run_turn` cleanup that awaits process exit, so do not await a canceled ask indefinitely **before** arranging process termination. Track the owned process/job association, terminate first or concurrently as appropriate, then await task/reader cleanup with bounded evidence. Wrapper stop does not by itself prove every descendant native subagent was reaped; tests/Windows process ownership must establish that guarantee before reporting complete cancellation.

`runtime/self_dev_service.py::SelfDevelopmentService.start(request, profile="code") -> self_dev.Job` saves a job in `runtime/self-dev`, owns `_work` in its task map, and returns `job_id` immediately. Control Center `POST /api/self-dev` accepts `{request, profile?}` and returns `{ok:true,job:...}`; GET returns jobs/running state. Construction uses separate `SelfDevelopmentRunner`, no conversational ask lock.

This requires existing `selfdev.enabled` gate; runner leases worktree, edits, validates, commits and pushes candidate. Separate auto_deploy setting can trigger deployment. `self_dev.py::_edit` invokes CLI with its own documented authority. Do not route ordinary lookup/research here or toggle its gate. There is no generic cancellation/status event seam suitable for arbitrary back-brain tasks. Reuse this exact service only for user-authorized self-development, preserving its existing gate and deployment behavior.

## Recommended bounded Task11 implementation

1. Reuse Core JobService for acceptance/idempotency/durable records/progress/lifetime; add a neutral typed backend task submission/status/cancellation port and corresponding LocalCoreClient/server endpoints if frontend runs outside Core. Keep its owner in Core, never VoiceFrontend.
2. Register a real background-agent worker at the production composition root. It must execute on a separate existing ClaudeLocalAgent/CodexLocalAgent instance/session (or another proven independent executor), not `ControlCenter.agent.ask` on the shared conversation. Reuse those subprocess wrappers and existing routing/permission settings rather than building a second agent framework. Isolate session/runtime files, own process cleanup and concurrency limits; do not pretend this worker already exists. An API hosting these separate existing instances may live beside Control Center's shared agent route while JobService retains task authority.
3. Capture a bounded immutable request context from ConversationCore: originating committed/revision-tagged intent, heard history evidence, verified backend facts, explicit scope/permissions, conversation/turn/correlation IDs. Do not rely on independent agent inheriting the conversational CLI context. Feed `build_agent_brief`/work brief only where their speech-oriented instructions fit the worker's result contract.
4. Translate terminal/progress events into canonical task result state/candidates. Do not call existing `_settle_success` SPEECH path or `announce_notice` for generic job completion. Frontend/controller chooses whether/when to speak. Rehydrate pending/completed durable task records during frontend switch.
5. Test a suspended fake long worker while a second direct conversational turn completes, frontend stop/replacement preserves job, late result remains tied to old source intent, duplicate acceptance launches once, cancellation reaches only owned worker, failed cleanup is not reported as canceled success, and Core restart reports interrupted rather than imaginary continuation.

Known implementation gaps are explicit: generic worker and protocol ingress do not exist; targeted subprocess/native-subagent cancellation needs real ownership; current JobService cancellation/idempotency edge cases need bounded fixes if used; no test fixture alone proves an isolated production agent entrypoint. This preparation supplies paths/contracts, not evidence that Task11 acceptance is already met.

## Codex speculative context-only profile — verification follow-up

Checked 2026-09-12, documentation and read-only local CLI inspection only. **Conclusion: a complete enforceable context-only profile is not established for the inspected CLI/config stack. Keep speculative Codex execution `unavailable` under Decision22.** This is not a claim that Codex can never be restricted; the necessary closed set of capabilities and effective restrictions has not been demonstrated here. Jobs already admitted by Core retain their normal configured permissions and model.

### Local evidence, without inference

`Get-Command codex -All` found npm shims and a separate desktop executable. The `codex` command resolved in this shell reports **codex-cli 0.154.0**. Findings concern that command, not every installed executable or an uninspected custom backend command. No configured model was changed or queried through inference.

Executed only `--version`, top-level/subcommand help and `features list` with process-local overrides. No `exec` session, `debug prompt-input`, sandboxed command, MCP connection, plugin catalog operation, model catalog fetch or authentication operation was run. No secrets or whole configuration file were printed. Official documentation was fetched afterward for the missing semantic guarantees.

The help declares:

- `--disable <FEATURE>` and `-c key=value` apply invocation overrides; `features enable/disable` would persist changes and were **not** used.
- `exec --sandbox read-only` selects a sandbox for model-generated commands; `--ephemeral` concerns session-file persistence, not absence of tool calls or arbitrary disk effects.
- `exec --ignore-user-config` omits `$CODEX_HOME/config.toml` while retaining the auth home. It does not advertise exclusion of every project/system/plugin source. Ignoring config can also lose the selected provider/default model; it is not a safe shortcut that demonstrably preserves the configured backend.
- `--ignore-rules` exists but would discard policy. It is not proposed as isolation.
- `--strict-config` exists for exec, but the read-only `codex --strict-config ... features list` probe explicitly failed: strict mode is unsupported for `features`. Help/parser acceptance alone therefore cannot validate an entire proposed exec profile.

Actual feature probes, filtered to non-sensitive names/states:

| Probe | Observed effective state |
|---|---|
| `--disable shell_tool --disable unified_exec --disable apps --disable plugins --disable hooks --disable multi_agent features list` | `shell_tool`, `apps`, `plugins`, `hooks`, `multi_agent` false; **`unified_exec` remained true**. |
| `-c features.unified_exec=false features list` | **`unified_exec` remained true** again. No cause was established; do not silently assume the restriction applied or infer a workaround. |
| Separate disable probe for existing `browser_use`, `computer_use`, `code_mode_host`, `view_image`, `skill_search`, `skill_mcp_dependency_install` names | All six reported false. This proves configuration visibility for these names, not that an exec session exposes no other tool or startup side effect. |

These local findings establish useful individual switches, not an exhaustive model-visible capability manifest. The inspection found no documented `exec` no-tools/context-only switch. Do not convert a list of known negative flags into a guarantee that future, plugin-provided or separately configured capabilities are absent.

### Official contract limits

The current reference documents shell and hooks switches, app integration control, and per-server `mcp_servers.<id>.enabled`. App traffic is outside the sandboxed-command network proxy/domain policy. Default app settings can have per-app overrides. Plugin availability also has managed feature controls. None of these entries establishes that assigning an empty MCP table removes all lower-layer entries or suppresses all independently installed capabilities. [Configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)

Read-only mode still permits file reads and sandboxed commands; `approval_policy=never` prevents approval prompts rather than removing those capabilities. Web search has its separate `web_search="disabled"` switch. Network restrictions must account for the distinct command, browser, app and MCP surfaces, not merely outbound shell access. [Agent approvals and security](https://learn.chatgpt.com/docs/agent-approvals-security)

“No network” must also distinguish model transport, which this backend necessarily needs, from arbitrary tool/connector egress. A no-egress shell sandbox neither disables provider-hosted search nor proves apps/MCP cannot perform remote actions. No guessed network flag, proxy policy, empty working directory, prompt-only restriction or replacement provider/model is accepted as the missing proof.

### Task11 admission consequence

Do not launch speculative CLI work merely with `read-only`, a prompt saying “use only this context”, or the partially verified switches above. Return the existing conservative capability-unavailable result while retaining provisional source/delegation metadata for future handling. This must not fall back to the normally privileged conversational instance or self-development runner.

Enabling this optional path later requires a verified contract for the **selected executable** that closes every tool/startup capability (shell/exec, file/image reads outside supplied context, apps, direct and plugin MCP, hooks, browser/computer, extensions and spawned agents), validates effective config after all layers, and preserves the configured backend/model. The retained model request is the only intended network operation. Demonstrate that boundary structurally and through controlled negative tests; a model declining an action in a fake or smoke transcript is not enforcement. Until then, the accepted Decision22 unavailable behavior is the implementation target for speculative Codex only.

# Task13 — durable Live lifecycle review plan

Preparation only, 2026-09-12. No implementation, slice status change, provider call or pricing claim. Read with Task12/13, `07-live-session-cost-safety.md`, `verified-provider-contracts.md` and `live-delegation-authority-plan.md`. Provider behavior below refers to the official pages already fetched in the verified notes; Task12 must recheck them when implementing its adapter.

## Existing seams and gaps

- `domain/voice_frontend.py` already defines `FrontendState`: NEW, STARTING, ACTIVE, STOPPING, STOPPED, UNKNOWN_REAP_REQUIRED, and distinguishes operation UNKNOWN from COMPLETED. Reuse this provider lifecycle; an idle candidate is policy metadata, not a second contradictory lifecycle enum.
- `runtime/voice_v2.py` owns activation, coalesces Stop in shielded `_mute_task`, and retains `_pending_audio` / `_pending_canonical_close`. These references prevent replacement inside the current process only. They are neither a durable lease nor evidence of Live billing finalization. Provider STOPPED and native device cleanup pending are independent facts; Task07 ownership rules still apply.
- `runtime/realtime_frontend_session.py` drains terminal canonical evidence on close. Its Realtime implementation must not supply an inferred Live close guarantee. Task12 needs an explicit authoritative close result and a receiver that survives the Stop operation.
- `adapters/sqlite_state.py` is the existing operational repository (WAL, transactions, serialized access, cancellation-safe native worker ownership). `core/v2_app.py` starts/stops long-lived services before closing that repository. No Live owner/lease table or watchdog exists in the inspected code.
- `UsefulActivityTracker` and `v2_config.parse_active_timeout` currently allow zero = never, default 90 seconds, and `brain_activity()` rearms on backend events. This is not the required Live semantic-idle policy. `control_center.py` persists settings atomically, but its `.voice_heartbeat` / `.voice_state` projection resets stale offline presentation to idle: neither file can be Live ownership truth or proof of OFF.

## Smallest proposed durable owner

Add one Core-owned lifecycle service and a narrow repository contract, exposed through authenticated existing local protocol. Voice owns the primary transport; Core owns the durable unresolved-session record and recovery scheduling. No second executor or conversation ledger.

Persist one attempt record with a schema version, device/owner scope, application attempt ID, owner process-incarnation ID, fencing generation, architecture/model, optional conversation and provider session IDs, lifecycle, start-may-have-been-sent flag, timestamps/heartbeat, stop reason, retry bookkeeping and normalized usage/terminal receipt. Do not persist credentials or raw audio/transcripts. Enforce one unresolved attempt per device/runtime owner scope in SQLite, across conversations, mode switches and processes; an asyncio lock alone is insufficient. Retain terminal receipts separately from the current admission slot. Never expire/delete an unresolved record merely because its lease is old.

1. Reserve STARTING transactionally **before** calling Task12's factory or sending `session.start`. Failure to reserve/persist means no billable start. Mark “may have been sent” durably before the send, accepting conservative uncertainty after a crash in between.
2. On `session.started`, persist its opaque provider ID immediately, before declaring ACTIVE or admitting audio/delegations. Recheck owner generation and pending Stop after every awaited start step. Stop that wins during startup remains latched: a late started event supplies an ID to close, never permission to activate.
3. Heartbeats renew ownership through Core; renewal failure fences local admission and initiates close. Lease expiry authorizes cleanup takeover, **not** another primary startup. Distinguish process incarnation from reusable PID. Use monotonic deadlines within a process; persist UTC observations/Core incarnation and treat clock jumps or restart ambiguity conservatively.
4. Stop coalesces for this attempt, disables new local output/input work, persists STOPPING, and requests provider close without holding a DB transaction across network waits. Retain native device ownership while cleanup runs. Bound the caller/control-plane wait; timeout persists UNKNOWN_REAP_REQUIRED and leaves one owned cleanup task. Cancellation of an HTTP/UI waiter must not cancel that owner.
5. A matching terminal provider receipt is persisted before releasing billable admission. Validate provider session ID and attempt identity; stale tasks cannot mutate a replacement session. If persistence fails after the terminal receipt, preserve/retry the receipt and block replacement until durable reconciliation succeeds.

## Exact close and crash boundary

Register the terminal receiver before sending `session.close`; continue receiving until `session.closed`. Its final reason and cumulative `usage.seconds` are the provider evidence. A sent close, socket EOF, expired heartbeat, UI timeout, local mute, empty audio queue or device drain is not that evidence. Never sum cumulative usage updates. Keep local elapsed-time estimates distinct from provider usage, including when the final figure is unavailable. [Official lifecycle](https://developers.openai.com/api/docs/guides/live-conversations#usage-and-graceful-close)

On Core startup, recover unresolved records before allowing another Live start. A watchdog outside the Voice/UI task retries close on an available owned primary, or attaches to the **known** ID at `/v1/live/sessions/{id}/attach`, then sends `session.close` and waits for `session.closed`. Never send `session.start` from the reaper. Use bounded, coalesced retries with backoff and visible next-attempt/error state; no retry limit silently converts uncertainty into STOPPED. [Official sideband reference](https://developers.openai.com/api/reference/python/resources/live/subresources/sideband)

Two irreducible gaps must remain explicit:

- Crash after start transmission but before the provider ID is durably known: no documented lookup by client event ID, list/retrieve/delete endpoint or start idempotency guarantee resolves this. Preserve UNKNOWN with an unknown-ID reason and block duplicate start. A pre-send record narrows but cannot remove this distributed crash window.
- Known-ID attach may fail or miss an already-emitted terminal event. Primary-WebSocket reattachment/replay and attach-404 semantics remain unverified; neither 404 nor an HTTP hangup ACK proves OFF. A fake can verify attempted recovery, not prove inaccessible-session billing ended.

Core's watchdog survives Voice/UI failure while Core remains alive. If the whole application/machine is down, this design executes no cleanup until restart; shutdown hooks cannot guarantee cleanup after a hard kill. Do not claim an independent always-running service or a hard bound on orphan cost. Graceful Core shutdown should attempt bounded close and persist uncertainty **before** stopping its watchdog/repository.

## Idle and settings integration

Reuse the shared config/settings validation path and Task02's finite Duplex idle policy: provisional default60 seconds, accepted range5–3600, zero rejected. Do not silently inherit zero = never or promote the legacy90 seconds to a benchmarked Live default. Task20 owns comparative default selection; no new user decision is needed to implement the already accepted provisional configuration. Snapshot effective settings on an attempt; architecture/model changes request close and await confirmed release before replacement.

Idle eligibility combines elapsed **validated conversational** inactivity, no currently admitted user speech, no output/device playback in progress, and no unexpired controller expectation of an immediate continuation. VAD activity can inhibit premature close but cannot establish authoritative intent or silence. Live transcript gaps are not turn completion. Sensor gaps, blocked drain and stale controller observations cannot be read as idle; expose uncertainty. Bound continuation expectations so a lost callback cannot hold the session indefinitely. Background Job activity, generic progress and a durable outcome arriving from another topic do not by themselves keep time-billed Live open: Task08 retains results for later selection. If a separate safety timeout is needed for unavailable idle evidence, name its safety reason rather than reporting validated idle.

Publish normalized lifecycle/elapsed/provider-usage/recovery state through the existing Core event/query and RuntimeJournal paths. Task16 consumes that truth even when `.voice_heartbeat` is stale. Stop remains callable in STARTING, ACTIVE, STOPPING and UNKNOWN; the visual design remains outside Task13.

## Verification matrix

| Controlled scenario | Required evidence |
|---|---|
| Two starts, separate clients/process-like owners and DB connections | Atomic reservation admits one primary; losing owner sends no start. |
| Stop at reservation, start-send, started-receipt and activation awaits | Stop stays latched; late started ID is retained/closed; no late ACTIVE/audio admission. |
| Repeated Stop, cancelled caller, UI disappears | One cleanup owner; bounded caller response; durable STOPPING/UNKNOWN remains queryable. |
| Close timeout/EOF; terminal arrives later | No OFF at timeout; late matching receipt persists final reason/usage and releases only its attempt. |
| Crash at each durable/send boundary; reopen same SQLite | Unresolved record recovered before startup, epochs/incarnations do not alias; missing ID remains explicit. |
| Voice heartbeat lost, then old owner resumes | Cleanup takeover never permits duplicate primary; stale owner updates are fenced. |
| Known-ID attach succeeds / fails / 404 / loses final event | Attach-close flow used without new start; only terminal receipt resolves uncertainty. |
| Repository fails before reserve, started-ID save or terminal save | Respectively no start, unknown owner retained, and admission blocked until receipt reconciliation. |
| Valid idle / active speaker / playback drain / immediate continuation / background result | Only validated idle closes as idle; no generic backend keepalive; no result/history loss. |
| Architecture switch, app exit, Core restart, native drain blocked | Provider and device states remain distinct; no false idle/replacement; pending cleanup survives durably where applicable. |
| Duplicate/out-of-order cumulative usage and repeated final receipt | Idempotent finalization, no double counting, estimates labelled independently. |

Reuse controlled HTTP/SQLite restart patterns in `tests/integration/test_voice_outcome_retention.py` and device ownership patterns in `test_voice_device_control_plane.py`; add Task13-owned files when authorized. Provider fakes must expose wire receipts and failures, never return synthetic close success from EOF. Real provider recovery/billing limits remain explicitly unverified until a separately authorized smoke run.

# Public agent detail projection

`jarvis/runtime/control_center_agent_detail.js` exposes `JarvisAgentDetail` in the Control Center and through `module.exports` for conformance tests. It is a transient read composition for the object viewer. Work State, Mission History, the scene, jobs and chat retain their existing ownership. No new endpoint, durable state, publication contract, model prompt or communication channel is introduced.

## Identity and public truth

`project({object, scene, work, instance, tree, errors?})` accepts an execution scene object (`agent` or `job`) with canonical `work_ref`; the existing Map-based scene client state; and the results of current public reads. It returns a newly constructed, explicitly whitelisted JSON view model. No whole input object, Work Item, instance, declaration or provider trace is forwarded.

- Work State joins by exact `(source, external_id)`, never label/title. When both scene and current work provide conflicting `work_id`, live state is unknown. Missing/pruned Work State, Core restart/unavailability, malformed or foreign snapshots cannot be replaced by historical `work_status`.
- Mission lookup is exact `(work_source, work_external_id)`; a response for another source is rejected even when the external ID matches. The mission objective is read only by canonical mission ID, with an explicit scene role reference allowed as a lookup seam when history cannot resolve the instance. History supplies role/identity/objective; it never supplies live execution status or a guessed start time.
- `steps` contains actual direct child work (same source + exact parent external ID) and actual recorded direct child instances (exact parent instance ID). Child live status again joins the full source/external pair. Historical-only children show `unknown`. The projector never turns raw declarations, prompts or reasoning into steps.
- `published_plan` is always `null`; `plan_notice` says no public plan was published. No structured future-plan source exists in current Work State. `findings` contains only current public Work State summaries, including child summaries, not a manufactured timeline.
- Related artifacts come from the existing `JarvisSceneLayout.artifactsExplaining` rule: active artifact objects with a real `explains` edge to the selected execution object, excluding signals. Board membership and title matches are not authorship. References contain only scene object ID, validated optional `jart_…` registry ID and bounded public title, with no URL/file-path execution shortcut.

## View model

```text
schema_version: 1
object_id
identity: {source, external_id, work_id|null}
title
mission: {mission_id, objective} | null
role: {role_id} | null
instance_id | null
status: pending|running|blocked|completed|failed|cancelled|interrupted|unknown
live_unknown
started_at, ended_at: canonical UTC timestamp | null
activity, summary
progress_fraction: 0..1 | null
counters: {tokens|null, tool_uses|null}
published_plan: null
plan_notice
steps: [{source, external_id, instance_id|null, label, status,
         activity, summary, progress_fraction|null}]
findings: [{source, external_id, text}]
artifacts: [{object_id, artifact_id|null, title, relation:'explains'}]
actions: {stop, ask}
provenance: {status, timing, mission, role, steps, findings, artifacts}
degraded: [{code, message}]
```

Timings come only from current Work State. Use the existing Control Center `taskElapsed` helper for live/final elapsed duration; do not use declaration `created_at` as an execution start or keep a second duration owner. Missing terminal end time remains unknown. Percent progress is displayed only when a valid published fraction exists.

Bounds: at most 64 Work Items, 256 missions and 1,024 instances accepted from upstream; at most 32 visible child facts, 24 artifact references and eight findings. Truncation is explicit in `degraded`. Titles/activities are at most 160 characters; objectives and summaries at most 1,000. Public timestamps/counters/fractions are validated. IDs and role tokens have their existing bounded syntax. Unknown input fields are ignored, never spread into output.

## Existing action owners

`actions.stop = {enabled, method:'POST', path:'/api/jobs/cancel', body:{source,external_id}, reason}`. Enabled only for a live Core job (`object.kind === 'job'`, source `job`, current pending/running/blocked Work State). A CLI sub-agent gets an explicit disabled reason because no individual-stop route exists. The renderer sends through the canonical route and preserves actual outcome/refusal/error semantics; this module never cancels anything itself.

`actions.ask = {enabled:true, mode:'main_chat', target:{source,external_id,instance_id,mission_id}, prefill}`. It identifies the work in a main-chat draft. There is no promise of a direct private agent channel. S05 integrates with the canonical chat prefill API; no automatic send or new message bus.

## Bounded reader

`createReader({fetchJson, log, onState?, timeoutMs?})` requires the page's existing JSON reader and structured log seam. `fetchJson(path, {signal})` returns the body or throws with the backend's actual `message`, `code` and optional `status` on non-2xx; pass through the AbortSignal. Do not inject `/api/agent/tasks` diagnostics.

The reader exposes:

- `load({object, scene})`: reads `/api/work` and `/api/missions/work/{source}/{external_id}` in parallel; reads `/api/missions/{mission_id}` only if an explicit mission ID exists. Returns `{phase, model, error, started_at, deadline_at}`. `phase` is `ready`, `degraded` (readable partial facts), or `error` (for example deadline). Start/deadline are numeric milliseconds for the UI's live wait counter.
- `snapshot()`: current public reader state, including `loading` or `idle`.
- `cancel()`: aborts and settles pending load, clears deadline, returns to idle.

A new load supersedes the prior one. Cancelled/superseded loads resolve `null`; late transports cannot replace the current model or initiate stale follow-up mission reads. A transport that ignores abort still cannot hold the UI indefinitely: an independent total deadline resolves to an actionable retry error. Default 5 seconds, constrained 50 ms–15 s. Errors retain actual public backend words, and success/failure/cancellation log identifiers/codes/counts only. Observer/render and log callbacks are the page's synchronous integration seams.

The reader owns no timer-based refresh loop. S05 refreshes only while the overlay is open using the existing bounded UI cadence, displays motion + a live counter + cancel/retry, and calls `cancel()` on close/navigation.

Conformance: `tests/unit/test_agent_detail_js.py`; real Core/SQLite + current Control Center routes + production JS composition: `tests/integration/test_agent_detail_projection.py`. The integration scenario shows running → terminal → persisted mission with unknown live state after sandbox Core restart. Actual renderer/click navigation and optional model-driven runs remain S05/S06 acceptance work.

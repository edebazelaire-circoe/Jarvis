# S04 public agent projection — 2026-10-30

IMPLEMENTING NEW LOGIC — a public viewer projection: the existing `/api/work` and Mission History reads contain canonical facts, but no bounded viewer model or unified loading/Stop/Ask descriptor seam existed. Reused public reads, identity semantics and `JarvisSceneLayout.artifactsExplaining`; no new endpoint, renderer, lifecycle owner or chat/cancel plane.

Implementation in isolated `C:/Projects/jarvis/mov4`, branch `task/mov-s4`. No shared page injection or scene-page edits; S05 owns wiring.

## Final API for S05

Module: `jarvis/runtime/control_center_agent_detail.js`; global / CommonJS `JarvisAgentDetail`.

```javascript
const reader = JarvisAgentDetail.createReader({
  fetchJson: (path, {signal}) => getJson(path, {signal}), // Existing page reader; throws on non-2xx.
  log: consoleLog,
  onState: state => renderPublicDetail(state),
  timeoutMs: 5000,
});
const result = await reader.load({object: sceneObject, scene: currentMapBasedSceneState});
// Result null means cancelled/superseded; do not render it.
reader.cancel(); // On close, target navigation and teardown.
```

Reader methods: `load`, `cancel`, `snapshot`. No periodic loop. S05 refreshes only while open with existing bounded cadence and supplies visible loading motion/live counter/cancel, then retry for errors. Reader state: `{phase,model,error,started_at,deadline_at}`. Lifecycle phases `idle`, `loading`, `ready`, `degraded`, `error`; start/deadline numeric milliseconds. Independent 5-second total deadline (bounded configurable 50ms–15s) settles even a transport ignoring abort. New loads/cancellation abort and settle old loads; late responses do not publish or launch stale mission reads.

Pure `project({object,scene,work,instance,tree,errors?})` emits the exact public model documented in `docs/agent-detail-viewer.md`:

- `schema_version:1`, `object_id`, `identity:{source,external_id,work_id|null}`, `title`;
- `mission:{mission_id,objective}|null`, `role:{role_id}|null`, `instance_id|null`;
- `status`, `live_unknown`, `started_at`, `ended_at`, `activity`, `summary`, `progress_fraction`, `counters`;
- `published_plan:null`, `plan_notice`, actual child `steps`, public-summary `findings`;
- `artifacts:[{object_id,artifact_id|null,title,relation:'explains'}]` — map these to the same real scene/artifact viewer adapter, not title matching;
- `actions`, `provenance`, `degraded:[{code,message}]`.

`actions.stop` has `{enabled,method:'POST',path:'/api/jobs/cancel',body:{source,external_id},reason}`. Only current active Core jobs enabled; CLI child agents explicitly disabled. Renderer sends through the existing route and preserves its actual outcome/refusal. Module sends no mutations.

`actions.ask` has `{enabled:true,mode:'main_chat',target:{source,external_id,instance_id,mission_id},prefill}`. S05 adds the canonical chat draft prefill seam. Do not auto-send or imply a private agent channel.

## Correctness/privacy

Work State is live truth, keyed by exact source/external pair. A conflicting explicit `work_id` degrades to unknown. Mission response for another source is ignored even if external ID matches. Historical status/timestamps never recreate live state. Actual children join by source/parent external ID or durable parent instance ID; their live statuses again use the complete identity. `published_plan` stays null; no speculative future steps or new prompt/provider publication path.

Output is a whitelist assembled field-by-field, never an input spread. Declaration/prompt/trace/thinking fields are omitted. Summaries are existing public Work State summaries, not provider diagnostics. Artifacts reuse existing `explains` relation rule and validated optional registry IDs. Board membership alone is not authorship. Errors preserve public backend words; logs contain codes/IDs/counts only.

Limits: 64 work items;256 missions;1024 instances upstream.32 displayed child facts;24 artifacts;8 findings; public text bounds160/1000. Unknown/invalid/oversized public inputs degrade truthfully; truncation reported. Canonical timestamp syntax/finiteness, counters and fractions validated. Existing `taskElapsed` consumes canonical times for display; no second elapsed-state owner.

## Validation actually executed

Using main checkout venv interpreter from mov4, foreground, no full suite:

`python -m pytest --assert=plain --tb=short -q tests/unit/test_agent_detail_js.py tests/integration/test_agent_detail_projection.py`

Final run: **23 passed in8.14s**. Unit scenarios cover running/terminal/pruned states, exact source identities and child joins, work-link conflict, private-field sentinels, safe Stop/Ask, artifact relation semantics, payload bounds/truncation, timestamp/progress validation, errors/malformed bodies, hung-transport timeout, cancellation/supersession and late-response suppression.

Real integration: production JS reader uses actual existing Control Center routes backed by real local Core HTTP + temporary SQLite. Seeded canonical mission/child facts and Work State observations show running → completed (with final end/summary) → sandbox Core restart, durable objective preserved but live status/times unknown. No real model or CLI agent ran; no agent behavior changed. This is real public-read composition with controlled canonical inputs, not a live-model validation claim.

`node --check` new module and `git diff --check` passed. No user's runtime/data touched. Independent QA pending. Full rendered agent overlay/Stop clicks/Ask draft navigation remain S05/S06 work; provider/model trace analysis not applicable to this read-only projection.

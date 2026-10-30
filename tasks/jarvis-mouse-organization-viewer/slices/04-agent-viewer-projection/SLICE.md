# Slice 04 - Agent viewer public projection

## Goal

Provide a bounded, truthful, UI-safe read model for the agent viewer, including mission, live work, elapsed time inputs, progress, public steps/facts, related artifacts and canonical Stop / Ask action seams.

## Context

Work State already exposes live public execution fields. Mission History already exposes objective, role, instances and relations. The missing part is a stable UI projection and, potentially, an optional structured public-step contract. The feature must never expose raw provider traces or private reasoning.

## Canonical Concepts

- Work State is live execution truth.
- Mission History is durable mission/role/relation truth.
- Scene/artifact links identify produced artifacts.
- Cancellation remains owned by the existing work/job/agent cancellation path.
- Communication/chat remains owned by existing canonical routes.

## Scope

### In Scope

- Agent viewer read-model endpoint/service or a clearly bounded composition of existing reads.
- Mission/objective, role, live status, started/end timestamps where canonical, current activity, summary, progress fraction and selected counters.
- Actual child work / mission facts for visible progress structure.
- Optional bounded public planned-step data only if a real structured upstream source exists or a minimal explicit contract is required.
- Honest degraded states after Core restart/Work State pruning.
- Related artifact references using canonical links.
- Stop action adapter to existing cancellation semantics.
- Ask action adapter to existing direct communication if supported, otherwise explicit main-chat target/prefill contract.
- Focused tests and privacy assertions.

### Out of Scope

- Rendering the full overlay shell.
- Inventing a plan from hidden reasoning.
- Exposing prompts, provider traces or chain-of-thought.
- New agent lifecycle owner.
- New chat/conversation store.
- Automatic final report artifact generation.

## Dependencies

### Hard `depends_on`

None after Slice 00 READY.

### Soft `requires`

- Current chat/communication route from `jarvis-unified-chat-and-board-drop` or current HEAD.

Fallback: return an `ask_mode` that tells Slice 05 to prefill/route through the canonical main chat with target identity; do not block the read model.

Integration required before: `05-scene-integration-organize-viewer`.

Mismatch policy: adapt the action descriptor to the final canonical chat ingress; never add a second message bus.

### Can Start With

Work State, Mission History and artifact-link read APIs.

### Produces

A stable public agent detail projection and action descriptors consumable by the viewer.

### Integration Checkpoint

Slice 05 verifies the projection against real scene agent identities and viewer navigation. Slice 06 validates on real running/terminal agents.

## Implementation Steps

1. Audit current work and mission read APIs and cancellation routes at HEAD.
2. Define a bounded view model with explicit provenance for each field.
3. Join scene/work identity to current Work State and mission instance/objective without guessing missing links.
4. Expose started/end timing data needed for elapsed duration, preserving unknown states.
5. Represent visible progress from `progress_fraction` when present and actual child work/mission facts.
6. Check for an existing structured public plan-step source. If absent, do not infer future steps; expose `published_plan: null` / equivalent plus actual progress facts.
7. Resolve related artifacts through canonical IDs/relations.
8. Bind Stop to canonical cancellation and preserve its refusal/error semantics.
9. Bind Ask to canonical direct communication only if it truly exists; otherwise emit a main-chat targeting/prefill descriptor.
10. Add tests that reject/omit raw prompt, trace, hidden reasoning and unbounded text.
11. If any new public-step contract is added, document its bounds and provider ownership explicitly.

## Files Likely Touched

Revalidate at HEAD. Likely read/service/protocol areas around:

- Work State reads
- Mission History service/routes/view
- artifact/Board link reads
- existing cancellation route
- current chat/communication ingress seam
- focused agent/work/mission tests

Prefer a new dedicated UI projection module over adding UI-specific fields to the core domains unless a field is genuinely canonical.

## Architecture Constraints

- Work State status wins over historical guesses.
- `unknown` remains unknown after restart/pruning.
- No private reasoning fields.
- No title matching to identify artifacts or missions.
- No parallel cancellation or chat owner.

## Automated Validation

Focused service/protocol tests plus privacy/shape tests. If provider adapters/prompts are changed to publish public steps, add agent-trace-analysis with real traces and prove that only the explicit public summary/steps cross the boundary. No full suite.

## Acceptance Criteria

- Running agent projection clearly states mission, live activity and available progress.
- Terminal and live-unknown cases are truthful.
- Public step section never fabricates unpublished future work.
- Related artifacts are canonical references.
- Stop and Ask paths reuse existing owners.
- Private reasoning cannot appear in the view-model payload.

## Documentation Updates

Update Work/Mission docs only for truly canonical new fields. Document the agent-viewer projection and privacy boundary.

## Handoff Notes

Return the exact endpoint/view-model and action descriptor shape to Slice 05, including degraded states and refresh expectations.


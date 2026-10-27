# Implementation strategy

## Relationship to the parent V1 task
This is an amendment overlay. Slice 00 must compare it with `jarvis-presentation-edition-v1` and current `main`. When both tasks touch the same contract, avoid implementing two competing versions: update/supersede the older planning or sequence the work explicitly.

## Recommended order
1. `01-presentation-product-brain-scope` — capability/prompt/routing contract first.
2. `02-board-project-continuity` — durable resume semantics.
3. `03-research-reuse-freshness-orchestration` — research behavior over existing roles/methods.
4. `04-research-documents-and-dossier` — durable output once research behavior is stable.
5. `05-voice-lifecycle-wake-chat`, `06-settings-and-novice-ui`, and `07-bug-report-diagnostic-bundle` may proceed in parallel after Slice 01 when hot-file overlap permits.
6. `08-macos-portability-build-validation` starts once baseline storage/runtime packaging seams are stable enough to abstract without duplicating work.
7. `09-v1-2-integration-e2e` closes the amendment.

## Migration constraints
- Do not migrate Board identity or create a new project schema.
- Existing Boards without the Presentation project `summary.md` convention must continue to open. The first meaningful turn may create/normalize the digest safely.
- Existing research notes remain readable. Freshness metadata applies prospectively or through best-effort inference, never destructive rewriting.
- Voice Off/Sleep preference migration must have a deterministic default and must not unexpectedly activate the microphone for users who explicitly disabled it.
- Diagnostic reporting must not move canonical files; it snapshots them.

## Parallelism and hot files
Likely shared files include brain/system prompt composition, `subagent_roles.py`, `work_methods.py`, agent/tool routing, Board brief/memory logic, Settings UI, Voice runtime and app launcher. Slice 00 must inspect active tasks and avoid concurrent edits to these hot surfaces without explicit coordination.

## Delivery discipline
Each Slice is one focused pass with its own regression tests and QA. Prompt/agent behavior changes require real agent traces, not only string assertions. UI/voice behavior requires real runtime validation before Human review.
# 03 — Implementation strategy

## Phase 0 — Readiness

Slice 00 performs a blind audit of current `main`, reconciles current implementation with the existing Settings/Architecture/Memory handoffs, resolves valid Workspace Task Types and records the concrete files/modules each UI Slice will touch.

## Phase 1 — Shared visual foundation

Slice 01 establishes or refines the reusable visual primitives, layout constraints and deterministic screenshot harness. It must not consume ownership of page-specific composition.

## Phase 2 — Parallel page refactors

After Slice 01, dispatch the five page-specific Slices in parallel when hot-file overlap is manageable:

- Slice 02 — Personalisation;
- Slice 03 — Architecture & Agents / Sous-agents;
- Slice 04 — Architecture & Agents / Architecture;
- Slice 05 — Mémoire & connaissances / Mémoire;
- Slice 06 — Memory Center.

Each Slice maps existing real data into the target visual composition and creates page-specific screenshot evidence.

## Phase 3 — Convergence

Slice 07 resolves shared CSS/component conflicts, verifies cross-page consistency, runs final accessibility/responsive checks and executes the final screenshot regression suite.

## Migration rule

Prefer incremental replacement inside existing routes/controllers. Do not duplicate writable settings or introduce a parallel settings store merely to simplify the UI rewrite.

## External task coordination

The PM must check the state of:

- `jarvis-settings-ui-reorganization` (done);
- `jarvis-architecture-agents-settings-editor` (done/currently reflected on `main`);
- `jarvis-memory-knowledge-settings-ui` (currently queued at task creation).

If the memory task is still unmerged, preserve a stable UI adapter seam and avoid blocking independent visual work that can be implemented against fixtures. Integration with final memory contracts belongs in the convergence phase.

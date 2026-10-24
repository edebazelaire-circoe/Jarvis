# Slice 05 — Mémoire & connaissances / Mémoire UI refactor

## Goal

Refactor the main **Mémoire** Settings view to the supplied two-column reference, keeping recall, semantic retrieval, consolidation and Memory Center entry points clear while moving technical diagnostics out of the primary experience.

## Context

Reference: `references/ui/04-memory-settings.png`.

The existing memory handoff defines canonical memory behavior: Markdown-backed canonical memory, lexical recall baseline, optional semantic retrieval, candidate-based consolidation and user-facing vs advanced diagnostics separation.

## Canonical Concepts

- `REFERENCE.md`
- current memory settings contracts and APIs
- `jarvis-memory-knowledge-settings-ui` decisions
- server-owned option/range metadata

## Scope

### In Scope

- Header and internal tabs: `Mémoire`, `Connaissances`, `Memory Center`.
- Left `Rappel` card with enablement, amount/budget presentation and simple recall profile when supported.
- Left `Consolidation` card with automatic/manual mode, confidence threshold and candidate budget mapped to live fields.
- Right `Recherche sémantique` card with enablement, provider selection and private-memory permission using actual provider availability.
- Right `Résumé du système mémoire` card with plain-language canonical memory/recall/consolidation/scope status.
- Right `Ouvrir le Memory Center` CTA with useful live summary counts where available.
- Bottom `Avancé & diagnostic` entry that keeps raw timeouts/index/service details out of the ordinary settings flow.
- Loading/degraded/offline/semantic-unavailable states.
- Responsive 2-column to 1-column behavior.

### Out of Scope

- Do not present derived indexes as canonical memory.
- Do not invent embedding providers.
- Do not expose Tencent/service IDs/raw index timings as primary controls.
- Do not create a second memory settings schema.
- Do not implement the full Memory Center workbench in this Slice.

## Dependencies

- `01-settings-visual-foundation`

## Implementation Steps

1. Load `/caveman`, `/coding-guideline`, `/impeccable`; use a Claude Work Agent when supported.
2. Check whether the related memory task has landed; bind to current live contracts or stable adapters/fixtures as decided by Slice 00.
3. Capture the current Mémoire page before-state.
4. Recompose the page into the reference two-column grid and preserve the three internal tabs.
5. Refactor Recall into a large primary card with concise explanatory copy and visually clear budget/profile state.
6. Refactor Consolidation into automatic/manual mode cards plus confidence/candidate controls using canonical ranges.
7. Refactor Semantic Search into enable/provider/private-data controls with explicit unavailable/degraded presentation.
8. Build the system summary as read-only status rows derived from live settings/runtime state.
9. Build the Memory Center CTA with live counts/availability where exposed; never fabricate counts.
10. Separate advanced diagnostics into a secondary footer/entry region.
11. Validate disabled semantic retrieval, no-provider, manual consolidation and degraded memory states.
12. Capture final 1254×1254 and narrower viewport screenshots.

## Files Likely Touched

Resolve exact paths during Slice 00. Likely memory Settings renderer/controller, memory settings styles, navigation/tab glue and targeted UI tests.

## Architecture Constraints

- Canonical memory store remains authoritative.
- Lexical-only recall remains a valid/default functional mode.
- Provider/range/option metadata stays server-owned.
- Candidate consolidation semantics remain unchanged.
- Advanced diagnostics are not promoted into the ordinary page for visual completeness.

## Automated Validation

- Recall/consolidation/semantic controls read and persist through current APIs.
- Semantic unavailable state is explicit and does not break lexical recall.
- Summary rows reflect real state and cannot drift from underlying settings.
- Tabs are keyboard navigable and preserve expected route/state behavior.
- No horizontal overflow at reference and narrower widths.
- Screenshot regression covers populated state and semantic-unavailable state.

## Acceptance Criteria

- The page visually matches the supplied Mémoire reference in hierarchy, card balance and neon/glass treatment.
- Ordinary memory decisions are understandable without raw diagnostics.
- No mockup-only provider/status is hard-coded.

## Documentation Updates

Document user-facing vs advanced memory fields and any intentional difference between reference copy and canonical runtime terminology.

## Handoff Notes

If the separate memory task is still in flight, keep the UI/data seam explicit and converge in Slice 07 instead of duplicating backend work.

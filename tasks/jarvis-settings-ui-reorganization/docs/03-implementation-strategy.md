# Implementation Strategy

## Rollout order

1. **Readiness + current-main reconciliation** - Slice 00.
2. **Canonical registry/IA contract** - create the destination model and migration aliases before moving pages.
3. **Settings shell** - build the new six-category visual/navigation shell while retaining temporary adapters for unmigrated content.
4. **Migrate ordinary-user categories** - Voice, Agents, Memory, Interface, Connections.
5. **Build structured Advanced** - move technical/operator surfaces only after their normal-user counterparts have a stable home.
6. **Remove legacy top-level injection paths** - stop `TABS.push/splice` patterns and preserve only explicit aliases.
7. **Integrated QA + human validation** - verify the whole Settings experience at once.

## Migration constraints

- Every move is a **surface relocation** unless the Slice explicitly proves a runtime change is necessary.
- Preserve persisted keys and tolerant-read/strict-write behavior.
- Preserve restart semantics. A relocated control must still say whether it applies immediately, next turn, next Core start, or next Voice start.
- Do not silently reset drafts when a controller moves between categories.
- Do not duplicate editable controls during transitional states. Use links/read-only mirrors when needed.
- Keep unavailable or stale model/CLI states explicit; do not hide broken configuration because the UI is cleaner.
- Preserve accessibility semantics: labels, focus return, keyboard navigation, aria-live error/status reporting, reduced-motion support.

## Temporary adapters

The new shell may initially mount legacy renderers inside the new categories. That is allowed only as a short migration bridge. The final state must use registry-owned section mounts rather than a hidden copy of the old top-level tab system.

## Freshness discipline

`main` changed between the original planning audit and this rebuilt handoff. Slice 00 must therefore treat all file lists as likely touch-points, not guaranteed exact diffs, and perform a targeted freshness check immediately before every Slice dispatch.

## Rollback strategy

Each migration Slice should preserve its previous renderer until its new destination passes tests. Avoid one monolithic removal of all old tabs. Legacy alias cleanup happens near the end so a failed category migration can be reverted without changing persistence.

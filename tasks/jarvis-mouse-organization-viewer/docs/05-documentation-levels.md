# 05 - Documentation Levels

## Canonical product documentation

Update canonical docs only when the implementation changes a durable contract:

- scene command/selection docs for any new atomic layout command;
- keyboard/scene interaction docs for user-visible bindings;
- work/mission docs only if a new public plan-step field is truly introduced;
- viewer documentation for the new overlay behavior and supported content types.

## Code-level documentation

Keep comments focused on non-obvious invariants:

- why context-menu selection is preserved;
- side/corner resize and Shift rebase behavior;
- all-or-nothing layout/undo stale protection;
- viewer overlay vs true browser fullscreen distinction;
- public agent progress vs private reasoning boundary.

Do not restate obvious DOM mechanics in comments.

## Handoff evidence

Each Slice may add compact evidence under its own folder after implementation. Do not prepopulate fictional success reports or screenshots.


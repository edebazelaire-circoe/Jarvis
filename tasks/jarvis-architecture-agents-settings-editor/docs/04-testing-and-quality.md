# 04 - Testing and Quality

## Per-Slice policy

Implementation Slices do **not** run the full unit suite or default broad test command at completion.

Per-Slice QA uses:

- code review;
- static/type/import/build checks where appropriate;
- narrow runtime smoke checks;
- real agent/runtime trace inspection when routing, brains, tools or delegation behavior changes;
- focused individual tests only when needed to diagnose a specific defect.

Every `Automated Validation` section explicitly repeats that the unit suite is deferred.

## Final validation ownership

Slice 08 is the single convergence gate and runs:

- full unit suite once;
- integration tests;
- browser/E2E tests for the page;
- runtime topology mutation validation;
- agent trace validation for delegation/routing;
- accessibility and keyboard/context-menu checks;
- visual comparison against the two references without treating mockup text as truth.

Unit and E2E checks should start in parallel when technically isolated. Otherwise run them in the same final validation phase.

## Required runtime scenarios

1. Architecture snapshot matches actual live nodes/endpoints.
2. A toggleable connection can be disabled and the corresponding runtime path actually stops being used.
3. Re-enabling the connection restores behavior.
4. A locked required connection rejects modification with a clear reason and leaves runtime state unchanged.
5. Invalid new connection creation is rejected rather than stored as UI-only state.
6. Brain model/provider change persists and the effective brain uses the selected supported configuration.
7. Brain delegation `never` prevents that brain from spawning/delegating to sub-agents.
8. A higher delegation level can delegate when appropriate but still uses the global role policy.
9. Updating a role's ordered candidate mapping changes candidate selection for that role without changing other roles.
10. Unavailable candidate/model entries remain visible with a reason instead of silently disappearing.
11. Existing role instruction revision/conflict handling still works.
12. No `Brains` tab, personality controls, CLI paths or raw permission controls appear in the normal page.

## Human validation

Human checks are last. They judge semantic clarity, graph readability, popup ergonomics and whether the neon/glass composition feels consistent with the approved Settings direction. Human validation never substitutes for machine proof that graph mutations alter the runtime.

# I-006 — Slice 08 leftovers (QA 2026-10-26)

Origin: Slice 08 QA (code review `slices/08-presentation-product-ui/qa/code-review.md`, runtime QA) and its rework.
Not blocking; owners:

1. **Slice 09 (explicit scope addition)**: Variantes still offers the « Remotion Studio » button and its texts in the
   `presentation` edition without developer mode (`control_center_presentation_studio_explorer_remotion.js:122,198`),
   and a message that sends the user to the « Présentations · moteur » card of the MCP dialog's « Plugins externes »
   tab (`:189`), a surface hidden in `presentation`. Mark the button `data-surface="developer"` (or read
   `JarvisProductEdition.developerSurfacesShown()`) and give the message a product wording. Added to the Slice 09
   `SLICE.md`.
2. **Slice 07 (then Slice 11)**: Slice 08 step 7 (connector / readiness affordances in the Presentation journey) was
   deferred: Slice 07 (onboarding/health) has no readiness state yet, and guessing one would break "the UI invents
   nothing". Plug it into the Presentation home (`control_center_presentation_rail.js`, `homeFor`) when Slice 07
   delivers its readiness source.
3. **Tests**: page/Core divergence on developer surfaces (`edition.surfaces_disagree`: page marked `hidden`, Core says
   `visible`, or the reverse) is logged and "Core wins", but has no node or browser test yet.
4. **`full` edition (runtime QA m3)**: since Slice 08, in `full` the kind orbs stay disabled until Core answers
   `/api/boards/edition` (a few ms locally; « Lecture… N s » then « Réessayer » if it fails). By design (never
   optimistic), but a new blocking point for creation when Core is older or the route fails. Decide whether `full`
   may fall back to its known three kinds.
5. **Board panel at 600×800 (runtime QA m4)**: the action icons of the active Board (rename, inspect, archive) overlap
   the orb ring. Present before Slice 08 (same layout on the `before-boards-600x800.png` capture), so not fixed here;
   owner: a Board panel polish pass (Slice 09 or the UI backlog).
6. Present before this task (fail on base `cf3f7e44`, absent from the known list of `main`):
   `test_barehands_interaction_js.py::test_the_practice_frame_is_moved_by_one_zone_through_the_real_engine`,
   `::test_the_practice_frame_resizes_only_on_two_distinct_compatible_zones`,
   `test_barehands_palette_js.py::test_the_served_page_puts_the_tools_on_the_palette_and_not_in_the_settings`.

## Slice 07 status (2026-10-26)
- Point 2: done. The Presentation home (`homeFor`) carries the readiness line (what is left before the first video, or the linked accounts) with a button that opens « Préparation de JARVIS » (`control_center_product_readiness.js`, `docs/product-install.md`).

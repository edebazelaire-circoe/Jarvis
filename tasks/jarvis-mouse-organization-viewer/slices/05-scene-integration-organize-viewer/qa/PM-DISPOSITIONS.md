# PM findings and dispositions — S05

- Atomic group drag: blocking, baseline-confirmed real regression within task contract. Fixed in80607352 via shared commitMany + S01 atomic path; final independent live acceptance pending.
- Legacy global ui_close prevented native viewer Escape: blocking, fixed local modal propagation boundary; final integrated QA pending.
- Polling replaced artifact focus/scroll; stale read kept timing: blocking UI consistency, fixed content stamps/focus restore/unknown timing.
- Late context response kept old pending tokens; organization auto-fit could add later writes: blocking scoped integration, fixed before implementation commit.
- QA-PREFILL-01: blocking. Source prefill only refreshes if conversationId absent. Closed chat may retain previous Board conversation, so opening starts async refresh while prefill appends to old cid. PM accepted defect; S2 owns separate S5 rework + targeted two-Board regression, S1 continues other real scenarios and verifies rework separately. No automatic send occurred; draft scope/preservation still must be correct.
- Public counters omitted from template: polish/optional. High-level mission/activity/progress/findings/artifacts are required; dense token/counter telemetry not required by locked UI.
- Selected-layout visual schematic: minor release polish; do not expand into redesign.

Machine acceptance withheld until independent runtime and blocking rework pass. Full suite reserved S06.


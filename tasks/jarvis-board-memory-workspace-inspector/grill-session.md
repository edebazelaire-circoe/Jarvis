# Reconstructed grill session

> This is a faithful reconstruction of the relevant design discussion, not a verbatim transcript. The original conversation remains the authority if a discrepancy is found.

## From Meeting design back to Boards

The user first explored a Meeting mode built on the previously designed Session/Context/Capture runtime. During the discussion, the role of Boards was revisited.

The user clarified that a Board is naturally an **entire state of work**: a meeting, a presentation, or ordinary assistant work. It includes the displayed scene/stars, tasks, created artifacts, and also useful context that may not be visible on screen. That hidden context should behave like an evolving memory which the agent can freely organize.

The key correction was therefore:

- Session remains the continuity of Jarvis/the user interaction.
- A Board is the durable workspace being worked on.
- The agent can load any Board and change/reinject its working context from that Board.
- SessionContext and Board memory are related but not identical; they evolve in parallel.

## Board types and future interaction modes

The user agreed that Boards may have lightweight kinds such as ordinary/empty, meeting and presentation. A meeting or presentation Board can be opened for preparation while Jarvis still behaves as an ordinary assistant. The live behavior only begins after an explicit "Démarrer la réunion" / "Démarrer la présentation" action.

The user also described a future Jarvis presence/profile model (`OFF`, `SLEEP`, `ASSISTANT`, `RÉUNION`, `PRÉSENTATION`) and confirmed that `SLEEP` is orthogonal to the active profile (`RÉUNION · SLEEP`, etc.). Those live-mode details are deliberately deferred from the current task.

## Immediate implementation priority

The user explicitly asked to stop drilling into detailed Meeting end behavior and instead focus on **good memory and Board management**.

Requested human capabilities:

- add a button among the top/settings controls to manage Sessions and Boards;
- see the actual folders/files created for memory;
- inspect links/connections among Sessions, Boards, agent/conversation bindings, artifacts and memory;
- inspect artifact references and provenance clearly;
- have a Board list screen and easy Board switching;
- create, rename, update, switch and archive Boards;
- use the manager as an implementation/debugging tool to verify that agent memory is clear and well organized.

Requested Jarvis/agent capabilities:

- expose the same management/inspection operations through MCP;
- inspect past Sessions and old Boards without having to foreground them;
- inspect/search/read Board/context memory;
- inspect artifact links/provenance;
- allow Jarvis to delegate an inspection to a sub-agent;
- give Jarvis broad semantic control over Boards (list/create/get/update/rename/switch/archive) while preserving backend invariants.

The assistant recommended a dedicated MCP server named `jarvis-workspace` rather than continuing to expand `jarvis-console`; the user accepted this direction (`ok si tu veux`) and requested `@Create Task`.

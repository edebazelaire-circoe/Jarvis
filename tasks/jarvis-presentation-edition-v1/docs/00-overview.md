# Overview

## Goal
Produce a Windows-first **Jarvis Presentation Edition V1** from the current `main` codebase, suitable for a controlled external/pilot installation rather than only the developer workstation.

## Scope
The V1 must:
- enforce Presentation-only Board availability at product boundaries;
- preserve shared Assistant/Meeting code but mark those product modes unavailable;
- give the installed product a stable per-user AppData identity;
- keep `CONTEXT_GLOBAL` as the brain's permanent personal directory under that AppData root;
- keep all working/internal documents canonical in AppData;
- expose `Documents\Jarvis` only as an explicit export destination;
- constrain brain writes/actions to bounded Jarvis capabilities;
- keep document search, Presentation Studio/Remotion, CIRCOE Mail/Calendar, Google Drive, and IGuard when configured;
- install/run without Git, system Python, system Node/npm, or user-installed FFmpeg;
- provide first-run provisioning, health/repair, and Windows release validation.

## Non-goals
- no server/local split;
- no cloud synchronization of Jarvis state;
- no macOS/Linux release in this handoff;
- no Meeting behavior implementation;
- no Assistant product enablement;
- no rewrite to another application framework;
- no general-purpose computer-use shell/file write capability for the distributed brain.

## Mental model
`AppData\Local\CIRCOE\Jarvis` is Jarvis's **home**. It contains canonical state and working material. `CONTEXT_GLOBAL` is Jarvis's permanent personal notebook/context inside that home. Boards and Sessions are scoped working contexts inside the same home. `Documents\Jarvis` is a **mailbox out**: it receives only explicit exports and is never authoritative.

The product edition is a capability policy layered on the shared Jarvis codebase. Product unavailability must be enforced by Core and protocol surfaces, not only visually hidden.

## Current repository baseline
Planning was grounded on `main` SHA `2d6ca879afac7a0e773598cff0872b4f819fa876`. The repository already contains Presentation mode/Studio/Remotion and the relevant Board, Session, Context, local capability and MCP infrastructure. This handoff is therefore intentionally productionization-heavy rather than a new Presentation feature build.

# 00 — Overview

## Goal

Move routine UI-tool orchestration out of the main Jarvis Brain into a dedicated Tool Brain that can react quickly, understand the current user-visible world, synchronize UI changes to live speech, and safely manipulate the UI through constrained tool contracts.

## Scope

This task includes:

- Tool Brain runtime boundary and model adapter;
- Jarvis-to-Tool-Brain intent and speech-progress events;
- a compact perception/world-state assembler plus targeted inspection operations;
- stable identity for Tool Brain-selectable objects;
- rich UI tool metadata with dynamic runtime choices for parameters;
- hybrid wakeups and a queue of scheduled UI actions;
- runtime precondition validation, stale-action rejection and replanning;
- UI capabilities for scene/Board/browser-window navigation where canonical project APIs exist;
- prompt/runtime changes so Jarvis knows UI execution is delegated;
- observability/timeline integration for Tool Brain decisions and tool calls;
- evaluation, shadow-mode rollout and end-to-end hardening.

## Non-goals

- Delegating arbitrary non-UI tools to Tool Brain in V1.
- Giving Tool Brain independent research, database-analysis or content-generation authority.
- Selecting or training a final specialized Tool Brain model.
- Replacing Board, Session, Context, scene, prefab, MCP catalog or conversation-event contracts that already exist.
- Rebuilding the live transcript/debug timeline from scratch.
- Making Jarvis and Tool Brain exchange free-form natural-language commands.

## Mental model

```text
                           +-------------------+
User transcript ---------->|                   |
Jarvis intents ------------>| Perception layer  |---- compact snapshot ----+
Speech progress/chunks ---->|                   |                          |
UI/runtime events --------->|                   |                          v
                           +-------------------+                    +------------+
                                                                        | TOOL BRAIN |
Targeted inspect tools <----------------------------------------------->| decision    |
                                                                        +-----+------+
                                                                              |
                                                                       action plan
                                                                              v
                                                                        +------------+
                                                                        | action queue|
                                                                        +-----+------+
                                                                              |
                                                                validate preconditions
                                                                              v
                                               +------------------------------+------------------+
                                               |              UI executor / canonical APIs       |
                                               | scene | board | browser surfaces | UI processes |
                                               +-------------------------------------------------+
```

## Success criteria

The feature is successful when:

1. ordinary UI changes no longer require main Jarvis Brain tool calls;
2. Tool Brain can act from valid current IDs/choices without fabricating selectors;
3. important events wake Tool Brain immediately instead of waiting for a periodic interval;
4. long Jarvis speech can drive actions scheduled against real speech/chunk progress;
5. interruption or stale UI state cancels/invalidates obsolete queued actions and produces a replan;
6. Jarvis continues to speak accurately about UI capabilities without claiming delegated capabilities are unavailable;
7. Board/scene/browser UI actions reuse canonical runtime ownership and do not create parallel state;
8. the existing observability timeline makes Tool Brain behavior debuggable end to end.

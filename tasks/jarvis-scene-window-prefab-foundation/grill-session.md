# Planning Session — Reconstructed

> Exact verbatim persistence of the full earlier project conversations was not available in the task-creation host. This file is a faithful reconstruction of the decisions and corrections visible in the current project context. It must not be treated as a word-for-word transcript.

## Rework FENETRES context

The user established that the visible scene is primarily controlled by the Brain or by the sub-agent responsible for a task. A small number of runtime-owned events, such as starting a task or surfacing an alert, may render automatically. Otherwise the scene is a representation controlled by the agentic layer. Nested agents may exist, but scene presentation should remain governed rather than letting arbitrary code mutate the UI without a contract.

The user accepted the idea of a lightweight control layer between agents and the visible scene if it does not create excessive complexity.

## Prefab discussion

The user rejected a V1 in which Jarvis continuously invents every object from scratch. The preferred V1 is a reusable prefab library.

The user described the library as containing existing window types and later other reusable scene objects. Jarvis should be able to start from an existing prefab, load its code, modify it for the current need, or create from scratch when no suitable prefab exists.

The user explicitly requested that Jarvis be able to save an adapted or newly created object as a new prefab in the shared library.

The user clarified that base prefabs may still be changed, but only when the user explicitly asks to modify the base itself. Normal runtime adaptation should not silently mutate a base prefab.

The library is shared and maintained for all uses; it is not per-user, per-session, or per-board.

The user stressed that prefabs need exposed variables. Typical changes such as color should happen through declared inputs rather than source edits.

The user clarified that "HTML" means HTML + CSS + JavaScript and that these objects are actionable/interactive.

The user gave the checklist as a canonical example: Jarvis should be able to send JSON or a list of objects to populate a prefab dynamically. Prefabs are skeletons that can be populated through variables or modified when needed.

## Presentation relationship

The user wants presentation mode to prepare a reserve of useful visual elements and data rather than a rigid timed slide deck. Jarvis may proactively show relevant prepared material while the user speaks, may react to off-script questions, may redisplay earlier material, and may create or adapt supporting visuals.

Presentation behavior is configurable per presentation board, not globally: visual initiative, vocal initiative, and an editable behavior prompt may vary from one meeting/presentation to another.

The user then refocused the planning session: board/session/context semantics and presentation-entry mechanics already exist and should not be redesigned. The key new architectural work is the reusable object/prefab capability and how Jarvis interacts with it.

## Task split decision

For implementation, the lower-level prefab/window foundation should be separate from presentation orchestration. Presentation is a consumer of the scene/prefab substrate and already has its own active task material. This handoff therefore covers only the reusable scene object and prefab foundation.

# 02 — Target Architecture

## 1. Components

### A. Jarvis Brain integration

Jarvis remains responsible for user understanding, reasoning, speech generation, context loading and non-UI tools. It receives a compact **UI capability manifest** describing what Jarvis-as-a-system can do, plus an explicit rule that UI execution is delegated.

Jarvis emits typed signals such as:

```text
ui.intent
ui.relevance
speech.response_planned
speech.chunk_started
speech.chunk_progress
speech.chunk_completed
speech.interrupted
```

The exact event names must follow the repository's canonical conversation/event conventions discovered in Slice 00.

### B. Perception Assembler

Builds the default Tool Brain snapshot from canonical sources. It must not create a second source of truth.

Conceptual shape:

```json
{
  "snapshot_id": "...",
  "captured_at": "...",
  "session": {"id": "..."},
  "board": {"id": "...", "label": "...", "revision": 42},
  "speech": {
    "response_id": "...",
    "current_chunk_id": "chunk-6",
    "progress": 0.41,
    "spoken": ["chunk-0", "..."],
    "current_text": "...",
    "upcoming": [
      {"id": "chunk-7", "summary_or_text": "..."}
    ]
  },
  "user": {"recent_transcript": "...", "latest_turn_id": "..."},
  "scene": {
    "focused_id": "...",
    "objects": [
      {
        "id": "win-28",
        "kind": "window",
        "label": "payments-worker analysis",
        "visibility": "visible",
        "board_id": "board-2",
        "summary": "..."
      }
    ]
  },
  "runtime": {
    "agents": [],
    "tasks": [],
    "processes": []
  },
  "browser_surfaces": [],
  "queue": {"executing": [], "waiting": []},
  "recent_ui_events": []
}
```

Snapshot contents are relevance-bounded. Rich metadata is retrieved through inspection operations.

### C. Object identity / world registry

Every object exposed as a tool choice needs stable identity and enough typed metadata to disambiguate it:

```text
id
kind/type
human label
board/session ownership when applicable
current status
visibility/focus/location when applicable
provenance/owner when applicable
revision/version for optimistic validation when applicable
```

Labels are descriptive; IDs are authoritative.

### D. Canonical UI Tool Catalog extension

The existing MCP/tool catalog remains the source of truth. Tool Brain consumes a Tool-Brain projection of that catalog.

Each mutating UI tool should expose:

```json
{
  "name": "move_element",
  "description": "...",
  "parameters": {
    "element_id": {
      "type": "id",
      "description": "Scene element to move",
      "choice_provider": "scene.movable_objects",
      "choices": [
        {"value": "win-28", "label": "payments-worker analysis", "kind": "window"}
      ]
    },
    "destination": {
      "type": "enum",
      "choices": ["primary", "secondary_left", "secondary_right", "background"]
    }
  },
  "side_effect": "reversible_ui",
  "preconditions": ["element_exists", "element_movable"]
}
```

Dynamic choices are computed from authoritative current state and must be traceable to the snapshot/revision they came from.

Free-form parameters are permitted only when the underlying operation genuinely requires open content and a stricter canonical representation is not available. V1 should minimize them.

### E. Targeted inspection layer

Tool Brain may request more information without mutating state, for example:

```text
get_board_state(board_id?)
get_information_on(object_id)
list_related(object_id)
get_available_actions(object_id)
get_queue_state()
```

Names are illustrative; Slice 01/02 must reuse canonical APIs and naming conventions.

### F. Tool Brain Decision Runtime

The decision runtime receives:

- triggering event;
- current compact snapshot;
- applicable tool capability manifest and dynamic choices;
- current queue state;
- bounded recent Tool Brain decision history.

It returns a structured plan, never arbitrary code.

The decision model sits behind an adapter so model selection can change without rewriting perception, scheduling or tools.

### G. Hybrid Scheduler

Immediate wake classes should include at minimum:

- new accepted user transcript / turn update;
- Jarvis response/intent publication;
- speech chunk transition or meaningful progress checkpoint;
- interruption/cancellation;
- Board/scene/user-visible state change;
- task/agent/process state change that affects visible UI;
- queued action failure/invalidation;
- explicit UI request.

A periodic tick catches missed/coalesced changes. It must not be the only path for important events.

### H. Action Queue

Conceptual action record:

```json
{
  "action_id": "...",
  "tool": "focus_element",
  "args": {"element_id": "win-28"},
  "priority": "high",
  "trigger": {"type": "speech_chunk", "chunk_id": "chunk-9"},
  "planned_from_snapshot": "snap-123",
  "preconditions": [
    {"type": "object_revision", "id": "win-28", "revision": 7}
  ],
  "supersedes": [],
  "reason_code": "about_to_discuss"
}
```

Queue operations include add, cancel, replace, reprioritize, reschedule and inspect.

Prefer deterministic event/speech triggers over absolute delays. Absolute delays may exist where no semantic trigger is available.

### I. Validator / Executor

Immediately before execution:

1. resolve current authoritative state;
2. re-check choices/preconditions;
3. execute only if valid;
4. record result and resulting revision/state;
5. on stale/invalid input, emit a typed invalidation event and wake Tool Brain with fresh state.

No silent best-effort coercion of stale IDs.

### J. UI capability adapters

Tool Brain should call canonical services for:

- scene object show/hide/focus/move/resize/group/archive/etc.;
- Board switch/open/create operations that already belong to UI navigation;
- process/agent/task object presentation;
- browser/display surfaces such as open/focus URL/window and scroll/navigation.

Tool Brain does not become the owner of web research or content retrieval in V1.

### K. Observability

Tool Brain is a first-class event producer into the existing conversation/event log. Required traceable events include:

```text
tool_brain.wake
tool_brain.snapshot
tool_brain.decision
tool_brain.inspect
tool_brain.queue.added
tool_brain.queue.cancelled
tool_brain.queue.rescheduled
tool_brain.tool.started
tool_brain.tool.completed
tool_brain.tool.failed
tool_brain.action_invalidated
tool_brain.replan_requested
```

Exact names must follow the canonical event schema.

The existing live timeline gains a Tool Brain lane/overlay showing decisions, queued actions, tool execution, cancellation and failure on the same time axis as User, Mouth/Reflex, Brain and sub-agent activity.

## 2. Ownership boundary

```text
Jarvis Brain
  owns: reasoning, speech content, context, non-UI tools, intent publication

Tool Brain
  owns: UI action selection, timing, queue management

Runtime / canonical services
  own: truth, IDs, validation, mutation, revisions, permissions
```

This ownership split prevents double tool execution and avoids giving the decision model authority to fabricate runtime state.

## 3. Failure semantics

- Unknown/stale ID: reject and replan.
- Choice no longer legal: reject and replan.
- Board authority changed: invalidate affected pending actions.
- User interruption: cancel/supersede future actions tied to obsolete speech/intents.
- Tool runtime unavailable: preserve observability, suppress repeated thrashing, retry only according to an explicit policy.
- Decision model unavailable: UI remains safe; fallback behavior should be no-op or narrow deterministic rules, not automatic hand-back of all UI calls to Jarvis unless explicitly designed during Slice 00.

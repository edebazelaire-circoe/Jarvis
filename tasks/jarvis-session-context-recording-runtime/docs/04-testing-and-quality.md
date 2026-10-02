# 04 - Testing and quality

## Mandatory QA composition

Every implemented Slice gets `qa-verification`.

Add:

- `code-review` for every code-changing Slice;
- `runtime-validation` for user-visible or runtime behavior;
- `agent-trace-analysis` with real trace evidence for agent prompts, tools, routing, modules, MCP, Context hydration/enrichment or agent runtime behavior.

QA agents return evidence and findings. The Project Manager owns the decision to approve, rework, continue, add a Slice, create an Issue or escalate.

A regression caused by the current Slice is blocking. It cannot be moved to `Issues/` to make a checklist turn green.

Human validation is a final-mile check, never a substitute for QA. Before a Human check, run all reasonable unit/integration/browser tests, fake-device simulations, deterministic replay and runtime validation.

## Critical regression suites from current main

At minimum, relevant changes must select from and preserve:

- `tests/unit/test_session_manager.py`
- `tests/unit/test_session_protocol.py`
- `tests/unit/test_voice_session_binding.py`
- `tests/unit/test_workspace_board_contract.py`
- `tests/unit/test_board_*`
- `tests/integration/test_board_session_e2e.py`
- `tests/unit/test_schema_migrations.py`
- `tests/unit/test_audio_capture.py`
- `tests/unit/test_presentation_audio_capture.py`
- `tests/unit/test_ambient_ingestion_lane.py`
- `tests/unit/test_presentation_working_set.py`
- `tests/unit/test_scene_capture.py`
- `tests/unit/test_scene_capture_logic.py`
- `tests/unit/test_barehands_palette_js.py`
- `tests/unit/test_barehands_hud_js.py`
- `tests/unit/test_control_center_timeline_js.py`
- `tests/integration/test_conversation_event_timeline.py`
- `tests/unit/test_mcp_catalog.py`
- `tests/unit/test_control_center_mcp_api.py`

The PM should refresh exact file names before dispatch.

## New tests required by behavior

### Session/Context

- Core restart with an open Session preserves `jarvis_session_id`.
- Explicit new-session closes old Session and opens a distinct one.
- Fresh install creates one open Session/Context deterministically.
- Exactly one active Context invariant survives concurrent create/switch requests.
- Switching Context atomically dormants the previous one.
- Dormant Context is not selected as implicit agent write target.
- Explicit reactivation restores the same Context workspace.
- Context workspace path traversal/symlink boundary tests.
- Migration from current main preserves historical Sessions and Boards.

### Artifact/activity

- stable artifact IDs and typed kinds;
- payload references remain inside data root;
- atomic finalize and partial failure behavior;
- provenance graph rejects impossible/self-invalid relationships as specified;
- time/type/session/context queries are deterministic and bounded;
- activity ordering/replay/idempotency;
- no raw binary leaks into JSON traces.

### Audio recording/transcript

- durable sink cannot silently `drop_oldest`;
- slow STT never causes raw recording loss;
- provider failure retries from durable source;
- transcript chunk timecodes/order across forced segmentation;
- duplicate retry does not duplicate canonical chunks;
- source loss produces explicit gap/partial state;
- current passive PRESENTATION lane remains memory-only.

### Desktop capture

- screenshot artifact validation and atomic write;
- screen-record start/stop/idempotency;
- crash leaves recoverable partial media;
- permission/unsupported-source errors are stable;
- scene capture remains separate and unchanged in semantics.

### UI

- capture group is in left floating palette, not primary right dock;
- hand-tool selection semantics remain unchanged;
- capture buttons remain usable when Bare Hands is off;
- screenshot is an action, recordings are toggles/stateful controls;
- multiple capture channels display concurrent state correctly;
- keyboard/focus/ARIA labels and non-color status cues;
- narrow viewport geometry;
- scene safe-area includes enlarged/generalized left rail;
- status loss does not lie about recording state.

### Recovery E2E

- start Session/Context, create artifacts, restart supported processes, resume same Session;
- Brain joins mid-recording and catches up without full transcript replay;
- explicit new Session cleanly separates subsequent Context/artifact defaults;
- interrupted recording recovery is visible and queryable.

## Physical-device validation

Real microphone and OS screen recording cannot be fully proven by fake tests. Human manifests cover only those irreducible checks, after automated validation has passed.

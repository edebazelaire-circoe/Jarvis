# Follow-up — test failures that predate this task, and interleaved trace lines

## Failing before the task, unchanged by it

Measured at the Slice 08 baseline (`36d5b819`) and again at its end. Each was already failing at an earlier
baseline of this task (LOG, Slices 01a to 07).

| Test | Cause |
| --- | --- |
| `test_brain_capability_parity.py::test_every_tool_of_a_declared_server_is_documented_in_the_brain_prompt` | `ui_intent_publish` (display, Slice 4 of another handoff) is not named in the brain prompt; the four Dossier tools are named since Slice 07 |
| `test_tool_brain_choices.py::test_ui_projection_is_consistent_in_the_single_metadata_copy` | `memory_propose` reversibility metadata |
| `test_brain_delegation.py::test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available` | stale prompt expectation |
| `test_control_center_voice_architecture.py::test_async_browser_render_does_not_restore_a_previous_panel` | `agenda_reminders` panel |
| `test_scene_artifacts.py`, `test_scene_query_tools.py` (one test each) | system-prompt hash stale since `claude_local.py@46b2800b` |
| `test_scene_group_drag_js.py` | a group drag through one command |
| `test_barehands_interaction_js.py` (practice frame move, resize) | Bare Hands practice frame engine |
| `test_app.py::test_the_control_center_receives_a_tools_gateway_target_built_from_core_settings` | `SimpleNamespace` without `data_root` |

Timing-sensitive under load, green alone: `test_memory_context.py::test_recall_over_2000_notes…` (index sync about
13 s), `test_mcp_plugin_service.py::test_stop_is_bounded_even_with_a_hanging_owner`,
`test_presentation_render_service.py` (once in Slice 01b).

## `runtime/trace.jsonl` holds a few non-JSON lines

Slice 01a QA, measured again in Slice 08 over the sandbox traces of Slices 02 to 07: 2 broken lines in 12 files,
each a fragment of another line (`…répondu en 30 s.", "data": …`, a line cut in the middle). Core, the Control
Center and the MCP server processes append to the same file, so a long line written by one process can be
interleaved with another's. Not caused by this task. Proposal: one file per writing process, or whole-line appends
below the atomic size, or a lock; readers already skip an unreadable line.

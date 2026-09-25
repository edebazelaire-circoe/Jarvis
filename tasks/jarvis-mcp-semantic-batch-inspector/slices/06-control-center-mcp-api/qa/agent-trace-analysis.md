# Slice 06 — Agent trace notes

Scope: S6 changes no prompt, tool or routing. The only change on the agent side is two snapshot flags (`barehands_tools`, `console_tools`) in `ClaudeLocalAgent`. These notes check that the catalog's `advertised` claim matches what the launched agent really got, and that the model-visible surface did not move. The scenario and environment are in `runtime-validation.md`.

## Trace sources

- The Control Center runtime trace (`evidence/cli/runtime-trace.jsonl`, readable form `evidence/trace-summary.txt`).
- The argv of each brain launch, as the Control Center passed it (`evidence/cli/brain-launches-argv.jsonl`).
- The CLI stream-json (`evidence/cli/stream-launch2.jsonl`, `stream-launch3.jsonl`).
- The tool definitions the CLI put in its Messages request (`evidence/cli/model-request-tools-launch*.json`, from a fake endpoint).

## Execution path per launch

| Launch | Trigger | argv `--mcp-config` | trace `agent.start` | MCP servers started (trace) | CLI `system/init` | Snapshot flags / catalog |
|---|---|---|---|---|---|---|
| 1 (pid 21960) | CC start, scene on (default), BH off | display, console | display ✓ barehands ✗ console ✓ | display, settings | not captured (no turn) | display/console `advertised`, barehands `disabled` |
| 2 (pid 35624) | `restart {new_conversation:true}` after BH on | display, barehands, console | ✓ ✓ ✓ | display, barehands, settings | 3 servers `connected`; tools 13/5/3 | all `advertised`, `pending:false` |
| 3 (pid 33188) | restart after scene off | barehands, console | ✗ ✓ ✓ | barehands, settings | 2 servers, 0 display tools | display `disabled` |
| 4 | after switching back from Codex | display, console | — | — | — | display/console `advertised` |

All four sources (argv, `agent.start`, `*.server_started`, CLI init) agree with each other and with the catalog on every launch. The catalog never claimed `advertised` for a server that the process did not get, and never missed one it did get.

## Findings

- **No defect in the trace path.** `advertised` is read from the snapshot flags, which are set in the same place as `display_tools` (right after `create_subprocess_exec` succeeds). The trace proves they follow each relaunch: flipped on at launch 2 and off at launch 3 without any stale value. A switch change without a restart shows up only as `pending_restart` (launch 2 → scene off; launch 3 → BH off / scene on). This is the contracted behaviour.
- **Model-visible surface unchanged.** Per tool, the bytes the model received equal the card's `context_bytes` (21/21). Display = 31 864 B, barehands = 4 107 B, console = 2 918 B. Key set = `{name, description, input_schema}`: annotations and output schemas stay catalog-only (the Slice constraint "do not increase model-visible tool surface" holds). The API adds no tool and no prompt text.
- **Catalog built once.** One `mcp.catalog_built` line for about 25 requests, lazily at the first GET. It is not built at CC start, so it costs nothing when the inspector is never opened.
- **MINOR (C1 in the runtime report):** for Codex, `advertised` is `false` between turns, not `null`, because the snapshot state is `ready`. The state and the pending flag are right.
- **FLAGGED (pre-existing / harness):** `agent.exit` at level error (`returncode 1`) on every intentional stop or restart.
- **OPTIMIZATION: none.** `_mcp_availability` calls `agent.snapshot()` once per request. That snapshot includes `events[-80:]`, which is cheap. Nothing redundant was seen.

## Missing trace evidence

- A real-model turn: the fake endpoint was used ($0), so deferred loading and `ToolSearch` expansion on the real API were not observed. Slice 05 already reported this.
- `claude-in-chrome` and user-scope servers (jarvis-drive) inside the brain: `--chrome` was stripped and the CLI config was isolated.

# Slice 04 — Agent trace analysis (read-only QA)

- HEAD analysed: `16418cd` (baseline for comparison: `57a33b9`, extracted with `git archive`; no checkout touched).
- Claude Code: 2.1.282. Date: 2026-09-25.
- Evidence scripts and raw outputs: `qa/trace-evidence/` (uncommitted).
- **Verdict: PASS**, with one MINOR documentation precision and three FLAGGED items for Slice 08.

## 1. Historical baseline: what the live brain actually received

Source: `C:\Projects\jarvis\jarvis\runtime\trace.jsonl` (23.9 MB, 26 138 lines, last write 2026-09-24 16:37; only read). The Jarvis brain's CLI `stream-json` is traced as `agent.event`. The `user/tool_result.content` there is exactly what the model saw. I paired every `mcp__jarvis-*` `tool_use` with its `tool_result` (`trace-evidence/extract.py`, summary in `historical-summary.txt`). The other `trace.jsonl` files on disk come from tests or task20 offline fixtures and contain no brain MCP turns.

| Tool | Calls | Errors | Wrapped `{"result":…}` | Model-visible bytes (min / median / max) |
| --- | ---: | ---: | ---: | --- |
| scene_inspect | 9 | 0 | **9** | 1 124 / 1 156 / **17 854** |
| scene_query | 1 | 0 | **1** | 11 546 |
| scene_archive | 3 | 0 | 0 | 183 / 476 / 956 |
| scene_add_artifact | 3 | 0 | 0 | 423 / 423 / 1 103 |
| scene_update_object, scene_pin, scene_capture | 1 each | 0 | 0 | 114, 236, 435 |
| barehands_activate | 1 | 0 | 0 (indented text, no structuredContent) | 148 |
| drive_search (sub-agent) | 16 | 0 | **16** (`{"result":[…]}`, list not escaped) | 13 / 723 / 32 915 |
| drive_read (sub-agent) | 6 | 0 | 0 | 2 062 / 3 584 / 4 107 |

Findings:
- The live trace confirms the implementer's claim on its own. In every historical `scene_inspect` and `scene_query` call, the model received `{"result":"{\"scene\":…}"}`: the `structuredContent` wrapper around an escaped string. `tool_use_result` holds both `content` and `structuredContent`, and `content` equals the wrapper.
- The wrapper cost **7.1 % to 8.5 %** extra on real scenes. The largest real read was 16 535 B of raw text, which reached the model as 17 854 B. No turn hit a size budget, no read came back `truncated`, and no tool errored.
- There was **no sign of confusion**. After each wrapped read, the brain acted on correct ids and counts: it archived 34 agents and then the leftover artifact, re-attached artifacts to the right star, and unpinned the two pinned objects. So the wrapper was a cost in bytes and legibility, not a behaviour bug.
- Routing: in 8 of 9 live turns the brain ran `scene_inspect` before mutating. This matches the "stale memory" design and is not a Slice 04 concern. `agent.turn_over_budget` (`brain_turn_slow`) fired on most turns. Its cause is delegation and turn latency, not scene tools (`inline_tools` is empty except for one `barehands_activate`).
- **The live brain uses deferred tool search.** Every scene turn starts with `ToolSearch select:mcp__jarvis-display__…`, for example at 07:44:49, 07:45:20 and 15:21:22 on 09-21. This is the path §10.3 says it could not observe.

## 2. Independent reproduction (fake Messages endpoint, old vs new)

Method (`trace-evidence/run.sh`):
- A real isolated Core (`CoreProcess` from the integration tests) runs on a free port with its data in scratchpad, seeded with 3 user artifacts. Their titles contain `"` and `\` to exercise escaping.
- The real `python -m jarvis display-mcp` runs from HEAD, or from the `57a33b9` tree through `PYTHONPATH`.
- `claude -p` runs with `ANTHROPIC_BASE_URL=http://127.0.0.1:<port>`, a dummy key, an isolated `CLAUDE_CONFIG_DIR`, non-essential traffic disabled, `--strict-mcp-config`, and `stream-json`.
- The stub (`fake_api.py`) records request **bodies only** (never headers). It replays the script `scene_inspect → scene_query → scene_get → scene_update_object → scene_link → scene_link (duplicate) → scene_add_artifact → scene_archive`, then `end_turn`.
- No real API call was made. Each run sent 9 requests to the stub, and all 8 tools succeeded.

Results (`measurement-output.txt`). Byte counts exclude the CLI's own `<system-reminder>` suffix.

| Tool | Before (57a33b9) | After (HEAD) | Observation |
| --- | ---: | ---: | --- |
| scene_inspect | 1 344 B, `{"result":"{\"scene\"…"}` | 1 225 B, `{"scene":…}` | New text is compact JSON. It is **identical to the old inner string** once ids and timestamps are normalized, with the same key paths in the same order. The wrapper cost was 9.7 %. |
| scene_query | 1 294 | 1 179 | same, wrapper cost 9.8 % |
| scene_get | 1 428 | 1 247 | same, wrapper cost **14.5 %** (backslashes in titles were escaped four times) |
| scene_update_object / scene_link / scene_add_artifact / scene_archive | 232 / 82 / 227 / 159 | identical | Byte-identical after normalization, same key order. The model receives the compact `structuredContent`. |
| scene_link (duplicate) | 130 | 143 | **Only intended change:** `"revision":5` is inserted after `outcome`, and the key order is otherwise unchanged. |

- (a) **Tool definitions**, old and new: every MCP tool definition has exactly the keys `description`, `input_schema` and `name`. The strings `outputSchema`, `annotations`, `readOnlyHint`, `destructiveHint`, `idempotentHint` and `structuredContent` appear **nowhere** in any request body. All 13 display definitions are **byte-identical** between old and new (34 079 B), so the model-visible cost did not change.
- (b) **Tool results:** after the slice, the stream's `tool_use_result` for inspect, query and get is a text list with no `structuredContent`. For mutations it is `{content, structuredContent}`, and the model gets the compact `structuredContent`.
- **Deferred-tool path, which the implementer did not measure.** I re-ran with `ENABLE_TOOL_SEARCH=true` (`run_ts.sh`), which reproduces the live brain's `ToolSearch select:…`. The MCP tools arrive as `defer_loading` definitions with keys `name`, `description`, `input_schema` and `defer_loading`. `ToolSearch` returns `tool_reference` blocks, and there are still no annotations or `outputSchema`. The result shapes match the non-deferred run: raw text for inspect, compact typed JSON for mutations.

Harness incident, disclosed for transparency. My first launch had a path bug that left `JARVIS_CORE_PORT` and `JARVIS_CORE_TOKEN_FILE` empty. The display server then fell back to the default port 17653, which is the user's live Core. `CoreLoopbackTransport._connect` reads the token before it creates any client (`core_forwarder.py:55-63`). The token file did not exist, so all 8 calls failed with `core_unreachable` and **no connection was opened**. The live `trace.jsonl` mtime is unchanged (09-24 16:37). The harness now refuses to run if the port is empty or equals 17653.

## 3. Risk to brain behaviour (prompts versus result shapes)

- The brain prompts (`claude_local.py`) and the display, settings and Bare Hands tool descriptions do not reference a `result` key or the wrapper anywhere. The display descriptions still say "JSON compact" and document the legend, which is now true without an extra decoding layer.
- The keys the prompts tell the brain to read are unchanged:
  - `note` for Bare Hands (`claude_local.py:150`) is still in `BarehandsCommandResult`, in the same position.
  - `restart_required` for `settings_set` (`:167`) is still present, and is `null` when no restart is needed, as before.
  - The re-read signal `scene_changed` is still present and in the same place (verified live in the update result).
- No key was renamed or removed. The only addition is `revision` on a duplicate `scene_link`.
- Bare Hands and `settings_get`/`settings_set` used to return a bare `-> dict`. FastMCP then produced **no structuredContent**, and the model saw **indented** text: the historical `barehands_activate` result was `{\n  "command": …}`, which I also reproduced with FastMCP 1.30. They are now typed, so the model sees **compact** JSON. The keys and their order match the dict the tool builds (`barehands_mcp.py:324-329` against the model at `mcp_results.py:179-185`, and `settings_mcp.py:588-601,639-646` against `:153-174`). The only difference is whitespace, which is lower risk and fewer bytes.
- Pydantic validation now runs after the call. A result that does not match its schema becomes an error saying "may have been applied", never a false "nothing sent". This is the correct direction.

## 4. Findings

| Severity | Finding |
| --- | --- |
| MINOR (doc) | §10.1 says the bytes the brain reads are unchanged except for `scene_link`. That holds for scene commands, but for Bare Hands and `settings_get`/`settings_set` the model now sees compact JSON instead of the previous indented text. Only whitespace changed, not keys or order. One sentence in §10.1 would make it accurate. |
| FLAGGED | §10.3 says deferral "is not observed here". It is reproducible locally with `ENABLE_TOOL_SEARCH=true`: the definitions carry `defer_loading` and nothing else extra, with the same result shapes. Slice 08 still needs to confirm this on the real API, because the real brain uses ToolSearch every turn. |
| FLAGGED | `drive_search` returns `-> list[dict]` and still reaches the model as `{"result":[…]}`. This happened 16 times historically, with up to 32 915 B for a 100-folder listing. The list is not escaped, so it is cheap, but it is the same wrapper pattern. It is outside the Slice 04 display scope; consider it when drive outputs get typed. |
| FLAGGED | The largest real `scene_inspect` was 16.5 KB of raw text against the 20 KB budget. The wrapper used to push it to 17.9 KB. Removing the wrapper gives back 7–15 % of headroom, and the most on titles full of quotes or paths. |
| OPTIMIZATION (not S4) | The brain ran `scene_inspect` before nearly every mutation. Slice 05 atomic selection ops should let "archive everything finished" run as a single call instead of query, archive, inspect, archive (as on 09-21 07:45). |

No BLOCKER or MAJOR finding. No historical error, retry or fallback was related to MCP result shapes.

## 5. What Slice 08 must verify on a live brain trace

1. `agent.event` `user/tool_result` for `scene_inspect`, `scene_query`, `scene_get` and `settings_describe` starts with `{"scene":` or the raw text, **never** `{"result":`, and `tool_use_result` carries no `structuredContent` for these tools.
2. For mutations, Bare Hands and `settings_get`/`settings_set`, `tool_use_result.structuredContent` is present and the model sees compact JSON with the dict's key order. A duplicate `scene_link` shows `revision`.
3. On the real API, the ToolSearch `select:` path still loads display tools, and the tool definitions carry no annotations or `outputSchema` (compare with `run_ts.sh`).
4. The runtime trace shows no `display.tool_failed` with code `output_contract`, and no `settings`/`barehands` equivalent.
5. The brain's spoken answers after a raw-text read are correct: counts, ids used in the next mutation, and the `scene_changed` re-read honoured.
6. The per-turn context bytes for scene reads drop by roughly 8–15 % compared with this baseline (median `scene_inspect` was about 1 156 B, maximum 17 854 B).

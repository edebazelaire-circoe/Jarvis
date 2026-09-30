# Slice 05 — Evidence

Branch `task/jarvis-generic-mcp-plugin-runtime`. Commits `1908d65` (propagation + prompt + tests),
`bcee50a` (E17 + docs). Date 2026-09-30. Claude Code 2.1.285 (`claude-opus-5-5[1m]`), codex-cli 0.157.0.

## 1. Tests (foreground, `-q -p no:cacheprovider`)

| Command | Result |
| --- | --- |
| `test_mcp_*` (8), `test_control_center_mcp_api`, `test_control_center_mcp_inspector_js`, `test_tools_gateway_mcp`, `test_tools_policy`, `test_tool_discovery`, `test_tool_relevance`, `test_claude_tools_gateway_args`, `test_codex_agent`, `test_brain_delegation`, `test_routing_hook`, `test_claude_debug_console`, `test_voice_to_claude` (20 files) | **742 passed, 1 failed** — the failure is `test_brain_delegation::test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available` (READINESS §Baseline, see §7) |
| `test_prompt_*` (4), `test_control_center_prompts`, `test_back_brain_*` (6), `test_presentation_integration`, `test_board_brains*` (5), `test_app`, `test_v2_architecture`, `test_display_mcp`, `test_scene_artifacts`, `test_scene_query_tools`, `test_scene_settings`, `test_settings_mcp` (24 files) | **582 passed** (one run from `tests/unit` as cwd failed `test_control_center_prompts` on a cwd-relative path; rerun from the repo root: 4 passed) |
| `tests/integration/test_tools_gateway_e2e.py` | **1 passed** |
| `test_codex_agent::test_requires_codex_the_real_cli_reads_the_overrides_back[dossier avec espaces / l'apostrophe]` | **2 passed** against the real `codex mcp get jarvis-tools --json` (skipped when `codex` is absent) |

Baseline before the change (same 13 prompt/argv/catalog files): 452 passed, 1 failed (the same READINESS test).

## 2. Acceptance → evidence

| Acceptance bullet | Evidence |
| --- | --- |
| One `--mcp-config` for `jarvis-tools`, file without token; restricted and `job_result` argv byte-identical | `test_claude_tools_gateway_args`: `…_gets_one_gateway_config_after_the_console_without_the_token` (sentinel token file, absent from file + argv, placed right after the console config), `test_restricted_and_job_profiles_are_unchanged_byte_for_byte[job_result/speculative_analysis/presentation_preparation]`. Live: `runtime/tools-mcp.json` of the isolated run holds `JARVIS_CORE_TOKEN_FILE` (a path), no token |
| `JARVIS_TOOLS_NATIVE_SERVERS` = declared set, 4 combinations | `test_the_native_set_is_exactly_the_servers_declared_this_launch[4 params]` + console-write-failure case. Live: `tools.server_started {"agent":"claude","native_servers":["jarvis-display","jarvis-console"]}` (trace l.32), Codex `{"agent":"codex","native_servers":[]}` (l.132) |
| Codex overrides on `exec` and `exec resume`, TOML quoting round-trip (space, `'`) | `test_codex_agent::test_the_gateway_overrides_reach_exec_and_exec_resume_before_stdin[2 sandbox modes]`, `test_requires_codex_…[2]` (real CLI) |
| Real trace Claude: `list_tools` → `call_tool`; subagent same, no credential (Q1) | §3 (a), (b) |
| Real trace Codex + Q4 | §3 (c), §5 |
| Q5 recorded; prompt names the tool accordingly | §3 (d), §5; `BRAIN_TOOLS_PROMPT` names `mcp__jarvis-tools__list_tools` / `call_tool`; `test_the_prompt_names_the_gateway_tools_in_full_and_stays_short` |
| Prompt fingerprint tests updated deliberately, no other prompt text changes | Only additions: `BRAIN_TOOLS_PROMPT` layer `backend.conversation.tools`; tests amended: `test_prompt_registry` (conversation text, Codex turn, new descriptor bound to exactly 5 programs, absent from job/speculative/presentation), `test_control_center_prompts` (layer listed), `_BASE_PROMPT` of `test_display_mcp`, `test_scene_artifacts`, `test_scene_query_tools`, `test_scene_settings`. No existing constant edited |
| `jarvis-tools` `advertised` from both agents' snapshots | `test_control_center_mcp_api::test_configure_agent_hands_the_gateway_to_both_clis[claude/codex]`, `test_the_gateway_is_advertised_from_either_agent_snapshot[6]`, `test_mcp_catalog::test_the_gateway_flag_is_read_from_a_live_snapshot_of_either_agent[6]`. Live: `/api/mcp/tools` → `jarvis-tools advertised` under Claude (running) and under Codex (`ready`, `advertised: true`), natives `disabled` under Codex |
| Write failure journaled, brain still starts; snapshot flag | `test_a_gateway_config_that_cannot_be_written_is_journaled_and_the_brain_still_starts` (`agent.tools_mcp_failed`, `tools_mcp_config_write_failed`, error); snapshot asserted in the argv tests |

## 3. Real traces (isolated instance)

Setup: `JARVIS_DATA_ROOT` / `JARVIS_RUNTIME_DIR` under the session scratchpad, Core `127.77.0.1:17763`, Control
Center `127.0.0.1:17764` (browser launch disabled, feedback dir in the sandbox), `JARVIS_DRIVE_PROVIDER=none`,
`JARVIS_MCP_ALLOW_LOOPBACK_HTTP=1`. Fake remote MCP (`tests/fakes/fake_remote_mcp.py`, bearer auth, three tools
`search_contacts` / `search_mail` / `send_mail`, canned fake results) on `127.0.0.1:65257`. Plugin created through
Core `POST /v1/mcp/plugins`, `PUT …/credential {"strategy":"bearer","value":"SENTINEL-SECRET-7f3a"}`,
`POST …/connect` → `connected`, plugin id `127`. The user's Jarvis (17653/17654) was not touched. Every turn went
through `POST /api/agent/ask` with `context.addressing:"addressed"` (program `backend.claude.turn` /
`backend.codex.turn`, real brief). Excerpts below: line of `runtime/trace.jsonl`, actor, tool, ids and codes; no
tool result data.

### (a) Claude brain — discovery then external call (4 API turns, 7.2 s)

```
37  brain init   tools=95  jarvis-tools: [call_tool, list_tools]  ToolSearch present
39  brain tool_use ToolSearch {"query":"select:mcp__jarvis-tools__list_tools,mcp__jarvis-tools__call_tool"}
40  brain tool_result ToolSearch ok  tool_reference: [list_tools, call_tool]
42  brain tool_use mcp__jarvis-tools__list_tools {"intent":"chercher un contact et son adresse e-mail"}
43  tools.list {"total":28,"recommended":["127.search_contacts","127.search_mail","127.send_mail"],"others":25,"bytes":6963,"catalog_revision":"n136fbd5b.e515109527"}
45  brain tool_use mcp__jarvis-tools__call_tool {"tool_id":"127.search_contacts"}
46  mcp.plugin.tool_called {"plugin_id":"127","tool":"search_contacts","ok":true,"agent":"claude","bytes":49}
47  tools.call {"tool_id":"127.search_contacts","ok":true,"duration_ms":13}
50  brain result success  num_turns 4
```

### (b) Claude subagent — Q1 (brain 2 API turns + background subagent + notification turn)

```
80   brain tool_use Agent {"description":"[fast] Sujet dernier mail Paul Martin","subagent_type":"general-purpose","run_in_background":true}  id …EgZiLG
84   agent.subagent.started {"tool_use_id":"toolu_…EgZiLG","subagent_type":"general-purpose","background":true,"depth":1}
91   sub[parent_tool_use_id=toolu_…EgZiLG] tool_use ToolSearch {"query":"select:mcp__jarvis-tools__list_tools,mcp__jarvis-tools__call_tool"}
94   sub[…EgZiLG] tool_use mcp__jarvis-tools__list_tools {"intent":"chercher des mails par expéditeur"}
96   tools.list {"total":28,"recommended":["127.search_mail","127.send_mail","127.search_contacts","mcp__jarvis-display__scene_query"],"others":24,"bytes":11095}
98   sub[…EgZiLG] tool_use mcp__jarvis-tools__call_tool {"tool_id":"127.search_mail"}  → tool_called ok (l.100-101)
103  sub[…EgZiLG] tool_use mcp__jarvis-tools__call_tool {"tool_id":"127.search_mail"}  → tool_called ok (l.105-106)
114  system task_notification {"status":"completed","usage":{"tool_uses":4,"duration_ms":13506}}
119  agent.unsolicited_result {"origin":"task-notification","spoken":true}
```

The brain's delegation prompt (its own text, l.80) carried the discovery hint from `BRAIN_TOOLS_PROMPT`
(« appelle mcp__jarvis-tools__list_tools … via mcp__jarvis-tools__call_tool ») and no credential; the subagent's
config is the parent process's MCP clients (no file, no token passed by Jarvis).

### (c) Codex — discovery then call, then Q4 (2 turns)

```
125 agent.start "Agent Codex prêt" {"sandbox_mode":"danger-full-access","tools_mcp":true}
130 agent.prompt {"program_id":"backend.codex.turn","prompt_ids":["backend.turn.addition","backend.conversation.tools","backend.turn.brief"]}
132 tools.server_started {"agent":"codex","native_servers":[]}
    codex item mcp_tool_call jarvis-tools list_tools completed {"intent":"chercher l'adresse e-mail de Paul Martin dans mes contacts"}
136 tools.list {"total":3,"recommended":["127.search_contacts","127.search_mail","127.send_mail"],"others":0,"bytes":1205}
    codex item mcp_tool_call jarvis-tools call_tool completed {"tool_id":"127.search_contacts"}
139 mcp.plugin.tool_called {"plugin_id":"127","tool":"search_contacts","ok":true,"agent":"codex"}
--- settings: codex permission_mode = workspace-write (-c sandbox_mode=workspace-write, exec resume)
    codex item mcp_tool_call jarvis-tools list_tools completed {"intent":"chercher le dernier e-mail reçu de Paul Martin et son objet"}
    codex item mcp_tool_call jarvis-tools call_tool FAILED  error "MCP tool call requires approval, but approval policy is never"
    answer: « l'accès à l'outil de recherche a été refusé par la politique d'approbation »
```

(Codex items come from the agent snapshot events; Core logged no `tool_called` for the refused call — Codex never
sent it.)

### (d) Q5 / E17 probe (3 API turns, same session as (a))

```
60  brain tool_use mcp__jarvis-tools__list_tools {"intent":"lire la valeur d'un réglage du Control Center"}
61  tools.list {"recommended":["mcp__jarvis-console__settings_set","mcp__jarvis-console__settings_get","mcp__jarvis-console__settings_describe"],"bytes":…}
66  brain tool_use mcp__jarvis-console__settings_get {"option_ids":[…]}     ← no ToolSearch before it
68  brain tool_result settings_get ok 712 B
```

CLI session file (`~/.claude/projects/…/3204b061-….jsonl`): attachment `deferred_tools_delta` lists 81 deferred
tools including `mcp__jarvis-tools__list_tools`, `mcp__jarvis-tools__call_tool`, every `mcp__jarvis-console__*`
and `mcp__jarvis-display__*`; after turn (d) a `deferred_tools_record` has `entries: []` and
`toolInputCopies: [{"id":"toolu_…ModGTs","copy":"wire"}]` — the CLI accepted the call of a deferred, never-loaded
tool.

## 4. Agent-trace analysis

- **Functional correctness — PASS.** Each scenario reaches the intended plugin tool through the gateway; Core
  journals match the model's calls one to one (`tools.call` ↔ `mcp.plugin.tool_called`); the fake server saw
  8 requests, all with the vault bearer; answers are grounded in the tool results.
- **Architecture — PASS.** Claude: gateway declared by `--mcp-config` with the per-launch native set; ranking in
  the gateway, execution in Core; the subagent used the parent's MCP clients (Q1). Codex: gateway only, empty
  native set, catalog revision `n97d170e1` (natives-free fingerprint) vs `n136fbd5b` for Claude.
- **Tool-call efficiency.** (a) 3 calls (ToolSearch, list_tools, call_tool): minimal given deferral. (d) 2
  calls. (c) 2 calls per turn. (b) subagent 4 tool uses: ToolSearch, list_tools, **two `search_mail` calls** with
  different queries (the address, then the name) — **OPTIMIZATION**: the first already answered; a verification
  habit of the subagent model, not a gateway defect.
- **Redundant calls.** No repeated `list_tools`, no `call_tool` retry after an error, no malformed argument, no
  refused id. The ToolSearch step is required by deferral (Q5), not redundant.
- **Prompt adherence — "re-call list_tools for prerequisites".** Not exercised as a *second* list: in every
  scenario the first `list_tools` already recommended the prerequisite tools (contacts + mail), so no new need
  appeared; Codex turn 2 did call `list_tools` again for the new need (the mail subject) — adherent. The brain
  relayed the discovery hint to the subagent (the rule added for Q1) — adherent.
- **Error/recovery.** Q4 refusal surfaced by Codex as a failed `mcp_tool_call` item and stated honestly to the
  user; no silent swallow. No `error` row in `trace.jsonl` (161 rows).
- **Context cost — OPTIMIZATION (E17-adjacent).** `list_tools` responses 7.0–12.1 KB for Claude; the
  subagent's mail intent still pulled `scene_query` (4.4 KB schema) into `recommended`. E17 keeps native schemas
  (they are the only schema the model gets, §5); a stricter native threshold remains the lever (Slice 08).
- **FLAGGED (environment, not this slice).** `agent.subagent.conversation_unattributed` and
  `core.brain.notice_dropped {"reason":"no_current_source"}` — the isolated run had no voice/Core conversation;
  the `[fast]` subagent ran on `claude-opus-5-5` (routing policy of the isolated settings, not a gateway matter);
  `agent.turn_over_budget` 8.8 s > 8 s on the delegation turn.
- **Missing evidence.** The model-facing request body (tool definitions with `defer_loading`) is not captured;
  deferral is proven from the CLI's own session attachments instead.

## 5. Q1, Q4, Q5, E17

- **Q1 — subagents inherit `--mcp-config` servers: YES.** A `general-purpose` background subagent
  (`parent_tool_use_id` set on its events) loaded and called `mcp__jarvis-tools__*` with no configuration from
  Jarvis. The `--agents` fallback (ARCH §8.3) is not built.
- **Q4 — Codex approvals.** `danger-full-access` (CC default, bypass flag): both tools run. `workspace-write`
  (`codex exec`, approval policy `never`): `list_tools` (read-only annotation) runs; `call_tool` (destructive
  annotation) is refused by Codex, « MCP tool call requires approval, but approval policy is never ». V1 keeps
  it (gateway follows the CLI permission mode, consistent with Q3); `default_tools_approval_mode` exists in
  codex 0.157.0 but is not wired (product decision).
- **Q5 — `jarvis-tools` is deferred behind ToolSearch** (both the brain and the subagent load it with
  `ToolSearch select:…` first; `deferred_tools_delta` lists it). The prompt names both tools in full.
- **E17 — natives are deferred but directly callable after `list_tools`** ⇒ a native `recommended` entry
  **keeps** `input_schema` (test `test_e17_a_recommended_native_keeps_its_full_input_schema`, docstring of
  `tool_discovery`, plugins.md §6.3).

## 6. Secret sentinel and processes

- `grep -r "SENTINEL-SECRET-7f3a"` over the isolated `runtime/` (`trace.jsonl`, `tools-mcp.json`,
  `display-mcp.json`, `console-mcp.json`, settings, crash logs), Core and CC stdout logs, the Claude session file,
  the Codex rollout of the run and the isolated SQLite files: **0 matches**. Argv (agent.start / Codex argv) holds
  paths only.
- Stopped: Control Center (which had already stopped the Claude brain on the switch), Core, fake server (stop
  file). Process list after the run compared with the list taken before: no process of this run left (the only
  new processes belong to the concurrent QA agent).

## 7. Deviations and notes

- `BRAIN_TOOLS_PROMPT` is one layer `backend.conversation.tools` shared by the four Claude programs and
  `backend.codex.turn` (the SLICE says "Codex prompt gets the same guidance through its prompt target"); Codex has
  no system channel, so it travels with each composed turn (+669 B per Codex turn).
- `mcp_catalog.advertised_from_agent_snapshot` reads `running` **or** `ready` (Codex between turns); Claude never
  reports `ready`, the native servers stay `false` for Codex through the missing attribute.
- `test_brain_delegation::test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available` stays red
  with the same assertion: it compares the whole appended prompt to `BRAIN_SYSTEM_PROMPT` alone; the settings
  layer already made it fail, the tools layer appends after it. Not worse; fixing it belongs to its owner.
- Cost: Claude session `total_cost_usd` **$0.61** cumulative (4 brain turns + 1 subagent); Codex 2 turns,
  164 k + 278 k input tokens (138 k / 246 k cached), 409 + 687 output tokens (subscription, no USD figure).
  7 real model turns + 1 subagent (budget ≤ 12).

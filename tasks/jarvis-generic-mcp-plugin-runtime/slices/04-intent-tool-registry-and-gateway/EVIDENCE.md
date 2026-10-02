# Slice 04 — Evidence

Branch `task/jarvis-generic-mcp-plugin-runtime`, base `357722b`. Commits:
`bb336ea` (domain relevance + discovery), `5586efe` (Core `/v1/mcp/tools*`),
`071f881` (redaction of credential pairs), `a66a21d` (gateway + merged
catalog), `655cc39` (contract docs), and the commit that adds this file.
2026-09-30, Windows 11, Python 3.14.6, `mcp` 1.30.0, foreground pytest
(`.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`), chunks ≤ 30 files.

## 1. Pytest

| Command scope | Result |
| --- | --- |
| New/changed + every `test_mcp*` + `test_control_center_mcp*`: `test_tool_relevance.py`, `test_tool_discovery.py`, `test_tools_gateway_mcp.py`, `test_mcp_catalog.py`, `test_mcp_endpoint_policy.py`, `test_mcp_http_policy.py`, `test_mcp_oauth_adapter.py`, `test_mcp_plugin_domain.py`, `test_mcp_plugin_service.py`, `test_mcp_plugin_store_sqlite.py`, `test_mcp_protocol_routes.py`, `test_control_center_mcp_api.py`, `test_control_center_mcp_inspector_js.py` (13 files) | **579 passed** |
| `test_display_mcp.py`, `test_settings_mcp.py`, `test_v2_architecture.py`, `test_app.py` | **151 passed** |
| Protocol/Core units: `test_back_brain_protocol.py`, `test_board_protocol.py`, `test_brain_outcome_protocol.py`, `test_core_brain_outcomes.py`, `test_interaction_mode_protocol.py`, `test_live_lifecycle_protocol.py`, `test_session_protocol.py`, `test_voice_admission_protocol.py`, `test_voice_ledger_protocol.py`, `test_schema_migrations.py` | **165 passed** |
| `tests/integration/test_remote_mcp_connector.py` + `tests/integration/test_tools_gateway_e2e.py` | **32 passed** (62 s). A first run gave 1 failure, `test_step_up_403_during_connect_then_reconnect_widens_the_scope` (`last_error_code=mcp_remote_timeout` under the 2 s test timeouts while the host was loaded); it passed alone 4/4 and in the full rerun. Timing flake of Slice 03's test, not a Slice 04 path (reported). |
| `CoreSessionTransport` users (`_twice` now delegates to `replay_on_401`): `test_board_brains_control_center.py`, `test_board_switch_control_center.py`, `tests/integration/test_board_session_e2e.py`, `test_conversation_event_forwarder.py`, `test_routing_hook.py` | **88 passed** |

No failure outside READINESS §Baseline.

## 2. Acceptance → proof

| Acceptance bullet | Test(s) |
| --- | --- |
| `jarvis-tools` passes every native parity gate | `test_mcp_catalog.py` parametrized over `SERVERS` (now incl. `jarvis-tools`): `test_metadata_and_the_real_server_list_the_same_tools_in_the_same_order`, `test_advertised_annotations_are_the_ones_derived_from_the_metadata`, `test_the_catalog_is_what_a_client_reads_in_tools_list`; amended `test_no_catalog_meta_tool_is_advertised_and_the_scene_stays_within_thirteen` (exempts `jarvis-tools` only, asserts exactly `list_tools`, `call_tool`) |
| Context ≤ 2 500 B, instructions ≤ 1 200 B, display/console unchanged | `test_tools_gateway_mcp.py::test_context_budgets_of_the_gateway` (measured 1 544 B / 584 B); unchanged gates `test_the_display_context_cost_stays_within_the_slice_04_baseline`, `test_the_console_server_instructions_stay_within_their_budget` |
| ≤ 5 full recommended, compact others ≤ 120, cursor, revision, ≤ 24 576 B on 500 tools, intents differ, stale cursor ⇒ `catalog_changed` | `test_tool_discovery.py` (`test_five_hundred_tools_fit_the_whole_response_budget`, `test_at_most_five_recommended_and_only_above_the_relative_threshold`, `test_an_entry_over_sixteen_kib_is_never_recommended_but_listed_too_large`, `test_cursor_pages_through_every_tool_once`, `test_a_stale_cursor_restarts_at_zero_with_catalog_changed`, `test_a_cursor_for_another_intent_is_refused`, `test_different_intents_give_different_recommendations`); gateway: `test_five_hundred_external_tools_stay_within_the_response_budget`, `test_a_new_revision_restarts_a_cursor_with_catalog_changed`, `test_natives_are_direct_with_call_as_and_different_intents_differ` |
| Natives = `JARVIS_TOOLS_NATIVE_SERVERS` − `jarvis-tools`; `jarvis-drive` never | `test_list_tools_lists_declared_natives_and_plugins_with_full_recommended`, `test_the_operator_server_is_never_listed_even_if_declared` |
| Disabled/disconnected absent from `list_tools`; call codes; native ⇒ `native_tool_call_directly` + `call_as`; unknown ⇒ `mcp_tool_unknown` | `test_mcp_plugin_service.py::test_external_tools_lists_enabled_connected_tools_and_every_plugin`, `test_call_on_a_disabled_or_disconnected_plugin_is_refused_with_its_code`, `test_call_refusals_happen_before_any_network`; routes `test_call_on_disabled_then_disconnected_plugin_is_409`, `test_call_refusals_keep_their_code_and_status`; gateway `test_a_native_name_is_refused_with_call_as_and_never_reaches_core`, `test_core_refusals_become_coded_tool_errors_with_a_next_step` |
| Bounds: args ≤ 64 KiB + required/closed; result ≤ 32 KiB `truncated`; remote error redacted ≤ 4 KiB; timeout 60/120 | `test_call_refusals_happen_before_any_network` (64 KiB, required, closed), `test_call_result_is_cut_at_thirty_two_kib_and_non_text_is_summarized`, `test_a_remote_tool_error_is_redacted_bounded_and_ok_false`, `test_call_timeout_defaults_to_sixty_and_is_capped_at_one_twenty`, routes `test_call_passes_a_bounded_timeout`, `test_call_refuses_malformed_bodies` |
| Recall@3 ≥ 0.9 on ≥ 20 FR/EN intents; deterministic | `test_tool_relevance.py::test_recall_at_3_is_at_least_ninety_percent` (26 intents, recall 0.923), `test_the_fixture_ranking_is_byte_identical_across_runs`, `test_tool_discovery.py::test_same_input_gives_a_byte_identical_response`, `test_tools_gateway_mcp.py::test_the_same_call_is_byte_identical` |
| CC `/api/mcp/tools`: natives when Core down (`plugins` unavailable), plugin descriptors + detail when up, no secret | `test_control_center_mcp_api.py::test_natives_are_still_served_when_core_is_down` (no transport / refused / > 2 s), `test_the_merged_list_serves_plugin_servers_and_tools_and_caches_by_revision`, `test_the_detail_of_a_plugin_tool_is_its_full_descriptor`, `test_no_plugin_secret_reaches_a_merged_response`, `test_core_down_is_journaled_once_then_the_recovery`; catalog `test_merge_with_core_down_keeps_natives_and_says_core_unreachable` |
| Tool-list mutation on the fake server ⇒ new `catalog_revision` at the next `list_tools` | `tests/integration/test_tools_gateway_e2e.py::test_list_call_relist_call_over_the_real_core_and_remote_server` (real SDK + fake remote, `notifications/tools/list_changed`); unit `test_a_tool_list_change_is_a_new_external_revision` |

The two relevance misses of the fixture (kept, not tuned away): « écrire un
brouillon de mail sans l'envoyer » (`create_draft` 4th: the negation is not
understood, `search_emails` wins on the `drafts` enum) and « créer une réunion
jeudi à 10h » (`create_event` 4th behind native `create` tools: a French
intent reaches the English tool only through synonyms at 0.6).

## 3. Recorded `list_tools` responses (real Core, fake remote plugin)

Source: `tests/integration/test_tools_gateway_e2e.py::scenario` (in-memory MCP
client → real `jarvis-tools` → real `LocalProtocolServer` + `McpPluginService`
→ `SdkRemoteMcpConnector` → fake remote server + fake OAuth AS on 127.0.0.1;
natives declared: `jarvis-console`, `jarvis-display`). Bytes = the contract
measure (compact JSON, UTF-8) of the `structuredContent` the client received.
Plugin id `127` (first DNS label of `127.0.0.1`), display name `Fake Remote`.

| # | Intent | Bytes | Recommended (bytes each) | Others | `catalog_revision` |
| --- | --- | ---: | --- | --- | --- |
| 1 | « répondre au dernier mail de Paul » | **13 082** | `127.search_mail` (312), `127.send_mail` (374), `scene_add_artifact` (3 371), `scene_create_object` (3 205) — part 7 267 | 25 (5 661 B), `next_cursor: null`, total 29 | `n136fbd5b.e723259752` |
| 2 | « trouver l'adresse email de Paul » | **11 236** | `127.search_contacts` (303), `127.search_mail` (312), `127.send_mail` (374), `scene_query` (4 389) — part 5 383 | 25 (5 701 B), total 29 | `n136fbd5b.e723259752` |
| 3 | « archiver un mail » (after the remote list mutation) | **10 697** | `127.archive_mail` (267), `127.search_mail`, `127.send_mail`, `board_archive` (734), `scene_archive` (3 202) — part 4 895 | 25 (5 665 B), total 30 | `n136fbd5b.e723259753` |

Recommended entry, verbatim (response 1):

```json
{"id":"127.send_mail","name":"send_mail","invocation":"managed_external","source":"Fake Remote",
 "description":"Send an email to a recipient email address.",
 "input_schema":{"additionalProperties":false,"properties":{"body":{"type":"string"},"to":{"description":"Recipient email address","type":"string"}},"required":["to","body"],"type":"object"},
 "side_effect":"destructive"}
```

Native recommended entries carry `"invocation":"direct_native","call_as":"mcp__jarvis-display__…"`.
Compact entry, verbatim (response 1): `{"id":"127.search_contacts","summary":"Search the user's contacts by name; returns their email address.","source":"Fake Remote","side_effect":"read","invocation":"managed_external"}`.

## 4. Agent-trace analysis — in-memory client transcript

**Scenario and source.** A scripted client (the "brain") on the real
`jarvis-tools` server, through real Core and a real remote MCP session
(§3). Trace sources: the client transcript (arguments, results, bytes,
durations) and the one `runtime/trace.jsonl` shared by Core and the gateway
(28 rows). Model-side prompts are **not** in scope: Slice 05 declares the
gateway to the real CLIs and records real-model traces.

**Execution path.**

| # | Call | Result | Bytes | ms |
| --- | --- | --- | ---: | ---: |
| 1 | `list_tools {"intent":"répondre au dernier mail de Paul"}` | ok, 4 recommended (search_mail, send_mail + 2 display natives) | 13 082 | 310 (first call builds the native catalog) |
| 2 | `call_tool 127.search_mail {"query":"Paul"}` | ok `search_mail ok {"query": "Paul"}` | 32 | 26 |
| 3 | `list_tools {"intent":"trouver l'adresse email de Paul"}` (prerequisite: the address) | ok, `127.search_contacts` first | 11 236 | 81 |
| 4 | `call_tool 127.search_contacts {"name":"Paul"}` | ok | 35 | 30 |
| 5 | `call_tool 127.send_mail {"to":"paul@example.com","body":"Bien reçu."}` — schema from step 1, **no second lookup** | ok | 66 | 28 |
| 6 | `call_tool 127.leak_error {}` | `isError`: `mcp_remote_tool_error : the plugin tool reported an error\nupstream said: Authorization: Bearer [secret masqué] token=[secret masqué]` | 134 | 31 |
| 7 | remote list mutation + `notifications/tools/list_changed`, then `list_tools {"intent":"archiver un mail"}` | ok, `127.archive_mail` first, revision `…e723259752` → `…e723259753` | 10 697 | 83 |

Journal (codes and ids only), in order: `mcp.plugin.created`,
`connecting`, `authorization_pending`, `connected` (tool_count 4),
`oauth_completed`; then per step `tools.list` {intent_chars, total,
recommended ids, others, next_cursor, catalog_revision, notes, bytes,
duration_ms}, `mcp.plugin.tool_called` {plugin_id, tool, ok, code, agent,
duration_ms, bytes} + `tools.call` {tool_id, ok, code, duration_ms} for each
call (step 6: both `warning`, code `mcp_remote_tool_error`),
`mcp.plugin.tools_changed` {capability_revision 2, tool_count 5}, final
`tools.list`, `mcp.plugins.stopped`.

**Findings.**

- **Functional correctness — PASS.** Every call reaches its intended tool; the
  prerequisite re-list surfaces `search_contacts` first; the mutation is
  visible at the very next `list_tools` (new `e` part, same native `n` part).
- **Tool-call quality — PASS, no redundant call.** The remote server saw
  exactly four `tools/call` (`search_mail`, `search_contacts`, `send_mail`,
  `leak_error`), asserted by the test. `send_mail` was called from the full
  schema of step 1 without another lookup; no malformed argument, no retry.
- **Architecture — PASS.** Ranking ran in the gateway (C2): Core logged no
  ranking, only `tool_called`; the external part was served from the
  revision cache (a second read with `since_revision` returned `unchanged`,
  unit `test_the_external_part_is_cached_by_revision`); natives were limited
  to the two declared servers; the token was read from its file.
- **Secrets — PASS.** The sentinel carried by the OAuth tokens and by the
  remote error text is absent from the transcript, the Core responses and
  `trace.jsonl` (asserted). This scenario **found a leak before the fix**:
  the remote text `token=<sentinel>` was not a vault value, nor `Bearer`, nor a
  JWT, so the ARCH §9 redaction let it through. Fixed in `071f881`
  (credential `key=value` pairs are masked; plugins.md §8.2).
- **Error visibility — PASS.** The remote error is an MCP tool error with a
  stable code and a next step, journaled at `warning` in both processes.
- **OPTIMIZATION — context cost per `list_tools` (10.7–13.1 KB).** Native
  display tools are expensive when recommended (`scene_add_artifact`
  3 371 B, `scene_query` 4 389 B) and entered the top 5 for mail intents on
  weak matches (« mail » in their long French descriptions) because they
  cleared 0.35 × top. Options for Slice 05/08: a higher relative threshold
  for natives the brain already sees in its tool list, or never recommending
  a native in full (the CLI already carries its schema — `call_as` alone
  suffices). Not changed here: the 0.35 threshold is ARCH-binding.
- **FLAGGED — duplicate records for a failed remote call.** A transport-level
  call failure (not step 6) is recorded as `mcp.plugin.refused` (the service
  operation wrapper) **and** `mcp.plugin.tool_called` with the same code — the
  same double record Slice 03's `invoke` already had. Harmless, noted for QA.
- **Missing evidence.** No real model: whether a model re-lists on its own for
  a prerequisite, and how `ENABLE_TOOL_SEARCH` defers the gateway (Q5), is
  Slice 05's trace obligation.

## 5. Contract sync

`docs/mcp/plugins.md` (status lines, §6.1/§6.4/§7 implemented, §8.1 route
rows, §8.2 redaction addition, new §13 implementation facts and deviations)
and `docs/mcp/tool-contract.md` (§1, §3, §4.3, §5.3, §8 status flips; merged
view facts) in `655cc39`; `docs/OPERATIONS.md` inspector line in `a66a21d`.

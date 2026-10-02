# Slice 08 — Evidence (phase A: everything without the live Circuit Toolbox login)

Branch `s8/phase-a` (worktree `C:/Projects/jarvis/bqa`) from `e081a94`. Date 2026-09-30.
Python `C:/Projects/jarvis/jarvis/.venv` with `PYTHONPATH=C:/Projects/jarvis/bqa` (`import jarvis` → bqa, checked).
Commits: `308a3f1` (sentinel + restart tests), `86df083` (budgets), `ab26563` (inspector `<pre>`),
`a0e114a` (docs, ARCH §15/§16, Issues), this file + LOG in the last commit.

## 1. Full regression (foreground, `-q -p no:cacheprovider`, ≤ 30 files per chunk, ≤ 590 s each)

`tests/unit`: 349 files in 12 alphabetical chunks (30 × 11 + 19).

| Chunk | Passed | Failed | Skipped | Failures |
| --- | --- | --- | --- | --- |
| u00 | 808 | 1 | 0 | `test_back_brain_tasks::test_persistent_transition_failure_keeps_owner_and_stop_bounded_until_recovery` — **flake** (passed 3/3 alone, file 34/34) |
| u01 | 666 | 2 | 1 | `test_barehands_interaction_js` ×2 — READINESS baseline |
| u02 | 446 | 1 | 0 | `test_brain_delegation::test_the_voice_agent_starts_with_the_rule…` — READINESS baseline |
| u03 | 792 | 0 | 0 | — |
| u04 | 925 | 1 | 2 | `test_interaction_mode_hud_browser::test_le_mouvement_reduit_arrete_vraiment_le_halo` — **flake** (headless Chrome; 2/3 file reruns green) |
| u05 | 861 | 0 | 1 | — |
| u06 | 1 266 | 0 | 1 | — |
| u07 | 1 126 | 5 | 0 | `test_scene_group_drag_js` ×5 — READINESS baseline |
| u08 | 844 | 0 | 1 | — |
| u09 | 1 455 | 0 | 0 | — |
| u10 | 543 | 0 | 0 | — |
| u11 | 759 | 0 | 0 | — |
| **unit total** | **10 491** | **10** | **6** | 8 = READINESS baseline, unchanged; 2 = load flakes of pre-existing tests |

`tests/integration`: every non-live file (64; the 7 `test_live_*` excluded), 3 chunks.

| Chunk | Passed | Failed | Skipped |
| --- | --- | --- | --- |
| i00 (27 files) | 307 | 0 | 1 |
| i01 (27 files) | 230 | 0 | 13 (opt-in hardware/real-state) |
| i02 (10 files) | 82 | 0 | 0 |
| **integration total** | **619** | **0** | **14** |

Baseline comparison (READINESS, D0 `52458ed`): 9 628 passed, 8 failed, 5 skipped. Now 10 491 passed: the
handoff's tests, and the same 8 baseline failures, none worse. The two flakes are not in the baseline list and are
not this task's: no handoff commit touches their files or the code under them (`git log main..HEAD`). Both pass
when rerun. They are filed in `Issues/load-sensitive-flaky-tests.md`.

## 2. Secret sentinel (`tests/unit/test_mcp_secret_sentinel.py`)

Two parametrized runs, `bearer` and `oauth`. Each run takes the full path: create, then credential (`PUT …/credential`) or OAuth consent (CC `GET /api/mcp/oauth/callback`), then connect, list, call, disconnect and delete. The layers are all real: Control Center relay → `CoreSessionTransport` → `LocalProtocolServer` → `McpPluginService` → `SdkRemoteMcpConnector` → fake RS + AS on 127.0.0.1. The `jarvis-tools` gateway is driven by an in-memory MCP client.

What the test scans:
- 11 `/api/*` responses per run: create, credential or consent, connect, plugins list/get/refresh, `/api/mcp/tools`, a tool descriptor, disconnect and delete.
- 5 `/v1/mcp/*` responses: plugins, plugin, tools, call ok, call with a remote error quoting the secret.
- 3 model results: `list_tools`, `call_tool` ok, `call_tool` error.
- `tools-mcp.json` and the Codex `-c` argv.
- Every file under the test root, including `runtime/trace.jsonl` and `errors.jsonl`.
- The raw bytes of `jarvis.sqlite3` and its `-wal`.

Results:

| Check | bearer | oauth |
| --- | --- | --- |
| sentinel reached the remote server (proves the test exercises the secret) | yes | yes |
| sentinel in any response, model result, config or run file | **none** | **none** |
| DB while connected | sealed marker present, plaintext absent | same |
| DB after the run | plaintext absent | same |

Mutation: removing `redact(...)` from the remote-error branch of `call_outcome` (`jarvis/domain/mcp_plugins.py`) → **2 failed**, with the leaks named as `/v1/mcp/tools/call leak` and `model call_tool`. After reverting it passes again. The CLI stream-json transcripts are out of this unit test's reach. Slice 05 scanned them (no leak), and the final live scan is phase B.

## 3. Restart persistence (`tests/integration/test_mcp_plugin_restart.py`)

The setup is one Core life, then a second Core life on the same `data_root` with a fresh `FakeSealer` and no Control Center. Five fake servers:

| Plugin | First life | After the Core restart |
| --- | --- | --- |
| `oauth` (valid token, no refresh) | authorized, connected | **connected** by itself, 0 new `/authorize`, a tool call is ok |
| `expiring` (token 1 s, no refresh) | authorized, connected | **`expired`/`disconnected`**, **0 requests** to its servers, `mcp.plugin.expired_at_boot` |
| `bearer` | authorized, connected | **connected** by itself |
| `open` (no auth) | not_required, connected | **connected** by itself |
| `paused` (bearer, then disabled) | enabled=false | **disabled, disconnected, 0 requests** |

- `mcp.plugins.boot_reconnect.plugin_ids` = {oauth, bearer, open} exactly.
- Registry rows (`enabled`, `credential_ref`) and all 4 sealed blobs are byte-identical before and after.
- **Control Center restart**: two successive CCs in front of the same Core return an identical `/api/mcp/plugins`. Core state is unchanged, and the remote servers see 0 new requests.

Mutations:
- Boot reconnect ignoring `enabled` → fails (`paused` connected).
- Skipping the expiry check → fails (no `expired_at_boot`).

Stable: 3/3 reruns together with the sentinel test (3 passed in ~8 s each).

## 4. Budgets re-measured on the final surface (2026-09-30)

| Measure | Bytes | Bound |
| --- | --- | --- |
| `jarvis-tools` context: `list_tools` / `call_tool` / total | 923 / 621 / **1 544** | 2 500 |
| gateway instructions | 584 | 1 200 |
| `BRAIN_TOOLS_PROMPT` | 669 | — |
| `list_tools`, natives display+barehands+console, 500 heavy plugin tools, first page: « envoyer un mail à Paul » / « qu'est-ce qui est affiché sur la scène » / « calibrer le geste de pincement » / « lister les boards » / empty | 19 003 / 17 913 / 20 501 / 17 182 / 15 609 | 24 576 |
| same, largest of the 9 cursor pages | 20 501 | 24 576 |
| same intents, 3 realistic mail tools | 4 248 / 2 973 / 5 561 / 2 242 / 669 | 24 576 |
| domain worst case (500 tools, descriptions 4 000 B, 8 × 200-char props, limit 60), largest page over 8 pages: « chercher un outil 042 pour le mail » / empty / « agenda de demain » | 23 428 / 15 118 / 23 469 | 24 576 |
| native context (unchanged gates): display / console / barehands / drive | 31 864 / 9 616 / 20 515 / 2 126 | 33 090 / 10 000 / — / — |
| real Circuit Toolbox `list_tools` | **phase B** | 24 576 |

New assertions:
- `test_tool_discovery.py`: `test_s8_the_response_budget_is_still_the_contract_value`, and `test_s8_every_page_of_a_heavy_500_tool_catalog_stays_within_the_budget` over 4 intents.
- `test_tools_gateway_mcp.py`: `test_s8_context_cost_of_the_final_gateway_surface`, and `test_s8_list_tools_over_every_declared_native_and_500_plugin_tools_stays_bounded` over 5 intents.

The display and console gates in `test_mcp_catalog.py` (`DISPLAY_CONTEXT_BASELINE_BYTES = 33_090`, `CONSOLE_CONTEXT_BUDGET_BYTES = 10_000`) are unchanged: the diff `main...HEAD` touches neither constant.

## 5. Carried fix: inspector raw schema

Both « Schéma brut (JSON) » `<pre>` blocks now carry `tabindex="0" role="region" aria-label="Schéma brut d’entrée (JSON)"` (and the same for « de résultat »). `control_center.html` adds `.mcpi-raw pre:focus-visible` to the shared focus ring. This fixes axe `scrollable-region-focusable`.

The plugin sheet reuses `detailHtml`, so the fix covers it too. Test: `test_control_center_mcp_inspector_js.py::test_the_raw_schema_blocks_are_keyboard_focusable_named_regions`. Inspector and plugins JS: 95 passed.

## 6. Documentation (checked against the code)

- `docs/ARCHITECTURE.md` gets a note in *Processes* and a new `##` *Core-owned MCP plugin runtime and the `jarvis-tools` gateway*, covering topology, the ownership table, enforced rules, the propagation matrix and the known `--strict-mcp-config` fact.
- `docs/SECURITY.md` gets control **§15**: DPAPI threat model, endpoint/SSRF policy, icons, OAuth (PKCE, state, TTL, `iss`, issuer-bound revocation), redaction (paging exemptions and the accepted prose trade-off, probed: « your token: abc123 » passes), Codex argv and permission mode. Three residual-risk lines are added.
- `docs/OPERATIONS.md` extends the existing French section « Plugins MCP externes » instead of duplicating it:
  - two table rows (`expired`, `mcp_oauth_timeout`, « Autorisation interrompue »);
  - « Exploiter les plugins », covering the lifecycle, Core/CC restarts, `JARVIS_UI_PORT` and the OAuth redirect, `JARVIS_MCP_ALLOW_LOOPBACK_HTTP`, recovery, v4 backup/rollback and the known fact;
  - the `JARVIS_UI_PORT` table row.
- `docs/state-model.md` gets the v4 table with columns and invariants, plus the plugin consequences of rollback and of a DB copied to another user.
- `docs/mcp/tool-contract.md` changes its status line to implemented and adds **§10.10** *Implementation facts* (release).
- `docs/mcp/plugins.md` changes its status to implemented, keeps what is pending in phase B, adds the Slice 08 tests to §12, and adds **§15** Release facts (numbers, sentinel, restart, pending phase B, known fact).
- Doc tests: `test_documented_routes.py` and `test_published_benchmark_figures.py` give 25 passed.

## 7. ARCH §15 open questions

| Q | Disposition | Evidence |
| --- | --- | --- |
| Q1 | closed | E19, Slice 05 trace |
| Q2 | closed | Slice 07 phase A, plugins.md §14 |
| Q3 | decided for V1 (no gate) — **filed** `Issues/q3-destructive-plugin-tool-confirmation.md` for Human confirmation at acceptance | READINESS, E19, SECURITY §15 |
| Q4 | closed | E19, E20 |
| Q5 | closed | E17, E19, E21 |

ARCH gains two additions:
- the dispositions table under §15;
- **E24** (dated): shipped vs designed. The sealed OAuth payload keys, and `ConnectOutcome` having no `failed` status, both differ from the design; the known `--strict-mcp-config` fact is recorded. §13 lists the Slice 08 tests.

## 8. Remaining for phase B

- Circuit Toolbox after login:
  - the real `list_tools` bytes;
  - the §14 rows (transport, token lifetime, refresh, tool count, rejected tools, one read-only call, disable/re-enable, disconnect/reconnect, expiry);
  - a Drive brain turn (Slice 07).
- The final Brain and delegated-subagent traces through `jarvis-tools`, with agent-trace analysis, and the final live secret scan of the CLI transcripts.
- Control Center accessibility and visual validation in a real browser (axe on the final page), and HV-06-01 / HV-07-01.
- The Human's confirmation of Q3.

Scratch files (`s8a_*`) were deleted at the end. No process or port is left.

# Slice 00 — Readiness report

- Date: 2026-09-30
- Branch: `task/jarvis-generic-mcp-plugin-runtime`, created from `origin/main@96a9396` (no `dev` branch exists in this repository); to be rebased onto the D0 fix branch before Slice 01.
- Planning snapshot: `main@58eeb18` (handoff), one commit behind the branch point (`96a9396`, local data moved out of the repo, versioned schema migrations mandatory — see CLAUDE.md).
- Handoff origin: remote (Drive `to-do/jarvis-generic-mcp-plugin-runtime`, folder id `1vF3XhJrCXLD7AlDxidSPXgaZVdQMCEtP`). The Drive connector cannot move folders: the Human moves it to `current`.
- Human delegated full autonomy for planning/QA decisions (standing instruction). Decisions below marked "agent 0" were taken under it.

## Declared state

**`READY`** (2026-09-30): D0 landed on `fix/main-merge-loss-2026-09-30` (code review of that branch running in parallel; any correction lands there and is rebased in), task branch rebased, post-D0 baseline below.

## Decisions

- **D0 (agent 0) — `origin/main` does not import.** Merge `b8c3ba1` (Board session task × voice stale speech task) silently dropped one side: `READY_SETTLE_S` (claude_local), `BRAIN_SPEECH_WITHHELD_KIND`, `ControlCenterBoardHost`, `SpeechScheduler._rebinding_to`, the Board/Session wiring of `core/v2_app.py`. At `96a9396`, 322 of ~6 600 unit tests fail, 116 files cannot import — including every MCP test this task relies on (`test_mcp_catalog`, `test_control_center_mcp_api`, `test_settings_mcp`, `test_display_mcp`, `test_control_center_mcp_inspector_js`). Precedent `tasks/mainfix-2026-09`: restoration on `fix/main-merge-loss-2026-09-30` (worktree `C:/Projects/jarvis/bfix`, log `tasks/mainfix-2026-09-30/MAINFIX-LOG.md`); this task branch is based on it; `main` untouched; merging the fix into `main` stays the Human's call.
- **D-TT (agent 0) — Workspace Task Type gate waived**, as for the five previous handoffs: the vocabulary does not exist in this workspace. `task_type` stays `null` in every Slice `metadata.json`.
- **D1–D12 (agent 0)** — design decisions, resolved against the code in `docs/06-resolved-architecture.md`, which is **binding**. Its §14 lists 12 contradictions where the code corrected a decision (notably C1: Core and the Control Center are two processes — Core owns registry/vault/connections/OAuth/execution, the CC relays; C2: ranking runs in the gateway process because Core may not import the native catalog).
- **Q2 (agent 0)** — dynamic client registration requests `grant_types=["authorization_code","refresh_token"]` only when the AS metadata lists `refresh_token` in `grant_types_supported`; otherwise `["authorization_code"]`. (Circuit Toolbox lists only `authorization_code`.)
- **Q3 (agent 0)** — no confirmation gate for `destructive` external tools in V1 (native write tools have none; brain runs under the CLI permission mode). Descriptors carry `side_effect` conservatively (MCP default = destructive). Slice 07 calls read-only tools only. Revisit with the Human at acceptance.
- **Q1, Q4, Q5** — proven by trace in Slice 05 (subagent inheritance of `--mcp-config` servers, Codex MCP approval in sandbox modes, ToolSearch deferral of the gateway).

## Blind audit — facts that shape the plan

1. No MCP client, plugin registry, user-configurable server, vault or keyring exists. `mcp 1.30.0` is installed (`streamable_http`, `client/auth/oauth2.py` unused), `httpx 0.28.1`.
2. Only catalog consumer is the Control Center (`control_center.py:4720-4791`); catalog = FastMCP introspection of 4 hard-coded servers; missing meta for one tool fails the whole catalog.
3. `jarvis-drive` is operator-registered (`claude mcp add --scope user`), OAuth files at env paths; three Drive paths share `adapters/google_drive.py`. Classified legacy, not migrated (D10).
4. Subagents are launched by the Claude CLI, not by Jarvis. Codex receives no Jarvis MCP; codex-cli 0.157.0 accepts `-c mcp_servers.<name>.*` (verified, including through the `codex.cmd` shim).
5. Restricted profiles `speculative_analysis` (no tools) and `presentation_preparation` (Read/Glob/Grep/Web only) run `--strict-mcp-config`: unchanged.
6. Plaintext secrets today: `runtime/control-center-settings.json` via `credentials.py` — **not** reused for plugin secrets.
7. `docs/mcp/tool-contract.md` §5.3 forbids model-facing `list_tools`/`get_tool` and `test_mcp_catalog.py:188-195` enforces it — both amended deliberately (Slices 01, 04). Stale: barehands listed with 5 tools, has 16.
8. Live target probe: `POST https://circoetoolbox-server-production.up.railway.app/mcp` → 401 `WWW-Authenticate: Bearer resource_metadata=…/.well-known/oauth-protected-resource, scope="mail calendar contacts"`; AS: DCR, PKCE S256, public client (`none`), `authorization_code` only (no refresh), `authorization_response_iss_parameter_supported: true`. ⇒ HV-07-01 (Human login) is required; tokens expire without refresh ⇒ "Reconnecter" path must work.
9. Parallel branches: `task/jarvis-board-session-context-runtime` and `task/jarvis-mcp-semantic-batch-inspector` have no commit missing from HEAD on any MCP path. No freshness conflict besides D0.

## Baseline

Measured at `96a9396` in detached worktree `C:/Projects/jarvis/gbase`, 12 foreground chunks, `--continue-on-collection-errors`: ~6 595 collected, 6 301 passed, 168 failed, 122 errors, 4 skipped (all traced to D0). Raw outputs were in the session scratchpad (not durable).

**Post-D0 baseline** (fix branch `eaabe85`, full `tests/unit` in foreground chunks): 9 622 passed, **13 failed**, 0 errors, 5 skipped; `tests/integration --collect-only` 606, no error. Task branch rebased onto `eaabe85` (2026-09-30).

"Not yours, do not fix" list — every implementer receives it:
- `tests/unit/test_barehands_interaction_js.py` (2) — pre-existing before `b8c3ba1` (fails at base `202333d`).
- `tests/unit/test_scene_group_drag_js.py` (5) — same.
- `tests/unit/test_brain_delegation.py::test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available` (1) — same (prompt also contains `BRAIN_SETTINGS_PROMPT`). **Slice 05 note:** adding `BRAIN_TOOLS_PROMPT` touches the same assertion; Slice 05 must not make it worse and should document it.
- ~~`tests/unit/test_environment.py` (5)~~ — fixed on the D0 branch (`67ac298`).

Update 2026-09-30: D0 branch final at `52458ed` after code review (M1: `_relay_conversation` removed; m1: single alert). Full unit suite there: 9 628 passed, **8 failed** (the three items above), 0 errors, 5 skipped; board/session/voice integration 69 passed, 5 skipped (opt-in). Task branch rebased onto `52458ed`.

Any other failure is the current Slice's.

## Reuse obligations

| Need | Existing implementation |
| --- | --- |
| Native catalog, descriptors, availability | `jarvis/runtime/mcp_catalog.py`, `mcp_tool_meta.py` |
| Stdio MCP server reaching Core with the token file | `display_mcp.py` `DisplayMcpTarget` + `runtime/core_forwarder.py` `CoreLoopbackTransport` |
| CC → Core relay routes | `runtime/board_routes.py` + `core_sessions.CoreSessionTransport.forward` |
| Core adapter injection | `app.py:_run_core_v2` (precedent `drive_backend`) + `CORE_ADAPTER_IMPORT_EXCEPTIONS` |
| SQLite migrations + snapshots | `adapters/sqlite_state.py` `_MIGRATIONS`, `tests/schema/*.sql`, `test_schema_migrations.py`, CLAUDE.md |
| Transactions | `sqlite_workspace_board.SQLiteBoardRepository._transaction` |
| OAuth protocol | `mcp.client.auth.OAuthClientProvider` (subclassed, not reimplemented) |
| Inspector UI + detail rendering | `control_center_mcp_inspector.js` (read-only invariant §10.7 kept) |
| Prompt constants + catalog | `claude_local.py` `BRAIN_SETTINGS_PROMPT` pattern, `runtime/prompt_catalog.py` |

## Plan amendments

- Order unchanged: 01 → 02 → 03 → 04 → 05 → 06 → 07 → 08, sequential (host RAM ~0.4–2 GB free: foreground chunked tests, one implementer per worktree, mutating QA counts as implementer, no `git stash`).
- Each SLICE.md now carries a binding `## Slice 00 contract` (scope, out-of-scope, acceptance, tests, evidence).
- Slice 01 is documentation-only (tool-contract amendments + `docs/mcp/plugins.md`); QA = qa-verification + doc/code consistency check, no runtime validation.
- Live evidence (Circuit Toolbox, real brain traces, ~$0.2–0.3/turn through the isolated CC `POST /api/agent/ask`) is concentrated in Slices 05 and 07; earlier slices use the fake remote MCP + fake AS fixture of Slice 03.

## Human checks carried

- HV-06-01 — visual UX of the plugin manager (after automated browser/a11y validation).
- HV-07-01 — real Circuit Toolbox authorization in the browser (OAuth consent/login).
- Drive folder move `to-do` → `current` (connector limitation).

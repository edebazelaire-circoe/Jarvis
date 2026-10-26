# Product agent capabilities (contract)

Canonical contract, documentation **Level 3**: vocabulary, one manifest,
launch enforcement by the CLI itself, unit conformance tests and real
traces. Handoff `tasks/jarvis-presentation-edition-v1/` (Slice 04, decision
D08). Neighbours: [product-edition.md](product-edition.md) (which Boards an
edition offers), [export.md](export.md) (the only way a file leaves Jarvis),
[product-connectors.md](product-connectors.md) (remote tool side effects).

| What | Code | Proof |
| --- | --- | --- |
| Manifest per edition (`AGENT_CAPABILITY_POLICIES`, `agent_capability_policy`) | `jarvis/domain/agent_capabilities.py` | `tests/unit/test_agent_capabilities.py` |
| Launch enforcement (conversation brain, Back Brain `job_result`) | `jarvis/runtime/claude_local.py` (`ClaudeLocalAgent.start`, `_capabilities`, `_confined_workdir`, `_confined_read_dirs`) | same (argv, cwd, snapshot, journal) |
| Settings cannot widen (CLI, permission mode) | `jarvis/runtime/agent_settings.py` (`edition_capabilities`, `effective_agent_cli`, `resolve_agent_settings`), `control_center.py` (`_apply_cli`, `_refuse_locked_permission`, `agent_capabilities` in `GET /api/settings`), `brain_config.py` (provider choices and refusal) | same |
| Codex refused | `codex_local.py` (`_ensure_edition_allows_codex`), `back_brain_worker.create_job_agent` | same |
| Debug console refused | `claude_local.open_console`, `codex_local.open_console` | same |
| Self-development refused | `self_dev_service.py` (`gate`, `_ensure_edition`) | same |
| Brain prompt describes only real capabilities | `claude_local.brain_system_prompt_for`, renderer `prompt_catalog._brain_system`; read-only `CONTEXT_GLOBAL` rules `global_context.GLOBAL_CONTEXT_READ_ONLY_RULES` | same, plus `test_product_edition.py` |

## Vocabulary

- **Model-callable tool**: a tool the CLI offers the model (built-in, or an
  MCP tool). This contract governs these.
- **Jarvis-owned subprocess**: a process Jarvis itself starts with fixed
  arguments for a bounded job (Remotion bundler/renderer and its Chrome
  headless, FFmpeg, `npm` installing the pinned Remotion capability, the MCP
  servers of Jarvis, the routing hook). The model can *request* the job
  through a Jarvis tool (`remotion_setup`, `remotion_export`,
  `presentation_source op preview`); it never chooses the executable, the
  arguments or the paths. These are not shell access and are not governed by
  the manifest; their own boundaries are in [remotion-isolation.md](remotion-isolation.md),
  [local-capabilities.md](local-capabilities.md) and [export.md](export.md).
- **Confined launch**: a CLI launch where the manifest is imposed.

## Manifests

One table, keyed by `ProductEdition` like `connector_policy`; it is derived
from the edition, never a second availability table.

| | `full` (development) | `presentation` (product) |
| --- | --- | --- |
| `confined` | no: launches are byte for byte those before this contract | yes |
| Built-in tools (`--tools`, exhaustive) | CLI default set | `Read, Glob, Grep, WebSearch, WebFetch, Agent, ToolSearch, TaskStop, SendMessage` |
| Session refusals (`--disallowedTools`) | none (or `Agent, Task` for a `never` delegation) | `Bash, PowerShell, REPL, Write, Edit, MultiEdit, NotebookEdit, Monitor, KillShell, CronCreate, CronDelete, ScheduleWakeup, RemoteTrigger, Workflow, EnterWorktree, ExitWorktree, Skill, DesignSync, PushNotification` (+ `Agent, Task` for `never`) |
| Permission mode | setting (`bypassPermissions` by default) | `dontAsk`, imposed; `--permission-prompts none` |
| Allowed rules (`--allowedTools`) | none | the built-in tools above + `mcp__<server>` for each Jarvis server declared **at this launch** |
| MCP servers | Jarvis servers + the user's personal ones | Jarvis servers only (`--strict-mcp-config`) |
| `--chrome` (Claude in Chrome) | conversation brain | never |
| User/project/local settings files, user hooks, plugins | loaded | ignored (`--restricted`); Jarvis `--settings` (routing hook) still applies |
| Skills / slash commands | loaded | off (`--disable-slash-commands`) |
| Working directory | the code (`CODE_ROOT`) | `<runtime>/agent-workdir` (empty, Jarvis-owned) |
| File tools reach | the whole PC | the working directory + `--add-dir` only (`--restricted`) |
| Agent CLIs | Claude, Codex | Claude only |
| Debug console | yes | refused `debug_console_unavailable_in_edition` |
| Self-development | per setting | refused `self_development_unavailable_in_edition` |

Flags verified on the installed CLI, Claude Code **2.1.310** (`claude --help`):
`--restricted` "removes the built-in tools that run commands or code (Bash,
PowerShell…) and WebFetch unless `--tools` names them, ignores user, project
and local settings files…, confines the file tools to the working directories
(`--add-dir` included), refuses bypassPermissions". Names a CLI version does
not know are ignored in `--tools`/`--disallowedTools` (probed).

### Which launches are confined

| Launch | `presentation` |
| --- | --- |
| Conversation brain (`execution_profile="conversation"`, every Board brain of the pool) | confined |
| Back Brain job (`job_result`, `back_brain_worker.create_job_agent`) | confined (no MCP) ; a Codex job is refused `agent_cli_unavailable_in_edition` |
| `speculative_analysis`, `presentation_preparation` | unchanged: already stricter (`--restricted`, `--tools ""` or the granted read tools, no MCP, no session) |
| Sub-agents (`Agent`/`Task`, any depth, incl. `general-purpose`, `claude`, `jarvis-no-spawn`) | inherit the session's tool pool and refusals: nothing to widen (probe and real trace below) |
| Debug console (`/api/agent/console/open`) | refused before any process |
| Self-dev (`/api/self-dev/*`) | refused before any job is written |
| Codex brain or console | refused at `start` / `open_console`; `cli.agent = codex` refused at save (`POST /api/settings`, Architecture page, `settings_set`) |

## Reading scope (decision)

`Read`/`Glob`/`Grep` stay: research, attachments, Remotion previews
(`presentation_source op preview` asks the model to look at frames with
`Read`). `--restricted` confines them to the working directory and the
`--add-dir` list, which in `presentation` is: `<data>/sessions`,
`<data>/artifacts` (once known), `<data>/CONTEXT_GLOBAL`, `<data>/boards`,
`<data>/local_capabilities` (Remotion previews land in
`remotion/runtime/render/previews/<job>/`; created at launch if missing, because
the CLI drops an `--add-dir` that does not exist yet, probed), and
`<runtime>/scene-captures`. The rest of the PC
(Documents, Desktop, the code, `.env`, the Core token in `<runtime>`) is
refused by the CLI ("is outside … --restricted confines the file tools to the
working directory"). `WebSearch`/`WebFetch` stay for research (D07).

**Residual risk (accepted, documented):** `WebFetch` can send to any URL what
the model can read (Jarvis folders, Drive documents, connector results).
Mitigations: read scope above, connector content framed as untrusted data
(Slice 05), no write/shell, Drive read-only. A domain allow-list for
`WebFetch` is a later option.

## Writing

No built-in tool writes. Every write goes through a Jarvis service with its
own path contract: Board memory (`board_memory_write|move|delete`,
`WorkspaceService`), Presentation sources and drafts (`presentation_*`,
Studio store), scene objects (`scene_*`), memory candidates
(`memory_propose`), and the single way out of Jarvis, the export
(`remotion_export op save`, [export.md](export.md)).

Consequence: in `presentation` the brain cannot reorganise `CONTEXT_GLOBAL`
(it is loaded and readable; its prompt rules say so,
`GLOBAL_CONTEXT_READ_ONLY_RULES`). A bounded MCP tool for it is a follow-up.

## Settings never widen

- `resolve_agent_settings` returns the manifest's permission mode for Claude;
  `effective_agent_cli` maps a stored `codex` to `claude`. Core (Back Brain),
  the Control Center and the Architecture page read the same result.
- `POST /api/settings` refuses `cli.agent = codex`
  (`agent_cli_unavailable_in_edition`) and a permission mode other than the
  imposed one (`agent_permission_locked_by_edition`), header
  `X-Jarvis-Error-Code`; sending the imposed value back is accepted. The
  legacy flat `claude_permission_mode` mirror keeps the **stored** value.
- The Architecture page lists Codex as unavailable with the reason and refuses
  it (`agent_cli_unavailable_in_edition`).
- `GET /api/settings` carries `agent_capabilities` (`to_payload()`): the UI
  shows the lock, it decides nothing (Slice 08 consumes it).
- Whatever the settings say, `ClaudeLocalAgent.start` imposes the manifest.

## Brain prompt

Written after enforcement, and only describing it
(`BRAIN_CONFINED_CAPABILITIES_PROMPT`, `vous`): no terminal, PowerShell, file
write/delete or piloted browser for the brain and its sub-agents; reading
limited to Jarvis folders; writing only through Jarvis tools; for « écris sur
le Bureau », « lance PowerShell », « supprime ce fichier »: say this edition
cannot, and offer the export to `Documents\Jarvis`. Board memory and user
feedback notes go through `board_memory_write`. In `full` the prompt is
unchanged byte for byte.

## Observability

`agent.start` carries `confined`, `launch_permission_mode`, `chrome`, `cwd`;
the agent snapshot carries `confined` and the launched `permission_mode`.
Refusals: `agent.console_refused`, `selfdev.refused`, `agent.start` (Codex,
level error), `settings.agent.rejected` (code). The CLI's own `system/init`
event lists the tools actually offered (`tools`), which the real traces check.

## Real traces (2026-10-26, CLI 2.1.310)

See `tasks/jarvis-presentation-edition-v1/LOG.md` (Slice 04) for the sandbox
run: init `tools` of the brain and of a sub-agent, normal authoring/export,
hostile turns (write outside, PowerShell, delete, delegated to a sub-agent).

## Residual risks

- `WebFetch` exfiltration (above).
- The routing hook, Remotion/FFmpeg/npm and the MCP servers are Jarvis code
  running with the user's rights: a bug there is not contained by the CLI.
- The CLI's own state (`%USERPROFILE%\.claude`, `%LOCALAPPDATA%\claude-cli-nodejs`)
  is written by the CLI, not by the model.
- A user-level `~/.claude/CLAUDE.md` is still read (memory, not settings).
- Confinement depends on the CLI honouring `--restricted`; Slice 06 pins the
  CLI version and must re-run the probe on upgrade.

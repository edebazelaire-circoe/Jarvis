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
| Brain prompt, sub-agent methods and routing hook describe only real capabilities | `claude_local.render_brain_system_prompt` / `brain_system_prompt` / `workspace_prompt_for`, renderer `prompt_catalog._brain_system`; `subagent_roles.brain_rules` / `role_brief` / `adapt_instructions`; `routing_hook.profile_rule` / `charter_input` (`capabilities`), `AgentCapabilityPolicy.subagent_note`; read-only `CONTEXT_GLOBAL` rules `global_context.GLOBAL_CONTEXT_READ_ONLY_RULES` | same, plus `test_product_edition.py` |
| A role the edition does not offer is refused (V1.2 Slice 01) | `subagent_roles.edition_role_refusal`, `routing_hook._edition_role_guard` (`role_unavailable_in_edition`) | `tests/unit/test_presentation_brain_scope.py` |
| Role tools shown per edition | `subagent_roles.role_tools`, `SubagentRole.as_dict(capabilities)`, `control_center._subagent_roles_payload` | same |
| Presentation project role in the brain prompt | `claude_local.presentation_project_section` (`BRAIN_PRESENTATION_PROJECT_MARK`) | same |

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
| Back Brain job (`job_result`, `back_brain_worker.create_job_agent`) | confined (no MCP, no `--add-dir`): it reads **no Jarvis folder** (only its empty `agent-workdir`) and the web; a job needing Board or Session material must receive it in its brief. A Codex job is refused `agent_cli_unavailable_in_edition` |
| `speculative_analysis`, `presentation_preparation` | unchanged: already stricter (`--restricted`, `--tools ""` or the granted read tools, no MCP, no session) |
| Sub-agents (`Agent`/`Task`, any depth, incl. `general-purpose`, `claude`, `jarvis-no-spawn`) | inherit the session's tool pool and refusals: nothing to widen (probe and real trace below) |
| Debug console (`/api/agent/console/open`) | refused before any process |
| Self-dev (`/api/self-dev/*`) | refused before any job is written |
| Codex brain or console | refused at `start` / `open_console`; `cli.agent = codex` refused at save (`POST /api/settings`, Architecture page, `settings_set`) |

## Reading scope (decision)

`Read`/`Glob`/`Grep` stay: research, attachments, Remotion previews
(`presentation_source op preview` asks the model to look at frames with
`Read`). `--restricted` confines them to the working directory and the
`--add-dir` list. **Since V1.2 Slice 03 (I-002 correction 1) the list is
scoped to the agent's Board** in `presentation`:

| Folder | `full` | `presentation` |
| --- | --- | --- |
| Board memory | `<data>/boards` (every Board) | `<data>/boards/<board_id>/memory` of the pool entry only |
| Session folders | `<data>/sessions` (every Session) | `<data>/sessions/<jarvis_session_id>` of the open Session only |
| Global context | `<data>/CONTEXT_GLOBAL` | same |
| Attachments | `<data>/artifacts` (once known) | same (not partitioned by Board, see below) |
| Remotion previews, scene captures | — | `<data>/local_capabilities`, `<runtime>/scene-captures` |

How (`ClaudeLocalAgent._board_scoped_dirs`, `jarvis/runtime/claude_local.py`):
the Control Center gives each agent of the pool `board_scope = lambda:
(entry.board_id, entry.jarvis_session_id)` and `sessions_root`
(`ControlCenter._wire_agent`, `_grant_dirs`); at each launch the confined CLI
replaces `<data>/boards` and `<data>/sessions` by the two scoped folders
(created with `safe_folders.ensure_folder_tree`, ids checked by
`check_memory_board_id` / `check_session_id`; a refusal is
`agent.add_dir_refused` with `agent_board_memory_dir_unavailable` /
`agent_session_dir_unavailable`, once, and the CLI starts without it). An
agent without a binding (the foreground before Core names it) gets no Board
and no Session folder. `agent.start` carries `board_scope`
(`[board_id, jarvis_session_id]`, `null` when not scoped) and
`ClaudeLocalAgent.launched_board_scope` keeps it.

**Rebinding relaunches.** A pool entry never changes Board, except the
unbound foreground adopted by `BoardBrainPool.adopt` without a relaunch.
`ClaudeLocalAgent.board_scope_stale()` is then true and the Control Center
treats it like a missing grant (`_lacks_workspace_grant`): relaunch with
`--resume` at adoption (`reason: session_resume`) and before a turn
(`reason: board_scope`), never during a turn or while sub-agents work
(`agent.relaunch_deferred`, `board_brain.relaunch_deferred`). Sub-agents
inherit the CLI's folders.

**Explicit inspection stays.** Reading another Board **by its id** through
`jarvis-workspace` (`board_memory_*`, `board_inspect`, `dossier_*`) is still
allowed (`docs/boards.md` › *Non-activating inspection*, decision of agent 0 in
I-002): it is an explicit, traced gesture. What is refused is the implicit
file-system sweep of every Board. The prompts say so: discovery covers the
current Board and the global knowledge, another Board is read only on request
or explicit reference (`BRAIN_CONFINED_CAPABILITIES_PROMPT`,
`AgentCapabilityPolicy.subagent_note`, `subagent_roles.RESEARCH_REUSE_BLOCK`).

Example (real trace, V1.2 Slice 03): a `[general] [research]` agent of Board A
asked to `Grep` `ZEPHYR` in `<data>/boards` and `<data>/sessions` gets « … is
outside …/agent-workdir, …/CONTEXT_GLOBAL, …/boards/default/memory,
…/sessions/<open session>, … » for both, and finds nothing of Board B in the
allowed folders.

Not covered: `<data>/artifacts` (attachments of every Board; registry
Artifacts are not stored per Board) and `local_capabilities` (Remotion previews
of every presentation) remain readable by path. The rest of the PC
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
(`BRAIN_CONFINED_CAPABILITIES_PROMPT`, `vous`): no terminal, shell, file
write/delete or piloted browser for the brain and its sub-agents; reading
limited to the Jarvis folders granted to the Board (its memory, the open
Session, global context, attachments, previews), another Board only through
the `board_*` tools by id and on request; writing only through Jarvis tools; for « écris sur
le Bureau », « lance PowerShell », « supprime ce fichier »: say this edition
cannot, and offer the export to `Documents\Jarvis`. Board memory and user
feedback notes go through `board_memory_write`. In `full` the prompt is
unchanged byte for byte.

### Derived prompts (no second list)

Every model-visible text is **rendered from the manifest**, never patched
after the fact:

- **Task profiles** (`routing.TASK_PROFILES`): a profile is offered when the
  manifest provides every capability it requires
  (`AgentCapabilityPolicy.offers_task_profile`): `code` needs a built-in write
  tool (`NATIVE_WRITE_TOOLS`), `desktop` needs `--chrome`. In `presentation`
  only `[fast]` and `[general]` remain; `profile_rule`, the Presentation author
  (`[general] [presentation-author]`), the ephemeral example, QA (`[general]
  [qa]`), the Mission Owner and relation briefs follow.
- **Sub-agent roles**: a role is offered when its default profile is
  (`subagent_roles.offers_role`); `[coder]` disappears from `brain_rules`,
  from the spawn catalogue of `research-lead` and from the Mission Owner list.
  It is also **refused**, not only unlisted (V1.2 Slice 01): an `Agent` call
  whose description announces a role the edition does not offer (a forged
  `[coder]`, any profile, `[mission]`, `[éphémère]`, the brain or a nested
  agent) is denied by the routing hook with the stable code
  `role_unavailable_in_edition`, logged as `agent.spawn_refused` (`role_id`,
  `written: false`, nothing declared to Core). The reason tells the model that
  this edition does no development and lists the offered roles; it holds no
  path or secret. `full`, and an unreadable edition, refuse nothing.
  Pinned by tests (`test_presentation_brain_scope.py`,
  `test_presentation_project_continuity.py`): an `Agent` **or `Task`** call
  (`routing_hook.AGENT_TOOLS`), `[coder]` without a profile, `[CODER]`,
  `[ coder ]`, the marker in the prompt only, `[éphémère]` first.
  **Unreadable edition (accepted, I-001 m4)**: when `JARVIS_PRODUCT_EDITION`
  cannot be read, the hook lets the call through
  (`agent_capabilities_unreadable` is logged, texts as in `full`); it never
  refuses on its own failure. This is not an opening: Core and the CLI
  launcher refuse to start on an unreadable edition, so no confined brain runs
  with it, and the real barrier stays the tools the CLI was launched with.
- **Role tools** (`SubagentRole.tools`, descriptive): the payload of
  `GET /api/subagent-roles` shows `role_tools(role, capabilities)`: no tool of
  `forbidden_native_tools` (`qa` no longer shows `Bash`), `board_memory_write`
  instead of the built-in write tools. `full`: the previous payload.
- **Mission dossier** (case B): without a built-in write tool, `_DOSSIER`
  becomes `_DOSSIER_TOOL`: read with `board_memory_read`, written only with
  `board_memory_write` (`create` once, `append` to add at the end, `replace`
  with the `expected_sha256` of the last read to insert), path relative to the
  Board memory (`missions/…/mission.md`). The brain passes the path and the
  active Board id to the Interviewer.
- **Brain lines**: the delegation line (`BRAIN_DELEGATE_WORK_LINE_CONFINED`:
  no browser, code, command), memory and feedback lines, and the workspace
  line on `board_memory_write` (`BRAIN_WORKSPACE_MEMORY_WRITE_TOOL_LINE`).
  That line **recommends** `expected_sha256` for `replace`, it does not claim
  Core requires it (V1.2 Slice 01): Core keeps it optional because `replace`
  creates a missing file (nothing to read first) and a file above 1 MiB has no
  hash (`docs/boards.md`); the Dossier editor and the workspace manager rely on
  both.
- **Presentation project role** (`presentation_project_section`, section
  `VOTRE RÔLE : LE PROJET DE PRÉSENTATION`, appended after the capabilities
  section in `presentation` only): each Board is a presentation project;
  interview, documentary and web research in the background, organisation in
  the Board memory, the approved connectors (labels read from
  `connector_policy`, a `contract_pending` connector such as IGuard is not
  named), creation through the Presentation tools. Roles are named only when
  offered. When the manifest closes `self_development`, it adds the refusal of
  development: no change to the Jarvis code or repository or another project,
  no arbitrary code or command; the only code made here is Remotion scenes and
  prefabs, through `presentation_source`. Project continuity (V1.2 Slice 02)
  is one line at the anchor comment (`- Continuité : …`) plus the section
  `MÉMOIRE DU PROJET : summary.md` (`BRAIN_PRESENTATION_MEMORY_SECTION`)
  appended to this section: the `summary.md` convention, when and how the
  brain updates it, how it resumes ([boards.md](boards.md) › *Presentation
  project digest*). Research reuse/freshness (V1.2 Slice 03) is one line at
  the same anchor (`- Réutilisation : …`) plus the section `RECHERCHE :
  EXISTANT D'ABORD` (`presentation_research_section`), appended last; case B
  of `brain_rules` launches helpers « selon RECHERCHE : EXISTANT D'ABORD »
  instead of « en parallèle », and the research roles receive
  `subagent_roles.RESEARCH_REUSE_BLOCK` ([subagent-roles.md](subagent-roles.md)
  § 11). `full` is unchanged byte for byte.
  The workspace adaptation replaces exact lines of a read-only constant and
  raises `PromptAdaptationError` (`prompt_adaptation_line_missing`) when one is
  missing, instead of skipping it.
- **Edited role methods**: user overrides (`subagent_role.<id>`) are adapted
  passage by passage (`CONFINED_REWRITES`); a passage the override changed is
  logged by the routing hook as `agent.role.confined_adaptation_missed`
  (`role_confined_adaptation_missed`, with the codes), and the confined dossier
  paragraph is appended anyway. Every confined sub-agent also receives
  `subagent_note()` (`CAPACITÉS DE CETTE ÉDITION (SOUS-AGENT)`), which lists
  the built-in tools from the manifest. An unreadable edition in the hook is
  logged `agent_capabilities_unreadable` (texts then as in `full`; enforcement
  is at launch, unaffected).
- Conformance: `tests/unit/test_agent_capabilities.py` renders the
  `presentation` brain prompt, every offered role brief and the hook output,
  and checks that no `--disallowedTools` name, no `[code]`, `[coder]` or
  `[desktop]` appears; `full` texts are compared to their constants.

## Observability

`agent.start` carries `confined`, `launch_permission_mode`, `chrome`, `cwd`;
the agent snapshot carries `confined` and the launched `permission_mode`.
Refusals: `agent.console_refused`, `selfdev.refused`, `agent.start` (Codex,
level error), `settings.agent.rejected` (code), `agent.spawn_refused` (`role_unavailable_in_edition`, routing hook). The CLI's own `system/init`
event lists the tools actually offered (`tools`), which the real traces check.
V1.2 Slice 03: `agent.start` also carries `board_scope` (reading scope above);
`agent.declared` carries `run_in_background` beside `role_id`,
`caller_agent_id`, `mission_id` and `mission_owner` (the sub-agent topology);
Core traces `core.research.freshness_decided` for each turn whose Board has
research documents (`docs/subagent-roles.md` › *11. Recherche : existant
d'abord*).

## Real traces (2026-10-26, CLI 2.1.310)

See `tasks/jarvis-presentation-edition-v1/LOG.md` (Slice 04) for the sandbox
run: init `tools` of the brain and of a sub-agent, normal authoring/export,
hostile turns (write outside, PowerShell, delete, delegated to a sub-agent).

**V1.2 Slice 01 (2026-10-27, model `claude-opus-5-5`)**, sandbox in
`presentation` (`tasks/jarvis-presentation-edition-v1-2/LOG.md`, Slice 01 and
its QA): the brain's `system/init` offers only `Task, Glob, Grep, Read,
SendMessage, ToolSearch, WebFetch, WebSearch` plus the `jarvis-*` MCP servers
(92 tools), `permissionMode` `dontAsk`. A development request (« modifie le
code de JARVIS… lance git status ») is refused in one sentence with no tool
call and no agent; a web question goes to one `[general] [web-research]`; a
one-slide request goes to `[general] [presentation-author]`
(`presentation_draft_assemble`, `presentation_source op preview`). No Bash,
Write, Edit, PowerShell nor `[coder]` call. The real hook process refuses a
forged `[coder]` / `[CODER]` with `role_unavailable_in_edition` and an
`agent.spawn_refused` line; the model itself never attempted `[coder]`, so the
refusal behind the live CLI is not observed. Cost: 1.07 $ + 0.29 $ (QA).

## Residual risks

- `WebFetch` exfiltration (above).
- The routing hook, Remotion/FFmpeg/npm and the MCP servers are Jarvis code
  running with the user's rights: a bug there is not contained by the CLI.
- The CLI's own state (`%USERPROFILE%\.claude`, `%LOCALAPPDATA%\claude-cli-nodejs`)
  is written by the CLI, not by the model.
- A user-level `~/.claude/CLAUDE.md` is still read (memory, not settings).
- Confinement depends on the CLI honouring `--restricted`; Slice 06 pins the
  CLI version and must re-run the probe on upgrade.

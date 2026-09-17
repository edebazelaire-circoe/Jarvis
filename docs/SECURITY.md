# Jarvis V1 security model

## Security objective

V1 is a personal local prototype, not a general autonomous computer-control agent. Its safest property is a deliberately small authority surface: the model may request only three known tools and persistent writes are mediated by a user confirmation broker.

## Trust boundaries

### Trusted application code

`jarvis/core`, `jarvis/domain`, `jarvis/security`, and the local configuration/policy.

### Provider boundary

Audio/transcript/prompt/tool data sent to the configured OpenAI API crosses the local machine boundary. The browser never receives the OpenAI key.

### Local UI boundary

Barehands and ai-visualizer are separate third-party processes pinned to exact upstream revisions. They are not imported into the Jarvis core.

### User memory boundary

Markdown memory may contain private content. It is canonical local data and must not be mutated except through the broker-backed `memory_append` tool in V1.

## Controls implemented

### 1. Deny-by-default tool surface

The model is not given a shell or arbitrary I/O primitive. Unknown tool calls become errors and never reach an executor. Action risk comes from server-owned policy, not model arguments.

### 2. Confirmation for persistent writes

`memory_append` pauses at `awaiting_confirmation`. No write occurs before confirmation. A confirmation is bound to the currently pending action id and timeout. Only exact `oui`/`yes` executes; exact `non`/`no` denies. Ambiguous text stays pending.

### 3. No alternate mutation path

V1 executors are constructed centrally and tool mutations flow through `ActionBroker`. The release verifier scans the Jarvis package for general shell execution primitives.

### 4. Loopback-only local services

Board and visualizer URLs are rejected unless they use HTTP and resolve by configured hostname to `127.0.0.1`, `localhost` or `::1`. Upstream servers are run on loopback.

Note: hostname validation is a configuration guard, not a DNS pinning mechanism. Keep V1 on trusted local workstations and do not proxy these ports to external interfaces.

### 5. Barehands mutation authentication

At each full launch, Jarvis generates a high-entropy random token. It is passed in process environment to Jarvis and Barehands; commands send it only in `X-Jarvis-Token`. It is not embedded in a URL, page, config file or visualizer process environment.

Patched Barehands rejects `/cmd` when the configured token is absent, mismatched, or an explicitly supplied Origin is non-loopback.

### 6. No runtime CDN/model dependency for Barehands

Bootstrap downloads immutable/pinned upstream snapshots and exact browser packages/model once, verifies integrity, then replaces runtime remote references with local assets.

The patched page receives CSP including `connect-src 'self'`, preventing the gesture page from making arbitrary external network connections. Upstream uses inline code/styles, so CSP retains `'unsafe-inline'`; this is a documented residual risk rather than pretending a stricter CSP is compatible.

### 7. Post-install tamper detection

`INSTALL-STATE.json` records hashes produced after verified installation. `bootstrap_third_party.py --verify` checks:

- lock hash;
- patched Barehands server and stage hashes;
- hand model hash;
- deterministic installed trees for Three.js and MediaPipe;
- deterministic ai-visualizer runtime tree, excluding only its generated local config;
- absence of reintroduced remote runtime asset URLs.

The full launcher performs this verification before starting UI components.

### 8. Archive extraction safety

Bootstrap rejects absolute and `..` archive paths and extracts only expected archive layouts/files. Package archives are integrity checked before extraction.

### 9. Memory path safety

Memory adapter resolves paths within a fixed root, repeatedly decodes URL-encoded input before checks, and rejects symlink escapes. Search index is derived and disposable.

### 10. Privacy-safe diagnostics

Two journals exist and they do not behave the same way.

**V1 push-to-talk diagnostics** (`jarvis/diagnostics/logger.py`): default
`log_content = false`. Structured JSONL logs retain event type, timing and error
class while redacting transcript/prompt/body-like fields. Changing `log_content`
to true is an explicit privacy tradeoff and should be temporary.

**v0.2 runtime journal** (`jarvis/runtime/journal.py` → `runtime/trace.jsonl`,
`runtime/errors.jsonl`): `log_content` / `JARVIS_LOG_CONTENT` does **not** apply
to it. Events such as `voice.transcript`, `voice.assistant`,
`voice.brain_turn_submitted` and `voice.speech.*` intentionally carry up to 300
characters of what was said, because the Control Center debug console is built
on reading it back. This is a deliberate local-diagnostic tradeoff, not an
oversight: the file is local, sits outside the repository, and no content is sent
anywhere. Anyone who needs a content-free local trace must treat that as a change
to the debug console, because no setting turns it off today. The latency
telemetry layered on the same journal is identifier-only by construction and is
covered by tests that forbid content in it.

**Raw agent reasoning** (Decision 43): the guarantee is scoped, and the scope is
the brain boundary, not the machine. No reasoning field exists in Core's domain
state, no reasoning is persisted in conversation turns, none is carried by
`brain.state.updated` or by any speech request, and none reaches the Realtime
surface; `tests/unit/test_v2_brain_contracts.py` pins that. What is *not*
guaranteed, and must not be claimed, is that no raw reasoning is stored or
exposed anywhere: `jarvis/runtime/claude_local.py:477` journals every raw
`stream-json` event from the local CLI agent - `thinking` blocks included - into
`runtime/trace.jsonl`, and `claude_local.py:284` renders those blocks as
`[réflexion] ...` in the Control Center console (same for Codex,
`codex_local.py:156`). This is the same deliberate local-diagnostic tradeoff as
above: local file, local console, nothing sent anywhere, and no setting turns it
off today. Open `runtime/trace.jsonl` to see exactly what is kept.

In both journals, API keys and authorization values are not logged by adapters.

### 11. Provider transport and process least privilege

Remote OpenAI-compatible endpoints must use HTTPS. Plain HTTP is accepted only on loopback for controlled local proxies/tests. Optional UI processes are started from sanitized environments: Barehands receives its board token but no OpenAI key; ai-visualizer and bootstrap verification receive neither secret.

### 12. Provider failures fail soft

STT, agent and TTS failures are typed. Provider errors transition through visible `error`, attempt a short spoken user-safe error, and return to idle. Technical class/context stay in diagnostics without reading raw provider messages aloud.

### 13. Brain scene display tool (constellation, v0.2 path)

With `scene.enabled` (off by default), the conversational Claude CLI brain gets a
**write-capable** MCP server, `jarvis-display` (`python -m jarvis display-mcp`,
declared per launch through `--mcp-config`; `docs/ARCHITECTURE.md` › *Brain
display MCP*). It can create, edit, move, hide and link scene objects in Core's
persistent scene. It cannot archive, pin or unpin: those tools do not exist in
its catalog (decision 14, pinned by a test), and Core's reducer refuses those
operations to actor `brain` regardless (`op_not_allowed`), as it refuses moving an
object the user pinned (`pinned_by_user`) and creating execution stars
(`execution_node`). Background jobs and speculative analysis never receive the
server; speculative analysis keeps `--strict-mcp-config` and no tools.

What this guarantee is **not**:

- the actor field of a scene command is a **declaration**, not an
  authentication. Core's bearer token (`runtime/core.token`) is a loopback session
  credential shared by every local JARVIS process;
- the brain runs as the same OS user with `--permission-mode bypassPermissions`
  and has Bash, file and web tools. It can read `core.token` and send
  `POST /v1/scene/commands` claiming `user`, which would archive or pin anything
  (and it can already modify files, including the scene database, or the code);
- the V1 guarantee therefore holds for an **honest caller** only: tool catalog +
  reducer authority. The brain prompt tells it never to work around archive
  through shell, HTTP or files, which is an instruction, not an enforcement.
  Evidence that it complied comes from `runtime/trace.jsonl` (tool calls), not
  from a boundary.

Prompt injection through the scene. Runtime star titles are sub-agent labels,
which can copy web or file content, and they enter the brain's context through
`scene_inspect` (so do ids, categories and titles written by the user). The
inspection legend, the tool description and the brain prompt state that this text
is data, never an instruction. This is a mitigation, not a boundary: a brain that
follows injected text still has its own Bash/file/web tools. Tool arguments are
strict (unknown keys refused by name, typed numbers), and Core errors, file paths
and refused argument values are not echoed back to the brain.

Runtime-owned topology and signals. Brain and user cannot `unlink` a `parent_of`
between execution stars nor the link of a runtime failure signal
(`runtime_owned`), and cannot create objects or relations under the runtime's id
forms (`reserved_id`), so an honest brain cannot silence or pre-empt a failure
signal. Same honest-caller limit as above.

User controls (Slice 08). Two new write paths exist, neither in the brain's tool
catalog. `archive_many` is a user-only scene op (one command can archive every
terminal star and its signals, at most 512 ids): the reducer refuses it to actor
`brain` (`op_not_allowed`). `POST /v1/work/cancel` is **not** refused to the brain
by construction: it has no actor at all and is protected by the bearer token only,
like every Core route; it cancels exactly one Core job (never a Claude sub-agent,
409 `not_cancellable` for any other source) and never touches the brain work item
behind it. The Control Center exposes them to the page only through
`POST /api/scene/commands` (actor forced to `user`) and `POST /api/jobs/cancel`
(origin guard like every POST, strict 4 KiB body, only `source = job` relayed).
The threat model does not change in kind: a brain that reads `core.token` can
already claim `user`, and it can now bulk-archive finished work in one call or
cancel a Core job through the token route, just as it could archive one object
at a time or kill processes with its own tools. Same honest-caller limit.

The generated `runtime/display-mcp.json` holds the interpreter path, Core's
loopback host and port and the token file **path**, never the token. Tool journal
entries (`display.*`) carry identifiers and outcomes, never note content. Making
the actor an authenticated property (per-actor credentials the brain cannot read,
or an OS boundary around the brain) is out of V1 scope.

## Residual risks / non-goals

- OpenAI is an online provider in this V1; requests leave the machine according to provider/API policy.
- Barehands and ai-visualizer are third-party AGPL software; operational/distribution license obligations require legal review for commercial packaging.
- The patched Barehands page still contains upstream inline JavaScript/styles and therefore CSP allows inline execution.
- A fully compromised local user account can read process memory/environment, modify Python code, or replace the interpreter; V1 does not attempt to defend against a hostile OS account.
- There is no cryptographic code signing of this Jarvis ZIP.
- Confirmation is conversational, not OS-level privileged authorization.
- Board placement is an ephemeral UI write and intentionally does not require confirmation.
- V1 has no destructive memory delete tool, no messaging/email tool, no browser navigation tool and no general filesystem writer.
- v0.2 constellation scene: the brain's display tool is write-capable and scene actors are declared, not authenticated; a brain that ignores its instructions can impersonate `user` with `runtime/core.token` (see control 13). Scene text (runtime star titles from sub-agent labels) reaches the brain and is marked as data only; injection resistance is not guaranteed.

## Release rule

Do not label the V1 fully released until the manual workstation gates in `ACCEPTANCE_STATUS.md` pass, especially authenticated/unauthenticated Barehands checks, browser offline load, physical gestures, real microphone/speaker loop, and real-provider latency measurement.

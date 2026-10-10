# Jarvis V1 security model

## Security objective

V1 is a personal local prototype, not a general autonomous computer-control agent. Its safest property is a deliberately small authority surface: the model may request only three known tools and persistent writes are mediated by a user confirmation broker.

## Trust boundaries

### Trusted application code

`jarvis/core`, `jarvis/domain`, `jarvis/security`, and the local configuration/policy.

### Provider boundary

Audio/transcript/prompt/tool data sent to the configured OpenAI API crosses the local machine boundary. The browser never receives the OpenAI key.

### Local UI boundary

**Barehands** (one word, the upstream AGPL board) and ai-visualizer are separate third-party processes pinned to exact upstream revisions. They are not imported into the Jarvis core.

**Bare Hands** (two words) is a different subsystem entirely: native Jarvis code running inside the Control Center page, with no separate process, no port and no token. It shares a name with the board and nothing else. The spelling convention is stated once in `docs/ARCHITECTURE.md`, *Two subsystems, one word*; this file follows it throughout. Bare Hands has its own control, § 14 below.

### User memory boundary

Markdown memory may contain private content. It is canonical local data (`<data_root>/memory`, outside git) and is mutated only through the canonical store, never by an index, a retriever or a sidecar.

Mutation paths of long-term memory: V1 `memory_append` (confirmed, broker-backed); `MemoryMaintenanceWorker` promotion of notes carrying `jarvis:retain` (copy with provenance, protected classes untouched); the store API (`create`, `revise`) used by the consolidation pipeline (`manual` by default: a candidate waits in `_candidates/` for a human decision in the Memory Center, `auto` is opt-in and refuses without dedup) and by humans. The Brain can write nothing durable: the `jarvis-memory` MCP server gives it `memory_search`, `memory_read`, `memory_propose`, `knowledge_search` and `knowledge_read`, at most 3 calls per turn (`memory_tool_budget_exceeded`), reads narrowed by the Brain policy and its loadout, and `memory_propose` only files a `proposed` candidate (confidence capped at 0.6). Board memory has its own write path (`WorkspaceService`). Read paths: Core injects a bounded `memory` block into every Brain turn and serves read-only `/v1/memory/*` (the Memory Center and the `/api/memory/*` relay; the only write is a candidate decision); all are token-protected and bounded. The reflex / voice model has no memory tool and cannot mutate or read memory. Injected memory is data, not instructions: the agent brief frames it so and neutralises lines that imitate a brief section; the trace keeps its size only; diagnostics never carry memory text or the recall query. Private scope stays out of any non-Brain reader, out of remote embeddings (opt-in `semantic.provider = openai`, `semantic.allow_private` false by default) and out of the optional Tencent sidecar (`memory.tencent.allow_private` false by default) unless the user allows it. Loadouts are deny-by-default: a sub-agent sees only the memory scopes, Wiki pages, CodeGraph repos and skills its loadout names.

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

### 5. Barehands (upstream board) mutation authentication

At each full launch, Jarvis generates a high-entropy random token. It is passed in process environment to Jarvis and Barehands; commands send it only in `X-Jarvis-Token`. It is not embedded in a URL, page, config file or visualizer process environment.

Patched Barehands rejects `/cmd` when the configured token is absent, mismatched, or an explicitly supplied Origin is non-loopback.

### 6. No runtime CDN/model dependency for Barehands (upstream board)

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

Memory adapter resolves paths within a fixed root (`<data_root>/memory`), repeatedly decodes URL-encoded input before checks, and rejects symlink escapes. Every index (FTS5 `index.sqlite3`, semantic `semantic.sqlite3`, Tencent mirror ledger) is derived and disposable; each hit is re-read from the canonical store, so a stale index cannot surface a note outside the caller's scope.

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

With `scene.enabled` (**on by default** since the closing human decision B1, so this
section describes the normal configuration, not an opt-in one; a stored `false`
turns it off; `JARVIS_SCENE_ENABLED` overrides both and then
locks the setting: writes are refused `scene_env_override`), the conversational
Claude CLI brain launched afterwards gets a **write-capable** MCP server, `jarvis-display` (`python -m jarvis display-mcp`,
declared per launch through `--mcp-config`; `docs/ARCHITECTURE.md` › *Brain
display MCP*). It can create, edit, move, hide and link scene objects in Core's
persistent scene, and since the 19/09/2026 rule it also archives, pins and
unpins through `scene_archive` and `scene_pin`: **the brain has exactly the
user's hand** on the scene (`ALLOWED_SCENE_OPS[brain] = frozenset(SceneOp)`;
decision 14 and the pin/unpin reservation are lifted, because they sent the
gesture back to the user). This is not a wider attack surface — the brain could
already reach every one of those operations by shell, by file or by
`POST /v1/scene/commands` with `runtime/core.token` — but a **named, bounded and
traced** capability instead of an out-of-catalog, out-of-journal workaround:
each call is a catalogued tool with readable selectors, sent as **one**
selection command (all or nothing, one revision, at most 512 members; Slice 05
of `jarvis-mcp-semantic-batch-inspector`), and it leaves `display.tool` / `display.tool_refused` in
`runtime/trace.jsonl`. Background jobs and speculative analysis never receive
the server; speculative analysis keeps `--strict-mcp-config` and no tools.

What the reducer still refuses to the brain is never "this belongs to the user"
but a truth from another layer: actor `runtime` is Core's projector, not a
person (`op_not_allowed` for `runtime`); `exec_state`/`work_ref` are read from
Core and not written from the scene (`execution_truth`, decision 17); an
`agent`/`job` star is born of an execution fact, not of a command
(`execution_node`); and a `resolver` placement is committed by `user` only
(`resolver_actor`), the browser's AutoResolver going through the Control
Center's user proxy. A user pin protects an object's **place** against automatic
placement, not its presence on screen: `pinned_by_user` now refuses only a
`placed_by = resolver` write, and a pinned object stays movable by explicit
command, hideable and archivable.

What this guarantee is **not**:

- the actor field of a scene command is a **declaration**, not an
  authentication. Core's bearer token (`runtime/core.token`) is a loopback session
  credential shared by every local JARVIS process;
- the brain runs as the same OS user with `--permission-mode bypassPermissions`
  and has Bash, file and web tools. It can read `core.token` and send
  `POST /v1/scene/commands` claiming `user`, which would commit the last writes
  the reducer keeps for that actor (a `resolver` placement), and it can already
  modify files, including the scene database, or the code;
- the V1 guarantee therefore holds for an **honest caller** only: tool catalog +
  reducer authority. What the catalog buys is not prevention but legibility —
  every scene write the brain makes on its own behalf is a named tool call with
  its selector and its counts in `runtime/trace.jsonl`, and a write that went
  around the catalog would leave no `display.*` entry at all. Evidence comes
  from the journal, not from a boundary.

Prompt injection through the scene. Runtime star titles are sub-agent labels,
which can copy web or file content, and they enter the brain's context through
`scene_inspect`, and since Slice 09 full summaries, artifact items, URLs and hosts
enter it through `scene_get` (so do ids, categories and titles written by the user). The
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

User controls (Slice 08). `archive_many` is bounded by **content**, not by
actor: one command archives every terminal star, its signals and orphan
artifacts (at most 512 ids), and the reducer refuses the **whole** batch as soon
as one id does not qualify (`bulk_archivable` / `not_bulk_archivable`), so a
confirmed count that went stale is recomputed instead of half-applied. It stays
in practice the page's op — the brain's tools archive object by object with
`archive` — but no authority rule reserves it to `user`.
`POST /v1/work/cancel` is **not** refused to the brain
by construction: it has no actor at all and is protected by the bearer token only,
like every Core route; it cancels exactly one Core job (never a Claude sub-agent,
409 `not_cancellable` for any other source) and never touches the brain work item
behind it. The Control Center exposes them to the page only through
`POST /api/scene/commands` (actor forced to `user`) and `POST /api/jobs/cancel`
(origin guard like every POST, strict 4 KiB body, only `source = job` relayed).
The threat model does not change in kind: a brain that reads `core.token` can
already claim `user`, and it can cancel a Core job through the token route just
as it could kill processes with its own tools. Same honest-caller limit.

Semantic artifacts and openable links (Slice 07). The brain's
`scene_add_artifact` writes one artifact and its `explains` link through the
brain/user-only `attach_artifact` op (runtime is refused). Item URLs are
brain-chosen and may come from web content, so an artifact link is an **injection
and phishing surface** on the user's own dashboard. Controls: the domain accepts
only single-line `http://`/`https://` URLs (≤ 2 048 chars). Since the Slice 09
QA rework the page and the brain apply **one conservative rule by construction**
(`link_host` in `jarvis/domain/scene_links.py`, `linkHost` in
`control_center_scene_layout.js`, both tested against the same 107-URL corpus): a
URL is a link, and has a host in `scene_get`, only if it starts exactly with
`http://` or `https://`; its percent-encoded length, computed identically on both
sides as an upper bound of the browser's `href`, is at most 2 048; contains no backslash, whitespace, control character, DEL,
no-break space, soft hyphen, bidi mark, invisible character or full-width or
ideographic dot anywhere; has no `@` and no `%` in its authority; and its host is a
plain ASCII dotted name (standard labels, no `xn--`, so no international name), a
strict dotted IPv4 (a numeric-looking last label such as `0x7f.1` is refused) or a
bracketed hex IPv6, with a port ≤ 65535. Otherwise the item is text,
`host: null`, `link: false`, for the page and for the brain alike. The renderer
(`linkOf`) additionally requires `new URL()` to parse it with an `http:`/`https:`
protocol, **no username or password**, and a hostname equal to the rule's host;
`href` is the parser's normalised form and is
set as a property, never through markup; `target="_blank"`,
`rel="noopener noreferrer"`, `referrerpolicy="no-referrer"`; the host is printed
**before** the label in a non-shrinking element and, when space is short, cut
**from the left** only, showing the longest suffix that fits, so its registrable
end stays visible as far as the room allows (`…ogin-check.co.uk`, never
`docs.python.org…` nor a bare `…co.uk`; rows under 260 px give the host the whole
row); the full host is in the
accessible name and tooltip, never pre-truncated; a long brain label or ref
shrinks instead. Everything else stays text (`textContent`). Opening a link is a
user click (a Bare Hands pinch opens nothing: popups need real user activation).
Right-click on a link keeps the browser's own menu. Not covered, accepted: a
legitimate-looking but hostile `https` host and ASCII look-alikes (mitigated only
by the printed host); international hosts are text, not links (the rule refuses
IDN and punycode rather than showing an opaque host). Brain/user can no
longer give an artifact link the signal shape (`signal_shape`).

Screen-content exposure (Slice 09, part 2, `scene_capture`). The brain can
obtain an **image of the scene layer** as the visible Control Center leader page
draws it: windows, capsules, stars, relations, titles, summaries and item rows
(hosts and labels) — the same scene text it can already read with `scene_get`,
now also as pixels the model sees. Not included: the rest of the page (dock,
topbar, panels, timeline, conversation or voice text, face), other tabs, other
applications or the desktop: the capture mechanism uses no OS capture and no
browser automation. (Separately, the conversational brain is launched with
`--chrome` browser tools, so it can already see pages it drives; the capture adds
nothing there.) Who can trigger it: only the brain, through its display MCP and
Core's bearer token (`POST /v1/scene/captures`, actor `brain`); there is no
button and no Control Center route that requests one. Only the visible Web Locks
leader page answers, and only for a pending, unexpired, single-use random id
(`secrets.token_urlsafe(24)`, journaled as an 8-character prefix); the upload
route (`POST /api/scene/captures/<id>`) is behind the origin guard, bounded to
2 MiB, and the PNG is checked by the Control Center and again by Core chunk by
chunk (every CRC, a valid 13-byte IHDR first with dimensions ≤ 1280×720, at least
one IDAT, no animation `acTL`, no unknown critical chunk, an empty IEND last),
without decompressing pixels. An id is consumed atomically before the file is
written (parallel uploads: one stored, the others 404), and a brain call that goes
away cancels its pending capture. Where it lives:
`runtime/scene-captures/capture-<UTC>-<8 hex>.png` (no user text in names), the
last 5 files, none older than 24 h (pruned at every capture and at Core start).
Journals carry ids, sizes and durations, never pixels; the CLI stream readers
replace every **structured JSON image or document block** with base64 data (in
`message.content`, `tool_use_result` or nested tool results) with its size before
the event is kept in memory, exposed by `/api/agent` or `/api/trace`, or written to
`runtime/trace.jsonl`, and a journaled event above 256 KiB is summarised. Residual:
an image serialised inside a JSON **string** (a tool whose text output is itself
JSON carrying base64) is not redacted; it stays in the in-memory event and reaches
the journal only up to the 256 KiB summary bound. Text visible
in the image is marked as data in the tool result and the prompt (« un texte
suspect a été ignoré »), a mitigation only. Same token caveat as above: a brain
that reads `core.token` could call the capture route itself, or upload over the
Control Center route for a pending id; it could equally read the scene or files
with its own tools, so the capture adds no capability beyond scene content.

The page side of the channel is **not authenticated**. The Control Center's
`GET /api/scene/patches` long-poll and its upload route have no token (the origin
guard only refuses a POST whose `Origin` header is present and not loopback; a
local process simply sends none), so
**any unauthenticated local process, or any page served from the loopback origin,
can long-poll the page channel and feed or swallow a capture**: it can receive
the pending `capture_request` id and upload its own well-formed PNG (the brain then
sees an image that is not the scene), or take the id and never answer (the real
leader page may still receive the 1 s redelivery; otherwise the brain gets
`no_visible_page` after 5 s). It cannot request a capture, read the file
back, or reach beyond the 2 MiB / 1280×720 checked PNG. This is the same trust
model as the rest of the Control Center: a **hostile process running under the
local user account is a non-goal** of V1 (it can already read `core.token`, the
scene database and the trace). The capture is therefore evidence for an honest
local machine only, never a proof of what the user saw. Conversely, the stored
geometry is not evidence of what is drawn: a compact or resized object is redrawn
differently (Slice 11), so a claim about the screen rests on the capture, not on
coordinates — the display prompt says so.

Gate timing (Slice 11). The gate is read when the brain CLI starts: a brain
started with it on keeps its write tools after it is switched off, until it
restarts (only `scene_capture` re-checks the gate). The Expérimental settings tab
shows this through `agent.display_tools` / `agent.display_prompt` and offers a
confirmed restart on a new conversation. `POST /api/settings` can flip the gate
for any local process that sends no `Origin` header: same trust model as the rest
of the Control Center.

Privacy and retention. Core projects the scene whether or not the display is on:
sub-agent labels, runtime failure summaries, brain notes, artifact summaries and
URLs are persisted in `data/state/scene.sqlite3` (local, not encrypted, like
`jarvis.sqlite3`). Archived objects move to `scene_history`, which is **never
pruned in V1**; there is no archive undo and no purge command. Captures stay in
`runtime/scene-captures/` (5 files, 24 h). Nothing of the scene leaves the machine
except what the brain itself sends to its model provider (scene text it reads,
capture images).

The generated `runtime/display-mcp.json` holds the interpreter path, Core's
loopback host and port and the token file **path**, never the token. Tool journal
entries (`display.*`) carry identifiers and outcomes, never note content. Making
the actor an authenticated property (per-actor credentials the brain cannot read,
or an OS boundary around the brain) is out of V1 scope.

### 14. Bare Hands (native subsystem): camera, assets, command channel, traces

Four surfaces that belong to the native subsystem and to nothing else. It runs
**inside the Control Center page**: no separate process, no port, no token, no
network egress of its own.

**The camera is opened by the page, and only after an explicit switch.** The
`Activer Bare Hands` switch in the Expérimental tab is **off by default** and
the browser's own camera permission prompt still gates it — Jarvis cannot grant
it. Turning it on leads to `sleep`, never straight to interaction: the camera is
open but feeds only a 5 fps watcher, and no pointer, hover or click exists until
the user holds the wake pose for a second. Frames are processed in the page by
locally served MediaPipe and are **never uploaded, never written to disk, and
never sent to any model provider**. Closing the page or navigating away releases
the device (`pagehide` disables an engaged controller).

**There is no raw-video path at all.** Not disabled, not opt-in — absent. The
only thing that leaves the tracker is a neutral `HandFrame` of scalars.

**`GET /barehands/assets/…` serves a closed whitelist, not a directory.** Six
exact names (`ASSETS` in `jarvis/runtime/barehands_test_mode.py`) map to six
exact files; anything else is 404 whatever the disk holds. A repository-wide
grep for `FileResponse|web.static|StaticFiles|send_file` under `jarvis/` returns
**exactly one hit** — this handler — so there is no second, more permissive way
to serve a file. Tests cover traversal, aliases and not-installed names.

**The `/api/barehands/commands` trio is origin-guarded on every method**, GET
included, and is listed in `READ_GUARDED_ROUTES` so the Host must be loopback
too (DNS rebinding) and `Sec-Fetch-Site: cross-site` is refused outright. The
GET matters for an unusual reason: `deliver()` marks a command delivered to the
**first** long-poll that asks, so a cross-origin page that could not read the
body would still have **consumed** the command — a denial of command, not a
leak. Every refusal carries a stable code in the body **and** in
`X-Jarvis-Error-Code`. `GET /api/scene/patches` has the same long-poll shape but
not that property (its cursor is caller-supplied and nothing is consumed), so it
is deliberately not in the table.

**Traces are opt-in, scalar-only, and local.** Diagnostic recording is off
unless the user starts it. A trace may carry **numbers, closed-vocabulary names
and booleans — and nothing else**: no landmarks, no images, no free text. The
whitelist runs at module load in the page (`assertDerivedOnly`) and again on the
server (`jarvis/runtime/barehands_trace.py`), which refuses a document with a
code rather than storing what it cannot vouch for. Files land in
`<runtime_root>/barehands-traces/`, capped per document (18000 frames, 32 MiB),
with one journal line each. **They are not pruned in V1** and are plain local
JSON — the same standing as `runtime/trace.jsonl`.

### 15. Managed MCP plugins: vault, endpoints, OAuth, redaction, argv

Handoff `jarvis-generic-mcp-plugin-runtime` (2026-09-30). A plugin is a remote
MCP server the user adds by URL; its tools reach the brain only through the
`jarvis-tools` gateway ([ARCHITECTURE.md](ARCHITECTURE.md) › *Core-owned MCP
plugin runtime*). Full contract and codes: [mcp/plugins.md](mcp/plugins.md)
§3, §4, §8.2, §10.

**Threat model.** Core, the Control Center and the brain CLI run as the same
OS user. Plugin secrets (OAuth tokens and client registration, manual bearer
or header values) are sealed with **Windows DPAPI CurrentUser**
(`jarvis/adapters/dpapi_sealer.py`, `CRYPTPROTECT_UI_FORBIDDEN`, entropy
`jarvis-mcp-v1`) and stored as opaque blobs in `mcp_credentials` of
`jarvis.sqlite3`. This protects against other OS users and against a copy of
the database (a copied or moved file unseals nowhere else; the plugin then
needs « Reconnecter »). It does **not** protect against a malicious process of
the same user, which can call DPAPI too — the same boundary as
`runtime/core.token` (control 13). The guarantee Jarvis makes instead is: **no
secret in model context, tool descriptors, API/UI payloads, journals, traces
or `--mcp-config` files**. Each sealed payload is bound to
`{plugin_id, endpoint_origin}`: a blob copied onto another plugin or origin
unseals to nothing. No sealer (non-Windows) ⇒ an OAuth connect or a
bearer/header credential is refused (`mcp_vault_unavailable`; a default `auto`
connect goes out unauthenticated and an OAuth server leaves the plugin
`required`); there is **no plaintext fallback**, and the
Control Center's plaintext `credentials.py` store is not used. Proof:
`tests/unit/test_mcp_secret_sentinel.py` (sentinel credential, bearer and
OAuth, absent from every response, model result, config file and run file;
present in the database only sealed).

**Endpoint / SSRF policy.** `validate_endpoint` (`jarvis/domain/mcp_endpoint.py`)
accepts `https` only; refuses userinfo, fragments, credential-like query keys,
over-long or non-IDNA hosts, and disguised IPv4 forms; refuses any private,
loopback, link-local, CGNAT, metadata or IPv6-embedded forbidden address
(`mcp_endpoint_forbidden`). `PolicyTransport` re-checks every **DNS-resolved**
address before each request (including OAuth discovery, registration and
token requests), caps response bodies at 4 MiB, never follows a cross-origin
redirect, never forwards credentials across origins and ignores environment proxies (`trust_env=False`); static credentials
are set on MCP requests to the plugin origin only. The development flag
`JARVIS_MCP_ALLOW_LOOPBACK_HTTP=1` (read by Core at start, journaled
`mcp.plugins.connector_ready`) allows `http` to loopback and `localhost` —
for the test fakes only; never set it on a user machine. Residual risk: DNS
rebinding between the check and the connect is not pinned in V1.

**Icons.** Core never fetches a plugin icon; the Control Center's browser does.
An advertised icon is kept only if it passes the same static endpoint policy
**without** the development flag (https, no private/loopback/metadata literal,
no `localhost`, no userinfo, no credential-like query, ≤ 512 chars); otherwise
the card draws a letter. The page loads it with `referrerpolicy=no-referrer`.

**OAuth.** Built on the `mcp` SDK's `OAuthClientProvider` (subclassed): RFC 9728
protected-resource discovery, RFC 8707 `resource`, RFC 8414 issuer validation,
dynamic client registration as a public client (`token_endpoint_auth_method
none`, loopback redirect `http://127.0.0.1:<JARVIS_UI_PORT>/api/mcp/oauth/callback`,
`refresh_token` grant only when the AS advertises it), **PKCE S256**, a
**single-use `state`** held by Core with a **300 s TTL**, and the **RFC 9207
`iss` check** when the AS advertises it (mismatch ⇒ the code is never
exchanged). The callback lives outside the guarded `/api/mcp/plugins*`
prefix (the AS redirect is a cross-site navigation) and is protected instead by
the single-use state, the TTL, the `iss` check and a loopback `Host` check; its
page is static, `no-store`, `no-referrer`, and never echoes `code` or `state`.
The authorization URL is opened only if it is `https` (or loopback `http`).
Revocation on Disconnect (RFC 7009) is sent only to the `revocation_endpoint`
of the issuer the tokens were issued by (`client_info.issuer`); when the
protected resource names another authorization server, the old tokens are
forgotten locally **without** being sent anywhere. Tool calls, boot and backoff
reconnects never open a browser (non-interactive mode): an authorization need
answers `mcp_plugin_reauthorization_required`.

**Redaction.** A remote text reaches the model only through
`call_tool` results and `mcp_remote_tool_error` (≤ 4 KiB), both passed through
`redact` / `redact_structured`: every vault value of the plugin, `Bearer …`,
JWT shapes, `Authorization` values of any scheme, `Cookie`/`Set-Cookie`,
`session=`, AWS signature parameters, `sig=`/`signature=`, and the value of
credential-named `key=value` / `"key": "value"` pairs are masked. Paging
tokens are **exempt** on purpose (`nextPageToken`, `$skiptoken`,
`next_page_token`, `syncToken`, `page-token`…) so the model can page.
**Accepted prose trade-off (V1):** an unquoted `key: value` written as prose
is left intact (« Remaining token: 512 » must stay readable), so a secret the
vault does not hold, written by a remote server in plain prose
(« your token: abc123 »), is not masked. Journals never carry an intent,
argument or result text (identifiers, codes, sizes and durations only).

**Codex argv.** `codex` on Windows is the npm shim `codex.CMD`, run by
`cmd.exe`, which splits on `&`, expands `%VAR%` and strips `^` whatever the
TOML quoting. The gateway overrides therefore carry **names only**:
`-c mcp_servers.jarvis-tools.env_vars=[…]` lists the `JARVIS_*` variables, whose
values (Core host, port, paths of the token file and runtime — never the token)
are set in the Codex child process environment; the only **path** left in
argv is `command` (the interpreter path) — the other overrides are the fixed
`args`, the variable names and `tool_timeout_sec`. If the resolved Codex executable is a
`.cmd`/`.bat` and an override still carries a `cmd.exe` metacharacter, that
turn runs **without** the gateway (`tools_mcp_unsafe_argv`, journaled).

**Permission mode.** V1 applies no confirmation gate to destructive plugin tools
beyond the CLI permission mode (the brain runs as native write tools do); under
Codex `workspace-write`/`read-only`, Codex itself refuses `call_tool`. This is
an agent-0 decision (ARCH §15 Q3) to be confirmed by the Human at acceptance.

### 16. Prefab sandbox

Status: library (Slice 02) and frame runtime (Slice 03:
`jarvis/runtime/control_center_prefab_protocol.js`,
`jarvis/runtime/control_center_prefab_host.js`, `jarvis/prefabs/runtime/shim.js`,
`/api/prefabs` guarded) and events and the scene block (Slice 04:
`jarvis/core/prefab_events.py`, `POST /api/prefabs/events` with its actor
forced to `user`, Core validation of every new or changed block, fail closed)
and the brain's definition operations with the base-edit witness (Slice 07:
`jarvis/runtime/display_prefabs.py`, `jarvis/core/prefab_witness.py`)
implemented — handoff `jarvis-scene-window-prefab-foundation`. Full
contract: [prefabs.md](prefabs.md).

A prefab definition carries HTML, CSS and JS that the brain or the user may
author. That code is **untrusted** and renders inside the Control Center page,
so the boundary is the browser sandbox, not the content check:

- **One runtime.** Every prefab instance, base or custom, renders in a
  `<iframe sandbox="allow-scripts">` — exactly that value; never
  `allow-same-origin`, `allow-popups`, `allow-forms`, `allow-top-navigation` or
  `allow-modals`. The frame has an opaque origin: no Control Center cookies or
  storage, no `parent.document`.
- **CSP first.** Right after `<meta charset>`, before anything that can load,
  the frame's `<head>` carries a CSP meta:
  `default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; base-uri 'none'; form-action 'none'`.
  No network, no `eval`.
- **No navigation out of a frame.** Guaranteed by the **page**, not the
  frame: the Control Center page is served with
  `Content-Security-Policy: frame-src <visualizer origin>` (`'none'` without a
  visualizer; `frame_src_policy` in `control_center.py`, the only directive
  set), so the browser blocks any navigation of a prefab frame —
  `location.href`, a link, an image map, a meta refresh — before a request
  leaves; `srcdoc` frames are not governed by `frame-src` and keep running.
  Second layer, **detection in the host**: a second `load` or a second
  `ready` in one frame generation removes the frame, stops hearing it,
  never re-sends `init` (props and data never reach a foreign document),
  shows the error band and logs `scene.prefab_error` (`navigation` /
  `protocol`). It bounds the damage in a browser that would ignore
  `frame-src`; it does not stop the request. Third, hygiene only: the lint
  refuses `<area`, `<form`, `<meta`, `<base`. `open_url` refuses local and
  private hosts (loopback, RFC 1918, link-local, `localhost`, IPv6
  equivalents), so a frame cannot make the user open Core, the Control
  Center or the LAN; the scene's own links keep `linkOf` unchanged.
- **Bounded before work.** The protocol refuses an oversized message before
  serializing it or running a pattern over it (lower-bound size walk
  stopping at 8 KiB, name and URL length first, error text cut before
  cleaning); the host coalesces `resize` (one per 16 ms), limits `error` to
  10/s per frame and keeps at most 64 bundles (LRU).
- **One HTML path.** The scene page keeps zero `innerHTML`,
  `insertAdjacentHTML` and `outerHTML`; setting `iframe.srcdoc` is the only
  HTML path and lives only in `jarvis/runtime/control_center_prefab_host.js`
  (static test).
- **Narrow channel.** Frame and host speak `postMessage` with a versioned
  protocol (`jv: 1`). The host accepts a message only from its own frame
  (`event.source === iframe.contentWindow`, `event.origin === "null"`) and drops
  anything else. The frame can only emit an event, a height, an `http(s)` URL to
  open (validated by the host, `noopener,noreferrer`) or an error. It sends
  nothing to the host but its instance's own props, data and theme, never a
  secret. **No event executes a tool**; events are rate-limited (10/s per frame
  in the host, 30/s in Core, then `429 rate_limited`).
- **Events are user writes, bounded by the manifest.** A `state` event becomes
  a `patch_object` as actor `user` through the reducer, limited to the data keys
  the manifest declares in `writes`, checked against the current data
  (`stale` otherwise) and revalidated. A `notify` event writes nothing; it
  reaches the brain as data in the next turn context, never as an instruction.
- **Defence in depth on the Control Center.** `Origin: null` is already refused
  on every non-GET (`ControlCenter._origin_guard`), and `/api/prefabs` joins
  `READ_GUARDED_ROUTES` (loopback Host and Origin, no cross-site
  `Sec-Fetch-Site`, on every method).
- **Validation in Core.** Definitions, instances and events are validated by
  Core (`PrefabService`); the MCP and the page only pre-check shape. The
  template, style and behavior lint (no `<script`, `<area`, `on*=`, `@import`,
  remote `url(`…) is hygiene, not the boundary.
- **Immutable library, protected base.** A published version is never
  rewritten (staging folder then `os.rename`, which fails on an existing
  target); links, junctions and reparse points are refused through
  `safe_folders`; a fingerprint mismatch marks a version `tampered` and refuses
  it for new instances. Shipped base prefabs (`jarvis.*`) are never written at
  runtime and are locked by fingerprint. A base prefab changes only as a new
  version in the data root through `PrefabService.edit_base`, which requires
  an existing `jarvis.*` id, `confirmed_by_user = true`, a `user_request` of
  12–500 characters that, normalized, still holds ≥ 12 characters and ≥ 3
  words and **names the prefab** (last id segment, published title or alias,
  whole words), and a **witness**: that request, normalized, must appear as
  whole words in a user turn recorded in Conversation Events within the last
  30 minutes.
  Any failure is `base_edit_unconfirmed`; a success is journaled
  `core.prefab.base_edited` at `warning`. The Control Center has no base-edit
  route; only the brain tool `prefab_edit_base` reaches it. Its one definition
  write is the library's fork relay `POST /api/prefabs` (Slice 08): actor
  forced to `user`, body ≤ 512 KiB, and Core refuses a `jarvis.*` id there too
  (`base_protected`). The witness
  (Slice 07, `ConversationUtteranceWitness`) accepts only the content of a
  public `user.transcript.accepted` event, actor `user`, in which the
  normalized quote appears as whole words. Core writes that event
  (`VoiceAdmissionService.record_user_turn_accepted`) for every durable user
  turn: voice admission, `POST /v1/conversations/{id}/brain-turns` (including
  `source=text`) and the legacy `POST /v1/conversations/{id}/turns` with
  `kind=user`; `user.*` events are refused by the ingestion route. Brain
  messages, scene titles, prefab events, diagnostic events and older turns
  never count, and the lookup journal carries counts, never the words. `prefab_save` refuses a
  `jarvis.*` id before sending and Core refuses it again (`base_protected`).

What the witness is: proof that recent user-turn events contain the quoted
words, and that those words name the prefab. It guards against an
**accidental** base edit and against one **prompt-injected** through the tool
path (a page, a file, a prefab payload or a frame event cannot write a user
turn). What it is **not**:

- not proof that the user meant the edit the brain made (a negated sentence
  quoted in part still matches: the gate checks words, not intent);
- **not a boundary against a process holding the Core token.** Any holder of
  `core.token` can create user turns through the legacy
  `POST /v1/conversations/{id}/turns` (`kind=user`) or
  `POST /v1/conversations/{id}/brain-turns` (`source=text`), and both
  producers write `user.transcript.accepted`. The brain runs with shell tools
  and could read that token, or write the data root (`<data_root>/prefabs/`)
  directly; the base-edit gate does not stop that, the brain's instructions
  and the declared actor model do (control 13).

A brain that ignores its instructions can also write custom prefabs
(`prefab_save`) and impersonate `user` on the scene, as in control 13. A sandboxed frame is not rasterized by
`scene_capture`, so the brain sees a prefab window's title and summary, not its
drawn body.

### 17. Configurable wake word (openWakeWord): resting microphone, models, no audio kept

The spoken wake word is **disabled by default** (`wake_word.enabled=false`): with
no setting and no Picovoice key JARVIS opens no microphone at rest. A resting
detector (an open input stream while JARVIS waits) exists only if the operator
turned it on in Settings or configured a Porcupine key, and it is closed during an
active session. Every input stream is counted in `jarvis/audio/input_ownership.py`
(`wakeword_openwakeword` for the SIMPLE openWakeWord detector), so a leak or a
second owner is a failed test, not a silent state.

- **No audio is persisted.** The detector holds frames in memory only (a bounded
  queue of 16 blocks in SIMPLE; the hub's bounded pre-roll in PRESENTATION).
  Traces carry a normalised source, the keyword label, a score and a threshold,
  never samples and never speech text; the timeline receives nothing.
- **Detection is local.** openWakeWord runs on the CPU through `onnxruntime`;
  no microphone audio leaves the machine for wake-word recognition.
- **Models are downloaded only on an explicit command, verified before use.** Three
  ONNX files from the pinned upstream release, installed under the git-ignored
  `runtime/wake-word/models/` only after their size and SHA-256 (pinned in
  `jarvis/adapters/wakeword_model_catalog.py`) match; a mismatch installs nothing
  (`wake_model_mismatch`) and a tampered installed file is refused at load.
- **Licence.** Code Apache-2.0; the pre-trained models are CC BY-NC-SA 4.0: private,
  non-commercial testing only (`third_party/README.md`).
- **Failure never removes the manual key.** F9 is a separate backend; a missing
  extra, a missing or altered model or a dead engine is said in
  `runtime/trace.jsonl` and leaves F9 usable.

### 18. Remotion scene sandbox: untrusted TSX/JS never gets Jarvis authority

> Slice 13 addendum: the manifest `data` block (user slide content) now reaches the scene, under the reserved `inputProps` key `data`, after the same
> validation as `props` ([remotion-isolation.md](remotion-isolation.md) section 12). It can leave through the same residual channels as `props` (section 9: DNS
> prefetch, bare TCP connect). Never put a secret in a manifest `props` or `data` value.

Status: contract and implementation delivered (handoff `jarvis-remotion-presentation-integration`, Slice 06); proven in a real
Chrome against a hostile corpus, **not yet mounted** (the Player is Slice 10). Full contract, rule list, protocol and evidence:
[remotion-isolation.md](remotion-isolation.md).

A Remotion scene is TSX/JS written by the brain, a model or an imported template. It is **untrusted**, so the boundary is the
browser, not a content check:

- **Dedicated origin.** The compiled `scene.js` only runs in a page served by a second loopback listener on **another address
  and port** than Core (cookies are shared between ports of one host, so a port alone is refused in code). The listener serves
  only non-secret compile output, sets no cookie and never receives a Core token.
- **`<iframe sandbox="allow-scripts">`, exactly** (never `allow-same-origin`, `allow-popups`, `allow-top-navigation`,
  `allow-forms`, `allow-modals`), mirrored by the CSP `sandbox` directive so the document is sandboxed even opened top-level.
- **CSP as a header:** `default-src 'none'`, scripts by per-response nonce plus `integrity` (no `unsafe-eval`, no
  `unsafe-inline` script), `connect-src 'none'`, `frame-src`/`worker-src`/`object-src 'none'`, images/media/fonts from the origin
  only, `frame-ancestors` the Control Center only. Every file is served `nosniff`, with a type fixed by its extension, a
  sandboxing CSP (an SVG opened as a document runs nothing) and no cookie.
- **Narrow channel.** `postMessage` protocol `rs: 1` (typed, exact fields, bounded, source-checked, origin-checked). A hostile
  frame is a data source: more than 20 refused messages, a message flood lasting 3 seconds, a missing `pong` for 3 s, or a
  reported JS heap above 768 MB removes the frame; the host page stays responsive (the frame is another process). The
  watchdog and the heap report are **best-effort against naive or accidental abuse only**: the scene shares the frame's JS
  realm and can answer pings, forge a `pong` or redefine `performance.memory`. A huge `postMessage` (tens of MB and up) stalls
  the host for the duration of the structured clone before any handler runs; the host cannot prevent that.
- **Static filter first** (`SOURCE_GUARDS`, at publication and at every re-read; every pattern is bounded and scanned under a
  time budget that refuses, never hangs): forbidden network/eval/worker/global APIs,
  external resources, active SVG content, asset signature mismatches. It is a filter, **not** a boundary: the evidence corpus
  contains, for each attack, a version written to pass it.
- **Compile side.** The compiler never runs scene code; its Node child gets an allow-listed environment (no `*_KEY`, `*_TOKEN`),
  a 1 GB V8 heap cap, a deadline and a killed process tree. Template archives are read in memory, bounded, and may only hold
  `src/**` and `public/**`; no `package.json`, no implicit `npm install`.

**Not claimed: "no network exfiltration".** The sandbox guarantees that a scene holds **no Jarvis secret** (token, cookie, storage,
tools, Core) and cannot act as Jarvis. `connect-src 'none'` closes fetch/XHR/WebSocket/beacon/prefetch/preload, but two channels
stay open: `<link rel=dns-prefetch>` (a DNS name chosen by the scene) and `<link rel=preconnect>` (a bare TCP connection to a
chosen host:port, also a blind port probe of the workstation and LAN). Measured in Chrome 154: neither the CSP nor
`X-DNS-Prefetch-Control: off` nor `allow=""` closes them. WebRTC (no CSP directive) is closed only in-realm, best-effort, by
the bootstrap removing `RTCPeerConnection` before scene code runs. Whatever the host gives the scene (`inputProps`, assets)
can leave through these channels: never pass a scene data more sensitive than the slide content.

Also residual: Chrome-only evidence; CPU burn by a still-responsive scene is not detected; a scene can draw a fake form inside
its own frame (it cannot submit or leave it); the native memory of the compiler child is not capped;
`Access-Control-Allow-Origin: *` on script/font files of the dedicated origin (keys are 128-bit content hashes). The page that
mounts the frame must carry `frame-src <sandbox origin>` alone (Slice 10 implements and tests it). See remotion-isolation.md
section 9.

### 19. Remotion Studio (optional dev server): a hardened process, not a sandbox

Status: contract and implementation delivered (handoff `jarvis-remotion-presentation-integration`, Slice 11, QA rework applied); proven
against the real `remotion studio`, an isolated Core and Control Center and a real Chrome. Contract and evidence:
[remotion-studio.md](remotion-studio.md).

The stock Studio binds `0.0.0.0`/`::`, its HTTP API can start a package manager, an editor, a terminal or a coding agent, and the
scene's code runs in the Studio tab **on the same origin as that API** (no iframe sandbox, unlike the Player of section 18). It is
therefore opt-in and wrapped by a preload guard that runs inside the Studio process:

- **Explicit, informed request only.** Core routes `open`, `restart` and `sync` of another scene refuse (400
  `remotion_studio_ack_required`) without `acknowledge_unsandboxed_scene: true`; the Control Center sends it only after a confirmation
  that names the risk and shows the exact version's provenance (stronger for a version not written by the user). No brain, MCP or agent
  path can open the Studio (tested).
- **Loopback only**: every TCP `listen` is rewritten to `127.0.0.1`/`::1` (measured: the LAN address refuses the port).
- **No path from a Studio page to the Control Center or any other local service**: CSP `connect-src 'self'` only; the Control Center
  refuses a loopback `Origin` whose port is not its own and any mutating `Sec-Fetch-Site: same-site|cross-site` request; the Studio refuses
  foreign `Origin` on mutating requests and WebSockets, and foreign `Host` (DNS rebinding). Each layer is proven alone, in a real Chrome.
- **No egress**: outbound TCP off the loopback is refused before any DNS (a caller-supplied `lookup` is ignored); DNS names (`dns`,
  `dns.promises`, `Resolver`) and UDP (`dgram.createSocket`, `dgram.Socket`) are refused; Worker threads get the same guard. Every
  refusal is counted and shown on the card.
- **No child process** except the pinned esbuild service the TSX loader needs: package install, editor, terminal, agent, render are refused.
- **Read-only working copy** of exactly the selected scene's `src/**` and `public/**` (no data root, no Board, no secret, allow-listed
  environment); paths are validated (no `..`, drive, backslash, empty segment); edits made anyway are set aside, never published; links
  planted in it are removed, never followed; the tool cache is wiped at each launch.
- **No orphan**: identity by `pid:creation time` and a per-launch identifier; Core stop closes it; if the Core declared in `parent.json`
  (pid and creation time, rewritten by a Core that adopts the Studio) is gone for 60 s the guard ends the process; an idle ceiling ends it too.

**Not claimed**: the guard is JavaScript inside the process, not an OS sandbox. Not covered: `process.binding`, native modules and any
non-JavaScript code; and the browser-side channels the CSP cannot close (WebRTC, `dns-prefetch`/`preconnect` link hints, `<a ping>`,
GET navigation) remain for a hostile scene. Whatever the scene can read (its own source, `defaultProps`) can leave through those channels:
that is why the user must confirm, per opening, knowing the provenance.

### Choix du moteur de présentation (Remotion handoff, Slice 20)

Contrat : [presentation-engine.md](presentation-engine.md) › *Human engine control*. Seule une action humaine nomme un moteur ; Remotion est le défaut, Slidecar une expérience confirmée et journalisée.

- **Déclaration, pas authentification.** Core ne peut pas prouver qu'une requête vient de la page : `actor` est une valeur du corps. Le relais du Control Center la **remplace** par `user` ; le serveur MCP du cerveau envoie `brain` et n'a aucun outil de moteur (test de parité) ; Core refuse tout moteur nommé par un autre acteur (ou sans acteur).
- **Barrière d'accès occasionnel, pas une frontière.** Sur les routes qui nomment un moteur (`POST /api/presentation-studio/presentations` avec `engine`, `.../{id}/experiment`) et sur `POST /api/local-capabilities/remotion/install|repair`, le relais exige `Sec-Fetch-Site: same-origin` (envoyé par tout navigateur pour un fetch de la page ; absent de curl, d'un script Python, d'un outil Bash) en plus de la garde de la Slice 11 (Host et Origin de boucle locale, jamais `cross-site`). Un client qui forge l'en-tête passe : un vrai garde-fou exigerait un secret que le cerveau ne peut pas lire (même compte, même disque : hors de cette Slice).
- **Pas de repli.** Un moteur indisponible est une erreur visible avec sa raison ; jamais l'autre moteur. Les anciens documents lus comme `slidecar` ne sont jamais réécrits par une lecture ; la première sauvegarde garde l'ancien manifeste (`.bak`).
- **Contenu affiché** : titres, raisons et messages du journal Slidecar entrent dans la carte par échappement (test dynamique avec des titres et raisons hostiles dans Chrome).
### 20. Upstream Remotion template import: verified origin, audited dependencies, Core-written provenance

Status: delivered (handoff `jarvis-remotion-presentation-integration`, Slice 18); exercised over the real network, with the real compiler
and in a real Chrome. Full contract, code table and evidence: [remotion-import.md](remotion-import.md).

Importing a template is Core fetching code written by someone else. The import never runs that code; it reads it as text, and the
result is an ordinary Remotion source, so control 18 (the sandbox) is still the execution boundary. The import adds the controls on
what is accepted and what is claimed about it:

- **Verified origins only.** HTTPS to `github.com` repositories of an owner in a user-set allowlist (default `remotion-dev`;
  `control-center-settings.json` > `remotion_import.allowed_owners`, read at each import). The download URL is built from a validated
  owner/repository and a **full commit SHA** (never a branch or tag), against `codeload.github.com`. Hosts are not configurable; no
  arbitrary URL, no `http`, no credentials/port, no preview MP4 or page as a source. Redirects (at most 3) are never followed
  automatically: each must stay on GitHub over HTTPS and on the same repository. Size (12 MiB), time (30 s) and one import at a time
  are bounded. Only Core fetches (a port with a fake for tests); untrusted scene code has no network.
- **Hostile archives refused whole.** In-memory stream, no disk: symlinks, hardlinks, devices, `..`/absolute/backslash paths, second
  roots, duplicate names (case-folded), decompression bombs (linear, capped, 20 s deadline: `import_timeout`) and an archive that does
  not attest the pinned commit. "Attested" only proves GitHub echoed the requested SHA: objects of a fork network can be served under
  an allowed owner's path (not tested), so **the allowlist protects the owner, not the commit** (reachability check: Issue 04).
- **Dependencies are what the source reaches, not what `package.json` claims.** Only `react`, `remotion` (the locked shared tree) are
  admitted; any other reached package is refused with its name and importer. Imports are looked for in the text with and without
  comments, without requiring spaces, so a fake comment (`<p>/*</p>`) cannot hide one; an analysis deadline (20 s) bounds hostile text. `package.json`, lockfiles and scripts are never copied or run.
  No npm, no adapter.
- **Licence is the template's, recorded apart from Remotion's.** The licence text must be EXACTLY a reviewed one (normalised comparison
  with canonical MIT, BSD-2/3, ISC, Apache-2.0, 0BSD, Unlicense, CC0 texts: an added "Commons Clause" / "personal use only" paragraph is
  refused); every licence file must agree. Unlicensed, unknown, copyleft, non-commercial, Remotion's own or a file/`package.json`
  conflict are refused. The licence text travels with the source.
- **Provenance is Core-written, and never laundered.** `catalog.upstream.{commit, archive_sha256, imported_at, changes, source_sha256}` and
  `catalog.runtime_license` can only be written by the importer (`PrefabService.save` and `edit_base` refuse them elsewhere; a revision may
  only carry them unchanged). Carrying is not vouching: the catalog view recomputes the digest of the CURRENT files and reports
  `verified_intact` or "modified since import" with the modified file list; the original origin stays as history only.
- **Scoped to one presentation.** The result is a `presentation-studio.*` prefab version; there is no request field to publish to the
  shared library (promotion is a separate, explicit step, Slice 19). No route reaches the Control Center, the brain or an MCP tool.

**Not claimed**: the import graph is read by pattern, not by a TypeScript parser (the compiler and control 18 are the backstop); licence
detection is by text and is not legal advice; Remotion's company-licence obligation is recorded, not assessed; assets are covered by
the repository licence only; GitHub (and the pinned commit staying available) is trusted for availability, not for content (the archive
SHA-256 and attested commit are recorded).

## Residual risks / non-goals

- Bare Hands traces are never pruned and are not encrypted at rest; a user who recorded a diagnostic session leaves scalar interaction data in `runtime/barehands-traces/` until they delete it by hand.
- Bare Hands has had **no real-camera validation on this run**: the human waived those checks, which means they are un-run, not passed. See `ACCEPTANCE_STATUS.md` and the camera session in `OPERATIONS.md`.
- Wake word: with openWakeWord (or Porcupine) enabled, a microphone stays open while JARVIS rests. A room echo of JARVIS's own voice containing "hey jarvis" is not filtered after playback (no tail guard); unmeasured on a real workstation (`HV-WAKEWORD-MIC-01-e`). The pre-trained models are not for commercial distribution.
- OpenAI is an online provider in this V1; requests leave the machine according to provider/API policy.
- Barehands (the upstream board) and ai-visualizer are third-party AGPL software; operational/distribution license obligations require legal review for commercial packaging. Bare Hands, the native subsystem, carries none of that code and none of that obligation — see § 14.
- The patched Barehands board page still contains upstream inline JavaScript/styles and therefore CSP allows inline execution.
- Remotion scene sandbox (control 18): the static source filter is bypassable by design (the sandbox is the boundary); only Chrome 154 on Windows 11 was exercised; a browser without site isolation would let a spinning scene freeze its host page.
- A fully compromised local user account can read process memory/environment, modify Python code, or replace the interpreter; V1 does not attempt to defend against a hostile OS account.
- There is no cryptographic code signing of this Jarvis ZIP.
- Confirmation is conversational, not OS-level privileged authorization.
- Board placement is an ephemeral UI write and intentionally does not require confirmation.
- V1 has no destructive memory delete tool, no messaging/email tool, no browser navigation tool and no general filesystem writer. **Exception since 2026-09-30:** a managed MCP plugin the user adds may expose such tools (e.g. send mail); they run under the CLI permission mode with no extra confirmation gate (control 15).
- Managed MCP plugins: DPAPI CurrentUser does not protect plugin secrets from a malicious same-user process; DNS rebinding between the endpoint check and the connection is not pinned; prose-form secrets unknown to the vault are not redacted (control 15).
- The Claude conversation brain is launched without `--strict-mcp-config` (pre-existing): the operator's user-level MCP servers (`jarvis-drive`, claude.ai connectors, `claude-in-chrome`) load in the conversation brain with the operator's own authority, outside Jarvis's plugin vault and policy.
- v0.2 constellation scene: the brain's display tool is write-capable and, by the user's own rule, holds the same scene hand as the user — archive, pin and unpin included, bounded at 128 designated objects per call and journalled as `display.tool`. Scene actors are declared, not authenticated; a brain that ignores its instructions can impersonate `user` with `runtime/core.token` (see control 13). Scene text (runtime star titles from sub-agent labels) reaches the brain and is marked as data only; injection resistance is not guaranteed.

## Release rule

Do not label the V1 fully released until the manual workstation gates in `ACCEPTANCE_STATUS.md` pass, especially authenticated/unauthenticated Barehands board checks, the Bare Hands camera session of `OPERATIONS.md`, browser offline load, physical gestures, real microphone/speaker loop, and real-provider latency measurement.

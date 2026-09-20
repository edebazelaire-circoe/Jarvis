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
each call is a catalogued tool with readable selectors, bounded at 128
designated objects per call (`selection_too_large`, refused before anything is
sent), and it leaves `display.tool` / `display.tool_refused` in
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

## Residual risks / non-goals

- Bare Hands traces are never pruned and are not encrypted at rest; a user who recorded a diagnostic session leaves scalar interaction data in `runtime/barehands-traces/` until they delete it by hand.
- Bare Hands has had **no real-camera validation on this run**: the human waived those checks, which means they are un-run, not passed. See `ACCEPTANCE_STATUS.md` and the camera session in `OPERATIONS.md`.
- OpenAI is an online provider in this V1; requests leave the machine according to provider/API policy.
- Barehands (the upstream board) and ai-visualizer are third-party AGPL software; operational/distribution license obligations require legal review for commercial packaging. Bare Hands, the native subsystem, carries none of that code and none of that obligation — see § 14.
- The patched Barehands board page still contains upstream inline JavaScript/styles and therefore CSP allows inline execution.
- A fully compromised local user account can read process memory/environment, modify Python code, or replace the interpreter; V1 does not attempt to defend against a hostile OS account.
- There is no cryptographic code signing of this Jarvis ZIP.
- Confirmation is conversational, not OS-level privileged authorization.
- Board placement is an ephemeral UI write and intentionally does not require confirmation.
- V1 has no destructive memory delete tool, no messaging/email tool, no browser navigation tool and no general filesystem writer.
- v0.2 constellation scene: the brain's display tool is write-capable and, by the user's own rule, holds the same scene hand as the user — archive, pin and unpin included, bounded at 128 designated objects per call and journalled as `display.tool`. Scene actors are declared, not authenticated; a brain that ignores its instructions can impersonate `user` with `runtime/core.token` (see control 13). Scene text (runtime star titles from sub-agent labels) reaches the brain and is marked as data only; injection resistance is not guaranteed.

## Release rule

Do not label the V1 fully released until the manual workstation gates in `ACCEPTANCE_STATUS.md` pass, especially authenticated/unauthenticated Barehands board checks, the Bare Hands camera session of `OPERATIONS.md`, browser offline load, physical gestures, real microphone/speaker loop, and real-provider latency measurement.

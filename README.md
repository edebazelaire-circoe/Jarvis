# Jarvis V1

Jarvis V1 is a local-first, push-to-talk personal assistant prototype built from the implementation handoff in `docs/handoff/`.
It deliberately **does not fork or build on `fullstack-agent`**. The Jarvis core owns state, tools, confirmation policy, memory and provider-neutral contracts; Barehands and ai-visualizer are optional external UI components.

## What is implemented

- Push-to-talk capture to an in-memory WAV clip; no raw audio file is persisted by the normal voice path.
- OpenAI transcription through a replaceable `TranscriptionBackend`.
- OpenAI Responses-based agent through a replaceable `AgentBackend`.
- Exactly three V1 tools: `memory_search`, `memory_append`, `board_present`.
- A deny-by-default `ActionBroker`; persistent writes require exact `oui`/`yes` confirmation and `non`/`no` denies them.
- Markdown as canonical memory plus a disposable/rebuildable local SQLite search index.
- OpenAI TTS through a replaceable `TTSBackend`, with cooperative PTT interruption.
- File signal bus compatible with ai-visualizer.
- Authenticated Barehands `/cmd` integration with a random per-launch token held only in process environment/headers.
- One-time third-party bootstrap with immutable commits, integrity checks and local vendoring of Three.js/MediaPipe so Barehands no longer needs CDN/model downloads at runtime.
- Optional Google Drive access (read/write) behind one OAuth client, exposed both as Jarvis voice tools and as a local MCP stdio server (`python -m jarvis drive-mcp`) usable from Claude Code. See `docs/OPERATIONS.md`.
- Health checks, privacy-safe JSONL diagnostics, automated release gates and a single local launcher.

## Architecture

```text
PTT -> AudioCapture -> TranscriptionBackend -> JarvisOrchestrator -> AgentBackend
                                              |      |              |
                                              |      |              +-> tool calls
                                              |      +-> StatePublisher -> ai-visualizer files
                                              +-> ToolRegistry -> ActionBroker -> Memory / Barehands
                                                                  |
                                                                  +-> confirmation for writes
JarvisOrchestrator -> TTSBackend -> speakers
```

The core package imports no OpenAI, HTTP, sounddevice or keyboard-provider types. External systems are adapters behind ports.
See `docs/ARCHITECTURE.md` for details. The uploaded handoff is preserved verbatim under `docs/handoff-source/`; `docs/handoff/` is the annotated implementation copy.

## Requirements

- Python 3.11+
- A microphone and speakers/headphones for the voice path
- An OpenAI API key for the live STT/agent/TTS path
- Internet once for Python dependencies and the optional third-party bootstrap
- Chrome/Chromium + camera for the Barehands gesture interface

The agent remains an online-provider prototype: after bootstrap, **Barehands itself** can load its tracking/3D assets locally, but OpenAI calls still require network access.

## Install

### macOS / Linux

```bash
./setup.sh
export OPENAI_API_KEY='your-key'
.venv/bin/python scripts/bootstrap_third_party.py
.venv/bin/python -m jarvis health
.venv/bin/python scripts/dev_start.py
```

### Windows PowerShell

```powershell
.\setup.ps1
$env:OPENAI_API_KEY="your-key"
.\.venv\Scripts\python.exe scripts\bootstrap_third_party.py
.\.venv\Scripts\python.exe -m jarvis health
.\.venv\Scripts\python.exe scripts\dev_start.py
```

`setup.ps1` accepts any working Python 3.11+ interpreter. It first tries the `python` command, then falls back to the Windows `py -3` launcher; it does not require Python 3.11 specifically.

If PowerShell reports that `setup.ps1` is not digitally signed because the downloaded file is blocked, prefer removing the Internet-zone mark from that file:

```powershell
Unblock-File .\setup.ps1
.\setup.ps1
```

If your organization enforces a stricter execution policy, you can use a process-scoped bypass for the current terminal only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\setup.ps1
```

The bootstrap is one-time and networked. It pins and verifies exact upstream inputs before applying the local Barehands hardening patch. The launcher re-verifies installed executable/static trees before starting the UI components.

## Run modes

Full V1:

```bash
python scripts/dev_start.py
```

Voice-only, proving visual components are optional:

```bash
python scripts/dev_start.py --no-board --no-visualizer
```

One text turn (uses the agent but no audio playback):

```bash
python -m jarvis text "Résume ce que tu sais du projet"
```

Health report:

```bash
python -m jarvis health
```

Rebuild the derived memory index:

```bash
python -m jarvis reindex
```

Default PTT key is `F9`. Edit `config/jarvis.toml` or use the documented environment variables in `docs/OPERATIONS.md`.

## Voice architectures (v0.2 realtime path)

Beside the V1 push-to-talk loop, the repository runs a v0.2 realtime stack as
three processes: `python -m jarvis core` (the persistent daemon that owns
conversations, jobs, tools and the brain), `python -m jarvis voice` (wake word +
Realtime session) and `python -m jarvis control-center` (browser panel and the
local Claude/Codex agent).

That voice path has two architectures, chosen by `JARVIS_VOICE_ARCH`:

- `legacy` (**the default**) - one wake press, one turn, back to background as
  soon as the answer ends. The microphone closes when the provider closes the
  turn, so the speakers can never feed the next VAD segment. The realtime
  surface holds the full Core tool catalogue (calendar, reminders, Drive) and
  reaches the local agent itself through its `claude_task` tool.
- `continuous_brain` (opt-in) - one ACTIVE session spans several turns; only an
  explicit mute, the useful-inactivity timeout or an unrecoverable failure
  returns to background. The microphone stays open between turns. The surface
  keeps reflexes only - a short acknowledgement, a hearing repair, a
  hearing-scoped clarification - and receives an **empty** tool catalogue. Every
  completed user turn is submitted to a Core-owned brain, which owns truth,
  intent and work state and speaks back through typed speech requests.
  The provider never answers on its own in this mode: echo, noise and
  hallucinated transcripts are filtered first, and a contextual acknowledgement
  is spoken only when the brain is slow. The microphone goes through WebRTC echo
  cancellation (optional `livekit` dependency) and an echo guard that lets the
  user interrupt JARVIS without JARVIS interrupting himself - see
  `docs/fixes/voice-duplex/resolution-report.md`.

The model behind it: **the surface has the reflexes, the brain has the truth.**

Rollback is removing the variable. The default is computed by
`default_voice_arch()` in `jarvis/v2_config.py`, which returns `legacy` while
`CONTINUOUS_BRAIN_DEFAULT_BLOCKERS` is non-empty; nothing else decides it.

**Blocking rollout gate.** That tuple currently holds
`brain_calendar_access_unverified` and `brain_reminder_access_unverified`. In
continuous mode the surface can no longer create a calendar event or a reminder,
and the brain's own calendar/reminder access is **not verified**. Only Drive is
reachable by the brain, and only if the operator registered
`python -m jarvis drive-mcp` in the CLI agent (see `docs/OPERATIONS.md`).
Continuous mode must not become the default until that access is wired or the
gap is accepted in writing.

Continuous mode additionally requires the OpenAI Realtime stack and automatic
turn mode. Gemini Live and manual turn mode are refused loudly at startup rather
than degraded silently.

**Not verified.** No workstation acceptance (microphone, speakers, headphones,
acoustic echo, VAD retriggering, audible barge-in) and no run against the real
OpenAI Realtime service have been executed for this path. See
`docs/handoff-realtime-brain/FINAL-REPORT.md` and `docs/ACCEPTANCE_STATUS.md`.

## Security defaults

- No general shell/browser/send/delete tool exists in the V1 registry.
- Tool mutation policy is locked in code; model-provided risk flags cannot bypass it.
- `memory_append` cannot execute until the broker receives an exact confirmation for the current action id within its timeout.
- Board/visualizer URLs must be HTTP loopback addresses.
- Barehands mutations require a random per-launch token and loopback origin; the token is never placed in the browser URL.
- Barehands remote runtime assets are replaced by verified local copies; CSP blocks external connects.
- V1 push-to-talk diagnostics redact transcript/prompt/body-like fields by default (`log_content = false`).
- The v0.2 realtime runtime writes a different journal. `runtime/trace.jsonl` deliberately keeps up to 300 characters of transcripts, agent answers and spoken text so the Control Center debug console can show what was actually said; `JARVIS_LOG_CONTENT` does not gate it. Nothing leaves the machine. The latency telemetry added on top of it carries identifiers only.
- Raw agent reasoning stays inside the brain boundary, not out of the machine (Decision 43). No reasoning field exists in Core's domain state, none is persisted in conversation turns, none is carried by `brain.state.updated` or by any speech request, and none reaches the Realtime surface. The local CLI agent's own reasoning, however, *is* kept locally by design: `runtime/trace.jsonl` records its raw `stream-json` events, `thinking` blocks included, and the Control Center console renders them as `[réflexion] ...`. That is the debug console working as intended; no setting turns it off today.
- Memory path traversal and symlink escape attempts are rejected.

See `docs/SECURITY.md` for threat boundaries and residual risks.

## Verification

```bash
python -W error::ResourceWarning -m pytest -q
python scripts/verify_release.py
```

A real OpenAI test exists but is intentionally opt-in to avoid spending API calls during ordinary tests:

```bash
JARVIS_LIVE_OPENAI=1 OPENAI_API_KEY=... python -m pytest -q tests/integration/test_live_openai.py
```

## Release status

The codebase is a **release candidate**. Automated gates pass in the build environment. The final physical acceptance gates that require a networked workstation, real OpenAI credentials, microphone/speakers, Chrome and a camera are deliberately not claimed as executed here. In particular, Barehands' manual hand-gesture smoke test and real latency measurements remain workstation acceptance items.

Read `docs/FINAL_IMPLEMENTATION_REPORT.md` and `docs/ACCEPTANCE_STATUS.md` before calling the V1 fully released.

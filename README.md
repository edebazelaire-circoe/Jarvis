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

## Security defaults

- No general shell/browser/send/delete tool exists in the V1 registry.
- Tool mutation policy is locked in code; model-provided risk flags cannot bypass it.
- `memory_append` cannot execute until the broker receives an exact confirmation for the current action id within its timeout.
- Board/visualizer URLs must be HTTP loopback addresses.
- Barehands mutations require a random per-launch token and loopback origin; the token is never placed in the browser URL.
- Barehands remote runtime assets are replaced by verified local copies; CSP blocks external connects.
- Transcript/prompt/body content is redacted from logs by default (`log_content = false`).
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

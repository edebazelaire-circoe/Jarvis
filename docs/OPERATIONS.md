# Jarvis V1 operations guide

## First install

Run `setup.sh` (macOS/Linux) or `setup.ps1` (Windows PowerShell). This creates `.venv`, installs Jarvis with voice/dev extras, and copies the example configuration to `config/jarvis.toml` if absent.

Set the OpenAI key in the environment; do not place it in the tracked TOML file.

```bash
export OPENAI_API_KEY='...'
```

```powershell
$env:OPENAI_API_KEY="..."
```

## Optional UI bootstrap

On a networked workstation:

```bash
python scripts/bootstrap_third_party.py
```

This downloads exact pinned snapshots and browser assets, verifies them, hardens Barehands and writes `third_party/INSTALL-STATE.json`.

Verify at any time:

```bash
python scripts/bootstrap_third_party.py --verify
```

Use `--force` only when intentionally rebuilding the pinned installation from `LOCK.json`.

## Health

```bash
python -m jarvis health
```

Required failures:

- missing API key;
- unreadable/unwritable memory directory;
- microphone preflight failure (unless intentionally skipped).

Optional warnings:

- Barehands unavailable;
- ai-visualizer unavailable;
- third-party UI not bootstrapped.

For headless/CI checks:

```bash
python -m jarvis health --skip-audio
```

## Starting Jarvis

Full stack:

```bash
python scripts/dev_start.py
```

Voice only:

```bash
python scripts/dev_start.py --no-board --no-visualizer
```

Useful launcher options:

- `--no-open`: do not open browser tabs automatically.
- `--no-preflight`: skip microphone startup check (debug only; normal operation should keep preflight).
- `--no-board`: do not start/use Barehands.
- `--no-visualizer`: do not start/use ai-visualizer.

## PTT behavior

Default key: `F9`.

- press/hold -> listening + capture;
- release -> stop capture, transcribe, think, answer;
- press during speech -> cancel playback and immediately enter listening for a new turn.

A very short accidental press is discarded without sending an empty turn.

## Confirmation behavior

For a persistent memory write, Jarvis reads a summary of the requested content and waits. Exact accepted forms:

- approve: `oui`, `yes`
- deny: `non`, `no`

Other forms (including `ok`, `confirme`, sentences containing yes/no, or stale confirmations) do not execute the write.

## Memory

Canonical files are Markdown under configured `memory_dir`. Do not rely on `.jarvis/index.sqlite3` as data; it is a derived cache.

Rebuild:

```bash
python -m jarvis reindex
```

It is safe to delete `<memory>/.jarvis/index.sqlite3`; the next rebuild recreates search from Markdown.

## Configuration

Tracked defaults live in `config/jarvis.example.toml`; local `config/jarvis.toml` is ignored by Git.

Main environment overrides:

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | required live provider credential |
| `OPENAI_BASE_URL` | provider base URL |
| `OPENAI_TRANSCRIPTION_MODEL` | STT model |
| `OPENAI_AGENT_MODEL` | Responses agent model |
| `OPENAI_TTS_MODEL` | speech model |
| `OPENAI_TTS_VOICE` | speech voice |
| `OPENAI_TIMEOUT_S` | provider timeout |
| `JARVIS_PTT_KEY` | global PTT key name |
| `JARVIS_MEMORY_DIR` | canonical Markdown root |
| `JARVIS_RUNTIME_DIR` | transient signal/log directory |
| `JARVIS_CONFIRMATION_TIMEOUT_S` | pending write confirmation expiry |
| `JARVIS_LOG_LEVEL` | diagnostic level |
| `JARVIS_LOG_CONTENT` | opt-in raw content logging; default false |
| `JARVIS_AUDIO_SAMPLE_RATE` | microphone capture sample rate |
| `JARVIS_AUDIO_INPUT_DEVICE` | explicit input device name (exact/substring match; missing configured device fails clearly) |
| `JARVIS_BOARD_ENABLED` | enable board adapter |
| `JARVIS_BOARD_URL` | loopback board URL only |
| `JARVIS_VISUALIZER_ENABLED` | enable visualizer health/config |
| `JARVIS_VISUALIZER_URL` | loopback visualizer URL only |

`JARVIS_BOARD_TOKEN` is an internal per-launch secret normally created by `dev_start.py`; do not persist it.

## Diagnostics

Runtime logs are JSONL in the runtime directory. With default privacy settings, content fields are redacted. Useful fields include state/event names, durations and exception class.

When troubleshooting provider errors, first run health, then inspect diagnostic event names/error classes. Avoid turning on content logging unless required and remove those logs afterwards.

## Tests

Fast full suite:

```bash
python -W error::ResourceWarning -m pytest -q
```

Release verifier:

```bash
python scripts/verify_release.py
```

Opt-in real-provider transcription smoke:

```bash
JARVIS_LIVE_OPENAI=1 OPENAI_API_KEY=... python -m pytest -q tests/integration/test_live_openai.py
```

## Manual workstation acceptance

Follow `docs/ACCEPTANCE_STATUS.md`. It is intentionally explicit about checks that cannot be proven in a headless build sandbox: real microphone/speaker, real OpenAI latency, Chrome camera permissions and physical Barehands gestures.

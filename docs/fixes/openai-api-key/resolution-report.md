# Realtime voice credential loading — 2026-09-07

The project `.env` contained a nonempty `OPENAI_API_KEY`, while the launching
process had no key and no Control Center credential override existed. None of
the startup paths loaded `.env`, so Voice stopped before contacting OpenAI.

`jarvis.environment.load_project_environment()` now loads the project-root file
before CLI configuration and before either launcher starts child processes.
Existing process variables retain priority. Voice continues to prefer saved
Control Center credentials. A genuinely missing key now gives actionable setup
instructions. The supported literal, single-line format is in `docs/OPERATIONS.md`.

## Validation

- 53 targeted tests passed, covering credential parsing, UTF-8 BOM, quoted values,
  comments, environment precedence, unrelated working directories, absent/invalid
  files, CLI-to-Realtime credential propagation, masked Control Center settings,
  supervisor inheritance, legacy startup, and existing voice/settings behavior.
- Local configuration smoke: both Voice and legacy configuration detect the key.
- `python -m jarvis health --skip-audio`: `openai_credentials=ok`; the optional
  Barehands component remains unavailable (`warn`). No live OpenAI request was made.
- `git diff --check` passed.
- This Windows sandbox denies access to Python 3.14 temporary directories created
  with mode `0700`. Tests ran with a process-local `os.mkdir` wrapper using inherited
  permissions for those directories, plus a fresh workspace basetemp and disabled
  pytest cache. No application or committed test behavior was bypassed.

## Observability / test contract

The existing runtime journal remains authoritative for this repository. On a real
Voice start, expect `voice.start` in `runtime/trace.jsonl`. A missing key must still
stop startup with `OPENAI_API_KEY` in the error and instructions for `.env`, the
environment, or Control Center. Neither diagnostics nor UI responses should contain
credential values. Startup has no conversation correlation ID yet; journal events
use their existing timestamp and runtime directory. No new channels or probes were added.

`python -m observability.cli logs summary --session latest --json` could not run:
this repository/environment does not include `observability` or LogBroker. The
existing Control Center trace/error query handlers were used instead. They returned
35 historical events, including two `voice.start` events, and three historical
`audio.test.failed` errors. These historical starts are not evidence of a live run
after this fix. Full microphone/speaker and Realtime authentication validation
remains pending after restarting Jarvis.

# Jarvis V1 qualitative audit and rework log

This is the post-implementation comparison against the original handoff, not a marketing checklist. Findings below caused actual rework before packaging.

## Audit standard

The project was checked against:

- the independent-core rule;
- tasks 00-11 and their acceptance criteria;
- the threat model and failure expectations in `docs/handoff`;
- observable behavior under provider/UI/memory failure;
- least-authority boundaries;
- restart/persistence behavior;
- test quality and resource hygiene.

## Rework cycle 1 - privacy logger shape

**Finding:** diagnostic output mixed a textual prefix/timestamp with JSON, making automated parsing and downstream privacy inspection unnecessarily brittle.

**Rework:** logger emits strict one-object-per-line JSONL with timestamp and level inside the object; content redaction remains default.

**Verification:** privacy/redaction tests parse every record and check content/secrets are absent by default.

## Rework cycle 2 - provider error was not spoken

**Finding:** agent-provider failure recovered to idle but initially returned an error only as result text. The handoff explicitly requires a clear spoken/visible error.

**Rework:** orchestrator now enters `error`, publishes alert state, attempts a user-safe TTS error announcement and returns to idle even if TTS fails too.

**Verification:** agent-failure and dual agent+TTS failure tests.

## Rework cycle 3 - STT failure path was still silent

**Finding:** the previous fix covered agent failure but transcription errors occur before `handle_text`; `VoiceRuntime` could still recover silently.

**Rework:** added public runtime-error handling in the orchestrator and routed capture/STT failures through the same visible/spoken error contract. Provider internals stay in diagnostics rather than spoken text.

**Verification:** transcription-provider failure test asserts an `error` state, spoken transcription message and clean return to `idle`.

## Rework cycle 4 - PTT interruption hidden by runtime lock

**Finding:** orchestrator-level cancellation worked, but `VoiceRuntime.release()` held its lock through STT -> agent -> TTS. A new PTT press would therefore wait behind the whole response and could not actually barge in.

**Rework:** the lock now protects microphone capture ownership only and is released before the expensive pipeline.

**Verification:** runtime-level concurrency test starts a long TTS, presses PTT concurrently, observes cancellation and confirms the microphone is listening for the new turn.

## Rework cycle 5 - SQLite resource leak warnings

**Finding:** SQLite connection context managers committed transactions but did not guarantee explicit close, producing `ResourceWarning` under a strict warning gate.

**Rework:** memory adapter uses an explicit connection context manager with commit/rollback/close.

**Verification:** full suite runs with `-W error::ResourceWarning` cleanly.

## Rework cycle 6 - confirmation language was too permissive

**Finding:** accepting convenient forms such as `ok`/`confirme` weakens the handoff's exact yes/no confirmation intent and creates ambiguity for persistent writes.

**Rework:** approval is exact normalized `oui`/`yes`; denial exact `non`/`no`; everything else stays pending. The confirmation prompt previews both note title and body content so the user can understand the exact write.

**Verification:** ambiguous, stale, forged-risk, timeout, approval and denial tests.

## Rework cycle 7 - post-install executable asset integrity incomplete

**Finding:** bootstrap verified package integrity at download and critical patched files afterward, but a later local modification to vendored JS or ai-visualizer static/runtime files was not comprehensively detected.

**Rework:** deterministic tree hashes are now stored for Three.js, MediaPipe and ai-visualizer runtime files. Launcher performs `--verify` before UI launch. Generated `ai-visualizer.json` is the only excluded runtime config file.

**Verification:** tree-hash tamper tests and release verifier; actual downloaded trees require workstation bootstrap.

## Rework cycle 8 - board token least privilege

**Finding:** a shared process environment would also expose the board token to ai-visualizer even though it has no reason to mutate the board.

**Rework:** launcher builds per-process environments; visualizer explicitly receives no `JARVIS_BOARD_TOKEN`.

## Rework cycle 9 - expected startup errors were too technical

**Finding:** missing API key could surface as a raw exception and microphone preflight errors needed a clear CLI path.

**Rework:** missing key is a typed `ConfigurationError`; CLI catches expected `JarvisError` and exits with a concise message/code 2. Health reports required vs optional failures separately.

**Verification:** command-line smoke without API key and health smoke were executed.

## Rework cycle 10 - stateless reasoning tool-loop replay

**Finding:** `store:false` is a strong privacy default, but Responses reasoning models need their encrypted reasoning item replayed during a stateless function-call continuation.

**Rework:** agent requests `reasoning.encrypted_content` and keeps replay mechanics private to the OpenAI adapter.

**Verification:** provider contract test asserts the `include` field and a complete function-call-output continuation.

## Rework cycle 11 - configured microphone silently degrading

**Finding:** an explicitly named microphone that disappeared could fall back to the OS default, making Jarvis listen through a device the user did not select.

**Rework:** an explicit device name is resolved by exact/substring match and fails clearly when absent; only an unspecified device uses the system default.

**Verification:** configured-missing-device regression test.

## Rework cycle 12 - remote cleartext provider endpoint

**Finding:** a configurable `OPENAI_BASE_URL` could have been pointed at remote plain HTTP, exposing the API credential in transit.

**Rework:** remote provider URLs require HTTPS; HTTP remains allowed only for loopback test/local proxies.

**Verification:** configuration tests cover remote HTTP rejection and loopback HTTP acceptance.

## Rework cycle 13 - Markdown/index truth divergence

**Finding:** an existing SQLite cache could be stale after direct Markdown edits, and a corrupt cache could block startup despite Markdown being canonical.

**Rework:** memory resynchronizes the derived index from Markdown at startup and discards/rebuilds a corrupt derived database.

**Verification:** external-edit restart and corrupt-index recovery tests.

## Rework cycle 14 - provider key inherited by optional UI children

**Finding:** sanitizing the browser/token path was not enough if optional third-party child processes inherited `OPENAI_API_KEY` from the launcher environment.

**Rework:** per-process environments apply least privilege: Jarvis receives provider key + board token, Barehands receives only board token, ai-visualizer receives neither; bootstrap verification receives neither.

**Verification:** launcher environment regression test.

## Rework cycle 15 - launcher configuration drift

**Finding:** the first launcher version implicitly enabled UIs and used default paths/ports even when `jarvis.toml` selected a different mode or location.

**Rework:** launcher loads the same `AppConfig`, respects enabled flags/`--no-*`, custom config path, runtime/memory paths and URL ports. Existing Barehands config is resynchronized for Jarvis-owned port/Memory orb while preserving other settings/orbs.

**Verification:** generated-config, stale-config resync and invalid-config fail-closed tests.

## Rework cycle 16 - voice-only health false warning

**Finding:** health warned about a missing third-party installation even when both optional UIs were intentionally disabled.

**Rework:** third-party status becomes `disabled` in voice-only mode, not a warning.

**Verification:** voice-only health regression test.

## Rework cycle 17 - malformed provider function-call boundary

**Finding:** a malformed Responses function call with no usable name/call id could enter local orchestration and produce a continuation that could not be safely correlated.

**Rework:** the provider adapter rejects malformed function-call records before the broker/tool layer.

**Verification:** missing-id and missing-name provider tests.

## Rework cycle 18 - CLI default command namespace

**Finding:** `python -m jarvis` correctly intended to default to health, but the parser namespace lacked the subcommand-only `skip_audio` attribute and could raise `AttributeError`.

**Rework:** default-health dispatch reads that optional flag safely.

**Verification:** no-subcommand and explicit `--skip-audio` CLI dispatch tests.

## Rework cycle 19 - durable write / derived-index partial failure

**Finding:** after an atomic Markdown write succeeded, an index update followed by an index rebuild failure could still bubble an error to the broker. The user would hear “failed” even though canonical data had actually persisted.

**Rework:** once canonical Markdown commits, derived-index repair is best-effort. Index failure cannot falsify the outcome of the durable write; a later process start resynchronizes it from Markdown.

**Verification:** regression test forces both upsert and rebuild failures and asserts the Markdown write is still returned as successful/canonical.

## Audit outcome

### Strong alignment

- independent modular core rather than `fullstack-agent` fork;
- exactly constrained tool surface;
- persistent-write confirmation broker;
- Markdown canonical memory with rebuildable index;
- provider-neutral state/audio/agent/TTS contracts;
- actual runtime-level PTT interruption;
- optional UI degradation;
- pinned/hardened third-party bootstrap with no Barehands runtime CDN requirement;
- privacy-safe logging defaults;
- original handoff preserved verbatim under `docs/handoff-source/`, with a separate annotated working copy under `docs/handoff/`.

### Deliberately not overclaimed

The headless sandbox cannot prove physical camera gestures, real microphone/speaker operation, downloaded third-party runtime execution, live OpenAI behavior or real latency. These are explicitly carried as manual release gates rather than being marked green from mocks.

That distinction is the principal remaining difference between a high-quality **release candidate** and a physically accepted V1.

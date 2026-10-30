# Shard 09 async conversation failures: provisional pretriage

Observed naturally while the root gate runs at
`97d56f1144cb721e7c5303f43ff71d291ed1d9bc`:

- `tests/integration/test_v2_async_conversation.py::test_jarvis_mute_leaves_the_work_in_core_and_speaks_nothing_stale[0]`
- Same node, parameters `[1]` and `[2]`.
- The same module's
  `test_ambient_noise_during_live_does_not_keep_the_session_alive` also shows
  FAILED in the running log.

The shard is not complete and its failure trace is not yet available. No cause
or baseline classification is assigned from these progress lines. No test,
server, browser, model or hardware was launched during this pretriage. Root
HEAD and all product files remain unchanged.

## Reachable composition and resource assessment

The integration test imports `tests/integration/async_conversation_harness.py`,
which reexports the actual harness in `jarvis/testlab/virtual/harness.py`.
Despite the old module summary's shorthand "no network", this is **not a pure
in-memory mock test**: the harness constructs a real `JarvisCoreApplication`,
SQLite data rooted at pytest `tmp_path`, a real `LocalProtocolServer` on
`127.0.0.1`/OS-selected free port, an explicit `LocalCoreClient` and actual
HTTP/WebSocket event flows. It runs in one Python process, without Chrome or a
Jarvis subprocess.

External boundaries are controlled:

- Strong model: `ScriptedBrainBackend`, a queue/event-driven backend, injected
  explicitly into Core. No provider/model request or CLI inference is selected.
- Realtime provider: `FakeRealtimeSession` by default. These tests do not pass
  the optional live `realtime_factory`.
- Audio: `SoundDeviceRealtimeAudio` is patched to `FakeAudio`. Its overridden
  `start()` enqueues controlled PCM rather than opening PortAudio input; output
  is `ImmediateOutputStream`/`BufferedOutputStream`, with production accounting
  over an in-memory controlled native boundary. No microphone or speaker is used.
- Wake: a queue-driven fake. No live wake-word engine.
- Data/ports: explicit temporary data root and isolated loopback server/client,
  not the daily runtime's URL/database.

Liveness boundaries found in source:

- Condition waits are bounded by `TIMEOUT_S = 30.0` (an earlier documented
  adjustment for host load), including websocket/subscription settlement.
- `FastShutdownRunner` sets aiohttp shutdown timeout to 0.05 s.
- Context `finally` cancels/gathers only its owned runtime task, releases all
  scripted brain handles, closes recorder and client, then stops its own server
  and Core. The module contains no subprocess/taskkill cleanup.
- A later baseline allocation should begin with one exact replay, not the whole
  module. Multiple waits/teardown can accumulate time; an outer owned-process
  deadline is appropriate if PM authorizes execution. Do not launch it beside
  the memory-constrained gate without a separate bounded permission.

## Baseline source comparison

Byte-identical between `c0858a80` and root HEAD:

| Source | SHA-256 at both revisions |
| --- | --- |
| integration test module | `6e6aab2fd429098a3c80b25aa7d0bcd56766c75b7623c7945907fd7359f29954` |
| harness reexport | `828422af012a4d9c1f1dcbca29cd0ea3d637fa01bca34d229c09d6bcec882171` |
| actual virtual harness | `5681e179e362cfb663b0e8cfacad013908f5992fa6da11cea68d1178449ead64` |
| voice_v2.py | `561d1f62975b2fc7a2fcbc9faeaf9bae8c36eccf1b6a3e881056a8a36ce0e8d0` |
| realtime_audio.py | `5adc42fa5f878a14ac8303b47568c40a42809fa4a4517826ea59ee9eb37228bb` |
| speech_scheduler.py | `144ba0c756ad1fe826c91c9cf62507859dffdd770a859e04ae37c5e4ca0f5d4a` |
| completion_watch.py | `8dfc0443b51f5ab148a5b2fdf8db08dd8ece1c6f1ce5a0c61ec4983b914881c1` |
| brain_service.py | `1016c0aaa008372aad1a57eac20ed7bfce286289e057899f8490179e0f101c09` |
| protocol/server.py | `beb019088592320d183adb91296ae65f2367ae2abf7a5605439d48ee8dce7a24` |

Also byte-identical: `core/v2_app.py`, `protocol/client.py`, virtual devices and
`domain/v2.py`. This feature does change the scene domain/backend layout command
and frontend code; source stability of the listed path is useful evidence but
is not substituted for an exact-baseline outcome. No product correction or
ignore is proposed without that evidence.

## Scenario/trace discriminator, still pending

Mute replays start one scripted brain work item, queue speech while fake output
is active, inject "Jarvis mute", and wait for complete background state. Only
then do they assert expired speech, retained Core work, result publication and a
clean new activation. The ambient case also waits for complete background after
a FakeClock-driven idle timeout. Shared `wait_background()` has two separate
bounded conditions: Voice state and event subscriber settlement. These locations
are candidates to inspect **after** the final traceback; no failed line,
subscriber count, internal cause or acoustic behavior has been measured here.

## Proposed exact baseline command; not executed

After final trace review and explicit PM resource allocation, start with replay
`[0]` only, preserving stdout/JUnit and the baseline revision:

```powershell
Set-Location C:/Projects/jarvis/movb
git rev-parse HEAD
$env:PYTHONDONTWRITEBYTECODE='1'
& C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe -m pytest --assert=plain --tb=short -p no:cacheprovider -q 'tests/integration/test_v2_async_conversation.py::test_jarvis_mute_leaves_the_work_in_core_and_speaks_nothing_stale[0]' --junitxml=C:/Projects/jarvis/mov5/tasks/jarvis-mouse-organization-viewer/slices/06-final-integration-e2e-qa/qa/async-conversation-baseline-replay0.xml
```

Baseline worktree is already detached at
`c0858a8000e2ca23b57231edb8f46c643080ad07`. If this passes, stop and report;
do not widen to all replays/module. If it fails, compare the exact traceback and
phase before requesting any further bounded replay. Other naturally observed
failures retain their own pending classifications. PM owns disposition.

## Later bounded baseline allocation: four actual outcomes retained

PM subsequently authorized exactly the three mute replays and the single
ambient-noise case together after checking the resource budget. This superseded
the proposed replay-zero-only command above. No other test/file was run.

Cwd was `C:/Projects/jarvis/movb`; HEAD was verified as
`c0858a8000e2ca23b57231edb8f46c643080ad07`. Main checkout interpreter,
`PYTHONDONTWRITEBYTECODE=1`, `--assert=plain --tb=short -p no:cacheprovider -q`:

```powershell
& C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe -m pytest --assert=plain --tb=short -p no:cacheprovider -q tests/integration/test_v2_async_conversation.py::test_jarvis_mute_leaves_the_work_in_core_and_speaks_nothing_stale tests/integration/test_v2_async_conversation.py::test_ambient_noise_during_live_does_not_keep_the_session_alive --junitxml=C:/Projects/jarvis/mov5/tasks/jarvis-mouse-organization-viewer/slices/06-final-integration-e2e-qa/qa/baseline-shard-09-async-conversation.xml
```

Result: **4 failed in 140.21 s**, exit 1. Evidence:
[stdout](baseline-shard-09-async-conversation.log),
[JUnit](baseline-shard-09-async-conversation.xml).

| Baseline node | Actual traceback |
| --- | --- |
| mute `[0]` | test line 344 → virtual harness wait_background line 796 → wait_until line 132 |
| mute `[1]` | same lines/condition |
| mute `[2]` | same lines/condition |
| ambient noise | test line 447 → virtual harness wait_background line 796 → wait_until line 132 |

Every failure is
`AssertionError: condition never reached: the /v1/events subscription is closed`.
The helper's preceding Voice-background predicate completed before this second
wait. **No actual subscriber count was recorded**, and this does not establish
that a websocket leaked or identify an internal cause; only the existing
subscription-settlement predicate's timeout is proven.

The pytest process completed, including the harness's owned fixture teardown.
No manual or broad process cleanup, hardware, provider, Chrome, model call or
daily runtime interaction occurred. Product files and root HEAD remain frozen.

These four exact baseline failures are established. The root shard was still
in progress when this evidence was captured; its final trace must match these
phases/conditions before classifying the four gate outcomes as unrelated. Do
not substitute the source hypothesis for that comparison or mark the red
canonical verdict green. No additional execution is proposed without PM request.

## Final root trace comparison and PM disposition

The completed root shard-09 JSON/log were subsequently read. Canonical totals:
**979 passed, 4 failed, 5 skipped**, 988 collected, exit 1, green false,
502.5 seconds, no session problems. Its four unknown nodes are exactly the
three mute replays and ambient-noise case above.

All four root tracebacks match the baseline failures: mute test line 344 or
ambient line 447 → virtual harness line 796 → helper line 132, with the exact
`condition never reached: the /v1/events subscription is closed` message.

PM accepted all four observed outcomes as **proven pre-existing and unrelated**
after this comparison. No actual subscriber values or more specific internal
root cause are claimed. The original canonical shard stays truthfully red;
no global ignore, product change, root commit, additional runtime or broader
test execution was introduced by this QA work. Remaining browser unknowns keep
their separate pending dispositions.

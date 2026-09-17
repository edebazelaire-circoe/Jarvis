# Category 2 Test Lab (contract, schema version 1)

Native Jarvis subsystem for targeted diagnosis after an observed failure. It
measures, executes, scores, compares and stores; it contains no intelligence.
Humans, Jarvis and external agents reason over its records. It is not part of
normal CI.

- Implementation (Level 3, pure domain: no I/O, no implicit clock, no
  provider/transport import), package `jarvis/testlab/`:
  - `validation.py`: errors, JSON/text/time guards, redaction and forbidden-code guards, fingerprint;
  - `identity.py`: schema names and version, diagnostic id/version, run/sweep/bundle ids;
  - `profiles.py`: `ProfileName`, `Capability`, `CostBounds`, `ProfileSpec`, `ResourceGrant`, `check_profile_permission`;
  - `diagnostics.py`: `ParameterSpec`, `MetricSpec`, `AssertionSpec`, `ScoreContract`, `DiagnosticSpec`;
  - `scenarios.py`: `Scenario`, `ScenarioStep`;
  - `runs.py`: `TestRun`, `RunStatus` state machine, `ArtifactRef`, `CodeIdentity`, `RunFailure`;
  - `store.py` (Slice 02): `TestRunStore` port, `RunQuery`/`RunPage`, usage types, `ArtifactWriteLimits`, store errors, `check_run_update`;
  - `retention.py` (Slice 02): `TestLabRetentionPolicy`, `plan_retention`, `apply_retention_plan`.
- I/O modules (Slice 02, see Storage):
  - `filesystem_store.py`: `FilesystemTestRunStore`, the local durable adapter;
  - `capture.py`: `read_git_revision`, `capture_code_identity`, `capture_environment`, `build_config_snapshot`, `store_config_snapshot`.
- Conformance tests: `tests/unit/test_testlab_identity.py`,
  `tests/unit/test_testlab_profiles.py`, `tests/unit/test_testlab_diagnostics.py`,
  `tests/unit/test_testlab_scenarios.py`, `tests/unit/test_testlab_runs.py`,
  `tests/unit/test_testlab_purity.py`, `tests/unit/test_testlab_store.py`,
  `tests/unit/test_testlab_store_retention.py`, `tests/unit/test_testlab_store_capture.py`;
  shared builders `tests/fakes/testlab.py`.
- Handoff: `tasks/jarvis-category2-test-lab/` (Slices 01, 02).

Status 2026-09-17: contracts (Slice 01) and run persistence (Slice 02). Nothing
composes the store yet (no default root wiring, no scheduled retention or
temporaries sweep). DiagnosticBundle (03), catalog, manifests and primitive
vocabulary (04), supervisor/worker (05), profile runners (06, 08, 09), score
computation and sweeps (07), API/CLI/HTTP (10) and UI (11) do not exist yet.

## Invariants

- Constructing any contract object validates it: an invalid spec, scenario or
  run never exists in memory. `dataclasses.replace` re-validates.
- Strict codecs: every document has `schema` + `schema_version`; every object
  has exactly its fields. Unknown or missing fields are rejected, never ignored.
- Maps are read-only after construction (`MappingProxyType`, lists become tuples).
- Times are supplied values: UTC, millisecond precision, wire form
  `YYYY-MM-DDTHH:MM:SS.mmmZ` (the Conversation Events time, normalize with
  `to_event_time`).
- No field or map name that designates hidden reasoning, a prompt, instructions,
  a secret or raw audio is accepted: fixed fields carry no such content, open names
  are denied by default unless they end in a metadata word (Name rule), and raw
  bytes are refused everywhere. A value stored under an innocuous name cannot be
  inspected; capturers must not collect such content (Slices 02, 03, 05).
- No code is executable from data (Forbidden code).
- Error messages name fields and rules, never values.

## Identity

| Item | Rule |
|---|---|
| `TESTLAB_SCHEMA_VERSION` | `1`, shared by all Test Lab documents. |
| Document names | `jarvis.testlab.diagnostic`, `jarvis.testlab.scenario`, `jarvis.testlab.run`. |
| Diagnostic id | `<domain>.<name>`, dotted lowercase snake_case segments, ≥ 2 segments, ≤ 64 chars (`voice.self_echo`, `speech.payload_integrity`). The first segment is the diagnostic `domain`. |
| Diagnostic version | Integer 1..2³¹−1. Bump it for any change of parameters, metrics, assertions, thresholds or meaning. Runs compare only within one `(diagnostic_id, version)`. |
| Run id | `tlr-YYYYMMDDTHHMMSSmmmZ-<16 lowercase hex>` from `format_run_id(created_at, nonce)`. |
| Sweep id / bundle id | Same form with `tls-` / `tlb-` (`format_sweep_id`, `format_bundle_id`). |
| Fingerprint | `content_fingerprint(value)`: 64 lowercase hex sha256 of canonical JSON (sorted keys, compact, UTF-8, no NaN), same encoding as `prompt_registry.fingerprint`. |

The id time is the creation time; ids therefore sort chronologically. The
nonce is supplied by the caller: `secrets.token_hex(8)` for a fresh run, or a
content-fingerprint prefix when an id must be idempotent (e.g. re-importing the
same session as a bundle). Pure code never generates it.

Why an integer version: every schema version in Jarvis is an integer
(Conversation Events, `jarvis.voice_replay`, benchmark suites), and the Test Lab
has no compatibility tiers that would give semver's minor/patch a meaning.

`id_timestamp(created_at)` is the single formatter of the id time segment
(`TestRun` checks `created_at` with it).

`decode_json_document(text)` is the strict JSON reader for Test Lab files:
size bound (256 KiB default); duplicate keys, `NaN`, `Infinity`, numbers that
overflow to infinity (`1e400`) and integers beyond the interpreter digit limit
fail with `testlab_json_invalid`; nesting too deep to decode fails with
`testlab_limit_exceeded`.

## Profiles and permissions

| Profile | Meaning | Required by the name |
|---|---|---|
| `virtual` | In-memory production path with controlled doubles | no capability, `max_cost_usd` = 0 |
| `audio` | Real audio chain, no physical acoustics | no provider, no `human_presence` |
| `live` | Real provider session(s) | ≥ 1 provider capability, no `human_presence` |
| `hardware:auto` | Real workstation devices, no human action | ≥ 1 audio device, no `human_presence` |
| `hardware:guided` | Real devices, the human is a scenario actor | ≥ 1 audio device and `human_presence` |

Capabilities (closed): `realtime_provider`, `llm_provider`, `audio_input_device`,
`audio_output_device`, `human_presence`.

`ProfileSpec {name, implementation, requires, cost}`: `implementation` is a
registered dotted name resolved by the catalog, never code; `requires` is a set
(wire: sorted list, no repeats); `cost` is `CostBounds {max_duration_s (0 < d ≤
86400), max_cost_usd (0..1000)}`, the declared upper bounds of one run.

`ResourceGrant {capabilities, max_cost_usd = 0, max_duration_s = null}` is what
a caller authorizes; the default grant allows only free, capability-less work
(`null` duration means no duration budget).

`check_profile_permission(profile, grant) -> PermissionDecision {profile,
allowed, denials}` returns every denial at once, in this order: missing
capabilities (vocabulary order, `capability_missing`), then
`cost_budget_exceeded`, then `duration_budget_exceeded` (each with `required`
and `granted`). It compares declarations only: checking that a device or
provider is really available, and not held by the running voice process, is the
runner's job (Slices 05, 08, 09).

## Diagnostics

`DiagnosticSpec` wire fields: `schema`, `schema_version`, `diagnostic_id`,
`version`, `title` (≤ 120), `domain`, `description` (≤ 512 or null),
`profiles` (list in vocabulary order; in memory a read-only map
`ProfileName -> ProfileSpec`), `parameters`, `metrics`, `assertions`, `score`.

Cross-references validated at construction: domain equals the id's first
segment; ≥ 1 profile, no duplicate; ≥ 1 metric, names unique; assertion ids
unique and ≥ 1 blocking assertion; each assertion references a declared metric
with a fitting threshold; each score component references a declared numeric
metric, with `best`/`worst` consistent with the metric direction.
`spec.fingerprint()` is a **semantic** fingerprint: it covers schema, id,
version, domain, profiles, parameters, metrics, assertions and score contract,
and excludes cosmetic wording (`title` and every `description`, including those
of parameters, metrics and assertions). A semantic edit under an unchanged version
changes it; a wording edit does not, so stored runs stay conforming.

### Parameters

`ParameterSpec {name, type, default, minimum, maximum, choices, max_length,
description}`, `type` in `bool`, `int`, `float`, `str`, `enum`:

- name: dotted lowercase ≤ 96, never a private or code-carrying key;
- `minimum`/`maximum` only for `int`/`float` (integers for `int`);
- `choices` (1..32 distinct) only and always for `enum`; choices are values, not
  names: each passes the value code heuristic only (`("idle", "thinking",
  "speaking")` and `("text", "audio")` are valid);
- `max_length` (1..1024) only for `str` (default bound 512);
- `default` must satisfy the spec.

`resolve_parameters(specs, supplied)` returns the effective read-only map of
every declared parameter (supplied value or default), sorted by name. Unknown
keys, wrong types (`bool` is never a number, `2.0` is not an `int`), out-of-bound
values and non-finite numbers fail with `testlab_parameter_invalid`; an `int` for
a `float` is normalized to float. String values that look like code fail with
`testlab_forbidden_code`. `ParameterSpec` may also describe an overridable
setting for run-local overrides (Slices 05, 07).

### Metrics, assertions and score

`MetricSpec {name, unit, direction, description}`. Units (closed): `ms`, `s`,
`count` (integer ≥ 0), `ratio` (0..1), `percent` (0..100), `boolean`, `db`,
`hz`, `usd`, `chars` (integer ≥ 0). Directions: `higher_better`,
`lower_better`, `neutral`. `check_metric_value` enforces the unit.

`AssertionSpec {assertion_id, metric, comparator, threshold, blocking,
description}`: `metric <comparator> threshold` with comparators `lt`, `le`,
`gt`, `ge`, `eq`, `ne`. A boolean metric takes a boolean threshold with `eq`/`ne`
only. A numeric threshold must itself be a valid value of the unit (`count` and
`chars` integral and ≥ 0, `ratio` in 0..1, `percent` in 0..100), failing with
`testlab_reference_invalid`. `eq` and `ne` compare exactly and are accepted only
for the exact units `count`, `chars` and `boolean`: measured durations, ratios and
levels are floats where exact equality is noise (`0.1 + 0.2 != 0.3`); express
those with `lt`/`le`/`gt`/`ge`.

`evaluate_assertion(assertion, metric, value)` returns `AssertionResult
{assertion_id, outcome, blocking, observed}`; `value` None gives outcome
`missing` (never a pass). `assertions_verdict(results)`:

| Blocking results | Verdict |
|---|---|
| any `failed` | `failed` |
| none failed, any `missing`, or no blocking result | `inconclusive` |
| all `passed` | `passed` |

Non-blocking outcomes and the score never change the verdict.

`ScoreContract {method, components}`: `none` (no component, run score null) or
`weighted_mean` (1..16 components `{metric, weight (0 < w ≤ 1000), best,
worst}`, distinct metrics). Binding formula for Slice 07: each component maps
the metric linearly from `worst` (0) to `best` (100), clamped to 0..100; the
score is the weight-weighted mean. The score is a UI synthesis, never a verdict.

## Scenarios

`Scenario {schema, schema_version, scenario_id, title, description, steps}`:
`scenario_id` dotted lowercase ≤ 64; title ≤ 120, description ≤ 512 (or null);
1..256 steps; ≤ 64 KiB canonical JSON (the `jarvis.voice_replay` fixture bound).

`ScenarioStep {primitive, args}`: `primitive` is a dotted lowercase name
registered by the catalog (vocabulary owned by Slice 04). `Scenario.from_dict(payload,
*, primitives)` requires `primitives`: the registered names (an unregistered step
fails with `testlab_reference_invalid`), or the explicit sentinel `SHAPE_ONLY` to
check shape and safety only (fixture tooling, catalog lint). There is no permissive
default; a scenario that will execute is decoded against the registry
(`check_scenario_primitives` does the same on a constructed scenario). `args` is a JSON object: snake_case keys
at every depth, nesting ≤ 6, ≤ 64 keys per object, ≤ 64 list items, strings ≤ 512,
integers within ±2⁵³, finite numbers, ≤ 4 KiB encoded. `scenario.fingerprint()`
identifies exactly what executed (order matters).

## TestRun

Wire fields (all always present, null when absent):

| Field | Rule |
|---|---|
| `schema`, `schema_version` | `jarvis.testlab.run`, `1` |
| `run_id` | Run id; its embedded time equals `created_at` |
| `diagnostic_id`, `diagnostic_version` | Identity of the diagnostic run |
| `profile` | `ProfileName` |
| `status` | See Run state machine |
| `created_at`, `started_at`, `finished_at` | Supplied UTC ms times, `created ≤ started ≤ finished` |
| `code` | `{git_revision (40 or 64 lowercase hex), dirty}` |
| `config_fingerprint` | Fingerprint of the effective configuration snapshot |
| `diagnostic_fingerprint` | `DiagnosticSpec.fingerprint()` of the declaration the run was judged by |
| `parameters` | Effective diagnostic parameters (≤ 32, JSON scalars) |
| `overrides` | Run-local setting overrides, dotted setting path → JSON scalar (≤ 64). Never written to permanent settings. |
| `environment` | Execution environment facts, dotted name → non-null JSON scalar (≤ 32 entries, strings ≤ 1024), e.g. `os`, `os_version`, `python_version`, `host.cpu_count`. Names pass the private-name and code-name rules; values pass the value heuristic. |
| `assertion_results` | `AssertionResult` list, unique ids |
| `metrics` | Metric name → boolean or finite number (≤ 64) |
| `score` | 0..100 or null |
| `artifacts` | `ArtifactRef {kind, path, media_type, sha256, size_bytes}`, unique paths |
| `failure` | `{code (snake_case), detail (≤ 512, secret-free)}` or null |
| `bundle_id`, `sweep_id`, `parent_run_id` | Optional ids (`parent_run_id` ≠ `run_id`) |
| `scenario_id`, `scenario_fingerprint` | Both or neither |
| `join_ids` | Conversation Events trace join values: keys among `conversation_id`, `session_id`, `turn_id`, `correlation_id`, `task_id`, `work_id`, `speech_id`, `outcome_id` (`TRACE_JOIN_FIELDS`), opaque ids |

Artifact kinds: `config_snapshot`, `scenario`, `event_log`, `trace_excerpt`,
`worker_log`, `metrics`, `report`, `audio_clip` (bounded, opt-in). An artifact
path is a relative POSIX path inside the run directory: ≤ 200 chars, ≤ 8
segments of `[A-Za-z0-9][A-Za-z0-9._-]*` not ending with `.`; no absolute path,
drive, backslash, `..` or hidden segment. The record holds references, never bytes.

Record invariants: `assertion_results`, `metrics` and `score` exist only on a
terminal run; `passed` requires verdict `passed`, `failed` requires verdict
`failed`, both with null `failure`; `errored` and `timed_out` require a
`failure`; `cancelled` may carry one. `check_run_against_spec(run, spec)` adds the
cross-check with the diagnostic: identity and `diagnostic_fingerprint`, supported
profile, exactly the declared parameters with valid values, declared metrics with
fitting values, declared assertions with the same `blocking` flag, a result for
every assertion on `passed`/`failed`, and **every recorded result re-derived** with
`evaluate_assertion(assertion, metric, run.metrics.get(metric))`: outcome and
observed value must be identical (a boolean never stands in for a number). A run
recording `passed` with `observed=3` against `eq 0`, an observed value that differs
from `metrics`, or results with no metrics is rejected (`testlab_reference_invalid`).

Why `environment` keys are pattern-checked, not a closed set: facts come from
different runners (worker, audio devices, hardware) added by later Slices, and a
closed vocabulary would force a contract change for every probe. The name rules
and bounds only refuse names that designate private data and code-looking values;
they cannot judge what an innocuous name holds. User-identifying facts (home path,
host name, user name, account or network identifiers) must not be captured; which
probes are recorded is decided by the capturers of Slices 02 and 05. Run
comparability is carried by the diagnostic identity and fingerprints, not by
environment names.

## Run state machine

```text
queued ──> running ──> passed | failed | errored | cancelled | timed_out
   └────> cancelled | errored   (worker never started)
```

Terminal states have no exit. `can_transition` / `check_transition`
(`RunTransitionError`, `testlab_transition_illegal`) implement the table.
`transition_run(run, target, at=, failure=)` sets `started_at` on `running` (a
`failure` there is an error, never silently dropped) and `finished_at` on terminal
targets; it refuses `passed` and `failed`, which only
`complete_run(run, at=, assertion_results=, metrics=, score=, artifacts=)`
derives from the verdict: `passed` → `passed`, `failed` → `failed`,
`inconclusive` → `errored` with failure code `assertions_inconclusive`.

## Redaction and forbidden code

These guards protect names and values; they are **not the security boundary**.
The boundary is structural: scenario steps name registered primitives, every
argument is plain JSON data, nothing in a Test Lab document is ever evaluated, and
runners never collect private values.

### Name rule

A name is split into words: camelCase, `.`, `-`, `:`, space and `_` all separate
words.

1. **Secrets, anywhere.** A secret word anywhere makes the name private:
   `password`, `passwd`, `passphrase`, `secret(s)`, `credential(s)`,
   `authorization`, `cookie(s)`, `apikey`, `bearer`, `jwt`, `otp`; so do the
   compounds `api_key`, `access_token`, `refresh_token`, `id_token`,
   `private_key`, `access_key`, `secret_key`, `signing_key`, `ssh_key`,
   `auth_header`, `encrypted_content`. `key` as the final word is a secret
   (`openai_key`, `porcupine_access_key`, bare `key`) unless the word before it is
   a closed keyboard, wake-word or data-structure qualifier (`wake`, `hot`,
   `shortcut`, `keyboard`, `push`, `talk`, `press`, `hold`, `toggle`, `mute`,
   `trigger`, `sort`, `primary`, `foreign`, `cache`, `dedupe`, `idempotency`,
   `partition`, `lookup`, `join`, `group`, `index`, `composite`, `row`, `map`,
   `dict`).
2. **Private content, deny by default.** The compounds `chain_of_thought`,
   `system_prompt`, `raw_arguments` and `tool_input` are private anywhere,
   whatever follows. A content word (`reasoning`, `thinking`, `thought(s)`,
   `scratchpad`, `cot`, `chainofthought`, `prompt(s)`, `systemprompt`,
   `instruction(s)`, `signature`, `token`, `audio`, `pcm`, `pcm16`, `wav`)
   anywhere makes the name private **unless** its final word is in the closed
   metadata vocabulary: `id(s)`, `ref(s)`, `hash`, `fingerprint`, `version`,
   `variant(s)`, `kind`, `type`, `format`, `mode`, `code`, `name`, `tokens`,
   `count(s)`, `chars`, `length`, `size`, `budget`, `limit`, `max`, `min`, `ms`,
   `s`, `seconds`, `duration`, `latency`, `timeout`, `threshold`, `rate`, `ratio`,
   `percent`, `level`, `gain`, `db`, `hz`, `channels`, `bits`, `effort`,
   `enabled`, `disabled`, `filler`, `pause`, `device(s)`, `index`, `status`,
   `state`, `lang`, `language`.
   `transcript` and `messages` are not content words: user-visible conversation
   text is public (Conversation Events `content`), and virtual scenarios inject
   simulated transcripts.
3. **Code.** A code word (`code`, `shell`, `import(s)`, `eval`, `exec`,
   `script(s)`, `module(s)`, `command(s)`, `cmd`, `cmdline`, `python`, `lambda`,
   `callable`, `subprocess`, `popen`, `function`, `bash`, `powershell`, `pwsh`)
   names code when it is the final word, or when the final word is a code carrier
   (`text`, `content`, `source`, `src`, `body`, `expr`, `expression`, `line(s)`,
   `string`, `snippet`, `args`, `argv`). `code` after a qualifier is a
   classification code (`status_code`) unless the qualifier is a code word or code
   carrier (`python_code`, `source_code`). A name starting or ending with `_`
   (dunders) is a code name.

Every name `conversation_events.is_forbidden_key` rejects is also private here,
except four deliberately allowed words, each with a regression test: `input`
(audio input devices, scenario inputs; `tool_input` stays private), `bytes` (a
byte size; raw bytes are refused by type), `arguments` and `args` (plain scenario
arguments; `raw_arguments` stays private).

The word sets are the closed vocabulary of the rule (constants in
`jarvis/testlab/validation.py`). Private names are refused at any depth of every
decoded document (`TestLabRedactionError`, `testlab_forbidden_private_data`), and
by metric, parameter, override, environment and scenario-arg names. Code names are
refused in scenarios and in parameter, override, environment and scenario-arg names
(`ForbiddenCodeError`, `testlab_forbidden_code`). Raw bytes are refused everywhere.

| Accepted | Rejected |
|---|---|
| `reason_code`, `status_code`, `error_code`, `language_code` | `code`, `python_code`, `source_code` |
| `reasoning_tokens`, `llm.prompt_tokens`, `token_budget`, `max_token_count`, `max_tokens` | `reasoning`, `brain.reasoning`, `thinking`, `prompt`, `auth_token`, `reasoning_trace`, `reasoning.items`, `hidden_reasoning_json`, `thinking_log` |
| `prompt_id`, `brain.prompt_id`, `prompt_variant`, `brain.reasoning_effort` | `thinking_text`, `prompt_text`, `prompt_template`, `prompt_messages`, `reasoning.summary` |
| `speech.thinking_filler`, `reflex.thinking_pause_ms` | `chain_of_thought`, `chain_of_thought_steps`, `cot_steps`, `system_prompt`, `system_prompt_v2`, `hiddenThinking` |
| `wav_gain_db`, `pcm.frame_ms`, `provider_first_pcm_ms`, `audio.output_latency_ms`, `audio_ref`, `size_bytes` | `raw_audio`, `audio_bytes`, `pcm_frames`, `input.wav`, `input_audio_buffer`, `instructions`, `session.instructions` |
| `module_id`, `voice.command_timeout_ms`, `tool.function_name` | `agent_cli_settings.claude.command`, `command_line`, `tool.function_args` |
| `agent_routing.profiles.code.model`, `python_version` | `api_key`, `openai_api_key`, `credentials`, `password`, `secret`, `cookie` |
| `manual_wake_key`, `shortcut_key`, `sort_key` | `porcupine_access_key`, `openai_key`, `signing_key`, `ssh_key`, `bearer`, `auth_header`, `authHeader`, `passphrase`, `jwt`, `encrypted_content` |
| | `__class__`, `_hidden`, `on_start_script`, `shellCommand` |

### Value heuristic

`looks_like_code` is a defense-in-depth **heuristic** on string values of
scenarios, parameters, enum choices, overrides and environment. It matches only
forms with no plausible natural-language reading (case-sensitive, like Python):

- a dunder call or dunder attribute: `__import__(`, `x.__class__`;
- `eval(`, `exec(`, `compile(`, `getattr(`, `setattr(`, `delattr(`, `globals(`,
  `breakpoint(` with no space before the parenthesis;
- a call on `os.` (`system`, `popen`, `exec*`, `spawn*`, `remove`, `unlink`,
  `rmdir`, `kill`) or on `subprocess`, `importlib`, `shutil`, `ctypes`, `pickle`,
  `marshal`, `builtins`, `runpy`, `pty`;
- an exact import statement of one of `os`, `sys`, `subprocess`, `shutil`,
  `socket`, `ctypes`, `importlib`, `builtins`, `pickle`, `marshal`, `pty`, `runpy`,
  `multiprocessing` (`import os`, `from subprocess import run`);
- a shebang path `#!/`.

Any non-JSON value (set, object, function, complex) is refused as well. Natural
utterances stay accepted, for example "import photos", "Je suis un utilisateur
lambda : peux-tu m'aider ?", "Le subprocess a planté", "Compile (vite) le rapport",
"exec (le directeur) arrive", "__Important__ : rappelle-moi", "Lance python -c
dans le terminal", "Ça coûte $(10)". Consequently shell text such as
`rm -rf /` is *not* detected: it is harmless because no Test Lab value is ever
executed.

## Errors

`TestLabError(ValueError)` carries a stable `code` and a `detail` naming the
field and rule (`str(error)` is `"<code>: <detail>"`). Subclasses:
`TestLabRedactionError`, `ForbiddenCodeError`, `RunTransitionError`.

| Code | Meaning |
|---|---|
| `testlab_field_invalid` | A field breaks its rule |
| `testlab_fields_mismatch` | Unknown or missing fields |
| `testlab_schema_unsupported` | Wrong `schema` or `schema_version` |
| `testlab_limit_exceeded` | Size, count or depth bound |
| `testlab_reference_invalid` | Cross-reference or status/verdict contradiction |
| `testlab_parameter_invalid` | Parameter value or key against its spec |
| `testlab_forbidden_private_data` | Private key or raw bytes |
| `testlab_forbidden_code` | Code-carrying key or value, non-JSON value |
| `testlab_json_invalid` | Malformed JSON text, duplicate key, NaN |
| `testlab_transition_illegal` | Status change outside the state machine |

## Storage

TestRuns and artifacts live in a filesystem store, separate from the
`RuntimeJournal` and never in `data/state/jarvis.sqlite3` (tracked in git,
locked by the running Jarvis, migrations shared with other branches). Joins to
sessions go through `TestRun.join_ids`.

### Port

`jarvis/testlab/store.py::TestRunStore` (synchronous Protocol). The port is
Test Lab-local rather than in `jarvis/ports/v2.py`: all callers are Test Lab
code, and `ports/v2.py` is the Core composition surface edited by parallel
work. Its shape follows `ConversationEventStore` (Protocol, frozen value types,
typed errors with a stable code). It is synchronous because it is local files
under an OS lock used by worker subprocesses and the CLI; async callers
(Control Center) wrap calls in `asyncio.to_thread`.

| Method | Contract |
|---|---|
| `create_run(run)` | Stores a new `queued` run with no artifacts; `testlab_store_run_exists` if the id is taken; `testlab_store_environment_refused` if `environment` holds a name outside `ENVIRONMENT_FACT_NAMES` (Capture). |
| `get_run(run_id)` | `RunNotFoundError` / `RunRecordCorruptError` instead of a record. |
| `update_run(updated, *, expected)` | Compare-and-swap under the run lock (Concurrency), then `check_run_update`, then each new artifact reference is checked against the write limits, the write-time manifest and the stored bytes (Artifacts). |
| `list_runs(query)` | `RunPage {runs, corrupt, next_cursor}` |
| `delete_run(run_id)` | Retention deletion of a terminal run: the only way a terminal record changes. |
| `put_artifact(run_id, path, *, kind, media_type, data)` | Streams `bytes`, an iterable of `bytes` or a binary file into a non-terminal run and returns the `ArtifactRef` (sha256 and size computed while streaming). The record is unchanged: the writer adds the reference in its next `update_run` or `complete_run(artifacts=...)`. |
| `read_artifact(run_id, path, *, verify=True)` / `open_artifact` | Only artifacts referenced by the record. `read_artifact` reads once; `verify` checks the size and sha256 of the returned bytes. On Windows, while a handle from `open_artifact` is open, `delete_run` fails with `testlab_store_busy` after about 1 s of retries; retention retries on its next pass. |
| `list_artifacts(run_id)` | The references committed in the record. |
| `storage_usage()` | `StorageUsage {runs: RunUsage[], corrupt}` for retention. |

`RunQuery` filters: `diagnostic_id`, `diagnostic_version`, `profile`,
`statuses` (frozenset), `sweep_id`, `bundle_id`, `created_from` /
`created_until` (half-open, on the run id time), `limit` (1..500, default 50),
`newest_first` (default true), `after_run_id` (cursor). Order is by run id
(creation time, then nonce): stable and total. `next_cursor` is set only when a
further run matches. Time and cursor filters are decided from directory names;
the other filters read each record, so a listing costs one record read per
in-range run.

### Update rule

`check_run_update(stored, updated)` (pure) is enforced by every store, whatever
built `updated`: `dataclasses.replace` can construct a valid record with a
regressed status, so the caller is never trusted.

- a terminal stored record is immutable (`RunTransitionError`, `testlab_transition_illegal`); only retention deletes it;
- a status change must satisfy `can_transition`; an unchanged non-terminal status may enrich the record (`environment`, `join_ids`, new artifacts);
- identity fields never change (`testlab_store_immutable_field`): `run_id`, `diagnostic_id`, `diagnostic_version`, `profile`, `created_at`, `code`, `config_fingerprint`, `diagnostic_fingerprint`, `parameters`, `overrides`, `bundle_id`, `sweep_id`, `parent_run_id`, `scenario_id`, `scenario_fingerprint`;
- `started_at` never changes once set;
- artifact references are only added, never removed or rewritten;
- `environment` names added by the update stay within `store.ENVIRONMENT_FACT_NAMES` (`testlab_store_environment_refused`; `create_run` checks every name), so the no-identifying-facts rule is enforced at the store boundary, not left to runner discipline. Names already present in the stored record are not re-checked, so a legacy or foreign record can still be cancelled, errored and deleted. The Slice 01 record contract is unchanged; the store is stricter than the codec.

### Layout on disk

The root is injected (`FilesystemTestRunStore(root)`). The composition layer
resolves it to `<runtime>/testlab/` from `V2Settings.runtime_root`
(`JARVIS_RUNTIME_DIR`, gitignored `/runtime/`).

```text
<root>/runs/<run_id>/record.json      canonical JSON of TestRun.to_dict()
<root>/runs/<run_id>/.artifacts.json  write-time manifest: path -> kind, media type, sha256, size
<root>/runs/<run_id>/<artifact path>  artifact bytes
<root>/runs/<run_id>/.record-*.tmp    record write in progress or crash leftover
<root>/runs/<run_id>/.artifact-*.tmp  artifact stream in progress or crash leftover
<root>/runs/.staging-<run_id>-*       run being created
<root>/runs/.deleting-<16 hex>        run being deleted (26 characters, never longer than a run id)
<root>/locks/<run_id>.lock            single-writer lock of the run
```

`record.json` holds exactly `canonical_json(run.to_dict())` (sorted keys,
compact UTF-8, bound 256 KiB). Protocol files have hidden names, which the
artifact path rule never accepts, so they cannot collide with evidence.

### Write protocol

- **Record**: write a hidden temp file in the run directory, flush, `fsync`,
  then `jarvis/adapters/file_replace.py::replace_with_retry` (retries brief
  Windows sharing violations). The target is the old or the new record, never
  partial. On failure the temp file is removed and `testlab_store_io` is raised;
  the previous record stays intact. Directories are not fsynced (not possible
  on Windows; NTFS journals the rename).
- **Creation**: the record is written into `.staging-<run_id>-<nonce>/`, then
  the directory is renamed to `<run_id>`. A run directory appears complete or
  not at all.
- **Artifact**: streamed into a hidden temp file with the per-kind byte cap
  checked on every chunk (`testlab_store_artifact_too_large`, nothing is
  buffered), fsynced, then, under the run lock after re-checking that the run is
  not terminal and the path is not referenced, moved into place; the manifest
  entry (`jarvis.testlab.artifact_manifest` v1, ≤ 1024 entries) is then written
  atomically. A crash between the two leaves bytes without a matching entry,
  which no reference can commit.
- **Deletion**: under the run lock, the run directory is renamed to
  `.deleting-<16 hex>` (it vanishes from every read at once), then removed. The
  hidden name (26 characters) is shorter than a run id (45), so every path inside
  stays within the path budget it was written under and `rmtree` can reach it. A
  failed removal (a file held open) is diagnosed, reported by `list_runs` and
  `storage_usage` in `corrupt` with code `testlab_store_deletion_pending` (never
  invisible), and retried by every temporaries sweep whatever its age. A longer
  leftover from an earlier layout is first renamed to the short form.
- **Crash leftovers**: readers ignore every protocol temporary.
  `FilesystemTestRunStore.remove_stale_temporaries(older_than_s=3600)` removes
  unfinished deletions (at any age), temp files and staging directories older
  than the threshold, empty subdirectories left inside a run (their age taken
  before the sweep empties them; never the run directory, record or manifest),
  and lock files whose run no longer exists. It never follows a link: a symlink
  or junction at any level (run directory, temp file, subdirectory) is skipped,
  so nothing outside the store is touched, and `storage_usage` does not count a
  link target's bytes. Nothing schedules it in Slice 02.
- **Known race (accepted)**: `put_artifact` creates missing parent directories
  just before moving the artifact into place. If a sweep runs at that moment and
  the parent is an old, empty directory being reused, the sweep can remove it
  and the put fails with a retryable error (`testlab_store_io` or
  `testlab_store_path_unsafe`); retrying the put succeeds. This stays documented
  behaviour: the sweep is unscheduled, and Slice 05 will schedule it outside
  active runs.

### Concurrency

One writer at a time per run, enforced by two mechanisms:

1. **Run lock**: an exclusive OS lock on `<root>/locks/<run_id>.lock`
   (`msvcrt.locking` on Windows, `flock` elsewhere), held only for
   read-compare-write (never during a stream; new artifact references are
   hashed under it). The OS releases it if the holder dies, so a crash never
   leaves a stale lock. Locks are per open handle, so threads exclude each
   other like processes. Waiting longer than `lock_timeout_s` (default 5 s)
   fails with `testlab_store_busy`.
2. **Compare-and-swap**: `update_run(updated, expected=...)` fails with
   `RunConflictError` (`testlab_store_conflict`) when the stored status differs
   from `expected.status`, or when the stored record differs in any field from
   `expected`. A writer re-reads (`get_run`) and decides again, so no update is
   silently lost.

### Corruption handling

A record that is missing, not UTF-8, not strict JSON, fails the `TestRun` codec,
or names another run id raises `RunRecordCorruptError`
(`testlab_store_corrupt`, the codec error code in the detail); it is never a
crash or a silent skip. `list_runs` and `storage_usage` return such entries in
`corrupt` (`CorruptRunEntry {entry, code, detail}`), together with stray names
in `runs/`, run directories that are links, unfinished deletions
(`testlab_store_deletion_pending`) and runs whose `.artifacts.json` manifest
does not decode (`testlab_store_corrupt`). A run with a corrupt manifest stays
readable and is also listed in `runs`, but no artifact can be put or committed
to it until the manifest is repaired. Corrupt entries never count
toward `limit` and are never deleted automatically. The store emits a
`warning` diagnostic for them through the optional injected `DiagnosticSink`
(the `RuntimeJournal.emit` signature), and `info` for creation, status changes,
stored artifacts and deletions. A failing sink never fails a store operation
(`diagnostic_failures` counts it under a lock, so the count is exact across threads).

### Artifacts

- Path: the `ArtifactRef` path rule (`check_artifact_path`) plus filesystem
  checks. `record.json` is reserved (any case); Windows device names (`con`,
  `nul`, `com1`, `lpt1`... with any extension) are refused on every platform; no
  component may be a symlink or junction, and the resolved target must stay
  inside the run directory; a path equal to a referenced path except for case is
  refused (case-insensitive filesystems). All fail with
  `testlab_store_path_unsafe`.
- An already-referenced path is never overwritten (`testlab_store_artifact_refused`).
- **Kind and media type are fixed at write time.** `put_artifact` records each
  written artifact in the hidden `.artifacts.json` manifest. A new reference
  committed by `update_run` must equal its manifest entry (kind, media type,
  sha256, size; otherwise `testlab_store_artifact_mismatch`), must satisfy the
  store's current limits (`audio_clip` only with `allow_audio`:
  `testlab_store_artifact_refused`; `size_bytes` within the cap of its kind:
  `testlab_store_artifact_too_large`), and must match the stored bytes. Bytes
  written as a `report` therefore cannot be committed as an `audio_clip` or as an
  oversized `config_snapshot`. The limits are checked again at commit because a
  store may be reopened with stricter limits than the one that wrote. A manifest
  is used rather than per-artifact sidecars: one atomic file per run, written
  under the lock that already serializes the write, with no extra path length.
- **Path budget.** On Windows without `LongPathsEnabled=1` (registry
  `HKLM\SYSTEM\CurrentControlSet\Control\FileSystem`), an absolute path may
  hold at most 259 characters (`MAX_PATH` 260 including the terminating NUL), and
  a created directory at most 247 (`CreateDirectoryW` keeps 12). The store checks
  the absolute length of every path it will create before writing: the artifact,
  its temp file (30-character name `.artifact-<16 hex>.tmp`; record and manifest
  temp files are 28 characters, `.record-<16 hex>.tmp`), each new parent directory, and, at
  `create_run`, the staging directory and record temp file, the run directory
  and the lock file. It raises `testlab_store_path_unsafe` with the length and the
  budget (numbers, never the path). With the default root
  `C:\Projects\jarvis\jarvis\runtime\testlab` a run directory takes 87
  characters, which leaves at most 171 for an artifact path. The budget is
  `FilesystemTestRunStore(max_path_chars=...)`: default
  `default_max_path_chars()` (259, or None when long paths are enabled or off
  Windows). The `\\?\` prefix is not used, because `replace_with_retry`,
  `shutil.rmtree` and the lock would all have to be proven with it.
- `ArtifactWriteLimits {max_bytes_by_kind, allow_audio=False}`. Default caps:
  `config_snapshot` and `scenario` 1 MiB, `metrics` 4 MiB, `report` 16 MiB,
  `event_log`, `trace_excerpt` and `worker_log` 64 MiB, `audio_clip` 32 MiB.
  `audio_clip` is refused unless the store was built with `allow_audio=True`.

### Retention

`jarvis/testlab/retention.py`. `TestLabRetentionPolicy` is disabled unless
explicitly enabled (the `ConversationEventRetentionPolicy` idiom); nothing
schedules it in Slice 02.

| Field | Default |
|---|---|
| `enabled` | `false` |
| `max_age` | 30 days (from `finished_at`, or `created_at` when absent) |
| `max_runs` | 1000 |
| `max_total_bytes` | 2 GiB (every byte under the run directories) |
| `max_bytes_by_kind` | `audio_clip`: 256 MiB (referenced artifact bytes) |
| `max_deletions_per_apply` | 128 (1..1024) |

`plan_retention(policy, usage, *, now)` is pure. Only whole terminal runs are
deleted: removing one artifact would leave a terminal record referencing missing
bytes, and a queued or running run still has a writer. Rules, each deleting the
oldest remaining terminal runs until its bound holds: `max_age`, `max_runs`,
each per-kind cap (vocabulary order), `max_total_bytes`. Active runs count
toward every bound but are never selected (`blocked_active`); corrupt entries
are never selected (`blocked_corrupt`; a run whose only defect is its artifact manifest is still a readable run and can be selected); a bound that cannot be met without
active runs is listed in `unmet`; selections beyond `max_deletions_per_apply`
are `deferred`. `apply_retention_plan(store, plan)` calls `delete_run`, which
re-checks under the lock that the run is still terminal, so a stale plan cannot
delete an active run. Refusals are reported as `(run_id, code)` in `skipped`
and never stop the pass.

### Capture

`jarvis/testlab/capture.py` fills the record fields a runner must not make up.

- **Code identity**: `read_git_revision(repo_root)` reads `.git` files directly:
  detached `HEAD`, symbolic refs (up to 5 hops), loose refs, `packed-refs`
  (comment and peeled `^` lines skipped), and linked worktrees (`.git` file
  `gitdir:` plus `commondir`). The reftable ref format and unborn branches fail
  with `testlab_capture_unavailable`. No subprocess: `scripts/verify_release.py`
  forbids `subprocess.run(` under `jarvis/`. `dirty` cannot be derived from
  files without reimplementing git's index comparison, so
  `capture_code_identity(repo_root, *, dirty_probe)` takes an async probe. The
  default `git_worktree_dirty` runs `git --no-optional-locks status --porcelain
  -- . :(exclude)data/state` through `jarvis.runtime.worktrees.git` (asyncio,
  argument array). `--no-optional-locks` stops git from refreshing the index, so a
  Test Lab run never takes `index.lock` against the user's own git commands. Untracked files count as dirty. `data/state` is excluded
  because the running Jarvis rewrites its tracked SQLite state continuously.
  Git error messages are reduced to their code (they may carry local paths).
- **Environment**: `capture_environment(probe, *, fragments)` returns
  `EnvironmentCapture {facts, omitted}`. The facts are a closed set (`store.ENVIRONMENT_FACT_NAMES`, which `create_run` and `update_run` enforce):
  `os` (lowercase system), `os_release`, `os_version`, `machine` (CPU
  architecture), `python_implementation`, `python_version`, `host.cpu_count`,
  `host.memory_gib_bucket` (total RAM rounded to a power of two GiB). It never
  captures the home path, host name, user name, account, domain or network
  identifiers (no `platform.node()`, no addresses). As a second guard, any
  value containing an identity fragment is dropped with reason `identifying`.
  The fragments are the current user name, host name, home path and the
  `USERNAME`/`USER`/`COMPUTERNAME`/`HOSTNAME`/`USERDOMAIN`/`USERPROFILE`/`HOME`
  values (≥ 3 characters, case-insensitive). Probe failures, empty values and
  values failing the environment name/value rules are omitted with reasons
  `probe_failed`, `unavailable`, `invalid`. The voice architecture is
  configuration, not environment: it belongs to the config snapshot.
- **Configuration snapshot**: `build_config_snapshot(settings, *, home)` takes a
  mapping or a dataclass (`V2Settings`) and returns `ConfigSnapshot {document,
  fingerprint, redacted, encoded}`. Document: `{schema:
  "jarvis.testlab.config_snapshot", schema_version: 1, settings}`, ≤ 1 MiB,
  depth ≤ 16. A key that the Name rule marks private (secrets, tokens, prompts,
  hidden reasoning, raw audio, for example `openai_api_key`, `credentials`,
  `token_file`) keeps its key, and its non-empty value becomes `"<redacted>"`,
  so presence stays comparable. `Path` and `Enum` values become text; the home
  directory inside any text becomes `~`; every URL inside any text keeps only
  `scheme://host[:port]/path` (userinfo, query and fragment removed, for example
  `https://u:p@host/x?token=abc` becomes `https://host/x`; an unparseable URL
  becomes `scheme://<redacted>`; prose punctuation right after a URL stays prose,
  so `Tu connais http://site.fr?` is unchanged; `redact_urls`). An scp-like SSH
  remote drops its user part the same way (`git@github.com:org/repo.git` becomes
  `github.com:org/repo.git`), and every email address becomes `<email>` (email
  addresses identify a person; the environment already bans identity;
  `redact_identifying_text`). Raw bytes, sets, non-string keys and non-finite
  numbers are refused. The fingerprint (`TestRun.config_fingerprint`)
  is `content_fingerprint(document)` of the **redacted** document: hashing
  secret values would make every record an offline guessing oracle.
  `store_config_snapshot(store, run_id, snapshot)` writes it as the
  `config_snapshot` artifact `config_snapshot.json` (`application/json`).
  Values under non-private names are otherwise kept verbatim. In particular, a
  secret embedded in a URL *path* (a webhook token such as
  `https://hooks.slack.com/services/T000/B000/<token>`) is **not** detected: such
  settings must be caught by their name. A regression test
  imports `jarvis/runtime/credentials.py` (`LEGACY_KEYS`, every `PROVIDERS[].env`
  name) plus the storage keys `credentials` and `credential_bindings`, and
  asserts that each one is redacted, so a new provider whose key name escapes the
  Name rule fails the test.

### Store errors

`TestLabStoreError(TestLabError)`; subclasses `RunNotFoundError`,
`RunConflictError`, `RunRecordCorruptError`. Details name the run id and the
rule, never values or local paths. `TestLabCaptureError(TestLabError)` carries
`testlab_capture_unavailable`.

| Code | Meaning |
|---|---|
| `testlab_store_not_found` | No such run, or artifact not referenced by the record |
| `testlab_store_run_exists` | `create_run` with a taken id |
| `testlab_store_conflict` | CAS lost, terminal run written to, non-terminal run deleted, invalid new run |
| `testlab_store_busy` | Run lock not acquired in time, or run directory held open at deletion |
| `testlab_store_corrupt` | Unreadable record, unreadable artifact manifest, or stray entry |
| `testlab_store_io` | Filesystem failure (exception type in the detail) |
| `testlab_store_immutable_field` | `check_run_update` identity rule |
| `testlab_store_path_unsafe` | Artifact path or run id refused, link crossing, case collision, path budget exceeded |
| `testlab_store_artifact_too_large` | Per-kind cap exceeded while streaming, or a new reference over the cap of its kind |
| `testlab_store_artifact_refused` | Audio not allowed (at put or commit), path already referenced, manifest full, invalid kind, media type or stream |
| `testlab_store_artifact_mismatch` | Reference differing from its write-time manifest entry, or bytes missing or differing in size or sha256 |
| `testlab_store_environment_refused` | Run `environment` name outside `ENVIRONMENT_FACT_NAMES` (all names at create, added names at update) |
| `testlab_store_deletion_pending` | Listing/usage entry: a run deletion not finished, retried by the sweep |
| `testlab_limit_exceeded` | Record over 256 KiB |
| `testlab_capture_unavailable` | Git identity not determinable |

## Validation

```powershell
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/unit/test_testlab_identity.py tests/unit/test_testlab_profiles.py tests/unit/test_testlab_diagnostics.py tests/unit/test_testlab_scenarios.py tests/unit/test_testlab_runs.py tests/unit/test_testlab_purity.py tests/unit/test_testlab_store.py tests/unit/test_testlab_store_retention.py tests/unit/test_testlab_store_capture.py
```

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
  - `runs.py`: `TestRun`, `RunStatus` state machine, `ArtifactRef`, `CodeIdentity`, `RunFailure`.
- Conformance tests: `tests/unit/test_testlab_identity.py`,
  `tests/unit/test_testlab_profiles.py`, `tests/unit/test_testlab_diagnostics.py`,
  `tests/unit/test_testlab_scenarios.py`, `tests/unit/test_testlab_runs.py`,
  `tests/unit/test_testlab_purity.py`; shared builders `tests/fakes/testlab.py`.
- Handoff: `tasks/jarvis-category2-test-lab/` (Slice 01).

Status 2026-09-17: contracts only. Persistence (Slice 02), DiagnosticBundle
(03), catalog, manifests and primitive vocabulary (04), supervisor/worker (05),
profile runners (06, 08, 09), score computation and sweeps (07), API/CLI/HTTP
(10) and UI (11) do not exist yet.

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

## Validation

```powershell
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/unit/test_testlab_identity.py tests/unit/test_testlab_profiles.py tests/unit/test_testlab_diagnostics.py tests/unit/test_testlab_scenarios.py tests/unit/test_testlab_runs.py tests/unit/test_testlab_purity.py
```

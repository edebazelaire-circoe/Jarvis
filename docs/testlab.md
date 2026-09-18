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
  - `retention.py` (Slice 02): `TestLabRetentionPolicy`, `plan_retention`, `apply_retention_plan`;
  - `redaction.py` (Slice 03): `redact_urls`, `redact_identifying_text` (moved from `capture.py`, which re-exports them);
  - `bundle.py` (Slice 03): `DiagnosticBundle` schema and strict codec, vocabularies, `SECTION_LIMITS`;
  - `bundle_rules.py` (Slice 03): `AnomalyRule`, `DEFAULT_RULES`, `RULE_EVALUATORS`, `evaluate_rules`;
  - `bundle_builder.py` (Slice 03): `SessionSelector`, evidence inputs, `BundleOptions`, `build_diagnostic_bundle`;
  - `primitives.py` (Slice 04): `ArgSpec`, `PrimitiveSpec`, `PrimitiveRegistry`, `DEFAULT_PRIMITIVES`, `ScenarioContext`, `check_scenario`, `PrimitiveHandler`;
  - `implementations.py` (Slice 04): `ImplementationEntry`, `ImplementationRegistry`, `default_implementations`;
  - `manifests.py` (Slice 04): `DiagnosticManifest`, `CatalogLock`, `LockEntry`, `check_manifest`, `render_manifest`, `CatalogError`;
  - `promotion.py` (Slice 04): `promote_scenario`, `PromotionResult`, `PromotionRefused`;
  - `jobs.py` (Slice 05): `WorkerJob`, `WorkerResult`, the per-run protocol file names and the failure-code vocabulary;
  - `scoring.py` (Slice 07): `component_score`, `score_breakdown`, `compute_score` (the `weighted_mean` contract);
  - `outcomes.py` (Slice 07): `RunOutcomeClass`, `FAILURE_OUTCOMES`, `outcome_of`, `classify_run`, `RunOutcomeSummary`;
  - `compare.py` (Slice 07): `compare_runs`, `compare_against`, `aggregate_runs`, `median`, their delta and incomparability types;
  - `sweeps.py` (Slice 07): `SweepSpec`, `SweptParameter`, `SweepPoint`, `expand_points`, `check_sweep_spec`, `SweepRecord`, `SweepStatus`.
- I/O modules (Slices 02, 03, 04, 05 and 07, see Storage, DiagnosticBundle, Catalog and Sweeps):
  - `_fs.py` (private, Slice 03): lock, atomic write, path budget and link helpers shared by both filesystem stores;
  - `filesystem_store.py`: `FilesystemTestRunStore`, the local durable adapter;
  - `capture.py`: `read_git_revision`, `capture_code_identity`, `capture_environment`, `build_config_snapshot`, `store_config_snapshot`, plus `redact_evidence` / `failure_detail` (Slice 05, captured worker output);
  - `bundle_capture.py` (Slice 03): `capture_diagnostic_bundle`, `read_session_trace`, `read_session_events`, `read_voice_session_reports`, `project_bundle_trace_entry`;
  - `filesystem_bundle_store.py` (Slice 03): `FilesystemBundleStore`;
  - `catalog.py` (Slice 04): `Catalog`, `CatalogEntry`, `ProfileAvailability`, `load_catalog`, `DEFAULT_CATALOG_ROOT`;
  - `replay.py` (Slice 04): the `jarvis.voice_replay` v1 codec and the scenario adapter;
  - `runners.py` (Slice 05): `DiagnosticRunner`, `RunContext`, `RunOutcome`, `RunCancelled`;
  - `supervisor.py` (Slice 05): `RunSupervisor`, `RunRequest`, `SupervisorPolicy`, `AdoptionReport`;
  - `worker_launcher.py` (Slice 05): `SubprocessWorkerLauncher` and the `WorkerLauncher` seam;
  - `worker.py` (Slice 05): the worker entry point `python -m jarvis.testlab.worker`;
  - `maintenance.py` (Slice 05): `MaintenancePolicy`, `run_maintenance_pass`;
  - `selftest.py` (Slice 05): the `selftest.worker` test fixture diagnostic and its runner;
  - `sweep_runner.py` (Slice 07): `SweepRunner`, `SweepPolicy`, `build_sweep_summary`;
  - `filesystem_sweep_store.py` (Slice 07): `FilesystemSweepStore`.
- Official manifests: `jarvis/testlab/official/<domain>/<name>.v<N>.json` plus `catalog.lock.json`.
- Conformance tests: `tests/unit/test_testlab_identity.py`,
  `tests/unit/test_testlab_profiles.py`, `tests/unit/test_testlab_diagnostics.py`,
  `tests/unit/test_testlab_scenarios.py`, `tests/unit/test_testlab_runs.py`,
  `tests/unit/test_testlab_purity.py`, `tests/unit/test_testlab_store.py`,
  `tests/unit/test_testlab_store_retention.py`, `tests/unit/test_testlab_store_capture.py`,
  `tests/unit/test_testlab_bundle.py`, `tests/unit/test_testlab_bundle_capture.py`,
  `tests/unit/test_testlab_primitives.py`, `tests/unit/test_testlab_primitives_replay.py`,
  `tests/unit/test_testlab_catalog.py`, `tests/unit/test_testlab_catalog_promotion.py`,
  `tests/unit/test_testlab_supervisor.py`, `tests/unit/test_testlab_supervisor_jobs.py`,
  `tests/unit/test_testlab_virtual.py`, `tests/unit/test_testlab_scoring.py`,
  `tests/unit/test_testlab_scoring_outcomes.py`, `tests/unit/test_testlab_compare.py`,
  `tests/unit/test_testlab_sweep.py`, `tests/unit/test_testlab_sweep_runner.py`,
  `tests/integration/test_testlab_worker.py`, `tests/integration/test_testlab_sweep_runs.py`, opt-in
  `tests/integration/test_testlab_bundle_real_session.py`; shared builders `tests/fakes/testlab.py`,
  session fixture `tests/fakes/testlab_bundle.py`.
- Handoff: `tasks/jarvis-category2-test-lab/` (Slices 01 to 07).

Status 2026-09-18: contracts (Slice 01), run persistence (Slice 02), the
DiagnosticBundle with its capture service and bundle store (Slice 03), the
catalog with its manifests, primitive vocabulary and promotion path (Slice 04),
the run supervisor with its isolated worker process (Slice 05), the `virtual`
profile with its five registered runners (Slice 06), and scoring, outcomes,
comparison and parameter sweeps (Slice 07). The four seed diagnostics run on
`virtual` through real worker processes, a run carries its declared score, a
terminal run classifies as `passed` / `failed` / `inconclusive` / `refused` /
`crashed` / `cancelled`, and a sweep fans isolated runs out over declared
parameter values and persists a replayable record. The supervisor schedules the
store upkeep and owns the run store root it is given; nothing composes it into
the application yet (no default root wiring, no CLI or HTTP entry). The `audio`,
`live` and `hardware:*` profiles (08, 09), API/CLI/HTTP (10), UI (11) and the
rollout (12) do not exist yet.

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
| Document names | `jarvis.testlab.diagnostic`, `jarvis.testlab.scenario`, `jarvis.testlab.run`, `jarvis.testlab.bundle`. |
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
worst}`, distinct metrics). Binding formula: each component maps the metric
linearly from `worst` (0) to `best` (100), clamped to 0..100; the score is the
weight-weighted mean. The score is a UI synthesis, never a verdict. It is
computed by `jarvis.testlab.scoring`, in the supervisor (see "Scoring").

## Scenarios

`Scenario {schema, schema_version, scenario_id, title, description, provenance,
steps}`: `scenario_id` dotted lowercase ≤ 64; title ≤ 120, description ≤ 512 (or
null); 1..256 steps; ≤ 64 KiB canonical JSON (the `jarvis.voice_replay` fixture
bound).

The `provenance` **key is required on the wire** (its value may be null), like every
other field of a strict codec: a scenario document written before Slice 04, without
that key, is refused with `testlab_fields_mismatch` and must gain `"provenance":
null`. Nothing had been stored when the field was added.

`provenance` (null for a scenario authored from scratch) is where an
incident-derived scenario comes from: `ScenarioProvenance {source_path, source_kind,
origin, reported, derived, constructed}`. `source_path` is repo-relative POSIX (no
parent segment, drive or backslash); `source_kind` is `human_trace_reconstruction`
or `sanitized_trace`; `origin` is the UTC millisecond instant of `at_ms` 0 in the
source; the three evidence categories hold each
category ≤ 32 `ScenarioEvidence {source_ref ≤ 160, fact ≤ 512}`. It is the
`jarvis.voice_replay` provenance, productized, so every replay fixture converts
with its evidence intact. It is inside `scenario.fingerprint()`: a scenario with
other evidence is a different declaration.

`ScenarioStep {primitive, args}`: `primitive` is a dotted lowercase name of the
registered vocabulary (Scenario primitives). `Scenario.from_dict(payload,
*, primitives)` requires `primitives`: the registered names (an unregistered step
fails with `testlab_reference_invalid`), or the explicit sentinel `SHAPE_ONLY` to
check shape and safety only (fixture tooling, catalog lint). There is no permissive
default; a scenario that will execute is decoded against the registry
(`check_scenario_primitives` does the same on a constructed scenario). `args` is a JSON object: snake_case keys
at every depth, nesting ≤ 6, ≤ 64 keys per object, ≤ 64 list items, strings ≤ 512,
integers within ±2⁵³, finite numbers, ≤ 4 KiB encoded. `scenario.fingerprint()`
identifies exactly what executed (order matters).

Error paths name a step by its index: `steps[<i>].args.<name>` in a decoded scenario
(`scenario.steps[<i>].…` when the whole document is scanned) and the same
`steps[<i>].args.<name>` in the primitive checks. A `ScenarioStep` built on its own
has no index, so it says `step.args.<name>`.

A scenario is inert data. Slice 04 adds the vocabulary that gives its steps meaning
(Scenario primitives) and the catalog that publishes official ones (Catalog); the
executor of the `virtual` profile is `jarvis/testlab/virtual/executor.py` (Virtual
profile).

## Scenario primitives

`jarvis/testlab/primitives.py` holds the closed registered vocabulary. It is a
**superset-compatible productization of the `jarvis.voice_replay` v1 action DSL**:
every replay action is a primitive of the same name with the same argument schema
(the replay codec validates its action data through this module), plus the common
`at_ms` argument and the primitives the replay DSL lacks.

Every step carries `at_ms`: the virtual time of the step, an integer from 0 to
604 800 000 ms (7 days, the replay bound), non-decreasing across the scenario.
`check_scenario(scenario, *, primitives, profiles=(), context=None)` checks
registration, argument schemas, the timeline, the override prelude, profile support
and (with a `ScenarioContext`) declared parameter, metric and assertion names. It
returns `ScenarioCheck {end_ms, primitives, supported_profiles, overrides}`.

| Primitive | Required args | Optional args | Profiles | Notes |
|---|---|---|---|---|
| `user.turn` | `turn_id`, `content_tag` | `addressing` | virtual | Committed user turn by opaque content tag (replay). |
| `user.speech` | `turn_id`, `text` | `addressing` | virtual, live, hw:guided | Authored utterance: virtual transcript, live text input, guided means the human says it. |
| `user.interrupt` | `turn_id`, `text` | – | virtual, live, hw:guided | The user starts speaking over Jarvis output. |
| `brain.hold` | `work_id` | – | virtual | The scripted brain starts holding work (replay). |
| `brain.ready` | `work_id`, `result_tag` | – | virtual | Scripted brain result, as an opaque tag (replay). |
| `brain.release` | `work_id` | – | virtual | The scripted brain releases held work (replay). |
| `scheduler.enqueue` | `candidate_id`, `kind` | `work_id`, `intent_id`, `intent_epoch`, `ttl_ms` | virtual | A speech candidate enters the scheduler (replay). |
| `provider.output_started` | `output_id` | – | virtual | Fake provider starts an output (replay). |
| `provider.transcript_final` | `output_id`, `generated_tag` | – | virtual | Generated words as an opaque tag (replay). |
| `provider.output_done` | `output_id`, `status` | – | virtual | Terminal status of an output (replay). |
| `provider.cancel_rejected` | `output_id`, `reason_code` | – | virtual | The provider refuses a cancel (replay). |
| `provider.session_closed` | `reason` | – | virtual | The provider session closes (replay). |
| `owner.candidate` | `candidate_id` | – | virtual | A barge-in owner candidate opens (replay). |
| `owner.rejected` | `candidate_id` | `reason_code` | virtual | The candidate is rejected (replay). |
| `owner.confirmed` | `candidate_id`, `played_ms` | `provider_item_id` | virtual | The candidate is confirmed (replay). |
| `device.output_busy` | – | `output_id`, `playback_id`, `played_ms` | virtual | The device is playing; needs `output_id` or `playback_id` (replay). |
| `device.consume` | `output_id`, `played_ms` | – | virtual | The device consumes played audio (replay). |
| `device.release` | `output_id` | `provider_still_active` | virtual | The device releases an output (replay). |
| `control.stop` | `reason` | – | all | The session is stopped (replay). |
| `control.checkpoint` | `checkpoint_id` | – | all | The executor settles and records a named point (replay). |
| `time.wait` | – | – | all | Virtual time advances to `at_ms` with no stimulus (timers, TTLs, queues). |
| `audio.inject` | `audio_ref` | `gain_db` | audio, live, hw:auto, hw:guided | A known audio fixture, by reference, never bytes. Not a virtual primitive. |
| `parameter.override` | `parameter`, `value` | – | all | Run-local value; prelude only (see below). |
| `expect.event` | `event` | `count_min`, `count_max` | all | A Conversation Events type must appear `count_min` (default 1) to `count_max` times. |
| `expect.metric` | `metric`, `comparator`, `threshold` | – | all | Ad-hoc check on a declared metric, evaluated on the final run metrics. |
| `expect.assertion` | `assertion_id`, `outcome` | – | all | A declared assertion must end `passed`, `failed` or `missing` (a reproduction expects `failed`). |

Argument types are global: one name has one type everywhere (as in the replay DSL),
declared in `ARG_SPECS` and validated in that order, so a document with several
faults always reports the same first fault.

| Type | Rule |
|---|---|
| identifier (`turn_id`, `work_id`, `candidate_id`, `intent_id`, `output_id`, `playback_id`, `content_tag`, `result_tag`, `generated_tag`, `checkpoint_id`, `provider_item_id`) | `[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}`, opaque; `provider_item_id` may be null |
| time in ms (`ttl_ms`, `played_ms`) and `intent_epoch` | non-negative integer (never a bool), within the timeline bound |
| boolean (`provider_still_active`) | strict bool |
| choice (`addressing`, `kind`, `status`, `reason`, `reason_code`, `comparator`, `outcome`) | closed vocabulary of that name |
| `text` | authored utterance ≤ 280 chars, single line, printable |
| `audio_ref` | relative POSIX path of a `.wav` fixture (the `ArtifactRef` path rule) |
| `gain_db` | −60..20 |
| `parameter` | name of a declared parameter or an allowlisted setting (name rules apply) |
| `value` | JSON scalar, checked against that declaration |
| `event` | a `ConversationEventType` value |
| `metric`, `assertion_id` | declared metric / assertion name |
| `threshold` | boolean or finite number fitting the metric unit |
| `count_min`, `count_max` | integers 0..10 000, `count_min ≤ count_max` |

Rules that span steps:

- **Profiles.** Each primitive declares the profiles that can perform it, and a
  scenario is validated against the profiles it will run on
  (`testlab_primitive_profile_unsupported`). Replay primitives drive controlled
  doubles, which only `virtual` has today; Slices 08 and 09 widen a set only
  together with a runner that really performs it on that profile.
- **Override prelude.** `parameter.override` steps come first, all at `at_ms` 0,
  never twice for one name: overrides are applied to the run snapshot before the
  run starts (Slice 05), never mid-run.
- **Privacy of `text`.** Scenario text is an authored test input, not user data: it
  stays short, single-line and printable, and anything the identifying-text
  redaction would change (an email address, URL credentials, an SSH remote user) is
  refused instead of silently rewritten. To reproduce a real utterance, use the
  opaque `content_tag` of `user.turn`, not a paste.
- **No code, structurally.** A step names a registered primitive and passes JSON
  data; no primitive carries code, an import path, a command or a file to execute,
  and nothing in a Test Lab document is evaluated. The Slice 01 name and value
  guards run on top of that (`testlab_forbidden_code`,
  `testlab_forbidden_private_data`).

`PrimitiveHandler` is the executor-facing seam: a profile runner registers one handler
per primitive it supports; the executor advances its virtual clock to
`step.args["at_ms"]` and calls it. `missing_handlers(primitives, profile, handlers)`
names what a runner still has to cover; it is empty for `virtual` (Virtual profile)
and names everything for the profiles Slices 08 and 09 will add.

## Replay fixtures

`jarvis/testlab/replay.py` is the production home of the `jarvis.voice_replay` v1
codec (schema, size bound, provenance, timeline) that `tests/replay/voice_replay.py`
introduced. That test module is now a thin compatibility layer: it re-exports the
codec unchanged — same names, same stable `fixture_*` error codes, same immutability
— and keeps only `ReplayClock` and `ReplayDriver`, the execution half used by the
existing replay tests; the productized executor is `jarvis/testlab/virtual/executor.py`. Every fixture in `tests/fixtures/voice_replay/` and the
tests `tests/unit/test_voice_replay_fixture.py`,
`tests/integration/test_voice_replay_regressions.py` and
`tests/integration/test_voice_replay_safety_regressions.py` keep passing unchanged.

`replay_fixture_to_scenario(fixture)` / `scenario_to_replay_fixture(scenario)`
convert 1:1: one scenario step per replay step, `args = {at_ms, **data}`, fixture
provenance and `origin` into the scenario provenance. `load_replay_scenario(path)`
does both at once. Two documented narrowings are refused rather than silently
rewritten: an integer above 2⁵³ (the Test Lab JSON bound, e.g. a huge
`intent_epoch`) and an origin with sub-millisecond precision.

## Catalog

The catalog is the introspectable list of official diagnostics. Manifests live in
`jarvis/testlab/official/<domain>/<name>.v<N>.json`, beside `catalog.lock.json` and
beside `implementations.py`, which registers what their profiles name. They ship
inside the package (like `jarvis/runtime/control_center.html`), because the catalog
is production data read by production code, not test or benchmark input.

`load_catalog(root=DEFAULT_CATALOG_ROOT, *, primitives, implementations, sink=None)`
reads the lock and every manifest in sorted path order, validates each one and
returns a `Catalog`. The layout is closed: only the lock at the root, only
`<domain>/` directories, only `<name>.v<N>.json` files, no links. Anything else
fails (`testlab_catalog_path_invalid`) instead of being skipped, so a manifest can
never be silently ignored. On success it emits `testlab.catalog.loaded` (counts
only) through the optional diagnostic sink.

| Call | Returns |
|---|---|
| `list_diagnostics()` | the latest version of every diagnostic, by id |
| `describe(diagnostic_id, version=None)` | one `CatalogEntry`, latest version by default |
| `history(diagnostic_id)` | every published version, oldest first |
| `versions(diagnostic_id)` | the published version numbers |
| `resources_and_cost(diagnostic_id, profile, version=None)` | `ProfileAvailability {profile, requires, cost, implementation, availability, unavailable_reason, detail}` |
| `check_run(run)` | `check_run_against_spec` against the exact version the run was judged by |
| `to_dict()` / `CatalogEntry.to_dict()` | introspection form for the CLI, HTTP API and UI (Slice 10) |

Versions are never removed and must be 1..N with no hole
(`testlab_catalog_history_gap`), so a stored `TestRun` always finds the declaration
it was judged by.

## Manifests

A manifest is a declarative JSON document (no YAML anywhere in the repository, and
none added):

```json
{
  "schema": "jarvis.testlab.manifest",
  "schema_version": 1,
  "diagnostic": { "schema": "jarvis.testlab.diagnostic", "...": "the DiagnosticSpec wire form" },
  "override_allowlist": [ { "name": "speech.stale_ttl_ms", "type": "int", "...": "a ParameterSpec" } ],
  "scenario": null
}
```

- `diagnostic` decodes to the Slice 01 `DiagnosticSpec`, including one `ProfileSpec`
  per supported profile, each with its `implementation` **name**.
- `override_allowlist` declares the settings a run may override run-locally
  (`ParameterSpec` describing the setting); a name may not repeat a declared
  parameter.
- `scenario` is the declarative scenario this diagnostic executes, or null when its
  implementations script it in code. It is validated against every declared profile
  and against the diagnostic's parameters, metrics and assertions; on a non-virtual
  profile its timeline must fit that profile's `max_duration_s`.

**Implementations are names, never code.** `jarvis/testlab/implementations.py` holds
the in-code registry: `ImplementationEntry {name, profile, factory | (unavailable_reason,
detail)}`. A manifest naming something the registry does not hold fails at load time
(`testlab_catalog_implementation_unknown`), and a name declared for another profile
fails too (`testlab_catalog_implementation_profile_mismatch`). No import path, module
name or code string is ever read from a manifest.

**A profile whose runner does not exist yet is `unavailable`, not missing.** The name
is *reserved* in the registry with a reason code (`runner_not_registered`) and a
detail naming the Slice that will register it. The catalog then declares the profile
with its requirements and cost and reports `availability: "unavailable"`, so callers
see that the diagnostic supports the profile and why it cannot run today. Slice 06
turned the five `virtual` reservations into registrations with
`ImplementationRegistry.registering(entries)`, which replaces a *reserved* entry of
the same name and profile and refuses anything else; Slices 08 and 09 do the same for
theirs. That is a code change only, with no manifest edit and therefore no version
bump.

**The lock proves nothing was edited in place.** `catalog.lock.json`
(`jarvis.testlab.catalog_lock` v1) holds one entry per published version:
`{diagnostic_id, version, path, manifest_fingerprint}`. `manifest.fingerprint()`
covers the semantic diagnostic fingerprint (which excludes cosmetic wording), the
override allowlist without its descriptions, and the scenario content fingerprint —
the scenario exactly, because `TestRun.scenario_fingerprint` records what executed.
Loading compares every manifest with its lock entry:

| Situation | Error |
|---|---|
| a published manifest changed without a version bump | `testlab_catalog_fingerprint_drift` |
| a manifest nobody published | `testlab_catalog_unlocked` |
| a locked version whose manifest is gone | `testlab_catalog_lock_orphan` |
| the lock itself is malformed or locks a version twice | `testlab_catalog_lock_invalid` |

**The integrity chain does not cover prose.** A wording edit — the title, or any
description of the diagnostic, a parameter, a metric, an assertion or the override
allowlist — changes no fingerprint, so it raises no drift error and needs no version
bump or lock edit. That is deliberate and it is the same property that keeps a
wording-only re-promotion comparable (`existing=true`, lock untouched) and stored runs
conforming: a sentence is not what a run was judged by. The consequence is worth stating
plainly — the lock proves that the *semantics* of a published version have not moved, not
that its text is the text that was reviewed. Review the prose in the diff, not in the
catalog test.

Publishing or republishing a version (by promotion or by hand) always ends with the
lock, which is data the human writes, never a generated side effect of loading:

```python
from pathlib import Path
from jarvis.testlab.catalog import DEFAULT_CATALOG_ROOT, LOCK_FILE_NAME
from jarvis.testlab.manifests import CatalogLock, decode_manifest_text, lock_entry_for

path = DEFAULT_CATALOG_ROOT / "voice" / "self_echo.v2.json"
entry = lock_entry_for(decode_manifest_text(path.read_text(encoding="utf-8")))
lock_path = DEFAULT_CATALOG_ROOT / LOCK_FILE_NAME
lock = CatalogLock.decode_text(lock_path.read_text(encoding="utf-8")).with_entry(entry)
lock_path.write_text(lock.render(), encoding="utf-8")
```

`with_entry` refuses to replace a version that is already locked, and nothing else:
it will happily add v4 to a diagnostic published up to v2, because a lock is a flat
set of entries and knows nothing about history. Only `load_catalog` refuses the hole
(`testlab_catalog_history_gap`), so **a publishing tool must load the catalog after
writing** — which is exactly what step 5 below does by running the catalog test.

## Promotion

`promote_scenario(scenario, skeleton, *, catalog, version=None, primitives,
implementations)` turns a working ad-hoc scenario plus a declared skeleton (id,
title, description, profiles with their implementation names, parameters, metrics,
assertions, score, override allowlist) into the CONTENT of an official manifest.

It is pure. It returns `PromotionResult {manifest, path, manifest_text,
manifest_fingerprint, lock_entry, existing}` and **writes nothing**: no file in the
repository, no lock edit. The human review step is the gate:

1. run the ad-hoc scenario until it is meaningful, and keep its run ids as evidence;
2. call `promote_scenario` and read the returned `manifest_text` as a diff;
3. write it at `jarvis/testlab/official/<path>` and add `lock_entry` to
   `catalog.lock.json` (`CatalogLock.with_entry(entry).render()`);
4. register or reserve the implementation names the skeleton uses;
5. run `tests/unit/test_testlab_catalog.py`, then commit. The catalog test is what
   proves the published content, its lock and its implementations agree.

Version choice: `version=None` targets the next version (1 for a new id), except
that re-promoting content identical to the latest version returns that version with
`existing: true`, so re-running the flow is idempotent. An explicit `version` must be
published already or be exactly the next one.

`existing: true` compares the *semantic* fingerprint, which excludes the diagnostic's
cosmetic wording: a re-promotion that only rewords the skeleton title, description or a
parameter/metric/assertion description also returns the published version, with
`manifest_text` carrying the new wording. Publishing that text overwrites the file at
the same version and leaves the lock untouched — exactly the wording edit the drift
rule allows. A scenario edit (including its own title or description) is inside the
fingerprint and therefore needs the next version.

`promote_scenario` takes the published history as data — `published={version:
manifest_fingerprint}`, from `Catalog.published_fingerprints(diagnostic_id)`, empty for
a new diagnostic — so it never imports the catalog and stays pure.

| Refusal | Code |
|---|---|
| that version exists with different semantics | `testlab_promotion_version_conflict` |
| the version is neither published nor the next one | `testlab_promotion_version_gap` |
| a step a declared profile cannot perform | `testlab_promotion_profile_unsupported` |
| an assertion or an `expect.metric` on an undeclared metric | `testlab_promotion_metric_undeclared` |
| an `expect.assertion` on an undeclared assertion | `testlab_promotion_assertion_undeclared` |
| a step naming an unregistered primitive | `testlab_promotion_primitive_unknown` |
| an unknown or mismatched implementation name | `testlab_promotion_implementation_unknown` |
| the skeleton itself is invalid (carries `cause_code`) | `testlab_promotion_skeleton_invalid` |
| the scenario is otherwise invalid for the manifest | `testlab_promotion_scenario_invalid` |

## Seed diagnostics

The catalog ships the four Slice 12 seeds with the `virtual` profile only. Slice 06
registered their runners (Virtual profile), so all four are `available` and runnable
today. Slices 08, 09 and 12 add other profiles through a version bump, which keeps the
earlier version in the history.

`speech.stale_supersession` is published at **v1 and v2**; every other seed is at v1. A
request without an explicit version resolves to the latest, so a plain
`RunRequest("speech.stale_supersession", VIRTUAL)` runs v2.

| Diagnostic | Blocking assertions | Notes |
|---|---|---|
| `voice.self_echo` | `barge_in.false_confirmed_count = 0`, `output.completed = true` | Jarvis speaks while its own output returns as input; parameters `output.duration_ms`, `echo.candidate_count`. |
| `speech.payload_integrity` | `speech.payload_mismatch_count = 0`, `speech.replayed_payload_count = 0`, `speech.undelivered_count = 0` | Virtual measure only: scripted payload vs the payload the harness delivered. The producer signal `voice.state.spoken_diverged` compares raw strings and is **not** used (Issue `speech-payload-integrity-needs-normalized-measure.md`). |
| `speech.stale_supersession` v1 | `speech.stale_delivered_count = 0`, `speech.latest_intent_delivered = true` | Carries the converted replay fixture `stale_ack_35_9s` as its scenario, provenance included. |
| `speech.stale_supersession` v2 | the two above, plus `scenario.expectations_failed_count = 0` | Same profiles, parameters and scenario as v1; adds `scenario.expectations_declared` and `scenario.expectations_failed_count` so that an `expect.*` step in its scenario can end the run `failed` rather than `inconclusive` (see "The `expect.*` verdict rule"). **The shipped scenario declares no expectation**, so on the seed's own run both measurements are 0 and the new blocking assertion is vacuous: it exists for a scenario SUPPLIED to this diagnostic, and it is the only thing that can make such a scenario's expectations a verdict. |
| `voice.queue_latency` | `speech.queue_free_to_started_ms ≤ 3000`, `speech.started_to_first_audio_ms ≤ 4000` | Thresholds match the `latency.above_threshold` bundle rule; `user_turn.end_to_first_audio_ms ≤ 8000` stays **non-blocking** and informational (Slice 07 brain-budget decision below). Virtual time measures scheduler delays, never provider or device latency. |

**Brain budget (Slice 07 decision).** Most of the latency findings the Slice 03
bundle raised on the real 2026-09-12 session were brain delay, not scheduler
delay. It does **not** become a blocking assertion of `voice.queue_latency`:
that diagnostic is about the speech scheduler's own delays, and on the `virtual`
profile the brain's thinking time is a run parameter
(`brain.result_delay_ms`), so asserting on it would test the parameter, not the
product. `user_turn.end_to_first_audio_ms` therefore stays exactly where it is,
non-blocking, as the end-to-end context number a reader needs beside the
scheduler ones — and it is what a sweep over `brain.result_delay_ms` moves. A
real brain budget needs a diagnostic of its own, with the brain stage joins as
its metrics; that is a **new manifest awaiting approval**, not a semantic edit of
a shipped one, and Slice 07 ships no manifest change.

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

That failure carries a detail (`inconclusive_detail`) naming the blocking
assertions that had no measurement, or saying that no blocking assertion was
evaluated at all. An assertion id designates exactly one metric in the
declaration, so it answers "which measurement is missing" without putting a
measured VALUE in a failure detail; an empty detail used to make the two "could
not measure" shapes indistinguishable without re-deriving the run.

## Scoring

`jarvis/testlab/scoring.py` (pure). Metrics and assertions are the primary
evidence; the score is a **synthesis** shown beside them.

`ScoreMethod.weighted_mean`, exactly as declared: each component maps its metric
linearly from `worst` (0) to `best` (100), clamps the result into 0..100, and the
score is the weight-weighted mean of the component scores, rounded to
`SCORE_DECIMALS` (4). The direction is carried by which side `best` is on, which
`DiagnosticSpec` already checked against the metric's `MetricDirection`, so a
`lower_better` metric has `best < worst` and the mapping needs no special case.

| Call | Returns |
|---|---|
| `component_score(component, value)` | `(score, clamped)` for one component |
| `score_breakdown(contract, metrics)` | `ScoreBreakdown {method, score, components, missing}` |
| `compute_score(contract, metrics)` | the score, or None |

Two rules:

- **The score never decides a status.** `complete_run` derives `passed` /
  `failed` / `errored` from the blocking assertions alone. A run with score 100
  and a failed blocking assertion is `failed`; a run with score 0 whose blocking
  assertions all passed is `passed`. Both are proven by test
  (`tests/unit/test_testlab_scoring.py`).
- **A score is all-or-nothing.** If any metric a component names was not
  measured, the score is `None` and `ScoreBreakdown.missing` says which. A
  weighted mean over the components that happened to be measured is not the
  declared synthesis, and it would let a diagnostic that measured half of what it
  promised look comparable to one that measured everything.

**Where it runs: the supervisor** (`_store_measured`), from the worker's metrics
and the declaration the run was queued against. Slice 05 made the worker
measurement-only, so `WorkerResult` and `RunOutcome` carry **no score field at
all** (removed in Slice 07): a field the supervisor would have to ignore is dead
contract data and a way for a runner to publish a judgement it has no declaration
to justify. A run the supervisor stopped keeps its partial metrics as evidence
but gets no score, for the same reason a partial mean is refused.

## Outcomes

`jarvis/testlab/outcomes.py` (pure). `RunStatus` is what the state machine and
the store enforce; an **outcome** is how a human or a caller reads the result. It
is derived from `(status, failure code)` with a closed table — no new status is
invented (Slice 01 forbids it) and nothing parses prose.

| Outcome | Means | Typical cause |
|---|---|---|
| `passed` | the product did what the diagnostic declared | every blocking assertion passed |
| `failed` | the product did NOT do what it declared | a blocking assertion failed |
| `inconclusive` | **could not measure**: no verdict was available | a metric was never measured, a stimulus was never answered, the run outlived its budget |
| `refused` | the Test Lab declined; nothing was learned about the product | permission, a resource that never freed, an unavailable runner or catalog |
| `crashed` | the Test Lab itself broke around the run | the worker died, its result was unusable, the declaration refused it |
| `cancelled` | a caller, or the supervisor stopping, ended it | `cancel()`, shutdown |
| `pending` | not terminal yet | `queued`, `running` |

`outcome_of(status, failure_code)` is the table; `classify_run(run)` returns
`RunOutcomeSummary {run_id, status, outcome, failure_code, verdict,
failed_assertions, missing_assertions, measured, score}` with `.conclusive` and
`.to_dict()`. `NO_VERDICT_OUTCOMES` is everything but `passed` and `failed`: a
caller comparing runs excludes them rather than counting them as failures.

`FAILURE_OUTCOMES` maps every code of the Slice 05 vocabulary plus
`assertions_inconclusive`, and a test asserts that coverage. A code that is
**not** in the table reads `crashed`, because an unmapped failure is one we did
not foresee, and a run we cannot explain must never read as a measurement.

Two Slice 07 codes join the vocabulary, both `inconclusive`:

| Code | Meaning |
|---|---|
| `measurement_unavailable` | the runner reached the product but could not obtain a measurement the declaration needs: a stimulus the stack never answered, a step the authored situation could not perform, an expectation with nothing to evaluate against |
| `scenario_expectation_unmet` | an evaluable `expect.*` step disagreed, in a diagnostic that declares no metric able to carry it |

This resolves the Slice 06 carry-over: a missing join still ends
`errored` / `assertions_inconclusive` and an unanswered onset now ends
`errored` / `measurement_unavailable`. Both read `inconclusive`, and the failure
code — a stable identifier, not prose — still tells them apart.

A runner declares "could not measure" by raising a typed exception, never by a
string the worker has to recognise: `runners.MeasurementUnavailable` (which
`VirtualRunError` and `VirtualStepError` subclass) and
`runners.ScenarioExpectationUnmet`. `worker.runner_failure_code(exc)` maps those
two and nothing else; anything else is `runner_failed`, which reads `crashed`.

### The `expect.*` verdict rule

An `expect.*` step is either a statement about the **product** or a defect of the
**scenario**, and the two must not share a shape.

**Which verdict a scenario expectation can produce is a property of the
DECLARATION, not of the runner.** Any diagnostic that declares
`scenario.expectations_failed_count` — a seed shipping a scenario as much as an
ad-hoc probe — carries its expectations as a product verdict; one that does not
cannot express a failed expectation at all, and gets `inconclusive` by design.
`jarvis.testlab.virtual.runners.expectation_metrics` is that single rule, shared
by the generic runner and every specialized one.

| Case | Treated as | Ends |
|---|---|---|
| Evaluated and disagrees, and the diagnostic declares `scenario.expectations_failed_count` | product verdict: the count is a MEASUREMENT, and the diagnostic's own blocking assertion (`scenario.expectations_failed_count eq 0`) turns it into a verdict through the ordinary path | `failed` |
| Evaluated and disagrees, in a diagnostic that does NOT declare that metric | it has no way to say so, and dropping it silently is worse; the authored situation did not materialise, so the run is not the experiment that was asked for | `errored` / `scenario_expectation_unmet` → `inconclusive` |
| Could not be evaluated at all: the metric was never measured, it is not declared, the comparator or threshold does not fit it, the assertion was not evaluated, no conversation was opened, the event scan could not finish | authoring / structural, never a statement about the product | `errored` / `measurement_unavailable` (code `testlab_virtual_expectation_unevaluable`) → `inconclusive` |

The consequence is that a failing expectation reaches `failed` **without any new
path**: the supervisor still derives the verdict from a measurement against the
declaration, exactly as for a seed, and no runner ever writes a status.
`VirtualExecutor` records an `ExpectationResult {index, primitive, met, detail}`
per evaluated step; `expectations_failed` is the count, and
`require_expectations_met()` is what `expectation_metrics` calls when the
declaration cannot carry one.

This matters most for `expect.event`, the only expectation form that states
something a seed's own metrics cannot (the Conversation Event log). A real defect
there must be able to read `failed`, not "could not measure" — so a seed that
wants that declares the metric, through a version bump like any other semantic
change. `speech.stale_supersession` v2 is exactly that bump, and the pair is
proven end to end: the same scenario with an unmet `expect.event` ends `failed`
on v2 and `errored` / `scenario_expectation_unmet` → `inconclusive` on v1
(`tests/integration/test_testlab_virtual_runs.py`). A v1 run stored before the
bump still validates against v1 (`Catalog.check_run`), and comparing it with a v2
run reads `different_version` rather than a delta.

**Counting events.** `expect.event` pages the event store with
`MAX_EVENT_PAGE_LIMIT` per page, at most `MAX_EVENT_PAGES` (20) pages. It never
asks for a larger page: the store refuses one, which used to make EVERY
`expect.event` step raise and read `crashed`, met or not. A scan it cannot finish
— more than 10 000 events, or a page with `skipped_rows` — yields a LOWER BOUND,
and a count that may be short cannot decide `count_min` / `count_max`, so the step
refuses to judge instead of truncating silently.

## Comparison

`jarvis/testlab/compare.py` (pure, deterministic, stdlib only — the one order
statistic computes its own median). Same inputs, same comparison, byte for byte.

**Compatibility rule.** Two runs are comparable when they executed the same
declaration on the same profile:

```text
diagnostic_id == diagnostic_id and diagnostic_version == diagnostic_version
and diagnostic_fingerprint == diagnostic_fingerprint and profile == profile
```

The fingerprint is the strict part, on purpose: it covers metrics, units,
directions, assertions, thresholds and the score contract, so two runs that share
it cannot disagree about what a metric means. Two runs of "the same version"
whose declaration was edited in place do not share it, and their numbers are not
the same numbers.

What is **not** an incomparability: different parameters, overrides, code
revision or environment. Those are what an experiment varies — a sweep compares
runs that differ by exactly one parameter — so they are reported as
`RunComparison.differences` (`FieldDifference {field, baseline, candidate}`).

`compare_runs(baseline, candidate, metrics=, candidate_metrics=)` returns
`RunComparison`:

| Field | Content |
|---|---|
| `comparable` | the rule above |
| `metrics` | `MetricDelta {metric, unit, direction, baseline, candidate, delta, percent_change, change}` |
| `assertions` | `AssertionDelta {assertion_id, blocking, baseline, candidate, change}` |
| `score_delta` | `(baseline, candidate, delta)` when both runs scored |
| `differences` | the inputs that differed |
| `incomparable` | `Incomparability {subject, reason, detail}` |
| `regressions` | blocking assertions that passed and no longer do |

`MetricChange` is `better` / `worse` / `unchanged` / `changed`. Direction
awareness needs the declaration: `metrics=` takes a `DiagnosticSpec` or a
`name -> MetricSpec` map, and without it every move reads `changed`, because a
delta with no direction is a number, not an improvement. A boolean metric has no
distance (`delta` and `percent_change` are null) but still has a direction. A
zero baseline has no `percent_change`. Equality is exact: no epsilon.

`AssertionChange` is `unchanged` / `fixed` / `regressed` / `appeared` /
`disappeared` / `changed`. `passed -> missing` is a **regression** (an assertion
nobody could evaluate is not a pass) and `missing -> passed` is `fixed`. Between
two non-passing outcomes — `missing -> failed` and `failed -> missing` — the change
is `changed`, not a regression and not a fix: neither end is a pass, so calling
either direction an improvement would be a judgement the evidence does not support.

`IncomparableReason`: `different_diagnostic`, `different_version`,
`different_declaration`, `different_profile`, `metric_missing_in_baseline`,
`metric_missing_in_candidate`, `different_value_type`, `different_unit`,
`run_not_terminal`. The last one flags a `queued` or `running` record on either
side: it carries no metrics and no verdict by invariant, so without the flag it
would read as "every metric disappeared" rather than "there is nothing here yet".
`candidate_metrics=` is what makes `different_unit` reachable: when the two
declarations give one name different units, the metric is listed instead of
subtracted (1500 ms and 1.5 s are not a 1498.5 regression).

`compare_against(baseline, candidates, metrics=)` keeps the order it was given.
`aggregate_runs(runs, metrics=)` returns `RunAggregate {run_ids, outcomes,
metrics, score}`, where each `MetricAggregate` carries `count`, `minimum`,
`maximum` and `median` — a sweep read at a glance. A metric only some runs
measured is aggregated over those runs and `count` says how many, so a spread
over three of five runs never looks like a spread over five.

## Sweeps

`jarvis/testlab/sweeps.py` (pure: declaration, expansion, record),
`jarvis/testlab/sweep_runner.py` (orchestration),
`jarvis/testlab/filesystem_sweep_store.py` (persistence).

**A sweep never writes a permanent setting.** Locked decision 9, made mechanical:
a `SweepSpec` has no field naming a settings file, the orchestrator has no write
path to one, and every swept value travels as a run-local parameter or a
run-local override — exactly like a single run's, through the supervisor, which
only ever reads the permanent file and copies it into the run scratch. The
summary names the best point per metric and stops there. Proven by
`tests/integration/test_testlab_sweep_runs.py`, which sweeps over a real settings
file and asserts its bytes are unchanged.

### Declaration

`SweepSpec {diagnostic_id, profile, version, parameters, overrides, swept,
repetitions, scenario, title, description}`, document `jarvis.testlab.sweep`
version 1, with `to_dict` / `from_dict` / `fingerprint()`.

`SweptParameter {name, target, values}` is one axis; `target` is `parameter` (a
declared `ParameterSpec`) or `override` (a name in the manifest's
`override_allowlist`). `SweptParameter.from_range(name, target, start=, stop=,
step=)` expands an inclusive numeric range to explicit values at construction —
computed as `start + i * step`, never accumulated, so a float range does not
drift — because the stored declaration must be the exact list of values that ran.

Bounds, refused as a whole rather than truncated: `MAX_SWEPT_PARAMETERS` 4,
`MAX_SWEEP_VALUES` 64 per axis, `MAX_SWEEP_POINTS` 256, `MAX_SWEEP_RUNS` 512
(points × repetitions), `MAX_REPETITIONS` 16. A silently shortened sweep is a
conclusion drawn from evidence nobody asked for.

`check_sweep_spec(spec, diagnostic, override_allowlist)` validates every swept
and fixed value with `check_parameter_value`, exactly as a single run's would be,
and returns the points; `SweepError` (`testlab_sweep_invalid`) on the first
violation. A sweep can therefore never reach a value, a setting or a profile a
single `RunRequest` could not.

`expand_points(spec)` is the cartesian product in declaration order, last axis
varying fastest: `SweepPoint {index, values, parameters, overrides}` with a
`label` (`name=value` pairs) for logs and reports.

### Orchestration

`SweepRunner(supervisor=, store=, policy=, diagnostics=)`, with
`await run(spec, grant=) -> SweepRecord` and `await cancel(sweep_id) -> bool`.

- **Sweep id.** One `tls-…` id, minted once and passed as `RunRequest.sweep_id`
  on every run, so the store's existing `RunQuery(sweep_id=…)` filter is the way
  back to the evidence.
- **Bounded fan-out.** Submission is windowed by `SweepPolicy.max_in_flight`,
  clamped down to the supervisor's `max_concurrent_runs`. Submitting every point
  at once would not run them faster — the supervisor bounds concurrency anyway —
  but it would make every queued run accrue blocked time against
  `max_queue_wait_s` and expire as `resource_wait_timeout`. Sweeps are also why
  `max_concurrent_runs` is worth raising above its default of 2 when the host
  allows it.
- **Partial failure is a result.** A point whose run errored, timed out or could
  not even be submitted is recorded with its outcome (or a point-level
  `RunFailure` with code `sweep_failed`) and the sweep carries on.
- **Cancellation.** `cancel(sweep_id)` starts no further point and cancels the
  in-flight runs through the supervisor; the record ends `cancelled` and keeps
  what already ran. It returns False when this runner does not hold that sweep.
- **Refusals.** `run()` raises `SweepError` only when no honest record could be
  written at all (unknown diagnostic, unsupported profile, a value the
  declaration refuses) — the same doctrine as `RunSupervisor.submit`. Everything
  after that is persisted instead.
- **Visible progress.** `testlab.sweep.started`, `testlab.sweep.run_finished`
  (point label, outcome, `completed/total`, elapsed seconds),
  `testlab.sweep.point_failed`, `testlab.sweep.cancelling`,
  `testlab.sweep.finished`. The record on disk is rewritten at the same moment,
  so a long sweep is never a silent process and a crashed orchestrator leaves the
  points it had already run.

### Record and summary

```text
<root>/sweeps/<sweep_id>/sweep.json      canonical JSON of the SweepRecord
<root>/sweeps/<sweep_id>/summary.json    the readable summary artifact
<root>/sweeps/<sweep_id>/.sweep-*.tmp    write in progress (or crash leftover)
<root>/sweeps/.staging-<sweep_id>-*      sweep being created
<root>/locks/<sweep_id>.lock             single-writer OS lock of the sweep
```

`SweepRecord {sweep_id, created_at, spec, status, diagnostic_version,
diagnostic_fingerprint, points, finished_at, failure}`, document
`jarvis.testlab.sweep_record` version 1. `SweepStatus` is `running`, `completed`,
`cancelled` or `failed`; `points` holds one `SweepPointResult {point, runs,
failure}` per point, with `SweepRunOutcome {run_id, status, outcome,
failure_code, score}` per run. `outcome_counts()` reads the whole sweep at a
glance.

A **running** sweep record is rewritten as it progresses — it is the
orchestrator's own progress log — and a **terminal** one is immutable, like a
terminal run (`testlab_store_conflict`). The runs themselves are ordinary
`TestRun` records in the run store, tagged with the sweep id, and the run store's
own rules are what make them evidence; this directory only holds what the runs
cannot say: the declaration that produced them and the order they were meant to
run in. That is what makes a sweep replayable.

`build_sweep_summary(record, runs, diagnostic)` is pure, so the summary can be
rebuilt from stored records at any time. Document `jarvis.testlab.sweep_summary`
version 1: the declaration, the outcome counts, one entry per point with its
`RunAggregate` and its `RunComparison` against the first point that measured
anything, `best_points` (for every directed metric, which point had the best
median), and a `note` stating that nothing here was written to permanent
settings.

`SweepStore` (port in `store.py`): `put_sweep`, `get_sweep`, `list_sweeps`,
`put_sweep_summary`, `get_sweep_summary`; errors `SweepNotFoundError`,
`SweepRecordCorruptError`. Unreadable or stray entries are reported in
`SweepPage.corrupt`, never skipped in silence. `put_sweep_summary` is
**write-once** (`testlab_store_conflict` on a second call), the same rule as a
terminal record and for the same reason: a summary is only ever written when the
sweep ends, so a rewrite would edit the conclusion of a finished experiment.

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

Slice 04 adds the vocabulary, catalog and promotion families. `PrimitiveError`
(and `PrimitiveArgError`, which carries the failed `rule`), `CatalogError` (with
`path` and `cause_code`) and `PromotionRefused` (with `cause_code`) are all
`TestLabError` subclasses.

| Code | Meaning |
|---|---|
| `testlab_primitive_unknown` | A step names a primitive the registry does not hold |
| `testlab_primitive_args_invalid` | Step arguments against the primitive schema |
| `testlab_primitive_profile_unsupported` | A declared profile cannot perform a step |
| `testlab_scenario_timeline_invalid` | `at_ms` missing, out of range, going backwards, or an override outside the prelude |
| `testlab_implementation_unknown` | An implementation name is not registered |
| `testlab_catalog_read_failed` | A catalog file could not be read |
| `testlab_catalog_json_invalid` | Malformed manifest JSON |
| `testlab_catalog_schema_invalid` | Manifest shape or contract (`cause_code` keeps the inner rule) |
| `testlab_catalog_path_invalid` | Wrong file name, stray entry, link or nested directory |
| `testlab_catalog_duplicate` | One `(diagnostic_id, version)` declared twice |
| `testlab_catalog_history_gap` | Versions are not 1..N |
| `testlab_catalog_primitive_unknown` / `testlab_catalog_primitive_unsupported` | Manifest scenario against the vocabulary or a declared profile |
| `testlab_catalog_scenario_invalid` | Manifest scenario against its diagnostic or a profile budget |
| `testlab_catalog_implementation_unknown` / `testlab_catalog_implementation_profile_mismatch` | Implementation name resolution |
| `testlab_catalog_fingerprint_drift` / `testlab_catalog_unlocked` / `testlab_catalog_lock_orphan` / `testlab_catalog_lock_invalid` | Catalog lock |
| `testlab_catalog_not_found` | Unknown diagnostic, version or profile |
| `testlab_promotion_*` | Promotion refusals (see Promotion) |

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
  and run lock files (`tlr-` names only; bundle locks are never touched) whose run
  no longer exists. It never follows a link: a symlink
  or junction at any level (run directory, temp file, subdirectory) is skipped,
  so nothing outside the store is touched, and `storage_usage` does not count a
  link target's bytes. Slice 05 schedules it (Supervisor and workers, Maintenance).
- **Known race (accepted)**: `put_artifact` creates missing parent directories
  just before moving the artifact into place. If a sweep runs at that moment and
  the parent is an old, empty directory being reused, the sweep can remove it
  and the put fails with a retryable error (`testlab_store_io` or
  `testlab_store_path_unsafe`); retrying the put succeeds. This stays documented
  behaviour, and the reason the Slice 05 supervisor only sweeps when it has no
  active run (Supervisor and workers, Maintenance).

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

### Listing cache

`list_runs` decodes one record per run in the store, and decoding is not cheap
(strict codec plus the redaction scan). Sweeps make listings hot, so
`FilesystemTestRunStore` keeps the decoded record of **terminal** runs in a
bounded LRU (`listing_cache_size`, default `DEFAULT_LISTING_CACHE` = 2048; 0
disables it), keyed by the record's `(st_mtime_ns, st_size)`.

**Every listed run is re-stated, and a cached entry whose stamp moved is
re-read.** A terminal record is immutable *through this store*, but the file is
an ordinary file: truncated by a crash, edited by hand or restored from a backup,
it becomes corrupt or different. A cache that trusted immutability kept serving
the old decoded record and reported `corrupt` empty — switching the Slice 02
corruption mechanism off in exactly the long-lived supervisor process it was built
for — and gave one process two truths, `list_runs` serving a record `get_run`
refused. One `os.stat` per listed run is noise against reading and decoding them.

Non-terminal records change under the reader and are never cached, and `get_run` /
`update_run` never consult the cache at all, so the compare-and-swap still reads
the bytes on disk every time. `delete_run` evicts. The manifest defect of a cached
run is remembered with it and revalidated by the same stamp.

**The stamp catches mistakes, not malice.** It is `(st_mtime_ns, st_size)`: an edit
that deliberately restores both — writing a same-sized record and resetting the
timestamp with `os.utime` — is served from the cache by `list_runs` while `get_run`
returns the new bytes. That is the documented threat model (see "Threat model"): the
store defends against crashes, truncation, partial writes and honest mistakes, not
against a process that already has write access to the run directory and is trying to
lie about it. Anyone in that position can rewrite the record for every reader anyway.

Measured on this host with a warm page cache, filtering by `sweep_id`: at 2000
stored runs, 1.9–2.9 s per call without the cache against 140–193 ms warm with it;
at 500 runs, 350–390 ms against 37–53 ms. The stat pass is the difference between
those warm numbers and the 66 ms / 17 ms an unvalidated cache reached — correctness
worth an order of magnitude less speedup, still 8× to 14× faster than no cache.

A store holding more than `listing_cache_size` terminal runs evicts in LRU order,
so a listing that walks past the ceiling re-decodes the runs that fell out and the
speedup degrades gracefully toward the uncached figures; it never becomes wrong,
only slower. Raise `listing_cache_size` (memory is a few kB per record) if a
deployment keeps more runs than that and lists them often.

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
explicitly enabled (the `ConversationEventRetentionPolicy` idiom). The Slice 05
supervisor schedules it, outside active runs (Supervisor and workers, Maintenance).

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

The bundle store (DiagnosticBundle, Bundle storage) reuses these codes with
`BundleNotFoundError` (`testlab_store_not_found`), `BundleConflictError`
(`testlab_store_conflict`) and `BundleRecordCorruptError` (`testlab_store_corrupt`).

## Supervisor and workers

Locked decision 13: a run executes in a supervised isolated worker process,
never inside the Control Center process. The supervisor turns "run this
diagnostic, on this profile, with these parameters" into a persisted, isolated,
observable `TestRun`; the worker executes it and measures.

| Module | Role |
|---|---|
| `jobs.py` (pure) | `WorkerJob` / `WorkerResult` documents, the per-run file names, the closed failure-code vocabulary |
| `runners.py` | `DiagnosticRunner` protocol, `RunContext`, `RunArtifacts`, `RunOutcome`, `RunCancelled`, `MeasurementUnavailable`, `ScenarioExpectationUnmet`: the seam Slices 06/08/09 implement |
| `supervisor.py` | `RunSupervisor`, `RunRequest`, `SupervisorPolicy`, `AdoptionReport`: queueing, reservation, bounds, persistence, adoption |
| `worker_launcher.py` | `SubprocessWorkerLauncher`: process start, stderr capture, tree kill (injectable `WorkerLauncher` seam) |
| `worker.py` | `python -m jarvis.testlab.worker <job.json>`: the child process |
| `maintenance.py` | `MaintenancePolicy`, `run_maintenance_pass`: the scheduled store upkeep |
| `selftest.py` | the `selftest.worker` TEST FIXTURE diagnostic and its runner (never a seed diagnostic) |

### API

```python
supervisor = RunSupervisor(store=store, work_root=runtime / "testlab" / "work",
                           catalog_root=DEFAULT_CATALOG_ROOT, settings_path=runtime / "control-center-settings.json")
await supervisor.start()                        # adopts orphans, then dispatches
run_id = await supervisor.submit(RunRequest(...))   # returns once the queued record is stored
run = await supervisor.status(run_id)               # the stored record, whatever its state
await supervisor.cancel(run_id)                     # cooperative, then killed
run = await supervisor.wait(run_id, timeout_s=...)  # the terminal record
await supervisor.aclose()                           # stops every run, then stops dispatching
```

`RunRequest {diagnostic_id, profile, version = null, parameters, overrides,
scenario, bundle_id, sweep_id, parent_run_id, grant}`. `version` null means the
latest published version, and the resolved one is recorded in the run.

`submit` raises `SupervisorError` only when no honest record could be written at
all — unknown diagnostic, undeclared profile, parameter or override refused by
the declaration, unreadable settings file, no git identity. Everything else is
persisted: the record is the evidence, including for a refusal.

### Lifecycle

1. **submit** resolves the catalog entry, the effective parameters, the
   run-local overrides and the scenario; captures the code identity, the
   environment facts and the redacted configuration snapshot; stores the
   `queued` record, then its `config_snapshot` artifact; returns the run id.
2. **gate**: `check_profile_permission(profile, grant)`. Denied, the run becomes
   `errored` with `permission_denied` and the denials in the detail, and no
   worker is ever started.
3. **dispatch**: the run waits for a free slot and for its declared
   capabilities. The queue is FIFO but a blocked head does not block the rest.
4. **start**: `queued -> running`, the per-run scratch is built, the worker is
   launched and its pid recorded.
5. **watch**: startup bound, heartbeat bound, declared duration, cancel grace,
   then the tree kill.
6. **terminal**: the worker log and the stderr tail are stored as artifacts, the
   verdict is derived from the metrics, `check_run_against_spec` re-checks the
   completed run, and the record is updated under the store's compare-and-swap.

Every step emits through the injected `DiagnosticSink`: `testlab.run.queued`,
`testlab.run.waiting`, `testlab.run.started` (with the pid), `testlab.run.progress`
(first heartbeat), `testlab.run.timeout`, `testlab.run.cancelling`,
`testlab.run.finished` (status, failure code, score), plus
`testlab.supervisor.started` / `.stopped` and `testlab.maintenance.pass`.

### Worker protocol and on-disk layout

Communication is by files in a per-run scratch directory, not by a pipe: the
result must survive the death of either side. A pipe dies with the worker, so a
supervisor that crashed mid-run would find nothing to adopt, while `result.json`
is still on disk. This is the isolated one-shot idiom of
`jarvis/runtime/speaker_benchmark.py::_run_isolated`, with the job written as a
file too, so the command line carries no run data.

```text
<work_root>/<run_id>/job.json            WorkerJob (jarvis.testlab.worker_job v1), written by the supervisor
<work_root>/<run_id>/result.json         WorkerResult (jarvis.testlab.worker_result v1), written atomically by the worker
<work_root>/<run_id>/cancel.json         presence means "stop cooperatively"
<work_root>/<run_id>/heartbeat.json      refreshed by the worker; its mtime is the liveness signal
<work_root>/<run_id>/worker.lock         held by the worker for its whole life (OS lock, released on death)
<work_root>/<run_id>/worker.json         pid and supervisor pid, for a human reading the scratch
<work_root>/<run_id>/worker.log          progress lines; stored as a `worker_log` artifact
<work_root>/<run_id>/worker-stderr.log   captured stderr; stored as a `worker_log` artifact
<work_root>/<run_id>/runtime/            the run's JARVIS_RUNTIME_DIR, with its settings copy
<work_root>/<run_id>/data/               the run's JARVIS_DATA_ROOT
```

The scratch is removed when the run ends (`keep_scratch` keeps it for
debugging); a scratch with no non-terminal run is removed by the next `start()`.
The store's own run directory is never used for protocol files: only committed
artifacts live there.

The worker is started as `python -m jarvis.testlab.worker <job.json>` with the
repository root as its working directory. It resolves the diagnostic from the
catalog named by the job, checks that the declaration still has the fingerprint
the run was queued against, resolves the implementation in the registry
(`default_implementations()` plus the self-test fixture names) and calls its
runner with a `RunContext`.

**The worker reports measurements, never a verdict.** `WorkerResult` carries
`metrics`, `join_ids` and the artifact references it committed — and **no score**
(Slice 07 removed the field; see "Scoring"). The supervisor derives every
`AssertionResult` with `evaluate_assertion` from the declaration, computes the
declared score with `jarvis.testlab.scoring`, calls `complete_run`, then
`check_run_against_spec`. A run whose measurements contradict its declaration
(an undeclared metric, a value outside its unit) is stored `errored` with
`result_contradicts_spec`, never `passed`.

A runner never receives the store. `RunContext.artifacts` is `RunArtifacts`, a
facade scoped to its own run: `put`, `read`, `open`, `list`, and nothing else:
no `update_run`, no `delete_run`, no other run id. The four operations are bound
at construction and the facade keeps no store attribute (`__slots__`), so no chain
of attribute accesses from a `RunContext` reaches a record method. A runner that could write the
record could store a forged `passed` verdict which the supervisor would then find
already terminal, and could delete another run. If a terminal record appears that
the supervisor did not write, it does not shrug: it tries to correct it, reports
the store's refusal (a terminal record is immutable) and logs the incident at
error level with `run_concluded_out_of_band`.

The result file is read once more after the worker exits and after any kill, so a
measurement written just before a liveness fault is never lost. What happens to it
depends on the reason the supervisor had:

- no reason of its own: the metrics decide the verdict, as usual;
- a liveness fault (`worker_startup_timeout`, `worker_unresponsive`) around a
  complete, declaration-conforming measurement: the fault was a false alarm and
  the measurement decides;
- a deliberate stop (`run_timeout`, `cancelled_by_caller`): the status stays the
  supervisor's, and the metrics are attached as evidence when the declaration
  accepts them (otherwise they are dropped and `testlab.run.partial_metrics_dropped`
  says why). A timed-out run therefore reads `timed_out` and still carries what it
  measured.

A result file that exists but does not decode is `worker_result_invalid`, never
`worker_crashed`: a truncated or edited result is a defect to see, not a crash to
infer. Failure details are English; `describe_exit_code` supplies the facts
(NTSTATUS, signal, native crash) and its French label is not used.

Exit codes: 0 measured, 1 a failed result was written, 2 no result could be
written (an unreadable job, a lock another worker holds). The supervisor prefers
the result file over the exit code, and uses the exit code only when there is no
result — `describe_exit_code` then names a native crash in the detail.

### Isolation

- The child's environment gets `JARVIS_RUNTIME_DIR` and `JARVIS_DATA_ROOT`
  inside the run scratch, plus `JARVIS_TESTLAB_RUN_SCRATCH` and
  `JARVIS_TESTLAB_WORKER=1`. `JARVIS_CORE_TOKEN_FILE` is dropped so it cannot
  point at the live Core token.
- Provider credentials (`OPENAI_API_KEY` and the other names in
  `PROVIDER_ENV_NAMES`) are emptied unless the profile declares a provider
  capability, and `JARVIS_TESTLAB_NO_PROVIDERS=1` is set. They are emptied
  rather than removed because `load_project_environment` fills *missing* names
  from `.env`.
- Before anything else, the worker checks that `V2Settings.load()` resolves
  `runtime_root` and `data_root` inside the scratch. It refuses with
  `isolation_violation` otherwise. This is the mechanical guard: the supervisor
  sets the environment, the worker proves it landed.
- The scratch is built through no link. A run id is used once, so anything
  already at that path is a leftover or a trap: a junction planted at
  `<run>/runtime` would send the settings copy and the job file outside the run,
  before the worker's guard can run. The supervisor removes what it finds (a link
  is removed, never followed, as the Slice 02/03 stores do), creates the three
  directories fresh and re-checks each one.
- **The permanent `runtime/control-center-settings.json` is never written**
  (READINESS B4.2). It is read, the run-local overrides are applied to a copy in
  memory, and the copy is written into the scratch runtime directory. The
  snapshot of that effective document is what `TestRun.config_fingerprint`
  covers.
- Run-local overrides may only name a setting the manifest allowlists. They come
  from the scenario's `parameter.override` prelude (`ScenarioCheck.overrides`,
  the only place a scenario may change configuration) and from
  `RunRequest.overrides`. A prelude name that is a declared parameter overrides
  that parameter instead. The same name given twice with two different values is
  refused, never silently resolved. `apply_overrides` addresses a name that
  already exists at the top level as a flat key (this is how
  `control-center-settings.json` names voice settings) and any other dotted name
  as a path, creating the objects it needs.
- No device or provider is opened by this Slice: it ships no profile runner.
  Detecting that a device is actually free, and not held by the running voice
  process, belongs to Slices 08 and 09 (READINESS B9).

### Threat model

Runners are reviewed in-repo code running inside the worker process: the
environment, the artifact facade and the scratch rules prevent mistakes, not
malice. A runner can still open any path it can name, including the store, by
absolute path, and can still reach the store object through `__self__` of a bound
method or through `gc`. What the facade removes is the route a runner can take by
accident: no attribute of what it is handed is a store.

What the Test Lab guarantees is that a correct-looking runner cannot touch the
live runtime, another run or its own verdict by accident, and that anything which
does is visible: the record is cross-checked against the declaration, an
out-of-band conclusion is reported as an incident, and captured evidence is
redacted before it is stored. The boundary is code review plus the catalog lock,
not the process.

### Resource reservation

The capabilities of a run are `Catalog.resources_and_cost(diagnostic_id,
profile).requires`. The supervisor holds them for the whole run, so two runs
never contend for the provider, an audio device or the human. A `virtual`
profile declares nothing, so virtual runs never contend and only the
`max_concurrent_runs` bound applies. A run whose capabilities are held waits
(`testlab.run.waiting`); after `max_queue_wait_s` it is refused with
`resource_wait_timeout` rather than waiting forever.

`check_profile_permission` is the authorization gate and reservation is the
contention gate: a run needs both.

Queue-wait time accrues only while a run is genuinely blocked: no free slot, or
a capability held. A run that never got a chance to be considered, because an
upkeep pass or another run's start held the start gate, accrues nothing and can
never be refused for a wait the supervisor itself caused.

**One supervisor per work root.** `start()` takes an exclusive OS lock on
`<work_root>/.supervisor.lock` and holds it until `aclose()`; a second supervisor
on the same work root refuses to start with `testlab_supervisor_work_root_busy`.
Two supervisors are not supported: between `queued -> running` and the worker
taking its own lock there is a window in which the second would see a live run as
abandoned and reap it. The kernel releases the lock when a supervisor dies, so the
next one starts normally.

### Timeout, cancellation and kill

| Bound | Default | Crossed |
|---|---|---|
| `startup_timeout_s` | 60 s | Spawn to first heartbeat: killed, `errored` / `worker_startup_timeout` |
| `heartbeat_timeout_s` | 30 s | A started worker goes silent: killed, `errored` / `worker_unresponsive` |
| declared `max_duration_s` | the profile's | Run budget, from the first heartbeat: `timed_out` / `run_timeout` |
| `cancel_grace_s` | 5 s | Between the stop marker and the tree kill |
| `max_queue_wait_s` | 600 s | Queued without its resources: `errored` / `resource_wait_timeout` |
| `max_run_duration_s` | none | Operator cap over the declared duration |

The run budget is measured from the worker's first heartbeat, so interpreter
startup does not eat into the declared duration. The worker holds the same budget
from the moment it calls the runner, which is slightly later (its catalog load
sits in between), so a timed-out run usually produces a real `run_timeout` result
before the cancel grace expires; the supervisor's kill is the backstop. When the supervisor initiated the stop, its reason decides the status,
whatever the worker wrote, so the record says what actually stopped the run.

Cancellation is cooperative first: `cancel.json` appears, the worker notices it
on its next heartbeat tick, `RunContext.cancelled` is set, `RunCancelled`
propagates out of the runner and the worker writes a `cancelled_by_caller`
result. A runner that ignores it is killed after the grace, and the detail then
says the process tree was killed. A queued run is cancelled immediately, with no
worker started at all.

Containment is `jarvis/runtime/owned_process_tree.py::OwnedProcessTree` on
Windows: the worker is created suspended, assigned to a Job Object with
`KILL_ON_JOB_CLOSE` and no breakaway, then resumed. Killing the job kills the
worker and everything it started, and the kernel kills the whole tree if the
supervisor itself dies. The documented POSIX fallback is `start_new_session=True`
plus `os.killpg`; a process group is not killed when the parent dies, so on
POSIX an orphaned worker can outlive its supervisor — adoption handles that by
refusing to touch a run whose worker lock is still held.

On this host the venv `python.exe` starts the real interpreter as a further
process, so the recorded pid may be that launcher's. Liveness therefore never
rests on a pid (pids are reused anyway): the worker lock is the test.

### Orphan adoption

`start()` lists every `queued` and `running` run and finishes it, so no run is
left `running` by a supervisor that died:

- the worker lock is acquired with a short timeout. It is an OS lock released by
  the kernel when its holder dies, so acquiring it proves no worker is running
  that id;
- **lock held**: a live worker owns the run. Nothing is touched and nothing is
  killed by pid; the run is reported in `AdoptionReport.active_elsewhere`;
- **lock free with a `result.json`**: the run is concluded from that result, as
  the dead supervisor would have done (`recovered`);
- **lock free, `running`**: `errored` / `worker_lost`;
- **lock free, `queued`**: `errored` / `run_abandoned` — it never started, and
  the grant it was authorized under did not survive its supervisor;
- scratch directories with no non-terminal run are removed.

A terminal time is clamped up to the run's `started_at`: an adopting supervisor's
clock may read earlier than the one that started the run, and `TestRun` refuses a
`finished_at` before `started_at`. `AdoptionReport.reaped` counts only runs whose
terminal write succeeded; one the store refused is in `failed` with its refusal
code. A report claiming a run was finished while it is still `running` is worse
than no report.

### Maintenance

`remove_stale_temporaries` and retention are scheduled here (Slice 02 built both
and scheduled neither). A pass runs every `maintenance.interval_s`, and only
when the supervisor has **no active run**: it takes the same lock the dispatcher
takes to start a run, so no run of this supervisor can be writing while the sweep
walks the store. A run submitted during a pass therefore waits for it (which is
why a sweep must stay short) and starts the moment it ends, because the pass
wakes the dispatcher on its way out. This is what keeps the documented sweep-versus-put race
(an empty subdirectory removed between the `mkdir` and the write, reported as a
retryable `testlab_store_io`) out of the run path. Retention selects terminal
runs only, `apply_retention_plan` re-checks under the run lock, and the
supervisor additionally removes the ids it holds from the plan before applying
it. Retention stays disabled unless enabled explicitly.

### Failure codes

`RunFailure.code` values the execution path produces (`jobs.FAILURE_CODES`). How each one READS to a caller is the table in "Outcomes":

| Code | Status | Meaning |
|---|---|---|
| `permission_denied` | `errored` | The grant does not authorize the profile (denials in the detail) |
| `resource_wait_timeout` | `errored` | Queued too long without its capabilities |
| `worker_spawn_failed` | `errored` | The scratch or the process could not be created |
| `worker_startup_timeout` | `errored` | No heartbeat within `startup_timeout_s` |
| `worker_unresponsive` | `errored` | A started worker stopped beating |
| `worker_crashed` | `errored` | Exited with no result (the exit code is described in the detail) |
| `worker_lost` | `errored` | Adopted: `running`, no live worker, no result |
| `worker_active_elsewhere` | — | Adoption report only: the run was left alone |
| `run_abandoned` | `errored` | Adopted: queued by a supervisor that is gone |
| `run_concluded_out_of_band` | — | Diagnostic only: a terminal record the supervisor did not write |
| `run_timeout` | `timed_out` | The declared duration was exceeded |
| `cancelled_by_caller` | `cancelled` | A caller, or the supervisor stopping, asked it to stop |
| `worker_result_invalid` | `errored` | The result file exists but does not decode, or names another run |
| `result_contradicts_spec` | `errored` | `check_run_against_spec` refused the completed run |
| `worker_job_invalid` | `errored` | The job file could not be read or decoded |
| `isolation_violation` | `errored` | The worker's roots are not inside the run scratch |
| `catalog_unavailable` | `errored` | The catalog could not be loaded, or the declaration drifted |
| `runner_unavailable` | `errored` | Reserved, unregistered, or mismatched implementation name |
| `runner_failed` | `errored` | The runner raised something unforeseen, or its measurements are invalid |
| `supervisor_stopped` | `cancelled` | The supervisor stopped while the run was queued or running |
| `measurement_unavailable` | `errored` | Slice 07: the runner could not obtain a measurement the declaration needs (it raised `MeasurementUnavailable`) |
| `scenario_expectation_unmet` | `errored` | Slice 07: an evaluable `expect.*` step disagreed in a diagnostic that cannot carry the count |

Supervisor refusals raised to the caller use `testlab_supervisor_request_invalid`,
`testlab_supervisor_stopped`, `testlab_supervisor_unknown_run` and
`testlab_supervisor_work_root_busy`.

Captured evidence (the worker log, the stderr tail, every failure detail) is
redacted before it is stored, by `capture.redact_evidence` / `capture.failure_detail`.
Four passes: identifying text through the Slice 03 helper; the current user, host
and home fragments; the value FOLLOWING a credential-introducing token
(`Authorization:`, a bare `Bearer` / `Basic` scheme, and `api_key`, `secret`,
`password`, `passwd`, `token`, `client_secret`, `access_token` before a `=` or a
`:`); then any word whose own shape is a credential (the canonical
`SECRET_PREFIXES` of `conversation_event_trace`, imported rather than copied) and
any hexadecimal blob of 32 characters or more. The introducer pass exists because
a credential has no shape of its own: a real worker printed `Bearer QABEARERTOKEN`
and the token survived every shape-based rule. A worker's stderr is arbitrary
text, and a traceback can carry the very key its provider call refused.

Two limits are deliberate. A word must be 8 characters to be judged by its shape,
and the value after a bare `Bearer` / `Basic` must be 8 characters too, so prose
("basic checks passed", "the token budget is 500") survives and a very short
secret does not: short secrets are the name rule's job, not a text scan's. These
helpers live in `capture.py`, not in `redaction.py`, because they need
`identity_fragments()` and the credential vocabulary of an I/O module, and
`redaction.py` is a pure contract module that may import neither.

### Self-test fixture

`jarvis/testlab/selftest.py` declares `selftest.worker` v1 with one `virtual`
profile and the implementation `testlab.selftest.virtual`. It is a TEST FIXTURE,
not a seed diagnostic: it ships no manifest under `jarvis/testlab/official/`, and
a test asserts that no official manifest references a `testlab.selftest.` name.
Its `mode` parameter selects the path to exercise — `measure`, `sleep`, `hang`
(ignores the stop), `spawn_child` (starts a grandchild, to prove the tree is
killed), `crash` (hard exit with no result), `error`, `undeclared_metric` and
`forge` (tries to write its own verdict and to reach another run, then measures a
failing value). `write_selftest_catalog(root)` writes a one-diagnostic catalog for
a test.

`testlab.selftest.reserved` is a second fixture name, declared and deliberately
never registered. Once a Slice has implemented every real reservation of a profile
(Slice 06 did for `virtual`), it is what keeps the `errored` / `runner_unavailable`
path covered: `write_selftest_catalog(root, implementation=...)` points the fixture
profile at it.

Slice 06 turned the five `virtual` reservations into registrations through
`ImplementationRegistry.registering` (see "Virtual profile"). The four remaining
names (`testlab.scenario.audio`, `.live`, `.hardware_auto`, `.hardware_guided`)
are still `unavailable`, and a run of one is persisted `errored` with
`runner_unavailable` rather than refused at submission, so the attempt stays in
the record.

### Validation

```powershell
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/unit/test_testlab_supervisor.py tests/unit/test_testlab_supervisor_jobs.py tests/integration/test_testlab_worker.py
```

The integration file starts real processes: one per test, two in the tree-kill
test (the worker and its grandchild).

## Virtual profile

`jarvis/testlab/virtual/` is the `virtual` execution profile: the **production
voice path**, mounted in memory and off the network, with a small, named set of
controlled doubles. It is the async conversation harness
(`tests/integration/async_conversation_harness.py`) moved into the product, because
production code may not import from `tests.`
(`tests/unit/test_v2_architecture.py::test_production_never_imports_test_frontends`).
The test module is now a re-export: same names, same semantics, same
`voice_stack(tmp_path, monkeypatch, ...)` call. `tests/fakes/audio_device.py` is a
re-export of `jarvis/testlab/virtual/devices.py` for the same reason.

| Module | Role |
|---|---|
| `patching.py` | `PatchStack`: `setattr` + restore with no pytest. `voice_stack` accepts it or a `monkeypatch`. |
| `devices.py` | `BufferedOutputStream` / `BufferedInputStream`, the controlled native streams. |
| `harness.py` | The doubles, `VoiceStack` and `voice_stack(...)`. |
| `echo_guard.py` | `VirtualEchoGuard`, the duplex-capture double (acoustic state only). |
| `journal.py` | `TraceRecordingJournal`: the in-memory view **and** `runtime/trace.jsonl`. |
| `executor.py` | `VirtualExecutor`: the primitive-to-harness mapping. |
| `runners.py` | The four seed runners and the generic scenario runner. |
| `registry.py` | The lazy factories `catalog_implementations()` registers. |

### What is real and what is a double

Real: `JarvisCoreApplication`, the local HTTP/WebSocket protocol, `BrainOrchestrator`,
`SpeechScheduler`, `PersistentVoiceRuntime`, `RealtimeConversationBridge`,
`SoundDeviceRealtimeAudio`'s admission, epochs, gain and byte accounting, the
conversation state store, and the `RuntimeJournal` format.

Doubles, and only these:

| Double | Replaces | What it decides |
|---|---|---|
| `FakeRealtimeSession` | the provider Realtime session | nothing: it relays the events the scenario pushes and records `speak()` |
| `FakeAudio` + `ImmediateOutputStream` | the PortAudio streams | nothing: the native write consumes immediately |
| `ScriptedBrainBackend` | the strong model | nothing: `run_turn` returns only when the scenario releases it |
| `VirtualEchoGuard` | the duplex capture (`jarvis/audio/duplex.py`) | nothing: it reports whether Jarvis is the far end |
| `FakeWakeWord` | the wake-word detector | nothing: it yields the keyword the run pushes |

`VirtualEchoGuard` deserves its own note. `_barge_in_allowed()` has no witness when
the audio has no capture (`has_echo_guard` false) and then believes the provider,
so a harness without a guard confirms **every** echo candidate and
`voice.self_echo` could not tell a correct stack from a broken one. The double is
fed by the production writer (`push_reference` per output block, `clear_reference`
on an output stop), so "Jarvis is audible" is observed rather than declared; the
decision that follows — `voice.barge_in` or `voice.barge_in_ignored` /
`speech_started_behind_echo_guard` — stays entirely in `realtime_audio.py`.

**The guard reads no clock.** It first held the gate closed for 2 s of
`time.monotonic` after the last output block, which made it the one part of the
profile that depended on wall time: a 2.2 s stall of a loaded host between the last
block and the candidate reopened the gate and turned a correct stack into a
`voice.self_echo` failure. The far end is now pure state — on from the first
reference block, off on `clear_reference()` — so no pause can change a verdict.
Nothing is lost: the bridge consults the guard only `if self.continuous and
self._output_live()`, so "is an output live" is already its own precondition, and a
conservative `far_end_recent` outside a live output only tightens input admission.

**The consequence, stated plainly: the latched state never decays.** The real duplex
guard reopens on its own once the far end goes quiet; this one only reopens on
`clear_reference()`, which the production writer calls when an output is *stopped* and
not when one simply finishes. After the first written block a virtual run therefore
reads "Jarvis is the far end" for the rest of the session. That is safe for what reads
it today — `_barge_in_allowed()` is gated on a live output, `near_playback` only becomes
more conservative, and the capture report is descriptive — and it is what makes the
verdict independent of host load. A later Slice that reads `echo_guard_open`,
`far_end_recent` or `near_end_observed` for anything else must know that in a virtual
run those fields are latched, not observed moment to moment, and must not read a closed
gate as evidence that Jarvis is audible *right now*.

### Primitive-to-harness mapping

Every primitive the `virtual` profile declares has a handler, so
`missing_handlers(DEFAULT_PRIMITIVES, VIRTUAL, HANDLED)` is empty (pinned by a
test). `audio.inject` is acoustic and is not a virtual primitive; Slice 08 owns it.

| Primitive | What the virtual profile does |
|---|---|
| `user.turn` | commits a transcript built from `content_tag`, waits for the turn submission, takes the brain turn |
| `user.speech` | same, with the authored `text` |
| `user.interrupt` | `realtime.speech_started`, then the authored turn |
| `brain.hold` | `start_work(work_id)` on the brain turn in flight |
| `brain.ready` | `say(result_tag, RESULT)` + `complete_work` |
| `brain.release` | `finish()` on the held turn, then settles |
| `scheduler.enqueue` | through the brain turn in flight (Core stamps the real source); with no turn, publishes `brain.speech.requested` on Core's bus with the scenario's own `SpeechSource` |
| `provider.output_started` | `realtime.output_started` |
| `provider.transcript_final` | `realtime.assistant_transcript` built from `generated_tag` |
| `provider.output_done` | `realtime.audio_done` + `realtime.response_done` with the declared status |
| `provider.cancel_rejected` | arms the fake provider to refuse the next cancel of that output (observed later as `voice.barge_in_degraded` / `barge_in_cancel_failed`) |
| `provider.session_closed` | closes the fake session; any later stimulus fails the run |
| `owner.candidate` | `realtime.speech_started` (a barge-in candidate opens) |
| `owner.rejected` | **observation**: waits for `voice.barge_in_rejected` / `voice.barge_in_ignored` |
| `owner.confirmed` | **observation**: waits for `voice.barge_in` / `voice.barge_in.owner_confirmed` |
| `device.output_busy` | opens the named output on the surface, optionally plays `played_ms` |
| `device.consume` | feeds `played_ms` of provider audio in 100 ms blocks |
| `device.release` | `realtime.audio_done` (unless `provider_still_active`) + `realtime.response_done` |
| `control.stop` | stops the voice runtime the way production does |
| `control.checkpoint` | settles and records the checkpoint id |
| `time.wait` | advances the virtual clock, then settles |
| `parameter.override` | verifies the prelude was actually applied to this run |
| `expect.event` | counts Conversation Events of that type at the end of the run |
| `expect.metric` | evaluates the ad-hoc assertion on the final metrics |
| `expect.assertion` | compares the declared assertion's outcome |

Two rules make the mapping honest:

- `owner.rejected` and `owner.confirmed` are **not stimuli**. The owner decision is
  the code under test, so the executor waits for it and fails the run when the stack
  decided otherwise. A scenario that declares a confirmation the stack never makes
  ends `steps[i] owner.confirmed: a confirmed barge-in never happened within Ns of
  run budget`, never a silent pass.
- Any step the harness cannot perform raises `testlab_virtual_step_failed` naming
  the step index, the primitive, what was expected and what was observed.

The same rule governs the scripted runners: **a stimulus the stack never answers is
not evidence of correctness.** `voice.self_echo` waits, after each injected onset, for
the stack to record a decision (`voice.barge_in`, `voice.barge_in.owner_confirmed`,
`voice.barge_in_rejected` or `voice.barge_in_ignored`) and fails the run when none
comes. Without that wait the seed passed vacuously on a bridge that ignores provider
VAD entirely: nothing confirmed, nothing rejected, every assertion green — a stack
that can never be interrupted looked perfect on the barge-in diagnostic.

Two limits of that wait, both deliberate:

- **It counts decision lines globally, from a snapshot taken just before the onset, not
  per onset.** The journal's barge-in lines carry no onset correlation id, so there is
  nothing to join them on. In principle a straggler decision belonging to the *previous*
  onset could arrive late and satisfy the next wait; the candidates are injected one at
  a time and each wait returns on the first new line, so this needs a decision that
  outlives its own injection. The guard is a check against *silence*, not a per-onset
  accounting.
- **It is satisfied by the journal, not by the reasoning behind it.** A stack that emits
  a `voice.barge_in_ignored` line without ever consulting the echo guard passes: the
  onset was answered, the output genuinely was not cut, and both metrics are what the
  manifest asks for. That is the diagnostic's contract — it judges the decision lines
  and the output's fate, not the code path that produced them. Proving that the guard
  is what *caused* the refusal is a code-level claim, and the mutations that remove the
  guard (`a`, `a2`) are what cover it.

`BARGE_IN_DECISION_KINDS` also does not cover the **Solo Owner** path. Under
`BargeInAuthority.OWNER` the bridge answers a provider onset with
`voice.barge_in.provider_advisory` (it correlates, it never cuts), which is not in the
set, so the wait would time out and the run would fail structurally instead of
measuring. That is unreachable today — owner authority needs an `owner_source` the
harness does not provide, so a virtual run is always in the acoustic-authority branch —
but a later profile or scenario that runs with owner authority must widen the set (and
rethink what "a false barge-in" means there) before `voice.self_echo` can judge it.

### Journal and session shape

Both sinks — the voice runtime's and Core's — are `TraceRecordingJournal`, which
appends to `<runtime_dir>/trace.jsonl` through the real `RuntimeJournal`. A run
therefore leaves the live runtime's own evidence: `voice.start`, `voice.connecting`,
`voice.active`, the `voice.speech.*` stages, `voice.latency.*`, `voice.barge_in*`,
`core.brain.*`, and `voice.stop` when the run closes the session. Every line the
scheduler and the bridge write carries `session_id`, set from the run id
(`<run_id>-s<n>`), because the Realtime session double now has one.

The trace is committed as a `trace_excerpt` artifact named `trace.jsonl`, **after**
the stack is torn down, so it holds the lines Core writes while stopping.

A `DiagnosticBundle` captured over that trace with
`SessionSelector(session_id=f"{run_id}-s1")` segments into exactly one voice
session, with no coverage warning (pinned by a test). Capturing the bundle and
setting `TestRun.bundle_id` is **not** done by a runner: a runner may not write the
run record, and `WorkerResult` carries no bundle id. That composition belongs to
Slice 10/12, and it has everything it needs — the stored `trace.jsonl` and the
session id derived from the run id.

### Determinism, cancellation and deadlines

- No `sleep` is ever a synchronization. Every wait is a condition:
  `VirtualExecutor.wait_for`, `runners.wait_condition`, and `_settle()`, which waits
  for the journal to go quiet rather than for a duration.
- Budgets come from the run: `min(STEP_TIMEOUT_S, RunContext.remaining_s)`. A loaded
  host makes a virtual run slower, not wrong, and only the supervisor's deadline ends
  it. The harness's own `TIMEOUT_S` (30 s) bounds the pytest tests, not Test Lab runs.
- The only real waits are stimuli a metric measures: the scripted brain's thinking
  time in `voice.queue_latency`. It goes through `RunContext.sleep`, which returns on
  a cancel.
- `RunContext.check_cancelled()` runs between scenario steps, inside every wait and
  inside every playback block, so a cancel ends a run cooperatively (seconds) long
  before the cancel grace and the forced tree kill, and an exhausted deadline ends it
  as `timed_out` — both proven with real workers.
- `at_ms` is the scenario's virtual timeline: it orders steps and dates what the
  scenario authored (for example `speech.stale_wait_ms`). It advances the injected
  clock; it never waits.

Two known heuristics, deliberate and documented rather than hidden:

- **`_settle()` waits for quiescence**, defined as `SETTLE_QUIET_POLLS` consecutive
  polls with no new journal line. It is a "the stack has finished reacting" proxy, not
  a proof; a stack that pauses longer than the poll window between two lines would be
  considered settled early. Every step that has an observable outcome waits for *that*
  outcome instead, so quiescence only ever backs steps with none (`time.wait`,
  `control.checkpoint`).
- **`voice.self_echo` spreads its echo candidates** over the output blocks with a
  plain `blocks // echoes` stride. Where in the output a candidate lands is not a
  contract; what the diagnostic asserts is the decision the stack made on each one.

### Seed runners and their metrics

Each runner emits exactly the metrics its manifest declares, with the declared
units, and nothing else — the supervisor stores a run with an undeclared metric as
`errored` / `result_contradicts_spec`.

| Diagnostic | Implementation | Metrics |
|---|---|---|
| `voice.self_echo` | `voice.self_echo.virtual` | `barge_in.false_confirmed_count` (count, `voice.barge_in` + `voice.barge_in.owner_confirmed`), `barge_in.rejected_count` (count, `voice.barge_in_rejected` + `voice.barge_in_ignored`), `output.completed` (boolean, terminal is `voice.speech.completed`), `output.played_ms` (ms, the device's own `played_output_ms`) |
| `speech.payload_integrity` | `speech.payload_integrity.virtual` | `speech.scripted_count`, `speech.delivered_count`, `speech.payload_mismatch_count`, `speech.replayed_payload_count`, `speech.undelivered_count` (all counts), from the scripted `SpeechRequest`s against what the surface received |
| `speech.stale_supersession` | `speech.stale_supersession.virtual` | `speech.superseded_count` (count, what the stack **admitted**), `speech.stale_delivered_count` (count, keyed on candidate identity — see below), `speech.latest_intent_delivered` (boolean, highest `intent_epoch`), `speech.stale_wait_ms` (ms, **virtual** time from the candidate's enqueue to the moment its staleness was resolved — its supersession, or its delivery when it was spoken anyway) |
| `voice.queue_latency` | `voice.queue_latency.virtual` | `speech.queue_free_to_started_ms` (ms, worst case from the later of the speech's queueing and the previous delivered speech's terminal, to its start), `speech.started_to_first_audio_ms` (ms, start to `voice.latency.provider_first_pcm`), `user_turn.end_to_first_audio_ms` (ms, `voice.brain_turn_submitted` to the first PCM, brain time included), `speech.delivered_count` (count of speeches that reached `voice.speech.completed` **and** have a `voice.latency.provider_first_pcm` line — see the note below on what that does and does not prove) |

**A missing join is omitted, never reported as 0.** A run where no provider audio was
ever relayed used to measure `started_to_first_audio_ms = 0` and pass every
assertion — the worst possible stack scored the best possible number. An omitted
metric makes its assertion `missing`, the verdict inconclusive and the run `errored`
(`assertions_inconclusive`): a diagnostic that could not measure says so instead of
certifying silence.

**`speech.delivered_count` is an evidence count, not an acoustic one.** It means
"completed, and the journal carries a `voice.latency.provider_first_pcm` line for it" —
no more. Suppress only that line while the audio really is relayed and the count reads
0 and the run is inconclusive: the metric cannot tell "nothing was played" from "the
producer stopped saying that something was played". That verdict is the honest one —
the diagnostic could not measure — but the number must not be read as proof that a user
heard, or did not hear, anything. Whether sound actually left a speaker is the `audio`
and `hardware` profiles' question.

**Staleness is keyed on candidate identity, not on the label the stack applied.**
`speech.stale_delivered_count` counts a candidate delivered after it became stale,
where stale means either the stack admitted it (`voice.speech.superseded` / `.expired`)
**or** the scheduler had already seen a candidate of a later `intent_epoch` — the
epochs are the scenario's own declaration and the moment the later candidate reached
the scheduler is a journal line, so both halves are observed fact. Counting only the
admitted half made the seed blind to its own incident: a stack that never noticed the
revision and spoke the old acknowledgement 35.9 s late measured 0. A candidate already
spoken before the revision reached the scheduler was never stale and is not counted.
`superseded_count` stays the count the stack admitted; the two disagreeing —
`superseded_count = 0` with `stale_delivered_count = 1` — is itself the finding.

Two boundaries a scenario author has to know:

- **A revision counts only once the later candidate has reached the scheduler**, that
  is, once the journal shows a `voice.speech.queued` or
  `voice.speech.presentation_decided` line for it. A candidate declared in the scenario
  but never seen by the scheduler revises nothing, and a candidate delivered before that
  moment was still current when it spoke and is not counted stale. This is what keeps
  the measure grounded in observed fact rather than in the scenario's text, and it is
  also why arrival order alone cannot fool it.
- **A scenario whose `scheduler.enqueue` steps declare no `intent_epoch` silently
  disables the identity half of the rule**: with no epochs there is no "later intent",
  so only the supersessions the stack admitted are counted. The seed cannot pass by
  accident in that state — `speech.latest_intent_delivered` derives from the same
  epochs and is `false` with none, so `latest_intent_wins` fails — but the failure then
  names the wrong thing. `intent_epoch` is optional in the primitive schema because the
  replay DSL made it so; for this diagnostic, treat it as required.

`speech.payload_integrity` compares the scripted payload with the delivered one and
never uses `voice.state.spoken_diverged`: that producer signal compares raw strings
and fires on ordinary transcription noise (see
`tasks/jarvis-category2-test-lab/Issues/speech-payload-integrity-needs-normalized-measure.md`).

`testlab.scenario.virtual` is the generic ad-hoc runner, and its **measurement
contract** (Slice 07) is exactly `SCENARIO_METRICS`: `scenario.steps_performed`,
`scenario.checkpoints_reached`, `scenario.expectations_declared` and
`scenario.expectations_failed_count`. A diagnostic declaring anything else fails with
`testlab_virtual_run_failed` rather than storing a verdict derived from nothing. The
last of the four is what lets an ad-hoc diagnostic FAIL: declare a blocking
`scenario.expectations_failed_count eq 0` and an `expect.*` step that disagrees becomes
an ordinary measured verdict (see "The `expect.*` verdict rule"). A diagnostic that does
not declare it ends `inconclusive` on an unmet expectation instead of dropping it.

Each seed's failure path is proven, not assumed: a real confirmed barge-in, a
corrupted delivered payload, an intent that is never delivered, and a first audio
past the declared threshold each turn the corresponding blocking assertion `failed`.

### What the virtual profile cannot prove

- **Acoustics.** No room, no speaker, no microphone, no real echo canceller. The
  virtual echo guard states whether Jarvis is the far end; whether a real AEC would
  have separated a real voice from real echo is the `audio` and `hardware` profiles'
  question.
- **Real provider timing.** `speech.started_to_first_audio_ms` measures the path from
  the speech start to the first PCM the bridge relayed. The provider's own generation
  latency, its jitter and its cancel behaviour are the `live` profile's.
- **Device contention and native failures.** The output stream consumes immediately
  and never fails unless a test asks it to. Real device ownership, the running
  Jarvis holding the laptop microphone, drains and underruns belong to
  `hardware:auto` (READINESS B9).
- **Transcription and addressing.** The provider transcript is authored text, so an
  addressing classification is the production classifier's answer on that text, not
  evidence about real speech. `user.turn` / `user.speech` therefore *verify* a
  declared `addressing`, and never impose it.
- **That a measure means what its name suggests.** Three of them are narrower than they
  read, and each says so where it is defined: `speech.delivered_count` counts evidence
  lines, not sound; the unanswered-onset guard checks that the stack answered, not why;
  and `VirtualEchoGuard`'s far-end state is latched for the session rather than decaying
  like the real duplex guard.
- **A verdict beyond its metrics.** A runner measures; only a declared blocking
  assertion fails a run. Slice 07 closed the two gaps this used to leave: an
  `expect.*` step that disagrees is now a measured count an ad-hoc diagnostic can
  assert on (so it can end `failed`), and a run the profile refuses to judge has its
  own shape — a missing latency join ends `errored` / `assertions_inconclusive`, an
  unanswered barge-in onset ends `errored` / `measurement_unavailable`, and both
  classify as the outcome `inconclusive` while keeping distinct codes (see
  "Outcomes"). What remains true is that the virtual profile still cannot produce a
  verdict its own declared metrics do not carry.

### Validation

```powershell
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/unit/test_testlab_virtual.py
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/integration/test_testlab_virtual_runners.py tests/integration/test_testlab_virtual_runs.py
```

`test_testlab_virtual_runners.py` runs the stack in process (no subprocess) and owns
the failure paths, the cancel and the journal/bundle shape.
`test_testlab_virtual_runs.py` starts one real worker process per test.

The harness's existing consumers must keep passing unchanged, in their own
foreground chunk (see
`tasks/jarvis-category2-test-lab/Issues/voice-harness-wall-clock-flake-under-load.md`):

```powershell
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/integration/test_v2_async_conversation.py tests/integration/test_voice_replay_regressions.py tests/integration/test_voice_replay_safety_regressions.py
```

## DiagnosticBundle

A normalized, versioned evidence document built mechanically from one real
Jarvis session, so humans and agents read sections instead of re-reading raw
logs. No model is involved: every field is a deterministic function of the
evidence read, and every derived item names the evidence that produced it.

Modules: `bundle.py` (schema, codec), `bundle_rules.py` (anomaly rules),
`bundle_builder.py` (pure builder), `bundle_capture.py` (I/O capture service),
`filesystem_bundle_store.py` (storage), port `store.BundleStore`.

### Document (`jarvis.testlab.bundle`, schema version 1)

Every object has exactly its fields (strict codec: unknown or missing fields are
rejected). Times are wire times, ids are opaque ids (`voice_state.state_id`),
codes are `[a-z][a-z0-9_.-]{0,63}`. The encoding is canonical JSON, at most 8 MiB.

| Field | Content |
|---|---|
| `schema`, `schema_version` | `jarvis.testlab.bundle`, `1` |
| `bundle_id` | `format_bundle_id(<id time>, content_fingerprint[:16])` (Identity and determinism) |
| `content_fingerprint` | `content_fingerprint` of the document without `bundle_id`, `content_fingerprint` and `capture` |
| `capture` | Capture context, outside the fingerprint: `captured_at` (injected), `code {status: capture_time\|unknown, git_revision, dirty}`, `config {status: capture_time\|unknown, fingerprint}` (the Slice 02 `CodeIdentity` and `ConfigSnapshot.fingerprint` when the caller supplies them; they describe the capturing checkout, not necessarily the session's) |
| `session` | `selector {conversation_id, session_id, start, end}`, `conversation_ids`, `session_ids` (≤ 64 each), `started_at`, `ended_at`, `duration_ms` (extent of all evidence read) |
| `identity` | Configuration found in the evidence: `status evidence\|unknown`, `voice_configuration_ids` (64 hex, from `voice.stack` and reports), `architectures` (`arch` of `voice.stack`/`voice.active`, reports), `evidence` |
| `coverage` | What was read (Coverage) |
| `turns` | `{item_id, actor user\|mouth\|brain, kind user_turn\|turn_accepted\|turn_failed\|message_published\|speech\|reflex, at, status, conversation_id, session_id, turn_id, correlation_id, speech_id, outcome_id, content, content_truncated, evidence}` |
| `speech` | `{speech_id, conversation_id, correlation_id, work_id, parent_speech_id, chunk_speech_ids, output_ids, kind, priority, outcome, reason, played_ms, queue_wait_ms, requested_at, queued_at, dispatched_at, started_at, ended_at, codes, terminals [{outcome, at, reason, evidence}], spoken_divergences, state_divergences, spoken_diverged_at, evidence}` |
| `playback` | `{output_id, speech_id, conversation_id, source, started_at, provider_chunk_at, first_write_at, ended_at, end_status, drain_ms, evidence}` |
| `barge_in` | `{episode_id, started_at, ended_at, outcome, authority, trigger, speech_id, output_id, played_ms, stop_latency_ms, device_stopped, codes, jarvis_speaking, audible, next_user_activity_ms, next_user_activity_basis, evidence}`. `audible`: `played_ms > 0`, or a `voice.latency.first_audible_write` / `output_first_write` on the episode's output (or its speech's outputs) before the episode; false when neither and the episode names an output or a `played_ms`. `next_user_activity_ms` and `next_user_activity_basis`: User activity below |
| `provider` | `{at, event, code, status, provider, conversation_id, evidence}` |
| `user_activity` | `{at, event speech_started\|input_submitted\|transcript\|turn_submitted\|turn_completed\|transcript_dropped\|manual_submit, conversation_id, code, near_playback, evidence}` (timing, ids and code tokens such as `addressing`; never text) |
| `lifecycle` | `{at, event started\|stopped\|output_stopped\|device_closed\|native_failed\|stream_closed\|timeout, code, conversation_id, session_id, evidence}` |
| `brain` | `{at, event replies_superseded\|turn_slow\|turn_over_budget\|work_completed, conversation_id, correlation_id, work_ids, measure, ms, budget_ms, evidence}` |
| `usage` | `{at, conversation_id, session_id, input_tokens, output_tokens, duration_seconds, source, evidence}` (token counts only) |
| `latency` | `{join_id, speech_id, correlation_id, stages [{stage, at, evidence}], measures [{name, ms, from_stage, to_stage}], reported [{measure, ms, evidence}]}` |
| `aggregates` | `trace_summary`: `trace_summary.summarize` output flattened to `[{path, value}]` (≤ 512, or null); `voice_session_reports`: `[{session_id, architecture, configuration_id, session_fingerprint, terminal_status, trace_evidence_complete, latency [{name, count, min_ms, max_ms, mean_ms}], counts [{name, value}], evidence}]` |
| `anomalies` | `rules [{rule_id, version, evaluated, skipped_reason, thresholds [{name, value}]}]`, `findings [{rule_id, rule_version, at, subject_kind, subject_id, measured [{name, value}], evidence}]` |
| `references` | `conversation_events [{ref, sequence, event_type, occurred_at, visibility}]`, `trace_lines [{ref, offset, ts, kind, level}]`, `voice_session_reports [{ref, sha256}]` |

Vocabularies:

- speech `outcome`: `dropped` (brain request, no voice-side record although
  voice-side evidence was read: the journal, or any `mouth.*` event), `unknown`
  (request only, no voice-side evidence), `chunked` (delivered as paragraph
  chunks, see `chunk_speech_ids`), `queued`, `started`, `spoken`,
  `interrupted`, `superseded`, `stale` (`*.speech.expired`), `failed`. A speech
  with terminals takes the earliest one; all are listed in `terminals`, one
  entry per outcome with every reference that observed it;
- barge-in `outcome`: `confirmed`, `rejected`, `ignored`, `degraded`,
  `advisory`, `unresolved` (a pending candidate never resolved);
- provider `event`: `connecting`, `connected`, `disconnected`, `error`,
  `keepalive_failed`, `refused`, `failure`, `response_silent`,
  `cancel_requested`, `models_failed`.

Section caps (`SECTION_LIMITS`): turns 4096, speech 2048, playback 2048,
barge_in 1024, provider 1024, user_activity 4096, lifecycle 1024, brain 2048,
usage 1024, latency 2048, findings 1024, segments 256, conversation event
references 20000, trace line references 20000. Evidence lists hold at most 32
references. Items past a cap are dropped after sorting and counted in
`coverage.limits` (`{section, kept, dropped}`). Every list is sorted (turns by
`at` then id, speech by first known time then id, episodes by start, references
by sequence or offset), so equal inputs give equal bytes.

### Provenance

A reference is one of:

- `cev-<64 hex>`: a Conversation Event id;
- `trace:<byte offset>`: the `RuntimeJournal` line starting at that offset (the
  journal is append-only, so an offset is stable);
- `report:<16 hex>`: a voice session report (first 16 hex of its sha256).

Every turn, speech, terminal, playback, episode, provider, user activity,
lifecycle, brain and usage item, latency stage, reported measure, report
aggregate and finding carries at least one reference, and every reference
resolves in `references` (codec, `testlab_reference_invalid`). A reference record
holds ids, offsets, times, kinds and levels only, never a journal message or
`data` payload.

### Codec consistency

Beyond shapes, the codec refuses (`testlab_reference_invalid`) a document whose
parts disagree, even when its fingerprint and id were recomputed after the edit:

- a rule row repeated, or whose `skipped_reason` is not set exactly when
  `evaluated` is false;
- a finding whose `rule_id` has no row, whose row is not evaluated, or whose
  `rule_version` differs from the row's; a `measured.threshold_ms` that differs
  from the row threshold named by its `measure`;
- a speech whose `outcome` contradicts its terminals and stages (a terminal
  outcome must be the earliest terminal with `ended_at` at its time; `chunked`
  needs chunk ids; `started` a start; `queued` a queue stage and no start;
  `dropped`/`unknown` only a request); `spoken_diverged_at` set without a
  spoken divergence, or the reverse;
- references to a source whose coverage status is not `available`, `empty` or
  `truncated`; a conversation event count that differs from its references; a
  segment count that differs from the listed plus dropped segments;
- segments out of time order, overlapping, ending before they start, with an
  index other than their position, or without items; warnings that disagree with
  the coverage they summarize (`multi_session_selection` exactly when an id-only
  selector has more than one segment, `long_selection` exactly when it spans more
  than 6 h, `open_window` exactly when `window_open`, `torn_tail` exactly when
  `torn_tail`);
- a finding whose subject does not show the rule's signature: `voice.self_barge_in`
  on an episode that is not a confirmed, speaking, audible episode with no user
  activity within the window (and the same `next_user_activity_ms`);
  `speech.missing_delivery_outcome` on a speech with a terminal, another state, or
  a `segment_end` other than its segment's closing kind;
  `speech.delivered_after_supersession` on a speech never superseded or expired;
  `speech.duplicate_payload` on a speech never started; `latency.above_threshold`
  on a join without that measure, another `ms`, or a value not above the row
  threshold; `events.reconstruction_anomaly` on an unreferenced event;
- a list out of its documented order (turns, speech, playback, barge-in, provider,
  user activity, lifecycle, brain, usage, latency, findings, references), latency
  stages out of `LATENCY_STAGES` order, or a measure whose stages or `ms` differ
  from the difference of its stages.

### Coverage

Coverage makes absence of evidence explicit, so it is never read as evidence of
absence.

| Field | Content |
|---|---|
| `conversation_events` | `status`, `origin store\|export`, `events`, `skipped_rows` (stored rows that did not decode), `export_complete` (export trailer), `truncated`, `reason` |
| `runtime_journal` | `status`, `lines_in_window` (timed lines inside the window, or between the first and last line carrying the selected id), `lines_selected` (lines kept under the selection budget), `corrupt_lines`, `oversized_lines`, `untimed_lines` (counted over the physical scan range, see Capture service), `truncated`, `start_truncated` (older bytes not read), `torn_tail` (the file ends with a line without newline, not decoded), `window_open`, `stopped_by` (`window_end`, `file_end`, `max_bytes`, `max_lines`, `max_selected`), `reason` |
| `voice_session_reports` | `status`, `reports`, `reason` |
| `content` | `included`, `max_chars`, `items`, `truncated_items`, `redactions` |
| `limits` | Section caps hit |
| `segments` | `count`, `idle_gap_ms`, `dropped`, `items [{index, session_id, started_at, ended_at, end_kind, items}]` (Voice session segments) |
| `warnings` | `multi_session_selection`, `long_selection`, `open_window`, `torn_tail` (below) |

Source `status`:

| Status | Meaning |
|---|---|
| `available` | Read whole, something matched |
| `empty` | Read whole, nothing matched |
| `truncated` | A bound stopped the read |
| `missing` | File or database absent |
| `unavailable` | Present but unreadable: I/O error, invalid export, `conversation_events` table absent, a journal with no decodable line (`no_decodable_lines`) or no timed line (`no_timed_lines`) |
| `not_requested` | The caller did not ask for this source |

Reason codes: `trace_file_missing`, `trace_unreadable`,
`state_database_missing`, `state_database_unreadable`,
`conversation_events_table_absent`, `store_read_failed`, `export_file_missing`,
`export_unreadable`, `export_too_large`, `export_invalid`,
`reports_directory_missing`, `reports_directory_unreadable`,
`some_reports_unreadable`, `no_decodable_lines`, `no_timed_lines`.

Warnings:

| Warning | Meaning |
|---|---|
| `multi_session_selection` | An id-only selector (no window) spans more than one voice session segment. The bundle is built; rules stay inside each segment, but read it as several sessions. |
| `long_selection` | An id-only selector spans more than `MAX_SELECTION_HOURS` (6 h). |
| `open_window` | The requested window ends after the last journal line read (no line later than end plus tolerance yet), or after `captured_at`. A recapture may differ. |
| `torn_tail` | The journal ended with a line without newline, which was not decoded. |

### Voice session segments

The evidence (events and selected journal lines, in time order) is split into
voice session segments, and every rule horizon stays inside the segment of its
subject: the window after a barge-in, the grace before a missing outcome, the
next user activity, the previous output of a queued speech, the pair of a
duplicate payload. Evidence of a later session never decides a finding.

A new segment starts when:

- the previous segment was closed by a session end kind (`voice.stop`,
  `voice.failure`, `audio.device_closed`; consecutive end kinds of one shutdown
  close the same segment);
- an item carries a `session_id` other than the segment's;
- a session start kind (`voice.start`, `voice.connecting`) follows other
  evidence in the segment;
- the gap to the previous item exceeds `SEGMENT_IDLE_GAP_MS` (10 min) and the
  item does not belong to the segment's known session. An item belongs to it when
  it carries that `session_id`, when it carries none and the next identified item
  carries that `session_id` (`voice.speech_started` has no session id), or when it
  is an unidentified session end kind (`voice.stop` carries no ids). A long silence
  inside one identified session therefore stays one segment, and a speech left
  without outcome stays decidable up to the session end. The idle gap still splits
  segments whose session is unknown.

Segmentation reads the selected evidence only: it depends on the selection filter
(Selection budget), so an unselected kind never opens, closes or extends a
segment.

`coverage.segments` lists every segment (up to 256) with its session id, extent,
closing kind and item count. The thresholds are declared data in
`bundle_builder.py` (`SEGMENT_START_KINDS`, `SEGMENT_END_KINDS`,
`SEGMENT_IDLE_GAP_MS`, `MAX_SELECTION_HOURS`).

### Evidence sources

Journal kinds were inventoried on the live `runtime/trace.jsonl` (13 123 lines,
2026-09-03 to 2026-09-16) and in the current producers.

| Source | Kind or event type | Section |
|---|---|---|
| Conversation Events | `user.transcript.accepted` | turn `user:<correlation>` (public content) |
| | `brain.turn.accepted`, `brain.turn.failed` | turns `brain_accepted:<correlation>` and `brain_failed:<correlation>` (status: `source` or `code` attribute) |
| | `brain.message.published` | turn `brain_message:<outcome>` (public content) |
| | `brain.speech.requested` | speech `requested_at`, kind, priority. Its diagnostic text is read in memory for the duplicate rule only. |
| | `mouth.speech.queued`, `mouth.speech.started` | speech `queued_at`, `started_at`; turn `mouth:<speech>` (public content); `parent_event_id` links chunks to their request |
| | `mouth.speech.completed`, `interrupted`, `superseded`, `expired`, `failed` | terminals `spoken`, `interrupted` (`reason`, `played_ms`), `superseded`, `stale`, `failed` |
| | `mouth.reflex.started` | turn `reflex:<correlation>:<output>` |
| | every event | `reconstruct_conversation` anomalies (rule `events.reconstruction_anomaly`) |
| `RuntimeJournal` | `voice.speech.queued`, `voice.speech.dispatched` (`queue_wait_ms`), `voice.speech.started` | speech stages, turn `mouth:<speech>` |
| | `voice.speech.completed`, `interrupted` (`played_ms`), `superseded`, `expired`, `speak_failed` | speech terminals (a line without `speech_id` is attached through its `output_id`) |
| | `voice.speech.output_stalled` | speech `codes` |
| | `voice.brain_turn_submitted` | turn `user:<correlation>` (never content) |
| | `core.brain.turn_failed`, `core.brain.outcome_retained` | turns `brain_failed:`, `brain_message:` |
| | `voice.reflex.started` | turn `reflex:` |
| | `voice.output_started`, `voice.latency.provider_first_pcm`, `voice.latency.playback_attempted`, `voice.latency.output_first_write`, `voice.latency.first_audible_write`, `audio.drain_requested`, `audio.drain_result` | playback by `output_id`: `audio.drain_result` gives `end_status` and `drain_ms`; a `voice.barge_in` on the output ends it as `interrupted` |
| | `voice.barge_in_pending`, `voice.barge_in`, `voice.barge_in_rejected`, `voice.barge_in_ignored`, `voice.barge_in_degraded`, `voice.barge_in.owner_confirmed`, `voice.barge_in.provider_advisory` | barge-in episodes: the next confirmation or rejection within 30 s resolves a pending candidate; degraded, owner and advisory lines attach to a confirmed episode within 5 s, otherwise they stand alone |
| | `voice.connecting`, `voice.active`, `provider.disconnected`, `provider.error`, `voice.provider_error`, `provider.keepalive_failed`, `voice.provider_refused`, `voice.failure`, `voice.response_silent`, `voice.manual_cancel` | provider events |
| | `voice.latency.*` with `speech_id` and `elapsed_ms` | latency `reported` (measured by the producer) |
| | `voice.latency.brain_turn_accepted` | latency stage `brain_turn_accepted` |
| | `voice.stack`, `voice.active` | identity |
| | `provider.models_failed` | provider event `models_failed` (`provider`, `code`) |
| | `voice.speech_started` (server VAD, at the START of user speech, logged when no Jarvis output is live), `voice.input_submitted` (commit at the end of the utterance), `voice.transcript` (timing and `addressing` only), `voice.brain_turn_submitted` (also a turn), `voice.turn_completed`, `voice.transcript_dropped`, `voice.manual_submit` | `user_activity`; onset `speech_started`; closing facts `input_submitted`, `transcript`, `turn_submitted` |
| | `voice.start`, `voice.stop`, `audio.output_stopped`, `audio.device_closed`, `audio.native_failed`, `voice.speech.stream_closed`, `voice.timeout` | `lifecycle`; segmentation; missing-outcome `cause` |
| | `core.brain.replies_superseded` (`work_ids`), `core.brain.turn_slow`, `core.brain.turn_over_budget` (`duration_ms`, `budget_ms`), `core.brain.latency.work_completed` (`elapsed_ms`, `measure`) | `brain` |
| | `voice.realtime.usage` | `usage` (token counts, duration, source) |
| | `voice.state.spoken_diverged`, `voice.state.diverged` | speech `spoken_divergences` / `state_divergences` when the line names a `speech_id` (counts only, never a finding: Why no payload divergence rule); a line without `speech_id` is not attributed |
| `VoiceSessionMetricRecorder` reports (`jarvis.voice_benchmark.session` v1) | reports of the selected session ids | `aggregates.voice_session_reports`, identity |
| `trace_summary.summarize` | the selected raw lines (scalars only) | `aggregates.trace_summary` |

Selection budget: the journal reader keeps only mapped kinds
(`bundle_builder.MAPPED_JOURNAL_KINDS`, plus the `voice.latency.` prefix) and the
kinds `trace_summary.summarize` reads (`bundle_capture.TRACE_SUMMARY_KINDS`:
`voice.owner.*`, `voice.barge_in.authority/owner_confirmed/provider_advisory`,
`voice.input.non_owner_dropped`, `voice.authorization_*`,
`core.brain.work_context`, `core.work.attention`, `core.work.updated`).
`max_selected_lines` and `max_selected_bytes` count those lines only; other kinds
are counted in `lines_in_window` and never kept. Consequently the per-kind
counts of `aggregates.trace_summary` cover the selected kinds only.

Deliberately unmapped kinds of the live inventory:

| Kinds | Why not mapped |
|---|---|
| `voice.state.updated` (3678 live lines), `voice.speech.presentation_decided`, `voice.ledger.projected` | Internal state and presentation bookkeeping, one line per state step; the delivery facts they lead to are mapped (`voice.speech.*`, divergences) |
| `voice.assistant`, `voice.prompt` | Carry text (assistant words, prompt fingerprints tied to instructions); no timing the mapped kinds lack. (`voice.transcript` is mapped for its timing only; its message is never read.) |
| `voice.reflex.decided`, `voice.reflex.skipped` | Reflex gate decisions; the reflex that played is mapped (`voice.reflex.started`) |
| `voice.background`, `voice.wake`, `voice.duplex`, `voice.input_submit_requested`, `voice.state.frontend_error` | Surface mode and UI state; session boundaries come from `voice.start`/`voice.stop`/`voice.connecting` |
| `audio.start`, `audio.stop`, `audio.devices.listed`, `audio.test.*` | Device enumeration and the Control Center audio test, not a conversation |
| `core.brain.backend_task_started`, `core.brain.backend_task_result`, `core.brain.notice_relayed`, `core.brain.woken_by_work` | Backend work lifecycle is carried by Conversation Events `brain.work.*`; not a speech or turn timing |
| `agent.*` (including `agent.event`, raw provider stream), `tool.call`, `tool.result` | Raw provider stream, prompts, tool arguments and results: private by contract |
| `process.*`, `settings.*`, `ui.*`, `calendar.backend`, `claude.*`, `brain.backend`, `errors.archived` | Process, settings and UI plumbing outside the voice conversation |

The bundle reuses the existing aggregators instead of re-deriving them. Session
latency summaries come from the recorder's reports, and owner, barge-in and
replay percentiles and per-kind counts come from `trace_summary`. The bundle adds
the per-item join with provenance, which no existing aggregate keeps.

### Latency joins

There is one join per non-chunked speech (`join_id` `speech:<speech_id>`). The
stages, in order:

1. `user_turn_end`: the user turn with the same `correlation_id`;
2. `brain_turn_accepted`;
3. `speech_requested` (a chunk takes its request's);
4. `speech_queued`;
5. `speech_queue_free`: the latest of `speech_queued`, the end of the latest
   other output (speech or playback) of the same segment that was still live
   after the queueing and ended before this start (the voice output is serial),
   and the end of the user's floor: when a user onset was open at the queueing
   (a `speech_started` not yet closed), the first closing fact
   (`input_submitted`, `transcript`, `turn_submitted`) after the queueing and
   before this start. Waiting for either is not queueing latency;
6. `speech_dispatched`;
7. `speech_started`;
8. `provider_first_pcm` and 9. `first_audio`: earliest
   `voice.latency.provider_first_pcm`, and earliest `output_first_write` or
   `first_audible_write`, over the speech's outputs;
10. `speech_ended`: the first terminal.

A stage is the earliest observation across sources and lists all of them.
A measure exists when both of its stages exist:

| Measure | From | To |
|---|---|---|
| `user_turn_end_to_brain_turn_accepted_ms` | `user_turn_end` | `brain_turn_accepted` |
| `brain_turn_accepted_to_speech_requested_ms` | `brain_turn_accepted` | `speech_requested` |
| `speech_requested_to_queued_ms` | `speech_requested` | `speech_queued` |
| `speech_queued_to_started_ms` | `speech_queued` | `speech_started` (raw, serial playback included) |
| `speech_queue_free_to_started_ms` | `speech_queue_free` | `speech_started` (thresholded) |
| `speech_started_to_first_audio_ms` | `speech_started` | `first_audio` |
| `user_turn_end_to_first_audio_ms` | `user_turn_end` | `first_audio`, only on the join whose first audio is the earliest of its `correlation_id` (the turn's first audio) |
| `first_audio_to_speech_ended_ms` | `first_audio` | `speech_ended` |

Joined stages come from several processes, whose clocks are only advisory
(Conversation Events, "Time, ordering and idempotency"). A joined measure can be
off by the clock skew, even negative. `reported` measures are the producers' own
durations measured within one process, so prefer them when both exist.

### Anomaly rules

Rules are table-driven (`DEFAULT_RULES` plus `RULE_EVALUATORS`) and
deterministic, and their thresholds are declared data: pass other thresholds
with `BundleOptions(rules=...)`. Each finding carries `rule_id`, `rule_version`
and the evidence of its subject. A rule is `evaluated` only when one of its
sources was read (`available`, `empty` or `truncated`). Otherwise its row says
`skipped_reason: source_unavailable`.

| Rule id | Version | Needs (any) | Signature | Thresholds |
|---|---|---|---|---|
| `voice.self_barge_in` | 1 | journal | Confirmed barge-in of **audible** Jarvis output (`audible`: played audio or an audible write before the episode) while output was live, with no user activity (User activity: an open onset, an onset after, or a closing fact of an utterance under way) in its segment within the window. Skipped when the segment ends before the window closes. Known blind spot: self-echo that was transcribed and submitted as a user turn is not flagged, so no finding is not evidence of no self-echo (User activity). | `user_activity_window_ms` 20000 |
| `speech.delivered_after_supersession` | 1 | events, journal | A start, completion or interruption of a speech later than its own `superseded` or `stale` terminal | none |
| `speech.duplicate_payload` | 1 | events | Two started speeches of one conversation and one segment with the same normalized payload (case-folded, whitespace collapsed; the played text, else the requested text, compared in memory) within the window | `window_ms` 120000, `min_chars` 12 |
| `speech.missing_delivery_outcome` | 1 | events, journal | A speech `queued`, `started` or `dropped` whose segment continues at least the grace after its last stage, or was closed by a session end kind. `measured`: `state`, `silent_ms` (to the segment end, never past it), `cause` (first `native_failed`, `device_closed`, `stream_closed`, `stopped`, `timeout`, provider `error`, `disconnected`, `failure`, `keepalive_failed` or `refused` after the last stage in the segment, else null), `segment_end` (closing kind or null) | `grace_ms` 30000 |
| `latency.above_threshold` | 1 | events, journal | A joined measure strictly above its threshold (thresholds are named after measures) | `user_turn_end_to_first_audio_ms` 8000, `speech_queue_free_to_started_ms` 3000, `speech_started_to_first_audio_ms` 4000 |
| `events.reconstruction_anomaly` | 1 | events | `reconstruct_conversation` absorbed a `duplicate_span_open`, `duplicate_span_close`, `close_before_open` or `conflicting_duplicate` | none |

To add a rule, add its `AnomalyRule` row, its evaluator under the same id, its
required thresholds in `REQUIRED_THRESHOLDS`, a row in this table and a test.
Changing a rule's meaning or a default threshold bumps its `version`. (Both Slice 03
reworks changed rules before any bundle was stored outside QA probes: nothing stored
yet, so every rule is still version 1.)

#### User activity

`next_user_activity_ms` and `next_user_activity_basis` of an episode, computed in
its segment from user onsets (`speech_started`) and closing facts
(`input_submitted`, `transcript`, `turn_submitted`):

| Basis | Evidence | `next_user_activity_ms` |
|---|---|---|
| `ongoing_onset` | An onset at or before the episode with no closing fact since: the user was speaking | 0 |
| `onset` | The first activity after the episode is an onset | its delay |
| `closed_without_onset` | The first activity after the episode is a closing fact, within `MAX_UTTERANCE_MS` (60 s), with no onset in between: it closes an utterance already under way at the episode (the VAD start that triggers a barge-in is not logged separately) | 0 |
| `closing` | Same, but later than `MAX_UTTERANCE_MS` | its delay |
| null | No activity after the episode in its segment | null |

Known limit: a closing fact that belongs to an utterance committed before the
episode but transcribed or submitted after it also reads as `closed_without_onset`.

Known blind spot of `voice.self_barge_in`: real acoustic self-echo is usually
transcribed and submitted as a user turn (`voice.transcript` and
`voice.brain_turn_submitted` within seconds of the barge-in). The journal
carries no text and no speaker attribution, so that closing fact reads as
`closed_without_onset` and the rule does not flag the episode. The bundle rule
therefore only catches echo barge-ins that produced no user turn, and the
absence of a finding is not evidence that there was no self-echo. Confirming
self-echo is the job of the `voice.self_echo` diagnostic and its profiles
(virtual, audio, hardware; Slices 06 to 09 and 12), not of the bundle.

#### Why no payload divergence rule

`voice.state.spoken_diverged` is emitted by `jarvis/core/voice_state.py` when the
provider's confirmed transcript is not exactly equal, as a string, to the
intended text. Any punctuation, casing or transcription difference triggers it:
on the live trace it flags about 40 % of normal, complete playbacks. It is
therefore counted on speech items (`spoken_divergences`, `state_divergences`,
`spoken_diverged_at`) and never reported as a finding. Payload integrity needs a
normalized producer measure (similarity or word error rate plus lengths, never
text); see `tasks/jarvis-category2-test-lab/Issues/speech-payload-integrity-needs-normalized-measure.md`.

### Privacy

- Only Conversation Events with `public` visibility (`user.transcript.accepted`,
  `brain.message.published`, `mouth.speech.*`, `mouth.reflex.started`) may fill
  `turns[].content`, and only when `BundleOptions.include_public_content` is
  true (the default). The text goes through `redact_identifying_text` (URL
  userinfo, query and fragment; SSH users; emails) and is cut at
  `max_content_chars` (default 512, at most 8192; `content_truncated`). With
  `include_public_content=False`, every content is null.
- Never copied: diagnostic content (speech requests, withheld speech, sub-agent
  descriptions), journal messages, journal `data` outside the allowlist, tool
  arguments and results, provider error text, `agent.event` lines, prompts,
  hidden reasoning, raw audio and secrets.
- Journal lines are projected before they reach the builder. The base is
  `conversation_event_trace.project_trace_entry` (the drill-down allowlist and
  value rules, credential prefixes refused). On top of it, a closed set of extra
  scalar keys has its own value rules:
  - numbers: `elapsed_ms`, `queue_wait_ms`, `stop_latency_ms`, `budget_ms`,
    `duration_seconds`, `input_tokens`, `output_tokens`;
  - code tokens: `measure`, `authority`, `trigger`, `addressing`, `arch`,
    `delivery`, `delivery_boundary`;
  - ids: `segment_id`, `interrupted_speech_id`;
  - booleans: `device_stopped`, `near_playback`, `cleanup_pending`,
    `still_active`;
  - 64 hex: `configuration_id`;
  - lists of at most 16 ids: `work_ids`.
- The codec applies the Test Lab Name rule at every depth (`scan_private`), so
  no private field name can be stored.
- Known limit: a secret shaped like a code token (`[a-z][a-z0-9_.-]{0,63}`, for
  example `hunter2pass`) written by a producer under an allowlisted code key
  (`code`, `status`, `reason`, ...) passes the value rule and is copied. The
  allowlisted keys are written by Jarvis code, never by providers or users, and
  credential prefixes (`sk-`, `ghp_`, ...) are refused.

### Identity and determinism

- The builder reads no clock and no entropy; `captured_at` is an input.
- The id time is `session.started_at`, else `selector.start`, else `captured_at`
  (a bundle with no evidence). The nonce is `content_fingerprint[:16]`. The
  capture context (`capture`) is outside the fingerprint, so capturing the same
  evidence again (later, from other code) gives the same `bundle_id` and
  `content_fingerprint`, and the store keeps the first copy (`duplicate`).
- Inputs are deduplicated (events by id, keeping the lowest sequence; lines by
  offset) and sorted before derivation, so their order does not matter.
- Determinism holds for closed evidence. A window is closed once the journal
  holds a line later than the window end plus the tolerance (`stopped_by:
  window_end`); a bundle captured before that (`window_open`, warning
  `open_window`) can change on recapture. An id-only capture is stable once its
  session has ended and the journal after it gets no new undecodable lines (its
  damage counts cover the scan to the file end) and stays within `max_bytes`.
- Lines with equal timestamps keep file order; their references are offsets, so
  a file with the same lines in another order gives another bundle.

### Capture service

`capture_diagnostic_bundle(selector, *, captured_at, trace_path, event_source,
reports_directory, code, config_fingerprint, options, store, trace_limits,
event_limits, diagnostics)` is async. A source left `None` is `not_requested`.

- Selector (`SessionSelector`): a `conversation_id`, a `session_id`, and/or a
  window `start`..`end`. It needs at least one id or both times.
- Conversation Events (`read_session_events`), bounded by `EventReadLimits`
  (20000 events, pages of 500, 8 conversations for a session, 64 MiB of export):
  - `StoreEventSource(store)` reads through the `ConversationEventStore` port.
    For a conversation it calls `list_conversation_events`. For a session it
    calls `list_events_by_id(session_id)`, then adds the untagged events of
    those conversations inside their extent. For a window it calls
    `list_events_in_time_range`.
  - `StateDatabaseEventSource(path)` opens a Core state database read-only
    (`ReadOnlyStateDatabase`: `file:<db>?mode=ro` URI, `PRAGMA query_only=ON`,
    one connection per read, closed afterwards) behind
    `SQLiteConversationEventStore`, so the store's own code decodes and
    cross-checks the rows. A v1 database without the table is `unavailable`.
  - `ExportEventSource(path)` reads the file with `read_export` and filters it
    by the selector.
- Journal window: the selector's, else the events' extent widened by
  `trace_margin` (30 s), else none.
- `read_session_trace`, bounded by `TraceReadLimits` (64 MiB read, 500000 lines,
  lines over 256 KiB skipped, 20000 selected lines, 16 MiB selected, 5 s
  tolerance):
  - With a window, it bisects the file on line timestamps to the window start
    minus the tolerance, reads forward, and stops at the first line later than
    the window end plus the tolerance. Without a window, it reads the last
    64 MiB (`start_truncated` when older bytes exist).
  - It keeps a line that is timed inside the window, is of a selected kind
    (Selection budget; never `agent.event`), and carries no other conversation or
    session id than the selector's.
  - A line carrying the selected id is `matched`. With ids and no window, lines
    without ids are kept only inside the extent of the matched lines.
  - Damage is counted over the physical scan range: from the scan start (id
    mode) or from the first line timed at or after the window start minus the
    tolerance (window mode), to the stop point. Non-JSON lines (including
    non-UTF-8) count as `corrupt_lines`, lines without a valid `ts` as
    `untimed_lines`, lines over 256 KiB as `oversized_lines`. A file whose read
    range holds no decodable line is `unavailable` with `no_decodable_lines`
    (never `empty`); decodable but untimed only, `no_timed_lines`.
  - A UTF-8 BOM at the file start is skipped (the first reference offset is 3).
    A carriage return separates records (CRLF and CR-only files decode; a
    CR-only file larger than 256 KiB reads as one oversized line). A final line
    without newline is never decoded: `torn_tail` plus the `torn_tail` warning.
  - `window_open` is set when a window was given and the read stopped at the
    file end.
- Voice session reports (`read_voice_session_reports`): the `*.json` files of
  the reports directory (at most 2048 files, 1 MiB each), kept when their
  `session_id` belongs to the selector, the events or the matched lines.
- `trace_summary.summarize` runs on the selected raw lines, which are then
  discarded.
- A missing or unreadable source never fails the capture. It becomes its
  coverage status plus one `testlab_bundle_source_degraded` warning (`source`,
  `status`, `reason`). A selector error raises `TestLabError`, and a store error
  propagates. The expected path emits `testlab_bundle_captured` (info:
  `bundle_id`, `stored`, counts, statuses, segment count and warnings, never
  content). Emission goes through the private `_diagnostics.SafeDiagnostics`
  shared with both filesystem stores (a failing sink is counted, never raised).
- Read-only database, known effects: SQLite opens a WAL database through its
  `-shm` index, so a read-only open of a database with no live owner can create
  or rewrite `<db>-shm` (the database and WAL content stay unchanged). When a
  writer holds an exclusive lock, the read waits for SQLite's busy timeout
  (about 5 s per statement, 7.4 s measured for a capture) and the source becomes
  `unavailable` / `state_database_unreadable`.

### Bundle storage

Port `store.BundleStore`, synchronous like `TestRunStore`:

| Method | Contract |
|---|---|
| `put_bundle(bundle)` | Writes a new bundle and returns `BundlePutResult` with status `stored`. For the same id with the same `content_fingerprint`, it returns `duplicate` and writes nothing. For the same id with another fingerprint, it raises `BundleConflictError` (`testlab_store_conflict`). An unreadable stored copy raises `BundleRecordCorruptError` and is never overwritten. |
| `get_bundle(bundle_id)` | Returns the bundle decoded with the strict codec, or raises `BundleNotFoundError` (`testlab_store_not_found`) or `BundleRecordCorruptError` (`testlab_store_corrupt`). |
| `list_bundles(query)` | `BundlePage {bundles: BundleSummary[], corrupt, next_cursor}` for `BundleQuery {limit 1..500, newest_first, after_bundle_id, conversation_id}`, ordered by bundle id. Each listed bundle is read and decoded, so the cost grows with the number of bundles. |

`FilesystemBundleStore(root)` shares the run store's root and conventions
(`_fs.py`: the same lock, atomic write, path budget and link rules):

```text
<root>/bundles/<bundle_id>/bundle.json      canonical JSON (DiagnosticBundle.encode)
<root>/bundles/<bundle_id>/.bundle-*.tmp    write in progress or crash leftover
<root>/bundles/.staging-<bundle_id>-*       bundle being created (renamed into place)
<root>/locks/<bundle_id>.lock               writer lock of the bundle
```

Both stores share `<root>/locks/`. Each store only ever treats its own lock
names as orphans: `FilesystemTestRunStore.remove_stale_temporaries` removes a
lock only when its name is a run id (`tlr-`) whose run is gone, never a bundle
lock (`tlb-`).

A bundle is immutable. Stray names, links and unreadable bundles are listed in
`corrupt` (`CorruptRunEntry`) and diagnosed as `testlab_bundle_listing_corrupt`;
nothing is deleted automatically. No sweep removes bundle staging leftovers yet
(readers ignore these hidden entries), and bundles have no retention yet.
`TestRun.bundle_id` references a stored bundle, but the run store does not check
that the bundle exists.

## Validation

```powershell
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/unit/test_testlab_*.py
```

Worker processes are real in the Slice 05 integration file (one process per test,
two in the tree-kill test):

```powershell
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/integration/test_testlab_worker.py
```

Sweeps run real workers too, at most two at once and two or three points per
sweep (the voice stack is mounted only by the one test that has to prove the
`virtual` profile really sweeps):

```powershell
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/integration/test_testlab_sweep_runs.py
```

The replay compatibility layer is covered by the existing replay tests, which must
keep passing unchanged:

```powershell
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/unit/test_voice_replay_fixture.py tests/integration/test_voice_replay_regressions.py tests/integration/test_voice_replay_safety_regressions.py
```

Opt-in real-session smoke test. It reads the local `runtime/trace.jsonl`, opens
`data/state/jarvis.sqlite3` read-only, and prints counts only:

```powershell
$env:JARVIS_TESTLAB_REAL_SESSION=1; .venv/Scripts/python -m pytest -q -s -p no:cacheprovider tests/integration/test_testlab_bundle_real_session.py
```

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
and `granted`). It compares declarations only. Checking that a device is really free, and not held
by the running voice process, is the SUPERVISOR's job, in the reservation path
("Device contention"); a runner runs in a process that has already been
spawned, and by then the microphone is a fraction of a second from being opened. A
`hardware:guided` run needs one more thing the declaration cannot express — a person at
the keyboard right now — and that is the `JARVIS_TESTLAB_GUIDED=1` opt-in the supervisor
checks in the same path ("Guided runs").

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
| `user.speech` | `turn_id`, `text` | `addressing` | virtual, live | Authored utterance: a virtual transcript, or a live text input. On `hardware:guided` a PERSON says the words, and that needs an id, a deadline and an acknowledgement — the `human.*` family. |
| `user.interrupt` | `turn_id`, `text` | – | virtual, live | The user starts speaking over Jarvis output. |
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
| `audio.inject` | `audio_ref` | `gain_db` | audio, live, hw:auto, hw:guided | A known audio fixture, by reference, never bytes, resolved inside the Slice 08 fixture root ("Audio profile"). On `audio`/`live` it enters the CAPTURE path; on `hardware:*` it is played through the real output device, because that profile has a speaker. Not a virtual primitive. |
| `human.silence` | `prompt_id` | `text`, `deadline_ms` | hw:guided | The human is asked to stay completely silent until the step ends ("Guided runs"). |
| `human.speak` | `prompt_id`, `text` | `deadline_ms` | hw:guided | The human is asked to say `text` out loud, at a normal volume. |
| `human.interrupt` | `prompt_id`, `text` | `deadline_ms` | hw:guided | The human is asked to cut Jarvis off with `text` while it is speaking. |
| `human.acknowledge` | `prompt_id` | `text`, `deadline_ms` | hw:guided | The human is asked to confirm that the previous step happened as described. |
| `parameter.override` | `parameter`, `value` | – | all | Run-local value; prelude only (see below). |
| `expect.event` | `event` | `count_min`, `count_max` | all | A Conversation Events type must appear `count_min` (default 1) to `count_max` times. |
| `expect.metric` | `metric`, `comparator`, `threshold` | – | all | Ad-hoc check on a declared metric, evaluated on the final run metrics. |
| `expect.assertion` | `assertion_id`, `outcome` | – | all | A declared assertion must end `passed`, `failed` or `missing` (a reproduction expects `failed`). |

Argument types are global: one name has one type everywhere (as in the replay DSL),
declared in `ARG_SPECS` and validated in that order, so a document with several
faults always reports the same first fault.

| Type | Rule |
|---|---|
| identifier (`turn_id`, `work_id`, `candidate_id`, `intent_id`, `output_id`, `playback_id`, `content_tag`, `result_tag`, `generated_tag`, `checkpoint_id`, `provider_item_id`, `prompt_id`) | `[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}`, opaque; `provider_item_id` may be null |
| time in ms (`ttl_ms`, `played_ms`, `deadline_ms`) and `intent_epoch` | non-negative integer (never a bool), within the timeline bound; `deadline_ms` is also bounded by `MAX_PROMPT_DEADLINE_S` (10 min), pinned equal by a test |
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
  doubles, which only `virtual` has today; Slices 08 and 09 widened a set only
  together with a runner that really performs it on that profile. Slice 09 also
  NARROWED one: `user.speech` and `user.interrupt` no longer claim `hardware:guided`.
  That was a declaration written before anything implemented it, and it is wrong in a
  way that matters — on a guided run a person says the words, and a step that asks a
  person for something is not measurable without a stable id, a deadline and an
  acknowledgement, none of which those two carry. The `human.*` family replaces them,
  so there is exactly one way to address a person. No published manifest referenced
  either primitive on that profile.
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
names what a runner still has to cover; it is empty for `virtual` (Virtual profile),
for `audio`/`live` (Audio profile) and for `hardware:auto`/`hardware:guided`
(Hardware profiles).

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

Slice 08 registered `audio` and `live` runners and PROPOSED two version bumps, neither
published: `voice.self_echo` v2 (adds the `audio` profile) and `voice.queue_latency` v2
(adds the `live` profile). Both are rendered and validated in
`tasks/jarvis-category2-test-lab/slices/08-audio-live-profiles/`; nothing about v1
changes, and `catalog.lock.json` is untouched until a human publishes them.

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

Five Slice 08 codes join it too: `device_contention` and `live_opt_in_missing` are
`refused` (nothing was started, and refusing is the point — the laptop microphone
belongs to the live conversation), `device_contention_during_run` and
`cost_budget_exceeded` are `inconclusive` (the run produced partial evidence and no
verdict), and `supervisor_fault` is `crashed` (our own resource gate or supervision
loop broke, which is a defect of ours and not a finding about the product). See
"Device contention" and "Cost and budget".

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

Slice 09 adds two families, both of them `MeasurementUnavailable` subclasses and so all
reading `inconclusive`: the device codes (`testlab_device_*`, "Hardware profiles") and
the guided codes (`testlab_guided_prompt_timed_out`, `testlab_guided_prompt_refused`,
`testlab_guided_prompt_late`, `testlab_guided_prompter_failed`,
`testlab_guided_prompt_limit`, `testlab_guided_step_not_followed`,
`testlab_guided_claim_unmeasured`, "Guided runs").

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
- **Audio is opt-in per RUN as well as per store (Slice 08).** `WorkerJob.allow_audio`
  is set by the supervisor only when the caller asked
  (`RunRequest.allow_audio_artifacts`), the profile can produce audio (`audio`,
  `hardware:auto`, `hardware:guided`) AND its own store allows audio; the worker builds
  its store from it. A job that claims `true` against a store built without audio is
  still refused at write time. See "Audio artifacts".
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
contention gate: a run needs both. Slice 08 adds two EXTERNAL gates in the same
path, evaluated before the reservation is taken and before any worker is spawned: a
run that needs an audio device is refused unless device-contention detection
positively reports the devices free (`device_contention`), and a run that needs a
provider is refused unless the explicit live opt-in is set in the supervisor's
environment (`live_opt_in_missing`). Neither is a wait: no amount of queueing changes
a live conversation or a missing flag, so both are refusals.

A dispatch pass that raises is captured and emitted at `error`
(`testlab.supervisor.dispatch_failed`, with the exception type and message) and the
loop survives it. An unforeseen fault used to end the dispatcher task silently, and
every queued run then waited forever with nothing in the log saying why.

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
| `device_contention` | `errored` | Slice 08: the audio devices are held, or their availability could not be established; nothing was started |
| `device_contention_during_run` | `errored` | Slice 08: the live Jarvis took the devices back while the run was executing; the run was stopped |
| `live_opt_in_missing` | `errored` | Slice 08: a provider run without the explicit `JARVIS_TESTLAB_LIVE=1`; nothing was called and nothing was spent |
| `cost_budget_exceeded` | `errored` | Slice 08: the estimated provider spend crossed the run's budget mid-run and the session was stopped |
| `supervisor_fault` | `errored` | Slice 08: the supervisor's own gate or supervision loop raised; never the worker's fault |
| `human_presence_missing` | `errored` | Slice 09: a guided run without the explicit `JARVIS_TESTLAB_GUIDED=1`; nobody's time was spent |

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
test). `audio.inject` is acoustic and is not a virtual primitive; Slice 08 owns it
("Audio profile"), through `VirtualExecutor.handler_for`.

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
  question. Slice 08 answered the first half: the `audio` profile runs the real
  canceller and the real near-end detector over injected audio, and proves they keep
  the gate closed on echo and open it for a real near-end voice. The room, the speaker
  and the microphone are still `hardware:*`.
- **Real provider timing.** `speech.started_to_first_audio_ms` measures the path from
  the speech start to the first PCM the bridge relayed. The provider's own generation
  latency, its jitter and its cancel behaviour are the `live` profile's, which Slice 08
  implements (`voice.queue_latency.live`) and which no one has yet run for real.
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

## Audio profile

`jarvis/testlab/audio/`. The `audio` profile runs the **real local audio chain** over
a controlled stimulus: the production writer, the production duplex capture
(`jarvis/audio/duplex.py::CaptureProcessor`), the real WebRTC echo canceller
(`jarvis/adapters/webrtc_echo.py`, when `livekit.rtc` is installed) and the real
near-end detector, working on real samples. It opens **no device** and calls **no
provider**, which is why it runs in an ordinary pytest chunk and why it declares no
capability.

It is the `virtual` profile with two substitutions and nothing else
(`virtual_voice_stack(context, capture_factory=, audio_class=)`):

| Piece | `virtual` | `audio` |
|---|---|---|
| Duplex capture | `VirtualEchoGuard` (states acoustic state, performs no acoustics) | `CaptureProcessor` + the real canceller |
| Microphone | the harness's canned block | `InjectedSourceAudio.inject_block`, running the production callback body (`capture.process` then `_deliver_capture` then `_put_input`) |
| Realtime session | `FakeRealtimeSession` | `FakeRealtimeSession` (unchanged: this profile needs no provider) |
| Output stream | `ImmediateOutputStream` | `ImmediateOutputStream` (no PortAudio) |

### Fixture root

`audio.inject` finally has a home: `jarvis/testlab/fixtures/audio/`, resolved by
`AudioFixtureRoot`. An `audio_ref` is a relative POSIX path inside that one root:

- the Slice 02 artifact-path rule first (`check_artifact_path`, already applied to the
  `audio_ref` argument by `jarvis.testlab.primitives`), so a scenario carrying `..`, a
  drive, a backslash or a hidden segment is refused **when the scenario is checked**,
  before a run exists (`testlab_primitive_args_invalid`, and the worker refuses the run);
- then, at resolution time, every path component is checked for a symlink **or a
  Windows junction** (`_fs.is_link`) and the resolved target must still be inside the
  root, so a planted link cannot move the subtree out (`testlab_audio_fixture_unsafe`);
- a ref naming nothing is `testlab_audio_fixture_unknown`, and a file that is not a
  mono 16-bit PCM WAV is `testlab_audio_fixture_invalid` — never silently converted.
  All three are `MeasurementUnavailable` when a run hits them, so the run reads
  `inconclusive`.

Shipped fixtures are **synthetic and reproducible**: `SHIPPED_FIXTURES` declares each
one, `build_reference_clip` / `build_silence` generate it from its parameters, and
`tests/unit/test_testlab_audio.py` regenerates both, compares bytes, and pins their
sha256 — that test, not the repository's unenforced `MANIFEST.sha256`, is what holds
these two binaries to their declaration. There is no recording of a human
voice in the root, so an injected clip cannot leak one.

| Fixture | Content |
|---|---|
| `reference-tone-1s.wav` | 1 s, 24 kHz mono PCM16: 220/440/880 Hz partials under a trapezoid envelope, peak about -12 dBFS |
| `silence-500ms.wav` | 500 ms of digital silence, the control stimulus of a level or gate measurement |

A clip at another rate is resampled to 24 kHz on load (`resample_pcm16`, linear
interpolation, standard library only — `audioop` was removed in Python 3.13), and
`gain_db` is applied with clipping, never wrapping.

### What the run records

Every audio run commits `audio_profile.json` (a bounded `report` artifact,
`jarvis.testlab.profile_metadata` v1): profile, `sample_rate`, `output_sample_rate`,
`input_block_ms`, `input_device`, `output_device`, `device_opened`, `duplex_engaged`,
`aec_engaged`, `aec_unavailable_reason`, `canceller`, and one entry per `audio.inject`
(ref, blocks, bytes, duration, gain, source rate, signals). Device ids are what the run
**requested** (always `null` here, because nothing is opened), never an enumeration of
the workstation's hardware: a device name is a fact about the user's machine.

A report artifact rather than metrics, because these are facts about the run, not
measurements of the product — and a manifest that had to declare them would need a new
version every time a probe is added.

### Registered implementations

| Name | Runner | Measures |
|---|---|---|
| `voice.self_echo.audio` | `SelfEchoAudioRunner` | the four `voice.self_echo` metrics, with the gate computed by the real detector |
| `testlab.scenario.audio` | `AudioScenarioRunner` | `scenario.steps_performed`, `.checkpoints_reached`, the two expectation metrics, `audio.injected_block_count`, `audio.injected_ms` |

`AudioScenarioRunner` is `VirtualExecutor` plus one primitive: `audio.inject`, through
the `handler_for` hook. A profile may **add** a handler, never replace one, or a shipped
scenario would quietly mean something else — and `resolve_handler` ENFORCES that rather
than asking politely: an executor returning anything but the shared handler for a
primitive the shared table performs is refused with
`testlab_virtual_profile_handler_invalid`, which reads `crashed` because it is a defect
of ours, not a measurement. Widening the replay primitives
(`provider.*`, `scheduler.*`, `owner.*`, `user.speech`) to `audio` is a deliberate
**non-goal** of Slice 08: they drive doubles the `audio` profile still has, so widening
them is defensible, but which of them should stay doubles on a real chain is a decision
for the manifest that needs them, not a side effect of adding a runner.

### What the audio profile can and cannot prove

**Can prove.** That the production writer's reference (`push_reference` per played
block), the production canceller and the near-end detector, on real samples, keep the
echo gate closed while Jarvis is the far end — and open it for a real near-end voice.
That is the acoustic discrimination the `virtual` profile explicitly cannot make. The
two tests that prove it are the same run with one difference: injected audio that
correlates with what Jarvis played (0 confirmed barge-ins, the run passes) versus a
loud uncorrelated voice (1 confirmed, the blocking assertion fails).

The injected echo is a **room response**, not a copy of what was played: one block of
delay, a slow level drift and a little broadband noise (`room_response`,
`ECHO_DELAY_BLOCKS` in `jarvis/testlab/audio/chain.py`), and the first candidate waits for
the canceller's 400 ms pre-roll. None of that is decoration. A delay-free, exactly-scaled,
noiseless copy is cancellable in a way no room is: the canceller converges until the
near-end detector learns to expect a residual no room produces, and after the detector's
three-second warm-up clamp lifts, the gate opens on its own arithmetic. Measured at this
seed's own declared default of 8 000 ms, the old copy made the diagnostic FAIL a healthy
product at ~3.4 s; the room response plays all 8 000 ms clean, 5/5. Full measurements and
the residual open question: `Issues/self-barge-in-after-seconds-of-speech.md`.

**Cannot prove.** No PortAudio stream is opened, so: no room, no speaker, no
microphone, no clock drift, no underrun, no device contention and no native failure.
The acoustic coupling is whatever the run states: `echo.coupling_db` is a DECLARED
parameter of the diagnostic (float, -60..0 dB, default -12), so it can be overridden and
swept like any other and is bounded by the declaration — it is not what a room would do. Those are `hardware:auto` and `hardware:guided` (Slice 09).
Nor does it say anything about a provider: the Realtime session is still the
deterministic double.

**Without the canceller** (`livekit.rtc` absent, or `echo_cancellation=False`) the run
still executes, with the production fallback (a more conservative initial coupling and
a shorter pre-roll) — and `aec_engaged: false` plus `aec_unavailable_reason` are
recorded, because a measurement taken without the AEC must never be read as a
measurement of the AEC.

## Live profile

`jarvis/testlab/live/`. The `live` profile is the `audio` profile with **one** thing
swapped: the deterministic Realtime double becomes a real provider session
(`voice_stack(realtime_factory=)`). Writer, duplex capture and canceller are
identical, so a difference between an `audio` run and a `live` run of the same
diagnostic is a difference the **provider** made.

### Four gates, all mechanical

| Gate | Where | Refusal |
|---|---|---|
| Capability | `check_profile_permission` at `submit` | `permission_denied` (`capability_missing`), outcome `refused` |
| Budget | the same gate: declared `max_cost_usd` against the grant's | `permission_denied` (`cost_budget_exceeded`), outcome `refused` |
| Explicit opt-in | the supervisor's reservation path: `JARVIS_TESTLAB_LIVE=1` in its environment | `live_opt_in_missing`, outcome `refused` |
| A key | the worker: `OPENAI_API_KEY` | `testlab_live_opt_in_missing`, outcome `inconclusive` |

Nothing derives the opt-in and nothing defaults it on. The supervisor refuses the
reservation **before a worker is spawned**, so a live run cannot happen because a test
forgot a flag. Slice 05 already empties provider keys in a worker's environment unless
the profile declares a provider capability, so a `virtual` or `audio` worker physically
cannot reach a provider.

Registering `voice.queue_latency.live` or `testlab.scenario.live` makes a diagnostic
**runnable**, never **permitted**: availability is a property of the code, the four
gates are properties of the request.

### Registered implementations

| Name | Runner | Measures |
|---|---|---|
| `voice.queue_latency.live` | `QueueLatencyLiveRunner` | the four `voice.queue_latency` metrics, with the real provider's own generation latency |
| `testlab.scenario.live` | `LiveScenarioRunner` | the same set as `testlab.scenario.audio` |

`QueueLatencyLiveRunner` reuses `latency_metrics`, the seed's own measurement function,
so a `virtual` run and a `live` run of `voice.queue_latency` are computed by the same
code on the same journal joins. The difference is that nothing in the live runner plays
the audio or closes the output: the provider does both, and how long that takes is the
measurement.

`arm_session` is the documented double seam: a real provider session needs nothing
there, and a test double receives the run's journal so it can emit the
`voice.realtime.usage` lines a real session emits. Nothing in a real run overrides it.

### What the live profile can and cannot prove

**Can prove.** That the provider accepts this session shape, and what its real
generation latency, jitter and terminal behaviour are —
`speech.started_to_first_audio_ms` measured against a real session is the number the
`virtual` profile explicitly cannot produce.

**Cannot prove.** Nothing acoustic beyond what `audio` proves (still no device), and
nothing repeatable: a provider's latency on the day is evidence about that day. A
`live` run is a sample, not a regression gate, which is why no `live` profile belongs
in a routine suite.

**It has never been executed against a real provider.** Slice 08 implemented and tested
it with doubles; the first real call is the human gate of Slices 09 and 12. The opt-in
test that would make it is
`tests/integration/test_testlab_live_runners.py::test_a_real_provider_session_measures_real_latency`.

## Hardware profiles

`jarvis/testlab/hardware/`. `hardware:auto` and `hardware:guided` are the only Test Lab
profiles that open this workstation's microphone and speaker. They are the `audio`
profile with ONE substitution, exactly as `audio` is `virtual` with one:

| Piece | `audio` | `hardware:auto` / `hardware:guided` |
|---|---|---|
| Audio bridge | `InjectedSourceAudio` (production writer, no PortAudio) | `DeviceAudio`: the PRODUCTION `SoundDeviceRealtimeAudio`, opening real streams |
| Microphone | a fixture pushed into `capture.process` | the room, through PortAudio's own callback |
| Speaker | `ImmediateOutputStream` | the workstation's output device |
| Echo coupling | the declared `echo.coupling_db` | whatever the room does |
| Duplex capture, canceller, near-end detector | production | production, unchanged |
| Realtime session | the deterministic double | the deterministic double (no hardware profile calls a provider) |

**What `hardware:auto` adds over `audio`.** The coupling stops being a number the run
states and becomes what the speaker, the room and the microphone actually do: real
delay, real reverberation, real drift between the two clocks, real underruns, and real
device failure. An `audio` run proves the production canceller keeps the echo gate closed
against an echo the run itself constructed; a `hardware:auto` run proves it against an
echo nobody designed. No human is involved, so it can only make the NEGATIVE claim —
nothing confirmed a barge-in while the room was *assumed* quiet.

**What `hardware:guided` adds over `auto`.** A human, and exactly two things follow. The
silence becomes DECLARED instead of assumed: the person was asked to be quiet and the run
recorded whether they were. And a real voice can be asked to interrupt, which is the only
way to measure the TRUE positive. "The echo gate never fires" and "the echo gate fires for
a person" are different claims, and a gate that never opens satisfies the first one
perfectly while being completely broken. The two profiles are meant to be read together.

### Device selection

Declared parameter, else the workstation's configured device, else PortAudio's own
default — and the `source` of each choice is recorded in the run metadata, so a reader
knows whether a measurement was taken on a pinned device or on whatever the machine
happened to default to.

1. the diagnostic's declared `device.input` / `device.output` parameters (a device id or
   name; empty means "no preference");
2. `audio_input_device` / `audio_output_device` from the run's OWN settings copy
   (`<runtime_dir>/control-center-settings.json`), the same keys the Control Center
   writes — never the live `runtime/`, which the worker's isolation check forbids;
3. `None`, which is what Realtime Voice uses when nothing is configured.

Ids are normalised by the product's own `normalize_device_id`, so "1", `1` and a device
name mean here what they mean to Voice. Before anything is mounted, the selection is
pre-flighted with `SoundDeviceAudioDiagnostics.check_input_format` /
`check_output_format` — the same PortAudio question the Control Center audio test asks,
which opens nothing.

### The device failure mapping

**Every way a device can fail is `MeasurementUnavailable`, which reads `inconclusive`.**
Never `crashed` (that would blame the lab for the workstation) and never `failed` (that
would blame Jarvis). This is the Slice 08 carry-over made mechanical: the contention
detector answers "is the live Jarvis using the devices", never "can this device be
opened", and a third application holding the microphone is invisible to it.

| What happened | Product code | Test Lab code |
|---|---|---|
| `sounddevice` is not installed | `audio_backend_unavailable` | `testlab_device_backend_unavailable` |
| PortAudio could not enumerate | `audio_device_enumeration_failed` | `testlab_device_backend_unavailable` |
| The microphone refuses 24 kHz mono, or somebody holds it | `audio_input_unavailable` | `testlab_device_input_unavailable` |
| The output refuses 24 kHz mono, or somebody holds it | `audio_output_unavailable` | `testlab_device_output_unavailable` |
| The microphone stream could not record | `audio_input_capture_failed` | `testlab_device_input_capture_failed` |
| Nothing above the noise floor was captured | `audio_input_no_signal` | `testlab_device_input_no_signal` |
| Playback failed | `audio_output_playback_failed` | `testlab_device_output_playback_failed` |
| A supplied device id cannot exist | — | `testlab_device_id_invalid` |
| Anything else the product raises | any other code | `testlab_device_unmapped`, with the product's code in the detail |
| The pre-flight passed and the open failed anyway | — | `testlab_device_open_failed` |
| The microphone delivered nothing during the run | — | `testlab_device_input_no_signal` |
| Nothing reached the output device during the run | — | `testlab_device_output_not_played` |

A product code this table does not list still becomes `MeasurementUnavailable`, on ONE
stable code, `testlab_device_unmapped`, with the product's own code in the detail. Never
on a code synthesised from the message: a `RunFailure.code` is an identifier callers
branch on and the Slice 01 name rules validate, and `f"testlab_device_{exc.code}"` would
happily produce `testlab_device_AUDIO WEIRD/code` from a product that grew a new message.
The detail is bounded, printable and single-line whatever the code contained.

`testlab_device_output_not_played` and `testlab_device_input_no_signal` are the
**anti-vacuity rule**. "No false barge-in" measured through a microphone that delivered
nothing is not a passing run, it is an empty one — and an empty run that reads `passed` is
worse than an inconclusive one, because somebody will believe it. A hardware run that
played nothing, or captured nothing, refuses to report.

Counting bytes is not enough for the input half: a driver that streams digital silence
delivers as many bytes as a working one. So the run also requires that something was above
the **digital** floor over its whole length — one LSB, -90.3 dBFS, read from the raw
microphone by `LevelledCapture`. That is a bound on "the microphone is wired to nothing",
not a judgement about the room: a quiet room still carries Jarvis's own echo, which is the
whole stimulus. A guided phase that played nothing fails the same way and NAMES the phase,
because reporting "they did not interrupt" for a sentence Jarvis never said would blame
the person for our defect.

### Releasing the device

Always, on every path: success, `MeasurementUnavailable`, `RunCancelled`, the run
deadline, and an unforeseen exception. `hardware_voice_stack` closes every `DeviceAudio`
it finds in its own `finally`, after the voice runtime's teardown has already closed it
once; closing twice is safe and leaving a microphone open is not. If the worker is killed
instead (the supervisor's forced tree kill), the operating system closes the streams with
the process — which is the backstop, not the plan.

### What a hardware run records

`hardware_profile.json` (`jarvis.testlab.profile_metadata` v1, a bounded `report`): the
same fields an `audio` run writes, with `device_opened: true`, the device **ids** that
were requested, the `source` of each choice, and `echo_source: "room"`. Device ids, never
an enumeration of the machine: a device name is a fact about the user's hardware. A
guided run adds `guided: true` and `prompt_count`, and commits `guided_prompts.json`
beside it.

`capture.wav` follows the Slice 08 rule unchanged, and it matters more here: on a
hardware profile a clip is a recording of the user's ROOM. All three conditions must hold
(the caller asked, the profile can produce audio, the store was built with
`ArtifactWriteLimits(allow_audio=True)`), and the store still refuses at write time.

### The stimulus schedule, and why it is shaped that way

Two rules in `play_through_the_room`, and both exist so the runner does not manufacture
its own result:

- **No barge-in candidate before 400 ms of output.** The production canceller keeps a
  400 ms pre-roll and learns the room's coupling from the first frames. A candidate
  raised before that measures the canceller's convergence, not the gate.
- **The output never stops while a decision is pending.** An onset is raised and the next
  block is played immediately; the decisions are collected after the last block. Stopping
  to wait would let Jarvis fall silent mid-sentence, the far-end window would expire, and
  the gate would open for a reason that has nothing to do with the room.

- **The far end must exist in the DETECTOR before the first candidate.** The canceller's
  far-end window is filled by what the room RETURNS, not by what was written, so the run
  waits for one microphone block before its first candidate and only the first. Fifty
  milliseconds against 400 ms already playing: the output does not fall silent for it.

Each block must also reach the device before the next is queued, and the wait is on
`DeviceAudio.written_output_ms` rather than on the audible `played_output_ms`: on a device
whose latency exceeds one block the audible figure is still zero when two blocks have been
written, and a run that waited on it would raise its stimulus before Jarvis was playing.
`played_output_ms` is likewise sampled WHILE the utterance plays, because it is the cursor
of the current output and returns to zero when the device releases it — which is exactly
what a confirmed barge-in does, so reading it afterwards reported "nothing was played" for
the one case the run wants.

`barge_in.first_candidate_offset_ms` records where the first candidate actually landed, so
the 400 ms gap is evidence a reader can check rather than a constant buried in the runner,
and a sweep can move it. It is declared by the proposed manifests only: a runner offers
its measurements and the DECLARATION selects them (`declared_metrics`), because reporting
a metric a declaration never mentioned makes `check_run_against_spec` refuse the completed
run.

### What the hardware profiles still cannot prove

- **Nothing about a provider.** The Realtime session is the deterministic double on both
  profiles, so the provider's VAD onsets are raised by the runner. What is real is the
  microphone, the room, the canceller and the gate that decides on them.
- **Nothing repeatable about a room.** A measurement taken in this room, on this machine,
  at this volume is evidence about that. A hardware run is a sample, not a regression
  gate, which is why no hardware profile belongs in a routine suite.
- **`hardware:auto` cannot prove the gate opens.** Only a human can, which is the guided
  profile.
- **They have never been executed against a real device.** Slice 09 implemented and tested
  both over a `sounddevice` double with a simulated room
  (`tests/fakes/sounddevice_double.py`); the first real open is the Human gate
  HV-TL-HW-01. Everything under `tests/integration/test_testlab_hardware_devices.py` is
  written and left skipped, and its result is "unverified", not "passed".

## Guided runs

`jarvis/testlab/hardware/prompts.py` and `channel.py`. Locked decision 11: on
`hardware:guided` the human is an explicit scenario actor. This is the whole contract of
that, and it contains no terminal, no HTTP and no UI — a runner executes inside a worker
process with no console attached, so it cannot assume one.

### The prompter contract

```
GuidedPrompt {prompt_id, action, text, deadline_s, phrase, expects_voice, strict_timing}
GuidedPrompter.present(prompt) -> PromptReply {acknowledged, refused, note}
```

| Piece | Rule |
|---|---|
| `prompt_id` | Stable and authored. It is how the CLI, the UI and the stored evidence name the same step, and how an acknowledgement is matched to what it answers. Same type as `turn_id`. |
| `action` | Closed: `remain_silent`, `say_phrase`, `interrupt`, `acknowledge`. A presenter renders one affordance per action. |
| `text` | The sentence shown to the human. Authored, bounded (240 chars), never user data. |
| `deadline_s` | Part of the CONTRACT, not a hint. A presenter must show how long the human has and how much is left: a step with no visible countdown is indistinguishable from a frozen run. |
| `phrase` | The exact words to say. Required for `say_phrase` and `interrupt`. |
| `strict_timing` | A late answer voids this step's measurement. True for `interrupt`, where the timing IS the measurement. |

**The presenter reports the answer; it never reports the timing.** `GuidedSession` stamps
the call on both sides, so no presenter can understate how long a human took, and a slow
presenter cannot be mistaken for a slow human — the run measures the whole round trip,
which is what the person experienced. `GuidedSession` also owns the deadline, so every
presenter is bounded identically.

Implementations:

| Presenter | Where |
|---|---|
| `HeadlessPrompter` | the test double: answers at once, after a delay, never, or refusing |
| `FilePrompter` / `PromptWatcher` | what a worker really uses, and the half Slices 10 and 11 render |
| a CLI | Slice 10 |
| the Control Center panel | Slice 11 |

### The channel

Two files in the run scratch, beside `job.json`, `heartbeat.json` and `cancel.json`:

| File | Written by | Says |
|---|---|---|
| `prompt.json` (`jarvis.testlab.guided_prompt` v1) | the worker | "show this to the human, they have this long" |
| `prompt-ack.json` (`jarvis.testlab.guided_ack` v1) | the presenter | "they answered, here is what they said" |

A `sequence` number matches the two, so a stale acknowledgement left by a previous step
can never answer the current one — the failure a naive "is the ack file there?" poll would
produce on every second prompt. Files rather than a socket, for the same reason
`result.json` is a file: the record has to survive either side dying. A presenter killed
mid-prompt leaves the prompt on disk for the next one; a worker killed leaves no ack to be
misread. Both files are removed when the step ends, including when its deadline passes.

### Human-as-actor rules

**A human is never a defect.** Only the product can fail a diagnostic.

| What the human did | Outcome | Reads as |
|---|---|---|
| Answered within the deadline | `acknowledged` | the step happened |
| Answered within the deadline + `LATE_GRACE_S` (15 s) | `late` | evidence; voids the step only when it declares `strict_timing` (`testlab_guided_prompt_late`) |
| Never answered | `timed_out` | `testlab_guided_prompt_timed_out` → `inconclusive` |
| Declined | `refused` | `testlab_guided_prompt_refused` → `inconclusive` |
| The presenter broke | `prompter_failed` | `testlab_guided_prompter_failed` → `inconclusive` |
| Did something OTHER than what was asked | recorded as an observation | the DIAGNOSTIC decides |

That last row is the interesting one, and it is deliberately not decided here. Each
`PromptRecord` carries what the microphone observed while the step was open, and
`followed` compares it with `expects_voice`. The same observation means opposite things:
speech during `remain_silent` voids a self-echo measurement, speech during `interrupt` IS
the measurement. `jarvis.testlab.hardware.prompts` records; the runner decides
(`require_silent_phase`).

"Did the human make a sound?" is one object, `RoomVoice`, built the same way in every
phase, from three measurements. What separates them is whether they can be Jarvis:

| Measurement | Can it be Jarvis? | Catches | Blind to |
|---|---|---|---|
| the room with NOTHING playing, before the step | no | somebody already talking | somebody who starts during the step |
| the same, after the step | no | somebody who started during it and kept going | a sound shorter than the step |
| the product's `near_end` signal, during the step | **yes** — it also rises on the canceller's residual | somebody who starts and stops inside the step | — |
| the microphone's in-window peak | **yes** — it carries the echo at a voice's level | nothing it can be trusted for | — |

So `RoomVoice.certain` is any of the three sources that cannot be Jarvis — a level with
nothing playing, a sustained near-end run with nothing playing, or a level measurably above
the CONTROL step — and `RoomVoice.suspected` is the near-end verdict while he was speaking.
The control is the silent phase of the same run: it plays the same utterance at the same
volume into the same room with nobody in it, so its in-window peak IS this room's echo, and
`VOICE_OVER_ECHO_DB` (10 dB) above that is something the stimulus does not explain. The
measured separation is about 21 dB (an empty room reads about -21 dBFS in-window, a person
about -0.0), so the margin is wide on both sides. The near-end run is counted as an
UNBROKEN run and not a total: an empty room produces 3 to 6 isolated near-alone frames over
a thousand while the floor re-settles, and six of those scattered across eight seconds
certified a person who was not there.

A CLAIM then takes what it needs:

- **"nobody spoke"** (the `remain_silent` step) is voided by `certain`, and by nothing
  else. It used to be voided by a suspicion whenever the phase had also confirmed a
  barge-in — which reads as caution and was the opposite. A confirmation REQUIRES a
  near-end candidate, so `confirmed > 0` implies `near_end_seen`, and that branch fired on
  every run where the gate opened on Jarvis's own echo: 2 to 5 runs in 10 at the declared
  default. The blocking `no_false_barge_in` assertion was therefore only ever evaluated
  against zero, and the one finding this diagnostic exists to produce could not be
  reported. When the silent windows are below the voice floor, the confirmation IS Jarvis's
  own echo, `barge_in.false_confirmed_count` is reported, and the declared assertion
  decides. That is the finding, not a reason to abort.
- **"somebody DID speak"** (the `interrupt` step) needs `certain` and never `suspected`.

That last line is the fix for a defect that would have certified the one claim only a
person can make, with nobody in the room. Both gates used to be satisfiable by Jarvis's own
sound: the in-window peak carries the echo at a voice's level, and the near-end signal also
rises on the canceller's residual over a long utterance. Empty room, no human, scripted
acknowledgements: clean at 1 000/1 500/2 000 ms, and from **2 500 ms upward**
deterministically `barge_in.true_confirmed_count = 1` with the run reading `passed`. The
proposed guided manifest's default is 8 000 ms, so the Human gate at defaults would have
certified it. A short phrase is covered too, and it took a third source to do it: a confirmed barge-in
STOPS the playback, so a person who said their phrase is silent again long before the
silent windows are sampled — the better the barge-in worked, the emptier its own evidence
was. Five runs of a one-phrase interrupt produced zero measurements, one of them with the
gate open and the person plainly heard.

**The two halves get the same number of chances.** The silent phase raises
`echo.candidate_count` candidates and the stack rejects each one, which teaches the
detector that this near-end is echo (`_release_near_end(learn=...)` after more than one
rejection). Giving the positive half a single onset to overturn that made the verdict a
coin flip at the declared default: 10 replays gave 4 measured, 3 failed with the person at
full scale for the whole 8 s and 807-857 near-end frames, 3 refused. The interrupt phase
now raises the same count, stopping as soon as the gate opens, and each one is still gated
on the person being audible so an empty room gets none of them. After: 19 of 20 replays
measured the claim, every one of them with `barge_in.true_confirmed_count >= 1`.

**The provider reports speech when there is speech.** On the interrupt step the run raises
the provider's VAD onset only once the capture reports a voice this stack would act on;
with nothing in the room it declines, `barge_in.true_confirmed_count` stays zero, and the
claim is reported as unmeasured. `DeviceAudio.heard_voice_since(mark)` is the one place
that question is asked, and what it asks took three attempts to get right:

| Signal | Why it is wrong on its own |
|---|---|
| the `NEAR_END` signal | an EDGE: it fires once, at the instant speech is CONFIRMED, and the detector then stays latched for the rest of the utterance. A genuine voice arriving after the gate had already latched raised NOTHING — the detector reported `near_end` on all 310 frames of it and the run missed every one. 10 failures in 10 runs of the true-positive case |
| a decibel margin over the echo | asks a person to beat a level the product has already discounted; fragile, and tuned |
| the per-frame `near_end` verdict alone | weaker than the detector's own rule for calling something speech, so the stimulus is raised before the stack would act on it |
| the `latched` state alone | can be left over from the ECHO, so it fires before the voice has arrived at all |

What it uses is both of the last two: `NEAR_END_FRAMES` (6 frames = 60 ms, the detector's
own `min_run_frames`) of the per-frame verdict SINCE the mark, and the detector currently
holding its latch. The frames say the voice in question is really in the capture; the latch
says the stack would act on it. The per-frame verdict reaches the Test Lab through the
production `CaptureObserver` seam (`NearEndWatch`), which is delivered for every frame
whatever the latch and the gate are doing.

Being permissive here is safe and deliberate: an onset only asks the stack to DECIDE. What
the run may CLAIM stays gated on `RoomVoice.certain`, a silent-window measurement nothing
Jarvis does can produce. An echo can get an onset raised; it can never get a claim
certified. Measured at 1 000 / 3 000 / 8 000 ms, the two sides are 65 dB apart: an empty
room reads -65.2 dBFS after the step and a person reads -0.0 to -0.4, against a -50 dBFS
threshold.

**And a zero is never a silent pass.** When the human acknowledged the interrupt step and
the stack confirmed nothing, the claim the guided profile exists to make was not made.
Whether that reads as a VERDICT or as a measurement failure is a property of the
DECLARATION, exactly as it is for scenario expectations: a diagnostic that declares a
BLOCKING assertion on `barge_in.true_confirmed_count` has said "zero is a product
failure", and the metric is reported so the supervisor can fail the run on it; a
diagnostic that has not said that cannot express the verdict, so the run ends
`testlab_guided_claim_unmeasured` -> `inconclusive`.

### The evidence

`guided_prompts.json` (`jarvis.testlab.guided_transcript` v1, a bounded `report`),
committed in a `finally` — the transcript of a run a human abandoned is exactly the
evidence worth keeping. Per prompt: the declaration, `shown_at` and `acknowledged_at`
(UTC ms, the Conversation Events wire form), `response_ms`, the outcome, the free note,
`observed_voice`, `observed_peak_dbfs` and `followed`. Plus the run totals:
`prompt_count`, `acknowledged_count`, `late_count` and the `unfollowed` ids.

**And the PROVENANCE of `observed_voice`** (`RoomVoice.to_dict`): `room_before_dbfs`,
`room_after_dbfs`, `window_peak_dbfs`, `near_end_seen`, `near_end_frames`,
`near_alone_frames`, `alone_run_frames`, `window_frames` (so a frame count reads as a
rate — 61 frames of 8 s and of 1 s are not the same fact), `heard_alone`,
`louder_than_control`, `control_peak_dbfs` and `voice_over_echo_db` where they apply,
`barge_in_decided`, `barge_in_confirmed`, `voice_floor_dbfs` and `certain`. The two levels
are kept apart: `window_peak_dbfs` carries the echo, `observed_peak_dbfs` is the quiet-room
level, and merging them into one field left a reader unable to tell a loud room from an
echo-triggered confirmation — which is exactly what the operator's triage turns on.
Without it a record said `voice: true` and a reader had no way to tell a person from
Jarvis's own echo — which is precisely how an empty room certified a human interrupt. A
stored guided record now carries the numbers the decision was made on.

A guided run may address the human at most `MAX_PROMPTS_PER_RUN` (64) times. A scenario
that needs more is not a diagnostic, it is a chore.

**Deadlines are derived, so watch the parameter.** The guided seed's per-phase deadline is
`output.duration_ms` plus `DEFAULT_PROMPT_DEADLINE_S` (30 s), capped by
`MAX_PROMPT_DEADLINE_S` and by what is left of the run budget. A declaration that sets
`output.duration_ms` to two minutes therefore asks a person to hold still for two and a
half, which is a long time to be silent on purpose. The manifests that declare it say so
on the parameter.

### Presence: the fifth mechanical gate

A guided run spends a PERSON's attention, and a prompt nobody is there to see times out
into `inconclusive` after burning the whole run budget. So, beside the four `live` gates:

| Gate | Where | Refusal |
|---|---|---|
| Capability | `check_profile_permission` at `submit` | `permission_denied` (`human_presence` missing), outcome `refused` |
| Presence | the supervisor's reservation path: `JARVIS_TESTLAB_GUIDED=1` in its environment | `human_presence_missing`, outcome `refused` |

The declared `human_presence` capability says the DIAGNOSTIC needs a person; the opt-in
says one is at this keyboard right now. Nothing derives it and nothing defaults it on,
exactly as for `JARVIS_TESTLAB_LIVE`. It is checked before the device contention gate and
before the device lease, so a refusal names the first cause and the one thing the gate
TAKES is still taken last.

### The guided vocabulary

Four primitives, `hardware:guided` only, data like every other
(see "Scenario primitives"): `human.silence`, `human.speak`, `human.interrupt`,
`human.acknowledge`. Each carries a `prompt_id` and an optional `deadline_ms`; the spoken
two require the `text` the person says. `GuidedExecutor` adds them to the shared handler
table and replaces nothing, which `resolve_handler` enforces.

On a hardware profile `time.wait` is a REAL wait: there is a room, a driver and possibly a
person, and pretending three seconds passed when they did not would measure nothing.

### Registered implementations

| Name | Profile | Runner | Measures |
|---|---|---|---|
| `testlab.scenario.hardware_auto` | `hardware:auto` | `HardwareScenarioRunner` | `scenario.steps_performed`, `.checkpoints_reached`, the two expectation metrics, `audio.played_ms`, `audio.captured_ms` |
| `testlab.scenario.hardware_guided` | `hardware:guided` | `GuidedScenarioRunner` | the same, plus `guided.prompt_count`, `guided.late_prompt_count`, `guided.unfollowed_count` |
| `voice.self_echo.hardware_auto` | `hardware:auto` | `SelfEchoHardwareRunner` | the four `voice.self_echo` metrics, with the gate decided in a real room |
| `voice.self_echo.hardware_guided` | `hardware:guided` | `SelfEchoGuidedRunner` | the same, plus `barge_in.true_confirmed_count` and the two guided counts |

The last two are registered but **not published**: no official manifest declares a
hardware profile yet. Two are rendered and awaiting approval in
`tasks/jarvis-category2-test-lab/slices/09-hardware-guided/`:

| Manifest | Claim | Assertion |
|---|---|---|
| `proposed-voice.self_echo.v3.json` | `hardware:auto` — Jarvis does not interrupt itself on its own echo in a real room | the existing blocking `no_false_barge_in` |
| `proposed-voice.barge_in_response.v1.json` | `hardware:guided` — a real human voice DOES get through the gate, and the echo still does not | blocking `real_voice_interrupts` (`ge 1`) and blocking `no_false_barge_in` |

Two diagnostics and not one version of one, because the positive claim needs a BLOCKING
assertion and assertions are diagnostic-level: a blocking assertion on a guided-only
metric would make every `virtual` and `audio` run of the same diagnostic inconclusive.
Registering a name makes a diagnostic runnable, never permitted.

`SelfEchoGuidedRunner` speaks TWICE, one whole turn per phase: the first while the human
is asked to be silent (every confirmation is FALSE), the second while they are asked to
interrupt (a confirmation is TRUE). Two turns and not two answers to one question, because
the first utterance ends when it is interrupted or runs out, and a second phase sharing it
would have nothing left to interrupt. The phases are counted separately, so a barge-in the
human caused can never be reported as a false positive.

## Device contention

`jarvis/testlab/devices.py`. READINESS B9: the workstation Jarvis owns the laptop
microphone and speakers continuously (`continuous_brain`), so a Test Lab run that needs
an audio device must detect that and **refuse** — never open the device, never
interrupt a live conversation.

### The mechanism

Read-only evidence the live runtime already publishes in its runtime root
(`jarvis/runtime/visual_signals.py`). Nothing in the Test Lab writes, resets or deletes
any of it: the Control Center already resets the signal bus when it observes a stale
heartbeat, and a second resetter would race it.

| File | Read as |
|---|---|
| `.voice_heartbeat` | a float `time.time()` rewritten every second while Voice runs. Fresh (age at most 5 s, the Control Center's own `VOICE_HEARTBEAT_MAX_AGE_S`, pinned equal by a test) means **busy** |
| `.voice_runtime` | `architecture` and `runtime_state`, quoted in the refusal so a human knows who holds the device |
| `.voice_state` | `listening` / `speaking` / `thinking`, and recent (at most 60 s): **busy** even when the heartbeat is stale, because a crash mid-sentence leaves it behind |

`LiveVoiceRuntimeProbe` returns `free`, `busy` or `unknown`;
`DeviceContentionDetector` combines probes **fail-closed**: one `busy` decides, one
`unknown` is enough to refuse, and only unanimous `free` frees. A probe that raises
becomes `unknown`, so a broken probe makes the detector more careful, never less.
`ContentionReport.available` is true for `free` alone: not knowing whether the user is
talking to Jarvis is not a licence to take the microphone.

The supervisor derives the runtime root from its `settings_path`
(`control-center-settings.json` lives in the runtime root) and never from
`JARVIS_RUNTIME_DIR` — a worker's environment points at its own scratch, and a
supervisor that inherited one would probe an empty directory and cheerfully report the
microphone free.

### Where it is enforced

In the **supervisor's reservation path** (`_start_ready`, then `_external_gate`), before
`self._reserved |= capabilities` and before any worker is spawned. Not in a runner: by
the time a runner runs, a process has been started and the microphone is a fraction of
a second from being opened.

| Situation | Failure code | Outcome |
|---|---|---|
| Devices held, or availability unknown, at reservation | `device_contention` | `refused` |
| A second Test Lab supervisor holds the shared lease | `device_contention` | `refused` |
| The live Jarvis appears WHILE a device run executes | `device_contention_during_run` | `inconclusive` |
| The gate itself raises (an injected detector breaks) | `supervisor_fault` | `crashed` |

**A gate that breaks refuses its run.** The detector is injected — Slice 10 composes
one — so an exception there is code the supervisor does not own. Letting it escape left
the run `queued` with no `blocked_since`, so `max_queue_wait_s` never applied and nothing
would ever make it terminal; the same exception on the mid-run probe killed the
`_execute` task with no diagnostic at any level and recorded `worker_result_invalid`, a
supervisor fault blamed on the worker. Both are now wrapped, emit
`testlab.run.gate_failed` / `testlab.run.supervision_failed` at `error`, and conclude the
run `supervisor_fault` — `crashed`, because it is a defect of ours and not a finding
about the product. A test asserts the invariant behind both: no submitted run can remain
non-terminal after a gate or supervision fault.

A run holding a device capability is re-probed every `device_probe_interval_s` (1 s)
**from the moment the worker is spawned**, not from its first heartbeat, and stopped
cooperatively the moment contention appears; the failure detail names what was seen. The
startup window matters: the reservation is held while the worker starts, and on a loaded
host that is up to `startup_timeout_s` (60 s by default) during which the live Jarvis
could come back. The worker has opened nothing yet, so it is also the cheapest moment to
give the devices back. A stop asked for during startup is ended by the cancel grace,
because a worker that has not begun cannot read the cancel marker. A `live` run declares no device capability, so none of this applies to it, and the
`audio` profile as proposed declares none either — the gate exists for the
`hardware:auto` and `hardware:guided` profiles of Slice 09, and for any manifest that
gives an `audio` profile a device capability.

### The Test Lab device lease

`DeviceLease` is an exclusive OS lock file (the `EntryLock` idiom), taken for the whole
of a device run and released by the kernel if the supervisor dies. Its default path is
`<work_root>/.device.lock`, where it only excludes a supervisor from itself — which
reservation already does. It earns its place when **two work roots** (two worktrees of
this repository) are pointed at one path: the second run is then refused instead of
racing for the one laptop microphone. `RunSupervisor(device_lease_path=...)` sets it,
and `None` disables it.

It is **not** protection against the live Jarvis or the Control Center audio test:
neither takes this lock, and the Control Center's own `_audio_test_lock` is an
in-process `asyncio.Lock` that no other process can see. Teaching the live runtime to
respect a shared lease is a change to `jarvis/runtime/` that Slice 08 may not make
(other worktrees hold uncommitted work there), and it is the obvious follow-up.

### Limits, stated plainly

- **"We could not look" is never "free".** An ABSENT signal file is evidence — the live
  runtime never wrote it. A signal file that is oversized (over `MAX_SIGNAL_BYTES`),
  locked by another process, a directory in the file's place, or unreadable for any
  other reason is the ABSENCE of evidence, and reads `unknown`, which refuses the run.
  The two collapsed into one `None` until the Slice 08 rework, which was a fail-OPEN
  hole in a fail-closed detector: a 100 KiB `.voice_heartbeat`, or one replaced by a
  directory, reported the microphone free. A runtime directory that does not exist at
  all is a configuration error and also reads `unknown`.
- **False "busy".** A Voice process that is alive but whose device failed to open still
  beats, and we refuse. Refusing a run we could have made is the safe direction.
- **False "free".** A Voice process holding the device while its heartbeat loop is
  wedged (the loop and the audio callback are different threads) looks free after 5 s.
  So does a Jarvis writing to a different runtime root than the one the supervisor was
  given. Neither can be closed without a change to the live runtime.
- **Jarvis starting mid-run.** Nothing here prevents it. Re-probing bounds the overlap
  to at most one poll interval and ends the run `inconclusive`; making it impossible
  needs a lock the live runtime takes.
- **Not an authority on the device itself.** The detector answers "is the live Jarvis
  using the audio devices", not "can this device be opened". A third application holding
  the microphone is invisible to it; only the real open finds that, and it reports it as
  `MeasurementUnavailable` — "Hardware profiles", the device failure mapping.
- **`AudioBackendProbe` is offered, not imposed.** `hardware_contention_detector`
  composes the live-voice probe with one that asks PortAudio whether this host has any
  device at all, fail-closed and never raising. `RunSupervisor` still builds
  `default_contention_detector`, because adding a native query to every device
  reservation is a cost a caller should choose; Slice 10 composes the other one for a
  workstation that runs hardware profiles.
- **Rejected alternative: probing the Core port.** Binding `core_host:core_port` would
  detect a running Jarvis Core, but Core can run with voice stopped, so it would refuse
  runs that were perfectly safe. The heartbeat is the signal that means "voice".
- **Rejected alternative: an exclusive device open.** It is authoritative, and it is
  exactly what the Slice may not do: a successful exclusive open takes the device, and
  a WASAPI shared-mode open succeeds even while Jarvis holds it, so a shared probe
  proves nothing.

## Cost and budget

Three separate things, kept separate (`jarvis/testlab/live/cost.py`).

**Usage is measured.** `UsageTotals` folds the `voice.realtime.usage` journal lines the
Realtime session already emits (`input_tokens`, `output_tokens`, `duration_seconds`,
`source`, plus the conversation and session ids). The provider reports **cumulative**
session totals, so each update replaces the counters; adding them would multiply the
bill by the number of updates and abort every run on its third line. A malformed
payload contributes what it can and raises nothing.

**Price is configuration.** There is no built-in price table and this Slice does not
add one: prices change, and a stale hard-coded table is worse than none because it
reads as authority. `CostModel.from_settings` parses the Control Center `live_pricing`
setting through `jarvis/runtime/pricing.py` (`TokenPricingMetadata`, else
`PricingMetadata`), so a Test Lab estimate uses the same arithmetic and the same
provenance fields (source, effective date, schema version) the Live status surface
uses. The run reads it from the **settings copy in its own scratch**
(`<runtime_dir>/control-center-settings.json`), not from a diagnostic parameter: a
price is configuration of the workstation, not an input of the experiment. Anything
that does not parse leaves the model unpriced rather than guessing.

**Budget is the declared bound.** `CostBounds.max_cost_usd` of the profile, already
compared to the caller's `ResourceGrant` before the run is queued. `CostBudget` is the
mid-run half: it recomputes the estimate on every usage update and raises
`CostBudgetExceeded` the moment it crosses. That exception lives on the runner seam
(`jarvis.testlab.runners`) and subclasses `MeasurementUnavailable`, with its own
failure code `cost_budget_exceeded` reading `inconclusive`, so "we stopped paying" is
never confused with "the product could not be measured" and never reads as a crash.

**Without a price, the money bound is the time bound.** An unpriced model records
`cost_usd: null` and `cost_basis: "unpriced"`, and the only thing bounding spend is the
profile's `max_duration_s`, which the supervisor enforces by killing the worker. That
is a real limit, stated here rather than papered over.

Every live run commits `live_profile.json` (a bounded `report` artifact,
`jarvis.testlab.provider_metadata` v1): `provider` (provider, `model_id`, `voice`,
`config_fingerprint`, the provider's own `session_id`), `cost` (budget, estimate,
basis, model id, folded usage) and `chain` (the same audio-chain facts an `audio` run
records). No key, no transcript, no host path.

## Audio artifacts

An `audio_clip` is written only when **all three** hold: the caller asked
(`RunRequest.allow_audio_artifacts`), the profile can produce one (`audio`,
`hardware:auto`, `hardware:guided`) and the supervisor's own store was built with
`ArtifactWriteLimits(allow_audio=True)`. The supervisor sets `WorkerJob.allow_audio`
from those three, and the worker builds its store with it; a job that claims `true`
against a store built without audio is still refused at write time, which is the point
of having the limit on the store as well.

`store_clip` turns a refusal into a logged fact instead of a failed run: losing the
optional evidence must not lose the measurement. Caps are the Slice 02 ones (32 MiB per
clip, retention `max_bytes_by_kind` 256 MiB), and the paths stay far inside the
171-character artifact budget (`capture.wav`, `audio_profile.json`,
`live_profile.json`).

### Validation

```powershell
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/unit/test_testlab_devices.py tests/unit/test_testlab_audio.py tests/unit/test_testlab_hardware.py
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/integration/test_testlab_audio_runners.py tests/integration/test_testlab_live_runners.py tests/integration/test_testlab_hardware_runners.py

# the acoustic seeds at their DECLARED DEFAULTS, which is what a real caller gets
.venv/Scripts/python -m pytest -q -p no:cacheprovider -s tests/integration/test_testlab_audio_runners.py tests/integration/test_testlab_hardware_runners.py -k defaults
```

**Run the acoustic seeds at their declared defaults, not only at a fast duration.** Both
of the defects above lived in the gap between the ~1.2 s every test used and the 8 000 ms
the manifests declare, and neither was visible at 1.2 s. The defaults cases are part of
the default suite (about 2 s for `audio`, about 7 s for each hardware profile) and they
assert the DIAGNOSTIC — that it measures, decides on every candidate it raises, honours
the pre-roll and reports a verdict derived from its metrics — never a particular acoustic
outcome, because that outcome is the measurement and on a long utterance it is still an
open question (`Issues/self-barge-in-after-seconds-of-speech.md`).

Opt-in, never in the default suite. Each switch is a deliberate act:

```powershell
# enumerate the real devices and run the contention detector against the live runtime root
$env:JARVIS_TESTLAB_AUDIO = "1"
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/integration/test_testlab_audio_devices.py

# additionally open the real microphone and speaker for two seconds. A SECOND switch, and
# the test skips rather than running unless the detector says the devices are free.
$env:JARVIS_TESTLAB_AUDIO_PLAYBACK = "1"

# a REAL, PAID provider session
$env:JARVIS_TESTLAB_LIVE = "1"
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/integration/test_testlab_live_runners.py

# the hardware profiles on the REAL speaker and microphone. Plays a tone out loud and
# records the room; it SKIPS rather than runs unless the detector says they are free.
$env:JARVIS_TESTLAB_HARDWARE = "1"
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/integration/test_testlab_hardware_devices.py

# additionally the guided flow, which needs a HUMAN at the keyboard following the prompts
# (HV-TL-HW-01; the operator script is in slices/09-hardware-guided/operator-script.md).
$env:JARVIS_TESTLAB_GUIDED = "1"
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

## Native API, CLI and HTTP

Slices 01-09 built every piece of the Test Lab and deliberately wired none of them: the
run store took an injected root, the supervisor took an injected work root, catalog root,
settings path and diagnostics sink, and nothing decided where any of them lived. This
section is that decision, made once, plus the three surfaces that read it.

```text
jarvis/testlab/composition.py   what the Test Lab IS: roots, policies, stores, catalog,
                                supervisor, sweep runner, and the capability grant
jarvis/testlab/api.py           TestLabApi: every operation, once, as async calls
                                returning documented JSON-ready shapes
jarvis/testlab/cli.py           python -m jarvis.testlab (humans and agents)
jarvis/testlab/presenter.py     the guided presenter: prompt, deadline, live countdown
jarvis/testlab/http.py          /api/testlab/... on the Control Center's aiohttp app
```

One rule holds the three together: **the CLI and the HTTP routes call the same facade**,
so they cannot disagree about a record, an outcome or a comparison. A second rule holds
the whole Slice: **nothing here decides anything**. The outcome of a run is
`RunOutcomeSummary` derived by the domain, the comparison is `compare_runs`, the sweep
summary is the stored document, the retention plan is `plan_retention`. There is no
threshold, no heuristic and no judgement in this layer.

### Composition

`TestLabConfig.from_environment()` resolves every root from `V2Settings` /
`JARVIS_RUNTIME_DIR`, and `TestLab` builds the pieces lazily:

```text
<runtime>/testlab/runs/<run_id>/     run records and artifacts       (Slice 02)
<runtime>/testlab/sweeps/<id>/       sweep records and summaries     (Slice 07)
<runtime>/testlab/bundles/<id>/      DiagnosticBundles               (Slice 03)
<runtime>/testlab/locks/             per-entry writer locks (ids are prefixed, so runs,
                                     sweeps and bundles share this directory)
<runtime>/testlab/work/              supervisor work root: one scratch per run, the
                                     work-root lock, the device lease (Slices 05, 08)
```

Four properties are load bearing:

- **The work root is never the store root.** `RunSupervisor` removes every directory
  directly under its work root that no live run claims, so sharing the path would delete
  `runs/` on the first `start()`.
- **Nothing is created until first use.** Building a `TestLab` reads no file and makes no
  directory; `python -m jarvis.testlab --help` touches nothing.
- **One store instance is shared** by the supervisor, the CLI and the routes. The Slice 07
  listing cache is per instance, so a second one would answer from cold disk and the two
  could disagree about a record that became corrupt.
- **The contention detector reads the LIVE runtime root**, never a run scratch (which is
  empty of voice signals by construction and would always read "free").

```python
from jarvis.testlab.api import TestLabApi
from jarvis.testlab.composition import build_test_lab

api = TestLabApi(build_test_lab())          # reads nothing yet
await api.start()                           # takes the work root, adopts orphan runs
run_id = (await api.submit_run("voice.self_echo", "virtual"))["run_id"]
view = await api.show_run(run_id, wait_s=30)
await api.aclose()
```

### Where a capability grant comes from

Never from a request, and never from a CLI flag: a caller that can grant itself
`realtime_provider` has no gate left. The grant is read by the composition layer from the
**process environment**, using the switches the supervisor already enforces in its own
reservation path, plus one name for the device capabilities (the supervisor gates devices
by contention detection and a lease, not by a variable):

| Environment variable | Grants | Default |
|---|---|---|
| `JARVIS_TESTLAB_LIVE=1` | `realtime_provider`, `llm_provider` | off |
| `JARVIS_TESTLAB_HARDWARE=1` | `audio_input_device`, `audio_output_device`, and the native PortAudio reachability probe in the contention detector | off |
| `JARVIS_TESTLAB_GUIDED=1` | `human_presence` | off |
| `JARVIS_TESTLAB_MAX_COST_USD` | the money budget of ONE run | `0` |
| `JARVIS_TESTLAB_AUDIO_ARTIFACTS=1` | lets the store keep `audio_clip` artifacts | off |

The default grant is empty, which is exactly the `virtual` profile: free, no device, no
provider, no human. A caller may only NARROW it: `TestLabApi.submit_run(grant=...)` and
the HTTP `grant` field are intersected with the environment's by `narrow_grant`, so the
worst a request body can do is ask for less. Setting a variable for the process is the
operator's act, it is visible in the process that will spend the money or take the
microphone, and it gives the CLI and the Control Center the same authority by
construction.

**A narrowing grant is a complete document.** `ResourceGrant.from_dict` requires all
three fields; a partial object is refused with `testlab_fields_mismatch`, not silently
completed, because a missing `max_cost_usd` would have to mean either "zero" or
"whatever you allow" and guessing either way is wrong:

```json
{"grant": {"capabilities": ["realtime_provider"], "max_cost_usd": 0.5, "max_duration_s": null}}
```

**Reading the environment can never fail.** `install_testlab_routes` is called from
`ControlCenter.__init__`, so an exception while reading a Test Lab variable would stop the
whole Control Center from being constructed — and would take the CLI away exactly when
somebody is trying to look at a run. So every unusable value falls back to a usable one,
in the refusing direction, and SAYS SO: an unreadable, negative or non-finite budget reads
`0`; a budget above the `MAX_PROFILE_COST_USD` ceiling a run may declare (1000 USD) is
clamped to it, because `ResourceGrant` would otherwise refuse it outright. The sentence
travels on `TestLabConfig.grant_refusal`, appears as `config.grant_refusal` in
`/api/testlab/status`, and the CLI prints it before every command — a grant quietly
reduced is a surprise waiting to be blamed on the diagnostic.

Everything else is inherited, not re-decided. The live opt-in, the guided presence opt-in,
device contention, the device lease, the cost budget and the audio opt-in stay in the
supervisor's reservation path (Slices 05, 08, 09); no CLI flag and no route reaches
around them, and a refusal is persisted as an `errored` run with its own failure code.

### CLI

`python -m jarvis.testlab [global options] <command>`, human-readable by default and
`--json` for agents. The global options are `--json`, `--runtime-root PATH` and
`--data-root PATH`, and they go BEFORE the command (argparse's own convention): after it
they are an unrecognized argument and the program exits 2 with its usage.

<!-- cli-commands -->

| Command | Does |
|---|---|
| `list` | every official diagnostic, latest version, with its profiles |
| `describe ID [--version N]` | one version: profiles, parameters, metrics, assertions, scenario |
| `run ID [--profile P] [-p N=V] [-o N=V] [--scenario FILE] [--guided] [--no-wait] [--timeout S]` | queue one run, follow it, report its outcome |
| `status [RUN_ID]` | one run, or the Test Lab itself (roots, grant, queue, devices, storage) |
| `cancel RUN_ID [--reason ...]` | ask a run to stop (cooperative, then the supervisor kills it) |
| `runs [--diagnostic-id ...] [--status S] [--profile P] [--sweep-id ...] [--limit N] [--after CURSOR]` | query stored runs |
| `show RUN_ID` | one run with metrics, assertions, outcome, artifacts and its declaration |
| `artifact RUN_ID PATH [--output FILE]` | read one stored artifact, verified against its sha256 |
| `compare BASELINE CANDIDATE` | per-metric deltas, assertion changes, incomparabilities |
| `sweep [ID] [--spec FILE] [--axis N=V1,V2] [--repetitions N]` | execute a sweep and report every point |
| `sweeps [--id TLS] [--limit N]` | stored sweeps, or one with its summary |
| `capture [--conversation-id ...] [--session-id ...] [--start T] [--end T] [--no-events] [--no-store]` | normalize a real session into a DiagnosticBundle |
| `bundles [--id TLB] [--document]` | stored DiagnosticBundles, or one with its coverage and findings |
| `retention [--apply]` | what retention would delete; `--apply` runs one upkeep pass |
| `guided RUN_ID` | attach this terminal to a running guided run's prompts |

<!-- /cli-commands -->

`--axis` sweeps a parameter by default and a setting with the `override:` prefix
(`--axis override:audio_input_device=1,2`). Values of `-p`, `-o` and `--axis` are read as
JSON and fall back to plain text, so `-p value=3` is the number 3 and `-p mode=measure` is
the string.

Only `run`, `sweep`, `cancel`, `guided` and `retention --apply` ever take the work root;
every other command reads the stores and keeps working while the Control Center holds it.
A work root somebody else holds is reported as `testlab_supervisor_work_root_busy`, never
as a hang.

**And they take it as late as they can.** `preflight()` refuses, before a Test Lab is
composed at all, everything the command line alone justifies: a malformed `-p`/`-o`/
`--axis`, and the guided tty rule. Each command then asks the catalog and the store —
neither of which needs a lock — before `_take_work_root()`. So a command that refuses
creates NO directory and holds NO lock: an unknown diagnostic, an unreadable scenario
file, an unknown run id, a bad argument and a guided run with no terminal all leave
`<runtime>/testlab/` absent on a machine where the Test Lab has never been used.
`tests/integration/test_testlab_cli_e2e.py` runs each of those command lines against a
fresh root and asserts nothing appeared.

**Exit codes.** An agent reads them before it reads anything else.

| Code | Means |
|---|---|
| 0 | the run passed, or the command succeeded |
| 1 | the run failed (a product verdict) |
| 2 | usage error (an argument this program cannot read) |
| 3 | inconclusive: could not measure |
| 4 | refused: a gate declined to run it |
| 5 | crashed: the Test Lab broke around the run |
| 6 | cancelled |
| 7 | the command itself failed (unknown id, store error, no such artifact) |
| 8 | no verdict yet (`--no-wait`, or the wait expired while the run continues) |

A sweep exits on its own status: `completed` 0, `failed` 1, `cancelled` 6. Anything the
command itself could not do — an unknown id, a store error, a body it could not read, and
any failure this program did not foresee (`testlab_cli_failed`, with its traceback on
stderr) — exits 7. Nothing reaches the shell as a bare traceback, and nothing that is not
a product verdict ever exits 1.

**Streams.** The report goes to stdout; every live line — the queued id, the progress
ticker, the guided countdown, warnings and the real cause of a failure — goes to stderr.
`--json` therefore produces a stdout that is parseable as it is. Under `--json` EVERY
failure prints a refusal document, including a usage refusal
(`{"ok": false, "code": "testlab_cli_usage", ...}`), so an agent never gets an empty
stdout for one class of failure; the exception is argparse's own exit 2 for an unknown
flag or a missing positional, which argparse prints on stderr before this program runs.
A failure the program did not foresee answers `testlab_cli_failed` with a FIXED sentence
— its type, message and traceback are on stderr only, because an agent forwarding the
document must not carry a path or a token out of a message the code happened to hold.
The progress ticker and the guided countdown are redrawn in place (``) on a terminal
and appended as plain lines when stderr is not one, so a 30-second step never scrolls its
own instruction off the screen.

**Progress.** Anything that waits shows what it is doing, how long it has been doing it
and how to get out: `| running - 12.3 s of at most 1800 s (Ctrl-C asks the run to stop)`.
`Ctrl-C` cancels the run rather than abandoning it. The wait has a deadline it cannot
outlive: when `--timeout` passes, the CLI says how long it waited, leaves the run alone
(the supervisor owns the run's own bounds) and exits 8.

**The guided presenter** (`jarvis/testlab/presenter.py`) is what `--guided` and the
`guided` command attach. For as long as a step is open it shows the authored text, the
phrase to say, a bar and a spinner that move, the seconds left and `[Enter] done  [r]
refuse`. The countdown is computed from the WORKER's `shown_at`
(`PromptWatcher.pending_shown()`), never from when the presenter happened to look, so it
can never promise time the run will not wait. When the deadline passes it sends nothing,
says how long it waited, and refuses to let a keystroke typed afterwards answer the NEXT
step:

```text
GUIDED STEP  say_it  [say_phrase]
Dites la phrase a voix haute, puis appuyez sur Entree.
Phrase to say: "jarvis quelle heure est-il"
You have 20 s.  [Enter] done   [r] refuse
  / [##################------]  15.2 s left of 20 s   [Enter] done   [r] refuse
  -> say_it: acknowledged.
```

`--guided` attaches a presenter; it grants nothing. A guided run without
`JARVIS_TESTLAB_GUIDED=1` is refused by the supervisor with `human_presence_missing`, and
the CLI prints that code and its sentence.

**A presenter is only attached where somebody can answer it.** With stdin at end of file —
a script, a pipe, CI — a reader returns immediately, and a presenter that read an empty
line as "Enter" would confirm every step the instant it appeared and record that a human
performed steps nobody performed: the one claim a guided run exists to make. Two things
prevent it. `NO_INPUT` is a distinct value from an empty line, and a reader that reaches
it answers nothing and takes the presenter out of the answering business for the rest of
the run (each step then ends on its own deadline, which is the honest outcome). And
`--guided` is REFUSED, before anything is queued, when stdin is not a terminal; `--headless`
is the operator saying they are feeding the answers in deliberately. An expired step is
announced once, not on every poll.

**The reader contract, for the next presenter.** A reader returns the line WITH its
newline: `"
"` is a human pressing Enter. `NO_INPUT`, a raised reader, a cancelled one,
a non-string, and the EMPTY STRING all mean "nobody answered" — `""` included, because a
real `readline()` gives it only at end of file and every other reader that will exist (a
websocket, an SSH session, the Slice 11 UI, a test double) ends its stream with it. The
seam is `_read_result`, and it is where B1 is prevented once for every presenter rather
than once per presenter.

### HTTP

Registered on the Control Center's existing aiohttp application by one call from
`ControlCenter.__init__` (`install_testlab_routes`). `/api/testlab` is one of the Control
Center's read-guarded prefixes, so EVERY method — not only writes — needs a loopback
`Host`, a loopback `Origin` when one is sent, and a request that is not `Sec-Fetch-Site:
cross-site`. The run store is synchronous, so every call into it runs in
`asyncio.to_thread`; no handler blocks the event loop.

<!-- testlab-routes -->

| Route | Method | Answers |
|---|---|---|
| `/api/testlab/status` | GET | composition, grant, queue, reservations, device contention, storage |
| `/api/testlab/diagnostics` | GET | `{diagnostics: [CatalogEntry]}` |
| `/api/testlab/diagnostics/{diagnostic_id}` | GET | one version (`?version=`) plus every published version |
| `/api/testlab/runs` | GET | a page of runs (`diagnostic_id`, `version`, `profile`, `status`, `sweep_id`, `bundle_id`, `limit`, `after`, `oldest_first`) |
| `/api/testlab/runs` | POST | queue a run; **202** with `{run_id}` |
| `/api/testlab/runs/{run_id}` | GET | one run with its outcome, artifacts and declaration; `?wait_s=` long-polls (at most 30 s) |
| `/api/testlab/runs/{run_id}/cancel` | POST | ask it to stop; `{held}` is false when this supervisor does not own it |
| `/api/testlab/runs/{run_id}/artifacts/{path}` | GET | the artifact bytes, verified against the recorded sha256 |
| `/api/testlab/runs/{run_id}/prompt` | GET | the open guided prompt with `remaining_s`, or `{prompt: null}` |
| `/api/testlab/runs/{run_id}/prompt` | POST | acknowledge or refuse it (`prompt_id`, `sequence`, `refused`, `note`) |
| `/api/testlab/compare` | GET | `?baseline=&candidate=`: a `RunComparison` |
| `/api/testlab/sweeps` | GET | a page of sweep records |
| `/api/testlab/sweeps` | POST | start a sweep in the background; **202** with `{sweep_id}` |
| `/api/testlab/sweeps/{sweep_id}` | GET | one sweep record plus its summary when it has one |
| `/api/testlab/sweeps/{sweep_id}/cancel` | POST | stop a sweep this process is running |
| `/api/testlab/bundles` | GET | a page of bundle summaries |
| `/api/testlab/bundles` | POST | capture a session into a DiagnosticBundle |
| `/api/testlab/bundles/{bundle_id}` | GET | one bundle summary, its coverage and its findings (`?document=1` for the whole document) |
| `/api/testlab/retention` | GET | the retention plan (nothing is deleted by reading it) |
| `/api/testlab/retention` | POST | run one upkeep pass |

<!-- /testlab-routes -->

**A request that will be refused takes nothing.** Every POST validates first and calls
`_supervised()` last, exactly as the CLI does: an unknown diagnostic, an unsupported
profile, a scenario outside the primitive vocabulary, a body over the limit, an unknown
run id on `cancel` — all answer without `<runtime>/testlab/` ever existing. Cancelling a
sweep takes no work root at all: a sweep in flight already started the supervisor, and one
that is not gets an honest `held: false`.

**Long work never holds a request open.** `POST /api/testlab/runs` answers `202` with the
run id as soon as the run is queued; progress is `GET /api/testlab/runs/{run_id}`,
optionally with `?wait_s=` (bounded at 30 s), which always answers with the current record
rather than with nothing. `POST /api/testlab/sweeps` answers `202` with the sweep id and
runs the sweep in a background task the application cancels on cleanup.

**The supervisor is started by the first request that needs it**, not when the Control
Center boots: taking the work root at boot would refuse a CLI sweep that is already
running, and an operator would find the Control Center unable to start for a reason that
has nothing to do with it. Read routes never start it.

**Every failure is a coded payload and a journal line.** Each handler is wrapped in one
boundary that answers the Control Center's own refusal shape, carrying the Test Lab's
stable code and the sentence whatever produced the failure wrote — never a generic one:

```json
{"ok": false, "code": "testlab_store_not_found", "error": "run tlr-... does not exist"}
```

The one exception is a **5xx**, which answers a fixed sentence and the code
`testlab_internal_error`. Below 500 the message is one this package wrote on purpose; the
message of a failure we did not foresee is whatever the code was holding — a path, a
token, the contents of a file — so it goes to the journal (`testlab.http.failed`, which is
local and redacted) and never into a response body.

| Status | When |
|---|---|
| 400 | a request we could not honour (bad body, unknown profile, invalid parameter) |
| 404 | an unknown run, sweep, bundle, diagnostic or artifact path |
| 413 | a body past the 256 KiB limit (`testlab_http_too_large`), said as a size and not as bad syntax |
| 409 | a lock somebody else holds (`testlab_supervisor_work_root_busy`, a store conflict) |
| 503 | a piece that did not come up |
| 500 | our own defect — an unmapped failure is 500 on purpose, never the caller's mistake |

### JSON shapes

Stable, and render-ready: Slice 11 displays them and derives nothing. Successful HTTP
responses are the shape below with `"ok": true` added.

| Shape | Fields |
|---|---|
| `run view` | `{"run": TestRun.to_dict(), "outcome": RunOutcomeSummary.to_dict()}` |
| `run detail` | the run view plus `"artifacts": [ArtifactRef]` and `"declaration": CatalogEntry or null` |
| `runs page` | `{"runs": [run view], "corrupt": [{entry, code, detail}], "next_cursor": str or null}` |
| `diagnostics` | `{"diagnostics": [CatalogEntry.to_dict()]}` |
| `declaration` | `{"diagnostic": CatalogEntry.to_dict(), "versions": [int]}` |
| `comparison` | `RunComparison.to_dict()` |
| `sweep` | `{"sweep": SweepRecord.to_dict(), "summary": the sweep summary document or null}` |
| `sweeps page` | `{"sweeps": [SweepRecord], "corrupt": [...], "next_cursor": ...}` |
| `bundle` | `{"bundle": summary, "coverage": ..., "findings": [...], "stored": status or null}` |
| `prompt` | `{"run_id", "prompt": GuidedPrompt or null, "sequence", "shown_at", "elapsed_s", "remaining_s"}` |
| `status` | `{"config", "started", "active_runs", "pending_runs", "reserved_capabilities", "active_sweeps", "contention", "storage"}` |
| `retention plan` | `{"enabled", "cutoff", "deletions", "deferred", "blocked_active", "blocked_corrupt", "unmet"}` |
| `upkeep pass` | `{"ran", "swept", "sweep_error", "skipped_active", "deleted", "delete_failures"}` |
| refusal | `{"ok": false, "code": <stable code>, "error": <sentence>}` |

`outcome` is derived ONCE, by `classify_run`, and carries `outcome`, `failure_code`,
`verdict`, `failed_assertions`, `missing_assertions`, `measured` and `score`. A caller
that re-derives a verdict from `status` is reimplementing the Slice 07 table and will get
`errored` wrong, because only the failure code says whether a run could not measure, was
refused, or crashed.

### Limits, stated plainly

- **`cancel` only reaches the supervisor of this process.** A run the Control Center is
  executing cannot be cancelled from a CLI process, and the answer says so (`held: false`)
  instead of pretending. Cancelling it means asking the process that owns it.
- **The guided channel is per run scratch**, so a presenter can only reach a run whose
  supervisor uses the same work root. Two work roots on one workstation are two labs.
- **`?wait_s=` is bounded at 30 s** so a browser or a proxy does not drop the connection;
  it answers with the current record when the bound expires, never with nothing.
- **The CLI does not expose the catalog root.** Pointing the Test Lab at another set of
  manifests is a composition decision (`TestLabConfig(catalog_root=...)`), not a flag, so
  a run is always judged by a declaration the catalog lock covers.
- **`retention` reads without the work root and `retention --apply` takes it.** Applying
  sweeps stale temporaries and deletes runs, so it must not race a run another process is
  executing; reading the plan touches nothing.
- **Paths in `status` are shown with the home directory as `~`.** That document reaches a
  browser and an agent's stdout, and the absolute form carries the account name.
- **An artifact is served as an opaque download** (`Content-Disposition: attachment`,
  `X-Content-Type-Options: nosniff`): artifacts are machine output, and some of them are
  logs a worker wrote.

## Control Center panel

The third surface, and the only one a person uses without a terminal: the **LAB** tool of
the Control Center dock opens a full-screen Test Lab panel
(`jarvis/runtime/control_center_testlab.js`, spliced into `control_center.html` at
`/*__CONTROL_CENTER_TESTLAB_JS__*/`). It calls the routes above and nothing else.

```text
TEST LAB   [ accordé : … · budget … · appareils audio … · N exécutions ]   Actualiser  ×
┌──────────────┬──────────────────────────────────────────────────────────┐
│ Diagnostics  │  (suivi de l'exécution en cours + étape guidée)           │
│  · filtre    ├──────────────────────────────────────────────────────────┤
│  · une carte │  <titre du diagnostic, id, version, domaine>              │
│    par       │  [ Préparer | Résultats | Comparer ]                      │
│    diagnostic│  …                                                        │
└──────────────┴──────────────────────────────────────────────────────────┘
```

| Onglet | Rend | Depuis |
|---|---|---|
| Préparer | une carte par profil : ce qu'il EXIGE, ce qu'il COÛTE, et ce qui l'empêche de tourner ici — avant le bouton ; les paramètres déclarés ; ce qui sera mesuré | `GET /diagnostics/{id}` + `GET /status` |
| Résultats | la liste des exécutions du diagnostic, puis pour l'une d'elles le verdict, chaque assertion avec son seuil et sa mesure, les métriques avec leurs unités, le score, les artefacts en liens | `GET /runs?diagnostic_id=` puis `GET /runs/{id}` |
| Comparer | écarts par métrique avec leur sens, changements d'assertion, et ce qui n'est PAS comparable avec la raison | `GET /compare?baseline=&candidate=` |

Four properties are load bearing, and each is pinned by
`tests/unit/test_control_center_testlab_js.py`:

- **The panel renders, it never decides.** The verdict is `outcome.outcome`
  (`RunOutcomeSummary`), the comparison is `RunComparison`, the reason a run could not be
  measured is `run.failure.detail` — the sentence the worker wrote — with its stable code
  beside it. No verdict, no threshold and no diagnosis is computed in JavaScript. The
  comparison template renders a sweep summary's `points[].comparison_to_baseline`
  unchanged, because that is the same document.
- **The one derivation is the permission gate, and it is a replay, not a guess.**
  `profileGate` runs exactly the arithmetic of `check_profile_permission` (missing
  capabilities in vocabulary order, then the money budget, then the duration budget) over
  `GET /diagnostics/{id}` and `GET /status`, and a test compares its answer to the Python
  function's, case by case. A blocked profile names the environment switch that lifts it
  (`JARVIS_TESTLAB_LIVE=1`, …). Device contention is shown as a WARNING and never blocks:
  the supervisor probes the devices again when it reserves them, and it remains the
  authority — the panel says so on the page.
- **A guided step is never acknowledged without a human click.** `createPromptGate` is the
  only path in the file to a `POST /runs/{id}/prompt`. It requires a trusted event
  (`event.isTrusted`, which a scripted `element.click()` does not carry), an open prompt,
  and a `run|prompt_id|sequence` key that has never been answered. Reading the server
  (`observe`) returns a view model and has no access to the posting function at all, so a
  poll that returns the same prompt twice, a re-render, a reconnect or a timer cannot
  answer in a person's name. A send that fails re-arms the step, because the worker
  received nothing and replaying the same `(prompt_id, sequence)` rewrites the same
  acknowledgement file. **The gate is not exported.** `window.JarvisTestLab` hands out
  `open`, `close`, `state` and a read-only `gateView()`; the gate object itself stays in
  its closure, because `isTrusted` means nothing on an object typed at a console and an
  exported gate would let any script in the page acknowledge a step in a person's name.
  Queuing a run and cancelling one are deliberately NOT gated the same way: neither claims
  that a human was present, and the guided step is the only claim the lab measures.
- **An outcome this screen does not know reads as unknown, never as running.** `readOutcome`
  falls back in the alarming direction, exactly as `outcome_of` does on the Python side
  (an unmapped failure code reads `crashed`): a panel older than the server must not
  report a finished run as still in flight. The raw value and the failure code stay on
  screen so the run can still be identified.
- **The deadline belongs to the run.** The countdown starts from the server's
  `remaining_s` (computed from the worker's own `shown_at`) and ticks down locally between
  polls so the line moves; it is clamped to `[0, deadline_s]` so the panel never promises
  time the run will not wait. At zero it says the run decides the step and that nothing was
  sent — and it does NOT disable the buttons. Two deadlines would eventually disagree.

What the panel deliberately does not do: it never starts a sweep and never captures a
bundle (both exist on the CLI), and it shows no per-step progress for a non-guided run —
`TestRun` carries no step or progress field, so the honest answer is the status, the
elapsed time and the open guided prompt when there is one.

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

The Slice 10 surfaces: the composition layer, the facade, the CLI (parsing, output shapes,
exit codes, the documented command table) and the guided presenter against a fake
`PromptWatcher`:

```powershell
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/unit/test_testlab_composition.py tests/unit/test_testlab_cli.py tests/unit/test_testlab_presenter.py tests/unit/test_testlab_http.py
```

The Slice 11 panel: its pure rendering run by node against documents the Python domain
built, the permission gate compared to `check_profile_permission`, and the rule that no
acknowledgement leaves without a click:

```powershell
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/unit/test_control_center_testlab_js.py
```

End to end, with real worker processes (one at a time, the cheap `selftest.worker`
fixture, no voice stack and no device):

```powershell
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/integration/test_testlab_cli_e2e.py tests/integration/test_testlab_http_routes.py
```

Opt-in real-session smoke test. It reads the local `runtime/trace.jsonl`, opens
`data/state/jarvis.sqlite3` read-only, and prints counts only:

```powershell
$env:JARVIS_TESTLAB_REAL_SESSION=1; .venv/Scripts/python -m pytest -q -s -p no:cacheprovider tests/integration/test_testlab_bundle_real_session.py
```

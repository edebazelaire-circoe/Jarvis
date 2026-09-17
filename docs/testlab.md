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
  - `jobs.py` (Slice 05): `WorkerJob`, `WorkerResult`, the per-run protocol file names and the failure-code vocabulary.
- I/O modules (Slices 02, 03 and 04, see Storage, DiagnosticBundle and Catalog):
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
  - `selftest.py` (Slice 05): the `selftest.worker` test fixture diagnostic and its runner.
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
  `tests/integration/test_testlab_worker.py`, opt-in
  `tests/integration/test_testlab_bundle_real_session.py`; shared builders `tests/fakes/testlab.py`,
  session fixture `tests/fakes/testlab_bundle.py`.
- Handoff: `tasks/jarvis-category2-test-lab/` (Slices 01, 02, 03, 04, 05).

Status 2026-09-17: contracts (Slice 01), run persistence (Slice 02), the
DiagnosticBundle with its capture service and bundle store (Slice 03), the
catalog with its manifests, primitive vocabulary and promotion path (Slice 04),
and the run supervisor with its isolated worker process (Slice 05). Runs execute,
but only the `selftest.worker` test fixture has a runner: every seed profile is
still `unavailable`, and a run of one is persisted `errored` with
`runner_unavailable`. The supervisor schedules the store upkeep and owns the run
store root it is given; nothing composes it into the application yet (no default
root wiring, no CLI or HTTP entry). Profile runners (06, 08, 09), score
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
worst}`, distinct metrics). Binding formula for Slice 07: each component maps
the metric linearly from `worst` (0) to `best` (100), clamped to 0..100; the
score is the weight-weighted mean. The score is a UI synthesis, never a verdict.

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
executor is Slice 06.

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

`PrimitiveHandler` is the executor-facing seam: a profile runner (Slice 06 onwards)
registers one handler per primitive it supports; the executor advances its virtual
clock to `step.args["at_ms"]` and calls it. `missing_handlers(primitives, profile,
handlers)` names what a runner still has to cover. Slice 04 implements no executor.

## Replay fixtures

`jarvis/testlab/replay.py` is the production home of the `jarvis.voice_replay` v1
codec (schema, size bound, provenance, timeline) that `tests/replay/voice_replay.py`
introduced. That test module is now a thin compatibility layer: it re-exports the
codec unchanged — same names, same stable `fixture_*` error codes, same immutability
— and keeps only `ReplayClock` and `ReplayDriver`, the execution half, until Slice 06
productizes an executor. Every fixture in `tests/fixtures/voice_replay/` and the
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
turns the virtual reservations into registrations, Slices 08 and 09 the others; that
is a code change only, with no manifest edit and therefore no version bump.

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

A wording edit (title, any description) is not drift: stored runs stay conforming.

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

The catalog ships the four Slice 12 seeds, all at version 1, all with the `virtual`
profile only, all `unavailable` until Slice 06 registers their runners. Slices 08, 09
and 12 add other profiles through a version bump, which keeps v1 in the history.

| Diagnostic | Blocking assertions | Notes |
|---|---|---|
| `voice.self_echo` | `barge_in.false_confirmed_count = 0`, `output.completed = true` | Jarvis speaks while its own output returns as input; parameters `output.duration_ms`, `echo.candidate_count`. |
| `speech.payload_integrity` | `speech.payload_mismatch_count = 0`, `speech.replayed_payload_count = 0`, `speech.undelivered_count = 0` | Virtual measure only: scripted payload vs the payload the harness delivered. The producer signal `voice.state.spoken_diverged` compares raw strings and is **not** used (Issue `speech-payload-integrity-needs-normalized-measure.md`). |
| `speech.stale_supersession` | `speech.stale_delivered_count = 0`, `speech.latest_intent_delivered = true` | Carries the converted replay fixture `stale_ack_35_9s` as its scenario, provenance included. |
| `voice.queue_latency` | `speech.queue_free_to_started_ms ≤ 3000`, `speech.started_to_first_audio_ms ≤ 4000` | Thresholds match the `latency.above_threshold` bundle rule; `user_turn.end_to_first_audio_ms ≤ 8000` is non-blocking (brain time, Slice 07). Virtual time measures scheduler delays, never provider or device latency. |

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
| `runners.py` | `DiagnosticRunner` protocol, `RunContext`, `RunArtifacts`, `RunOutcome`, `RunCancelled`: the seam Slices 06/08/09 implement |
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
`metrics`, an optional `score`, `join_ids` and the artifact references it
committed. The supervisor derives every `AssertionResult` with
`evaluate_assertion` from the declaration, calls `complete_run`, then
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

`RunFailure.code` values this Slice produces (`jobs.FAILURE_CODES`):

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
| `runner_failed` | `errored` | The runner raised, or its measurements are invalid |
| `supervisor_stopped` | `cancelled` | The supervisor stopped while the run was queued or running |

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

Slice 05 registers nothing else: every seed profile is still `unavailable`, and a
run of one is persisted `errored` with `runner_unavailable` rather than refused
at submission, so the attempt stays in the record. Slice 06 registers the virtual
runners.

### Validation

```powershell
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/unit/test_testlab_supervisor.py tests/unit/test_testlab_supervisor_jobs.py tests/integration/test_testlab_worker.py
```

The integration file starts real processes: one per test, two in the tree-kill
test (the worker and its grandchild).

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

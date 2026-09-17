# Execution Log

Reserved for implementation agents and the Project Manager to record durable execution notes, decisions made from live repository evidence, validation outcomes, and handoff changes. No implementation progress is pre-populated here.

## 2026-09-17 — Slice 00 (agent 0)

- Handoff mirrored from Drive (51 files). Branch `task/jarvis-category2-test-lab` created from `origin/main@f7e33ad`.
- Blind audit and baseline done. `origin/main` doesn't import because of conflict markers in `realtime_audio.py`. With that resolved in a scratch worktree, the baseline has 9 known unit failures, all unrelated to this task.
- Declared `HUMAN_DECISION_REQUIRED`: D1 (fix `main`), D2 (Task Type waiver). See `slices/00-project-manager/READINESS.md`.
- Human decisions: D1 fix `main` → `b86f228` pushed, branch replayed onto it; D2 Task Type gate waived. Slice 00 → `READY`.

## 2026-09-17 — Slice 01 (implementer)

- Package `jarvis/testlab/` (pure, no I/O/clock/provider): `validation`, `identity`, `profiles`, `diagnostics`, `scenarios`, `runs`. Contract `docs/testlab.md`, linked from `docs/ARCHITECTURE.md` ("Category 2 Test Lab").
- Decisions from repo evidence: integer diagnostic version (every Jarvis schema version is an int); self-describing documents `schema` + `schema_version` (`jarvis.voice_replay` / benchmark suite idiom); fingerprints are bare 64-hex sha256 of canonical JSON (same encoding as `prompt_registry.fingerprint`); times reuse the Conversation Events UTC-ms wire form; `TestRun.join_ids` keys are Conversation Events `TRACE_JOIN_FIELDS`; errors carry a stable `code` like `ReplayFixtureError` / `BenchmarkSuiteError`.
- Ids `tlr-|tls-|tlb-YYYYMMDDTHHMMSSmmmZ-<16 hex>`: time and nonce are arguments (filesystem-safe, chronological for the Slice 02 per-run directory store).
- Profile names imply minimal requirements (virtual: nothing, cost 0; live: a provider; hardware:*: an audio device; only hardware:guided may and must require human_presence). Audio forbids providers. Slice 08/09 may need to revisit `audio`.
- Status machine queued → running → {passed, failed, errored, cancelled, timed_out}, plus queued → {cancelled, errored}. passed/failed only via `complete_run` from the blocking-assertion verdict; inconclusive → errored `assertions_inconclusive`. A DiagnosticSpec needs ≥ 1 blocking assertion.
- Tests are flat `tests/unit/test_testlab_*.py` (orchestrator instruction) instead of READINESS's `tests/unit/testlab/`; shared builders in `tests/fakes/testlab.py`.

## 2026-09-17 — Slice 01 rework (QA findings F1–F9, F11)

- F1: `check_run_against_spec` re-derives every recorded assertion result from `run.metrics` with `evaluate_assertion` (outcome and observed must match, bool never stands in for a number); forged passed runs are rejected.
- F2: name guard redesigned as a final-word rule over closed word sets (secret words anywhere; private content and code words only as final word or before a carrier word; `<qualifier>_code` is a classification code). Accept/reject tables in `docs/testlab.md` and tests.
- F3: value code scan narrowed to unambiguous forms (dunder call/attribute, `eval(` without space, calls on `os.`/`subprocess.`/…, exact imports of dangerous modules, `#!/`). Documented as a heuristic, not the security boundary.
- F4: `TestRun` v1 gains `diagnostic_fingerprint` (verified by `check_run_against_spec`) and `environment` (pattern-checked dotted names, ≤ 32 non-null scalars; open names because later runners add probes; privacy held by the name rules).
- F5–F9, F11: `1e400`/huge ints → `testlab_json_invalid`; thresholds must fit the unit and `eq`/`ne` only on count/chars/boolean; enum choices guarded; `transition_run(RUNNING, failure=...)` raises; `Scenario.from_dict` requires `primitives` (explicit `SHAPE_ONLY` sentinel); single `identity.id_timestamp`.
- 2026-09-17 Slice 01 rework 2: private names deny-by-default (content word anywhere unless final word is metadata; chain_of_thought/system_prompt compounds anywhere), secret `key` rule with closed UI/data qualifiers plus bearer/jwt/passphrase/auth_header/encrypted_content, enum choices value-checked only, `DiagnosticSpec.fingerprint()` semantic (title/descriptions excluded), docs overclaims fixed; conversation_events forbidden names regression-tested (input/bytes/arguments/args allowed on purpose).
- 2026-09-17 PM: Slice 01 approved after 2 QA rounds (F1 verdict re-derivation, redaction name rule made deny-by-default, value code scan narrowed to unambiguous code, TestRun gains diagnostic_fingerprint + environment). 539 narrow tests pass. Carried to later Slices: F10 (`dataclasses.replace` bypasses transitions) goes to the Slice 02 store; the ban on user-identifying `environment` facts goes to the Slice 02/05 capturers.

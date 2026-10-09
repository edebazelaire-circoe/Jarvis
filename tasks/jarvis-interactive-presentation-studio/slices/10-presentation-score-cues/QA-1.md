# QA-1 - Slice 10 (presentation score, tracks, cues, timing) - standard tier

Reviewed: `feat/ips-s10` @ `a7eea0f5` (diff `306ed560..a7eea0f5`, base = Slice 03 merge, Slice 05 NOT in it). Detached worktree `bipq`, HEAD checked before/after, `git status` clean at the end.
Skills applied: qa-verification, code-review, caveman. Product code untouched (mutants restored with `git checkout`).

## Recommendation: REWORK (small). 1 BLOCKING, 4 POLISH, 3 ISSUE. Everything else checked is solid.

## Runtime evidence (all foreground, one file at a time, venv python, `PYTHONPATH=bipq`, import path verified)

| Suite | Result |
| --- | --- |
| test_presentation_studio_score | 111 passed |
| test_presentation_studio_score_service | 30 passed |
| store 26, routes 20, docs 13, domain 142, scene 120, scene_service 26, service 25, crash 6 | all passed |
| test_documented_routes 3, test_v2_architecture 8, test_schema_migrations 8 | all passed (no SQLite schema change: file store, correct) |

BASELINE.md (10 red tests not ours): not re-run (outside the named suites); none of the named suites is red.

Own adversarial scripts (scratchpad `adv.py`, `adv2.py`, `ph.py`, `svc.py`), highlights:
- 200 items ok, 201 refused; nested/stacked/overlapping loops: expansion stops at 2000 in ~3 ms (no DoS); `max_repeats` 0 refused; cycles (to start, mid, tail, self) refused; duplicate item ids refused; empty score accepted; 5000-deep JSON list refused cleanly (no RecursionError).
- NaN, inf, 1e400, list, object, `None` as control value refused; `True`/`1`/`1.0` have three distinct canonical keys; `True` and `"5"` refused on a numeric control; 11 and -1 refused by curated bounds; real `lab.counter` manifest refuses a wrong enum string and a wrong type (service path).
- Spare key `tool` on an action refused ("unknown keys"); runtime key `position` gets `runtime_state_refused`; newer `schema_version` refused; `True` as version/revision refused; 200 x 1200 chars score refused with `limit_reached` and nothing written.
- Shuffled key order x20 gives identical `canonical()`. Sequence offsets: dup 0, reversed, first offset 1, negative, float, bool, duration == last offset, host duration mismatch, host `allow`, dup step id, user step, sequence-in-step, abort without recovery id, dup sequence, second host: all refused with a named reason.
- 5 concurrent `save_score` with the same `expected_revision`: exactly one wins (rev 2), four `stale_revision`.
- Zero-width space, RLO, lone surrogate, newline in any text field: refused (`isprintable` + utf-8 encode).

Mutation testing (5 mutants, all killed, all restored, status clean):
1. Add free-text `command: str` field to `ActionRef` -> killed (2 failures, classification test).
2. `check_score` returns `[]` (skip reference resolution) -> killed (5 score + 6 service failures).
3. Loop bound `MAX_EXPANDED_ITEMS` -> `10**9` -> killed (1).
4. Strictly increasing offsets -> non-strict -> killed (1).
5. Unknown-key refusal dropped in `ActionRef.from_dict` -> killed (4).

## Critical architecture rule (a cue never embeds tool instructions): HOLDS

- `ActionRef` is a closed 5-kind enum, fixed key shape per kind (`_SHAPE`), every id field is regex/slug-validated, `value` is a bounded scalar only for `control_set`. No kind or field can carry a tool name, command, URL or JSON. Validated `from_dict` uses `_exact_keys` at every level (score, item, action, step, sequence, cue, predicate, loop, recovery point).
- Cue predicate is a finite phrase set: letters/digits/space/apostrophe/hyphen only, so `{"tool":..}`, `/tool x`, URLs, `^(a+)+$`, `<script>`, `$(curl)` are all refused as phrases (tested). NFKC + casefold + whitespace folding verified: fullwidth, ligature `fi`, circled digits, roman numerals, NBSP, combining accents all fold; idempotent.
- Free-text fields (`text`, `note`, `label`s, control `value`) accept arbitrary printable text by design (injection strings are stored verbatim). This is acceptable for the stated rule because none is executable data at this layer, but see ISSUE I1 for Slices 13/14.
- Structural guard is real (mutant 1 killed) but narrow: see P3.

## Findings

### BLOCKING

**B1 - A variant can be locked into a permanently unusable `score_id` state through the public API (regression created by the new guard).**
`jarvis/core/presentation_studio_service.py` `_save_variant` (new guard, ~l.235) + `_create_score` + `_load_score`.
Scenario (reproduced, `svc.py`): variant has no score; `PUT .../variants/{id}` with `score_id: "psr_00000000dead"` (valid shape, no file) is accepted (Slice 02 behaviour, unchanged). Then: `GET score` -> 404 `unknown_score`; `POST score` -> 409 `already_exists` ("save it"); `PUT score` -> 404 `unknown_score`; `PUT variant` with `score_id: null` or another id -> 400 `invalid` ("keep it"). Every API path is closed; only hand-editing the JSON on disk recovers. Same dead end when a score file is later missing/deleted (a missing file is `unknown_score`, not recoverable). Before this Slice a client could simply send `null`; the new "link ownership" rule removed that way out without providing another.
Expected: either (a) refuse attaching a `score_id` through `save_variant` when `current.score_id is None` (only the score routes create the link), and/or (b) let `POST score` replace a link whose file is absent, and/or (c) allow `save_variant` to clear a link whose file is absent. (a)+(b) is the smallest. Add a regression test for the dangling attach.

### POLISH

**P1 - Cue collisions/ambiguity are not detectable by any pure helper, test or doc line.** `CuePredicate`/`Score._check_references` (score.py ~l.231, ~l.766). Verified: two cues with the same phrase, or the same phrase differently spelled ("PASSONS  AU Contexte"), are accepted and normalise to the same string. Refusing score-wide would be wrong (the same "suivant" can legitimately recur on different items), so the right fix is a pure `Score.phrase_index()` / `ambiguous_phrases(cue_ids)` (normalised phrase -> cue_ids, plus semantic labels) with a test, and one doc sentence telling Slice 13 that ambiguity is evaluated on the armed set. Right now Slice 13 must re-derive it.
**P2 - Lookalike characters survive normalisation and pass `isalnum`.** Cyrillic `а` in "plan" (`plаn`), modifier letter apostrophe U+02BC (`lʼhôtel` vs `l'hôtel`), Arabic-Indic digits `٣٣` vs `33` are all accepted and stay distinct from the Latin phrase. Effect: a visually identical dead cue or a silent non-collision. Suggest restricting phrase characters to Latin letters (plus accents), ASCII digits, space, `'`, `-` (French/English only today), and fold U+02BC with U+2019. Zero-width/soft-hyphen are already refused (tested).
**P3 - FREE_TEXT/ID classification test has blind spots.** `test_nothing_in_the_model_can_hold_free_text...` skips any field whose annotation does not contain the substring "str" (`typing.Any`, `object`, `dict`, `bytes`). `ActionRef.value: Any` is only covered because it was listed by hand. A future `payload: Any` or `args: dict` field would pass silently. Also the name blacklist test is only a name list. Suggest also failing on any annotation containing `Any`/`object`/`dict`/`Mapping` not on an explicit allow-list, and asserting ID fields actually carry a pattern (cheap mutation: swap a regex for `str`).
**P4 - Small doc/spec drift.** (a) `09-canonical-names.md` line 33 names `score_item_id`; code and `docs/presentation-studio.md` use `item_id` (and `CueDefinition` vs `Cue`); update 09 or the doc says so. (b) The doc says "loops may nest" but overlapping (non-nested) loops are accepted and expand deterministically (73 items for loops 5->2 and 8->4); either document or refuse. (c) `ScoreItem.scene_id` is never compared with the `scene_goto` target of its own actions: an item can belong to scene 3 and goto scene 9 (maybe intended, but unstated). (d) `assert control is not None` in `_bounds_problem` is a production assert guarded only by the call order.

### ISSUE (non-blocking, for later Slices)

**I1 - `note` and `text` will reach the speech/brain path (Slices 13/14).** Injection strings are stored verbatim (verified). Slice 14 must treat `note` as untrusted data in a presenter-speech turn with no tool authority (Slice 01c), and Slice 13 must only ever name a `cue_id`. Record this in those SLICE.md files.
**I2 - Removing a scene from a variant is not blocked or flagged when a score references it.** `get_score` reports `problems` (verified) and `save_score` then refuses until fixed, but `save_variant` and, after the merge, Slice 05 deletion edits do not warn. Slice 05/08 should surface "score references scene X" before deleting. Also: `save_score` does not bump the variant revision, so autosave/undo (Slice 08) and compare (Slice 19) must track the score revision separately.
**I3 - Orphan score files are never swept** (documented as harmless; failure-injection test exists). Acceptable; a one-line sweep in the startup sweeper can come with Slice 22.

## Checks that passed without finding

- Contract completeness vs SLICE.md: user speech/intention track (`note`), Jarvis speech and explicit silence (`kind=silence`, `Track.JARVIS_SPEECH` lists `{"silence": true}`), visual/motion action refs with track-vs-group check, cue definitions + `armable` (armable needs non-empty predicate), soft target timing, locked sequences, recovery metadata (`Recovery`, `RecoveryPoint`, sequence `recovery_id`), validation against scene/anchor/control ids and bounds, then against the pinned manifest. Acceptance ("full presentation as inspectable score without wall clock") met: 12-scene fixture, `playback_order()` and `estimated_duration_ms()` have no clock.
- Storage: new document kind `jarvis.presentation_studio.score`, `schema_version` 1, `UPGRADES[score] = {}`, strict unknown-key refusal, path-component id checks before disk access, atomic write, temp sweep extended to `scores/`. Score-first-then-variant order has an orphan test; stale revision and concurrency verified above. Reads (`_get_score`) take the same service lock as writes, so the Slice 02 B1 pattern (read racing a save) is not reintroduced for scores.
- `save_variant` change vs callers: Slice 05 (`bips` `presentation_studio_edit.py:141`) passes `variant.score_id` through unchanged, so it is unaffected by the "keep the same score_id" rule. Note the guard sits in `_save_variant` only; Slice 05's `_write_variant` path is not guarded. Harmless today, but when 05 and 10 merge, move the guard into `_write_variant` so it protects every writer. Slice 02/04 tests pass.
- Routes/client/docs parity: 3 routes, 3 typed client methods, 2 new error codes with status, doc tables and `local-data.md` updated; documented-routes and docs suites pass. Strict JSON body (NaN/duplicate keys refused by `loads_strict_json`).
- Error handling and diagnostics: refusals use typed codes; `score_loaded` and `saved part=score` events carry ids and counts, not speech.

## Answers to the implementer's open questions

1. Granular score edit ops: not now. Agree with PM; whole-document PUT with `expected_revision` is enough until Slices 11 (authoring), 15 (rehearsal) and 21 (agent ops) need item/cue ops. Keep `parse_content` as the one validation entry so granular ops can reuse it.
2. Empty `items` valid: yes (accepted and tested; useful for create-then-fill). Keep, but note `create_score` with an empty score plus "every cue must be used" means cues cannot be authored ahead of items; fine for whole-document PUT.
3. One score per variant: yes, matches 09 ("one Score per variant"). Fix B1 so the link cannot dangle.
4. Marker reveal/hide decided by Slice 12: agree. Slice 10 only validates that the anchor exists; runtime semantics (marker vs control-bound anchor) belong to playback. Write that sentence in the doc seam table.

## Not verified

BASELINE red tests not re-run; no live Core/browser run (no UI in this Slice); Slice 05 merge interaction only read, not executed; real-model/voice behaviour not applicable; route-level HTTP calls exercised through the existing route tests only (my service script bypassed aiohttp).

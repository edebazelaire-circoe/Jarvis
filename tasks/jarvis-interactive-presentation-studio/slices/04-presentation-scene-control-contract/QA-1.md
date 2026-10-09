# QA-1 - Slice 04 (standard) - Presentation scene and control contract

Reviewed `006ffa72..d8866ef9` (a6f445fc, d8866ef9) in detached `bipr` at d8866ef9 (`PYTHONPATH=C:/Projects/jarvis/bipr`, import path verified). HEAD checked before/after each mutant; `git status` clean at the end. No product code changed. Skills: qa-verification, code-review, caveman.

## Verdict recommendation (PM decides): REWORK (small, one fix)

Contract complete, architecture rules held, upgrade safe, mutants all killed. One BLOCKING: the "new or changed scene" test in `save_variant` uses dataclass `==`, so `true` over `1` and `1.0` over `1` count as "unchanged", skip PrefabService, and are persisted invalid. Fix is one line plus one test. Polish items can ride along.

## Runtime evidence (one file at a time, all green)
new: scene 120, scene_service 22. modified/neighbours: domain 104, routes 15, docs 9, store 21, crash 6, service 25, test_documented_routes 3, test_v2_architecture 8, test_schema_migrations 8, test_scene_service_prefab 18, test_prefab_domain 182, test_prefab_service 44, test_prefab_routes 25, test_prefab_library 25. No SQLite change (file store): migration rules N/A, schema test still green. BASELINE's 10 red tests not re-run (outside touched files).

## Mutation (5 mutants, riskiest first, each restored by `git checkout`, `git status` clean, HEAD d8866ef9)
| # | Mutant | Result |
| --- | --- | --- |
| M1 | allow widening of numeric bounds (`bounds_problem` range test off) | KILLED (scene + scene_service) |
| M2 | `_check_scenes` checks nothing (`changed = []`) | KILLED (12 scene_service failures) |
| M3 | v1->v2 upgrade fill off | KILLED (scene test only; `StudioScene.from_dict` also fills defaults, so the step is partly redundant, harmless) |
| M4 | unknown-key refusal dropped on controls | KILLED (bounds/escape-hatch test) |
| M5 | manifest/pin check dropped in `SceneCatalog.check` | KILLED (10 scene_service failures) |
Note: first attempts of M2/M5 did not apply (CRLF), those runs were discarded; results above are from the applied mutants. The BLOCKING below is NOT caught by any test (no mutant needed: reproduced by script).

## Findings

### BLOCKING
**B1 - value-type change (`true`/`1.0` over `1`) bypasses scene validation and is persisted.**
`jarvis/core/presentation_studio_service.py` `_check_scenes`: `changed = [scene for scene in scenes if scene not in stored]`. `StudioScene` is a frozen dataclass, `props`/`data` are dicts: `{"count": 1} == {"count": True} == {"count": 1.0}` in Python, so the scene is judged unchanged and `SceneCatalog.check` is skipped.
Scenario (script adv1, real `PrefabService`, `lab.counter` where `data.count` is `integer 0..1000000`): save count=1 (ok); save same scene with `"count": true` -> accepted, file now `"data": {"count": true}`; save with `1.0` -> accepted, file `{"count": 1.0}`. The same value on a new scene id is refused (`scene_incompatible: expected a finite integer, got True`). So the "save checks every changed scene" invariant (docs "Validation", item 2) has a hole reachable over HTTP (`true` vs `1` in a PUT body), which Slice 05 edit API will use. No data loss; an invalid instance reaches the stage host.
Fix: compare by stored form (`scene.to_dict()` serialized with `json.dumps`, or `canonical_json`, which keeps `true` != `1`), not `==`. Add a test: re-save a scene with `true`/`1.0` in an int prop -> `scene_incompatible`.

### POLISH
**P1 - locator hygiene: coverage gaps and an undocumented rule** (`domain/presentation_studio.py` `_check_locator_hygiene`, `resource_from_dict`). Tried 40 locators (script loc.py):
- Correct: `https://x/a%20b?q=100%`, `C:/Users/me/doc.pdf`, `https://x/a%E0%A4%A` accepted; `scene:`, `SCENE:`, `scene%3A`, `%73cene:`, `Scene%3a` refused as runtime handle; `%2e%2e`, `.%2e`, `%2E%2E`, `..%2f`, `#../`, `memory:..` refused.
- `drive://` and `memory:` are refused, but by the existing `ResourceReference` scheme allow-list (pre-existing), not by the new code.
- Double encoding is accepted (`scene%253Aabc`, `%252e%252e/etc`): only one decode level is checked. Acceptable only if every resolver decodes once; say so in the doc, and have Slices 11/12 never double-decode.
- Controls are checked on the raw text only: `x%00y` and `%0a` (decoded NUL/newline) pass.
- Lookalikes pass: zero-width prefix `\u200bscene:abc`, fullwidth colon `scene\uff1aabc`, Cyrillic `\u0455cene:abc`. No resolver treats these as `scene:` today (no NFKC), so low risk; refuse non-printable characters (`isprintable`) for free.
- Still accepted from the Slice 02 P5 carry-forward: `file:///etc/passwd`, `//host/share/x`. The commit message says P5 is addressed; it is partly. Decide at Slices 11/12 (resolver) and say it in the doc.
- False positive: a bare fragment `https://x/a#..` is refused; native Windows path `C:\Users\me\x.pdf` (backslash) is refused for kind `document` while `C:/Users/...` is accepted. Policy call, not a bug; document it.
- `docs/presentation-studio.md` line 58 still says only "allowed-scheme locators, no markup": the new refusal rules are in tests only. Add them.
**P2 - caller fault logged as a hard error.** `PREFAB_UNAVAILABLE` is added to `hard` in `_guard` (service ~325): an agent typo (`unknown_prefab`, `unknown_version`) is a 409 plus `core.presentation_studio.failed` at `error`. Only `tampered`/disk/catalog faults deserve `error`; unknown pin is a caller refusal (info, 400/404). Keeps the Error Logs viewer meaningful.
**P3 - route tests cover only 404 for the new scene errors.** `test_presentation_studio_routes.py` asserts `unknown_scene` 404 and 200; nothing asserts HTTP 400 `scene_incompatible` or 409 `prefab_unavailable` (status table is correct by inspection `HTTP_STATUS`, but untested).
**P4 - docs "unchanged scenes are not rechecked"** is true for identical scenes but, per B1, also for type-coerced equal ones; fix with B1, wording stays.
**P5 - discovery is per scene.** A GUI building a panel for N scenes makes N calls. `get_variant` returns declared controls but not resolved ones. Fine for Slice 07 if the inspector shows one scene at a time; note for Slice 07/18.

### ISSUE (out of scope, for the PM to file)
- Prefab `PROPERTY_NAME` (`jarvis/domain/prefab.py:86`) accepts `__proto__` and `constructor`; the control path regex inherits it (`props.__proto__` is refused only because no manifest declares it). Slice 05/06 JS code that patches by key must use own-property-safe assignment.
- `_check_scenes` awaits `PrefabService` while holding the service lock: a slow catalog stalls every studio read/write. Fine today (local files); revisit if the catalog ever goes remote.

## Checks with no finding
- Contract completeness vs SLICE.md: logical identity/order/section (`scene_id`, position, `title`, `section`); exact pin (`PrefabRef`); typed curated controls with label, type (from manifest), widget (derived), range/enum (`effective_bounds`), default, `meaning`, group; score anchors (`ScoreAnchor`, closed set, `control_id` must be declared); preview metadata; discovery for agents and GUI via `describe_scene` + GET route + typed client; stable ids (authored slugs, unique, order kept; v1/v2 fixtures round-trip byte-equal; same answer across calls). Verified by script on both fixtures plus a fresh service per run.
- Architecture: no prefab definition field in the schema (`manifest/template/style/behavior/html/css/js/inputs/events` refused); `PrefabService` only called from `SceneCatalog` (grep + `PrefabCatalog` port); curated bounds only narrow: widen max/min, string length +1, enum outside, float on integer, bool/NaN/inf bounds, duplicate or empty enum values, bounds on a colour: all refused with typed errors; no CSS dump (paths = manifest-declared object properties only, depth capped, no index/selector: `data.history.0`, `data.history[0]`, `props..x`, `props.`, `props`, `scene.title` refused); 33 controls refused; default over 2000 chars, NaN default, wrong-type default, `True` default for integer, default outside curated bounds: all refused; control-level `css`/`handle` keys refused (runtime key gets its own code). Domain purity: `presentation_studio_scene.py` imports only `jarvis.domain.*`; `test_v2_architecture` green. 16 KiB accounting goes through `ScenePayload`/`ScenePrefabRef` (`payload_bytes`, `budget`).
- Variant 1->2 upgrade: v1 fixtures and a v1 file on disk read through `UPGRADES`, read leaves the file byte-identical (sha256), next save rewrites as v2 with all other fields preserved; `variant.parent.v1`, `variant.v1` round-trip; Presentation stays 1. A v1-only JARVIS (code of 006ffa72 extracted with `git archive`, run in isolation): v2 fixture -> `unsupported_schema_version`; real service `get` and `save` on a v2 file both refuse and the file hash is unchanged. v3 file: refused, untouched, 409. v1 scene whose prefab needs required data: reads fine, `describe` answers with `problems: ["...data.count: is required"]`; a rename-only save keeps it; adding a new bare scene of that prefab is refused `scene_incompatible`.
- Extraction: `ast`-level byte comparison of source segments old vs `presentation_studio_checks.py`: `clip, _fail, _check_id, _check_title, _check_int, _exact_keys, PresentationStudioError, RUNTIME_KEYS, MAX_ERROR_CHARS, _C` IDENTICAL. Differences are only expected: `MAX_TITLE` now literal 80 (test ties it to prefab `MAX_TITLE_CHARS`), `SCENE_ID` literal same pattern, error enum and `HTTP_STATUS` gained the 3 new codes, `is_scene_id` new. `SceneRef = StudioScene` keeps the `(scene_id, prefab)` constructor; its `to_dict` now emits the full scene (v2), and Slice 02 tests were updated for that, which is the documented bump. Re-exports with `noqa` keep old import paths.
- Slice 02 B1 race: `get_variant` is `_locked`; `describe_scene` loads presentation and variant under the same lock (`_describe_scene`). Script: 4 reader tasks (get_variant + describe_scene in a loop) vs 60 saves: 0 errors. 10 concurrent same-revision saves in one service: exactly 1 wins, 9 `stale_revision`.
- Errors: 404 `unknown_scene` (also for a malformed id, never a path), `unknown_variant`; 400 `scene_incompatible`; 409 `prefab_unavailable`; 500 only for storage. Pin removed from the library after save: `describe` -> 409 `prefab_unavailable` with the prefab service's reason, logged; changed-scene save refused likewise; rename-only save still works (by design). Nothing swallowed: `_trace` swallow is the existing intentional one.
- Lone surrogate in `data` string: 400 `presentation_studio_invalid` (not 500). Variant of 64 rich scenes: typed 409 `limit_reached` (doc says it). Doc text for versioning/validation/routes matches behaviour except the points in B1/P1.

## Implementer's 4 open questions
The prompt did not contain them and none exist in the Slice folder, LOG.md, commit messages or bips (searched). I could not answer item by item; please resend. My view on the decisions most likely meant: (1) variant bumped to v2 with an upgrade step rather than optional fields at v1: agree, it makes a v1-only JARVIS refuse instead of silently dropping controls on its next save (proved above). (2) `SceneRef` as alias of `StudioScene` plus checks extraction: agree, diff is byte-identical, no behavior change for Slice 02 callers. (3) Check only new/changed scenes: agree in principle (rename must not depend on the catalog) but compare by stored form, see B1. (4) One stage window / scenes are not global-scene objects, stable `control_id` slugs authored per scene, anchors as closed action set: agree, matches R2/R5; keep `suggest_controls` as a non-persisted helper.

## Not verified
Live Core process and browser (no UI in this Slice); real HTTP assertions for 400/409 scene statuses (inferred from the status table); two event loops/threads on one service (my harness hung because it shared one `PrefabService` across loops, so not a product result; Core runs one loop and single writer is documented); POSIX behaviour (Windows only); BASELINE's 10 red tests.

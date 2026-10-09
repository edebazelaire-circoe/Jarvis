# QA-1 - Slice 09 (art direction profile) - standard tier, no UI

Commit reviewed: `4e6ae1e9` (diff `ec6da364..4e6ae1e9`), detached worktree `C:/Projects/jarvis/bipq`. HEAD and `git status` verified clean before and after every step. No product code modified. Recommendation: **approve with POLISH** (no BLOCKING). The PM decides.

## Verdict summary
- Security-critical rule holds. No CSS/JS/URL injection path found through any field. `to_theme()` emits exactly the 5 host keys; `to_theme_variables()` emits exactly `ALLOWED_THEME_VARIABLES` (15 names, all declared in `jarvis/prefabs/runtime/shell.css`), every value matches a closed grammar. Free text never reaches the theme (verified by script and by mutant).
- WCAG math correct (independent recompute, 20 000 random pairs, max diff 0.0). One real gap: gradient contrast is checked at stops only (P1).
- Deterministic across processes and `PYTHONHASHSEED` (0, 1, 12345, random: identical sha256 over fallback x5, diverge n=6, derive).
- 5/5 mutants killed. 18 test files run, all green.

## Evidence (what actually ran)
Tests, one pytest process per file, all pass:
art_direction 50, art_direction_authoring 26, art_direction_service 29, store 32, routes 26, docs 20, domain 142, service 25, crash 6, score 129, edit 85, scene 120, score_service 34, score_edit 6, edit_service 59, edit_routes 18, scene_service 26, edit_docs 6, roles 29, documented_routes 3, v2_architecture 8, schema_migrations 8. The 10 baseline-red tests live in other files and were not hit. `BASELINE.md` is not present in bipq (not read).

Mutants (restored by `git checkout`, status clean after each):
| # | mutant | result |
| --- | --- | --- |
| 1 | `if failing:` -> `if False:` (skip contrast check) | killed (4 failed) |
| 2 | `_HEX` loosened to `[^\n]{1,40}` | killed (4 failed) |
| 3 | `--jv-title` = `self.name` (theme leaks free text) | killed (`test_free_text_..._never_reaches_the_theme`) |
| 4 | link guard in `_persist_variant` disabled | killed (3 failed) |
| 5 | `serious` ignored in `require_art_direction` (both branches) | killed (2 failed) |
(Mutant 5 ran art_direction and art_direction_service in one pytest process, a small deviation from "one file at a time". Two first attempts of mutants 1 and 5 did not apply because of a bad match string, no change was made, then redone.)

Adversarial scripts (own, in scratchpad, not committed):
- Colour fields (8 paths x 24 payloads: `#fff;}</style><script>`, `red`, `rgb()`, `url()`, `expression()`, `@import`, `var(--x)`, `\75rl(`, fullwidth `ＦＦＦ`, NUL, trailing `\n`, 3 and 8 digit hex, 100 000 chars, None, int, list): all refused except `accent_alt: None` which is legal.
- Font `preferred`: 20 payloads (`Arial"; } body{x:y`, quotes, `;`, braces, backslash, NUL, newline, fullwidth, 41 chars, `é`, zero-width): all refused. Accepted only `A b`, `inherit`, `url` - emitted quoted (`"inherit", "Segoe UI", ...`), so they are family names, not CSS keywords or functions. Inert.
- Free text (name, motif, note): newline, NUL, lone surrogate, 100 000 chars, bidi override U+202E, zero-width, U+2028, NBSP, BOM, tag chars, tab: refused. `a}</style><script>alert(1)</script>` and `url(javascript:x)` are accepted as printable text by design, stored verbatim, and proven absent from `to_theme()` / `to_theme_variables()` output.
- Signals (`parse_design_signals`): hostile colour, font, `calc(1px)`, `8px;x`, `1e3px`, ` 8px`, fullwidth `８px`, `9999px` (clamped to 48), non-int radius, newline mention, bool/0 weight, unknown key: all refused or clamped. Reference locators (16 forms: `javascript:`, `data:`, `%2575rl(`, `url%28x%29`, fullwidth `ＵＲＬ(`, `@import`, backtick, `;`, `{}`, `"`, `%22`, `%2522`, `//host/share`, `file://`, backslash, NUL, 5000 chars): all refused.
- `derive_from_signals` fuzz, 3 000 random colour sets with random roles, weights, radii, fonts: 0 exceptions, every output re-parses through `parse_profile`. Hostile text in mentions and source titles never copied into the profile (only validated colours, a plain family name, sources as references).
- Contrast boundary: grey on white, `#767676` = 4.542 accepted, `#777777` = 4.478 refused (matches the known WCAG boundary).
- Diverge: n=1,3,6 from the fallback: min distance to base 0.614 / 0.522 / 0.363, min pairwise 0.522 / 0.344. Worst case over all 21 archetype x accent bases at n=6: 0.334, so above `MIN_DIVERGENCE` 0.2. Candidates are visibly different (7 archetypes: light/dark backgrounds, 6 distinct accents).

## Findings

### BLOCKING
None.

### POLISH
**P1 - Gradient text contrast is only checked at the stops, not along the gradient** (`presentation_studio_art_direction.py:138-141`, `Palette.contrast_report`). Scenario: text `#000000`, gradient `#0a8465` -> `#e71610` (both stops pass 4.5:1 against black). Linear interpolation passes through `#784d3a`, ratio 2.92:1. `Palette(...)` is accepted (reproduced). Luminance along an sRGB line is convex, so its minimum can sit between the stops, which is exactly the case for dark text. Contradicts the module docstring ("une palette illisible n'existe pas") and the docs "Contrast, in numbers" claim "on every stop". Today no code renders the gradient (`gradient_css` has no consumer), so no user-visible harm yet; fix before Slice 11/12 uses gradients: sample each segment (e.g. 16 steps, or the analytic minimum) and add the pair `"... mid"`, or restrict `text_token` to light text on dark stops. `test_a_gradient_must_carry_its_text_on_every_stop` only tests stops.

**P2 - `--jv-wash` and `--jv-surface` backgrounds are not in the contrast set** (`to_theme_variables`, `:478`). Buttons use `--jv-text` on `--jv-wash` (text at 9% over the background). With the boundary-legal text `#767676` on white, text on wash is 4.09:1 (< 4.5). Shipped archetypes are fine (>= 12.7:1). Add "text on wash" (and "accent/accent_alt on effective surface" at 3:1; `playful_bright` accent on surface is 4.69, `warm_human` 4.84, fine but unchecked) to `contrast_report`, or document the 4.5 boundary as "on background and surface only".

**P3 - `check_reference` regex has false positives on legitimate locators** (`:411`, `_INJECTION_SHAPE`). `data\s*:` is unanchored, so `https://x.test/metadata:v2` or `note:data: Q3` is refused; `;`, `{`, `}` in a URL query (`?a=1;b=2`, templated URLs), `env(`/`var(`/`attr(` as a suffix (`.../myenv(1)`) are refused. Safe direction (over-refuse) and defence in depth, but a real design-system URL could be refused with an unhelpful message. Suggest anchoring on a word boundary (`(?<![A-Za-z0-9])data\s*:`) and naming the offending character in the message. Low priority.

**P4 - Derived provenance is slightly inconsistent when only mentions are usable** (`derive_from_signals`, `:597-609`). With only `mentions` (no colour/font/radius), `usable` is True, every section is `generated`, yet the profile `origin` is `inferred`, with confidence 0.35. Either set `origin=GENERATED` when `inferred == 0`, or treat mentions-only as fallback. Origin is the field Slices 11/19 will read to say "derived from your brand sheet", so honesty matters.

**P5 - Authoring policy says candidates "2 to 6", the route accepts 1..6** (`docs/presentation-studio.md` policy item 6 vs `_candidates` `_check_int("count", ..., 1, MAX_DIVERGE)`). One word to align.

**P6 - Module size/shape.** `presentation_studio_art_direction.py` is 1 073 lines (about 250 of them closed vocabularies and CSS constants), plus 609 in authoring; the split in two modules is documented (doc 09 s12) and reasonable, but the vocabularies (`FontStack` ... `ReducedMotion`, `FONT_STACK_CSS`, `EASING_CSS`) could move to a `..._art_direction_vocab.py` before Slice 19 adds more. Also `authoring` imports the private `_FAMILY`, `_color`, `_enum`, `_line`, `_tuple` from the sibling module: promote them (or `__all__`) rather than reach into underscore names. No functional impact.

### ISSUE (not defects of this Slice; for PM follow-up)
**I1 - `require_art_direction` has no caller yet.** The Slice acceptance ("every produced presentation variant has a coherent DA") is enforced only when Slice 11 (before delivering a serious/generated variant) and Slice 12 (before playing) call `PresentationStudioService.require_art_direction`. Nothing in Slice 09 blocks creating or saving a variant without a DA (by design: `serious` is a caller flag, the variant has no "kind"). Make this an explicit acceptance line in Slices 11 and 12 and a trace scenario ("serious variant, no DA -> fallback is created, announced").

**I2 - 10 of the 15 `--jv-*` variables have no delivery path.** The shim applies only the 5 `THEME_VARS` (`shim.js:49,220-223`). `--jv-font`, `--jv-radius`, `--jv-gap`, `--jv-ground`, `--jv-veil`, `--jv-title`, `--jv-link`, `--jv-body`, `--jv-edge`, `--jv-wash` are produced by `to_theme_variables()` but nothing can set them in a frame today. The docs say so honestly ("contract for a future shell extension", `presentation-studio.md:489-491`, `prefabs.md:1415`). Consequence: typography, radius, density and background of a DA are not visible in scenes until a shell/protocol change. Slice 07 or 12 needs a decision (extend `THEME_VARS` with the same validated grammar, or accept that only accent/text/muted/surface/scale apply). Security note for that future change: the grammar proven here is the allowlist to reuse; do not widen it.

**I3 - Provenance is self-declared.** A `POST` body can claim `origin: provided` or `fallback: false` for a guessed profile; Core cannot verify. Acceptable (policy item 1 says "never mark provided what was guessed") but the Slice 11 prompt must carry that rule and Slice 19 `mix` must not trust it as proof.

**I4 - Reference `title` accepts newline and `url(...)` text** (pre-existing `resource_from_dict`, Slice 02; `title='a\nb'`, `'url(javascript:x)'` accepted, `'</style><script>'` refused). Not a Slice 09 defect (titles are classed free text and never reach CSS), but a Slice 11 prompt that interpolates titles must treat them as untrusted multi-line text. Candidate hardening: apply `_line` to titles.

**I5 - Error text echoes attacker-chosen key names** (pre-existing `_exact_keys`; an unknown key of 500 chars + `<script>` is echoed up to about 300 chars in the message). Same family as the Slice 05 QA P2 (`_guard` logs the refusal message). Slice 09 adds no new value echo: colour errors echo only validated tokens, enum errors list members only, and `test_a_hostile_profile_is_stored_only_as_inert_data_and_logged_without_content` passes. Still open from Slice 05.

**I6 - Saving a DA does not bump the variant `revision`/`updated_at`** (documented: "Saving a DA does not touch the variant file"). A reader that caches by variant revision (Slice 12 playback, Slice 07 relay) will not see a DA change; it must compare `art_direction.revision`. Say so in the Slice 07 relay and Slice 12 notes.

**I7 - Crash path is covered at service level only.** `test_a_crash_between_the_two_writes_leaves_a_harmless_orphan_and_a_retry_works` and `test_a_failed_save_keeps_the_previous_document` exist and pass; `tests/unit/test_presentation_studio_crash.py` (process-level) was not extended. Acceptable; flagged for completeness.

## Axis by axis
- **Contract**: palette (+gradients), typography, spacing, shapes, imagery, dataviz (charts), motion (reduced-motion mandatory and never "keep motion"), references, provenance (`provided|inferred|generated`, per-section override, confidence 0..1, notes, `fallback` only with `generated`). Strict document: `schema` + `schema_version`, unknown key refused at every level, newer version refused, canonical JSON, frozen fixture `tests/fixtures/presentation_studio/art_direction.v1.json`. Complete against SLICE.md steps 1-5.
- **Resource linkage**: reuses `ResourceReference`, `resource_from_dict` hygiene and `ALLOWED_LOCATOR_SCHEMES`; adds an injection-shape check. No filesystem, network or DB in the pure modules (tested by `test_the_module_is_pure...` and `test_derivation_does_no_io_at_all`). Derivation consumes signals reported by agent tools, as SLICE.md step 2 asks.
- **`require_art_direction` matrix** (resolved / None / dangling x serious True/False) matches code and docs table; non-bool `serious` refused; document naming another variant or presentation is `corrupt_document`; fallback resolves and reports `is_fallback`.
- **Storage**: new kind registered in `CURRENT_VERSIONS` and `UPGRADES`; atomic write via the same `_write_file`/`replace_with_retry`, ids validated before any path use, `*.tmp` swept in `art_directions/`, oversize file is `corrupt_document`. Write order DA then variant, orphan inert, retry works. Stale revision writes nothing, 5 concurrent saves give one winner, concurrent creates give one DA. Dangling link repaired by a create (with `relinked_from` and a warning trace); an unusable file is never replaced.
- **`_persist_variant` guard**: `art_direction_id` changes only via the create/fallback path. Regression analysis: the only earlier-slice caller affected is `PUT .../variants/{id}` which used to accept any well-formed `psd_` id; it now refuses a change with `presentation_studio_invalid`. This tightens Slice 02 and is recorded in doc 09 s12 and `presentation-studio.md:530`; one Slice 02 service test was edited accordingly (it no longer passes `art_direction_id="psd_00000000000a"`). The Slice 05 edit path passes `variant.art_direction_id` unchanged (`presentation_studio_edit.py:148`), so edits are unaffected (edit, edit_service, edit_routes suites green). Slice 10 `create_score` keeps `art_direction_id` via `replace`. No UI or other caller found in `jarvis/` that sends the field.
- **Determinism and coherence**: fallback picks an archetype by closed lexicon (FR+EN, accent-folded) else a sha256 digest of canonical JSON; no `hash()`, no set iteration into output, ties broken by index. Every archetype x accent passes the contrast check (test and my run). `diverge` distance claim is real (numbers above), candidates are drawn from 7 archetypes so n=6 gives six different looks.
- **Repair vs refuse**: `derive_from_signals` repairs (4 attempts, last valid by construction) and says so in notes; direct construction of a bad palette refuses with a named pair and its measured ratio.
- **Error handling / observability**: typed codes `unknown_art_direction` (404), `art_direction_required` (409); service wraps in `_guard`; traces `art_direction_loaded|relinked|candidates|resolved` and `saved part=art_direction` carry ids, origin, counts, never profile content. Visible and logged.
- **Docs**: `presentation-studio.md` (contract, theme mapping, provenance, routes, authoring policy), `prefabs.md` row, `ARCHITECTURE/OPERATIONS/local-data` mentions, doc 09 s12 amendments, routes table in the routes module docstring; `test_presentation_studio_docs.py` extended and green; `test_documented_routes` green. Accurate except P5 and the honest-but-important I2.

## Answers to the implementer's 4 open questions
1. **`psd_` id kept (PM: accepted).** Agree. `pda_` appears nowhere in the handoff docs (only the brief); doc 09 s2 and s2 table (line 35, 113) already say `psd_`, the Slice 02 variant validates `psd_`, and doc 09 s12 records the decision. No inconsistency left.
2. **Candidates computed, not stored (PM: accepted).** Agree. `diverge` is deterministic (process-stable, hash-seed-stable), so the same request returns the same set; no orphan files, no delete path. Caveat for Slice 11: because candidates are not stored, the agent must carry the chosen candidate's full content to `POST`/`PUT`; asking the same `count` again gives the same list, but a different `seed_context` or a changed base changes it.
3. **Trace scenarios and untrusted-data line to Slice 11/21 SLICE.md (PM will add).** Agree. Suggested scenarios: inspect-then-derive without asking; fallback created and announced when the project has nothing; one question only when two brands conflict; serious variant with no DA -> `require_art_direction` refusal handled by creating the fallback (I1); hostile project text in mentions/titles not obeyed (I3, I4). The untrusted-data line should cover `name`, `notes`, `motifs`, reference `titles` and mentions, and say titles may be multi-line (I4).
4. **Slice 07 read relay for art direction (PM: will add).** Agree. Relay GET `.../art-direction` and `.../candidates` (read-only computation); keep create/save/fallback behind the author path. Slice 07 must also decide I2 (10 variables with no delivery) and I6 (compare `art_direction.revision`, not the variant revision).

## Not verified
- No runtime/browser check (no UI in this Slice, and the shim does not consume the extra variables).
- No agent trace analysis (no agent behaviour yet; deferred to Slices 11/21 by the PM).
- Full repo test suite not run (only the files listed). `BASELINE.md` not available in bipq, so the 10 pre-existing red tests were not cross-checked by name.
- Mid-gradient failure (P1) shown with direct `Palette(...)` construction, not through the HTTP route (the route calls the same constructor).
- Windows only; no check of the `replace_with_retry` behaviour under real lock contention beyond the existing monkeypatched tests.

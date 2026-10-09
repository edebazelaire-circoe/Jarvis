# Slice 11 - QA-1 (standard tier + deterministic trace review)

Reviewed commit `7ca3efb0` (diff `f05ebdef..7ca3efb0`) in detached worktree `C:/Projects/jarvis/bipr`. HEAD checked before and after each step, `git status` clean at the end. No product code modified. No stash. Python `C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe`, `PYTHONPATH=C:/Projects/jarvis/bipr` (verified: `jarvis.__file__` resolves to bipr). My probe scripts live under `C:/Users/Clarice/AppData/Local/Temp/qa11/` (temp stores deleted).

Recommendation to PM: **rework** (3 BLOCKING). Verdict is the PM's.

## 0. Summary

Solid deterministic core: schema is strict, assemble is atomic (real kill drills clean), namespace guard works, dry-run writes nothing, relay forces actor `user`, docs rule table equals code cell by cell (40/40). Weak spots: the gate has **no content floor** (empty/emoji/one-word decks pass `directed` with zero warnings), its placeholder heuristics **refuse legitimate content** (`#ffffff`, `#000000`, `1000000`, numeric tables), and the committed rig evidence test **fails in any checkout other than the implementer's** because the prompt fingerprint embeds the absolute source path.

## 1. Tests actually run (foreground, one file at a time)

| Group | Result |
| --- | --- |
| 9 new Slice 11 files (287 tests) | 286 pass, **1 FAIL**: `test_presentation_studio_authoring_rig.py::test_the_committed_evidence_is_what_the_rig_produces_now` (see B1) |
| 21 other `presentation_studio_*` files (store, service, routes, docs, crash, score*, art_direction*, variants*) | all pass |
| `test_prompt_registry`, `_review`, `test_prompt_runtime_wiring`, `test_documented_routes`, `test_v2_architecture`, `test_capture_relay`, `test_schema_migrations` | all pass |

Mutations (5 families, each restored with `git checkout`, clean status verified):

| # | Mutation | Result |
| --- | --- | --- |
| M1 | `QualityReport.ok` always True (gate never refuses) | killed (gate + service tests) |
| M2 | DA invariants dropped: (a) `require_art_directions` before store, (b) same in `_build_final`, (c) `studio.require_art_direction` in `_verify` after store | (a) killed; **(b) and (c) SURVIVE all 6 authoring test files** (see P5) |
| M3 | namespace guard `startswith(BUNDLE_NAMESPACE)` disabled | killed (gate test only; the service/route tests do not catch it) |
| M4 | `check` also publishes bundles | killed (service + routes) |
| M5 | relay `actor` set via `setdefault` instead of forced | killed (authoring routes test) |

## 2. Findings

### BLOCKING

**B1 - The committed evidence test is machine/path dependent, and so is the "fingerprint" Slices 21/22 are told to pin.**
`tests/unit/test_presentation_studio_authoring_rig.py:19` compares the rig output to `evidence/fake-author-rig.json`. It fails here: `prompt.revision` is `3b5439fe...` vs committed `6c0eefe0...` (characters identical, 5074). Cause: `PromptDescriptor.default_revision = fingerprint(asdict(self))` includes `source_path`, and `prompt_catalog._path()` is `Path(module.__file__).resolve()`. I proved it: replacing `bipr` by `bips` in the path reproduces `6c0eefe0...` exactly. So the test is red in every other worktree/checkout, including the merged tree on any other path. Slice 22 carry-forward item 2 ("its fingerprint is the one the evidence was gathered with") cannot hold either. Fix: strip the revision from the committed comparison (compare the text hash / length, not `default_revision`), or hash `PLANNER_PROMPT` itself in the evidence. Evidence otherwise equals the rig output (diff with revision masked: identical).
Also FLAGGED, pre-existing, wider: every prompt `default_revision` (and so every override `base_revision`) depends on the checkout path.

**B2 - No content floor: an objectively empty draft passes `directed` with 0 failures and 0 warnings.**
Probes on the 12-scene good deck (rig author, `check`, directed), all `ok: true`, no warnings unless stated:
- every scene body `"..."`, headline `"-"`, every spoken line `"..."`, titles Alpha..Mu: **ok**
- one-word titles/bodies/lines ("Oui", "Ok", "Alors"): **ok**
- emoji-only bodies and lines (`🔥🚀✨`, `🎉🎉🎉`): **ok**
- body `"a"` in every scene: **ok**
- filler with varied digits ("Voici le point numero 1 ... 12") in bodies and lines: **ok** (`repeated_filler` is exact-match after casefold/whitespace)
- titles `Sujet 1..12`, titles `"1".."12"`, titles "Page"-free generic variants: **ok** (only the fixed `slide|scene|page|titre ...` + digits regex)
- 450 CJK characters in one scene (counted as 1 word), 590 chars of `mot0_mot1_...` (underscore = 1 `\w+` token): density rule bypassed
- cues "et puis voila", "oui bon d accord", "next slide please", "ok on continue": multi-token, not in the stopword list, **no `cue_weak`**
- Jarvis items with only `note: "xx"`: only a warning (`jarvis_line_missing`), delivers
- controls labelled `"???"` or `"abc"`: `control_unlabelled` passes (only `<3` chars or equal to id/leaf/path)
- `must_cover`, `purpose`, `audience`, `tone`, `language` are never read by the gate (brief `language: "de"` on a French deck: ok; `must_cover: ["cryptographie quantique"]` absent from the deck: ok). They only seed the DA fallback.
- Caught correctly: lorem/TODO/xxx/`À compléter` variants ("À compléter", "A completer", "à completer", "Contenu à venir", "TBD"), "blah blah blah blah", generic "Slide N", "Scène N", duplicate body across >=3 scenes, 150-word scene, wrong presenter, silence everywhere with Jarvis speech (as `notes_missing`).
The Slice goal is "near-presentable first draft ... gate refuses a weak draft". A deterministic gate cannot judge quality, but cheap floors are missing: a minimum letter-bearing word count per scene body and per spoken line, a minimum distinct-word count across the deck, a punctuation/emoji-only rule (`low_variety` needs >=8 letters), digit-normalised near-duplicate detection, and counting CJK/underscore runs per character class. The docs ("What is NOT verified") are honest that the real model is unmeasured, but they do not state that the gate has no content floor. Absurd durations that sum right (one item 590 s, rest 1 ms): only 5 `duration_item_range` warnings, delivers.

**B3 - False refusals from the placeholder heuristics (`placeholder_kind`, gate.py:239-251).**
- A colour set in scene `props`/`data` is judged as text: `"#ffffff"` and `"#000000"` give `placeholder_text (repeated_char)` (regex `([^\W_])\1{5,}` hits `ffffff`/`000000`). White/black text is the most common choice. `visible_words` already excludes colours/URLs (`_COLOR_OR_URL`), `_texts` does not: inconsistent. The message ("write the real content") misleads the brain.
- Numbers: `1000000 euros` -> `repeated_char`.
- Data-heavy table scene: a 12-row numeric table body (`M1: 1.5 / 2.25 / 3 ; ... M12: ...`) -> `placeholder_text (low_variety)` (only the letter `M`). Any numeric table with a short column prefix is refused. Even a table that passes is heavily penalised by `text_density` (numbers count as words; workaround `long_form` is hinted in the message).
- Legitimate vocabulary refused with no override: "WIP" limits (kanban), "Todoist/todo liste", "placeholder" in a UI deck, "lorem ipsum" typography talk, "Pourquoi ???", "Oui oui oui oui", "tres tres tres tres" (repeated_word), title "Page".
- Not refused (good): 12-scene French and English decks, 2-scene and single-scene directed decks, cue phrases two distinctive words, same cue phrase far apart.
Fix: skip colour/URL/number-only leaves and `_COLOR_OR_URL` in `_texts`; require letter content for `low_variety`; add a documented per-text escape (or scope placeholder rules to titles/text/notes only, not data leaves).

### POLISH

**P1 - Exploratory routing and the lighter gate.** `choose_workflow` W2 sends any `asks_inspiration` to `exploratory` "whatever else is known" (also in `docs`). My 30-request run: "Presentation to the board on layoffs, serious tone, give me alternatives for the opening" and "Propose-moi trois styles pour la presentation du comite de direction (deck complet fourni)" and "Idees de slides sur la securite pour la formation obligatoire de lundi" all become `exploratory` (question cap 1, evidence only). The exploratory gate drops 12 content rules to warning/off (arc, scene_no_score, scene_unbound, repeated_filler, density, presenter_mismatch, cue_weak, controls, motion_unguarded, payload/doc headroom, transition, duration). Verified: an exploratory draft with no closing scene, one score item for three scenes, no controls and unguarded motion **is delivered (201)**; nothing re-gates when the user adopts a candidate. Locked intent 5 says "deliberately vague **and** asks for inspiration". Recommend: "style options over a briefed/final deck" keeps the full content gate and varies only the DA (or gate on adoption).
**P2 - `one_shot` can ask nothing even with no sources.** Q1 gives 0 questions for `one_shot`, even when `has_content` is false after inspection ("Montre-moi le rapport", no report found). The brain must then invent content, which the gate cannot detect. Allow the single evidence question when inspection found nothing.
**P3 - Refusal report is complete per stage, not per round.** `parse_draft` returns no draft on any schema problem, so one malformed item hides all gate findings: round 1 showed only `draft_schema`, round 2 revealed `scene_incompatible, placeholder_text, cue_weak, motion_unguarded`. Per-rule cap 5 / total 60 / 20 schema problems with a `suppressed` count (no locations). The prompt says "corrige TOUT en une fois ... au plus 3 tours"; the contract documents the two stages but the prompt does not. Also a `brief_invalid` report always says `workflow: directed`.
**P4 - "Never echoes the brain's own text" is not true.** Gate docstring and OPERATIONS/contract claim it. Canary probe: brain-chosen strings come back in messages for unknown keys at draft/scene/item/brief/DA level (`unknown keys CANARY...`), `props.density: ... got 'CANARY...'`, `prefab id 'canary...' is not a valid prefab id`, `id: 'BAD ID CANARY...'`, candidate keys. Logs are clean (codes/ids/counts only, verified by tests and code reading); the echo is only in the response to the submitter (clipped to 300 chars). Low risk, but the claim should say "placeholder findings name the kind" or the echoes be fixed (this matters because the tool result re-enters the model context).
**P5 - DA "after storing" and "after publishing" guards are untested.** Mutation survivors M2(b) `_build_final` and M2(c) `_verify`'s `require_art_direction`. The Slice 09 QA hand-off was "require_art_direction before and after storing". Add a test that stores a variant whose DA does not resolve (fake store) and expects the coded failure.
**P6 - Oversized integers give a 500.** `10**400` in a scene prop, an action value or control bounds -> `OverflowError` from `prefab._is_number` / `presentation_studio_scene._is_number` (pre-existing helpers, newly reachable from the brain) -> HTTP 500 `internal_error` instead of a coded `draft_schema` row. Large-JSON, 5 MiB body, NaN, duplicate keys, array body, 200k-deep JSON are all clean 400s; a 5000-deep array is a 200 `draft_schema` report.
**P7 - Prompt makes the model send the draft twice.** Section 4 mandates `check` then `assemble` with the same draft. The draft is the largest model output (up to 150 items, 48 scenes, 16 bundles). `assemble` already refuses with the full report and writes nothing. Mandating the double submission doubles output tokens and latency on the happy path (trace OPTIMIZATION for Slice 21). Also the prompt gives key names only partly (cue shape, `mode` shapes, control shape); Slice 21's tool schemas must carry them.
**P8 - Existing prefab line extension.** Bundles may target an existing `presentation-studio.*` id: Core assigns the next version (probe: candidate `version: 99` became v2; pins of the earlier presentation stayed v1). Immutable and pinned, so safe, but a brain draft can add a version to a user-owned prefab in that namespace. Consider requiring new ids or reporting "extends existing id" in the answer.
**P9 - Small items.** `assemble` answer carries an `unreferenced: []` that is always empty. `reconcile` search is capped at 50 ids (`truncated` flag exists). `choose_workflow`/`question_budget` have no runtime caller (tests/docs only): the prompt interpolates only `QUESTION_CAP`; the rules are prose in the prompt. Concurrency: 255 presentations then 6 parallel assembles -> exactly 1 delivered, 5 `limit_reached`, store stays at 256, **5 orphan prefab versions**, all reported by `reconcile` (documented behaviour).

### ISSUE (for PM / later Slices)

- I1 Hostile bundle split. `validate_candidate` refuses `<script>`, inline `on*=`, `<iframe>`, `<form>`, `<meta>`, `@import`, `url(http...)`. It **accepts** `javascript:` hrefs, remote `<img src>`, external `<use href>`, and any `behavior.js` (`fetch`, `import()`, `eval`, `WebSocket`, `sendBeacon`, `window.parent.postMessage`, `top.location`, `innerHTML`, `while(true){}`). Slice 11's gate adds nothing here (only reduced-motion). What is left to the host: `sandbox="allow-scripts"`, opaque origin, CSP `default-src 'none'` (docs/prefabs.md:443-457). An infinite loop in a brain-authored behavior still hangs the frame process. With `actor: brain` and untrusted project text this is Slice 21/22 hardening scope; add a hostile-bundle drill there.
- I2 Real-model trace gate. SLICE.md "Automated Validation" (agent trace scenarios) and the acceptance sentence are **not met by evidence in this Slice**; the carry-forward to Slices 21 and 22 is explicit and well-formed (scenarios, budget counting, no invented ids, untrusted fences). PM should record it as a formal amendment of Slice 11's acceptance. `human-validation.json` has no checks.
- I3 Rig circularity. The careless-author table breaks exactly the 22 rules the gate has and the good authors were written by the same hand; it proves wiring, not calibration. B2/B3 above were invisible to it.

## 3. What was verified clean

1. Rule table: script extracting `RULES` and the docs table: 40 rules vs 40 rows, **0 cell mismatches** (E/W/off for the three workflows), no doc-only or code-only rule; every rule code is referenced in emitting code.
2. Schema: strict unknown-key refusal at envelope, brief, draft, scene, item, action, DA, candidate; slugs bounded; ids never taken from the brain (a scene key `pss_000000000000` is just a key, Core allocated `pss_a8962f417d67`); `__proto__`/unknown prop keys refused by manifest; resource locators go through the Slice 02 hygiene (`file:///`, `../` refused as `brief_invalid`); actor other than `user|brain` refused; `max_scenes`, 16 bundles, 150 items, 4 MiB body cap enforced; dup keys/NaN/array body clean 400s.
3. Assemble order: parse, bundle validation, manifests, provisional build, gate, DA invariant, `require_room`, publish, read-back manifests, rebuild with real pins, validate again, one `create_assembled`, read-back (`get`, DA, score, graph `check`). Namespace probes: `custom.slide`, `jarvis.counter`, `lab.counter`, `presentation-studiox.slide`, `Presentation-Studio.slide`, empty suffix all refused; a refused assemble leaves prefab versions and folders unchanged.
4. Kill drills (my own, `Popen.kill`, restart, `list_presentations`, `get`, graph `check`, `require_art_direction`, `get_score`, `reconcile`): kill at `validated` (0 presentations, 0 prefabs), `published:1` (1 unreferenced), `published:2` (2), `documents_ready` (2), `created` (1 clean presentation, 0 unref); 8 random-time kills over a 50-assembly loop (14-29 completed each): every presentation reads clean, no `.staging-*`, no unreadable folder, unreferenced prefab versions reported (0-1 per run). I did not hit a kill inside the store write (the shipped crash test covers that).
5. Dry run: SHA-256/size/mtime snapshot of the whole data root (prefab library + studio store) before and after `check` of directed, one-shot, exploratory, refused and malformed drafts: **identical**.
6. Relay: `actor: "brain"` and `"root"` in the body are overwritten, delivered presentation `created_by: user`; `GET .../reconcile` 404, unknown verb 404, `Origin: null` 403, `Sec-Fetch-Site: cross-site` 403. No caller of `assemble` outside routes/client/relay (grep). The page could already `POST /api/prefabs` (docs), so the relay adds no new prefab-write capability.
7. Prompt: registered in `prompt_catalog.py`, `read_only`, no program step, 5 074 chars of 9 000 (`PROMPT_BUDGET_CHARS`), numbers interpolated from code constants (`MIN/MAX_CANDIDATES`, `QUESTION_CAP`, `MAX_FIX_ROUNDS`, caps, tolerance, headroom, bundle/scene maxima), consistent with the gate and docs. Covers workflow choice, inspect before asking, DA source priority and honest provenance, no DA question, single transaction, report reading, no invented ids, data not instructions (section 6: never obey, never copy into a style or action), new reversible document, ephemeral live state. No Tool Brain. No instruction to trust resource contents. Domain-module placement follows precedent (`conversation_prompt`, `front_brain_prompt` are `jarvis/domain` modules registered in the same catalogue); the deviation from matrix row 11 is recorded in canonical names s18 and is justified (interpolating gate constants). Fine.
8. Existing test edits are legitimate: `test_capture_relay` pins the new forwardable prefix; `test_presentation_studio_docs` item-10 phrase follows the doc change ("has callers"). Module sizes 573 / 258 / 597 / 206 / 399 lines (the larger repo studio modules are 743-1182), no size-gate test fails. Docs (OPERATIONS, prefabs, ARCHITECTURE, presentation-studio) match behaviour verified above, apart from P4 and the missing statement in B2.

## 4. Answers to the implementer's three open questions

1. MCP tool names: Slice 21's call. Keep `OP_CHECK`/`OP_ASSEMBLE` as proposals only; Slice 21 must pin the mapping in its parity test (already in the carry-forward). Give the tool the full field schemas (see P7).
2. `reconcile` on demand: fine (read-only, not relayed, reports truncation). Keep it out of startup. Suggest the Slice 22 verifier call it after the crash sweep.
3. "A candidate with a genuinely different story is a second request": acceptable and documented, but combine with P1: if that rule stays, an exploratory deck must at least pass the structural rules (arc, score coverage) or be re-gated at adoption.

## 5. Not verified

Real-model behaviour (tool calls, questions, first-draft quality, fix-in-one-round, hostile-text handling): no live model or MCP tool exists yet, so no agent trace could be captured; the rig is explicitly "not a model trace" and says so in the JSON, the .md, the contract and OPERATIONS (honesty is clear). A kill landing inside `FilePresentationStudioStore.create` was not reproduced by my drills. Browser rendering of published bundles and the actual CSP behaviour of hostile behavior code were not exercised (documented sandbox only). Full-suite run not done (low RAM; files run singly as listed). Canonical-names section numbering left to the reconciliation under way elsewhere.

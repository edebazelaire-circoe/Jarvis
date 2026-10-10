# Slice 16 - QA-1 (critical tier: qa-verification + code-review + runtime-validation + mutations)

Reviewed: `git diff 9e4894f2..ebf1080d` (3 S16 commits) in the detached worktree `C:/Projects/jarvis/bipr`, HEAD `ebf1080d` checked before, during (every mutant) and after; `git status` clean at the end. No product code touched. Scratch scripts live in the session scratchpad; all runtime work used isolated temp data roots (never the live Jarvis). Python: `C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe`, `PYTHONPATH=C:/Projects/jarvis/bipr` (`import jarvis` verified to resolve to bipr).

## Verdict recommendation: APPROVE with polish. No BLOCKING finding.

The acceptance sentence ("hold several durable creative directions and return to any retained branch safely") holds. The destructive-action safety and the multi-file crash safety survived every attack I could build. Findings are one documented-but-unguarded multi-instance hazard (ISSUE), and polish on documentation claims, the archive cap UX and two test gaps.

## Evidence summary

### Test runs (all foreground, one file at a time)
- 7 new variants files: domain 70, store 7, recovery 11, docs 10, routes 16, service 36, crash 10 (crash run 3 times: 10/10 each time). All green.
- Neighbours, all green: 32 files `presentation_studio_*` (domain 142, edit 85, history* 89, score* 169, scene* 146, store 26, service 25, routes 20, recovery 23, ...), `prefab_retention` 41, `prefab_retention_crash` 6, `conversation_events` 142, `control_center_timeline_js` 72, `documented_routes` 3, `v2_architecture` 8, `schema_migrations` 8, `capture_relay` 35, `prefab_relay` 22. None of the 10 BASELINE reds is in this set.

### Own adversarial scripts (isolated roots) - 78 checks, 1 real failure (the multi-instance one, F1)
- Numbers: archive highest then create -> 4 (no reuse); restore keeps its number; hand-edited manifest (counter lowered, duplicate number, active missing) -> `corrupt_document` on read AND on create; restored manifest reads again.
- Tokens: forged none/empty/garbage/int/list -> `confirmation_required`; wrong hex, extended expiry, other process secret, token of another root, token after a branch was added under the planned parent (TOCTOU), after a rename of a title in the set, replayed after archive+restore, bound to the chosen new active, valid at 599 s and stale at 601 s, 300 random single/multi-char mutations of a real token, unicode digits, 100 KB token: all refused with the right code, never a raw exception, never executed.
- Active protection: plan has no token when blocked; archive of the active is `active_variant_protected`; last live variant protected.
- Titles/rationales: NUL, newline, tab, RLO, bidi isolate, ZWJ, leading space, empty, 5000 chars -> `invalid`; RTL Hebrew, emoji, 80 accented chars accepted and round-trip. Odd bodies (unknown key, actor `system`, `activate:"yes"`, `expected_revision` 0/stale, `../` id, `[]`, `None`, string) all coded `presentation_studio_*`, no `RAW:` exception.
- Scale: 64 live (60-deep chain + 3 siblings) fine, 65th refused `limit_reached`; archive of the mid-tree node (31 variants) 527 ms, plan 62 ms; restore of the deepest leaf brings the 30 archived ancestors in order (469 ms); graph valid after each.
- Concurrency in one service: 12 concurrent creates -> numbers 2..13 unique; switch+archive of the same node -> one wins, the other typed refusal, active stays live; double switch -> `[True, False]`.
- Archive cap: 128 reached after 128 create+archive cycles, the 129th archive is `limit_reached`, nothing moved (live files intact), create and restore still work after.
- Fidelity: branch canonical-JSON-equal to its parent apart from `variant_id/number/title/parent/created/updated/revision/score_id`; score copy equal apart from ids, `variant_id` re-pointed to the branch; item/cue ids kept (documented).
- Undo: edit on a branch, rename it, undo -> applied (label restored, title kept). Undo on a non-active variant with no ring -> `history_unavailable`. `drop_variant` observed called on archive.
- Leak scan: secret title and rationale pushed through failing operations (bad token, bad title, bad rationale, stale revision, restore of a live variant) then grepped in the error messages, the diagnostics sink and the recorded events (ASCII secret; first attempt used a non-ASCII secret that `json.dumps` escaped, so I redid it): 0 hits.
- `pin_index()`: keys `(presentation_id, variant_id)`, values `frozenset[(prefab_id, int)]`, includes live AND archived variants (an archived variant's pins equal its pins before archive). Compared with `feat/ips-s06` `PresentationStudioService.pin_index` and `StudioPinRegistry.rebuild/register_variant(pid, vid, Iterable[Pin])`: same shape, compatible.
- Manifest v1 -> v2 with REAL old code (`git archive 9e4894f2` into a scratch dir): old code made a v1 presentation; new code read it with identical sha256 (`get`, `start()`, `graph()` all leave the file untouched); first `create_branch` rewrote it as v2; the old code then answered `unsupported_schema_version` and left the v2 file byte-identical.

### Kill drills (real `Popen.kill` through the S16 `checkpoint`, isolated root; 1 -> {a -> {c}, b}, score on #1), restart with a fresh Core, then `graph`, `start()`, `check`, next create
| Op | Kill after | After restart |
| --- | --- | --- |
| create | allocated | hole in numbers (counter 5, 4 nodes), clean, next number 6, 0 file lost |
| create | linked:score | orphan score reported by `check` (`orphan_linked.score=1`), no node, next number 6 |
| create | variant_written | orphan variant file reported (`flagged:1`), orphan score reported, never adopted, never deleted, next number 6 |
| create | committed | done, 5 nodes |
| archive | moved:1 / moved:2 | read before restart = `corrupt_document` (visible, documented); `start()` moved 1 / 2 files back, archive did not happen, clean, 0 lost |
| archive | manifest_written | done, clean |
| restore | moved:1 / moved:2 | `start()` moved them back to `archive/`, 0 lost |
| restore | manifest_written | done, clean |
In every drill: sha256 of every non-manifest `*.json` before the operation still present after recovery (LOST=0) and numbers unique.

### Destruction grep (`git diff` for `unlink|rmtree|os.remove|shutil|rename|replace(`)
Product code: only `os.rename` in `FilePresentationStudioStore.move_variant` (store:`move_variant`, refuses an existing target, refuses links, one rename, directory flush). No `unlink/rmtree/remove/shutil` in product code. All `unlink/shutil` hits are in tests (simulated corruption). Judged clean. See P4 for the POSIX replace caveat.

### Mutation testing (10 mutants, riskiest first, each restored with `git checkout -- .`, `status` clean after each)
| # | Mutant | Result |
| --- | --- | --- |
| M1 | counter not persisted before use (`branch_allocate` write removed) | KILLED (service numbers test) |
| M2 | token not bound to the set (`rows: []`) | KILLED (domain) |
| M3 | token expiry ignored | KILLED (domain) |
| M4 | active protection off (`elif False`) | KILLED (domain) |
| M5 | restore without ancestors | KILLED (domain) |
| M6 | `drop_variant` not called | KILLED (service) |
| M7 | relay does not force actor (`setdefault`) | KILLED (routes) |
| M8 | reconcile blind to orphans | KILLED (domain) |
| M9 | archive = copy + delete instead of rename | SURVIVED all 7 files (see P3) |
| M10 | `pin_index` skips archived | KILLED (service) |
9 killed, 1 survived. Not mutated (cost/ROI): "titles leaking into event" (the event allowlist `ATTRIBUTE_KEYS` plus `content="forbidden"` plus the leak scan above cover it).

## Contract check against SLICE.md / docs

- Branch from current/selected: yes (default active; archived source refused). Immutable short monotonic number never reused: yes, including delete(archive)-highest, kill after allocate, restore, restart, hand-edited counter (refused). Title/rename: yes, number never changes. Parentage/rationale/`sources` provenance: yes (`sources == [parent]`, validated older). Switch: manifest only, idempotent. Archive with descendants under destructive policy: yes. Autosave isolated per variant: yes (service test asserts only the active file changes; rings per variant kept; `drop_variant` on archive).
- R3 (file store, atomic writes, nothing under the repo, kill-proof): yes. R8/R9/R10: one event type, registered in Python and JS (tests pass), same service for GUI (actor forced `user` by the relay) and later MCP (`brain`). The MCP `confirm` path is Slice 21's, recorded as a seam.
- 02 QA-1 P3 (cycles accepted by the loader): fixed here (`validate_graph` on every load and before/after every write). 08 QA-1 I3 (`drop_variant` never called): done. 01a QA-1 I2 (fork from archived versions): pins of archived variants kept via `pin_index`, but see P2.

## Findings

No BLOCKING.

### ISSUE

**F1 (ISSUE, documented limitation with a silent failure mode): two writers on one data root lose branches and reuse numbers.** `jarvis/core/presentation_studio_variants.py` (`_create_branch`) and every other write rely on the in-process `asyncio.Lock`; the store has no cross-process lock. Repro (`adv.py::t_threads`): 3 threads, each its own service instance on the same root, 5 creates each -> every caller got a success, numbers `2,2,2,3,3,3,...,6,6,6` (each number handed to three different variants), the manifest ends with 6 nodes; 10 variant files are orphans on disk and the 10 callers were told "created". `docs/presentation-studio.md` line ~551 records "two Core processes on one root are unsupported (lost updates)", so this is by design since Slice 02, and a second Core on one root is unlikely (port, per-repo data roots). What is new in S16 is the consequence: the "never reused" promise breaks and the caller is told success. Cheap hardening if wanted (not required for approval): an exclusive lock file taken by `start()` (or `PresentationStudioService`) so a second instance refuses to start instead of corrupting; or at least a doc sentence in the Variant contract "Display numbers" paragraph that the guarantee is per Core process.

### POLISH

**P1 (docs claim false for non-ASCII): "128 archived nodes fit under 256 KiB with a 600-character rationale on each".** `docs/presentation-studio.md` "Decisions and limits"; true only for ASCII (600 bytes). Measured: 600-emoji rationales -> create+archive cycles stop at the 93rd with `limit_reached: document would exceed 262144 bytes` (manifest 261 705 bytes, 92 archived); 600 CJK chars would stop near 120. The refusal is pre-checked (`dump_document` before any move), so no data is at risk, but the message does not give the remedy (the 128-cap message does), and a rationale cannot be edited or shortened, so at that point the only way to free space is `restore` (restore shrinks an entry) or a hand edit. Fix options: count UTF-8 bytes in `check_rationale` (cap 600 chars AND ~2 KB), or reword the doc and the `limit_reached` text ("restore a branch or clear `archive/` by hand").

**P2 (merge seam, already recorded, make it a test): Slice 06 registry.** `PresentationStudioVariants.pin_index()` is wired to nothing yet (grep: no caller). Until Slice 06's `StudioPinRegistry.rebuild` also reads it, an archived variant's pins disappear from the registry after a Core restart (`studio.pin_index()` = live only) and its prefab versions can age out of the last-16 window, after which `restore` yields a variant whose pinned version is `unknown_version`. The doc lists it under "Slice 06 merge". PM: put the explicit merge acceptance "archive a variant, restart, retire old versions, restore -> pin still resolves" in the Slice 06 merge checklist. Also `variant_pins()` is duplicated in S16 (`core/presentation_studio_variants.py:684`, `getattr(scene, "last_valid_pin", None)` anticipating S06) while S06 has its own `variant_pins(scenes)`; at merge keep one.

**P3 (test gap, mutant M9 survived): nothing pins "one rename, never copy+delete".** The docs and the CLAUDE.md rule rest on `os.rename`; replacing it by `copyfile + os.remove` passes all 7 files because the store test only checks the final bytes. Add one store test that fails when the move is not a single rename (e.g. assert the inode/`os.stat().st_ino` is unchanged on a filesystem that supports it, or monkeypatch `os.remove`/`shutil.copyfile` to raise).

**P4 (POSIX only): `move_variant` check-then-rename.** `os.path.lexists(target)` then `os.rename`: on POSIX `os.rename` silently replaces an existing target if one appears between the two calls (Windows raises). Single writer under the Studio lock makes it theoretical here; if the project ever runs on POSIX, use `os.link` + unlink-of-source semantics or an `O_EXCL` guard. No action on this Windows-only box.

**P5 (UX): the plan does not foresee the archive cap.** `plan_archive` returns a token even when `with_archived` will refuse with `limit_reached` (128 archived); the human confirms and then gets the refusal (nothing moved, safe). Surface it in the plan (`blocked: presentation_studio_limit_reached`) so Slice 18 can say it before the confirmation.

**P6 (test gap, small): the reconcile `start()` report counters** (`flagged`) are only asserted indirectly; and no test kills during `switch` ("switched" checkpoint exists, drill not in the crash file; trivially atomic, I did not drill it either).

### OBSERVATION / Flagged (no action required)
- O1: the manifest is overwritten v1 -> v2 on the first graph operation with no copy of the v1 text (the migration is lossless and v1-only code refuses v2 untouched, so rollback means hand-editing). CLAUDE.md's `.v<N>.bak` rule is written for the SQLite databases; Slice 04's variant v1->v2 has the same behaviour. Consider a one-time `presentation.json.v1.bak` at first upgrade if the PM wants the rule applied to file stores.
- O2: cost is O(live variants) per operation (`create` loads every live variant to validate parents, then `_verify_locked` loads them again, all under the Studio lock): create 124 ms at 1 live (the claim says 94 ms; first call includes warm-up), 251 ms at 63 live (claim 245 ms): claim holds roughly; a 64-variant graph read is ~60 ms under the lock, so a graph poll briefly delays an autosave edit. Fine for the stated bounds.
- O3: `_announce` runs after the lock is released, so event order between two concurrent operations can differ from commit order (the event carries `revision`, so consumers can sort).
- O4: a read between an interrupted archive and the restart report answers `corrupt_document` ("indexed variant is missing") - documented, visible, resolved by `start()` or the next mutating operation (`_ensure_reconciled_locked`).
- O5: the 128-archive cap behaves as documented (checked before any file moves).

## Answers to the implementer's 5 questions (PM leaning confirmed)
1. One event type `variant_changed` with `op`: agree. It is the canonical name, registered in Python and JS, content forbidden, no title/rationale anywhere (verified by leak scan).
2. Delete = archive only, no hard delete: agree. CLAUDE.md compatible, restore is exact, hand-clearing documented in OPERATIONS.md (copy first). The only wart is the cap UX (P5) and the size claim (P1).
3. Whole-presentation deletion: not needed for this task. `drop_presentation` is the hook, documented; leave it to a later decision.
4. Slice 09 brings its own `ArtDirectionLink` at merge: agree; fail-closed behaviour proven (a variant that cites `art_direction_id` is refused `linked_document_unsupported`, not shared). Add to the Slice 09 merge checklist: register the link, add its store area to `list_documents` and the orphan check.
5. Archive clearing stays manual and documented: agree.

## Not verified
- Power loss / OS crash (only process kill); `FlushFileBuffers` effect cannot be proven here (same limit as Slice 08).
- Browser/runtime through the real Control Center page and a live Core process: the lifecycle is exercised over real aiohttp routes and the relay in `variants_routes` (green), but I did not drive a live Core + browser; there is no UI in this Slice (Slice 18).
- Two real OS processes on one root (threads with separate service instances reproduce the same race and are what F1 reports).
- Slice 06/09 integration (not present on this base); pin_index compared with the S06 branch by reading code only.
- Timeline JS rendering in a browser (parity tests pass; no visual check).

## Residual risks
- F1 and P2 are the two that can bite after merge; both are recorded seams rather than defects in the delivered code.
- Manifest growth with long non-ASCII rationales (P1).

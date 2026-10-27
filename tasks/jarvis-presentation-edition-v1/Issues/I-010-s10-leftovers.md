# I-010 — Slice 10 leftovers (implementation 2026-10-27)

Origin: Slice 10 implementation (`docs/release.md`, LOG entry « 2026-10-27 — Slice 10 (agent d'implémentation) »).
Not blocking for the Slice as implemented; each one is either outside its scope, a decision for agent 0 / the
Human, or a gate that cannot be run from this workstation. Owners in brackets.

1. **The CI workflow has never run on GitHub** [agent 0 / Human, gate A12]. `.github/workflows/ci.yml` passed
   `actionlint` 1.7.7 and every script it calls ran on Windows 11, but no implementation agent may push. Unknowns of
   a first run: `actions/setup-python` offering exactly `3.14.6` on `windows-latest`, `pip install -e .[dev]` on
   3.14 from a clean runner, the duration of the browser shards, Chrome of the runner for the browser suite, the
   Defender scan time of the installed smoke (~4-7 min per install here). Actions are pinned by tag (`@v4`, `@v5`),
   not by commit SHA.
2. **Two pipeline decisions to confirm** [agent 0]: the Ubuntu matrix (3.11-3.13, never executed) is replaced by
   Windows jobs; the former `-W error::ResourceWarning` run is not kept (never measured on Windows). Both are written
   in `docs/release.md` › *Pipeline*.
3. **Support bundle without a button** [UI pass / Slice 11]: the command `python -B -m jarvis support-bundle`
   exists and is tested; the readiness window offers no « Créer un paquet de support » action (frontend change).
4. **Renderer recovery in the installed product** [Slice 11, HV-RECOVERY-01]: the package smoke does not install
   Remotion (network `npm ci`), so a renderer crash in the INSTALLED product is covered only by the unit fault matrix
   (`test_remotion_release_faults.py`, render runner tests) and by the Slice 06/07 real renders.
5. **Voice in the installed product** [Slice 11, HV-AUDIO-01]: every trial runs with `JARVIS_LAUNCH_VOICE=0`.
6. **Deferred uninstall and a reused PID** (I-009 mn1) [post-V1 or Slice 11]: the removal script watches PID +
   image name only; a reinstall made while it waits on a reused PID could be erased. Fix: a token in the operation
   state, checked by the script before each delete. I-009 point 4 (screen readers of the bootstrap) and mn2-mn6 are
   unchanged.
7. **Not treated, outside this Slice's code** [owners as in their Issue]: I-004 point 5 (silent model switch by the
   CLI not surfaced), I-005 point 1 (`self_development` setting accepted 200 in `presentation`), I-008 point 3 and
   7 (editing jargon, Variants notice « Core ne répond plus… » staying after Core is back, frozen copy refused at
   render, native floor met by a dead control) — frontend and authoring work, best done with the Slice 11 wording
   and acceptance pass.
8. **Cross-machine reproducibility** of `package_sha256` [CI first run]: still proven on one machine only.
9. **Observed during the full sweep** (not caused by the task): `test_memory_context.py::test_recall_over_2000_notes…`
   exceeds its wall-clock latency budget on a loaded machine (passes alone 2/2): listed as `intermittent` in
   `tests/known_failures.json`; so is `test_presentation_integration.py::test_une_source_evincee_par_son_propre…`
   (failed once in a shard, cause not diagnosed, passes alone 3/3 and with its file 3/3; review by 2026-11-30).
   An architecture regression of Slice 03 (core importing the export destination adapter) was found by the sweep and
   fixed (`jarvis/ports/document_export.py`). `test_product_setup.py::test_the_deferred_removal_waits…` failed once under load:
   fixed in the test (wait counted from the file hold), not listed.
10. **A WAL after a hard stop**: killing the launcher leaves `jarvis.sqlite3-wal` / `-shm` next to the base (normal
    SQLite recovery at the next start, seen in the package smoke). The rollback procedure of `docs/release.md` moves
    them aside WITH their base; a support or recovery tool must never delete them.
11. **One unreadable Presentation folder degrades the whole Studio** [Studio owner, post-V1 or Slice 11]: the first
    package smoke seeded a fake `presentations/<id>/presentation.json`; Core then logged
    `presentation_studio_corrupt_document` (« 1 presentation folder(s) are unreadable »), `pins_degraded` (« rien ne
    sera archivé ») and failed the `all_variants` operation for every Presentation. The seed now writes a real
    Presentation through the Studio service and the smoke fails on any `corrupt` error; the product behaviour itself
    (one damaged folder blocking operations on the others, e.g. after a disk fault) is unchanged and worth a
    recovery path (« mettre de côté » the unreadable folder, keep the others working).
    **Added by the QA rework (independent real trial, 2026-10-27)**: with a truncated `presentation.json`, the
    readiness window still says « Dossier de JARVIS : Prêt » — the readiness check does not look at the Studio's
    own documents, so the user is told everything is ready while the Studio is degraded. Same owner; the readiness
    line should name the unreadable folder count (no title).

## QA rework of Slice 10 (2026-10-27)

Fixed by the rework (LOG « 2026-10-27 — Slice 10, reprise QA ») : B1, M1, M2, m1, m2, m3, m5, m7 (with R2), m9, m10,
R1, R2, R3, the quadratic masking (`_JWT`), the exact rollback names, the skipped-test count. The following are
**recorded, not fixed** (decision of the PM, or minor findings of `slices/10-…/qa/code-review.md` not in the rework
list). Owners in brackets.

12. **File names in the free text of messages** [support / post-V1]: the support bundle keeps the `message` of
    `errors.jsonl` (now bounded to 500 characters after masking) and each log line; a file name written there
    (`%USERPROFILE%\Documents\Bilan secret.pptx`, `…\CONTEXT_GLOBAL\préférences élève.md`, seen in the real
    trial) stays readable after the personal roots are masked. Structured `data` is now filtered by allowlist (m3);
    free text is not. Fix: a path rule that keeps the folder kind and masks the last segment, or no file names in
    error messages at the source.
13. **Misleading installer labels** [installer / Slice 11 wording pass]: after a first install killed during its copy,
    the next run says « Réparation de JARVIS… » / `mode: repair` (the killed run had already copied the program);
    the real trial also saw `mode: install` on a run that then failed and rolled back. The labels describe the folder
    state, not what the user did. Reword (« Reprise de l'installation… ») from `resumed`/state, not `folder_kind`.
14. **A killed bootstrap makes its Python fail at its next progress line** [installer, post-V1]: seen again in the R3
    real trial of the rework. The bootstrap is killed during the copy; its child `product_setup` keeps running
    without a standard output, fails at its next echo with `OSError: [Errno 22] Invalid argument` (phase
    `verify_target`), reports `rollback` but leaves the copied `Jarvis` and its `Jarvis.setup-state.json`, and writes
    no `result.json`. Nothing is lost (the home is untouched) and the next install recognises the folder and
    finishes (`ok`, mode `repair`), and now removes the bootstrap's work folder (R3). Fix: `Progress` must never
    fail on a closed stdout (catch `OSError` on the echo), so a lone child either finishes or rolls back fully.
15. **m4 — execution primitives checked as text** [`verify_release`, post-V1]: `from subprocess import run`,
    `shell = True`, `os.system (`, `os.popen(`, `Popen`, `asyncio.create_subprocess_*` pass. Not a weakening
    (same needles as before). Fix: an AST check.
16. **m6 — actions pinned by tag, no provenance attestation** [agent 0 / Human, with A12]: `@v4`/`@v5` in the job
    that builds the installer; no `attest-build-provenance`, no signature. Already in `docs/release.md` › Out of scope.
17. **m8 — Python matrix** [agent 0]: only 3.14.6 is tested while `pyproject.toml` says `requires-python = ">=3.11"`;
    the dropped `-W error::ResourceWarning` run has no follow-up. Decide: raise `requires-python`, or keep a light
    3.11 job; open a follow-up for `ResourceWarning` (the gate runs show `Unclosed client session` warnings).
18. **Review observations** [CI / support, post-V1]: `cancel-in-progress: true` on `github.ref` also cancels a
    release build in progress on `main` at each push; `_cap` cuts a file in bytes (possibly inside a UTF-8 character
    or a JSON line) and a `.tmp` may remain if `write_bytes` fails midway; the leading `\\?\` of a long path is
    reduced to one backslash by the masking (no privacy effect).
19. **Gate reports of a sweep made across two commits** [process]: `release_info.py` now refuses a gate report of
    another revision (m7). A local sweep interrupted by a commit must be rerun at the final revision before its
    reports can be joined (seen in the rework: the parts made at `8968850c` were refused for the `63697cfa`
    package; 13 reports of `63697cfa` were joined).

## Second rework of Slice 10 (2026-10-27, counter-review `slices/10-…/qa/rework-review.md`)

Fixed (LOG « 2026-10-27 — Slice 10, seconde reprise ») : X1 (canonical `.env` parser in the support bundle), X2
(installer test waiting for the self-erasing script), x3 (unreadable owner = alive), x4 (ordinary settings with a
sensitive-looking name stay readable, trivial values never secrets), x6 (sealed local keys and MCP vault credentials
given to the redactor, in memory only, `secret_sources` counts and `degraded` in `bundle.json`). Recorded, not fixed:

20. **x5 — the rest of m7: `release_info.py` does not require a COMPLETE set of gate reports** [agent 0, with A12].
    One green report is enough, even an `--only` of a single file: the suites `unit`, `browser` and `release` and the
    number of shards are not required (in CI, `needs: [static, tests, browser]` and the joined `gate-*` artifacts make
    up for it). A gate report's `source_revision` is `HEAD` even when the working tree is modified
    (`release_test_gate.py`, `source_revision()`), so a local run on uncommitted changes is reported at the last commit.
    Fix: record `git status --porcelain` emptiness (`worktree_clean`) in the report and refuse a dirty one; let
    `release_info.py` require one report per expected suite/shard (or a `--require unit:4,browser:10,release:1`).

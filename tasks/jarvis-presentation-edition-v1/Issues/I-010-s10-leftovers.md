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
   `tests/known_failures.json`. `test_product_setup.py::test_the_deferred_removal_waits…` failed once under load:
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

# I-009 — Slice 07 leftovers (QA 2026-10-26, rework 2026-10-27)

Origin: Slice 07 QA (code review `slices/07-installer-onboarding-health/qa/code-review.md`, runtime QA of 2026-10-26)
and its rework (LOG entry « 2026-10-27 — Slice 07, reprise QA »). The rework fixed B1, both majors (rollback, foreign
folder with an unreadable manifest) and the listed minors; what follows was deliberately left out. Not blocking; owners
in brackets.

1. **Late refusal of a locked file** [Slice 10] — runtime QA m5: when a file of the program is in use by something
   other than JARVIS (antivirus scan, an editor), the installer only finds out after the full package verification
   (~3 min): the rename of the current program then refuses with `jarvis_running`. A cheap rename probe (or an
   exclusive-open probe of the main executables) before `verify_package` would answer in seconds.
2. **PID reuse in `launcher.json`** [Slice 10] — runtime QA m6 and code review m7: `launcher_running`
   (`jarvis/product_setup.py`) and `ProductReadinessService.launcher()` (`jarvis/runtime/product_readiness.py`) trust
   only that the PID is alive. After a launcher crash, a reused PID makes the installer refuse with `jarvis_running`
   and shows « Quitter JARVIS » for nothing (fails safe, nothing is killed). Fix: write the process creation time in
   `launcher.json` and compare it (`GetProcessTimes`).
3. **DLL search order of the .NET bootstrap** [HV-INSTALL-04 / HV-PACKAGE-10] — code review O2: the unsigned
   `JARVIS-Setup.exe` run from the Downloads folder follows the default DLL search order (no
   `SetDefaultDllDirectories`). To handle with signing.
4. **Screen readers in the WinForms window** [Slice 10] — code review O5: phase and status updates of the bootstrap are
   not announced (no UI Automation notification / live region equivalent). The graphical installer has never run.
5. **CLI stderr copied into the error** [Slice 10] — code review O3: `brain_cli.probe` copies the last stderr line of
   `claude auth status` (200 characters) into `error` when the JSON is unreadable. Not the case today; it would reach
   the report and the journal if the CLI ever printed an address there. Redact or drop it.
6. **Not exercised for real** [Slice 11, HV-INSTALL-01]: the installer's graphical window, SmartScreen on the unsigned
   installer, the real registry / Start menu / Desktop / « Applications installées » (the rework trial used the JSON
   hive and simulated folders; the deferred removal was run with `pythonw.exe` and a real message box, but launched
   by hand, not by Windows), the real `brain_sign_in` (would open the user's account sign-in) and `connect_circoe`
   (OAuth registration at Circuit Toolbox, HV-07-01), and Voice started by the launcher (`JARVIS_LAUNCH_VOICE=0` in
   every trial).
7. **Observations of the rework** (no action decided):
   - Voice does not read the clean stop request (`JARVIS_STOP_REQUEST_FILE`): « Quitter JARVIS » still terminates it.
     Its `finally` (audio close) is therefore skipped; the Job Object ends its tree.
   - The deferred removal script waits at most 30 min for the uninstalling process, then tries anyway; a message box
     left open longer leaves a recognised leftover (key kept), never an orphan.

## Rework counter-review (`qa/rework-review.md`, `cabd2782`)
- mn1: the deferred uninstall script watches the process by PID + image name, without start time, and does not check it still owns the target: a reinstall made while it waits on a reused PID gets erased (probe R2; data untouched; very unlikely). Cheap fix: a token in the state file, checked before each delete.
- mn2: a `.failed-*` folder that could not be deleted is never resumed (probe R10): a full package size left after a successful install.
- mn3: `&`, `%`, `!`, `^` in the Windows profile name: default target refused `target_unsafe` (install needs `--target`), and `%` in `%TEMP%` loses the uninstall log.
- mn4: no test checks the failed copy is set aside before deletion (surviving mutation).
- mn5: the uninstall log says the key was removed without checking `reg delete` succeeded.
- mn6: `/S` only catches `ArgumentException` on paths (`setup_stub.cs`); another path error would crash with a Windows dialog (read only).

# Slice 07: QA code review and verification

Reviewer: independent QA agent (`code-review` + `qa-verification`, with `error-handling` and `impeccable` used as checklists). Date: 2026-10-26.
Scope: `2e7f2972..169db0c7` (`f888775f`, `758a3e36`, `707f4d2d`, `efa48283`, `7fe5e9a0`, `169db0c7`) on `task/jarvis-presentation-edition-v1` (worktree `pev1`). No product code was changed. No JARVIS, installer or package build was launched. Probes and mutations ran on copies in the session scratchpad.

## Summary

The Slice delivers what it promised: a per-user installer, one launcher, the readiness matrix with named actions, a first-run window, and a level-3 contract (`docs/product-install.md`). Several parts are sound:

- the Job Object containment;
- the package check that runs before the program folder is touched;
- the server-side gate on « Commencer »;
- the `full` edition, which reads nothing;
- jargon-free labels and an accessible dialog.

Uninstall and rollback do not hold up. Uninstalling the normal way, from Windows « Applications installées » (a message box is shown), reliably leaves a broken program folder that the installer then refuses to reinstall into. A failed update whose cleanup hits a locked file leaves no working program, and the message says the opposite. The real trial ran neither path: it used `uninstall --quiet` with `python.exe`, and no rollback happened under a lock.

**Recommendation (PM decides):** fix B1 and M1 before approval. The minors can go to an Issue.

## Scope Reviewed

- Installer: `packaging/windows/setup_stub.cs` (whole file), `packaging/windows/build_package.py` (diff), `jarvis/product_setup.py` (whole file), `jarvis/private_runtime.py` (diff).
- Launcher: `jarvis/runtime/product_launcher.py` (whole file), `jarvis/app.py` (dispatch).
- Readiness: `jarvis/runtime/product_readiness.py` (whole file), `jarvis/runtime/brain_cli.py`, `jarvis/runtime/cli_catalog.py`, `jarvis/protocol/client.py`, the `report_payload`/blocking logic of `jarvis/domain/product_readiness.py`, `jarvis/runtime/control_center.py` (wiring plus the origin guard), and the action, URL and a11y paths of `control_center_product_readiness.js`.
- Docs and handoff: `docs/product-install.md` (Installer and Launcher), `SLICE.md`, the S07 entry of `LOG.md`, `human-validation.json` of S06 and S07, I-002, I-006 and I-007.
- Screenshots: `after-refused-repair-1440x900.png` and `after-first-launch-600x800.png`.

## Evidence

Tests run in the foreground with `C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe -B -m pytest`, from `pev1`:

| Batch | Result |
| --- | --- |
| `test_product_setup`, `test_windows_installer`, `test_product_launcher`, `test_brain_cli`, `test_product_readiness`, `test_product_readiness_js` | 73 passed |
| `test_product_readiness_browser`, `test_private_runtime`, `test_windows_packaging`, `test_control_center_shell_layers` | 112 passed |
| `test_control_center_relay_whitelist`, `test_app`, `test_presentation_edition_ui_browser`, `test_product_edition`, `test_product_edition_ui_js` | 115 passed, 1 failed: the known `test_app::…tools_gateway_target…` |
| `test_control_center_presentation_rail_browser`, `test_control_center_presentation_rail_js`, `test_browser_harness_safety` | 47 passed |
| `test_status_centre_browser`, `test_global_launcher_browser` | 36 passed |

Note: `test_windows_installer` compiles the stub and runs it with `/S` on a fake package under `tmp_path`, with an injected registry file. That is part of the suite. No real target was touched.

Scratchpad probes (`scratchpad\s07qa\probe_setup.py`, run against the real `product_setup` of `pev1`, all paths under the scratchpad):

- **P1**: deferred uninstall while the uninstalling process still holds a program file (the final message box is still open). Result: `target exists: True leftover: ['runtime', 'runtime\\python', 'runtime\\python\\pythonw.exe'] registry: None`. Reinstalling then fails with `target_not_empty`.
- **P2**: uninstall of a foreign folder that holds an unreadable `runtime-manifest.json`. Result: the folder is deleted, `thesis.docx` included.
- **P3**: a failed update whose half copy cannot be fully removed because a file is locked. Result: `PermissionError [WinError 5]` is raised from the rollback. The target exists but has no manifest. The previous program sits aside as `Jarvis.previous-20261026T222457Z`.
- **P4**: the stub's command line with a trailing backslash on `--target`. Python receives `--target 'D:\Apps\Jarvis" --progress C:\w\progress.jsonl --result C:\w\result.json'`.

Mutations (scratchpad copy `s07qa\mut`, `s07qa\mutate.py`):

| Mutation | Result |
| --- | --- |
| M1: remove the refusal of a target that is an ancestor of the home | **SURVIVED** |
| M2: the instance lock is always granted | killed |
| M3: remove the server-side `readiness_not_ready` gate | killed |
| M4: remove the restore of the previous program in rollback | killed |
| M5: remove the `not_a_jarvis_folder` guard | killed |

Files: the committed blobs of every changed text file contain 0 CR and 0 control bytes, both before and after the Slice. The index is LF everywhere. Three working copies are `w/mixed` under `core.autocrlf=true`; this is cosmetic, and the blobs are clean.

## Findings

### BLOCKER

**B1. The normal uninstall leaves a broken program that blocks reinstalling.** `jarvis/product_setup.py:476` and `:549-558`.

- The deferred removal waits a fixed `ping -n 4` (about 3 s), then runs `rmdir /s /q`. It does not wait for the uninstalling process to end.
- `main()` spawns that command and only afterwards shows `_tell(« JARVIS est désinstallé … »)`, a modal message box. `pythonw.exe` stays alive until the user clicks OK.
- This is the path Windows takes from « Applications installées »: `UninstallString` has no `--quiet`.

Failure scenario: the user takes more than about 3 s to read the box. `rmdir` deletes everything it can, including `runtime-manifest.json`, but not the files the running Python holds (`pythonw.exe`, `python314.dll`, loaded `.pyd`). The uninstall key and the shortcuts are already gone, so the leftover folder is orphaned. The next install finds a non-empty folder with no manifest and refuses with `target_not_empty`: « Ce dossier contient déjà autre chose que JARVIS ». The user cannot reinstall without deleting the folder by hand.

Proof: probe P1 (above).

Related problems:
- The same orphaning happens when the direct `shutil.rmtree(target)` (`:481`) fails after `registry.delete()` (`:466`).
- The docstring at `:446-447` claims the command « attend la fin de ce processus », which is false.

Not covered by a test, and not exercised by the trial (`trial.py` uses `uninstall --quiet` with `python.exe`).

Suggested direction:
- Wait for the real end of the process (pass the PID and wait on it, or poll with a bound), and show the message before spawning.
- Then retry or report what remains.
- Remove the key only after the folder is gone, or keep a recoverable mark so a reinstall recognizes a half-removed JARVIS folder.

### MAJOR

**M1. The update rollback is not reliable.** `jarvis/product_setup.py:407-414`.

- On failure after the swap, `shutil.rmtree(target, ignore_errors=True)` can leave files behind. The antivirus scanning freshly written files is exactly what the LOG measured.
- `os.replace(previous, target)` then raises inside the `except` block.
- The previous program stays at `<target>.previous-<UTC>`, the target is a headless half copy, and the original error is replaced by the `PermissionError`.
- The stub then shows « Rien n'a été effacé : une installation précédente reste en place. » (`setup_stub.cs:310`), which is false here. The shortcuts point to a broken program.
- The next install refuses with `target_not_empty`: no manifest, folder not empty.
- Stale `.previous-*` folders are never named or cleaned up.

Proof: probe P3.

Suggested direction:
- Restore by renaming the failed copy aside first (`target` → `.failed-…`, then `previous` → `target`) instead of deleting before restoring.
- Report `rollback_failed` with both paths.
- Let install recognize and recover a `.previous-*` folder.

### MINOR

- **m1. Weak foreign-folder guard on uninstall.** `jarvis/product_setup.py:454-457`. A folder whose `runtime-manifest.json` is unreadable is treated as JARVIS (`manifest = {}`) and deleted. The target comes from the HKCU `InstallLocation` or `--target`. Proof: probe P2. Suggestion: also require the product marker (`app\<PRODUCT_MARKER>`) before deleting anything.
- **m2. A trailing backslash breaks the stub's command line.** `packaging/windows/setup_stub.cs:155` (`Quote`), with `:81-84` (`GetFullPath` keeps the trailing separator). `"D:\Apps\Jarvis\"` swallows the following arguments (probe P4). This fails closed (`target_unsafe` or « s'est arrêtée sans rendre son issue »), but the cause is unreadable. Suggestion: trim trailing separators, or double the backslashes before the closing quote.
- **m3. Refusal text in English with technical words.** `jarvis/runtime/product_readiness.py:290-308`, `:459`, `:274-275`; JS `act` (`control_center_product_readiness.js:281`). The line shows the server's English technical message, for example « Core is unreachable: ConnectionRefusedError (core_unreachable) » in `after-refused-repair-1440x900.png`. This goes against « user-facing status language that hides implementation jargon ». Suggestion: map the codes to product sentences and keep the technical detail under « Détails ».
- **m4. A URL opened after an `await` can be blocked by the browser.** `control_center_product_readiness.js:274`: `win.open` runs after the POST, and the server also rebuilds the full report (`product_readiness.py:387`, CLI probes, Core reads up to 6 s). Past the browser's user-activation window, the popup is blocked. `win.open`'s return value is not checked, while the line says « … la page CIRCOE qui s'ouvre ». Most exposed: `connect_circoe`, and `brain_install_guide` when the cache has expired. Not verified at runtime. Suggestion: if `open` returns `null`, show a visible link.
- **m5. `launch` does not refuse a development checkout.** `jarvis/runtime/product_launcher.py:495-501`. `docs/product-install.md` › Launcher §1 says it « checks the installation (marker…) », but without a marker it starts Core, Control Center and Voice on the development ports and data. On this machine that collides with the user's live Core (Errno 10048, crash loop). The process handles keep it from killing anything outside its own tree. Suggestion: refuse `launch` without a marker (`not_installed_product`), or document it.
- **m6. « Quitter JARVIS » is a hard kill.** `jarvis/runtime/product_launcher.py:433-446`. `Popen.terminate()` on Windows is `TerminateProcess`: Core and the Control Center get no shutdown (renders in progress, brain sessions, flushes). The docstring and the doc say « s'arrête proprement ». Suggestion: a Core and Control Center stop route, or `CTRL_BREAK_EVENT` with `CREATE_NEW_PROCESS_GROUP`, before `terminate`.
- **m7. PID reuse gives false « running » answers.** `launcher_running` (`product_setup.py:284-294`) and `ProductReadinessService.launcher()` (`product_readiness.py:333-343`) trust only that the PID is alive. After a launcher crash, a reused PID makes the installer refuse with `jarvis_running` and shows « Quitter JARVIS » for nothing. This fails safe, with no kill. Suggestion: write the creation time to `launcher.json` and compare it.
- **m8. The silent stub can crash after a successful install.** `setup_stub.cs:342`: in `/S --launch` mode, an exception from `LaunchJarvis` is not caught. The result is a crash with no log line, after an install that succeeded.
- **m9. Misleading failure text on a first install.** `setup_stub.cs:310` always adds « une installation précédente reste en place », even when there was none.
- **m10. Test gaps.**
  - Mutation M1 survives: the `targets.target in home.parents` refusal (`product_setup.py:247`) is never tested, yet it protects the home on uninstall.
  - No test for B1 (lock or message box during the deferred removal), M1 (rollback with a locked file), the stub's `SafeEntry` (zip slip) or its argument quoting.
- **m11. Module docstring out of date.** `jarvis/product_setup.py:6` documents `--move`, which the stub never passes.

## Answers to the review priorities

- **Integrity before writing.** Yes. The stub extracts into `<parent>\.jarvis-setup-<guid>`, a per-user folder with a random name, using `FileMode.CreateNew`. `verify_package` then checks every tree and `package_sha256` before the target is renamed. The program folder is never written before that check.
  - This is integrity, not authenticity: the manifest travels inside the payload it describes, and the executable is unsigned (HV-INSTALL-04 / HV-PACKAGE-10).
  - The verifying Python itself comes from the not-yet-verified payload. That is inherent to the design; only signing closes it.
- **Zip slip.** Guarded (`SafeEntry`: prefix check on `GetFullPath`, rooted names refused, `:` refused). Read as correct; no test exercises it (m10).
- **Elevation.** No admin rights are requested. `csc` embeds its default `asInvoker` manifest; the executable was not inspected (not verified).
- **DLL hijacking.** The Python child loads from the freshly extracted folder. The .NET stub run from the Downloads folder follows the normal DLL search order; there is no `SetDefaultDllDirectories` mitigation (Observation O2).
- **Uninstall outside the program folder.**
  - `check_target` refuses the home, its ancestors and its descendants.
  - The target is `resolve()`d.
  - Neither `rmtree` (Python 3.14) nor `rmdir /s` follows junctions inside the folder.
  - Remaining hole: m1.
- **Data kept.** No code path writes to `%LOCALAPPDATA%\CIRCOE\Jarvis` (install, repair, uninstall), and the tests check the home byte for byte.
- **Launcher.**
  - Single instance through `msvcrt.locking`, which removes the double-click race.
  - Each child runs in its own `KILL_ON_JOB_CLOSE` Job Object, through Popen handles. There is **no `taskkill` and no kill by a stored PID** anywhere in the Slice (grep on all changed files).
  - Restarts are bounded (3 in 120 s).
  - Refusals are shown and journaled.
  - Every child runs with `-B`; the MCP servers started by the CLI do not (I-007).
  - The `full` edition and the development commands are unchanged; `launch` is a new command (m5).
- **First run.**
  - The `readiness_not_ready` gate is server-side (M3 killed). « Plus tard » lets the user use JARVIS without finishing, which is by design.
  - No secret is logged: `auth status` is reduced to `loggedIn`/`authMethod`, and the CIRCOE `authorization_url` goes only to the page.
  - The CLI is not redistributed.
  - `claude auth login` is spawned as a list, with no user-controlled argument.
- **HV-PACKAGE-02 (PowerShell step).** There is **no PowerShell step at all**. `brain_install_guide` only returns the official page `https://docs.anthropic.com/en/docs/claude-code/setup` (a constant in `brain_cli.py:39`), opened on click. Nothing is downloaded or run.
- **Docs.** `docs/product-install.md` is consistent with the code except on the points above:
  - « waits ~3 s » is accurate, but the module docstring and the LOG wording overstate it (B1);
  - « stops cleanly » (m6);
  - « checks the installation » (m5).
- **Line endings and control characters.** Clean (see Evidence).

## Flagged

- **O1.** `GET /api/product/readiness` is not in `READ_GUARDED_ROUTES` (`control_center.py:327`). It exposes the CLI version, the sign-in method, connector states and the launcher state to a DNS-rebinding read. Low sensitivity. The POSTs are covered by the generic Origin guard.
- **O2.** The .NET stub run from the Downloads folder: DLL search order without mitigation (pre-signing; to handle with HV-INSTALL-04).
- **O3.** `brain_cli.probe` copies the last stderr line of `claude auth status` (200 characters) into `error` when the JSON is unreadable. That is not the case today, but it would reach the report and the journal if the CLI ever printed an address there.
- **O4.** `connect_circoe` is not covered by `_running`: a double click can register the plugin twice (`product_readiness.py:468-477`).
- **O5.** The WinForms window: phase and status updates are not announced to screen readers. The graphical installer was never run (stated in the LOG).

## Missing / Not Verified

- The installer's graphical window, the real registry, Start menu, Desktop and « Applications installées », and SmartScreen (HV-INSTALL-01).
- The interactive uninstall: reproduced here by simulation only (P1).
- The stub's embedded manifest (`asInvoker`).
- The real `brain_sign_in` and `connect_circoe`.
- The behaviour of `window.open` after a long action.
- `test_control_center_*` beyond the batches above; I-006 / I-007 cross-checked only by reading.

## Residual Risks

- Unsigned installer with no authenticity check of the payload.
- MCP servers started without `-B`.
- Hard kill of Core when the user quits (m6).

## Improvement Opportunities

- One `remove_program(target)` helper that waits for its users, renames before deleting, and is the only place allowed to delete a program folder (B1, M1, m1).
- Map the codes to product sentences in one table, shared by the page and the stub (m3, m9).

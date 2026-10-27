# Installer, launcher, first run and readiness of the Presentation Edition (contract)

Canonical contract, documentation **Level 3**: vocabulary, contract, one reusable implementation per
part and conformance tests. Handoff `tasks/jarvis-presentation-edition-v1/` (Slice 07). It builds on
[windows-packaging.md](windows-packaging.md) (the package, Slice 06), [local-data.md](local-data.md)
(the product home, Slice 02), [product-connectors.md](product-connectors.md) (connector states,
Slice 05) and [product-edition.md](product-edition.md); it does not repeat them.

| What | Code | Proof |
| --- | --- | --- |
| Installer bootstrap (one `.exe`, silent mode, injectable targets) | `packaging/windows/setup_stub.cs`, `build_package.py installer` | `tests/unit/test_windows_installer.py` |
| Install, update, repair, uninstall (data kept) | `jarvis/product_setup.py` (`python -m jarvis.product_setup`) | `tests/unit/test_product_setup.py` |
| Package verification shared by build, installer and repair | `jarvis/private_runtime.py` (`verify_package`) | `tests/unit/test_windows_packaging.py`, `test_product_setup.py` |
| Single launcher (Core, Control Center, Voice; one instance; no orphan) | `jarvis/runtime/product_launcher.py` (`python -B -m jarvis launch`) | `tests/unit/test_product_launcher.py` |
| Clean stop request of a launched role | `jarvis/runtime/stop_request.py` (`JARVIS_STOP_REQUEST_FILE`, read by `jarvis/app.py` Core and Control Center) | `tests/unit/test_product_launcher.py` |
| Readiness matrix (pure, product words) | `jarvis/domain/product_readiness.py` | `tests/unit/test_product_readiness.py` |
| Readiness facts, named actions, first run | `jarvis/runtime/product_readiness.py` (`/api/product/*`) | same |
| Claude Code CLI: locate, sign-in state, official sign-in | `jarvis/runtime/brain_cli.py`, `cli_catalog.resolve_command` | `tests/unit/test_brain_cli.py` |
| « Préparation de JARVIS » window, home line | `jarvis/runtime/control_center_product_readiness.js` | `tests/unit/test_product_readiness_js.py`, `test_product_readiness_browser.py` |

## Who owns what

| Owner | Owns | Never touches |
| --- | --- | --- |
| Installer (`product_setup`) | the program folder, its shortcuts, its uninstall key | `%LOCALAPPDATA%\CIRCOE\Jarvis` (data, settings, presentations, `CONTEXT_GLOBAL`) |
| JARVIS (launcher, Core, Control Center) | `%LOCALAPPDATA%\CIRCOE\Jarvis` | the program folder (read only, `-B`) |
| The user | exports in `Documents\Jarvis`, the Claude Code CLI and its account | — |

Update, repair (reinstalling the same version) and uninstall keep the product home byte for byte.
Uninstall says where it stays. V1 offers no « also delete my data » option: deleting the home is a
deliberate manual act (decision HV-INSTALL-03, safe default).

## Installer

**Technology (recommendation under HV-PACKAGE-10, nothing installed on the build machine).** A
per-user installer, no administrator rights, no UAC prompt:

- the bootstrap is a small WinForms program written in C# 5 and compiled by the **C# compiler of the
  .NET Framework 4.x that ships with Windows 10/11** (`%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe`);
  no Inno Setup, WiX, NSIS or MSIX toolchain is needed;
- the package folder (Slice 06) is zipped **deterministically** (path order, fixed date) and appended
  to the bootstrap, followed by a 24-byte trailer: `JVSETUP1` + offset (int64 LE) + length (int64 LE);
- the bootstrap only extracts and shows progress; the installation itself is done by the **package's
  own Python** (`python -B -m jarvis.product_setup install`), so one tested implementation serves the
  graphical installer, unattended deployment and repair.

The executable is **unsigned** (HV-PACKAGE-10: signing identity to choose; SmartScreen will warn until
it is signed). The C# 4.x compiler has no deterministic mode: the bootstrap bytes change from one build
to the next, the payload zip does not (`payload_sha256` in the build report).

```powershell
# after `build_package.py build --out <pkg>` (windows-packaging.md); output outside the repository
.\.venv\Scripts\python.exe packaging\windows\build_package.py installer --package <pkg> --out $env:TEMP\JARVIS-Setup-0.2.0.exe
```

The build refuses a package that `verify_package` finds altered and reports
`{package_sha256, payload_sha256, installer_sha256, files, bytes, signed:false}`.

**Install location**: `%LOCALAPPDATA%\Programs\CIRCOE\Jarvis` by default (per user, outside the
product home; the export guard refuses an overlap). Start menu and Desktop shortcut `JARVIS.lnk` →
`<install>\runtime\python\pythonw.exe -B -m jarvis launch`. Uninstall key
`HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\CIRCOE.Jarvis` (`DisplayName`,
`DisplayVersion`, `Publisher`, `InstallLocation`, `UninstallString`, `QuietUninstallString`,
`EstimatedSize`, `NoModify`, `NoRepair`). Windows « Installed apps » runs
`pythonw.exe -B -m jarvis.product_setup uninstall` (confirmation, then a final message).

**Nothing is deleted without proof that it is JARVIS** (`product_setup.folder_kind`). A program
folder is JARVIS only with **both** proofs: the Slice 02 product marker `app\jarvis-product.json`
(schema, vendor `CIRCOE`, product `Jarvis`) **and** a readable `runtime-manifest.json` of the known
schema whose `product.name` is `Jarvis`. The only other folder the installer may replace or delete is
a **leftover** of its own unfinished operation: an operation state `<target>.setup-state.json`
(`jarvis.setup-state` v1, written **next to** the target before any destructive step, removed when the
step has succeeded) that names this exact target, and every entry of the folder is one it listed.
Anything else is foreign: install refuses `target_not_empty`, uninstall refuses
`not_a_jarvis_folder` (S07 QA: a folder with an unreadable manifest used to be deleted).

**Steps** (`product_setup.install`): refuse a running JARVIS (`runtime\launcher.json` of a living
launcher: PID **and** creation time, `product_launcher.launcher_alive`, so a PID reused after a launcher
crash never blocks the installer — Slice 10, I-009 point 2) → **rename probe** of an installed program
(`probe_swappable`, Slice 10, I-009 point 1: the program is renamed to `<target>.previous-<UTC>` and
straight back, the operation state naming it; a file held by an antivirus or an editor refuses
`jarvis_running` in seconds instead of after the verification; a failed rename back is
`rollback_failed`, resumed by the next install) → verify the source package (every tree,
`package_sha256`) → write the operation state →
rename the current program (or a recognised leftover) to `<target>.previous-<UTC>` (a file still in
use refuses with `jarvis_running`) → copy the new one → verify the copy → shortcuts → uninstall key →
remove the operation state → delete the previous folder (and the previous program left aside by an
earlier failed rollback, when it is JARVIS). Progress is one JSON line per step (`--progress`), the
outcome a JSON file (`--result`): the bootstrap shows both, with a live seconds counter.

**Rollback** (any failure after the rename): the failed copy is first **renamed aside**
(`<target>.failed-<UTC>`, with retries ~7 s for an antivirus or a file still open), the previous
program is renamed back, and only then the failed copy is deleted — never a delete before the
restore. The refusal says what is true afterwards: « L'ancienne version de JARVIS est remise en
place » (`rolled_back: true, had_previous: true`), « Rien n'a été installé » (first install), or
`rollback_failed` when a locked file prevents the restore: « Redémarrez Windows, puis relancez
l'installation : elle réparera JARVIS », with the target and the previous folder in `detail`
(`rolled_back: false`, `previous`). The operation state stays, so the next install recognises the
half copy as a leftover, replaces it and deletes the previous folder after success. A first install
that fails also removes the shortcuts it wrote.

**Refusals** (`SetupError.code`, a product sentence, a technical `detail`, extra fields in the
result): `package_damaged`, `target_not_empty` (a folder that is not JARVIS is never overwritten),
`target_overlaps_home` (the target is the home, inside it, or one of its ancestors), `target_unsafe`
(`" % ! ^ & | < >` in the path), `target_unusable`, `jarvis_running`, `installed_copy_damaged`,
`rollback_failed`, `not_a_jarvis_folder` (uninstall never deletes a foreign folder),
`uninstall_incomplete`, `not_installed`, `setup_failed` (unexpected; its message names install or
uninstall).

**Uninstall** (`product_setup.uninstall`), repairable at every step: shortcuts are removed first
(they would start a half-deleted program); the operation state is written; the folder is deleted
with retries; **only then** are the uninstall key and the operation state removed. If files stay
locked, `uninstall_incomplete` says so, the key stays (Windows still offers the uninstall) and a new
uninstall or install recognises the leftover.

**Uninstall from the program itself** (« Installed apps », `pythonw.exe`): the running Python lives in
the folder it removes, and the final message box keeps it alive as long as the user reads it. The
deletion is handed to a script `%TEMP%\jarvis-uninstall-<pid>-<UTC>.cmd` run by `cmd.exe` in a hidden
console (`CREATE_NO_WINDOW`; not `DETACHED_PROCESS`: without a console its `tasklist | find` pipe
never returns, measured) that **waits for the real end of that process** (`tasklist /fi "PID eq …"`,
once per second, at most 30 min), then deletes the folder with up to 40 attempts ~3 s apart, then
removes the uninstall key and the operation state, logs each step to `%TEMP%\jarvis-uninstall.log`
and deletes itself. If the folder cannot be removed, the log says `ECHEC`, the key stays and the
leftover stays recognisable.

### Unattended, CI and simulated installs

Every target is injectable; tests and trials never touch the real registry, Start menu or Desktop:

```text
JARVIS-Setup.exe /S --target <dir> --start-menu <dir> --desktop <dir> | --no-desktop
                    --registry-file <hive.json> --result <file> --log <file> [--launch]
python -B -m jarvis.product_setup install --source <pkg> --target <dir> --registry-file <hive.json> [...]
python -B -m jarvis.product_setup uninstall --quiet --registry-file <hive.json> [--target <dir>]
python -B -m jarvis.product_setup status --registry-file <hive.json>
```

`--registry-file` replaces `HKCU` by a JSON hive and, without `--start-menu`/`--desktop`, writes no
shortcut at all. Without `--target`, the bootstrap reads `LOCALAPPDATA` from its environment first
(a trial that redirects it never aims at the real profile), then the Windows known folder. Paths lose
their trailing separator and are quoted with the `CommandLineToArgvW` rules (a trailing `\` used to
swallow the following arguments). Bootstrap exit codes in `/S`: 0 = installed, 1 = failed (outcome in
`--result`/`--log`), 2 = refused argument (written to `--log`, else `%TEMP%\jarvis-setup-error.log`;
**never a dialog box in silent mode**), 3 = installed but JARVIS could not be opened (`--launch`,
logged). `product_setup` exit code 0 = done. `product_setup status` also reports `folder`
(`folder_kind`) and `pending` (the operation state).

## Launcher

`python -B -m jarvis launch` (the shortcut uses `pythonw.exe`: no console):

1. checks the installation (marker, `LOCALAPPDATA`) and creates `data\`, `runtime\`, `config\` under
   the product home (I-002 point 3). **Without the product marker it refuses** (`not_installed_product`,
   « ce dossier n'est pas un JARVIS installé ») instead of starting on the ports and data of the
   development JARVIS. A refusal is **visible** (a Windows message box without console;
   `JARVIS_LAUNCHER_NOTIFY=stderr` for unattended runs) and **durable**: `runtime\logs\launcher.log`
   (one JSON line per event) and `errors.jsonl`; before any home is known,
   `%TEMP%\jarvis-launcher-error.log` (I-002 point 4);
2. one instance per home (`runtime\launcher.lock`, `msvcrt.locking`): a second click reopens the page;
3. starts Core, waits for `/v1/health` (with its token), then the Control Center (`JARVIS_OPEN_BROWSER=0`
   for it), waits for `/api/status`, then Voice (optional, `JARVIS_LAUNCH_VOICE=0` leaves it out) **unless the
   user's persisted preference is Off or the voice provider key is missing**: Voice is then *held* with its code
   (`voice_off`, `voice_provider_key_missing`) instead of crashing three times ([voice-lifecycle.md](voice-lifecycle.md));
   the preference is re-read while JARVIS runs (Off stops Voice, Sleep starts it again); each
   child runs `python -B -m jarvis <role>` (no bytecode written in the program folder), its output in
   `runtime\logs\<role>.log`, **inside its own Job Object** `KILL_ON_JOB_CLOSE`
   (`owned_process_tree.OwnedProcessTree`): if the launcher dies, Windows ends the whole tree (MCP
   servers, Remotion, the Claude CLI) — no orphan; deadline `JARVIS_LAUNCHER_START_TIMEOUT_S`
   (default 120 s), its expiry is said with the role;
4. opens the page once (`JARVIS_OPEN_BROWSER=0`: not), publishes `runtime\launcher.json`
   (`pid`, `process_ref` = `pid:creation time` since Slice 10, `ui_url`, roles). Readers
   (`launcher_alive`: installer, uninstaller, « Quitter JARVIS ») compare the creation time when
   `process_ref` is present; a state without it (older launcher) or an unreadable one falls back to
   the PID alone, the safe default;
5. watches: Core or Control Center that dies is restarted, at most 3 times in 120 s, then everything
   stops and the cause is shown (`child_crash_loop`); Voice that dies 3 times is abandoned
   (`child_abandoned`) without stopping the rest. A Core that dies at start because its port is taken
   says so (« une autre application utilise son port »);
6. stops on « Quitter JARVIS » (`POST /api/product/quit` writes `runtime\launcher-stop.request`) or
   Ctrl+C: Control Center and Voice first, Core last. **Core and the Control Center are asked to stop
   first**: each was started with `JARVIS_STOP_REQUEST_FILE=runtime\stop-<role>.request`
   (`jarvis/runtime/stop_request.py`); the launcher writes that file, the role leaves its main wait and
   runs its normal shutdown (`finally`: servers stopped, Core stopped, sessions closed, token removed;
   journal `core.stop_requested` / `ui.stop_requested`); the launcher waits up to 15 s
   (`child_stopped_cleanly`), and only then `terminate`, 5 s, `kill` (`child_stop_timeout`, warning).
   Voice reads the request too since Slice 05 of v1-2 (session and microphone closed by its `finally`). Each Job is then closed and the state
   and request files removed; a stale request is deleted before each start.

The development path is unchanged: `project jarvis start`, `scripts/supervisor_v2.py` and
`python -m jarvis core|control-center|voice` keep their behaviour (no `JARVIS_STOP_REQUEST_FILE`, no
change); `launch` is a new command for the installed product only.

## Readiness

`GET /api/product/readiness` (Control Center). **A read never changes anything**: it reads Core
(`/v1/health`, `/v1/boards/edition`, `/v1/edition/connectors`, `/v1/local-capabilities/remotion`,
`/v1/exports/root`, all through the relay whitelist), the Claude CLI (`--version`,
`auth status --json`: only `loggedIn` and `authMethod` are kept, never an e-mail or organisation),
the browser lookup of the renderer, the audio devices and the free disk space. Expensive facts are
cached (CLI 30 s, 3 s while a sign-in is open; audio 60 s); `?force=1` re-reads.

| Item | Group | Required | Ready when | Named actions |
| --- | --- | --- | --- | --- |
| `core` | essentials | yes | Core answers `ready` | `recheck` |
| `data` | essentials | yes | `data\`, `runtime\`, `config\` exist; data root from the product home | `prepare_data` |
| `runtimes` (installed only) | essentials | yes | private runtimes `ok`; last `verify_installation` clean | `verify_installation` |
| `brain` | essentials | yes | Claude Code found and signed in | `brain_install_guide`, `brain_sign_in`, `recheck` |
| `render` | essentials | yes | Remotion capability `ready`/`running`, pinned versions, and (installed) the private Node present | `render_install`, `render_repair`, `render_update`, `render_enable`; `verify_installation` when the private Node is missing (a reinstall puts it back) |
| `browser` | essentials | yes | Edge or Chrome found (HV-PACKAGE-09) | `recheck` |
| `connector:<id>` | services | no | Core says `ready` | `connect_circoe` (Circuit Toolbox), `open_connections` |
| `audio` | computer | no | at least one input and one output | `recheck` |
| `voice` | computer | no | Sleep or Active ([voice-lifecycle.md](voice-lifecycle.md)); Off is optional, a missing provider key is « À faire » | `open_connections` (key missing) |
| `disk` | computer | below 512 MB only | ≥ 2 GB free (below: optional warning) | `recheck` |
| `export` | computer | no | `Documents\Jarvis` usable (created at the first export, [export.md](export.md)) | — |

States: `ready` « Prêt », `action_needed` « À faire », `in_progress` « En cours », `optional`
« Facultatif », `unavailable` « Indisponible ». A fact that could not be read is `unavailable` with
its cause in `detail`, never `ready`. The report is `ready` when no required item is open. Sentences
are product words (no « MCP », « npm », « CLI », « Remotion », « PowerShell », `.env`; a test pins
it); the exact cause is kept in `detail` (« Détails »).

### Named actions (`POST /api/product/readiness/actions/{action_id}`)

The only way the readiness view changes something. Each answer is
`{action_id, status: done|started|open|navigate, message, url?, report}`; refusals are
`{"error": {"code", "message", "detail"}}` — `message` a product sentence shown in the line, `detail`
the technical cause (Core's own words) shown under « Détails » with the code — (404 unknown action,
409 already running / not applicable, 5xx with the real cause), journaled
`product.readiness.action_failed` at `error` with the detail. `connect_circoe` and `brain_sign_in`
are held while they run: a second click (or a second tab) gets 409 `readiness_action_running`, the
account is never registered twice. A render operation that Core is still running keeps its mark
(`running_elapsed_s.render_*`) until a later read sees Core done (or 15 min): the line stays
« En cours » with a live seconds counter until it turns « Prêt ». `/api/product/*` is in
`READ_GUARDED_ROUTES` (loopback Host and Origin, also for reads).

**Pages to open** (`kind: open`): the page reserves a blank window **at the click** (the browser's user
activation is still valid), then points it at the URL the server returns; if the browser blocks it
anyway, the line offers the URL as a link (« Ouvrir la page »), journaled `open_blocked`.

| Action | Effect | Never |
| --- | --- | --- |
| `recheck` | forgets the cached CLI and audio facts | — |
| `prepare_data` | creates the missing home folders | deletes or moves anything |
| `verify_installation` | full package verification in the background (`verify_package`) | repairs the program folder (a reinstall does) |
| `render_install` / `render_repair` / `render_update` / `render_enable` | the Remotion local capability operation on Core (`docs/remotion-runtime.md`); `repair` reinstalls at the pinned versions — this is how a capability left `install_failed` after its runtime came back recovers (I-007 point 1) | touches presentations or the compiled cache of another capability |
| `brain_install_guide` | returns Anthropic's official setup page to open (`https://code.claude.com/docs/en/setup`) | downloads or runs anything (HV-PACKAGE-02) |
| `brain_sign_in` | opens `claude auth login` in its own console window; the line reads « En cours » until the CLI says signed in (deadline 10 min) | reads or writes inside that window |
| `connect_circoe` | registers the Circuit Toolbox account if absent, starts its connection, returns the consent page to open | stores a secret outside the vault (`docs/mcp/plugins.md` §3.3) |
| `open_connections` | page navigation to Réglages › Connexions | — |

### Brain: the Claude Code CLI (HV-PACKAGE-02)

Default applied: **not redistributed, not auto-provisioned**. The first launch guides: « Ouvrir la
page d'installation » (Anthropic's official setup page), then « Vérifier à nouveau », then « Se
connecter » (`claude auth login`, subscription or Console key, chosen in Claude's own window).
Installing the CLI with Anthropic's official installer is the one step that is Anthropic's, not
JARVIS's; letting JARVIS run that official installer on the user's click is a pending decision
(HV-PACKAGE-02). In the installed product, `brain_cli.locate` and `cli_catalog.resolve_command`
also look at the official install locations (`%USERPROFILE%\.local\bin\claude.exe`,
`%APPDATA%\npm\claude.cmd`, `%LOCALAPPDATA%\Microsoft\WinGet\Links\claude.exe`): JARVIS started from
the Start menu keeps the `PATH` it had before the CLI was installed. Development: unchanged.

## First run (onboarding)

`<html data-product-edition>` other than `full`: at page load, the « Préparation de JARVIS » window
opens by itself while the first run is not done **or** a required item is no longer ready. It shows
the three groups, a meter of required items, each line with its actions and details; an action in
flight shows its label with a live seconds counter and has a 45 s deadline; « Plus tard » and Échap
close it for this page (focus returned); it is reopened from the Presentation home line, by
`JarvisReadiness.open()` or `#preparation`. Only required items are asked; services are optional and
deferred cleanly.

**« Commencer »** (enabled when every required item is ready): `POST /api/product/onboarding/complete`
makes a **Presentation** Board active — the active one if it is a Presentation Board, else the first
Presentation Board, else a new « Mes présentations » — never an Assistant Board, then records
`runtime\product-onboarding.json` (`jarvis.product-onboarding` v1). The server holds the same rule as
the greyed button: while a required item is open it answers 409 `readiness_not_ready` (naming the
items) and changes nothing. An unreadable record replays the
first run (nothing is lost) and is journaled. Once done, the button reads « Fermer » and never switches
Boards again.

**Presentation home line** (I-006 point 2, `control_center_presentation_rail.js` › `homeFor`): what is
left before the first video, or « JARVIS est prêt. Comptes reliés : n sur m », with a button that opens
the window.

`full` edition (the development JARVIS): no read, no window.

## Repair runbook

| Symptom | What the user sees | What to do |
| --- | --- | --- |
| JARVIS does not open | message box « JARVIS ne peut pas démarrer … Détails : <log> » | read `runtime\logs\launcher.log` (or `%TEMP%\jarvis-launcher-error.log`); a port taken by another application is named |
| « Composants de JARVIS : À faire » | missing private runtime / failed verification | run the installer again (same version = repair); data kept |
| « Moteur de rendu : Réparer » | `install_failed` (offline, disk, permission, missing runtime) | « Réparer » (network needed); the cause is in « Détails » |
| « Navigateur pour le rendu : À faire » | no Edge/Chrome | install Edge or Chrome, « Vérifier à nouveau » |
| « Claude : À faire » | CLI missing or signed out | official setup page, then « Se connecter » |
| Compte CIRCOE « Facultatif » | not linked / authorisation expired | « Relier le compte CIRCOE » |
| JARVIS stopped by itself | message box `child_crash_loop` with the role | read `runtime\logs\<role>.log`; restart JARVIS |
| Installer: « l'état d'avant n'a pas pu être remis en place » (`rollback_failed`) | a locked file blocked the rollback | restart Windows, run the installer again: it recognises the half copy and repairs; data kept |
| JARVIS still in « Installed apps » after an uninstall | the deferred removal could not delete every file (`%TEMP%\jarvis-uninstall.log` says `ECHEC`) | close what uses the files (or restart Windows), uninstall again — or reinstall over it |
| Installer: « Des fichiers de JARVIS sont encore utilisés (JARVIS, un antivirus ou un autre programme) » | the rename probe found a file of the program held open | close that program (or wait for the antivirus), run the installer again |
| Support asks for diagnostics | — | `<install>\runtime\python\python.exe -B -m jarvis support-bundle`: a bounded, redacted zip under `runtime\support\` ([release.md](release.md#support-bundle)) |
| Installer refuses « Ce dossier contient déjà autre chose que JARVIS » | the target folder is not JARVIS (no marker or unreadable manifest) and no operation state names it | choose another folder, or move the user's files away; the installer never deletes them |

## Out of scope / open

- signing, final installer technology and location: HV-PACKAGE-10 (recommendation above);
- Google Drive linking from the onboarding needs a CIRCOE Google OAuth client: HV-INSTALL-02; until
  then the Drive line says it is not offered in this version;
- the official Claude Code installer run by JARVIS on the user's click: HV-PACKAGE-02;
- auto-update: none; the installer is update-compatible (same command, newer package). Update over an
  existing profile, migrations, rollback boundary, support bundle and crash recovery:
  [release.md](release.md);
- clean-machine trial: HV-PACKAGE-01 / HV-INSTALL-01.

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

**Steps** (`product_setup.install`): verify the source package (every tree, `package_sha256`) →
refuse a running JARVIS (`runtime\launcher.json` of a living launcher) → rename the current program to
`<target>.previous-<UTC>` (a file still in use refuses with `jarvis_running`) → copy the new one →
verify the copy → shortcuts → uninstall key → delete the previous folder. Any failure after the
rename puts the previous program back. Progress is one JSON line per step (`--progress`), the
outcome a JSON file (`--result`): the bootstrap shows both, with a live seconds counter.

**Refusals** (`SetupError.code`, a product sentence, a technical `detail`): `package_damaged`,
`target_not_empty` (a folder that is not JARVIS is never overwritten), `target_overlaps_home`,
`target_unsafe` (`" % ! ^ & | < >` in the path), `jarvis_running`, `installed_copy_damaged`,
`not_a_jarvis_folder` (uninstall never deletes a foreign folder), `not_installed`.

**Uninstall from the program itself**: the running Python lives in the folder it removes, so the
folder deletion is handed to a detached `cmd.exe` that waits ~3 s (`ping`) then `rmdir /s /q`.
Shortcuts and key are removed first, synchronously.

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
shortcut at all. Exit code 0 = done.

## Launcher

`python -B -m jarvis launch` (the shortcut uses `pythonw.exe`: no console):

1. checks the installation (marker, `LOCALAPPDATA`) and creates `data\`, `runtime\`, `config\` under
   the product home (I-002 point 3). A refusal is **visible** (a Windows message box without console;
   `JARVIS_LAUNCHER_NOTIFY=stderr` for unattended runs) and **durable**: `runtime\logs\launcher.log`
   (one JSON line per event) and `errors.jsonl`; before any home is known,
   `%TEMP%\jarvis-launcher-error.log` (I-002 point 4);
2. one instance per home (`runtime\launcher.lock`, `msvcrt.locking`): a second click reopens the page;
3. starts Core, waits for `/v1/health` (with its token), then the Control Center (`JARVIS_OPEN_BROWSER=0`
   for it), waits for `/api/status`, then Voice (optional, `JARVIS_LAUNCH_VOICE=0` leaves it out); each
   child runs `python -B -m jarvis <role>` (no bytecode written in the program folder), its output in
   `runtime\logs\<role>.log`, **inside its own Job Object** `KILL_ON_JOB_CLOSE`
   (`owned_process_tree.OwnedProcessTree`): if the launcher dies, Windows ends the whole tree (MCP
   servers, Remotion, the Claude CLI) — no orphan; deadline `JARVIS_LAUNCHER_START_TIMEOUT_S`
   (default 120 s), its expiry is said with the role;
4. opens the page once (`JARVIS_OPEN_BROWSER=0`: not), publishes `runtime\launcher.json`
   (`pid`, `ui_url`, roles);
5. watches: Core or Control Center that dies is restarted, at most 3 times in 120 s, then everything
   stops and the cause is shown (`child_crash_loop`); Voice that dies 3 times is abandoned
   (`child_abandoned`) without stopping the rest. A Core that dies at start because its port is taken
   says so (« une autre application utilise son port »);
6. stops on « Quitter JARVIS » (`POST /api/product/quit` writes `runtime\launcher-stop.request`) or
   Ctrl+C: Control Center and Voice first, Core last, each Job closed, the state files removed.

The development path is unchanged: `project jarvis start`, `scripts/supervisor_v2.py` and
`python -m jarvis core|control-center|voice` keep their behaviour; `launch` is a new command.

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
| `render` | essentials | yes | Remotion capability `ready`/`running`, pinned versions | `render_install`, `render_repair`, `render_update`, `render_enable` |
| `browser` | essentials | yes | Edge or Chrome found (HV-PACKAGE-09) | `recheck` |
| `connector:<id>` | services | no | Core says `ready` | `connect_circoe` (Circuit Toolbox), `open_connections` |
| `audio` | computer | no | at least one input and one output | `recheck` |
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
`{"error": {"code", "message"}}` (404 unknown action, 409 already running / not applicable, 5xx with
the real cause from Core), journaled `product.readiness.action_failed` at `error`.

| Action | Effect | Never |
| --- | --- | --- |
| `recheck` | forgets the cached CLI and audio facts | — |
| `prepare_data` | creates the missing home folders | deletes or moves anything |
| `verify_installation` | full package verification in the background (`verify_package`) | repairs the program folder (a reinstall does) |
| `render_install` / `render_repair` / `render_update` / `render_enable` | the Remotion local capability operation on Core (`docs/remotion-runtime.md`); `repair` reinstalls at the pinned versions — this is how a capability left `install_failed` after its runtime came back recovers (I-007 point 1) | touches presentations or the compiled cache of another capability |
| `brain_install_guide` | returns Anthropic's official setup page to open | downloads or runs anything (HV-PACKAGE-02) |
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

## Out of scope / open

- signing, final installer technology and location: HV-PACKAGE-10 (recommendation above);
- Google Drive linking from the onboarding needs a CIRCOE Google OAuth client: HV-INSTALL-02; until
  then the Drive line says it is not offered in this version;
- the official Claude Code installer run by JARVIS on the user's click: HV-PACKAGE-02;
- auto-update: none (Slice 10); the installer is update-compatible (same command, newer package);
- clean-machine trial: HV-PACKAGE-01 / HV-INSTALL-01.

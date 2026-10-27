# Release of the Presentation Edition: pipeline, gates, update, recovery and support (contract)

Level 3 contract of Slice 10 of `jarvis-presentation-edition-v1`. It says how a Windows release candidate
is built from a known commit, which evidence it must carry, how an update preserves the user's profile,
where the rollback boundary is, how a running product recovers from a crash, what a support bundle may
contain, and which gates remain physical, external or not delivered. Packaging itself is
[windows-packaging.md](windows-packaging.md); installer, launcher and readiness are
[product-install.md](product-install.md); the data layout is [local-data.md](local-data.md).

## Pipeline

`.github/workflows/ci.yml` (on pull requests, pushes to `main`, and by hand). Every step calls a script
of the repository, so each one runs locally exactly as in CI:

| Job | Script | What makes it red |
| --- | --- | --- |
| `static` | `python scripts/verify_release.py` | a release finding (below) |
| `tests` (4 shards) | `python scripts/release_test_gate.py --suite unit --shard K/4` | a failure not in the dated list, a stale, unseen or expired entry, a pytest session that did not finish |
| `browser` (10 shards) | `python scripts/release_test_gate.py --suite browser --shard K/10` | same, for the files that drive a real browser or Node (`*_browser.py`, `*_js.py`) |
| `package` | `packaging/windows/build_package.py build` / `verify` / `installer`, `scripts/package_smoke.py`, `scripts/release_info.py` | a build or probe failure, a tampered package, a red smoke step, a red verdict, a package, installer, smoke or gate report that do not belong together |

**Shard sizing** (QA S10 M1). Measured on this workstation on 2026-10-27: the browser suite runs at
0.9 min per file on average (65 files in 60 min over five gate runs; the independent real trial measured
about 55 min for about 80 files) and at 2.2 min per file for the slowest group (the settings files: 13
files in 28 min). The suite has 185 files: about 170 min at the mean, at most about 410 min if every
file were as slow as the slowest group. With 4 shards (46-47 files) a shard needed about 42 to 100 min,
over its former 60 min limit, and `package` (`needs: [static, tests, browser]`) could then never run.
Now: **10 shards** of at most 19 files, about 17 min each at the mean and at most 42 min at the slowest
rate, with `timeout-minutes: 75` (about 1.8 times the worst estimate). The unit suite (845 files, 19
local parts of 3 to 8 min, about 0.12 min per file) keeps 4 shards of at most 212 files, about 25 min
each, under 60 min. `test_every_ci_shard_fits_its_timeout_with_margin` (`test_release_tooling.py`)
fails when files per shard × the measured rate × 1.5 exceeds a job's timeout, so adding files cannot
silently push a shard over its limit. Each gate report carries its `duration_seconds`, so the first CI
runs replace these local figures.

The interpreter is the pinned private runtime's version (`3.14.6`, `packaging/windows/runtimes.json`): the
build compiles the package bytecode with it. The build download cache (`actions/cache`) is keyed on the
runtimes and the wheel lock and is re-verified by SHA-256 at every build; `pip` writes no user cache
(`--no-cache-dir`). The release artifact is uploaded under
`jarvis-<version>-<commit 12>-<installer SHA-256 12>` (an artifact is never rewritten under the same
name) with `JARVIS-Setup.exe`, `package-smoke.json` and `release-info.json`.

Decisions taken with the pipeline (2026-10-27):

- the former Ubuntu matrix (3.11-3.13, never executed: the audited commit had no run) is replaced by
  Windows jobs: V1 is Windows-first and the known-failure list is measured on Windows; a Linux job comes
  back with a measured list of its own;
- the former `-W error::ResourceWarning` run is not kept: it was never measured on Windows, and a gate
  whose result nobody has seen is not a gate. Re-enable it once a run shows which tests it fails;
- the PR comment step (it needed `pull-requests: write`) is gone; failures are in the job logs and the
  uploaded gate reports, and the workflow keeps `contents: read`.

**Not verified**: the workflow has been checked by `actionlint` 1.7.7 and every script it calls has run
on Windows 11, but it has never run on a GitHub-hosted runner (no push from the implementation agents).
Its first run is the gate `A12` below.

### Release verifier (`scripts/verify_release.py`)

Static, no model, no browser (`--with-tests` also runs the full test gate):

- **internal wheels** (`internal_lock_findings`): every wheel of `requirements-internal.lock` is reserved to the
  internal channel by the policy and none duplicates a production wheel (HD-V12-01);
- **edition guard** (`product_release_findings`): the `presentation` edition offers only Presentation
  Boards and hides developer surfaces; an installed product defaults to it; its agents are confined
  (`dontAsk`), receive none of Bash, PowerShell, Write, Edit, MultiEdit, NotebookEdit, REPL and deny them
  all, have no Codex, no `--chrome`, no debug console, no self-development; every package-owned tool
  (`node`, `npm`, `npx`, `python`, `py`, `ffmpeg`, `ffprobe`) is never resolved on the PATH by an
  installed product; no excluded component (openWakeWord, onnxruntime, imageio-ffmpeg, Porcupine,
  sherpa-onnx, MediaPipe) is back in the wheel lock;
- **execution primitives**: `os.system(` and `shell=True` nowhere in `jarvis/`; `subprocess.run(` only
  in the reviewed files of `SUBPROCESS_RUN_REVIEWED` (a new file is a finding until reviewed; a stale
  entry too). The former rule "no `subprocess.run` at all" was stale since Remotion, capture and the
  brain CLI, and its CI had never run;
- `ARTIFACT_INFO.json` names the version of `pyproject.toml` and points at the generated release info;
- the existing Presentation Studio and Remotion release evidence, benchmark tooling isolation, pinned
  third-party sources and privacy-by-default logging.

### Known failures

`tests/known_failures.json` is an **explicit, dated** list (`nodeid`, `kind` `failing` or `intermittent`,
`since`, `origin`, `issue`, `reason`, `review_by`), read by `scripts/release_test_gate.py`:

- any failure that is not listed fails the gate; an import error of a test file is a failure;
- a pytest session that did not finish fails the gate, whatever its tests said (QA S10 B1): an exit
  code other than 0 or 1 (2 interrupted by `KeyboardInterrupt` or `pytest.exit`, or a collection error;
  3 internal error; 4 usage; 5 nothing collected), 1 without any failure seen, a session stopped early,
  fewer tests run than collected, no report at all, or no test passed (everything skipped);
- a listed `failing` test that passes fails the gate: the entry is stale and must be removed;
- a listed `failing` test whose file ran but which neither failed nor passed (skipped, e.g. without
  Chrome) fails the gate: the known failure was not seen (QA S10 m1);
- a listed `intermittent` test that fails is rerun alone, at most twice, and must then pass;
- an entry past its `review_by` date fails the gate until someone looks at it again;
- there is no pattern, no file-wide entry, no global ignore.

The report (`--report`) gives `passed`, `failed`, `skipped`, `collected`, `exitstatus`,
`session_problems`, `duration_seconds` and the tested `source_revision`. About 40 Remotion tests of the
browser suite (`test_variants_*`, `test_presentation_*` renders) are **skipped** without
`JARVIS_REMOTION_RUNTIME_DIR` (an installed Remotion runtime with its `node_modules`) or
`JARVIS_VARIANTS_REMOTION_EVIDENCE_DIR`; the CI does not install Remotion (network `npm ci`), so these
tests are reported as skipped there, never as passed. Their coverage is the Slice 06/07/09 real renders
and gate A10.

The list was measured on 2026-10-27 (Windows 11, branch of the task at `79d1c7c5`). Every entry was
already failing before this task or on its base, with its Issue: the `ui_intent_publish` display tool
(brain capability parity, MCP API), the settings redesign (Connections, message destinations, shell
geometry), Barehands (excluded from the Presentation package), two older debts (`test_app` tools gateway
stub, `test_surface_reflex_policy`), and one intermittent layout test of the Studio explorer at 800×600.
Two former intermittents were fixed instead of listed (I-007 point 3): the render service test now waits
for the `cleanup` call that the service makes after publishing the final state, and the isolation regex
timing test measures the CPU time of its thread instead of the wall clock.

### Release info (`scripts/release_info.py`)

`release-info.json` is the identity of a candidate: product version, edition and channel (`production_blockers` for an internal build), `source_revision`,
`package_sha256` (after `verify_package`), runtime versions and tree hashes, installer SHA-256, size,
stub and zip payload (read from the `JVSETUP1` trailer), the SHA-256 of each build input **at the
package revision** (`git show`, never the working tree), build host, CI context (`GITHUB_*`), the
verdicts of the test gates and of the package smoke (each must be green, or nothing is written), the
artifact name, and the gates still open (`unsigned`, clean machine). It is never rewritten.

It refuses a candidate whose parts do not belong together (QA S10 R2: the real trial had produced a
« green » identity for a package of another revision, with no gate report and no smoke): at least one
`--gate-report`, each green and made at the package revision (`source_revision` of the report); the
`--smoke-report` is mandatory, green, made on **this** installer (same SHA-256) and its `install` step
installed **this** package (`package_sha256`); the package **embedded** in the installer (its
`runtime-manifest.json`, read in the appended zip without extracting it) has the declared
`package_sha256` and `source_revision`; in CI, `GITHUB_SHA` equals that revision.
`ARTIFACT_INFO.json` at the root only names the source version.

## Package smoke (`scripts/package_smoke.py`)

The real installer, installed under `--work` with every target explicit and redirected (`--target`,
simulated `LOCALAPPDATA` and `TEMP`, JSON hive, simulated Start menu and Desktop), children started
with `PATH` = `System32;Windows`, no Python/Node variable, `JARVIS_OPEN_BROWSER=0`,
`JARVIS_VISUALIZER_ENABLED=0`, `JARVIS_LAUNCH_VOICE=0`, dedicated ports (default 43653-43656). Steps:

| Step | Proves |
| --- | --- |
| `snapshot_before` / `snapshot_after` | the real profile (HKCU uninstall keys, `%LOCALAPPDATA%\Programs`, `%LOCALAPPDATA%\CIRCOE`, JARVIS shortcuts) is identical at the end |
| `seed` | a profile of a previous version is present before the install ([Update](#update-over-an-existing-profile)) |
| `install` | silent install; the seeded home is byte-identical afterwards; `verify_package` of the program is intact |
| `launch` | `/v1/health` ready, `installation.mode` `installed`, private runtimes `ok` with the reduced PATH, edition `presentation`, the seeded Boards and the seeded Presentation listed, no document of the profile judged corrupt, the profile migrated with its backups, `launcher.json` carrying `process_ref` |
| `crash_core`, `crash_ui` | the child is a verified descendant (PID and creation time) of the launcher **this script started**; it is killed; the launcher restarts it, Core is ready again, the profile is intact |
| `support_bundle` | the packaged `support-bundle` command writes its zip; a planted fake secret, the home path and the user name are absent; `%LOCALAPPDATA%` replaces the root |
| `quit` | « Quitter JARVIS » stops everything (no process of the program left) and the program folder was never written |
| `repair` | reinstalling the same version is a repair and leaves the home byte-identical |
| `kill_launcher` | the launcher (this script's own `Popen`) is killed: its Job Objects end every child |
| `uninstall` | `--quiet --target`: program and key removed, home kept and still verified |

`--phase install|run|repair|finish` runs the same steps in four parts (state in `smoke-state.json`),
for machines where one command is bounded to a few minutes; `--phase all` (default, CI) runs everything.
The script never stops a process it did not start (no `taskkill /T`, no memorised PID: kills go through
`process_tree.kill_tree` with the creation time, or through its own `Popen`).

Not covered by the smoke: the Remotion renderer (its install needs the network; renderer crash and
recovery are covered by the fault matrix of `test_remotion_release_faults.py` and the render runner
tests), Voice (no audio device on a runner; Voice abandonment after three crashes is covered by
`test_product_launcher.py`), the graphical installer window, the real registry/Start menu/Desktop,
SmartScreen.

## Update over an existing profile

The installer never touches the home `%LOCALAPPDATA%\CIRCOE\Jarvis` (install, update, repair, uninstall:
[product-install.md](product-install.md)). An update replaces the program; the **new Core** then migrates
the databases at its first start, forward only, one transaction per step, after a one-time backup
`<db>.v<old version>.bak` next to each base (`CLAUDE.md`, [state-model.md](state-model.md)). Files
(`CONTEXT_GLOBAL`, presentations, artifacts, Board memory, sessions, `config\.env`) are never rewritten
by an update.

`scripts/release_seed_profile.py seed` builds such a profile in a throw-away home: `jarvis.sqlite3`
created by the code of this repository brought back to schema **v10** (the real DDL and migrations up to
it) with three Boards (two Presentation, one archived Assistant, as a profile from before the edition),
`scene.sqlite3` at **v1**, and known bytes in `CONTEXT_GLOBAL`, a real Studio Presentation (written by the Studio service of the same code), an artifact, a
Board memory and a product `.env`. `verify` checks, read-only (immutable opening when no `-wal`/`-shm`
exists), that every seeded file is byte-identical, both bases are at the current version with their
`.v10.bak` / `.v1.bak` still at the old version, and the Boards kept their id, title, kind and status.
`tests/unit/test_release_update_profile.py` runs it with the installer code and fake packages; the
package smoke runs it with the real installer and the real installed Core.

## Rollback

**Program**: run the installer of the previous version. A different version is an `update`, so an older
package replaces a newer one and the home stays untouched (tested).

**Data — the boundary**: a Core refuses a base whose schema is newer than its own (`state DB schema N is
newer than supported M`). After an update has migrated the profile, the previous program therefore
**does not start**: the launcher shows `child_crash_loop` with Core's log, which names that cause.
To go back, with JARVIS stopped (« Quitter JARVIS »), for each base that was migrated:

1. rename the migrated base **and its own `-wal` / `-shm` if present**, with the UTC time of the
   rollback (`YYYYMMDDTHHMMSSZ`), to exactly:
   `<db>.v<new version>.before-rollback-<UTC>.bak`, `<db>.v<new version>.before-rollback-<UTC>.bak-wal`
   and `<db>.v<new version>.before-rollback-<UTC>.bak-shm` — for example `jarvis.sqlite3` →
   `jarvis.sqlite3.v11.before-rollback-20261027T101500Z.bak`, `jarvis.sqlite3-wal` →
   `jarvis.sqlite3.v11.before-rollback-20261027T101500Z.bak-wal`. They are kept, never deleted, a `-wal`
   is never replayed into another base, and the time makes a second rollback to the same version write
   new names instead of colliding with the first (QA S10 m10);
2. copy `<db>.v<old version>.bak` to `<db>` (a copy: the `.bak` stays);
3. start the previous version.

Everything written after the backup (Boards created, sessions, artifact rows, connector rows) is absent
from the restored base; the files of the data root stay (a newer artifact folder is then not indexed).
To upgrade again later, with JARVIS stopped, keep the `.before-rollback-<UTC>.bak` files aside and
first rename the old backup `<db>.v<old version>.bak` to exactly `<db>.v<old version>.restored-<UTC>.bak`
(for example `jarvis.sqlite3.v10.bak` → `jarvis.sqlite3.v10.restored-20261027T101500Z.bak`): a migration
never overwrites an existing `.bak`, so this rename is what lets the next migration write a fresh
`<db>.v<old version>.bak` of the base as the previous version left it
([state-model.md](state-model.md) has the per-version details). `test_release_update_profile.py`
exercises this whole procedure with these exact names: refusal of the newer base, base set aside,
backup restored, older Core reading the seeded Boards, seeded files and the migrated base still
present, then the old backup renamed and the re-upgrade writing fresh `.v10.bak` / `.v1.bak`.

Limits: there is no automatic downgrade and no down-migration; the data rollback loses what was written
after the backup; a profile copied to another Windows user or PC loses its DPAPI-sealed secrets
(`mcp_plugin_reauthorization_required`), by design.

## Crash recovery

| What dies | What happens | Evidence |
| --- | --- | --- |
| Core or Control Center | the launcher restarts it (at most 3 times in 120 s, then `child_crash_loop` with the role and its log); data on disk is untouched | package smoke `crash_core`, `crash_ui`; `test_product_launcher.py` |
| Voice | restarted, abandoned after 3 crashes without stopping the rest | `test_product_launcher.py` |
| the launcher | Windows ends each child's Job Object (`KILL_ON_JOB_CLOSE`): no orphan; the next start replays the WAL of the bases | package smoke `kill_launcher` |
| a launcher crash leaving `launcher.json` | its `process_ref` (PID + creation time) no longer matches: the installer and « Quitter JARVIS » ignore a reused PID | `test_product_launcher.py`, `test_product_setup.py`, `test_product_readiness.py` |
| the Remotion renderer / Studio | typed refusal, no fallback, job state kept; orphans found by job id | `test_remotion_release_faults.py`, render runner tests |
| an install interrupted | operation state next to the target; the next install resumes, rollback never deletes before restoring | `test_product_setup.py`, [product-install.md](product-install.md) |
| the installer itself killed (its extraction folder left behind) | the bootstrap's work folder is `Programs\CIRCOE\.jarvis-setup-<bootstrap PID>-<hex>`; the next successful install and the uninstall remove such folders when their bootstrap is dead (a live PID created before the folder keeps it; a reused PID does not), never the current one, never one whose files are still open (rename probe first), and an older name without PID only after one hour unchanged; the uninstall then removes `Programs\CIRCOE` if it is empty (never the home `%LOCALAPPDATA%\CIRCOE\Jarvis`) | `test_product_setup.py`, real trial of the S10 QA rework |
| a file of the program held by another program | rename probe refuses in seconds (`jarvis_running`) | `test_product_setup.py` |

## Support bundle

`<install>\runtime\python\python.exe -B -m jarvis support-bundle [--out DIR]`
(`jarvis/runtime/support_bundle.py`) writes `jarvis-support-<UTC>.zip` under `runtime\support\`
(temporary file then rename: never a half zip; two in the same second never overwrite each other):

| File | Content | Bound |
| --- | --- | --- |
| `bundle.json` | system, install mode, package version/edition/revision/`package_sha256`, `verify_package` result, `launcher.json`, `product-onboarding.json`, local capability states, schema versions and `.bak` names of both bases (read-only; opened `mode=ro` only when the `-shm` already exists, otherwise `immutable=1`: SQLite would create a `-shm` next to a `-wal` left alone by a hard stop or a copy, so in that case the `-wal` is not read and `wal_not_read: true` says so; nothing is ever created next to a base), file count and bytes per data folder (never a name), free disk | — |
| `logs/errors.jsonl` | end of the error journal: `ts`, `kind`, `level`, redacted `message` (500 characters), `data` redacted then filtered by **allowlist**: numbers, booleans, identifier-shaped strings (no space, 120 characters at most), and the text of the diagnostic keys only (`error`, `detail`, `reason`, `code`, `status`, `phase`…, 300 characters); any other text (a title, a query, a sentence) becomes its length | 400 lines |
| `logs/trace-events.jsonl` | end of the trace reduced to `ts`, `kind`, `level` — no message, no data (the trace may carry room speech) | 600 lines |
| `logs/<launcher|core|ui|voice>.log` | end of each log, each line redacted | 300 lines, 2000 characters per line |
| `config-keys.json` | the **names** of the variables of `config\.env` | — |

Every file is capped at 1 MiB (the end is kept); a line is cut at 16 000 characters before being
masked (the output keeps 2 000). Redaction (`jarvis/domain/diagnostic_redaction.py`):
**known secrets first** (QA S10 M2, X1, x4, x6), unsealed or read **in memory only**:
every value of `config\.env` read by the canonical parser `jarvis.environment.parse_environment_lines`
(BOM, `export`, quotes, ` #` comments: the value the redactor knows is the value JARVIS loads; a line
the parser refuses is counted, never copied, and does not hide the other lines) that looks like a secret
— any non-trivial value of 6 characters or more of a variable whose name has a word `TOKEN`, `KEY`,
`SECRET`, `PASSWORD`, `PASSWD`, `PWD`, `PASS`, `PASSPHRASE`, `CREDENTIAL(S)`, `COOKIE`, `SIGNATURE`,
`AUTHORIZATION`, `BEARER` (or ends with `TOKEN`, `SECRET`, `PASSWORD`, `APIKEY`…), unless another word
makes it a descriptive setting (`TYPE`, `FILE`, `MAX`, `TIMEOUT`, `HOST`…), so `KEYBOARD_LAYOUT=azerty`,
`BYPASS_HOST=localhost` or `MAX_TOKEN=100000` stay readable; and, by prudence, any other value of 8
characters or more without space that mixes letters and digits or is 20 characters long; the content of
`core.token`; the API keys of the local settings (`control-center-settings.json`: plain in development,
DPAPI-sealed in the product, where the provider keys of `.env` are moved at the first start); and the
credentials of the MCP vault (`mcp_credentials` of `jarvis.sqlite3`, read like the schema versions,
`immutable=1` without a `-shm`). `bundle.json` › `secret_sources` gives only counts per source, and
`degraded` when a sealed value cannot be unsealed (another Windows account, no DPAPI): the bundle is
still written, with that weaker masking said. An opaque token with no recognisable shape is thus masked
wherever a log prints it; then
the canonical secret masking of MCP plugins (`Bearer`, JWT, `Authorization`, cookies, any
`token=` / `api_key:` / `password` pair, credential keys of structured data), bare key shapes
(`sk-…`, `sk-ant-…`, `AIza…`, `ya29.…`, `1//0…`, `ghp_…`, `xox?-…`, Google client secret `GOCSPX-…`
and authorization code `4/0…`, AWS `AKIA…`/`ASIA…`, Stripe `sk_live_…`), the password of any
`scheme://user:password@host` URL, `pwd`, `passphrase`, `private_key`, `aws_secret_access_key`,
`aws_session_token` pairs (QA S10 m2), e-mail addresses → `<email>`,
personal roots → `%LOCALAPPDATA%`, `%APPDATA%`, `%TEMP%`, `%USERPROFILE%`, any other `C:\Users\<name>`
→ `<user>`, the Windows user name → `<user>`; content keys (`text`, `transcript`, `prompt`, `content`…)
are replaced by their length. Every expression is linear: the JWT shape used to rescan a long run of
token characters from each position (2 min 38 s on one log line in the real trial); it now starts
only at the beginning of a run (`test_masking_stays_linear_on_long_runs_of_one_character`).
Known limit: file names written in the free text of a `message` are kept (I-010). **Never included**: the databases, history, memory, `CONTEXT_GLOBAL`,
presentations, artifacts, `control-center-settings.json`, `core.token`, `.env` values. Tested with fake
secrets and fake room speech (`tests/unit/test_support_bundle.py`, `test_diagnostic_redaction.py`) and
in the package smoke. The same redactor bounds the last line of `claude auth status` copied into the
readiness report (I-009 point 5). The bundle is written on the user's PC only; sending it is the user's
act. There is no telemetry backend (out of scope).

## Release gates

Status of the candidate built from a clean clone of `63697cfa` on 2026-10-27, after the QA rework of the Slice
(package `c9fca483…`, installer `47e9fbd4…`, payload `a9337b9d…`, artifact
`jarvis-0.2.0-63697cfa6ffc-47e9fbd4e056`; its `release-info.json` joins 13 green gate reports of that revision
and the green package smoke of that installer; later commits of the Slice change no build input). The
previous candidate (`fa89e894`, package `1621617d…`) is superseded. « Automated » means run on this
Windows 11 workstation, not on a clean machine.

| Id | Gate | Kind | Status |
| --- | --- | --- | --- |
| A1 | static release verifier | automated | green |
| A2 | test gate, `release` suite (product, packaging, installer, edition, confinement, export, migrations, support) | automated | green at `63697cfa`: 29 files, 720 passed, 2 skipped |
| A3 | test gate, `unit` suite (all non-browser tests) | automated | green after the rework: 845 files in 16 parts (some halved), 22 013 passed, 10 listed failures seen, 2 listed intermittents tolerated, 96 skipped |
| A4 | test gate, `browser` suite | automated | **partial**: 19 files by the implementation, 65 by the independent real trial (2026-10-27: one unlisted unstable test found, fixed in the test and passed 5 times in a row alone); the full suite is for the 10 CI shards |
| A5 | package built from a clean clone of a known commit, private runtimes, probe with PATH reduced to Windows | automated | green (`package_sha256` `c9fca483…`); two installers of that package carry the same payload `a9337b9d…`; reproducibility across two machines not proven |
| A6 | installer built from the verified package | automated | green (unsigned); `release_info.py` refuses an installer that embeds another package, another installer than the smoked one, a gate report of another revision, or no gate report |
| A7 | installed-product smoke, 12 steps (above) | automated | green (ports 45653-45656) |
| A8 | update over a seeded older profile, migrations with backups, rollback boundary | automated | green (pytest and package smoke) |
| A9 | forbidden capabilities / PATH fallback regression | automated | green (`verify_release`, release suite) |
| A10 | Remotion renderer crash/recovery in the installed product | automated (unit fault matrix) | partial: not in the package smoke (network install) |
| A11 | export persistence (copy to Documents is not canonical state) | automated | green in the release suite; real OneDrive is HV-EXPORT-02 |
| A12 | the CI workflow on a clean GitHub-hosted Windows runner | automated | **not verified** (written, `actionlint` green, never run) |
| A13 | macOS portability job (`macos`, arm64 + x64): hard gate = platform tests on a real macOS kernel; discovery = neighbour suite, Core smoke, loopback probe ([macos-portability.md](macos-portability.md)) | automated | **not verified** (written, `actionlint` 1.7.12 green, never run). A green job is NOT macOS support |
| — | HV-V12-MAC-01 (real Mac: install, permissions, voice, chat, research, Presentation, stop, update/repair) | physical Human gate | **not verified**; macOS is not a supported platform before it passes (HD-V12-03) |
| — | HV-STORAGE-01, HV-EXPORT-01, HV-EXPORT-02, HV-SECURITY-01, HV-CONNECTORS-01, HV-PACKAGE-01, HV-INSTALL-01, HV-UI-01, HV-EDIT-01..05, HV-RECOVERY-01, HV-UPDATE-01, HV-E2E-01, HV-AUDIO-01, HV-PILOT-01 | physical Human gate | **not verified** (Slice 11 and the Human) |
| — | HV-PACKAGE-02 (Claude Code CLI distribution), -03 (FFmpeg GPL), -04 (openWakeWord), -05 (Picovoice), -06 (AGPL Barehands/visualizer), -07 (legal review of the manifest), -08 (Remotion company licence), -09 (system Chrome/Edge) | external prerequisite: licence | open, safe default applied |
| — | HV-PACKAGE-10 / HV-INSTALL-04 (code signing certificate, installer technology), HV-INSTALL-05 (icon) | external prerequisite: signing | open: the installer is **unsigned** |
| — | HV-INSTALL-02 (CIRCOE Google OAuth client), X1 IGuard contract, Circuit Toolbox tool annotations (I-004 point 6) | external prerequisite: contract | open |
| P1 | spoken wake word technology replaced (openWakeWord models are CC BY-NC-SA 4.0), HD-V12-01 | production blocker | **open**: only the `internal` channel ships it; `production` keeps F9 |
| — | visual replacement in the editor, durable undo, PPTX export, Assistant/Meeting Boards, wake word (F9 instead), screen recording, auto-update, telemetry, macOS/Linux | not delivered in V1 | by decision (handoff, Slices 06/09) |

A missing physical gate is reported as unverified, never assumed passed.

### Voice lifecycle and wake word (v1-2)

Off / Sleep / Active and the launcher's voice gate: [voice-lifecycle.md](voice-lifecycle.md). Physical checks:
HV-V12-VOICE-01 (real microphone), HV-V12-VOICE-02 (« Hey Jarvis » on an installed internal build).

### Build channels and the production blocker (HD-V12-01)

A candidate is built in one of two channels ([windows-packaging.md](windows-packaging.md) › *Channels*):

| Channel | How | Wake word | May be released |
| --- | --- | --- | --- |
| `production` | `build_package.py build` (default) | F9 only; no openWakeWord, no onnxruntime, no model | yes, once the gates above are green |
| `internal` | `build_package.py build --channel internal` (explicit) | « Hey Jarvis » armed in Sleep by default, plus F9; openWakeWord + onnxruntime + the three CC BY-NC-SA 4.0 models shipped and pinned | **no**: internal, non-commercial testing only |

The channel is carried by `runtime-manifest.json` (`product.channel`), the third-party manifest and
`release-info.json` (`product.channel`). An internal identity is named apart
(`jarvis-<version>-internal-<commit 12>-<installer 12>`) and carries `production_blockers` and the
`channel_warning` « Usage interne non commercial ; à remplacer avant production ». `verify` (and the installer,
which shares `verify_package`) refuses a production package that holds any internal component.

**Production blocker P1 (HD-V12-01).** The spoken wake word technology (openWakeWord, whose pre-trained models are
CC BY-NC-SA 4.0, non-commercial) must be **replaced by another technology** before any production release. Until
then, only the `production` channel (keyboard wake, F9) may leave the company; the internal channel exists for
V1.2 internal testing. Closing P1 means: a new engine and its models with a commercial-compatible licence, a policy
entry for it in the production channel, and the removal of the internal-only openWakeWord entries.

## Out of scope / open

- running the pipeline on GitHub (A12) and pinning its actions by commit SHA instead of tag;
- a support bundle button in the readiness window (the command exists; the UI is a frontend change);
- cross-machine reproducibility of the package (same `package_sha256` on two different machines).

# « Signaler un problème » : paquet de diagnostic, rapport, envoi (contract)

V1.2 Slice 07 (`tasks/jarvis-presentation-edition-v1-2/slices/07-bug-report-diagnostic-bundle/`). Extends the support
bundle of `docs/release.md` › *Support bundle* (same service, `jarvis/runtime/support_bundle.py`): the light bundle
of the command line is unchanged; a **problem report** adds, with the user's consent, the masked context that lets
support diagnose a failure without asking the user to hunt files.

| Module | Role |
| --- | --- |
| `jarvis/runtime/support_bundle.py` | collection (`collect_bundle`), `manifest.json`, atomic zip (`write_archive`), retention (`prune_support_folder`), CLI |
| `jarvis/runtime/support_snapshot.py` | full-mode collectors: SQLite snapshot, active Board memory, sanitized settings; `ManifestEntry` |
| `jarvis/runtime/support_report.py` | `report.md`: evidence, AI report (zero-tool model path), factual fallback, grounding check |
| `jarvis/runtime/support_send.py` | destination (`DEFAULT_SUPPORT_EMAIL`), transports (`mapi`, `outbox`, `none`) |
| `jarvis/runtime/support_routes.py` | Control Center service and routes `/api/support/*` (guarded like `/api/product`) |
| `jarvis/runtime/control_center_support_report.js` | the dialog (`window.JarvisSupportReport`) |
| `jarvis/domain/diagnostic_redaction.py` | the masker (now also PEM private-key blocks) |

## User flow

Entry points: **Errors view** (dock `ERR` › « Signaler un problème ») and the **readiness window** footer
(« Signaler un problème »). The dialog shows, before anything is written:

- an optional free description (« Que s'est-il passé ? », masked, 4 000 characters);
- the preview (`GET /api/support/preview`, no side effect): active Board, approximate size before compression,
  included categories (all masked), never-included categories, the destination and what « Envoyer » will do;
- a **consent checkbox**. Without it, « Envoyer » and « Enregistrer… » refuse and say so; the server also refuses
  (`400 support_consent_required`).

Then **Envoyer** (create, then send) or **Enregistrer…** (create, then « Enregistrer dans Documents\Jarvis » or
« Télécharger… », the browser choosing the place). A running act shows its label, a live seconds counter and its
deadline (creation 3 min 30 s, send 50 s); closing the dialog stops nothing. A failure shows the server's sentence
and code (`role="alert"`, « Détails »), logs `[support] support.<key>` in the console, and keeps the bundle: save,
download and retry stay offered. A created bundle is reused for the retry, never rebuilt.

## Bundle content (full mode)

Everything is masked by the bundle's `DiagnosticRedactor` (known secrets first: `.env` values, `core.token`, local
settings keys unsealed in memory, MCP vault credentials; then key shapes, PEM blocks, credential pairs, e-mails,
personal paths, user name).

| Path | Content |
| --- | --- |
| `report.md` | AI report then the factual annex, or the factual report alone (below) |
| `manifest.json` | `jarvis.support-manifest` v1: mode, active Board, report kind and status, totals, one entry per file: `path`, `category`, `status` (`included`, `masked`, `omitted`, `refused`, `excluded`), `bytes`, `reason` |
| `bundle.json`, `logs/*`, `config-keys.json` | the light bundle (`docs/release.md`) |
| `context/description.txt` | the user's description, masked |
| `health/readiness.json` | the readiness report of the Control Center (version, brain, render engine, connectors…), masked |
| `settings/control-center-settings.json` | Control Center settings **without any key**: `*_api_key` fields and the `credentials` list (plain or sealed) are removed, only `credentials_removed` (a count) stays; the rest masked |
| `state/jarvis.sqlite3`, `state/scene.sqlite3` | consistent snapshots (below) |
| `board/board.json`, `board/memory/**` | the active Board (`board_id`, title, kind) and the **text** files of `<data>/boards/<id>/memory/` (summary, documents, missions), masked |

### SQLite snapshots

Source opened **read-only** (`mode=ro` when the `-shm` already exists, otherwise `immutable=1`: nothing is created
next to a base, a lone `-wal` is never replayed, `wal_not_read` is said), copied by the **backup API** in one step
(one read transaction: consistent while Core writes). On the copy only: triggers dropped, virtual tables dropped,
`mcp_credentials` emptied, every BLOB value emptied, every text value masked (a masked value colliding in a
`UNIQUE` column gets its rowid appended, never left clear), then `VACUUM INTO` a new file so no freed page keeps an
old byte. A base over 64 MiB (file + `-wal`) is omitted (`too_large:<bytes>`); an absent or unreadable one too.
The manifest entry carries the counts (`vault_rows_removed`, `triggers_removed`, `text_values_masked`…).

### Confinement

Only `<data>` (resolved root), `<runtime>` and `config\.env` (names and known secrets, in memory) are read. The
Board id must match `[A-Za-z0-9_-]{1,128}`; each of `boards`, `<id>`, `memory` is inspected with `lstat` (a link or
junction is refused, `link_refused`) and the real path must stay under the data root. Inside the memory, a link,
junction or reparse point is **never followed** (`refused`, `link_or_junction_not_followed`); binary or non-UTF-8
files, files over 1 MiB, files past the 16 MiB budget or the 2 000-file limit are omitted with their reason.

### Never included / omitted

`excluded` entries: the MCP credential vault, the local settings keys (plain or sealed), `core.token`, `.env`
values. `omitted` data folders, each with its size: `CONTEXT_GLOBAL`, `sessions` (media), `artifacts`,
`presentations`, `presentation_templates`, global `memory`, `history`, `prefabs`, `local_capabilities` (private
runtimes), `backups`. Other Boards are never read.

## `report.md`

Secondary evidence: the raw files are authoritative. Evidence (`build_evidence`) is read from the bundle's
**already-masked** files only: description `[D]`, product `[P]`, the last 30 errors `[E1]`…`[E30]`, the last 40
trace events `[T…]` (no text), readiness lines not ready `[H:<item>]`, schema versions; bounded at 24 000
characters. The prompt goes through the masker again before leaving.

- **AI report**: the existing zero-tool model path (`memory_extractor_llm.CliTextModel`: Claude CLI, profile
  `speculative_analysis`, `--tools ""`, no MCP, no session, launched in an empty work folder), with the `fast` routing
  model when one is set. The instruction requires fixed sections (Symptôme, Faits observés, Erreur la plus récente,
  Hypothèses, Zone probable, Contexte et reproduction, Identifiants et horodatages, Incertitudes), a reference for
  each fact, « Hypothèse : » plus a confidence for each hypothesis, and no invented error. `unknown_mentions`
  lists, without AI, every dotted or snake_case code and every reference the model cites that is not in the
  evidence; the report shows them under **Attention**. The factual annex always follows.
- **Factual report** (no AI): copies the evidence (description, latest error, last 10 errors, context, ids and
  timestamps) and states that it proposes no cause and why the AI report is missing (`unavailable`, `failed`,
  `timeout` after 120 s, `invalid` answer without the required sections). The bundle is always written.

## Send

Destination (HD-V12-02): `DEFAULT_SUPPORT_EMAIL = "e.debazelaire@circoe.com"` in `support_send.py`, the only
occurrence in the code (tested); `JARVIS_SUPPORT_EMAIL` (product configuration, `config\.env`) replaces it; the
Control Center setting `support_email` (« Modifier » in the dialog, `POST /api/support/destination`, empty = back to
the default) replaces both. An invalid value is ignored.

Transport `JARVIS_SUPPORT_TRANSPORT`:

| Value | Effect |
| --- | --- |
| `mapi` (default on Windows) | Simple MAPI `MAPISendMailW`: a **draft** opens in the user's default mail client with the zip attached, to the destination; the user reviews and sends it from their own mail client. Modeless when the client allows it. No mail client declared (`Software\Clients\Mail`) → `support_mail_client_missing`; refusal → `support_mapi_failed` (MAPI code in `detail`); draft closed → `support_send_cancelled`. If the client has not returned after 30 s, the dialog says to finish in the compose window (`waiting`). |
| `outbox` | **test destination**: copies the zip and a `.eml.txt` into `runtime\support\outbox\`; nothing leaves the PC |
| `none` (default elsewhere, or unknown value) | « Envoyer » refused (`support_send_unconfigured`); save stays |

Why MAPI: it needs no extra secret and carries the attachment; the user's own client sends it, after one more look.
The CIRCOE Mail connector (Circuit Toolbox) classes sending as `destructive`, refused at call time in V1
(`docs/product-connectors.md`), and takes no local attachment. A zip over 20 MiB is not mailed
(`413 support_bundle_too_large`): save it. **A send failure never deletes the zip.** Nothing is sent without the
user's click on « Envoyer » with the consent box checked; there is no automatic upload or telemetry.

## Retention

Bundles live in `<runtime>\support\` (`%LOCALAPPDATA%\CIRCOE\Jarvis\runtime\support\` installed). After each bundle:
keep the 5 newest, delete any older than 30 days (the one just written is always kept), delete `*.zip.tmp` and
`.work-*` leftovers older than one hour. Only these names are touched; `outbox\` and other files never.

## Diagnostics (journal `runtime\trace.jsonl`, errors also in `errors.jsonl`)

`support.report.started`, `.board_unknown` (warning), `.health_unavailable` (warning), `.model_unavailable`
(warning), `.ai_failed` (warning, `code` `support_ai_<status>`), `.omissions` (info: count, reasons),
`.created` (name, bytes, report kind, AI status, cost, duration, pruned), `.failed` (error: `support_folder_unavailable`,
`support_collect_failed`, `support_write_failed`), `.send_started`, `.sent`, `.send_waiting` (warning),
`.send_failed` (error, transport code), `.saved`, `.save_failed` (error), `.downloaded`,
`support.destination.changed`. No message carries a secret, a path or the description.

## How support opens a bundle

1. Unzip anywhere. Read `manifest.json` first: what is there, what was omitted or refused and why.
2. Read `report.md`: facts cite `[E…]` (line of `logs/errors.jsonl`, counted from the oldest of the last 30), `[T…]`,
   `[H:…]`; check any **Attention** list; hypotheses are only hypotheses.
3. `bundle.json`: version, edition, package integrity, schema versions. `health/readiness.json`: readiness lines.
4. Bases: `sqlite3 state/jarvis.sqlite3` (or any SQLite browser): conversations, Boards, missions, jobs; masked
   values read `[secret masqué]`, `<email>`, `%LOCALAPPDATA%`, `<user>`. Triggers are absent in the snapshot.
5. `board/memory/summary.md` and `documents/`: the project state when the problem happened.

Command line: `python -B -m jarvis support-bundle --full [--description "…"] [--out DIR]` writes the same full
bundle with a factual report (no model call).

## Tests

`tests/unit/test_support_report.py` (content, canaries in every zip member and in the prompt, snapshot during
writes, traversal and junction refusal, large and binary files, AI grounding and fallbacks, retention, send success
and failure with the zip kept, save, destination), `test_support_report_js.py`, `test_support_report_browser.py`,
`test_support_bundle.py`, `test_diagnostic_redaction.py`. The real MAPI draft to the real destination is a Human
check (no implementation agent sends mail).

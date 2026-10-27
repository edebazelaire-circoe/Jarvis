# Dossier (contract)

**Canonical page** for the Board's documentary workspace. Handoff
`tasks/jarvis-board-ui-wheel-dossier-refactor/`, Slice 05 (contract, projection
and semantic operations). The full-screen human UI is Slice 07; scene selection
actions (the `Ranger` button) are Slice 06. Both consume this contract and
nothing else. The full-screen UI and its policies are in *Full-screen Dossier
(UI)* below.

| Layer | Module |
| --- | --- |
| pure contract | `jarvis/domain/dossier.py` (entry identity, kinds, scene backing, Ranger Markdown) |
| service (Core) | `jarvis/core/dossier_service.py` (`DossierService`, `core.dossier`) |
| routes (Core) | `jarvis/protocol/workspace_routes.py` (`/v1/workspace/boards/{board_id}/dossier*`) |
| relay (Control Center) | `jarvis/runtime/workspace_relay.py` (`/api/workspace/boards/{board_id}/dossier*`) |
| agent -> UI channel (Control Center) | `jarvis/runtime/dossier_navigation.py` (`/api/dossier/navigation/commands`) |
| MCP | `jarvis-workspace`: `dossier_list`, `dossier_ranger`, `dossier_present`, `dossier_view` ([mcp/tool-contract.md](mcp/tool-contract.md) §10.18) |
| scene reference | `ScenePayload.registry_artifact_id` (`jarvis/domain/scene.py`, [scene-model.md](scene-model.md) › *Dossier references*) |
| tests | `tests/unit/test_dossier_service_api.py`, `test_dossier_mcp.py`, `test_dossier_navigation.py`; Slice 06 consumer: `test_selection_actions_js.py`, `test_selection_actions_browser.py` |

## What the Dossier is

The Dossier is a **projection**, never a store. It shows, as one list of
human-readable entries, two canonical owners of one Board:

- the **Board memory** (`<data_root>/boards/<board_id>/memory/`,
  [boards.md](boards.md) › *Board memory*): free-form files, `summary.md`
  convention (in a Presentation project, the structured project digest:
  [boards.md](boards.md) › *Presentation project digest*; its *Documents
  clés* point to Dossier entries by their memory path);
- the **registry Artifacts linked to the Board** (`board_artifact_links`, v8,
  [artifacts.md](artifacts.md) › *Board links*).

No table, no copy, no index of its own: an entry is a pointer to its owner,
and every read and write goes through that owner (paths, bounds, archive rule,
per-Board lock, activity ledger). **No schema migration** was needed:
`jarvis.sqlite3` stays at v9 and `scene.sqlite3` at v1 (the scene reference
is a JSON payload key, see *Rollback*).

The Board and the Dossier are two views of the same work (D16): the Board is
spatial (scene representations, visible or hidden), the Dossier is durable and
documentary. `SessionContext` stays separate: the Dossier is Board memory, not
a Session's cognitive workspace.

### Vocabulary trap: scene artifact ≠ registry Artifact

| Word | What it is | Lives in |
| --- | --- | --- |
| **scene artifact** | a scene object `kind=artifact` (title, summary, items) explaining finished work ([scene-model.md](scene-model.md) › *Semantic artifacts*) | the scene only (ephemeral) |
| **registry Artifact** | a durable media or derived payload with provenance, id `jart_…` | `artifacts` table ([artifacts.md](artifacts.md)) |
| **representation** | any scene object showing an entry (a window, a capsule, a star) | the scene |
| **entry** | a Dossier item: one memory file or one linked registry Artifact | its owner |

A scene artifact becomes durable only through `Ranger`, which writes its
content **once** into Board memory as Markdown. A representation is never a
document: its identity (`object_id`) is not the entry's identity (`entry_id`).

## Entry

`entry_id` is the stable locator: `memory:<path>` (path relative to `memory/`,
validated by `BoardMemoryPath`) or `artifact:<jart_…>` (`check_artifact_id`).
Anything else is `dossier_entry_invalid` (400).

Default (human) view, one object per entry:

| Field | Meaning |
| --- | --- |
| `entry_id`, `source` | locator; `memory` or `artifact` |
| `kind` | `memory_summary` (`summary.md`), `note` (`.md`, `.markdown`, `.txt`), `document` (other text formats, PDF of a presentation), `image`, `media`, `transcript`, `report` (description, derived), `presentation` (snapshot), `link`, `file` |
| `title` | memory: file stem (`summary.md` -> « Résumé du Board »); a note Ranger wrote (`notes/<slug>-<8 hex>[-<8 hex>].md`) takes its `#` heading, read in the first 1 KiB through `memory_read` (Slice 07, QA S05 polish 1), else the slug without its digest suffix (« Pistes de financement »); Artifact: the given file name, the URL of a link, otherwise a dated French label (« Transcription du 18/10/2026 14:05 ») — never the raw id |
| `open` | `text` (`memory/read`, or the Artifact `text`), `media` (Artifact payload), `link` (URL, never fetched), `none` (a binary memory file: listed, never pretended openable) |
| `modified_at` | memory: file mtime; Artifact: the later of `updated_at` and the link date |
| memory only | `folder`, `path`, `size` |
| research only | `research` (V1.2 Slice 04), for a memory file `documents/research/*.md`: its front-matter is read (2 KiB, up to 16 KiB when longer, page entries only) and the entry takes the `topic` as `title`; `research = {topic, checked_at, volatility, sources, failed_sources}`, or `{problem}` (`no_front_matter`, `unterminated_front_matter`, `front_matter_too_long`, `unreadable` when the read is refused: logged `core.dossier.research_unread`, the list never fails). Not relayed by the MCP `dossier_list` (its output contract is unchanged): agents read the header with `board_memory_read` |
| Artifact only | `preview` (the registry's short preview), `state`, `added_at` (link date), `provenance`: « déposé sur le Board » / « joint dans la conversation » for an upload (its `metadata.provenance`, since a drop links with `origin=active_board`: Slice 07, QA S05 polish 4), otherwise « ajouté au Dossier » for an explicit link, « ajouté automatiquement (Board actif à sa création) » for an automatic one |

`advanced=true` adds an `advanced` object per entry (memory: relative locator;
Artifact: `artifact_id`, `artifact_kind`, `source`, `link_origin`,
`jarvis_session_id`, `context_id`, `mime_type`, `size_bytes`). The default view
never needs raw ids, logs or provenance details (D14). No `human_status`
(draft/validated) is shown: no canonical status exists, none is invented.

## Operations

The UI and the brain call the **same** service through the same Core routes
(the brain through the Control Center relay, `origin: "brain"`). Equal inputs
give equal outcomes and codes.

| # | Operation | Service | Core route (relay: `/api/workspace/…`) | MCP |
| --- | --- | --- | --- | --- |
| 1 | composed list | `list_entries(board_id, *, limit=50, since=None, advanced=False)` | `GET /v1/workspace/boards/{id}/dossier[?limit≤100&since&advanced]` | `dossier_list` (≤ 50) |
| 1 | one entry | `entry(board_id, entry_id, *, advanced=False)` | `GET …/dossier/entry?id=[&advanced]` | used by `dossier_view` |
| 2 | scene -> durable backing | `backing(board_id, object_ids)` | `GET …/dossier/backing?object_id=…` (repeated, ≤ 20) -> `{board_id, board_active, board_code?, board_message?, objects}` | `dossier_ranger dry_run=true` |
| 3 | Ranger | `ranger(board_id, object_ids, *, origin)` | `POST …/dossier/ranger {object_ids, origin?}` | `dossier_ranger` |
| 4 | Afficher sur le Board | `present(board_id, entry_id, *, representation="window", origin)` | `POST …/dossier/present {entry_id, representation?, origin?}` (201 created, 200 reused) | `dossier_present` |
| 5 | open an entry on screen | Control Center broker | `POST /api/dossier/navigation/commands {board_id, entry_id}` | `dossier_view` |

Browse, read and search of the content itself reuse the owners as they are:
`memory/tree|stat|read|search` and `artifact_get` / `/api/artifacts/{id}/payload`.
Edits and corrections reuse `memory/write` (`expected_sha256` for a safe
replace), `memory/move`, `memory/delete`, `artifacts/{id}` link / unlink: the
Dossier adds no second write path. A human edit is therefore the very file the
agents read next (`board_memory_read`, the `board` block's `summary.md`)
(`test_a_human_edit_is_what_the_agent_reads_next`).

### 1. Composed list

Memory files come from `WorkspaceService.memory_tree` (depth 8, ≤ 500 entries,
the same walk as `board_inspect`), linked Artifacts from `links_of_board`
(the 100 most recently linked, each read from the registry). Sort: `summary.md`
first, then most recently modified. `limit` cuts the merged list; `truncated`
is true when the cut, the tree or the link scan stopped early; `total` counts
the merged list. `since` (ISO-8601 with offset) keeps entries modified after it:
this is « what changed », from canonical timestamps only (no read receipt, no
usage invented; the `board.memory.*` / `board.artifact.*` ledger rows remain the
event history). An unreadable memory is said in `sources.memory.error` (code)
and the Artifacts are still listed; a link to a vanished Artifact is counted in
`sources.artifacts.missing`, never listed. Reads write nothing
(`test_list_composes_memory_and_linked_artifacts_once_without_side_effect`).

### 2. Durable backing of a scene object

`classify_scene_object` then the service, per object, in this order:

| Scene object | Backing | Ranger does |
| --- | --- | --- |
| `payload.registry_artifact_id` set | `artifact` (registry Artifact must exist, else `dossier_source_missing`) | link it to the Board if needed (`linked`) or confirm (`confirmed`) |
| `payload.source_path` inside **this** Board's memory | `memory` (file must exist, else `dossier_source_missing`) | confirm |
| `payload.source_path` anywhere else (disk, another Board) | refused `dossier_source_outside_board` | nothing: no host file is ever copied |
| `agent`, `job` (execution), `attention` (signal), `group` | refused `dossier_not_eligible` | nothing |
| prefab window without a reference | refused `dossier_not_eligible` (an interface, not a document) | nothing |
| no title, summary nor item | refused `dossier_nothing_to_keep` | nothing |
| anything else (scene artifact, note window) | `content` | materialize once |
| unknown or archived id | refused `dossier_object_not_found` | nothing |

The preview also says whether Ranger may run at all (Slice 06, QA S05 polish 8):
`board_active` is false when this Board is not the displayed (active) one or is
archived, with `board_code` (`dossier_board_not_active`, `board_archived`) and a
« vous » sentence `board_message`. The per-object `rangeable` is unchanged; a
consumer never shows « rangeable » on it alone. `dossier_ranger dry_run=true`
turns every `rangeable` into `refused` with that code and sentence when the Board
is not displayed.

### 3. Ranger

`Ranger` = durable organization **then** removal of the representation (D15).
`Masquer` is only `visibility = hidden` and never creates an entry
(`test_masquer_never_creates_a_dossier_entry_and_show_hidden_is_visibility_only`);
« Afficher masqués » changes visibility only. Exactly two scene dispositions
exist (hidden is active-not-rendered, archived is out of the snapshot); the
Dossier is a separate dimension, never a third disposition.

1. The Board must be the **active** Board (`dossier_board_not_active` 409:
   the displayed scene is the active Board's) and not archived
   (`board_archived` 409). Whole-request refusals change nothing.
2. Per object (≤ 20, deduplicated), resolve the backing (§2). A refused object
   gets its code and a « vous » sentence (`SENTENCES` in `jarvis/core/dossier_service.py`).
3. Durability first: `artifact_link` (one ledger row), confirm a memory file,
   or **materialize** a `content` object with `memory_write` mode `create` at
   `notes/<slug>-<sha256(object_id)[:8]>.md`: the title as `#` heading, the
   summary (Markdown kept as written), the items as a list, then a footer
   « Rangé depuis le Board le … , par vous|par Jarvis. » and a machine comment
   `<!-- jarvis:dossier object_id=… kind=… category=… origin=… stored_at=… -->`.
   The path is deterministic. When a second Ranger of the same object finds a
   file there (`memory_exists`), it compares that file's **body** (everything
   before the last provenance footer) with the body rendered from what is shown
   now: identical -> `confirmed` (idempotent, no second copy); different (the
   content changed since, same title: after `dossier_changed_meanwhile` or
   `dossier_archive_failed` and an edit) -> it writes, still in mode `create`,
   the body's own path `notes/<slug>-<sha256(object_id)[:8]>-<sha256(body)[:8]>.md`
   (or confirms it if it already holds that body) and only then removes the
   representation. An existing file is never overwritten, and the shown content
   is always durable before it leaves the Board
   (`test_same_title_changed_content_second_ranger_keeps_both_versions`). The
   answer's `entry_id` / `path` name the file that holds the shown content.
   A failed write (`memory_*`, `board_*`) leaves the
   object visible, `status: refused`, `durable: false`, with the owner's code.
   `workspace_ledger_failed` after a write counts as durable (the file exists)
   and is said (`ledger_failed: true`).
4. Removal second: **one** `archive_selection` of the objects whose
   durability is acquired, planned under the scene lock (`apply_if`). A
   materialized object whose payload changed since it was read is left out
   (`dossier_changed_meanwhile`: the stored version is kept, the newer one
   stays on the Board). A refused or failed archive keeps every representation
   (`dossier_archive_failed`, `durable: true`, `archived: false`).
5. Answer (200, per object, in request order): `{object_id, status:
   stored|refused, backing, action: materialized|linked|confirmed|null,
   entry_id, durable, archived, path?|artifact_id?, code?, message?, reason?}`
   plus `stored`, `refused` and the scene `revision` when it advanced.

No step ever destroys the only copy of content. Durable deletion stays
`memory/delete` (explicit, confirmed policy), never Ranger nor a scene archive.

#### Ranger from the wheel (Slice 06)

The Board's « Ranger dans le Dossier » button is the wheel › Sélection row
([scene-selection-batch.md](scene-selection-batch.md) › *Selection actions
(wheel)*): it posts the page selection (≤ 20) to the **active** Board's route
with `origin: "user"`, removes nothing in advance and reports per object —
removed, kept in the Dossier but still on the Board (`dossier_changed_meanwhile`,
`dossier_archive_failed`: said), refused (its `message`, the object stays
selected, followed by the object's precise `reason` when Core gives one, e.g.
« un groupe n'est qu'un cadre : rangez ses objets un par un »; Slice 08). A
registry Artifact this Board did not link yet (a window presented from another
Board) is linked, never moved or copied, and the report says so (« l'Artifact est
désormais aussi dans le Dossier de ce Board »; Slice 08). Its row reads the
backing preview and the displayed Board first.
« Masquer » and « Retirer du Board » never write to the Dossier; « Retirer du
Board » never deletes a durable source either.

## 4. Afficher sur le Board

Resolve the entry (`dossier_entry_not_found` 404 when it is not in this
Dossier: missing file, a folder, an Artifact not linked to this Board), then,
under the scene lock: an active representation of the **same source** (same
`source_path`, case-insensitive, or same `registry_artifact_id`) is reused —
made visible and given the asked representation with one `patch_selection`,
or left untouched when it already is (`revision: null`). Otherwise one
`upsert_object` creates a `window` of category `dossier`:

- memory file: `payload.source_path` = the file's absolute path, so the
  existing file watcher fills and follows the summary ([scene-model.md](scene-model.md)
  › *Windows bound to a file*); nothing is copied by this operation;
- registry Artifact: `payload.registry_artifact_id`, empty summary: the
  page reads the Artifact from the registry (Slice 06: `GET /api/artifacts/{id}`
  with `text_chars=2000`, an image through `/api/artifacts/{id}/payload`, once
  per Artifact and page, journal `scene.registry_view` / `_failed`); the scene
  payload is never rewritten by the page (no page command carries `payload`).

`representation`: `window` (default), `capsule`, `point`. Same active-Board
rule as Ranger. Ranger of a presented representation confirms its source.
The answer's `entry_id` (and the `source_path` of a new window) name the file
**as stored** on disk: `memory:Notes/PLAN.md` on Windows answers
`memory:notes/plan.md` (Slice 07, QA S05 polish 5; `dossier_view` sends the
page the id Core resolved, likewise).

### 5. Agent -> UI navigation

`dossier_view` first resolves the entry with Core (`…/dossier/entry`: a missing
entry never disturbs the screen), then asks the Control Center broker. Transport
of the Variantes explorer and fullscreen channels: one command in flight, an
exclusive long-poll delivery, a single-use receipt carrying the page token,
a deadline (5 s).

| Route | Who | Body / answer |
| --- | --- | --- |
| `GET /api/dossier/navigation/commands?wait_s≤25&page=&visible=0\|1` | page | `{command: null}` or `{command: {id, remaining_ms, action: "open_entry", board_id, entry_id}}` |
| `POST /api/dossier/navigation/commands` | agent | `{board_id, entry_id}` -> 200 `{state: opened\|refused, code, reason, command, board_id, entry_id, id, duration_ms, explanation}` |
| `POST /api/dossier/navigation/commands/{id}` | page, header `X-Jarvis-Page-Token` | `{state: "opened"}` or `{state: "refused", code, reason?}` |

Only a **page receipt** is a 200: `state` is then what the page did,
`opened` or `refused` with the page's code. Every other outcome is an HTTP
refusal, never a 200 (Slice 07, QA S05 polish 7).

Refusals: `no_visible_page` 504 (nobody took it), `command_expired` 504 (taken,
never answered: outcome unknown), `command_busy` 409, `command_cancelled` 503
(Control Center stopping), `bad_page_token` 403, `bad_receipt` 400 to the page
and 502 to the waiting agent at once, `unknown_command_id` 404, `bad_request` /
`dossier_entry_invalid` 400. `/api/dossier` is in `READ_GUARDED_ROUTES`.

**Consumer (Slice 07).** The view `control_center_dossier.js` carries
`__JARVIS_DOSSIER_PAGE_TOKEN__` (the Control Center replaces it once the view is
inserted), and since Slice 08 **holds no long connection**: each visible page
already holds the full-screen and explorer long-polls, the scene leader one more,
and a Dossier long-poll (one per page, then one per Web Locks leader) took the
sixth of Chrome's connections per origin and starved `/api/status` with two
visible windows (median 13 s). The Control Center now says in `/api/status`
whether an order waits (`dossier_navigation: {pending}`, `status_block()` of the
broker); a visible page that reads `pending: true` at its 1 Hz beat takes it with
a short `GET …/commands?wait_s=0&page=…&visible=1`. Delivery stays exclusive: one
page executes it, the others get `{command: null}`. Opening takes one beat plus
one short read (≈ 1 s; the broker waits 5 s). The beat itself keeps one read in
flight and abandons it after 4 s (`STATUS_BEAT`), so a stuck status says
« statut perdu » instead of freezing the page
(`test_dossier_navigation_browser.py`: two visible windows, p90 < 1 s, the order
run once). A hidden page still says `visible=0`. The page
answers **what it did**: `opened` once the Dossier is visible with an
`article[data-entry=…]` of that entry in the DOM (checked, not assumed; the
text may still be loading), or `refused` with `board_not_displayed` (another
Board is displayed), `entry_not_found` (the page's own `…/dossier/entry` read
says 404), `edit_in_progress` (an unsaved edit would be lost: the order would
move the Dossier to another Board, or every one of the 8 tabs holds an unsaved
edit; the draft stays, the Dossier's notice says which entry Jarvis wanted, and
`dossier_view` returns the `ERROR_SENTENCES` sentence so the agent says it
plainly) or `dossier_unavailable` (Variantes covers the screen, the displayed
Board is unknown, a page error; `reason` says which). Several pages may poll
(two tabs): the command goes to one of them, and its receipt is that page's.

## Full-screen Dossier (UI)

Slice 07. Modules `jarvis/runtime/control_center_dossier_core.js` (pure:
routes, organisation, Markdown as data, tabs, outcomes, capabilities, channel
decisions) and `jarvis/runtime/control_center_dossier.js` (view). Shell rules
(rank 55, focus, Escape, layout): [control-center-shell.md](control-center-shell.md)
› *Dossier full-screen view*. Tests: `test_dossier_core_js.py`,
`test_dossier_fullscreen_browser.py`.

### Screen

| Zone | What it shows | Source |
| --- | --- | --- |
| header | « Dossier », Board type chip, Board title, « Archivé · lecture seule » when so; filter field; Contexte; Retour au Board (Échap) | the `board` of the list answer (never the status block) |
| organisation (left) | Vue d'ensemble; collections (Synthèses, Recherches, Notes, Documents, Transcriptions, Images et médias, Liens) with counts; the memory folders as a tree. « Recherches » (V1.2 Slice 04) gathers the entries that carry `research`, whatever their `kind`; their row and header say « Recherche · vérifiée le 27 octobre 2026 · 3 sources (1 non lue) » (`researchLine`), the side panel adds a « Recherche » fact, and an opened document keeps its leading `---` front-matter as a monospace block before the body (its `#` title still becomes the document title) | the list entries only (`kind`, `folder`, `research`) |
| centre | a « Parcourir » tab (overview: `summary.md` excerpt and the 10 most recent; or the chosen section or filter, then « Chercher dans le texte » = `memory/search`) and one tab per opened document (8 at most, the oldest unmodified one leaves) | entries; documents read on demand |
| context (right, collapsible) | En bref (Artifact preview or first paragraph), nature, source, modified, size, provenance; « Jarvis peut lire ce document à la demande… » (no read telemetry exists: nothing is claimed); « Détails techniques » disclosure | the entry; `…/dossier/entry?advanced=true` read only when the disclosure opens; Ranger's machine comment |
| status line | entry count, reading or waiting with a seconds counter, refusals | the reads in flight |

A document renders with reading typography (serif body, sans headings), from
Markdown turned into **data** (`markdownBlocks`: headings, paragraphs, lists,
quotes, code, links opening in a new tab); author HTML stays text. The first
`#` heading becomes the document title (tab and header). Ranger's machine
comment leaves the reading and shows under « Détails techniques ». Long notes
read by 64 KiB chunks (« Lire la suite »). An image Artifact shows its payload
(`/api/artifacts/{id}/payload`, fit or real size); audio and video play the
payload; a PDF opens in a new tab; a link shows its URL (never fetched); a
binary memory file says it is listed, not readable.

### Actions and their canonical path

| Action | Path | Rule |
| --- | --- | --- |
| list, entry, details | `GET …/dossier?limit=100`, `…/dossier/entry?id=[&advanced=true]` | readable on any Board, archived included |
| read | `GET …/memory/read?path&offset&max_bytes=65536`; Artifact `GET /api/artifacts/{id}?text_chars=16000` (the registry's bound) | — |
| search in text | `GET …/memory/search?q=` | from the filter (Entrée) |
| Afficher sur le Board | `POST …/dossier/present {entry_id, representation}` (Fenêtre, Capsule, Étoile) | displayed Board only; 201 « Affiché sur le Board », 200 « Déjà sur le Board : la représentation existante est reprise » |
| Modifier | whole file read first (≤ 256 KiB), then `POST …/memory/write {path, content, mode: replace, expected_sha256}` | memory notes only, never an Artifact; 409 `memory_conflict` keeps the draft, shows the disk version beside it, and the next save is an explicit overwrite with the new sha; a timeout is « issue inconnue » with « Relire » |
| Renommer ou déplacer | `POST …/memory/move {from, to}` | memory only; the tab follows the new id |
| Supprimer du Dossier | `POST …/memory/delete {path}` | the only durable delete; confirmation inside the view (focus on Annuler); disabled during a Variantes run |
| open from outside | wheel, `JarvisDossier.open / openBoard / openEntry`, Ranger toast | the entry is resolved by the service, never assumed |

Writes are refused by the page before the network when the Board is archived,
when the status is lost (« Core ne répond pas » : nothing is written until the
state is read again), or for an Artifact; each disabled action carries its
reason. The client reaches only these routes (`allowed`); anything else is
refused before the network (`forbidden_route`).

### Policies

- **Board switch.** A Dossier following the displayed Board rebinds to the new
  one (tabs closed, list read again; answers of the old Board dropped by a
  generation counter) and says so; a Dossier opened on a precise Board stays.
  An unsaved edit holds the Dossier on the old Board until it is closed. Since
  Slice 08 **every** answer checks the generation (list, document, more text,
  advanced details, open-by-id, present, save, re-read, rename, delete): an
  answer that arrives after a rebind is dropped (`dossier.stale_answer_dropped
  {what}`), never applied to the new Board.
- **Core stopped, Control Center still answering** (Slice 08). The status then
  carries a `boards` block without an active Board and with its `error`: the
  Dossier treats it as « Core ne répond pas » (`dossier.core_lost`, the notice,
  every write and Afficher sur le Board off with that reason, nothing sent),
  not as « ce Board n'est pas le Board affiché ». The next beat that names an
  active Board ends it.
- **Messages and titles.** An earlier message of a document (« Déjà sur le
  Board… ») is not shown while it is being edited or in conflict. A note that
  has been read once is listed by its `#` heading (the list otherwise shows the
  file stem: reading every note's head would cost one read per entry).
- **Links.** A dropped link becomes a clickable `href` only when it is an
  absolute `http(s)` URL (`safeLinkUrl`, defence in depth over `check_link_url`);
  any other scheme is shown as text, `dossier.link_refused`.
- **Unsaved edits are never dropped silently** (QA S07, B1/B2). Every tab whose
  editor differs from the loaded text is `dirty`. A dirty tab is never evicted
  by the 8-tab bound; when all 8 are dirty, opening another entry is refused
  (said in the notice, `edit_in_progress` for Jarvis). Any order that would
  rebind the Dossier to another Board (Jarvis, the wheel, `openBoard`,
  `openEntry`) is refused `edit_in_progress` while an edit is unsaved. Closing the
  Dossier (button, Escape, `JarvisDossier.close()`) asks « Abandonner vos
  modifications ? » whenever **any** tab is dirty, not only the one in front.
- **Jarvis navigation.** `open_entry` opens (or focuses) the entry's tab, marked
  « Jarvis »; two Jarvis openings within 30 s are shown side by side when the
  centre keeps 960 px, else as tabs. Manual and voice navigation share the same
  state (same tabs, same view). The brain is told when to use it
  (`BRAIN_WORKSPACE_PROMPT`: « montre-moi » = `dossier_view`, one call per entry;
  `dossier_present` only on request; a note is read with `board_memory_read`).
- **Escape, focus, narrow screens, layer**: [control-center-shell.md](control-center-shell.md)
  › *Dossier full-screen view*.

## Context and retrieval rule

The Dossier is accessible and searchable on demand (`dossier_list`,
`board_memory_search`, `board_memory_read`, `artifact_get`), **never injected
wholesale** into a turn. The `board` block of every turn keeps its bounded
hydration (manifest ≤ 40 entries, head of `summary.md` ≤ 2 048 bytes,
[boards.md](boards.md) › *Board memory hydration*); a Ranger-materialized note
reaches the brain only as a manifest line until it is read. Board boundaries
are strict: every operation names one Board; a scene `source_path` into another
Board's memory is refused, never merged.

## Archived Board

Readable: list, entry, backing, memory reads. Every write is refused
`board_archived` 409 by the owners (memory, links) and by Ranger / present
before anything else (`test_archived_board_dossier_stays_readable_and_refuses_writes`).
An archived Board is never active, so it can never be the displayed scene.

## Refusal codes

| Code | HTTP | When |
| --- | --- | --- |
| `dossier_entry_invalid` | 400 | malformed `entry_id`, or a path longer than the scene's `source_path` bound |
| `dossier_entry_not_found` | 404 | entry not in this Dossier |
| `dossier_board_not_active` | 409 | Ranger / present on another Board than the active one |
| `scene_unavailable` | 503 | the scene is not served (Ranger, present, backing) |
| `board_not_found` / `board_archived` / `memory_*` / `artifact_*` / `invalid_request` | owners' | unchanged |
| per object: `dossier_object_not_found`, `dossier_not_eligible`, `dossier_nothing_to_keep`, `dossier_source_outside_board`, `dossier_source_missing`, `dossier_changed_meanwhile`, `dossier_archive_failed`, or the owner's code | in the 200 answer | see §2-§3 |

The MCP turns every refusal into `Refus <code> : <phrase vouvoyée> (<source> : <message>)`
(`workspace_boards.ERROR_SENTENCES`); per-object refusals carry their own
`message` sentence.

## Observability

Core diagnostics: `core.dossier.read` and `core.dossier.mutated` (info, the
expected path: operation, board, counts, duration), `core.dossier.ranger_refused`
(warning, per object, code), `core.dossier.archive_failed`,
`core.dossier.memory_unreadable`, `core.dossier.integrity_problem` (warning).
A refused route is journaled by `WorkspaceService.trace_failure`
(`core.workspace.read_failed` / `mutation_failed`; `dossier_ranger` and
`dossier_present` count as mutations). Control Center journal:
`dossier.navigation.requested|delivered|answered|expired|busy|abandoned|receipt_refused|receipt_rejected|write_refused`
(short ids, states, durations, codes; never a title). The ledger rows of a
Ranger are the owners' (`board.memory.written`, `board.artifact.linked`, with
`origin`).

## Rollback

- No DDL, no data migration: an older binary reads both databases.
- **`registry_artifact_id` is refused by an older binary**: `ScenePayload.from_payload`
  checks keys with `check_wire_keys`, so a Core from before this Slice cannot load
  a scene whose active objects carry the key (the scene would be unavailable at
  start), nor read history rows that carry it. Before rolling back, archive the
  representations presented from a registry Artifact (`category = dossier`,
  `scene_get` shows `registry_artifact_id`) with this binary, or clear the key
  (re-present them as memory files). `source_path` windows are unaffected.
- Materialized notes are ordinary Board memory files: they stay readable by any
  version.

## Accepted V1 limits

- One global scene (`docs/boards.md` › *Accepted V1 limits*): Ranger and
  present act on the scene shown with the active Board, hence the active-Board
  rule.
- A memory file shown on the Board follows the file watcher's limits (first
  2 000 characters, Windows notifications).
- The listing reads at most 500 memory entries and the 100 most recently linked
  Artifacts per call (`truncated` says so); no cursor yet.
- The page that takes a navigation command is whichever visible Control Center
  tab polls first: with two visible tabs, Jarvis may open the entry in the other
  one (its receipt is still true). Each `python -m jarvis control-center` start
  opens a browser tab (`webbrowser.open` in `jarvis/app.py`); a sandbox sets
  `BROWSER` to a no-op command so it leaves no poller behind.

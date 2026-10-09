# Presentation source vs Artifacts - parent, snapshot, derivatives, Boards (Level 2 contract, domain Level 3)

Status: **Level 2 contract** with a **Level 3 domain and Core service** (`jarvis/domain/presentation_artifacts.py`, `jarvis/core/presentation_artifacts.py`,
conformance `tests/unit/test_presentation_artifacts*.py`). Written by Remotion Slice 07 (handoff `jarvis-remotion-presentation-integration`).
Entry pages: [presentation-studio.md](presentation-studio.md), [artifacts.md](artifacts.md). Slice 08 wired the service into Core (`v2_app`),
added two read routes and the Board manager display ([Board discoverability](#board-discoverability-slice-08)); Slice 09 builds the snapshot package ([Snapshot package](#snapshot-package-slice-09), live Board references: [presentation-live-refs.md](presentation-live-refs.md)), Slice 16 produces the renders. Nothing here starts Remotion.

## The three things, and who owns each

| Thing | What it is | Owner | Mutable | Artifact? | Board link row? |
| --- | --- | --- | --- | --- | --- |
| **Source** (the logical parent) | the editable `Presentation`: `pst_<32 hex>`, variants, score, art direction, engine | `PresentationStudioService` (Core's one writer), `<data_root>/presentations/` | yes, by revision (CAS) | **never** | **never** |
| **Snapshot** (frozen source) | one variant of one presentation at one pair of revisions, packaged self-contained | `ArtifactService`, kind `presentation_snapshot`, payload `artifacts/<id>/snapshot.zip` | no: terminal once `complete` | yes | yes (automatic + explicit) |
| **Derivative** (render) | MP4, still image or PDF of **one** snapshot | `ArtifactService`, kinds `presentation_video`, `presentation_still`, `presentation_pdf` | no: terminal once `complete` | yes | yes (automatic + explicit) |

Why not make the source an Artifact: an Artifact's acquisition fields freeze at `complete`/`partial`/`failed`
([artifacts.md](artifacts.md)); a source changes on every edit. A mutable Artifact would break the registry's one invariant, and an
Artifact that is re-created on each edit would be a snapshot with a misleading name. The source therefore stays where it is (no file move, no
migration, no forced conversion of existing presentations), and the registry only ever holds **frozen** things. This is the audit recommendation
(P01) applied.

## Identity of the mutable parent

`SourceRef` is the stable, navigable address: `presentation:<pst_id>` or `presentation:<pst_id>/<psv_id>` (`SourceRef.parse` / `str`).

- It never names a revision, so it is valid before and after every edit.
- It never starts with `jart_`, so no code can mistake it for an Artifact id. `WorkspaceService.artifact_link` (which runs `check_artifact_id`
  first) refuses a `pst_` id with `invalid_artifact`; there is no phantom link, by construction and by test.
- It is the only thing a screen keeps to "open the source". Opening is the Studio's existing route; this page adds none.

## Provenance (typed, one copy)

A snapshot's `metadata` (acquisition metadata, frozen with the terminal state) carries **exactly** these keys, written by
`SourceProvenance.to_metadata()` and read back by `SourceProvenance.of_snapshot()` (strict: a missing key, an unknown engine, or an id that
contradicts the keys is `invalid_artifact`, never repaired):

| Key | Meaning |
| --- | --- |
| `source_kind` | `presentation` |
| `source_presentation_id`, `source_variant_id` | the parent and the variant that were frozen |
| `source_presentation_revision`, `source_variant_revision` | the exact revisions (the Studio's `revision` of each document) |
| `source_engine` | `slidecar` or `remotion`, copied from the document (never inferred) |
| `content_sha256` | added by `finalize_snapshot` before the freeze: hash of `snapshot.zip` |

A derivative carries **no** copy of this: `render_format` only. Its provenance is the snapshot it points to through its single
`rendered_from` relation, so source, variant and revision can never disagree between a snapshot and its renders. The chain is
`source -> snapshot -> render`; the first hop is the typed metadata (a source is not an Artifact, so there is no relation row to it), the second is a
registry relation (immutable, cycle-checked, cascade-aware).

### Artifact id of a snapshot

`jart_ps_<32 hex presentation>_<32 hex variant>_p<presentation revision>_v<variant revision>_a<attempt>`: deterministic, so freezing the same
revision twice lands on the same Artifact (replay-safe, never overwritten). A terminal attempt that is not `complete` (`failed`, `partial`) is evidence and
stays; the next call opens `_a2`, and so on, up to 8 (then `artifact_conflict`: fix the cause or delete a failed attempt explicitly).

## Operations (`PresentationArtifacts`, Core)

| Operation | Does | Refuses |
| --- | --- | --- |
| `begin_snapshot(presentation_id, variant_id, expected_presentation_revision, expected_variant_revision)` | reads the live source, requires **both** revisions to match, creates the `pending` snapshot with its typed provenance (payload `snapshot.zip` reserved), returns `{artifact, created}`; the registry links it to the active Board in the same transaction | `presentation_studio_stale_revision` (409, nothing written), `presentation_studio_unknown_presentation`, `presentation_studio_unknown_variant` (archived variants are unknown), `artifact_conflict` after 8 failed attempts |
| `PresentationPackager.freeze` (Slice 09) | the packager: checks the revisions, assembles the package in memory, then `begin_snapshot` -> spool -> `finalize_snapshot` with the real hash ([below](#snapshot-package-slice-09)) | `presentation_studio_stale_revision`, `live_ref_unresolved`, `live_ref_invalid`, `live_ref_cross_presentation`, `snapshot_package_too_large` |
| `finalize_snapshot(artifact_id, content_sha256)` | re-reads the live source; unchanged: **recomputes the SHA-256 of the final `snapshot.zip`** (read through the artifact service, off the loop), compares, stores the hash and finalizes (`complete`, size measured). Source gone (`unknown_presentation`, `unknown_variant`) -> `failed` with `source_missing`; revision moved (`stale_revision`) -> `failed` with `source_stale`; the same typed error is raised | a snapshot that is not `pending` (`artifact_not_pending`), a malformed hash, a hash that does not match the file, or no final file yet (all `invalid_artifact`: the snapshot **stays `pending`**, the caller fixes and calls again, or fails it). Any **other** Studio error (storage, corrupt or unsupported document) propagates unchanged and the snapshot **stays `pending`**: it says nothing about the revision, so it never becomes evidence of staleness |
| `begin_render(snapshot_id, "mp4" \| "still" \| "pdf")` | creates the `pending` derivative with `rendered_from` -> snapshot **in its creation transaction** (payload `render.mp4` / `still.png` / `render.pdf`) | unknown snapshot (`artifact_not_found`: no orphan), not a snapshot or not `complete` (`invalid_relation`), engine of the snapshot without `export` (`presentation_studio_engine_unsupported`: Slidecar), bad format (`presentation_studio_invalid`) |
| `finalize` / `fail` / spool | the existing `ArtifactService` ones, unchanged | - |
| `describe_source(presentation_id)` | `{source_ref, source: {exists: true \| false \| null, title, engine, revision, ...}, snapshots: [{artifact_id, state, variant_id, revisions, engine, content_sha256, created_at, error_code, stale, renders: [{artifact_id, kind, state, format, size_bytes, board_ids}], board_ids, truncated}], board_ids, unreadable, truncated}` | - |
| `boards_of_source(presentation_id)` | `describe_source(...)["board_ids"]` | - |
| `sources_of_board(board_id)` | the Board's presentation Artifacts grouped by source: `{sources: [{source_ref, presentation_id, source, snapshots: [{..., linked_here}]}], unreadable, truncated}` | - |

Reading never fails as a whole because of one bad row, and never lies about being complete:

- **`unreadable`** lists `{artifact_id, kind, code}` for each registry row whose provenance cannot be read (a snapshot without or with contradicting
  `source_*` keys, a render without a `rendered_from` origin). The row is skipped and flagged; the other rows are returned. `describe_source` cannot attribute a
  snapshot with no `source_presentation_id` to any source, so it flags it for every source.
- **`truncated: true`** means something was cut: the registry scan limit, the Board's 200-row page, a snapshot's dependents read at the relation cap
  (256), or a Board-links read at its cap (100; the service asks for one more row to know). `false` means nothing was cut.

Rules worth stating twice:

- **Stale is refused at the two moments it matters** (begin and finalize), with the Studio's existing code. After the freeze, "stale" is only a **display
  fact** (`stale: true` = the live source has moved on): a snapshot never expires, a render of an older snapshot is valid for *that* snapshot.
- **A terminal Artifact is never edited.** Its source moving on never touches it (tests assert byte-equal rows after edits); a re-render or re-freeze
  is a new Artifact. Only `enrichment` stays open, as for every Artifact.
- **Deleting is the registry's own rule**: a snapshot with renders is refused (`artifact_has_dependents`) unless the user explicitly cascades;
  nothing is deleted automatically. Deleting the *source* never deletes snapshots: their lineage stays readable (`source: {"exists": false}`).
- **Artifact kinds are closed (now 11)**: `presentation_snapshot`, `presentation_video`, `presentation_still`, `presentation_pdf` were added with the
  relation kind `rendered_from`; no migration (no SQL `CHECK` on either column, `jarvis.sqlite3` stays v8).

## Which Boards show this? One owner: the Artifact link service (decision)

**Owner: `board_artifact_links`** ([artifacts.md](artifacts.md#board-links)), through `WorkspaceService.artifact_link` / `artifact_unlink` and the
automatic link to the active Board at creation. **`Board.artifact_refs` is not a second owner**: it stays the opaque legacy list ([boards.md](boards.md)); no
presentation id, snapshot id or `SourceRef` is ever written to it (a test scans the code), and no reader of it should be taught about presentations.

Consequences, accepted:

1. A **source never frozen is on no Board.** Freezing (or sharing, or exporting: requirement 7 of the handoff) is the act that creates something a Board can hold. The
   Studio itself is reached from the Studio, not from a Board.
2. A Board shows a **source** as the *group* of its linked snapshots/renders (`sources_of_board`), each group opening the live source through `SourceRef`. The
   grouping is computed on read, so there is no list to keep in sync, nothing to repair after a restart, and nothing to contradict the link table.
3. "Cross-Board" is the existing explicit link: link a snapshot or a render to another Board. `boards_of_source` is the union over the source's artifacts.
4. Unlinking every artifact of a source removes it from that Board; the source and the artifacts are untouched.

Cost, stated: finding a source's snapshots reads the registry's `presentation_snapshot` kind and filters on the typed metadata (`SCAN_PAGE` 200 x
`MAX_SCAN_PAGES` 25, then `truncated: true`). There are few snapshots per installation; if that ever stops being true, add a filtered index through a
versioned migration (CLAUDE.md) - not a second list.

## Board discoverability (Slice 08)

Delivered by Remotion Slice 08 on top of `PresentationArtifacts`; **no storage, no table, no migration** (`jarvis.sqlite3` stays v8).

1. **Composition.** `v2_app` builds `self.presentation_artifacts = PresentationArtifacts(presentation_studio, artifacts, SQLiteBoardArtifactLinks(state))`
   (injected, stateless) and binds it to `WorkspaceService` (`bind_presentations`); `test_v2_architecture` stays green (no concrete adapter is imported
   by the service). Without the binding the routes answer `presentations_unavailable` (503).
2. **Freeze entry point** = `begin_snapshot` (+ package + `finalize_snapshot`); a freeze never asks for a Board: the automatic link to the active
   Board does it. Cross-Board = the existing `POST /v1/workspace/boards/{board_id}/artifacts/{artifact_id}` with a snapshot or render id (a `pst_` id is
   refused `invalid_artifact`: no phantom link).
3. **Two read routes** (no tool: the `jarvis-presentation` and `jarvis-workspace` budgets are untouched; the models already read the artifacts through
   `artifact_search` / `artifact_get`, now with the four kinds):

   | Core route | Relay | Answer |
   | --- | --- | --- |
   | `GET /v1/workspace/boards/{board_id}/presentation-sources` | `/api/workspace/boards/{board_id}/presentation-sources` | `sources_of_board`: `{board_id, sources[], unreadable[], truncated}`; unknown Board `board_not_found` 404; an archived Board is readable |
   | `GET /v1/workspace/presentation-sources/{presentation_id}` | `/api/workspace/presentation-sources/{presentation_id}` | `describe_source` (snapshots, renders, `board_ids`): the reverse navigation; a malformed id `presentation_studio_unknown_presentation` 404, a well-formed absent one `source.exists: false` |

   Each source group: `source_ref`, `presentation_id`, `source` = `{exists: true, title, engine, revision, variant_revisions}` or `{exists: false}` (deleted:
   the lineage stays) or `{exists: null, unreadable: <code>}` (document corrupt or unsupported: flagged, the Board stays readable). Each snapshot:
   `artifact_id`, `state`, `variant_id`, `source_presentation_revision`, `source_variant_revision`, `engine`, `content_sha256`, `created_at`, `error_code`,
   `stale` (`true` the live source moved on, `false` current, `null` unknown because the source is gone or unreadable), `linked_here`, `board_ids`, `renders[]`
   (`artifact_id`, `kind`, `state`, `format`, `size_bytes`, `board_ids`), `truncated`.
4. **Visible states (never hidden, never repaired):** stale (`stale: true`), source deleted (`exists: false`), source unreadable (`exists: null`), a failed or
   partial snapshot (`state` + `error_code`), a snapshot reached only through a linked render (`linked_here: false`), a render not linked to this Board
   (`board_ids` without it), a row without readable provenance (`unreadable[]`), a cut read (`truncated`).
5. **Closed kind lists.** `artifact_search` (`jarvis/runtime/capture_mcp.py`) accepts the four kinds (11 in all, `max_length=11`); the Control Center
   `ARTIFACT_KINDS` labels them « Présentation figée », « Présentation (vidéo) », « Présentation (image) », « Présentation (PDF) » and `rendered_from` reads
   « rendu de » / « a été rendu en ». The workspace and capture routes already filtered by the `ArtifactKind` enum.
6. **Control Center** (Artefacts view, scope Board): « Présentations de « <Board> » » above the list, source → copie figée → rendus ([boards.md](boards.md#control-center-sessions--boards-manager)).
   « Ouvrir la source » / « Ouvrir la variante » call `JarvisStudioExplorer.open({presentation_id, variant_id})` (a `SourceRef`, never an artifact id), close the
   panel only if the explorer accepted, and show every refusal. After a restart everything is read again from the registry and the Studio: nothing is cached in the page.
7. `legacy_artifact_refs` stays labelled legacy; presentations are never added to it (test `test_a_frozen_presentation_never_enters_the_legacy_refs_of_its_board`).

Conformance: `tests/unit/test_presentation_board_discovery.py` (real Core + relay), `tests/unit/test_workspace_presentations_js.py` (the module under node),
`tests/unit/test_presentation_artifacts_docs.py`.

## Snapshot package (Slice 09)

Owner: `PresentationPackager` (`jarvis/core/presentation_snapshot_packager.py`); pure format in `jarvis/domain/presentation_snapshot_package.py`;
live references: [presentation-live-refs.md](presentation-live-refs.md). **No storage, no table, no migration** (`jarvis.sqlite3` stays v8); the package is the
`snapshot.zip` payload the registry already reserves. Not wired into a route or a tool yet (see the residual risks in the handoff LOG).

`snapshot.zip` (deterministic: sorted members, fixed dates, no compression):

| Member | Content |
| --- | --- |
| `manifest.json` | `format` `jarvis.presentation-snapshot/1`, `provenance` (exactly `SourceProvenance.to_metadata()`), `frozen_at`, `scenes` (scene id, pin, every held pin), `prefabs` (per pin: `kind` `remotion` + `source_digest` + `engine` pin {name, version, react_version, lock_sha256}, or `html` + `fingerprint`), `live_refs` (per resolved item: pin, name, original `ref`, mime, size, sha256, member path), `runtime` (what the local capability really installed: `remotion_version`, `react_version`, `lock_sha256`, `compiler_sha256`; `null` when not wired), `files` (sha256 + size of **every** other member), `package_digest` (sha256 of the canonical `files` table) |
| `presentation/{presentation,variant,art_direction,score}.json` | the documents at the frozen revisions (art direction and score only when the variant has them) |
| `prefabs/<prefab_id>/<version>/` | the exact source of each pin: Remotion `src/**`, `public/**`, `source.json` (the manifest block); HTML `bundle.json` (manifest + files; the shared runtime is **not** copied) |
| `prefabs/<prefab_id>/<version>/live/<name><ext>` | the Board item bytes copied at freeze time |

The package holds no machine path, no session id, no URL it must fetch. Reopening (`read_snapshot`) reads the registry payload only: it checks the recorded
`content_sha256` against the file, then every member against the manifest (`read_package`: name rules, duplicates by case, links, encrypted members,
sizes, unlisted or missing members, digest). Any difference is `snapshot_package_invalid`; a package is never repaired.

Freeze order, so nothing partial exists: (1) the live source must have **exactly** the two expected revisions; (2) everything is assembled in memory, each live
reference resolved one last time, and any reference that is not `ok` stops the freeze with `live_ref_unresolved` (details: one row per reference, state and
reason, no path) **before any Artifact exists**; (3) `begin_snapshot` (second revision guard), spool write, `finalize_snapshot` (third guard + real sha256 of the
file). A write error fails the snapshot with `package_failed` (terminal evidence; the next call opens `_a2`). **Replay**: a `complete` snapshot of the same
revisions is returned as is (`replayed: true`, no Board read, no rewrite); a `pending` one whose file already exists is verified and finalized with that very file.
Bounds: 600 members; the **built ZIP** (headers and manifest included, not only the member sizes) is at most 64 MiB and the manifest 2 MiB, so a snapshot can never be
complete yet unreadable; paths up to 12 segments (`prefabs/<id>/<version>/` + Slice 05's maximum source depth of 8, with margin); each live item as in
[presentation-live-refs.md](presentation-live-refs.md#bounds). **Peak memory**: the package is assembled in memory, about twice the package size (members + ZIP),
so up to ~128 MiB for one freeze at the limit; freezes of different presentations may overlap.

Authorisation: `freeze` takes a mandatory `authorised_boards` (default deny, [rule](presentation-live-refs.md#authorisation-default-deny-who-decides-which-board-is-read)) and
returns the Boards actually used; a reference outside it is `live_ref_not_authorised` and no Artifact is created.

Concurrency, resume and failures:

- Two freezes of the same revisions are serialised (lock per snapshot): the second replays the first (4 concurrent calls give one snapshot, one hash).
- A `pending` snapshot whose final file exists is verified (zip, member hashes, **manifest provenance equal to the Artifact's frozen `source_*` metadata**); if it fails, the snapshot
  becomes `failed` (`package_invalid`), is logged (`core.snapshot_packager.resume_rejected`, error) and the next call opens `_a2`. `read_snapshot` applies the same provenance check
  and logs any tampering (`core.snapshot_packager.tampered`, error).
- A leftover `.partial` (a crashed earlier life) is never overwritten or deleted: the spool refuses it, the snapshot becomes `failed` (`package_failed`) with a typed error that
  names no machine path, the `.partial` stays as evidence, the next call opens `_a2`. Any other write error is the same typed `package_failed`.

`presentation/presentation.json` describes only what the frozen variant needs: the presentation document with `variants` reduced to the frozen variant's index entry,
`archived` emptied and `active_variant_id` set to it (`resources` kept). It is a description for provenance, not a loadable multi-variant presentation. The `live_refs[].ref`
strings (`board:<id>/...`) stay in the manifest on purpose: they are the provenance of each copied item, and only authorised Boards can appear there.

Frozen means frozen: editing, moving or deleting the Board item, the Board, or the source afterwards never changes the package (tests assert byte-equal payload and a
successful reopen with the item deleted). Slidecar (HTML) presentations freeze without live references.

Conformance: `tests/unit/test_presentation_live_refs.py` (pure), `tests/unit/test_presentation_freeze.py` (real registry, Board memory, Studio, prefab library).

## Backward compatibility

No existing presentation, Artifact, Board or schema changes. A legacy (Slidecar) presentation can be frozen; it cannot be rendered to MP4/still/PDF
because the capability matrix says `export` is unsupported for Slidecar ([presentation-engine.md](presentation-engine.md)). Older Cores that meet one of
the four new kinds in a database would refuse the row (`artifact_store_unreadable`: closed enum, never repaired or skipped): rolling back to a build without this Slice after freezing is not supported.

## Conformance

`tests/unit/test_presentation_artifacts.py` (service, real SQLite registry and real Studio file store), `tests/unit/test_presentation_freeze.py`, `tests/unit/test_presentation_live_refs.py`, `tests/unit/test_presentation_board_discovery.py`, `tests/unit/test_workspace_presentations_js.py`, `tests/unit/test_presentation_artifacts_docs.py`
(this page against the code and against the entry pages).

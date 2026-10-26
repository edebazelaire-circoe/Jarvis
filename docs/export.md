# Export: internal documents and the explicit user copy (contract)

Canonical contract, documentation **Level 3**: vocabulary, contract, one reusable bounded implementation and conformance
tests. Handoff `tasks/jarvis-presentation-edition-v1/` (Slice 03; decisions D06, D07, D08). Storage: [local-data.md](local-data.md);
final files: [remotion-render.md](remotion-render.md), [presentation-artifacts.md](presentation-artifacts.md),
[artifacts.md](artifacts.md).

| What | Code | Proof |
| --- | --- | --- |
| Exportable classes, file names, collisions, typed errors, result | `jarvis/domain/document_export.py` | `tests/unit/test_document_export.py` |
| Documents folder (Windows known-folder API) | `jarvis/adapters/known_folders.py` | same |
| Export root, destination policy, atomic no-overwrite copy | `jarvis/adapters/export_destination.py` | same (junctions, links, reparse points, forbidden roots) |
| Service (artifact id in, copy out, journal) | `jarvis/core/document_export_service.py`, wired as `core.document_export` (`jarvis/core/v2_app.py`) | `tests/unit/test_document_export_routes.py` (real Core, real registry, fake renderer) |
| Core routes | `jarvis/protocol/export_routes.py` (`GET /v1/exports/root`, `POST /v1/exports`) | same |
| Control Center relay | `jarvis/runtime/export_relay.py` (`GET /api/exports/root`, `POST /api/exports`) | `tests/unit/test_export_relay.py` |
| UI | « Enregistrer dans Documents\Jarvis » after « Exporter la vidéo » (`control_center_presentation_studio_explorer_export.js`) | `tests/unit/test_variants_export_save_js.py` |
| Brain (MCP) | `remotion_export` op `save` (`jarvis/runtime/remotion_mcp.py`, `remotion_mcp_tools.py`), typed client `LocalCoreClient.document_export` | `tests/unit/test_remotion_export_save_mcp.py` |

## Internal vs exported

**Internal** (canonical, under the data root — `%LOCALAPPDATA%\CIRCOE\Jarvis\data` for the installed product,
[local-data.md](local-data.md)): Presentation sources and variants, scene code, prefabs, assets, briefs, drafts, Board
memory, Sessions, `CONTEXT_GLOBAL`, snapshots, every Artifact payload (`<data_root>/artifacts/<id>/`), render work folders and
previews (`<runtime>/render/...`, `local_capabilities/remotion/runtime/render/jobs/`). Jarvis reads and writes only these.

**Exported**: a user-facing COPY of one final file, written to the export root only when the user asks. It is not state:
Jarvis never reads it back, never links to it, never records its absolute path. Deleting, renaming or moving it changes
nothing in Jarvis; exporting again recreates it from the internal Artifact.

Before this contract (inventory of 2026-10-26), no code path wrote a presentation, document or media file outside the data
root and runtime folders: a user got a file only as a stream from the Control Center relay (`GET /api/artifacts/{id}/payload`,
« Ouvrir la vidéo »). That stream stays; this contract adds the explicit copy.

## Classes

V1 exports the three existing final derivatives (`EXPORT_CLASSES`, derived from `presentation_artifacts.RENDERS`):

| Artifact kind | Format | File | MIME |
| --- | --- | --- | --- |
| `presentation_video` | `mp4` | `.mp4` | `video/mp4` |
| `presentation_still` | `still` | `.png` | `image/png` |
| `presentation_pdf` | `pdf` (image-only pages) | `.pdf` | `application/pdf` |

Any other kind (snapshot, screenshot, transcript, ...) is `export_source_not_exportable`: internal state is never exported.
Only a `complete` Artifact whose payload name is its class's is exported. **No PPTX in V1** (no implementation exists; Human
decision required to add one).

## Export root

- **Default**: `<Documents>\Jarvis`. `<Documents>` comes from `SHGetKnownFolderPath(FOLDERID_Documents)` (ctypes,
  `known_folders.documents_folder`): the real folder, moved or redirected (OneDrive, another drive) included, never a guessed
  localized name. Outside Windows (development): `$XDG_DOCUMENTS_DIR` if absolute, else `~/Documents`. An API failure is
  `export_destination_unavailable` with the HRESULT, never a silent fallback.
- **Override**: `JARVIS_EXPORT_ROOT` (absolute) replaces the whole root (tests, sandbox, administration). Its parent must exist.
  Same checks as the default.
- **Never created early**: describing the root (`GET /v1/exports/root`), starting Core, authoring, freezing and rendering
  create nothing; `Jarvis` is created by the first export.
- **Labels, never paths**: answers and journal lines name the root `Documents\Jarvis` (or `JARVIS_EXPORT_ROOT`) and the file
  name, never the user's absolute path.
- **Explicit user-selected destination: not offered in V1.** The Control Center is a browser page with no native folder
  picker; accepting a typed absolute path would be a write-anywhere primitive. Only the root above exists.

## Destination policy

Refused as `export_destination_unsafe`: empty or relative root; `..` anywhere; a drive root (`C:\`, or Documents itself a drive
root); UNC or device paths (`\\server\share`, `//server/share`, `\\?\...`); a base folder whose resolved path differs from its
path (it goes through a link or junction); an export folder that is a symbolic link, a junction or any reparse point, or a
file. **One admitted reparse point**: OneDrive cloud-file folders (`IO_REPARSE_TAG_CLOUD*`, `tag & 0xFFFF0FFF == 0x9000001A`),
which are ordinary folders for the user. A folder-redirected Documents on a network share (UNC) is refused in V1.

Refused as `export_destination_forbidden`: a root equal to, inside, or containing the data root, `CONTEXT_GLOBAL`, the
runtime root, the installed product home `%LOCALAPPDATA%\CIRCOE\Jarvis`, or the program folder (`CODE_ROOT`).

## Names and collisions

- The caller names a source (`artifact_id`), never a path. An optional `file_name` (UI or HTTP only; the brain cannot send one)
  is a stem, sanitized to ONE component (`file_stem`): separators, `..`, Windows-forbidden and control characters become spaces,
  trailing dots and spaces go, reserved names (`CON`, `NUL`, `COM1`, ...) get a `_` prefix, at most 80 characters, empty =
  `Jarvis export`. The extension comes from the class.
- Default name: `<presentation title> - <video|image|pdf>` (title read through `rendered_from` → snapshot → source; unreadable →
  `Jarvis export - <class>`, journalled `core.export.title_unavailable`).
- Collision: never an overwrite. `name.ext`, then `name (2).ext` ... `name (999).ext`; any existing entry (file, folder, link)
  takes a name. All taken: `export_collision_exhausted`. `renamed: true` says a number was added.

## Atomic copy

1. The internal payload path comes from `ArtifactService.payload_files` (validated folder defenses); it must be a plain file
   (not a link).
2. Free space at the root must cover the file plus 64 MiB.
3. A hidden temporary `.<random>.jarvis-export.partial` is created exclusively (`O_EXCL`) INSIDE the export folder; bytes are
   copied by 1 MiB chunks and hashed; `fsync`.
4. Size and SHA-256 are compared with the Artifact record (`size_bytes`, `render_output_sha256`); a mismatch is
   `export_source_unavailable` and nothing is kept.
5. Rename without replacement: `os.rename` on Windows (fails if the target exists), `os.link` + unlink elsewhere. A name taken
   meanwhile moves to the next candidate.
6. Any failure removes the temporary file. The internal payload is only read.

## API

| Method | Core | Control Center relay | Body | Answer |
| --- | --- | --- | --- | --- |
| GET | `/v1/exports/root` | `/api/exports/root` (10 s) | — | `{root: {available, root, exists}}` or `{root: {available: false, root, code, message}}` |
| POST | `/v1/exports` | `/api/exports` (120 s) | `{artifact_id, file_name?, actor?}` | 201 `{export: {artifact_id, format, file_name, destination: {root, display_path}, size_bytes, sha256, exported_at, renamed, copy: true}}` |

Closed keys: any other key (`path`, `source`, `destination`, ...) is `export_invalid`. `actor` is `user` (default) or `brain`,
journal information only; the relay refuses any `actor` other than `user`. Core token required; the relay prefix is in
`READ_GUARDED_ROUTES` (loopback Host and Origin, never cross-site).

## Errors

| Code | HTTP | Meaning |
| --- | --- | --- |
| `export_invalid` | 400 | body, key, query or actor refused |
| `export_source_not_found` | 404 | no such Artifact (an id that looks like a path is just an unknown id) |
| `export_source_not_exportable` | 409 | internal kind, not `complete`, or no payload of its class |
| `export_source_unavailable` | 409 | payload missing, not a plain file, refused folder, or not matching its record |
| `export_destination_unavailable` | 503 | Documents folder not given by the system, or the root's parent is missing |
| `export_destination_unsafe` | 409 | see *Destination policy* |
| `export_destination_forbidden` | 409 | root overlaps internal storage or the program folder |
| `export_collision_exhausted` | 409 | 999 names taken |
| `export_failed` | 500 | disk full, path too long, OS refusal (cause in `message`) |
| `export_unavailable` | 503 | this Core has no export service |

## Journal

`core.export.completed` (info: artifact, actor, format, file name, root label, size, renamed), `core.export.refused`
(warning, code and detail), `core.export.failed` (error), `core.export.title_unavailable` (warning), `core.export.route_failed`
(error, unexpected exception). Relay: `export.request.relayed` (action, status, code; never a body). The UI logs
`[studio-explorer] video_export_save_requested|saved|save_failed`.

## Brain

`remotion_export` gains `op: "save"` with `artifact_id` only (an `jart_…` read with `remotion_status`): the same user gate as
`start` (an addressed user turn and the user's words in `user_request`), no path, folder or name argument in the schema
(`additionalProperties: false`), `actor: brain` sent by the typed client. The Slice 04 capability profile decides whether the
Presentation product brain keeps it; nothing else in the brain can write outside the data root through this contract.

## Not canonical

The export result is returned to the caller and journalled; it is **not** written into the Artifact (no metadata, no
enrichment, no relation). Nothing reads an exported path back. Test: delete the exported file and the export folder, the
presentation still opens and the next export recreates the same bytes (`test_deleting_the_exported_copy_then_exporting_again_...`).

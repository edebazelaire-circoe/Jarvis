# Live Board references of a Remotion scene (Level 2 contract, domain + Core Level 3)

Written by Remotion Slice 09 (handoff `jarvis-remotion-presentation-integration`, decision 7). Code: `jarvis/domain/presentation_live_refs.py` (pure),
`jarvis/core/presentation_live_refs.py` (`LiveRefResolver`), `jarvis/core/presentation_snapshot_packager.py` (`PresentationPackager.scene_live_data`, `freeze`).
Conformance: `tests/unit/test_presentation_live_refs.py`, `tests/unit/test_presentation_freeze.py`. The frozen side is in
[presentation-artifacts.md](presentation-artifacts.md#snapshot-package-slice-09). Isolation model: [remotion-isolation.md](remotion-isolation.md); source layout: [remotion-source.md](remotion-source.md).

## Decision

While editing, a scene refers to Board items by **validated live references**; at freeze/share/export the same references are resolved one last time and the
bytes are **copied** into the self-contained package. Resolution happens only in Core: the scene code is untrusted (no disk, no tool, no secret), so it never
resolves anything itself and only receives resolved *data*. No second resolver and no new store: the Board, Board memory and Artifact owners are read, never written.

## Declaration

A Remotion scene lists its references in its own source, `src/live-refs.json` (a normal declared JSON module, so it travels with the pin and freezes with it; no
Studio schema change). Strict: exactly `{"format": "jarvis.live-refs/1", "refs": [{"name", "ref"}, ...]}`, at most 32 refs, unique names, 16 KiB.
`name` follows the sandbox protocol grammar `[a-z][a-z0-9_]{0,39}`.

## Grammar of a reference

| Form | Reads | Allowed content |
| --- | --- | --- |
| `board:<board_id>/memory/<path>` | a Board memory file | `.txt .md .json .csv`, UTF-8 text |
| `board:<board_id>/artifact/<jart_id>` | a `complete` Artifact **linked to that Board** | kinds `screenshot`, `description`, `derived`, `transcript`, `transcript_segment`; mime `image/png|jpeg|webp|gif` (signature checked), `text/plain|markdown|csv`, `application/json` |

Refused at parse time (`live_ref_invalid`): any other scheme (`file:`, `http:`, a drive path, `/abs`), `..`, a backslash, a drive letter, a Windows device name
(the memory path goes through `BoardMemoryPath`, the id through `check_artifact_id`). `presentation:` and `jart_ps_` ids are `live_ref_cross_presentation`: a presentation
or a snapshot is never a scene item. At resolve time a presentation Artifact (`presentation_*` kinds, any id) is `not_allowed`; SVG, audio and video are `not_allowed`.
A scene can only get the names its own pin declares, in its own presentation variant: an unknown scene, variant of another presentation or name is `live_ref_unknown`.

## Typed states (`LiveRefState`)

`ok` and `changed` carry bytes. `changed` (edit only, when the caller passes the sha256 it last saw) means the item moved on: it is *stale*, shown, not hidden.
The others carry none: `missing` (item or artifact gone, memory absent), `board_missing`, `not_on_board` (artifact exists but is not linked to that Board), `not_ready`
(artifact not `complete`), `not_allowed`, `too_large`, `not_text`, `unreadable` (a store error: reported as `unreadable (ErrorType)` with no path, logged
`core.live_refs.unreadable`). During editing none of them raises: `PresentationPackager.scene_live_data` returns `{refs: [status...], payload}` and the screen shows each state.
Every non-usable resolution is logged `core.live_refs.unresolved` (warning).

## Bounds

Text item 256 KiB, binary item 4 MiB, one set 16 MiB (the item that crosses it is `too_large`). A package: 600 members, 64 MiB. Sandbox message: text inline only up to
24 KiB per item and 48 KiB in total (the protocol's `maxPropsBytes` is 64 KiB); larger text and every binary are announced as `file: "live/<name><ext>"`.

## What crosses into the sandbox

`sandbox_payload(resolved)` is the only thing meant for the `rs:1` `props` message: `{name: {state, message, mime, size, sha256, text | file}}`. It carries no `board:`
reference, no Board id, no artifact id, no path (tests assert it). The host (Slice 10) serves `file` entries under the scene's `public/live/` with the existing sandbox
static route; the protocol is unchanged. The message is built from Core-resolved bytes: the scene cannot ask for another item.

## Freeze

`PresentationPackager.freeze` resolves every declared reference of every held pin; one non-`ok` state stops the freeze with `live_ref_unresolved` before any Artifact is
created (details list name + state, never a path). See [the package](presentation-artifacts.md#snapshot-package-slice-09). After the freeze the package no longer depends on
the Board, the session or any URL: items moved, edited or deleted later do not change it.

## Not here

Wiring `PresentationPackager` into `v2_app`, a route or a tool, the editing UI for references, serving `public/live/` and sending the `props` message (Slice 10), the
render of a snapshot (Slice 16), recording the installed engine into the package at the real wiring point (`runtime` hook, `InstalledEngine.to_dict()`).

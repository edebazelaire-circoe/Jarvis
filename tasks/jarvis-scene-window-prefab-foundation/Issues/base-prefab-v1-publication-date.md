# Shipped base prefabs v1 carry a hand-set publication date.

Found by: Slice 08 (browser proof), confirmed by Slice 09 (2026-10-03). Status: open — cosmetic, immutable.

`jarvis/prefabs/base/{jarvis.window,jarvis.document,jarvis.table}/1/publication.json` say
`"published_at": "2026-10-03T18:00:00Z"`, a fixed time later than their real commits (S05 `e85f6ca`, rework `9e08d44`) and
later than the `jarvis.table` v2 base edit made during the S08 proof — so the library history shows v1 "published
after" v2. `jarvis.checklist/1` carries a real time (`13:42:14Z`). The date is not part of the bundle fingerprint,
but a published version is never rewritten (D-STORE), so v1 stays as is. Follow-up: `scripts/lock_base_prefabs.py`
should stamp the current UTC time (or the commit time) for new base versions, never a constant; the library could
order history by version rather than by date.

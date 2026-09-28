# Live Core journal: stale WAL makes the database read as malformed

- Found: Slice 00 baseline measurement, 2026-09-28.
- `data/state/jarvis.sqlite3` with its 4.1 MB `-wal` fails `PRAGMA integrity_check` ("malformed") and the view stops at 2026-09-21 15:34Z. The main file alone (copied without `-wal`/`-shm`) passes and contains events up to 2026-09-28 12:58Z.
- Risk: any reader applying the WAL (Control Center timeline, testlab, exports) may see truncated or wrong history; a checkpoint could corrupt the main file.
- Not touched by this task (out of scope, runtime state). Human decision: back up the three files, then investigate who writes the WAL while Core is stopped.
- Measurement scripts read a WAL-less copy: `<scratchpad>/baseline/snapshot_dbs.py`.

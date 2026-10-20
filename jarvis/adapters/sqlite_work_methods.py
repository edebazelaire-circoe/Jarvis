"""SQLite adapter of the promoted Work Method versions (schema v11, `work_method_versions`).

Same shape as the other `jarvis.sqlite3` adapters: `data` is the canonical
`WorkMethod.to_payload()`, the other columns are extracted copies checked on
every read (`WorkMethodStoreError`, never repaired). Append-only by triggers;
the primary key `(method_id, version)` turns a second content for one
`id@version` into `work_method_version_conflict`. Contract:
`docs/work-methods.md` › *Promotion*.
"""

from __future__ import annotations

import json
import sqlite3

from jarvis.adapters.sqlite_session_activity import dump_json, utc_key
from jarvis.adapters.sqlite_state import SQLiteStateRepository, immediate_transaction
from jarvis.domain.work_methods import MethodError, MethodOrigin, WorkMethod
from jarvis.ports.work_methods import WorkMethodStoreError, WorkMethodStoreUnavailable

#: Volume humain (une promotion est un acte d'une personne) : au-delà, la lecture le refuse au lieu de tout charger.
MAX_PROMOTED_VERSIONS = 2_000


def _method_row(row: sqlite3.Row) -> WorkMethod:
    key = f"{row['method_id']}@{row['version']}"
    try:
        method = WorkMethod.from_payload(json.loads(row["data"]))
    except (ValueError, TypeError) as exc:
        raise WorkMethodStoreError("work_method_versions", key, f"{type(exc).__name__}: {exc}") from exc
    provenance = method.provenance
    if (method.method_id != row["method_id"] or method.version != row["version"]
            or provenance.origin is not MethodOrigin.PROMOTED or provenance.candidate_id != row["candidate_id"]
            or provenance.promoted_by != row["promoted_by"] or provenance.promoted_at is None
            or utc_key(provenance.promoted_at) != row["promoted_at"]):
        raise WorkMethodStoreError("work_method_versions", key, "key columns disagree with data")
    return method


class SQLiteWorkMethodRepository:
    """`WorkMethodRepository` over the shared state DB (schema v11)."""

    def __init__(self, state: SQLiteStateRepository) -> None:
        self._state = state

    async def promoted_methods(self) -> tuple[WorkMethod, ...]:
        def read(conn: sqlite3.Connection) -> tuple[WorkMethod, ...]:
            rows = conn.execute("SELECT * FROM work_method_versions ORDER BY method_id, version LIMIT ?",
                                (MAX_PROMOTED_VERSIONS + 1,)).fetchall()
            if len(rows) > MAX_PROMOTED_VERSIONS:
                raise WorkMethodStoreError("work_method_versions", "*",
                                           f"more than {MAX_PROMOTED_VERSIONS} promoted versions")
            return tuple(_method_row(row) for row in rows)

        try:
            return await self._state.run_serialized(read)
        except sqlite3.Error as exc:
            raise WorkMethodStoreUnavailable("promoted_methods", f"{type(exc).__name__}: {exc}") from exc

    async def publish(self, method: WorkMethod) -> WorkMethod:
        provenance = method.provenance
        if provenance.origin is not MethodOrigin.PROMOTED or provenance.promoted_at is None:
            raise MethodError("only a promoted version is stored here", code="work_method_invalid")

        def write(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO work_method_versions (method_id, version, candidate_id, promoted_by, promoted_at, data) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (method.method_id, method.version, provenance.candidate_id, provenance.promoted_by,
                 utc_key(provenance.promoted_at), dump_json(method.to_payload())),
            )

        try:
            await self._state.run_serialized(lambda conn: immediate_transaction(conn, write))
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc) or "PRIMARY KEY" in str(exc):
                raise MethodError(f"{method.key} already exists: a published version is never rewritten",
                                  code="work_method_version_conflict") from exc
            raise MethodError(f"work method store refused the write: {exc}", code="work_method_constraint") from exc
        except sqlite3.Error as exc:
            raise WorkMethodStoreUnavailable("publish", f"{type(exc).__name__}: {exc}") from exc
        return method

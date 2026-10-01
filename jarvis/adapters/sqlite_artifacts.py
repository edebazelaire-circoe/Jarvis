"""SQLite adapter of the Artifact registry (handoff session-context-recording, Slice 04).

Port: `jarvis.ports.artifacts.ArtifactRepository`. Contract:
`docs/artifacts.md`. Tables `artifacts` and `artifact_relations` come from
migration v6 of `sqlite_state`; like `sqlite_session_context`, the adapter
shares the state DB connection, lock and worker thread through
`run_serialized`, and every multi-row write is one `immediate_transaction`
that also appends its activity events (`append_activity`).

Guarantees:

- `data` is the Artifact's `to_payload()`; every read decodes it strictly and
  cross-checks the key columns (`ArtifactStoreError`, never skipped or
  repaired);
- an update is a compare-and-swap on the previous row's exact `data`, after
  the domain guard `check_artifact_update` (identity fixed at acquisition,
  terminal states frozen except enrichment);
- a relation names two existing artifacts and never closes a provenance cycle
  (recursive check, `relation_cycle`); adding an existing relation is a no-op;
- deletion follows the documented policy (dependents refused unless
  `cascade`, pending refused, bounded cascade); payload folders are removed by
  the caller **after** this commit;
- any other `sqlite3.Error` is `ArtifactStoreUnavailable`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
import json
import sqlite3
from typing import TypeVar

from jarvis.adapters.sqlite_session_activity import append_activity, dump_json, utc_key
from jarvis.adapters.sqlite_state import SQLiteStateRepository, immediate_transaction
from jarvis.domain.artifacts import (
    MAX_RELATIONS_PER_ARTIFACT, Artifact, ArtifactError, ArtifactErrorCode, ArtifactPage, ArtifactQuery,
    ArtifactRelation, ArtifactRelationKind, ArtifactState, check_artifact_id, check_artifact_update,
    check_relations, decode_artifact_cursor, encode_artifact_cursor,
)
from jarvis.domain.session_activity import ActivityDraft, ActivityEvent, ActivityKind
from jarvis.ports.artifacts import (
    ArtifactStoreError, ArtifactStoreUnavailable, DeletedArtifacts, RelationDirection,
)

T = TypeVar("T")
_TABLE = "artifacts"
#: Une suppression en cascade retire au plus ce nombre d'Artifacts ; au-delà,
#: refus explicite (supprimer par morceaux) plutôt qu'une transaction géante.
MAX_CASCADE_ARTIFACTS = 256
MAX_RELATION_LIMIT = 256


def _artifact_row(row: sqlite3.Row) -> Artifact:
    key = row["artifact_id"]
    try:
        artifact = Artifact.from_payload(json.loads(row["data"]))
    except (ValueError, TypeError) as exc:
        raise ArtifactStoreError(_TABLE, key, f"{type(exc).__name__}: {exc}") from exc
    if (artifact.artifact_id != key or artifact.kind.value != row["kind"] or artifact.state.value != row["state"]
            or artifact.jarvis_session_id != row["jarvis_session_id"] or artifact.context_id != row["context_id"]
            or artifact.payload_ref != row["payload_ref"] or utc_key(artifact.created_at) != row["created_at"]):
        raise ArtifactStoreError(_TABLE, key, "key columns disagree with data")
    return artifact


def _relation_row(row: sqlite3.Row) -> ArtifactRelation:
    try:
        return ArtifactRelation(
            artifact_id=row["artifact_id"], relation=ArtifactRelationKind(row["relation"]),
            origin_artifact_id=row["origin_artifact_id"], created_at=datetime.fromisoformat(row["created_at"]),
        )
    except (ValueError, TypeError) as exc:
        raise ArtifactStoreError("artifact_relations", row["artifact_id"], f"{type(exc).__name__}: {exc}") from exc


def _check_association(conn: sqlite3.Connection, artifact: Artifact) -> None:
    if artifact.jarvis_session_id is not None and conn.execute(
            "SELECT 1 FROM jarvis_sessions WHERE jarvis_session_id=?", (artifact.jarvis_session_id,)).fetchone() is None:
        raise ArtifactError(ArtifactErrorCode.INVALID_ARTIFACT,
                            f"artifact {artifact.artifact_id}: session {artifact.jarvis_session_id} does not exist")
    if artifact.context_id is not None:
        row = conn.execute("SELECT jarvis_session_id FROM session_contexts WHERE context_id=?",
                           (artifact.context_id,)).fetchone()
        if row is None or row[0] != artifact.jarvis_session_id:
            raise ArtifactError(ArtifactErrorCode.INVALID_ARTIFACT,
                                f"artifact {artifact.artifact_id}: context {artifact.context_id} is not a context "
                                f"of session {artifact.jarvis_session_id}")


def _exists(conn: sqlite3.Connection, artifact_id: str) -> bool:
    return conn.execute("SELECT 1 FROM artifacts WHERE artifact_id=?", (artifact_id,)).fetchone() is not None


def _put_relations(conn: sqlite3.Connection, relations: Sequence[ArtifactRelation]) -> None:
    by_subject: dict[str, list[ArtifactRelation]] = {}
    for relation in relations:
        by_subject.setdefault(relation.artifact_id, []).append(relation)
    for subject, items in by_subject.items():
        check_relations(subject, tuple(items))
    for relation in relations:
        for artifact_id in (relation.artifact_id, relation.origin_artifact_id):
            if not _exists(conn, artifact_id):
                raise ArtifactError(ArtifactErrorCode.ARTIFACT_NOT_FOUND,
                                    f"relation names unknown artifact {artifact_id}")
        # Adding subject -> origin closes a cycle iff the subject is already
        # an origin (transitively) of `origin`. UNION deduplicates: terminates.
        cycle = conn.execute(
            "WITH RECURSIVE up(id) AS (SELECT ? UNION SELECT r.origin_artifact_id FROM artifact_relations r "
            "JOIN up ON r.artifact_id = up.id) SELECT 1 FROM up WHERE id = ? LIMIT 1",
            (relation.origin_artifact_id, relation.artifact_id)).fetchone()
        if cycle is not None:
            raise ArtifactError(ArtifactErrorCode.RELATION_CYCLE,
                                f"{relation.artifact_id} {relation.relation.value} {relation.origin_artifact_id} "
                                "would close a provenance cycle")
        conn.execute(
            "INSERT INTO artifact_relations(artifact_id,relation,origin_artifact_id,created_at) VALUES(?,?,?,?) "
            "ON CONFLICT DO NOTHING",
            (relation.artifact_id, relation.relation.value, relation.origin_artifact_id,
             relation.created_at.isoformat()))
        count = conn.execute("SELECT COUNT(*) FROM artifact_relations WHERE artifact_id=?",
                             (relation.artifact_id,)).fetchone()[0]
        if count > MAX_RELATIONS_PER_ARTIFACT:
            raise ArtifactError(ArtifactErrorCode.INVALID_RELATION,
                                f"artifact {relation.artifact_id} has more than {MAX_RELATIONS_PER_ARTIFACT} origins")


class SQLiteArtifactRepository:
    """`ArtifactRepository` over the shared state DB (schema v6)."""

    def __init__(self, state: SQLiteStateRepository) -> None:
        self._state = state

    async def _run(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        try:
            return await self._state.run_serialized(fn)
        except sqlite3.Error as exc:
            operation = getattr(fn, "__qualname__", "operation").split(".<locals>")[0].rsplit(".", 1)[-1]
            raise ArtifactStoreUnavailable(operation, f"{type(exc).__name__}: {exc}") from exc

    async def _transaction(self, write: Callable[[sqlite3.Connection], T]) -> T:
        result: list[T] = []
        await self._run(lambda c: immediate_transaction(c, lambda conn: result.append(write(conn))))
        return result[0]

    # ------------------------------------------------------------ écriture

    async def create_artifact(self, artifact: Artifact, *, relations: Sequence[ArtifactRelation] = (),
                              activity: Sequence[ActivityDraft] = ()) -> tuple[ActivityEvent, ...]:
        if not isinstance(artifact, Artifact):
            raise ArtifactError(ArtifactErrorCode.INVALID_ARTIFACT, "expected an Artifact")
        relations = check_relations(artifact.artifact_id, tuple(relations))

        def write(conn: sqlite3.Connection) -> tuple[ActivityEvent, ...]:
            _check_association(conn, artifact)
            try:
                conn.execute(
                    "INSERT INTO artifacts(artifact_id,kind,state,created_at,updated_at,jarvis_session_id,context_id,"
                    "payload_ref,data) VALUES(?,?,?,?,?,?,?,?,?)",
                    (artifact.artifact_id, artifact.kind.value, artifact.state.value, utc_key(artifact.created_at),
                     utc_key(artifact.updated_at), artifact.jarvis_session_id, artifact.context_id,
                     artifact.payload_ref, dump_json(artifact.to_payload())))
            except sqlite3.IntegrityError as exc:
                raise ArtifactError(ArtifactErrorCode.ARTIFACT_CONFLICT,
                                    f"artifact {artifact.artifact_id} refused by the store: {exc}") from exc
            _put_relations(conn, relations)
            return append_activity(conn, tuple(activity))

        return await self._transaction(write)

    async def update_artifact(self, previous: Artifact, updated: Artifact, *,
                              activity: Sequence[ActivityDraft] = ()) -> tuple[ActivityEvent, ...]:
        check_artifact_update(previous, updated)

        def write(conn: sqlite3.Connection) -> tuple[ActivityEvent, ...]:
            cursor = conn.execute(
                "UPDATE artifacts SET state=?, updated_at=?, data=? WHERE artifact_id=? AND data=?",
                (updated.state.value, utc_key(updated.updated_at), dump_json(updated.to_payload()),
                 previous.artifact_id, dump_json(previous.to_payload())))
            if cursor.rowcount == 0:
                if not _exists(conn, previous.artifact_id):
                    raise ArtifactError(ArtifactErrorCode.ARTIFACT_NOT_FOUND,
                                        f"artifact {previous.artifact_id} does not exist")
                raise ArtifactError(ArtifactErrorCode.ARTIFACT_CONFLICT,
                                    f"artifact {previous.artifact_id} changed since it was read")
            return append_activity(conn, tuple(activity))

        return await self._transaction(write)

    async def add_relations(self, relations: Sequence[ArtifactRelation], *,
                            activity: Sequence[ActivityDraft] = ()) -> tuple[ActivityEvent, ...]:
        relations = tuple(relations)

        def write(conn: sqlite3.Connection) -> tuple[ActivityEvent, ...]:
            _put_relations(conn, relations)
            return append_activity(conn, tuple(activity))

        return await self._transaction(write)

    async def delete_artifact(self, artifact_id: str, *, cascade: bool, now: datetime,
                              origin: str) -> DeletedArtifacts:
        """Explicit user delete. Policy (`docs/artifacts.md` › *Deletion*):

        - an artifact others derive from is refused (`artifact_has_dependents`)
          unless `cascade`: then its dependents (transitively) go with it;
        - a `pending` artifact in the set is refused (`artifact_still_pending`):
          its acquisition must stop first;
        - more than `MAX_CASCADE_ARTIFACTS` is refused, nothing deleted;
        - its own relations to origins are removed; origins stay.
        One `artifact.deleted` event per artifact, same transaction.
        """

        check_artifact_id(artifact_id)

        def write(conn: sqlite3.Connection) -> DeletedArtifacts:
            row = conn.execute("SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
            if row is None:
                raise ArtifactError(ArtifactErrorCode.ARTIFACT_NOT_FOUND, f"artifact {artifact_id} does not exist")
            ids = [r[0] for r in conn.execute(
                "WITH RECURSIVE down(id) AS (SELECT ? UNION SELECT r.artifact_id FROM artifact_relations r "
                "JOIN down ON r.origin_artifact_id = down.id) SELECT id FROM down LIMIT ?",
                (artifact_id, MAX_CASCADE_ARTIFACTS + 1)).fetchall()]
            dependents = [i for i in ids if i != artifact_id]
            if dependents and not cascade:
                raise ArtifactError(ArtifactErrorCode.ARTIFACT_HAS_DEPENDENTS,
                                    f"artifact {artifact_id} has dependents {dependents[:5]}; "
                                    "delete with cascade to remove them too")
            if len(ids) > MAX_CASCADE_ARTIFACTS:
                raise ArtifactError(ArtifactErrorCode.ARTIFACT_HAS_DEPENDENTS,
                                    f"artifact {artifact_id} has more than {MAX_CASCADE_ARTIFACTS - 1} dependents; "
                                    "delete them in parts")
            marks = ",".join("?" * len(ids))
            artifacts = [_artifact_row(r) for r in conn.execute(
                f"SELECT * FROM artifacts WHERE artifact_id IN ({marks})", ids).fetchall()]
            pending = [a.artifact_id for a in artifacts if a.state is ArtifactState.PENDING]
            if pending:
                raise ArtifactError(ArtifactErrorCode.ARTIFACT_STILL_PENDING,
                                    f"artifact {pending[0]} is still being acquired; stop it before deleting")
            conn.execute(f"DELETE FROM artifact_relations WHERE artifact_id IN ({marks})", ids)
            conn.execute(f"DELETE FROM artifacts WHERE artifact_id IN ({marks})", ids)
            order = {i: n for n, i in enumerate(ids)}
            artifacts.sort(key=lambda a: order[a.artifact_id])
            drafts = tuple(ActivityDraft(
                kind=ActivityKind.ARTIFACT_DELETED, occurred_at=now, jarvis_session_id=a.jarvis_session_id,
                context_id=a.context_id, artifact_ids=(a.artifact_id,),
                data={"origin": origin, "artifact_kind": a.kind.value, "cascade_of": artifact_id
                      if a.artifact_id != artifact_id else None}) for a in artifacts)
            return DeletedArtifacts(artifact_ids=tuple(a.artifact_id for a in artifacts),
                                    events=append_activity(conn, drafts))

        return await self._transaction(write)

    # ------------------------------------------------------------ lecture

    async def get_artifact(self, artifact_id: str) -> Artifact | None:
        row = await self._run(lambda c: c.execute(
            "SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)).fetchone())
        return _artifact_row(row) if row else None

    async def query_artifacts(self, query: ArtifactQuery) -> ArtifactPage:
        if not isinstance(query, ArtifactQuery):
            raise ArtifactError(ArtifactErrorCode.INVALID_ARTIFACT, "expected an ArtifactQuery")
        clauses: list[str] = []
        params: list[object] = []
        for column, value in (("jarvis_session_id", query.jarvis_session_id), ("context_id", query.context_id)):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        for column, values in (("kind", query.kinds), ("state", query.states)):
            if values:
                clauses.append(f"{column} IN ({','.join('?' * len(values))})")
                params.extend(v.value for v in values)
        if query.since is not None:
            clauses.append("created_at >= ?")
            params.append(utc_key(query.since))
        if query.until is not None:
            clauses.append("created_at < ?")
            params.append(utc_key(query.until))
        if query.cursor is not None:
            key, last_id = decode_artifact_cursor(query.cursor)
            clauses.append("(created_at < ? OR (created_at = ? AND artifact_id < ?))")
            params.extend((key, key, last_id))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM artifacts {where} ORDER BY created_at DESC, artifact_id DESC LIMIT ?"
        rows = await self._run(lambda c: c.execute(sql, (*params, query.limit + 1)).fetchall())
        items = tuple(_artifact_row(row) for row in rows[:query.limit])
        next_cursor = None
        if len(rows) > query.limit:
            last = rows[query.limit - 1]
            next_cursor = encode_artifact_cursor(last["created_at"], last["artifact_id"])
        return ArtifactPage(items=items, next_cursor=next_cursor)

    async def pending_artifacts(self, *, limit: int) -> Sequence[Artifact]:
        if type(limit) is not int or not 1 <= limit <= MAX_CASCADE_ARTIFACTS:
            raise ArtifactError(ArtifactErrorCode.INVALID_ARTIFACT, f"limit must be in 1..{MAX_CASCADE_ARTIFACTS}")
        rows = await self._run(lambda c: c.execute(
            "SELECT * FROM artifacts WHERE state=? ORDER BY created_at, artifact_id LIMIT ?",
            (ArtifactState.PENDING.value, limit)).fetchall())
        return tuple(_artifact_row(row) for row in rows)

    async def relations_of(self, artifact_id: str, direction: RelationDirection, *,
                           limit: int = MAX_RELATION_LIMIT) -> Sequence[ArtifactRelation]:
        check_artifact_id(artifact_id)
        if type(limit) is not int or not 1 <= limit <= MAX_RELATION_LIMIT:
            raise ArtifactError(ArtifactErrorCode.INVALID_RELATION, f"limit must be in 1..{MAX_RELATION_LIMIT}")
        column = "artifact_id" if RelationDirection(direction) is RelationDirection.ORIGINS else "origin_artifact_id"
        rows = await self._run(lambda c: c.execute(
            f"SELECT * FROM artifact_relations WHERE {column}=? ORDER BY created_at, artifact_id, relation, "
            "origin_artifact_id LIMIT ?", (artifact_id, limit)).fetchall())
        return tuple(_relation_row(row) for row in rows)

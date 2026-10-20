"""SQLite adapter of the durable mission history (handoff organic-agent-orchestration, Slice 03).

Port: `jarvis.ports.mission_history.MissionHistoryRepository`. Contract:
`docs/mission-history.md`. Tables come from migration v10 of `sqlite_state`;
like `sqlite_artifacts`, the adapter shares the state DB connection, lock and
worker thread through `run_serialized`, and every multi-row write is one
`immediate_transaction`.

Guarantees:

- `data` is the domain value's `to_payload()`; every read decodes it strictly
  and cross-checks the key columns (`MissionHistoryStoreError`, never skipped
  or repaired);
- an instance is never ephemeral (D08, also a table CHECK); the same work
  identity recorded twice goes through `missions.reconcile_instance`: identical
  or refused (`immutable_field`), only an empty label is enriched (D01, also a
  trigger);
- a mission opens in the same transaction as the instance that owns it; an
  ownership change needs an explicit handoff relation and appends to
  `mission_owners`;
- a relation, its participants and its handoff packet are written in one
  transaction after `check_relation_participants(..., missions=, relations=)`
  and `check_handoff_chain`; a message after `check_message`, the thread order
  being the insertion order (`seq`);
- the same relation or message submitted twice, identical, is a no-op (replay);
  different, it is refused (`relation_conflict`, `message_conflict`);
- any other `sqlite3.Error` is `MissionHistoryUnavailable`.

No execution status is read or written here: it lives in Core Work State.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from datetime import datetime
import json
import sqlite3
from typing import Any, TypeVar

from jarvis.adapters.sqlite_session_activity import dump_json, utc_key
from jarvis.adapters.sqlite_state import SQLiteStateRepository, immediate_transaction
from jarvis.domain.agent_relations import (
    AgentRelation, AgentRelationKind, HandoffPacket, RelationError, RelationMessage,
    RelationOutcome, check_handoff_chain, check_message, check_relation_participants,
)
from jarvis.domain.mission_history import (
    MAX_MESSAGES_PER_RELATION, MAX_THREAD_PAGE, MAX_TREE_INSTANCES, MAX_TREE_MISSIONS, MAX_TREE_RELATIONS,
    AgentDeclarationFact, MissionHistoryError, MissionTree, OwnershipChange, StoredInstance,
)
from jarvis.domain.missions import (
    MAX_MISSION_DEPTH, AgentInstance, Mission, MissionError, MissionStatus, reconcile_instance, transfer_ownership,
)
from jarvis.ports.mission_history import MissionHistoryStoreError, MissionHistoryUnavailable

T = TypeVar("T")
MAX_LIST_LIMIT = 200


def _decode(table: str, key: str, build: Callable[[Any], T], raw: str) -> T:
    try:
        return build(json.loads(raw))
    except (ValueError, TypeError) as exc:
        raise MissionHistoryStoreError(table, key, f"{type(exc).__name__}: {exc}") from exc


def _opt_key(value: datetime | None) -> str | None:
    return utc_key(value) if value is not None else None


def _instance_row(row: sqlite3.Row) -> StoredInstance:
    key = row["instance_id"]
    instance = _decode("agent_instances", key, AgentInstance.from_payload, row["data"])
    declaration = None
    if row["declaration"] is not None:
        declaration = _decode("agent_instances", key, AgentDeclarationFact.from_payload, row["declaration"])
    if (instance.instance_id != key or instance.work_source != row["work_source"]
            or instance.work_external_id != row["work_external_id"] or instance.role_id != row["role_id"]
            or instance.mission_id != row["mission_id"] or int(instance.mission_owner) != row["mission_owner"]
            or instance.parent_instance_id != row["parent_instance_id"] or instance.ephemeral
            or utc_key(instance.created_at) != row["created_at"]):
        raise MissionHistoryStoreError("agent_instances", key, "key columns disagree with data")
    return StoredInstance(instance, ephemeral_lowered=bool(row["ephemeral_lowered"]), declaration=declaration)


def _mission_row(row: sqlite3.Row) -> Mission:
    key = row["mission_id"]
    mission = _decode("missions", key, Mission.from_payload, row["data"])
    if (mission.mission_id != key or mission.parent_mission_id != row["parent_mission_id"]
            or mission.root_mission_id != row["root_mission_id"] or mission.owner_instance_id != row["owner_instance_id"]
            or mission.status.value != row["status"] or utc_key(mission.created_at) != row["created_at"]
            or _opt_key(mission.closed_at) != row["closed_at"]):
        raise MissionHistoryStoreError("missions", key, "key columns disagree with data")
    return mission


def _relations(conn: sqlite3.Connection, rows: Sequence[sqlite3.Row]) -> list[AgentRelation]:
    """Decode relation rows and cross-check their participants and handoff packet rows."""

    if not rows:
        return []
    ids = [row["relation_id"] for row in rows]
    marks = ",".join("?" * len(ids))
    participants: dict[str, set[tuple[str, str]]] = {key: set() for key in ids}
    for item in conn.execute(f"SELECT relation_id, instance_id, position FROM agent_relation_participants "
                             f"WHERE relation_id IN ({marks})", ids):
        participants[item["relation_id"]].add((item["instance_id"], item["position"]))
    packets = {item["relation_id"]: item for item in conn.execute(
        f"SELECT relation_id, predecessor_instance_id, successor_instance_id, data FROM agent_handoff_packets "
        f"WHERE relation_id IN ({marks})", ids)}
    relations = []
    for row in rows:
        key = row["relation_id"]
        relation = _decode("agent_relations", key, AgentRelation.from_payload, row["data"])
        if (relation.relation_id != key or relation.kind.value != row["kind"] or relation.mission_id != row["mission_id"]
                or relation.status.value != row["status"] or utc_key(relation.created_at) != row["created_at"]
                or _opt_key(relation.closed_at) != row["closed_at"]):
            raise MissionHistoryStoreError("agent_relations", key, "key columns disagree with data")
        if participants[key] != {(p.instance_id, p.position.value) for p in relation.participants}:
            raise MissionHistoryStoreError("agent_relations", key, "participant rows disagree with data")
        packet = packets.get(key)
        if relation.kind is AgentRelationKind.HANDOFF:
            endpoints = relation.endpoints()
            if (packet is None or (packet["predecessor_instance_id"], packet["successor_instance_id"]) != endpoints
                    or _decode("agent_handoff_packets", key, HandoffPacket.from_payload, packet["data"])
                    != relation.handoff):
                raise MissionHistoryStoreError("agent_relations", key, "handoff packet row disagrees with data")
        elif packet is not None:
            raise MissionHistoryStoreError("agent_relations", key, "a packet row belongs to a handoff only")
        relations.append(relation)
    return relations


def _message_row(row: sqlite3.Row) -> RelationMessage:
    key = row["message_id"]
    message = _decode("agent_relation_messages", key, RelationMessage.from_payload, row["data"])
    if (message.message_id != key or message.relation_id != row["relation_id"]
            or message.author_instance_id != row["author_instance_id"] or message.type.value != row["type"]
            or utc_key(message.created_at) != row["created_at"]):
        raise MissionHistoryStoreError("agent_relation_messages", key, "key columns disagree with data")
    return message


def _fetch_instance(conn: sqlite3.Connection, instance_id: str) -> StoredInstance | None:
    row = conn.execute("SELECT * FROM agent_instances WHERE instance_id=?", (instance_id,)).fetchone()
    return _instance_row(row) if row is not None else None


def _fetch_mission(conn: sqlite3.Connection, mission_id: str) -> Mission | None:
    row = conn.execute("SELECT * FROM missions WHERE mission_id=?", (mission_id,)).fetchone()
    return _mission_row(row) if row is not None else None


def _fetch_relation(conn: sqlite3.Connection, relation_id: str) -> AgentRelation | None:
    row = conn.execute("SELECT * FROM agent_relations WHERE relation_id=?", (relation_id,)).fetchone()
    return _relations(conn, [row])[0] if row is not None else None


def _tree_missions(conn: sqlite3.Connection, root_mission_id: str) -> list[Mission]:
    rows = conn.execute("SELECT * FROM missions WHERE root_mission_id=? ORDER BY created_at, mission_id LIMIT ?",
                        (root_mission_id, MAX_TREE_MISSIONS + 1)).fetchall()
    return [_mission_row(row) for row in rows]


def _insert_mission(conn: sqlite3.Connection, mission: Mission) -> None:
    try:
        conn.execute(
            "INSERT INTO missions(mission_id,parent_mission_id,root_mission_id,owner_instance_id,status,created_at,"
            "closed_at,data) VALUES(?,?,?,?,?,?,?,?)",
            (mission.mission_id, mission.parent_mission_id, mission.root_mission_id, mission.owner_instance_id,
             mission.status.value, utc_key(mission.created_at), _opt_key(mission.closed_at),
             dump_json(mission.to_payload())))
    except sqlite3.IntegrityError as exc:
        raise MissionError(f"mission {mission.mission_id} refused by the store: {exc}",
                           code="mission_conflict", field="mission_id") from exc
    conn.execute("INSERT INTO mission_owners(mission_id,owner_instance_id,handoff_relation_id,at) VALUES(?,?,NULL,?)",
                 (mission.mission_id, mission.owner_instance_id, utc_key(mission.created_at)))


def _chain_depth(conn: sqlite3.Connection, table: str, key: str, parent: str, start: str) -> int:
    """Length of the stored parent chain from `start` (itself included), bounded by `MAX_MISSION_DEPTH` + 1."""

    depth, current = 0, start
    while current is not None and depth <= MAX_MISSION_DEPTH:
        row = conn.execute(f"SELECT {parent} FROM {table} WHERE {key}=?", (current,)).fetchone()
        if row is None:
            break
        depth, current = depth + 1, row[0]
    return depth


def _check_new_mission(conn: sqlite3.Connection, mission: Mission) -> None:
    """A sub-mission names a stored parent of the same root, within the depth bound (`missions` rules)."""

    if mission.status.is_closed:
        raise MissionError("a mission is opened open", code="mission_closed", field="status")
    if mission.parent_mission_id is None:
        return
    parent = _fetch_mission(conn, mission.parent_mission_id)
    if parent is None:
        raise MissionError(f"parent mission {mission.parent_mission_id} is missing", code="mission_parent_missing",
                           field="parent_mission_id")
    if parent.status.is_closed:
        raise MissionError(f"parent mission {parent.mission_id} is {parent.status.value}: a closed mission is frozen",
                           code="mission_closed", field="parent_mission_id")
    if parent.root_mission_id != mission.root_mission_id:
        raise MissionError(f"mission {mission.mission_id} declares root {mission.root_mission_id}, its chain ends at "
                           f"{parent.root_mission_id}", field="root_mission_id")
    if _chain_depth(conn, "missions", "mission_id", "parent_mission_id", parent.mission_id) >= MAX_MISSION_DEPTH:
        raise MissionError(f"mission chain deeper than {MAX_MISSION_DEPTH}", code="mission_too_deep",
                           field="parent_mission_id")


class SQLiteMissionHistoryRepository:
    """`MissionHistoryRepository` over the shared state DB (schema v10)."""

    def __init__(self, state: SQLiteStateRepository) -> None:
        self._state = state

    async def _run(self, fn: Callable[[sqlite3.Connection], T], *, operation: str | None = None) -> T:
        try:
            return await self._state.run_serialized(fn)
        except sqlite3.IntegrityError as exc:
            # A constraint the domain checks should have caught: a defect, not an outage.
            raise MissionHistoryError(f"mission history constraint refused the write: {exc}",
                                      code="mission_history_constraint") from exc
        except sqlite3.Error as exc:
            raise MissionHistoryUnavailable(operation or _operation_of(fn), f"{type(exc).__name__}: {exc}") from exc

    async def _transaction(self, write: Callable[[sqlite3.Connection], T]) -> T:
        result: list[T] = []
        # Le nom de l'opération est celui de la méthode qui écrit (`record_instance`...), pas celui de la lambda.
        await self._run(lambda c: immediate_transaction(c, lambda conn: result.append(write(conn))),
                        operation=_operation_of(write))
        return result[0]

    # ------------------------------------------------------------ instances

    async def record_instance(
        self, instance: AgentInstance, *, declaration: AgentDeclarationFact | None = None,
        ephemeral_lowered: bool = False, mission: Mission | None = None,
    ) -> tuple[StoredInstance, bool]:
        if not isinstance(instance, AgentInstance):
            raise MissionError("expected an AgentInstance")
        if instance.ephemeral:
            raise MissionHistoryError(f"instance {instance.instance_id} is ephemeral: history keeps no row for it",
                                      code="ephemeral_not_retained", field="ephemeral")
        if mission is not None and mission.mission_id != instance.mission_id:
            raise MissionError("the mission opened with an instance is that instance's mission", field="mission_id")

        def write(conn: sqlite3.Connection):
            return _write_instance(conn, instance, declaration, ephemeral_lowered, mission)

        return await self._transaction(write)

    async def get_instance(self, instance_id: str) -> StoredInstance | None:
        def read(conn: sqlite3.Connection) -> StoredInstance | None:
            return _fetch_instance(conn, instance_id)

        return await self._run(read)

    async def find_instance(self, work_source: str, work_external_id: str) -> StoredInstance | None:
        def read(conn: sqlite3.Connection) -> StoredInstance | None:
            row = conn.execute("SELECT * FROM agent_instances WHERE work_source=? AND work_external_id=?",
                               (work_source, work_external_id)).fetchone()
            return _instance_row(row) if row is not None else None

        return await self._run(read)

    async def recent_instances(self, *, limit: int = 50) -> tuple[StoredInstance, ...]:
        limit = max(1, min(int(limit), MAX_LIST_LIMIT))

        def read(conn: sqlite3.Connection) -> tuple[StoredInstance, ...]:
            rows = conn.execute("SELECT * FROM agent_instances ORDER BY created_at DESC, instance_id DESC LIMIT ?",
                                (limit,)).fetchall()
            return tuple(_instance_row(row) for row in rows)

        return await self._run(read)

    # ------------------------------------------------------------ missions

    async def close_mission(self, mission_id: str, status: MissionStatus, at: datetime) -> Mission:
        def write(conn: sqlite3.Connection) -> Mission:
            current = _fetch_mission(conn, mission_id)
            if current is None:
                raise MissionError(f"mission {mission_id} is unknown", code="mission_unknown", field="mission_id")
            closed = current.close(status, at)
            if closed != current:
                conn.execute("UPDATE missions SET status=?, closed_at=?, data=? WHERE mission_id=?",
                             (closed.status.value, utc_key(closed.closed_at), dump_json(closed.to_payload()),
                              mission_id))
            return closed

        return await self._transaction(write)

    async def transfer_ownership(self, mission_id: str, successor_instance_id: str, *, handoff_relation_id: str,
                                 at: datetime) -> Mission:
        def write(conn: sqlite3.Connection):
            return _write_transfer(conn, mission_id, successor_instance_id, handoff_relation_id, at)

        return await self._transaction(write)

    async def get_mission(self, mission_id: str) -> Mission | None:
        def read(conn: sqlite3.Connection) -> Mission | None:
            return _fetch_mission(conn, mission_id)

        return await self._run(read)

    async def list_missions(self, *, open_only: bool = False, limit: int = 50) -> tuple[Mission, ...]:
        limit = max(1, min(int(limit), MAX_LIST_LIMIT))

        def read(conn: sqlite3.Connection) -> tuple[Mission, ...]:
            where = "WHERE status='open' " if open_only else ""
            rows = conn.execute(f"SELECT * FROM missions {where}ORDER BY created_at DESC, mission_id DESC LIMIT ?",
                                (limit,)).fetchall()
            return tuple(_mission_row(row) for row in rows)

        return await self._run(read)

    async def open_missions_after(self, after: tuple[datetime, str] | None, *, limit: int) -> tuple[Mission, ...]:
        """Curseur du balayage (Slice 05, reprise QA) : ordre croissant `(created_at, mission_id)`, au plus `limit`."""

        limit = max(1, min(int(limit), MAX_LIST_LIMIT))

        def read(conn: sqlite3.Connection) -> tuple[Mission, ...]:
            if after is None:
                rows = conn.execute("SELECT * FROM missions WHERE status='open' ORDER BY created_at, mission_id "
                                    "LIMIT ?", (limit,)).fetchall()
            else:
                key = utc_key(after[0])
                rows = conn.execute("SELECT * FROM missions WHERE status='open' AND (created_at > ? OR "
                                    "(created_at = ? AND mission_id > ?)) ORDER BY created_at, mission_id LIMIT ?",
                                    (key, key, after[1], limit)).fetchall()
            return tuple(_mission_row(row) for row in rows)

        return await self._run(read)

    async def ownership(self, mission_id: str) -> tuple[OwnershipChange, ...]:
        def read(conn: sqlite3.Connection) -> tuple[OwnershipChange, ...]:
            return tuple(_ownership(conn, [mission_id]))

        return await self._run(read)

    async def mission_tree(self, root_mission_id: str) -> MissionTree | None:
        def read(conn: sqlite3.Connection) -> MissionTree | None:
            start = _fetch_mission(conn, root_mission_id)
            if start is None:
                return None
            root = start.root_mission_id
            missions = _tree_missions(conn, root)
            truncated = len(missions) > MAX_TREE_MISSIONS
            missions = missions[:MAX_TREE_MISSIONS]
            ids = [mission.mission_id for mission in missions]
            marks = ",".join("?" * len(ids))
            rows = conn.execute(f"SELECT * FROM agent_instances WHERE mission_id IN ({marks}) "
                                f"ORDER BY created_at, instance_id LIMIT ?", (*ids, MAX_TREE_INSTANCES + 1)).fetchall()
            truncated = truncated or len(rows) > MAX_TREE_INSTANCES
            instances = tuple(_instance_row(row) for row in rows[:MAX_TREE_INSTANCES])
            rows = conn.execute(f"SELECT * FROM agent_relations WHERE mission_id IN ({marks}) "
                                f"ORDER BY created_at, relation_id LIMIT ?", (*ids, MAX_TREE_RELATIONS + 1)).fetchall()
            truncated = truncated or len(rows) > MAX_TREE_RELATIONS
            relations = tuple(_relations(conn, rows[:MAX_TREE_RELATIONS]))
            return MissionTree(root_mission_id=root, missions=tuple(missions), instances=instances,
                               relations=relations, ownership=tuple(_ownership(conn, ids)), truncated=truncated)

        return await self._run(read)

    # ------------------------------------------------------------ relations

    async def create_relation(self, relation: AgentRelation) -> AgentRelation:
        if not isinstance(relation, AgentRelation):
            raise RelationError("expected an AgentRelation")

        def write(conn: sqlite3.Connection):
            return _write_relation(conn, relation)

        return await self._transaction(write)

    async def close_relation(
        self, relation_id: str, outcome: RelationOutcome, at: datetime, *, summary: str = "",
        winner_instance_id: str | None = None, closed_by: str | None = None,
    ) -> AgentRelation:
        def write(conn: sqlite3.Connection):
            return _write_close(conn, relation_id, outcome, at, summary=summary, winner_instance_id=winner_instance_id, closed_by=closed_by)

        return await self._transaction(write)

    async def record_handoff(
        self, instance: AgentInstance, *, declaration: AgentDeclarationFact | None, relation: AgentRelation,
        at: datetime, summary: str,
    ) -> tuple[StoredInstance, AgentRelation, Mission]:
        """Le successeur d'un relais, sa relation (paquet compris), le transfert de propriété et la clôture
        `transferred`, en **une** transaction (Slice 06) : tout est écrit, ou rien. Un successeur ne peut donc
        jamais être retenu propriétaire sans paquet complet, ni le paquet exister sans successeur."""

        if not isinstance(instance, AgentInstance) or not isinstance(relation, AgentRelation):
            raise MissionError("expected an AgentInstance and an AgentRelation")
        if relation.kind is not AgentRelationKind.HANDOFF or relation.endpoints()[1] != instance.instance_id:
            raise RelationError("the relation is the handoff to this successor", code="handoff_mission_mismatch",
                                field="relation")
        if instance.ephemeral or not instance.mission_owner or instance.mission_id != relation.mission_id:
            raise MissionError("a handoff successor is a non-ephemeral mission owner of the handed-off mission",
                               code="ownership_invalid", field="mission_owner")

        def write(conn: sqlite3.Connection) -> tuple[StoredInstance, AgentRelation, Mission]:
            stored, created = _write_instance(conn, instance, declaration, False, None)
            if not created:
                raise MissionError(f"instance {stored.instance.instance_id} already exists: a handoff goes to a fresh "
                                   "instance", code="handoff_successor_not_fresh", field="instance_id")
            written = _write_relation(conn, relation)
            mission = _write_transfer(conn, relation.mission_id, instance.instance_id, relation.relation_id, at)
            closed = _write_close(conn, relation.relation_id, RelationOutcome.TRANSFERRED, at, summary=summary,
                                  winner_instance_id=None, closed_by=None)
            del written
            return stored, closed, mission

        return await self._transaction(write)

    async def stale_open_relations(self, closed_before: datetime, *, limit: int = 64) -> tuple[AgentRelation, ...]:
        """Relations ouvertes d'une mission close avant `closed_before`, les plus anciennes d'abord."""

        limit = max(1, min(int(limit), MAX_LIST_LIMIT))

        def read(conn: sqlite3.Connection) -> tuple[AgentRelation, ...]:
            rows = conn.execute(
                "SELECT r.* FROM agent_relations r JOIN missions m ON m.mission_id = r.mission_id "
                "WHERE r.status='open' AND m.status<>'open' AND m.closed_at < ? "
                "ORDER BY m.closed_at, r.relation_id LIMIT ?", (utc_key(closed_before), limit)).fetchall()
            return tuple(_relations(conn, rows))

        return await self._run(read)

    async def relations_of_instance(self, instance_id: str, *, limit: int = 16) -> tuple[AgentRelation, ...]:
        """Les relations où figure une instance, les plus récentes d'abord (résumés du contexte du cerveau)."""

        limit = max(1, min(int(limit), MAX_LIST_LIMIT))

        def read(conn: sqlite3.Connection) -> tuple[AgentRelation, ...]:
            rows = conn.execute(
                "SELECT r.* FROM agent_relations r JOIN agent_relation_participants p ON p.relation_id = r.relation_id "
                "WHERE p.instance_id=? ORDER BY r.created_at DESC, r.relation_id DESC LIMIT ?",
                (instance_id, limit)).fetchall()
            return tuple(_relations(conn, rows))

        return await self._run(read)

    async def get_relation(self, relation_id: str) -> AgentRelation | None:
        def read(conn: sqlite3.Connection) -> AgentRelation | None:
            return _fetch_relation(conn, relation_id)

        return await self._run(read)

    async def append_message(self, message: RelationMessage) -> int:
        if not isinstance(message, RelationMessage):
            raise RelationError("expected a RelationMessage")

        def write(conn: sqlite3.Connection) -> int:
            row = conn.execute("SELECT * FROM agent_relation_messages WHERE message_id=?",
                               (message.message_id,)).fetchone()
            if row is not None:
                if _message_row(row) == message:
                    return int(row["seq"])
                raise RelationError(f"message {message.message_id} already exists with other content",
                                    code="message_conflict", field="message_id")
            relation = _fetch_relation(conn, message.relation_id)
            if relation is None:
                raise RelationError(f"relation {message.relation_id} is unknown", code="relation_unknown",
                                    field="relation_id")
            thread: tuple[RelationMessage, ...] | None = None
            if message.reply_to_message_id is not None:
                replied = conn.execute("SELECT * FROM agent_relation_messages WHERE message_id=?",
                                       (message.reply_to_message_id,)).fetchone()
                thread = (_message_row(replied),) if replied is not None else ()
            check_message(relation, message, thread=thread)
            count = conn.execute("SELECT COUNT(*) FROM agent_relation_messages WHERE relation_id=?",
                                 (message.relation_id,)).fetchone()[0]
            if count >= MAX_MESSAGES_PER_RELATION:
                raise RelationError(f"relation {message.relation_id} board holds {MAX_MESSAGES_PER_RELATION} messages: "
                                    "summarise and open a new relation", code="relation_board_full",
                                    field="relation_id")
            cursor = conn.execute(
                "INSERT INTO agent_relation_messages(message_id,relation_id,author_instance_id,type,created_at,data) "
                "VALUES(?,?,?,?,?,?)",
                (message.message_id, message.relation_id, message.author_instance_id, message.type.value,
                 utc_key(message.created_at), dump_json(message.to_payload())))
            return int(cursor.lastrowid)

        return await self._transaction(write)

    async def thread(self, relation_id: str, *, after: int = 0, limit: int = 100
                     ) -> tuple[tuple[int, RelationMessage], ...]:
        limit = max(1, min(int(limit), MAX_THREAD_PAGE))

        def read(conn: sqlite3.Connection) -> tuple[tuple[int, RelationMessage], ...]:
            rows = conn.execute("SELECT * FROM agent_relation_messages WHERE relation_id=? AND seq>? ORDER BY seq "
                                "LIMIT ?", (relation_id, int(after), limit)).fetchall()
            return tuple((int(row["seq"]), _message_row(row)) for row in rows)

        return await self._run(read)

    async def counts(self) -> dict[str, int]:
        def read(conn: sqlite3.Connection) -> dict[str, int]:
            return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in _TABLES}

        return await self._run(read)


def _write_instance(conn: sqlite3.Connection, instance: AgentInstance, declaration: AgentDeclarationFact | None,
                    ephemeral_lowered: bool, mission: Mission | None) -> tuple[StoredInstance, bool]:
    row = conn.execute("SELECT * FROM agent_instances WHERE work_source=? AND work_external_id=?",
                       instance.work_identity).fetchone()
    if row is not None:
        existing = _instance_row(row)
        merged = reconcile_instance(existing.instance, replace(instance, instance_id=existing.instance.instance_id))
        if merged != existing.instance:
            conn.execute("UPDATE agent_instances SET data=? WHERE instance_id=?",
                         (dump_json(merged.to_payload()), merged.instance_id))
        return replace(existing, instance=merged), False
    if instance.parent_instance_id is not None:
        if _fetch_instance(conn, instance.parent_instance_id) is None:
            raise MissionError(f"parent instance {instance.parent_instance_id} is missing",
                               code="mission_parent_missing", field="parent_instance_id")
        if _chain_depth(conn, "agent_instances", "instance_id", "parent_instance_id",
                        instance.parent_instance_id) >= MAX_MISSION_DEPTH:
            raise MissionError(f"agent instance chain deeper than {MAX_MISSION_DEPTH}",
                               code="mission_too_deep", field="parent_instance_id")
    if mission is not None:
        if _fetch_mission(conn, mission.mission_id) is not None:
            raise MissionError(f"mission {mission.mission_id} is already open", code="mission_conflict",
                               field="mission_id")
        if (mission.owner_instance_id != instance.instance_id or not instance.mission_owner):
            raise MissionError(f"mission {mission.mission_id} is opened by its own mission owner instance",
                               code="ownership_invalid", field="owner_instance_id")
        _check_new_mission(conn, mission)
    elif instance.mission_id is not None and _fetch_mission(conn, instance.mission_id) is None:
        raise MissionError(f"mission {instance.mission_id} is unknown: open it with its owner instance",
                           code="mission_unknown", field="mission_id")
    try:
        conn.execute(
            "INSERT INTO agent_instances(instance_id,work_source,work_external_id,role_id,mission_id,"
            "mission_owner,parent_instance_id,ephemeral_lowered,created_at,declaration,data) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (instance.instance_id, instance.work_source, instance.work_external_id, instance.role_id,
             instance.mission_id, int(instance.mission_owner), instance.parent_instance_id,
             int(ephemeral_lowered), utc_key(instance.created_at),
             dump_json(declaration.to_payload()) if declaration is not None else None,
             dump_json(instance.to_payload())))
    except sqlite3.IntegrityError as exc:
        raise MissionError(f"instance {instance.instance_id} refused by the store: {exc}",
                           code="instance_conflict", field="instance_id") from exc
    if mission is not None:
        _insert_mission(conn, mission)
    return StoredInstance(instance, ephemeral_lowered=ephemeral_lowered, declaration=declaration), True


def _write_transfer(conn: sqlite3.Connection, mission_id: str, successor_instance_id: str,
                    handoff_relation_id: str, at: datetime) -> Mission:
    mission = _fetch_mission(conn, mission_id)
    if mission is None:
        raise MissionError(f"mission {mission_id} is unknown", code="mission_unknown", field="mission_id")
    successor = _fetch_instance(conn, successor_instance_id)
    if successor is None:
        raise MissionError(f"instance {successor_instance_id} is unknown", code="ownership_invalid",
                           field="owner_instance_id")
    relation = _fetch_relation(conn, handoff_relation_id)
    if (relation is None or relation.kind is not AgentRelationKind.HANDOFF or relation.mission_id != mission_id
            or relation.outcome is RelationOutcome.WITHDRAWN
            or relation.endpoints() != (mission.owner_instance_id, successor_instance_id)):
        raise MissionError(
            "an ownership change needs a handoff relation of this mission, not withdrawn, from the current "
            f"owner {mission.owner_instance_id} to {successor_instance_id}",
            code="ownership_invalid", field="handoff_ref")
    if at < relation.created_at:
        raise MissionError("an ownership change cannot precede its handoff", code="ownership_invalid",
                           field="at")
    moved = transfer_ownership(mission, successor.instance, handoff_ref=handoff_relation_id)
    conn.execute("UPDATE missions SET owner_instance_id=?, data=? WHERE mission_id=?",
                 (moved.owner_instance_id, dump_json(moved.to_payload()), mission_id))
    conn.execute("INSERT INTO mission_owners(mission_id,owner_instance_id,handoff_relation_id,at) "
                 "VALUES(?,?,?,?)", (mission_id, moved.owner_instance_id, handoff_relation_id, utc_key(at)))
    return moved


def _write_relation(conn: sqlite3.Connection, relation: AgentRelation) -> AgentRelation:
    existing = _fetch_relation(conn, relation.relation_id)
    if existing is not None:
        if existing == relation:
            return existing
        raise RelationError(f"relation {relation.relation_id} already exists with other content",
                            code="relation_conflict", field="relation_id")
    mission = _fetch_mission(conn, relation.mission_id)
    if mission is None:
        raise RelationError(f"mission {relation.mission_id} is missing", code="relation_mission_missing",
                            field="mission_id")
    if mission.status.is_closed:
        raise RelationError(f"mission {relation.mission_id} is closed", code="mission_closed",
                            field="mission_id")
    missions = {item.mission_id: item for item in _tree_missions(conn, mission.root_mission_id)}
    instances = {}
    for instance_id in relation.participant_ids:
        found = _fetch_instance(conn, instance_id)
        if found is not None:
            instances[instance_id] = found.instance
    if relation.created_by_instance_id is not None and _fetch_instance(
            conn, relation.created_by_instance_id) is None:
        raise RelationError(f"creator {relation.created_by_instance_id} is not a known agent instance",
                            code="relation_participant_missing", field="created_by_instance_id")
    rows = conn.execute("SELECT * FROM agent_relations WHERE mission_id=? ORDER BY created_at, relation_id",
                        (relation.mission_id,)).fetchall()
    siblings = _relations(conn, rows)
    check_relation_participants(relation, instances, missions=missions, relations=siblings)
    if relation.kind is AgentRelationKind.HANDOFF:
        check_handoff_chain([*siblings, relation])
    conn.execute(
        "INSERT INTO agent_relations(relation_id,kind,mission_id,status,created_at,closed_at,data) "
        "VALUES(?,?,?,?,?,?,?)",
        (relation.relation_id, relation.kind.value, relation.mission_id, relation.status.value,
         utc_key(relation.created_at), _opt_key(relation.closed_at), dump_json(relation.to_payload())))
    conn.executemany(
        "INSERT INTO agent_relation_participants(relation_id,instance_id,position) VALUES(?,?,?)",
        [(relation.relation_id, p.instance_id, p.position.value) for p in relation.participants])
    if relation.handoff is not None:
        predecessor, successor = relation.endpoints()
        conn.execute(
            "INSERT INTO agent_handoff_packets(relation_id,predecessor_instance_id,successor_instance_id,data) "
            "VALUES(?,?,?,?)", (relation.relation_id, predecessor, successor,
                                dump_json(relation.handoff.to_payload())))
    return relation


def _write_close(conn: sqlite3.Connection, relation_id: str, outcome: RelationOutcome, at: datetime, *,
                 summary: str, winner_instance_id: str | None, closed_by: str | None) -> AgentRelation:
    current = _fetch_relation(conn, relation_id)
    if current is None:
        raise RelationError(f"relation {relation_id} is unknown", code="relation_unknown", field="relation_id")
    closed = current.close(outcome, at, summary=summary, winner_instance_id=winner_instance_id,
                           closed_by=closed_by)
    if closed != current:
        if closed_by is not None and closed_by not in current.participant_ids and _fetch_instance(
                conn, closed_by) is None:
            raise RelationError(f"closed_by {closed_by} is not a known agent instance",
                                code="relation_participant_missing", field="closed_by_instance_id")
        conn.execute("UPDATE agent_relations SET status=?, closed_at=?, data=? WHERE relation_id=?",
                     (closed.status.value, utc_key(closed.closed_at), dump_json(closed.to_payload()),
                      relation_id))
    return closed


def _operation_of(fn: Callable[..., object]) -> str:
    """`SQLiteMissionHistoryRepository.record_instance.<locals>.write` -> `record_instance`."""

    return getattr(fn, "__qualname__", "operation").split(".<locals>")[0].rsplit(".", 1)[-1]


_TABLES = ("missions", "agent_instances", "mission_owners", "agent_relations", "agent_relation_participants",
           "agent_handoff_packets", "agent_relation_messages")


def _ownership(conn: sqlite3.Connection, mission_ids: Iterable[str]) -> list[OwnershipChange]:
    ids = list(mission_ids)
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    rows = conn.execute(f"SELECT * FROM mission_owners WHERE mission_id IN ({marks}) ORDER BY seq", ids).fetchall()
    try:
        return [OwnershipChange(mission_id=row["mission_id"], owner_instance_id=row["owner_instance_id"],
                                at=datetime.fromisoformat(row["at"]), handoff_relation_id=row["handoff_relation_id"])
                for row in rows]
    except (TypeError, ValueError) as exc:
        raise MissionHistoryStoreError("mission_owners", ",".join(ids)[:80], f"{type(exc).__name__}: {exc}") from exc


__all__ = ("SQLiteMissionHistoryRepository",)

"""Registre d'Artifacts et ledger d'activité en SQLite : migration v6, requêtes, relations, suppression, atomicité.

Handoff session-context-recording, Slice 04. Contrat : `docs/artifacts.md`.
Bases temporaires (`tmp_path`) seulement ; jamais une base réelle.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

import pytest

from jarvis.adapters import sqlite_state
from jarvis.adapters.sqlite_artifacts import MAX_CASCADE_ARTIFACTS, SQLiteArtifactRepository
from jarvis.adapters.sqlite_session_activity import SQLiteActivityLedger
from jarvis.adapters.sqlite_session_context import SQLiteContextRepository
from jarvis.adapters.sqlite_state import SQLiteStateRepository, pre_migration_backup_path
from jarvis.adapters.sqlite_workspace_board import SQLiteBoardRepository
from jarvis.domain.artifacts import (
    ArtifactError, ArtifactErrorCode, ArtifactKind, ArtifactQuery, ArtifactRelation, ArtifactRelationKind,
    ArtifactState, enrich_artifact, finalize_artifact, new_artifact,
)
from jarvis.domain.session_activity import ActivityDraft, ActivityError, ActivityKind, ActivityQuery, context_event
from jarvis.domain.session_context import (
    SessionContextError, create_context, dormant_contexts_of_closed_session,
)
from jarvis.domain.workspace_board import SessionEndReason, close_session, default_board, open_session
from jarvis.ports.artifacts import ArtifactStoreError, RelationDirection

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
SID = "jsess_0123456789abcdef"


def t(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def _inspect(path: Path, sql: str, params: tuple = ()):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


@pytest.fixture
def db(tmp_path) -> Path:
    return tmp_path / "state" / "jarvis.sqlite3"


@pytest.fixture
async def stores(db):
    state = SQLiteStateRepository(db)
    await state.initialize()
    try:
        yield (SQLiteBoardRepository(state), SQLiteContextRepository(state), SQLiteArtifactRepository(state),
               SQLiteActivityLedger(state))
    finally:
        await state.close()


async def _session_with_context(boards, contexts):
    board = default_board(now=T0)
    await boards.save_board(board)
    session = open_session(board, now=T0, jarvis_session_id=SID)
    await boards.save_session(session)
    transition = create_context(session, (), now=T0)
    await contexts.commit_contexts(transition.changed)
    return session, transition.active


def art(kind=ArtifactKind.SCREENSHOT, *, now=T0, **kw):  # noqa: ANN001, ANN202
    return new_artifact(kind=kind, source="test", now=now, **kw)


# ------------------------------------------------------------------ migration v5 -> v6


async def test_v5_file_migrates_to_v6_after_a_backup_and_matches_a_fresh_file(db, tmp_path, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(sqlite_state, "_SCHEMA_VERSION", 5)
        state = SQLiteStateRepository(db)
        await state.initialize()
        await state.close()
    assert _inspect(db, "SELECT version FROM schema_version") == [(5,)]
    state = SQLiteStateRepository(db)
    await state.initialize()
    await state.close()
    # v6 puis les versions suivantes (v7, Slice 05) : sauvegarde de la version de départ seulement.
    assert _inspect(db, "SELECT version FROM schema_version") == [(sqlite_state._SCHEMA_VERSION,)]
    assert _inspect(pre_migration_backup_path(db, 5), "SELECT version FROM schema_version") == [(5,)]
    assert _inspect(db, "SELECT COUNT(*) FROM artifacts") == [(0,)]  # aucune ligne produit migrée
    fresh = tmp_path / "fresh" / "jarvis.sqlite3"
    repo = SQLiteStateRepository(fresh)
    await repo.initialize()
    await repo.close()
    schema = "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    assert _inspect(db, schema) == _inspect(fresh, schema)


# ------------------------------------------------------------------ registre


async def test_create_get_and_survive_restart(db):
    state = SQLiteStateRepository(db)
    await state.initialize()
    boards, contexts = SQLiteBoardRepository(state), SQLiteContextRepository(state)
    _session, context = await _session_with_context(boards, contexts)
    artifact = art(ArtifactKind.AUDIO_RECORDING, jarvis_session_id=SID, context_id=context.context_id,
                   payload_name="source.wav", mime_type="audio/wav")
    events = await SQLiteArtifactRepository(state).create_artifact(artifact, activity=(
        ActivityDraft(kind=ActivityKind.ARTIFACT_CREATED, occurred_at=T0, jarvis_session_id=SID,
                      artifact_ids=(artifact.artifact_id,)),))
    assert events[0].seq >= 1
    await state.close()
    state = SQLiteStateRepository(db)  # redémarrage
    await state.initialize()
    try:
        assert await SQLiteArtifactRepository(state).get_artifact(artifact.artifact_id) == artifact
        tail = await SQLiteActivityLedger(state).list(ActivityQuery())
        assert [e.event_id for e in tail] == [events[0].event_id]
    finally:
        await state.close()


async def test_create_refuses_duplicates_unknown_session_and_foreign_context(stores):
    boards, contexts, artifacts, ledger = stores
    _session, context = await _session_with_context(boards, contexts)
    artifact = art()
    await artifacts.create_artifact(artifact)
    with pytest.raises(ArtifactError) as caught:
        await artifacts.create_artifact(artifact)
    assert caught.value.code is ArtifactErrorCode.ARTIFACT_CONFLICT
    with pytest.raises(ArtifactError) as caught:
        await artifacts.create_artifact(art(jarvis_session_id="jsess_unknown"))
    assert caught.value.code is ArtifactErrorCode.INVALID_ARTIFACT
    other = open_session(default_board(now=T0), now=T0, jarvis_session_id="jsess_other")
    with pytest.raises(ArtifactError):
        await artifacts.create_artifact(art(jarvis_session_id=other.jarvis_session_id,
                                            context_id=context.context_id))


async def test_a_refused_create_writes_neither_row_nor_activity(stores):
    _b, _c, artifacts, ledger = stores
    origin = art()
    await artifacts.create_artifact(origin)
    before = await ledger.latest_seq()
    child = art(ArtifactKind.DESCRIPTION)
    bad = ArtifactRelation(child.artifact_id, ArtifactRelationKind.DESCRIBED_FROM, "jart_missing", T0)
    event = ActivityDraft(kind=ActivityKind.ARTIFACT_CREATED, occurred_at=T0, artifact_ids=(child.artifact_id,))
    with pytest.raises(ArtifactError) as caught:
        await artifacts.create_artifact(child, relations=(bad,), activity=(event,))
    assert caught.value.code is ArtifactErrorCode.ARTIFACT_NOT_FOUND
    assert await artifacts.get_artifact(child.artifact_id) is None
    assert await ledger.latest_seq() == before


async def test_update_is_a_compare_and_swap_and_guards_terminal_states(stores):
    _b, _c, artifacts, ledger = stores
    pending = art(payload_name="x.png")
    await artifacts.create_artifact(pending)
    done = finalize_artifact(pending, now=t(1), size_bytes=3)
    await artifacts.update_artifact(pending, done)
    assert (await artifacts.get_artifact(pending.artifact_id)).state is ArtifactState.COMPLETE
    with pytest.raises(ArtifactError) as caught:  # écriture concurrente : `pending` n'est plus la ligne
        await artifacts.update_artifact(pending, finalize_artifact(pending, now=t(2), size_bytes=9))
    assert caught.value.code is ArtifactErrorCode.ARTIFACT_CONFLICT
    with pytest.raises(ArtifactError) as caught:
        await artifacts.update_artifact(done, replace(done, size_bytes=4, updated_at=t(2)))
    assert caught.value.code is ArtifactErrorCode.ARTIFACT_NOT_PENDING
    enriched = enrich_artifact(done, {"description": "un écran"}, now=t(3))
    await artifacts.update_artifact(done, enriched)
    assert (await artifacts.get_artifact(done.artifact_id)).enrichment["description"] == "un écran"
    ghost = art()
    with pytest.raises(ArtifactError) as caught:
        await artifacts.update_artifact(ghost, enrich_artifact(ghost, {"a": 1}, now=t(1)))
    assert caught.value.code is ArtifactErrorCode.ARTIFACT_NOT_FOUND


async def test_query_filters_bounds_and_stable_keyset_pages(stores):
    boards, contexts, artifacts, _ledger = stores
    _s, context = await _session_with_context(boards, contexts)
    made = []
    for i in range(7):
        kind = ArtifactKind.SCREENSHOT if i % 2 else ArtifactKind.AUDIO_RECORDING
        # deux Artifacts au même instant : la page suivante ne doit ni sauter ni répéter
        a = art(kind, now=t(i // 2), jarvis_session_id=SID if i < 5 else None,
                context_id=context.context_id if i < 3 else None)
        await artifacts.create_artifact(a)
        made.append(a)
    expected = sorted(made, key=lambda a: (a.created_at, a.artifact_id), reverse=True)
    seen, cursor = [], None
    while True:
        page = await artifacts.query_artifacts(ArtifactQuery(limit=2, cursor=cursor))
        seen.extend(page.items)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    assert seen == expected
    shots = await artifacts.query_artifacts(ArtifactQuery(kinds=(ArtifactKind.SCREENSHOT,)))
    assert {a.kind for a in shots.items} == {ArtifactKind.SCREENSHOT} and len(shots.items) == 3
    assert len((await artifacts.query_artifacts(ArtifactQuery(jarvis_session_id=SID))).items) == 5
    assert len((await artifacts.query_artifacts(ArtifactQuery(context_id=context.context_id))).items) == 3
    window = await artifacts.query_artifacts(ArtifactQuery(since=t(1), until=t(3)))
    assert all(t(1) <= a.created_at < t(3) for a in window.items) and len(window.items) == 4
    pending = await artifacts.query_artifacts(ArtifactQuery(states=(ArtifactState.COMPLETE,)))
    assert pending.items == ()
    assert len(await artifacts.pending_artifacts(limit=3)) == 3


async def test_a_corrupted_row_is_reported_never_skipped(stores, db):
    _b, _c, artifacts, _l = stores
    a = art()
    await artifacts.create_artifact(a)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE artifacts SET state='complete' WHERE artifact_id=?", (a.artifact_id,))
    conn.commit()
    conn.close()
    with pytest.raises(ArtifactStoreError):
        await artifacts.get_artifact(a.artifact_id)


# ------------------------------------------------------------------ relations


async def test_relations_both_directions_idempotent_and_acyclic(stores):
    _b, _c, artifacts, _l = stores
    audio, transcript, segment, summary = (art(k) for k in (ArtifactKind.AUDIO_RECORDING, ArtifactKind.TRANSCRIPT,
                                                            ArtifactKind.TRANSCRIPT_SEGMENT, ArtifactKind.DERIVED))
    await artifacts.create_artifact(audio)
    await artifacts.create_artifact(transcript, relations=(
        ArtifactRelation(transcript.artifact_id, ArtifactRelationKind.TRANSCRIBED_FROM, audio.artifact_id, T0),))
    seg = (ArtifactRelation(segment.artifact_id, ArtifactRelationKind.TRANSCRIBED_FROM, audio.artifact_id, T0),
           ArtifactRelation(segment.artifact_id, ArtifactRelationKind.SEGMENT_OF, transcript.artifact_id, T0))
    await artifacts.create_artifact(segment, relations=seg)
    await artifacts.create_artifact(summary, relations=(
        ArtifactRelation(summary.artifact_id, ArtifactRelationKind.DERIVED_FROM, segment.artifact_id, T0),))
    await artifacts.add_relations(seg)  # idempotent
    origins = await artifacts.relations_of(segment.artifact_id, RelationDirection.ORIGINS)
    assert {(r.relation, r.origin_artifact_id) for r in origins} == {
        (ArtifactRelationKind.TRANSCRIBED_FROM, audio.artifact_id),
        (ArtifactRelationKind.SEGMENT_OF, transcript.artifact_id)}
    dependents = await artifacts.relations_of(audio.artifact_id, RelationDirection.DEPENDENTS)
    assert {r.artifact_id for r in dependents} == {transcript.artifact_id, segment.artifact_id}
    for relation in (ArtifactRelationKind.DERIVED_FROM, ArtifactRelationKind.TRANSCRIBED_FROM):
        with pytest.raises(ArtifactError) as caught:  # audio <- ... <- summary : summary ne peut pas être son origine
            await artifacts.add_relations((ArtifactRelation(audio.artifact_id, relation, summary.artifact_id, T0),))
        assert caught.value.code is ArtifactErrorCode.RELATION_CYCLE


# ------------------------------------------------------------------ suppression


async def _chain(artifacts):
    audio, transcript, summary = art(ArtifactKind.AUDIO_RECORDING), art(ArtifactKind.TRANSCRIPT), art(
        ArtifactKind.DERIVED)
    for a in (audio, transcript, summary):
        await artifacts.create_artifact(a)
    await artifacts.add_relations((
        ArtifactRelation(transcript.artifact_id, ArtifactRelationKind.TRANSCRIBED_FROM, audio.artifact_id, T0),
        ArtifactRelation(summary.artifact_id, ArtifactRelationKind.DERIVED_FROM, transcript.artifact_id, T0)))
    for a in (audio, transcript, summary):
        await artifacts.update_artifact(a, replace(a, state=ArtifactState.FAILED, error_code="x"))
    return audio, transcript, summary


async def test_delete_refuses_dependents_unless_cascade(stores):
    _b, _c, artifacts, ledger = stores
    audio, transcript, summary = await _chain(artifacts)
    with pytest.raises(ArtifactError) as caught:
        await artifacts.delete_artifact(audio.artifact_id, cascade=False, now=t(1), origin="user")
    assert caught.value.code is ArtifactErrorCode.ARTIFACT_HAS_DEPENDENTS
    assert await artifacts.get_artifact(audio.artifact_id) is not None
    # une feuille part seule, ses relations vers ses origines avec elle ; les origines restent
    leaf = await artifacts.delete_artifact(summary.artifact_id, cascade=False, now=t(1), origin="user")
    assert leaf.artifact_ids == (summary.artifact_id,)
    assert await artifacts.relations_of(transcript.artifact_id, RelationDirection.DEPENDENTS) == ()
    gone = await artifacts.delete_artifact(audio.artifact_id, cascade=True, now=t(2), origin="user")
    assert set(gone.artifact_ids) == {audio.artifact_id, transcript.artifact_id}
    assert gone.artifact_ids[0] == audio.artifact_id
    assert [e.kind for e in gone.events] == [ActivityKind.ARTIFACT_DELETED] * 2
    assert gone.events[1].data["cascade_of"] == audio.artifact_id
    assert (await artifacts.query_artifacts(ArtifactQuery())).items == ()
    with pytest.raises(ArtifactError) as caught:
        await artifacts.delete_artifact(audio.artifact_id, cascade=True, now=t(3), origin="user")
    assert caught.value.code is ArtifactErrorCode.ARTIFACT_NOT_FOUND


async def test_delete_refuses_a_pending_artifact_and_bounds_the_cascade(stores, monkeypatch):
    _b, _c, artifacts, _l = stores
    pending = art()
    await artifacts.create_artifact(pending)
    with pytest.raises(ArtifactError) as caught:
        await artifacts.delete_artifact(pending.artifact_id, cascade=True, now=t(1), origin="user")
    assert caught.value.code is ArtifactErrorCode.ARTIFACT_STILL_PENDING
    audio, _t, _s = await _chain(artifacts)
    import jarvis.adapters.sqlite_artifacts as module
    monkeypatch.setattr(module, "MAX_CASCADE_ARTIFACTS", 2)
    with pytest.raises(ArtifactError) as caught:
        await artifacts.delete_artifact(audio.artifact_id, cascade=True, now=t(1), origin="user")
    assert caught.value.code is ArtifactErrorCode.ARTIFACT_HAS_DEPENDENTS and "in parts" in str(caught.value)
    assert MAX_CASCADE_ARTIFACTS == 256


# ------------------------------------------------------------------ ledger


async def test_ledger_is_ordered_bounded_and_filterable(stores):
    boards, contexts, _a, ledger = stores
    _s, context = await _session_with_context(boards, contexts)
    drafts = [ActivityDraft(kind=ActivityKind.CAPTURE_GAP, occurred_at=t(i), jarvis_session_id=SID,
                            context_id=context.context_id if i % 2 else None, data={"i": i}) for i in range(10)]
    drafts.append(ActivityDraft(kind=ActivityKind.ARTIFACT_CREATED, occurred_at=t(10)))
    events = await ledger.append(drafts)
    seqs = [e.seq for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == 11
    tail = await ledger.list(ActivityQuery(after_seq=seqs[3], limit=3))
    assert [e.seq for e in tail] == seqs[4:7]
    assert [e.data["i"] for e in await ledger.list(ActivityQuery(context_id=context.context_id))] == [1, 3, 5, 7, 9]
    assert len(await ledger.list(ActivityQuery(jarvis_session_id=SID))) == 10
    assert len(await ledger.list(ActivityQuery(kinds=(ActivityKind.ARTIFACT_CREATED,)))) == 1
    assert len(await ledger.list(ActivityQuery(since=t(2), until=t(5)))) == 3
    assert await ledger.latest_seq() == seqs[-1]
    assert await ledger.list(ActivityQuery(after_seq=seqs[-1])) == ()
    with pytest.raises(ActivityError):  # même event_id deux fois : refus, rien d'écrit
        await ledger.append((drafts[0],))
    assert await ledger.latest_seq() == seqs[-1]


async def test_a_seq_is_never_reused_after_the_last_row_is_gone(stores, db):
    *_rest, ledger = stores
    (first,) = await ledger.append((ActivityDraft(kind=ActivityKind.ARTIFACT_CREATED, occurred_at=T0),))
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM session_activity")
    conn.commit()
    conn.close()
    (second,) = await ledger.append((ActivityDraft(kind=ActivityKind.ARTIFACT_CREATED, occurred_at=T0),))
    assert second.seq > first.seq


# ------------------------------------------------------------------ atomicité transition + activité


async def test_context_transition_and_its_activity_commit_or_roll_back_together(stores):
    boards, contexts, _a, ledger = stores
    session, context = await _session_with_context(boards, contexts)
    good = create_context(session, (context,), now=t(1))
    events = (context_event(ActivityKind.CONTEXT_DORMANT, SID, context.context_id, now=t(1), origin="p"),
              context_event(ActivityKind.CONTEXT_CREATED, SID, good.active.context_id, now=t(1), origin="p"))
    await contexts.commit_contexts(good.changed, activity=events)
    assert [e.kind for e in await ledger.list(ActivityQuery())] == [ActivityKind.CONTEXT_DORMANT,
                                                                   ActivityKind.CONTEXT_CREATED]
    # 1) l'événement est refusé (déjà écrit) : la transition n'est pas écrite non plus
    third = create_context(session, good.contexts, now=t(2))
    with pytest.raises(ActivityError):
        await contexts.commit_contexts(third.changed, activity=events)
    assert (await contexts.active_context(SID)).context_id == good.active.context_id
    # 2) la transition est refusée (deux actifs) : l'événement n'est pas écrit
    before = await ledger.latest_seq()
    with pytest.raises(SessionContextError):
        await contexts.commit_contexts((third.active,), activity=(
            context_event(ActivityKind.CONTEXT_CREATED, SID, third.active.context_id, now=t(2), origin="p"),))
    assert await ledger.latest_seq() == before


async def test_session_close_and_its_activity_are_one_transaction(stores):
    boards, contexts, _a, ledger = stores
    session, context = await _session_with_context(boards, contexts)
    closed = close_session(session, reason=SessionEndReason.NEW_SESSION, now=t(1))
    dormant = dormant_contexts_of_closed_session(closed, (context,), now=t(1))
    duplicate = ActivityDraft(kind=ActivityKind.SESSION_CLOSED, occurred_at=t(1), jarvis_session_id=SID)
    await ledger.append((duplicate,))
    with pytest.raises(ActivityError):
        await boards.commit_switch(sessions=(closed,), boards=(), bindings=(), contexts=dormant,
                                   activity=(duplicate,))
    assert (await boards.get_session(SID)).is_open
    await boards.commit_switch(sessions=(closed,), boards=(), bindings=(), contexts=dormant, activity=(
        ActivityDraft(kind=ActivityKind.SESSION_CLOSED, occurred_at=t(1), jarvis_session_id=SID),))
    assert not (await boards.get_session(SID)).is_open
    assert (await ledger.list(ActivityQuery(kinds=(ActivityKind.SESSION_CLOSED,))))[-1].occurred_at == t(1)


async def test_a_context_of_another_session_is_refused(stores):
    """A19 : le Context d'un Artifact appartient à sa Session (vérifié à l'insertion)."""

    boards, contexts, artifacts, _ = stores
    old, old_ctx = await _session_with_context(boards, contexts)
    closed = close_session(old, now=t(1), reason=SessionEndReason.NEW_SESSION)
    await boards.save_session(closed)
    await contexts.commit_contexts(dormant_contexts_of_closed_session(closed, (old_ctx,), now=t(1)))
    board = await boards.get_board(old.active_board_id)
    other = open_session(board, now=t(2), jarvis_session_id="jsess_fedcba9876543210")
    await boards.save_session(other)
    with pytest.raises(ArtifactError) as caught:
        await artifacts.create_artifact(art(jarvis_session_id=other.jarvis_session_id, context_id=old_ctx.context_id))
    assert caught.value.code is ArtifactErrorCode.INVALID_ARTIFACT
    assert "is not a context of session" in str(caught.value)
    created = art(jarvis_session_id=old.jarvis_session_id, context_id=old_ctx.context_id)
    await artifacts.create_artifact(created)  # la bonne Session passe

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from jarvis.adapters.jsonl_history import JsonlHistoryStore
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.domain.v2 import Conversation, ConversationTurn, HistoryRecord, TurnKind


@pytest.mark.asyncio
async def test_state_survives_reopen_and_history_deduplicates(tmp_path):
    db = tmp_path / "state" / "jarvis.sqlite3"
    state = SQLiteStateRepository(db)
    await state.initialize()
    conversation = Conversation()
    await state.save_conversation(conversation)
    turn = ConversationTurn(conversation_id=conversation.id, kind=TurnKind.USER, content="bonjour", correlation_id="corr")
    await state.save_turn(turn)
    await state.close()

    reopened = SQLiteStateRepository(db)
    await reopened.initialize()
    assert (await reopened.get_conversation(conversation.id)).id == conversation.id
    turns = await reopened.list_turns(conversation.id)
    assert [t.content for t in turns] == ["bonjour"]
    await reopened.close()

    history = JsonlHistoryStore(tmp_path / "history")
    record = HistoryRecord(id=turn.id, kind=TurnKind.USER, created_at=datetime.now(timezone.utc), correlation_id="corr", conversation_id=conversation.id, content="bonjour")
    assert await history.append(record) is True
    assert await history.append(record) is False
    assert [r.id for r in await history.read()] == [record.id]


@pytest.mark.asyncio
async def test_history_tolerates_only_truncated_final_line(tmp_path):
    history = JsonlHistoryStore(tmp_path / "history")
    root = tmp_path / "history"
    path = root / "2026-09-02.jsonl"
    path.write_text('{"id":"a","kind":"user","created_at":"2026-09-02T08:00:00+00:00","correlation_id":"c"}\n{"id":', encoding="utf-8")
    records = await history.read()
    assert [r.id for r in records] == ["a"]

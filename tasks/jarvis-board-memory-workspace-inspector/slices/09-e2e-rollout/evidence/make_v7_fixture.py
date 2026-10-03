"""Fabrique une racine de données v7 avec le code v7 (467232f, worktree b7e)."""
import asyncio, json, sqlite3, sys
from pathlib import Path
import jarvis
assert "b7e" in jarvis.__file__, jarvis.__file__
from jarvis.adapters import sqlite_state
assert sqlite_state._SCHEMA_VERSION == 7
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.v2 import ConversationTurn, TurnKind
from jarvis.domain.artifacts import ArtifactKind, ArtifactRelationKind

root = Path(sys.argv[1])

async def main():
    c = JarvisCoreApplication(data_root=root)
    await c.start()
    a = await c.boards.create({"title": "Projet Atlas", "context_summary": "Refonte du site, lot 2",
                               "task_refs": ["task-atlas-1"], "artifact_refs": ["drive:atlas-brief"]})
    b = await c.boards.create({"title": "Ancien projet Borée"})
    old = await c.boards.create({"title": "Archive 2025"})
    first = await c.sessions.current_context()
    s1 = first.context.jarvis_session_id
    await c.boards.switch(b.board_id)
    t = await c.artifacts.record_text(artifact_id="jart_" + "1" * 32, kind=ArtifactKind.TRANSCRIPT, source="v7-fixture",
        text="réunion Borée : décision ORION", jarvis_session_id=s1, context_id=first.context.context_id,
        started_at=None, ended_at=None, duration_ms=None, metadata={}, origins=())
    ctx2 = await c.sessions.create_context(title="Revue Borée")
    await c.artifacts.record_text(artifact_id="jart_" + "2" * 32, kind=ArtifactKind.DERIVED, source="v7-fixture",
        text="résumé Borée", jarvis_session_id=s1, context_id=ctx2.context.context_id, started_at=None,
        ended_at=None, duration_ms=None, metadata={}, origins=((ArtifactRelationKind.DERIVED_FROM, t.artifact_id),))
    await c.boards.switch(a.board_id)
    await c.boards.archive(old.board_id)
    _closed, view = await c.sessions.start_new_session()
    await c.artifacts.record_text(artifact_id="jart_" + "3" * 32, kind=ArtifactKind.DESCRIPTION, source="v7-fixture",
        text="note Atlas", jarvis_session_id=view.session.jarvis_session_id, context_id=None, started_at=None,
        ended_at=None, duration_ms=None, metadata={}, origins=())
    conv = view.binding.conversation_id
    await c.state.save_turn(ConversationTurn(conversation_id=conv, kind=TurnKind.USER, content="où en est Atlas ?"))
    await c.state.save_turn(ConversationTurn(conversation_id=conv, kind=TurnKind.ASSISTANT, content="Lot 2 en cours."))
    print(json.dumps({"a": a.board_id, "b": b.board_id, "archived": old.board_id, "closed_session": s1,
                      "open_session": view.session.jarvis_session_id}))
    await c.stop()

asyncio.run(main())

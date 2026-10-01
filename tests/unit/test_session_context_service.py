"""Contexts de Session dans Core : démarrage, nouvelle Session, service, bloc du tour (Slice 03 session-context).

Contrat : `docs/session-context.md` (*Service*, *Agent hydration*, *Workspace
folder failure*). Bases et dossiers temporaires uniquement.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.adapters.jsonl_history import JsonlHistoryStore
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.adapters.sqlite_workspace_board import SQLiteBoardRepository
from jarvis.core.board_service import BoardService
from jarvis.core.interaction_mode import InteractionModeService
from jarvis.core.session_manager import MAX_HANDOFF_SUMMARY_CHARS, SessionManager
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.core.v2_services import ConversationService
from jarvis.domain.brain_context import MAX_BRAIN_CONTEXT_SUMMARY_BYTES, MAX_BRAIN_DORMANT_CONTEXTS
from jarvis.domain.session_context import ContextOrigin, ContextStatus, SessionContextError


class Bus:
    async def publish(self, envelope) -> None:
        pass


class Journal:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None) -> None:
        self.lines.append((kind, level, dict(data or {})))

    def kinds(self) -> list[str]:
        return [kind for kind, _, _ in self.lines]

    def of(self, kind: str) -> list[dict]:
        return [data for k, _, data in self.lines if k == kind]


@pytest.fixture
async def core(tmp_path):
    app = JarvisCoreApplication(data_root=tmp_path, diagnostics=(journal := Journal()))
    await app.start()
    app.journal_for_tests = journal  # type: ignore[attr-defined]
    try:
        yield app
    finally:
        await app.stop()


# ------------------------------------------------------------------ démarrage


async def test_a_new_session_at_start_is_born_with_one_active_context_and_its_folder(core, tmp_path):
    view = await core.sessions.current_context()
    session = (await core.sessions.current()).session
    assert view.context.jarvis_session_id == session.jarvis_session_id
    assert (view.context.status, view.context.origin) == (ContextStatus.ACTIVE, ContextOrigin.CREATED)
    expected = tmp_path.resolve() / "sessions" / session.jarvis_session_id / "contexts" / view.context.context_id
    assert Path(view.workspace_path) == expected and expected.is_dir() and view.workspace_error is None
    opened = core.journal_for_tests.of("core.session.opened")
    assert opened[0]["context_id"] == view.context.context_id


async def test_an_open_session_from_before_contexts_is_adopted_once_at_start(tmp_path):
    # Vie précédente : Core d'avant les Contexts (aucun dépôt de Context branché).
    state = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await state.initialize()
    repo = SQLiteBoardRepository(state)
    boards = BoardService(repo, interaction_mode=InteractionModeService(events=Bus()))
    legacy = SessionManager(repo, boards=boards, conversations=ConversationService(
        state, JsonlHistoryStore(tmp_path / "history")))
    await boards.ensure_default()
    old = await legacy.start()
    await boards.stop()
    await state.close()

    for _ in range(2):  # deux démarrages : une seule adoption
        app = JarvisCoreApplication(data_root=tmp_path, diagnostics=(journal := Journal()))
        await app.start()
        try:
            assert (await app.sessions.current()).session.jarvis_session_id == old.session.jarvis_session_id
            contexts = await app.sessions.list_contexts()
            assert [(c.origin, c.status) for c in contexts] == [(ContextOrigin.ADOPTED, ContextStatus.ACTIVE)]
            assert Path((await app.sessions.current_context()).workspace_path).is_dir()
        finally:
            await app.stop()
    assert journal.of("core.context.adopted") == []  # le second démarrage n'adopte plus


# ------------------------------------------------------------------ nouvelle Session


async def test_new_session_puts_the_old_context_to_sleep_and_gives_the_new_one_its_own(core):
    before = await core.sessions.current_context()
    closed, view = await core.sessions.start_new_session()
    old = await core.sessions._contexts.list_contexts(closed.jarvis_session_id)
    assert [(c.context_id, c.status) for c in old] == [(before.context.context_id, ContextStatus.DORMANT)]
    after = await core.sessions.current_context()
    assert after.context.jarvis_session_id == view.session.jarvis_session_id
    assert after.context.context_id != before.context.context_id and after.context.origin is ContextOrigin.CREATED
    assert Path(after.workspace_path).is_dir()
    created = core.journal_for_tests.of("core.context.created")
    assert created[-1]["origin"] == "new_session" and created[-1]["dormanted"] == [before.context.context_id]


# ------------------------------------------------------------------ service : créer, relayer, réactiver


async def test_create_context_writes_a_bounded_handoff_and_never_copies_the_old_folder(core):
    first = await core.sessions.current_context()
    (Path(first.workspace_path) / "notes.md").write_text("brouillon de l'ancien Context", encoding="utf-8")
    view = await core.sessions.create_context(title="Analyse", handoff_summary="Retenir : budget validé.",
                                              source_context_ids=[first.context.context_id])
    folder = Path(view.workspace_path)
    assert sorted(p.name for p in folder.iterdir()) == ["handoff.md"]  # aucun fichier hérité
    text = (folder / "handoff.md").read_text(encoding="utf-8")
    assert "Retenir : budget validé." in text and first.context.context_id in text
    assert view.handoff_path == str(folder / "handoff.md") and view.handoff_error is None
    contexts = {c.context_id: c for c in await core.sessions.list_contexts()}
    assert contexts[first.context.context_id].status is ContextStatus.DORMANT
    assert contexts[view.context.context_id].source_context_ids == (first.context.context_id,)


async def test_create_context_without_handoff_writes_nothing(core):
    view = await core.sessions.create_context(title="Vide")
    assert list(Path(view.workspace_path).iterdir()) == [] and view.handoff_path is None


async def test_create_context_refusals_change_nothing(core):
    first = await core.sessions.current_context()
    for kwargs, code in (
        ({"source_context_ids": ["jctx_unknown"]}, "context_not_found"),
        ({"handoff_summary": "x" * (MAX_HANDOFF_SUMMARY_CHARS + 1)}, "invalid_context"),
        ({"source_context_ids": "jctx_a"}, "invalid_context"),
    ):
        with pytest.raises(SessionContextError) as raised:
            await core.sessions.create_context(**kwargs)
        assert raised.value.code.value == code
    assert [c.context_id for c in await core.sessions.list_contexts()] == [first.context.context_id]


async def test_activate_context_reactivates_a_dormant_one_and_the_next_turn_sees_it(core):
    first = await core.sessions.current_context()
    second = await core.sessions.create_context(title="Deuxième")
    conversation = (await core.sessions.current()).binding.conversation_id
    assert (await core.sessions.session_context(conversation)).context_id == second.context.context_id
    again = await core.sessions.activate_context(first.context.context_id)
    assert again.context.context_id == first.context.context_id and again.context.is_active
    block = await core.sessions.session_context(conversation)
    assert block.context_id == first.context.context_id
    assert [d.context_id for d in block.dormant] == [second.context.context_id]
    unchanged = await core.sessions.activate_context(first.context.context_id)  # déjà actif : rien
    assert unchanged.context == again.context
    with pytest.raises(SessionContextError) as raised:
        await core.sessions.activate_context("jctx_missing")
    assert raised.value.code.value == "context_not_found"


# ------------------------------------------------------------------ bloc du tour


async def test_session_context_block_is_bounded_and_names_dormant_contexts_only(core, tmp_path):
    conversation = (await core.sessions.current()).binding.conversation_id
    titles = [f"Context {i}" for i in range(MAX_BRAIN_DORMANT_CONTEXTS + 2)]
    for title in titles:
        dormant_view = await core.sessions.create_context(title=title)
        (Path(dormant_view.workspace_path) / "summary.md").write_text(f"secret de {title}", encoding="utf-8")
    active = await core.sessions.create_context(title="Actif")
    (Path(active.workspace_path) / "summary.md").write_text("é" * MAX_BRAIN_CONTEXT_SUMMARY_BYTES, encoding="utf-8")
    block = await core.sessions.session_context(conversation)
    assert block.context_id == active.context.context_id and block.title == "Actif"
    assert block.workspace_path == active.workspace_path
    assert block.sessions_root == str(tmp_path.resolve() / "sessions")
    assert block.summary_clipped and len(block.summary.encode("utf-8")) <= MAX_BRAIN_CONTEXT_SUMMARY_BYTES
    assert set(block.summary) == {"é"}  # coupé sur un caractère entier
    assert len(block.dormant) == MAX_BRAIN_DORMANT_CONTEXTS and block.omitted_dormant == 3
    assert block.dormant[0].title == titles[-1]  # le plus récemment actif d'abord
    assert "secret de" not in str(block.to_payload())  # jamais le contenu d'un dormant


async def test_a_summary_that_is_not_a_regular_file_is_never_read(core):
    conversation = (await core.sessions.current()).binding.conversation_id
    view = await core.sessions.current_context()
    (Path(view.workspace_path) / "summary.md").mkdir()
    block = await core.sessions.session_context(conversation)
    assert block.summary == "" and block.workspace_error is None
    warned = core.journal_for_tests.of("core.context.summary_unreadable")
    assert warned and warned[0]["code"] == "context_workspace_unsafe"


async def test_a_conversation_of_a_closed_session_has_no_context_block(core):
    old = (await core.sessions.current()).binding.conversation_id
    await core.sessions.start_new_session()
    assert await core.sessions.session_context(old) is None
    assert await core.sessions.session_context("unknown-conversation") is None


# ------------------------------------------------------------------ politique d'échec du dossier


async def test_a_blocked_workspace_never_stops_core_and_recovers_on_the_next_access(tmp_path):
    (tmp_path / "sessions").write_text("un fichier là où un dossier est attendu", encoding="utf-8")
    app = JarvisCoreApplication(data_root=tmp_path, diagnostics=(journal := Journal()))
    await app.start()  # ne lève pas : Core sert, le Context est dégradé
    try:
        assert app.health.ready
        conversation = (await app.sessions.current()).binding.conversation_id
        view = await app.sessions.current_context()
        assert view.workspace_error == "context_workspace_unsafe"
        block = await app.sessions.session_context(conversation)
        assert block.workspace_error == "context_workspace_unsafe" and block.summary == ""
        failures = journal.of("core.context.workspace_failed")
        assert len(failures) == 1 and failures[0]["code"] == "context_workspace_unsafe"  # dit une fois, pas à chaque tour
        (tmp_path / "sessions").unlink()
        recovered = await app.sessions.session_context(conversation)
        assert recovered.workspace_error is None and Path(recovered.workspace_path).is_dir()
        assert journal.of("core.context.workspace_ready")
    finally:
        await app.stop()


async def test_sessions_current_carries_the_context_for_the_control_center(core):
    payload = await core.sessions.context_brief_payload()
    view = await core.sessions.current_context()
    assert payload["context"]["context_id"] == view.context.context_id
    assert payload["workspace_path"] == view.workspace_path
    assert Path(payload["sessions_root"]).is_absolute()

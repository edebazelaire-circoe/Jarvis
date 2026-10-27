"""Recherche : existant d'abord, fraîcheur explicite, lectures bornées au Board (V1.2 Slice 03).

Contrat : `docs/subagent-roles.md` › *Recherche : existant d'abord (édition Presentation)*,
`docs/product-capabilities.md` › *Reading scope*. Couvre :

- la décision pure `research_freshness.decide` (réutiliser / rafraîchir en partie / tout revérifier / chercher à
  neuf) et son front-matter ;
- son transport réel : Core lit `documents/research/` du Board du tour (édition Presentation seulement), décide sur
  le texte du tour, trace `core.research.freshness_decided`, et le Control Center le rend dans le brief ;
- la consigne : Presentation seulement (`full` identique, prouvé aussi par `dump_full.py` à l'octet) ;
- I-002 correction 1 : un CLI confiné ne reçoit que la mémoire du Board de son entrée et le dossier de sa Session.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from jarvis.adapters.board_memory_store import FileBoardMemoryStore
from jarvis.adapters.context_workspace import FileContextWorkspaces
from jarvis.adapters.jsonl_history import JsonlHistoryStore
from jarvis.adapters.sqlite_session_context import SQLiteContextRepository
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.adapters.sqlite_workspace_board import SQLiteBoardRepository
from jarvis.core.board_hydration import read_board_memory, with_board_research
from jarvis.core.board_service import BoardService
from jarvis.core.interaction_mode import InteractionModeService
from jarvis.core.session_manager import SessionManager
from jarvis.core.speech_authority import SpeechAuthority
from jarvis.core.v2_services import ConversationService
from jarvis.domain.agent_capabilities import PRESENTATION_CAPABILITIES, UNCONFINED
from jarvis.domain.board_memory import BoardMemoryPath
from jarvis.domain.research_freshness import (
    MAX_RESEARCH_DOCS, RECENCY_MAX_AGE_DAYS, TOPIC_STOPWORDS, FreshnessAction, FreshnessDecision, ResearchDocStatus,
    ResearchMetadata, ResearchSource, Volatility, decide, matches_topic, parse_front_matter, recency_terms,
)
from jarvis.domain.subagent_roles import (
    RESEARCH_REUSE_MARK, ROLES, brain_rules, research_reuse_text, role_brief, role_by_id,
)
from jarvis.domain.workspace_board import DEFAULT_BOARD_ID
from jarvis.ports.board_memory import WriteMode
from jarvis.runtime import claude_local
from jarvis.runtime.board_brief import BRIEF_RESEARCH_HEAD, render_board_brief, render_board_research
from jarvis.runtime.claude_local import BRAIN_PRESENTATION_RESEARCH_MARK, ClaudeLocalAgent, render_brain_system_prompt
from jarvis.runtime.control_center import ControlCenter
from tests.unit.test_agent_capabilities import _brain, _launch
from tests.unit.test_board_switch import Bus, Clock, Host, Journal

TODAY = date(2026, 10, 27)
OLD_OPENAI_NOTE = """---
topic: Modèles d'OpenAI
scope: modèles de l'API
checked_at: 2025-03-02
volatility: forte
uncertainty: dates de retrait
sources:
  - https://platform.openai.com/docs/models | date: 2025-02-20
---
# Modèles d'OpenAI (mars 2025)
"""


def _meta(checked: date, volatility: Volatility = Volatility.MEDIUM, *sources: ResearchSource) -> ResearchMetadata:
    return ResearchMetadata(topic="Sujet", checked_at=checked, volatility=volatility, sources=sources)


# ------------------------------------------------------------------ 1. décision pure


def test_a_recent_document_is_reused():
    decision = decide(_meta(date(2026, 10, 20), Volatility.HIGH, ResearchSource("https://a", date(2026, 10, 18))),
                      today=TODAY, request="Fais-moi le point sur ce sujet pour la slide 3")
    assert decision.action is FreshnessAction.REUSE and decision.reason == "fresh" and decision.age_days == 7


def test_a_volatile_partly_old_document_is_refreshed_only_where_stale():
    meta = _meta(date(2026, 10, 1), Volatility.LOW,
                 ResearchSource("https://prix", checked_at=date(2026, 8, 1), volatility=Volatility.HIGH),
                 ResearchSource("https://histoire", checked_at=date(2026, 10, 1)))
    decision = decide(meta, today=TODAY, request="reprends la note sur les tarifs")
    assert decision.action is FreshnessAction.PARTIAL_REFRESH and decision.reason == "partially_stale"
    assert decision.stale_sources == ("https://prix",)


def test_a_2025_note_and_latest_openai_models_forces_a_full_revalidation():
    meta, problem = parse_front_matter(OLD_OPENAI_NOTE)
    assert problem is None and meta.checked_at == date(2025, 3, 2) and meta.volatility is Volatility.HIGH
    decision = decide(meta, today=TODAY, request="Quels sont les derniers modèles d'OpenAI ?")
    assert decision.action is FreshnessAction.FULL_REFRESH and decision.reason == "recency_requested"
    assert decision.recency == ("derniers",)


def test_no_document_means_a_new_research():
    decision = decide(None, today=TODAY, request="les derniers modèles", exists=False)
    assert decision.action is FreshnessAction.NEW_RESEARCH and decision.reason == "no_document"


@pytest.mark.parametrize(("request_text", "terms"), [
    ("Quels sont les DERNIERS modèles ?", ("derniers",)),
    ("l’état actuel du marché", ("actuel",)),
    ("Qu'en est-il aujourd'hui ?", ("aujourd'hui",)),
    ("what is the latest version", ("latest",)),
    ("la dernière version de Remotion", ("dernière",)),
    ("les prix actuellement pratiqués", ("actuellement",)),
    ("la dernière présentation de l'équipe", ("dernière",)),
    ("résume la note", ()),
    ("les actualités du secteur", ()),
    # Faux positifs écartés (reprise QA M3) : un élément du deck, « maintenant » seul, une année seule.
    ("Modifie la dernière diapo", ()),
    ("change la dernière slide et la dernière phrase", ()),
    ("reprends la dernière version du deck", ()),
    ("relis mes derniers messages", ()),
    ("maintenant, fais la slide 3", ()),
    ("les chiffres de 2026", ()),
])
def test_recency_wording_is_detected_on_whole_words(request_text, terms):
    assert recency_terms(request_text, TODAY) == terms


def test_a_recency_request_shrinks_the_tolerated_age_of_each_source():
    checked = date(2026, 10, 25)
    meta = _meta(checked, Volatility.LOW, ResearchSource("https://a", checked_at=date(2026, 10, 1)),
                 ResearchSource("https://b"))
    assert decide(meta, today=TODAY, request="résume").action is FreshnessAction.REUSE
    decision = decide(meta, today=TODAY, request="où en est-on actuellement ?")
    assert decision.action is FreshnessAction.PARTIAL_REFRESH and decision.stale_sources == ("https://a",)
    assert (TODAY - date(2026, 10, 1)).days > RECENCY_MAX_AGE_DAYS


def test_unknown_future_and_entirely_stale_documents_are_revalidated_in_full():
    assert decide(ResearchMetadata(topic="x"), today=TODAY).reason == "freshness_unknown"
    assert decide(None, today=TODAY).action is FreshnessAction.FULL_REFRESH
    assert decide(_meta(date(2027, 1, 1)), today=TODAY).reason == "checked_at_in_future"
    stale = decide(_meta(date(2025, 1, 1), Volatility.MEDIUM), today=TODAY, request="résume")
    assert stale.action is FreshnessAction.FULL_REFRESH and stale.reason == "stale"
    # Pas de durée universelle : le même âge est frais pour un sujet stable.
    assert decide(_meta(date(2025, 1, 1), Volatility.LOW), today=TODAY).action is FreshnessAction.REUSE


def test_staleness_follows_the_last_check_not_the_publication_date():
    """Reprise QA B2 : une source ancienne mais vérifiée hier reste valable ; son âge est seulement signalé."""

    meta = _meta(date(2026, 10, 26), Volatility.HIGH, ResearchSource("https://vieux", date(2024, 5, 1)),
                 ResearchSource("https://neuf", date(2026, 10, 20)))
    decision = decide(meta, today=TODAY)
    assert decision.action is FreshnessAction.REUSE and decision.old_sources == ("https://vieux",)
    # Même avec une demande d'actualité sur ce sujet : vérifié hier, donc réutilisable.
    assert decide(meta, today=TODAY, request="les derniers prix").action is FreshnessAction.REUSE
    # Le jour même de son rafraîchissement, un document est réutilisable, quelle que soit la date de ses sources.
    refreshed = _meta(TODAY, Volatility.HIGH,
                      ResearchSource("https://usagepricing.com/gamma", date(2026, 9, 8), checked_at=TODAY),
                      ResearchSource("https://help.gamma.app", date(2025, 1, 2), checked_at=TODAY))
    assert decide(refreshed, today=TODAY, request="les derniers tarifs de Gamma").action is FreshnessAction.REUSE


FAILED_NOTE = """---
topic: Gamma
checked_at: 2026-10-27
volatility: high
sources:
  - https://help.gamma.app | checked: 2026-10-27 (échec HTTP 403, non lue)
  - https://gamma.app/pricing | checked: 2026-10-27 | status: failed
  - https://gamma.app/docs | checked: 2026-10-27
---
"""
QUOTED_NOTE = """---
topic: 'Sujet'
checked_at: '2026-10-20'
volatility: "medium"
sources:
  - https://a | date: "2026-10-01" | checked: '2026-10-20'
---
"""


def test_a_failed_check_does_not_count_as_a_check():
    meta, _ = parse_front_matter(FAILED_NOTE)
    assert [source.failed for source in meta.sources] == [True, True, False]
    decision = decide(meta, today=TODAY)
    # Seconde reprise F1 : la date de `checked` d'une source ratée est celle de la tentative ; pas de nouvel essai
    # avant l'âge toléré (30 j, `high`), la source est seulement « non vérifiable ».
    assert [source.tried_at for source in meta.sources[:2]] == [TODAY, TODAY]
    decision = decide(meta, today=TODAY)
    assert decision.action is FreshnessAction.REUSE
    assert decision.unverifiable_sources == ("https://help.gamma.app", "https://gamma.app/pricing")
    later = decide(meta, today=date(2026, 11, 27))
    assert later.action is FreshnessAction.FULL_REFRESH  # toutes au-delà de 30 j : on réessaie, et on revérifie


def test_quoted_yaml_dates_are_read():
    meta, _ = parse_front_matter(QUOTED_NOTE)
    assert meta.topic == "Sujet" and meta.checked_at == date(2026, 10, 20) and meta.volatility is Volatility.MEDIUM
    assert meta.sources[0].date == date(2026, 10, 1) and meta.sources[0].checked_at == date(2026, 10, 20)


def test_recency_applies_only_to_documents_on_the_topic_of_the_turn():
    """Reprise QA M3 : « derniers modèles d'OpenAI » ne fait pas revérifier la note sur Gamma."""

    gamma = _meta(date(2026, 10, 10), Volatility.HIGH, ResearchSource("https://gamma.app"))
    request = "Quels sont les derniers modèles d'OpenAI ?"
    assert not matches_topic(request, "gamma-outil", "Gamma (gamma.app) : fonctionnalités et tarifs")
    assert matches_topic(request, "openai-modeles", "Modèles d'OpenAI disponibles")
    off = decide(gamma, today=TODAY, request=request, on_topic=False)
    assert off.action is FreshnessAction.REUSE and off.recency == ()
    on = decide(gamma, today=TODAY, request=request, on_topic=True)
    assert on.action is FreshnessAction.FULL_REFRESH and on.reason == "recency_requested"
    assert not matches_topic("Modifie la dernière diapo", "gamma-outil", "Gamma")
    assert not matches_topic("", "gamma-outil", "Gamma")


def test_the_front_matter_parser_is_small_strict_and_never_raises():
    assert parse_front_matter("# pas de métadonnées") == (None, "no_front_matter")
    meta, problem = parse_front_matter("---\ntopic: x\n")
    assert problem == "unterminated_front_matter" and meta.topic == "x"
    meta, _ = parse_front_matter("---\nchecked_at: 27/10/2026\nvolatility: chaotique\n---\n")
    assert meta.checked_at is None and meta.volatility is None
    meta, _ = parse_front_matter(OLD_OPENAI_NOTE.replace("forte", "low"))
    assert meta.volatility is Volatility.LOW and meta.sources[0].date == date(2025, 2, 20)


# ------------------------------------------------------------------ 2. transport réel : Core -> brief


def _write(store: FileBoardMemoryStore, board_id: str, path: str, text: str) -> None:
    store.write(board_id, BoardMemoryPath.parse(path), text, mode=WriteMode.REPLACE)


def test_core_reads_the_board_research_documents_and_decides_on_the_turn_text(tmp_path):
    store = FileBoardMemoryStore(tmp_path)
    _write(store, DEFAULT_BOARD_ID, "summary.md", "# Projet")
    _write(store, DEFAULT_BOARD_ID, "documents/research/openai.md", OLD_OPENAI_NOTE)
    _write(store, DEFAULT_BOARD_ID, "documents/research/sans-date.md", "# Notes sans métadonnées")
    _write(store, DEFAULT_BOARD_ID, "documents/research/image.png", "pas un document")
    memory = read_board_memory(store, tmp_path, DEFAULT_BOARD_ID)
    enriched, unread = with_board_research(memory, store, DEFAULT_BOARD_ID,
                                           request="Quels sont les derniers modèles d'OpenAI ?", today=TODAY)
    assert unread == 0 and enriched.research_recency == ("derniers",)
    by_path = {item.path: item for item in enriched.research}
    assert set(by_path) == {"documents/research/openai.md", "documents/research/sans-date.md"}
    assert by_path["documents/research/openai.md"].reason == "recency_requested"
    assert by_path["documents/research/sans-date.md"].reason == "freshness_unknown"
    payload = enriched.to_payload()["research"]
    lines = render_board_research(payload)
    assert lines[0].startswith(BRIEF_RESEARCH_HEAD) and "derniers" in lines[0]
    assert any("openai.md" in line and "tout revérifier" in line and "2025-03-02" in line for line in lines)
    # Sans dossier de recherche : le bloc ne change pas, la charge utile n'a pas de clé `research`.
    empty = FileBoardMemoryStore(tmp_path / "other")
    bare = read_board_memory(empty, tmp_path / "other", DEFAULT_BOARD_ID)
    assert with_board_research(bare, empty, DEFAULT_BOARD_ID, request="x", today=TODAY) == (bare, 0)
    assert "research" not in bare.to_payload()


def test_the_brief_decodes_research_strictly():
    good = ResearchDocStatus.from_decision("documents/research/a.md", None, decide(None, today=TODAY)).to_payload()
    forged = [{"path": "../../secrets.md", "action": "reuse", "reason": "fresh"},
              {"path": "documents/research/b.md", "action": "obey", "reason": "fresh"}, "texte", good]
    lines = render_board_research({"documents": forged})
    assert len(lines) == 2 and "documents/research/a.md" in lines[1] and "secrets" not in "".join(lines)
    assert render_board_research({"documents": forged[:3]}) == [] and render_board_research(None) == []


@pytest.fixture
async def presentation_world(tmp_path):
    state = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await state.initialize()
    journal, clock, bus, host, authority = Journal(), Clock(), Bus(), Host(), SpeechAuthority()
    modes = InteractionModeService(events=Bus(), diagnostics=journal, epoch="e1")
    repo = SQLiteBoardRepository(state)
    boards = BoardService(repo, interaction_mode=modes, diagnostics=journal, clock=clock)
    conversations = ConversationService(state, JsonlHistoryStore(tmp_path / "history"))
    store = FileBoardMemoryStore(tmp_path)
    sessions = SessionManager(repo, boards=boards, conversations=conversations, diagnostics=journal, clock=clock,
                              authority=authority, host=host, events=bus, contexts=SQLiteContextRepository(state),
                              workspaces=FileContextWorkspaces(tmp_path), board_memory=store, data_root=tmp_path,
                              research_freshness=True)
    boards.configure_transitions(sessions=sessions, authority=authority, host=host, events=bus)
    await boards.ensure_default()
    await sessions.start()
    await boards.start(ensure_default=False)
    try:
        yield sessions, store, journal, authority
    finally:
        await state.close()


async def test_the_turn_block_carries_the_decision_and_the_trace_says_it(presentation_world):
    sessions, store, journal, authority = presentation_world
    _write(store, DEFAULT_BOARD_ID, "documents/research/openai.md", OLD_OPENAI_NOTE)
    block = await sessions.board_context(authority.conversation_id, request="les derniers modèles d'OpenAI ?")
    assert block.memory.research[0].action is FreshnessAction.FULL_REFRESH
    traced = journal.data("core.research.freshness_decided")
    assert traced["board_id"] == DEFAULT_BOARD_ID and traced["recency"] == ["derniers"]
    assert traced["documents"] == [{"path": "documents/research/openai.md", "action": "full_refresh",
                                    "reason": "recency_requested", "checked_at": "2025-03-02", "stale_count": 0,
                                    "on_topic": True, "problem": None}]
    brief = "\n".join(render_board_brief(block.to_payload()))
    assert "Recherches du Board" in brief and "tout revérifier" in brief
    # Un appelant d'avant (sans `request`) garde son bloc ; la décision suit alors une demande neutre.
    again = await sessions.board_context(authority.conversation_id)
    assert again.memory.research[0].reason == "stale"


async def test_full_edition_never_reads_research(tmp_path):
    state = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await state.initialize()
    journal, clock, bus, host, authority = Journal(), Clock(), Bus(), Host(), SpeechAuthority()
    repo = SQLiteBoardRepository(state)
    boards = BoardService(repo, interaction_mode=InteractionModeService(events=Bus(), diagnostics=journal, epoch="e"),
                          diagnostics=journal, clock=clock)
    store = FileBoardMemoryStore(tmp_path)
    sessions = SessionManager(repo, boards=boards, conversations=ConversationService(state, JsonlHistoryStore(
        tmp_path / "history")), diagnostics=journal, clock=clock, authority=authority, host=host, events=bus,
        board_memory=store, data_root=tmp_path)
    boards.configure_transitions(sessions=sessions, authority=authority, host=host, events=bus)
    await boards.ensure_default()
    await sessions.start()
    await boards.start(ensure_default=False)
    try:
        _write(store, DEFAULT_BOARD_ID, "documents/research/openai.md", OLD_OPENAI_NOTE)
        block = await sessions.board_context(authority.conversation_id, request="les derniers modèles")
        assert block.memory.research == () and "research" not in block.memory.to_payload()
        assert "core.research.freshness_decided" not in journal.kinds()
    finally:
        await state.close()


# ------------------------------------------------------------------ 3. consigne : Presentation seulement


def test_the_research_rules_live_in_the_presentation_prompt_only():
    prompt = render_brain_system_prompt(PRESENTATION_CAPABILITIES)
    assert prompt.count(BRAIN_PRESENTATION_RESEARCH_MARK + "\n") == 1
    assert "aucune recherche web" in prompt and "Un autre Board ne se lit que si l'utilisateur le demande" in prompt
    assert "le web seulement pour ce qui manque ou est périmé" in brain_rules(capabilities=PRESENTATION_CAPABILITIES)
    for text in (claude_local.BRAIN_SYSTEM_PROMPT, render_brain_system_prompt(UNCONFINED),
                 render_brain_system_prompt(None)):
        assert BRAIN_PRESENTATION_RESEARCH_MARK not in text and "Recherches du Board" not in text
    for rules in (brain_rules(), brain_rules(capabilities=UNCONFINED)):
        assert "lance alors en parallèle ceux qui servent" in rules and "EXISTANT D'ABORD" not in rules


def test_research_roles_get_the_reuse_block_in_presentation_only():
    for role in ROLES:
        brief = role_brief(role, capabilities=PRESENTATION_CAPABILITIES)
        expected = role.id in {"research", "web-research", "research-lead"}
        assert (RESEARCH_REUSE_MARK in brief) is expected, role.id
        assert RESEARCH_REUSE_MARK not in role_brief(role) and RESEARCH_REUSE_MARK not in role_brief(
            role, capabilities=UNCONFINED)
    lead = research_reuse_text(role_by_id("research-lead"), PRESENTATION_CAPABILITIES)
    assert "relation adversary" in lead and "relation qa" in lead and "Pas pour chaque question" in lead
    doc = research_reuse_text(role_by_id("research"), PRESENTATION_CAPABILITIES)
    assert "checked_at:" in doc and "documents/research/" in doc and "un autre Board" in doc
    # Le gabarit d'écriture se relit par la décision : un document écrit selon lui a une fraîcheur connue.
    template = doc[doc.index("---"):doc.rindex("---") + 3]
    filled = (template.replace("<AAAA-MM-JJ de votre vérification>", "2026-10-27")
              .replace("<low | medium | high>", "high"))
    meta, problem = parse_front_matter(filled)
    assert problem is None and meta.checked_at == TODAY and meta.volatility is Volatility.HIGH


# ------------------------------------------------------------------ 4. I-002 correction 1 : lectures bornées au Board


def _confined_brain(monkeypatch, tmp_path: Path, scope: tuple[str | None, str | None]) -> ClaudeLocalAgent:
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", "presentation")
    agent = _brain(tmp_path)
    data = tmp_path / "data"
    (data / "sessions").mkdir(parents=True)
    agent.boards_dir = data / "boards"
    agent.sessions_root = data / "sessions"
    agent.add_dirs = (data / "sessions",)
    agent.board_scope = lambda: scope
    return agent


def _add_dirs(argv: list[str]) -> list[str]:
    start = argv.index("--add-dir") + 1
    end = next(i for i in range(start, len(argv)) if argv[i].startswith("--"))
    return argv[start:end]


async def test_a_confined_cli_reads_only_its_board_memory_and_its_session(monkeypatch, tmp_path):
    agent = _confined_brain(monkeypatch, tmp_path, ("board_a", "jsess_one"))
    argv, _ = await _launch(monkeypatch, agent)
    dirs = _add_dirs(argv)
    data = (tmp_path / "data").resolve()
    assert str(data / "boards" / "board_a" / "memory") in dirs
    assert str(data / "sessions" / "jsess_one") in dirs
    assert str(tmp_path / "data" / "boards") not in dirs and str(tmp_path / "data" / "sessions") not in dirs
    assert not any(Path(item).name == "boards" or Path(item).name == "sessions" for item in dirs)
    assert agent.launched_board_scope == ("board_a", "jsess_one")


async def test_an_unbound_confined_cli_reads_no_board_and_no_session(monkeypatch, tmp_path):
    agent = _confined_brain(monkeypatch, tmp_path, (None, None))
    argv, _ = await _launch(monkeypatch, agent)
    assert not any("boards" in Path(item).parts or "sessions" in Path(item).parts for item in _add_dirs(argv))


async def test_rebinding_to_another_board_makes_the_running_cli_stale_and_the_control_center_relaunches(
        monkeypatch, tmp_path):
    scope = {"value": (None, None)}
    agent = _confined_brain(monkeypatch, tmp_path, ("x", "y"))
    agent.board_scope = lambda: scope["value"]
    await _launch(monkeypatch, agent)
    assert agent.launched_board_scope == (None, None)
    monkeypatch.setattr(type(agent), "state", property(lambda self: "running"))
    assert not agent.board_scope_stale()
    scope["value"] = ("board_b", "jsess_two")  # adoption : même processus, autre liaison
    assert agent.board_scope_stale()
    center = ControlCenter.__new__(ControlCenter)
    center._sessions_root = None
    center._artifacts_root = None
    assert ControlCenter._lacks_workspace_grant(center, agent) is True


async def test_the_full_edition_keeps_every_board_and_session_folder(monkeypatch, tmp_path):
    agent = _confined_brain(monkeypatch, tmp_path, ("board_a", "jsess_one"))
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", "full")
    argv, _ = await _launch(monkeypatch, agent)
    dirs = _add_dirs(argv)
    assert str(tmp_path / "data" / "sessions") in dirs
    assert any(Path(item).name == "boards" for item in dirs)
    assert agent.launched_board_scope is None and not agent.board_scope_stale()


# ------------------------------------------------------------------ 5. reprise QA : en-tête long, surplus, relances

LONG_FRONT_MATTER = Path(__file__).parents[1] / "fixtures" / "research" / "long-front-matter.md"


def test_the_real_3907_byte_header_written_by_the_research_lead_is_read_in_full(tmp_path):
    """Reprise QA B1 : l'en-tête réel du bac (30 sources, 3 907 octets) n'est plus lu comme « sans date »."""

    text = LONG_FRONT_MATTER.read_text(encoding="utf-8")
    assert len(text[:text.index("\n---", 3) + 4].encode("utf-8")) == 3907
    store = FileBoardMemoryStore(tmp_path)
    _write(store, DEFAULT_BOARD_ID, "documents/research/outils-video-presentation-ia-2026.md", text)
    memory = read_board_memory(store, tmp_path, DEFAULT_BOARD_ID)
    enriched, _ = with_board_research(memory, store, DEFAULT_BOARD_ID,
                                      request="Rappelle-moi les prix de Synthesia et HeyGen", today=TODAY)
    status = enriched.research[0]
    assert status.topic.startswith("Outils de génération de vidéos") and status.checked_at == TODAY
    assert status.action is FreshnessAction.REUSE and status.problem is None
    line = render_board_research(enriched.to_payload()["research"])[1]
    assert "réutiliser tel quel" in line and "sans sujet" not in line and "trop long" not in line


def test_a_header_beyond_its_own_bound_is_said_not_turned_into_unknown(tmp_path):
    sources = "".join(f"  - https://exemple.org/{i:04d}/{'x' * 120} | date: 2026-10-01 | checked: 2026-10-26\n"
                      for i in range(160))
    text = (f"---\ntopic: Sujet très sourcé\nchecked_at: 2026-10-26\nvolatility: medium\nsources:\n{sources}---\n"
            "# corps\n")
    store = FileBoardMemoryStore(tmp_path)
    _write(store, DEFAULT_BOARD_ID, "documents/research/sujet.md", text)
    memory = read_board_memory(store, tmp_path, DEFAULT_BOARD_ID)
    status = with_board_research(memory, store, DEFAULT_BOARD_ID, request="x", today=TODAY)[0].research[0]
    assert status.problem == "front_matter_too_long" and status.topic == "Sujet très sourcé"
    # Seconde reprise m2 : décision prudente, la même que pour un en-tête jamais fermé ; sujet et date affichés.
    assert status.action is FreshnessAction.FULL_REFRESH and status.reason == "freshness_unknown"
    assert status.checked_at == date(2026, 10, 26)
    lines = render_board_research({"documents": [{**status.to_payload(), "on_topic": True}]})
    assert "jamais fermé ou trop long, lu en partie" in lines[1]


def test_beyond_eight_documents_the_brain_is_told_how_many_are_missing_and_the_topic_comes_first(tmp_path):
    store = FileBoardMemoryStore(tmp_path)
    note = "---\ntopic: Sujet {n}\nchecked_at: 2026-10-26\n---\n"
    for n in range(MAX_RESEARCH_DOCS + 2):
        _write(store, DEFAULT_BOARD_ID, f"documents/research/a{n:02d}.md", note.format(n=n))
    _write(store, DEFAULT_BOARD_ID, "documents/research/zz-tarifs-synthesia.md", note.format(n="Synthesia"))
    memory = read_board_memory(store, tmp_path, DEFAULT_BOARD_ID)
    enriched, unread = with_board_research(memory, store, DEFAULT_BOARD_ID, request="les tarifs de Synthesia",
                                           today=TODAY)
    assert unread == 3 and enriched.research_unread == 3 and len(enriched.research) == MAX_RESEARCH_DOCS
    assert enriched.research[0].path == "documents/research/zz-tarifs-synthesia.md" and enriched.research[0].on_topic
    lines = render_board_research(enriched.to_payload()["research"])
    assert lines[-1].startswith("- et 3 autre(s) document(s) non listé(s)") and "board_memory_tree" in lines[-1]


def test_the_last_slide_triggers_nothing_and_an_off_topic_note_keeps_its_decision(tmp_path):
    store = FileBoardMemoryStore(tmp_path)
    _write(store, DEFAULT_BOARD_ID, "documents/research/gamma-outil.md",
           "---\ntopic: Gamma (gamma.app) : fonctionnalités et tarifs\nchecked_at: 2026-10-20\nvolatility: high\n---\n")
    _write(store, DEFAULT_BOARD_ID, "documents/research/openai-modeles.md", OLD_OPENAI_NOTE)
    memory = read_board_memory(store, tmp_path, DEFAULT_BOARD_ID)
    slide, _ = with_board_research(memory, store, DEFAULT_BOARD_ID, request="Modifie la dernière diapo", today=TODAY)
    assert slide.research_recency == () and {item.reason for item in slide.research} == {"fresh", "stale"}
    latest, _ = with_board_research(memory, store, DEFAULT_BOARD_ID,
                                    request="Quels sont les derniers modèles d'OpenAI ?", today=TODAY)
    by_path = {item.path.rsplit("/", 1)[-1]: item for item in latest.research}
    assert by_path["openai-modeles.md"].reason == "recency_requested" and by_path["openai-modeles.md"].on_topic
    assert by_path["gamma-outil.md"].action is FreshnessAction.REUSE and not by_path["gamma-outil.md"].on_topic
    head = render_board_research(latest.to_payload()["research"])[0]
    assert "« derniers »" in head and "sujet du tour" in head


async def test_a_new_session_on_the_same_board_makes_the_running_cli_stale(monkeypatch, tmp_path):
    """Reprise QA m7 : comparer le seul Board laisserait le dossier de l'ancienne Session accordé."""

    scope = {"value": ("board_a", "jsess_one")}
    agent = _confined_brain(monkeypatch, tmp_path, ("x", "y"))
    agent.board_scope = lambda: scope["value"]
    await _launch(monkeypatch, agent)
    monkeypatch.setattr(type(agent), "state", property(lambda self: "running"))
    assert not agent.board_scope_stale()
    scope["value"] = ("board_a", "jsess_two")
    assert agent.board_scope_stale()


async def test_a_stale_scope_relaunches_the_foreground_cli_before_the_turn(tmp_path):
    """Reprise QA m7 : `agent_ask` relance (`--resume`) un CLI lancé pour une autre liaison avant de servir le tour."""

    from tests.unit.test_board_brains_control_center import JsonRequest, binding, make_control, trace

    control = make_control(tmp_path)
    entry = await control.board_brains.activate(binding("conv-a"))
    agent = entry.agent
    stale = {"value": True}
    agent.board_scope_stale = lambda: stale["value"]
    starts_before = len(agent.starts)

    def relaunched_once() -> None:
        stale["value"] = False

    original_start = agent.start

    async def start(*, resume: bool = True) -> dict:
        relaunched_once()
        return await original_start(resume=resume)

    agent.start = start
    answered = await control.agent_ask(JsonRequest({"text": "bonjour", "conversation": {"conversation_id": "conv-a"}}))
    assert answered.status == 200 and agent.asked == ["bonjour"]
    assert len(agent.starts) == starts_before + 1 and agent.stops >= 1
    assert trace(tmp_path, "board_brain.relaunched")[-1]["data"]["reason"] == "board_scope"
    # Portée à jour : le tour suivant ne relance rien.
    await control.agent_ask(JsonRequest({"text": "encore", "conversation": {"conversation_id": "conv-a"}}))
    assert len(agent.starts) == starts_before + 1


# ------------------------------------------------------------------ 6. seconde reprise (contre-relecture)

GAMMA_DOC = Path(__file__).parents[1] / "fixtures" / "research" / "gamma-outil.md"
#: Les 12 demandes rejouées par la contre-relecture sur le bac QA (`scratchpad\v12s03cr\replay.py`).
REPLAY_REQUESTS = (
    "Rappelle-moi les prix de Synthesia et HeyGen", "Modifie la dernière diapo",
    "Quels sont les derniers prix de Gamma ?", "Les dernières tendances de l'IA vidéo",
    "Quel est le prix actuel de Synthesia en 2026 ?", "Mets à jour la slide sur les outils vidéo",
    "Est-ce que le deck est à jour ?", "latest pricing for gamma", "Parle-moi de l'IA",
    "Que dit la recherche sur les avatars ?", "Gamma coûte combien aujourd'hui ?", "les tarifs de GAMMA actuellement",
)


def _qa_board(tmp_path: Path) -> FileBoardMemoryStore:
    store = FileBoardMemoryStore(tmp_path)
    _write(store, DEFAULT_BOARD_ID, "documents/research/gamma-outil.md", GAMMA_DOC.read_text(encoding="utf-8"))
    _write(store, DEFAULT_BOARD_ID, "documents/research/outils-video-presentation-ia-2026.md",
           LONG_FRONT_MATTER.read_text(encoding="utf-8"))
    return store


def test_a_durable_403_is_not_retried_at_every_turn_on_the_real_gamma_document(tmp_path):
    """F1 : le vrai document Gamma (gamma.app/pricing en 403 le 27/10), 12 demandes le jour même : aucun
    rafraîchissement ; la source est signalée « non vérifiable » ; on ne la réessaie qu'au-delà de 30 j."""

    store = _qa_board(tmp_path)
    memory = read_board_memory(store, tmp_path, DEFAULT_BOARD_ID)
    for request in REPLAY_REQUESTS:
        enriched, _ = with_board_research(memory, store, DEFAULT_BOARD_ID, request=request, today=TODAY)
        gamma = next(item for item in enriched.research if item.path.endswith("gamma-outil.md"))
        # La source en 403 n'est jamais redemandée ; seules deux sources vérifiées le 10/10 le sont, et seulement
        # quand le tour réclame l'actualité de Gamma (7 j tolérés) : c'est la règle d'actualité, pas une boucle.
        assert "https://gamma.app/pricing" not in gamma.stale_sources, request
        assert gamma.unverifiable_sources == ("https://gamma.app/pricing",), request
        recency_on_gamma = gamma.on_topic and bool(recency_terms(request))
        assert (gamma.action is FreshnessAction.REUSE) is not recency_on_gamma, request
        lines = "\n".join(render_board_research(enriched.to_payload()["research"]))
        if gamma.on_topic:
            assert "non vérifiable pour l'instant" in lines and "dites-le si la donnée compte" in lines
    # Le même document juste rafraîchi (les deux sources du 10/10 relues aujourd'hui, le 403 toujours en échec) :
    # « réutiliser » pour les 12 demandes, sans aucun rafraîchissement.
    refreshed = GAMMA_DOC.read_text(encoding="utf-8").replace("checked: 2026-10-10", "checked: 2026-10-27")
    _write(store, DEFAULT_BOARD_ID, "documents/research/gamma-outil.md", refreshed)
    for request in REPLAY_REQUESTS:
        enriched, _ = with_board_research(memory, store, DEFAULT_BOARD_ID, request=request, today=TODAY)
        gamma = next(item for item in enriched.research if item.path.endswith("gamma-outil.md"))
        assert gamma.action is FreshnessAction.REUSE and gamma.stale_count == 0, request
        lines = "\n".join(render_board_research(enriched.to_payload()["research"]))
        assert "rafraîchir seulement" not in lines and "tout revérifier" not in lines, request
    meta, _ = parse_front_matter(GAMMA_DOC.read_text(encoding="utf-8"))
    pricing = meta.sources[0]
    assert pricing.failed and pricing.tried_at == TODAY and pricing.checked_at is None
    assert "https://gamma.app/pricing" in decide(meta, today=date(2026, 11, 20)).unverifiable_sources  # 24 j
    assert "https://gamma.app/pricing" in decide(meta, today=date(2026, 11, 28)).stale_sources  # 32 j : réessai


def test_a_successful_read_after_a_failed_try_counts_again():
    meta, _ = parse_front_matter("---\ntopic: Gamma\nchecked_at: 2026-10-27\nvolatility: high\nsources:\n"
                                 "  - https://gamma.app/pricing | checked: 2026-10-27 | tried: 2026-10-20 | status: failed\n"
                                 "  - https://autre | checked: 2026-10-27\n---\n")
    decision = decide(meta, today=TODAY)
    assert decision.action is FreshnessAction.REUSE and decision.unverifiable_sources == ()


def test_editing_wording_and_generic_words_do_not_touch_unrelated_documents(tmp_path):
    """F2 : « à jour » n'est plus un déclencheur ; « prix », « outils », « slide »… ne rapprochent rien."""

    for request in ("Mets à jour la slide sur les outils vidéo", "Fais une mise à jour de la diapo 3",
                    "Est-ce que le deck est à jour ?", "mettre à jour le plan"):
        assert recency_terms(request) == (), request
    store = _qa_board(tmp_path)
    memory = read_board_memory(store, tmp_path, DEFAULT_BOARD_ID)
    enriched, _ = with_board_research(memory, store, DEFAULT_BOARD_ID,
                                      request="Quel est le prix actuel de Synthesia en 2026 ?", today=TODAY)
    by_name = {item.path.rsplit("/", 1)[-1]: item for item in enriched.research}
    assert not by_name["gamma-outil.md"].on_topic
    assert by_name["outils-video-presentation-ia-2026.md"].on_topic
    for request in ("le prix des outils", "comparaison des tarifs pour la présentation", "une slide sur les offres"):
        assert not matches_topic(request, "gamma-outil", "Gamma (gamma.app) : fonctionnalités et tarifs",
                                 "outil de présentations par IA, offre et prix des formules"), request
    for word in ("prix", "outils", "tarif", "comparaison", "presentation", "slide"):
        assert word in TOPIC_STOPWORDS


@pytest.mark.parametrize(("request_text", "texts", "expected"), [
    ("Parle-moi de l'IA", ("Outils IA", "ia-video"), True),
    ("Quoi de neuf sur les LLM ?", ("Modèles de langage", "llm-2026"), True),
    ("les derniers prix de Synthesia", ("Gamma : fonctionnalités et tarifs", "gamma-outil"), False),
    ("Les tarifs de Synthesia", ("Prix de Synthesia",), True),
    ("la marge de l'IA", ("Diagramme", "paiement"), False),  # « ia » n'est pas un morceau de « diagramme »
    ("j'ai une question", ("AI tools", "ai"), False),        # « ai » de « j'ai » n'est pas un sujet
])
def test_short_topics_match_on_whole_words(request_text, texts, expected):
    assert matches_topic(request_text, *texts) is expected


@pytest.mark.parametrize("request_text", [
    "dernière chose : change le titre", "en dernier, ajoute une image", "le dernier mot", "current slide",
    "show the current slide", "la toute dernière diapositive",
])
def test_conversation_and_deck_ordinals_are_not_recency(request_text):
    assert recency_terms(request_text) == ()


@pytest.mark.parametrize(("checked", "failed"), [
    ("2026-10-27T11:35:12.450Z", False), ("2026-10-27 (vidéo regardée)", False), ("2026-10-27 (vide)", True),
    ("2026-10-27 (HTTP 403)", True), ("2026-10-27 (échec)", True), ("2026-10-27 12:404", False),
])
def test_failure_words_are_whole_words_and_timestamps_are_not_http_codes(checked, failed):
    meta, _ = parse_front_matter(f"---\ntopic: X\nchecked_at: 2026-10-27\nsources:\n  - https://a | checked: {checked}\n---\n")
    assert meta.sources[0].failed is failed


def test_an_unclosed_header_is_judged_the_same_whatever_the_file_size(tmp_path):
    store = FileBoardMemoryStore(tmp_path)
    head = "---\ntopic: Sujet\nchecked_at: 2026-10-26\nvolatility: low\nsources:\n  - https://a | checked: 2026-10-26\n"
    _write(store, DEFAULT_BOARD_ID, "documents/research/petit.md", head + "corps sans fin\n")
    _write(store, DEFAULT_BOARD_ID, "documents/research/grand.md", head + "corps sans fin\n" * 2000)
    memory = read_board_memory(store, tmp_path, DEFAULT_BOARD_ID)
    enriched, _ = with_board_research(memory, store, DEFAULT_BOARD_ID, request="le sujet", today=TODAY)
    decisions = {item.path.rsplit("/", 1)[-1]: (item.action, item.reason, item.topic, item.problem is not None)
                 for item in enriched.research}
    assert decisions["petit.md"][:3] == decisions["grand.md"][:3] == (
        FreshnessAction.FULL_REFRESH, "freshness_unknown", "Sujet")
    assert decisions["petit.md"][3] and decisions["grand.md"][3]


def test_nested_yaml_sources_and_block_scalars_are_read():
    text = "\n".join(["---", "topic: >", "  Prix de", "  Synthesia", "checked_at: 2026-10-27", "volatility: high",
                      "sources:", "  - url: https://a", "    date: 2026-01-01", "    checked: 2025-01-01",
                      "  - url: https://b", "    checked: 2026-10-20", "    tried: 2026-10-26", "    status: failed",
                      "  - https://c | checked: 2026-10-27", "---", "corps"])
    meta, problem = parse_front_matter(text)
    assert problem is None and meta.topic == "Prix de Synthesia"
    assert [(s.ref, s.checked_at, s.failed, s.tried_at) for s in meta.sources] == [
        ("https://a", date(2025, 1, 1), False, None), ("https://b", date(2026, 10, 20), True, date(2026, 10, 26)),
        ("https://c", TODAY, False, None)]
    decision = decide(meta, today=TODAY)
    assert decision.stale_sources == ("https://a",) and decision.unverifiable_sources == ("https://b",)


def test_the_brain_is_told_to_refresh_only_documents_on_the_topic_of_the_turn():
    off = ResearchDocStatus.from_decision(
        "documents/research/a.md", ResearchMetadata(topic="Autre"),
        FreshnessDecision(FreshnessAction.PARTIAL_REFRESH, "partially_stale", stale_sources=("https://x",)))
    on = ResearchDocStatus.from_decision(
        "documents/research/b.md", ResearchMetadata(topic="Sujet"),
        FreshnessDecision(FreshnessAction.PARTIAL_REFRESH, "partially_stale", stale_sources=("https://y",)),
        on_topic=True)
    lines = render_board_research({"documents": [off.to_payload(), on.to_payload()]})
    assert "a.md" in lines[1] and "hors sujet du tour, aucune action" in lines[1] and "rafraîchir" not in lines[1]
    assert "b.md" in lines[2] and "rafraîchir seulement" in lines[2] and "https://y" in lines[2]


def test_the_source_holds_no_invisible_byte_order_mark():
    from jarvis.domain import research_freshness

    source = Path(research_freshness.__file__).read_text(encoding="utf-8")
    assert chr(0xFEFF) not in source and chr(0x2019) not in source
    meta, _ = parse_front_matter(chr(0xFEFF) + "---\ntopic: X\nchecked_at: 2026-10-27\n---\n")
    assert meta.topic == "X"

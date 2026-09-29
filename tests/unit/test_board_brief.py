"""Le bloc `board` de Core atteint vraiment la consigne de l'agent (handoff board-session, Slice 08).

Trouvé par la matrice E2E de la Slice 08 : Core joignait `context.board` à
chaque `/api/agent/ask`, mais `build_agent_brief` ne le rendait pas — un CLI
neuf (nouvelle Session) n'était donc hydraté par rien du Board.
"""

from __future__ import annotations

from jarvis.runtime.board_brief import BRIEF_BOARD_SCOPE, render_board_brief
from jarvis.runtime.control_center import build_agent_brief

BOARD = {"board_id": "board_ab", "title": "Recherche", "context_summary": "Veille IA\nlot 2",
         "task_refs": ["task-1", "task-2"], "artifact_refs": ["docs/x.md"], "project_refs": []}


def test_the_brief_carries_the_board_title_summary_and_refs_before_the_request():
    brief = build_agent_brief({"addressing": "addressed", "board": BOARD}, "où en est-on ?")
    lines = brief.splitlines()
    board_line = next(i for i, line in enumerate(lines) if line.startswith("Board : « Recherche »"))
    assert BRIEF_BOARD_SCOPE in lines[board_line]
    assert "Résumé du Board : Veille IA\nlot 2" in brief
    assert "Tâches du Board : task-1, task-2" in brief and "Artefacts du Board : docs/x.md" in brief
    assert "Projets du Board" not in brief, "empty lists are not rendered"
    assert board_line < lines.index("[Demande]")


def test_no_board_block_no_board_line():
    assert "Board :" not in build_agent_brief({"addressing": "addressed"}, "salut")
    assert render_board_brief(None) == [] and render_board_brief({"title": ""}) == []
    assert render_board_brief("x") == []


def test_omitted_refs_are_announced_and_values_are_bounded():
    lines = render_board_brief({**BOARD, "title": "T" * 500, "omitted_refs": 3, "task_refs": ["r" * 900]})
    assert len(lines[0]) < 120 + len(BRIEF_BOARD_SCOPE) + 20
    assert any("3 référence(s)" in line for line in lines)
    assert all(len(line) < 1700 for line in lines)
    assert not any("référence(s)" in line for line in render_board_brief({**BOARD, "omitted_refs": True}))

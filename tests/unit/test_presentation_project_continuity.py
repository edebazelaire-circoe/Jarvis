"""Continuité d'un projet Presentation (V1.2, Slice 02 ; `docs/boards.md` › *Presentation project digest*).

- la convention `summary.md` (sections stables, gabarit compact) et le comportement du cerveau (mise à jour
  conditionnelle, reprise sans « où en étions-nous ») vivent dans la consigne `presentation` seulement ;
- un condensé structuré réaliste tient dans le plafond d'hydratation, sans coupe, et revient au tour suivant ;
- `summary.md` absent, illisible, Board archivé : dégradation sûre et dite, aucune écriture tentée à tort ;
- A/B/A : chaque Board retrouve son propre condensé ;
- cycle d'écriture du cerveau par la vraie pile : `create`, lecture → `sha256`, `replace` conditionnel,
  `memory_conflict` sur empreinte périmée, relecture puis fusion ;
- restes de la Slice 01 (I-001) : refus du hook pour `Task` et les variantes du marqueur `[coder]`.
"""

from __future__ import annotations

import json

import pytest

from jarvis.adapters.board_memory_store import FileBoardMemoryStore
from jarvis.core.board_hydration import read_board_memory
from jarvis.domain.agent_capabilities import PRESENTATION_CAPABILITIES, UNCONFINED
from jarvis.domain.brain_context import MAX_BRAIN_BOARD_SUMMARY_BYTES, BrainBoardContext
from jarvis.domain.subagent_roles import ROLE_UNAVAILABLE_CODE
from jarvis.domain.workspace_board import DEFAULT_BOARD_ID
from jarvis.runtime import claude_local, routing_hook
from jarvis.runtime.board_brief import BOARD_SUMMARY_BEGIN, BRIEF_MEMORY_EMPTY
from jarvis.runtime.claude_local import (
    BRAIN_PRESENTATION_MEMORY_MARK, BRAIN_PRESENTATION_MEMORY_SECTION, PRESENTATION_SUMMARY_SECTIONS,
    PRESENTATION_SUMMARY_TARGET_BYTES, PRESENTATION_SUMMARY_TEMPLATE, presentation_project_section,
    render_brain_system_prompt,
)
from jarvis.runtime.control_center import build_agent_brief
from tests.fakes.capture_stack import CaptureStack
from tests.unit.test_board_memory_hydration import _next_turn_block, _write, world  # noqa: F401 (fixture)
from tests.unit.test_capture_api_protocol import core
from tests.unit.test_presentation_brain_scope import _decision, _event, _refusals
from tests.unit.test_workspace_inspection_api import build

V1 = "/v1/workspace"

#: Un projet riche, au format de la convention : la mesure qui justifie de garder le plafond à 2 048 octets.
RICH_SUMMARY = """\
# Lancement du programme Circuit 2027
## Finalité
Convaincre le comité de direction de financer le programme Circuit 2027 (décision le 12 novembre).
## Objectifs
- Présentation de 10 minutes, 12 slides, ton sobre et chiffré.
- Une vidéo de 90 secondes pour l'intranet, voix de JARVIS.
- Obtenir un budget de 450 k€ sur deux ans.
## État actuel
Plan en 5 actes validé ; recherche marché faite ; slides 1 à 6 rédigées, 7 à 12 à écrire ; charte reçue.
## Décisions
- 2026-10-27 : public = comité de direction, pas les équipes.
- 2026-10-27 : charte de la marque (bleu nuit, Inter), pas de photo d'illustration.
- 2026-10-28 : chiffres 2025 du rapport annuel, pas ceux du prévisionnel.
- 2026-10-28 : la vidéo reprend les actes 1, 3 et 5 seulement.
## Questions ouvertes
- Montrer la comparaison avec le concurrent principal ? (défaut : non)
- Durée exacte du créneau au comité : 10 ou 15 minutes ?
## Prochaines étapes
- Rédiger les slides 7 à 12 (auteur), puis relecture.
- Valider les chiffres de la slide 9 avec la direction financière.
## Documents clés
- documents/research/marche-2026.md : étude de marché sourcée
- documents/plan.md : plan en 5 actes et storyboard
- presentation/production_brief.md : dossier de production
- missions/m-0007/ : recherche concurrentielle
- Présentation « Circuit 2027 – Comité » (Studio)
"""


def _digest(title: str, purpose: str, step: str) -> str:
    return (f"# {title}\n## Finalité\n{purpose}\n## Objectifs\n- (rien)\n## État actuel\nCadrage.\n"
            f"## Décisions\n- (rien)\n## Questions ouvertes\n- (rien)\n## Prochaines étapes\n- {step}\n"
            "## Documents clés\n- (rien)\n")


# ------------------------------------------------------------------ 1. consigne : presentation seulement


def test_the_convention_is_in_the_presentation_prompt_only():
    prompt = render_brain_system_prompt(PRESENTATION_CAPABILITIES)
    assert prompt.count(BRAIN_PRESENTATION_MEMORY_MARK) == 1 and BRAIN_PRESENTATION_MEMORY_SECTION in prompt
    assert prompt.endswith(BRAIN_PRESENTATION_MEMORY_SECTION)
    for text in (claude_local.BRAIN_SYSTEM_PROMPT, render_brain_system_prompt(UNCONFINED),
                 render_brain_system_prompt(None)):
        assert BRAIN_PRESENTATION_MEMORY_MARK not in text and "## Finalité" not in text
    assert presentation_project_section(UNCONFINED) is None


def test_the_template_lists_the_stable_sections_in_order():
    headings = [line[3:] for line in PRESENTATION_SUMMARY_TEMPLATE.splitlines() if line.startswith("## ")]
    assert tuple(headings) == PRESENTATION_SUMMARY_SECTIONS
    assert "documents/" in PRESENTATION_SUMMARY_TEMPLATE
    assert len(PRESENTATION_SUMMARY_TEMPLATE.encode("utf-8")) < 600
    assert PRESENTATION_SUMMARY_TARGET_BYTES < MAX_BRAIN_BOARD_SUMMARY_BYTES


def test_the_prompt_states_when_how_and_how_to_resume():
    section = BRAIN_PRESENTATION_MEMORY_SECTION
    # Quand : changement significatif, pas chaque phrase ; par le cerveau lui-même.
    assert "changement significatif" in section and "pas à chaque phrase" in section and "sans sous-agent" in section
    # Comment : lecture → empreinte → replace conditionnel ; create si absent ; conflit → relire et fusionner.
    for needle in ("board_memory_read", "board_memory_write", "mode replace", "expected_sha256",
                   "memory_not_found", "mode create", "memory_conflict", "relisez-le"):
        assert needle in section, needle
    # Reprise sans demander où on en était, documents seulement si besoin.
    assert "Ne demandez jamais à l'utilisateur où vous en étiez" in section
    assert "que si la demande en a besoin" in section
    # Robustesse et frontière avec context_summary.
    assert "illisible" in section and "INDISPONIBLE" in section and "board_archived" in section
    assert "context_summary" in section and "jamais une copie de summary.md" in section
    assert "un autre Board" in section
    assert f"moins de {PRESENTATION_SUMMARY_TARGET_BYTES} octets" in section


# ------------------------------------------------------------------ 2. hydratation du condensé structuré


def test_a_rich_structured_digest_fits_the_hydration_cap_without_being_cut(tmp_path):
    assert len(RICH_SUMMARY.encode("utf-8")) <= PRESENTATION_SUMMARY_TARGET_BYTES
    store = FileBoardMemoryStore(tmp_path)
    _write(store, DEFAULT_BOARD_ID, "summary.md", RICH_SUMMARY)
    memory = read_board_memory(store, tmp_path, DEFAULT_BOARD_ID)
    assert memory.summary == RICH_SUMMARY and not memory.summary_clipped
    board = BrainBoardContext(board_id=DEFAULT_BOARD_ID, title="Circuit", board_kind="presentation", memory=memory)
    brief = build_agent_brief({"addressing": "addressed", "board": json.loads(json.dumps(board.to_payload()))},
                              "on continue ?")
    assert "Condensé (summary.md) " in brief and "coupé" not in brief.split(BOARD_SUMMARY_BEGIN)[0][-80:]
    for heading in PRESENTATION_SUMMARY_SECTIONS:
        assert heading in brief.split(BOARD_SUMMARY_BEGIN, 1)[1]


def test_an_absent_digest_is_an_empty_memory_not_a_failure(tmp_path):
    store = FileBoardMemoryStore(tmp_path)
    memory = read_board_memory(store, tmp_path, DEFAULT_BOARD_ID)
    assert memory.summary == "" and memory.summary_error is None and memory.error is None
    board = BrainBoardContext(board_id=DEFAULT_BOARD_ID, title="Neuf", board_kind="presentation", memory=memory)
    brief = build_agent_brief({"addressing": "addressed", "board": json.loads(json.dumps(board.to_payload()))}, "x")
    assert BRIEF_MEMORY_EMPTY in brief


@pytest.mark.parametrize("raw", [b"\xff\xfe\x00\x01binaire", b"# Projet\n\xc3\x28 utf-8 invalide\n"],
                         ids=["binary", "invalid-utf8"])
def test_a_corrupted_digest_degrades_safely_and_is_said(tmp_path, raw):
    store = FileBoardMemoryStore(tmp_path)
    _write(store, DEFAULT_BOARD_ID, "documents/plan.md", "plan")
    (tmp_path / "boards" / DEFAULT_BOARD_ID / "memory" / "summary.md").write_bytes(raw)
    memory = read_board_memory(store, tmp_path, DEFAULT_BOARD_ID)
    assert memory.summary == "" and memory.summary_error == "memory_not_text" and memory.error is None
    assert [entry.path for entry in memory.entries] == ["documents", "documents/plan.md", "summary.md"]
    board = BrainBoardContext(board_id=DEFAULT_BOARD_ID, title="P", board_kind="presentation", memory=memory)
    brief = build_agent_brief({"addressing": "addressed", "board": json.loads(json.dumps(board.to_payload()))}, "x")
    assert "summary.md illisible (memory_not_text)" in brief and BOARD_SUMMARY_BEGIN not in brief


async def test_a_b_a_gives_each_presentation_board_its_own_digest(world):  # noqa: F811
    other = await world.boards.create({"title": "Projet B", "board_kind": "presentation"})
    digest_a = _digest("Projet A", "Former les commerciaux.", "Écrire le plan.")
    digest_b = _digest("Projet B", "Lever des fonds.", "Chercher les chiffres.")
    _write(world.store, DEFAULT_BOARD_ID, "summary.md", digest_a)
    _write(world.store, other.board_id, "summary.md", digest_b)

    assert (await _next_turn_block(world)).memory.summary == digest_a
    await world.boards.switch(other.board_id)
    second = await _next_turn_block(world)
    assert second.memory.summary == digest_b
    assert "Former les commerciaux" not in json.dumps(second.to_payload(), ensure_ascii=False)
    await world.boards.switch(DEFAULT_BOARD_ID)
    back = await _next_turn_block(world)
    assert back.memory.summary == digest_a and "Lever des fonds" not in json.dumps(back.to_payload(),
                                                                                   ensure_ascii=False)


# ------------------------------------------------------------------ 3. cycle d'écriture du cerveau (vraie pile)


async def _write_summary(stack, board_id: str, content: str, mode: str, sha: str | None = None):
    body = {"path": "summary.md", "content": content, "mode": mode, "origin": "brain"}
    if sha is not None:
        body["expected_sha256"] = sha
    status, payload, _, _ = await core(stack, "POST", f"{V1}/boards/{board_id}/memory/write", json=body)
    return status, payload


async def _read_summary(stack, board_id: str):
    return await core(stack, "GET", f"{V1}/boards/{board_id}/memory/read", params={"path": "summary.md"})


async def test_the_brain_write_cycle_creates_then_replaces_conditionally_and_merges_on_conflict(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        board = w.board_b
        status, missing, _, _ = await _read_summary(stack, board)
        assert status == 404 and missing["error"]["code"] == "memory_not_found"

        first = _digest("Projet", "Convaincre le comité.", "Écrire le plan.")
        status, created = await _write_summary(stack, board, first, "create")
        assert status == 201 and created["created"] is True

        _, read, _, _ = await _read_summary(stack, board)
        sha = read["sha256"]
        assert read["text"] == first and len(sha) == 64

        # Un autre écrivain (onglet Dossier, sous-agent) change le condensé entre la lecture et l'écriture.
        theirs = first.replace("- (rien)\n## Questions", "- Public : direction.\n## Questions", 1)
        status, _ = await _write_summary(stack, board, theirs, "replace", sha)
        assert status == 200

        mine = first.replace("Écrire le plan.", "Rédiger les slides 1 à 6.")
        status, refused = await _write_summary(stack, board, mine, "replace", sha)
        assert status == 409 and refused["error"]["code"] == "memory_conflict"
        _, still, _, _ = await _read_summary(stack, board)
        assert still["text"] == theirs, "le remplacement refusé ne touche pas au fichier"

        merged = theirs.replace("Écrire le plan.", "Rédiger les slides 1 à 6.")
        status, done = await _write_summary(stack, board, merged, "replace", still["sha256"])
        assert status == 200 and done["sha256"] != still["sha256"]
        _, final, _, _ = await _read_summary(stack, board)
        assert "Public : direction." in final["text"] and "Rédiger les slides 1 à 6." in final["text"]


async def test_an_archived_board_refuses_the_digest_write_and_keeps_it_readable(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        w = await build(stack)
        before = await _read_summary(stack, w.board_archived)
        for mode, sha in (("create", None), ("replace", None), ("replace", (before[1] or {}).get("sha256"))):
            status, refused = await _write_summary(stack, w.board_archived, _digest("x", "y", "z"), mode, sha)
            assert status == 409 and refused["error"]["code"] == "board_archived", mode
        after = await _read_summary(stack, w.board_archived)
        assert after[0] == before[0] and after[1] == before[1], "lecture permise, rien n'a changé"


# ------------------------------------------------------------------ 4. restes de la Slice 01 (I-001, m1/m2)


@pytest.mark.parametrize(("tool", "description", "prompt"), [
    ("Task", "[general] [coder] Modifier le code", "[general] [coder] Consigne."),
    ("Agent", "[coder] Modifier le code", "Consigne."),
    ("Agent", "[general] [CODER] Modifier le code", "Consigne."),
    ("Agent", "[general] [ coder ] Modifier le code", "Consigne."),
    ("Agent", "Modifier le code", "[general] [coder] Consigne."),
    ("Agent", "[éphémère] [general] [coder] Corriger", "Consigne."),
], ids=["task-tool", "no-profile", "upper-case", "inner-spaces", "prompt-only", "ephemeral-first"])
def test_the_hook_refuses_every_coder_variant_in_presentation(tmp_path, monkeypatch, tool, description, prompt):
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", "presentation")
    event = {**_event(""), "tool_name": tool, "tool_input": {"description": description, "prompt": prompt}}
    output = routing_hook.run(event, tmp_path)
    assert _decision(output) == "deny"
    assert _refusals(tmp_path)[-1]["data"]["code"] == ROLE_UNAVAILABLE_CODE


def test_the_task_tool_still_launches_a_coder_in_full(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", "full")
    event = {**_event("[code] [coder]"), "tool_name": "Task"}
    assert _decision(routing_hook.run(event, tmp_path)) != "deny"

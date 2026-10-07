"""Conscience du Tool Brain dans la consigne de tour de Jarvis (Slice 4) : capacités, mode, intention, bornes.

Preuve d'agent sans modèle : la consigne est déterministe (même bloc, mêmes lignes) ; les traces de modèle réel
sont à S5/S10. Les tests verrouillent ce qu'un modèle lirait : il connaît chaque capacité d'écran, ne conclut pas
à une incapacité, n'appelle pas deux fois (mode délégué), et sait déclarer une intention.
"""

from __future__ import annotations

import asyncio
import re

import pytest

from jarvis.runtime import claude_local
from jarvis.runtime.control_center import build_agent_brief
from jarvis.runtime.mcp_catalog import build_catalog
from jarvis.runtime.mcp_tool_meta import tool_meta
from jarvis.runtime.tool_brain_brief import (
    BRIEF_HEADER, INTENT_TOOL, MAX_BRIEF_BYTES, OWNERSHIP_DIRECT, OWNERSHIP_TOOL_BRAIN, render_tool_brain_brief,
    tool_brain_brief_block, tool_brain_ownership, ui_capability_surface,
)
from jarvis.runtime.tool_brain_choices import UiState, build_manifest

CONTEXT = {"addressing": "addressed"}
#: Formules par lesquelles un modèle nierait une capacité d'écran (français parlé).
DENIALS = re.compile(r"je ne (peux|sais) pas (afficher|montrer|ouvrir)|impossible d'afficher|je n'ai pas accès à l'écran", re.I)


@pytest.fixture(scope="module")
def catalog():
    return asyncio.run(build_catalog())


def brief(ownership):
    return "\n".join(render_tool_brain_brief(tool_brain_brief_block(ownership)))


def test_the_capability_surface_is_exactly_the_s2_manifest_tool_set(catalog):
    manifest = build_manifest(catalog, UiState(None, None, (), None))
    surface = ui_capability_surface()
    names = {name for entry in surface.values() for kind in ("read", "act") for name in entry[kind]}
    assert names == {tool["name"] for tool in manifest["tools"]}
    by_surface = {tool["name"]: tool["surface"] for tool in manifest["tools"]}
    for key, entry in surface.items():
        assert {by_surface[name] for kind in ("read", "act") for name in entry[kind]} == {key}
    irreversible = {name for entry in surface.values() for name in entry["irreversible"]}
    assert irreversible == {tool["name"] for tool in manifest["tools"] if tool["reversibility"] == "irreversible"}


@pytest.mark.parametrize("ownership", [OWNERSHIP_DIRECT, OWNERSHIP_TOOL_BRAIN])
def test_jarvis_is_told_every_ui_capability_and_never_a_false_incapability(ownership):
    text = brief(ownership)
    surface = ui_capability_surface()
    for entry in surface.values():
        for name in (*entry["read"], *entry["act"]):
            assert name in text, name
    assert text.startswith(BRIEF_HEADER) and "Un Tool Brain existe" in text
    assert not DENIALS.search(text)
    assert "ne prétends jamais qu'une d'elles manque" in text
    # G1 fermé par S7 : la navigation web existe, du Tool Brain seul (nommée, jamais déclarée impossible) ; en
    # observation Jarvis la sait absente de ses outils et ne la promet pas ; ce qui est définitif est dit aussi.
    assert "navigation web (Tool Brain seul : " in text
    assert ("n'existe qu'en mode délégué" in text) == (ownership == OWNERSHIP_DIRECT)
    assert "N'existe pas encore" not in text
    assert "scene_archive" in text.split("Définitif :")[1].split(".")[0]


def test_observation_mode_keeps_direct_execution_and_never_asks_for_a_duplicate_call():
    text = brief(OWNERSHIP_DIRECT)
    assert "Mode actuel : observation" in text and "une seule fois par geste" in text
    assert "n'appelle pas les outils d'action" not in text


def test_delegated_mode_forbids_the_normal_direct_ui_calls_and_names_the_explicit_fallback():
    text = brief(OWNERSHIP_TOOL_BRAIN)
    actions = [name for key, entry in ui_capability_surface().items() if key != "browser" for name in entry["act"]]
    rule = text.split("n'appelle pas les outils d'action d'écran (")[1].split(")")[0]
    assert set(rule.split(", ")) == set(actions)  # exactement ses outils d'action, ni lecture ni intention
    assert not any(name.startswith("surface_") for name in rule.split(", "))  # jamais dans ses outils
    assert INTENT_TOOL not in actions and "scene_inspect" not in rule
    assert "la lecture reste à toi" in text
    assert "Repli direct seulement" in text and "dis-le" in text  # repli explicite, jamais silencieux


def test_the_intent_instruction_matches_the_tool_it_names_and_carries_no_layout_vocabulary():
    text = brief(OWNERSHIP_DIRECT)
    line = next(line for line in text.splitlines() if line.startswith("Intention :"))
    meta = tool_meta("jarvis-display", INTENT_TOOL)  # l'outil existe vraiment
    assert meta.ui_surface is None
    for word in ("reveal", "attention", "relevance", "dismiss", "with_speech", "after_speech", "paragraph", "subject"):
        assert word in line
    assert "ni coordonnées ni commande" in line and "jamais où ni comment" in line
    assert "pendant ton tour" in line


@pytest.mark.parametrize("ownership", [OWNERSHIP_DIRECT, OWNERSHIP_TOOL_BRAIN])
def test_the_block_is_deterministic_bounded_and_single_line_entries(ownership):
    first, second = brief(ownership), brief(ownership)
    assert first == second
    assert len(first.encode("utf-8")) <= MAX_BRIEF_BYTES
    assert "\r" not in first and "\n\n" not in first


def test_the_default_ownership_is_observation_until_s8_flips_it():
    assert tool_brain_ownership() == OWNERSHIP_DIRECT == tool_brain_brief_block()["ownership"]
    with pytest.raises(ValueError, match="ownership must be one of"):
        tool_brain_brief_block("whoever")


@pytest.mark.parametrize("junk", [None, "x", {}, {"ownership": "other", "surface": {}}, {"ownership": OWNERSHIP_DIRECT, "surface": []}])
def test_a_missing_or_malformed_block_renders_nothing(junk):
    assert render_tool_brain_brief(junk) == []


def test_the_turn_brief_carries_the_block_only_when_given_and_is_otherwise_unchanged():
    plain = build_agent_brief(CONTEXT, "montre-moi le résultat")
    assert BRIEF_HEADER not in plain
    with_block = build_agent_brief({**CONTEXT, "tool_brain": tool_brain_brief_block()}, "montre-moi le résultat")
    assert BRIEF_HEADER in with_block
    head, tail = with_block.split("[Demande]")
    assert tail == "\nmontre-moi le résultat"
    assert with_block.replace("\n".join(render_tool_brain_brief(tool_brain_brief_block())) + "\n", "") == plain


def test_the_brief_never_asks_jarvis_to_drive_layout_and_the_system_prompt_still_names_the_scene_tools():
    # Garde-fou de dérive : le prompt système d'affichage (empreinte testée ailleurs) reste celui d'avant, le
    # bloc de tour le complète sans le contredire en mode observation.
    assert "scene_inspect" in claude_local.BRAIN_DISPLAY_PROMPT
    assert f"mcp__jarvis-display__{INTENT_TOOL}" in claude_local.DISPLAY_TOOLS  # compté comme affichage, pas comme travail

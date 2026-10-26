"""`remotion_export op=save` sur le vrai protocole MCP (presentation-edition-v1 Slice 03, `docs/export.md` › *Brain*).

Le cerveau ne peut demander qu'une COPIE d'un export terminé, désigné par son `artifact_id`, dans `Documents\\Jarvis` : aucun argument de
chemin, de dossier ni de nom n'existe dans le schéma ; un tour non adressé ne copie rien ; un refus de Core revient avec son code.
"""

from __future__ import annotations

import pytest

from tests.unit.remotion_mcp_world import make_tools, refusal
from tests.unit.test_remotion_mcp_server import call


async def test_an_addressed_turn_copies_the_finished_export_by_its_id_alone(tmp_path):
    tools, core, _ = make_tools(tmp_path, turn=True)
    failed, text = await call(tools, "remotion_export", {"op": "save", "artifact_id": "jart_x", "user_request": "mets-la dans mes documents"})
    assert not failed, text
    assert core.named("document_export") == [("jart_x",)] and core.writes == ["document_export"]
    assert "Copie enregistrée dans Documents\\\\Jarvis\\\\Atelier - video (2).mp4 (nom déjà pris : numéroté" in text


async def test_an_ambient_turn_copies_nothing(tmp_path):
    tools, core, _ = make_tools(tmp_path, turn=False)
    failed, text = await call(tools, "remotion_export", {"op": "save", "artifact_id": "jart_x", "user_request": "copie"})
    assert failed and "remotion_user_turn_required" in text and core.writes == []


@pytest.mark.parametrize("arguments", [
    {"op": "save", "artifact_id": "jart_x", "path": "C:\\Users\\x\\Desktop\\out.txt", "user_request": "copie"},
    {"op": "save", "artifact_id": "jart_x", "destination": "C:\\", "user_request": "copie"},
    {"op": "save", "artifact_id": "jart_x", "file_name": "..\\..\\evil", "user_request": "copie"},
    {"op": "save", "artifact_id": "jart_x", "folder": "Desktop", "user_request": "copie"},
], ids=["path", "destination", "file_name", "folder"])
async def test_no_path_destination_or_name_can_be_sent(tmp_path, arguments):
    tools, core, _ = make_tools(tmp_path, turn=True)
    failed, text = await call(tools, "remotion_export", arguments)
    assert failed and "Arguments inconnus refusés, rien n'a été envoyé" in text and core.calls == []


@pytest.mark.parametrize("artifact_id", [None, "", "C:\\Windows\\win.ini", "../jart_x", "jart_x/../../y", "rj_0123456789ab"])
async def test_an_id_that_is_not_an_artifact_id_is_refused_before_core(tmp_path, artifact_id):
    tools, core, _ = make_tools(tmp_path, turn=True)
    arguments = {"op": "save", "user_request": "copie"}
    if artifact_id is not None:
        arguments["artifact_id"] = artifact_id
    failed, text = await call(tools, "remotion_export", arguments)
    assert failed and "invalid_id" in text and core.writes == []


async def test_a_core_refusal_comes_back_with_its_code(tmp_path):
    tools, core, _ = make_tools(tmp_path, turn=True)
    core.refusals["document_export"] = refusal("export_destination_unsafe", "the export folder is a junction")
    failed, text = await call(tools, "remotion_export", {"op": "save", "artifact_id": "jart_x", "user_request": "copie"})
    assert failed and "export_destination_unsafe" in text and "junction" in text


async def test_a_sub_agent_refused_outside_the_users_turn_is_told_to_stop_and_hand_back(tmp_path):
    """QA S03 B2: the delegated path was refused without saying what to do; the sub-agent then looked for another way."""
    tools, core, _ = make_tools(tmp_path, turn=False)
    for arguments in ({"op": "save", "artifact_id": "jart_x", "user_request": "copie"},
                      {"op": "start", "format": "mp4", "user_request": "exporte"}):
        failed, text = await call(tools, "remotion_export", arguments)
        assert failed and "remotion_user_turn_required" in text
        assert "Si tu es un sous-agent" in text and "n'essaie aucun autre moyen" in text and "le cerveau principal appelle" in text
    failed, text = await call(tools, "remotion_setup", {"op": "install", "user_request": "installe"})
    assert failed and "sous-agent" not in text, "only the export carries the hand-back advice"
    assert core.writes == []


def test_the_brain_prompt_and_the_tool_say_the_main_brain_exports_itself():
    from jarvis.runtime import claude_local, mcp_tool_meta  # noqa: F401
    from jarvis.runtime.remotion_mcp import build_server  # noqa: F401

    prompt = claude_local.BRAIN_REMOTION_PROMPT
    assert "« dans mes documents » : save" in prompt and "start, cancel, save : TOI, dans ce tour, jamais un sous-agent" in prompt
    assert len(prompt.encode("utf-8")) <= 2_600


async def test_an_already_exported_copy_is_said_without_a_new_copy(tmp_path):
    tools, core, _ = make_tools(tmp_path, turn=True)

    async def already(artifact_id):
        core._record("document_export", artifact_id)
        return {"export": {"file_name": "A.mp4", "already_exported": True, "destination": {"display_path": "Documents\\Jarvis\\A.mp4"}}}
    core.document_export = already
    failed, text = await call(tools, "remotion_export", {"op": "save", "artifact_id": "jart_x", "user_request": "copie"})
    assert not failed and "already_exported" in text and "rien n'a été recopié" in text

"""CONTEXT_GLOBAL : le dossier que l'agent gère pour composer son prompt initial (docs/context-global.md)."""
from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.adapters import global_context
from jarvis.adapters.global_context import (
    MANIFEST_NAME,
    ManifestError,
    assemble_global_context,
    load_global_context,
    parse_manifest,
    render_global_context_prompt,
    seed_global_context,
)
from jarvis.domain.prompt_registry import PromptTarget
from jarvis.runtime import claude_local
from jarvis.runtime.claude_local import BRAIN_SYSTEM_PROMPT, ClaudeLocalAgent
from jarvis.runtime.prompt_catalog import conversation_session_name
from jarvis.runtime.prompt_runtime import prompt_channel, resolve_prompt


def _write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_the_versioned_seed_lists_only_files_it_ships():
    seed = global_context.SEED_ROOT
    entries = parse_manifest((seed / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert entries[:4] == ["base_instruction.md", "personnality.md", "mission.md", "user_habits.md"]
    assert all((seed / entry).is_file() for entry in entries)
    # Le reste du dossier existe mais n'est pas chargé.
    assert (seed / "current_task").is_dir() and "todo.md" not in entries


def test_first_start_seeds_the_folder_then_never_again(tmp_path):
    root = tmp_path / "CONTEXT_GLOBAL"
    loaded = load_global_context(root)
    assert loaded.seeded and loaded.problems == ()
    assert loaded.files[0] == "base_instruction.md"
    assert "« Monsieur »" in loaded.text
    # L'agent supprime un fichier et le retire du manifeste : il ne revient pas.
    (root / "mission.md").unlink()
    _write(root, MANIFEST_NAME, "- personnality.md\n")
    again = load_global_context(root)
    assert not again.seeded and again.files == ("personnality.md",)
    assert not (root / "mission.md").exists()
    assert not seed_global_context(root)


def test_files_are_assembled_in_manifest_order_with_their_names(tmp_path):
    _write(tmp_path, "b.md", "deuxième")
    _write(tmp_path, "notes/a.md", "premier")
    _write(tmp_path, MANIFEST_NAME, "# commentaire\nfiles:\n- notes/a.md\n- 'b.md'  # citée\n- notes/a.md\n")
    result = assemble_global_context(tmp_path)
    assert result.files == ("notes/a.md", "b.md")
    assert result.text == "# notes/a.md\npremier\n\n# b.md\ndeuxième"
    assert result.problems == ()


@pytest.mark.parametrize("entry", ["../dehors.md", "C:/Windows/win.ini", "/etc/passwd", "absent.md",
                                   "image.png", MANIFEST_NAME])
def test_a_bad_entry_is_skipped_and_reported_never_read(tmp_path, entry):
    _write(tmp_path.parent, "dehors.md", "secret")
    _write(tmp_path, "image.png", "x")
    _write(tmp_path, "ok.md", "gardé")
    _write(tmp_path, MANIFEST_NAME, f"- {entry}\n- ok.md\n")
    result = assemble_global_context(tmp_path)
    assert result.files == ("ok.md",)
    assert "secret" not in result.text and len(result.problems) == 1


def test_a_manifest_that_is_not_a_list_loads_nothing_and_says_why(tmp_path):
    with pytest.raises(ManifestError):
        parse_manifest("files: [a.md]\n")
    _write(tmp_path, MANIFEST_NAME, "personnalite: a.md\n")
    result = assemble_global_context(tmp_path)
    assert result.text == "" and "ligne 1" in result.problems[0]
    assert "absent" in assemble_global_context(tmp_path / "vide").problems[0]


def test_the_assembled_text_is_capped(tmp_path):
    _write(tmp_path, "long.md", "x" * 5000)
    _write(tmp_path, "suite.md", "jamais lu")
    _write(tmp_path, MANIFEST_NAME, "- long.md\n- suite.md\n")
    result = assemble_global_context(tmp_path, max_chars=1000)
    assert result.truncated and len(result.text) <= 1000
    assert "jamais lu" not in result.text and result.files == ("long.md",)


def test_rules_carry_the_folder_path_and_problems_before_the_content(tmp_path):
    rendered = render_global_context_prompt({"root": str(tmp_path), "text": "# a.md\nbonjour",
                                             "problems": ["b.md : fichier absent"]})
    assert str(tmp_path) in rendered and "JARVIS_GLOBAL_CONTEXT_DIR" in rendered
    assert rendered.index("b.md : fichier absent") < rendered.index("# a.md\nbonjour")
    assert render_global_context_prompt(None) == ""


@pytest.mark.parametrize("tools", [False, True])
@pytest.mark.parametrize("display", [False, True])
@pytest.mark.parametrize("hands", [False, True])
def test_every_conversation_program_carries_the_global_context_last(tmp_path, tools, display, hands):
    invocation = "conversation_" + conversation_session_name(tools=tools, display=display, hands=hands)
    target = PromptTarget("backend", None, "claude", None, None, invocation)
    bare = prompt_channel(resolve_prompt(target), "cli.append_system_prompt")
    value = {"root": str(tmp_path), "text": "# personnality.md\nTu es JARVIS."}
    loaded = prompt_channel(resolve_prompt(target, variables={"global_context": value}), "cli.append_system_prompt")
    assert loaded.startswith(bare) and loaded.endswith("Tu es JARVIS.")


class _FakeProcess:
    pid = 4321
    returncode = 0
    stdin = None

    class _Empty:
        async def readline(self) -> bytes:
            return b""

    stdout = stderr = _Empty()

    async def wait(self) -> int:
        return 0


async def test_the_voice_agent_assembles_grants_and_names_the_folder(tmp_path, monkeypatch):
    launches: list[tuple[list[str], dict]] = []

    async def fake_exec(*args, **kwargs):  # noqa: ANN002, ANN003
        launches.append((list(args), kwargs))
        return _FakeProcess()

    monkeypatch.setattr(claude_local.asyncio, "create_subprocess_exec", fake_exec)
    root = tmp_path / "data" / "CONTEXT_GLOBAL"
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path)
    agent.global_context_dir = root
    await agent.start()

    argv, kwargs = launches[0]
    prompt = argv[argv.index("--append-system-prompt") + 1]
    assert prompt.startswith(claude_local.cli_prompt_argument(BRAIN_SYSTEM_PROMPT, argv[0]).rstrip())
    assert "CONTEXTE GLOBAL" in prompt and "Monsieur" in prompt
    assert str(root) in argv[argv.index("--add-dir") + 1:]
    assert kwargs["env"]["JARVIS_GLOBAL_CONTEXT_DIR"] == str(root)
    assert (root / MANIFEST_NAME).is_file()

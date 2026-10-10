"""Une consigne trop longue part dans un fichier : `CreateProcess` refuse plus de 32 767 caractères."""

from __future__ import annotations

from jarvis.runtime.claude_local import PROMPT_ARGV_LIMIT, append_prompt_args, launched_append_prompt


def test_a_short_prompt_stays_in_the_argument(tmp_path):
    args = append_prompt_args("court", "claude.exe", tmp_path)
    assert args == ["--append-system-prompt", "court"]
    assert launched_append_prompt(args) == "court"


def test_a_long_prompt_goes_through_a_file_and_comes_back_whole(tmp_path):
    text = ("é" * 99 + "\n") * (PROMPT_ARGV_LIMIT // 100 + 50)
    args = append_prompt_args(text, "claude.exe", tmp_path)
    assert args[0] == "--append-system-prompt-file"
    assert sum(len(a) for a in args) < PROMPT_ARGV_LIMIT
    assert launched_append_prompt(args) == text
    assert append_prompt_args(text, "claude.exe", tmp_path) == args


def test_the_studio_program_no_longer_rides_the_command_line(tmp_path):
    from jarvis.domain.prompt_registry import PromptTarget
    from jarvis.runtime.prompt_runtime import prompt_channel, resolve_prompt

    resolution = resolve_prompt(
        PromptTarget("backend", None, "claude", None, None, "conversation_tools_display_studio_barehands_session"),
        variables={"global_context": ""})
    args = append_prompt_args(prompt_channel(resolution, "cli.append_system_prompt"), "claude.exe", tmp_path)
    assert args[0] == "--append-system-prompt-file"

"""Control Center of the tested checkout with a Claude CLI isolated from the user's own MCP servers (Slice 13 benchmark harness).

Precedent: tasks/jarvis-board-memory-workspace-inspector/slices/09-e2e-rollout/evidence/run_cc_strict.py.
`--strict-mcp-config`: only Jarvis's own `--mcp-config` servers are mounted. `--chrome` removed: the Chrome extension is not a Jarvis
server. No browser tab is opened. Nothing else changes (prompts, tools, hooks).
"""
import asyncio
import sys

real = asyncio.create_subprocess_exec


async def spawn(program, *args, **kwargs):
    if "claude" in str(program).lower().rsplit("\\", 1)[-1].rsplit("/", 1)[-1]:
        args = ("--strict-mcp-config", *[a for a in args if a != "--chrome"])
    return await real(program, *args, **kwargs)


asyncio.create_subprocess_exec = spawn
# Never open a tab of this throw-away Control Center in the user's default browser (`jarvis.app` calls `webbrowser.open(url)` at start):
# the first benchmark runs did, which put stray Jarvis tabs on the user's desktop.
import webbrowser  # noqa: E402

webbrowser.open = lambda *args, **kwargs: True
sys.argv = ["jarvis", "control-center"]
from jarvis.app import main  # noqa: E402  (after the patch on purpose)

main()

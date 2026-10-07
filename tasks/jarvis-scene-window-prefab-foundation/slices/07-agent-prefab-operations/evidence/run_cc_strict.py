"""Lance le Control Center du worktree avec un CLI Claude isolé des serveurs MCP de l'utilisateur (harnais de trace, repris de board-memory S09).

`--strict-mcp-config` : seuls les `--mcp-config` de Jarvis sont montés (pas `jarvis-drive`, réglage personnel).
`--chrome` retiré : l'extension Chrome n'est pas un serveur de Jarvis. Rien d'autre ne change (prompt, outils).
"""
import asyncio, sys
real = asyncio.create_subprocess_exec

async def spawn(program, *args, **kwargs):
    if "claude" in str(program).lower().rsplit("\\", 1)[-1].rsplit("/", 1)[-1]:
        args = ("--strict-mcp-config", *[a for a in args if a != "--chrome"])
    return await real(program, *args, **kwargs)

asyncio.create_subprocess_exec = spawn
sys.argv = ["jarvis", "control-center"]
from jarvis.app import main
main()

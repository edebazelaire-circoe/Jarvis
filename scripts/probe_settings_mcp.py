"""Preuve de bout en bout : le cerveau éteint vraiment Bare Hands par MCP.

Se lance contre le **vrai** Control Center qui tourne (127.0.0.1:17654) et le
**vrai** serveur MCP, parlé en stdio par un vrai client MCP — pas un faux
serveur, pas un appel de fonction en direct. Ce que ce script constate est ce
que le cerveau constaterait.

    .venv\\Scripts\\python.exe scripts\\probe_settings_mcp.py

Il remet l'interrupteur dans son état de départ avant de sortir.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys

import aiohttp

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASE = "http://127.0.0.1:17654"


async def read_switch(session: aiohttp.ClientSession) -> bool:
    async with session.get(BASE + "/api/barehands") as response:
        body = await response.json(content_type=None)
    return bool(body.get("enabled"))


async def main() -> int:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "jarvis", "console-mcp"],
        env={
            **os.environ,
            "JARVIS_CONTROL_CENTER_HOST": "127.0.0.1",
            "JARVIS_CONTROL_CENTER_PORT": "17654",
            "JARVIS_RUNTIME_DIR": str(ROOT / "runtime"),
        },
        cwd=str(ROOT),
    )

    async with aiohttp.ClientSession() as http:
        started = await read_switch(http)
        print(f"[1] Interrupteur au départ, lu sur le vrai serveur : enabled={started}")

        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as mcp:
                await mcp.initialize()
                listed = (await mcp.list_tools()).tools
                names = [tool.name for tool in listed]
                print(f"[2] Outils réellement exposés par le serveur MCP : {names}")
                assert names == ["settings_describe", "settings_get", "settings_set"], names

                shown = await mcp.call_tool("settings_describe", {"category": "hands"})
                print("[3] settings_describe(hands) :")
                print("    " + "\n    ".join(shown.content[0].text.splitlines()[:4]))
                assert shown.isError is False

                print("[4] Appel : settings_set(barehands.enabled, false)")
                result = await mcp.call_tool(
                    "settings_set", {"option_id": "barehands.enabled", "value": False}
                )
                assert result.isError is False, result.content[0].text
                payload = json.loads(result.content[0].text)
                print(f"    -> {json.dumps(payload, ensure_ascii=False)}")

                after = await read_switch(http)
                print(f"[5] Interrupteur relu sur le vrai serveur : enabled={after}")
                assert after is False, "l'interrupteur n'est pas retombé"
                assert payload["after"] is False and payload["changed"] is True

                print("[6] Rallumage par le même outil (il n'a pas disparu avec l'extinction)")
                back = await mcp.call_tool(
                    "settings_set", {"option_id": "barehands.enabled", "value": True}
                )
                assert back.isError is False, back.content[0].text
                assert await read_switch(http) is True

                # Un réglage hors de Bare Hands, pour montrer que la surface
                # n'est pas taillée pour un seul interrupteur.
                voice = await mcp.call_tool("settings_get", {"option_ids": ["openai.voice", "scene.enabled"]})
                print(f"[7] settings_get(openai.voice, scene.enabled) : {voice.content[0].text[:200]}")
                assert voice.isError is False

        final = await read_switch(http)
        if final != started:
            async with http.post(BASE + "/api/barehands", json={"enabled": started}) as response:
                await response.read()
        print(f"[8] Interrupteur remis comme au départ : enabled={await read_switch(http)}")

    print("\nPREUVE OK : un outil MCP a éteint puis rallumé Bare Hands sur le vrai Control Center.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

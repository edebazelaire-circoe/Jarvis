"""Appelle le vrai serveur display-mcp (config écrite par le vrai code) hors modèle : list_tools + refus."""
import asyncio, json, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
cfg = json.load(open(sys.argv[1], encoding="utf-8"))["mcpServers"]["jarvis-display"]
assert cfg["env"]["JARVIS_CORE_PORT"] not in ("", "17653", "17654")
async def main():
    p = StdioServerParameters(command=cfg["command"], args=cfg["args"], env=cfg["env"])
    async with stdio_client(p) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = (await s.list_tools()).tools
            raw = json.dumps([t.model_dump(exclude_none=True) for t in tools], ensure_ascii=False)
            print("tools", len(tools), [t.name for t in tools])
            print("title keys in inputSchema:", raw.count('"title"'))
            await s.call_tool("scene_inspect", {})
            for name, args in [("scene_archive", {"object_ids": ["courses", "zzz-inconnu"]}),
                               ("scene_pin", {"select": {"constellation": {"object_id": "zzz-inconnu"}}, "pinned": True}),
                               ("scene_move", {"object_ids": ["orion"], "dx": 0, "dy": 0})]:
                res = await s.call_tool(name, args)
                txt = "".join(c.text for c in res.content if c.type == "text")
                print(f"\n## {name} {json.dumps(args)} isError={res.isError} structured={res.structuredContent is not None}\n{txt}")
asyncio.run(main())

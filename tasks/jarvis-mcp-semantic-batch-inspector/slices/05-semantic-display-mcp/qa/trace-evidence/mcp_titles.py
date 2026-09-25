import asyncio, json, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
cfg = json.load(open(sys.argv[1], encoding="utf-8"))["mcpServers"]["jarvis-display"]
async def main():
    async with stdio_client(StdioServerParameters(command=cfg["command"], args=cfg["args"], env=cfg["env"])) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tot = 0
            for t in (await s.list_tools()).tools:
                i = json.dumps(t.inputSchema, ensure_ascii=False, separators=(",", ":"))
                o = json.dumps(t.outputSchema or {}, ensure_ascii=False)
                b = len(t.name.encode()) + len((t.description or "").encode()) + len(i.encode()); tot += b
                print(f"{t.name:22} in_title={i.count(chr(34)+'title'+chr(34))} out_title={o.count(chr(34)+'title'+chr(34))} outSchema={t.outputSchema is not None} ann={t.annotations is not None} bytes={b}")
            print("total model_visible_bytes", tot)
asyncio.run(main())

import json, sys, collections
stream, bodies = sys.argv[1], sys.argv[2]
for l in open(stream, encoding="utf-8"):
    e = json.loads(l)
    if e.get("type") == "system" and e.get("subtype") == "init":
        print("init mcp_servers:", e.get("mcp_servers"))
        t = [x for x in e.get("tools", []) if x.startswith("mcp__")]
        c = collections.Counter(x.split("__")[1] for x in t); print("init mcp tools per server:", dict(c))
        print("  ", sorted(t))
    elif e.get("type") == "result": print("result:", e.get("subtype"), "cost", e.get("total_cost_usd"), e.get("result"))
if bodies != "-":
    rows = [json.loads(l) for l in open(bodies, encoding="utf-8")]
    b = [r for r in rows if r["path"].startswith("/v1/messages") and any((t.get("name") or "").startswith("mcp__") for t in r["body"].get("tools") or [])][-1]["body"]
    tools = b["tools"]; per = collections.defaultdict(list)
    for t in tools:
        n = t.get("name", "")
        if n.startswith("mcp__"): per[n.split("__")[1]].append(t)
    for srv, ts in per.items():
        short = sum(len((t["name"].split("__",2)[2] + t.get("description","") + json.dumps(t.get("input_schema"), ensure_ascii=False, separators=(",",":"))).encode()) for t in ts)
        keys = sorted({k for t in ts for k in t})
        print(f"body {srv}: {len(ts)} tools, bytes(short name+desc+compact schema)={short}, keys={keys}")
    raw = json.dumps([t for t in tools if t['name'].startswith('mcp__jarvis-display')])
    for w in ("outputSchema", "annotations", "readOnlyHint", "destructiveHint", "structuredContent"): print(" ", w, w in raw)

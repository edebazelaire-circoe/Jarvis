import json, sys
S = sys.argv[1]
res = {}
for v in ("old", "new"):
    bodies = [json.loads(l) for l in open(f"{S}/run-{v}/bodies.jsonl", encoding="utf-8")]
    raw = open(f"{S}/run-{v}/bodies.jsonl", encoding="utf-8").read()
    main = [b["body"] for b in bodies if any(t.get("name", "").startswith("mcp__") for t in b["body"].get("tools") or [])]
    last = main[-1]
    tools = [t for t in last["tools"] if t["name"].startswith("mcp__")]
    keysets = sorted({tuple(sorted(t)) for t in tools})
    uses = {}
    results = []
    for m in last["messages"]:
        if not isinstance(m.get("content"), list):
            continue
        for c in m["content"]:
            if c.get("type") == "tool_use":
                uses[c["id"]] = c["name"].split("__")[-1]
            if c.get("type") == "tool_result":
                content = c["content"]
                text = content if isinstance(content, str) else "".join(x.get("text", "") for x in content if x.get("type") == "text")
                results.append((uses[c["tool_use_id"]], c.get("is_error", False), text))
    res[v] = dict(n_requests=len(bodies), n_main=len(main), tool_count=len(tools), keysets=keysets,
                  leaks={k: (k in raw) for k in ("outputSchema", "output_schema", "annotations", "readOnlyHint", "destructiveHint", "idempotentHint", "structuredContent")},
                  results=results)
    print(f"== {v}: requests={len(bodies)} main={len(main)} mcp_tools={len(tools)} tool_def_keys={keysets}")
    print("   leaks in any request body:", res[v]["leaks"])
print()
print(f"{'tool':22} {'old_B':>7} {'new_B':>7}  old_head | new_head")
for (n, eo, to), (_, en, tn) in zip(res["old"]["results"], res["new"]["results"]):
    print(f"{n:22} {len(to.encode()):7} {len(tn.encode()):7}  err={eo}/{en}  {to[:70]!r} | {tn[:70]!r}")
json.dump({v: [[n, e, t] for n, e, t in res[v]["results"]] for v in res}, open(f"{S}/results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

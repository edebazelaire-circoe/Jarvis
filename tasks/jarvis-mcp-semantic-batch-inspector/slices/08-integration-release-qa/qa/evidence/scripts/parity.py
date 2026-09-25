"""Inspector (Control Center API) vs what the live CLI reports (system/init) and what the model receives (request bodies)."""
import glob, json, os, sys, urllib.request
S = os.path.dirname(os.path.abspath(__file__))
def get(path): return json.loads(urllib.request.urlopen("http://127.0.0.1:17685" + path, timeout=30).read())
lst = get("/api/mcp/tools")
api = {}
for t in lst["tools"]: api.setdefault(t["server"], []).append(t["name"])
states = {s["server"]: s["availability"] for s in lst["servers"]}
out = {"api_servers": {s: {"count": len(v), "state": states[s].get("state"), "advertised": states[s].get("advertised")} for s, v in api.items()}}
# 1. system/init of every CC brain launch (fake endpoint) and of the real brain (phase A)
inits = []
for f in sorted(glob.glob(os.path.join(S, "wrap", "stream-*.jsonl"))):
    for l in open(f, encoding="utf-8", errors="replace"):
        try: e = json.loads(l)
        except ValueError: continue
        if e.get("type") == "system" and e.get("subtype") == "init":
            inits.append((os.path.basename(f), e)); break
real = json.load(open(os.path.join(S, "system-init.json"), encoding="utf-8"))
def by_server(tools):
    d = {}
    for x in tools:
        if x.startswith("mcp__jarvis-"): d.setdefault(x.split("__")[1], []).append(x.split("__", 2)[2])
    return d
res = []
for name, e in inits:
    b = by_server(e["tools"])
    res.append({"launch": name, "servers": {m["name"]: m["status"] for m in e["mcp_servers"]},
                "per_server": {s: {"cli": len(v), "api": len(api.get(s, [])), "names_equal": sorted(v) == sorted(api.get(s, []))} for s, v in b.items()}})
res.append({"launch": "real brain (phase A, brain8.py)", "servers": {m["name"]: m["status"] for m in real["mcp_servers"]},
            "per_server": {s: {"cli": len(v), "api": len(api.get(s, [])), "names_equal": sorted(v) == sorted(api.get(s, []))} for s, v in real["mcp_tools_by_server"].items()}})
out["system_init_vs_api"] = res
# 2. definitions the model received (fake endpoint request bodies) vs the inspector detail
defs = {}
for l in open(os.path.join(S, "fake-bodies.jsonl"), encoding="utf-8"):
    b = json.loads(l); b = b.get("body", b)
    for t in b.get("tools", []):
        if t.get("name", "").startswith("mcp__jarvis-"): defs[t["name"]] = t
cmp = []
for q, t in sorted(defs.items()):
    _, server, name = q.split("__", 2)
    d = get(f"/api/mcp/tools/{server}/{name}")
    d = d.get("tool", d)
    cmp.append({"tool": q, "keys": sorted(t.keys()), "input_schema_equal": t.get("input_schema") == d.get("input_schema"),
                "description_equal": t.get("description") == d.get("description"),
                "bytes": len((name + t["description"] + json.dumps(t["input_schema"], ensure_ascii=False, separators=(",", ":"))).encode()),
                "api_context_bytes": d.get("context_bytes")})
out["model_definitions_vs_inspector"] = {"count": len(cmp), "all_schema_equal": all(c["input_schema_equal"] for c in cmp),
    "all_description_equal": all(c["description_equal"] for c in cmp), "key_sets": sorted({tuple(c["keys"]) for c in cmp}),
    "bytes_equal_context_bytes": all(c["bytes"] == c["api_context_bytes"] for c in cmp), "rows": cmp}
raw = open(os.path.join(S, "fake-bodies.jsonl"), encoding="utf-8").read()
out["forbidden_strings_in_bodies"] = {k: (k in raw) for k in ("outputSchema", "output_schema", "readOnlyHint", "destructiveHint", "idempotentHint", "annotations")}
json.dump(out, open(os.path.join(S, "parity.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps({k: v for k, v in out.items() if k != "model_definitions_vs_inspector"}, ensure_ascii=False, indent=1))
print(json.dumps({k: v for k, v in out["model_definitions_vs_inspector"].items() if k != "rows"}, ensure_ascii=False))
for c in cmp:
    if not (c["input_schema_equal"] and c["description_equal"] and c["bytes"] == c["api_context_bytes"]): print("MISMATCH", c)
# The CLI rewrites U+2026 "…" to "..." (same byte count) in what it sends; compare modulo that rewrite.
def norm(x): return json.loads(json.dumps(x, ensure_ascii=False).replace("…", "..."))
eq = []
for q, t in sorted(defs.items()):
    _, server, name = q.split("__", 2)
    d = get(f"/api/mcp/tools/{server}/{name}"); d = d.get("tool", d)
    eq.append((q, norm(d["input_schema"]) == t["input_schema"], norm(d["description"]) == t["description"],
               "…" in json.dumps(d["input_schema"], ensure_ascii=False) + d["description"], "…" in json.dumps(t, ensure_ascii=False)))
out["modulo_ellipsis"] = {"all_equal": all(a and b for _, a, b, _, _ in eq), "tools_with_ellipsis_in_catalog": [q for q, _, _, c, _ in eq if c],
                          "ellipsis_reaching_model": any(m for *_, m in eq)}
json.dump(out, open(os.path.join(S, "parity.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("modulo_ellipsis", out["modulo_ellipsis"])

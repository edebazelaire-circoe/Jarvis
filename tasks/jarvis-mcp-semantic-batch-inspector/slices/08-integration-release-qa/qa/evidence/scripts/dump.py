import json,sys
for l in open(sys.argv[1],encoding="utf-8"):
    r=json.loads(l); print("==",r["text"],r["rev_before"],"->",r["rev_after"],"dur",r["duration_ms"],"cost",r["cost"])
    for e in r["events"]:
        m=e.get("message") or {}
        if e.get("type")=="result": print("  RESULT", e.get("subtype"), "num_turns", e.get("num_turns"), "usage", {k:v for k,v in (e.get("usage") or {}).items() if "tokens" in k})
        if e.get("type") in("assistant","user") and isinstance(m.get("content"),list):
            for c in m["content"]:
                if c.get("type")=="tool_use": print("  USE",c["name"],json.dumps(c["input"],ensure_ascii=False))
                elif c.get("type")=="tool_result":
                    ct=c.get("content"); t=ct if isinstance(ct,str) else "".join(x.get("text","") for x in ct if x.get("type")=="text")
                    kinds=[x.get("type") for x in ct] if isinstance(ct,list) else "str"
                    print("  RES err=%s %dB blocks=%s tur_keys=%s\n     %s"%(c.get("is_error"),len(t.encode()),kinds,sorted((e.get("tool_use_result") or {}) if isinstance(e.get("tool_use_result"),dict) else []),t[:1500]))
                elif c.get("type")=="text": print("  TXT",c["text"])

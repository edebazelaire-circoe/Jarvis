"""Résume la sortie de `plan_b1.py` en `b1-keyboard.json` (une ligne par section)."""
import json, sys

d = json.load(open(sys.argv[1], encoding="utf-8"))
acts = {a.get("id"): a for a in d["steps"][0]["actions"] if a.get("id")}
rows = []
for key, a in acts.items():
    if not key.startswith("info-"):
        continue
    s = key[5:]
    info = a.get("value") or {"error": a.get("error")}
    tab = (acts.get(f"tab-{s}") or {}).get("value") or {}
    shift = (acts.get(f"shift-{s}") or {}).get("value") or {}
    trail = acts.get(f"trail-{s}") or {}
    steps = [t for t in trail.get("trail", []) if t]
    rows.append({
        "section": s, "reachable": info.get("count"), "hiddenInClosedDetails": info.get("hiddenInClosedDetails"),
        "trapEndsMatchReal": info.get("same"), "realLast": info.get("realLast"),
        "tabFromLast": {"end": tab.get("end"), "inShell": tab.get("inShell"), "escapes": tab.get("escapes")},
        "shiftTabFromFirst": {"end": shift.get("end"), "inShell": shift.get("inShell"), "escapes": shift.get("escapes")},
        "traversal": {"backToRail": trail.get("ok"), "presses": trail.get("presses"),
                      "outOfShell": [t.get("id") or t.get("tag") for t in steps if not t.get("inShell")],
                      "noOutline": [t.get("id") or t.get("tag") for t in steps if not t.get("outline")],
                      "escapes": (acts.get(f"trailesc-{s}") or {}).get("value")},
    })
ok = [r for r in rows if r["trapEndsMatchReal"] and r["tabFromLast"]["end"] == "first" and r["shiftTabFromFirst"]["end"] == "last"
      and not r["tabFromLast"]["escapes"] and not r["shiftTabFromFirst"]["escapes"] and r["traversal"]["backToRail"]
      and not r["traversal"]["outOfShell"] and not r["traversal"]["escapes"]]
noise = [c for c in d["console"] if "424" not in c["text"] and "favicon" not in c["text"]]
out = {"sections": len(rows), "sectionsAllGood": len(ok), "bad": [r["section"] for r in rows if r not in ok],
       "withHiddenControlsInClosedDetails": [r["section"] for r in rows if r["hiddenInClosedDetails"]],
       "exceptions": d["exceptions"], "consoleOther": noise,
       "posts": [r for r in d["requests"] if r["method"] not in ("GET", "HEAD", "OPTIONS")], "rows": rows}
json.dump(out, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps({k: out[k] for k in ("sections", "sectionsAllGood", "bad", "withHiddenControlsInClosedDetails", "exceptions", "consoleOther", "posts")}, ensure_ascii=False))

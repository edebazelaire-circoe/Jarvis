"""Résumé d'un tour capturé par trace_s9.py : appels d'outils (nom, arguments abrégés, sous-agent ou non), rangs display/prefab, réponse, coût."""
import json, sys
from pathlib import Path

d = json.loads((Path(__file__).parent / "out" / f"{sys.argv[1]}.json").read_text("utf-8"))
calls, results, costs, texts = [], [], [], []
for r in d["rows"]:
    data = r.get("data") or {}
    if r.get("kind") == "agent.event":
        for block in (data.get("message") or {}).get("content") or data.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                calls.append({"name": block.get("name"), "sub": bool(data.get("parent_tool_use_id")),
                              "input": json.dumps(block.get("input"), ensure_ascii=False)[:300]})
        if r.get("message") == "result":
            costs.append(data.get("total_cost_usd") or data.get("cost_usd"))
            texts.append(data.get("result"))
    elif str(r.get("kind", "")).startswith(("display.", "core.prefab", "core.brain.prefab", "agent.subagent", "agent.unsolicited", "agent.turn_over")):
        results.append({"kind": r["kind"], "msg": (r.get("message") or "")[:120],
                        **{k: data.get(k) for k in ("tool", "prefab_id", "version", "origin", "code", "outcome", "found") if k in data}})
print(json.dumps({"answered_s": d.get("answered_s"), "settled_s": d.get("settled_s"), "calls": calls, "rows": results,
                  "cost_usd": costs, "answers": texts, "after": d.get("after")}, ensure_ascii=False, indent=1))

"""Résumé d'un tour capturé par trace_s7.py : appels d'outils (nom, arguments abrégés), résultats d'outils display.*, réponse, coût."""
import json, sys
from pathlib import Path

d = json.loads((Path(__file__).parent / "out" / f"{sys.argv[1]}.json").read_text("utf-8"))
calls, results, cost, text = [], [], None, None
for r in d["rows"]:
    data = r.get("data") or {}
    if r["kind"] == "agent.event":
        for block in (data.get("message") or {}).get("content") or data.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                calls.append({"name": block.get("name"), "input": json.dumps(block.get("input"), ensure_ascii=False)[:400]})
        if r.get("message") == "result":
            cost, text = data.get("total_cost_usd") or data.get("cost_usd"), data.get("result")
    elif r["kind"].startswith(("display.", "core.prefab", "core.brain.prefab")):
        results.append({"kind": r["kind"], **{k: data.get(k) for k in ("tool", "prefab_id", "version", "origin", "code", "outcome", "ok", "errors", "count", "seq", "include_source") if k in data}})
answer = d.get("answer")
if isinstance(answer, (list, tuple)) and len(answer) == 2 and isinstance(answer[1], dict):
    text = text or answer[1].get("text")
print(json.dumps({"elapsed_s": d.get("elapsed_s"), "calls": calls, "display": results, "cost_usd": cost,
                  "answer": text, "after": d.get("after")}, ensure_ascii=False, indent=1))

"""Rangs de trace.jsonl postérieurs au dernier rang d'un tour capturé (travail d'un sous-agent) : out/<nom>-subagent.json."""
import json, os, sys
from pathlib import Path
rt = Path(os.environ["S07_SCRATCH"]) / "runtime" / "trace.jsonl"
rows = [json.loads(l) for l in rt.read_text("utf-8").splitlines() if l.strip()]
turn = json.loads((Path(__file__).parent / "out" / f"{sys.argv[1]}.json").read_text("utf-8"))
start = next(k for k, r in enumerate(rows) if r == turn["rows"][-1]) + 1
end = len(rows) if len(sys.argv) < 3 else next(k for k, r in enumerate(rows) if r.get("kind") == sys.argv[2] and k >= start) + 1
(Path(__file__).parent / "out" / f"{sys.argv[1]}-subagent.json").write_text(
    json.dumps({"rows": rows[start:end]}, ensure_ascii=False, indent=1), "utf-8")
print(end - start)

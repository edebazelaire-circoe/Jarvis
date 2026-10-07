"""Relecture du journal de Core après `stress_probe.mjs` (Slice 09) : pas de tempête d'erreurs.

Lit `trace.jsonl` du runtime de scratch et écrit un résumé SANS chemin ni donnée :
compteurs par niveau, par famille `core.*` d'erreur/avertissement, diagnostics de
débit des événements prefab, et nombre d'entrées `core.prefab.event`.

Usage : python stress_core_journal.py <trace.jsonl> <sortie.json> [depuis ISO]
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path


def summarize(lines: list[dict], since: str = "") -> dict:
    rows = [row for row in lines if row.get("ts", "") >= since]
    by_level = collections.Counter(row.get("level", "?") for row in rows)
    core_bad = collections.Counter(row["kind"] for row in rows
                                   if str(row.get("kind", "")).startswith("core.") and row.get("level") in {"error", "critical"})
    core_warn = collections.Counter(row["kind"] for row in rows
                                    if str(row.get("kind", "")).startswith("core.") and row.get("level") == "warning")
    rate = [{"level": row.get("level"), "message": row.get("message")} for row in rows
            if row.get("kind") == "core.prefab.event_rate_limited"]
    events = collections.Counter(str((row.get("data") or {}).get("outcome", "?")) for row in rows
                                 if row.get("kind") == "core.prefab.event")
    return {"entries": len(rows), "by_level": dict(by_level), "core_errors": dict(core_bad),
            "core_warnings": dict(core_warn), "rate_limited_diagnostics": rate,
            "prefab_event_diagnostics_by_outcome": dict(events)}


def main() -> int:
    source, target = Path(sys.argv[1]), Path(sys.argv[2])
    since = sys.argv[3] if len(sys.argv) > 3 else ""
    lines, unreadable = [], 0
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            lines.append(json.loads(line))
        except ValueError:
            unreadable += 1  # deux processus (Core, CC) écrivent le même fichier : ligne entrelacée
    result = {**summarize(lines, since), "unreadable_lines": unreadable}
    target.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

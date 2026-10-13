"""Slice 01 census: every declared Remotion composition (width, height, fps[, frames]) in tests/** and the authoring defaults.
Run from the repository root: python census.py > census.json. Lexical (regex) census; reproducible on any checkout."""
import json, re, sys
from collections import Counter
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
pats = [
    ("Composition(...)", re.compile(r'Composition\(\s*"([A-Za-z][\w-]*)"\s*,\s*(\w+)\s*,\s*(\w+)\s*,\s*(\w+)\s*,\s*([^)]+)\)')),
    ("composition dict", re.compile(r'"composition"\s*:\s*\{\s*(?:"id"\s*:\s*"[^"]*"\s*,\s*)?"width"\s*:\s*(\w+)\s*,\s*"height"\s*:\s*(\w+)\s*,\s*"fps"\s*:\s*(\w+)')),
]
rows = []
for path in sorted(list(root.glob("tests/**/*.py")) + list(root.glob("tests/fixtures/**/*.json")) + list(root.glob("jarvis/domain/presentation_studio_authoring*.py"))):
    text = path.read_text(encoding="utf-8", errors="replace")
    for kind, pat in pats:
        for m in pat.finditer(text):
            g = m.groups()
            w, h, fps = (g[1], g[2], g[3]) if kind == "Composition(...)" else (g[0], g[1], g[2])
            rows.append({"file": path.relative_to(root).as_posix(), "line": text.count("\n", 0, m.start()) + 1, "kind": kind,
                         "width": w, "height": h, "fps": fps})
for path in sorted(root.glob("tests/fixtures/**/manifest.json")):
    m = json.loads(path.read_text(encoding="utf-8"))
    c = (m.get("source") or {}).get("composition")
    if c:
        rows.append({"file": path.relative_to(root).as_posix(), "line": 0, "kind": "fixture manifest", "width": str(c["width"]),
                     "height": str(c["height"]), "fps": str(c["fps"])})
spec = Counter(f'{r["width"]}x{r["height"]}@{r["fps"]}' for r in rows)
print(json.dumps({"declarations": len(rows), "by_spec": dict(spec.most_common()), "rows": rows}, indent=1))

"""Assemble le `behavior.js` de chaque prefab circoe.* : bloc commun + corps.

`jarvis/prefabs/circoe/_common/cx.js` (helpers : cxEl, cxIcon, cxCount, cxNum,
spotlight) suivi de `<id>/behavior.body.js`. Le résultat est committé ; un test
vérifie qu'il est à jour.   python scripts/circoe_assemble.py
"""
from __future__ import annotations

from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "jarvis" / "prefabs" / "circoe"


def assembled(folder: Path) -> str:
    common = (BASE / "_common" / "cx.js").read_text(encoding="utf-8")
    return common + (folder / "behavior.body.js").read_text(encoding="utf-8")


def main() -> int:
    for body in sorted(BASE.glob("*/behavior.body.js")):
        target = body.parent / "behavior.js"
        target.write_text(assembled(body.parent), encoding="utf-8", newline="\n")
        print(target.relative_to(BASE.parent.parent.parent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

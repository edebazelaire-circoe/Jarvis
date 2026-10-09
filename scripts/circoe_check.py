"""Valide les sources des prefabs circoe.* avec le domaine (comme `prefab_validate`).

    python scripts/circoe_check.py [dossier ...]      (défaut : tous)

Pour chacun : manifeste strict, exemple valide, lint d'hygiène, bornes de
taille, LF partout, `behavior.js` à jour (bloc commun + corps), empreinte.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis.domain.prefab import parse_bundle  # noqa: E402
from scripts.circoe_assemble import BASE, assembled  # noqa: E402


def sources(folder: Path) -> dict[str, str]:
    return {name: (folder / name).read_text(encoding="utf-8") for name in
            ("manifest.json", "template.html", "style.css", "behavior.js")}


def check(folder: Path) -> list[str]:
    problems: list[str] = []
    for name in ("manifest.json", "template.html", "style.css", "behavior.js", "behavior.body.js"):
        if b"\r" in (folder / name).read_bytes():
            problems.append(f"{name}: CRLF (LF requis)")
    if (folder / "behavior.js").read_text(encoding="utf-8") != assembled(folder):
        problems.append("behavior.js n'est pas à jour : python scripts/circoe_assemble.py")
    files = sources(folder)
    try:
        bundle = parse_bundle(json.loads(files["manifest.json"]), files["template.html"], files["style.css"], files["behavior.js"])
    except Exception as error:  # noqa: BLE001 - on veut tout le texte de l'erreur
        return problems + [f"parse_bundle: {error}"]
    print(f"{folder.name}: ok, empreinte {bundle.fingerprint()[:12]}, "
          + ", ".join(f"{k} {len(v.encode())}" for k, v in files.items()))
    return problems


def main(argv: list[str]) -> int:
    folders = [Path(a) for a in argv] or sorted(p.parent for p in BASE.glob("*/manifest.json"))
    failed = 0
    for folder in folders:
        for problem in check(folder):
            if problem:
                failed += 1
                print(f"{folder.name}: {problem}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

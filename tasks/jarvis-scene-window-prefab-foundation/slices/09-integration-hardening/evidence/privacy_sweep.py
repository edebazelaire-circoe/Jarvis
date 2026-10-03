"""Balayage de confidentialité de TOUT le dossier du handoff (Slice 09).

`python privacy_sweep.py` (ou `--check`) : parcourt `tasks/jarvis-scene-window-prefab-foundation/**`
(fichiers texte ; les images sont listées à part, non lisibles par motif) et sort en code 1 en
listant chaque fichier qui contient encore :
- le dossier personnel (formes Windows `C:\\…`, `C:/…`, JSON `\\\\`, Git Bash `/c/…`) ;
- un nom d'utilisateur de la machine (`USERNAME`/`USER`, `Path.home().name`, `getpass.getuser()`) ;
- une adresse électronique ;
- une forme de jeton (porteur `Bearer …`, clé `sk-…`, jeton GitHub, champ `token` en clair).

`python privacy_sweep.py --fix` : remplace dossier personnel, racine de scratch et noms par
`<home>`, `<scratch>`, `<user>` dans les fichiers texte (les autres motifs sont seulement signalés :
un jeton ou une adresse se retire à la main, en comprenant d'où il vient). Idempotent.

Les cibles sont lues à l'exécution, jamais écrites ici (même approche que `redact.py` de la
Slice 07) : ce fichier ne contient aucun nom de personne. Utilisé par
`tests/unit/test_task_evidence_privacy.py`.
"""

from __future__ import annotations

import getpass
import os
from pathlib import Path
import re
import sys

TASK = Path(__file__).resolve().parents[3]
TEXT_SUFFIXES = {".md", ".json", ".jsonl", ".txt", ".mjs", ".js", ".py", ".html", ".css", ".csv", ".log", ".yaml", ".yml", ""}
SEP = r"(?:\\\\|\\|/)"
#: Un nom plus court se retrouverait dans des mots ordinaires : il n'est pas cherché seul.
MIN_NAME_CHARS = 3
#: Adresses qui ne désignent personne (exemples de la documentation, attribution des commits).
ALLOWED_EMAILS = {"noreply@anthropic.com"}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
TOKENS = [
    re.compile(r"Bearer\s+(?!\$\{|<|\{)[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\"(?:token|session_token|api_key)\"\s*:\s*\"(?!<)[A-Za-z0-9._~+/=-]{16,}\""),
]


def user_names() -> list[str]:
    names = {os.environ.get("USERNAME", ""), os.environ.get("USER", ""), Path.home().name}
    try:
        names.add(getpass.getuser())
    except (KeyError, OSError):
        pass
    return sorted(name for name in names if len(name) >= MIN_NAME_CHARS)


def home_pattern() -> str:
    home = Path.home()
    drive = home.drive.rstrip(":")
    parts = [re.escape(part) for part in home.parts[1:]]
    prefix = rf"(?:{re.escape(drive)}:|/{re.escape(drive.lower())})" if drive else ""
    return prefix + "".join(SEP + part for part in parts)


def rewrite_rules() -> list[tuple[re.Pattern[str], str]]:
    home = home_pattern()
    rules = [
        (re.compile(home + SEP + r"AppData" + SEP + r"Local" + SEP + r"Temp" + SEP + r"claude" + SEP
                    + r"[^\\/\"\s]+" + SEP + r"[0-9a-f-]{36}" + SEP + r"scratchpad", re.I), "<scratch>"),
        (re.compile(home, re.I), "<home>"),
    ]
    rules += [(re.compile(r"(?<![A-Za-z])" + re.escape(name) + r"(?![a-z])", re.I), "<user>") for name in user_names()]
    return rules


def text_files(root: Path = TASK) -> tuple[list[Path], list[Path]]:
    texts, binaries = [], []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        (texts if path.suffix.lower() in TEXT_SUFFIXES else binaries).append(path)
    return texts, binaries


def findings(text: str, rules=None) -> list[str]:
    rules = rules if rules is not None else rewrite_rules()
    hits = sorted({repl for pattern, repl in rules if pattern.search(text)})
    emails = sorted({m for m in EMAIL.findall(text) if m.lower() not in ALLOWED_EMAILS})
    if emails:
        hits.append(f"email×{len(emails)}")
    if any(pattern.search(text) for pattern in TOKENS):
        hits.append("token")
    return hits


def sweep(root: Path = TASK) -> dict[str, list[str]]:
    rules = rewrite_rules()
    texts, _ = text_files(root)
    leaks = {}
    for path in texts:
        hits = findings(path.read_text("utf-8", errors="ignore"), rules)
        if hits:
            leaks[str(path.relative_to(root)).replace("\\", "/")] = hits
    return leaks


def fix(root: Path = TASK) -> int:
    rules = rewrite_rules()
    changed = 0
    texts, _ = text_files(root)
    for path in texts:
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        new = text
        for pattern, repl in rules:
            new = pattern.sub(repl, new)
        if new != text:
            path.write_bytes(new.encode("utf-8"))
            changed += 1
    return changed


def main(argv: list[str]) -> int:
    if "--fix" in argv:
        print(f"réécrits : {fix()}")
    leaks = sweep()
    texts, binaries = text_files()
    if leaks:
        for name, hits in leaks.items():
            print(f"{name}: {', '.join(hits)}")
        return 1
    print(f"ok: {len(texts)} fichiers texte sans dossier personnel, nom d'utilisateur, adresse ni jeton "
          f"({len(binaries)} images non lisibles par motif)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

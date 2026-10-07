"""Expurge out/* avant commit, et vérifie qu'aucune trace committée ne garde d'identité locale.

`python redact.py` : remplace le dossier personnel, la racine de scratch et le nom de l'utilisateur par des
marqueurs, vide les champs d'inventaire de l'événement `system/init` du CLI (skills, slash_commands, plugins,
agents, memory_paths…). Idempotent.

`python redact.py --check` : parcourt tout le dossier evidence (y compris ce script) et sort en code 1 en
listant chaque fichier qui contient encore le dossier personnel ou le nom de l'utilisateur.

Les cibles sont lues à l'exécution (`Path.home()`, `USERNAME`/`USER`, `getpass.getuser()`), jamais écrites
ici : ce fichier ne contient aucun nom de personne.
"""
import getpass
import json
import os
from pathlib import Path
import re
import sys

HERE = Path(__file__).parent
OUT = HERE / "out"
INVENTORY = {"skills", "slash_commands", "plugins", "agents", "memory_paths", "output_style", "cwd", "apiKeySource",
             "claude_code_version_path", "additional_directories"}
SEP = r"(?:\\\\|\\|/)"  # séparateur tel qu'il apparaît : `\\` (JSON), `\`, `/`
#: Un nom plus court se retrouverait dans des mots ordinaires : il n'est pas cherché seul.
MIN_NAME_CHARS = 3


def user_names() -> list[str]:
    names = {os.environ.get("USERNAME", ""), os.environ.get("USER", ""), Path.home().name}
    try:
        names.add(getpass.getuser())
    except (KeyError, OSError):
        pass
    return sorted(name for name in names if len(name) >= MIN_NAME_CHARS)


def home_pattern() -> str:
    """Le dossier personnel sous ses formes Windows (`C:\\…`, `C:/…`, JSON) et Git Bash (`/c/…`)."""

    home = Path.home()
    drive = home.drive.rstrip(":")
    parts = [re.escape(part) for part in home.parts[1:]]
    prefix = rf"(?:{re.escape(drive)}:|/{re.escape(drive.lower())})" if drive else ""
    return prefix + "".join(SEP + part for part in parts)


def patterns() -> list[tuple[re.Pattern[str], str]]:
    home = home_pattern()
    found = [
        (re.compile(home + SEP + r"AppData" + SEP + r"Local" + SEP + r"Temp" + SEP + r"claude" + SEP
                    + r"[^\\/\"]+" + SEP + r"[0-9a-f-]{36}" + SEP + r"scratchpad", re.I), "<scratch>"),
        (re.compile(home, re.I), "<home>"),
    ]
    found += [(re.compile(re.escape(name), re.I), "<user>") for name in user_names()]
    return found


def scrub(value, rules):
    if isinstance(value, dict):
        return {k: ("<redacted>" if k in INVENTORY else scrub(v, rules)) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v, rules) for v in value]
    if isinstance(value, str):
        for pattern, repl in rules:
            value = pattern.sub(repl, value)
        return value
    return value


def redact() -> None:
    rules = patterns()
    for path in sorted(OUT.iterdir()):
        if path.suffix == ".json":
            data = scrub(json.loads(path.read_text("utf-8")), rules)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
        elif path.suffix == ".txt":
            path.write_text(scrub(path.read_text("utf-8"), rules), "utf-8")
    print("ok")


def check() -> int:
    rules = patterns()
    leaks = []
    for path in sorted(HERE.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        text = path.read_text("utf-8", errors="ignore")
        hits = sorted({repl for pattern, repl in rules if pattern.search(text)})
        if hits:
            leaks.append(f"{path.relative_to(HERE)}: {', '.join(hits)}")
    print("\n".join(leaks) if leaks else f"ok: {sum(1 for p in HERE.rglob('*') if p.is_file())} fichiers, "
          f"aucun dossier personnel ni nom d'utilisateur")
    return 1 if leaks else 0


if __name__ == "__main__":
    sys.exit(check() if "--check" in sys.argv[1:] else redact())

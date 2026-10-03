"""Expurge out/*.json avant commit : chemins personnels, listes de skills/plugins/commandes/agents du CLI, mémoire.

Remplace le dossier personnel et la racine de scratch par des marqueurs, vide les champs d'inventaire de
l'événement `system/init` du CLI (skills, slash_commands, plugins, agents, memory_paths…), retire le rang
s07-trace-c3-core-confirmed-subagent vide. Idempotent.
"""
import json, re
from pathlib import Path

OUT = Path(__file__).parent / "out"
INVENTORY = {"skills", "slash_commands", "plugins", "agents", "memory_paths", "output_style", "cwd", "apiKeySource",
             "claude_code_version_path", "additional_directories"}
PATTERNS = [
    (re.compile(r"C:(?:\\\\|\\|/)Users(?:\\\\|\\|/)Clarice(?:\\\\|\\|/)AppData(?:\\\\|\\|/)Local(?:\\\\|\\|/)Temp(?:\\\\|\\|/)claude(?:\\\\|\\|/)[^\\/\"]+(?:\\\\|\\|/)[0-9a-f-]{36}(?:\\\\|\\|/)scratchpad", re.I), "<scratch>"),
    (re.compile(r"(?:C:|/c)(?:\\\\|\\|/)Users(?:\\\\|\\|/)Clarice", re.I), "<home>"),
    (re.compile(r"Clarice", re.I), "<user>"),
]


def scrub(value):
    if isinstance(value, dict):
        return {k: ("<redacted>" if k in INVENTORY else scrub(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        for pattern, repl in PATTERNS:
            value = pattern.sub(repl, value)
        return value
    return value


for path in sorted(OUT.iterdir()):
    if path.suffix == ".json":
        path.write_text(json.dumps(scrub(json.loads(path.read_text("utf-8"))), ensure_ascii=False, indent=1), "utf-8")
    elif path.suffix == ".txt":
        path.write_text(scrub(path.read_text("utf-8")), "utf-8")
print("ok")

"""Expurge out/* des traces S09 avant commit : même règle que `redact.py` de la Slice 07 (réutilisé, pas recopié).

Remplace dossier personnel, racine de scratch et noms d'utilisateur par `<home>`, `<scratch>`, `<user>`, et
vide les champs d'inventaire de l'événement `system/init` du CLI (skills, plugins, agents, memory_paths…).
Cibles lues à l'exécution. Vérification : `python privacy_sweep.py` (tout le dossier du handoff).
"""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location(
    "s07_redact", HERE.parents[1] / "07-agent-prefab-operations" / "evidence" / "redact.py")
s07 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s07)

rules = s07.patterns()
for path in sorted((HERE / "out").glob("*.json")):
    data = s07.scrub(json.loads(path.read_text("utf-8")), rules)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
print("ok")

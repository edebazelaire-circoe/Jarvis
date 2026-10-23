"""Ancien fichier de réglages, page ouverte, « Enregistrer » de Comportement (une valeur changée), comparaison."""
import json, shutil, subprocess, sys
sys.path.insert(0, r"C:\Projects\jarvis\arch-s08")
import s08_sandbox as S
from tests.unit.test_wake_word_settings_browser import CHROME_CANDIDATES, HARNESS
from tests.unit.test_architecture_agents_settings_browser import OPEN, SAVE
for name in ("brain-config.json", "subagent-role-routing.json", "brain-delegation-launched.json"):
    p = S.RUNTIME / name
    if p.exists():
        p.rename(p.with_suffix(p.suffix + ".phases"))  # mis de côté : l'état « avant la tâche » n'en a pas
shutil.copy2(S.SANDBOX / "settings-before.json", S.RUNTIME / "control-center-settings.json")
before = json.loads((S.SANDBOX / "settings-before.json").read_text(encoding="utf-8"))
chrome = next((str(c) for c in CHROME_CANDIDATES if c.is_file()), None)
with S.ControlCenterSandbox():
    _, core = S.http("GET", "/api/brains/core/config")
    _, routing = S.http("GET", "/api/subagent-role-routing")
    S.say(f"(migration) ancien fichier relu : CLI={core['fields']['provider']['value']} modèle={core['fields']['model']['value'] or '(défaut)'} "
          f"délégation={core['fields']['delegation']['value']} (store {core['fields']['delegation'].get('store_revision')}) ; "
          f"rôles {sorted({r['provenance'] for r in routing['roles']})} ; révision rôles {routing['revision']}")
    plan = [{"width": 1440, "height": 900, "actions": [*OPEN, *SAVE]}]
    done = subprocess.run([shutil.which("node"), str(HARNESS), S.UI + "/", chrome, json.dumps(plan)], capture_output=True,
                          text=True, encoding="utf-8", timeout=300)
    out = json.loads(done.stdout)
    posts = [json.loads(r["body"]) for r in out["requests"] if r["method"] == "POST" and r["path"] == "/api/settings"]
    S.say(f"(migration) Enregistrer de Comportement : {len(posts)} POST /api/settings, clés {sorted(posts[0]) if posts else None} ; "
          f"attentes tenues {sum(1 for a in out['steps'][0]['actions'] if a.get('a') == 'wait' and a.get('ok'))} ; console {out['console']}")
after = S.settings_now()
b, a = dict(S.leaves(before)), dict(S.leaves(after))
S.say(f"(migration) ancien fichier avant/après la page et un enregistrement à pied : clés perdues={sorted(k for k in b if k not in a)} ; "
      f"valeurs changées={ {k: [b[k], a[k]] for k in b if k in a and a[k] != b[k]} } ; clés ajoutées={sorted(k for k in a if k not in b)} ; "
      f"brain-config.json écrit={(S.RUNTIME / 'brain-config.json').exists()} ; subagent-role-routing.json écrit={(S.RUNTIME / 'subagent-role-routing.json').exists()}")
with open(S.SCRATCH / "s08-sandbox-evidence.log", "a", encoding="utf-8") as fh:
    fh.write("\n".join(S.LOG) + "\n")

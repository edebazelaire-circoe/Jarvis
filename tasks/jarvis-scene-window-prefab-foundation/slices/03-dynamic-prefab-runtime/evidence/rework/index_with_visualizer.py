"""S3 rework — la vraie page `ControlCenter.index` avec un visualiseur configuré.

`python -m jarvis control-center` ne pose `visualizer_url` que s'il lance
`third_party/ai-visualizer` (absent d'un worktree) : ce banc sert la même
méthode `index` sur `<port>` avec `visualizer_url=<url>`, pour vérifier dans
un vrai navigateur que l'en-tête `frame-src <origine>` laisse charger le
visualiseur. Usage (racine du dépôt) : python <ce fichier> <port> <url> <scratch>
"""

import asyncio
from pathlib import Path
import sys

from aiohttp import web

sys.path.insert(0, str(Path.cwd()))
from jarvis.runtime.control_center import ControlCenter  # noqa: E402


async def main() -> None:
    port, url, scratch = int(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    scratch.mkdir(parents=True, exist_ok=True)
    control = ControlCenter(runtime_root=scratch, project_root=scratch, visualizer_url=url)
    app = web.Application()
    app.router.add_get("/", control.index)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    print(f"index on http://127.0.0.1:{port}/ visualizer {url}", flush=True)
    await asyncio.Event().wait()


asyncio.run(main())

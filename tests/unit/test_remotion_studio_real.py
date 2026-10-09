"""Studio Remotion RÉEL : Node, @remotion/cli, webpack et le garde du Studio, dans une installation privée (Slice 11).

Ignoré sans `JARVIS_REMOTION_RUNTIME_DIR` (le dossier `runtime/` d'une capacité Remotion installée dans une racine PRIVÉE, jamais le
profil vivant). Le test écrit sous `<runtime>/studio/` et s'arrête avant de rendre la main :

    JARVIS_REMOTION_RUNTIME_DIR=<racine privée>/local_capabilities/remotion/runtime pytest tests/unit/test_remotion_studio_real.py

Preuves plus larges (Core isolé, Chrome, interface, orphelins) : `scripts/remotion_studio_harness.py`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import urllib.request

import pytest

from jarvis.adapters.remotion_studio_runner import RemotionStudioRunner
from jarvis.core.remotion_studio_service import RemotionStudioService
from jarvis.domain.prefab import parse_candidate
from jarvis.domain.remotion_studio import StudioPin
from tests.fakes.remotion_scene import scene_candidate, scene_files

RUNTIME = os.environ.get("JARVIS_REMOTION_RUNTIME_DIR")
pytestmark = pytest.mark.skipif(not RUNTIME or not (Path(RUNTIME or ".") / "node_modules" / "@remotion" / "cli").is_dir() or shutil.which("node") is None,
                                reason="JARVIS_REMOTION_RUNTIME_DIR points to no installed Remotion runtime")
SCENE = "presentation-studio.p000000000001.s000000000001"
PIN, PIN2 = StudioPin(SCENE, 1), StudioPin(SCENE, 2)


def fetch(url: str, timeout: float = 30) -> tuple[int, dict, str]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=timeout) as response:
        return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read().decode("utf-8", "replace")


async def provide(pin):
    suffix = f'export const MARKER = "MARKER_V{pin.version}";\n'  # un littéral : un commentaire serait retiré par la compilation
    source = parse_candidate(scene_candidate(pin.prefab_id, files=scene_files(suffix))).remotion_source()
    return source, {"title": "Réel"}


async def test_the_real_studio_opens_serves_the_scene_reloads_and_leaves_nothing_behind():
    runtime = Path(RUNTIME)
    runner = RemotionStudioRunner(lambda: runtime)
    service = RemotionStudioService(runner, source_provider=provide, capability_status=lambda: "ready")
    view = await service.open(PIN)
    try:
        assert view["status"] == "ready", view
        url = view["url"]
        assert url.startswith("http://127.0.0.1:")
        status, headers, page = fetch(url)
        assert status == 200 and "Remotion Studio" in page and "default-src 'self'" in headers["content-security-policy"]
        _, _, health = fetch(url + "__jarvis_studio__/health")
        assert json.loads(health)["launch"] == runner.read_state()["launch_id"]
        # La copie de travail est exactement la source + ses trois fichiers générés, en lecture seule.
        work = runtime / "studio" / "work"
        assert (work / "studio-root.tsx").is_file() and not os.access(work / "src" / "Scene.tsx", os.W_OK)
        # Rechargement à chaud : la nouvelle version atteint le paquet servi sans redémarrer le processus.
        pid_before = runner.read_state()["process_ref"]
        _, _, bundle = fetch(url + "bundle.js", timeout=60)
        assert "MARKER_V1" in bundle and "MARKER_V2" not in bundle
        await service.sync(PIN2)
        for _ in range(60):
            _, _, bundle = fetch(url + "bundle.js", timeout=60)
            if "MARKER_V2" in bundle:
                break
            import asyncio
            await asyncio.sleep(0.5)
        assert "MARKER_V2" in bundle and "MARKER_V1" not in bundle
        assert runner.read_state()["process_ref"] == pid_before
    finally:
        closed = await service.close()
    assert closed["status"] == "stopped"
    ref = runner.read_state()["process_ref"]
    assert not runner.is_alive(ref) or ref == ""
    with pytest.raises(OSError):
        fetch(view["url"], timeout=3)

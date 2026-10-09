"""Chaîne réelle de la Slice 10 (Remotion Player dans Jarvis) : Core composé avec Remotion, serveur de protocole, Control Center.

Réel : `JarvisCoreApplication` avec le magasin de capacités locales et le runner Node (la composition de `jarvis/app.py`), le
compilateur (Node + esbuild du verrou), l'écouteur du bac à sable (une adresse de boucle locale à part), `LocalProtocolServer`,
le vrai `ControlCenter` servi sur un port fixe (l'origine qui encadre le cadre) avec ses relais de scène et de mode.
Simulé : rien du côté serveur. Racine de données et ports jetables ; jamais le Jarvis vivant.

`provision_runtime(data_root, runtime_dir)` rend la capacité Remotion `ready` SANS installation : les petits fichiers d'une
installation existante sont copiés (`install-record.json`, verrou, `runtime-host.mjs`) et `node_modules` est une jonction vers
celle-ci (aucune copie de plusieurs centaines de Mo). Sans appel, la capacité est absente : le scénario « runtime désinstallé ».
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from typing import Any

from aiohttp.test_utils import TestServer

from jarvis.adapters.file_local_capability_store import FileLocalCapabilityStore
from jarvis.adapters.node_capability_runner import default_remotion_runner
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.remotion_capability import REMOTION_COMPONENTS
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.core_sessions import CoreSessionTransport
from jarvis.runtime.interaction_mode_view import CoreInteractionModeTransport, CoreInteractionModeView
from jarvis.runtime.remotion_composition import remotion_factory
from jarvis.runtime.remotion_sandbox_server import RemotionSandboxSettings
from jarvis.runtime.scene_view import CoreSceneTransport, CoreSceneView
from tests.fakes.conversation_events import RecordingDiagnostics

TOKEN = "d" * 48
SANDBOX_HOST = "127.77.0.2"
SMALL_RUNTIME_FILES = ("install-record.json", "package.json", "package-lock.json", "runtime-host.mjs")


def free_port(host: str = "127.0.0.1") -> int:
    with socket.socket() as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def runtime_dir_from_env() -> Path | None:
    """Une installation existante à réutiliser (`JARVIS_REMOTION_RUNTIME_DIR` = son dossier `runtime/`), ou `None`."""

    raw = os.environ.get("JARVIS_REMOTION_RUNTIME_DIR")
    path = Path(raw) if raw else None
    return path if path is not None and (path / "node_modules").is_dir() and (path / "runtime-host.mjs").is_file() else None


def provision_runtime(data_root: Path, runtime_dir: Path) -> None:
    target = data_root / "local_capabilities" / "remotion"
    (target / "runtime").mkdir(parents=True, exist_ok=True)
    for name in SMALL_RUNTIME_FILES:
        shutil.copy2(runtime_dir / name, target / "runtime" / name)
    link = target / "runtime" / "node_modules"
    if not link.exists():
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(runtime_dir / "node_modules")], check=True,
                           capture_output=True)
        else:
            link.symlink_to(runtime_dir / "node_modules", target_is_directory=True)
    (target / "state.json").write_text(json.dumps({
        "capability_id": "remotion", "enabled": True, "health": "healthy", "install_attempts": 1, "install_status": "installed",
        "installed_components": dict(REMOTION_COMPONENTS), "last_error_code": None, "last_error_detail": "",
        "process_ref": "", "process_status": "stopped", "updated_at": "2026-10-09T17:36:47.158074+00:00"}), encoding="utf-8")


class RemotionStack:
    """`async with RemotionStack(tmp_path, runtime_dir=...) as stack`. `runtime_dir=None` : capacité absente (échec typé)."""

    def __init__(self, tmp_path: Path, *, runtime_dir: Path | None = None, visualizer_url: str | None = None,
                 configure_sandbox: bool = True) -> None:
        self.tmp_path = tmp_path
        self.runtime_dir = runtime_dir
        self.visualizer_url = visualizer_url
        self.configure_sandbox = configure_sandbox
        self.diagnostics = RecordingDiagnostics()

    async def __aenter__(self) -> "RemotionStack":
        self.cc_port, self.core_port, self.sandbox_port = free_port(), free_port(), free_port(SANDBOX_HOST)
        self.data_root = self.tmp_path / "data"
        self.data_root.mkdir(parents=True, exist_ok=True)
        if self.runtime_dir is not None:
            provision_runtime(self.data_root, self.runtime_dir)
        self.sandbox_settings = RemotionSandboxSettings(SANDBOX_HOST, self.sandbox_port, f"http://127.0.0.1:{self.cc_port}")
        self.core = JarvisCoreApplication(
            data_root=self.data_root, diagnostics=self.diagnostics,
            local_capability_store=FileLocalCapabilityStore(self.data_root), local_capability_runner=default_remotion_runner(),
            remotion=remotion_factory(self.sandbox_settings) if self.configure_sandbox else None)
        await self.core.start()
        self.server = LocalProtocolServer(self.core, host="127.0.0.1", port=self.core_port, token=TOKEN)
        await self.server.start()
        self.core_url = f"http://127.0.0.1:{self.core_port}"
        token_file = self.tmp_path / "core.token"
        token_file.write_text(TOKEN, encoding="utf-8")
        self.sessions = CoreSessionTransport(host="127.0.0.1", port=self.core_port, token_file=token_file)
        runtime = self.tmp_path / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        self.center = ControlCenter(runtime_root=runtime, project_root=self.tmp_path, visualizer_url=self.visualizer_url)
        self.center.sessions = self.sessions
        self.center.scene_view = CoreSceneView(CoreSceneTransport(host="127.0.0.1", port=self.core_port, token_file=token_file))
        self.center.interaction_mode_view = CoreInteractionModeView(
            CoreInteractionModeTransport(host="127.0.0.1", port=self.core_port, token_file=token_file))
        self.cc_server = TestServer(self.center._app, host="127.0.0.1", port=self.cc_port)
        await self.cc_server.start_server()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.cc_server.close()
        await self.center.scene_view.aclose()
        await self.sessions.close()
        await self.server.stop()
        await self.core.stop()

    @property
    def page_url(self) -> str:
        return f"http://127.0.0.1:{self.cc_port}/"

    @property
    def sandbox_origin(self) -> str:
        return self.sandbox_settings.origin

    # ------------------------------------------------------------------ monde de la scène

    async def publish(self, prefab_id: str, files: dict | None = None, *, title: str = "Scène Remotion",
                      props: dict | None = None, sample: dict | None = None) -> int:
        """Publie une source Remotion (écrite pour l'arbre installé) par `PrefabService.save` ; rend son numéro de version."""

        from jarvis.adapters.remotion_compiler import shipped_engine_pin
        from tests.fakes.remotion_scene import scene_candidate
        options: dict[str, Any] = {"engine": shipped_engine_pin(), "title": title}
        if files is not None:
            options["files"] = files
        if props is not None:
            options["props"] = props
        if sample is not None:
            options["sample"] = sample
        return (await self.core.prefabs.save(scene_candidate(prefab_id, **options), actor="user")).version

    async def call(self, method: str, path: str, **kwargs: Any) -> tuple[int, Any]:
        """Requête directe à Core (jeton porteur)."""

        import aiohttp
        async with aiohttp.ClientSession() as http:
            async with http.request(method, self.core_url + path, headers={"Authorization": f"Bearer {TOKEN}"}, **kwargs) as response:
                return response.status, await response.json(content_type=None)

    async def presentation(self, scenes: list[dict], *, title: str = "Remotion") -> tuple[str, str]:
        """Une Presentation (moteur Remotion, par défaut) avec ces scènes, une partition qui les parcourt une à une et la direction
        artistique de secours : prête à `start`. Rend `(presentation_id, variant_id)`."""

        base = "/v1/presentation-studio/presentations"
        _, created = await self.call("POST", base, json={"title": title})
        pid, variant = created["presentation"]["presentation_id"], created["variants"][0]
        vid = variant["variant_id"]
        status, saved = await self.call("PUT", f"{base}/{pid}/variants/{vid}", json={
            "expected_revision": variant["revision"], "title": variant["title"], "scenes": scenes,
            "art_direction_id": variant["art_direction_id"], "score_id": variant["score_id"]})
        assert status == 200, saved
        items = [{"item_id": f"psi_{index + 1:012d}", "scene_id": scene["scene_id"], "presenter": "user", "kind": "speech",
                  "note": scene["title"], **({"next_item_id": f"psi_{index + 2:012d}"} if index + 1 < len(scenes) else {})}
                 for index, scene in enumerate(scenes)]
        status, made = await self.call("POST", f"{base}/{pid}/variants/{vid}/score", json={
            "expected_variant_revision": saved["revision"], "start_item_id": items[0]["item_id"], "items": items, "cues": [],
            "sequences": [], "recovery_points": []})
        assert status == 201, made
        status, art = await self.call("POST", f"{base}/{pid}/variants/{vid}/art-direction/fallback",
                                      json={"expected_variant_revision": saved["revision"] + 1})
        assert status == 201, art
        return pid, vid

    async def start(self, presentation_id: str) -> tuple[int, Any]:
        return await self.call("POST", "/v1/presentation-studio/playback/start",
                               json={"actor": "user", "presentation_id": presentation_id, "role": "user_presenter"})

    def kinds(self) -> list[str]:
        return self.diagnostics.kinds()

    def trace(self) -> list[dict]:
        """Le journal du Control Center (`runtime/trace.jsonl`)."""

        path = self.tmp_path / "runtime" / "trace.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    async def get(self, path: str, *, headers: dict | None = None, **kwargs: Any) -> tuple[int, dict, str]:
        """GET sur le Control Center (Host de bouclage) : (statut, en-têtes, texte)."""

        import aiohttp
        async with aiohttp.ClientSession() as http:
            async with http.get(self.page_url.rstrip("/") + path, headers=headers, **kwargs) as response:
                return response.status, dict(response.headers), await response.text()

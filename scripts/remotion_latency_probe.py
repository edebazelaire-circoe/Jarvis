"""Latences côté Core d'une scène Remotion, vrai compilateur (Node + esbuild du verrou) (Slice 22 de jarvis-remotion-presentation-integration).

    python scripts/remotion_latency_probe.py --runtime-dir <runtime> --evidence <fichier.json> [--samples 5]

Mesure, sur un Core isolé composé comme `jarvis/app.py` (ports libres, racine de données jetable, jamais le JARVIS vivant) :
- démarrage à froid du Player côté Core : première description de la scène (compile `host.js` + `scene.js`, cache vide) ;
- description à chaud (cache) ;
- rechargement après une édition de SOURCE (`POST .../source-edits` : compile `scene.js` seul, l'hôte est en cache, publie, épingle) ;
- édition de PROPS pendant la lecture (`POST .../playback/edit` `control.set`).
Le trajet jusqu'aux pixels (échange du cadre, `props` au Player) se mesure dans un navigateur : `evidence/edit/source_edit_hmr.json` (`waited_s`).
Ce script n'ouvre aucun navigateur ; les durées sont des allers-retours HTTP vers Core.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.fakes.remotion_player_stack import RemotionStack  # noqa: E402
from tests.unit.test_remotion_player_realpage_browser import A, PROPS, SAMPLE, SCENE_TSX, S1, scene  # noqa: E402


def stats(values: list[float]) -> dict:
    return {"n": len(values), "min_s": round(min(values), 3), "median_s": round(statistics.median(values), 3), "max_s": round(max(values), 3)}


def footprint(root: Path) -> dict:
    """Taille (Kio) des dossiers de la racine de données après la mesure, `node_modules` exclu (jonction vers l'installation)."""

    sizes: dict[str, int] = {}
    for base, folders, files in os.walk(root):
        folders[:] = [f for f in folders if f != "node_modules"]
        top = Path(base).relative_to(root).parts[:3]
        key = "/".join(top) or "."
        sizes[key] = sizes.get(key, 0) + sum(os.path.getsize(os.path.join(base, f)) for f in files if os.path.exists(os.path.join(base, f)))
    return {k: round(v / 1024, 1) for k, v in sorted(sizes.items()) if v > 4096}


async def main(runtime: Path, samples: int) -> dict:
    out: dict = {"environment": {"os": platform.platform(), "python": platform.python_version(),
                                 "node": subprocess.run(["node", "--version"], capture_output=True, text=True, check=False).stdout.strip(),
                                 "cpu_threads": os.cpu_count(), "when": datetime.now(timezone.utc).isoformat(timespec="seconds")}}
    with tempfile.TemporaryDirectory(prefix="jrs22lat-") as tmp:
        async with RemotionStack(Path(tmp), runtime_dir=runtime) as stack:
            await stack.publish(A, {"src/Scene.tsx": SCENE_TSX}, title="Un", props=PROPS, sample=SAMPLE)
            pid, vid = await stack.presentation([scene(S1, A, "Premier")])
            started = time.perf_counter()
            description = await stack.core.remotion_player.describe(A, 1)
            out["player_cold_describe_s"] = round(time.perf_counter() - started, 3)
            out["player_cold_host_bytes"] = description.get("host", {}).get("bytes") if isinstance(description.get("host"), dict) else None
            started = time.perf_counter()
            await stack.core.remotion_player.describe(A, 1)
            out["player_warm_describe_s"] = round(time.perf_counter() - started, 3)
            started = time.perf_counter()
            status, run = await stack.start(pid)
            out["playback_start_s"] = round(time.perf_counter() - started, 3)
            assert status == 200, run
            props_edit = []
            for index in range(samples):
                started = time.perf_counter()
                status, answer = await stack.call("POST", "/v1/presentation-studio/playback/edit", json={
                    "actor": "user", "ops": [{"op": "control.set", "scene_id": S1, "control_id": "headline", "value": f"Titre {index}"}]})
                props_edit.append(time.perf_counter() - started)
                assert status == 200, answer
            out["props_edit_roundtrip"] = stats(props_edit)
            await stack.call("POST", "/v1/presentation-studio/playback/stop", json={"actor": "user"})
            variants = f"/v1/presentation-studio/presentations/{pid}/variants/{vid}"
            source_edit = []
            for index in range(samples):
                _, variant = await stack.call("GET", variants)
                started = time.perf_counter()
                status, answer = await stack.call("POST", variants + "/source-edits", json={
                    "actor": "user", "basis": {"variant_revision": variant["revision"]}, "scene_id": S1,
                    "files": {"sources": {"src/Scene.tsx": SCENE_TSX.replace("#101820", f"#1018{index:02d}")}}})
                source_edit.append(time.perf_counter() - started)
                assert status == 200, answer
            out["source_edit_roundtrip"] = stats(source_edit)
            out["data_root_footprint_kb"] = footprint(stack.data_root)
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-dir", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--samples", type=int, default=5)
    args = parser.parse_args()
    result = asyncio.run(main(Path(args.runtime_dir), args.samples))
    Path(args.evidence).parent.mkdir(parents=True, exist_ok=True)
    Path(args.evidence).write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))

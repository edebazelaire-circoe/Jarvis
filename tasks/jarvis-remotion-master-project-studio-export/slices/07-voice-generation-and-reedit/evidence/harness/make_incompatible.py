"""Slice 07 refusal control: a native two-scene deck whose scenes declare different fps (30 and 25), made through Core's own assembly
route as the user (no model), so the brain can be asked to export « la vidéo » of a variant that is NOT master-ready.
`python make_incompatible.py <run>` prints the presentation and variant ids."""
import json
import sys

import bench

TSX = ('import React from "react";\nimport {AbsoluteFill} from "remotion";\n\n'
       'export default function Scene() {\n  return <AbsoluteFill style={{background: "#111", color: "#eee", fontSize: 90, '
       'justifyContent: "center", alignItems: "center"}}>Cadence {FPS}</AbsoluteFill>;\n}\n')


def bundle(key: str, fps: int) -> dict:
    return {"key": key, "remotion": {"title": f"Cadence {fps}", "files": {"src/Scene.tsx": TSX.replace("{FPS}", str(fps))},
                                     "composition": {"width": 1920, "height": 1080, "fps": fps, "duration_in_frames": 3 * fps}}}


m = bench.meta(sys.argv[1])
body = {"actor": "user", "brief": {"title": "Deux cadences", "workflow": "directed", "authoring": "native", "language": "fr"},
        "draft": {"prefabs": [bundle("trente", 30), bundle("vingtcinq", 25)],
                  "scenes": [{"key": "trente", "title": "Trente", "prefab": {"bundle": "trente"}},
                             {"key": "vingtcinq", "title": "Vingt-cinq", "prefab": {"bundle": "vingtcinq"}}]}}
status, made = bench.core(m, "POST", "/v1/presentation-studio/authoring/assemble", body)
print(status, json.dumps({k: made.get(k) for k in ("status", "presentation_id", "active_variant_id")} if isinstance(made, dict) else made))

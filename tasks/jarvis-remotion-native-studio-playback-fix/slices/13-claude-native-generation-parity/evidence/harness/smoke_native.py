"""No-model smoke of the native loop on an isolated stack (`bench.py jarvis-up <run>` first): the native guide's example is assembled as the
brain would (real compiler), one scene is rewritten through the source-edit route without a request id (authoring record), and frames are
rendered by the real guarded render host. Prints one JSON line per step; writes `smoke.json` in the run folder."""
from __future__ import annotations

import json
import sys
import time

import bench

sys.path.insert(0, str(bench.BRN))
from jarvis.domain.presentation_studio_authoring_guide import native_example  # noqa: E402


def main(run: str) -> None:
    m = bench.meta(run)
    report: dict = {}
    example = native_example()
    started = time.monotonic()
    status, body = bench.core(m, "POST", "/v1/presentation-studio/authoring/assemble", {"actor": "brain", **example}, timeout=180)
    report["assemble"] = {"http": status, "elapsed_ms": round((time.monotonic() - started) * 1000),
                          "status": body.get("status") if isinstance(body, dict) else body,
                          "warnings": sorted({w["code"] for w in (body.get("report") or {}).get("warnings", [])}) if isinstance(body, dict) else None,
                          "failures": [(f["code"], f["message"][:200]) for f in (body.get("report") or {}).get("failures", [])] if isinstance(body, dict) else None,
                          "source_requests": len(body.get("source_requests") or []) if isinstance(body, dict) else None}
    print(json.dumps(report["assemble"], ensure_ascii=False))
    if status != 201:
        raise SystemExit(1)
    pid, vid = body["presentation_id"], body["active_variant_id"]
    scene = body["scenes"][0]["scene_id"]
    _, variant = bench.core(m, "GET", f"/v1/presentation-studio/presentations/{pid}/variants/{vid}")
    tsx = example["draft"]["prefabs"][0]["remotion"]["files"]["src/Scene.tsx"].replace("Remplace ce titre", "Titre reecrit par l'agent")
    started = time.monotonic()
    status, edit = bench.core(m, "POST", f"/v1/presentation-studio/presentations/{pid}/variants/{vid}/source-edits",
                              {"actor": "brain", "basis": {"variant_revision": variant["revision"]}, "scene_id": scene,
                               "files": {"sources": {"src/Scene.tsx": tsx}}}, timeout=120)
    report["source_edit"] = {"http": status, "elapsed_ms": round((time.monotonic() - started) * 1000),
                             "status": edit.get("status") if isinstance(edit, dict) else edit,
                             "prefab": edit.get("prefab") if isinstance(edit, dict) else None}
    print(json.dumps(report["source_edit"], ensure_ascii=False))
    started = time.monotonic()
    status, preview = bench.core(m, "POST", "/v1/local-capabilities/remotion/render/preview",
                                 {"presentation_id": pid, "variant_id": vid, "scene_id": scene, "frames": [5, 60, 200]}, timeout=200)
    report["preview"] = {"http": status, "elapsed_ms": round((time.monotonic() - started) * 1000),
                         "body": preview if not isinstance(preview, dict) else {k: v for k, v in preview.get("preview", {}).items()
                                                                                if k in ("frames", "prefab", "elapsed_ms", "scale")}}
    print(json.dumps(report["preview"], ensure_ascii=False)[:600])
    # A second preview of another scene right after the first (two real runs lost Core at this point).
    other = body["scenes"][1]["scene_id"]
    started = time.monotonic()
    status, second = bench.core(m, "POST", "/v1/local-capabilities/remotion/render/preview",
                                {"presentation_id": pid, "variant_id": vid, "scene_id": other}, timeout=200)
    report["preview_2"] = {"http": status, "elapsed_ms": round((time.monotonic() - started) * 1000),
                           "frames": len((second.get("preview") or {}).get("frames") or []) if isinstance(second, dict) else second}
    print(json.dumps(report["preview_2"], ensure_ascii=False)[:600])
    status, alive = bench.core(m, "GET", "/v1/local-capabilities/remotion/render", timeout=20)
    report["core_alive_after"] = status
    print("core alive:", status)
    (bench.run_dir(run) / "smoke.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])

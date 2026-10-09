"""Harnais de compilation RÉELLE d'une scène Remotion (Slice 05 de jarvis-remotion-presentation-integration).

Vrai `LocalCapabilityHost` + vrai `NodeCapabilityRunner` (vrai npm, vrai réseau pour l'installation), vrai `PrefabService`
sur une vraie bibliothèque de prefabs, vrai Node + esbuild du verrou pour la compilation, vrai Chrome pour le Player. Racine de
données PRIVÉE (refuse toute racine sous `~/.jarvis`) ; ne démarre ni n'arrête Core, le Control Center ni la voix.

    python scripts/remotion_compile_harness.py --work-dir C:/Users/<moi>/AppData/Local/Temp/jrs5 \
        --evidence tasks/jarvis-remotion-presentation-integration/slices/05-remotion-project-source-contract/evidence/real-compile.json

`--reuse-root <dossier>` réutilise une installation déjà faite par ce harnais (saute les ~35 s de `npm ci`).
Sortie : un JSON de preuve (environnement, SHA du dépôt, durées, tailles, résultats typés, texte rendu par le Player).
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import functools
import http.server
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis.adapters.file_local_capability_store import FileLocalCapabilityStore  # noqa: E402
from jarvis.adapters.file_prefab_library import LIBRARY_DIR, FilePrefabLibrary  # noqa: E402
from jarvis.adapters.node_capability_runner import default_remotion_runner  # noqa: E402
from jarvis.adapters.remotion_compiler import build_remotion_compiler, shipped_engine_pin  # noqa: E402
from jarvis.core.prefab_service import PrefabService  # noqa: E402
from jarvis.domain import remotion_compile as rc  # noqa: E402
from jarvis.domain.remotion_source import Composition, build_candidate  # noqa: E402
from scripts.remotion_install_harness import CID, Sink, make_host, runtime  # noqa: E402

SCENE_ID = "presentation-studio.p0000000000a1.s0000000000b1"
CHROME = (Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
          Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe")
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c63f8cfc0f01f00050001ffabce36890000000049454e44ae426082")

SCENE_TSX = """import React from "react";
import {AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame} from "remotion";
import {Title} from "./lib/Title";
import {palette} from "./theme.json";

export default function Scene(props: {title: string; accent: string}) {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 10], [0, 1], {extrapolateRight: "clamp"});
  return (
    <AbsoluteFill id="scene" style={{background: palette.background, opacity: Math.max(opacity, 0.5)}}>
      <Title text={props.title} color={props.accent} />
      <Img id="dot" src={staticFile("dot.png")} style={{width: 16, height: 16}} />
    </AbsoluteFill>
  );
}
"""
TITLE_TSX = 'import React from "react";\nexport const Title = ({text, color}: {text: string; color: string}) => <h1 id="title" style={{color}}>{text}</h1>;\n'
FILES = {"src/Scene.tsx": SCENE_TSX, "src/lib/Title.tsx": TITLE_TSX, "src/theme.json": '{"palette": {"background": "#101820"}}\n',
         "public/dot.png": PNG}
PROPS = {"type": "object", "properties": {"title": {"type": "string", "default": "Bonjour", "max_length": 80},
                                          "accent": {"type": "color", "default": "#3366ff"}}}


def candidate(files=None):
    return build_candidate(prefab_id=SCENE_ID, title="Scène de preuve", composition=Composition("Scene", 1280, 720, 30, 90),
                           engine=shipped_engine_pin(), files=files or FILES, props=PROPS,
                           sample={"props": {"title": "Bonjour", "accent": "#3366ff"}, "data": {}})


def tree(path: Path) -> list[str]:
    return sorted(str(p.relative_to(path)).replace("\\", "/") for p in path.rglob("*") if p.is_file())


def forbidden_names(path: Path) -> list[str]:
    return sorted({p.name for p in path.rglob("*") if p.name in ("node_modules", "package.json", "package-lock.json")})


def timed(fn):
    start = time.monotonic()
    result = fn()
    return result, round(time.monotonic() - start, 2)


def typed(compiler, source, **options) -> dict:
    try:
        compiler.compile_scene(source, **options)
    except rc.RemotionCompileError as exc:
        return {"code": exc.code.value, "status": exc.status, "message": exc.message,
                "diagnostics": [d.to_dict() for d in exc.diagnostics[:3]]}
    return {"code": None}


def browser(chrome: Path, compiler, host_art, scene_art, work: Path) -> dict:
    page = work / "player"
    shutil.rmtree(page, ignore_errors=True)
    page.mkdir(parents=True)
    shutil.copy(compiler.resolve_output_file(host_art.cache_key, "host.js"), page / "host.js")
    shutil.copy(compiler.resolve_output_file(scene_art.cache_key, "scene.js"), page / "scene.js")
    public = page / "public"
    public.mkdir()
    shutil.copy(compiler.resolve_output_file(scene_art.cache_key, "public/dot.png"), public / "dot.png")
    (page / "index.html").write_text("""<!doctype html><html><head><meta charset="utf-8"></head><body><div id="root" style="width:320px;height:180px"></div><pre id="out">pending</pre>
<script>window.remotion_staticBase = "/public"; // staticFile() always returns "/" + base: the base is a path of the serving origin</script>
<script src="host.js"></script><script src="scene.js"></script>
<script>
try {
  const H = globalThis.__JARVIS_HOST__;
  H["react-dom/client"].createRoot(document.getElementById("root")).render(H.react.createElement(H["@remotion/player"].Player, {
    component: JarvisScene.component, durationInFrames: 90, fps: 30, compositionWidth: 1280, compositionHeight: 720,
    inputProps: {title: "Player evidence", accent: "#ff8800"}, controls: false, style: {width: 320, height: 180}}));
  setTimeout(() => {
    const img = document.getElementById("dot");
    document.getElementById("out").textContent = JSON.stringify({title: (document.getElementById("title") || {}).innerText || null,
      color: (document.getElementById("title") || {style: {}}).style.color || null, image_loaded: !!img && img.complete && img.naturalWidth === 1,
      image_src: img ? img.getAttribute("src") : null, players: Object.keys(H)});
  }, 1500);
} catch (err) { document.getElementById("out").textContent = JSON.stringify({error: String(err && err.message || err)}); }
</script></body></html>""", encoding="utf-8")
    profile = Path(tempfile.mkdtemp(prefix="jrs5-chrome-"))

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):  # noqa: D401 - silence
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(page)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        out = subprocess.run([str(chrome), "--headless=new", "--disable-gpu", "--no-sandbox", "--virtual-time-budget=6000",
                              f"--user-data-dir={profile}", "--dump-dom", f"http://127.0.0.1:{server.server_address[1]}/index.html"],
                             capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace").stdout
    finally:
        server.shutdown()
        shutil.rmtree(profile, ignore_errors=True)
    marker = '<pre id="out">'
    if marker not in out:
        return {"error": "Chrome returned no page", "tail": out[-300:]}
    return json.loads(out.split(marker, 1)[1].split("</pre>", 1)[0].replace("&quot;", '"').replace("&amp;", "&"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--reuse-root", default=None)
    args = parser.parse_args()
    work = Path(args.work_dir).resolve()
    if ".jarvis" in work.parts:
        print("refused: the work dir must not live under ~/.jarvis (the live profile)")
        return 2
    work.mkdir(parents=True, exist_ok=True)
    root = Path(args.reuse_root).resolve() if args.reuse_root else work / "compile-root"
    if not args.reuse_root:
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True)
    package = work / "empty-package"
    package.mkdir(exist_ok=True)
    report: dict = {"harness": "scripts/remotion_compile_harness.py", "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "platform": platform.platform(), "python": sys.version.split()[0],
                    "repo_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
                    "repo_dirty": bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip()),
                    "node": subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip(), "scenarios": {}}
    scenarios = report["scenarios"]
    store = FileLocalCapabilityStore(root)
    host, sink = make_host(root)
    if args.reuse_root:
        view = host.check_health(CID)
        scenarios["install"] = {"reused": True, "status": view["status"]}
    else:
        view, seconds = timed(lambda: host.install(CID))
        scenarios["install"] = {"seconds": seconds, "status": view["status"], "error": view.get("last_error_code")}
    if view["status"] not in ("ready", "running"):
        report["verdict"] = "FAILED: capability not ready"
        Path(args.evidence).write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 1
    # the runtime-host.mjs of the repository is the one the install copied (fresh install); a reused root must match
    same = (runtime(root) / "runtime-host.mjs").read_bytes() == (ROOT / "jarvis/capabilities/remotion/runtime-host.mjs").read_bytes()
    scenarios["install"]["runtime_host_matches_repository"] = same
    record = json.loads((runtime(root) / "install-record.json").read_text(encoding="utf-8"))
    scenarios["install"]["installed"] = record["installed"]

    # --- 1. publish a Remotion source as a prefab version, then "restart"
    sink_prefab = Sink()
    service = PrefabService(FilePrefabLibrary(package, root), diagnostics=sink_prefab)
    publication = asyncio.run(service.save(candidate(), actor="user"))
    revised = asyncio.run(service.save(candidate({**FILES, "src/lib/Title.tsx": TITLE_TSX + "// revision 2\n"}), actor="user"))
    folder = root / LIBRARY_DIR / SCENE_ID / "1"
    reopened = PrefabService(FilePrefabLibrary(package, root), diagnostics=Sink())
    asyncio.run(reopened.start())
    again = asyncio.run(reopened.remotion_source(SCENE_ID, 1))
    original = asyncio.run(service.remotion_source(SCENE_ID, 1))
    scenarios["source"] = {
        "prefab_id": SCENE_ID, "versions": [publication.version, revised.version], "fingerprint": publication.fingerprint,
        "layout": tree(folder), "forbidden_names_in_library": forbidden_names(root / LIBRARY_DIR),
        "reopened_digest_equal": again.digest == original.digest, "reopened_bytes_equal": dict(again.files) == dict(original.files),
        "digest": again.digest, "v1_untouched_after_revision": tree(folder) == tree(root / LIBRARY_DIR / SCENE_ID / "1"),
        "prefab_events": [e["kind"] for e in sink_prefab.events]}

    # --- 2. compile: host + scene, reuse, restart
    runner = default_remotion_runner()
    compiler = build_remotion_compiler(host, store, runner, diagnostics=(csink := Sink()))
    host_art, host_s = timed(compiler.compile_host)
    scene_art, scene_s = timed(lambda: compiler.compile_scene(again))
    scene_again, reuse_s = timed(lambda: compiler.compile_scene(again))
    host2, store2 = make_host(root)[0], FileLocalCapabilityStore(root)
    restarted = build_remotion_compiler(host2, store2, default_remotion_runner(), diagnostics=Sink())
    scene_restart, restart_s = timed(lambda: restarted.compile_scene(asyncio.run(reopened.remotion_source(SCENE_ID, 1))))
    scene_v2 = compiler.compile_scene(asyncio.run(service.remotion_source(SCENE_ID, 2)))
    scenarios["compile"] = {
        "host": {**host_art.to_public(), "seconds": host_s}, "scene": {**scene_art.to_public(), "seconds": scene_s},
        "reuse_in_process": {"reused": scene_again.reused, "seconds": reuse_s},
        "reuse_after_restart": {"reused": scene_restart.reused, "seconds": restart_s, "same_key": scene_restart.cache_key == scene_art.cache_key},
        "revision_gets_its_own_output": scene_v2.cache_key != scene_art.cache_key,
        "forbidden_names_in_compiled_cache": forbidden_names(runtime(root).parent / "compiled"),
        "compiled_layout": tree(runtime(root).parent / "compiled"), "events": [e["kind"] for e in csink.events]}
    public_text = json.dumps(scenarios["compile"])
    scenarios["compile"]["public_form_has_no_absolute_path"] = str(root) not in public_text and str(root).replace("\\", "/") not in public_text

    # --- 3. typed failures with the real compiler
    failures = {}
    base = dict(FILES)
    cases = {
        "syntax_error": {**base, "src/lib/Title.tsx": "export const Title = () => <h1>{</h1>;\n"},
        "forbidden_import_fs": {**base, "src/lib/Title.tsx": 'import fs from "fs";\nexport const Title = () => <h1>{String(fs)}</h1>;\n'},
        "import_escapes_source": {**base, "src/lib/Title.tsx": 'import x from "../../outside";\nexport const Title = () => <h1>{String(x)}</h1>;\n'},
        "missing_default_export": {**base, "src/Scene.tsx": "export const Scene = () => null;\n"},
    }
    for name, files in cases.items():
        src = asyncio.run(_variant_source(package, root, name, files))
        failures[name] = typed(compiler, src)
    slow = build_remotion_compiler(host, store, default_remotion_runner(), diagnostics=Sink())
    slow._timeouts[rc.CompileTarget.SCENE] = 0.001  # noqa: SLF001 - harness forces the deadline
    failures["deadline"] = typed(slow, asyncio.run(_variant_source(package, root, "slow", {**base, "src/lib/Title.tsx": TITLE_TSX + "// slow\n"})))
    scenarios["typed_failures"] = failures
    scenarios["typed_failures"]["no_orphan_tmp_in_cache"] = not [p for p in (runtime(root).parent / "compiled").iterdir() if p.name.startswith(".tmp-")]

    # --- 4. the browser: the Player renders the compiled scene with a shared host
    chrome = next((c for c in CHROME if c.is_file()), None)
    scenarios["browser_player"] = browser(chrome, compiler, host_art, scene_art, work) if chrome else {"skipped": "Chrome absent"}

    # --- 5. uninstalling the capability never touches the sources; compile then refuses with a typed error
    before = {p: (folder / p).read_bytes() for p in tree(folder)}
    host.uninstall(CID)
    after = {p: (folder / p).read_bytes() for p in tree(folder)}
    refused = typed(compiler, again)
    scenarios["uninstall"] = {"sources_identical_bytes": before == after, "compile_after_uninstall": refused,
                              "compiled_cache_kept": bool(tree(runtime(root).parent / "compiled"))}
    ok = (scenarios["source"]["reopened_digest_equal"] and scenarios["source"]["reopened_bytes_equal"]
          and not scenarios["source"]["forbidden_names_in_library"] and not scenarios["compile"]["forbidden_names_in_compiled_cache"]
          and scene_again.reused and scene_restart.reused and scenarios["compile"]["public_form_has_no_absolute_path"]
          and failures["syntax_error"]["code"] == "compile_source_error" and failures["forbidden_import_fs"]["code"] == "compile_import_refused"
          and failures["import_escapes_source"]["code"] == "compile_import_refused"
          and failures["missing_default_export"]["code"] == "compile_entry_invalid" and failures["deadline"]["code"] == "compile_timeout"
          and scenarios["browser_player"].get("title") == "Player evidence" and scenarios["browser_player"].get("image_loaded") is True
          and scenarios["uninstall"]["sources_identical_bytes"] and refused["code"] == "compile_runtime_unavailable")
    report["verdict"] = "PASSED" if ok else "FAILED"
    Path(args.evidence).parent.mkdir(parents=True, exist_ok=True)
    Path(args.evidence).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(report["verdict"], args.evidence)
    return 0 if ok else 1


async def _variant_source(package: Path, root: Path, name: str, files: dict):
    """Source Remotion d'une variante de scène, publiée sous son propre id (jamais l'id de la scène de preuve)."""

    service = PrefabService(FilePrefabLibrary(package, root))
    prefab_id = "presentation-studio.p0000000000a1.s" + format(sum(map(ord, name)) * 7919 % 16**12, "012x")
    cand = build_candidate(prefab_id=prefab_id, title=f"Variante {name}", composition=Composition("Scene", 1280, 720, 30, 90),
                           engine=shipped_engine_pin(), files=files, props=PROPS, sample={"props": {}, "data": {}})
    await service.save(cand, actor="user")
    return await service.remotion_source(prefab_id, 1)


if __name__ == "__main__":
    raise SystemExit(main())

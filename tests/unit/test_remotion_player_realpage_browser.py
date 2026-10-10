"""Une scène Remotion jouée par Jarvis, dans le VRAI Control Center, un VRAI Chrome, un Core isolé (Slice 10).

Opt-in : exige une installation Remotion existante (`JARVIS_REMOTION_RUNTIME_DIR` = son dossier `runtime/`, comme
`test_remotion_compiler_real.py`), Node et Chrome ; sans eux ces épreuves sont ignorées (elles n'installent jamais rien).

Réel : `JarvisCoreApplication` composé comme `jarvis/app.py` (magasin de capacités, runner Node, bac à sable sur une adresse de
boucle locale à part), le compilateur (Node + esbuild du verrou), `LocalProtocolServer`, le `ControlCenter` servi sur HTTP, la page
de scène, le Player de Remotion, le chien de garde. Simulé : seulement l'affichage sans tête et le puits d'exfiltration (un petit
serveur HTTP qui journalise tout) ; la capacité est « prête » par copie des petits fichiers d'une installation et jonction de
`node_modules` (jamais une installation de plus).

Prouvé (mesuré) : lecture de bout en bout depuis une Presentation, changement de couleur / titre / durée à chaud sans rendu, passage
de scène en scène, plein écran, démarrage muet puis son sur un vrai geste ; moteur indisponible (aucune lecture, jamais de HTML) ;
erreur de compilation (fichier:ligne:colonne) ; cadre figé retiré par le chien de garde avec sa raison et « Recharger » ; une
scène qui navigue vers une origine de Jarvis n'envoie aucune requête (`frame-src`).
"""

from __future__ import annotations

import asyncio
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading

import pytest

from jarvis.adapters.remotion_compiler import shipped_engine_pin
from jarvis.domain.scene import (
    Representation, SceneActor, SceneCommand, SceneObjectFields, SceneObjectKind, SceneOp, ScenePayload, ScenePrefabRef,
)
from tests.fakes.remotion_hostile import SAMPLES
from tests.fakes.remotion_player_stack import TOKEN, RemotionStack, free_port, runtime_dir_from_env
from tests.unit.test_fullscreen_browser import _chrome

DRIVER = Path(__file__).parent / "_remotion_stage_browser.mjs"
RUNTIME = runtime_dir_from_env()
pytestmark = pytest.mark.skipif(RUNTIME is None or shutil.which("node") is None,
                                reason="needs JARVIS_REMOTION_RUNTIME_DIR (an existing Remotion install), node and Chrome")

A, B = "presentation-studio.p000000000001.s000000000001", "presentation-studio.p000000000001.s000000000002"
S1, S2 = "pss_000000000001", "pss_000000000002"

SCENE_TSX = """import React from "react";
import {AbsoluteFill, interpolate, useCurrentFrame} from "remotion";

export default function Scene(props: {title: string; accent: string; fade: number}) {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, Math.max(props.fade, 1)], [0, 1], {extrapolateRight: "clamp"});
  return (
    <AbsoluteFill style={{background: "#101820"}}>
      <h1 id="title" style={{color: props.accent, opacity, fontSize: 90}}>{props.title}</h1>
      <p id="fade" style={{color: "#fff"}}>{String(props.fade)}</p>
      <p id="frame" style={{color: "#fff"}}>{String(frame)}</p>
    </AbsoluteFill>
  );
}
"""
PROPS = {"type": "object", "properties": {"title": {"type": "string", "default": "Bonjour", "max_length": 80},
                                          "accent": {"type": "color", "default": "#3366ff"},
                                          "fade": {"type": "integer", "default": 10, "min": 1, "max": 90}}}
SAMPLE = {"props": {"title": "Bonjour", "accent": "#3366ff", "fade": 10}, "data": {}}
CONTROLS = [{"control_id": "headline", "path": "props.title", "label": "Titre", "group": "content"},
            {"control_id": "accent", "path": "props.accent", "label": "Accent", "group": "visual"},
            {"control_id": "fade", "path": "props.fade", "label": "Durée du fondu", "group": "motion"}]

STAGE = "document.querySelector('iframe[data-remotion-stage]')"
SHELL = f"{STAGE}.contentWindow.__remotionStage.state()"
READY = {"until": f"!!{STAGE} && !!{STAGE}.contentWindow.__remotionStage && {SHELL}.phase==='ready'", "ms": 60000}
SANDBOX = {"scope": "sandbox"}
TITLE = "document.querySelector('#title') && document.querySelector('#title').textContent"


def scene(scene_id: str, prefab_id: str, title: str, **props) -> dict:
    return {"scene_id": scene_id, "prefab": {"id": prefab_id, "version": 1}, "title": title,
            "props": {"title": title, "accent": "#3366ff", "fade": 10, **props}, "data": {}, "controls": CONTROLS, "anchors": []}


def drive(url: str, plan: list, *, viewport: str = "1280x720") -> dict:
    done = subprocess.run(["node", str(DRIVER), url, _chrome(), json.dumps(plan)], capture_output=True, text=True, encoding="utf-8",
                          timeout=300, check=False, env={**os.environ, "CDP_VIEWPORT": viewport})
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


async def run(url: str, plan: list, **kwargs) -> dict:
    # The blocking subprocess runs in a thread so the event loop keeps serving Core and the Control Center.
    return await asyncio.to_thread(drive, url, plan, **kwargs)


def http_step(stack: RemotionStack, name: str, method: str, path: str, body: dict | None = None) -> dict:
    return {"http": {"method": method, "url": stack.core_url + path, "headers": {"Authorization": f"Bearer {TOKEN}"},
                     **({"json": body} if body is not None else {})}, "as": name}


def edit_step(stack: RemotionStack, name: str, *ops: dict) -> dict:
    return http_step(stack, name, "POST", "/v1/presentation-studio/playback/edit", {"actor": "user", "ops": list(ops)})


def control(scene_id: str, control_id: str, value) -> dict:
    return {"op": "control.set", "scene_id": scene_id, "control_id": control_id, "value": value}


class Sink:
    """The attacker's (and "the visualizer's") listener: records every request it receives."""

    def __init__(self, host: str = "127.0.0.3") -> None:
        self.requests: list[str] = []
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                owner.requests.append(self.path)
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body>sink</body></html>")

            do_POST = do_GET  # noqa: N815

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer((host, 0), Handler)
        self.origin = f"http://{host}:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def record_evidence(name: str, payload: dict, *shots: str) -> None:
    """With `JARVIS_REMOTION_EVIDENCE_DIR` set (`scripts/remotion_player_harness.py`), keep what this test measured and its screenshots."""

    folder = os.environ.get("JARVIS_REMOTION_EVIDENCE_DIR")
    if not folder:
        return
    target = Path(folder)
    target.mkdir(parents=True, exist_ok=True)
    kept = []
    for shot in shots:
        if Path(shot).exists():
            shutil.copy2(shot, target / Path(shot).name)
            kept.append(Path(shot).name)
    (target / f"{name}.json").write_text(json.dumps({"scenario": name, "screenshots": kept, **payload}, indent=2, ensure_ascii=False, default=str),
                                         encoding="utf-8")


def noise(result: dict) -> list[str]:
    return [line for line in result["console"] if line.startswith("page error")] + result["errors"]


# ------------------------------------------------------------------ the whole way, from a presentation to the screen

async def test_a_remotion_scene_plays_edits_switches_and_goes_fullscreen_from_a_presentation(tmp_path):
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        await stack.publish(A, {"src/Scene.tsx": SCENE_TSX}, title="Un", props=PROPS, sample=SAMPLE)
        await stack.publish(B, {"src/Scene.tsx": SCENE_TSX}, title="Deux", props=PROPS, sample=SAMPLE)
        pid, _ = await stack.presentation([scene(S1, A, "Premier"), scene(S2, B, "Second")])
        status, started = await stack.start(pid)
        assert status == 200 and started["state"]["phase"] == "playing", started
        shot = str(tmp_path / "windowed.png")
        result = await run(stack.page_url, [
            {"wait": 500}, READY, {"wait": 1200},
            # --- plays: the frame counter of the SCENE (read inside the sandbox) moves without any gesture
            {"value": "title", "expr": TITLE, **SANDBOX},
            {"value": "frame_a", "expr": "Number(document.querySelector('#frame').textContent)", **SANDBOX},
            {"wait": 900}, {"value": "frame_b", "expr": "Number(document.querySelector('#frame').textContent)", **SANDBOX},
            {"value": "shell", "expr": SHELL},
            {"value": "isolation", "expr": "(()=>{let t;try{t=parent.document.title}catch(e){t=e.name}let s;try{s=localStorage.length}catch(e){s=e.name}"
                                             "return {href:location.href.slice(0,24),parent:t,storage:s,origin:self.origin}})()", **SANDBOX},
            {"value": "frames", "expr": "document.querySelectorAll('iframe[data-remotion-stage]').length"},
            {"shot": shot},
            # --- editable while it plays: colour, title, timing, five rapid edits; no render, the same sandbox frame
            {"value": "frame_id_before", "expr": "document.querySelector('iframe[data-remotion-stage]').contentWindow.__remotionStage.state().generation"},
            edit_step(stack, "edit1", control(S1, "headline", "Titre modifié"), control(S1, "accent", "#ff0000"), control(S1, "fade", 60)),
            {"until": f"{TITLE}==='Titre modifié'", "ms": 8000, **SANDBOX},
            {"value": "after_edit", "expr": "({title:document.querySelector('#title').textContent,color:getComputedStyle(document.querySelector('#title')).color,"
                                             "fade:document.querySelector('#fade').textContent})", **SANDBOX},
            edit_step(stack, "rapid1", control(S1, "accent", "#00ff00")), edit_step(stack, "rapid2", control(S1, "accent", "#0000ff")),
            edit_step(stack, "rapid3", control(S1, "accent", "#ffff00")), edit_step(stack, "rapid4", control(S1, "fade", 5)),
            edit_step(stack, "rapid5", control(S1, "accent", "#ff00ff")),
            {"until": "getComputedStyle(document.querySelector('#title')).color==='rgb(255, 0, 255)'", "ms": 8000, **SANDBOX},
            {"value": "after_rapid", "expr": "({color:getComputedStyle(document.querySelector('#title')).color,fade:document.querySelector('#fade').textContent})", **SANDBOX},
            {"value": "generation_after_edits", "expr": "document.querySelector('iframe[data-remotion-stage]').contentWindow.__remotionStage.state().generation"},
            {"value": "same_frame", "expr": "document.querySelectorAll('iframe[data-remotion-stage]').length"},
            # --- play / pause / seek from the window host
            {"value": "pause", "expr": f"{STAGE}.contentWindow.__remotionStage.control('pause')"},
            {"wait": 500},
            {"value": "paused_a", "expr": "Number(document.querySelector('#frame').textContent)", **SANDBOX}, {"wait": 700},
            {"value": "paused_b", "expr": "Number(document.querySelector('#frame').textContent)", **SANDBOX},
            {"value": "seek", "expr": f"{STAGE}.contentWindow.__remotionStage.control('seek',45)"},
            {"until": "Number(document.querySelector('#frame').textContent)===45", "ms": 5000, **SANDBOX},
            {"value": "seeked", "expr": "Number(document.querySelector('#frame').textContent)", **SANDBOX},
            # --- switch scenes: the stage window is patched to the other source, one frame, no leftover
            http_step(stack, "resume", "POST", "/v1/presentation-studio/playback/resume", {"actor": "user"}),
            http_step(stack, "next", "POST", "/v1/presentation-studio/playback/next", {"actor": "user"}),
            {"until": f"{TITLE}==='Second'", "ms": 30000, **SANDBOX},
            {"value": "second", "expr": TITLE, **SANDBOX},
            {"until": "document.querySelectorAll('iframe[data-remotion-stage]').length===1", "ms": 3000},
            {"value": "frames_after_next", "expr": "document.querySelectorAll('iframe[data-remotion-stage]').length"},
            http_step(stack, "previous", "POST", "/v1/presentation-studio/playback/previous", {"actor": "user"}),
            {"until": f"{TITLE}==='Premier' || {TITLE}==='Titre modifié'", "ms": 30000, **SANDBOX},
            {"value": "back", "expr": TITLE, **SANDBOX},
            {"until": "document.querySelectorAll('iframe[data-remotion-stage]').length===1", "ms": 3000},
            # --- the sound is a gesture inside the frame: the scene started silent and a real click unlocks it
            {"until": f"{SHELL}.phase==='ready'", "ms": 30000},
            {"value": "muted_before", "expr": f"{SHELL}.muted"},
            {"clickExpr": f"(()=>{{const r={STAGE}.getBoundingClientRect();return {{x:r.left+r.width/2,y:r.top+r.height/2}}}})()"},
            {"until": f"{SHELL}.muted===false", "ms": 8000},
            {"value": "muted_after", "expr": f"{SHELL}.muted"},
            # --- fullscreen: a real click on the band's button (the user gesture), the scene fills the screen, Esc-equivalent leaves it
            {"click": ".jvsp-full"}, {"until": "!!document.fullscreenElement", "ms": 8000}, {"wait": 1000},
            {"value": "fullscreen", "expr": f"(()=>{{const f={STAGE};const d=f.contentDocument;const r=e=>{{const b=e.getBoundingClientRect();return [Math.round(b.width),Math.round(b.height)]}};"
                                          "return {on:!!document.fullscreenElement,shell:r(f),sandbox:r(d.querySelector('.rs-frame')),vw:innerWidth,vh:innerHeight}})()"},
            {"shot": str(tmp_path / "fullscreen.png")},
            {"eval": "document.exitFullscreen()"}, {"until": "!document.fullscreenElement", "ms": 5000},
            {"value": "after_fullscreen", "expr": f"({{on:!!document.fullscreenElement,phase:{SHELL}.phase}})"},
        ])
        reads = result["reads"]
        assert "failed" not in reads, reads
        assert reads["title"] == "Premier" and reads["frame_b"] != reads["frame_a"], "the scene plays without any gesture"
        assert reads["shell"]["phase"] == "ready" and reads["shell"]["muted"] is True and reads["frames"] == 1
        assert reads["isolation"]["href"].startswith("http://127.77.0.2:") and reads["isolation"]["parent"] == "SecurityError"
        assert reads["isolation"]["storage"] == "SecurityError" and reads["isolation"]["origin"] == "null"
        for name in ("edit1", "rapid1", "rapid2", "rapid3", "rapid4", "rapid5"):
            assert reads[name]["status"] == 200 and reads[name]["body"]["status"] in ("applied", "stale") or reads[name]["body"].get("edit"), (name, reads[name])
        assert reads["after_edit"] == {"title": "Titre modifié", "color": "rgb(255, 0, 0)", "fade": "60"}
        assert reads["after_rapid"] == {"color": "rgb(255, 0, 255)", "fade": "5"}, "five rapid edits: the last values won, no render, no remount"
        assert reads["generation_after_edits"] == reads["frame_id_before"] and reads["same_frame"] == 1
        assert reads["pause"] is True and reads["paused_a"] == reads["paused_b"], "pause holds the frame"
        assert reads["seeked"] == 45
        assert reads["second"] == "Second" and reads["frames_after_next"] == 1, "one stage frame, the previous scene's frame is gone"
        assert reads["back"] in ("Premier", "Titre modifié")
        assert reads["muted_before"] is True and reads["muted_after"] is False
        fullscreen = reads["fullscreen"]
        assert fullscreen["on"] is True and fullscreen["shell"] == [fullscreen["vw"], fullscreen["vh"]] == fullscreen["sandbox"]
        assert reads["after_fullscreen"]["on"] is False and reads["after_fullscreen"]["phase"] == "ready"
        assert not noise(result), noise(result)
        assert Path(shot).stat().st_size > 2000
        trace = [row["kind"] for row in stack.trace()]
        record_evidence("play_edit_switch_fullscreen", {"reads": reads, "console": result["console"][-30:], "errors": result["errors"],
                                                          "journal": sorted(set(stack.kinds()) | set(trace))}, shot, str(tmp_path / "fullscreen.png"))
        assert "remotion.stage.ready" in trace
        assert {"core.presentation_studio.engine_resolved", "remotion.compile.done", "remotion.sandbox.listening",
                "core.remotion_player.described"} <= set(stack.kinds()), "the normal path is journalled too"


# ------------------------------------------------------------------ failures: typed, visible, never HTML

async def test_without_the_runtime_nothing_plays_and_nothing_falls_back_to_html(tmp_path):
    async with RemotionStack(tmp_path, runtime_dir=None) as stack:
        await stack.publish(A, {"src/Scene.tsx": SCENE_TSX}, title="Un", props=PROPS, sample=SAMPLE)
        pid, _ = await stack.presentation([scene(S1, A, "Premier")])
        # The engine gate: the Presentation's own engine is not ready -> typed refusal, and NOTHING reaches the scene.
        status, refused = await stack.start(pid)
        assert status == 409 and refused["error"]["code"] == "presentation_studio_engine_unavailable", refused
        assert "not_installed" in refused["error"]["message"] and "Repair" in refused["error"]["message"]
        for verb, body in (("edit", {"actor": "user", "ops": [control(S1, "headline", "x")]}),):
            status, answer = await stack.call("POST", f"/v1/presentation-studio/playback/{verb}", json=body)
            assert status in (404, 409), (verb, status, answer)
        _, snapshot = await stack.call("GET", "/v1/scene/snapshot")
        objects = snapshot["snapshot"]["objects"]
        assert not [o for o in objects if str(o.get("object_id", "")).startswith("studio-")], "no stage window, no HTML, nothing"
        _, state = await stack.call("GET", "/v1/presentation-studio/playback")
        assert state["state"]["phase"] == "idle"
        # The explicit edit API of the Presentation is refused by the same gate (the engine of THIS presentation is not ready).
        base = f"/v1/presentation-studio/presentations/{pid}"
        _, view = await stack.call("GET", base)
        variant = view["variants"][0]
        status, edited = await stack.call("POST", f"{base}/variants/{variant['variant_id']}/edits", json={
            "actor": "user", "mode": "preview", "basis": {"variant_revision": variant["revision"]}, "ops": [control(S1, "headline", "x")]})
        assert status == 409 and edited["error"]["code"] == "presentation_studio_engine_unavailable", edited
        assert "core.presentation_studio.engine_refused" in stack.kinds()
        record_evidence("runtime_missing_api", {"start": {"status": 409, "error": refused["error"]}, "edit_preview": {"status": status, "error": edited["error"]},
                                                 "scene_objects": [o.get("object_id") for o in objects], "playback_phase": state["state"]["phase"],
                                                 "journal": sorted(set(stack.kinds()))})


async def test_a_remotion_window_on_the_scene_says_in_the_window_that_the_engine_is_unavailable(tmp_path):
    """The stage UI, not only the API: a Remotion window that reaches the page without a runtime shows the typed state and the repair."""

    async with RemotionStack(tmp_path, runtime_dir=None) as stack:
        await stack.publish(A, {"src/Scene.tsx": SCENE_TSX}, title="Un", props=PROPS, sample=SAMPLE)
        update = await stack.core.scene.apply(SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=SceneActor.USER, object_id="win-remotion", fields=SceneObjectFields(
            kind=SceneObjectKind.WINDOW, category="remotion_test", representation=Representation.WINDOW,
            payload=ScenePayload(title="Scène Remotion", prefab=ScenePrefabRef(A, 1, {"title": "Bonjour"}, {})))))
        assert update.outcome.value == "applied", update
        result = await run(stack.page_url, [
            {"wait": 500},
            {"until": f"!!{STAGE} && !!{STAGE}.contentWindow.__remotionStage && {SHELL}.phase==='failed'", "ms": 30000},
            {"value": "panel", "expr": f"{STAGE}.contentDocument.getElementById('stage').innerText"},
            {"value": "band", "expr": "(document.querySelector('.sc-prefab-error')||{}).textContent||null"},
            {"value": "html_frames", "expr": "document.querySelectorAll('iframe[srcdoc]').length"},
            {"value": "state", "expr": f"{SHELL}.phase"},
            {"shot": str(tmp_path / "unavailable.png")},
        ])
        reads = result["reads"]
        assert "failed" not in reads, reads
        assert "Remotion n’est pas disponible" in reads["panel"] and "not_installed" in reads["panel"] and "Réessayer" in reads["panel"]
        assert "Repair" in reads["panel"] and reads["state"] == "failed"
        assert reads["band"] is None, "the stage page says it in full; the window host adds no band over it"
        assert reads["html_frames"] == 0, "no HTML frame was ever mounted for a Remotion source"
        assert any(row["kind"] == "remotion.stage.failed" for row in stack.trace())
        record_evidence("runtime_missing_window", {"reads": reads, "console": result["console"][-20:], "errors": result["errors"],
                                                    "journal": sorted({row["kind"] for row in stack.trace()})}, str(tmp_path / "unavailable.png"))


async def test_a_scene_that_does_not_compile_shows_file_line_and_column_in_the_window(tmp_path):
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        broken = SCENE_TSX.replace("const frame = useCurrentFrame();", "const frame = useCurrentFrame(;")
        await stack.publish(A, {"src/Scene.tsx": broken}, title="Cassée", props=PROPS, sample=SAMPLE)
        pid, _ = await stack.presentation([scene(S1, A, "Cassée")])
        status, started = await stack.start(pid)
        assert status == 200, started
        result = await run(stack.page_url, [
            {"wait": 500},
            {"until": f"!!{STAGE} && !!{STAGE}.contentWindow.__remotionStage && {SHELL}.phase==='failed'", "ms": 60000},
            {"value": "panel", "expr": f"{STAGE}.contentDocument.getElementById('stage').innerText"},
            {"value": "frame_in_stage", "expr": f"{STAGE}.contentDocument.querySelectorAll('iframe').length"},
            {"shot": str(tmp_path / "compile_error.png")},
        ])
        reads = result["reads"]
        assert "failed" not in reads, reads
        assert "La scène ne compile pas" in reads["panel"] and "src/Scene.tsx:" in reads["panel"], reads["panel"]
        assert reads["frame_in_stage"] == 0, "no sandbox frame for a source that does not compile"
        assert "Core" not in reads["panel"].replace("Core est", "")
        record_evidence("compile_error", {"reads": reads, "errors": result["errors"]}, str(tmp_path / "compile_error.png"))


async def test_a_frozen_scene_is_removed_by_the_watchdog_with_its_reason_and_a_reload_action(tmp_path):
    loop = next(sample for sample in SAMPLES if sample.id == "infinite_loop")
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        files = {path: (data.replace("__ATTACKER__", "http://127.0.0.3:9") if isinstance(data, str) else data)
                 for path, data in loop.source("evasive").items()}
        await stack.publish(A, files, title="Boucle", props=None, sample=None)
        pid, _ = await stack.presentation([{"scene_id": S1, "prefab": {"id": A, "version": 1}, "title": "Boucle", "props": {}, "data": {},
                                           "controls": [], "anchors": []}])
        status, started = await stack.start(pid)
        assert status == 200, started
        result = await run(stack.page_url, [
            {"wait": 500},
            {"until": f"!!{STAGE} && !!{STAGE}.contentWindow.__remotionStage && {SHELL}.phase==='killed'", "ms": 60000},
            {"value": "state", "expr": SHELL},
            {"value": "panel", "expr": f"{STAGE}.contentDocument.getElementById('stage').innerText"},
            {"value": "sandbox_frames", "expr": f"{STAGE}.contentDocument.querySelectorAll('iframe').length"},
            {"value": "band", "expr": "(document.querySelector('.sc-prefab-error')||{}).textContent||null"},
            {"value": "page_alive", "expr": "performance.now()>0"},
            {"shot": str(tmp_path / "killed.png")},
            {"clickExpr": f"(()=>{{const b=[...{STAGE}.contentDocument.querySelectorAll('button')].find(x=>x.textContent==='Recharger la scène');"
                          f"const f={STAGE}.getBoundingClientRect();const r=b.getBoundingClientRect();return {{x:f.left+r.left+r.width/2,y:f.top+r.top+r.height/2}}}})()"},
            {"until": f"{SHELL}.generation>=2", "ms": 10000},
            {"until": f"{SHELL}.phase==='killed' && {SHELL}.generation>=2", "ms": 60000},
            {"value": "after_reload", "expr": f"({{generation:{SHELL}.generation,phase:{SHELL}.phase}})"},
        ])
        reads = result["reads"]
        assert "failed" not in reads, reads
        assert reads["state"]["killedReason"] == "unresponsive" and reads["sandbox_frames"] == 0
        assert "La scène ne répond plus depuis 3 s" in reads["panel"] and "Recharger la scène" in reads["panel"]
        assert reads["band"] is None and reads["page_alive"] is True
        assert reads["after_reload"]["generation"] >= 2 and reads["after_reload"]["phase"] == "killed", "reload restarted it, the watchdog removed it again"
        assert any(row["kind"] == "remotion.sandbox.killed" and row["data"].get("reason") == "unresponsive" for row in stack.trace())
        record_evidence("watchdog_kill_and_reload", {"reads": reads, "errors": result["errors"],
                                                      "journal": [row for row in stack.trace() if row["kind"].startswith("remotion.")]}, str(tmp_path / "killed.png"))


async def navigation_requests(tmp_path: Path, *, stage_policy=None) -> tuple[list[str], str, dict]:
    """Play the hostile self-navigation scene with the "visualizer" being the attacker's listener; return what the listener saw."""

    nav = next(sample for sample in SAMPLES if sample.id == "window_nav")
    sink = Sink()
    try:
        async with RemotionStack(tmp_path, runtime_dir=RUNTIME, visualizer_url=sink.origin) as stack:
            files = {path: (data.replace("__ATTACKER__", sink.origin) if isinstance(data, str) else data)
                     for path, data in nav.source("evasive", "frame_src_probe").items()}
            await stack.publish(A, files, title="Navigation", props=None, sample=None)
            pid, _ = await stack.presentation([{"scene_id": S1, "prefab": {"id": A, "version": 1}, "title": "Nav", "props": {}, "data": {},
                                               "controls": [], "anchors": []}])
            status, started = await stack.start(pid)
            assert status == 200, started
            result = await run(stack.page_url, [
                {"wait": 500},
                {"until": f"!!{STAGE} && !!{STAGE}.contentWindow.__remotionStage && ['ready','killed'].includes({SHELL}.phase)", "ms": 60000},
                {"wait": 6000},
                {"value": "state", "expr": f"({{phase:{SHELL}.phase,reason:{SHELL}.killedReason}})"},
                {"value": "supervisor", "expr": f"{SHELL}.supervisor"},
            ])
            _, headers, _ = await stack.get(f"/remotion-stage?id={A}&v=1")
            assert "failed" not in result["reads"], result["reads"]
            return list(sink.requests), headers["Content-Security-Policy"], {**result["reads"], "sink": sink.origin}
    finally:
        sink.close()


async def test_a_scene_that_navigates_to_an_origin_of_jarvis_sends_no_request(tmp_path):
    """`frame-src` of the stage document names the sandbox origin alone. The "visualizer" here is the attacker's own listener (the
    main page frames it, as it frames the real one): if the stage document allowed it, the navigation would land."""

    requests, policy, reads = await navigation_requests(tmp_path)
    record_evidence("frame_src_navigation", {"sink_requests": requests, "stage_policy": policy, "reads": reads})
    assert [path for path in requests if "frame_src_probe" in path] == [], f"the scene reached an origin of Jarvis: {requests}"
    assert requests == ["/"], "the only request the listener saw is the main page's own visualizer frame"
    assert policy.startswith("frame-src http://127.77.0.2:") and reads["sink"] not in policy and policy.count(" ") == 1
    supervisor = reads["supervisor"]
    assert supervisor["violations"] >= 1 or reads["state"]["phase"] == "killed",         "the scene did run its navigation attempts (each one reports a probe the protocol refuses): the zero is a measurement"


async def test_the_same_scene_does_reach_the_origin_if_the_stage_policy_names_it(tmp_path, monkeypatch):
    """Positive control: the zero above is the policy's doing. Name the "visualizer" in the stage document's `frame-src` (the union the
    contract forbids) and the very same navigation lands."""

    from jarvis.runtime import remotion_relay

    sink_origin: list[str] = []
    original = remotion_relay.stage_csp

    def permissive(origin):
        return f"{original(origin)} {sink_origin[0]}" if sink_origin else original(origin)

    class Spy(Sink):
        def __init__(self) -> None:
            super().__init__()
            sink_origin.append(self.origin)

    monkeypatch.setattr(remotion_relay, "stage_csp", permissive)
    monkeypatch.setitem(globals(), "Sink", Spy)
    requests, policy, _ = await navigation_requests(tmp_path)
    record_evidence("frame_src_navigation_ablation", {"sink_requests": requests, "stage_policy": policy})
    assert any("frame_src_probe" in path for path in requests), f"with the visualizer in frame-src the scene's navigation lands: {requests}"
    assert sink_origin[0] in policy

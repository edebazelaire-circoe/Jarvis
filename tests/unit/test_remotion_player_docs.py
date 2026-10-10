"""`docs/remotion-isolation.md` § 10 et `docs/presentation-engine.md` (Slice 10) contre le code : chaque réglage, route, état et appel cité existe et dit vrai."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

import jarvis.app as app
from jarvis.core.presentation_studio_edit import PresentationStudioEditService
from jarvis.protocol.remotion_player_routes import PREFIX, RemotionPlayerProtocolRoutes
from jarvis.runtime.remotion_relay import GUARDED_PREFIXES, STAGE_ROUTE
from jarvis.runtime.remotion_sandbox_server import DEFAULT_HOST, DEFAULT_PORT

ROOT = Path(__file__).resolve().parents[2]
ISOLATION = (ROOT / "docs" / "remotion-isolation.md").read_text(encoding="utf-8")
SECTION = ISOLATION[ISOLATION.index("## 10. Slice 10"):]
ENGINE = (ROOT / "docs" / "presentation-engine.md").read_text(encoding="utf-8")
STAGE_JS = (ROOT / "jarvis" / "runtime" / "control_center_remotion_stage.js").read_text(encoding="utf-8")


def node_json(script: str):
    if shutil.which("node") is None:
        pytest.skip("node absent")
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_documented_defaults_and_settings_are_the_code_ones():
    assert f"`{DEFAULT_HOST}`" in SECTION and f"`{DEFAULT_PORT}`" in SECTION
    for name in ("JARVIS_REMOTION_SANDBOX_HOST", "JARVIS_REMOTION_SANDBOX_PORT"):
        assert name in SECTION and name in (ROOT / "jarvis" / "app.py").read_text(encoding="utf-8")
    assert "JARVIS_UI_PORT" in SECTION and "_remotion_sandbox_settings" in SECTION and callable(app._remotion_sandbox_settings)


def test_the_documented_routes_exist_on_core_and_on_the_control_center():
    core = {route.path for route in RemotionPlayerProtocolRoutes(object()).routes()}
    for route in re.findall(r"`GET (/v1/remotion/[^`]*)`", SECTION):
        assert route.replace("{prefab_id}", "{prefab_id}") in core, route
    assert "/remotion-stage" in SECTION and STAGE_ROUTE == "/remotion-stage" and PREFIX == "/v1/remotion"
    assert "/api/remotion/report" in SECTION and set(GUARDED_PREFIXES) == {"/remotion-stage", "/api/remotion"}


def test_the_documented_visible_states_are_the_texts_the_page_draws():
    for text in ("La préparation est trop longue", "Remotion n’est pas disponible", "La scène ne compile pas",
                 "La source de la scène est refusée", "Scène retirée par le chien de garde", "Recharger la scène",
                 "Son coupé · cliquez la scène pour l’activer", "Son actif"):
        assert text.replace("’", "'") in SECTION.replace("’", "'") or text in SECTION, text
        assert text in STAGE_JS, text
    kill = node_json(f"process.stdout.write(JSON.stringify(require({json.dumps(str(ROOT / 'jarvis/runtime/control_center_remotion_stage.js'))}).KILL_TEXT))")
    for reason in ("unresponsive", "memory", "protocol_abuse", "no_ready"):
        assert reason in kill
    assert "La scène ne répond plus depuis 3 s" in kill["unresponsive"] and "trop de mémoire" in kill["memory"]
    assert "messages invalides" in kill["protocol_abuse"] and "10 s" in kill["no_ready"]


def test_the_documented_stage_protocol_is_the_one_the_window_host_speaks():
    frame = node_json(f"const f=require({json.dumps(str(ROOT / 'jarvis/runtime/control_center_remotion_frame.js'))});"
                      "process.stdout.write(JSON.stringify({phases:f.PHASES,path:f.STAGE_PATH}))")
    assert f"`status {{phase: {'|'.join(frame['phases'])}}}`" in SECTION and frame["path"] == STAGE_ROUTE
    stage = node_json(f"const s=require({json.dumps(str(ROOT / 'jarvis/runtime/control_center_remotion_stage.js'))});"
                      "process.stdout.write(JSON.stringify({parent:s.PARENT_TYPES,tick:s.TICK_MS,deadline:s.PREPARE_DEADLINE_MS}))")
    assert stage["tick"] == 250 and "toutes les 250 ms" in SECTION and f"échéance de {stage['deadline'] // 1000} s" in SECTION
    for kind in stage["parent"]:
        assert f"`{kind}" in SECTION, kind


def test_the_engine_gate_is_called_where_the_doc_says():
    gate_calls = {
        "play": ROOT / "jarvis/core/presentation_studio_playback.py", "edit": ROOT / "jarvis/core/presentation_studio_edit.py",
        "preview": ROOT / "jarvis/core/presentation_studio_preview.py"}
    for action, path in gate_calls.items():
        assert f'require_engine(presentation_id, "{action}")' in path.read_text(encoding="utf-8") or \
            f'require_engine(presentation_id, "{action}")' in path.read_text(encoding="utf-8").replace("self._studio.", ""), (action, path)
    assert "`PresentationStudioPlaybackService._start`" in ENGINE and "`PresentationStudioEditService.edit`" in ENGINE and "show_preview" in ENGINE
    assert hasattr(PresentationStudioEditService, "render_overlay") and "render_overlay" in ENGINE
    assert "_check_scenes" in ENGINE and "require_compatible" in ENGINE
    assert "compatibility" in (ROOT / "jarvis/core/presentation_studio_scene_catalog.py").read_text(encoding="utf-8")


def test_the_residual_risks_the_pm_asked_to_keep_listed_are_listed():
    assert "Access-Control-Allow-Origin: *" in SECTION and "Discipline des props" in SECTION
    assert "frame-src <origine du bac à sable>" in SECTION and "(`embedder_frame_src`) et **rien d'autre**" in SECTION

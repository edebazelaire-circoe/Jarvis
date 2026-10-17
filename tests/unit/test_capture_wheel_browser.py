"""Captures dans la roue d'outils, mesurées dans un vrai Chrome sur une vraie chaîne.

Handoff `jarvis-board-orbital-ui-workspace-rail`, Slice 04 ; architecture
résolue §5 (D6), D3, D4. Contrat : `docs/capture.md` › *Interface*.

**Aucun double dans la page.** Un vrai Core (SQLite, payloads sous
`tmp_path`, sources de capture **factices** de `tests/fakes/capture_stack.py`
— jamais l'écran ni le micro de ce poste) et un vrai `ControlCenter`
(`CaptureStack`) servent la page sur le bouclage ; `_capture_wheel_browser.mjs`
pilote de vrais événements d'entrée (clic, clic droit = vrai `contextmenu`,
Entrée, flèches, Maj+F10). Chaque état affiché est confronté à
`core.captures.status()`, la seule vérité.

Ce que ce fichier épingle (critères de la Slice 00) :

- Audio et Vidéo se démarrent et s'arrêtent depuis leur secteur, comme Core
  le dit ; jamais un état actif peint avant Core ;
- `REC` + durée (tirée de Core) reste visible roue repliée, puis après un
  rechargement et dans un second onglet ;
- Capture d'écran : une vraie prise, cible par défaut, résultat exposé ;
- le sous-arc ne propose que des cibles réelles ; une cible unique est une
  entrée informative et focalisable ;
- statut perdu (Core arrêté pour de vrai) : l'arrêt reste offert, aucun
  démarrage ; retour à la vérité ensuite ;
- audio et vidéo indépendants ;
- invariants migrés de `test_capture_rail_browser.py` : clavier, refus visible
  avec sa phrase et son code, mouvement réduit, contraste forcé, axe-core
  (`JARVIS_AXE_JS`), aucun recouvrement des commandes voisines.

Captures d'écran dans `JARVIS_S04_EVIDENCE_DIR` quand la variable est posée.
Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil

import pytest

from jarvis.adapters.fake_capture import FakeCaptureSource
from jarvis.domain.capture import CaptureChannel, CaptureErrorCode
from jarvis.ports.capture import CaptureTarget
from tests.fakes.capture_stack import CaptureStack
from tests.unit.test_interaction_mode_hud_browser import _chrome

HARNESS = Path(__file__).parent / "_capture_wheel_browser.mjs"
SCREEN, AUDIO = CaptureChannel.SCREEN, CaptureChannel.AUDIO

DOT = "#toolWheel [data-tw-slot={slot}] .tw-dot"
ANCHOR = "#toolWheel .tw-anchor"
OPENED = "window.JarvisToolWheel.isOpen()&&getComputedStyle(document.querySelector('#toolWheel .tw-panel')).opacity==='1'"
CLOSED = "!window.JarvisToolWheel.isOpen()"
SUB = ("document.querySelectorAll('#toolWheel .tw-item').length>0"
       "&&!document.querySelector('#toolWheel .tw-item').textContent.startsWith('Chargement')")
SETTLED = "window.JarvisCaptureRail.view().settled"


def _chip(channel: str, state: str = "active") -> str:
    return f"!!document.querySelector('#recIndicators .ri-chip[data-ri-channel={channel}][data-ri-state={state}]')"


def _no_chip(channel: str) -> str:
    return f"!document.querySelector('#recIndicators .ri-chip[data-ri-channel={channel}]')"


def _shot(tmp_path: Path, name: str) -> dict:
    folder = Path(os.environ.get("JARVIS_S04_EVIDENCE_DIR") or tmp_path)
    folder.mkdir(parents=True, exist_ok=True)
    return {"shot": str(folder / f"2026-10-16-s04-{name}.png")}


def _until(js: str, ms: int = 8000, name: str | None = None) -> dict:
    return {"until": js, "ms": ms, "name": name or js}


def _open_wheel() -> list[dict]:
    return [{"click": ANCHOR}, _until(OPENED, 3000, "opened")]


def _activate(slot: str) -> list[dict]:
    """Ouvrir la roue à la souris, cliquer le secteur : elle se replie."""

    return [*_open_wheel(), {"click": DOT.format(slot=slot)}, _until(CLOSED, 3000, "closed")]


async def _drive(url: str, actions: list, *, width: int = 1440, height: int = 900, reduced_motion: bool = False,
                 forced_colors: bool = False, tmp_path: Path | None = None) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    step = {"width": width, "height": height, "reducedMotion": reduced_motion, "forcedColors": forced_colors,
            "actions": actions}
    arg = json.dumps(step)
    if tmp_path is not None and len(arg) > 6000:
        plan = tmp_path / f"plan-{abs(hash(arg))}.json"
        plan.write_text(arg, encoding="utf-8")
        arg = "@" + str(plan)
    process = await asyncio.create_subprocess_exec(node, str(HARNESS), url, _chrome(), arg,
                                                   stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await asyncio.wait_for(process.communicate(), 300)
    assert process.returncode == 0, stderr.decode("utf-8", "replace")
    out = json.loads(stdout.decode("utf-8"))
    if os.environ.get("JARVIS_S04_DUMP"):
        Path(os.environ["JARVIS_S04_DUMP"]).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    assert out["reads"]["ready"] is True, out
    assert "failed" not in out["reads"], out["reads"].get("failed")
    assert out["errors"] == [], out["errors"]
    for key, value in out["reads"].items():
        if key.startswith("until:"):
            assert value is True, (key, out["reads"])
    return out


def _two_displays() -> list[CaptureTarget]:
    return [CaptureTarget(token="default", label="Écran principal", primary=True, width=1920, height=1080),
            CaptureTarget(token="display2", label="Écran 2", primary=False, width=1280, height=1024)]


@pytest.fixture
async def stack(tmp_path):
    async with CaptureStack(tmp_path) as opened:
        opened.url = f"http://127.0.0.1:{opened.cc_port}/"
        yield opened


def _open_rows(stack, channel: CaptureChannel) -> list:
    return [r for r in stack.core.captures.status().captures if r.channel is channel]


# ------------------------------------------------------------------ critères d'acceptation


async def test_audio_toggle_start_stop_matches_status(stack, tmp_path):
    gate = asyncio.Event()
    sources = stack.core.captures._sources
    real_audio = sources._continuous[AUDIO]
    sources._continuous[AUDIO] = lambda: FakeCaptureSource(start_gate=gate, payload_name="source.wav",
                                                           mime_type="audio/wav")
    loop = asyncio.get_running_loop()
    seen: dict = {}

    def release() -> None:
        seen["while_starting"] = [r.state.value for r in _open_rows(stack, AUDIO)]
        gate.set()

    loop.call_later(4.0, release)
    out = await _drive(stack.url, [
        _until(SETTLED, 5000, "settled"), {"read": "idle"}, _shot(tmp_path, "wheel-idle"),
        *_open_wheel(), _shot(tmp_path, "wheel-open"), {"click": DOT.format(slot="audio")}, _until(CLOSED, 3000),
        # Core tient le démarrage : la puce dit l'attente, le secteur n'est pas coché.
        _until(_chip("audio", "starting"), 3000, "starting"), {"read": "starting"},
        _until(_chip("audio"), 9000, "active"), {"wait": 1200}, {"read": "active"},
        _shot(tmp_path, "audio-rec-wheel-closed"),
        *_activate("audio"), _until(_no_chip("audio"), 9000, "stopped"), {"read": "stopped"},
    ], tmp_path=tmp_path)
    sources._continuous[AUDIO] = real_audio
    r = out["reads"]
    idle = r["idle"]
    assert idle["wheelHidden"] is False and idle["open"] is False, "la roue est là par défaut, repliée"
    assert idle["bareHands"] == {"hud": False, "palette": False}, "Sélection tient la colonne (Slice 03)"
    assert idle["oldRail"] is False and idle["indicators"]["hidden"] is True
    assert idle["wedges"]["audio"]["role"] == "menuitemcheckbox" and idle["wedges"]["audio"]["checked"] == "false"
    assert idle["bhToolsInWheel"] == 0
    starting = r["starting"]
    chip = next(c for c in starting["chips"] if c["channel"] == "audio")
    assert chip["state"] == "starting" and chip["waitShown"] and chip["time"].endswith(" s"), chip
    assert starting["wedges"]["audio"]["checked"] == "false", "jamais coché avant Core"
    assert starting["view"]["controls"]["audio"]["pressed"] is False
    assert seen["while_starting"] == ["starting"], "Core tenait bien la ligne en démarrage"
    active = r["active"]
    chip = next(c for c in active["chips"] if c["channel"] == "audio")
    assert active["open"] is False, "roue repliée"
    assert chip["state"] == "active" and chip["glyph"] == "audio" and chip["stopShown"]
    assert chip["label"] == "Arrêter l’enregistrement audio" and chip["detail"].startswith("en cours depuis ")
    assert active["wedges"]["audio"]["checked"] == "true" and active["wedges"]["audio"]["label"] == "Audio — en cours"
    core_id = active["view"]["controls"]["audio"]["captureId"]
    assert chip["key"] == core_id
    stopped = r["stopped"]
    assert stopped["wedges"]["audio"]["checked"] == "false" and stopped["indicators"]["hidden"] is True
    assert _open_rows(stack, AUDIO) == []
    recent = await stack.core.captures.recent(limit=5)
    assert any(rec.capture_id == core_id and rec.state.value == "complete" for rec in recent)
    lines = "\n".join(out["console"])
    for key in ("capture_rail.start_requested", "capture_rail.started", "capture_rail.stop_requested",
                "capture_rail.stopped", "capture_views.activate", "tool_wheel.activate"):
        assert key in lines, key


async def test_video_toggle_rec_timer_survives_wheel_close_and_reload(stack, tmp_path):
    out = await _drive(stack.url, [
        *_activate("video"), _until(_chip("screen"), 9000, "rec"), {"wait": 2300}, {"read": "closed"},
        _shot(tmp_path, "video-rec-wheel-closed"),
        {"reload": True}, _until(_chip("screen"), 6000, "after-reload"), {"read": "reloaded"},
        *_activate("video"), _until(_no_chip("screen"), 9000, "stopped"),
    ], tmp_path=tmp_path)
    r = out["reads"]
    closed, reloaded = r["closed"], r["reloaded"]
    chip = next(c for c in closed["chips"] if c["channel"] == "screen")
    assert closed["open"] is False
    assert chip["tag"] == "REC" and chip["dot"] and chip["stopShown"], chip
    assert chip["time"] in ("0:02", "0:03", "0:04"), chip["time"]
    assert closed["wedges"]["video"]["checked"] == "true"
    # Rechargé : la même capture, une durée qui part de Core, pas du clic ni du chargement.
    again = next(c for c in reloaded["chips"] if c["channel"] == "screen")
    assert again["key"] == chip["key"]
    assert again["time"] >= chip["time"] and again["time"] != "0:00", (chip["time"], again["time"])
    assert reloaded["indicators"]["z"] == "40"
    assert _open_rows(stack, SCREEN) == []


async def test_screenshot_one_shot_default_target(stack, tmp_path):
    out = await _drive(stack.url, [
        *_activate("screenshot"), _until(_chip("screenshot", "done"), 6000, "done"), {"read": "done"},
        _shot(tmp_path, "screenshot-done"),
        _until(_no_chip("screenshot"), 6000, "gone"),
    ], tmp_path=tmp_path)
    done = out["reads"]["done"]
    chip = next(c for c in done["chips"] if c["channel"] == "screenshot")
    assert chip["label"] == "Capture d’écran enregistrée" and chip["glyph"] == "done"
    assert done["live"] == "Capture d’écran enregistrée."
    shot = done["view"]["shot"]
    assert shot["device"] == "default" and shot["artifact"]["artifact_id"].startswith("jart_")
    artifact = await stack.core.artifacts.get(shot["artifact"]["artifact_id"])
    assert artifact.kind.value == "screenshot" and artifact.state.value == "complete"
    # Une prise ponctuelle n'occupe aucun canal.
    assert stack.core.captures.status().captures == ()
    assert '"device":"default"' in "\n".join(l for l in out["console"] if "screenshot_taken" in l)


async def test_secondary_lists_only_real_targets_single_entry_informative(stack, tmp_path):
    # Un seul écran (la cible par défaut) : une entrée, focalisable, qui le dit.
    first = await _drive(stack.url, [
        *_open_wheel(), {"right": DOT.format(slot="video")}, _until(SUB, 4000, "single"), {"read": "single"},
        _shot(tmp_path, "target-subarc-single"),
        {"focus": "#toolWheel .tw-item"}, {"read": "singleFocus"}, {"key": "Escape"}, {"key": "Escape"},
        # Audio : la liste réelle de Core (micro de Voice seul ici).
        *_open_wheel(), {"right": DOT.format(slot="audio")}, _until(SUB, 4000, "audio"), {"read": "audio"},
    ], tmp_path=tmp_path)
    single = first["reads"]["single"]
    assert [i["label"] for i in single["items"]] == ["Écran principal — seule cible disponible"]
    assert single["items"][0]["disabled"] is None and single["items"][0]["tabindex"] == "0"
    assert single["subLabel"] == "Vidéo"
    assert first["reads"]["singleFocus"]["focus"]["item"] == "Écran principal — seule cible disponible",         "l'entrée unique est focalisable"
    audio = first["reads"]["audio"]
    assert [i["label"] for i in audio["items"]] == ["Micro de Voice — seule cible disponible"]
    assert stack.core.captures.status().captures == (), "ouvrir une liste ne démarre rien"
    # Deux écrans : le clavier ouvre la liste (Maj+F10) et choisit l'écran 2.
    stack.core.captures._sources.target_lists[SCREEN] = _two_displays
    out = await _drive(stack.url, [
        {"focus": ANCHOR}, {"key": "Enter"}, _until(OPENED, 3000), {"key": "ArrowDown"},
        {"key": "F10", "shift": True}, _until("document.querySelectorAll('#toolWheel .tw-item').length===2", 5000, "two"),
        {"read": "two"}, {"key": "ArrowDown"}, {"key": "Enter"}, _until(_chip("screen"), 9000, "display2"),
        {"read": "recording"},
        # L'écran 2 enregistre : son arrêt en tête, sa cible n'est plus offerte.
        *_open_wheel(), {"right": DOT.format(slot="video")}, _until(SUB, 4000, "with-stop"), {"read": "withStop"},
        _shot(tmp_path, "target-subarc-two-displays"),
        {"key": "Escape"}, {"key": "Escape"},
    ], tmp_path=tmp_path)
    r = out["reads"]
    two = r["two"]
    assert [i["label"] for i in two["items"]] == ["Écran principal — 1920×1080", "Écran 2 — 1280×1024"], two["items"]
    assert two["focus"]["item"] is not None, "le clavier est dans le sous-arc"
    rows = _open_rows(stack, SCREEN)
    assert [row.device for row in rows] == ["display2"], "la cible choisie est celle que Core enregistre"
    chip = next(c for c in r["recording"]["chips"] if c["channel"] == "screen")
    assert chip["dev"] == "écran 2" and chip["label"] == "REC — arrêter l’enregistrement d’écran (écran 2)"
    labels = [(i["label"], i["disabled"]) for i in r["withStop"]["items"]]
    assert labels[0][0].startswith("Arrêter — écran 2") and labels[0][1] is None, labels
    assert ("Écran 2 — en cours d’enregistrement sur cette cible", "true") in labels, labels
    assert ("Écran principal — 1920×1080", None) in labels
    lines = "\n".join(first["console"] + out["console"])
    assert "capture_rail.targets_read" in lines and "capture_views.target_chosen" in lines
    assert '"device":"display2"' in lines
    for row in rows:
        await stack.core.captures.stop(row.capture_id)


async def test_status_loss_keeps_stop_and_refuses_start(stack, tmp_path):
    loop = asyncio.get_running_loop()
    steps: dict = {}

    def down() -> None:
        steps["down"] = asyncio.ensure_future(stack.server.stop())

    def up() -> None:
        steps["up"] = asyncio.ensure_future(stack.server.start())

    status = await stack.call("POST", "/api/captures/start", json={"channel": "audio"})
    assert status[0] == 201
    loop.call_later(5.0, down)
    out = await _drive(stack.url, [
        _until(_chip("audio"), 5000, "live"), {"read": "live"},
        _until("!window.JarvisCaptureRail.view().reachable", 12000, "lost"), {"wait": 300}, {"read": "lost"},
        _shot(tmp_path, "status-loss"),
        # Démarrer n'est pas possible : rien ne part, la lecture est relancée.
        *_activate("video"), {"wait": 600}, {"read": "refused"},
    ], tmp_path=tmp_path)
    r = out["reads"]
    lost = r["lost"]
    chip = next(c for c in lost["chips"] if c["channel"] == "audio")
    assert chip["state"] == "unknown" and chip["mark"] == "?" and chip["border"] == "dashed"
    assert chip["disabled"] == "false" and chip["stopShown"], "vie privée d'abord : l'arrêt reste offert"
    assert "tenter l’arrêt" in chip["label"]
    assert lost["wedges"]["video"]["badge"] == "unknown:?" and lost["wedges"]["video"]["checked"] == "false"
    assert lost["wedges"]["audio"]["checked"] == "false", "rien n'est dit actif sans Core"
    assert lost["anchor"]["tone"] is None, "un état inconnu n'alarme pas l'ancre"
    refused = r["refused"]
    assert not [row for row in stack.core.captures.status().captures if row.channel is SCREEN]
    assert any("capture_rail.status_lost" in line for line in out["console"])
    del refused
    # Core revient : la vérité aussi, et l'arrêt part pour de vrai.
    await steps["down"]
    loop.call_later(1.0, up)
    out = await _drive(stack.url, [
        _until(_chip("audio"), 12000, "back"), {"read": "back"},
        {"click": "#recIndicators .ri-chip[data-ri-channel=audio]"}, _until(_no_chip("audio"), 9000, "stopped"),
    ], tmp_path=tmp_path)
    assert _open_rows(stack, AUDIO) == []


async def test_status_loss_stop_reaches_core_when_it_returns(stack, tmp_path):
    """Statut perdu côté page seulement (le relais refuse, Core tient la capture) :
    l'arrêt demandé pendant la perte part, et Core l'exécute."""

    status = await stack.call("POST", "/api/captures/start", json={"channel": "audio"})
    assert status[0] == 201
    out = await _drive(stack.url, [
        _until(_chip("audio"), 5000, "live"),
        # Le statut seul tombe dans la page (lecture refusée) ; les écritures passent toujours.
        {"eval": "(()=>{const real=window.fetch.bind(window);window.fetch=(u,i)=>String(u).includes('/api/captures/status')"
                 "?Promise.reject(new TypeError('Failed to fetch')):real(u,i)})()"},
        _until("!window.JarvisCaptureRail.view().reachable", 12000, "lost"),
        {"click": "#recIndicators .ri-chip[data-ri-channel=audio]"}, {"wait": 1500}, {"read": "after"},
    ], tmp_path=tmp_path)
    assert _open_rows(stack, AUDIO) == [], "l'arrêt pendant la perte a atteint Core"
    after = out["reads"]["after"]
    assert not [c for c in after["chips"] if c["channel"] == "audio"], "oubliée une fois l'arrêt accepté"
    assert any("capture_rail.stopped" in line for line in out["console"])


async def test_two_tabs_same_truth(stack, tmp_path):
    out = await _drive(stack.url, [
        *_activate("video"), _until(_chip("screen"), 9000, "rec"), {"wait": 1500}, {"read": "first"},
        {"open": True}, _until(_chip("screen"), 6000, "second-sees"), {"read": "second"},
        # L'arrêt depuis le second onglet : le premier le voit aussi.
        {"click": "#recIndicators .ri-chip[data-ri-channel=screen]"}, _until(_no_chip("screen"), 9000, "second-stopped"),
        {"use": 0}, _until(_no_chip("screen"), 9000, "first-sees-stop"), {"read": "firstAfter"},
    ], tmp_path=tmp_path)
    r = out["reads"]
    a = next(c for c in r["first"]["chips"] if c["channel"] == "screen")
    b = next(c for c in r["second"]["chips"] if c["channel"] == "screen")
    assert a["key"] == b["key"]
    # Le second onglet, chargé après, montre au moins la durée du premier : elle vient de Core.
    assert b["time"] >= a["time"] and b["time"] != "0:00", (a["time"], b["time"])
    assert r["firstAfter"]["wedges"]["video"]["checked"] == "false"
    assert _open_rows(stack, SCREEN) == []


async def test_audio_and_video_independent(stack, tmp_path):
    out = await _drive(stack.url, [
        *_activate("audio"), _until(_chip("audio"), 9000, "audio"),
        *_activate("video"), _until(_chip("screen"), 9000, "video"), {"wait": 1100}, {"read": "both"},
        _shot(tmp_path, "audio-and-video"),
        *_activate("screenshot"), _until(_chip("screenshot", "done"), 6000, "shot"), {"read": "shot"},
        {"click": "#recIndicators .ri-chip[data-ri-channel=audio]"}, _until(_no_chip("audio"), 9000, "audio-off"),
        {"read": "audioOff"},
        *_activate("video"), _until(_no_chip("screen"), 9000, "video-off"),
    ], tmp_path=tmp_path)
    r = out["reads"]
    both = r["both"]
    assert {c["channel"] for c in both["chips"]} == {"screen", "audio"}
    assert both["wedges"]["audio"]["checked"] == both["wedges"]["video"]["checked"] == "true"
    assert both["view"]["caption"] == "REC 2"
    screen = next(c for c in r["shot"]["chips"] if c["channel"] == "screen")
    assert screen["state"] == "active", "la capture d'écran ne touche pas l'enregistrement"
    off = r["audioOff"]
    recordings = [c["channel"] for c in off["chips"] if c["channel"] != "screenshot"]
    assert recordings == ["screen"], "arrêter l'audio ne touche pas l'écran"
    assert off["wedges"]["video"]["checked"] == "true" and off["wedges"]["audio"]["checked"] == "false"
    assert stack.core.captures.status().captures == ()


# ------------------------------------------------------------------ invariants migrés du rail


async def test_a_refused_start_is_visible_with_its_reason_and_code(stack, tmp_path):
    sources = stack.core.captures._sources
    real = sources._continuous[SCREEN]
    sources._continuous[SCREEN] = lambda: FakeCaptureSource(refuse=CaptureErrorCode.SOURCE_UNAVAILABLE)
    out = await _drive(stack.url, [
        *_activate("video"), _until("!document.getElementById('recIndicatorsNote').hidden", 9000, "note"),
        {"wait": 400}, {"read": "refused"}, _shot(tmp_path, "refused-start"),
        {"focus": "#recIndicatorsNote .ri-note-close"}, {"key": "Escape"}, {"wait": 300}, {"read": "dismissed"},
    ], tmp_path=tmp_path)
    sources._continuous[SCREEN] = real
    r = out["reads"]
    refused = r["refused"]
    assert refused["note"]["tone"] == "bad"
    assert refused["note"]["text"] == "Enregistrement d’écran non démarré — écran indisponible (source_unavailable)."
    assert refused["wedges"]["video"]["badge"] == "error:!" and refused["wedges"]["video"]["checked"] == "false"
    assert refused["anchor"]["tone"] == "error" and "échec (source_unavailable)" in refused["anchor"]["label"]
    assert any("capture_rail.start_failed" in line and "source_unavailable" in line for line in out["console"])
    dismissed = r["dismissed"]
    assert dismissed["note"]["hidden"] is True and dismissed["anchor"]["tone"] is None
    assert dismissed["focus"]["anchor"] is True, "le focus revient à l'ancre, jamais sur body"


async def test_keyboard_reaches_every_capture_action_and_stops_from_the_indicator(stack, tmp_path):
    out = await _drive(stack.url, [
        {"focus": ANCHOR}, {"key": "Enter"}, _until(OPENED, 3000), {"read": "first"},
        {"key": "ArrowDown"}, {"key": "ArrowDown"}, {"key": "ArrowDown"}, {"read": "audio"},
        {"key": "Enter"}, _until(_chip("audio"), 9000, "audio"), {"read": "afterEnter"},
        {"key": "Tab"}, {"read": "tabbed"},
        {"focus": "#recIndicators .ri-chip[data-ri-channel=audio]"}, {"key": " "},
        _until(_no_chip("audio"), 9000, "stopped"), {"read": "stopped"},
    ], tmp_path=tmp_path)
    r = out["reads"]
    assert r["first"]["focus"]["slot"] == "selection"
    assert r["audio"]["focus"]["slot"] == "audio"
    assert r["afterEnter"]["focus"]["anchor"] is True, "activé : la roue se replie, le focus revient à l'ancre"
    assert r["stopped"]["focus"]["anchor"] is True, "la puce partie, le focus revient à l'ancre"
    assert _open_rows(stack, AUDIO) == []


@pytest.mark.parametrize("width,height", [(1440, 900), (1280, 720), (900, 600), (600, 800), (375, 667)])
async def test_indicators_cover_no_neighbouring_control(stack, tmp_path, width, height):
    loop = asyncio.get_running_loop()
    sources = stack.core.captures._sources
    sources.target_lists[SCREEN] = _two_displays
    await stack.call("POST", "/api/captures/start", json={"channel": "audio"})
    await stack.call("POST", "/api/captures/start", json={"channel": "screen"})
    await stack.call("POST", "/api/captures/start", json={"channel": "screen", "options": {"device": "display2"}})
    del loop
    out = await _drive(stack.url, [
        _until("document.querySelectorAll('#recIndicators .ri-chip').length===3", 6000, "three"),
        {"eval": "(()=>{const c=window.JarvisCaptureRail;return c.dismiss()})()"}, {"read": "seen"},
        _shot(tmp_path, f"indicators-{width}x{height}"),
    ], width=width, height=height, tmp_path=tmp_path)
    seen = out["reads"]["seen"]
    box = seen["indicators"]["box"]
    assert box and box["l"] >= 0 and box["t"] >= 0 and box["r"] <= width and box["b"] <= height, box
    for name, other in seen["boxes"].items():
        if other:
            overlap = min(box["r"], other["r"]) - max(box["l"], other["l"]), min(box["b"], other["b"]) - max(box["t"], other["t"])
            assert not (overlap[0] > 0.5 and overlap[1] > 0.5), (name, box, other)
    anchor = seen["anchor"]["box"]
    assert box["l"] > anchor["r"], "jamais sur l'ancre de la roue"
    assert seen["overflowX"] is False
    for row in stack.core.captures.status().captures:
        await stack.core.captures.stop(row.capture_id)


async def test_reduced_motion_and_forced_colours_keep_the_information(stack, tmp_path):
    await stack.call("POST", "/api/captures/start", json={"channel": "audio"})
    await stack.call("POST", "/api/captures/start", json={"channel": "screen"})
    actions = [_until("document.querySelectorAll('#recIndicators .ri-chip').length===2", 6000, "two"),
               {"wait": 1100}, {"read": "seen"}]
    normal = await _drive(stack.url, actions, tmp_path=tmp_path)
    reduced = await _drive(stack.url, actions, reduced_motion=True, tmp_path=tmp_path)
    forced = await _drive(stack.url, [*actions, _shot(tmp_path, "forced-colours")], forced_colors=True, tmp_path=tmp_path)
    n = {c["channel"]: c for c in normal["reads"]["seen"]["chips"]}
    m = {c["channel"]: c for c in reduced["reads"]["seen"]["chips"]}
    f = {c["channel"]: c for c in forced["reads"]["seen"]["chips"]}
    assert n["screen"]["dotAnimation"] == "riBreathe" and m["screen"]["dotAnimation"] == "none"
    # Le mouvement s'arrête, pas l'information : la durée continue.
    assert m["screen"]["time"] and m["audio"]["time"]
    assert f["screen"]["borderWidth"] == "2px" and f["screen"]["tag"] == "REC" and f["audio"]["stopShown"]
    assert forced["reads"]["seen"]["wedges"]["video"]["checked"] == "true"
    for row in stack.core.captures.status().captures:
        await stack.core.captures.stop(row.capture_id)


async def test_axe_finds_no_violation_in_the_wheel_and_indicators(stack, tmp_path):
    axe = os.environ.get("JARVIS_AXE_JS")
    if not axe or not Path(axe).is_file():
        pytest.skip("JARVIS_AXE_JS absent (axe-core n'est pas une dépendance du dépôt)")
    await stack.call("POST", "/api/captures/start", json={"channel": "audio"})
    await stack.call("POST", "/api/captures/start", json={"channel": "screen"})
    # Ce que chaque puce montre hors de sa durée est dans son nom (« REC », l'écran choisi ; QA S09 P6). Une cible
    # signalée se reconnaît à sa balise (`html`), pas à son sélecteur, qui change de forme avec deux puces.
    targets = r"""(()=>{const norm=t=>t.toLowerCase().replace(/[^\p{L}\p{N}]+/gu,' ').trim();
      const chips=[...document.querySelectorAll('#recIndicators .ri-chip')].map(c=>{const k=c.cloneNode(true);
        k.querySelectorAll('.ri-time,.ri-sr,[hidden]').forEach(n=>n.remove());
        const words=norm(k.textContent).split(' ').filter(Boolean),name=norm(c.getAttribute('aria-label')||'').split(' ');
        return {channel:c.dataset.riChannel,label:c.getAttribute('aria-label'),missing:words.filter(w=>!name.includes(w))}});
      return {chips}})()"""
    out = await _drive(stack.url, [
        _until("document.querySelectorAll('#recIndicators .ri-chip[data-ri-state=active]').length===2", 6000, "two"),
        {"value": "chips", "expr": targets},
        {"axe": "indicators", "file": axe, "selector": "#recIndicators"},
        *_open_wheel(), {"right": DOT.format(slot="video")}, _until(SUB, 4000),
        {"axe": "wheel", "file": axe, "selector": "#toolWheel"},
    ], tmp_path=tmp_path)
    reads = out["reads"]
    assert reads["until:two"] is True, reads
    chips = {c["channel"]: c for c in reads["chips"]["chips"]}
    assert set(chips) == {"audio", "screen"} and chips["screen"]["label"].startswith("REC — "), chips
    assert all(c["missing"] == [] for c in chips.values()), ("ce que la puce montre manque à son nom", chips)
    for name, violations in reads.items():
        if name.startswith("axe:"):
            # Exception écrite (Slice 09, docs/control-center-shell.md › Accessibility) : la puce montre une durée
            # qui avance, qu'un nom ne porte jamais ; axe (WCAG 2.5.3) la voit hors du nom. Tout le reste de ce
            # qu'elle montre est dans le nom (ci-dessus). Rien d'autre n'est admis.
            rest = [v for v in violations if not (v["id"] == "label-content-name-mismatch"
                                                  and v["html"] and all('class="ri-chip"' in h.split(">", 1)[0] for h in v["html"]))]
            assert rest == [], (name, rest)

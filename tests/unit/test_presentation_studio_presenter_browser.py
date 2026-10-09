"""The band of a Jarvis-presented run on the REAL Control Center page, in a REAL headless Chrome, against an isolated REAL Core
(jarvis-interactive-presentation-studio, Slice 14).

Nothing is simulated except the display: a real `JarvisCoreApplication` (its real brain, playback service and presenter, on the
real clock) behind the real `LocalProtocolServer`, the real `ControlCenter` page relaying to it, real CDP clicks. Proved, measured:

- a Jarvis run that the speech stack cannot take (a fresh Core has no current intention) is a visible pause on the band, with the
  reason in plain words and a working `Continuer` that retries (the count of lines goes from 1 to 2);
- a locked sequence is executed by Core on its real clock and the band shows its step, its exact length and a live counter;
  the user's `Sortir de la séquence` leaves it;
- the band never covers the interaction-mode HUD with its new rows.

Not provable here (Human check, `docs/OPERATIONS.md`): audible output, the real voice stack.
"""

from __future__ import annotations

import asyncio

import pytest

from jarvis.runtime.interaction_mode_view import CoreInteractionModeTransport, CoreInteractionModeView
from jarvis.runtime.presentation_studio_relay import PLAYBACK_ROUTE
from jarvis.runtime.scene_view import CoreSceneTransport, CoreSceneView
from tests.unit.test_presentation_studio_player_realpage_browser import GEOMETRY, READY, _no_noise, _until, drive
from tests.unit.test_presentation_studio_playback_routes import start_body
from tests.unit.test_presentation_studio_presenter_routes import jarvis_score, locked_score, presentation
from tests.unit.test_presentation_studio_routes import Core

BAND = "document.getElementById('jvStudioBand')"
VIEW = "window.JarvisStudioPlayer.view()"


async def boot(core: Core, tmp_path, make_score, **start):
    stack = core.stack
    port = int(stack.core_url.rsplit(":", 1)[1])
    token_file = tmp_path / "core.token"
    stack.center.scene_view = CoreSceneView(CoreSceneTransport(host="127.0.0.1", port=port, token_file=token_file))
    stack.center.interaction_mode_view = CoreInteractionModeView(
        CoreInteractionModeTransport(host="127.0.0.1", port=port, token_file=token_file))
    pid = await presentation(core, make_score)
    status, started, _ = await stack.call("POST", f"{PLAYBACK_ROUTE}/start", json=start_body(pid, **start))
    assert status == 200, started
    return f"http://127.0.0.1:{stack.cc_port}/"


async def test_a_jarvis_run_the_speech_stack_cannot_take_is_a_visible_pause_and_continue_retries(tmp_path):
    async with Core(tmp_path) as core:
        url = await boot(core, tmp_path, jarvis_score, role="jarvis_presenter")
        try:
            result = await drive(url, [
                {"wait": 600}, READY,
                _until(f"{VIEW}.phase==='paused' && ({VIEW}.problems||[]).includes('announce_refused')", 10000),
                {"value": "text", "expr": f"{BAND}.textContent"},
                {"value": "voice", "expr": f"{BAND}.querySelector('.jvsp-voice').textContent"},
                {"value": "voice_state", "expr": f"{BAND}.querySelector('.jvsp-voice').getAttribute('data-state')"},
                {"value": "kind", "expr": f"{BAND}.getAttribute('data-kind')"},
                {"value": "label", "expr": f"{BAND}.querySelector('.jvsp-pause').textContent"},
                {"value": "lines_before", "expr": f"({VIEW}.presenter||{{}}).lines"},
                {"click": "#jvStudioBand .jvsp-pause"},
                _until(f"({VIEW}.presenter||{{}}).lines===2 && {VIEW}.phase==='paused'", 10000),
                {"value": "lines_after", "expr": f"({VIEW}.presenter||{{}}).lines"},
                {"value": "again", "expr": f"({VIEW}.problems||[]).includes('announce_refused')"},
                GEOMETRY,
            ])
        finally:
            await core.stack.center.scene_view.aclose()
        reads = result["reads"]
        assert "failed" not in reads, reads
        assert "Jarvis présente" in reads["text"] and "n'a pas pu prendre la ligne" in reads["text"], reads["text"]
        assert reads["voice"] == "Jarvis se tait (pause)" and reads["voice_state"] == "paused" and reads["kind"] == "problem"
        assert reads["label"] == "Continuer"
        assert (reads["lines_before"], reads["lines_after"], reads["again"]) == (1, 2, True), "continue retried, and said it failed again"
        assert "Bonjour" not in reads["text"], "the band shows states and codes, never the script"
        geometry = reads["geometry"]
        assert geometry["overlap"] is False and geometry["hudReachable"] is True, geometry
        _no_noise(result)


async def test_a_locked_sequence_shows_its_progress_and_the_users_escape_leaves_it(tmp_path):
    async with Core(tmp_path) as core:
        url = await boot(core, tmp_path, lambda revision: locked_score(revision, duration_ms=30_000), role="user_presenter")
        status, moved, _ = await core.stack.call("POST", f"{PLAYBACK_ROUTE}/next", json={})
        assert status == 200 and moved["state"]["owner"] == "sequence"
        try:
            result = await drive(url, [
                {"wait": 600}, READY,
                _until(f"{BAND}.querySelector('.jvsp-seq') && !{BAND}.querySelector('.jvsp-seq').hidden", 10000),
                {"value": "first", "expr": f"{BAND}.querySelector('.jvsp-seqtext').textContent"},
                {"value": "role", "expr": f"{BAND}.querySelector('.jvsp-seqbar').getAttribute('role')"},
                {"wait": 2600},
                {"value": "later", "expr": f"{BAND}.querySelector('.jvsp-seqtext').textContent"},
                {"value": "now", "expr": f"+{BAND}.querySelector('.jvsp-seqbar').getAttribute('aria-valuenow')"},
                {"value": "skip_visible", "expr": f"!{BAND}.querySelector('.jvsp-skip').hidden"},
                {"click": "#jvStudioBand .jvsp-skip"},
                _until(f"{VIEW}.sequence===null && {VIEW}.owner==='user' && {VIEW}.position.index===3", 10000),
                {"value": "after", "expr": f"[{VIEW}.position.index,{VIEW}.owner,{BAND}.querySelector('.jvsp-seq').hidden]"},
            ])
        finally:
            await core.stack.center.scene_view.aclose()
        reads = result["reads"]
        assert "failed" not in reads, reads
        assert reads["first"].startswith("Séquence 1/2 · ") and "/ 30,0 s" in reads["first"] and reads["role"] == "progressbar"
        assert reads["later"] != reads["first"] and reads["now"] >= 0 and reads["skip_visible"] is True
        assert reads["after"] == [3, "user", True]
        state = await core.client.presentation_studio_playback_state()
        assert state["state"]["position"]["index"] == 3 and state["state"]["owner"] == "user"
        _no_noise(result)

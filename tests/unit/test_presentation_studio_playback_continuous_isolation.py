"""La vidéo continue n'utilise rien de la partition (handoff jarvis-remotion-native-studio-playback-fix, Slice 07, contrat § 5).

Vrai Core (`JarvisCoreApplication`) derrière le vrai `LocalProtocolServer`, vrai Control Center devant lui, vrai flux `/v1/events`. Une
présentation de deux vraies scènes Remotion avec une partition qui a une cue armable. Ce que la lecture continue de Variantes demande à Core
(la carte de l'horloge de composition, la variante, l'état de lecture), lu par le relais exactement comme la page le fait pendant « Lire » ou
« Lire seulement cette scène », ne démarre aucune course, n'arme aucune cue, ne fait parler personne, ne change pas le mode et ne pose rien
sur la scène. Le côté navigateur (le séquenceur et le transport de Variantes n'appellent que des lectures) :
`test_variants_transport_js.py::test_continuous_video_reads_the_map_and_never_touches_the_score_cues_or_speech`.
"""

from __future__ import annotations

import asyncio

from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.interaction_mode import InteractionMode
from jarvis.runtime.presentation_studio_relay import PLAYBACK_ROUTE, STUDIO_ROUTE
from tests.unit.test_presentation_studio_composition_clock_routes import FAST, SLOW, at, presentation, publish_scenes, remotion_scene
from tests.unit.test_presentation_studio_edit_routes import S1, S2
from tests.unit.test_presentation_studio_routes import AUTH, Core

I1, I2 = "psi_0000000000e1", "psi_0000000000e2"
CUE = "psc_0000000000e1"
#: Event types that would mean the score, a cue or the voice moved (none may appear).
SCORE_OR_VOICE = {T.SYSTEM_PRESENTATION_STUDIO_PLAYBACK_CHANGED, T.SYSTEM_PRESENTATION_STUDIO_PRESENTER_CHANGED,
                  T.BRAIN_SPEECH_REQUESTED, T.MOUTH_SPEECH_STARTED, T.MOUTH_SPEECH_COMPLETED}


async def with_score(core, pid: str, vid: str) -> None:
    _, variant = await core.call("GET", f"/{pid}/variants/{vid}")
    status, made = await core.call("POST", f"/{pid}/variants/{vid}/score", json={
        "expected_variant_revision": variant["revision"], "start_item_id": I1, "items": [
            {"item_id": I1, "scene_id": S1, "presenter": "jarvis", "kind": "speech", "text": "Bonjour", "target_duration_ms": 1000,
             "next_item_id": I2},
            {"item_id": I2, "scene_id": S2, "presenter": "user", "kind": "speech", "note": "Suite", "cue_id": CUE,
             "target_duration_ms": 1000}],
        "cues": [{"cue_id": CUE, "label": "Suite", "armable": True, "predicate": {"phrases": ["passons a la suite"]}}],
        "sequences": [], "recovery_points": []})
    assert status == 201, made


async def test_continuous_video_reads_arm_no_cue_speak_nothing_and_never_start_a_run(tmp_path):
    async with Core(tmp_path) as core:
        await publish_scenes(core)
        pid, vid = await presentation(core, [remotion_scene(S1, FAST), remotion_scene(S2, SLOW)])
        await with_score(core, pid, vid)
        app = core.stack.core
        events = []
        app.conversation_event_emitter.add_listener(events.append)
        mode_before = (app.interaction_mode.mode, app.interaction_mode.state.source)
        objects_before = len((await app.scene.snapshot()).objects)
        heard = []
        async with core.http.ws_connect(core.stack.core_url + "/v1/events", headers=AUTH) as ws:
            assert (await ws.receive_json())["message_type"] == "connected"
            # What Variants reads while it plays the video (« Lire », scene-only, scrub, ⏮ ⏭), through the page's relay, many times.
            for _ in range(5):
                status, clock, _ = await core.stack.call("GET", STUDIO_ROUTE + at(pid, vid))
                assert status == 200 and clock["clock"]["total_frames"] == 180
                status, _variant, _ = await core.stack.call("GET", STUDIO_ROUTE + f"/{pid}/variants/{vid}")
                assert status == 200
                status, run, _ = await core.stack.call("GET", PLAYBACK_ROUTE)
                assert status == 200 and run["state"]["phase"] == "idle"
            try:
                while True:
                    heard.append(await asyncio.wait_for(ws.receive_json(), 0.5))
            except asyncio.TimeoutError:
                pass   # intentional: half a second of silence on the bus is the measure
            silent = list(heard)
            # positive control: the same stream does carry a mode change when one happens (the measure can see what it rules out)
            await app.interaction_mode.request(InteractionMode.PRESENTATION, source="control_center")
            control = await asyncio.wait_for(ws.receive_json(), 5)
            assert control["message_type"] == "interaction.mode.changed"
            await app.interaction_mode.request(mode_before[0], source="control_center")
        heard = silent
        armed = await core.client.presentation_studio_playback_armed()
        assert armed["cues"] == [] and armed["run_id"] is None, "nothing is armed outside a presenter run"
        assert [m for m in heard if str(m.get("message_type", "")).startswith(("presentation_studio.", "interaction.mode"))] == [], \
            "no armed set, no mode switch while the video was read"
        assert [e.event_type for e in events if e.event_type in SCORE_OR_VOICE] == [], "no speech, no run, no presenter"
        assert app.interaction_mode.mode == mode_before[0]
        assert len((await app.scene.snapshot()).objects) == objects_before, "no stage window, no auxiliary window"
        assert app.presentation_studio_playback.state.phase.value == "idle"
        await app.conversation_event_emitter.stop()

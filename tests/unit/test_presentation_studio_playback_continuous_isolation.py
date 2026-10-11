"""La vidéo continue n'utilise rien de la partition (handoff jarvis-remotion-native-studio-playback-fix, Slice 07, contrat § 5).

Vrai Core (`JarvisCoreApplication`) derrière le vrai `LocalProtocolServer`, vrai Control Center devant lui, vrai flux `/v1/events`. Une
présentation de deux vraies scènes Remotion avec une partition qui a une cue armable. Ce que la lecture continue de Variantes demande à Core
(la carte de l'horloge de composition, la variante, l'état de lecture), lu par le relais exactement comme la page le fait pendant « Lire » ou
« Lire seulement cette scène », ne démarre aucune course, n'arme aucune cue, ne fait parler personne, ne change pas le mode et ne pose rien
sur la scène. Les routes rejouées ne sont pas écrites à la main (Slice 07 rework, P1) : c'est la liste COMPLÈTE de ce que la vraie page
Variantes (`control_center_presentation_studio_explorer.js` et son séquenceur, dans le faux DOM de `tests/fakes/explorer_js.py`) appelle
de son ouverture à la fin de chaque geste de la vidéo continue (`CONTINUOUS_GESTURES`), ses identifiants remplacés par ceux de la vraie
présentation. Une route que la page ajouterait serait rejouée ici d'elle-même ; une route qui écrit fait échouer le test.
Le côté navigateur seul : `test_variants_transport_js.py::test_continuous_video_reads_the_map_and_never_touches_the_score_cues_or_speech`.
"""

from __future__ import annotations

import asyncio

from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.interaction_mode import InteractionMode
from jarvis.runtime.presentation_studio_relay import PLAYBACK_ROUTE, STUDIO_ROUTE
from tests.fakes.explorer_js import run_ui
from tests.unit.test_presentation_studio_composition_clock_routes import FAST, SLOW, presentation, publish_scenes, remotion_scene
from tests.unit.test_presentation_studio_edit_routes import S1, S2
from tests.unit.test_presentation_studio_routes import AUTH, Core
from tests.unit.test_variants_transport_js import CONTINUOUS_GESTURES, VIDEO_WORLD

I1, I2 = "psi_0000000000e1", "psi_0000000000e2"
CUE = "psc_0000000000e1"
#: Event types that would mean the score, a cue or the voice moved (none may appear).
SCORE_OR_VOICE = {T.SYSTEM_PRESENTATION_STUDIO_PLAYBACK_CHANGED, T.SYSTEM_PRESENTATION_STUDIO_PRESENTER_CHANGED,
                  T.BRAIN_SPEECH_REQUESTED, T.MOUTH_SPEECH_STARTED, T.MOUTH_SPEECH_COMPLETED}


#: The ids of the explorer's fake world (`tests/fakes/explorer_js.py`, `seed`), replaced by the real presentation's.
WORLD_PID, WORLD_VID = "pst_00000000000000000000000000000001", "psv_00000000000000000000000000000001"
#: The shape of every call the page made (ids folded): a change of the page's reads shows here, and is replayed below either way.
PAGE_READS = {"GET /api/presentation-studio/playback", "GET /api/presentation-studio/presentations/{pid}",
              "GET /api/presentation-studio/presentations/{pid}/graph?archived=1",
              "GET /api/presentation-studio/presentations/{pid}/variants/{vid}",
              "GET /api/presentation-studio/presentations/{pid}/variants/{vid}/upgrades",
              "GET /api/presentation-studio/presentations/{pid}/variants/{vid}/art-direction",
              "GET /api/presentation-studio/presentations/{pid}/variants/{vid}/composition-clock"}


def page_calls(tmp_path) -> list[tuple[str, str]]:
    """What the real Variants page calls from its opening through every continuous-video gesture, in order."""

    work = tmp_path / "page"
    work.mkdir()
    out = run_ui(work, VIDEO_WORLD + CONTINUOUS_GESTURES + "return {calls:world.calls.map(c=>[c.method,c.url]),errors:env.errors};")
    assert out["errors"] == [], out
    return [(method, url) for method, url in out["calls"]]


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
            # Everything the real Variants page calls while it opens and plays the video, through the page's relay, many times.
            calls = page_calls(tmp_path)
            shapes = {f"{method} {url}".replace(WORLD_PID, "{pid}").replace(WORLD_VID, "{vid}") for method, url in calls}
            assert shapes == PAGE_READS, f"the page's calls changed: {sorted(shapes ^ PAGE_READS)}"
            assert {method for method, _ in calls} == {"GET"}, "continuous video only reads"
            assert any(url.startswith(STUDIO_ROUTE) for _, url in calls) and any(url == PLAYBACK_ROUTE for _, url in calls)
            for _ in range(5):
                for method, url in calls:
                    status, body, _ = await core.stack.call(method, url.replace(WORLD_PID, pid).replace(WORLD_VID, vid))
                    no_art = url.endswith("/art-direction") and status == 404 and "art_direction" in body["error"]["code"]
                    assert status == 200 or no_art, (url, status, body)   # a variant without art direction: the page's typed "none yet"
                    if url.endswith("/composition-clock"):
                        assert body["clock"]["total_frames"] == 180
                    if url == PLAYBACK_ROUTE:
                        assert body["state"]["phase"] == "idle"
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

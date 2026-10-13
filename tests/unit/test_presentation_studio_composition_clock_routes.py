"""La carte de l'horloge de composition servie par Core (handoff jarvis-remotion-native-studio-playback-fix, Slice 04).

Vrai Core (`JarvisCoreApplication`) derrière le vrai `LocalProtocolServer`, vrai Control Center devant lui ; les scènes sont de vraies
versions Remotion publiées dans la bibliothèque (`scene_candidate`, 30 i/s et 24 i/s). Prouvé : `GET .../composition-clock` rend la
carte (fps maître, débuts, longueurs) liée aux pins par sa clé ; un autre pin donne une autre clé ; rien n'est écrit ; une variante sans
vidéo (scène HTML, variante vide) le dit avec un code au lieu d'une carte ; le relais du Control Center sert la même réponse ; la vue de
lecture d'une course porte la même clé. Contrat : `docs/presentation-studio.md` > *Composition clock (Level 3)*.
"""

from __future__ import annotations

import pytest

from jarvis.core.presentation_studio_composition_clock import NOT_REMOTION, PresentationStudioCompositionClock, pins_of
from jarvis.domain.composition_clock import EMPTY, SCENE_INVALID, composition_key
from jarvis.domain.remotion_source import Composition
from jarvis.ports.prefabs import PrefabStoreError, PrefabStoreErrorCode
from jarvis.runtime.presentation_studio_relay import STUDIO_ROUTE, _READ_ROUTES
from tests.fakes.remotion_scene import SAMPLE, scene_candidate
from tests.unit.test_presentation_studio_edit_routes import S1, S2, scene
from tests.unit.test_presentation_studio_routes import Core, variant_body
from tests.unit.test_presentation_studio_upgrades_routes import tree

FAST = "presentation-studio.p000000000001.s000000000001"
SLOW = "presentation-studio.p000000000001.s000000000002"


def at(pid, vid):
    return f"/{pid}/variants/{vid}/composition-clock"


def remotion_scene(scene_id, prefab_id, version=1):
    return {"scene_id": scene_id, "prefab": {"id": prefab_id, "version": version}, "title": "Remotion", **SAMPLE}


async def publish_scenes(core) -> None:
    prefabs = core.stack.core.prefabs
    await prefabs.save(scene_candidate(FAST), actor="user")                                                   # 30 fps, 90 frames
    await prefabs.save(scene_candidate(SLOW, composition=Composition("Scene", 1280, 720, 24, 72)), actor="user")  # 24 fps, 3 s


async def presentation(core, scenes) -> tuple[str, str]:
    _, created = await core.call("POST", "", json={"title": "Horloge"})
    pid, variant = created["presentation"]["presentation_id"], created["variants"][0]
    status, saved = await core.call("PUT", f"/{pid}/variants/{variant['variant_id']}", json=variant_body(variant, scenes=scenes))
    assert status == 200, saved
    return pid, variant["variant_id"]


async def test_the_map_is_served_tied_to_its_pins_and_writes_nothing(tmp_path):
    async with Core(tmp_path) as core:
        await publish_scenes(core)
        pid, vid = await presentation(core, [remotion_scene(S1, FAST), remotion_scene(S2, SLOW)])
        before = tree(core, pid)
        status, view = await core.call("GET", at(pid, vid))
        assert status == 200, view
        assert view["problem"] is None and view["presentation_id"] == pid and view["variant_id"] == vid
        assert view["key"] == composition_key(pid, vid, [(S1, FAST, 1), (S2, SLOW, 1)])
        clock = view["clock"]
        assert clock["key"] == view["key"] and clock["version"] == 1
        assert (clock["fps"], clock["total_frames"]) == (30, 180)                      # 3 s at 30 + 3 s at 24 -> 90 + 90 master frames
        assert [(s["scene_id"], s["fps"], s["start"], s["length"], s["transition_in"]) for s in clock["scenes"]] == [
            (S1, 30, 0, 90, 0), (S2, 24, 90, 90, 0)]
        assert tree(core, pid) == before, "reading the map writes nothing"

        # the same variant with another pin order is another composition: another key, never the stale map
        _, variant = await core.call("GET", f"/{pid}/variants/{vid}")
        status, _ = await core.call("PUT", f"/{pid}/variants/{vid}", json=variant_body(
            variant, scenes=[remotion_scene(S2, SLOW), remotion_scene(S1, FAST)]))
        assert status == 200
        _, swapped = await core.call("GET", at(pid, vid))
        assert swapped["key"] != view["key"] and swapped["clock"]["scenes"][0]["scene_id"] == S2

        # the Control Center relays the same read
        status, via, _ = await core.stack.call("GET", STUDIO_ROUTE + at(pid, vid))
        assert status == 200 and via == swapped


async def test_a_variant_without_video_says_why_instead_of_a_map(tmp_path):
    async with Core(tmp_path) as core:
        await publish_scenes(core)
        pid, vid = await presentation(core, [remotion_scene(S1, FAST), scene(S2)])           # S2 pins the HTML jarvis.window
        status, view = await core.call("GET", at(pid, vid))
        assert status == 200 and view["clock"] is None
        assert view["problem"]["code"] == NOT_REMOTION and view["problem"]["scene_id"] == S2
        pid, vid = await presentation(core, [])
        _, empty = await core.call("GET", at(pid, vid))
        assert empty["clock"] is None and empty["problem"]["code"] == EMPTY
        status, payload = await core.call("GET", at(pid, "psv_" + "0" * 32))
        assert (status, payload["error"]["code"]) == (404, "presentation_studio_unknown_variant")
        status, payload = await core.call("GET", at(pid, vid) + "?x=1")
        assert (status, payload["error"]["code"]) == (400, "invalid_request")


class _Studio:
    def __init__(self, scenes) -> None:
        self.scenes = scenes

    async def get_variant(self, presentation_id, variant_id):
        return type("V", (), {"scenes": self.scenes, "revision": 7})()


class _Prefabs:
    def __init__(self, answers) -> None:
        self.answers = answers

    async def remotion_composition(self, prefab_id, version):
        answer = self.answers[prefab_id]
        if isinstance(answer, Exception):
            raise answer
        return answer


def _scene(scene_id, prefab_id):
    return type("S", (), {"scene_id": scene_id, "prefab": type("P", (), {"prefab_id": prefab_id, "version": 1})()})()


class _Sink:
    def __init__(self) -> None:
        self.rows = []

    def emit(self, kind, message, *, level, data):
        self.rows.append((kind, level, data))


async def test_an_unreadable_or_invalid_manifest_is_a_coded_problem_and_a_journal_row():
    scenes = [_scene("s1", "a"), _scene("s2", "b")]
    good = {"id": "Scene", "fps": 30, "duration_in_frames": 90}
    for answer in (PrefabStoreError(PrefabStoreErrorCode.TAMPERED, "changed"), {"id": "Scene", "fps": 0, "duration_in_frames": 9}):
        sink = _Sink()
        view = await PresentationStudioCompositionClock(_Studio(scenes), _Prefabs({"a": good, "b": answer}), diagnostics=sink).view("p", "v")
        assert view["clock"] is None and view["problem"]["code"] == SCENE_INVALID and view["problem"]["scene_id"] == "s2"
        assert [(k, lvl) for k, lvl, _ in sink.rows] == [("core.presentation_studio.composition_clock_refused", "warning")]
    sink = _Sink()
    view = await PresentationStudioCompositionClock(_Studio(scenes), _Prefabs({"a": good, "b": good}), diagnostics=sink).view("p", "v")
    assert view["clock"]["total_frames"] == 180 and view["variant_revision"] == 7
    assert sink.rows[0][0] == "core.presentation_studio.composition_clock_built" and sink.rows[0][2]["key"] == view["key"]
    assert pins_of(scenes) == [("s1", "a", 1), ("s2", "b", 1)]


async def test_a_disk_failure_of_the_catalogue_is_a_fault_not_a_problem():
    failing = _Prefabs({"a": PrefabStoreError(PrefabStoreErrorCode.STORAGE_IO, "disk")})
    with pytest.raises(PrefabStoreError) as caught:   # reaches the route boundary: 500 with its real cause, never a quiet problem
        await PresentationStudioCompositionClock(_Studio([_scene("s1", "a")]), failing).view("p", "v")
    assert caught.value.status == 500


def test_the_relay_serves_the_map_read_only():
    assert ("GET", "studio_composition_clock", "/{presentation_id}/variants/{variant_id}/composition-clock") in _READ_ROUTES


async def test_a_presenter_run_view_names_the_same_map_key_as_the_composition_clock_route(tmp_path):
    from tests.unit.test_presentation_studio_playback_service import Rig, applied

    rig = await Rig(tmp_path).open()
    try:
        rig.build()
        state = applied(await rig.service.start(rig.start_body()))
        variant = await rig.studio.get_variant(rig.pid, rig.vid)
        assert state["composition_key"] == composition_key(rig.pid, rig.vid, pins_of(variant.scenes))
        assert "composition_key" not in applied(await rig.run("stop"))       # no run, no map named
    finally:
        await rig.close()

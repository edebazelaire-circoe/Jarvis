"""La ligne de temps Remotion dans le service de lecture de Core (handoff jarvis-remotion-presentation-integration, Slice 12).

Banc réel de la Slice 12 d'origine (scène, catalogue, service d'édition, fichiers) ; seule la source de composition est un faux
(`PrefabService.remotion_composition` a ses propres tests). Prouvé : la vue de lecture porte `timeline` pour une scène Remotion
qui a des ancres et pour elle seule ; révéler une ancre ouvre son segment ; la pause gèle le temps joué, la reprise le
continue sans changer de segment ; un échec de résolution est dit et la lecture continue ; la lecture n'écrit rien ; lire la vue
n'a aucun effet de bord.
Contrat : `docs/presentation-studio.md` > *Remotion timeline bridge*.
"""

from __future__ import annotations

import json

import pytest

from jarvis.core.presentation_studio_playback import MAX_VIEW_BYTES
from tests.unit.test_presentation_studio_playback_service import Rig, applied, scenes_body, S1, S2

COMP = {"id": "Scene", "width": 1280, "height": 720, "fps": 30, "duration_in_frames": 300}


class Compositions:
    """Faux de `PrefabService.remotion_composition` : `None` = prefab HTML ; une exception = version illisible."""

    def __init__(self, answer) -> None:
        self.answer, self.calls = answer, []

    async def remotion_composition(self, prefab_id, version):
        self.calls.append((prefab_id, version))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def timed_scenes():
    """S2 : repères à 2 s et 6 s (images 60 et 180 à 30 i/s). S1 et S3 : ancres sans position (réparties à parts égales)."""

    out = scenes_body()
    out[1] = {**out[1], "anchors": [{"anchor_id": "reveal", "label": "Reveler", "control_id": "count", "at_ms": 2000},
                                    {"anchor_id": "marker", "label": "Repere", "at_ms": 6000}]}
    return out


def sub(root, name):
    path = root / name
    path.mkdir()
    return path


async def open_rig(tmp_path, answer, **extra):
    rig = await Rig(tmp_path).open(scenes=timed_scenes())
    source = Compositions(answer)
    rig.build(timeline_source=source, **extra)
    return rig, source


@pytest.fixture
async def remotion(tmp_path):
    rig, source = await open_rig(tmp_path, COMP)
    yield rig, source
    await rig.close()


async def test_a_scene_with_anchors_gets_its_entry_segment_and_a_scene_without_a_source_gets_nothing(tmp_path):
    rig, _ = await open_rig(tmp_path, COMP)
    try:
        state = applied(await rig.service.start(rig.start_body()))
        timeline = state["timeline"]
        # S1: anchors spread evenly (reveal at 0, marker at 150); nothing revealed yet = the entry segment, which is a hold at frame 0
        assert (timeline["scene_id"], timeline["composition_id"], timeline["fps"], timeline["duration_frames"]) == (S1, "Scene", 30, 300)
        assert (timeline["anchor_id"], timeline["from_frame"], timeline["until_frame"], timeline["playing"]) == (None, 0, 0, False)
        assert timeline["seq"] >= 1 and timeline["tolerance_ms"] == 500 and timeline["problems"] == []
    finally:
        await rig.close()
    plain = await Rig(sub(tmp_path, "plain")).open()
    try:
        plain.build()                                                             # no source wired: Slice 10 behaviour
        assert "timeline" not in applied(await plain.service.start(plain.start_body()))
    finally:
        await plain.close()
    html = await Rig(sub(tmp_path, "html")).open()
    try:
        html.build(timeline_source=Compositions(None))                            # a source that says "not a Remotion scene"
        assert "timeline" not in applied(await html.service.start(html.start_body()))
    finally:
        await html.close()


async def test_revealing_an_anchor_opens_its_segment_pause_freezes_the_played_time_and_resume_keeps_the_segment(remotion):
    rig, _ = remotion
    applied(await rig.service.start(rig.start_body()))
    state = applied(await rig.run("next"))                                        # S2: the score reveals "marker" (6 s = frame 180)
    first = state["timeline"]
    assert (first["scene_id"], first["anchor_id"], first["from_frame"], first["until_frame"], first["playing"]) == (S2, "marker", 180, 299, True)
    assert first["play_ms"] == 0
    rig.mono.t += 1.2
    playing = rig.service.where()["timeline"]
    assert playing["play_ms"] == 1200 and playing["seq"] == first["seq"]
    paused = applied(await rig.run("pause"))["timeline"]
    assert paused["playing"] is False and paused["seq"] == first["seq"] and paused["play_ms"] == 1200
    rig.mono.t += 30
    assert rig.service.where()["timeline"]["play_ms"] == 1200                      # thirty seconds of pause cost nothing
    resumed = applied(await rig.run("resume"))["timeline"]
    assert resumed["playing"] is True and resumed["seq"] == first["seq"] and resumed["play_ms"] == 1200
    rig.mono.t += 0.5
    assert rig.service.where()["timeline"]["play_ms"] == 1700


async def test_a_pause_between_two_reads_is_not_lost_because_every_transition_observes_the_clock(remotion):
    rig, _ = remotion
    applied(await rig.service.start(rig.start_body()))
    applied(await rig.run("next"))
    rig.mono.t += 2
    applied(await rig.run("pause"))          # nobody read the view while it played
    rig.mono.t += 60
    applied(await rig.run("resume"))
    assert rig.service.where()["timeline"]["play_ms"] == 2000


async def test_moving_to_another_segment_restarts_the_played_time_and_the_sequence_number_only_ever_grows(remotion):
    rig, _ = remotion
    applied(await rig.service.start(rig.start_body()))
    seqs = [rig.service.where()["timeline"]["seq"]]
    applied(await rig.run("next"))
    rig.mono.t += 3
    seqs.append(rig.service.where()["timeline"]["seq"])
    back = applied(await rig.run("previous"))["timeline"]
    seqs.append(back["seq"])
    assert back["scene_id"] == S1 and back["play_ms"] == 0
    again = applied(await rig.run("next"))["timeline"]
    assert again["play_ms"] == 0 and again["anchor_id"] == "marker"
    seqs.append(again["seq"])
    assert seqs == sorted(set(seqs)) and len(seqs) == 4


async def test_reading_the_view_has_no_side_effect_and_the_view_stays_small(remotion):
    rig, _ = remotion
    applied(await rig.service.start(rig.start_body()))
    applied(await rig.run("next"))
    rig.mono.t += 1
    views = [rig.service.where() for _ in range(5)]
    assert all(v["timeline"] == views[0]["timeline"] for v in views)
    assert len(json.dumps(views[0])) <= MAX_VIEW_BYTES


async def test_a_composition_that_cannot_be_read_is_said_and_the_run_goes_on_unguided(tmp_path):
    rig, _ = await open_rig(tmp_path, RuntimeError("version tampered"))
    try:
        state = applied(await rig.service.start(rig.start_body()))
        assert "timeline" not in state and state["phase"] == "playing"
        assert "timeline_unresolved" in state["notices"]
        assert applied(await rig.run("next"))["phase"] == "playing"
    finally:
        await rig.close()


async def test_a_bad_composition_in_the_manifest_is_a_notice_not_a_crash(tmp_path):
    rig, _ = await open_rig(tmp_path, {**COMP, "fps": 0})
    try:
        state = applied(await rig.service.start(rig.start_body()))
        assert "timeline" not in state and "timeline_unresolved" in state["notices"]
    finally:
        await rig.close()


async def test_findings_about_the_authors_anchors_are_notices(tmp_path):
    rig, _ = await open_rig(tmp_path, {**COMP, "duration_in_frames": 90})          # S2's 6 s anchor falls after the 3 s scene
    try:
        applied(await rig.service.start(rig.start_body()))
        state = applied(await rig.run("next"))
        assert "timeline_anchor_clamped" in state["notices"] and "timeline_anchors_partly_timed" not in state["notices"]
        assert state["timeline"]["from_frame"] == 89 and state["timeline"]["until_frame"] == 89     # clamped to the last frame
    finally:
        await rig.close()


async def test_the_composition_is_read_once_per_pin_and_the_run_writes_nothing(remotion):
    rig, source = remotion
    before = rig.tree_digest()
    applied(await rig.service.start(rig.start_body()))
    for verb in ("next", "previous", "next"):
        applied(await rig.run(verb))
    applied(await rig.run("pause"))
    applied(await rig.run("resume"))
    assert source.calls == [("lab.counter", 1)]
    applied(await rig.run("stop"))
    assert rig.tree_digest() == before                                            # playback never writes the variant (or anything else)


async def test_a_new_run_starts_its_played_time_at_zero_and_stop_leaves_no_timeline(remotion):
    rig, _ = remotion
    applied(await rig.service.start(rig.start_body()))
    applied(await rig.run("next"))
    rig.mono.t += 4
    assert rig.service.where()["timeline"]["play_ms"] == 4000
    stopped = applied(await rig.run("stop"))
    assert "timeline" not in stopped
    rig.build(timeline_source=Compositions(COMP))
    applied(await rig.service.start(rig.start_body()))
    assert applied(await rig.run("next"))["timeline"]["play_ms"] == 0


# ------------------------------------------------------------------ QA rework: reload, scene leaving the timeline

async def test_a_hot_reload_carries_the_anchors_over_and_recomputes_the_frames(remotion):
    from jarvis.domain.presentation_studio_reload import ReloadOrigin
    rig, source = remotion
    applied(await rig.service.start(rig.start_body()))
    before = applied(await rig.run("next"))["timeline"]
    assert (before["fps"], before["duration_frames"], before["from_frame"], before["until_frame"]) == (30, 300, 180, 299)
    # The reload moved the pin to a version with another cadence and length; the stage window was patched by the reload itself.
    source.answer = {**COMP, "fps": 60, "duration_in_frames": 1200}
    variant = await rig.studio.get_variant(rig.pid, rig.vid)
    saved = await rig.studio.save_variant(rig.pid, rig.vid, {
        "expected_revision": variant.revision, "title": variant.title, "scenes": timed_scenes(),
        "art_direction_id": variant.art_direction_id, "score_id": variant.score_id})
    await rig.service._on_edit_committed(rig.pid, rig.vid, saved.revision, ReloadOrigin(S2, "confirm"))
    after = rig.service.where()["timeline"]
    assert (after["fps"], after["duration_frames"]) == (60, 1200)
    assert after["anchor_id"] == "marker" and (after["from_frame"], after["until_frame"]) == (360, 1199)   # 6 s at 60 fps: same at_ms, new frame
    assert after["seq"] > before["seq"] and after["playing"] is True and rig.service.where()["phase"] == "playing"


async def test_played_time_does_not_survive_leaving_the_timeline_and_coming_back(tmp_path):
    scenes = timed_scenes()
    scenes[0] = {**scenes[0], "anchors": []}           # S1 has no anchor: it is not on the timeline
    rig = await Rig(tmp_path).open(scenes=scenes)
    rig.build(timeline_source=Compositions(COMP))
    try:
        applied(await rig.service.start(rig.start_body()))
        assert "timeline" not in rig.service.where()
        applied(await rig.run("next"))
        rig.mono.t += 2
        assert rig.service.where()["timeline"]["play_ms"] == 2000
        applied(await rig.run("previous"))
        assert "timeline" not in rig.service.where()
        rig.mono.t += 5
        again = applied(await rig.run("next"))["timeline"]
        assert again["anchor_id"] == "marker" and again["play_ms"] == 0
    finally:
        await rig.close()

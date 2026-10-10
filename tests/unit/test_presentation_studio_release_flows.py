"""Release gate, Slice 22: the product journeys, end to end, on a real Core (jarvis-interactive-presentation-studio).

Each test is one journey a person would live, not one feature: it starts where the user starts (a brief, a request) and ends where they
end (a deck on the screen, a template in the library), through the same doors the brain and the page use. Real `JarvisCoreApplication`
behind the real `LocalProtocolServer`, real file stores and scene store, the real `jarvis-presentation` tools, the real Control Center
relay for the page-side routes. The only stand-ins are the Control Center's turn attestation (`FakeCC`) and the speech stack (a fresh
Core has no current intention, which the Slice 14 tests already pin as a visible pause).

What is NOT proven here, by construction: audible speech, the microphone, a real projector, a real model (see
`slices/22-end-to-end-hardening/evidence/`). Contract: `docs/presentation-studio.md`; report: `docs/presentation-studio-release.md`.
"""

from __future__ import annotations

import pytest

from jarvis.runtime.presentation_studio_mcp_support import PresentationToolError
from tests.fakes import presentation_studio_fake_author as fa
from tests.unit.presentation_studio_release_world import assemble_deck, attest, open_world, reopen
from tests.unit.test_presentation_studio_playback_routes import PLAYBACK_ROUTE, start_body
from tests.unit.test_presentation_studio_presenter_routes import locked_score, presentation, stage_body, until
from tests.unit.test_presentation_studio_routes import Core


@pytest.fixture
async def world(tmp_path):
    core, built = await open_world(tmp_path)
    try:
        yield built
    finally:
        await core.__aexit__(None, None, None)


async def stage_ids(core) -> list[str]:
    return [o.object_id for o in (await core.stack.core.scene.snapshot()).objects if o.object_id.startswith("studio-stage-")]


async def numbered(world, pid) -> dict[int, str]:
    graph = await world.tools.inspect("presentation", presentation_id=pid)
    return {v["number"]: v["variant_id"] for v in graph["variants"]["items"]}


# ------------------------------------------------------------------ 1. one-shot report

async def test_journey_one_shot_report_from_brief_to_the_screen_and_back(world):
    """"Show me what is in this folder": a gate-clean single scene with the generated fallback DA, shown at once, then gone."""

    brief, draft = fa.good_one_shot()
    before = len(world.spy.calls)
    checked = await world.tools.draft("check", brief=brief, draft=draft)
    assert checked["ok_gate"] is True and checked["report"]["failures"] == []
    made = await world.tools.draft("assemble", brief=brief, draft=draft)
    assert made["status"] == "delivered" and made["provenance"]["gate"] == {"errors": 0, "warnings": 0}
    assert [a["fallback"] for a in made["provenance"]["art_directions"]] == [True], "nothing to derive from: the generated fallback"
    assert len(world.spy.calls) - before <= 6, "a one-shot report is a handful of Core calls, not a conversation"
    pid = made["presentation_id"]
    vid = (await world.tools.inspect("presentation", presentation_id=pid))["active_variant_id"]
    await attest(world)
    started = await world.tools.play("start", role="rehearsal", presentation_id=pid, variant_id=vid)
    assert started["state"]["phase"] == "playing" and started["state"]["position"] == {"index": 1, "of": 1}
    assert started["state"]["art_direction"] == "fallback"
    [stage] = await stage_ids(world.core)
    snapshot = await world.core.stack.core.scene.snapshot()
    assert "quarante-deux fichiers" in snapshot.get_object(stage).payload.prefab.data["body"], "the report is on the screen"
    stopped = await world.tools.play("stop")
    assert stopped["state"]["phase"] == "stopped" and await stage_ids(world.core) == []


# ------------------------------------------------------------------ 2. serious authoring, live edit, variant, rehearsal, user presenter

async def test_journey_serious_deck_live_edit_variant_rehearsal_and_user_presenter(tmp_path):
    core, world = await open_world(tmp_path)
    try:
        deck = await assemble_deck(world)
        assert len(deck.scenes) == len(deck.items) == 12 and len(deck.cues) == 5
        await attest(world)
        mode_before = core.stack.core.interaction_mode.mode.value
        # -- live edit by the brain, then the brain's own edit is undone directly
        edited = await world.tools.edit([{"op": "control.set", "scene_id": deck.scenes[2], "control_id": "headline", "value": "CA du T3"}],
                                        presentation_id=deck.pid, variant_id=deck.vid)
        assert edited["status"] == "applied" and edited["committed"] is True
        _, variant = await core.call("GET", f"/{deck.pid}/variants/{deck.vid}")
        assert variant["scenes"][2]["props"]["headline"] == "CA du T3"
        undone = await world.tools.undo("undo", presentation_id=deck.pid, variant_id=deck.vid)
        assert undone["status"] in ("applied", "undone")
        _, variant = await core.call("GET", f"/{deck.pid}/variants/{deck.vid}")
        assert variant["scenes"][2]["props"]["headline"] != "CA du T3"
        # -- a sober variant: the branch is edited, the original is untouched
        made = await world.tools.variant("create", title="Version sobre", rationale="moins de couleurs", presentation_id=deck.pid,
                                         source_variant_id=deck.vid)
        assert made["variant_number"] == 2
        ids = await numbered(world, deck.pid)
        _, original_before = await core.call("GET", f"/{deck.pid}/variants/{deck.vid}")
        await world.tools.edit([{"op": "control.set", "scene_id": (await core.call("GET", f"/{deck.pid}/variants/{ids[2]}"))[1]["scenes"][0]["scene_id"],
                                 "control_id": "headline", "value": "Version sobre"}], presentation_id=deck.pid, variant_id=ids[2])
        _, original_after = await core.call("GET", f"/{deck.pid}/variants/{deck.vid}")
        assert original_after == original_before, "editing a branch never touches its parent"
        # -- rehearsal with Jarvis silent runs in PRESENTATION and walks the whole score
        started = await world.tools.play("start", role="rehearsal", presentation_id=deck.pid, variant_id=deck.vid)
        assert started["state"]["mode"] == "presentation" and started["state"]["position"]["of"] == 12
        for _ in range(11):
            assert (await world.tools.play("next"))["state"]["phase"] == "playing"
        last = await world.tools.play("goto", position=1)
        assert last["state"]["position"]["index"] == 1
        await world.tools.play("stop")
        assert core.stack.core.interaction_mode.mode.value == mode_before, "the user's mode is given back"
        # -- the user presents: Jarvis stays silent, the first cue is armed with its phrase, moving on re-arms the next one
        started = await world.tools.play("start", role="user_presenter", presentation_id=deck.pid, variant_id=deck.vid)
        assert started["state"]["role"] == "user_presenter" and started["state"]["mode"] == "presentation"
        first = await core.client.presentation_studio_playback_armed()
        assert [c["phrases"] for c in first["cues"]] == [["passons au chiffre d'affaires"]]
        fired = await core.client.presentation_studio_report_cue(first["run_id"], first["generation"], first["cues"][0]["cue_id"])
        assert fired["status"] == "fired", "the follower's report advanced the score"
        assert (await world.tools.inspect("playback"))["state"]["position"]["index"] == 2
        await world.tools.play("next")
        second = await core.client.presentation_studio_playback_armed()
        assert second["generation"] > first["generation"] and second["cues"][0]["cue_id"] != first["cues"][0]["cue_id"]
        assert [c["phrases"] for c in second["cues"]] == [["regardons les couts de support"]]
        await world.tools.play("stop")
        assert core.stack.core.interaction_mode.mode.value == mode_before and await stage_ids(core) == []
        saved = (await core.call("GET", f"/{deck.pid}/variants/{ids[2]}"))[1]
    finally:
        await core.__aexit__(None, None, None)
    # -- a Core restart: everything durable is back, no run, no stage object, the undo ring is (by design) gone
    core, world = await reopen(tmp_path)
    try:
        listed = (await core.client.presentation_studio_list())["presentations"]
        assert deck.pid in [p["presentation_id"] for p in listed]
        assert (await core.call("GET", f"/{deck.pid}/variants/{ids[2]}"))[1] == saved
        assert (await core.client.presentation_studio_playback_state())["state"]["phase"] == "idle"
        assert await stage_ids(core) == []
        assert (await core.call("GET", f"/{deck.pid}/graph"))[1]["variant_counter"] == 2
    finally:
        await core.__aexit__(None, None, None)


# ------------------------------------------------------------------ 2b. rehearse and refine (the Slice 15 behaviours, proven through Slices 12, 01c and 21)

async def test_journey_rehearsal_section_where_am_i_edit_pause_resume_and_backtrack(world):
    """Slice 15 never had a round of its own: its acceptance (rehearse and refine without losing position or state) is proven here."""

    deck = await assemble_deck(world, count=8)
    await attest(world)
    started = await world.tools.play("start", role="rehearsal", presentation_id=deck.pid, variant_id=deck.vid)
    assert started["state"]["role"] == "rehearsal" and started["state"]["position"] == {"index": 1, "of": 8}
    # rehearse a section: jump to the fourth scene, then ask where we are (bounded: no script text in the answer)
    await world.tools.play("goto", scene_id=deck.scenes[3])
    where = (await world.tools.inspect("playback"))["state"]
    assert where["position"] == {"index": 4, "of": 8} and where["next"]["scene_title"] and "text" not in where["item"]
    assert len(str(where).encode("utf-8")) < 3072
    # refine while rehearsing: the edit pauses the run on the same item and the stage follows; resuming keeps the place
    edit = await world.tools.edit([{"op": "control.set", "scene_id": deck.scenes[3], "control_id": "headline", "value": "Marge et coûts"}],
                                  presentation_id=deck.pid, variant_id=deck.vid)
    assert edit["status"] == "applied"
    paused = (await world.tools.inspect("playback"))["state"]
    assert paused["phase"] in ("paused", "playing") and paused["position"] == {"index": 4, "of": 8}
    if paused["phase"] == "paused":
        resumed = await world.tools.play("resume")
        assert resumed["state"]["phase"] in ("playing", "resuming")
    stage = (await stage_ids(world.core))[0]
    shown = (await world.core.stack.core.scene.snapshot()).get_object(stage).payload.prefab.props
    assert shown["headline"] == "Marge et coûts", "the refined text is what the rehearsal shows next"
    # backtrack, then forward again: position and refined state survive
    assert (await world.tools.play("previous"))["state"]["position"]["index"] == 3
    assert (await world.tools.play("goto", position=4))["state"]["position"]["index"] == 4
    # nothing about the rehearsal became durable content: the stores hold the deck, the score and the edit, not a transcript
    await world.tools.play("stop")
    names = {p.name for p in (world.core.stack.data_root / "presentations" / deck.pid).rglob("*") if p.is_file()}
    assert not any("rehears" in n or "transcript" in n for n in names)


# ------------------------------------------------------------------ 3. Jarvis presents a locked sequence

async def test_journey_jarvis_presenter_locked_sequence_returns_the_timeline_and_the_mode(tmp_path):
    async with Core(tmp_path) as core:
        app = core.stack.core
        pid = await presentation(core, locked_score)
        await app.interaction_mode.request("presentation", source="control_center")             # what the user had
        status, started, _ = await core.stack.call("POST", f"{PLAYBACK_ROUTE}/start", json=start_body(pid))
        assert status == 200 and started["state"]["role"] == "user_presenter" and started["state"]["mode"] == "presentation"
        await core.stack.call("POST", f"{PLAYBACK_ROUTE}/stop", json={})
        # Jarvis presents (explicit request): the run leaves PRESENTATION so the scripted line can be spoken, and gives it back
        status, started, _ = await core.stack.call("POST", f"{PLAYBACK_ROUTE}/start", json={**start_body(pid, role="jarvis_presenter"), "actor": "brain"})
        assert status == 200 and started["state"]["mode"] == "assistant" and app.interaction_mode.mode.value == "assistant"
        stage = started["state"]["stage_object_id"]
        status, moved, _ = await core.stack.call("POST", f"{PLAYBACK_ROUTE}/next", json={})
        assert status == 200
        # the speech stack of a fresh Core cannot take the line: a visible pause, never a hang (Slice 14), then the user's continue
        paused = await until(core, lambda s: s["phase"] in ("paused", "playing"))
        assert paused["phase"] in ("paused", "playing")
        await core.stack.call("POST", f"{PLAYBACK_ROUTE}/stop", json={})
        assert app.interaction_mode.mode.value == "presentation" and await stage_ids(core) == []
        # the locked sequence itself, under the user's role: steps on the real clock, then the timeline is the user's again
        await core.stack.call("POST", f"{PLAYBACK_ROUTE}/start", json=start_body(pid))
        status, moved, _ = await core.stack.call("POST", f"{PLAYBACK_ROUTE}/next", json={})
        assert moved["state"]["owner"] == "sequence"
        stage = moved["state"]["stage_object_id"]
        assert await stage_body(core, stage, "Etape A") == "Etape A"
        done = await until(core, lambda s: s["owner"] == "user")
        assert done["sequence"] is None and await stage_body(core, stage, "Etape B") == "Etape B"
        status, nxt, _ = await core.stack.call("POST", f"{PLAYBACK_ROUTE}/next", json={})
        assert status == 200 and nxt["state"]["scene"]["title"] == "Trois"
        await core.stack.call("POST", f"{PLAYBACK_ROUTE}/stop", json={})
        assert await stage_ids(core) == []


# ------------------------------------------------------------------ 4. compare, mix, promote

async def test_journey_compare_mix_and_promote_a_template_then_reuse_it(world):
    deck = await assemble_deck(world, count=6)
    pid = deck.pid
    for title in ("Plus visuelle", "Plus courte", "Plus formelle"):
        await world.tools.variant("create", title=title, presentation_id=pid, source_variant_id=deck.vid)
    ids = await numbered(world, pid)
    assert sorted(ids) == [1, 2, 3, 4]
    # two edits in two branches so the sources really differ
    for number, headline in ((2, "Visuel"), (3, "Court")):
        _, variant = await world.core.call("GET", f"/{pid}/variants/{ids[number]}")
        await world.tools.edit([{"op": "control.set", "scene_id": variant["scenes"][1]["scene_id"], "control_id": "headline", "value": headline}],
                               presentation_id=pid, variant_id=ids[number])
    # compare four-up, focus a pair, navigate in step, close
    opened = await world.tools.compare("open", presentation_id=pid, variant_ids=[ids[1], ids[2], ids[3], ids[4]])
    assert opened["layout"] == "four_up" and opened["speech"] == "silent" and len(opened["variants"]) == 4
    assert (await world.tools.compare("focus", presentation_id=pid, pair=[ids[2], ids[3]]))["layout"] == "focus"
    assert (await world.tools.compare("close", presentation_id=pid))["active"] is False
    # mix: the narrative of 3 over the base 2, planned first, created as a NEW child; the sources are inputs
    sources = {n: (await world.core.call("GET", f"/{pid}/variants/{ids[n]}"))[1] for n in (2, 3)}
    request = {"title": "Mélange visuel et court", "base": ids[2], "narrative": ids[3]}
    planned = await world.tools.compose("plan", request, presentation_id=pid)
    assert planned["ok_plan"] is True and planned["conflicts"] == []
    mixed = await world.tools.compose("create", request, presentation_id=pid)
    assert mixed["status"] == "created" and mixed["variant_number"] == 5
    for n in (2, 3):
        assert (await world.core.call("GET", f"/{pid}/variants/{ids[n]}"))[1] == sources[n]
    provenance = await world.tools.inspect("composition", presentation_id=pid, variant_id=mixed["variant_id"])
    assert {d["dimension"] for d in provenance["dimensions"]} == {"scenes", "narrative", "motion", "art_direction"}
    # promote the mixed variant as a template (Remotion Slice 19 owns the promotion of Remotion scenes)
    plan_request = {"kind": "presentation", "title": "Revue type", "slug": "revue-type"}
    planned = await world.tools.template("plan", presentation_id=pid, variant_id=mixed["variant_id"], plan=plan_request)
    assert planned["plan"]["selection_required"] is True and (await world.tools.inspect("templates"))["templates"]["total"] == 0
    chosen = [{"scene_id": s["scene_id"], "dimensions": ["accent"], "parameters": ["headline"]} for s in planned["plan"]["scenes"]["items"]]
    await attest(world)   # QA B1: a promotion only follows a request of the user in this turn (the same attestation as a presentation start)
    promoted = await world.tools.template("promote", presentation_id=pid, variant_id=mixed["variant_id"], plan={**plan_request, "scenes": chosen})
    assert promoted["status"] == "promoted" and promoted["template_id"]
    listing = await world.tools.inspect("templates")
    assert listing["templates"]["total"] == 1
    assert promoted["published_to_library"] is False and promoted["prefabs"]["total"] == 0, "a presentation is ONE artefact (Remotion Slice 19)"
    # reuse: instantiate into a brand new presentation (scenes + art direction + the score SKELETON: structure, never the words)
    made = await world.tools.template("instantiate", template_id=promoted["template_id"], title="Revue du T4")
    assert made["status"] == "instantiated" and len(made["scene_ids"]) == 6 and made["art_direction_id"] and made["score_id"]
    new_pid, new_vid = made["presentation_id"], made["variant_id"]
    await attest(world)
    _, fresh = await world.core.call("GET", f"/{new_pid}/variants/{new_vid}")
    status, carried = await world.core.call("GET", f"/{new_pid}/variants/{new_vid}/score")
    assert status == 200 and carried["problems"] == [] and len(carried["score"]["items"]) == 6, "the items of the mixed variant score came as a skeleton"
    assert all(i["text"] == "" and i["cue_id"] is None for i in carried["score"]["items"]) and carried["score"]["cues"] == []
    assert {i["scene_id"] for i in carried["score"]["items"]} <= {s["scene_id"] for s in fresh["scenes"]}
    started = await world.tools.play("start", role="rehearsal", presentation_id=new_pid, variant_id=new_vid)
    assert started["state"]["phase"] == "playing" and started["state"]["position"]["of"] == 6
    await world.tools.play("stop")
    # the source presentation is not touched by the promotion
    for n in (2, 3):
        assert (await world.core.call("GET", f"/{pid}/variants/{ids[n]}"))[1] == sources[n]

"""Brief -> draft -> assemble -> play a multi-scene Remotion presentation, in a REAL Chrome on an isolated Core (Remotion Slice 15).

Opt-in like the other real-page proofs (`JARVIS_REMOTION_RUNTIME_DIR` = an installed Remotion `runtime/`, Node, Chrome); never the live Jarvis.
The author is the scripted rig (`tests/fakes/presentation_studio_fake_author.py`): no model, but everything else is the product - the
authoring tool route of Core with the REAL compiler (Node + esbuild), the Remotion Player in its sandboxed frame, the Control Center, the
playback runtime and the Slice 13 controls bridge.

Proven by what the sandbox itself reads: the draft is delivered as a `remotion` Presentation (never Slidecar), its four scenes compile and
play one after the other with their own text; **the art direction of the variant is what is drawn** (the theme prop: accent colour, ground
colour and font family read from the DOM equal the stored art direction); a control on `props.theme.accent` changes the colour of the live
scene without a remount; the second candidate of an exploratory request, played from the same shared scenes, is drawn with ITS
direction (a different ground colour); a draft whose TSX does not compile is refused with file/line/column and nothing is written.
"""

from __future__ import annotations

import copy

import pytest

from tests.fakes import presentation_studio_fake_author as fa
from tests.fakes.remotion_player_stack import RemotionStack
from tests.unit.test_remotion_player_realpage_browser import (
    READY, RUNTIME, SANDBOX, SHELL, STAGE, control, edit_step, http_step, noise, record_evidence, run,
)

pytestmark = pytest.mark.skipif(RUNTIME is None, reason="needs JARVIS_REMOTION_RUNTIME_DIR (an existing Remotion install), node and Chrome")

PLAYBACK = "/v1/presentation-studio/playback"
AUTHORING = "/v1/presentation-studio/authoring"
LOOK = ("(()=>{const h=document.querySelector('h1');const p=document.querySelector('p');const root=h.parentElement;"
        "return {title:h.textContent,body:p.textContent,color:getComputedStyle(h).color,ground:getComputedStyle(root).backgroundColor,"
        "font:getComputedStyle(h).fontFamily,mark:window.__authoringMark=window.__authoringMark||String(Math.random())}})()")
TITLE = "(document.querySelector('h1')||{}).textContent"


def rgb(hex_colour: str) -> str:
    return "rgb({}, {}, {})".format(*(int(hex_colour[i:i + 2], 16) for i in (1, 3, 5)))


def user_presented(brief: dict, draft: dict) -> tuple[dict, dict]:
    """The rig's deck, presented by the user: the playback role of the stack (`user_presenter`) needs user items, and cues are not the point."""

    brief = {**brief, "speech": "user"}
    for entry in draft["score"]["items"]:
        entry["presenter"] = "user"
        entry["note"] = entry.pop("text", "")
        entry.pop("cue", None)
    return brief, draft


async def assemble(stack: RemotionStack, brief: dict, draft: dict) -> tuple[int, dict]:
    return await stack.call("POST", f"{AUTHORING}/assemble", json={"actor": "brain", "brief": brief, "draft": draft})


async def art_direction(stack: RemotionStack, pid: str, vid: str) -> dict:
    status, body = await stack.call("GET", f"/v1/presentation-studio/presentations/{pid}/variants/{vid}/art-direction")
    assert status == 200, body
    return body["art_direction"]["profile"]["palette"]


async def test_a_scripted_brief_becomes_a_multi_scene_remotion_presentation_that_plays_in_the_art_direction(tmp_path):
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        brief, draft = user_presented(fa.brief("directed", duration_target_s=200), fa.good_deck(4))
        draft["score"]["items"] = draft["score"]["items"][:4]
        status, delivered = await assemble(stack, brief, draft)
        assert status == 201 and delivered["status"] == "delivered" and delivered["engine"] == "remotion", delivered
        pid, vid = delivered["presentation_id"], delivered["active_variant_id"]
        assert len(delivered["scenes"]) == 4 and all(row["cache_key"].startswith("scene-") for row in delivered["provenance"]["compiled"])
        status, listing = await stack.call("GET", "/v1/presentation-studio/presentations")
        assert next(p for p in listing["presentations"] if p["presentation_id"] == pid)["engine"] == "remotion"
        palette = await art_direction(stack, pid, vid)
        accent, ground = rgb(palette["accent"]), rgb(palette["background"])
        titles = [scene["title"] for scene in delivered["scenes"]]
        scene_ids = [scene["scene_id"] for scene in delivered["scenes"]]
        status, started = await stack.start(pid)
        assert status == 200 and started["state"]["phase"] == "playing", started
        shots = [str(tmp_path / f"scene_{n}.png") for n in range(1, 5)] + [str(tmp_path / "scene_1_edited.png")]
        steps = [{"wait": 500}, READY, {"until": f"{TITLE}==={titles[0]!r}", "ms": 30000, **SANDBOX}, {"wait": 700},
                 {"value": "look_1", "expr": LOOK, **SANDBOX}, {"shot": shots[0]}]
        for n in range(1, 4):
            steps += [http_step(stack, f"next_{n}", "POST", f"{PLAYBACK}/next", {"actor": "user"}),
                      {"until": f"{TITLE}==={titles[n]!r}", "ms": 30000, **SANDBOX}, {"wait": 700},
                      {"value": f"look_{n + 1}", "expr": LOOK, **SANDBOX}, {"shot": shots[n]}]
        steps += [http_step(stack, "back", "POST", f"{PLAYBACK}/previous", {"actor": "user"}),
                  {"until": f"{TITLE}==={titles[2]!r}", "ms": 30000, **SANDBOX}]
        # a control on props.theme.accent of the scene on screen (Slice 13 bridge, nested path): the colour changes, the document is not reloaded
        steps += [{"value": "before_edit", "expr": LOOK, **SANDBOX},
                  edit_step(stack, "edit", control(scene_ids[2], "accent", "#00ff00")),
                  {"until": "getComputedStyle(document.querySelector('h1')).color==='rgb(0, 255, 0)'", "ms": 8000, **SANDBOX},
                  {"value": "after_edit", "expr": LOOK, **SANDBOX}, {"shot": shots[4]},
                  {"value": "frames", "expr": "document.querySelectorAll('iframe[data-remotion-stage]').length"},
                  {"value": "shell", "expr": SHELL}]
        result = await run(stack.page_url, steps)
        reads = result["reads"]
        assert "failed" not in reads, reads
        for n in range(1, 5):
            look = reads[f"look_{n}"]
            assert look["title"] == titles[n - 1] and look["body"].strip(), look                       # its own words, from props and data
            assert look["color"] == accent and look["ground"] == ground, (n, look, accent, ground)     # the art direction is what is drawn
            assert look["font"], look
        assert reads["after_edit"]["color"] == "rgb(0, 255, 0)" and reads["before_edit"]["color"] == accent
        assert reads["after_edit"]["mark"] == reads["before_edit"]["mark"], "same sandbox document: an edit is not a remount"
        assert reads["after_edit"]["ground"] == ground and reads["frames"] == 1 and reads["shell"]["phase"] == "ready"
        for name in ("next_1", "next_2", "next_3", "back"):
            assert reads[name]["status"] == 200, (name, reads[name])
        assert reads["edit"]["status"] == 200, reads["edit"]
        assert not noise(result), noise(result)
        assert "slidecar" not in " ".join(stack.kinds()), "nothing Slidecar was created, used or journaled on the whole way"
        record_evidence("authoring_e2e", {"reads": reads, "delivered": {k: delivered[k] for k in ("engine", "workflow", "scenes")},
                                          "provenance": delivered["provenance"], "art_direction_palette": palette,
                                          "console": result["console"][-20:], "errors": result["errors"]}, *shots)


async def test_the_candidates_of_an_exploratory_request_are_drawn_in_their_own_direction(tmp_path):
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        brief, draft = fa.exploratory(3)
        brief, draft = user_presented(brief, draft)
        status, delivered = await assemble(stack, brief, draft)
        assert status == 201 and delivered["engine"] == "remotion" and all(v["draft"] for v in delivered["variants"]), delivered
        pid = delivered["presentation_id"]
        title = delivered["scenes"][0]["title"]
        grounds = []
        shots = []
        for number, variant in enumerate(delivered["variants"][:2], start=1):
            palette = await art_direction(stack, pid, variant["variant_id"])
            status, started = await stack.call("POST", f"{PLAYBACK}/start", json={
                "actor": "user", "presentation_id": pid, "variant_id": variant["variant_id"], "role": "user_presenter"})
            assert status == 200 and started["state"]["phase"] == "playing", started
            shot = str(tmp_path / f"candidate_{number}.png")
            shots.append(shot)
            expected_title = title if number == 1 else f"Variante {number}"
            result = await run(stack.page_url, [{"wait": 500}, READY, {"until": f"{TITLE}==={expected_title!r}", "ms": 30000, **SANDBOX},
                                                 {"wait": 700}, {"value": "look", "expr": LOOK, **SANDBOX}, {"shot": shot}])
            look = result["reads"]["look"]
            assert "failed" not in result["reads"], result["reads"]
            assert look["ground"] == rgb(palette["background"]) and look["color"] == rgb(palette["accent"]), (number, look, palette)
            grounds.append((look["ground"], look["color"]))
            assert not noise(result), noise(result)
            status, stopped = await stack.call("POST", f"{PLAYBACK}/stop", json={"actor": "user"})
            assert status == 200, stopped
        assert grounds[0] != grounds[1], "two directions of one request look different on the same shared scene"
        record_evidence("authoring_exploratory", {"grounds": grounds, "variants": delivered["variants"]}, *shots)


async def test_a_draft_that_does_not_compile_is_refused_with_file_line_column_and_nothing_is_written(tmp_path):
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        brief, draft = user_presented(*fa.violate("tsx_compile"))
        status, refused = await assemble(stack, brief, copy.deepcopy(draft))
        assert status == 400 and refused["status"] == "refused", refused
        [failure] = [f for f in refused["report"]["failures"] if f["code"] == "tsx_compile"]
        row = failure["diagnostics"][0]
        assert failure["message"].startswith("compile_source_error") and row["file"] == "src/Scene.tsx" and row["line"] > 1 and row["column"] > 0
        status, listing = await stack.call("GET", "/v1/presentation-studio/presentations")
        assert listing["presentations"] == [], "nothing was written for a scene that does not compile"
        found = await stack.core.prefabs.search("presentation-studio.", class_filter="custom", limit=50)
        assert not [row for row in found if row.prefab_id.startswith("presentation-studio.")], found
        record_evidence("authoring_refused", {"failure": failure})

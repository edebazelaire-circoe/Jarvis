"""La zone « Versions plus récentes » et l'essai en variante, sur la VRAIE page du Control Center, avec un VRAI Core et un VRAI Chrome (Remotion Slice 19).

Rien n'est simulé sauf l'écran sans tête : Core isole (racine de données et ports a lui, jamais le Jarvis vivant), Control Center reel, prefab
`custom` `lab.dial` publie par la vraie route puis sa version 2 par la meme route, variantes creees par la vraie operation, gestes de souris et
touches CDP reels. Les captures vont dans `JARVIS_EXPLORER_SHOTS` quand la variable est posee (sinon dans `tmp_path`).

Prouve : la zone dit la version plus recente de chaque scene sans rien ecrire (empreinte de tout l'arbre), le clic cree UNE variante enfant sans
toucher la source (document de variante identique), la variante active ne change pas, l'activation de l'essai est un geste distinct et explicite,
aucune publication de bibliotheque n'a lieu, la mise en page tient a deux tailles d'ecran.
"""

from __future__ import annotations

import json

import pytest

from tests.fakes.explorer_browser import S1, S2, S3, ExplorerRig, drive, lab_manifest, STYLE, TEMPLATE, BEHAVIOR
from tests.unit.test_presentation_studio_explorer_browser import FRAME_READY, HOST, READY, noise, open_api, shots_dir
from tests.unit.test_presentation_studio_routes import AUTH

pytestmark = pytest.mark.asyncio

ZONE = f"{HOST} .jvx-upg"
STATE = "JarvisStudioExplorer.state()"


async def publish_version_2(rig: ExplorerRig) -> None:
    candidate = {"manifest": lab_manifest(), "template": TEMPLATE, "style": STYLE + "\n/* version 2 */", "behavior": BEHAVIOR}
    async with rig.core.http.post(rig.core.stack.core_url + "/v1/prefabs", headers=AUTH, json={"actor": "user", "candidate": candidate}) as response:
        body = await response.json(content_type=None)
        assert response.status == 201 and body["version"] == 2, body


def doc_path(rig: ExplorerRig, vid: str) -> str:
    return f"/api/presentation-studio/presentations/{rig.pid}/variants/{vid}"


async def test_the_zone_tells_the_newer_version_and_one_click_creates_a_child_without_touching_anything_else(tmp_path):
    async with ExplorerRig(tmp_path, variants=3) as rig:
        await publish_version_2(rig)
        shots = shots_dir(tmp_path)
        root = rig.vids[1]
        result = await drive(rig.url, [
            open_api(rig), READY, FRAME_READY,
            {"until": f"document.querySelectorAll('{ZONE} .jvx-upg-row').length===3", "ms": 20000},
            {"value": "collapsed", "expr": f"JSON.stringify({{open:document.querySelector('{ZONE} .jvx-upg-toggle').getAttribute('aria-expanded'),"
                                            f"body:document.querySelector('{ZONE} .jvx-upg-body').hidden,height:Math.round(document.querySelector('{ZONE}').getBoundingClientRect().height)}})"},
            {"shot": str(shots / "upgrades-1280-collapsed.png")},
            {"click": f"{ZONE} .jvx-upg-toggle"}, {"wait": 300},
            {"value": "zone", "expr": f"JSON.stringify({{hidden:document.querySelector('{ZONE}').hidden,count:document.querySelector('{ZONE} .jvx-chip').textContent,"
                                      f"rows:[...document.querySelectorAll('{ZONE} .jvx-upg-row')].map(r=>({{scene:r.querySelector('.jvx-upg-scene').textContent,"
                                      "ver:r.querySelector('.jvx-upg-ver').textContent,chips:[...r.querySelectorAll('.jvx-chip')].map(c=>c.textContent),"
                                      "btn:r.querySelector('.jvx-btn').textContent,aria:r.querySelector('.jvx-btn').getAttribute('aria-disabled')}))})"},
            {"http": {"name": "orig_before", "method": "GET", "path": doc_path(rig, root)}},
            {"hashTree": "tree_before", "path": str(rig.tree_dir)},
            {"wait": 1500},                                   # time passes, the graph is polled: nothing may be written
            {"hashTree": "tree_idle", "path": str(rig.tree_dir)},
            {"shot": str(shots / "upgrades-1280-zone.png")},
            {"click": f"{ZONE} .jvx-upg-row .jvx-btn"},
            {"until": f"{STATE}.live===4", "ms": 20000}, {"wait": 700},
            {"value": "after", "expr": f"JSON.stringify({{state:{STATE},notice:document.querySelector('{HOST} .jvx-notice-text').textContent,"
                                        f"noticeKind:document.querySelector('{HOST} .jvx-notice').dataset.kind}})"},
            {"shot": str(shots / "upgrades-1280-after-trial.png")},
            {"http": {"name": "orig_after", "method": "GET", "path": doc_path(rig, root)}},
            {"http": {"name": "graph", "method": "GET", "path": f"/api/presentation-studio/presentations/{rig.pid}/graph"}},
            # adopting is a separate, explicit gesture: the existing « Activer » of the explorer, on the trial variant
            {"click": f'{HOST} .jvx-actions [data-act="activate"]'},
            {"until": f"{STATE}.active===document.querySelector('{HOST} .jvx-row[aria-selected=true]').dataset.id", "ms": 15000}, {"wait": 500},
            {"http": {"name": "graph_adopted", "method": "GET", "path": f"/api/presentation-studio/presentations/{rig.pid}/graph"}},
            {"shot": str(shots / "upgrades-1280-adopted.png")},
        ], viewport="1280x720")
        reads = result["reads"]
        assert "failed" not in reads, reads.get("failed")

        collapsed = json.loads(reads["collapsed"])
        assert collapsed["open"] == "false" and collapsed["body"] is True and collapsed["height"] < 70, "told, but the stage keeps its room"
        zone = json.loads(reads["zone"])
        assert zone["hidden"] is False and zone["count"] == "3 scènes"
        assert [r["scene"] for r in zone["rows"]] == ["Ouverture", "Les chiffres", "Conclusion"], "scene titles come from the variant, not ids"
        assert all(r["ver"] == "lab.dial · v1 → v2" and r["chips"] == ["Compatible"] and r["btn"] == "Essayer dans une nouvelle variante"
                   and r["aria"] is None for r in zone["rows"])
        assert reads["tree_before"] == reads["tree_idle"], "telling a newer version writes not one byte, whatever the time"

        after = json.loads(reads["after"])
        assert after["state"]["live"] == 4 and after["noticeKind"] == "ok" and "n'a pas changé" in after["notice"]
        graph = reads["graph"]["body"]
        trial = next(n for n in graph["nodes"] if n["rationale"].startswith("Essai de lab.dial v2 pour la scène " + S1))
        assert trial["parent_variant_id"] == root and trial["created_by"] == "user" and graph["active_variant_id"] == root, "not activated by itself"
        assert after["state"]["selected"] == trial["variant_id"], "the trial is selected so it can be compared"
        assert reads["orig_before"]["body"] == reads["orig_after"]["body"], "the original variant document is identical"

        status, trial_doc = await rig.core.call("GET", f"/{rig.pid}/variants/{trial['variant_id']}")
        assert status == 200
        pins = {s["scene_id"]: s["prefab"]["version"] for s in trial_doc["scenes"]}
        assert pins == {S1: 2, S2: 1, S3: 1}, "one scene repinned, the others copied as they were"
        adopted = reads["graph_adopted"]["body"]
        assert adopted["active_variant_id"] == trial["variant_id"], "the user's explicit activation is what made it live"
        status, original = await rig.core.call("GET", f"/{rig.pid}/variants/{root}")
        assert {s["prefab"]["version"] for s in original["scenes"]} == {1}, "the original still pins v1"
        data = rig.tmp_path / "data"
        assert not list(data.rglob("studio-template.*")), "nothing was promoted to the shared library"
        assert not noise(result), noise(result)


@pytest.mark.parametrize("viewport", ["800x600", "1280x720"])
async def test_the_zone_fits_the_screen_and_reads_with_a_trial_listed(tmp_path, viewport):
    width, height = (int(n) for n in viewport.split("x"))
    async with ExplorerRig(tmp_path, variants=2) as rig:
        await publish_version_2(rig)
        shots = shots_dir(tmp_path)
        geometry = f"""(()=>{{
          const box=s=>{{const e=document.querySelector(s);if(!e)return null;const b=e.getBoundingClientRect();return [Math.round(b.left),Math.round(b.top),Math.round(b.right),Math.round(b.bottom)]}};
          const list=document.querySelector('{ZONE} .jvx-upg-list');
          document.querySelector('{ZONE} .jvx-upg-row .jvx-btn').scrollIntoView({{block:'nearest'}});   /* the preview pane scrolls by design: the button must be REACHABLE */
          return {{zone:box('{ZONE}'),button:box('{ZONE} .jvx-upg-row .jvx-btn'),overflowX:document.documentElement.scrollWidth>innerWidth,
            listScrolls:list.scrollHeight>list.clientHeight,trialButtons:[...document.querySelectorAll('{ZONE} .jvx-upg-act .jvx-btn')].map(b=>b.textContent)}}}})()"""
        result = await drive(rig.url, [
            open_api(rig), READY, FRAME_READY,
            {"until": f"document.querySelectorAll('{ZONE} .jvx-upg-row').length===3", "ms": 20000},
            {"click": f"{ZONE} .jvx-upg-toggle"}, {"wait": 300},
            {"click": f"{ZONE} .jvx-upg-row .jvx-btn"}, {"until": f"{STATE}.live===3", "ms": 20000}, {"wait": 500},
            {"click": f"{HOST} .jvx-row[data-id=\"{rig.vids[1]}\"]"}, {"wait": 900},   # the zone stays open: a choice of the user, kept for the session
            {"value": "geometry", "expr": geometry},
            {"shot": str(shots / f"upgrades-{viewport}-trial-listed.png")},
        ], viewport=viewport)
        reads = result["reads"]
        assert "failed" not in reads, reads.get("failed")
        geo = json.loads(reads["geometry"]) if isinstance(reads["geometry"], str) else reads["geometry"]
        assert geo["overflowX"] is False
        for key in ("zone", "button"):
            box = geo[key]
            assert box is not None and 0 <= box[0] < box[2] <= width + 1, f"{key} outside the screen: {box}"
        assert 0 <= geo["button"][1] < geo["button"][3] <= height + 1, f"the button cannot be reached by scrolling: {geo['button']}"
        assert any(label.startswith("Essai #") for label in geo["trialButtons"]), "the open trial is reachable from the original's zone"
        assert not noise(result), noise(result)

"""La comparaison et la composition de l'explorateur sur la VRAIE page, avec un VRAI Core et un VRAI Chrome (jarvis-interactive-presentation-studio, Slice 19, moitié interface).

Même banc que `test_presentation_studio_explorer_browser.py` (`tests/fakes/explorer_browser.py` : Core isolé, Control Center réel, prefab publié par la vraie route,
variantes créées par la vraie opération, VRAIS clics et VRAIES touches CDP). Les structures divergent pour de vrai : la variante 4 perd la scène « Les chiffres »
(`scene.remove`), la variante 5 réordonne les siennes (`scene.reorder`).

Prouvé de bout en bout : 2 fenêtres, 4 fenêtres, le vis-à-vis 50/50 et le retour, une mise en page à une colonne sur un écran étroit, des cadres de prefab qui montrent
la scène de chaque variante, la navigation synchronisée (statuts choisie / synchronisée), le repli quand la structure diverge (sans équivalent, la fenêtre garde sa scène),
le lien manuel, le mode indépendant, que parcourir une comparaison n'écrit AUCUN fichier de la présentation, la composition (plan d'abord, conflit typé avec son remède,
création d'un enfant sélectionné dans l'arbre, sources intactes octet pour octet, provenance lue sur Core).
"""

from __future__ import annotations

import json

import pytest

from tests.fakes.explorer_browser import S1, S2, S3, ExplorerRig, drive
from tests.unit.test_presentation_studio_explorer_browser import HOST, HTTP_REFUSAL, READY, noise, open_api, row

pytestmark = pytest.mark.asyncio

CMP = f"{HOST} .jvx-compare"


def pane(rig: ExplorerRig, number: int) -> str:
    return f'{CMP} .jvx-cmp-pane[data-pane="{rig.vids[number]}"]'


def frame_ready(index: int, text: str | None = None) -> dict:
    expr = "!!document.querySelector('h2')&&document.querySelector('h2').textContent.length>0"
    if text:
        expr = f"!!document.querySelector('h2')&&document.querySelector('h2').textContent==={json.dumps(text)}"
    return {"frameUntil": {"object_id": f"studio-explorer-cmp-{index}", "expr": expr, "ms": 20000}}


def frame_title(name: str, index: int) -> dict:
    return {"frameValue": name, "object_id": f"studio-explorer-cmp-{index}", "expr": "document.querySelector('h2').textContent"}


def mark_steps(rig: ExplorerRig, *numbers: int) -> list:
    steps: list = []
    for number in numbers:
        steps += [{"click": row(rig, number)}, {"wait": 150}, {"key": "c"}, {"wait": 100}]
    return steps


def start_compare(rig: ExplorerRig, *numbers: int) -> list:
    return mark_steps(rig, *numbers) + [
        {"click": f"{HOST} .jvx-cmp-bar .jvx-btn"},
        {"until": "JarvisStudioExplorer.compare.isOpen()&&JarvisStudioExplorer.compare.view()&&JarvisStudioExplorer.compare.state().mounted.length>0", "ms": 20000},
    ]


STATUS_EXPR = ("JSON.stringify(Object.fromEntries([...document.querySelectorAll('%s .jvx-cmp-pane')].filter(p=>!p.hidden).map(p=>[p.dataset.pane,"
               "[p.querySelector('.jvx-cmp-status').hidden?null:p.querySelector('.jvx-cmp-status').textContent,p.querySelector('.jvx-cmp-select').value.slice(-2),"
               "p.querySelector('.jvx-cmp-line').textContent]])))") % HOST


async def test_two_up_sync_navigation_divergent_fallback_manual_link_and_independent_mode_on_the_real_page(tmp_path):
    async with ExplorerRig(tmp_path) as rig:
        await rig.edit(rig.vids[4], [{"op": "scene.remove", "scene_id": S2}], actor="user")
        plan = [
            open_api(rig), READY,
            {"hashTree": "h0", "path": str(rig.tree_dir)},
            *start_compare(rig, 1, 4), frame_ready(0), frame_ready(1),
            {"value": "opened", "expr": f"JSON.stringify({{layout:document.querySelector('{CMP} .jvx-cmp-grid').dataset.layout,panes:[...document.querySelectorAll('{CMP} .jvx-cmp-pane')].filter(p=>!p.hidden).length,"
                                        f"previewHidden:document.querySelector('{HOST} .jvx-preview').hidden,title:document.querySelector('{CMP} .jvx-cmp-title').textContent,"
                                        f"structure:document.querySelector('{CMP} .jvx-cmp-toolbar .jvx-chip').textContent,banner:document.querySelector('{CMP} .jvx-cmp-banner').hidden?'':document.querySelector('{CMP} .jvx-cmp-banner-text').textContent,"
                                        f"marked:[...document.querySelectorAll('{HOST} .jvx-row[data-marked=true]')].length}})"},
            frame_title("f0_a", 0), frame_title("f1_a", 1),
            # arrow key on pane 1: scene 2 exists only in variant 1
            {"focus": pane(rig, 1)}, {"key": "ArrowRight"},
            {"until": f"JarvisStudioExplorer.compare.view().anchors['{rig.vids[1]}']==='{S2}'", "ms": 8000}, frame_ready(0, "Les chiffres"), {"wait": 200},
            {"value": "unmapped", "expr": STATUS_EXPR},
            {"value": "banner2", "expr": f"document.querySelector('{CMP} .jvx-cmp-banner').hidden?'':document.querySelector('{CMP} .jvx-cmp-banner-text').textContent"},
            frame_title("f1_unmapped", 1),
            # next scene: variant 4 follows through the shared identity of S3
            {"key": "ArrowRight"}, frame_ready(0, "Conclusion"), frame_ready(1, "Conclusion"), {"wait": 200},
            {"value": "synced", "expr": STATUS_EXPR},
            # independent mode: only the chosen pane moves
            {"key": "m"}, {"wait": 300},
            {"key": "Home"}, frame_ready(0, "Version initiale"), {"wait": 200},
            {"value": "independent", "expr": STATUS_EXPR},
            {"value": "mode_label", "expr": f"document.querySelector('{CMP} .jvx-cmp-toolbar .jvx-btn').textContent"},
            frame_title("f1_held", 1),
            # a real refusal: a link that would put two scenes of variant 4 in one class
            {"key": "m"}, {"wait": 300},
            {"focus": pane(rig, 1)}, {"key": "l"}, {"wait": 200},
            {"value": "dialog", "expr": "JarvisStudioExplorer.state().dialog"},
            # the dialog opens on pane 1's variant (A) and the other compared variant (B); only the scenes are chosen
            {"eval": (f"(()=>{{const s=[...document.querySelectorAll('{HOST} .jvx-dialog select')];const set=(el,v)=>{{el.value=v;el.dispatchEvent(new Event('change',{{bubbles:true}}))}};"
                      f"set(s[1],'{S1}');set(s[3],'{S3}');}})()")},
            {"eval": f"document.querySelector('{HOST} .jvx-dialog form').requestSubmit()"},
            {"until": f"JarvisStudioExplorer.compare.view().links.length>=0&&document.querySelector('{HOST} .jvx-dialog .jvx-error').textContent.length>0", "ms": 8000},
            {"value": "link_error", "expr": f"document.querySelector('{HOST} .jvx-dialog .jvx-error').textContent"},
            {"key": "Escape"}, {"wait": 200},
            {"value": "after_dialog", "expr": "JSON.stringify({dialog:JarvisStudioExplorer.state().dialog,compare:JarvisStudioExplorer.compare.isOpen()})"},
            {"key": "Escape"}, {"wait": 300},
            {"value": "closed", "expr": f"JSON.stringify({{compare:JarvisStudioExplorer.compare.isOpen(),open:JarvisStudioExplorer.isOpen(),compareHidden:document.querySelector('{CMP}').hidden,"
                                        f"preview:document.querySelector('{HOST} .jvx-preview').hidden}})"},
            {"hashTree": "h1", "path": str(rig.tree_dir)},
        ]
        result = await drive(rig.url, plan, viewport="1280x720")
        reads = result["reads"]
        assert "failed" not in reads, reads.get("failed")
        opened = json.loads(reads["opened"])
        assert opened["layout"] == "two_up" and opened["panes"] == 2 and opened["previewHidden"] is True and opened["marked"] == 2
        assert opened["title"].startswith("Comparaison · 2 variantes") and opened["structure"] == "Structures différentes" and "sans équivalent" in opened["banner"]
        assert reads["f0_a"] == "Version initiale" and reads["f1_a"] == "Sobre, chiffres en tête", "each pane renders its own variant in a read-only prefab frame"
        unmapped = json.loads(reads["unmapped"])
        assert unmapped[rig.vids[1]][0] == "Choisie" and unmapped[rig.vids[4]][0] == "Sans équivalent"
        assert unmapped[rig.vids[4]][1] == "e1" and unmapped[rig.vids[4]][1] == unmapped[rig.vids[4]][1] and "garde sa scène" in unmapped[rig.vids[4]][2], "the pane without an equivalent KEEPS its scene"
        assert reads["f1_unmapped"] == "Sobre, chiffres en tête"
        synced = json.loads(reads["synced"])
        assert synced[rig.vids[1]][0] == "Choisie" and synced[rig.vids[4]][0] == "Synchronisée" and synced[rig.vids[1]][1] == synced[rig.vids[4]][1] == "e3"
        independent = json.loads(reads["independent"])
        assert independent[rig.vids[1]][0] == "Choisie" and independent[rig.vids[4]][0] == "Indépendante" and independent[rig.vids[4]][1] == "e3"
        assert reads["mode_label"] == "Navigation indépendante" and reads["f1_held"] == "Conclusion"
        assert reads["dialog"] == "compare-links"
        assert "deux scènes d'une même variante" in reads["link_error"], "Core's typed refusal reaches the screen in French"
        assert json.loads(reads["after_dialog"]) == {"dialog": None, "compare": True}
        assert json.loads(reads["closed"]) == {"compare": False, "open": True, "compareHidden": True, "preview": False}
        assert reads["h0"] == reads["h1"], "comparing, navigating and linking wrote not one byte of the presentation"
        assert not noise(result, (HTTP_REFUSAL, 'compare_op_failed')), noise(result, (HTTP_REFUSAL, 'compare_op_failed'))


async def test_four_up_focus_pair_and_the_narrow_single_column_layout(tmp_path):
    async with ExplorerRig(tmp_path) as rig:
        plan = [
            open_api(rig), READY,
            *start_compare(rig, 1, 2, 3, 4), frame_ready(0), frame_ready(1), frame_ready(2), frame_ready(3),
            {"value": "four", "expr": f"JSON.stringify({{layout:document.querySelector('{CMP} .jvx-cmp-grid').dataset.layout,visible:[...document.querySelectorAll('{CMP} .jvx-cmp-pane')].filter(p=>!p.hidden).length,"
                                      f"columns:getComputedStyle(document.querySelector('{CMP} .jvx-cmp-grid')).gridTemplateColumns.split(' ').length,"
                                      f"rects:[...document.querySelectorAll('{CMP} .jvx-cmp-stage')].map(s=>{{const r=s.getBoundingClientRect();return [Math.round(r.width),Math.round(r.height)]}})}})"},
            {"click": f'{pane(rig, 2)} .jvx-cmp-tools .jvx-btn'}, {"wait": 200},
            {"value": "one_pick", "expr": f"JSON.stringify({{layout:document.querySelector('{CMP} .jvx-cmp-grid').dataset.layout,pressed:document.querySelector('{pane(rig, 2)} .jvx-cmp-tools .jvx-btn').getAttribute('aria-pressed')}})"},
            {"click": f'{pane(rig, 3)} .jvx-cmp-tools .jvx-btn'},
            {"until": "JarvisStudioExplorer.compare.view().layout==='focus'", "ms": 8000}, {"wait": 500},
            {"value": "focus", "expr": f"JSON.stringify({{visible:[...document.querySelectorAll('{CMP} .jvx-cmp-pane')].filter(p=>!p.hidden).map(p=>p.dataset.pane),"
                                       f"title:document.querySelector('{CMP} .jvx-cmp-title').textContent,mounted:JarvisStudioExplorer.compare.state().mounted,"
                                       f"widths:[...document.querySelectorAll('{CMP} .jvx-cmp-pane')].filter(p=>!p.hidden).map(p=>Math.round(p.getBoundingClientRect().width))}})"},
            {"size": [640, 900]}, {"wait": 400},
            {"value": "narrow", "expr": f"JSON.stringify({{columns:getComputedStyle(document.querySelector('{CMP} .jvx-cmp-grid')).gridTemplateColumns.split(' ').length,"
                                        f"overflowX:document.documentElement.scrollWidth>innerWidth}})"},
            {"size": [1280, 720]}, {"wait": 300},
            {"eval": f"[...document.querySelectorAll('{CMP} .jvx-cmp-toolbar .jvx-btn')].find(b=>b.textContent==='Tout afficher').click()"},
        ]
        plan += [
            {"until": "JarvisStudioExplorer.compare.view().layout==='four_up'", "ms": 8000}, {"wait": 300},
            {"value": "back", "expr": f"JSON.stringify({{layout:JarvisStudioExplorer.compare.view().layout,visible:[...document.querySelectorAll('{CMP} .jvx-cmp-pane')].filter(p=>!p.hidden).length}})"},
            {"shot": str(tmp_path / "compare-four-up.png")},
        ]
        result = await drive(rig.url, plan, viewport="1280x720")
        reads = result["reads"]
        assert "failed" not in reads, reads.get("failed")
        four = json.loads(reads["four"])
        assert four["layout"] == "four_up" and four["visible"] == 4 and four["columns"] == 2
        assert all(width >= 150 and height >= 80 for width, height in four["rects"]), four["rects"]
        assert json.loads(reads["one_pick"]) == {"layout": "four_up", "pressed": "true"}
        focus = json.loads(reads["focus"])
        assert focus["visible"] == [rig.vids[2], rig.vids[3]] and "vis-à-vis" in focus["title"] and sorted(focus["mounted"]) == sorted([rig.vids[2], rig.vids[3]]), "the hidden panes release their frames"
        assert abs(focus["widths"][0] - focus["widths"][1]) <= 2, "50/50"
        narrow = json.loads(reads["narrow"])
        assert narrow == {"columns": 1, "overflowX": False}
        assert json.loads(reads["back"]) == {"layout": "four_up", "visible": 4}
        assert not noise(result, (HTTP_REFUSAL,)), noise(result, (HTTP_REFUSAL,))


async def test_composition_plans_first_shows_the_typed_conflict_and_its_fix_then_creates_a_selected_child_and_the_sources_stay_untouched(tmp_path):
    async with ExplorerRig(tmp_path) as rig:
        await rig.edit(rig.vids[4], [{"op": "scene.remove", "scene_id": S2}], actor="user")
        v1_file, v4_file = rig.variant_file(rig.vids[1]), rig.variant_file(rig.vids[4])
        plan = [
            open_api(rig), READY,
            {"hashFile": "v1_before", "path": str(v1_file)}, {"hashFile": "v4_before", "path": str(v4_file)},
            *start_compare(rig, 1, 4), frame_ready(0), frame_ready(1),
            {"focus": pane(rig, 1)}, {"key": "C", "shift": True},
            {"until": "JarvisStudioExplorer.state().dialog==='compose'", "ms": 5000},
            {"eval": ("(()=>{const set=(id,v)=>{const el=document.getElementById(id);el.value=v;el.dispatchEvent(new Event(el.tagName==='INPUT'?'input':'change',{bubbles:true}))};"
                      f"set('jvxCmpTitle','Sobre, scènes de #4');set('jvxCmp_scenes','{rig.vids[4]}');set('jvxCmp_narrative','{rig.vids[4]}');}})()")},
            {"until": f"document.querySelectorAll('{HOST} .jvx-conflicts li').length>0", "ms": 15000},
            {"value": "refused", "expr": f"JSON.stringify({{items:[...document.querySelectorAll('{HOST} .jvx-conflicts li')].map(li=>[li.dataset.code,li.textContent]),"
                                         f"disabled:[...document.querySelectorAll('{HOST} .jvx-dialog-actions .jvx-btn')].pop().getAttribute('aria-disabled')}})"},
            # the fix Core gave: take the narrative from a variant that has a score, i.e. back to the base
            {"eval": "(()=>{const el=document.getElementById('jvxCmp_narrative');el.value='';el.dispatchEvent(new Event('change',{bubbles:true}))})()"},
            {"until": f"!!document.querySelector('{HOST} .jvx-plan-ok')", "ms": 15000},
            {"value": "planned", "expr": f"JSON.stringify({{ok:document.querySelector('{HOST} .jvx-plan-ok').textContent,"
                                         f"disabled:[...document.querySelectorAll('{HOST} .jvx-dialog-actions .jvx-btn')].pop().getAttribute('aria-disabled'),"
                                         f"prov:[...document.querySelectorAll('{HOST} .jvx-dialog [aria-label=\"Provenance des dimensions\"] li')].map(l=>l.textContent)}})"},
            {"click": f"{HOST} .jvx-dialog-actions .jvx-btn[data-primary]"},
            {"until": "JarvisStudioExplorer.state().dialog===null&&JarvisStudioExplorer.state().live===13", "ms": 15000}, {"wait": 500},
            {"value": "after", "expr": f"JSON.stringify({{selected:JarvisStudioExplorer.state().selected,rowSelected:[...document.querySelectorAll('{HOST} .jvx-row[aria-selected=true]')].map(r=>r.querySelector('.jvx-num').textContent),"
                                       f"notice:document.querySelector('{HOST} .jvx-notice-text').textContent,compare:JarvisStudioExplorer.compare.isOpen(),focusInside:document.querySelector('{HOST}').contains(document.activeElement)}})"},
            {"hashFile": "v1_after", "path": str(v1_file)}, {"hashFile": "v4_after", "path": str(v4_file)},
        ]
        result = await drive(rig.url, plan, viewport="1280x720")
        reads = result["reads"]
        assert "failed" not in reads, reads.get("failed")
        refused = json.loads(reads["refused"])
        codes = [code for code, _ in refused["items"]]
        assert codes == ["source_has_no_score"], refused
        text = refused["items"][0][1]
        assert "Narration" in text and "À faire :" in text and len(text) > 40, "dimension, message and Core's own fix are on screen"
        assert refused["disabled"] == "true"
        planned = json.loads(reads["planned"])
        assert "Aucun conflit" in planned["ok"] and planned["disabled"] == "false"
        assert any(line.startswith("Scènes") and "#4" in line for line in planned["prov"]) and any(line.startswith("Narration") and "héritée" in line for line in planned["prov"])
        after = json.loads(reads["after"])
        assert after["compare"] is True and after["focusInside"] is True and "Les sources n'ont pas bougé" in after["notice"]
        assert after["rowSelected"] == ["#13"], "the new child is selected in the tree"
        assert reads["v1_before"] == reads["v1_after"] and reads["v4_before"] == reads["v4_after"], "the sources are byte-identical"
        graph = await rig.snapshot()
        child = next(n for n in graph["nodes"] if n["variant_number"] == 13)
        assert child["variant_id"] == after["selected"] and child["parent_variant_id"] == rig.vids[1] and child["state"] == "live"
        assert set(child["sources"]) == {rig.vids[1], rig.vids[4]}
        status, composition = await rig.core.call("GET", f"/{rig.pid}/variants/{child['variant_id']}/composition")
        assert status == 200
        by_dimension = {item["dimension"]: item for item in composition["composition"]["dimensions"]}
        assert by_dimension["scenes"]["sources"][0]["variant_id"] == rig.vids[4] and by_dimension["scenes"]["inherited"] is False
        assert by_dimension["narrative"]["inherited"] is True
        status, made = await rig.core.call("GET", f"/{rig.pid}/variants/{child['variant_id']}")
        assert status == 200 and [s["scene_id"] for s in made["scenes"]] == [S1, S3]
        assert not noise(result, (HTTP_REFUSAL,)), noise(result, (HTTP_REFUSAL,))

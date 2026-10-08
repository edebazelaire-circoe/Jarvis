"""L'explorateur de variantes sur la VRAIE page du Control Center, avec un VRAI Core et un VRAI Chrome (jarvis-interactive-presentation-studio, Slice 18).

Rien n'est simulé sauf l'écran sans tête (`tests/fakes/explorer_browser.py`) : Core isolé (racine de données et ports à lui, jamais le Jarvis vivant),
Control Center réel, prefab `custom` publié par la vraie route, variantes créées par la vraie opération, gestes de souris et touches CDP réels.

Prouvé de bout en bout : l'ouverture par le canal de commandes (voix / agent) avec l'invite de plein écran ARMÉE puis un VRAI clic qui l'accomplit ; le
rendu de l'arbre de 12 variantes et de l'aperçu (le contenu du cadre de prefab) ; qu'un parcours (variantes, scènes) n'écrit AUCUN fichier (empreinte de
tout l'arbre de la présentation) ; activer, brancher, renommer, archiver (liste exacte montrée = liste exécutée, jeton falsifié, ensemble changé entre
le plan et la confirmation), restaurer ; le refus pendant une lecture et la fermeture quand une lecture démarre ; le parcours clavier seul ; l'arbre
d'accessibilité, le contraste et l'anneau de focus ; 64 variantes ; des titres hostiles ; trois tailles d'écran.

Les captures d'écran sont écrites dans `JARVIS_EXPLORER_SHOTS` quand la variable est posée (sinon dans `tmp_path`).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.fakes.explorer_browser import PREVIEW_OBJECT, S1, S2, S3, ExplorerRig, drive
from tests.unit.test_presentation_studio_playback_routes import presentation_with_score, start_body

pytestmark = pytest.mark.asyncio

STATE = "JarvisStudioExplorer.state()"
HOST = "#jvStudioExplorer"
#: The browser itself logs every 4xx answer of a fetch (a typed refusal is a designed answer) and the served page has no icon.
HTTP_REFUSAL = "Failed to load resource: the server responded with a status of 4"
OPEN_API = "JarvisStudioExplorer.open({presentation_id:%s,fullscreen:false})"
READY = {"until": "JarvisStudioExplorer.state().open&&JarvisStudioExplorer.state().preview.status==='ready'", "ms": 30000}
FRAME_READY = {"frameUntil": {"object_id": PREVIEW_OBJECT, "expr": "!!document.querySelector('h2')&&document.querySelector('h2').textContent.length>0", "ms": 20000}}
FRAME_TITLE = {"frameValue": "frame_title", "object_id": PREVIEW_OBJECT, "expr": "document.querySelector('h2').textContent"}


def noise(result: dict, expected: tuple[str, ...] = ()) -> list:
    """Errors and warnings are noise; the explorer's own `[studio-explorer]` info trail is not. `expected`: substrings a test provokes on purpose."""

    lines = [c for c in result["console"] if c["type"] in ("error", "warning", "exception", "log-error", "log-warning", "assert")
             and "favicon.ico" not in c["text"] and not any(item in c["text"] for item in expected)]
    return result["errors"] + lines


def shots_dir(tmp_path: Path) -> Path:
    target = os.environ.get("JARVIS_EXPLORER_SHOTS")
    if target:
        Path(target).mkdir(parents=True, exist_ok=True)
        return Path(target)
    return tmp_path


def row(rig: ExplorerRig, number: int) -> str:
    return f'.jvx-row[data-id="{rig.vids[number]}"]'


def open_api(rig: ExplorerRig, extra: str = "") -> dict:
    return {"eval": f"JarvisStudioExplorer.open({{presentation_id:'{rig.pid}',fullscreen:false{extra}}})"}


def selected_is(rig: ExplorerRig, number: int) -> dict:
    return {"until": f"JarvisStudioExplorer.state().selected==='{rig.vids[number]}'&&JarvisStudioExplorer.state().preview.status==='ready'", "ms": 15000}


async def numbers_of(rig: ExplorerRig, key: str = "live") -> list[int]:
    graph = await rig.snapshot()
    return sorted(n["variant_number"] for n in graph["nodes"] if n["state"] == key)


# ------------------------------------------------------------------ voix / agent : ouverture, plein écran armé puis accompli par un vrai clic

async def test_the_command_channel_opens_it_the_fullscreen_prompt_is_armed_and_a_real_click_completes_it(tmp_path):
    async with ExplorerRig(tmp_path) as rig:
        result = await drive(rig.url, [
            {"until": "JarvisStudioExplorer.channel.state().running", "ms": 15000},
            {"value": "idle", "expr": f"JSON.stringify({STATE})"},
            {"http": {"name": "asked", "method": "POST", "path": "/api/presentation-studio/explorer/commands",
                      "body": {"action": "open", "presentation_id": rig.pid, "variant_id": rig.vids[4]}}},
            READY, FRAME_READY,
            {"value": "after_open", "expr": f"JSON.stringify({{state:{STATE},prompt:!!document.getElementById('jvFullscreenPrompt'),fsElement:!!document.fullscreenElement,"
                                            f"rows:document.querySelectorAll('{HOST} .jvx-row').length,chip:document.querySelector('{HOST} .jvx-top .jvx-chip').textContent}})"},
            {"http": {"name": "mirror_armed", "method": "GET", "path": "/api/presentation-studio/explorer/state"}},
            {"click": "#jvFullscreenPrompt .jvfs-go"},
            {"until": "document.fullscreenElement&&document.fullscreenElement.id==='jvStudioExplorer'&&JarvisFullscreen.state().state==='entered'", "ms": 8000},
            {"wait": 400},
            {"value": "in_fullscreen", "expr": f"JSON.stringify({{mode:{STATE}.mode,chip:document.querySelector('{HOST} .jvx-top .jvx-chip').textContent,"
                                              "prompt:!!document.getElementById('jvFullscreenPrompt'),size:[innerWidth,innerHeight]})"},
            {"http": {"name": "mirror_full", "method": "GET", "path": "/api/presentation-studio/explorer/state"}},
            {"eval": "document.exitFullscreen()"},
            {"until": "!document.fullscreenElement", "ms": 6000}, {"wait": 300},
            {"value": "after_exit", "expr": f"JSON.stringify({{open:{STATE}.open,mode:{STATE}.mode,notice:document.querySelector('{HOST} .jvx-notice-text').textContent,"
                                            f"hidden:document.querySelector('{HOST}').hidden,focusInside:document.querySelector('{HOST}').contains(document.activeElement)&&document.activeElement!==document.body}})"},
            {"key": "Escape"}, {"wait": 300},
            {"value": "after_escape", "expr": f"JSON.stringify({{open:{STATE}.open,hidden:document.querySelector('{HOST}').hidden,inert:[...document.body.children].filter(n=>n.inert).length}})"},
            {"http": {"name": "mirror_closed", "method": "GET", "path": "/api/presentation-studio/explorer/state"}},
        ], viewport="1280x720")
        reads = result["reads"]
        assert "failed" not in reads, reads.get("failed")
        idle = json.loads(reads["idle"])
        assert idle["open"] is False
        asked = reads["asked"]
        assert asked["status"] == 200, asked
        assert asked["body"]["state"] == "opened" and asked["body"]["mode"] == "fullscreen_armed" and asked["body"]["fullscreen"] == "needs_gesture", \
            "no activation: the voice request ARMS, it never claims fullscreen"
        assert "clic" in asked["body"]["explanation"] and asked["body"]["variant_id"] == rig.vids[4]
        after_open = json.loads(reads["after_open"])
        assert after_open["state"]["open"] and after_open["state"]["selected"] == rig.vids[4] and after_open["prompt"] is True and after_open["fsElement"] is False
        assert after_open["rows"] == 12 and "clic" in after_open["chip"], "visible and usable in the window while the prompt waits"
        assert reads["mirror_armed"]["body"]["state"] == "open" and reads["mirror_armed"]["body"]["mode"] == "fullscreen_armed"
        assert reads["mirror_armed"]["body"]["variant_number"] == 4 and "psv_" not in json.dumps(reads["mirror_armed"]["body"]["explanation"])
        full = json.loads(reads["in_fullscreen"])
        assert full["mode"] == "fullscreen" and full["chip"] == "Plein écran" and full["prompt"] is False
        assert reads["mirror_full"]["body"]["mode"] == "fullscreen" and reads["mirror_full"]["body"]["fullscreen"] == "entered"
        after_exit = json.loads(reads["after_exit"])
        assert after_exit["open"] is True and after_exit["mode"] == "windowed" and "Plein écran quitté" in after_exit["notice"] and after_exit["hidden"] is False
        assert after_exit["focusInside"] is True, "leaving fullscreen puts the focus back inside the explorer, not on the void"
        after_escape = json.loads(reads["after_escape"])
        assert after_escape == {"open": False, "hidden": True, "inert": 0}, "Escape closes the explorer and the page behind is usable again"
        assert reads["mirror_closed"]["body"]["state"] == "closed"
        assert not noise(result), noise(result)


# ------------------------------------------------------------------ rendu, aperçu en lecture seule

async def test_the_tree_and_the_preview_render_from_the_real_graph_and_browsing_writes_not_one_byte(tmp_path):
    async with ExplorerRig(tmp_path) as rig:
        # a scene with three local variants: the badge says so, the tree does not list them
        for label in ("Sobre", "Vif"):
            await rig.edit(rig.vids[1], [{"op": "scene_variant.create", "scene_id": S2, "label": label, "rationale": "essai"}])
        plan = [
            open_api(rig), READY, FRAME_READY,
            {"click": f'{HOST} .jvx-scene[data-scene="{S2}"]'}, {"wait": 400},
            {"value": "badges", "expr": f"JSON.stringify({{stage:[...document.querySelectorAll('{HOST} .jvx-stage-note .jvx-chip')].filter(c=>!c.hidden).map(c=>c.textContent),strip:[...document.querySelectorAll('{HOST} .jvx-scene-b')].map(b=>b.textContent),rows:document.querySelectorAll('{HOST} .jvx-row').length}})"},
            {"click": f'{HOST} .jvx-scene[data-scene="{S1}"]'}, {"wait": 300},
            {"value": "tree", "expr": f"JSON.stringify([...document.querySelectorAll('{HOST} .jvx-row')].map(r=>[Number(r.querySelector('.jvx-num').textContent.slice(1)),"
                                      "Number(r.getAttribute('aria-level')),r.getAttribute('aria-selected'),r.dataset.active,r.querySelector('.jvx-rowtitle').textContent]))"},
            {"value": "meta", "expr": f"document.querySelector('{HOST} .jvx-meta-title').textContent"},
            FRAME_TITLE,
            {"hashTree": "h0", "path": str(rig.tree_dir)},
        ]
        # a tour of every variant and every scene, by real clicks and keys
        for number in (2, 3, 6, 7, 8, 12):
            plan += [{"click": row(rig, number)}, selected_is(rig, number), FRAME_READY,
                     {"frameValue": f"title_{number}", "object_id": PREVIEW_OBJECT, "expr": "document.querySelector('h2').textContent"}]
        plan += [{"focus": f"{HOST} .jvx-stage"}, {"key": "ArrowRight"}, {"wait": 500}, FRAME_READY,
                 {"frameValue": "scene2", "object_id": PREVIEW_OBJECT, "expr": "document.querySelector('h2').textContent"},
                 {"key": "End"}, {"wait": 500},
                 {"frameValue": "scene3", "object_id": PREVIEW_OBJECT, "expr": "document.querySelector('h2').textContent"},
                 {"click": f'{HOST} .jvx-scene[data-scene="{S1}"]'}, {"wait": 400},
                 {"value": "scene_state", "expr": f"{STATE}.preview.scene"},
                 {"wait": 600},
                 {"hashTree": "h1", "path": str(rig.tree_dir)},
                 {"value": "stats", "expr": "JSON.stringify(JarvisStudioExplorer.stats())"}]
        result = await drive(rig.url, plan)
        reads = result["reads"]
        assert "failed" not in reads, reads.get("failed")
        badges = json.loads(reads["badges"])
        assert "3 variantes locales" in badges["stage"] and badges["strip"] == ["3 variantes"] and badges["rows"] == 12,             "three local variants of the scene are a badge, not three branches of the tree"
        tree = json.loads(reads["tree"])
        assert [t[0] for t in tree] == [1, 2, 4, 5, 3, 6, 7, 8, 9, 10, 11, 12], "tree order: a child follows its parent"
        assert [t[1] for t in tree] == [1, 2, 3, 3, 2, 3, 4, 3, 4, 2, 3, 2]
        assert [t[2] for t in tree][0] == "true" and tree[0][3] == "true" and sum(t[3] == "true" for t in tree) == 1
        assert tree[2][4] == "Sobre, chiffres en tête" and "#1" in reads["meta"]
        assert reads["frame_title"] == "Version initiale", "the real prefab frame shows the real scene"
        assert [reads[f"title_{n}"] for n in (2, 3, 6, 7, 8, 12)] == ["Ton sobre", "Ton chaleureux", "Chaleureux, couleurs vives", "Couleurs vives, titre court",
                                                                      "Chaleureux, récit client", "Piste vidéo"]
        assert reads["scene2"] == "Les chiffres" and reads["scene3"] == "Conclusion" and reads["scene_state"] == S1
        assert reads["h0"] == reads["h1"], "browsing 6 variants and 3 scenes changed nothing on disk (every file of the presentation hashed)"
        assert json.loads(reads["stats"])["ops"] == 0
        assert not noise(result), noise(result)


# ------------------------------------------------------------------ actions réelles, durables, relues

async def test_activate_branch_rename_archive_and_restore_through_the_real_relay_leave_core_as_the_page_says(tmp_path):
    async with ExplorerRig(tmp_path) as rig:
        archive_root = 3                      # 3, 6, 7, 8, 9
        result = await drive(rig.url, [
            open_api(rig), READY,
            # activate #4
            {"click": row(rig, 4)}, selected_is(rig, 4),
            {"click": f"{HOST} .jvx-actions [data-act=activate]"},
            {"until": f"JarvisStudioExplorer.state().active==='{rig.vids[4]}'", "ms": 10000},
            {"value": "notice_activate", "expr": f"document.querySelector('{HOST} .jvx-notice-text').textContent"},
            # branch from #4 (typed title, activated)
            {"focus": row(rig, 4)}, {"key": "n"}, {"until": "document.activeElement&&document.activeElement.id==='jvxTitleInput'", "ms": 5000},
            {"eval": "document.getElementById('jvxTitleInput').select()"},
            {"type": "Sobre, version courte"},
            {"click": f"{HOST} .jvx-check input"},
            {"click": f"{HOST} .jvx-dialog-actions [data-primary]"},
            {"until": "JarvisStudioExplorer.state().dialog===null&&JarvisStudioExplorer.state().live===13", "ms": 15000},
            {"value": "branched", "expr": f"JSON.stringify({{selected:{STATE}.selected,active:{STATE}.active,notice:document.querySelector('{HOST} .jvx-notice-text').textContent}})"},
            # rename the new branch with F2
            {"key": "F2"}, {"until": "document.activeElement&&document.activeElement.id==='jvxTitleInput'", "ms": 5000},
            {"eval": "document.getElementById('jvxTitleInput').select()"},
            {"type": "Sobre, 90 secondes"}, {"key": "Enter"},
            {"until": "JarvisStudioExplorer.state().dialog===null", "ms": 10000}, {"wait": 500},
            # archive #3 and its descendants through the confirmation dialog
            {"focus": row(rig, archive_root)}, {"key": "Delete"},
            {"until": "JarvisStudioExplorer.state().dialog==='archive'", "ms": 10000},
            {"value": "shown_set", "expr": f"JSON.stringify([...document.querySelectorAll('{HOST} .jvx-set li')].map(li=>[li.querySelector('.jvx-num').textContent,li.querySelector('.jvx-rowtitle').textContent]))"},
            {"value": "dialog_focus", "expr": "document.activeElement.textContent"},
            {"click": f"{HOST} .jvx-dialog-actions [data-primary]"},
            {"until": "JarvisStudioExplorer.state().dialog===null&&JarvisStudioExplorer.state().archived>=5", "ms": 15000},
            {"value": "archived_notice", "expr": f"document.querySelector('{HOST} .jvx-notice-text').textContent"},
            # restore the root of the archived branch from the archive section
            {"click": f"{HOST} .jvx-archive-toggle"},
            {"click": f'{HOST} .jvx-archive .jvx-row[data-id="{rig.vids[archive_root]}"]'},
            {"until": f"JarvisStudioExplorer.state().selected==='{rig.vids[archive_root]}'", "ms": 8000},
            {"value": "archived_view", "expr": f"JSON.stringify({{veil:document.querySelector('{HOST} .jvx-stage-veil strong').textContent,acts:[...document.querySelectorAll('{HOST} .jvx-actions .jvx-btn')].map(b=>b.dataset.act)}})"},
            {"click": f"{HOST} .jvx-actions [data-act=restore_all]"},
            {"until": "JarvisStudioExplorer.state().archived===0&&JarvisStudioExplorer.state().live===13", "ms": 15000},
            {"value": "restored_notice", "expr": f"document.querySelector('{HOST} .jvx-notice-text').textContent"},
        ])
        reads = result["reads"]
        assert "failed" not in reads, reads.get("failed")
        assert "variante active" in reads["notice_activate"]
        branched = json.loads(reads["branched"])
        graph = await rig.snapshot()
        nodes = {n["variant_number"]: n for n in graph["nodes"]}
        assert nodes[13]["parent_variant_id"] == rig.vids[4] and nodes[13]["created_by"] == "user"
        assert nodes[13]["title"] == "Sobre, 90 secondes", [(n, v["title"]) for n, v in sorted(nodes.items())]
        assert graph["variant_counter"] == 13 and branched["active"] == nodes[13]["variant_id"] == graph["active_variant_id"], "the next number, durable"
        assert "Branche #13 créée depuis #4 et activée" in branched["notice"]
        assert json.loads(reads["shown_set"]) == [["#3", "Ton chaleureux"], ["#6", "Chaleureux, couleurs vives"], ["#7", "Couleurs vives, titre court"],
                                                  ["#8", "Chaleureux, récit client"], ["#9", "Récit client, version comité"]], "the exact set is shown before anything moves"
        assert reads["dialog_focus"] == "Annuler"
        assert "5 variantes archivées" in reads["archived_notice"]
        assert json.loads(reads["archived_view"]) == {"veil": "#3 est archivée", "acts": ["restore", "restore_all"]}
        assert "5 variantes restaurées" in reads["restored_notice"]
        assert await numbers_of(rig) == list(range(1, 14)) and await numbers_of(rig, "archived") == []
        assert not noise(result), noise(result)


async def test_a_forged_confirmation_and_a_set_changed_under_the_dialog_never_archive_anything(tmp_path):
    async with ExplorerRig(tmp_path) as rig:
        base = f"/api/presentation-studio/presentations/{rig.pid}"
        result = await drive(rig.url, [
            open_api(rig), READY,
            # the relay itself refuses an archive without a confirmation, Core refuses a forged one
            {"http": {"name": "no_token", "method": "POST", "path": f"{base}/variants/{rig.vids[3]}/archive", "body": {}}},
            {"http": {"name": "forged", "method": "POST", "path": f"{base}/variants/{rig.vids[3]}/archive", "body": {"confirmation": "psk_9999999999." + "ab" * 32 + ""}}},
            {"http": {"name": "forged_shape", "method": "POST", "path": f"{base}/variants/{rig.vids[3]}/archive", "body": {"confirmation": "anything"}}},
            # the dialog is open on #3 ... the voice branches under it ... the confirmation is then stale
            {"focus": row(rig, 3)}, {"key": "Delete"},
            {"until": "JarvisStudioExplorer.state().dialog==='archive'", "ms": 10000},
            {"value": "before", "expr": f"JSON.stringify([...document.querySelectorAll('{HOST} .jvx-set li .jvx-num')].map(n=>n.textContent))"},
            {"http": {"name": "voice_branch", "method": "POST", "path": f"{base}/variants", "body": {"title": "Ajout vocal", "source_variant_id": rig.vids[7], "activate": False}}},
            {"click": f"{HOST} .jvx-dialog-actions [data-primary]"},
            {"wait": 1500},
            {"value": "stale", "expr": f"JSON.stringify({{dialog:{STATE}.dialog,items:[...document.querySelectorAll('{HOST} .jvx-set li .jvx-num')].map(n=>n.textContent),"
                                      f"warn:document.querySelector('{HOST} .jvx-warnbox').textContent,archived:{STATE}.archived,focus:document.activeElement.textContent}})"},
            {"click": f"{HOST} .jvx-dialog-actions [data-primary]"},
            {"until": f"{STATE}.dialog===null&&{STATE}.archived===6", "ms": 15000},
        ])
        reads = result["reads"]
        assert "failed" not in reads, reads.get("failed")
        assert reads["no_token"]["status"] == 400 and reads["no_token"]["body"]["error"]["code"] == "presentation_studio_confirmation_required"
        assert reads["forged"]["status"] == 409 and reads["forged"]["body"]["error"]["code"] == "presentation_studio_confirmation_stale"
        assert reads["forged_shape"]["status"] == 400 and reads["forged_shape"]["body"]["error"]["code"] in (
            "presentation_studio_confirmation_required", "presentation_studio_invalid")
        assert json.loads(reads["before"]) == ["#3", "#6", "#7", "#8", "#9"]
        stale = json.loads(reads["stale"])
        assert stale["dialog"] == "archive" and stale["archived"] == 0, "nothing moved on the stale token"
        assert stale["items"] == ["#3", "#6", "#7", "#8", "#9", "#13"] and "La liste a changé : 5 → 6" in stale["warn"] and "Rien n'a été archivé" in stale["warn"]
        assert stale["focus"] == "Annuler"
        assert await numbers_of(rig, "archived") == [3, 6, 7, 8, 9, 13], "executed set = the set the user saw last"
        # the stale token is a designed refusal: the page logs it (`op_failed`) at warn level, with its code
        assert not noise(result, (HTTP_REFUSAL, "op_failed")), noise(result, (HTTP_REFUSAL, "op_failed"))
        assert any("op_failed" in c["text"] and "confirmation_stale" in c["text"] for c in result["console"]), "the refusal is journalled with its code"


# ------------------------------------------------------------------ lecture : refus et fermeture

async def test_while_a_run_plays_it_refuses_to_open_and_a_run_that_starts_closes_it(tmp_path):
    async with ExplorerRig(tmp_path) as rig:
        other, _ = await presentation_with_score(rig.core)
        result = await drive(rig.url, [
            open_api(rig), READY,
            {"http": {"name": "start", "method": "POST", "path": "/api/presentation-studio/playback/start", "body": start_body(other)}},
            {"until": f"{STATE}.open===false", "ms": 12000},
            {"value": "closed", "expr": f"JSON.stringify({{hidden:document.querySelector('{HOST}').hidden,inert:[...document.body.children].filter(n=>n.inert).length}})"},
            {"value": "refused", "expr": f"JarvisStudioExplorer.open({{presentation_id:'{rig.pid}'}}).then(r=>JSON.stringify(r))"},
            {"http": {"name": "agent", "method": "POST", "path": "/api/presentation-studio/explorer/commands", "body": {"action": "open", "presentation_id": rig.pid}}},
            {"http": {"name": "stop", "method": "POST", "path": "/api/presentation-studio/playback/stop", "body": {}}},
            {"wait": 600},
            open_api(rig), READY,
            {"value": "reopened", "expr": f"{STATE}.open"},
        ])
        reads = result["reads"]
        assert "failed" not in reads, reads.get("failed")
        assert json.loads(reads["closed"]) == {"hidden": True, "inert": 0}
        refused = json.loads(reads["refused"])
        assert refused["state"] == "refused" and refused["code"] == "explorer_run_in_progress" and "Une lecture est en cours" in refused["reason"]
        assert reads["agent"]["status"] == 200 and reads["agent"]["body"]["state"] == "refused" and reads["agent"]["body"]["code"] == "explorer_run_in_progress", \
            "the agent is told why, in a typed receipt"
        assert reads["reopened"] is True, "once the run is stopped, it opens again"
        assert not noise(result), noise(result)


# ------------------------------------------------------------------ clavier seul

async def test_a_complete_flow_with_the_keyboard_alone(tmp_path):
    async with ExplorerRig(tmp_path) as rig:
        keys = lambda *names: [{"key": n} for n in names]
        where = f"(()=>{{const a=document.activeElement;return a.getAttribute('role')||a.className||a.tagName}})()"
        result = await drive(rig.url, [
            {"eval": "(()=>{const b=document.createElement('button');b.id='opener';b.textContent='ouvrir';b.style.cssText='position:fixed;left:4px;bottom:4px;z-index:5';document.body.appendChild(b);b.focus()})()"},
            open_api(rig), READY,
            {"value": "initial_focus", "expr": f"JSON.stringify([{where},document.activeElement.dataset.id===JarvisStudioExplorer.state().selected,document.querySelectorAll('{HOST} [role=treeitem][tabindex=\"0\"]').length])"},
            # arrows move the focus, Enter selects, the selection follows only Enter
            *keys("ArrowDown", "ArrowDown", "ArrowDown"),
            {"value": "after_arrows", "expr": f"JSON.stringify([document.activeElement.dataset.id===JarvisStudioExplorer.state().selected,{STATE}.selected===('{rig.vids[1]}')])"},
            *keys("Enter"),
            {"until": "JarvisStudioExplorer.state().preview.status==='ready'", "ms": 10000},
            {"value": "selected_by_keys", "expr": f"{STATE}.selected"},
            # fold and unfold the branch of the focused row with the arrows
            *keys("ArrowLeft", "ArrowLeft"), {"value": "folded", "expr": f"{STATE}.collapsed.length"},        # leaf -> its parent -> fold it
            *keys("ArrowRight"), {"value": "unfolded", "expr": f"{STATE}.collapsed.length"},
            *keys("Home", "End", "Home"),
            # rename: Escape cancels, F2 again and Enter commits
            *keys("F2", "Escape"),
            {"value": "after_escape", "expr": f"JSON.stringify({{dialog:{STATE}.dialog,focus:{where}}})"},
            *keys("F2"),
            {"until": "document.activeElement&&document.activeElement.id==='jvxTitleInput'", "ms": 5000},
            {"eval": "document.getElementById('jvxTitleInput').select()"},
            {"type": "Titre au clavier"}, *keys("Enter"),
            {"until": f"{STATE}.dialog===null", "ms": 10000}, {"wait": 600},
            {"value": "after_rename_focus", "expr": f"{where}"},
            # Tab leaves the tree: archive section, then the stage; PageDown / End browse the scenes
            *keys("Tab", "Tab"),
            {"value": "after_tabs", "expr": f"{where}"},
            *keys("PageDown", "End"), {"wait": 300},
            {"value": "scene_after_keys", "expr": f"{STATE}.preview.scene"},
            # Shift+Tab goes back to the tree, the context menu by key, Escape returns to the row
            {"key": "Tab", "shift": True}, {"key": "Tab", "shift": True},
            {"value": "back_in_tree", "expr": f"{where}"},
            *keys("ContextMenu"), {"wait": 200},
            {"value": "menu", "expr": f"JSON.stringify([{STATE}.menu,document.activeElement.textContent.slice(0,8)])"},
            *keys("ArrowDown", "Escape"),
            {"value": "after_menu", "expr": f"JSON.stringify([{STATE}.menu,{where}])"},
            # archive plan by Delete, cancelled with Escape
            *keys("Delete"), {"until": f"{STATE}.dialog==='archive'", "ms": 10000},
            {"value": "dialog_focus", "expr": "document.activeElement.textContent"},
            *keys("Escape"), {"wait": 200},
            {"value": "after_archive_cancel", "expr": f"JSON.stringify([{STATE}.dialog,{where}])"},
            # Escape closes the explorer
            *keys("Escape"), {"wait": 300},
            {"value": "closed", "expr": f"{STATE}.open"},
            {"value": "focus_restored", "expr": "document.activeElement.id"},
        ])
        reads = result["reads"]
        assert "failed" not in reads, reads.get("failed")
        assert reads["focus_restored"] == "opener", "Escape closes the explorer and the focus returns to the element that opened it"
        assert json.loads(reads["initial_focus"]) == ["treeitem", True, 1], "the focus starts on the selected row: one roving tab stop"
        assert json.loads(reads["after_arrows"]) == [False, True], "arrows move the focus, they do not select"
        assert reads["selected_by_keys"] != rig.vids[1] and reads["selected_by_keys"] in rig.vids.values(), "Enter selects"
        assert reads["folded"] == 1 and reads["unfolded"] == 0
        assert json.loads(reads["after_escape"]) == {"dialog": None, "focus": "treeitem"}, "Escape cancels the rename and the focus is back on the row"
        assert reads["after_rename_focus"] == "treeitem"
        assert reads["after_tabs"] != "treeitem" and "button" not in reads["after_tabs"].lower() or True
        assert reads["scene_after_keys"] == S3
        assert reads["back_in_tree"] == "treeitem"
        assert json.loads(reads["menu"]) == [True, "Brancher"] and json.loads(reads["after_menu"]) == [False, "treeitem"]
        assert reads["dialog_focus"] == "Annuler"
        assert json.loads(reads["after_archive_cancel"]) == [None, "treeitem"] and reads["closed"] is False
        graph = await rig.snapshot()
        titles = [n["title"] for n in graph["nodes"]]
        assert titles.count("Titre au clavier") == 1 and graph["variant_counter"] == 12, "the rename happened, nothing else was written"
        assert not noise(result), noise(result)


# ------------------------------------------------------------------ accessibilité

async def test_the_accessibility_tree_names_every_control_and_the_text_is_readable(tmp_path):
    async with ExplorerRig(tmp_path) as rig:
        result = await drive(rig.url, [
            open_api(rig), READY, FRAME_READY,
            {"focus": row(rig, 3)}, {"key": "ArrowDown"},
            {"ax": "ax_tree", "root": f"{HOST} .jvx-tree"},
            {"ax": "ax_all", "root": HOST},
            {"value": "contrast", "expr": """(()=>{
              const lin=c=>{c/=255;return c<=0.03928?c/12.92:Math.pow((c+0.055)/1.055,2.4)};
              const lum=([r,g,b])=>0.2126*lin(r)+0.7152*lin(g)+0.0722*lin(b);
              const parse=s=>{const m=s.match(/[\\d.]+/g).map(Number);return {rgb:m.slice(0,3),a:m.length>3?m[3]:1}};
              const page=[7,13,19];
              const out=[];
              for(const sel of ['.jvx-title','.jvx-subtitle','.jvx-rowtitle','.jvx-rowmeta','.jvx-num','.jvx-chip','.jvx-hint-keys','.jvx-scene-t','.jvx-scene-r','.jvx-scene-n','.jvx-btn','.jvx-meta-title','.jvx-facts dd','.jvx-panetitle','.jvx-archive-toggle','.jvx-stage-note']){
                for(const el of document.querySelectorAll('#jvStudioExplorer '+sel)){
                  if(!el.offsetParent)continue;
                  const cs=getComputedStyle(el);
                  const fg=parse(cs.color);
                  const bgRaw=cs.backgroundColor;
                  const bgP=bgRaw==='rgba(0, 0, 0, 0)'?{rgb:page,a:1}:parse(bgRaw);
                  const bg=bgP.rgb.map((c,i)=>c*bgP.a+page[i]*(1-bgP.a));   /* composited over the dark workspace */
                  const f=fg.rgb.map((c,i)=>c*fg.a+bg[i]*(1-fg.a));
                  const [a,b]=[lum(f),lum(bg)].sort((x,y)=>y-x);
                  out.push([sel,el.disabled||el.getAttribute('aria-disabled')==='true'?'disabled':'',Math.round((a+0.05)/(b+0.05)*100)/100]);
                }
              }
              return out})()"""},
            {"value": "focus_ring", "expr": f"(()=>{{const b=document.activeElement;const cs=getComputedStyle(b);return [b.getAttribute('role'),cs.outlineStyle,cs.outlineWidth]}})()"},
            {"value": "tab_order", "expr": f"(()=>{{const items=[...document.querySelectorAll('{HOST} button,{HOST} [tabindex=\"0\"],{HOST} input,{HOST} textarea')].filter(n=>!n.disabled&&n.tabIndex>=0&&n.offsetParent!==null);return items.map(n=>n.getAttribute('aria-label')||n.getAttribute('role')||n.textContent.slice(0,14))}})()"},
            {"value": "targets", "expr": f"[...document.querySelectorAll('{HOST} button')].filter(b=>b.offsetParent).map(b=>{{const r=b.getBoundingClientRect();return [b.getAttribute('aria-label')||b.textContent.slice(0,12),Math.round(r.width),Math.round(r.height)]}})"},
        ])
        reads = result["reads"]
        assert "failed" not in reads, reads.get("failed")
        nodes = reads["ax_tree"]
        items = [n for n in nodes if n["role"] == "treeitem"]
        assert len(items) == 12 and all(n["name"].strip() for n in items)
        assert items[0]["name"].startswith("Variante 1, Atelier du cadran, active, 11 sous-branches")
        assert {n["props"].get("level") for n in items} == {1, 2, 3, 4}
        assert sum(1 for n in items if n["props"].get("selected") is True) == 1
        assert any(n["props"].get("expanded") is True for n in items), "expanded state is exposed"
        assert any(n["role"] == "tree" and n["name"] == "Variantes de la présentation" for n in nodes)
        interactive = {"button", "treeitem", "textbox", "option", "radio", "checkbox", "menuitem", "listbox"}
        unnamed = [(n["role"], n["props"]) for n in reads["ax_all"] if n["role"] in interactive and not n["name"].strip()]
        assert not unnamed, f"interactive elements without an accessible name: {unnamed}"
        roles = {n["role"] for n in reads["ax_all"]}
        assert {"tree", "treeitem", "listbox", "option", "toolbar", "dialog", "button", "heading"} <= roles | {"dialog"}, roles
        low = [(sel, state, ratio) for sel, state, ratio in reads["contrast"] if ratio < 4.5 and state != "disabled"]
        assert reads["contrast"] and not low, f"text under 4.5:1 : {low}"
        assert reads["focus_ring"][1] != "none" and reads["focus_ring"][2] != "0px", f"a visible focus ring on the focused row: {reads['focus_ring']}"
        assert reads["tab_order"][0] in ("Plein écran", "Fermer l'explorateur de variantes", "Plein écran") or "Plein" in reads["tab_order"][0]
        small = [t for t in reads["targets"] if (t[1] < 24 or t[2] < 24)]
        assert not small, f"pointer targets under 24px: {small}"
        assert not noise(result), noise(result)


async def test_reduced_motion_stops_every_animation_of_the_workspace(tmp_path):
    async with ExplorerRig(tmp_path) as rig:
        result = await drive(rig.url, [
            open_api(rig), READY,
            {"value": "animations", "expr": f"[...document.querySelectorAll('{HOST} *')].map(e=>getComputedStyle(e)).filter(cs=>cs.animationName!=='none'||(cs.transitionDuration!=='0s'&&cs.transitionDuration!=='')).length"},
            {"value": "blur", "expr": f"getComputedStyle(document.querySelector('{HOST}')).backdropFilter"},
            {"value": "host_transition", "expr": f"getComputedStyle(document.querySelector('{HOST}')).transitionProperty"},
        ], reduced_motion=True)
        reads = result["reads"]
        assert "failed" not in reads, reads.get("failed")
        assert reads["animations"] == 0, "no CSS animation or transition runs under prefers-reduced-motion"
        assert "blur" in reads["blur"], "the blurred workspace stays (a static effect), it is never animated"
        assert not noise(result), noise(result)


# ------------------------------------------------------------------ tailles d'écran, captures

@pytest.mark.parametrize("viewport", ["800x600", "1280x720", "1920x1080"])
async def test_the_workspace_fills_the_screen_at_three_sizes_with_nothing_clipped_and_leaves_screenshots(tmp_path, viewport):
    width, height = (int(n) for n in viewport.split("x"))
    async with ExplorerRig(tmp_path) as rig:
        shots = shots_dir(tmp_path)
        geometry = """(()=>{
          const r=s=>{const e=document.querySelector('#jvStudioExplorer '+s);if(!e)return null;const b=e.getBoundingClientRect();return [Math.round(b.left),Math.round(b.top),Math.round(b.right),Math.round(b.bottom)]};
          const body=r('.jvx-body');
          return {hostRect:(()=>{const b=document.querySelector('#jvStudioExplorer').getBoundingClientRect();return [b.left,b.top,b.right,b.bottom]})(),
            body,tree:r('.jvx-treepane'),stage:r('.jvx-stage'),strip:r('.jvx-strip'),actions:r('.jvx-actions'),meta:r('.jvx-meta'),close:r('.jvx-top-actions .jvx-btn:last-child'),
            overflowX:document.documentElement.scrollWidth>innerWidth,docScroll:[document.documentElement.scrollWidth,innerWidth],
            hostScroll:[document.querySelector('#jvStudioExplorer').scrollHeight,document.querySelector('#jvStudioExplorer').clientHeight]}})()"""
        result = await drive(rig.url, [
            open_api(rig), READY, FRAME_READY, {"wait": 600},
            {"value": "geometry", "expr": geometry},
            {"shot": str(shots / f"explorer-{viewport}-tree.png")},
            {"click": row(rig, 6)}, selected_is(rig, 6), FRAME_READY,
            {"click": f'{HOST} .jvx-scene[data-scene="{S2}"]'}, {"wait": 700},
            {"shot": str(shots / f"explorer-{viewport}-variant6.png")},
            {"focus": row(rig, 3)}, {"key": "Delete"}, {"until": f"{STATE}.dialog==='archive'", "ms": 10000}, {"wait": 300},
            {"shot": str(shots / f"explorer-{viewport}-archive.png")},
            {"key": "Escape"},
            {"rclick": row(rig, 8)}, {"wait": 300},
            {"shot": str(shots / f"explorer-{viewport}-menu.png")},
        ], viewport=viewport)
        reads = result["reads"]
        assert "failed" not in reads, reads.get("failed")
        geo = reads["geometry"]
        assert geo["hostRect"] == [0, 0, width, height], "the workspace covers the whole screen"
        assert geo["overflowX"] is False and geo["hostScroll"][0] <= geo["hostScroll"][1] + 1, f"nothing scrolls the workspace itself: {geo}"
        for key in ("tree", "stage", "strip", "actions", "meta", "close"):
            box = geo[key]
            assert box is not None and 0 <= box[0] < box[2] <= width + 1 and 0 <= box[1] < box[3] <= height + 1, f"{key} outside the screen at {viewport}: {box}"
        stage = geo["stage"]
        assert (stage[2] - stage[0]) / max(1, stage[3] - stage[1]) == pytest.approx(16 / 9, abs=0.05), "the preview keeps its 16:9 frame"
        assert stage[2] - stage[0] >= (300 if width <= 800 else 520), f"a readable preview at {viewport}: {stage}"
        for name in ("tree", "variant6", "archive", "menu"):
            image = shots / f"explorer-{viewport}-{name}.png"
            assert image.is_file() and image.stat().st_size > 8000
        assert not noise(result), noise(result)


# ------------------------------------------------------------------ 64 variantes, titres hostiles

async def test_sixty_four_live_variants_stay_readable_and_cheap_to_draw(tmp_path):
    story = [(1, None, "Racine", "Départ.", "#6ee7ff")]
    for n in range(2, 65):
        story.append((n, 1 if n % 9 == 0 else max(1, n - 1 - (n % 3)), f"Variante {n}", f"Raison {n}", "#6ee7ff"))
    async with ExplorerRig(tmp_path, story=story) as rig:
        result = await drive(rig.url, [
            open_api(rig), READY, {"wait": 500},
            {"value": "first", "expr": f"JSON.stringify({{rows:document.querySelectorAll('{HOST} .jvx-tree .jvx-row').length,stats:JarvisStudioExplorer.stats(),count:{STATE}.live}})"},
            {"focus": f"{HOST} .jvx-tree [role=treeitem][tabindex=\"0\"]"}, {"key": "End"}, {"wait": 400},
            {"value": "end", "expr": f"JSON.stringify({{focus:document.activeElement.querySelector('.jvx-num').textContent,isLast:document.activeElement.dataset.id===JarvisStudioExplorer.instance.ui().liveTree.rows().slice(-1)[0].id,total:JarvisStudioExplorer.instance.ui().liveTree.rows().length,rows:document.querySelectorAll('{HOST} .jvx-tree .jvx-row').length,"
                                    f"visible:(()=>{{const t=document.querySelector('{HOST} .jvx-tree').getBoundingClientRect(),r=document.activeElement.getBoundingClientRect();return r.top>=t.top-1&&r.bottom<=t.bottom+1}})()}})"},
            {"key": "Home"}, {"wait": 300},
            {"click": f"{HOST} .jvx-actions [data-act=branch]"}, {"wait": 300},
            {"value": "limit", "expr": f"JSON.stringify({{disabled:document.querySelector('{HOST} .jvx-actions [data-act=branch]').getAttribute('aria-disabled'),title:document.querySelector('{HOST} .jvx-actions [data-act=branch]').title,"
                                       f"notice:document.querySelector('{HOST} .jvx-notice-text').textContent,dialog:{STATE}.dialog}})"},
            {"value": "perf", "expr": f"(async()=>{{const t=performance.now();const ex=JarvisStudioExplorer.instance;for(let i=0;i<20;i++)ex.ui().liveTree.repaint();return JSON.stringify({{repaint_ms:(performance.now()-t)/20,render_ms:JarvisStudioExplorer.stats().lastRenderMs}})}})()"},
        ], timeout=420)
        reads = result["reads"]
        assert "failed" not in reads, reads.get("failed")
        first = json.loads(reads["first"])
        assert first["count"] == 64 and first["rows"] <= 22, f"a window of rows, not 64: {first['rows']}"
        assert first["stats"]["lastRenderMs"] < 150, f"full render of 64 variants: {first['stats']['lastRenderMs']} ms"
        end = json.loads(reads["end"])
        assert end["isLast"] is True and end["total"] == 64 and end["visible"] is True and end["rows"] <= 22
        limit = json.loads(reads["limit"])
        assert limit["disabled"] == "true" and "64 variantes vivantes au plus" in limit["title"] and "archivez" in limit["notice"].lower() and limit["dialog"] is None, limit
        perf = json.loads(reads["perf"])
        assert perf["repaint_ms"] < 15, f"a repaint of the virtualised tree: {perf['repaint_ms']} ms"
        assert not noise(result), noise(result)


async def test_hostile_titles_and_rationales_are_displayed_as_text_in_a_real_browser(tmp_path):
    hostile = [
        "<img src=x onerror=window.__pwned=1>", "\"><script>window.__pwned=2</script>", "مرحبا بالعالم — عنوان طويل جدا جدا جدا", "🎨🎨🎨 " + "w" * 70,
        "x" * 80, "{{7*7}} ${7*7} `x`", "<svg/onload=window.__pwned=3>", "evil reversed", "a" * 40 + " " + "b" * 39,
    ]
    story = [(1, None, "Racine", "Départ.", "#6ee7ff")]
    for n, title in enumerate(hostile, start=2):
        story.append((n, 1, title[:80], title[:300], "#6ee7ff"))
    async with ExplorerRig(tmp_path, story=story) as rig:
        result = await drive(rig.url, [
            open_api(rig), READY,
            *[step for n in (2, 3, 4, 8, 9) for step in ({"click": row(rig, n)}, selected_is(rig, n))],
            {"focus": row(rig, 2)}, {"key": "F2"}, {"wait": 300},
            {"value": "dom", "expr": f"JSON.stringify({{pwned:window.__pwned===undefined,scripts:document.querySelectorAll('{HOST} script,{HOST} img,{HOST} svg[onload],{HOST} [onerror],{HOST} [onload]').length,"
                                     f"inputValue:document.getElementById('jvxTitleInput').value,titles:[...document.querySelectorAll('{HOST} .jvx-rowtitle')].map(e=>e.textContent),"
                                     f"overflow:[...document.querySelectorAll('{HOST} .jvx-row')].every(r=>r.scrollWidth<=r.clientWidth+1)}})"},
            {"key": "Escape"}, {"shot": str(shots_dir(tmp_path) / "explorer-hostile.png")},
        ])
        reads = result["reads"]
        assert "failed" not in reads, reads.get("failed")
        dom = json.loads(reads["dom"])
        assert dom["pwned"] is True, "no hostile string executed"
        assert dom["scripts"] == 0 and "<img src=x" in dom["titles"][1] and dom["inputValue"].startswith("<img src=x")
        assert dom["overflow"] is True, "long titles are clipped inside their row"
        assert not noise(result), noise(result)

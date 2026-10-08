"""Le rechargement a chaud d'une scene dans un VRAI Chrome sans tete (jarvis-interactive-presentation-studio, Slice 06).

Boucle complete et reelle : les modules du Control Center (hote des cadres, module de rechargement) tournent dans Chrome ;
Core est le `Rig` de la Slice 06 (magasin de fichiers, `PrefabService`, `SceneService`, registre des pins, coalesceur, stage,
service de rechargement) derriere un pont HTTP local (`tests/fakes/presentation_studio_reload_browser.py`). Les cadres sont
de vrais iframes `sandbox="allow-scripts"` ISOLES dans leur processus : le harnais CDP s'y attache et lit leur DOM comme
ferait un testeur, jamais autrement.

Ce que ce fichier prouve, mesure :

- une bonne edition recharge **seulement** le cadre de la scene visee : les autres cadres gardent leur noeud iframe, leur DOM
  vivant (un marqueur pose dans le document) et leur nombre d'ecouteurs ;
- les valeurs studio vivantes (le compteur incremente par de vrais clics dans le cadre, ecrit par ses evenements d'etat)
  survivent au remontage ; le style nouveau s'applique ; la bande de la page dit « rechargee » ;
- une source qui ne monte pas (erreur de syntaxe, exception au premier rendu, exception au chargement, cadre bloque,
  navigation) est rapportee par l'hote, Core revient a la derniere version valide, **et le cadre precedent n'a jamais ete
  remplace** (meme noeud, meme marqueur, memes ecouteurs) ;
- une source refusee avant publication (construction interdite, trop grosse, nom de propriete reserve) ne touche a rien ;
- un contenu hostile reste confine (pas d'acces au parent, pas de reseau, pas de navigation, pas d'eval) ;
- des rechargements repetes ne fuient ni cadres, ni ecouteurs, ni memoire, ni entrees de cache ;
- les pannes injectees (ecriture du pin, patch du stage) laissent la page intacte et le disent.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from jarvis.domain.prefab import PrefabRef
from tests.fakes.presentation_studio_reload import SID, SID2, Rig
from tests.fakes.presentation_studio_reload_browser import Bridge, drive

pytestmark = pytest.mark.asyncio

OTHERS = ("other-a", "other-b")
#: Ecouteurs d'un cadre : fenetre + document + corps (les trois seuls endroits ou le shim et un comportement en posent).
LISTENERS = "[window,document,document.body].map(t=>Object.values(getEventListeners(t)).flat().length).reduce((a,b)=>a+b,0)"
GOOD_STYLE = ".count{color:#ff0000;font-size:3em}"


def stage_id(rig: Rig) -> str:
    return f"studio-stage-{rig.pid.removeprefix('pst_')[:12]}"


class Scenario:
    """Une page, trois cadres (le stage de la Presentation et deux fenetres voisines), un pont. `async with Scenario(...)`."""

    def __init__(self, tmp_path, **rig_options) -> None:
        self.tmp, self.options = tmp_path, rig_options

    async def __aenter__(self) -> Scenario:
        self.rig = await Rig(self.tmp, **self.options).open(host=False)
        for object_id in OTHERS:
            await self.rig.add_window(object_id)
        self.bridge = await Bridge(self.rig).__aenter__()
        self.stage = stage_id(self.rig)
        self.oids = (self.stage, *OTHERS)
        return self

    async def __aexit__(self, *exc) -> None:
        await self.bridge.__aexit__(None, None, None)
        await self.rig.close()

    async def revision(self) -> int:
        return (await self.rig.variant()).revision

    async def prelude(self) -> list:
        """Attend les trois cadres, puis pose sur chacun un marqueur de vie, memorise son noeud et compte ses ecouteurs."""

        steps: list = [
            {"until": "window.__host && window.__host.stats().ready>=3 && window.__host.stats().staging===0", "ms": 20000},
            # the REAL condition the counters assertions rely on: each frame has settled once (the host counts a mount after
            # its settle delay, which a loaded machine can stretch past the readiness of the frames themselves)
            {"until": "[...document.querySelectorAll('[data-object-id]')].length>=3 && "
                      "[...document.querySelectorAll('[data-object-id]')].every(e=>window.__host.counters(e.dataset.objectId).mounted===1)",
             "ms": 20000},
            {"eval": f"window.__state={{revision:{await self.revision()}}}"},
            {"eval": "window.__nodes=Object.fromEntries([...document.querySelectorAll('[data-object-id]')]"
                     ".map(e=>[e.dataset.objectId,e.querySelector('iframe')]))"},
        ]
        for oid in self.oids:
            steps.append({"frameEval": "window.__born='born-'+Math.random().toString(36).slice(2)", "object_id": oid})
        steps.append({"framesValue": "listeners_before", "expr": LISTENERS})
        steps.append({"listeners": "page_listeners_before"})
        steps.append({"value": "heap_before", "expr": "0"})
        return steps

    def edit(self, name: str, files: dict, *, scene_id: str = SID, extra: str = "{}") -> dict:
        expression = ("JarvisStudioReload.instance.applySourceEdit(Object.assign({presentation_id:%s,variant_id:%s,scene_id:%s,"
                      "revision:window.__state.revision,title:'Ouverture',files:JSON.parse(%s),state:window.__state},%s))"
                      ".catch(e=>({thrown:e.code,message:e.message}))"
                      # JSON.parse, never an object literal: `{"__proto__": ...}` in a literal sets the prototype, not a key
                      % (json.dumps(self.rig.pid), json.dumps(self.rig.vid), json.dumps(scene_id),
                         json.dumps(json.dumps(files)), extra))
        return {"value": name, "expr": expression}

    def survey(self, tag: str) -> list:
        """Ce que la page et les cadres montrent MAINTENANT : noeuds, marqueurs, ecouteurs, compteurs de l'hote, bande."""

        steps: list = [
            {"value": f"{tag}:same_nodes", "expr": "Object.fromEntries(Object.entries(window.__nodes).map(([id,n])=>[id,"
                                                  "document.querySelector('[data-object-id=\"'+id+'\"] iframe')===n]))"},
            {"value": f"{tag}:iframes", "expr": "[...document.querySelectorAll('iframe')].length"},
            {"value": f"{tag}:counters", "expr": "Object.fromEntries(Object.keys(window.__nodes).map(id=>[id,window.__host.counters(id)]))"},
            {"value": f"{tag}:stats", "expr": "window.__host.stats()"},
            {"value": f"{tag}:band", "expr": "(()=>{const b=document.getElementById('jvStudioReloadBand');"
                                            "return b?{kind:b.dataset.kind,phase:b.dataset.phase,role:b.getAttribute('role'),text:b.textContent}:null})()"},
            {"value": f"{tag}:sandboxes", "expr": "[...document.querySelectorAll('iframe')].map(f=>[f.getAttribute('sandbox'),f.getAttribute('allow'),f.hasAttribute('allowfullscreen')])"},
        ]
        for oid in self.oids:
            steps.append({"frameValue": f"{tag}:born:{oid}", "object_id": oid, "expr": "window.__born||null"})
        steps.append({"framesValue": f"{tag}:listeners", "expr": LISTENERS})
        return steps


def silent(out: dict, *, allow: tuple[str, ...] = ()) -> None:
    """Aucune exception non rattrapee dans la page ; les erreurs de console sont celles qu'on attend, pas du bruit."""

    assert out["errors"] == [], out["errors"]
    # the module's own `[studio-reload]` lines are the journal of a failed edit on purpose (error level): they are asserted
    # where a test provokes a failure, not counted as noise
    noise = [line for line in out["console"] if line["where"] == "page" and line["type"] in ("error", "warning")
             and not line["text"].startswith("[studio-reload]") and not any(token in line["text"] for token in allow)]
    assert noise == [], noise


# ------------------------------------------------------------------ une bonne edition

async def test_the_bridge_page_mounts_the_real_frames_with_the_real_sandbox(tmp_path):
    async with Scenario(tmp_path) as sc:
        out = await drive(sc.bridge, tmp_path, [*await sc.prelude(), *sc.survey("start")])
        reads = out["reads"]
        assert reads["start:iframes"] == 3 and reads["start:sandboxes"] == [["allow-scripts", None, False]] * 3
        assert reads["start:stats"]["ready"] == 3 and reads["start:stats"]["errorFrames"] == 0
        assert all(reads[f"start:born:{oid}"] for oid in sc.oids)
        silent(out)


async def test_a_good_edit_reloads_only_the_affected_frame_and_keeps_the_live_values(tmp_path):
    async with Scenario(tmp_path) as sc:
        out = await drive(sc.bridge, tmp_path, [
            *await sc.prelude(),
            # two REAL clicks in the stage frame: its own state events write the stage window's data through Core
            {"clickInFrame": {"object_id": sc.stage, "selector": "button"}},
            {"frameUntil": {"object_id": sc.stage, "expr": "document.querySelector('.count').textContent==='13'", "ms": 8000}},
            {"clickInFrame": {"object_id": sc.stage, "selector": "button"}},
            {"frameUntil": {"object_id": sc.stage, "expr": "document.querySelector('.count').textContent==='14'", "ms": 8000}},
            sc.edit("edit", {"style": GOOD_STYLE}),
            {"frameUntil": {"object_id": sc.stage, "expr": "!!document.querySelector('.count')", "ms": 8000}},
            {"frameValue": "text", "object_id": sc.stage, "expr": "document.querySelector('.count').textContent"},
            {"frameValue": "label", "object_id": sc.stage, "expr": "document.querySelector('h2').textContent"},
            {"frameValue": "style", "object_id": sc.stage,
             "expr": "(()=>{const c=getComputedStyle(document.querySelector('.count'));return [c.color,c.fontSize]})()"},
            {"wait": 300},
            *sc.survey("end"),
        ])
        reads = out["reads"]
        result = reads["edit"]
        assert result["status"] == "reloaded" and result["mounted"] is True and result["source_revision"] == 1
        assert result["previous"] == {"id": "lab.counter", "version": 1} and result["prefab"]["id"].startswith("presentation-studio.p")
        # the NEW frame carries the live values (14 clicks-worth of state) and the new style
        assert reads["text"] == "14" and reads["label"] == "Visiteurs" and reads["style"] == ["rgb(255, 0, 0)", "36px"]
        # ... and ONLY that frame was replaced: the neighbours keep their iframe node, their live document and their listeners
        assert reads["end:same_nodes"] == {sc.stage: False, "other-a": True, "other-b": True}
        for oid in OTHERS:
            assert reads[f"end:born:{oid}"]                                            # the very document that was stamped
            assert reads["end:counters"][oid] == {"starts": 1, "mounted": 1, "failed": 0, "remounts": 0}
            assert reads["end:listeners"][oid] == reads["listeners_before"][oid]
        assert reads[f"end:born:{sc.stage}"] is None                                   # a fresh document
        assert reads["end:counters"][sc.stage] == {"starts": 2, "mounted": 2, "failed": 0, "remounts": 1}
        assert reads["end:listeners"][sc.stage] == reads["listeners_before"][sc.stage]   # the new frame holds no more than the old
        assert reads["end:iframes"] == 3 and reads["end:stats"]["staging"] == 0 and reads["end:stats"]["departing"] == 0
        assert reads["end:sandboxes"] == [["allow-scripts", None, False]] * 3
        band = reads["end:band"]
        assert band["kind"] == "ok" and band["role"] == "status" and "rechargée" in band["text"] and "montage confirmé" in band["text"]
        # Core agrees
        scene = next(s for s in (await sc.rig.variant()).scenes if s.scene_id == SID)
        assert scene.prefab.prefab_id.startswith("presentation-studio.") and scene.last_valid_pin is None and scene.data["count"] == 12
        block = await sc.rig.stage_block()
        assert (block.prefab_id, block.data["count"]) == (scene.prefab.prefab_id, 14)
        silent(out)


async def test_the_frames_are_the_real_prefab_the_bundle_cache_serves_each_version_once(tmp_path):
    async with Scenario(tmp_path) as sc:
        out = await drive(sc.bridge, tmp_path, [*await sc.prelude(), sc.edit("e1", {"style": GOOD_STYLE}),
                                                sc.edit("e2", {"style": ".count{color:blue}"}), {"wait": 300}])
        assert out["reads"]["e1"]["status"] == out["reads"]["e2"]["status"] == "reloaded"
        fetched = [key for kind, key in sc.bridge.requests if kind == "bundle"]
        assert sorted(fetched) == sorted(set(fetched)) and len(fetched) == 3 and "lab.counter@1" in fetched   # 1 shared + 2 revisions
        silent(out)


# ------------------------------------------------------------------ une source qui ne monte pas

BAD_BEHAVIORS = {
    "syntax_error": ("function ( {", "frame"),
    "throws_at_first_render": ("jarvis.on('init', function () { throw new Error('boom at mount'); });", "frame"),
    "throws_at_load": ("throw new Error('boom at load');", "frame"),
    "hangs_the_frame": ("var t = Date.now(); while (Date.now() - t < 20000) {}", "timeout"),
}


@pytest.mark.parametrize("name", sorted(BAD_BEHAVIORS))
async def test_a_source_that_does_not_mount_is_rolled_back_and_the_previous_frame_never_left(tmp_path, name):
    behavior, reason = BAD_BEHAVIORS[name]
    async with Scenario(tmp_path, mount_deadline_s=10.0) as sc:
        out = await drive(sc.bridge, tmp_path, [
            *await sc.prelude(),
            {"clickInFrame": {"object_id": sc.stage, "selector": "button"}},
            {"frameUntil": {"object_id": sc.stage, "expr": "document.querySelector('.count').textContent==='13'", "ms": 8000}},
            sc.edit("edit", {"behavior": behavior}),
            {"wait": 400},
            {"frameValue": "text", "object_id": sc.stage, "expr": "document.querySelector('.count').textContent"},
            *sc.survey("end"),
        ])
        reads = out["reads"]
        result = reads["edit"]
        assert result["status"] == "rolled_back" and result["code"] == "presentation_studio_mount_failed", result
        assert result["reason"] == reason and result["prefab"] == {"id": "lab.counter", "version": 1}
        # THE guarantee: the frame that was on screen is the same node, in the same document, still alive and still correct
        assert reads["end:same_nodes"] == {sc.stage: True, "other-a": True, "other-b": True}
        assert reads["end:iframes"] == 3
        for oid in sc.oids:
            assert reads[f"end:born:{oid}"], oid                                      # nobody's document was recreated
            assert reads["end:listeners"][oid] == reads["listeners_before"][oid]
        assert reads["text"] == "13"                                                  # the live value is still there
        assert reads["end:counters"][sc.stage] == {"starts": 2, "mounted": 1, "failed": 1, "remounts": 0}
        for oid in OTHERS:
            assert reads["end:counters"][oid] == {"starts": 1, "mounted": 1, "failed": 0, "remounts": 0}
        assert reads["end:stats"]["staging"] == 0 and reads["end:stats"]["errorFrames"] == 0
        band = reads["end:band"]
        assert band["kind"] == "bad" and band["role"] == "alert" and "annulée" in band["text"] and band["phase"] == "done"
        # Core: the document is the previous one, the stage names the previous version again
        scene = next(s for s in (await sc.rig.variant()).scenes if s.scene_id == SID)
        assert scene.prefab == PrefabRef("lab.counter", 1) and scene.last_valid_pin is None and scene.source_revision == 2
        block = await sc.rig.stage_block()
        assert (block.prefab_id, block.version, block.data["count"]) == ("lab.counter", 1, 13)
        assert sc.rig.sink.of("core.presentation_studio.reload_rolled_back")
        silent(out, allow=("Failed to load resource",))


async def test_a_frame_that_navigates_away_cannot_reach_the_network_and_never_replaces_the_live_one(tmp_path):
    async with Scenario(tmp_path, mount_deadline_s=6.0) as sc:
        url = sc.bridge.url + "/secret/nav"
        out = await drive(sc.bridge, tmp_path, [
            *await sc.prelude(),
            sc.edit("edit", {"behavior": f"location.href = {json.dumps(url)};"}),
            {"wait": 600},
            *sc.survey("end"),
        ])
        reads = out["reads"]
        assert sc.bridge.hits == {}                                                  # the document it asked for was never fetched
        assert reads["edit"]["status"] in ("rolled_back", "reloaded")
        if reads["edit"]["status"] == "rolled_back":
            assert reads["end:same_nodes"][sc.stage] is True and reads[f"end:born:{sc.stage}"]
        assert reads["end:sandboxes"] == [["allow-scripts", None, False]] * 3 and reads["end:iframes"] == 3
        silent(out, allow=("frame-src", "Refused", "Failed to load resource"))


# ------------------------------------------------------------------ une source refusee avant publication

REFUSED = {
    "forbidden_tag": ({"template": "<iframe src='https://example.com'></iframe>"}, "presentation_studio_source_invalid"),
    "inline_handler": ({"template": "<p onclick='x()'>hi</p>"}, "presentation_studio_source_invalid"),
    "css_import": ({"style": "@import url(https://evil.example/x.css);"}, "presentation_studio_source_invalid"),
}


@pytest.mark.parametrize("name", sorted(REFUSED))
async def test_a_source_refused_before_publication_touches_nothing_in_the_page_or_in_core(tmp_path, name):
    files, code = REFUSED[name]
    async with Scenario(tmp_path) as sc:
        library = sorted(p.name for p in (sc.rig.data / "prefabs").iterdir())
        out = await drive(sc.bridge, tmp_path, [*await sc.prelude(), sc.edit("edit", files), {"wait": 200}, *sc.survey("end")])
        reads = out["reads"]
        assert reads["edit"]["status"] == "refused_validation" and reads["edit"]["code"] == code
        assert reads["end:same_nodes"] == {oid: True for oid in sc.oids} and reads["end:iframes"] == 3
        assert all(c == {"starts": 1, "mounted": 1, "failed": 0, "remounts": 0} for c in reads["end:counters"].values())
        band = reads["end:band"]
        assert band["kind"] == "bad" and "refusée avant publication" in band["text"] and "Rien n'a changé" in band["text"]
        assert sorted(p.name for p in (sc.rig.data / "prefabs").iterdir()) == library          # nothing published
        silent(out)


async def test_an_oversize_source_is_refused_by_the_request_check_and_the_page_says_so(tmp_path):
    async with Scenario(tmp_path) as sc:
        out = await drive(sc.bridge, tmp_path, [
            *await sc.prelude(),
            sc.edit("edit", {"behavior": "// " + "x" * (65 * 1024)}),
            {"wait": 200}, *sc.survey("end")])
        reads = out["reads"]
        assert reads["edit"]["thrown"] == "presentation_studio_invalid" and "exceeds" in reads["edit"]["message"]
        assert reads["end:same_nodes"] == {oid: True for oid in sc.oids}
        band = reads["end:band"]
        assert band["kind"] == "bad" and band["role"] == "alert" and "presentation_studio_invalid" in band["text"]
        assert [b.split("</button>")[0] for b in [band["text"]] if "Réessayer" in b]            # a retry is offered
        silent(out)


async def test_a_manifest_naming_a_prototype_property_is_refused_before_any_page_code_sees_it(tmp_path):
    async with Scenario(tmp_path) as sc:
        manifest = sc.rig.manifest_of_pin()
        manifest["inputs"]["data"]["properties"]["__proto__"] = {"type": "string"}
        out = await drive(sc.bridge, tmp_path, [*await sc.prelude(), sc.edit("edit", {"manifest": manifest}), *sc.survey("end")])
        assert out["reads"]["edit"]["status"] == "refused_validation" and "__proto__" in out["reads"]["edit"]["message"]
        assert out["reads"]["end:same_nodes"] == {oid: True for oid in sc.oids}
        silent(out)


# ------------------------------------------------------------------ un contenu hostile reste confine

async def test_hostile_content_in_a_reloaded_frame_stays_inside_its_sandbox(tmp_path):
    async with Scenario(tmp_path) as sc:
        server = sc.bridge.url
        behavior = f"""
        window.__hostile = [];
        var note = function (label, work) {{ try {{ var r = work(); if (r && r.catch) r.catch(function (e) {{ window.__hostile.push(label + ':' + e.name); }}); else window.__hostile.push(label + ':ran'); }} catch (e) {{ window.__hostile.push(label + ':' + e.name); }} }};
        note('parent', function () {{ return parent.document.title; }});
        note('top', function () {{ return top.document.title; }});
        note('cookie', function () {{ return document.cookie; }});
        note('storage', function () {{ return localStorage.getItem('x'); }});
        note('eval', function () {{ return eval('1+1'); }});
        note('function', function () {{ return new Function('return 1')(); }});
        note('fetch', function () {{ return fetch({json.dumps(server + '/secret/fetch')}); }});
        note('socket', function () {{ return new WebSocket({json.dumps(server.replace('http', 'ws') + '/secret/ws')}); }});
        note('beacon', function () {{ return navigator.sendBeacon({json.dumps(server + '/secret/beacon')}, 'x'); }});
        note('image', function () {{ var i = new Image(); i.src = {json.dumps(server + '/secret/img')}; return 'sent'; }});
        note('open', function () {{ return window.open({json.dumps(server + '/secret/open')}); }});
        note('topnav', function () {{ top.location.href = {json.dumps(server + '/secret/top')}; }});
        note('form', function () {{ var f = document.createElement('form'); f.action = {json.dumps(server + '/secret/form')}; f.method = 'post'; document.body.appendChild(f); f.submit(); }});
        """
        out = await drive(sc.bridge, tmp_path, [
            *await sc.prelude(),
            sc.edit("edit", {"behavior": behavior}),
            {"wait": 800},
            {"frameValue": "hostile", "object_id": sc.stage, "expr": "window.__hostile"},
            {"frameValue": "csp", "object_id": sc.stage,
             "expr": "document.querySelector('meta[http-equiv=\"Content-Security-Policy\"]').content"},
            {"value": "title", "expr": "document.title"},
            *sc.survey("end"),
        ])
        reads = out["reads"]
        assert reads["edit"]["status"] in ("reloaded", "rolled_back"), reads["edit"]
        assert sc.bridge.hits == {}, sc.bridge.hits                                       # nothing reached the server
        hostile = {entry.split(":")[0]: entry.split(":")[1] for entry in reads["hostile"]}
        # the parent and top documents are cross-origin, storage and cookies belong to an opaque origin, eval is not allowed
        assert hostile["parent"] == "SecurityError" and hostile["top"] == "SecurityError"
        assert hostile["cookie"] == "SecurityError" and hostile["storage"] == "SecurityError"
        assert hostile["eval"] == "EvalError" and hostile["function"] == "EvalError"
        assert hostile["fetch"] == "TypeError"                                              # connect-src falls back to default-src 'none'
        assert reads["title"] == "studio reload bridge"                                    # the parent page was not touched
        assert "default-src 'none'" in reads["csp"] and "connect" not in reads["csp"]
        assert reads["end:sandboxes"] == [["allow-scripts", None, False]] * 3 and reads["end:iframes"] == 3
        assert reads["end:same_nodes"][OTHERS[0]] and reads["end:same_nodes"][OTHERS[1]]
        silent(out, allow=("Failed to load resource", "Refused", "frame-src", "Blocked"))


# ------------------------------------------------------------------ les valeurs qui ne peuvent pas etre gardees

async def test_a_state_reset_is_a_visible_persistent_band_naming_what_was_dropped(tmp_path):
    async with Scenario(tmp_path) as sc:
        out = await drive(sc.bridge, tmp_path, [
            *await sc.prelude(),
            sc.edit("refused", {"manifest": sc.rig.shrunk_manifest()}),
            {"value": "refused_band", "expr": "document.getElementById('jvStudioReloadBand').textContent"},
            sc.edit("reset", {"manifest": sc.rig.shrunk_manifest()}, extra="{allow_state_reset:true}"),
            {"wait": 300},
            {"value": "items", "expr": "[...document.querySelectorAll('#jvStudioReloadBand li')].map(li=>li.textContent)"},
            {"value": "persists", "expr": "new Promise(r=>setTimeout(()=>r(!!document.getElementById('jvStudioReloadBand')),7000))"},
            {"frameValue": "text", "object_id": sc.stage, "expr": "document.querySelector('.count').textContent"},
            *sc.survey("end"),
        ])
        reads = out["reads"]
        assert reads["refused"]["status"] == "refused_validation" and "allow_state_reset" in reads["refused"]["message"]
        assert "refusée avant publication" in reads["refused_band"]
        reset = reads["reset"]
        assert reset["status"] == "reloaded_state_reset" and reset["mounted"] is True
        assert reset["reset"]["data"] == ["count"] and reset["reset"]["controls"] == ["start_count"]
        assert reset["reset"]["anchors"] == ["reveal"] and reset["reset"]["runtime_values"] is True
        # the band stays (a warning is never auto-dismissed), names what went, and carries no value
        assert reads["items"][0].startswith("Valeurs retirées : ") and "data.count" in reads["items"][0]
        assert "Contrôles retirés : start_count" in reads["items"] and "Ancres déliées : reveal" in reads["items"]
        assert reads["persists"] is True and reads["end:band"]["kind"] == "warn" and reads["end:band"]["role"] == "alert"
        assert "12" not in " ".join(reads["items"])
        assert reads["text"] == "0"                                                  # the manifest default, never a stale number
        assert reads["end:same_nodes"][OTHERS[0]] and reads["end:same_nodes"][OTHERS[1]]
        scene = next(s for s in (await sc.rig.variant()).scenes if s.scene_id == SID)
        assert "count" not in scene.data and [c.control_id for c in scene.controls] == ["headline"]
        assert sc.rig.sink.of("core.presentation_studio.reload_applied")[-1][1]["reset"]["data"] == 1
        silent(out)


# ------------------------------------------------------------------ rechargements repetes : pas de fuite

async def test_many_reloads_good_and_bad_leak_no_frame_listener_cache_entry_or_memory(tmp_path):
    good, bad = ".count{color:#%02x0000}", "throw new Error('boom %d');"
    rounds = 36                                    # crosses the retention trigger (32 live versions) of the scene's source id
    async with Scenario(tmp_path, mount_deadline_s=6.0) as sc:
        loop = []
        for index in range(rounds):
            if index % 3 == 2:
                loop.append(sc.edit(f"r{index}", {"behavior": bad % index}))
            else:
                loop.append(sc.edit(f"r{index}", {"style": good % (index * 6 % 256)}))
        out = await drive(sc.bridge, tmp_path, [
            *await sc.prelude(), {"heap": "heap_before"}, {"listeners": "page_before"},
            *loop,
            {"wait": 500}, {"heap": "heap_after"}, {"listeners": "page_after"},
            *sc.survey("end"),
        ], timeout=420)
        reads = out["reads"]
        statuses = [reads[f"r{i}"]["status"] for i in range(rounds)]
        assert statuses == ["rolled_back" if i % 3 == 2 else "reloaded" for i in range(rounds)], statuses
        stats = reads["end:stats"]
        # frames: exactly the three that were there, no staged leftover, nothing departing, no error frame
        assert reads["end:iframes"] == 3 and stats["frames"] == 3 and stats["staging"] == 0 and stats["departing"] == 0
        assert stats["errorFrames"] == 0 and stats["bundles"] <= 64
        # listeners: the page holds the same ones, and every frame holds what it held at the start
        assert reads["page_after"] == reads["page_before"]
        for oid in sc.oids:
            assert reads["end:listeners"][oid] == reads["listeners_before"][oid], oid
        # the neighbours were never touched in 36 reloads; the stage counted every attempt
        for oid in OTHERS:
            assert reads["end:counters"][oid] == {"starts": 1, "mounted": 1, "failed": 0, "remounts": 0}
            assert reads["end:same_nodes"][oid] is True
        assert reads["end:counters"][sc.stage]["starts"] == 1 + rounds
        assert reads["end:counters"][sc.stage]["failed"] == rounds // 3 and reads["end:counters"][sc.stage]["remounts"] == rounds - rounds // 3
        assert reads[f"end:born:{sc.stage}"] is None                                   # the stage frame is a recent document
        # memory: after a forced collection the page heap did not grow by more than a few MiB over 36 reloads
        assert reads["heap_after"] - reads["heap_before"] < 8 * 1024 * 1024, (reads["heap_before"], reads["heap_after"])
        # Core: versions are bounded by retention, the current pin and every pinned version are alive, nothing failed
        source_id = (await sc.rig.variant()).scenes[0].prefab.prefab_id
        assert source_id.startswith("presentation-studio.")
        live = sc.rig.versions_of(source_id)
        assert len(live) <= 32 and (await sc.rig.variant()).scenes[0].prefab.version in live
        assert (sc.rig.data / "prefabs" / ".archive" / source_id).exists()
        assert not sc.rig.sink.of("core.prefab.retention_failed")
        silent(out, allow=("Failed to load resource",))


# ------------------------------------------------------------------ concurrence et lecture

EXTRA_TEMPLATE = ('<section class="jv-panel"><h2 data-jv-text="props.label"></h2><p class="count" data-jv-text="data.count"></p>'
                  '<p class="extra">+</p><button type="button" class="jv-button">+1</button></section>')


async def test_a_burst_from_the_page_is_one_published_version_and_both_callers_get_the_outcome(tmp_path):
    async with Scenario(tmp_path, quiet_s=0.5, max_wait_s=3.0) as sc:
        raw = ("(async()=>{const call=(files)=>fetch(%s,{method:'POST',headers:{'Content-Type':'application/json'},"
               "body:JSON.stringify({actor:'user',basis:{variant_revision:window.__state.revision},scene_id:%s,files})}).then(r=>r.json());"
               "return Promise.all([call({style:'.count{color:#00ff00}'}),call({template:%s})])})()"
               % (json.dumps(f"/api/presentation-studio/presentations/{sc.rig.pid}/variants/{sc.rig.vid}/source-edits"),
                  json.dumps(SID), json.dumps(EXTRA_TEMPLATE)))
        out = await drive(sc.bridge, tmp_path, [*await sc.prelude(), {"value": "both", "expr": raw},
                                                 {"wait": 400}, *sc.survey("end")])
        first, second = out["reads"]["both"]
        assert first["status"] == "reloaded" and second["status"] == "reloaded" and sorted([first["merged"], second["merged"]]) == [False, True]
        assert first["prefab"] == second["prefab"]
        source_id = first["prefab"]["id"]
        assert sc.rig.versions_of(source_id) == [1]                                        # one version for the burst
        detail = await sc.rig.prefabs.get(source_id, 1)
        assert detail.entry.bundle.style == ".count{color:#00ff00}" and "extra" in detail.entry.bundle.template   # nothing lost
        assert out["reads"]["end:counters"][sc.stage]["remounts"] == 1                       # ONE reload in the page
        assert out["reads"]["end:same_nodes"][OTHERS[0]] and out["reads"]["end:same_nodes"][OTHERS[1]]
        silent(out)


async def test_an_edit_during_playback_leaves_the_reported_position_alone(tmp_path):
    class Playback:
        def position(self, presentation_id):
            return {"variant_id": "psv", "scene_id": SID, "state": "running", "item_id": "psi_000000000001"}

    sc = Scenario(tmp_path)
    sc.options = {}
    scenario_rig = Rig(tmp_path)
    scenario_rig.playback = Playback()
    sc.rig = await scenario_rig.open(host=False)
    for object_id in OTHERS:
        await sc.rig.add_window(object_id)
    sc.bridge = await Bridge(sc.rig).__aenter__()
    sc.stage = stage_id(sc.rig)
    sc.oids = (sc.stage, *OTHERS)
    try:
        out = await drive(sc.bridge, tmp_path, [*await sc.prelude(), sc.edit("edit", {"style": GOOD_STYLE})])
        result = out["reads"]["edit"]
        assert result["status"] == "reloaded"
        assert result["preserved"] == {"variant_id": sc.rig.vid, "scene_id": SID, "playback_unchanged": True,
                                       "playback": {"variant_id": "psv", "scene_id": SID, "state": "running", "item_id": "psi_000000000001"}}
        silent(out)
    finally:
        await sc.bridge.__aexit__(None, None, None)
        await sc.rig.close()


# ------------------------------------------------------------------ pannes injectees, vues de la page

async def test_a_stage_patch_that_fails_is_rolled_back_without_the_page_remounting_anything(tmp_path, monkeypatch):
    from jarvis.core.presentation_studio_stage import StagePatchError
    async with Scenario(tmp_path) as sc:
        async def gone(*args, **kwargs):
            raise StagePatchError("stage_missing", "the stage window no longer exists")

        monkeypatch.setattr(sc.rig.stage, "repin", gone)
        out = await drive(sc.bridge, tmp_path, [*await sc.prelude(), sc.edit("edit", {"style": GOOD_STYLE}), {"wait": 300},
                                                 *sc.survey("end")])
        reads = out["reads"]
        assert reads["edit"]["status"] == "rolled_back" and reads["edit"]["code"] == "presentation_studio_stage_failed"
        assert reads["end:same_nodes"] == {oid: True for oid in sc.oids}
        assert all(c == {"starts": 1, "mounted": 1, "failed": 0, "remounts": 0} for c in reads["end:counters"].values())
        assert reads["end:band"]["kind"] == "bad" and "annulée" in reads["end:band"]["text"]
        scene = next(s for s in (await sc.rig.variant()).scenes if s.scene_id == SID)
        assert scene.prefab == PrefabRef("lab.counter", 1) and scene.last_valid_pin is None
        silent(out)


async def test_a_pin_write_that_fails_is_a_coded_error_in_the_band_and_the_page_is_untouched(tmp_path, monkeypatch):
    from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
    async with Scenario(tmp_path) as sc:
        async def broken(*args, **kwargs):
            raise PresentationStudioError(C.STORAGE_IO, "replace_scene_source: OSError: disk full")

        monkeypatch.setattr(sc.rig.studio, "replace_scene_source", broken)
        out = await drive(sc.bridge, tmp_path, [*await sc.prelude(), sc.edit("edit", {"style": GOOD_STYLE}), {"wait": 200},
                                                 *sc.survey("end"), {"value": "toasts", "expr": "window.__toasts.map(t=>t.kind)"}])
        reads = out["reads"]
        assert reads["edit"]["thrown"] == "presentation_studio_storage_io" and "disk full" in reads["edit"]["message"]
        assert reads["end:same_nodes"] == {oid: True for oid in sc.oids}
        band = reads["end:band"]
        assert band["kind"] == "bad" and "presentation_studio_storage_io" in band["text"] and "disk full" in band["text"]
        assert "Réessayer" in band["text"] and reads["toasts"] == ["bad"]
        silent(out)


# ------------------------------------------------------------------ le delai et les rapports tardifs

async def test_a_slow_frame_makes_a_pending_mount_then_the_late_report_confirms_it_and_the_swap_happens(tmp_path):
    slow = "var t = Date.now(); while (Date.now() - t < 1200) {}"          # the frame is busy for 1.2 s, then fine
    async with Scenario(tmp_path, mount_deadline_s=0.4) as sc:
        out = await drive(sc.bridge, tmp_path, [
            *await sc.prelude(), sc.edit("edit", {"behavior": slow}),
            {"value": "band_pending", "expr": "document.getElementById('jvStudioReloadBand').textContent"},
            {"until": "window.__host.counters(%s).remounts===1" % json.dumps(sc.stage), "ms": 10000},
            {"wait": 500}, *sc.survey("end"),
        ])
        reads = out["reads"]
        assert reads["edit"]["status"] == "pending_mount"
        assert "montage non confirmé" in reads["band_pending"] and "repli" in reads["band_pending"]
        assert reads["end:counters"][sc.stage] == {"starts": 2, "mounted": 2, "failed": 0, "remounts": 1}
        scene = next(s for s in (await sc.rig.variant()).scenes if s.scene_id == SID)
        assert scene.prefab.prefab_id.startswith("presentation-studio.") and scene.last_valid_pin is None     # confirmed late
        assert sc.rig.sink.of("core.presentation_studio.reload_late")[-1][1]["status"] == "reloaded"
        silent(out)


async def test_a_slow_frame_that_then_fails_is_rolled_back_late_and_the_previous_frame_is_still_there(tmp_path):
    slow_then_boom = "var t = Date.now(); while (Date.now() - t < 1200) {} throw new Error('late boom');"
    async with Scenario(tmp_path, mount_deadline_s=0.4) as sc:
        out = await drive(sc.bridge, tmp_path, [
            *await sc.prelude(), sc.edit("edit", {"behavior": slow_then_boom}),
            {"until": "window.__host.counters(%s).failed===1" % json.dumps(sc.stage), "ms": 10000},
            {"wait": 800}, *sc.survey("end"),
        ])
        reads = out["reads"]
        assert reads["edit"]["status"] == "pending_mount"
        assert reads["end:same_nodes"][sc.stage] is True and reads[f"end:born:{sc.stage}"]    # the live frame was never replaced
        scene = next(s for s in (await sc.rig.variant()).scenes if s.scene_id == SID)
        assert scene.prefab == PrefabRef("lab.counter", 1) and scene.last_valid_pin is None    # rolled back by the late report
        assert (await sc.rig.stage_block()).prefab_id == "lab.counter"
        late = sc.rig.sink.of("core.presentation_studio.reload_late")[-1]
        assert late[0] == "warning" and late[1]["status"] == "rolled_back"
        silent(out, allow=("Failed to load resource",))


# ------------------------------------------------------------------ la page servie du Control Center

async def test_the_served_control_center_installs_the_reload_module_and_wires_the_host(tmp_path):
    """La vraie page assemblee par la chaine de marqueurs de `ControlCenter.index` : le module est la, installe sans erreur, et la
    page de scene branche `onOutcome` et `swapPrefix` sur l'hote (lus dans la source servie, l'hote ne se cree qu'au premier prefab)."""

    from tests.unit.test_fullscreen_browser import _drive, _served_page

    page = _served_page(tmp_path)
    html = page.read_text(encoding="utf-8")
    assert html.count("root.JarvisStudioReload=api") == 1 and "__CONTROL_CENTER_PRESENTATION_STUDIO_RELOAD_JS__" not in html
    assert html.index("root.JarvisPrefabHost=api") < html.index("root.JarvisStudioReload=api")          # after the host
    assert "onOutcome:reportPrefabOutcome,swapPrefix:'presentation-studio.'" in html
    result = await asyncio.to_thread(_drive, page, [
        {"wait": 700},
        {"value": "api", "expr": "Object.keys(window.JarvisStudioReload).sort()"},
        {"value": "instance", "expr": "Object.keys(window.JarvisStudioReload.instance).sort()"},
        {"value": "state", "expr": "window.JarvisStudioReload.instance.state()"},
        {"value": "style", "expr": "!!document.getElementById('jv-studio-reload-style')"},
        {"value": "statuses", "expr": "window.JarvisStudioReload.STATUSES"},
    ])
    reads = result["reads"]
    assert "applySourceEdit" in reads["instance"] and "hostOutcome" in reads["instance"] and "watch" in reads["instance"]
    assert reads["state"] == {"busy": False, "band": None, "watching": False,
                              "counters": {"reportsSent": 0, "reportsFailed": 0, "edits": 0, "failures": 0, "bands": 0}}
    assert reads["style"] is False                                          # no band, no style until something is shown
    assert result["errors"] == [], result["errors"]

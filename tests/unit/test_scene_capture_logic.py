"""Capture visuelle de la scène : logique de page exécutée avec node (handoff
jarvis-constellation-scene-runtime, Slice 09, partie 2).

`control_center_scene_capture.js` (commandes de dessin tirées du modèle de vue,
exécution sur un contexte 2D, réponse du meneur visible) et le crochet
`onCapture` de la boucle de `control_center_scene_page.js`, avec les fichiers
mêmes que la page reçoit, fausses minuteries et requêtes.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

import pytest

from jarvis.runtime.control_center import SCENE_CAPTURE_SCRIPT_MARKER, SCENE_PAGE_SCRIPT_MARKER, ControlCenter
from tests.unit.test_scene_renderer_logic import CLIENT_JS, LAYOUT_JS, PAGE_HTML, PAGE_JS, PRELUDE

CAPTURE_JS = PAGE_JS.with_name("control_center_scene_capture.js")

CAPTURE_PRELUDE = r"""
const C=require(PATHS.capture);
const ID='A'.repeat(32),ID2='B'.repeat(32);
const palette={background:'#010203',ink:'#eeeeee',muted:'#999999',edge:'#444444',surface:'#101010',warn:'#ffaa00',error:'#ff0000',
  done:'#00cc66',tones:{agent:'#ffffff',research:'#00ffff',doc:'#00ff00'}};
function fakeCtx(){
  const calls=[];
  const record=name=>(...args)=>calls.push([name,...args]);
  const ctx={calls};
  for(const name of ['setTransform','fillRect','beginPath','setLineDash','moveTo','lineTo','stroke','arc','fill','roundRect','rect','save','clip','restore','fillText'])ctx[name]=record(name);
  return ctx;
}
function responderHarness(flags){
  const logs=[],uploads=[],renders=[];
  let release=null;
  const deps={now:()=>T.now,isLeader:()=>flags.leader,isVisible:()=>flags.visible,isEnabled:()=>flags.enabled,
    render:request=>{renders.push(request.id);
      if(flags.throwRender)return Promise.reject(new Error('boom'));
      return new Promise(resolve=>{release=()=>resolve({blob:{size:1234},width:1280,height:720});if(!flags.holdRender)release()})},
    upload:(id,blob)=>{uploads.push(id);return Promise.resolve(flags.uploadStatus===undefined?{status:200,body:{}}:{status:flags.uploadStatus,body:{error:{code:'unknown_capture'}}})},
    log:(level,event,data)=>logs.push([level,event,data])};
  return {responder:C.createCaptureResponder(deps),logs,uploads,renders,release:()=>release&&release()};
}
"""


def run_node(tmp_path: Path, body: str) -> Any:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    paths = {"client": str(CLIENT_JS), "layout": str(LAYOUT_JS), "page": str(PAGE_JS), "capture": str(CAPTURE_JS)}
    index = len(list(tmp_path.glob("scene-capture-*.cjs")))
    script = tmp_path / f"scene-capture-{index}.cjs"
    script.write_text(
        f"const PATHS={json.dumps(paths)};\nconst D=null;\n" + PRELUDE + CAPTURE_PRELUDE
        + "(async()=>{\n" + body + "\n})().then(v=>console.log(JSON.stringify(v)),e=>{console.error(e&&e.stack||e);process.exit(1)});\n",
        encoding="utf-8",
    )
    result = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


# ------------------------------------------------------------------ dessin


def test_the_capture_is_scaled_down_to_1280x720_and_never_up(tmp_path):
    result = run_node(tmp_path, r"""
      return [C.captureSize(1920,1080),C.captureSize(1280,720),C.captureSize(800,600),C.captureSize(3000,500),C.captureSize(1000,2000),C.captureSize(0,0)];
    """)
    assert result[0] == {"width": 1280, "height": 720, "scale": pytest.approx(2 / 3)}
    assert result[1] == {"width": 1280, "height": 720, "scale": 1}
    assert result[2] == {"width": 800, "height": 600, "scale": 1}
    assert result[3]["width"] == 1280 and result[3]["height"] <= 720
    assert result[4]["height"] == 720 and result[4]["width"] == 360
    assert result[5] == {"width": 1, "height": 1, "scale": 1}


def test_draw_commands_follow_the_view_model_the_page_draws(tmp_path):
    result = run_node(tmp_path, r"""
      const s=state([
        obj('win-b','window',{origin:'brain',layer:240,category:'note',geometry:{x:-90,y:-30,w:64,h:40},
          payload:{title:'Fenêtre B chevauche A',summary:'ligne 1\nligne 2',items:[{label:'Doc',ref:'',url:'https://docs.python.org/3/'}]}}),
        obj('win-a','window',{origin:'brain',layer:220,category:'research',geometry:{x:-120,y:-50,w:64,h:40},payload:{title:'Fenêtre A',summary:'',items:[]}}),
        obj('tiny','window',{origin:'brain',layer:220,category:'note',geometry:{x:100,y:40,w:10,h:6},payload:{title:'trop petite',summary:'',items:[]}}),
        obj('star','agent',{geometry:{x:0,y:0,w:6,h:6},exec_state:'running'}),
        obj('hidden','window',{origin:'brain',visibility:'hidden',geometry:{x:0,y:0,w:64,h:40}}),
      ],[rel('e1','explains','win-a','star')]);
      const vp=L.viewport(1920,1080);
      const model=L.viewModel(s,L.resolveLayout(s),vp,{});
      const plan=C.drawCommands(model,vp,palette);
      const ops=plan.commands.map(c=>c.op);
      const texts=plan.commands.filter(c=>c.op==='text').map(c=>c.text);
      const rrects=plan.commands.filter(c=>c.op==='rrect');
      const boxes=Object.fromEntries(model.nodes.map(n=>[n.id,[n.box.left,n.box.top,n.box.width,n.box.height,n.shape]]));
      const ctx=fakeCtx();C.paint(ctx,plan);
      let unknown=null;try{C.paint(fakeCtx(),{commands:[{op:'nope'}]})}catch(e){unknown=e.message}
      return {size:[plan.width,plan.height,plan.scale],first:ops.slice(0,3),texts,
        rrects:rrects.map(r=>[r.x,r.y,r.w,r.h,r.stroke]),boxes,circles:plan.commands.filter(c=>c.op==='circle').length,
        painted:ctx.calls.map(c=>c[0]),fillTexts:ctx.calls.filter(c=>c[0]==='fillText').length,unknown,
        clipsBalanced:ops.filter(o=>o==='clip').length===ops.filter(o=>o==='restore').length};
    """)
    assert result["size"][:2] == [1280, 720]
    assert result["first"] == ["scale", "fill", "line"]  # arêtes sous les nœuds
    # Même boîte écran que le DOM (le modèle de vue), empilement par couche : A (220) avant B (240).
    rrects = result["rrects"]
    assert [r[:4] for r in rrects[:2]] == [result["boxes"]["win-a"][:4], result["boxes"]["win-b"][:4]]
    assert rrects[1][4] == "#00ff00"  # tonalité doc de la catégorie note
    # Fenêtre trop petite pour son texte : forme compacte, comme la page.
    assert result["boxes"]["tiny"][4] != "window"
    assert "hidden" not in result["boxes"]
    assert "Fenêtre B chevauche A" in result["texts"] and "ligne 1" in result["texts"]
    assert any(text.startswith("docs.python.org") for text in result["texts"])
    assert result["circles"] >= 2  # étoile et son anneau (en cours)
    assert result["painted"][0] == "setTransform" and result["fillTexts"] == len(result["texts"])
    assert result["unknown"] == "unknown draw op nope" and result["clipsBalanced"] is True


def test_text_is_fitted_to_its_box(tmp_path):
    result = run_node(tmp_path, r"""return [C.fit('abcdef',1000,12),C.fit('abcdefghijklmnop',40,12),C.fit('abc',5,12)]""")
    assert result[0] == "abcdef" and result[1].endswith("…") and len(result[1]) == 5 and result[2] == ""


# ------------------------------------------------------------------ réponse du meneur visible


def test_only_the_visible_leader_renders_and_uploads_once(tmp_path):
    result = run_node(tmp_path, r"""
      const leader=responderHarness({leader:true,visible:true,enabled:true});
      const first=await leader.responder.offer({id:ID,remaining_ms:5000});
      const again=await leader.responder.offer({id:ID,remaining_ms:4000});
      const follower=responderHarness({leader:false,visible:true,enabled:true});
      const hidden=responderHarness({leader:true,visible:false,enabled:true});
      const off=responderHarness({leader:true,visible:true,enabled:false});
      const declined=[await follower.responder.offer({id:ID,remaining_ms:5000}),await hidden.responder.offer({id:ID,remaining_ms:5000}),
        await off.responder.offer({id:ID,remaining_ms:5000})];
      const invalid=await leader.responder.offer({id:'short',remaining_ms:5000});
      return {first,again,uploads:leader.uploads,renders:leader.renders.length,declined,
        others:[follower,hidden,off].map(h=>h.renders.length+h.uploads.length),invalid,stats:leader.responder.stats(),
        events:leader.logs.map(l=>l[1])};
    """)
    assert result["first"] == "sent" and result["again"] == "duplicate"
    assert result["uploads"] == ["A" * 32] and result["renders"] == 1
    assert result["declined"] == ["declined", "declined", "declined"] and result["others"] == [0, 0, 0]
    assert result["invalid"] == "invalid"
    assert result["stats"]["sent"] == 1 and "scene.capture_sent" in result["events"]


def test_a_second_request_while_rendering_is_busy_and_a_deadline_blocks_the_upload(tmp_path):
    result = run_node(tmp_path, r"""
      const h=responderHarness({leader:true,visible:true,enabled:true,holdRender:true});
      const pending=h.responder.offer({id:ID,remaining_ms:300});
      await flush();
      const busy=await h.responder.offer({id:ID2,remaining_ms:5000});
      T.now+=400;h.release();
      const late=await pending;
      return {busy,late,uploads:h.uploads,events:h.logs.map(l=>l[1])};
    """)
    assert result == {"busy": "busy", "late": "expired", "uploads": [], "events": ["scene.capture_started", "scene.capture_expired"]}


def test_a_leader_hidden_mid_capture_abandons_and_the_new_leader_answers(tmp_path):
    result = run_node(tmp_path, r"""
      const flags={leader:true,visible:true,enabled:true,holdRender:true};
      const old=responderHarness(flags);
      const pending=old.responder.offer({id:ID,remaining_ms:5000});
      await flush();
      flags.visible=false;flags.leader=false;old.release();
      const abandoned=await pending;
      /* Core redonne la demande au nouveau meneur (une seconde plus tard). */
      const next=responderHarness({leader:true,visible:true,enabled:true});
      T.now+=1000;
      const answered=await next.responder.offer({id:ID,remaining_ms:4000});
      /* L'ancien onglet, redevenu meneur, peut encore la reprendre : l'identifiant n'est pas marqué traité. */
      flags.visible=true;flags.leader=true;flags.holdRender=false;
      const retaken=await old.responder.offer({id:ID,remaining_ms:3000});
      return {abandoned,answered,retaken,oldUploads:old.uploads.length,newUploads:next.uploads.length};
    """)
    assert result == {"abandoned": "abandoned", "answered": "sent", "retaken": "sent", "oldUploads": 1, "newUploads": 1}


def test_refused_or_failing_captures_are_reported_and_never_reject(tmp_path):
    result = run_node(tmp_path, r"""
      const refused=responderHarness({leader:true,visible:true,enabled:true,uploadStatus:404});
      const failing=responderHarness({leader:true,visible:true,enabled:true,throwRender:true});
      return {refused:await refused.responder.offer({id:ID,remaining_ms:5000}),refusedLog:refused.logs.at(-1),
        failed:await failing.responder.offer({id:ID,remaining_ms:5000}),failedLog:failing.logs.at(-1)[1]};
    """)
    assert result["refused"] == "refused" and result["refusedLog"][1] == "scene.capture_refused"
    assert result["refusedLog"][2]["status"] == 404 and result["refusedLog"][2]["code"] == "unknown_capture"
    assert result["failed"] == "failed" and result["failedLog"] == "scene.capture_failed"


# ------------------------------------------------------------------ boucle : remise au meneur, jamais diffusée


def test_the_loop_hands_capture_requests_to_the_leader_only_and_never_broadcasts_them(tmp_path):
    result = run_node(tmp_path, r"""
      function harness(role){
        const calls=[],captures=[],sent=[];
        const loop=P.createSceneLoop({client:S,
          request:(path,options)=>new Promise((resolve,reject)=>{
            const call={path,resolve,reject,aborted:false};
            options.signal.addEventListener('abort',()=>{call.aborted=true;const e=new Error('aborted');e.name='AbortError';reject(e)});
            calls.push(call);}),
          setTimeout:(fn,ms)=>T.set(fn,ms),clearTimeout:id=>T.clear(id),now:()=>T.now,random:()=>.5,
          createAbort:()=>new AbortController(),onUpdate:()=>{},log:()=>{},broadcast:m=>sent.push(m),onCapture:r=>captures.push(r)});
        loop.setRole(role);
        const answer=async body=>{const c=calls.filter(c=>!c.done&&!c.aborted)[0];c.done=true;c.resolve(body);await flush()};
        return {loop,calls,captures,sent,answer};
      }
      const request={id:ID,remaining_ms:4800};
      const lead=harness('leader');
      lead.loop.setEnabled(true);await flush();
      await lead.answer(snapshotBody([],0));
      await lead.answer({...patchesBody(0,[obj('claude:1','agent')]),capture_request:request});
      await lead.answer({...patchesBody(1,[]),revision:1,capture_request:request});
      const broadcastBodies=lead.sent.filter(m=>m.type==='patches').map(m=>Object.keys(m.body).includes('capture_request'));
      const follow=harness('follower');
      follow.loop.setEnabled(true);await flush();
      await follow.answer(snapshotBody([],0));
      follow.loop.receive({v:1,type:'tick',scene_id:'scene',epoch:'e1',revision:1,health:{level:'ok'}});await flush();
      await follow.answer({...patchesBody(0,[obj('claude:1','agent')]),capture_request:request});
      return {leaderCaptures:lead.captures,broadcastBodies,leaderPolls:lead.calls.length,followerCaptures:follow.captures.length,
        stripped:P.withoutCapture({a:1,capture_request:request}),same:(()=>{const b={a:1};return P.withoutCapture(b)===b})()};
    """)
    assert result["leaderCaptures"] == [{"id": "A" * 32, "remaining_ms": 4800}] * 2  # dédoublonné ensuite par le répondeur
    assert result["broadcastBodies"] == [False]
    assert result["followerCaptures"] == 0
    assert result["stripped"] == {"a": 1} and result["same"] is True


def test_the_page_receives_the_capture_script_before_the_page_block(tmp_path):
    html = PAGE_HTML.read_text(encoding="utf-8")
    assert html.index(SCENE_CAPTURE_SCRIPT_MARKER) < html.index(SCENE_PAGE_SCRIPT_MARKER)
    source = CAPTURE_JS.read_text(encoding="utf-8")
    assert "innerHTML" not in source and "fetch(" not in source and "document." not in source  # pur : ni DOM ni réseau
    page = PAGE_JS.read_text(encoding="utf-8")
    assert "leader.held&&leader.mode==='lock'" in page and "document.visibilityState!=='hidden'" in page
    del tmp_path
    assert ControlCenter  # le module qui insère le script s'importe


# ------------------------------------------------------------------ reprise QA M2 : formes dessinées partagées


def test_capture_draws_the_same_rectangles_as_the_page_for_compact_capsule_and_pinned_shapes(tmp_path):
    result = run_node(tmp_path, r"""
      const s=state([
        obj('win','window',{origin:'brain',category:'note',geometry:{x:-30,y:-20,w:64,h:40},payload:{title:'Fenêtre compacte',summary:'x',items:[]}}),
        obj('cap','artifact',{origin:'brain',category:'research',representation:'capsule',geometry:{x:-150,y:30,w:120,h:40},
          constraints:{placed_by:'brain',pinned_by_user:true},payload:{title:'Capsule dans une boîte de fenêtre',summary:'',items:[]}}),
        obj('star','agent',{geometry:{x:60,y:40,w:6,h:6},constraints:{placed_by:'resolver',pinned_by_user:true}}),
      ]);
      const out={};
      for(const [w,h] of [[390,844],[800,600],[1920,1080]]){
        const vp=L.viewport(w,h);
        const model=L.viewModel(s,L.resolveLayout(s),vp,{});
        const plan=C.drawCommands(model,vp,palette,L);
        const drawn=Object.fromEntries(model.nodes.map(n=>[n.id,{shape:n.shape,compact:n.compact,rect:L.drawnRect(n)}]));
        const shapes=Object.fromEntries(plan.commands.filter(c=>c.id).map(c=>[c.id,c]));
        const pins=plan.commands.filter(c=>c.marker==='pin');
        const texts=plan.commands.filter(c=>c.op==='text');
        out[`${w}x${h}`]={drawn,shapes,pins,scale:plan.scale,fonts:texts.map(t=>t.font),texts:texts.map(t=>[t.x,t.y,t.text])};
      }
      return out;
    """)
    for size, view in result.items():
        for object_id, drawn in view["drawn"].items():
            command = view["shapes"][object_id]
            rect = drawn["rect"]
            if drawn["shape"] == "point":
                assert command["op"] == "circle"
                assert (command["cx"], command["cy"]) == (rect["left"] + rect["width"] / 2, rect["top"] + rect["height"] / 2), size
            else:
                assert (command["x"], command["y"], command["w"], command["h"]) == (rect["left"], rect["top"], rect["width"], rect["height"]), (size, object_id)
        # Chaque repère d'épinglage est dans le rectangle dessiné de son objet.
        rects = [d["rect"] for d in view["drawn"].values()]
        for pin in view["pins"]:
            assert any(r["left"] <= pin["cx"] <= r["left"] + r["width"] and r["top"] <= pin["cy"] <= r["top"] + r["height"] for r in rects)
        # Texte compensé : taille de la page après réduction.
        for font in view["fonts"]:
            px = float(font.split("px")[0].split()[-1])
            assert px * view["scale"] >= 9 - 0.01, (size, font)
    small = result["390x844"]["drawn"]
    assert small["win"]["shape"] == "capsule" and small["win"]["compact"] is True
    assert small["win"]["rect"]["height"] == 28  # pilule collée en haut, pas la boîte entière
    big = result["1920x1080"]["drawn"]
    assert big["cap"]["shape"] == "capsule" and big["cap"]["rect"]["height"] >= 24


def test_capsule_category_and_title_never_overprint(tmp_path):
    result = run_node(tmp_path, r"""
      const out=[];
      for(const w of [60,90,140,300]){
        const node={id:'c',shape:'capsule',compact:false,kind:'artifact',category:'research-long-category',title:'Titre assez long pour couper',
          tone:'research',stack:1,box:{left:10,top:10,width:w,height:24},cx:10+w/2,cy:22,pinned:false,itemCount:0,items:[],summary:''};
        const plan=C.drawCommands({nodes:[node],edges:[]},{width:1280,height:720},palette,L);
        const texts=plan.commands.filter(c=>c.op==='text').map(t=>({x:t.x,text:t.text,font:t.font}));
        out.push({w,texts});
      }
      return out;
    """)
    for row in result:
        texts = row["texts"]
        if len(texts) == 2:
            category, title = texts
            px = float(category["font"].split("px")[0].split()[-1])
            assert title["x"] >= category["x"] + len(category["text"]) * px * 0.62, row
        for text in texts:
            assert text["x"] + len(text["text"]) * float(text["font"].split("px")[0].split()[-1]) * 0.62 <= 10 + row["w"] + 1, row


def test_the_page_places_nodes_with_the_shared_drawn_rect():
    page = PAGE_JS.read_text(encoding="utf-8")
    assert "const rect=L.drawnRect(node);" in page and "CAPSULE_MIN_HEIGHT=24" not in page
    capture = CAPTURE_JS.read_text(encoding="utf-8")
    assert "L.drawnRect(node)" in capture


# ------------------------------------------------------------------ reprise QA finale : encodage sans attendre d'image


def test_png_is_encoded_synchronously_from_the_canvas_and_checked(tmp_path):
    result = run_node(tmp_path, r"""
      const png=Buffer.from('89504e470d0a1a0a0000000d49484452','hex');
      const calls=[];
      const canvas={toDataURL:type=>{calls.push(type);return 'data:image/png;base64,'+png.toString('base64')}};
      const bytes=C.encodePng(canvas,value=>atob(value));
      const refused=[];
      for(const url of ['data:,','data:image/png;base64,','data:image/jpeg;base64,AAAA',null]){
        try{C.pngBytes(url,value=>atob(value));refused.push(false)}catch(_error){refused.push(true)}
      }
      return {calls,same:Buffer.from(bytes).equals(png),isUint8:bytes instanceof Uint8Array,refused};
    """)
    assert result == {"calls": ["image/png"], "same": True, "isUint8": True, "refused": [True, True, True, True]}


def test_the_page_never_waits_for_a_frame_to_encode_a_capture():
    page = PAGE_JS.read_text(encoding="utf-8")
    start = page.index("async function renderCapture(){")
    body = page[start:page.index("async function uploadCapture(", start)]
    assert "Capture.encodePng(canvas," in body
    for waiting in ("convertToBlob", "toBlob", "OffscreenCanvas", "requestAnimationFrame", "Worker"):
        assert waiting not in body


def test_the_capture_draws_the_finish_marker_like_the_page(tmp_path):
    """Anneau serré vert pour une fin normale, rouge pour un échec ; rien pour un signal."""

    result = run_node(tmp_path, r"""
      const base={id:'s',shape:'point',compact:false,kind:'agent',category:'agent',title:'Sous-agent',tone:'agent',stack:1,
        box:{left:100,top:100,width:16,height:16},cx:108,cy:108,pinned:false,itemCount:0,items:[],summary:'',
        signal:false,live:false,urgency:'none',restartUnknown:false};
      const out={};
      for(const [name,extra] of [['completed',{exec:'completed'}],['failed',{exec:'failed'}],
          ['running',{exec:'running'}],['cancelled',{exec:'cancelled'}],
          ['signal',{exec:'failed',signal:true,live:true,urgency:'high'}]]){
        const plan=C.drawCommands({nodes:[Object.assign({},base,extra)],edges:[]},{width:1280,height:720},palette,L);
        const rings=plan.commands.filter(c=>c.op==='circle'&&c.r>4).map(c=>[c.r,c.stroke]);
        out[name]=rings;
      }
      return out;
    """)

    assert result["completed"] == [[7.5, "#00cc66"]]
    assert result["failed"] == [[7.5, "#ff0000"]]
    # Inchangé : en cours (anneau large, teinte neutre) et fins sans marque.
    assert result["running"] == [[9, "#999999"]]
    assert result["cancelled"] == []
    # Un signal garde son anneau d'alerte, jamais la marque de fin.
    assert result["signal"] == [[9, "#ff0000"]]

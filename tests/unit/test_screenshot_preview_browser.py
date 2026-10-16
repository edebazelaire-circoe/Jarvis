"""Aperçu de capture d'écran et actions rapides, mesurés dans un vrai Chrome sur une vraie chaîne.

Handoff `jarvis-board-orbital-ui-workspace-rail`, Slice 05 ; architecture résolue §6 (D7). Contrat :
`docs/capture.md` › *Interface* › *Screenshot preview*, `docs/chat.md` › *Attachments*.

**Aucun double dans la page.** Un vrai Core (SQLite, payloads sous `tmp_path`, source de capture d'écran
**factice** qui rend un PNG 480×270 — jamais l'écran de ce poste) et un vrai `ControlCenter` (`CaptureStack`)
servent la page sur le bouclage ; `_screenshot_preview_browser.mjs` pilote de vrais événements d'entrée.
La capture part du vrai secteur de la roue (ou de `JarvisCaptureRail.screenshot()`, le même contrôleur) ;
chaque effet est confronté au registre de Core.

Captures dans `JARVIS_S05_EVIDENCE_DIR` quand la variable est posée. Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil

import pytest

from jarvis.adapters.fake_capture import FakeOneShotSource
from jarvis.domain.artifacts import ArtifactError, ArtifactKind, ArtifactQuery
from jarvis.domain.capture import CaptureChannel
from tests.fakes.capture_stack import CaptureStack
from tests.unit.test_interaction_mode_hud_browser import _chrome
from tests.unit.test_presentation_rail_e2e_browser import png

HARNESS = Path(__file__).parent / "_screenshot_preview_browser.mjs"
WIDTH, HEIGHT = 480, 270
IMAGE = png(WIDTH, HEIGHT)

ANCHOR = "#toolWheel .tw-anchor"
SHOT_WEDGE = "#toolWheel [data-tw-slot=screenshot] .tw-dot"
SHOWN = ("!document.getElementById('screenshotPreview').hidden"
         "&&document.querySelector('#screenshotPreview .sp-thumb').dataset.spImage==='ready'")
HIDDEN = "document.getElementById('screenshotPreview').hidden"
LIGHTBOX_OPEN = "document.getElementById('screenshotLightbox').classList.contains('open')"
TAKE = {"eval": "window.JarvisCaptureRail.screenshot()"}

#: Relevé de l'aperçu, de la visionneuse et des commandes voisines.
READ = """(()=>{
  const q=s=>document.querySelector(s);
  const box=el=>{if(!el)return null;const r=el.getBoundingClientRect();return r.width||r.height?{l:r.left,t:r.top,r:r.right,b:r.bottom}:null};
  const host=q('#screenshotPreview'),img=q('#screenshotPreview .sp-thumb img'),lb=q('#screenshotLightbox');
  const lbImg=lb&&lb.querySelector('img'),tab=lb&&lb.querySelector('a');
  const ae=document.activeElement;
  return {
    hidden:host.hidden,z:getComputedStyle(host).zIndex,box:box(host),control:host.hasAttribute('data-shell-control'),
    image:(q('#screenshotPreview .sp-thumb')||{dataset:{}}).dataset.spImage,
    natural:img?[img.naturalWidth,img.naturalHeight]:null,src:img?img.getAttribute('src'):null,alt:img?img.alt:null,
    title:(q('#screenshotPreview .sp-title')||{}).textContent,meta:(q('#screenshotPreview .sp-meta')||{}).textContent,
    placeholder:(q('#screenshotPreview .sp-ph')||{}).textContent,
    note:(n=>n?{hidden:n.hidden,text:n.textContent}:null)(q('#screenshotPreview .sp-note')),
    buttons:[...document.querySelectorAll('#screenshotPreview .sp-actions button')].map(b=>[b.dataset.spAct,b.textContent,b.getAttribute('aria-disabled')]),
    paused:!!(q('#screenshotPreview .sp-card')||{hasAttribute:()=>false}).hasAttribute('data-sp-paused'),
    focusInPreview:host.contains(ae),focus:ae?(ae.id||ae.dataset&&ae.dataset.spAct||ae.className||ae.tagName):null,
    lightbox:lb?{open:lb.classList.contains('open'),z:getComputedStyle(lb).zIndex,cls:lb.className,
      title:(lb.querySelector('h2')||{}).textContent,natural:lbImg?[lbImg.naturalWidth,lbImg.naturalHeight]:null,
      src:lbImg?lbImg.getAttribute('src'):null,href:tab?tab.getAttribute('href'):null,target:tab?tab.target:null,rel:tab?tab.rel:null,
      modal:(lb.querySelector('[role=dialog]')||{getAttribute:()=>null}).getAttribute('aria-modal'),
      focusInside:lb.contains(ae),focusText:ae?ae.textContent:null}:null,
    boxes:{modeBtn:box(q('#interactionModeButton')),chat:box(q('#chatTab')),anchor:box(q('#toolWheel .tw-anchor')),
      rec:q('#recIndicators').hidden?null:box(q('#recIndicators')),tray:q('#boardDropTray')&&!q('#boardDropTray').hidden?box(q('#boardDropTray')):null,
      scene:q('#sceneLayer>.sc-status')?box(q('#sceneLayer>.sc-status')):null,topbar:box(q('.topbar'))},
    view:window.JarvisScreenshotPreview.view(),
    inert:[...document.body.children].filter(el=>el.inert).map(el=>el.id||el.className),
    vw:innerWidth,vh:innerHeight,
  };
})()"""


def _shot(tmp_path: Path, name: str) -> dict:
    folder = Path(os.environ.get("JARVIS_S05_EVIDENCE_DIR") or tmp_path)
    folder.mkdir(parents=True, exist_ok=True)
    return {"shot": str(folder / f"2026-10-16-s05-{name}.png")}


def _until(js: str, ms: int = 8000, name: str | None = None) -> dict:
    return {"until": js, "ms": ms, "name": name or js}


def _read(name: str) -> dict:
    return {"value": name, "expr": READ}


def _overlap(a: dict | None, b: dict | None) -> bool:
    if not a or not b:
        return False
    return a["l"] < b["r"] and b["l"] < a["r"] and a["t"] < b["b"] and b["t"] < a["b"]


async def _drive(url: str, actions: list, *, width: int = 1440, height: int = 900, tmp_path: Path,
                 reduced_motion: bool = False, forced_colors: bool = False) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    plan = tmp_path / f"plan-{abs(hash(json.dumps(actions)))}.json"
    plan.write_text(json.dumps({"width": width, "height": height, "reducedMotion": reduced_motion,
                                "forcedColors": forced_colors, "actions": actions}), encoding="utf-8")
    process = await asyncio.create_subprocess_exec(node, str(HARNESS), url, _chrome(), "@" + str(plan),
                                                   stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await asyncio.wait_for(process.communicate(), 300)
    assert process.returncode == 0, stderr.decode("utf-8", "replace")
    out = json.loads(stdout.decode("utf-8"))
    if os.environ.get("JARVIS_S05_DUMP"):
        Path(os.environ["JARVIS_S05_DUMP"]).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    assert out["reads"]["ready"] is True, out
    assert "failed" not in out["reads"], out["reads"].get("failed")
    assert out["errors"] == [], out["errors"]
    for key, value in out["reads"].items():
        if key.startswith("until:"):
            assert value is True, (key, out["reads"], out["console"][-30:])
    return out


@pytest.fixture
async def stack(tmp_path):
    async with CaptureStack(tmp_path) as opened:
        opened.core.captures._sources._one_shot[CaptureChannel.SCREEN] = (
            lambda: FakeOneShotSource(data=IMAGE, width=WIDTH, height=HEIGHT))
        opened.url = f"http://127.0.0.1:{opened.cc_port}/"
        yield opened


async def _screenshots(stack) -> list:
    page = await stack.core.artifacts.query(ArtifactQuery(kinds=(ArtifactKind.SCREENSHOT,), limit=50))
    return list(page.items)


def _no_overlap_with_neighbours(read: dict) -> None:
    preview = read["box"]
    assert preview is not None
    for name, other in read["boxes"].items():
        if name == "topbar":
            assert preview["t"] >= other["b"], ("under the state line", read)
            continue
        assert not _overlap(preview, other), (name, preview, other, read["vw"], read["vh"])
    assert preview["l"] >= read["boxes"]["anchor"]["r"], "right of the wheel anchor"
    assert preview["b"] <= read["vh"] - 170, "above the bottom-left context zone, never bottom-centre"


# ------------------------------------------------------------------ critères d'acceptation


async def test_open_lightbox_and_tab(stack, tmp_path):
    out = await _drive(stack.url, [
        {"click": ANCHOR}, _until("window.JarvisToolWheel.isOpen()", 3000, "wheel"), {"click": SHOT_WEDGE},
        _until(SHOWN, 8000, "shown"), {"wait": 200}, _read("shown"), _shot(tmp_path, "preview-1440x900"),
        {"click": "#screenshotPreview [data-sp-act=open]"},
        _until(LIGHTBOX_OPEN + "&&document.querySelector('#screenshotLightbox img').complete", 5000, "lightbox"),
        {"wait": 150}, _read("lightbox"), _shot(tmp_path, "lightbox-1440x900"),
        {"value": "tab", "expr": "fetch(document.querySelector('#screenshotLightbox a').href).then(async r=>"
                                 "({status:r.status,type:r.headers.get('content-type'),bytes:(await r.arrayBuffer()).byteLength}))"},
        {"key": "Tab"}, {"value": "tab1", "expr": "document.activeElement.textContent"},
        {"key": "Tab"}, {"value": "tab2", "expr": "document.activeElement.textContent"},
        {"key": "Escape"}, _until("!" + LIGHTBOX_OPEN, 2000, "closed"), _read("closed"),
        {"value": "badId", "expr": "(()=>{try{JarvisScreenshotPreview.openLightbox({artifact_id:'../../etc/passwd'});return 'opened'}"
                                   "catch(e){return e.code}})()"},
    ], tmp_path=tmp_path)
    r = out["reads"]
    [artifact] = await _screenshots(stack)
    payload = f"/api/artifacts/{artifact.artifact_id}/payload"
    shown = r["shown"]
    assert shown["hidden"] is False and shown["z"] == "38" and shown["control"] is True
    assert shown["natural"] == [WIDTH, HEIGHT] and shown["src"] == payload, "a real thumbnail through the payload route"
    assert shown["title"].startswith("Capture d’écran · ") and shown["meta"].startswith(f"{WIDTH}×{HEIGHT} · ")
    assert [b[0] for b in shown["buttons"]] == ["send", "open", "delete"], "no Annotate button outside S05.B"
    assert shown["focusInPreview"] is False, "the preview never takes the focus when it appears"
    _no_overlap_with_neighbours(shown)
    lb = r["lightbox"]["lightbox"]
    assert lb["open"] is True and lb["z"] == "60" and "overlay" in lb["cls"].split() and lb["modal"] == "true"
    assert lb["natural"] == [WIDTH, HEIGHT] and lb["src"] == payload
    assert lb["href"] == payload and lb["target"] == "_blank" and "noopener" in lb["rel"]
    assert lb["focusInside"] is True and lb["focusText"] == "Fermer"
    assert r["lightbox"]["paused"] is True and r["lightbox"]["hidden"] is False, "the preview waits behind the lightbox"
    assert r["tab"] == {"status": 200, "type": "image/png", "bytes": len(IMAGE)}, "same payload, same origin"
    assert (r["tab1"], r["tab2"]) == ("Fermer", "Ouvrir dans un onglet") or (r["tab1"], r["tab2"]) == (
        "Ouvrir dans un onglet", "Fermer"), "the focus stays inside the lightbox"
    closed = r["closed"]
    assert closed["lightbox"]["open"] is False and closed["hidden"] is False
    assert closed["focus"] == "open", "Escape returns the focus to « Ouvrir »"
    assert r["badId"] == "invalid_artifact_id"
    lines = "\n".join(out["console"])
    assert "preview_shown" in lines and "lightbox_opened" in lines and "lightbox_closed" in lines


async def test_rail_board_image_opens_the_same_lightbox(stack, tmp_path):
    """Slice 07 appelle `JarvisScreenshotPreview.openLightbox({artifact_id, url, title})` pour une image liée au
    Board : la carte du rail (« Sur ce Board ») ouvre cette visionneuse, sur la vraie route du payload. La capture
    est prise AVANT le chargement : l'aperçu ne la montre pas (seulement après une prise de cette page)."""

    status, body, _ = await stack.call("POST", "/api/captures/screenshot", json={})
    assert status == 201, body
    artifact_id = body["artifact"]["artifact_id"]
    out = await _drive(stack.url, [
        {"eval": "JarvisPresentationRail.setPref('shown')"},
        _until("!!document.querySelector('#presentationRail .jvr-ws .jvr-item[data-ws]')", 15000, "rail item"),
        {"value": "railItem", "expr": "document.querySelector('#presentationRail .jvr-ws .jvr-item[data-ws]').dataset.id"},
        {"value": "previewBefore", "expr": "window.JarvisScreenshotPreview.view().shown"},
        {"click": "#presentationRail .jvr-ws .jvr-item[data-ws]"},
        _until(LIGHTBOX_OPEN + "&&document.querySelector('#screenshotLightbox img').complete", 5000, "rail lightbox"),
        {"wait": 150}, _read("fromRail"), _shot(tmp_path, "lightbox-from-rail-1440x900"),
        {"key": "Escape"}, _until("!" + LIGHTBOX_OPEN, 2000, "rail closed"),
        {"value": "focusBack", "expr": "!!document.activeElement.closest('#presentationRail')"},
    ], tmp_path=tmp_path)
    r = out["reads"]
    assert r["railItem"] == artifact_id and r["previewBefore"] is False
    lb = r["fromRail"]["lightbox"]
    assert lb["open"] is True and lb["src"] == f"/api/artifacts/{artifact_id}/payload" and lb["natural"] == [WIDTH, HEIGHT]
    assert lb["title"] and lb["focusText"] == "Fermer"
    assert r["focusBack"] is True, "Escape returns the focus to the rail card"
    lines = "\n".join(out["console"])
    assert "workspace_item_opened" in lines and '"surface":"lightbox"' in lines and "lightbox_opened" in lines


async def test_delete_requires_confirm_and_removes_artifact(stack, tmp_path):
    out = await _drive(stack.url, [
        TAKE, _until(SHOWN, 8000, "shown"),
        {"click": "#screenshotPreview [data-sp-act=delete]"},
        _until("!document.getElementById('confirmBack').hidden", 3000, "confirm"),
        {"value": "confirm", "expr": "({title:document.getElementById('confirmTitle').textContent,"
                                     "go:document.getElementById('confirmGo').textContent,"
                                     "danger:document.getElementById('confirmDialog').classList.contains('danger')})"},
        _shot(tmp_path, "delete-confirm-1440x900"),
        {"click": "#confirmCancel"}, _until("document.getElementById('confirmBack').hidden", 2000, "cancelled"),
        {"value": "afterCancel", "expr": "window.JarvisScreenshotPreview.view().shown"},
        # Double clic : une seule confirmation, une seule requête.
        {"eval": "(b=>{b.click();b.click()})(document.querySelector('#screenshotPreview [data-sp-act=delete]'))"},
        _until("!document.getElementById('confirmBack').hidden", 3000, "confirm again"),
        {"click": "#confirmGo"}, _until(HIDDEN, 8000, "deleted"), _read("deleted"),
    ], tmp_path=tmp_path)
    r = out["reads"]
    assert r["confirm"] == {"title": "Supprimer cette capture d’écran ?", "go": "Supprimer", "danger": True}
    assert r["afterCancel"] is True, "cancel keeps the preview and the artifact"
    assert await _screenshots(stack) == [], "the artifact is gone from Core"
    lines = "\n".join(out["console"])
    assert lines.count("delete_cancelled") == 1 and lines.count("delete_requested") == 1
    assert lines.count("delete_ignored") == 1 and lines.count("[screenshot_preview] deleted") == 1
    trace = [row for row in stack.trace() if row.get("kind") == "capture.request.relayed"
             and (row.get("data") or {}).get("action") == "artifact_delete"]
    assert len(trace) == 1 and trace[0]["data"]["status"] == 200, "one DELETE relayed, after the confirmation"
    assert r["deleted"]["view"]["shown"] is False


async def test_delete_refusal_keeps_preview_and_capture_truth(stack, tmp_path):
    """Adversarial : l'Artifact a disparu entre la prise et le clic (un autre onglet, le cerveau) ; Core refuse,
    l'aperçu dit le refus avec son code, rien d'autre ne bouge (la ligne de capture reste `complete`)."""

    out = await _drive(stack.url, [
        TAKE, _until(SHOWN, 8000, "shown"),
        {"value": "id", "expr": "window.JarvisScreenshotPreview.view().item.artifactId"},
        {"eval": "fetch('/api/artifacts/'+window.JarvisScreenshotPreview.view().item.artifactId,{method:'DELETE'})"},
        {"click": "#screenshotPreview [data-sp-act=delete]"},
        _until("!document.getElementById('confirmBack').hidden", 3000, "confirm"), {"click": "#confirmGo"},
        _until("!document.querySelector('#screenshotPreview .sp-note').hidden", 8000, "refused"), _read("refused"),
        _shot(tmp_path, "delete-refused-1440x900"),
        {"value": "wrong", "expr": "fetch('/api/artifacts/not-an-artifact',{method:'DELETE'}).then(async r=>[r.status,(await r.json()).error.code])"},
    ], tmp_path=tmp_path)
    r = out["reads"]
    refused = r["refused"]
    assert refused["hidden"] is False and refused["note"]["text"] == (
        "Suppression refusée : elle n’existe plus chez Jarvis Core (artifact_not_found).")
    assert "true" not in [b[2] for b in refused["buttons"]], "actions stay usable after a refusal"
    assert r["wrong"] == [400, "invalid_artifact"]
    recent = await stack.core.captures.recent(limit=5)
    assert [rec.state.value for rec in recent if rec.channel is CaptureChannel.SCREEN] == ["complete"]


async def test_send_attaches_existing_artifact_to_chat_composer(stack, tmp_path):
    out = await _drive(stack.url, [
        TAKE, _until(SHOWN, 8000, "shown"),
        {"value": "chatBefore", "expr": "window.JarvisChat.isOpen()"},
        {"click": "#screenshotPreview [data-sp-act=send]"},
        _until("document.querySelectorAll('#chatFiles .chat-file[data-status=ready]').length===1", 15000, "chip"),
        {"wait": 200},
        {"value": "chat", "expr": """(()=>{const s=window.JarvisChat.instance.snapshot();
            const li=document.querySelector('#chatFiles .chat-file');
            const drafts=Object.keys(localStorage).filter(k=>k.startsWith('jarvis.chat.draft.')).map(k=>localStorage.getItem(k));
            return {open:s.open,cid:s.conversation_id,items:s.attachments.items.map(i=>({name:i.name,status:i.status,existing:!!i.existing,
              cu:i.clientUploadId,id:i.artifactId,mime:i.mime,size:i.size})),ids:s.attachments.ids,
              chip:[li.querySelector('.chat-file-name').textContent,li.querySelector('.chat-file-text').textContent],
              focus:document.activeElement.id,send:document.getElementById('chatSend').getAttribute('aria-disabled'),
              note:document.getElementById('chatAttNote').hidden?null:document.getElementById('chatAttNote').textContent,
              drafts,previewShown:window.JarvisScreenshotPreview.view().shown}})()"""},
        _shot(tmp_path, "send-chip-1440x900"),
        # Le tour part par la VRAIE route ; on relève seulement ce que la page envoie et ce que Core répond.
        {"eval": "(f=>{window.__turns=[];window.fetch=(u,i)=>{const p=f(u,i);if(String(u).startsWith('/api/chat/turns'))"
                 "p.then(r=>r.clone().json()).then(b=>window.__turns.push({body:JSON.parse(i.body),answer:b})).catch(()=>{});return p}})(window.fetch)"},
        # Le verrou du composer vient de `/api/chat/state` (voix) : on attend que Core dise le chat inscriptible.
        _until("!window.JarvisChat.instance.snapshot().view.locked", 15000, "writable"), {"focus": "#chatInput"},
        {"type": "Que vois-tu sur cette capture ?"}, {"wait": 100},
        {"value": "typed", "expr": "(s=>({locked:s.view.locked||false,send:document.getElementById('chatSend').getAttribute('aria-disabled')}))(window.JarvisChat.instance.snapshot())"},
        {"key": "Enter"}, _until("window.__turns.length>0", 15000, "turn"), {"wait": 300},
        {"value": "turns", "expr": "window.__turns"},
    ], tmp_path=tmp_path)
    r = out["reads"]
    [artifact] = await _screenshots(stack)
    chat = r["chat"]
    assert r["chatBefore"] is False and chat["open"] is True and chat["cid"]
    [item] = chat["items"]
    assert item["status"] == "ready" and item["existing"] is True and item["cu"] == "" and item["id"] == artifact.artifact_id
    assert item["mime"] == "image/png" and item["size"] == len(IMAGE) and item["name"].startswith("Capture d’écran ")
    assert chat["chip"] == [item["name"], "Prête"]
    assert chat["focus"] == "chatInput", "the input takes the focus"
    assert chat["send"] == "true" and chat["note"] == "Ajoutez un message pour accompagner les fichiers.", "text still required"
    assert chat["previewShown"] is False
    assert all(len(d) < 1024 and artifact.artifact_id in d for d in chat["drafts"]), "the draft keeps an id, never bytes"
    [turn] = r["turns"]
    assert turn["body"]["content"] == "Que vois-tu sur cette capture ?" and turn["body"]["attachments"] == [artifact.artifact_id]
    assert r["typed"] == {"locked": False, "send": "false"}, "with text, the message may leave"
    assert turn["answer"]["ok"] is True and turn["answer"]["duplicate"] is False, "Core admits the screenshot"
    record = await stack.core.brain.admitted_turn(turn["body"]["conversation_id"], turn["answer"]["correlation_id"])
    assert record.metadata["attachments"] == [artifact.artifact_id]
    lines = "\n".join(out["console"])
    assert "chat.attached_existing" in lines and "upload_started" not in lines, "no upload: the artifact is already in Core"
    assert '"attachments":1' in lines and "turn_sending" in lines


async def test_preview_never_blocks_board_pointer(stack, tmp_path):
    out = await _drive(stack.url, [
        {"focus": "#chatTab"},
        {"eval": "window.__hits=[];document.addEventListener('pointerdown',e=>window.__hits.push(e.target.id||String(e.target.className)||e.target.tagName),true)"},
        # Témoin : ce que reçoit un clic au centre et près du coin bas-gauche AVANT l'aperçu.
        {"at": {"x": 720, "y": 450}}, {"at": {"x": 330, "y": 600}}, {"wait": 100}, {"focus": "#chatTab"},
        TAKE, _until(SHOWN, 8000, "shown"), _read("shown"),
        {"value": "points", "expr": """(()=>{const r=document.getElementById('screenshotPreview').getBoundingClientRect();
            const pts=[[innerWidth/2,innerHeight/2],[r.right+12,r.top+20],[r.left+20,r.top-12],[r.right+40,r.bottom-10]];
            return pts.map(([x,y])=>{const el=document.elementFromPoint(x,y);
              return {inPreview:!!el.closest('#screenshotPreview'),overlay:!!el.closest('.overlay,.cdialog-back')}})})()"""},
        {"at": {"x": 720, "y": 450}}, {"at": {"x": 330, "y": 600}}, {"wait": 150}, {"value": "hits", "expr": "window.__hits"},
        {"value": "afterClick", "expr": "window.JarvisScreenshotPreview.view().shown"},
        # Survol : le délai s'arrête ; sortie : il repart entier.
        {"move": "#screenshotPreview .sp-title"}, {"wait": 6500}, {"value": "hovered", "expr": "window.JarvisScreenshotPreview.view()"},
        {"hover": {"x": 720, "y": 300}}, {"wait": 6400}, _until(HIDDEN, 2000, "timeout"),
        # Échap avec le focus sur la page ferme l'aperçu ; jamais de suppression.
        TAKE, _until(SHOWN, 8000, "shown again"), {"eval": "document.activeElement.blur()"}, {"key": "Escape"},
        _until(HIDDEN, 2000, "escape"),
        # Un clavier dans l'aperçu le retient pendant qu'on mesure les tailles (le focus suspend le délai).
        {"resize": {"width": 1280, "height": 720}}, TAKE, _until(SHOWN, 8000, "1280"),
        {"focus": "#screenshotPreview .sp-close"}, _read("w1280"),
        _shot(tmp_path, "preview-1280x720"),
        {"resize": {"width": 900, "height": 600}}, _read("w900"),
        {"resize": {"width": 600, "height": 800}}, {"wait": 200}, _read("w600"), _shot(tmp_path, "preview-600x800"),
    ], tmp_path=tmp_path)
    r = out["reads"]
    shown = r["shown"]
    assert shown["focus"] == "chatTab", "the focus did not move"
    assert shown["inert"] == [], "nothing is made inert: non-modal"
    assert r["points"] == [{"inPreview": False, "overlay": False}] * 4, "no veil around the card"
    hits = r["hits"]
    assert len(hits) == 4 and hits[2:] == hits[:2], ("the same surfaces receive the pointer with the preview shown", hits)
    assert r["afterClick"] is True, "a click on the Board does not dismiss the preview"
    assert r["hovered"]["shown"] is True and r["hovered"]["paused"] is True
    for size in ("w1280", "w900", "w600"):
        _no_overlap_with_neighbours(r[size])
    assert len(await _screenshots(stack)) == 3, "timeouts and Escape never delete"
    lines = "\n".join(out["console"])
    assert '"reason":"timeout"' in lines and '"reason":"escape"' in lines

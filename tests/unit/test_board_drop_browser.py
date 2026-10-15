"""Dépôt sur le Board affiché, mesuré dans un vrai Chrome sans tête (handoff jarvis-unified-chat-and-board-drop, Slice 08).

Aucun double dans la page : un vrai Core (SQLite, payloads et scène sous
`tmp_path`) et un vrai `ControlCenter` (`CaptureStack`, scène relayée par
`CoreSceneView`) servent la page sur le bouclage ; `_board_drop_browser.mjs`
pilote un vrai glisser-déposer CDP (fichiers réels, `text/uri-list`) et de
vrais gestes de souris. Ce que ce fichier épingle (`slices/08-board-drop-extra/
SLICE.md` › *Contrat Slice 00*) :

- le calque visible au survol avec un fichier, et qui part sans dépôt ;
- un dépôt multiple (PDF + image) et une URL déposée, chacun dit dans le
  plateau (« Ajouté au Board « … » ») ;
- un dépôt sur le panneau du Chat reste une pièce jointe du Chat et
  n'atterrit pas aussi sur le Board ;
- la scène toujours manipulable après les dépôts (clic puis déplacement d'un
  objet, relu dans Core) ;
- Board A → B → A, et rechargement : les dépôts restent ceux de A dans
  l'inspecteur Workspace, absents de B ;
- aucune requête de la page vers l'URL déposée, aucune connexion sortante de
  Core ou du Control Center, aucun événement de conversation.

Captures dans `JARVIS_S8_EVIDENCE_DIR` quand la variable est posée. Se saute si
Chrome ou node manque.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil

import pytest

from jarvis.domain.artifacts import ArtifactKind, ArtifactQuery
from jarvis.domain.scene import SceneObjectKind, WorkRef
from jarvis.runtime.scene_view import CoreSceneTransport, CoreSceneView
from tests.fakes.capture_stack import CaptureStack
from tests.unit.test_board_drop import NoOutboundNetwork
from tests.unit.test_interaction_mode_hud_browser import _chrome
from tests.unit.test_scene_contracts import star

HARNESS = Path(__file__).parent / "_board_drop_browser.mjs"
URL = "https://example.invalid/compte-rendu?id=7"
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x35\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82")
PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
ITEMS = "[...document.querySelectorAll('#boardDropList .board-drop-item')]"
DONE = f"{ITEMS}.filter(li=>li.dataset.status==='done').length"
LAYER = ("(()=>{const l=document.getElementById('boardDrop');return {hidden:l.hidden,tone:l.dataset.tone||null,"
         "title:document.getElementById('boardDropTitle').textContent,sub:document.getElementById('boardDropSub').textContent,"
         "z:getComputedStyle(l).zIndex,frame:getComputedStyle(l,'::before').zIndex,"
         "card:getComputedStyle(l.querySelector('.board-drop-card')).zIndex,pe:getComputedStyle(l).pointerEvents}})()")
TRAY = (f"{ITEMS}.map(li=>({{status:li.dataset.status,name:li.querySelector('.board-drop-name').textContent,"
        "state:li.querySelector('.board-drop-state').textContent,time:li.querySelector('.board-drop-time').textContent,"
        "act:li.querySelector('.board-drop-act').hidden?null:li.querySelector('.board-drop-act').textContent}))")
#: Les lignes de l'inspecteur Workspace (Artefacts du Board ouvert) : libellé de nature et aperçu.
INSPECTOR = "[...document.querySelectorAll('#workspaceManager [data-act=artifact-toggle]')].map(el=>el.textContent.replace(/\\s+/g,' '))"


def _shot(tmp_path: Path, name: str) -> dict:
    folder = Path(os.environ.get("JARVIS_S8_EVIDENCE_DIR") or tmp_path)
    folder.mkdir(parents=True, exist_ok=True)
    return {"shot": str(folder / f"2026-10-15-s08-{name}.png")}


def _files(tmp_path: Path) -> dict[str, str]:
    folder = tmp_path / "files"
    folder.mkdir(exist_ok=True)
    out = {}
    for name, body in {"rapport.pdf": PDF, "photo.png": PNG, "note.txt": "Pièce du chat\n".encode()}.items():
        (folder / name).write_bytes(body)
        out[name] = str(folder / name)
    return out


async def _drive(url: str, actions: list, *, width: int = 1440, height: int = 900, ready: str = "true",
                 reduced_motion: bool = False) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    step = {"width": width, "height": height, "ready": ready, "reducedMotion": reduced_motion, "actions": actions}
    process = await asyncio.create_subprocess_exec(node, str(HARNESS), url, _chrome(), json.dumps(step),
                                                   stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await asyncio.wait_for(process.communicate(), 240)
    assert process.returncode == 0, stderr.decode("utf-8", "replace")
    out = json.loads(stdout.decode("utf-8"))
    if os.environ.get("JARVIS_S8_DUMP"):
        Path(os.environ["JARVIS_S8_DUMP"]).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    assert out["reads"]["ready"] is True, out
    assert "failed" not in out["reads"], out["reads"].get("failed")
    assert out["errors"] == [], out["errors"]
    return out


def _until(js: str, ms: int = 8000, name: str | None = None) -> dict:
    return {"until": js, "ms": ms, "name": name or js}


@pytest.fixture
async def stack(tmp_path):
    async with CaptureStack(tmp_path) as opened:
        port = int(opened.core_url.rsplit(":", 1)[1])
        opened.center.scene_view = CoreSceneView(
            CoreSceneTransport(host="127.0.0.1", port=port, token_file=tmp_path / "core.token"),
            journal=opened.center.journal)
        # `CaptureStack` pose `center.sessions` après la construction : le relais `/api/boards*` le reçoit ici.
        opened.center.board_routes._transport = opened.sessions
        await opened.core.scene.apply(star("star-a", kind=SceneObjectKind.AGENT,
                                           work_ref=WorkRef(source="claude", external_id="task-a")))
        try:
            yield opened
        finally:
            await opened.center.scene_view.aclose()


async def _drops(stack, board_id: str) -> dict[str, object]:
    page = await stack.core.artifacts.query(ArtifactQuery(board_id=board_id, limit=100))
    return {item.artifact_id: item for item in page.items if item.metadata.get("provenance") == "board_drop"}


async def _events(stack) -> list:
    store = stack.core.conversation_events
    rows = []
    for summary in (await store.list_conversations(limit=100)).summaries:
        rows.extend(item.event for item in (await store.list_conversation_events(summary.conversation_id,
                                                                                 limit=500)).events)
    return rows


async def test_board_drop_in_a_real_page(stack, tmp_path, monkeypatch):
    f = _files(tmp_path)
    board_a = (await stack.core.sessions.current()).session.active_board_id
    board_b = (await stack.core.boards.create({"title": "Projet B"})).board_id
    before = next(o for o in (await stack.core.scene.snapshot()).objects if o.object_id == "star-a")
    events_before = await _events(stack)
    guard = NoOutboundNetwork(monkeypatch)
    page = f"http://127.0.0.1:{stack.cc_port}/"
    switch = lambda board: {"eval": (  # noqa: E731 - bascule normale du contrôle Boards (POST /api/boards/switch)
        f"window.JarvisBoardsControl.switchTo('{board}');1")}
    active_is = lambda board: _until(f"window.JarvisBoardsControl.activeId()==='{board}'"  # noqa: E731
                                     "&&window.JarvisBoardsControl.presentation().tone==='ready'", 15000)
    out = await _drive(page, [
        active_is(board_a), _until("document.querySelector('#sceneLayer .sc-node')", 15000, "node"),
        # Survol avec un fichier : le calque dit où ira le dépôt ; sans dépôt, il part.
        {"hover": "free", "paths": [f["photo.png"]]}, {"value": "hover", "expr": LAYER},
        _shot(tmp_path, "hover-1440x900"),
        {"cancel": "free"}, {"wait": 700}, {"value": "after_cancel", "expr": LAYER},
        # Dépôt multiple, puis une URL.
        {"drop": "free", "paths": [f["rapport.pdf"], f["photo.png"]]}, _until(f"{DONE}===2", 15000, "files"),
        {"drop": "free", "url": URL}, _until(f"{DONE}===3", 15000, "link"),
        {"value": "tray", "expr": TRAY}, _shot(tmp_path, "done-1440x900"),
        # « Voir dans l'inspecteur » : la vue Artefacts du Board, avec les trois dépôts.
        {"click": "#boardDropList .board-drop-item:nth-child(3) .board-drop-act"},
        _until(f"{INSPECTOR}.length>=3", 10000, "inspector_now"), {"value": "inspector_now", "expr": INSPECTOR},
        _shot(tmp_path, "inspector-1440x900"), {"eval": "window.JarvisWorkspace.close();1"}, {"wait": 300},
        # Un fichier lâché sur le panneau du Chat reste une pièce jointe du Chat.
        {"click": "#chatTab"}, _until("document.getElementById('chatPanel').classList.contains('open')", 5000, "chat"),
        {"drop": "#chatLog", "paths": [f["note.txt"]]},
        _until("[...document.querySelectorAll('#chatFiles .chat-file')].some(li=>li.dataset.status==='ready')", 15000,
               "chat_ready"),
        {"value": "tray_after_chat", "expr": f"{ITEMS}.length"}, {"click": "#chatClose"}, {"wait": 300},
        # La scène reste manipulable : clic, puis glisser d'un objet.
        {"click": "#sceneLayer .sc-node"}, {"wait": 200},
        {"value": "clicked", "expr": "!!(document.activeElement&&document.activeElement.closest('.sc-node'))"},
        {"mouseDrag": "#sceneLayer .sc-node", "dx": 90, "dy": 60}, {"wait": 1500},
        # A -> B -> A : un dépôt sur B va à B ; revenu sur A, ceux de A sont là.
        switch(board_b), active_is(board_b), {"drop": "free", "paths": [f["photo.png"]]},
        _until(f"{DONE}>=1&&{ITEMS}.some(li=>li.textContent.includes('Projet B'))", 15000, "on_b"),
        {"value": "tray_b", "expr": TRAY}, switch(board_a), active_is(board_a),
        # Après rechargement, l'inspecteur Workspace du Board A liste les trois dépôts.
        {"reload": True}, active_is(board_a),
        {"eval": f"window.JarvisWorkspace.open();window.JarvisWorkspace.act('goto',{{view:'artifacts',scope:'board',id:'{board_a}'}});1"},
        _until(f"{INSPECTOR}.filter(t=>t.includes('Fichier déposé')||t.includes('Lien')).length>=3", 15000, "inspector"),
        {"value": "inspector_a", "expr": INSPECTOR}, _shot(tmp_path, "inspector-a-1440x900"),
    ], reduced_motion=True)  # le champ ne tourne pas : le clic vise l'objet là où il est
    reads = out["reads"]
    hover = reads["hover"]
    assert hover["hidden"] is False and hover["tone"] == "ok" and hover["title"] == "Déposer sur « Jarvis »" \
        or hover["title"].startswith("Déposer sur « "), hover
    assert hover["z"] == "auto" and hover["frame"] == "21" and hover["pe"] == "none", "above the scene, no pointer"
    assert hover["card"] == "34", "the card stays above the capture rail and the hands button (30-32)"
    assert reads["after_cancel"]["hidden"] is True, "the layer leaves without a drop"
    tray = reads["tray"]
    assert [row["status"] for row in tray] == ["done", "done", "done"], tray
    assert [row["name"] for row in tray] == ["rapport.pdf", "photo.png", URL]
    assert all(row["state"].startswith("Ajouté au Board « ") and row["act"] == "Voir dans l’inspecteur" for row in tray)
    assert reads["until:chat_ready"] is True and reads["tray_after_chat"] == 3, "a chat drop never lands on the Board"
    assert reads["clicked"] is True
    assert reads["until:on_b"] is True
    assert reads["until:inspector_now"] is True and any(URL in row and "Lien" in row for row in reads["inspector_now"])
    assert reads["reloaded"] is True and reads["until:inspector"] is True
    inspector = " | ".join(reads["inspector_a"])
    assert "rapport.pdf" in inspector and "photo.png" in inspector and URL in inspector and "Lien" in inspector
    # Core : A garde ses trois dépôts, B le sien, aucun croisement.
    on_a, on_b = await _drops(stack, board_a), await _drops(stack, board_b)
    assert sorted(item.kind.value for item in on_a.values()) == ["link", "upload", "upload"]
    assert len(on_b) == 1 and set(on_a).isdisjoint(on_b)
    uploads = (await stack.core.artifacts.query(ArtifactQuery(kinds=(ArtifactKind.UPLOAD,), limit=50))).items
    assert sum(1 for item in uploads if item.metadata.get("provenance") == "chat_attachment") == 1
    # La scène : l'objet déplacé par l'utilisateur a changé de place dans Core.
    after = next(o for o in (await stack.core.scene.snapshot()).objects if o.object_id == "star-a")
    assert after.geometry != before.geometry, (before.geometry, after.geometry)
    # Ni requête vers l'URL, ni connexion sortante, ni événement de conversation.
    assert not any("example.invalid" in request for request in out["requests"]), out["requests"]
    assert guard.attempts == []
    assert await _events(stack) == events_before
    assert not any("rapport.pdf" in line or "example.invalid" in line for line in out["console"] if "[board-drop]" in line)
    assert any("board_drop.upload_done" in line for line in out["console"])


async def test_refusals_are_said_in_words_and_narrow_screens_fit(stack, tmp_path):
    """Lien refusé par Core, Board changé ailleurs (409) : dits dans le plateau, « Réessayer » ; 600 × 800 et Cosmos."""

    board_a = (await stack.core.sessions.current()).session.active_board_id
    board_b = (await stack.core.boards.create({"title": "Projet B"})).board_id
    page = f"http://127.0.0.1:{stack.cc_port}/"
    out = await _drive(page, [
        _until(f"window.JarvisBoardsControl.activeId()==='{board_a}'", 15000),
        {"drop": "free", "url": "ftp://example.invalid/fichier"},
        _until(f"{ITEMS}.some(li=>li.dataset.status==='failed')", 10000, "refused"),
        {"value": "refused", "expr": TRAY}, _shot(tmp_path, "refused-600x800"),
        # Le Board change par la voix ou un autre onglet : la page croit encore A, Core dit 409.
        {"eval": f"(async()=>{{const r=await fetch('/api/boards/switch',{{method:'POST',headers:{{'Content-Type':"
                 f"'application/json'}},body:JSON.stringify({{board_id:'{board_b}'}})}});const c=window.JarvisBoardsControl;"
                 f"window.JarvisBoardsControl={{...c,activeId:()=>'{board_a}',presentation:()=>({{tone:'ready',"
                 f"title:'Board principal'}})}};return r.status}})()"},
        {"drop": "free", "url": URL},
        _until(f"{ITEMS}.filter(li=>li.dataset.status==='failed').length===2", 10000, "inactive"),
        {"value": "inactive", "expr": TRAY},
        {"eval": "document.documentElement.dataset.jarvisTheme='cosmos';1"}, {"wait": 200},
        {"hover": "free", "paths": [__file__]}, {"wait": 100}, _shot(tmp_path, "hover-cosmos-600x800"),
        # La carte n'est couverte par aucune commande (rail de capture, palette, bouton des mains) à 600 px.
        {"value": "cover", "expr": "(()=>{const card=document.querySelector('#boardDrop .board-drop-card');"
                                   "const r=card.getBoundingClientRect(),z=+getComputedStyle(card).zIndex;"
                                   "return [...document.querySelectorAll('#captureRail,#captureRail *,#barehandsPalette,"
                                   "#barehandsPalette *,#barehandsHud *')].filter(el=>{const b=el.getBoundingClientRect();"
                                   "const ez=+getComputedStyle(el).zIndex||0;return b.width&&b.right>r.left&&b.left<r.right"
                                   "&&b.bottom>r.top&&b.top<r.bottom&&ez>=z}).map(el=>el.id||el.className)})()"},
        {"value": "width", "expr": "[document.documentElement.scrollWidth,innerWidth,"
                                   "document.getElementById('boardDropTray').getBoundingClientRect().right]"},
    ], width=600, height=800)
    reads = out["reads"]
    refused = reads["refused"][0]
    assert refused["status"] == "failed" and refused["state"].startswith("Lien refusé : http ou https seulement")
    assert refused["act"] is None, "the same link would be refused the same way"
    inactive = reads["inactive"][1]
    assert inactive["state"].startswith("Le Board affiché a changé") and inactive["act"] == "Réessayer"
    assert reads["cover"] == [], "no page control above the drop card"
    scroll, inner, right = reads["width"]
    assert scroll == inner and right <= inner, "no horizontal scroll at 600 px"
    assert any("board_drop.link_failed" in line and "board_drop_target_inactive" in line for line in out["console"])
    assert await _drops(stack, board_a) == {} and await _drops(stack, board_b) == {}

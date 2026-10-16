"""Rail actif, etape B (Slice 07 du handoff orbital, D10) : l'adaptateur pur `control_center_workspace_rail_model.js` (node, sans navigateur).

Il fait des Artifacts lies au Board actif (`GET /api/workspace/artifacts?board_id=`) des `WorkspaceRailItem` : type par nature, `mime_type` ou hote du
lien, apercu image seulement par la route bornee du payload, etat sans jaune, aucune fuite d'un Board vers l'autre. Le dessin est prouve par
`test_control_center_presentation_rail_browser.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

RUNTIME = Path(__file__).resolve().parents[2] / "jarvis" / "runtime"
B1, B2 = "brd_" + "1" * 16, "brd_" + "2" * 16


def node(script: str):
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node absent")
    code = (f"const M=require({json.dumps(str(RUNTIME / 'control_center_workspace_rail_model.js'))});"
            f"(async()=>{{const out=await (async()=>{{{script}}})();process.stdout.write(JSON.stringify(out))}})().catch(e=>{{console.error(e);process.exit(1)}})")
    done = subprocess.run([exe, "-e", code], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def art(n: int, kind: str, **extra) -> dict:
    return {"artifact_id": f"jart_{n:032x}", "kind": kind, "state": "complete", "has_payload": True, "created_at": "2026-10-16T09:00:00Z", **extra}


ARTIFACTS = [
    art(1, "screenshot", mime_type="image/png"),
    art(2, "upload", mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation", preview="Roadmap Q4.pptx"),
    art(3, "upload", mime_type="image/jpeg", preview="montagne.jpg"),
    art(4, "upload", mime_type="video/mp4", preview="demo.mp4", state="pending"),
    art(5, "link", preview="https://docs.google.com/presentation/d/abc/edit", has_payload=False),
    art(6, "link", preview="https://www.youtube.com/watch?v=x", has_payload=False),
    art(7, "link", preview="https://exemple.fr/notes", has_payload=False),
    art(8, "upload", mime_type="application/pdf", preview="contrat.pdf", state="failed"),
    art(9, "presentation_video", mime_type="video/mp4", state="partial"),
    art(10, "transcript", mime_type="text/plain"),               # not a working document: never shown
    art(11, "presentation_snapshot", mime_type="application/zip"),
    {"artifact_id": "../etc/passwd", "kind": "upload", "state": "complete"},
    art(12, "screen_recording", mime_type="video/webm", state="weird"),
]


def test_items_from_board_artifacts_typed_by_mime_and_host():
    answer = {"artifacts": ARTIFACTS, "scope": {"board_id": B1}, "next_cursor": None}
    items = node(f"return M.itemsOf({json.dumps(answer)},{json.dumps(B1)})")
    by_id = {i["id"][-2:]: i for i in items}
    assert sorted(by_id) == ["01", "02", "03", "04", "05", "06", "07", "08", "09", "0c"], "transcripts, snapshots and a bad id are not shown"
    assert {k: v["type"]["badge"] for k, v in by_id.items()} == {
        "01": "Capture", "02": "PowerPoint", "03": "Image", "04": "Vidéo", "05": "Google Slides", "06": "YouTube", "07": "exemple.fr",
        "08": "PDF", "09": "MP4", "0c": "Vidéo"}
    assert by_id["01"]["preview"] == {"kind": "image", "url": "/api/artifacts/jart_00000000000000000000000000000001/payload"}
    assert by_id["03"]["preview"]["kind"] == "image" and by_id["03"]["primary_action"] == "lightbox"
    for key in ("02", "04", "05", "06", "07", "08", "09", "0c"):
        assert by_id[key]["preview"]["kind"] == "placeholder" and by_id[key]["primary_action"] == "detail", key
    assert {k: v["activity_state"] for k, v in by_id.items()} == {
        "01": "ready", "02": "ready", "03": "ready", "04": "working", "05": "ready", "06": "ready", "07": "ready",
        "08": "problem", "09": "problem", "0c": "unknown"}, "no yellow for Board artifacts: no canonical review owner"
    assert by_id["02"]["title"] == "Roadmap Q4.pptx" and by_id["05"]["title"] == "docs.google.com/presentation/d/abc/edit"
    assert by_id["05"]["url"] == "https://docs.google.com/presentation/d/abc/edit" and by_id["01"]["url"] is None
    assert by_id["01"]["source_scope"] == {"board_id": B1} and by_id["01"]["context_actions"] == ["detail"]
    url = node(f"return M.urlFor({json.dumps(B1)})")
    assert url.startswith(f"/api/workspace/artifacts?board_id={B1}&limit=24&kind=upload&kind=link") and "presentation_snapshot" not in url
    pending_image = node(f"return M.itemOf({json.dumps(art(20, 'screenshot', state='pending'))},{json.dumps(B1)}).preview.kind")
    assert pending_image == "placeholder", "an image that is not complete is never fetched"
    js = node("return M.itemOf({artifact_id:'jart_0123456789abcdef',kind:'link',state:'complete',preview:'javascript:alert(1)'},'b').url")
    assert js is None, "only http(s) links are offered"


def test_board_switch_drops_previous_items():
    out = node(f"""
      const calls=[];const gates={{}};
      const fetch=(url)=>{{calls.push(url);const board=new URL('http://x'+url).searchParams.get('board_id');
        return new Promise(res=>{{gates[board]=()=>res({{ok:true,status:200,json:async()=>({{artifacts:[{{artifact_id:'jart_'+board.slice(-1).repeat(32),kind:'screenshot',state:'complete'}}],scope:{{board_id:board}}}})}})}})}};
      const seen=[];const src=M.createSource({{fetch,onChange:v=>seen.push([v.boardId,v.status,v.items.map(i=>i.id.slice(-1))])}});
      const first=src.setBoard({json.dumps(B1)});
      const second=src.setBoard({json.dumps(B2)});          // switch before B1 answered
      const afterSwitch=src.view();
      gates[{json.dumps(B1)}]();await first;                  // B1's late answer must not show under B2
      const afterLate=src.view();
      gates[{json.dumps(B2)}]();await second;
      const final=src.view();
      const back=src.setBoard({json.dumps(B1)});const whileBack=src.view();gates[{json.dumps(B1)}]();await back;const backView=src.view();
      // a foreign scope (a relay answering another Board) gives nothing
      const foreign=M.itemsOf({{artifacts:[{{artifact_id:'jart_'+'9'.repeat(32),kind:'screenshot',state:'complete'}}],scope:{{board_id:{json.dumps(B2)}}}}},{json.dumps(B1)});
      const none=await src.setBoard(null);
      return {{afterSwitch,afterLate,final,whileBack,back:backView,foreign,none,calls:calls.length}}""")
    assert out["afterSwitch"] == {"boardId": B2, "items": [], "status": "loading", "error": None}, "switching empties at once"
    assert out["afterLate"]["items"] == [] and out["afterLate"]["boardId"] == B2, "the previous Board's late answer is dropped"
    assert [i["id"][-1] for i in out["final"]["items"]] == ["2"] and out["final"]["status"] == "ready"
    assert out["whileBack"]["items"] == [], "nothing of B2 stays while B1 loads"
    assert [i["id"][-1] for i in out["back"]["items"]] == ["1"]
    assert out["foreign"] == [] and out["none"]["items"] == [] and out["none"]["status"] == "idle"
    assert out["calls"] == 3


def test_a_failed_read_is_said_and_keeps_nothing_false():
    out = node(f"""
      const logs=[];
      const src=M.createSource({{fetch:async()=>({{ok:false,status:404,json:async()=>({{error:{{code:'board_not_found',message:'board inconnu'}}}})}}),log:(k,d,l)=>logs.push([k,l,d.code])}});
      await src.setBoard({json.dumps(B1)});
      const down=M.createSource({{fetch:async()=>{{throw new TypeError('Failed to fetch')}}}});await down.setBoard({json.dumps(B1)});
      return {{v:src.view(),logs,down:down.view()}}""")
    assert out["v"]["status"] == "failed" and out["v"]["error"] == "board inconnu" and out["v"]["items"] == []
    assert out["logs"] == [["workspace_items_failed", "warn", "board_not_found"]]
    assert out["down"]["status"] == "failed" and "Failed to fetch" in out["down"]["error"]

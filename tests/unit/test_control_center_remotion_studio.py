"""Carte « Remotion » et Studio optionnel du Control Center : relais vers Core et module JavaScript (Slice 11).

Relais : six adresses seulement, jamais d'installation ni de chemin libre, toutes gardées (Host et origine de boucle locale), erreurs de
Core rendues telles quelles. Module : modèle de la carte (libellés français, actions possibles, compteurs), client, absence de nom ou de
chemin en dur. Le rendu dans un vrai navigateur est dans les preuves de la Slice (`slices/11-remotion-studio-process-ui/evidence`).
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.runtime.control_center import REMOTION_STUDIO_SCRIPT_MARKER
from jarvis.runtime.remotion_studio_relay import START_TIMEOUT_S, SHORT_TIMEOUT_S
from tests.unit.test_control_center_mcp_plugins_api import RecordingCore, _center, _trace

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "jarvis" / "runtime" / "control_center_remotion_studio.js"
PAGE = ROOT / "jarvis" / "runtime" / "control_center.html"
STUDIO = "/api/local-capabilities/remotion/studio"
CORE = "/v1/local-capabilities/remotion"


async def client_for(tmp_path, core) -> TestClient:
    client = TestClient(TestServer(_center(tmp_path, core)._app))
    await client.start_server()
    return client


# ------------------------------------------------------------------ relais

async def test_each_route_relays_to_the_matching_core_route_with_the_right_deadline(tmp_path):
    core = RecordingCore((200, {"studio": {"status": "stopped"}}))
    client = await client_for(tmp_path, core)
    try:
        for method, path, core_path, timeout in (
            ("GET", "/api/local-capabilities/remotion", CORE, 10.0), ("GET", STUDIO, CORE + "/studio", 10.0),
            ("POST", STUDIO + "/open", CORE + "/studio/open", START_TIMEOUT_S), ("POST", STUDIO + "/restart", CORE + "/studio/restart", START_TIMEOUT_S),
            ("POST", STUDIO + "/sync", CORE + "/studio/sync", SHORT_TIMEOUT_S), ("POST", STUDIO + "/close", CORE + "/studio/close", SHORT_TIMEOUT_S)):
            core.calls.clear()
            response = await client.request(method, path, **({"data": b'{"prefab_id":"a","version":1}'} if method == "POST" else {}))
            assert response.status == 200, (method, path)
            [call] = core.calls
            assert (call["method"], call["path"], call["timeout_s"]) == (method, core_path, timeout)
    finally:
        await client.close()


async def test_the_body_goes_through_unchanged_and_core_errors_are_returned_as_they_are(tmp_path):
    core = RecordingCore((409, {"error": {"code": "remotion_studio_runtime_unavailable", "message": "install first"}}))
    client = await client_for(tmp_path, core)
    try:
        response = await client.post(STUDIO + "/open", data=b'{"prefab_id":"x","version":2}')
        assert response.status == 409 and (await response.json())["error"]["code"] == "remotion_studio_runtime_unavailable"
        assert core.calls[0]["body"] == b'{"prefab_id":"x","version":2}'
    finally:
        await client.close()


async def test_nothing_else_is_relayed_no_uninstall_no_free_path_and_queries_are_refused(tmp_path):
    core = RecordingCore()
    client = await client_for(tmp_path, core)
    try:
        for method, path, status in (("POST", "/api/local-capabilities/remotion/uninstall", 404), ("POST", "/api/local-capabilities/remotion/disable", 404),
                                     ("POST", "/api/local-capabilities/remotion/update", 404), ("GET", "/api/local-capabilities/remotion/repair", 405),
                                     ("POST", "/api/local-capabilities/remotion/repair?x=1", 400),
                                     ("POST", STUDIO + "/../uninstall", 404),
                                     ("DELETE", STUDIO, 405), ("PUT", STUDIO + "/open", 405), ("GET", STUDIO + "/open", 405),
                                     ("GET", STUDIO + "?x=1", 400)):
            response = await client.request(method, path)
            assert response.status == status, (method, path, response.status)
            body = await response.json()
            assert body["error"]["code"] in {"not_found", "method_not_allowed", "remotion_studio_invalid"}
        assert (await client.get("/api/local-capabilities/other")).status == 404
        big = await client.post(STUDIO + "/open", data=b"x" * 3000)
        assert big.status == 400
        assert core.calls == []
    finally:
        await client.close()


async def test_install_and_repair_are_the_only_capability_writes_and_never_forward_the_page_body(tmp_path):
    """Slice 20: the repair gesture of the engine error card. Empty `{}` body to Core whatever the page sent; same guard as the rest."""

    core = RecordingCore((202, {"capability": {"status": "installing"}}))
    client = await client_for(tmp_path, core)
    try:
        for operation in ("install", "repair"):
            core.calls.clear()
            response = await client.post(f"/api/local-capabilities/remotion/{operation}", data=b'{"path":"C:/evil","force":true}')
            assert response.status == 202
            [call] = core.calls
            assert (call["method"], call["path"], call["body"], call["timeout_s"]) == (
                "POST", f"{CORE}/{operation}", b"{}", SHORT_TIMEOUT_S)
            core.calls.clear()
            for headers in ({"Origin": "https://evil.example"}, {"Host": "evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
                assert (await client.post(f"/api/local-capabilities/remotion/{operation}", headers=headers)).status == 403
            assert core.calls == []
    finally:
        await client.close()


async def test_every_method_is_guarded_against_foreign_origins_and_hosts(tmp_path):
    core = RecordingCore()
    client = await client_for(tmp_path, core)
    try:
        for method, path in (("GET", STUDIO), ("POST", STUDIO + "/open"), ("POST", STUDIO + "/close"), ("GET", "/api/local-capabilities/remotion")):
            for headers in ({"Origin": "https://evil.example"}, {"Host": "evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
                response = await client.request(method, path, headers=headers)
                assert response.status == 403, (method, path, headers)
        assert core.calls == []
    finally:
        await client.close()


async def test_core_down_and_slow_are_reported_with_their_own_codes_and_journaled_once(tmp_path):
    client = await client_for(tmp_path, RecordingCore(fail=ConnectionRefusedError("down")))
    try:
        for _ in range(2):
            response = await client.get(STUDIO)
            assert response.status == 503 and (await response.json())["error"]["code"] == "core_unreachable"
        assert [e["kind"] for e in _trace(tmp_path)].count("remotion_studio.core_unreachable") == 1
    finally:
        await client.close()
    import asyncio
    client = await client_for(tmp_path, RecordingCore(fail=asyncio.TimeoutError()))
    try:
        response = await client.post(STUDIO + "/open", data=b"{}")
        body = await response.json()
        assert response.status == 504 and body["error"]["code"] == "core_timeout" and "unknown" in body["error"]["message"]
    finally:
        await client.close()
    center = _center(tmp_path, None)
    client = TestClient(TestServer(center._app))
    await client.start_server()
    try:
        response = await client.get(STUDIO)
        assert response.status == 503 and (await response.json())["error"]["code"] == "core_unconfigured"
    finally:
        await client.close()


async def test_writes_are_journaled_without_a_body(tmp_path):
    client = await client_for(tmp_path, RecordingCore((200, {"studio": {"status": "ready"}})))
    try:
        await client.post(STUDIO + "/open", data=b'{"prefab_id":"secret-looking-id","version":1}')
        events = [e for e in _trace(tmp_path) if e["kind"] == "remotion_studio.relayed"]
        assert events and events[0]["data"]["studio_status"] == "ready" and "secret-looking-id" not in json.dumps(events)
    finally:
        await client.close()


async def test_the_page_serves_the_module_and_the_container_in_the_plugins_tab(tmp_path):
    assert REMOTION_STUDIO_SCRIPT_MARKER in PAGE.read_text(encoding="utf-8")
    client = await client_for(tmp_path, RecordingCore())
    try:
        served = await (await client.get("/")).text()
    finally:
        await client.close()
    assert REMOTION_STUDIO_SCRIPT_MARKER not in served and "JarvisRemotionStudioCore" in served
    assert served.index('id="rmsCard"') > served.index('id="mcpPlugins"') and served.index('id="rmsCard"') < served.index('id="mcppBody"')


# ------------------------------------------------------------------ module JavaScript

def run_node(tmp_path: Path, source: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "rms-test.cjs"
    script.write_text(f"const C=require({json.dumps(str(MODULE))});const out=v=>process.stdout.write(JSON.stringify(v));\n"
                      "(async()=>{" + source + "})().then(v=>out(v===undefined?null:v)).catch(e=>{process.stderr.write(String(e&&e.stack||e));process.exit(1)});",
                      encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


READY = {"status": "ready", "url": "http://127.0.0.1:41000/", "port": 41000, "pin": {"prefab_id": "s", "version": 1}, "viewers": 0,
         "idle_in_s": 125, "syncs": 2, "started_at": 100, "diagnostics": [], "work_copy": {"modified_files": [], "edits_saved": 0}}


def model(tmp_path, studio, capability="ready", scene=None, now=200_000):
    return run_node(tmp_path, f"return C.viewModel({json.dumps(studio)},{json.dumps({'status': capability})},{json.dumps(scene)},{now});")


def test_a_stopped_studio_offers_only_open_and_only_when_a_scene_exists_and_remotion_is_ready(tmp_path):
    scene = {"id": "s", "version": 1}
    stopped = {"status": "stopped", "pin": None, "diagnostics": []}
    m = model(tmp_path, stopped, scene=scene)
    assert m["label"] == "Arrêté" and m["actions"]["open"]["enabled"] is True
    assert not any(m["actions"][k]["enabled"] for k in ("sync", "restart", "close"))
    assert model(tmp_path, stopped, scene=None)["actions"]["open"]["enabled"] is False
    assert "bibliothèque" in model(tmp_path, stopped, scene=None)["actions"]["open"]["why"]
    blocked = model(tmp_path, stopped, capability="not_installed", scene=scene)
    assert blocked["actions"]["open"]["enabled"] is False and blocked["capability"]["label"] == "Non installé"


def test_a_starting_studio_shows_motion_elapsed_time_and_its_deadline_and_blocks_actions(tmp_path):
    m = model(tmp_path, {"status": "starting", "started_at": 190, "pin": {"prefab_id": "s", "version": 1}, "diagnostics": []},
              scene={"id": "s", "version": 1}, now=200_000)
    assert m["activity"]["spin"] is True and "10 s écoulées" in m["activity"]["text"] and "2 min au plus" in m["activity"]["text"]
    assert not any(m["actions"][k]["enabled"] for k in ("open", "sync", "restart", "close"))


def test_a_ready_studio_shows_the_url_viewers_and_the_automatic_stop_countdown(tmp_path):
    m = model(tmp_path, READY, scene={"id": "s", "version": 1})
    assert m["url"] == "http://127.0.0.1:41000/" and m["label"] == "Prêt" and m["tone"] == "ok"
    assert "aucune fenêtre ouverte" in m["activity"]["text"] and "arrêt automatique dans 2 min 05 s" in m["activity"]["text"]
    assert m["actions"]["sync"]["enabled"] and m["actions"]["close"]["enabled"] and m["actions"]["restart"]["enabled"]
    assert m["actions"]["open"]["label"] == "Ouvrir le Studio"
    viewers = model(tmp_path, {**READY, "viewers": 2}, scene={"id": "s", "version": 1})
    assert "2 fenêtres ouvertes" in viewers["activity"]["text"] and "arrêt automatique" not in viewers["activity"]["text"]


def test_choosing_another_scene_while_open_switches_in_place(tmp_path):
    m = model(tmp_path, READY, scene={"id": "other", "version": 3})
    assert m["actions"]["open"]["label"] == "Afficher cette scène" and m["actions"]["open"]["enabled"] is True


def test_a_failure_is_explained_by_its_code_and_keeps_the_log(tmp_path):
    failed = {"status": "failed", "last_error_code": "remotion_studio_process_exited", "last_error_detail": "gone", "pin": {"prefab_id": "s", "version": 1},
              "diagnostics": ["line a", "line b"], "work_copy": {"modified_files": ["src/Scene.tsx"], "edits_saved": 1}, "egress_blocked": 3}
    m = model(tmp_path, failed, scene={"id": "s", "version": 1})
    assert m["tone"] == "bad" and m["error"]["code"] == "remotion_studio_process_exited" and "disparu" in m["error"]["text"]
    assert m["diagnostics"] == ["line a", "line b"] and m["edits"] == {"modified": 1, "saved": 1} and m["egressBlocked"] == 3
    assert m["actions"]["restart"]["enabled"] and m["actions"]["close"]["enabled"]
    unknown = model(tmp_path, {**failed, "last_error_code": "weird_code", "last_error_detail": "the real cause"}, scene=None)
    assert unknown["error"]["text"] == "the real cause" and unknown["error"]["code"] == "weird_code"


def test_a_stopped_studio_says_why_it_stopped(tmp_path):
    m = model(tmp_path, {"status": "stopped", "stop_reason": "idle_timeout", "diagnostics": []}, scene={"id": "s", "version": 1})
    assert "automatiquement" in m["note"]


def test_every_core_code_the_studio_can_return_has_a_french_sentence():
    from jarvis.domain.remotion_studio import StudioErrorCode
    text = MODULE.read_text(encoding="utf-8")
    for code in StudioErrorCode:
        assert code.value in text, code


def test_the_client_posts_json_to_the_six_routes_with_deadlines_and_types_its_failures(tmp_path):
    result = run_node(tmp_path, """
      const calls=[];
      const answer=(status,body)=>({ok:status<400,status,json:async()=>body});
      let next=answer(200,{studio:{status:'ready'},capability:{status:'ready'},prefabs:[{id:'a',title:'Titre',latest_version:3},{id:'b'},{latest_version:1}]});
      const client=C.createClient({fetchImpl:async(path,options)=>{calls.push([path,options.method,options.body||null]);return next}});
      const out={};
      out.scenes=await client.scenes();
      await client.write('open',{prefab_id:'a',version:3});
      await client.write('close');
      try{await client.write('install')}catch(e){out.unknown=e.message}
      next=answer(409,{error:{code:'remotion_studio_busy',message:'busy'}});
      try{await client.write('sync')}catch(e){out.code=e.code;out.status=e.status}
      next=answer(502,null);
      try{await client.studio()}catch(e){out.noJson=e.code}
      const timeouts=[];
      const hung=C.createClient({fetchImpl:(path,options)=>new Promise((_,reject)=>options.signal.addEventListener('abort',()=>reject(Object.assign(new Error('x'),{name:'AbortError'})))),
        setTimeoutImpl:(fn,ms)=>{timeouts.push(ms);setTimeout(fn,1);return 1},clearTimeoutImpl:()=>{}});
      try{await hung.write('open',{})}catch(e){out.timeout=e.code}
      out.timeouts=timeouts;
      out.calls=calls;
      return out;""")
    assert result["scenes"] == [{"id": "a", "version": 3, "label": "Titre · v3"}]
    assert result["calls"][1:3] == [["/api/local-capabilities/remotion/studio/open", "POST", '{"prefab_id":"a","version":3,"acknowledge_unsandboxed_scene":true}'],
                                    ["/api/local-capabilities/remotion/studio/close", "POST", "{}"]]
    assert result["unknown"] == "unknown Studio action" and (result["code"], result["status"]) == ("remotion_studio_busy", 409)
    assert result["noJson"] == "http_502" and result["timeout"] == "timeout" and result["timeouts"] == [160000]


def test_the_module_launches_nothing_by_itself_and_hardcodes_no_path_or_secret():
    text = MODULE.read_text(encoding="utf-8")
    browser = text[text.index("function installJarvisRemotionStudio"):]
    # Aucune écriture n'est déclenchée hors d'un clic : les seuls appels `act(` sont dans le gestionnaire de clics.
    handler = browser[browser.index("host.addEventListener('click'"):browser.index("host.addEventListener('change'")]
    outside = browser.replace(handler, "")
    assert "act('open'" not in outside and "act('restart'" not in outside and "client.write(" in outside.split("async function act")[1].split("host.addEventListener")[0]
    assert "C:\\" not in text and "node_modules" not in text and "localStorage" not in text and "Bearer" not in text


# ------------------------------------------------------------------ vraie chaîne : Control Center -> transport -> Core

async def test_the_whole_chain_reaches_a_real_core_through_the_real_transport(tmp_path):
    """Régression relevée par le harnais réel : le transport du Control Center n'a le droit de relayer qu'une liste de préfixes."""

    import socket
    from jarvis.adapters.file_local_capability_store import FileLocalCapabilityStore
    from jarvis.core.v2_app import JarvisCoreApplication
    from jarvis.protocol.server import LocalProtocolServer
    from jarvis.runtime.core_sessions import CoreSessionTransport
    from tests.fakes.remotion_scene import scene_candidate
    from tests.fakes.remotion_studio import FakeStudioRunner
    from tests.unit.test_local_capability_host import FakeRunner

    token = "k" * 48
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    core = JarvisCoreApplication(data_root=tmp_path / "data", local_capability_runner=FakeRunner(),
                                 local_capability_store=FileLocalCapabilityStore((tmp_path / "data").resolve()),
                                 remotion_studio_runner=FakeStudioRunner())
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=token)
    await server.start()
    (tmp_path / "core.token").write_text(token, encoding="utf-8")
    sessions = CoreSessionTransport(host="127.0.0.1", port=port, token_file=tmp_path / "core.token")
    client = await client_for(tmp_path, sessions)
    try:
        assert (await (await client.get("/api/local-capabilities/remotion")).json())["capability"]["status"] == "not_installed"
        assert (await (await client.get(STUDIO)).json())["studio"]["status"] == "stopped"
        publication = await core.prefabs.save(scene_candidate("presentation-studio.p000000000001.s000000000001"), actor="user")
        refused = await client.post(STUDIO + "/open", data=json.dumps({"prefab_id": publication.prefab_id, "version": publication.version, "acknowledge_unsandboxed_scene": True}))
        assert refused.status == 409 and (await refused.json())["error"]["code"] == "remotion_studio_runtime_unavailable"
        await core.local_capabilities.act("remotion", "install")
        opened = await client.post(STUDIO + "/open", data=json.dumps({"prefab_id": publication.prefab_id, "version": publication.version, "acknowledge_unsandboxed_scene": True}))
        body = await opened.json()
        assert opened.status == 200 and body["studio"]["status"] == "ready" and body["studio"]["url"].startswith("http://127.0.0.1:")
        closed = await (await client.post(STUDIO + "/close")).json()
        assert closed["studio"]["status"] == "stopped"
        assert (await client.post("/api/local-capabilities/remotion/uninstall")).status == 404, "uninstall stays an explicit Core action (Slice 20 relays only install and repair)"
    finally:
        await client.close()
        await sessions.close()
        await server.stop()
        await core.stop()


# ------------------------------------------------------------------ revue QA : confirmation, provenance, toast

def spec(tmp_path, scene, provenance, kind="open"):
    return run_node(tmp_path, f"return C.confirmSpec({json.dumps(scene)},{json.dumps(provenance)},{json.dumps(kind)});")


SCENE = {"id": "presentation-studio.p1.s1", "version": 3, "label": "Scène A · v3"}


def test_the_confirmation_names_the_risk_and_the_provenance_of_the_exact_version(tmp_path):
    own = spec(tmp_path, SCENE, {"origin": "custom", "created_by": {"actor": "user"}})
    text = json.dumps(own["lines"], ensure_ascii=False)
    assert "Sans bac à sable" in text and "Même origine que l’API du Studio" in text and "sortir de ce poste" in text
    assert "Scène A · v3" in text and "créée sur ce poste" in text and "auteur : vous" in text
    assert own["danger"] is False and own["own"] is True and "Attention" not in text
    assert own["confirmLabel"] == "Ouvrir le Studio sur cette scène" and own["cancelLabel"] == "Annuler"


@pytest.mark.parametrize("provenance,wanted", [
    ({"origin": "custom", "created_by": {"actor": "brain"}}, "un agent de Jarvis"),
    ({"origin": "fork", "created_by": {"actor": "system"}}, "Jarvis (système)"),
    ({"origin": "base_edit", "created_by": {"actor": "brain"}}, "modification d’une scène de base"),
    (None, "inconnue")])
def test_a_version_not_written_by_the_user_or_of_unknown_origin_gets_the_stronger_warning(tmp_path, provenance, wanted):
    result = spec(tmp_path, SCENE, provenance)
    text = json.dumps(result["lines"], ensure_ascii=False)
    assert result["danger"] is True and result["own"] is False and "Attention" in text and wanted in text
    assert "Ne l’ouvrez que si vous lui faites confiance" in text and "écrite par vous" not in text.replace("n’a pas été écrite par vous", "")


def test_the_card_sends_the_acknowledgement_only_after_the_dialog_and_never_without_it():
    text = MODULE.read_text(encoding="utf-8")
    browser = text[text.index("function installJarvisRemotionStudio"):]
    assert "confirmDialog" in browser and "await confirmUnsandboxed(scene,kind)" in browser
    assert browser.index("confirmUnsandboxed(scene,kind)") < browser.index("client.write(action,body)")
    assert "typeof confirmDialog!=='function'" in browser and "return false" in browser.split("typeof confirmDialog!=='function'")[1][:260], "no dialog, no launch"
    assert "ACK_FIELD" in text and "acknowledge_unsandboxed_scene" in text


def test_a_failure_toast_uses_the_fields_the_page_toast_reads(tmp_path):
    toast = run_node(tmp_path, "return C.failureToast({code:'remotion_studio_busy'},'x');")
    assert set(toast) == {"title", "sub", "kind"} and toast["kind"] == "error" and "opération" in toast["sub"]
    unknown = run_node(tmp_path, "return C.failureToast({code:'weird',message:'real cause'},'x');")
    assert unknown["sub"] == "real cause"
    page = (ROOT / "jarvis" / "runtime" / "control_center.html").read_text(encoding="utf-8")
    assert "function toast({title:heading,sub='',kind='info'" in page


def test_the_card_does_not_rebuild_its_html_each_second_nor_replace_the_live_region():
    text = MODULE.read_text(encoding="utf-8")
    browser = text[text.index("function installJarvisRemotionStudio"):]
    assert "%%ACTIVITY%%" in browser and "if(html===S.rendered)" in browser and "node.textContent=activityText" in browser
    assert "S.deferred" in browser and "rmsBusy" in browser and "setAttribute('aria-live','polite')" in browser
    assert browser.count("host.innerHTML") == 0, "never wholesale: the card element alone is replaced, and only when its structure changed"

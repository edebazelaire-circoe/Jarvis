"""Control Center : la page de la scène Remotion, ses relais et le `frame-src` de la page qui monte le cadre (Slice 10).

Acceptation (addendum PM après la Slice 06) : la page qui monte un cadre Remotion porte
`Content-Security-Policy: frame-src <origine du bac à sable>` et RIEN d'autre : ni l'origine du visualiseur, ni celle de Core.
La page principale du Control Center encadre déjà un visualiseur et ne monte JAMAIS le cadre Remotion : elle n'encadre que le
document de la scène, par son adresse exacte. Vrai Core composé avec Remotion (sans runtime installé : rien ne compile ici).
"""

from __future__ import annotations

import json
import re

import pytest

from jarvis.domain import remotion_sandbox as sb
from jarvis.protocol.client import FORWARDABLE_PREFIXES
from jarvis.protocol.remotion_player_routes import RemotionPlayerProtocolRoutes
from jarvis.runtime.control_center import READ_GUARDED_ROUTES, frame_src_policy
from jarvis.runtime.remotion_relay import GUARDED_PREFIXES, RemotionRelayRoutes, stage_csp
from tests.fakes.remotion_player_stack import RemotionStack

ID = "presentation-studio.p000000000001.s000000000001"
VISUALIZER = "http://127.0.0.1:19999"


def test_the_routes_are_guarded_on_every_method_and_relayable_and_each_has_its_core_route():
    assert GUARDED_PREFIXES == ("/remotion-stage", "/api/remotion") and set(GUARDED_PREFIXES) <= set(READ_GUARDED_ROUTES)
    assert any("/v1/remotion/player/x/1".startswith(prefix) for prefix in FORWARDABLE_PREFIXES)
    core = {(route.method, route.path) for route in RemotionPlayerProtocolRoutes(object()).routes()}
    relay = RemotionRelayRoutes(transport=lambda: None, journal=None, protocol_js="", stage_js="", page_template="")  # type: ignore[arg-type]
    mapped = {(route.method, "/v1" + route.path[len("/api"):]) for route in relay.routes() if route.path.startswith("/api/")
              and not route.path.endswith("/report")}
    assert mapped == core, "every relayed read has its Core route and none is invented"
    writes = [(route.method, route.path) for route in relay.routes() if route.method != "GET"]
    assert writes == [("POST", "/api/remotion/report")], "the only write is the page's own report, journalled here, never sent to Core"


def test_the_stage_policy_is_one_origin_or_none_and_the_main_page_never_names_the_sandbox():
    assert stage_csp("http://127.77.0.2:17655") == "frame-src http://127.77.0.2:17655" == sb.embedder_frame_src("http://127.77.0.2:17655")
    assert stage_csp(None) == "frame-src 'none'"
    main = frame_src_policy(VISUALIZER, "http://127.0.0.1:17654/remotion-stage")
    assert main == f"frame-src {VISUALIZER} http://127.0.0.1:17654/remotion-stage"
    assert "17655" not in main and "127.77.0.2" not in main, "the sandbox origin is the stage document's, not the main page's"
    assert frame_src_policy(None) == "frame-src 'none'" and frame_src_policy(VISUALIZER) == f"frame-src {VISUALIZER}"
    assert frame_src_policy(None, "http://127.0.0.1:17654/remotion-stage") == "frame-src http://127.0.0.1:17654/remotion-stage"
    assert "'self'" not in main, "a path source, not the whole origin: the frame cannot navigate to any other Control Center page"


async def test_the_stage_page_carries_frame_src_of_the_sandbox_alone_never_the_visualizer(tmp_path):
    async with RemotionStack(tmp_path, visualizer_url=VISUALIZER) as stack:
        status, headers, text = await stack.get(f"/remotion-stage?id={ID}&v=1")
        assert status == 200
        assert headers["Content-Security-Policy"] == f"frame-src {stack.sandbox_origin}", "exactly one origin and no other directive"
        assert VISUALIZER not in headers["Content-Security-Policy"] and str(stack.core_port) not in headers["Content-Security-Policy"]
        assert headers["Cache-Control"] == "no-store" and headers["Referrer-Policy"] == "no-referrer"
        assert re.findall(r"setAttribute\('sandbox',([^)]*)\)", text) == ["d.iframeAttributes.sandbox"], "the one sandbox value, from the contract"
        assert "'allow-same-origin'" not in text and '"allow-same-origin"' not in text
        config = json.loads(re.search(r"const config=(\{.*?\});", text).group(1))
        assert config == {"prefabId": ID, "version": 1, "iframeAttributes": sb.IFRAME_ATTRIBUTES}
        assert text.count("</script>") == 3 and "createStage" in text and "RemotionSandboxProtocol" in text
        # The main page frames the visualizer and the stage DOCUMENT, by its exact address; it never names the sandbox.
        status, headers, main = await stack.get("/")
        assert status == 200
        assert headers["Content-Security-Policy"] == f"frame-src {VISUALIZER} http://127.0.0.1:{stack.cc_port}/remotion-stage"
        assert stack.sandbox_origin not in headers["Content-Security-Policy"]


async def test_without_a_configured_sandbox_the_stage_page_frames_nothing_and_the_player_says_why(tmp_path):
    async with RemotionStack(tmp_path, configure_sandbox=False) as stack:
        status, headers, _ = await stack.get(f"/remotion-stage?id={ID}&v=1")
        assert status == 200 and headers["Content-Security-Policy"] == "frame-src 'none'"
        status, _, text = await stack.get(f"/api/remotion/player/{ID}/1")
        body = json.loads(text)
        assert status == 409 and body["error"]["code"] == "presentation_studio_engine_unavailable"
        assert "no Remotion adapter" in body["error"]["message"] or "sandbox" in body["error"]["message"]
        status, _, text = await stack.get("/api/remotion/sandbox")
        assert status == 200 and json.loads(text)["engine"]["ready"] is False


async def test_an_installed_runtime_missing_is_a_typed_409_with_its_repair_through_the_relay(tmp_path):
    async with RemotionStack(tmp_path) as stack:
        status, _, text = await stack.get(f"/api/remotion/player/{ID}/1")
        body = json.loads(text)["error"]
        assert status == 409 and body["code"] == "presentation_studio_engine_unavailable"
        assert "not_installed" in body["message"] and "Repair" in body["message"] and "html" not in body["message"].lower()
        status, _, text = await stack.get("/api/remotion/sandbox")
        engine = json.loads(text)["engine"]
        assert status == 200 and engine["ready"] is False and engine["repair"] and "not_installed" in engine["reason"]


@pytest.mark.parametrize("query", ["", "?id=BAD ID&v=1", "?id=" + "presentation-studio.p000000000001.s000000000001" + "&v=x",
                                   "?id=jarvis.counter&v=1&extra=1", "?id=jarvis.counter&v=12345", "?v=1"])
async def test_a_stage_page_names_a_prefab_and_a_version_and_nothing_else(tmp_path, query):
    async with RemotionStack(tmp_path) as stack:
        status, _, text = await stack.get("/remotion-stage" + query)
        assert status == 400 and json.loads(text)["error"]["code"] == "invalid_request"


@pytest.mark.parametrize("path", ["/remotion-stage?id=jarvis.counter&v=1", "/api/remotion/sandbox", f"/api/remotion/player/{ID}/1"])
@pytest.mark.parametrize("headers", [{"Origin": "null"}, {"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}, {"Host": "evil.example"}])
async def test_a_sandbox_frame_or_a_foreign_origin_can_neither_read_nor_load_the_stage(tmp_path, path, headers):
    async with RemotionStack(tmp_path) as stack:
        status, _, text = await stack.get(path, headers=headers)
        assert status == 403 and json.loads(text)["code"] == "forbidden_origin"


async def test_the_page_reports_are_journalled_with_closed_fields_and_bounded_values(tmp_path):
    import aiohttp
    async with RemotionStack(tmp_path) as stack:
        async with aiohttp.ClientSession() as http:
            async def post(body, raw=None):
                async with http.post(stack.page_url + "api/remotion/report", data=raw if raw is not None else json.dumps(body),
                                     headers={"Content-Type": "application/json"}) as response:
                    return response.status

            assert await post({"event": "killed", "reason": "unresponsive", "prefab_id": ID, "version": 1, "detail": "9001",
                               "secret": "token-123", "message": "x" * 500}) == 200
            assert await post({"event": "ready", "prefab_id": ID, "version": 1}) == 200
            assert await post({"event": "failed", "code": "compile_source_error", "diagnostics": 2}) == 200
            assert await post({"event": "nope"}) == 400
            assert await post(None, raw="not json") == 400
            assert await post({"event": "ready", "pad": "x" * 5000}) == 413
        rows = [row for row in stack.trace() if row["kind"].startswith("remotion.")]
        kinds = [row["kind"] for row in rows]
        assert "remotion.sandbox.killed" in kinds and "remotion.stage.ready" in kinds and "remotion.stage.failed" in kinds
        killed = next(row for row in rows if row["kind"] == "remotion.sandbox.killed")
        assert killed["level"] == "warning" and killed["data"]["reason"] == "unresponsive"
        assert "secret" not in killed["data"] and "token-123" not in json.dumps(rows) and len(killed["data"]["message"]) <= 200

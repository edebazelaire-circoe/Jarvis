"""Le Control Center refuse une page d'un AUTRE service local (autre port de la boucle locale) : Slice 11, B1 de la revue QA.

Une scène qui tourne dans l'onglet du Studio Remotion (127.0.0.1:<port Studio>) pouvait envoyer un `fetch(..., {mode: "no-cors"})`
modifiant au Control Center : l'origine était de boucle locale, donc acceptée. Désormais : l'`Origin` doit porter le port du Control
Center lui-même, et une requête modifiante `Sec-Fetch-Site: same-site` ou `cross-site` est refusée.
"""

from __future__ import annotations

from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.runtime.control_center import _foreign_port_refusal, _loopback_refusal
from tests.unit.test_control_center_mcp_plugins_api import RecordingCore, _center

GUARDED_WRITE = "/api/local-capabilities/remotion/studio/open"
UNGUARDED_WRITE = "/api/live/stop"


def test_the_pure_refusal_distinguishes_the_control_center_port_from_any_other_local_service():
    host = "127.0.0.1:17654"
    assert _loopback_refusal("http://127.0.0.1:55555", host, "same-site") is not None, "the exact case QA measured"
    assert _loopback_refusal("http://127.0.0.1:55555", host, "same-origin") is not None
    assert _loopback_refusal("http://127.0.0.1:17654", host, "same-origin", mutating=True) is None
    assert _loopback_refusal("http://127.0.0.1:17654", host, None, mutating=True) is None
    assert _loopback_refusal(None, host, None, mutating=True) is None, "a script or console client has no Origin"
    assert _loopback_refusal("http://127.0.0.1:17654", host, "same-site", mutating=True) is not None
    assert _loopback_refusal("http://127.0.0.1:17654", host, "same-site", mutating=False) is None
    assert _loopback_refusal("http://localhost:17654", "localhost:17654", "same-origin", mutating=True) is None
    assert _loopback_refusal("http://[::1]:17654", "[::1]:17654", "same-origin") is None
    assert _loopback_refusal("http://127.0.0.1:17654", "127.0.0.1:17655", None) is not None
    assert _loopback_refusal("http://127.0.0.1", "127.0.0.1:80", None) is None
    assert _foreign_port_refusal("http://127.0.0.1:99999", "127.0.0.1:99999") is not None


async def _client(tmp_path):
    client = TestClient(TestServer(_center(tmp_path, RecordingCore((200, {"studio": {"status": "stopped"}})))._app))
    await client.start_server()
    return client


@pytest.mark.parametrize("path", [GUARDED_WRITE, "/api/local-capabilities/remotion/studio/close", "/api/mcp/plugins", UNGUARDED_WRITE])
async def test_a_page_served_by_another_local_port_cannot_drive_a_mutating_route(tmp_path, path):
    client = await _client(tmp_path)
    try:
        cases = [{"Origin": "http://127.0.0.1:55555"}, {"Origin": "http://127.0.0.1:55555", "Sec-Fetch-Site": "same-site"}]
        if path != UNGUARDED_WRITE:  # les routes gardées refusent aussi l'en-tête seul ; les autres jugent l'`Origin` (un POST de navigateur en porte un)
            cases += [{"Sec-Fetch-Site": "same-site"}, {"Sec-Fetch-Site": "cross-site"}]
        for headers in cases:
            response = await client.post(path, headers=headers, data=b"{}")
            assert response.status == 403, (path, headers, response.status)
    finally:
        await client.close()


async def test_the_real_control_center_page_still_works_with_its_own_origin_and_without_one(tmp_path):
    client = await _client(tmp_path)
    try:
        own = f"http://127.0.0.1:{client.port}"
        ok = await client.post(GUARDED_WRITE, headers={"Origin": own, "Sec-Fetch-Site": "same-origin"}, data=b"{}")
        assert ok.status == 200
        assert (await client.post(GUARDED_WRITE, data=b"{}")).status == 200, "no Origin: a console or script client"
        assert (await client.get("/api/local-capabilities/remotion/studio", headers={"Origin": own, "Sec-Fetch-Site": "same-origin"})).status == 200
        assert (await client.get("/api/local-capabilities/remotion/studio", headers={"Origin": "http://127.0.0.1:55555"})).status == 403
        assert (await client.get("/api/local-capabilities/remotion/studio", headers={"Sec-Fetch-Site": "same-site"})).status == 200, "a plain read stays blind"
    finally:
        await client.close()


async def test_a_same_site_navigation_to_a_guarded_route_is_refused_but_the_page_itself_is_not(tmp_path):
    """P3 : une page d'un autre service local qui NAVIGUE vers une route gardée consommerait un état ; la page du Control Center est `same-origin`."""

    client = await _client(tmp_path)
    try:
        route = "/api/local-capabilities/remotion/studio"
        assert (await client.get(route, headers={"Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "navigate"})).status == 403
        assert (await client.get(route, headers={"Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "no-cors"})).status == 200, "a blind subresource read"
        assert (await client.get(route, headers={"Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors"})).status == 200
        assert (await client.get(route, headers={"Sec-Fetch-Site": "none", "Sec-Fetch-Mode": "navigate"})).status == 200, "the user typing the address"
        assert (await client.get(route, headers={"Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "navigate"})).status == 200
        assert (await client.get("/api/fullscreen/commands?wait_s=0", headers={"Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "navigate"})).status == 403
    finally:
        await client.close()


def test_the_pure_refusal_names_the_navigation_case():
    host = "127.0.0.1:17654"
    assert _loopback_refusal(None, host, "same-site", fetch_mode="navigate") is not None
    assert _loopback_refusal(None, host, "same-origin", fetch_mode="navigate") is None
    assert _loopback_refusal(None, host, "none", fetch_mode="navigate") is None
    assert _loopback_refusal(None, host, "same-site", fetch_mode="cors") is None

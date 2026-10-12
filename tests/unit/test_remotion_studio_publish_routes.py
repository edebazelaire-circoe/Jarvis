"""`POST /v1/local-capabilities/remotion/studio/publish` sur un vrai Core, son relais, et qui peut publier (native-studio-playback-fix Slice 12).

Vrai Core (`JarvisCoreApplication`, vrai Studio de présentations, faux runner du Studio) : confirmation obligatoire, corps exact, enveloppe
d'erreur qui garde le code de la variante (`publish_code`), `discard_unpublished` sur `open`. Relais du Control Center : seulement depuis
la page (`Sec-Fetch-Site: same-origin`), délai de 150 s. Garde statique : aucun chemin du cerveau, d'un outil MCP ou d'un agent n'envoie
`confirm_publish` ni n'appelle `studio/publish` ; la commande de la page (voix, agents) n'a aucune action de publication.
"""

from __future__ import annotations

from pathlib import Path
import socket

import aiohttp
from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.adapters.file_local_capability_store import FileLocalCapabilityStore
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.remotion_studio import StudioPin, StudioState
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime.remotion_studio_relay import START_TIMEOUT_S
from tests.fakes.remotion_studio import FakeStudioRunner
from tests.unit.test_control_center_mcp_plugins_api import RecordingCore, _center
from tests.unit.test_local_capability_host import FakeRunner

pytestmark = pytest.mark.asyncio

TOKEN = "t" * 48
STUDIO = "/v1/local-capabilities/remotion/studio"
PIN = StudioPin("presentation-studio.p000000000001.s000000000001", 1)
ROOT = Path(__file__).resolve().parents[2] / "jarvis"


@pytest.fixture
async def stack(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    studio = FakeStudioRunner()
    core = JarvisCoreApplication(data_root=tmp_path, local_capability_runner=FakeRunner(),
                                 local_capability_store=FileLocalCapabilityStore(tmp_path.resolve()), remotion_studio_runner=studio)
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
    await server.start()
    try:
        yield core, f"http://127.0.0.1:{port}", studio
    finally:
        await server.stop()
        await core.stop()


async def call(base, method, path, **kwargs):
    async with aiohttp.ClientSession() as session:
        async with session.request(method, base + path, headers={"Authorization": f"Bearer {TOKEN}"}, **kwargs) as response:
            return response.status, await response.json(content_type=None)


def body(**changes):
    return {"presentation_id": "prs_000000000001", "variant_id": "var_000000000001", "scene_id": "pss_000000000001",
            "base": PIN.to_dict(), "digest": "0" * 64, "confirm_publish": True, **changes}


async def test_publish_needs_the_confirmation_and_an_exact_body(stack):
    _core, base, studio = stack
    status, answer = await call(base, "POST", STUDIO + "/publish", json={k: v for k, v in body().items() if k != "confirm_publish"})
    assert status == 400 and answer["error"]["code"] == "remotion_studio_invalid"
    status, answer = await call(base, "POST", STUDIO + "/publish", json=body(confirm_publish=False))
    assert status == 400 and answer["error"]["code"] == "remotion_studio_publish_confirm_required"
    for extra in ({"allowed_imports": ["zod"]}, {"actor": "brain"}, {"trust": "widened"}, {"digest": "not-a-digest"}):
        status, answer = await call(base, "POST", STUDIO + "/publish", json=body(**extra))
        assert status == 400 and answer["error"]["code"] == "remotion_studio_invalid", extra
    status, answer = await call(base, "POST", STUDIO + "/publish?x=1", json=body())
    assert status == 400
    assert "workspace_diff" not in studio.calls, "nothing was read before the body was accepted"


async def test_without_a_workspace_there_is_nothing_to_publish(stack):
    _core, base, _studio = stack
    status, answer = await call(base, "POST", STUDIO + "/publish", json=body())
    assert status == 409 and answer["error"]["code"] == "remotion_studio_publish_nothing"


async def test_a_base_the_page_did_not_see_and_an_unknown_scene_are_typed_refusals_carrying_their_details(stack):
    core, base, studio = stack
    studio.state = StudioState(pin=PIN).to_payload()
    core.remotion_studio._state = None  # as a fresh Core would: the state file is read again
    studio.work = studio.base = {"src/Scene.tsx": b"x", "studio-root.tsx": b"r", "package.json": b"{}"}
    studio.work = {**studio.work, "src/Scene.tsx": b"y"}
    status, answer = await call(base, "POST", STUDIO + "/publish", json=body(base={"prefab_id": PIN.prefab_id, "version": 2}))
    assert status == 409 and answer["error"]["code"] == "remotion_studio_publish_base_mismatch" and answer["error"]["base"] == PIN.to_dict()
    status, answer = await call(base, "POST", STUDIO + "/publish", json=body())
    assert status == 409 and answer["error"]["code"] == "remotion_studio_publish_listing_changed", "not the listing the page showed"
    assert answer["error"]["count"] == 1 and answer["error"]["files"] == ["src/Scene.tsx"]
    _status, view = await call(base, "GET", STUDIO)
    shown = view["studio"]["work_copy"]["digest"]
    assert len(shown) == 64 and view["studio"]["work_copy"]["modified_files"] == ["src/Scene.tsx"]
    status, answer = await call(base, "POST", STUDIO + "/publish", json=body(digest=shown))
    assert answer["error"]["code"] == "remotion_studio_publish_refused" and status in (400, 404)
    assert answer["error"]["publish_code"].startswith("presentation_studio_"), "the variant's own code is kept, never relabelled"


async def test_open_accepts_the_confirmed_discard_flag_only_as_true(stack):
    _core, base, _studio = stack
    status, answer = await call(base, "POST", STUDIO + "/open", json={"prefab_id": PIN.prefab_id, "version": 1,
                                                                    "acknowledge_unsandboxed_scene": True, "discard_unpublished": "yes"})
    assert status == 400 and answer["error"]["code"] == "remotion_studio_invalid"


async def test_the_relay_forwards_publish_only_from_the_page_with_its_deadline(tmp_path):
    core = RecordingCore((200, {"studio": {"status": "stopped"}, "publish": {"status": "reloaded"}}))
    client = TestClient(TestServer(_center(tmp_path, core)._app))
    await client.start_server()
    try:
        path = "/api/local-capabilities/remotion/studio/publish"
        payload = b'{"presentation_id":"prs_1"}'
        for headers in ({}, {"Sec-Fetch-Site": "same-site"}, {"Sec-Fetch-Site": "none"}, {"Sec-Fetch-Site": "cross-site"},
                        {"Origin": "https://evil.example", "Sec-Fetch-Site": "same-origin"}):
            response = await client.post(path, data=payload, headers=headers)
            assert response.status == 403, headers
        assert core.calls == []
        response = await client.post(path, data=payload, headers={"Sec-Fetch-Site": "same-origin"})
        assert response.status == 200 and (await response.json())["publish"]["status"] == "reloaded"
        [forwarded] = core.calls
        assert (forwarded["path"], forwarded["body"], forwarded["timeout_s"]) == ("/v1/local-capabilities/remotion/studio/publish", payload, START_TIMEOUT_S)
    finally:
        await client.close()


async def test_no_brain_mcp_or_agent_path_can_publish_a_workspace():
    """Only the Core route, the relay, the Studio service and the two user doors (card core, Variants door) name the publish verb."""

    allowed = {"protocol/remotion_studio_routes.py", "core/remotion_studio_publish.py", "runtime/remotion_studio_relay.py", "domain/remotion_studio_workspace.py",
               "runtime/control_center_remotion_studio.js", "runtime/control_center_presentation_studio_explorer_remotion.js"}
    users = {path.relative_to(ROOT).as_posix() for path in ROOT.rglob("*") if path.suffix in {".py", ".js", ".html", ".cjs", ".mjs"}
             and any(token in path.read_text(encoding="utf-8", errors="replace") for token in ("studio/publish", "confirm_publish", "CONFIRM_PUBLISH"))}
    assert users <= allowed, sorted(users - allowed)
    explorer = (ROOT / "runtime" / "control_center_presentation_studio_explorer.js").read_text(encoding="utf-8")
    commands = explorer[explorer.index("handleCommand:async(command)=>{"):explorer.index("destroy(){", explorer.index("handleCommand:async(command)=>{"))]
    assert "publish" not in commands.lower() and "remotion" not in commands.lower(), "the page command channel (voice, agents) cannot publish"
    for path in ROOT.rglob("*.py"):
        name = path.relative_to(ROOT).as_posix()
        if "mcp" in name or "tool_brain" in name or name.startswith(("brain", "core/brain", "core/tool")):
            text = path.read_text(encoding="utf-8", errors="replace")
            assert "publish_workspace" not in text and "studio/publish" not in text and "discard_unpublished" not in text, name

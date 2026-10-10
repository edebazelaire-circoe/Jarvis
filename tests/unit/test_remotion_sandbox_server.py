"""L'écouteur du bac à sable Remotion (Slice 10) : un second socket de boucle locale, ouvert à la demande, qui ne sert que
`SandboxResponder.respond`. Vrai `aiohttp` sur `127.77.0.2`, contenu de compilation factice sur disque.
Contrat : `docs/remotion-isolation.md` § 4 et § 10.
"""

from __future__ import annotations

from pathlib import Path
import socket

import aiohttp
import pytest

from jarvis.domain import remotion_sandbox as sb
from jarvis.domain.remotion_compile import CompileErrorCode, RemotionCompileError
from jarvis.runtime.remotion_sandbox_server import RemotionSandboxServer, RemotionSandboxSettings, SandboxBindError

HOST = "127.77.0.2"
SCENE_KEY, HOST_KEY = "scene-" + "a" * 32, "host-" + "b" * 32


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind((HOST, 0))
        return sock.getsockname()[1]


@pytest.fixture
def served(tmp_path: Path):
    files = {(SCENE_KEY, "scene.js"): b"var JarvisScene={component:function(){}};", (HOST_KEY, "host.js"): b"/* host */",
             (SCENE_KEY, "public/dot.png"): b"\x89PNG\r\n\x1a\n" + b"0" * 64}
    for (key, name), data in files.items():
        path = tmp_path / key / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def resolve(key: str, relative: str) -> Path:
        if (key, relative) not in files:
            raise RemotionCompileError(CompileErrorCode.CACHE_IO, f"{key} has no compiled file {relative}")
        return tmp_path / key / relative

    port = free_port()
    settings = RemotionSandboxSettings(HOST, port, "http://127.0.0.1:17654")
    traces: list[tuple[str, dict]] = []
    server = RemotionSandboxServer(settings, resolve, trace=lambda kind, message, data: traces.append((kind, data)))
    return server, settings, traces


def test_the_settings_refuse_an_origin_that_shares_the_host_of_the_embedder():
    with pytest.raises(sb.SandboxContractError):
        RemotionSandboxSettings("127.0.0.1", 17655, "http://127.0.0.1:17654")
    with pytest.raises(ValueError):
        RemotionSandboxSettings(HOST, 70000, "http://127.0.0.1:17654")
    assert RemotionSandboxSettings(HOST, 17655, "http://127.0.0.1:17654").origin == "http://127.77.0.2:17655"


async def test_nothing_listens_until_a_scene_is_played_and_stop_frees_the_port(served):
    server, settings, traces = served
    assert server.origin is None and server.configured_origin == settings.origin
    with pytest.raises(OSError):
        with socket.create_connection((HOST, settings.port), timeout=0.5):
            pass
    assert await server.ensure_started() == settings.origin and server.origin == settings.origin
    assert await server.ensure_started() == settings.origin, "idempotent"
    with socket.create_connection((HOST, settings.port), timeout=2):
        pass
    await server.stop()
    assert server.origin is None
    with pytest.raises(OSError):
        with socket.create_connection((HOST, settings.port), timeout=0.5):
            pass
    assert [kind for kind, _ in traces] == ["remotion.sandbox.listening"]


async def test_it_serves_the_page_and_the_files_with_the_exact_headers_and_nothing_else(served):
    server, settings, _ = served
    await server.ensure_started()
    try:
        async with aiohttp.ClientSession() as http:
            async with http.get(f"{settings.origin}/page/{SCENE_KEY}/{HOST_KEY}") as page:
                text = await page.text()
                assert page.status == 200 and "frame-ancestors http://127.0.0.1:17654" in page.headers["Content-Security-Policy"]
                assert page.headers["Content-Security-Policy"].endswith("sandbox allow-scripts")
                assert "script-src 'nonce-" in page.headers["Content-Security-Policy"] and "unsafe-eval" not in page.headers["Content-Security-Policy"]
                assert "Set-Cookie" not in page.headers and "Authorization" not in page.headers
                assert f"/f/{SCENE_KEY}/scene.js" in text and 'integrity="sha384-' in text
            async with http.get(f"{settings.origin}/f/{SCENE_KEY}/scene.js") as script:
                assert script.status == 200 and script.headers["Access-Control-Allow-Origin"] == "*"
                assert script.headers["Content-Type"].startswith("text/javascript") and script.headers["X-Content-Type-Options"] == "nosniff"
                assert "immutable" in script.headers["Cache-Control"]
            async with http.get(f"{settings.origin}/f/{SCENE_KEY}/public/dot.png") as image:
                assert image.status == 200 and "Access-Control-Allow-Origin" not in image.headers and image.headers["Content-Type"] == "image/png"
            async with http.get(f"{settings.origin}/f/{SCENE_KEY}/public/dot.png", headers={"Range": "bytes=0-7"}) as part:
                assert part.status == 206 and len(await part.read()) == 8
            async with http.head(f"{settings.origin}/f/{SCENE_KEY}/scene.js") as head:
                assert head.status == 200 and int(head.headers["Content-Length"]) > 0
            for path in ("/", "/f/scene-" + "c" * 32 + "/scene.js", f"/f/{SCENE_KEY}/compile.json", f"/f/{SCENE_KEY}/../x",
                         "/v1/health", "/api/status"):
                async with http.get(f"{settings.origin}{path}") as other:
                    assert other.status == 404, path
            async with http.post(f"{settings.origin}/page/{SCENE_KEY}/{HOST_KEY}", data=b"x") as posted:
                assert posted.status == 405
    finally:
        await server.stop()


async def test_a_request_for_another_host_name_is_refused_even_on_the_right_socket(served):
    server, settings, _ = served
    await server.ensure_started()
    try:
        async with aiohttp.ClientSession() as http:
            async with http.get(f"{settings.origin}/page/{SCENE_KEY}/{HOST_KEY}", headers={"Host": f"evil.test:{settings.port}"}) as rebound:
                assert rebound.status == 421, "DNS rebinding: the Host must be the sandbox's own"
    finally:
        await server.stop()


async def test_a_busy_port_is_a_typed_failure_with_the_real_cause_and_a_trace(served):
    server, settings, traces = served
    with socket.socket() as holder:
        holder.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1) if hasattr(socket, "SO_EXCLUSIVEADDRUSE") else None
        holder.bind((HOST, settings.port))
        holder.listen()
        with pytest.raises(SandboxBindError) as caught:
            await server.ensure_started()
    assert str(settings.port) in str(caught.value) and server.origin is None
    assert traces and traces[0][0] == "remotion.sandbox.bind_failed"
    assert await server.ensure_started() == settings.origin, "once the port is free the next attempt succeeds"
    await server.stop()

"""Isolation d'une scène Remotion non fiable, couches statique et contrat d'exécution (Slice 06).

Contrat : `docs/remotion-isolation.md`. Les gardes statiques refusent le corpus hostile (`tests/fakes/remotion_hostile.py`) ; le
contrat d'exécution (CSP, en-têtes, chemins, page, route) est testé comme fonctions pures ; la preuve dans un vrai Chrome est
`scripts/remotion_isolation_harness.py` (jointe en preuve, pas un test automatique).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.adapters.file_prefab_library import FilePrefabLibrary
from jarvis.core.prefab_service import PrefabService
from jarvis.domain import remotion_isolation as iso
from jarvis.domain import remotion_sandbox as sb
from jarvis.domain import remotion_source as rs
from jarvis.domain.prefab import PrefabDefinitionError, parse_candidate
from jarvis.ports.prefabs import PrefabStoreError, PrefabStoreErrorCode as C
from jarvis.runtime.remotion_sandbox import SandboxResponder, load_bootstrap
from tests.fakes.prefabs import install_version
from tests.fakes.remotion_hostile import SAMPLES
from tests.fakes.remotion_scene import PNG_1X1, scene_candidate, scene_files

SCENE = "presentation-studio.p000000000001.s000000000009"
SCENE_KEY = "scene-" + "a" * 32
HOST_KEY = "host-" + "b" * 32


def module_findings(text: str) -> set[str]:
    return {finding.split(": ", 2)[1].split(" - ")[0] for finding in iso.scan_module("src/Scene.tsx", text)}


# ------------------------------------------------------------------ gardes statiques

def test_the_guard_is_installed_where_slice_05_left_the_hook():
    assert iso.isolation_guard in rs.SOURCE_GUARDS


def test_the_benign_sample_scene_passes_every_rule():
    for path, text in scene_files().items():
        if isinstance(text, str):
            assert iso.scan_module(path, text) == []
        else:
            assert iso.scan_asset(path, text) == []


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda s: s.id)
def test_every_hand_written_hostile_scene_is_refused_with_its_rule(sample):
    files = sample.source("direct")
    found = module_findings(files["src/Scene.tsx"])
    for path, data in files.items():
        if path.startswith("public/"):
            found |= {f.split(": ", 2)[1].split(" - ")[0] for f in iso.scan_asset(path, data)}
    assert set(sample.static_codes) <= found, (sample.id, found)


@pytest.mark.parametrize("sample", [s for s in SAMPLES if s.id != "svg_script"], ids=lambda s: s.id)
def test_the_evasive_versions_pass_the_static_layer_which_is_why_the_runtime_layer_exists(sample):
    # Documents the limit instead of hiding it: a regex filter is not a boundary (docs/remotion-isolation.md, section 3).
    assert module_findings(sample.source("evasive")["src/Scene.tsx"]) == set(), sample.id


@pytest.mark.parametrize("text,code", [
    ("fetch('/x')", "network_api"), ("const w = new WebSocket(u);", "network_api"), ("navigator.sendBeacon(u, d)", "realm_access"),
    ("eval(code)", "code_execution"), ("new Function('return 1')", "code_execution"),
    ("x.constructor.constructor('return this')()", "constructor_chain"), ("const m = await import('./x')", "dynamic_import"),
    ("setTimeout('boom()', 10)", "string_timer"), ("new Worker(u)", "worker_or_channel"), ("w.postMessage(1)", "worker_or_channel"),
    ("window.localStorage", "realm_access"), ("const d = document;", "realm_value"), ("foo(window)", "realm_value"),
    ("el.contentWindow", "realm_property"), ("open(url)", "popup_or_dialog"), ("<iframe src={u} />", "markup_tag"),
    ("<script>x</script>", "markup_tag"), ('el.innerHTML = "<img onerror=\\"x\\">"', "inline_handler_string"),
    ("srcDoc={html}", "srcdoc"), ("const u = 'javascript:alert(1)'", "active_url_scheme"),
    ('<img src="https://evil.example/x.png" />', "external_resource"), ("style={{backgroundImage: 'url(//evil/x)'}}", "external_resource"),
    ("G['fe' + 'tch'](u)", "obfuscated_name"), ("atob('ZmV0Y2g=')", "obfuscated_name"), ("while (true) {}", "unbounded_loop"),
    ("for (;;) {}", "unbounded_loop"),
])
def test_each_rule_fires_on_its_form(text, code):
    assert code in module_findings(text)


@pytest.mark.parametrize("text", [
    "const style = {top: 10, left: 20};",                      # CSS keys are not the global
    "const title = 'Le document principal, avec un parent.';",  # prose is not code
    "const top = 5; const parent = {a: 1};",                   # local names are fine until they are used as the global
    "const frames = items.map((x) => x * 2); frames.length;",
    "const x: Array<object> = [];",                            # TS generics are not elements
    "export class A { constructor(public v: number) {} }",
    "const once = 'a'; const only = \"b\"; const online = `c`;",
    "if (typeof window !== 'undefined') {}",                  # typeof guard alone is not an access
    "const open = true; const isOpen = open;",
    "const s = useCurrentFrame(); const t = interpolate(s, [0, 30], [0, 1]);",
    "const color = props.palette['accent' ];",
    "// we never fetch anything here",
])
def test_honest_code_and_prose_are_not_refused(text):
    assert module_findings(text) == set(), text


def test_json_modules_are_not_scanned_and_long_lines_are_refused():
    assert iso.scan_module("src/theme.json", '{"fetch": "eval(x)"}') == []
    assert "a line has" in iso.scan_module("src/a.ts", "x" * (iso.MAX_LINE_CHARS + 1))[0]


def test_findings_name_the_file_and_the_line_and_are_capped():
    text = "const a = 1;\nconst b = 2;\nfetch('/x');\n"
    assert iso.scan_module("src/a.ts", text)[0].startswith("src/a.ts:3: network_api - ")
    noisy = "\n".join(["fetch(1); eval(2); window.x; import('y'); open(z); while(true){}"] * 3)
    assert len(iso.scan_module("src/a.ts", noisy)) == iso.MAX_FINDINGS_PER_FILE


# ------------------------------------------------------------------ assets

EVIL_SVGS = {
    "script": '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    "handler": '<svg xmlns="http://www.w3.org/2000/svg" onload="x()"><rect/></svg>',
    "foreign": '<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><div/></foreignObject></svg>',
    "javascript_url": '<svg xmlns="http://www.w3.org/2000/svg"><a href="javascript:alert(1)"><rect/></a></svg>',
    "external_image": '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://evil.example/x.png"/></svg>',
    "external_xlink": '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"><use xlink:href="//evil/x.svg#a"/></svg>',
    "css_import": '<svg xmlns="http://www.w3.org/2000/svg"><style>@import url(https://evil.example/a.css);</style></svg>',
    "css_url": '<svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:url(https://evil.example/p)"/></svg>',
    "entity": '<!DOCTYPE svg [<!ENTITY a "aaaa">]><svg xmlns="http://www.w3.org/2000/svg">&a;</svg>',
    "smil": '<svg xmlns="http://www.w3.org/2000/svg"><a><set attributeName="href" to="javascript:alert(1)"/></a></svg>',
    "data_html": '<svg xmlns="http://www.w3.org/2000/svg"><a href="data:text/html;base64,PHNjcmlwdD4="/></svg>',
}


@pytest.mark.parametrize("name", EVIL_SVGS)
def test_an_svg_with_active_content_is_refused_not_cleaned(name):
    assert iso.scan_asset("public/a.svg", EVIL_SVGS[name].encode()), name


def test_a_clean_svg_with_local_references_is_accepted():
    clean = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 10 10">'
             '<defs><linearGradient id="g"><stop offset="0" stop-color="#fff"/></linearGradient></defs>'
             '<style>.a{fill:url(#g)}</style><rect class="a" width="10" height="10"/><use xlink:href="#g"/>'
             '<image href="sibling.png"/><image href="data:image/png;base64,AAAA"/></svg>')
    assert iso.scan_asset("public/a.svg", clean.encode()) == []


def test_the_asset_header_must_match_the_extension():
    assert iso.scan_asset("public/a.png", PNG_1X1) == []
    assert "asset_signature" in iso.scan_asset("public/a.png", b"<html><script>x</script></html>")[0]
    assert "asset_signature" in iso.scan_asset("public/a.jpg", PNG_1X1)[0]
    assert iso.scan_asset("public/a.woff2", b"wOF2....") == [] and iso.scan_asset("public/a.mp4", b"\x00\x00\x00\x18ftypmp42") == []
    assert iso.scan_asset("public/a.svg", b"\xff\xfe") and iso.scan_asset("public/a.svg", b"<html></html>")


# ------------------------------------------------------------------ branchement (publication et relecture)

def hostile_files(**changes):
    return {**scene_files(), **changes}


def test_publication_refuses_a_hostile_candidate_with_the_file_and_the_line():
    with pytest.raises(PrefabDefinitionError) as caught:
        parse_candidate(scene_candidate(files=hostile_files(**{"src/lib/Title.tsx": "export const Title = () => {\n fetch('/x');\n return null;\n};\n"})))
    assert "src/lib/Title.tsx:2: network_api" in "; ".join(caught.value.errors)


def test_publication_refuses_an_active_svg_and_a_disguised_asset():
    for name, data in (("public/evil.svg", EVIL_SVGS["script"].encode()), ("public/photo.png", b"<html>not a png</html>")):
        with pytest.raises(PrefabDefinitionError):
            parse_candidate(scene_candidate(files=hostile_files(**{name: data})))


async def test_a_version_published_before_a_guard_is_refused_on_reread_and_its_bytes_are_left_alone(tmp_path, monkeypatch):
    package, data = tmp_path / "package", tmp_path / "data"
    package.mkdir(), data.mkdir()
    install_version(package, "jarvis.counter", title="Base counter")
    service = PrefabService(FilePrefabLibrary(package, data), clock=lambda: datetime(2026, 11, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(rs, "SOURCE_GUARDS", ())  # the world before the guard existed
    await service.save(scene_candidate(SCENE, files=hostile_files(**{"src/lib/Title.tsx": "export const Title = () => { eval('1'); return null; };\n"})), actor="user")
    monkeypatch.undo()
    reopened = PrefabService(FilePrefabLibrary(package, data))
    await reopened.start()
    folder = data / "prefabs" / SCENE / "1"
    before = {p.name: p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    with pytest.raises(PrefabStoreError) as caught:
        await reopened.remotion_source(SCENE, 1)
    assert caught.value.code is C.INVALID_DEFINITION and "code_execution" in " ".join(caught.value.errors)
    assert before == {p.name: p.read_bytes() for p in folder.rglob("*") if p.is_file()}  # preserved for diagnosis, never rewritten
    assert (await reopened.get(SCENE, 1)).entry is not None  # the catalogue still lists it


# ------------------------------------------------------------------ contrat d'exécution : en-têtes

EMBEDDER, SANDBOX = "http://127.77.0.1:17653", "http://127.77.0.2:18200"
NONCE = "abcdefghijklmnopqrstuv"


def directives(csp: str) -> dict[str, str]:
    return {part.split(" ", 1)[0]: part.split(" ", 1)[1] if " " in part else "" for part in csp.split("; ")}


def test_the_page_csp_is_closed_by_default_and_carries_the_sandbox_directive():
    d = directives(sb.page_csp(NONCE, EMBEDDER))
    assert d["default-src"] == "'none'" and d["connect-src"] == "'none'" and d["frame-src"] == "'none'"
    assert d["worker-src"] == "'none'" and d["object-src"] == "'none'" and d["base-uri"] == "'none'" and d["form-action"] == "'none'"
    assert d["script-src"] == f"'nonce-{NONCE}'"  # no 'unsafe-inline', no 'unsafe-eval', no host
    assert "unsafe-eval" not in sb.page_csp(NONCE, EMBEDDER) and "*" not in sb.page_csp(NONCE, EMBEDDER)
    assert d["img-src"] == "'self' data:" and d["media-src"] == "'self'" and d["font-src"] == "'self'"
    assert d["frame-ancestors"] == EMBEDDER and d["sandbox"] == "allow-scripts"


def test_the_sandbox_value_never_grants_the_dangerous_tokens():
    assert sb.SANDBOX_VALUE == "allow-scripts" and not set(sb.SANDBOX_VALUE.split()) & sb.FORBIDDEN_SANDBOX_TOKENS
    assert sb.IFRAME_ATTRIBUTES["sandbox"] == "allow-scripts" and sb.IFRAME_ATTRIBUTES["allow"] == ""


@pytest.mark.parametrize("nonce", ["", "short", "x" * 65, "has space has space!!", "a;b" * 8])
def test_a_malformed_nonce_never_reaches_a_header(nonce):
    with pytest.raises(sb.SandboxContractError):
        sb.page_csp(nonce, EMBEDDER)


@pytest.mark.parametrize("origin", ["", "ftp://x", "http://u:p@host", "http://host/path", "http://h?q=1", "http://a b", "javascript:alert(1)"])
def test_an_embedder_origin_is_scheme_host_port_and_nothing_else(origin):
    with pytest.raises(sb.SandboxContractError):
        sb.page_csp(NONCE, origin)


def test_the_sandbox_cannot_share_a_host_with_the_embedder():
    sb.assert_distinct_origins(EMBEDDER, SANDBOX)
    with pytest.raises(sb.SandboxContractError):
        sb.assert_distinct_origins(EMBEDDER, "http://127.77.0.1:18200")  # another port is not enough: cookies cross ports


def test_the_embedder_frame_src_names_only_the_sandbox_and_the_visualizer():
    assert sb.embedder_frame_src(SANDBOX) == "frame-src http://127.77.0.2:18200"
    assert sb.embedder_frame_src(SANDBOX, "http://127.0.0.1:9000") == "frame-src http://127.77.0.2:18200 http://127.0.0.1:9000"


def test_file_headers_fix_the_type_forbid_sniffing_and_carry_no_credentials():
    for name, expected in (("scene.js", "text/javascript"), ("public/a.png", "image/png"), ("public/a.svg", "image/svg+xml"),
                           ("public/a.woff2", "font/woff2"), ("public/a.mp4", "video/mp4")):
        headers = sb.file_headers(name, 12)
        assert headers["Content-Type"].startswith(expected) and headers["X-Content-Type-Options"] == "nosniff"
        assert "sandbox" in headers["Content-Security-Policy"] and "script-src" not in headers["Content-Security-Policy"]
        assert headers["Referrer-Policy"] == "no-referrer" and "Camera" not in headers and "camera=()" in headers["Permissions-Policy"]
        sb.assert_no_ambient_authority(headers)
    assert sb.file_headers("public/a.woff2", 1)["Access-Control-Allow-Origin"] == "*"
    assert "Access-Control-Allow-Origin" not in sb.file_headers("public/a.png", 1)
    with pytest.raises(sb.SandboxContractError):
        sb.file_headers("public/a.html", 1)
    with pytest.raises(sb.SandboxContractError):
        sb.assert_no_ambient_authority({"Set-Cookie": "a=b"})


@pytest.mark.parametrize("path", [
    f"/page/{SCENE_KEY}/{HOST_KEY}", f"/f/{SCENE_KEY}/scene.js", f"/f/{HOST_KEY}/host.js", f"/f/{SCENE_KEY}/public/dot.png",
    f"/f/{SCENE_KEY}/public/img/a.svg?x=1",
])
def test_the_routes_parse(path):
    assert sb.parse_sandbox_path(path).kind in ("page", "file")


@pytest.mark.parametrize("path", [
    "/", "/page/", f"/page/{HOST_KEY}/{SCENE_KEY}", f"/page/{SCENE_KEY}", f"/f/{SCENE_KEY}/compile.json", f"/f/{SCENE_KEY}/host.js",
    f"/f/{HOST_KEY}/scene.js", f"/f/{SCENE_KEY}/public/../scene.js", f"/f/{SCENE_KEY}/public/%2e%2e/scene.js", f"/f/{SCENE_KEY}/public\\a.png",
    f"/f/{SCENE_KEY}/public/a.html", f"/f/{SCENE_KEY}/public/.hidden.png", f"/f/{SCENE_KEY}/src/Scene.tsx", f"/f/{HOST_KEY}/public/a.png",
    "/f/scene-zz/scene.js", f"/f/{SCENE_KEY}/public/a.png\x00", "/f/" + "a" * 300, f"/page/{SCENE_KEY}/{HOST_KEY}/extra", "//evil.example/x",
])
def test_every_other_path_is_refused(path):
    with pytest.raises(sb.SandboxContractError):
        sb.parse_sandbox_path(path)


def test_the_page_orders_host_then_bootstrap_then_scene_and_every_script_has_the_nonce():
    page = sb.build_sandbox_page(nonce=NONCE, scene_key=SCENE_KEY, host_key=HOST_KEY, host_integrity="sha384-h", scene_integrity="sha384-s",
                                 embedder_origin=EMBEDDER, bootstrap_js="/*bootstrap*/")
    marks = [page.index(m) for m in (f"/f/{HOST_KEY}/host.js", "/*bootstrap*/", f"/f/{SCENE_KEY}/scene.js")]
    assert marks == sorted(marks)
    assert page.count("<script") == page.count(f'<script nonce="{NONCE}"') == 3
    assert 'integrity="sha384-h"' in page and 'integrity="sha384-s"' in page
    assert f'"staticBase":"/f/{SCENE_KEY}/public"' in page and f'"embedder":"{EMBEDDER}"' in page
    assert "<meta http-equiv" not in page  # the CSP is a header: frame-ancestors and sandbox do not exist as a meta
    with pytest.raises(sb.SandboxContractError):
        sb.build_sandbox_page(nonce=NONCE, scene_key=SCENE_KEY, host_key=HOST_KEY, host_integrity="x", scene_integrity="y",
                              embedder_origin=EMBEDDER, bootstrap_js="a </script><script>b")


# ------------------------------------------------------------------ route

class Files:
    """Faux `resolve_output_file` : un dossier réel avec les fichiers déclarés."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.declared = {(SCENE_KEY, "scene.js"): b"var JarvisScene={};", (HOST_KEY, "host.js"): b"globalThis.__JARVIS_HOST__={};",
                         (SCENE_KEY, "public/dot.png"): PNG_1X1, (SCENE_KEY, "public/evil.svg"): b"<svg xmlns='http://www.w3.org/2000/svg'/>",
                         (SCENE_KEY, "public/clip.mp4"): b"0123456789"}
        for (key, name), data in self.declared.items():
            target = root / key / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    def __call__(self, key: str, name: str) -> Path:
        from jarvis.domain.remotion_compile import CompileErrorCode, RemotionCompileError
        if (key, name) not in self.declared:
            raise RemotionCompileError(CompileErrorCode.CACHE_IO, f"{key} has no compiled file {name!r}")
        return self.root / key / name


@pytest.fixture
def responder(tmp_path):
    seen = []
    nonces = iter(["n" * 16 + str(i).zfill(4) for i in range(50)])
    return SandboxResponder(resolve_file=Files(tmp_path), embedder_origin=EMBEDDER, sandbox_origin=SANDBOX,
                            allowed_hosts=frozenset({"127.77.0.2:18200"}), bootstrap_js="/*b*/", nonce_factory=lambda: next(nonces),
                            trace=lambda kind, message, data: seen.append(kind)), seen


def test_the_page_response_has_a_fresh_nonce_per_response_and_integrity_of_the_served_bytes(responder):
    route, _ = responder
    first = route.respond("GET", f"/page/{SCENE_KEY}/{HOST_KEY}", "127.77.0.2:18200")
    second = route.respond("GET", f"/page/{SCENE_KEY}/{HOST_KEY}", "127.77.0.2:18200")
    assert first.status == 200 and first.headers["Content-Type"].startswith("text/html")
    assert first.headers["Content-Security-Policy"] != second.headers["Content-Security-Policy"]
    assert sb.sri(b"var JarvisScene={};") in first.body.decode() and first.headers["Cache-Control"] == "no-store"
    assert "nonce-" + "n" * 16 in first.headers["Content-Security-Policy"]
    sb.assert_no_ambient_authority(first.headers)


def test_files_are_served_with_their_fixed_type_head_has_no_body_and_ranges_work(responder):
    route, _ = responder
    ok = route.respond("GET", f"/f/{SCENE_KEY}/public/dot.png", "127.77.0.2:18200")
    assert ok.status == 200 and ok.body == PNG_1X1 and ok.headers["Content-Type"] == "image/png"
    head = route.respond("HEAD", f"/f/{SCENE_KEY}/public/dot.png", "127.77.0.2:18200")
    assert head.status == 200 and head.body == b"" and head.headers["Content-Length"] == str(len(PNG_1X1))
    part = route.respond("GET", f"/f/{SCENE_KEY}/public/clip.mp4", "127.77.0.2:18200", "bytes=2-4")
    assert (part.status, part.body, part.headers["Content-Range"]) == (206, b"234", "bytes 2-4/10")
    assert route.respond("GET", f"/f/{SCENE_KEY}/public/clip.mp4", "127.77.0.2:18200", "bytes=-3").body == b"789"
    for bad in ("bytes=20-30", "bytes=-", "items=1-2", "bytes=5-2"):
        assert route.respond("GET", f"/f/{SCENE_KEY}/public/clip.mp4", "127.77.0.2:18200", bad).status == 416
    svg = route.respond("GET", f"/f/{SCENE_KEY}/public/evil.svg", "127.77.0.2:18200")
    assert svg.headers["Content-Security-Policy"] == sb.FILE_CSP and "sandbox" in svg.headers["Content-Security-Policy"]


def test_the_route_refuses_foreign_hosts_methods_unknown_files_and_never_leaks_a_path(responder, tmp_path):
    route, seen = responder
    assert route.respond("GET", f"/f/{SCENE_KEY}/scene.js", "evil.example:18200").status == 421   # DNS rebinding
    assert route.respond("GET", f"/f/{SCENE_KEY}/scene.js", None).status == 421
    assert route.respond("POST", f"/f/{SCENE_KEY}/scene.js", "127.77.0.2:18200").status == 405
    assert route.respond("OPTIONS", f"/f/{SCENE_KEY}/scene.js", "127.77.0.2:18200").status == 405
    missing = route.respond("GET", f"/f/{SCENE_KEY}/public/none.png", "127.77.0.2:18200")
    assert missing.status == 404 and str(tmp_path) not in missing.body.decode()
    assert route.respond("GET", f"/f/{SCENE_KEY}/public/../scene.js", "127.77.0.2:18200").status == 404
    assert "remotion.sandbox.unknown_file" in seen
    for response in (missing, route.respond("GET", "/x", "127.77.0.2:18200")):
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        sb.assert_no_ambient_authority(response.headers)


def test_the_responder_refuses_to_be_built_on_the_embedder_host():
    with pytest.raises(sb.SandboxContractError):
        SandboxResponder(resolve_file=lambda k, n: Path(), embedder_origin=EMBEDDER, sandbox_origin="http://127.77.0.1:18200",
                         allowed_hosts=frozenset(), bootstrap_js="")


def test_the_shipped_bootstrap_is_inlinable_and_has_the_pieces_the_page_needs():
    text = load_bootstrap()
    assert "</script" not in text.lower() and "<!--" not in text
    for needle in ("RemotionSandboxProtocol", "__JARVIS_SANDBOX_CONFIG__", "remotion_staticBase", "parseHostMessage", "securitypolicyviolation"):
        assert needle in text
    for forbidden in ("localStorage", "sessionStorage", "document.cookie", "fetch(", "XMLHttpRequest", "WebSocket(", "eval("):
        assert forbidden not in text, forbidden  # the trusted bootstrap obeys its own rules

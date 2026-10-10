"""`docs/remotion-render.md` contre le code (Slice 16) : chaque code, route, borne, réglage, clé de métadonnée, variable et fichier cité existe et dit vrai."""

from __future__ import annotations

from pathlib import Path
import re

from jarvis.adapters import remotion_render_runner as runner
from jarvis.core import presentation_render_service as service
from jarvis.domain import presentation_render as D
from jarvis.domain.presentation_artifacts import RENDERS, RenderFormat
from jarvis.protocol.presentation_render_routes import PREFIX, PresentationRenderProtocolRoutes
from jarvis.runtime import presentation_render_relay as relay
from tests.unit.test_presentation_render_domain import target

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
DOC = (DOCS / "remotion-render.md").read_text(encoding="utf-8")
GUARD = (ROOT / "jarvis" / "capabilities" / "remotion" / "render-guard.cjs").read_text(encoding="utf-8")
HOST = (ROOT / "jarvis" / "capabilities" / "remotion" / "render-host.cjs").read_text(encoding="utf-8")


def test_every_error_code_is_documented_with_its_http_status_where_it_has_one():
    for code in D.RenderErrorCode:
        assert code.value in DOC or "`_" + code.value.removeprefix("presentation_render_") in DOC, code
    for code, status in ((D.RenderErrorCode.INVALID, 400), (D.RenderErrorCode.UNKNOWN_JOB, 404), (D.RenderErrorCode.UNKNOWN_SCENE, 404),
                         (D.RenderErrorCode.UNAVAILABLE, 503), (D.RenderErrorCode.RUNTIME_UNAVAILABLE, 409), (D.RenderErrorCode.BROWSER_UNAVAILABLE, 409),
                         (D.RenderErrorCode.SNAPSHOT_INVALID, 409), (D.RenderErrorCode.SOURCE_REFUSED, 409), (D.RenderErrorCode.ENGINE_MISMATCH, 409),
                         (D.RenderErrorCode.NOT_CANCELLABLE, 409), (D.RenderErrorCode.QUEUE_FULL, 429), (D.RenderErrorCode.DISK_LOW, 507),
                         (D.RenderErrorCode.STORE_FAILED, 500), (D.RenderErrorCode.INTERNAL, 500)):
        assert re.search(rf"`{code.value}`[^|]*\| {status} \|", DOC), code
        assert D.RenderError(code).status == status


def test_every_state_and_phase_is_documented():
    for state in D.JobState:
        assert f"`{state.value}`" in DOC, state
    phases = re.search(r"Phases : (.+?)\.", DOC).group(1)
    for phase in ("queued", "preparing", "bundling", "opening_browser", "selecting_composition", "rendering", "encoding", "verifying", "storing",
                  "complete", "failed", "cancelled"):
        assert f"`{phase}`" in phases, phase
    from jarvis.ports.remotion_render import BrowserInfo
    job = service.RenderJob("rj_" + "0" * 12, "jart_x", "jart_ps_x", D.resolve(RenderFormat.MP4, D.parse_settings(RenderFormat.MP4, None), target()),
                            BrowserInfo("x", "chrome 1"))
    for field in job.view():
        assert f"`{field}`" in DOC, field


def test_the_documented_routes_are_the_registered_ones():
    registered = {(route.method, route.path) for route in PresentationRenderProtocolRoutes(object()).routes() if route.method != "HEAD"}
    documented = set(re.findall(r"\| (GET|POST) \| `(/v1/local-capabilities/remotion/render[A-Za-z/{}_]*)`", DOC))
    assert registered == documented and len(registered) == 5 and PREFIX == "/v1/local-capabilities/remotion/render"


def test_the_relayed_control_center_routes_are_documented():
    registered = {(route.method, route.path) for route in relay.PresentationRenderRelayRoutes(transport=lambda: None, journal=None).routes() if route.method != "HEAD"}
    assert len(registered) == 5
    for _, path in registered:
        assert path in DOC, path
    assert "Cinq adresses relaient" in DOC and relay.CREATE_TIMEOUT_S == 60.0 and "60 s pour la création" in DOC and "40 s pour l'annulation" in DOC


def test_the_documented_bounds_are_the_code_bounds():
    assert D.MAX_RENDER_FRAMES == 3600 and "| images d'un MP4 | 3 600 |" in DOC
    assert D.MAX_PDF_PAGES == 24 and "| pages d'un PDF | 24 |" in DOC
    assert (D.MAX_OUTPUT_WIDTH, D.MAX_OUTPUT_HEIGHT) == (3840, 2160) and "3 840 × 2 160" in DOC
    assert D.MAX_OUTPUT_BYTES == 512 * 1024 * 1024 and "| fichier produit | 512 Mio |" in DOC
    assert D.MAX_JOB_DIR_BYTES == 2 * 1024**3 and "2 Gio" in DOC and runner.DIR_CHECK_EVERY_S == 2.0 and "toutes les 2 s" in DOC
    assert D.MIN_FREE_BYTES == 1536 * 1024 * 1024 and "1,5 Gio" in DOC and "64 Mio" in DOC
    assert (D.TIMEOUT_BASE_S, D.TIMEOUT_PER_FRAME_S, D.TIMEOUT_CAP_S) == (300.0, 1.0, 3600.0) and "300 s + 1 s par image, plafonné à 3 600 s" in DOC
    assert (D.CONCURRENCY_LIMIT, D.MAX_ACTIVE_JOBS, D.KEEP_FINISHED, D.KEEP_RENDERS_PER_SNAPSHOT) == (1, 8, 20, 20)
    assert "8 non terminés" in DOC and "les 20 derniers" in DOC and "les 20 rendus les plus récents" in DOC
    assert (D.MIN_CRF, D.MAX_CRF, D.DEFAULT_CRF) == (16, 35, 23) and "16 à 35" in DOC
    assert (D.MAX_CONCURRENCY, D.DEFAULT_CONCURRENCY) == (2, 1) and "1 à 2" in DOC and D.MAX_PIXELS_TIMES_TABS == 3840 * 2160
    assert "pixels de sortie × onglets est borné à 3 840 × 2 160" in DOC
    assert D.SCALES == (0.25, 0.5, 1.0, 1.5, 2.0) and "0,25 · 0,5 · 1 · 1,5 · 2" in DOC
    assert D.CODEC == "h264" and D.PIXEL_FORMAT == "yuv420p" and D.JPEG_QUALITY == 90 and "JPEG qualité 90" in DOC


def test_the_documented_settings_are_the_accepted_ones():
    for key in D.SETTINGS_KEYS:
        assert f"`{key}`" in DOC, key
    assert "`frame_start`, `frame_end`" in DOC


def test_the_documented_metadata_keys_are_the_recorded_ones():
    meta = D.resolve(RenderFormat.MP4, D.parse_settings(RenderFormat.MP4, None), target()).to_metadata()
    meta |= D.resolve(RenderFormat.PDF, D.parse_settings(RenderFormat.PDF, {"frames": [0, 1]}), target()).to_metadata()
    for key in meta:
        assert f"`{key}`" in DOC, key
    source = Path(service.__file__).read_text(encoding="utf-8")
    for key in re.findall(r'"(render_[a-z0-9_]+)"', source):
        assert f"`{key}`" in DOC, key
    for key in ("render_format", "render_job_id", "render_engine_drift"):
        assert f"`{key}`" in DOC


def test_the_documented_kinds_files_and_mime_types_are_the_registry_ones():
    for fmt, spec in RENDERS.items():
        assert f"`{spec.kind.value}` `{spec.payload_name}` `{spec.mime_type}`" in DOC, fmt


def test_the_documented_command_line_environment_and_files_are_the_launched_ones():
    source = Path(runner.__file__).read_text(encoding="utf-8")
    for needle in ("--max-old-space-size=2048", "--require", "JARVIS_RENDER_DIR", "JARVIS_RENDER_RUNTIME", "JARVIS_RENDER_BROWSER", "JARVIS_REMOTION_RENDER_BROWSER",
                   "JARVIS_REMOTION_RENDER_NO_SANDBOX"):
        assert needle in source and needle in DOC, needle
    for name in (runner.GUARD_FILE, runner.HOST_FILE, "job.json", "render.log", "result.json", "egress.json"):
        assert name in DOC, name
    assert runner.PROXY_ENV == ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")
    for path in ("jarvis/domain/presentation_render_output.py", "jarvis/runtime/presentation_render_relay.py", "jarvis/protocol/presentation_render_routes.py",
                 "jarvis/core/presentation_render_service.py"):
        assert path in DOC and (ROOT / path).is_file(), path
    app = (ROOT / "jarvis" / "app.py").read_text(encoding="utf-8")
    assert "remotion_render_runner=_remotion_render_runner" in app


def test_the_documented_guard_layers_exist_in_the_guard_file():
    for needle in ("net.Server.prototype.listen", "net.Socket.prototype.connect", "dgram.createSocket", "<-loopback>", "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1",
                   "disable_non_proxied_udp", "taskkill", "startEgressProxy", "egress.json", "fs.realpathSync", "ALLOWED_FLAGS", "PINNED_BINARY",
                   "render_guard_unexpected_args", "JARVIS_REMOTION_RENDER_NO_SANDBOX", "SANDBOX_FLAGS"):
        assert needle in GUARD, needle
    for needle in ("--no-proxy-server", "--proxy-server=", "--proxy-bypass-list="):
        assert needle in GUARD and needle in DOC, needle
    assert "chrome-for-testing" in HOST and "openBrowser" in HOST and "browserExecutable" in HOST
    assert "ensureBrowser" not in HOST and "downloadBrowser" not in HOST, "a render never downloads a browser"


def test_the_pages_that_must_know_about_renders_link_to_the_contract():
    for page in ("presentation-artifacts.md", "artifacts.md", "local-capabilities.md", "remotion-studio.md", "remotion-isolation.md", "local-data.md"):
        assert "remotion-render.md" in (DOCS / page).read_text(encoding="utf-8"), page
    assert "### 20. Presentation render" in (DOCS / "SECURITY.md").read_text(encoding="utf-8")
    assert "remotion-render.md" in (DOCS / "OPERATIONS.md").read_text(encoding="utf-8") and "SECURITY.md § 20" in (DOCS / "OPERATIONS.md").read_text(encoding="utf-8")


def test_the_pdf_decision_matches_the_code():
    from jarvis.domain import presentation_render_output as O
    assert O.PDF_POINTS_PER_PIXEL == 0.75 and "96 ppp" in DOC and "pas de texte sélectionnable" in DOC
    document, _ = O.build_pdf([b"\xff\xd8\xff\xc0\x00\x0b\x08\x00\x10\x00\x10\x01\x01\x11\x00\xff\xd9"])
    assert b"not editable" in document


def test_the_sandbox_the_lock_the_dedupe_and_the_streaming_are_documented_as_implemented():
    assert runner.NO_SANDBOX_ENV == "JARVIS_REMOTION_RENDER_NO_SANDBOX" and runner.LOCK_FILE == "core.lock" and "render/core.lock" in DOC
    assert "never retries" in runner.SANDBOX_HELP and "JARVIS_REMOTION_RENDER_NO_SANDBOX=1" in runner.SANDBOX_HELP
    for code in (D.RenderErrorCode.SANDBOX_UNAVAILABLE, D.RenderErrorCode.GUARD_UNEXPECTED_ARGS, D.RenderErrorCode.GUARD_NOT_APPLIED, D.RenderErrorCode.LOCKED):
        assert f"`{code.value}`" in DOC, code
    assert "deduplicated" in DOC and "`max_jobs, active_jobs`" in DOC.replace("{render: {ready, reason, browser, concurrency, ", "`").replace("}}", "`", 1) or "max_jobs, active_jobs" in DOC
    from jarvis.runtime import capture_relay
    assert capture_relay.MAX_STREAMED_PAYLOAD_BYTES == 1024**3 and "borné à 1 Gio" in DOC and "plus de 8 Mio" in DOC
    assert "GET .../render/jobs" in DOC

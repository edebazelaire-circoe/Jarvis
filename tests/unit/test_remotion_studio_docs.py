"""`docs/remotion-studio.md` contre le code (Slice 11) : chaque code, route, borne, drapeau, variable et fichier cité existe et dit vrai."""

from __future__ import annotations

from pathlib import Path
import re

from jarvis.adapters import remotion_studio_runner as runner
from jarvis.core import remotion_studio_service as service
from jarvis.domain import remotion_studio as D
from jarvis.protocol.remotion_studio_routes import PREFIX, RemotionStudioProtocolRoutes
from jarvis.runtime import remotion_studio_relay as relay

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "docs" / "remotion-studio.md").read_text(encoding="utf-8")
GUARD = (ROOT / "jarvis" / "capabilities" / "remotion" / "studio-guard.cjs").read_text(encoding="utf-8")


def test_every_error_code_is_in_the_table_with_its_http_status():
    for code in D.StudioErrorCode:
        assert code.value.removeprefix("remotion_studio_") in DOC, code
    assert "| `invalid` | 400 |" in DOC and "| `unavailable` | 503 |" in DOC and "| `source_unavailable` | 404 |" in DOC
    for code, status in ((D.StudioErrorCode.BUSY, 409), (D.StudioErrorCode.RUNTIME_UNAVAILABLE, 409), (D.StudioErrorCode.NOT_RUNNING, 409),
                         (D.StudioErrorCode.SYNC_FAILED, 409), (D.StudioErrorCode.INVALID, 400), (D.StudioErrorCode.UNAVAILABLE, 503),
                         (D.StudioErrorCode.SOURCE_UNAVAILABLE, 404)):
        assert D.StudioError(code).http_status == status


def test_every_status_and_stop_reason_is_documented():
    for status in D.StudioStatus:
        assert f"`{status.value}`" in DOC, status
    for reason in ("user", "idle_timeout", "core_stopped", "capability_change", "restart"):
        assert f"`{reason}`" in DOC, reason
    view = D.public_view(D.StudioState(), idle_timeout_s=1, now=0)
    for field in view:
        assert f"`{field}`" in DOC or field in ("family", "capability_id"), field


def test_the_documented_routes_are_the_registered_ones():
    registered = {(route.method, route.path) for route in RemotionStudioProtocolRoutes(object()).routes() if route.method != "HEAD"}
    documented = set(re.findall(r"\| (GET|POST) \| `(/v1/local-capabilities/remotion/studio[a-z/]*)`", DOC))
    assert registered == documented and len(registered) == 5
    assert PREFIX == "/v1/local-capabilities/remotion/studio"


def test_the_relayed_control_center_routes_are_documented_and_installation_is_not_relayed():
    for path in (relay.CAPABILITY_ROUTE, relay.STUDIO_ROUTE):
        assert path in DOC
    for action in relay._WRITES:
        assert action in DOC
    assert len(relay.RemotionStudioRelayRoutes(transport=lambda: None, journal=None).routes()) == 6
    assert "Aucune installation ni désinstallation n'est relayée" in DOC and relay.START_TIMEOUT_S == 150.0 and "150 s" in DOC


def test_the_documented_bounds_are_the_code_bounds():
    assert D.DEFAULT_IDLE_TIMEOUT_S == 1800 and "30 min par défaut" in DOC
    assert (D.MIN_IDLE_TIMEOUT_S, D.MAX_IDLE_TIMEOUT_S) == (60, 86400) and "60 s à 24 h" in DOC and "60 à 86400 s (défaut 1800)" in DOC
    assert D.START_TIMEOUT_S == 120 and "120 s au plus" in DOC
    assert D.MAX_SAVED_EDITS == 5 and "au plus 5 dossiers" in DOC
    assert runner.MAX_WORK_FILES == 400 and runner.MAX_WORK_BYTES == 64 * 1024 * 1024 and "400 fichiers, 64 Mio" in DOC
    assert (D.MIN_PORT, D.MAX_PORT) == (1024, 65535) and "1024-65535" in DOC
    assert service.TICK_S == 15.0 and "toutes les 15 s" in DOC
    assert D.IDLE_GUARD_MARGIN_S == 120 and "plus 2 min" in DOC and "depuis 60 s" in DOC and "'60'" in GUARD
    assert runner.LOG_MAX_BYTES == 1_000_000 and "1 Mio, une génération" in DOC
    assert D.MAX_DIAGNOSTIC_LINES == 12


def test_the_documented_command_line_and_environment_are_the_launched_ones(tmp_path):
    source = Path(runner.__file__).read_text(encoding="utf-8")
    for flag in ("--no-open", "--ipv4", "--disable-ask-ai", "--disable-git-source", "--port=", "--require", "--max-old-space-size=2048"):
        assert flag in source and flag in DOC, flag
    for name in ("JARVIS_STUDIO_DIR", "JARVIS_STUDIO_LAUNCH", "JARVIS_STUDIO_IDLE_S"):
        assert name in source and name in DOC, name
    app_source = (ROOT / "jarvis" / "app.py").read_text(encoding="utf-8")
    for name in ("JARVIS_REMOTION_STUDIO_PORT", "JARVIS_REMOTION_STUDIO_IDLE_S"):
        assert name in DOC and (name in app_source or name in source), name


def test_the_documented_guard_layers_exist_in_the_guard_file():
    for needle in ("net.Server.prototype.listen", "net.Socket.prototype.connect", "dns.lookup", "dgram", "Content-Security-Policy",
                   "/__jarvis_studio__/health", "activity.json", "listening.json", "exit.json", "esbuild", "parent_gone", "'idle'"):
        assert needle in GUARD, needle
    for needle in ("boucle locale", "aucune connexion sortante", "aucun processus enfant", "Content-Security-Policy", "plus d'orphelin",
                   "connect-src 'self'` seul", "Host et Origin", "parent.json", "Non couvert par ce garde", "process.binding", "dns.promises", "dgram.Socket"):
        assert needle in DOC, needle
    for needle in ("parent.json", "foreignRequest", "dns.promises", "dgram.Socket", "workerThreads.Worker", "options.lookup", "connect-src 'self'"):
        assert needle in GUARD, needle
    assert "ws://127.0.0.1" not in GUARD and "http://127.0.0.1:*" not in GUARD


def test_the_acknowledgement_contract_is_documented_and_enforced_by_name():
    assert D.ACK_FIELD in DOC and "ack_required" in DOC and "Aucun chemin du cerveau" in DOC
    assert D.ACK_FIELD in (ROOT / "jarvis" / "runtime" / "control_center_remotion_studio.js").read_text(encoding="utf-8")


def test_the_files_the_document_cites_exist():
    for name in ("jarvis/domain/remotion_studio.py", "jarvis/adapters/remotion_studio_runner.py", "jarvis/core/remotion_studio_service.py",
                 "jarvis/protocol/remotion_studio_routes.py", "jarvis/runtime/remotion_studio_relay.py", "jarvis/runtime/control_center_remotion_studio.js",
                 "jarvis/capabilities/remotion/studio-guard.cjs", "scripts/remotion_studio_harness.py",
                 "tests/unit/test_remotion_studio.py", "tests/unit/test_remotion_studio_runner.py", "tests/unit/test_remotion_studio_guard.py",
                 "tests/unit/test_remotion_studio_routes.py", "tests/unit/test_control_center_remotion_studio.py", "tests/unit/test_remotion_studio_real.py",
                 "tests/unit/test_remotion_studio_rework.py", "tests/unit/test_control_center_origin_ports.py"):
        assert (ROOT / name).is_file(), name
        assert Path(name).name in DOC or name in DOC, name
    assert "tasks/jarvis-remotion-presentation-integration/slices/11-remotion-studio-process-ui/evidence/real-studio.json" in DOC


def test_the_work_layout_documented_is_the_one_planned():
    assert D.WORK_PACKAGE in DOC and D.WORK_ROOT_FILE in DOC and D.GUARD_FILE in DOC and D.STUDIO_DIR in DOC
    for name in (runner.STATE_FILE, runner.MANIFEST_FILE, runner.LOG_FILE):
        assert name in DOC, name

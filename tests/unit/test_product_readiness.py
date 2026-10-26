"""Préparation du produit (presentation-edition-v1 Slice 07) : matrice pure, service, actions nommées, premier lancement.

Contrat : `docs/product-install.md` › *Readiness*. Aucun test ne lance la vraie CLI Claude, n'ouvre de navigateur ni ne
touche au JARVIS vivant : Core est un faux relais (`RecordingCore`-like), la CLI une fonction injectée.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.domain import product_readiness as R
from jarvis.domain.product_readiness import ActionId, BrainFacts, Probe, ReadinessFacts, ReadinessState
from jarvis.installation import Installation, InstallMode, ProductHome
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.product_readiness import ProductReadinessService, ReadinessActionError
from tests.unit.test_control_center_mcp_plugins_api import _center

HEALTH_OK = {"ready": True, "status": "ok", "installation": {
    "mode": "installed", "data_root": {"source": "product_home"},
    "runtimes": {"mode": "installed", "status": "ok", "problems": []}}}
EDITION = {"edition": "presentation", "board_kinds": [], "default_board_kind": "presentation"}
CONNECTORS = {"edition": "presentation", "connectors": [
    {"connector_id": "google_drive", "label": "Google Drive", "integration": "native", "state": "not_configured",
     "state_label": "À configurer", "detail": "Aucun compte Google Drive n'est relié à JARVIS."},
    {"connector_id": "calendar", "label": "Agenda CIRCOE", "integration": "remote_plugin", "state": "not_configured",
     "state_label": "À configurer", "detail": "Le compte CIRCOE n'est pas encore relié à JARVIS."},
    {"connector_id": "iguard", "label": "IGuard", "integration": "contract_pending", "state": "contract_pending",
     "state_label": "Bientôt disponible", "detail": "Bientôt disponible."}]}
RENDER_READY = {"status": "ready", "update_required": False}
EXPORT_ROOT = {"available": True, "root": r"Documents\Jarvis", "exists": False}
JARGON = ("MCP", "plugin", "npm", "CLI", "Remotion", "Node", "Python", "PowerShell", ".env", "pip")


def facts(**overrides) -> ReadinessFacts:
    base = dict(installed=True, core=Probe(HEALTH_OK), edition=Probe(EDITION), connectors=Probe(CONNECTORS),
                render=Probe(RENDER_READY), brain=BrainFacts(found=True, version="2.1.310", logged_in=True,
                                                             auth_method="claude.ai"),
                browser=Probe("edge 141.0"), audio=Probe({"inputs": 1, "outputs": 2}), disk_free=Probe(50 * 1024 ** 3),
                layout_missing=(), export_root=Probe(EXPORT_ROOT))
    base.update(overrides)
    return ReadinessFacts(**base)


def by_id(f: ReadinessFacts) -> dict[str, R.ReadinessItem]:
    return R.items_by_id(R.assemble(f))


def report(f: ReadinessFacts) -> dict:
    return R.report_payload(f, checked_at="2026-10-26T00:00:00+00:00", onboarding={"completed": False})


# ---------------------------------------------------------------------- matrice pure


def test_a_complete_installation_is_ready_and_optional_services_never_block():
    payload = report(facts())
    assert payload["ready"] is True and payload["blocking"] == []
    items = {item["item_id"]: item for item in payload["items"]}
    assert items["connector:google_drive"]["state"] == "optional" and items["connector:google_drive"]["required"] is False
    assert items["connector:calendar"]["actions"][0]["action_id"] == "connect_circoe"
    assert items["connector:iguard"]["state"] == "unavailable"
    assert items["export"]["summary"].endswith("sera créé à votre premier export.")


def test_every_sentence_the_user_reads_is_free_of_implementation_jargon():
    worlds = [facts(), facts(brain=BrainFacts(found=False, error="x")), facts(brain=BrainFacts(found=True, logged_in=False)),
              facts(render=Probe({"status": "not_installed"})), facts(render=Probe({"status": "install_failed",
                                                                                   "last_error_code": "local_capability_install_offline"})),
              facts(core=Probe(error="core_unreachable: boom")), facts(browser=Probe(None)), facts(layout_missing=("config",))]
    for world in worlds:
        for item in R.assemble(world):
            for word in JARGON:
                assert word not in item.summary, (item.item_id, word, item.summary)
                assert word not in item.label, (item.item_id, word)


def test_core_unreachable_is_never_ready_and_says_its_cause():
    payload = report(facts(core=Probe(error="core_unreachable: ConnectionRefusedError")))
    items = {item["item_id"]: item for item in payload["items"]}
    assert payload["ready"] is False
    assert items["core"]["state"] == "unavailable" and "ConnectionRefusedError" in items["core"]["detail"]
    assert items["runtimes"]["state"] == "unavailable"


def test_the_brain_line_guides_install_then_sign_in_then_reads_connected():
    missing = by_id(facts(brain=BrainFacts(found=False, error="claude_cli_not_found: nope")))["brain"]
    assert missing.state is ReadinessState.ACTION_NEEDED and missing.actions[0].action_id is ActionId.BRAIN_INSTALL_GUIDE
    out = by_id(facts(brain=BrainFacts(found=True, logged_in=False)))["brain"]
    assert out.actions[0].action_id is ActionId.BRAIN_SIGN_IN and out.blocking
    signing = by_id(facts(brain=BrainFacts(found=True, logged_in=False, sign_in_running=True)))["brain"]
    assert signing.state is ReadinessState.IN_PROGRESS
    unknown = by_id(facts(brain=BrainFacts(found=True, logged_in=None, error="claude_auth_status_timeout: 20 s")))["brain"]
    assert unknown.state is ReadinessState.UNAVAILABLE and unknown.detail.startswith("claude_auth_status_timeout")
    ready = by_id(facts())["brain"]
    assert ready.state is ReadinessState.READY and "abonnement Claude" in ready.summary


@pytest.mark.parametrize(("view", "state", "action"), [
    ({"status": "not_installed"}, ReadinessState.ACTION_NEEDED, ActionId.RENDER_INSTALL),
    # I-007 point 1 : un échec persistant (runtime remis après coup) se répare par une action nommée.
    ({"status": "install_failed", "last_error_code": "local_capability_requirement_missing",
      "last_error_detail": "node_missing"}, ReadinessState.ACTION_NEEDED, ActionId.RENDER_REPAIR),
    ({"status": "repair_needed"}, ReadinessState.ACTION_NEEDED, ActionId.RENDER_REPAIR),
    ({"status": "crashed"}, ReadinessState.ACTION_NEEDED, ActionId.RENDER_REPAIR),
    ({"status": "state_unreadable", "last_error_code": "local_capability_store_failed"}, ReadinessState.ACTION_NEEDED,
     ActionId.RENDER_REPAIR),
    ({"status": "disabled"}, ReadinessState.ACTION_NEEDED, ActionId.RENDER_ENABLE),
    ({"status": "ready", "update_required": True}, ReadinessState.ACTION_NEEDED, ActionId.RENDER_UPDATE),
    ({"status": "installing"}, ReadinessState.IN_PROGRESS, ActionId.RECHECK),
])
def test_each_render_state_offers_its_named_repair(view, state, action):
    item = by_id(facts(render=Probe(view)))["render"]
    assert item.state is state and item.actions[0].action_id is action
    if view.get("last_error_detail"):
        assert "node_missing" in item.detail


def test_render_failure_sentences_name_the_real_cause():
    offline = by_id(facts(render=Probe({"status": "install_failed", "last_error_code": "local_capability_install_offline"})))
    assert "Internet" in offline["render"].summary
    disk = by_id(facts(render=Probe({"status": "install_failed", "last_error_code": "local_capability_install_disk_full"})))
    assert "place" in disk["render"].summary


def test_broken_private_runtimes_and_failed_integrity_ask_for_a_reinstall_without_losing_data():
    degraded = {**HEALTH_OK, "installation": {**HEALTH_OK["installation"], "runtimes": {
        "status": "degraded", "problems": [{"component": "node", "code": "private_runtime_missing"}]}}}
    item = by_id(facts(core=Probe(degraded)))["runtimes"]
    assert item.blocking and "node: private_runtime_missing" in item.detail and "conservées" in item.summary
    damaged = by_id(facts(integrity=Probe(error="node: private_runtime_integrity_failed")))["runtimes"]
    assert damaged.state is ReadinessState.ACTION_NEEDED
    assert by_id(facts(integrity=Probe("abc")))["runtimes"].summary.endswith("Fichiers vérifiés.")
    assert "runtimes" not in by_id(facts(installed=False))


def test_layout_missing_disk_and_browser_lines():
    assert by_id(facts(layout_missing=("config",)))["data"].actions[0].action_id is ActionId.PREPARE_DATA
    critical = by_id(facts(disk_free=Probe(100 * 1024 ** 2)))["disk"]
    assert critical.required and critical.blocking
    low = by_id(facts(disk_free=Probe(1024 ** 3)))["disk"]
    assert low.state is ReadinessState.OPTIONAL and not low.blocking
    browser = by_id(facts(browser=Probe(None)))["browser"]
    assert browser.blocking and browser.detail == "render_browser_missing"
    audio = by_id(facts(audio=Probe({"inputs": 0, "outputs": 1})))["audio"]
    assert audio.state is ReadinessState.OPTIONAL and "aucun micro" in audio.summary


# ---------------------------------------------------------------------- service


class FakeCore:
    """Faux relais `forward` : réponses par (méthode, chemin), appels notés."""

    def __init__(self, routes: dict | None = None) -> None:
        self.routes = {("GET", "/v1/health"): (200, HEALTH_OK), ("GET", "/v1/boards/edition"): (200, EDITION),
                       ("GET", "/v1/edition/connectors"): (200, CONNECTORS),
                       ("GET", "/v1/local-capabilities/remotion"): (200, {"capability": RENDER_READY}),
                       ("GET", "/v1/exports/root"): (200, {"root": EXPORT_ROOT}), **(routes or {})}
        self.calls: list[tuple[str, str, object]] = []

    async def forward(self, method, path, *, params=None, body=None, timeout_s=None):
        self.calls.append((method, path, json.loads(body) if body else None))
        answer = self.routes.get((method, path))
        if answer is None:
            raise AssertionError(f"unexpected {method} {path}")
        if isinstance(answer, BaseException):
            raise answer
        return answer(body) if callable(answer) else answer


def service(tmp_path: Path, core: FakeCore, *, installed: bool = True, **kwargs) -> ProductReadinessService:
    home = ProductHome(tmp_path / "home" / "CIRCOE" / "Jarvis")
    installation = Installation(InstallMode.INSTALLED if installed else InstallMode.DEVELOPMENT, tmp_path / "app",
                                home if installed else None)
    runtime = tmp_path / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    defaults = dict(transport=lambda: core, runtime_root=runtime, journal=RuntimeJournal(runtime),
                    list_audio=lambda: {"inputs": [1], "outputs": [1]}, installation=installation, layout=None,
                    locate_brain=lambda: "claude", probe_brain=lambda cli, signing: BrainFacts(found=True, logged_in=True),
                    find_browser=lambda: "edge 141", disk_free=lambda path: 50 * 1024 ** 3, pid_alive=lambda pid: False)
    defaults.update(kwargs)
    return ProductReadinessService(**defaults)


async def test_a_report_reads_core_and_writes_nothing(tmp_path):
    core = FakeCore()
    svc = service(tmp_path, core)
    before = sorted(p.name for p in tmp_path.rglob("*"))
    payload = await svc.report()
    assert payload["schema"] == "jarvis.product-readiness" and payload["edition"] == "presentation"
    assert {call[1] for call in core.calls} == {"/v1/health", "/v1/boards/edition", "/v1/edition/connectors",
                                                "/v1/local-capabilities/remotion", "/v1/exports/root"}
    assert all(call[0] == "GET" for call in core.calls)
    # La maison du produit manque ici : la ligne le dit, la lecture ne la crée pas.
    assert payload["blocking"] == ["data"]
    after = sorted(p.name for p in tmp_path.rglob("*") if p.name not in ("trace.jsonl", "errors.jsonl"))
    assert after == [name for name in before if name not in ("trace.jsonl", "errors.jsonl")]


async def test_a_core_refusal_or_timeout_becomes_a_line_with_its_cause(tmp_path):
    core = FakeCore({("GET", "/v1/health"): asyncio.TimeoutError(),
                     ("GET", "/v1/local-capabilities/remotion"): (503, {"error": {"code": "local_capability_runner_unavailable",
                                                                                   "message": "no store"}})})
    payload = await service(tmp_path, core).report()
    items = {item["item_id"]: item for item in payload["items"]}
    assert items["core"]["state"] == "unavailable" and items["core"]["detail"].startswith("core_unreachable")
    assert items["render"]["detail"].startswith("local_capability_runner_unavailable")
    assert payload["ready"] is False


async def test_prepare_data_creates_the_home_layout_only(tmp_path):
    svc = service(tmp_path, FakeCore())
    outcome = await svc.act("prepare_data")
    home = tmp_path / "home" / "CIRCOE" / "Jarvis"
    assert outcome["status"] == "done" and sorted(outcome["created"]) == ["config", "data", "runtime"]
    assert sorted(p.name for p in home.iterdir()) == ["config", "data", "runtime"]
    assert "data" not in outcome["report"]["blocking"]
    with pytest.raises(ReadinessActionError) as refused:
        await service(tmp_path / "dev", FakeCore(), installed=False).act("prepare_data")
    assert refused.value.code == "not_installed_product"


async def test_render_repair_is_a_named_core_operation(tmp_path):
    core = FakeCore({("POST", "/v1/local-capabilities/remotion/repair"): (202, {"capability": {"status": "installing"}})})
    outcome = await service(tmp_path, core).act("render_repair")
    assert outcome["status"] == "started" and ("POST", "/v1/local-capabilities/remotion/repair", {}) in core.calls


async def test_unknown_and_concurrent_actions_are_refused(tmp_path):
    svc = service(tmp_path, FakeCore())
    with pytest.raises(ReadinessActionError) as unknown:
        await svc.act("format_disk")
    assert unknown.value.status == 404
    svc._running["verify_installation"] = 0.0
    with pytest.raises(ReadinessActionError) as busy:
        await svc.act("verify_installation")
    assert busy.value.code == "readiness_action_running"


async def test_verify_installation_runs_in_the_background_and_reports_damage(tmp_path):
    from jarvis.private_runtime import PackageLayout

    def verify(layout):
        return {"package_sha256": "x"}, ["node: private_runtime_integrity_failed (tree differs)"]

    svc = service(tmp_path, FakeCore(), layout=PackageLayout(tmp_path / "pkg"), verify=verify)
    outcome = await svc.act("verify_installation")
    assert outcome["status"] == "started"
    for _ in range(50):
        if "verify_installation" not in svc._running:
            break
        await asyncio.sleep(0.02)
    payload = await svc.report()
    items = {item["item_id"]: item for item in payload["items"]}
    assert items["runtimes"]["state"] == "action_needed" and "integrity_failed" in items["runtimes"]["detail"]


async def test_brain_sign_in_opens_once_and_reads_in_progress(tmp_path):
    started: list[str] = []

    class Proc:
        def poll(self):
            return None

    from jarvis.runtime.brain_cli import SignIn

    svc = service(tmp_path, FakeCore(), probe_brain=lambda cli, signing: BrainFacts(found=True, logged_in=False,
                                                                                    sign_in_running=signing),
                  start_sign_in=lambda cli: started.append(cli) or SignIn(Proc(), 0.0), monotonic=lambda: 1.0)
    first = await svc.act("brain_sign_in")
    second = await svc.act("brain_sign_in")
    assert started == ["claude"] and first["status"] == second["status"] == "started"
    items = {item["item_id"]: item for item in second["report"]["items"]}
    assert items["brain"]["state"] == "in_progress"
    no_cli = service(tmp_path / "b", FakeCore(), locate_brain=lambda: None)
    with pytest.raises(ReadinessActionError) as refused:
        await no_cli.act("brain_sign_in")
    assert refused.value.code == "claude_cli_not_found"


async def test_brain_install_guide_opens_the_official_page_and_downloads_nothing(tmp_path):
    outcome = await service(tmp_path, FakeCore()).act("brain_install_guide")
    assert outcome["status"] == "open" and outcome["url"].startswith("https://docs.anthropic.com/")


async def test_connect_circoe_registers_the_circuit_toolbox_account_then_returns_the_consent_page(tmp_path):
    from jarvis.domain.product_connectors import CIRCUIT_TOOLBOX_ENDPOINT

    core = FakeCore({("GET", "/v1/mcp/plugins"): (200, {"plugins": []}),
                     ("POST", "/v1/mcp/plugins"): (201, {"plugin": {"plugin_id": "circoetoolbox-server-production",
                                                                     "endpoint": CIRCUIT_TOOLBOX_ENDPOINT}}),
                     ("POST", "/v1/mcp/plugins/circoetoolbox-server-production/connect"):
                         (202, {"status": "authorizing", "authorization_url": "https://auth.example/consent"})})
    outcome = await service(tmp_path, core).act("connect_circoe")
    assert outcome["status"] == "open" and outcome["url"] == "https://auth.example/consent"
    created = next(call for call in core.calls if call[:2] == ("POST", "/v1/mcp/plugins"))
    assert created[2]["endpoint"] == CIRCUIT_TOOLBOX_ENDPOINT


async def test_onboarding_activates_a_presentation_board_and_never_an_assistant_one(tmp_path):
    boards = {"boards": [{"board_id": "default", "board_kind": "assistant"},
                         {"board_id": "pres1", "board_kind": "presentation"}], "active_board_id": "default"}
    core = FakeCore({("GET", "/v1/boards"): (200, boards),
                     ("POST", "/v1/boards/switch"): (200, {"board": {"board_id": "pres1", "board_kind": "presentation"}})})
    svc = service(tmp_path, core)
    done = await svc.complete_onboarding()
    assert done["board"]["board_id"] == "pres1" and done["onboarding"]["completed"] is True
    assert ("POST", "/v1/boards/switch", {"board_id": "pres1"}) in core.calls
    assert not any(call[:2] == ("POST", "/v1/boards") for call in core.calls)
    record = json.loads((tmp_path / "runtime" / "product-onboarding.json").read_text(encoding="utf-8"))
    assert record["schema"] == "jarvis.product-onboarding" and record["board_id"] == "pres1"


async def test_onboarding_creates_a_presentation_board_when_none_exists(tmp_path):
    core = FakeCore({("GET", "/v1/boards"): (200, {"boards": [{"board_id": "a", "board_kind": "assistant"}],
                                                   "active_board_id": "a"}),
                     ("POST", "/v1/boards"): (201, {"board": {"board_id": "new", "board_kind": "presentation"}}),
                     ("POST", "/v1/boards/switch"): (200, {"board": {"board_id": "new", "board_kind": "presentation"}})})
    done = await service(tmp_path, core).complete_onboarding()
    created = next(call for call in core.calls if call[:2] == ("POST", "/v1/boards"))
    assert created[2] == {"title": "Mes présentations", "board_kind": "presentation"}
    assert done["board"]["board_id"] == "new"


async def test_onboarding_keeps_an_active_presentation_board(tmp_path):
    core = FakeCore({("GET", "/v1/boards"): (200, {"boards": [{"board_id": "default", "board_kind": "presentation"}],
                                                   "active_board_id": "default"})})
    done = await service(tmp_path, core).complete_onboarding()
    assert done["board"]["board_id"] == "default" and [c[:2] for c in core.calls] == [("GET", "/v1/boards")]


async def test_an_unreadable_onboarding_record_replays_the_first_run(tmp_path):
    svc = service(tmp_path, FakeCore())
    (tmp_path / "runtime" / "product-onboarding.json").write_text("{nope", encoding="utf-8")
    assert svc.onboarding() == {"completed": False, "completed_at": None, "unreadable": True}


async def test_quit_needs_a_living_launcher(tmp_path):
    svc = service(tmp_path, FakeCore())
    with pytest.raises(ReadinessActionError) as refused:
        svc.request_quit()
    assert refused.value.code == "launcher_not_running"
    (tmp_path / "runtime" / "launcher.json").write_text(json.dumps({"pid": 4242, "started_at": "t"}), encoding="utf-8")
    alive = service(tmp_path, FakeCore(), pid_alive=lambda pid: pid == 4242)
    assert alive.launcher()["managed"] is True
    assert alive.request_quit() == {"status": "stopping"}
    assert (tmp_path / "runtime" / "launcher-stop.request").is_file()


# ---------------------------------------------------------------------- routes du Control Center


async def test_the_control_center_serves_the_readiness_routes(tmp_path):
    center = _center(tmp_path, FakeCore())
    svc = center.product_readiness
    svc._locate_brain = lambda: None
    svc._probe_brain = lambda cli, signing: BrainFacts(found=False, error="claude_cli_not_found: test")
    svc._list_audio = lambda: {"inputs": [], "outputs": []}
    svc._find_browser = lambda: None
    client = TestClient(TestServer(center._app))
    await client.start_server()
    try:
        response = await client.get("/api/product/readiness")
        payload = await response.json()
        assert response.status == 200 and payload["ready"] is False and "brain" in payload["blocking"]
        refused = await client.post("/api/product/readiness/actions/nope")
        assert refused.status == 404 and (await refused.json())["error"]["code"] == "readiness_action_unknown"
        quit_refused = await client.post("/api/product/quit")
        assert quit_refused.status == 409
        assert (await client.get("/api/product/readiness?x=1")).status == 400
    finally:
        await client.close()

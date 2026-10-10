"""Monde de test des outils `jarvis-remotion` (Remotion Slice 21) : un client de Core scripté qui ENREGISTRE chaque appel, et le Control Center factice.

`FakeRemotionCore` n'implémente que les méthodes du client typé que les outils ont le droit d'appeler. Il n'a volontairement AUCUNE méthode
d'ouverture du Studio ni de choix de moteur : un outil qui en appellerait une lèverait `AttributeError`, ce que les tests prouvent par
`calls` (jamais un appel d'écriture sans tour attesté).
"""

from __future__ import annotations

from typing import Any

from jarvis.protocol.client import CoreProtocolError
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.remotion_mcp_tools import RemotionTools
from tests.unit.presentation_studio_mcp_world import FakeCC

PID = "pst_0123456789abcdef0123456789abcdef"
VID = "psv_0123456789abcdef0123456789abcdef"
SID = "pss_0123456789ab"
SID2 = "pss_aaaaaaaaaaaa"
JOB = "rj_0123456789ab"
SHA = "a" * 40
TURN_ROUTE = "/api/presentation-studio/agent/turn"

READY_CAP = {"capability": {"status": "ready", "install_status": "installed", "process_status": "stopped", "health": "ok", "enabled": True,
                            "update_required": False, "pinned": {"remotion": "4.0.0"}, "last_error_code": None, "last_error_detail": None}}
MISSING_CAP = {"capability": {"status": "not_installed", "install_status": "not_installed", "process_status": "stopped", "health": "unknown",
                              "enabled": True, "update_required": False, "pinned": {}, "last_error_code": None, "last_error_detail": None}}
JOB_VIEW = {"job_id": JOB, "artifact_id": "jart_x", "state": "queued", "phase": "queued", "format": "mp4", "percent": 0, "elapsed_s": 0.0,
            "can_cancel": True, "error_code": None, "frames_done": 0, "frames_total": 90, "timeout_s": 390, "queue_position": 0}
NOTICE = {"scene_id": SID, "prefab_id": "circoe.demo", "pinned_version": 1, "latest_version": 3, "newer_versions": [3, 2], "fits": True,
          "problem": None, "licence_changed": False, "licence_ack_required": None, "pinned_licence": "MIT", "latest_licence": "MIT", "trials": []}


class FakeRemotionCore:
    """Le client typé de Core, scripté ; `calls` = [(nom, args)] dans l'ordre. `refusals[nom]` = `CoreProtocolError` à lever."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.refusals: dict[str, CoreProtocolError] = {}
        self.capability = READY_CAP
        self.notices: list[dict[str, Any]] = [dict(NOTICE)]
        self.presentation = {"presentation": {"presentation_id": PID, "revision": 7},
                             "variants": [{"variant_id": VID, "revision": 4, "scenes": []}]}

    def _record(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))
        if name in self.refusals:
            raise self.refusals[name]

    def named(self, name: str) -> list[tuple]:
        return [args for n, args in self.calls if n == name]

    WRITES = ("local_capability_action", "remotion_render_create", "remotion_render_cancel", "remotion_import_plan", "remotion_import",
              "presentation_studio_upgrade_try")

    @property
    def writes(self) -> list[str]:
        return [n for n, _ in self.calls if n in self.WRITES]

    async def remotion_capability(self) -> dict[str, Any]:
        self._record("remotion_capability")
        return self.capability

    async def presentation_studio_engine(self) -> dict[str, Any]:
        self._record("presentation_studio_engine")
        return {"default_engine": "remotion", "engines": {"slidecar": {"ready": True}, "remotion": {"ready": True, "reason": None}}}

    async def remotion_studio_status(self) -> dict[str, Any]:
        self._record("remotion_studio_status")
        return {"studio": {"status": "stopped", "work_copy": {"modified_files": []}}}

    async def remotion_render_availability(self) -> dict[str, Any]:
        self._record("remotion_render_availability")
        return {"render": {"ready": True, "reason": None, "browser": "chrome 154"}}

    async def remotion_render_jobs(self) -> dict[str, Any]:
        self._record("remotion_render_jobs")
        return {"jobs": [JOB_VIEW]}

    async def remotion_render_job(self, job_id: str) -> dict[str, Any]:
        self._record("remotion_render_job", job_id)
        return {"job": JOB_VIEW}

    async def remotion_render_create(self, body: dict[str, Any]) -> dict[str, Any]:
        self._record("remotion_render_create", body)
        return {"job": JOB_VIEW}

    async def remotion_render_cancel(self, job_id: str) -> dict[str, Any]:
        self._record("remotion_render_cancel", job_id)
        return {"job": {**JOB_VIEW, "state": "cancelled", "can_cancel": False}}

    async def local_capability_action(self, capability_id: str, operation: str) -> dict[str, Any]:
        self._record("local_capability_action", capability_id, operation)
        return {"capability": {**READY_CAP["capability"], "status": "installing"}}

    async def remotion_import_plan(self, body: dict[str, Any]) -> dict[str, Any]:
        self._record("remotion_import_plan", body)
        return {"plan": {"origin": {"name": "remotion-dev/template", "commit": body["commit"], "subdir": ""}, "license": {"spdx": "MIT"},
                         "composition": {"width": 1280, "height": 720, "fps": 30}, "dependencies": [{"name": "remotion", "version": "4"}],
                         "files": {"modules": ["src/Root.tsx"], "assets": []}, "warnings": []}, "guards_passed": True, "compiled": False, "publishes": False}

    async def remotion_import(self, body: dict[str, Any]) -> dict[str, Any]:
        self._record("remotion_import", body)
        return {"imported": True, "scope": "presentation", "presentation_id": body["presentation_id"], "scene_id": SID2,
                "prefab": {"prefab_id": "presentation-studio.x", "version": 1, "fingerprint": "f"}, "published_to_library": False}

    async def presentation_studio_list(self, *, limit: int | None = None) -> dict[str, Any]:
        self._record("presentation_studio_list")
        return {"presentations": [{"presentation_id": PID, "active_variant_id": VID}]}

    async def presentation_studio_graph(self, presentation_id: str, **kwargs: Any) -> dict[str, Any]:
        self._record("presentation_studio_graph", presentation_id)
        return {"active_variant_id": VID}

    async def presentation_studio_playback_state(self) -> dict[str, Any]:
        self._record("presentation_studio_playback_state")
        return {"state": {"phase": "idle"}}

    async def presentation_studio_get(self, presentation_id: str) -> dict[str, Any]:
        self._record("presentation_studio_get", presentation_id)
        return self.presentation

    async def presentation_studio_scene_controls(self, presentation_id: str, variant_id: str, scene_id: str) -> dict[str, Any]:
        self._record("presentation_studio_scene_controls", presentation_id, variant_id, scene_id)
        return {"prefab": {"id": "circoe.demo", "version": 1}}

    async def presentation_studio_upgrades(self, presentation_id: str, variant_id: str) -> dict[str, Any]:
        self._record("presentation_studio_upgrades", presentation_id, variant_id)
        return {"notices": self.notices, "variant_revision": 4, "count": len(self.notices), "auto_upgrade": False}

    async def presentation_studio_upgrade_try(self, presentation_id: str, variant_id: str, body: dict[str, Any]) -> dict[str, Any]:
        self._record("presentation_studio_upgrade_try", presentation_id, variant_id, body)
        return {"variant_id": "psv_" + "b" * 32, "trial": True, "adopted": False, "from": 1, "to": 3}


class DirectRemotionCore:
    def __init__(self, client: FakeRemotionCore) -> None:
        self.client = client

    async def call(self, fn: Any) -> Any:
        return await fn(self.client)


def addressed(cc: FakeCC, value: bool = True) -> FakeCC:
    cc.answers[("GET", TURN_ROUTE)] = (200, {"ok": True, "addressed_user_turn": value})
    return cc


def make_tools(tmp_path: Any, *, turn: bool | None = None) -> tuple[RemotionTools, FakeRemotionCore, FakeCC]:
    """`turn` : `None` = le Control Center ne dit rien (jamais attesté), sinon la réponse de l'attestation du tour."""

    core = FakeRemotionCore()
    cc = FakeCC()
    if turn is not None:
        addressed(cc, turn)
    root = tmp_path / "journal"
    root.mkdir(exist_ok=True)
    return RemotionTools(DirectRemotionCore(core), cc, journal=RuntimeJournal(root)), core, cc


def refusal(code: str, message: str = "") -> CoreProtocolError:
    return CoreProtocolError(409, code, message or code)

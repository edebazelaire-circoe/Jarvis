"""Une panne Bare Hands constatée par la page se range dans `errors.jsonl`.

Constat du 25/09/2026 : un navigateur sans WebGL faisait tomber le suivi, et la
cause réelle (`reading 'activeTexture'` dans le wasm MediaPipe) ne vivait que
dans la console de la page. `POST /api/barehands/failures` la garde côté
serveur, bornée, et refuse ce qui n'est pas une panne lisible.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from aiohttp import web

from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail


class Request:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        if self._payload is _BROKEN:
            raise ValueError("pas du json")
        return self._payload


_BROKEN = object()


def control_center(tmp_path):
    from jarvis.runtime.control_center import ControlCenter

    return ControlCenter(runtime_root=tmp_path / "runtime", project_root=tmp_path,
                         barehands_vendor_root=tmp_path / "vendor")


def test_a_reported_failure_lands_in_the_error_log_with_its_real_cause(tmp_path):
    control = control_center(tmp_path)
    response = asyncio.run(control.report_barehands_failure(Request({
        "code": "webgl_unavailable",
        "message": "aucun contexte WebGL (webgl2 ni webgl)",
        "stack": "Error: aucun contexte WebGL\n    at createLandmarker",
    })))
    assert json.loads(response.text) == {"ok": True}

    errors = read_jsonl_tail(RuntimeJournal(tmp_path / "runtime").error_path, limit=10)
    assert len(errors) == 1
    line = errors[0]
    assert line["kind"] == "barehands.failure" and line["level"] == "error"
    assert line["data"]["code"] == "webgl_unavailable"
    assert "aucun contexte WebGL" in line["message"]
    assert "createLandmarker" in line["data"]["stack"]


def test_the_texts_are_bounded_so_a_runaway_page_cannot_flood_the_log(tmp_path):
    control = control_center(tmp_path)
    asyncio.run(control.report_barehands_failure(Request({
        "code": "tracking_failed", "message": "x" * 50_000, "stack": "y" * 50_000})))
    line = read_jsonl_tail(RuntimeJournal(tmp_path / "runtime").error_path, limit=1)[0]
    assert len(line["data"]["message"]) <= 4000
    assert len(line["data"]["stack"]) <= 4000


@pytest.mark.parametrize("payload", [
    _BROKEN, ["tracking_failed"], {}, {"code": ""}, {"code": "Tracking Failed"},
    {"code": "a" * 200},
])
def test_an_unreadable_report_is_refused_and_writes_nothing(tmp_path, payload):
    control = control_center(tmp_path)
    with pytest.raises(web.HTTPBadRequest):
        asyncio.run(control.report_barehands_failure(Request(payload)))
    assert read_jsonl_tail(RuntimeJournal(tmp_path / "runtime").error_path, limit=10) == []

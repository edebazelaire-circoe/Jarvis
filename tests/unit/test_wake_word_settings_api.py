"""Route `/api/wake-word` : même forme que `/api/interaction-mode`, un seul magasin."""

from __future__ import annotations

import json
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.runtime.journal import read_jsonl_tail
from jarvis.runtime.control_center import SETTINGS_ERROR_CODE_HEADER, ControlCenter


class JsonRequest:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    async def json(self) -> object:
        return self.payload


class BrokenJsonRequest:
    async def json(self) -> object:
        raise ValueError("not json")


@pytest.fixture
def control(tmp_path, monkeypatch):
    for name in ("PORCUPINE_ACCESS_KEY", "OPENAI_API_KEY", "JARVIS_VOICE_ARCH"):
        monkeypatch.delenv(name, raising=False)
    return ControlCenter(runtime_root=tmp_path, project_root=tmp_path)


def settings_file(control: ControlCenter) -> Path:
    return control.settings_path


async def get(control) -> dict:
    return json.loads((await control.get_wake_word(None)).text)


def test_the_route_is_registered_like_its_model(control):
    routes = {(r.method, r.resource.canonical) for r in control._app.router.routes()}
    assert ("GET", "/api/wake-word") in routes and ("POST", "/api/wake-word") in routes


async def test_get_returns_the_described_block(control):
    payload = await get(control)

    assert payload["enabled"] is False
    assert payload["provider"] == "porcupine" and payload["keyword"] == "jarvis"
    assert payload["restart_required"] is True
    assert not settings_file(control).exists(), "lire ne crée aucun fichier"


async def test_get_on_a_corrupt_settings_file_falls_back_to_defaults_without_raising(control):
    control.runtime_root.mkdir(parents=True, exist_ok=True)
    settings_file(control).write_text("{ not json", encoding="utf-8")

    assert (await get(control))["enabled"] is False


async def test_get_reports_an_unreadable_block_and_keeps_it(control):
    block = {"schema_version": 7, "enabled": True}
    settings_file(control).write_text(json.dumps({"wake_word": block}), encoding="utf-8")

    payload = await get(control)

    assert payload["enabled"] is False and payload["unreadable"] is True
    assert json.loads(settings_file(control).read_text(encoding="utf-8"))["wake_word"] == block


async def test_post_valid_block_is_written_atomically_and_the_next_get_reads_it_back(control):
    response = await control.save_wake_word(JsonRequest(
        {"enabled": True, "provider": "openwakeword", "sensitivity": 0.8, "cooldown_ms": 3000}))

    body = json.loads(response.text)
    assert body["enabled"] is True and body["keyword"] == "hey_jarvis"
    stored = json.loads(settings_file(control).read_text(encoding="utf-8"))["wake_word"]
    assert stored["schema_version"] == 1 and stored["sensitivity"] == 0.8 and stored["cooldown_ms"] == 3000
    assert not list(control.runtime_root.glob("*.tmp")), "aucun temporaire ne survit"
    assert await get(control) == body


async def test_post_preserves_the_other_keys_secrets_included(control):
    original = {"manual_wake_key": "f7", "shortcuts": {"wake_toggle": "f6"},
                "interaction_mode": {"schema_version": 1, "mode": "presentation"},
                "credentials": {"openai": "sk-keep-me"}}
    settings_file(control).write_text(json.dumps(original), encoding="utf-8")

    await control.save_wake_word(JsonRequest({"enabled": True}))

    after = json.loads(settings_file(control).read_text(encoding="utf-8"))
    for key, value in original.items():
        assert after[key] == value
    assert after["wake_word"]["enabled"] is True


@pytest.mark.parametrize(
    "payload, code",
    [
        ({"sensitivity": 3}, "wake_word_sensitivity_out_of_range"),
        ({"cooldown_ms": 1}, "wake_word_cooldown_out_of_range"),
        ({"enabled": "yes"}, "wake_word_enabled_invalid"),
        ({"provider": "alexa"}, "wake_word_provider_unknown"),
        ({"surprise": 1}, "wake_word_unknown_field"),
        ([1, 2], "wake_word_bad_payload"),
        (None, "wake_word_bad_payload"),
    ],
)
async def test_post_invalid_block_is_refused_with_a_code_and_the_file_is_unchanged(control, payload, code):
    settings_file(control).write_text('{"manual_wake_key": "f9"}\n', encoding="utf-8")
    before = settings_file(control).read_bytes()

    with pytest.raises(web.HTTPBadRequest) as refused:
        await control.save_wake_word(JsonRequest(payload))

    assert refused.value.headers[SETTINGS_ERROR_CODE_HEADER] == code
    assert settings_file(control).read_bytes() == before


async def test_post_with_a_body_that_is_not_json_is_refused_with_a_code(control):
    with pytest.raises(web.HTTPBadRequest) as refused:
        await control.save_wake_word(BrokenJsonRequest())

    assert refused.value.headers[SETTINGS_ERROR_CODE_HEADER] == "wake_word_bad_payload"
    assert not settings_file(control).exists()


async def test_a_refusal_on_a_fresh_install_creates_no_file(control):
    with pytest.raises(web.HTTPBadRequest):
        await control.save_wake_word(JsonRequest({"sensitivity": 9}))

    assert not settings_file(control).exists()


async def test_the_response_says_voice_must_restart(control):
    body = json.loads((await control.save_wake_word(JsonRequest({"enabled": True}))).text)

    assert body["restart_required"] is True
    assert "redémarrage de Voice" in body["restart_message"]


async def test_other_settings_endpoints_are_unaffected(control):
    before = json.loads((await control.get_settings(None)).text)

    await control.save_wake_word(JsonRequest({"enabled": True}))

    after = json.loads((await control.get_settings(None)).text)
    assert "wake_word" not in after, "le bloc n'entre pas dans /api/settings"
    assert after == before


async def test_no_sqlite_file_is_created_or_modified(control):
    await control.save_wake_word(JsonRequest({"enabled": True}))
    await get(control)

    assert not list(control.runtime_root.rglob("*.sqlite3*"))
    assert not list(control.runtime_root.rglob("*.bak"))


# ----------------------------------------- B1 : entier démesuré, route réelle


@pytest.mark.parametrize("field, code", [
    ("sensitivity", "wake_word_sensitivity_out_of_range"), ("cooldown_ms", "wake_word_cooldown_out_of_range")])
@pytest.mark.parametrize("sign", ["", "-"])
async def test_a_real_post_with_a_giant_integer_is_a_400_with_a_stable_code(control, field, code, sign):
    control.runtime_root.mkdir(parents=True, exist_ok=True)
    settings_file(control).write_text('{"manual_wake_key": "f9"}\n', encoding="utf-8")
    before = settings_file(control).read_bytes()
    body = '{"%s": %s%s}' % (field, sign, "9" * 400)

    async with TestClient(TestServer(control._app)) as client:
        response = await client.post(
            "/api/wake-word", data=body, headers={"Content-Type": "application/json"})
        assert response.status == 400
        assert response.headers[SETTINGS_ERROR_CODE_HEADER] == code

    assert settings_file(control).read_bytes() == before


async def test_a_real_post_of_1e400_is_a_400_with_the_invalid_code(control):
    async with TestClient(TestServer(control._app)) as client:
        response = await client.post(
            "/api/wake-word", data='{"sensitivity": 1e400}', headers={"Content-Type": "application/json"})
        assert response.status == 400
        assert response.headers[SETTINGS_ERROR_CODE_HEADER] == "wake_word_sensitivity_invalid"
    assert not settings_file(control).exists()


@pytest.mark.parametrize("field", ["sensitivity", "cooldown_ms"])
async def test_a_real_get_of_a_file_holding_a_giant_integer_serves_defaults_and_a_diagnostic(control, field):
    control.runtime_root.mkdir(parents=True, exist_ok=True)
    raw = '{"wake_word": {"schema_version": 1, "enabled": true, "%s": %s}}' % (field, "9" * 400)
    settings_file(control).write_text(raw, encoding="utf-8")

    async with TestClient(TestServer(control._app)) as client:
        response = await client.get("/api/wake-word")
        assert response.status == 200
        payload = await response.json()

    assert payload["enabled"] is False
    assert payload["problems"][0]["code"] == f"wake_word_{field.split('_')[0]}_out_of_range"
    assert settings_file(control).read_text(encoding="utf-8") == raw


# ------------------------------------------ P3 : version étrangère, journal et refus


def trace_kinds(control) -> list[str]:
    return [item["kind"] for item in read_jsonl_tail(control.journal.trace_path, limit=500)]


async def test_an_unreadable_block_is_logged_once_per_process_with_a_stable_code_only(control):
    secret = "sk-never-in-the-log"
    settings_file(control).write_text(
        json.dumps({"wake_word": {"schema_version": 7, "enabled": True, "note": secret}}), encoding="utf-8")

    await get(control)
    await get(control)

    lines = [i for i in read_jsonl_tail(control.journal.trace_path, limit=500)
             if i["kind"] == "wake_word.settings.unreadable"]
    assert len(lines) == 1
    assert lines[0]["level"] == "warning"
    assert lines[0]["data"]["code"] == "wake_word_stored_version_unreadable"
    assert secret not in json.dumps(lines[0])


async def test_a_readable_or_absent_block_logs_no_unreadable_warning(control):
    await get(control)
    await control.save_wake_word(JsonRequest({"enabled": True}))
    await get(control)

    assert "wake_word.settings.unreadable" not in trace_kinds(control)


async def test_post_refuses_to_overwrite_a_block_from_a_newer_schema_version(control):
    settings_file(control).write_text(
        '{"manual_wake_key": "f9", "wake_word": {"schema_version": 7, "enabled": true}}\n', encoding="utf-8")
    before = settings_file(control).read_bytes()

    with pytest.raises(web.HTTPBadRequest) as refused:
        await control.save_wake_word(JsonRequest({"enabled": False}))

    assert refused.value.headers[SETTINGS_ERROR_CODE_HEADER] == "wake_word_foreign_version"
    assert settings_file(control).read_bytes() == before

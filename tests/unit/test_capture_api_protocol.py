"""API HTTP de Core pour les Contexts, captures, Artifacts et transcriptions (session-context-recording, Slice 09).

Contrat : `docs/capture.md` › *HTTP API*. Ce qui doit tenir, route par route :
réponse nominale, codes stables des domaines et leur statut, bornes refusées
(jamais tronquées en silence), jamais de chemin absolu ni de jeton dans un
corps, transcription marquée non adressée (D17), payload en plages bornées,
abandon explicite d'une transcription qui rend l'enregistrement supprimable.
Vraie chaîne Core (`tests/fakes/capture_stack.py`), sources factices.
"""

from __future__ import annotations

import json

import aiohttp
import pytest

from jarvis.core import capture_api
from jarvis.core.capture_api import REDACTED_PATH, redact_paths
from jarvis.core.recording_transcriber import projection_id_of, segment_id_of
from tests.fakes.capture_stack import TOKEN, CaptureStack, until



async def core(stack: CaptureStack, method: str, path: str, *, token: str = TOKEN, **kwargs):
    headers = {"Authorization": f"Bearer {token}", **kwargs.pop("headers", {})}
    async with aiohttp.ClientSession() as session:
        async with session.request(method, stack.core_url + path, headers=headers, **kwargs) as response:
            raw = await response.read()
            try:
                body = json.loads(raw)
            except ValueError:
                body = None
            return response.status, body, raw, dict(response.headers)


def assert_clean(stack: CaptureStack, raw: bytes) -> None:
    text = raw.decode("utf-8", "replace")
    assert TOKEN not in text
    for root in (str(stack.tmp_path), str(stack.tmp_path).replace("\\", "/"), json.dumps(str(stack.tmp_path))[1:-1]):
        assert root not in text


async def recorded(stack: CaptureStack) -> dict:
    """Un enregistrement audio démarré, arrêté, transcrit en entier (trois segments)."""

    status, body, _, _ = await core(stack, "POST", "/v1/captures/start", json={"channel": "audio"})
    assert status == 201, body
    capture_id = body["capture"]["capture_id"]
    status, stopped, _, _ = await core(stack, "POST", f"/v1/captures/{capture_id}/stop")
    assert status == 200 and stopped["capture"]["state"] == "complete", stopped

    async def done() -> bool:
        _, answer, _, _ = await core(stack, "GET", f"/v1/captures/{capture_id}")
        return (answer["capture"]["transcription"] or {}).get("state") == "complete"

    await until(done)
    return stopped["capture"]


# ------------------------------------------------------------------ garde


async def test_every_route_needs_the_bearer_token(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        for method, path in (("GET", "/v1/contexts"), ("GET", "/v1/captures/status"), ("GET", "/v1/artifacts"),
                             ("POST", "/v1/captures/start"), ("GET", "/v1/activity")):
            status, body, _, _ = await core(stack, method, path, token="x" * 48)
            assert status == 401 and body["error"]["code"] == "unauthorized"


# ------------------------------------------------------------------ Contexts


async def test_contexts_list_create_activate_with_relative_refs_only(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        status, listed, raw, _ = await core(stack, "GET", "/v1/contexts")
        assert status == 200 and len(listed["contexts"]) == 1
        first = listed["active_context_id"]
        entry = listed["contexts"][0]
        assert entry["workspace_ref"] == f"sessions/{listed['jarvis_session_id']}/contexts/{first}"
        assert_clean(stack, raw)

        status, created, raw, _ = await core(stack, "POST", "/v1/contexts", json={
            "title": "Revue", "handoff_summary": "Reprendre l'export PDF.", "source_context_ids": [first],
            "origin": "brain"})
        assert status == 201, created
        assert created["previous_context_id"] == first and created["handoff_written"] is True
        assert created["context"]["title"] == "Revue" and created["context"]["source_context_ids"] == [first]
        assert "workspace_path" not in created and "handoff_path" not in created
        assert_clean(stack, raw)

        _, current, _, _ = await core(stack, "GET", "/v1/contexts/current")
        assert current["context"]["context_id"] == created["context"]["context_id"]

        status, back, _, _ = await core(stack, "POST", f"/v1/contexts/{first}/activate", json={"origin": "brain"})
        assert status == 200 and back["changed"] is True and back["context"]["status"] == "active"
        status, again, _, _ = await core(stack, "POST", f"/v1/contexts/{first}/activate")
        assert status == 200 and again["changed"] is False

        events = (await core(stack, "GET", "/v1/activity", params={"kind": "context.created,context.activated"}))[1]
        assert [e["kind"] for e in events["events"]][-2:] == ["context.created", "context.activated"]


@pytest.mark.parametrize("body, code, http", [
    ({"source_context_ids": ["jctx_missing"]}, "context_not_found", 404),
    ({"source_context_ids": "jctx_x"}, "invalid_request", 400),
    ({"handoff_summary": "x" * 8_001}, "invalid_request", 400),
    ({"title": "Ok", "colour": "red"}, "invalid_request", 400),
    ({"origin": "voice"}, "invalid_request", 400),
])
async def test_context_creation_refusals_keep_their_codes(tmp_path, body, code, http):
    async with CaptureStack(tmp_path) as stack:
        status, answer, _, _ = await core(stack, "POST", "/v1/contexts", json=body)
        assert (status, answer["error"]["code"]) == (http, code)


async def test_activating_an_unknown_context_is_context_not_found(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        status, answer, _, _ = await core(stack, "POST", "/v1/contexts/jctx_nope/activate")
        assert (status, answer["error"]["code"]) == (404, "context_not_found")


# ------------------------------------------------------------------ captures


async def test_capture_lifecycle_status_is_the_capture_service_truth(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        _, empty, _, _ = await core(stack, "GET", "/v1/captures/status")
        assert empty["captures"] == [] and empty["stuck"] == [] and empty["recent"] == []
        assert empty["enrichment"]["state"] in {"idle", "unavailable", "stopped"}

        status, started, _, _ = await core(stack, "POST", "/v1/captures/start",
                                           json={"channel": "audio", "origin": "brain"})
        assert status == 201 and started["capture"]["state"] == "active"
        capture_id = started["capture"]["capture_id"]
        assert started["capture"]["data"] == {"origin": "brain"}

        status, busy, _, _ = await core(stack, "POST", "/v1/captures/start", json={"channel": "audio"})
        assert (status, busy["error"]["code"], busy["error"]["capture_id"]) == (409, "already_active", capture_id)

        _, live, raw, _ = await core(stack, "GET", "/v1/captures/status")
        truth = stack.core.captures.status()
        assert [c["capture_id"] for c in live["captures"]] == [r.capture_id for r in truth.captures]
        assert live["captures"][0]["bytes_written"] == truth.captures[0].bytes_written
        assert live["captures"][0]["transcription"]["transcript_artifact_id"] == projection_id_of(
            truth.captures[0].artifact_id)
        assert_clean(stack, raw)

        status, stopped, _, _ = await core(stack, "POST", f"/v1/captures/{capture_id}/stop")
        assert status == 200 and stopped["capture"]["state"] == "complete"
        status, twice, _, _ = await core(stack, "POST", f"/v1/captures/{capture_id}/stop")
        assert status == 200 and twice["capture"]["state"] == "complete"  # idempotent

        _, after, _, _ = await core(stack, "GET", "/v1/captures/status", params={"recent": "2"})
        assert after["captures"] == [] and after["recent"][0]["capture_id"] == capture_id


@pytest.mark.parametrize("method, path, body, code, http", [
    ("GET", "/v1/captures/jcap_unknown", None, "capture_not_found", 404),
    ("GET", "/v1/captures/NOT-AN-ID", None, "invalid_capture", 400),
    ("POST", "/v1/captures/start", {"channel": "camera"}, "invalid_request", 400),
    ("POST", "/v1/captures/start", {}, "invalid_request", 400),
    ("POST", "/v1/captures/start", {"channel": "audio", "options": {"path": "C:/x"}}, "invalid_request", 400),
    ("POST", "/v1/captures/start", {"channel": "audio", "options": {"source": "microphone"}},
     "unsupported_source", 400),
    ("GET", "/v1/captures/status?recent=21", None, "invalid_request", 400),
    ("GET", "/v1/captures/status?other=1", None, "invalid_request", 400),
])
async def test_capture_refusals_keep_their_codes(tmp_path, method, path, body, code, http):
    async with CaptureStack(tmp_path) as stack:
        status, answer, raw, _ = await core(stack, method, path, json=body)
        assert (status, answer["error"]["code"]) == (http, code)
        assert_clean(stack, raw)


async def test_screenshot_returns_the_capture_and_its_artifact_summary(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        status, shot, raw, _ = await core(stack, "POST", "/v1/captures/screenshot", json={})
        assert status == 201, shot
        assert shot["capture"]["mode"] == "one_shot" and shot["capture"]["state"] == "complete"
        artifact = shot["artifact"]
        assert artifact["kind"] == "screenshot" and artifact["width"] == 1 and artifact["has_payload"] is True
        assert "payload_ref" not in artifact and "metadata" not in artifact
        assert_clean(stack, raw)


# ------------------------------------------------------------------ transcription


async def test_transcript_tail_forward_and_time_reads_are_bounded_and_not_addressed(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        capture = await recorded(stack)
        capture_id, audio_id = capture["capture_id"], capture["artifact_id"]

        status, tail, raw, _ = await core(stack, "GET", f"/v1/captures/{capture_id}/transcript")
        assert status == 200 and tail["segments_total"] == 3
        assert [s["text"] for s in tail["segments"]] == ["phrase 1", "phrase 2", "phrase 3"]
        assert tail["addressed"] is False and "NON adressée" in tail["notice"]
        assert tail["transcription_state"] == "complete" and tail["truncated"] is False
        assert tail["segments"][0]["start_ms"] < tail["segments"][1]["start_ms"]
        assert_clean(stack, raw)

        _, bounded, _, _ = await core(stack, "GET", f"/v1/captures/{capture_id}/transcript", params={"max_chars": "10"})
        assert [s["text"] for s in bounded["segments"]] == [" 2", "phrase 3"] and bounded["truncated"] is True

        _, forward, _, _ = await core(stack, "GET", f"/v1/captures/{capture_id}/transcript", params={"after_seq": "1"})
        assert [s["seq"] for s in forward["segments"]] == [2, 3] and forward["next_after_seq"] == 3

        second_start = tail["segments"][1]["start_ms"]
        _, timed, _, _ = await core(stack, "GET", f"/v1/captures/{capture_id}/transcript",
                                    params={"from_ms": str(second_start)})
        assert [s["seq"] for s in timed["segments"]] == [2, 3]

        for artifact_id in (audio_id, projection_id_of(audio_id), segment_id_of(audio_id, 2)):
            _, via, _, _ = await core(stack, "GET", f"/v1/artifacts/{artifact_id}/transcript")
            assert via["transcript_artifact_id"] == projection_id_of(audio_id) and len(via["segments"]) == 3

        status, both, _, _ = await core(stack, "GET", f"/v1/captures/{capture_id}/transcript",
                                        params={"after_seq": "1", "from_ms": "0"})
        assert (status, both["error"]["code"]) == (400, "invalid_request")
        status, big, _, _ = await core(stack, "GET", f"/v1/captures/{capture_id}/transcript",
                                       params={"max_chars": "12001"})
        assert status == 400


async def test_a_screenshot_has_no_transcript(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        _, shot, _, _ = await core(stack, "POST", "/v1/captures/screenshot", json={})
        status, answer, _, _ = await core(stack, "GET", f"/v1/artifacts/{shot['artifact']['artifact_id']}/transcript")
        assert (status, answer["error"]["code"]) == (400, "invalid_artifact")
        status, answer, _, _ = await core(stack, "GET", f"/v1/captures/{shot['capture']['capture_id']}/transcript")
        assert (status, answer["error"]["code"]) == (503, "transcription_unavailable")


async def test_abandon_finalizes_a_stuck_transcript_partial_and_unblocks_deletion(tmp_path):
    async with CaptureStack(tmp_path, transcription=False) as stack:
        _, started, _, _ = await core(stack, "POST", "/v1/captures/start", json={"channel": "audio"})
        capture_id = started["capture"]["capture_id"]
        audio_id = started["capture"]["artifact_id"]

        status, refused, _, _ = await core(stack, "POST", f"/v1/captures/{capture_id}/transcription/abandon")
        assert (status, refused["error"]["code"]) == (409, "capture_still_open")
        await core(stack, "POST", f"/v1/captures/{capture_id}/stop")

        async def unavailable() -> bool:
            _, answer, _, _ = await core(stack, "GET", f"/v1/captures/{capture_id}")
            return (answer["capture"]["transcription"] or {}).get("state") == "unavailable"

        await until(unavailable)
        status, retried, _, _ = await core(stack, "POST", f"/v1/captures/{capture_id}/transcription/retry")
        assert status == 200 and retried["transcription"]["capture_id"] == capture_id

        status, blocked, _, _ = await core(stack, "DELETE", f"/v1/artifacts/{audio_id}", params={"cascade": "true"})
        assert (status, blocked["error"]["code"]) == (409, "artifact_still_pending")

        status, gone, _, _ = await core(stack, "POST", f"/v1/captures/{capture_id}/transcription/abandon",
                                        json={"reason": "pas de clé OpenAI"})
        assert status == 200 and gone["transcription"]["state"] == "abandoned"
        projection = await stack.core.artifacts.get(projection_id_of(audio_id))
        assert projection.state.value == "partial" and projection.error_code == "transcription_abandoned"
        assert projection.metadata["last_error"] == "pas de clé OpenAI"
        status, again, _, _ = await core(stack, "POST", f"/v1/captures/{capture_id}/transcription/abandon")
        assert status == 200 and again["transcription"]["state"] == "abandoned"  # idempotent

        status, deleted, _, _ = await core(stack, "DELETE", f"/v1/artifacts/{audio_id}", params={"cascade": "true"})
        assert status == 200 and set(deleted["deleted"]) >= {audio_id, projection_id_of(audio_id)}


async def test_abandon_keeps_the_segments_already_transcribed(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        capture = await recorded(stack)
        # Déjà complète : l'abandon rend l'état tel quel, rien n'est réécrit.
        status, answer, _, _ = await core(stack, "POST", f"/v1/captures/{capture['capture_id']}/transcription/abandon")
        assert status == 200 and answer["transcription"]["state"] == "complete"
        assert (await stack.core.artifacts.get(segment_id_of(capture["artifact_id"], 1))).text == "phrase 1"


# ------------------------------------------------------------------ Artifacts


async def test_artifact_query_get_relations_and_bounds(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        capture = await recorded(stack)
        audio_id = capture["artifact_id"]
        _, page, raw, _ = await core(stack, "GET", "/v1/artifacts",
                                     params={"context_id": "active", "kind": "transcript_segment", "limit": "2"})
        assert [item["kind"] for item in page["artifacts"]] == ["transcript_segment"] * 2
        assert page["next_cursor"] and page["artifacts"][0]["addressed"] is False
        assert all("text" not in item and len(item["preview"]) <= 161 for item in page["artifacts"])
        _, rest, _, _ = await core(stack, "GET", "/v1/artifacts", params={
            "context_id": "active", "kind": "transcript_segment", "limit": "2", "cursor": page["next_cursor"]})
        assert len(rest["artifacts"]) == 1 and rest["next_cursor"] is None
        assert_clean(stack, raw)

        _, many, _, _ = await core(stack, "GET", "/v1/artifacts", params={"kind": "audio_recording,transcript",
                                                                         "jarvis_session_id": "current"})
        assert {item["kind"] for item in many["artifacts"]} == {"audio_recording", "transcript"}

        status, detail, raw, _ = await core(stack, "GET", f"/v1/artifacts/{projection_id_of(audio_id)}",
                                            params={"text_chars": "5"})
        assert status == 200 and detail["artifact"]["text"] == "phrase"[:5]
        assert detail["artifact"]["text_truncated"] is True and detail["artifact"]["addressed"] is False
        assert detail["artifact"]["payload_ref"].startswith("artifacts/")
        assert_clean(stack, raw)

        _, relations, _, _ = await core(stack, "GET", f"/v1/artifacts/{segment_id_of(audio_id, 1)}/relations")
        assert {r["relation"] for r in relations["origins"]} == {"transcribed_from", "segment_of"}
        _, deps, _, _ = await core(stack, "GET", f"/v1/artifacts/{audio_id}/relations",
                                   params={"direction": "dependents"})
        assert "origins" not in deps and len(deps["dependents"]) >= 4


@pytest.mark.parametrize("path, params, code, http", [
    ("/v1/artifacts", {"limit": "51"}, "invalid_request", 400),
    ("/v1/artifacts", {"kind": "video"}, "invalid_request", 400),
    ("/v1/artifacts", {"since": "2026-10-01T10:00:00"}, "invalid_request", 400),
    ("/v1/artifacts", {"cursor": "forged"}, "invalid_artifact", 400),
    ("/v1/artifacts", {"context_id": "jctx_x", "jarvis_session_id": "bad"}, "invalid_artifact", 400),
    ("/v1/artifacts/jart_unknown", {}, "artifact_not_found", 404),
    ("/v1/artifacts/bad-id", {}, "invalid_artifact", 400),
    ("/v1/artifacts/jart_unknown/relations", {"direction": "up"}, "invalid_request", 400),
    ("/v1/activity", {"limit": "201"}, "invalid_request", 400),
])
async def test_artifact_refusals_keep_their_codes(tmp_path, path, params, code, http):
    async with CaptureStack(tmp_path) as stack:
        status, answer, _, _ = await core(stack, "GET", path, params=params)
        assert (status, answer["error"]["code"]) == (http, code)


async def test_payload_bytes_with_ranges_mime_and_bounds(tmp_path, monkeypatch):
    async with CaptureStack(tmp_path) as stack:
        _, shot, _, _ = await core(stack, "POST", "/v1/captures/screenshot", json={})
        artifact_id = shot["artifact"]["artifact_id"]
        status, _, data, headers = await core(stack, "GET", f"/v1/artifacts/{artifact_id}/payload")
        assert status == 200 and data.startswith(b"\x89PNG") and headers["Content-Type"] == "image/png"
        assert headers["X-Content-Type-Options"] == "nosniff" and headers["Accept-Ranges"] == "bytes"
        assert headers["Content-Disposition"] == 'inline; filename="screenshot.png"'
        total = len(data)

        status, _, part, headers = await core(stack, "GET", f"/v1/artifacts/{artifact_id}/payload",
                                              headers={"Range": "bytes=1-3"})
        assert status == 206 and part == data[1:4] and headers["Content-Range"] == f"bytes 1-3/{total}"
        status, _, suffix, _ = await core(stack, "GET", f"/v1/artifacts/{artifact_id}/payload",
                                          headers={"Range": "bytes=-4"})
        assert status == 206 and suffix == data[-4:]
        status, refused, _, headers = await core(stack, "GET", f"/v1/artifacts/{artifact_id}/payload",
                                                 headers={"Range": f"bytes={total}-"})
        assert (status, refused["error"]["code"]) == (416, "artifact_range_invalid")
        assert headers["Content-Range"] == f"bytes */{total}"

        monkeypatch.setattr(capture_api, "MAX_PAYLOAD_CHUNK_BYTES", 10)
        status, big, _, _ = await core(stack, "GET", f"/v1/artifacts/{artifact_id}/payload")
        assert (status, big["error"]["code"]) == (413, "artifact_payload_too_large")
        status, _, chunk, headers = await core(stack, "GET", f"/v1/artifacts/{artifact_id}/payload",
                                               headers={"Range": "bytes=0-"})
        assert status == 206 and chunk == data[:10] and headers["Content-Range"] == f"bytes 0-9/{total}"


async def test_payload_of_a_pending_or_payloadless_artifact_is_refused(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        _, started, _, _ = await core(stack, "POST", "/v1/captures/start", json={"channel": "screen"})
        artifact_id = started["capture"]["artifact_id"]
        status, answer, _, _ = await core(stack, "GET", f"/v1/artifacts/{artifact_id}/payload")
        assert (status, answer["error"]["code"]) == (409, "artifact_still_pending")
        status, answer, _, _ = await core(stack, "DELETE", f"/v1/artifacts/{artifact_id}")
        assert (status, answer["error"]["code"]) == (409, "artifact_still_pending")
        await core(stack, "POST", f"/v1/captures/{started['capture']['capture_id']}/stop")
        capture = await recorded(stack)
        segment = segment_id_of(capture["artifact_id"], 1)
        status, answer, _, _ = await core(stack, "GET", f"/v1/artifacts/{segment}/payload")
        assert (status, answer["error"]["code"]) == (404, "artifact_no_payload")


async def test_delete_is_explicit_and_refuses_dependents_without_cascade(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        capture = await recorded(stack)
        audio_id = capture["artifact_id"]
        status, answer, _, _ = await core(stack, "DELETE", f"/v1/artifacts/{audio_id}")
        assert (status, answer["error"]["code"]) == (409, "artifact_has_dependents")
        status, answer, _, _ = await core(stack, "DELETE", f"/v1/artifacts/{audio_id}", params={"cascade": "yes"})
        assert status == 400
        status, deleted, _, _ = await core(stack, "DELETE", f"/v1/artifacts/{audio_id}",
                                           params={"cascade": "true", "origin": "user"})
        assert status == 200 and len(deleted["deleted"]) == 5 and deleted["orphan_folders"] == 0


async def test_activity_tail_is_a_cursor_over_the_open_session(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        await recorded(stack)
        _, first, raw, _ = await core(stack, "GET", "/v1/activity", params={"limit": "3"})
        assert len(first["events"]) == 3 and first["latest_seq"] >= first["events"][-1]["seq"]
        _, more, _, _ = await core(stack, "GET", "/v1/activity", params={"after_seq": str(first["events"][-1]["seq"])})
        assert more["events"][0]["seq"] > first["events"][-1]["seq"]
        assert all(event["jarvis_session_id"] == first["jarvis_session_id"] for event in more["events"])
        assert_clean(stack, raw)


# ------------------------------------------------------------------ aucun chemin absolu


@pytest.mark.parametrize("value, expected", [
    ("C:\\Users\\x\\data\\a.wav", REDACTED_PATH),
    ("ffmpeg at C:/Tools/ffmpeg.exe failed", f"ffmpeg at {REDACTED_PATH} failed"),
    ("\\\\server\\share\\x", REDACTED_PATH),
    ("/home/user/data/a.wav", REDACTED_PATH),
    ("\\\\.\\DISPLAY1", "\\\\.\\DISPLAY1"),
    ("artifacts/jart_x/source.wav", "artifacts/jart_x/source.wav"),
    ("sessions/jsess_x/contexts/jctx_y", "sessions/jsess_x/contexts/jctx_y"),
    # QA Slice 09 : jusqu'au bout du chemin, espaces d'un profil Windows compris, racines connues.
    ("C:\\Users\\Jean Dupont\\AppData\\Local\\a.wav", REDACTED_PATH),
    ("open C:\\Users\\Jean Dupont\\AppData\\a.wav failed", f"open {REDACTED_PATH} failed"),
    ("see \\Users\\x\\data now", f"see {REDACTED_PATH} now"),
    ("cannot read /home/jean/data/a.wav today", f"cannot read {REDACTED_PATH} today"),
    ("at /Users/jean/Library/x.wav", f"at {REDACTED_PATH}"),
    ("\\\\?\\C:\\Users\\Jean Dupont\\x.wav", REDACTED_PATH),
    ("\\\\server\\share\\Jean Dupont\\x", REDACTED_PATH),
    ("in ~/data/x.wav", f"in {REDACTED_PATH}"),
    ("version 1:2 at http://x/y", "version 1:2 at http://x/y"),
    # QA rework 3 : chemin cité par `repr` (barres obliques inverses doublées), masqué d'un tenant.
    ("open 'C:\\\\Users\\\\Clarice\\\\AppData\\\\a.wav' failed", f"open '{REDACTED_PATH}' failed"),
    ("'D:\\\\Clarice\\\\jarvis\\\\data\\\\a.wav'", f"'{REDACTED_PATH}'"),
    ("'E:\\\\Jean Dupont\\\\x.wav'", f"'{REDACTED_PATH}'"),
    ("'\\\\\\\\?\\\\C:\\\\Users\\\\Jean Dupont\\\\x.wav'", f"'{REDACTED_PATH}'"),
    ("'\\\\\\\\server\\\\share\\\\Jean Dupont\\\\x'", f"'{REDACTED_PATH}'"),
    ("'\\\\\\\\.\\\\DISPLAY1'", "'\\\\\\\\.\\\\DISPLAY1'"),
])
def test_redact_paths_masks_absolute_paths_and_keeps_relative_refs(value, expected):
    assert redact_paths({"a": [value]}) == {"a": [expected]}
    assert "Dupont" not in json.dumps(redact_paths(value))


@pytest.mark.parametrize("path", [
    "C:\\Users\\Clarice\\AppData\\Local\\a.wav", "D:\\Clarice\\jarvis\\data\\a.wav",
    "E:\\Jean Dupont\\x.wav", "\\\\server\\share\\Jean Dupont\\x"])
def test_redaction_masks_whole_path_quoted_by_an_os_error(path):
    message = str(PermissionError(13, "Accès refusé", path))  # le chemin y est un `repr` : `\\` doublés
    redacted = redact_paths(message)
    assert redacted == f"[Errno 13] Accès refusé: '{REDACTED_PATH}'"
    assert "Clarice" not in redacted and "Dupont" not in redacted


def test_redaction_keeps_user_authored_fields_only_at_the_top_level():
    value = {"title": "Notes C:\\Users\\x", "runtime_metadata": {"title": "C:\\Users\\x\\y"}}
    assert redact_paths(value, keep=capture_api.USER_AUTHORED_FIELDS) == {
        "title": "Notes C:\\Users\\x", "runtime_metadata": {"title": REDACTED_PATH}}


# ------------------------------------------------------------------ rework QA Slice 09


async def test_a_context_title_written_by_the_user_round_trips_unchanged(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        title = "Notes C:\\Users\\x"
        status, created, _, _ = await core(stack, "POST", "/v1/contexts", json={"title": title})
        assert status == 201 and created["context"]["title"] == title
        _, listed, _, _ = await core(stack, "GET", "/v1/contexts")
        assert [entry["context"]["title"] for entry in listed["contexts"]][-1] == title
        _, current, _, _ = await core(stack, "GET", "/v1/contexts/current")
        assert current["context"]["title"] == title


async def test_an_error_message_never_carries_an_absolute_path(tmp_path):
    """Mutant M9-08 : le message d'un refus est masqué comme une métadonnée."""

    async with CaptureStack(tmp_path) as stack:
        status, answer, raw, _ = await core(stack, "GET", "/v1/captures/status",
                                            params={"C:\\Users\\Jean Dupont\\secret": "1"})
        assert (status, answer["error"]["code"]) == (400, "invalid_request")
        assert REDACTED_PATH in answer["error"]["message"] and "Dupont" not in raw.decode("utf-8")


@pytest.mark.parametrize("header", ["bytes=" + "9" * 5000 + "-", "bytes=0-" + "9" * 20, "bytes=-" + "1" * 4300],
                         ids=["5000-digit-start", "20-digit-end", "4300-digit-suffix"])
async def test_a_range_with_absurd_digits_is_416_never_a_python_error(tmp_path, header):
    async with CaptureStack(tmp_path) as stack:
        _, shot, _, _ = await core(stack, "POST", "/v1/captures/screenshot", json={})
        status, refused, raw, headers = await core(stack, "GET", f"/v1/artifacts/{shot['artifact']['artifact_id']}/payload",
                                                   headers={"Range": header})
        assert (status, refused["error"]["code"]) == (416, "artifact_range_invalid")
        assert headers["Content-Range"].startswith("bytes */") and b"int" not in raw


async def test_forward_paging_never_skips_the_rest_of_a_clipped_segment(tmp_path):
    async with CaptureStack(tmp_path) as stack:
        capture = await recorded(stack)
        route = f"/v1/captures/{capture['capture_id']}/transcript"
        pieces: dict[int, str] = {}
        cursor: dict[str, str] = {"after_seq": "0"}
        for _ in range(20):
            status, page, _, _ = await core(stack, "GET", route, params={**cursor, "max_chars": "5"})
            assert status == 200, page
            for segment in page["segments"]:
                assert segment.get("char_offset", 0) == len(pieces.get(segment["seq"], ""))
                pieces[segment["seq"]] = pieces.get(segment["seq"], "") + segment["text"]
            if not page["truncated"] and not page["next_char_offset"]:
                break
            cursor = {"after_seq": str(page["next_after_seq"])}
            if page["next_char_offset"]:
                cursor["char_offset"] = str(page["next_char_offset"])
        assert [pieces[seq] for seq in sorted(pieces)] == ["phrase 1", "phrase 2", "phrase 3"]
        status, alone, _, _ = await core(stack, "GET", route, params={"char_offset": "3"})
        assert (status, alone["error"]["code"]) == (400, "invalid_request")


async def test_status_never_lists_an_open_capture_as_recent(tmp_path):
    """Mutant M9-20."""

    async with CaptureStack(tmp_path) as stack:
        _, shot, _, _ = await core(stack, "POST", "/v1/captures/screenshot", json={})
        _, started, _, _ = await core(stack, "POST", "/v1/captures/start", json={"channel": "screen"})
        _, status, _, _ = await core(stack, "GET", "/v1/captures/status", params={"recent": "5"})
        assert [c["capture_id"] for c in status["captures"]] == [started["capture"]["capture_id"]]
        assert [c["capture_id"] for c in status["recent"]] == [shot["capture"]["capture_id"]]
        await core(stack, "POST", f"/v1/captures/{started['capture']['capture_id']}/stop")

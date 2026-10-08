"""Core routes, typed client and Control Center relay of the authoring planner (jarvis-interactive-presentation-studio, Slice 11).

Real Core (`JarvisCoreApplication`) behind the real `LocalProtocolServer`, real Control Center in front of it: statuses and codes,
the full report of a refused draft carried as a result (not a bare envelope), a dry run that writes nothing, the actor forced to `user`
by the relay, the origin guard, a journal without content. Contract: `docs/presentation-studio.md` > *Authoring contract (Slice 11)*.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from jarvis.domain.presentation_studio_authoring import MAX_AUTHORING_BODY_BYTES
from jarvis.protocol import client as client_module
from jarvis.protocol.client import CoreProtocolError
from jarvis.protocol.presentation_studio_authoring_routes import AUTHORING_PREFIX, PresentationStudioAuthoringRoutes
from jarvis.runtime.presentation_studio_authoring_relay import AUTHORING_ROUTE, PresentationStudioAuthoringRelayRoutes
from tests.fakes import presentation_studio_fake_author as fa
from tests.unit.test_presentation_studio_routes import AUTH, Core

ROOT = Path(__file__).resolve().parents[2]


def request_body(workflow="directed", **extra):
    return {"brief": fa.brief(workflow), "draft": fa.good_deck(), **extra}


async def post(core, verb, body, *, relay=False, **kwargs):
    if relay:
        status, payload, _ = await core.stack.call("POST", f"{AUTHORING_ROUTE}/{verb}", json=body, **kwargs)
        return status, payload
    async with core.http.post(f"{core.stack.core_url}{AUTHORING_PREFIX}/{verb}", headers=AUTH, json=body, **kwargs) as response:
        return response.status, await response.json(content_type=None)


async def presentations(core):
    status, listing = await core.call("GET", "")
    assert status == 200
    return listing["presentations"]


# ------------------------------------------------------------------ the table and the parity

def test_the_route_table_the_prefixes_and_the_relay_surface():
    routes = [(r.method, r.path) for r in PresentationStudioAuthoringRoutes(object()).routes()]
    assert routes == [("POST", AUTHORING_PREFIX + "/check"), ("POST", AUTHORING_PREFIX + "/assemble"),
                      ("GET", AUTHORING_PREFIX + "/reconcile"), ("POST", AUTHORING_PREFIX + "/finalize")]
    assert AUTHORING_PREFIX == client_module.AUTHORING_PREFIX == "/v1/presentation-studio/authoring"
    assert AUTHORING_PREFIX in client_module.FORWARDABLE_PREFIXES
    relay = PresentationStudioAuthoringRelayRoutes(transport=lambda: None, journal=None)  # type: ignore[arg-type]
    mapped = [(r.method, "/v1/presentation-studio" + r.path[len("/api/presentation-studio"):]) for r in relay.routes()]
    assert sorted(mapped) == sorted([routes[0], routes[1], routes[3]]), "the page reaches check, assemble and finalize, each with a forced actor"
    assert not any(path.endswith("/reconcile") for _, path in mapped), "the read-only recovery report is never relayed to the page"
    assert set(vars(relay)) == {"_transport", "_journal"}               # no state in the Control Center
    assert relay.MAX_BODY_BYTES == MAX_AUTHORING_BODY_BYTES


def test_both_routes_are_documented_with_their_statuses():
    page = (ROOT / "docs" / "presentation-studio.md").read_text(encoding="utf-8")
    section = page[page.index("## Authoring contract (Slice 11)"):]
    for fragment in ("/v1/presentation-studio/authoring/check", "/v1/presentation-studio/authoring/assemble",
                     "/api/presentation-studio/authoring/check", "/api/presentation-studio/authoring/assemble",
                     "/v1/presentation-studio/authoring/reconcile", "/v1/presentation-studio/authoring/finalize",
                     "/api/presentation-studio/authoring/finalize", "presentation_studio_draft_refused",
                     "LocalCoreClient.presentation_studio_authoring_finalize",
                     "LocalCoreClient.presentation_studio_authoring_check", "LocalCoreClient.presentation_studio_authoring_assemble",
                     "LocalCoreClient.presentation_studio_authoring_reconcile"):
        assert fragment in section, fragment
    assert re.search(r"authoring/assemble.*201", section) and "400" in section


# ------------------------------------------------------------------ Core

async def test_the_token_is_required(tmp_path):
    async with Core(tmp_path) as core:
        for verb in ("check", "assemble"):
            async with core.http.post(f"{core.stack.core_url}{AUTHORING_PREFIX}/{verb}", json=request_body()) as response:
                assert response.status == 401
        async with core.http.get(f"{core.stack.core_url}{AUTHORING_PREFIX}/reconcile") as response:
            assert response.status == 401


async def test_reconcile_is_a_read_only_report_and_is_not_reachable_from_the_page(tmp_path):
    async with Core(tmp_path) as core:
        status, _, _ = await core.stack.call("GET", f"{AUTHORING_ROUTE}/reconcile")
        assert status == 404                                                             # the Control Center relays no such route
        async with core.http.get(f"{core.stack.core_url}{AUTHORING_PREFIX}/reconcile", headers=AUTH) as response:
            report = await response.json()
            assert response.status == 200 and report["unreferenced_prefabs"] == [] and report["pins_known"] is True
        status, delivered = await post(core, "assemble", request_body())
        assert status == 201
        assert (await core.client.presentation_studio_authoring_reconcile())["unreferenced_prefabs"] == []   # pinned by the delivered one
        async with core.http.get(f"{core.stack.core_url}{AUTHORING_PREFIX}/reconcile?x=1", headers=AUTH) as response:
            assert response.status == 400


async def test_check_is_a_dry_run_that_writes_and_publishes_nothing(tmp_path):
    async with Core(tmp_path) as core:
        status, answer = await post(core, "check", request_body())
        assert status == 200 and answer["status"] == "checked" and answer["ok"] is True and answer["workflow"] == "directed"
        assert answer["report"]["failures"] == [] and answer["report"]["stats"]["scenes"] == 12
        assert await presentations(core) == []
        found = await core.stack.core.prefabs.search("presentation-studio.", class_filter="custom")
        assert found == ()
        bad = request_body()
        bad["draft"]["scenes"][0]["data"]["body"] = "Lorem ipsum"
        status, answer = await post(core, "check", bad)
        assert status == 200 and answer["ok"] is False and answer["report"]["failures"][0]["code"] == "placeholder_text"


async def test_assemble_delivers_201_and_the_result_is_readable_through_the_ordinary_routes(tmp_path):
    async with Core(tmp_path) as core:
        status, answer = await post(core, "assemble", request_body())
        assert status == 201 and answer["status"] == "delivered" and answer["presentation_id"].startswith("pst_")
        pid, vid = answer["presentation_id"], answer["active_variant_id"]
        status, loaded = await core.call("GET", f"/{pid}")
        assert status == 200 and len(loaded["variants"][0]["scenes"]) == 12
        status, score = await core.call("GET", f"/{pid}/variants/{vid}/score")
        assert status == 200 and score["problems"] == [] and len(score["score"]["items"]) == 12
        status, art = await core.call("GET", f"/{pid}/variants/{vid}/art-direction")
        assert status == 200 and art["art_direction"]["profile"]["provenance"]["origin"] == "inferred"
        scene_id = answer["scenes"][3]["scene_id"]
        status, controls = await core.call("GET", f"/{pid}/variants/{vid}/scenes/{scene_id}/controls")
        assert status == 200 and controls["problems"] == [] and len(controls["controls"]) == 3
        status, graph = await core.call("GET", f"/{pid}/graph?check=1")
        assert status == 200 and graph["check"]["clean"] is True


async def test_a_refused_draft_is_a_400_result_with_the_full_report_and_nothing_is_written(tmp_path):
    async with Core(tmp_path) as core:
        body = request_body()
        for code in ("placeholder_text", "cue_weak", "duration_off"):
            dict(fa.VIOLATIONS)[code](body["brief"], body["draft"])
        status, answer = await post(core, "assemble", body)
        assert status == 400 and answer["status"] == "refused"
        assert answer["error"]["code"] == "presentation_studio_draft_refused" and set(answer) == {"status", "workflow", "report", "error"}
        assert {f["code"] for f in answer["report"]["failures"]} == {"placeholder_text", "cue_weak", "duration_off"}
        assert await presentations(core) == []


async def test_the_exploratory_workflow_over_http(tmp_path):
    async with Core(tmp_path) as core:
        brief, draft = fa.exploratory(3)
        status, answer = await post(core, "assemble", {"brief": brief, "draft": draft})
        assert status == 201 and [v["draft"] for v in answer["variants"]] == [True, True, True]
        assert (await presentations(core))[0]["variant_count"] == 3


@pytest.mark.parametrize("payload", [
    {"draft": {}}, {"brief": {}, "draft": {}, "surprise": 1}, {"brief": {}, "draft": {}, "actor": "root"}, [],
])
async def test_a_bad_envelope_is_a_coded_400_never_a_500(tmp_path, payload):
    async with Core(tmp_path) as core:
        for verb in ("check", "assemble"):
            status, answer = await post(core, verb, payload)
            assert status == 400 and answer["error"]["code"] == "presentation_studio_invalid", (verb, answer)


async def test_a_body_that_is_not_strict_json_or_is_too_big_is_invalid_request(tmp_path):
    async with Core(tmp_path) as core:
        for raw in (b"{not json", b'{"brief": {}, "brief": {}}', b'{"brief": NaN}', b""):
            async with core.http.post(f"{core.stack.core_url}{AUTHORING_PREFIX}/check", headers=AUTH, data=raw) as response:
                assert response.status == 400 and (await response.json())["error"]["code"] == "invalid_request"
        big = b'{"brief": "' + b"x" * (MAX_AUTHORING_BODY_BYTES + 10) + b'"}'
        async with core.http.post(f"{core.stack.core_url}{AUTHORING_PREFIX}/assemble", headers=AUTH, data=big) as response:
            assert response.status == 400 and (await response.json())["error"]["code"] == "invalid_request"
        assert await presentations(core) == []


async def test_core_records_a_brain_actor_when_the_tool_layer_will_send_one(tmp_path):
    async with Core(tmp_path) as core:
        status, answer = await post(core, "assemble", request_body(actor="brain"))
        assert status == 201 and answer["provenance"]["actor"] == "brain"


# ------------------------------------------------------------------ the typed client

async def test_the_typed_client_returns_both_outcomes_and_raises_for_a_bad_envelope(tmp_path):
    async with Core(tmp_path) as core:
        checked = await core.client.presentation_studio_authoring_check(request_body())
        assert checked["status"] == "checked" and checked["ok"] is True
        bad = request_body()
        dict(fa.VIOLATIONS)["da_missing"](bad["brief"], bad["draft"])
        refused = await core.client.presentation_studio_authoring_assemble(bad)
        assert refused["status"] == "refused" and refused["report"]["failures"][0]["code"] == "da_missing"      # a result, not an exception
        delivered = await core.client.presentation_studio_authoring_assemble(request_body())
        assert delivered["status"] == "delivered" and delivered["presentation_id"].startswith("pst_")
        with pytest.raises(CoreProtocolError) as caught:
            await core.client.presentation_studio_authoring_assemble({"draft": {}})
        assert caught.value.status == 400 and caught.value.code == "presentation_studio_invalid"


# ------------------------------------------------------------------ the Control Center relay

async def test_the_relay_forces_the_actor_to_user_whatever_the_page_says(tmp_path):
    async with Core(tmp_path) as core:
        for claimed in ("brain", "system", None):
            body = request_body()
            if claimed:
                body["actor"] = claimed
            status, answer = await post(core, "assemble", body, relay=True)
            assert status == 201 and answer["provenance"]["actor"] == "user", (claimed, answer)
        status, answer = await post(core, "check", request_body(actor="brain"), relay=True)
        assert status == 200 and answer["ok"] is True
        _, graph = await core.call("GET", f"/{(await presentations(core))[0]['presentation_id']}/graph")
        assert {n["created_by"] for n in graph["nodes"]} == {"user"}


async def test_the_relay_passes_a_refusal_through_with_its_report(tmp_path):
    async with Core(tmp_path) as core:
        body = request_body()
        dict(fa.VIOLATIONS)["arc_incomplete"](body["brief"], body["draft"])
        status, answer = await post(core, "assemble", body, relay=True)
        assert status == 400 and answer["status"] == "refused" and answer["report"]["failures"][0]["code"] == "arc_incomplete"
        assert await presentations(core) == []


@pytest.mark.parametrize("headers", [{"Origin": "null"}, {"Origin": "https://evil.example"},
                                     {"Sec-Fetch-Site": "cross-site"}, {"Host": "evil.example"}])
async def test_a_frame_or_a_foreign_origin_cannot_author(tmp_path, headers):
    async with Core(tmp_path) as core:
        for verb in ("check", "assemble"):
            status, payload = await post(core, verb, request_body(), relay=True, headers=headers)
            assert status == 403, (verb, payload)
        assert await presentations(core) == []


async def test_the_relay_rejects_malformed_bodies_and_exposes_no_other_write(tmp_path):
    async with Core(tmp_path) as core:
        call = core.stack.call
        status, payload, _ = await call("POST", f"{AUTHORING_ROUTE}/check", data=b"[1]", headers={"Content-Type": "application/json"})
        assert status == 400 and payload["error"]["code"] == "invalid_request"
        status, payload, _ = await call("POST", f"{AUTHORING_ROUTE}/check?x=1", json=request_body())
        assert status == 400 and payload["error"]["code"] == "invalid_request"
        status, _, _ = await call("GET", f"{AUTHORING_ROUTE}/check")
        assert status in (404, 405)
        status, _, _ = await call("POST", f"{AUTHORING_ROUTE}/delete", json={})
        assert status == 404                                                           # no other write is exposed


async def test_the_relay_journal_never_holds_a_title_a_phrase_or_a_value(tmp_path):
    async with Core(tmp_path) as core:
        marker = "TITRE-PRIVE-A-NE-PAS-JOURNALISER"
        body = request_body()
        body["draft"]["scenes"][1]["title"] = marker
        body["draft"]["score"]["items"][1]["text"] = f"{marker} je dis ceci"
        status, _ = await post(core, "assemble", body, relay=True)
        assert status == 201
        rows = [e for e in core.stack.trace() if str(e.get("kind", "")).startswith("presentation_studio.request")]
        mine = [r for r in rows if r["data"].get("action") == "studio_authoring_assemble"]
        assert mine and mine[0]["data"]["status"] == 201 and mine[0]["data"]["result"] == "delivered"
        assert marker not in json.dumps(core.stack.trace(), default=str)


# ------------------------------------------------------------------ finalize (QA-1 P1)

async def exploratory_over_http(core, mutate=None):
    brief, draft = fa.exploratory(3)
    if mutate:
        mutate(brief, draft)
    status, answer = await post(core, "assemble", {"brief": brief, "draft": draft})
    assert status == 201, answer
    return answer


async def test_finalize_over_http_core_client_and_relay(tmp_path):
    async with Core(tmp_path) as core:
        answer = await exploratory_over_http(core)
        pid, second, third = answer["presentation_id"], answer["variants"][1]["variant_id"], answer["variants"][2]["variant_id"]
        status, done = await post(core, "finalize", {"presentation_id": pid, "variant_id": second})
        assert status == 200 and done["status"] == "finalized" and done["activated"] is True and done["report"]["ok"] is True
        client = await core.client.presentation_studio_authoring_finalize({"presentation_id": pid, "variant_id": third, "actor": "brain"})
        assert client["status"] == "finalized"
        status, relayed = await post(core, "finalize", {"presentation_id": pid, "variant_id": second, "actor": "brain"}, relay=True)
        assert status == 200 and relayed["status"] == "finalized"
        _, graph = await core.call("GET", f"/{pid}/graph")
        assert graph["active_variant_id"] == second
        rows = [e for e in core.stack.trace() if str(e.get("kind", "")).startswith("presentation_studio.request")]
        assert any(r["data"].get("action") == "studio_authoring_finalize" and r["data"]["result"] == "finalized" for r in rows)


async def test_finalize_refusal_is_a_400_result_through_core_client_and_relay(tmp_path):
    def thin(brief, draft):
        draft["scenes"][1].update(title="Alpha", props={"headline": "-"}, data={"body": "..."})

    async with Core(tmp_path) as core:
        answer = await exploratory_over_http(core, thin)
        pid, second = answer["presentation_id"], answer["variants"][1]["variant_id"]
        status, refused = await post(core, "finalize", {"presentation_id": pid, "variant_id": second})
        assert status == 400 and refused["status"] == "refused" and refused["error"]["code"] == "presentation_studio_draft_refused"
        assert any(f["code"] == "content_thin" for f in refused["report"]["failures"])
        assert (await core.client.presentation_studio_authoring_finalize({"presentation_id": pid, "variant_id": second}))["status"] == "refused"
        status, relayed = await post(core, "finalize", {"presentation_id": pid, "variant_id": second}, relay=True)
        assert status == 400 and relayed["status"] == "refused"
        for bad in ({}, {"presentation_id": pid}, {"presentation_id": "nope", "variant_id": second}):
            status, payload = await post(core, "finalize", bad)
            assert status in (400, 404) and "error" in payload

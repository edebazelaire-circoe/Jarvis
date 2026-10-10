"""Routes Core de l'edition de source d'une scene (Slice 14) : lecture de la source par l'agent, corps Remotion, refus types.

Vrai Core (HTML par defaut, pas de composition Remotion) derriere le vrai `LocalProtocolServer`. La compilation reelle est dans
`test_remotion_source_edit_real.py`.
"""

from __future__ import annotations

import pytest

from tests.unit.test_presentation_studio_edit_routes import S1, new_presentation
from tests.unit.test_presentation_studio_reload_routes import request
from tests.unit.test_presentation_studio_routes import Core


async def test_the_agent_reads_a_slidecar_scene_source_and_a_remotion_body_is_refused_for_it(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, revision = await new_presentation(core)
        status, source = await core.call("GET", f"/{pid}/variants/{vid}/scenes/{S1}/source")
        assert status == 200 and source["engine"] == "slidecar" and set(source["files"]) == {"template", "style", "behavior"}, source
        assert source["scene_id"] == S1 and source["basis"] == {"variant_revision": revision} and source["manifest"]["id"]
        assert source["prefab"] == {"id": "jarvis.window", "version": 1}
        url = f"/{pid}/variants/{vid}/source-edits"
        status, refused = await core.call("POST", url, json=request(revision, {"sources": {"src/Scene.tsx": "export default () => null"}}))
        assert status == 400 and refused["status"] == "refused_validation" and "Slidecar" in refused["message"], refused
        status, nothing = await core.call("POST", url, json=request(revision, {"sources": {}}))
        assert status == 400 and nothing["error"]["code"] == "presentation_studio_invalid" and "no change" in nothing["error"]["message"]
        status, mixed = await core.call("POST", url, json=request(revision, {"style": "p{}", "sources": {"src/a.ts": "x"}}))
        assert status == 400 and "not both" in mixed["error"]["message"]
        status, unknown = await core.call("GET", f"/{pid}/variants/{vid}/scenes/pss_00000000ffff/source")
        assert status == 404 and unknown["error"]["code"] == "presentation_studio_unknown_scene"


async def test_the_scene_source_route_rejects_query_strings(tmp_path):
    async with Core(tmp_path) as core:
        pid, vid, _ = await new_presentation(core)
        status, answer = await core.call("GET", f"/{pid}/variants/{vid}/scenes/{S1}/source?x=1")
        assert status == 400, answer

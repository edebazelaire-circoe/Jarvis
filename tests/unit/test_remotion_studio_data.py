"""The Studio and the render hand a Remotion scene the same `data` input as the Player (Slice 22, release journey).

A scene authored by the planner reads `props.data.*`. The Player gives it `inputProps.data`; the render (`presentation_render_plan`) and the
Studio work copy (`prefab_source_provider` -> `plan_workspace`) did not, so the export and the Studio view of every authored deck failed with a
`TypeError` in the browser. Found by `test_remotion_release_flows.py` (export) and fixed with the same rule in both places.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json

from jarvis.adapters.file_prefab_library import FilePrefabLibrary
from jarvis.core.prefab_service import PrefabService
from jarvis.core.remotion_studio_service import prefab_source_provider
from jarvis.domain.remotion_studio import StudioPin, plan_workspace
from tests.fakes.prefabs import install_version
from tests.fakes.remotion_scene import PROPS_SCHEMA, scene_candidate

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
DATA_SCHEMA = {"type": "object", "properties": {"body": {"type": "string", "default": "", "max_length": 200}}}


async def service(tmp_path) -> PrefabService:
    package, data = tmp_path / "package", tmp_path / "data"
    package.mkdir()
    data.mkdir()
    install_version(package, "jarvis.counter", title="Base counter")
    return PrefabService(FilePrefabLibrary(package, data), clock=lambda: NOW)


async def test_the_studio_work_copy_carries_the_sample_data_of_the_scene(tmp_path):
    prefabs = await service(tmp_path)
    published = await prefabs.save(scene_candidate("lab.rm", data=DATA_SCHEMA, props=PROPS_SCHEMA,
                                                   sample={"props": {"title": "A"}, "data": {"body": "texte d'exemple"}}), actor="user")
    source, props = await prefab_source_provider(prefabs)(StudioPin("lab.rm", published.version))
    assert props["data"] == {"body": "texte d'exemple"} and props["title"] == "A"
    root = plan_workspace(source, props)["studio-root.tsx"].decode("utf-8")
    assert json.dumps({"body": "texte d'exemple"}, ensure_ascii=True, sort_keys=True) in root, "the composition's defaultProps carry data"


async def test_a_scene_without_data_gets_no_data_key_in_the_studio(tmp_path):
    prefabs = await service(tmp_path)
    published = await prefabs.save(scene_candidate("lab.plain"), actor="user")
    _, props = await prefab_source_provider(prefabs)(StudioPin("lab.plain", published.version))
    assert "data" not in props

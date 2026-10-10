"""Service, routes et câblage de l'import d'un modèle Remotion amont (Slice 18).

Vrai `PrefabService` + vraie bibliothèque sur dossiers temporaires, faux téléchargeur (aucun réseau). Contrat :
`docs/remotion-import.md` §6-8 ; code : `jarvis/core/remotion_import_service.py`, `jarvis/protocol/remotion_import_routes.py`.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.adapters.fake_upstream_fetcher import FakeUpstreamFetcher
from jarvis.adapters.file_prefab_library import LIBRARY_DIR, FilePrefabLibrary
from jarvis.core.prefab_service import PrefabService
from jarvis.core.remotion_import_service import RemotionImportService, status_of
from jarvis.domain.presentation_studio_checks import PresentationStudioError, PresentationStudioErrorCode
from jarvis.domain.remotion_import import ImportErrorCode as E
from jarvis.domain.remotion_upstream import UpstreamOrigin, UpstreamRefusal
from jarvis.ports.prefabs import PrefabStoreError
from jarvis.protocol.remotion_import_routes import PREFIX, RemotionImportProtocolRoutes
from tests.fakes.prefabs import install_version
from tests.fakes.remotion_scene import ENGINE, scene_candidate
from tests.fakes.upstream_archive import GPL, SHA, good_project, link, make_tarball

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
PRESENTATION = "pst_0123456789abcdef0123456789abcdef"
URL = "https://github.com/someone/demo"
ORIGIN = UpstreamOrigin("someone", "demo", SHA)


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None) -> None:
        self.events.append((kind, level, dict(data or {})))

    def kinds(self):
        return [kind for kind, _, _ in self.events]


class FakeStudio:
    def __init__(self, known=(PRESENTATION,)) -> None:
        self.known = set(known)

    async def get(self, presentation_id):
        if presentation_id not in self.known:
            raise PresentationStudioError(PresentationStudioErrorCode.INVALID_PRESENTATION, "unknown presentation")
        return object()


@pytest.fixture
def world(tmp_path: Path):
    package, data = tmp_path / "package", tmp_path / "data"
    package.mkdir()
    data.mkdir()
    install_version(package, "jarvis.counter", title="Base counter")
    recorder = Recorder()
    prefabs = PrefabService(FilePrefabLibrary(package, data), diagnostics=recorder, clock=lambda: NOW)
    fetcher = FakeUpstreamFetcher()
    fetcher.add(ORIGIN, make_tarball(good_project()))
    service = RemotionImportService(fetcher, prefabs, FakeStudio(), engine=lambda: ENGINE, allowed_owners=lambda: ("someone",),
                                    diagnostics=recorder, clock=lambda: NOW)
    return SimpleNamespace(service=service, prefabs=prefabs, fetcher=fetcher, recorder=recorder, data=data)


def body(**fields):
    return {"repo_url": URL, "commit": SHA, "presentation_id": PRESENTATION, **fields}


async def refusal(coro) -> UpstreamRefusal:
    with pytest.raises(UpstreamRefusal) as caught:
        await coro
    return caught.value


def library_folders(world) -> list[str]:
    root = world.data / LIBRARY_DIR
    return sorted(p.name for p in root.iterdir()) if root.exists() else []


# ------------------------------------------------------------------ plan et import

async def test_a_plan_downloads_validates_and_writes_nothing(world):
    answer = await world.service.plan({k: v for k, v in body().items() if k != "presentation_id"})
    assert answer["publishes"] is False and answer["guards_passed"] is True and answer["compiled"] is False and answer["plan"]["license"]["spdx"] == "MIT"
    assert world.fetcher.requests == [ORIGIN.archive_url]
    assert library_folders(world) == []
    assert "core.remotion_import.planned" in world.recorder.kinds()


async def test_an_import_publishes_one_version_scoped_to_the_presentation_and_never_to_the_shared_library(world):
    result = await world.service.import_template(body(scene_id="pss_aaaaaaaaaaaa"))
    prefab = result["prefab"]
    assert prefab["prefab_id"] == "presentation-studio.p0123456789ab.saaaaaaaaaaaa" and prefab["version"] == 1
    assert result["scope"] == "presentation" and result["published_to_library"] is False and result["presentation_id"] == PRESENTATION
    assert library_folders(world) == [prefab["prefab_id"]]
    # le catalogue lit la provenance écrite par Core ; rien d'une base ni d'un prefab « studio-template.* » n'est créé
    manifest = await world.prefabs.manifest(prefab["prefab_id"], 1)
    view = manifest.catalog_view()
    assert view["declared"] is True and view["license"] == "MIT" and view["runtime_license"].startswith("Remotion License")
    upstream = view["upstream"]
    assert upstream["commit"] == SHA and upstream["imported_at"] == "2026-10-10T12:00:00Z" and upstream["name"] == "someone/demo"
    assert upstream["changes"] and len(upstream["archive_sha256"]) == 64
    assert view["compatibility"] == {"slidecar": "unsupported", "remotion": "native"}
    assert "core.remotion_import.imported" in world.recorder.kinds()


async def test_the_library_folder_holds_only_the_scene_files_no_package_json_no_node_modules(world):
    result = await world.service.import_template(body())
    folder = world.data / LIBRARY_DIR / result["prefab"]["prefab_id"] / "1"
    names = sorted(str(p.relative_to(folder)).replace("\\", "/") for p in folder.rglob("*") if p.is_file())
    assert "src/Scene.tsx" in names and "src/upstream/license.json" in names and "public/logo.png" in names
    assert not any("package" in n.split("/")[-1] and n.endswith(".json") and not n.endswith("manifest.json") and "upstream" not in n for n in names)
    assert not any("node_modules" in n for n in names)


async def test_a_new_scene_id_is_minted_when_none_is_given_and_two_imports_stay_apart(world):
    first = await world.service.import_template(body())
    second = await world.service.import_template(body())
    assert first["scene_id"] != second["scene_id"] and first["prefab"]["prefab_id"] != second["prefab"]["prefab_id"]
    assert first["scene_id"].startswith("pss_")


async def test_a_second_import_into_the_same_scene_is_a_new_immutable_version(world):
    first = await world.service.import_template(body(scene_id="pss_bbbbbbbbbbbb"))
    folder = world.data / LIBRARY_DIR / first["prefab"]["prefab_id"] / "1"
    before = {p.name: p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    second = await world.service.import_template(body(scene_id="pss_bbbbbbbbbbbb"))
    assert second["prefab"]["version"] == 2
    assert {p.name: p.read_bytes() for p in folder.rglob("*") if p.is_file()} == before


# ------------------------------------------------------------------ refus : rien ne se publie

async def test_an_origin_outside_the_allowlist_opens_no_connection_and_writes_nothing(world):
    for url in ("https://gitlab.com/someone/demo", "https://github.com/stranger/demo", "http://github.com/someone/demo"):
        error = await refusal(world.service.import_template(body(repo_url=url)))
        assert error.code in (E.ORIGIN_NOT_ALLOWED, E.ORIGIN_INVALID)
    assert world.fetcher.requests == [] and library_folders(world) == []


async def test_an_unpinned_commit_is_refused_before_any_connection(world):
    error = await refusal(world.service.import_template(body(commit="main")))
    assert error.code == E.COMMIT_NOT_PINNED and world.fetcher.requests == []


async def test_the_allowlist_is_read_at_each_import_so_a_setting_change_applies_without_restart(world):
    owners = ["someone"]
    world.service._owners = lambda: tuple(owners)
    await world.service.plan(body())
    owners[:] = ["other"]
    assert (await refusal(world.service.plan(body()))).code == E.ORIGIN_NOT_ALLOWED


@pytest.mark.parametrize("project_changes, code", [
    ({"LICENSE": GPL}, E.LICENSE_RESTRICTED),
    ({"src/lib/Badge.tsx": "import x from 'three';\nexport const Badge = () => null;\n"}, E.DEPENDENCY_REFUSED),
    ({"src/lib/Badge.tsx": "export const Badge = () => { fetch('x'); return null; };\n"}, E.SOURCE_GUARD),
])
async def test_a_refused_source_publishes_nothing_and_says_why(world, project_changes, code):
    files = good_project()
    files.update(project_changes)
    world.fetcher.add(ORIGIN, make_tarball(files))
    error = await refusal(world.service.import_template(body()))
    assert error.code == code and library_folders(world) == []
    refused = [data for kind, _, data in world.recorder.events if kind == "core.remotion_import.refused"]
    assert refused and refused[-1]["code"] == code and refused[-1]["commit"] == SHA


async def test_a_hostile_archive_is_refused_whole(world):
    hostile = make_tarball(good_project(), extra=[link(f"demo-{SHA}/src/evil.ts", "/etc/passwd")])
    world.fetcher.add(ORIGIN, hostile)
    assert (await refusal(world.service.import_template(body()))).code == E.ARCHIVE_LINK
    world.fetcher.add(ORIGIN, make_tarball(good_project(), comment="c" * 40))
    assert (await refusal(world.service.import_template(body()))).code == E.ARCHIVE_COMMIT_MISMATCH
    assert library_folders(world) == []


async def test_an_unknown_presentation_is_refused_and_nothing_is_published(world):
    error = await refusal(world.service.import_template(body(presentation_id="pst_" + "f" * 32)))
    assert error.code == "presentation_not_found" and library_folders(world) == [] and status_of(error.code) == 404


async def test_a_fetch_failure_is_typed_and_journaled(world):
    failing = RemotionImportService(FakeUpstreamFetcher(error=UpstreamRefusal("fetch_timeout", "slow")), world.prefabs, FakeStudio(),
                                    engine=lambda: ENGINE, allowed_owners=lambda: ("someone",), diagnostics=world.recorder)
    assert (await refusal(failing.plan(body()))).code == "fetch_timeout"
    assert any(kind == "core.remotion_import.refused" and data["code"] == "fetch_timeout" for kind, _, data in world.recorder.events)


async def test_only_one_import_runs_at_a_time(world):
    gate = asyncio.Event()

    class Slow(FakeUpstreamFetcher):
        def fetch(self, origin):
            import time
            time.sleep(0.2)
            return super().fetch(origin)

    slow = Slow()
    slow.add(ORIGIN, make_tarball(good_project()))
    service = RemotionImportService(slow, world.prefabs, FakeStudio(), engine=lambda: ENGINE, allowed_owners=lambda: ("someone",))
    first = asyncio.create_task(service.plan(body()))
    await asyncio.sleep(0.05)
    assert (await refusal(service.plan(body()))).code == "import_busy"
    assert (await first)["guards_passed"] is True
    gate.set()


# ------------------------------------------------------------------ la provenance vérifiée n'est écrite que par l'importeur

async def test_no_other_door_can_write_the_verified_provenance_keys(world):
    result = await world.service.import_template(body())
    manifest = await world.prefabs.manifest(result["prefab"]["prefab_id"], 1)
    plan_candidate = (await world.service.plan(body()))
    # reconstruire un candidat identique et le publier SANS passer par l'importeur
    from jarvis.domain.remotion_import import analyse_archive, parse_import_request
    request = parse_import_request(body(), allowed_owners=("someone",), need_presentation=True)
    candidate = analyse_archive(make_tarball(good_project()), request, engine=ENGINE, imported_at=NOW).candidate
    forged = json.loads(json.dumps(candidate))
    forged["manifest"]["id"] = "presentation-studio.p0123456789ab.scccccccccccc"
    with pytest.raises(PrefabStoreError) as caught:
        await world.prefabs.save(forged, actor="user")
    assert "importer only" in caught.value.message and plan_candidate["guards_passed"]
    # même un agent qui « décrit » une provenance vérifiable pour un prefab neuf est refusé ; la déclarer sans les clés vérifiées est permis
    declared = json.loads(json.dumps(forged))
    for key in ("commit", "archive_sha256", "imported_at", "changes", "source_sha256"):
        declared["manifest"]["catalog"]["upstream"].pop(key)
    declared["manifest"]["catalog"].pop("runtime_license")
    assert (await world.prefabs.save(declared, actor="user")).version == 1
    assert manifest.catalog.upstream.verified


async def revised(world, prefab_id, *, edit="// edited by someone else\n", path="src/lib/Badge.tsx", replace=False, actor="brain"):
    """Une révision de la source importée, publiée par `PrefabService.save` SANS l'importeur (le sondage du QA : un agent remplace du code)."""

    from jarvis.domain.remotion_import import analyse_archive, parse_import_request
    request = parse_import_request(body(), allowed_owners=("someone",), need_presentation=True)
    candidate = analyse_archive(make_tarball(good_project()), request, engine=ENGINE, imported_at=NOW).candidate
    candidate["manifest"]["id"] = prefab_id
    candidate["sources"][path] = edit if replace else candidate["sources"][path] + edit
    return candidate, (await world.prefabs.save(candidate, actor=actor)).version


async def test_a_revision_carries_the_origin_but_is_never_reported_intact(world):
    """B1 (laundering) : la provenance reportée ne vaut pas « vérifié » : la vue compare l'empreinte des fichiers courants à celle de
    l'import, dit « modifié depuis l'import » et nomme les fichiers ; l'origine reste comme historique."""

    result = await world.service.import_template(body(scene_id="pss_dddddddddddd"))
    prefab_id = result["prefab"]["prefab_id"]
    first = (await world.prefabs.get(prefab_id, 1)).to_dict(catalog=True)["catalog"]["upstream"]
    assert first["verified_intact"] is True and "modified_files" not in first and len(first["source_sha256"]) == 64
    candidate, version = await revised(world, prefab_id, edit="export const Badge = () => { return null; };\n", replace=True)
    assert version == 2
    for row in ((await world.prefabs.get(prefab_id, 2)).to_dict(catalog=True)["catalog"]["upstream"],
                next(row for row in await world.prefabs.search("", with_catalog=True, limit=50) if row.prefab_id == prefab_id).catalog["upstream"]):
        assert row["verified_intact"] is False and row["modified_files"] == ["src/lib/Badge.tsx"]
        # l'historique d'origine reste, daté, mais plus rien ne l'affirme pour ces fichiers
        assert row["commit"] == SHA and row["imported_at"] == "2026-10-10T12:00:00Z" and row["changes"] == first["changes"]
        assert row["archive_sha256"] == first["archive_sha256"] and row["source_sha256"] == first["source_sha256"]
    assert (await world.prefabs.get(prefab_id, 1)).to_dict(catalog=True)["catalog"]["upstream"]["verified_intact"] is True
    # ajouter ou retirer un fichier est aussi une modification
    extra = json.loads(json.dumps(candidate))
    extra["sources"]["src/lib/Extra.ts"] = "export const extra = 1;\n"
    extra["manifest"]["source"]["modules"] = sorted([*extra["manifest"]["source"]["modules"], "src/lib/Extra.ts"])
    assert (await world.prefabs.save(extra, actor="user")).version == 3
    third = (await world.prefabs.get(prefab_id, 3)).to_dict(catalog=True)["catalog"]["upstream"]
    assert third["verified_intact"] is False and third["modified_files"] == ["src/lib/Badge.tsx", "src/lib/Extra.ts"]
    # une révision qui REVIENT aux octets de l'import est de nouveau intacte (l'empreinte, pas l'histoire, décide)
    back = json.loads(json.dumps(candidate))
    back["sources"]["src/lib/Badge.tsx"] = (await world.prefabs.remotion_source(prefab_id, 1)).text("src/lib/Badge.tsx")
    assert (await world.prefabs.save(back, actor="user")).version == 4
    assert (await world.prefabs.get(prefab_id, 4)).to_dict(catalog=True)["catalog"]["upstream"]["verified_intact"] is True


async def test_a_revision_cannot_alter_the_origin_or_the_digest_only_carry_them(world):
    result = await world.service.import_template(body(scene_id="pss_eeeeeeeeeeee"))
    prefab_id = result["prefab"]["prefab_id"]
    candidate, _ = await revised(world, prefab_id)
    for key, value in (("commit", "f" * 40), ("source_sha256", "e" * 64), ("archive_sha256", "d" * 64), ("imported_at", "2030-01-01T00:00:00Z"),
                       ("changes", ["nothing happened"])):
        forged = json.loads(json.dumps(candidate))
        forged["manifest"]["catalog"]["upstream"][key] = value
        with pytest.raises(PrefabStoreError) as caught:
            await world.prefabs.save(forged, actor="brain")
        assert "importer only" in caught.value.message, key
    stripped = json.loads(json.dumps(candidate))
    stripped["manifest"]["catalog"]["upstream"] = {"name": "x/y", "url": "https://github.com/x/y"}
    with pytest.raises(PrefabStoreError):  # the engine licence cannot stay behind a dropped origin: both are Core-written
        await world.prefabs.save(stripped, actor="brain")
    stripped["manifest"]["catalog"].pop("runtime_license")
    assert (await world.prefabs.save(stripped, actor="brain")).version == 3  # dropping the claim is allowed: nothing is asserted anymore
    assert "verified_intact" not in (await world.prefabs.get(prefab_id, 3)).to_dict(catalog=True)["catalog"]["upstream"]


async def test_the_runtime_licence_is_core_written_like_the_upstream_keys(world):
    plain = scene_candidate("presentation-studio.p000000000009.s000000000009")
    plain["manifest"] = {**plain["manifest"], "schema_version": 3, "catalog": {
        "type": "composition", "compatibility": {"remotion": "native"}, "stack": ["react"], "license": "MIT",
        "runtime_license": "Remotion License (company licence may be required)"}}
    with pytest.raises(PrefabStoreError) as caught:
        await world.prefabs.save(plain, actor="user")
    assert "runtime_license" in caught.value.message
    plain["manifest"]["catalog"].pop("runtime_license")  # the author's own licence stays author-declared
    assert (await world.prefabs.save(plain, actor="user")).version == 1
    result = await world.service.import_template(body(scene_id="pss_ffffffffffff"))
    candidate, _ = await revised(world, result["prefab"]["prefab_id"])
    candidate["manifest"]["catalog"]["runtime_license"] = "Something else"
    with pytest.raises(PrefabStoreError):
        await world.prefabs.save(candidate, actor="user")


async def test_edit_base_cannot_write_the_core_written_provenance_either(world):
    from tests.fakes.prefabs import candidate as html_candidate

    async def witness(text):
        return "evt-1"

    prefabs = PrefabService(FilePrefabLibrary(world.data.parent / "package", world.data), user_utterance_witness=witness,
                            clock=lambda: NOW)
    forged = html_candidate(id="jarvis.counter", title="Base counter")
    forged["manifest"] = {**forged["manifest"], "schema_version": 3, "catalog": {
        "type": "component", "compatibility": {"slidecar": "native"}, "stack": ["html"],
        "upstream": {"name": "x/y", "url": "https://github.com/x/y", "commit": SHA, "archive_sha256": "a" * 64,
                     "imported_at": "2026-10-10T12:00:00Z", "source_sha256": "b" * 64, "changes": ["trust me"]}}}
    request = "Please change the base counter prefab so that it reads better for me"
    with pytest.raises(PrefabStoreError) as caught:
        await prefabs.edit_base("jarvis.counter", forged, user_request=request, confirmed_by_user=True)
    assert "importer only" in caught.value.message
    forged["manifest"]["catalog"].pop("upstream")
    forged["manifest"]["catalog"]["runtime_license"] = "Remotion License"
    with pytest.raises(PrefabStoreError):
        await prefabs.edit_base("jarvis.counter", forged, user_request=request, confirmed_by_user=True)


async def test_the_presentation_is_checked_before_any_download(world):
    error = await refusal(world.service.import_template(body(presentation_id="pst_" + "f" * 32)))
    assert error.code == "presentation_not_found" and world.fetcher.requests == [] and library_folders(world) == []


async def test_a_busy_refusal_is_journaled_too(world):
    class Slow(FakeUpstreamFetcher):
        def fetch(self, origin):
            import time
            time.sleep(0.2)
            return super().fetch(origin)

    slow = Slow()
    slow.add(ORIGIN, make_tarball(good_project()))
    service = RemotionImportService(slow, world.prefabs, FakeStudio(), engine=lambda: ENGINE, allowed_owners=lambda: ("someone",),
                                    diagnostics=world.recorder)
    first = asyncio.create_task(service.plan(body()))
    await asyncio.sleep(0.05)
    assert (await refusal(service.plan(body()))).code == "import_busy"
    await first
    assert any(kind == "core.remotion_import.refused" and data["code"] == "import_busy" for kind, _, data in world.recorder.events)
    assert status_of("import_timeout") == 504


# ------------------------------------------------------------------ routes

async def client_for(world, *, service=True, ready=True):
    core = SimpleNamespace(health=SimpleNamespace(ready=ready), remotion_import=world.service if service else None)
    app = web.Application()
    app.add_routes(RemotionImportProtocolRoutes(core).routes())
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


async def test_the_routes_plan_and_import_and_refuse_with_typed_envelopes(world):
    client = await client_for(world)
    try:
        plan = await client.post(PREFIX + "/plan", json={"repo_url": URL, "commit": SHA})
        assert plan.status == 200 and (await plan.json())["publishes"] is False and plan.headers["Cache-Control"] == "no-store"
        done = await client.post(PREFIX, json=body())
        payload = await done.json()
        assert done.status == 200 and payload["imported"] is True and payload["published_to_library"] is False
        bad = await client.post(PREFIX + "/plan", json={"repo_url": "https://evil.example/x/y", "commit": SHA})
        assert bad.status == 403 and (await bad.json())["error"]["code"] == "origin_not_allowed"
        unpinned = await client.post(PREFIX + "/plan", json={"repo_url": URL, "commit": "main"})
        assert unpinned.status == 400 and (await unpinned.json())["error"]["code"] == "commit_not_pinned"
        scope = await client.post(PREFIX, json=body(scope="library"))
        assert scope.status == 400 and "promotion" in (await scope.json())["error"]["message"]
        assert (await client.post(PREFIX + "/plan?x=1", json={})).status == 400
        assert (await client.post(PREFIX + "/plan", data=b"not json")).status == 400
        assert (await client.post(PREFIX + "/plan", data=b"x" * 9000)).status == 400
        assert (await client.post(PREFIX, json=body(presentation_id="pst_" + "f" * 32))).status == 404
    finally:
        await client.close()


async def test_a_license_refusal_is_a_422_with_the_reason_and_details(world):
    files = good_project()
    files["src/lib/Badge.tsx"] = "import x from 'three';\nexport const Badge = () => null;\n"
    world.fetcher.add(ORIGIN, make_tarball(files))
    client = await client_for(world)
    try:
        response = await client.post(PREFIX + "/plan", json={"repo_url": URL, "commit": SHA})
        error = (await response.json())["error"]
        assert response.status == 422 and error["code"] == "dependency_refused" and any("three" in d for d in error["details"])
    finally:
        await client.close()


async def test_without_an_importer_or_before_core_is_ready_the_routes_answer_503(world):
    for kwargs in ({"service": False}, {"ready": False}):
        client = await client_for(world, **kwargs)
        try:
            assert (await client.post(PREFIX + "/plan", json={})).status == 503
        finally:
            await client.close()


async def test_an_unexpected_defect_is_a_coded_500_and_a_durable_error_entry(world):
    class Broken:
        async def plan(self, raw):
            raise RuntimeError("boom with /secret/path")

        def report_failure(self, exc):
            world.service.report_failure(exc)

    core = SimpleNamespace(health=SimpleNamespace(ready=True), remotion_import=Broken())
    app = web.Application()
    app.add_routes(RemotionImportProtocolRoutes(core).routes())
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        response = await client.post(PREFIX + "/plan", json={})
        assert response.status == 500 and "boom" not in await response.text()
        assert ("core.remotion_import.route_failed", "error", {"error_class": "RuntimeError"}) in world.recorder.events
    finally:
        await client.close()


# ------------------------------------------------------------------ câblage de Core

def test_core_builds_the_importer_only_when_a_fetcher_is_given(tmp_path):
    from jarvis.core.v2_app import JarvisCoreApplication
    without = JarvisCoreApplication(data_root=tmp_path / "a")
    assert without.remotion_import is None
    with_fetcher = JarvisCoreApplication(data_root=tmp_path / "b", upstream_fetcher=FakeUpstreamFetcher(), upstream_engine=lambda: ENGINE,
                                         remotion_import_owners=lambda: ("someone",))
    assert with_fetcher.remotion_import is not None and with_fetcher.remotion_import.allowed_owners() == ("someone",)


def test_the_settings_reader_defaults_to_remotion_dev_and_reads_the_allowlist_from_the_control_center_settings(tmp_path):
    from jarvis.app import _remotion_import_owners
    assert _remotion_import_owners(tmp_path) == ("remotion-dev",)
    (tmp_path / "control-center-settings.json").write_text(json.dumps({"remotion_import": {"allowed_owners": ["Remotion-Dev", "someone"]}}),
                                                           encoding="utf-8")
    assert _remotion_import_owners(tmp_path) == ("remotion-dev", "someone")
    (tmp_path / "control-center-settings.json").write_text(json.dumps({"remotion_import": {"allowed_owners": "nope"}}), encoding="utf-8")
    assert _remotion_import_owners(tmp_path) == ("remotion-dev",)


def test_the_app_supplies_the_shipped_engine_pin_and_a_real_fetcher():
    from jarvis.adapters.https_upstream_fetcher import HttpsUpstreamFetcher
    from jarvis.app import _upstream_engine, _upstream_fetcher
    from jarvis.domain.remotion_capability import REMOTION_VERSION
    assert isinstance(_upstream_fetcher(), HttpsUpstreamFetcher) and _upstream_engine()().version == REMOTION_VERSION

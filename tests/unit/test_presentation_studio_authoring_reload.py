"""The authoring planner (Slice 11) and the scene hot reload (Slice 06) on one real stack (merge of the Slice 11 branch).

Real `PrefabService` (with the real `StudioPinRegistry`), file store, Studio, variant graph, authoring service, scene service and
reload service; the author is the scripted rig and no browser is involved. Proven: an assembled deck is a valid v3 document set
(`source_revision` 0, no fallback pin, no forgery), its pins are protected from the first instant, a fresh deck can receive a source
edit at once, retention at 64+ versions spares the assembled versions, `finalize` waits for a reload, the unreferenced report and
the reload's version counts agree, and the agent rate limit does not touch `finalize`.
"""

from __future__ import annotations

import json

import pytest

from jarvis.adapters.sqlite_scene import SQLiteSceneRepository
from jarvis.core.prefab_draft_coalescer import PrefabDraftCoalescer
from jarvis.core.presentation_studio_pins import StudioPinRegistry
from jarvis.core.presentation_studio_reload import PresentationStudioReloadService
from jarvis.core.presentation_studio_reload_stage import StageWindows
from jarvis.core.scene_service import SceneService
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C, VARIANT_SCHEMA_VERSION
from jarvis.domain.presentation_studio_reload import ReloadStatus as S, source_prefab_id
from tests.fakes import presentation_studio_fake_author as fa
from tests.fakes.presentation_studio_authoring_env import AuthoringEnv

pytestmark = pytest.mark.asyncio


class Stack:
    async def open(self, root) -> "Stack":
        self.pins = StudioPinRegistry()
        self.env = AuthoringEnv(root / "e", pin_registry=self.pins)
        self.scene = SceneService(SQLiteSceneRepository(root / "scene.sqlite3"), prefab_validator=self.env.prefabs)
        await self.scene.start()
        self.pins.bind_scene(self.scene)
        await self.env.start()
        assert await self.pins.rebuild(self.env.variants)
        self.reload = PresentationStudioReloadService(
            self.env.studio, self.env.prefabs, PrefabDraftCoalescer(self.env.prefabs, quiet_s=0.01, max_wait_s=0.05),
            StageWindows(self.scene), pins=self.pins, mount_deadline_s=1.0)
        return self

    async def close(self) -> None:
        await self.reload.close()
        await self.scene.close()

    async def deck(self, count: int = 3):
        out = await self.env.assemble(fa.brief("directed", duration_target_s=count * 50), fa.good_deck(count))
        assert out.status == "delivered", out.body.get("report", {}).get("failures")
        body = out.to_dict()
        view = await self.env.studio.get(body["presentation_id"])
        return view.presentation.presentation_id, view.variants[0]

    def edit(self, pid, variant, scene_id, files, **extra):
        return self.reload.apply_source_edit(pid, variant.variant_id, {
            "actor": "user", "basis": {"variant_revision": variant.revision}, "scene_id": scene_id, "files": files, **extra})


@pytest.fixture
async def stack(tmp_path):
    made = await Stack().open(tmp_path)
    yield made
    await made.close()


async def test_an_assembled_deck_is_a_valid_v3_document_set_owned_by_nobody_yet(stack):
    pid, variant = await stack.deck()
    document = json.loads((stack.env.studio_root / "presentations" / pid / "variants" / f"{variant.variant_id}.json").read_text(encoding="utf-8"))
    assert document["schema_version"] == VARIANT_SCHEMA_VERSION == 5  # v5 Remotion Slice 12 (anchor at_ms); v3 is Slice 06 (the two fields below), v4 Slice 17 (no scene_variants key)
    assert all("scene_variants" not in s for s in document["scenes"])
    assert all(s["source_revision"] == 0 and s["last_valid_pin"] is None for s in document["scenes"])
    assert all(s.source_revision == 0 and s.last_valid_pin is None for s in variant.scenes)
    # its pins are protected from the very first instant (no restart, no rebuild)
    pins = {(s.prefab.prefab_id, s.prefab.version) for s in variant.scenes}
    held = await stack.pins.pinned_versions(sorted({i for i, _ in pins}))
    assert all(v in held[i] for i, v in pins)


async def test_a_forged_assembled_scene_is_refused_before_anything_is_written_or_registered(stack):
    pid, variant = await stack.deck()
    folder = stack.env.studio_root / "presentations" / pid
    document = json.loads((folder / "variants" / f"{variant.variant_id}.json").read_text(encoding="utf-8"))
    document["scenes"][0]["source_revision"] = 3
    document["scenes"][0]["last_valid_pin"] = {"id": "lab.counter", "version": 1}
    before = stack.pins.stats()
    with pytest.raises(PresentationStudioError) as caught:
        await stack.env.studio.create_assembled("pst_" + "a" * 32, "{}", {variant.variant_id: json.dumps(document)}, {}, {})
    assert caught.value.code is C.INVALID_PRESENTATION and "owned by the hot reload" in caught.value.message
    assert stack.pins.stats() == before and stack.env.folders() == [pid]


async def test_a_failed_assembly_write_puts_the_registry_back(stack, monkeypatch):
    pid, variant = await stack.deck()
    folder = stack.env.studio_root / "presentations" / pid
    texts = {variant.variant_id: (folder / "variants" / f"{variant.variant_id}.json").read_text(encoding="utf-8")}
    new_pid = "pst_" + "b" * 32

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(stack.env.studio._store, "create", broken)
    before = dict(stack.pins._variants)
    with pytest.raises(PresentationStudioError):
        await stack.env.studio.create_assembled(new_pid, (folder / "presentation.json").read_text(encoding="utf-8"), texts, {}, {})
    assert dict(stack.pins._variants) == before                                                  # nothing left registered


async def test_a_fresh_deck_receives_a_source_edit_at_once_and_the_pin_is_forked_with_its_fallback(stack):
    pid, variant = await stack.deck()
    scene = variant.scenes[0]
    result = await stack.edit(pid, variant, scene.scene_id, {"style": "p{color:#abcdef}"})
    assert result.status is S.REPINNED, result.message                                            # no stage window: pinned, waits to mount
    after = next(s for s in (await stack.env.studio.get_variant(pid, variant.variant_id)).scenes if s.scene_id == scene.scene_id)
    assert after.prefab.prefab_id == source_prefab_id(pid, scene.scene_id) and after.source_revision == 1
    assert after.last_valid_pin == scene.prefab                                                  # the assembled pin is the fallback
    held = await stack.pins.pinned_versions([scene.prefab.prefab_id, after.prefab.prefab_id])
    assert scene.prefab.version in held[scene.prefab.prefab_id] and after.prefab.version in held[after.prefab.prefab_id]
    other = variant.scenes[1]
    assert next(s for s in (await stack.env.studio.get_variant(pid, variant.variant_id)).scenes
                if s.scene_id == other.scene_id).source_revision == 0                             # neighbours untouched


async def test_retention_at_64_plus_versions_spares_every_assembled_version(stack):
    pid, variant = await stack.deck()
    pins = {(s.prefab.prefab_id, s.prefab.version) for s in variant.scenes}
    bundle_id = sorted({i for i, _ in pins if i.startswith("presentation-studio.")})[0]
    manifest = json.loads((stack.env.data / "prefabs" / bundle_id / "1" / "manifest.json").read_text(encoding="utf-8")) \
        if hasattr(stack.env, "data") else None
    for index in range(70):
        await stack.env.prefabs.save({"manifest": {**manifest, "id": bundle_id}, "template": "<p>x</p>",
                                      "style": f"p{{--n:{index}}}", "behavior": "// b"}, actor="user")
    live = sorted(int(p.name) for p in (stack.env.data / "prefabs" / bundle_id).iterdir() if p.name.isdigit())
    assert all(v in live for i, v in pins if i == bundle_id), (live, pins)                       # the assembled version is pinned
    assert (stack.env.data / "prefabs" / ".archive" / bundle_id).exists()                          # and retention really ran
    assert not stack.env.sink.of("core.prefab.retention_failed")


async def test_finalize_waits_for_a_reload_of_any_scene_of_the_variant(stack):
    pid, variant = await stack.deck()
    request = {"presentation_id": pid, "variant_id": variant.variant_id, "actor": "user", "activate": False}
    stack.reload._reloading[(pid, variant.variant_id, variant.scenes[1].scene_id)] = 1           # a reload is in flight
    with pytest.raises(PresentationStudioError) as caught:
        await stack.env.authoring.finalize(request)
    assert caught.value.code is C.SCENE_RELOADING
    del stack.reload._reloading[(pid, variant.variant_id, variant.scenes[1].scene_id)]
    out = await stack.env.authoring.finalize(request)
    assert out.status == "finalized"


async def test_the_unreferenced_report_and_the_reload_counts_use_the_same_definitions(stack):
    pid, variant = await stack.deck()
    report = await stack.env.authoring.reconcile()
    assert report["pins_known"] and report["unreferenced_count"] == 0
    scene = variant.scenes[0]
    assert (await stack.edit(pid, variant, scene.scene_id, {"style": "p{color:red}"})).status is S.REPINNED
    source_id = source_prefab_id(pid, scene.scene_id)
    counts = stack.reload.archive_counts([scene.scene_id], pid)[scene.scene_id]
    assert counts["live"] == 1 and counts["archived"] == 0 and counts["newest"] == 1
    report = await stack.env.authoring.reconcile()
    assert report["unreferenced_count"] == 0                                                      # the fork is pinned (and its fallback too)
    # `studio_prefab_versions` counts the LIVE catalogue only: the same `live` as the counts above, archived ones in neither
    live_total = sum(stack.env.prefabs.retention_counts(i)["live"] for i in
                     {i for i, _ in {(s.prefab.prefab_id, s.prefab.version) for s in variant.scenes} if i.startswith("presentation-studio.")} | {source_id})
    assert report["studio_prefab_versions"] == live_total
    # a published version that nothing pins is unreferenced ... until ANY pin source holds it (here an in-flight hold)
    manifest = json.loads((stack.env.data / "prefabs" / source_id / "1" / "manifest.json").read_text(encoding="utf-8"))
    published = await stack.env.prefabs.save({"manifest": {**manifest, "id": source_id}, "template": "<p>x</p>", "style": "p{}",
                                              "behavior": "// b"}, actor="user")
    stray = {"id": published.prefab_id, "version": published.version}
    assert stray in (await stack.env.authoring.reconcile())["unreferenced_prefabs"]
    with stack.pins.hold((published.prefab_id, published.version)):
        assert stray not in (await stack.env.authoring.reconcile())["unreferenced_prefabs"]


async def test_the_agent_rate_limit_and_finalize_do_not_interfere(stack, monkeypatch):
    from jarvis.core import presentation_studio_reload_limits as limits
    monkeypatch.setattr(limits, "BRAIN_EDIT_LIMIT", 1)
    pid, variant = await stack.deck()
    scene = variant.scenes[0]
    first = await stack.reload.apply_source_edit(pid, variant.variant_id, {
        "actor": "brain", "basis": {"variant_revision": variant.revision}, "scene_id": scene.scene_id, "files": {"style": "p{color:red}"}})
    assert first.status is S.REPINNED
    current = await stack.env.studio.get_variant(pid, variant.variant_id)
    with pytest.raises(PresentationStudioError) as caught:
        await stack.reload.apply_source_edit(pid, variant.variant_id, {
            "actor": "brain", "basis": {"variant_revision": current.revision}, "scene_id": scene.scene_id, "files": {"style": "p{color:blue}"}})
    assert caught.value.code is C.SOURCE_EDIT_RATE
    out = await stack.env.authoring.finalize({"presentation_id": pid, "variant_id": variant.variant_id, "actor": "brain", "activate": False})
    assert out.status in ("finalized", "refused")                                                  # judged on its merits, never rate-limited

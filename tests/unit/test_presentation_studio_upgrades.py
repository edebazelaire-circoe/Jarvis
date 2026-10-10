"""Nouvelle version d'un prefab epingle : avis sans mise a jour, essai en variante enfant, adoption explicite (Remotion Slice 19).

Banc de la Slice 06 : vrai `PrefabService` avec la VRAIE retention (registre des pins du Studio), vrais magasins, vraies variantes. Contrat :
`docs/presentation-studio.md` > *Newer prefab versions and trial variants*.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from jarvis.adapters.file_prefab_library import LIBRARY_DIR
from jarvis.core.presentation_studio_engine_gate import StudioEngineGate
from jarvis.core.presentation_studio_upgrades import PresentationStudioUpgrades
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_reload import source_prefab_id
from tests.fakes.prefabs import candidate
from tests.fakes.presentation_studio_reload import SID, SID2, Rig, scene_body

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def rig(tmp_path):
    opened = await Rig(tmp_path).open(host=False, show=False)
    yield opened
    await opened.close()


def service(rig) -> PresentationStudioUpgrades:
    return PresentationStudioUpgrades(rig.studio, rig.variants, rig.prefabs, edit=rig.edits)


async def publish(rig, prefab_id="lab.counter", *, style="", manifest=None):
    """Une nouvelle version immuable de `prefab_id` (revision par la porte de publication de Core)."""

    cand = candidate()
    cand["manifest"] = {**cand["manifest"], "id": prefab_id, **(manifest or {})}
    cand["style"] += f"\n/* {style} */" if style else ""
    return (await rig.prefabs.save(cand, actor="user")).version


def tree(root) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


def studio_files(rig) -> dict[str, str]:
    return tree(rig.tmp / "studio")


def library_files(rig) -> dict[str, str]:
    return tree(rig.data / LIBRARY_DIR)


async def pins(rig, variant_id):
    variant = await rig.studio.get_variant(rig.pid, variant_id)
    return {s.scene_id: (s.prefab.prefab_id, s.prefab.version) for s in variant.scenes}


# ------------------------------------------------------------------ l'avis : rien n'est mis a jour


async def test_a_pin_on_the_latest_version_raises_no_notice(rig):
    answer = await service(rig).notices(rig.pid, rig.vid)
    assert answer["count"] == 0 and answer["notices"] == [] and answer["auto_upgrade"] is False


async def test_a_newer_version_is_announced_and_nothing_moves(rig):
    await publish(rig, style="second")
    before = (studio_files(rig), library_files(rig))
    answer = await service(rig).notices(rig.pid, rig.vid)
    assert answer["count"] == 2 and {n["scene_id"] for n in answer["notices"]} == {SID, SID2}
    notice = answer["notices"][0]
    assert (notice["prefab_id"], notice["pinned_version"], notice["latest_version"]) == ("lab.counter", 1, 2)
    assert notice["newer_versions"] == [2] and notice["fits"] is True and notice["engine_ok"] is True and notice["trials"] == []
    assert notice["latest_catalog"]["type"] == "component" and notice["latest_catalog"]["compatibility"]["slidecar"] == "native"
    # asking again, and again, never changes a pin, a variant or the library: no auto-upgrade, no silent rebinding
    for _ in range(3):
        await service(rig).notices(rig.pid, rig.vid)
    assert (studio_files(rig), library_files(rig)) == before
    assert await pins(rig, rig.vid) == {SID: ("lab.counter", 1), SID2: ("lab.counter", 1)}


async def test_a_version_that_does_not_hold_the_scene_is_announced_as_not_fitting_with_the_reason(rig):
    shrunk = rig.shrunk_manifest()
    await publish(rig, manifest={"inputs": shrunk["inputs"]})
    notice = (await service(rig).notices(rig.pid, rig.vid))["notices"][0]
    assert notice["fits"] is False and notice["problem"] == C.SCENE_INCOMPATIBLE.value and notice["engine_ok"] is True


async def test_only_a_native_version_is_usable_in_the_engine_of_the_presentation(rig):
    rig.studio._engine_gate = StudioEngineGate(lambda: {})
    catalog = {"type": "component", "compatibility": {"slidecar": "adapter"}, "stack": ["html"]}
    await publish(rig, manifest={"schema_version": 3, "catalog": catalog})
    notice = (await service(rig).notices(rig.pid, rig.vid))["notices"][0]
    assert notice["engine_ok"] is False and notice["problem"] == C.ENGINE_UNSUPPORTED.value
    before = studio_files(rig)
    await rig_refused(service(rig).try_version(rig.pid, rig.vid, {"scene_id": SID}), C.ENGINE_UNSUPPORTED)
    assert studio_files(rig) == before, "declared, not usable: no variant is created for it"


async def rig_refused(awaitable, code):
    with pytest.raises(PresentationStudioError) as caught:
        await awaitable
    assert caught.value.code is code, caught.value
    return caught.value


# ------------------------------------------------------------------ l'essai : une variante enfant, la source intacte


async def test_trying_the_new_version_creates_a_child_variant_and_leaves_the_original_untouched(rig):
    await publish(rig, style="second")
    original = rig.variant_file().read_bytes()
    library = library_files(rig)
    up = service(rig)
    answer = await up.try_version(rig.pid, rig.vid, {"scene_id": SID, "title": "Essai"})
    assert answer["trial"] is True and answer["adopted"] is False and answer["activated"] is False
    assert answer["from"] == {"id": "lab.counter", "version": 1} and answer["to"] == {"id": "lab.counter", "version": 2}
    trial_id = answer["node"]["variant_id"]
    assert trial_id != rig.vid and answer["node"]["parent_variant_id"] == rig.vid
    assert answer["node"]["rationale"].startswith("Essai de lab.counter v2 pour la scène " + SID)

    assert rig.variant_file().read_bytes() == original, "the original variant is byte-identical"
    assert library_files(rig) == library, "a trial publishes no prefab and promotes nothing"
    assert await pins(rig, rig.vid) == {SID: ("lab.counter", 1), SID2: ("lab.counter", 1)}
    assert await pins(rig, trial_id) == {SID: ("lab.counter", 2), SID2: ("lab.counter", 1)}, "one scene repinned, the rest copied"
    original_scene = (await rig.studio.get_variant(rig.pid, rig.vid)).scenes[0]
    trial_scene = (await rig.studio.get_variant(rig.pid, trial_id)).scenes[0]
    assert trial_scene.props == original_scene.props and trial_scene.data == original_scene.data
    assert trial_scene.controls == original_scene.controls and trial_scene.anchors == original_scene.anchors, "nothing rebound"
    presentation = await rig.studio.get(rig.pid)
    assert presentation.presentation.active_variant_id == rig.vid, "the trial is never activated by itself"

    notices = await up.notices(rig.pid, rig.vid)
    assert [t["variant_id"] for t in notices["trials"]] == [trial_id]
    assert notices["notices"][0]["trials"][0]["version"] == 2 and notices["notices"][1]["trials"] == []


async def test_adopting_the_trial_is_a_separate_explicit_act(rig):
    await publish(rig, style="second")
    trial = (await service(rig).try_version(rig.pid, rig.vid, {"scene_id": SID}))["node"]["variant_id"]
    switched = await rig.variants.switch(rig.pid, trial, {})  # the existing activation: the only way a trial becomes the live variant
    assert switched["changed"] is True
    assert (await rig.studio.get(rig.pid)).presentation.active_variant_id == trial
    assert await pins(rig, rig.vid) == {SID: ("lab.counter", 1), SID2: ("lab.counter", 1)}, "the original still pins its version"


async def test_a_trial_can_target_an_older_listed_version_and_refuses_a_version_that_is_not_newer(rig):
    await publish(rig, style="second")
    await publish(rig, style="third")
    up = service(rig)
    assert (await up.notices(rig.pid, rig.vid))["notices"][0]["newer_versions"] == [3, 2]
    two = await up.try_version(rig.pid, rig.vid, {"scene_id": SID, "version": 2})
    assert two["to"]["version"] == 2
    before = studio_files(rig)
    await rig_refused(up.try_version(rig.pid, rig.vid, {"scene_id": SID, "version": 1}), C.INVALID_PRESENTATION)
    await rig_refused(up.try_version(rig.pid, rig.vid, {"scene_id": SID, "version": 9}), C.PREFAB_UNAVAILABLE)
    assert studio_files(rig) == before


async def test_a_new_version_that_does_not_hold_the_scene_is_refused_and_nothing_is_written(rig):
    await publish(rig, manifest={"inputs": rig.shrunk_manifest()["inputs"]})
    before = studio_files(rig)
    error = await rig_refused(service(rig).try_version(rig.pid, rig.vid, {"scene_id": SID}), C.SCENE_INCOMPATIBLE)
    assert "scene" in error.message
    assert studio_files(rig) == before, "no variant, no number spent, no file"
    assert len((await rig.variants.graph(rig.pid))["nodes"]) == 1


async def test_a_stale_revision_an_unknown_scene_and_an_unconfirmed_reload_are_refused(rig):
    await publish(rig, style="second")
    up = service(rig)
    revision = (await rig.variant()).revision
    await rig_refused(up.try_version(rig.pid, rig.vid, {"scene_id": SID, "expected_variant_revision": revision + 4}), C.STALE_REVISION)
    await rig_refused(up.try_version(rig.pid, rig.vid, {"scene_id": "pss_00000000beef"}), C.UNKNOWN_SCENE)
    await rig_refused(up.try_version(rig.pid, rig.vid, {"scene_id": SID, "activate": True}), C.INVALID_PRESENTATION)
    document = json.loads(rig.variant_file().read_text(encoding="utf-8"))
    document["scenes"][0]["last_valid_pin"] = {"id": "lab.counter", "version": 1}
    document["scenes"][0]["prefab"] = {"id": "lab.counter", "version": 2}
    rig.variant_file().write_text(json.dumps(document), encoding="utf-8")
    await rig.studio.start()
    await rig_refused(up.try_version(rig.pid, rig.vid, {"scene_id": SID}), C.SCENE_RELOADING)


async def test_nothing_is_promoted_to_the_shared_library_by_noticing_or_trying(rig):
    await publish(rig, style="second")
    up = service(rig)
    await up.notices(rig.pid, rig.vid)
    await up.try_version(rig.pid, rig.vid, {"scene_id": SID})
    assert not list((rig.data / LIBRARY_DIR).glob("studio-template.*")) and not (rig.tmp / "studio" / "presentation_templates").exists()
    assert sorted(p.name for p in (rig.data / LIBRARY_DIR / "lab.counter").iterdir()) == ["1", "2"], "only the version the user published"


# ------------------------------------------------------------------ la retention tient les deux pins


async def test_retention_keeps_the_old_pin_and_the_trial_pin_while_the_trial_exists(rig):
    source = source_prefab_id(rig.pid, SID)
    assert await publish(rig, source, style="v1") == 1
    await rig.save_scenes([scene_body(SID, prefab=(source, 1)), scene_body(SID2)])
    await rig.rebuild_pins()
    assert await publish(rig, source, style="v2") == 2
    trial = (await service(rig).try_version(rig.pid, rig.vid, {"scene_id": SID}))["node"]["variant_id"]
    assert (await pins(rig, trial))[SID] == (source, 2) and (await pins(rig, rig.vid))[SID] == (source, 1)
    for number in range(3, 41):  # 38 more versions: the retention (32 live versions) runs under the write lock
        await publish(rig, source, style=f"v{number}")
    folder = rig.data / LIBRARY_DIR / source
    live = sorted(int(p.name) for p in folder.iterdir() if p.name.isdigit())
    assert 1 in live and 2 in live, "the original pin and the trial pin both survive"
    assert 5 not in live and (rig.data / LIBRARY_DIR / ".archive" / source / "5").is_dir(), "an unpinned old version is archived, never deleted"
    # the original variant still resolves its pin after the retention ran
    assert (await rig.prefabs.get(source, 1)).entry.ok and (await rig.prefabs.get(source, 2)).entry.ok
    notice = next(n for n in (await service(rig).notices(rig.pid, rig.vid))["notices"] if n["scene_id"] == SID)
    assert notice["pinned_version"] == 1 and notice["latest_version"] == 40 and notice["trials"][0]["variant_id"] == trial


# ------------------------------------------------------------------ renoncer, ancienne version epinglee, amont indisponible


async def test_declining_a_trial_archives_the_child_and_the_original_keeps_working_untouched(rig):
    """Rollback of an upgrade is not an undo of the original: there is nothing to undo there. The trial is archived like any variant."""

    await publish(rig, style="second")
    original = rig.variant_file().read_bytes()
    trial = (await service(rig).try_version(rig.pid, rig.vid, {"scene_id": SID}))["node"]["variant_id"]
    planned = await rig.variants.plan_archive(rig.pid, trial)
    await rig.variants.archive(rig.pid, trial, {"confirmation": planned["confirmation"]})
    assert rig.variant_file().read_bytes() == original and await pins(rig, rig.vid) == {SID: ("lab.counter", 1), SID2: ("lab.counter", 1)}
    after = await service(rig).notices(rig.pid, rig.vid)
    assert after["count"] == 2 and after["trials"] == [], "the notice is back to a plain notice, the old pin is still the pin"
    again = await service(rig).try_version(rig.pid, rig.vid, {"scene_id": SID})   # a declined trial can be tried again, as a new variant
    assert again["node"]["variant_number"] == 3, "numbers are never reused"


async def test_the_old_pin_keeps_playing_after_newer_versions_and_the_notice_needs_no_network(rig):
    """Pinned old version, upstream unavailable: the notice and the trial read only the local library; nothing else is consulted."""

    for number in range(2, 6):
        await publish(rig, style=f"v{number}")
    assert (await rig.prefabs.get("lab.counter", 1)).entry.ok
    answer = await service(rig).notices(rig.pid, rig.vid)
    assert answer["notices"][0]["pinned_version"] == 1 and answer["notices"][0]["latest_version"] == 5
    assert answer["notices"][0]["newer_versions"] == [5, 4, 3, 2] and answer["notices"][0]["newer_count"] == 4
    described = await rig.studio.describe_scene(rig.pid, rig.vid, SID)
    assert described["problems"] == [] and described["prefab"] == {"id": "lab.counter", "version": 1}, "the pinned version still renders"


async def test_a_scene_whose_prefab_cannot_be_read_is_said_not_hidden(rig):
    import shutil

    await publish(rig, style="second")
    other = source_prefab_id(rig.pid, SID2)
    await publish(rig, other, style="own")
    await rig.save_scenes([scene_body(SID), scene_body(SID2, prefab=(other, 1))])
    shutil.rmtree(rig.data / LIBRARY_DIR / other)           # the id vanished from disk behind the catalogue's back
    await rig.prefabs.start()
    answer = await service(rig).notices(rig.pid, rig.vid)
    assert [n["scene_id"] for n in answer["notices"]] == [SID]
    assert [(u["scene_id"], u["code"]) for u in answer["unavailable"]] == [(SID2, "unknown_prefab")]


# ------------------------------------------------------------------ QA B3 : la licence d'une version plus recente ; QA c : la course


def licensed(name: str | None) -> dict:
    block = {"type": "component", "compatibility": {"slidecar": "native"}, "stack": ["html"]}
    if name and len(name) <= 64:
        block["license"] = name
    elif name:   # an upstream licence may be up to 120 characters, longer than a declared `license`
        block["upstream"] = {"name": "acme/tpl", "url": "https://github.com/acme/tpl", "license": name}
    return {"schema_version": 3, "catalog": block}


async def test_a_newer_version_whose_licence_changed_is_told_with_both_licences_and_needs_a_named_acknowledgement(rig):
    await publish(rig, style="second", manifest=licensed("CC-BY-NC-4.0"))
    notice = (await service(rig).notices(rig.pid, rig.vid))["notices"][0]
    assert notice["pinned_licence"] is None and notice["latest_licence"] == "CC-BY-NC-4.0" and notice["licence_changed"] is True
    assert notice["licence_ack_required"] == "CC-BY-NC-4.0" and notice["fits"] is True, "it fits, and the licence still needs a decision"
    before = studio_files(rig)
    up = service(rig)
    error = await rig_refused(up.try_version(rig.pid, rig.vid, {"scene_id": SID}), C.INVALID_PRESENTATION)
    assert "CC-BY-NC-4.0" in error.message and "licence_ack" in error.message
    await rig_refused(up.try_version(rig.pid, rig.vid, {"scene_id": SID, "licence_ack": ["MIT"]}), C.INVALID_PRESENTATION)
    await rig_refused(up.try_version(rig.pid, rig.vid, {"scene_id": SID, "licence_ack": ["CC-BY-NC-4.0"], "actor": "brain"}), C.INVALID_PRESENTATION)
    assert studio_files(rig) == before, "no variant, no number, nothing written without the user's named acknowledgement"
    done = await up.try_version(rig.pid, rig.vid, {"scene_id": SID, "licence_ack": ["CC-BY-NC-4.0"]})
    assert done["trial"] is True and done["to"]["version"] == 2


async def test_an_unchanged_permitted_licence_needs_no_acknowledgement_and_a_restrictive_one_does_even_unchanged(rig):
    await publish(rig, style="second")
    assert (await service(rig).notices(rig.pid, rig.vid))["notices"][0]["licence_ack_required"] is None
    await publish(rig, style="third", manifest=licensed("MIT"))
    notice = (await service(rig).notices(rig.pid, rig.vid))["notices"][0]
    assert notice["licence_changed"] is True and notice["licence_ack_required"] == "MIT", "a licence that CHANGES is always named, even a gentler one"
    long_name = "LicenseRef-" + "x" * 100
    await publish(rig, style="fourth", manifest=licensed(long_name))
    latest = (await service(rig).notices(rig.pid, rig.vid))["notices"][0]
    assert latest["licence_ack_required"] == long_name and len(long_name) > 64, "acknowledgements are as long as licences can be"
    assert (await service(rig).try_version(rig.pid, rig.vid, {"scene_id": SID, "licence_ack": [long_name]}))["trial"] is True


async def test_a_change_of_the_variant_between_the_check_and_the_write_is_refused_inside_the_lock(rig, monkeypatch):
    """QA c: the compatibility was checked outside the variants lock; an edit that lands before the branch is written must not slip through."""

    await publish(rig, style="second")
    real = rig.studio.check_scenes

    seen = {"edited": False}

    async def check_then_edit(*args, **kwargs):
        await real(*args, **kwargs)
        if seen["edited"]:
            return
        seen["edited"] = True
        revision = (await rig.variant()).revision
        result = await rig.edits.edit(rig.pid, rig.vid, {"actor": "user", "mode": "commit", "basis": {"variant_revision": revision},
                                                          "ops": [{"op": "control.set", "scene_id": SID, "control_id": "headline", "value": "Autre"}]})
        assert result.status.value == "applied", result

    monkeypatch.setattr(rig.studio, "check_scenes", check_then_edit)
    numbers = (await rig.studio.get(rig.pid)).presentation.variant_counter
    await rig_refused(service(rig).try_version(rig.pid, rig.vid, {"scene_id": SID}), C.STALE_REVISION)
    assert (await rig.studio.get(rig.pid)).presentation.variant_counter == numbers, "no number spent, no variant created"
    assert len((await rig.variants.graph(rig.pid))["nodes"]) == 1

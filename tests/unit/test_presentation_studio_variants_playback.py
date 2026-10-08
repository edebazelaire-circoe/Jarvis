"""Graphe des variantes et lecture (Slices 16 et 12) : ce qui arrive à une lecture vivante quand on change de variante ou qu'on
archive (jarvis-interactive-presentation-studio).

Vrai service de lecture (vraie scène, vrai catalogue de prefabs, vrai magasin), vrai service de variantes. Règle : une lecture reste
liée à **sa** variante ; activer une autre variante ne l'arrête pas ; archiver la variante qu'elle joue est refusé, typé, avant tout
jeton et même avec un jeton obtenu avant le démarrage ; une variante branchée joue avec sa **propre** direction artistique.
Contrat : `docs/presentation-studio.md` › *Variant graph and operations contract*, *Playback and the variant graph*.
"""

from __future__ import annotations

import json

import pytest

from jarvis.core.presentation_studio_variants import PresentationStudioVariants
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from tests.unit.test_presentation_studio_playback_service import Gate, Rig, applied

SECRET = b"p" * 32


class Opened:
    def __init__(self, rig: Rig, variants: PresentationStudioVariants) -> None:
        self.rig, self.variants = rig, variants


@pytest.fixture
async def world(tmp_path):
    rig = await Rig(tmp_path).open()
    variants = PresentationStudioVariants(rig.studio, diagnostics=rig.env.sink, secret=SECRET, epoch=lambda: 1_000_000.0)
    variants.bind_playback(rig.service)
    yield Opened(rig, variants)
    await rig.close()


async def refused(awaitable, code: C) -> PresentationStudioError:
    with pytest.raises(PresentationStudioError) as caught:
        await awaitable
    assert caught.value.code is code, caught.value
    return caught.value


def snapshot(rig: Rig) -> dict[str, str]:
    return rig.tree_digest()


async def test_switching_the_active_variant_does_not_stop_a_run_nor_rebind_it(world):
    rig, variants = world.rig, world.variants
    other = (await variants.create_branch(rig.pid, {"title": "Autre"}))["variant"]["variant_id"]
    applied(await rig.service.start(rig.start_body(variant_id=rig.vid)))
    stage_before = (await rig.stage_object()).object_id
    switched = await variants.switch(rig.pid, other)
    assert switched["changed"] is True
    where = rig.service.where()
    assert where["variant_id"] == rig.vid and rig.service.state.active and rig.service.running_variant() == (rig.pid, rig.vid)
    state = applied(await rig.run("next"))
    assert state["phase"] in ("playing", "paused") and state["position"]["index"] == 2
    assert (await rig.stage_object()).object_id == stage_before, "the same stage window keeps being patched"
    # creating a branch that becomes active changes nothing either
    await variants.create_branch(rig.pid, {"title": "Encore", "activate": True})
    assert rig.service.running_variant() == (rig.pid, rig.vid)
    applied(await rig.service.stop({"actor": "user"}))
    assert rig.service.running_variant() is None


async def test_archiving_the_variant_being_played_is_refused_with_a_typed_error_at_the_plan_and_at_the_archive(world):
    rig, variants = world.rig, world.variants
    child = (await variants.create_branch(rig.pid, {"title": "Enfant"}))["variant"]["variant_id"]
    await variants.switch(rig.pid, child)
    leaf = (await variants.create_branch(rig.pid, {"title": "Feuille", "source_variant_id": child}))["variant"]["variant_id"]
    token = (await variants.plan_archive(rig.pid, leaf))["confirmation"]  # obtained before the run starts
    applied(await rig.service.start(rig.start_body(variant_id=leaf)))
    before = snapshot(rig)
    error = await refused(variants.plan_archive(rig.pid, leaf), C.VARIANT_IN_PLAYBACK)
    assert "stop the playback first" in error.message
    await refused(variants.archive(rig.pid, leaf, {"confirmation": token}), C.VARIANT_IN_PLAYBACK)
    await refused(variants.plan_archive(rig.pid, child), C.VARIANT_IN_PLAYBACK)  # an ancestor whose subtree holds the played one
    assert snapshot(rig) == before, "nothing moved, nothing written"
    assert rig.service.running_variant() == (rig.pid, leaf) and rig.service.state.active
    # a variant outside the played one is archivable while the run goes on
    other = (await variants.create_branch(rig.pid, {"title": "Autre", "source_variant_id": rig.vid}))["variant"]["variant_id"]
    plan = await variants.plan_archive(rig.pid, other)
    done = await variants.archive(rig.pid, other, {"confirmation": plan["confirmation"]})
    assert done["count"] == 1 and rig.service.state.active
    # once the run is stopped the archive goes through
    applied(await rig.service.stop({"actor": "user"}))
    again = await variants.plan_archive(rig.pid, leaf)
    assert (await variants.archive(rig.pid, leaf, {"confirmation": again["confirmation"]}))["count"] == 1


async def test_a_run_started_between_the_check_and_the_archive_is_stopped_and_it_is_said(tmp_path):
    rig = await Rig(tmp_path).open()
    try:
        calls = {"n": 0, "stopped": []}

        class Racy:
            """Idle at the check, playing right after: the narrow race the safety net covers."""

            def running_variant(self):
                calls["n"] += 1
                return None if calls["n"] <= 2 else (rig.pid, victim)

            async def stop(self, raw, *, reason="user"):
                calls["stopped"].append(reason)

        variants = PresentationStudioVariants(rig.studio, diagnostics=rig.env.sink, secret=SECRET, epoch=lambda: 1_000_000.0)
        variants.bind_playback(Racy())
        victim = (await variants.create_branch(rig.pid, {"title": "Victime"}))["variant"]["variant_id"]
        plan = await variants.plan_archive(rig.pid, victim)
        done = await variants.archive(rig.pid, victim, {"confirmation": plan["confirmation"]})
        assert done["count"] == 1 and calls["stopped"] == ["variant_archived"], "the archive stands, the run is stopped"
        assert rig.env.sink.of("core.presentation_studio.playback_variant_archived")[0][0] == "warning"
    finally:
        await rig.close()


async def test_a_branched_variant_plays_with_its_own_art_direction_not_its_sources(tmp_path):
    rig = Rig(tmp_path, gate=None)
    await rig.open()
    try:
        studio = rig.studio
        rig.gate = studio  # the REAL gate of Slice 09 (`require_art_direction`), not the fake
        service = rig.build()
        variant = await studio.get_variant(rig.pid, rig.vid)
        parent_da = (await studio.create_fallback_art_direction(rig.pid, rig.vid, {"expected_variant_revision": variant.revision})
                     )["art_direction"]["art_direction_id"]
        variants = PresentationStudioVariants(studio, diagnostics=rig.env.sink, secret=SECRET, epoch=lambda: 1_000_000.0)
        variants.bind_playback(service)
        branch = (await variants.create_branch(rig.pid, {"title": "Serieuse"}))["variant"]
        assert branch["art_direction_id"] and branch["art_direction_id"] != parent_da
        resolved = await studio.require_art_direction(rig.pid, branch["variant_id"], serious=True)
        assert resolved["art_direction"]["art_direction_id"] == branch["art_direction_id"]
        # the parent's document disappears: the branch still plays because it resolved ITS copy
        (rig.env.root / "presentations" / rig.pid / "art_directions" / f"{parent_da}.json").unlink()
        applied(await service.start(rig.start_body(variant_id=branch["variant_id"])))
        assert service.running_variant() == (rig.pid, branch["variant_id"])
        applied(await service.stop({"actor": "user"}))
    finally:
        await rig.close()

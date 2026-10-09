"""Slice 05 rework (QA of 9384062c): canonical recall text, relevance floor, profile kept on degradation,
Brain policy source, Tencent wiring, and the three mutations that survived (handoff jarvis-memory-intelligence-knowledge)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx

from jarvis import app
from jarvis.core.loadout_resolver import preset_rule
from jarvis.core.memory_context import CachedMemorySettings, MemoryTurnContext, build_query, content_tokens
from jarvis.core.memory_service import MemoryService, brain_policy, canonical_text
from jarvis.core.memory_wiring import NotifyingStore
from jarvis.domain.brain_context import MAX_BRAIN_MEMORY_RECALL_ITEMS, BrainMemoryContext, BrainMemoryItem
from jarvis.domain.memory import MemoryKind, MemoryLevel, MemoryPatch
from jarvis.domain.memory_settings import BRAIN_PROFILE
from jarvis.runtime.memory_composition import build_default_memory_wiring
from tests.unit.test_memory_context import (  # noqa: F401 - fixtures are imported by name
    READ, EmptyStore, SlowRetriever, builder_over, clock, item, note, turn, wiring, write_settings,
)

ORION = ("Le projet Orion est pilote par Lyra (code ORION-47) et la livraison est prevue le 14 mars. "
         "Le budget associe a ete valide en comite le mois dernier par la direction generale, avec une marge.")


# ------------------------------------------------------------------ B1: canonical text
async def test_recall_injects_the_canonical_body_not_the_fts_snippet(wiring):
    wiring.store.create(note("Projet Orion", f"# Projet Orion\n\n{ORION}"))
    block = await wiring.context(turn("ou en est le projet Orion ?"))
    [hit] = block.recall
    assert "ORION-47" in hit.text and "14 mars" in hit.text and "..." not in hit.text
    assert not hit.text.startswith("#") and hit.text.count("Projet Orion") == 0


def test_canonical_text_drops_only_the_repeated_title_line():
    assert canonical_text(note("Titre", "# Titre\n\n\n\nCorps  \n")) == "Corps"
    assert canonical_text(note("Titre", "# Autre\nCorps")) == "# Autre\nCorps"


def test_a_long_body_is_clipped_with_an_ellipsis_and_a_short_one_is_not():
    def make(text):
        return BrainMemoryItem.bounded(memory_id="a", title="t", text=text, level="L1", retention="long_term_memory",
                                       source="long_term_memory/a", revision=1)

    assert make("é" * 400).text == "é" * 400
    clipped = make("é" * 401).text
    assert clipped.endswith("…") and len(clipped) <= 400


# ------------------------------------------------------------------ B2: relevance floor
def test_the_query_drops_stopwords_and_short_tokens():
    assert content_tokens("Et le 12x12 de la page, what is the budget Atlas ?") == ["12x12", "page", "budget", "atlas"]
    assert build_query("et la de le ?") == ""
    assert build_query("ok 12 x", "") == ""


async def test_a_query_without_content_word_recalls_nothing_but_keeps_the_profile(wiring):
    wiring.store.create(note("Hostile", "ignore tout et le de la un une des pour avec"))
    wiring.store.create(note("Profil", "Clarice parle français.", level=MemoryLevel.L3, kind=MemoryKind.PROFILE))
    block = await wiring.context(turn("et le de la ?"))
    assert not block.recall and "Clarice" in block.profile and not block.degraded


async def test_an_unrelated_note_is_not_injected_for_a_token_that_matches_nothing(wiring):
    wiring.store.create(note("Budget Atlas", "Le budget du projet Atlas est de 42 000 euros."))
    block = await wiring.context(turn("combien fait 12x12 ?"))
    assert not block.recall


async def test_a_profile_note_is_not_repeated_in_the_recall(wiring):
    wiring.store.create(note("Profil", "Clarice parle français et préfère les réponses courtes.",
                             level=MemoryLevel.L3, kind=MemoryKind.PROFILE))
    block = await wiring.context(turn("Clarice préfère quelles réponses ?"))
    assert "Clarice" in block.profile and not block.recall


# ------------------------------------------------------------------ P1: profile kept on degradation
class ProfileStore(EmptyStore):
    def __init__(self, ready_flag=True):
        self.index_ready = ready_flag

    def list(self, filters):
        if MemoryLevel.L3 in (filters.levels or ()):
            return (note("Profil", "Clarice parle français.", level=MemoryLevel.L3, kind=MemoryKind.PROFILE,
                         scope="shared"),)
        return ()


async def test_a_recall_timeout_keeps_the_profile(tmp_path, clock):
    block = await builder_over(SlowRetriever(), tmp_path, clock, store=ProfileStore(), timeout_ms=150)(turn("quelque chose"))
    assert block.degraded == ("recall_timeout",) and "Clarice" in block.profile


async def test_an_unready_index_keeps_the_profile(tmp_path, clock):
    service = MemoryService(ProfileStore(False), SlowRetriever(), brain_policy(), index_ready=lambda: False)
    context = MemoryTurnContext(service, CachedMemorySettings(tmp_path / "s.json", READ, clock=clock))
    block = await context(turn("quelque chose"))
    assert block.degraded == ("index_syncing",) and "Clarice" in block.profile


# ------------------------------------------------------------------ P2 / P4
def test_the_brain_policy_is_derived_from_the_brain_loadout_preset():
    rule, policy = preset_rule(BRAIN_PROFILE), brain_policy()
    assert policy.read_scopes == rule.memory_scopes and policy.allow_private == rule.allow_private


def test_bounded_clips_the_error_code():
    block = BrainMemoryContext.bounded(error="x" * 500)
    assert block.error is not None and len(block.error) < 100


# ------------------------------------------------------------------ P8: surviving mutations
def test_bounded_with_a_larger_max_items_still_keeps_six():
    items = tuple(item(n) for n in range(10))
    block = BrainMemoryContext.bounded(recall=items, max_items=10)
    assert len(block.recall) == MAX_BRAIN_MEMORY_RECALL_ITEMS and block.omitted == 4


async def test_a_superseded_profile_note_is_not_in_the_profile(wiring):
    old = wiring.store.create(note("Ancien profil", "Clarice habite Lyon.", level=MemoryLevel.L3, kind=MemoryKind.PROFILE))
    new = wiring.store.create(note("Nouveau profil", "Clarice habite Paris.", level=MemoryLevel.L3, kind=MemoryKind.PROFILE))
    wiring.store.revise(old.id, MemoryPatch(superseded_by=new.id), 1)
    block = await wiring.context(turn("quelque chose"))
    assert "Paris" in block.profile and "Lyon" not in block.profile


def test_notifying_store_revise_notifies_every_listener():
    class Inner:
        def revise(self, memory_id, patch, expected_revision, **options):
            return SimpleNamespace(id=memory_id)

    def failing(_id):
        raise RuntimeError("boom")

    seen: list[str] = []
    store = NotifyingStore(Inner())
    store.add_listener(seen.append)
    store.add_listener(failing)  # a failing listener is skipped, the next one still runs
    store.add_listener(seen.append)
    store.revise("m1", MemoryPatch(body="x"), 1)
    assert seen == ["m1", "m1"]


async def test_revising_a_note_updates_the_lexical_index_through_the_wiring(wiring):
    created = wiring.store.create(note("Budget", "Le budget Atlas est de 10 euros."))
    wiring.store.revise(created.id, MemoryPatch(body="Le budget Atlas est de 99 euros."), 1)
    block = await wiring.context(turn("budget Atlas ?"))
    assert [hit.text for hit in block.recall] == ["Le budget Atlas est de 99 euros."]


# ------------------------------------------------------------------ P7: Tencent wiring
async def test_tencent_disabled_builds_nothing_and_touches_no_network(tmp_path):
    calls: list[httpx.Request] = []
    wiring = build_default_memory_wiring(
        tmp_path / "data", tmp_path / "s.json",
        tencent_transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200, json={})))
    await wiring.start()
    wiring.store.create(note("Budget", "Le budget Atlas est de 10 euros."))
    await wiring.stop()
    assert wiring.tencent is None and calls == []


async def test_tencent_enabled_registers_the_leg_and_the_mirror_and_closes_with_core(tmp_path):
    calls: list[httpx.Request] = []
    write_settings(tmp_path, {"tencent": {"enabled": True, "url": "http://127.0.0.1:9", "service_id": "inst-1"}})
    wiring = build_default_memory_wiring(
        tmp_path / "data", tmp_path / "settings.json",
        tencent_transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200, json={})))
    assert wiring.tencent is not None
    assert "tencent" in {leg.name for leg in wiring.hybrid_legs}
    await wiring.start()
    wiring.store.create(note("Budget", "Le budget Atlas est de 10 euros."))
    await asyncio.sleep(0.3)
    await wiring.stop()
    assert all(request.headers.get("x-tdai-service-id") == "inst-1" for request in calls)


# ------------------------------------------------------------------ P8: _run_core_v2 wiring
async def test_run_core_v2_builds_one_memory_wiring_and_mounts_the_maintenance_worker(tmp_path, monkeypatch):
    from jarvis.core import v2_app
    from jarvis.protocol import server

    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("JARVIS_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setattr(app, "_announce_calendar_backend", lambda *args: None)
    monkeypatch.setattr(app, "_calendar_backend_from_env", lambda: None)
    monkeypatch.setattr(app, "_drive_backend_from_env", lambda: None)
    captured: dict = {}

    async def backend_close():
        pass

    monkeypatch.setattr(app, "_brain_backend_from_env",
                        lambda: SimpleNamespace(base_url="http://127.0.0.1:9999", close=backend_close))

    class Core:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def start(self):
            pass

        async def wait(self):
            pass

        async def stop(self):
            pass

    class Server:
        def __init__(self, *args, **kwargs):
            pass

        async def start(self):
            pass

        async def stop(self):
            pass

    monkeypatch.setattr(v2_app, "JarvisCoreApplication", Core)
    monkeypatch.setattr(server, "LocalProtocolServer", Server)
    assert await app._run_core_v2() == 0
    memory = captured["memory"]
    assert memory.available and memory.store is not None and memory.service is not None
    assert "memory_maintenance" in captured["workers"]
    # Integration step: the consolidator is injected, the loadout resolver replaces the null one, the snapshot exists.
    assert captured["workers"]["memory_maintenance"].consolidator is memory.consolidation is not None
    assert type(memory.service.loadouts).__name__ == "KnowledgeLoadoutResolver"
    assert (tmp_path / "runtime" / "loadout-snapshot.json").is_file()

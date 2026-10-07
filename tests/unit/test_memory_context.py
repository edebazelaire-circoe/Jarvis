"""Bloc `memory` du tour : bornes, requête, réglages, dégradation (handoff jarvis-memory-intelligence-knowledge, Slice 05).

Contrat : `docs/memory.md` › *Injection into the Brain context*. Ce qui doit tenir :

- `BrainMemoryContext.bounded` coupe chaque texte sur un caractère entier, garde les souvenirs entiers dans
  les budgets (6 souvenirs, 400 caractères, 6 000 de bloc) et compte le reste ;
- la requête est l'énoncé (+ au plus un tour récent s'il a moins de 8 mots), sans appel de modèle, jamais journalisée ;
- les réglages sont relus au plus toutes les 2 s : `recall.enabled=false` agit au tour suivant ;
- un délai dépassé, un magasin en panne, un index en cours de synchronisation : un bloc dégradé, jamais une exception ;
- une note remplacée n'est jamais injectée, la portée privée ne fuit pas quand la politique la refuse.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
import statistics
import time

import pytest

from jarvis.core.memory_context import (
    SHORT_UTTERANCE_WORDS,
    CachedMemorySettings,
    MemoryTurnContext,
    build_query,
    render_knowledge_manifest,
)
from jarvis.core.memory_hybrid import HybridRetriever
from jarvis.core.memory_service import MemoryService, brain_policy
from jarvis.runtime.memory_composition import build_default_memory_wiring as build_memory_wiring
from jarvis.domain.brain_context import (
    MAX_BRAIN_MEMORY_CONTEXT_CHARS,
    MAX_BRAIN_MEMORY_ITEM_CHARS,
    MAX_BRAIN_MEMORY_MANIFEST_CHARS,
    MAX_BRAIN_MEMORY_PROFILE_CHARS,
    MAX_BRAIN_MEMORY_RECALL_ITEMS,
    BrainContext,
    BrainMemoryContext,
    BrainMemoryItem,
)
from jarvis.domain.knowledge import Loadout
from jarvis.domain.memory import (
    MemoryErrorCode,
    MemoryKind,
    MemoryLevel,
    MemoryNote,
    MemoryPatch,
    MemoryStoreError,
    RecallResult,
    RetentionClass,
    capability_ok,
    new_memory_id,
)
from jarvis.domain.memory_policy import AgentMemoryPolicy
from jarvis.domain.memory_settings import KnowledgeSettings
from jarvis.domain.v2 import BrainTurnInput, BrainTurnSource
from jarvis.runtime.memory_settings import read_memory_settings_file

T0 = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)


def READ(file):  # noqa: N802 - the settings reader the wiring injects, with no environment variable in play
    return read_memory_settings_file(file, {})


SECRET = "zorblaxquerytoken"


def note(title: str, body: str, **over) -> MemoryNote:
    base = dict(id=new_memory_id(), title=title, body=body, level=MemoryLevel.L1, kind=MemoryKind.FACT,
                retention=RetentionClass.LONG_TERM, scope="private", created_at=T0, updated_at=T0)
    return MemoryNote(**{**base, **over})


def turn(text: str, *, source: BrainTurnSource = BrainTurnSource.REALTIME) -> BrainTurnInput:
    return BrainTurnInput(conversation_id="conv-1", text=text, correlation_id="corr-1", source=source)


def item(index: int = 0, text: str = "texte", **over) -> BrainMemoryItem:
    values = dict(memory_id=f"id{index}", title=f"Titre {index}", text=text, level="L1",
                  retention="long_term_memory", source=f"long_term_memory/id{index}", revision=1)
    return BrainMemoryItem.bounded(**{**values, **over})


async def ready(wiring) -> None:
    async def loop() -> None:
        while not wiring.store.index_ready:
            await asyncio.sleep(0.01)

    await asyncio.wait_for(loop(), 30)


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
async def wiring(tmp_path, clock):
    built = build_memory_wiring(tmp_path / "data", tmp_path / "settings.json", clock=clock)
    assert built.available
    await ready(built)
    return built


def write_settings(tmp_path, memory: dict) -> None:
    (tmp_path / "settings.json").write_text(json.dumps({"memory": memory}), encoding="utf-8")


# =============================================================== bornes du domaine


def test_an_empty_block_is_empty_and_has_no_wire_form():
    block = BrainMemoryContext()
    assert block.is_empty and block.to_payload() == {}


def test_bounded_clips_an_item_on_a_whole_character_never_in_a_byte():
    text = "é" * 500 + "😀" * 50
    block = BrainMemoryContext.bounded(recall=[item(text=text)])
    clipped = block.recall[0].text
    assert len(clipped) <= MAX_BRAIN_MEMORY_ITEM_CHARS and clipped.endswith("…")
    assert clipped.encode("utf-8").decode("utf-8") == clipped and "�" not in clipped
    assert clipped[:-1] == ("é" * 500)[: len(clipped) - 1]


def test_bounded_keeps_at_most_six_items_whole_and_counts_the_rest():
    block = BrainMemoryContext.bounded(recall=[item(i, text="x" * 100) for i in range(9)])
    assert len(block.recall) == MAX_BRAIN_MEMORY_RECALL_ITEMS and block.omitted == 3
    assert [entry.memory_id for entry in block.recall] == [f"id{i}" for i in range(6)]
    assert block.to_payload()["omitted"] == 3


def test_bounded_honours_a_smaller_item_count_from_the_settings():
    block = BrainMemoryContext.bounded(recall=[item(i) for i in range(5)], max_items=2)
    assert len(block.recall) == 2 and block.omitted == 3


def test_bounded_keeps_the_whole_block_under_6000_characters_by_dropping_whole_items():
    big = [item(i, text="é" * 400, title="T" * 120, source="long_term_memory/" + "a" * 100) for i in range(6)]
    block = BrainMemoryContext.bounded(profile="p" * 5_000, recall=big, knowledge_manifest="k" * 3_000)
    size = len(json.dumps(block.to_payload(), ensure_ascii=False, separators=(",", ":")))
    assert size <= MAX_BRAIN_MEMORY_CONTEXT_CHARS
    assert len(block.profile) <= MAX_BRAIN_MEMORY_PROFILE_CHARS
    assert len(block.knowledge_manifest) <= MAX_BRAIN_MEMORY_MANIFEST_CHARS
    assert block.omitted > 0 and all(len(entry.text) == 400 for entry in block.recall)  # whole items, never half


def test_bounded_shrinks_the_profile_last_when_escapes_make_the_block_too_big():
    block = BrainMemoryContext.bounded(profile='"' * 2_048, recall=[item(i, text='"' * 400) for i in range(6)])
    assert len(json.dumps(block.to_payload(), ensure_ascii=False, separators=(",", ":"))) <= MAX_BRAIN_MEMORY_CONTEXT_CHARS


def test_the_constructor_refuses_what_bounded_would_have_cut():
    with pytest.raises(ValueError):
        BrainMemoryContext(profile="p" * (MAX_BRAIN_MEMORY_PROFILE_CHARS + 1))
    with pytest.raises(ValueError):
        BrainMemoryContext(recall=tuple(item(i) for i in range(7)))
    with pytest.raises(ValueError):
        BrainMemoryItem(memory_id="i", title="t", text="x" * (MAX_BRAIN_MEMORY_ITEM_CHARS + 1), level="L1",
                        retention="long_term_memory", source="long_term_memory/i", revision=1)
    with pytest.raises(ValueError):
        BrainMemoryContext(knowledge_manifest="k" * (MAX_BRAIN_MEMORY_MANIFEST_CHARS + 1))


def test_the_wire_form_carries_provenance_on_every_item_and_only_what_exists():
    payload = BrainMemoryContext.bounded(recall=[item(1)], degraded=("recall_timeout",)).to_payload()
    assert set(payload) == {"recall", "degraded"}
    assert payload["recall"][0]["source"] == "long_term_memory/id1" and payload["recall"][0]["revision"] == 1
    assert BrainMemoryContext.bounded(error="memory_failed").to_payload() == {"error": "memory_failed"}


def test_the_brain_context_takes_a_memory_block_only_of_that_type():
    from jarvis.domain.v2 import BrainWorkingState

    state = BrainWorkingState(conversation_id="c")
    assert BrainContext(state=state).memory is None
    with pytest.raises(TypeError):
        BrainContext(state=state, memory={"recall": []})  # type: ignore[arg-type]


# ======================================================================= requête


def test_a_short_utterance_borrows_the_previous_turn_a_long_one_does_not():
    assert build_query("et le budget ?", "Projet Atlas") == "Projet Atlas et le budget ?"
    long_text = " ".join(["mot"] * SHORT_UTTERANCE_WORDS)
    assert build_query(long_text, "Projet Atlas") == long_text
    assert build_query("et le budget ?", "") == "et le budget ?"


def test_the_borrowed_turn_is_clipped_and_the_query_bounded():
    query = build_query("oui", "y" * 5_000)
    assert query.startswith("y" * 100) and len(query) < 400
    assert len(build_query("m " * 3_000)) <= 2_000


# ======================================================================= réglages


def test_settings_are_re_read_at_most_every_two_seconds_and_only_when_the_file_changed(tmp_path, clock):
    path = tmp_path / "settings.json"
    cached = CachedMemorySettings(path, READ, clock=clock)
    assert cached.current().recall.enabled is True  # no file: defaults
    path.write_text(json.dumps({"memory": {"recall": {"enabled": False}}}), encoding="utf-8")
    clock.now += 1.0
    assert cached.current().recall.enabled is True  # looked at 1 s ago: not again yet
    clock.now += 1.5
    assert cached.current().recall.enabled is False
    path.write_text("{ not json", encoding="utf-8")
    clock.now += 3.0
    assert cached.current().recall.enabled is False  # unreadable: the last good value stays
    path.unlink()
    clock.now += 3.0
    assert cached.current().recall.enabled is True  # file gone: defaults


def test_the_raw_settings_serve_the_credential_reader(tmp_path, clock):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"other": 1}), encoding="utf-8")
    assert CachedMemorySettings(path, READ, clock=clock).raw() == {"other": 1}


def test_the_knowledge_manifest_lists_names_only_for_the_kinds_left_on():
    loadout = Loadout(profile="general", wiki_ids=("w1", "w2"), codegraph_repos=("jarvis",), skill_ids=("s1",))
    assert render_knowledge_manifest(loadout, KnowledgeSettings()) == "wiki: w1, w2; codegraph: jarvis; skills: s1"
    assert render_knowledge_manifest(loadout, KnowledgeSettings(wiki_enabled=False, skills_enabled=False)) == "codegraph: jarvis"
    assert render_knowledge_manifest(Loadout(profile="general"), KnowledgeSettings()) == ""


# ================================================== le constructeur, magasin réel


async def test_a_hit_carries_its_provenance_and_a_profile_note_the_stable_block(wiring):
    wiring.store.create(note("Budget Atlas", "Le budget du projet Atlas est de 42 000 euros."))
    wiring.store.create(note("Profil", "Clarice parle français et préfère les réponses courtes.",
                             level=MemoryLevel.L3, kind=MemoryKind.PROFILE))
    block = await wiring.context(turn("quel est le budget du projet Atlas ?"))
    assert block is not None and not block.degraded and block.error is None
    assert [entry.title for entry in block.recall] == ["Budget Atlas"]
    hit = block.recall[0]
    assert hit.source == f"long_term_memory/{hit.memory_id}" and hit.revision == 1 and hit.level == "L1"
    assert "42 000 euros" in hit.text and hit.why
    assert "Profil" in block.profile and "préfère les réponses courtes" in block.profile
    assert f"long_term_memory/" in block.profile  # the stable block cites its notes too


async def test_a_superseded_note_is_never_injected(wiring):
    old = wiring.store.create(note("Ancien budget", "Le budget Atlas est de 10 euros."))
    new = wiring.store.create(note("Nouveau budget", "Le budget Atlas est de 20 euros."))
    wiring.store.revise(old.id, MemoryPatch(superseded_by=new.id), 1)
    block = await wiring.context(turn("budget Atlas"))
    assert [entry.memory_id for entry in block.recall] == [new.id]
    assert old.id not in json.dumps(block.to_payload())


async def test_a_note_past_its_validity_is_never_in_the_profile(wiring):
    wiring.store.create(note("Ancien profil", "Habitait à Lyon.", level=MemoryLevel.L3, kind=MemoryKind.PROFILE,
                             valid_to=T0 - timedelta(days=1)))
    block = await wiring.context(turn("bonjour"))
    assert "Lyon" not in (block.profile if block else "")


async def test_the_private_scope_never_leaks_when_the_policy_forbids_it(tmp_path, clock):
    built = build_memory_wiring(tmp_path / "data", tmp_path / "settings.json", clock=clock)
    await ready(built)
    built.store.create(note("Secret", "Le code du coffre est 1234 Atlas.", scope="private"))
    built.store.create(note("Public", "Atlas est le nom du projet partagé.", scope="shared"))
    built.store.create(note("Profil privé", "Profil intime Atlas.", level=MemoryLevel.L3, kind=MemoryKind.PROFILE))
    service = built.service
    service.policy = AgentMemoryPolicy(agent_id="subagent", read_scopes=("shared",))
    service.retriever = HybridRetriever(built.hybrid_legs, policy=service.policy)
    block = await built.context(turn("Atlas"))
    wire = json.dumps(block.to_payload(), ensure_ascii=False)
    assert [entry.title for entry in block.recall] == ["Public"]
    assert "1234" not in wire and "intime" not in wire


async def test_a_policy_that_grants_nothing_recalls_and_lists_nothing(tmp_path, clock):
    built = build_memory_wiring(tmp_path / "data", tmp_path / "settings.json", clock=clock)
    await ready(built)
    built.store.create(note("Secret", "Atlas confidentiel."))
    built.service.policy = AgentMemoryPolicy(agent_id="nobody")
    block = await built.context(turn("Atlas"))
    assert block is not None and block.is_empty


async def test_a_turn_with_nothing_to_recall_is_an_empty_block_not_none(wiring):
    block = await wiring.context(turn("rien ici ne correspond"))
    assert block is not None and block.is_empty


async def test_a_system_turn_has_no_memory_block(wiring):
    assert await wiring.context(turn("réveil de travail", source=BrainTurnSource.SYSTEM)) is None


async def test_the_recent_turn_sharpens_a_short_utterance_without_being_part_of_the_block(wiring):
    wiring.store.create(note("Budget Atlas", "Le budget du projet Atlas est de 42 000 euros."))
    asked: list[str] = []

    async def previous(current: BrainTurnInput) -> str:
        asked.append(current.conversation_id)
        return "parle-moi du projet Atlas"

    wiring.context.bind_recent_turn(previous)
    block = await wiring.context(turn("et son budget ?"))
    assert asked == ["conv-1"] and [entry.title for entry in block.recall] == ["Budget Atlas"]
    asked.clear()
    await wiring.context(turn("quel est le budget exact du projet Atlas pour cette année ?"))
    assert asked == []  # a long utterance never reads the previous turn


async def test_a_failing_recent_turn_lookup_costs_the_pronoun_not_the_recall(wiring):
    wiring.store.create(note("Budget Atlas", "Le budget du projet Atlas est de 42 000 euros."))

    async def broken(current: BrainTurnInput) -> str:
        raise RuntimeError("history down")

    wiring.context.bind_recent_turn(broken)
    block = await wiring.context(turn("budget Atlas"))
    assert block is not None and block.error is None and len(block.recall) == 1


# ================================================ dégradation : jamais d'exception


class SlowRetriever:
    async def recall(self, query, budget):
        await asyncio.sleep(5)
        return RecallResult()

    def status(self):
        return capability_ok()


class BrokenRetriever:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    async def recall(self, query, budget):
        raise self.error

    def status(self):
        return capability_ok()


class EmptyStore:
    index_ready = True

    def list(self, filters):
        return ()


def builder_over(retriever, tmp_path, clock, *, store=None, timeout_ms: int | None = None) -> MemoryTurnContext:
    if timeout_ms is not None:
        write_settings(tmp_path, {"recall": {"timeout_ms": timeout_ms}})
    service = MemoryService(store or EmptyStore(), retriever, brain_policy())
    return MemoryTurnContext(service, CachedMemorySettings(tmp_path / "settings.json", READ, clock=clock))


async def test_a_recall_past_its_deadline_gives_a_degraded_block_and_the_turn_goes_on(tmp_path, clock):
    context = builder_over(SlowRetriever(), tmp_path, clock, timeout_ms=100)
    started = time.perf_counter()
    block = await context(turn("quelque chose"))
    assert time.perf_counter() - started < 0.5
    assert block is not None and block.degraded == ("recall_timeout",) and not block.recall and block.error is None
    assert block.to_payload() == {"degraded": ["recall_timeout"]}


async def test_a_store_exception_gives_an_error_block_never_an_exception(tmp_path, clock):
    context = builder_over(BrokenRetriever(RuntimeError("disk on fire")), tmp_path, clock)
    block = await context(turn("quelque chose"))
    assert block is not None and block.error == "memory_failed" and not block.recall


async def test_a_coded_store_refusal_is_a_degraded_block(tmp_path, clock):
    refusal = MemoryStoreError(MemoryErrorCode.UNAVAILABLE, "no leg could answer")
    block = await builder_over(BrokenRetriever(refusal), tmp_path, clock)(turn("quelque chose"))
    assert block.degraded == ("store_unavailable",) and block.error is None


async def test_a_profile_listing_that_fails_degrades_only_the_profile(tmp_path, clock):
    class Failing(EmptyStore):
        def list(self, filters):
            raise MemoryStoreError(MemoryErrorCode.UNAVAILABLE, "root refused")

    class Fine:
        async def recall(self, query, budget):
            return RecallResult()

        def status(self):
            return capability_ok()

    block = await builder_over(Fine(), tmp_path, clock, store=Failing())(turn("quelque chose"))
    assert block.degraded == ("profile_unavailable",) and block.error is None


async def test_an_index_still_syncing_is_reported_degraded_without_waiting(tmp_path, clock):
    class Syncing(EmptyStore):
        index_ready = False

    class Never:
        called = False

        async def recall(self, query, budget):
            Never.called = True
            return RecallResult()

        def status(self):
            return capability_ok()

    service = MemoryService(Syncing(), Never(), brain_policy(), index_ready=lambda: False)
    context = MemoryTurnContext(service, CachedMemorySettings(tmp_path / "s.json", READ, clock=clock))
    block = await context(turn("quelque chose"))
    assert block.degraded == ("index_syncing",) and Never.called is False


async def test_a_wiring_without_store_degrades_every_turn_and_names_it(tmp_path):
    context = MemoryTurnContext(None, CachedMemorySettings(tmp_path / "s.json", READ))
    block = await context(turn("quelque chose"))
    assert block.degraded == ("store_unavailable",) and block.to_payload() == {"degraded": ["store_unavailable"]}


async def test_the_semantic_leg_failing_keeps_the_lexical_items_and_says_so(tmp_path, clock):
    from tests.fakes.fake_embedder import FakeEmbedder

    built = build_memory_wiring(tmp_path / "data", tmp_path / "settings.json", clock=clock,
                                embedder=FakeEmbedder(fail=MemoryStoreError(MemoryErrorCode.UNAVAILABLE, "key missing")))
    await ready(built)
    built.store.create(note("Budget Atlas", "Le budget du projet Atlas est de 42 000 euros."))
    block = await built.context(turn("budget Atlas"))
    assert [entry.title for entry in block.recall] == ["Budget Atlas"]
    assert "semantic_unavailable" in block.degraded


# ============================================================== réglage à chaud


async def test_recall_enabled_false_takes_effect_at_the_next_turn_without_restart(tmp_path, wiring, clock):
    wiring.store.create(note("Budget Atlas", "Le budget du projet Atlas est de 42 000 euros."))
    assert len((await wiring.context(turn("budget Atlas"))).recall) == 1
    write_settings(tmp_path, {"recall": {"enabled": False}})
    clock.now += 2.5
    assert await wiring.context(turn("budget Atlas")) is None
    write_settings(tmp_path, {"recall": {"enabled": True, "max_items": 1}})
    clock.now += 2.5
    assert len((await wiring.context(turn("budget Atlas"))).recall) == 1


async def test_a_smaller_max_items_setting_applies_to_the_next_turn(tmp_path, wiring, clock):
    for index in range(4):
        wiring.store.create(note(f"Atlas {index}", f"Atlas détail numéro {index} du projet."))
    assert len((await wiring.context(turn("Atlas projet"))).recall) == 4
    write_settings(tmp_path, {"recall": {"max_items": 2}})
    clock.now += 2.5
    block = await wiring.context(turn("Atlas projet"))
    assert len(block.recall) == 2


# ===================================================================== journaux


async def test_the_query_is_in_no_log_record_on_the_happy_path(wiring, caplog):
    wiring.store.create(note("Budget", f"Le budget {SECRET} du projet est de 42 euros."))
    with caplog.at_level(logging.DEBUG):
        block = await wiring.context(turn(f"budget {SECRET}"))
    assert len(block.recall) == 1
    assert SECRET not in caplog.text and SECRET not in repr(block.timings_ms)


async def test_the_query_is_in_no_log_record_when_the_build_fails_or_times_out(tmp_path, clock, caplog):
    with caplog.at_level(logging.DEBUG):
        await builder_over(BrokenRetriever(RuntimeError("boom")), tmp_path, clock)(turn(f"budget {SECRET}"))
        await builder_over(SlowRetriever(), tmp_path, clock, timeout_ms=100)(turn(f"budget {SECRET}"))
    assert SECRET not in caplog.text


# ================================================================ démarrage de Core


async def test_an_unreadable_memory_root_gives_a_wiring_without_store_and_does_not_raise(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "memory").write_text("a file where the root should be", encoding="utf-8")
    events: list[tuple[str, str, dict]] = []

    class Sink:
        def emit(self, kind, message, *, level="info", data=None):
            events.append((kind, level, dict(data or {})))

    built = build_memory_wiring(data, tmp_path / "settings.json", diagnostics=Sink())
    assert not built.available and built.unavailable == "memory_unavailable" and built.store is None
    assert events and events[0][0] == "core.memory.unavailable" and events[0][1] == "error"
    block = await built.context(turn("quelque chose"))
    assert block.degraded == ("store_unavailable",)


async def test_a_missing_memory_root_is_created_and_recall_is_simply_empty(tmp_path):
    built = build_memory_wiring(tmp_path / "fresh-data", tmp_path / "settings.json")
    await ready(built)
    assert (tmp_path / "fresh-data" / "memory").is_dir() and built.unavailable is None
    assert (await built.context(turn("quelque chose"))).is_empty


async def test_startup_does_not_wait_for_the_index_sync_and_reports_it_degraded(tmp_path):
    release = asyncio.Event()

    class SlowStartStore(EmptyStore):
        """A store whose start-up sync is still running (amendment A2)."""

        ready = False

        def __init__(self, root) -> None:
            pass

        @property
        def index_ready(self) -> bool:
            return self.ready

        def search_ranked(self, *args, **kwargs):  # would block a thread for the whole sync
            assert self.ready, "a turn recall must not reach the store while the index syncs"
            return []

    store = SlowStartStore(None)
    started = time.perf_counter()
    built = build_memory_wiring(tmp_path / "data", tmp_path / "settings.json", store_factory=lambda root: store)
    assert time.perf_counter() - started < 1.0
    block = await built.context(turn("quelque chose"))
    assert block.degraded == ("index_syncing",)
    assert built.service.status()["store"].reason_code == "index_syncing"
    store.ready = True
    assert (await built.context(turn("quelque chose"))).degraded == ()
    release.set()


# ================================================================== latence (R1)


async def test_recall_over_2000_notes_adds_nothing_to_the_other_context_builders_and_stays_in_budget(tmp_path, clock, capsys):
    """Recall runs beside the other per-turn blocks: the turn waits for the slowest, never for their sum.

    Reports p50/p95 of the block build with 2 000 notes (the numbers go to the slice log; the gate is the
    400 ms budget, which `wait_for` enforces even on a slow host).
    """

    root = tmp_path / "data" / "memory" / "long_term_memory"
    root.mkdir(parents=True)
    subjects = ["voiture", "projet", "réunion", "budget", "voyage", "recette", "facture", "client"]
    for index in range(2_000):
        subject = subjects[index % len(subjects)]
        (root / f"note-{index:04d}.md").write_text(
            f"# Note {index} {subject}\nDétail {index} sur le {subject} numéro {index % 97}, mot-clé k{index % 211}.\n",
            encoding="utf-8")
    built = build_memory_wiring(tmp_path / "data", tmp_path / "settings.json", clock=clock)
    started = time.perf_counter()
    await ready(built)
    sync_s = time.perf_counter() - started

    async def other_block() -> None:  # stands for the work/board/session builders: 150 ms of awaiting
        await asyncio.sleep(0.15)

    alone: list[float] = []
    for index in range(30):
        began = time.perf_counter()
        block = await built.context(turn(f"parle-moi du {subjects[index % 8]} numéro {index % 97}"))
        alone.append((time.perf_counter() - began) * 1000)
        assert block is not None and block.error is None and not block.degraded and block.recall
    alone.sort()
    assert alone[-1] <= 400  # the budget, enforced by the builder itself

    samples: list[float] = []
    for index in range(30):
        began = time.perf_counter()
        block, _ = await asyncio.gather(built.context(turn(f"parle-moi du {subjects[index % 8]} numéro {index % 97}")), other_block())
        samples.append((time.perf_counter() - began) * 1000)
        assert block is not None and block.error is None
    build_ms = sorted(float(entry) for entry in samples)
    p50, p95 = statistics.median(build_ms), build_ms[int(len(build_ms) * 0.95) - 1]
    with capsys.disabled():
        print(f"\n[memory latency 2000 notes] index sync {sync_s:.2f}s; recall block alone "
              f"p50={statistics.median(alone):.0f} ms p95={alone[int(len(alone) * 0.95) - 1]:.0f} ms max={alone[-1]:.0f} ms; "
              f"turn wall (recall || 150 ms other) p50={p50:.0f} ms p95={p95:.0f} ms max={max(build_ms):.0f} ms")
    assert max(build_ms) <= 150 + 400 + 100  # never more than the slowest builder plus the recall budget
    assert p50 < 150 + 120  # in parallel: the recall hides behind the other builder

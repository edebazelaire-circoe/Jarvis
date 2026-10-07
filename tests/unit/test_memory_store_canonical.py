"""Canonical store (handoff jarvis-memory-intelligence-knowledge, Slice 02).

`MarkdownMemoryBackend` as a `CanonicalMemoryStore`: front-matter round trip,
legacy notes, revisions and history, optimistic concurrency, protected classes,
path defences, derived-index recovery, promotion with provenance.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import threading
import time

import pytest

from jarvis.adapters import file_replace, markdown_memory
from jarvis.adapters.markdown_memory import MarkdownMemoryBackend, legacy_note_id
from jarvis.core.memory_maintenance import RETAIN_MARKER, MemoryMaintenanceWorker
from jarvis.domain.errors import MemorySecurityError
from jarvis.domain.memory import (
    MemoryErrorCode,
    MemoryFilters,
    MemoryKind,
    MemoryLevel,
    MemoryNote,
    MemoryPatch,
    MemoryStoreError,
    Provenance,
    RetentionClass,
    SourceType,
    new_memory_id,
)
from jarvis.ports.memory_store import CanonicalMemoryStore

T0 = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)


def make_note(**over) -> MemoryNote:
    base = dict(
        id=new_memory_id(), title="Projet Atlas", body="Le budget est 42.", level=MemoryLevel.L1,
        kind=MemoryKind.FACT, retention=RetentionClass.SHORT_TERM, scope="private", created_at=T0, updated_at=T0,
    )
    return MemoryNote(**{**base, **over})


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "memory"


@pytest.fixture
def store(root: Path) -> MarkdownMemoryBackend:
    return MarkdownMemoryBackend(root)


def code(excinfo) -> MemoryErrorCode:
    return excinfo.value.code


def write_legacy(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def reopen(root: Path) -> MarkdownMemoryBackend:
    return MarkdownMemoryBackend(root)


# ------------------------------------------------------------------ the port
def test_store_implements_the_canonical_port(store):
    assert isinstance(store, CanonicalMemoryStore)


# ------------------------------------------------------------ create and get
def test_create_get_round_trip_keeps_every_field(store, root):
    source = Provenance(SourceType.TURN, "turn-12", T0)
    original = make_note(
        title="Préférence café", body="Premier paragraphe.\n\nDeuxième avec é et \U0001f600.",
        level=MemoryLevel.L2, kind=MemoryKind.PREFERENCE, retention=RetentionClass.PLASTIC, scope="project:atlas",
        agent="brain", valid_from=T0, valid_to=T0 + timedelta(days=30), confidence=0.65, sources=(source,),
        supersedes=("old1",), superseded_by="new1", contradicts=("other1", "other2"),
        updated_at=T0 + timedelta(hours=1),
    )
    stored = store.create(original)
    assert stored == original
    assert store.get(original.id) == original
    assert reopen(root).get(original.id) == original, "survives a restart"
    files = list((root / "plastic_memory").glob("*.md"))
    assert len(files) == 1 and files[0].name.endswith(f"-{original.id[:8]}.md")
    text = files[0].read_text(encoding="utf-8")
    assert text.startswith("---\n") and f'id: "{original.id}"' in text and "retention" not in text
    assert text.endswith("Deuxième avec é et \U0001f600.\n")


def test_new_notes_land_in_the_directory_of_their_class(store, root):
    for retention, level in (
        (RetentionClass.SHORT_TERM, MemoryLevel.L0), (RetentionClass.LONG_TERM, MemoryLevel.L1),
        (RetentionClass.TRAUMATIC, MemoryLevel.L2), (RetentionClass.ETERNAL, MemoryLevel.L3),
    ):
        note = store.create(make_note(retention=retention, level=level))
        assert (root / retention.value).is_dir() and store.get(note.id).retention is retention
    assert not (root / "notes").exists()


def test_create_normalises_body_edges_and_returns_what_get_returns(store):
    stored = store.create(make_note(title="  T  ", body="\n\ncorps\n\n"))
    assert stored.title == "T" and stored.body == "corps"
    assert store.get(stored.id) == stored


def test_create_refuses_bad_input_and_duplicates(store):
    with pytest.raises(TypeError):
        store.create({"id": "x"})  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        store.create(make_note(revision=2))
    created = store.create(make_note())
    with pytest.raises(MemoryStoreError) as dup:
        store.create(make_note(id=created.id, title="Autre"))
    assert code(dup) is MemoryErrorCode.CONFLICT_REVISION


def test_get_unknown_id_is_not_found(store):
    with pytest.raises(MemoryStoreError) as err:
        store.get("0" * 32)
    assert code(err) is MemoryErrorCode.NOT_FOUND


def test_empty_body_round_trips(store):
    stored = store.create(make_note(body=""))
    assert store.get(stored.id).body == ""


# --------------------------------------------------------- level x retention
def test_create_checks_level_against_retention(store, root):
    with pytest.raises(ValueError):
        store.create(make_note(retention=RetentionClass.LONG_TERM, level=MemoryLevel.L0))
    with pytest.raises(ValueError):
        store.create(make_note(retention=RetentionClass.TRAUMATIC, level=MemoryLevel.L3))
    assert not list(root.rglob("*.md"))


def test_check_level_retention_is_called_on_create_and_revise(store, monkeypatch):
    calls = []
    real = markdown_memory.check_level_retention
    monkeypatch.setattr(markdown_memory, "check_level_retention", lambda level, ret: (calls.append((level, ret)), real(level, ret))[1])
    note = store.create(make_note())
    store.revise(note.id, MemoryPatch(level=MemoryLevel.L2), 1)
    assert calls == [(MemoryLevel.L1, RetentionClass.SHORT_TERM), (MemoryLevel.L2, RetentionClass.SHORT_TERM)]


def test_revise_refuses_a_level_the_class_does_not_allow(store, root):
    note = store.create(make_note())  # short_term: no L3
    path = next((root / "short_term_memory").glob("*.md"))
    before = path.read_bytes()
    with pytest.raises(ValueError):
        store.revise(note.id, MemoryPatch(level=MemoryLevel.L3), 1)
    assert path.read_bytes() == before and not (root / ".history").exists()


# ------------------------------------------------------------ legacy notes
def test_legacy_note_in_notes_dir_is_long_term_readable_and_never_moved(root):
    path = write_legacy(root, "notes/20260101-vieux-abc.md", "# Vieux souvenir\n\nLa clé est sous le paillasson.\n")
    raw = path.read_bytes()
    store = reopen(root)
    rid = legacy_note_id("notes/20260101-vieux-abc.md")
    note = store.get(rid)
    assert (note.title, note.body) == ("Vieux souvenir", "La clé est sous le paillasson.")
    assert note.retention is RetentionClass.LONG_TERM and note.level is MemoryLevel.L1
    assert note.kind is MemoryKind.FACT and note.scope == "private" and note.revision == 1
    assert [n.id for n in store.list(MemoryFilters())] == [rid]
    assert [h.memory_id for h in store.search_ranked("paillasson")] == [rid]
    assert store.search_ranked("paillasson", filters=MemoryFilters(retentions=(RetentionClass.LONG_TERM,)))
    store.rebuild_indexes()
    assert path.read_bytes() == raw, "reading never writes the legacy note back"
    assert store.history(rid) == (note,)


def test_legacy_note_gets_metadata_only_when_revised_and_stays_in_place(root):
    path = write_legacy(root, "notes/vieux.md", "# Vieux\n\nancien texte\n")
    raw = path.read_text(encoding="utf-8")
    store = reopen(root)
    rid = legacy_note_id("notes/vieux.md")
    revised = store.revise(rid, MemoryPatch(body="texte corrigé"), 1)
    assert path.exists() and revised.revision == 2 and revised.retention is RetentionClass.LONG_TERM
    assert path.read_text(encoding="utf-8").startswith("---\n") and not (root / "long_term_memory").exists()
    assert (root / ".history" / f"{rid}.rev1.md").read_text(encoding="utf-8") == raw
    versions = store.history(rid)
    assert [(n.revision, n.body) for n in versions] == [(1, "ancien texte"), (2, "texte corrigé")]
    assert store.get(rid).id == rid, "identity unchanged once the id is stored"


def test_legacy_note_outside_the_five_classes_is_long_term(root):
    write_legacy(root, "vrac.md", "sans titre, juste du texte\n")
    note = reopen(root).get(legacy_note_id("vrac.md"))
    assert note.retention is RetentionClass.LONG_TERM and note.title == "vrac" and note.body == "sans titre, juste du texte"


def test_hand_written_partial_front_matter_is_completed_with_defaults(root):
    write_legacy(root, "long_term_memory/a.md", '---\nid: "hand1"\nconfidence: 0.4\n---\n# À la main\n\ncorps\n')
    note = reopen(root).get("hand1")
    assert note.confidence == 0.4 and note.level is MemoryLevel.L1 and note.title == "À la main"


def test_invalid_metadata_values_fall_back_to_defaults_keeping_the_id(root):
    write_legacy(root, "long_term_memory/a.md", '---\nid: "keep1"\nlevel: "L9"\n---\n# T\n\ncorps\n')
    note = reopen(root).get("keep1")
    assert note.level is MemoryLevel.L1 and note.body == "corps"


def test_oversized_note_is_not_listed_but_still_searchable_by_the_legacy_search(root):
    write_legacy(root, "long_term_memory/big.md", "# Big\n\nmotgeant " + "x" * 70_000)
    store = reopen(root)
    assert store.list(MemoryFilters()) == ()
    hits = asyncio.run(store.search("motgeant"))
    assert hits and hits[0].memory_id == "long_term_memory/big.md"


# ----------------------------------------------------------- unknown keys
def test_unknown_front_matter_keys_survive_a_revision(root):
    store = reopen(root)
    note = store.create(make_note())
    path = next((root / "short_term_memory").glob("*.md"))
    path.write_text(path.read_text(encoding="utf-8").replace("---\n# ", '---\n# ', 1).replace(
        f'id: "{note.id}"\n', f'id: "{note.id}"\nobsidian_tags: ["a", "b"]\nowner: "moi"\n', 1), encoding="utf-8")
    store.rebuild_indexes()
    store.revise(note.id, MemoryPatch(body="nouveau"), 1)
    text = path.read_text(encoding="utf-8")
    assert 'obsidian_tags: ["a", "b"]' in text and 'owner: "moi"' in text and "revision: 2" in text
    assert store.get(note.id).body == "nouveau"


# ----------------------------------------------------------- corrupt block
def test_corrupt_block_is_body_only_and_the_note_is_never_dropped(root):
    text = '---\nid: "x"\nthis is not valid\n---\n# Titre cassé\n\ncontenu retrouvable zorglub\n'
    path = write_legacy(root, "long_term_memory/c.md", text)
    store = reopen(root)
    rid = legacy_note_id("long_term_memory/c.md")
    note = store.get(rid)
    assert note.title == "Titre cassé" and "this is not valid" in note.body, "the whole text is the body"
    assert [h.memory_id for h in store.search_ranked("zorglub")] == [rid]
    assert [n.id for n in store.list(MemoryFilters())] == [rid]
    assert path.read_text(encoding="utf-8") == text
    store.revise(rid, MemoryPatch(confidence=0.5), 1)
    assert (root / ".history" / f"{rid}.rev1.md").read_text(encoding="utf-8") == text, "raw text kept in history"
    assert "zorglub" in store.get(rid).body


# ----------------------------------------------- front matter not indexed
def test_front_matter_is_stripped_before_indexing(store, root):
    note = store.create(make_note(id="zzmetaid", body="contenu normal", agent="agentzz"))
    assert store.search_ranked("zzmetaid") == [] and store.search_ranked("agentzz") == []
    assert asyncio.run(store.search("agentzz")) == []
    assert [h.memory_id for h in store.search_ranked("contenu")] == [note.id]
    # a restart (full rebuild) indexes the same thing
    assert reopen(root).search_ranked("zzmetaid") == []


def test_legacy_read_strips_the_metadata_block(store):
    note = store.create(make_note(body="lisible"))
    rel = next(iter(store.search_ranked("lisible"))).path
    record = asyncio.run(store.read(rel))
    assert record.body == "# Projet Atlas\n\nlisible\n" and record.title == "Projet Atlas"


# ------------------------------------------------------------ revise
def test_revise_writes_next_revision_and_keeps_the_previous_in_history(store, root):
    note = store.create(make_note(body="v1"))
    later = T0 + timedelta(minutes=5)
    src = Provenance(SourceType.MANUAL, "moi", later)
    v2 = store.revise(note.id, MemoryPatch(body="v2", add_sources=(src,), confidence=0.5), 1)
    v3 = store.revise(note.id, MemoryPatch(title="Nouveau titre", add_contradicts=("c1",)), 2)
    assert (v2.revision, v3.revision) == (2, 3)
    assert v2.sources == (src,) and v3.sources == (src,) and v3.contradicts == ("c1",)
    assert v3.created_at == T0 and v3.updated_at >= v2.updated_at > T0
    assert store.get(note.id) == v3
    assert [n.revision for n in store.history(note.id)] == [1, 2, 3]
    assert [n.body for n in store.history(note.id)] == ["v1", "v2", "v2"]
    assert sorted(p.name for p in (root / ".history").iterdir()) == [f"{note.id}.rev1.md", f"{note.id}.rev2.md"]
    assert store.history(note.id)[-1] == v3
    assert len(list((root / "short_term_memory").glob("*.md"))) == 1, "one live file per note"


def test_revise_links_are_added_without_duplicates(store):
    note = store.create(make_note(supersedes=("a",)))
    revised = store.revise(note.id, MemoryPatch(add_supersedes=("a", "b"), superseded_by="z"), 1)
    assert revised.supersedes == ("a", "b") and revised.superseded_by == "z"
    with pytest.raises(ValueError):
        store.revise(note.id, MemoryPatch(add_contradicts=(note.id,)), 2)


def test_revise_conflict_revision_and_not_found(store):
    note = store.create(make_note())
    store.revise(note.id, MemoryPatch(body="x"), 1)
    with pytest.raises(MemoryStoreError) as stale:
        store.revise(note.id, MemoryPatch(body="y"), 1)
    assert code(stale) is MemoryErrorCode.CONFLICT_REVISION
    assert store.get(note.id).body == "x"
    with pytest.raises(MemoryStoreError) as missing:
        store.revise("1" * 32, MemoryPatch(body="y"), 1)
    assert code(missing) is MemoryErrorCode.NOT_FOUND


def test_concurrent_revisions_with_the_same_expected_revision_yield_one_winner(store):
    note = store.create(make_note())
    outcomes: list[str] = []
    gate = threading.Barrier(6)

    def attempt(n: int) -> None:
        gate.wait()
        try:
            store.revise(note.id, MemoryPatch(body=f"b{n}"), 1)
            outcomes.append("ok")
        except MemoryStoreError as exc:
            outcomes.append(exc.code.value)

    threads = [threading.Thread(target=attempt, args=(n,)) for n in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert outcomes.count("ok") == 1 and outcomes.count("memory_conflict_revision") == 5
    assert store.get(note.id).revision == 2


def test_revise_failure_mid_write_leaves_the_old_revision_intact(store, root, monkeypatch):
    note = store.create(make_note(body="ancien"))
    path = next((root / "short_term_memory").glob("*.md"))
    before = path.read_bytes()
    real = markdown_memory.replace_with_retry
    calls = []

    def flaky(source, target):
        calls.append(Path(target).name)
        if len(calls) == 2:  # history written, now the live file
            raise OSError("disque plein")
        real(source, target)

    monkeypatch.setattr(markdown_memory, "replace_with_retry", flaky)
    with pytest.raises(MemoryStoreError) as err:
        store.revise(note.id, MemoryPatch(body="nouveau"), 1)
    assert code(err) is MemoryErrorCode.UNAVAILABLE
    assert path.read_bytes() == before
    assert store.get(note.id).revision == 1 and store.get(note.id).body == "ancien"
    assert store.search_ranked("ancien") and not store.search_ranked("nouveau")
    assert not list((root / ".history").glob("*.md")), "no phantom history for a revision that never landed"
    assert not list(root.rglob("*.tmp")), "no temp file left behind"
    monkeypatch.setattr(markdown_memory, "replace_with_retry", real)
    assert store.revise(note.id, MemoryPatch(body="nouveau"), 1).revision == 2


def test_create_failure_leaves_nothing_and_a_clear_error(store, root, monkeypatch):
    def boom(source, target):
        raise OSError("verrou")

    monkeypatch.setattr(markdown_memory, "replace_with_retry", boom)
    with pytest.raises(MemoryStoreError) as err:
        store.create(make_note())
    assert code(err) is MemoryErrorCode.UNAVAILABLE
    assert not list(root.rglob("*.md")) and not list(root.rglob("*.tmp"))


def test_windows_style_transient_replace_lock_is_retried(store, monkeypatch):
    note = store.create(make_note(body="a"))
    monkeypatch.setattr(file_replace, "REPLACE_BACKOFF_S", 0.0)
    monkeypatch.setattr(file_replace, "REPLACE_BACKOFF_MAX_S", 0.0)
    real, failures = os.replace, []

    def locked_twice(source, target):
        if len(failures) < 2:
            failures.append(1)
            raise PermissionError(13, "WinError 5 simulated", str(target))
        return real(source, target)

    monkeypatch.setattr(file_replace.os, "replace", locked_twice)
    assert store.revise(note.id, MemoryPatch(body="b"), 1).revision == 2
    assert len(failures) == 2 and store.get(note.id).body == "b"


def test_a_lock_that_never_clears_is_an_error_not_a_hang(store, monkeypatch):
    note = store.create(make_note(body="a"))
    monkeypatch.setattr(file_replace, "REPLACE_BACKOFF_S", 0.0)
    monkeypatch.setattr(file_replace, "REPLACE_BACKOFF_MAX_S", 0.0)

    def always_locked(source, target):
        raise PermissionError(13, "locked", str(target))

    monkeypatch.setattr(file_replace.os, "replace", always_locked)
    with pytest.raises(MemoryStoreError) as err:
        store.revise(note.id, MemoryPatch(body="b"), 1)
    assert code(err) is MemoryErrorCode.UNAVAILABLE
    monkeypatch.undo()
    assert store.get(note.id).body == "a"


# --------------------------------------------------------- protected classes
@pytest.mark.parametrize("retention", [RetentionClass.TRAUMATIC, RetentionClass.ETERNAL])
def test_protected_notes_are_never_rewritten(store, root, retention):
    note = store.create(make_note(retention=retention, body="gravé"))
    path = next((root / retention.value).glob("*.md"))
    before = path.read_bytes()
    for patch in (
        MemoryPatch(body="réécrit"), MemoryPatch(title="autre"), MemoryPatch(confidence=0.1),
        MemoryPatch(level=MemoryLevel.L2), MemoryPatch(kind=MemoryKind.EPISODE),
    ):
        for human in (False, True):
            with pytest.raises(MemoryStoreError) as err:
                store.revise(note.id, patch, 1, human=human)
            assert code(err) is MemoryErrorCode.SCOPE_DENIED
    assert path.read_bytes() == before and not (root / ".history").exists()


def test_protected_note_supersession_needs_a_human(store, root):
    note = store.create(make_note(retention=RetentionClass.ETERNAL))
    patch = MemoryPatch(superseded_by="newer", valid_to=T0 + timedelta(days=1))
    with pytest.raises(MemoryStoreError) as err:
        store.revise(note.id, patch, 1)
    assert code(err) is MemoryErrorCode.SCOPE_DENIED
    revised = store.revise(note.id, patch, 1, human=True)
    assert revised.superseded_by == "newer" and revised.revision == 2 and revised.body == note.body
    assert [n.body for n in store.history(note.id)] == [note.body, note.body]


def test_maintenance_and_rebuilds_never_touch_protected_notes(store, root):
    kept = [store.create(make_note(retention=r, body=f"sacré {r.value}")) for r in
            (RetentionClass.TRAUMATIC, RetentionClass.ETERNAL)]
    snapshot = {p: p.read_bytes() for p in root.rglob("*.md")}
    store.rebuild_indexes()
    asyncio.run(MemoryMaintenanceWorker(root, store).execute(None))
    reopen(root)
    assert {p: p.read_bytes() for p in root.rglob("*.md")} == snapshot
    assert [store.get(n.id) for n in kept] == kept


# ------------------------------------------------------------ list / filters
def test_list_orders_filters_and_paginates(store):
    a = store.create(make_note(title="A", updated_at=T0 + timedelta(hours=1), scope="shared"))
    b = store.create(make_note(title="B", updated_at=T0 + timedelta(hours=3), retention=RetentionClass.LONG_TERM))
    c = store.create(make_note(title="C", updated_at=T0 + timedelta(hours=2), level=MemoryLevel.L2,
                               kind=MemoryKind.SCENARIO, scope="board:b1"))
    assert [n.id for n in store.list(MemoryFilters())] == [b.id, c.id, a.id]
    assert [n.id for n in store.list(MemoryFilters(limit=1, offset=1))] == [c.id]
    assert [n.id for n in store.list(MemoryFilters(scopes=("shared",)))] == [a.id]
    assert [n.id for n in store.list(MemoryFilters(retentions=(RetentionClass.LONG_TERM,)))] == [b.id]
    assert [n.id for n in store.list(MemoryFilters(levels=(MemoryLevel.L2,)))] == [c.id]
    assert [n.id for n in store.list(MemoryFilters(kinds=(MemoryKind.SCENARIO,)))] == [c.id]
    assert store.list(MemoryFilters(scopes=("project:none",))) == ()


def test_superseded_notes_are_hidden_unless_asked(store):
    old = store.create(make_note(title="Ancien fait"))
    new = store.create(make_note(title="Nouveau fait"))
    store.revise(old.id, MemoryPatch(superseded_by=new.id), 1)
    assert [n.id for n in store.list(MemoryFilters())] == [new.id]
    assert {n.id for n in store.list(MemoryFilters(include_superseded=True))} == {old.id, new.id}
    assert [h.memory_id for h in store.search_ranked("fait")] == [new.id]
    assert {h.memory_id for h in store.search_ranked("fait", filters=MemoryFilters(include_superseded=True))} == {old.id, new.id}


# ---------------------------------------------------------- search_ranked
def test_search_ranked_has_no_ten_item_cap_and_legacy_search_keeps_it(store):
    ids = {store.create(make_note(title=f"Fiche {n}", body="mot-clef commun")).id for n in range(15)}
    assert {h.memory_id for h in store.search_ranked("commun", limit=50)} == ids
    assert len(store.search_ranked("commun", limit=12)) == 12
    assert len(asyncio.run(store.search("commun", limit=50))) == 10
    assert len(store.search_ranked("commun")) == 15


def test_search_ranked_orders_by_relevance_and_reports_facts(store):
    weak = store.create(make_note(title="Faible", body="atlas une fois " + "blabla " * 40))
    strong = store.create(make_note(title="Fort", body="atlas atlas atlas", scope="shared", agent="a"))
    hits = store.search_ranked("atlas")
    assert [h.memory_id for h in hits] == [strong.id, weak.id]
    top = hits[0]
    assert top.score >= hits[1].score and top.scope == "shared" and top.revision == 1
    assert top.retention is RetentionClass.SHORT_TERM and top.level is MemoryLevel.L1 and top.kind is MemoryKind.FACT
    assert top.updated_at == T0 and top.path.startswith("short_term_memory/") and top.title == "Fort"
    assert store.search_ranked("... ---") == []


def test_search_ranked_filters(store):
    a = store.create(make_note(body="zebre", scope="shared"))
    store.create(make_note(body="zebre", scope="private"))
    assert [h.memory_id for h in store.search_ranked("zebre", filters=MemoryFilters(scopes=("shared",)))] == [a.id]
    assert store.search_ranked("zebre", filters=MemoryFilters(scopes=("board:none",))) == []


def test_every_mutation_reaches_the_index_at_once(store):
    note = store.create(make_note(body="avant sentinelle1"))
    assert store.search_ranked("sentinelle1")
    store.revise(note.id, MemoryPatch(body="apres sentinelle2"), 1)
    assert not store.search_ranked("sentinelle1")
    assert [h.memory_id for h in store.search_ranked("sentinelle2")] == [note.id]
    record = asyncio.run(store.append_note("Legacy", "sentinelle3 ajoutée"))
    assert asyncio.run(store.search("sentinelle3"))[0].memory_id == record.memory_id
    assert [h.path for h in store.search_ranked("sentinelle3")] == [record.memory_id]


def test_append_note_lands_in_short_term_memory_with_the_same_bytes(store, root):
    record = asyncio.run(store.append_note("Projet Atlas", "Le budget est 42."))
    assert record.memory_id.startswith("short_term_memory/")
    assert (root / record.memory_id).read_text(encoding="utf-8") == "# Projet Atlas\n\nLe budget est 42.\n"
    assert not (root / "notes").exists()
    assert store.get(legacy_note_id(record.memory_id)).retention is RetentionClass.SHORT_TERM


# -------------------------------------------------- derived index recovery
def test_deleting_the_derived_index_loses_nothing(root):
    store = reopen(root)
    one = store.create(make_note(title="Un", body="alpha"))
    two = store.create(make_note(title="Deux", body="beta"))
    store.revise(two.id, MemoryPatch(body="beta corrigé"), 1)
    legacy = write_legacy(root, "notes/leg.md", "# Leg\n\ngamma\n")
    store.rebuild_indexes()
    expected = (store.list(MemoryFilters()), store.history(two.id))
    del store
    for victim in (root / ".jarvis").glob("index.sqlite3*"):
        victim.unlink()
    again = reopen(root)
    assert (again.list(MemoryFilters()), again.history(two.id)) == expected
    assert again.get(one.id).body == "alpha" and again.search_ranked("corrigé") and again.search_ranked("gamma")
    assert legacy.read_text(encoding="utf-8") == "# Leg\n\ngamma\n"


def test_index_deleted_while_running_is_healed_on_next_read(store, root):
    note = store.create(make_note(body="vivant"))
    store.db_path.unlink()
    assert store.get(note.id).body == "vivant"
    assert [h.memory_id for h in store.search_ranked("vivant")] == [note.id]
    assert [n.id for n in store.list(MemoryFilters())] == [note.id]


def test_corrupt_index_is_dropped_and_rebuilt_from_markdown(store, root):
    note = store.create(make_note(body="résilient"))
    store.db_path.write_bytes(b"not a sqlite database")
    assert store.get(note.id).body == "résilient"
    assert store.search_ranked("résilient")
    assert reopen(root).get(note.id).body == "résilient"


def test_rebuild_indexes_returns_the_number_of_indexed_notes(store, root):
    store.create(make_note())
    write_legacy(root, "notes/a.md", "# A\n\nb\n")
    assert store.rebuild_indexes() == 2


def test_a_moved_note_keeps_its_identity(store, root):
    note = store.create(make_note(body="voyageur"))
    path = next((root / "short_term_memory").glob("*.md"))
    target = root / "long_term_memory"
    target.mkdir()
    path.replace(target / path.name)
    assert store.get(note.id).retention is RetentionClass.LONG_TERM


def test_index_failure_after_a_canonical_write_does_not_fail_the_write(store, monkeypatch):
    import sqlite3

    def broken(doc):
        raise sqlite3.OperationalError("index unavailable")

    monkeypatch.setattr(store, "_upsert_doc", broken)
    note = store.create(make_note(body="durable"))
    assert store.get(note.id).body == "durable"


# ---------------------------------------------------- lazy / threaded start
def test_construction_does_not_wait_for_the_index_sync(root, monkeypatch):
    for n in range(3):
        write_legacy(root, f"long_term_memory/n{n}.md", f"# N{n}\n\ncorps{n}\n")
    gate = threading.Event()
    real = MarkdownMemoryBackend._rebuild_index_sync

    def slow(self):
        gate.wait(10)
        return real(self)

    monkeypatch.setattr(MarkdownMemoryBackend, "_rebuild_index_sync", slow)
    started = time.monotonic()
    store = MarkdownMemoryBackend(root)
    assert time.monotonic() - started < 2 and not store._ready.is_set()
    results: list[int] = []
    reader = threading.Thread(target=lambda: results.append(len(store.list(MemoryFilters()))))
    reader.start()
    reader.join(0.3)
    assert reader.is_alive(), "reads wait for the sync instead of answering from a stale index"
    gate.set()
    reader.join(10)
    assert results == [3] and store._ready.is_set()


def test_restart_resyncs_external_edits_before_the_first_read(root):
    store = reopen(root)
    note = store.create(make_note(body="avant"))
    path = next((root / "short_term_memory").glob("*.md"))
    path.write_text(path.read_text(encoding="utf-8").replace("avant", "après-edit"), encoding="utf-8")
    again = reopen(root)
    assert again.get(note.id).body == "après-edit" and not again.search_ranked("avant")


# ---------------------------------------------------- excluded directories
def test_candidates_and_history_are_never_recalled_or_listed(store, root):
    write_legacy(root, "_candidates/c1.md", "# Candidat\n\nsecretcandidat\n")
    write_legacy(root, ".hidden/h.md", "# Caché\n\nsecretcache\n")
    note = store.create(make_note(body="visible"))
    store.revise(note.id, MemoryPatch(body="visible deux secrethistorique"), 1)
    store.rebuild_indexes()
    for word in ("secretcandidat", "secretcache"):
        assert store.search_ranked(word) == [] and asyncio.run(store.search(word)) == []
    assert [h.memory_id for h in store.search_ranked("visible")] == [note.id]
    assert [n.id for n in store.list(MemoryFilters(include_superseded=True))] == [note.id]


# --------------------------------------------------- traversal and links
@pytest.mark.parametrize("bad", ["../x", "..", "%2e%2e/x", "a/b", "a\\b", "/etc/passwd", "", " ", "x" * 65])
def test_ids_that_are_not_tokens_are_refused(store, bad):
    for call in (lambda: store.get(bad), lambda: store.history(bad),
                 lambda: store.revise(bad, MemoryPatch(body="x"), 1)):
        with pytest.raises(MemorySecurityError):
            call()


def test_non_string_id_is_refused(store):
    with pytest.raises(MemorySecurityError):
        store.get(123)  # type: ignore[arg-type]


@pytest.mark.parametrize("name", ["../evil.md", "a/b.md", "..\\evil.md", "..", ".", ""])
def test_promotion_file_names_cannot_traverse(store, name):
    with pytest.raises(MemorySecurityError):
        store.create(make_note(), filename=name)


def test_create_file_name_must_be_a_visible_markdown_file(store):
    for name in ("x.txt", ".hidden.md", "_x.md"):
        with pytest.raises(ValueError):
            store.create(make_note(), filename=name)


def make_dir_link(link: Path, target: Path) -> bool:
    """Directory symlink, else a Windows junction; False when neither can be made."""

    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        return done.returncode == 0
    return False


def test_a_retention_directory_that_is_a_link_is_never_written_through(tmp_path, root):
    outside = tmp_path / "outside"
    outside.mkdir()
    root.mkdir()
    if not make_dir_link(root / "long_term_memory", outside):
        pytest.skip("directory links unavailable")
    store = reopen(root)
    with pytest.raises(MemorySecurityError):
        store.create(make_note(retention=RetentionClass.LONG_TERM))
    assert not list(outside.iterdir())


def test_a_history_directory_that_is_a_link_stops_the_revision(tmp_path, root):
    store = reopen(root)
    note = store.create(make_note(body="v1"))
    path = next((root / "short_term_memory").glob("*.md"))
    before = path.read_bytes()
    outside = tmp_path / "outside"
    outside.mkdir()
    if not make_dir_link(root / ".history", outside):
        pytest.skip("directory links unavailable")
    with pytest.raises(MemorySecurityError):
        store.revise(note.id, MemoryPatch(body="v2"), 1)
    assert path.read_bytes() == before and not list(outside.iterdir())


def test_a_note_directory_that_is_a_link_is_neither_indexed_nor_revisable(tmp_path, root):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "ext.md").write_text("# Extérieur\n\nsecretexterieur\n", encoding="utf-8")
    root.mkdir()
    if not make_dir_link(root / "plastic_memory", outside):
        pytest.skip("directory links unavailable")
    store = reopen(root)
    assert store.search_ranked("secretexterieur") == [] and store.list(MemoryFilters()) == ()
    with pytest.raises(MemoryStoreError):
        store.get(legacy_note_id("plastic_memory/ext.md"))


def test_a_symlinked_note_file_is_ignored(tmp_path, root):
    outside = tmp_path / "outside.md"
    outside.write_text("# Dehors\n\nsecretfichier\n", encoding="utf-8")
    (root / "long_term_memory").mkdir(parents=True)
    try:
        (root / "long_term_memory" / "lien.md").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    store = reopen(root)
    assert store.search_ranked("secretfichier") == [] and store.list(MemoryFilters()) == ()


# --------------------------------------------------------------- promotion
def test_promote_file_copies_with_provenance_and_is_idempotent(store, root):
    src = store.create(make_note(title="À garder", body=f"fait important {RETAIN_MARKER}", level=MemoryLevel.L0))
    rel = store.search_ranked("important")[0].path
    promoted = store.promote_file(rel, RetentionClass.LONG_TERM)
    assert promoted is not None and promoted.id != src.id and promoted.retention is RetentionClass.LONG_TERM
    assert promoted.level is MemoryLevel.L1, "L0 is not valid outside short_term_memory"
    assert promoted.sources[-1].type is SourceType.NOTE and promoted.sources[-1].ref == src.id
    assert promoted.revision == 1 and promoted.title == "À garder"
    assert (root / "long_term_memory" / Path(rel).name).is_file() and (root / rel).is_file(), "source stays"
    assert store.get(promoted.id) == promoted and store.get(src.id) == src
    assert {h.memory_id for h in store.search_ranked("important")} == {src.id, promoted.id}
    assert store.promote_file(rel, RetentionClass.LONG_TERM) is None
    assert len(list((root / "long_term_memory").glob("*.md"))) == 1


def test_promoting_a_legacy_note_cites_its_path(store, root):
    write_legacy(root, "short_term_memory/leg.md", f"# Leg\n\ncorps {RETAIN_MARKER}\n")
    store.rebuild_indexes()
    promoted = store.promote_file("short_term_memory/leg.md", RetentionClass.LONG_TERM)
    assert promoted.sources[-1].ref == "short_term_memory/leg.md"
    assert (root / "short_term_memory" / "leg.md").read_text(encoding="utf-8") == f"# Leg\n\ncorps {RETAIN_MARKER}\n"


def test_promote_missing_source_is_an_error(store):
    with pytest.raises(FileNotFoundError):
        store.promote_file("short_term_memory/none.md", RetentionClass.LONG_TERM)
    with pytest.raises(MemorySecurityError):
        store.promote_file("../x.md", RetentionClass.LONG_TERM)


def test_maintenance_worker_promotes_retained_notes_through_the_store(store, root):
    kept = store.create(make_note(title="Garde", body=f"à retenir {RETAIN_MARKER}"))
    store.create(make_note(title="Jette", body="éphémère"))
    worker = MemoryMaintenanceWorker(root, store)
    assert asyncio.run(worker.execute(None)) == {"promoted": 1}
    assert asyncio.run(worker.execute(None)) == {"promoted": 0}
    copies = store.list(MemoryFilters(retentions=(RetentionClass.LONG_TERM,)))
    assert len(copies) == 1 and copies[0].sources[-1].ref == kept.id
    assert [h.memory_id for h in store.search_ranked("retenir", filters=MemoryFilters(retentions=(RetentionClass.LONG_TERM,)))] == [copies[0].id]
    assert all((root / name).is_dir() for name in ("traumatic_memory", "eternal_memory", "plastic_memory"))


def test_maintenance_class_list_is_the_domain_enum():
    from jarvis.core.memory_maintenance import MEMORY_CLASSES

    assert MEMORY_CLASSES == tuple(item.value for item in RetentionClass)

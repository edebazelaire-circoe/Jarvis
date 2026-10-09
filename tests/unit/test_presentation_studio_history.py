"""Anneau d'annulation borne, pur (jarvis-interactive-presentation-studio, Slice 08).

`UndoBook` seul, sans E/S : chaque borne dure (entrees par variante, octets par variante, octets au total, variantes
suivies, octets d'une entree), l'eviction visible (`Drop`, compteurs), la pile rétablir vidée par une nouvelle edition,
l'abandon quand le document a bougé, le « trou » d'une entrée trop grosse, les pins tenus. Contrat :
`docs/presentation-studio.md` > *Persistence and undo contract*.
"""

from __future__ import annotations

import random

import pytest

from jarvis.domain.presentation_studio_checks import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_history import (
    HISTORY_CODE, MAX_ENTRIES_PER_VARIANT, MAX_ENTRY_BYTES, MAX_REMEMBERED_DROPS, MAX_TOTAL_BYTES, MAX_TRACKED_VARIANTS,
    MAX_VARIANT_BYTES, DropReason, HistoryDirection, HistoryStatus, UndoBook, limits, ops_size, parse_history_request,
    pins_of, reason_text,
)

PID = "pst_" + "a" * 32


def key(n: int = 1):
    return (PID, "psv_%032x" % n)


def counter():
    state = {"n": 0}

    def next_id():
        state["n"] += 1
        return "psh_%012x" % state["n"]

    return next_id


def pad_op(size: int) -> dict:
    """Une operation inverse dont la taille JSON est exactement `size` octets une fois dans une liste."""

    base = ops_size([{"op": "scene.rename", "scene_id": "pss_000000000001", "title": ""}])
    return {"op": "scene.rename", "scene_id": "pss_000000000001", "title": "x" * (size - base)}


def entry(book: UndoBook, size: int = 100, *, revision: int = 2, ops=None):
    return book.make_entry(ops or [pad_op(size)], op_names=["scene.rename"], tier="structure", actor="user", revision=revision)


def record(book: UndoBook, k, size=100, *, before=None, after=None, n=[0]):
    n[0] += 1
    ring = book.ring(k)
    chained = ring.expected_digest if ring is not None else "start"
    return book.record_edit(k, entry(book, size, revision=n[0]), before_digest=before or chained, after_digest=after or f"d{n[0]}")


def test_the_bounds_are_the_documented_ones_and_consistent():
    assert limits() == {"entries_per_variant": 32, "bytes_per_entry": 64 * 1024, "bytes_per_variant": 256 * 1024,
                        "bytes_total": 1024 * 1024, "tracked_variants": 8}
    assert MAX_ENTRY_BYTES <= MAX_VARIANT_BYTES < MAX_TOTAL_BYTES
    assert MAX_TRACKED_VARIANTS * MAX_VARIANT_BYTES > MAX_TOTAL_BYTES  # the total bound is reachable, so it is tested below


def test_the_entry_count_is_bounded_and_the_oldest_cedes_visibly():
    book = UndoBook(new_id=counter())
    drops = []
    for i in range(MAX_ENTRIES_PER_VARIANT + 5):
        drops += record(book, key(), 100, before=f"d{i}", after=f"d{i + 1}")
    ring = book.ring(key())
    assert len(ring.undo) == MAX_ENTRIES_PER_VARIANT and ring.evicted == 5 and book.evicted_entries == 5
    assert [d.reason for d in drops] == [DropReason.VARIANT_BOUND] * 5 and all(d.kind == "entries" and d.entries == 1 for d in drops)
    assert ring.undo[0].entry_id == "psh_%012x" % 6  # entries 1..5 went, the newest 32 remain, oldest first
    assert book.describe(key())["evicted"] == 5 and book.stats()["evicted_entries"] == 5


def test_the_bytes_of_a_variant_are_bounded():
    book = UndoBook(new_id=counter())
    per = MAX_ENTRY_BYTES - 10
    drops = []
    for i in range(6):
        drops += record(book, key(), per, before=f"d{i}", after=f"d{i + 1}")
    ring = book.ring(key())
    assert ring.size <= MAX_VARIANT_BYTES and len(ring.undo) == MAX_VARIANT_BYTES // per
    assert ring.evicted == 6 - len(ring.undo) and any(d.reason is DropReason.VARIANT_BOUND and d.bytes for d in drops)


def test_an_entry_over_the_entry_bound_is_not_kept_and_the_ring_is_dropped_not_left_with_a_hole():
    book = UndoBook(new_id=counter())
    record(book, key(), 100)
    record(book, key(), 100)
    assert entry(book, MAX_ENTRY_BYTES + 1) is None and entry(book, MAX_ENTRY_BYTES) is not None
    drops = book.record_edit(key(), None, before_digest=book.ring(key()).expected_digest, after_digest="d3")
    assert [(d.kind, d.reason, d.entries) for d in drops] == [("ring", DropReason.ENTRY_TOO_LARGE, 2)]
    assert book.ring(key()) is None and book.why_unavailable(key()) is DropReason.ENTRY_TOO_LARGE
    assert book.describe(key())["tracked"] is False and "too large" in book.describe(key())["message"]
    # the very first edit being too large leaves a reason too (there was no ring to drop)
    fresh = UndoBook()
    assert fresh.record_edit(key(2), None, before_digest="a", after_digest="b") == []
    assert fresh.why_unavailable(key(2)) is DropReason.ENTRY_TOO_LARGE


def test_the_total_bytes_are_bounded_by_dropping_the_least_recently_used_ring():
    book = UndoBook(new_id=counter())
    per = MAX_ENTRY_BYTES - 10
    drops = []
    for variant in range(1, 7):
        for i in range(MAX_VARIANT_BYTES // per):  # each ring at its own byte bound
            drops += record(book, key(variant), per, before=f"v{variant}d{i}", after=f"v{variant}d{i + 1}")
    assert book.total_bytes <= MAX_TOTAL_BYTES
    dropped = [d for d in drops if d.reason is DropReason.MEMORY_BOUND]
    assert dropped and all(d.kind == "ring" for d in dropped)
    assert book.ring(key(1)) is None and book.why_unavailable(key(1)) is DropReason.MEMORY_BOUND  # the oldest went first
    assert book.ring(key(6)) is not None  # the one being written never does
    assert book.dropped_rings == len(dropped)


def test_only_a_few_variants_are_tracked_and_the_least_recently_used_goes():
    book = UndoBook(new_id=counter())
    for variant in range(1, MAX_TRACKED_VARIANTS + 1):
        record(book, key(variant), 50)
    first = book.ring(key(1))
    book.record_edit(key(1), entry(book, 50), before_digest=first.expected_digest, after_digest="touch")  # variant 1 is now the freshest
    drops = record(book, key(99), 50)
    assert [d.reason for d in drops] == [DropReason.TRACKED_VARIANTS_BOUND] and drops[0].key == key(2)
    assert book.ring(key(1)) is not None and book.ring(key(2)) is None
    assert book.stats()["tracked_variants"] == MAX_TRACKED_VARIANTS


def test_a_new_edit_clears_redo_and_says_so():
    book = UndoBook(new_id=counter())
    record(book, key(), before="d0", after="d1")
    record(book, key(), before="d1", after="d2")
    top = book.ring(key()).undo[-1]
    inverse = entry(book, 80)
    book.record_step(key(), HistoryDirection.UNDO, top.entry_id, inverse, after_digest="d1")
    ring = book.ring(key())
    assert len(ring.undo) == 1 and len(ring.redo) == 1 and ring.expected_digest == "d1"
    drops = book.record_edit(key(), entry(book, 60), before_digest="d1", after_digest="d3")
    assert ring.redo == [] and ring.redo_cleared == 1 and len(ring.undo) == 2
    assert [(d.kind, d.reason) for d in drops] == [("redo", DropReason.REDO_CLEARED)]
    assert book.evicted_entries == 0  # clearing the redo branch is semantics, not eviction


def test_undo_moves_the_entry_to_redo_and_back_keeping_the_count():
    book = UndoBook(new_id=counter())
    for i in range(3):
        record(book, key(), before=f"d{i}", after=f"d{i + 1}")
    ring = book.ring(key())
    for step in range(3):
        top = ring.undo[-1]
        book.record_step(key(), HistoryDirection.UNDO, top.entry_id, entry(book, 70), after_digest=f"u{step}")
    assert (len(ring.undo), len(ring.redo)) == (0, 3)
    for step in range(3):
        top = ring.redo[-1]
        book.record_step(key(), HistoryDirection.REDO, top.entry_id, entry(book, 70), after_digest=f"r{step}")
    assert (len(ring.undo), len(ring.redo)) == (3, 0) and ring.evicted == 0


def test_a_step_names_the_head_of_its_stack_or_it_is_refused():
    book = UndoBook(new_id=counter())
    record(book, key())
    with pytest.raises(LookupError):
        book.record_step(key(), HistoryDirection.UNDO, "psh_" + "f" * 12, entry(book), after_digest="x")
    with pytest.raises(LookupError):
        book.record_step(key(), HistoryDirection.REDO, book.ring(key()).undo[-1].entry_id, entry(book), after_digest="x")
    with pytest.raises(LookupError):
        book.record_step(key(9), HistoryDirection.UNDO, "psh_" + "0" * 12, entry(book), after_digest="x")


def test_a_step_whose_inverse_is_too_large_clears_the_opposite_stack_and_says_so():
    book = UndoBook(new_id=counter())
    for i in range(3):
        record(book, key(), before=f"d{i}", after=f"d{i + 1}")
    ring = book.ring(key())
    book.record_step(key(), HistoryDirection.UNDO, ring.undo[-1].entry_id, entry(book), after_digest="u1")
    assert len(ring.redo) == 1
    drops = book.record_step(key(), HistoryDirection.UNDO, ring.undo[-1].entry_id, None, after_digest="u2")
    assert [(d.kind, d.reason, d.entries) for d in drops] == [("entries", DropReason.ENTRY_TOO_LARGE, 1)]
    assert ring.redo == [] and len(ring.undo) == 1 and ring.expected_digest == "u2"


def test_a_document_that_moved_on_drops_the_ring_at_the_next_edit():
    book = UndoBook(new_id=counter())
    record(book, key(), before="d0", after="d1")
    drops = book.record_edit(key(), entry(book), before_digest="someone-else-wrote", after_digest="d9")
    assert [d.reason for d in drops] == [DropReason.DOCUMENT_MOVED_ON] and drops[0].kind == "ring"
    ring = book.ring(key())
    assert len(ring.undo) == 1 and ring.expected_digest == "d9"  # a fresh ring: only the new edit is undoable


def test_dropping_a_variant_or_a_presentation_is_explicit_and_remembered():
    book = UndoBook(new_id=counter())
    record(book, key(1))
    record(book, key(2))
    other = ("pst_" + "b" * 32, "psv_" + "1" * 32)
    book.record_edit(other, entry(book), before_digest="a", after_digest="b")
    assert book.drop(key(1), DropReason.VARIANT_ARCHIVED).kind == "ring" and book.drop(key(1), DropReason.VARIANT_ARCHIVED) is None
    assert book.why_unavailable(key(1)) is DropReason.VARIANT_ARCHIVED
    gone = book.drop_presentation(PID, DropReason.PRESENTATION_REMOVED)
    assert [d.key for d in gone] == [key(2)] and book.ring(other) is not None
    assert book.why_unavailable(key(2)) is DropReason.PRESENTATION_REMOVED


def test_the_remembered_reasons_are_themselves_bounded():
    book = UndoBook()
    for variant in range(MAX_REMEMBERED_DROPS + 10):
        book.record_edit(key(variant), None, before_digest="a", after_digest="b")
    assert book.why_unavailable(key(0)) is DropReason.NOT_RECORDED  # forgotten: the honest default
    assert book.why_unavailable(key(MAX_REMEMBERED_DROPS + 9)) is DropReason.ENTRY_TOO_LARGE


def test_an_unknown_variant_says_it_is_not_recorded_since_start():
    book = UndoBook()
    state = book.describe(key(7))
    assert state["tracked"] is False and state["reason"] == "not_recorded_since_start"
    assert "since Core started" in state["message"] and state["undo_count"] == state["redo_count"] == 0


def test_pins_come_from_scene_add_inverses_only_and_reservations_count_until_released():
    add = {"op": "scene.add", "scene": {"scene_id": "pss_000000000001", "prefab": {"id": "lab.counter", "version": 3}}, "index": 0}
    other = {"op": "scene.add", "scene": {"scene_id": "pss_000000000002", "prefab": {"id": "lab.other", "version": 1}}}
    restore = {"op": "scene.restore_values", "scene_id": "pss_000000000001", "props": {}, "data": {}}
    assert pins_of([restore, add, other]) == {("lab.counter", 3), ("lab.other", 1)}
    assert pins_of([restore]) == frozenset() and pins_of([{"op": "scene.add", "scene": {"prefab": "x"}}]) == frozenset()
    book = UndoBook(new_id=counter())
    token = book.reserve(pins_of([add]))
    assert book.pins() == {("lab.counter", 3)}  # held before any entry exists
    kept = book.make_entry([add], op_names=["scene.remove"], tier="structure", actor="user", revision=2)
    book.record_edit(key(), kept, before_digest="a", after_digest="b")
    book.release(token)
    assert book.pins() == {("lab.counter", 3)}  # now held by the entry itself
    book.drop(key(), DropReason.VARIANT_ARCHIVED)
    assert book.pins() == frozenset()


def test_a_dropped_or_evicted_entry_releases_its_pin():
    add = {"op": "scene.add", "scene": {"scene_id": "pss_000000000001", "prefab": {"id": "lab.counter", "version": 3}}}
    book = UndoBook(new_id=counter())
    book.record_edit(key(), book.make_entry([add], op_names=["scene.remove"], tier="structure", actor="user", revision=2),
                     before_digest="a", after_digest="b")
    for i in range(MAX_ENTRIES_PER_VARIANT):
        book.record_edit(key(), entry(book, 60), before_digest=book.ring(key()).expected_digest, after_digest=f"n{i}")
    assert book.pins() == frozenset()  # the oldest entry (the one holding the pin) was evicted


def test_the_request_parser_is_closed():
    assert parse_history_request({"actor": "user"}).expected_entry_id is None
    assert parse_history_request({"actor": "brain", "expected_entry_id": "psh_" + "a" * 12}).expected_entry_id == "psh_aaaaaaaaaaaa"
    for bad in ({}, {"actor": "root"}, {"actor": "user", "extra": 1}, {"actor": "user", "expected_entry_id": "x"},
                {"actor": "user", "expected_entry_id": 5}, {"actor": "user", "expected_entry_id": "psh_" + "A" * 12},
                {"actor": "user", "expected_entry_id": "psh_" + "a" * 12 + "\n"}, [], None):
        with pytest.raises(PresentationStudioError) as caught:
            parse_history_request(bad)
        assert caught.value.code is C.INVALID_PRESENTATION, bad


def test_every_non_applied_status_has_a_typed_code_and_every_reason_a_sentence():
    assert {s for s in HistoryStatus if s not in (HistoryStatus.APPLIED, HistoryStatus.REFUSED)} == set(HISTORY_CODE)
    for reason in DropReason:
        assert reason_text(reason) and "{" not in reason_text(reason), reason
    assert reason_text("not_a_reason") == "not_a_reason"


@pytest.mark.parametrize("seed", range(5))
def test_random_sequences_never_break_a_hard_bound(seed):
    """Property: whatever the mix of edits, undos, redos, oversize inverses and drops, every bound holds after every step
    and every loss is reported (the counters equal the sum of the reported drops)."""

    rng = random.Random(seed)
    book = UndoBook(new_id=counter())
    reported = 0
    digests = {}
    for step in range(600):
        k = key(rng.randrange(1, 14))
        ring = book.ring(k)
        roll = rng.random()
        size = rng.choice([10, 500, 5_000, 40_000, MAX_ENTRY_BYTES - 10, MAX_ENTRY_BYTES - 10])
        digest = digests.get(k)
        if roll < 0.6 or ring is None:
            e = book.make_entry([pad_op(size)], op_names=["scene.rename"], tier="structure", actor="user", revision=step)
            drops = book.record_edit(k, e, before_digest=digest or "x", after_digest=f"{step}")
            digests[k] = f"{step}"
        elif roll < 0.8 and ring.undo:
            e = book.make_entry([pad_op(size)], op_names=["scene.rename"], tier="structure", actor="user", revision=step)
            drops = book.record_step(k, HistoryDirection.UNDO, ring.undo[-1].entry_id, e, after_digest=f"{step}")
            digests[k] = f"{step}"
        elif roll < 0.95 and ring.redo:
            e = book.make_entry([pad_op(size)], op_names=["scene.rename"], tier="structure", actor="user", revision=step)
            drops = book.record_step(k, HistoryDirection.REDO, ring.redo[-1].entry_id, e, after_digest=f"{step}")
            digests[k] = f"{step}"
        else:
            d = book.drop(k, DropReason.VARIANT_ARCHIVED)
            drops = [d] if d else []
        reported += sum(d.entries for d in drops if d.reason is not DropReason.REDO_CLEARED)
        assert len(book._rings) <= MAX_TRACKED_VARIANTS and book.total_bytes <= MAX_TOTAL_BYTES
        for ring in book._rings.values():
            assert ring.count <= MAX_ENTRIES_PER_VARIANT and ring.size <= MAX_VARIANT_BYTES
            assert all(e.size <= MAX_ENTRY_BYTES for e in (*ring.undo, *ring.redo))
    assert book.evicted_entries == reported

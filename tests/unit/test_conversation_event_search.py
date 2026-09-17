"""Bounded search over safe Conversation Event fields (Slice 06).

Contract: `docs/conversation-events.md`, "Search". Domain matching and snippets,
then the SQLite store scan (newest first, cursor, limits, budget, visibility,
unreadable rows, planted secrets).
"""

from __future__ import annotations

import json

import pytest

import jarvis.adapters.sqlite_conversation_events as adapter
from jarvis.domain.conversation_event_search import (
    MAX_QUERY_CHARS, SEARCH_ATTRIBUTE_KEYS, SearchQuery, decode_search_page, encode_search_page, fold, match_payload,
    search_query, searchable_fields,
)
from jarvis.domain.conversation_events import ConversationEventType as T, ConversationVisibility, encode_conversation_event
from tests.fakes.conversation_events import RecordingDiagnostics, make_event, open_store

VOICE = "voice.speech_scheduler"


# ------------------------------------------------------------------ domain

@pytest.mark.parametrize(("text", "folded"), [("Élan", "elan"), ("CŒUR", "coeur"), ("Ça  va\tbien", "ca va bien"),
                                              ("été", "ete"), ("Straße", "strasse"), ("ÆON", "aeon")])
def test_fold_is_case_and_accent_insensitive(text, folded):
    assert fold(text) == folded


def test_query_parsing_names_rules_never_values():
    secret = "sk-PLANTED-SECRET"
    for raw in ("", "   ", secret * 20, "a\x00b", "a " * 9 + "b c d e f g h i"):
        with pytest.raises(ValueError) as caught:
            SearchQuery.parse(raw)
        assert secret not in str(caught.value)
    assert SearchQuery.parse("  Réunion   réunion Paris ").terms == ("reunion", "paris")
    with pytest.raises(ValueError, match="q is required"):
        search_query({})
    with pytest.raises(ValueError, match="limit"):
        search_query({"q": "x", "limit": "51"})
    assert len("é" * MAX_QUERY_CHARS) == MAX_QUERY_CHARS and SearchQuery.parse("é" * MAX_QUERY_CHARS)


def payload(event):
    return encode_conversation_event(event)


def test_content_is_searched_only_on_public_events():
    public = make_event(T.USER_TRANSCRIPT_ACCEPTED, "u", content="Réserve la salle de réunion.")
    diagnostic = make_event(T.BRAIN_SPEECH_REQUESTED, "r", content="Réserve la salle de réunion.")
    query = SearchQuery.parse("REUNION salle")
    assert match_payload(query, payload(public)).fields == ("content",)
    assert match_payload(query, payload(diagnostic)) is None
    assert "content" not in dict(searchable_fields(payload(diagnostic)))


def test_metadata_ids_types_and_status_codes_are_searchable_other_attributes_are_not():
    failure = make_event(T.BRAIN_TURN_FAILED, "c9", correlation_id="corr-crash",
                         attributes={"code": "brain_backend_exception", "error_class": "ConnectionResetError"})
    tool = make_event(T.TOOL_CALL_STARTED, "call-1", producer="voice.realtime_audio", correlation_id=None,
                      attributes={"tool_name": "secret_tool_name", "arguments_redacted": True})
    assert match_payload(SearchQuery.parse("corr-crash"), payload(failure)).fields == ("correlation_id",)
    assert match_payload(SearchQuery.parse("backend_exception"), payload(failure)).fields == ("attributes.code",)
    assert match_payload(SearchQuery.parse("turn.failed"), payload(failure)).fields == ("event_type",)
    assert match_payload(SearchQuery.parse("secret_tool_name"), payload(tool)) is None
    assert match_payload(SearchQuery.parse("voice.realtime_audio"), payload(tool)) is None  # producer: not searched
    assert set(SEARCH_ATTRIBUTE_KEYS) == {"status", "code", "reason", "error_class"}


def test_short_terms_match_ids_only_when_they_are_the_whole_id():
    event = make_event(T.USER_TRANSCRIPT_ACCEPTED, "u", correlation_id="L17", content="Question numéro 57")
    # hex event ids contain short numbers: they must not make every event a hit
    assert match_payload(SearchQuery.parse("17"), payload(event)) is None
    assert match_payload(SearchQuery.parse("l17"), payload(event)).fields == ("correlation_id",)
    assert match_payload(SearchQuery.parse(event.event_id[4:14]), payload(event)).fields == ("event_id",)
    assert match_payload(SearchQuery.parse("57"), payload(event)).fields == ("content",)


def test_every_term_must_match_somewhere_in_the_same_event():
    event = make_event(T.USER_TRANSCRIPT_ACCEPTED, "u", correlation_id="corr-lundi", content="Le vol de Paul.")
    assert match_payload(SearchQuery.parse("paul corr-lundi"), payload(event)).fields == ("content", "correlation_id")
    assert match_payload(SearchQuery.parse("paul corr-mardi"), payload(event)) is None


def test_page_codec_round_trips_and_rejects_out_of_contract_answers():
    from jarvis.domain.conversation_event_search import ConversationEventSearchPage, build_hit
    from jarvis.domain.conversation_event_store import StoredConversationEvent

    event = make_event(T.USER_TRANSCRIPT_ACCEPTED, "u", content="Un 😀 émoji puis réunion.")
    query = SearchQuery.parse("reunion")
    hit = build_hit(query, StoredConversationEvent(7, event.occurred_at, event), match_payload(query, payload(event)))
    assert hit.snippet == "Un 😀 émoji puis réunion."
    start, end = hit.marks[0]
    assert hit.snippet[start:end] == "réunion"  # code points, astral character counted once
    page = ConversationEventSearchPage((hit,), 7, True, 0, 12, False)
    wire = json.loads(json.dumps(encode_search_page(page)))
    assert decode_search_page(wire) == page
    for broken in ({**wire, "extra": 1}, {**wire, "hits": [{**wire["hits"][0], "marks": [[1]]}]},
                   {**wire, "hits": wire["hits"] * 2}):
        with pytest.raises(ValueError):
            decode_search_page(broken)


# ------------------------------------------------------------------ store scan

async def seeded(tmp_path, events, **kwargs):
    state, store = await open_store(tmp_path / "state.sqlite3", **kwargs)
    for start in range(0, len(events), 32):
        await store.append_many(events[start:start + 32])
    return state, store


def spoken(index: int, text: str, conversation_id: str = "conv-a"):
    return make_event(T.USER_TRANSCRIPT_ACCEPTED, f"u{index}", conversation_id=conversation_id, ms=index,
                      producer="core.voice_admission", content=text)


async def test_hits_come_newest_first_and_the_cursor_pages_without_gaps_or_repeats(tmp_path):
    events = [spoken(i, f"Réunion numéro {i}" if i % 3 == 0 else f"Autre sujet {i}") for i in range(60)]
    state, store = await seeded(tmp_path, events)
    try:
        query = SearchQuery.parse("reunion")
        seen, cursor, pages = [], None, 0
        while True:
            page = await store.search_events(query, before_sequence=cursor, limit=7)
            pages += 1
            seen += [hit.sequence for hit in page.hits]
            cursor = page.next_cursor
            if not page.has_more:
                break
        assert seen == sorted(seen, reverse=True) and len(seen) == len(set(seen)) == 20 and pages == 3
        first = await store.search_events(query, limit=1)
        assert first.hits[0].snippet == "Réunion numéro 57" and first.hits[0].marks == ((0, 7),)
        assert first.next_cursor == first.hits[0].sequence and first.has_more and not first.scan_limited
    finally:
        await state.close()


async def test_conversation_and_visibility_filters(tmp_path):
    events = [spoken(1, "Budget du projet", "conv-a"), spoken(2, "Budget du voyage", "conv-b"),
              make_event(T.BRAIN_WORK_STARTED, "w", conversation_id="conv-a", ms=3, content="budget interne",
                         attributes={"status": "budget_open"})]
    state, store = await seeded(tmp_path, events)
    try:
        query = SearchQuery.parse("budget")
        everything = await store.search_events(query)
        assert [(h.conversation_id, h.event_type) for h in everything.hits] == [
            ("conv-a", "brain.work.started"), ("conv-b", "user.transcript.accepted"),
            ("conv-a", "user.transcript.accepted")]
        assert everything.hits[0].matched == ("attributes.status",)  # its diagnostic content is not what matched
        assert "interne" not in everything.hits[0].snippet
        only_a = await store.search_events(query, conversation_id="conv-a", visibility=ConversationVisibility.PUBLIC)
        assert [h.snippet for h in only_a.hits] == ["Budget du projet"]
    finally:
        await state.close()


async def test_the_scan_budget_stops_a_request_and_the_cursor_continues(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "SEARCH_SCAN_CHUNK", 10)
    events = [spoken(i, "rien" if i else "Le mot cherché") for i in range(45)]
    state, store = await seeded(tmp_path, events)
    reads = []
    original = state.run_serialized

    async def counting(fn):
        reads.append(fn)
        return await original(fn)

    monkeypatch.setattr(state, "run_serialized", counting)
    try:
        query = SearchQuery.parse("cherche")
        page = await store.search_events(query, max_scan_rows=25)
        assert (page.hits, page.scanned_rows, page.has_more, page.scan_limited) == ((), 25, True, True)
        assert len(reads) == 3  # chunks of 10, 10, 5: the lock is taken per chunk, never for the whole scan
        rest = await store.search_events(query, before_sequence=page.next_cursor, max_scan_rows=25)
        assert [h.snippet for h in rest.hits] == ["Le mot cherché"] and not rest.has_more and not rest.scan_limited
    finally:
        await state.close()


async def test_unreadable_rows_are_never_returned_and_are_counted(tmp_path):
    diagnostics = RecordingDiagnostics()
    events = [spoken(1, "Alpha visible"), spoken(2, "Alpha abîmé"), spoken(3, "Alpha illisible")]
    state, store = await seeded(tmp_path, events, diagnostics=diagnostics)
    try:
        def damage(conn):
            row = conn.execute("SELECT data FROM conversation_events WHERE sequence=2").fetchone()
            doctored = json.loads(row[0])
            doctored["attributes"] = {"prompt": "PLANTED alpha prompt"}  # a forbidden key the codec refuses
            conn.execute("UPDATE conversation_events SET data=? WHERE sequence=2", (json.dumps(doctored),))
            conn.execute("UPDATE conversation_events SET data='{alpha not json' WHERE sequence=3")
            conn.commit()

        await state.run_serialized(damage)
        page = await store.search_events(SearchQuery.parse("alpha"))
        assert [h.snippet for h in page.hits] == ["Alpha visible"] and page.skipped_rows == 2
        assert "core.conversation_events.row_unreadable" in diagnostics.kinds()
        assert "PLANTED" not in json.dumps(encode_search_page(page), ensure_ascii=False)
    finally:
        await state.close()


async def test_a_hit_that_does_not_decode_never_hides_the_rows_after_it(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "SEARCH_SCAN_CHUNK", 10)
    events = [spoken(i, f"Delta {i}") for i in range(1, 6)]
    state, store = await seeded(tmp_path, events)
    try:
        def damage(conn):  # the newest hit keeps valid JSON (it matches) but no longer decodes
            row = conn.execute("SELECT data FROM conversation_events WHERE sequence=5").fetchone()
            doctored = json.loads(row[0])
            doctored["attributes"] = {"prompt": "x"}
            conn.execute("UPDATE conversation_events SET data=? WHERE sequence=5", (json.dumps(doctored),))
            conn.commit()

        await state.run_serialized(damage)
        page = await store.search_events(SearchQuery.parse("delta"), limit=1)
        assert [h.snippet for h in page.hits] == ["Delta 4"] and page.skipped_rows == 1
        rest = await store.search_events(SearchQuery.parse("delta"), before_sequence=page.next_cursor, limit=10)
        assert [h.snippet for h in rest.hits] == ["Delta 3", "Delta 2", "Delta 1"]
    finally:
        await state.close()


async def test_planted_private_values_are_never_found(tmp_path):
    secret = "zqxplanted"
    events = [
        make_event(T.SUBAGENT_STARTED, "t", correlation_id=None, content=f"description {secret}",
                   attributes={"model": f"model-{secret}", "subagent_type": secret}),
        make_event(T.BRAIN_SPEECH_REQUESTED, "r", ms=1, content=f"requested {secret}"),
        make_event(T.TOOL_CALL_FINISHED, "call", ms=2, producer="voice.realtime_audio", correlation_id=None,
                   attributes={"tool_name": secret, "arguments_redacted": True}),
        make_event(T.MOUTH_SPEECH_SUPERSEDED, "s", ms=3, producer=VOICE, content=f"never said {secret}"),
        spoken(4, "Texte public sans rien de privé"),
    ]
    state, store = await seeded(tmp_path, events)
    try:
        page = await store.search_events(SearchQuery.parse(secret))
        assert page.hits == () and not page.has_more and page.scanned_rows == 5
    finally:
        await state.close()


async def test_invalid_arguments_are_caller_errors(tmp_path):
    state, store = await open_store(tmp_path / "state.sqlite3")
    try:
        for kwargs in ({"limit": 0}, {"limit": 51}, {"max_scan_rows": 0}, {"before_sequence": -1},
                       {"conversation_id": " padded "}):
            with pytest.raises(ValueError):
                await store.search_events(SearchQuery.parse("x"), **kwargs)
        with pytest.raises(ValueError):
            await store.search_events("x")  # type: ignore[arg-type]
        empty = await store.search_events(SearchQuery.parse("x"))
        assert (empty.hits, empty.next_cursor, empty.has_more, empty.scanned_rows) == ((), None, False, 0)
    finally:
        await state.close()



# ------------------------------------------------------------ Slice 06 rework

def test_typographic_apostrophes_fold_to_the_ascii_one():
    event = make_event(T.USER_TRANSCRIPT_ACCEPTED, "u", content="Réserve l’hôtel d‘Anna, c\u02bcest urgent.")
    for query in ("l'hotel", "l’HÔTEL", "d'anna", "c'est"):
        assert match_payload(SearchQuery.parse(query), payload(event)).fields == ("content",), query


def test_event_type_and_actor_match_whole_dotted_tokens_only():
    accepted = payload(make_event(T.BRAIN_TURN_ACCEPTED, "c"))
    interrupted = payload(make_event(T.MOUTH_SPEECH_INTERRUPTED, "s", producer=VOICE, attributes={"played_ms": 1}))
    assert match_payload(SearchQuery.parse("re"), accepted) is None
    assert match_payload(SearchQuery.parse("accept"), accepted) is None
    assert match_payload(SearchQuery.parse("accepted"), accepted).fields == ("event_type",)
    assert match_payload(SearchQuery.parse("brain"), accepted).fields == ("event_type", "actor")
    assert match_payload(SearchQuery.parse("speech.interrupted"), interrupted).fields == ("event_type",)
    assert match_payload(SearchQuery.parse("speech.inter"), interrupted) is None


def test_fast_fold_equals_the_reference_definition():
    import random
    import unicodedata

    from jarvis.domain.conversation_event_search import _SPECIAL, fold_text

    def reference(text):
        decomposed = unicodedata.normalize("NFKD", text.translate(str.maketrans(_SPECIAL)))
        return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold()

    rng = random.Random(6)
    pool = [chr(code) for code in (*range(0x20, 0x600), *range(0x1AB0, 0x1B00), *range(0x1DC0, 0x1E00),
                                    *range(0x2000, 0x2100), *range(0xFE20, 0xFE30), *range(0x1D165, 0x1D170))]
    for _ in range(4000):
        text = "".join(rng.choice(pool) for _ in range(rng.randint(1, 12)))
        assert fold_text(text) == reference(text), [hex(ord(c)) for c in text]


async def test_a_search_yields_to_the_event_loop_while_it_matches(tmp_path, monkeypatch):
    import asyncio

    monkeypatch.setattr(adapter, "SEARCH_SLICE_S", 0.0)  # yield at every slice check (every 8 rows)
    monkeypatch.setattr(adapter, "SEARCH_SCAN_CHUNK", 600)  # one chunk: only matching can interleave
    events = [spoken(i, f"Texte public numéro {i}") for i in range(600)]
    state, store = await seeded(tmp_path, events)
    ticks = 0
    stop = asyncio.Event()
    seen_by_matcher: list[int] = []
    original_match = adapter.match_payload

    def observing_match(query, payload):
        seen_by_matcher.append(ticks)
        return original_match(query, payload)

    monkeypatch.setattr(adapter, "match_payload", observing_match)

    async def ticker():
        nonlocal ticks
        while not stop.is_set():
            ticks += 1
            await asyncio.sleep(0)

    try:
        task = asyncio.create_task(ticker())
        page = await store.search_events(SearchQuery.parse("absent"))
        stop.set()
        await task
        assert page.scanned_rows == 600 and page.hits == () and len(seen_by_matcher) == 600
        # Other tasks ran between slices of matching, not only around store reads.
        assert len(set(seen_by_matcher)) >= 600 // 8 - 1
    finally:
        await state.close()


async def test_a_cancelled_search_stops_at_its_next_yield(tmp_path, monkeypatch):
    import asyncio

    monkeypatch.setattr(adapter, "SEARCH_SCAN_CHUNK", 20)
    events = [spoken(i, "Rien") for i in range(400)]
    state, store = await seeded(tmp_path, events)
    reads = []
    original = state.run_serialized

    async def counting(fn):
        reads.append(fn)
        return await original(fn)

    monkeypatch.setattr(state, "run_serialized", counting)
    try:
        task = asyncio.create_task(store.search_events(SearchQuery.parse("absent")))
        while len(reads) < 3:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(reads) < 20  # far from the 20 chunks a full scan reads
    finally:
        await state.close()

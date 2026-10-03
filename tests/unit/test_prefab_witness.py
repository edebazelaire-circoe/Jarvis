"""Témoin de la porte d'édition de base (prefab-foundation, Slice 07) : `jarvis/core/prefab_witness.py`.

Faux lecteur du journal (même interface que `ConversationEventQueryService`) pour
les cas limites ; le chemin réel (vrai Core, vrais Conversation Events) est couvert
par `tests/unit/test_display_mcp_prefabs.py`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from jarvis.core.conversation_event_query import ConversationEventBusyError
from jarvis.core.prefab_witness import (
    BUSY_RETRIES, ConversationUtteranceWitness, normalize_utterance, prefilter_query,
)
from jarvis.domain.conversation_event_search import MAX_QUERY_CHARS, MAX_QUERY_TERMS, match_payload

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


class Diagnostics:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def emit(self, kind, message, *, level="info", data=None):  # noqa: ANN001, ANN201
        self.entries.append({"kind": kind, "message": message, "level": level, "data": data or {}})


class Journal:
    """Faux `ConversationEventQueryService` : `search` filtre comme le vrai (`match_payload`), plus récent d'abord."""

    def __init__(self, events: list[dict], *, busy: int = 0) -> None:
        self.events = events
        self.busy = busy
        self.searches: list = []

    async def search(self, query, *, conversation_id, before_sequence, limit, visibility):  # noqa: ANN001, ANN201
        self.searches.append(query)
        if self.busy:
            self.busy -= 1
            raise ConversationEventBusyError("search_busy", "busy")
        hits = []
        for seq, event in sorted(enumerate(self.events, 1), reverse=True):
            payload = {"content": event["content"], "visibility": event.get("visibility", "public"),
                       "event_type": event.get("type", "user.transcript.accepted"), "actor": event.get("actor", "user")}
            if visibility is not None and payload["visibility"] != visibility.value:
                continue
            if match_payload(query, payload) is not None:
                hits.append(SimpleNamespace(event_id=f"ev{seq}", event_type=payload["event_type"],
                                            actor=payload["actor"], occurred_at=event["at"]))
        return SimpleNamespace(hits=tuple(hits[:limit]), has_more=False, next_cursor=None)

    async def event(self, event_id):  # noqa: ANN001, ANN201
        event = self.events[int(event_id[2:]) - 1]
        return SimpleNamespace(event=SimpleNamespace(content=event["content"]))


def witness(journal: Journal, diagnostics: Diagnostics | None = None) -> ConversationUtteranceWitness:
    return ConversationUtteranceWitness(journal, clock=lambda: NOW, diagnostics=diagnostics, busy_retry_s=0)


def test_normalization_folds_case_accents_and_punctuation_the_same_on_both_sides():
    assert normalize_utterance("  Modifie LE prefab « jarvis.checklist » — en Rouge !! ") == \
        "modifie le prefab jarvis checklist en rouge"
    assert normalize_utterance("l’en-tête, s'il te plaît") == normalize_utterance("L'EN TETE s il te plait")


def test_the_prefilter_keeps_what_search_can_express():
    query = prefilter_query(normalize_utterance(
        "change le prefab de base checklist pour que chaque ligne ait une colonne priorité visible et rouge"))
    assert query is not None and len(query.terms) <= MAX_QUERY_TERMS and len(query.text) <= MAX_QUERY_CHARS
    assert "checklist" in query.terms and "priorite" in query.terms  # les plus longs, donc les plus sélectifs
    assert prefilter_query("") is None


async def test_the_witness_finds_the_exact_words_in_a_recent_user_turn():
    diagnostics = Diagnostics()
    journal = Journal([
        {"content": "Affiche une checklist", "at": NOW - timedelta(minutes=3)},
        {"content": "Ok Jarvis : modifie le prefab de base Checklist, en rouge !", "at": NOW - timedelta(minutes=2)},
    ])
    assert await witness(journal, diagnostics)("modifie le prefab de base checklist en rouge") == "ev2"
    [entry] = diagnostics.entries
    assert entry["kind"] == "core.prefab.witness_lookup" and entry["data"]["found"] is True
    assert "rouge" not in str(entry)  # jamais les mots de l'utilisateur dans le journal


@pytest.mark.parametrize("event", [
    {"content": "modifie le prefab de base checklist en rouge", "at": NOW - timedelta(minutes=31)},  # trop ancien
    {"content": "modifie le prefab de base checklist en rouge", "at": NOW, "type": "brain.message.published",
     "actor": "brain"},  # le cerveau ne témoigne pas pour l'utilisateur
    {"content": "modifie le prefab de base checklist en rouge", "at": NOW, "visibility": "diagnostic"},
    {"content": "rouge en checklist base de prefab le modifie", "at": NOW},  # mêmes mots, pas la même phrase
])
async def test_no_witness_without_the_users_own_recent_words(event):
    assert await witness(Journal([event]))("modifie le prefab de base checklist en rouge") is None


async def test_a_busy_search_is_retried_then_the_failure_reaches_the_gate():
    journal = Journal([{"content": "modifie le prefab de base checklist", "at": NOW}], busy=BUSY_RETRIES)
    assert await witness(journal)("modifie le prefab de base checklist") == "ev1"
    stuck = Journal([], busy=BUSY_RETRIES + 1)
    with pytest.raises(ConversationEventBusyError):
        await witness(stuck)("modifie le prefab de base checklist")

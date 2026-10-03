"""Témoin de la porte d'édition de base des prefabs (handoff jarvis-scene-window-prefab-foundation, Slice 07).

Condition 4 du contrat (`docs/prefabs.md` › *Base-edit gate*) : la demande
citée par le cerveau (`user_request`), normalisée, doit se retrouver telle
quelle dans **un** tour de l'utilisateur consigné dans les Conversation Events
depuis moins de `WITNESS_WINDOW` (30 minutes). Rend l'`event_id` de ce tour,
ou `None`.

Recherche en deux temps, par le seul lecteur du journal
(`ConversationEventQueryService`) :

1. **préfiltre** `search` : `SearchQuery` accepte ≤ `MAX_QUERY_TERMS` (8)
   termes et ≤ `MAX_QUERY_CHARS` (200) caractères, chaque terme cherché
   séparément (pas une phrase). On lui donne les termes les plus longs de la
   demande normalisée (les plus sélectifs), visibilité `public` ; tout tour qui
   contient la demande entière contient ces termes, donc rien n'est manqué ;
2. **vérification** : pour chaque résultat `user.transcript.accepted`, acteur
   `user`, survenu dans la fenêtre, le contenu **entier** est relu
   (`event(event_id)`, l'extrait de recherche est coupé) puis normalisé ; la
   demande normalisée doit en être une sous-chaîne.

Normalisation (`normalize_utterance`) : pliage de la recherche (`fold` :
casse, accents, ligatures, apostrophes typographiques), toute ponctuation ou
symbole remplacé par une espace, espaces regroupées. Même fonction des deux
côtés.

Bornes : `MAX_WITNESS_PAGES` pages de `WITNESS_PAGE_LIMIT` résultats (chaque
page balaie au plus `MAX_SEARCH_SCAN_ROWS` lignes, du plus récent au plus
ancien). Une recherche déjà en cours (`search_busy`) est réessayée
`BUSY_RETRIES` fois ; au-delà, l'exception remonte et la porte refuse
(`witness lookup failed`, tracé par `PrefabService`). Diagnostic
`core.prefab.witness_lookup` : compteurs seulement, jamais les mots de
l'utilisateur.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
import re
from typing import Any

from jarvis.core.conversation_event_query import ConversationEventBusyError, ConversationEventQueryService
from jarvis.domain.conversation_event_search import MAX_QUERY_CHARS, MAX_QUERY_TERMS, SearchQuery, fold
from jarvis.domain.conversation_events import ConversationActor, ConversationEventType, ConversationVisibility
from jarvis.domain.v2 import utc_now
from jarvis.ports.v2 import DiagnosticSink

WITNESS_WINDOW = timedelta(minutes=30)
WITNESS_PAGE_LIMIT = 20
MAX_WITNESS_PAGES = 3
BUSY_RETRIES = 3
BUSY_RETRY_S = 0.2
WITNESS_LOOKUP_KIND = "core.prefab.witness_lookup"

_PUNCTUATION = re.compile(r"[^\w\s]|_", re.UNICODE)
_SPACES = re.compile(r"\s+")


def normalize_utterance(text: str) -> str:
    """Forme comparée : pliée (casse, accents), ponctuation retirée, espaces regroupées."""

    return _SPACES.sub(" ", _PUNCTUATION.sub(" ", fold(text))).strip()


def prefilter_query(normalized: str) -> SearchQuery | None:
    """Les termes les plus longs (≤ 8, ≤ 200 caractères en tout) : ce que `search` sait chercher."""

    terms = sorted(dict.fromkeys(normalized.split(" ")), key=lambda term: (-len(term), term))
    chosen: list[str] = []
    for term in terms:
        if not term or len(chosen) >= MAX_QUERY_TERMS:
            continue
        if len(" ".join([*chosen, term])) > MAX_QUERY_CHARS:
            continue
        chosen.append(term)
    return SearchQuery.parse(" ".join(chosen)) if chosen else None


class ConversationUtteranceWitness:
    """`await witness(user_request) -> event_id | None` (port `UserUtteranceWitness` de `PrefabService`)."""

    def __init__(self, queries: ConversationEventQueryService, *, window: timedelta = WITNESS_WINDOW,
                 clock: Callable[[], datetime] = utc_now, diagnostics: DiagnosticSink | None = None,
                 busy_retry_s: float = BUSY_RETRY_S) -> None:
        self._queries = queries
        self._window = window
        self._clock = clock
        self._diagnostics = diagnostics
        self._busy_retry_s = busy_retry_s

    async def __call__(self, user_request: str) -> str | None:
        wanted = normalize_utterance(user_request)
        query = prefilter_query(wanted)
        if query is None:
            self._trace(found=False, pages=0, hits=0, checked=0, reason="empty_request")
            return None
        since = self._clock() - self._window
        cursor: int | None = None
        hits = checked = 0
        for page_number in range(1, MAX_WITNESS_PAGES + 1):
            page = await self._search(query, cursor)
            hits += len(page.hits)
            for hit in page.hits:
                if hit.event_type != ConversationEventType.USER_TRANSCRIPT_ACCEPTED.value \
                        or hit.actor != ConversationActor.USER.value or hit.occurred_at < since:
                    continue
                stored = await self._queries.event(hit.event_id)
                if stored is None or not stored.event.content:
                    continue
                checked += 1
                if wanted in normalize_utterance(stored.event.content):
                    self._trace(found=True, pages=page_number, hits=hits, checked=checked)
                    return hit.event_id
            if not page.has_more or page.next_cursor is None:
                break
            cursor = page.next_cursor
        self._trace(found=False, pages=page_number, hits=hits, checked=checked, reason="not_found")
        return None

    async def _search(self, query: SearchQuery, cursor: int | None) -> Any:
        for attempt in range(BUSY_RETRIES + 1):
            try:
                return await self._queries.search(query, conversation_id=None, before_sequence=cursor,
                                                  limit=WITNESS_PAGE_LIMIT, visibility=ConversationVisibility.PUBLIC)
            except ConversationEventBusyError:
                if attempt == BUSY_RETRIES:
                    raise
                await asyncio.sleep(self._busy_retry_s)
        raise AssertionError("unreachable")

    def _trace(self, **data: Any) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(WITNESS_LOOKUP_KIND, "Témoin d'édition de base cherché dans les Conversation Events",
                                   level="info", data=data)
        except Exception:  # noqa: BLE001 - silence argumentée : un journal indisponible ne change pas l'issue de la porte
            pass

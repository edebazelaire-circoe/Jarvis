"""Faux `UpstreamFetcher` pour les tests : aucune connexion, archives fournies par le test (Slice 18).

Pas de comportement temporaire : c'est l'adaptateur de test du port, sans date de retrait. Il garde la liste des adresses demandées
(`requests`), ce qui prouve qu'un refus d'origine n'a ouvert AUCUNE connexion.
"""

from __future__ import annotations

from jarvis.domain.remotion_upstream import UpstreamOrigin
from jarvis.ports.upstream_fetcher import FetchedArchive


class FakeUpstreamFetcher:
    def __init__(self, archives: dict[str, bytes] | None = None, *, error: Exception | None = None) -> None:
        self._archives = dict(archives or {})
        self._error = error
        self.requests: list[str] = []

    def add(self, origin: UpstreamOrigin, data: bytes) -> None:
        self._archives[origin.archive_url] = data

    def fetch(self, origin: UpstreamOrigin) -> FetchedArchive:
        self.requests.append(origin.archive_url)
        if self._error is not None:
            raise self._error
        return FetchedArchive(self._archives[origin.archive_url], origin.archive_url)

"""Port : récupérer l'archive d'un modèle amont (Slice 18, `docs/remotion-import.md` §2).

Seul Core appelle ce port. Le code d'une scène (non fiable) n'y touche jamais, et le port n'accepte pas d'adresse libre : il reçoit une
`UpstreamOrigin` déjà validée (liste blanche, commit épinglé) et construit lui-même l'adresse. Adaptateurs : `HttpsUpstreamFetcher`
(réel), `FakeUpstreamFetcher` (tests, aucun réseau).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from jarvis.domain.remotion_upstream import UpstreamOrigin


@dataclass(frozen=True, slots=True)
class FetchedArchive:
    data: bytes
    final_url: str
    redirects: int = 0


class UpstreamFetcher(Protocol):
    def fetch(self, origin: UpstreamOrigin) -> FetchedArchive:
        """Télécharge l'archive `tar.gz` du commit épinglé. BLOQUANT (appelé dans un fil). Lève `UpstreamRefusal`
        (`redirect_refused`, `fetch_failed`, `fetch_timeout`, `fetch_too_large`) ; ne rend jamais une réponse partielle."""

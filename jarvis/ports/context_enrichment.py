"""Port du modèle du worker d'enrichissement de Context (handoff session-context-recording, Slice 08).

Texte en entrée, texte en sortie : **aucun outil, aucun MCP**. L'adaptateur
de production (`jarvis/runtime/context_enrichment_model.py`) lance le CLI
Claude en profil restreint `speculative_analysis` (`--tools ""`,
`--strict-mcp-config`, sans session persistée) ; Core n'en connaît que ce
port. Contrat : `docs/session-context.md` › *Enrichment worker*.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

#: Codes stables d'un appel raté (`EnrichmentModelError.code`).
MODEL_UNAVAILABLE = "enrichment_provider_unavailable"
MODEL_TIMEOUT = "enrichment_model_timeout"
MODEL_FAILED = "enrichment_model_failed"
MODEL_EMPTY = "enrichment_model_empty"


class EnrichmentModelError(RuntimeError):
    """Appel au modèle raté ; `code` stable, `detail` = la cause dite par le fournisseur (bornée)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail[:300]}" if detail else code)
        self.code = code
        self.detail = detail[:300]


@dataclass(frozen=True, slots=True)
class EnrichmentReply:
    text: str
    model: str
    #: Coût rendu par le fournisseur (`total_cost_usd` du CLI) ; `None` s'il ne le dit pas.
    cost_usd: float | None = None
    duration_ms: int | None = None
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EnrichmentImage:
    media_type: str
    data: bytes


class ContextEnrichmentModel(Protocol):
    """Un appel borné, sans outil. Lève `EnrichmentModelError` ; ne rend jamais une réponse vide."""

    #: Nom du modèle demandé (journal, coût).
    model: str
    #: L'adaptateur sait joindre des images (description de captures d'écran).
    supports_images: bool

    async def complete(self, prompt: str, *, timeout_s: float,
                       images: tuple[EnrichmentImage, ...] = ()) -> EnrichmentReply: ...

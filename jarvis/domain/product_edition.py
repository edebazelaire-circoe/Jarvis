"""Édition produit : quels types de Board un JARVIS donné rend disponibles (`docs/product-edition.md`).

Une seule vérité, consommée par Core (`BoardService`, `SessionManager`), le
protocole (`GET /v1/boards/edition`, refus `board_kind_unavailable`), le
serveur MCP `jarvis-workspace` (schéma de `board_create`) et la consigne du
cerveau (`claude_local.board_kind_prompt`). Aucune autre table de disponibilité
ne doit exister : l'interface lit `to_payload()`, elle ne redécide rien.

- `full` (développement, défaut du dépôt) : les trois types, comportement
  historique inchangé (défaut de création `assistant`).
- `presentation` (Presentation Edition V1) : seul `presentation` se crée et
  s'active ; Assistant et Réunion restent dans le code, affichables comme
  « à venir / indisponibles », jamais actionnables. Les Boards hérités de ces
  types sont **conservés intacts** : ni réécrits, ni supprimés, ni activés.

Sélection : variable d'environnement `JARVIS_PRODUCT_EDITION` (`full` |
`presentation`), sinon le défaut fourni par l'appelant (`installed_default` :
le produit installé fixera `presentation`, Slice 02), sinon `full`. Une valeur
illisible est un refus de démarrer (`ConfigurationError`), jamais un repli
silencieux vers `full`, qui rouvrirait les types verrouillés.

Pur : aucune E/S (l'environnement est passé en argument), aucune horloge.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from jarvis.domain.errors import ConfigurationError
from jarvis.domain.interaction_mode import INTERACTION_MODES
from jarvis.domain.workspace_board import BoardError, BoardErrorCode, BoardKind, board_kind_mode

#: Variable qui choisit l'édition. Héritée par les processus enfants (Control Center, serveurs MCP).
PRODUCT_EDITION_ENV = "JARVIS_PRODUCT_EDITION"


class ProductEdition(StrEnum):
    """Édition d'un JARVIS. Valeurs internes, stables, jamais traduites."""

    #: Développement : tout le vocabulaire de Boards, comportement d'avant cette Slice.
    FULL = "full"
    #: Presentation Edition V1 : seuls les Boards Présentation sont disponibles.
    PRESENTATION = "presentation"


class BoardKindAvailability(StrEnum):
    """Ce que l'édition permet d'un type de Board (`docs/product-edition.md` › *Availability*)."""

    #: Se crée et s'active.
    AVAILABLE = "available"
    #: Connu et affichable (« à venir / indisponible »), refusé à la création et à l'activation.
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ProductEditionPolicy:
    """Politique d'une édition : types disponibles et défaut de création."""

    edition: ProductEdition
    available_board_kinds: tuple[BoardKind, ...]
    default_board_kind: BoardKind

    def __post_init__(self) -> None:
        if not self.available_board_kinds or self.default_board_kind not in self.available_board_kinds:
            raise ValueError("an edition needs its default Board kind among its available kinds")

    @property
    def restricts_board_kinds(self) -> bool:
        """Vrai quand un type connu est indisponible (repli de démarrage, schéma MCP réduit)."""

        return len(self.available_board_kinds) < len(BoardKind)

    def availability(self, kind: BoardKind) -> BoardKindAvailability:
        return (BoardKindAvailability.AVAILABLE if BoardKind(kind) in self.available_board_kinds
                else BoardKindAvailability.UNAVAILABLE)

    def allows(self, kind: BoardKind) -> bool:
        return self.availability(kind) is BoardKindAvailability.AVAILABLE

    def ensure_available(self, kind: BoardKind, *, action: str) -> BoardKind:
        """Porte de création (`action="create"`) et d'activation (`"switch"`) ; refus 409 `board_kind_unavailable`."""

        if not self.allows(kind):
            raise BoardError(
                BoardErrorCode.BOARD_KIND_UNAVAILABLE,
                f"board_kind {BoardKind(kind).value!r} is not available in the {self.edition.value} edition "
                f"({action} refused, nothing written); available: {[k.value for k in self.available_board_kinds]}",
            )
        return BoardKind(kind)

    def to_payload(self) -> dict[str, Any]:
        """Données de disponibilité pour l'interface et les diagnostics (`GET /v1/boards/edition`).

        `behavior_status` reprend le statut READY/PLANNED du mode que désigne le
        type (`interaction_mode.INTERACTION_MODES`) : deux axes distincts, un
        type peut être disponible et son comportement encore prévu (Réunion en `full`).
        """

        return {
            "edition": self.edition.value,
            "default_board_kind": self.default_board_kind.value,
            "board_kinds": [
                {"board_kind": kind.value, "availability": self.availability(kind).value,
                 "available": self.allows(kind),
                 "behavior_status": INTERACTION_MODES[board_kind_mode(kind)].status.value}
                for kind in BoardKind
            ],
        }


#: Porte unique vers les politiques.
PRODUCT_EDITIONS: Mapping[ProductEdition, ProductEditionPolicy] = MappingProxyType({
    ProductEdition.FULL: ProductEditionPolicy(
        ProductEdition.FULL, available_board_kinds=tuple(BoardKind), default_board_kind=BoardKind.ASSISTANT),
    ProductEdition.PRESENTATION: ProductEditionPolicy(
        ProductEdition.PRESENTATION, available_board_kinds=(BoardKind.PRESENTATION,),
        default_board_kind=BoardKind.PRESENTATION),
})

FULL_EDITION = PRODUCT_EDITIONS[ProductEdition.FULL]
PRESENTATION_EDITION = PRODUCT_EDITIONS[ProductEdition.PRESENTATION]


def resolve_product_edition(environ: Mapping[str, str], *,
                            installed_default: ProductEdition | None = None) -> ProductEditionPolicy:
    """Politique de l'édition active : `JARVIS_PRODUCT_EDITION`, sinon `installed_default`, sinon `full`.

    Valeur vide = absente. Valeur inconnue : `ConfigurationError` (voir l'en-tête).
    """

    raw = str(environ.get(PRODUCT_EDITION_ENV) or "").strip().casefold()
    if not raw:
        return PRODUCT_EDITIONS[installed_default or ProductEdition.FULL]
    try:
        return PRODUCT_EDITIONS[ProductEdition(raw)]
    except ValueError:
        raise ConfigurationError(
            f"{PRODUCT_EDITION_ENV} doit valoir {[e.value for e in ProductEdition]}, reçu {raw[:40]!r}") from None

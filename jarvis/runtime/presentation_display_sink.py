"""Adaptateur d'affichage direct : l'intention sémantique vers la scène, sans Tool Brain.

Handoff `jarvis-presentation-interaction-mode` (2026-10), Slice 07 (A3, R4).
Réalise `PresentationDisplaySink` (`jarvis/core/presentation_display.py`) en
réutilisant **le** chemin de révélation existant, sans en construire un second :

    reveal_prepared → PresentationSpeculativeService.reveal(resource_id)
                    → LedgeredSceneStager → DisplaySceneStager.reveal
                    → SceneDisplayTools.update_object(visibility="visible")

La voie spéculative reste propriétaire du monteur et réchauffe la ressource au
passage (`use_resource`) ; ce module ne touche ni la scène ni le magasin.

`show_attention` rend un reçu sans rien faire : la carte d'attention a déjà son
chemin (`BackgroundEventLedger.attention_digest` → carte, `bgCue`), et un
second émetteur dessinerait deux fois la même alerte.

`withdraw_speculative` rend 0 : la voie directe n'a **aucune file**, chaque
intention est exécutée à sa publication. Le dire dans la trace plutôt que de
se taire, c'est ce qui permet de distinguer « rien à retirer » de « retrait
jamais appelé ». Le Tool Brain (Slice 08) en fera une vraie annulation.
"""

from __future__ import annotations

from typing import Any

from jarvis.core.presentation_display import DisplayReceipt
from jarvis.domain.presentation_intent import DisplaySemantic, PresentationOutputIntent

__all__ = ["DISPLAY_SINK_KIND", "DirectSceneDisplaySink"]

#: Préfixe des lignes de journal de cet adaptateur.
DISPLAY_SINK_KIND = "presentation.display"


class DirectSceneDisplaySink:
    """`PresentationDisplaySink` réalisé par la voie spéculative et son monteur."""

    __slots__ = ("_speculative", "_journal", "diagnostic_failures")

    def __init__(self, speculative: Any, *, journal: Any | None = None) -> None:
        self._speculative = speculative
        self._journal = journal
        self.diagnostic_failures = 0

    async def publish(self, intent: PresentationOutputIntent) -> DisplayReceipt:
        """Exécuter la moitié visuelle. Une panne de la voie est relevée, pas déguisée."""

        display = getattr(intent, "display", None)
        if display is None:
            return DisplayReceipt(False, "display_nothing_to_show")
        if display.semantic is DisplaySemantic.SHOW_ATTENTION:
            return DisplayReceipt(True, "display_attention_card_path", detail="noop")
        if display.semantic is not DisplaySemantic.REVEAL_PREPARED:
            return DisplayReceipt(False, "display_semantic_unsupported",
                                  detail=str(getattr(display.semantic, "value", ""))[:64])
        for resource_id in display.resource_refs:
            admission = await self._speculative.reveal(resource_id)
            name = str(getattr(admission, "value", admission))[:64]
            if name != "accepted":
                # La première ressource refusée arrête la série : montrer la
                # moitié d'une demande serait un écran que personne n'a voulu.
                return DisplayReceipt(False, "display_reveal_refused", detail=name)
        return DisplayReceipt(True, "display_revealed", detail="accepted")

    def withdraw_speculative(self, reason: str) -> int:
        """Rien n'attend sur la voie directe : 0, et la trace le dit."""

        if self._journal is not None:
            try:
                self._journal.emit(
                    f"{DISPLAY_SINK_KIND}.withdraw_noop",
                    "Voie d'affichage directe : aucune intention en file, rien à retirer",
                    level="info",
                    data={"code": "display_withdraw_nothing_queued",
                          "reason": str(reason)[:64], "withdrawn": 0},
                )
            except Exception:  # noqa: BLE001 - un journal en panne ne casse pas un tour
                self.diagnostic_failures += 1
        return 0

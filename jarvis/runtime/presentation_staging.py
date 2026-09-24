"""Monter un objet de scène masqué pour la préparation spéculative, et le révéler.

Slice 08, moitié runtime. Décision **D12** : l'autorité d'affichage reste à la
scène. Ce module n'est donc **pas** un second chemin vers la scène — c'est un
adaptateur mince au-dessus de `SceneDisplayTools`
(`jarvis/runtime/display_mcp.py`), l'outil que le cerveau emploie déjà.

## Ce qu'il ne fait pas, et pourquoi c'est le sujet

Il ne construit aucune `SceneCommand`, ne choisit aucun `SceneActor`, ne touche
ni épingle, ni géométrie, ni `exec_state`, ni `work_ref`. Tout cela reste jugé
par le réducteur, qui refuse déjà ce qu'il doit refuser
(`ALLOWED_SCENE_OPS`, `PINNED_BY_USER`, `EXECUTION_TRUTH`). Passer à côté de
l'outil aurait été le moyen le plus court de perdre ces refus-là sans que rien
ne le signale.

## Masqué à la naissance, pas masqué juste après

`stage_hidden` crée l'objet avec `visibility="hidden"` dans la **même**
commande. Deux commandes — créer, puis masquer — auraient laissé l'objet
visible entre les deux, sur un écran que quelqu'un regarde. C'est pour cela que
`SceneDisplayTools.create_object` reçoit un paramètre `visibility` dans cette
Slice : le champ existait déjà sur `SceneObjectFields`, seul le chemin d'appel
manquait.

`reveal` emploie `scene_set_visibility`, qui n'est accordé à **aucune**
capacité spéculative : révéler n'est jamais un geste de la préparation
elle-même.
"""

from __future__ import annotations

from typing import Any, Sequence

from jarvis.domain.scene import Visibility
from jarvis.runtime.journal import RuntimeJournal

__all__ = ["DisplaySceneStager", "SceneStagingError"]

#: Nature de l'objet monté. Un artefact est ce que le cerveau crée pour
#: expliquer quelque chose, et une préparation est exactement cela ; `window`
#: aurait promis une fenêtre que personne n'a demandée.
STAGED_KIND = "artifact"

#: Longueur retenue d'un titre ou d'un résumé recopié dans la scène. La scène a
#: ses propres bornes et refuserait au-delà ; couper ici donne un objet plutôt
#: qu'un refus, parce qu'une préparation trop bavarde reste une préparation.
MAX_STAGED_TITLE_CHARS = 120
MAX_STAGED_SUMMARY_CHARS = 280

STAGING_KIND = "presentation.staging"


class SceneStagingError(RuntimeError):
    """Le montage ou la révélation a échoué. Code stable, cause conservée."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DisplaySceneStager:
    """`HiddenSceneStager` réalisé au-dessus de l'outil d'affichage existant."""

    def __init__(self, tools: Any, *, journal: RuntimeJournal | None = None) -> None:
        self._tools = tools
        self._journal = journal
        self._diagnostic_failures = 0

    async def stage_hidden(self, *, category: str, title: str, summary: str) -> str:
        """Créer l'objet masqué et rendre son identifiant.

        Une réponse sans `object_id` est une erreur, pas un succès muet : sans
        identifiant, la ressource rangée pointerait vers rien et la révélation
        échouerait plus tard, loin de sa cause.
        """

        answer = await self._tools.create_object(
            kind=STAGED_KIND,
            category=category or "preparation",
            title=(title or "")[:MAX_STAGED_TITLE_CHARS],
            summary=(summary or "")[:MAX_STAGED_SUMMARY_CHARS],
            visibility=Visibility.HIDDEN.value,
        )
        object_id = answer.get("object_id") if isinstance(answer, dict) else None
        if not isinstance(object_id, str) or not object_id.strip():
            raise SceneStagingError(
                "presentation_stage_no_object_id",
                "la scène a accepté la commande sans rendre d'identifiant d'objet",
            )
        self._emit("staged", {"object_id": object_id, "category": category})
        return object_id

    async def reveal(self, object_id: str) -> None:
        """Rendre l'objet visible. La scène reste juge du reste."""

        if not isinstance(object_id, str) or not object_id.strip():
            raise SceneStagingError("presentation_reveal_invalid_id", "identifiant d'objet invalide")
        await self._tools.set_visibility(object_id=object_id, visibility=Visibility.VISIBLE.value)
        self._emit("revealed", {"object_id": object_id})

    async def discard(self, object_ids: Sequence[str]) -> None:
        """Retirer de la scène les objets montés. D13 : rien ne survit à la séance.

        `scene_archive` est l'opération de retrait de la scène, et elle n'est
        accordée à **aucune** capacité spéculative : seule la voie elle-même
        reprend ce qu'elle a posé, jamais le travail qui l'a demandé.

        Un objet déjà archivé, ou que l'utilisateur a supprimé entre-temps, fait
        répondre la scène sans rien changer ; c'est un succès, pas une panne.
        """

        wanted = [value for value in object_ids if isinstance(value, str) and value.strip()]
        if not wanted:
            return
        await self._tools.archive(object_ids=wanted)
        self._emit("discarded", {"objects": len(wanted)})

    #: Phrase lisible de chaque événement. Une première version passait le nom
    #: de l'événement comme message, donc les lignes n'en portaient aucun.
    _MESSAGES = {
        "staged": "Objet de scène préparé, masqué dès sa création",
        "revealed": "Objet de scène préparé rendu visible",
        "discarded": "Objets de scène préparés retirés de la scène",
    }

    @property
    def diagnostic_failures(self) -> int:
        """Lignes de journal perdues. Comptées, comme dans `OwnedJobExecution`."""

        return self._diagnostic_failures

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        if self._journal is None:
            return
        try:
            self._journal.emit(
                f"{STAGING_KIND}.{event}", self._MESSAGES.get(event, event), level="info", data=data,
            )
        except Exception:  # noqa: BLE001 - un journal en panne ne casse pas le montage qu'il observe
            self._diagnostic_failures += 1

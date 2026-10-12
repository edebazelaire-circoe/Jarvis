"""La surface de lecture vue par le rechargement a chaud (handoff jarvis-interactive-presentation-studio, Slice 06 ;
native-studio-playback-fix Slice 09).

La lecture POSSEDE la surface : depuis la Slice 09 c'est la surface en memoire de Variantes (`RunSurface`,
`presentation_studio_run_surface.py`, id `variants-run-<run_id>`), et non plus une fenetre du Board (`studio-stage-<run_id>`,
retiree). Ce module n'en cree jamais : il garde en memoire **quelle surface affiche quelle scene** (handle d'execution : jamais
persiste, jamais dans un document) et n'ecrit qu'une chose, le **pin** de cette surface :

- `bind` / `unbind` : appeles par le service de lecture (observateur de stage) a chaque affichage d'une scene et a la fin du
  run. Une scene qui n'est pas affichee n'a pas de liaison : sa source est seulement re-epinglee.
- `repin` : change le pin de la surface (le lecteur de Variantes remonte donc **ce** cadre, sous le meme id), compare-and-set sous
  le verrou de la surface : un patch ne s'applique que si la surface porte encore le pin attendu (`stage_changed` sinon).
  Idempotent : une surface qui porte deja le pin cible (la lecture l'a suivi entre-temps) n'est pas reecrite.
- `current` : le bloc vivant.

Le bloc passe par le catalogue des prefabs (`validate_instance`) : une instance invalide pour le nouveau manifeste est refusee
(`prefab_invalid`), jamais montree. Le montage est confirme par la page de Variantes (rapport de montage sous l'id de la surface).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jarvis.core.presentation_studio_run_surface import RunSurface
from jarvis.core.presentation_studio_stage import StageError
from jarvis.domain.prefab import PrefabRef
from jarvis.domain.scene import ScenePrefabRef
from jarvis.ports.v2 import DiagnosticSink


class StagePatchError(Exception):
    """Le stage n'a pas pu etre patche : `code` court (`stage_missing`, `stage_changed`, `prefab_invalid`...), message borne."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message[:300]


@dataclass(frozen=True, slots=True)
class StageBinding:
    presentation_id: str
    variant_id: str
    scene_id: str
    object_id: str
    #: Le run de lecture dont c'est la surface (`variants-run-<run_id>`), pour la trace.
    run_id: str = ""


class StageWindows:
    """Voir l'en-tete du module."""

    def __init__(self, surface: RunSurface, *, diagnostics: DiagnosticSink | None = None) -> None:
        self._surface = surface
        self._diagnostics = diagnostics
        self._bindings: dict[str, StageBinding] = {}

    # ------------------------------------------------------------ liaison

    def bind(self, binding: StageBinding) -> None:
        """Appele par la lecture (Slice 12) quand une scene arrive sur le stage."""

        self._bindings[binding.presentation_id] = binding

    def unbind(self, presentation_id: str) -> None:
        self._bindings.pop(presentation_id, None)

    def binding_for(self, presentation_id: str, variant_id: str, scene_id: str) -> StageBinding | None:
        """La surface qui affiche **cette** scene de **cette** variante en ce moment, sinon `None`."""

        found = self._bindings.get(presentation_id)
        return found if found is not None and (found.variant_id, found.scene_id) == (variant_id, scene_id) else None

    async def locate(self, presentation_id: str, variant_id: str, scene_id: str, pin: PrefabRef) -> StageBinding | None:
        """La surface que la lecture affiche pour **cette** scene, SI elle montre encore ce pin. Sinon `None` : la source est
        seulement re-epinglee. Apres un redemarrage de Core il n'y a plus de liaison (aucune lecture ne survit)."""

        bound = self.binding_for(presentation_id, variant_id, scene_id)
        if bound is None:
            return None
        block = await self.current(bound)
        if block is None or PrefabRef(block.prefab_id, block.version) != pin:
            return None
        return bound

    def bindings(self) -> tuple[StageBinding, ...]:
        return tuple(self._bindings.values())

    # ------------------------------------------------------------ lecture

    async def current(self, binding: StageBinding) -> ScenePrefabRef | None:
        """Le bloc `prefab` vivant de la surface (`None` : ce n'est plus la surface a l'ecran)."""

        return self._surface.current_block(binding.object_id)

    # ------------------------------------------------------------ ecriture

    async def repin(self, binding: StageBinding, *, expect: PrefabRef, to: PrefabRef,
                    props: dict[str, Any], data: dict[str, Any]) -> None:
        """Change le pin de la surface (le lecteur remonte donc **ce** cadre) et pose `props`/`data`, seulement si elle porte
        encore `expect`. `StagePatchError` sinon ou si le catalogue refuse l'instance."""

        try:
            refused = await self._surface.repin(binding.object_id, expect=expect, to=to, props=props, data=data)
        except StageError as exc:  # the catalogue refused the block: refused, not a fault
            raise StagePatchError(exc.code, exc.message) from None
        if refused == "stage_missing":
            raise StagePatchError("stage_missing", "the run surface no longer shows this scene")
        if refused == "stage_changed":
            raise StagePatchError("stage_changed", "the run surface no longer shows the expected version")

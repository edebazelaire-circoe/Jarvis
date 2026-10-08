"""La fenetre « stage » du Studio, vue par le rechargement a chaud (handoff jarvis-interactive-presentation-studio, Slice 06).

R2 / integration map 4.5 : une Presentation affiche la scene courante par **un seul** objet `window` de la scene globale,
patche avec `update_object(prefab=...)` ; un changement de `(id, version)` est le remontage de l'hote (la regle existante),
un changement de `props`/`data` est `host.update`. Ce module est le **seul** endroit de la Slice 06 qui ecrit cet objet :

- `StageWindows` garde en memoire quelle fenetre affiche quelle scene (handle d'execution : jamais persiste, jamais dans
  un document ; `RUNTIME_KEYS`). La Slice 12 (lecture) possede le cycle de vie complet de cette fenetre (creation sur
  la demande de lecture, reprise apres un arret brutal) ; ce module n'en donne que ce que le rechargement et le Human
  check ont besoin : `show` (cree ou re-patche le stage, **provisoire**), `repin` (change le pin, compare-and-set) et
  `current` (le bloc vivant).
- Toute ecriture passe par `SceneService.apply_if` : le plan lit l'etat **sous le verrou de la scene** (docs/07 §4.4), donc
  un evenement d'etat du cadre qui arrive en meme temps n'est jamais perdu et un patch ne s'applique que si la fenetre
  porte encore le pin attendu (`stage_changed` sinon : on n'ecrase jamais l'ecriture d'un autre).
- L'objet a un id **deterministe** par Presentation (`studio-stage-<12 hex>`) : apres un redemarrage de Core, `show`
  retrouve la meme fenetre (un `upsert` idempotent) au lieu d'en laisser une orpheline dans la scene durable.

Les patchs prefab traversent la validation de la scene (`SceneService._check_prefabs`) : une instance invalide pour le
nouveau manifeste est refusee (`prefab_invalid`), jamais ecrite.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from jarvis.core.scene_service import SceneService
from jarvis.domain.prefab import PrefabRef
from jarvis.domain.presentation_studio_reload import source_prefab_id
from jarvis.domain.presentation_studio_scene import StudioScene
from jarvis.domain.scene import (
    Representation, SceneActor, SceneCommand, SceneCommandOutcome, SceneGeometry, SceneObjectFields, SceneObjectKind,
    SceneOp, ScenePayload, ScenePrefabRef, Visibility,
)
from jarvis.ports.v2 import DiagnosticSink

STAGE_CATEGORY = "presentation"
STAGE_OBJECT_PREFIX = "studio-stage-"
DEFAULT_GEOMETRY = SceneGeometry(0, 0, 40, 24)


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


def stage_object_id(presentation_id: str) -> str:
    return STAGE_OBJECT_PREFIX + presentation_id.removeprefix("pst_")[:12]


class StageWindows:
    """Voir l'en-tete du module."""

    def __init__(self, scene: SceneService, *, diagnostics: DiagnosticSink | None = None) -> None:
        self._scene = scene
        self._diagnostics = diagnostics
        self._bindings: dict[str, StageBinding] = {}

    # ------------------------------------------------------------ liaison

    def bind(self, binding: StageBinding) -> None:
        """Appele par la lecture (Slice 12) quand une scene arrive sur le stage."""

        self._bindings[binding.presentation_id] = binding

    def unbind(self, presentation_id: str) -> None:
        self._bindings.pop(presentation_id, None)

    def binding_for(self, presentation_id: str, variant_id: str, scene_id: str) -> StageBinding | None:
        """La fenetre qui affiche **cette** scene de **cette** variante en ce moment, sinon `None`."""

        found = self._bindings.get(presentation_id)
        return found if found is not None and (found.variant_id, found.scene_id) == (variant_id, scene_id) else None

    async def locate(self, presentation_id: str, variant_id: str, scene_id: str, pin: PrefabRef) -> StageBinding | None:
        """La fenetre qui affiche `scene_id` **avec ce pin** : la liaison en memoire, ou — apres un redemarrage de Core, qui
        l'a perdue — l'objet a l'id deterministe de la Presentation, SI son pin est la source propre de cette scene (cet
        id de prefab porte l'id de la scene : aucune ambiguite). Un pin partage (une base, un prefab commun) ne permet pas
        de savoir quelle scene le stage montre : `None`, et la lecture (Slice 12) rebinde au prochain affichage."""

        bound = self.binding_for(presentation_id, variant_id, scene_id)
        if bound is not None:
            return bound
        if pin.prefab_id != source_prefab_id(presentation_id, scene_id):
            return None
        candidate = StageBinding(presentation_id, variant_id, scene_id, stage_object_id(presentation_id))
        block = await self.current(candidate)
        if block is None or PrefabRef(block.prefab_id, block.version) != pin:
            return None
        self.bind(candidate)
        self._trace("core.presentation_studio.stage_rebound", "Fenetre stage retrouvee apres un redemarrage",
                    data={"presentation_id": presentation_id, "variant_id": variant_id, "scene_id": scene_id})
        return candidate

    def bindings(self) -> tuple[StageBinding, ...]:
        return tuple(self._bindings.values())

    # ------------------------------------------------------------ lecture

    async def current(self, binding: StageBinding) -> ScenePrefabRef | None:
        """Le bloc `prefab` vivant de la fenetre (valeurs committees par les evenements d'etat du cadre comprises)."""

        snapshot = await self._scene.snapshot()
        found = snapshot.get_object(binding.object_id)
        return None if found is None else found.payload.prefab

    # ------------------------------------------------------------ ecriture

    async def repin(self, binding: StageBinding, *, expect: PrefabRef, to: PrefabRef,
                    props: dict[str, Any], data: dict[str, Any]) -> None:
        """Change le pin de la fenetre (donc remonte **ce** cadre) et pose `props`/`data`, seulement si la fenetre porte
        encore `expect`. `StagePatchError` sinon ou si la scene refuse l'instance."""

        verdict: list[tuple[str, str]] = []

        def plan(snapshot: Any) -> SceneCommand | None:
            target = snapshot.get_object(binding.object_id)
            block = None if target is None else target.payload.prefab
            if target is None:
                verdict.append(("stage_missing", "the stage window no longer exists"))
                return None
            if block is None or PrefabRef(block.prefab_id, block.version) != expect:
                verdict.append(("stage_changed", "the stage window no longer shows the expected version"))
                return None
            payload = replace(target.payload, prefab=ScenePrefabRef(to.prefab_id, to.version, props, data))
            return SceneCommand(op=SceneOp.PATCH_OBJECT, actor=SceneActor.USER, object_id=binding.object_id,
                                fields=SceneObjectFields(payload=payload))

        try:
            update = await self._scene.apply_if(plan)
        except (ValueError, TypeError) as exc:  # a payload beyond the scene bounds: refused, not a fault
            raise StagePatchError("prefab_invalid", str(exc)) from None
        if update is None:
            code, message = verdict[0]
            raise StagePatchError(code, message)
        if update.outcome not in (SceneCommandOutcome.APPLIED, SceneCommandOutcome.DUPLICATE):
            reason = update.reason.value if update.reason is not None else update.outcome.value
            raise StagePatchError(reason, update.detail or reason)

    async def show(self, presentation_id: str, variant_id: str, scene: StudioScene) -> StageBinding:
        """**Provisoire** (la lecture, Slice 12, la remplace) : cree le stage de la Presentation ou le re-patche avec
        `scene.payload()` (un upsert idempotent sur l'id deterministe), puis le lie. Rend la liaison."""

        binding = StageBinding(presentation_id, variant_id, scene.scene_id, stage_object_id(presentation_id))
        fields = SceneObjectFields(kind=SceneObjectKind.WINDOW, category=STAGE_CATEGORY,
                                   representation=Representation.WINDOW, geometry=DEFAULT_GEOMETRY,
                                   visibility=Visibility.VISIBLE, payload=scene.payload())
        update = await self._scene.apply(SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=SceneActor.USER,
                                                      object_id=binding.object_id, fields=fields))
        if update.outcome not in (SceneCommandOutcome.APPLIED, SceneCommandOutcome.DUPLICATE):
            reason = update.reason.value if update.reason is not None else update.outcome.value
            raise StagePatchError(reason, update.detail or reason)
        self.bind(binding)
        self._trace("core.presentation_studio.stage_shown", "Scene affichee sur le stage",
                    data={"presentation_id": presentation_id, "variant_id": variant_id, "scene_id": scene.scene_id})
        return binding

    def _trace(self, kind: str, message: str, *, data: dict[str, Any]) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level="info", data=data)
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal never undoes a scene write
            pass

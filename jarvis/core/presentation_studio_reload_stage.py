"""La fenetre « stage » vue par le rechargement a chaud (handoff jarvis-interactive-presentation-studio, Slice 06).

La Slice 12 (lecture) POSSEDE la fenetre : `SceneStage` (`presentation_studio_stage.py`) la cree par run (`studio-stage-<run_id>`),
la patche d'une scene a l'autre et la retire. Ce module n'en cree jamais : il garde en memoire **quelle fenetre affiche quelle
scene** (handle d'execution : jamais persiste, jamais dans un document) et n'ecrit qu'une chose, le **pin** de cette fenetre :

- `bind` / `unbind` : appeles par le service de lecture (observateur de stage) a chaque affichage d'une scene et a la fin du
  run. Une scene qui n'est pas affichee n'a pas de liaison : sa source est seulement re-epinglee.
- `repin` : change le pin de la fenetre (donc remonte **ce** cadre, la regle de l'hote), compare-and-set sous le verrou de la
  scene (`SceneService.apply_if`, docs/07 §4.4) : un evenement d'etat du cadre simultane n'est jamais perdu et un patch ne
  s'applique que si la fenetre porte encore le pin attendu (`stage_changed` sinon). Idempotent : une fenetre qui porte deja
  le pin cible (la lecture l'a suivi entre-temps) n'est pas reecrite.
- `current` : le bloc vivant (valeurs committees par les evenements d'etat du cadre comprises).

Les patchs prefab traversent la validation de la scene (`SceneService._check_prefabs`) : une instance invalide pour le
nouveau manifeste est refusee (`prefab_invalid`), jamais ecrite.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from jarvis.core.scene_service import SceneService
from jarvis.domain.prefab import PrefabRef
from jarvis.domain.scene import SceneActor, SceneCommand, SceneCommandOutcome, SceneObjectFields, SceneOp, ScenePrefabRef
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
    #: Le run de lecture dont c'est la fenetre (`studio-stage-<run_id>[-<n>]`), pour la trace.
    run_id: str = ""


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
        """La fenetre que la lecture affiche pour **cette** scene, SI elle existe encore dans la scene globale et porte ce
        pin (l'utilisateur a pu la fermer ; la lecture la rouvre sous un autre id et rebinde). Sinon `None` : la source est
        seulement re-epinglee. Apres un redemarrage de Core il n'y a plus de liaison (la lecture est reprise a zero)."""

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
            if block is not None and PrefabRef(block.prefab_id, block.version) == to:
                return None  # already there (the playback followed the variant): nothing to write, nothing failed
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
            if not verdict:
                return
            code, message = verdict[0]
            raise StagePatchError(code, message)
        if update.outcome not in (SceneCommandOutcome.APPLIED, SceneCommandOutcome.DUPLICATE):
            reason = update.reason.value if update.reason is not None else update.outcome.value
            raise StagePatchError(reason, update.detail or reason)

    def _trace(self, kind: str, message: str, *, data: dict[str, Any]) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level="info", data=data)
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal never undoes a scene write
            pass

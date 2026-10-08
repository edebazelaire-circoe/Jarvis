"""Service Core des variantes locales d'une scène (handoff jarvis-interactive-presentation-studio, Slice 17).

Les **écritures** d'ensemble (créer, renommer, choisir, supprimer) ne sont pas ici : ce sont des opérations du vocabulaire
d'édition sémantique (`scene_variant.*`, Slice 05), donc la voix et l'interface partagent la même porte, la même base de
révision, la même écriture durable (`_write_variant` -> `_persist_variant`), le même évènement `edit_committed` et la même
annulation (Slice 08). Ce module ajoute ce que le vocabulaire ne peut pas dire :

- **lister** (`describe`) : les variantes locales d'une scène, sans leur contenu, avec leurs bornes ;
- **aperçu** (`preview`) : la scène telle qu'elle serait si la variante locale était choisie, rendue **en mémoire** par
  `render_overlay` (Slice 12). Rien n'est écrit (ni fichier, ni évènement, ni anneau d'annulation). Si l'utilisateur le demande
  (`stage: true`) et que la lecture de cette variante est **en pause**, la fenêtre de scène la montre dans un état d'aperçu
  éphémère, rendu à la scène canonique par `cancel_preview`, par le délai, par n'importe quelle commande de lecture, par une
  édition validée ou par l'arrêt (`PresentationStudioPlaybackService.show_preview`) ;
- **promouvoir** (`promote`) : une nouvelle variante de présentation (opération de branche de la Slice 16, `transform`) dont la
  scène prend le contenu de la variante locale. La source garde son ensemble ; la branche en reçoit la copie (les variantes
  locales font partie du document de variante). Aucun prefab n'est publié : les épingles sont partagées.

Diagnostics `core.presentation_studio.scene_variant_{described,previewed,preview_ended,promoted}` : identifiants, comptes,
octets ; jamais un libellé, une valeur ni un titre.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from jarvis.domain.presentation_studio import (
    PresentationStudioError, PresentationStudioErrorCode as C, PresentationVariant, _check_title, is_presentation_id,
    is_variant_id,
)
from jarvis.domain.presentation_studio_checks import _check_int, _exact_keys, _fail, is_scene_id
from jarvis.domain.presentation_studio_edit import (
    EditRefusal, EditStatus, SceneVariantSelect, StudioActor, apply_ops, scenes_changed,
)
from jarvis.domain.presentation_studio_scene import StudioScene
from jarvis.domain.presentation_studio_scene_variants import (
    MAX_SCENE_VARIANTS, MAX_SET_BYTES, is_scene_variant_id,
)
from jarvis.domain.presentation_studio_variants import check_rationale
from jarvis.domain.prefab import canonical_json
from jarvis.ports.v2 import DiagnosticSink

#: L'aperçu sur la fenêtre de scène s'éteint seul : défaut et plafond (secondes).
PREVIEW_TIMEOUT_S = 30
MAX_PREVIEW_TIMEOUT_S = 120
MAX_BODY_KEYS = frozenset({"actor", "stage", "timeout_s"})


class PresentationStudioSceneVariants:
    def __init__(self, studio: Any, edit: Any, variants: Any, *, diagnostics: DiagnosticSink | None = None) -> None:
        self._studio = studio
        self._edit = edit
        self._variants = variants
        self._diagnostics = diagnostics
        self._playback: Any | None = None

    def bind_playback(self, playback: Any) -> None:
        """La lecture (Slice 12), liée après sa construction : elle seule touche la fenêtre de scène."""

        self._playback = playback

    # ------------------------------------------------------------ lecture

    async def describe(self, presentation_id: str, variant_id: str, scene_id: str) -> dict[str, Any]:
        """Les variantes locales de la scène (sans contenu) : `selected`, `count`, bornes, une ligne par variante."""

        scene, variant = await self._scene(presentation_id, variant_id, scene_id)
        variants = scene.scene_variants
        rows: list[dict[str, Any]] = []
        if variants is not None:
            for item in variants.items:
                content = scene.live_content() if item.content is None else item.content
                rows.append({**item.meta(), "selected": item.variant_id == variants.current_id,
                             "prefab": dict(content["prefab"]), "controls": len(content["controls"]),
                             "anchors": len(content["anchors"])})
        size = len(canonical_json(variants.to_dict()).encode("utf-8")) if variants is not None else 0
        self._trace("scene_variant_described", "Variantes locales decrites",
                    data={"presentation_id": presentation_id, "variant_id": variant_id, "scene_id": scene_id,
                          "count": len(rows), "bytes": size})
        return {"presentation_id": presentation_id, "variant_id": variant_id, "scene_id": scene_id,
                "variant_revision": variant.revision, "selected": variants.current_id if variants else None,
                "count": len(rows), "variants": rows,
                "limits": {"variants": MAX_SCENE_VARIANTS, "bytes": MAX_SET_BYTES, "bytes_used": size}}

    # ------------------------------------------------------------ aperçu

    async def preview(self, presentation_id: str, variant_id: str, scene_id: str, scene_variant_id: str,
                      raw: object = None) -> dict[str, Any]:
        """La scène avec cette variante locale choisie, **en mémoire**. `stage: true` la montre sur la fenêtre de scène si la
        lecture de cette variante est en pause (`staged`, `stage_reason` dit pourquoi pas). N'écrit jamais."""

        data = _exact_keys({} if raw is None else raw, "scene variant preview", set(), MAX_BODY_KEYS)
        stage = data.get("stage", False)
        if type(stage) is not bool:
            raise _fail("stage must be true or false")
        timeout_s = data.get("timeout_s", PREVIEW_TIMEOUT_S)
        _check_int("timeout_s", timeout_s, 1, MAX_PREVIEW_TIMEOUT_S)
        actor = _actor(data)
        self._require_ids(presentation_id, variant_id, scene_id, scene_variant_id)
        scene, variant = await self._scene(presentation_id, variant_id, scene_id)
        if scene.scene_variants is None:
            raise PresentationStudioError(C.UNKNOWN_SCENE_VARIANT, f"{scene_variant_id} is not a variant of this scene")
        scene.scene_variants.get(scene_variant_id)  # unknown id -> typed 404
        render = await self._edit.render_overlay(
            presentation_id, variant_id, variant.revision,
            [SceneVariantSelect(scene_id, scene_variant_id).to_dict()], actor=actor)
        if render.status is not EditStatus.APPLIED:
            code = C(render.code) if render.code else C.INVALID_PRESENTATION
            raise PresentationStudioError(code, render.message or "the preview was refused")
        shown = next(s for s in render.scenes if s.scene_id == scene_id)
        staged, reason = False, None
        if stage:
            outcome = await self._stage(presentation_id, variant_id, shown, scene_variant_id, variant.revision, timeout_s)
            staged, reason = outcome["staged"], outcome.get("reason")
        self._trace("scene_variant_previewed", "Variante locale apercue (rien d'ecrit)",
                    data={"presentation_id": presentation_id, "variant_id": variant_id, "scene_id": scene_id,
                          "scene_variant_id": scene_variant_id, "staged": staged, "stage_requested": stage,
                          "stage_reason": reason, "written": False})
        return {"presentation_id": presentation_id, "variant_id": variant_id, "scene_id": scene_id,
                "scene_variant_id": scene_variant_id, "variant_revision": variant.revision, "written": False,
                "preview": {"title": shown.title, "payload": shown.payload().to_payload(), "budget": shown.budget(),
                            "live_unchanged": scene.scene_variants.current_id},
                "staged": staged, "stage_reason": reason, "expires_in_s": timeout_s if staged else None}

    async def cancel_preview(self, presentation_id: str, raw: object = None) -> dict[str, Any]:
        """Rend la fenêtre de scène à la scène canonique. Sans aperçu en cours : `cancelled: false` (rien à faire, pas une faute)."""

        _exact_keys({} if raw is None else raw, "cancel preview", set(), frozenset({"actor"}))
        if not is_presentation_id(presentation_id):
            raise PresentationStudioError(C.UNKNOWN_PRESENTATION, "unknown presentation id")
        cancelled = False
        if self._playback is not None:
            cancelled = await self._playback.end_preview("cancel", presentation_id=presentation_id)
        self._trace("scene_variant_preview_ended", "Apercu de variante locale termine",
                    data={"presentation_id": presentation_id, "reason": "cancel", "cancelled": cancelled})
        return {"presentation_id": presentation_id, "cancelled": cancelled}

    async def _stage(self, presentation_id: str, variant_id: str, scene: StudioScene, scene_variant_id: str, revision: int,
                     timeout_s: int) -> dict[str, Any]:
        if self._playback is None:
            return {"staged": False, "reason": "no_playback"}
        return await self._playback.show_preview(presentation_id, variant_id, scene, scene_variant_id=scene_variant_id,
                                                 revision=revision, timeout_s=float(timeout_s))

    # ------------------------------------------------------------ promouvoir

    async def promote(self, presentation_id: str, variant_id: str, scene_id: str, scene_variant_id: str,
                      raw: object) -> dict[str, Any]:
        """Une nouvelle variante de présentation (enfant de `variant_id`) dont la scène prend le contenu de la variante locale.

        Corps `{title, rationale?, activate?, actor?, expected_revision?, expected_variant_revision?}`. Provenance : la source
        de la branche est `variant_id`, la raison de création commence par les identifiants de la variante locale et de la
        scène. La source garde son ensemble tel quel (hachage identique) ; la branche reçoit la copie, la variante locale
        promue y est la choisie. Les validations (contenu contre le prefab, partition) précèdent toute écriture."""

        data = _exact_keys(raw, "promote", {"title"}, frozenset(
            {"rationale", "activate", "actor", "expected_revision", "expected_variant_revision"}))
        _check_title("title", data["title"])
        note = check_rationale(data.get("rationale", ""))
        actor = _actor(data)
        if data.get("expected_variant_revision") is not None:
            _check_int("expected_variant_revision", data["expected_variant_revision"], 1, 2**31 - 1)
        self._require_ids(presentation_id, variant_id, scene_id, scene_variant_id)
        scene, source = await self._scene(presentation_id, variant_id, scene_id)
        if data.get("expected_variant_revision") not in (None, source.revision):
            raise PresentationStudioError(
                C.STALE_REVISION, f"{variant_id} is at revision {source.revision}, not {data['expected_variant_revision']}: "
                                  "reload, then retry")
        if scene.scene_variants is None:
            raise PresentationStudioError(C.UNKNOWN_SCENE_VARIANT, f"{scene_variant_id} is not a variant of this scene")
        scene.scene_variants.get(scene_variant_id)
        promoted = _selected_in(source, scene_id, scene_variant_id, actor)  # pure: may refuse before anything is written
        if scenes_changed(source.scenes, promoted.scenes):
            await self._studio.check_scenes(presentation_id, variant_id, promoted.scenes, source.scenes)
            broken = await self._edit.score_regression(source, promoted.scenes)
            if broken:
                raise PresentationStudioError(
                    C.SCORE_INCOMPATIBLE, f"promoting this scene variant would leave {len(broken)} score reference(s) "
                                          f"unresolved (first: {broken[0]})")
        reason = f"promoted from scene variant {scene_variant_id} of scene {scene_id}."
        body = {"title": data["title"], "source_variant_id": variant_id, "actor": actor.value,
                "rationale": check_rationale(f"{reason} {note}".strip()),
                **{key: data[key] for key in ("activate", "expected_revision") if key in data}}
        answer = await self._variants.create_branch(
            presentation_id, body, transform=lambda base: _selected_in(base, scene_id, scene_variant_id, actor))
        self._trace("scene_variant_promoted", "Variante locale promue en variante de presentation",
                    data={"presentation_id": presentation_id, "source_variant_id": variant_id, "scene_id": scene_id,
                          "scene_variant_id": scene_variant_id, "variant_id": answer["node"]["variant_id"],
                          "activated": answer["activated"]})
        return {**answer, "scene_id": scene_id, "scene_variant_id": scene_variant_id}

    # ------------------------------------------------------------ interne

    async def _scene(self, presentation_id: str, variant_id: str, scene_id: str) -> tuple[StudioScene, PresentationVariant]:
        if not is_presentation_id(presentation_id):
            raise PresentationStudioError(C.UNKNOWN_PRESENTATION, "unknown presentation id")
        if not is_variant_id(variant_id):
            raise PresentationStudioError(C.UNKNOWN_VARIANT, "unknown variant id")
        if not is_scene_id(scene_id):
            raise PresentationStudioError(C.UNKNOWN_SCENE, "unknown scene id")
        variant = await self._studio.get_variant(presentation_id, variant_id)
        scene = next((s for s in variant.scenes if s.scene_id == scene_id), None)
        if scene is None:
            raise PresentationStudioError(C.UNKNOWN_SCENE, f"{scene_id} is not a scene of this variant")
        return scene, variant

    @staticmethod
    def _require_ids(presentation_id: str, variant_id: str, scene_id: str, scene_variant_id: str) -> None:
        if not is_scene_variant_id(scene_variant_id):
            raise PresentationStudioError(C.UNKNOWN_SCENE_VARIANT, "unknown scene variant id")

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any]) -> None:
        self._studio.trace(f"core.presentation_studio.{kind}", message, level=level, data=data)


def _actor(data: Mapping[str, Any]) -> StudioActor:
    try:
        return StudioActor(data.get("actor", "user"))
    except ValueError:
        raise _fail("actor must be 'user' or 'brain'") from None


def _selected_in(variant: PresentationVariant, scene_id: str, scene_variant_id: str, actor: StudioActor) -> PresentationVariant:
    """La variante avec `scene_variant_id` choisie dans sa scène : le moteur d'édition, pur, sans écriture ni manifeste."""

    try:
        plan = apply_ops(variant.scenes, [SceneVariantSelect(scene_id, scene_variant_id)], {},
                         presentation_id=variant.presentation_id, variant_id=variant.variant_id, actor=actor,
                         basis_revision=variant.revision)
    except EditRefusal as refusal:
        raise PresentationStudioError(refusal.code, refusal.message) from None
    return replace(variant, scenes=plan.scenes)

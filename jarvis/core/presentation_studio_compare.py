"""Service Core de la comparaison de variantes (handoff jarvis-interactive-presentation-studio, Slice 19).

L'ensemble de comparaison (2 ou 4 variantes, paire en focus 50/50, mode `sync` / `independent`, liens de scenes manuels, scene
courante de chaque variante) est de l'etat d'**interface** : une entree **en memoire** par Presentation (au plus
`MAX_TRACKED` Presentations, la moins recente est oubliee), perdue a l'arret de Core, jamais ecrite dans un document, jamais
dans l'historique d'annulation. Aucune operation n'ecrit une variante : la comparaison **lit** la structure (ids, titres, pins)
et rend a chaque fois la vue complete (`build_view`, `domain/presentation_studio_compare.py`).

Chaque operation est atomique sur l'etat (une seule coroutine sans `await` entre la lecture et l'ecriture de l'etat), numerote
l'etat (`revision`) et accepte `expected_revision` : un client qui a vu la revision 7 ne ecrase pas la 8.
Contrat : `docs/presentation-studio.md` > *Comparison and semantic composition contract*.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from typing import Any

from jarvis.domain.presentation_studio import (
    PresentationStudioError, PresentationStudioErrorCode as C, PresentationVariant, is_presentation_id,
)
from jarvis.domain.presentation_studio_compare import (
    CompareState, SceneShape, VariantShape, add_link, build_view, navigate, parse_body, parse_select, remove_link, select,
    set_mode, set_pair,
)

#: Presentations dont l'ensemble est garde en memoire.
MAX_TRACKED = 16


class PresentationStudioCompare:
    def __init__(self, studio: Any) -> None:
        self._studio = studio
        self._states: OrderedDict[str, CompareState] = OrderedDict()

    # ------------------------------------------------------------ lecture

    async def view(self, presentation_id: str) -> dict[str, Any]:
        """L'ensemble courant (vide : `active: false`, revision 0) avec les structures lues maintenant."""

        self._require(presentation_id)
        state = self._states.get(presentation_id) or CompareState(presentation_id)
        shapes, problems = await self._shapes(presentation_id, state)
        return build_view(state, shapes, problems)

    # ------------------------------------------------------------ operations

    async def select(self, presentation_id: str, raw: object) -> dict[str, Any]:
        """Choisit 2 ou 4 variantes **vivantes** (et, si on veut, la paire en focus et le mode). Remplace la selection ; les liens
        manuels entre variantes encore choisies sont gardes."""

        self._require(presentation_id)
        request = parse_select(raw)
        state = self._current(presentation_id, request.get("expected_revision"))
        wanted = CompareState(presentation_id, variant_ids=request["variant_ids"])
        shapes, problems = await self._shapes(presentation_id, wanted)
        if problems:
            code, text = (C.UNKNOWN_VARIANT, f"{problems[0]['variant_id']} is not a live variant of this presentation "
                                             "(archived variants must be restored before they are compared)")
            raise PresentationStudioError(code, text)
        return await self._commit(presentation_id, select(state, request, shapes), shapes, "select")

    async def set_pair(self, presentation_id: str, raw: object) -> dict[str, Any]:
        """Met une paire en focus (mode 50/50), ou `pair: null` pour revenir a tout l'ensemble."""

        return await self._apply(presentation_id, "pair", raw, lambda state, data, shapes: set_pair(state, data["pair"]))

    async def set_mode(self, presentation_id: str, raw: object) -> dict[str, Any]:
        return await self._apply(presentation_id, "mode", raw, lambda state, data, shapes: set_mode(state, data["mode"]))

    async def link(self, presentation_id: str, raw: object) -> dict[str, Any]:
        """Apparie a la main deux scenes de deux variantes de l'ensemble (structures divergentes)."""

        return await self._apply(presentation_id, "link", raw, lambda state, data, shapes: add_link(state, data["a"], data["b"], shapes))

    async def unlink(self, presentation_id: str, raw: object) -> dict[str, Any]:
        return await self._apply(presentation_id, "link", raw, lambda state, data, shapes: remove_link(state, data["a"], data["b"]))

    async def navigate(self, presentation_id: str, raw: object) -> dict[str, Any]:
        """Deplace la scene courante d'une variante (par `scene_id` ou `step`) ; en `sync`, celles des autres selon l'equivalence.
        La reponse ajoute `navigation: {origin, results: {variant_id: {scene_id, status}}}`."""

        self._require(presentation_id)
        data = parse_body(raw, "navigate")
        state = self._current(presentation_id, data.get("expected_revision"))
        shapes, problems = await self._shapes(presentation_id, state)
        self._refuse_problems(problems)
        moved, navigation = navigate(state, shapes, data)
        view = await self._commit(presentation_id, moved, shapes, "navigate")
        return {**view, "navigation": navigation}

    async def clear(self, presentation_id: str, raw: object = None) -> dict[str, Any]:
        self._require(presentation_id)
        data = parse_body(raw, "clear")
        state = self._current(presentation_id, data.get("expected_revision"))
        self._states.pop(presentation_id, None)
        self._trace("compare_cleared", presentation_id, 0)
        return {"presentation_id": presentation_id, "cleared": state.active, "active": False, "revision": state.revision + 1}

    # ------------------------------------------------------------ interne

    async def _apply(self, presentation_id: str, kind: str, raw: object, change: Any) -> dict[str, Any]:
        self._require(presentation_id)
        data = parse_body(raw, kind)
        state = self._current(presentation_id, data.get("expected_revision"))
        shapes, problems = await self._shapes(presentation_id, state)
        self._refuse_problems(problems)
        return await self._commit(presentation_id, change(state, data, shapes), shapes, kind)

    async def _commit(self, presentation_id: str, state: CompareState, shapes: Mapping[str, VariantShape], op: str) -> dict[str, Any]:
        self._states[presentation_id] = state
        self._states.move_to_end(presentation_id)
        while len(self._states) > MAX_TRACKED:
            self._states.popitem(last=False)
        self._trace(f"compare_{op}", presentation_id, len(state.variant_ids))
        return build_view(state, shapes, ())

    def _current(self, presentation_id: str, expected: int | None) -> CompareState:
        state = self._states.get(presentation_id) or CompareState(presentation_id)
        if expected is not None and expected != state.revision:
            raise PresentationStudioError(
                C.STALE_REVISION, f"the comparison of {presentation_id} is at revision {state.revision}, not {expected}: reload, then retry")
        return state

    @staticmethod
    def _refuse_problems(problems: list[dict[str, str]]) -> None:
        if problems:
            raise PresentationStudioError(
                C.UNKNOWN_VARIANT, f"{problems[0]['variant_id']} is no longer a live variant: select the comparison again")

    async def _shapes(self, presentation_id: str, state: CompareState) -> tuple[dict[str, VariantShape], list[dict[str, str]]]:
        """La structure de chaque variante choisie, lue maintenant. Une variante qui n'est plus vivante est un `problem`, pas une panne."""

        view = await self._studio.get(presentation_id)
        live: dict[str, PresentationVariant] = {v.variant_id: v for v in view.variants}
        active = view.presentation.active_variant_id
        shapes: dict[str, VariantShape] = {}
        problems: list[dict[str, str]] = []
        for variant_id in state.variant_ids:
            variant = live.get(variant_id)
            if variant is None:
                problems.append({"variant_id": variant_id, "code": "variant_unavailable"})
                continue
            shapes[variant_id] = VariantShape(
                variant_id, variant.variant_number, variant.title, variant.revision, variant_id == active,
                tuple(SceneShape(s.scene_id, s.title, s.prefab.prefab_id, s.prefab.version) for s in variant.scenes))
        return shapes, problems

    @staticmethod
    def _require(presentation_id: str) -> None:
        if not is_presentation_id(presentation_id):
            raise PresentationStudioError(C.UNKNOWN_PRESENTATION, "unknown presentation id")

    def _trace(self, kind: str, presentation_id: str, count: int) -> None:
        self._studio.trace(f"core.presentation_studio.{kind}", "Comparaison de variantes", data={"presentation_id": presentation_id, "count": count})

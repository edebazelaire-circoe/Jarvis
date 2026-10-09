"""Presentation Studio : les cinq opérations d'édition des variantes locales d'une scène (handoff
jarvis-interactive-presentation-studio, Slice 17).

Vocabulaire seul (dataclasses, analyse, forme filaire) ; le moteur qui les applique est `_apply_scene_variant` dans
`presentation_studio_edit.py`, qui importe ce module et en fait des membres de `OpName` (`scene_variant.*`). Le nom d'une
opération est ici une chaîne : `OpName` est un `StrEnum`, donc égal à elle, et ce module n'importe pas le moteur (pas de cycle).

`restore_set` est ouverte aux deux acteurs (comme `scene.restore_values`) : c'est la forme d'une annulation, rejouée par
l'historique. Son ensemble est validé **comme celui d'un `create`** (mêmes validateurs de `SceneVariant` : identifiant `psx_`,
libellé unique d'une ligne, `created_by` ∈ {user, brain}, `source`, horodatage, bornes) ; une provenance forgée est refusée, et
chaque contenu est revalidé comme une scène par `StudioScene`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from jarvis.domain.presentation_studio_checks import SCENE_ID, _check_id, _exact_keys, _fail
from jarvis.domain.presentation_studio_scene_variants import (
    SceneVariantSet, check_label, check_rationale, is_scene_variant_id,
)


def _scene_id(raw: Mapping[str, Any]) -> str:
    _check_id("scene_id", raw["scene_id"], SCENE_ID)
    return raw["scene_id"]


def _variant_id(raw: Mapping[str, Any]) -> str:
    if not is_scene_variant_id(raw["variant_id"]):
        raise _fail("variant_id is not a scene variant id (psx_...)")
    return raw["variant_id"]


@dataclass(frozen=True, slots=True)
class SceneVariantCreate:
    """Copie le contenu **vivant** de la scène (ou celui d'une autre variante locale) dans une nouvelle variante locale rangée.
    La scène ne bouge pas. Sans ensemble, la scène devient d'abord l'entrée « Original »."""

    NAME: ClassVar[str] = "scene_variant.create"
    scene_id: str
    label: str
    rationale: str = ""
    from_variant: str | None = None

    def to_dict(self) -> dict[str, Any]:
        wire = {"op": self.NAME, "scene_id": self.scene_id, "label": self.label, "rationale": self.rationale}
        if self.from_variant is not None:
            wire["from_variant"] = self.from_variant
        return wire

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> SceneVariantCreate:
        data = _exact_keys(raw, "scene_variant.create", {"op", "scene_id", "label"}, frozenset({"rationale", "from_variant"}))
        source = data.get("from_variant")
        if source is not None and not is_scene_variant_id(source):
            raise _fail("from_variant must be a scene variant id (psx_...)")
        return cls(_scene_id(data), check_label(data["label"]), check_rationale(data.get("rationale", "")), source)


@dataclass(frozen=True, slots=True)
class SceneVariantRename:
    NAME: ClassVar[str] = "scene_variant.rename"
    scene_id: str
    variant_id: str
    label: str

    def to_dict(self) -> dict[str, Any]:
        return {"op": self.NAME, "scene_id": self.scene_id, "variant_id": self.variant_id, "label": self.label}

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> SceneVariantRename:
        data = _exact_keys(raw, "scene_variant.rename", {"op", "scene_id", "variant_id", "label"})
        return cls(_scene_id(data), _variant_id(data), check_label(data["label"]))


@dataclass(frozen=True, slots=True)
class SceneVariantSelect:
    """La permutation : la variante locale choisie devient la scène, l'ancienne est rangée avec son contenu exact.
    `drop_others` : « promouvoir dans la variante courante », les autres variantes locales sont retirées (l'annulation les rend)."""

    NAME: ClassVar[str] = "scene_variant.select"
    scene_id: str
    variant_id: str
    drop_others: bool = False

    def to_dict(self) -> dict[str, Any]:
        wire = {"op": self.NAME, "scene_id": self.scene_id, "variant_id": self.variant_id}
        if self.drop_others:
            wire["drop_others"] = True
        return wire

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> SceneVariantSelect:
        data = _exact_keys(raw, "scene_variant.select", {"op", "scene_id", "variant_id"}, frozenset({"drop_others"}))
        drop = data.get("drop_others", False)
        if type(drop) is not bool:
            raise _fail("drop_others must be true or false")
        return cls(_scene_id(data), _variant_id(data), drop)


@dataclass(frozen=True, slots=True)
class SceneVariantDelete:
    NAME: ClassVar[str] = "scene_variant.delete"
    scene_id: str
    variant_id: str

    def to_dict(self) -> dict[str, Any]:
        return {"op": self.NAME, "scene_id": self.scene_id, "variant_id": self.variant_id}

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> SceneVariantDelete:
        data = _exact_keys(raw, "scene_variant.delete", {"op", "scene_id", "variant_id"})
        return cls(_scene_id(data), _variant_id(data))


@dataclass(frozen=True, slots=True)
class SceneVariantRestoreSet:
    """La forme exacte de l'annulation d'une opération sur l'ensemble : l'ensemble entier (`None` : aucun), la scène intacte.
    Ne change jamais la variante locale choisie (sinon un contenu serait perdu) ; limité à l'ensemble de la scène."""

    NAME: ClassVar[str] = "scene_variant.restore_set"
    scene_id: str
    scene_variants: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {"op": self.NAME, "scene_id": self.scene_id, "scene_variants": self.scene_variants}

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> SceneVariantRestoreSet:
        data = _exact_keys(raw, "scene_variant.restore_set", {"op", "scene_id", "scene_variants"})
        body = data["scene_variants"]
        if body is not None:
            SceneVariantSet.from_dict(body, "scene_variants")  # shape and bounds now; the scene validates the contents
        return cls(_scene_id(data), body)

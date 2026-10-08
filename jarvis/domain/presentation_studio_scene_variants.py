"""Presentation Studio : les variantes locales d'une scène (handoff jarvis-interactive-presentation-studio, Slice 17).

Une *variante locale* est une alternative légère d'**une** scène logique, à l'intérieur d'une variante de présentation :
trois traitements d'une révélation de produit, deux mises en page, sans brancher tout le diaporama. Elle ne copie ni le
reste de la variante, ni l'identité de la scène : seul le **contenu** diffère (épingle de prefab, valeurs `props`/`data`,
contrôles curés, ancres). Contrat : `docs/presentation-studio.md` › *Scene-local variant contract*.

## Le modèle : l'état vivant est toujours la scène

Les champs canoniques de `StudioScene` (`prefab`, `props`, `data`, `controls`, `anchors`) **sont** le contenu de la variante
locale choisie (`current_id`) : le lecteur, l'inspecteur, la partition et les éditions de la Slice 05 ne lisent et n'écrivent
que ça, rien n'a changé pour eux. L'ensemble ne garde donc le contenu que des variantes **non choisies** ; celle qui est
choisie n'a pas de `content` (une seule copie de chaque contenu, jamais deux sources de vérité).

## Choisir = une permutation

`select(cible)` fait `contenu_vivant -> emplacement de l'ancienne choisie`, `emplacement de cible -> scène`. Rien n'est jamais
recopié ni recalculé : les contenus sont stockés dans leur forme canonique (`StudioScene.to_dict()`), donc choisir A puis B
puis A rend la scène **identique en JSON canonique**, et `select(ancienne)` est l'inverse exact de `select(cible)`.
Supprimer une variante non choisie n'altère pas la scène ; la choisie ne se supprime pas (`scene_variant_protected`).

## Forme canonique

Un ensemble contient 2 à `MAX_SCENE_VARIANTS` entrées. Une scène avec une seule variante est une scène **sans** ensemble
(clé absente) : un document qui n'a jamais utilisé la fonction est octet pour octet celui d'avant, et la dernière
suppression ramène exactement à cet état. Les identifiants sont `psx_<12 hex>`.

Pur : aucune E/S, aucune dépendance de `presentation_studio_scene` (qui en dépend). Le contenu y est un dictionnaire JSON ;
sa validité sémantique (pin, contrôles, plafond de charge) est celle de `StudioScene`, qui construit un candidat par entrée.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
import json
import re
import secrets
from typing import Any

from jarvis.domain.prefab import canonical_json
from jarvis.domain.presentation_studio_checks import PresentationStudioError, PresentationStudioErrorCode as C, _exact_keys, _fail

#: Bornes (toute collection est bornée).
MAX_SCENE_VARIANTS = 8
MAX_LABEL = 40
MAX_RATIONALE = 160
#: Octets canoniques d'un ensemble : choisi pour que l'enregistrement d'annulation d'une opération sur l'ensemble
#: (`MAX_UNDO_BYTES` = 64 Kio) tienne toujours avec sa marge. Le plafond du document (256 Kio) reste celui de la variante.
MAX_SET_BYTES = 40 * 1024
ORIGINAL_LABEL = "Original"
#: `source` de l'entrée « Original » (la scène telle qu'elle était avant tout ensemble).
CURRENT = "current"

VARIANT_ID = re.compile(r"psx_[0-9a-f]{12}\Z")
CONTENT_KEYS = ("prefab", "props", "data", "controls", "anchors")
_ACTORS = frozenset({"user", "brain"})
_STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z")


def new_scene_variant_id() -> str:
    return "psx_" + secrets.token_hex(6)


def is_scene_variant_id(value: object) -> bool:
    return isinstance(value, str) and bool(VARIANT_ID.fullmatch(value))


def _line(name: str, value: object, limit: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise _fail(f"{name} must be a string")
    if not value:
        if allow_empty:
            return value
        raise _fail(f"{name} must not be empty")
    if value != value.strip() or not value.isprintable() or len(value) > limit:
        raise _fail(f"{name} must be one printable line of at most {limit} characters, without surrounding spaces")
    return value


def check_label(value: object) -> str:
    return _line("label", value, MAX_LABEL)


def check_rationale(value: object) -> str:
    return _line("rationale", value, MAX_RATIONALE, allow_empty=True)


def _copy(content: Mapping[str, Any]) -> dict[str, Any]:
    """Copie profonde **qui garde l'ordre des clés** (donc les octets du document après un aller-retour) : aucune référence
    partagée avec l'appelant, aucune valeur non JSON. `1`, `1.0` et `true` restent ce qu'ils sont."""

    try:
        return json.loads(json.dumps(content, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError, RecursionError):
        raise _fail("scene variant content must be pure JSON") from None


def check_content(content: object, where: str = "content") -> dict[str, Any]:
    """Forme (pas la sémantique) : exactement `CONTENT_KEYS`, des objets et des listes."""

    data = _exact_keys(content, where, set(CONTENT_KEYS))
    if not isinstance(data["prefab"], dict):
        raise _fail(f"{where}.prefab must be an object")
    for key in ("props", "data"):
        if not isinstance(data[key], dict):
            raise _fail(f"{where}.{key} must be an object")
    for key in ("controls", "anchors"):
        if not isinstance(data[key], list):
            raise _fail(f"{where}.{key} must be a list")
    return _copy(data)


@dataclass(frozen=True, slots=True)
class SceneVariant:
    variant_id: str
    label: str
    #: Une phrase de l'auteur : pourquoi cette alternative existe.
    rationale: str
    #: D'où elle vient : `current` (la scène avant tout ensemble) ou l'identifiant de la variante locale copiée.
    source: str
    created_by: str
    created_at: str
    #: Le contenu rangé. `None` pour la variante choisie : son contenu est la scène elle-même.
    content: dict[str, Any] | None = field(default=None)

    def __post_init__(self) -> None:
        if not is_scene_variant_id(self.variant_id):
            raise _fail("scene variant id is not a valid id (psx_...)")
        check_label(self.label)
        check_rationale(self.rationale)
        if self.source != CURRENT and not is_scene_variant_id(self.source):
            raise _fail("scene variant source must be 'current' or a scene variant id")
        if self.created_by not in _ACTORS:
            raise _fail("scene variant created_by must be 'user' or 'brain'")
        if not isinstance(self.created_at, str) or not _STAMP.fullmatch(self.created_at):
            raise _fail("scene variant created_at must be a UTC timestamp like 2026-10-07T12:00:00.000000Z")
        if self.content is not None:
            object.__setattr__(self, "content", check_content(self.content, f"scene variant {self.variant_id}.content"))

    def meta(self) -> dict[str, Any]:
        return {"variant_id": self.variant_id, "label": self.label, "rationale": self.rationale, "source": self.source,
                "created_by": self.created_by, "created_at": self.created_at}

    def to_dict(self) -> dict[str, Any]:
        wire = self.meta()
        if self.content is not None:
            wire["content"] = _copy(self.content)
        return wire

    @classmethod
    def from_dict(cls, raw: object, where: str = "scene variant") -> SceneVariant:
        data = _exact_keys(raw, where, {"variant_id", "label", "rationale", "source", "created_by", "created_at"},
                           frozenset({"content"}))
        return cls(data["variant_id"], data["label"], data["rationale"], data["source"], data["created_by"],
                   data["created_at"], data.get("content"))


@dataclass(frozen=True, slots=True)
class SceneVariantSet:
    """L'ensemble des variantes locales d'une scène : 2 à `MAX_SCENE_VARIANTS`, dont exactement une choisie."""

    current_id: str
    items: tuple[SceneVariant, ...]

    def __post_init__(self) -> None:
        items = tuple(self.items)
        object.__setattr__(self, "items", items)
        if not all(isinstance(item, SceneVariant) for item in items):
            raise _fail("scene variants must be SceneVariant values")
        if not 2 <= len(items) <= MAX_SCENE_VARIANTS:
            raise _fail(f"a scene variant set holds 2..{MAX_SCENE_VARIANTS} variants (a scene with one has no set)")
        ids = [item.variant_id for item in items]
        if len(set(ids)) != len(ids):
            raise _fail("a scene holds the same scene variant twice")
        labels = [item.label.casefold() for item in items]
        if len(set(labels)) != len(labels):
            raise PresentationStudioError(C.ALREADY_EXISTS, "two scene variants of one scene cannot share a label")
        if self.current_id not in ids:
            raise _fail("the selected scene variant is not in the set")
        for item in items:
            if (item.variant_id == self.current_id) != (item.content is None):
                raise _fail("exactly the selected scene variant has no stored content (its content is the scene)")
        size = len(canonical_json(self.to_dict()).encode("utf-8"))
        if size > MAX_SET_BYTES:
            raise PresentationStudioError(
                C.LIMIT_REACHED, f"the scene variants of one scene take {size} bytes, at most {MAX_SET_BYTES}: delete one")

    # -- lecture

    def get(self, variant_id: str) -> SceneVariant:
        for item in self.items:
            if item.variant_id == variant_id:
                return item
        raise PresentationStudioError(C.UNKNOWN_SCENE_VARIANT, f"{variant_id} is not a variant of this scene")

    @property
    def current(self) -> SceneVariant:
        return self.get(self.current_id)

    def contents(self) -> tuple[dict[str, Any], ...]:
        """Les contenus rangés (les non choisis)."""

        return tuple(item.content for item in self.items if item.content is not None)

    def to_dict(self) -> dict[str, Any]:
        return {"current_id": self.current_id, "items": [item.to_dict() for item in self.items]}

    @classmethod
    def from_dict(cls, raw: object, where: str = "scene_variants") -> SceneVariantSet:
        data = _exact_keys(raw, where, {"current_id", "items"})
        items = data["items"]
        if not isinstance(items, list) or len(items) > MAX_SCENE_VARIANTS:
            raise _fail(f"{where}.items must be a list of at most {MAX_SCENE_VARIANTS}")
        return cls(data["current_id"], tuple(SceneVariant.from_dict(item, f"{where}.items[{i}]")
                                              for i, item in enumerate(items)))

    def summary(self) -> list[dict[str, Any]]:
        """Une ligne par variante (sans contenu) : ce que l'interface et la voix listent."""

        return [{**item.meta(), "selected": item.variant_id == self.current_id} for item in self.items]


# ------------------------------------------------------------------ transformations (pures)

def _normalise(items: tuple[SceneVariant, ...], current_id: str) -> SceneVariantSet | None:
    """Forme canonique : un seul élément = pas d'ensemble."""

    return None if len(items) == 1 else SceneVariantSet(current_id, items)


def create(existing: SceneVariantSet | None, live: Mapping[str, Any], *, label: str, rationale: str, from_id: str | None,
           actor: str, now: str, new_id: Callable[[], str] = new_scene_variant_id) -> tuple[SceneVariantSet, str]:
    """Ajoute une variante locale, copie du contenu vivant (ou d'une autre variante locale). Rend `(ensemble, nouvel id)`.

    Sans ensemble, la scène devient l'entrée « Original » (choisie) : son contenu reste la scène. La copie n'est **pas**
    choisie (la scène ne bouge pas) ; elle est rangée avec son contenu. Une copie de la variante choisie (ou de la scène)
    a pour source cette variante ; `current` n'est que la source de l'« Original »."""

    check_label(label)
    check_rationale(rationale)
    if existing is None:
        if from_id is not None:
            raise PresentationStudioError(C.UNKNOWN_SCENE_VARIANT, f"{from_id} is not a variant of this scene")
        original = SceneVariant(new_id(), ORIGINAL_LABEL, "", CURRENT, actor, now)
        items: tuple[SceneVariant, ...] = (original,)
        current_id = original.variant_id
        source_id = original.variant_id
        content = _copy(live)
    else:
        items, current_id = existing.items, existing.current_id
        if len(items) >= MAX_SCENE_VARIANTS:
            raise PresentationStudioError(
                C.LIMIT_REACHED, f"a scene holds at most {MAX_SCENE_VARIANTS} variants: delete one first")
        source = existing.get(from_id) if from_id is not None else existing.current
        source_id = source.variant_id
        content = _copy(live if source.content is None else source.content)
    fresh = SceneVariant(new_id(), label, rationale, source_id, actor, now, content)
    if any(item.variant_id == fresh.variant_id for item in items):
        raise _fail("the generated scene variant id is already used")  # pragma: no cover - 48 random bits
    return SceneVariantSet(current_id, (*items, fresh)), fresh.variant_id


def rename(existing: SceneVariantSet, variant_id: str, label: str) -> SceneVariantSet:
    check_label(label)
    existing.get(variant_id)
    return SceneVariantSet(existing.current_id, tuple(
        replace(item, label=label) if item.variant_id == variant_id else item for item in existing.items))


def select(existing: SceneVariantSet, variant_id: str, live: Mapping[str, Any]) -> tuple[SceneVariantSet, dict[str, Any]]:
    """La permutation. Rend `(ensemble, nouveau contenu vivant)` : le contenu de `variant_id` devient la scène, le contenu
    vivant prend l'emplacement de l'ancienne choisie. Aucun contenu n'est perdu ni dupliqué ; `select(ancienne)` rend
    exactement l'état de départ."""

    target = existing.get(variant_id)
    if target.variant_id == existing.current_id:
        return existing, _copy(live)
    assert target.content is not None
    items = tuple(
        replace(item, content=None) if item.variant_id == variant_id
        else replace(item, content=_copy(live)) if item.variant_id == existing.current_id else item
        for item in existing.items)
    return SceneVariantSet(variant_id, items), _copy(target.content)


def delete(existing: SceneVariantSet, variant_id: str) -> SceneVariantSet | None:
    """Retire une variante non choisie. Il ne reste que la choisie : plus d'ensemble (`None`)."""

    target = existing.get(variant_id)
    if target.variant_id == existing.current_id:
        raise PresentationStudioError(
            C.SCENE_VARIANT_PROTECTED, "the selected scene variant is the scene itself: select another one first")
    items = tuple(item for item in existing.items if item.variant_id != variant_id)
    return _normalise(items, existing.current_id)


def restore(existing: SceneVariantSet | None, incoming: Mapping[str, Any] | None) -> SceneVariantSet | None:
    """Forme d'annulation : remplace l'ensemble en bloc, **sans** toucher la scène. Permis seulement si la variante choisie
    ne change pas (sinon le contenu vivant ne correspondrait plus à son entrée : un contenu serait perdu)."""

    new = None if incoming is None else SceneVariantSet.from_dict(incoming, "scene_variants")
    if new is not None and existing is not None and new.current_id != existing.current_id:
        raise _fail("scene_variant.restore_set cannot change the selected scene variant (use scene_variant.select)")
    if new is None and existing is not None:
        return None
    return new

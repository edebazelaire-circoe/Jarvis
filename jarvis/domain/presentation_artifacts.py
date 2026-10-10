"""Source de Presentation (parent logique éditable) contre Artifacts terminaux (Remotion Slice 07).

Contrat : `docs/presentation-artifacts.md`. Pur : aucune E/S, aucune horloge.

Trois choses, trois propriétaires, jamais mélangées :

- la **source éditable** est la `Presentation` (`pst_...`, `<data_root>/presentations/`). Elle reste mutable, n'est
  **jamais** un Artifact et n'a pas de ligne de lien Board ;
- le **snapshot** est un vrai Artifact (`presentation_snapshot`), créé `pending`, terminal ensuite : une variante à une
  révision précise, figée. Il porte la provenance de sa source dans des métadonnées d'acquisition **typées** (clés fixes
  `source_*`, gelées avec l'état terminal), pas dans un blob libre ;
- les **dérivés** (MP4, image, PDF) sont des Artifacts (`presentation_video|still|pdf`) reliés par **une** relation
  `rendered_from` vers un snapshot `complete`. Leur provenance (source, variante, révisions) est celle du snapshot : une seule
  copie, donc aucune contradiction possible.

« Quels Boards montrent cette source ? » n'a qu'un propriétaire : les liens Board-artifact (`board_artifact_links`). Il
n'existe aucune seconde liste.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import re
from types import MappingProxyType
from typing import Any

from jarvis.domain.artifacts import (
    Artifact, ArtifactError, ArtifactErrorCode, ArtifactKind, ArtifactState, check_artifact_id,
)
from jarvis.domain.presentation_studio_checks import PresentationStudioError, PresentationStudioErrorCode
from jarvis.domain.presentation_studio_engine import Engine, coerce_engine
from jarvis.domain.presentation_studio_variants import VARIANT_ID

#: `Artifact.source` de tout ce que ce module crée (token court, voir `artifacts.py`).
ARTIFACT_SOURCE = "presentation.studio"
#: Valeur de `source_kind` : la seule source connue aujourd'hui.
SOURCE_KIND = "presentation"

SNAPSHOT_KIND = ArtifactKind.PRESENTATION_SNAPSHOT
SNAPSHOT_PAYLOAD_NAME = "snapshot.zip"
SNAPSHOT_MIME = "application/zip"
#: Codes d'échec posés sur un snapshot `failed` (preuve, jamais effacée).
SOURCE_STALE = "source_stale"
SOURCE_MISSING = "source_missing"
#: Essais d'un même (variante, révisions) : un snapshot `failed`/`partial` est terminal, on ouvre l'essai suivant.
MAX_SNAPSHOT_ATTEMPTS = 8

_PRESENTATION = re.compile(r"pst_([0-9a-f]{32})\Z")
_VARIANT = re.compile(r"psv_([0-9a-f]{32})\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SNAPSHOT_ID = re.compile(r"jart_ps_[0-9a-f]{32}_[0-9a-f]{32}_p[0-9]{1,10}_v[0-9]{1,10}_a[0-9]{1,2}\Z")


class RenderFormat(StrEnum):
    """Formats de dérivé. Le nom de fichier et le type MIME sont fixés ici : un seul endroit à lire."""

    MP4 = "mp4"
    STILL = "still"
    PDF = "pdf"


@dataclass(frozen=True, slots=True)
class RenderSpec:
    kind: ArtifactKind
    payload_name: str
    mime_type: str


RENDERS: Mapping[RenderFormat, RenderSpec] = MappingProxyType({
    RenderFormat.MP4: RenderSpec(ArtifactKind.PRESENTATION_VIDEO, "render.mp4", "video/mp4"),
    RenderFormat.STILL: RenderSpec(ArtifactKind.PRESENTATION_STILL, "still.png", "image/png"),
    RenderFormat.PDF: RenderSpec(ArtifactKind.PRESENTATION_PDF, "render.pdf", "application/pdf"),
})
RENDER_KINDS = frozenset(spec.kind for spec in RENDERS.values())
PRESENTATION_ARTIFACT_KINDS = frozenset({SNAPSHOT_KIND, *RENDER_KINDS})


def is_presentation_artifact(artifact: Artifact) -> bool:
    return artifact.kind in PRESENTATION_ARTIFACT_KINDS


def parse_render_format(value: object) -> RenderFormat:
    try:
        return RenderFormat(value)
    except ValueError:
        allowed = ", ".join(f.value for f in RenderFormat)
        raise PresentationStudioError(PresentationStudioErrorCode.INVALID_PRESENTATION,
                                      f"render format must be one of {allowed}") from None


# ------------------------------------------------------------------ identité navigable de la source


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Adresse stable de la source éditable : `presentation:<pst_id>` ou `presentation:<pst_id>/<psv_id>`.

    C'est la seule chose qu'une interface garde pour « ouvrir la source » ; elle survit aux révisions (elle ne nomme
    jamais une révision) et ne ressemble à aucun id d'Artifact (`jart_`), donc ne peut pas être lue comme un lien.
    """

    presentation_id: str
    variant_id: str | None = None

    def __post_init__(self) -> None:
        if not _PRESENTATION.fullmatch(str(self.presentation_id)):
            raise PresentationStudioError(PresentationStudioErrorCode.UNKNOWN_PRESENTATION, "unknown presentation id")
        if self.variant_id is not None and not _VARIANT.fullmatch(str(self.variant_id)):
            raise PresentationStudioError(PresentationStudioErrorCode.UNKNOWN_VARIANT, "unknown variant id")

    def __str__(self) -> str:
        tail = "" if self.variant_id is None else f"/{self.variant_id}"
        return f"{SOURCE_KIND}:{self.presentation_id}{tail}"

    @classmethod
    def parse(cls, value: object) -> SourceRef:
        if not isinstance(value, str) or not value.startswith(f"{SOURCE_KIND}:") or len(value) > 100:
            raise PresentationStudioError(PresentationStudioErrorCode.INVALID_PRESENTATION,
                                          "a source ref is 'presentation:<pst_id>[/<psv_id>]'")
        presentation_id, _, variant_id = value[len(SOURCE_KIND) + 1:].partition("/")
        return cls(presentation_id, variant_id or None)


def snapshot_artifact_id(presentation_id: str, variant_id: str, presentation_revision: int, variant_revision: int,
                         attempt: int = 1) -> str:
    """Id **déterministe** d'un snapshot : le même (variante, révisions) retombe sur le même Artifact (rejouable, jamais
    écrasé). `attempt` ouvre l'essai suivant quand le précédent est terminal sans être `complete`."""

    p, v = _PRESENTATION.fullmatch(str(presentation_id)), _VARIANT.fullmatch(str(variant_id))
    if p is None or v is None:
        raise PresentationStudioError(PresentationStudioErrorCode.UNKNOWN_PRESENTATION, "unknown presentation or variant id")
    for name, value, low in (("presentation_revision", presentation_revision, 1), ("variant_revision", variant_revision, 1),
                             ("attempt", attempt, 1)):
        if type(value) is not int or not low <= value <= (99 if name == "attempt" else 2**31 - 1):
            raise PresentationStudioError(PresentationStudioErrorCode.INVALID_PRESENTATION, f"{name} must be a positive integer")
    artifact_id = f"jart_ps_{p.group(1)}_{v.group(1)}_p{presentation_revision}_v{variant_revision}_a{attempt}"
    check_artifact_id(artifact_id)
    return artifact_id


# ------------------------------------------------------------------ provenance typée du snapshot


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    """Quelle source, quelle variante, quelles révisions, quel moteur : les faits que le snapshot fige."""

    presentation_id: str
    variant_id: str
    presentation_revision: int
    variant_revision: int
    engine: Engine

    def __post_init__(self) -> None:
        snapshot_artifact_id(self.presentation_id, self.variant_id, self.presentation_revision, self.variant_revision)
        object.__setattr__(self, "engine", coerce_engine(self.engine))

    @property
    def ref(self) -> SourceRef:
        return SourceRef(self.presentation_id, self.variant_id)

    def to_metadata(self) -> dict[str, Any]:
        return {"source_kind": SOURCE_KIND, "source_presentation_id": self.presentation_id,
                "source_variant_id": self.variant_id, "source_presentation_revision": self.presentation_revision,
                "source_variant_revision": self.variant_revision, "source_engine": self.engine.value}

    @classmethod
    def of_snapshot(cls, artifact: Artifact) -> SourceProvenance:
        """Relit la provenance d'un snapshot. Contradiction (autre nature, clé absente, id qui ne dit pas la même chose) :
        `invalid_artifact`, jamais réparée ni devinée."""

        if artifact.kind is not SNAPSHOT_KIND:
            raise ArtifactError(ArtifactErrorCode.INVALID_ARTIFACT,
                                f"artifact {artifact.artifact_id} is {artifact.kind.value}, not a presentation snapshot")
        meta = artifact.metadata
        try:
            if meta["source_kind"] != SOURCE_KIND:
                raise ValueError("source_kind")
            found = cls(meta["source_presentation_id"], meta["source_variant_id"], meta["source_presentation_revision"],
                        meta["source_variant_revision"], meta["source_engine"])
        except (KeyError, ValueError, TypeError, PresentationStudioError) as exc:
            raise ArtifactError(ArtifactErrorCode.INVALID_ARTIFACT,
                                f"snapshot {artifact.artifact_id} has no readable source provenance ({type(exc).__name__})") from None
        stem = snapshot_artifact_id(found.presentation_id, found.variant_id, found.presentation_revision,
                                    found.variant_revision).removesuffix("_a1")
        if not _SNAPSHOT_ID.fullmatch(artifact.artifact_id) or not artifact.artifact_id.startswith(f"{stem}_a"):
            raise ArtifactError(ArtifactErrorCode.INVALID_ARTIFACT,
                                f"snapshot {artifact.artifact_id}: its id contradicts its recorded source provenance")
        return found


def check_content_hash(value: object) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ArtifactError(ArtifactErrorCode.INVALID_ARTIFACT, "content_sha256 must be 64 lowercase hex characters")
    return value


# ------------------------------------------------------------------ gardes


def is_stale(provenance: SourceProvenance, *, presentation_revision: int, variant_revision: int) -> bool:
    """La source vivante a bougé depuis le snapshot (information d'affichage : un snapshot ne « périme » jamais)."""

    return (provenance.presentation_revision, provenance.variant_revision) != (presentation_revision, variant_revision)


def require_current(label: str, *, expected_presentation: int, expected_variant: int, live_presentation: int,
                    live_variant: int) -> None:
    """Refuse de figer une révision que la source ne porte plus. Même code que les écritures du Studio."""

    if (expected_presentation, expected_variant) != (live_presentation, live_variant):
        raise PresentationStudioError(
            PresentationStudioErrorCode.STALE_REVISION,
            f"{label} is at revision {live_presentation} (variant {live_variant}), not "
            f"{expected_presentation} (variant {expected_variant}): reload, then retry")


def check_render_origin(origin: Artifact) -> SourceProvenance:
    """Un dérivé ne se rattache qu'à un snapshot **complet** : pas d'orphelin, pas de dérivé d'un instantané inachevé."""

    if origin.kind is not SNAPSHOT_KIND:
        raise ArtifactError(ArtifactErrorCode.INVALID_RELATION,
                            f"{origin.artifact_id} is {origin.kind.value}: a render derives from a presentation snapshot only")
    if origin.state is not ArtifactState.COMPLETE:
        raise ArtifactError(ArtifactErrorCode.INVALID_RELATION,
                            f"snapshot {origin.artifact_id} is {origin.state.value}: a render needs a complete snapshot")
    return SourceProvenance.of_snapshot(origin)

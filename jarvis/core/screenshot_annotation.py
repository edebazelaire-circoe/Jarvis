"""Annotation d'une capture d'écran : une NOUVELLE capture dérivée, l'originale intacte (orbital-ui Slice 05.B, D7).

Le navigateur dessine sur une copie de l'image (canvas) et envoie le PNG obtenu ;
Core le vérifie puis l'enregistre comme un **nouvel** Artifact `screenshot`,
`metadata.annotated_from = <original>`, relation `derived_from` vers l'original,
même Session et même Context. L'original n'est jamais modifié ni réécrit ; le
supprimer ensuite est refusé tant que la dérivée existe (`artifact_has_dependents`).

Vérifications, dans l'ordre (refus `AnnotationRefused(status, code)`, rien n'est écrit) :

1. l'original existe (404 `artifact_not_found`), est une capture d'écran
   (400 `annotation_source_invalid`) et `complete` (409 `annotation_source_not_ready`) ;
2. le corps n'est pas vide (400 `annotation_empty`) et tient dans
   `MAX_ANNOTATION_BYTES` (413 `annotation_too_large`) — borne vérifiée en lisant ;
3. c'est un PNG : signature puis en-tête `IHDR` lisible (415 `annotation_not_png`) ;
4. ses dimensions sont celles de l'original (400 `annotation_dimensions_mismatch`) :
   une annotation recouvre l'image, elle ne la recadre pas.

Contrat : `docs/capture.md` › *Screenshot preview and quick actions* › Annotate ;
`docs/artifacts.md` (relation `derived_from`).
"""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Any

from jarvis.domain.artifacts import Artifact, ArtifactKind, ArtifactRelationKind, ArtifactState

#: Corps accepté : la borne d'une réponse de payload (`MAX_PAYLOAD_CHUNK_BYTES`), pour qu'une annotation se relise d'un coup.
MAX_ANNOTATION_BYTES = 8 * 1024 * 1024
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
ANNOTATION_SOURCE = "annotation"
ANNOTATION_PAYLOAD_NAME = "screenshot.png"


@dataclass(frozen=True, slots=True)
class AnnotationRefused(Exception):
    status: int
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def png_size(data: bytes) -> tuple[int, int]:
    """(largeur, hauteur) d'un PNG, lues dans son premier bloc `IHDR` ; `AnnotationRefused` 415 sinon."""

    if not data.startswith(PNG_MAGIC) or len(data) < 33 or data[12:16] != b"IHDR":
        raise AnnotationRefused(415, "annotation_not_png", "the annotation must be a PNG image")
    length, = struct.unpack(">I", data[8:12])
    width, height = struct.unpack(">II", data[16:24])
    if length != 13 or width == 0 or height == 0:
        raise AnnotationRefused(415, "annotation_not_png", "the PNG header is unreadable")
    return width, height


def check_annotation(original: Artifact, data: bytes) -> tuple[int, int]:
    """Les règles 1 à 4 de l'en-tête sur l'original et les octets reçus ; rend les dimensions."""

    if original.kind is not ArtifactKind.SCREENSHOT:
        raise AnnotationRefused(400, "annotation_source_invalid",
                                f"artifact {original.artifact_id} is a {original.kind.value}, not a screenshot")
    if original.state is not ArtifactState.COMPLETE:
        raise AnnotationRefused(409, "annotation_source_not_ready",
                                f"screenshot {original.artifact_id} is {original.state.value}, not complete")
    if not data:
        raise AnnotationRefused(400, "annotation_empty", "the annotation body is empty")
    if len(data) > MAX_ANNOTATION_BYTES:
        raise AnnotationRefused(413, "annotation_too_large",
                                f"the annotation exceeds the {MAX_ANNOTATION_BYTES}-byte bound")
    width, height = png_size(data)
    if original.width is not None and original.height is not None and (width, height) != (original.width, original.height):
        raise AnnotationRefused(400, "annotation_dimensions_mismatch",
                                f"the annotation is {width}x{height}, the screenshot is {original.width}x{original.height}")
    return width, height


async def annotate_screenshot(artifacts: Any, artifact_id: str, data: bytes) -> Artifact:
    """Vérifie puis enregistre la capture annotée ; rend le nouvel Artifact `complete`. L'original n'est que lu.

    Journal : `core.artifact.created` / `artifact.finalized` de `ArtifactService` (ids, nature, origine).
    """

    original = await artifacts.get(artifact_id)  # `artifact_not_found` (404) tel quel
    width, height = check_annotation(original, data)
    derived = await artifacts.create(
        kind=ArtifactKind.SCREENSHOT, source=ANNOTATION_SOURCE, jarvis_session_id=original.jarvis_session_id,
        context_id=original.context_id, payload_name=ANNOTATION_PAYLOAD_NAME, mime_type="image/png",
        metadata={"annotated_from": original.artifact_id},
        origins=((ArtifactRelationKind.DERIVED_FROM, original.artifact_id),))
    try:
        return await artifacts.store_payload(derived.artifact_id, data, width=width, height=height)
    except Exception:
        # Capture : la dérivée finit `failed` (code stable) ; l'original n'a jamais été touché ; la cause remonte.
        try:
            await artifacts.fail(derived.artifact_id, error_code="write_failed")
        except Exception:  # noqa: BLE001 - argued: the start-up recovery fails a pending artifact; the first cause is raised
            pass
        raise

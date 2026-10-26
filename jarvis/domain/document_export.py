"""Export explicite d'un fichier final vers le dossier de l'utilisateur (handoff jarvis-presentation-edition-v1, Slice 03).

Contrat : `docs/export.md`. Domaine pur : aucune E/S, aucun chemin absolu reçu d'un appelant.

- **Source canonique seulement** : un export désigne un Artifact (`artifact_id`) d'une classe exportable
  (`EXPORT_CLASSES`, les dérivés finaux de `presentation_artifacts.RENDERS` : MP4, image PNG, PDF de pages-images),
  jamais un chemin source. Le fichier exporté est une COPIE ; l'état interne n'est jamais déplacé.
- **Nom** : un seul composant, assaini ici (`file_stem`) ; caractères interdits par Windows, noms réservés (`CON`,
  `NUL`, `COM1`…), points et espaces finaux, `..` : tous neutralisés. L'extension vient de la classe, jamais de
  l'appelant.
- **Collision** : jamais d'écrasement ; `candidate_names` propose `nom.ext`, `nom (2).ext` … `nom (MAX_COLLISIONS).ext`.
- **Refus typés** : `ExportErrorCode`, chacun avec son statut HTTP.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any
import re
import unicodedata

from jarvis.domain.artifacts import ArtifactKind
from jarvis.domain.presentation_artifacts import RENDERS, RenderFormat

#: Sous-dossier créé dans Documents (le nom du produit, jamais localisé).
EXPORT_DIR_NAME = "Jarvis"
#: Libellé affichable de la racine par défaut : jamais le nom de l'utilisateur dans une réponse ni un journal.
DEFAULT_ROOT_LABEL = r"Documents\Jarvis"
#: Libellé d'une racine imposée par `JARVIS_EXPORT_ROOT` (tests, bac à sable, administration).
OVERRIDE_ROOT_LABEL = "JARVIS_EXPORT_ROOT"
MAX_STEM_CHARS = 80
MAX_COLLISIONS = 999
FALLBACK_STEM = "Jarvis export"
#: Suffixe du fichier temporaire écrit dans la destination avant le renommage atomique.
TEMP_SUFFIX = ".jarvis-export.partial"

_FORBIDDEN_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_RESERVED = frozenset({"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
                       *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10)),
                       "COM¹", "COM²", "COM³", "LPT¹", "LPT²", "LPT³"})
_SPACES = re.compile(r"\s+")


class ExportErrorCode(StrEnum):
    INVALID = "export_invalid"
    SOURCE_NOT_FOUND = "export_source_not_found"
    SOURCE_NOT_EXPORTABLE = "export_source_not_exportable"
    SOURCE_UNAVAILABLE = "export_source_unavailable"
    DESTINATION_UNAVAILABLE = "export_destination_unavailable"
    DESTINATION_UNSAFE = "export_destination_unsafe"
    DESTINATION_FORBIDDEN = "export_destination_forbidden"
    COLLISION_EXHAUSTED = "export_collision_exhausted"
    FAILED = "export_failed"
    UNAVAILABLE = "export_unavailable"


_STATUS: Mapping[ExportErrorCode, int] = MappingProxyType({
    ExportErrorCode.INVALID: 400,
    ExportErrorCode.SOURCE_NOT_FOUND: 404,
    ExportErrorCode.SOURCE_NOT_EXPORTABLE: 409,
    ExportErrorCode.SOURCE_UNAVAILABLE: 409,
    ExportErrorCode.DESTINATION_UNAVAILABLE: 503,
    ExportErrorCode.DESTINATION_UNSAFE: 409,
    ExportErrorCode.DESTINATION_FORBIDDEN: 409,
    ExportErrorCode.COLLISION_EXHAUSTED: 409,
    ExportErrorCode.FAILED: 500,
    ExportErrorCode.UNAVAILABLE: 503,
})


class ExportError(Exception):
    """Refus ou échec typé d'un export. `detail` est en anglais, sans chemin absolu de l'utilisateur."""

    def __init__(self, code: ExportErrorCode, detail: str) -> None:
        super().__init__(f"{code.value}: {detail}")
        self.code = code
        self.detail = detail[:300]

    @property
    def status(self) -> int:
        return _STATUS[self.code]


@dataclass(frozen=True, slots=True)
class ExportClass:
    """Une classe de fichier exportable : nature d'Artifact, format, extension et type MIME (repris de `RENDERS`)."""

    kind: ArtifactKind
    format: str
    extension: str
    mime_type: str
    payload_name: str
    label: str


def _classes() -> Mapping[ArtifactKind, ExportClass]:
    labels = {RenderFormat.MP4: "video", RenderFormat.STILL: "image", RenderFormat.PDF: "pdf"}
    out: dict[ArtifactKind, ExportClass] = {}
    for fmt, spec in RENDERS.items():
        extension = "." + spec.payload_name.rsplit(".", 1)[1]
        out[spec.kind] = ExportClass(spec.kind, fmt.value, extension, spec.mime_type, spec.payload_name, labels[fmt])
    return MappingProxyType(out)


#: Classes exportables en V1 : MP4, image PNG, PDF de pages-images (pas de PPTX, `docs/export.md` › *Classes*).
EXPORT_CLASSES: Mapping[ArtifactKind, ExportClass] = _classes()


def export_class_of(kind: ArtifactKind) -> ExportClass:
    found = EXPORT_CLASSES.get(kind)
    if found is None:
        allowed = ", ".join(sorted(k.value for k in EXPORT_CLASSES))
        raise ExportError(ExportErrorCode.SOURCE_NOT_EXPORTABLE,
                          f"an artifact of kind {kind.value} is internal state, not an exportable file (exportable: {allowed})")
    return found


def file_stem(raw: object) -> str:
    """Un seul composant de nom de fichier sûr sous Windows (et POSIX), ou `FALLBACK_STEM`.

    Séparateurs, `..`, caractères interdits et de contrôle remplacés ; espaces repliés ; points et espaces finaux
    retirés ; un nom réservé de Windows reçoit un `_` ; borné à `MAX_STEM_CHARS`.
    """

    text = unicodedata.normalize("NFC", str(raw or ""))
    # Format characters (Cf: U+202E right-to-left override, zero-width joiners...) would disguise the visible name or extension.
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    text = _FORBIDDEN_CHARS.sub(" ", text)
    text = _SPACES.sub(" ", text).strip()
    text = text[:MAX_STEM_CHARS].strip().rstrip(". ").lstrip(". ")
    if not text or set(text) <= {"."}:
        return FALLBACK_STEM
    if text.split(".", 1)[0].upper().rstrip() in _RESERVED:
        text = "_" + text
    return text


def candidate_names(stem: str, extension: str) -> Iterator[str]:
    """`stem.ext`, puis `stem (2).ext` … `stem (MAX_COLLISIONS).ext` : la première libre gagne, rien n'est écrasé."""

    yield f"{stem}{extension}"
    for n in range(2, MAX_COLLISIONS + 1):
        yield f"{stem} ({n}){extension}"


def default_stem(title: str | None, export_class: ExportClass) -> str:
    """Nom proposé quand l'appelant n'en donne pas : `<titre de la présentation> - <classe>`."""

    base = file_stem(title) if title else FALLBACK_STEM
    return file_stem(f"{base} - {export_class.label}")


@dataclass(frozen=True, slots=True)
class ExportResult:
    """Ce que l'utilisateur a obtenu. Information seulement : jamais relu comme source (`docs/export.md` › *Not canonical*)."""

    artifact_id: str
    format: str
    file_name: str
    root_label: str
    size_bytes: int
    sha256: str
    exported_at: str
    renamed: bool
    #: The same bytes already sat under one of this export's names: nothing was copied (no flood of copies).
    already_exported: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"artifact_id": self.artifact_id, "format": self.format, "file_name": self.file_name,
                "destination": {"root": self.root_label, "display_path": f"{self.root_label}\\{self.file_name}"},
                "size_bytes": self.size_bytes, "sha256": self.sha256, "exported_at": self.exported_at,
                "renamed": self.renamed, "already_exported": self.already_exported, "copy": True}

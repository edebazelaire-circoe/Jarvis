"""Contrat pur du **Dossier** d'un Board (handoff jarvis-board-ui-wheel-dossier-refactor, Slice 05).

Le Dossier est une **projection**, jamais un magasin : la mémoire du Board
(`boards/<id>/memory/`, `jarvis/domain/board_memory.py`) et les Artifacts du
registre liés au Board (`board_artifact_links`, v8) vus comme une seule liste
d'entrées lisibles par un humain. Aucune table, aucune copie : chaque entrée
désigne sa source canonique par un `entry_id` stable.

Ce module, sans E/S, fixe :

- l'identité d'une entrée : `memory:<chemin relatif>` ou `artifact:<jart_…>`
  (`DossierEntryRef`), validée avec les règles des propriétaires
  (`BoardMemoryPath`, `check_artifact_id`) ;
- la nature humaine d'une entrée (`note`, `image`, `transcript`…) et son mode
  d'ouverture (`text`, `media`, `link`, `none`), dérivés de la source, jamais
  inventés ;
- la **source durable d'un objet de scène** (`classify_scene_object`) : lien
  vers un Artifact du registre (`payload.registry_artifact_id`), fichier lié
  (`payload.source_path`, à situer par le service), contenu éphémère à ranger
  une fois, ou refus nommé (nœud d'exécution, signal, groupe, fenêtre prefab,
  contenu vide) ;
- la forme Markdown d'un contenu rangé (avec sa provenance) et son chemin
  déterministe dans la mémoire (un second Ranger du même objet retrouve le
  même fichier au lieu d'en créer un autre).

Piège de vocabulaire : un *artefact de scène* (`kind=artifact`, titre/résumé/
entrées, vit dans la scène) n'est **pas** un *Artifact du registre* (table
`artifacts`). Contrat : `docs/dossier.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
from pathlib import PurePosixPath
import re
import unicodedata

from jarvis.domain.artifacts import ArtifactKind, check_artifact_id
from jarvis.domain.board_memory import MEMORY_SUMMARY_NAME, BoardMemoryPath
from jarvis.domain.scene import SceneObject, SceneObjectKind

#: Préfixes d'`entry_id`.
MEMORY_PREFIX = "memory:"
ARTIFACT_PREFIX = "artifact:"
MAX_ENTRY_ID_CHARS = 260
#: Liste du Dossier : entrées par réponse, et parcours borné de la mémoire.
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 100
MEMORY_SCAN_DEPTH = 8
MEMORY_SCAN_ENTRIES = 1000
#: Artifacts liés lus au plus pour une liste (les plus récemment liés).
MAX_LINKED_SCAN = 100
#: Objets de scène par Ranger / par résolution (une sélection de l'interface ou du cerveau).
MAX_RANGER_OBJECTS = 20
#: Dossier où un contenu éphémère rangé est écrit, dans la mémoire du Board.
RANGER_FOLDER = "notes"
MAX_SLUG_CHARS = 48
#: Catégorie d'une représentation posée par « Afficher sur le Board ».
PRESENT_CATEGORY = "dossier"


class DossierCode(StrEnum):
    """Refus stables du Dossier (en plus des codes des propriétaires : `board_*`, `memory_*`, `artifact_*`)."""

    ENTRY_INVALID = "dossier_entry_invalid"
    ENTRY_NOT_FOUND = "dossier_entry_not_found"
    #: Ranger / Afficher sur le Board visent la scène affichée : seulement le Board actif.
    BOARD_NOT_ACTIVE = "dossier_board_not_active"
    SCENE_UNAVAILABLE = "scene_unavailable"
    #: Par objet (Ranger, résolution).
    OBJECT_NOT_FOUND = "dossier_object_not_found"
    NOT_ELIGIBLE = "dossier_not_eligible"
    NOTHING_TO_KEEP = "dossier_nothing_to_keep"
    SOURCE_OUTSIDE_BOARD = "dossier_source_outside_board"
    SOURCE_MISSING = "dossier_source_missing"
    #: Le contenu a changé entre la mise en Dossier et le retrait : la représentation reste.
    CHANGED_MEANWHILE = "dossier_changed_meanwhile"
    #: La source durable est confirmée, mais la scène a refusé le retrait : la représentation reste.
    ARCHIVE_FAILED = "dossier_archive_failed"


class DossierError(ValueError):
    """Refus du Dossier : code stable et statut HTTP (même forme que `WorkspaceError`)."""

    def __init__(self, code: DossierCode, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class EntrySource(StrEnum):
    MEMORY = "memory"
    ARTIFACT = "artifact"


@dataclass(frozen=True, slots=True)
class DossierEntryRef:
    """Identité d'une entrée : sa source canonique, jamais une copie."""

    source: EntrySource
    key: str

    @property
    def entry_id(self) -> str:
        return (MEMORY_PREFIX if self.source is EntrySource.MEMORY else ARTIFACT_PREFIX) + self.key

    @classmethod
    def memory(cls, path: str) -> DossierEntryRef:
        return cls(EntrySource.MEMORY, path)

    @classmethod
    def artifact(cls, artifact_id: str) -> DossierEntryRef:
        return cls(EntrySource.ARTIFACT, artifact_id)

    @classmethod
    def parse(cls, value: object) -> DossierEntryRef:
        """`memory:<chemin>` (règles de `BoardMemoryPath`) ou `artifact:<jart_…>` ; `dossier_entry_invalid` sinon."""

        if not isinstance(value, str) or not value or len(value) > MAX_ENTRY_ID_CHARS:
            raise DossierError(DossierCode.ENTRY_INVALID,
                               f"entry_id must be 'memory:<path>' or 'artifact:<jart_…>' (<= {MAX_ENTRY_ID_CHARS} chars)")
        if value.startswith(MEMORY_PREFIX):
            try:
                path = BoardMemoryPath.parse(value[len(MEMORY_PREFIX):])
            except ValueError as exc:
                raise DossierError(DossierCode.ENTRY_INVALID, f"entry_id: {exc}") from None
            return cls.memory(path.value)
        if value.startswith(ARTIFACT_PREFIX):
            artifact_id = value[len(ARTIFACT_PREFIX):]
            try:
                check_artifact_id(artifact_id)
            except ValueError as exc:
                raise DossierError(DossierCode.ENTRY_INVALID, f"entry_id: {exc}") from None
            return cls.artifact(artifact_id)
        raise DossierError(DossierCode.ENTRY_INVALID, "entry_id must start with 'memory:' or 'artifact:'")


# ------------------------------------------------------------------ nature et ouverture


class EntryKind(StrEnum):
    MEMORY_SUMMARY = "memory_summary"
    NOTE = "note"
    DOCUMENT = "document"
    IMAGE = "image"
    MEDIA = "media"
    TRANSCRIPT = "transcript"
    REPORT = "report"
    PRESENTATION = "presentation"
    LINK = "link"
    FILE = "file"


class OpenMode(StrEnum):
    """Comment l'interface ouvre l'entrée, d'après ce que le propriétaire sait servir."""

    #: Texte UTF-8 : `memory/read` (mémoire) ou `text` de l'Artifact.
    TEXT = "text"
    #: Octets d'un payload d'Artifact (`/api/artifacts/{id}/payload`).
    MEDIA = "media"
    #: URL d'un Artifact `link`, jamais récupérée par Jarvis.
    LINK = "link"
    #: Rien d'ouvrable ici (fichier binaire de la mémoire) : l'entrée est dite, pas montrée.
    NONE = "none"


_NOTE_SUFFIXES = frozenset({".md", ".markdown", ".txt"})
_TEXT_SUFFIXES = frozenset({".json", ".csv", ".tsv", ".yaml", ".yml", ".html", ".htm", ".xml", ".log", ".ini",
                            ".toml", ".py", ".js", ".ts", ".css", ".sql"})
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"})
_MEDIA_SUFFIXES = frozenset({".mp3", ".wav", ".m4a", ".ogg", ".mp4", ".webm", ".mov"})


def memory_entry_kind(path: str) -> tuple[EntryKind, OpenMode]:
    """Nature et ouverture d'un fichier de la mémoire, par son nom (le magasin ne sert que du texte)."""

    name = PurePosixPath(path)
    if str(name).casefold() == MEMORY_SUMMARY_NAME:
        return EntryKind.MEMORY_SUMMARY, OpenMode.TEXT
    suffix = name.suffix.casefold()
    if suffix in _NOTE_SUFFIXES:
        return EntryKind.NOTE, OpenMode.TEXT
    if suffix in _TEXT_SUFFIXES:
        return EntryKind.DOCUMENT, OpenMode.TEXT
    if suffix in _IMAGE_SUFFIXES:
        return EntryKind.IMAGE, OpenMode.NONE
    if suffix in _MEDIA_SUFFIXES:
        return EntryKind.MEDIA, OpenMode.NONE
    return EntryKind.FILE, OpenMode.NONE


def memory_entry_title(path: str) -> str:
    name = PurePosixPath(path)
    if str(name).casefold() == MEMORY_SUMMARY_NAME:
        return "Résumé du Board"
    return name.stem or name.name


_ARTIFACT_KINDS: dict[ArtifactKind, EntryKind] = {
    ArtifactKind.AUDIO_RECORDING: EntryKind.MEDIA,
    ArtifactKind.SCREEN_RECORDING: EntryKind.MEDIA,
    ArtifactKind.PRESENTATION_VIDEO: EntryKind.MEDIA,
    ArtifactKind.SCREENSHOT: EntryKind.IMAGE,
    ArtifactKind.PRESENTATION_STILL: EntryKind.IMAGE,
    ArtifactKind.TRANSCRIPT: EntryKind.TRANSCRIPT,
    ArtifactKind.TRANSCRIPT_SEGMENT: EntryKind.TRANSCRIPT,
    ArtifactKind.DESCRIPTION: EntryKind.REPORT,
    ArtifactKind.DERIVED: EntryKind.REPORT,
    ArtifactKind.PRESENTATION_SNAPSHOT: EntryKind.PRESENTATION,
    ArtifactKind.PRESENTATION_PDF: EntryKind.DOCUMENT,
    ArtifactKind.LINK: EntryKind.LINK,
}
#: Libellé humain d'un Artifact sans nom propre (ni fichier donné, ni URL).
_ARTIFACT_LABELS: dict[ArtifactKind, str] = {
    ArtifactKind.AUDIO_RECORDING: "Enregistrement audio",
    ArtifactKind.TRANSCRIPT_SEGMENT: "Extrait de transcription",
    ArtifactKind.TRANSCRIPT: "Transcription",
    ArtifactKind.SCREENSHOT: "Capture d'écran",
    ArtifactKind.SCREEN_RECORDING: "Enregistrement d'écran",
    ArtifactKind.DESCRIPTION: "Description",
    ArtifactKind.DERIVED: "Synthèse",
    ArtifactKind.PRESENTATION_SNAPSHOT: "Présentation figée",
    ArtifactKind.PRESENTATION_VIDEO: "Vidéo de présentation",
    ArtifactKind.PRESENTATION_STILL: "Image de présentation",
    ArtifactKind.PRESENTATION_PDF: "PDF de présentation",
    ArtifactKind.UPLOAD: "Fichier",
    ArtifactKind.LINK: "Lien",
}


def artifact_entry_kind(kind: ArtifactKind, *, mime_type: str | None, has_payload: bool,
                        has_text: bool) -> tuple[EntryKind, OpenMode]:
    """Nature et ouverture d'un Artifact du registre ; un fichier donné se lit par son type MIME."""

    if kind is ArtifactKind.UPLOAD:
        mime = (mime_type or "").casefold()
        entry = (EntryKind.IMAGE if mime.startswith("image/") else EntryKind.MEDIA
                 if mime.startswith(("audio/", "video/")) else EntryKind.DOCUMENT)
    else:
        entry = _ARTIFACT_KINDS.get(kind, EntryKind.FILE)
    if kind is ArtifactKind.LINK:
        return entry, OpenMode.LINK
    if has_payload:
        return entry, OpenMode.MEDIA
    return entry, OpenMode.TEXT if has_text else OpenMode.NONE


def artifact_entry_title(kind: ArtifactKind, *, original_name: object, text: str | None,
                         created_at: datetime) -> str:
    """Nom propre si la source en a un (fichier donné, URL) ; sinon un libellé daté, jamais l'identifiant."""

    if kind is ArtifactKind.UPLOAD and isinstance(original_name, str) and original_name.strip():
        return original_name.strip()[:160]
    if kind is ArtifactKind.LINK and text:
        return text.strip()[:160]
    label = _ARTIFACT_LABELS.get(kind, "Artifact")
    return f"{label} du {created_at.astimezone().strftime('%d/%m/%Y %H:%M')}"


# ------------------------------------------------------------------ source durable d'un objet de scène


class BackingKind(StrEnum):
    #: `payload.registry_artifact_id` : un Artifact du registre ; Ranger confirme (et pose) le lien au Board.
    ARTIFACT = "artifact"
    #: `payload.source_path` : un fichier ; le service dit s'il est dans la mémoire de ce Board.
    FILE = "file"
    #: Contenu affiché seulement dans la scène (artefact de scène, note, fenêtre) : rangé une fois en Markdown.
    CONTENT = "content"
    #: Refus nommé (`code`) : rien n'est rangé, la représentation reste.
    REFUSED = "refused"


@dataclass(frozen=True, slots=True)
class SceneBacking:
    kind: BackingKind
    artifact_id: str = ""
    source_path: str = ""
    code: DossierCode | None = None
    reason: str = ""


#: Natures qui ne portent pas un contenu à ranger : exécution (étoiles), signaux, groupes.
_NOT_CONTENT = {
    SceneObjectKind.AGENT: "un nœud d'exécution (étoile d'agent) n'est pas un contenu",
    SceneObjectKind.JOB: "un nœud d'exécution (tâche) n'est pas un contenu",
    SceneObjectKind.ATTENTION: "un signal d'attention n'est pas un contenu",
    SceneObjectKind.GROUP: "un groupe n'est qu'un cadre : rangez ses objets un par un",
}


def classify_scene_object(item: SceneObject) -> SceneBacking:
    """Source durable d'une représentation : lien explicite d'abord, puis fichier lié, puis contenu à ranger."""

    payload = item.payload
    if payload.registry_artifact_id:
        return SceneBacking(BackingKind.ARTIFACT, artifact_id=payload.registry_artifact_id)
    if payload.source_path:
        return SceneBacking(BackingKind.FILE, source_path=payload.source_path)
    if item.kind in _NOT_CONTENT:
        return SceneBacking(BackingKind.REFUSED, code=DossierCode.NOT_ELIGIBLE, reason=_NOT_CONTENT[item.kind])
    if payload.prefab is not None:
        return SceneBacking(BackingKind.REFUSED, code=DossierCode.NOT_ELIGIBLE,
                            reason="une fenêtre prefab est une interface, pas un document")
    if not (payload.title.strip() or payload.summary.strip() or payload.items):
        return SceneBacking(BackingKind.REFUSED, code=DossierCode.NOTHING_TO_KEEP,
                            reason="l'objet n'a ni titre, ni texte, ni entrée")
    return SceneBacking(BackingKind.CONTENT)


def _slug(title: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii").casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")[:MAX_SLUG_CHARS].strip("-")
    return slug or "note"


def ranger_path(item: SceneObject, *, content_variant: bool = False) -> BoardMemoryPath:
    """Chemin déterministe du contenu rangé : `notes/<titre>-<empreinte de l'objet>.md`.

    L'empreinte vient de l'`object_id` (stable pour toute la vie de l'objet) : un second Ranger du même objet
    après un retrait refusé retrouve ce fichier (`memory_exists`) au lieu d'en écrire un second. Si ce fichier
    porte un **autre** corps que celui affiché (contenu modifié depuis, même titre), `content_variant=True`
    donne le chemin propre à ce corps : `notes/<titre>-<objet>-<empreinte du corps>.md`. L'ancien fichier
    n'est jamais écrasé, et un même corps retombe toujours sur le même chemin.
    """

    digest = hashlib.sha256(item.object_id.encode("utf-8")).hexdigest()[:8]
    suffix = ""
    if content_variant:
        suffix = "-" + hashlib.sha256(ranger_body(item).encode("utf-8")).hexdigest()[:8]
    return BoardMemoryPath.parse(f"{RANGER_FOLDER}/{_slug(item.payload.title)}-{digest}{suffix}.md")


#: Début du pied de provenance écrit par `ranger_markdown` (ligne `---` puis cette phrase).
_FOOTER_MARK = "\n---\nRangé depuis le Board le "


def ranger_body(item: SceneObject) -> str:
    """Le corps rangé (titre, texte, entrées), sans pied de provenance : ce qui se compare d'un Ranger à l'autre."""

    payload = item.payload
    lines: list[str] = []
    if payload.title.strip():
        lines += [f"# {payload.title.strip()}", ""]
    if payload.summary.strip():
        lines += [payload.summary.rstrip(), ""]
    for entry in payload.items:
        target = entry.url or entry.ref
        lines.append(f"- {entry.label}" + (f" ({target})" if target else ""))
    if payload.items:
        lines.append("")
    return "\n".join(lines)


def stored_body(text: str) -> str:
    """Le corps d'un fichier déjà rangé : tout ce qui précède le **dernier** pied de provenance."""

    cut = text.rfind(_FOOTER_MARK)
    return text if cut < 0 else text[:cut]


def ranger_markdown(item: SceneObject, *, stored_at: datetime, origin: str) -> str:
    """Le contenu de la représentation, une fois, en Markdown ; la provenance en pied (lisible, puis machine)."""

    lines = [ranger_body(item)] if ranger_body(item) else []
    who = "par Jarvis" if origin == "brain" else "par vous"
    lines += ["---", f"Rangé depuis le Board le {stored_at.astimezone().strftime('%d/%m/%Y à %H:%M')}, {who}.",
              f"<!-- jarvis:dossier object_id={item.object_id} kind={item.kind.value} category={item.category} "
              f"origin={origin} stored_at={stored_at.isoformat()} -->", ""]
    return "\n".join(lines)


__all__ = [
    "ARTIFACT_PREFIX", "BackingKind", "DEFAULT_LIST_LIMIT", "DossierCode", "DossierEntryRef", "DossierError",
    "EntryKind", "EntrySource", "MAX_LINKED_SCAN", "MAX_LIST_LIMIT", "MAX_RANGER_OBJECTS", "MEMORY_PREFIX",
    "MEMORY_SCAN_DEPTH", "MEMORY_SCAN_ENTRIES", "OpenMode", "PRESENT_CATEGORY", "RANGER_FOLDER", "SceneBacking",
    "artifact_entry_kind", "artifact_entry_title", "classify_scene_object", "memory_entry_kind",
    "memory_entry_title", "ranger_body", "ranger_markdown", "ranger_path", "stored_body",
]

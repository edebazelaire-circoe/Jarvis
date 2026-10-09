"""Références vivantes d'une scène Remotion vers un Board (Remotion Slice 09). Pur : aucune E/S, aucune horloge.

Contrat : `docs/presentation-live-refs.md`. Pendant l'édition, une scène désigne des éléments de Board par une
**référence validée** (jamais un chemin libre) ; la résolution se fait côté Core (`jarvis/core/presentation_live_refs.py`)
et seules des **données résolues** passent au bac à sable (`sandbox_payload`). Au gel, les mêmes références sont résolues
une dernière fois et **copiées** dans le paquet (`presentation_snapshot_package.py`).

Une scène déclare ses références dans `src/live-refs.json` (un module JSON ordinaire de sa source : il voyage avec le pin,
il est donc figé avec lui, et le Studio n'a aucun schéma de plus) :

    {"format": "jarvis.live-refs/1", "refs": [{"name": "notes", "ref": "board:board_x/memory/notes/a.md"},
                                              {"name": "photo", "ref": "board:board_x/artifact/jart_..."}]}

Grammaire d'une référence : `board:<board_id>/memory/<chemin de mémoire>` (texte) ou `board:<board_id>/artifact/<jart_id>`
(artefact complet lié à ce Board). Rien d'autre : ni URL, ni chemin disque, ni `presentation:`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import json
import re
from typing import Any

from jarvis.domain.artifacts import ArtifactError, ArtifactKind, check_artifact_id
from jarvis.domain.board_memory import BoardMemoryError, BoardMemoryPath
from jarvis.domain.workspace_board import BOARD_ID_PREFIX, DEFAULT_BOARD_ID

LIVE_REFS_PATH = "src/live-refs.json"
LIVE_REFS_FORMAT = "jarvis.live-refs/1"
MAX_REFS_PER_SOURCE = 32
MAX_DECLARATION_BYTES = 16 * 1024
#: Même grammaire que les noms du protocole du bac à sable (`remotion_sandbox_protocol.js`, `NAME`).
NAME = re.compile(r"[a-z][a-z0-9_]{0,39}\Z")
_BOARD = re.compile(r"(?:board_[a-z0-9_-]{1,100}|" + re.escape(DEFAULT_BOARD_ID) + r")\Z")
_REF = re.compile(r"board:([^/]{1,128})/(memory|artifact)/(.{1,300})\Z", re.S)

#: Bornes d'un élément résolu et d'un ensemble (ce qui entre dans un paquet ou dans un message).
MAX_TEXT_BYTES = 256 * 1024
MAX_BINARY_BYTES = 4 * 1024 * 1024
MAX_SET_BYTES = 16 * 1024 * 1024
#: Un message vers le bac à sable ne porte du texte en ligne que sous cette borne (`maxPropsBytes` du protocole = 64 Kio).
MAX_INLINE_TEXT_BYTES = 24 * 1024
MAX_INLINE_TOTAL_BYTES = 48 * 1024

TEXT_MEMORY_SUFFIXES = frozenset({".txt", ".md", ".json", ".csv"})
#: mime -> extension du fichier copié dans le paquet. Pas de SVG (contenu actif), pas d'audio ni de vidéo.
BINARY_MIMES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
TEXT_MIMES = {"text/plain": ".txt", "text/markdown": ".md", "application/json": ".json", "text/csv": ".csv"}
#: Natures d'artefact lisibles. Un artefact de présentation (instantané, rendu) n'est jamais un élément de scène :
#: c'est ce qui ferme la référence entre présentations.
ALLOWED_ARTIFACT_KINDS = frozenset({
    ArtifactKind.SCREENSHOT, ArtifactKind.DESCRIPTION, ArtifactKind.DERIVED, ArtifactKind.TRANSCRIPT,
    ArtifactKind.TRANSCRIPT_SEGMENT})
_SIGNATURES = {
    "image/png": lambda head: head.startswith(b"\x89PNG\r\n\x1a\n"),
    "image/jpeg": lambda head: head.startswith(b"\xff\xd8\xff"),
    "image/webp": lambda head: head[:4] == b"RIFF" and head[8:12] == b"WEBP",
    "image/gif": lambda head: head[:6] in (b"GIF87a", b"GIF89a"),
}


class LiveRefErrorCode(StrEnum):
    INVALID = "live_ref_invalid"            # déclaration ou référence mal formée
    UNKNOWN = "live_ref_unknown"            # nom que la scène ne déclare pas
    UNRESOLVED = "live_ref_unresolved"      # au gel : au moins une référence n'est pas `ok`
    CROSS_PRESENTATION = "live_ref_cross_presentation"
    NOT_AUTHORISED = "live_ref_not_authorised"  # au moins une référence vise un Board que l'appelant n'a pas autorisé
    PACKAGE_FAILED = "package_failed"           # écriture du paquet impossible (le snapshot est `failed`)
    PACKAGE_INVALID = "snapshot_package_invalid"
    PACKAGE_TOO_LARGE = "snapshot_package_too_large"


class LiveRefError(ValueError):
    """Refus typé ; `details` = les références en cause (`[{name, ref, state, message}]`), jamais de chemin disque."""

    def __init__(self, code: LiveRefErrorCode, message: str, *, details: tuple[Mapping[str, Any], ...] = ()) -> None:
        super().__init__(message)
        self.code = LiveRefErrorCode(code)
        self.details = details


class LiveRefState(StrEnum):
    """État visible d'une référence. Seul `ok` (et `changed` pendant l'édition) porte des données."""

    OK = "ok"
    CHANGED = "changed"                # édition : le contenu n'est plus celui qu'on avait vu (`expected_sha256`) : périmé
    MISSING = "missing"                # l'élément n'existe plus (fichier de mémoire supprimé, artefact supprimé)
    BOARD_MISSING = "board_missing"    # le Board n'existe plus
    NOT_ON_BOARD = "not_on_board"      # l'artefact existe mais n'est (plus) lié à ce Board
    NOT_READY = "not_ready"            # artefact pas `complete`
    NOT_ALLOWED = "not_allowed"        # nature ou type de contenu hors liste, signature fausse
    TOO_LARGE = "too_large"
    NOT_TEXT = "not_text"
    UNREADABLE = "unreadable"          # erreur d'E/S ou de magasin : dite, jamais devinée
    #: Board hors de la liste blanche de l'appelant (refus par défaut). Même état que le Board soit absent ou interdit :
    #: l'existence d'un Board non autorisé ne se devine pas. Rien n'est lu.
    NOT_AUTHORISED = "not_authorised"


#: États qui portent des octets valides.
USABLE = frozenset({LiveRefState.OK, LiveRefState.CHANGED})


@dataclass(frozen=True, slots=True)
class LiveRef:
    name: str
    kind: str          # "memory" | "artifact"
    board_id: str
    locator: str       # chemin de mémoire ou id d'artefact

    def __str__(self) -> str:
        return f"board:{self.board_id}/{self.kind}/{self.locator}"


def parse_live_ref(name: object, value: object) -> LiveRef:
    """Une référence ou `LiveRefError(INVALID)`. Le chemin de mémoire passe par `BoardMemoryPath` (échappement, `..`,
    antislash, noms Windows), l'id d'artefact par `check_artifact_id`."""

    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise _bad(f"live reference name must match {NAME.pattern}, got {_p(name)}")
    if not isinstance(value, str):
        raise _bad(f"{name}: reference must be a string, got {_p(value)}")
    if value.startswith("presentation:") or value.startswith("jart_ps_"):
        raise LiveRefError(LiveRefErrorCode.CROSS_PRESENTATION, f"{name}: a presentation is not a Board item")
    match = _REF.fullmatch(value)
    if match is None:
        raise _bad(f"{name}: expected board:<board_id>/memory/<path> or board:<board_id>/artifact/<id>, got {_p(value)}")
    board_id, kind, locator = match.groups()
    if not _BOARD.fullmatch(board_id) or not (board_id == DEFAULT_BOARD_ID or board_id.startswith(BOARD_ID_PREFIX)):
        raise _bad(f"{name}: invalid board id {_p(board_id)}")
    try:
        if kind == "memory":
            locator = BoardMemoryPath.parse(locator).value
        else:
            check_artifact_id(locator)
            if locator.startswith("jart_ps_"):
                raise LiveRefError(LiveRefErrorCode.CROSS_PRESENTATION, f"{name}: a presentation snapshot is not a Board item")
    except (BoardMemoryError, ArtifactError) as exc:
        raise _bad(f"{name}: {exc}") from None
    return LiveRef(name, kind, board_id, locator)


def parse_declaration(data: bytes) -> tuple[LiveRef, ...]:
    """`src/live-refs.json` -> références (exactement les clés connues, noms uniques, bornes). Rien n'est lu ailleurs."""

    if len(data) > MAX_DECLARATION_BYTES:
        raise _bad(f"{LIVE_REFS_PATH} is {len(data)} bytes, at most {MAX_DECLARATION_BYTES}")
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise _bad(f"{LIVE_REFS_PATH} is not UTF-8 JSON") from None
    if not isinstance(doc, dict) or set(doc) != {"format", "refs"} or doc["format"] != LIVE_REFS_FORMAT:
        raise _bad(f"{LIVE_REFS_PATH} must be {{\"format\": \"{LIVE_REFS_FORMAT}\", \"refs\": [...]}}")
    refs = doc["refs"]
    if not isinstance(refs, list) or len(refs) > MAX_REFS_PER_SOURCE:
        raise _bad(f"refs must be a list of at most {MAX_REFS_PER_SOURCE}")
    parsed: list[LiveRef] = []
    for item in refs:
        if not isinstance(item, dict) or set(item) != {"name", "ref"}:
            raise _bad("each ref is exactly {name, ref}")
        parsed.append(parse_live_ref(item["name"], item["ref"]))
    if len({ref.name for ref in parsed}) != len(parsed):
        raise _bad("two references share a name")
    return tuple(parsed)


@dataclass(frozen=True, slots=True)
class ResolvedLiveRef:
    """Résultat typé d'une résolution. `data` n'existe que pour `ok`/`changed` ; `message` ne contient jamais de chemin disque."""

    ref: LiveRef
    state: LiveRefState
    message: str = ""
    mime: str | None = None
    data: bytes | None = None
    sha256: str | None = None

    @property
    def usable(self) -> bool:
        return self.state in USABLE and self.data is not None

    @property
    def is_text(self) -> bool:
        return self.mime is not None and (self.mime in TEXT_MIMES or self.mime.startswith("text/"))

    @property
    def extension(self) -> str:
        return {**BINARY_MIMES, **TEXT_MIMES}.get(self.mime or "", ".bin")

    def status(self) -> dict[str, Any]:
        """Ce qu'un écran ou un journal peut montrer : aucune donnée, aucun chemin."""

        return {"name": self.ref.name, "ref": str(self.ref), "state": self.state.value, "message": self.message,
                "mime": self.mime, "size": None if self.data is None else len(self.data), "sha256": self.sha256}


def binary_signature_ok(mime: str, data: bytes) -> bool:
    check = _SIGNATURES.get(mime)
    return check is not None and check(data[:16])


def sandbox_payload(resolved: Mapping[str, ResolvedLiveRef], *, static_prefix: str = "live") -> dict[str, Any]:
    """Les **données résolues** qu'un message `props` du bac à sable peut porter (JSON simple, bornes du protocole).

    `{name: {"state", "mime", "size", "sha256", "text"?, "file"?}}` : un texte court est en ligne ; un texte long ou un binaire
    est annoncé par `file` (`<static_prefix>/<name><ext>`, à servir sous `public/` par l'hôte : Slice 10) et jamais embarqué.
    Aucune référence `board:`, aucun id de Board, aucun chemin : la scène ne sait pas d'où vient la donnée et ne peut pas
    en demander une autre (un nom absent d'ici n'existe pas pour elle).
    """

    out: dict[str, Any] = {}
    inline = 0
    for name in sorted(resolved):
        item = resolved[name]
        entry: dict[str, Any] = {"state": item.state.value, "message": item.message[:200]}
        if item.usable:
            assert item.data is not None
            entry.update(mime=item.mime, size=len(item.data), sha256=item.sha256)
            if item.is_text and len(item.data) <= MAX_INLINE_TEXT_BYTES and inline + len(item.data) <= MAX_INLINE_TOTAL_BYTES:
                entry["text"] = item.data.decode("utf-8")
                inline += len(item.data)
            else:
                entry["file"] = f"{static_prefix}/{name}{item.extension}"
        out[name] = entry
    return out


def _bad(message: str) -> LiveRefError:
    return LiveRefError(LiveRefErrorCode.INVALID, message)


def _p(value: object) -> str:
    return repr(value)[:80]

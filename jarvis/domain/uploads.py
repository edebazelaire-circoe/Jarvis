"""Règles pures des fichiers téléversés (handoff jarvis-unified-chat-and-board-drop, Slice 07).

Contrat : `docs/chat.md` › *Attachments*, `docs/artifacts.md` › *Uploads and links*.
Pur : aucune E/S, aucune horloge. Lu par Core (route `PUT /v1/uploads/…`,
garde des pièces d'un tour écrit, bloc du brief) et par le Control Center
(relais, lisibilité par agent).

- **Bornes** réglables (`upload_bounds(env)`) : `JARVIS_UPLOAD_MAX_BYTES`
  (64 Mio par fichier) et `JARVIS_CHAT_MAX_ATTACHMENTS` (10 par message). Une
  valeur illisible ou hors plage garde le défaut et le dit (`problems`).
- **Identité rejouable** : `jart_up_<sha256(client_upload_id)[:40]>`.
- **Type reniflé** sur les octets de tête (`sniff_mime`) : le type déclaré et
  l'extension ne sont jamais crus seuls.
- **Nom de payload** `upload.<ext>` (`payload_name_for`) : extension canonique
  du type reniflé pour une image ou un PDF (le CLI lit par extension), sinon
  l'extension d'origine si elle est sûre, sinon `txt` / `bin`.
- **Nom d'origine** (`decode_upload_name`) : décodé, normalisé, nettoyé ; il
  ne sert qu'à l'affichage et au brief, jamais de nom de fichier sur disque.
- **Lisibilité par le cerveau** (`BRAIN_READABLE`, `brain_readable`) : par
  agent, ce que son CLI sait réellement lire.
"""

from __future__ import annotations

import codecs
from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import re
from types import MappingProxyType
import unicodedata
from urllib.parse import unquote

from jarvis.domain.artifacts import ARTIFACT_ID_PREFIX

# ------------------------------------------------------------------ bornes

UPLOAD_MAX_BYTES_ENV = "JARVIS_UPLOAD_MAX_BYTES"
CHAT_MAX_ATTACHMENTS_ENV = "JARVIS_CHAT_MAX_ATTACHMENTS"
DEFAULT_UPLOAD_MAX_BYTES = 64 * 1024 * 1024
DEFAULT_CHAT_MAX_ATTACHMENTS = 10
#: Plafond dur d'un réglage : au-delà, la valeur est refusée (défaut gardé).
HARD_UPLOAD_MAX_BYTES = 4 * 1024 * 1024 * 1024
#: = `jarvis.domain.v2.MAX_TURN_ATTACHMENTS` (testé) : la borne réglable reste en dessous.
HARD_CHAT_MAX_ATTACHMENTS = 64
#: Morceau de lecture d'un flux et taille de l'en-tête reniflé.
UPLOAD_CHUNK_BYTES = 64 * 1024
SNIFF_BYTES = 64 * 1024
#: Marge multipart (frontières, en-têtes de parties) au-dessus de la borne d'un fichier, au Control Center.
MULTIPART_MARGIN_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class UploadBounds:
    max_bytes: int = DEFAULT_UPLOAD_MAX_BYTES
    max_attachments: int = DEFAULT_CHAT_MAX_ATTACHMENTS
    #: Réglages ignorés (nom de la variable), pour un journal au démarrage.
    problems: tuple[str, ...] = ()


def _setting(env: Mapping[str, str], name: str, default: int, hard: int) -> tuple[int, bool]:
    raw = env.get(name)
    if raw is None or not str(raw).strip():
        return default, True
    text = str(raw).strip()
    if not text.isdigit():
        return default, False
    value = int(text)
    return (value, True) if 1 <= value <= hard else (default, False)


def upload_bounds(env: Mapping[str, str]) -> UploadBounds:
    """Bornes lues de `env` (`os.environ` à l'appel) ; partagées par Core et le Control Center."""

    max_bytes, ok_bytes = _setting(env, UPLOAD_MAX_BYTES_ENV, DEFAULT_UPLOAD_MAX_BYTES, HARD_UPLOAD_MAX_BYTES)
    count, ok_count = _setting(env, CHAT_MAX_ATTACHMENTS_ENV, DEFAULT_CHAT_MAX_ATTACHMENTS, HARD_CHAT_MAX_ATTACHMENTS)
    problems = tuple(name for name, ok in ((UPLOAD_MAX_BYTES_ENV, ok_bytes), (CHAT_MAX_ATTACHMENTS_ENV, ok_count))
                     if not ok)
    return UploadBounds(max_bytes=max_bytes, max_attachments=count, problems=problems)


# ------------------------------------------------------------------ identité

UPLOAD_ID_PREFIX = ARTIFACT_ID_PREFIX + "up_"
#: `client_upload_id` : tiré par le client, un par fichier, réutilisé à chaque reprise.
_CLIENT_UPLOAD_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{7,127}")


class UploadPurpose:
    CHAT = "chat"
    BOARD = "board"


class Provenance:
    CHAT_ATTACHMENT = "chat_attachment"
    BOARD_DROP = "board_drop"


SOURCE_BY_PROVENANCE: Mapping[str, str] = MappingProxyType({Provenance.CHAT_ATTACHMENT: "chat",
                                                             Provenance.BOARD_DROP: "board_drop"})


def check_client_upload_id(value: object) -> str:
    if not isinstance(value, str) or not _CLIENT_UPLOAD_ID.fullmatch(value):
        raise ValueError("client_upload_id must be 8-128 letters, digits, '_' or '-' (a UUID fits)")
    return value


def upload_artifact_id(client_upload_id: str) -> str:
    """Identité rejouable : même `client_upload_id` → même Artifact, jamais un double."""

    check_client_upload_id(client_upload_id)
    return UPLOAD_ID_PREFIX + hashlib.sha256(client_upload_id.encode("utf-8")).hexdigest()[:40]


# ------------------------------------------------------------------ reniflage

TEXT_PLAIN = "text/plain"
OCTET_STREAM = "application/octet-stream"
_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"%PDF-", "application/pdf"),
)
#: Extension canonique d'un type reniflé binaire : le CLI choisit son lecteur d'après elle.
_CANONICAL_EXT: Mapping[str, str] = MappingProxyType({"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif",
                                                      "image/webp": "webp", "application/pdf": "pdf"})
_BINARY_EXTS = frozenset({"png", "jpg", "jpeg", "gif", "webp", "pdf"})
#: Octets de contrôle qu'un texte ne porte pas (C0 sauf `\t \n \v \f \r` et ESC).
_TEXT_CONTROLS = bytes(b for b in range(0x20) if b not in (0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x1B))


def sniff_mime(head: bytes, *, whole: bool) -> str:
    """Type d'après les octets de tête (≤ `SNIFF_BYTES` lus). `whole` : `head` est tout le fichier.

    Images PNG/JPEG/GIF/WebP et PDF par signature ; texte = UTF-8 valide sans
    NUL (une séquence coupée en fin d'en-tête est tolérée seulement si le
    fichier continue) ; tout le reste `application/octet-stream`.
    """

    if not isinstance(head, (bytes, bytearray)):
        raise TypeError("head must be bytes")
    head = bytes(head[:SNIFF_BYTES])
    for signature, mime in _SIGNATURES:
        if head.startswith(signature):
            return mime
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if not head or head.translate(None, _TEXT_CONTROLS) != head:
        # NUL ou autre octet de contrôle C0 (hors tabulation, fins de ligne, saut de page, ESC) : binaire.
        return OCTET_STREAM
    decoder = codecs.getincrementaldecoder("utf-8")()
    try:
        decoder.decode(head, final=whole)
    except UnicodeDecodeError:
        return OCTET_STREAM
    return TEXT_PLAIN


# ------------------------------------------------------------------ noms

MAX_ORIGINAL_NAME_CHARS = 255
#: Nom encodé (en-tête `X-Jarvis-Upload-Name`) : 255 caractères UTF-8 font au plus 3 060 octets encodés pourcent.
MAX_ENCODED_NAME_CHARS = 4 * 3 * MAX_ORIGINAL_NAME_CHARS
DEFAULT_ORIGINAL_NAME = "fichier"
_EXT = re.compile(r"[a-z0-9]{1,8}")
_RESERVED_WINDOWS = frozenset({"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                               *(f"lpt{i}" for i in range(1, 10))})


class UploadNameError(ValueError):
    """Nom d'origine illisible ou trop long : 400 `upload_name_invalid`."""


def clean_display_name(name: str) -> str:
    """Nom montrable : NFC, sans caractère de contrôle ni de format (bidi), sans chemin, ≤ 255.

    Jamais un nom de fichier sur disque : seulement l'affichage et le brief.
    Un nom réservé de Windows (`CON`, `LPT1`…) est préfixé de `_` pour qu'une
    copie faite à la main ne surprenne pas.
    """

    text = unicodedata.normalize("NFC", name)
    text = "".join(" " if unicodedata.category(char) in ("Zl", "Zp") else char for char in text
                   if unicodedata.category(char) not in ("Cc", "Cf", "Cs", "Co", "Cn"))
    text = re.split(r"[\\/]", text)[-1]
    text = " ".join(text.split()).strip(" .")
    if not text:
        return DEFAULT_ORIGINAL_NAME
    if text.split(".", 1)[0].strip().lower() in _RESERVED_WINDOWS:
        text = "_" + text
    return text[:MAX_ORIGINAL_NAME_CHARS]


def decode_upload_name(header: str | None) -> str:
    """`X-Jarvis-Upload-Name` (UTF-8 encodé pourcent) → nom montrable. Absent : `fichier`."""

    if header is None or not header.strip():
        return DEFAULT_ORIGINAL_NAME
    if len(header) > MAX_ENCODED_NAME_CHARS or not header.isascii():
        raise UploadNameError("X-Jarvis-Upload-Name must be percent-encoded UTF-8 (ASCII on the wire)")
    try:
        decoded = unquote(header, encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        raise UploadNameError("X-Jarvis-Upload-Name is not valid UTF-8 once decoded") from None
    if len(decoded) > MAX_ORIGINAL_NAME_CHARS:
        raise UploadNameError(f"the original name exceeds {MAX_ORIGINAL_NAME_CHARS} characters")
    return clean_display_name(decoded)


def original_extension(name: str) -> str | None:
    """Extension d'origine en minuscules si elle tient dans `[a-z0-9]{1,8}`, sinon `None`."""

    if "." not in name:
        return None
    ext = name.rsplit(".", 1)[1].lower()
    return ext if _EXT.fullmatch(ext) else None


def payload_name_for(original_name: str, mime_type: str) -> str:
    """`upload.<ext>` : le type reniflé décide d'abord ; une extension qui ment ne passe pas."""

    canonical = _CANONICAL_EXT.get(mime_type)
    if canonical is not None:
        return f"upload.{canonical}"
    ext = original_extension(original_name)
    if ext is None or ext in _BINARY_EXTS:
        # Un texte nommé `.pdf`, un binaire inconnu nommé `.png` : jamais l'extension d'un format qu'il n'est pas.
        ext = "txt" if mime_type == TEXT_PLAIN else "bin"
    return f"upload.{ext}"


# ------------------------------------------------------------------ lisibilité

#: Ce que le CLI de chaque agent lit réellement (outil Read de Claude : texte, images, PDF).
#: Codex : rien n'est attesté, donc rien n'est annoncé lisible.
BRAIN_READABLE: Mapping[str, frozenset[str]] = MappingProxyType({
    "claude": frozenset({TEXT_PLAIN, "image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf"}),
    "codex": frozenset(),
})
BRAIN_AGENTS = frozenset(BRAIN_READABLE)


def brain_readable(agent: str | None, mime_type: str | None) -> bool:
    """Vrai seulement si l'agent sait lire ce type. Agent inconnu : faux."""

    return bool(mime_type) and mime_type in BRAIN_READABLE.get(str(agent or ""), frozenset())

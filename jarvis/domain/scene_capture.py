"""Capture visuelle exceptionnelle de la scène (handoff jarvis-constellation-scene-runtime, Slice 09, partie 2).

Décision 16 : le cerveau lit la scène par la structure (`scene_inspect`,
`scene_query`, `scene_get`) ; la capture n'est qu'une vérification visuelle
ponctuelle. Choix du PM après le spike (option a1) : la page meneuse **visible**
du Control Center dessine son propre modèle de vue sur un canevas et envoie un
PNG ; Core le range sous `runtime/scene-captures/`.

Ce module ne tient que les bornes, les codes stables et la validation d'un PNG
reçu : sans E/S, partagé par Core, le Control Center et l'outil du cerveau.
"""

from __future__ import annotations

import re
import struct
import zlib

#: Corps maximal d'un PNG envoyé par la page (et relu par Core).
MAX_CAPTURE_BYTES = 2 * 1_048_576
#: Rendu borné : la page réduit sa fenêtre à ce cadre, sans agrandir.
MAX_CAPTURE_WIDTH = 1280
MAX_CAPTURE_HEIGHT = 720
#: Échéance d'une capture, de la demande du cerveau au fichier rangé.
CAPTURE_DEADLINE_S = 5.0
#: Une demande encore en attente est redonnée au long-poll au plus une fois par
#: seconde : un nouveau meneur (passation) la reçoit sans boucle serrée.
CAPTURE_REDELIVER_S = 1.0
#: Rétention des fichiers : les 5 derniers, jamais plus de 24 h.
CAPTURE_KEEP_FILES = 5
CAPTURE_MAX_AGE_S = 24 * 3600.0
#: Blocs d'un PNG accepté au plus (un canevas en produit une poignée).
MAX_PNG_CHUNKS = 4096
#: Corps de la demande du cerveau (`POST /v1/scene/captures`).
MAX_CAPTURE_REQUEST_BYTES = 4_096

#: Codes stables (`error.code`, erreurs d'outil du cerveau, journal).
CAPTURE_BUSY = "capture_busy"
NO_VISIBLE_PAGE = "no_visible_page"
UNKNOWN_CAPTURE = "unknown_capture"
CAPTURE_EXPIRED = "capture_expired"
INVALID_PNG = "invalid_png"
CAPTURE_UNAVAILABLE = "capture_unavailable"
CAPTURE_CANCELLED = "capture_cancelled"
CAPTURE_STORE_FAILED = "capture_store_failed"
SCENE_DISABLED = "scene_disabled"

#: Identifiant de capture : aléatoire, non devinable, à usage unique
#: (`secrets.token_urlsafe(24)` donne 32 caractères).
_CAPTURE_ID = re.compile(r"\A[A-Za-z0-9_-]{32,64}\Z")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_END = b"\x00\x00\x00\x00IEND\xaeB`\x82"
#: Profondeurs admises par type de couleur (spécification PNG, tableau 11.1).
_PNG_DEPTHS = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}


def check_capture_id(value: object) -> str:
    """L'identifiant tel qu'il voyage dans un chemin ; `ValueError` sinon."""

    if not isinstance(value, str) or not _CAPTURE_ID.match(value):
        raise ValueError("capture id must be 32 to 64 characters of [A-Za-z0-9_-]")
    return value


def png_dimensions(data: bytes) -> tuple[int, int]:
    """Largeur et hauteur d'un PNG complet et borné ; `ValueError` sinon.

    Vérifie la taille, la signature, puis **chaque** bloc : longueur dans le corps,
    CRC exact ; `IHDR` de 13 octets en premier, dimensions (1..`MAX_CAPTURE_WIDTH` ×
    1..`MAX_CAPTURE_HEIGHT`) ; au moins un `IDAT` ; aucun `acTL` (PNG animé) ; aucun
    bloc critique inconnu (majuscule initiale hors `IHDR`, `PLTE`, `IDAT`, `IEND`) ;
    `IEND` vide en dernier, rien après. Ne décompresse pas les pixels.
    """

    if not isinstance(data, (bytes, bytearray)):
        raise ValueError("capture body must be bytes")
    if len(data) > MAX_CAPTURE_BYTES:
        raise ValueError(f"capture exceeds {MAX_CAPTURE_BYTES} bytes")
    if len(data) < len(_PNG_SIGNATURE) + 25 + len(_PNG_END) or not data.startswith(_PNG_SIGNATURE):
        raise ValueError("capture is not a PNG (signature)")
    position = len(_PNG_SIGNATURE)
    width = height = 0
    seen_idat = False
    index = 0
    while True:
        if position + 12 > len(data):
            raise ValueError("capture PNG is truncated (no IEND)")
        length, tag = struct.unpack(">I4s", data[position:position + 8])
        end = position + 12 + length
        if end > len(data):
            raise ValueError("capture PNG chunk runs past the end")
        body = data[position + 8:position + 8 + length]
        (crc,) = struct.unpack(">I", data[end - 4:end])
        if zlib.crc32(tag + body) & 0xFFFFFFFF != crc:
            raise ValueError(f"capture PNG {tag!r} checksum mismatch")
        if index == 0:
            if tag != b"IHDR" or length != 13:
                raise ValueError("capture PNG must start with a 13-byte IHDR chunk")
            width, height = struct.unpack(">II", body[:8])
            if not (1 <= width <= MAX_CAPTURE_WIDTH and 1 <= height <= MAX_CAPTURE_HEIGHT):
                raise ValueError(f"capture PNG is {width}x{height}, expected at most {MAX_CAPTURE_WIDTH}x{MAX_CAPTURE_HEIGHT}")
            depth, color, compression, filtering, interlace = body[8], body[9], body[10], body[11], body[12]
            if depth not in _PNG_DEPTHS.get(color, ()) or compression != 0 or filtering != 0 or interlace not in (0, 1):
                raise ValueError("capture PNG header has an invalid depth, color type or method")
        elif tag == b"acTL":
            raise ValueError("animated PNG (acTL) is not a capture")
        elif tag == b"IDAT":
            seen_idat = True
        elif tag == b"IEND":
            if length != 0 or end != len(data):
                raise ValueError("capture PNG IEND must be empty and last")
            if not seen_idat:
                raise ValueError("capture PNG has no IDAT")
            return width, height
        elif tag[0:1].isupper() and tag not in (b"PLTE",):
            raise ValueError(f"capture PNG has an unknown critical chunk {tag!r}")
        position = end
        index += 1
        if index > MAX_PNG_CHUNKS:
            raise ValueError("capture PNG has too many chunks")

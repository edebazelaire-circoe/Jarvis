"""Encodeur PNG minimal d'une capture d'écran (handoff session-context-recording, Slice 07).

Pur, bibliothèque standard seulement (`zlib`) : la capture d'écran du bureau
n'ajoute aucune dépendance (ni Pillow ni mss, D-SCREEN). Entrée : pixels
BGRA 8 bits de haut en bas (format d'une DIB GDI 32 bits), sortie : PNG
RGB 8 bits non entrelacé, filtre `None` par ligne. Le canal alpha de GDI
n'a pas de sens pour le bureau : il est jeté.
"""

from __future__ import annotations

import struct
import zlib

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
#: Niveau zlib : 6 est le compromis taille/temps mesuré sur l'hôte (docs/capture.md › Screen).
DEFAULT_LEVEL = 6


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def bgra_to_png(width: int, height: int, bgra: bytes, *, level: int = DEFAULT_LEVEL) -> bytes:
    """PNG RGB d'une image BGRA de haut en bas ; `ValueError` si la taille ne correspond pas."""

    if width <= 0 or height <= 0:
        raise ValueError(f"image size must be positive, got {width}x{height}")
    if len(bgra) != width * height * 4:
        raise ValueError(f"expected {width * height * 4} BGRA bytes for {width}x{height}, got {len(bgra)}")
    rgb = bytearray(width * height * 3)
    # Réordonnancement par tranches : fait en C, sans boucle Python par pixel.
    rgb[0::3] = bgra[2::4]
    rgb[1::3] = bgra[1::4]
    rgb[2::3] = bgra[0::4]
    stride = width * 3
    view = memoryview(rgb)
    raw = b"".join(b"\x00" + view[y * stride:(y + 1) * stride] for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (PNG_SIGNATURE + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(raw, level))
            + _chunk(b"IEND", b""))


def png_size(data: bytes) -> tuple[int, int]:
    """Largeur et hauteur lues dans l'en-tête `IHDR` ; `ValueError` si ce n'est pas un PNG."""

    if len(data) < 24 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        raise ValueError("not a PNG image")
    return struct.unpack(">II", data[16:24])


__all__ = ["DEFAULT_LEVEL", "PNG_SIGNATURE", "bgra_to_png", "png_size"]

"""Octets d'un rendu : lecture des dimensions, vérification d'un MP4 / PNG / PDF, PDF de pages-images (Remotion Slice 16).

Pur : octets en entrée, octets ou constats en sortie. Aucun processus (le contrôle `ffprobe` est dans l'adaptateur).

PDF (décision, `docs/remotion-render.md` « PDF ») : un PDF est un **assemblage de pages-images** — une image JPEG rendue par page demandée,
rien d'autre. Ce n'est PAS un document éditable ni un texte sélectionnable : l'export est plat et le dit (`render_flat`, `render_kind`).
Écriture déterministe (aucune date, aucun identifiant aléatoire) : mêmes pages, mêmes octets.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Any

from jarvis.domain.presentation_artifacts import RenderFormat

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PDF_POINTS_PER_PIXEL = 0.75
MAX_PAGE_IMAGE_BYTES = 32 * 1024 * 1024


class OutputProblem(ValueError):
    """Un fichier de sortie qui n'est pas ce qu'il prétend être."""


def png_size(data: bytes) -> tuple[int, int]:
    if len(data) < 33 or data[:8] != PNG_SIGNATURE or data[12:16] != b"IHDR":
        raise OutputProblem("not a PNG file")
    width, height = struct.unpack(">II", data[16:24])
    if width < 1 or height < 1:
        raise OutputProblem("PNG has an empty size")
    return width, height


def jpeg_info(data: bytes) -> tuple[int, int, int]:
    """`(largeur, hauteur, composantes)` d'un JPEG de base ou progressif."""

    if len(data) < 4 or data[:2] != b"\xff\xd8":
        raise OutputProblem("not a JPEG file")
    index = 2
    while index + 4 <= len(data):
        if data[index] != 0xFF:
            raise OutputProblem("JPEG markers are damaged")
        marker = data[index + 1]
        if marker == 0xFF:
            index += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        (length,) = struct.unpack(">H", data[index + 2:index + 4])
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if index + 10 > len(data):
                break
            height, width = struct.unpack(">HH", data[index + 5:index + 9])
            return width, height, data[index + 9]
        index += 2 + length
    raise OutputProblem("JPEG has no frame header")


def build_pdf(pages: list[bytes]) -> tuple[bytes, list[tuple[int, int]]]:
    """PDF 1.4 d'une image JPEG par page (taille de page = taille de l'image à 96 ppp). Rend `(octets, tailles en pixels)`."""

    if not pages:
        raise OutputProblem("a PDF needs at least one page")
    infos = []
    for number, image in enumerate(pages, 1):
        if len(image) > MAX_PAGE_IMAGE_BYTES:
            raise OutputProblem(f"page {number} image is larger than {MAX_PAGE_IMAGE_BYTES} bytes")
        width, height, components = jpeg_info(image)
        if components not in (1, 3):
            raise OutputProblem(f"page {number}: {components}-component JPEG is not supported")
        infos.append((width, height, components))
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog_id = add(b"")  # rempli après : les numéros des pages sont connus
    pages_id = add(b"")
    kids: list[int] = []
    for image, (width, height, components) in zip(pages, infos):
        pt_w, pt_h = round(width * PDF_POINTS_PER_PIXEL, 2), round(height * PDF_POINTS_PER_PIXEL, 2)
        space = b"/DeviceRGB" if components == 3 else b"/DeviceGray"
        image_id = add(b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace %s /BitsPerComponent 8 /Filter /DCTDecode /Length %d >>\nstream\n"
                       % (width, height, space, len(image)) + image + b"\nendstream")
        content = b"q %s 0 0 %s 0 0 cm /Im0 Do Q" % (f"{pt_w}".encode(), f"{pt_h}".encode())
        content_id = add(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
        page_id = add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %s %s] /Resources << /XObject << /Im0 %d 0 R >> >> /Contents %d 0 R >>"
                      % (pages_id, f"{pt_w}".encode(), f"{pt_h}".encode(), image_id, content_id))
        kids.append(page_id)
    objects[catalog_id - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id
    objects[pages_id - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % k for k in kids), len(kids))
    info_id = add(b"<< /Producer (Jarvis presentation export) /Subject (Flat export of a frozen presentation snapshot: page images, not editable) >>")
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, catalog_id, info_id, xref)
    return bytes(out), [(w, h) for w, h, _ in infos]


def pdf_page_count(data: bytes) -> int:
    """Nombre de pages d'un PDF produit par `build_pdf` (relu dans le dictionnaire `/Pages`)."""

    if not data.startswith(b"%PDF-") or not data.rstrip().endswith(b"%%EOF"):
        raise OutputProblem("not a complete PDF file")
    marker = data.rfind(b"/Type /Pages")
    if marker < 0:
        raise OutputProblem("PDF has no page tree")
    count = data.find(b"/Count ", marker)
    digits = data[count + 7:count + 12].split(b" ")[0].split(b">")[0]
    if count < 0 or not digits.isdigit():
        raise OutputProblem("PDF page count is unreadable")
    return int(digits)


@dataclass(frozen=True, slots=True)
class VideoFacts:
    width: int
    height: int
    frames: int | None
    duration_ms: int
    codec: str
    fps: float | None


def video_facts(probe: dict[str, Any]) -> VideoFacts:
    """Constats d'un JSON `ffprobe -show_format -show_streams` : exactement un flux vidéo H.264, dimensions et durée lisibles."""

    streams = [s for s in probe.get("streams", []) if isinstance(s, dict) and s.get("codec_type", "video") == "video"]
    if len(streams) != 1:
        raise OutputProblem(f"expected one video stream, found {len(streams)}")
    stream = streams[0]
    try:
        width, height = int(stream["width"]), int(stream["height"])
        raw_duration = stream.get("duration") or probe.get("format", {}).get("duration")
        duration_ms = round(float(raw_duration) * 1000)
        frames = int(stream["nb_frames"]) if str(stream.get("nb_frames", "")).isdigit() else None
        rate = str(stream.get("r_frame_rate", ""))
        num, _, den = rate.partition("/")
        fps = float(num) / float(den or 1) if rate and float(den or 1) else None
    except (KeyError, TypeError, ValueError):
        raise OutputProblem("ffprobe did not report the size and duration of the video") from None
    return VideoFacts(width, height, frames, duration_ms, str(stream.get("codec_name", "")), fps)


def check_header(fmt: RenderFormat, head: bytes) -> None:
    """Contrôle d'en-tête (toujours possible, même sans `ffprobe`)."""

    if fmt is RenderFormat.MP4 and head[4:8] != b"ftyp":
        raise OutputProblem("the video does not start with an MP4 'ftyp' box")
    if fmt is RenderFormat.STILL and head[:8] != PNG_SIGNATURE:
        raise OutputProblem("the still image is not a PNG file")
    if fmt is RenderFormat.PDF and not head.startswith(b"%PDF-"):
        raise OutputProblem("the document is not a PDF file")

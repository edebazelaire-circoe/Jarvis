"""Lecture des boîtes de premier niveau d'un MP4 fragmenté (handoff session-context-recording, Slice 07).

Pur (un fichier binaire ouvert suffit), aucune dépendance. Un enregistrement
d'écran est écrit en MP4 **fragmenté** (`ftyp`, `moov` vide d'échantillons,
puis des paires `moof`+`mdat` d'environ 1 s) : chaque fragment complet est
lisible seul, si bien qu'un processus tué en pleine écriture laisse un fichier
lisible jusqu'au dernier fragment complet. Ce module dit ce qui est complet et
où commence la fin déchirée, pour la réparation après une mort de Core
(`FragmentedMp4Repair`).
"""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import BinaryIO

_HEADER = 8
_LARGE_HEADER = 16


@dataclass(frozen=True, slots=True)
class Box:
    kind: str
    offset: int
    size: int

    @property
    def end(self) -> int:
        return self.offset + self.size


@dataclass(frozen=True, slots=True)
class FragmentScan:
    """Ce qu'un fichier contient de lisible."""

    file_bytes: int
    has_ftyp: bool
    has_moov: bool
    #: Paires `moof`+`mdat` complètes.
    fragments: int
    #: Fin du dernier élément lisible ; tout ce qui suit est une fin déchirée.
    readable_end: int
    #: Boîte inconnue, taille impossible... : raison courte, sinon `None`.
    problem: str | None = None

    @property
    def usable(self) -> bool:
        return self.has_ftyp and self.has_moov and self.fragments > 0

    @property
    def torn_bytes(self) -> int:
        return self.file_bytes - self.readable_end


def _boxes(handle: BinaryIO, file_bytes: int) -> tuple[list[Box], str | None]:
    boxes: list[Box] = []
    offset = 0
    while offset + _HEADER <= file_bytes:
        handle.seek(offset)
        header = handle.read(_HEADER)
        if len(header) < _HEADER:
            return boxes, "short_header"
        size, raw_kind = struct.unpack(">I4s", header)
        kind = raw_kind.decode("latin-1")
        if size == 1:
            large = handle.read(8)
            if len(large) < 8:
                return boxes, "short_header"
            (size,) = struct.unpack(">Q", large)
            minimum = _LARGE_HEADER
        else:
            minimum = _HEADER
        if size == 0:
            # « jusqu'à la fin du fichier » : jamais écrit par l'encodeur en mode
            # fragmenté ; complète seulement si c'est bien la dernière boîte.
            size = file_bytes - offset
        if size < minimum:
            return boxes, f"bad_box_size:{kind}"
        if offset + size > file_bytes:
            return boxes, None  # fin déchirée : la boîte n'est pas finie sur disque
        boxes.append(Box(kind, offset, size))
        offset += size
    return boxes, None


def scan(handle: BinaryIO, file_bytes: int) -> FragmentScan:
    """Inventaire des boîtes complètes ; ne lit que les en-têtes (quelques octets par boîte)."""

    boxes, problem = _boxes(handle, file_bytes)
    has_ftyp = bool(boxes) and boxes[0].kind == "ftyp"
    has_moov = any(b.kind == "moov" for b in boxes)
    readable_end = 0
    fragments = 0
    pending_moof: Box | None = None
    for box in boxes:
        if box.kind == "moof":
            pending_moof = box
            continue
        if box.kind == "mdat" and pending_moof is not None:
            fragments += 1
            readable_end = box.end
            pending_moof = None
            continue
        if pending_moof is None:
            # `ftyp`, `moov`, `mfra`... : complets et sans fragment ouvert.
            readable_end = box.end
    return FragmentScan(file_bytes=file_bytes, has_ftyp=has_ftyp, has_moov=has_moov, fragments=fragments,
                        readable_end=readable_end, problem=problem)


__all__ = ["Box", "FragmentScan", "scan"]

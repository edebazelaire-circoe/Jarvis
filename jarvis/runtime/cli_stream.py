"""Lecture robuste des flux d'un CLI enfant (stream-json) : lignes bornées, images retirées, journal borné.

Handoff jarvis-constellation-scene-runtime, Slice 09 (reprise QA). Trouvé par le run réel de
`scene_capture` : la ligne d'un résultat d'outil portant une image dépassait la borne de 64 Kio de
`asyncio.StreamReader.readline`, qui levait ; la lecture du CLI mourait en silence. Partagé par
`claude_local`, `codex_local` et `scripts/supervisor_v2.py` :

- `iter_lines(stream)` lit par blocs (`read`, jamais `readline`) et rend chaque ligne entière, ou
  `OversizeLine(size)` pour une ligne au-delà de la borne, **entièrement** écartée jusqu'à son saut de
  ligne (aucun fragment ne revient comme une ligne suivante) ;
- `redact_media(value)` remplace partout, récursivement, toute donnée base64 d'une image ou d'une
  pièce (`{"type": "image", "source": {"type": "base64", "data": …}}`, forme MCP
  `{"type": "image", "data": …}`, tout `source` base64) par sa taille : ni journal, ni API, ni mémoire
  ne portent les pixels ;
- `journal_view(event, size)` rend l'événement tel quel, ou un résumé borné au-delà de
  `MAX_JOURNAL_EVENT_BYTES`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
import json
from typing import Any

#: Plus longue ligne gardée ; au-delà, la ligne entière est écartée et signalée.
MAX_LINE_BYTES = 16 * 1024 * 1024
#: Taille lue par appel : ce que le tube rend d'un coup.
READ_CHUNK_BYTES = 64 * 1024
#: Au-delà, un événement est journalisé en résumé (type, taille, clés), jamais en entier.
MAX_JOURNAL_EVENT_BYTES = 256 * 1024
#: Aperçu gardé d'une ligne de texte trop grosse pour le journal.
JOURNAL_PREVIEW_CHARS = 2_000


@dataclass(frozen=True, slots=True)
class OversizeLine:
    """Ligne écartée : sa taille en octets (au moins `limit + 1`)."""

    size: int


async def iter_lines(stream: asyncio.StreamReader, *, limit: int = MAX_LINE_BYTES,
                     chunk_bytes: int = READ_CHUNK_BYTES) -> AsyncIterator[bytes | OversizeLine]:
    """Lignes de `stream` sans leur saut de ligne ; `OversizeLine` pour une ligne trop longue.

    Une dernière ligne sans saut de ligne avant la fin du flux est rendue telle quelle.
    """

    if not hasattr(stream, "read"):
        # Doublure de flux à lignes seulement (tests) : même contrat, sans découpe par blocs.
        while True:
            raw = await stream.readline()
            if not raw:
                return
            line = raw[:-1] if raw.endswith(b"\n") else raw
            yield OversizeLine(len(line)) if len(line) > limit else line
    buffer = bytearray()
    discarding = False
    dropped = 0
    while True:
        chunk = await stream.read(chunk_bytes)
        if not chunk:
            if discarding:
                yield OversizeLine(dropped)
            elif buffer:
                yield bytes(buffer)
            return
        position = 0
        while position < len(chunk):
            newline = chunk.find(b"\n", position)
            end = len(chunk) if newline < 0 else newline
            if discarding:
                dropped += end - position
            else:
                buffer += chunk[position:end]
                if len(buffer) > limit:
                    dropped = len(buffer)
                    buffer.clear()
                    discarding = True
            if newline < 0:
                break
            if discarding:
                yield OversizeLine(dropped)
                discarding, dropped = False, 0
            else:
                line = bytes(buffer)
                buffer.clear()
                yield line
            position = newline + 1


def _redacted_block(block: dict[str, Any]) -> dict[str, Any] | None:
    """Le bloc sans ses données base64, ou `None` s'il n'en porte pas."""

    source = block.get("source")
    if isinstance(source, dict) and isinstance(source.get("data"), str) and (
            source.get("type") == "base64" or block.get("type") == "image"):
        kept = {key: value for key, value in block.items() if key != "source"}
        kept["source"] = {key: value for key, value in source.items() if key != "data"}
        kept["source"]["omitted_bytes"] = len(source["data"])
        return kept
    if block.get("type") == "image" and isinstance(block.get("data"), str):
        kept = {key: value for key, value in block.items() if key != "data"}
        kept["omitted_bytes"] = len(block["data"])
        return kept
    return None


def redact_media(value: Any) -> Any:
    """Copie de `value` où chaque image ou pièce base64, à toute profondeur, ne garde que sa taille.

    Les parties sans média sont rendues telles quelles (pas de copie).
    """

    if isinstance(value, dict):
        redacted = _redacted_block(value)
        base = redacted if redacted is not None else value
        changed = redacted is not None
        out: dict[str, Any] = {}
        for key, item in base.items():
            new = redact_media(item)
            changed = changed or new is not item
            out[key] = new
        return out if changed else value
    if isinstance(value, list):
        items = [redact_media(item) for item in value]
        return items if any(new is not old for new, old in zip(items, value)) else value
    return value


def may_carry_media(raw: bytes) -> bool:
    """Filtre bon marché avant `redact_media` : une ligne sans ces marqueurs n'a pas de base64 à retirer."""

    return b'"base64"' in raw or b'"image"' in raw


def journal_view(event: dict[str, Any], *, size: int, limit: int = MAX_JOURNAL_EVENT_BYTES) -> dict[str, Any]:
    """L'événement à journaliser : lui-même sous `limit` octets, sinon un résumé borné.

    `size` : taille de la ligne lue (borne haute de l'événement encodé).
    """

    if size <= limit:
        return event
    encoded = len(json.dumps(event, ensure_ascii=False).encode("utf-8"))
    if encoded <= limit:
        return event
    summary: dict[str, Any] = {"type": event.get("type"), "journal_truncated": True, "bytes": encoded,
                               "keys": sorted(str(key) for key in event)[:20]}
    text = event.get("text")
    if isinstance(text, str):
        summary["preview"] = text[:JOURNAL_PREVIEW_CHARS]
    for key in ("session_id", "subtype", "parent_tool_use_id", "uuid"):
        if key in event and isinstance(event[key], (str, int, type(None))):
            summary[key] = event[key]
    return summary


def clip_text(text: str, limit: int = MAX_JOURNAL_EVENT_BYTES) -> str:
    """Texte borné pour le journal ou la mémoire (`…[+N caractères]` au-delà)."""

    if len(text) <= limit:
        return text
    return f"{text[:limit]}…[+{len(text) - limit} caractères]"

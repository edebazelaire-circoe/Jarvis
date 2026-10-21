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
  `MAX_JOURNAL_EVENT_BYTES` ;
- `restricted_event_view(event, size)` (session-context, reprise QA Slice 08) : pour un profil
  restreint (enrichissement, spéculatif, préparation), **métadonnées seulement** — type, sous-type,
  tailles, jetons, coût, durée, codes — jamais un texte : sa sortie résume la parole de la salle.
- `ToolContentRedactor.view(event)` (organic orchestration, Slice 13) : avant `journal_view`, le
  texte libre des outils de relation (`mcp__jarvis-workspace__relation_*` : messages, packet de relais,
  synthèses) devient sa taille, leurs résultats aussi ; tout autre résultat d'outil est borné à
  `JOURNAL_TOOL_RESULT_CHARS`. Restent les identifiants, codes, drapeaux et tailles, ce qui suffit au
  diagnostic ; le tableau de relation et l'historique de mission gardent seuls le texte délibéré.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from collections import OrderedDict
from dataclasses import dataclass
import json
import re
from typing import Any

#: Plus longue ligne gardée ; au-delà, la ligne entière est écartée et signalée.
MAX_LINE_BYTES = 16 * 1024 * 1024
#: Taille lue par appel : ce que le tube rend d'un coup.
READ_CHUNK_BYTES = 64 * 1024
#: Au-delà, un événement est journalisé en résumé (type, taille, clés), jamais en entier.
MAX_JOURNAL_EVENT_BYTES = 256 * 1024
#: Aperçu gardé d'une ligne de texte trop grosse pour le journal.
JOURNAL_PREVIEW_CHARS = 2_000
#: Outils dont le texte est une communication délibérée entre agents : jamais recopiée dans le journal.
RELATION_TOOL_PREFIX = "mcp__jarvis-workspace__relation_"
#: Aperçu gardé du résultat d'un autre outil dans le journal diagnostique (le reste : sa taille).
JOURNAL_TOOL_RESULT_CHARS = 1_000
#: Identifiants d'appels d'outil de relation retenus pour reconnaître leur résultat (borne mémoire).
_RELATION_CALLS_KEPT = 256
#: Valeur gardée telle quelle dans l'entrée d'un outil de relation : un identifiant ou un code, jamais une phrase.
_TOKEN_VALUE = re.compile(r"[A-Za-z0-9_.:@/-]{1,96}")


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


#: Champs scalaires d'un événement gardés pour un profil restreint : aucun ne porte de texte libre.
_RESTRICTED_SCALARS = ("type", "subtype", "session_id", "uuid", "is_error", "duration_ms", "duration_api_ms",
                       "num_turns", "total_cost_usd", "stop_reason", "model")


def restricted_event_view(event: dict[str, Any], *, size: int) -> dict[str, Any]:
    """L'événement d'un profil restreint réduit à ses métadonnées : jamais de texte (D13/D17)."""

    view: dict[str, Any] = {"bytes": size, "text_withheld": True}
    for key in _RESTRICTED_SCALARS:
        value = event.get(key)
        if isinstance(value, (bool, int, float)) or (isinstance(value, str) and len(value) <= 128 and key != "result"):
            view[key] = value
    usage = event.get("usage")
    if not isinstance(usage, dict):
        message = event.get("message")
        usage = message.get("usage") if isinstance(message, dict) else None
    if isinstance(usage, dict):
        view["usage"] = {key: value for key, value in usage.items()
                         if isinstance(value, (int, float)) and not isinstance(value, bool)}
        details = usage.get("output_tokens_details")
        if isinstance(details, dict) and isinstance(details.get("thinking_tokens"), int):
            view["usage"]["thinking_tokens"] = details["thinking_tokens"]
    message = event.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        view["content"] = [{"type": str(block.get("type") or "?")[:32],
                            "chars": len(str(block.get("text") or block.get("thinking") or ""))}
                           for block in content[:16] if isinstance(block, dict)]
    if isinstance(event.get("result"), str):
        view["result_chars"] = len(event["result"])
    errors = event.get("errors")
    if isinstance(errors, list):
        view["errors"] = len(errors)
    return view


def _token_view(value: Any) -> Any:
    """Entrée d'un outil de relation : identifiants, codes, nombres et drapeaux gardés ; tout texte libre → sa taille."""

    if isinstance(value, dict):
        return {str(key): _token_view(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_token_view(item) for item in value[:32]]
    if isinstance(value, str):
        return value if _TOKEN_VALUE.fullmatch(value) else {"redacted_chars": len(value)}
    return value


def _result_chars(content: Any) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(str(item.get("text") or "")) for item in content if isinstance(item, dict))
    return len(json.dumps(content, ensure_ascii=False, default=str)) if content is not None else 0


def _bounded_result(content: Any, limit: int) -> Any:
    """Résultat d'outil borné à `limit` caractères de texte au total ; les blocs sans texte restent tels quels."""

    if isinstance(content, str):
        return clip_text(content, limit)
    if not isinstance(content, list):
        return content
    out: list[Any] = []
    left = limit
    for item in content:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            text = item["text"]
            out.append({**item, "text": clip_text(text, left) if left > 0 else f"…[+{len(text)} caractères]"})
            left -= len(text)
        else:
            out.append(item)
    return out


class ToolContentRedactor:
    """Vue journal d'un événement stream-json : contenu des outils de relation retiré, autres résultats bornés.

    Garde en mémoire (bornée) les `tool_use_id` des appels de relation vus, pour reconnaître leur résultat, qui
    arrive dans un événement `user` ultérieur. Ne modifie jamais l'événement reçu (copie des seules parties changées).
    """

    def __init__(self, *, result_chars: int = JOURNAL_TOOL_RESULT_CHARS) -> None:
        self._relation_calls: OrderedDict[str, None] = OrderedDict()
        self._result_chars = result_chars

    def _remember(self, tool_use_id: str) -> None:
        self._relation_calls[tool_use_id] = None
        while len(self._relation_calls) > _RELATION_CALLS_KEPT:
            self._relation_calls.popitem(last=False)

    def view(self, event: dict[str, Any]) -> dict[str, Any]:
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            return event
        changed = relation_result = False
        blocks: list[Any] = []
        for block in content:
            if not isinstance(block, dict):
                blocks.append(block)
                continue
            kind = block.get("type")
            if kind == "tool_use" and str(block.get("name") or "").startswith(RELATION_TOOL_PREFIX):
                if isinstance(block.get("id"), str):
                    self._remember(block["id"])
                blocks.append({**block, "input": _token_view(block.get("input"))})
                changed = True
            elif kind == "tool_result":
                chars = _result_chars(block.get("content"))
                if block.get("tool_use_id") in self._relation_calls:
                    relation_result = True
                    kept = {key: value for key, value in block.items() if key != "content"}
                    blocks.append({**kept, "content_withheld": True, "content_chars": chars})
                    changed = True
                elif chars > self._result_chars:
                    blocks.append({**block, "content": _bounded_result(block.get("content"), self._result_chars),
                                   "content_chars": chars})
                    changed = True
                else:
                    blocks.append(block)
            else:
                blocks.append(block)
        if not changed:
            return event
        out = {**event, "message": {**message, "content": blocks}}
        if relation_result and "tool_use_result" in out:
            out["tool_use_result"] = {"withheld": True,
                                      "chars": len(json.dumps(out["tool_use_result"], ensure_ascii=False, default=str))}
        return out


def clip_text(text: str, limit: int = MAX_JOURNAL_EVENT_BYTES) -> str:
    """Texte borné pour le journal ou la mémoire (`…[+N caractères]` au-delà)."""

    if len(text) <= limit:
        return text
    return f"{text[:limit]}…[+{len(text) - limit} caractères]"

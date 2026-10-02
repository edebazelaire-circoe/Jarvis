"""Réponse bornée de `list_tools(intent)` (generic-mcp-plugin-runtime, Slice 04 ; ARCH §7.2, E3, E6).

Entrée : les outils accessibles **déjà classés** (`tool_relevance.rank`).
Sortie : le JSON que lit le modèle (`docs/mcp/plugins.md` §6.3) :

- `recommended` : ≤ 5 entrées COMPLÈTES (description, `input_schema`,
  `side_effect`, `invocation`, `call_as` pour un natif), score > 0 et
  ≥ 0,35 × le meilleur, **au plus 2 natifs** (E21), empaquetées tant que la
  partie recommandée tient en 16 Kio ; une entrée qui dépasse seule 16 Kio
  n'est jamais recommandée : elle reste appelable et figure dans `others` avec
  `"detail": "too_large"` (E3) ;
- `others` : le reste des outils **externes**, ordre du classement, en fiches
  compactes (résumé ≤ 120 caractères), pagé par `limit` et rempli tant que
  **toute** la réponse tient en 24 576 octets (JSON compact UTF-8). Un natif
  (`direct_native`) n'y figure jamais : le CLI en montre déjà le nom dans sa
  liste d'outils différés (E21) ;
- `total` : ce que la réponse pagine (les outils externes) ; `native_total` :
  les natifs accessibles, classés mais seulement recommandables ;
- `next_cursor` : base64url d'un JSON `{r, o, h}` — révision (chaîne
  `n<fp8>.e<rev>`, E6), décalage dans `others`, `sha1(intention)[:8]`. Révision
  différente : reprise à 0 avec la note `catalog_changed` ; autre intention :
  `mcp_cursor_invalid`.

`recommended` n'est rendu qu'en première page (décalage 0) : la suite d'un
curseur ne répète pas les fiches complètes. Pur, déterministe.

Décision E17 (ARCH §16, mesurée en Slice 05 sur le vrai CLI) : un natif
recommandé **garde** son `input_schema`. Les natifs sont différés derrière
ToolSearch, mais le CLI accepte l'appel direct d'un `call_as` juste après
`list_tools` ; le schéma rendu ici est alors le seul que le modèle ait.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from typing import Any

from jarvis.domain.mcp_plugins import McpErrorCode, McpPluginError

MAX_RECOMMENDED = 5
#: E21 : un natif recommandé coûte 3-4 Ko de schéma ; le CLI connaît déjà son nom.
MAX_RECOMMENDED_NATIVES = 2
RECOMMENDED_RATIO = 0.35
MAX_RECOMMENDED_BYTES = 16 * 1024
MAX_RESPONSE_BYTES = 24_576
MAX_SUMMARY_CHARS = 120
MIN_LIMIT = 1
MAX_LIMIT = 60
DEFAULT_LIMIT = 30
MAX_INTENT_CHARS = 500
MAX_CURSOR_CHARS = 512

NOTE_CATALOG_CHANGED = "catalog_changed"
NOTE_PLUGINS_UNAVAILABLE = "plugins_unavailable"
DETAIL_TOO_LARGE = "too_large"
DIRECT_NATIVE = "direct_native"


@dataclass(frozen=True, slots=True)
class ToolEntry:
    """Un outil accessible, tel que `list_tools` peut le recommander.

    `invocation` : `direct_native` (appel par `call_as`, jamais par `call_tool`)
    ou `managed_external` (par `call_tool(tool_id)`).
    """

    id: str
    name: str
    invocation: str
    source: str
    description: str
    input_schema: Mapping[str, Any]
    side_effect: str
    call_as: str | None = None

    def full(self) -> dict[str, Any]:
        entry: dict[str, Any] = {"id": self.id, "name": self.name, "invocation": self.invocation}
        if self.call_as is not None:
            entry["call_as"] = self.call_as
        entry.update({"source": self.source, "description": self.description,
                      "input_schema": dict(self.input_schema), "side_effect": self.side_effect})
        return entry

    def compact(self, *, too_large: bool = False) -> dict[str, Any]:
        entry = {"id": self.id, "summary": summary_of(self.description), "source": self.source,
                 "side_effect": self.side_effect, "invocation": self.invocation}
        if too_large:
            entry["detail"] = DETAIL_TOO_LARGE
        return entry


def size_of(value: Any) -> int:
    """Octets mesurés par le contrat : `json.dumps(ensure_ascii=False, separators=(",", ":"))` en UTF-8."""

    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def summary_of(description: str) -> str:
    """Première ligne non vide de la description, ≤ 120 caractères (coupée avec « … »)."""

    line = next((part.strip() for part in description.splitlines() if part.strip()), "")
    return line if len(line) <= MAX_SUMMARY_CHARS else line[: MAX_SUMMARY_CHARS - 1].rstrip() + "…"


def intent_hash(intent: str) -> str:
    return hashlib.sha1(intent.encode("utf-8")).hexdigest()[:8]


def encode_cursor(revision: str, offset: int, intent: str) -> str:
    raw = json.dumps({"r": revision, "o": offset, "h": intent_hash(intent)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def _cursor_error(reason: str) -> McpPluginError:
    # La suite (« rappelle list_tools sans curseur ») est ajoutée une fois, par la passerelle.
    return McpPluginError(McpErrorCode.CURSOR_INVALID, f"curseur refusé ({reason})")


def decode_cursor(cursor: str, intent: str) -> tuple[str, int]:
    """`(révision, décalage)` d'un curseur émis pour cette intention, sinon `mcp_cursor_invalid`."""

    if not isinstance(cursor, str) or not cursor or len(cursor) > MAX_CURSOR_CHARS:
        raise _cursor_error("illisible")
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        payload = json.loads(raw.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise _cursor_error("illisible") from None
    if not isinstance(payload, dict) or set(payload) != {"r", "o", "h"}:
        raise _cursor_error("illisible")
    revision, offset, digest = payload["r"], payload["o"], payload["h"]
    if not isinstance(revision, str) or type(offset) is not int or offset < 0 or not isinstance(digest, str):
        raise _cursor_error("illisible")
    if digest != intent_hash(intent):
        raise _cursor_error("émis pour une autre intention")
    return revision, offset


def check_limit(limit: object) -> int:
    if type(limit) is not int or not MIN_LIMIT <= limit <= MAX_LIMIT:
        raise McpPluginError(McpErrorCode.ARGUMENTS_INVALID, f"limit doit être un entier de {MIN_LIMIT} à {MAX_LIMIT}")
    return limit


def _select_recommended(ranked: Sequence[tuple[ToolEntry, float]]) -> tuple[list[ToolEntry], set[str]]:
    """Recommandés (ordre du classement) et ids trop gros pour l'être jamais."""

    too_large = {entry.id for entry, _ in ranked if size_of(entry.full()) > MAX_RECOMMENDED_BYTES}
    top = next((score for entry, score in ranked if entry.id not in too_large), 0.0)
    chosen: list[ToolEntry] = []
    natives = 0
    used = 2  # les crochets de la liste
    if top <= 0:
        return chosen, too_large
    for entry, score in ranked:
        if len(chosen) >= MAX_RECOMMENDED or score <= 0 or score < RECOMMENDED_RATIO * top:
            break
        if entry.id in too_large:
            continue
        native = entry.invocation == DIRECT_NATIVE
        if native and natives >= MAX_RECOMMENDED_NATIVES:
            continue
        cost = size_of(entry.full()) + (1 if chosen else 0)
        if used + cost > MAX_RECOMMENDED_BYTES:
            continue  # ne tient plus : reste dans `others`, le suivant peut encore tenir
        chosen.append(entry)
        natives += native
        used += cost
    return chosen, too_large


def build_list_response(intent: str, ranked: Sequence[tuple[ToolEntry, float]], *, catalog_revision: str,
                        cursor: str | None = None, limit: int = DEFAULT_LIMIT,
                        notes: Sequence[str] = ()) -> dict[str, Any]:
    """Réponse complète de `list_tools`, ≤ `MAX_RESPONSE_BYTES`. Lève `McpPluginError` (`mcp_cursor_invalid`...)."""

    limit = check_limit(limit)
    all_notes = list(notes)
    offset = 0
    if cursor is not None:
        revision, offset = decode_cursor(cursor, intent)
        if revision != catalog_revision:
            offset = 0
            all_notes.append(NOTE_CATALOG_CHANGED)
    recommended, too_large = _select_recommended(ranked)
    chosen = {entry.id for entry in recommended}
    paged = [entry for entry, _ in ranked if entry.invocation != DIRECT_NATIVE]
    remaining = [entry for entry in paged if entry.id not in chosen]
    offset = min(offset, len(remaining))
    response: dict[str, Any] = {
        "intent": intent,
        "catalog_revision": catalog_revision,
        "recommended": [entry.full() for entry in recommended] if offset == 0 else [],
        "others": [],
        "next_cursor": None,
        "total": len(paged),
        "native_total": len(ranked) - len(paged),
        "notes": all_notes,
    }
    page = remaining[offset: offset + limit]
    # Remplir tant que toute la réponse (curseur compris) tient dans le budget.
    for count in range(len(page) + 1):
        candidate_others = [entry.compact(too_large=entry.id in too_large) for entry in page[:count]]
        more = offset + count < len(remaining)
        candidate = {**response, "others": candidate_others,
                     "next_cursor": encode_cursor(catalog_revision, offset + count, intent) if more else None}
        if size_of(candidate) > MAX_RESPONSE_BYTES:
            break
        response = candidate
    return response

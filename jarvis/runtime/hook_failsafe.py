"""Échec fermé du hook pour les outils de relation, sans aucune dépendance de JARVIS (Slice 06, reprise QA N2).

Le hook `PreToolUse` est *fail-open* pour tout outil : une panne laisse l'appel partir intact (Slice 05). Pour un
outil de relation (`mcp__jarvis-workspace__relation_*`), partir sans l'identité apposée serait faux : le serveur le
refuserait (`relation_caller_unstamped`), mais l'agent mériterait de savoir pourquoi. Ce module rend alors un refus
explicite. Il n'importe que la bibliothèque standard : il sert aussi quand l'import du hook lui-même échoue
(`jarvis/app.py`, sous-commande `routing-hook`). `RELATION_TOOL_PREFIX` est égal à celui de `relation_runtime`
(vérifié par un test).
"""

from __future__ import annotations

import json
import sys
from typing import Any, Mapping

RELATION_TOOL_PREFIX = "mcp__jarvis-workspace__relation_"
FAILURE_REASON = ("Le hook de JARVIS est en panne : l'identité de l'appelant n'a pas pu être apposée, l'outil de "
                  "relation n'est pas appelé. Réessayez ; si la panne dure, dites dans votre compte rendu que la "
                  "relation n'a pas pu être nouée.")


def is_relation_call(event: Mapping[str, Any] | None) -> bool:
    name = event.get("tool_name") if isinstance(event, Mapping) else None
    return isinstance(name, str) and name.startswith(RELATION_TOOL_PREFIX)


def deny(reason: str = FAILURE_REASON) -> dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def main(raw: str | None = None) -> int:
    """Lire l'événement sur stdin ; refuser un outil de relation, se taire pour tout autre outil. Sortie 0."""

    try:
        text = sys.stdin.read() if raw is None else raw
        event = json.loads(text.lstrip("﻿") or "{}")
    except (OSError, ValueError, UnicodeDecodeError):
        return 0  # intentional: an unreadable event names no tool; any other tool stays fail-open
    if is_relation_call(event):
        sys.stdout.write(json.dumps(deny(), ensure_ascii=False))
    return 0

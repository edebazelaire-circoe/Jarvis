"""Échec fermé du hook pour les outils de relation, sans aucune dépendance de JARVIS (Slice 06, reprise QA N2).

Le hook `PreToolUse` est *fail-open* pour tout outil : une panne laisse l'appel partir intact (Slice 05). Pour un
outil de relation (`mcp__jarvis-workspace__relation_*`), partir sans l'identité apposée serait faux : le serveur le
refuserait (`relation_caller_unstamped`), mais l'agent mériterait de savoir pourquoi. Ce module rend alors un refus
explicite. Il n'importe que la bibliothèque standard : il sert aussi quand l'import du hook lui-même échoue
(`jarvis/app.py`, sous-commande `routing-hook`). Dans ce cas la panne est toujours dite (`report` : stderr et
`<runtime>/trace.jsonl`) ; le code de sortie reste 0 pour tout outil. `RELATION_TOOL_PREFIX` est égal à celui de
`relation_runtime` (vérifié par un test).
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Mapping

RELATION_TOOL_PREFIX = "mcp__jarvis-workspace__relation_"
FAILURE_REASON = ("Le hook de JARVIS est en panne : l'identité de l'appelant n'a pas pu être apposée, l'outil de "
                  "relation n'est pas appelé. Réessayez ; si la panne dure, dites dans votre compte rendu que la "
                  "relation n'a pas pu être nouée.")
FAILED_KIND = "agent.routing.failed"
FAILED_CODE = "routing_hook_import_failed"
_BOM = "\N{ZERO WIDTH NO-BREAK SPACE}"


def is_relation_call(event: Mapping[str, Any] | None) -> bool:
    name = event.get("tool_name") if isinstance(event, Mapping) else None
    return isinstance(name, str) and name.startswith(RELATION_TOOL_PREFIX)


def deny(reason: str = FAILURE_REASON) -> dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def report(runtime_root: str | Path | None, *, cause: str, tool: str, fail_closed: bool) -> None:
    """Dire la panne (reprise QA) : une ligne sur stderr, et un événement dans `<runtime>/trace.jsonl` et
    `errors.jsonl` quand le dossier runtime est connu. Bibliothèque standard seule ; ne lève jamais."""

    line = (f"jarvis routing-hook : hook indisponible ({cause}) ; "
            + ("outil de relation refusé." if fail_closed else "l'appel part sans routage ni déclaration."))
    try:
        sys.stderr.write(line + "\n")
    except (OSError, ValueError):
        pass  # intentional: stderr closed by the CLI; the trace below still records the failure
    if not runtime_root:
        return
    event = {"ts": datetime.now(timezone.utc).isoformat(), "kind": FAILED_KIND, "level": "error", "message": line,
             "data": {"code": FAILED_CODE, "exception_type": cause[:120], "tool": tool[:96],
                      "fail_closed": fail_closed}}
    for name in ("trace.jsonl", "errors.jsonl"):
        try:
            with (Path(runtime_root) / name).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError:
            pass  # intentional: an unwritable runtime folder must not change the hook's exit code


def main(raw: str | None = None, *, runtime_root: str | Path | None = None,
         cause: str = "import du hook en échec") -> int:
    """Lire l'événement sur stdin ; refuser un outil de relation, se taire pour tout autre outil. Sortie 0.

    La panne est toujours dite (stderr, et `trace.jsonl` si `runtime_root`) : sans cela, le routage, les
    déclarations et le suivi disparaîtraient sans bruit.
    """

    try:
        text = sys.stdin.read() if raw is None else raw
        event = json.loads(text.lstrip(_BOM) or "{}")
    except (OSError, ValueError, UnicodeDecodeError):
        event = {}  # intentional: an unreadable event names no tool; any other tool stays fail-open
    relation = is_relation_call(event)
    tool = event.get("tool_name") if isinstance(event, dict) else None
    report(runtime_root, cause=cause, tool=tool if isinstance(tool, str) else "", fail_closed=relation)
    if relation:
        sys.stdout.write(json.dumps(deny(), ensure_ascii=False))
    return 0

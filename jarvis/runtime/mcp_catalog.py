"""Catalogue canonique des outils MCP de Jarvis (contrat `docs/mcp/tool-contract.md` §2, §4.3, §5).

Un descripteur par outil, construit à partir de **deux sources et d'aucune
autre** :

1. l'**introspection des vrais serveurs FastMCP** : `build_server(tools=_Inert())`
   puis `list_tools()` (la surcharge stricte comprise, donc le schéma d'entrée tel
   qu'annoncé, `additionalProperties: false`). Les backends injectés sont
   inertes : **aucun outil n'est invoqué**, aucun réseau, aucune variable
   d'environnement ni aucun fichier de jeton n'est lu (`jarvis-drive` construit
   son backend Google à l'appel d'un outil seulement) ;
2. les **métadonnées partagées** `jarvis/runtime/mcp_tool_meta.py`, que
   l'enregistrement consomme aussi (annotations, `TOOL_NAMES`).

Les schémas du **texte** de `scene_inspect/query/get/capture` viennent de
`display_mcp.text_output_schemas()` (colonnes définies une fois en code).

La disponibilité (§4.3) n'est jamais stockée : `availability(...)` est une
fonction pure que l'API du Control Center (Slice 06) appelle à chaque requête
avec ce qu'elle tient déjà (réglages, cibles, instantané de l'agent).

Aucun méta-outil n'en sort vers le modèle : ce module sert des routes HTTP du
Control Center, jamais un serveur MCP.
"""

from __future__ import annotations

import json
from typing import Any, Literal, Mapping

from jarvis.runtime.mcp_tool_meta import (
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    SERVERS,
    ServerMeta,
    annotation_hints,
    server_meta,
)

AvailabilityState = Literal["advertised", "configured", "disabled", "known"]

#: Clé de l'instantané de l'agent (`ClaudeLocalAgent.snapshot()`) qui dit si le
#: processus en cours a reçu le `--mcp-config` du serveur. `display_tools` existe ;
#: la Slice 06 ajoute les deux autres (contrat §4.3).
AGENT_SNAPSHOT_FLAGS: dict[str, str] = {
    "jarvis-display": "display_tools",
    "jarvis-barehands": "barehands_tools",
    "jarvis-console": "console_tools",
}


class _Inert:
    """Backend injecté pour l'introspection : tout accès est une faute (le catalogue n'invoque rien)."""

    def __getattr__(self, name: str) -> Any:
        raise RuntimeError(f"catalog introspection must never invoke a tool (touched {name!r})")


def build_introspection_server(server: str) -> Any:
    """Le vrai serveur FastMCP de `server`, avec un backend inerte. Importe `mcp` à l'appel."""

    if server == "jarvis-display":
        from jarvis.runtime.display_mcp import build_server

        return build_server(tools=_Inert())  # type: ignore[arg-type]
    if server == "jarvis-console":
        from jarvis.runtime.settings_mcp import build_server

        return build_server(tools=_Inert())  # type: ignore[arg-type]
    if server == "jarvis-barehands":
        from jarvis.runtime.barehands_mcp import build_server

        return build_server(tools=_Inert())  # type: ignore[arg-type]
    if server == "jarvis-drive":
        from jarvis.runtime.drive_mcp import build_server

        return build_server()
    raise KeyError(f"unknown MCP server {server!r}")


# ------------------------------------------------------------------ paramètres

_CONSTRAINT_KEYS = ("enum", "const", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength",
                    "maxLength", "minItems", "maxItems", "pattern", "format")


def _resolve(schema: Mapping[str, Any], defs: Mapping[str, Any]) -> Mapping[str, Any]:
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        return defs.get(ref.rsplit("/", 1)[-1], {})
    return schema


def _render_type(schema: Mapping[str, Any], defs: Mapping[str, Any]) -> str:
    schema = _resolve(schema, defs)
    variants = schema.get("anyOf") or schema.get("oneOf")
    if variants:
        return " | ".join(_render_type(variant, defs) for variant in variants)
    if "enum" in schema:
        return "enum"
    kind = schema.get("type")
    if isinstance(kind, list):
        return " | ".join(str(item) for item in kind)
    if kind == "array":
        items = schema.get("items")
        return f"array<{_render_type(items, defs)}>" if isinstance(items, Mapping) else "array"
    if kind is None:
        return "any"
    return str(kind)


def _constraints(schema: Mapping[str, Any], defs: Mapping[str, Any]) -> dict[str, Any]:
    schema = _resolve(schema, defs)
    found: dict[str, Any] = {}
    for variant in schema.get("anyOf") or schema.get("oneOf") or ():
        for key, value in _constraints(variant, defs).items():
            found.setdefault(key, value)
    for key in _CONSTRAINT_KEYS:
        if key in schema:
            found[key] = schema[key]
    properties = schema.get("properties")
    if isinstance(properties, Mapping):
        found["keys"] = {
            name: {"type": _render_type(prop, defs), "required": name in schema.get("required", ()),
                   **_constraints(prop, defs)}
            for name, prop in properties.items()
        }
        if schema.get("additionalProperties") is False:
            found["closed"] = True
    items = schema.get("items")
    if isinstance(items, Mapping):
        nested = _constraints(items, defs)
        if nested:
            found["items"] = nested
    return found


def parameters_of(input_schema: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Un paramètre par propriété du schéma annoncé : requis, défaut (absent ≠ `null`), contraintes, description."""

    defs = input_schema.get("$defs", {})
    required = set(input_schema.get("required", ()))
    parameters = []
    for name, prop in input_schema.get("properties", {}).items():
        entry: dict[str, Any] = {
            "name": name,
            "type": _render_type(prop, defs),
            "required": name in required,
            "has_default": "default" in prop,
            "constraints": _constraints(prop, defs),
            "description": prop.get("description") or _resolve(prop, defs).get("description") or "",
        }
        if "default" in prop:
            entry["default"] = prop["default"]
        parameters.append(entry)
    return parameters


# ------------------------------------------------------------------ descripteurs

def model_visible_bytes(name: str, description: str, input_schema: Mapping[str, Any]) -> int:
    """Coût d'un outil dans le contexte du modèle (contrat §5.3) : nom + description + schéma d'entrée."""

    schema = json.dumps(input_schema, ensure_ascii=False, separators=(",", ":"))
    return len(name.encode("utf-8")) + len(description.encode("utf-8")) + len(schema.encode("utf-8"))


def _output(meta_format: str, tool: Any, name: str, text_schemas: Mapping[str, Any], notes: tuple[str, ...]) -> dict[str, Any]:
    advertised = tool.outputSchema
    if meta_format in ("json_text", "json_text+image"):
        schema = text_schemas[name]
    elif meta_format == "text_lines":
        schema = {"type": "string"}
    else:
        schema = advertised
    return {"format": meta_format, "schema": schema, "advertised_schema": advertised is not None, "notes": list(notes)}


def describe_tool(meta: ServerMeta, tool: Any, text_schemas: Mapping[str, Any]) -> dict[str, Any]:
    """Descripteur complet (§2) d'un outil introspecté ; sans `availability`, calculée à la requête."""

    info = meta.tools[tool.name]
    description = tool.description or ""
    annotations = tool.annotations.model_dump(exclude_none=True) if tool.annotations is not None else {}
    return {
        "name": tool.name,
        "server": meta.server,
        "qualified_name": f"mcp__{meta.server}__{tool.name}",
        "category": meta.category,
        "label": info.label,
        "summary": description.strip().split("\n", 1)[0].strip(),
        "description": description,
        "input_schema": tool.inputSchema,
        "parameters": parameters_of(tool.inputSchema),
        "parameter_rules": list(info.parameter_rules),
        "output": _output(info.output_format, tool, tool.name, text_schemas, info.output_notes),
        "side_effect": info.side_effect,
        "idempotent": info.idempotent,
        "atomicity": info.atomicity,
        "annotations": annotations,
        "deprecation": None if info.deprecation is None else info.deprecation.to_dict(),
        "context_bytes": model_visible_bytes(tool.name, description, tool.inputSchema),
    }


async def list_server_tools(server: str) -> list[Any]:
    """`tools/list` du vrai serveur (surcharge stricte comprise), sans rien invoquer."""

    return list(await build_introspection_server(server).list_tools())


async def build_catalog() -> dict[str, Any]:
    """Tous les serveurs natifs, décrits par introspection + métadonnées, dans l'ordre §8.

    Un serveur qui ne s'importe pas (dépendance facultative absente) donne une
    entrée `unavailable` avec la **classe** de l'erreur, jamais un descripteur deviné.
    """

    from jarvis.runtime.display_mcp import text_output_schemas

    text_schemas = text_output_schemas()
    servers: list[dict[str, Any]] = []
    tools: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    ordered = sorted(SERVERS, key=lambda meta: CATEGORY_ORDER.index(meta.category))
    for meta in ordered:
        try:
            listed = await list_server_tools(meta.server)
        except ImportError as exc:
            unavailable.append({"server": meta.server, "category": meta.category, "error": type(exc).__name__})
            continue
        described = [describe_tool(meta, tool, text_schemas) for tool in listed if tool.name in meta.tools]
        unknown = sorted({tool.name for tool in listed} - set(meta.tools))
        if unknown:
            # Garde de parité à l'exécution : un outil enregistré sans métadonnées
            # n'est pas décrit à moitié ; le test de parité échoue avant d'en arriver là.
            raise LookupError(f"{meta.server}: tools without shared metadata: {unknown}")
        tools.extend(described)
        servers.append({
            "server": meta.server,
            "module": meta.module,
            "category": meta.category,
            "category_label": CATEGORY_LABELS[meta.category],
            "condition": meta.condition,
            "registration": meta.registration,
            "tool_count": len(described),
            "context_bytes": sum(entry["context_bytes"] for entry in described),
        })
    return {"categories": [{"category": name, "label": CATEGORY_LABELS[name]} for name in CATEGORY_ORDER],
            "servers": servers, "tools": tools, "unavailable": unavailable}


_CACHE: dict[str, Any] | None = None


async def cached_catalog() -> dict[str, Any]:
    """Le catalogue, construit une fois par processus (clé : rien de contrôlé par l'utilisateur).

    Sans verrou : deux premières requêtes simultanées le construisent deux fois,
    à l'identique (introspection pure) ; la seconde écrase la première.
    """

    global _CACHE
    if _CACHE is None:
        _CACHE = await build_catalog()
    return _CACHE


# ------------------------------------------------------------------ disponibilité (§4.3)

def availability(
    server: str,
    *,
    condition_value: bool | None = None,
    target_present: bool | None = None,
    advertised: bool | None = None,
) -> dict[str, Any]:
    """État affiché d'un serveur, par précédence, à partir de trois faits indépendants (fonction pure).

    - `condition_value` : valeur courante du réglage `condition` du serveur
      (`scene.enabled`, `barehands.enabled`) ; ignorée quand le serveur n'en a pas ;
    - `target_present` : la cible du serveur existe au Control Center
      (`ControlCenter.display_mcp` / `barehands_mcp` / `console_mcp` non `None`) ;
    - `advertised` : le processus cerveau en cours a reçu son `--mcp-config`
      (`advertised_from_agent_snapshot`) ; `None` = inconnaissable.

    Un fait inconnu (`None`) ne se devine pas : `next_launch` reste `None`.
    `jarvis-drive` (déclaré par l'opérateur) est toujours `known`.
    """

    meta = server_meta(server)
    next_launch: Literal["configured", "disabled"] | None
    if meta.registration == "operator":
        next_launch, advertised = None, None
    elif target_present is None or (meta.condition is not None and condition_value is None):
        next_launch = None
    else:
        gate_open = meta.condition is None or bool(condition_value)
        next_launch = "configured" if gate_open and target_present else "disabled"
    pending_restart = advertised is not None and next_launch is not None and advertised != (next_launch == "configured")
    state: AvailabilityState
    if advertised is True:
        state = "advertised"
    elif next_launch == "configured":
        state = "configured"
    elif next_launch == "disabled":
        state = "disabled"
    else:
        state = "known"
    return {"state": state, "condition": meta.condition, "next_launch": next_launch, "advertised": advertised,
            "pending_restart": pending_restart}


def advertised_from_agent_snapshot(server: str, snapshot: Mapping[str, Any] | None) -> bool | None:
    """`advertised` lu dans l'instantané de l'agent : `False` cerveau arrêté, `None` quand l'instantané ne le dit pas."""

    flag = AGENT_SNAPSHOT_FLAGS.get(server)
    if flag is None or snapshot is None:
        return None
    if snapshot.get("state") != "running":
        return False
    if flag not in snapshot:
        return None
    return bool(snapshot[flag])


def expected_annotations(server: str, name: str) -> dict[str, bool]:
    """Annotations que l'enregistrement doit avoir posées (gate de parité §5.1 (2))."""

    return annotation_hints(server, name)

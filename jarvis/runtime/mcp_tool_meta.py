"""Métadonnées partagées des outils MCP de Jarvis : ce que l'introspection ne dit pas.

Contrat : `docs/mcp/tool-contract.md` (§2 descripteur, §3 catégories, §4 classes,
§5.1 source unique). **Ce module est la seule copie** de la catégorie, du libellé
humain, de la classe d'effet, de l'idempotence, de l'atomicité, des règles entre
paramètres, du format de sortie et de la dépréciation de chaque outil, et de la
condition de déclaration de chaque serveur.

Deux lecteurs, jamais d'autre copie :

- **l'enregistrement** : chaque `build_server` pose les annotations MCP
  (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) avec
  `tool_annotations(...)`, et prend ses `TOOL_NAMES` dans `tool_names(...)` ;
- **le catalogue** (`jarvis/runtime/mcp_catalog.py`) : descripteurs du Control
  Center, qui ajoutent ce que l'introspection des vrais serveurs rend (nom,
  description, schémas).

Module pur : aucun import de `mcp`, de `pydantic` ni des serveurs (ils
l'importent ; l'inverse ferait un cycle). Ajouter un outil : voir la section
« Ajouter un outil » du contrat.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Category = Literal["general", "scene", "settings", "barehands", "external"]
SideEffect = Literal["read", "write", "destructive"]
#: Contrat §4.2. Pas de `best_effort` : depuis la Slice 05, chaque lot de
#: `jarvis-display` est **une** commande de sélection (`atomic_batch`).
Atomicity = Literal["none", "single_command", "atomic_batch", "single_request", "external"]
#: Contrat §5.2. `untyped` : sortie ouverte, montrée comme telle (jamais embellie).
OutputFormat = Literal["structured", "json_text", "json_text+image", "text_lines", "untyped"]
Registration = Literal["jarvis", "operator"]

#: Ordre des onglets de l'inspecteur (contrat §3, §8).
CATEGORY_ORDER: tuple[Category, ...] = ("general", "scene", "settings", "barehands", "external")
CATEGORY_LABELS: dict[Category, str] = {
    "general": "Général",
    "scene": "Étoiles / Scène",
    "settings": "Réglages",
    "barehands": "Bare Hands",
    "external": "Externe",
}
MAX_LABEL_CHARS = 48


@dataclass(frozen=True)
class Deprecation:
    """Outil encore annoncé mais voué au retrait (contrat §7) : jamais un état de disponibilité."""

    replacement: str
    removal_condition: str
    since: str
    legacy_doc: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"replacement": self.replacement, "removal_condition": self.removal_condition,
                "since": self.since, "legacy_doc": self.legacy_doc}


@dataclass(frozen=True)
class ToolMeta:
    label: str
    side_effect: SideEffect
    idempotent: bool
    atomicity: Atomicity
    output_format: OutputFormat
    parameter_rules: tuple[str, ...] = ()
    output_notes: tuple[str, ...] = ()
    deprecation: Deprecation | None = None


@dataclass(frozen=True)
class ServerMeta:
    server: str
    module: str
    category: Category
    #: Réglage qui conditionne la déclaration au cerveau (contrat §4.3), ou `None`.
    condition: str | None
    registration: Registration
    #: Ordre = ordre d'enregistrement dans `build_server` (test de parité).
    tools: dict[str, ToolMeta] = field(default_factory=dict)


_READ_FIRST_RULE = "relire la scène (scene_inspect) dans le tour avant d'écrire"
_SELECTOR_RULES = (
    "select XOR object_ids (jamais les deux, au moins un)",
    "select : filtres de scene_query combinés (tous vrais)",
)
_BATCH_NOTE = ("une commande de sélection : tout ou rien, une révision au plus ; *_count exacts, "
               "listes d'ids bornées à 20 ; refus = erreur d'outil qui nomme chaque fautif")

DISPLAY = ServerMeta(
    server="jarvis-display", module="jarvis.runtime.display_mcp", category="scene",
    condition="scene.enabled", registration="jarvis",
    tools={
        "scene_inspect": ToolMeta(
            "Lire la scène affichée", "read", True, "none", "json_text",
            output_notes=("JSON compact borné à ~20 Ko (MAX_INSPECT_BYTES) ; colonnes positionnelles, "
                          "même légende que celle lue par le cerveau",)),
        "scene_query": ToolMeta(
            "Trouver des objets", "read", True, "none", "json_text",
            parameter_rules=("au moins un filtre", "include_hidden seulement avec near",
                             "filtres combinés (tous vrais)", "kind XOR kinds, exec_state XOR exec_states"),
            output_notes=("avec near : deux colonnes de plus, distance et overlap",)),
        "scene_get": ToolMeta(
            "Lire le détail d'objets", "read", True, "none", "json_text",
            output_notes=("JSON compact borné à ~20 Ko (MAX_GET_BYTES) ; ids absents dans not_found",)),
        "scene_create_object": ToolMeta(
            "Créer une note, une fenêtre, un groupe", "write", False, "single_command", "structured",
            output_notes=("identifiant neuf à chaque appel",)),
        "scene_update_object": ToolMeta(
            "Modifier un objet", "write", True, "single_command", "structured",
            parameter_rules=("au moins un champ à modifier", _READ_FIRST_RULE)),
        "scene_update_many": ToolMeta(
            "Masquer, réafficher, étiqueter un ensemble", "write", True, "atomic_batch", "structured",
            parameter_rules=(*_SELECTOR_RULES, "au moins un changement",
                             "confirm=true pour masquer la moitié ou plus des objets visibles", _READ_FIRST_RULE),
            output_notes=(_BATCH_NOTE,)),
        "scene_move": ToolMeta(
            "Déplacer un ensemble", "write", False, "atomic_batch", "structured",
            parameter_rules=(*_SELECTOR_RULES, "(dx, dy) ≠ (0, 0)", "pin : true seulement", _READ_FIRST_RULE),
            output_notes=(_BATCH_NOTE, "delta : écart demandé, écart effectif commun, clamped")),
        "scene_archive": ToolMeta(
            "Retirer des objets (définitif)", "destructive", True, "atomic_batch", "structured",
            parameter_rules=(*_SELECTOR_RULES, _READ_FIRST_RULE),
            output_notes=(_BATCH_NOTE, "cascade_ids : signaux runtime emportés avec leur étoile")),
        "scene_pin": ToolMeta(
            "Épingler ou désépingler", "write", True, "atomic_batch", "structured",
            parameter_rules=(*_SELECTOR_RULES, _READ_FIRST_RULE),
            output_notes=(_BATCH_NOTE,)),
        "scene_link": ToolMeta(
            "Relier deux objets", "write", True, "single_command", "structured",
            parameter_rules=("relation_id absent : dérivé du lien (même lien → duplicate)", _READ_FIRST_RULE)),
        "scene_unlink": ToolMeta(
            "Retirer un lien", "write", True, "single_command", "structured"),
        "scene_add_artifact": ToolMeta(
            "Ranger le résultat d'un travail", "write", True, "single_command", "structured",
            parameter_rules=("un artefact par (cible, catégorie) : un second appel complète le premier",
                             "representation et geometry ignorées quand l'artefact existe")),
        "scene_capture": ToolMeta(
            "Capturer l'écran de la scène", "read", True, "none", "json_text+image",
            output_notes=("bloc texte JSON puis bloc image PNG ; écrit un fichier dans runtime/scene-captures/ "
                          "(artefact de diagnostic, pas un effet)",)),
    },
)

CONSOLE = ServerMeta(
    server="jarvis-console", module="jarvis.runtime.settings_mcp", category="settings",
    condition=None, registration="jarvis",
    tools={
        "settings_describe": ToolMeta(
            "Lister les réglages", "read", True, "none", "text_lines",
            output_notes=("première ligne « N réglage(s) : », puis une ligne par réglage : "
                          "« - id · libellé = valeur » suivi de « (lecture seule) » éventuel et des valeurs "
                          "possibles « [a, b, …] », « [min..max] » ou « [true, false] »",)),
        "settings_get": ToolMeta(
            "Lire des réglages", "read", True, "none", "structured"),
        "settings_set": ToolMeta(
            "Changer un réglage", "write", True, "single_request", "structured",
            output_notes=("before/after relus après écriture ; restart_required quand l'effet attend un redémarrage",)),
    },
)

_FLOW_NOTE = ("un succès dit que le parcours a démarré (surimpression ouverte), pas qu'il est fini",)

BAREHANDS = ServerMeta(
    server="jarvis-barehands", module="jarvis.runtime.barehands_mcp", category="barehands",
    condition="barehands.enabled", registration="jarvis",
    tools={
        "barehands_activate": ToolMeta("Réveiller Bare Hands", "write", True, "single_request", "structured"),
        "barehands_deactivate": ToolMeta("Mettre Bare Hands en veille", "write", True, "single_request", "structured"),
        "barehands_calibrate": ToolMeta("Lancer la calibration", "write", False, "single_request", "structured",
                                        output_notes=_FLOW_NOTE),
        "barehands_tutorial": ToolMeta(
            "Tutoriel (ouvre la calibration)", "write", False, "single_request", "structured",
            output_notes=_FLOW_NOTE,
            deprecation=Deprecation(
                replacement="barehands_calibrate",
                removal_condition="prochain changement du contrat de commandes Bare Hands (les trois tables "
                                  "retirées dans un seul commit)",
                since="jarvis-bare-hands-ui-calibration-refinement, Slice 07B",
                legacy_doc="docs/legacy/barehands-tutorial-retirement.md",
            )),
        "barehands_exit_overlay": ToolMeta("Fermer la surimpression", "write", True, "single_request", "structured"),
    },
)

DRIVE = ServerMeta(
    server="jarvis-drive", module="jarvis.runtime.drive_mcp", category="external",
    condition=None, registration="operator",
    tools={
        "drive_search": ToolMeta("Chercher dans Drive", "read", True, "none", "untyped"),
        "drive_get": ToolMeta("Métadonnées d'un fichier Drive", "read", True, "none", "untyped"),
        "drive_read": ToolMeta("Lire un fichier Drive", "read", True, "none", "untyped"),
        "drive_create": ToolMeta("Créer un fichier Drive", "write", False, "external", "untyped"),
        "drive_update": ToolMeta("Remplacer le contenu d'un fichier Drive", "destructive", True, "external", "untyped"),
        "drive_delete": ToolMeta("Mettre un fichier Drive à la corbeille", "destructive", True, "external", "untyped"),
        "drive_share": ToolMeta("Partager un fichier Drive", "write", True, "external", "untyped"),
    },
)

#: Ordre d'affichage : catégorie (§3), puis ce tuple.
SERVERS: tuple[ServerMeta, ...] = (DISPLAY, CONSOLE, BAREHANDS, DRIVE)
_BY_SERVER = {meta.server: meta for meta in SERVERS}


def server_meta(server: str) -> ServerMeta:
    try:
        return _BY_SERVER[server]
    except KeyError:
        raise KeyError(f"unknown MCP server {server!r}") from None


def tool_names(server: str) -> tuple[str, ...]:
    """Noms des outils d'un serveur, dans l'ordre d'enregistrement."""

    return tuple(server_meta(server).tools)


def tool_meta(server: str, name: str) -> ToolMeta:
    return server_meta(server).tools[name]


def annotation_hints(server: str, name: str) -> dict[str, bool]:
    """Annotations MCP dérivées de la classe d'effet (contrat §4.1), en dict simple."""

    meta = tool_meta(server, name)
    hints = {"readOnlyHint": meta.side_effect == "read"}
    if meta.side_effect != "read":
        hints["destructiveHint"] = meta.side_effect == "destructive"
    hints["idempotentHint"] = meta.idempotent
    hints["openWorldHint"] = server_meta(server).category == "external"
    return hints


def tool_annotations(server: str, name: str) -> Any:
    """`mcp.types.ToolAnnotations` à passer à `@mcp.tool(annotations=...)`. Importe `mcp` à l'appel."""

    from mcp.types import ToolAnnotations

    return ToolAnnotations(**annotation_hints(server, name))

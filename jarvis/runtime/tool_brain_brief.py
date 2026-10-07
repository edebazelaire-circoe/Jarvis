"""Conscience du Tool Brain dans la consigne de tour de Jarvis (handoff jarvis-tool-brain-ui-orchestrator, Slice 4).

Contrat : `docs/tool-brain-contracts.md` §12. Le bloc dit à Jarvis, à **chaque tour** (le mode change à chaud,
comme `BRIEF_PRESENTATION_MODE`) :

1. qu'un Tool Brain existe et décide des outils d'écran et de leur moment ;
2. la **surface de capacités d'écran**, dérivée de `ToolMeta` (la même copie que le manifeste S2 : un test
   compare les deux) : Jarvis ne doit jamais déclarer une capacité absente parce qu'un autre cerveau
   l'exécute, ni en promettre une qui n'existe pas (navigation web : G1, S7) ;
3. **qui exécute** (`ownership`) : `jarvis_direct` (observation : le Tool Brain regarde, Jarvis agit comme
   avant, aucun double appel puisque le Tool Brain n'agit pas) ou `tool_brain` (délégué : Jarvis n'appelle pas
   les outils d'action d'écran, il déclare ses intentions) ;
4. comment déclarer une intention (`ui_intent_publish`, §11).

Le passage de `jarvis_direct` à `tool_brain` appartient à S8 (garde-fous) ; ici `tool_brain_ownership()` est la
couture et rend le mode d'observation. Le repli direct reste explicite dans le bloc délégué et observable par
les traces d'outils habituelles (`display.*`, `tool.call.*`) : aucune voie cachée.
"""

from __future__ import annotations

from typing import Any, Mapping

from jarvis.runtime.mcp_tool_meta import SERVERS

OWNERSHIP_DIRECT = "jarvis_direct"
OWNERSHIP_TOOL_BRAIN = "tool_brain"
OWNERSHIPS = (OWNERSHIP_DIRECT, OWNERSHIP_TOOL_BRAIN)
INTENT_TOOL = "ui_intent_publish"
#: Capacités d'écran qui n'existent pas (aucune depuis S7 : la navigation web de présentation, gap G1, existe dans
#: `jarvis-surface` ; elle est du Tool Brain seul, voir `delegated_only`). À dire telles quelles, jamais à promettre.
MISSING_SURFACES: tuple[str, ...] = ()
BRIEF_HEADER = "[Tool Brain — écran]"
#: Plafond du rendu (octets UTF-8) : ajouté à chaque tour, il doit rester discret.
MAX_BRIEF_BYTES = 1900


def tool_brain_ownership(settings: Mapping[str, Any] | None = None) -> str:
    """Qui exécute l'écran. S4 : toujours l'observation ; S8 branche ici le réglage de propriété."""

    return OWNERSHIP_DIRECT


def ui_capability_surface() -> dict[str, dict[str, list[str]]]:
    """`{surface: {"read": [...], "act": [...], "irreversible": [...]}}`, lu dans `ToolMeta` (jamais recopié)."""

    surface: dict[str, dict[str, list[str]]] = {}
    for server in SERVERS:
        for name, meta in server.tools.items():
            if meta.ui_surface is None:
                continue
            entry = surface.setdefault(meta.ui_surface, {"read": [], "act": [], "irreversible": []})
            entry["read" if meta.side_effect == "read" else "act"].append(name)
            if meta.reversibility == "irreversible":
                entry["irreversible"].append(name)
    return surface


def tool_brain_brief_block(ownership: str | None = None) -> dict[str, Any]:
    """Valeur de `context["tool_brain"]` : données seulement, la formulation est rendue ici (Décision 23)."""

    mode = ownership or tool_brain_ownership()
    if mode not in OWNERSHIPS:
        raise ValueError(f"ownership must be one of {OWNERSHIPS}")
    return {"ownership": mode, "surface": ui_capability_surface(), "missing": list(MISSING_SURFACES),
            "intent_tool": INTENT_TOOL, "delegated_only": delegated_only_surfaces()}


def delegated_only_surfaces() -> list[str]:
    """Surfaces d'écran dont tous les outils sont du Tool Brain seul (`registration="tool_brain"`, jamais déclarés à Jarvis)."""

    owners: dict[str, set[bool]] = {}
    for server in SERVERS:
        for meta in server.tools.values():
            if meta.ui_surface is not None:
                owners.setdefault(meta.ui_surface, set()).add(server.registration == "tool_brain")
    return sorted(key for key, flags in owners.items() if flags == {True})


_SURFACE_LABELS = {"scene": "scène", "board": "Boards", "browser": "navigation web"}


def render_tool_brain_brief(block: Any) -> list[str]:
    """Lignes du bloc ; rien quand il manque ou est hors contrat (le brief est alors celui d'avant)."""

    if not isinstance(block, dict) or block.get("ownership") not in OWNERSHIPS or not isinstance(block.get("surface"), dict):
        return []
    surface: dict[str, dict[str, list[str]]] = block["surface"]
    only_tool_brain = {str(x) for x in block.get("delegated_only", ())}
    parts, actions, final = [], [], []
    for key, entry in surface.items():
        if not isinstance(entry, dict):
            continue
        read, act = [str(x) for x in entry.get("read", ())], [str(x) for x in entry.get("act", ())]
        final.extend(str(x) for x in entry.get("irreversible", ()))
        label = _SURFACE_LABELS.get(key, str(key))
        if key in only_tool_brain:
            # Connue de Jarvis (il ne dit jamais « impossible »), mais jamais dans ses outils : pas d'appel direct.
            parts.append(f"{label} (Tool Brain seul : {', '.join(read + act)})")
            continue
        actions.extend(act)
        parts.append(f"{label} (lire : {', '.join(read) or 'rien'} ; agir : {', '.join(act) or 'rien'})")
    missing = "; ".join(str(x) for x in block.get("missing", ()) if str(x).strip())
    lines = [
        BRIEF_HEADER,
        "Un Tool Brain existe : il décide quels outils d'écran appeler et quand, d'après ce que tu dis et ce que "
        "l'utilisateur voit. Tu connais toutes les capacités d'écran du système ; ne prétends jamais qu'une "
        "d'elles manque parce que c'est lui qui l'exécute.",
        "Capacités d'écran : " + " ; ".join(parts) + "."
        + (f" Définitif : {', '.join(final)}." if final else "")
        + (f" N'existe pas encore : {missing} ; dis-le franchement, ne le promets pas." if missing else ""),
    ]
    if block["ownership"] == OWNERSHIP_TOOL_BRAIN:
        lines.append(
            "Mode actuel : délégué. Le Tool Brain exécute l'affichage : n'appelle pas les outils d'action d'écran "
            f"({', '.join(actions)}) pour l'affichage courant ; la lecture reste à toi. Repli direct seulement si "
            "l'utilisateur demande un geste précis qu'une intention ne dit pas, ou si le Tool Brain est en panne "
            "(dis-le).")
    else:
        lines.append(
            "Mode actuel : observation. Le Tool Brain regarde mais n'agit pas encore : exécute toi-même l'affichage "
            "avec ces outils, comme avant, une seule fois par geste."
            + (" La navigation web n'existe qu'en mode délégué : dis-le, ne la promets pas." if only_tool_brain else ""))
    tool = block.get("intent_tool") or INTENT_TOOL
    lines.append(
        f"Intention : {tool}(kind reveal|attention|relevance|dismiss, refs [{{kind object|board, id}}] lus dans "
        "scene_inspect ou board_list, jamais inventés, subject si pas d'id, timing with_speech (défaut)|now|"
        "after_speech, paragraph = n° base 0 du paragraphe de ta réponse). Ce que l'utilisateur doit voir, jamais "
        "où ni comment : ni coordonnées ni commande. Appelle-la pendant ton tour, avant ta réponse, et sans en "
        "parler à l'oral. Si ta réponse a plusieurs paragraphes, une ligne vide les sépare : l'écran se cale dessus.")
    return lines


__all__ = [
    "BRIEF_HEADER", "INTENT_TOOL", "MAX_BRIEF_BYTES", "MISSING_SURFACES", "OWNERSHIPS", "OWNERSHIP_DIRECT",
    "OWNERSHIP_TOOL_BRAIN", "render_tool_brain_brief", "tool_brain_brief_block", "tool_brain_ownership",
    "ui_capability_surface",
]

"""Qualité de restitution d'un Mission Owner : règle de jugement, garde-fous, repli (Slice 11).

Handoff jarvis-organic-agent-orchestration, décision D23 : un rapport ou une comparaison sérieuse se livre
sur une surface riche **existante** (`jarvis.document`, `jarvis.table`, `jarvis.checklist`, un prefab plus
riche trouvé par `prefab_search`), jamais en mur de texte ; une réponse simple reste simple. Ce module ne
construit aucun rendu : il dit au Mission Owner quand et comment utiliser les outils `jarvis-display` qu'il a
déjà (`scene_create_object` avec `prefab`), et il prépare le repli quand un affichage échoue.

La forme se décide sur le **résultat réel**, jamais sur les mots de la demande (arbitrage de l'agent 0 après
la QA de la Slice 11 : un indice par mots-clés classait juste 46 % d'un corpus de 64 demandes réalistes).

Quatre choses, toutes pures (aucune entrée-sortie) :

- **consigne de restitution** (`delivery_brief`) : le paragraphe « RESTITUTION (JARVIS) » que le hook place
  en tête du bloc « RESPONSABILITÉ DE MISSION (JARVIS) » (`agent_orchestration.mission_brief`). Bornes des
  prefabs de base recopiées de la dernière version livrée de leurs manifestes, égalité vérifiée par
  `tests/unit/test_delivery_quality.py` ;
- **note de compte rendu** (`REPORT_NOTE`) : la ligne que la charte reçoit, pour un Mission Owner seulement,
  juste après sa consigne de compte rendu (`agent_charter.sign_brief(report_note=)`) : la synthèse s'affiche,
  le compte rendu en donne l'`object_id` et la conclusion ;
- **repli structuré** (`fallback_note`) : le texte joint à l'erreur d'un affichage de prefab
  (`display_mcp.SceneDisplayTools`), qui dit l'état réel de l'écran : création refusée (rien de nouveau),
  mise à jour refusée (la fenêtre garde son contenu précédent) ou issue inconnue (relire la scène) ;
- **contenu lisible** (`readable_content`) : les données du prefab sous une forme écrite prête à livrer.

Le texte du repli est neutre vis-à-vis de l'appelant : le serveur d'affichage ne distingue pas le cerveau
d'un sous-agent (même acteur `brain`).

Contrat : `docs/subagent-roles.md` §5bis, `docs/prefabs.md` « Consumers ».
"""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any, Literal

#: Tête du paragraphe de restitution ; sert aussi à ne jamais le doubler.
DELIVERY_MARK = "RESTITUTION (JARVIS)"
#: Tête du repli joint à une erreur d'affichage de prefab.
FALLBACK_MARK = "REPLI DE RESTITUTION (JARVIS)"
#: Outils d'affichage d'un Mission Owner (serveur `jarvis-display`, noms complets vus par un sous-agent).
DISPLAY_TOOL = "mcp__jarvis-display__scene_create_object"
SEARCH_TOOL = "mcp__jarvis-display__prefab_search"
#: Borne du contenu prêt à l'emploi joint à un repli. Le journal `agent.event` recopie le résultat d'outil entier
#: (reprise QA N7) : la borne reste courte.
MAX_FALLBACK_CHARS = 4000

#: Bornes des prefabs de base, recopiées de la dernière version de leurs manifestes (test de conformité).
TABLE_MAX_COLUMNS = 8
TABLE_MAX_COLUMN_LABEL = 40
TABLE_MAX_ROWS = 64
TABLE_MAX_CELLS_PER_ROW = 8
TABLE_MAX_CELL = 200
DOCUMENT_MAX_BODY = 12000
CHECKLIST_MAX_ITEMS = 64
CHECKLIST_MAX_ID = 64
CHECKLIST_MAX_LABEL = 200
CHECKLIST_MAX_NOTE = 500

#: Codes d'une panne dont on ne sait pas si l'écran a changé (transport, expiration, réponse illisible), tels que
#: les lèvent `display_mcp` / `scene_view.classify_scene_call_failure` / `display_prefabs` pour une création ou une
#: mise à jour. `core_refused` en fait partie : `classify_scene_call_failure` le donne à toute réponse d'erreur HTTP
#: de Core hors 400/413 et hors codes de scène, **5xx compris**, et le statut n'arrive pas jusqu'ici ; une erreur
#: interne de Core après application ne peut pas être exclue, donc l'issue est dite inconnue (reprise QA).
#: `protocol_error` n'y figure pas : seul un lot (`scene_update_many`) le lève, jamais une création ni une mise à jour.
#: Tout autre code est un refus sûr, sans application : vérification avant envoi (`invalid_argument`,
#: `payload_too_large`, `prefab_unavailable`, `ui_delegated`), commande non envoyée (`command_not_sent`), refus
#: de catalogue (`unknown_prefab`…), refus du domaine de la scène dans une réponse 200 (`scene_refused`, issue
#: `invalid` / `rejected_authority` : rien d'appliqué par contrat du domaine), ou 400/413/503 de scène dont Core
#: garantit qu'ils n'appliquent rien (`scene_unavailable`, `scene_persist_failed` : « Rien n'a été appliqué »).
UNKNOWN_OUTCOME_CODES = frozenset({
    "core_timeout", "core_unreachable", "core_bad_answer", "invalid_scene_response", "core_refused",
    "display_internal_error",
})
#: Motifs d'un refus de la scène qui disent qu'aucune fenêtre active ne porte cet identifiant.
MISSING_TARGET_REASONS = frozenset({"unknown_object", "object_archived"})

#: Ligne ajoutée à la charte d'un Mission Owner, juste après sa consigne de compte rendu (cohérence N8).
REPORT_NOTE = (
    "Pour un Mission Owner : un résultat structuré s'affiche à l'écran (voir « RESTITUTION (JARVIS) ») ; le "
    "compte rendu donne alors l'object_id et la conclusion, pas la synthèse entière."
)


def delivery_brief() -> str:
    """Le paragraphe de restitution d'un Mission Owner : une règle de jugement sur le résultat réel.

    Il dit quand une surface riche sert, laquelle, comment l'afficher et quoi faire si l'affichage échoue ; il
    n'impose ni gabarit ni nombre d'artefacts, et ne lit pas les mots de la demande.
    """

    return "\n".join((
        DELIVERY_MARK,
        "L'utilisateur ne lit pas votre compte rendu : le cerveau vocal le lui résume en quelques phrases. Ce qui "
        "doit être relu n'atteint l'utilisateur que s'il est affiché. Une fois le résultat obtenu, jugez sa forme "
        "sur lui, pas sur les mots de la demande :",
        "- Il tient en une ou deux phrases (fait, chiffre, oui/non, correction faite) : dites-le dans le compte "
        "rendu, sans fenêtre.",
        "- Il est structuré (plusieurs options ou critères à comparer, rapport, état des lieux, bilan, audit, "
        "synthèse de recherche, explication détaillée, liste d'actions, tout ce que l'utilisateur voudra relire) : "
        "affichez-le, par la surface adaptée :",
        f"  - comparaison : jarvis.table, data {{columns: [{{label ≤ {TABLE_MAX_COLUMN_LABEL} car., align?}}], "
        f"rows: [[cellules]]}} ; {TABLE_MAX_COLUMNS} colonnes, {TABLE_MAX_ROWS} lignes, "
        f"{TABLE_MAX_CELLS_PER_ROW} cellules par ligne au plus ; chaque cellule est une chaîne ≤ "
        f"{TABLE_MAX_CELL} car. Une recommandation de plus de quelques lignes va dans un jarvis.document à côté ;",
        f"  - rapport, état des lieux, bilan, synthèse : jarvis.document, data {{body: Markdown ≤ "
        f"{DOCUMENT_MAX_BODY} car.}}, structuré (titres, listes, sources nommées) ;",
        f"  - liste d'actions : jarvis.checklist, data {{items: [{{id ≤ {CHECKLIST_MAX_ID} car., label ≤ "
        f"{CHECKLIST_MAX_LABEL} car., done?, note? ≤ {CHECKLIST_MAX_NOTE} car.}}]}}, {CHECKLIST_MAX_ITEMS} "
        "éléments au plus ;",
        f"  - une surface plus riche existe peut-être : {SEARCH_TOOL}.",
        f"- Pour afficher : {DISPLAY_TOOL} (kind window, category, title, prefab {{prefab_id, data}}) ; s'il "
        f"n'est pas chargé, chargez-le avec ToolSearch (« select:{DISPLAY_TOOL} »).",
        "- L'affichage n'est fait que si l'outil rend un object_id. Sur un refus ou une erreur, suivez le repli "
        "joint à l'erreur : ne dites jamais affiché ce qui ne l'est pas, livrez le contenu en Markdown structuré "
        "et dites en une phrase ce qui a échoué. Sans ces outils dans votre session, même chose.",
        "- Après un affichage réussi, le compte rendu donne l'object_id et la conclusion en quelques lignes, sans "
        "recopier ce qui est affiché.",
    ))


# ------------------------------------------------------------------ repli

def _cell(value: object, limit: int = TABLE_MAX_CELL) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(text.split()).replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _table_markdown(data: Mapping[str, Any]) -> str | None:
    columns = data.get("columns")
    if not isinstance(columns, list) or not columns:
        return None
    labels = [_cell(column.get("label", "") if isinstance(column, Mapping) else column, 80) for column in columns]
    lines = ["| " + " | ".join(labels) + " |", "|" + "---|" * len(labels)]
    rows = data.get("rows")
    for row in rows if isinstance(rows, list) else []:
        cells = [_cell(value) for value in row] if isinstance(row, list) else [_cell(row)]
        cells = (cells + [""] * len(labels))[: max(len(labels), len(cells))]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _checklist_markdown(data: Mapping[str, Any]) -> str | None:
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return None
    lines = []
    for item in items:
        if not isinstance(item, Mapping):
            lines.append(f"- [ ] {_cell(item)}")
            continue
        mark = "x" if item.get("done") is True else " "
        note = f" — {_cell(item['note'])}" if item.get("note") else ""
        lines.append(f"- [{mark}] {_cell(item.get('label', ''))}{note}")
    return "\n".join(lines)


def readable_content(prefab_id: str, data: object) -> str | None:
    """Le contenu de `data` sous une forme lisible sans fenêtre, ou `None` s'il n'y a rien à livrer.

    `jarvis.table` : tableau Markdown ; `jarvis.document`, `jarvis.window`, `jarvis.browser` : le corps ;
    `jarvis.checklist` : liste à cocher ; tout autre prefab : ses données en JSON indenté. Borné à
    `MAX_FALLBACK_CHARS`, la coupure est dite.
    """

    if not isinstance(data, Mapping) or not data:
        return None
    text: str | None
    if prefab_id == "jarvis.table":
        text = _table_markdown(data)
    elif prefab_id == "jarvis.checklist":
        text = _checklist_markdown(data)
    elif isinstance(data.get("body"), str) and data["body"].strip():
        text = data["body"].strip()
    else:
        text = None
    if text is None:
        text = json.dumps(data, ensure_ascii=False, indent=1, default=str)
    if len(text) > MAX_FALLBACK_CHARS:
        text = text[:MAX_FALLBACK_CHARS].rstrip() + f"\n[… coupé à {MAX_FALLBACK_CHARS} caractères]"
    return text


def screen_state(operation: Literal["create", "update"], code: str, object_id: str | None,
                 reason: str | None = None) -> str:
    """Ce qui est réellement à l'écran après l'échec `code` (motif `reason`) d'une création ou d'une mise à jour."""

    if code in UNKNOWN_OUTCOME_CODES:
        return ("L'état de l'affichage est inconnu (la commande a pu partir ou non) : relisez la scène "
                "(scene_get ou scene_inspect) avant d'en parler ou de réessayer.")
    if operation == "update" and reason in MISSING_TARGET_REASONS:
        name = object_id or "visée"
        why = "elle est archivée" if reason == "object_archived" else "l'identifiant ne désigne aucun objet actif"
        return (f"Aucune fenêtre {name} n'existe ({why}) ; rien n'est affiché sous ce nom. Relisez la scène "
                "(scene_inspect) pour retrouver la bonne fenêtre, ou créez-en une avec scene_create_object.")
    if operation == "update":
        target = f"la fenêtre {object_id}" if object_id else "la fenêtre visée"
        return (f"La mise à jour n'est pas appliquée : {target} garde son contenu précédent. Si la cause tient "
                "aux données (bornes, schéma), corrigez-les et réessayez ; la remarque scene_changed éventuelle "
                "ne concerne que d'autres objets et n'empêche pas ce nouvel essai.")
    return ("La fenêtre n'a pas été créée : rien de nouveau n'est à l'écran, ne dites pas le contraire. Si la cause "
            "tient aux données (bornes, schéma), corrigez-les et réessayez ; la remarque scene_changed éventuelle "
            "ne concerne que d'autres objets et n'empêche pas ce nouvel essai.")


def fallback_note(prefab: object, *, operation: Literal["create", "update"] = "create", code: str = "",
                  object_id: str | None = None, reason: str | None = None) -> str:
    """Le repli joint à l'erreur d'un affichage de prefab (`prefab` : l'argument de l'outil, tel que reçu).

    Neutre vis-à-vis de l'appelant (cerveau ou sous-agent) : l'état réel de l'écran, puis le contenu sous une
    forme écrite, à résumer s'il est dit à voix haute.
    """

    given = prefab if isinstance(prefab, Mapping) else {}
    prefab_id = given.get("prefab_id")
    lines = [FALLBACK_MARK, screen_state(operation, code, object_id, reason)]
    if not isinstance(prefab_id, str) or not prefab_id.strip():
        lines.append("L'argument prefab ne nomme aucun prefab_id : donnez-en un (prefab_search) ou livrez le "
                     "contenu autrement.")
        return "\n".join(lines)
    lines.append(f"Prefab visé : {prefab_id}. S'il n'est pas corrigé, livrez le contenu autrement que par cette "
                 "fenêtre et dites en une phrase que l'affichage a échoué, avec sa cause.")
    content = readable_content(prefab_id, given.get("data"))
    if content is not None:
        lines += ["Contenu prêt à livrer (forme écrite ; à l'oral, résumez-le au lieu de le lire) :", content]
    return "\n".join(lines)

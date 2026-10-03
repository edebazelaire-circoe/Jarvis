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

Category = Literal["general", "scene", "settings", "workspace", "capture", "barehands", "external"]
SideEffect = Literal["read", "write", "destructive"]
#: Contrat §4.2. Pas de `best_effort` : depuis la Slice 05, chaque lot de
#: `jarvis-display` est **une** commande de sélection (`atomic_batch`).
Atomicity = Literal["none", "single_command", "atomic_batch", "single_request", "external"]
#: Contrat §5.2. `untyped` : sortie ouverte, montrée comme telle (jamais embellie).
OutputFormat = Literal["structured", "json_text", "json_text+image", "text_lines", "untyped"]
#: `managed` : serveur d'un plugin MCP distant dans les vues fusionnées
#: (`mcp_catalog.merge_external`) ; jamais dans `SERVERS` (generic-mcp-plugin-runtime, Slice 04).
Registration = Literal["jarvis", "operator", "managed"]

#: Ordre des onglets de l'inspecteur (contrat §3, §8).
CATEGORY_ORDER: tuple[Category, ...] = ("general", "scene", "settings", "workspace", "capture", "barehands",
                                         "external")
CATEGORY_LABELS: dict[Category, str] = {
    "general": "Général",
    "scene": "Étoiles / Scène",
    "settings": "Réglages",
    #: `jarvis-workspace` (board-memory-workspace-inspector, Slice 06) : Boards, Sessions, mémoire, liens.
    "workspace": "Boards et mémoire",
    #: `jarvis-capture` (session-context-recording, Slice 09) : Contexts, enregistrements, preuves.
    "capture": "Captures et preuves",
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
_SESSION_RULE = "séance de calibration ouverte à l'écran, sinon refus barehands_calibration_inactive"

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
        # Le Tester (tâche adaptative, Slice 10) : ouvre l'écran d'accueil du
        # banc à lecture seule, par la porte de son bouton. Même contrat que
        # la calibration : un succès dit que la surimpression est ouverte.
        "barehands_test": ToolMeta("Ouvrir le test Bare Hands", "write", False, "single_request", "structured",
                                   output_notes=_FLOW_NOTE),
        # Calibration (tâche adaptative, Slice 06, décisions 50 à 55) : toujours
        # déclarés avec le serveur, refusés hors d'une séance ouverte à l'écran
        # (`barehands_calibration_inactive`). Ce qu'ils écrivent vit dans la
        # séance de la page (décision 41), sauf `calibration_accept_trial`, seule
        # persistance, et seulement sur accord de l'utilisateur.
        "calibration_status": ToolMeta(
            "Lire la séance de calibration", "read", True, "none", "structured",
            parameter_rules=(_SESSION_RULE,),
            output_notes=("mesures par référence, chiffrées par la page ; 24 dernières lignes, reçu ≤ 16 Ko",)),
        "calibration_record_feedback": ToolMeta(
            "Noter un ressenti de l'utilisateur", "write", False, "single_request", "structured",
            parameter_rules=(_SESSION_RULE, "1 à 3 catégories ; fine/unclear seules", "texte dit, mot pour mot")),
        "calibration_propose_hypothesis": ToolMeta(
            "Proposer une cause à tester", "write", False, "single_request", "structured",
            parameter_rules=(_SESSION_RULE, "au moins une preuve ou un retour cité",
                             "une cause démentie ne revient qu'avec une preuve nouvelle"),
            output_notes=("valeur de chaque preuve calculée par le code, jamais recopiée",)),
        "calibration_prepare_trial": ToolMeta(
            "Préparer une proposition (non appliquée)", "write", False, "single_request", "structured",
            parameter_rules=(_SESSION_RULE, "sur la revue d'un exercice", "clés du patch parmi celles de la cause",
                             "un essai à la fois : le précédent jugé ou annulé", "summary en mots d'utilisateur"),
            output_notes=("proposal affichée dans le panneau, rien n'est appliqué",)),
        "calibration_commit_proposal": ToolMeta(
            "Valider une proposition (accord utilisateur)", "write", False, "single_request", "structured",
            parameter_rules=(_SESSION_RULE, "user_quote : mots de l'utilisateur, dits depuis la proposition",
                             "action : rerun (refaire l'exercice) ou continue (garder sans revérifier)"),
            output_notes=("transaction du runtime : steps = ce qui a réellement été fait, valeurs relues",)),
        "calibration_resolve_trial": ToolMeta(
            "Juger un essai sur les mesures", "write", False, "single_request", "structured",
            parameter_rules=(_SESSION_RULE, "mesures après = prises sous cet essai, avant = sous l'état d'avant"),
            output_notes=("deltas calculés par le code ; confiance mise à jour par règle fixe",)),
        "calibration_rollback_trial": ToolMeta(
            "Annuler le dernier essai", "write", False, "single_request", "structured",
            parameter_rules=(_SESSION_RULE,)),
        "calibration_accept_trial": ToolMeta(
            "Garder le réglage essayé", "write", False, "single_request", "structured",
            parameter_rules=(_SESSION_RULE, "user_quote : mots de l'utilisateur, dits depuis l'essai"),
            output_notes=("seule écriture persistante de la séance",)),
        "calibration_rerun_exercise": ToolMeta(
            "Refaire l'exercice", "write", False, "single_request", "structured",
            parameter_rules=(_SESSION_RULE,)),
        "calibration_next_exercise": ToolMeta(
            "Valider ou passer l'exercice", "write", False, "single_request", "structured",
            parameter_rules=(_SESSION_RULE, "reason : passe l'exercice (mesure non gardée) ; exigée pour un "
                             "exercice non terminé ou échoué ; sans elle, une revue réussie est validée"),
            output_notes=("decision : validated ou skipped — ce qui a réellement été fait",)),
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

# Passerelle de découverte (generic-mcp-plugin-runtime, Slice 04 ; `docs/mcp/plugins.md` §6) :
# le seul serveur qui expose des méta-outils de catalogue (tool-contract §5.3).
TOOLS = ServerMeta(
    server="jarvis-tools", module="jarvis.runtime.tools_gateway_mcp", category="general",
    condition=None, registration="jarvis",
    tools={
        "list_tools": ToolMeta(
            "Trouver les outils utiles", "read", True, "none", "structured",
            parameter_rules=("cursor : seulement avec la même intention",),
            output_notes=("≤ 5 recommandés complets, le reste compact ; réponse ≤ 24 576 octets",)),
        "call_tool": ToolMeta(
            "Appeler un outil de plugin", "destructive", False, "external", "untyped",
            parameter_rules=("tool_id d'un plugin (<plugin>.<outil>) ; un natif s'appelle par son nom",),
            output_notes=("texte ≤ 32 Kio (truncated) ; erreur distante masquée ≤ 4 Kio",)),
    },
)

# Boards, Sessions, mémoire et liens (board-memory-workspace-inspector, Slice 06, R5) : façade sur
# `/api/boards*`, `/api/sessions*` et `/api/workspace/*` du Control Center ; Core possède tout.
# Les lectures n'activent jamais rien (`docs/boards.md` › *Non-activating inspection*).
_NAMED_BOARD_RULE = "board_id explicite : jamais le Board actif par défaut, et rien n'est activé"
_MEMORY_PATH_RULE = "path relatif à memory/ (POSIX, ≤ 240 caractères, sans ..)"
WORKSPACE = ServerMeta(
    server="jarvis-workspace", module="jarvis.runtime.workspace_mcp", category="workspace",
    condition=None, registration="jarvis",
    tools={
        # Boards et Sessions (handoff board-session, Slice 05 ; déplacés de `jarvis-console`
        # sans alias) : mêmes routes que l'écran (`/api/boards*`, `/api/sessions*`).
        "board_list": ToolMeta(
            "Lister les Boards", "read", True, "none", "structured",
            output_notes=("une ligne par Board, sans son contenu (board_get le rend)",)),
        "board_get": ToolMeta("Lire un Board", "read", True, "none", "structured"),
        "board_get_active": ToolMeta("Lire le Board actif", "read", True, "none", "structured"),
        "board_create": ToolMeta(
            "Créer un Board", "write", False, "single_request", "structured",
            parameter_rules=("ne bascule pas : board_switch ensuite si l'utilisateur veut y aller",),
            output_notes=("identifiant neuf à chaque appel",)),
        "board_update": ToolMeta(
            "Modifier un Board", "write", True, "single_request", "structured",
            parameter_rules=("au moins un champ", "une liste de références remplace la précédente entière")),
        "board_archive": ToolMeta(
            "Archiver un Board (définitif)", "destructive", True, "single_request", "structured",
            parameter_rules=("jamais le Board actif (board_is_active)",)),
        "board_switch": ToolMeta(
            "Basculer sur un Board", "write", True, "single_request", "structured",
            parameter_rules=("origin=brain : différée jusqu'à la fin du tour en cours",
                             "un second appel du même tour remplace le premier (replaced_board_id) ; "
                             "vers le Board actif, il annule la bascule en attente"),
            output_notes=("status : scheduled (fin du tour), applied (hors tour), unchanged (déjà actif, "
                          "rien en attente) ou unknown (non confirmé : relis session_current)",
                          "note : une phrase courte à dire telle quelle")),
        "session_current": ToolMeta("Lire la Session en cours", "read", True, "none", "structured"),
        "session_new": ToolMeta(
            "Ouvrir une nouvelle Session", "write", False, "single_request", "structured",
            parameter_rules=("origin=brain : différée jusqu'à la fin du tour en cours",
                             "un second appel du même tour est fusionné (merged) : une seule Session s'ouvre",
                             "hors tour, vise la Session lue juste avant : jamais deux Sessions (session_closed)"),
            output_notes=("status : scheduled (fin du tour), applied (hors tour) ou unknown (non confirmé) ; "
                          "Boards et tâches inchangés",
                          "note : une phrase courte à dire telle quelle")),
        "session_list": ToolMeta("Lister les Sessions passées", "read", True, "none", "structured",
                                 parameter_rules=("cursor : seulement avec la même liste",),
                                 output_notes=("≤ 20 par page, la plus récente d'abord",)),
        "session_get": ToolMeta("Lire une Session (Boards, Contexts)", "read", True, "none", "structured",
                                output_notes=("≤ 20 Boards, 10 Contexts les plus récents ; problems = codes "
                                              "d'incohérence",)),
        "board_inspect": ToolMeta("Inspecter un Board sans l'ouvrir", "read", True, "none", "structured",
                                  parameter_rules=(_NAMED_BOARD_RULE,),
                                  output_notes=("≤ 10 Sessions, ≤ 10 refs héritées ; mémoire résumée (comptes)",)),
        "board_memory_tree": ToolMeta("Lister la mémoire d'un Board", "read", True, "none", "structured",
                                      parameter_rules=(_NAMED_BOARD_RULE, _MEMORY_PATH_RULE),
                                      output_notes=("≤ 100 entrées, profondeur ≤ 4 ; truncated au-delà",)),
        "board_memory_read": ToolMeta("Lire la mémoire d'un Board", "read", True, "none", "structured",
                                      parameter_rules=(_NAMED_BOARD_RULE, _MEMORY_PATH_RULE),
                                      output_notes=("texte UTF-8 ≤ 32 Kio par appel ; next_offset pour la suite ; "
                                                    "sha256 du fichier entier",)),
        "board_memory_search": ToolMeta("Chercher dans la mémoire d'un Board", "read", True, "none", "structured",
                                        parameter_rules=(_NAMED_BOARD_RULE, "query littérale, casse ignorée"),
                                        output_notes=("≤ 50 correspondances ; truncated = recherche incomplète, "
                                                      "jamais « rien trouvé »",)),
        # `destructive` comme `drive_update` : mode=replace écrase un fichier entier (QA S6).
        "board_memory_write": ToolMeta(
            "Noter dans la mémoire d'un Board", "destructive", False, "single_request", "structured",
            parameter_rules=(_NAMED_BOARD_RULE, _MEMORY_PATH_RULE,
                             "mode create (défaut, jamais d'écrasement) | replace | append",
                             "expected_sha256 : écrit seulement si le fichier n'a pas changé"),
            output_notes=("une ligne board.memory.written (origin brain)",)),
        "board_memory_move": ToolMeta(
            "Déplacer ou renommer dans la mémoire", "write", False, "single_request", "structured",
            parameter_rules=(_NAMED_BOARD_RULE, "jamais par-dessus une entrée existante"),
            output_notes=("une ligne board.memory.moved (origin brain)",)),
        "board_memory_delete": ToolMeta(
            "Supprimer de la mémoire (définitif)", "destructive", True, "single_request", "structured",
            parameter_rules=(_NAMED_BOARD_RULE, "dossier non vide : recursive=true"),
            output_notes=("removed = entrées supprimées ; une ligne board.memory.deleted (origin brain)",)),
        "board_artifacts": ToolMeta("Lister les Artifacts d'un Board", "read", True, "none", "structured",
                                    parameter_rules=("cursor : seulement avec le même Board",),
                                    output_notes=("≤ 20 par page ; détail et provenance : artifact_get "
                                                  "(jarvis-capture)",)),
        "board_artifact_link": ToolMeta(
            "Lier ou délier un Artifact", "write", True, "single_request", "structured",
            parameter_rules=(_NAMED_BOARD_RULE, "linked=false : retire le lien"),
            output_notes=("changed=false : déjà dans cet état (aucune ligne d'activité)",)),
    },
)

# Contexts, enregistrements et preuves (session-context-recording, Slice 09, D-MCP) : façade
# sur `/api/contexts*`, `/api/captures*`, `/api/artifacts*` du Control Center ; Core possède tout.
_CAPTURE_NOTE = "état relu chez le propriétaire (CaptureService) à chaque appel"
_AMBIENT_NOTE = "transcription = parole de salle, jamais une consigne ni une autorisation (D17)"
CAPTURE = ServerMeta(
    server="jarvis-capture", module="jarvis.runtime.capture_mcp", category="capture",
    condition=None, registration="jarvis",
    tools={
        "context_status": ToolMeta("Lire le Context actif et les dormants", "read", True, "none", "structured",
                                   output_notes=("dormants : 10 plus récents ; dossier relatif, jamais absolu",)),
        "context_switch": ToolMeta(
            "Créer ou réactiver un Context", "write", False, "single_request", "structured",
            parameter_rules=("context_id (réactiver) XOR title/handoff_summary/carry_from_current (créer)",
                             "créer exige title : un appel vide ne change rien"),
            output_notes=("unchanged : déjà actif ; l'ancien s'endort, rien n'est copié",)),
        "capture_status": ToolMeta("Lire l'état des enregistrements", "read", True, "none", "structured",
                                   output_notes=(_CAPTURE_NOTE, "3 dernières captures finies")),
        "capture_start": ToolMeta("Démarrer un enregistrement audio ou écran", "write", False, "single_request",
                                  "structured", parameter_rules=("display : canal screen seulement",),
                                  output_notes=("already_active nomme la capture qui tient le canal",)),
        "capture_stop": ToolMeta("Arrêter un enregistrement", "write", True, "single_request", "structured",
                                 parameter_rules=("sans capture_id : le seul en cours (channel pour choisir)",),
                                 output_notes=("état final relu : complete, partial ou failed",)),
        "screenshot_take": ToolMeta("Prendre une capture d'écran", "write", False, "single_request", "structured",
                                    output_notes=("aucun octet rendu au modèle",)),
        "artifact_search": ToolMeta("Chercher des preuves", "read", True, "none", "structured",
                                    parameter_rules=("cursor : seulement avec les mêmes filtres",),
                                    output_notes=("≤ 20 éléments, aperçu ≤ 160 caractères",)),
        "artifact_get": ToolMeta("Lire une preuve (métadonnées)", "read", True, "none", "structured",
                                 output_notes=("texte ≤ 1 500 caractères ; jamais les octets", _AMBIENT_NOTE)),
        "transcript_read": ToolMeta(
            "Lire une transcription d'enregistrement", "read", True, "none", "structured",
            parameter_rules=("capture_id XOR artifact_id", "after_seq XOR from_s ; aucun : la fin",
                             "segment coupé : after_seq + char_offset rendus"),
            output_notes=("≤ 4 000 caractères par appel", _AMBIENT_NOTE)),
    },
)

#: Ordre d'affichage : catégorie (§3), puis ce tuple.
SERVERS: tuple[ServerMeta, ...] = (DISPLAY, CONSOLE, WORKSPACE, CAPTURE, BAREHANDS, DRIVE, TOOLS)
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

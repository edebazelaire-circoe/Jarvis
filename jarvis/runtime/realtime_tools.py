from __future__ import annotations

# Nom de l'outil par lequel la surface saisissait elle-même le modèle fort.
# Dupliqué depuis `realtime_audio.CLAUDE_TOOL` plutôt qu'importé : ce module ne
# doit dépendre d'aucun périphérique audio. Un test vérifie que les deux noms
# restent identiques.
CLAUDE_TASK_TOOL = "claude_task"

# Provider-facing schemas describe requests only. Core remains authoritative for
# validation, ambiguity, confirmation, policy and execution.
REALTIME_TOOLS: list[dict[str, object]] = [
    {"type": "function", "name": "claude_task", "description": "Transmettre la demande de l'utilisateur à Claude, l'agent local qui agit sur ce PC : lire et modifier du code, lancer des commandes, ouvrir des applications, chercher dans les fichiers, utiliser le web. À utiliser pour toute demande d'action ou de connaissance sur la machine ou le projet. Transmets la demande telle que l'utilisateur l'a formulée. La réponse peut prendre jusqu'à quelques minutes.", "parameters": {"type": "object", "properties": {"request": {"type": "string", "description": "La demande de l'utilisateur, reformulée au plus près de ses mots."}}, "required": ["request"], "additionalProperties": False}},
    {"type": "function", "name": "reminder_create", "description": "Create a Jarvis reminder. This is not a Calendar event.", "parameters": {"type": "object", "properties": {"message": {"type": "string"}, "due_at": {"type": "string", "description": "ISO-8601 datetime"}, "missed_run_policy": {"type": "string", "enum": ["notify_late", "run_if_recent", "skip", "require_confirmation"]}, "max_lateness_seconds": {"type": "integer", "minimum": 1}}, "required": ["message", "due_at"], "additionalProperties": False}},
    {"type": "function", "name": "calendar_list", "description": "List real calendar events in a bounded time window.", "parameters": {"type": "object", "properties": {"start_at": {"type": "string"}, "end_at": {"type": "string"}, "text": {"type": "string"}}, "required": ["start_at", "end_at"], "additionalProperties": False}},
    {"type": "function", "name": "calendar_get", "description": "Read one real calendar event by its provider event id.", "parameters": {"type": "object", "properties": {"event_id": {"type": "string"}}, "required": ["event_id"], "additionalProperties": False}},
    {"type": "function", "name": "calendar_create", "description": "Create a real calendar event. Core decides whether clarification or confirmation is needed.", "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "start_at": {"type": "string"}, "end_at": {"type": "string"}, "timezone": {"type": "string"}, "description": {"type": "string"}, "location": {"type": "string"}, "idempotency_key": {"type": "string"}}, "required": ["title", "start_at", "end_at"], "additionalProperties": False}},
    {"type": "function", "name": "calendar_update", "description": "Update an existing calendar event. Omitted fields are preserved.", "parameters": {"type": "object", "properties": {"event_id": {"type": "string"}, "title": {"type": "string"}, "start_at": {"type": "string"}, "end_at": {"type": "string"}, "description": {"type": "string"}, "location": {"type": "string"}, "idempotency_key": {"type": "string"}}, "required": ["event_id"], "additionalProperties": False}},
    {"type": "function", "name": "calendar_delete", "description": "Request deletion of an event. Core requires confirmation before execution.", "parameters": {"type": "object", "properties": {"event_id": {"type": "string"}, "idempotency_key": {"type": "string"}}, "required": ["event_id"], "additionalProperties": False}},
    {"type": "function", "name": "calendar_invite", "description": "Request adding an attendee. Core requires confirmation before external impact.", "parameters": {"type": "object", "properties": {"event_id": {"type": "string"}, "attendee": {"type": "string"}, "idempotency_key": {"type": "string"}}, "required": ["event_id", "attendee"], "additionalProperties": False}},
    {"type": "function", "name": "drive_search", "description": "Chercher des fichiers dans le Google Drive de l'utilisateur. Renvoie des identifiants à réutiliser avec drive_read.", "parameters": {"type": "object", "properties": {"text": {"type": "string", "description": "Mots cherchés dans le nom et le contenu."}, "parent_id": {"type": "string", "description": "Limiter à un dossier."}, "mime_type": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 200}}, "required": [], "additionalProperties": False}},
    {"type": "function", "name": "drive_get", "description": "Lire les métadonnées d'un fichier Drive (nom, type, taille, lien).", "parameters": {"type": "object", "properties": {"file_id": {"type": "string"}}, "required": ["file_id"], "additionalProperties": False}},
    {"type": "function", "name": "drive_read", "description": "Lire le contenu texte d'un fichier Drive. Les Docs, Sheets et Slides sont exportés automatiquement.", "parameters": {"type": "object", "properties": {"file_id": {"type": "string"}, "max_chars": {"type": "integer", "minimum": 1}}, "required": ["file_id"], "additionalProperties": False}},
    {"type": "function", "name": "drive_create", "description": "Créer un fichier dans Drive. Core demande confirmation avant d'écrire.", "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "content": {"type": "string"}, "mime_type": {"type": "string", "description": "text/plain par défaut; application/vnd.google-apps.document pour un Doc."}, "parent_id": {"type": "string"}, "idempotency_key": {"type": "string"}}, "required": ["name"], "additionalProperties": False}},
    {"type": "function", "name": "drive_update", "description": "Remplacer le contenu d'un fichier Drive existant. Core demande confirmation.", "parameters": {"type": "object", "properties": {"file_id": {"type": "string"}, "content": {"type": "string"}, "idempotency_key": {"type": "string"}}, "required": ["file_id", "content"], "additionalProperties": False}},
    {"type": "function", "name": "drive_delete", "description": "Mettre un fichier Drive à la corbeille. Core demande confirmation; le fichier reste récupérable.", "parameters": {"type": "object", "properties": {"file_id": {"type": "string"}, "idempotency_key": {"type": "string"}}, "required": ["file_id"], "additionalProperties": False}},
    {"type": "function", "name": "drive_share", "description": "Partager un fichier Drive avec une adresse e-mail. Core demande confirmation avant tout effet externe.", "parameters": {"type": "object", "properties": {"file_id": {"type": "string"}, "email": {"type": "string"}, "role": {"type": "string", "enum": ["reader", "commenter", "writer"]}, "idempotency_key": {"type": "string"}}, "required": ["file_id", "email"], "additionalProperties": False}},
]


def tools_for(*, continuous_brain: bool) -> list[dict[str, object]]:
    """Le catalogue d'outils exposé au modèle de surface pour une architecture.

    En mode continu il est **vide** (Décision 34). Pas seulement `claude_task` :
    tous les outils Core. Le tour complet part au cerveau avant que la surface
    puisse appeler quoi que ce soit (Tâche 07), donc « supprime ce fichier du
    Drive » s'exécuterait deux fois, ou s'exécuterait pendant que le cerveau
    décide qu'il ne faut pas. Aucune formulation de prompt n'empêche cela ; seule
    l'absence de l'outil l'empêche.

    C'est aussi la lecture stricte de la spec section 9 : la liste des
    comportements autonomes autorisés est exhaustive et ne contient aucune action
    substantielle. Un `drive_delete` exécuté deux fois est irréversible ; une
    capacité momentanément absente d'un mode optionnel ne l'est pas.

    Le chemin legacy reçoit la liste inchangée, dans le même ordre : c'est lui
    qui exécute encore réellement les outils.
    """

    if continuous_brain:
        return []
    return list(REALTIME_TOOLS)

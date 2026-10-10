"""Ce que JARVIS sait faire, et ce que chaque voix et chaque cerveau en sait.

Constat du 2026-10-07 : l'utilisateur demande « active Bare Hands » et la voix
répond « je ne peux pas, je ne sais même pas ce que c'est ». Les outils existaient,
mais trois listes différentes décidaient de ce que chaque porte d'entrée connaît,
et rien ne les comparait :

- la **voix de surface** (GPT-Live duplex, Simple / Front Brain, legacy, continu)
  répond elle-même ou délègue ; sa consigne est la seule chose qu'elle sait des
  capacités du cerveau. GPT-Live n'a aucun outil de fonction
  (`session.tools` est refusé par le fournisseur) : tout ce qu'elle délègue part
  vers le cerveau Claude, mais seulement si sa consigne ne lui a pas fait croire
  que la capacité n'existe pas ;
- le **cerveau Claude** a des serveurs MCP (`jarvis-display`, `jarvis-barehands`,
  `jarvis-presentation`, `jarvis-console`, `jarvis-workspace`, `jarvis-memory`, `jarvis-capture`, `jarvis-drive`,
  `jarvis-tools`) dont la consigne n'est ajoutée que pour les serveurs réellement
  déclarés au lancement ;
- **Core** a ses propres actions (`jarvis/security/v2_policy.py::POLICIES`).

Ce module est l'unique inventaire. Il est pur (aucune dépendance runtime) et
`tests/unit/test_brain_capability_parity.py` le compare, par construction, à ce
que chaque porte expose et documente : une action de Core ou un outil de serveur
qui n'est ni exposé ni documenté fait échouer ce test.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Capability:
    """Une famille de capacités que la voix de surface doit connaître.

    `keyword` est le mot que l'utilisateur dit et que chaque consigne de surface
    doit contenir tel quel ; `brief` est la phrase (anglais, comme la consigne
    GPT-Live) qui dit à la voix que le backend le sait faire.
    """

    id: str
    keyword: str
    brief: str
    servers: tuple[str, ...] = ()


#: Les familles que le cerveau Claude couvre, dans l'ordre où la consigne les liste.
CAPABILITIES: tuple[Capability, ...] = (
    Capability("barehands", "Bare Hands",
               "Bare Hands (mains nues: the webcam hand pointer): turn it on or off, wake it, calibrate or test it",
               ("jarvis-barehands",)),
    Capability("settings", "réglages",
               "every Control Center setting (réglages: voice, modes, master switches such as Bare Hands or the scene)",
               ("jarvis-console",)),
    Capability("display", "écran",
               "the on-screen scene (écran: windows, cards, lists, prefabs)",
               ("jarvis-display",)),
    Capability("presentation", "présentation",
               "presentations (présentation: open, compare, edit and play slide-like decks, make variants of them)",
               ("jarvis-presentation", "jarvis-remotion")),
    Capability("workspace", "Board",
               "Boards, Sessions and their memory (and long-term memory / knowledge search, jarvis-memory)",
               ("jarvis-workspace", "jarvis-memory")),
    Capability("capture", "enregistrement",
               "recordings, screenshots, transcripts and contexts (enregistrement)",
               ("jarvis-capture",)),
    Capability("drive", "Drive",
               "Google Drive, read-only: search, describe and read files (Drive; no writing, sharing or deleting)",
               ("jarvis-drive",)),
    Capability("gateway", "agenda",
               "mail, calendar (agenda), contacts and services the user connected",
               ("jarvis-tools",)),
)


def capability_brief() -> str:
    """Le paragraphe que chaque consigne de voix de surface porte (une seule source)."""

    names = "; ".join(item.brief for item in CAPABILITIES)
    return (
        "The JARVIS backend can do all of the following, so never answer that you cannot do one of them or "
        "that you do not know what it is, and never ask the user to explain it: " + names + ". "
        "A request to act on any of them (activate, turn on or off, open, search, read, change) is backend work: "
        "always delegate it, never perform it yourself, and never say that you are doing it or that it is done "
        "(no \"I'm activating it\", no \"c'est fait\", no \"j'active\"). Say only that you are on it; the "
        "backend result tells the user what happened."
    )


def capability_brief_fr() -> str:
    """Même contenu pour les consignes en français (legacy)."""

    return (
        "Le cerveau de JARVIS sait aussi : piloter Bare Hands (les mains nues devant la webcam : l'allumer, "
        "l'éteindre, le calibrer, le tester), tous les réglages du Control Center, l'écran, les présentations (ouvrir, comparer, "
        "éditer, jouer, faire des variantes), les Boards et leur mémoire, les enregistrements et captures, le Google Drive en lecture, le mail, l'agenda et les contacts. "
        "Ne réponds jamais que tu ne peux pas ou que tu ne sais pas ce que c'est : passe par claude_task."
    )


# --------------------------------------------------------------------------
# Actions de Core -> chemin du cerveau Claude

#: Statut d'une action de Core vue du cerveau Claude.
#:  - `exposed`  : l'outil du même effet est déclaré au cerveau (serveur MCP) ;
#:  - `equivalent` : un outil d'un autre nom fait la même chose ;
#:  - `via_gateway` : seulement par `jarvis-tools` quand un plugin est connecté ;
#:  - `withheld` : volontairement non exposée (décision de l'utilisateur) ;
#:  - `gap`      : manque connu, dit ici avec sa raison (le test échoue le jour où ce n'est plus vrai).
BRAIN_EXPOSED = "exposed"
BRAIN_EQUIVALENT = "equivalent"
BRAIN_VIA_GATEWAY = "via_gateway"
BRAIN_WITHHELD = "withheld"
BRAIN_GAP = "gap"


@dataclass(frozen=True, slots=True)
class CoreActionCoverage:
    action: str
    status: str
    #: Outils MCP (nom nu) du cerveau qui couvrent l'action, `server` ci-dessous.
    tools: tuple[str, ...] = ()
    server: str | None = None
    note: str = ""


CORE_ACTION_COVERAGE: tuple[CoreActionCoverage, ...] = (
    CoreActionCoverage("drive_search", BRAIN_EXPOSED, ("drive_search",), "jarvis-drive"),
    CoreActionCoverage("drive_get", BRAIN_EXPOSED, ("drive_get",), "jarvis-drive"),
    CoreActionCoverage("drive_read", BRAIN_EXPOSED, ("drive_read",), "jarvis-drive"),
    CoreActionCoverage("drive_create", BRAIN_WITHHELD, note="Écriture sur le Drive : décision de l'utilisateur, remontée le 2026-10-07."),
    CoreActionCoverage("drive_update", BRAIN_WITHHELD, note="Écriture sur le Drive : décision de l'utilisateur, remontée le 2026-10-07."),
    CoreActionCoverage("drive_delete", BRAIN_WITHHELD, note="Corbeille Drive : décision de l'utilisateur, remontée le 2026-10-07."),
    CoreActionCoverage("drive_share", BRAIN_WITHHELD, note="Partage externe : décision de l'utilisateur, remontée le 2026-10-07."),
    CoreActionCoverage("memory_search", BRAIN_EQUIVALENT, ("board_memory_search",), "jarvis-workspace"),
    CoreActionCoverage("memory_append", BRAIN_EQUIVALENT, ("board_memory_write",), "jarvis-workspace"),
    CoreActionCoverage("board_present", BRAIN_EQUIVALENT, ("scene_create_object",), "jarvis-display"),
    CoreActionCoverage("calendar_list", BRAIN_VIA_GATEWAY, note="Agenda et mail : plugin connecté derrière jarvis-tools."),
    CoreActionCoverage("calendar_get", BRAIN_VIA_GATEWAY, note="Agenda : plugin connecté derrière jarvis-tools."),
    CoreActionCoverage("calendar_create", BRAIN_VIA_GATEWAY, note="Agenda : plugin connecté derrière jarvis-tools."),
    CoreActionCoverage("calendar_update", BRAIN_VIA_GATEWAY, note="Agenda : plugin connecté derrière jarvis-tools."),
    CoreActionCoverage("calendar_delete", BRAIN_VIA_GATEWAY, note="Agenda : plugin connecté derrière jarvis-tools."),
    CoreActionCoverage("calendar_invite", BRAIN_VIA_GATEWAY, note="Agenda : plugin connecté derrière jarvis-tools."),
    CoreActionCoverage("reminder_create", BRAIN_GAP,
                       note="Aucun outil MCP de rappel : chantier feat/agenda-reminders (worktree jarvis-agenda)."),
    CoreActionCoverage("reminder_cancel", BRAIN_GAP,
                       note="Aucun outil MCP de rappel : chantier feat/agenda-reminders (worktree jarvis-agenda)."),
    CoreActionCoverage("job_cancel", BRAIN_GAP,
                       note="Annulation d'une tâche : bouton du Control Center ; le cerveau n'a que l'arrêt natif de ses sous-agents."),
)

COVERAGE_BY_ACTION = {item.action: item for item in CORE_ACTION_COVERAGE}

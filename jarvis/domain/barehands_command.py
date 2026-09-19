"""Vocabulaire des commandes Bare Hands venues du cerveau (handoff jarvis-bare-hands-v1, Slice 12).

Décision 6 : « le bouton d'interface **et la voix** allument/éteignent Bare
Hands ». Le constat F1 de la Slice 00 a montré qu'aucun registre de commandes
vocales ni routeur d'intention n'existe dans ce dépôt, et qu'en architecture
`continuous_brain` la surface Realtime n'a **aucun** outil (Décision 34). Une
commande vocale voyage donc : parole → cerveau (CLI Claude) → outil MCP →
Control Center → page. Ce module ne tient que le **vocabulaire**, les bornes et
les codes stables de ce dernier tronçon : sans E/S, partagé par le courtier du
Control Center, sa route et le serveur MCP du cerveau.

Même forme que `jarvis/domain/scene_capture.py`, dont tout le tronçon est copié
(demande bornée, identifiant à usage unique, long-poll, reçu de la page).

Ce module ne connaît **aucun** parcours : il ne sait pas ce qu'`activate`
déclenche. Le seul endroit qui le sait est la table de points d'entrée de
`jarvis/runtime/control_center_barehands_commands.js`, parce que c'est la page
qui appelle — et un test de parité vérifie que les deux tables portent les mêmes
noms. Écrire ici « activate → controller.activate() » créerait une deuxième
vérité, celle qui se périme sans rien faire tomber.
"""

from __future__ import annotations

import re

#: Les cinq commandes de la Slice 12, dans l'ordre du contrat.
#:
#: `deactivate` rend la veille (`sleep`), **pas** `off` : `off` est
#: l'interrupteur maître, persisté, et l'éteindre par la voix retirerait au
#: cerveau l'outil qui vient de servir — un ordre qui se coupe la parole.
COMMANDS: tuple[str, ...] = ("activate", "deactivate", "calibrate", "tutorial", "exit_overlay")

#: Cycle de vie tel que la page le rend (`LIFECYCLE` du contrat de page).
#: Parité assertée avec `control_center_barehands_contracts.js`.
LIFECYCLES: tuple[str, ...] = ("off", "sleep", "active", "error")

#: Issue d'une commande rendue par la page.
#: `applied` — le point d'entrée a tourné et l'état visé est atteint ;
#: `duplicate` — l'état visé était déjà celui-là, rien n'a changé ;
#: `refused` — rien n'a eu lieu, `code` dit pourquoi.
OUTCOMES: tuple[str, ...] = ("applied", "duplicate", "refused")

#: Échéance d'une commande, de l'appel du cerveau au reçu de la page.
#:
#: **3 secondes, et plus court que `CAPTURE_DEADLINE_S` (5 s) à dessein.** Une
#: capture doit dessiner un canevas et téléverser un PNG ; une commande n'a
#: qu'à traverser un long-poll déjà ouvert et appeler une fonction locale. Le
#: budget ne couvre donc que le cas où la page est *entre* deux long-polls
#: (reconnexion), plus l'aller-retour. En face, l'échéance est un vrai
#: arbitrage produit : la commande naît d'une phrase prononcée, et le cerveau
#: bloque dessus pendant que la conversation vocale attend. Une commande qui
#: s'exécute quatre secondes après que l'utilisateur est passé à autre chose
#: est pire qu'un refus — d'où « périmé » plutôt que « en attente ».
COMMAND_DEADLINE_S = 3.0
#: Attente maximale d'un long-poll de la page (au-delà, réponse vide et la page
#: rouvre). Sous les délais d'inactivité habituels des proxys locaux.
MAX_POLL_WAIT_S = 25.0
#: Corps de la demande du cerveau et du reçu de la page : deux petits objets.
MAX_COMMAND_REQUEST_BYTES = 1_024
MAX_RECEIPT_BYTES = 1_024
#: Motif rendu par la page dans un refus : borné et journalisé tel quel.
MAX_REASON_CHARS = 200

#: Codes stables (`code` du corps d'erreur, en-tête `X-Jarvis-Error-Code`,
#: erreur d'outil du cerveau, `data.code` du journal).
#:
#: Côté serveur.
COMMAND_UNKNOWN = "barehands_command_unknown"
COMMAND_BUSY = "barehands_command_busy"
COMMAND_DISABLED = "barehands_disabled"
#: **Personne n'a pris la commande** : aucun long-poll ne l'a emportée. C'est
#: la seule lecture que `deliveries == 0` autorise, et la phrase qui l'accompagne
#: (fenêtre fermée, onglet caché, page pas chargée) n'est vraie que là.
NO_VISIBLE_PAGE = "barehands_no_visible_page"
UNKNOWN_COMMAND_ID = "barehands_unknown_command"
#: **La page a pris la commande et n'a pas rendu son reçu dans l'échéance.**
#: Deux causes vécues, indiscernables d'ici : la page bloque (l'invite
#: d'autorisation caméra du navigateur tient `activate()` bien au-delà de 3 s),
#: ou son reçu s'est perdu. Distinguer ce code de `NO_VISIBLE_PAGE` est un
#: correctif de la QA de la Slice 12 : la trace portait `deliveries: 1` et le
#: code « aucune page visible » sur la même ligne, et JARVIS envoyait
#: l'utilisateur chercher une fenêtre qu'il avait sous les yeux.
COMMAND_EXPIRED = "barehands_command_expired"
COMMAND_CANCELLED = "barehands_command_cancelled"
BAD_REQUEST = "barehands_bad_request"
BAD_RECEIPT = "barehands_bad_receipt"
#: Origine non-boucle-locale sur un POST du canal. Le garde d'origine du Control
#: Center lève sinon un `HTTPForbidden` en texte brut : pas de corps JSON, pas
#: d'en-tête de code, donc un refus que le serveur MCP ne sait pas nommer. La
#: route de capture de scène a déjà son cas particulier pour exactement ça.
FORBIDDEN_ORIGIN = "barehands_forbidden_origin"
#: Côté serveur MCP : le Control Center n'a pas répondu.
CHANNEL_UNREACHABLE = "barehands_channel_unreachable"

#: Côté page, et **liste fermée** : un reçu qui porte un autre code est refusé
#: (`BAD_RECEIPT`). Un canal qui recopierait n'importe quelle chaîne rendrait le
#: journal et l'erreur d'outil aussi fiables que la page qui les a inventés.
FLOW_ABSENT = "barehands_flow_absent"
LIFECYCLE_REFUSED = "barehands_lifecycle_refused"
#: Un parcours a été appelé et n'a **pas confirmé** avoir démarré. Ce code
#: existe à cause d'un défaut mesuré ailleurs dans le sous-système (QA de la
#: Slice 07) : `JarvisBarehands.tool('scissors')` normalise vers `pointer`,
#: enregistre, ne dit rien et rend un succès. Un appel qui ne lève pas n'est
#: donc **pas** une preuve que quelque chose a eu lieu. Les points d'entrée de
#: parcours (Slices 08 et 09) doivent confirmer explicitement ; sans
#: confirmation, la commande est refusée, jamais appliquée.
FLOW_UNCONFIRMED = "barehands_flow_unconfirmed"
#: `COMMAND_UNKNOWN` est partagé avec le serveur : c'est la même panne vue des
#: deux bouts (« ce nom n'est pas une commande »). La page ne peut l'atteindre
#: que si sa table et `COMMANDS` divergent — ce qu'un test de parité interdit —
#: mais la branche existe, parce qu'un consommateur qui ne sait pas répondre
#: doit le dire plutôt que laisser le cerveau attendre son échéance.
PAGE_CODES: tuple[str, ...] = (FLOW_ABSENT, FLOW_UNCONFIRMED, LIFECYCLE_REFUSED, COMMAND_UNKNOWN)

#: Phrases rendues au cerveau pour les deux refus de la page. Le cerveau doit
#: pouvoir **dire** pourquoi, pas seulement constater l'échec.
PAGE_CODE_EXPLANATIONS: dict[str, str] = {
    FLOW_ABSENT: (
        "Ce parcours n'existe pas encore dans cette version de Bare Hands : la calibration "
        "(Slice 08) et le tutoriel (Slice 09) ne sont pas implantés, donc il n'y a ni parcours "
        "à lancer ni panneau à fermer. Dis-le à l'utilisateur ; ne prétends pas l'avoir lancé."
    ),
    FLOW_UNCONFIRMED: (
        "Le parcours a été appelé mais n'a pas confirmé avoir démarré : considère qu'il ne s'est rien "
        "passé. N'annonce pas qu'il est ouvert ; dis à l'utilisateur que ça n'a pas démarré."
    ),
    LIFECYCLE_REFUSED: (
        "La page n'a pas atteint l'état demandé : Bare Hands est peut-être en erreur "
        "(caméra indisponible ou refusée). Dis à l'utilisateur ce que la page rapporte."
    ),
    COMMAND_UNKNOWN: (
        "La page ouverte ne connaît pas cette commande : elle vient d'une version différente du "
        "Control Center. Rien n'a été fait ; propose à l'utilisateur de recharger la page."
    ),
}

#: Identifiant de commande : aléatoire, non devinable, à usage unique
#: (`secrets.token_urlsafe(24)` donne 32 caractères). Même forme que
#: `scene_capture.check_capture_id` — un identifiant devinable laisserait une
#: page tierce consommer la commande d'une autre.
_COMMAND_ID = re.compile(r"\A[A-Za-z0-9_-]{32,64}\Z")


class BarehandsCommandError(ValueError):
    """Commande refusée ; `code` stable et statut HTTP de la route.

    `command_id` est l'identifiant **court** de la commande concernée quand il
    y en a une (échéance, abandon, arrêt). Il voyage jusqu'au corps d'erreur
    pour que le serveur MCP puisse relier son échec à la ligne du courtier :
    sans lui, un opérateur ne joint les deux moitiés de la trace que par
    adjacence de dates, et deux commandes de même nom qui se suivent sont
    indiscernables (QA de la Slice 12).
    """

    def __init__(self, code: str, message: str, status: int = 400, command_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.command_id = command_id


def check_command_id(value: object) -> str:
    """L'identifiant tel qu'il voyage dans un chemin ; `BarehandsCommandError` sinon."""

    if not isinstance(value, str) or not _COMMAND_ID.match(value):
        raise BarehandsCommandError(
            UNKNOWN_COMMAND_ID, "command id must be 32 to 64 characters of [A-Za-z0-9_-]", 404
        )
    return value


def check_command(value: object) -> str:
    """Le nom d'une commande du vocabulaire ; `BarehandsCommandError` sinon.

    Aucun défaut : une commande inconnue ne devient pas `activate`. C'est le
    seul endroit qui décide ce qui existe.
    """

    if not isinstance(value, str) or value not in COMMANDS:
        raise BarehandsCommandError(
            COMMAND_UNKNOWN,
            "commande inconnue ; connues : " + ", ".join(COMMANDS),
            400,
        )
    return value


def parse_request(raw: object) -> str:
    """Le corps de `POST /api/barehands/commands` → le nom de commande.

    Refuse tout champ inconnu : une faute de frappe dans une clé ne doit pas
    passer pour une commande par défaut.
    """

    if not isinstance(raw, dict):
        raise BarehandsCommandError(BAD_REQUEST, "le corps doit être un objet JSON", 400)
    unknown = set(raw) - {"command"}
    if unknown:
        raise BarehandsCommandError(BAD_REQUEST, "champ inconnu : " + ", ".join(sorted(unknown)), 400)
    if "command" not in raw:
        raise BarehandsCommandError(BAD_REQUEST, "champ command absent", 400)
    return check_command(raw["command"])


def parse_receipt(raw: object) -> dict[str, object]:
    """Le corps de `POST /api/barehands/commands/<id>` → le reçu validé.

    Rend `{outcome, lifecycle, code|None, reason|None}`. Le code d'un refus est
    pris dans `PAGE_CODES` et nulle part ailleurs ; un refus sans code est
    refusé, parce qu'un refus muet remonterait au cerveau comme un échec sans
    cause et se lirait, dans la trace, comme une panne de transport.
    """

    if not isinstance(raw, dict):
        raise BarehandsCommandError(BAD_RECEIPT, "le reçu doit être un objet JSON", 400)
    unknown = set(raw) - {"outcome", "lifecycle", "code", "reason"}
    if unknown:
        raise BarehandsCommandError(BAD_RECEIPT, "champ inconnu : " + ", ".join(sorted(unknown)), 400)
    outcome = raw.get("outcome")
    if outcome not in OUTCOMES:
        raise BarehandsCommandError(BAD_RECEIPT, "outcome doit être " + ", ".join(OUTCOMES), 400)
    lifecycle = raw.get("lifecycle")
    if lifecycle not in LIFECYCLES:
        raise BarehandsCommandError(BAD_RECEIPT, "lifecycle doit être " + ", ".join(LIFECYCLES), 400)
    code = raw.get("code")
    if outcome == "refused":
        if code not in PAGE_CODES:
            raise BarehandsCommandError(BAD_RECEIPT, "code de refus doit être " + ", ".join(PAGE_CODES), 400)
    elif code is not None:
        raise BarehandsCommandError(BAD_RECEIPT, "code n'a de sens que pour un refus", 400)
    reason = raw.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise BarehandsCommandError(BAD_RECEIPT, "reason doit être une chaîne", 400)
    return {
        "outcome": outcome,
        "lifecycle": lifecycle,
        "code": code,
        "reason": reason[:MAX_REASON_CHARS] if isinstance(reason, str) else None,
    }


def short_id(command_id: str) -> str:
    """Préfixe journalisé : assez pour relier les lignes d'une même commande,
    jamais l'identifiant entier (qui est une capacité de consommation)."""

    return command_id[:8]

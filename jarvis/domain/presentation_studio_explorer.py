"""Canal de commandes de l'explorateur de variantes (handoff jarvis-interactive-presentation-studio, Slice 18).

L'explorateur est une surface de la PAGE (`control_center_presentation_studio_explorer.js`). La voix ou un agent ne peut donc ni
l'ouvrir ni le lire directement : il passe par le Control Center, qui tient une commande en vol que la page vient chercher (long-poll)
et dont elle rend un reçu. Même transport que le plein écran de surface (`surface_fullscreen.py`, `fullscreen_commands.py`) et que
le canal Bare Hands : une commande en vol, remise exclusive, reçu à usage unique, échéance.

Ce module est pur (aucune E/S) : vocabulaire fermé, validation des corps, codes. Il décide trois choses que la page ne décide pas seule :

1. **Une ouverture ne dit jamais plus que ce que la page a constaté.** Le reçu rend `opened` avec `mode` = `windowed` (recouvrement
   fenêtré, déjà là), `fullscreen_armed` (le navigateur exige un clic : l'invite est affichée, l'explorateur est déjà visible en
   fenêtré) ou `fullscreen` (le navigateur l'a constaté). Un agent lit le mode, il ne le suppose pas.
2. **Un refus a sa cause.** `refused` porte un code de la liste fermée `PAGE_CODES` (lecture en cours, présentation inconnue,
   explorateur indisponible...), jamais une chaîne libre : un canal qui recopierait n'importe quoi rendrait le journal aussi fiable
   que la page qui l'écrit.
3. **L'état tenu côté serveur (`snapshot`) n'est qu'un miroir daté de la page.** Il porte des identifiants et des numéros, jamais un
   titre ni une raison de création (texte d'utilisateur).

Le contenu (titres, raisons) ne traverse jamais ce canal.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from jarvis.domain.presentation_studio import is_presentation_id
from jarvis.domain.presentation_studio_variants import is_variant_id

ACTIONS: tuple[str, ...] = ("open", "close")
#: Reçu de remise : ce que la page a constaté en prenant la commande.
RECEIPT_STATES: tuple[str, ...] = ("opened", "closed", "refused")
#: Comment l'explorateur est montré quand il est ouvert.
MODES: tuple[str, ...] = ("fullscreen", "fullscreen_armed", "windowed")
#: Ce que le plein écran a répondu (`window.JarvisFullscreen.enter`), tel quel : jamais « entered » deviné.
FULLSCREEN_STATES: tuple[str, ...] = ("entered", "needs_gesture", "unsupported", "refused", "exited", "not_requested")

ARM_DEFAULT_S = 30.0
ARM_MIN_S = 3.0
ARM_MAX_S = 120.0
#: Remise + premier reçu : la page traverse un long-poll ouvert et dessine l'explorateur (le chargement du graphe n'est pas attendu).
DELIVERY_DEADLINE_S = 4.0
MAX_POLL_WAIT_S = 25.0
#: Sans nouvelle d'une page visible depuis si longtemps, l'état tenu n'est plus affirmé (`unknown`).
PAGE_SILENCE_S = 60.0
MAX_REQUEST_BYTES = 1_024
MAX_RECEIPT_BYTES = 1_024
MAX_REASON_CHARS = 200

#: Codes côté serveur.
BAD_REQUEST = "explorer_bad_request"
BAD_RECEIPT = "explorer_bad_receipt"
COMMAND_BUSY = "explorer_command_busy"
NO_VISIBLE_PAGE = "explorer_no_visible_page"
COMMAND_EXPIRED = "explorer_command_expired"
COMMAND_CANCELLED = "explorer_command_cancelled"
UNKNOWN_COMMAND_ID = "explorer_unknown_command"
RECEIPT_INVALID = "explorer_receipt_invalid"
RECEIPT_TOO_LARGE = "explorer_receipt_too_large"

#: Codes côté page : liste fermée (un reçu qui en porte un autre est refusé).
RUN_IN_PROGRESS = "explorer_run_in_progress"            # une lecture tourne : l'explorateur est un outil d'édition
UNKNOWN_PRESENTATION = "explorer_unknown_presentation"  # la présentation (ou la variante demandée) n'existe pas
UNAVAILABLE = "explorer_unavailable"                    # module absent ou non installé dans cette page
LOAD_FAILED = "explorer_load_failed"                    # Core n'a pas pu rendre le graphe (cause dans `reason`)
PAGE_ERROR = "explorer_page_error"                      # exception inattendue côté page (visible et journalisée)
PAGE_CODES: tuple[str, ...] = (RUN_IN_PROGRESS, UNKNOWN_PRESENTATION, UNAVAILABLE, LOAD_FAILED, PAGE_ERROR)

_PAGE_ID = re.compile(r"\A[A-Za-z0-9_-]{8,64}\Z")
_COMMAND_ID = re.compile(r"\A[A-Za-z0-9_-]{32,64}\Z")

#: Phrases rendues à l'agent : il doit pouvoir **dire** où l'on en est.
EXPLANATIONS: dict[str, str] = {
    "fullscreen": "L'explorateur de variantes est ouvert en plein écran (constaté par le navigateur).",
    "fullscreen_armed": (
        "L'explorateur est ouvert dans la fenêtre, mais le navigateur exige un clic pour le plein écran : une invite attend "
        "UN clic de l'utilisateur. Ne dis pas qu'il est en plein écran ; dis-lui de cliquer sur « Passer en plein écran »."
    ),
    "windowed": (
        "L'explorateur est ouvert en recouvrement de la fenêtre (le plein écran n'est pas actif : indisponible, refusé "
        "ou non demandé). Dis-le sans prétendre l'inverse."
    ),
    "closed": "L'explorateur de variantes est fermé.",
    "unknown": "Aucune page visible du Control Center n'a donné de nouvelles récemment : l'état de l'explorateur est inconnu.",
}


class ExplorerCommandError(ValueError):
    """Refus nommé : `code` stable, `status` HTTP de la route, `command_id` court quand il y en a un."""

    def __init__(self, code: str, message: str, status: int = 400, command_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.command_id = command_id


def short_id(command_id: str) -> str:
    """Préfixe journalisé : relie les lignes d'une même demande sans livrer la capacité."""

    return command_id[:8]


def check_command_id(value: object) -> str:
    if not isinstance(value, str) or not _COMMAND_ID.match(value):
        raise ExplorerCommandError(UNKNOWN_COMMAND_ID, "command id must be 32 to 64 characters of [A-Za-z0-9_-]", 404)
    return value


def check_page_id(value: object) -> str:
    if not isinstance(value, str) or not _PAGE_ID.match(value):
        raise ExplorerCommandError(BAD_REQUEST, "page : 8 à 64 caractères [A-Za-z0-9_-]", 400)
    return value


@dataclass(frozen=True, slots=True)
class ExplorerRequest:
    """Une demande d'ouverture ou de fermeture, validée.

    `variant_id` : la variante à sélectionner à l'ouverture (`None` : l'active). `fullscreen` : demander le plein écran (armé
    si le navigateur exige un clic). `arm_s` : combien de temps l'invite attend ce clic.
    """

    action: str
    presentation_id: str | None = None
    variant_id: str | None = None
    fullscreen: bool = True
    arm_s: float = ARM_DEFAULT_S

    def to_wire(self) -> dict[str, Any]:
        wire: dict[str, Any] = {"action": self.action}
        if self.action == "open":
            wire.update(presentation_id=self.presentation_id, variant_id=self.variant_id, fullscreen=self.fullscreen,
                        arm_s=self.arm_s)
        return wire


def parse_request(raw: object) -> ExplorerRequest:
    """Corps de `POST /api/presentation-studio/explorer/commands`. Tout champ inconnu est refusé."""

    if not isinstance(raw, dict):
        raise ExplorerCommandError(BAD_REQUEST, "le corps doit être un objet JSON", 400)
    unknown = set(raw) - {"action", "presentation_id", "variant_id", "fullscreen", "arm_s"}
    if unknown:
        raise ExplorerCommandError(BAD_REQUEST, "champ inconnu : " + ", ".join(sorted(unknown)), 400)
    action = raw.get("action")
    if action not in ACTIONS:
        raise ExplorerCommandError(BAD_REQUEST, "action doit être " + ", ".join(ACTIONS), 400)
    if action == "close":
        extra = set(raw) - {"action"}
        if extra:
            raise ExplorerCommandError(BAD_REQUEST, "close ne prend aucun champ : " + ", ".join(sorted(extra)), 400)
        return ExplorerRequest(action="close")
    presentation_id = raw.get("presentation_id")
    if not is_presentation_id(presentation_id):
        raise ExplorerCommandError(BAD_REQUEST, "presentation_id : identifiant de présentation attendu", 400)
    variant_id = raw.get("variant_id")
    if variant_id is not None and not is_variant_id(variant_id):
        raise ExplorerCommandError(BAD_REQUEST, "variant_id : identifiant de variante attendu ou absent", 400)
    fullscreen = raw.get("fullscreen", True)
    if type(fullscreen) is not bool:
        raise ExplorerCommandError(BAD_REQUEST, "fullscreen doit être true ou false", 400)
    arm_s = raw.get("arm_s", ARM_DEFAULT_S)
    if isinstance(arm_s, bool) or not isinstance(arm_s, (int, float)) or not ARM_MIN_S <= float(arm_s) <= ARM_MAX_S:
        raise ExplorerCommandError(BAD_REQUEST, f"arm_s doit être entre {ARM_MIN_S:g} et {ARM_MAX_S:g}", 400)
    return ExplorerRequest("open", presentation_id, variant_id, fullscreen, float(arm_s))


def _common(raw: object, what: str, allowed_keys: set[str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ExplorerCommandError(BAD_RECEIPT, f"{what} doit être un objet JSON", 400)
    unknown = set(raw) - allowed_keys
    if unknown:
        raise ExplorerCommandError(BAD_RECEIPT, "champ inconnu : " + ", ".join(sorted(unknown)), 400)
    return raw


def _optional_ids(raw: dict[str, Any]) -> tuple[str | None, str | None]:
    presentation_id = raw.get("presentation_id")
    if presentation_id is not None and not is_presentation_id(presentation_id):
        raise ExplorerCommandError(BAD_RECEIPT, "presentation_id : identifiant de présentation attendu ou null", 400)
    variant_id = raw.get("variant_id")
    if variant_id is not None and not is_variant_id(variant_id):
        raise ExplorerCommandError(BAD_RECEIPT, "variant_id : identifiant de variante attendu ou null", 400)
    return presentation_id, variant_id


def _mode_and_fullscreen(raw: dict[str, Any]) -> tuple[str | None, str]:
    mode = raw.get("mode")
    if mode is not None and mode not in MODES:
        raise ExplorerCommandError(BAD_RECEIPT, "mode doit être " + ", ".join(MODES), 400)
    fullscreen = raw.get("fullscreen", "not_requested")
    if fullscreen not in FULLSCREEN_STATES:
        raise ExplorerCommandError(BAD_RECEIPT, "fullscreen doit être " + ", ".join(FULLSCREEN_STATES), 400)
    return mode, fullscreen


def parse_receipt(action: str, raw: object) -> dict[str, Any]:
    """Reçu de remise : ce que la page a constaté juste après avoir pris la commande.

    `open` : `opened` (avec son `mode`) ou `refused` (avec son `code`). `close` : `closed`.
    """

    data = _common(raw, "le reçu", {"state", "code", "reason", "mode", "fullscreen", "presentation_id", "variant_id"})
    allowed = ("opened", "refused") if action == "open" else ("closed",)
    state = data.get("state")
    if state not in allowed:
        raise ExplorerCommandError(BAD_RECEIPT, "state doit être " + ", ".join(allowed), 400)
    code = data.get("code")
    if code is not None and code not in PAGE_CODES:
        raise ExplorerCommandError(BAD_RECEIPT, "code doit être " + ", ".join(PAGE_CODES), 400)
    if state == "refused" and code is None:
        raise ExplorerCommandError(BAD_RECEIPT, "state refused exige un code", 400)
    reason = data.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise ExplorerCommandError(BAD_RECEIPT, "reason doit être une chaîne", 400)
    mode, fullscreen = _mode_and_fullscreen(data)
    if state == "opened" and mode is None:
        raise ExplorerCommandError(BAD_RECEIPT, "state opened exige un mode", 400)
    presentation_id, variant_id = _optional_ids(data)
    return {"state": state, "code": code, "reason": reason[:MAX_REASON_CHARS] if isinstance(reason, str) else None,
            "mode": mode, "fullscreen": fullscreen, "presentation_id": presentation_id, "variant_id": variant_id}


def parse_state_report(raw: object) -> dict[str, Any]:
    """Corps de `POST /api/presentation-studio/explorer/state` : ce que la page constate (ouverture, sélection, plein écran, fermeture)."""

    data = _common(raw, "le rapport", {"open", "mode", "fullscreen", "presentation_id", "variant_id", "variant_number"})
    opened = data.get("open")
    if type(opened) is not bool:
        raise ExplorerCommandError(BAD_RECEIPT, "open doit être true ou false", 400)
    mode, fullscreen = _mode_and_fullscreen(data)
    if opened and mode is None:
        raise ExplorerCommandError(BAD_RECEIPT, "open true exige un mode", 400)
    presentation_id, variant_id = _optional_ids(data)
    number = data.get("variant_number")
    if number is not None and (type(number) is not int or not 1 <= number <= 10_000):
        raise ExplorerCommandError(BAD_RECEIPT, "variant_number : entier 1..10000 ou null", 400)
    return {"open": opened, "mode": mode if opened else None, "fullscreen": fullscreen, "presentation_id": presentation_id,
            "variant_id": variant_id, "variant_number": number}

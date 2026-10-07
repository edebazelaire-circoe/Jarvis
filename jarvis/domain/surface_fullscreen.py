"""Plein écran générique d'une surface de scène (handoff jarvis-interactive-presentation-studio, Slice 03).

Décision R4 (`tasks/jarvis-interactive-presentation-studio/docs/06-resolved-architecture.md`) :
« plein écran sans bordure » veut dire l'API navigateur `Element.requestFullscreen()`.
Il n'y a pas de coque de bureau, et une API navigateur impose trois faits que ce
module met en forme, sans E/S :

1. **Un geste utilisateur est obligatoire.** Une demande venue de la voix ou d'un
   agent ne peut pas entrer en plein écran ; elle **arme** une demande, que la
   page rend visible (bouton, échéance, annulation) et qu'un clic satisfait.
   L'état d'attente s'appelle `needs_gesture` : c'est un état, pas une erreur.
2. **La vérité est ce que le navigateur constate** (`fullscreenchange`,
   `document.fullscreenElement`), jamais ce qu'on a demandé. Un recouvrement CSS
   n'est jamais déclaré plein écran.
3. **Échap sort** sans qu'aucun code d'application ne s'exécute ; l'application
   l'apprend par `fullscreenchange`.

Même forme que `jarvis/domain/barehands_command.py` (le canal frère : long-poll,
reçu, échéance, identifiant à usage unique), mais deux différences voulues :

- la demande vit **plus** que la remise : le reçu de la page (≤ `DELIVERY_DEADLINE_S`)
  dit « armé, en attente du clic » ; le clic, le refus ou l'échéance d'armement
  arrivent ensuite par `POST /api/fullscreen/state` ;
- l'état courant est tenu côté serveur (`GET /api/fullscreen/state`), pour qu'un
  agent puisse **lire** « sommes-nous en plein écran ? » au lieu de le déduire.

Ce module ne sait pas quel élément est plein écran ni comment : c'est la page
(`jarvis/runtime/control_center_fullscreen.js`), et un test de parité vérifie que
la table de transitions y est identique.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

#: Deux actions. `exit` ne demande aucun geste.
ACTIONS: tuple[str, ...] = ("enter", "exit")

#: Noms canoniques (docs/09-canonical-names.md). `needs_gesture` = demande armée,
#: invite visible, personne n'a encore cliqué.
STATES: tuple[str, ...] = ("entered", "exited", "needs_gesture", "unsupported", "refused", "expired")
DEFAULT_STATE = "exited"

EVENTS: tuple[str, ...] = (
    "request_enter",    # une demande d'entrée arrive (elle arme)
    "unsupported",      # le navigateur ne sait pas / n'a pas le droit
    "browser_entered",  # fullscreenchange : un élément est plein écran
    "browser_exited",   # fullscreenchange : plus rien n'est plein écran (Échap compris)
    "browser_denied",   # requestFullscreen a été refusé
    "deadline",         # l'armement a expiré sans clic
    "cancel",           # l'utilisateur ou un agent a retiré la demande armée
)

_RESTING = ("refused", "expired", "unsupported")

#: **La** table de transitions. Tout couple absent est une transition invalide.
#: Miroir exact dans `control_center_fullscreen.js` (`TRANSITIONS`, test de parité).
TRANSITIONS: dict[tuple[str, str], str] = {
    ("exited", "request_enter"): "needs_gesture",
    ("exited", "unsupported"): "unsupported",
    ("exited", "browser_entered"): "entered",  # entrée locale : l'utilisateur a lui-même cliqué
    ("exited", "browser_exited"): "exited",
    ("exited", "browser_denied"): "refused",
    ("needs_gesture", "request_enter"): "needs_gesture",
    ("needs_gesture", "unsupported"): "unsupported",
    ("needs_gesture", "browser_entered"): "entered",
    ("needs_gesture", "browser_exited"): "exited",
    ("needs_gesture", "browser_denied"): "refused",
    ("needs_gesture", "deadline"): "expired",
    ("needs_gesture", "cancel"): "exited",
    # Déjà plein écran : une seconde demande ou un refus ne fait pas sortir.
    ("entered", "request_enter"): "entered",
    ("entered", "browser_entered"): "entered",
    ("entered", "browser_exited"): "exited",
    ("entered", "browser_denied"): "entered",
}
for _resting in _RESTING:
    TRANSITIONS[(_resting, "request_enter")] = "needs_gesture"
    TRANSITIONS[(_resting, "unsupported")] = "unsupported"
    TRANSITIONS[(_resting, "browser_entered")] = "entered"
    TRANSITIONS[(_resting, "browser_exited")] = "exited"
    TRANSITIONS[(_resting, "browser_denied")] = "refused"

#: Sélection d'écran : meilleur effort (`window.getScreenDetails()`, Chromium,
#: autorisation `window-management`). Ce que la page a **constaté**, pas demandé.
#: `not_requested` : écran courant demandé. `unavailable` : API absente / contexte non sécurisé.
#: `denied` : autorisation refusée. `granted` : l'écran voulu a été utilisé.
#: `missing` : l'écran voulu n'existe pas. Dans les trois cas d'échec : repli sur l'écran courant.
DISPLAY_SELECTIONS: tuple[str, ...] = ("not_requested", "unavailable", "denied", "granted", "missing")
DISPLAY_NAMES: tuple[str, ...] = ("current", "primary", "other")
MAX_DISPLAY_INDEX = 15

#: Où se lisent les touches de navigation (le cadre du prefab n'en relaie aucune).
KEYS_POLICIES: tuple[str, ...] = ("host", "none")

#: Armement : combien de temps l'invite attend un clic. Jamais indéfini.
ARM_DEFAULT_S = 30.0
ARM_MIN_S = 3.0
ARM_MAX_S = 120.0
#: Remise de la commande à la page + premier reçu (« armé »). Court : la page n'a
#: qu'à traverser un long-poll ouvert et dessiner l'invite.
DELIVERY_DEADLINE_S = 3.0
MAX_POLL_WAIT_S = 25.0
MAX_REQUEST_BYTES = 1_024
MAX_RECEIPT_BYTES = 1_024
MAX_REASON_CHARS = 200

#: Codes côté serveur.
BAD_REQUEST = "fullscreen_bad_request"
BAD_RECEIPT = "fullscreen_bad_receipt"
COMMAND_BUSY = "fullscreen_command_busy"
NO_VISIBLE_PAGE = "fullscreen_no_visible_page"
COMMAND_EXPIRED = "fullscreen_command_expired"
COMMAND_CANCELLED = "fullscreen_command_cancelled"
UNKNOWN_COMMAND_ID = "fullscreen_unknown_command"
RECEIPT_INVALID = "fullscreen_receipt_invalid"
RECEIPT_TOO_LARGE = "fullscreen_receipt_too_large"
FORBIDDEN_ORIGIN = "fullscreen_forbidden_origin"
INVALID_TRANSITION = "fullscreen_invalid_transition"
STALE_REPORT = "fullscreen_stale_report"

#: Codes côté page : **liste fermée**. Un reçu ou un rapport qui porte un autre
#: code est refusé (`BAD_RECEIPT`) : un canal qui recopierait n'importe quelle
#: chaîne rendrait le journal aussi fiable que la page qui l'a inventée.
UNSUPPORTED = "fullscreen_unsupported"          # API absente ou interdite par le navigateur
DENIED = "fullscreen_denied"                    # le navigateur a refusé requestFullscreen()
TARGET_MISSING = "fullscreen_target_missing"    # la surface demandée n'est pas à l'écran
CANCELLED = "fullscreen_cancelled"              # armement retiré avant le clic
ARM_EXPIRED = "fullscreen_arm_expired"          # personne n'a cliqué dans l'échéance
NEEDS_GESTURE = "fullscreen_needs_gesture"      # clic requis (aussi : refus faute d'activation)
OTHER_ENTERED = "fullscreen_other_surface_entered"  # une autre surface est déjà plein écran
EXIT_FAILED = "fullscreen_exit_failed"          # exitFullscreen() a échoué
PAGE_ERROR = "fullscreen_page_error"            # exception inattendue côté page (visible et journalisée)
PAGE_CODES: tuple[str, ...] = (
    UNSUPPORTED, DENIED, TARGET_MISSING, CANCELLED, ARM_EXPIRED, NEEDS_GESTURE, OTHER_ENTERED, EXIT_FAILED, PAGE_ERROR,
)

#: Phrases rendues à l'agent : il doit pouvoir **dire** où l'on en est.
STATE_EXPLANATIONS: dict[str, str] = {
    "needs_gesture": (
        "La demande est armée : une invite est affichée à l'écran et attend UN clic de l'utilisateur "
        "(le navigateur interdit le plein écran sans geste). Ne dis pas que c'est en plein écran ; "
        "dis à l'utilisateur de cliquer sur « Passer en plein écran »."
    ),
    "entered": "La surface est en plein écran (constaté par le navigateur).",
    "exited": "La surface n'est pas en plein écran.",
    "unsupported": "Le navigateur n'offre pas le plein écran pour cette page. Rien n'a changé ; dis-le.",
    "refused": "Le navigateur a refusé le plein écran. Rien n'a changé ; dis-le sans prétendre l'inverse.",
    "expired": "L'invite est restée sans clic jusqu'à son échéance et a été retirée. Rien n'a changé.",
}

_COMMAND_ID = re.compile(r"\A[A-Za-z0-9_-]{32,64}\Z")
_OBJECT_ID = re.compile(r"\A[A-Za-z0-9._:-]{1,128}\Z")


class SurfaceFullscreenError(ValueError):
    """Refus nommé : `code` stable, `status` HTTP de la route, `command_id` court quand il y en a un."""

    def __init__(self, code: str, message: str, status: int = 400, command_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.command_id = command_id


def next_state(state: str, event: str) -> str:
    """État suivant, ou `SurfaceFullscreenError(INVALID_TRANSITION)` : jamais un état deviné."""

    try:
        return TRANSITIONS[(state, event)]
    except KeyError:
        raise SurfaceFullscreenError(
            INVALID_TRANSITION, f"transition impossible : {event!r} depuis {state!r}", 409
        ) from None


def event_for_report(current: str, reported: str) -> str:
    """L'événement que traduit un état rapporté par la page.

    `exited` rapporté pendant l'armement est un retrait (`cancel`), pas une sortie
    du navigateur : les deux ne mènent pas au même journal.
    """

    if reported == "exited":
        return "cancel" if current == "needs_gesture" else "browser_exited"
    mapping = {
        "entered": "browser_entered",
        "refused": "browser_denied",
        "expired": "deadline",
        "needs_gesture": "request_enter",
        "unsupported": "unsupported",
    }
    if reported not in mapping:
        raise SurfaceFullscreenError(BAD_RECEIPT, "state doit être " + ", ".join(STATES), 400)
    return mapping[reported]


def check_command_id(value: object) -> str:
    if not isinstance(value, str) or not _COMMAND_ID.match(value):
        raise SurfaceFullscreenError(
            UNKNOWN_COMMAND_ID, "command id must be 32 to 64 characters of [A-Za-z0-9_-]", 404
        )
    return value


def short_id(command_id: str) -> str:
    """Préfixe journalisé : relie les lignes d'une même demande sans livrer la capacité."""

    return command_id[:8]


@dataclass(frozen=True, slots=True)
class SurfaceFullscreenRequest:
    """Une demande d'entrée ou de sortie, validée.

    `object_id` : la fenêtre de scène à mettre en plein écran ; `None` = toute la scène.
    `display` : `current` | `primary` | `other` | indice entier d'écran.
    """

    action: str
    object_id: str | None = None
    display: str | int = "current"
    keys: str = "host"
    arm_s: float = ARM_DEFAULT_S

    def to_wire(self) -> dict[str, Any]:
        wire: dict[str, Any] = {"action": self.action}
        if self.action == "enter":
            wire.update(object_id=self.object_id, display=self.display, keys=self.keys, arm_s=self.arm_s)
        return wire


def parse_request(raw: object) -> SurfaceFullscreenRequest:
    """Corps de `POST /api/fullscreen/commands`. Tout champ inconnu est refusé."""

    if not isinstance(raw, dict):
        raise SurfaceFullscreenError(BAD_REQUEST, "le corps doit être un objet JSON", 400)
    unknown = set(raw) - {"action", "object_id", "display", "keys", "arm_s"}
    if unknown:
        raise SurfaceFullscreenError(BAD_REQUEST, "champ inconnu : " + ", ".join(sorted(unknown)), 400)
    action = raw.get("action")
    if action not in ACTIONS:
        raise SurfaceFullscreenError(BAD_REQUEST, "action doit être " + ", ".join(ACTIONS), 400)
    if action == "exit":
        extra = set(raw) - {"action"}
        if extra:
            raise SurfaceFullscreenError(BAD_REQUEST, "exit ne prend aucun champ : " + ", ".join(sorted(extra)), 400)
        return SurfaceFullscreenRequest(action="exit")
    object_id = raw.get("object_id")
    if object_id is not None and (not isinstance(object_id, str) or not _OBJECT_ID.match(object_id)):
        raise SurfaceFullscreenError(BAD_REQUEST, "object_id : identifiant de scène attendu ou null", 400)
    display = raw.get("display", "current")
    if isinstance(display, bool) or not (
        display in DISPLAY_NAMES or (isinstance(display, int) and 0 <= display <= MAX_DISPLAY_INDEX)
    ):
        raise SurfaceFullscreenError(
            BAD_REQUEST, f"display doit être {', '.join(DISPLAY_NAMES)} ou un indice 0..{MAX_DISPLAY_INDEX}", 400
        )
    keys = raw.get("keys", "host")
    if keys not in KEYS_POLICIES:
        raise SurfaceFullscreenError(BAD_REQUEST, "keys doit être " + ", ".join(KEYS_POLICIES), 400)
    arm_s = raw.get("arm_s", ARM_DEFAULT_S)
    if isinstance(arm_s, bool) or not isinstance(arm_s, (int, float)) or not ARM_MIN_S <= float(arm_s) <= ARM_MAX_S:
        raise SurfaceFullscreenError(BAD_REQUEST, f"arm_s doit être entre {ARM_MIN_S:g} et {ARM_MAX_S:g}", 400)
    return SurfaceFullscreenRequest("enter", object_id, display, keys, float(arm_s))


def _parse_report(raw: object, *, allowed: tuple[str, ...], what: str) -> dict[str, Any]:
    """Forme commune au reçu de remise et au rapport d'état de la page."""

    if not isinstance(raw, dict):
        raise SurfaceFullscreenError(BAD_RECEIPT, f"{what} doit être un objet JSON", 400)
    unknown = set(raw) - {"state", "code", "reason", "display_selection", "object_id", "id"}
    if unknown:
        raise SurfaceFullscreenError(BAD_RECEIPT, "champ inconnu : " + ", ".join(sorted(unknown)), 400)
    state = raw.get("state")
    if state not in allowed:
        raise SurfaceFullscreenError(BAD_RECEIPT, "state doit être " + ", ".join(allowed), 400)
    code = raw.get("code")
    if code is not None and code not in PAGE_CODES:
        raise SurfaceFullscreenError(BAD_RECEIPT, "code doit être " + ", ".join(PAGE_CODES), 400)
    if state in ("refused", "unsupported", "expired") and code is None:
        # Un refus muet remonterait comme une panne de transport : on exige sa cause.
        raise SurfaceFullscreenError(BAD_RECEIPT, f"state {state} exige un code", 400)
    reason = raw.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise SurfaceFullscreenError(BAD_RECEIPT, "reason doit être une chaîne", 400)
    selection = raw.get("display_selection", "not_requested")
    if selection not in DISPLAY_SELECTIONS:
        raise SurfaceFullscreenError(BAD_RECEIPT, "display_selection doit être " + ", ".join(DISPLAY_SELECTIONS), 400)
    object_id = raw.get("object_id")
    if object_id is not None and (not isinstance(object_id, str) or not _OBJECT_ID.match(object_id)):
        raise SurfaceFullscreenError(BAD_RECEIPT, "object_id : identifiant de scène attendu ou null", 400)
    request_id = raw.get("id")
    if request_id is not None and not (isinstance(request_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{8}", request_id)):
        raise SurfaceFullscreenError(BAD_RECEIPT, "id : préfixe court de 8 caractères attendu", 400)
    return {
        "state": state,
        "code": code,
        "reason": reason[:MAX_REASON_CHARS] if isinstance(reason, str) else None,
        "display_selection": selection,
        "object_id": object_id,
        "id": request_id,
    }


def parse_receipt(action: str, raw: object) -> dict[str, Any]:
    """Reçu de remise : ce que la page a constaté juste après avoir pris la commande.

    `enter` : `needs_gesture` (armé), `entered` (déjà plein écran), `unsupported`, `refused`.
    `exit` : `exited`, ou `refused`/`entered` si la sortie a échoué.
    """

    allowed = ("needs_gesture", "entered", "unsupported", "refused") if action == "enter" else ("exited", "entered", "refused")
    return _parse_report(raw, allowed=allowed, what="le reçu")


def parse_state_report(raw: object) -> dict[str, Any]:
    """Corps de `POST /api/fullscreen/state` : une transition constatée par la page."""

    return _parse_report(raw, allowed=STATES, what="le rapport")

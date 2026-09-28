"""Séance de calibration vue par le Control Center (tâche adaptative, Slice 06, décisions 50 et 53).

La séance **vit dans la page** (décision 41 : mesures, retours, hypothèses ne la
quittent pas). Le serveur n'en tient que ce dont il a besoin pour trois
décisions qui ne peuvent pas attendre la page :

1. **le mode du cerveau** : un tour reçu pendant une séance ouverte porte le
   drapeau `calibration` et la consigne du mode (`build_agent_brief`) ;
2. **la porte des outils** : une commande `calibration_*` hors séance est
   refusée (`barehands_calibration_inactive`) avant toute attente ;
3. **l'accord de l'utilisateur** : `calibration_accept_trial` exige que la
   citation que le cerveau donne ait été **dite** par l'utilisateur, dans un
   tour reçu **après** l'application de l'essai en cours.

La page déclare la séance (`POST /api/barehands/calibration-session`) à son
ouverture, la confirme toutes les `HEARTBEAT_S` et la ferme à sa sortie. Sans
nouvelle depuis `SESSION_TTL_S`, elle est échue — un onglet tué ne laisse pas le
cerveau en mode calibration.

**Ce qui est gardé des paroles.** Les dernières phrases de l'utilisateur, en
mémoire seulement, pendant la séance seulement, pour la vérification d'accord ;
effacées à la fin de la séance. Jamais journalisées (le journal ne porte que
leur nombre et leur longueur), jamais écrites sur disque.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import re
import time
from typing import Any

from jarvis.domain.barehands_calibration import (
    SESSION_BUSY,
    SESSION_TTL_S,
    check_session_id,
    consent_found,
)
from jarvis.domain.barehands_command import BarehandsCommandError

#: Phrases gardées pour la vérification d'accord : l'accord suit l'essai de
#: quelques tours, pas de dizaines.
UTTERANCES_MAX = 12
UTTERANCE_CHARS_MAX = 500
#: Nom d'exercice rendu par la page (identifiant d'étape du contrat).
EXERCISE_CHARS_MAX = 40
_TRIAL_REF = re.compile(r"\Atr-[0-9]{1,9}\Z")


@dataclass(slots=True)
class _Session:
    session_id: str
    opened: float
    seen: float
    exercise: str | None = None
    #: Instant (horloge du serveur) où le dernier essai **appliqué** a été reçu ;
    #: `None` sans essai en cours. C'est l'origine de la fenêtre d'accord.
    trial_applied: float | None = None
    trial_ref: str | None = None
    utterances: list[tuple[float, str]] = field(default_factory=list)


class CalibrationSessionRegistry:
    """La séance de calibration déclarée par la page, bornée dans le temps."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic, ttl_s: float = SESSION_TTL_S,
                 emit: Callable[..., None] | None = None) -> None:
        self._clock = clock
        self.ttl_s = ttl_s
        self._emit = emit
        self._session: _Session | None = None

    # ------------------------------------------------------------ page

    def report(self, session_id: object, active: object, exercise: object = None,
               trial: object = None) -> dict[str, Any]:
        """Ouverture, battement ou fermeture déclarés par la page ; rend `status()`.

        **Une séance à la fois** (décision 50, reprise QA) : tant qu'une séance
        vit, une autre page qui en déclare une est refusée
        (`barehands_calibration_session_busy`, 409) — deux calibrations qui se
        disputeraient l'agent rendraient chaque commande ambiguë (le long-poll
        la remet au premier onglet venu). La page refusée garde sa calibration,
        sans agent, et le dit.

        **L'essai en cours voyage avec le battement** (`trial` : `tr-N` ou
        `null`). Une séance recréée (échéance, Control Center redémarré) ou un
        battement qui voit un autre essai **rouvre** la fenêtre d'accord à cet
        instant : l'horloge de la page ne se traduit pas dans celle du serveur,
        donc on ne remonte pas le temps — seules les phrases dites **après** le
        battement comptent. Plus strict, jamais plus large.
        """

        sid = check_session_id(session_id)
        if not isinstance(active, bool):
            raise BarehandsCommandError("barehands_bad_request", "active : booléen attendu", 400)
        if trial is not None and not (isinstance(trial, str) and _TRIAL_REF.match(trial)):
            raise BarehandsCommandError("barehands_bad_request", "trial : tr-N ou null", 400)
        step = exercise if isinstance(exercise, str) and 0 < len(exercise) <= EXERCISE_CHARS_MAX else None
        now = self._clock()
        current = self._current(now)
        if active:
            if current is not None and current.session_id != sid:
                self._log("barehands.calibration_session_refused", "seconde séance de calibration refusée",
                          {"session": sid[:8], "holder": current.session_id[:8], "code": SESSION_BUSY})
                raise BarehandsCommandError(
                    SESSION_BUSY,
                    "Une autre page du Control Center tient déjà une séance de calibration : fermez-la d'abord.",
                    409)
            if current is None:
                current = self._session = _Session(sid, now, now, step)
                self._log("barehands.calibration_session_opened", "séance de calibration ouverte",
                          {"session": sid[:8], "exercise": step, "trial": trial})
            current.seen = now
            current.exercise = step
            if trial is None and current.trial_ref is not None:
                current.trial_applied = None
                current.trial_ref = None
            elif trial is not None and trial != current.trial_ref:
                current.trial_applied = now
                current.trial_ref = str(trial)
        elif current is not None and current.session_id == sid:
            self._close("page", now)
        return self.status()

    # ------------------------------------------------------------ lectures

    def _current(self, now: float) -> _Session | None:
        session = self._session
        if session is not None and now - session.seen > self.ttl_s:
            self._close("expired", now)
            return None
        return session

    def holder(self) -> str | None:
        """L'identifiant complet de la séance vivante (routage des commandes), ou `None`."""

        session = self._current(self._clock())
        return session.session_id if session is not None else None

    def active(self) -> bool:
        return self._current(self._clock()) is not None

    def status(self) -> dict[str, Any]:
        now = self._clock()
        session = self._current(now)
        if session is None:
            return {"active": False}
        return {"active": True, "session": session.session_id[:8], "exercise": session.exercise,
                "age_ms": round((now - session.opened) * 1000),
                "expires_in_ms": max(0, round((self.ttl_s - (now - session.seen)) * 1000)),
                "trial": session.trial_ref}

    def context(self) -> dict[str, Any] | None:
        """Le drapeau joint au tour du cerveau, ou `None` hors séance (contexte inchangé)."""

        session = self._current(self._clock())
        if session is None:
            return None
        return {"active": True, "exercise": session.exercise, "trial": session.trial_ref}

    # ------------------------------------------------------------ paroles et accord

    def note_user_turn(self, text: str) -> bool:
        """Garder la phrase de l'utilisateur pour la vérification d'accord (séance ouverte seulement)."""

        now = self._clock()
        session = self._current(now)
        if session is None or not text.strip():
            return False
        session.utterances.append((now, text[:UTTERANCE_CHARS_MAX]))
        del session.utterances[:-UTTERANCES_MAX]
        return True

    def trial_applied(self, trial_ref: str | None) -> None:
        session = self._current(self._clock())
        if session is not None:
            session.trial_applied = self._clock()
            session.trial_ref = trial_ref

    def trial_closed(self) -> None:
        session = self._current(self._clock())
        if session is not None:
            session.trial_applied = None
            session.trial_ref = None

    def consent(self, quote: str) -> tuple[bool, str]:
        """La citation a-t-elle été dite **depuis** l'essai en cours ? `(trouvée, motif)`.

        Le motif dit ce qui manque, dans les mots que le cerveau doit relayer :
        pas d'essai, rien dit depuis, ou la citation n'y est pas mot pour mot.
        """

        session = self._current(self._clock())
        if session is None:
            return False, "aucune séance de calibration ouverte"
        if session.trial_applied is None:
            return False, "aucun essai appliqué dans cette séance : il n'y a rien à garder"
        since = [said for at, said in session.utterances if at > session.trial_applied]
        if not since:
            return False, "l'utilisateur n'a rien dit depuis l'application de l'essai"
        return consent_found(quote, since)

    # ------------------------------------------------------------ fin

    def close(self, why: str = "shutdown") -> None:
        """Fermer la séance tout de suite (arrêt, Bare Hands éteint)."""

        if self._session is not None:
            self._close(why, self._clock())

    def _close(self, why: str, now: float) -> None:
        session, self._session = self._session, None
        if session is None:
            return
        self._log("barehands.calibration_session_closed", f"séance de calibration fermée ({why})",
                  {"session": session.session_id[:8], "why": why,
                   "duration_ms": round((now - session.opened) * 1000),
                   "utterances": len(session.utterances)})
        session.utterances.clear()

    def _log(self, kind: str, message: str, data: dict[str, Any]) -> None:
        if self._emit is None:
            return
        try:
            self._emit(kind, message, data=data)
        except OSError:
            pass  # intentional: a full disk must not turn a declared session into a refused one


# ---------------------------------------------------------------- événements du parcours
#
# Retour utilisateur du 28/09 : l'assistant n'apprenait la fin d'un exercice que
# si l'utilisateur lui en parlait, et ne disait rien à la fin de la calibration.
# La page envoie donc au Control Center chaque **revue** (un exercice vient de se
# terminer) et le **rapport** final (`POST /api/barehands/calibration-event`) ;
# le Control Center fait dire un accusé de réception tout de suite, puis ouvre un
# tour du cerveau avec ces résultats, dont la réponse est dite comme un relais.
# Les valeurs sont celles que l'écran affiche déjà, en texte : rien de neuf ne
# quitte la page.

#: Ce que la voix dit tout de suite, avant l'analyse du cerveau : une analyse
#: prend plusieurs secondes, et le silence pendant ce temps se lisait « il ne
#: m'a pas entendu ». Rédigé par le Control Center, pas par le cerveau : c'est
#: un accusé de réception fixe, pas une réponse.
CALIBRATION_ANALYSIS_ACK = "Tes résultats viennent d'arriver, je les analyse."
#: Bornes du corps d'un événement (la page n'envoie que des mots d'écran).
EVENT_TEXT_MAX = 200
EVENT_LINES_MAX = 16
EVENT_TYPES = frozenset({"review", "report"})
_STATUS_WORDS = {"ok": "réussi", "failed": "échoué", "skipped": "passé"}


def _clip(value: object, limit: int = EVENT_TEXT_MAX) -> str:
    return " ".join(str(value).split())[:limit] if isinstance(value, (str, int, float)) else ""


def _texts(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for text in (_clip(item) for item in value[:EVENT_LINES_MAX]) if text]


def _rows(value: object, keys: tuple[str, ...]) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    return [{key: _clip(item.get(key)) for key in keys} for item in value[:EVENT_LINES_MAX] if isinstance(item, dict)]


def parse_calibration_event(body: object) -> dict[str, Any]:
    """Le corps d'un événement de parcours, borné et réduit aux champs connus.

    Lève `BarehandsCommandError` (400) sur un corps qui n'est pas un événement :
    `type` inconnu ou séance absente. Les champs de texte inconnus sont ignorés,
    les listes tronquées, chaque texte coupé à `EVENT_TEXT_MAX`.
    """

    if not isinstance(body, dict):
        raise BarehandsCommandError("barehands_bad_request", "corps attendu : un objet", 400)
    kind = body.get("type")
    if kind not in EVENT_TYPES:
        raise BarehandsCommandError("barehands_bad_request", f"type attendu : {', '.join(sorted(EVENT_TYPES))}", 400)
    event: dict[str, Any] = {"type": kind, "session": check_session_id(body.get("session"))}
    if kind == "review":
        stage = body.get("stage")
        event.update({
            "stage": stage if isinstance(stage, str) and 0 < len(stage) <= EXERCISE_CHARS_MAX else None,
            "label": _clip(body.get("label")),
            "status": body.get("status") if body.get("status") in _STATUS_WORDS else None,
            "reason": _clip(body.get("reason")),
            "attempt": body.get("attempt") if isinstance(body.get("attempt"), int) and not isinstance(body.get("attempt"), bool) else 1,
            "held": body.get("held") is True,
            "lines": _rows(body.get("lines"), ("label", "text")),
        })
    else:
        event.update({
            "saving": body.get("saving") is True,
            "stages": _rows(body.get("stages"), ("label", "status", "detail")),
            "will_save": _texts(body.get("willSave")),
            "kept": _texts(body.get("kept")),
            "trials": _texts(body.get("trials")),
        })
    return event


_EVENT_HEADER = (
    "[Événement de la calibration — personne n'a parlé : c'est l'écran qui t'écrit]\n"
    f"L'utilisateur vient d'entendre « {CALIBRATION_ANALYSIS_ACK} » : ne le redis pas, commence par ton analyse."
)
_EVENT_RULES = (
    "Réponds dans ce tour, toi-même, sans sous-agent. Les valeurs ci-dessus sont celles que l'écran affiche : "
    "tu peux les citer telles quelles, sans les arrondir ni en calculer d'autres ; calibration_status donne le "
    "détail si tu en as besoin. Pour cette analyse : trois phrases au plus, quarante-cinq mots au plus, en mots "
    "d'utilisateur, sans nom de paramètre."
)


def render_calibration_event(event: dict[str, Any]) -> str:
    """La demande que le cerveau reçoit pour un événement de parcours (texte français)."""

    lines = [_EVENT_HEADER]
    if event["type"] == "review":
        label = event.get("label") or event.get("stage") or "l'exercice"
        status = _STATUS_WORDS.get(event.get("status") or "", "terminé")
        attempt = event.get("attempt") or 1
        head = f"L'exercice « {label} » vient de se terminer : {status}"
        if attempt > 1:
            head += f" (essai n° {attempt})"
        if event.get("reason"):
            head += f", motif : {event['reason']}"
        lines.append(head + ". L'écran est sur sa revue et attend une décision.")
        if event.get("lines"):
            lines.append("Ce qui a été mesuré :")
            lines.extend(f"- {row['label']} : {row['text']}" for row in event["lines"] if row.get("label"))
        else:
            lines.append("Aucune mesure chiffrée pour cet exercice : il se juge sur le geste lui-même.")
        if event.get("held"):
            lines.append("Un réglage d'essai attend d'être jugé sur cet exercice : ces mesures ont été prises sous lui.")
        lines.append(
            "Analyse ces résultats pour l'utilisateur :\n"
            "- d'abord ton verdict : tout va bien, ou ce qu'il a probablement ressenti (un léger retard, un clic "
            "qui part trop tôt ou pas du tout, un relâchement qui colle, un pointeur qui tremble…) et pourquoi, "
            "d'après ces valeurs ;\n"
            "- puis ta proposition : passer à la suite, refaire l'exercice, ou un changement que tu expliques par "
            "ce qu'il sentira de différent (par exemple « il faudra rapprocher un peu plus le pouce et l'index "
            "pour que le clic parte ») ;\n"
            "- termine par une question simple (« on passe à la suite ? », « j'essaie ce réglage ? »). "
            "N'applique aucun essai et n'avance pas le parcours sans sa réponse ; tu peux noter la piste "
            "(calibration_propose_hypothesis)."
        )
    else:
        lines.append("La calibration est terminée : l'écran montre le rapport final.")
        if event.get("stages"):
            lines.append("Exercice par exercice :")
            lines.extend(f"- {row['label']} : {row['detail'] or row['status']}" for row in event["stages"] if row.get("label"))
        if event.get("will_save"):
            lines.append("« Enregistrer » rangera : " + " ; ".join(event["will_save"]) + ".")
        elif not event.get("saving"):
            lines.append("Aucune mesure n'a été retenue : il n'y a rien à enregistrer.")
        if event.get("kept"):
            lines.append("Conservé du profil d'avant : " + " ; ".join(event["kept"]) + ".")
        if event.get("trials"):
            lines.append("Réglages déjà gardés pendant la séance : " + " ; ".join(event["trials"]) + ".")
        lines.append(
            "Fais-lui le bilan : ce qui va bien, ce qui reste fragile s'il y en a, et dis-lui que « Enregistrer » "
            "range ces mesures (ou qu'il n'y a rien à enregistrer). Termine en lui demandant s'il enregistre."
        )
    lines.append(_EVENT_RULES)
    return "\n".join(lines)

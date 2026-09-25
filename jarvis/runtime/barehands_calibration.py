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
